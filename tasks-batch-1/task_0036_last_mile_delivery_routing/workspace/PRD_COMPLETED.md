# Last-Mile Delivery Routing API — Product Requirements Document

## 1. Introduction

Last-mile delivery is the final and most operationally fragile leg of a parcel's journey: the stretch from a regional sorting hub to the recipient's door. This document specifies the API for a UPS/FedEx-style last-mile platform that coordinates the people, vehicles, and facilities involved in that leg. Inbound parcels are received, sorted into transit centers, batched into driver routes, taken out for delivery against customer time windows, and either handed off (with or without a signature) or carried back for redelivery. The platform must keep four classes of operator working from a single consistent picture of the day: dispatch planners assembling routes, sort-floor associates loading parcels into hubs, drivers logging what happened at each door, and customer-service agents renegotiating delivery windows on the recipient's behalf.

The hard problems this API exists to solve are temporal and safety-driven. Delivery windows must be honored and must not be allowed to collide on a single route. Hazardous-materials parcels must never touch an uncertified hub or an uncertified driver. Signature-required and Driver-Release parcels follow strict proof-of-delivery rules. Vehicles must not be overloaded, hubs must not be over-filled, and a driver must not be committed to two routes on the same day. Layered on top, the platform meters service quality through a per-driver failure score and prices redelivery through an escalating surcharge, so that repeated failed attempts have both an operational and a financial consequence. Because routes are planned collaboratively and dispatched once, the dispatch action is guarded by optimistic concurrency so that a planner never dispatches a route whose composition has changed underneath them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint. All resource collections in this API are mounted under the `/delivery` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is missing or invalid, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The platform recognizes exactly four roles: `DispatchManager`, `SortAssociate`, `Driver`, and `CustomerServiceAgent`. The `DispatchManager` owns transit centers, drivers, routes, and stops — planning, dispatching, rescheduling, cancelling, and completing routes. The `SortAssociate` works the transit center floor, registering inbound parcels and sorting them into hubs. The `Driver` executes assigned stops and logs delivery attempts at the door. The `CustomerServiceAgent` handles customer-requested adjustments to delivery windows.

For `DispatchManager`, `SortAssociate`, and `CustomerServiceAgent`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`. For `Driver`, the value of `X-User-ID` is the `id` of the acting `Driver` entity; any ownership check on a resource that references a `Driver` compares that resource's driver foreign key to `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless explicitly overridden by a particular endpoint, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order. List responses populate the `limit`, `offset`, `total_count`, and `has_more` fields in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most primary resources — `TransitCenter`, `Driver`, `Parcel`, `DeliveryRoute`, `DeliveryStop`, and `Appointment` — carry a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at its initial value of 1 and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in §2.8.

The `DeliveryAttempt` resource is an exception. It is an append-only event record and carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Once written, an attempt is never modified.

### 2.5. Hierarchical Consistency and Cascading Effects

Many operations in this domain mutate more than one entity at once, and every such cascade must be applied atomically. Whenever the server changes any persisted field on a resource that carries `version`, it also refreshes that resource's `updated_at` and increments its `version` by one. This applies equally to derived fields: when the server recomputes a route's load metrics, a center's sorted count, a stop's fee or attempt count, or a driver's failure score, those are mutations of the owning resource.

Several derived values are recomputed automatically rather than supplied by clients, and they are always kept current with the events that affect them. A transit center's `sorted_count` reflects the live number of parcels sorted there; a route's `planned_weight_kg`, `committed_weight_kg`, and `stop_count` reflect its current stop set; a stop's `attempt_count` and `redelivery_fee_cents` reflect its attempt and reschedule history; and a driver's `failure_points` reflects the running service-quality accumulator. The precise recomputation rules live in the workflow narratives of §3.

### 2.6. Nested Reference Validation

All resources are addressed by their own collection paths; the topology is flat rather than deeply nested. Even so, many requests carry resource identifiers both in the URL path and in the request body as foreign-key references. The server validates these left-to-right, path before body. A path identifier that does not resolve to an existing resource is rejected first, with the not-found error for that resource type — `ERR_CENTER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, or `ERR_APPOINTMENT_NOT_FOUND` as appropriate — before any body reference is examined. Only after all path identifiers resolve does the server check that required foreign keys in the body refer to existing resources, again returning the matching not-found error.

### 2.7. Precision and Monetary Rounding

Two distinct numeric regimes apply. Parcel weights and the weight sums derived from them (`planned_weight_kg`, `committed_weight_kg`, `vehicle_capacity_kg`) are kept in kilograms at full double precision and are never rounded. Failure-score arithmetic is exact and is floored at zero, as described in §3.6.

Monetary values are tracked in whole cents as integers. Wherever a fee computation produces a fractional cent, the result is rounded half up to the nearest whole cent. The order in which rounding is applied relative to other arithmetic is significant and is pinned individually for each fee calculation in §3 — readers must follow the stated evaluation order exactly, because rounding before versus after an intermediate step yields different totals at half-cent boundaries.

### 2.8. Optimistic Concurrency at Dispatch

Routes are assembled collaboratively: stops are added and cancelled, and appointment-applied window edits mutate a route's stops, each of which increments the route's `version`. Dispatch is the single committing action that turns a planning view into a live run, and it is guarded against acting on a stale plan. A dispatch request must carry `expected_route_version`, a non-optional field that must equal the target route's current `version`. If another writer has advanced the route's `version` since the client last read it — by adding or cancelling a stop, or by applying an appointment that moved one of its stops — the dispatch is rejected with `ERR_STALE_ROUTE_VERSION` and HTTP status 412. This prevents a planner from dispatching a route whose committed load and stop set no longer match the picture they were working from. No other endpoint takes a version field; dispatch is the only optimistic-concurrency-guarded operation.

### 2.9. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed priority order so that failures surface predictably. The order is: first, presence and validity of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role authorization for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); third, existence of the path identifiers and then the body foreign-key references, validated left-to-right with path before body (the matching not-found error); fourth, request-body field types and ranges (`ERR_INVALID_REQUEST`); fifth, the tracking-code uniqueness check on parcel registration (`ERR_DUPLICATE_TRACKING_CODE`); sixth, the state precondition for the requested transition (the transition-specific conflict error). Domain-specific business checks — hazmat certification, signature and Driver-Release rules, appointment-window conflict, stop-limit and sequence uniqueness, sort capacity, double-booking, vehicle capacity, and the dispatch optimistic-concurrency check — are evaluated after the state precondition holds. Each domain check and its trigger condition is described alongside the workflow it guards in §3.

## 3. Business Logic & Workflows

### 3.1. Transit Centers and the Sort Floor

A `DispatchManager` establishes a sorting hub by creating a `TransitCenter` with a `name`, a `sort_capacity`, and an optional `hazmat_certified` flag. The `sort_capacity` is the maximum number of parcels the hub may simultaneously hold in the `SORTED` state and must be at least 1; `hazmat_certified` declares whether the hub may sort hazardous-materials parcels and defaults to false when omitted. A new center opens in `OPEN` status with its `sorted_count` at zero. A `DispatchManager` may later close a hub to new sorting, moving its `status` to `CLOSED`.

Parcels enter the system through registration, which a `SortAssociate` or a `DispatchManager` may perform. A `Parcel` is registered with a `tracking_code`, a `weight_kg`, and four optional descriptors: `service_level` (one of `GROUND`, `EXPRESS`, or `PRIORITY`, defaulting to `GROUND`), `signature_required` (defaulting to false), `hazmat_class` (one of `NONE`, `CLASS_3`, or `CLASS_8`, defaulting to `NONE`), and `driver_release_authorized` (defaulting to false, indicating whether the shipper pre-authorized leaving the parcel without a signature). The `weight_kg` must be greater than zero. A freshly registered parcel begins in `RECEIVED` status with its `sorted_at_center_id` null. The `tracking_code` must be unique across all parcels; registering a parcel whose code already exists is rejected with `ERR_DUPLICATE_TRACKING_CODE`.

Sorting is a `SortAssociate` action that moves a parcel from `RECEIVED` to `SORTED` at a chosen hub, supplied as `center_id` in the request. The parcel must currently be in `RECEIVED` (otherwise `ERR_PARCEL_NOT_RECEIVED`), and the target center must be `OPEN` (otherwise `ERR_CENTER_CLOSED`). If the parcel's `hazmat_class` is anything other than `NONE`, the target center's `hazmat_certified` must be true, or the request is rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED`. The hub must also have room: its `sorted_count` must be strictly less than its `sort_capacity`, otherwise the sort is rejected with `ERR_SORT_CAPACITY_EXCEEDED`. On success, the parcel's `sorted_at_center_id` is set to the target center and the center's `sorted_count` is recomputed. A center's `sorted_count` is always the count of parcels whose `status` is exactly `SORTED` and whose `sorted_at_center_id` equals that center's `id`; this recomputation runs on every sort, on stop creation (when a parcel leaves `SORTED` for `ROUTED`), and on stop or route cancellation (when a parcel reverts to `SORTED`). The set of parcels currently sorted at a hub can be retrieved as a reverse lookup over `sorted_at_center_id`.

### 3.2. Drivers and Service Quality

A `DispatchManager` registers a `Driver` with a `name`, a `vehicle_capacity_kg`, and an optional `hazmat_certified` flag. The `vehicle_capacity_kg` is the maximum total parcel weight the driver's vehicle may carry and must be greater than zero; `hazmat_certified` declares whether the driver may carry hazardous parcels and defaults to false. A new driver starts `ACTIVE` with `failure_points` at zero. A `DispatchManager` may suspend a driver, moving `status` to `SUSPENDED`; a suspended driver cannot be assigned to a route at dispatch. The set of routes assigned to a driver can be retrieved as a reverse lookup over `driver_id`, and a driver record always reports its current computed `failure_points`.

The `failure_points` value is a running service-failure score, never displayed below zero and never capped above. Its movements are detailed alongside the attempt and reschedule workflows in §3.4 through §3.6.

### 3.3. Building and Dispatching a Route

A `DispatchManager` creates a `DeliveryRoute` in `PLANNING` status by supplying a `driver_id`, an `origin_center_id`, a `service_date` (a calendar date conventionally in YYYY-MM-DD form, validated only as a non-empty string — its textual format is not otherwise checked, and the dispatch double-booking comparison treats it as an opaque exact-equality string), and a `max_stops`. The `max_stops` is the ceiling on how many stops the route may hold and must be at least 1. A new route reports `planned_weight_kg`, `committed_weight_kg`, and `stop_count` all at zero.

Stops are then added one at a time. Adding a `DeliveryStop` (a `DispatchManager` action) takes a `route_id`, a `parcel_id`, a `sequence`, a `window_start_min`, and a `window_end_min`. The `sequence` is the stop's ordering index on the route and must be at least 1; it must be unique among the route's non-`CANCELLED` stops. The `window_start_min` and `window_end_min` express the delivery time window in minutes from local midnight: `window_start_min` lies in the range 0 through 1440 inclusive, and `window_end_min` must be greater than `window_start_min` and at most 1440. The referenced parcel must currently be in `SORTED` status, otherwise the add is rejected with `ERR_PARCEL_NOT_SORTED`. Adding a stop must not push the route's `stop_count` above its `max_stops`, and the new `sequence` must not duplicate an existing non-`CANCELLED` stop's sequence; either violation is rejected with `ERR_ROUTE_STOP_LIMIT`. On success, the new stop starts in `PENDING`, the parcel moves from `SORTED` to `ROUTED`, the origin center's `sorted_count` is recomputed downward, the route's `stop_count`, `planned_weight_kg`, and `committed_weight_kg` are recomputed, and the route's `version` is incremented. Stops can be listed filtered by `route_id` and by `parcel_id`.

A `DispatchManager` may cancel an individual stop, but only while it is still in `PENDING`; a cancel attempt against a stop in any other state is rejected with `ERR_STOP_NOT_CANCELLABLE`. Cancelling a `PENDING` stop moves it from `PENDING` to `CANCELLED`, reverts its parcel from `ROUTED` back to `SORTED` with the parcel's `sorted_at_center_id` restored to the route's `origin_center_id`, recomputes that origin center's `sorted_count` upward, and recomputes the route's load metrics.

Dispatching a route advances it from `PLANNING` to `DISPATCHED` and is the moment the run goes live. The route must be in `PLANNING` (otherwise `ERR_ROUTE_NOT_PLANNING`) and must hold at least one non-`CANCELLED` stop (otherwise `ERR_ROUTE_EMPTY`). The assigned driver's `status` must be `ACTIVE`, or the dispatch is rejected with `ERR_DRIVER_SUSPENDED`. The route's `committed_weight_kg` must not exceed the driver's `vehicle_capacity_kg`; if it does, the dispatch is rejected with `ERR_VEHICLE_CAPACITY_EXCEEDED`. If any stop's parcel has a `hazmat_class` other than `NONE`, the driver's `hazmat_certified` must be true, otherwise the dispatch is rejected with `ERR_DRIVER_NOT_HAZMAT_CERTIFIED`. The driver must not already hold another `DISPATCHED` route whose `service_date` is identical to this route's `service_date`: dispatch claims the whole day exclusively, keyed on exact `service_date` string equality, and a collision is rejected with `ERR_DRIVER_DOUBLE_BOOKED`. Finally, the request's `expected_route_version` must equal the route's current `version`, or it is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412) per §2.8. When all checks pass, every `PENDING` stop on the route transitions automatically to `OUT_FOR_DELIVERY` and the route's `version` is incremented by one.

Completing a route advances it from `DISPATCHED` to `COMPLETED`. The route must be in `DISPATCHED` (otherwise `ERR_ROUTE_NOT_DISPATCHED`), and no stop may still be open — that is, no stop may be in `OUT_FOR_DELIVERY`, `ATTEMPTED`, or `REDELIVERY_SCHEDULED`; if any open stop remains, completion is rejected with `ERR_OPEN_STOPS_REMAIN`.

Cancelling a route is permitted only while it is in `PLANNING`; otherwise the request is rejected with `ERR_ROUTE_NOT_CANCELLABLE`. Cancellation moves the route to `CANCELLED` and cascades down: every non-`CANCELLED` stop on the route is moved to `CANCELLED`, and for each such cascaded stop its parcel reverts from `ROUTED` back to `SORTED`, the parcel's `sorted_at_center_id` is restored to the route's `origin_center_id`, and that origin center's `sorted_count` is recomputed upward. Routes can be listed filtered by `driver_id` and `origin_center_id`.

A route exposes two distinct weight views, both summed over the parcels of its stops in kilograms with no rounding. The `planned_weight_kg` is the sum of `weight_kg` over all stops whose `status` is `PENDING`, `OUT_FOR_DELIVERY`, `ATTEMPTED`, `REDELIVERY_SCHEDULED`, or `DELIVERED` — the capacity-planning view of everything loaded for the run, including parcels already delivered. The `committed_weight_kg` is the sum of `weight_kg` over stops whose `status` is `PENDING`, `OUT_FOR_DELIVERY`, `ATTEMPTED`, or `REDELIVERY_SCHEDULED` — the live owing-load view, which excludes both `DELIVERED` and `FAILED` stops because those no longer owe carriage. The two are equal only before any delivery completes; `committed_weight_kg` is the value gated against vehicle capacity at dispatch. The `stop_count` is the number of the route's stops whose `status` is not `CANCELLED`. All three are recomputed on stop creation, on stop cancellation, on route dispatch, and on each delivery attempt that changes a stop's status.

### 3.4. At the Door: Delivery Attempts

A `Driver` records what happened at a stop by logging a `DeliveryAttempt` against it, supplying an `outcome` (one of `DELIVERED`, `NO_ONE_HOME`, `REFUSED`, or `ADDRESS_ISSUE`) and optionally a `signature_name` and a `used_driver_release` flag (defaulting to false). The stop must be in either `OUT_FOR_DELIVERY` or `REDELIVERY_SCHEDULED`; an attempt logged against a stop in any other state is rejected with `ERR_STOP_NOT_OUT_FOR_DELIVERY`. Every attempt appends a `DeliveryAttempt` record, after which the stop's `attempt_count` is recomputed as the number of attempt records for that stop. Each attempt also carries a computed `attempt_index`, the 1-based chronological ordinal of that attempt on its stop (ordered by `created_at`), equal to the stop's `attempt_count` immediately after the append. The full attempt history of a stop can be retrieved as a reverse lookup over `stop_id`.

A successful attempt — `outcome` of `DELIVERED` — drives the stop to `DELIVERED` from either `OUT_FOR_DELIVERY` or `REDELIVERY_SCHEDULED`, and cascades the parcel from `ROUTED` to `DELIVERED`. Two proof-of-delivery rules guard this success path. If the parcel's `signature_required` is true and `used_driver_release` is not true, a non-empty `signature_name` must be supplied, otherwise the attempt is rejected with `ERR_SIGNATURE_REQUIRED`. Setting `used_driver_release` to true is only allowed when the parcel's `driver_release_authorized` is true; using Driver Release on a parcel the shipper did not pre-authorize is rejected with `ERR_DRIVER_RELEASE_NOT_AUTHORIZED`. Driver Release, when authorized, substitutes for the signature so that a signature-required parcel may be delivered without a captured `signature_name`.

A failed attempt — any `outcome` other than `DELIVERED` — drives the stop to `ATTEMPTED` from either `OUT_FOR_DELIVERY` or `REDELIVERY_SCHEDULED` and adds a penalty to the driver's `failure_points` as described in §3.6. The two source states are treated identically: whether a stop is on its first run (`OUT_FOR_DELIVERY`) or has already been rescheduled (`REDELIVERY_SCHEDULED`), a non-delivered outcome lands it in `ATTEMPTED` and a delivered outcome lands it in `DELIVERED`.

### 3.5. Rescheduling, Redelivery, and Returns

After a failed attempt leaves a stop in `ATTEMPTED`, a `DispatchManager` resolves it by rescheduling. The stop must be in `ATTEMPTED`, otherwise the request is rejected with `ERR_STOP_NOT_ATTEMPTED`. The outcome branches on how many times the stop has already been attempted. While the stop's `attempt_count` is below the maximum of 3, rescheduling moves the stop from `ATTEMPTED` to `REDELIVERY_SCHEDULED` and recomputes its `redelivery_fee_cents`. Once `attempt_count` has reached 3, redelivery is exhausted: rescheduling instead drives the stop to `FAILED`, cascades the parcel from `ROUTED` to `RETURNED`, and adds the return penalty to the driver's `failure_points`. An attempt to take the redelivery branch when `attempt_count` has already reached 3 — that is, when the maximum number of attempts is reached — is the condition signalled by `ERR_MAX_ATTEMPTS_REACHED`.

A stop that has gone to `REDELIVERY_SCHEDULED` is eligible for a fresh attempt and can again be driven to `DELIVERED` or back to `ATTEMPTED` per §3.4. When a stop is successfully delivered out of `REDELIVERY_SCHEDULED`, the driver earns a recovery credit against their `failure_points` as described in §3.6.

The `redelivery_surcharge` calculation governs `redelivery_fee_cents`, which is a cumulative running total: each reschedule that schedules a redelivery adds its own surcharge to the field rather than overwriting it, so the value grows across successive reschedules of the same stop. For a given reschedule, the surcharge is built up as follows. Start from a service-level base: 300 cents for a `GROUND` parcel, 500 cents for `EXPRESS`, and 800 cents for `PRIORITY`. Add an attempt-escalation increment of 150 cents multiplied by the reschedule index, where the reschedule index is the stop's `attempt_count` minus 1 taken at the moment of reschedule (so the first reschedule, which follows the first attempt, uses index 0; the second uses index 1; and so on). To that escalated base, add a flat 120-cent signature surcharge if the parcel's `signature_required` is true, and nothing otherwise. Then multiply the resulting sum by a hazmat multiplier of 1.5 if the parcel's `hazmat_class` is anything other than `NONE`, or by 1 otherwise. The multiply-then-round order is pinned: take the sum of the escalated base and the signature surcharge, multiply that sum by the hazmat multiplier, and only then round the product half up to a whole number of cents. The rounded result is this reschedule's surcharge, which is added to the accumulated `redelivery_fee_cents`.

### 3.6. The Driver Failure Score

A driver's `failure_points` is a running accumulator that begins at zero, is floored at zero so it is never negative, and has no upper cap. It is recomputed on every attempt append, on a successful redelivery (a stop moving from `REDELIVERY_SCHEDULED` to `DELIVERED`), and on a stop being driven to `FAILED`.

Each non-delivered attempt logged against a stop on the driver's route adds a penalty composed of three parts. The base penalty is 10 points. On top of that, an escalation of 5 points is multiplied by the attempt's `attempt_index` minus 1, so the first attempt carries no escalation, the second carries 5 points of escalation, the third carries 10, and so on — later attempts cost more than earlier ones. Finally, if the parcel's `hazmat_class` is anything other than `NONE`, an extra 8 points is added; for non-hazmat parcels nothing is added. The sum of base, escalation, and the hazmat extra is added to `failure_points`.

Two countervailing movements complete the picture. When a stop is successfully redelivered out of `REDELIVERY_SCHEDULED` into `DELIVERED`, 6 points are subtracted from `failure_points` as a recovery credit (with the floor at zero applied so the score never drops below zero). When a stop is driven to `FAILED` and its parcel returns to the hub, 20 points are added to `failure_points`.

### 3.7. Customer Appointment Adjustments

A `CustomerServiceAgent` represents the recipient's request to move a delivery window. Creating an `Appointment` takes a `stop_id`, a `requested_start_min`, and a `requested_end_min`; the requested window is expressed in minutes from local midnight, with `requested_start_min` in the range 0 through 1440 inclusive and `requested_end_min` greater than `requested_start_min` and at most 1440. A new appointment begins in `REQUESTED` status. Appointments can be listed filtered by `stop_id`.

A `CustomerServiceAgent` may reject a requested appointment, moving it from `REQUESTED` to `REJECTED`; rejection requires the appointment to be in `REQUESTED`, otherwise the request fails with `ERR_APPOINTMENT_NOT_REQUESTED`. Applying an appointment is the action that actually edits the stop's window. The appointment must be in `REQUESTED` (otherwise `ERR_APPOINTMENT_NOT_REQUESTED`). The target stop must be in `PENDING`, `OUT_FOR_DELIVERY`, or `REDELIVERY_SCHEDULED`; if the stop is in any other (terminal or otherwise locked) state, the apply is rejected with `ERR_STOP_WINDOW_LOCKED`. The requested window must not collide with another non-`CANCELLED` stop on the same route once a 30-minute buffer is taken into account: a conflict exists when the requested start is earlier than another stop's window end plus 30 minutes and, simultaneously, the requested end plus 30 minutes is later than that other stop's window start. In other words, two windows conflict not only when they literally overlap but also when the gap between adjacent windows is less than 30 minutes; any such buffered overlap is rejected with `ERR_APPOINTMENT_WINDOW_CONFLICT`. This buffered-minute overlap test is distinct from the whole-day exact-equality semantics of the dispatch double-booking check. On a successful apply, the appointment moves from `REQUESTED` to `APPLIED`, the target stop's `window_start_min` and `window_end_min` are overwritten with the appointment's `requested_start_min` and `requested_end_min`, and because a stop has been mutated, the stop's route has its `version` incremented by one.

### 3.8. The Route Handling-Fee Manifest

A `DispatchManager` may pull a computed manifest for a route, which reports the route's `route_id`, its `stop_count`, and a `total_handling_fee_cents`. The manifest is a read-only computation and persists nothing. Its handling fee is computed per line item and then summed, in pinned order. For each non-`CANCELLED` stop on the route, taken in ascending `sequence` (ties broken by `created_at` ascending), compute that line's raw fee as a base of 50 cents plus the parcel's `weight_kg` multiplied by 12.5 cents per kilogram, then round that raw fee half up to a whole number of cents to obtain the line fee. The `total_handling_fee_cents` is the sum of those already-rounded per-line fees. The order is pinned at round-per-line-item then sum, not sum-then-round; the two strategies diverge at fractional half-cent boundaries, and this manifest uses round-then-sum.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return HTTP 201 Created. Operations that modify an existing resource — including all state-transition actions and computed reads — return HTTP 200 OK. Logging a delivery attempt (`POST /delivery/stops/{stopId}/attempts`) is classified as a resource creation and returns HTTP 201 Created even though it also transitions the target stop, because it appends a new stand-alone `DeliveryAttempt` record, which is returned as the response `data`. To reconstruct the full request and response shape and the side effects of any endpoint below, refer back to the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/delivery/transit-centers` | Create a transit center / sorting hub | DispatchManager |
| GET | `/delivery/transit-centers` | List transit centers | DispatchManager, SortAssociate, Driver, CustomerServiceAgent |
| GET | `/delivery/transit-centers/{centerId}` | Get a transit center | DispatchManager, SortAssociate, Driver, CustomerServiceAgent |
| POST | `/delivery/transit-centers/{centerId}/close` | Close a transit center to new sorting | DispatchManager |
| GET | `/delivery/transit-centers/{centerId}/sorted-parcels` | List parcels currently SORTED at this center | DispatchManager, SortAssociate |
| POST | `/delivery/drivers` | Create a driver | DispatchManager |
| GET | `/delivery/drivers` | List drivers | DispatchManager, CustomerServiceAgent |
| GET | `/delivery/drivers/{driverId}` | Get a driver (includes computed failure points) | DispatchManager, Driver, CustomerServiceAgent |
| POST | `/delivery/drivers/{driverId}/suspend` | Suspend a driver | DispatchManager |
| GET | `/delivery/drivers/{driverId}/routes` | List routes assigned to a driver | DispatchManager, Driver |
| POST | `/delivery/parcels` | Register an inbound parcel | SortAssociate, DispatchManager |
| GET | `/delivery/parcels` | List parcels; filterable by sorted center | DispatchManager, SortAssociate, CustomerServiceAgent |
| GET | `/delivery/parcels/{parcelId}` | Get a parcel | DispatchManager, SortAssociate, Driver, CustomerServiceAgent |
| POST | `/delivery/parcels/{parcelId}/sort` | Sort a RECEIVED parcel into a transit center | SortAssociate |
| POST | `/delivery/routes` | Create a delivery route in PLANNING | DispatchManager |
| GET | `/delivery/routes` | List routes; filterable by driver and origin center | DispatchManager, Driver |
| GET | `/delivery/routes/{routeId}` | Get a route (includes computed load metrics) | DispatchManager, Driver |
| GET | `/delivery/routes/{routeId}/manifest` | Computed per-route handling-fee manifest | DispatchManager |
| POST | `/delivery/routes/{routeId}/dispatch` | Dispatch a planned route (OCC-guarded) | DispatchManager |
| POST | `/delivery/routes/{routeId}/complete` | Complete a dispatched route once no open stops remain | DispatchManager |
| POST | `/delivery/routes/{routeId}/cancel` | Cancel a planning route; cascade-cancels stops | DispatchManager |
| POST | `/delivery/stops` | Add a delivery stop to a planning route | DispatchManager |
| GET | `/delivery/stops` | List stops; filterable by route and parcel | DispatchManager, Driver |
| GET | `/delivery/stops/{stopId}` | Get a stop | DispatchManager, Driver, CustomerServiceAgent |
| POST | `/delivery/stops/{stopId}/attempts` | Log a delivery attempt against a stop | Driver |
| GET | `/delivery/stops/{id}/attempts` | List delivery attempts for a stop | DispatchManager, Driver |
| POST | `/delivery/stops/{stopId}/reschedule` | Reschedule an attempted stop, or mark FAILED at max attempts | DispatchManager |
| POST | `/delivery/stops/{stopId}/cancel` | Cancel a pending stop; reverts parcel to SORTED | DispatchManager |
| POST | `/delivery/appointments` | Create a customer time-window adjustment request | CustomerServiceAgent |
| GET | `/delivery/appointments` | List appointments; filterable by stop | CustomerServiceAgent, DispatchManager |
| GET | `/delivery/appointments/{appointmentId}` | Get an appointment | CustomerServiceAgent, DispatchManager |
| POST | `/delivery/appointments/{appointmentId}/apply` | Apply a requested appointment, moving the stop's window | CustomerServiceAgent |
| POST | `/delivery/appointments/{appointmentId}/reject` | Reject a requested appointment | CustomerServiceAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_TRACKING_CODE` | 409 Conflict |
| `ERR_CENTER_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_PARCEL_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PARCEL_NOT_RECEIVED` | 409 Conflict |
| `ERR_PARCEL_NOT_SORTED` | 409 Conflict |
| `ERR_CENTER_CLOSED` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNING` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ROUTE_EMPTY` | 409 Conflict |
| `ERR_OPEN_STOPS_REMAIN` | 409 Conflict |
| `ERR_STOP_NOT_OUT_FOR_DELIVERY` | 409 Conflict |
| `ERR_STOP_NOT_ATTEMPTED` | 409 Conflict |
| `ERR_STOP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_REQUESTED` | 409 Conflict |
| `ERR_STOP_WINDOW_LOCKED` | 409 Conflict |
| `ERR_HAZMAT_HUB_NOT_CERTIFIED` | 409 Conflict |
| `ERR_DRIVER_NOT_HAZMAT_CERTIFIED` | 409 Conflict |
| `ERR_DRIVER_RELEASE_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_SIGNATURE_REQUIRED` | 409 Conflict |
| `ERR_DRIVER_SUSPENDED` | 409 Conflict |
| `ERR_DRIVER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_APPOINTMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_ROUTE_STOP_LIMIT` | 409 Conflict |
| `ERR_SORT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_MAX_ATTEMPTS_REACHED` | 409 Conflict |
| `ERR_VEHICLE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STALE_ROUTE_VERSION` | 412 Precondition Failed |
