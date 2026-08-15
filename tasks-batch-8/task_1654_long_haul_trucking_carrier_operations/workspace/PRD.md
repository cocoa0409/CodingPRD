# Long-Haul Trucking Carrier Operations API — Product Requirements Document

## 1. Introduction

An asset-based long-haul carrier earns its margin one load at a time. Revenue arrives as linehaul rates, fuel surcharges, and accessorial charges; costs accrue as driver pay, fuel burned state by state, and the variable expense of turning the carrier's own wheels. The spread on any single tender is thin, and the operating constraints are unforgiving — federal hours-of-service limits, home-time commitments, safety scores that decide who may legally be dispatched, and customers whose credit can freeze mid-negotiation. Most of the money is made or lost before the truck moves, and the truth of it is only settled weeks later, when detention claims, fuel receipts, and final odometer readings have all landed.

This document specifies the API through which such a carrier runs that discipline end to end. It covers the commercial pipeline from load tender through profitability screening, acceptance, rejection, and tiered cancellation; the assignment of drivers and tractors under safety, hours-of-service, home-time, and scheduling gates; execution telemetry through duty events and check calls; the capture, adjudication, and billing of detention and other accessorials; fuel purchasing with state-tax equalization; customer invoicing with a full issue, void, and payment cycle; and weekly driver payroll under a segregation-of-duties control. Every time-dependent rule — projections, decay windows, appointment deadlines — evaluates against a server-managed logical clock, so behavior is reproducible regardless of when a request physically arrives.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request that is missing either header, or whose role is not one of the six recognized values, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the targeted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The six roles are:

- `FleetAdmin` — the fleet master-data administrator: registers and reconfigures drivers and tractors, creates customer accounts and fuel-rate windows, terminates drivers, and controls the logical clock.
- `LoadPlanner` — the commercial planner: maintains lanes, tenders and adjudicates loads, manages customer credit holds, decides accessorial disputes, and runs the invoicing lifecycle.
- `Dispatcher` — the dispatch operator: creates, replans, dispatches, and cancels trips, records check calls and fuel purchases on a driver's behalf, captures accessorials, and works the backhaul board.
- `SafetyOfficer` — the safety and compliance authority: suspends and reinstates drivers, records manual safety events, and voids them.
- `PayrollClerk` — the payroll operator: owns the settlement lifecycle end to end, subject to the segregation-of-duties control described in §3.9.
- `Driver` — the driver self-service role: records their own duty events, check calls, fuel purchases, and accessorial claims, and reads their own settlements and safety record.

When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting Driver; ownership checks on any resource that references a Driver compare the resource's driver reference to `X-User-ID`. Concretely, a caller in the `Driver` role may append duty events only to their own driver record, record check calls only against a trip whose `driver_id` equals `X-User-ID`, record a fuel purchase only when the payload's `driver_id` equals both the trip's driver and `X-User-ID`, and capture or submit accessorials only for loads with a trip driven by `X-User-ID`; any mismatch is rejected with `ERR_DRIVER_MISMATCH` (HTTP 403). When `X-User-Role` is `FleetAdmin`, `LoadPlanner`, `Dispatcher`, `SafetyOfficer`, or `PayrollClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_id` or `approved_by_id` on a Settlement — but does not compare it to any entity's `id`.

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

### 2.3. Pagination and List Ordering

Endpoints that return lists of resources accept the `limit` and `offset` query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items to skip and defaults to 0. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

Unless an endpoint documents its own ordering, every list is returned in `created_at` ascending order, where `created_at` is the server-stamped creation timestamp with three fractional digits; no business ordering anywhere in the system is based on `id`. Two endpoints are explicit exceptions: a driver's duty-event history is returned in `occurred_at` ascending order, and the dispatch backhaul board returns its candidates in ranking order as defined in §3.3.

Several list endpoints accept domain filters in addition to `limit` and `offset`: the driver roster accepts `status`, the tractor roster accepts `status`, the load board accepts `status`, `customer_id`, and `lane_id`, the trip list accepts `driver_id`, `tractor_id`, `load_id`, and `status`, the settlement list accepts `driver_id` and `status`, and the fuel-rate list accepts `state_code`. Each filter narrows the list to resources whose corresponding attribute equals the supplied value.

### 2.4. The Logical Clock

The server maintains a logical clock, and every time-gated rule in this document — appointment comparisons, hours-of-service projections, safety-score decay windows, fuel-rate effective windows, settlement period boundaries — evaluates against that logical now rather than wall-clock time. A `FleetAdmin`-only clock-setting capability accepts a `to_iso8601` timestamp and installs it as the current logical time, returning the installed value as `current_utc`; advancing the clock immediately reframes every projection computed from it. At startup, before any clock-setting call has been made, the logical time is exactly 2026-08-01T00:00:00Z, and the server must never fall back to wall-clock time in lieu of an explicit set.

Throughout this document, the phrase "logical now" always refers to the current value of this clock.

### 2.5. Common Resource Properties

Every primary resource — Driver, Tractor, CustomerAccount, Lane, StateFuelRate, Load, Trip, AccessorialCharge, FuelPurchase, SafetyEvent, Settlement, and Invoice — carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the resource type.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped by the server at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations the server applies as cascaded side effects.
- `version` — an integer assigned the value 1 at creation and incremented by one on every mutation of the resource, again including cascaded mutations. It is the currency of optimistic concurrency control as described in §2.8.

Two resources are deliberately leaner. DutyEvent and CheckCall are append-only telemetry records: they carry `id` and `created_at` only, and both `updated_at` and `version` are absent, because a recorded event is never modified after the fact.

### 2.6. Money, Mileage, and Precision

All monetary amounts are integer cents — linehaul rates, surcharges, accessorial amounts, pay figures, and invoice totals alike — and no response ever carries fractional currency. Wherever a rule in this document states that a value is rounded, the method is round half up to the nearest whole cent, applied exactly at the step the rule names and nowhere else; per-charge values are rounded per charge before any summation when a rule says so. Rates per mile are likewise whole cents. Durations, clocks, and deadlines in the hours-of-service and ETA machinery are whole minutes. Mileage odometers, trip miles, and fuel gallons are whole numbers, with the single exception of the fleet fuel-economy constant of 6.5 miles per gallon, whose divisions are carried as exact rational arithmetic until the rule's stated rounding step. A driver's `safety_score` is an integer between 0 and 100.

### 2.7. Cascading Mutations and Derived-Field Reconciliation

A single client action in this system frequently mutates several resources at once, because a Trip binds a Driver, a Tractor, and a Load, and an Invoice aggregates a load's AccessorialCharges. Whenever one operation ripples into another resource — assigning a load, releasing a tractor, cascading a suspension, flipping accessorials to billed — every resource the server touches has its `updated_at` refreshed and its `version` incremented, whether or not the client named that resource in the request. Creating a trip, for example, moves the load from `ACCEPTED` to `ASSIGNED` and explicitly increments the load's `version`; a client holding a stale snapshot of the load will observe that bump on its next read.

Derived fields are reconciled immediately at the event that changes them, never lazily at read time. A driver's `duty_status` mirrors the latest recorded duty event; the `safety_score` is recomputed the moment a safety event is recorded or voided; a load's `total_accessorial_cents` is recomputed when charges flip to billed at invoice issue and again when they flip back at void; a tractor's odometer, location state, and fuel on board are rewritten when its trip completes. Consistency is immediate in both directions: no read ever computes what a write should have settled.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against the version of the resource being modified:

- Updating a Driver's pay or home-terminal configuration requires the request to carry `expected_driver_version`, holding the Driver `version` the client last observed. If the driver's current `version` has moved past that value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never overwrites a pay configuration it has not seen.
- Replanning a `PLANNED` Trip requires `expected_trip_version`, holding the Trip `version` the client last observed. Because cascaded touches also advance a trip's `version`, any intervening write — including one the client did not itself perform — causes the replan to be rejected with `ERR_STALE_VERSION` (HTTP 412).
- Recalculating a `DRAFT` Settlement requires `expected_settlement_version`, holding the Settlement `version` the client last observed; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so a manual adjustment is never applied on top of an unobserved recalculation.

The version field is a non-optional input on exactly these three operations. Endpoints not named here do not accept a version field at all.

### 2.9. Request Validation Pipeline

Every request is evaluated against a fixed, ordered pipeline of checks, and a failure at any stage short-circuits the stages after it. The order matters because it determines which error a doubly-invalid request produces.

1. **Identity headers.** `X-User-ID` and `X-User-Role` must be present and the role recognized — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The role must be permitted for the endpoint — otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
3. **Path existence.** Resource identifiers in the path must resolve, validated left to right — otherwise the corresponding 404 (see §2.10).
4. **Body shape.** Required fields must be present, enum values must belong to their declared sets, numeric minimums must hold (positive rates, weights, gallon counts; non-negative odometers and deadhead plans), documented datetime orderings must hold (a load's delivery appointment strictly after its pickup appointment; a settlement's `period_end` strictly after its `period_start`), and no client-supplied event timestamp may fall after the logical now — failures are `ERR_INVALID_REQUEST` (HTTP 400).
5. **Driver identity.** On driver-scoped writes by a caller in the `Driver` role, the identity-matching rules of §2.1 apply — mismatches are `ERR_DRIVER_MISMATCH` (HTTP 403).
6. **State admissibility.** The target resource must be in a state that admits the requested transition; this stage produces the family of 409 state errors such as `ERR_LOAD_NOT_ASSIGNABLE`, `ERR_TRACTOR_NOT_AVAILABLE`, `ERR_DRIVER_NOT_ACTIVE`, and `ERR_TRIP_NOT_FUELABLE`, each named alongside its transition in §3.
7. **Concurrency freshness.** On the three OCC-guarded writes, the expected version must equal the resource's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412).
8. **Safety and regulatory gates.** On trip creation and trip replan, three gates apply in a fixed sub-order: first the safety floor (`ERR_DRIVER_SAFETY_BELOW_FLOOR`), then the four hours-of-service feasibility clauses (`ERR_HOS_INSUFFICIENT`), then the home-time ceiling (`ERR_HOME_TIME_EXCEEDED`) — all HTTP 422.
9. **Temporal ordering and overlap.** Half-open driver trip windows must not overlap (`ERR_TRIP_OVERLAP`); check-call kind rank, timestamps, and odometers must advance monotonically (`ERR_CHECK_CALL_OUT_OF_ORDER`); duty events must be strictly increasing in time (`ERR_DUTY_EVENT_OUT_OF_ORDER`); a driver's settlement periods must not overlap (`ERR_SETTLEMENT_PERIOD_OVERLAP`); a state's fuel-rate windows must not overlap (`ERR_FUEL_RATE_WINDOW_OVERLAP`) — all HTTP 422.
10. **Constraint rules.** Pay-config completeness for the declared `pay_model` (`ERR_PAY_CONFIG_INCOMPLETE`); at most one open detention charge of each leg type per load (`ERR_DUPLICATE_ACCESSORIAL_TYPE`); at most one non-`VOID` invoice per load (`ERR_INVOICE_ALREADY_EXISTS`); a fuel purchase's state must lie on the trip's route (`ERR_STATE_NOT_ON_ROUTE`); the tractor's tank must hold the purchase (`ERR_TANK_CAPACITY_EXCEEDED`); a currently effective fuel-rate row must exist where one is required (`ERR_FUEL_RATE_UNAVAILABLE`); a fuel plan must be feasible (`ERR_FUEL_PLAN_INFEASIBLE`) — all HTTP 422.
11. **Aggregate gate on invoice issue.** Issuing an invoice requires that no accessorial of the load remain open — otherwise `ERR_INVOICE_OPEN_ACCESSORIALS` (HTTP 422).
12. **Fiscal gates.** On load acceptance, in a fixed sub-order: first the customer must be off credit hold (`ERR_CUSTOMER_CREDIT_HOLD`), then the recomputed margin screen must clear its floor (`ERR_MARGIN_BELOW_FLOOR`) — both HTTP 402.

### 2.10. Resource Identifier Resolution

When an endpoint path carries resource identifiers, each is resolved in strict left-to-right order, and the request is rejected with a 404 the moment an identifier fails to resolve — the failure corresponds to the *first* unresolvable identifier, and later identifiers are never examined. Each resource type has its own not-found error: `ERR_DRIVER_NOT_FOUND`, `ERR_TRACTOR_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_ACCESSORIAL_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_FUEL_RATE_NOT_FOUND`, and `ERR_SAFETY_EVENT_NOT_FOUND` (all HTTP 404). Existence failures therefore always precede body, state, concurrency, and business-rule failures on the same request, per the pipeline order in §2.9.

## 3. Business Logic & Workflows

### 3.1. Fleet and Commercial Master Data

Everything else in the system hangs off five kinds of master data, maintained before the first load is ever tendered.

A `FleetAdmin` registers each driver with a `cdl_number` that is unique across the roster, a `full_name`, a `home_terminal` code, a `hired_at` hire timestamp, and a `last_home_at` timestamp recording when the driver was last at home — the home-time clock described in §3.4 starts from this value. Registration also fixes the pay configuration: `pay_model` is either `MILEAGE` or `PERCENTAGE`, and it must be complete for its kind. A `MILEAGE` driver requires a `pay_rate_cents_per_mile` of at least 1; a `PERCENTAGE` driver requires a `pay_percentage_bp` share of no less than 1 and no more than 10000 basis points. Registering a driver whose pay configuration does not match its model is rejected with `ERR_PAY_CONFIG_INCOMPLETE` (HTTP 422). A new driver starts with `employment_status` `ACTIVE`, `duty_status` `OFF_DUTY` until the first duty event says otherwise, a `safety_score` of 100, and `version` 1. Pay terms and home terminal can later be reconfigured through the OCC-guarded update described in §2.8, which accepts any of `pay_model`, `pay_rate_cents_per_mile`, `pay_percentage_bp`, and `home_terminal`.

Tractors join the fleet through the same administrator, each with a unique `unit_number`, a `home_terminal`, an `odometer_miles` reading that may be zero but never negative, the `current_state_code` where the unit physically sits, a `tank_capacity_gallons` of at least 1, and a `current_fuel_gallons` level that is never negative and never above the tank's capacity. A registered tractor begins `AVAILABLE`. From `AVAILABLE` — and only from `AVAILABLE`, otherwise `ERR_TRACTOR_NOT_AVAILABLE` — a `FleetAdmin` may park a unit as `OUT_OF_SERVICE`, and a unit in `OUT_OF_SERVICE` may be returned to `AVAILABLE` (any other source state draws `ERR_TRACTOR_NOT_OUT_OF_SERVICE`). The `ASSIGNED` state in between is never set directly: it is entered when a trip binds the tractor and left when that trip completes or is cancelled, as §3.3 and §3.5 describe.

Customer accounts are simple but consequential. A `FleetAdmin` creates one with a `name`; it opens in `ACTIVE` status. A `LoadPlanner` may place an `ACTIVE` customer on `CREDIT_HOLD` — doing so from any other status, or releasing a customer that is not on hold, is rejected with `ERR_CUSTOMER_INVALID_STATE` — and may later release the hold back to `ACTIVE`. The hold matters downstream: acceptance of that customer's loads is blocked for as long as it stands (§3.2).

Lanes are the commercial yardstick. A `LoadPlanner` creates a lane with an `origin_state`, a `destination_state`, a benchmark `loaded_miles` of at least 1, and an `rpm_floor_cents` — the minimum acceptable all-in rate per mile, counting revenue against total miles including the deadhead estimate — which may be zero. Every load tendered on the lane is screened against this floor.

Fuel economics come from the StateFuelRate table, maintained by a `FleetAdmin`. Each row pairs a `state_code` — a two-letter state code, or the reserved value `US-NATIONAL` for the national average row that drives fuel-surcharge computation — with a `tax_cents_per_gallon` that may be zero and an `avg_pump_price_cents` of at least 1, effective over a closed window from `effective_from` through `effective_to`, both endpoints inclusive. Omitting `effective_to` (or passing null) leaves the row open-ended. Because the windows are closed intervals, two windows for the same `state_code` conflict whenever the new window starts on or before the existing window's end (or the existing window is open-ended) and the new window's end is open or falls on or after the existing window's start — even windows that merely touch at an endpoint conflict, and the create is rejected with `ERR_FUEL_RATE_WINDOW_OVERLAP` (HTTP 422).

### 3.2. The Load Commercial Lifecycle: Tender, Screen, Accept, Cancel

A load enters the system when a `LoadPlanner` tenders it with a `customer_id` naming the tendering account, a `lane_id` selecting the lane benchmark, a `rate_cents` linehaul rate of at least 1 cent, a `weight_lbs` of at least 1, a `pickup_appt_at`, and a `delivery_appt_at` that must fall strictly after the pickup appointment — a reversal of the two is an `ERR_INVALID_REQUEST`. The tender opens in `TENDERED` status with `reassignment_count` at 0; its `fuel_surcharge_cents`, `projected_margin_cents`, `projected_rpm_cents`, `final_margin_cents`, and `cancellation_fee_cents` do not exist yet, and `total_accessorial_cents` stands at 0.

Screening is the carrier's first profitability gate, run by a `LoadPlanner` against a `TENDERED` load — screening from any other status is rejected with `ERR_LOAD_NOT_TENDERED`. Screening needs a national fuel benchmark: the single StateFuelRate row whose `state_code` is `US-NATIONAL` and whose effective window contains the logical now; if no such row is current, the screen fails with `ERR_FUEL_RATE_UNAVAILABLE`. The fuel surcharge rests on a baseline of 300 cents per gallon: the excess is the amount by which the national row's `avg_pump_price_cents` exceeds that baseline, floored at zero, so a national average at or below 300 cents yields no surcharge at all. `fuel_surcharge_cents` is then the lane's `loaded_miles` multiplied by the excess and divided by the fleet fuel economy of 6.5 miles per gallon — the division carried as an exact rational, equivalently the miles times the excess times two, divided by thirteen — with the final figure rounded half up to whole cents.

The same screen produces the provisional margin picture. Estimated total miles are the lane's `loaded_miles` plus a flat deadhead allowance of 100 miles. Projected revenue is the `rate_cents` linehaul plus the freshly computed `fuel_surcharge_cents`. Projected cost charges every estimated mile at 145 cents of variable operating cost and — because no driver has been assigned yet — a further 62 cents per mile of fleet-average driver pay. `projected_margin_cents` is revenue minus cost, and `projected_rpm_cents` is revenue divided by estimated total miles, rounded half up to whole cents. The load advances from `TENDERED` to `SCREENED` carrying these three figures. A margin read on the load reports `projected_margin_cents`, `projected_rpm_cents`, `final_margin_cents`, and a `floor_pass` flag showing whether the load currently clears the acceptance floor — a non-negative projected margin with a projected rate per mile at or above the lane's `rpm_floor_cents`.

Acceptance re-runs the whole screen against fresher data before committing. Only a `SCREENED` load may be accepted (otherwise `ERR_LOAD_NOT_SCREENED`), and acceptance recomputes the fuel surcharge and the provisional margin and rate-per-mile with the currently effective `US-NATIONAL` row, overwriting the earlier snapshot. Two fiscal gates then apply in a fixed order: first, the tendering customer's `status` must be `ACTIVE`, since acceptance against a customer on `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402); second, the recomputed `projected_margin_cents` must be at least zero and the recomputed `projected_rpm_cents` must reach the lane's `rpm_floor_cents`, failing which the acceptance is rejected with `ERR_MARGIN_BELOW_FLOOR` (HTTP 402). A load that clears both gates moves from `SCREENED` to `ACCEPTED` and becomes dispatchable inventory.

Not every tender is worth keeping. A `LoadPlanner` may reject a load while it is `TENDERED` or `SCREENED` — from any later state, rejection draws `ERR_LOAD_NOT_REJECTABLE` — moving it to the terminal `REJECTED` state with no financial consequence.

Cancellation, by contrast, is priced by how far the booking has progressed, and the resulting `cancellation_fee_cents` — null until the load is actually `CANCELLED` — follows a tiered schedule. Cancelling a `TENDERED` or `SCREENED` load costs nothing: the fee is 0. Cancelling an `ACCEPTED` load costs a flat 15000 cents. Cancelling an `ASSIGNED` or `DISPATCHED` load is a truck-order-not-used event, and the fee is the greater of 25000 cents and ten percent of the `rate_cents` linehaul, rounded half up to whole cents. Cancellation from `IN_TRANSIT` or any later state is not permitted at all and is rejected with `ERR_LOAD_NOT_CANCELLABLE`. When a load in `ASSIGNED` or `DISPATCHED` is cancelled, its non-terminal trip — one in `PLANNED`, `DISPATCHED`, or `AT_PICKUP` — is cancelled with it, the trip's `cancel_reason` recorded as `CUSTOMER`, and the trip's tractor is released from `ASSIGNED` back to `AVAILABLE`. `CANCELLED` is terminal, as are `REJECTED` and `CLOSED`.

### 3.3. Trip Assignment, Dispatch, and Backhaul Matching

A trip is the binding of three resources: a `Dispatcher` creates one by naming a `load_id`, a `driver_id`, and a `tractor_id`, together with the `planned_deadhead_miles` to run empty to pickup (zero or more), the `planned_start_at` dispatch time, and the planned `route_states` — an ordered list of state codes and the miles to be run in each, which may be empty but feeds the fuel machinery of §3.7. Creation is gated, and the gates run in the pipeline order of §2.9: the load must be `ACCEPTED` (any other status draws `ERR_LOAD_NOT_ASSIGNABLE`), the tractor must be `AVAILABLE` (otherwise `ERR_TRACTOR_NOT_AVAILABLE`), and then the safety and regulatory screen of §3.4 applies — the driver's `safety_score` must be at least 60 (a score of exactly 60 passes; below it the create is rejected with `ERR_DRIVER_SAFETY_BELOW_FLOOR`), the four hours-of-service feasibility clauses must all hold (`ERR_HOS_INSUFFICIENT`), and the projected days away from home must not exceed the ceiling (`ERR_HOME_TIME_EXCEEDED`). Finally, the new trip's working window — the half-open interval from `planned_start_at` up to but not including the load's `delivery_appt_at` — must not intersect the corresponding window of any other non-terminal trip the driver holds; intersection is rejected with `ERR_TRIP_OVERLAP`, while two trips that merely touch at a boundary, one ending exactly when the other begins, do not overlap and are allowed.

A trip that clears every gate is created in `PLANNED` status. Creation ripples outward per §2.7: the load moves from `ACCEPTED` to `ASSIGNED` with its `version` incremented, the tractor moves from `AVAILABLE` to `ASSIGNED`, and the driver's provisional pay for the trip is computed immediately into `provisional_pay_cents`. For a `MILEAGE` driver, the provisional figure is the planned total miles — the lane's `loaded_miles` plus the trip's `planned_deadhead_miles` — multiplied by the driver's `pay_rate_cents_per_mile`. For a `PERCENTAGE` driver, it is the load's `rate_cents` multiplied by the driver's `pay_percentage_bp` and divided by 10000, rounded half up to whole cents — a linehaul-only base, since surcharges are not yet in it.

While the trip remains `PLANNED`, a `Dispatcher` may replan it, changing any of `planned_deadhead_miles`, `planned_start_at`, and `route_states`; replanning a trip in any other state is rejected with `ERR_TRIP_NOT_PLANNED`. The replan is OCC-guarded by `expected_trip_version` as described in §2.8, re-runs the full safety-and-temporal screen — the safety floor, the four feasibility clauses, the home-time ceiling, and the overlap rule — against the revised inputs, recomputes `provisional_pay_cents`, and increments the trip's `version`.

Dispatching commits the plan to the road. A `Dispatcher` may dispatch only a `PLANNED` trip (otherwise `ERR_TRIP_NOT_PLANNED`) whose load still stands at `ASSIGNED` (otherwise `ERR_LOAD_NOT_ASSIGNABLE`) and whose driver is `ACTIVE` (otherwise `ERR_DRIVER_NOT_ACTIVE`). At dispatch, the tractor's current `odometer_miles` is frozen into the trip's `start_odometer_miles` — the baseline every later odometer report is measured against — the trip advances from `PLANNED` to `DISPATCHED`, and the load moves from `ASSIGNED` to `DISPATCHED` with it.

A trip that will not run is cancelled instead. A `Dispatcher` may cancel a trip in `PLANNED`, `DISPATCHED`, or `AT_PICKUP`; from `IN_TRANSIT`, `AT_DELIVERY`, or any terminal state the attempt is rejected with `ERR_TRIP_NOT_CANCELLABLE`. The optional `reason` in the request accepts only `REASSIGN` or `CUSTOMER`, defaulting to `REASSIGN` when omitted, and any other value is an invalid enum member rejected with `ERR_INVALID_REQUEST`; the third `cancel_reason`, `SAFETY`, is reserved for the system-initiated cascades of §3.8 and is never set from a client request. Cancellation rolls the booking back for another attempt: the load returns from `ASSIGNED` or `DISPATCHED` to `ACCEPTED`, its `reassignment_count` increments by one, and the tractor is released from `ASSIGNED` to `AVAILABLE`. `COMPLETED` and `CANCELLED` are the trip's terminal states.

Dispatchers also work the other side of the empty-mile problem. The backhaul board ranks candidate loads for a given `tractor_id`, optionally narrowed by a `driver_id` and a `limit`. Eligible candidates are loads in `SCREENED` or `ACCEPTED` — an `ACCEPTED` load by construction has no non-terminal trip, since assignment would have moved it to `ASSIGNED` — and loads still `TENDERED` never appear, because they carry no fuel surcharge until screened. Each candidate's estimated deadhead is zero when the lane's `origin_state` matches the tractor's `current_state_code`, and 250 miles otherwise. The effective rate per mile is the candidate's `rate_cents` plus its `fuel_surcharge_cents`, divided by the lane's `loaded_miles` plus the deadhead estimate, rounded half up to whole cents. Candidates rank by that effective rate per mile descending; ties break toward the earlier `pickup_appt_at`, then toward the earlier load `created_at`. When `driver_id` is supplied, any candidate that would fail the hours-of-service feasibility screen for that driver is excluded from the list. An empty board is not an error: the response is 200 with an empty array.

### 3.4. Hours-of-Service Accounting and Trip Feasibility

Every driver carries a duty-event stream, and the entire hours-of-service apparatus is a projection over it. A `Driver` appends events to their own record, or a `Dispatcher` appends them on the driver's behalf; appending to a suspended or terminated driver is rejected with `ERR_DRIVER_NOT_ACTIVE`, since the driver must be `ACTIVE`. Each event carries an `event_type` of `OFF_DUTY`, `SLEEPER`, `DRIVING`, or `ON_DUTY`, an `occurred_at` timestamp, an optional `trip_id` linking the event to the trip being worked, and an `at_home` flag that defaults to false and is meaningful only on `OFF_DUTY` events — recording `OFF_DUTY` with `at_home` set true moves the driver's `last_home_at` to the event's `occurred_at`. An `occurred_at` after the logical now fails request validation with `ERR_INVALID_REQUEST`; one that does not fall strictly after the driver's previous event is rejected with `ERR_DUTY_EVENT_OUT_OF_ORDER`, so the stream is strictly increasing in time by construction. Each appended event rewrites the driver's `duty_status` to the event's `event_type`. A driver's event history reads back in `occurred_at` ascending order.

From that stream, three clocks and a break flag are projected at the logical now, and a driver's hours-of-service status reports `drive_11h_remaining_minutes`, `window_14h_remaining_minutes`, `cycle_70h_remaining_minutes`, `break_blocked`, and the mirrored `duty_status`. Consecutive events define half-open intervals: each interval runs from its event's `occurred_at` to the next event's `occurred_at` and is typed by the earlier event's `event_type`, with the final interval ending at the logical now. A **long-off run** is a maximal contiguous sequence of `OFF_DUTY` and `SLEEPER` intervals whose durations total at least 600 minutes — ten hours.

- The 11-hour driving clock, `drive_11h_remaining_minutes`, is 660 minutes minus the `DRIVING` minutes accumulated since the end of the most recent long-off run; a driver currently inside a long-off run has the full 660 minutes available.
- The 14-hour window clock, `window_14h_remaining_minutes`, is the full 840 minutes while the driver is inside a long-off run, and otherwise the greater of zero and 840 minutes minus the time elapsed from the end of the most recent long-off run to the logical now.
- A **restart run** is a contiguous sequence of `OFF_DUTY` and `SLEEPER` intervals totalling at least 2040 minutes — 34 hours; a run of exactly 34 hours qualifies — and it resets the cycle accumulator at the moment the run ends. The cycle window then begins at the later of two instants: 10080 minutes (seven days) before the logical now, or the end of the most recent restart run ending at or before the logical now. The 70-hour cycle clock, `cycle_70h_remaining_minutes`, is 4200 minutes minus the combined `DRIVING` and `ON_DUTY` minutes falling inside that window, the window's starting instant included.
- `break_blocked` is true when the `DRIVING` minutes accumulated since the end of the driver's most recent `OFF_DUTY` or `SLEEPER` run of at least 30 minutes reach 480 — eight hours behind the wheel without a qualifying break.

Recording duty is not itself blocked by the clocks, but illegal driving is punished. A `DRIVING` event appended while `break_blocked` is true, or while any of the three remaining-minutes clocks stands at zero, is still recorded — and it also auto-creates a SafetyEvent of kind `HOS_VIOLATION` with `severity_points` 5 and `source` `AUTO_HOS`, which immediately recomputes the driver's `safety_score` as described in §3.8.

The same projection drives the feasibility screen applied at trip creation and replan. The required drive time, in whole minutes, is the planned total miles — the lane's `loaded_miles` plus the trip's `planned_deadhead_miles` — multiplied by 60 and divided by the planning speed of 50 miles per hour, rounded up to the next whole minute. Four clauses are then evaluated at the logical now:

1. The driver's `drive_11h_remaining_minutes` must be at least the smaller of the required drive time and 660 minutes.
2. The driver's `cycle_70h_remaining_minutes` must be at least the required drive time.
3. 660 minutes, multiplied by one plus the number of whole 1440-minute days between the logical now and the load's `delivery_appt_at` (the quotient rounded down), must be at least the required drive time — each full day of runway adds another full driving shift of capacity.
4. The required drive time plus its mandatory rest overhead — 600 minutes for every additional 660-minute driving block beyond the first, computed as 600 multiplied by the rounded-down quotient of the required drive time minus one, divided by 660 — must not exceed the total minutes between the logical now and the load's `delivery_appt_at`.

If any clause fails, the create or replan is rejected with `ERR_HOS_INSUFFICIENT` (HTTP 422). Home time is checked separately, after the HOS clauses: the number of whole 24-hour days between the driver's `last_home_at` and the load's `delivery_appt_at`, rounded down, must be at most 14 — a projection of exactly 14 days passes — and a longer projection is rejected with `ERR_HOME_TIME_EXCEEDED` (HTTP 422).

### 3.5. Trip Execution: Check Calls, Completion, ETA, and Detention Capture

Once dispatched, a trip reports its progress through check calls, recorded by the trip's `Driver` or by a `Dispatcher` on the driver's behalf. Each call carries a `kind`, an `occurred_at`, a `state_code`, and an `odometer_miles` reading. The four milestone kinds carry a strict rank — `ARRIVED_PICKUP` is rank 1, `DEPARTED_PICKUP` rank 2, `ARRIVED_DELIVERY` rank 3, and `DELIVERED` rank 4 — and each milestone must advance beyond the rank of the trip's previous milestone. `EN_ROUTE` reports carry no rank and may be interleaved while the trip is `DISPATCHED` or `IN_TRANSIT` without disturbing the sequence; an `EN_ROUTE` report in any other trip state is out of order. An `occurred_at` after the logical now fails request validation with `ERR_INVALID_REQUEST`, while one that falls before the trip's previous check call is rejected with `ERR_CHECK_CALL_OUT_OF_ORDER` (HTTP 422). The same 422 rejection meets a kind that regresses the milestone rank, an `odometer_miles` below the previous report's reading, a first report whose odometer reads below the trip's `start_odometer_miles`, and any check call at all against a `PLANNED` or terminal trip.

Each milestone moves the machinery. `ARRIVED_PICKUP` advances the trip from `DISPATCHED` to `AT_PICKUP`. `DEPARTED_PICKUP` advances it from `AT_PICKUP` to `IN_TRANSIT` and moves the load from `DISPATCHED` to `IN_TRANSIT` alongside it. `ARRIVED_DELIVERY` advances the trip from `IN_TRANSIT` to `AT_DELIVERY`. `DELIVERED` completes the trip, and completion is the busiest moment in the system. The report's `occurred_at` becomes the trip's `completed_at`; `actual_miles` is the report's odometer minus the `start_odometer_miles` snapshot taken at dispatch; `pay_miles` is the greater of `actual_miles` and the planned total of lane `loaded_miles` plus `planned_deadhead_miles`. Final pay replaces the provisional figure in `final_pay_cents`: for a `MILEAGE` driver, `pay_miles` multiplied by `pay_rate_cents_per_mile`; for a `PERCENTAGE` driver, the sum of the load's `rate_cents` and `fuel_surcharge_cents` multiplied by `pay_percentage_bp` and divided by 10000, rounded half up to whole cents — so the final figure differs from the provisional one whenever actual miles exceed the plan or a surcharge exists. The tractor is released from `ASSIGNED` back to `AVAILABLE`, its `odometer_miles` reset to the `DELIVERED` report's reading, its `current_state_code` reset to the report's `state_code`, and its `current_fuel_gallons` reduced by the trip's fuel burn — the `actual_miles` divided by 6.5 miles per gallon, rounded up to the next whole gallon — but never below zero. Finally, the load moves from `IN_TRANSIT` to `DELIVERED`, which triggers detention evaluation.

Detention is measured against the load's appointments, leg by leg. Each leg anchors at the later of its arrival report and its appointment: the pickup leg anchors at the later of the `ARRIVED_PICKUP` report's `occurred_at` and the load's `pickup_appt_at`, and the delivery leg anchors at the later of the `ARRIVED_DELIVERY` report and the `delivery_appt_at`. From its anchor, each leg grants 120 free minutes — two hours. On the pickup leg, billable time runs from the anchor to the `DEPARTED_PICKUP` report; on the delivery leg, from the anchor to the `DELIVERED` report; the billable minutes are the elapsed minutes beyond the free allowance, never below zero. Exactly 120 elapsed minutes produces nothing, while a single minute beyond the allowance produces one billable minute, and the charge is the billable minutes divided into 15-minute increments, rounded up, at 1500 cents per increment. For each leg whose billable minutes exceed zero, an AccessorialCharge is created in `PENDING` status with `type` `DETENTION_PICKUP` or `DETENTION_DELIVERY` as the leg dictates, `quantity` set to the billable minutes, `amount_cents` per the increment formula, `source` `AUTO_DETENTION`, and `trip_id` bound to the completing trip. If a leg's arrival anchor is missing — no arrival report for that leg was ever recorded — that leg materializes nothing automatically; the manual claim path of §3.6 remains open.

While the trip runs, anyone may ask where it stands. The ETA projection works from the most recent check call: `remaining_miles` is the greater of zero and the planned total miles minus the miles actually covered, where miles covered is the latest report's `odometer_miles` minus the trip's `start_odometer_miles`. If no check call has been recorded yet, the remaining miles equal the full planned total and the projection base is the trip's `planned_start_at`. Driving time is the remaining miles multiplied by 60 and divided by 50 miles per hour, rounded up to whole minutes. Break time adds 30 minutes for every additional 480-minute driving block beyond the first — 30 multiplied by the rounded-down quotient of the driving minutes minus one, divided by 480 — so no break time accrues at or under 480 minutes of driving. Rest time adds 600 minutes for every additional 660-minute driving block beyond the first, computed the same way against 660, so no rest accrues at or under 660 minutes. With check calls present, the projection base is the later of the logical now and the latest report's `occurred_at`. The projected `eta_at` is that base plus driving, break, and rest minutes, and the `late` flag is set only when `eta_at` falls strictly after the load's `delivery_appt_at` — arriving exactly at the appointment is not late. The projection response carries `eta_at`, `late`, `remaining_miles`, `drive_minutes`, `break_minutes`, and `rest_minutes`.

### 3.6. Accessorial Adjudication and Invoicing

Beyond auto-created detention, a `Dispatcher` — or a `Driver` with a trip on the load — may capture a manual accessorial charge against a load, naming its `type`, a `quantity` of at least 1, and optionally a `trip_id`. The `Driver` caller must have driven some trip of that load, otherwise `ERR_DRIVER_MISMATCH`. Five types exist, and `quantity` means something different for each: minutes of detention for `DETENTION_PICKUP` and `DETENTION_DELIVERY`, days for `LAYOVER`, a stop count for `STOP_OFF`, and — for `LUMPER`, a receipt passthrough — the amount itself in cents. The charge's `amount_cents` is computed, never supplied: manual detention prices by the same increment rule as automatic detention, the `quantity` minutes divided into 15-minute increments rounded up at 1500 cents per increment; `LAYOVER` prices at 30000 cents per day; `STOP_OFF` at 10000 cents per stop; `LUMPER` passes its `quantity` straight through as the amount. A manual charge is created in `PENDING` status with `source` `MANUAL`. One hard rule protects against double-billing a dock: a load may carry at most one non-`REJECTED` `DETENTION_PICKUP` charge, and likewise at most one non-`REJECTED` `DETENTION_DELIVERY` charge; a second open claim of the same leg type is rejected with `ERR_DUPLICATE_ACCESSORIAL_TYPE`.

From `PENDING`, a charge enters adjudication. Submission by a `Dispatcher` or an eligible `Driver` moves it from `PENDING` to `SUBMITTED`, and a disputed charge re-enters the same way — submission is admissible only from `PENDING` or `DISPUTED`, and from anywhere else is rejected with `ERR_ACCESSORIAL_NOT_SUBMITTABLE`. A `LoadPlanner` then decides: approval moves `SUBMITTED` to `APPROVED` (from any other state, `ERR_ACCESSORIAL_NOT_APPROVABLE`); disputing moves `SUBMITTED` to `DISPUTED` (from any other state, `ERR_ACCESSORIAL_NOT_DISPUTABLE`); and rejection is possible from `SUBMITTED` or `DISPUTED` (otherwise `ERR_ACCESSORIAL_NOT_REJECTABLE`) and lands in the terminal `REJECTED` state. The `DISPUTED` to `SUBMITTED` resubmission is the cycle's only loop.

Billing is the invoice's doing. An invoice is created by a `LoadPlanner` against a load that has reached `DELIVERED` — creating one against a load in any other status is rejected with `ERR_INVOICE_NOT_ISSUABLE` — and a load may have at most one non-`VOID` invoice at a time, a second attempt drawing `ERR_INVOICE_ALREADY_EXISTS`. At creation the invoice is `DRAFT` and snapshots the load's `rate_cents` into `linehaul_cents` and the load's `fuel_surcharge_cents` into its own `fuel_surcharge_cents`; `accessorial_total_cents` stands at 0 until issue. Reading a load's invoice yields an array of at most one entry, `VOID` invoices excluded.

Issuing is the point of no return for the load's billing. The invoice must be `DRAFT` and the load still `DELIVERED` — either violation is `ERR_INVOICE_NOT_ISSUABLE` — and no accessorial of the load may remain open: any charge in `PENDING`, `SUBMITTED`, or `DISPUTED` blocks the issue with `ERR_INVOICE_OPEN_ACCESSORIALS`, leaving `APPROVED`, `BILLED`, and `REJECTED` charges admissible. On issue, every `APPROVED` accessorial of the load flips to `BILLED`; `accessorial_total_cents` becomes the sum of those newly billed amounts; `total_cents` is the sum of `linehaul_cents`, `fuel_surcharge_cents`, and `accessorial_total_cents`; and the invoice moves from `DRAFT` to `ISSUED`. The same event moves the load from `DELIVERED` to `INVOICED` and computes the final margin: revenue is now the `rate_cents` linehaul plus the snapshotted `fuel_surcharge_cents` plus the newly billed accessorial total; miles are the completing trip's `actual_miles`; cost is those miles at the same 145-cent variable rate plus the trip's `final_pay_cents`; and `final_margin_cents` is the difference. Because actuals replace estimates and accessorials enter revenue, the final figure differs from the provisional screen even for identical tender data. The load's `total_accessorial_cents` is recomputed to include the newly billed charges.

Two exits follow. Marking an `ISSUED` invoice paid — from any other state, `ERR_INVOICE_NOT_PAYABLE` — moves it to the terminal `PAID` state and closes the load, `INVOICED` to `CLOSED`. Voiding an `ISSUED` invoice — from any other state, `ERR_INVOICE_NOT_VOIDABLE` — is the compensating unwind: the invoice lands in the terminal `VOID` state, every `BILLED` accessorial of the load flips back to `APPROVED`, the load returns from `INVOICED` to `DELIVERED` with its `final_margin_cents` cleared to null, and the load's `total_accessorial_cents` is recomputed with no billed charges remaining.

### 3.7. Fuel Purchasing and Stop Planning

Fuel is bought on the road and booked against the trip. A purchase may be recorded by the trip's `Driver` or by a `Dispatcher`, but only while the trip is between `DISPATCHED` and `AT_DELIVERY` inclusive — a purchase against a `PLANNED`, `COMPLETED`, or `CANCELLED` trip is rejected with `ERR_TRIP_NOT_FUELABLE`. The payload names the `driver_id`, which must equal the trip's driver — and, when the caller acts in the `Driver` role, must equal `X-User-ID` as well, with any mismatch rejected as `ERR_DRIVER_MISMATCH` — plus the `state_code` of the purchase, a whole number of `gallons` of at least 1, a `pump_price_cents` of at least 1, and a `purchased_at` that may not fall after the logical now (a future timestamp is an `ERR_INVALID_REQUEST`). The purchase state must lie on the trip's planned route: a `state_code` absent from the trip's `route_states` is rejected with `ERR_STATE_NOT_ON_ROUTE`.

Costing follows the IFTA-style principle that state fuel tax is equalized across jurisdictions, so the economically comparable price is the pump price net of tax. The current StateFuelRate row for the purchase's `state_code` — the one whose effective window contains the logical now — supplies the tax; if no such row is current, the purchase is rejected with `ERR_FUEL_RATE_UNAVAILABLE`. The recorded figures are then `total_cost_cents`, the `gallons` multiplied by the `pump_price_cents`; `tax_paid_cents`, the `gallons` multiplied by the row's `tax_cents_per_gallon`; and `net_effective_price_cents`, the `pump_price_cents` minus the row's `tax_cents_per_gallon`. The purchase also lands in the tank: the tractor's `current_fuel_gallons` increases by the `gallons` bought, and a purchase that would push the level above the tractor's `tank_capacity_gallons` is rejected with `ERR_TANK_CAPACITY_EXCEEDED`.

The same net-of-tax logic drives stop planning. The fuel-plan query for a trip first computes how far the tractor can reach: the range in miles is the tractor's `current_fuel_gallons` multiplied by the fleet economy of 6.5 miles per gallon, rounded down to whole miles. Walking the trip's `route_states` in order, the cumulative miles to enter each state are the sum of the miles of every route segment before it. A route state is eligible when the cumulative miles to enter it do not exceed the range and a StateFuelRate row for that `state_code` is currently effective. Each eligible state's effective price is its `avg_pump_price_cents` minus its `tax_cents_per_gallon`. The plan ranks eligible states by effective price ascending; a tie breaks toward the higher `tax_cents_per_gallon`, since tax paid there is recovered through equalization; a further tie breaks toward the state earlier in the route order. The response names the winning `recommended_state`, its `effective_price_cents`, and the ranked `candidates`. A trip with an empty `route_states` list, or one whose reachable states all lack a current rate, has no plan and the query is rejected with `ERR_FUEL_PLAN_INFEASIBLE`.

### 3.8. Safety Scoring and Employment Actions

The safety record is an event log with a decaying memory. A `SafetyOfficer` records manual safety events against a driver: a `kind` of `INSPECTION_VIOLATION` or `CRASH_AT_FAULT`, an optional `severity_points` penalty that, when supplied, must be no less than 1 and no more than 100, and an `occurred_at` that may not fall after the logical now. The third kind, `HOS_VIOLATION`, is reserved to the system — it arises only from the illegal-driving rule of §3.4 with `source` `AUTO_HOS` — and an attempt to record one manually is rejected with `ERR_INVALID_REQUEST`. Manual events carry `source` `MANUAL`. Every event opens with `voided` false; a `SafetyOfficer` may later void one as a compensating action, setting `voided` true, and voiding an already-voided event is rejected with `ERR_SAFETY_EVENT_NOT_VOIDABLE`.

A driver's `safety_score` starts at 100 and is recomputed immediately whenever an event is recorded or voided. Every non-voided event contributes its `severity_points`, weighted by age at the logical now: full weight while the event is at most 8760 hours old — 365 days, the boundary included; half weight while it is older than that but at most 17520 hours old — 730 days, again with the boundary included; and no weight at all beyond that. Because half-weight penalties can yield fractional totals, the weighted penalty sum is rounded half up to a whole number before it is subtracted from 100, and the result is floored at zero. The score gates dispatch: at trip creation and replan, a driver whose score has fallen below 60 is rejected with `ERR_DRIVER_SAFETY_BELOW_FLOOR`, while a score of exactly 60 passes.

Employment actions sit on a parallel track from duty status. A driver's `employment_status` — `ACTIVE`, `SUSPENDED`, or the terminal `TERMINATED` — is entirely independent of the `duty_status` mirror of the event stream; suspending a driver, in particular, does not rewrite their `duty_status`. A `SafetyOfficer` suspends an `ACTIVE` driver — suspension from any other state is rejected with `ERR_DRIVER_NOT_ACTIVE` — and the suspension cascades through the dispatch book: every non-terminal trip of the driver, meaning each in `PLANNED`, `DISPATCHED`, or `AT_PICKUP`, is cancelled with `cancel_reason` `SAFETY`, and each such cancellation rolls its load back to `ACCEPTED` with `reassignment_count` incremented by one and releases its tractor from `ASSIGNED` to `AVAILABLE`. Reinstatement by a `SafetyOfficer` returns a `SUSPENDED` driver to `ACTIVE` — from any other state, `ERR_DRIVER_NOT_SUSPENDED`. Termination by a `FleetAdmin` lands from `ACTIVE` or `SUSPENDED` — acting on a driver already `TERMINATED` is rejected with `ERR_DRIVER_ALREADY_TERMINATED` — and applies the same trip cascade as suspension, cancelling every non-terminal trip with `cancel_reason` `SAFETY` and the same per-trip rollback of load and tractor. A terminated driver is never again eligible for the settlement guarantee described in §3.9.

### 3.9. Payroll Settlement

Payroll runs per driver over a half-open period. A `PayrollClerk` generates a settlement by naming the `driver_id`, a `period_start`, and a `period_end` that must fall strictly after the start — an inversion is an `ERR_INVALID_REQUEST`. The period is the half-open interval from `period_start` inclusive to `period_end` exclusive, and it must not intersect any existing settlement period for the same driver; an intersection is rejected with `ERR_SETTLEMENT_PERIOD_OVERLAP`, while two periods that merely touch, one ending exactly where the next begins, do not overlap and are allowed. The new settlement opens in `DRAFT` status with `created_by_id` stamped from the caller's `X-User-ID`, `approved_by_id` null until approval, and its pay components computed at once.

The gross-pay computation proceeds in a pinned order. Trips in scope are the driver's trips in `COMPLETED` status whose `completed_at` falls at or after `period_start` and strictly before `period_end` — a trip completing exactly at `period_end` belongs to the next period. `trip_pay_cents` is the sum of those trips' `final_pay_cents`, each already rounded when the trip completed. `accessorial_share_cents` is the driver's quarter share of billed accessorials on the loads those trips hauled: for each `BILLED` AccessorialCharge, the `amount_cents` is multiplied by 2500 basis points — twenty-five percent — and rounded half up to whole cents per charge, and only then are the per-charge amounts summed; summing first and rounding once would produce a different, non-conforming figure. The subtotal is `trip_pay_cents` plus `accessorial_share_cents` plus `manual_adjustment_cents`, and it is computed first, deliberately excluding any guarantee. Only then does the weekly minimum apply: when the driver is not `TERMINATED` and at least one `COMPLETED` trip falls in scope, `guarantee_top_up_cents` is the greater of zero and 120000 cents — a $1,200 weekly floor — minus the subtotal; in every other case it is zero, and a subtotal of exactly 120000 cents yields a top-up of zero. `gross_pay_cents` is the subtotal plus the top-up.

While the settlement remains `DRAFT`, a `PayrollClerk` may recalculate it, recomputing every component from current data and replacing `manual_adjustment_cents` with a supplied value — which may be negative — that defaults to 0 when omitted. The recalculation is OCC-guarded by `expected_settlement_version` per §2.8 and increments the settlement's `version`; recalculating in any other status is rejected with `ERR_SETTLEMENT_NOT_DRAFT`. Submission moves a `DRAFT` settlement to `PENDING_APPROVAL` (from any other state, `ERR_SETTLEMENT_NOT_DRAFT`). Approval is where segregation of duties bites: the approver's `X-User-ID` must differ from the settlement's `created_by_id`, and a self-approval is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403); approval from any state other than `PENDING_APPROVAL` is `ERR_SETTLEMENT_NOT_PENDING_APPROVAL`. A successful approval stamps `approved_by_id` with the approver's `X-User-ID` and moves the settlement to `APPROVED`. A settlement that needs rework is instead rejected from `PENDING_APPROVAL` back to `DRAFT` — again, `ERR_SETTLEMENT_NOT_PENDING_APPROVAL` from any other state — where recalculation may begin again. Finally, marking an `APPROVED` settlement paid — from any other state, `ERR_SETTLEMENT_NOT_APPROVED` — lands it in the terminal `PAID` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, transition, or compute against existing resources return `200 OK`. The narratives of §2 and §3 define each endpoint's request payload, guards, and side effects; the table below is only a structural index. "All roles" means `FleetAdmin`, `LoadPlanner`, `Dispatcher`, `SafetyOfficer`, `PayrollClerk`, and `Driver`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z; no wall-clock fallback) | FleetAdmin |
| POST | `/drivers` | Register a driver | FleetAdmin |
| GET | `/drivers` | List drivers, optional `status` filter | All roles |
| GET | `/drivers/{id}` | Get a driver | All roles |
| PATCH | `/drivers/{id}` | Update driver pay/home-terminal config (OCC-guarded) | FleetAdmin |
| POST | `/drivers/{id}/suspend` | Suspend a driver; cancels non-terminal trips with SAFETY cascade | SafetyOfficer |
| POST | `/drivers/{id}/reinstate` | Reinstate a suspended driver | SafetyOfficer |
| POST | `/drivers/{id}/terminate` | Terminate a driver; same trip cascade as suspend | FleetAdmin |
| GET | `/drivers/{id}/hos-status` | Computed HOS projection at the logical now | All roles |
| GET | `/drivers/{id}/duty-events` | List a driver's duty events (`occurred_at` ascending) | All roles |
| POST | `/drivers/{id}/duty-events` | Append a duty event; illegal DRIVING auto-creates an HOS_VIOLATION safety event | Driver, Dispatcher |
| GET | `/drivers/{id}/safety-events` | List a driver's safety events | All roles |
| POST | `/drivers/{id}/safety-events` | Record a manual safety event (INSPECTION_VIOLATION or CRASH_AT_FAULT only) | SafetyOfficer |
| GET | `/safety-events/{id}` | Get a safety event | All roles |
| POST | `/safety-events/{id}/void` | Void a safety event; recomputes the driver's score | SafetyOfficer |
| GET | `/drivers/{id}/fuel-purchases` | List fuel purchases made by a driver | All roles |
| GET | `/drivers/{id}/settlements` | List a driver's settlements | All roles |
| POST | `/tractors` | Register a tractor | FleetAdmin |
| GET | `/tractors` | List tractors, optional `status` filter | All roles |
| GET | `/tractors/{id}` | Get a tractor | All roles |
| POST | `/tractors/{id}/out-of-service` | Mark an AVAILABLE tractor out of service | FleetAdmin |
| POST | `/tractors/{id}/return-to-service` | Return an OUT_OF_SERVICE tractor to service | FleetAdmin |
| GET | `/tractors/{id}/trips` | List trips of a tractor | All roles |
| POST | `/customers` | Create a customer account | FleetAdmin |
| GET | `/customers` | List customers | All roles |
| GET | `/customers/{id}` | Get a customer | All roles |
| POST | `/customers/{id}/credit-hold` | Place an ACTIVE customer on credit hold | LoadPlanner |
| POST | `/customers/{id}/release-credit-hold` | Release a customer credit hold | LoadPlanner |
| GET | `/customers/{id}/loads` | List loads of a customer | All roles |
| POST | `/lanes` | Create a lane benchmark | LoadPlanner |
| GET | `/lanes` | List lanes | All roles |
| GET | `/lanes/{id}` | Get a lane | All roles |
| POST | `/state-fuel-rates` | Create a fuel-rate window (closed-interval overlap per state rejected) | FleetAdmin |
| GET | `/state-fuel-rates` | List fuel rates, optional `state_code` filter | All roles |
| GET | `/state-fuel-rates/{id}` | Get a fuel rate | All roles |
| POST | `/loads` | Tender a load | LoadPlanner |
| GET | `/loads` | List loads with `status`, `customer_id`, `lane_id` filters | All roles |
| GET | `/loads/{id}` | Get a load | All roles |
| POST | `/loads/{id}/screen` | Run the lane profitability screen (provisional margin + fuel surcharge) | LoadPlanner |
| POST | `/loads/{id}/accept` | Accept a screened load (customer credit + margin floor gates) | LoadPlanner |
| POST | `/loads/{id}/reject` | Reject a tendered or screened load | LoadPlanner |
| POST | `/loads/{id}/cancel` | Cancel a load with tiered cancellation fee; cancels its non-terminal trip | LoadPlanner |
| GET | `/loads/{id}/margin` | Margin read: provisional vs final side by side, with `floor_pass` | All roles |
| GET | `/loads/{id}/trips` | List trips of a load | All roles |
| GET | `/loads/{id}/accessorials` | List accessorial charges of a load | All roles |
| POST | `/loads/{id}/accessorials` | Create a manual accessorial charge (PENDING) | Dispatcher, Driver |
| GET | `/loads/{id}/invoice` | Get the load's invoice (array of 0-1; VOID excluded) | All roles |
| POST | `/trips` | Create a trip: HOS feasibility, safety floor, home-time, overlap, tractor gates | Dispatcher |
| GET | `/trips` | List trips with `driver_id`, `tractor_id`, `load_id`, `status` filters | All roles |
| GET | `/trips/{id}` | Get a trip | All roles |
| PATCH | `/trips/{id}` | Replan a PLANNED trip (OCC-guarded) | Dispatcher |
| POST | `/trips/{id}/dispatch` | Dispatch a PLANNED trip; snapshots start odometer | Dispatcher |
| POST | `/trips/{id}/cancel` | Cancel a non-terminal trip (`reason` accepts REASSIGN or CUSTOMER) | Dispatcher |
| GET | `/trips/{id}/eta` | Computed ETA against the delivery appointment | All roles |
| GET | `/trips/{id}/fuel-plan` | Fuel purchase optimization by state tax | All roles |
| GET | `/trips/{id}/check-calls` | List check calls of a trip | All roles |
| POST | `/trips/{id}/check-calls` | Record a check call; drives trip/load transitions and completion cascade | Driver, Dispatcher |
| GET | `/trips/{id}/duty-events` | List duty events linked to a trip | All roles |
| GET | `/trips/{id}/accessorials` | List accessorial charges linked to a trip | All roles |
| POST | `/trips/{id}/fuel-purchases` | Record a fuel purchase (trip must be DISPATCHED..AT_DELIVERY) | Driver, Dispatcher |
| GET | `/trips/{id}/fuel-purchases` | List fuel purchases of a trip | All roles |
| GET | `/accessorials/{id}` | Get an accessorial charge | All roles |
| POST | `/accessorials/{id}/submit` | Submit a PENDING or DISPUTED charge (DISPUTED resubmission cycle) | Dispatcher, Driver |
| POST | `/accessorials/{id}/approve` | Approve a SUBMITTED charge | LoadPlanner |
| POST | `/accessorials/{id}/dispute` | Dispute a SUBMITTED charge | LoadPlanner |
| POST | `/accessorials/{id}/reject` | Reject a SUBMITTED or DISPUTED charge (terminal) | LoadPlanner |
| POST | `/settlements` | Generate a DRAFT settlement for a driver and half-open period | PayrollClerk |
| GET | `/settlements` | List settlements with `driver_id`, `status` filters | All roles |
| GET | `/settlements/{id}` | Get a settlement | All roles |
| POST | `/settlements/{id}/recalculate` | Recompute a DRAFT settlement, optionally applying `manual_adjustment_cents` (OCC-guarded) | PayrollClerk |
| POST | `/settlements/{id}/submit` | Submit a DRAFT settlement for approval | PayrollClerk |
| POST | `/settlements/{id}/reject` | Reject a PENDING_APPROVAL settlement back to DRAFT (rework cycle) | PayrollClerk |
| POST | `/settlements/{id}/approve` | Approve a PENDING_APPROVAL settlement; approver must differ from creator | PayrollClerk |
| POST | `/settlements/{id}/mark-paid` | Mark an APPROVED settlement paid (terminal) | PayrollClerk |
| POST | `/loads/{id}/invoice` | Create a DRAFT invoice for a DELIVERED load (at most one non-VOID per load) | LoadPlanner |
| GET | `/invoices/{id}` | Get an invoice | All roles |
| POST | `/invoices/{id}/issue` | Issue a DRAFT invoice (requires all accessorials terminal) | LoadPlanner |
| POST | `/invoices/{id}/void` | Void an ISSUED invoice (compensating cascade) | LoadPlanner |
| POST | `/invoices/{id}/mark-paid` | Mark an ISSUED invoice paid; closes the load | LoadPlanner |
| GET | `/dispatch/backhaul-candidates` | Ranked backhaul/empty-mile candidates for a tractor | Dispatcher |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the guarded workflow is described; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DRIVER_MISMATCH` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_TRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_LANE_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_ACCESSORIAL_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_FUEL_RATE_NOT_FOUND` | 404 Not Found |
| `ERR_SAFETY_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_ACTIVE` | 409 Conflict |
| `ERR_DRIVER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_DRIVER_ALREADY_TERMINATED` | 409 Conflict |
| `ERR_TRACTOR_NOT_AVAILABLE` | 409 Conflict |
| `ERR_TRACTOR_NOT_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_CUSTOMER_INVALID_STATE` | 409 Conflict |
| `ERR_LOAD_NOT_TENDERED` | 409 Conflict |
| `ERR_LOAD_NOT_SCREENED` | 409 Conflict |
| `ERR_LOAD_NOT_REJECTABLE` | 409 Conflict |
| `ERR_LOAD_NOT_ASSIGNABLE` | 409 Conflict |
| `ERR_LOAD_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_TRIP_NOT_PLANNED` | 409 Conflict |
| `ERR_TRIP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_TRIP_NOT_FUELABLE` | 409 Conflict |
| `ERR_ACCESSORIAL_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_ACCESSORIAL_NOT_APPROVABLE` | 409 Conflict |
| `ERR_ACCESSORIAL_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_ACCESSORIAL_NOT_REJECTABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PENDING_APPROVAL` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_SAFETY_EVENT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_DRIVER_SAFETY_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_HOS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_HOME_TIME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRIP_OVERLAP` | 422 Unprocessable Entity |
| `ERR_CHECK_CALL_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_DUTY_EVENT_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_FUEL_RATE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_PAY_CONFIG_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACCESSORIAL_TYPE` | 422 Unprocessable Entity |
| `ERR_INVOICE_OPEN_ACCESSORIALS` | 422 Unprocessable Entity |
| `ERR_FUEL_RATE_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_STATE_NOT_ON_ROUTE` | 422 Unprocessable Entity |
| `ERR_TANK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FUEL_PLAN_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 Payment Required |
| `ERR_MARGIN_BELOW_FLOOR` | 402 Payment Required |
| `ERR_SEGREGATION_OF_DUTY` | 403 Forbidden |
