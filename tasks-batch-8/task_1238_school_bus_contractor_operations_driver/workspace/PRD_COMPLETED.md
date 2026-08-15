# School Bus Contractor Operations API — Product Requirements Document

## 1. Introduction

A school bus contractor in the mold of First Student lives and dies by a daily promise: every contracted route, every school morning, covered by a credentialed driver in an inspected bus — and a monthly invoice that the district can audit down to the cent. This document specifies the School Bus Contractor Operations API, a single REST surface mounted under `/busops`, through which the contractor runs that promise end to end: bidding and winning district contracts, recruiting and certifying drivers through a CDL and S-endorsement training pipeline, keeping the fleet inspection-compliant, dispatching every service day, absorbing driver shortages through route-doubling decisions, selling field-trip charters, and billing the district with a fuel-escalation clause, shortage credits, and a monthly cap.

The system serves seven distinct operator populations — district administrators, contractor dispatchers, recruiters, fleet managers, finance clerks, drivers, and a platform operator — each with its own surface. It is deliberately strict about the things school transportation is strict about: no driver touches a route without an active CDL-B and S-endorsement, no bus rolls with an overdue state inspection, no invoice exceeds its monthly cap, and no district acknowledgment of a critical incident may slip past its 24-hour SLA unnoticed. All side effects are atomic within the triggering request: when a credential expires, a bus fails inspection, or a contract is terminated, every downstream cancellation and recomputation lands in the same transaction.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the capacity in which they act. The system recognizes exactly seven roles: `SystemAdmin`, `DistrictAdmin`, `ContractorOps`, `HRRecruiter`, `FleetManager`, `FinanceClerk`, and `Driver`. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles have entity-backed identities. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is the `id` of the acting District; ownership checks on any resource that resolves to a district — a contract, a charter under a contract, an invoice under a contract, an incident addressed to a district — compare the resource's district foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting Driver; a driver may act only on assignments whose `driver_id` equals `X-User-ID` and may read only their own driver record, with the same `ERR_FORBIDDEN_OWNERSHIP` rejection on mismatch. The remaining roles — `SystemAdmin`, `ContractorOps`, `HRRecruiter`, `FleetManager`, and `FinanceClerk` — carry an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. Ownership is enforced on single-resource reads and on mutations; list endpoints are not ownership-filtered and return the unfiltered collection to any authorized role. A resource carrying no district or driver reference (for example, a still-`PLANNED` assignment with `driver_id` null) is not ownership-restricted on read.

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

Requests to unmatched paths, or matched paths with an unsupported method, are reported in the same envelope as `ERR_NOT_FOUND` (HTTP 404); unexpected server faults are reported as `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. All list endpoints sort by `created_at` ascending, with ties broken by creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Change Semantics

Every primary resource — District, Contract, Route, Driver, Credential, Bus, Inspection, WorkOrder, ServiceDay, Assignment, CharterTrip, Invoice, and Incident — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that starts at 1 and increments by one on every mutation, including system-driven mutations caused by cascades and clock advancement. `created_at` and `updated_at` are stamped from real wall-clock UTC; only the business date and instant fields described in §3 derive from the logical clock of §2.5.

Three resources are append-only and carry only `id` and `created_at` — both `updated_at` and `version` are absent on them: TrainingEvent, FuelPriceEntry, and RidershipReport. Once written, they are never modified.

Free-text annotations supplied with transition requests — `reason`, `resolution_note`, and the like — are accepted but not persisted, except where the resource defines a dedicated field: `cancellation_reason` on ServiceDay and Assignment, `suspension_reason` on Driver, and `dispute_reason` on Invoice.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every date- and time-sensitive rule in this document: credential expiry, inspection overdue detection, charter quote expiry, contract expiry, dispute windows, SLA deadlines, and all "on or after the clock date" comparisons. At server startup the clock is exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A `SystemAdmin`-only test-driving capability advances the clock by supplying a `to_iso8601` instant, and the response reports the resulting `current_utc`. Any parsable instant is accepted — the endpoint performs no monotonicity check, so the supplied instant may precede the current value. Logical-clock-derived fields (`hired_on`, `completed_on`, `issued_on`, `paid_on`, `submitted_at`, `district_due_by`, `acknowledged_at`, `quote_valid_until`, `occurred_at`) serialize at seconds precision. Advancing the clock is a system event with teeth: it fires the time-based transitions described throughout §3 — credentials lapse, inspections go overdue, charter quotes expire, and contracts expire — each with its full cascade applied atomically in the same request.

### 2.6. Monetary Precision and Rounding Discipline

All money in the system is integer cents; there are no fractional-cent values anywhere. Where a formula produces a non-integer intermediate — fuel per-gallon tier rates, per-day fuel adjustments, charter cancellation fees — the result is rounded half-up to whole cents at the step the relevant rule specifies, and the rounding order pinned by that rule is mandatory because alternative orders produce different cents. Hour-to-money conversions for charters floor to whole cents because durations are stored in tenths of an hour (`estimated_hours_x10`, `actual_hours_x10`). Percentages exposed to districts, such as on-time performance, are stored as the percentage multiplied by one hundred and floored to an integer.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its required version field explicitly:

- Applying a pricing amendment to a Contract requires `expected_contract_version` in the request body, carrying the client's last observed `version` of that contract. If the contract's current `version` has advanced — for example because another amendment or a lifecycle transition landed since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the amendment to be rebased on pricing terms the client has actually seen.
- Locking a ServiceDay requires `expected_service_day_version`. A lock issued against a stale view of the day — one that does not reflect confirms or cancellations that have since landed — is rejected with `ERR_STALE_VERSION` (HTTP 412), so a lock never freezes a state the caller never observed.
- Approving a CharterTrip requires `expected_charter_trip_version`. Because issuing a quote increments the trip's version, an approval carrying a pre-quote version pins a price the district never saw; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not accept a version field at all; a version field sent to a non-guarded endpoint is ignored rather than rejected. When a guarded mutation succeeds, the parent entity's `version` increments as part of the same request.

### 2.8. The Validation Pipeline and Its Ordering

Every request passes through a fixed validation pipeline, and the order is part of the contract — when several checks would fail, the earliest one in this order determines the error returned:

1. **Schema and format.** The body parses, required fields are present, enum values are valid, and integers are in range; violations yield `ERR_INVALID_REQUEST` (HTTP 400). Integer money and count fields are non-negative unless a rule states otherwise (an invoice `adjustment_delta_cents` may be negative), and minute-of-day fields (`am_start_minute`, `am_end_minute`, `pickup_minute`, `return_minute`, `actual_start_minute`, `actual_end_minute`, `first_pickup_actual_minute`, `last_dropoff_actual_minute`) accept integers from 0 through 1439 inclusive. Endpoint-level conditional presence is evaluated at this same stage, before any existence or state lookup — notably, confirming an assignment requires `driver_id` and `bus_id` together, and a payload missing either, or carrying a non-string value for either, is rejected here with `ERR_DRIVER_REQUIRED` (HTTP 422); likewise a `COMPLETE` work-order event missing `labor_minutes` or `parts_cost_cents` is rejected here with `ERR_INVALID_REQUEST`.
2. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is recognized, else `ERR_UNAUTHENTICATED` (HTTP 401).
3. **Role authorization.** The acting role appears in the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE` (HTTP 403).
4. **Existence.** Path identifiers are resolved first, then body foreign-key references — `contract_id`, `district_id`, `driver_id`, `bus_id`, `route_id`, `assignment_id`, and the uncovered/absorbing assignment identifiers of a doubling decision — validated left to right; the first missing reference yields `ERR_NOT_FOUND` (HTTP 404). Because the API's topology is flat, no nested path prefixes need walking; the left-to-right rule still governs the order in which references are checked.
5. **Entity-backed ownership.** A `DistrictAdmin` may act only on resources whose district matches `X-User-ID`, and a `Driver` only on their own assignments and record, else `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
6. **Optimistic concurrency.** On the three OCC-guarded operations of §2.7, the expected version must match the parent's current version, else `ERR_STALE_VERSION` (HTTP 412).
7. **Terminal-state rejection.** An entity already in a terminal state accepts no further transitions; attempts yield `ERR_ALREADY_TERMINAL` (HTTP 409). The terminal set is per resource: Contract (`EXPIRED`, `TERMINATED`, `WITHDRAWN`, `LOST`), Route (`ARCHIVED`), Driver (`TERMINATED`), Credential (`REVOKED`), Bus (`DECOMMISSIONED`), Inspection (`CANCELLED`), WorkOrder (`COMPLETED`, `CANCELLED`), ServiceDay (`CANCELLED`, `INVOICED`), Assignment (`COMPLETED`, `NO_SHOW`, `CANCELLED`), CharterTrip (`EXPIRED`, `DECLINED`, `CANCELLED`, `INVOICED`), Invoice (`PAID`, `WRITTEN_OFF`), and Incident (`CLOSED`). A state not in this list that nonetheless lacks the requested transition — for example an `EXPIRED` credential being revoked — falls through to the from-state check below.
8. **From-state validity.** The entity must be in a state from which the requested transition exists, else `ERR_INVALID_STATE` (HTTP 409).
9. **Driver dispatchability.** Where dispatch requires it: the driver's status is `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), the driver holds an active CDL-B credential (`ERR_CREDENTIAL_EXPIRED`), holds an active S-endorsement (`ERR_ENDORSEMENT_MISSING`), and has `license_class` B (`ERR_LICENSE_CLASS_INSUFFICIENT`).
10. **Bus dispatchability.** The bus is `IN_SERVICE` (`ERR_BUS_NOT_IN_SERVICE`), its `next_inspection_due` is on or after the service or trip date (`ERR_INSPECTION_OVERDUE`), and its `capacity` covers the ridership (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422).
11. **Temporal rules.** Interval-overlap rules (`ERR_DRIVER_OVERLAP_CONFLICT`, `ERR_BUS_OVERLAP_CONFLICT`), the charter buffered window (`ERR_CHARTER_BUS_UNAVAILABLE`), the trip date not in the past (`ERR_CHARTER_DATE_PAST`), the dispute window (`ERR_DISPUTE_WINDOW_CLOSED`), service dates within the contract term (`ERR_OUTSIDE_CONTRACT_TERM`), incidents not in the future (`ERR_FUTURE_INCIDENT`), and time ranges with a strictly positive duration (`ERR_INVALID_TIME_RANGE`).
12. **Constraint rules.** Weekly-minute caps (`ERR_DRIVER_HOURS_CAP_EXCEEDED`), training-hour thresholds (`ERR_TRAINING_HOURS_INSUFFICIENT`), doubling feasibility (`ERR_DOUBLING_INFEASIBLE`), and uniqueness rules (`ERR_DUPLICATE_ROUTE_CODE`, `ERR_FUEL_ENTRY_DUPLICATE_MONTH`, `ERR_SERVICE_DAY_DATE_CONFLICT`, `ERR_DUPLICATE_RIDERSHIP_REPORT`), plus discipline context (`ERR_DISCIPLINE_CONTEXT_REQUIRED`) and in-flight assignments at reconcile (`ERR_ASSIGNMENTS_IN_FLIGHT`).
13. **Referential consistency.** The bus's home district matches the contract's district (`ERR_BUS_DISTRICT_MISMATCH`), the fuel index entry exists for the billed district and period (`ERR_FUEL_ENTRY_MISSING`), and incident route/service-day references belong to the incident's district (`ERR_CROSS_DISTRICT_REFERENCE`).
14. **Fiscal rules.** The district credit check (`ERR_DISTRICT_CREDIT_HOLD`, HTTP 402), the invoice period containing something final to bill (`ERR_INVOICE_PERIOD_INCOMPLETE`), and the contract being `ACTIVE` where required (`ERR_CONTRACT_NOT_ACTIVE`).

### 2.9. Cascading Consistency Across the Roster, Fleet, and Calendar

The system treats driver employability, bus legality, and contract vitality as invariant backbones. When one of them breaks — a driver's credential lapses, a bus fails inspection, a contract is terminated — the break propagates immediately and atomically: future commitments built on the broken resource are cancelled with a reason that names the cause, and every affected ServiceDay recomputes its coverage and shortage figures in the same request. Conversely, recovery is equally explicit: a reinstated driver or a bus returned to service does not resurrect cancelled work; dispatchers rebuild coverage through new confirmations and doubling decisions. Each mutation a cascade performs on an entity refreshes that entity's `updated_at` and increments its `version` independently.

## 3. Business Logic & Workflows

### 3.1. Districts and the Contract Bid Lifecycle

Everything begins with a District. A `SystemAdmin` creates one with a display `name`, a `region_fuel_index_code` identifying which fuel price index governs its escalation clauses, a `credit_limit_cents` bounding the district's outstanding billed balance, and an optional `billing_dispute_window_days` that defaults to 30 when omitted. A district's `status` is `ACTIVE` — version 1 has no district suspension lifecycle — and its `outstanding_balance_cents` is a computed figure, derived from its invoices as described in §3.7, starting at zero.

A `ContractorOps` manager bids on district work by creating a Contract, which is born in `DRAFT_BID` with `amendment_seq` at zero. The bid payload carries the commercial spine of the relationship: `district_id`, the district's `bid_reference`, the `daily_rate_per_bus_cents` that prices every bus-day, the `school_days_per_year` under contract, and the `start_date` and `end_date` bounding the term. Fuel economics come from `fuel_base_price_cents` — the cents-per-gallon baseline — plus two optional knobs: `fuel_escalation_trigger_pct` (default 5) and `fuel_escalation_share_pct` (default 80), whose mechanics §3.7 details. Shortage remedies are selected by `penalty_mode`: under `FLAT_PER_ROUTE` each uncovered route-day credits `shortage_penalty_flat_cents`, while under `PER_STUDENT_MINUTE` the credit scales with `shortage_penalty_per_student_minute_cents` and the `assumed_minutes_per_missed_route` each rider is presumed to lose. All three shortage fields are required at creation regardless of the selected mode, and no ordering constraint between `start_date` and `end_date` is enforced. Charter pricing uses `charter_hourly_rate_cents` and `charter_per_mile_cents`, and `monthly_cap_cents` bounds every invoice total for the contract.

From `DRAFT_BID`, the contractor submits the bid, moving it to `SUBMITTED` and incrementing its version. The owning `DistrictAdmin` then either awards it — `SUBMITTED` to `AWARDED`, again incrementing the version — or marks it lost, moving it to terminal `LOST`. The contractor may instead withdraw a submitted bid, landing in terminal `WITHDRAWN`. An awarded contract goes live when the contractor activates it, but only once the logical clock date has reached the contract's `start_date`; activating earlier is rejected with `ERR_CONTRACT_NOT_YET_STARTED`. Thereafter, when the clock advances beyond the contract's `end_date`, the system itself moves the contract from `ACTIVE` to terminal `EXPIRED`.

Termination is the heavy hammer. The owning `DistrictAdmin` may terminate an `ACTIVE` contract, optionally supplying a `reason`, and the cascade is total: every route of the contract in `ACTIVE` or `SUSPENDED` status becomes `ARCHIVED`; every service day in `SCHEDULED`, `DISPATCH_OPEN`, or `LOCKED` becomes `CANCELLED` under the contract-termination cause; every assignment on those days in `PLANNED` or `CONFIRMED` becomes `CANCELLED` with `cancellation_reason` `CONTRACT_TERMINATED`; and every charter trip of the contract in `REQUESTED`, `QUOTED`, `APPROVED`, or `SCHEDULED` becomes `CANCELLED` with `cancel_fee_cents` zero and `refund_cents` equal to the full `deposit_cents` — termination is fee-free to the district.

Pricing terms may evolve while a contract is `AWARDED` or `ACTIVE` through amendments. The owning `DistrictAdmin` applies one by carrying `expected_contract_version` per §2.7 plus any subset of the amendable pricing fields — `daily_rate_per_bus_cents`, `fuel_base_price_cents`, `fuel_escalation_trigger_pct`, `fuel_escalation_share_pct`, `monthly_cap_cents`, `shortage_penalty_flat_cents`, and `shortage_penalty_per_student_minute_cents`. A successful amendment increments the contract's `version` by one and bumps `amendment_seq`; a stale expected version is rejected with `ERR_STALE_VERSION`. Contracts can be listed filtered by `district_id` and `status`.

### 3.2. Routes and Service-Day Planning

Under an `ACTIVE` contract, `ContractorOps` defines Routes, each created `ACTIVE` with a `route_code` unique within the contract among non-archived routes — a duplicate is rejected with `ERR_DUPLICATE_ROUTE_CODE` — plus the `school_site` served, the planned AM run window as `am_start_minute` and `am_end_minute` in minutes since midnight (the end must be strictly after the start, else `ERR_INVALID_TIME_RANGE`), and the `student_count` of assigned riders. Creating a route under a contract that is not `ACTIVE` fails with `ERR_CONTRACT_NOT_ACTIVE`. Routes may be listed filtered by `contract_id` and `status`.

Routes are reversible until they are not. Deactivating a route without archiving moves `ACTIVE` to `SUSPENDED`, a parking state that excludes the route from coverage planning; reactivation returns it to `ACTIVE` provided the owning contract is still `ACTIVE`. Deactivating with `archive` set to true moves a `SUSPENDED` route to terminal `ARCHIVED`, but only while no assignment on this route remains in `PLANNED`, `CONFIRMED`, or `EN_ROUTE` on any service day dated on or after the clock date; a blocked archive is rejected with `ERR_INVALID_STATE` (HTTP 409).

Service days are the unit of daily operations. `ContractorOps` creates one with a `contract_id` and a `service_date`; the contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`), the date must fall within the contract's `start_date`-to-`end_date` term inclusive (else `ERR_OUTSIDE_CONTRACT_TERM`, HTTP 422), and one contract may not have two days on the same date (else `ERR_SERVICE_DAY_DATE_CONFLICT`). Creation does real work: the day is born `SCHEDULED`, its `required_routes` is computed as the count of the contract's routes that are `ACTIVE` at that moment (suspended routes do not count), and one `PLANNED` assignment is auto-created per active route with `planned_start_minute` and `planned_end_minute` copied from the route's AM window. From then on the system maintains `covered_routes` — assignments of the day with a `driver_id` set and status `CONFIRMED`, `EN_ROUTE`, or `COMPLETED` — and `uncovered_routes` as the required count minus the covered count, with `shortage_flag` true exactly when anything is uncovered. `shortage_credit_cents` stays zero until reconcile, and `cancellation_reason` stays null unless the day is cancelled. Service days can be listed filtered by `contract_id`, `status`, and `service_date`.

The daily epoch advances in stages. Opening dispatch moves `SCHEDULED` to `DISPATCH_OPEN` — allowed only while the contract is `ACTIVE` — and increments the day's version. Locking moves `DISPATCH_OPEN` to `LOCKED` and is OCC-guarded per §2.7: the request carries `expected_service_day_version`, a mismatch is rejected with `ERR_STALE_VERSION`, and a successful lock increments the version. What happens in `LOCKED`, and how a day reaches `RECONCILED` and finally `INVOICED`, is the subject of §3.5.

Weather and district closures cancel a day outright: from `SCHEDULED`, `DISPATCH_OPEN`, or `LOCKED`, `ContractorOps` cancels with a `cancellation_reason` of `WEATHER` or `DISTRICT_CLOSURE`. Every assignment of the day in `PLANNED` or `CONFIRMED` is cancelled with reason `WEATHER`, and a cancelled day is excluded from invoice billing under both variants and from shortage credit entirely.

### 3.3. The Driver Pipeline: Recruitment, Training, Credentials, and Discipline

An `HRRecruiter` onboards a driver by creating the record with `primary_district_id` — the district the driver is credentialed for — plus `full_name`, `license_number`, `license_class` (`A` or `B`; school bus dispatch requires `B`), and `hourly_wage_cents`. The record is born `APPLICANT` with all computed counters — `behind_wheel_minutes`, `classroom_minutes`, `test_fail_count`, `weekly_assigned_minutes` — at zero and `hired_on` null. Drivers may be listed filtered by `primary_district_id` and `status`; a `Driver`-role caller may read only their own record. The reported `weekly_assigned_minutes` is derived at read time as the driver's §3.5 projection over the ISO week containing the logical clock date.

The pipeline advances through recruiter-posted events identified by `event_type`, each optionally annotated with a `reason`. `SCREEN` moves `APPLICANT` to `SCREENING`; `ENROLL` moves `SCREENING` to `TRAINING`. Training hours accumulate through append-only TrainingEvents, each logging a `driver_id`, a `category` of `CLASSROOM`, `BEHIND_WHEEL`, or `SAFETY`, a positive `minutes` duration, and the `occurred_on` date; every logged event recomputes the driver's aggregates, with `behind_wheel_minutes` summing only `BEHIND_WHEEL` events and `classroom_minutes` summing only `CLASSROOM` events — `SAFETY` minutes count toward neither. Training events may be listed filtered by `driver_id` and `category`. `SCHEDULE_TEST` moves `TRAINING` to `TESTING`, and is gated on both aggregates: at least 2400 behind-wheel minutes and at least 1200 classroom minutes, both thresholds inclusive, so exactly 2400 and 1200 qualifies while 2399 behind-wheel fails with `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422). The testing loop is cyclic: `TEST_FAIL` sends the driver back to `TRAINING` and increments `test_fail_count`, while `TEST_PASS` promotes to `CERTIFIED` — but only if the driver already holds a credential of `kind` `CDL_B` with status `ACTIVE`, failing with `ERR_CREDENTIAL_EXPIRED` otherwise. Finally, `ACTIVATE` moves `CERTIFIED` to `ACTIVE` provided the driver holds an active `S_ENDORSEMENT` credential (else `ERR_ENDORSEMENT_MISSING`), and stamps `hired_on` with the logical clock date. `TERMINATE` ends the line from any non-terminal state — `APPLICANT`, `SCREENING`, `TRAINING`, `TESTING`, `CERTIFIED`, `ACTIVE`, or `SUSPENDED` — moving the driver to terminal `TERMINATED` and cancelling every assignment of theirs in `PLANNED` or `CONFIRMED` on service days dated on or after the clock date with `cancellation_reason` `DRIVER_SUSPENDED`, recomputing each affected day's shortage fields.

Credentials are recorded by the recruiter with a `driver_id`, a `kind` of `CDL_B`, `S_ENDORSEMENT`, or `FIRST_AID`, an `issued_on` date, and an `expires_on` date; the credential is valid through its `expires_on` — expiry begins the day after — and is born `ACTIVE`. A credential may only be recorded for a driver in `TRAINING`, `TESTING`, `CERTIFIED`, `ACTIVE`, or `SUSPENDED`; recording for an `APPLICANT` or `SCREENING` driver is rejected with `ERR_INVALID_STATE`, and for a `TERMINATED` driver with `ERR_ALREADY_TERMINAL`. No ordering constraint between `issued_on` and `expires_on` is enforced. Two forces end a credential. The recruiter may revoke it, moving `ACTIVE` to terminal `REVOKED` with an optional `reason`. Or the logical clock may advance past it: any credential whose `expires_on` falls before the new clock date flips from `ACTIVE` to `EXPIRED`. Either way, when the lost credential is a `CDL_B` or `S_ENDORSEMENT` and its holder is an `ACTIVE` driver, the same protective cascade fires: the driver is suspended with `suspension_reason` `CREDENTIAL_LAPSED`, their future `CONFIRMED` assignments are cancelled with reason `DRIVER_SUSPENDED`, and every affected service day recomputes its coverage and shortage fields. Credentials may be listed filtered by `driver_id`, `kind`, and `status`.

Discipline is the contractor's lever, exercised through a discipline posting carrying an `action` and an optional `reason`. An `action` of `SUSPEND` on an `ACTIVE` driver moves them to `SUSPENDED` with `suspension_reason` `DISCIPLINE` and fires the same assignment cascade: future `CONFIRMED` assignments on days dated on or after the clock date are cancelled with reason `DRIVER_SUSPENDED`, and each affected service day recomputes its `covered_routes`, `uncovered_routes`, and `shortage_flag`. An `action` of `REINSTATE` on a `SUSPENDED` driver returns them to `ACTIVE` and clears `suspension_reason` to null — but only when the driver once again holds both an active `CDL_B` (else `ERR_CREDENTIAL_EXPIRED`) and an active `S_ENDORSEMENT` (else `ERR_ENDORSEMENT_MISSING`).

### 3.4. Fleet Compliance: Buses, Inspections, and Work Orders

A `FleetManager` registers each Bus with its home `district_id`, a `fleet_number` recorded as supplied (no uniqueness check is enforced), a passenger `capacity`, a `fuel_type` of `DIESEL`, `GASOLINE`, or `ELECTRIC`, an `mpg_x10` — fuel economy multiplied by ten, so 80 means 8.0 miles per gallon; even `ELECTRIC` buses carry a diesel-equivalent figure for escalation accounting — and the `next_inspection_due` date. The bus is born `IN_SERVICE` with `odometer_miles` at zero; the odometer advances only through completed work, as §3.5 and §3.6 describe. Buses may be listed filtered by `district_id` and `status`.

State inspections are scheduled per bus with a `bus_id`, a `scheduled_date`, and an `inspector_ref`, and are born `SCHEDULED`. Scheduling is rejected with `ERR_INSPECTION_DAY_CONFLICT` when the bus holds a `CONFIRMED` assignment on the proposed date — inspection occupies the whole day, so interval arithmetic does not apply. Scheduling an inspection on a `DECOMMISSIONED` bus is rejected with `ERR_ALREADY_TERMINAL`. When the inspector's verdict arrives, the fleet manager records a `result` of `PASS` or `FAIL`, optionally with a new `next_inspection_due`; a result may be recorded while the inspection is `SCHEDULED` or `OVERDUE`. Recording `PASS` sets `completed_on` to the clock date, moves the inspection to `PASSED`, updates the bus's `next_inspection_due` from the supplied value, and — provided no work order on the bus remains open — returns a `GROUNDED` or `IN_SHOP` bus to `IN_SERVICE`. Recording `FAIL` sets `completed_on`, moves the inspection to `FAILED`, grounds the bus, and cancels every assignment on that bus in `PLANNED` or `CONFIRMED` on days dated on or after the clock date with `cancellation_reason` `BUS_GROUNDED`, recomputing shortage fields on each affected day. Inspections may be listed filtered by `bus_id` and `status`.

Time itself is a hazard: when the logical clock advances past a `SCHEDULED` inspection's `scheduled_date` with no result recorded, the inspection flips to `OVERDUE` and the exact same grounding cascade fires — bus to `GROUNDED`, future assignments cancelled `BUS_GROUNDED`, shortage recomputed. The re-inspection loop is cyclic: a `FAILED` inspection may be rescheduled back to `SCHEDULED` with a new `scheduled_date` on or after the clock date (an earlier date is rejected with `ERR_INVALID_TIME_RANGE`), clearing `result` and `completed_on` to null. A `SCHEDULED` inspection may also simply be cancelled, landing in terminal `CANCELLED`.

Work orders are the repair lane. Creating one with a `bus_id`, a `category` of `PM`, `REPAIR`, or `INSPECTION_FOLLOWUP`, and a `description` opens it in `OPEN` and immediately moves an `IN_SERVICE` bus to `IN_SHOP`; a `GROUNDED` bus moves to `IN_SHOP` only when the order's category is `REPAIR` or `INSPECTION_FOLLOWUP` — a `PM` order leaves a grounded bus grounded. Opening a work order on a `DECOMMISSIONED` bus is rejected with `ERR_ALREADY_TERMINAL`. The order then advances through fleet-posted events named by `event_type`: `DIAGNOSE` moves `OPEN` to `DIAGNOSING`; `ORDER_PARTS` moves `DIAGNOSING` to `WAITING_PARTS`; `START_REPAIR` moves `DIAGNOSING` to `IN_REPAIR`; `PARTS_RECEIVED` moves `WAITING_PARTS` to `IN_REPAIR`; and a further `ORDER_PARTS` from `IN_REPAIR` loops back to `WAITING_PARTS` for the parts re-order cycle. `COMPLETE` moves `IN_REPAIR` to `COMPLETED` and requires both `labor_minutes` and `parts_cost_cents` in the payload. `CANCEL` moves an order from `OPEN`, `DIAGNOSING`, `WAITING_PARTS`, or `IN_REPAIR` to terminal `CANCELLED`. Either completion or cancellation returns the bus to `IN_SERVICE` when three conditions all hold: no other work order on the bus remains in `OPEN`, `DIAGNOSING`, `WAITING_PARTS`, or `IN_REPAIR`; no inspection on the bus stands at `FAILED` or `OVERDUE`; and the bus's `next_inspection_due` is on or after the clock date. Work orders may be listed filtered by `bus_id` and `status`.

A bus retires through a fleet-posted `action` of `DECOMMISSION`, moving from `IN_SERVICE`, `IN_SHOP`, or `GROUNDED` to terminal `DECOMMISSIONED` — but only while no assignment on the bus remains in `PLANNED`, `CONFIRMED`, or `EN_ROUTE` on any service day dated on or after the clock date; a blocked decommission is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Daily Dispatch: Confirmation, Execution, Doubling, and Reconciliation

While a service day stands `DISPATCH_OPEN`, `ContractorOps` builds coverage by confirming its `PLANNED` assignments — confirming against a day in any other state is rejected with `ERR_INVALID_STATE`. Confirming moves an assignment to `CONFIRMED` and attaches the `driver_id` and `bus_id` that will run it; the two must be supplied together — a payload missing either is rejected at the schema stage with `ERR_DRIVER_REQUIRED` (HTTP 422), before any existence lookup. Confirmation runs the full safety stack. The driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), hold an active `CDL_B` (`ERR_CREDENTIAL_EXPIRED`) and an active `S_ENDORSEMENT` (`ERR_ENDORSEMENT_MISSING`), and carry `license_class` `B` (`ERR_LICENSE_CLASS_INSUFFICIENT`). The bus must be `IN_SERVICE` (`ERR_BUS_NOT_IN_SERVICE`) with its `next_inspection_due` on or after the day's `service_date` (`ERR_INSPECTION_OVERDUE`), must seat at least the route's `student_count` (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422), and must belong to the same district as the contract being served (`ERR_BUS_DISTRICT_MISMATCH`). Neither driver nor bus may already hold a conflicting commitment on the same service date: intervals are treated as half-open, so one commitment ending at exactly the minute another begins is permissible, while any true intersection is rejected with `ERR_DRIVER_OVERLAP_CONFLICT` or `ERR_BUS_OVERLAP_CONFLICT` respectively. A commitment here means an assignment in `CONFIRMED` or `EN_ROUTE` status, plus any `SCHEDULED` or `IN_PROGRESS` charter trip, which occupies its driver and bus with the ±30-minute buffered window of §3.6. Finally, the driver's projected week must fit the soft cap described below. A successful confirmation sets the assignment's driver and bus, adds the planned minutes to the driver's `weekly_assigned_minutes`, and recomputes the day's covered and uncovered counts.

The weekly-hours rule governs how much one driver may be assigned. For the ISO week — Monday through Sunday — containing the target service date, the projection sums the planned minutes (`planned_end_minute` minus `planned_start_minute`) of every assignment of that driver in `CONFIRMED`, `EN_ROUTE`, or `COMPLETED` status falling in that week, plus the candidate assignment's planned minutes. A plain confirmation requires the projection to be at most 2400 minutes — forty hours — with exactly 2400 passing. Route doubling, described below, is the only sanctioned way past the soft cap: a doubling decision may push the projection beyond 2400 but never beyond the hard cap of 2700 minutes — forty-five hours — with exactly 2700 passing and anything higher rejected with `ERR_DRIVER_HOURS_CAP_EXCEEDED` (HTTP 422). Cancellations and no-shows recompute the figure.

Execution belongs to the driver. Starting a run moves a driver's own `CONFIRMED` assignment to `EN_ROUTE`, permitted while the day stands `DISPATCH_OPEN` or `LOCKED` and only when the acting `Driver`'s identity matches the assignment's `driver_id`. Completing the run moves `EN_ROUTE` to `COMPLETED` and records the actuals: `actual_start_minute`, `actual_end_minute` — which must be strictly later than the start, else `ERR_INVALID_TIME_RANGE` — and `actual_miles`, which is added to the bus's `odometer_miles`. A completed assignment remains covered. When a confirmed driver simply does not appear, `ContractorOps` marks the assignment `NO_SHOW` with an optional `reason` — again only while the day is `DISPATCH_OPEN` or `LOCKED` — and the route drops back to uncovered as the day's counts recompute. Dispatch may also cancel outright: from `PLANNED` or `CONFIRMED`, an operator cancellation lands the assignment in terminal `CANCELLED` with `cancellation_reason` `OPS_CANCEL`, while system cascades use `BUS_GROUNDED`, `DRIVER_SUSPENDED`, `CONTRACT_TERMINATED`, or `WEATHER` as the cause dictates; either way the day's coverage recomputes.

Driver shortages meet their remedy once the day is `LOCKED`: the route-doubling decision. `ContractorOps` nominates an `uncovered_assignment_id` and an `absorbing_assignment_id`, proposing that the absorbing driver and bus run the uncovered route immediately after their own. The uncovered assignment must be `PLANNED` and belong to the nominated day — a terminal uncovered assignment yields `ERR_ALREADY_TERMINAL`, a non-`PLANNED` one `ERR_INVALID_STATE`, and one belonging to another day `ERR_DOUBLING_INFEASIBLE`. The absorbing driver and bus re-run the dispatchability stack of §2.8 stages 9–10 (an absorbing assignment without a driver or bus fails with `ERR_DOUBLING_INFEASIBLE`), the shifted window is overlap-checked against the driver's and bus's other commitments per stage 11, and the absorbing bus's home district must match the contract's district per stage 13 (`ERR_BUS_DISTRICT_MISMATCH`). The decision is feasible only when the absorbing assignment is `CONFIRMED` on the same service day; when the absorbing bus seats at least the uncovered route's `student_count`; when the absorbing assignment's `planned_end_minute` is no later than the uncovered route's `am_start_minute` plus 45 minutes, the maximum doubling delay; and when the absorbing driver's projected weekly minutes plus the uncovered run's planned minutes stay within the 2700-minute hard cap. Feasibility failures are rejected with `ERR_DOUBLING_INFEASIBLE` (HTTP 422), and a hard-cap breach with `ERR_DRIVER_HOURS_CAP_EXCEEDED`. An accepted decision confirms the uncovered assignment with the absorbing driver and bus copied over, sets `is_doubled` true, points `doubled_after_assignment_id` at the absorbing assignment, and shifts the planned window: `planned_start_minute` becomes the absorbing assignment's planned end, and `planned_end_minute` becomes that start plus the uncovered route's own duration. The driver's weekly projection and the day's coverage counts recompute accordingly.

Reconciliation closes the books on a locked day. `ContractorOps` reconciles a `LOCKED` day to `RECONCILED`, but only once no assignment on the day remains `EN_ROUTE` — an in-flight run blocks the reconcile with `ERR_ASSIGNMENTS_IN_FLIGHT` (HTTP 422). Reconcile performs final accounting: each assignment's `billable` flag is set true exactly when its status is `COMPLETED`; assignments still `PLANNED` or `CONFIRMED` at this point are treated as uncovered and bill nothing. `covered_routes` is then recomputed as the count of billable assignments — this final figure replaces the live dispatch metric — `uncovered_routes` becomes the required count minus that, and `shortage_flag` reflects whether anything is uncovered. The day's `shortage_credit_cents` is computed per the contract's `penalty_mode`: under `FLAT_PER_ROUTE`, the uncovered count multiplied by `shortage_penalty_flat_cents`; under `PER_STUDENT_MINUTE`, the sum over each uncovered assignment — one still `PLANNED`, `CONFIRMED`, or `NO_SHOW` at reconcile, with cancelled assignments contributing nothing — of its route's `student_count` multiplied by `assumed_minutes_per_missed_route` multiplied by `shortage_penalty_per_student_minute_cents`. Thereafter, when a finance clerk issues an invoice covering the day's period, the system moves the day from `RECONCILED` to `INVOICED`. Assignments support reverse reachability: the list endpoint filters by `service_day_id`, `route_id`, `driver_id`, `bus_id`, `doubled_after_assignment_id`, and `status`.

### 3.6. Charter Trips and Field-Trip Billing

Districts buy extra-curricular transport as charters. A `DistrictAdmin` requests one under an `ACTIVE` contract — a request under any other contract state fails with `ERR_CONTRACT_NOT_ACTIVE` — supplying the `contract_id`, a free-text `purpose`, a `trip_date` on or after the logical clock date (an earlier date is rejected with `ERR_CHARTER_DATE_PAST`, HTTP 422), a `pickup_minute` and a strictly later `return_minute` (else `ERR_INVALID_TIME_RANGE`), an `estimated_hours_x10` duration in tenths of an hour (55 means five and a half hours), `estimated_miles`, and an expected `passenger_count`. The trip is born `REQUESTED`.

`ContractorOps` prices a requested trip, moving it to `QUOTED` — quoting requires the contract still be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`. The provisional `quote_price_cents` is the estimated hours in tenths multiplied by the contract's `charter_hourly_rate_cents`, divided by ten and floored to whole cents, plus the `estimated_miles` multiplied by `charter_per_mile_cents`. The quote carries a deadline: `quote_valid_until` is set exactly 72 hours after the quoting instant, and quoting increments the trip's `version`. The district then decides. Approval — by the owning `DistrictAdmin` — moves `QUOTED` to `APPROVED`, records the supplied `deposit_cents`, and increments the version; it is OCC-pinned per §2.7, so the request must carry `expected_charter_trip_version` matching the trip's current version, with mismatches rejected as `ERR_STALE_VERSION`. Approval is also racing the quote's shelf life: advancing the clock strictly past `quote_valid_until` flips a `QUOTED` trip to terminal `EXPIRED`, after which approval lands on a terminal state and fails with `ERR_ALREADY_TERMINAL`; an approval arriving exactly at the deadline still succeeds, because expiry is strictly-past. Declining, with an optional `reason`, moves `QUOTED` to terminal `DECLINED`.

Scheduling turns approval into an operating commitment. `ContractorOps` schedules an `APPROVED` trip to `SCHEDULED` by supplying `assigned_bus_id` and optionally `assigned_driver_id`. The contract must still be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`). The bus must be `IN_SERVICE` (`ERR_BUS_NOT_IN_SERVICE`), with `next_inspection_due` on or after the `trip_date` (`ERR_INSPECTION_OVERDUE`), and must seat the `passenger_count` (`ERR_CAPACITY_INSUFFICIENT`). The bus's calendar is checked with a buffer: the charter occupies the closed window from thirty minutes before its pickup through thirty minutes after its return, and that buffered window must not intersect the buffered window of any other `SCHEDULED` or `IN_PROGRESS` charter on the same bus and date (`ERR_CHARTER_BUS_UNAVAILABLE`), nor intersect the planned interval — half-open, as with route work — of any `CONFIRMED` or `EN_ROUTE` route assignment on the same bus and date (`ERR_BUS_OVERLAP_CONFLICT`). If a driver is named, that driver must be `ACTIVE` with valid credentials and no `CONFIRMED` or `EN_ROUTE` assignment whose planned half-open interval intersects the charter's unbuffered pickup-to-return interval on the trip date (`ERR_DRIVER_OVERLAP_CONFLICT`). Last comes the fiscal gate of §3.7: the district's outstanding balance plus this trip's `quote_price_cents` must not exceed the district's `credit_limit_cents`, with equality allowed, else the schedule is rejected with `ERR_DISTRICT_CREDIT_HOLD` (HTTP 402). A successful schedule records the assigned bus and driver.

On the day, `ContractorOps` starts the trip — `SCHEDULED` to `IN_PROGRESS` — and later completes it with `actual_hours_x10` and `actual_miles`, moving it to `COMPLETED`. Completion prices the trip for real. The final `final_price_cents` is the actual hours in tenths multiplied by the hourly rate, divided by ten and floored to whole cents, plus the actual miles multiplied by the per-mile rate, plus an overage charge on any hours beyond the estimate: the excess in tenths of an hour multiplied by the hourly rate and by 125, divided by one thousand, floored to whole cents — that is, excess hours bill at one-and-a-quarter times the hourly rate. The bus's `odometer_miles` advances by the actual miles. When an invoice covering the trip's month is later issued, the system moves the trip from `COMPLETED` to `INVOICED`.

Either the district or the contractor may cancel a trip still in `REQUESTED`, `QUOTED`, `APPROVED`, or `SCHEDULED`, optionally giving a `reason`. Cancellation computes a tiered `cancel_fee_cents` from the whole hours between the cancellation instant and the scheduled pickup: 72 hours or more means no fee; at least 24 but fewer than 72 hours means twenty-five percent of `quote_price_cents`, rounded half-up; fewer than 24 hours means fifty percent, rounded half-up. Boundaries are inclusive downward: exactly 72 hours is free, exactly 24 hours falls in the twenty-five-percent tier. The `refund_cents` returned to the district is the `deposit_cents` minus the fee, so fee plus refund always equals the deposit; trips cancelled from `REQUESTED` or `QUOTED` hold no deposit, so both fee and refund are zero there. Charter trips may be listed filtered by `contract_id`, `assigned_bus_id`, `assigned_driver_id`, and `status`.

### 3.7. Invoicing, Fuel Escalation, and District Credit

Billing runs on a monthly period, keyed `YYYY-MM`. The fuel side of the ledger needs data first: a `FinanceClerk` records each month's index price as a FuelPriceEntry carrying the `district_id`, the `effective_month` — unique per district, so a second entry for the same district and month is rejected with `ERR_FUEL_ENTRY_DUPLICATE_MONTH` — the `avg_price_cents_per_gallon`, and a `source` reference such as an EIA PADD designation. Entries are append-only and may be listed filtered by `district_id` and `effective_month`.

Invoice generation opens a `DRAFT` invoice for a `contract_id` and `period_month`. Two gates apply up front: a fuel price entry must exist for the contract's district and the billed period (else `ERR_FUEL_ENTRY_MISSING`, HTTP 422), and the period must contain at least one `RECONCILED` service day — something final to bill — else generation fails with `ERR_INVOICE_PERIOD_INCOMPLETE` (HTTP 422). The draft computes the PROVISIONAL variant. Its `bus_lines_cents` sums one line per qualifying service day: for days in `RECONCILED` or `INVOICED`, the count of assignments with `billable` true multiplied by the contract's `daily_rate_per_bus_cents`; for days still `LOCKED`, the planned `required_routes` multiplied by the daily rate — optimistic billing at planned coverage. `CANCELLED` days never enter either variant. `charter_lines_cents` sums the `final_price_cents` of the contract's `COMPLETED` charters whose `trip_date` falls in the period. `shortage_credit_cents` sums the `shortage_credit_cents` of the period's `RECONCILED` days. The provisional total is recorded as `provisional_total_cents` and, while the invoice stands `DRAFT`, the authoritative `total_cents` equals it; `final_total_cents` stays null until issue. No per-period uniqueness applies: any number of invoices for the same contract and period may coexist. Invoices may be listed filtered by `contract_id`, `status`, and `period_month`.

The fuel escalation clause adjusts the invoice for diesel-price drift. Let the contract's `fuel_base_price_cents` be the base and the district's monthly entry price be the average. The trigger comparison is integer-exact: if one hundred times the average is less than the base multiplied by (one hundred plus `fuel_escalation_trigger_pct`), the adjustment is zero for every day; an average of exactly the base increased by the trigger percentage does trigger. When triggered, the excess over base splits into two tiers: tier one is the excess capped at the whole-cent floor of ten percent of the base, and tier two is whatever remains. Each tier earns its own per-gallon rate — tier one's excess times `fuel_escalation_share_pct` hundredths, rounded half-up to a whole cent; tier two's excess times a share of one-and-a-half times `fuel_escalation_share_pct` capped at one hundred percent, hundredths, rounded half-up — and the per-gallon adjustment is their sum. Fuel consumed per service day is reckoned in thousandths of a gallon: for every `COMPLETED` assignment on the day, and every `COMPLETED` charter whose `trip_date` equals the day's date, the `actual_miles` times ten thousand divided by the bus's `mpg_x10`, floored to a whole number. The day's fuel adjustment is those thousandths of a gallon times the per-gallon adjustment, divided by one thousand, rounded half-up to whole cents — and the rounding order is pinned: each day is rounded individually, then the rounded day amounts are summed. Summing all gallons first and rounding once is forbidden, because the two orders produce different cents. The raw fuel adjustment is the sum of day adjustments over the variant's input set, computed identically at generate and at issue — the fuel input set is the period's `RECONCILED` service days in both variants.

The invoice total applies a pinned evaluation order because the monthly cap makes the fuel adjustment depend on a total that itself includes fuel. First `bus_lines_cents`, then `charter_lines_cents`, then `shortage_credit_cents` is subtracted, yielding a preliminary total. The raw fuel adjustment is computed next. If the preliminary total plus the raw adjustment would exceed `monthly_cap_cents`, the recorded `fuel_adjustment_cents` is truncated to the larger of zero and the cap minus the preliminary total; otherwise it is the raw adjustment. The invoice total is the preliminary total plus the recorded fuel adjustment, and if that total still exceeds `monthly_cap_cents` — possible only when the preliminary total alone already exceeds the cap, with fuel truncated to zero — the total is clamped to the cap itself.

Issuing is the point of finality. A `FinanceClerk` issues a `DRAFT` invoice, moving it to `ISSUED`; the FINAL variant is recomputed from scratch — only `RECONCILED` days bill, at their `billable` assignment counts, with `LOCKED` days contributing nothing and shortage credit drawn from `RECONCILED` days only — and recorded as `final_total_cents`, which becomes the authoritative `total_cents`. The `issued_on` date is taken from the logical clock, every `RECONCILED` service day in the period cascades to `INVOICED`, every `COMPLETED` charter in the period cascades to `INVOICED`, and the district's outstanding balance is recomputed.

An issued invoice lives under the district's scrutiny. The owning `DistrictAdmin` may dispute it — moving `ISSUED` to `DISPUTED` with a required `reason` — provided the clock date is no later than `issued_on` plus the district's `billing_dispute_window_days`; that last day is still inside the window, and any later attempt is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. Each dispute increments `dispute_count` and records the reason in `dispute_reason`. Resolution loops back: the `FinanceClerk` reissues a `DISPUTED` invoice to `ISSUED` with an `adjustment_delta_cents` — which may be negative — and a `reason`, both of which are required fields; the delta is added to both `total_cents` and `final_total_cents`, `issued_on` refreshes to the clock date, and the district's balance recomputes. Payment moves `ISSUED` to terminal `PAID`, stamps `paid_on` from the clock, and recomputes the balance. A hopeless invoice in `ISSUED` or `DISPUTED` may be written off to terminal `WRITTEN_OFF` with an optional `reason`, likewise recomputing the balance.

The district's `outstanding_balance_cents` is the sum of `total_cents` over all its `ISSUED` invoices across every contract — unpaid and not written off — and it is recomputed at issue, reissue, payment, and write-off. This figure is the input to the charter credit gate of §3.6: at schedule time, the outstanding balance plus the trip's `quote_price_cents` must not exceed the district's `credit_limit_cents`; equality passes, and exceeding it is `ERR_DISTRICT_CREDIT_HOLD`.

### 3.8. Incidents, Ridership, and District Reporting

Safety and conduct reporting flows through Incidents. A `Driver` or `ContractorOps` creates one in `DRAFT`, addressing it to a `district_id`, with a `category` of `ACCIDENT`, `BEHAVIOR`, `MECHANICAL`, or `MEDICAL`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a narrative `description`, and an `occurred_at` instant that must not lie in the future relative to the logical clock (else `ERR_FUTURE_INCIDENT`, HTTP 422). Optional context attaches a `route_id`, an involved `driver_id`, a `service_day_id`, and a `student_discipline_flag` defaulting to false; any route or service day referenced must belong to the incident's own district, else `ERR_CROSS_DISTRICT_REFERENCE` (HTTP 422). Incidents may be listed filtered by `district_id`, `route_id`, `driver_id`, `service_day_id`, `status`, and `severity`.

Submission starts the district's clock. Submitting from `DRAFT` — or resubmitting from `RETURNED_FOR_INFO`, the cyclic loop — moves the incident to `SUBMITTED`, stamps `submitted_at` from the logical clock, and sets the SLA deadline `district_due_by` from severity: 24 hours for `CRITICAL`, 72 hours for `HIGH`, and 168 hours for anything else; resubmission recomputes both timestamps afresh. When the discipline flag is true, submission additionally requires both `route_id` and `service_day_id` to be present, else `ERR_DISCIPLINE_CONTEXT_REQUIRED` (HTTP 422). The owning `DistrictAdmin` then either acknowledges the incident — moving it to `ACKNOWLEDGED` and stamping `acknowledged_at` — or returns it for more information, `SUBMITTED` to `RETURNED_FOR_INFO`, with an optional `reason`. Acknowledgement evaluates the SLA: `sla_breached` is true exactly when `acknowledged_at` is strictly later than `district_due_by`; an acknowledgement landing exactly at the deadline is not a breach. An acknowledged incident is closed — by either the district or `ContractorOps`, with an optional `resolution_note` — landing in terminal `CLOSED`.

Ridership telemetry arrives one report per assignment. A `Driver` or `ContractorOps` submits a RidershipReport for a `COMPLETED` assignment — any other assignment status is rejected with `ERR_INVALID_STATE` — carrying the `assignment_id`, the denormalized `service_day_id` (existence-checked only; it is not cross-checked against the assignment's own service day), the `boardings` and `alightings` counts, and the GPS-derived `first_pickup_actual_minute` and `last_dropoff_actual_minute`; a second report for the same assignment is rejected with `ERR_DUPLICATE_RIDERSHIP_REPORT`. The system derives the punctuality measures: `minutes_late` is the larger of zero and the first pickup minute minus the assignment's `planned_start_minute` minus a five-minute grace; `on_time` is true exactly when `minutes_late` is zero; and `student_minutes_late` multiplies `minutes_late` by the `boardings`. Reports may be listed filtered by `assignment_id` and `service_day_id`.

Districts consume all of this through a computed daily report on any service day. The report returns the `service_day_id`, the day's `required_routes`, `covered_routes`, and `uncovered_routes`, the `total_boardings` across reports, the `total_student_minutes_late`, the count `sla_breached_incidents` of that day's incidents whose acknowledgement breached the SLA, and the day's `shortage_credit_cents`. On-time performance aggregates over the day's `COMPLETED` assignments that have a ridership report: `on_time_pct_x100` is the count of on-time reports times ten thousand, divided by the number of reports, floored to an integer — the percentage times one hundred — and is null when no reports exist. The `on_time_tier` grades the result: at least 9500 is `EXCELLENT`, at least 9000 is `SATISFACTORY`, and anything below is `DEFICIENT`, with both thresholds inclusive — and is likewise null when no reports exist.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, event postings, confirmations, pricing actions — return `200 OK`. All endpoints sit under the `/busops` mount. Request bodies, preconditions, and side effects for each operation are specified in §3; this table is the routing and authorization index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/busops/_clock/set_current_utc` | Advance the logical clock; fires time-based transitions | SystemAdmin |
| POST | `/busops/districts` | Create a district | SystemAdmin |
| GET | `/busops/districts` | List districts | SystemAdmin, DistrictAdmin, ContractorOps, HRRecruiter, FleetManager, FinanceClerk, Driver |
| GET | `/busops/districts/{id}` | Get a district | SystemAdmin, DistrictAdmin, ContractorOps, HRRecruiter, FleetManager, FinanceClerk, Driver |
| POST | `/busops/contracts` | Create a bid contract in `DRAFT_BID` | ContractorOps |
| GET | `/busops/contracts` | List contracts, filterable by district and status | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk |
| GET | `/busops/contracts/{id}` | Get a contract | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk |
| POST | `/busops/contracts/{id}/submit` | Submit a draft bid | ContractorOps |
| POST | `/busops/contracts/{id}/award` | Award a submitted contract | DistrictAdmin |
| POST | `/busops/contracts/{id}/mark-lost` | Mark a submitted contract lost | DistrictAdmin |
| POST | `/busops/contracts/{id}/withdraw` | Withdraw a submitted bid | ContractorOps |
| POST | `/busops/contracts/{id}/activate` | Activate an awarded contract | ContractorOps |
| POST | `/busops/contracts/{id}/terminate` | Terminate an active contract with full cascade | DistrictAdmin |
| POST | `/busops/contracts/{id}/amendments` | Apply a pricing amendment (OCC-guarded) | DistrictAdmin |
| POST | `/busops/routes` | Create a route under an active contract | ContractorOps |
| GET | `/busops/routes` | List routes, filterable | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| GET | `/busops/routes/{id}` | Get a route | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| POST | `/busops/routes/{id}/deactivate` | Suspend a route, or archive when `archive` is true | ContractorOps |
| POST | `/busops/routes/{id}/reactivate` | Reactivate a suspended route | ContractorOps |
| POST | `/busops/drivers` | Create a driver applicant | HRRecruiter |
| GET | `/busops/drivers` | List drivers, filterable | SystemAdmin, DistrictAdmin, ContractorOps, HRRecruiter, FleetManager, FinanceClerk |
| GET | `/busops/drivers/{id}` | Get a driver (Driver role reads own record only) | SystemAdmin, DistrictAdmin, ContractorOps, HRRecruiter, FinanceClerk, Driver |
| POST | `/busops/drivers/{id}/events` | Post a pipeline event (`SCREEN`, `ENROLL`, `SCHEDULE_TEST`, `TEST_PASS`, `TEST_FAIL`, `ACTIVATE`, `TERMINATE`) | HRRecruiter |
| POST | `/busops/drivers/{id}/discipline` | Suspend or reinstate a driver | ContractorOps |
| POST | `/busops/training-events` | Log a training event | HRRecruiter |
| GET | `/busops/training-events` | List training events, filterable | SystemAdmin, ContractorOps, HRRecruiter |
| GET | `/busops/training-events/{id}` | Get a training event | SystemAdmin, ContractorOps, HRRecruiter |
| POST | `/busops/credentials` | Record a state-issued credential | HRRecruiter |
| GET | `/busops/credentials` | List credentials, filterable | SystemAdmin, ContractorOps, HRRecruiter |
| GET | `/busops/credentials/{id}` | Get a credential | SystemAdmin, ContractorOps, HRRecruiter |
| POST | `/busops/credentials/{id}/revoke` | Revoke an active credential | HRRecruiter |
| POST | `/busops/buses` | Register a bus | FleetManager |
| GET | `/busops/buses` | List buses, filterable | SystemAdmin, DistrictAdmin, ContractorOps, FleetManager |
| GET | `/busops/buses/{id}` | Get a bus | SystemAdmin, DistrictAdmin, ContractorOps, FleetManager |
| POST | `/busops/buses/{id}/events` | Post a bus event (`DECOMMISSION`) | FleetManager |
| POST | `/busops/inspections` | Schedule a state inspection | FleetManager |
| GET | `/busops/inspections` | List inspections, filterable | SystemAdmin, ContractorOps, FleetManager |
| GET | `/busops/inspections/{id}` | Get an inspection | SystemAdmin, ContractorOps, FleetManager |
| POST | `/busops/inspections/{id}/record-result` | Record a PASS/FAIL result | FleetManager |
| POST | `/busops/inspections/{id}/reschedule` | Reschedule a failed inspection | FleetManager |
| POST | `/busops/inspections/{id}/cancel` | Cancel a scheduled inspection | FleetManager |
| POST | `/busops/work-orders` | Open a work order; bus goes to shop | FleetManager |
| GET | `/busops/work-orders` | List work orders, filterable | SystemAdmin, ContractorOps, FleetManager |
| GET | `/busops/work-orders/{id}` | Get a work order | SystemAdmin, ContractorOps, FleetManager |
| POST | `/busops/work-orders/{id}/events` | Post a work-order event (`DIAGNOSE`, `ORDER_PARTS`, `START_REPAIR`, `PARTS_RECEIVED`, `COMPLETE`, `CANCEL`) | FleetManager |
| POST | `/busops/service-days` | Create a service day; auto-creates planned assignments | ContractorOps |
| GET | `/busops/service-days` | List service days, filterable | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| GET | `/busops/service-days/{id}` | Get a service day | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| POST | `/busops/service-days/{id}/open-dispatch` | Open dispatch on a scheduled day | ContractorOps |
| POST | `/busops/service-days/{id}/lock` | Lock a dispatch-open day (OCC-guarded) | ContractorOps |
| POST | `/busops/service-days/{id}/reconcile` | Reconcile a locked day; computes billable flags and shortage credit | ContractorOps |
| POST | `/busops/service-days/{id}/cancel` | Cancel a day for weather or district closure | ContractorOps |
| POST | `/busops/service-days/{id}/doubling-decisions` | Cover an uncovered assignment by route doubling | ContractorOps |
| GET | `/busops/service-days/{id}/district-report` | Computed district-facing daily report | SystemAdmin, DistrictAdmin, ContractorOps |
| GET | `/busops/assignments` | List assignments, filterable (reverse reachability) | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| GET | `/busops/assignments/{id}` | Get an assignment | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| POST | `/busops/assignments/{id}/confirm` | Confirm a planned assignment with driver and bus | ContractorOps |
| POST | `/busops/assignments/{id}/start` | Start a confirmed run (driver self-service) | Driver |
| POST | `/busops/assignments/{id}/complete` | Complete a run with actuals (driver self-service) | Driver |
| POST | `/busops/assignments/{id}/no-show` | Mark a confirmed assignment as no-show | ContractorOps |
| POST | `/busops/assignments/{id}/cancel` | Cancel a planned or confirmed assignment | ContractorOps |
| POST | `/busops/charter-trips` | Request a charter trip | DistrictAdmin |
| GET | `/busops/charter-trips` | List charter trips, filterable | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| GET | `/busops/charter-trips/{id}` | Get a charter trip | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk, Driver |
| POST | `/busops/charter-trips/{id}/quote` | Price a requested trip; sets 72-hour quote validity | ContractorOps |
| POST | `/busops/charter-trips/{id}/approve` | Approve a quoted trip (OCC version-pinning) | DistrictAdmin |
| POST | `/busops/charter-trips/{id}/decline` | Decline a quoted trip | DistrictAdmin |
| POST | `/busops/charter-trips/{id}/schedule` | Schedule an approved trip with bus and optional driver | ContractorOps |
| POST | `/busops/charter-trips/{id}/start` | Start a scheduled trip | ContractorOps |
| POST | `/busops/charter-trips/{id}/complete` | Complete a trip; computes final price with overage | ContractorOps |
| POST | `/busops/charter-trips/{id}/cancel` | Cancel a trip with tiered fee and deposit refund | DistrictAdmin, ContractorOps |
| POST | `/busops/fuel-price-entries` | Record a district's monthly fuel index price | FinanceClerk |
| GET | `/busops/fuel-price-entries` | List fuel price entries, filterable | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk |
| GET | `/busops/fuel-price-entries/{id}` | Get a fuel price entry | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk |
| POST | `/busops/invoices/generate` | Generate a provisional draft invoice for a contract and period | FinanceClerk |
| GET | `/busops/invoices` | List invoices, filterable | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk |
| GET | `/busops/invoices/{id}` | Get an invoice | SystemAdmin, DistrictAdmin, ContractorOps, FinanceClerk |
| POST | `/busops/invoices/{id}/issue` | Issue a draft invoice; recomputes final totals and cascades | FinanceClerk |
| POST | `/busops/invoices/{id}/dispute` | Dispute an issued invoice within the dispute window | DistrictAdmin |
| POST | `/busops/invoices/{id}/reissue` | Reissue a disputed invoice with an adjustment delta | FinanceClerk |
| POST | `/busops/invoices/{id}/pay` | Mark an issued invoice paid | FinanceClerk |
| POST | `/busops/invoices/{id}/write-off` | Write off an issued or disputed invoice | FinanceClerk |
| POST | `/busops/incidents` | Create an incident report in draft | Driver, ContractorOps |
| GET | `/busops/incidents` | List incidents, filterable | SystemAdmin, DistrictAdmin, ContractorOps, HRRecruiter, Driver |
| GET | `/busops/incidents/{id}` | Get an incident | SystemAdmin, DistrictAdmin, ContractorOps, HRRecruiter, Driver |
| POST | `/busops/incidents/{id}/submit` | Submit or resubmit an incident; sets SLA deadline | Driver, ContractorOps |
| POST | `/busops/incidents/{id}/acknowledge` | Acknowledge a submitted incident; evaluates SLA breach | DistrictAdmin |
| POST | `/busops/incidents/{id}/return` | Return a submitted incident for more information | DistrictAdmin |
| POST | `/busops/incidents/{id}/close` | Close an acknowledged incident | DistrictAdmin, ContractorOps |
| POST | `/busops/ridership-reports` | Submit GPS/ridership data for a completed assignment | Driver, ContractorOps |
| GET | `/busops/ridership-reports` | List ridership reports, filterable | SystemAdmin, DistrictAdmin, ContractorOps, Driver |
| GET | `/busops/ridership-reports/{id}` | Get a ridership report | SystemAdmin, DistrictAdmin, ContractorOps, Driver |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_CONTRACT_NOT_YET_STARTED` | 409 |
| `ERR_DRIVER_NOT_ACTIVE` | 409 |
| `ERR_CREDENTIAL_EXPIRED` | 409 |
| `ERR_ENDORSEMENT_MISSING` | 409 |
| `ERR_LICENSE_CLASS_INSUFFICIENT` | 409 |
| `ERR_TRAINING_HOURS_INSUFFICIENT` | 422 |
| `ERR_BUS_NOT_IN_SERVICE` | 409 |
| `ERR_INSPECTION_OVERDUE` | 409 |
| `ERR_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_DRIVER_OVERLAP_CONFLICT` | 409 |
| `ERR_BUS_OVERLAP_CONFLICT` | 409 |
| `ERR_CHARTER_BUS_UNAVAILABLE` | 409 |
| `ERR_INSPECTION_DAY_CONFLICT` | 409 |
| `ERR_DRIVER_HOURS_CAP_EXCEEDED` | 422 |
| `ERR_DOUBLING_INFEASIBLE` | 422 |
| `ERR_CHARTER_DATE_PAST` | 422 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 |
| `ERR_OUTSIDE_CONTRACT_TERM` | 422 |
| `ERR_FUTURE_INCIDENT` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_DUPLICATE_ROUTE_CODE` | 409 |
| `ERR_FUEL_ENTRY_DUPLICATE_MONTH` | 409 |
| `ERR_FUEL_ENTRY_MISSING` | 422 |
| `ERR_SERVICE_DAY_DATE_CONFLICT` | 409 |
| `ERR_DUPLICATE_RIDERSHIP_REPORT` | 409 |
| `ERR_DISCIPLINE_CONTEXT_REQUIRED` | 422 |
| `ERR_CROSS_DISTRICT_REFERENCE` | 422 |
| `ERR_BUS_DISTRICT_MISMATCH` | 409 |
| `ERR_DRIVER_REQUIRED` | 422 |
| `ERR_ASSIGNMENTS_IN_FLIGHT` | 422 |
| `ERR_DISTRICT_CREDIT_HOLD` | 402 |
| `ERR_INVOICE_PERIOD_INCOMPLETE` | 422 |
