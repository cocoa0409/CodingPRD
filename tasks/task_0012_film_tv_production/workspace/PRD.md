# Film TV Production API — Product Requirements Document

## 1. Introduction

Film and television production is a high-stakes coordination problem: a single feature or limited series simultaneously juggles a script broken down into scores of scenes, a casting funnel that moves talent from open auditions through signed contracts, a constellation of physical locations whose permits and weather windows can collapse without warning, a fleet of camera, lighting, sound, and grip equipment that must be tracked from check-out through return verification, and a multi-million-dollar budget whose every line item is contested by line producers, finance controllers, and external vendors. When any one of these threads goes silent — when a permit lapses unobserved, when an actor is double-booked across two productions, when reserve fund draws bypass dual-control approval — the cost ripples through every other thread, and the show falls behind schedule or over budget within days.

This document specifies the contract for a back-end service that brings these threads under a single, auditable system of record. The service governs the production lifecycle from greenlight through final account closure, enforces segregation of duties between the producers who request budget changes and the controllers who approve them, detects scheduling conflicts both within a single project and across an actor's full slate of signed work, and emits authoritative events to downstream payment, contract, and finance systems. Every schedule change and budget adjustment is recorded for audit. The system is the source of truth for whether a production is `GREEN`, `YELLOW`, `RED`, or `FROZEN`, and a `RED` posture progressively narrows what operations remain permissible until the underlying budget condition is repaired.

The reader of this document is the engineer implementing the API. The intended consumers are five distinct human roles whose responsibilities are deliberately partitioned, plus a small set of test-driving capabilities that allow integration suites to advance the logical clock and inject simulated external events.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, declaring which of the system's roles that principal is acting under. If either header is missing or blank, the request is rejected with `ERR_AUTH_REQUIRED` and HTTP 401. If the supplied role is not authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

Five roles are recognized, spelled exactly as follows:

- **`ExecutiveProducer`** — top-level authority who creates productions, cancels them, reads audit logs, and drives the test-only clock and event simulators.
- **`LineProducer`** — day-to-day producer responsible for scene breakdown, baseline lock, casting sign, change-order submission, crew assignments, and the begin-wrap transition.
- **`FinanceController`** — owner of budget approval, vendor invoice lifecycle, equipment financial closure, and final account closure. By design, a `FinanceController` cannot submit change orders; that is reserved for `LineProducer`. This is the system's primary segregation-of-duties boundary.
- **`CastingDirector`** — owner of the casting funnel: roles, auditions, shortlisting, offers, recasting, and reopening auditions. Also creates `Actor` records.
- **`ProductionCoordinator`** — operational role responsible for locations, reservations, permit and weather status updates, scene shoot tracking, and the non-financial equipment events (`CHECK_OUT`, `CHECK_IN`, `REPORT_DAMAGE`, `REPORT_LOSS`).

For every role in this system, the value of `X-User-ID` is an opaque operator identifier and is **not** the primary key of any entity stored by the API. The server treats it as an external principal handle: it may be recorded on entities — for example as `requested_by` and `approved_by` on `ChangeOrder`, as `actor_user_id` on `EquipmentEvent` and `AuditLog`, or as `crew_user_id` on `CrewAssignment` — but ownership checks compare the recorded identifier to `X-User-ID` directly without dereferencing it to any persisted record. This convention applies to all five roles: `ExecutiveProducer`, `LineProducer`, `FinanceController`, `CastingDirector`, and `ProductionCoordinator`.

The detailed role-to-endpoint matrix is summarized in §4. Three further rules govern access checks across the catalogue:

- A header pair that passes the existence check but is not in the permitted role set for the endpoint yields `ERR_FORBIDDEN`.
- For change-order approval, even when the role is `FinanceController`, the call is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) if the approver's `X-User-ID` equals the `requested_by` value recorded on the change order.
- For change-order cancellation, the call is permitted only when `X-User-ID` equals `requested_by`; the originating `LineProducer` is the only principal who may withdraw a pending request.

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

Every list endpoint accepts two optional query-string parameters, `limit` and `offset`. The default value of `limit` is 10; valid values are integers from 1 through 100 inclusive. The default value of `offset` is 0, and any non-negative integer is accepted. Out-of-bounds values are rejected with `ERR_INVALID_PAGINATION` (HTTP 422).

List results are sorted by `created_at` in ascending order. Each list response carries the four pagination fields inside `meta`: `limit` (the limit applied), `offset` (the offset applied), `total_count` (the total number of records that match the query), and `has_more` (true if more records remain beyond this page).

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource in this system is identified by a server-minted `id` that is a UUID. The `id` is opaque and carries no type prefix; clients distinguish resource types by the endpoint path that returned the value, not by the shape of the identifier. All datetimes — including `created_at`, `updated_at`, the `audition_at` of an `Audition`, the `start_at`/`end_at` of a reservation, the `occurred_at` of an `EquipmentEvent`, the `signed_at` of a `Role`, the `schedule_baseline_locked_at` of a `Production`, and the `now` field of the system `Clock` — are ISO 8601 strings in UTC with exactly three fractional digits.

Most entities carry the four common system fields: `id`, `created_at`, `updated_at`, and `version`. The `version` is an integer that begins at 1 on creation and is incremented by exactly 1 every time the entity is mutated; `updated_at` is refreshed to the current logical clock time on every mutation. Three entities — `Audition`, `EquipmentEvent`, and `AuditLog`, plus the singleton `Clock` — are append-only and carry only `id` and `created_at`; they have no `updated_at` and no `version`, because they are never mutated after the initial write.

Optimistic concurrency control is offered on every state-changing endpoint that accepts a `version` field in its request body. The semantics are: if the client supplies `version`, it is compared against the current `version` of the target resource and a mismatch yields `ERR_VERSION_MISMATCH` (HTTP 409); if the client omits `version`, the check is skipped and the operation proceeds against the current resource state. Clients that need linearizability against a specific snapshot must therefore include `version`; clients that explicitly want last-writer-wins semantics may omit it.

Resources that are created return HTTP 201 with the newly created resource as the `data` payload. State-transition endpoints and other modifications return HTTP 200 with the updated resource. Read endpoints return HTTP 200.

### 2.5. Nested Resource Path Resolution

Many endpoints are nested — for example a scene reschedule lives at `/productions/{pid}/scenes/{sid}/reschedule`, and an audition list lives at `/productions/{pid}/roles/{rid}/auditions`. Path parameters are validated **left to right**: first the production identified by `{pid}` must exist, then the nested resource (scene, role) identified by the next segment must exist *and must belong to that production*. A scene that exists in the database but is parented to a different production yields `ERR_NOT_FOUND` against the supplied `{pid}`, not `ERR_REFERENCE_MISMATCH`, because path resolution is treated as an existence question first. `ERR_REFERENCE_MISMATCH` (HTTP 422) is reserved for foreign-key fields supplied in request bodies — for instance a `LocationReservation` whose `scene_id` belongs to one production but is submitted under a `production_id` belonging to another.

### 2.6. Production Posture and Operation Gating

A production carries a derived `posture` that summarizes the joint health of its budget categories. The posture takes one of four values: `GREEN`, `YELLOW`, `RED`, or `FROZEN`. The evaluation rule is as follows, and is recomputed after any change-order approval, vendor-invoice reconcile or pay, equipment damage or loss event, baseline lock, or contract sign:

- If the production's lifecycle `status` is `WRAP_PENDING`, posture is `FROZEN` until the production reaches `WRAPPED`.
- Otherwise, if any `BudgetCategory` of the production has `alert_state` equal to `OVER`, posture is `RED`.
- Otherwise, if any `BudgetCategory` has `alert_state` equal to `WARN`, posture is `YELLOW`.
- Otherwise, posture is `GREEN`.

A `FROZEN` posture gates all non-wrap-progression operations: any mutation other than the wrap-progression endpoints is rejected with `ERR_POSTURE_BLOCKED` (HTTP 409). A `RED` posture additionally gates approval of `RESERVE_DRAW` change orders: such approvals are rejected with `ERR_POSTURE_BLOCKED` unless the approver supplies the `X-Override-Reason` header with a non-empty value. The two snapshots of posture diverge in a subtle way that the implementer must respect: the value returned by reads on a production is a fresh evaluation against current data and is not persisted; the value written to the production's `posture` column is updated only on the qualifying side-effects listed above, and the persisted-eval write additionally emits an `AuditLog` entry with action `BUDGET_ADJUSTMENT` whenever the persisted posture transitions to `RED`.

### 2.7. Budget Category Alert State and Threshold Semantics

Each `BudgetCategory` carries a derived `alert_state` of `OK`, `WARN`, or `OVER`. The state is recomputed after any mutation to its `committed_cents`, `actual_cents`, or `planned_cents`. The rule is utilization-based: utilization is the sum of `committed_cents` and `actual_cents` divided by `planned_cents` when `planned_cents` is greater than zero, and zero when `planned_cents` is zero. If utilization is strictly greater than 1.00 the category is `OVER`; otherwise if utilization is at least 0.90 the category is `WARN`; otherwise the category is `OK`. The boundary is deliberately asymmetric — utilization of exactly 1.00 maps to `WARN`, not `OVER` — because a category that has consumed exactly its plan is not yet *over* it. Recomputation triggered by change-order approval scopes to the target category only; recomputation triggered by vendor-invoice reconcile or pay scopes to the invoice's `category_code`.

### 2.8. Monetary Precision and Rounding

All monetary quantities are integers expressed in cents. Where calculations involve a multiplication by a fractional rate (notably the overtime multipliers in crew payroll), the result is rounded **half up** to the nearest integer cent, applied **per component before summation**. Division and ceiling operations on time quantities (notably the conversion of scene minutes into shoot days) round **up** to the nearest whole unit.

### 2.9. Cascading Side Effects and Audit Logging

A small number of operations in this system intentionally fan out into multi-entity cascades. Whenever such a cascade fires, every affected entity has its `updated_at` refreshed and its `version` incremented by 1. The cascade is described in the workflow that triggers it; the implementer must apply every documented secondary effect and not just the primary state transition.

Every schedule change, budget adjustment, reserve draw, contract signing, equipment loss event, and wrap close generates an `AuditLog` row carrying the acting user (`actor_user_id`), the affected entity name (`subject_entity`) and identifier (`subject_id`), the pre-mutation snapshot (`before_json`), the post-mutation snapshot (`after_json`), and the mutation timestamp (`occurred_at`). The recognized values for `action` are `SCHEDULE_CHANGE`, `BUDGET_ADJUSTMENT`, `RESERVE_DRAW`, `CONTRACT_SIGNED`, `EQUIPMENT_LOSS`, and `WRAP_CLOSE`; the workflow narratives in §3 indicate which action attaches to which transition.

### 2.10. Validation Priority

When several of the validations defined in this document apply to the same endpoint, they are evaluated in a fixed priority order so that two implementations exercising the same misbehaving request return the same `error_id`. The order is, from highest priority to lowest:

1. **Authentication** — missing or blank `X-User-ID` / `X-User-Role` (`ERR_AUTH_REQUIRED`).
2. **Authorization** — supplied role not in the endpoint's permitted set (`ERR_FORBIDDEN`).
3. **Existence** — every path-parameter resource (`Production`, `Scene`, `Role`, `Audition`, `Location`, `LocationReservation`, `BudgetCategory`, `ChangeOrder`, `Equipment`, `EquipmentEvent`, `VendorInvoice`, `CrewAssignment`, `Actor`) resolved left-to-right; first-missing yields `ERR_NOT_FOUND`.
4. **OCC** — when the request body carries a `version`, mismatch yields `ERR_VERSION_MISMATCH`.
5. **State** — target entity must be in a state that permits the requested transition (`ERR_INVALID_STATE`).
6. **Posture gate** — production posture `FROZEN` blocks non-wrap operations; production posture `RED` blocks `RESERVE_DRAW` change-order approvals unless `X-Override-Reason` is present (`ERR_POSTURE_BLOCKED`).
7. **Segregation of duties** — `ChangeOrder` approver must differ from requester (`ERR_SEGREGATION_OF_DUTIES`).
8. **Referential scope** — every foreign key in the body resolves to an entity in the expected scope (`ERR_REFERENCE_MISMATCH`).
9. **Domain-specific business constraints** — interval semantics, permit, capacity, weather, audition, actor conflicts, equipment availability, equipment event payload, budget allocation, reserve sufficiency, open obligations, pagination bounds — all evaluated after the higher-priority gates above have passed.

The earliest failing rule in this list determines the response; lower-priority rules are not evaluated. The pagination check (`ERR_INVALID_PAGINATION`) applies to every list endpoint and is evaluated after the auth and authorization checks but before any data is read. Generic request-body shape failures — required fields missing, wrong JSON types, malformed enum values — are reported as `ERR_VALIDATION` (HTTP 422); this is the catch-all body-shape error and is evaluated alongside the body-level business validations.

## 3. Business Logic & Workflows

### 3.1. Production Greenlight and Schedule Baseline Lock

A new production is created by an `ExecutiveProducer`. The creation payload identifies the project by its `title`, declares its `production_type` as one of `FILM`, `TV_SERIES`, `DOCUMENTARY`, or `COMMERCIAL`, fixes the outer envelope of available shoot days via `shoot_window_start` and `shoot_window_end`, and pins the financial envelope via `total_budget_cents` and `reserve_fund_cents`. The reserve must be a non-negative amount no larger than the total budget. On creation, the production's lifecycle `status` is initialized to `PLANNING`, its `posture` is initialized to `GREEN`, the `schedule_baseline_locked_at` cursor is unset, and the three rolling totals — `spent_cents`, `committed_cents`, and `residual_cents` — are initialized to zero. Two productions cannot share a `title` while both are in active (non-cancelled, non-wrapped) state; the `title` is bounded to 1 through 200 characters.

During `PLANNING`, the production is assembled. Scenes are broken down, casting roles are opened, locations are reserved, equipment is registered, crew is booked, and budget categories are allocated. Each `BudgetCategory` belongs to a `code` drawn from `CAST`, `CREW`, `EQUIPMENT`, `LOCATION`, `POST`, and `MISC`, and is created with an initial `planned_cents`. The sum of `planned_cents` across all categories of a production, plus the `reserve_fund_cents`, must never exceed the `total_budget_cents`; an attempt to create or change-order a category that would breach this cap is rejected with `ERR_BUDGET_OVERALLOCATED` (HTTP 422).

When the `LineProducer` is satisfied that the production is ready to start shooting, they lock the schedule baseline. The lock requires three preconditions: `schedule_baseline_locked_at` must still be unset (a baseline can only be locked once), at least one scene must already be in the `SCHEDULED` state, and the sum of all categories' `planned_cents` must not exceed `total_budget_cents` minus `reserve_fund_cents`. On success, `schedule_baseline_locked_at` is stamped with the current logical clock value, the production transitions `PLANNING → IN_PRODUCTION`, every `CrewAssignment` belonging to the production transitions from `BOOKED` to `ACTIVE` (cascading on the production transition), and posture is recomputed. Each crew transition adds the crew member's `day_rate_cents` multiplied by their `scheduled_days` to the `EQUIPMENT`-distinct `CREW` budget category's `committed_cents`. An `AuditLog` row with action `SCHEDULE_CHANGE` is appended.

### 3.2. The Casting Funnel

Casting begins when a `CastingDirector` opens a role under a production with the supplied `role_name`, `description`, `union_tier` (one of `PRINCIPAL`, `SUPPORTING`, or `FEATURED_BACKGROUND`), and contracted `day_rate_cents`. A new `Role` is created in `casting_status` `OPEN`. The actors auditioning for that role are tracked separately: an `Actor` record carries `legal_name`, `agency_contact_email`, and `travel_origin_zone` — the last of which is used downstream by the travel-buffer calculation that detects scheduling conflicts. Each `Actor` also carries an `active` flag, which begins true and is used for soft archival of records that are no longer in service.

When the first audition is recorded against a role, the role auto-advances from `OPEN` to `AUDITIONING`. Each audition is parented to the role through its `role_id` and captures the candidate `actor_id`, the scheduled `audition_at`, the panel's `outcome` (one of `PASS`, `REJECT`, or `CALLBACK`), and free-text `notes`. After at least one audition records `outcome` of `PASS`, the casting director may shortlist the role, transitioning `AUDITIONING → SHORTLISTED`. A shortlisted role can be reopened — `SHORTLISTED → AUDITIONING` — provided the production is still in `PLANNING`.

Making an offer transitions the role from `SHORTLISTED` to `OFFERED`; the offer carries the `actor_id` of the chosen candidate. The actor must already have a `PASS` audition recorded on this exact role, otherwise the call is rejected with `ERR_AUDITION_NOT_PASSED` (HTTP 422). Either before or after offering, a casting director may abandon the role by recasting it (`AUDITIONING → RECAST`).

Signing the contract — `OFFERED → SIGNED` — is the moment cost commitment crystallizes, and is reserved for the `LineProducer`. Two preconditions are checked at sign time. First, the chosen actor must have no scene call-sheet conflict on any scene that lists this role in its `required_actor_role_ids` (the same logic applied at scene-schedule time, including the cross-project pass; see §3.4). Second, the `CAST` budget category must have remaining headroom for the projected commitment — `planned_cents` minus `committed_cents` minus `actual_cents` must be at least the projected `CAST` commit value computed by the rule below; if not, the sign fails with `ERR_BUDGET_OVERALLOCATED`. On success, the role's `signed_actor_id` and `signed_at` are stamped, the projected commitment is added to the `CAST` category's `committed_cents`, the role transitions to `SIGNED`, the `contract.role.signed` event is emitted, posture is recomputed (cascade), and an `AuditLog` row with action `CONTRACT_SIGNED` is appended.

Two `OFFERED → SIGNED` calls landing concurrently on the same role serialize so that exactly one wins; the loser receives `ERR_INVALID_STATE` because the race resolves at the level of `Role.casting_status` and the second writer encounters a state already advanced to `SIGNED`.

The projected `CAST` commit at sign time is computed as follows. For each scene of the production whose `required_actor_role_ids` includes this role and whose scene `status` is in the set `BREAKDOWN`, `SCHEDULED`, or `RESCHEDULING` (scenes already in `SHOT` or `OMITTED` are excluded), the system computes the scene's projected work-days by dividing `planned_duration_minutes` by 480 minutes per shoot day and rounding up to the next whole day. Those per-scene work-days are summed, then capped at the union-tier ceiling: 60 days for `PRINCIPAL`, 30 days for `SUPPORTING`, and 10 days for `FEATURED_BACKGROUND`. The capped day count is multiplied by the role's `day_rate_cents` to yield the projected commitment in integer cents (no further rounding step is applied beyond the round-up already performed on each scene). A separate read-only forecast variant of this same calculation — used for posture display while the role is merely `OFFERED` — uses the *same* multiplication and cap but considers **all** scenes of the role regardless of status, and is therefore typically larger; the value persisted as the `committed_cents` delta on the `OFFERED → SIGNED` transition is the smaller, status-filtered variant.

A signed role can later be substituted (`SIGNED → RECAST`) by a `LineProducer` provided the production is in `PLANNING` or `IN_PRODUCTION`. The substitute payload carries `replacement_actor_id`, `replacement_role_name`, and `replacement_day_rate_cents`. The replacement must be a different `Actor` from the originally signed one and must clear all scheduling-conflict checks. On success, the previously projected `CAST` commit (computed under the original role) is decremented from the `CAST` category's `committed_cents`, a fresh `Role` record is created carrying the replacement values and is immediately signed in-line (its own projected commit is added to `CAST.committed_cents`), the `contract.role.substituted` event is emitted, and an `AuditLog` row with action `CONTRACT_SIGNED` is appended.

### 3.3. Locations, Reservations, Permits, and Weather

A `ProductionCoordinator` registers physical locations. Each `Location` carries a human-readable `name`, the geographic `zone` it sits in (using the same zone identifier semantics as `Actor.travel_origin_zone`), a flag `requires_permit` indicating whether shoots there need permit clearance, and the integer `max_parallel_units` declaring how many distinct shooting units (`MAIN`, `B_UNIT`, `SECOND`, etc.) may operate at the same time at that location.

A reservation binds a location, a production, and a specific scene to a time window. The create payload carries `location_id`, `production_id`, `scene_id`, the shooting `unit_label`, the inclusive `start_at`, and the exclusive `end_at`. Five validation checks fire on creation, in priority order after the upstream auth and existence checks:

- The interval must satisfy `start_at` strictly earlier than `end_at`, and both must fall within the production's `shoot_window_start` and `shoot_window_end`. Violations yield `ERR_INVALID_INTERVAL` (HTTP 422).
- The scene's parent production must equal the supplied `production_id`. A foreign-key mismatch (e.g., a scene from production A being reserved under production B) yields `ERR_REFERENCE_MISMATCH` (HTTP 422).
- The set of overlapping reservations at the same `location_id` (two reservations overlap when the half-open interval from each candidate's `start_at` inclusive to its `end_at` exclusive intersects, and the candidate is in `HELD`, `CONFIRMED`, or `RESCHEDULING`) must contain fewer than `max_parallel_units` rows; if accepting this reservation would tie or exceed the cap, the create is rejected with `ERR_LOCATION_OVER_CAPACITY` (HTTP 409).
- The `unit_label` must be unique among all currently-overlapping reservations at the same location; two simultaneous create requests racing for the last available unit slot serialize so that exactly one wins, and the loser also receives `ERR_LOCATION_OVER_CAPACITY`.

A new reservation lands in `HELD`. Its `permit_status` is initialized to `PENDING` if the location's `requires_permit` is true, and `NOT_REQUIRED` otherwise. Its `weather_status` is initialized to `UNKNOWN`. The coordinator may update `permit_status` to `APPROVED`, `REJECTED`, or `EXPIRED` via the dedicated patch endpoint, and may update `weather_status` to `ACCEPTABLE` or `BLOCKED` via the corresponding patch.

Confirming a reservation transitions it from `HELD` to `CONFIRMED`. Two preconditions apply: if the underlying location's `requires_permit` is true, the reservation's `permit_status` must equal `APPROVED` (otherwise `ERR_PERMIT_REQUIRED`, HTTP 409); and the reservation's `weather_status` must not be `BLOCKED` (otherwise `ERR_WEATHER_BLOCKED`, HTTP 409). The capacity check repeats at confirm time — confirming a held reservation that would now violate `max_parallel_units` because peer reservations were upgraded in the meantime is rejected with `ERR_LOCATION_OVER_CAPACITY`. A reservation may instead be released from `HELD` to `RELEASED` at any time. Reservations also undergo system-driven transitions (`CONFIRMED → RESCHEDULING`, `RESCHEDULING → RELEASED`, `CONFIRMED → FULFILLED`) that are cascaded by scene-state changes; see §3.4.

### 3.4. Scene Scheduling, Conflicts, and the Travel Buffer

A scene is a script-breakdown entry created by the `LineProducer` under a production. The payload supplies `scene_number` (the script identifier, unique within the production), the interior/exterior classification `int_ext` (one of `INT`, `EXT`, or `INT_EXT`), the `planned_duration_minutes` (a value between 1 and 720 minutes inclusive), the list of `required_actor_role_ids`, the list of `required_equipment_categories` drawn from `CAMERA`, `LIGHTING`, `SOUND`, `GRIP`, `WARDROBE`, `PROPS`, and `MISC`, and the boolean `weather_dependent` flag (defaulting to false). The new scene begins in `BREAKDOWN`.

Scheduling a scene transitions it `BREAKDOWN → SCHEDULED`. The request carries the target `reservation_id`, plus the optional `version` for optimistic concurrency. Three preconditions hold. First, the reservation referenced by `reservation_id` must currently be in `HELD` or `CONFIRMED` and its `scene_id` must match the scene being scheduled; reservations bound to other scenes are not eligible. Second, every role listed in the scene's `required_actor_role_ids` whose `casting_status` is `SIGNED` must clear both actor scheduling conflict checks (described below). Third, if the scene is `weather_dependent`, the reservation's `weather_status` must already be `ACCEPTABLE`; a weather-blocked reservation is rejected with `ERR_WEATHER_BLOCKED`. On success, the reservation is upgraded to `CONFIRMED` if it was still `HELD`, and an `AuditLog` row with action `SCHEDULE_CHANGE` is appended.

The actor scheduling conflict check has two flavors. The **same-production** check (validation priority 14, error `ERR_ACTOR_CALLSHEET_CONFLICT`) compares this scene's reservation against every other scene of the same production whose call sheet features the same signed actor: their reservation intervals must not overlap, and the gap between them must satisfy the travel buffer described below. The **cross-production** check (validation priority 15, error `ERR_CROSS_PROJECT_CONFLICT`) extends the same comparison to every other active production (production lifecycle `status` is `PLANNING` or `IN_PRODUCTION`) on which the actor is signed; intervals across productions must also not overlap, and the same travel buffer applies. Both checks run at scene schedule and scene reschedule time; the cross-project check additionally runs at role sign time.

The travel buffer between two consecutive reservations featuring the same actor is determined by zone comparison. If the prior `Location.zone` equals the next `Location.zone`, the required buffer is 60 minutes. If the zones differ, the required buffer is 240 minutes — that is, four hours of cross-zone transit. The buffer is required after the prior reservation's `end_at` (exclusive) and before the next reservation's `start_at` (inclusive); the conflict condition is precisely that the next reservation's `start_at` is strictly less than the prior reservation's `end_at` plus the required buffer. The same buffer constants apply to both the same-production and cross-production variants of the check.

When weather forecasts deteriorate, the `ProductionCoordinator` may mark a scheduled scene weather-blocked, transitioning it `SCHEDULED → RESCHEDULING`. Two preconditions hold: the scene must be `weather_dependent`, and its linked reservation's `weather_status` must currently be `BLOCKED`. The cascade transitions the linked reservation `CONFIRMED → RESCHEDULING` and appends an `AuditLog` action `SCHEDULE_CHANGE`. The coordinator then reschedules the scene by supplying a `new_reservation_id` whose `weather_status` is `ACCEPTABLE`; this transitions the scene `RESCHEDULING → SCHEDULED`, cascades the **old** reservation `RESCHEDULING → RELEASED`, advances the **new** reservation from `HELD` or `CONFIRMED` to `CONFIRMED`, and appends a further `SCHEDULE_CHANGE` audit row. The same actor conflict checks rerun on the new reservation.

When the unit captures the scene on the day, the coordinator marks the scene shot, transitioning it `SCHEDULED → SHOT`. Preconditions: the parent production is in `IN_PRODUCTION` and the linked reservation is `CONFIRMED`. The cascade upgrades the reservation `CONFIRMED → FULFILLED`. The `LineProducer` may also omit a scene, transitioning it `BREAKDOWN → OMITTED` (no preconditions) or `SCHEDULED → OMITTED` (only while the production is still in `PLANNING`); the latter cascades the linked reservation `CONFIRMED → RELEASED` and writes `SCHEDULE_CHANGE`.

### 3.5. Equipment, Rentals, and Damage Reconciliation

Equipment is registered by a `ProductionCoordinator` and lives in a global inventory shared across productions. Each `Equipment` record carries a `name`, a `category` (one of `CAMERA`, `LIGHTING`, `SOUND`, `GRIP`, `WARDROBE`, `PROPS`, `MISC`), an `acquisition_mode` of either `RENTAL` or `PURCHASE`, the opaque `vendor_id` of the supplier, and the `unit_cost_cents` that will be charged (this is the daily rate for `RENTAL` items, or the one-time price for `PURCHASE`). The denormalized `last_check_event_id` cursor records the most recent `EquipmentEvent.id`.

State transitions on equipment are driven exclusively by `EquipmentEvent` rows. Each event carries the `equipment_id`, the `production_id` it is associated with, an `event_type` of `CHECK_OUT`, `CHECK_IN`, `REPORT_DAMAGE`, `REPORT_LOSS`, or `RETURN_VERIFIED`, the recorded `occurred_at` timestamp, the `actor_user_id` of the operator, and the `damage_charge_cents` (mandatorily zero for non-loss/non-damage events; mandatorily strictly greater than zero for damage and loss events). A payload that violates these `damage_charge_cents` rules is rejected with `ERR_INVALID_EVENT_PAYLOAD` (HTTP 422).

Checking equipment out transitions it `AVAILABLE → CHECKED_OUT`. Preconditions: no other record on this exact `id` is currently `CHECKED_OUT` (a second `CHECK_OUT` against an already-checked-out item is `ERR_EQUIPMENT_UNAVAILABLE`), and the production is in `PLANNING` or `IN_PRODUCTION`. Side effect: if the equipment is `RENTAL`, the equipment's `unit_cost_cents` is added to the `EQUIPMENT` budget category's `committed_cents`. Two simultaneous `CHECK_OUT` events on the same equipment serialize so that exactly one succeeds; the loser receives `ERR_EQUIPMENT_UNAVAILABLE`.

Checking equipment back in transitions it `CHECKED_OUT → AVAILABLE`. Side effect for `RENTAL`: the `unit_cost_cents` from the matching `CHECK_OUT` is subtracted from the `EQUIPMENT` category's `committed_cents`, and the same amount is added to the category's `actual_cents` — closing out that day's rental as actual spend.

If equipment is damaged or lost while checked out, the coordinator records `REPORT_DAMAGE` (transitioning `CHECKED_OUT → DAMAGED`) or `REPORT_LOSS` (transitioning `CHECKED_OUT → LOST`). Each fires the same financial cascade: the event's `damage_charge_cents` is added to the `EQUIPMENT` category's `committed_cents`, and an `AuditLog` row with action `EQUIPMENT_LOSS` is appended.

Recovering damaged or lost equipment is the `FinanceController`'s responsibility. Recording a `RETURN_VERIFIED` event transitions the equipment from `DAMAGED` or `LOST` back to `RETURNED`. Preconditions: the previous event for this equipment must be `REPORT_DAMAGE` or `REPORT_LOSS` (and for the `LOST → RETURNED` path specifically, that previous event must have been `REPORT_LOSS` and the lost item must have been located), and the related vendor invoice for this `vendor_id` must not yet have reconciled the charge. The cascade fires three coordinated effects: the linked vendor invoice's `deduction_cents` is increased by the `damage_charge_cents` of the loss event (this reduces the gross obligation by the deducted amount), the `EQUIPMENT` category's `committed_cents` is decreased by the same `damage_charge_cents` (because that portion is no longer payable), and an `AuditLog` row with action `EQUIPMENT_LOSS` is appended.

Available equipment can be retired — `AVAILABLE → DECOMMISSIONED` — by a `FinanceController`, provided the most recent event is `CHECK_IN`, `RETURN_VERIFIED`, or there are no events at all.

### 3.6. Vendor Invoices

A `FinanceController` submits a `VendorInvoice` for a production. The submission carries `production_id`, `vendor_id`, the `category_code` against which the invoice will be charged (drawn from `CAST`, `CREW`, `EQUIPMENT`, `LOCATION`, `POST`, or `MISC`), and the `gross_cents` amount. The new invoice begins in `SUBMITTED`. Its `deduction_cents` starts at zero and is accumulated by equipment damage/loss reconciliation (§3.5); its `net_cents` is computed as `gross_cents` minus `deduction_cents` at reconcile time.

Reconciliation transitions the invoice `SUBMITTED → RECONCILED`. The precondition is that every linked equipment item currently in `DAMAGED` or `LOST` against this vendor has been driven through `RETURN_VERIFIED` (or the submitter has explicitly accepted the deduction snapshot as it stands). On reconciliation, `net_cents` is recomputed from the current `gross_cents` and `deduction_cents`; the `committed_cents` of the invoice's `category_code` budget category is decremented by the resulting `net_cents` and the same `actual_cents` is incremented by `net_cents`.

Paying an invoice transitions it `RECONCILED → PAID`, provided the production is in `IN_PRODUCTION` or `WRAP_PENDING`. The cascade emits the `payment.invoice.paid` event and increments the production's denormalized `spent_cents` by `net_cents`. An invoice can alternatively be moved `SUBMITTED → DISPUTED` and held there indefinitely; disputed invoices do not block wrap close (see §3.8) but also do not generate spend.

### 3.7. Change Orders, Reserve Draws, and the Approval Wall

When the budget plan needs to shift mid-production, the `LineProducer` files a `ChangeOrder`. The submission carries `production_id`, the target `category_id`, the signed `delta_cents` (positive to increase, negative to release back), free-text `justification`, and the `source` (one of `REALLOCATION` or `RESERVE_DRAW`). The system records `requested_by` from the `LineProducer`'s `X-User-ID`, leaves `approved_by` null, and parks the change order in `PENDING`.

A pending change order has three terminal paths. The originator may **cancel** (`PENDING → CANCELLED`) provided their `X-User-ID` equals the recorded `requested_by`. A `FinanceController` may **reject** (`PENDING → REJECTED`) or **approve** (`PENDING → APPROVED`); both reject and approve enforce that the approver's `X-User-ID` is *not* equal to `requested_by` — segregation of duties is the system's primary fiscal control, and any violation yields `ERR_SEGREGATION_OF_DUTIES`. Two simultaneous approves on the same pending change order serialize so that exactly one wins; the loser sees `ERR_INVALID_STATE` because the second writer encounters a row already advanced past `PENDING`.

Approval has additional preconditions and a fan-out cascade. The production must be in `PLANNING` or `IN_PRODUCTION`. If the change order is sourced as `RESERVE_DRAW` and the `delta_cents` is positive, the production's remaining reserve fund — `reserve_fund_cents` minus the cumulative reserve already drawn — must be at least the new `delta_cents`; an insufficient reserve yields `ERR_RESERVE_INSUFFICIENT` (HTTP 409). Two concurrent `RESERVE_DRAW` approvals racing for a reserve fund that cannot satisfy both serialize on the production's reserve debit; whichever lands first wins, and the second receives `ERR_RESERVE_INSUFFICIENT`. When the production posture is currently `RED`, a `RESERVE_DRAW` approval is also gated by the posture rule of §2.6: the approver must supply the `X-Override-Reason` header to bypass it; absent that header, the call returns `ERR_POSTURE_BLOCKED`.

On a successful approve, `delta_cents` is added to the target `BudgetCategory.planned_cents`. If `source` is `RESERVE_DRAW`, the production's `reserve_fund_cents` is decreased by the same `delta_cents` (the reserve depletes). The category's `alert_state` is recomputed via the threshold rule of §2.7 against the freshly-updated `planned_cents`, and the production's `posture` is recomputed (cascade) against the new alert states. An `AuditLog` row with action `BUDGET_ADJUSTMENT` is appended; if the source was `RESERVE_DRAW`, an additional row with action `RESERVE_DRAW` is also appended.

### 3.8. Crew Booking, Wrap, and Settlement

A crew assignment is created by the `LineProducer` for a production. The payload carries the `crew_user_id` of the crew member, the `role_label` (e.g., `DP`, `GAFFER`, `PA`), the contracted `day_rate_cents`, and the `scheduled_days` count (a non-negative integer). The new assignment lands in `BOOKED`; its `actual_days` and `payroll_cents` are zero, and its lifecycle `status` is `BOOKED`. As described in §3.1, when the production locks its baseline (`PLANNING → IN_PRODUCTION`), every `BOOKED` assignment cascades to `ACTIVE` and the crew member's `day_rate_cents` multiplied by `scheduled_days` is added to the `CREW` category's `committed_cents`.

While the production is in `IN_PRODUCTION`, the producer logs each crew member's actual hours-worked through the `actual_days` patch endpoint. The patch records the `actual_days` that will be used by the payroll calculation at settlement; it does not by itself compute payroll.

Beginning the wrap is the `LineProducer`'s call. The transition `IN_PRODUCTION → WRAP_PENDING` has three preconditions: every `Scene` is in `SHOT` or `OMITTED`, every `LocationReservation` is in `FULFILLED` or `RELEASED`, and no `Equipment` for this production is currently `CHECKED_OUT`. The cascade forces the production's `posture` to `FROZEN`, transitions every `CrewAssignment` `ACTIVE → RELEASED`, and appends a `SCHEDULE_CHANGE` audit row. With posture `FROZEN`, every non-wrap-progression operation on the production is now refused with `ERR_POSTURE_BLOCKED`.

Closing the account — `WRAP_PENDING → WRAPPED` — is the `FinanceController`'s call. Three preconditions hold: every `CrewAssignment` is in `RELEASED` or `SETTLED`, every `VendorInvoice` is in `PAID` or `DISPUTED`, and every `CrewAssignment.payroll_cents` field has been computed (this last check is a sanity check that the cascade is internally consistent before final close fires). The wrap-close validation is broader: every category's `committed_cents` must be zero, no equipment for this production may be `DAMAGED`, `LOST`, or `CHECKED_OUT`, every crew assignment must be `RELEASED` or `SETTLED`, and every vendor invoice must be `PAID` or `DISPUTED`; any breach is rejected with `ERR_OPEN_OBLIGATIONS` (HTTP 409).

On a successful close, three things happen. First, every crew assignment in `RELEASED` cascades to `SETTLED`, and as part of that cascade the crew payroll calculation fires for each one. The base portion is the crew member's `day_rate_cents` multiplied by the smaller of `actual_days` and `scheduled_days` (an integer product, since `day_rate_cents` is an integer-cent value). The overtime day count is `actual_days` minus `scheduled_days` if `actual_days` is larger, and zero otherwise. Overtime is split into two tiers: the first 5 overtime days are paid at `day_rate_cents` multiplied by 1.50; any overtime days beyond the first 5 are paid at `day_rate_cents` multiplied by 1.75. Each of the two overtime components is computed and rounded half-up to the nearest integer cent **independently**, and only then are the three components (base, first-tier overtime, second-tier overtime) summed to produce the persisted `payroll_cents`. The order — round per component, then sum — is load-bearing and must not be changed; a forecast view available before settlement uses an alternative *display-only* variant that sums the components in fractional cents and rounds at the end, and may therefore differ by 1 cent from the persisted value, but the persisted `payroll_cents` MUST come from the per-component-rounding variant. As each assignment settles, the `CREW` category's `committed_cents` is decremented by the crew member's `day_rate_cents` multiplied by `scheduled_days` (releasing the booking commitment) and its `actual_cents` is incremented by `payroll_cents`.

Second, the residual budget is computed and persisted. The final `residual_cents` equals `total_budget_cents` minus the sum of every `BudgetCategory.actual_cents` for this production minus the sum of every `BudgetCategory.committed_cents` for this production. At this moment in the lifecycle, every category's `committed_cents` MUST be zero (because all crew has settled, all vendor invoices are `PAID` or `DISPUTED`, and all equipment commitments have closed); if any committed amount remains, the close is aborted with `ERR_OPEN_OBLIGATIONS`. A provisional-residual variant is exposed via the wrap preview endpoint while the production is still `WRAP_PENDING`: it computes the same difference but includes the still-outstanding `committed_cents` in the subtraction (a forecast subtotal). The authoritative `residual_cents` is only persisted on the final `WRAP_PENDING → WRAPPED` transition.

Third, the `finance.production.closed` event is emitted, and an `AuditLog` row with action `WRAP_CLOSE` is appended.

### 3.9. Cancellation, Audit Log Reads, and Test Driving

Cancellation is reserved for the `ExecutiveProducer`. From `PLANNING`, the transition `PLANNING → CANCELLED` requires that no role of the production has `casting_status` of `SIGNED` — once contracts have been signed, a planning cancellation is not permitted, because doing so would orphan committed cast obligations. The cascade releases every `LocationReservation` currently in `HELD` or `CONFIRMED` to `RELEASED`, transitions every non-terminal `Role` to `RECAST`, and appends an `AuditLog` action `SCHEDULE_CHANGE`. From `IN_PRODUCTION`, the transition `IN_PRODUCTION → CANCELLED` requires a non-empty `X-Override-Reason` header (the executive must consciously assume the consequences of mid-production cancellation), and the cascade is broader: every `LocationReservation` is released, every `CrewAssignment` in `ACTIVE` is demoted to `RELEASED`, every `ChangeOrder` in `PENDING` is moved to `CANCELLED`, and the `SCHEDULE_CHANGE` audit row records the override reason. A simultaneous role-sign-and-cancel race on the same production serializes so that exactly one operation succeeds; the loser receives `ERR_INVALID_STATE`.

Audit-log reads are available to the `ExecutiveProducer` and the `FinanceController` and accept an optional filter on `action`.

Two test-driving capabilities sit outside the production lifecycle proper. The first advances the logical clock that backs `created_at`, `updated_at`, and the system `Clock.now`: the `ExecutiveProducer` supplies a target `to_iso8601` instant in the request body, and the system pins its sense of "now" to that instant. The second is an external-event simulator: the `ExecutiveProducer` supplies an `event_type` and `payload` and the system replays the side-effects of that external event (for example, a weather-forecast update or a payment-system acknowledgement) against the relevant production. Both endpoints exist exclusively to support deterministic integration tests; they are not part of the production-user-facing API surface.

## 4. Endpoint Definitions

This section lists every endpoint exposed by the API. New resource creations return HTTP 201; state transitions and other modifications return HTTP 200; reads return HTTP 200. Trigger conditions and side effects are described in §3 — the table is intentionally minimal. Path parameters are validated left-to-right and yield `ERR_NOT_FOUND` on first miss; foreign-key fields supplied in request bodies are validated separately and yield `ERR_REFERENCE_MISMATCH` when out of scope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /productions | Create a production | `ExecutiveProducer` |
| GET | /productions/{id} | Read a production with derived posture | `ExecutiveProducer`, `LineProducer`, `FinanceController`, `CastingDirector`, `ProductionCoordinator` |
| GET | /productions | List productions; filter by `status`, `production_type` | `ExecutiveProducer`, `LineProducer`, `FinanceController`, `CastingDirector`, `ProductionCoordinator` |
| POST | /productions/{id}/lock-baseline | Lock schedule baseline | `LineProducer` |
| POST | /productions/{id}/begin-wrap | Begin wrap | `LineProducer` |
| POST | /productions/{id}/close-account | Close production account | `FinanceController` |
| POST | /productions/{id}/cancel | Cancel a production | `ExecutiveProducer` |
| GET | /productions/{id}/wrap-preview | Provisional residual & payroll preview | `LineProducer`, `FinanceController` |
| POST | /productions/{pid}/scenes | Create a scene | `LineProducer` |
| GET | /productions/{pid}/scenes | List scenes; filter by `status` | `ExecutiveProducer`, `LineProducer`, `FinanceController`, `CastingDirector`, `ProductionCoordinator` |
| POST | /productions/{pid}/scenes/{sid}/schedule | Schedule scene to a reservation | `LineProducer` |
| POST | /productions/{pid}/scenes/{sid}/mark-weather-blocked | Mark scene weather-blocked | `ProductionCoordinator` |
| POST | /productions/{pid}/scenes/{sid}/reschedule | Reschedule scene to a new reservation | `ProductionCoordinator` |
| POST | /productions/{pid}/scenes/{sid}/mark-shot | Mark scene shot | `ProductionCoordinator` |
| POST | /productions/{pid}/scenes/{sid}/omit | Omit scene | `LineProducer` |
| POST | /productions/{pid}/roles | Create casting role | `CastingDirector` |
| POST | /productions/{pid}/roles/{rid}/auditions | Record audition | `CastingDirector` |
| GET | /productions/{pid}/roles/{rid}/auditions | List auditions | `CastingDirector`, `LineProducer` |
| POST | /productions/{pid}/roles/{rid}/shortlist | Shortlist role | `CastingDirector` |
| POST | /productions/{pid}/roles/{rid}/reopen-auditions | Reopen auditions | `CastingDirector` |
| POST | /productions/{pid}/roles/{rid}/offer | Offer role to actor | `CastingDirector` |
| POST | /productions/{pid}/roles/{rid}/sign | Sign role contract | `LineProducer` |
| POST | /productions/{pid}/roles/{rid}/recast | Mark role recast | `CastingDirector` |
| POST | /productions/{pid}/roles/{rid}/substitute | Substitute signed actor | `LineProducer` |
| POST | /actors | Create actor record | `CastingDirector` |
| GET | /actors/{id} | Read actor | `CastingDirector`, `LineProducer` |
| POST | /locations | Create location | `ProductionCoordinator` |
| POST | /location-reservations | Create reservation | `ProductionCoordinator` |
| POST | /location-reservations/{id}/confirm | Confirm reservation | `ProductionCoordinator` |
| POST | /location-reservations/{id}/release | Release reservation | `ProductionCoordinator` |
| PATCH | /location-reservations/{id}/permit-status | Set permit status | `ProductionCoordinator` |
| PATCH | /location-reservations/{id}/weather-status | Set weather status | `ProductionCoordinator` |
| POST | /productions/{pid}/budget-categories | Create budget category | `FinanceController` |
| GET | /productions/{pid}/budget-categories | List categories with alert state | `LineProducer`, `FinanceController` |
| POST | /change-orders | Submit change order | `LineProducer` |
| POST | /change-orders/{id}/approve | Approve change order (segregation enforced) | `FinanceController` |
| POST | /change-orders/{id}/reject | Reject change order | `FinanceController` |
| POST | /change-orders/{id}/cancel | Cancel change order (originator only) | `LineProducer` |
| POST | /equipment | Register equipment item | `ProductionCoordinator` |
| GET | /equipment | List equipment; filter by `status`, `category` | `ProductionCoordinator`, `LineProducer`, `FinanceController` |
| POST | /equipment/{id}/events | Record equipment event | `ProductionCoordinator`, `FinanceController` |
| POST | /equipment/{id}/decommission | Decommission equipment | `FinanceController` |
| POST | /productions/{pid}/crew-assignments | Create crew assignment | `LineProducer` |
| PATCH | /productions/{pid}/crew-assignments/{cid}/actual-days | Patch `actual_days` | `LineProducer` |
| POST | /vendor-invoices | Submit vendor invoice | `FinanceController` |
| POST | /vendor-invoices/{id}/reconcile | Reconcile vendor invoice | `FinanceController` |
| POST | /vendor-invoices/{id}/pay | Pay vendor invoice | `FinanceController` |
| POST | /vendor-invoices/{id}/dispute | Dispute vendor invoice | `FinanceController` |
| GET | /productions/{pid}/audit-logs | List audit log entries; filter by `action` | `ExecutiveProducer`, `FinanceController` |
| POST | /_clock/advance | Advance the logical clock (test only) | `ExecutiveProducer` |
| POST | /_events/emit | Emit external simulator event (test only) | `ExecutiveProducer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_POSTURE_BLOCKED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REFERENCE_MISMATCH` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_PERMIT_REQUIRED` | 409 |
| `ERR_LOCATION_OVER_CAPACITY` | 409 |
| `ERR_WEATHER_BLOCKED` | 409 |
| `ERR_AUDITION_NOT_PASSED` | 422 |
| `ERR_ACTOR_CALLSHEET_CONFLICT` | 409 |
| `ERR_CROSS_PROJECT_CONFLICT` | 409 |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 |
| `ERR_INVALID_EVENT_PAYLOAD` | 422 |
| `ERR_BUDGET_OVERALLOCATED` | 422 |
| `ERR_RESERVE_INSUFFICIENT` | 409 |
| `ERR_OPEN_OBLIGATIONS` | 409 |
| `ERR_INVALID_PAGINATION` | 422 |
| `ERR_VALIDATION` | 422 |
