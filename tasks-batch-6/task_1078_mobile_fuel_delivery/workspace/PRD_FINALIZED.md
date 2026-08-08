# Mobile Fuel Delivery API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Mobile Fuel Delivery API, the backend that powers an on-demand fuel-and-gas delivery service in the style of Yoshi and Booster. Rather than routing drivers to a gas station, the platform brings the pump to the vehicle: a customer parks, requests a fill, and a fuel truck visits within a booked delivery window and dispenses the requested grade of fuel directly into the tank. The system must reconcile several concerns that ordinarily live in separate products — a pricing engine that locks a per-gallon rate at order time and reconciles it against the true dispensed volume, a membership subscription with per-period quotas and settlement credits, a fleet-management layer with account-wide spend ceilings and per-vehicle controls, and a physical logistics layer of trucks, multi-grade compartments, routes, and time windows.

The central design tension is that money and fuel are both conserved quantities that must never leak. Every order reserves budget and physical gallons the moment it is created, and every cancellation, failed access, or route teardown must release exactly what was reserved. Prices are computed twice — a provisional estimate at creation and a final figure at delivery — and the two deliberately diverge whenever the pumped volume differs from the requested volume or the posted price has moved. The API is consumed by six operational roles (platform operators, dispatchers, drivers, fleet managers, individual members, and billing officers), each owning a distinct slice of the surface. Because all time-sensitive logic (price effectivity, membership periods, route windows) is evaluated against a server-controlled logical clock rather than wall-clock time, the platform behaves deterministically and can be exercised end-to-end in test scenarios.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource paths are mounted at the service root.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. When either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the declared role is not permitted to perform the requested operation — or an ownership-scoped role attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `Dispatcher`, `Driver`, `FleetManager`, `Member`, and `BillingOfficer`.

Roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Customer` (an INDIVIDUAL account holder); ownership checks on any resource that references a customer — a membership, a vehicle, or an order — compare that resource's `customer_id` to `X-User-ID`. When `X-User-Role` is `FleetManager`, `X-User-ID` is likewise the `id` of the acting `Customer` (a FLEET account holder); ownership checks on fleet accounts, fleet vehicles, and fleet orders compare the owning `customer_id` to `X-User-ID`. When `X-User-Role` is `Driver`, `X-User-ID` is an opaque operator identifier that is not the primary key of any persisted entity; a driver may only execute stops on a route whose `assigned_driver_id` equals `X-User-ID`, and a driver acting on an order routed to a different driver's route is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `Dispatcher`, `PlatformAdmin`, or `BillingOfficer`, `X-User-ID` is similarly an opaque operator identifier not tied to any persisted entity's `id`; the server may record it for audit but does not compare it to any entity key for ownership.

`PlatformAdmin` manages customers, trucks, compartments, fuel prices, the logical clock, and the suspend/reactivate/close lifecycle of fleet accounts. `Dispatcher` plans routes, assigns orders to routes, and dispatches, completes, or cancels routes. `Driver` executes the field steps of arrival, delivery, and inaccessibility reporting. `FleetManager` manages a fleet account's controls, its vehicles, and its orders. `Member` manages an individual's own membership, own vehicles, and own orders. `BillingOfficer` runs membership period billing and settlement. The per-endpoint authorization matrix is given in Section 4.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every persisted resource carries a server-minted `id` that is an opaque UUID with no type prefix, along with a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Most resources — `Customer`, `Membership`, `FleetAccount`, `Vehicle`, `FuelTruck`, `TruckCompartment`, `DeliveryRoute`, and `DeliveryOrder` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that resource. Two resources are lightweight records and carry only `id` and `created_at`: the `AddOnService` line item and the `FuelPrice` posting. For these two, both `updated_at` and `version` are absent entirely.

All time-dependent behavior is evaluated against a server-controlled logical clock, never against wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-set call it remains fixed at this default and never falls back to real time. A `PlatformAdmin` may advance or rewind the clock by supplying a `to_iso8601` instant; the endpoint returns no resource body. The clock is the reference instant for fuel-price effectivity, membership period boundaries, and any comparison described elsewhere in this document as being "at the current clock."

### 2.5. Monetary Precision and Fuel Bookkeeping Precision

All monetary quantities are stored and returned as integer cents. Wherever a calculation multiplies a fractional quantity (such as gallons) by a per-unit price, the product is rounded to a whole number of cents using half-up rounding — a fractional cent of exactly one-half always rounds away from zero to the next whole cent. This rounding discipline is applied per component line, as detailed in Section 3: each fuel line, each add-on line, and each per-gallon discount is rounded to whole cents independently, and only the already-rounded lines are summed. Implementations must not sum raw fractional products and round once at the end, because the two approaches diverge by design on the catalog values chosen for this platform.

Physical fuel volumes (gallons) are tracked to one decimal place with exact bookkeeping. A compartment's reserved and available gallons must always be non-negative.

### 2.6. Optimistic Concurrency Control on Fleet Account Updates

Updating a fleet account's controls is a plain field overwrite that is not gated by any state precondition, so it is protected instead by optimistic concurrency control. A request to update a fleet account must carry `expected_fleet_account_version`, a non-optional field that must equal the target `FleetAccount`'s current `version` as the client last observed it. If another writer has advanced the account's `version` since the client last read it, the values no longer match and the update is rejected with `ERR_STALE_FLEET_ACCOUNT_VERSION` (HTTP 412), which prevents the client from silently clobbering a change it never saw (a lost update). This version gate applies only to the fleet-account update endpoint; no other endpoint accepts or requires a version field in its request body.

### 2.7. Budget and Fuel Conservation Invariants

Two ledger-style conservation laws hold at all times and govern how commitments are reserved and released.

The first is per-vehicle and per-fleet-account budget conservation. For any `Vehicle` whose `monthly_spend_cap_cents` is greater than 0, the sum of `committed_spend_cents`, `settled_spend_cents`, and `remaining_budget_cents` always equals `monthly_spend_cap_cents`, and both `committed_spend_cents` and `settled_spend_cents` are always at least 0. A `monthly_spend_cap_cents` of 0 signifies an unlimited cap (the default for individual vehicles), in which case the budget ceiling is not enforced. The parallel account-level law holds on every `FleetAccount`: the sum of `committed_budget_cents`, `settled_budget_cents`, and `remaining_budget_cents` always equals `monthly_budget_cap_cents`. Committing and releasing form a compensating pair: creating an order reserves its estimated total into the committed bucket, and cancelling that order releases exactly the same amount, so a create-then-cancel round trip leaves the remaining budget unchanged.

The second is per-compartment fuel conservation. For every `TruckCompartment`, the sum of `gallons_reserved` and `gallons_available` always equals `gallons_onboard`, with both `gallons_reserved` and `gallons_available` never negative. Reserving and releasing gallons form a compensating pair: assigning an order to a route reserves the order's requested gallons, and cancelling the order, reporting inaccessibility, or tearing down the route releases exactly those same gallons, so a reserve-then-release round trip leaves available gallons unchanged. The onboard total itself changes only in two circumstances — it rises when a compartment is restocked and falls when fuel is physically dispensed at delivery.

### 2.8. Existence Resolution and Validation Ordering

Requests are validated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication of the `X-User-ID` / `X-User-Role` headers, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization and ownership, failing with `ERR_UNAUTHORIZED`; (3) existence of every path-referenced and body-referenced resource; (4) state validity of the target and related resources; (5) cross-reference/referential business rules; (6) safety limits on gallons; (7) temporal-overlap rules; (8) capacity and quota constraints; and (9) fiscal budget rules. A check at a lower priority is only reached once every higher-priority check has passed.

For existence (priority 3), referenced resources are resolved left to right in the order they appear in the path and then the body, and the first unknown identifier determines the error: a missing customer yields `ERR_CUSTOMER_NOT_FOUND`, a missing membership `ERR_MEMBERSHIP_NOT_FOUND`, a missing fleet account `ERR_FLEET_ACCOUNT_NOT_FOUND`, a missing vehicle `ERR_VEHICLE_NOT_FOUND`, a missing truck `ERR_TRUCK_NOT_FOUND`, a missing compartment (or a compartment that does not belong to the named truck) `ERR_COMPARTMENT_NOT_FOUND`, a missing route `ERR_ROUTE_NOT_FOUND`, and a missing order `ERR_ORDER_NOT_FOUND`. A malformed body, a missing required field, or a value outside a field's allowed enum or type is a request-shape failure reported as `ERR_VALIDATION` (HTTP 400).

### 2.9. Cascading State Propagation and Hierarchical Consistency

Many operations mutate more than one resource, and every such cascade must be applied atomically together with its trigger. When a route is dispatched, the truck it runs transitions to `ON_ROUTE` and each routed order advances to `EN_ROUTE` in the same operation. When a route is cancelled, each order assigned to it returns to `SCHEDULED`, the route's stop count falls to zero, each such order releases its compartment reservation, and — if the truck was on this route — the truck returns to `AVAILABLE`. When a delivery completes, the settlement cascade touches the vehicle's fuel level, the compartment's onboard and reserved gallons, the vehicle's and fleet account's budget ledgers, and potentially the vehicle's and fleet account's status. When a membership is cancelled, its open-period settlement is computed and its schedulable orders are cancelled in turn, each releasing its own reservations and budget commitments. Every resource touched by a cascade has its `updated_at` refreshed and its `version` incremented as part of the same operation. Section 3 specifies each cascade in full at the point where its triggering workflow is described.

## 3. Business Logic & Workflows

This section describes the platform's business processes. The rules that govern a single request are deliberately distributed across the workflow that request participates in, so a complete implementation of any one endpoint must draw on several subsections here as well as the cross-cutting principles of Section 2.

### 3.1. Accounts, Memberships, and Fleet Controls

Every actor in the system ultimately traces back to a `Customer`, which a `PlatformAdmin` registers with a `name`, a contact `email`, and a `customer_type` of either `INDIVIDUAL` or `FLEET`. A customer's `status` is set to `ACTIVE` at registration and is the only lifecycle value it ever holds.

An individual customer subscribes to the platform by opening a `Membership`, supplied with the owning `customer_id`, an informational `tier` of `BASIC`, `PLUS`, or `PRO`, a recurring `monthly_fee_cents`, and the number of `included_deliveries` covered per period before an overage fee applies. The subscriber may also set `price_lock_enabled`; when this flag is omitted it defaults to true, meaning the fuel price is locked at order creation for this member's orders (its effect at delivery is detailed in Section 3.6). A new membership begins in status `ACTIVE` with `deliveries_used_this_period` at 0. Its `current_period_start` is stamped with the logical clock at creation, and `current_period_end` is computed as the period start plus a membership period of 30 days. At creation the provisional `estimated_next_charge_cents` is set to the full `monthly_fee_cents`, and `final_settlement_charge_cents` remains null until a settlement occurs.

A membership follows a cyclic lifecycle. A `Member` may pause an `ACTIVE` membership, moving it from `ACTIVE` to `PAUSED`; only an `ACTIVE` membership may be paused, and attempting to pause from any other state is rejected with `ERR_INVALID_MEMBERSHIP_STATE`. A `PAUSED` membership may be resumed, moving `PAUSED` to `ACTIVE`; resuming a membership that is not `PAUSED` is likewise rejected with `ERR_INVALID_MEMBERSHIP_STATE`. While a membership sits in `PAUSED` (or in `PAST_DUE`), the member cannot create new orders under it — that block surfaces during order creation, described in Section 3.4. A `Member` may cancel a membership from `ACTIVE`, `PAUSED`, or `PAST_DUE`; cancellation moves the membership to the terminal `CANCELLED` state, settles the open period, and cascades to the member's schedulable orders as described in Section 3.8. The billing-driven transitions into and out of `PAST_DUE`, and the self-loop that rolls an active period forward, are the province of the `BillingOfficer` and are described in Section 3.8.

A fleet is administered through a `FleetAccount`, which a `FleetManager` opens for a customer by supplying the `customer_id`; the referenced customer's `customer_type` must be `FLEET`, and an attempt to open a fleet account for a non-fleet customer is rejected with `ERR_CUSTOMER_NOT_FLEET`. The account is created with a `monthly_budget_cap_cents` ceiling, an `allowed_fuel_types` array drawn from `REGULAR`, `PREMIUM`, and `DIESEL`, and an `allowed_addons` array drawn from `CAR_WASH` and `OIL_CHANGE`. A new account opens in status `ACTIVE` with `committed_budget_cents` and `settled_budget_cents` both at 0; `remaining_budget_cents` is derived as the budget cap minus the committed and settled amounts, and the account tracks `active_vehicle_count` and `suspended_vehicle_count`, both starting at 0.

Fleet-account controls may be revised by a `FleetManager` through an update that carries `expected_fleet_account_version` together with any of the mutable fields — `monthly_budget_cap_cents`, `allowed_fuel_types`, or `allowed_addons`. The optimistic-concurrency behavior of that version field is specified in Section 2.6; when the update succeeds it applies only the provided fields and increments the account's `version` by 1. A `PlatformAdmin` governs the rest of the account lifecycle. Suspending an `ACTIVE` account moves it to `SUSPENDED`; reactivating a `SUSPENDED` account moves it back to `ACTIVE`. An account may also be suspended automatically by the system when its count of active vehicles falls to zero (see Section 3.2). Closing an account moves it from either `ACTIVE` or `SUSPENDED` to the terminal `CLOSED` state, but only when no non-terminal `DeliveryOrder` still references the account; if any live order remains, the close is rejected with `ERR_FLEET_ACCOUNT_HAS_ACTIVE_ORDERS`. Fleet lifecycle actions taken from a state the transition does not allow are rejected as an invalid fleet state.

### 3.2. Vehicles and the Fleet Roster

A `Vehicle` is registered by a `Member` or a `FleetManager` with the owning `customer_id`, a `make_model` label, a required `fuel_type` grade of `REGULAR`, `PREMIUM`, or `DIESEL`, and a `tank_capacity_gallons` that must be greater than 0. Optional inputs include `fleet_account_id` (which links the vehicle to a fleet account; it is null for a standalone individual vehicle), a starting `current_fuel_level_gallons` (defaulting to 0), and a `monthly_spend_cap_cents` per-vehicle spend ceiling (defaulting to 0, which means unlimited). A vehicle opens in status `ACTIVE`. Its `committed_spend_cents` and `settled_spend_cents` both begin at 0, and `remaining_budget_cents` is meaningful only when the cap is above 0, computed as the spend cap minus committed minus settled. When a vehicle is registered against a fleet account, that account's `active_vehicle_count` is incremented by 1.

Vehicles follow a cyclic suspend/reactivate lifecycle. A `FleetManager` may suspend an `ACTIVE` vehicle, moving it to `SUSPENDED`; the system may also suspend a vehicle automatically at delivery time when its settled spend reaches its cap (see Section 3.6). Whenever a fleet-linked vehicle transitions to `SUSPENDED`, its fleet account's `suspended_vehicle_count` rises by 1 and its `active_vehicle_count` falls by 1; if that decrement brings the account's active vehicle count to 0, the account itself transitions to `SUSPENDED`. While a vehicle is `SUSPENDED`, no new order may be created against it. A `FleetManager` reactivates a `SUSPENDED` vehicle, moving it back to `ACTIVE`; for a fleet-linked vehicle this decrements the account's `suspended_vehicle_count` and increments its `active_vehicle_count`, after which a previously auto-suspended account holding at least one active vehicle again may be reactivated separately by a `PlatformAdmin`. A vehicle suspend or reactivate attempted from a state the transition does not allow is an invalid-state condition.

### 3.3. Trucks, Compartments, and Fuel Inventory

The physical fleet consists of `FuelTruck` records, each created by a `PlatformAdmin` with a `plate` identifier and a `home_zone` base service zone of `ZONE_A` or `ZONE_B`. A truck opens in status `AVAILABLE` and moves cyclically through `AVAILABLE`, `ON_ROUTE`, and `MAINTENANCE`. The transitions to and from `ON_ROUTE` are driven entirely by the system as routes are dispatched and completed or cancelled (see Section 3.5). A `PlatformAdmin` may toggle maintenance directly by supplying `in_maintenance`: a true value moves an `AVAILABLE` truck to `MAINTENANCE`, and a false value returns a `MAINTENANCE` truck to `AVAILABLE`. A maintenance toggle attempted from a state that does not allow it is an invalid state.

Each truck carries fuel in one or more `TruckCompartment` sub-resources, added by a `PlatformAdmin`. A compartment is created under its parent truck (recorded as `truck_id`) with the `fuel_type` grade it stores and a `gallons_capacity` greater than 0; an optional starting `gallons_onboard` may be supplied and otherwise begins at 0. On creation `gallons_reserved` is 0 and `gallons_available` equals `gallons_onboard`. As specified in Section 2.7, a compartment's `gallons_available` is always its `gallons_onboard` minus its `gallons_reserved`. A truck's compartments may be listed as a reverse lookup by the parent `truck_id`.

Restocking adds fuel to a specific compartment: a `PlatformAdmin` names the `compartment_id` and the number of `gallons` to add, which raises that compartment's `gallons_onboard`. The named compartment must belong to the named truck, or the request fails with `ERR_COMPARTMENT_NOT_FOUND`. A restock that would push `gallons_onboard` above the compartment's `gallons_capacity` is rejected with `ERR_COMPARTMENT_OVERFILL`.

Posted fuel prices live in `FuelPrice` records, each registered by a `PlatformAdmin` with a `fuel_type`, a `zone`, a `price_per_gallon_cents` greater than 0, and an `effective_date` — the instant from which the price applies. Any operator role plus members and fleet managers may list prices. Price selection for an order works as follows: the candidate set is every `FuelPrice` row whose `fuel_type` matches the order's fuel type and whose `zone` matches the order's zone and whose `effective_date` is at or before the current logical clock. Candidates are ranked by `effective_date` from newest to oldest, so the most recent applicable price is preferred; when two candidates share the same effective date, the tie is broken in favor of the one with the later `created_at` (the more recently registered price wins). The `price_per_gallon_cents` of the winning row is the selected price. If the candidate set is empty — no price has been posted for that fuel type and zone at or before the clock — the operation is rejected with `ERR_NO_FUEL_PRICE_AVAILABLE`.

### 3.4. Placing an Order: Pricing Lock and Budget Commitment

A `DeliveryOrder` is created by a `Member` or a `FleetManager` and represents a single booked fill of one vehicle. The request supplies the ordering `customer_id`, the `vehicle_id` to fuel, the delivery `zone` (`ZONE_A` or `ZONE_B`), a free-text `delivery_address`, the `requested_gallons` to deliver (greater than 0), and a requested window given as `delivery_window_start` and `delivery_window_end`. Three optional inputs shape the order: a `membership_id` selects per-membership pricing (it is null for a plain per-fill order), a `fleet_account_id` marks the order as a fleet order (null otherwise), and an `is_priority` flag (defaulting to false) requests a priority window whose surcharge is described in Section 3.7. The order's `fuel_type` is not supplied by the caller; it is copied from the vehicle's required grade at creation. On creation the order enters status `SCHEDULED` with `payment_status` of `UNCHARGED` and no `route_id` yet assigned.

Order creation must clear several gates, evaluated in the global priority order of Section 2.8. For state validity, the target vehicle must be `ACTIVE` — an order on a `SUSPENDED` vehicle is rejected with `ERR_VEHICLE_SUSPENDED`. For a member order, the referenced membership must be `ACTIVE`; if it is `PAUSED`, `PAST_DUE`, or `CANCELLED`, the order is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`. For a fleet order, the referenced fleet account must be `ACTIVE`; if it is `SUSPENDED` or `CLOSED`, the order is rejected with `ERR_FLEET_ACCOUNT_SUSPENDED`. On referential grounds, a fleet order's `fuel_type` (the grade copied from the vehicle) must appear in the fleet account's `allowed_fuel_types`, or the order is rejected with `ERR_FUEL_TYPE_NOT_ALLOWED`; and a fuel price must be selectable for the order's fuel type and zone at the current clock, failing which the order is rejected with `ERR_NO_FUEL_PRICE_AVAILABLE`.

On safety grounds, the `requested_gallons` must fit the vehicle's tank headroom, defined as `tank_capacity_gallons` minus `current_fuel_level_gallons`; a request that exceeds that headroom is rejected with `ERR_EXCEEDS_TANK_CAPACITY`. On temporal grounds, a vehicle may not hold two non-terminal orders whose delivery windows crowd each other: the new order's window must be separated from every other non-terminal order window on the same vehicle by at least 60 minutes, measured as the gap between the nearest endpoints of the two windows. Two windows that overlap, that merely touch at an endpoint, or that are less than 60 minutes apart all conflict and are rejected with `ERR_VEHICLE_WINDOW_CONFLICT`.

When these gates pass, the order captures its price and reserves budget. The `locked_price_per_gallon_cents` is set from the price selection of Section 3.3 evaluated at the creation clock. The provisional `estimated_fuel_cost_cents` is the requested gallons multiplied by that locked per-gallon price, rounded to whole cents half-up. The order's provisional `service_fee_cents`, its `membership_discount_cents`, and — including any add-ons attached later — its `addon_total_cents` combine into the provisional `estimated_total_cents` exactly as Section 3.7 specifies. That estimated total is then reserved as budget: the vehicle's `committed_spend_cents` increases by the estimated total, and for a fleet order the fleet account's `committed_budget_cents` increases by the same amount. The final fiscal gate guards those ceilings — for a capped vehicle (a `monthly_spend_cap_cents` above 0), the estimated total must not push the vehicle's settled-plus-committed spend above its cap, or the order is rejected with `ERR_VEHICLE_BUDGET_EXCEEDED`; for a fleet order, the estimated total must not push the fleet account's settled-plus-committed budget above its `monthly_budget_cap_cents`, or it is rejected with `ERR_FLEET_BUDGET_EXCEEDED`.

### 3.5. Routing, Dispatch, and Route Teardown

A `Dispatcher` plans delivery work as a `DeliveryRoute`, created with the `truck_id` running the route, the `assigned_driver_id` (the opaque driver identifier permitted to execute this route's stops), the `zone` it covers (`ZONE_A` or `ZONE_B`), and its service window `window_start` and `window_end`. The window is half-open — the start is included and the end is excluded — and an optional `max_stops` cap (defaulting to 8, and at least 1) bounds how many orders may be assigned. A route opens in status `PLANNING` with `stop_count` at 0. At creation the platform enforces that a single truck never runs two overlapping routes: the new route's half-open window must not overlap any existing non-terminal route on the same truck. Because the interval is half-open, two windows that merely touch — where one window's end instant equals the other's start instant — do not overlap and are allowed; any genuine overlap is rejected with `ERR_TRUCK_ROUTE_OVERLAP`.

Assigning an order to a route is how a `SCHEDULED` order becomes `ROUTED`. A `Dispatcher` names the `route_id` on the order; the order must be `SCHEDULED` and the route must be in `PLANNING`, or the request is rejected as an invalid order state (`ERR_INVALID_ORDER_STATE`) or invalid route state (`ERR_INVALID_ROUTE_STATE`) respectively. The route's `zone` must equal the order's `zone`, or the assignment is rejected with `ERR_ROUTE_ZONE_MISMATCH`. The route must have capacity — its `stop_count` must be strictly less than its `max_stops`, or the assignment is rejected with `ERR_ROUTE_AT_CAPACITY`. Finally, the truck must physically carry the fuel: it must have a compartment of the order's `fuel_type` whose `gallons_available` is at least the order's `requested_gallons`; if no matching compartment exists or the matching compartment lacks sufficient available gallons, the assignment is rejected with `ERR_INSUFFICIENT_COMPARTMENT_FUEL`. On success the order advances `SCHEDULED → ROUTED`, its `route_id` is set, the route's `stop_count` increases by 1, and the matching compartment's `gallons_reserved` increases by the requested gallons.

Dispatching a route sets the field work in motion. A `Dispatcher` dispatches a route that is in `PLANNING`; the route's truck must be `AVAILABLE`, or the dispatch is rejected with `ERR_TRUCK_UNAVAILABLE`, and the route must carry at least one stop (`stop_count` of 1 or more). On dispatch the route advances `PLANNING → DISPATCHED`, the truck transitions to `ON_ROUTE`, and every assigned order still in `ROUTED` advances to `EN_ROUTE`. A `Dispatcher` completes a route that is in `DISPATCHED`, permitted only when no order assigned to it is still `EN_ROUTE` or `ARRIVED` — every order must have reached `DELIVERED`, `UNABLE_TO_ACCESS`, or been removed. On completion the route advances `DISPATCHED → COMPLETED` and its truck returns to `AVAILABLE`.

A `Dispatcher` may cancel a route from `PLANNING` or `DISPATCHED`, moving it to the terminal `CANCELLED` state. If the truck was `ON_ROUTE` for this route it returns to `AVAILABLE`. The cancellation cascades to the work in flight: each order assigned to the route that is still `ROUTED` or `EN_ROUTE` returns to `SCHEDULED`, the route's `stop_count` is reset to 0, and each such order releases its compartment reservation by decreasing that compartment's `gallons_reserved` by the order's `requested_gallons`. A dispatch, complete, or cancel attempted from a state the transition does not allow is rejected as an invalid route state.

### 3.6. Field Execution: Arrival, Delivery, and Exceptions

Once a route is dispatched, its orders are executed by the `Driver` assigned to the route. Every driver action is ownership-scoped, and this ownership check is applied before the order's own state is examined (consistent with the priority order of Section 2.8, where ownership is priority 2 and state validity is priority 4): the acting driver's `X-User-ID` must equal the `assigned_driver_id` of the route the order is currently assigned to, and a driver acting on an order that is not currently assigned to any route (`route_id` is null) or whose route belongs to another driver is rejected with `ERR_UNAUTHORIZED` — even when the order also sits in a state from which the action would otherwise be an invalid order state. A driver marks arrival at the vehicle, advancing the order `EN_ROUTE → ARRIVED`; the order must be `EN_ROUTE` for this to be valid.

Delivery is the settlement event. A driver reports the `dispensed_gallons` actually pumped for an order that is `ARRIVED`. The dispensed amount must not exceed the `requested_gallons` booked on the order, or the delivery is rejected with `ERR_DISPENSE_EXCEEDS_REQUESTED`; it must also fit the vehicle's remaining tank headroom (`tank_capacity_gallons` minus the current `current_fuel_level_gallons`), or the delivery is rejected with `ERR_EXCEEDS_TANK_CAPACITY`. On success the order advances `ARRIVED → DELIVERED`, its `payment_status` becomes `CHARGED`, and its final charges are computed. The `final_fuel_cost_cents` uses an effective per-gallon price: for a member order whose membership has `price_lock_enabled` set to true, the effective price is the order's `locked_price_per_gallon_cents` captured at creation; for every other order — a non-member order, or a member order whose price lock is disabled — the effective price is re-selected from the current fuel price at the delivery clock (per Section 3.3). The final fuel cost is the dispensed gallons multiplied by that effective price, rounded to whole cents half-up. The order's `membership_discount_cents` and its `total_cost_cents` are then assembled as Section 3.7 specifies.

Delivery also drives a chain of physical and financial side effects. The vehicle's `current_fuel_level_gallons` increases by the dispensed gallons. On the dispensing compartment, `gallons_onboard` decreases by the dispensed gallons and `gallons_reserved` decreases by the original requested-gallons reservation that assignment had placed. For a member order, the membership's `deliveries_used_this_period` increases by 1. The budget ledger then settles: the vehicle's `committed_spend_cents` is reduced by the order's original estimated total and its `settled_spend_cents` is increased by the final `total_cost_cents`; for a fleet order, in parallel, the fleet account's `committed_budget_cents` is reduced by the estimate and its `settled_budget_cents` is increased by the final total. If the vehicle has a cap above 0 and its `settled_spend_cents` reaches or exceeds its `monthly_spend_cap_cents`, the vehicle is automatically suspended (`ACTIVE → SUSPENDED`); that auto-suspension of a fleet-linked vehicle increments the fleet account's `suspended_vehicle_count` and decrements its `active_vehicle_count`, and if that decrement brings the account's `active_vehicle_count` to 0 the fleet account is itself suspended.

Not every visit succeeds. When the vehicle is unreachable, a driver reports inaccessibility for an `ARRIVED` order, advancing it `ARRIVED → UNABLE_TO_ACCESS`. That removal takes the order off the route: the route's `stop_count` decreases by 1, the order's `route_id` is cleared to null, and the compartment reservation is released by decreasing `gallons_reserved` by the order's `requested_gallons`. A `Member` or `FleetManager` may then reschedule an `UNABLE_TO_ACCESS` order back to `SCHEDULED`, supplying a fresh `delivery_window_start` and `delivery_window_end`. Rescheduling re-locks pricing: the `locked_price_per_gallon_cents` and `estimated_fuel_cost_cents` are recomputed from the current clock price, so the order can be re-routed onto a later route at then-current pricing.

An order may be cancelled before it is dispatched and delivered. A `Member`, `FleetManager`, or `Dispatcher` cancels an order in `SCHEDULED`, `ROUTED`, or `UNABLE_TO_ACCESS`, moving it to the terminal `CANCELLED` state. If the order was `ROUTED`, its route's `stop_count` decreases by 1 and its compartment reservation is released (that compartment's `gallons_reserved` decreases by `requested_gallons`). In all cases the vehicle's `committed_spend_cents` is reduced by the order's estimated total, and for a fleet order the fleet account's `committed_budget_cents` is reduced by the same estimated total. An arrive, deliver, report-inaccessible, reschedule, or cancel attempted from a state the transition does not allow is rejected as an invalid order state.

### 3.7. Add-Ons, Service Fees, and Order Totals

Beyond fuel, an order may carry add-on services. A `Member` or `FleetManager` attaches an `AddOnService` to an order by naming an `addon_type` of `CAR_WASH` or `OIL_CHANGE`. For a fleet order, the add-on type must appear in the fleet account's `allowed_addons`, or the request is rejected with `ERR_ADDON_NOT_ALLOWED`. Each add-on line records its own `order_id`, a `list_price_cents` catalog price for the type, and the `charged_price_cents` actually billed. The catalog price is 1595 cents for a `CAR_WASH` and 6495 cents for an `OIL_CHANGE`. For an order tied to a membership, the charged price applies a 10 percent member discount, computed as the list price multiplied by nine-tenths and rounded to whole cents half-up; for a non-member order, the charged price equals the list price with no discount. This discount is applied and rounded per add-on line — each line is rounded to whole cents on its own and only then are the lines summed — never by discounting the summed catalog total once. Attaching an add-on recomputes the order's `addon_total_cents` (the sum of the per-line charged prices) and, in turn, recomputes and re-commits the order's `estimated_total_cents`, adjusting the committed budget on the vehicle (and, for a fleet order, on the fleet account) to match the new estimate. An order's add-ons may be listed as a reverse lookup by `order_id`.

The `service_fee_cents` is a tiered delivery fee that depends on membership, quota usage, and priority. For a member order, the fee's base is 0 when the membership's `deliveries_used_this_period` is strictly less than its `included_deliveries` (the delivery is covered by the plan) and is a `MEMBER_OVERAGE_FEE_CENTS` of 600 cents once the plan quota is exhausted (that is, when used deliveries have reached the included count). For a per-fill order with no membership, the base is a `BASE_DELIVERY_FEE_CENTS` of 1200 cents. On top of the base, a priority order (`is_priority` set to true) adds a `PRIORITY_SURCHARGE_CENTS` surcharge of 500 cents, while a non-priority order adds nothing. The service fee is the base plus the surcharge. The quota comparison reads `deliveries_used_this_period` before this order's own delivery increment is applied, so the delivery that brings usage up to `included_deliveries` — the plan's last covered fill — is still free, and only deliveries beyond it incur the overage.

An order's total is assembled from independently rounded component lines; the platform rounds each line to whole cents first and only then sums the rounded lines, and must never sum raw products and round once. The lines are the fuel cost, the service fee (already an integer), the add-on total (itself a sum of per-line-rounded add-on charges), and a membership fuel discount that is subtracted. The `membership_discount_cents` is 0 for a non-member order; for a member order it is a per-gallon discount of `MEMBER_DISCOUNT_PER_GALLON_CENTS`, equal to 10 cents per gallon. In the provisional estimate the discount is the requested gallons multiplied by 10 cents, rounded half-up; in the final settlement it is the dispensed gallons multiplied by 10 cents, rounded half-up. Accordingly, the provisional `estimated_total_cents` equals `estimated_fuel_cost_cents` plus `service_fee_cents` plus `addon_total_cents` minus the estimate-variant discount, and the final `total_cost_cents` equals `final_fuel_cost_cents` plus `service_fee_cents` plus `addon_total_cents` minus the final-variant discount. The final total is clamped so it is never below 0.

### 3.8. Membership Billing, Settlement, and Cancellation

Membership billing is run by a `BillingOfficer`, who settles a period and rolls it forward by supplying an `outcome` of either `SUCCEEDED` or `FAILED`. Renewal is due only once the period has elapsed: the current logical clock must be at or after the membership's `current_period_end`, and a renewal attempted before then, or from a membership state the transition does not allow, is rejected with `ERR_INVALID_MEMBERSHIP_STATE`.

Two provisional-versus-final billing figures govern the money. At all times before a period is settled, the provisional `estimated_next_charge_cents` bills the full recurring `monthly_fee_cents` and ignores any unused-delivery credit. When a period is actually settled, the `final_settlement_charge_cents` grants credit for deliveries the member paid for but did not use: the count of unused deliveries is the included deliveries minus the deliveries used this period, floored at 0, and each unused delivery is worth an `UNUSED_DELIVERY_CREDIT_CENTS` credit of 400 cents. The final settlement charge is therefore the `monthly_fee_cents` minus that credit (unused deliveries multiplied by 400 cents), and it is clamped so it never falls below 0. The two figures diverge exactly when the member used fewer deliveries than were included.

The renewal outcome selects the transition. A successful renewal of an `ACTIVE` membership whose period has elapsed keeps it `ACTIVE` (a self-loop): the closing period's `final_settlement_charge_cents` is computed, the `current_period_start` advances to the prior `current_period_end`, the `current_period_end` is recomputed 30 days later, and `deliveries_used_this_period` is reset to 0. A failed renewal of an `ACTIVE` membership whose period has elapsed moves it `ACTIVE → PAST_DUE`, computing the closing period's `final_settlement_charge_cents`; while a membership is `PAST_DUE`, its member cannot create new orders (as noted in Section 3.4). A subsequent successful renewal of a `PAST_DUE` membership recovers it `PAST_DUE → ACTIVE`, advancing `current_period_start` to the prior `current_period_end`, recomputing `current_period_end`, resetting `deliveries_used_this_period` to 0, and recomputing `estimated_next_charge_cents` back to the full `monthly_fee_cents`.

Cancellation closes a membership out. When a `Member` cancels a membership from `ACTIVE`, `PAUSED`, or `PAST_DUE`, the membership moves to the terminal `CANCELLED` state and its open period is settled — its `final_settlement_charge_cents` is computed as the fee minus the unused-delivery credit, exactly as at renewal. Cancellation then cascades to the member's live orders: every `DeliveryOrder` carrying this `membership_id` that is still `SCHEDULED` or `ROUTED` transitions to `CANCELLED`, and each such cascaded cancellation itself releases that order's fuel reservation (if it was `ROUTED`) and releases the vehicle's committed spend — and, for a fleet order, the fleet account's committed budget — by the order's estimated total, exactly as an ordinary order cancellation does in Section 3.6.

## 4. Endpoint Definitions

The table below summarizes every endpoint, its path, a short description, and the roles authorized to call it. Creating a new resource returns HTTP 201; all other successful operations, including state transitions and updates that return the mutated resource, return HTTP 200. Request bodies, response bodies, and side effects are not repeated here — they are specified in the Section 3 workflow narratives. Ownership scoping (Section 2.1) further restricts entity-backed roles to resources they own even where the role is listed as authorized.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /customers | Register a customer (INDIVIDUAL or FLEET) | PlatformAdmin |
| GET | /customers | List customers | PlatformAdmin, BillingOfficer |
| GET | /customers/{id} | Get a customer | PlatformAdmin, BillingOfficer, FleetManager, Member |
| POST | /memberships | Subscribe an individual customer to a membership | Member |
| GET | /memberships | List memberships | Member, BillingOfficer, PlatformAdmin |
| GET | /memberships/{id} | Get a membership | Member, BillingOfficer, PlatformAdmin |
| POST | /memberships/{id}/pause | Pause an active membership | Member |
| POST | /memberships/{id}/resume | Resume a paused membership | Member |
| POST | /memberships/{id}/cancel | Cancel a membership | Member |
| POST | /memberships/{id}/renew-charge | Settle the period and roll it forward or mark past due | BillingOfficer |
| POST | /fleet-accounts | Create a fleet account for a FLEET customer | FleetManager |
| GET | /fleet-accounts | List fleet accounts | FleetManager, PlatformAdmin, BillingOfficer |
| GET | /fleet-accounts/{id} | Get a fleet account | FleetManager, PlatformAdmin, BillingOfficer |
| PATCH | /fleet-accounts/{id} | Update fleet controls (OCC-guarded) | FleetManager |
| POST | /fleet-accounts/{id}/suspend | Suspend a fleet account | PlatformAdmin |
| POST | /fleet-accounts/{id}/reactivate | Reactivate a suspended fleet account | PlatformAdmin |
| POST | /fleet-accounts/{id}/close | Close a fleet account | PlatformAdmin |
| POST | /vehicles | Register a vehicle for an individual or fleet customer | Member, FleetManager |
| GET | /vehicles | List vehicles | Member, FleetManager, Dispatcher, PlatformAdmin |
| GET | /vehicles/{id} | Get a vehicle | Member, FleetManager, Dispatcher, PlatformAdmin |
| POST | /vehicles/{id}/suspend | Suspend a vehicle | FleetManager |
| POST | /vehicles/{id}/reactivate | Reactivate a suspended vehicle | FleetManager |
| POST | /trucks | Create a fuel truck | PlatformAdmin |
| GET | /trucks | List fuel trucks | PlatformAdmin, Dispatcher, Driver |
| GET | /trucks/{id} | Get a fuel truck | PlatformAdmin, Dispatcher, Driver |
| POST | /trucks/{id}/maintenance | Toggle a truck in/out of maintenance | PlatformAdmin |
| POST | /trucks/{id}/compartments | Add a fuel compartment to a truck | PlatformAdmin |
| GET | /trucks/{id}/compartments | List a truck's compartments | PlatformAdmin, Dispatcher, Driver |
| POST | /trucks/{id}/restock | Add gallons to a compartment | PlatformAdmin |
| POST | /routes | Create a delivery route for a truck | Dispatcher |
| GET | /routes | List routes | Dispatcher, Driver, PlatformAdmin |
| GET | /routes/{id} | Get a route | Dispatcher, Driver, PlatformAdmin |
| POST | /routes/{id}/dispatch | Dispatch a planned route | Dispatcher |
| POST | /routes/{id}/complete | Complete a dispatched route | Dispatcher |
| POST | /routes/{id}/cancel | Cancel a route | Dispatcher |
| POST | /orders | Create a delivery order (member, fleet, or per-fill) | Member, FleetManager |
| GET | /orders | List orders | Member, FleetManager, Dispatcher, Driver, BillingOfficer, PlatformAdmin |
| GET | /orders/{id} | Get an order | Member, FleetManager, Dispatcher, Driver, BillingOfficer, PlatformAdmin |
| POST | /orders/{id}/assign-route | Assign a scheduled order to a planning route | Dispatcher |
| POST | /orders/{id}/arrive | Driver marks arrival at the vehicle | Driver |
| POST | /orders/{id}/deliver | Driver dispenses fuel and completes the order | Driver |
| POST | /orders/{id}/report-unable-access | Driver reports the vehicle was inaccessible | Driver |
| POST | /orders/{id}/reschedule | Reschedule an inaccessible order with a new window | Member, FleetManager |
| POST | /orders/{id}/cancel | Cancel a non-dispatched order | Member, FleetManager, Dispatcher |
| POST | /orders/{id}/addons | Attach an add-on service to an order | Member, FleetManager |
| GET | /orders/{id}/addons | List an order's add-ons | Member, FleetManager, Dispatcher, Driver, BillingOfficer, PlatformAdmin |
| POST | /fuel-prices | Post a fuel price for a (fuel type, zone) effective at a date | PlatformAdmin |
| GET | /fuel-prices | List fuel prices | PlatformAdmin, Dispatcher, Member, FleetManager |
| POST | /_clock/set_current_utc | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

The table lists every error identifier and its HTTP status code. The conditions that trigger each error are described in the Section 2 and Section 3 narratives, not repeated here.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_VALIDATION | 400 |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_MEMBERSHIP_NOT_FOUND | 404 |
| ERR_FLEET_ACCOUNT_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_TRUCK_NOT_FOUND | 404 |
| ERR_COMPARTMENT_NOT_FOUND | 404 |
| ERR_ROUTE_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_VEHICLE_SUSPENDED | 409 |
| ERR_MEMBERSHIP_NOT_ACTIVE | 409 |
| ERR_INVALID_MEMBERSHIP_STATE | 409 |
| ERR_FLEET_ACCOUNT_SUSPENDED | 409 |
| ERR_TRUCK_UNAVAILABLE | 409 |
| ERR_INVALID_ORDER_STATE | 409 |
| ERR_INVALID_ROUTE_STATE | 409 |
| ERR_FLEET_ACCOUNT_HAS_ACTIVE_ORDERS | 409 |
| ERR_FUEL_TYPE_NOT_ALLOWED | 422 |
| ERR_ADDON_NOT_ALLOWED | 422 |
| ERR_NO_FUEL_PRICE_AVAILABLE | 422 |
| ERR_ROUTE_ZONE_MISMATCH | 422 |
| ERR_CUSTOMER_NOT_FLEET | 422 |
| ERR_EXCEEDS_TANK_CAPACITY | 422 |
| ERR_DISPENSE_EXCEEDS_REQUESTED | 422 |
| ERR_TRUCK_ROUTE_OVERLAP | 409 |
| ERR_VEHICLE_WINDOW_CONFLICT | 409 |
| ERR_ROUTE_AT_CAPACITY | 409 |
| ERR_INSUFFICIENT_COMPARTMENT_FUEL | 409 |
| ERR_COMPARTMENT_OVERFILL | 409 |
| ERR_VEHICLE_BUDGET_EXCEEDED | 402 |
| ERR_FLEET_BUDGET_EXCEEDED | 402 |
| ERR_STALE_FLEET_ACCOUNT_VERSION | 412 |
