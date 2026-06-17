# Concrete & Paving Contractor API — Product Requirements Document

## 1. Introduction

Concrete and paving contractors live at the intersection of field reality and back-office accounting: a job is scoped in square feet and slab thickness, priced in cubic yards of mix and tiered labor, gated by weather and cure chemistry, governed by permits and inspectors, and paid out in deposit, progress, and final draws against a contract value that itself drifts every time a change order is approved. This document specifies a REST API that manages that full lifecycle as a single coherent system, with the **Project** as the aggregate root around which estimates, flatwork segments, permits, material orders, crew bookings, change orders, draws, and warranties all revolve.

The API exists to make the implicit explicit. Estimating a job and ordering the mix for it use *different* cubic-yard math, and the system pins both so neither can drift. Contract value has two simultaneous readings — a forward-looking provisional figure that counts reviews in flight, and a committed figure that counts only what has been signed — and the system computes both rather than forcing the operator to choose. Money cannot be drawn faster than work is committed, the same finance officer cannot both approve a change order and release a draw on one project, and concrete cannot be declared done before its mix-specific cure window has physically elapsed. Each of these is a hard rule, not a guideline.

The intended readers are the engineers who will implement the service. The sections below first establish the global contract — authentication, response envelope, pagination, concurrency, and the cross-cutting financial and safety principles — and then walk the business workflows in narrative form. Field names, thresholds, and state names are deliberately introduced where they make business sense; implementers should expect to assemble the complete behavior of a single endpoint from more than one place.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Estimator`, `ProjectManager`, `FinanceOfficer`, and `Inspector`. An `Estimator` drafts project scope and estimates. A `ProjectManager` approves estimates, schedules the job, advances the pour-and-cure lifecycle, and manages crews, equipment, material orders, holds, and warranty issuance. A `FinanceOfficer` submits, reviews, and approves change orders and requests, releases, and voids draws. An `Inspector` issues, closes, and revokes permits and files and resolves warranty defect claims.

For all four roles the `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity; the server never compares it to any entity's `id`. The server does, however, record it where a workflow demands an audit trail or a segregation check: when a `FinanceOfficer` submits or last revises a change order, that user's `X-User-ID` is stored as the change order's `submitted_by_user_id`, and when a `FinanceOfficer` releases a draw, their `X-User-ID` is stored as the draw's `released_by_user_id`. These recorded identifiers drive the segregation-of-duties rules in §3, never resource ownership.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip from the front of the result and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Most resources in this system carry a uniform set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix, used for identity only and never as a business-decision input. Each has a `created_at` timestamp in ISO 8601 UTC with three fractional digits, fixed at creation. Each has an `updated_at` timestamp in the same format, refreshed on every mutation including mutations caused by a cascade from another resource. And each has a `version`: an integer that starts at 1 on creation and increments by exactly 1 on every mutation, serving as the optimistic-concurrency token described in §2.7. These uniform fields apply to `Project`, `FlatworkSegment`, `Estimate`, `Permit`, `MaterialOrder`, `Crew`, `Equipment`, `CrewAssignment`, `ChangeOrder`, `Draw`, and `Warranty`.

The lone exception is the **weather reading**, which is an immutable sub-event appended to a material order. A weather reading carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never modified after creation.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths whose segments name a parent resource and then a child or collection. The system validates the identifiers in such a path strictly left-to-right and rejects the request at the *first* identifier that does not resolve to an existing resource, returning `ERR_NOT_FOUND` (HTTP 404). A request for a material order under a project that does not exist, for example, fails on the project before the material order is ever consulted. The same left-to-right discipline governs every path-parameterized endpoint.

Separately from path identifiers, several create and link operations carry foreign keys in the request body — for instance a `project_id`, a `crew_id`, an `equipment_id`, or a `material_order_id`. When a body foreign key points at a resource that does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). Path existence is checked before body foreign keys.

### 2.6. Validation Ordering

When a single request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) role authorization, yielding `ERR_FORBIDDEN_ROLE`; (3) existence of path-referenced resources, yielding `ERR_NOT_FOUND`; (4) existence of body foreign keys, yielding `ERR_FK_NOT_FOUND`; (5) request well-formedness — required fields present and well-typed, enum values within their declared sets, and numeric ranges satisfied — yielding `ERR_INVALID_REQUEST` (HTTP 422); (6) that the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE` (HTTP 409); (7) cross-entity transition guards, yielding `ERR_PRECONDITION_NOT_MET` (HTTP 409); and (8) the optimistic-concurrency version check, yielding `ERR_STALE_PROJECT_VERSION` (HTTP 412). Checks specific to a single workflow — the weather gate, the cure-window timer, crew and equipment double-booking, segregation of duties, the draw waterfall cap, and the draw sequence rule — are evaluated after these foundational checks, as described in the workflows that own them; their relative ordering is detailed where each rule is introduced.

### 2.7. Optimistic Concurrency Control

Three project-mutating operations are guarded by optimistic concurrency against the `Project` aggregate, and for these the client must supply `expected_project_version` in the request body as a required field carrying the `version` of the project the client last observed.

When a `ProjectManager` approves an estimate, the request must carry `expected_project_version` equal to the project's current `version`; a mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

When a `FinanceOfficer` approves a change order, the request must carry `expected_project_version` matching the project's current `version`. Because a separate change-order approval or review legitimately advances the project's committed and provisional contract values — and therefore its `version` — between the client's read and this approval, a stale view would recompute the contract value on an outdated base. The approval is therefore refused with `ERR_STALE_PROJECT_VERSION` (HTTP 412) when the supplied version no longer matches.

When a `FinanceOfficer` releases a draw, the request must likewise carry `expected_project_version` matching the project's current `version`. Another draw release or change-order approval legitimately changes `total_drawn_amount` or `committed_contract_value` (and the project's `version`) between the client's read and this release; a stale view would let the waterfall cap be evaluated against an outdated draw total, so the release is refused with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

No other endpoint takes a version field. Operations not named above proceed without an OCC check.

### 2.8. Hierarchical Consistency and Cascades

The `Project` is the aggregate root, and most other resources hang off it. State changes propagate **upward and outward** through documented cascades rather than being declared by the client. When a material order's pour is completed, the order's own transition to `POURED` bubbles the owning project from `SCHEDULED` to `POURED`, which in turn triggers a recomputation of the project's `warranty_risk_score`; each hop is caused by the resulting state of the prior hop. When a project completes, every still-`BOOKED` crew assignment on it is released. When a permit is revoked while its project is `SCHEDULED`, the project is forced into a hold. Every resource a cascade touches has its `updated_at` refreshed and its `version` incremented by 1, exactly as a direct mutation would. Where a cascade advances both a child and the project, both versions increment.

### 2.9. Monetary Precision and Rounding

All monetary amounts and contract values are carried to two decimal places, and every rounding step uses the round-half-up convention. Where a calculation specifies that individual line items are each rounded before being summed, that order is binding: rounding the components first and the total once more is the wrong order and is forbidden. Cubic-yard figures are whole integers, reached by the ceiling operations described with each calculation. The `warranty_risk_score` is an integer clamped to the range 0 through 100 inclusive.

### 2.10. The Logical Clock

Cure-window evaluation and project completion depend on the current UTC instant. To make these time-dependent rules testable, the system exposes an administrative test-driving capability that sets the server's logical current-UTC clock to a supplied `to_iso8601` instant. All comparisons against cure windows and completion timers read this logical clock. This capability is restricted to a `ProjectManager` and returns no resource body.

## 3. Business Logic & Workflows

### 3.1. Scoping a Project: Segments and the Two Cubic-Yard Calculations

An `Estimator` opens a job by creating a **Project**, supplying a `site_name` for the job site and a `client_name` for the client. A new project begins in `DRAFT` with a `base_contract_amount` of 0.00 and every derived financial figure — `provisional_contract_value`, `committed_contract_value`, `total_drawn_amount` — also at 0.00, a `warranty_risk_score` of 0, a `status_before_hold` of null, and an `approved_estimate_id` of null.

Into a `DRAFT` project the `Estimator` adds one or more **flatwork segments**, each describing a pour area. A segment carries a `label` such as a driveway or patio, an `area_sqft` plan area that must be strictly greater than zero, a `thickness_in` slab thickness that must be strictly greater than zero, a `finish_grade`, and a `reinforcement` type. The `finish_grade` is one of `BROOM`, `EXPOSED_AGGREGATE`, or `STAMPED`, defaulting to `BROOM`; the `reinforcement` is one of `NONE`, `MESH`, or `REBAR`, defaulting to `NONE`. A segment is owned by its project through the project identity in its path. Adding a segment increments the project's `version`.

The volume of concrete a job needs is computed two different ways, and the difference is intentional. The common starting point treats every segment identically regardless of finish or reinforcement: for each segment, the raw volume in cubic yards is its `area_sqft` multiplied by its `thickness_in` divided by 12 (converting inches of thickness to feet) and then divided by 27 (converting cubic feet to cubic yards), and that raw figure is then multiplied by 1.10 to apply a ten-percent waste factor.

The **planning** figure, `provisional_cubic_yards`, sums the waste-adjusted volumes of all the project's segments first and only then rounds the grand total up to the next whole cubic yard. The **ordering** figure, `order_cubic_yards`, instead rounds *each* segment's waste-adjusted volume up to the next quarter-yard ticket increment first — multiply the segment's adjusted volume by 4, round that up to the next whole number, and divide by 4 — then sums those per-segment ticket quantities and rounds the sum up to the next whole cubic yard. Because the rounding happens per line item before summing, the ordering figure can come out strictly larger than the planning figure on the very same segments; this reflects supplier truck-ticket reality, where each delivery is billed in quarter-yard increments.

### 3.2. Pricing the Estimate

When the `Estimator` creates an **Estimate**, the project moves from `DRAFT` to `ESTIMATING`, provided it is currently `DRAFT` and has at least one flatwork segment. The estimate is created in `DRAFT` status, and the system computes its figures in one shot. The estimate records `total_sqft` as the sum of `area_sqft` across the project's segments, rounded to two decimal places, and `provisional_cubic_yards` from the planning variant of §3.1.

Labor is priced on a marginal, progressive tier schedule against the total square footage. The first 500 square feet are billed at 9.00 per square foot. Square footage above 500 and up to 1,500 — that is, the next 1,000 square feet — is billed at 7.50 per square foot. Any square footage beyond 1,500 is billed at 6.00 per square foot. Summing the amounts from the tiers the job reaches yields the labor base.

That labor base is then scaled by a single **finish multiplier**, taken as the maximum finish multiplier across all the project's segments, where a `BROOM` finish multiplies by 1.00, `EXPOSED_AGGREGATE` by 1.20, and `STAMPED` by 1.35. On top of the scaled labor, a **reinforcement add** is applied as the sum over every segment of that segment's per-square-foot reinforcement rate times its `area_sqft`, where `NONE` adds 0.00 per square foot, `MESH` adds 0.60, and `REBAR` adds 1.25. The `labor_subtotal` is the scaled labor base plus the reinforcement add, rounded to two decimal places.

The `material_subtotal` is the estimate's `provisional_cubic_yards` multiplied by the mix rate of 145.00 per cubic yard, rounded to two decimal places. The `estimate_total` is then the rounded `labor_subtotal` added to the rounded `material_subtotal`. The order is pinned: each subtotal is rounded to cents on its own before the two are added, and summing the raw figures and rounding once at the end is incorrect.

A project holds at most one `DRAFT` estimate at a time. If an `Estimator` creates another estimate while the project is already `ESTIMATING`, the prior `DRAFT` estimate is moved to `SUPERSEDED` and the new one becomes the live `DRAFT`; the project's `status` stays `ESTIMATING`. Each such creation increments the project's `version`.

### 3.3. Approving, Rejecting, and the Contract Baseline

A `ProjectManager` decides the estimate's fate. Approving an estimate carries the project from `ESTIMATING` to `APPROVED`. The approval names which estimate to approve through an `estimate_id` in the body and, per §2.7, an `expected_project_version`. The named estimate must belong to this project and be in `DRAFT`; the project must currently be `ESTIMATING`. On approval the chosen estimate moves to `APPROVED` and any other `DRAFT` estimate on the project is moved to `SUPERSEDED`. The project's `approved_estimate_id` is set to the chosen estimate, and the project's `base_contract_amount` is set to that estimate's `estimate_total`. The project then recomputes both contract-value figures and advances to `APPROVED`, incrementing its `version`. The approved estimate is a version-pinned forward pointer rather than a parent foreign key; the estimate itself is discovered through the project's estimate collection.

Alternatively, a `ProjectManager` may reject the project while it is `ESTIMATING`, which moves it to the terminal `REJECTED` state, sets every `DRAFT` estimate on the project to `SUPERSEDED`, and increments the project's `version`.

The two contract-value figures express the same money from two vantage points. The **provisional contract value** is forward-looking: it is the project's `base_contract_amount` plus the sum of `delta_amount` over every change order whose status is `UNDER_REVIEW` or `APPROVED`, rounded to two decimal places. Because it counts reviews in flight as if they will land, it can exceed the committed figure while reviews are open. The **committed contract value** is the conservative, billable reading: it is the `base_contract_amount`, then each `APPROVED` change order's `delta_amount` added in `created_at` ascending order, with the running total rounded to two decimal places. It counts only signed change orders and equals the provisional figure exactly when no change order is `UNDER_REVIEW`. Both figures are recomputed at estimate approval and at every change-order transition that moves an order into or out of the relevant status sets, and both are recomputed when a project is read.

### 3.4. Permits and the Inspector's Authority

Once a project is approved, a `ProjectManager` applies for a **Permit**, supplying the `jurisdiction` (the issuing authority) and the authority-assigned `permit_number`. A new permit starts in `APPLIED`. An `Inspector` then drives the permit: issuing it moves `APPLIED` to `ISSUED`; closing it moves `ISSUED` to `CLOSED`, but only when the owning project has reached `COMPLETED` — a close attempted on a project that is not yet `COMPLETED` is refused as a precondition failure with `ERR_PRECONDITION_NOT_MET`.

An `Inspector` may also revoke a permit from either `APPLIED` or `ISSUED`, moving it to the terminal `REVOKED` state. Revocation carries a consequence: if the owning project is in `SCHEDULED` at the moment of revocation, the project is forced into `ON_HOLD` and its `status_before_hold` is snapshotted as `SCHEDULED`, with the project's `version` incremented alongside the permit's. If the project is not `SCHEDULED`, only the permit's `version` increments.

### 3.5. Ordering Mix and the Weather Gate

A `ProjectManager` places a **MaterialOrder** against the project, choosing a `mix_type` of `STANDARD`, `HIGH_EARLY`, or `FIBER`, and supplying a `pour_scheduled_start` instant and a planned `pour_duration_hours` that must be strictly greater than zero. At placement the system snapshots `order_cubic_yards` using the ordering variant of §3.1, sets the order to `ORDERED`, leaves `pour_completed_at` and `cure_window_end` null, and increments the project's `version`.

Either a `ProjectManager` or an `Inspector` may append **weather readings** to a material order to document field conditions. Each reading carries a `reading_at` instant, an ambient `temp_f` in Fahrenheit, and a `precip_pct` between 0 and 100 inclusive. Readings accumulate as an immutable log against the order through its `material_order_id`.

Before a project can be poured it must be scheduled. A `ProjectManager` schedules an `APPROVED` project, advancing it to `SCHEDULED`, but only when three cross-entity conditions all hold: the project has a permit in `ISSUED` status, at least one material order in `ORDERED` status, and at least one crew assignment in `BOOKED` status. If any of the three is missing, scheduling is refused with `ERR_PRECONDITION_NOT_MET`.

Starting the pour advances a material order from `ORDERED` to `POURING`, and is permitted only while the order is `ORDERED` and its project is `SCHEDULED`. This action is guarded by the **weather gate**: the system examines every weather reading on the order whose `reading_at` falls in the half-open window that begins at `pour_scheduled_start` and ends `pour_duration_hours` later — that is, at or after the scheduled start and strictly before the start-plus-duration instant. If any such in-window reading has a `temp_f` below 40, or a `temp_f` above 90, or a `precip_pct` at or above 50, the pour start is blocked with `ERR_WEATHER_OUT_OF_RANGE` (HTTP 409). The block can be overridden: the start-pour request accepts an optional `force_override` flag, and when it is set to true the pour proceeds despite an out-of-range reading. Forcing the pour over a bad reading sets a weather-violation flag on the order that later feeds the warranty risk score.

### 3.6. Completing the Pour and the Cure Cascade

Completing the pour moves a material order from `POURING` to `POURED`. The request supplies the `completed_at` instant, which the system records as the order's `pour_completed_at`. The system then computes the order's `cure_window_end` as `pour_completed_at` plus the mix-specific cure duration: a `STANDARD` mix cures for 168 hours, a `FIBER` mix likewise for 168 hours, and a `HIGH_EARLY` mix for 72 hours. This completion sets off a depth-three cascade: the order reaching `POURED` bubbles the project from `SCHEDULED` to `POURED`, and the project reaching `POURED` with a now-populated cure window triggers a recomputation of its `warranty_risk_score`. Both the material order's `version` and the project's `version` increment.

A `ProjectManager` then begins curing, advancing the project from `POURED` to `CURING`, which requires the project to be `POURED` and its poured material order to have a non-null `cure_window_end`. A material order may also be cancelled from `ORDERED`, moving it to the terminal `CANCELLED` state and incrementing its `version`.

### 3.7. The Warranty Risk Score

The `warranty_risk_score` is a quality-risk indicator computed additively and then clamped to the range 0 through 100 inclusive. It starts at zero and accumulates four contributions. First, if the order's pour has been completed but the span from `pour_completed_at` to `cure_window_end` is shorter than the cure hours the mix requires, a cure-window compromise adds 30. Second, if the pour was started over an out-of-range weather reading with the override flag set, a weather violation adds 25. Third, the score adds 15 for each defect claim, multiplying 15 by the total `defect_claims_count` summed across the project's warranties. Fourth, if any flatwork segment on the project has a `reinforcement` of `NONE`, an unreinforced-scope penalty adds 10. A score that would exceed 100 saturates at 100, and the score never drops below 0. The score is recomputed when a pour completes, when a defect claim is filed, and whenever a project is read.

### 3.8. Crews, Equipment, and Booking Conflicts

Crews and equipment are flat resource pools, not children of any project. A `ProjectManager` creates a **Crew** with a `crew_name`, a `skill` of `FLATWORK`, `FINISHING`, or `PAVING`, and a `headcount` that must be at least 1. A `ProjectManager` likewise creates an **Equipment** asset with an `asset_name` and an `asset_type` of `PUMP_TRUCK`, `POWER_TROWEL`, `SCREED`, or `MIXER`.

A `ProjectManager` books a crew onto a project by creating a **CrewAssignment**, supplying the `crew_id` of the crew, optionally an `equipment_id` for a reserved asset (null when no equipment is reserved), and a booking window defined by `window_start` and `window_end`, where `window_end` must be strictly after `window_start`. A new assignment starts in `BOOKED` and increments the project's `version`. Booking windows are half-open: an interval is considered to occupy from its start inclusive up to but not including its end.

Two temporal conflicts are checked at booking time. A new assignment for a given `crew_id` is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409) when its half-open window overlaps the window of any existing `BOOKED` assignment for the same crew; because the intervals are half-open, two windows that merely touch — one ending exactly when the next begins — do not overlap and are allowed. A new assignment for a given `equipment_id` is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED` (HTTP 409) when its window, after each existing equipment booking is expanded by a two-hour cleandown buffer on each side, falls inside that buffered span. Concretely, an existing booking running from its start to its end is treated as occupying from two hours before its start up to two hours after its end; a new window that touches that buffered edge exactly does not collide, but a window that reaches inside it does.

A booked assignment is released — moving from `BOOKED` to the terminal `RELEASED` — either explicitly by a `ProjectManager` or automatically when its project completes, as described in §3.9. Either way the assignment's `version` increments.

### 3.9. Holds, Resumption, and Project Completion

A project under way is not always able to proceed, so a `ProjectManager` may place an `APPROVED` or `SCHEDULED` project on hold, capturing the current status into `status_before_hold` and moving the project to `ON_HOLD`. Resuming the project restores it to whatever `status_before_hold` recorded — back to `APPROVED` if it was held from `APPROVED`, or back to `SCHEDULED` if it was held from `SCHEDULED` — and clears `status_before_hold` to null. Each hold and each resume increments the project's `version`.

Completion is the lifecycle's terminus. A `ProjectManager` completes a `CURING` project, moving it to the terminal `COMPLETED` state, but only when two further conditions hold beyond the curing status: the logical current UTC instant has reached or passed the poured material order's `cure_window_end`, and the project has a warranty in `ACTIVE` status. Attempting completion before the cure window has elapsed is refused with `ERR_CURE_WINDOW_NOT_ELAPSED` (HTTP 409); the absence of an `ACTIVE` warranty is a precondition failure yielding `ERR_PRECONDITION_NOT_MET`. On successful completion every crew assignment still in `BOOKED` is released to `RELEASED`, the project's `version` increments, and each released assignment's `version` increments as well.

### 3.10. Change Orders and the Revision Cycle

A `FinanceOfficer` submits a **ChangeOrder** against a project, supplying a `description` of what the change covers, a signed `delta_amount` in dollars where a positive figure adds to the contract and a negative figure deducts, and an optional `delta_sqft` signed change to the project's scope square footage that defaults to 0. A submitted change order starts in `SUBMITTED`, and the submitting officer's `X-User-ID` is recorded as `submitted_by_user_id`; the project's `version` increments.

Review proceeds as a cycle. Beginning review moves a `SUBMITTED` change order to `UNDER_REVIEW`, which brings the order into the forward-looking provisional sum and so recomputes the project's `provisional_contract_value`. From `UNDER_REVIEW`, a `FinanceOfficer` has three choices. Requesting a revision moves the order to `REVISION_REQUESTED`, removing it from the provisional sum and recomputing `provisional_contract_value`. Rejecting moves the order to the terminal `REJECTED` state, again removing it from the provisional sum and recomputing `provisional_contract_value`. Approving moves the order to the terminal `APPROVED` state. A `REVISION_REQUESTED` order can be resubmitted, which returns it to `SUBMITTED`, updates its `delta_amount` and `delta_sqft` from the new request, and re-stamps `submitted_by_user_id` with the resubmitting officer's `X-User-ID` for another review round. Each of these transitions increments the change order's `version`, and the start-review, request-revision, reject, and approve transitions also increment the project's `version`.

Approval is the most heavily guarded transition. Beyond requiring the order to be `UNDER_REVIEW`, it requires the project to be in `APPROVED`, `SCHEDULED`, or `ON_HOLD`; it requires the `expected_project_version` OCC match of §2.7; and it enforces segregation of duties — the approving `FinanceOfficer`'s `X-User-ID` must not equal the `released_by_user_id` of any draw that has been released on this project. A segregation breach is rejected with `ERR_SEGREGATION_VIOLATION` (HTTP 403). On approval the order's `delta_amount` enters the committed sum, so the project recomputes both `committed_contract_value` and `provisional_contract_value`, and the order's `delta_sqft` is applied to the project's effective scope total used by later estimates and draw caps. Both the order's and the project's `version` increment.

### 3.11. Draws and the Waterfall Cap

A `FinanceOfficer` requests a **Draw** against a project, declaring a `draw_type` of `DEPOSIT`, `PROGRESS`, or `FINAL` and an `amount` in dollars that must be strictly greater than zero. A requested draw starts in `REQUESTED` with `released_by_user_id` null and increments the project's `version`. A draw may be voided from `REQUESTED`, moving it to the terminal `VOIDED` state and incrementing its `version`.

Releasing a draw — moving it from `REQUESTED` to `RELEASED` — is the system's most constrained financial act, and several guards apply in addition to the draw being `REQUESTED`. The request carries the `expected_project_version` OCC token of §2.7, and the project must be in `APPROVED`, `SCHEDULED`, `POURED`, or `CURING`. Segregation of duties applies in the mirror direction of change-order approval: the releasing `FinanceOfficer`'s `X-User-ID` must not equal the `submitted_by_user_id` of any `APPROVED` change order on the project, and a breach yields `ERR_SEGREGATION_VIOLATION` (HTTP 403).

The release must respect a **waterfall cap** on cumulative draws. The cap depends on the draw type. For a `FINAL` draw the cap is the project's full `committed_contract_value`, letting the final draw reach 100 percent of committed contract value. For a `DEPOSIT` or `PROGRESS` draw the cap is the `committed_contract_value` multiplied by 0.90 — that is, committed value less a ten-percent retainage — rounded to two decimal places. The release is allowed only when the project's `total_drawn_amount` plus this draw's `amount` is at most the applicable cap; if it would exceed the cap, the release is refused with `ERR_DRAW_EXCEEDS_CONTRACT` (HTTP 409).

Sequencing is also enforced. At most one `DEPOSIT` draw may ever be released on a project, so a second `DEPOSIT` release is refused. A `FINAL` draw may be released only when the project is in `CURING` and every other non-`VOIDED` draw on the project has already been `RELEASED`. A violation of either sequencing rule yields `ERR_DRAW_SEQUENCE_INVALID` (HTTP 409). When all guards pass, the draw moves to `RELEASED`, its `released_by_user_id` is set to the acting officer's `X-User-ID`, the project's `total_drawn_amount` is recomputed as the sum of `amount` over all `RELEASED` draws, and both the draw's and the project's `version` increment.

### 3.12. Warranties and Defect Claims

A `ProjectManager` issues a **Warranty** on an approved-or-later project, supplying a `term_months` term that must be at least 1. A new warranty starts in `ACTIVE` with a `defect_claims_count` of 0 and increments the project's `version`.

An `Inspector` files defect claims against a warranty, but only on a project that has reached `COMPLETED`; a claim filed against a project that is not `COMPLETED` is refused with `ERR_PRECONDITION_NOT_MET`. Each claim may carry an optional `defect_note`. The first claim moves the warranty from `ACTIVE` to `CLAIM_OPEN`; subsequent claims on an already-open warranty are a self-loop that keeps it `CLAIM_OPEN`. Either way, the warranty's `defect_claims_count` increments by 1, the project's `warranty_risk_score` is recomputed to reflect the added defect contribution, and both the warranty's and the project's `version` increment. Resolving an open claim returns the warranty from `CLAIM_OPEN` to `ACTIVE` and increments its `version`; the `defect_claims_count` is *not* decremented on resolution, because claims are historical and accumulate permanently. Finally, a `ProjectManager` may void a warranty from either `ACTIVE` or `CLAIM_OPEN`, moving it to the terminal `VOID` state and incrementing its `version`.

## 4. Endpoint Definitions

Operations that create a new resource return HTTP 201. Operations that modify an existing resource — including all state transitions and the administrative clock-set — return HTTP 200. Read operations return HTTP 200. The table below lists every endpoint; request bodies, response shapes, and side effects are described in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/projects` | Create a project in DRAFT | Estimator |
| GET | `/projects/{id}` | Fetch a project (recomputes derived fields) | Estimator, ProjectManager, FinanceOfficer, Inspector |
| GET | `/projects` | List projects (optional status filter) | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/projects/{id}/estimates` | Create an estimate; DRAFT to ESTIMATING | Estimator |
| GET | `/projects/{id}/estimates` | List a project's estimates | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/projects/{id}/approve-estimate` | Approve a DRAFT estimate; ESTIMATING to APPROVED | ProjectManager |
| POST | `/projects/{id}/reject` | Reject the project; ESTIMATING to REJECTED | ProjectManager |
| POST | `/projects/{id}/schedule` | Schedule the project; APPROVED to SCHEDULED | ProjectManager |
| POST | `/projects/{id}/begin-cure` | Begin cure; POURED to CURING | ProjectManager |
| POST | `/projects/{id}/complete` | Complete the project; CURING to COMPLETED | ProjectManager |
| POST | `/projects/{id}/hold` | Place project ON_HOLD | ProjectManager |
| POST | `/projects/{id}/resume` | Resume from hold | ProjectManager |
| POST | `/projects/{id}/segments` | Add a flatwork segment to a DRAFT project | Estimator |
| GET | `/projects/{id}/segments` | List a project's flatwork segments | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/projects/{id}/permits` | Apply for a permit | ProjectManager |
| GET | `/projects/{id}/permits` | List a project's permits | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/permits/{id}/issue` | Issue a permit; APPLIED to ISSUED | Inspector |
| POST | `/permits/{id}/close` | Close a permit; ISSUED to CLOSED | Inspector |
| POST | `/permits/{id}/revoke` | Revoke a permit; may force project ON_HOLD | Inspector |
| POST | `/projects/{id}/material-orders` | Place a material order | ProjectManager |
| GET | `/projects/{id}/material-orders` | List a project's material orders | Estimator, ProjectManager, FinanceOfficer, Inspector |
| GET | `/material-orders/{id}` | Fetch a material order | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/material-orders/{id}/start-pour` | Start the pour; ORDERED to POURING (weather gate) | ProjectManager |
| POST | `/material-orders/{id}/complete-pour` | Complete the pour; POURING to POURED | ProjectManager |
| POST | `/material-orders/{id}/cancel` | Cancel a material order; ORDERED to CANCELLED | ProjectManager |
| POST | `/material-orders/{id}/weather-readings` | Append a weather reading | ProjectManager, Inspector |
| GET | `/material-orders/{id}/weather-readings` | List weather readings | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/crews` | Create a crew | ProjectManager |
| GET | `/crews/{id}` | Fetch a crew | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/equipment` | Create an equipment asset | ProjectManager |
| GET | `/equipment/{id}` | Fetch an equipment asset | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/projects/{id}/crew-assignments` | Book crew and optional equipment for a window | ProjectManager |
| GET | `/projects/{id}/crew-assignments` | List a project's crew assignments | Estimator, ProjectManager, FinanceOfficer, Inspector |
| GET | `/crew-assignments` | List crew assignments filtered by crew or equipment | Estimator, ProjectManager, FinanceOfficer, Inspector |
| GET | `/crew-assignments/{id}` | Fetch a single crew assignment | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/crew-assignments/{id}/release` | Release a crew assignment; BOOKED to RELEASED | ProjectManager |
| POST | `/projects/{id}/change-orders` | Submit a change order | FinanceOfficer |
| GET | `/projects/{id}/change-orders` | List a project's change orders | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/change-orders/{id}/start-review` | Begin review; SUBMITTED to UNDER_REVIEW | FinanceOfficer |
| POST | `/change-orders/{id}/request-revision` | Request revision; UNDER_REVIEW to REVISION_REQUESTED | FinanceOfficer |
| POST | `/change-orders/{id}/resubmit` | Resubmit after revision; REVISION_REQUESTED to SUBMITTED | FinanceOfficer |
| POST | `/change-orders/{id}/approve` | Approve; UNDER_REVIEW to APPROVED | FinanceOfficer |
| POST | `/change-orders/{id}/reject` | Reject; UNDER_REVIEW to REJECTED | FinanceOfficer |
| POST | `/projects/{id}/draws` | Request a draw | FinanceOfficer |
| GET | `/projects/{id}/draws` | List a project's draws | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/draws/{id}/release` | Release a draw; REQUESTED to RELEASED | FinanceOfficer |
| POST | `/draws/{id}/void` | Void a draw; REQUESTED to VOIDED | FinanceOfficer |
| POST | `/projects/{id}/warranties` | Issue a warranty | ProjectManager |
| GET | `/projects/{id}/warranties` | List a project's warranties | Estimator, ProjectManager, FinanceOfficer, Inspector |
| POST | `/warranties/{id}/claims` | File a defect claim; ACTIVE to CLAIM_OPEN or self-loop | Inspector |
| POST | `/warranties/{id}/resolve-claim` | Resolve an open claim; CLAIM_OPEN to ACTIVE | Inspector |
| POST | `/warranties/{id}/void` | Void a warranty; ACTIVE or CLAIM_OPEN to VOID | ProjectManager |
| POST | `/_clock/set_current_utc` | Set the server's logical current-UTC clock | ProjectManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRECONDITION_NOT_MET` | 409 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_WEATHER_OUT_OF_RANGE` | 409 |
| `ERR_CURE_WINDOW_NOT_ELAPSED` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_EQUIPMENT_DOUBLE_BOOKED` | 409 |
| `ERR_SEGREGATION_VIOLATION` | 403 |
| `ERR_DRAW_EXCEEDS_CONTRACT` | 409 |
| `ERR_DRAW_SEQUENCE_INVALID` | 409 |
