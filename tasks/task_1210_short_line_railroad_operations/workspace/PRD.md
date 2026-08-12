# Short Line Railroad Operations API — Product Requirements Document

## 1. Introduction

A short line railroad earns its keep in the space between a local shipper's loading dock and the national rail network. It takes customer orders for empty freight cars, switches industry sidings, assembles trains over its own track, and hands traffic to a connecting Class I carrier — all while owing the car owners per-diem hire for every hour and mile their equipment spends on line, answering to federal hours-of-service law for its crews, holding its track to FRA class-speed standards, dividing through-route revenue with the connecting road, and reporting derailments and other incidents to the regulator. Capital renewal is typically bankrolled by grant programs with matching-fund obligations and milestone-based drawdowns. Every one of these obligations generates records that must agree with each other: a settled train implies billed waybills, a billed through waybill implies an agreed revenue division, and a restricted stretch of track implies movements that can no longer run.

This document specifies the Short Line Railroad Operations API, a single operations platform mounted under `/rail` that governs that full lifecycle — from the moment a shipper places a car order to the settlement of the movement that carries the load, and from the registration of each railcar to the close of its car-hire statement. It is written for the engineers who will build the service. Because so much of railroad bookkeeping is time-dependent, the platform runs on a logical clock rather than wall-clock time; all deadlines, accruals, rest calculations, and sweeps described below read that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Nine roles are recognized, spelled exactly as follows: `SystemAdmin`, `Dispatcher`, `CrewCaller`, `Conductor`, `TrackInspector`, `SettlementClerk`, `RegulatorOfficer`, `CustomerRep`, and `GrantManager`. Authorization is per-endpoint: a caller whose role is not in the endpoint's authorized list, or whose entity-backed identity does not match the targeted resource, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Conductor`, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks on a crew call compare the call's `crew_member_id` to `X-User-ID`, so a conductor may answer or report on duty only for their own calls. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on a car order compare the order's `customer_id` to `X-User-ID`, so a representative may place, amend, cancel, release, or read demurrage only for their own company's orders.

The remaining seven roles carry opaque identities. When `X-User-Role` is `SystemAdmin`, `Dispatcher`, `CrewCaller`, `TrackInspector`, `SettlementClerk`, `RegulatorOfficer`, or `GrantManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it, but it is never compared to an entity's `id`. Broadly, the `SystemAdmin` owns master data and the logical clock; the `Dispatcher` runs car orders, switching, movements, interchange reporting, and incident reporting; the `CrewCaller` staffs and relieves crew calls and corrects timekeeping; the `TrackInspector` schedules, files, and remediates track inspections; the `SettlementClerk` owns interchange confirmation, car hire, waybill rating, revenue divisions, movement settlement, and milestone payment; the `RegulatorOfficer` files FRA reports, closes and reopens incidents, waives defects, and rules on grant milestone submissions; the `GrantManager` owns grant projects and submits milestones — deliberately segregated from the agency officer who approves them.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Sweeps

All temporal behavior in the system — accruals, deadlines, rest periods, agreement expirations — is measured against a server-maintained logical clock, never against wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and it advances only when a `SystemAdmin` sets it to a supplied `to_iso8601` instant through the clock-advance capability. The capability returns the new `current_utc` together with three sweep counters: `swept_segments`, `swept_crew`, and `swept_sidings`.

Every clock advance runs three sweeps across the whole database. The inspection-overdue sweep examines every track segment and moves any segment whose inspection deadline has passed from `IN_SERVICE` to `RESTRICTED`, with the movement cascade described in §2.10 and §3.6. The crew rest sweep returns any `RESTING` crew member who has completed the mandatory rest period to `AVAILABLE`. The siding expiry sweep moves every maintenance agreement whose expiry instant has been reached from `ACTIVE` to `EXPIRED`. Each sweep's detailed rule lives with its owning workflow in §3.

### 2.5. Common Resource Properties

Every resource in this API carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation. `version` is an integer that increments by exactly one on every mutation of the resource — including mutations performed by system cascades rather than by a direct client write — and anchors the optimistic concurrency rules of §2.8. No entity in this specification is exempt: customers, sidings, orders, cars, jobs, movements, interchange events, statements, waybills, divisions, segments, inspections, crew members, crew calls, incidents, projects, and milestones all carry the full set.

### 2.6. Reference Validation and Nested Retrieval

Identifiers must resolve before business rules run. Path identifiers are validated left to right: in a nested path, the parent identifier is resolved first, and the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — a milestone request under a nonexistent project fails on the project before the milestone is ever considered. Foreign keys carried in request bodies are validated the same way: an order naming an unknown `customer_id` or `siding_id`, a waybill naming an unknown `railcar_id`, or a crew call naming an unknown `crew_member_id` is rejected with the same error before any state or business rule is evaluated.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts are integer cents — awards, charges, drawdowns, shares, damages, and rates alike. Where a calculation cannot avoid division, rounding is round half up, and the number of decimal places is stated with the rule: shares and drawdown bases round to whole cents, and the grant completion percentage rounds to two decimal places. Two rounding orders are pinned by contract and may not be varied. In a revenue division, our railroad's share is rounded to whole cents first, and the connecting road receives the unrounded remainder — the two shares are never rounded independently. In a car-hire final amount, the time component and the mileage component are each rounded to whole cents first (in practice exact, because the hire rates are integer cents), then summed, and only then is the minimum-hire floor applied. Speeds and minute accumulators are integers throughout; where a duration must be derived from two timestamps it is truncated down to whole hours or whole minutes as stated in the owning rule, and `effective_speed_mph` is an integer in miles per hour with no rounding.

### 2.8. Optimistic Concurrency Control

Exactly two write operations in this API are guarded by optimistic concurrency control, and each names its guard field explicitly.

Amending a car order through `PATCH /rail/car-orders/{id}` requires the request to carry `expected_car_order_version`, holding the order's `version` as the client last observed it. If the order's current `version` has advanced beyond that value — for example because a dispatcher accepted the order or furnished cars against it in the interim, both of which legitimately increment the version — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite an order state it never observed.

Correcting a crew member's hours-of-service accumulators through `POST /rail/crew-members/{id}/adjust-hos` requires the request to carry `expected_crew_member_version`, holding the member's `version` as the client last observed it. If the member's current `version` has advanced since — duty transitions in the interim legitimately changed the accumulators and the correction baseline is stale — the correction is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; all other writes proceed without an OCC check.

### 2.9. Validation Ordering and Error Precedence

Requests are evaluated against a fixed pipeline of validation bands, and the band order is part of the contract — a request that violates several rules always surfaces the error from the earliest band. First, authentication: both headers present and the role recognized, failing as `ERR_UNAUTHENTICATED`. Immediately after the headers, and still ahead of any business rule, syntactic body validation rejects malformed payloads, missing required fields, invalid enum values, and invalid types with `ERR_INVALID_REQUEST` (HTTP 400). Second, authorization: the role must be listed for the endpoint and entity-backed identity must match, failing as `ERR_FORBIDDEN_ROLE`. Third, existence: path identifiers and body foreign keys resolve left to right, failing as `ERR_RESOURCE_NOT_FOUND`. Fourth, state legality: the target resource must be in a state from which the requested transition is defined, failing as `ERR_INVALID_STATE` (HTTP 409) — or the more specific state errors `ERR_ORDER_NOT_AMENDABLE` and `ERR_MEMBER_NOT_AVAILABLE` where §3 names them. Fifth, business safety gates: hours-of-service limits, siding agreement activity, segment-in-service requirements, and FRA filing prerequisites. Sixth, temporal overlap rules for crew call windows and inspection dates. Seventh, business constraints: capacity ceilings, uniqueness, and duplication rules. Eighth, referential business rules: call targets, on-line car requirements, crew presence, rated waybills, division basis shape, and grant activity. Ninth and last, fiscal rules: the customer's credit standing is examined only after every earlier band has passed.

### 2.10. Cascading State Consistency

Many operations mutate more than one resource, and the system — not the client — keeps the graph consistent. When a track segment passes from `IN_SERVICE` to `RESTRICTED`, planned and ready movements routed over it are annulled, departed movements routed over it are held, and the crew calls attached to an annulled movement expire. When a movement departs or arrives, the cars on its waybills change fleet status to match. When an incident names an involved movement, the loaded and in-transit cars on that movement are held. When a waybill is billed at movement settlement, the order that supplied its car completes, and settling a revenue division settles its waybill. When every milestone of a grant project has been paid, the project completes itself. Each such cascade mutates every resource it touches: the affected resource's `updated_at` refreshes and its `version` increments by one, exactly as if a client had written it directly. The detailed trigger conditions for each cascade appear with the owning workflow in §3.

## 3. Business Logic & Workflows

### 3.1. Shippers, Sidings, and Car Order Placement

Every commercial relationship begins with a **Customer** record — the legal shipper — created by a `SystemAdmin` with a `name`, a `billing_email` for invoice delivery, and an optional `demurrage_free_days` count that defaults to 2 when omitted. Each customer carries a system-managed `credit_status` that starts at `GOOD`; a `SystemAdmin` amendment may move it to `SUSPENDED` or back, and may also revise `demurrage_free_days`, with either change incrementing the customer's `version`.

A shipper's plant is reached through an **IndustrySiding**, registered by a `SystemAdmin` with the owning `customer_id`, a display `name`, a `capacity_cars` ceiling on the cars the siding can hold, the `serving_track_segment_id` of the track segment the siding connects to, and an `agreement_expires_on` instant bounding the siding maintenance agreement. The siding's `maintenance_agreement_status` begins `ACTIVE`. An administrator may suspend an active agreement, moving it to `SUSPENDED`, and may renew an `EXPIRED` or `SUSPENDED` agreement by supplying a `new_expires_on` strictly later than the current clock; renewal copies `new_expires_on` into `agreement_expires_on` and returns the siding to `ACTIVE`. When the logical clock reaches or passes `agreement_expires_on`, the siding expiry sweep moves an `ACTIVE` agreement to `EXPIRED` on its own. Sidings can be listed filtered by `customer_id`, by `serving_track_segment_id`, or by `maintenance_agreement_status`.

With master data in place, a `CustomerRep` places a **CarOrder** by naming the `customer_id`, the delivery `siding_id` — which must belong to that customer — the requested `car_type` (one of `BOX`, `HOPPER`, `TANK`, `FLAT`, or `GONDOLA`), a `quantity` of at least one car, and a `needed_by_date`. A new order rests in `PLACED` with `cars_furnished_count` at zero and neither `furnished_at` nor `released_at` set. Because the `CustomerRep` identity is entity-backed, every order-scoped write compares the order's `customer_id` to the caller's `X-User-ID`, and a mismatch is refused as `ERR_FORBIDDEN_ROLE`. Orders can be listed filtered by `customer_id`, by `siding_id`, or by `status`.

An order may be amended — a replacement `quantity`, a replacement `needed_by_date`, or both — only while it is `PLACED`, `ACCEPTED`, or `PARTIALLY_FURNISHED`; an amendment attempted in any other status is refused with `ERR_ORDER_NOT_AMENDABLE`. The amendment always carries `expected_car_order_version` under the optimistic concurrency rule of §2.8, and a stale value fails with `ERR_STALE_VERSION` before any field is applied. When a replacement `quantity` is supplied, it must be at least the number of cars already furnished against the order (`cars_furnished_count`); a smaller value is rejected with `ERR_QUANTITY_BELOW_FURNISHED`. A successful amendment leaves the order in the same status and increments its `version` by one.

### 3.2. Acceptance, Furnishing, Release, and Demurrage

Acceptance is the railroad's commitment to serve an order, performed by a `Dispatcher`. Acceptance runs its own ordered gauntlet of business gates, and the order matters because a request failing several gates surfaces the earliest: first the delivery siding's `maintenance_agreement_status` must be `ACTIVE`, failing as `ERR_SIDING_AGREEMENT_INACTIVE`; then the order's `quantity` must not exceed the siding's `capacity_cars`, failing as `ERR_SIDING_CAPACITY_EXCEEDED`; and only then is the shipper's credit examined, a `credit_status` other than `GOOD` surfacing `ERR_CUSTOMER_CREDIT_SUSPENDED`. A successful acceptance moves the order from `PLACED` to `ACCEPTED` and increments its `version`.

Furnishing assigns physical cars to an accepted order. Each furnish request carries a `count` of at least one car. Eligible cars are fleet members whose `status` is `AVAILABLE` and whose `car_type` equals the order's; when fewer eligible cars exist than the requested `count`, the request fails with `ERR_INSUFFICIENT_AVAILABLE_CARS`. Selection follows roster seniority — earliest `created_at` first, ties broken by ascending `reporting_mark` — and each selected car moves to `ASSIGNED` with its `assigned_order_id` pointing at the order, incrementing the car's `version` alongside the order's. The first successful furnish stamps `furnished_at` with the current clock, and that instant becomes the demurrage baseline. Furnishing fewer cars than the unfilled remainder (the `quantity` minus the `cars_furnished_count`) moves an `ACCEPTED` order to `PARTIALLY_FURNISHED`, or leaves a `PARTIALLY_FURNISHED` order in that status; furnishing exactly the remainder completes the assignment and the order stands `FURNISHED`. Furnish is defined only from `ACCEPTED` and `PARTIALLY_FURNISHED`; from any other status the request is an invalid-state rejection.

Once the shipper has loaded the cars, a `CustomerRep` releases the order — permitted from `FURNISHED` or from `PARTIALLY_FURNISHED`. Release stamps `released_at` from the clock, detaches every car still tied to the order by clearing its `assigned_order_id`, and moves those cars from `ASSIGNED` to `LOADED`, each car's `version` incrementing alongside the order's. An order may instead be cancelled by a `CustomerRep` from `PLACED`, `ACCEPTED`, `PARTIALLY_FURNISHED`, or `FURNISHED`. Cancelling a `PARTIALLY_FURNISHED` or `FURNISHED` order returns each assigned car to `AVAILABLE` and clears its `assigned_order_id`; cancelling a `PLACED` or `ACCEPTED` order has no fleet to unwind. `CANCELLED` is terminal, as is `COMPLETED` — and the road to `COMPLETED` runs through billing: when the first waybill referencing the order through `car_order_id` reaches `BILLED`, the system advances a `RELEASED` order to `COMPLETED`, incrementing its `version`.

Demurrage is the tariff the railroad charges for cars held in the customer's hands too long, exposed as a computed read on the order that returns `billable_days`, `cars_held`, `free_days`, and `charge_cents` to the owning `CustomerRep` and to `Dispatcher` and `SettlementClerk` staff. While an order is `FURNISHED` or `PARTIALLY_FURNISHED` and `furnished_at` is set, the number of loading days is the whole days elapsed between `furnished_at` and the current logical clock; in any other status, or before the first furnish, the loading days are zero. The shipper's `demurrage_free_days` supplies the `free_days` allowance, and the billable days are the loading days minus the allowance, floored at zero — boundary-exact, so loading for exactly the free allowance bills nothing and only a strictly longer hold bills. The charge multiplies the billable days by `cars_held` — the order's current `cars_furnished_count` — at 7,500 cents, that is $75.00, per car per day.

### 3.3. The Railcar Fleet and Class I Interchange

The **Railcar** roster is maintained by a `SystemAdmin`, who registers each car with its unique AAR `reporting_mark` — a duplicate mark anywhere on the roster is refused with `ERR_DUPLICATE_REPORTING_MARK` — a `car_type` from the same five-value fleet enum used by orders, an `ownership` of `HOME` for railroad-owned cars or `FOREIGN` for cars owned by a connecting road, and, for foreign cars, the `home_road_mark` plus the car-hire rates `hire_rate_per_hour_cents` and `hire_rate_per_mile_cents`, both integer cents payable to the owner. An optional `current_location_segment_id` records where the car sits. New cars enter the roster `AVAILABLE`, and the fleet list can be filtered by `ownership`, `status`, `car_type`, `current_location_segment_id`, or `assigned_order_id`.

A `Dispatcher` may mark a car out of service for repair, moving it from `AVAILABLE` to `BAD_ORDER`. Bad-ordering an `ASSIGNED` car withdraws it from its order: the car's `assigned_order_id` is cleared, and the order's `cars_furnished_count` — a computed count of the cars pointing at the order — reflects the withdrawal. Returning a car to service restores a `BAD_ORDER` or `HELD` car to `AVAILABLE`. The remaining fleet transitions are cascades owned by other workflows and described with them: selection by furnish moves `AVAILABLE` to `ASSIGNED`; order cancellation moves `ASSIGNED` back to `AVAILABLE`; order release moves `ASSIGNED` to `LOADED`; departure of a carrying movement moves `LOADED` to `IN_TRANSIT`; arrival with a local waybill moves `IN_TRANSIT` back to `AVAILABLE`; involvement in a reported incident moves `LOADED` or `IN_TRANSIT` to `HELD`; and confirmed delivery to a connecting road moves `AVAILABLE`, `LOADED`, or `IN_TRANSIT` to `INTERCHANGED_OUT`, the fleet's only terminal status.

Every exchange with a Class I partner is booked as an **InterchangeEvent**, reported by a `Dispatcher` with the partner's `class_i_partner` road mark, a `direction` of `RECEIVED` for a car entering our line or `DELIVERED` for a car leaving it, the `railcar_id`, an optional `waybill_id` identifying the through waybill on a delivered load, an `occurred_at` instant that defaults to the logical clock when omitted, and — for delivered foreign cars — the `miles_traveled_on_line` hauled on our line. Two booking guards apply. A `RECEIVED` report is refused with `ERR_INTERCHANGE_DUPLICATE` when the same car already has an open received event: one in `REPORTED` or `CONFIRMED` status with no matching delivered confirmation. A `DELIVERED` report requires the car to be on the line in `AVAILABLE`, `LOADED`, or `IN_TRANSIT` status, and for a `FOREIGN` car the `miles_traveled_on_line` figure is mandatory; either violation surfaces `ERR_INTERCHANGE_DIRECTION_INVALID`. A new event rests in `REPORTED`, and events can be listed filtered by `railcar_id`, `waybill_id`, `direction`, or `status`.

Confirmation is a `SettlementClerk` duty, and its effects fork on direction. Confirming a `RECEIVED` event for a `FOREIGN` car opens car-hire accrual: a **CarHireStatement** is created in `OPEN` status for the car — or the existing `OPEN` statement for that car and the current accrual period is reused — with `hire_accrual_start` stamped from the clock and `period_month` set to that instant's year-month. Confirming a `DELIVERED` event moves the car to `INTERCHANGED_OUT` regardless of ownership and, for a `FOREIGN` car, stops the meter: `hire_accrual_end` is stamped from the clock, `accrued_miles` records the reported miles (it is zero until that moment), the final amount is computed, and the statement moves from `OPEN` to `CLOSED`. Either confirmation increments the event's `version`. A confirmed event may later be challenged, moving `CONFIRMED` to `DISPUTED`, and a dispute may be resolved back to `CONFIRMED`; both are clerk actions that increment the `version`.

While a statement is `OPEN` — or later `DISPUTED` — it carries a live estimate, `provisional_amount_cents`, recomputed on every read from the computed `accrued_hours`: the whole hours elapsed between `hire_accrual_start` and the earlier of the current clock and `hire_accrual_end` (with no end set, simply the current clock), any partial hour discarded, multiplied by the car's `hire_rate_per_hour_cents`. The estimate is time-based only: `accrued_miles` and the mileage rate play no part in it, and no minimum applies. At close — manually by a `SettlementClerk`, or through the delivered-confirmation cascade — the final figure is computed and frozen into `final_amount_cents`: the time component (the accrued hours times the hourly rate) plus the mileage component (`accrued_miles` times `hire_rate_per_mile_cents`), each component rounded to whole cents first, then summed, and finally raised to a 3,600-cent — $36.00 — minimum when the sum falls short. A `CLOSED` statement may be settled, reaching the terminal `SETTLED`, or disputed to `DISPUTED`; a disputed statement can be reopened to `OPEN`, in which case the final amount is recomputed afresh at the next close. Statements can be listed filtered by `railcar_id`, `period_month`, or `status`, and only `SettlementClerk` and `SystemAdmin` read them.

### 3.4. Train Movements and Switching Operations

A **TrainMovement** is planned by a `Dispatcher` with a train `symbol`, an ordered array `route_segment_ids` naming the track segments the train will traverse, and an optional `origin_interchange_id` linking the interchange event that originated the movement. The plan carries a computed `max_speed_mph`, the minimum of the `effective_speed_mph` values over the route segments, computed when the movement is created and recomputed each time it is readied. A new movement rests in `PLANNED`; movements can be listed filtered by `status` or `origin_interchange_id`.

Readying a movement is a `Dispatcher` action with two gates: every segment in `route_segment_ids` must be `IN_SERVICE`, failing as `ERR_SEGMENT_NOT_IN_SERVICE`, and at least one crew call tied to the movement must be in `ACCEPTED` or `ON_DUTY`, failing as `ERR_MOVEMENT_NO_CREW`. Success moves the movement `PLANNED` → `READY`. Departure tightens the track gate: every route segment must be `IN_SERVICE` with `defect_open` false, again failing as `ERR_SEGMENT_NOT_IN_SERVICE`. A successful departure stamps `departed_at` and moves every railcar carried on a waybill of this movement from `LOADED` to `IN_TRANSIT`. A departed movement may be held — `DEPARTED` → `HELD` — and later resumed, provided every route segment is back `IN_SERVICE`. Arrival moves the movement from `DEPARTED` to `ARRIVED`, stamps `arrived_at`, and releases the local cars: every railcar on a waybill of this movement that is not a through movement returns from `IN_TRANSIT` to `AVAILABLE`, while cars on through waybills remain in transit until interchanged. Settlement and annulment, the two terminal outcomes, are described below — settlement with the waybill cascade in §3.5, and annulment here.

Annulment is never a client action. When a route segment passes from `IN_SERVICE` to `RESTRICTED` — whether because a `CRITICAL` defect was filed or because the overdue sweep restricted it — every movement in `PLANNED` or `READY` routed over that segment is annulled, and every such movement's crew calls in `CALLED` or `ACCEPTED` expire, moving to `EXPIRED`. A `DEPARTED` movement routed over the newly restricted segment is instead held. Each cascade increments the `version` of every movement and call it touches.

Alongside road trains, a `Dispatcher` plans **SwitchJob** work — industry switching tied, when relevant, to a `car_order_id` — with a planned `scheduled_date` and free-text `notes`. A new job is `PLANNED`. Assigning a crew call to the job requires a call that exists, that is in `ACCEPTED` or `ON_DUTY`, and whose `switch_job_id` names this job; any other reference fails as `ERR_INVALID_STATE`. A successful assignment records the `crew_call_id` and moves the job `PLANNED` → `ASSIGNED`. From either `PLANNED` or `ASSIGNED`, the dispatcher may complete the job (`COMPLETED`) or annul it (`ANNULLED`); both are terminal, and jobs can be listed filtered by `car_order_id`, `crew_call_id`, or `status`.

### 3.5. Waybills, Rating, and Revenue Division

A **Waybill** is the shipment contract, created by a `Dispatcher` with the carrying `railcar_id`, the `origin_customer_id` of the shipper, a `destination` station or off-line junction, a `commodity` of `GRAIN`, `LUMBER`, or `CHEMICALS`, and a billed `weight_tons`. The waybill may also carry the `car_order_id` of the order that supplied the car and the `movement_id` of the train carrying it. The `through_route` flag marks revenue that divides with a connecting road; when it is true, `our_miles` and `total_miles` are both required, with `total_miles` at least `our_miles` and `our_miles` at least zero — a through waybill submitted without both mileages, or with mileages violating that ordering, is rejected as `ERR_INVALID_REQUEST`. At creation, and again at rating, the named car must be on the line: a car in `INTERCHANGED_OUT`, `BAD_ORDER`, or `HELD` fails with `ERR_CAR_NOT_ON_LINE`. A new waybill rests in `CREATED`, and waybills can be listed filtered by `railcar_id`, `origin_customer_id`, `car_order_id`, `movement_id`, or `status`.

Rating is a `SettlementClerk` action that prices the waybill and moves it `CREATED` → `RATED`. The `total_freight_charge_cents` is the billed `weight_tons` multiplied by the per-ton rate for the `commodity`: 38,500 cents — $385.00 — per ton for `GRAIN`, 42,000 cents — $420.00 — per ton for `LUMBER`, and 51,500 cents — $515.00 — per ton for `CHEMICALS`, an exact integer product with no rounding.

Settlement of an arrived movement is the accounting pivot of the whole system, performed by a `SettlementClerk`. The gate is that every waybill tied to the movement must already be `RATED` or `BILLED`; a waybill still in `CREATED` blocks settlement with `ERR_WAYBILL_NOT_RATED`. On success, four cascades run. Every `RATED` waybill on the movement becomes `BILLED`. For each through waybill, a **RevenueDivision** is auto-created in `DRAFT` with basis `MILEAGE_PRORATE`, its snapshot fields copied from the waybill. Each non-through waybill steps straight from `BILLED` to `SETTLED`. And every car order referenced by a billed waybill's `car_order_id` completes, moving `RELEASED` → `COMPLETED`. The movement itself stands `SETTLED`, terminal, with its `version` incremented.

A **RevenueDivision** exists at most once per waybill: creating a second division for the same waybill is refused with `ERR_DIVISION_EXISTS`. Beyond the settle cascade, a `SettlementClerk` may create a division directly for a waybill in `RATED` or `BILLED` — any other waybill status fails as `ERR_DIVISION_BASIS_INVALID` — choosing a `basis` of `MILEAGE_PRORATE` or `AGREED_PERCENTAGE`. The `AGREED_PERCENTAGE` basis requires an `agreed_pct` strictly between zero and one and forbids it for `MILEAGE_PRORATE`; a missing, out-of-range, or misplaced `agreed_pct` also fails as `ERR_DIVISION_BASIS_INVALID`. At creation the division snapshots `our_miles`, `total_miles`, and `total_charge_cents` from the waybill, computes the two shares, and freezes them. Under `MILEAGE_PRORATE`, `our_share_cents` is the total charge times `our_miles` divided by `total_miles`, rounded half up to whole cents. Under `AGREED_PERCENTAGE`, `our_share_cents` is the total charge times `agreed_pct`, rounded half up to whole cents — identical waybill data yields a different split under the two bases. In both bases, `connecting_share_cents` is the total charge minus our rounded share; the connecting road's share is never rounded independently. A division moves `DRAFT` → `AGREED` on clerk agreement, `AGREED` → `DISPUTED` on dispute, `DISPUTED` → `AGREED` on renewed agreement, and `AGREED` → `SETTLED` on settlement — at which point the waybill itself steps from `BILLED` to `SETTLED`. Divisions can be listed filtered by `waybill_id` or `status`, readable by `SettlementClerk` and `SystemAdmin`.

### 3.6. Track Infrastructure, Inspection, and FRA Compliance

The railroad's plant is modeled as **TrackSegment** records, created by a `SystemAdmin` with a `name`, a `milepost_start`, a `milepost_end` that must be strictly greater than the start, and an `fra_class` of `EXCEPTED`, `CLASS_1`, `CLASS_2`, `CLASS_3`, `CLASS_4`, or `CLASS_5`. Each segment carries a computed `effective_speed_mph`: the base speed for its class — 10 mph for `EXCEPTED`, 10 for `CLASS_1`, 25 for `CLASS_2`, 40 for `CLASS_3`, 60 for `CLASS_4`, and 80 for `CLASS_5` — and, while a defect is open on the segment, the lesser of that base and the defect cap, which is 25 mph for a `MONITOR` defect and 10 mph for a `CRITICAL` one. The value is an integer in miles per hour, recomputed at creation, whenever an administrator changes the class by supplying a `new_fra_class`, and whenever a defect is filed, remediated, or waived. A new segment is `IN_SERVICE` with `defect_open` false, `open_defect_severity` unset, `is_overdue` false, and `last_inspection_at` stamped with the creation clock; segments can be listed filtered by `fra_class` or `status`.

Inspections are scheduled by a `TrackInspector` as **TrackInspection** records naming the `segment_id` and a planned `scheduled_date`. Two inspections on the same segment must be separated by at least one full day: a new inspection whose date falls less than two days from an existing inspection on that segment is rejected with `ERR_INSPECTION_OVERLAP`. A new inspection is `SCHEDULED`, and inspections can be listed filtered by `segment_id` or `status`.

Filing turns a scheduled inspection into a finding, always stamping `filed_at` from the clock and refreshing the segment's `last_inspection_at` to the same instant, which clears the segment's `is_overdue` flag. When the inspector files with `defect_found` false, the inspection becomes `FILED`, terminal, and the segment is otherwise untouched. When the inspector files with `defect_found` true, a `defect_severity` of `MONITOR` or `CRITICAL` is required, the inspector's narrative is recorded in `findings`, and the inspection becomes `DEFECT_FILED`: the segment's `defect_open` goes true, `open_defect_severity` takes the filed severity, and `effective_speed_mph` is recomputed under the defect cap. A `CRITICAL` filing additionally forces the segment from `IN_SERVICE` to `RESTRICTED`, triggering the movement cascade of §2.10 and §3.4 — planned and ready movements over the segment annulled, their called and accepted crew calls expired, departed movements held.

An open defect is closed one of two ways, with equal effect. The `TrackInspector` remediates the defect, moving the inspection `DEFECT_FILED` → `REMEDIATED`; or a `RegulatorOfficer` waives it, optionally recording a `justification`, moving the inspection `DEFECT_FILED` → `WAIVED`. Either action clears the segment's defect — `defect_open` false, `open_defect_severity` unset — and returns the segment from `RESTRICTED` to `IN_SERVICE`, provided it is not overdue, with `effective_speed_mph` recomputed on return.

Independent of defects, the inspection-overdue sweep runs on every clock advance across all segments. A segment's inspection deadline is its `last_inspection_at` plus the frequency for its class: 30 days for `EXCEPTED`, 7 days for `CLASS_1`, 7 days for `CLASS_2`, 3 days for `CLASS_3`, 2 days for `CLASS_4`, and 1 day for `CLASS_5`. The segment is overdue when the clock is strictly later than the deadline — a clock reading exactly at the deadline is not overdue, and the comparison is made to the second. An overdue segment has `is_overdue` set, and if it is still `IN_SERVICE` it moves to `RESTRICTED` with the same movement cascade as a critical defect.

### 3.7. Crew Calling and Hours-of-Service Governance

The crew roster is maintained by a `SystemAdmin`, each **CrewMember** created with a `name` and a `craft` of `ENGINEER` or `CONDUCTOR`, beginning `AVAILABLE`. Two accumulators track the member's duty exposure — `on_duty_minutes_rolling_24h` over the trailing 24 hours and `on_duty_minutes_month` over the calendar month, both starting at zero — and two fields track rest: `rest_minutes_completed`, which is unset while the member is fully rested, and `rest_start_at`, unset in the same condition. A computed `hos_available_minutes`, visible on every member read, is the smaller of the two remaining allowances — 720 minutes minus the rolling accumulator, and 16,560 minutes minus the month accumulator — each floored at zero before the comparison. Members can be listed filtered by `status` or `craft`.

Federal hours-of-service law caps a crew member at 720 minutes — twelve hours — on duty in any trailing 24-hour window, and at 16,560 minutes — 276 hours — in the calendar month, and requires 600 minutes — ten hours — of completed rest before a new call. A `CrewCaller` creates a **CrewCall** naming the `crew_member_id`, a planned duty window from `scheduled_start_at` to `scheduled_end_at` with the end strictly later than the start, and exactly one duty target: a `movement_id` for a train or a `switch_job_id` for a switching job. Supplying both targets, or neither, is refused with `ERR_CALL_TARGET_REQUIRED`. Creation runs its eligibility gates in band order: the member's `status` must be `AVAILABLE`, failing as `ERR_MEMBER_NOT_AVAILABLE`; the daily remaining allowance must be greater than zero — a member whose rolling accumulator has reached exactly 720 has none left — failing as `ERR_HOS_DAILY_LIMIT`; the monthly remaining allowance must likewise be greater than zero, failing as `ERR_HOS_MONTHLY_LIMIT`; and the member must be fully rested, meaning `rest_minutes_completed` unset or at least 600, failing as `ERR_HOS_REST_REQUIRED`. After the safety gates, the window rule: the half-open window from `scheduled_start_at` up to but not including `scheduled_end_at` must not overlap any existing call of the same member in `CALLED`, `ACCEPTED`, or `ON_DUTY`; mere adjacency — a new call starting exactly when an existing one ends — is permitted. An overlap is rejected with `ERR_CALL_WINDOW_OVERLAP`. A new call rests in `CALLED`, and calls can be listed filtered by `crew_member_id`, `movement_id`, `switch_job_id`, or `status`.

Answering a call belongs to the called crew member alone, acting under the `Conductor` role with the identity check of §2.1 — the call's `crew_member_id` must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN_ROLE`. The response payload's `response` value steers the call: `ACCEPTED` moves `CALLED` → `ACCEPTED`, and `DECLINED` moves `CALLED` → `DECLINED`, terminal. Reporting for duty, again by the called member alone, moves an `ACCEPTED` call to `ON_DUTY`, stamps `on_duty_at` from the clock, and moves the member from `AVAILABLE` to `ON_DUTY` with both rest fields unset. Relief is a `CrewCaller` action on an `ON_DUTY` call: `off_duty_at` is stamped, `actual_on_duty_minutes` is computed as the whole minutes between `on_duty_at` and `off_duty_at` with any partial minute discarded, the call reaches the terminal `RELIEVED`, and the member moves from `ON_DUTY` to `RESTING` — both accumulators increased by the call's `actual_on_duty_minutes`, `rest_minutes_completed` set to zero, and `rest_start_at` stamped from the clock. Every one of these steps increments the `version` of the call, and duty transitions increment the member's as well.

Rest completes by the clock: on every clock advance, the rest sweep returns each `RESTING` member whose `rest_start_at` lies at least 600 minutes in the past to `AVAILABLE`, unsetting both rest fields. Calls also die with their trains — when a movement is annulled by the segment-restriction cascade, its calls in `CALLED` or `ACCEPTED` move to `EXPIRED`, terminal.

Timekeeping corrections exist for the cases the automatic accumulators cannot capture. A `SystemAdmin` or `CrewCaller` may correct a member's books by supplying any of `rolling_24h_minutes`, `month_minutes`, or `minutes_of_rest_completed`, which replace the corresponding accumulators. The correction always carries `expected_crew_member_version` under the optimistic concurrency rule of §2.8; a stale value fails with `ERR_STALE_VERSION`, and a successful correction increments the member's `version`.

### 3.8. Incident Reporting and Regulatory Filing

A derailment or other mishap is reported by a `Dispatcher` as an **Incident** with an `incident_type` of `DERAILMENT`, `COLLISION`, `CROSSING`, `HAZMAT`, or `INJURY`, the `segment_id` where it occurred, the `occurred_at` instant, an `estimated_damage_cents` figure, an optional `movement_id` naming the involved train, and an `injuries_count` that defaults to zero. Creation carries an immediate safety cascade: every railcar on a waybill of the named movement that is `LOADED` or `IN_TRANSIT` moves to `HELD`. Each incident carries a computed `fra_reportable` flag, true when the `incident_type` is `DERAILMENT`, `COLLISION`, or `HAZMAT`, or when the `estimated_damage_cents` reaches or exceeds the FRA damage-reporting threshold `FRA_DAMAGE_THRESHOLD_CENTS`. A new incident rests in `REPORTED`, and incidents can be listed filtered by `segment_id`, `movement_id`, or `status`.

Investigation is opened by a `Dispatcher`, moving `REPORTED` → `INVESTIGATING`, and the same action resumes a `REOPENED` incident back into `INVESTIGATING`. From `INVESTIGATING` the file forks on reportability. A `RegulatorOfficer` files the FRA report for a reportable incident, assigning its `fra_report_number` and moving it to `FRA_FILED`; attempting the filing on a non-reportable incident is rejected with `ERR_INCIDENT_NOT_REPORTABLE`. Closing from `INVESTIGATING` is permitted only for a non-reportable incident — attempting to close a reportable one before its FRA report is filed fails with `ERR_FRA_REPORT_REQUIRED` — while an incident in `FRA_FILED` may be closed without further condition. A `CLOSED` incident may be reopened to `REOPENED` by a `RegulatorOfficer` when new facts emerge. The incident lifecycle has no terminal state; a closed file can always be revived.

### 3.9. Grant-Funded Infrastructure Projects

Capital renewal runs through **GrantProject** records, created by a `GrantManager` with a `title`, a `grantor` funding agency, an `award_amount_cents` total, and a `required_match_pct` giving the railroad's matching share as a percentage between 0 and 100 inclusive. A new project is `AWARDED`; the manager activates it to `ACTIVE`, may suspend an active project to `SUSPENDED`, and may resume a suspended one back to `ACTIVE`. Four aggregates are computed on every read and after every milestone status change: `committed_cents`, the sum of `drawdown_cents` over the project's milestones in `APPROVED`; `drawn_cents`, the same sum over milestones in `PAID`; `remaining_cents`, the award minus the committed and drawn sums; and `percent_complete`, the summed `milestone_value_cents` of the project's milestones in `APPROVED` or `PAID` divided by the `award_amount_cents`, expressed as a percentage and rounded half up to two decimal places. Projects can be listed filtered by `status`.

Work is decomposed into **GrantMilestone** records, created by a `GrantManager` under the project — the nested path resolves the `project_id` first under the left-to-right rule of §2.6 — with a `name` and a `milestone_value_cents` attribution. The project's budget is guarded at creation: the sum of `milestone_value_cents` over the project's milestones, excluding any in `REJECTED` and including the new one, must not exceed the `award_amount_cents`, failing as `ERR_MILESTONE_VALUE_EXCEEDS_AWARD`. A new milestone is `PENDING`, and milestones can be listed filtered by `project_id` or `status`.

Submission belongs to the `GrantManager`, ruling belongs to the `RegulatorOfficer`, and payment belongs to the `SettlementClerk` — a deliberate segregation of duties. Submitting moves `PENDING` → `SUBMITTED`, records the `actual_cost_cents` — which must be zero or greater — and stamps `submitted_at`; a `REJECTED` milestone may be resubmitted the same way, its `actual_cost_cents` replaced by the new figure. Submission, approval, and payment all require the project to be `ACTIVE`, failing otherwise as `ERR_GRANT_NOT_ACTIVE`. Approval and rejection are defined only from `SUBMITTED`; either action attempted on a milestone in any other status fails with `ERR_MILESTONE_NOT_SUBMITTED`.

Approval freezes the money. When the agency officer approves a submitted milestone, its `drawdown_cents` is computed and frozen by a pinned waterfall: the cost basis is the `actual_cost_cents` multiplied by the grantor's share — one hundred minus the `required_match_pct`, over one hundred — rounded half up to whole cents; that basis is capped first at the milestone's own `milestone_value_cents`; and the result is capped again at the award remaining before this milestone, computed as the `award_amount_cents` minus the project's `committed_cents` and `drawn_cents` as they stand before this drawdown is added. The drawdown is the smaller of the two caps, and the evaluation order — cost basis, then milestone value, then award remaining, with the project aggregates read before this milestone contributes — is fixed to break the apparent circularity between the milestone and the project totals.

Payment is the terminal act. Paying an `APPROVED` milestone moves it to `PAID`, recomputes the project's `drawn_cents` and `remaining_cents`, and runs the completion bubble-up: when the project has at least one milestone and every milestone stands `PAID`, the project moves itself from `ACTIVE` to the terminal `COMPLETED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or return a computed read respond with `200 OK`. The table below is a navigational summary only — request payloads, validation order, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rail/_clock/set_current_utc` | Advance the logical clock and run the sweeps | SystemAdmin |
| POST | `/rail/customers` | Create a shipper customer | SystemAdmin |
| GET | `/rail/customers` | List customers | Any |
| GET | `/rail/customers/{id}` | Get one customer | Any |
| PATCH | `/rail/customers/{id}` | Update credit status or free days | SystemAdmin |
| POST | `/rail/industry-sidings` | Create an industry siding | SystemAdmin |
| GET | `/rail/industry-sidings` | List sidings | Any |
| GET | `/rail/industry-sidings/{id}` | Get one siding | Any |
| POST | `/rail/industry-sidings/{id}/renew-agreement` | Renew an expired or suspended agreement | SystemAdmin |
| POST | `/rail/industry-sidings/{id}/suspend` | Suspend a siding agreement | SystemAdmin |
| POST | `/rail/car-orders` | Place a car order | CustomerRep |
| GET | `/rail/car-orders` | List car orders | Any |
| GET | `/rail/car-orders/{id}` | Get one car order | Any |
| PATCH | `/rail/car-orders/{id}` | Amend an order (OCC guarded) | CustomerRep |
| POST | `/rail/car-orders/{id}/accept` | Accept a placed order | Dispatcher |
| POST | `/rail/car-orders/{id}/furnish` | Assign eligible railcars to the order | Dispatcher |
| POST | `/rail/car-orders/{id}/release` | Release loaded cars to the railroad | CustomerRep |
| POST | `/rail/car-orders/{id}/cancel` | Cancel the order | CustomerRep |
| GET | `/rail/car-orders/{id}/demurrage` | Computed demurrage read | CustomerRep, Dispatcher, SettlementClerk |
| POST | `/rail/railcars` | Register a railcar | SystemAdmin |
| GET | `/rail/railcars` | List railcars | Any |
| GET | `/rail/railcars/{id}` | Get one railcar | Any |
| POST | `/rail/railcars/{id}/bad-order` | Mark a car out of service | Dispatcher |
| POST | `/rail/railcars/{id}/return-to-service` | Return a car to service | Dispatcher |
| POST | `/rail/crew-members` | Create a crew member | SystemAdmin |
| GET | `/rail/crew-members` | List crew members | Any |
| GET | `/rail/crew-members/{id}` | Get one crew member with HOS availability | Any |
| POST | `/rail/crew-members/{id}/adjust-hos` | Correct HOS accumulators (OCC guarded) | SystemAdmin, CrewCaller |
| POST | `/rail/crew-calls` | Call a crew member for duty | CrewCaller |
| GET | `/rail/crew-calls` | List crew calls | CrewCaller, Conductor, Dispatcher, SystemAdmin |
| GET | `/rail/crew-calls/{id}` | Get one crew call | CrewCaller, Conductor, Dispatcher, SystemAdmin |
| POST | `/rail/crew-calls/{id}/respond` | Called member accepts or declines | Conductor |
| POST | `/rail/crew-calls/{id}/report-on-duty` | Called member reports for duty | Conductor |
| POST | `/rail/crew-calls/{id}/relieve` | Relieve an on-duty call | CrewCaller |
| POST | `/rail/switch-jobs` | Plan a switching job | Dispatcher |
| GET | `/rail/switch-jobs` | List switch jobs | Any |
| GET | `/rail/switch-jobs/{id}` | Get one switch job | Any |
| POST | `/rail/switch-jobs/{id}/assign` | Assign a crew call to the job | Dispatcher |
| POST | `/rail/switch-jobs/{id}/complete` | Complete the job | Dispatcher |
| POST | `/rail/switch-jobs/{id}/annul` | Annul the job | Dispatcher |
| POST | `/rail/train-movements` | Plan a train movement | Dispatcher |
| GET | `/rail/train-movements` | List train movements | Any |
| GET | `/rail/train-movements/{id}` | Get one movement | Any |
| POST | `/rail/train-movements/{id}/ready` | Mark the movement ready | Dispatcher |
| POST | `/rail/train-movements/{id}/depart` | Depart the movement | Dispatcher |
| POST | `/rail/train-movements/{id}/hold` | Hold a departed movement | Dispatcher |
| POST | `/rail/train-movements/{id}/resume` | Resume a held movement | Dispatcher |
| POST | `/rail/train-movements/{id}/arrive` | Arrive the movement | Dispatcher |
| POST | `/rail/train-movements/{id}/settle` | Settle the movement and bill its waybills | SettlementClerk |
| POST | `/rail/interchange-events` | Report a Class I interchange event | Dispatcher |
| GET | `/rail/interchange-events` | List interchange events | Any |
| GET | `/rail/interchange-events/{id}` | Get one interchange event | Any |
| POST | `/rail/interchange-events/{id}/confirm` | Confirm the event and start or stop car hire | SettlementClerk |
| POST | `/rail/interchange-events/{id}/dispute` | Dispute a confirmed event | SettlementClerk |
| POST | `/rail/interchange-events/{id}/resolve` | Resolve a disputed event | SettlementClerk |
| GET | `/rail/car-hire-statements` | List car hire statements | SettlementClerk, SystemAdmin |
| GET | `/rail/car-hire-statements/{id}` | Get one statement with live provisional amount | SettlementClerk, SystemAdmin |
| POST | `/rail/car-hire-statements/{id}/close` | Close a statement and freeze the final amount | SettlementClerk |
| POST | `/rail/car-hire-statements/{id}/settle` | Settle a closed statement | SettlementClerk |
| POST | `/rail/car-hire-statements/{id}/dispute` | Dispute a closed statement | SettlementClerk |
| POST | `/rail/car-hire-statements/{id}/reopen` | Reopen a disputed statement | SettlementClerk |
| POST | `/rail/waybills` | Create a shipment waybill | Dispatcher |
| GET | `/rail/waybills` | List waybills | Any |
| GET | `/rail/waybills/{id}` | Get one waybill | Any |
| POST | `/rail/waybills/{id}/rate` | Rate the waybill | SettlementClerk |
| POST | `/rail/revenue-divisions` | Create a revenue division for a through waybill | SettlementClerk |
| GET | `/rail/revenue-divisions` | List revenue divisions | SettlementClerk, SystemAdmin |
| GET | `/rail/revenue-divisions/{id}` | Get one division | SettlementClerk, SystemAdmin |
| POST | `/rail/revenue-divisions/{id}/agree` | Agree a draft or disputed division | SettlementClerk |
| POST | `/rail/revenue-divisions/{id}/dispute` | Dispute an agreed division | SettlementClerk |
| POST | `/rail/revenue-divisions/{id}/settle` | Settle an agreed division | SettlementClerk |
| POST | `/rail/track-segments` | Create a track segment | SystemAdmin |
| GET | `/rail/track-segments` | List track segments | Any |
| GET | `/rail/track-segments/{id}` | Get one segment | Any |
| POST | `/rail/track-segments/{id}/change-class` | Change the FRA class | SystemAdmin |
| POST | `/rail/track-inspections` | Schedule an inspection | TrackInspector |
| GET | `/rail/track-inspections` | List inspections | Any |
| GET | `/rail/track-inspections/{id}` | Get one inspection | Any |
| POST | `/rail/track-inspections/{id}/file` | File inspection results | TrackInspector |
| POST | `/rail/track-inspections/{id}/remediate` | Remediate an open defect | TrackInspector |
| POST | `/rail/track-inspections/{id}/waive` | Waive an open defect | RegulatorOfficer |
| POST | `/rail/incidents` | Report an incident | Dispatcher |
| GET | `/rail/incidents` | List incidents | Any |
| GET | `/rail/incidents/{id}` | Get one incident | Any |
| POST | `/rail/incidents/{id}/investigate` | Open or resume investigation | Dispatcher |
| POST | `/rail/incidents/{id}/file-fra-report` | File the FRA report | RegulatorOfficer |
| POST | `/rail/incidents/{id}/close` | Close the incident | RegulatorOfficer |
| POST | `/rail/incidents/{id}/reopen` | Reopen a closed incident | RegulatorOfficer |
| POST | `/rail/grant-projects` | Create a grant-funded project | GrantManager |
| GET | `/rail/grant-projects` | List grant projects | Any |
| GET | `/rail/grant-projects/{id}` | Get one project with aggregates | Any |
| POST | `/rail/grant-projects/{id}/activate` | Activate an awarded project | GrantManager |
| POST | `/rail/grant-projects/{id}/suspend` | Suspend an active project | GrantManager |
| POST | `/rail/grant-projects/{id}/resume` | Resume a suspended project | GrantManager |
| POST | `/rail/grant-projects/{id}/milestones` | Create a milestone on the project | GrantManager |
| GET | `/rail/grant-milestones` | List milestones | Any |
| GET | `/rail/grant-milestones/{id}` | Get one milestone | Any |
| POST | `/rail/grant-milestones/{id}/submit` | Submit a milestone with actual costs | GrantManager |
| POST | `/rail/grant-milestones/{id}/approve` | Approve a submitted milestone and freeze drawdown | RegulatorOfficer |
| POST | `/rail/grant-milestones/{id}/reject` | Reject a submitted milestone | RegulatorOfficer |
| POST | `/rail/grant-milestones/{id}/pay` | Pay an approved milestone | SettlementClerk |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_REPORTING_MARK` | 409 Conflict |
| `ERR_CALL_TARGET_REQUIRED` | 400 Bad Request |
| `ERR_MEMBER_NOT_AVAILABLE` | 409 Conflict |
| `ERR_HOS_DAILY_LIMIT` | 422 Unprocessable Entity |
| `ERR_HOS_MONTHLY_LIMIT` | 422 Unprocessable Entity |
| `ERR_HOS_REST_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CALL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SIDING_AGREEMENT_INACTIVE` | 422 Unprocessable Entity |
| `ERR_SIDING_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_QUANTITY_BELOW_FURNISHED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_AVAILABLE_CARS` | 409 Conflict |
| `ERR_ORDER_NOT_AMENDABLE` | 409 Conflict |
| `ERR_CAR_NOT_ON_LINE` | 409 Conflict |
| `ERR_SEGMENT_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_INSPECTION_OVERLAP` | 409 Conflict |
| `ERR_MOVEMENT_NO_CREW` | 422 Unprocessable Entity |
| `ERR_WAYBILL_NOT_RATED` | 409 Conflict |
| `ERR_INTERCHANGE_DUPLICATE` | 409 Conflict |
| `ERR_INTERCHANGE_DIRECTION_INVALID` | 409 Conflict |
| `ERR_FRA_REPORT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INCIDENT_NOT_REPORTABLE` | 422 Unprocessable Entity |
| `ERR_GRANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_MILESTONE_VALUE_EXCEEDS_AWARD` | 422 Unprocessable Entity |
| `ERR_MILESTONE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DIVISION_BASIS_INVALID` | 400 Bad Request |
| `ERR_DIVISION_EXISTS` | 409 Conflict |
