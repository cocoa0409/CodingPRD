# Roll-Off Dumpster Rental API — Product Requirements Document

## 1. Introduction

A roll-off dumpster operator runs a finite fleet of steel containers between a yard and contractor job sites. The business has four intertwined pressures that this API exists to reconcile. First, containers are scarce capital assets: a single physical can cycles through many jobs over its life, and two dispatchers competing for the same idle can in the yard must never both win. Second, the money on each job is only knowable in two stages — a provisional figure quoted from the driver's eyeball estimate at pickup, and a final figure read off the scale-house weigh ticket — and the books have to reflect both without drift. Third, every truck run is a sequenced route with a hard stop count, and a container's journey (delivered, optionally swapped, finally picked up) has to stay in lockstep with the logistics of who is driving where on which day. Fourth, the yard extends credit to contractors, places cans on public streets under municipal permits, and charges punitively for prohibited material found in a load.

This document specifies the REST API that coordinates container inventory, delivery/swap/pickup scheduling, rental-period and tonnage billing, contamination penalties, street-placement permits, and contractor credit accounts. The central modeling decision is that a rental order advances along **two independent status axes at once** — a logistics axis tracking the physical movement of the can, and a billing axis tracking how far the money has settled — and the reader should keep these two axes mentally separate throughout. Where the two axes meet is the pickup event, which simultaneously closes out the logistics journey and runs the dual-stage billing cascade in a single call.

The intended audience is the engineering team building the service. Sections 2 and 3 carry the binding business rules; sections 4 and 5 summarize the HTTP surface and the error vocabulary. The narrative deliberately spreads the rules of a single workflow across the subsection that owns each concern, so the complete behavior of, say, a pickup must be assembled from the logistics, billing, scale, and ledger subsections together.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before any other processing. If the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly six roles, spelled exactly as follows: `Contractor`, `Dispatcher`, `YardAdmin`, `ScaleOperator`, `PermitOfficer`, and `BillingClerk`.

The `Contractor` role is **entity-backed**: when `X-User-Role` is `Contractor`, the value of `X-User-ID` is the `id` of the acting `ContractorAccount`. Ownership checks compare the `account_id` of any resource the contractor touches against this `X-User-ID`. A contractor may read and write only its own rental orders, the service stops and invoices belonging to those orders, and its own permits and weigh-ticket views; an attempt to act on a `RentalOrder`, `ServiceStop`, or `Invoice` the contractor does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). For a `ServiceStop` or an `Invoice`, ownership is resolved through the owning order's `account_id`.

The other five roles are **opaque operator identities**: when `X-User-Role` is `Dispatcher`, `YardAdmin`, `ScaleOperator`, `PermitOfficer`, or `BillingClerk`, the value of `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; these roles are authorized by role membership alone, not by resource ownership. In broad strokes: `Dispatcher` runs fleet and route operations (committing containers, sequencing and dispatching stops, completing stops, returning cans to the yard); `YardAdmin` manages master data (container types, physical containers, contractor accounts, and the business clock); `ScaleOperator` records weigh tickets; `PermitOfficer` approves, denies, and expires street permits; and `BillingClerk` pays and voids invoices and may suspend or reinstate accounts. The precise authorized-role set for each endpoint is listed in Section 4.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1, and a maximum of 100; the `offset` defaults to 0 and has a minimum of 0. List results are ordered by `created_at` ascending — that is, oldest record first; records sharing the same `created_at` timestamp are ordered by ascending `id` to keep the ordering deterministic. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the count of all records matching the filter (ignoring pagination) and `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is identified by a server-minted `id`, formatted as a UUID with no type prefix; clients never supply ids. Most resources also carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation that changes the resource. `created_at` is fixed at creation; `updated_at` is refreshed on every mutation.

Two entities are exceptions. The `WeighTicket` is an append-only scale event: once recorded it is immutable, so it carries only `id` and `created_at` — it has neither `updated_at` nor `version`. The `ClockState` likewise carries only `id` and `created_at`; it has no `updated_at` and no `version`. Every other entity — `ContainerType`, `ContractorAccount`, `Container`, `Route`, `RentalOrder`, `ServiceStop`, `StreetPermit`, and `Invoice` — carries the full `created_at` / `updated_at` / `version` triple.

### 2.5. Optimistic Concurrency on Shared Fleet and Route State

Two operations contend over state that several dispatchers may read and then try to mutate, and both are guarded by optimistic concurrency control rather than by any notion of request timing.

The first is committing a container to a delivery. A delivery dispatch must carry `expected_container_version`, the `version` of the target `Container` as the dispatcher last observed it. If that value does not equal the container's current `version` — because the same can was committed to a different order, retired, or restored since the dispatcher read it — the request is rejected with `ERR_STALE_CONTAINER_VERSION` (HTTP 412). The dispatcher carrying the stale view is the one turned away; the can it tried to grab was legitimately taken by an earlier sanctioned dispatch. The field is mandatory on this operation.

The second is appending a service stop to a route. Adding a stop must carry `expected_route_version`, the `version` of the target `Route` as last observed. If that value does not equal the route's current `version` — because another stop was appended to or cancelled from the route since, changing its `stop_count` and the next free sequence slot — the append is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412). This guarantees two appends can never both claim the same `sequence` position. The field is mandatory on this operation.

No other endpoint takes a version field; only these two carry an `expected_*_version` input.

### 2.6. Monetary Precision and the Cents Convention

All money in the system is stored and computed as whole integer cents — `base_rate_cents`, `overage_day_cents`, `overage_rate_cents_per_lb`, `credit_limit_cents`, `permit_fee_cents`, and every computed charge field. There is no sub-cent fractional arithmetic anywhere; every calculation in Section 3 yields an integer number of cents, and weights are likewise whole integer pounds with no rounding. Because all inputs and rates are integers and all operations are integer addition, subtraction, and multiplication, results are exact integers; no rounding step is applied.

### 2.7. Cascading Mutations and Version Propagation

Several operations mutate more than one entity in a single call. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` increments by 1 — and this holds for **every** entity touched in a cascade, not only the entity named in the request path. The pickup-completion cascade, described in detail in Section 3, is the largest example: a single stop completion advances the stop, the order on both its axes, the container, the account ledger, and issues an invoice, with each affected entity's version bumping independently. Implementers must treat each entity's `version` as its own counter; there is no global version.

### 2.8. Nested Resource Access and Existence Checks

Several read endpoints are nested under a parent — an account's orders and invoices, an order's service stops, weigh tickets, street permits, and invoice, and a route's stops. For any nested path, the parent id is validated first, left to right: if the parent does not exist, the request fails with that resource's not-found error (for example `ERR_ACCOUNT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, or `ERR_ROUTE_NOT_FOUND`) before the child collection is considered. More generally, every path or body id is checked for existence and, when missing, yields the resource-specific not-found error at HTTP 404: `ERR_CONTAINER_TYPE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_CONTAINER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_WEIGH_TICKET_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`.

### 2.9. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order, and the first failure is the one reported. Authentication comes first: presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_AUTH_HEADERS`). Then role authorization for the operation (`ERR_FORBIDDEN_ROLE`). Then existence of every referenced resource id, checked left to right (the not-found family above). Then, for a `Contractor` acting on a resource, ownership (`ERR_NOT_RESOURCE_OWNER`). Then the target resource's state suitability for the requested transition (the state-conflict errors at HTTP 409 enumerated per workflow in Section 3). Then the operation-specific business checks: on a delivery dispatch, container-type match (`ERR_CONTAINER_TYPE_MISMATCH`) and then the permit requirement (`ERR_PERMIT_NOT_APPROVED`); on completing a swap or pickup, the weigh-ticket requirement (`ERR_WEIGH_TICKET_REQUIRED`); on a route append, capacity (`ERR_ROUTE_AT_CAPACITY`); on permit approval, the window-passed check (`ERR_PERMIT_WINDOW_PASSED`) and then the window-overlap check (`ERR_PERMIT_WINDOW_OVERLAP`). Date-range well-formedness on creation (`ERR_INVALID_DATE_RANGE`) and the credit gate on order booking (`ERR_CREDIT_LIMIT_EXCEEDED`) sit with their respective workflows. General request well-formedness — required fields present, enum values legal, integers non-negative — is reported as `ERR_INVALID_REQUEST` (HTTP 422), and uniqueness collisions as `ERR_DUPLICATE_RESOURCE` (HTTP 409).

### 2.10. Uniqueness Constraints

Three uniqueness rules are enforced at creation time, each surfacing as `ERR_DUPLICATE_RESOURCE` (HTTP 409). A container's `asset_tag` must be unique across all containers. A route's `truck_code` must be unique among routes sharing the same `service_date`. A container type's `size_code` must be unique across all currently active container types (a retired type's code may be reused).

## 3. Business Logic & Workflows

### 3.1. Yard Master Data: Container Types and Physical Cans

A `YardAdmin` seeds the catalogue before any rental can happen. A **container type** captures both a size and a pricing profile. Its `size_code` is one of `YD10`, `YD20`, `YD30`, or `YD40`. The pricing profile sets `base_rate_cents` (the once-per-order haul price, at least 0), `included_days` (the number of rental days covered by the base rate before per-day overage applies, at least 1), `overage_day_cents` (the per-day fee beyond the included days, at least 0), `included_tonnage_lbs` (pounds of disposed material covered by the base rate before tonnage overage applies, at least 0), and `overage_rate_cents_per_lb` (the per-pound fee on disposed weight above the included tonnage, at least 0). A new type is born with `active` set to true. A type may later be retired, which sets `active` to false so no new order may select it; retiring does not disturb orders already placed against it.

Physical containers are registered individually against a type. A `Container` records its `container_type_id` (the type whose size and pricing it carries), an `asset_tag` stencilled on the steel (unique yard-wide), and a `yard_code` naming the depot where the empty can stages. A freshly registered can starts `IN_YARD` with a null `current_order_id`. Over its life a can cycles `IN_YARD → ASSIGNED → ON_SITE → AWAITING_DUMP → IN_YARD`, and may be taken out of service and brought back. Taking an `IN_YARD` can out of service moves it to `OUT_OF_SERVICE` (rejected with `ERR_CONTAINER_NOT_AVAILABLE` if the can is not `IN_YARD`); restoring an out-of-service can moves it from `OUT_OF_SERVICE` back to `IN_YARD` (rejected with `ERR_CONTAINER_NOT_OUT_OF_SERVICE` if it is not currently out of service). Each of these transitions increments the container's `version`.

### 3.2. Contractor Accounts and the Credit Ledger

A `ContractorAccount` is opened by a `YardAdmin` with a `business_name` and a `credit_limit_cents` (the maximum unpaid balance the account may carry, at least 0). The account opens `ACTIVE` with `outstanding_cents` at 0. Two ledger figures on the account are always computed, never directly written. The `outstanding_cents` is the sum of `total_cents` across every invoice on the account that is currently in `ISSUED` status; invoices that have been paid or voided are excluded from the sum. The `available_credit_cents` is the account's `credit_limit_cents` minus its `outstanding_cents`. These two figures are recomputed every time an invoice is issued, paid, or voided.

An account's `status` toggles between `ACTIVE` and `SUSPENDED`. Suspending an account blocks it from taking on new orders; reinstating it returns it to `ACTIVE`. A `SUSPENDED` account that a dispatcher tries to push a delivery for, or that anyone tries to book a new order against, is turned away — see the booking and dispatch flows for the exact codes.

When a contractor reads its own account, the `available_credit_cents` reported is simply `credit_limit_cents` minus `outstanding_cents` as they stand right now; this current reading ignores any order being booked in the same moment. The booking flow uses a stricter, forward-looking reading of the very same credit, described next.

### 3.3. Booking a Rental Order

A `Contractor` (booking for itself) or a `Dispatcher` (booking on a contractor's behalf) creates a rental order by supplying `account_id`, `container_type_id`, `site_address`, `requested_delivery_date` (an ISO `YYYY-MM-DD` date), and optionally `requires_street_permit` (defaulting to false when omitted). When a contractor books, the supplied `account_id` must equal its own `X-User-ID`. The order is created with `logistics_status` of `BOOKED` and `billing_status` of `UNBILLED`, with `container_id`, `delivered_on`, and `picked_up_on` all null, and `rental_days`, `estimated_total_cents`, and `final_total_cents` all 0. As a side effect of booking, a single `DELIVERY` service stop is created for the order in `UNASSIGNED` status.

Booking is gated on credit and account standing. The account must be `ACTIVE`; a booking against a suspended account is rejected. The credit gate uses the **projected** reading of available credit: take the account's current `available_credit_cents` and subtract the prospective order's `base_rate_cents` (the base rate of the requested container type). If that projected figure would be below zero — equivalently, if the new order's `base_rate_cents` exceeds the account's current `available_credit_cents` — the booking is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). The two readings of credit differ by exactly the prospective order's base rate: the account read shows credit as it stands, while the booking gate looks one order ahead.

A booked order may still be cancelled (covered in 3.8), and only `requires_street_permit` orders need a permit before they can be dispatched (covered in 3.4 and 3.5).

### 3.4. Street-Placement Permits

When a can must sit on a public street, the order is flagged with `requires_street_permit` set to true, and a `StreetPermit` must be approved before delivery. A permit is requested — by a `PermitOfficer`, a `Dispatcher`, or the owning `Contractor` — against an order via `order_id`, naming the `municipality`, the flat `permit_fee_cents` passed through to the bill (at least 0), and the closed date window `valid_from` to `valid_until` (both ISO `YYYY-MM-DD` dates). The `valid_until` must be on or after `valid_from`; a reversed window is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 422). A new permit enters in `REQUESTED` status.

A `PermitOfficer` decides each requested permit. Approving moves it `REQUESTED → APPROVED`; denying moves it `REQUESTED → DENIED`. Either decision requires the permit to currently be `REQUESTED`, otherwise it fails with `ERR_PERMIT_NOT_REQUESTED`. Approval carries two extra guards. First, the business clock's `current_date` must be on or before the permit's `valid_until`; approving a permit whose window has already passed is rejected with `ERR_PERMIT_WINDOW_PASSED` (if the business clock has never been set, this window-passed guard is treated as satisfied and approval proceeds to the overlap check). Second, the order may not already hold another `APPROVED` permit whose closed window overlaps this one — two windows that share even a single calendar day overlap — and an overlapping approval is rejected with `ERR_PERMIT_WINDOW_OVERLAP`. These two approval guards are evaluated in that order: window-passed first, then window-overlap.

An approved permit can later be expired. Running an expiry check on an `APPROVED` permit moves it `APPROVED → EXPIRED`, but only when the clock's `current_date` is strictly after the permit's `valid_until`; if the window has not yet passed — or if the business clock has never been set — the check is rejected with `ERR_PERMIT_NOT_EXPIRED`, and if the permit is not in `APPROVED` status to begin with it is rejected with `ERR_PERMIT_NOT_APPROVED`. The business `current_date` itself is set by a `YardAdmin` through the clock capability and read back through the clock-read capability; reading the clock before it has ever been set is rejected with `ERR_INVALID_REQUEST` (HTTP 422), and the set operation creates the clock on first use and returns HTTP 200 with the clock state; it governs both permit expiry and the dispatch-time permit-window check below.

### 3.5. Dispatching the Delivery: Committing a Container

A `Dispatcher` turns a `BOOKED` order into a scheduled one by committing a specific physical can to it. The dispatch supplies the chosen `container_id` and the `expected_container_version` for optimistic concurrency. Several conditions must all hold. The order must be `BOOKED`, else `ERR_ORDER_NOT_BOOKED`. The order's account must be `ACTIVE`, else `ERR_ACCOUNT_SUSPENDED`. The chosen container must be `IN_YARD`, else `ERR_CONTAINER_NOT_AVAILABLE`. The container's `container_type_id` must equal the order's `container_type_id`, else `ERR_CONTAINER_TYPE_MISMATCH`. If the order has `requires_street_permit` set, there must exist an `APPROVED` `StreetPermit` for the order whose `valid_from`–`valid_until` window covers the order's `requested_delivery_date`, else `ERR_PERMIT_NOT_APPROVED`. And the supplied `expected_container_version` must match the container's current `version`, else `ERR_STALE_CONTAINER_VERSION` as described in 2.5.

When all conditions hold, the order moves `BOOKED → SCHEDULED` on its logistics axis. The container moves `IN_YARD → ASSIGNED`, its `current_order_id` is set to the order's id, and its `version` increments. The order's `container_id` is set to the committed can. The order's `DELIVERY` service stop remains for the dispatcher to sequence onto a route; dispatching the delivery commits the can and schedules the order but does not by itself place the stop on a truck.

### 3.6. Routes and Stop Sequencing

A `Dispatcher` plans the day's truck runs as routes. A `Route` is created with a `service_date` (ISO `YYYY-MM-DD`), a `truck_code` (unique among routes on the same `service_date`), and a `capacity_stops` (the maximum number of stops it may hold, at least 1). It opens in `PLANNING` status with `stop_count` at 0, where `stop_count` is the live count of non-`CANCELLED` stops on the route.

Service stops are the unit of work on a route. Every order's `DELIVERY` stop is born with booking; `SWAP` and `PICKUP` stops are added later (see 3.7). A stop records its owning `order_id`, its `stop_type` (one of `DELIVERY`, `SWAP`, or `PICKUP`), an `estimated_weight_lbs` (the operator's estimate of loaded weight, used for swap and pickup stops and 0 for delivery, at least 0), and once placed on a route its `route_id` and 1-based `sequence`. A new stop is `UNASSIGNED` with a null `route_id` and null `sequence`.

Appending a stop to a route sequences it. The append targets a route and supplies the `service_stop_id` and the `expected_route_version`. The stop must be `UNASSIGNED` (`ERR_STOP_NOT_UNASSIGNED`); the route must be `PLANNING` (`ERR_ROUTE_NOT_PLANNING`); the route must have room, meaning its `stop_count` is strictly less than its `capacity_stops` (`ERR_ROUTE_AT_CAPACITY`); and the `expected_route_version` must match the route's current `version` (`ERR_STALE_ROUTE_VERSION`). On success the stop moves `UNASSIGNED → ASSIGNED`, its `route_id` is set, its `sequence` becomes the route's old `stop_count` plus 1 (so it lands last), the route's `stop_count` increases by 1, and the route's `version` increments.

A planned route is dispatched once it holds work. Dispatching requires the route to be `PLANNING` (`ERR_ROUTE_NOT_PLANNING`) and to hold at least one stop, that is `stop_count` of 1 or more (`ERR_ROUTE_EMPTY`); it then moves `PLANNING → DISPATCHED` and increments the route's `version`. Stops on a route become completable only once the route is `DISPATCHED`. After all of a route's non-`CANCELLED` stops are `COMPLETED`, the route may be closed: closing requires the route to be `DISPATCHED` (`ERR_ROUTE_NOT_DISPATCHED`) and every non-`CANCELLED` stop on it to be `COMPLETED` (`ERR_ROUTE_HAS_OPEN_STOPS`), then moves `DISPATCHED → CLOSED` and increments the route's `version`.

### 3.7. The Can on Site: Delivery, Swaps, and Pickup

Completing a stop is the single verb that drives the physical workflow forward, and what it does depends on the stop's type. A completion always requires the stop to be `ASSIGNED` (`ERR_STOP_NOT_ASSIGNED`) and its route to be `DISPATCHED` (`ERR_ROUTE_NOT_DISPATCHED`). For `SWAP` and `PICKUP` stops there is an additional gate: a `WeighTicket` referencing that very stop must already exist, else the completion is rejected with `ERR_WEIGH_TICKET_REQUIRED`. On success the stop itself moves `ASSIGNED → COMPLETED`.

Completing the **`DELIVERY`** stop advances the order from `SCHEDULED` to `ON_SITE` on its logistics axis (rejected with `ERR_ORDER_NOT_SCHEDULED` if the order is not `SCHEDULED`). The order's `delivered_on` is stamped with the `service_date` of the route that ran the stop, and the committed container moves `ASSIGNED → ON_SITE` (with its `version` incrementing).

While the order is `ON_SITE`, the contractor or dispatcher may request a **swap** (exchange a full can for an empty one) or a **pickup** (final removal). Creating a swap stop or a pickup stop both require the order to be `ON_SITE`, else `ERR_ORDER_NOT_ON_SITE`; each accepts an optional `estimated_weight_lbs` for the loaded can and creates a new `SWAP` or `PICKUP` service stop respectively in `UNASSIGNED` status, to be sequenced onto a route like any other stop. Completing a **`SWAP`** stop sends the hauled-away can `ON_SITE → AWAITING_DUMP` (its `version` incrementing) while the order stays `ON_SITE`; a fresh can continues the job. The weigh-ticket gate applies to swaps as it does to pickups.

Completing the **`PICKUP`** stop is the terminal logistics event and, on the same call, the full billing cascade. The order must be `ON_SITE` (`ERR_ORDER_NOT_ON_SITE`) and the pickup stop's `WeighTicket` must exist (`ERR_WEIGH_TICKET_REQUIRED`). The order moves `ON_SITE → AWAITING_PICKUP`; its `picked_up_on` is stamped with the completing route's `service_date`; and its `rental_days` is recomputed as the inclusive span from delivery to pickup — that is, `picked_up_on` minus `delivered_on`, plus 1, so a same-day deliver-and-pickup is 1 rental day. The container goes `ON_SITE → AWAITING_DUMP`. Then the billing cascade runs (3.9), and once billing finalizes the order automatically advances `AWAITING_PICKUP → COMPLETED` on the same call. A can left `AWAITING_DUMP` after a swap or pickup is brought back by a dispatcher returning it to the yard, which requires the can to be `AWAITING_DUMP` (`ERR_CONTAINER_NOT_AWAITING_DUMP`), then moves it `AWAITING_DUMP → IN_YARD`, clears its `current_order_id` to null, and increments its `version`.

### 3.8. Cancelling an Order or a Stop

A `Contractor` or `Dispatcher` may cancel an order that has not yet been delivered — that is, one whose `logistics_status` is `BOOKED` or `SCHEDULED`; cancelling any other order is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves the order's `logistics_status` to `CANCELLED` and cascades to its stops and any committed can. If the order was `BOOKED`, its `DELIVERY` stop is still `UNASSIGNED`, and that stop (and any other `UNASSIGNED` stop on the order) moves to `CANCELLED`. If the order was `SCHEDULED`, its `DELIVERY` stop is already `ASSIGNED` on a still-`PLANNING` route: that stop moves to `CANCELLED`, the route's `stop_count` is recomputed downward and its `version` increments, the committed container is released directly from `ASSIGNED → IN_YARD` with its `current_order_id` cleared to null and its `version` incremented, and the order's `container_id` is cleared to null.

A single stop may also be cancelled on its own. An `UNASSIGNED` stop can always be cancelled; an `ASSIGNED` stop can be cancelled only while its route is still `PLANNING`. A cancel request that finds the stop in neither cancellable condition is rejected with `ERR_STOP_NOT_CANCELLABLE`, and attempting to cancel an `ASSIGNED` stop whose route has left `PLANNING` additionally surfaces as a route-state conflict (`ERR_ROUTE_NOT_PLANNING`). Cancelling a stop moves it to `CANCELLED`; if it was `ASSIGNED`, the owning route's `stop_count` is recomputed downward and the route's `version` increments.

### 3.9. The Scale, the Weigh Ticket, and the Two-Stage Bill

A `ScaleOperator` records a **weigh ticket** when a hauled can crosses the scale. A `WeighTicket` references the `order_id` whose can was weighed and the `service_stop_id` of the `SWAP` or `PICKUP` stop that brought it in, and records the `gross_weight_lbs` (truck plus loaded can) and `tare_weight_lbs` (empty truck plus can), both whole pounds at least 0. The ticket's `net_weight_lbs` is computed as the gross weight minus the tare weight, but never below zero — if tare meets or exceeds gross, net is 0. The operator also records whether the load was `contaminated` (defaulting to false) and, if so, the `contamination_kind`, one of `NONE`, `TIRES`, `APPLIANCES`, or `HAZMAT` (defaulting to `NONE`). The ticket is immutable once written.

Billing runs as a two-stage cascade triggered by completing the `PICKUP` stop. The order's `billing_status` advances `UNBILLED → ESTIMATED → FINALIZED` within the one call, and the two stages use different weight sources.

**Stage one — the estimate.** The order moves `UNBILLED → ESTIMATED` and its `estimated_total_cents` is computed in this pinned order: (1) the base is the container type's `base_rate_cents`; (2) the overage-day charge is computed as below; (3) the tonnage charge is computed using the **estimated** weight — the `estimated_weight_lbs` recorded on the `PICKUP` service stop; (4) the permit charge is the `permit_fee_cents` of an `APPROVED` `StreetPermit` on the order if one exists, otherwise 0. The estimate is the sum of these four. Contamination is deliberately excluded from the estimate, because it cannot be known before the scale is read.

**Stage two — the final.** Immediately after, the order moves `ESTIMATED → FINALIZED` and its `final_total_cents` is computed in this pinned order: (1) base equals `base_rate_cents`; (2) the overage-day charge as below; (3) the tonnage charge using the **final** weight — the `net_weight_lbs` of the `PICKUP` stop's weigh ticket, which replaces the estimate; (4) permit equals the `APPROVED` permit's `permit_fee_cents` else 0; (5) the contamination fee as below. The tonnage charge must be computed before the contamination fee, because the HAZMAT branch of the contamination fee reuses the same overage pounds. The final is the sum of these five components. The provisional and final totals diverge whenever the estimated weight differs from the scale weight or any contamination is found.

**The overage-day charge.** The number of billable overage days is the order's `rental_days` minus the container type's `included_days`, but never below zero. The charge is that number of billable days multiplied by the type's `overage_day_cents`. At the boundary, an order whose `rental_days` exactly equals `included_days` incurs zero overage days, and one day beyond that incurs exactly one overage day's fee.

**The tonnage-overage charge.** The number of billable overage pounds is the weight in pounds minus the container type's `included_tonnage_lbs`, but never below zero; the charge is that number of billable pounds multiplied by the type's `overage_rate_cents_per_lb`. The weight used is the estimated weight in stage one and the scale `net_weight_lbs` in stage two. At the boundary, a weight exactly equal to `included_tonnage_lbs` yields zero, and one pound over yields exactly one unit of the per-pound rate.

**The contamination fee.** This fee is computed only at finalization and reads the `PICKUP` ticket's contamination flag and kind. If the ticket is not `contaminated`, or its `contamination_kind` is `NONE`, the fee is 0. If the kind is `TIRES`, the fee is a flat 7,500 cents. If the kind is `APPLIANCES`, the fee is a flat 12,000 cents. If the kind is `HAZMAT`, the fee is a flat 50,000 cents **plus** a surcharge of 15 cents for each billable overage pound — where the billable overage pounds are the very same pounds used in the final tonnage charge, namely the scale `net_weight_lbs` minus the type's `included_tonnage_lbs`, never below zero (not the full net weight). This is why tonnage must be computed before contamination.

### 3.10. Invoicing and Ledger Settlement

The tail of the pickup cascade issues an invoice. When the order reaches `FINALIZED`, an `Invoice` is created in `ISSUED` status against the order's `order_id`, with the order's `account_id` copied onto it at finalization. The invoice carries the same line items the final charge was built from: `base_cents` copied from the container type's base rate at finalization, the computed `overage_day_cents`, the computed `tonnage_cents`, `permit_cents` (the `APPROVED` permit's fee if one exists, else 0), and `contamination_cents` (the contamination fee). Its `total_cents` is the sum of `base_cents`, `overage_day_cents`, `tonnage_cents`, `permit_cents`, and `contamination_cents`. Issuing the invoice recomputes the account's `outstanding_cents` and `available_credit_cents`, since the new `ISSUED` invoice enters the unpaid set.

A `BillingClerk` settles invoices. Paying an invoice requires it to be `ISSUED` (`ERR_INVOICE_NOT_ISSUED`) and moves it `ISSUED → PAID`; voiding an invoice likewise requires `ISSUED` (`ERR_INVOICE_NOT_ISSUED`) and moves it `ISSUED → VOID`. Either action removes the invoice from the unpaid set, so in both cases the account's `outstanding_cents` and `available_credit_cents` are recomputed. Because outstanding counts only `ISSUED` invoices, paying or voiding immediately frees the corresponding credit, which the next booking's projected credit gate will see.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`. State-changing actions on existing resources, and all reads, return HTTP 200. Errors follow the envelope in Section 2.2 with the appropriate 4xx status from Section 5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/container-types` | Create a container size/pricing type | YardAdmin |
| GET | `/container-types` | List container types | YardAdmin, Dispatcher, Contractor, BillingClerk, ScaleOperator, PermitOfficer |
| GET | `/container-types/{typeId}` | Get a container type | YardAdmin, Dispatcher, Contractor, BillingClerk, ScaleOperator, PermitOfficer |
| POST | `/container-types/{typeId}/retire` | Mark a container type inactive for new orders | YardAdmin |
| POST | `/contractor-accounts` | Open a contractor credit account | YardAdmin |
| GET | `/contractor-accounts` | List contractor accounts | YardAdmin, BillingClerk, Dispatcher |
| GET | `/contractor-accounts/{accountId}` | Get a contractor account (computed outstanding/available) | YardAdmin, BillingClerk, Dispatcher, Contractor |
| POST | `/contractor-accounts/{accountId}/suspend` | Suspend an account (blocks new orders) | YardAdmin, BillingClerk |
| POST | `/contractor-accounts/{accountId}/reinstate` | Reinstate a suspended account | YardAdmin, BillingClerk |
| GET | `/contractor-accounts/{accountId}/orders` | List rental orders for an account | YardAdmin, BillingClerk, Dispatcher, Contractor |
| GET | `/contractor-accounts/{accountId}/invoices` | List invoices for an account | YardAdmin, BillingClerk, Contractor |
| POST | `/containers` | Register a physical container in the yard | YardAdmin |
| GET | `/containers` | List/filter containers | YardAdmin, Dispatcher |
| GET | `/containers/{containerId}` | Get a container | YardAdmin, Dispatcher |
| POST | `/containers/{containerId}/return-to-yard` | Return an AWAITING_DUMP container to the yard | Dispatcher |
| POST | `/containers/{containerId}/retire-asset` | Take an IN_YARD container out of service | YardAdmin |
| POST | `/containers/{containerId}/restore-asset` | Restore an OUT_OF_SERVICE container to the yard | YardAdmin |
| POST | `/rental-orders` | Book a rental order (credit-checked against the account) | Contractor, Dispatcher |
| GET | `/rental-orders` | List/filter rental orders | YardAdmin, Dispatcher, BillingClerk, Contractor |
| GET | `/rental-orders/{orderId}` | Get a rental order (computed estimated/final totals) | YardAdmin, Dispatcher, BillingClerk, Contractor |
| GET | `/rental-orders/{orderId}/service-stops` | List service stops for an order | YardAdmin, Dispatcher, Contractor |
| GET | `/rental-orders/{orderId}/weigh-tickets` | List weigh tickets for an order | YardAdmin, Dispatcher, BillingClerk, ScaleOperator, Contractor |
| GET | `/rental-orders/{orderId}/street-permits` | List street permits for an order | YardAdmin, Dispatcher, PermitOfficer, Contractor |
| GET | `/rental-orders/{orderId}/invoice` | List the invoice(s) for an order | YardAdmin, Dispatcher, BillingClerk, Contractor |
| POST | `/rental-orders/{orderId}/swap-stop` | Create an UNASSIGNED SWAP stop for an ON_SITE order | Dispatcher, Contractor |
| POST | `/rental-orders/{orderId}/pickup-stop` | Create an UNASSIGNED PICKUP stop for an ON_SITE order | Dispatcher, Contractor |
| POST | `/rental-orders/{orderId}/dispatch-delivery` | Commit a container and schedule the order's delivery (OCC on the chosen container) | Dispatcher |
| POST | `/rental-orders/{orderId}/cancel` | Cancel a BOOKED or SCHEDULED order | Contractor, Dispatcher |
| POST | `/routes` | Create a dispatch route for a service date | Dispatcher |
| GET | `/routes` | List/filter routes | YardAdmin, Dispatcher |
| GET | `/routes/{routeId}` | Get a route | YardAdmin, Dispatcher |
| GET | `/routes/{routeId}/stops` | List service stops sequenced on a route | YardAdmin, Dispatcher |
| POST | `/routes/{routeId}/stops` | Append an UNASSIGNED service stop to a PLANNING route (OCC on the route) | Dispatcher |
| POST | `/routes/{routeId}/dispatch` | Dispatch a planned route | Dispatcher |
| POST | `/routes/{routeId}/close` | Close a dispatched route once all its stops are completed | Dispatcher |
| GET | `/service-stops` | List/filter service stops | YardAdmin, Dispatcher, Contractor |
| GET | `/service-stops/{stopId}` | Get a service stop | YardAdmin, Dispatcher, Contractor |
| POST | `/service-stops/{stopId}/complete` | Complete an ASSIGNED stop on a DISPATCHED route; drives the order/container/billing cascade | Dispatcher |
| POST | `/service-stops/{stopId}/cancel` | Cancel an UNASSIGNED stop, or an ASSIGNED stop while its route is still PLANNING | Dispatcher, Contractor |
| POST | `/weigh-tickets` | Record a scale ticket for a SWAP/PICKUP stop | ScaleOperator |
| GET | `/weigh-tickets` | List/filter weigh tickets | YardAdmin, Dispatcher, BillingClerk, ScaleOperator |
| GET | `/weigh-tickets/{ticketId}` | Get a weigh ticket | YardAdmin, Dispatcher, BillingClerk, ScaleOperator |
| POST | `/street-permits` | Request a street-placement permit for an order | PermitOfficer, Dispatcher, Contractor |
| GET | `/street-permits` | List/filter street permits | YardAdmin, Dispatcher, PermitOfficer, Contractor |
| GET | `/street-permits/{permitId}` | Get a street permit | YardAdmin, Dispatcher, PermitOfficer, Contractor |
| POST | `/street-permits/{permitId}/approve` | Approve a requested permit | PermitOfficer |
| POST | `/street-permits/{permitId}/deny` | Deny a requested permit | PermitOfficer |
| POST | `/street-permits/{permitId}/expire-check` | Expire an approved permit whose window has passed | PermitOfficer |
| GET | `/invoices` | List/filter invoices | YardAdmin, BillingClerk, Contractor |
| GET | `/invoices/{invoiceId}` | Get an invoice with line items | YardAdmin, BillingClerk, Contractor |
| POST | `/invoices/{invoiceId}/pay` | Mark an issued invoice paid | BillingClerk |
| POST | `/invoices/{invoiceId}/void` | Void an issued invoice | BillingClerk |
| POST | `/_clock/set-current-date` | Set the server business date (test-driving) | YardAdmin |
| GET | `/_clock` | Read the current server business date | YardAdmin, Dispatcher, BillingClerk, ScaleOperator, PermitOfficer, Contractor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_CONTAINER_TYPE_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_CONTAINER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_STOP_NOT_FOUND` | 404 |
| `ERR_WEIGH_TICKET_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_ORDER_NOT_BOOKED` | 409 |
| `ERR_ORDER_NOT_SCHEDULED` | 409 |
| `ERR_ORDER_NOT_ON_SITE` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_STOP_NOT_UNASSIGNED` | 409 |
| `ERR_STOP_NOT_ASSIGNED` | 409 |
| `ERR_STOP_NOT_CANCELLABLE` | 409 |
| `ERR_ROUTE_NOT_PLANNING` | 409 |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 |
| `ERR_ROUTE_EMPTY` | 409 |
| `ERR_ROUTE_HAS_OPEN_STOPS` | 409 |
| `ERR_ROUTE_AT_CAPACITY` | 409 |
| `ERR_CONTAINER_NOT_AVAILABLE` | 409 |
| `ERR_CONTAINER_NOT_AWAITING_DUMP` | 409 |
| `ERR_CONTAINER_NOT_OUT_OF_SERVICE` | 409 |
| `ERR_CONTAINER_TYPE_MISMATCH` | 409 |
| `ERR_PERMIT_NOT_REQUESTED` | 409 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_PERMIT_NOT_EXPIRED` | 409 |
| `ERR_PERMIT_WINDOW_PASSED` | 409 |
| `ERR_PERMIT_WINDOW_OVERLAP` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_WEIGH_TICKET_REQUIRED` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_CONTAINER_VERSION` | 412 |
| `ERR_STALE_ROUTE_VERSION` | 412 |
