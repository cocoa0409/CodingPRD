# Residential Yard Waste & Composting Program API — Product Requirements Document

## 1. Introduction

Municipal yard waste programs live and die by the calendar. Residents enroll for a season, set out carts on their route's weekday, and expect the city to absorb the autumn leaf surge and the January wave of holiday trees without collapsing under its own logistics. Behind the curb, composting facilities can only accept so many pounds per day, contaminated loads threaten worker safety, and every missed pickup becomes a customer-service dispute that someone must validate and someone else must pay for. This document specifies the API for a city's residential yard waste and composting program: enrollment and seasonal billing, cart delivery, route scheduling, curbside contamination inspection, surge collection events, facility receiving, and the compost giveback that returns processed material to residents.

The system serves eight distinct operational capacities, from the resident paying a seasonal fee to the field inspector tagging a contaminated setout to the billing clerk granting a service credit for a missed pickup. Because missed-pickup money and contamination strikes are the two places a municipal program loses public trust, the specification separates duties deliberately: the supervisor who validates a missed pickup may never approve the resulting credit, and a contamination suspension can only be cured by payment, never by appeal. All time-dependent behavior — season windows, booking windows, event-day status, automatic expiry — is driven by a logical clock under administrator control, never by the server's wall clock, so the entire program can be rehearsed, audited, and replayed deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the declared roles. The system recognizes exactly eight roles: `Anonymous`, `Resident`, `Driver`, `FieldInspector`, `RouteSupervisor`, `BillingClerk`, `ProgramAdmin`, and `OutreachCoordinator`. A request with a missing or unrecognized role header, or a missing user identifier, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`.

Role identity works as follows. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Household`; ownership checks on any resource that references a household compare the resource's `household_id` (or the household reached through its subscription or ticket) to `X-User-ID`, and a mismatch is rejected with `ERR_RESIDENT_NOT_OWNER`. A household registers itself through the public, anonymous signup, and the `id` returned by that registration becomes the `X-User-ID` the resident presents on all subsequent calls. When `X-User-Role` is `Anonymous`, `Driver`, `FieldInspector`, `RouteSupervisor`, `BillingClerk`, `ProgramAdmin`, or `OutreachCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `inspector_user_id` on a contamination inspection, as `missed_validated_by` on a pickup ticket, or as `validated_by` and `approved_by` on a service credit — but it never compares such an identifier to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A `limit` that is not an integer or falls outside 1–100, or an `offset` that is not a non-negative integer, is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp (`created_at`) in ascending order, with ties on `created_at` broken by `id` ascending; the same `created_at`-then-`id` ordering applies wherever this document orders by creation time, such as oldest-first credit consumption in §3.2 and cart-fee ordering in §3.3. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items in the returned page is still below `total_count`. List endpoints also accept optional exact-match query filters, applied before pagination: zones by `service_model` and `status`; households by `zone_id`; subscriptions by `household_id`, `status`, and `season_year`; carts by `household_id`, `subscription_id`, and `status`; routes by `zone_id`, `weekday`, and `status`; pickup tickets by `subscription_id`, `route_id`, `service_date`, and `status`; inspections by `pickup_ticket_id` and `result`; surge events by `zone_id`, `event_type`, and `status`; surge bookings by `surge_event_id`, `household_id`, and `status`; facilities by `status`; deliveries by `facility_id`, `route_id`, `delivery_date`, and `status`; giveback events by `zone_id` and `status`; claims by `giveback_event_id`, `household_id`, and `status`; credits by `household_id`, `subscription_id`, `missed_pickup_ticket_id`, and `status`; campaigns by `zone_id` and `status`.

### 2.4. The Logical Clock and Season-Derived Status

All date- and time-dependent behavior in the system is driven by a single logical clock, never by the server's wall clock. An administrator-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant in ISO 8601 UTC. Before any such call, the server's startup default is exactly `2026-05-01T00:00:00Z`. When this document refers to "the current clock date" it means the UTC calendar date of the logical clock. Timestamps stamped from the logical clock (a cart's `delivered_at`, a ticket's `completed_at`) are recorded in the clock's canonical form: ISO 8601 UTC at whole-second precision with a `Z` suffix.

Three resources derive their `status` from the logical clock on every read and write rather than storing it. A service zone reads `OPEN_ENROLLMENT` when the clock date falls before `season_start_date`, `IN_SEASON` from `season_start_date` through `season_end_date` inclusive, and `OFF_SEASON` once the clock date passes `season_end_date`. A surge event reads `SCHEDULED` before `booking_window_start`, `OPEN` from `booking_window_start` up to but not including `booking_window_end`, `CLOSED` from `booking_window_end` until the clock date passes the event's `service_date`, and `COMPLETED` thereafter. A compost giveback event reads `SCHEDULED` before its `event_date`, `OPEN` exactly on `event_date`, and `CLOSED` after it. All other clock-driven transitions — subscription expiry at season's end, route archival, cart retrieval finalization, no-show marking, campaign completion — are likewise re-evaluated lazily on subsequent access after the clock moves.

### 2.5. Common Resource Properties

Every top-level resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, assigned at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation of the resource.
- `version` — an integer that starts at 1 and increments by one on every mutation of the resource; at creation `updated_at` equals `created_at`.

Two resources are deliberately lighter: a contamination inspection and a service credit are immutable evidentiary records and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. Any mutation described in this document — including automatic, system-driven reconciliations such as a credit approval changing a household's balance or a booking changing an event's reserved count — updates the affected resource's `updated_at` and increments its `version`, unless the resource is one of the two just named.

### 2.6. Optimistic Concurrency Control

Two write operations guard against stale client state with optimistic concurrency control, and these are the only two endpoints that take a version field.

Creating a subscription requires the request to carry `expected_household_version` holding the client-observed `version` of the target household. If the household's current `version` has advanced since the client last read it — for example because another subscription for a different season year was just created, or a credit approval changed the household — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the household before enrolling.

Creating a surge booking requires the request to carry `expected_surge_event_version` holding the client-observed `version` of the surge event. Every booking creation or cancellation mutates the event's `reserved_slots` and `version`, so a stale expected version means the client decided from out-of-date capacity; the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and the client must re-read the event before booking. No other endpoint accepts or requires a version field.

### 2.7. Monetary Precision, Yield Ratios, and Rounding

All money in the system is integer cents. Fees, surcharges, credits, budgets, and balances are never fractional. Where a calculation derives an amount by division or proration — the mid-season subscription fee and the prorated missed-pickup credit — the result is floored to the next whole cent.

Compost volumes are the one exception to integer arithmetic. A household's compost entitlement is a number carried at exactly two decimal places, and the per-pickup conversion uses round-half-up at two decimal places before any summation. The canonical yield constant is one half: every pound of collected yard waste yields half a unit of compost feedstock, and twenty pounds of feedstock make one gallon of finished compost, so each collected pound corresponds to 0.025 gallons of entitlement. Inventory for a giveback event is instead expressed in whole gallons and is floored at derivation time. Route and facility weights are whole pounds throughout.

### 2.8. Validation Pipeline and Error Precedence

Every request is validated against an ordered pipeline, and the first failing check wins — a request that would fail two checks always surfaces the earlier one. The order is:

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is one of the eight declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The acting role appears in the endpoint's authorized list; otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Resident ownership.** On resident-scoped operations — paying, curing, or cancelling a subscription, creating a cart, reporting a missed pickup, creating or cancelling a surge booking, creating a compost claim, and reading one's own household, subscription, or cart — `X-User-ID` must equal the target resource's household; otherwise `ERR_RESIDENT_NOT_OWNER`.
4. **Path existence.** Path parameters are resolved to existing resources left to right. A missing household yields `ERR_HOUSEHOLD_NOT_FOUND`; a missing zone `ERR_ZONE_NOT_FOUND`; a missing subscription `ERR_SUBSCRIPTION_NOT_FOUND`; a missing pickup ticket `ERR_TICKET_NOT_FOUND`; a missing surge event `ERR_SURGE_EVENT_NOT_FOUND`; a missing facility `ERR_FACILITY_NOT_FOUND`; a missing giveback event `ERR_GIVEBACK_EVENT_NOT_FOUND`; any other missing resource (cart, route, booking, delivery, claim, credit, campaign, inspection) yields the generic `ERR_NOT_FOUND`.
5. **Request shape.** Required fields are present, types are correct, enum members are valid, and ranges hold: `gallons` at least 1, `quantity_bundles` between 1 and 10 inclusive, `weight_lbs` greater than 0, `window_end` later than `window_start`, `violation_codes` non-empty exactly when the inspection result is a tagged outcome, a ticket's `service_date` weekday matching the route's weekday, a route's effective window inside its zone's season window, and no unknown fields. Any violation yields `ERR_INVALID_REQUEST`.
6. **Body references.** Foreign keys in the request body resolve to existing resources, using the resource-specific 404 identifiers from step 4 where one is declared and `ERR_NOT_FOUND` otherwise.
7. **State preconditions.** The target resource is in a valid state for the operation: an `ACTIVE` subscription where one is required (`ERR_SUBSCRIPTION_NOT_ACTIVE`), a `SCHEDULED` ticket where one is required (`ERR_TICKET_NOT_SCHEDULED`), an `OPEN` surge event (`ERR_SURGE_EVENT_NOT_OPEN`), an `OPEN` giveback event (`ERR_GIVEBACK_EVENT_NOT_OPEN`), OCC version matches (`ERR_STALE_VERSION`), and every other wrong-from-state or immutable-field rejection under the generic `ERR_INVALID_STATE`.
8. **Load safety.** On facility receiving with an accept outcome, the load's contaminated item count must not exceed the facility's safety limit; otherwise `ERR_LOAD_SAFETY_LIMIT_EXCEEDED`.
9. **Uniqueness, capacity, and quota.** The family of conflict checks: one non-terminal subscription per household per season year (`ERR_DUPLICATE_SUBSCRIPTION`), the two-cart limit (`ERR_CART_LIMIT_EXCEEDED`), route window overlap (`ERR_ROUTE_WINDOW_OVERLAP`), route stop and tonnage capacity (`ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_ROUTE_TONNAGE_EXCEEDED`), one booking per household per service date (`ERR_SURGE_BOOKING_DAY_CONFLICT`), one inspection per ticket (`ERR_DUPLICATE_INSPECTION`), buffered bay-window overlap (`ERR_DELIVERY_WINDOW_OVERLAP`), facility daily capacity on accept (`ERR_FACILITY_CAPACITY_EXCEEDED`), the giveback quota ladder (`ERR_ENTITLEMENT_EXCEEDED`, then `ERR_PER_HOUSEHOLD_CAP_EXCEEDED`, then `ERR_INSUFFICIENT_INVENTORY`), and credit approver differing from validator (`ERR_SEGREGATION_OF_DUTIES`).
10. **Temporal windows.** Signup only while the zone is in `OPEN_ENROLLMENT` or `IN_SEASON` (`ERR_ENROLLMENT_WINDOW_CLOSED`), ticket service dates inside the season window (`ERR_TICKET_DATE_OUT_OF_SEASON`), and missed-pickup reports only on or after the service date (`ERR_TICKET_NOT_YET_DUE`).
11. **Referential state.** The route must be `PUBLISHED` at ticket creation, delivery scheduling, and delivery receiving (`ERR_ROUTE_NOT_PUBLISHED`), and the facility must be `OPEN` at delivery scheduling (`ERR_FACILITY_NOT_OPEN`).
12. **Fiscal gates, last.** Money checks run after everything else: a surge booking requires the household to carry no subscription with an outstanding balance (`ERR_OUTSTANDING_BALANCE`), and a campaign launch requires the computed spend to fit the budget (`ERR_CAMPAIGN_BUDGET_EXCEEDED`).

Two qualifications pin the evaluation order exactly. Because ownership is defined relative to a resolved target, the step 3 ownership check is evaluated only after the target resource has been resolved (step 4) and any request body parsed (step 5), so a missing target or a malformed body surfaces its own error before `ERR_RESIDENT_NOT_OWNER`. And on pickup-ticket creation the stop and tonnage capacity checks (step 9) run after the season-window (step 10) and route-published (step 11) checks; on facility-delivery scheduling the buffered-overlap check (step 9) likewise runs after the facility-open and route-published checks (step 11); and on a zone update the `OFF_SEASON` gate (step 7) is evaluated before the replacement window's shape (step 5).

### 2.9. Resource Addressing and Flat Topology

All resources are peers addressed by flat, top-level paths; there are no nested URLs. Relationships between resources are expressed by reference fields in request payloads — a subscription is created with a `household_id`, a ticket with a `subscription_id` and a `route_id` — never by path hierarchy. Where a path does contain an identifier, the existence checks of §2.8 step 4 apply in left-to-right order, and the first unresolvable identifier produces its resource-specific 404 before any later check runs.

### 2.10. Immediate Consistency and Cascading Side Effects

The consistency model is immediate: every side effect of an operation is visible in that operation's own response and in any subsequent read, with no asynchronous settlement. Cascades propagate across resources in hops — a single contamination inspection can reject a ticket, raise a subscription's strike count, suspend the subscription, skip its future tickets, and free route capacity in one request. Whenever such a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments, per §2.5. Derived aggregates — a household's `credit_balance_cents` and `compost_entitlement_gallons`, a subscription's fee components, an event's `reserved_slots` and `remaining_gallons`, a facility's `season_accepted_lbs` — are reconciled at the moment the underlying event occurs, not lazily on read.

## 3. Business Logic & Workflows

### 3.1. Zoning and Household Registration

The program is organized into **service zones**, each created by a `ProgramAdmin` with a display `name`, a `service_model` of either `OPT_IN` (residents pay per season) or `UNIVERSAL` (base service covered by utility billing), an inclusive season window bounded by `season_start_date` and `season_end_date`, a `base_seasonal_fee_cents` charged for opt-in seasons, a `universal_flat_credit_cents` used as the missed-pickup credit in universal zones, and optionally `max_strikes_per_season`, which defaults to 3 when omitted. The season window must be well-formed at creation: `season_end_date` on or after `season_start_date` (`ERR_INVALID_REQUEST`). A zone's `status` is derived from the logical clock as described in §2.4 — `OPEN_ENROLLMENT`, then `IN_SEASON`, then `OFF_SEASON`. Zone configuration is editable by a `ProgramAdmin`, but the season window fields `season_start_date` and `season_end_date` may only be changed while the zone is `OFF_SEASON`; attempting to move the window of an `OPEN_ENROLLMENT` or `IN_SEASON` zone is rejected with `ERR_INVALID_STATE`. Setting a new, future season window on an `OFF_SEASON` zone is exactly how the zone cycles back to `OPEN_ENROLLMENT` for the next year. Fee fields and `max_strikes_per_season` may be adjusted in any status, and every zone update increments the zone's `version` by one; the zone's `name` and `service_model` are immutable after creation. When a zone's season ends — the clock date passes `season_end_date` — every subscription of every household in that zone that is still `PENDING_PAYMENT`, `ACTIVE`, or `SUSPENDED` transitions to `EXPIRED`.

Residents self-register: an `Anonymous` caller provides an `address_line` and the `zone_id` of the zone the address belongs to, and the created household's `id` becomes that resident's `X-User-ID` for all future calls. Each household carries two derived figures that follow it through the season: `credit_balance_cents`, the sum of the household's granted service credits, and `compost_entitlement_gallons`, the household's season compost entitlement at two decimal places; both start at zero at registration. Households can be listed by `ProgramAdmin`, `BillingClerk`, and `RouteSupervisor` (with optional `zone_id` filtering), and read individually by staff or by the owning resident.

### 3.2. Season Signup and Subscription Billing

A resident enrolls their household for a season by creating a subscription with the `household_id`, a `season_year` label such as 2026, and the OCC field `expected_household_version` described in §2.6. Signup is only accepted while the household's zone is `OPEN_ENROLLMENT` or `IN_SEASON`; once the zone turns `OFF_SEASON`, enrollment attempts are rejected with `ERR_ENROLLMENT_WINDOW_CLOSED`. A household may hold at most one non-terminal subscription per `season_year` — a second signup while an earlier subscription for the same year is still `PENDING_PAYMENT`, `ACTIVE`, or `SUSPENDED` fails with `ERR_DUPLICATE_SUBSCRIPTION`. At creation the subscription pins a snapshot of the zone's `service_model`; later edits to the zone never retroactively change existing subscriptions. Creation also increments the household's `version` by one.

The subscription's bill has three components, all integer cents. The `base_fee_cents` depends on the pinned service model and on when the resident signs up. For a `UNIVERSAL` subscription the base fee is zero — base service is covered by utility billing — though cart fees and surcharges still apply. For an `OPT_IN` subscription, signing up on or before `season_start_date` bills the zone's full `base_seasonal_fee_cents`; signing up mid-season prorates: the season length in weeks is computed as the number of days from `season_start_date` to `season_end_date` (end minus start, not an inclusive day count) divided by seven and rounded up to a whole week, the remaining full weeks are computed as the days from the signup date to `season_end_date` divided by seven and rounded down, and the billed base fee is the zone's base fee multiplied by the remaining full weeks, divided by the season weeks, and floored to whole cents. The `cart_fees_cents` component is described in §3.3, and `surcharge_cents` accumulates a 2000-cent reinstatement surcharge on each contamination suspension (§3.5). The `total_due_cents` is the sum of these three components, and `paid_cents` tracks what has actually been collected in cash plus applied credits.

A subscription in a universal zone activates immediately at creation — its `status` starts at `ACTIVE`. An opt-in subscription starts at `PENDING_PAYMENT` and must be paid. The resident pays with an optional `use_credit_balance` flag. The request may also carry an optional `payment_cents` naming the cash portion; when omitted, the cash portion is exactly the balance remaining after any credit application, and when supplied it must equal that remainder exactly — an under- or over-payment is rejected with `ERR_INVALID_REQUEST`. When the flag is true, the household's `GRANTED` service credits are consumed oldest first by `created_at`, each moving to `APPLIED` and its amount added to the subscription's `paid_cents` and subtracted from the household's `credit_balance_cents`, until the amount due is covered; the cash portion of the payment covers whatever remains. A payment only succeeds when it covers the full outstanding balance — credits applied plus cash must bring `paid_cents` exactly to `total_due_cents` — at which point the subscription becomes `ACTIVE`. If nothing is owed, the payment attempt is rejected with `ERR_PAYMENT_NOT_REQUIRED`; paying a subscription that is not `PENDING_PAYMENT` or `ACTIVE` is rejected with `ERR_INVALID_STATE`. The same payment action serves as a top-up later in the season: when cart fees or a reinstatement surcharge push `total_due_cents` above `paid_cents` on an already-`ACTIVE` subscription, the resident pays the new outstanding amount in the same way, with the same oldest-first credit application, and the subscription remains `ACTIVE`. Attempting a top-up when there is no outstanding balance is likewise `ERR_PAYMENT_NOT_REQUIRED`.

A resident (or a `ProgramAdmin`) may cancel a subscription while it is `PENDING_PAYMENT`, `ACTIVE`, or `SUSPENDED`, moving it to `CANCELLED` and clearing `suspended_reason` to null. Cancellation cascades through the household's season: every surge booking of this household for events in the subscription's zone that is still `CONFIRMED` or `WAITLISTED` becomes `CANCELLED`; each freed confirmed slot is released and immediately re-offered to the waitlist per §3.7; every cart still `DELIVERED` moves to `RETRIEVAL_SCHEDULED`; and every pickup ticket still `SCHEDULED` for a `service_date` strictly after the current clock date moves to `SKIPPED`, freeing its route capacity. `CANCELLED` and `EXPIRED` are terminal.

### 3.3. Carts and Fee Accrual

A resident requests a cart for their household's subscription by providing `household_id`, `subscription_id`, and a `size_gallons` tier of `35`, `64`, or `96`. The server records the supplied `household_id` and `subscription_id` as given; it does not verify that the subscription belongs to the household. The subscription must be `ACTIVE`, otherwise the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`, and a household may hold at most two carts in `REQUESTED` or `DELIVERED` status at once — a third request fails with `ERR_CART_LIMIT_EXCEEDED`. A new cart starts at `REQUESTED`. A `RouteSupervisor` marks it delivered, which requires the cart to be `REQUESTED` (otherwise `ERR_INVALID_STATE`), stamps `delivered_at` with the logical clock, and moves the cart to `DELIVERED`.

Cart fees accrue per season per size: a 35-gallon cart carries no surcharge, a 64-gallon cart adds 1500 cents ($15.00), and a 96-gallon cart adds 3000 cents ($30.00), and each cart exposes this figure as its own `surcharge_cents`. The subscription's `cart_fees_cents` is recomputed whenever carts are requested, delivered, or retrieved: take the subscription's carts whose status is anything other than `RETRIEVED`, ordered by `created_at` ascending; sum each cart's size surcharge; then add an extra-cart fee of 2500 cents ($25.00) for every cart beyond the first — the first cart is exempt from the extra-cart fee. When the owning subscription is cancelled or expires, each `DELIVERED` cart moves to `RETRIEVAL_SCHEDULED`; once the clock date passes fourteen days beyond the zone's `season_end_date`, the cart moves to `RETRIEVED`, at which point it no longer counts toward `cart_fees_cents` and the subscription's fees are recomputed without it.

### 3.4. Routes, Scheduling, and Pickup Day Operations

A `ProgramAdmin` defines collection routes with a `zone_id`, a `weekday` (one of `MONDAY` through `SUNDAY`), an effective window from `effective_start_date` inclusive to `effective_end_date`, a `max_stops` cap on tickets per service date, and a `max_tonnage_lbs` cap on projected tonnage per service date. The effective window is half-open: it includes the start date and excludes the end date, and `effective_end_date` must not fall after the zone's `season_end_date` (a malformed window is `ERR_INVALID_REQUEST`). Two routes in the same zone on the same weekday may not have overlapping half-open windows while both are non-`ARCHIVED`; such a conflict is rejected with `ERR_ROUTE_WINDOW_OVERLAP`, though adjacency — one route's window ending exactly where the next begins — is allowed. A route starts `DRAFT`, is made bookable when a `ProgramAdmin` publishes it (`DRAFT` is required, otherwise `ERR_INVALID_STATE`), and, provided it is `PUBLISHED`, becomes `ARCHIVED` automatically once the clock date passes its `effective_end_date`, applied lazily on access — a `DRAFT` route is never auto-archived.

Scheduling a pickup is a `RouteSupervisor` action on a payload of `subscription_id`, `route_id`, and `service_date`. The subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), the route must be `PUBLISHED` (`ERR_ROUTE_NOT_PUBLISHED`), the `service_date` must fall inside the season window of the ticket household's zone — the zone reached through the subscription — inclusive on both ends (`ERR_TICKET_DATE_OUT_OF_SEASON`), and the weekday of the `service_date` must match the route's `weekday` (`ERR_INVALID_REQUEST`); the route's own zone is not cross-checked against the subscription's. Capacity is then enforced in two stages. First, count the route's existing tickets on the same `service_date` in any status other than `SKIPPED` — that is, tickets that are `SCHEDULED`, `COMPLETED`, `MISSED_REPORTED`, `MISSED`, or `REJECTED_CONTAMINATION`; if that count already equals or exceeds `max_stops`, the new ticket is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (a count one below the cap is allowed). Second, project the day's tonnage as the existing count plus the new ticket, multiplied by an average of 200 pounds per ticket; if that projection exceeds `max_tonnage_lbs`, the ticket is rejected with `ERR_ROUTE_TONNAGE_EXCEEDED` (a projection exactly equal to the cap is allowed). A created ticket starts at `SCHEDULED`.

On pickup day, a `Driver` completes a ticket by recording its scale `weight_lbs`, which must be greater than zero (`ERR_INVALID_REQUEST`); the ticket must be `SCHEDULED` (`ERR_TICKET_NOT_SCHEDULED`) and its subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`). Completion stamps `completed_at` with the logical clock and immediately recomputes the household's `compost_entitlement_gallons` (§3.8). A ticket whose subscription is suspended, cancelled, or expired while the ticket's `service_date` is strictly after the current clock date moves from `SCHEDULED` to `SKIPPED`, and its slot no longer counts against the route's stop or tonnage capacity.

### 3.5. Contamination Inspection and the Strike Regime

A `FieldInspector` records a curbside setout inspection against a pickup ticket by providing the `pickup_ticket_id`, a `result`, and `violation_codes`, with optional free-text `notes`; the acting inspector's `X-User-ID` is stored as `inspector_user_id`. The ticket must be `SCHEDULED` (`ERR_TICKET_NOT_SCHEDULED`), and a ticket may be inspected at most once — a second inspection attempt fails with `ERR_DUPLICATE_INSPECTION`. The `result` is one of `PASSED`, `TAGGED_WARNING`, or `TAGGED_REJECTED`. A `PASSED` result requires `violation_codes` to be empty; either tagged result requires a non-empty list drawn from `PLASTIC_BAG`, `FOOD_WASTE`, `DIRT_ROCK`, `HAZARDOUS`, and `NON_YARD_MATERIAL`; violating this pairing is `ERR_INVALID_REQUEST`. A `PASSED` or `TAGGED_WARNING` inspection simply records the finding without changing the ticket.

A `TAGGED_REJECTED` inspection is consequential. The ticket moves from `SCHEDULED` to `REJECTED_CONTAMINATION`, and the subscription's `strikes_this_season` rises by one. `strikes_this_season` is a stored counter carried on the subscription, never recomputed from the inspection log: it starts at zero when the subscription is created, each `TAGGED_REJECTED` inspection adds exactly one to it, `PASSED` and `TAGGED_WARNING` results never increment it, and only a successful cure payment returns it to zero — so strikes recorded before a cure do not count toward the next suspension. When the strike count reaches the zone's `max_strikes_per_season` while the subscription is `ACTIVE`, the strike regime fires: reaching the threshold exactly is sufficient (one strike below it is not). The subscription moves to `SUSPENDED`, a 2000-cent reinstatement surcharge is added to `surcharge_cents`, `suspended_reason` is set to `CONTAMINATION_STRIKES`, and every one of that subscription's tickets still `SCHEDULED` for a `service_date` strictly after the current clock date moves to `SKIPPED`, freeing the corresponding route capacity.

The way back is a cure payment by the resident, supplying `payment_cents`. The subscription must be `SUSPENDED` (otherwise `ERR_INVALID_STATE`), and the payment must be at least the outstanding balance — `total_due_cents` minus `paid_cents`, a shortfall rejected with `ERR_INVALID_REQUEST` — which by construction covers the reinstatement surcharge and any unpaid cart fees. A successful cure resets `strikes_this_season` to zero, clears `suspended_reason` to null, adds `payment_cents` to `paid_cents`, and returns the subscription to `ACTIVE`. The cycle from `ACTIVE` to `SUSPENDED` and back is repeatable within a season.

### 3.6. Missed Pickups and the Service Credit Ledger

When a crew fails to service a setout, the resident who owns the ticket's household reports the miss. The ticket must be `SCHEDULED` (`ERR_TICKET_NOT_SCHEDULED`), the report may only be filed on or after the ticket's `service_date` — reporting before the scheduled day is rejected with `ERR_TICKET_NOT_YET_DUE` — and the acting resident must own the household (`ERR_RESIDENT_NOT_OWNER`). The ticket moves to `MISSED_REPORTED` and remembers the reporting household in `missed_reported_by`.

Validation of the report belongs to a `RouteSupervisor`, who submits a `validated` flag. The ticket must be `MISSED_REPORTED` (otherwise `ERR_INVALID_STATE`). When `validated` is false, the report is invalidated: `missed_reported_by` is cleared to null and the ticket loops back to `SCHEDULED` — this cycle may repeat. When `validated` is true, the ticket becomes `MISSED`, the supervisor's `X-User-ID` is recorded as `missed_validated_by`, and the system creates a service credit in `PENDING_APPROVAL` status, stamped with the supervisor's `X-User-ID` as `validated_by` and linked back through `household_id`, `subscription_id`, and `missed_pickup_ticket_id`. The credit's `amount_cents` depends on the subscription's pinned service model: for an `OPT_IN` subscription it is the subscription's `base_fee_cents` divided by the season length in weeks (computed as in §3.2: season window days divided by seven, rounded up), floored to whole cents — so the credit reflects the fee actually charged, prorated season included; for a `UNIVERSAL` subscription it is simply the zone's `universal_flat_credit_cents`, independent of any fee.

Approval is a separate hand. A `BillingClerk` approves a credit that is `PENDING_APPROVAL` (otherwise `ERR_INVALID_STATE`), and segregation of duties is enforced: the approving clerk's `X-User-ID` must differ from the credit's `validated_by`, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval records the clerk in `approved_by`, moves the credit to `GRANTED`, adds `amount_cents` to the household's `credit_balance_cents`, and increments the household's `version` by one. A household's `credit_balance_cents` is always exactly the sum of `amount_cents` over its `GRANTED` credits — `PENDING_APPROVAL`, `APPLIED`, and `VOIDED` credits never count. From `GRANTED`, a credit has two exits. It is consumed automatically when the resident pays a subscription with `use_credit_balance` set true, moving to `APPLIED` as described in §3.2, with the household's balance decremented and its `version` incremented per applied credit. Or a `BillingClerk` may void a `GRANTED` credit (any other status is `ERR_INVALID_STATE`), which moves it to `VOIDED`, subtracts `amount_cents` from the household's balance, and increments the household's `version` — so approving and then voiding the same credit leaves the balance unchanged. `APPLIED` and `VOIDED` are terminal.

### 3.7. Surge Collection Events and Slot Allocation

For seasonal peaks a `ProgramAdmin` creates a surge event: a `zone_id`, an `event_type` of `LEAF_SURGE` or `HOLIDAY_TREE`, the `service_date` of the collection, a booking window from `booking_window_start` inclusive to `booking_window_end` exclusive, and the total `capacity_slots`. The booking window must be well-formed — `booking_window_end` strictly later than `booking_window_start` — and `capacity_slots` must be non-negative (`ERR_INVALID_REQUEST`). The event's `status` is clock-derived per §2.4 — `SCHEDULED`, `OPEN`, `CLOSED`, then `COMPLETED` — and `reserved_slots` tracks how many slots are currently held by `CONFIRMED` bookings, maintaining the invariant that `capacity_slots` always equals `reserved_slots` plus the remaining available slots. When the event completes — the clock date passes the `service_date` — every booking still `CONFIRMED` is marked `NO_SHOW`.

A resident books a slot for their household with `surge_event_id`, `household_id`, a `quantity_bundles` of 1 to 10 (bags for leaf events, trees for holiday events), and the OCC field `expected_surge_event_version` (§2.6). Booking requires the event to be `OPEN` (`ERR_SURGE_EVENT_NOT_OPEN`), the household to hold an `ACTIVE` subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and no same-day conflict: a household already holding a `CONFIRMED` or `WAITLISTED` booking for the same `service_date` is rejected with `ERR_SURGE_BOOKING_DAY_CONFLICT`. The fiscal gate runs last per §2.8: if the household carries any subscription whose `total_due_cents` exceeds its `paid_cents`, the booking is rejected with `ERR_OUTSTANDING_BALANCE`. Slot allocation itself is never an error: if `reserved_slots` is still below `capacity_slots`, the booking is created `CONFIRMED` and `reserved_slots` rises by one; if the event is full, the booking is created `WAITLISTED`. Either way the event's `version` increments by one.

A resident may cancel their own booking while it is `CONFIRMED` or `WAITLISTED` (otherwise `ERR_INVALID_STATE`; a non-owner is rejected with `ERR_RESIDENT_NOT_OWNER`). Cancelling a `WAITLISTED` booking simply increments the event's `version`. Cancelling a `CONFIRMED` booking releases the slot — `reserved_slots` drops by one — and the freed capacity immediately promotes from the waitlist: among the event's `WAITLISTED` bookings, the earliest created wins, with ties broken by smaller `quantity_bundles`, and promotion continues while capacity remains and waitlisted candidates exist; each promotion sets the booking `CONFIRMED` and raises `reserved_slots` by one. The event's `version` increments by one on the cancellation. The same release-and-promote machinery fires when a subscription cancellation (§3.2) cancels the household's surge bookings in that zone.

### 3.8. Facility Receiving, Compost Inventory, and the Giveback Program

A `ProgramAdmin` registers a processing facility with a `name`, a `daily_receiving_capacity_lbs` ceiling on accepted gross pounds per calendar day, and a `safety_contamination_item_limit` on contaminated items tolerated in an accepted load. A facility starts `OPEN` and may be toggled to `CLOSED` and back by a `ProgramAdmin`; each toggle requires the opposite current state (otherwise `ERR_INVALID_STATE`), and `daily_receiving_capacity_lbs` and `safety_contamination_item_limit` may be adjusted in either status, every update incrementing the facility's `version`; the facility's `name` is immutable after creation. The facility's `season_accepted_lbs` accumulates the accepted weight of every accepted delivery.

A `RouteSupervisor` schedules a bay appointment with `facility_id`, `route_id` (which pins the load's zone attribution), `delivery_date`, and a `window_start` and `window_end` that must both fall on `delivery_date` with `window_end` later than `window_start` (`ERR_INVALID_REQUEST`). The facility must be `OPEN` (`ERR_FACILITY_NOT_OPEN`) and the route must be `PUBLISHED` (`ERR_ROUTE_NOT_PUBLISHED`). Bay scheduling uses a buffered-overlap rule: each appointment's window is expanded by thirty minutes on both sides, and if that expanded window overlaps another delivery in any status other than `REJECTED` at the same facility on the same date, the new appointment is rejected with `ERR_DELIVERY_WINDOW_OVERLAP`; appointments whose buffers merely touch at the edges are allowed. A scheduled delivery starts at `SCHEDULED`.

Receiving is the supervisor's weigh-in, submitted with an `outcome` of `ACCEPT` or `REJECT`, the scale `gross_weight_lbs`, and a `contaminated_item_count` (both non-negative integers). The delivery must be `SCHEDULED` (otherwise `ERR_INVALID_STATE`). An accept outcome then faces three gates in this order: the safety gate rejects with `ERR_LOAD_SAFETY_LIMIT_EXCEEDED` when `contaminated_item_count` exceeds the facility's `safety_contamination_item_limit`; the capacity gate rejects with `ERR_FACILITY_CAPACITY_EXCEEDED` when the facility's already-accepted pounds on that `delivery_date` plus `gross_weight_lbs` would exceed `daily_receiving_capacity_lbs`; and the referential gate rejects with `ERR_ROUTE_NOT_PUBLISHED` if the origin route is no longer `PUBLISHED` at receive time. An accepted load sets `accepted_weight_lbs` equal to `gross_weight_lbs` and adds the gross weight to the facility's `season_accepted_lbs`. A reject outcome is the operator's prerogative and bypasses all three gates — no load enters the facility, `accepted_weight_lbs` is set to 0, and the delivery is `REJECTED`.

Households earn compost through completed pickups. A household's `compost_entitlement_gallons` is recomputed whenever one of its tickets completes: for each `COMPLETED` ticket across all of the household's subscriptions, regardless of season — `REJECTED_CONTAMINATION`, `SKIPPED`, and `MISSED` tickets are excluded — convert that ticket's `weight_lbs` to gallons at half yield and twenty pounds per gallon (0.025 gallons per pound), round the per-pickup figure half-up to two decimal places, and then sum the rounded figures. The rounding order is pinned: each pickup is rounded first and the rounded values are summed. The alternative order — summing all pounds first and converting once — is explicitly forbidden because it diverges: 133 pounds plus 67 pounds yields 5.01 gallons under the pinned order (3.33 plus 1.68) but 5.00 under the forbidden one. The entitlement is always carried at two decimal places.

The giveback closes the loop. A `ProgramAdmin` creates a giveback event with a `zone_id`, an `event_date`, and a `per_household_cap_gallons`, which must be non-negative (`ERR_INVALID_REQUEST`). At creation, the event's `initial_inventory_gallons` is computed once: sum `accepted_weight_lbs` over every `ACCEPTED` facility delivery whose route belongs to the event's zone and whose `delivery_date` falls inside the zone's season window, convert at the same half yield and twenty pounds per gallon, and floor the result to whole gallons. The event's `status` is clock-derived — `SCHEDULED` before the date, `OPEN` on `event_date` itself, `CLOSED` after — and `remaining_gallons` starts at the initial inventory and falls as claims are fulfilled.

A resident claims compost for their household with `giveback_event_id`, `household_id`, and a whole-number `gallons` of at least 1. The event must be `OPEN` — claims are only possible on the event date — otherwise `ERR_GIVEBACK_EVENT_NOT_OPEN`. Three quota checks then run in a fixed order: first entitlement, rejecting with `ERR_ENTITLEMENT_EXCEEDED` when the requested gallons exceed the household's remaining entitlement — its `compost_entitlement_gallons` minus the gallons of its `FULFILLED` claims across all giveback events; second the per-household cap, rejecting with `ERR_PER_HOUSEHOLD_CAP_EXCEEDED` when the request would push the household's cumulative `FULFILLED` claimed gallons at this event (`VOIDED` claims do not count) above `per_household_cap_gallons`; third inventory, rejecting with `ERR_INSUFFICIENT_INVENTORY` when the request exceeds the event's `remaining_gallons`. A successful claim is created already `FULFILLED`, deducts its `gallons` from `remaining_gallons`, and records the household's entitlement at claim time in `entitlement_snapshot_gallons` at two decimal places. A `BillingClerk` may void a `FULFILLED` claim (otherwise `ERR_INVALID_STATE`): the claim becomes `VOIDED`, its gallons are added back to the event's `remaining_gallons`, and the household's entitlement consumption is released.

### 3.9. Outreach Campaigns

Education and outreach are run by an `OutreachCoordinator`, segregated from program administration. A campaign is created in `DRAFT` with an optional `zone_id` (a null zone means the campaign is citywide), a `channel` of `MAIL`, `DOOR_TAG`, `EMAIL`, or `SOCIAL`, a `topic` of `ACCEPTABLE_MATERIALS`, `SEASON_START`, `CONTAMINATION_PREVENTION`, or `COMPOST_GIVEBACK`, a `budget_cents` ceiling, a planned `audience_size`, a `cost_per_impression_cents`, and an `end_date`. While `DRAFT`, the budget fields — `budget_cents`, `audience_size`, `cost_per_impression_cents`, and `end_date` — remain editable; once launched, non-status fields are immutable and edits to them are rejected with `ERR_INVALID_STATE`.

Launching a `DRAFT` campaign (any other status is `ERR_INVALID_STATE`) computes the spend as `audience_size` multiplied by `cost_per_impression_cents` and records it as `spent_cents`; the fiscal gate requires this spend to fit within `budget_cents` — a spend exactly equal to the budget is allowed, one cent over is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`. An `ACTIVE` campaign may be paused and resumed by status updates (`ACTIVE` to `PAUSED` and back, each requiring the matching current state under `ERR_INVALID_STATE`), and a campaign in `DRAFT`, `ACTIVE`, or `PAUSED` may be cancelled outright to `CANCELLED`. When the clock date passes `end_date`, a campaign in `ACTIVE` or `PAUSED` is marked `COMPLETED` automatically. Every campaign update increments the campaign's `version`; `COMPLETED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — payments, cancellations, state transitions, receiving, approvals, configuration updates — return `200 OK`. All responses use the envelope of §2.2, and list endpoints paginate per §2.3. A request to an undefined path, or to a defined path with an unsupported method, is rejected with `ERR_NOT_FOUND` (404).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-zones` | Create a service zone | ProgramAdmin |
| GET | `/service-zones` | List zones | Anonymous, Resident, Driver, FieldInspector, RouteSupervisor, BillingClerk, ProgramAdmin, OutreachCoordinator |
| GET | `/service-zones/{id}` | Get one zone | Anonymous, Resident, Driver, FieldInspector, RouteSupervisor, BillingClerk, ProgramAdmin, OutreachCoordinator |
| PATCH | `/service-zones/{id}` | Update zone fee, window, or strike configuration; season window only while `OFF_SEASON` | ProgramAdmin |
| POST | `/households` | Register a household; the returned id becomes the resident's `X-User-ID` | Anonymous |
| GET | `/households` | List households | ProgramAdmin, BillingClerk, RouteSupervisor |
| GET | `/households/{id}` | Get one household (residents: own only) | Resident, ProgramAdmin, BillingClerk, RouteSupervisor |
| POST | `/subscriptions` | Season signup; computes the seasonal fee; universal subscriptions auto-activate, opt-in start `PENDING_PAYMENT` | Resident |
| GET | `/subscriptions` | List subscriptions | Resident, ProgramAdmin, BillingClerk, RouteSupervisor |
| GET | `/subscriptions/{id}` | Get one subscription | Resident, ProgramAdmin, BillingClerk, RouteSupervisor |
| POST | `/subscriptions/{id}/pay` | Pay the full outstanding due (cash plus optional credit balance); activates when covered | Resident |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription; cascades to bookings, carts, and future tickets | Resident, ProgramAdmin |
| POST | `/subscriptions/{id}/cure` | Cure a contamination suspension by paying the outstanding balance including the reinstatement surcharge | Resident |
| POST | `/carts` | Request a cart for a subscription (at most two active per household) | Resident |
| GET | `/carts` | List carts | Resident, ProgramAdmin, RouteSupervisor |
| GET | `/carts/{id}` | Get one cart | Resident, ProgramAdmin, RouteSupervisor |
| POST | `/carts/{id}/deliver` | Mark a cart delivered | RouteSupervisor |
| POST | `/routes` | Create a route; rejects half-open window overlap for the same zone and weekday | ProgramAdmin |
| GET | `/routes` | List routes | ProgramAdmin, RouteSupervisor, Resident, Driver, FieldInspector, BillingClerk, OutreachCoordinator |
| GET | `/routes/{id}` | Get one route | ProgramAdmin, RouteSupervisor, Resident, Driver, FieldInspector, BillingClerk, OutreachCoordinator |
| POST | `/routes/{id}/publish` | Publish a `DRAFT` route | ProgramAdmin |
| POST | `/pickup-tickets` | Schedule a pickup; enforces season window, published route, and stop/tonnage capacity | RouteSupervisor |
| GET | `/pickup-tickets` | List pickup tickets | Resident, Driver, FieldInspector, RouteSupervisor, ProgramAdmin, BillingClerk |
| GET | `/pickup-tickets/{id}` | Get one ticket | Resident, Driver, FieldInspector, RouteSupervisor, ProgramAdmin, BillingClerk |
| POST | `/pickup-tickets/{id}/complete` | Record a completed pickup with scale weight | Driver |
| POST | `/pickup-tickets/{id}/report-missed` | Resident reports a missed pickup on or after the service date | Resident |
| POST | `/pickup-tickets/{id}/validate-missed` | Supervisor validates (creates a pending service credit) or invalidates (ticket returns to `SCHEDULED`) | RouteSupervisor |
| POST | `/contamination-inspections` | Record a setout inspection; a rejected tag rejects the ticket, increments strikes, and may suspend the subscription | FieldInspector |
| GET | `/contamination-inspections` | List inspections | FieldInspector, RouteSupervisor, ProgramAdmin, Resident, BillingClerk |
| GET | `/contamination-inspections/{id}` | Get one inspection | FieldInspector, RouteSupervisor, ProgramAdmin, Resident, BillingClerk |
| POST | `/surge-events` | Create a seasonal surge collection event (leaf or holiday tree) | ProgramAdmin |
| GET | `/surge-events` | List surge events | Anonymous, Resident, Driver, FieldInspector, RouteSupervisor, BillingClerk, ProgramAdmin, OutreachCoordinator |
| GET | `/surge-events/{id}` | Get one surge event | Anonymous, Resident, Driver, FieldInspector, RouteSupervisor, BillingClerk, ProgramAdmin, OutreachCoordinator |
| POST | `/surge-bookings` | Book a surge slot; confirmed while capacity remains, waitlisted otherwise | Resident |
| GET | `/surge-bookings` | List surge bookings | Resident, ProgramAdmin, RouteSupervisor |
| GET | `/surge-bookings/{id}` | Get one surge booking | Resident, ProgramAdmin, RouteSupervisor |
| POST | `/surge-bookings/{id}/cancel` | Cancel a booking; releases the slot and promotes the earliest waitlisted booking | Resident |
| POST | `/facilities` | Register a composting facility | ProgramAdmin |
| GET | `/facilities` | List facilities | ProgramAdmin, RouteSupervisor |
| GET | `/facilities/{id}` | Get one facility | ProgramAdmin, RouteSupervisor |
| PATCH | `/facilities/{id}` | Toggle open/closed or adjust capacity and safety limits | ProgramAdmin |
| POST | `/facility-deliveries` | Schedule a bay appointment; rejects buffered-window overlap at the same facility and date | RouteSupervisor |
| GET | `/facility-deliveries` | List deliveries | RouteSupervisor, ProgramAdmin |
| GET | `/facility-deliveries/{id}` | Get one delivery | RouteSupervisor, ProgramAdmin |
| POST | `/facility-deliveries/{id}/receive` | Weigh and accept or reject a load; safety, capacity, and route-published checks on accept | RouteSupervisor |
| POST | `/giveback-events` | Create a compost giveback event; initial inventory derived from accepted zone tonnage | ProgramAdmin |
| GET | `/giveback-events` | List giveback events | Resident, ProgramAdmin, BillingClerk, RouteSupervisor |
| GET | `/giveback-events/{id}` | Get one giveback event | Resident, ProgramAdmin, BillingClerk, RouteSupervisor |
| POST | `/compost-claims` | Claim giveback compost; entitlement, per-household cap, and inventory enforced in that order | Resident |
| GET | `/compost-claims` | List claims | Resident, BillingClerk, ProgramAdmin |
| GET | `/compost-claims/{id}` | Get one claim | Resident, BillingClerk, ProgramAdmin |
| POST | `/compost-claims/{id}/void` | Void a claim; restores event inventory and household entitlement | BillingClerk |
| GET | `/service-credits` | List credits | Resident, BillingClerk, RouteSupervisor, ProgramAdmin |
| GET | `/service-credits/{id}` | Get one credit | Resident, BillingClerk, RouteSupervisor, ProgramAdmin |
| POST | `/service-credits/{id}/approve` | Grant a validated credit; approver must differ from validator | BillingClerk |
| POST | `/service-credits/{id}/void` | Void a granted credit; decrements the household balance | BillingClerk |
| POST | `/outreach-campaigns` | Create an outreach campaign in `DRAFT` | OutreachCoordinator |
| GET | `/outreach-campaigns` | List campaigns | OutreachCoordinator, ProgramAdmin |
| GET | `/outreach-campaigns/{id}` | Get one campaign | OutreachCoordinator, ProgramAdmin |
| POST | `/outreach-campaigns/{id}/launch` | Launch a `DRAFT` campaign; computes spend and enforces the budget | OutreachCoordinator |
| PATCH | `/outreach-campaigns/{id}` | Pause, resume, or cancel via status; budget fields editable only in `DRAFT` | OutreachCoordinator |
| POST | `/_clock/set_current_utc` | Set the logical clock; startup default is exactly 2026-05-01T00:00:00Z | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_RESIDENT_NOT_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_SURGE_EVENT_NOT_FOUND` | 404 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_GIVEBACK_EVENT_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_TICKET_NOT_SCHEDULED` | 409 |
| `ERR_PAYMENT_NOT_REQUIRED` | 409 |
| `ERR_SURGE_EVENT_NOT_OPEN` | 409 |
| `ERR_GIVEBACK_EVENT_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 |
| `ERR_CART_LIMIT_EXCEEDED` | 409 |
| `ERR_ROUTE_WINDOW_OVERLAP` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_ROUTE_TONNAGE_EXCEEDED` | 409 |
| `ERR_SURGE_BOOKING_DAY_CONFLICT` | 409 |
| `ERR_DUPLICATE_INSPECTION` | 409 |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 409 |
| `ERR_FACILITY_NOT_OPEN` | 409 |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_ROUTE_NOT_PUBLISHED` | 409 |
| `ERR_LOAD_SAFETY_LIMIT_EXCEEDED` | 422 |
| `ERR_ENROLLMENT_WINDOW_CLOSED` | 422 |
| `ERR_TICKET_DATE_OUT_OF_SEASON` | 422 |
| `ERR_TICKET_NOT_YET_DUE` | 422 |
| `ERR_ENTITLEMENT_EXCEEDED` | 422 |
| `ERR_PER_HOUSEHOLD_CAP_EXCEEDED` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 402 |
| `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 402 |
