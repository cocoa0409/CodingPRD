# Last-Mile Delivery API — Product Requirements Document

## 1. Introduction

Last-mile delivery is the most visible — and most expensive — segment of a parcel network. From the moment a shipment is inducted at a transit center, through the optimization of its route, to the driver's final attempt at the front door, every step must reconcile customer expectations (a tight delivery window, occasionally an unattended drop, sometimes a signature) with the operator's economic and safety realities (regulated hazardous goods, redelivery costs, hub specialization). This document specifies the Last-Mile Delivery API, the system that orchestrates that flow end to end.

The system models five core resources — parcels, routes, transit centers, drivers, and customers — and the side artifacts they produce: route stops, delivery attempts, and customer appointment requests. Workflows are deliberately stateful: a parcel moves through induction, hub sorting, route loading, delivery attempts, and either successful delivery or return-to-sender; a route is planned, dispatched, executed, and closed; an appointment is requested, then accepted, rejected, or superseded. Calculations are likewise multi-stage: a forward-looking shipping fee is quoted at induction, while a definitive final fee is computed only at terminalization after all attempts and appointment changes have been tallied.

The API is mounted under the URL prefix `/parcels` for the parcel resource family, with adjacent prefixes for the other resource families (`/customers`, `/transit-centers`, `/drivers`, `/routes`, `/appointments`). Test instrumentation is mounted under `/_clock`. All endpoints are JSON over HTTP, authenticated by headers, and governed by the global rules in §2.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and contract-level mechanics that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity in which that principal is acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes five role names — spelled exactly as `Customer`, `Driver`, `Dispatcher`, `SortingHubOperator`, and `ComplianceOfficer`. When a request carries a valid pair of headers but the role is not authorized for the endpoint, the response is `ERR_FORBIDDEN`.

The `X-User-ID` value is interpreted according to the role:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field (most notably `Parcel.customer_id` and the `customer_id` on an `Address`) to `X-User-ID`. A `Customer` reading or filing an appointment for a parcel they do not own must be rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on routes and delivery attempts compare `Route.driver_id` and `DeliveryAttempt.driver_id` to `X-User-ID`. A driver may only check themselves in or out and may only record attempts on stops belonging to routes assigned to them.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`.
- When `X-User-Role` is `SortingHubOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is similarly an opaque operator identifier; this role is strictly read-only on operational endpoints and may inspect parcels, routes, transit centers, and customers without performing mutations.

The auth checks above are the two highest-priority validations in the system: header presence is checked before role authorization, which is checked before path-id existence, which in turn is checked before any body-level validation.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items returned and defaults to 10, with a minimum of 1 and a maximum of 100; values outside that range are rejected. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints sort their results by `created_at` in ascending order.

Every paginated list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

All top-level resources — `Customer`, `TransitCenter`, `Driver`, `Parcel`, `Route`, and `Appointment` — share a standard set of system-managed fields:

- `id` (string): a unique server-generated identifier formatted as a UUID, with no type-prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. Every mutation, including server-driven recomputations of derived fields such as `quoted_fee`, `parcels_on_belt`, `total_distance_km`, `stop_count`, `hazmat_present`, `redelivery_attempts`, and `redelivery_attempts_used_30d`, refreshes `updated_at` on the affected resource.
- `version` (integer): a system-managed counter that increments by one on every mutation to the resource. It is used for optimistic concurrency control as described in §2.10.

Two scaffold entities are intentionally lightweight and carry only the `id` and `created_at` fields — both `updated_at` and `version` are absent from their representations. These are `Address` (a child of `Customer`, identified by `customer_id` plus the geocoded fields) and the per-attempt and per-stop records `DeliveryAttempt` and `RouteStop`, which are append-only with no mutation surface beyond the controlled state transitions described in §3. The synthetic `Clock` entity exposes only a single `now` instant and is described in §2.11.

### 2.5. Nested Resource Retrieval and Hierarchical Consistency

When an endpoint path carries multiple identifiers — for example a stop nested under a route, or an address nested under a customer — the system validates each identifier in strict left-to-right order. The first identifier that does not resolve to an existing row yields `ERR_NOT_FOUND` with a message naming the missing parent; only when every preceding path id has resolved does the system examine the leaf id. Body-level foreign-key references (a `customer_id` on a parcel, a `parcel_id` on an appointment, a `driver_id` on a route) are validated after path ids; a body-level reference to a non-existent row produces `ERR_REFERENCE_NOT_FOUND`.

Hierarchical state propagation is bi-directional. A state transition on a parent always cascades to the children it implicates: dispatching a route advances every parcel on it from `ON_VEHICLE` to `OUT_FOR_DELIVERY`, cancelling a planned route reverts every parcel on it to `SORTED` and deletes every `RouteStop` attached to the route, and closing a route forces any parcel still in `OUT_FOR_DELIVERY` into `EXCEPTION` as if a `NO_ONE_HOME` had been recorded. Conversely, mutations to children flow upward where the parent maintains a derived summary: adding or deleting a stop recomputes `total_distance_km`, `stop_count`, and `hazmat_present` on the parent route, and recording a failed delivery attempt increments `redelivery_attempts` on the parent parcel. Every such cascade is a mutation in its own right — it refreshes `updated_at` and increments `version` on each affected resource.

### 2.6. Hazardous-Materials Protocol

The system treats hazardous goods as a first-class compliance concern that cuts across induction, sorting, route loading, and dispatch. Every parcel declares a `hazmat_class` drawn from the enumerated set `NONE`, `CLASS_2`, `CLASS_3`, `CLASS_4`, `CLASS_8`, and `CLASS_9`; a value other than `NONE` marks the parcel as regulated.

A regulated parcel may only be inducted into or sorted by a `TransitCenter` whose `hazmat_certified` flag is `true`; either operation against a non-certified hub is rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED`. A regulated parcel may only be loaded onto a `Route` whose assigned `Driver` carries `hazmat_endorsement` equal to `true`, and a route whose `hazmat_present` flag is `true` may only be dispatched with a hazmat-endorsed driver; either violation is rejected with `ERR_DRIVER_NO_HAZMAT_ENDORSEMENT`. Finally, the driver-release outcome — leaving a parcel without a signature — is categorically forbidden for any regulated parcel: an attempt to record `DRIVER_RELEASED` on a parcel whose `hazmat_class` is anything other than `NONE` must be rejected with `ERR_DRIVER_RELEASE_NOT_AUTHORIZED`.

### 2.7. Signature and Driver-Release Authorization

Two parcel-level flags govern the rules of the final hand-off. `signature_required`, set at induction or via a controlled update while the parcel is still in `INDUCTED` or `IN_TRANSIT_HUB`, declares that the recipient must sign for the parcel; `driver_release_authorized`, set on the `Customer` record, declares that the customer permits unattended drops at their default address as a standing instruction. The interaction of these flags is strict.

When a delivery attempt is recorded with `outcome` of `DELIVERED_SIGNED`, the `signature_blob_ref` field must be present and non-empty; omitting it is rejected with `ERR_SIGNATURE_MISSING`. When an attempt is recorded with `outcome` of `DRIVER_RELEASED`, the `release_location` field describes where the parcel was left, and three independent gates must all hold: the parcel's `signature_required` is `false`, the customer's `driver_release_authorized` is `true`, and the parcel's `hazmat_class` is `NONE`. If any one of these gates fails — signature was required, the customer never authorized release, or the parcel is regulated — the attempt is rejected with `ERR_DRIVER_RELEASE_NOT_AUTHORIZED`.

The `Parcel`'s `last_attempt_outcome` field records the result of the most recent attempt and is drawn from the same enumeration the attempt itself uses: `NONE` until the first attempt, then one of `DELIVERED_SIGNED`, `DRIVER_RELEASED`, `NO_ONE_HOME`, `REFUSED`, `ADDRESS_INVALID`, or `HAZMAT_BLOCKED`.

### 2.8. Fee Precision and Rounding

All monetary values — `quoted_fee`, `final_fee` on a parcel and `fee_charged` on an appointment — are stored and returned with exactly two decimal places. All multi-step fee calculations are performed in full precision internally and rounded once, at the end, using the "round half up" convention. Distances are likewise carried to two decimal places on `Route.total_distance_km`, and time-window arithmetic operates at minute granularity with arrival instants truncated to the start of the minute.

### 2.9. Validation Priority

Validation across the API proceeds in a deterministic priority order so that, when more than one rule could plausibly fail, the response always names the highest-priority failure. The order is:

1. Header presence — missing or malformed `X-User-Role` / `X-User-ID` yields `ERR_UNAUTHENTICATED`.
2. Role authorization — a role not permitted for the endpoint yields `ERR_FORBIDDEN`.
3. Path-id existence (left-to-right) — a missing row yields `ERR_NOT_FOUND`.
4. Body-level foreign-key existence on mutation endpoints — a dangling reference yields `ERR_REFERENCE_NOT_FOUND`.
5. State-machine admissibility on all transition endpoints — an operation requested in a state that does not admit it yields `ERR_INVALID_STATE`.
6. Business-safety rules — hazmat hub certification (`ERR_HAZMAT_HUB_NOT_CERTIFIED`), hazmat driver endorsement (`ERR_DRIVER_NO_HAZMAT_ENDORSEMENT`), driver-release authorization (`ERR_DRIVER_RELEASE_NOT_AUTHORIZED`), and signature presence (`ERR_SIGNATURE_MISSING`), evaluated in that order.
7. Business-referential rules — postal-prefix service area (`ERR_HUB_NOT_SERVICING_POSTAL`).
8. Business-temporal rules — delivery within the parcel's time window (`ERR_OUTSIDE_TIME_WINDOW`) and appointment-window feasibility (`ERR_APPOINTMENT_WINDOW_INVALID`).
9. Business-constraint rules — time-window infeasibility on stop assignment (`ERR_TIME_WINDOW_INFEASIBLE`), parcel uniqueness on a route (`ERR_PARCEL_ALREADY_ON_ROUTE`), route-must-be-planned (`ERR_ROUTE_NOT_PLANNED`), per-parcel redelivery limit (`ERR_REDELIVERY_LIMIT_EXCEEDED`), per-customer redelivery cap (`ERR_CUSTOMER_REDELIVERY_CAP_REACHED`).
10. Business-fiscal range checks — parcel weight in range (`ERR_PARCEL_WEIGHT_OUT_OF_RANGE`) and declared value in range (`ERR_DECLARED_VALUE_OUT_OF_RANGE`).
11. Optimistic concurrency control (`ERR_VERSION_CONFLICT`) on every endpoint that accepts a `version` in the request body.
12. The clock-advance forward-only rule (`ERR_CLOCK_BACKWARDS`) on the test-only clock endpoint.

When a single request is in violation of more than one rule, the lower-numbered (higher-priority) rule's error_id is the one returned.

### 2.10. Optimistic Concurrency Control

Every mutation endpoint that targets an existing resource by path id accepts an optional `version` field in the request body. When `version` is supplied, the server compares it to the current `version` of the resource and, on mismatch, rejects the request with `ERR_VERSION_CONFLICT` without applying any side effect. When `version` is omitted, the server processes the mutation unconditionally — there is no implicit OCC check.

Because cascading side effects (§2.5) increment `version` on every affected resource, a client holding a stale `version` for a parcel may find a subsequent edit rejected even though they have not themselves touched the parcel, because a route-level cascade has advanced the parcel in the interim. This is the intended behavior.

### 2.11. The Logical Clock

Time-window enforcement, redelivery rolling-window aggregation, and appointment feasibility all consult a single logical clock exposed on the synthetic `Clock` entity. The `now` field on `Clock` is the server's authoritative current instant; it is not derived from wall-clock time. A test-only capability advances the clock to a supplied target instant carried in the request body as `to_iso8601`. The clock is forward-only: advancing to an instant earlier than the current `now` is rejected with `ERR_CLOCK_BACKWARDS`. Any role may advance the clock, since it is purely a test instrument.

## 3. Business Logic & Workflows

### 3.1. Customers, Addresses, and the Driver-Release Standing Instruction

A `Dispatcher` creates customers by supplying a contact `email` (unique and in RFC 5322 form), a `full_name` for label printing, a `phone` number in E.164 format used for ETA and appointment notifications, and an optional `driver_release_authorized` flag — defaulting to `false` — which represents the customer's standing consent to leave parcels at their default address without a signature. A new customer's `default_address_id` is unset until at least one address has been added.

Addresses are owned by a customer and identified through the `customer_id` foreign key. Each address carries a `line1` street string, a `city` string, a five-digit `postal_code` that acts as the routing key for service-area decisions, a geocoded `latitude` between -90.0 and 90.0 inclusive, a geocoded `longitude` between -180.0 and 180.0 inclusive, and a `residential` flag (defaulting to `true`) that influences the residential surcharge described in §3.7 and informs the default expectations around signature and driver-release. Once an address exists, the customer's `default_address_id` may be updated to point at it. Both the customer-profile update and the toggle of `driver_release_authorized` flow through the same controlled customer update path, which accepts `full_name`, `phone`, `driver_release_authorized`, `default_address_id`, and an optional `version` for concurrency control.

Customers may also file appointment requests against parcels they own (see §3.5). The aggregated counter `redelivery_attempts_used_30d` on the customer record is recomputed on demand when the customer record is read and after any `EXCEPTION → SORTED` reattempt transition; it counts the customer's failed-attempt activity over a strictly rolling 30-day window as described in §3.5.

### 3.2. Transit Centers, Drivers, and the Hub Network

Each `TransitCenter` is registered by a `Dispatcher` with a three-letter `code` consisting of exactly three uppercase letters (such as `LAX` or `JFK`, unique across the network), a `serviced_postal_prefixes` array enumerating the three-digit postal prefixes that center sorts for, and an optional `hazmat_certified` flag — defaulting to `false` — that gates the hazmat workflows described in §2.6. The `parcels_on_belt` counter is system-maintained and reflects the number of parcels currently in the `IN_TRANSIT_HUB` state attributed to this center; it is initialized to zero, incremented when a parcel transitions from `INDUCTED` to `IN_TRANSIT_HUB`, and decremented when a parcel transitions from `IN_TRANSIT_HUB` to `SORTED`. Each such change refreshes the center's `updated_at` and increments its `version`.

Drivers are created by a `Dispatcher` with a unique `badge_id`, a `home_center_id` foreign key naming the center where the driver checks in, and an optional `hazmat_endorsement` flag (default `false`). A driver's `status` field is system-computed and traverses a four-state cycle: starting `OFF_DUTY`, transitioning to `ON_DUTY` when the driver checks in (an operation the driver may perform on their own record or a `Dispatcher` may perform on their behalf), then to `ON_ROUTE` when the system dispatches a route assigned to the driver, then to `RETURNED` when the driver closes that route, and finally back to `OFF_DUTY` when the driver checks out. The two endpoints the driver directly controls — checking in and checking out — carry no body parameters; the intervening transitions are server-driven side effects of route dispatch and route closure described in §3.4.

### 3.3. Parcel Induction and Hub Sorting

A parcel enters the system through induction by either a `Dispatcher` or a `SortingHubOperator`. The induction payload carries a `customer_id`, an optional `destination_address_id` (which, when omitted, defaults to the customer's `default_address_id`), an `origin_center_id` naming the inducting hub, a `weight_kg` declared weight, a `declared_value` in USD, an optional `signature_required` flag (default `false`), an optional `hazmat_class` (default `NONE`), and the two ends of the customer-acceptable delivery interval, `time_window_start` and `time_window_end`, both UTC instants.

The server mints a 12-character alphanumeric `tracking_number` composed of uppercase letters and digits, places the parcel into the initial state `INDUCTED`, initializes `redelivery_attempts` to zero, sets `last_attempt_outcome` to `NONE`, leaves `final_fee` unset, and runs the forward-looking fee quote described in §3.7 to populate `quoted_fee`. The declared `weight_kg` is rejected with `ERR_PARCEL_WEIGHT_OUT_OF_RANGE` if it is not strictly greater than zero and at most 70.0 kilograms (70.0 inclusive is accepted; 70.01 is rejected); the `declared_value` is rejected with `ERR_DECLARED_VALUE_OUT_OF_RANGE` if it is below zero or above 50000.00.

While the parcel is still in `INDUCTED` or `IN_TRANSIT_HUB`, a `Dispatcher` or `SortingHubOperator` may update `weight_kg`, `declared_value`, `signature_required`, `hazmat_class`, `destination_address_id`, `time_window_start`, or `time_window_end`, supplying an optional `version` for the concurrency check; any such update reruns the forward-looking fee quote and refreshes `quoted_fee`. Once the parcel has advanced past `IN_TRANSIT_HUB`, this edit path is no longer admissible and the request is rejected with `ERR_INVALID_STATE`.

Induction-to-hub is the transition that moves a parcel from `INDUCTED` to `IN_TRANSIT_HUB`, performed by a `SortingHubOperator`. It is gated by two preconditions: the declared `weight_kg` must be at most 70.0 kilograms, and, if `hazmat_class` is anything other than `NONE`, the origin center's `hazmat_certified` flag must be `true`. A hazmat-class parcel inducted to a non-certified hub is rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED`. On success, the origin center's `parcels_on_belt` counter is incremented and the parcel's `quoted_fee` is recomputed.

Sorting moves the parcel from `IN_TRANSIT_HUB` to `SORTED`. This transition has two preconditions: first, the first three digits of the destination address's `postal_code` must appear in the origin center's `serviced_postal_prefixes` list (otherwise the operation is rejected with `ERR_HUB_NOT_SERVICING_POSTAL`); second, if the parcel is regulated, the origin center must still be `hazmat_certified` (rejected with `ERR_HAZMAT_HUB_NOT_CERTIFIED` if not). On success, `parcels_on_belt` at the origin center is decremented.

### 3.4. Route Planning, Stop Loading, Dispatch, and Closure

A `Dispatcher` creates a `Route` by naming the originating `center_id`, the assigned `driver_id`, and a `planned_date` expressed as a calendar date string `YYYY-MM-DD` in the center's local time zone. A new route starts in `PLANNED` with `total_distance_km` of 0.00, `stop_count` of 0, and `hazmat_present` of `false`. From `PLANNED`, three terminal arcs are possible: the route may be cancelled, advanced to `DISPATCHED` (and then immediately auto-advanced by the system to `IN_PROGRESS`), or — once dispatched — closed.

Stops are loaded onto a planned route by a `Dispatcher`, who supplies only the `parcel_id` of the parcel to be loaded. The action drives a `SORTED → ON_VEHICLE` transition on the parcel and, simultaneously, the creation of a `RouteStop` row whose `route_id` is the parent route, whose `parcel_id` is the loaded parcel, whose `sequence` is assigned by the optimizer as a 1-indexed delivery order unique per `route_id`, and whose `planned_arrival` and `planned_departure` are computed by the time-assignment rule of §3.7. The stop is created in the `PLANNED` status. The preconditions are exact: the parent route must still be in `PLANNED` status (a non-planned route's stop-add is rejected with `ERR_ROUTE_NOT_PLANNED`), the parcel must currently be in `SORTED`, and, if `hazmat_class` is anything other than `NONE`, the assigned driver's `hazmat_endorsement` must be `true` (otherwise `ERR_DRIVER_NO_HAZMAT_ENDORSEMENT`). A parcel that is already linked to a stop while in `ON_VEHICLE` cannot be loaded a second time; the second loader receives `ERR_PARCEL_ALREADY_ON_ROUTE`. Loading triggers three derived recomputations on the parent route: `stop_count` is incremented, `hazmat_present` is set to `true` if the loaded parcel is regulated, and `total_distance_km` is recomputed via the route-distance rule of §3.7.

Stop removal is the symmetric operation: a `Dispatcher` may delete a stop while the parent route is still in `PLANNED`. Removal reverts the underlying parcel from `ON_VEHICLE` back to `SORTED`, recomputes `total_distance_km` and `stop_count` on the route, and re-evaluates `hazmat_present` — setting it back to `false` if no remaining stop carries a regulated parcel. Removal on a non-planned route is rejected with `ERR_ROUTE_NOT_PLANNED`. A successful stop removal carries no response body.

Cancelling a planned route is performed by a `Dispatcher` and is admissible only while the route is in `PLANNED`; an attempt to cancel a route that has already been dispatched is rejected with `ERR_ROUTE_NOT_PLANNED`. On cancellation, every parcel currently in `ON_VEHICLE` on the route reverts to `SORTED`, every `RouteStop` row attached to the route is deleted as a cascade, and `hazmat_present` is recomputed to `false`. The route lands in the terminal `CANCELLED` state. Two simultaneous attempts to cancel-and-add-stop on the same planned route serialize on `Route.status`: the first writer wins, and whichever loses (whether the cancel or the add) observes a state that no longer admits its operation and receives `ERR_ROUTE_NOT_PLANNED`.

Dispatch advances the route from `PLANNED` through `DISPATCHED` to `IN_PROGRESS` atomically — clients never observe an intermediate `DISPATCHED` state in steady-state reads because the auto-transition to `IN_PROGRESS` is part of the same operation. Dispatch is performed by a `Dispatcher` and requires three preconditions: the route's `stop_count` must be at least 1, the assigned driver's `status` must currently be `ON_DUTY`, and, if the route's `hazmat_present` is `true`, the assigned driver's `hazmat_endorsement` must also be `true` (otherwise `ERR_DRIVER_NO_HAZMAT_ENDORSEMENT`). Dispatch cascades broadly: the driver's `status` advances to `ON_ROUTE`, and every parcel on the route currently in `ON_VEHICLE` advances to `OUT_FOR_DELIVERY`. Each cascaded mutation refreshes that resource's `updated_at` and increments its `version`.

Closure is the terminal arc of a dispatched route, initiated by the assigned `Driver`. It is admissible only when every `RouteStop` on the route has reached one of `COMPLETED`, `FAILED`, or `SKIPPED`; if any stop is still in `PLANNED` or `ARRIVED`, the close is rejected with `ERR_INVALID_STATE`. On close, the route lands in the terminal `CLOSED` state, the driver's `status` advances to `RETURNED`, and any parcel still in `OUT_FOR_DELIVERY` at the moment of closure is forced into the `EXCEPTION` state and treated as if a `NO_ONE_HOME` outcome had been recorded — this also increments the parcel's `redelivery_attempts`. Two concurrent close attempts on the same route serialize on `Route.status`; the second writer observes a route already in `CLOSED` and receives `ERR_INVALID_STATE`.

### 3.5. Delivery Attempts, Reattempts, and Returns

When a driver arrives at a stop, the resulting attempt is recorded as a `DeliveryAttempt` row referencing the `route_stop_id` and an `outcome` drawn from the enumeration `DELIVERED_SIGNED`, `DRIVER_RELEASED`, `NO_ONE_HOME`, `REFUSED`, `ADDRESS_INVALID`, or `HAZMAT_BLOCKED`. The attempt row also stamps an `attempted_at` instant (set by the server from the logical `Clock.now`), records the acting `driver_id`, and — depending on outcome — carries either a `signature_blob_ref` (when `outcome` is `DELIVERED_SIGNED`) or a `release_location` free-text drop-spot (when `outcome` is `DRIVER_RELEASED`). Across the two success outcomes, signature submission without `signature_blob_ref` is rejected with `ERR_SIGNATURE_MISSING`, and any driver-release that violates the three gates of §2.7 is rejected with `ERR_DRIVER_RELEASE_NOT_AUTHORIZED`.

The attempt drives one of two parcel transitions out of `OUT_FOR_DELIVERY`. If `outcome` is `DELIVERED_SIGNED` or `DRIVER_RELEASED`, the parcel advances to the terminal `DELIVERED` state: the corresponding `RouteStop.status` advances to `COMPLETED`, the parcel's `last_attempt_outcome` is set to the supplied outcome, and the system runs the chronological final-fee calculation of §3.7 to populate `final_fee`. The success transition has one further precondition above and beyond the gates already discussed: `Clock.now` must lie within the parcel's delivery window — that is, `Clock.now` must be at or after `time_window_start` and at or before `time_window_end`, with both ends inclusive. An attempt outside that interval is rejected with `ERR_OUTSIDE_TIME_WINDOW`.

If `outcome` is one of the failure outcomes `NO_ONE_HOME`, `REFUSED`, `ADDRESS_INVALID`, or `HAZMAT_BLOCKED`, the parcel advances from `OUT_FOR_DELIVERY` to `EXCEPTION`. The corresponding `RouteStop.status` advances to `FAILED`, the parcel's `last_attempt_outcome` is set to the failure value, and `redelivery_attempts` is incremented by one. Two concurrent operations on a parcel in `OUT_FOR_DELIVERY` — for example a driver recording `DELIVERED_SIGNED` while a customer's appointment-change is being accepted — serialize on `Parcel.status`; whichever loses observes a parcel no longer in `OUT_FOR_DELIVERY` and is rejected with `ERR_INVALID_STATE`.

From `EXCEPTION` two recovery arcs are available, both initiated by a `Dispatcher`. The reattempt arc transitions the parcel back to `SORTED` and re-enters it into the origin center's queue. Three preconditions guard the reattempt: the parcel's `redelivery_attempts` must be strictly less than three, the parcel's owning customer's `redelivery_attempts_used_30d` must be strictly less than ten at the moment of reattempt, and the parcel's `last_attempt_outcome` must not be `ADDRESS_INVALID` (an address-invalid outcome blocks any further reattempt because the destination itself is unreachable). The corresponding error codes are `ERR_REDELIVERY_LIMIT_EXCEEDED`, `ERR_CUSTOMER_REDELIVERY_CAP_REACHED`, and `ERR_INVALID_STATE` respectively. As a side effect of the reattempt, any `Appointment` for the same parcel that is still in `PENDING` is auto-superseded to `SUPERSEDED`. The rolling 30-day counter on the customer is itself an aggregation: it counts the number of `DeliveryAttempt` rows belonging to parcels owned by this customer whose `outcome` is either `NO_ONE_HOME` or `REFUSED` and whose `attempted_at` falls in the half-open interval beginning at the instant 30 days before `Clock.now` (inclusive of that lower bound) and ending at `Clock.now`. The counter is read at appointment-accept time and at reattempt time, and is refreshed on every `EXCEPTION → SORTED` transition.

The return arc transitions the parcel from `EXCEPTION` to the terminal `RETURNED_TO_SENDER` state. It is admissible when the parcel has exhausted its reattempts (`redelivery_attempts` is at or above three) or when the most recent attempt outcome was `ADDRESS_INVALID`. On return, the system runs the chronological final-fee calculation, this time including the return-to-sender surcharge described in §3.7.

A customer who wants to renegotiate the window files an `Appointment` against a parcel they own. The appointment payload carries the target `parcel_id`, a `requested_window_start`, and a `requested_window_end`. The appointment begins in `PENDING` and may end up in any of three terminal states: `ACCEPTED`, `REJECTED`, or `SUPERSEDED`. A `Dispatcher` accepts an appointment if and only if the parent parcel is currently in one of `SORTED`, `ON_VEHICLE`, `OUT_FOR_DELIVERY`, or `EXCEPTION` (an already-`DELIVERED` or `RETURNED_TO_SENDER` parcel admits no new appointment) and the requested window is feasible: `requested_window_start` must be strictly earlier than `requested_window_end`, and the interval between them must be at least two hours long. A window that violates either feasibility rule is rejected with `ERR_APPOINTMENT_WINDOW_INVALID`. A window that cannot be honored because the parcel is already terminalized or already inside a closed route's date is rejected — by the dispatcher, via the `REJECTED` arc; on rejection the appointment's `fee_charged` remains 0.00. Filing a brand-new appointment for a parcel that already has a `PENDING` appointment auto-supersedes the prior one to `SUPERSEDED`.

Acceptance has substantive side effects. The parcel's `time_window_start` and `time_window_end` are overwritten with the new window. The appointment's `fee_charged` is set to the appointment-change fee, which contributes to the parcel's final fee via the chronological fee rule of §3.7. If the parcel is on a route that is still in `PLANNED`, the route's `planned_arrival_assignment` is rerun and the affected stop's `planned_arrival` is recomputed; in some cases the optimizer will re-sequence stops, in which case `sequence` values on neighboring stops are reissued.

### 3.6. Concurrency Serialization at a Glance

Four high-leverage races are explicitly serialized by the system, and each loser receives a specific error_id rather than a generic conflict:

- Two simultaneous attempts to load the same parcel onto two different routes serialize on the uniqueness of `RouteStop.parcel_id` while the parcel is in `ON_VEHICLE`. Exactly one loader wins; the loser receives `ERR_PARCEL_ALREADY_ON_ROUTE`.
- A driver recording `DELIVERED_SIGNED` while a dispatcher is accepting an appointment-change for the same parcel serialize on `Parcel.status`. Exactly one operation succeeds; the loser observes a parcel no longer in the state it expected and receives `ERR_INVALID_STATE`.
- Two drivers trying to close the same route serialize on `Route.status`. The first writer wins; the second writer observes a route already in `CLOSED` and receives `ERR_INVALID_STATE`.
- A cancel-route and an add-stop arriving simultaneously on a planned route serialize on `Route.status`. The first writer wins. If the cancel wins, the add-stop sees a non-planned route and receives `ERR_ROUTE_NOT_PLANNED`. If the add-stop wins, the cancel still completes because cancelling a planned route is admissible regardless of `stop_count`.

### 3.7. Pricing, Distance, and Time-Window Assignment

The system performs four named calculations that, taken together, define the economics and the geometry of every shipment.

**Forward-looking shipping-fee quote.** A quote is computed every time a parcel is inducted into the system, every time it transitions from `INDUCTED` to `IN_TRANSIT_HUB`, and every time the controlled update path mutates `weight_kg`, `destination_address_id`, `hazmat_class`, or `signature_required` while the parcel is still in `INDUCTED` or `IN_TRANSIT_HUB`. The result is written to `quoted_fee`. The quote is forward-looking: it presumes a single successful first-attempt delivery, zero redelivery surcharges, and no appointment changes.

The quote is the sum of six components, each carried at full precision and rounded once, half-up, to two decimal places at the very end:

- The base fee is a flat 5.00.
- The weight fee is computed by first taking the parcel's `weight_kg` and subtracting the free-weight allowance of 1.0 kilogram, taking the result as zero if it would otherwise be negative; the remaining kilograms are then rounded up to the next whole kilogram (ceiling); the resulting integer is multiplied by the per-kilogram rate of 0.75.
- The distance fee is computed by taking the great-circle (haversine) distance, in kilometers, from the origin transit center's stored coordinates to the destination address's stored `latitude` and `longitude`, using an Earth radius of 6371.0 kilometers; that distance is divided by the bucket width of 25.0 kilometers; the quotient is rounded up to the next whole bucket (ceiling); the resulting integer is multiplied by the per-bucket rate of 1.50.
- The hazmat surcharge of 12.00 is added if and only if the parcel's `hazmat_class` is anything other than `NONE`.
- The signature surcharge of 2.50 is added if and only if `signature_required` is `true`.
- The residential surcharge of 1.00 is added if and only if the destination address's `residential` flag is `true`.

The six components are summed in full precision, then the resulting total is rounded half-up to two decimal places to produce `quoted_fee`. The hazmat variant of the quote (when `hazmat_class` is not `NONE`) is the standard quote plus the hazmat surcharge, and downstream sorting of the parcel is gated by `hazmat_certified` on the relevant hub. The signature variant of the quote (when `signature_required` is `true`) is the standard quote plus the signature surcharge, and disables `DRIVER_RELEASED` as a valid attempt outcome for that parcel.

**Chronological final-fee calculation.** When the parcel terminalizes — either by reaching `DELIVERED` or by reaching `RETURNED_TO_SENDER` — the system computes the definitive `final_fee` by walking the parcel's full history. The accumulator begins at `quoted_fee`. The system then iterates the parcel's `DeliveryAttempt` rows in ascending `attempted_at` order and, for each row, applies one of the following: if the attempt's `outcome` is `NO_ONE_HOME` or `REFUSED`, a reattempt fee of 3.00 is added to the accumulator; if the `outcome` is `ADDRESS_INVALID`, an address-correction fee of 8.00 is added to the accumulator and the chronological walk stops immediately — no further attempts are processed even if later rows exist. After the attempts have been processed, the system counts the number of `Appointment` rows for this parcel whose `status` is `ACCEPTED` and adds the appointment-change fee of 4.50 to the accumulator once per accepted appointment. Finally, if the parcel's terminal `status` is `RETURNED_TO_SENDER`, a return-to-sender surcharge of 7.00 is added to the accumulator. The accumulator is rounded half-up to two decimal places to produce `final_fee`.

The order matters. A redelivery surcharge that accrued chronologically before an appointment change must remain in the running total even after the appointment is accepted; a return-to-sender surcharge is added last, after every redelivery and every appointment change has been counted. Reordering produces drift in the case where a customer files an appointment after a failed attempt and the parcel is still ultimately returned. The success-path variant of the final fee (when the terminal state is `DELIVERED`) excludes the return-to-sender surcharge; the return-path variant (when the terminal state is `RETURNED_TO_SENDER`) includes it and is the only path on which the chronological iteration may be cut short by an `ADDRESS_INVALID` attempt.

**Route-total-distance calculation.** Whenever a `RouteStop` is added or removed, or the sequence is renumbered, the system recomputes `total_distance_km` for the parent route. Starting from the origin transit center's stored coordinates, the system iterates the stops in ascending `sequence` order and, for each stop, computes the haversine distance (Earth radius 6371.0 kilometers) from the previous point to the destination address of the current stop and adds that leg to a running total. The previous point is then updated to the current stop's destination coordinates. No return-to-hub leg is included in the total. The accumulated total is rounded half-up to two decimal places and written to `total_distance_km`.

**Time-assignment for stops.** Whenever a stop is added or the route is re-sequenced, the system also assigns `planned_arrival` and `planned_departure` to every stop. A cursor starts at the route's `planned_date` at 08:00 local time of the origin center. The system iterates the stops in ascending `sequence` order. For each stop, the system computes the leg distance in kilometers from the previous point (origin center for the first stop, prior stop's destination coordinates thereafter) and the travel time in minutes by dividing that leg distance by an average vehicle speed of 40.0 kilometers per hour, multiplying by 60, and rounding the result up to the next whole minute (ceiling). The cursor is advanced by that travel time. If the cursor is now strictly earlier than the parcel's `time_window_start`, the cursor is bumped forward to `time_window_start` to model waiting at the door. If the cursor is now strictly later than the parcel's `time_window_end`, the assignment fails immediately and the stop-add is rejected with `ERR_TIME_WINDOW_INFEASIBLE`. Otherwise, the stop's `planned_arrival` is set to the current cursor (truncated to the start of the minute), the cursor is advanced by the per-stop service time of 6 minutes, and the resulting cursor becomes the stop's `planned_departure`. The system then proceeds to the next stop in sequence.

**Customer rolling-30-day count.** The customer counter `redelivery_attempts_used_30d` is an aggregation over the customer's parcels: the system counts the number of `DeliveryAttempt` rows whose `outcome` is either `NO_ONE_HOME` or `REFUSED` and whose `attempted_at` is greater than or equal to the instant exactly 30 days before `Clock.now`, and at most equal to `Clock.now`. The window is half-open at the lower bound — an attempt whose `attempted_at` falls exactly 30 days ago counts; the bound at the upper end is inclusive. The count is an integer; it is recomputed on customer reads, consulted when an appointment is accepted, and consulted again at reattempt time.

## 4. Endpoint Definitions

Operations that create a brand-new stand-alone resource (a customer, a parcel, an address, a transit center, a driver, a route, a route stop, an appointment, or a delivery attempt) return `201 Created`. Operations that modify or transition an existing resource — including profile updates, state transitions such as induction, sorting, dispatch, close, cancel, reattempt, return-to-sender, appointment accept/reject, driver check-in/out, and the test-only clock advance — return `200 OK`. A successful stop-removal returns `204 No Content`. Errors follow the priority order of §2.9 and use the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/customers` | Create a customer record | Dispatcher |
| GET    | `/customers/{id}` | Read a customer (includes the rolling 30-day redelivery counter) | Customer, Dispatcher |
| PATCH  | `/customers/{id}` | Update customer profile or toggle driver-release authorization | Customer, Dispatcher |
| POST   | `/customers/{id}/addresses` | Add a delivery address to a customer | Customer, Dispatcher |
| POST   | `/transit-centers` | Register a transit center | Dispatcher |
| GET    | `/transit-centers/{id}` | Read a transit center including the belt counter | Dispatcher, SortingHubOperator |
| POST   | `/drivers` | Create a driver | Dispatcher |
| POST   | `/drivers/{id}/check-in` | Driver goes on duty | Driver, Dispatcher |
| POST   | `/drivers/{id}/check-out` | Driver returns to off duty | Driver, Dispatcher |
| POST   | `/parcels` | Induct a parcel into the network | Dispatcher, SortingHubOperator |
| GET    | `/parcels/{id}` | Read parcel by id | Customer, Dispatcher, Driver, SortingHubOperator |
| GET    | `/parcels` | List parcels with filters | Dispatcher, SortingHubOperator |
| PATCH  | `/parcels/{id}` | Update parcel fields while still pre-sort | Dispatcher, SortingHubOperator |
| POST   | `/parcels/{id}/induct-to-hub` | Transition parcel into the hub belt | SortingHubOperator |
| POST   | `/parcels/{id}/sort` | Transition parcel to sorted | SortingHubOperator |
| POST   | `/parcels/{id}/attempts` | Record a delivery attempt | Driver |
| POST   | `/parcels/{id}/reattempt` | Re-queue an exception parcel | Dispatcher |
| POST   | `/parcels/{id}/return-to-sender` | Terminalize an exception parcel as returned | Dispatcher |
| POST   | `/routes` | Create a route | Dispatcher |
| GET    | `/routes/{id}` | Read a route including computed distance, stop count, and hazmat flag | Dispatcher, Driver |
| POST   | `/routes/{route_id}/stops` | Append a parcel to a route as a stop | Dispatcher |
| DELETE | `/routes/{route_id}/stops/{stop_id}` | Remove a stop from a planned route | Dispatcher |
| POST   | `/routes/{id}/dispatch` | Dispatch the route | Dispatcher |
| POST   | `/routes/{id}/close` | Driver closes the route at end of shift | Driver |
| POST   | `/routes/{id}/cancel` | Cancel a planned route | Dispatcher |
| POST   | `/appointments` | File a new appointment for a parcel | Customer, Dispatcher |
| POST   | `/appointments/{id}/accept` | Dispatcher accepts an appointment | Dispatcher |
| POST   | `/appointments/{id}/reject` | Dispatcher rejects an appointment | Dispatcher |
| POST   | `/_clock/advance` | Advance the logical clock to a supplied instant | Dispatcher, Driver, Customer, SortingHubOperator, ComplianceOfficer |

Filters available on the parcel list endpoint are passed as query parameters: `status`, `customer_id`, `origin_center_id`, `hazmat_class`, plus the pagination parameters `limit` and `offset`. The clock-advance request carries a single `to_iso8601` field in its body. The optional `version` parameter described in §2.10 is accepted on every endpoint that mutates an existing resource by path id.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_HAZMAT_HUB_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_DRIVER_NO_HAZMAT_ENDORSEMENT` | 422 Unprocessable Entity |
| `ERR_DRIVER_RELEASE_NOT_AUTHORIZED` | 422 Unprocessable Entity |
| `ERR_SIGNATURE_MISSING` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_TIME_WINDOW_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_PARCEL_ALREADY_ON_ROUTE` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNED` | 409 Conflict |
| `ERR_HUB_NOT_SERVICING_POSTAL` | 422 Unprocessable Entity |
| `ERR_REDELIVERY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_REDELIVERY_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_PARCEL_WEIGHT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DECLARED_VALUE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CLOCK_BACKWARDS` | 422 Unprocessable Entity |
