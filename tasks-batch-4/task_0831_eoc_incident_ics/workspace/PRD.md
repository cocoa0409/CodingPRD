# Eoc Incident Ics API — Product Requirements Document

## 1. Introduction

When a disaster strikes, an Emergency Operations Center (EOC) becomes the nerve center that turns chaos into coordinated response. This API is the digital backbone of that center, implementing the Incident Command System (ICS) discipline that jurisdictions rely on to activate incidents, request and track resources on ICS-213RR forms, publish Incident Action Plans, stand up shelters, negotiate mutual aid with neighboring jurisdictions, assess damage, and document the costs that ultimately flow into a FEMA Public Assistance (FEMA-PA) declaration and cost-recovery package.

The system exists because emergency response is simultaneously time-critical and heavily accountable. Every unit of personnel or equipment committed to one task cannot be double-committed to another; every dollar spent must be traceable and defensible against a cost ceiling; every shelter opened must be closeable only when truly empty; and every federal declaration hinges on verified damage crossing a legal threshold. The API therefore treats resource pools as strictly conserved quantities, treats the incident's financial ledger as an auditable running total, and treats each entity's lifecycle as an explicit state machine whose transitions carry precise preconditions and cascading side effects. A single incident aggregates many child records, and concurrent editors are guarded by optimistic concurrency so that a planner working from a stale view cannot silently overwrite newer work.

This document specifies the complete contract: the global rules that apply everywhere, the business workflows that span the response lifecycle from activation through demobilization, the full endpoint surface, and the catalogue of error codes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If `X-User-Role` is missing or is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles, corresponding to the ICS section that owns each resource type: `EOCManager`, `LogisticsChief`, `OperationsChief`, `PlanningChief`, `FinanceChief`, and `JurisdictionLiaison`. The `EOCManager` acts as EOC director / Incident Commander and owns the incident lifecycle, activation level, and jurisdiction registry. The `LogisticsChief` owns resource pools, sources and fills ICS-213RR requests, and drives mutual-aid negotiation from the requesting side. The `OperationsChief` submits resource requests, executes tasks, and runs shelters. The `PlanningChief` owns Incident Action Plans, tasks and objectives, and damage assessments. The `FinanceChief` owns FEMA-PA cost documentation. The `JurisdictionLiaison` represents a specific partner jurisdiction and responds to mutual-aid requests directed at that jurisdiction.

Five of these roles are operator identities not tied to any persisted entity. When `X-User-Role` is `EOCManager`, `LogisticsChief`, `OperationsChief`, `PlanningChief`, or `FinanceChief`, the `X-User-ID` value is an opaque operator identifier; the server may record it for audit but never compares it to any entity's `id`. In contrast, when `X-User-Role` is `JurisdictionLiaison`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks on any mutual-aid request compare the request's `to_jurisdiction_id` field to `X-User-ID`. A liaison whose `X-User-ID` does not match the `to_jurisdiction_id` of the mutual-aid request they are acting on is rejected with `ERR_NOT_RESOURCE_OWNER`.

All six roles may perform every read (GET) operation and may retrieve the computed situation-report snapshot. Write operations are restricted to the owning section as described throughout §3 and summarized in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system — incidents, jurisdictions, resource pools, resource requests, incident action plans, tasks, shelters, mutual-aid requests, damage assessments, and cost records — carries a standard set of system-managed fields:

- `id`: a server-minted UUID with no type prefix, unique across the system.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits marking when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at its initial value on creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control described in §2.6.

Whenever the server recomputes a derived field on a resource (for example, an incident's rolled-up cost totals or a pool's availability counters), that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. Referential Existence and Nested Retrieval

Requests routinely reference resources both in the URL path and in the request body via foreign-key fields. The system validates the existence of every referenced resource, evaluating path identifiers left-to-right before body-referenced foreign keys, and rejects the request on the first identifier that does not resolve. A retrieval of resource requests under a non-existent incident, for example, fails with `ERR_INCIDENT_NOT_FOUND` before any child lookup is attempted.

Each entity type has its own not-found code: `ERR_INCIDENT_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_RESOURCE_POOL_NOT_FOUND`, `ERR_RESOURCE_REQUEST_NOT_FOUND`, `ERR_IAP_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_SHELTER_NOT_FOUND`, `ERR_MUTUAL_AID_NOT_FOUND`, `ERR_DAMAGE_ASSESSMENT_NOT_FOUND`, and `ERR_COST_RECORD_NOT_FOUND`. All are returned with HTTP 404.

### 2.6. Optimistic Concurrency on the Incident Aggregate

An incident is a shared aggregate: many child records grow its rolled-up totals and advance its current operational plan. To prevent a client working from a stale incident view from silently clobbering newer work, two create operations are guarded by optimistic concurrency keyed on the incident's `version`.

Creating an Incident Action Plan requires the body to carry `expected_incident_version` holding the client's last observed `version` of the target incident. If that value does not equal the incident's current `version` — because another writer has advanced it since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A newly created plan legitimately supersedes the incident's prior current operational plan and advances the incident `version`, so a creator working from a stale view must be turned away rather than overwrite the newer plan.

Likewise, creating a Cost Record requires `expected_incident_version` to match the incident's current `version`; because a new cost record grows the incident's committed-cost ledger and advances the incident `version`, a creator whose `expected_incident_version` no longer matches (another cost record already landed) is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and neither of these two guarded creates may omit `expected_incident_version`.

### 2.7. Order of Validation

When several checks could reject a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then authorization for the acting role (`ERR_UNAUTHORIZED`), then existence of every referenced resource (the 404 family of §2.5). Ownership of a mutual-aid request by its liaison (`ERR_NOT_RESOURCE_OWNER`) is checked next. After that, the system verifies that the target resource is in a valid originating state for the requested transition (`ERR_INVALID_STATE`), then applies the incident optimistic-concurrency check (`ERR_STALE_VERSION`). Cross-aggregate reference integrity (`ERR_CROSS_INCIDENT_REFERENCE`) follows. Temporal-window checks come next (operational-period overlap, deployment-window capacity, and resource-window mismatch). Then the safety and readiness gates that block closing occupied shelters or unfinished incidents. Then cross-entity state and quantity/capacity gates (incident-active, IAP-published, request-filled, quantity, pool sufficiency, shelter capacity, activation-level validity, and missing transition target). Finally, the fiscal ceiling check on cost creation (`ERR_COST_CEILING_EXCEEDED`) is the lowest-priority gate. Where a later check would also fail, the earlier one in this ordering is the one reported.

### 2.8. Resource Pools as Conserved Quantities

A resource pool models a fixed inventory of interchangeable units, and the system treats that inventory as a strictly conserved quantity. A pool tracks `total_units` (the units it owns), `units_reserved` (units held by requests that have been sourced against it but not yet deployed), and `units_committed` (units held by requests that have been filled and deployed). Its `units_available` is always `total_units` minus `units_reserved` minus `units_committed`. `units_reserved` is the sum of `requested_quantity` over the requests currently sourced from the pool, and `units_committed` is the sum of `requested_quantity` over the requests currently filled from the pool. The invariant that `total_units` equals `units_available` plus `units_reserved` plus `units_committed` holds at every moment; reservations and commitments move units between the three buckets but never create or destroy them. All pool quantities are whole integer units and are never rounded.

### 2.9. Fiscal Ledger and Monetary Precision

An incident carries an auditable running ledger of the FEMA-PA costs documented against it. Its `total_committed_cost` is the sum, over every cost record in either `ESTIMATED` or `ACTUAL` status, of that record's contribution — the record's `actual_cost` when it has reached `ACTUAL`, otherwise its `estimated_cost`. Its `total_actual_cost` is the sum of `actual_cost` over cost records in `ACTUAL` status. Voiding a record removes its contribution from these sums, a compensating action that conserves the ledger. The `total_committed_cost` equals that defined sum at all times.

All monetary rollups are carried to two decimal places using the round-half-up method. Where per-record rounding is required (the federal-share rollups of §3.8), each record's share is rounded to two decimals before the records are summed — rounding is applied per record and then the rounded amounts are added, never the reverse.

### 2.10. Cascades and Hierarchical Consistency

Several operations mutate more than one entity in a single request. Demobilizing an incident cancels its still-live tasks, cancelling a task can release its backing resource request, and releasing a resource request restores units to its pool — a three-hop chain described in §3.9. Validating a damage assessment increases the incident's verified-damage total and may flip its declaration eligibility. Finalizing or voiding a cost record recomputes the incident's cost rollups. In each case, every entity touched by the cascade is independently mutated: its `updated_at` is refreshed and its `version` is incremented, exactly as a direct edit would do. These secondary effects are part of the contract, not incidental; §3 states each cascade hop explicitly so that an implementation reproduces the full chain rather than only its first hop.

## 3. Business Logic & Workflows

### 3.1. Incident Activation and the Operational Lifecycle

Everything in the system hangs off an **Incident**, created by an `EOCManager` with a human-readable `name`, a primary `hazard_type` (one of `FLOOD`, `WILDFIRE`, `HURRICANE`, `EARTHQUAKE`, `HAZMAT`, or `PUBLIC_HEALTH`), an anticipated `declaration_category` (`EMERGENCY` or `MAJOR_DISASTER`, defaulting to `EMERGENCY`), and a `cost_ceiling` capping the cumulative committed cost the incident may carry (defaulting to 100,000,000). A freshly created incident starts with `op_status` of `MONITORING`, `activation_level` of `LEVEL_3`, `declaration_status` of `INELIGIBLE`, and every rolled-up aggregate — `total_committed_cost`, `total_actual_cost`, `federal_share_estimated`, `federal_share_actual`, and `total_verified_damage` — at zero. Its `current_iap_id` is null until a plan is published, and its `activated_at` and `closed_at` timestamps are null.

An incident's operational status moves through a linear lifecycle driven only by the `EOCManager`. Activating the incident advances `op_status` from `MONITORING` to `ACTIVATED` and stamps `activated_at` with the request timestamp. Later, the incident advances from `ACTIVATED` to `DEMOBILIZING`, and finally from `DEMOBILIZING` to `CLOSED`, which stamps `closed_at`. The manager drives these moves by supplying a target `to_status` on the incident transition. The `activation_level` is an independent, parallel dimension: while an incident is `ACTIVATED`, the manager may change its level among `LEVEL_1` (full activation), `LEVEL_2`, and `LEVEL_3` by supplying `to_activation_level` on the same transition endpoint. A transition request that supplies neither `to_status` nor `to_activation_level` is rejected with `ERR_MISSING_TRANSITION_TARGET`, and a `to_activation_level` that is not one of the three levels, or a level change attempted while the incident is not `ACTIVATED`, is rejected with `ERR_INVALID_ACTIVATION_LEVEL`. The demobilization and closure cascades and the closure preconditions are detailed in §3.9.

Any user may pull a **situation report** for an incident — a computed snapshot, not a stored entity. It reports the incident's `incident_id`, current `op_status` and `activation_level`, the `open_shelter_count` (shelters currently `OPEN`), the `total_shelter_occupancy` (the sum of `current_occupancy` across the incident's open shelters), the `open_request_count` (resource requests still in flight — those in `SUBMITTED`, `NEEDS_INFO`, or `SOURCED`), the `filled_request_count` (requests in `FILLED`), the `total_verified_damage`, the `declaration_status`, the `total_committed_cost`, the `federal_share_estimated`, and the `federal_share_actual`.

### 3.2. Resource Requests: the ICS-213RR Lifecycle

Before any request can draw units, a `LogisticsChief` stands up **Resource Pools**. A pool is created under a jurisdiction, recording the owning `jurisdiction_id`, the `resource_type` it holds, its `total_units`, and optionally its `surge_cap` and `turnaround_hours` (both discussed in §3.3). On creation its `units_reserved` and `units_committed` start at zero and its `units_available` equals `total_units`.

Resource needs are captured on an ICS-213RR **Resource Request**, created by an `OperationsChief` against an incident. Creation records the `incident_id`, the requested `resource_type` (one of `PERSONNEL`, `VEHICLE`, `EQUIPMENT`, or `SUPPLY`), the `requested_quantity`, and an optional `priority` (`LOW`, `MEDIUM`, or `HIGH`, defaulting to `MEDIUM`). A new request begins in `DRAFT`, with `source_pool_id` null, `committed_units` at zero, and its `deploy_start`, `deploy_end`, `submitted_at`, `sourced_at`, and `demobilized_at` timestamps all null.

Submitting a request advances it from `DRAFT` to `SUBMITTED` and stamps `submitted_at`. Submission is performed by an `OperationsChief` and requires that the parent incident's `op_status` be `ACTIVATED` (otherwise `ERR_INCIDENT_NOT_ACTIVE`) and that `requested_quantity` be at least 1 (otherwise `ERR_INVALID_QUANTITY`). A `LogisticsChief` reviewing a submitted request may send it back for more information, moving it from `SUBMITTED` to `NEEDS_INFO`; the `OperationsChief` then resubmits, moving it from `NEEDS_INFO` back to `SUBMITTED` and refreshing `submitted_at`. This revision loop, which again requires the incident to be `ACTIVATED`, may repeat as many times as needed. From either `SUBMITTED` or `NEEDS_INFO`, a `LogisticsChief` may deny the request outright, moving it to the terminal `DENIED` state.

Sourcing is where a request draws against a pool. A `LogisticsChief` advances a request from `SUBMITTED` to `SOURCED`, supplying the `pool_id` of the chosen pool. The pool must exist (otherwise `ERR_RESOURCE_POOL_NOT_FOUND`); its `resource_type` must match the request's `resource_type` (otherwise `ERR_INSUFFICIENT_RESOURCES`); and the pool's `units_available` must be at least the request's `requested_quantity`, where exactly-equal is sufficient (otherwise `ERR_INSUFFICIENT_RESOURCES`). On success the request records `source_pool_id` as the chosen pool, sets `committed_units` equal to `requested_quantity`, stamps `sourced_at`, and the pool's `units_reserved` increases by `requested_quantity`, with `units_available` recomputed accordingly.

### 3.3. Deployment Windows and Filling Requests

Filling a sourced request turns a reservation into a committed deployment. A `LogisticsChief` advances a request from `SOURCED` to `FILLED`, supplying a deployment window as `deploy_start` and `deploy_end`; both must be present and `deploy_start` must be strictly earlier than `deploy_end`, otherwise the request is rejected with `ERR_VALIDATION`. On a successful fill, the pool's `units_reserved` decreases by `requested_quantity` and its `units_committed` increases by the same amount, keeping the pool's conserved-quantity invariant intact; `committed_units` on the request is unchanged.

Before the fill is allowed, the system enforces an aggregate deployment-capacity check against the pool. Each pool has an effective surge capacity equal to its `surge_cap` when one is set, and otherwise its `total_units` (a pool's `surge_cap`, when provided, may not exceed `total_units` and defaults to `total_units`). The pool also carries a `turnaround_hours` buffer, the rest time required between overlapping deployments of the same pool, defaulting to zero. To test a candidate window, the system considers every already-filled request drawn from the same pool whose deployment interval — expanded by `turnaround_hours` at both its start and its end — overlaps the candidate window, treating intervals as closed. It sums the `requested_quantity` of those overlapping filled requests, adds the candidate request's own `requested_quantity`, and permits the fill only if that total is at most the effective surge capacity; otherwise it rejects with `ERR_DEPLOYMENT_WINDOW_CONFLICT`. This is an aggregate concurrent-window test across all overlapping deployments with their buffers, distinct from the instantaneous `units_available` sufficiency test that governs sourcing.

### 3.4. Incident Action Plans, Tasks, and Objectives

Planning work is organized under **Incident Action Plans (IAPs)**, authored by a `PlanningChief`. Creating an IAP records its `incident_id` and an operational period defined by `operational_period_start` (inclusive) and `operational_period_end` (exclusive), forming a half-open interval, and starts the plan in `DRAFT`. Because a plan create grows the incident aggregate and advances the incident's current operational plan, the create carries `expected_incident_version` and is subject to the optimistic-concurrency rule of §2.6.

A `PlanningChief` publishes a plan by advancing it from `DRAFT` to `PUBLISHED`. Publication is allowed only if no other already-published IAP for the same incident has an operational period that overlaps this one; because periods are half-open, a plan whose start equals the immediately prior plan's end is adjacent, not overlapping, and is permitted. An overlap is rejected with `ERR_OPERATIONAL_PERIOD_OVERLAP`. On publication the plan stamps `published_at`, and the incident's `current_iap_id` is set to this plan's id, making it the incident's current operational plan. A published plan may later be advanced from `PUBLISHED` to `CLOSED`, but only if no task under it (matched by `iap_id`) is still in `PLANNED` or `ASSIGNED`; otherwise the closure is rejected with `ERR_INVALID_STATE`.

**Tasks** (ICS-204 assignments and objectives) are created by a `PlanningChief` under a plan. A task records its owning `iap_id`, a `title`, an optional `parent_task_id` referencing another task as its parent objective (null for a top-level objective), and an optional `resource_request_id` naming the resource assignment backing it (null when none). A new task starts in `PLANNED`, with `assigned_at` and `completed_at` null. Tasks may be listed and filtered by `iap_id`, `parent_task_id`, or `resource_request_id`.

An `OperationsChief` drives a task through its lifecycle. Assigning a task advances it from `PLANNED` to `ASSIGNED` and stamps `assigned_at`, subject to several gates: the task's IAP must be `PUBLISHED` (otherwise `ERR_IAP_NOT_PUBLISHED`); and when the task names a backing `resource_request_id`, that request must belong to the same incident as the task's IAP (otherwise `ERR_CROSS_INCIDENT_REFERENCE`), that request's `deploy_end` must be at or after the IAP's `operational_period_start` (otherwise `ERR_RESOURCE_WINDOW_MISMATCH`), and that request's `status` must be `FILLED` (otherwise `ERR_REQUEST_NOT_FILLED`). From `ASSIGNED`, an `OperationsChief` completes the task, advancing it to `COMPLETED` and stamping `completed_at`. A task may also be cancelled from either `PLANNED` or `ASSIGNED`, moving it to the terminal `CANCELLED` state; cancellation carries a resource-release cascade detailed in §3.9.

### 3.5. Sheltering Operations

Sheltering is run by the `OperationsChief`. A **Shelter** is created against an incident with its `incident_id`, a `name`, and a `capacity` (its maximum simultaneous occupancy, at least 1). It begins in `PLANNED`, with `current_occupancy` and `reserved_occupancy` at zero and `opened_at` and `closed_at` null.

Opening a shelter advances it from `PLANNED` to `OPEN` and stamps `opened_at`; it requires the parent incident to be `ACTIVATED` (otherwise `ERR_INCIDENT_NOT_ACTIVE`) and the shelter's `capacity` to be at least 1 (otherwise `ERR_VALIDATION`). While a shelter is open, the `OperationsChief` adjusts its occupancy by supplying deltas: `check_in` adds occupants to `current_occupancy`, `check_out` removes occupants from `current_occupancy`, `reserve` adds beds to `reserved_occupancy`, and `release_reserve` removes beds from `reserved_occupancy`. After any such adjustment, both `current_occupancy` and `reserved_occupancy` must remain at or above zero (otherwise `ERR_VALIDATION`), and the sum of `current_occupancy` and `reserved_occupancy` must not exceed `capacity`, where exactly-equal is allowed (otherwise `ERR_SHELTER_CAPACITY_EXCEEDED`). Gating a new check-in or reservation therefore uses projected availability — `capacity` minus `current_occupancy` minus `reserved_occupancy`, which counts reservations against capacity. When the situation report describes beds physically free right now, it instead uses strict availability — `capacity` minus `current_occupancy`, ignoring reservations; the two diverge whenever `reserved_occupancy` is above zero.

Closing a shelter advances it from `OPEN` to `CLOSED` and stamps `closed_at`, but only when it is truly empty: both `current_occupancy` and `reserved_occupancy` must be exactly zero. A close attempted with any current or reserved occupants is rejected with `ERR_SHELTER_OCCUPIED`.

### 3.6. Mutual Aid Negotiation (EMAC)

Partner jurisdictions are registered by the `EOCManager` as **Jurisdictions**, each recording a `name` and an optional `contact_email` point-of-contact (defaulting to null). When an incident's own pools are insufficient, a `LogisticsChief` opens an EMAC-style **Mutual Aid Request** to a partner jurisdiction, recording the requesting `incident_id`, the target `to_jurisdiction_id`, the `resource_type`, and the `requested_units`. The request opens in `REQUESTED`, with `offered_units`, `countered_units`, and `accepted_units` at zero and `resolved_at` null.

Negotiation alternates between the partner and the requester. The partner — acting as `JurisdictionLiaison` whose `X-User-ID` must match the request's `to_jurisdiction_id`, otherwise `ERR_NOT_RESOURCE_OWNER` — makes an offer, advancing the request from `REQUESTED` to `OFFERED` and setting `offered_units`, which must be at least 1 (otherwise `ERR_INVALID_QUANTITY`). From `OFFERED`, the `LogisticsChief` may counter, advancing to `COUNTERED` and setting `countered_units`, which must likewise be at least 1 (otherwise `ERR_INVALID_QUANTITY`). The liaison may then re-offer, advancing from `COUNTERED` back to `OFFERED` with a fresh `offered_units` of at least 1 (again subject to the ownership check) — a negotiation loop that may repeat. From `OFFERED`, the `LogisticsChief` resolves the negotiation in one of two ways: accepting advances it to the terminal `ACCEPTED` state — which requires the incident to be `ACTIVATED` (otherwise `ERR_INCIDENT_NOT_ACTIVE`), sets `accepted_units` equal to the current `offered_units`, and stamps `resolved_at` — or declining advances it to the terminal `DECLINED` state and stamps `resolved_at`. Separately, from the initial `REQUESTED` state the `LogisticsChief` may withdraw the request, moving it to the terminal `WITHDRAWN` state and stamping `resolved_at`.

### 3.7. Damage Assessment and the Federal Declaration

Damage feeding the federal declaration is captured as **Damage Assessments**, authored by a `PlanningChief` against an incident. Each records its `incident_id`, the `site_name` assessed, the `estimated_loss` in dollars (at least zero), and the FEMA-PA `infrastructure_category` (one of `CAT_A_DEBRIS`, `CAT_B_PROTECTIVE`, `CAT_C_ROADS`, `CAT_E_BUILDINGS`, or `CAT_G_PARKS`). An assessment starts in `DRAFT`, with `validated_at` null.

A `PlanningChief` adjudicates each assessment. Rejecting one moves it to the terminal `REJECTED` state with no ledger effect. Validating one advances it from `DRAFT` to `VALIDATED`, stamps `validated_at`, and recomputes the incident's `total_verified_damage` as the sum of `estimated_loss` over the incident's assessments that are in `VALIDATED` status. The incident's `declaration_status` is then recomputed: it becomes `ELIGIBLE` when `total_verified_damage` is at least the declaration threshold of 5,000,000 dollars, and remains `INELIGIBLE` below that; a total exactly equal to 5,000,000 is `ELIGIBLE`. Because the federal cost-share percentage depends on `declaration_status`, a validation that flips the incident to `ELIGIBLE` also refreshes the incident's federal-share rollups described in §3.8.

### 3.8. FEMA-PA Cost Recovery

FEMA-PA costs are documented by the `FinanceChief` as **Cost Records** against an incident. Creating one records the `incident_id`, an optional backing `resource_request_id`, the FEMA-PA `category` (one of `LABOR`, `EQUIPMENT`, `MATERIALS`, or `CONTRACT`), the `estimated_cost` (at least zero), and an `eligible` flag stating whether the cost is FEMA-PA eligible for federal share (defaulting to true). The record opens in `ESTIMATED`, with `actual_cost` null and `finalized_at` null. Because a cost record grows the incident's committed-cost ledger, the create carries `expected_incident_version` and is subject to the optimistic-concurrency rule of §2.6. The create also enforces the cost ceiling: adding the new record's `estimated_cost` to the incident's `total_committed_cost` must not push that total above the incident's `cost_ceiling`, where a result exactly equal to the ceiling is allowed; a create that would exceed it is rejected with `ERR_COST_CEILING_EXCEEDED`.

A `FinanceChief` finalizes a record by advancing it from `ESTIMATED` to `ACTUAL`, supplying an `actual_cost` that must be present and at least zero (otherwise `ERR_VALIDATION`); this sets `actual_cost`, stamps `finalized_at`, and recomputes the incident's cost rollups. A record may also be voided, moving it from `ESTIMATED` or from `ACTUAL` to the terminal `VOID` state; voiding removes the record's contribution from the incident's totals, a compensating action that conserves the ledger.

The federal cost-share percentage applied to a record is chosen jointly from the incident's `declaration_status`, `declaration_category`, and `total_verified_damage`. When `declaration_status` is not `ELIGIBLE`, the percentage is zero. Otherwise, when `declaration_category` is `MAJOR_DISASTER` and `total_verified_damage` is at least the enhanced damage threshold of 10,000,000 dollars, the enhanced share of 90 percent applies; in every other eligible case the base share of 75 percent applies.

The incident's federal-share rollups are computed per record and then summed. `federal_share_estimated` is the sum, over the incident's eligible cost records in `ESTIMATED` status, of each record's `estimated_cost` multiplied by the applicable percentage and rounded to two decimal places; `federal_share_actual` is the sum, over the incident's eligible cost records in `ACTUAL` status, of each record's `actual_cost` multiplied by the applicable percentage and rounded to two decimal places. Only records whose `eligible` flag is true contribute. The rounding order is fixed: each record's share is rounded to two decimals using round-half-up first, and only then are the rounded shares summed — summing first and rounding once would yield a different cent total and is not used. The estimated-basis rollup uses each record's `estimated_cost` while the actual-basis rollup uses each record's `actual_cost`; the two diverge once a record's `actual_cost` differs from its `estimated_cost`. Alongside these, the incident's `total_committed_cost` and `total_actual_cost` are maintained exactly as defined in §2.9. All of these rollups are refreshed whenever a cost record is created, finalized to `ACTUAL`, or voided, and whenever the incident's `declaration_status` changes.

### 3.9. Demobilization, Cascades, and Closure

Winding an incident down is a cascade that spans several entities. When the `EOCManager` advances an incident from `ACTIVATED` to `DEMOBILIZING`, the first hop cancels work: every task under the incident's plans whose status is `PLANNED` or `ASSIGNED` is transitioned to `CANCELLED`. Each such cancellation triggers the second hop: if the cancelled task names a backing `resource_request_id` whose request is in `SOURCED` or `FILLED`, that request is transitioned to `DEMOBILIZED`. That demobilization triggers the third hop against the pool: a request demobilized from `SOURCED` releases its reservation, decreasing the pool's `units_reserved` by `requested_quantity`; a request demobilized from `FILLED` releases its commitment, decreasing the pool's `units_committed` by `requested_quantity`. In both cases the pool's `units_available` is restored so that `total_units` is conserved, and the request stamps `demobilized_at`. A `LogisticsChief` may also demobilize an individual `SOURCED` or `FILLED` request directly, driving the same pool-release effects. Every entity touched along the chain is independently mutated as described in §2.10.

Closing the incident is the final, gated step. The `EOCManager` advances the incident from `DEMOBILIZING` to `CLOSED` only when the incident is genuinely wound down: no resource request for the incident may remain in `SUBMITTED`, `NEEDS_INFO`, `SOURCED`, or `FILLED`; no shelter for the incident may remain in `PLANNED` or `OPEN`; and no cost record for the incident may remain in `ESTIMATED`. If any of these readiness conditions fails, the closure is rejected with `ERR_INCIDENT_NOT_READY_TO_CLOSE`. On success the incident stamps `closed_at`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch, list, or transition an existing resource return `200 OK`. Every request must satisfy the header, authorization, existence, and business rules described throughout §2 and §3; this table lists only the method, path, purpose, and the roles authorized to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/eoc/incidents` | Create an incident | EOCManager |
| GET | `/eoc/incidents/{id}` | Fetch a single incident | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/incidents/{id}/transition` | Advance op_status and/or change activation level | EOCManager |
| GET | `/eoc/incidents/{id}/situation-report` | Computed situation-report snapshot | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/incidents/{id}/resource-requests` | List resource requests for an incident | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/incidents/{id}/incident-action-plans` | List IAPs for an incident | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/incidents/{id}/shelters` | List shelters for an incident | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/incidents/{id}/damage-assessments` | List damage assessments for an incident | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/jurisdictions` | Register a mutual-aid partner jurisdiction | EOCManager |
| GET | `/eoc/jurisdictions/{id}` | Fetch a single jurisdiction | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/jurisdictions/{id}/resource-pools` | List resource pools owned by a jurisdiction | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/resource-pools` | Create a resource pool under a jurisdiction | LogisticsChief |
| GET | `/eoc/resource-pools/{id}` | Fetch a single resource pool | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/resource-pools/{id}/resource-requests` | List resource requests sourced from a pool | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/resource-requests` | Create an ICS-213RR resource request | OperationsChief |
| POST | `/eoc/resource-requests/{id}/transition` | Advance a resource request | OperationsChief, LogisticsChief |
| POST | `/eoc/incident-action-plans` | Create an IAP (OCC on incident) | PlanningChief |
| POST | `/eoc/incident-action-plans/{id}/transition` | Publish or close an IAP | PlanningChief |
| POST | `/eoc/tasks` | Create a task/objective under an IAP | PlanningChief |
| GET | `/eoc/tasks/{id}` | Fetch a single task | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/tasks` | List/filter tasks | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/tasks/{id}/transition` | Advance a task | OperationsChief |
| POST | `/eoc/shelters` | Create a shelter for an incident | OperationsChief |
| POST | `/eoc/shelters/{id}/transition` | Open or close a shelter | OperationsChief |
| POST | `/eoc/shelters/{id}/occupancy` | Adjust shelter occupancy | OperationsChief |
| POST | `/eoc/mutual-aid-requests` | Open a mutual-aid (EMAC) request | LogisticsChief |
| GET | `/eoc/mutual-aid-requests/{id}` | Fetch a single mutual-aid request | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/mutual-aid-requests` | List/filter mutual-aid requests | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/mutual-aid-requests/{id}/transition` | Negotiate/resolve mutual aid | LogisticsChief, JurisdictionLiaison |
| POST | `/eoc/damage-assessments` | Record a damage assessment | PlanningChief |
| POST | `/eoc/damage-assessments/{id}/transition` | Validate or reject a damage assessment | PlanningChief |
| POST | `/eoc/cost-records` | Document a FEMA-PA cost estimate (OCC on incident) | FinanceChief |
| GET | `/eoc/cost-records/{id}` | Fetch a single cost record | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| GET | `/eoc/cost-records` | List/filter cost records | EOCManager, LogisticsChief, OperationsChief, PlanningChief, FinanceChief, JurisdictionLiaison |
| POST | `/eoc/cost-records/{id}/transition` | Finalize (ACTUAL) or void a cost record | FinanceChief |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_RESOURCE_POOL_NOT_FOUND` | 404 |
| `ERR_RESOURCE_REQUEST_NOT_FOUND` | 404 |
| `ERR_IAP_NOT_FOUND` | 404 |
| `ERR_TASK_NOT_FOUND` | 404 |
| `ERR_SHELTER_NOT_FOUND` | 404 |
| `ERR_MUTUAL_AID_NOT_FOUND` | 404 |
| `ERR_DAMAGE_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_COST_RECORD_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CROSS_INCIDENT_REFERENCE` | 409 |
| `ERR_OPERATIONAL_PERIOD_OVERLAP` | 409 |
| `ERR_DEPLOYMENT_WINDOW_CONFLICT` | 409 |
| `ERR_RESOURCE_WINDOW_MISMATCH` | 409 |
| `ERR_INCIDENT_NOT_ACTIVE` | 409 |
| `ERR_IAP_NOT_PUBLISHED` | 409 |
| `ERR_REQUEST_NOT_FILLED` | 409 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_INSUFFICIENT_RESOURCES` | 409 |
| `ERR_SHELTER_CAPACITY_EXCEEDED` | 409 |
| `ERR_SHELTER_OCCUPIED` | 409 |
| `ERR_INVALID_ACTIVATION_LEVEL` | 422 |
| `ERR_MISSING_TRANSITION_TARGET` | 422 |
| `ERR_INCIDENT_NOT_READY_TO_CLOSE` | 409 |
| `ERR_COST_CEILING_EXCEEDED` | 409 |
