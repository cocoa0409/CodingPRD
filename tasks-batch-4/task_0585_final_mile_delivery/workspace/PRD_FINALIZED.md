# Final-Mile Delivery API — Product Requirements Document

## 1. Introduction

The Final-Mile Delivery API coordinates the "big & bulky" white-glove logistics network — the last leg of the supply chain where heavy, high-value freight (appliances, furniture, fitness equipment) is scheduled, routed, loaded, and physically placed inside a customer's home by a two-person crew. Unlike parcel delivery, every shipment here carries a promised level of service (threshold drop, room-of-choice placement, or full white-glove installation), an appointment window the customer must be able to confirm, capacity constraints on the crew's truck, and a proof-of-delivery obligation at the door.

This system exists because the operational reality is unforgiving: a crew can only carry so much weight and volume in a day, a dock can only load one truck at a time, a refused delivery must gracefully release its committed capacity and loop back for a reattempt, and a damaged item must be reflected in the crew's liability exposure. The API models the entire lifecycle — from network configuration (depots, docks, crews, customers), through order intake and fee quoting, window reservation and confirmation, route building and dock loading, field dispatch and proof-of-delivery capture, to final fee settlement and payout reconciliation. Throughout, the platform enforces immediate consistency: derived aggregates such as committed route load, provisional crew liability, and customer balances are always reconciled the moment their underlying facts change.

The intended readers are the engineers implementing the service. This document specifies the behavioral contract: the resource model, the state machines that govern each entity, the arithmetic behind every fee and points figure, the validation precedence, and the exact error surface. Where a rule has a natural home in a workflow, it is described there rather than in an isolated table.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is absent, or the role is not one the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`.

The system recognizes exactly five roles: `PlatformAdmin`, `DispatchPlanner`, `DockCoordinator`, `DeliveryLead`, and `Customer`. Each write operation is restricted to specific roles; an authenticated principal attempting an operation outside its authority is rejected with `ERR_UNAUTHORIZED`. All read (list and fetch) endpoints are available to every one of the five roles.

Three roles carry an **opaque** identity and two are **entity-backed**:

- When `X-User-Role` is `PlatformAdmin`, `DispatchPlanner`, or `DockCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it against any resource's `id`; these operators act on the network at large.
- When `X-User-Role` is `DeliveryLead`, `X-User-ID` is the `id` of the acting `DeliveryTeam`; that crew is the one recording field results. Any operation whose ownership is scoped to a crew compares the crew referenced by the target resource (through its route) to `X-User-ID`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on a delivery window compare the `customer_id` of the window's order to `X-User-ID`.

Ownership enforcement is described where each workflow uses it: a `Customer` confirming a window that does not belong to their own order is rejected with `ERR_NOT_RESOURCE_OWNER`, and a `DeliveryLead` recording an attempt on an order whose active stop belongs to a different crew is rejected with `ERR_STOP_ORDER_MISMATCH`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0.

Unless a workflow states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources are **fully versioned** and expose a common set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp (three fractional digits) marking when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp marking the most recent mutation; it is refreshed on every change, including changes to derived fields.
- `version` — an integer that begins at creation and increments by one on every mutation of the resource.

These common fields are carried by `Depot`, `Dock`, `DeliveryTeam`, `Customer`, `DeliveryOrder`, `DeliveryWindow`, `Route`, `RouteStop`, and `DockAppointment`.

The `DeliveryAttempt` resource is an exception. An attempt is an immutable field record: once written it is never modified. It therefore carries only `id` and `created_at`; it has no `updated_at` field and no `version` field.

### 2.5. Monetary and Points Precision

All money in the system is expressed in **integer cents** — there are no fractional cents anywhere in a stored fee, balance, or payout. Wherever a calculation multiplies by a rate (the white-glove multiplier or the payout rate), the intermediate product is rounded to a whole number of cents using the **round half up** convention (a value ending in exactly one-half rounds up to the next integer). The precise point at which rounding is applied within each formula is fixed and stated with that formula in §3; rounding is never deferred or re-applied to an already-rounded subtotal unless the formula says so.

Liability is tracked in **integer points**, not money. Where a points figure divides a monetary value by a unit size, the quotient is rounded **up to the next whole number** (ceiling) before it contributes to the total.

### 2.6. Optimistic Concurrency Control on Delivery Orders

Reserving, rescheduling, or superseding a delivery window is guarded by optimistic concurrency control on the parent `DeliveryOrder`. A window-reservation request must carry `expected_order_version`, a non-optional field holding the `version` of the order the client last observed. The server compares `expected_order_version` against the order's current `version`; if they differ — because another writer has advanced the order since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no window is created.

This matters because a reservation against a `SCHEDULED` order legitimately supersedes the order's prior reserved window (releasing it) and bumps the order's `version`. A second reservation still carrying the pre-supersede version is acting on a stale view of the order and must be rejected on the version mismatch rather than silently clobbering the window the client never saw. No other endpoint takes a version field; only window reservation is version-checked.

### 2.7. Cascading Reconciliation and Derived-Field Integrity

Several operations mutate more than one resource. The system performs each cascade fully and immediately; a partial cascade is never observable.

Derived aggregates are always recomputed from their source facts rather than incrementally patched in isolation. A route's committed load (`committed_stops`, `committed_weight_lbs`, `committed_volume_cuft`) is recomputed whenever a stop is added, removed, completed, or skipped. A crew's provisional liability (`estimated_liability_points`) is recomputed whenever one of its windows enters or leaves the reserved/confirmed set. A route's `dock_ready` flag is recomputed from its dock appointment link. Every such reconciliation is a mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`.

When a dock is closed, the effect cascades: each booked appointment on that dock is released, and for each such appointment the owning route's dock link is cleared and its readiness turned off. When a delivery fails in the field, the effect cascades from the attempt through the order to its route stop and on to the route's committed load. These multi-hop cascades are detailed in the workflows of §3.

### 2.8. Left-to-Right Path Resolution

Endpoints that nest identifiers in the URL — for example, a route's stops or a stop-scoped removal — resolve each identifier from left to right and reject on the **first** one that does not exist. A body foreign key (`depot_id`, `dock_id`, `team_id`, `customer_id`, `order_id`, `window_id`, `route_id`, `stop_id`) is likewise checked for existence. Each missing identifier maps to its own not-found error: `ERR_DEPOT_NOT_FOUND`, `ERR_DOCK_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, and `ERR_STOP_NOT_FOUND`. Existence is verified before any business rule is evaluated.

### 2.9. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed order, so the returned error is deterministic. The precedence, from first to last, is:

1. **Authentication** — presence and recognition of `X-User-ID` and `X-User-Role`; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted this write operation per §2.1; failure yields `ERR_UNAUTHORIZED`.
3. **Resource ownership** — for ownership-scoped operations (a customer confirming their own window); failure yields `ERR_NOT_RESOURCE_OWNER`.
4. **Existence** — every path id and body foreign key resolves, left to right (§2.8); failure yields the matching not-found error.
5. **Payload validity** — required fields present, enums valid, and the field-level constraints of §3 satisfied (`weight_lbs` greater than 0, `volume_cuft` greater than 0, `declared_value_cents` at least 0); failure yields `ERR_VALIDATION`. The structural window check that `window_end_min` is strictly greater than `window_start_min` yields `ERR_INVALID_WINDOW` at this same stage.
6. **Optimistic concurrency** — `expected_order_version` matches the order's current `version`; failure yields `ERR_STALE_VERSION`.
7. **State legality** — the target resource is in a state that permits the requested transition; a general failure yields `ERR_INVALID_STATE`.
8. **Referential business rules** — cross-entity consistency such as already-routed, team/route mismatch, window/route date mismatch, region mismatch, and stop/order crew mismatch.
9. **Safety rules** — crew in service, crew certification, and proof-of-delivery completeness.
10. **Temporal rules** — window overlap on a crew's calendar, and dock buffer conflicts.
11. **Referral/limit rules** — reattempt ceiling, dock-appointment presence at dispatch, and route-close readiness.
12. **Capacity (fiscal) rules** — the per-route stop, weight, and volume ceilings.

Later sections attach each specific `error_id` to the rule it guards; this ordering determines which one surfaces when more than one applies.

## 3. Business Logic & Workflows

### 3.1. Configuring the Delivery Network

Before any freight moves, a `PlatformAdmin` provisions the static network. A **depot** is created with a `name` and a `region_code` denoting the service region it serves. Within a depot, the admin creates **loading docks**, each referencing its `depot_id` and carrying a human `dock_code`. A dock also holds a `slot_length_min` — the nominal appointment length in minutes, purely informational, defaulting to 60 — and a `buffer_min`, the required clear gap in minutes between two booked appointments on that dock, defaulting to 30. A dock begins life `OPEN`; its `status` toggles to `CLOSED` only through the coordinator action described in §3.4.

The admin also provisions **delivery crews**. A crew references its home `depot_id` and is described by a `team_name`, the crew lead's `lead_name` (the person-one identity behind the `DeliveryLead` role), and the mandatory second crew member's `member2_name` — every crew is a two-person team. A crew serves a single `region_code`, which must match a customer's region for that crew to be scheduled against the customer's order. Capacity ceilings are set per crew: `max_daily_stops`, `max_daily_weight_lbs`, and `max_daily_volume_cuft`. Two certification flags govern what work the crew may take on: `white_glove_certified` (default false) gates white-glove orders, and `assembly_certified` (default false) gates in-home assembly. A crew's `status` is a configuration flag, not a lifecycle — either `ACTIVE` (the default) or `OUT_OF_SERVICE`. Two computed exposure figures ride along on the crew: `estimated_liability_points` and `settled_liability_points`, both starting at 0 and reconciled as described in §3.7.

Finally, the admin registers **customers**. A customer carries a `full_name`, an `address_line`, the `region_code` of the delivery address, and its geographic coordinates `geo_lat` and `geo_lng`. A customer's `outstanding_balance_cents`, a computed money ledger, starts at 0 and moves only through settlement and its reversal (§3.7).

### 3.2. Order Intake and the Quoted Fee

A `DispatchPlanner` opens the fulfillment lifecycle by creating a **delivery order** against a `customer_id`. The order describes the freight through an `item_description`, its `weight_lbs` and `volume_cuft` (each of which must be strictly greater than 0), and its `declared_value_cents` (which must be at least 0). The ordered `service_level` is one of `THRESHOLD`, `ROOM_OF_CHOICE`, or `WHITE_GLOVE`. Three option fields tune the job: `assembly_required` (default false), `haul_away_required` (default false, for old-item debris removal), and `stair_flights` (default 0, the number of stair flights up to the room of choice). A new order enters `status` `CREATED`.

At creation, the system computes a provisional **quoted fee** and stores it as `quoted_fee_cents`. The quote is built as follows. Start from the service base for the ordered level: `THRESHOLD` costs 4000 cents, `ROOM_OF_CHOICE` 7000 cents, and `WHITE_GLOVE` 12000 cents. Add the weight surcharge, chosen by tier from `weight_lbs`: items of 75 pounds or less add nothing; items from 76 through 150 pounds add 1500 cents; items from 151 through 300 pounds add 3500 cents; items heavier than 300 pounds add 6000 cents. Take the sum of the service base and the weight surcharge and multiply it by the white-glove multiplier — 1.15 when the ordered `service_level` is `WHITE_GLOVE`, and 1.00 otherwise — then round that product half up to a whole cent. This rounded amount is the core charge; rounding happens exactly once here, before any flat add-ons.

To the core charge, add the stair charge: take the smaller of `stair_flights` and the billable ceiling of 5 flights, and multiply by 800 cents per flight. Then add a flat 2500 cents when `assembly_required` is true, and a flat 3000 cents when `haul_away_required` is true. The resulting sum is `quoted_fee_cents`. The quote assumes the ordered service level, assumes assembly will be performed, uses the flat haul-away estimate, and includes no reattempt fees — it is a forward estimate, reconciled against actuals only at delivery.

Orders expose several system-maintained fields that track their progress: `reattempt_count` (the number of failed attempts so far, starting at 0), `active_window_id` (the id of the current non-terminal window, or null), `active_stop_id` (the id of the current planned stop, or null), `actual_placement_level` (the placement actually achieved, null until delivered), and `final_fee_cents` (the settled fee, null until delivered). The order `status` traverses `CREATED`, `SCHEDULED`, `ROUTED`, `OUT_FOR_DELIVERY`, `DELIVERED`, `REFUSED_RETRY`, `SETTLED`, `RETURNED`, and `CANCELLED`; `SETTLED`, `RETURNED`, and `CANCELLED` are terminal.

An order may be abandoned before it is ever delivered. Cancellation is permitted only while the order is in `CREATED`, `SCHEDULED`, or `REFUSED_RETRY`; from any other state the request is rejected with `ERR_INVALID_STATE`. Cancelling releases any active window (moving it to `RELEASED` and clearing `active_window_id`) and moves the order to `CANCELLED`.

### 3.3. Reserving and Confirming Delivery Windows

Scheduling attaches an appointment window to an order. A `DispatchPlanner` reserves a window by supplying the crew's `team_id`, the `service_date` (a calendar date, `YYYY-MM-DD`), and the interval `window_start_min` and `window_end_min` (minutes from midnight, where the end must be strictly greater than the start — otherwise `ERR_INVALID_WINDOW`). The request must also carry `expected_order_version` per the concurrency rule of §2.6.

A reservation is legal in three order states, each a distinct transition. From `CREATED`, reserving a window advances the order `CREATED → SCHEDULED`. From `REFUSED_RETRY`, reserving a fresh window re-enters the scheduling loop and advances `REFUSED_RETRY → SCHEDULED`; this reschedule is allowed only while `reattempt_count` is strictly less than the ceiling of 2 reattempts, otherwise `ERR_MAX_REATTEMPTS`. From `SCHEDULED`, reserving again is a self-loop `SCHEDULED → SCHEDULED` that supersedes the current window — but only while the order has not yet been routed, that is, `active_stop_id` is null. In every case, a reservation on an order not in one of these permitted states is rejected with `ERR_INVALID_STATE`.

The following crew checks apply on every reservation (from `CREATED`, from `REFUSED_RETRY`, and on the superseding self-loop alike). The referenced crew must exist and its `status` must be `ACTIVE`, else `ERR_TEAM_OUT_OF_SERVICE`. The crew's `region_code` must equal the customer's `region_code`, else `ERR_REGION_MISMATCH`. If the order's `service_level` is `WHITE_GLOVE`, the crew must be `white_glove_certified`; if the order's `assembly_required` is true, the crew must be `assembly_certified`; a failure of either certification check yields `ERR_TEAM_NOT_CERTIFIED`. Finally, the new interval must not overlap any window already held by that same crew in `RESERVED` or `CONFIRMED` status on the same `service_date`; an overlap is rejected with `ERR_TEAM_WINDOW_CONFLICT`. Two intervals overlap when each starts before the other ends, treating each window as the half-open interval from its start minute up to (but not including) its end minute.

A successful reservation creates a `DeliveryWindow` in `RESERVED` status, records the order's `order_id` and the reserved `team_id`, and sets the order's `active_window_id` to the new window. On the superseding self-loop, the prior active window is first moved to `RELEASED`. In all cases the order moves to (or remains) `SCHEDULED`, its `version` increments by one, and the crew's `estimated_liability_points` is recomputed. Each window carries its own `status` through `RESERVED`, `CONFIRMED`, `RELEASED`, and `COMPLETED`.

The `Customer` who owns the order confirms a reserved window, transitioning it `RESERVED → CONFIRMED`. Confirmation requires that the window be `RESERVED` and the owning order be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), and that the acting `Customer` be the order's own customer (otherwise `ERR_NOT_RESOURCE_OWNER`). Confirmation is optional to the delivery flow: a window may be delivered against directly from `RESERVED`. When a window is superseded, or its order is cancelled or refused, the window moves to `RELEASED` (from either `RESERVED` or `CONFIRMED`), and the crew's `estimated_liability_points` is recomputed. When the order is delivered, the window moves to `COMPLETED` (from either `RESERVED` or `CONFIRMED`).

### 3.4. Building Routes and Booking Dock Slots

A `DispatchPlanner` creates a **route** — a single crew's trip on a date — by supplying the origin `depot_id`, the running `team_id`, and the `service_date` (which must equal the service date of every window realized by the route's stops). A route starts in `status` `PLANNING`, with `committed_stops`, `committed_weight_lbs`, and `committed_volume_cuft` all at 0, `dock_ready` false, and its `dock_appointment_id` (the back-link to a booked appointment) null. Its `route_settlement_cents` (the crew payout) is null until the route closes.

The planner adds a scheduled order to a route as a **stop** by supplying the `order_id`, the `window_id` the stop realizes, and an optional visiting `sequence` (default 0, cosmetic — it does not affect settlement). Adding a stop advances the order `SCHEDULED → ROUTED` and is governed by a chain of checks. The order must be `SCHEDULED` and must not already have an active stop — a second stop for an already-routed order is rejected with `ERR_ORDER_ALREADY_ROUTED`. This already-routed check (the order's `active_stop_id` is not null) is evaluated before the generic `SCHEDULED`-state check, so an order that is already routed — and therefore no longer `SCHEDULED` — surfaces `ERR_ORDER_ALREADY_ROUTED` rather than `ERR_INVALID_STATE`, notwithstanding the general step-7-before-step-8 ordering of §2.9. The referenced `window_id` must be the order's `active_window_id`, and that window's `team_id` must equal the route's `team_id`, else `ERR_ROUTE_TEAM_MISMATCH`; the window's `service_date` must equal the route's `service_date`, else `ERR_WINDOW_ROUTE_DATE_MISMATCH`. The route itself must still be in `PLANNING`.

Capacity is then enforced against the crew's ceilings, each with its own error. Adding the stop must keep the route's `committed_stops` plus one at or below `max_daily_stops` (`ERR_ROUTE_STOPS_EXCEEDED`), its `committed_weight_lbs` plus the order's `weight_lbs` at or below `max_daily_weight_lbs` (`ERR_ROUTE_WEIGHT_EXCEEDED`), and its `committed_volume_cuft` plus the order's `volume_cuft` at or below `max_daily_volume_cuft` (`ERR_ROUTE_VOLUME_EXCEEDED`). On success, a `RouteStop` is created in `PLANNED` status referencing its `route_id`, the order's `order_id`, and the realizing `window_id`; the order's `active_stop_id` is set; the order moves to `ROUTED`; and the route's committed load is recomputed.

The route's committed aggregates are always the sum over the route's stops whose `status` is `PLANNED` or `COMPLETED` (stops that are `SKIPPED` are excluded): `committed_stops` is the count of those stops, `committed_weight_lbs` is the sum of their orders' `weight_lbs`, and `committed_volume_cuft` is the sum of their orders' `volume_cuft`.

A planner may un-route a stop before dispatch. Removing a stop is allowed only while the route is still in `PLANNING`; it drives the stop `PLANNED → SKIPPED`, returns the order to `SCHEDULED`, clears the order's `active_stop_id`, and recomputes the route's committed load so the released capacity becomes available again. A `SKIPPED` stop is terminal, as is a `COMPLETED` one.

Loading the truck requires a dock slot. A `DockCoordinator` books a **dock appointment** for a route by supplying the `dock_id`, the loading `appt_date`, and the interval `appt_start_min` and `appt_end_min` (the end must be greater than the start). The booking is refused if any already-booked appointment on the same dock and date sits within the dock's `buffer_min` gap of the requested interval — that is, if the clear gap between the new interval and an existing booked interval is smaller than `buffer_min`, the request is rejected with `ERR_DOCK_SLOT_CONFLICT`. A successful booking creates a `DockAppointment` in `BOOKED` status carrying its `dock_id` and the loaded `route_id`, sets the route's `dock_appointment_id`, and turns `dock_ready` true (the flag is true exactly when the route has a linked appointment whose `status` is `BOOKED`).

When a `DockCoordinator` closes a dock, its `status` moves `OPEN → CLOSED` (only from `OPEN`, else `ERR_INVALID_STATE`), and the closure cascades: every `BOOKED` appointment on that dock is moved to `RELEASED`, and for each such appointment the owning route's `dock_appointment_id` is cleared and its `dock_ready` set back to false. This is a two-hop cascade from the dock, through its appointments, to their routes.

### 3.5. Dispatch and Field Proof-of-Delivery

Once a route carries at least one committed stop and is dock-ready, the `DispatchPlanner` dispatches it. Dispatch moves the route `PLANNING → DISPATCHED` and is refused unless the route is in `PLANNING`, has `committed_stops` of at least 1, and has `dock_ready` true — a dispatch attempt without a booked dock appointment is rejected with `ERR_DOCK_APPOINTMENT_MISSING`. Dispatch cascades to the freight: each `PLANNED` stop's order advances `ROUTED → OUT_FOR_DELIVERY`.

In the field, the `DeliveryLead` records a **delivery attempt** against an order that is `OUT_FOR_DELIVERY`. The acting crew must be the route team of the order's active stop, else `ERR_STOP_ORDER_MISMATCH`. Each attempt states an `outcome` — one of `DELIVERED`, `REFUSED`, `CUSTOMER_UNAVAILABLE`, or `DAMAGED` — and may carry a free-text `refusal_reason`. The attempt records a `damage_severity` of `NONE` (the default), `MINOR`, or `MAJOR`, meaningful only for a damaged outcome. Every attempt is stamped with an `attempt_number`, the one-based ordinal for the order, equal to the order's prior failed-attempt count plus one. An attempt's `fee_delta_cents` records that attempt's contribution to the order's final fee and defaults to 0.

A **successful** attempt (`outcome` = `DELIVERED`) drives the order `OUT_FOR_DELIVERY → DELIVERED`. It states the `placement` actually achieved — `THRESHOLD`, `ROOM_OF_CHOICE`, or `WHITE_GLOVE` — which may downgrade the ordered level and which, when omitted, defaults to the order's `service_level`. It reports whether `assembly_completed` (default false) and the `debris_weight_lbs` of haul-away removed (default 0). Proof of delivery is mandatory: `signature_captured` must be true and `photo_count` must be at least 1, otherwise the attempt is rejected with `ERR_POD_REQUIRED`. Certification is re-checked at the door: if `placement` is `WHITE_GLOVE` the crew must be `white_glove_certified`, and if `assembly_completed` is true the crew must be `assembly_certified`, else `ERR_TEAM_NOT_CERTIFIED`. On success the system creates the attempt (with `attempt_number` equal to `reattempt_count` plus one), moves the order's active `RouteStop` `PLANNED → COMPLETED` (a completed stop keeps occupying route capacity), sets the order's `actual_placement_level` from `placement`, computes the order's `final_fee_cents` (see §3.7), moves the order to `DELIVERED`, moves the active window to `COMPLETED`, and clears both `active_window_id` and `active_stop_id`.

A **failed** attempt (`outcome` of `REFUSED`, `CUSTOMER_UNAVAILABLE`, or `DAMAGED`) drives the order `OUT_FOR_DELIVERY → REFUSED_RETRY` and triggers a three-hop cascade. First, the attempt is created and the order's `reattempt_count` increases by one. Second, the order's active `RouteStop` moves `PLANNED → SKIPPED`. Third, because a skipped stop no longer occupies capacity, the route's `committed_stops`, `committed_weight_lbs`, and `committed_volume_cuft` are recomputed so the freed capacity returns to the route. The active window is moved to `RELEASED`, and `active_window_id` and `active_stop_id` are cleared. When the failed outcome is specifically `DAMAGED`, the crew's realized-damage exposure is charged: `settled_liability_points` increases by 50 for a `MAJOR` severity or 20 for a `MINOR` severity. A refused order can then loop back into scheduling per §3.3, subject to the reattempt ceiling.

### 3.6. Settlement, Payout, and Reversal

Once an order is `DELIVERED`, its `final_fee_cents` has already been computed at the delivering attempt. The final fee mirrors the quote's structure but uses actuals. Determine the placement level from the delivering attempt's `placement`, falling back to the order's `service_level` when placement was omitted. Take the service base for that actual level (`THRESHOLD` 4000, `ROOM_OF_CHOICE` 7000, `WHITE_GLOVE` 12000 cents) plus the weight surcharge tier for the order's `weight_lbs` (the same 0 / 1500 / 3500 / 6000-cent bands as the quote), multiply that sum by 1.15 when the actual level is `WHITE_GLOVE` and by 1.00 otherwise, and round half up to a whole cent — this rounded core is computed once. Add the stair charge (the smaller of the order's `stair_flights` and 5, times 800 cents). Add 2500 cents for assembly only when the delivering attempt's `assembly_completed` is true. Add the disposal charge: when `debris_weight_lbs` is greater than 0, divide the debris weight by the 50-pound disposal unit, round that quotient **up** to the next whole unit, and multiply by 1000 cents per unit; when there is no debris the disposal charge is 0. Add the reattempt charge: 2000 cents for each prior failed attempt, that is, 2000 cents multiplied by the order's `reattempt_count`. The sum of core, stair, assembly, disposal, and reattempt charges is `final_fee_cents`. Relative to the quote, the final fee thus credits any placement downgrade, replaces the flat haul-away with the actual per-ticket disposal, bills assembly only if it was truly performed, and adds the accrued reattempt fees.

Settling a delivered order is a `DispatchPlanner` action that moves the order `DELIVERED → SETTLED` (rejected with `ERR_INVALID_STATE` unless the order is `DELIVERED`) and posts the forward money leg: the customer's `outstanding_balance_cents` increases by the order's `final_fee_cents`. A customer's `outstanding_balance_cents` is, by construction, the sum of `final_fee_cents` over that customer's settled orders. A settled delivery may be reversed: voiding it moves the order `SETTLED → RETURNED` (only from `SETTLED`) and posts the compensating money leg, decreasing the customer's `outstanding_balance_cents` by the same `final_fee_cents` so the pair nets to zero.

A route is closed by the `DispatchPlanner` after dispatch. Closing moves the route `DISPATCHED → CLOSED` and is refused unless the route is `DISPATCHED` (`ERR_INVALID_STATE`) and every one of its stops has reached a terminal state — that is, each `RouteStop` is `COMPLETED` or `SKIPPED`; a lingering `PLANNED` stop is rejected with `ERR_ROUTE_NOT_READY_TO_CLOSE`. On close, the crew payout `route_settlement_cents` is computed: for each `COMPLETED` stop, multiply that stop's order's `final_fee_cents` by the payout rate of 0.375 and round the result half up to a whole cent; then sum those per-stop rounded amounts. Rounding is applied to each completed stop's payout before summing, not to the aggregate. Skipped stops contribute nothing. Closing the route also completes its loading appointment: the route's `BOOKED` dock appointment moves `BOOKED → COMPLETED`.

### 3.7. Crew Liability Exposure

A crew carries two independent liability figures, both integer points, both reconciled automatically. The **provisional** figure, `estimated_liability_points`, is forward-looking risk from open white-glove work: it is the sum, over each of the crew's windows whose `status` is `RESERVED` or `CONFIRMED` and whose order's `service_level` is `WHITE_GLOVE`, of the order's `declared_value_cents` divided by 100000 and rounded **up** to the next whole point. It is recomputed every time one of the crew's windows enters or leaves the reserved/confirmed set — on reserve, on supersede, on release. The **settled** figure, `settled_liability_points`, is realized damage: it is the sum, over every `DAMAGED` attempt on the crew's orders, of a fixed penalty — 50 points for `MAJOR` severity and 20 points for `MINOR` severity. The provisional figure projects exposure from not-yet-delivered declared value; the settled figure ignores declared value and books fixed penalties for actual damage.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state-transition actions and settlement — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/depots` | Create a depot | PlatformAdmin |
| GET | `/depots` | List depots | Any role |
| POST | `/docks` | Create a loading dock at a depot | PlatformAdmin |
| GET | `/docks` | List docks | Any role |
| GET | `/docks/{dockId}` | Get a dock | Any role |
| POST | `/docks/{dockId}/close` | Close a dock; releases its booked appointments | DockCoordinator |
| POST | `/delivery-teams` | Create a two-person delivery crew | PlatformAdmin |
| GET | `/delivery-teams` | List teams | Any role |
| GET | `/delivery-teams/{teamId}` | Get a team | Any role |
| POST | `/customers` | Create a customer / delivery address | PlatformAdmin |
| GET | `/customers/{customerId}` | Get a customer | Any role |
| POST | `/delivery-orders` | Create a big & bulky delivery order | DispatchPlanner |
| GET | `/delivery-orders` | List orders | Any role |
| GET | `/delivery-orders/{orderId}` | Get an order | Any role |
| POST | `/delivery-orders/{orderId}/windows` | Reserve, reschedule, or supersede a delivery window | DispatchPlanner |
| GET | `/delivery-orders/{orderId}/attempts` | List an order's attempts | Any role |
| POST | `/delivery-orders/{orderId}/attempts` | Record a field delivery attempt | DeliveryLead |
| POST | `/delivery-orders/{orderId}/settle` | Settle a delivered order onto the customer ledger | DispatchPlanner |
| POST | `/delivery-orders/{orderId}/void-delivery` | Reverse a settled delivery | DispatchPlanner |
| POST | `/delivery-orders/{orderId}/cancel` | Cancel an order before delivery | DispatchPlanner |
| GET | `/delivery-windows` | List windows | Any role |
| GET | `/delivery-windows/{windowId}` | Get a delivery window | Any role |
| POST | `/delivery-windows/{windowId}/confirm` | Customer confirms a reserved window | Customer |
| POST | `/routes` | Create a route for a team on a service date | DispatchPlanner |
| GET | `/routes` | List routes | Any role |
| GET | `/routes/{routeId}` | Get a route | Any role |
| POST | `/routes/{routeId}/stops` | Add a scheduled order as a stop on the route | DispatchPlanner |
| GET | `/routes/{routeId}/stops` | List a route's stops | Any role |
| POST | `/routes/{routeId}/stops/{stopId}/remove` | Un-route a stop before dispatch | DispatchPlanner |
| POST | `/routes/{routeId}/dispatch` | Dispatch a route; cascades its orders out for delivery | DispatchPlanner |
| POST | `/routes/{routeId}/close` | Close a dispatched route; compute team payout | DispatchPlanner |
| GET | `/route-stops/{stopId}` | Get a single route stop | Any role |
| GET | `/route-stops` | List stops | Any role |
| POST | `/routes/{routeId}/dock-appointments` | Book a dock loading slot for a route | DockCoordinator |
| GET | `/dock-appointments/{apptId}` | Get a single dock appointment | Any role |
| GET | `/dock-appointments` | List dock appointments | Any role |
| GET | `/delivery-attempts/{attemptId}` | Get a single delivery attempt | Any role |
| GET | `/delivery-attempts` | List attempts | Any role |

*"Any role" denotes all five: `PlatformAdmin`, `DispatchPlanner`, `DockCoordinator`, `DeliveryLead`, and `Customer`.*

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_DEPOT_NOT_FOUND` | 404 |
| `ERR_DOCK_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_WINDOW_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_STOP_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ORDER_ALREADY_ROUTED` | 409 |
| `ERR_ROUTE_TEAM_MISMATCH` | 409 |
| `ERR_WINDOW_ROUTE_DATE_MISMATCH` | 409 |
| `ERR_REGION_MISMATCH` | 409 |
| `ERR_STOP_ORDER_MISMATCH` | 409 |
| `ERR_TEAM_OUT_OF_SERVICE` | 409 |
| `ERR_TEAM_NOT_CERTIFIED` | 409 |
| `ERR_POD_REQUIRED` | 422 |
| `ERR_TEAM_WINDOW_CONFLICT` | 409 |
| `ERR_DOCK_SLOT_CONFLICT` | 409 |
| `ERR_MAX_REATTEMPTS` | 409 |
| `ERR_DOCK_APPOINTMENT_MISSING` | 409 |
| `ERR_ROUTE_NOT_READY_TO_CLOSE` | 409 |
| `ERR_ROUTE_STOPS_EXCEEDED` | 409 |
| `ERR_ROUTE_WEIGHT_EXCEEDED` | 409 |
| `ERR_ROUTE_VOLUME_EXCEEDED` | 409 |
