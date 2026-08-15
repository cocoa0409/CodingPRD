# Mobile Car Wash & Fleet Washing Service API — Product Requirements Document

## 1. Introduction

Operating a mobile wash business means bringing the wash bay to the customer's pavement. Crews in equipment vans criss-cross a service territory to clean everything from a single retail sedan in a driveway to forty-vehicle commercial fleets on corporate lots, carrying their own fresh water and, where local ordinances demand it, containment and reclamation gear. The commercial reality is equally varied: retail accounts book one-off washes and recurring subscriptions, while fleet accounts sign contracts with per-class rate cards, monthly billing minimums, and loyalty credits. Weather, water-discharge regulation, and a quality guarantee that promises re-washes and damage restitution all impose hard operational constraints that the platform must enforce, not merely record.

This document specifies the API for that operating platform. It governs the book of business (customers, sites, vehicles, vans, technicians), commercial agreements (fleet contracts and subscriptions), the wash-order lifecycle from booking through completion, daily route and stop planning under van water and vehicle capacity limits, weather policy evaluation with freeze cascades and rescheduling windows, water-compliance incident handling, quality audits, damage claims with segregation of duties, and fleet invoicing with minimums and claim credits. All temporal rules are evaluated against a controllable logical clock so that windows, deadlines, and scheduled sweeps behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and invariants that apply to every endpoint of the API, which is mounted under the `/fleet-wash` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. The API recognizes exactly six roles: `PlatformAdmin`, `Dispatcher`, `Customer`, `Technician`, `QualityAuditor`, and `ComplianceOfficer`. A request whose `X-User-Role` header is missing or does not name one of these six roles is rejected with `ERR_UNAUTHENTICATED`. When the role is valid but not permitted for the endpoint — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer — a site, a vehicle, a subscription, a wash order, a damage claim, or the invoice of the customer's own fleet contract — compare the resource's customer foreign key to `X-User-ID`. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting Technician; crew checks compare it to a route's `lead_technician_id` or to a report's `technician_id`. When `X-User-Role` is `PlatformAdmin`, `Dispatcher`, `QualityAuditor`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `auditor_id` on a QualityAudit, or as `reviewed_by` and `paid_by` on a DamageClaim) but does not compare it to any entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. When omitted, `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — Customer, Site, Vehicle, Van, Technician, FleetContract, Subscription, WashOrder, Route, RouteStop, InspectionReport, DamageClaim, ComplianceIncident, and Invoice — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource.
- `version` (integer): starts at 1 when the resource is created and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.7).

The QualityAudit resource is the single exception to this convention: it carries only `id` and `created_at`; both `updated_at` and `version` are absent.

All datetime fields the API returns — for example `held_at`, `completed_at`, `filed_at`, `planned_start_at`, and `planned_end_at` — are serialized as ISO 8601 UTC with three fractional digits. Calendar dates use the YYYY-MM-DD form, and billing periods use YYYY-MM.

### 2.5. The Logical Clock

The server evaluates every deadline, window, and sweep against a logical clock, never against wall-clock time. Before any call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time thereafter. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every time-delta rule described in §3 — the 72-hour claim and rewash windows, the fourteen-day weather reschedule window, the trailing 365-day pause accounting window, and the daily sweeps — reads this clock.

### 2.6. Validation Cascade and Check Ordering

Requests are validated in a fixed cascade, and the cascade's ordering is part of the contract: a request that would fail several checks is rejected with the error from the earliest check. The order is:

1. Authentication — the `X-User-Role` header is present and names a declared role, else `ERR_UNAUTHENTICATED`.
2. Authorization and ownership — the role is permitted for the endpoint and the ownership checks pass (a Customer acts only on its own resources; a Technician acts only as route lead or report filer), else `ERR_FORBIDDEN`.
3. Existence — path identifiers and body foreign-key references exist, validated left to right, else `ERR_NOT_FOUND`.
4. Body shape — required fields are present, and types, enum members, and ranges are valid (dates parse, a window's end is strictly after its start, gallons are positive, audit scores lie between 0 and 20 inclusive), else `ERR_VALIDATION`.
5. Optimistic concurrency — any required `expected_..._version` field matches the parent entity's current `version`, else `ERR_STALE_VERSION` (§2.7).
6. State eligibility — the target entity is in a valid from-state for the requested transition, else `ERR_INVALID_STATE`; route-stop mutations additionally require the route to be in a state that accepts them, else `ERR_ROUTE_LOCKED`. At this shared tier, on the stop-add and stop-removal operations the path resource's state (the Route) is checked before the referenced wash order's state.
7. Safety rules, in order: containment adequacy (`ERR_CONTAINMENT_REQUIRED`), then the discharge cap (`ERR_DISCHARGE_CAP_EXCEEDED`), then reclaim certification (`ERR_CERTIFICATION_REQUIRED`).
8. Temporal rules, in order: site service-window conflict (`ERR_SITE_WINDOW_CONFLICT`), technician travel buffer (`ERR_TECHNICIAN_SCHEDULE_CONFLICT`), damage-claim window (`ERR_CLAIM_WINDOW_EXPIRED`), rewash window (`ERR_REWASH_WINDOW_EXPIRED`), weather reschedule window (`ERR_RESCHEDULE_WINDOW_EXPIRED`).
9. Capacity and consistency constraints, in order: route water capacity (`ERR_ROUTE_WATER_CAPACITY_EXCEEDED`), route vehicle capacity (`ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED`), van route conflicts (`ERR_VAN_ROUTE_CONFLICT`), lead technician active (`ERR_TECHNICIAN_NOT_ACTIVE`), duplicate subscription (`ERR_DUPLICATE_SUBSCRIPTION`), pause count and minimum length (`ERR_PAUSE_LIMIT_EXCEEDED`), pause day budget (`ERR_PAUSE_DURATION_EXCEEDED`), documented pre-existing condition (`ERR_PRE_EXISTING_CONDITION_DOCUMENTED`), required inspection (`ERR_INSPECTION_REQUIRED`), open rewash (`ERR_REWASH_IN_PROGRESS`).
10. Referential guards, in order: customer active (`ERR_CUSTOMER_SUSPENDED`), site active (`ERR_SITE_SUSPENDED`), subscription active (`ERR_SUBSCRIPTION_NOT_ACTIVE`), contract active (`ERR_CONTRACT_NOT_ACTIVE`).
11. Fiscal guards, in order: duplicate final invoice (`ERR_INVOICE_EXISTS`), claim cap (`ERR_CLAIM_CAP_EXCEEDED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
12. Finally, the compliance reinstatement guard: a site cannot be reinstated while a confirmed incident remains open there (`ERR_OPEN_COMPLIANCE_INCIDENT`).

Where several of these checks share a single operation, §3 states the concrete guard chain for that operation.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against the `version` of a parent entity:

- Appending a stop to a route requires the request to carry `expected_route_version`, the client's last observed `version` of that Route. If the route's version has advanced since the client last read it, the append is rejected with `ERR_STALE_VERSION` (HTTP 412): stop planning — sequence numbers, planned windows, and water reservations — is derived from the route's stop list at observation time, so a plan built on a stale version must not land.
- Rescheduling a wash order requires `expected_wash_order_version`, the client's last observed `version` of that WashOrder. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the chosen window was validated against the observed record and must not overwrite a newer one.
- Amending a fleet contract requires `expected_fleet_contract_version`, the client's last observed `version` of that FleetContract. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since the new rate card supersedes whatever terms the client read.

The version field is non-optional on these three operations. Endpoints not listed here do not take a version field.

### 2.8. Van Water Accountability

Every van carries a conserved water budget. Three counters live on the Van resource: `water_loaded_gal` (the gallons currently in the tank, set by loading), `water_reserved_gal` (gallons committed to planned work), and `water_used_gal` (gallons drawn by completed work since the last load). At all times the loaded gallons equal the sum of used gallons, reserved gallons, and the free remainder, and the free remainder never goes negative. Reservations are held by stops in `PLANNED` or `ARRIVED`; completing, skipping, or cancelling a stop releases its reservation, and completing a wash additionally converts reservation into usage by growing `water_used_gal` by the actual net draw. Loading water resets the budget entirely: `water_loaded_gal` becomes the loaded amount and both the reserved and used counters return to zero.

Water math is driven by vehicle class and van equipment. Gross consumption per vehicle is 8 gallons for a `SEDAN`, 10 for an `SUV_PICKUP`, 15 for a `VAN_BOXTRUCK`, and 25 for a `HEAVY_FLEET`. A van's `reclaim_system` recovers a fixed fraction of gross usage: `NONE` recovers nothing, `BASIC` recovers sixty percent, and `ADVANCED` recovers eighty-five percent. A net draw — projected or actual — is the gross gallons multiplied by the fraction of water not recovered. Gallon values are carried to one decimal place, and capacity comparisons are exact.

### 2.9. Money, Units, and Rounding

All monetary amounts are integer cents. Wherever a fraction arises — a volume discount, a reclamation surcharge, a loyalty credit, an invoice claim-credit cap — the value is rounded half-up to integer cents. Invoice arithmetic pins the rounding order: each wash-order line's charge is rounded half-up to integer cents first, and only then are the lines summed; summing exact fractions and rounding once at the end is forbidden, because the two orders can differ by cents. Loyalty credits are likewise rounded per line before summing. Audit scores are integers, each category between 0 and 20 inclusive. Service and setup durations are whole minutes. Temperatures are integer degrees Fahrenheit, and precipitation probability is an integer percent between 0 and 100.

### 2.10. Resource Topology, Retrieval, and Cascades

Resources form a flat topology joined by foreign-key references, with one nested family: stops live under their route, so a stop-level path contains both a route identifier and a stop identifier (`stop_id`). Nested paths are validated left to right, and the request is rejected with `ERR_NOT_FOUND` for the first identifier that does not correspond to an existing resource, before later identifiers are examined.

State changes frequently cascade across entities to keep the operation consistent: suspending a site cancels its booked orders and their stops, a weather freeze cancels routes and holds their orders, confirming an incident suspends the site, voiding an invoice reverts its orders' billing. Wherever §3 describes such a cascade, every affected resource is mutated as part of the same operation — each mutation refreshes that resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Accounts and Assets: Customers, Sites, Vehicles, Vans, and Technicians

A `PlatformAdmin` opens the book of business by registering customers. A customer is created with a display `name`, a contact `email` that must be unique across customers, and an optional `customer_type` of `RETAIL` or `FLEET` (defaulting to `RETAIL`). New customers start with `status` `ACTIVE`. An administrator may later suspend and reactivate a customer by posting the `SUSPEND` and `REACTIVATE` events — lifecycle event calls across the API carry an `event_type` field whose value names the event. Suspension is deliberately shallow — it does not cascade to existing orders or subscriptions, but it blocks the creation of new wash orders and subscriptions, and the confirmation of a booked order, with `ERR_CUSTOMER_SUSPENDED`. Both customer events increment the customer's `version`.

Each customer property where washing takes place is a site, registered by an administrator or dispatcher with the owning `customer_id`, a display `name`, the paved `lot_size_sqft` (a positive integer, and the driver of setup time when stops are planned), a `containment_type` of `NONE`, `BERMS`, `RECLAIM_MAT`, or `VACUUM_RECOVERY`, a `water_reclaim_required` flag recording whether local ordinance requires reclamation at that lot, and a `max_discharge_gal` cap (zero or more) on permitted discharge per wash order. Sites are created `ACTIVE`, and `suspension_reason` stays empty while a site is active; §3.7 covers how and why a site leaves `ACTIVE`.

Vehicles are registered with the owning `customer_id`, a home-lot `site_id`, a `plate` that must be unique across vehicles, and a `vehicle_class` of `SEDAN`, `SUV_PICKUP`, `VAN_BOXTRUCK`, or `HEAVY_FLEET` — the class drives pricing, service minutes, and water consumption throughout the system. A `PlatformAdmin` may register any vehicle; a `Customer` registers only its own, meaning the payload's `customer_id` must equal the caller's `X-User-ID`.

Equipment vans are the mobile plant. An administrator creates a van with a call-sign `name`, a positive `tank_capacity_gal`, and a `reclaim_system` of `NONE`, `BASIC`, or `ADVANCED`; new vans are `AVAILABLE` with all water counters zeroed. A dispatcher takes a van out of service with `MAINTENANCE_START` (`AVAILABLE` → `MAINTENANCE`) and returns it with `MAINTENANCE_END`. Maintenance cannot begin while any route using that van exists in `DRAFT`, `PUBLISHED`, or `LOCKED` — the attempt is rejected with `ERR_VAN_ROUTE_CONFLICT`. While `AVAILABLE`, a dispatcher may also load water: the supplied `gallons` must not exceed `tank_capacity_gal` (a range failure is `ERR_VALIDATION`), and loading is blocked while a route with this van is `PUBLISHED` or `LOCKED` (`ERR_VAN_ROUTE_CONFLICT`) — a mere `DRAFT` route does not block loading, though it does block maintenance. Loading sets `water_loaded_gal` to the supplied amount and zeroes both `water_reserved_gal` and `water_used_gal`, per the conserved budget of §2.8, and increments the van's `version`.

Field crew are technicians, created by an administrator with a `name` and an optional `water_reclaim_certified` flag that defaults to false. Technicians start `ACTIVE`; the `DEACTIVATE` and `REACTIVATE` events move them between `ACTIVE` and `INACTIVE`. Deactivation is prospective only: existing routes keep their lead, while creating a new route led by an inactive technician is rejected with `ERR_TECHNICIAN_NOT_ACTIVE`. The `CERTIFY_RECLAIM` event, valid on an active technician, sets `water_reclaim_certified` to true, qualifying that technician to lead routes on `ADVANCED`-reclaim vans. Every technician event increments the technician's `version`.

### 3.2. Commercial Agreements: Fleet Contracts and Subscriptions

Fleet accounts are governed by contracts. An administrator creates a FleetContract — only for a `FLEET`-type customer — capturing `customer_id`, a `start_date`, an `end_date` that must fall after the start, a `monthly_minimum_cents` billing commitment of zero or more, and the four per-class rates `sedan_rate_cents`, `suv_pickup_rate_cents`, `van_boxtruck_rate_cents`, and `heavy_fleet_rate_cents`, each strictly positive. An optional `loyalty_credit_pct`, defaulting to 0, expresses the per-order credit fraction, so a value of 0.025 means two and a half percent. Contracts are born `DRAFT` at version 1 and move through `ACTIVATE` (to `ACTIVE`), `SUSPEND` (to `SUSPENDED`), `REINSTATE` (back to `ACTIVE`), and `TERMINATE` (to `TERMINATED`, allowed from either `ACTIVE` or `SUSPENDED`). Every lifecycle event increments the contract's `version`.

Terminating early carries a fee. When the logical clock's date is before `end_date`, `early_termination_fee_cents` is the number of remaining full calendar months multiplied by `monthly_minimum_cents` multiplied by one-half. Remaining full months are the calendar months that begin after the clock date and are no later than the month containing `end_date`: the month containing the clock date never counts, and the end month counts only when it begins after the clock date. When the clock date is on or after `end_date`, the fee is zero. For example, with the clock at 2026-08-14, an `end_date` of 2026-12-31, and a minimum of 200,000 cents, the full months September through December number four, and the fee is 400,000 cents. The field stays null until the contract reaches `TERMINATED`.

While a contract is `DRAFT` or `ACTIVE`, an administrator may amend its commercial terms — any of the four rates, the minimum, the loyalty percentage, or the dates — leaving the state unchanged; amendment attempts in any other state are rejected with `ERR_INVALID_STATE`. Because a new rate card supersedes whatever terms the client previously read, amendment is guarded by `expected_fleet_contract_version` per §2.7 and increments the contract's `version` on success.

Recurring business runs on subscriptions. An administrator, or the subscribing customer acting for itself, creates a Subscription with `customer_id`, `vehicle_id`, a `cadence` of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, and a `next_service_date`. A vehicle may carry at most one subscription in `ACTIVE` or `PAUSED`; a second attempt is rejected with `ERR_DUPLICATE_SUBSCRIPTION`, and a suspended customer cannot create one at all (`ERR_CUSTOMER_SUSPENDED`). Subscriptions start `ACTIVE` and hold an initially empty, append-only `pauses` list whose records carry `started_at`, `ended_at`, and `days`; an open pause has `ended_at` null.

Pause accounting works over a trailing window of 365 days measured back from the logical clock date. Two computed counters summarize the window: `pause_count_365d` is the number of pause records whose `started_at` falls inside it (a prospective pause being requested is not yet counted), and `paused_days_365d` sums the days of those records, an open record contributing the days elapsed from its `started_at` through the clock date. A `Customer` (for its own subscription) or an administrator requests a pause by supplying `pause_days`. Two guards apply, evaluated in this order: first, the trailing pause count must be below two and the requested pause must be at least seven days long — otherwise the request fails with `ERR_PAUSE_LIMIT_EXCEEDED`; second, the trailing paused days plus the requested days must not exceed ninety — ninety exactly is allowed — otherwise the request fails with `ERR_PAUSE_DURATION_EXCEEDED`. An admitted pause appends an open record stamped with the clock date and the requested number of days.

Resuming closes the open record: `ended_at` becomes the clock date, the record's `days` becomes the elapsed day count, and `next_service_date` shifts forward by exactly that closed record's days, so the subscription calendar is conserved — the service date after a pause-resume pair minus the date before it equals the paused days. Cancelling is allowed from both `ACTIVE` and `PAUSED` and moves the subscription to `CANCELLED`; cancelling a paused subscription also closes its open pause record the same way. Subscription events increment the subscription's `version`.

### 3.3. Booking, Quoting, and Confirming Wash Orders

A wash order is the unit of work. An administrator, a dispatcher, or the booking customer itself creates one with `customer_id`, the service `site_id`, an ordered, non-empty `vehicle_ids` list (every vehicle must belong to that customer), and a planned service window from `scheduled_window_start` to `scheduled_window_end`, the end strictly after the start. Two optional inputs refine billing and process: `subscription_id` links the order to a subscription, which must then cover one of the listed vehicles, and `requires_inspection`, defaulting to false, demands documentation before work may start. A new order is `DRAFT` with `billing_status` `UNBILLED`; `vehicle_count` is the length of `vehicle_ids`; `final_cents` stays null until completion; `rewash_of_id` is null and `is_rewash` is false.

At booking, the order is priced into `quote_cents`. The per-vehicle rate comes from the customer's `ACTIVE` FleetContract rate card when one exists; otherwise the retail card applies — 3,500 cents for a `SEDAN`, 4,500 for an `SUV_PICKUP`, 7,000 for a `VAN_BOXTRUCK`, and 12,000 for a `HEAVY_FLEET`. The evaluation order is fixed. First comes the subtotal, the sum of the per-vehicle rates over the booked vehicles. Then a volume discount percentage is chosen by the booked count: fifteen percent when the count is at least twenty, ten percent when at least ten, five percent when at least five, and no discount below five; the discount amount is the subtotal multiplied by that percentage, rounded half-up to integer cents. The after-discount amount is the subtotal minus the discount. Finally, only when the site's `water_reclaim_required` is true, a reclamation surcharge of eight percent of the after-discount amount — again rounded half-up to integer cents — is added; otherwise the surcharge is zero. The quote is the after-discount amount plus the surcharge. Rewash orders always price zero regardless of this routine.

Confirmation moves an order `DRAFT` → `SCHEDULED` and is performed by the owning customer or a dispatcher. Its guard chain is evaluated in the cascade order of §2.6, so an early failure masks later ones: containment adequacy first — when the site requires reclamation (`water_reclaim_required` true) yet its `containment_type` is `NONE`, confirmation is rejected with `ERR_CONTAINMENT_REQUIRED`; then the site window check — the half-open window from `scheduled_window_start` up to but not including `scheduled_window_end` must not overlap any other order at the same site in `SCHEDULED`, `ASSIGNED`, or `IN_PROGRESS`, though touching endpoints (one order's end equal to another's start) do not conflict, and a violation is `ERR_SITE_WINDOW_CONFLICT`; then the referential guards in order — the customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`), the site must be `ACTIVE` (`ERR_SITE_SUSPENDED`), a linked `subscription_id` must point to an `ACTIVE` subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and a `FLEET` customer must have an `ACTIVE` FleetContract (`ERR_CONTRACT_NOT_ACTIVE`). A confirmed order's `version` increments by one.

While an order is `DRAFT` or `SCHEDULED`, the owning customer or a dispatcher may cancel it; the recorded `cancel_reason` is `CUSTOMER_REQUEST` or `DISPATCH` depending on the actor path, and a system cascade can cancel a `SCHEDULED` order with `cancel_reason` `SITE_SUSPENDED` (§3.7). A `SCHEDULED` order may also be moved to a new window by rescheduling: the caller supplies a fresh `scheduled_window_start` and `scheduled_window_end` together with `expected_wash_order_version` (§2.7), the half-open overlap check above runs again against the new window, and the order stays `SCHEDULED` with its window replaced and its `version` incremented. Cancellation is terminal; rescheduling never is.

The list of an order's stops can be retrieved through the order's route-stops listing; an order has at most one non-cancelled stop at a time.

### 3.4. Route and Stop Planning

Dispatch assembles each service day into routes. A dispatcher creates a Route with a `route_date`, the assigned `van_id`, the `lead_technician_id`, and an optional `shift_start_at` that defaults to 08:00:00 UTC on the route date and must fall on that date. Three guards apply at creation: when the van's `reclaim_system` is `ADVANCED`, the lead technician must be `water_reclaim_certified` (`ERR_CERTIFICATION_REQUIRED`); a van may appear on at most one non-terminal route per date — no other route with the same van and the same `route_date` may exist in `DRAFT`, `PUBLISHED`, or `LOCKED` (`ERR_VAN_ROUTE_CONFLICT`); and the lead technician must be `ACTIVE` (`ERR_TECHNICIAN_NOT_ACTIVE`). A new route is `DRAFT` at version 1.

From `DRAFT`, a dispatcher publishes the route (`DRAFT` → `PUBLISHED`), may unpublish it back to `DRAFT` only while no stop on it has reached `ARRIVED` or `DONE` (otherwise `ERR_INVALID_STATE`), and locks it (`PUBLISHED` → `LOCKED`) when the crew rolls out. A `LOCKED` route is completed once every stop on it sits in `DONE`, `SKIPPED`, or `CANCELLED` (otherwise `ERR_INVALID_STATE`). Any of `DRAFT`, `PUBLISHED`, or `LOCKED` may be cancelled; a manual cancellation records `cancel_reason` `DISPATCH`, while the weather cascade of §3.6 records `WEATHER_FREEZE`. Cancelling a route cascades: its stops in `PLANNED` or `ARRIVED` move to `CANCELLED` and release their reserved water from the van, and the orders behind those stops leave `ASSIGNED` — back to `SCHEDULED` on a manual cancellation, each such return incrementing the order's `version`, or to `WEATHER_HELD` with `hold_reason` `WEATHER_FREEZE` and `held_at` set on a weather one. Every route event increments the route's `version`.

Two computed counters keep a route's load visible: `assigned_vehicle_count` sums the `vehicle_count` of orders whose stop on this route is `PLANNED`, `ARRIVED`, or `DONE`, and `reserved_water_gal` sums the `reserved_water_gal` of stops in `PLANNED` or `ARRIVED`. Both are recomputed whenever stops change state.

Stops are appended one at a time by a dispatcher. The request names the `wash_order_id` of a `SCHEDULED` order and carries `expected_route_version` (§2.7); the route must be `DRAFT` or `PUBLISHED`, since a `LOCKED`, `COMPLETED`, or `CANCELLED` route rejects the mutation with `ERR_ROUTE_LOCKED` — and, per §2.6, the route's state is checked before the order's, an order that is not `SCHEDULED` failing with `ERR_INVALID_STATE`. On success the order moves `SCHEDULED` → `ASSIGNED` with its own `version` incremented, the stop is anchored to its route (recorded as the stop's `route_id` taken from the path) and receives the next 1-based `sequence` in append-only order, and the route's `version` increments.

Each appended stop is planned deterministically. Setup time comes from the site's `lot_size_sqft`: 15 minutes under 10,000 square feet, 25 minutes from 10,000 up to 49,999, and 40 minutes at 50,000 or more. Service time sums per-vehicle minutes over the order's vehicles — 20 for a `SEDAN`, 25 for an `SUV_PICKUP`, 35 for a `VAN_BOXTRUCK`, 50 for a `HEAVY_FLEET`. The first stop's `planned_start_at` is the route's `shift_start_at` (or its 08:00:00 UTC default); each later stop starts twenty minutes of drive time after the previous stop's `planned_end_at`; and a stop's `planned_end_at` is its start plus setup plus service minutes. Stops are processed in ascending `sequence`, and because sequence assignment is append-only, no tie-break ever arises. A route's stops can be listed in sequence order.

Appending a stop also reserves water and runs the compliance gate, in that order of concern. The stop's `reserved_water_gal` is the projected net draw for its order on this route's van — the gross gallons of the order's `vehicle_ids` multiplied by the fraction not recovered (§2.8) — and the van's `water_reserved_gal` grows by the same amount. Feasibility requires the van's free gallons — `water_loaded_gal` minus `water_used_gal` minus `water_reserved_gal` — to be at least the candidate stop's projected net draw, with equality allowed; otherwise the append fails with `ERR_ROUTE_WATER_CAPACITY_EXCEEDED`. Before any reservation lands, the discharge check runs when the site's `water_reclaim_required` is true: equipment adequacy is checked first, so a van whose recovery fraction is below sixty percent is rejected with `ERR_CONTAINMENT_REQUIRED`; then the projected discharge — gross gallons times the unrecovered fraction — must not exceed the site's `max_discharge_gal`, with a projection exactly equal to the cap allowed and anything strictly greater rejected with `ERR_DISCHARGE_CAP_EXCEEDED`.

Two further capacity and schedule guards complete the append chain. Across different routes on the same date led by the same technician, the gap between one stop's `planned_end_at` and another stop's `planned_start_at` must be at least thirty minutes — exactly thirty is allowed — else `ERR_TECHNICIAN_SCHEDULE_CONFLICT`. And the route's `assigned_vehicle_count` plus the candidate order's `vehicle_count` must not exceed forty vehicles — exactly forty is allowed — else `ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED`.

### 3.5. Day-of-Service Execution: Arrival, Inspection, Washing, and Completion

On site, the route's lead technician marks arrival, moving a stop `PLANNED` → `ARRIVED`. Arrival is accepted only while the route is `PUBLISHED` or `LOCKED`; on a route in any other state — including `DRAFT` — it is rejected with `ERR_ROUTE_LOCKED`.

Documentation comes from inspection reports. A technician files an InspectionReport with the `wash_order_id` and an `areas` list: a non-empty collection of entries each pairing an `area` — one of `EXTERIOR_BODY`, `GLASS`, `WHEELS`, `INTERIOR`, or `TRIM`, each area appearing at most once — with a `pre_existing_damage` flag and free-text `notes`. The filing technician's identity is taken from the caller: `technician_id` is set from `X-User-ID`. A report starts `DRAFT`, and only the filing technician may submit it, moving it `DRAFT` → `SUBMITTED`. Submission requires the order to be in `SCHEDULED`, `ASSIGNED`, `IN_PROGRESS`, `COMPLETED`, or `REWASH_PENDING` (otherwise `ERR_INVALID_STATE`) — documentation may be finalized after the wash — and a `SUBMITTED` report is immutable. Its consequence lands later: submission blocks any future claim approval on an area it flags with `pre_existing_damage` (§3.8).

Starting the wash moves the order `ASSIGNED` → `IN_PROGRESS` and belongs to the lead technician of the route holding the order's stop. The order's non-cancelled stop must be `ARRIVED` (otherwise `ERR_INVALID_STATE`), the site must be `ACTIVE` (`ERR_SITE_SUSPENDED`), and when `requires_inspection` is true a `SUBMITTED` InspectionReport must already exist for the order (`ERR_INSPECTION_REQUIRED`). A started order's `version` increments.

Completion moves `IN_PROGRESS` → `COMPLETED`. The lead technician reports `vehicles_washed_ids`, which must be a non-empty subset of `vehicle_ids` (otherwise `ERR_VALIDATION`). Completion then settles several books at once: `final_cents` is computed with the same pricing routine as §3.3 but over the washed subset, so the washed count — not the booked count — drives the discount tier, and identical order data yields a different amount whenever the washed count crosses a tier boundary or drops a vehicle; `completed_at` is stamped from the logical clock; the order's stop — whether still `PLANNED` or already `ARRIVED` — moves to `DONE`; the stop's `reserved_water_gal` is released from the van's `water_reserved_gal` while the van's `water_used_gal` grows by the actual net draw, the gross gallons of `vehicles_washed_ids` multiplied by the unrecovered fraction; the route's counters are recomputed; and if the completed order is a rewash — its `rewash_of_id` set — the original order moves `REWASH_PENDING` → `CLOSED`. The order's `version` increments.

Not every stop ends in a wash. The route lead or a dispatcher may skip a stop in `PLANNED` or `ARRIVED`, moving it to `SKIPPED`; the order behind it is cancelled with `cancel_reason` `NO_SHOW` — from `ASSIGNED` when the stop was still planned, or from `ASSIGNED` or `IN_PROGRESS` when the crew had already arrived — and the stop's reservation is released with the route counters recomputed. A dispatcher may instead remove a `PLANNED` stop outright while the route is `DRAFT` or `PUBLISHED` (a `LOCKED`, `COMPLETED`, or `CANCELLED` route rejects removal with `ERR_ROUTE_LOCKED`); removal moves the stop to `CANCELLED`, returns the order from `ASSIGNED` to `SCHEDULED` with the order's `version` incremented, and releases the reservation. System cascades — a cancelled route, a suspended site, or a cancelled order — also cancel stops, following whichever cascade triggered them.

Cancelling an order while it is `ASSIGNED` unwinds the field plan: the order's stop moves to `CANCELLED`, its reserved water is released from the van, the route counters are recomputed, and — when the cancelled order is itself a rewash — the original order compensates by moving `REWASH_PENDING` → `COMPLETED`, restoring it to its pre-rewash state.

### 3.6. Weather Disruptions, Holds, and the Daily Sweep

Weather policy is evaluated per service date by a dispatcher, supplying `evaluation_date`, an integer `forecast_low_f` in degrees Fahrenheit, and an integer `precip_probability_pct` between 0 and 100. The evaluation creates a record (hence 201) and answers with `evaluation_date`, a `freeze` flag, an `advisory` flag, and the lists `cancelled_route_ids` and `held_order_ids`.

A freeze triggers when `forecast_low_f` is at most 32 — 32 exactly freezes, 33 does not. The freeze cascades: every route whose `route_date` equals the evaluation date and whose status is `PUBLISHED` or `LOCKED` moves to `CANCELLED` with `cancel_reason` `WEATHER_FREEZE`; each such route's stops in `PLANNED` or `ARRIVED` move to `CANCELLED` and release their reserved water from the van; each of those stops' orders in `ASSIGNED` moves to `WEATHER_HELD` with `hold_reason` `WEATHER_FREEZE` and `held_at` stamped from the logical clock, the stop's water being released before the order's transition lands; and every unrouted order whose scheduled window date equals the evaluation date and whose status is `SCHEDULED` likewise moves to `WEATHER_HELD` with the same hold fields set. A rain advisory triggers when the low is above 32 and `precip_probability_pct` is at least 60 — 60 exactly raises the advisory, 59 does not — setting `advisory` true without changing any order or route state. Anything milder has no effect. Independently of the evaluation, a dispatcher may also place a single `SCHEDULED` order on hold directly through the order's `WEATHER_HOLD` event, which sets the same hold fields.

A weather hold is recoverable for two weeks. Rescheduling a `WEATHER_HELD` order — by the owning customer or a dispatcher — requires the logical clock date to be no later than the `held_at` date plus fourteen days (the fourteenth day is allowed; later is `ERR_RESCHEDULE_WINDOW_EXPIRED`), runs the half-open overlap check of §3.3 against the new window (`ERR_SITE_WINDOW_CONFLICT`), and carries `expected_wash_order_version` per §2.7. Success replaces `scheduled_window_start` and `scheduled_window_end`, clears `hold_reason` and `held_at`, returns the order to `SCHEDULED`, and increments its `version`. Alternatively, the owning customer or a dispatcher may simply cancel a held order.

A dispatcher-run daily sweep closes out expired timers. Orders still `COMPLETED` whose `completed_at` is at or before the logical clock minus 72 hours move to `CLOSED` — this is the guarantee window lapsing without a claim or rewash. Orders still `WEATHER_HELD` whose `held_at` date plus fourteen days falls before the clock date are cancelled with `cancel_reason` `WEATHER_EXPIRED`; an order held exactly fourteen days is not expired. The sweep answers with the affected `closed_order_ids` and `expired_order_ids`.

### 3.7. Water Compliance: Incidents and Site Suspension

Environmental compliance is enforced through incidents. A `ComplianceOfficer` reports an incident with the `site_id`, an `incident_type` of `DISCHARGE_TO_STORM_DRAIN`, `CONTAINMENT_FAILURE`, `RECLAIM_EQUIPMENT_FAILURE`, or `SPILL`, free-text `notes`, and an optional `wash_order_id` linking the related order; the incident starts `REPORTED`. Review moves it `REPORTED` → `UNDER_REVIEW` (`START_REVIEW`), from which the officer either confirms it or dismisses it (`DISMISSED`, terminal).

Confirmation is the heavy action. Moving an incident to `CONFIRMED` suspends the site with `suspension_reason` `COMPLIANCE_INCIDENT`, and the suspension cascades exactly as the site state machine dictates: every wash order at the site in `SCHEDULED` or `ASSIGNED` is cancelled with `cancel_reason` `SITE_SUSPENDED`; each such assigned order's stop moves to `CANCELLED`; the stop's reserved water is released from the route's van, so `water_reserved_gal` decreases; and the route's `assigned_vehicle_count` and `reserved_water_gal` are recomputed. Resolution moves `CONFIRMED` → `RESOLVED`; when no other incident at that site remains `CONFIRMED`, the system reinstates the site to `ACTIVE` and clears `suspension_reason`.

An officer may also suspend a site directly, which records `suspension_reason` `MANUAL` and runs the same order, stop, and water cascade as a confirmed incident. Reinstatement through the `REINSTATE` event is blocked while any incident at the site has status `CONFIRMED`, failing with `ERR_OPEN_COMPLIANCE_INCIDENT`; the system's own reinstatement on resolution simply does not fire while another incident at the site remains `CONFIRMED`. Both officer-driven and system-driven site transitions increment the site's `version`.

### 3.8. Quality Audits, Damage Claims, and the Rewash Guarantee

Quality is measured by audits on finished work. A `QualityAuditor` records an audit for a `COMPLETED` wash order, supplying the `wash_order_id` and five integer category scores — `exterior_score`, `wheels_score`, `glass_score`, `trim_score`, and `water_spotting_score` — each between 0 and 20 inclusive. The `total_score` is the plain sum of the five categories with equal weights, spanning 0 to 100, and the computed `result` is `PASS` when the total reaches 80 — 80 exactly passes — and `FAIL` below it. The auditor's opaque `X-User-ID` is recorded as `auditor_id`. A `FAIL` result has teeth: if no open rewash exists for the order — open meaning `DRAFT`, `SCHEDULED`, `ASSIGNED`, `IN_PROGRESS`, or `WEATHER_HELD` — the system creates a rewash order and moves the audited order `COMPLETED` → `REWASH_PENDING`, just as a customer-requested rewash would.

The rewash guarantee gives the owning customer a direct path to the same remedy. Within 72 hours of an order's `completed_at` — exactly 72 hours is allowed; later requests fail with `ERR_REWASH_WINDOW_EXPIRED` — the customer may request a rewash of a `COMPLETED` order, provided no other rewash of that same order is still open (`ERR_REWASH_IN_PROGRESS`). The rewash order is created fresh: `customer_id`, `site_id`, and `vehicle_ids` are copied from the original; `rewash_of_id` points back to it, making `is_rewash` true; `billing_status` is `WAIVED`; `quote_cents` is 0; and the status is `SCHEDULED` with a window of the next day — the logical clock date plus one day — from 08:00:00 to 10:00:00 UTC. The original order moves `COMPLETED` → `REWASH_PENDING` with its `version` incremented. From there the pair resolves in one of two ways: the rewash completing closes the original (`REWASH_PENDING` → `CLOSED`, per §3.5), while the rewash being cancelled before completion reverts the original to `COMPLETED` as a compensating action. Orders that stay `COMPLETED` past the 72-hour guarantee window without a claim or rewash are closed by the daily sweep of §3.6.

Damage claims run on a parallel track with stricter duties. The owning customer files a claim against a `COMPLETED` order within 72 hours of its `completed_at` — exactly 72 hours is allowed; a later filing fails with `ERR_CLAIM_WINDOW_EXPIRED` — supplying `wash_order_id`, the affected `area`, a strictly positive `claimed_amount_cents`, and a free-text `description`. The claim's `customer_id` is copied from the wash order, `filed_at` is stamped from the logical clock, and the claim starts `FILED`. A `QualityAuditor` opens review (`FILED` → `UNDER_REVIEW`) and then either approves or denies.

Approval applies two checks in this order. First, if any `SUBMITTED` InspectionReport for the order flags the claimed `area` with `pre_existing_damage`, approval is blocked with `ERR_PRE_EXISTING_CONDITION_DOCUMENTED`. Second, the amount: `approved_amount_cents` defaults to the lesser of `claimed_amount_cents` and the class cap taken from the order's first vehicle's class — 25,000 cents for a `SEDAN`, 30,000 for an `SUV_PICKUP`, 40,000 for a `VAN_BOXTRUCK`, and 60,000 for a `HEAVY_FLEET` — and an explicit `approved_amount_cents` may be supplied only at or below that minimum, anything higher failing with `ERR_CLAIM_CAP_EXCEEDED`. The approving auditor's `X-User-ID` is recorded as `reviewed_by`. Until a claim reaches `APPROVED`, its `approved_amount_cents` is null. Denial instead records the supplied `deny_reason`, sets `reviewed_by` the same way, moves the claim to `DENIED`, and creates no credit.

Payment is deliberately separated from approval. Marking an `APPROVED` claim `PAID` requires the paying auditor's `X-User-ID` to differ from the claim's `reviewed_by`; the same user attempting both steps is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful payment records `paid_by` and makes the claim eligible for the invoice claim credits of §3.9 in the wash order's completion period.

### 3.9. Fleet Billing and Invoicing

Fleet accounts are billed monthly through generated invoices. An administrator or dispatcher generates an invoice by naming the `fleet_contract_id`, the `period_month` in YYYY-MM form, and a `variant` of `PROJECTION` or `FINAL`; the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`). The variant controls both the line set and the initial status: a `PROJECTION` produces a `PREVIEW` invoice that can never be issued, while a `FINAL` produces a `DRAFT` invoice that may proceed through settlement. Generating a `FINAL` invoice voids any existing `PREVIEW` rows for the same contract and period.

Line selection differs by variant. A `FINAL` invoice includes the contract customer's wash orders in `COMPLETED`, `REWASH_PENDING`, or `CLOSED` whose `completed_at` falls inside the period, excluding any whose `billing_status` is `WAIVED`, and prices each line at the contract rate card over the washed vehicle set — the final amounts of §3.5. A `PROJECTION` additionally includes orders in `SCHEDULED`, `ASSIGNED`, or `IN_PROGRESS` whose `scheduled_window_start` falls inside the period, priced at their booking quotes, so identical period data yields a different total whenever unfinished orders exist or a quote differs from its final. Rounding follows §2.9: each order line's charge is rounded half-up to integer cents first, and only then are lines summed — summing exact fractions and rounding once at the end is forbidden. Each line's loyalty credit is its rounded charge multiplied by the contract's `loyalty_credit_pct`, itself rounded half-up to integer cents.

The invoice totals then derive in a fixed order. `line_count` is the number of included wash-order lines; `charges_cents` and `loyalty_credits_cents` are the per-line sums. The billed amount `billed_cents` is the greater of charges minus credits and the contract's `monthly_minimum_cents`, and `minimum_applied` is true exactly when charges minus credits fell below the minimum. A period with zero included orders still bills the minimum: `line_count` and `charges_cents` are 0 and `billed_cents` equals `monthly_minimum_cents`. Claim credits come last and are capped from the post-minimum figure: the cap is `billed_cents` multiplied by one quarter, rounded half-up — never derived from `net_due_cents`; the eligible pool sums `approved_amount_cents` over the customer's `PAID` damage claims whose orders completed inside the period; `claim_credits_cents` is the lesser of the pool and the cap; and `net_due_cents` is `billed_cents` minus `claim_credits_cents`.

Only one `FINAL`-variant invoice may exist per contract and period in `DRAFT`, `ISSUED`, `DISPUTED`, or `PAID`; a second generation attempt fails with `ERR_INVOICE_EXISTS`. `PREVIEW` rows never block generation, and voiding releases the period for regeneration.

Settlement moves a `DRAFT` invoice through its lifecycle. Issuing — a dispatcher action allowed only on a `FINAL` invoice, a `PREVIEW` attempt failing with `ERR_INVALID_STATE` — moves it to `ISSUED` and flips every included order's `billing_status` from `UNBILLED` to `INVOICED`. Marking paid moves `ISSUED` → `PAID` and flips the included orders from `INVOICED` to `PAID`. A dispute — raised by a dispatcher or by the contract's own customer — moves `ISSUED` → `DISPUTED`. Voiding, a dispatcher action from `DISPUTED`, moves the invoice to `VOID` and reverts every included order from `INVOICED` back to `UNBILLED` as a compensating action. Invoice events increment the invoice's `version`.

Throughout, an order's `billing_status` — `UNBILLED`, `INVOICED`, `PAID`, or `WAIVED` — is an independent dimension living on the same WashOrder row as the lifecycle status; rewash orders are created already `WAIVED`, and the two dimensions never block each other.

## 4. Endpoint Definitions

Operations that create new resources — including generated invoices, rewash orders, and weather evaluations — return `201 Created`. Operations that modify an existing resource or fire lifecycle events, including the logical-clock capability and the daily sweep, return `200 OK`. Readers reconstruct each endpoint's full request and response from the §3 narratives; this table is only a locator. Rows marked "All" accept any of the six roles of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fleet-wash/_clock/set_current_utc` | Advance the server's logical clock | PlatformAdmin |
| POST | `/fleet-wash/ops/run-daily` | Daily sweep: close stale completed orders, expire lapsed weather holds | Dispatcher |
| POST | `/fleet-wash/weather/evaluations` | Evaluate the freeze/rain policy for a service date | Dispatcher |
| POST | `/fleet-wash/customers` | Create a customer | PlatformAdmin |
| GET | `/fleet-wash/customers/{id}` | Get a customer | All |
| POST | `/fleet-wash/customers/{id}/events` | Customer lifecycle events: SUSPEND, REACTIVATE | PlatformAdmin |
| POST | `/fleet-wash/sites` | Create a customer site (lot) | PlatformAdmin, Dispatcher |
| GET | `/fleet-wash/sites/{id}` | Get a site | All |
| GET | `/fleet-wash/sites` | List sites with optional filters | All |
| POST | `/fleet-wash/sites/{id}/events` | Site lifecycle events: SUSPEND, REINSTATE | ComplianceOfficer |
| POST | `/fleet-wash/vehicles` | Register a vehicle | PlatformAdmin, Customer |
| GET | `/fleet-wash/vehicles/{id}` | Get a vehicle | All |
| GET | `/fleet-wash/vehicles` | List vehicles with optional filters | All |
| POST | `/fleet-wash/fleet-contracts` | Create a fleet contract in DRAFT for a FLEET customer | PlatformAdmin |
| GET | `/fleet-wash/fleet-contracts/{id}` | Get a fleet contract | All |
| GET | `/fleet-wash/fleet-contracts` | List fleet contracts with optional filters | All |
| PUT | `/fleet-wash/fleet-contracts/{id}` | Amend rate card, minimum, or dates while DRAFT or ACTIVE (OCC-guarded) | PlatformAdmin |
| POST | `/fleet-wash/fleet-contracts/{id}/events` | Contract lifecycle events: ACTIVATE, SUSPEND, REINSTATE, TERMINATE | PlatformAdmin |
| POST | `/fleet-wash/subscriptions` | Create a recurring subscription for a vehicle | PlatformAdmin, Customer |
| GET | `/fleet-wash/subscriptions/{id}` | Get a subscription | All |
| GET | `/fleet-wash/subscriptions` | List subscriptions with optional filters | All |
| POST | `/fleet-wash/subscriptions/{id}/events` | Subscription events: PAUSE, RESUME, CANCEL | PlatformAdmin, Customer |
| POST | `/fleet-wash/wash-orders` | Create a wash order in DRAFT with a booking quote | PlatformAdmin, Dispatcher, Customer |
| GET | `/fleet-wash/wash-orders/{id}` | Get a wash order | All |
| GET | `/fleet-wash/wash-orders` | List wash orders with optional filters | All |
| POST | `/fleet-wash/wash-orders/{id}/events` | Order lifecycle events: CONFIRM, START, COMPLETE, CANCEL, WEATHER_HOLD | PlatformAdmin, Dispatcher, Customer, Technician |
| POST | `/fleet-wash/wash-orders/{id}/reschedule` | Move a SCHEDULED or WEATHER_HELD order to a new window (OCC-guarded) | PlatformAdmin, Dispatcher, Customer |
| POST | `/fleet-wash/wash-orders/{id}/rewash` | Customer requests a guarantee rewash of a COMPLETED order | Customer |
| GET | `/fleet-wash/wash-orders/{id}/route-stops` | List route stops serving this order | All |
| POST | `/fleet-wash/routes` | Create a route for a date, van, and lead technician | Dispatcher |
| GET | `/fleet-wash/routes/{id}` | Get a route | All |
| GET | `/fleet-wash/routes` | List routes with optional filters | All |
| POST | `/fleet-wash/routes/{id}/events` | Route lifecycle events: PUBLISH, UNPUBLISH, LOCK, COMPLETE, CANCEL | Dispatcher |
| POST | `/fleet-wash/routes/{id}/stops` | Append a stop for a SCHEDULED wash order (OCC-guarded) | Dispatcher |
| GET | `/fleet-wash/routes/{id}/stops` | List a route's stops in sequence order | All |
| POST | `/fleet-wash/routes/{id}/stops/{stop_id}/events` | Stop events: ARRIVE, SKIP, REMOVE | Dispatcher, Technician |
| POST | `/fleet-wash/vans` | Create an equipment van | PlatformAdmin |
| GET | `/fleet-wash/vans/{id}` | Get a van | All |
| POST | `/fleet-wash/vans/{id}/events` | Van events: LOAD_WATER, MAINTENANCE_START, MAINTENANCE_END | Dispatcher |
| POST | `/fleet-wash/technicians` | Create a technician | PlatformAdmin |
| GET | `/fleet-wash/technicians/{id}` | Get a technician | All |
| POST | `/fleet-wash/technicians/{id}/events` | Technician events: DEACTIVATE, REACTIVATE, CERTIFY_RECLAIM | PlatformAdmin |
| POST | `/fleet-wash/inspection-reports` | File a pre-wash inspection report in DRAFT | Technician |
| GET | `/fleet-wash/inspection-reports/{id}` | Get an inspection report | All |
| GET | `/fleet-wash/inspection-reports` | List inspection reports with optional filters | All |
| POST | `/fleet-wash/inspection-reports/{id}/events` | Report events: SUBMIT (filing technician only) | Technician |
| POST | `/fleet-wash/damage-claims` | File a damage claim against a COMPLETED wash order | Customer |
| GET | `/fleet-wash/damage-claims/{id}` | Get a damage claim | All |
| GET | `/fleet-wash/damage-claims` | List damage claims with optional filters | All |
| POST | `/fleet-wash/damage-claims/{id}/events` | Claim events: START_REVIEW, APPROVE, DENY, MARK_PAID | QualityAuditor |
| POST | `/fleet-wash/quality-audits` | Record a quality audit for a COMPLETED wash order | QualityAuditor |
| GET | `/fleet-wash/quality-audits/{id}` | Get a quality audit | All |
| GET | `/fleet-wash/quality-audits` | List quality audits with optional filters | All |
| POST | `/fleet-wash/compliance-incidents` | Report a water-compliance incident at a site | ComplianceOfficer |
| GET | `/fleet-wash/compliance-incidents/{id}` | Get a compliance incident | All |
| GET | `/fleet-wash/compliance-incidents` | List compliance incidents with optional filters | All |
| POST | `/fleet-wash/compliance-incidents/{id}/events` | Incident events: START_REVIEW, CONFIRM, DISMISS, RESOLVE | ComplianceOfficer |
| POST | `/fleet-wash/invoices/generate` | Generate an invoice; PROJECTION yields PREVIEW, FINAL yields DRAFT | PlatformAdmin, Dispatcher |
| GET | `/fleet-wash/invoices/{id}` | Get an invoice | All |
| GET | `/fleet-wash/invoices` | List invoices with optional filters | All |
| POST | `/fleet-wash/invoices/{id}/events` | Invoice events: ISSUE, MARK_PAID, DISPUTE, VOID | Dispatcher, Customer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUTE_LOCKED` | 409 Conflict |
| `ERR_CONTAINMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DISCHARGE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SITE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TECHNICIAN_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REWASH_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RESCHEDULE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ROUTE_WATER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_VAN_ROUTE_CONFLICT` | 409 Conflict |
| `ERR_TECHNICIAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_SUBSCRIPTION` | 409 Conflict |
| `ERR_PAUSE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PAUSE_DURATION_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRE_EXISTING_CONDITION_DOCUMENTED` | 409 Conflict |
| `ERR_INSPECTION_REQUIRED` | 409 Conflict |
| `ERR_REWASH_IN_PROGRESS` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_SITE_SUSPENDED` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVOICE_EXISTS` | 409 Conflict |
| `ERR_CLAIM_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OPEN_COMPLIANCE_INCIDENT` | 409 Conflict |
