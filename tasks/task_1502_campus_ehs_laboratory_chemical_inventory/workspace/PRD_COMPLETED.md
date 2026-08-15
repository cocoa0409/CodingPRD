# Campus EHS Lab Chemical Inventory API — Product Requirements Document

## 1. Introduction

University Environmental Health & Safety (EHS) offices are accountable for every regulated chemical on campus from the moment a bottle crosses the loading dock to the day a lab is decommissioned. Today that accountability is spread across binders, spreadsheets, and institutional memory: container barcodes are tracked per lab, hazardous-material totals must be screened against permit thresholds, waste accumulates in satellite areas under strict aging limits, inspectors cycle through labs and chase corrective actions, and controlled substances require regulator registrations that must stay in lockstep with what is physically on the shelf. When a principal investigator departs, the entire compliance posture of their lab has to be wound down in a disciplined order.

This document specifies a REST API, mounted under `/ehs`, that operationalizes that entire lifecycle. The API tracks chemical containers by lab and barcode, derives per-lab hazard totals and a permit-reporting flag, manages waste tagging into accumulation areas and the pickup-request workflow that disposes of them, schedules lab inspections and the corrective actions that findings spawn, assigns hazard-class training to workers, records incidents and near-misses, and coordinates controlled-substance and select-agent registrations. A derived **safety posture** per lab gates dangerous operations, and a test-drivable logical clock governs all time-based behavior such as training expiry and accumulation overstay, so that compliance scenarios can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, identifying the role under which the operator acts. A request missing either header, or presenting a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, a request whose role is not in the endpoint's allowed set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), and a request that passes the role check but violates an ownership scope is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

The declared roles are exactly four, spelled as follows:

- `EHSAdmin` — the university EHS office administrator, a platform-level operator with override power over scheduling, verification workflow setup, and decommissioning.
- `EHSInspector` — the field inspector who performs assigned inspections and verifies corrective actions, subject to segregation of duties against inspections they themselves completed.
- `PrincipalInvestigator` — the lab PI, who owns the lab's compliance workflow: closeout, waste pickup submission, and corrective-action response.
- `LabMember` — a lab worker (researcher or student) who handles day-to-day container and waste operations.

Identity semantics differ by role and are contractual. When `X-User-Role` is `EHSAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `EHSInspector`: `X-User-ID` is an opaque operator identifier, recorded on an inspection as `inspector_id` at scheduling time and as `completed_by_inspector_id` at completion time, but never compared to a persisted worker entity. By contrast, when `X-User-Role` is `PrincipalInvestigator` or `LabMember`, `X-User-ID` is the `id` of the acting `LabWorker`; ownership checks on any resource that references a `LabWorker` — most importantly the lab's `pi_worker_id` and a training assignment's `worker_id` — compare the resource's foreign-key field to `X-User-ID`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock — it is not drawn from the logical clock of §2.5.
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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses order resources by `created_at` ascending, with ties broken by creation order (earlier-created first). Filter query parameters match by exact equality, and a filter value that matches nothing yields an empty page rather than an error. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of resources matching the applied filters and `has_more` indicates whether further pages exist beyond the returned window.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource in this API carries four common properties. The `id` is a server-minted UUID without any type prefix, and resources are addressed by their `id` in URL paths. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` is refreshed on every mutation of the resource. Datetime values supplied in request bodies — a pickup request's `window_start` and `window_end`, an inspection's `scheduled_start` and `scheduled_end`, a training assignment's `due_date`, and the clock endpoint's `to_iso8601` — are accepted as ISO 8601 strings in any offset, stored as instants, and rendered in responses in UTC with three fractional digits, so a supplied `2026-08-10T11:30:00Z` reads back as `2026-08-10T11:30:00.000Z`; the clock endpoint's `current_utc` is rendered in the same format. The `version` is an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of the resource — including system-driven mutations such as sweeps, cascades, and compensations — and is returned on every read so clients can observe the current value. Recomputing a derived field is not by itself a mutation: a posture recomputation (§2.6), even one that changes the lab's stored `posture`, neither increments the lab's `version` nor refreshes its `updated_at`.

Optimistic concurrency control applies to exactly one write operation: creating a controlled-material registration. That request must carry `expected_lab_version` holding the client-observed `version` of the target lab. If the lab's current `version` does not match — because another writer has mutated the lab since the client last read it, for example by creating a registration of the same material type that superseded a pending one — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a lab state it has not observed. No other endpoint accepts or requires a version field; all other synchronization is expressed through state preconditions.

### 2.5. The Logical Clock

All time-dependent behavior in the system — training expiry, accumulation overstay, due-date comparisons — is evaluated against a **logical clock**, never the wall clock. At server startup the logical clock reads 2026-08-01T00:00:00Z. An admin-only test-driving capability sets the logical clock to a supplied instant: the request carries `to_iso8601` and the response reports the resulting `current_utc`. The supplied instant is accepted without any comparison to the current value, so the clock may be set to an earlier instant. Every set triggers a sweep with three effects: every training assignment still `ASSIGNED` whose `due_date` is strictly earlier than the new logical now transitions to `EXPIRED`; accumulation overstay is re-evaluated for every tagged container; and the safety posture of every lab is recomputed from the new now. Timestamps the server stamps onto entities as a consequence of mutations — such as a container's `tagged_at`, an inspection's `completed_at`, or a training assignment's `completed_at` — record the logical now at the moment of the mutation. Datetime comparisons throughout the system compare the exact stored instants, with no truncation to second (or any coarser) granularity.

### 2.6. Laboratory Safety Posture

Each lab carries a derived **safety posture** in its `posture` field, one of `NORMAL`, `RESTRICTED`, or `FROZEN`. Posture is never set directly; it is recomputed from source data on every mutation of the lab's corrective actions, inspections, training assignments, incidents, container states, and lab status, and on every clock sweep. The derivation is an ordered, first-match-wins evaluation:

1. If the lab's `status` is `DECOMMISSIONED`, posture is `FROZEN`.
2. Otherwise, if at least one corrective action of the lab is in `OPEN` or `REOPENED` status with a `due_date` strictly earlier than the logical now, posture is `FROZEN`.
3. Otherwise, if the lab's most recently completed inspection — the `COMPLETED` inspection with the latest `completed_at`, ties broken in favor of the earliest `created_at`, and any remaining tie broken in favor of the earliest-created inspection — has `outcome` equal to `FAIL` with at least one `MAJOR` finding, posture is `FROZEN`.
4. Otherwise, if at least two incidents of the lab are in `REPORTED` status with `severity` equal to `HIGH`, posture is `FROZEN`.
5. Otherwise, if at least one corrective action of the lab is in `OPEN`, `SUBMITTED`, or `REOPENED` status, posture is `RESTRICTED`.
6. Otherwise, if exactly one incident of the lab is in `REPORTED` status with `severity` equal to `HIGH`, posture is `RESTRICTED`.
7. Otherwise, if at least one training assignment of the lab is in `EXPIRED` status, posture is `RESTRICTED`.
8. Otherwise, if at least one container of the lab is `WASTE_TAGGED` and has been tagged for strictly more than 365 days, posture is `RESTRICTED`.
9. Otherwise, posture is `NORMAL`.

While a lab is `FROZEN`, four mutations are gated and fail with `ERR_LAB_FROZEN` (HTTP 409): registering a new container in the lab, tagging a container as waste, creating a waste pickup request for the lab, and submitting a waste pickup request for the lab. The transition into `FROZEN` also cascades: every registration of the lab in `ACTIVE` status transitions to `SUSPENDED`, and each such suspension recomputes the `access_blocked` flag of the lab's containers whose `hazard_class` matches the suspended registration's `material_type`, setting it to true. A lab created fresh starts with `status` equal to `ACTIVE` and `posture` equal to `NORMAL`.

### 2.7. Hazard Inventory Accounting and Permit Screening

Every container's `quantity_value` is an amount already normalized to gallons-equivalent at receipt; the `quantity_unit` records the original unit as received — one of `GAL`, `L`, `KG`, or `LB`, defaulting to `GAL` — and is informational only. From the container population of a lab, the system maintains two per-hazard-class totals for each of the six hazard classes (`FLAMMABLE`, `OXIDIZER`, `CORROSIVE`, `TOXIC`, `CONTROLLED_SUBSTANCE`, `SELECT_AGENT`). The physical total for a class, exposed in `hazard_totals_physical`, sums `quantity_value` over the lab's containers in state `IN_USE` only — a container that has been tagged as waste but not yet picked up drops out of this total. The regulatory total, exposed in `hazard_totals_regulatory`, sums `quantity_value` over containers in state `IN_USE` or `WASTE_TAGGED`, so the identical container data yields a total at least as large. Containers in state `PICKED_UP` are excluded from both totals.

A hazard class is flagged when its regulatory total is greater than zero and at least the class's permit threshold in gallons: 10.0 for `FLAMMABLE`, 10.0 for `OXIDIZER`, 5.0 for `CORROSIVE`, 1.0 for `TOXIC`, and 0.0 for both `CONTROLLED_SUBSTANCE` and `SELECT_AGENT` — meaning any positive on-hand quantity of a regulated class flags it. The threshold comparison is inclusive: a regulatory total exactly equal to the threshold flags the class. The lab's `permit_report_required` is true whenever at least one class is flagged. Stored totals are kept at 2 decimal places with round-half-up. This screening re-runs whenever a container is created, tagged as waste, untagged, or carried to `PICKED_UP` by a completed pickup; because tagging moves a container into the regulatory set and pickup removes it, the permit flag can flip in either direction at those moments.

### 2.8. Validation Order and Referential Integrity

Every mutating request is screened against the applicable checks in a fixed priority order, and the first failing check determines the rejection — a later check never masks an earlier one. The order is:

1. Authentication: headers present and role declared, else `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. Request-body well-formedness: required fields present (an explicit `null` counts as absent), string fields non-empty, enum values in range, boolean and integer fields well-typed (`capacity_containers` an integer greater than zero, `expected_lab_version` an integer), `quantity_value` greater than zero, else `ERR_INVALID_REQUEST`. A body that parses to something other than a JSON object is rejected at parse time, ahead of the role check; a missing or syntactically malformed JSON body is treated as an empty object.
4. Ownership scope, enforced at exactly five places — a `PrincipalInvestigator` closing out a lab, creating a waste pickup request, submitting one, or submitting a corrective action must have `X-User-ID` equal to that lab's `pi_worker_id`; an inspector completing an inspection must have `X-User-ID` equal to the inspection's `inspector_id`; and a training completion requires `X-User-ID` equal to the assignment's `worker_id` or the lab's `pi_worker_id` — else `ERR_FORBIDDEN_OWNERSHIP`. No other endpoint applies an ownership scope (in particular, a PI creating workers, training assignments, or registrations is not scoped to their own lab). On three actions the state precondition (priority 6) is deliberately evaluated ahead of this ownership check: completing a training assignment, submitting a corrective action, and submitting a pickup request surface `ERR_TRAINING_STATE`, `ERR_CORRECTIVE_ACTION_STATE`, or `ERR_PICKUP_STATE` respectively before any ownership rejection.
5. Existence of referenced resources, validated left to right: path identifiers first, then body foreign keys such as `lab_id`, `container_id`, `accumulation_area_id`, and `worker_id`, else `ERR_NOT_FOUND`. Nested URLs are resolved the same way, each path segment's resource validated before the next.
6. State preconditions for the requested transition, surfaced through the state-specific errors `ERR_LAB_STATE`, `ERR_CONTAINER_STATE`, `ERR_PICKUP_STATE`, `ERR_INSPECTION_STATE`, `ERR_CORRECTIVE_ACTION_STATE`, `ERR_REGISTRATION_STATE`, `ERR_TRAINING_STATE`, or `ERR_INCIDENT_STATE`.
7. The frozen-posture gate on the four gated mutations, else `ERR_LAB_FROZEN`.
8. The controlled-material registration screen on container creation, else `ERR_CONTROLLED_MATERIAL_UNREGISTERED`.
9. The required-training gate on waste tagging, else `ERR_REQUIRED_TRAINING_INCOMPLETE`.
10. Segregation of duties on corrective-action verification, else `ERR_SEGREGATION_OF_DUTIES`.
11. Barcode uniqueness within the lab, else `ERR_DUPLICATE_BARCODE`.
12. The single-PI rule on worker creation, else `ERR_PI_ALREADY_ASSIGNED`.
13. The duplicate-active-registration rule, else `ERR_DUPLICATE_ACTIVE_REGISTRATION`.
14. Cross-lab reference integrity, applied exactly where the prose specifies it — the accumulation area named on waste tagging must belong to the container's lab, and the container named on add-item must belong to the request's lab; no other foreign-key pairing (such as a training assignment's worker versus lab) is cross-lab screened — else `ERR_CROSS_LAB_REFERENCE`.
15. The non-empty-pickup rule on submit, else `ERR_PICKUP_EMPTY`.
16. Window validity, else `ERR_INVALID_WINDOW`.
17. Inspector schedule overlap, else `ERR_INSPECTOR_SCHEDULE_CONFLICT`.
18. Dock window buffer, else `ERR_DOCK_WINDOW_CONFLICT`.
19. Accumulation-area capacity, else `ERR_AREA_CAPACITY_EXCEEDED`.
20. Decommission cleanliness, else `ERR_DECOMMISSION_BLOCKED`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Lab and Its People

An `EHSAdmin` establishes a lab by supplying its `name`, `department`, `building`, and `room`. The new lab begins life with `status` equal to `ACTIVE` and `posture` equal to `NORMAL`. Labs can be browsed through the lab list, which supports optional filtering by `posture`, by `status`, and by `pi_worker_id`, alongside the standard pagination parameters; a single lab read returns the derived `posture`, both hazard-total maps, and the `permit_report_required` flag alongside the stored attributes.

People join a lab as workers. Creating a worker takes the target `lab_id`, the worker's `full_name`, and a `role_in_lab` of `PI`, `RESEARCHER`, or `STUDENT`; both `EHSAdmin` and `PrincipalInvestigator` operators may add workers. A lab has at most one PI-role worker: when a worker is created with `role_in_lab` equal to `PI`, the lab's `pi_worker_id` is automatically set to the new worker's `id` and the lab's `version` increments by 1, and attempting to add a second PI to a lab that already has one is rejected with `ERR_PI_ALREADY_ASSIGNED` (HTTP 409). The workers of a lab are listed through the lab's worker collection, and an individual worker can be read directly.

Training is assigned per worker and per hazard class. Creating an assignment — available to `EHSAdmin` and `PrincipalInvestigator` — takes the `lab_id`, the `worker_id`, the `hazard_class` the training certifies, and a `due_date` deadline; the assignment begins in `ASSIGNED` status. Completing the training moves it from `ASSIGNED` to `COMPLETED` and stamps `completed_at` with the logical now; the acting operator must be either the assigned worker themselves (the header matches the assignment's `worker_id`) or the lab's PI (the header matches the lab's `pi_worker_id`), and anyone else is rejected with `ERR_FORBIDDEN_OWNERSHIP`. Completing an assignment that is no longer `ASSIGNED` is rejected with `ERR_TRAINING_STATE` (HTTP 409). When the logical clock advances past an assignment's `due_date` while it is still `ASSIGNED`, the sweep transitions it to `EXPIRED`, and in either completion or expiry the lab's posture is recomputed. Training assignments are listed per lab and per worker, each list optionally filterable by `status`.

### 3.2. Chemical Container Intake and Inventory

A `PrincipalInvestigator` or `LabMember` registers a new container with a payload containing the `lab_id`, a `barcode` unique within that lab, the `chemical_name`, the `hazard_class`, the `quantity_value` normalized to gallons-equivalent, and optionally the `quantity_unit`. The `quantity_value` may be supplied as a JSON number or a numeric string; it is stored as supplied and rendered in responses rounded half-up to 2 decimal places, while the unrounded stored value is what feeds the hazard-total and pickup-cost sums. The container begins in state `IN_USE`. Registration is refused with `ERR_INVALID_REQUEST` (HTTP 400) when the quantity is not greater than zero; with `ERR_LAB_STATE` (HTTP 409) when the lab's `status` is not `ACTIVE`; with `ERR_LAB_FROZEN` when the lab's posture is `FROZEN`; and with `ERR_DUPLICATE_BARCODE` (HTTP 409) when the barcode already exists within the lab. Containers of the regulated classes carry an extra gate: a container whose `hazard_class` is `CONTROLLED_SUBSTANCE` or `SELECT_AGENT` may only be registered while the lab holds an `ACTIVE` registration of the matching `material_type`, and otherwise the create is rejected with `ERR_CONTROLLED_MATERIAL_UNREGISTERED` (HTTP 422).

Each regulated container also exposes the computed `access_blocked` flag, which is true whenever its `hazard_class` is `CONTROLLED_SUBSTANCE` or `SELECT_AGENT` and the lab currently has no `ACTIVE` registration of the matching `material_type`. The flag flips as registrations move: activation clears it for matching containers, while suspension, surrender, and the frozen-posture cascade set it. Every container registration, and every later state change of the container, re-screens the lab's hazard totals and recomputes the lab's posture. The container catalog is listed with optional filters `lab_id`, `accumulation_area_id`, `pickup_request_id`, `state`, and `hazard_class` — these filters are also the supported way to reach containers in reverse from the areas or pickup requests that reference them — and a single container is readable by any declared role.

### 3.3. Waste Tagging and the Accumulation Areas

Before waste can be staged, an `EHSAdmin` creates an accumulation area for a lab, supplying the `lab_id`, a display `name`, an `area_type` of `SAA` (satellite) or `CAA` (central), and a `capacity_containers` ceiling that must be greater than zero; neither the lab's `status` nor its posture is screened at area creation. Each area exposes the computed `current_container_count` — the number of containers currently `WASTE_TAGGED` into it — and the computed `has_overstay_containers` flag. The areas of a lab are listed through the lab's accumulation-area collection.

Tagging a container as waste moves it from `IN_USE` to `WASTE_TAGGED` and places it into an accumulation area named by `accumulation_area_id` in the request. The acting operator, a `PrincipalInvestigator` or `LabMember`, faces a battery of guards: the container must currently be `IN_USE` (otherwise `ERR_CONTAINER_STATE`); the lab's `status` must be `ACTIVE` or `CLOSING` (otherwise `ERR_LAB_STATE`); the lab's posture must not be `FROZEN` (otherwise `ERR_LAB_FROZEN`); the acting worker must hold a training assignment in this lab, for the container's `hazard_class`, in status `COMPLETED` (otherwise `ERR_REQUIRED_TRAINING_INCOMPLETE`, HTTP 422); the named area must belong to the same lab as the container (otherwise `ERR_CROSS_LAB_REFERENCE`, HTTP 422); and the area's `current_container_count` must be below its `capacity_containers` before the tag (otherwise `ERR_AREA_CAPACITY_EXCEEDED`, HTTP 409). On success the container's `accumulation_area_id` is set to the area and its `tagged_at` is stamped with the logical now; the area's count increases by one; the container joins the regulatory hazard set, which re-screens the lab's totals and may set `permit_report_required`; the lab's posture is recomputed; and the container's `version` increments by 1.

Untagging is the compensating action, returning a container from `WASTE_TAGGED` to `IN_USE`. It is permitted only while the container is `WASTE_TAGGED` and either its `pickup_request_id` is null or the linked pickup request is in `REJECTED` or `CANCELLED` status; any other combination is rejected with `ERR_CONTAINER_STATE`. Untagging clears `accumulation_area_id`, `tagged_at`, and `pickup_request_id` to null, decreases the previous area's count by one, re-screens the hazard totals, recomputes posture, and increments the container's `version`.

Accumulation aging is tracked at day granularity. For each `WASTE_TAGGED` container, the age in days is the whole-day floor of the elapsed time between `tagged_at` and the logical now; the container is an overstay when that age is strictly greater than 365 days, so a container at exactly 365 days is still compliant. An area's `has_overstay_containers` is true when any container currently tagged into it is an overstay, and the overstay population feeds rule 8 of the posture derivation. Aging is re-evaluated on every tag and on every clock sweep.

### 3.4. The Waste Pickup Cycle

Disposal begins when a `PrincipalInvestigator` creates a pickup request for their own lab, supplying the `lab_id`; the request starts as a `DRAFT`. The acting `X-User-ID` must equal the lab's `pi_worker_id`, otherwise the create is rejected with `ERR_FORBIDDEN_OWNERSHIP`, and the create is blocked while the lab's posture is `FROZEN`, surfacing `ERR_LAB_FROZEN`; no lab-`status` precondition applies, so a request may be opened while the lab is `ACTIVE` or `CLOSING`. Pickup requests are listed with optional `lab_id` and `status` filters, and a single request read returns the computed `estimated_quantity_total` and `estimated_cost` alongside the stored fields.

While the request is in `DRAFT` or `REJECTED` status, its composition is editable: `PrincipalInvestigator` and `LabMember` operators add items by supplying a `container_id`, which links that container to the request, and remove items the same way to unlink. Adding requires the container to be `WASTE_TAGGED` and to belong to the same lab as the request — a cross-lab link is rejected with `ERR_CROSS_LAB_REFERENCE` — and operating on a request that has left the editable statuses is rejected with `ERR_PICKUP_STATE`; the request's editable-status check is applied before the container's state check. Adding sets the container's `pickup_request_id` to the request; removing clears it to null, and removing a container that is not linked to the request is rejected with `ERR_CONTAINER_STATE` (HTTP 409). Either change recomputes the request's economics and increments the request's `version` by 1.

The estimate follows a pinned rounding order. The `estimated_quantity_total` is the plain sum of `quantity_value` over the containers linked to the request that are still `WASTE_TAGGED`, carried without rounding — the 2-decimal round-half-up rule of §2.7 applies to the lab hazard-total maps only, not to this total. Each linked container contributes a per-item fee equal to its `quantity_value` multiplied by the per-gallon disposal rate for its hazard class — 12.50 for `FLAMMABLE`, 11.00 for `OXIDIZER`, 9.75 for `CORROSIVE`, 21.20 for `TOXIC`, 45.00 for `CONTROLLED_SUBSTANCE`, and 60.00 for `SELECT_AGENT` — with each per-item fee first rounded half-up to 2 decimal places. The `estimated_cost` is then the sum of those already-rounded per-item fees plus a flat base fee of 75.00. Summing first and rounding once at the end is a different interpretation that can differ by cents and is not the prescribed order.

Submission is the PI's signature action and moves the request from `DRAFT` to `SUBMITTED`, or from `REJECTED` back to `SUBMITTED` in the revision loop. Submitting requires at least one linked container (an empty request is rejected with `ERR_PICKUP_EMPTY`, HTTP 422), requires the lab's posture not to be `FROZEN`, and requires the acting `X-User-ID` to equal the lab's `pi_worker_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`); a request in any other status is rejected with `ERR_PICKUP_STATE`. A successful submit clears any recorded `rejection_reason` to null and increments the request's `version`.

Review belongs to the `EHSAdmin`. Rejecting a `SUBMITTED` request records the supplied `reason` into `rejection_reason` and moves the request to `REJECTED`, deliberately preserving every container link — the containers stay `WASTE_TAGGED` with their `pickup_request_id` intact — so the PI can revise and resubmit. Scheduling a `SUBMITTED` request reserves a loading dock: the admin supplies `dock_id`, `window_start`, and `window_end`, where `window_end` must be strictly after `window_start` (otherwise `ERR_INVALID_WINDOW`, HTTP 400). The dock enforces a 30-minute buffer: no other `SCHEDULED` pickup at the same `dock_id` may have a window that falls within 30 minutes of the new window on either side, while a gap of exactly 30 minutes is allowed; a violation is rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409). Scheduling stores the dock and window on the request and moves it to `SCHEDULED`; until a request is scheduled, its `dock_id`, `window_start`, and `window_end` are null.

Completion of a `SCHEDULED` request is the cascade point of the waste workflow. Every container linked to the request transitions from `WASTE_TAGGED` to `PICKED_UP`; each such container retains its `accumulation_area_id` for audit but drops out of the area's count, because the count only considers containers currently in `WASTE_TAGGED`, so the area counts decrease by one per collected container. As each container leaves the regulatory set, the lab's hazard totals are re-screened and `permit_report_required` may flip to false; the lab's posture is recomputed; and both the containers' and the request's `version` values increment. Cancelling a `SCHEDULED` request is the compensating path: it moves the request to `CANCELLED` and clears the `pickup_request_id` of every linked container to null, while the containers themselves remain `WASTE_TAGGED` in their areas and the area counts are unchanged. Completion and cancellation are both `EHSAdmin` actions and are only valid from `SCHEDULED`, otherwise `ERR_PICKUP_STATE`; both increment the request's `version` by 1. A request that reaches `COMPLETED` or `CANCELLED` is terminal.

### 3.5. Inspections, Findings, and the Corrective-Action Loop

An `EHSAdmin` schedules an inspection by supplying the `lab_id`, the `inspector_id` of the field inspector who will perform it, and a half-open window from `scheduled_start` to `scheduled_end`. The end must be strictly after the start, otherwise `ERR_INVALID_WINDOW`. An inspector's calendar is protected by a half-open overlap rule: no other `SCHEDULED` inspection for the same `inspector_id` may overlap the new window, where two windows overlap exactly when the new start is before the existing end and the existing start is before the new end — windows that merely touch at an endpoint are allowed. A conflict is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT` (HTTP 409). The new inspection begins in `SCHEDULED` status. Inspections are listed with optional `lab_id`, `inspector_id`, and `status` filters.

Completion belongs to the assigned inspector: the acting `X-User-ID` must equal the inspection's `inspector_id`, otherwise `ERR_FORBIDDEN_OWNERSHIP`, and the inspection must still be `SCHEDULED`, otherwise `ERR_INSPECTION_STATE`. The completing inspector supplies the `findings`, an array in which each entry pairs a `severity` of `MAJOR` or `MINOR` with a non-empty free-text `description`. Scoring is computed at completion with integer arithmetic: `score_weighted` starts from 100 and deducts 20 per `MAJOR` finding and 5 per `MINOR` finding, while `score_flat` starts from 100 and deducts a flat 10 per finding regardless of severity, so identical findings can yield a different flat score than weighted score (two `MAJOR` findings and one `MINOR` finding give a weighted 55 against a flat 70). The `outcome` is `PASS` when `score_weighted` is at least 70 — the boundary is inclusive, so a weighted score of exactly 70 passes — and `FAIL` otherwise; an empty findings array yields both scores equal to 100 and an `outcome` of `PASS`. Until completion, `findings`, `score_weighted`, `score_flat`, `outcome`, `completed_by_inspector_id`, and `completed_at` are all null. Completion also stamps `completed_by_inspector_id` with the acting `X-User-ID`, records `completed_at` at the logical now, and increments the inspection's `version`.

Every finding spawns exactly one corrective action in `OPEN` status, carrying the parent `inspection_id`, the `lab_id` copied from the inspection, and the `description` and `severity` copied from the triggering finding. The action's `due_date` is `completed_at` plus 14 days for a `MAJOR` finding or plus 30 days for a `MINOR` finding. Completion also recomputes the lab's posture, which is where the heaviest cascade in the system begins: a `FAIL` with at least one `MAJOR` finding forces the posture to `FROZEN` via derivation rule 3, and a transition into `FROZEN` suspends every `ACTIVE` registration of the lab and recomputes `access_blocked` to true on the lab's containers of each suspended `material_type`. A corrective action's `overdue` flag is true whenever its status is `OPEN` or `REOPENED` and the logical now is strictly later than its `due_date`. Corrective actions are listed per lab with an optional `status` filter, and the actions spawned by a single inspection are listed through the inspection's own collection.

Remediation is a cyclic rework loop between the PI and the inspectorate. The lab's PI submits remediation evidence by supplying a `resolution_note`, moving the action from `OPEN` — or from `REOPENED` on a rework pass — to `SUBMITTED`; the note is stored on submit and overwritten if the action is resubmitted after a reopen. Submitting requires the acting `X-User-ID` to equal the lab's `pi_worker_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`) and the action to be in `OPEN` or `REOPENED` (otherwise `ERR_CORRECTIVE_ACTION_STATE`, HTTP 409). Verification then requires a different pair of hands: the verifying `EHSInspector` supplies a `decision`, and segregation of duties forbids the verifying inspector's `X-User-ID` from equalling the parent inspection's `completed_by_inspector_id` — a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A `decision` of `APPROVE` moves the action from `SUBMITTED` to `VERIFIED`, its terminal state, and stamps `verified_by` with the verifying inspector's id; a `decision` of `REJECT` moves it back to `REOPENED`, restarting the loop. Verifying an action that is not `SUBMITTED` is rejected with `ERR_CORRECTIVE_ACTION_STATE`. Every submit and every verify recomputes the lab's posture and increments the action's `version` by 1, so posture lifts out of `RESTRICTED` only when the last open action leaves the open statuses.

### 3.6. Incident and Near-Miss Reporting

Anyone on the ground — `LabMember`, `PrincipalInvestigator`, or `EHSAdmin` — reports an incident for a lab by supplying the `lab_id`, a short `title`, a `description` of what happened (spill, exposure, near-miss), a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and optionally the `near_miss` flag, which defaults to false and marks reports where no release or injury occurred. Reporting is not gated on the lab's `status` or posture. The incident opens in `REPORTED` status, the reporter's `X-User-ID` is recorded as `reported_by`, and because open `HIGH`-severity incidents feed posture derivation rules 4 and 6, the lab's posture is recomputed at report time. The incidents of a lab are listed with optional `status` and `severity` filters.

Closure is an `EHSAdmin` action that moves the incident from `REPORTED` to its terminal `CLOSED` status, storing the supplied `resolution` narrative. Closing an incident in any other status is rejected with `ERR_INCIDENT_STATE` (HTTP 409). Because closure shrinks the open-incident population, the lab's posture is recomputed and the incident's `version` increments by 1.

### 3.7. Controlled-Material Registrations

Possession of controlled substances and select agents is tracked through registrations coordinated with the external regulator. A `PrincipalInvestigator` or `EHSAdmin` creates a registration by supplying the `lab_id`, a `material_type` of `CONTROLLED_SUBSTANCE` or `SELECT_AGENT`, the regulator-issued `registration_number`, and — this is the system's one optimistic-concurrency point — an `expected_lab_version` equal to the lab's current `version`. If the lab's `version` has advanced beyond what the client last observed, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The `expected_lab_version` must be supplied as a JSON integer, and the version check is applied after the lab's existence is confirmed and before the duplicate-active-registration screen. No uniqueness constraint applies to `registration_number`. The new registration begins in `PENDING` status, and creating it increments the lab's `version` by 1.

Replacement and conflict rules keep one authoritative registration per material type per lab. If a registration of the same `lab_id` and `material_type` already exists in `PENDING` status when the new one is created, the existing one transitions to the terminal `SUPERSEDED` status and its `version` increments by 1. If instead one exists in `ACTIVE` or `SUSPENDED` status, the create is rejected outright with `ERR_DUPLICATE_ACTIVE_REGISTRATION` (HTTP 409). The registrations of a lab are listed with an optional `status` filter.

The lifecycle after creation is an `EHSAdmin` responsibility. Activation moves a registration from `PENDING` or `SUSPENDED` to `ACTIVE` — a registration in any other status is rejected with `ERR_REGISTRATION_STATE` (HTTP 409) — and recomputes `access_blocked` to false for the lab's containers whose `hazard_class` matches the registration's `material_type`. Suspension moves an `ACTIVE` registration to `SUSPENDED`, either by direct admin action or by the system cascade when the lab's posture becomes `FROZEN`, and recomputes `access_blocked` to true on the matching containers. Surrender moves an `ACTIVE` or `SUSPENDED` registration to the terminal `SURRENDERED` status and likewise recomputes `access_blocked` to true. Each of these transitions increments the registration's `version` by 1, and none of them is gated on the lab's `status` or posture. Because the container-intake gate and the `access_blocked` flag both key on an `ACTIVE` registration of the matching type, suspension or surrender immediately closes the door to new regulated containers and flags the existing stock.

### 3.8. Lab Closeout and Decommissioning

When a PI departs, closeout begins with the transition from `ACTIVE` to `CLOSING`, available to the lab's own `PrincipalInvestigator` or to an `EHSAdmin`. The lab must currently be `ACTIVE`, otherwise `ERR_LAB_STATE`; and when the actor is a `PrincipalInvestigator`, the acting `X-User-ID` must equal the lab's `pi_worker_id`, otherwise `ERR_FORBIDDEN_OWNERSHIP`. Closeout cancels every inspection of the lab still in `SCHEDULED` status — each cancelled inspection's `version` increments by 1 — recomputes the lab's posture, and increments the lab's `version` by 1. Note that waste tagging remains available while a lab is `CLOSING`, since the lab's remaining inventory still has to be disposed of.

Decommissioning finalizes the lab from `CLOSING` to the terminal `DECOMMISSIONED` status and is an `EHSAdmin`-only action. It is permitted only when the lab's books are clean across five dimensions: no container of the lab in any state other than `PICKED_UP`; no pickup request in `DRAFT`, `SUBMITTED`, `REJECTED`, or `SCHEDULED`; no corrective action in `OPEN`, `SUBMITTED`, or `REOPENED`; no registration in `PENDING`, `ACTIVE`, or `SUSPENDED` (surrender is therefore a prerequisite for any regulated lab); and no incident in `REPORTED` status. A lab not in `CLOSING` is rejected with `ERR_LAB_STATE`; any violation of the five cleanliness checks is rejected with `ERR_DECOMMISSION_BLOCKED` (HTTP 409). On success the lab's `posture` is set to `FROZEN` — consistent with derivation rule 1 — and the lab's `version` increments by 1.

## 4. Endpoint Definitions

All endpoints live under the `/ehs` prefix. Creating a new resource returns HTTP 201 with the created resource; all other successful operations — reads, list queries, and state-transition actions that modify an existing resource — return HTTP 200 with the affected resource (or the clock payload for the clock endpoint). Requests and responses follow the envelope in §2.2, and request inputs are validated in the order given in §2.8.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/ehs/_clock/set_current_utc` | Test-driving endpoint: set the logical clock (startup default 2026-08-01T00:00:00Z); sweeps expired training and recomputes overstay and all lab postures | EHSAdmin |
| POST | `/ehs/labs` | Create a lab (status ACTIVE, posture NORMAL) | EHSAdmin |
| GET | `/ehs/labs` | List labs with optional filters and pagination | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/labs/{id}` | Get one lab including computed posture, hazard totals, and permit flag | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/labs/{id}/closeout` | Initiate closeout at PI departure (ACTIVE → CLOSING); cancels SCHEDULED inspections | PrincipalInvestigator, EHSAdmin |
| POST | `/ehs/labs/{id}/decommission` | Finalize decommissioning (CLOSING → DECOMMISSIONED) with aggregate cleanliness preconditions | EHSAdmin |
| POST | `/ehs/workers` | Add a worker to a lab; role_in_lab=PI auto-assigns the lab's PI (one PI max) | EHSAdmin, PrincipalInvestigator |
| GET | `/ehs/labs/{id}/workers` | List workers of a lab | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/workers/{id}` | Get one worker | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/containers` | Register a barcoded container (state IN_USE); controlled classes need an ACTIVE registration; gated by posture and lab status | PrincipalInvestigator, LabMember |
| GET | `/ehs/containers` | List containers with filters (lab, area, pickup request, state, hazard class) | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/containers/{id}` | Get one container | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/containers/{id}/tag-waste` | Tag container as waste into an accumulation area (IN_USE → WASTE_TAGGED) | PrincipalInvestigator, LabMember |
| POST | `/ehs/containers/{id}/untag-waste` | Compensating action: return a tagged container to inventory (WASTE_TAGGED → IN_USE) | PrincipalInvestigator, LabMember |
| POST | `/ehs/accumulation-areas` | Create a satellite/central accumulation area for a lab | EHSAdmin |
| GET | `/ehs/labs/{id}/accumulation-areas` | List accumulation areas of a lab | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/waste-pickup-requests` | Create a DRAFT waste pickup request for own lab (FROZEN posture blocks) | PrincipalInvestigator |
| GET | `/ehs/waste-pickup-requests` | List pickup requests with filters | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/waste-pickup-requests/{id}` | Get one pickup request including computed totals | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/waste-pickup-requests/{id}/add-item` | Link a WASTE_TAGGED container to a DRAFT or REJECTED request | PrincipalInvestigator, LabMember |
| POST | `/ehs/waste-pickup-requests/{id}/remove-item` | Compensating action: unlink a container from a DRAFT or REJECTED request | PrincipalInvestigator, LabMember |
| POST | `/ehs/waste-pickup-requests/{id}/submit` | Submit for EHS review (from DRAFT or REJECTED) | PrincipalInvestigator |
| POST | `/ehs/waste-pickup-requests/{id}/reject` | Reject a SUBMITTED request with reason (items preserved for revision) | EHSAdmin |
| POST | `/ehs/waste-pickup-requests/{id}/schedule` | Schedule a SUBMITTED request into a dock window (30-minute buffered overlap check) | EHSAdmin |
| POST | `/ehs/waste-pickup-requests/{id}/complete` | Mark pickup executed; cascades containers to PICKED_UP and re-screens lab hazard totals | EHSAdmin |
| POST | `/ehs/waste-pickup-requests/{id}/cancel` | Cancel a SCHEDULED request; compensates by unlinking containers (they stay WASTE_TAGGED) | EHSAdmin |
| POST | `/ehs/inspections` | Schedule a lab inspection for an inspector (half-open overlap check per inspector) | EHSAdmin |
| GET | `/ehs/inspections` | List inspections with filters | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/inspections/{id}` | Get one inspection including computed scores and outcome | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/inspections/{id}/complete` | Complete with findings; computes scores/outcome, spawns one corrective action per finding, may cascade to FROZEN posture | EHSInspector |
| GET | `/ehs/labs/{id}/corrective-actions` | List corrective actions of a lab | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/inspections/{id}/corrective-actions` | List corrective actions spawned by one inspection | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/corrective-actions/{id}/submit` | PI submits remediation evidence (OPEN or REOPENED → SUBMITTED) | PrincipalInvestigator |
| POST | `/ehs/corrective-actions/{id}/verify` | Inspector verifies (decision=APPROVE → VERIFIED, REJECT → REOPENED); verifying inspector must differ from the completing inspector | EHSInspector |
| POST | `/ehs/training-assignments` | Assign hazard-class training to a worker with a due date | EHSAdmin, PrincipalInvestigator |
| GET | `/ehs/labs/{id}/training-assignments` | List training assignments of a lab | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| GET | `/ehs/workers/{id}/training-assignments` | List training assignments of a worker | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/training-assignments/{id}/complete` | Worker (or lab PI) marks assigned training complete | LabMember, PrincipalInvestigator |
| POST | `/ehs/incidents` | Report a spill/incident/near-miss for a lab | LabMember, PrincipalInvestigator, EHSAdmin |
| GET | `/ehs/labs/{id}/incidents` | List incidents of a lab | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/incidents/{id}/close` | Close a reported incident with a resolution | EHSAdmin |
| POST | `/ehs/registrations` | Create a controlled-substance/select-agent registration (PENDING); OCC via expected lab version; supersedes a PENDING same-type registration; conflicts with ACTIVE/SUSPENDED same-type | PrincipalInvestigator, EHSAdmin |
| GET | `/ehs/labs/{id}/registrations` | List registrations of a lab | EHSAdmin, EHSInspector, PrincipalInvestigator, LabMember |
| POST | `/ehs/registrations/{id}/activate` | Activate a PENDING registration or reinstate a SUSPENDED one | EHSAdmin |
| POST | `/ehs/registrations/{id}/suspend` | Suspend an ACTIVE registration | EHSAdmin |
| POST | `/ehs/registrations/{id}/surrender` | Surrender an ACTIVE or SUSPENDED registration (terminal; required before decommission) | EHSAdmin |

## 5. Error Code Catalogue

Error trigger conditions are described in context throughout §2 and §3; this catalogue is the authoritative list of error identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_LAB_STATE | 409 |
| ERR_CONTAINER_STATE | 409 |
| ERR_PICKUP_STATE | 409 |
| ERR_INSPECTION_STATE | 409 |
| ERR_CORRECTIVE_ACTION_STATE | 409 |
| ERR_REGISTRATION_STATE | 409 |
| ERR_TRAINING_STATE | 409 |
| ERR_INCIDENT_STATE | 409 |
| ERR_LAB_FROZEN | 409 |
| ERR_CONTROLLED_MATERIAL_UNREGISTERED | 422 |
| ERR_REQUIRED_TRAINING_INCOMPLETE | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DUPLICATE_BARCODE | 409 |
| ERR_PI_ALREADY_ASSIGNED | 409 |
| ERR_DUPLICATE_ACTIVE_REGISTRATION | 409 |
| ERR_AREA_CAPACITY_EXCEEDED | 409 |
| ERR_PICKUP_EMPTY | 422 |
| ERR_INVALID_WINDOW | 400 |
| ERR_INSPECTOR_SCHEDULE_CONFLICT | 409 |
| ERR_DOCK_WINDOW_CONFLICT | 409 |
| ERR_CROSS_LAB_REFERENCE | 422 |
| ERR_DECOMMISSION_BLOCKED | 409 |
