# Snow & Ice Operations API — Product Requirements Document

## 1. Introduction

When a winter storm bears down on a municipality, its public-works dispatch center must orchestrate a small army of plows and spreaders across a prioritized street network, keep salt and brine flowing without running a yard dry, and account for every overtime hour and every ton of material once the roads are clear. This document specifies the backend API for a municipal Snow & Ice Operations platform that ties those concerns together: it tracks the fleet and roster, declares and drives storm events, plans route assignments and field callouts, records GPS/AVL positions and material applications, fields citizen complaints about missed streets, and produces cost-per-event reporting that reconciles what was planned against what was actually spent.

The platform serves four distinct operational constituencies whose responsibilities do not overlap. A yard manager stocks depots and registers the vehicle fleet and operator roster. A dispatch supervisor runs the storm from declaration through billing close-out, planning who plows what and when. Field operators drive the trucks, ping their positions, and log the salt and brine they lay down. Citizen-services staff intake and work the public's complaints. The system must hold two invariants sacred throughout: material is conserved (every ton debited from a yard is either consumed or credited back on a void), and labor is conserved (every accrued straight-time and overtime hour can be reversed cleanly if a completed callout is later cancelled). Because storms are replanned in real time and multiple supervisors may touch the same event, the platform relies on optimistic concurrency and deterministic cascades so that no two writers silently clobber each other's work.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is absent, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If both headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `DispatchSupervisor`, `Operator`, `YardManager`, and `CitizenServices`. Their responsibilities are non-overlapping. A `DispatchSupervisor` orchestrates storms — declaring, activating, closing, and finalizing them — and owns route planning, callout issuance, application voids, cost-report generation, and the logical clock. A `YardManager` owns the fleet and roster: registering depots with their opening inventory, vehicles, and operators. An `Operator` is a field driver who records material applications and AVL pings on assignments they personally hold and completes their own callouts. `CitizenServices` owns the entire complaint lifecycle. Every role may call any read (GET) endpoint.

Three of the four roles carry an opaque identity. When `X-User-Role` is `DispatchSupervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`. The same is true when `X-User-Role` is `YardManager` and when `X-User-Role` is `CitizenServices` — in both cases `X-User-ID` is opaque and is not matched against stored records.

The `Operator` role is different: it is entity-backed. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` record. Ownership checks on any resource that references an operator compare that resource's operator foreign key to `X-User-ID`. Concretely, when an operator records a material application or an AVL ping against an assignment, the acting `X-User-ID` must equal that assignment's `operator_id`; when an operator completes a callout, the acting `X-User-ID` must equal that callout's `operator_id`. If an entity-backed operator acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must be at least 0. List results are ordered by ascending server creation sequence (insertion order) — that is, oldest records first; this insertion-order sort is authoritative and is not re-derived from the `created_at` value, so records that share a `created_at` (common while the logical clock is static) retain insertion order and setting the clock backward never reshuffles records already created. Each list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, disregarding pagination), and `has_more` (true when records remain beyond the current page) inside the `meta` object. Beyond pagination, list endpoints accept optional exact-match filter query parameters, and any query parameter not recognized by an endpoint is ignored: `/vehicles` filters by `home_depot_id` and `status`; `/assignments` by `route_id`, `vehicle_id`, `operator_id`, and `status`; `/material-applications` by `depot_id`, `route_assignment_id`, and `status`; `/callouts` by `operator_id` and `status`; `/complaints` by `route_id`, `storm_event_id`, and `status`; a storm's nested assignment list and callout list each by `status`; an assignment's application list by `status`; and a storm's cost-report list by `variant`.

### 2.4. Resource Identity, Versioning, and the Common Property Set

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Every resource also carries a `created_at` timestamp. Most resources additionally carry an `updated_at` timestamp and an integer `version` that starts at 1 on creation and increments by 1 on every mutation of that resource. The `created_at` and `updated_at` values are ISO 8601 UTC timestamps with three fractional digits.

One entity is an exception. A cost report is an immutable computed snapshot: once generated it is never mutated. A cost report therefore carries only `id` and `created_at` — it has no `updated_at` field and no `version` field. Every other entity (depot, vehicle, operator, route, storm event, route assignment, material application, callout, and complaint) carries the full common set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. The Logical Clock

The server keeps a logical clock that supplies every server-stamped timestamp and drives all window arithmetic. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it the clock returns exactly this default — it never falls back to the host wall clock. An admin-only test-driving capability advances the clock to a supplied instant, provided as `to_iso8601`. All server-stamped fields — a storm's `closed_at`, an application's `applied_at`, an assignment's `last_ping_at`, a complaint's `reported_at`, a cost report's `generated_at`, and every `created_at`/`updated_at` — are read from this logical clock.

### 2.6. Optimistic Concurrency on Storm Replanning

Route-assignment creation is guarded by optimistic concurrency control keyed on the owning storm event. A request to create an assignment under a storm must carry `expected_storm_event_version`, and this field is mandatory on that request. Its value must equal the target storm event's current `version`. If another writer has advanced the storm's `version` since the client last read it — for instance, by creating an assignment that bumped the storm and possibly superseded the route's prior plan — the create is rejected with `ERR_STALE_STORM_VERSION` (HTTP 412). This prevents a client working from a stale view of the storm from overwriting a newer plan it never observed. No other endpoint accepts or requires a version field.

### 2.7. Cascading State Propagation

Two operations in this system fan out three entities deep, and the propagation must land atomically within the triggering request. Closing a storm is the root of one depth-3 chain (storm → assignments → vehicles); cancelling an assignment is the root of the other (assignment → applications → depot). In both cases, the secondary and tertiary effects are not optional side-work — they are part of the operation's contract, and the sections below spell out each hop. Whenever a mutation changes a resource, that resource's `updated_at` is refreshed and, for entities that carry one, its `version` is incremented.

### 2.8. Material Conservation and Inventory

Each depot anchors a material-conservation invariant. At creation the depot's opening `salt_tons_on_hand` and `brine_gallons_on_hand` are snapshotted into `initial_salt_tons` and `initial_brine_gallons`, which never change thereafter. Recording a salt application debits `salt_tons_on_hand`; recording a brine application debits `brine_gallons_on_hand`. Voiding an application credits the same amount back to the same depot. Neither inventory figure may go negative — both `salt_tons_on_hand` and `brine_gallons_on_hand` are constrained to be at least 0 — and an application that would draw more than the depot holds is refused before any debit occurs. Salt tonnage figures (both inventory and applied amounts) support up to four decimal places.

### 2.9. Monetary and Labor Precision

All money in this system is expressed in integer cents; an operator's `hourly_rate_cents` is a straight-time wage in integer cents per hour and must be greater than 0. Wherever a monetary or recommendation figure requires rounding, the system rounds half up. The material-recommendation figure is rounded to two decimal places. Pay is computed to a final integer-cents value using round-half-up. Material-cost lines in a cost report are each rounded half up to integer cents before being summed. Operators additionally maintain a labor-hours ledger — `regular_hours_accrued` and `overtime_hours_accrued`, both initialized to 0 — which is credited when a callout completes and reversed if a completed callout is later cancelled, so that the accrued totals always reflect only the operator's currently-live completed work.

### 2.10. Validation Ordering and Nested Path Resolution

When several conditions could reject a request, they are evaluated in a fixed order so that failures surface deterministically. Authentication (presence of both headers) is checked first, yielding `ERR_UNAUTHENTICATED`. Authorization (the role may perform the operation) is checked next, yielding `ERR_UNAUTHORIZED`. Existence is checked third: every path id and every body foreign key — storm, route, vehicle, operator, depot, assignment, callout, and application references — is resolved left-to-right along the URL hierarchy, and the first that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). Fourth, the request body is checked for well-formedness — required fields present, enum values within their declared sets, and numbers within their stated constraints — yielding `ERR_INVALID_REQUEST` (HTTP 400) for a malformed body, or `ERR_INVALID_ENUM` (HTTP 422) specifically when an enum field carries a value outside its declared set. Fifth, entity-backed resource ownership is enforced, yielding `ERR_NOT_RESOURCE_OWNER`. Sixth, the target must be in the state the requested transition requires, yielding the state error described with each workflow below. The remaining domain checks — vehicle safety, operator on-call status, vehicle double-booking, window validity, the optimistic-concurrency version match, and depot material sufficiency — follow, each described in its workflow section. (For assignment creation specifically, the route-already-active guard yielding `ERR_ROUTE_ALREADY_ACTIVE` is evaluated within the state step, alongside the storm-status guard and ahead of these domain checks.)

## 3. Business Logic & Workflows

### 3.1. Standing Up the Yard, Fleet, Roster, and Street Network

Before a storm can be run, a `YardManager` establishes the physical resources. A depot is registered with a human `name` and its opening inventory — `salt_tons_on_hand` and `brine_gallons_on_hand` — at which point the system snapshots those opening balances into `initial_salt_tons` and `initial_brine_gallons` as the permanent conservation anchor. Vehicles are registered against a home depot: a vehicle create supplies `home_depot_id`, a `unit_number` fleet label, and a `vehicle_type`, and may optionally supply an initial `status`. The `vehicle_type` is one of `PLOW` (blade only), `SPREADER` (hopper only), or `COMBO` (both). From that type the system computes `has_spreader`, which is true exactly when the `vehicle_type` is `SPREADER` or `COMBO`; a vehicle needs a spreader to service a salting or brining run. A vehicle's `status` is one of `AVAILABLE` (idle), `ASSIGNED` (reserved to an in-progress run), or `OUT_OF_SERVICE` (in maintenance), and it defaults to `AVAILABLE` when not supplied at creation.

An operator is registered with a `full_name`, a roster `badge_number`, a commercial license `cdl_class` (one of `A`, `B`, or `C`), and an `hourly_rate_cents` straight-time wage. Their `regular_hours_accrued` and `overtime_hours_accrued` ledgers both begin at 0. A route is created by a `DispatchSupervisor` with a `name`, a priority `tier`, its `lane_miles`, and an operational `zone` label. The `tier` is either `ARTERIAL` — a primary corridor plowed and salted first — or `RESIDENTIAL`, a lower-priority street group; the tier both sets service priority and later scales the material recommendation. Lane-miles must be greater than 0, since they drive material-requirement math.

### 3.2. Declaring and Running a Storm Event

A `DispatchSupervisor` declares a storm event with a `name`, a `severity`, and a forecast window given by `forecast_start_at` and `forecast_end_at`. The `severity` is one of `LIGHT`, `MODERATE`, `SEVERE`, or `EMERGENCY`; the lighter two drive standard overtime terms while the heavier two drive storm-mode overtime and a cost premium, as detailed later. A storm carries two independent status axes. The operational axis, `operational_status`, begins at `PLANNED` and moves `PLANNED → ACTIVE` on activation and `ACTIVE → CLOSED` on close. The billing axis, `billing_status`, begins at `OPEN` and moves `OPEN → FINALIZED` on billing finalization. These axes are independent except for one guard described below.

Activation requires the storm to currently be in `PLANNED`; it sets `operational_status` to `ACTIVE` and bumps the storm's `version`. Only an `ACTIVE` storm admits the starting of assignments and (as a practical matter) the working of new field labor. Attempting to activate or close a storm whose `operational_status` is already `CLOSED` is rejected with `ERR_STORM_ALREADY_CLOSED`. Attempting to activate a storm that is already `ACTIVE` (and thus not `PLANNED` and not `CLOSED`) is rejected with `ERR_INVALID_STATE` (HTTP 409).

Closing a storm requires it to currently be `ACTIVE`. On close, `operational_status` is set to `CLOSED`, `closed_at` is stamped from the logical clock, and the storm's `version` is incremented. Closing is also the root of a three-hop cascade over that storm's assignments. In the first hop, every route assignment of this storm that is currently `IN_PROGRESS` transitions to `COMPLETED`, and every route assignment that is currently `PLANNED` transitions to `CANCELLED`. In the further hops, each assignment that reaches `COMPLETED` this way releases its vehicle back to `AVAILABLE` — the same vehicle release that a direct completion produces. A storm that is not in `ACTIVE` cannot be closed, surfacing the state error for that transition.

Finalizing billing moves `billing_status` from `OPEN` to `FINALIZED` and increments the storm's `version`. It carries the single cross-axis guard: the storm's `operational_status` must already be `CLOSED`. If billing finalization is attempted while the storm is not closed, it is rejected with `ERR_STORM_NOT_CLOSED`; if attempted while `billing_status` is not `OPEN`, it is rejected with `ERR_BILLING_NOT_OPEN`. The operational `CLOSED` state and the billing `FINALIZED` state are each terminal on their respective axis.

### 3.3. Issuing Field Callouts and Protecting Operator Rest

To put a driver in the field, a `DispatchSupervisor` issues a callout under a storm, supplying the target `operator_id` and the scheduled shift window `window_start_at` and `window_end_at`. A callout is created in `ISSUED` status. Two temporal guards protect the create. First, the window must be well-formed: `window_end_at` must be strictly later than `window_start_at`, or the create is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Second, a rest buffer of eight hours separates an operator's shifts. No other callout for the same operator that is in `ISSUED` or `COMPLETED` status may fall within eight hours of this window; concretely, this window's `window_start_at` must be at least eight hours after the other callout's `window_end_at`, or the other callout's `window_start_at` must be at least eight hours after this window's `window_end_at`. If neither holds, the create is rejected with `ERR_OPERATOR_REST_VIOLATION`.

A callout's `hours_worked` is null-equivalent (0) while the callout is `ISSUED` and is supplied only at completion; likewise, until completion runs, `pay_mode` is null and `regular_hours`, `overtime_hours`, and `pay_cents` are each 0. Completing a callout is the operator's own action, so the acting `X-User-ID` must match the callout's `operator_id`, and the callout must currently be `ISSUED` or the completion is rejected with `ERR_CALLOUT_NOT_ISSUED`. Cancellation of a callout is a supervisor action available from either `ISSUED` or `COMPLETED`. Cancelling an already-`CANCELLED` callout is rejected with `ERR_CALLOUT_NOT_CANCELLABLE`. The compensating behavior of cancelling a completed callout is described in the pay section below; `COMPLETED` and `CANCELLED` are the terminal callout states.

### 3.4. Planning Route Assignments

Assigning work is where the storm's plan takes shape, and it is the most heavily guarded write in the system. A `DispatchSupervisor` creates an assignment under a storm, naming the `route_id` to service, the `vehicle_id` to use, the `operator_id` to drive, an `assignment_type`, the occupation window `window_start_at` and `window_end_at`, a `planned_material_tons` figure (which must be at least 0) that will feed the estimate cost variant, and the mandatory `expected_storm_event_version`. The `assignment_type` is either `PRETREAT` (an anti-icing brine run before onset) or `PLOWING` (salting and plowing during the storm). A new assignment is created in `PLANNED` status.

Several checks gate the create, and they express distinct failures. The owning storm's `operational_status` must be either `PLANNED` or `ACTIVE`; if it is `CLOSED` the create is rejected with `ERR_STORM_ALREADY_CLOSED`. The chosen vehicle must not be `OUT_OF_SERVICE`, or the create is rejected with `ERR_VEHICLE_OUT_OF_SERVICE` (HTTP 422); and when the `assignment_type` is `PLOWING`, the vehicle's `has_spreader` must be true, or the create is rejected with `ERR_VEHICLE_MISSING_SPREADER` (HTTP 422). The named operator must already hold a callout for this storm in either `ISSUED` or `COMPLETED` status, or the create is rejected with `ERR_OPERATOR_NOT_ON_CALL`. The vehicle must not be double-booked: no other assignment for the same vehicle in `PLANNED` or `IN_PROGRESS` status may have a half-open occupation window `[window_start_at, window_end_at)` that overlaps this one — abutting windows where one ends exactly as the other starts are allowed — otherwise the create is rejected with `ERR_VEHICLE_DOUBLE_BOOKED`. The window itself must be well-formed, with `window_end_at` strictly after `window_start_at`, or `ERR_INVALID_WINDOW` results. And `expected_storm_event_version` must match the storm's current `version`, or the create is rejected with `ERR_STALE_STORM_VERSION` as described in the concurrency principle.

Assignment creation is also a replan mechanism. When the create succeeds, any existing assignment for the very same storm-and-route pairing that is currently in `PLANNED` status is superseded — it transitions `PLANNED → SUPERSEDED` — so that the newest plan for a street wins. The successful create also increments the storm's `version`. If, however, an existing assignment for that storm-and-route pairing is `IN_PROGRESS` rather than merely `PLANNED`, the route is already being actively serviced and the create is rejected with `ERR_ROUTE_ALREADY_ACTIVE` rather than superseding live work.

### 3.5. Driving, Tracking, and Cancelling Assignments

Once planned, an assignment is started by a `DispatchSupervisor`, which advances it `PLANNED → IN_PROGRESS` and reserves the truck by setting the vehicle's `status` to `ASSIGNED`. Starting requires three things: the assignment must currently be `PLANNED` (otherwise `ERR_ASSIGNMENT_NOT_PLANNED`), the owning storm must currently be `ACTIVE` (otherwise `ERR_STORM_NOT_ACTIVE`), and the vehicle must currently be `AVAILABLE` (otherwise `ERR_INVALID_STATE`, HTTP 409). Direct completion advances the assignment `IN_PROGRESS → COMPLETED` and releases the vehicle back to `AVAILABLE`; completion requires the assignment to be `IN_PROGRESS`, and this same vehicle release also occurs when a completion is produced by the storm-close cascade rather than by a direct call.

Field position is reported through AVL pings, which only the assignment's own operator may send: the acting `X-User-ID` must equal the assignment's `operator_id`. A ping supplies a `lat` and a `lon`, and may optionally supply `plow_down`. Recording a ping updates the assignment's `last_lat` and `last_lon`, sets `plow_down` (which defaults to false and reflects whether the blade was down on the latest ping), and stamps `last_ping_at` from the logical clock. An assignment must be `IN_PROGRESS` to accept a ping; otherwise the request is rejected with `ERR_ASSIGNMENT_NOT_IN_PROGRESS`.

Cancellation is the root of the second depth-3 cascade. A `DispatchSupervisor` may cancel an assignment from either `PLANNED` or `IN_PROGRESS`; attempting to cancel an assignment already in a terminal state (`COMPLETED`, `SUPERSEDED`, or `CANCELLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409). Cancelling a `PLANNED` assignment simply sets its `status` to `CANCELLED`. Cancelling an `IN_PROGRESS` assignment sets its `status` to `CANCELLED`, releases the reserved vehicle back to `AVAILABLE`, and in the first cascade hop transitions every material application of this assignment that is currently `RECORDED` to `VOIDED`; each such void, in the further hops, credits the voided material back to the depot it was drawn from, restoring the conservation invariant. An assignment reaches `COMPLETED`, `SUPERSEDED`, or `CANCELLED` as its terminal states.

### 3.6. Recording Material and Computing the Recommendation

A material application is the field record of salt or brine laid on a route, and only the assignment's own operator may record one — the acting `X-User-ID` must equal the assignment's `operator_id`, or the request is refused for lack of ownership. The assignment must be `IN_PROGRESS`, or the request is rejected with `ERR_ASSIGNMENT_NOT_IN_PROGRESS`. The application supplies the `depot_id` the material is drawn from, a `material_type` of `SALT` or `BRINE`, the `lane_miles_treated` (which must be greater than 0), and the measured `pavement_temp_f`. When `material_type` is `SALT`, the `salt_tons` figure is required and `brine_gallons` must be 0; when `material_type` is `BRINE`, `brine_gallons` is required and `salt_tons` must be 0. Both amounts default to 0 and must be at least 0. A new application is created in `RECORDED` status, its `route_assignment_id` bound to the assignment it was recorded under, and `applied_at` is stamped from the logical clock.

The application debits inventory at the named depot: a salt application decrements that depot's `salt_tons_on_hand` by `salt_tons`, and a brine application decrements `brine_gallons_on_hand` by `brine_gallons`. The depot must hold enough first — `salt_tons_on_hand` at least `salt_tons` for salt, or `brine_gallons_on_hand` at least `brine_gallons` for brine — or the request is rejected with `ERR_INSUFFICIENT_MATERIAL` and no debit occurs.

Each application also computes a `recommended_salt_tons` advisory figure by reading the owning route's tier. The recommendation is the product of four factors: the `lane_miles_treated`, a base spread rate of 0.15 tons per lane-mile, a temperature factor selected from the measured `pavement_temp_f`, and a tier multiplier selected from the route's `tier`. The temperature factor is 0.8 when the pavement temperature is at least 30 degrees Fahrenheit; 1.0 when it is at least 20 but below 30; 1.3 when it is at least 10 but below 20; and 1.6 when it is below 10. The tier multiplier is 1.0 for an `ARTERIAL` route and 0.6 for a `RESIDENTIAL` route. The four factors are multiplied together and the result is rounded half up to two decimal places to yield `recommended_salt_tons`.

A recorded application may be voided by a `DispatchSupervisor`. Voiding sets the application's `status` to `VOIDED` and credits the material back to the depot — salt applications add `salt_tons` back to `salt_tons_on_hand`, brine applications add `brine_gallons` back to `brine_gallons_on_hand`. An application must be `RECORDED` to be voided; voiding one already `VOIDED` is rejected with `ERR_APPLICATION_ALREADY_VOIDED`. The same void behavior is what the assignment-cancel cascade triggers on each recorded application. `VOIDED` is the terminal application state.

### 3.7. Completing Callouts and Computing Overtime Pay

When an operator completes their callout, they supply the actual `hours_worked` (which must be at least 0), and the system computes the pay in a single deterministic pass, writing `pay_mode`, `regular_hours`, `overtime_hours`, and `pay_cents`, then setting the callout to `COMPLETED`. The pay terms are selected from the owning storm's `severity`. A `LIGHT` or `MODERATE` storm uses the standard variant, recorded as `pay_mode` `STANDARD`; a `SEVERE` or `EMERGENCY` storm uses the storm variant, recorded as `pay_mode` `STORM_MODE`.

The chosen variant fixes three parameters. Under `STANDARD`, the overtime threshold is 8 hours, the overtime multiplier is 1.5, and the guaranteed callout minimum is 2 hours. Under `STORM_MODE`, the overtime threshold is 6 hours, the overtime multiplier is 2.0, and the guaranteed callout minimum is 3 hours — so for identical `hours_worked` a storm-mode completion always yields strictly higher pay. Computation proceeds in steps. First, the paid hours are the greater of the reported `hours_worked` and the variant's callout minimum. The `regular_hours` credited are the lesser of those paid hours and the threshold. The `overtime_hours` are the paid hours in excess of the threshold, and zero when the paid hours do not exceed it — overtime accrues strictly above the threshold, not at it. Finally, `pay_cents` is the regular hours times the operator's `hourly_rate_cents`, plus the overtime hours times the operator's `hourly_rate_cents` times the variant's multiplier, with the final cents value rounded half up.

Completion then credits the operator's ledger: `regular_hours_accrued` is increased by this callout's `regular_hours` and `overtime_hours_accrued` by its `overtime_hours`. This credit is exactly reversible. If a `COMPLETED` callout is later cancelled, the operator's `regular_hours_accrued` is decreased by that callout's `regular_hours` and `overtime_hours_accrued` by its `overtime_hours`, returning the accrued totals to their pre-completion values.

### 3.8. Working Citizen Complaints

`CitizenServices` owns a cyclic complaint workflow. A complaint is filed against a specific street and storm, supplying the `route_id`, the `storm_event_id`, the reported `address`, and a `complaint_type` of `MISSED_STREET`, `ICY_CONDITIONS`, or `PROPERTY_DAMAGE`. A new complaint opens in `OPEN` status with `reported_at` stamped from the logical clock and `missed_street_confirmed` defaulting to false. Investigation moves a complaint into `INVESTIGATING` — permitted from either `OPEN` or `REOPENED` — and while doing so sets `missed_street_confirmed` from the request's `confirm_missed` flag (which defaults to false when omitted), recording whether the street was in fact never serviced. Resolution moves an `INVESTIGATING` complaint to `RESOLVED`. A `RESOLVED` complaint may be reopened to `REOPENED`, from which it can be investigated again, and so on indefinitely — complaints have no terminal state. Any complaint transition attempted from a state that does not permit it is rejected with `ERR_COMPLAINT_INVALID_STATE`.

### 3.9. Costing Out the Event

At any point a `DispatchSupervisor` generates a cost-per-event snapshot for a storm, choosing a `variant` of either `ESTIMATE` or `ACTUAL`. The snapshot is immutable once produced: it records `total_material_cost_cents`, `total_labor_cost_cents`, and `total_cost_cents` (which is simply the material total plus the labor total), and stamps `generated_at` from the logical clock. Two fixed unit costs apply throughout: salt costs 8,500 cents per ton and brine costs 25 cents per gallon. In every material total, each contributing line is rounded half up to integer cents on its own before the lines are summed — the per-line rounding happens first, and summing already-rounded lines is required.

The `ESTIMATE` variant costs the plan. Its material lines are this storm's route assignments whose `status` is `PLANNED`, `IN_PROGRESS`, or `COMPLETED`; each contributes its `planned_material_tons` times 8,500 cents, rounded half up, and these are summed into `total_material_cost_cents`. Its labor lines are this storm's callouts whose `status` is `ISSUED` or `COMPLETED`; each contributes a straight-time projection equal to the number of hours between its `window_start_at` and `window_end_at` times the operator's `hourly_rate_cents`, rounded half up, with no overtime multiplier applied, and these are summed into `total_labor_cost_cents`.

The `ACTUAL` variant costs what really happened, and for identical storm data it diverges from the estimate. Its material lines are this storm's material applications whose `status` is `RECORDED` (voided applications are excluded); each salt line contributes its `salt_tons` times 8,500 cents and each brine line its `brine_gallons` times 25 cents, each rounded half up, then summed into `total_material_cost_cents`. Its labor lines are this storm's callouts whose `status` is `COMPLETED`; their already-integer `pay_cents` values — which include any overtime — are summed directly into `total_labor_cost_cents`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that modify or transition an existing resource, and all reads, respond with HTTP 200. Request and response bodies are governed by the workflows in §3; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/depots` | Register a depot with opening salt/brine inventory. | YardManager |
| GET | `/depots/{id}` | Read a depot including current inventory. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/vehicles` | Register a plow/spreader unit at a depot. | YardManager |
| GET | `/vehicles/{id}` | Read a vehicle. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/vehicles` | List/filter vehicles. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/operators` | Register an operator (driver). | YardManager |
| GET | `/operators/{id}` | Read an operator including accrued hours. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/routes` | Create a route with priority tier and lane-miles. | DispatchSupervisor |
| GET | `/routes/{id}` | Read a route. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/storm-events` | Declare a storm event. | DispatchSupervisor |
| GET | `/storm-events/{id}` | Read a storm event including both status axes and version. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/storm-events/{id}/activate` | Activate a planned storm. | DispatchSupervisor |
| POST | `/storm-events/{id}/close` | Close an active storm; runs the close cascade. | DispatchSupervisor |
| POST | `/storm-events/{id}/finalize-billing` | Finalize billing on a closed storm. | DispatchSupervisor |
| POST | `/storm-events/{id}/assignments` | Create a route assignment (OCC on the storm; may supersede a prior plan). | DispatchSupervisor |
| GET | `/storm-events/{id}/assignments` | List assignments of a storm. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/assignments/{id}` | Read an assignment including AVL position and status. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/assignments` | List/filter assignments. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/assignments/{id}/start` | Start an assignment; reserve the vehicle. | DispatchSupervisor |
| POST | `/assignments/{id}/complete` | Complete an assignment; release the vehicle. | DispatchSupervisor |
| POST | `/assignments/{id}/cancel` | Cancel an assignment; runs the cancel cascade. | DispatchSupervisor |
| POST | `/assignments/{id}/avl-ping` | Record a GPS/AVL ping from the field. | Operator |
| POST | `/assignments/{id}/applications` | Record a salt/brine spread event; debit depot inventory. | Operator |
| GET | `/assignments/{id}/applications` | List applications of an assignment. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/material-applications/{id}` | Read a single application. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/material-applications` | List/filter applications. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/material-applications/{id}/void` | Void a recorded application; credit the depot. | DispatchSupervisor |
| POST | `/storm-events/{id}/callouts` | Issue an overtime callout for a shift window. | DispatchSupervisor |
| GET | `/storm-events/{id}/callouts` | List callouts of a storm. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/callouts/{id}` | Read a callout including computed pay fields. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/callouts` | List/filter callouts. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/callouts/{id}/complete` | Complete a callout; compute pay and credit the ledger. | Operator |
| POST | `/callouts/{id}/cancel` | Cancel a callout; reverse accrued hours if it was completed. | DispatchSupervisor |
| POST | `/complaints` | File a citizen complaint. | CitizenServices |
| GET | `/complaints/{id}` | Read a complaint. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| GET | `/complaints` | List/filter complaints. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/complaints/{id}/investigate` | Move a complaint into investigation; optionally confirm a missed street. | CitizenServices |
| POST | `/complaints/{id}/resolve` | Resolve a complaint under investigation. | CitizenServices |
| POST | `/complaints/{id}/reopen` | Reopen a resolved complaint. | CitizenServices |
| POST | `/storm-events/{id}/cost-reports` | Generate an immutable cost-per-event snapshot. | DispatchSupervisor |
| GET | `/storm-events/{id}/cost-reports` | List cost-report snapshots of a storm. | DispatchSupervisor, Operator, YardManager, CitizenServices |
| POST | `/_clock/set_current_utc` | Set the server logical clock. | DispatchSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 422 |
| ERR_INVALID_WINDOW | 422 |
| ERR_STORM_NOT_ACTIVE | 409 |
| ERR_STORM_ALREADY_CLOSED | 409 |
| ERR_STORM_NOT_CLOSED | 409 |
| ERR_BILLING_NOT_OPEN | 409 |
| ERR_ASSIGNMENT_NOT_PLANNED | 409 |
| ERR_ASSIGNMENT_NOT_IN_PROGRESS | 409 |
| ERR_ROUTE_ALREADY_ACTIVE | 409 |
| ERR_APPLICATION_ALREADY_VOIDED | 409 |
| ERR_CALLOUT_NOT_ISSUED | 409 |
| ERR_CALLOUT_NOT_CANCELLABLE | 409 |
| ERR_COMPLAINT_INVALID_STATE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_VEHICLE_OUT_OF_SERVICE | 422 |
| ERR_VEHICLE_MISSING_SPREADER | 422 |
| ERR_OPERATOR_NOT_ON_CALL | 409 |
| ERR_VEHICLE_DOUBLE_BOOKED | 409 |
| ERR_OPERATOR_REST_VIOLATION | 409 |
| ERR_INSUFFICIENT_MATERIAL | 409 |
| ERR_STALE_STORM_VERSION | 412 |
