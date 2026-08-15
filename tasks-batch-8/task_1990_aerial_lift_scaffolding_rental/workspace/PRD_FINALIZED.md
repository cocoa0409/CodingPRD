# Aerial Lift & Scaffolding Rental API — Product Requirements Document

## 1. Introduction

A rental branch lives or dies on three clocks running at once: the calendar that decides whether a serialized boom lift is inspection-current under its governing ANSI or OSHA standard, the route clock that decides whether a delivery truck can reach a jobsite inside a dispatcher's window, and the billing clock that decides how many billable days a customer owes when a scaffold section comes off rent and goes back out again two days later. Customers rent by equipment class and working height; the branch answers with serialized units, flat route fees, minimum rental periods, damage waivers, and — when a machine comes back bent or does not come back at all — waiver-aware chargebacks and recovery credits.

This document specifies the API that runs such a branch. It covers the catalog of equipment classes and their rate structures, the serialized fleet and its annual inspection cycle, customer credit standing, rental contracts and the individual lines booked against them, delivery and pickup logistics with jobsite standby and erection labor billing, familiarization training documentation, damage and loss claims with dispute handling, and close-out invoicing under a pinned rounding order. All date-sensitive evaluation in the system — inspection due dates, training validity, provisional rental quotes — reads a logical server clock rather than wall-clock time, so that every rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, the logical clock, resource properties, monetary precision, concurrency control, validation order, and the temporal and cascading rules that cut across every workflow.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request with a missing or malformed header, or whose role is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes five roles, spelled exactly: `BranchManager`, `RentalCoordinator`, `Driver`, `YardTechnician`, and `Customer`. Each operation in §4 lists its authorized roles; a caller whose role is not authorized for the operation, or who fails an ownership check described below, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Customer` role is entity-backed: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting customer account, and ownership checks on any resource that references a customer — reading one's own account record, listing or reading contracts, reading an invoice, calling a line off rent or re-renting it, reporting or disputing a claim — compare the resource's `customer_id` to `X-User-ID`. A `Customer` may read only its own customer record, may see only its own contracts and claims, and may act only on lines and claims belonging to its own contracts.

The remaining four roles carry opaque operator identifiers not tied to any persisted entity. When `X-User-Role` is `BranchManager`, `RentalCoordinator`, or `YardTechnician`, the server may record the identifier — as `certified_by` or `resolved_by` on decisions a branch manager takes, as `inspector_id` on an inspection record a technician submits, as `trainer_id` on a training record, as `reported_by` on a claim — but never compares it to any entity's `id`. When `X-User-Role` is `Driver`, the identifier is likewise opaque, but with one assignment-binding rule: a trip is scheduled against a specific `driver_id`, and the driver-only actions on that trip (starting the route leg, completing it, failing it) require the caller's `X-User-ID` to equal the trip's assigned `driver_id`, failing which the request is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Server Clock

Every date-sensitive rule in this document — inspection due dates, training-record validity, provisional rental quotes, segment boundaries — evaluates against a logical server clock, not wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until a clock-setting call is made it keeps reading exactly that value and never falls back to wall-clock time. A `BranchManager` may set the clock through an admin test-driving capability that accepts a `to_iso8601` timestamp; the response echoes the new reading as `current_utc`. All computed fields described below (`is_valid` on training records, unit rentability, provisional charges) re-evaluate against this clock on every read.

### 2.5. Common Resource Properties

Every primary resource — customer accounts, equipment classes, equipment units, rental contracts, rental lines, delivery trips, inspection records, and damage claims — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation — including mutations caused by system cascades rather than direct client writes.

Both `created_at` and `updated_at` are stamped from wall-clock time, not from the logical server clock of §2.4 — setting the logical clock does not change what they record.

Training records are the exception: a training record is created once and never modified, so it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Money, Rates, and Rounding Discipline

All monetary values in the system — catalog rates, repair estimates, chargebacks, trip fees, subtotals, invoice totals, credit limits, and balances — are integer cents, stored and returned as integers. Where a computation can produce a fractional cent, the result is rounded half-up to the nearest whole cent. Rounding is pinned to the component level: the damage chargeback is rounded per claim at charge time, the labor charge is rounded per trip at completion, the recovery credit is rounded per claim at recovery, and each rounded integer is stored. Rental segment charges are exact integer products of integer-cent rates and are never rounded. Invoice-level aggregates then sum those stored integer components and are never re-rounded — summing raw unrounded percentages and rounding once at the aggregate level is explicitly not the rule. The single non-integer monetary-adjacent input is `crew_labor_hours`, accepted as a number of hours (for example, 2.5) and multiplied by an integer-cent hourly rate at completion time.

### 2.7. Optimistic Concurrency Control on Contract Writes

Exactly one write participates in optimistic concurrency control: adding a rental line to a contract (`POST /rental-lines`) requires a non-optional `expected_contract_version` field carrying the client's last observed `version` of the parent rental contract. If the contract's current `version` no longer matches — because another writer added a line, activated the contract, or a cascade recomputed its subtotals — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a contract it has not observed. No other endpoint accepts a version field.

### 2.8. Validation Order and Reference Resolution

Every request is validated against a fixed pipeline, and the first failing check determines the error returned:

1. **Authentication** (§2.1): headers present, well-formed, and role declared — otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization**: role permitted on the endpoint, plus the `Customer` ownership checks and the `Driver` assignment check — otherwise `ERR_FORBIDDEN`.
3. **Request shape**: all required fields present, types correct, enum values valid, date and datetime formats valid, `requested_end_date` not earlier than `requested_start_date`, and `planned_end_utc` strictly later than `planned_start_utc` — otherwise `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence**: every referenced entity must exist. Path identifiers are validated left to right — the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) — followed by body references such as `customer_id`, `unit_id`, `contract_id`, `line_id`, and `class_id`, each of which must name an existing resource.
5. **Optimistic concurrency** (§2.7): a stale `expected_contract_version` yields `ERR_STALE_VERSION`.
6. **State-machine preconditions**: wrong from-state, writes against terminal states, and cross-entity state gates (for example, a line action requiring its contract to be `ACTIVE`) yield `ERR_INVALID_STATE` (HTTP 409).
7. **Business-safety rules**, in this order where several apply to the same operation: unit rentability (`ERR_UNIT_NOT_RENTABLE`), familiarization (`ERR_FAMILIARIZATION_REQUIRED`), engineering plan (`ERR_ENGINEERING_PLAN_REQUIRED`), reach (`ERR_REACH_EXCEEDED`), and segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) — all HTTP 422.
8. **Business constraints**: the close gates (`ERR_LINES_OUTSTANDING` evaluated before `ERR_OPEN_CLAIMS_EXIST`), the unit window conflict (`ERR_UNIT_WINDOW_CONFLICT`), and the route window conflict (`ERR_ROUTE_WINDOW_CONFLICT`) — all HTTP 409.
9. **Fiscal gates**: customer suspension (`ERR_CUSTOMER_SUSPENDED`), then the credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`) — both HTTP 402.

### 2.9. Rental Windows and Driver Route Buffers

Two temporal overlap rules guard the schedule, one for equipment and one for drivers.

Every rental line occupies a half-open calendar window: it begins on `requested_start_date` and runs through `requested_end_date` inclusive, formally ending at the start of the day after `requested_end_date`. A unit may not be committed to two overlapping lines: creating a line is rejected with `ERR_UNIT_WINDOW_CONFLICT` (HTTP 409) when another line on the same unit in `RESERVED`, `OUT_ON_RENT`, or `OFF_RENT` status has a window intersecting the new one. Back-to-back bookings are expressly allowed — when an existing line's window ends exactly where the new window begins, that adjacency is not an intersection. Lines already `RETURNED` or `CANCELLED` never block reuse of their unit.

Every driver follows a buffered route window. A new trip for a given `driver_id` is rejected with `ERR_ROUTE_WINDOW_CONFLICT` (HTTP 409) when its planned window intersects the buffered window of any other trip assigned to the same driver in `SCHEDULED` or `EN_ROUTE` status, where the buffered window extends forty-five minutes before that trip's `planned_start_utc` and forty-five minutes after its `planned_end_utc`. The same buffer check runs again when a failed trip is rescheduled into a new window, evaluated against the trip's assigned driver.

### 2.10. Fleet Rentability and Cascading State Consistency

A serialized unit is rentable only while two conditions hold: its `status` is `AVAILABLE`, and the logical-clock date is on or before its `next_inspection_due_date`. Any attempt to put an unrentable unit out on rent is rejected with `ERR_UNIT_NOT_RENTABLE` (HTTP 422) at the moment the delivery completes.

State changes in this system rarely stop at one resource. Completing a trip moves both a rental line and a unit; certifying a failed inspection quarantines a unit and cancels its reserved lines; charging a lost-or-stolen claim marks the unit lost; recovering a unit credits its charged claims. Each cascade recomputes the affected contract's subtotals and the renting customer's outstanding balance, and every resource mutated along the way — however deep in the chain — has its `version` incremented and its `updated_at` refreshed. If any such recompute pushes a customer's outstanding balance above their credit limit, the account is suspended automatically, as described in §3.1.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and Credit Standing

A `BranchManager` onboards a renter by creating a customer account with a `company_name`, a billing `contact_email`, and a `credit_limit_cents` — the maximum outstanding balance the branch will carry for this customer, which must be zero or positive. New accounts start in `ACTIVE` status with `outstanding_balance_cents` equal to zero.

The outstanding balance is a live aggregate: it is the sum of the invoice totals of exactly those of the customer's rental contracts currently in `ACTIVE` status — contracts still in `DRAFT` and contracts already `CLOSED` are excluded. The balance is recomputed whenever any component of any contract invoice mutates: at activation, at off-rent, at re-rent, at pickup completion, at claim charge or waive, at unit recovery, at line cancellation, and at close.

When a recompute yields an `outstanding_balance_cents` that exceeds `credit_limit_cents`, the customer cascades from `ACTIVE` to `SUSPENDED` and the account's `version` increments. A suspended customer is shut out of new business: creating a contract for them, adding a line to one of their contracts, or activating one of their contracts is rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 402). Reinstatement is a deliberate `BranchManager` action that moves the account from `SUSPENDED` back to `ACTIVE`; it is permitted only while the account is in fact `SUSPENDED` (otherwise `ERR_INVALID_STATE`) and only when the outstanding balance no longer exceeds the credit limit (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402). A successful reinstatement increments the account's `version`.

Reading a customer account is open to `BranchManager` and `RentalCoordinator`; a `Customer` may read only its own record, and reading another customer's record is rejected with `ERR_FORBIDDEN`.

### 3.2. Catalog and Fleet: Classes, Rates, and Serialized Units

The catalog is the branch's menu of rentable equipment. A `BranchManager` creates an equipment class with a unique `class_code` (catalog codes such as S19, BOOM45, or SCAF5X5), a `category` of either `AERIAL_LIFT` or `SCAFFOLD`, and a `max_working_height_ft` — a positive number of feet that caps what customers may book against the class. Pricing is three-tiered: `daily_rate_cents` per billable day, `weekly_rate_cents` per seven-day week block, and `monthly_rate_cents` per twenty-eight-day month block, each zero or positive. The class also carries a `min_rental_days` floor of at least one day, applied to every billable segment, and a `replacement_value_cents`, zero or positive, which becomes the chargeback basis when a unit of the class is lost or stolen. Two booleans gate booking: `requires_familiarization` (default false) demands documented operator training before a line may be created, and `requires_engineering` (default false, typical for scaffolds) demands an engineering plan reference at line creation. The class catalog is readable by `BranchManager`, `RentalCoordinator`, and `Customer`.

The fleet is the physical inventory: serialized units, each registered by a `BranchManager` against a class via `class_id`, with a manufacturer `serial_number` unique across the fleet and an `ansi_standard_ref` naming the governing inspection standard (for example, ANSI A92.22 for an aerial lift or OSHA 1926.451 for a scaffold). Registration stamps the unit's `last_annual_inspection_date` to the logical-clock date — the factory pre-delivery inspection — and computes `next_inspection_due_date` three hundred sixty-five days later; the unit enters service in `AVAILABLE` status. A unit's `status` cycles through `AVAILABLE`, `ON_RENT`, `QUARANTINED`, and `LOST` as trips complete, inspections certify, claims charge, and recoveries occur; the unit is rentable only per §2.10. The fleet list and detail reads are available to `BranchManager`, `RentalCoordinator`, and `YardTechnician`, and the list accepts optional `class_id` and `status` filters alongside `limit` and `offset`.

### 3.3. Contracts and Rental Lines: Booking the Job

Booking begins when a `RentalCoordinator` opens a rental contract for a customer, supplying the `customer_id` and the `jobsite_address` where equipment will be delivered, and optionally electing `damage_waiver_elected` (default false). The election is immutable once the contract leaves `DRAFT`. The contract is created in `DRAFT` status with all subtotals at zero; if the customer is `SUSPENDED`, creation is rejected with `ERR_CUSTOMER_SUSPENDED`. Contract list and detail reads are open to `BranchManager`, `RentalCoordinator`, and `Customer` — a customer's listing is restricted to its own account, with the `customer_id` filter matching its own id — and the list accepts optional `customer_id` and `status` filters with `limit` and `offset`.

Lines are added to the contract while it is in `DRAFT` or `ACTIVE` status. The `RentalCoordinator` submits the `contract_id` of the owning contract and the `unit_id` of the serialized unit being rented, the planned `requested_start_date` and `requested_end_date` (ISO calendar dates; the end date must not fall before the start date), the `required_working_height_ft` the job calls for (a positive number of feet), and the optimistic-concurrency token `expected_contract_version` described in §2.7. When the class requires engineering, an `engineering_plan_ref` must accompany the request. The line is created in `RESERVED` status, its `class_id` is copied from the unit's class and frozen there (denormalized and immutable), its `segment_count` starts at zero and its `accrued_charge_cents` at zero, with `on_rent_at` and `off_rent_at` null and `final_charge_cents` null until the line is returned. Creating the line increments the contract's `version`, recomputes its `rental_subtotal_cents`, and recomputes the customer's outstanding balance.

Line creation is the most heavily guarded write in the system, and its checks evaluate in a fixed order after authentication, authorization, request shape, existence, and the stale-version check of §2.7: familiarization first — when the class's `requires_familiarization` is true, a valid training record must exist for the contract's customer on the line's class, otherwise `ERR_FAMILIARIZATION_REQUIRED`; then engineering — when `requires_engineering` is true, a missing or empty `engineering_plan_ref` is rejected with `ERR_ENGINEERING_PLAN_REQUIRED`; then reach — a `required_working_height_ft` that exceeds the class's `max_working_height_ft` is rejected with `ERR_REACH_EXCEEDED`; then the unit window conflict of §2.9 (`ERR_UNIT_WINDOW_CONFLICT`); and finally the fiscal gate — a `SUSPENDED` customer yields `ERR_CUSTOMER_SUSPENDED`.

Activation commits the contract. A `RentalCoordinator` may activate a contract only while it is in `DRAFT` status and only when at least one of its lines is in `RESERVED` status; violations of either are rejected with `ERR_INVALID_STATE`. Two fiscal gates then apply in order: the customer must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`), and the customer's current `outstanding_balance_cents` plus the sum of `provisional_charge_cents` across the contract's non-`CANCELLED` lines must not exceed the customer's `credit_limit_cents` — otherwise activation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. A successful activation moves the contract from `DRAFT` to `ACTIVE`, increments its `version`, and recomputes the customer's outstanding balance, which from that moment includes this contract.

### 3.4. The Rental Cycle: On Rent, Off Rent, and Re-Rent

Each continuous period a unit spends with the customer is a billable segment, bounded by `on_rent_at` and `off_rent_at`. Billable days are computed from actual elapsed time: the number of seconds between segment start and segment end is divided by the 86,400 seconds in a day and rounded up to a whole day, and the class's `min_rental_days` then applies as a floor — a segment never bills fewer days than the class minimum. The segment charge itself is the lowest of three rate applications over that billable day count: the class's `daily_rate_cents` multiplied by the billable days; the `weekly_rate_cents` multiplied by the number of seven-day week blocks needed to cover the billable days (the day count divided by seven, rounded up); and the `monthly_rate_cents` multiplied by the number of twenty-eight-day month blocks needed to cover them (divided by twenty-eight, rounded up). All inputs are integer cents, so the result is exact and no rounding occurs.

Calling off rent is how a customer stops the billing clock on a line. Either a `RentalCoordinator` or the `Customer` that owns the contract may call a line off rent; the line must currently be `OUT_ON_RENT` and its contract must be `ACTIVE` — violations of either yield `ERR_INVALID_STATE` — and a `Customer` caller's identity must match the contract's `customer_id` (`ERR_FORBIDDEN`). Off-rent stamps `off_rent_at` from the logical clock, finalizes the segment over the actual `on_rent_at`-to-`off_rent_at` interval using the best-rate calculation above, adds that charge into `accrued_charge_cents`, and increments `segment_count`. The line moves from `OUT_ON_RENT` to `OFF_RENT`, its `version` increments, the contract's `rental_subtotal_cents` is recomputed with the contract's `version` incrementing, and the customer's outstanding balance is recomputed — which may trigger the suspension cascade of §3.1.

Re-rent covers the common jobsite pattern of calling off rent and then needing the machine again before the pickup truck arrives. The same two roles may re-rent a line, under the same guards: the line must be `OFF_RENT` and the contract `ACTIVE` (`ERR_INVALID_STATE`), and a `Customer` caller must own the contract (`ERR_FORBIDDEN`). Re-renting moves the line back from `OFF_RENT` to `OUT_ON_RENT`, stamps a fresh `on_rent_at` from the logical clock, clears `off_rent_at` back to null, and increments the line's `version`. Because the customer has kept the equipment, any pickup already scheduled becomes pointless: every `SCHEDULED` pickup trip for the line is cancelled by cascade (each such trip's `version` increments as it moves to `CANCELLED`). The `OUT_ON_RENT` → `OFF_RENT` → `OUT_ON_RENT` cycle may repeat as often as the job demands, and each off-rent finalizes exactly one more billable segment. Because the line's contribution to the contract's rental subtotal switches from accrued charges back to a forward-looking provisional quote, the customer's outstanding balance is recomputed on re-rent as well.

A line leaves the cycle for good when its pickup trip completes: it moves from `OFF_RENT` to `RETURNED`, `final_charge_cents` is set equal to `accrued_charge_cents`, the contract's `rental_subtotal_cents` is recomputed with the contract's `version` incrementing, the customer's balance is recomputed, and the line's `version` increments. `RETURNED` is terminal, as is `CANCELLED`.

Until a line reaches a terminal state, its charge is partly a projection, exposed as `provisional_charge_cents`. The projection is status-dependent. For a `RESERVED` line, the projected segment runs from midnight UTC on `requested_start_date` to midnight UTC on the day after `requested_end_date`, and the provisional charge is the best-rate calculation over that window. For an `OUT_ON_RENT` line, the projected segment runs from `on_rent_at` to the later of the current logical-clock reading and midnight UTC on the day after `requested_end_date`; the provisional charge is the best-rate calculation over that projected segment plus whatever has already accrued into `accrued_charge_cents` from finalized segments. For an `OFF_RENT` line the projection is simply the already-finalized `accrued_charge_cents`. Once `RETURNED`, the provisional charge equals `final_charge_cents`; a `CANCELLED` line's provisional charge is zero. These per-line values feed the contract's `rental_subtotal_cents`: `RETURNED` lines contribute `final_charge_cents`, `OFF_RENT` lines contribute `accrued_charge_cents`, `RESERVED` and `OUT_ON_RENT` lines contribute `provisional_charge_cents`, and `CANCELLED` lines contribute zero.

Lines are listed with optional `contract_id`, `unit_id`, `class_id`, and `status` filters plus `limit` and `offset`, and are readable by `BranchManager`, `RentalCoordinator`, and `Customer`.

### 3.5. Delivery and Pickup Logistics

Every physical movement of equipment runs through a delivery trip. A `RentalCoordinator` schedules a trip with the `contract_id` being serviced, the `line_id` whose unit is moving, a `trip_type` of `DELIVERY` or `PICKUP`, the `driver_id` of the route driver, and a planned route window from `planned_start_utc` to `planned_end_utc` (the end must be strictly later than the start). Scheduling is subject to the forty-five-minute route buffer of §2.9, and the trip is created in `SCHEDULED` status. Trips are listed with optional `contract_id`, `line_id`, `driver_id`, and `status` filters plus `limit` and `offset`, readable by `BranchManager`, `RentalCoordinator`, and `Driver`.

The assigned driver starts the route leg, moving the trip from `SCHEDULED` to `EN_ROUTE`; the trip must be `SCHEDULED` (`ERR_INVALID_STATE`) and the caller must be the assigned driver (`ERR_FORBIDDEN`). Completion is the pivotal event. The assigned driver completes an `EN_ROUTE` trip and may report `standby_minutes` — minutes the crew spent waiting at the jobsite, defaulting to zero — and `crew_labor_hours`, the erection or dismantle labor performed, also defaulting to zero. Completion stamps `completed_at` from the logical clock and computes three charge components: a flat `trip_fee_cents` of 15,000 cents per completed trip; a `standby_charge_cents` that grants the first thirty minutes of standby free and bills each minute beyond thirty at 250 cents (a trip reporting twenty-five standby minutes pays nothing; one reporting ninety pays for sixty); and a `labor_charge_cents` that applies only to scaffolds — when the line's class has `category` `SCAFFOLD`, the labor charge is `crew_labor_hours` multiplied by 9,500 cents per hour, rounded half-up to whole cents, while for `AERIAL_LIFT` lines the labor charge is zero regardless of the hours reported. The trip moves from `EN_ROUTE` to `COMPLETED`, its `version` increments, the contract's `logistics_subtotal_cents` — the sum of trip fee, standby charge, and labor charge across the contract's `COMPLETED` trips — is recomputed with the contract's `version` incrementing, and the customer's outstanding balance is recomputed.

Completion also drives the equipment cascades, and the two trip types behave symmetrically. Completing a `DELIVERY` trip requires its line to be `RESERVED` and the contract to be `ACTIVE` (`ERR_INVALID_STATE`), and the unit to be rentable per §2.10 (`ERR_UNIT_NOT_RENTABLE`); the line then moves from `RESERVED` to `OUT_ON_RENT` with `on_rent_at` stamped from the logical clock and its `version` incrementing, and the unit moves from `AVAILABLE` to `ON_RENT` with its `version` incrementing. Completing a `PICKUP` trip requires its line to be `OFF_RENT` (`ERR_INVALID_STATE`); the line then moves from `OFF_RENT` to `RETURNED` with `final_charge_cents` set to `accrued_charge_cents` and its `version` incrementing, and the unit returns from `ON_RENT` to `AVAILABLE` when the logical-clock date is on or before its `next_inspection_due_date`, or falls from `ON_RENT` to `QUARANTINED` when that date has passed — either way the unit's `version` increments.

Not every run succeeds. The assigned driver may fail an `EN_ROUTE` trip — an access issue, a refused delivery — by supplying a `failure_reason`; a missing reason is rejected with `ERR_INVALID_REQUEST`, and the trip moves from `EN_ROUTE` to `FAILED` with its `version` incrementing and no charges or cascades. A `RentalCoordinator` may then reschedule a `FAILED` trip into a fresh `planned_start_utc`/`planned_end_utc` window, which must clear the route buffer against the trip's assigned driver (`ERR_ROUTE_WINDOW_CONFLICT`); rescheduling replaces the planned window, returns the trip to `SCHEDULED`, and increments its `version`. The `SCHEDULED` → `EN_ROUTE` → `FAILED` → `SCHEDULED` cycle may repeat as often as dispatch requires. Trips reach `CANCELLED` only through the re-rent cascade of §3.4; `COMPLETED` and `CANCELLED` are the terminal states.

### 3.6. Annual Inspections, Certification, and Quarantine

Every unit carries an annual inspection obligation under its governing standard. A `YardTechnician` submits an inspection record with the `unit_id` inspected, the `inspection_date` on which the annual inspection was performed, the `ansi_standard_ref` applied, and a `result` of `PASS` or `FAIL`. The record is created in `SUBMITTED` status with the submitting technician's identity stamped into `inspector_id`, and with `certified_by` and `certified_at` null until a decision is made. Records are listed with an optional `unit_id` filter plus `limit` and `offset`, readable by `BranchManager` and `YardTechnician`.

Decisions belong to a `BranchManager`, under a segregation-of-duties rule: the manager who certifies or rejects a record must not be the technician who submitted it — a caller whose identity equals the record's `inspector_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) on either action. Both actions require the record to be in `SUBMITTED` status (`ERR_INVALID_STATE`), and both stamp `certified_by` with the manager's identity and `certified_at` from the logical clock while incrementing the record's `version`. `CERTIFIED` and `REJECTED` are both terminal.

Certification is where the record bites the fleet. A certified `PASS` rewrites the unit's inspection calendar: `last_annual_inspection_date` is set to the record's `inspection_date` and `next_inspection_due_date` is recomputed three hundred sixty-five days out from it. If the unit was `QUARANTINED`, it returns to `AVAILABLE`; if it was `ON_RENT`, its status is unchanged and only the dates move; either way the unit's `version` increments. A certified `FAIL` is harsher. When the unit is `AVAILABLE`, it moves to `QUARANTINED`, and every `RESERVED` line booked against that unit is cancelled by cascade — each such line moves from `RESERVED` to `CANCELLED` with its `version` incrementing, its contract's `rental_subtotal_cents` is recomputed with the contract's `version` incrementing, and the affected customer's balance is recomputed — while lines already `OUT_ON_RENT` or `OFF_RENT` are unaffected. When the unit is `ON_RENT`, its status is unchanged — the current renter keeps the machine — but the same cancellation cascade still clears the unit's `RESERVED` lines. In all cases the unit's `version` increments. A rejected record has no effect on the unit at all; the inspection simply needs to be redone.

### 3.7. Familiarization Training Documentation

Classes flagged `requires_familiarization` may not be rented by a customer whose crew lacks documented, current training on that class — the gate at line creation described in §3.3, which rejects with `ERR_FAMILIARIZATION_REQUIRED` when no qualifying record exists. A `YardTechnician` documents familiarization training by creating a training record with the `customer_id` whose crew was trained, the `class_id` the familiarization covers, the `trainee_name` of the trained operator, and the `trained_at` timestamp of completion. The technician's identity is stamped into `trainer_id`. The record's `valid_until` is computed as exactly three hundred sixty-five days after `trained_at`, and its `is_valid` is true exactly while the logical clock reads earlier than `valid_until`. A qualifying record for the line-creation gate is one whose `customer_id` matches the contract's customer, whose `class_id` matches the line's class, and whose `is_valid` is true at that moment. Training records are never modified after creation — per §2.5 they carry no `updated_at` and no `version` — and are listed with optional `customer_id` and `class_id` filters plus `limit` and `offset`, readable by `BranchManager`, `RentalCoordinator`, and `YardTechnician`.

### 3.8. Damage, Loss, and Recovery: The Claims Workflow

When equipment comes back damaged — or does not come back — the branch works the claim queue. A `RentalCoordinator`, or the `Customer` owning the contract, reports a claim with the `line_id` the damage or loss occurred on, a `claim_type` of `DAMAGE`, `LOST`, or `STOLEN`, and a free-text `description`. The line must be `OUT_ON_RENT`, `OFF_RENT`, or `RETURNED` — a claim against a line still `RESERVED` or already `CANCELLED` is rejected with `ERR_INVALID_STATE`. The claim is created in `OPEN` status; its `contract_id` and `unit_id` are copied from the line, the reporter's identity is stamped into `reported_by`, and `chargeback_cents`, `recovery_credit_cents`, and `resolved_by` remain null. Claims are listed with optional `line_id`, `unit_id`, `contract_id`, and `status` filters plus `limit` and `offset`; a `Customer` sees only claims on its own contracts.

A `BranchManager` assesses an `OPEN` claim, moving it to `ASSESSED`. For a `DAMAGE` claim the manager supplies `repair_estimate_cents`, which must be present and zero or positive — otherwise `ERR_INVALID_REQUEST`. For `LOST` and `STOLEN` claims no estimate is needed: the system sets `repair_estimate_cents` itself to the class's full `replacement_value_cents`. Assessment increments the claim's `version`.

Charging converts assessment into money. A `BranchManager` charges an `ASSESSED` claim whose contract is still `ACTIVE` (`ERR_INVALID_STATE` otherwise). The `chargeback_cents` computation depends on claim type and the contract's waiver election: for a `DAMAGE` claim on a contract that elected the damage waiver, customer liability is ten percent of `repair_estimate_cents`, rounded half-up to whole cents at charge time and stored as that rounded integer; for a `DAMAGE` claim without the waiver, the chargeback is the full `repair_estimate_cents`; for `LOST` and `STOLEN` claims the waiver never applies and the chargeback is always the class's full `replacement_value_cents`. The manager's identity is stamped into `resolved_by`. Charging then cascades outward: the contract's `damage_subtotal_cents` — the sum of `chargeback_cents` over the contract's claims in `CHARGED` status, minus the sum of `recovery_credit_cents` over those same claims, treating a missing credit as zero — is recomputed with the contract's `version` incrementing; the customer's outstanding balance is recomputed and may trigger the suspension cascade; and for `LOST` and `STOLEN` claims a unit still `ON_RENT` moves to `LOST` with its `version` incrementing. The claim itself moves from `ASSESSED` to `CHARGED` with its `version` incrementing.

The customer may push back: the `Customer` owning the contract disputes a `CHARGED` claim (`ERR_INVALID_STATE` if it is not `CHARGED`; `ERR_FORBIDDEN` if the caller is not the contract's customer), moving it to `DISPUTED` with its `version` incrementing. A `BranchManager` then resolves the dispute with a `decision` of `UPHOLD` or `WAIVE`. Upholding returns the claim from `DISPUTED` to `CHARGED` and re-stamps `resolved_by` — no monetary change occurs, because the chargeback was already applied at charge time — and the `CHARGED` → `DISPUTED` → `CHARGED` cycle may repeat. Waiving moves the claim from `DISPUTED` to `WAIVED`, the compensating action of the charge: the chargeback is removed from the contract's `damage_subtotal_cents`, which is recomputed with the contract's `version` incrementing, the customer's balance is recomputed with a possible suspension cascade, and the claim's `version` increments. `WAIVED` is terminal.

Recovery closes the loop on lost equipment. A `BranchManager` recovers a unit that is `LOST` (`ERR_INVALID_STATE` otherwise). Every claim on that unit with `claim_type` `LOST` or `STOLEN`, still in `CHARGED` status, and with `recovery_credit_cents` still null receives a recovery credit equal to eighty percent of its `chargeback_cents`, rounded half-up to whole cents per claim. Each credited claim's contract has its `damage_subtotal_cents` recomputed — decreasing by the credited amount — with the contract's `version` incrementing, and each affected customer's outstanding balance is recomputed with a possible suspension cascade. The recovered unit returns to `AVAILABLE` when the logical-clock date is on or before its `next_inspection_due_date`, or to `QUARANTINED` when that date has passed, and the unit's `version` increments.

### 3.9. Close-Out and the Customer Invoice

Close-out is deliberately gated, and the gates evaluate in a fixed order: the contract must be `ACTIVE` (`ERR_INVALID_STATE`); then every line of the contract must be in `RETURNED` or `CANCELLED` status — a line anywhere else is rejected with `ERR_LINES_OUTSTANDING` (HTTP 409); then no claim of the contract may remain in `OPEN`, `ASSESSED`, or `DISPUTED` status — otherwise `ERR_OPEN_CLAIMS_EXIST` (HTTP 409). A `RentalCoordinator` performs the close. On success the contract moves from `ACTIVE` to `CLOSED` — its terminal state — `closed_at` is stamped from the logical clock, the contract's `version` increments, and the invoice is finalized: with all lines returned or cancelled, the rental subtotal now rests entirely on final charges. Because the contract leaves the `ACTIVE` inclusion set, the customer's outstanding balance is recomputed and the closed contract stops counting toward it.

The invoice itself is available to `BranchManager`, `RentalCoordinator`, and `Customer` throughout the contract's life, and always reflects the pinned rounding order of §2.6. Its body carries the `contract_id`, the contract's `status`, and four integer-cent figures: `rental_subtotal_cents` aggregated from the lines per §3.4, `logistics_subtotal_cents` aggregated from completed trips per §3.5, `damage_subtotal_cents` aggregated from claims per §3.8, and `invoice_total_cents` as the sum of the three subtotals. Every component is stored as integer cents at its own computation time, and the totals sum those stored integers without re-rounding.

## 4. Endpoint Definitions

Operations that create a new resource — a customer account, an equipment class, a unit, a contract, a line, a trip, an inspection record, a training record, or a claim — return `201 Created`. Operations that modify an existing resource, including every state-transition action, and all reads return `200 OK`. Request payloads, validations, and side effects for each operation are specified in §2 and §3; this table is the navigational index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customer-accounts` | Create a renter customer account | BranchManager |
| GET | `/customer-accounts/{id}` | Read one customer (Customer restricted to own id) | BranchManager, RentalCoordinator, Customer |
| POST | `/customer-accounts/{id}/reinstate` | Reinstate a SUSPENDED customer whose balance is back within the credit limit | BranchManager |
| POST | `/equipment-classes` | Create a catalog equipment class | BranchManager |
| GET | `/equipment-classes` | List equipment classes (paginated) | BranchManager, RentalCoordinator, Customer |
| POST | `/equipment-units` | Register a serialized unit; factory pre-delivery inspection stamps the inspection dates | BranchManager |
| GET | `/equipment-units` | List units with optional filters | BranchManager, RentalCoordinator, YardTechnician |
| GET | `/equipment-units/{id}` | Read one unit | BranchManager, RentalCoordinator, YardTechnician |
| POST | `/equipment-units/{id}/recover` | Recover a LOST unit; applies recovery credit and returns the unit to AVAILABLE or QUARANTINED | BranchManager |
| POST | `/rental-contracts` | Create a rental contract in DRAFT | RentalCoordinator |
| GET | `/rental-contracts` | List contracts (Customer restricted to own customer_id filter) | BranchManager, RentalCoordinator, Customer |
| GET | `/rental-contracts/{id}` | Read one contract (Customer restricted to own) | BranchManager, RentalCoordinator, Customer |
| POST | `/rental-contracts/{id}/activate` | Activate a DRAFT contract (requires at least one RESERVED line; credit check) | RentalCoordinator |
| POST | `/rental-contracts/{id}/close` | Close an ACTIVE contract once all lines are RETURNED/CANCELLED and all claims resolved | RentalCoordinator |
| GET | `/rental-contracts/{id}/invoice` | Computed invoice read with pinned rounding order | BranchManager, RentalCoordinator, Customer |
| POST | `/rental-lines` | Add a line to a DRAFT or ACTIVE contract (OCC on contract version) | RentalCoordinator |
| GET | `/rental-lines` | List lines with optional filters | BranchManager, RentalCoordinator, Customer |
| GET | `/rental-lines/{id}` | Read one line | BranchManager, RentalCoordinator, Customer |
| POST | `/rental-lines/{id}/off-rent` | Call a line off rent; finalizes the current billable segment with the minimum-period floor | RentalCoordinator, Customer |
| POST | `/rental-lines/{id}/re-rent` | Re-rent an OFF_RENT line before pickup; cancels its SCHEDULED pickup trips | RentalCoordinator, Customer |
| POST | `/delivery-trips` | Schedule a delivery or pickup trip (route buffer check per driver) | RentalCoordinator |
| GET | `/delivery-trips` | List trips with optional filters | BranchManager, RentalCoordinator, Driver |
| GET | `/delivery-trips/{id}` | Read one trip | BranchManager, RentalCoordinator, Driver |
| POST | `/delivery-trips/{id}/start` | Assigned driver starts the route leg | Driver |
| POST | `/delivery-trips/{id}/complete` | Assigned driver completes the trip; reports standby and labor; cascades line and unit transitions | Driver |
| POST | `/delivery-trips/{id}/fail` | Assigned driver marks the trip failed (access issue, refused delivery, etc.) | Driver |
| POST | `/delivery-trips/{id}/reschedule` | Reschedule a FAILED trip to a new route window (route buffer re-checked) | RentalCoordinator |
| POST | `/inspection-records` | Yard technician submits an annual inspection result | YardTechnician |
| GET | `/inspection-records` | List inspection records with optional unit filter | BranchManager, YardTechnician |
| GET | `/inspection-records/{id}` | Read one inspection record | BranchManager, YardTechnician |
| POST | `/inspection-records/{id}/certify` | Branch manager certifies a submitted inspection (must not be the inspector) | BranchManager |
| POST | `/inspection-records/{id}/reject` | Branch manager rejects a submitted inspection (must not be the inspector) | BranchManager |
| POST | `/training-records` | Document familiarization training for a customer's crew on an equipment class | YardTechnician |
| GET | `/training-records` | List training records with optional filters | BranchManager, RentalCoordinator, YardTechnician |
| GET | `/training-records/{id}` | Read one training record | BranchManager, RentalCoordinator, YardTechnician |
| POST | `/damage-claims` | Report damage or loss on a line that is OUT_ON_RENT, OFF_RENT, or RETURNED | RentalCoordinator, Customer |
| GET | `/damage-claims` | List claims with optional filters (Customer restricted to own contract's claims) | BranchManager, RentalCoordinator, Customer |
| GET | `/damage-claims/{id}` | Read one claim | BranchManager, RentalCoordinator, Customer |
| POST | `/damage-claims/{id}/assess` | Assess an OPEN claim (repair estimate for DAMAGE; replacement value auto-set for LOST/STOLEN) | BranchManager |
| POST | `/damage-claims/{id}/charge` | Charge an ASSESSED claim; computes the chargeback and cascades to contract, customer, and unit | BranchManager |
| POST | `/damage-claims/{id}/dispute` | Customer disputes a CHARGED claim | Customer |
| POST | `/damage-claims/{id}/resolve` | Resolve a DISPUTED claim: UPHOLD returns to CHARGED, WAIVE moves to WAIVED and backs out the chargeback | BranchManager |
| POST | `/_clock/set_current_utc` | Set the logical server clock (test-driving endpoint; startup default 2026-08-01T00:00:00Z) | BranchManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the reference index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNIT_NOT_RENTABLE` | 422 |
| `ERR_FAMILIARIZATION_REQUIRED` | 422 |
| `ERR_ENGINEERING_PLAN_REQUIRED` | 422 |
| `ERR_REACH_EXCEEDED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_LINES_OUTSTANDING` | 409 |
| `ERR_OPEN_CLAIMS_EXIST` | 409 |
| `ERR_UNIT_WINDOW_CONFLICT` | 409 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 402 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
