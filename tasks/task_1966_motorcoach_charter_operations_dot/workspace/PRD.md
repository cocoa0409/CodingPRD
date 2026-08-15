# Motorcoach Charter Operations API — Product Requirements Document

## 1. Introduction

Group transportation by charter motorcoach runs on three calendars at once: the customer's itinerary, the driver's legal hours of service, and the fleet's inspection and maintenance schedule. A charter operator must quote trips priced by mileage and hours, plan overnight lodging and relief drivers for long runs, assign only coaches whose DOT inspection and insurance will remain valid through the trip date, collect deposits scaled to booking lead time, and settle final invoices that account for extra hours, fuel surcharges, and mid-trip disruptions. Wrapped around that commercial core sit the compliance obligations — driver hours-of-service logging, incident reporting, safety scoring, customer-requested audits, and venue insurance certificates — that determine whether the operation may legally run at all.

This document specifies the Motorcoach Charter Operations API, the system of record for that entire lifecycle, from first quote to final invoice. All endpoints are mounted under the `/api/v1` prefix. The API deliberately segregates duties across seven roles — quoting, dispatch, fleet maintenance, safety, compliance, and the customer each hold distinct powers — and applies optimistic concurrency on the two write operations where acting on a stale read is most dangerous. Section 2 defines the system-wide contracts every endpoint obeys; Section 3 walks the business workflows in narrative form; Sections 4 and 5 catalogue the endpoints and error identifiers.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. Domain behavior lives in Section 3; this section governs how every request is framed, validated, and answered.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role name the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles, spelled exactly as the `X-User-Role` header must present them, are:

- `PlatformAdmin` — system administrator with broad read access and exclusive control of the logical clock.
- `QuoteAgent` — creates and prices charter quotes and maintains customer accounts.
- `DispatchManager` — assigns vehicles and drivers, starts and completes trips, and runs breakdown response.
- `FleetManager` — manages the vehicle fleet, the driver roster, and the maintenance program.
- `SafetyOfficer` — manages driver suspensions and reinstatements, incident resolution, and safety audits.
- `ComplianceOfficer` — issues and revokes insurance certificates.
- `Customer` — the charter customer, who views their own resources, accepts quotes, pays deposits, and requests changes.

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is any of `PlatformAdmin`, `QuoteAgent`, `DispatchManager`, `FleetManager`, `SafetyOfficer`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit`, the maximum number of items returned, and `offset`, the number of items skipped. `limit` defaults to 10 when omitted, accepts a minimum of 1, and is capped at 100. `offset` defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — customer accounts, vehicles, drivers, charter quotes, charter orders, breakdown events, insurance certificates, and safety audit requests — carries four system-managed fields:

- `id`: a server-minted UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version`: an integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects and lazy reconciliations.

Sub-records — trip logs, incident reports, and maintenance records — carry only `id` and `created_at`. Both `updated_at` and `version` are absent from those three resource types.

### 2.5. Money, Rates, and Rounding Precision

All monetary amounts are integer cents, carried in fields whose names end in `_cents`; no fractional cents ever persist. Every monetary computation rounds half-up to integer cents at each intermediate step of the calculation, not merely at the final total — a quoted subtotal, a tax figure, a deposit, a surcharge, and a refund are each rounded as they are produced. Durations and scores are decimal quantities kept to one decimal place: estimated and actual trip hours, the driver hours-of-service accumulators, the driver safety score, and the customer composite audit score.

### 2.6. The Logical Clock and Lazy State Reconciliation

The server keeps a logical clock rather than trusting wall time. At startup, before any clock-set call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z. A `PlatformAdmin` may move the clock through an admin-only capability that accepts a `to_iso8601` timestamp and sets the logical clock to that instant. Every time-dependent rule in this document — quote expiry, rest completion, maintenance overdue, certificate expiry, deposit and cancellation lead-time tiers — evaluates against this logical clock.

Several state transitions fire lazily, reconciled when the resource is next read or when an explicit check is invoked, rather than by a background sweeper:

- A quote still in `QUOTED` once the logical clock reaches its `quote_expiry` transitions to `EXPIRED` when the quote is read; a `QuoteAgent` or `DispatchManager` may also force the check through the quote expiry-check capability.
- A driver in `OFF_DUTY` whose rest has reached ten consecutive hours transitions to `AVAILABLE` when the driver record is read; a `FleetManager` or `DispatchManager` may force the check through the driver rest-check capability.
- A maintenance record still `SCHEDULED` once its `scheduled_date` has passed transitions to `OVERDUE` when the record is read.
- An issued insurance certificate whose `expires_at` has passed transitions to `EXPIRED` when the certificate is read.

Each lazy reconciliation that changes state is a mutation like any other: it refreshes `updated_at` and increments `version` on the affected resource.

### 2.7. Optimistic Concurrency Control

Two write operations require the caller to present the resource version it last observed, so that a decision is never committed against a stale read:

- Quote acceptance requires the request body to carry `expected_quote_version`, equal to the quote's `version` as the customer last read it. If the quote's current `version` has advanced since that read — because the quote was repriced or otherwise mutated in the meantime — acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412), and no order is created.
- Order assignment requires the request body to carry `expected_order_version`, equal to the order's `version` as the dispatch manager last read it. A mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and no assignment is written.

No other endpoint accepts a version field; every other write proceeds without an optimistic-concurrency token.

### 2.8. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline. Earlier failures mask later ones: a request that fails step one is never examined by step two, and so on down the line.

1. Authentication: the `X-User-Role` and `X-User-ID` headers are present and the role is recognized, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. Authorization: the role is permitted on the endpoint per Section 4, else `ERR_UNAUTHORIZED` (HTTP 403).
3. Existence: every identifier in the request path resolves to an existing resource, validated left to right, else `ERR_NOT_FOUND` (HTTP 404).
4. State validity: the target entity is in a state from which the requested transition exists per Section 3, else `ERR_INVALID_STATE` (HTTP 409).
5. Domain rules, in their declared priority. For order assignment this battery runs in exactly this order: hours-of-service feasibility first (rejected with `ERR_HOS_VIOLATION`, with the more specific `ERR_HOS_DRIVING_LIMIT`, `ERR_HOS_ON_DUTY_WINDOW`, or `ERR_HOS_CYCLE_LIMIT` identifying the limit breached), then DOT inspection currency (`ERR_INSPECTION_EXPIRED`), then insurance currency (`ERR_INSURANCE_EXPIRED`), then driver safety score (`ERR_DRIVER_SAFETY_SCORE_LOW`), then seating capacity (`ERR_CAPACITY_EXCEEDED`), then ADA equipment (`ERR_ADA_REQUIRED`), then maintenance-due status (`ERR_MAINTENANCE_DUE`), and finally CDL class and endorsement (`ERR_CDL_INSUFFICIENT`). The remaining domain guards attach to their own operations: quote expiry (`ERR_QUOTE_EXPIRED`) on quote acceptance, the trip-start window (`ERR_TRIP_NOT_YET`) on trip start, deposit sufficiency (`ERR_INSUFFICIENT_DEPOSIT`) on deposit payment, and credit standing (`ERR_CREDIT_SUSPENDED`) on both quote pricing and quote acceptance.
6. Request-body type and format validation — required fields present, enum values valid, numeric ranges valid — else `ERR_INVALID_REQUEST` (HTTP 400).
7. Optimistic-concurrency staleness on the two guarded operations of §2.7, else `ERR_STALE_VERSION` (HTTP 412).
8. Replacement-vehicle eligibility on breakdown dispatch, else `ERR_REPLACEMENT_INELIGIBLE` (HTTP 422).
9. Reinstatement eligibility on driver reinstatement, else `ERR_REINSTATEMENT_DENIED` (HTTP 422).

### 2.9. Nested Resource Retrieval

Paths that nest a child collection under a parent — an order's trip logs, a vehicle's maintenance records, a customer's quotes — validate identifiers in strict left-to-right order: the parent identifier first, then any child identifier. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, and later identifiers are not examined. Creation beneath a parent likewise requires the parent's existence to be confirmed before any child-level validation runs.

### 2.10. Cascading Mutations and Version Semantics

Many operations in this domain mutate more than one resource as a single atomic effect: assigning an order re-marks its vehicle and its drivers; completing a trip settles the invoice, advances the odometer, rests the crew, and rolls up customer aggregates. Every such cascade is all-or-nothing, and every resource touched by the cascade — not merely the one named in the request path — refreshes its `updated_at` and increments its `version`. Derived recomputations on a customer account, such as `lifetime_revenue_cents` or `safety_audit_score`, are mutations of the account and follow the same rule. System-initiated transitions (lazy expiries, rest completions, odometer-triggered maintenance scheduling) obey it as well.

## 3. Business Logic & Workflows

This section tells the story of a charter from first inquiry to final settlement, then turns to the fleet, safety, and compliance machinery that surrounds it. State names appear as exact uppercase strings; transition pairs such as `DRAFT` → `QUOTED` bridge each narrative back to the endpoint table in Section 4.

### 3.1. Customer Accounts and Credit Standing

A `QuoteAgent` or `PlatformAdmin` registers a customer account with the organization's `company_name`, a `contact_email`, a `contact_phone`, and a `billing_address` for invoicing; `tax_exempt` may be declared at registration and defaults to false. New accounts open with `credit_status` set to `ACTIVE`; over time the standing may move to `SUSPENDED` or `COLLECTIONS`. The same two roles may later update any of those input fields on the account, and every such update increments the account's `version`. The customer list may be filtered by `credit_status`.

Three computed figures summarize each relationship. `total_completed_trips` counts the customer's orders that have reached `COMPLETED`, starting at zero. `lifetime_revenue_cents` accumulates the money the relationship has produced — it grows by the deposit amount received when a deposit is paid, and again by the `final_invoice_cents` when a trip completes — starting from zero. `safety_audit_score` is a composite rating between 0.0 and 100.0 built from the customer's completed orders, their incidents, and their breakdowns, as detailed in §3.9. Credit standing gates commerce: a customer in `COLLECTIONS` cannot price a draft quote and cannot accept a priced one — both attempts are rejected with `ERR_CREDIT_SUSPENDED` — while `ACTIVE` and `SUSPENDED` customers transact normally.

### 3.2. Fleet Roster and Driver Qualifications

A `FleetManager` or `PlatformAdmin` registers each coach with a fleet-unique `unit_number` (such as "MC-101"), its `make_model` and `year`, the `seating_capacity`, the `dot_inspection_expiry` of its next required annual DOT inspection, the `maintenance_due_miles` odometer threshold at which preventive service comes due, and the coach's `insurance_policy_number` and `insurance_expiry`. Two equipment facts ride along: `ada_accessible`, recording a lift-equipped coach and defaulting to false, and `vehicle_class` — `STANDARD`, `PREMIUM`, or `EXECUTIVE` — defaulting to `STANDARD` and driving the rate tables of §3.3. The coach's `odometer_miles` begins at zero and advances only when trips complete; `last_inspection_date` is written by the maintenance program, not by hand. A vehicle's `status` walks `AVAILABLE` → `ASSIGNED` → `IN_TRIP` and back to `AVAILABLE`, with `IN_MAINTENANCE` and the terminal `OUT_OF_SERVICE` alongside; the fleet list filters by `status` and `vehicle_class`. From `AVAILABLE`, a fleet manager may send a coach to maintenance, moving it to `IN_MAINTENANCE`, and may decommission a coach — the request carries a `reason` — from either `AVAILABLE` or `IN_MAINTENANCE` into `OUT_OF_SERVICE`, from which there is no return.

Drivers join the roster through a `FleetManager` or `PlatformAdmin` with a `full_name`, a fleet-unique `cdl_number`, a `cdl_class` of `CLASS_A`, `CLASS_B`, or `CLASS_C`, an `endorsements` array (for example ["P", "S"]), the `hire_date`, and an optional `hos_cycle_type` — `CYCLE_70_8`, the default, permitting seventy on-duty hours in eight days, or `CYCLE_60_7`, permitting sixty in seven. Each driver carries live hours-of-service accumulators: `current_driving_hours_today` for driving time in the current day, `current_on_duty_hours_today` for all on-duty time inside the current fourteen-hour window, `current_cycle_hours` for on-duty time inside the cycle window, `consecutive_driving_minutes` of unbroken driving since the last thirty-minute break, and `last_rest_start`, marking when the current or most recent off-duty period began. A driver's `safety_score` opens at 100.0 and degrades per §3.9. Driver `status` walks `AVAILABLE` → `ON_DUTY_NOT_DRIVING` → `ON_TRIP` → `OFF_DUTY` and back to `AVAILABLE`, with `SUSPENDED` standing off to the side; the driver list filters by `status`.

Rest is what returns a driver to service. Once a driver has been `OFF_DUTY` for at least ten consecutive hours — the logical clock has reached `last_rest_start` plus ten hours — the driver becomes `AVAILABLE` again, and the daily counters `current_driving_hours_today` and `current_on_duty_hours_today` reset to zero along with `consecutive_driving_minutes`. The transition is lazy: it reconciles on driver reads, or on demand when a fleet or dispatch manager invokes the driver's rest-check capability.

Discipline runs through the `SafetyOfficer`. Suspension requires a non-empty `reason`. From `AVAILABLE` it always succeeds; from `ON_DUTY_NOT_DRIVING` it succeeds only when no order in `ASSIGNED` or `IN_PROGRESS` names the driver as its primary driver — otherwise the request is refused with `ERR_INVALID_STATE`. Reinstatement returns a `SUSPENDED` driver to `AVAILABLE` only when the driver's `safety_score` is at least 30.0; below that floor the request is rejected with `ERR_REINSTATEMENT_DENIED`. Each driver's history is reachable directly: the orders on which they served as primary or relief driver, their trip-log segments, the incident reports naming them, and the breakdowns they reported.

### 3.3. Quoting and the Dual-Variant Pricing Engine

A `QuoteAgent` opens a quote by naming the `customer_id` and the trip facts: `trip_date` and `return_date`, `origin` and `destination`, `passenger_count`, `estimated_miles`, and `estimated_hours`. Equipment requirements ride on the same payload — `ada_required`, defaulting to false, and `vehicle_class_requested`, defaulting to `STANDARD` — along with free-text `special_requests`, empty by default. The quote is born in `DRAFT`. Quote lists filter by `status` and `customer_id`, and each customer's quotes are listed from the account as well.

Pricing a draft — the quote-agent act that moves `DRAFT` → `QUOTED` — first demands that `estimated_miles`, `estimated_hours`, and `passenger_count` all be positive, and that the customer not stand in `COLLECTIONS` (`ERR_CREDIT_SUSPENDED`). Pricing then chooses between two variants. When `estimated_miles` divided by `estimated_hours` is at least 55.0 — a highway-dominated trip averaging fifty-five miles per hour or better — the quote prices under `MILEAGE_PRIMARY`; below that ratio it prices under `HOURLY_PRIMARY`, and the selection is recorded in `pricing_variant`.

Rates come from the requested class. A `STANDARD` coach bills at 250 cents per mile and 15,000 cents per hour; `PREMIUM` bills at 350 cents per mile and 20,000 cents per hour; `EXECUTIVE` bills at 500 cents per mile and 30,000 cents per hour; the resolved figures are stored on the quote as `mileage_rate_cents` and `hourly_rate_cents`. Every class includes the first five hours and the first one hundred miles in its primary charge. Under `MILEAGE_PRIMARY`, the base charge is the full `estimated_miles` multiplied by the mileage rate, and only the estimated hours beyond the included five are billed additionally — at one half of the hourly rate, rounded half-up to integer cents. Under `HOURLY_PRIMARY`, the base charge is the `estimated_hours` multiplied by the hourly rate, rounded half-up to integer cents, and only the estimated miles beyond the included one hundred are billed additionally — at one half of the mileage rate, rounded half-up to integer cents.

Two requirement flags are computed during pricing. `requires_overnight` is set when `estimated_hours` exceeds 10 or when the itinerary between `trip_date` and `return_date` crosses midnight. `requires_relief_driver` is set when `estimated_hours` exceeds what a single driver may legally drive under hours-of-service limits. An overnight requirement adds driver lodging: the number of nights is `estimated_hours` divided by 24 and rounded up to the next whole night, each night billed at a flat 25,000 cents, recorded in `overnight_fee_cents`. A relief requirement adds a flat 45,000 cents in `relief_driver_fee_cents`. When `ada_required` is set, a surcharge of five percent of the combined base and supplementary charges — rounded half-up to integer cents — is added.

The quote's `subtotal_cents` then sums the base charge, the supplementary charge, the overnight fee, the relief fee, and the ADA surcharge. `tax_cents` is 8.25 percent of the subtotal, rounded half-up to integer cents — and is zero for a tax-exempt customer. `total_cents` is the sum of subtotal and tax. Pricing also fixes the quote's `deposit_cents` according to the lead-time tier of §3.4 as it stands at pricing time, stamps `quote_expiry` seventy-two hours after creation, moves the quote to `QUOTED`, and increments its `version`.

Quotes do not live forever. A quote still in `QUOTED` lapses to `EXPIRED` once the logical clock reaches `quote_expiry` — reconciled lazily on read, or on demand through the expiry-check capability available to quote agents and dispatch managers (§2.6). Either the customer or a quote agent may cancel a quote from `DRAFT` or from `QUOTED`, moving it to `CANCELLED`. `EXPIRED` and `CANCELLED` are both terminal.

### 3.4. From Acceptance to Assignment: Deposits and Dispatch

Acceptance is the customer's act, moving `QUOTED` → `ACCEPTED`. Three guards stand in front of it: the quote must still be inside its seventy-two-hour window — a lapsed quote rejects with `ERR_QUOTE_EXPIRED`; the customer must not stand in `COLLECTIONS` — rejecting with `ERR_CREDIT_SUSPENDED`; and the request must carry `expected_quote_version` matching the quote's current `version` per §2.7, else `ERR_STALE_VERSION`. Acceptance creates the charter order: the new order is born in `PENDING_DEPOSIT`, carries the `quote_id` of its origin quote and the `customer_id` denormalized from it, and is returned to the caller with a 201 status while the quote's `version` increments. The order's required `deposit_cents` is fixed at this moment from the lead time remaining between acceptance and `trip_date`: at least 720 hours (thirty days) of lead time requires ten percent of the quote's `total_cents`; at least 336 hours (fourteen days) but fewer than 720 requires twenty-five percent; at least 168 hours (seven days) but fewer than 336 requires fifty percent; at least 48 hours but fewer than 168 requires seventy-five percent; and fewer than 48 hours requires the entire total — each figure rounded half-up to integer cents. Order lists filter by `status`, `customer_id`, `quote_id`, `assigned_vehicle_id`, `assigned_driver_id`, and `relief_driver_id`; a customer's orders are listed from the account, and a quote's orders from the quote.

The customer then pays the deposit by tendering `amount_cents`; a tender below the required `deposit_cents` is rejected with `ERR_INSUFFICIENT_DEPOSIT`. A sufficient payment records `deposit_paid_cents` equal to the amount tendered, stamps `deposit_paid_at`, adds the amount received to the customer's `lifetime_revenue_cents`, and moves the order `PENDING_DEPOSIT` → `CONFIRMED`.

Assignment — a `DispatchManager` act moving `CONFIRMED` → `ASSIGNED` — names a `vehicle_id`, a `driver_id`, an optional `relief_driver_id`, and the `expected_order_version` token of §2.7. The eligibility battery then runs in the fixed order of §2.8. On the vehicle side: the named vehicle must exist and stand `AVAILABLE`; its `dot_inspection_expiry` must fall after the trip date, else `ERR_INSPECTION_EXPIRED`; its `insurance_expiry` must fall after the trip date, else `ERR_INSURANCE_EXPIRED`; its `seating_capacity` must be at least the quote's `passenger_count`, else `ERR_CAPACITY_EXCEEDED`; whenever the quote's `ada_required` is set the coach must be lift-equipped, else `ERR_ADA_REQUIRED`; and its current `odometer_miles` must still sit below `maintenance_due_miles`, else `ERR_MAINTENANCE_DUE`.

On the driver side: the named driver must exist and stand `AVAILABLE`; must hold a `CLASS_A` or `CLASS_B` license carrying a `P` endorsement, else `ERR_CDL_INSUFFICIENT`; and must carry a `safety_score` of at least 50.0, else `ERR_DRIVER_SAFETY_SCORE_LOW`. Hours-of-service feasibility then measures the trip's `estimated_hours` against three remaining allowances: the driving allowance of 11.0 hours minus the driver's `current_driving_hours_today`, breaching which yields `ERR_HOS_DRIVING_LIMIT`; the on-duty window of 14.0 hours minus `current_on_duty_hours_today`, breaching which yields `ERR_HOS_ON_DUTY_WINDOW`; and the cycle allowance — 70.0 hours for a `CYCLE_70_8` driver or 60.0 for a `CYCLE_60_7` driver — minus `current_cycle_hours`, breaching which yields `ERR_HOS_CYCLE_LIMIT`. Any such breach rejects the assignment with `ERR_HOS_VIOLATION`. When the quote `requires_relief_driver`, a `relief_driver_id` must be supplied, the relief driver must satisfy the same existence, availability, license, endorsement, and safety-score checks, and the three hour allowances no longer block the primary driver because the relief driver covers the overflow. A trip estimated beyond 8.0 hours must schedule at least one thirty-minute break; at assignment time this is advisory and does not block the operation.

A successful assignment writes `assigned_vehicle_id`, `assigned_driver_id`, and — when one was named — `relief_driver_id`; moves the vehicle `AVAILABLE` → `ASSIGNED`; moves each assigned driver `AVAILABLE` → `ON_DUTY_NOT_DRIVING`; and increments the order's `version`. Thereafter the trip may start — `ASSIGNED` → `IN_PROGRESS` — no earlier than one hour before the scheduled `trip_date`; an earlier start attempt is rejected with `ERR_TRIP_NOT_YET`. Starting the trip moves the vehicle to `IN_TRIP` and every assigned driver to `ON_TRIP`.

### 3.5. Trip Execution, Logging, and Settlement

While an order runs, a dispatch manager or administrator records the crew's duty segments against it. Each segment names the `driver_id` on duty, a `log_type` of `DRIVING`, `ON_DUTY_NOT_DRIVING`, `OFF_DUTY`, or `SLEEPER_BERTH`, the segment's `start_time` and `end_time`, its `start_location` and `end_location`, and `miles_driven`, which defaults to zero for non-driving segments. Posting a segment recomputes the driver's hours-of-service accumulators: driving segments feed `current_driving_hours_today` and extend `consecutive_driving_minutes`, on-duty time feeds `current_on_duty_hours_today` within the fourteen-hour window and `current_cycle_hours` within the driver's cycle. The segment itself is flagged `hos_violation` — with the particulars written into `violation_details` — whenever it causes or contributes to a violation. An order's segment list filters by `driver_id` and `log_type`, and each driver's segments are also listed from the driver record.

Completing the trip — permitted from `IN_PROGRESS`, and from `DISPUTED` on the terms of §3.6 — takes the trip's actuals: `actual_miles` and `actual_hours`, both required to be positive. Hours beyond the quote's `estimated_hours` (itself possibly revised by itinerary changes), floored at zero, are recorded as `extra_hours` and billed into `extra_hours_charge_cents` at one and a half times the quote's `hourly_rate_cents`, rounded half-up to integer cents.

A fuel surcharge on the quoted `subtotal_cents` scales with the actual mileage: nothing when `actual_miles` is 100 or fewer; three percent when it exceeds 100 but not 300; five percent when it exceeds 300 but not 600; and eight percent when it exceeds 600 — each figure rounded half-up into `fuel_surcharge_cents`. Final settlement then chains through the order: `final_subtotal_cents` is the quoted subtotal plus the extra-hours charge plus the fuel surcharge, less any breakdown compensation credited under §3.7; `final_tax_cents` is 8.25 percent of that final subtotal, rounded half-up, or zero for a tax-exempt customer; `final_invoice_cents` is the final subtotal plus the final tax; and `balance_due_cents` is the final invoice less the `deposit_paid_cents` already collected. `completed_at` stamps the finish, and the order lands in `COMPLETED`.

Completion cascades across the fleet, the crew, and the account. The vehicle's `odometer_miles` accrues the trip's `actual_miles`; if the new reading reaches or exceeds `maintenance_due_miles`, the vehicle drops to `IN_MAINTENANCE` and a `PREVENTIVE` maintenance record is automatically scheduled against it, and otherwise the vehicle returns to `AVAILABLE`. Every assigned driver — primary and relief alike — moves to `OFF_DUTY` with `last_rest_start` stamped at completion, beginning the ten-hour rest of §3.2, and each driver's accumulators are refreshed from the order's trip logs. On the account, `total_completed_trips` increases by one, `lifetime_revenue_cents` accrues the `final_invoice_cents`, and `safety_audit_score` recomputes; the driver's `safety_score` likewise recomputes from the driver's incident reports on completed orders (§3.9). Every resource the cascade touches increments its `version`.

### 3.6. Cancellations, Disputes, and Itinerary Changes

A customer may cancel an order while it stands in `PENDING_DEPOSIT` — no fee and no refund, since nothing was ever paid — or from `CONFIRMED` or `ASSIGNED`, where a cancellation fee applies. The fee is a percentage of `deposit_paid_cents`, selected by the lead time remaining until `trip_date`: with at least 720 hours (thirty days) remaining, no fee at all; at least 336 hours, ten percent; at least 168 hours, twenty-five percent; at least 72 hours, fifty percent; at least 24 hours, seventy-five percent; and inside 24 hours, the entire deposit. The fee is rounded half-up to integer cents into `cancellation_fee_cents`, and the remainder of the deposit comes back as `refund_cents` — the deposit paid less the fee. Cancelling from `ASSIGNED` additionally releases the assigned vehicle and every assigned driver back to `AVAILABLE`. All customer-initiated cancellations record `cancelled_by` as `CUSTOMER`.

A dispatch manager may cancel an order standing in `ASSIGNED`, and must supply a non-empty `reason`, which is recorded in `cancellation_reason`. Operator-initiated cancellations waive the fee entirely, refund the deposit in full, release the vehicle and drivers back to `AVAILABLE`, and record `cancelled_by` as `OPERATOR`. The same operator terms apply when a dispatch manager cancels an order standing in `DISPUTED`. The full vocabulary of `cancelled_by` is `CUSTOMER`, `OPERATOR`, and `SYSTEM`.

A customer who contests an in-progress trip files a dispute carrying a non-empty `reason`, moving the order `IN_PROGRESS` → `DISPUTED` and recording that reason in `cancellation_reason`. A disputed order resolves in exactly two ways: dispatch completes the trip, settling it precisely as §3.5 describes — actuals, extra hours, fuel surcharge, final invoice, and every cascade — moving `DISPUTED` → `COMPLETED`; or dispatch cancels it on the operator terms above, moving `DISPUTED` → `CANCELLED`.

Mid-trip itinerary changes are recorded on the order by the customer or by dispatch. Each change requires a `description` and may carry `new_estimated_hours` and `new_estimated_miles`. Every change appends an entry — a timestamp and the description — to the order's `itinerary_changes`, and any revised estimates propagate to the underlying quote's `estimated_hours` and `estimated_miles`, so that the completion settlement of §3.5 measures `extra_hours` against the latest estimate rather than the original one.

### 3.7. Breakdown Response and Replacement Dispatch

When a coach fails mid-trip, a dispatch manager or administrator reports the breakdown against the order, naming the stricken `vehicle_id`, the reporting `driver_id`, the `location`, and a `description` of the failure; the event is born in `REPORTED`. Breakdown lists — scoped to the order, to a vehicle, to a driver, or across the fleet — filter by `status`, `order_id`, `vehicle_id`, `driver_id`, `replacement_vehicle_id`, and `replacement_driver_id`.

Dispatching a replacement requires the event to still stand in `REPORTED`, and names a `replacement_vehicle_id` with an optional `replacement_driver_id`. The replacement coach must satisfy the same roadworthiness bar as an original assignment: it must stand `AVAILABLE`, seat at least the quote's `passenger_count`, hold a `dot_inspection_expiry` and an `insurance_expiry` that both fall after the current time, and be lift-equipped whenever the quote's `ada_required` is set — failing any of which rejects the dispatch with `ERR_REPLACEMENT_INELIGIBLE`. A successful dispatch moves the event `REPORTED` → `DISPATCHED`, records the replacement identifiers, marks the replacement vehicle `ASSIGNED`, puts any named replacement driver `ON_DUTY_NOT_DRIVING`, moves the stricken original vehicle to `IN_MAINTENANCE`, and schedules a `REPAIR` maintenance record against it.

Marking the replacement as en route moves `DISPATCHED` → `REPLACEMENT_EN_ROUTE`. Completing the replacement carries a `delay_minutes` figure that may not be negative, moves the event to `REPLACED`, and hands the order over: the order's `assigned_vehicle_id` becomes the replacement vehicle, its `assigned_driver_id` becomes the replacement driver when one was named, the replacement vehicle moves to `IN_TRIP`, and any replacement driver moves to `ON_TRIP`. When the coach is instead repaired where it sits, resolving in place — again with a non-negative `delay_minutes` — moves `REPORTED` directly to `RESOLVED_IN_PLACE`, leaving the original assignment untouched. Either resolution writes the event's `resolution_notes` recording how the breakdown was resolved, and both the event's and the order's `version` increment.

Delay compensation scales with the recorded `delay_minutes`: under 60 minutes, nothing; at least 60 but under 120 minutes, five percent of the quoted `subtotal_cents`; at least 120 but under 240, ten percent; at least 240 but under 480, twenty percent; and 480 minutes or more, thirty-five percent — each figure rounded half-up to integer cents and capped at the order's `deposit_paid_cents`. The resulting `customer_compensation_cents` is credited against the order, reducing its `final_subtotal_cents` at settlement.

A dispatch may be called off while the event still stands in `DISPATCHED`: the event moves to `CANCELLED`, the replacement vehicle and any replacement driver release back to `AVAILABLE`, and the original vehicle reverts to `IN_TRIP`. `REPLACED`, `RESOLVED_IN_PLACE`, and `CANCELLED` are terminal.

### 3.8. Maintenance and Inspection Program

A fleet manager files a maintenance record against a vehicle with a `maintenance_type` of `PREVENTIVE`, `DOT_INSPECTION`, `REPAIR`, `RECALL`, `TIRE_REPLACE`, or `BRAKE_SERVICE`; a `scheduled_date`; a `description` of the work; the `technician`; the `cost_cents`; and the `odometer_at_service`. Inspection records may carry `dot_inspection_passed`, and `defects_found` lists whatever the inspection uncovered, empty by default. Records are born in `SCHEDULED`, and the record list filters by `maintenance_type` and `status`. A record still in `SCHEDULED` once its `scheduled_date` has passed flips to `OVERDUE` on read, per the lazy reconciliation of §2.6.

Work begins only while the vehicle stands in `IN_MAINTENANCE`, moving the record `SCHEDULED` → `IN_PROGRESS`. Completing the work requires an `odometer_at_service` no lower than the vehicle's current `odometer_miles`, and — for `DOT_INSPECTION` records — an explicit `dot_inspection_passed` verdict. Completion stamps `completed_date`, projects `next_due_miles` exactly ten thousand miles beyond the service odometer, and returns the vehicle `IN_MAINTENANCE` → `AVAILABLE` with its `maintenance_due_miles` reset to the record's `next_due_miles`; a passed DOT inspection additionally refreshes the vehicle's `last_inspection_date`. Completion also recomputes `safety_audit_score` for every customer with orders on that vehicle, per §3.9. `COMPLETED` is terminal for a maintenance record.

### 3.9. Safety Governance: Incidents, Scores, Audits, and Certificates

An incident on an order is filed by a dispatch manager, safety officer, or administrator, naming the `driver_id` and `vehicle_id` involved, an `incident_type` of `ACCIDENT`, `BREAKDOWN`, `TRAFFIC_VIOLATION`, `CUSTOMER_COMPLAINT`, `HOS_VIOLATION`, `CARGO_DAMAGE`, or `OTHER`, a `severity` of `MINOR`, `MODERATE`, `MAJOR`, or `CRITICAL`, a `description`, the `occurred_at` moment, and the `reported_by` name. Filing computes two things: `dot_recordable`, true exactly when an `ACCIDENT` reaches `MAJOR` or `CRITICAL` severity, and `safety_score_impact`, the points the report costs the driver. Incident lists filter by `incident_type` and `severity`, and reports are also reachable per driver and per vehicle. A `SafetyOfficer` advances `resolution_status` — the report opens at `OPEN` and may move through `UNDER_INVESTIGATION` to `RESOLVED` or `CLOSED` — while maintaining `resolution_notes`.

A driver's `safety_score` recomputes from that driver's incident reports on completed orders, starting from a base of 100.0. Each report deducts by severity: 2.0 for `MINOR`, 5.0 for `MODERATE`, 12.0 for `MAJOR`, and 25.0 for `CRITICAL`. The deduction multiplies by one and a half when the incident is an `ACCIDENT`, and by 1.2 when it is an `HOS_VIOLATION`. The score never falls below 0.0 and is kept to one decimal place. The recomputation runs whenever an incident is filed and whenever one of the driver's orders completes; the per-report figure filed as `safety_score_impact` is the deduction a single report contributes under this schedule.

A customer's `safety_audit_score` composites the customer's completed orders, weighted by recency. A customer with no completed orders scores 100.0. Each completed order starts from a base of 100.0 and loses points for the incidents filed against it: 3.0 per `MINOR`, 7.0 per `MODERATE`, 15.0 per `MAJOR`, and 30.0 per `CRITICAL`. It loses further points for each breakdown on the order that ended `REPLACED` or `RESOLVED_IN_PLACE`: 5.0 when the recorded delay reached at least 60 minutes, and 10.0 when it reached at least 240. Each order's residual score is then weighted by recency — the weight is one minus the number of days since the order's `completed_at`, divided by 365, but never less than 0.1 — and the composite is the weighted sum divided by the total weight, rounded to one decimal place. The score recomputes when one of the customer's orders completes and when maintenance completes on a vehicle the customer's orders have used.

Venues routinely demand proof of coverage before a group arrives. A customer or a compliance officer requests a certificate against an `order_id`, naming the `venue_name` and `venue_address`, a `certificate_type` of `GENERAL_LIABILITY`, `AUTO_LIABILITY`, `UMBRELLA`, or `WORKERS_COMP`, and the `coverage_amount_cents`; the request is born in `REQUESTED`. Issuance is a `ComplianceOfficer` act requiring the order to stand in `CONFIRMED`, `ASSIGNED`, or `IN_PROGRESS`, and the assigned vehicle's `insurance_expiry` to extend beyond the trip date. Issuance moves the certificate `REQUESTED` → `ISSUED`, stamps `issued_at`, generates a unique `certificate_number`, and fixes `expires_at` at the earlier of the vehicle's insurance expiry and the quote's `return_date`. A certificate in `ISSUED` lapses to `EXPIRED` once the logical clock passes `expires_at`, reconciled lazily per §2.6, and a compliance officer may revoke an issued certificate — the request carries a `reason` — moving it to `REVOKED`. `EXPIRED` and `REVOKED` are terminal. Certificate lists filter by `status` and `order_id`.

Safety audits close the loop between operator and customer. A customer may request an audit of the operation, and a safety officer may open one directly; either way the request names the `customer_id`, an `audit_type` of `DOT_COMPLIANCE`, `SAFETY_RATING`, `INSURANCE_VERIFICATION`, or `FULL_OPERATIONAL`, and the `requested_date`, and is born in `REQUESTED`. Review begins with `REQUESTED` → `IN_REVIEW`. From review, a safety officer either approves — supplying an `overall_rating` of `SATISFACTORY` or `CONDITIONAL`, plus `notes` and optional `findings`, which land in `auditor_notes` and `findings` — moving the audit to `APPROVED`, or rejects it with `notes` and optional `findings`, fixing the rating at `UNSATISFACTORY` and moving the audit to `REJECTED`. Rejection carries teeth: the customer's `credit_status` drops to `SUSPENDED`, and both the audit record and the customer account increment their `version`. An approved audit finalizes to `COMPLETED`, stamping `completed_date`. `COMPLETED` and `REJECTED` are terminal. Audit lists filter by `status` and `customer_id`, and each customer's audits are listed from the account.

## 4. Endpoint Definitions

The table below is the complete HTTP contract. Endpoints that create a new resource answer 201; reads, updates, and state-transition operations answer 200. Quote acceptance answers 201 because it creates the charter order. Request payloads, preconditions, side effects, and error triggers are defined by the narratives of Sections 2 and 3 — this table intentionally carries no request or response schemas. All paths are mounted under the `/api/v1` prefix as shown.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/v1/customers | Register a new customer account | QuoteAgent, PlatformAdmin |
| GET | /api/v1/customers | List customer accounts | QuoteAgent, DispatchManager, PlatformAdmin, SafetyOfficer |
| GET | /api/v1/customers/{id} | Get customer account details | QuoteAgent, DispatchManager, PlatformAdmin, Customer |
| PATCH | /api/v1/customers/{id} | Update customer account fields | QuoteAgent, PlatformAdmin |
| POST | /api/v1/vehicles | Register a new vehicle in the fleet | FleetManager, PlatformAdmin |
| GET | /api/v1/vehicles | List vehicles | FleetManager, DispatchManager, PlatformAdmin |
| GET | /api/v1/vehicles/{id} | Get vehicle details | FleetManager, DispatchManager, PlatformAdmin |
| POST | /api/v1/vehicles/{id}/send-to-maintenance | Send vehicle to maintenance | FleetManager |
| POST | /api/v1/vehicles/{id}/decommission | Decommission a vehicle | FleetManager |
| POST | /api/v1/drivers | Register a new driver | FleetManager, PlatformAdmin |
| GET | /api/v1/drivers | List drivers | FleetManager, DispatchManager, SafetyOfficer, PlatformAdmin |
| GET | /api/v1/drivers/{id} | Get driver details | FleetManager, DispatchManager, SafetyOfficer, PlatformAdmin |
| POST | /api/v1/drivers/{id}/suspend | Suspend a driver | SafetyOfficer |
| POST | /api/v1/drivers/{id}/reinstate | Reinstate a suspended driver | SafetyOfficer |
| POST | /api/v1/drivers/{id}/check-rest | Manually trigger rest check for a driver | FleetManager, DispatchManager |
| POST | /api/v1/quotes | Create a new charter quote | QuoteAgent |
| GET | /api/v1/quotes | List charter quotes | QuoteAgent, DispatchManager, PlatformAdmin, Customer |
| GET | /api/v1/quotes/{id} | Get quote details | QuoteAgent, DispatchManager, Customer |
| POST | /api/v1/quotes/{id}/price | Compute pricing for a draft quote | QuoteAgent |
| POST | /api/v1/quotes/{id}/accept | Accept a quoted price and create an order | Customer |
| POST | /api/v1/quotes/{id}/cancel | Cancel a draft or quoted quote | Customer, QuoteAgent |
| POST | /api/v1/quotes/{id}/check-expiry | Manually trigger quote expiry check | QuoteAgent, DispatchManager |
| GET | /api/v1/orders | List charter orders | QuoteAgent, DispatchManager, PlatformAdmin, Customer |
| GET | /api/v1/orders/{id} | Get order details | QuoteAgent, DispatchManager, PlatformAdmin, Customer |
| POST | /api/v1/orders/{id}/pay-deposit | Pay deposit for a pending order | Customer |
| POST | /api/v1/orders/{id}/assign | Assign vehicle and driver to a confirmed order | DispatchManager |
| POST | /api/v1/orders/{id}/start-trip | Start the trip | DispatchManager |
| POST | /api/v1/orders/{id}/complete-trip | Complete a trip with actual miles/hours | DispatchManager |
| POST | /api/v1/orders/{id}/cancel | Cancel an order | Customer, DispatchManager |
| POST | /api/v1/orders/{id}/dispute | Dispute an in-progress order | Customer |
| POST | /api/v1/orders/{id}/itinerary-change | Record an itinerary change for an active order | Customer, DispatchManager |
| POST | /api/v1/orders/{id}/trip-logs | Add a trip log entry | DispatchManager, PlatformAdmin |
| GET | /api/v1/orders/{id}/trip-logs | List trip log entries for an order | DispatchManager, SafetyOfficer, PlatformAdmin |
| POST | /api/v1/orders/{id}/incidents | File an incident report | DispatchManager, SafetyOfficer, PlatformAdmin |
| GET | /api/v1/orders/{id}/incidents | List incident reports for an order | DispatchManager, SafetyOfficer, PlatformAdmin |
| PATCH | /api/v1/incidents/{id} | Update incident report resolution | SafetyOfficer |
| POST | /api/v1/vehicles/{id}/maintenance-records | Create a maintenance record | FleetManager |
| GET | /api/v1/vehicles/{id}/maintenance-records | List maintenance records for a vehicle | FleetManager, DispatchManager, SafetyOfficer |
| POST | /api/v1/maintenance-records/{id}/start | Start a scheduled maintenance | FleetManager |
| POST | /api/v1/maintenance-records/{id}/complete | Complete a maintenance record | FleetManager |
| POST | /api/v1/orders/{id}/breakdowns | Report a breakdown | DispatchManager, PlatformAdmin |
| GET | /api/v1/orders/{id}/breakdowns | List breakdown events for an order | DispatchManager, PlatformAdmin |
| GET | /api/v1/breakdowns/{id} | Get breakdown event details | DispatchManager, PlatformAdmin |
| POST | /api/v1/breakdowns/{id}/dispatch | Dispatch replacement vehicle for breakdown | DispatchManager |
| POST | /api/v1/breakdowns/{id}/en-route | Mark replacement as en route | DispatchManager |
| POST | /api/v1/breakdowns/{id}/complete-replacement | Complete vehicle replacement | DispatchManager |
| POST | /api/v1/breakdowns/{id}/resolve-in-place | Resolve breakdown without replacement | DispatchManager |
| POST | /api/v1/breakdowns/{id}/cancel-dispatch | Cancel a dispatched replacement | DispatchManager |
| POST | /api/v1/insurance-certificates | Request an insurance certificate | Customer, ComplianceOfficer |
| GET | /api/v1/insurance-certificates | List insurance certificates | ComplianceOfficer, PlatformAdmin, Customer |
| GET | /api/v1/insurance-certificates/{id} | Get insurance certificate details | ComplianceOfficer, PlatformAdmin, Customer |
| POST | /api/v1/insurance-certificates/{id}/issue | Issue an insurance certificate | ComplianceOfficer |
| POST | /api/v1/insurance-certificates/{id}/revoke | Revoke an insurance certificate | ComplianceOfficer |
| POST | /api/v1/safety-audits | Request a safety audit | Customer, SafetyOfficer |
| GET | /api/v1/safety-audits | List safety audit requests | SafetyOfficer, PlatformAdmin |
| GET | /api/v1/safety-audits/{id} | Get safety audit details | SafetyOfficer, PlatformAdmin |
| POST | /api/v1/safety-audits/{id}/begin-review | Begin reviewing a safety audit | SafetyOfficer |
| POST | /api/v1/safety-audits/{id}/approve | Approve a safety audit | SafetyOfficer |
| POST | /api/v1/safety-audits/{id}/reject | Reject a safety audit | SafetyOfficer |
| POST | /api/v1/safety-audits/{id}/finalize | Finalize an approved safety audit | SafetyOfficer |
| GET | /api/v1/customers/{id}/quotes | List quotes for a specific customer | QuoteAgent, DispatchManager, Customer |
| GET | /api/v1/customers/{id}/orders | List orders for a specific customer | QuoteAgent, DispatchManager, Customer |
| GET | /api/v1/customers/{id}/safety-audits | List safety audit requests for a customer | SafetyOfficer, Customer |
| GET | /api/v1/quotes/{id}/orders | List orders created from a specific quote | QuoteAgent, DispatchManager, Customer |
| GET | /api/v1/vehicles/{id}/orders | List orders assigned to a specific vehicle | FleetManager, DispatchManager, PlatformAdmin |
| GET | /api/v1/drivers/{id}/orders | List orders assigned to a specific driver (as primary or relief) | FleetManager, DispatchManager, SafetyOfficer, PlatformAdmin |
| GET | /api/v1/drivers/{id}/trip-logs | List trip log entries for a specific driver | FleetManager, DispatchManager, SafetyOfficer, PlatformAdmin |
| GET | /api/v1/drivers/{id}/incidents | List incident reports involving a specific driver | FleetManager, DispatchManager, SafetyOfficer, PlatformAdmin |
| GET | /api/v1/vehicles/{id}/incidents | List incident reports involving a specific vehicle | FleetManager, DispatchManager, SafetyOfficer, PlatformAdmin |
| GET | /api/v1/vehicles/{id}/breakdowns | List breakdown events involving a specific vehicle | FleetManager, DispatchManager, PlatformAdmin |
| GET | /api/v1/drivers/{id}/breakdowns | List breakdown events reported by a specific driver | FleetManager, DispatchManager, PlatformAdmin |
| GET | /api/v1/breakdowns | List all breakdown events (filtered) | DispatchManager, PlatformAdmin |
| POST | /api/v1/_clock/set_current_utc | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return. Trigger conditions are defined where each error arises in Sections 2 and 3; this table is deliberately limited to the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_HOS_VIOLATION | 422 |
| ERR_HOS_DRIVING_LIMIT | 422 |
| ERR_HOS_ON_DUTY_WINDOW | 422 |
| ERR_HOS_CYCLE_LIMIT | 422 |
| ERR_INSPECTION_EXPIRED | 422 |
| ERR_INSURANCE_EXPIRED | 422 |
| ERR_DRIVER_SAFETY_SCORE_LOW | 422 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_ADA_REQUIRED | 422 |
| ERR_MAINTENANCE_DUE | 422 |
| ERR_CDL_INSUFFICIENT | 422 |
| ERR_QUOTE_EXPIRED | 422 |
| ERR_TRIP_NOT_YET | 422 |
| ERR_INSUFFICIENT_DEPOSIT | 422 |
| ERR_CREDIT_SUSPENDED | 422 |
| ERR_REPLACEMENT_INELIGIBLE | 422 |
| ERR_REINSTATEMENT_DENIED | 422 |
