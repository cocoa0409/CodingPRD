# Commercial Fleet Leasing API — Product Requirements Document

## 1. Introduction

A commercial fleet lessor rents vehicles to customer companies on multi-month terms, and the operational reality behind a single lease is dense: a vehicle has to be allocated to a named driver for a window of time, fuel cards have to draw against the lease, telematics hardware streams odometer and driving-behavior data continuously, the shop schedules preventive and corrective maintenance, the body shop processes collision damage through an insurance waterfall, and at lease end the lessor has to settle mileage overage and excess wear and free the vehicle for the next customer. On top of all of that, a carrier running medium- and heavy-duty trucks across state lines owes apportioned fuel tax under the International Fuel Tax Agreement (IFTA), which has to be computed from the same telematics and fuel data each quarter.

This document specifies the back-office API that runs that business. It is a JSON REST service mounted under `/fleet`. The system is built around several peer aggregates — lessees, drivers, vehicles, leases, allocations, fuel cards and their transactions, telematics readings, maintenance orders, collision repair orders, overage settlements, and IFTA returns — linked by foreign keys carried in request bodies rather than by deep URL nesting. The hard parts the implementer must get right are the cascading state changes (activating a lease allocates its vehicle; finalizing a settlement closes the lease and frees the vehicle), the dual-variant money calculations (two overage pricing models, two collision-waterfall orderings), the rate-threshold triggers (excess-wear charge, total-loss declaration), and the optimistic-concurrency guards on two create endpoints.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are four roles, spelled exactly as follows: `FleetManager`, `Lessee`, `ComplianceOfficer`, and `TelematicsGateway`.

A `FleetManager` is the lessor's own operator and is the most broadly privileged actor: it runs vehicles, leases, allocations, maintenance, collision repairs, and settlements. When `X-User-Role` is `FleetManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. A `ComplianceOfficer` opens and files IFTA returns and audits fuel and telematics data; when `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A `TelematicsGateway` is a device principal that ingests telematics readings; when `X-User-Role` is `TelematicsGateway`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity. By contrast, a `Lessee` is the customer company itself: when `X-User-Role` is `Lessee`, `X-User-ID` is the `id` of the acting `Lessee` entity, and ownership checks on any resource that references a lessee compare the resource's lessee foreign key to `X-User-ID`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a requested `limit` above the maximum is capped at 100. `offset` defaults to 0 and has a minimum of 0. Results are returned sorted by `created_at` in ascending order.

For list responses, the `meta` object includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of records matching the query across all pages and `has_more` indicates whether records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned an `id` that is a server-minted UUID with no type prefix. Most resources also carry a `created_at` timestamp, an `updated_at` timestamp (both ISO 8601 UTC with millisecond precision), and an integer `version` that starts at 1 and increments by 1 on every mutation of that resource. Two resource types are deliberately leaner: a `FuelTransaction` and a `TelematicsReading` are append-style records that carry only `id` and `created_at` — they have no `updated_at` and no `version`.

The `version` field is also the substrate for optimistic concurrency control on two endpoints (see §2.6). Whenever a transition's side effects state that an entity's version increments, that increment is part of the same atomic mutation.

### 2.5. Money, Mileage, and Rounding Conventions

All monetary amounts are stored and returned as integer cents. The two overage pricing computations and the collision-repair waterfall operate purely on integer inputs and produce integer cents with no rounding step. The excess-wear score is computed as a real number and rounded half-up to two decimal places, while its resulting charge is an integer number of cents. The IFTA computation is the only place fractional rounding is layered: fleet miles-per-gallon and per-jurisdiction taxable gallons are rounded half-up to three decimal places, per-jurisdiction tax amounts are rounded half-up to two decimal places (dollars), and the final net tax is converted to an integer number of cents. Wherever rounding is applied anywhere in the system, it is round-half-up.

### 2.6. Optimistic Concurrency on Guarded Creates

Two create operations are guarded against acting on a stale view of their parent. Reporting a collision repair against a vehicle requires the request to include `expected_vehicle_version`, carrying the client's last observed `version` of that `Vehicle`. If that value does not match the vehicle's current `version` — because another writer has advanced the vehicle since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Similarly, creating an allocation requires `expected_lease_version`, carrying the client's last observed `version` of the target `Lease`; if it does not match the lease's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). These two version fields are required, non-optional inputs on their respective creates. No other endpoint accepts or requires a version field.

### 2.7. Validation Ordering

When several conditions could reject a request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (presence of both headers) is checked first, then authorization (role permitted for the operation), then existence of every path-referenced and foreign-key-referenced resource, validated left to right. After those come well-formedness of the request body (required fields present and correctly typed, enum values within their allowed sets), then uniqueness of any unique field, then the state precondition (the target is in a state from which the requested transition is defined). Only after all of those pass are the operation-specific business rules — vehicle availability, driver license standing, lease activeness, window overlaps, odometer monotonicity, fuel-card standing, open-blocker gates, qualified-fuel presence, total-loss thresholds, and the optimistic-concurrency version match — evaluated. The corresponding error identifiers are `ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN`, `ERR_NOT_FOUND`, `ERR_INVALID_REQUEST`, `ERR_DUPLICATE`, and `ERR_INVALID_STATE` for the ordered front of the chain, followed by the business-specific codes introduced in §3.

### 2.8. Uniqueness Constraints

Four uniqueness rules are enforced at creation time, each surfacing `ERR_DUPLICATE` (HTTP 409) when violated: a vehicle's `vin` must be unique across all vehicles, a driver's `license_number` must be unique across all drivers, a fuel card's `card_number` must be unique across all fuel cards, and an IFTA return's `quarter` must be unique per lessee (the pair of lessee and `quarter` may not repeat).

### 2.9. Nested Listing and Reverse Reachability

A handful of list endpoints are reached through a parent path segment — the telematics readings and maintenance orders of a given vehicle. For these, the parent vehicle in the path is validated first; if it does not exist the request fails with `ERR_NOT_FOUND` (HTTP 404) before any listing occurs. Other lists are flat collections filterable by a foreign-key query parameter.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Lessees, Drivers, and Vehicles

The lessor begins by registering a leasing customer company, supplying its `company_name` and `billing_email`. A newly registered lessee starts in `account_status` `ACTIVE` and carries an `outstanding_balance_cents` of 0; that balance is a running ledger of what the customer owes, accumulating from settlement and total-loss charges as described later. A lessee account can be suspended, moving its `account_status` to `SUSPENDED`; a suspended lessee blocks new lease activation.

Drivers are registered under a lessee. Each driver record carries the `lessee_id` of the company it works for, the driver's `full_name`, and a `license_number`. A driver begins with `license_status` `VALID`, and a fleet operator may later mark a license `SUSPENDED`; license standing gates whether the driver can receive a vehicle. Both a `FleetManager` and a `Lessee` may register drivers, but only a `FleetManager` may suspend a license.

Vehicles enter the fleet with a `vin` and a `class`, where `class` is one of `LIGHT_DUTY`, `MEDIUM_DUTY`, or `HEAVY_DUTY` and determines IFTA qualification. A new vehicle starts with `status` `AVAILABLE`, `odometer_miles` of 0, and `open_block_count` of 0. The `odometer_miles` field is the latest reading and is advanced both by incoming telematics and by the lease-end return. The `open_block_count` is a derived count of non-terminal blockers on the vehicle — maintenance orders that are `SCHEDULED` or `IN_PROGRESS`, plus repair orders that are not yet `COMPLETED`, `TOTAL_LOSS_SETTLED`, or `REJECTED` — and it is the gate that controls whether a vehicle may return to `AVAILABLE`.

### 3.2. The Lease Lifecycle

A lease is created in `DRAFT` and references the customer through `lessee_id` and the vehicle through `vehicle_id`. At creation the lessor fixes the commercial terms: `term_start` and `term_end` (the contracted term), `contracted_miles` (the mileage cap included over the full term, which must be zero or greater), `per_mile_overage_cents` (the flat per-excess-mile rate, zero or greater, used by one of the two overage models), `overage_model` (either `CONTRACT_FLAT` or `TIERED_EXCESS`), `collision_deductible_cents` (the lessee deductible used in the collision waterfall, zero or greater), and `waterfall_model` (either `DEDUCTIBLE_FIRST` or `INSURANCE_FIRST`). The lease also carries two system-maintained odometer snapshots, `odometer_start` and `odometer_end`, both 0 until set by the lifecycle.

Activating a draft lease — the `DRAFT` to `ACTIVE` transition — requires that the lease currently be `DRAFT`, that the referenced vehicle be `AVAILABLE`, and that the lessee's account be `ACTIVE`. If the vehicle is in any state other than `AVAILABLE`, activation is refused with `ERR_VEHICLE_NOT_AVAILABLE` (HTTP 409). On a successful activation three things happen atomically: the lease's `odometer_start` is set to the vehicle's current `odometer_miles`, the vehicle cascades from `AVAILABLE` to `ALLOCATED`, and the lease's `version` increments by 1. A draft lease that is not yet wanted can instead be cancelled — the `DRAFT` to `CANCELLED` transition — which simply moves the lease to `CANCELLED`; `CANCELLED` is terminal.

When the term is up, the lessor initiates the return — the `ACTIVE` to `RETURN_INITIATED` transition — which is permitted only from `ACTIVE` and only when no allocation on this lease is still `ASSIGNED`; a lingering assignment blocks return with `ERR_ACTIVE_ALLOCATION_EXISTS` (HTTP 409). Initiating return captures the vehicle's current `odometer_miles` into the lease's `odometer_end`, freezes every still-`ACTIVE` fuel card on the lease (each cascading from `ACTIVE` to `FROZEN`), and increments the lease's `version` by 1. From `RETURN_INITIATED`, opening a settlement advances the lease to `PENDING_SETTLEMENT`, and finalizing that settlement advances the lease from `PENDING_SETTLEMENT` to its terminal `CLOSED` state; both of those are detailed in §3.7. Any lifecycle action attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.3. Allocating Vehicles to Drivers

Once a lease is live, the vehicle it carries can be assigned to a driver for a time window. Creating an allocation references the lease through `lease_id` and the driver through `driver_id`, and supplies the assignment interval as `window_start` and `window_end`, treated as a half-open interval that includes the start instant and excludes the end instant. The create also carries `expected_lease_version` for the concurrency check described in §2.6; a stale value yields `ERR_STALE_VERSION` (HTTP 412). A successful create increments the lease's `version` by 1. An allocation is born `ASSIGNED` and can later be released — the `ASSIGNED` to `RELEASED` transition — which moves it to its terminal `RELEASED` state; releasing is permitted only from `ASSIGNED`.

Three business rules guard allocation creation beyond existence and well-formedness. The referenced driver's `license_status` must be `VALID`; assigning a vehicle to a driver whose license is `SUSPENDED` is rejected with `ERR_DRIVER_LICENSE_INVALID` (HTTP 409). The referenced lease's `status` must be `ACTIVE`; an allocation against a lease in any other state is rejected with `ERR_LEASE_NOT_ACTIVE` (HTTP 409). And the requested half-open window must not overlap any other `ASSIGNED` allocation on the same lease's vehicle: two intervals that merely touch at the boundary (one ending exactly when the next begins) do not overlap and are allowed, but any genuine overlap is rejected with `ERR_ALLOCATION_OVERLAP` (HTTP 409).

### 3.4. Fuel Cards and Fuel Transactions

A fuel card is issued against a lease, referencing it through `lease_id` and carrying a `card_number`. A card starts `ACTIVE` and tracks a computed `total_gallons_purchased` that begins at 0. A card's `status` is one of `ACTIVE`, `FROZEN`, or `CLOSED`; cards are frozen automatically when their lease's return is initiated, as described in §3.2.

A fuel transaction records a purchase against a card. It references the card through `fuel_card_id` and supplies the `jurisdiction` where fuel was bought (one of `CA`, `NV`, `AZ`, `OR`, `TX`, or `WA`), the `gallons` dispensed (which must be strictly greater than zero), and the `purchased_at` timestamp that determines the IFTA quarter the purchase falls in. A transaction begins `POSTED`. Posting a transaction is allowed only when the target card's `status` is `ACTIVE`; a transaction posted against a `FROZEN` or `CLOSED` card is rejected with `ERR_FUEL_CARD_NOT_ACTIVE` (HTTP 409). Each successful post adds the transaction's gallons to the card's `total_gallons_purchased`. A posted transaction can be voided — the `POSTED` to `VOIDED` transition, permitted only from `POSTED` — which moves it to its terminal `VOIDED` state and compensating-reverses its effect by subtracting its `gallons` back out of the card's `total_gallons_purchased`. Both a `FleetManager` and a `Lessee` may post fuel transactions, but only a `FleetManager` may void one.

### 3.5. Telematics Ingestion

Telematics readings stream in from the vehicles. A reading references the reporting vehicle through `vehicle_id`, names the `jurisdiction` the miles were driven in (one of `CA`, `NV`, `AZ`, `OR`, `TX`, or `WA`), and carries a cumulative `odometer_miles`, the `segment_miles` driven in this jurisdiction since the prior reading (zero or greater), an optional `harsh_events` count of harsh-braking and acceleration events (defaulting to 0), an optional `idle_minutes` of engine idling (defaulting to 0), and a `recorded_at` timestamp. Both a `TelematicsGateway` and a `FleetManager` may ingest readings. The cumulative `odometer_miles` on a reading must be at least the vehicle's current `odometer_miles` — readings may stay equal or move forward but may never regress; a reading whose odometer falls below the vehicle's current reading is rejected with `ERR_ODOMETER_REGRESSION` (HTTP 409). Each accepted reading advances the vehicle's `odometer_miles` to the reading's `odometer_miles`. The `harsh_events` and `idle_minutes` figures are the raw inputs to the excess-wear score computed at settlement, and the `segment_miles` together with the `jurisdiction` feed the IFTA mileage apportionment.

### 3.6. Maintenance Orders

A maintenance order is scheduled against a vehicle, referencing it through `vehicle_id` and specifying its `kind` (one of `PREVENTIVE`, `CORRECTIVE`, or `RECALL`), the shop window as `window_start` and `window_end` (a closed interval), and the cost components `labor_cents` and `parts_cents` (each zero or greater). A maintenance order's `total_cost_cents` begins at 0 and is pinned only at completion. An order is created `SCHEDULED`.

Scheduling is guarded by a buffered overlap rule. The order's closed window is expanded by sixty minutes on each end, and that expanded window must not collide with the window of any other `SCHEDULED` or `IN_PROGRESS` maintenance order on the same vehicle. Equivalently, two maintenance windows on a vehicle conflict whenever the clear gap between them is sixty minutes or less; a gap strictly greater than sixty minutes is required for the new order to be accepted. A violation is rejected with `ERR_MAINTENANCE_OVERLAP` (HTTP 409).

Starting maintenance — the `SCHEDULED` to `IN_PROGRESS` transition — is permitted only when the order is `SCHEDULED` and the vehicle is either `ALLOCATED` or `IN_MAINTENANCE`. Starting increments the vehicle's `open_block_count` by 1, and if the vehicle was `ALLOCATED` it cascades to `IN_MAINTENANCE` (a vehicle already `IN_MAINTENANCE` stays put). Completing maintenance — the `IN_PROGRESS` to `COMPLETED` transition, permitted only from `IN_PROGRESS` — pins the order's `total_cost_cents` to the sum of its `labor_cents` and `parts_cents`, decrements the vehicle's `open_block_count` by 1, and, only if that count has reached zero and the vehicle is currently `IN_MAINTENANCE`, cascades the vehicle from `IN_MAINTENANCE` back to `ALLOCATED`. A still-scheduled order can instead be cancelled — the `SCHEDULED` to `CANCELLED` transition, permitted only from `SCHEDULED` — moving it to its terminal `CANCELLED` state. Both `COMPLETED` and `CANCELLED` are terminal.

### 3.7. Lease-End Return and Overage Settlement

After a lease's return has been initiated, the lessor opens its settlement. Opening the settlement is the lease's `RETURN_INITIATED` to `PENDING_SETTLEMENT` transition: it is permitted only when the lease is `RETURN_INITIATED` and no settlement already exists for that lease, and it creates a fresh `OverageSettlement` in `DRAFT` referencing the lease through `lease_id` while moving the lease to `PENDING_SETTLEMENT`. The settlement's computed figures — `excess_miles`, `mileage_charge_cents`, `excess_wear_score`, `excess_wear_charge_cents`, and `net_charge_cents` — all start at 0 and are pinned only at finalization.

Finalizing the settlement — the `DRAFT` to `FINALIZED` transition — is permitted only when the settlement is `DRAFT` and its lease is `PENDING_SETTLEMENT`, and it is additionally gated on the vehicle having no open blockers: if the vehicle's `open_block_count` is greater than zero, finalization is rejected with `ERR_OPEN_BLOCKERS` (HTTP 409). Finalization pins all five computed figures (per the calculations below), adds the settlement's `net_charge_cents` to the lessee's `outstanding_balance_cents`, increments the settlement's `version` by 1, and cascades the lease from `PENDING_SETTLEMENT` to its terminal `CLOSED` state — which in turn cascades the vehicle from `ALLOCATED` back to `AVAILABLE`, making it eligible for the next customer.

The mileage figures come first. The settlement's `excess_miles` is the vehicle's mileage driven over the lease beyond the contracted cap: take the lease's `odometer_end` minus its `odometer_start` minus its `contracted_miles`, and if that is negative treat it as zero. The `mileage_charge_cents` then depends on the lease's `overage_model`. Under `CONTRACT_FLAT`, the charge is the excess miles multiplied by the lease's `per_mile_overage_cents` — a single flat rate on every excess mile. Under `TIERED_EXCESS`, the excess miles are split into two tiers: the first ten thousand excess miles are charged at twenty cents each, and every excess mile beyond ten thousand is charged at thirty-five cents each; the charge is the sum of the two tiers. (Concretely: the tier-one miles are the lesser of the excess miles and ten thousand; the tier-two miles are whatever excess remains above ten thousand, or zero if there is none.)

The wear figures come from the telematics gathered over the lease. First aggregate, across all telematics readings for the lease's vehicle whose `recorded_at` falls within the lease's `term_start` to `term_end`, the total `harsh_events` and the total `idle_minutes`. Compute a denominator of total miles as the lease's `odometer_end` minus `odometer_start`, but never less than one mile. Then form a harsh-event rate of total harsh events divided by total miles, scaled to a per-thousand-mile figure by multiplying by one thousand, and an idle figure of total idle minutes divided by total miles scaled by one hundred (idle minutes per hundred miles, treated as a percentage). The raw score is a weighted blend: the harsh-per-thousand figure is itself multiplied by ten and then weighted at one-half, the idle figure is weighted at three-tenths, and a speed component (reserved and always zero in this revision) is weighted at two-tenths. Round the raw score half-up to two decimal places to obtain `excess_wear_score`. The `excess_wear_charge_cents` is a flat fifty thousand cents when the `excess_wear_score` is strictly greater than thirty, and zero otherwise. Finally, `net_charge_cents` is the sum of `mileage_charge_cents` and `excess_wear_charge_cents`. All of these amounts are integer cents with no rounding beyond the half-up rounding of the score itself.

### 3.8. Collision Repair and the Insurance Waterfall

When a leased vehicle is damaged, a repair order is reported against it, referencing the damaged vehicle through `vehicle_id` and the governing lease through `lease_id` (the lease whose deductible and lessee-responsibility apply). The report also carries `expected_vehicle_version` for the concurrency guard in §2.6; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), and a successful report increments the vehicle's `version` by 1. A repair order begins `REPORTED`. Its money fields — the input `estimate_cents` and `insurance_cap_cents`, and the computed `driver_deductible_cents`, `insurance_paid_cents`, and `lessee_responsible_cents` — all start at 0.

Assessment — the `REPORTED` to `ASSESSED` transition, permitted only from `REPORTED` — records the adjuster's `estimate_cents` (the repair-cost estimate) and `insurance_cap_cents` (the maximum the insurer will cover) from the request, and increments the vehicle's `open_block_count` by 1. From `ASSESSED` the claim forks two ways, and the fork is decided by a total-loss threshold: the estimate is compared against eight-tenths of the insurance cap. Approval — the `ASSESSED` to `APPROVED` transition — is the not-a-total-loss path and is permitted only when the `estimate_cents` is at most eight-tenths of `insurance_cap_cents`; attempting to approve when the estimate exceeds that threshold is rejected with `ERR_IS_TOTAL_LOSS` (HTTP 409) because the claim must instead be declared a total loss. Declaring a total loss — the `ASSESSED` to `TOTAL_LOSS` transition — is the mirror path and is permitted only when the `estimate_cents` is strictly greater than eight-tenths of `insurance_cap_cents`; attempting to declare a total loss when the estimate is at or below that threshold is rejected with `ERR_NOT_TOTAL_LOSS` (HTTP 409). A claim in `ASSESSED` may also be rejected outright — the `ASSESSED` to `REJECTED` transition, permitted only from `ASSESSED` — which decrements the vehicle's `open_block_count` by 1 and moves the order to its terminal `REJECTED` state.

Approval runs the collision waterfall (described below), pinning the three computed allocations, and cascades the vehicle from `ALLOCATED` to `IN_REPAIR`. From `APPROVED`, completing the repair — the `APPROVED` to `COMPLETED` transition, permitted only from `APPROVED` — decrements the vehicle's `open_block_count` by 1 and, only if that count has reached zero, cascades the vehicle from `IN_REPAIR` back to `ALLOCATED`; `COMPLETED` is terminal. On the total-loss branch, settling — the `TOTAL_LOSS` to `TOTAL_LOSS_SETTLED` transition, permitted only from `TOTAL_LOSS` — also runs the collision waterfall to pin the three allocations, adds the order's `lessee_responsible_cents` to the lessee's `outstanding_balance_cents`, decrements the vehicle's `open_block_count` by 1, and cascades the vehicle from `IN_REPAIR` to its terminal `RETIRED` state; `TOTAL_LOSS_SETTLED` is terminal.

The waterfall itself allocates the `estimate_cents` across three buckets — the lessee's deductible, the insurer's coverage up to the cap, and an overflow the lessee absorbs — and the order in which the first two buckets are filled is set by the lease's `waterfall_model`. Under `DEDUCTIBLE_FIRST`, the `driver_deductible_cents` is filled first as the lesser of the `estimate_cents` and the lease's `collision_deductible_cents`; the remaining estimate after that is the `insurance_paid_cents`, taken as the lesser of that remainder and the `insurance_cap_cents`; whatever still remains is the overflow. Under `INSURANCE_FIRST`, the `insurance_paid_cents` is filled first as the lesser of the `estimate_cents` and the `insurance_cap_cents`; the remaining estimate after that funds the `driver_deductible_cents`, taken as the lesser of that remainder and the lease's `collision_deductible_cents`; whatever still remains is the overflow. In both orderings the `lessee_responsible_cents` is the sum of the `driver_deductible_cents` and the overflow. The two orderings produce the same totals only sometimes; they diverge whenever the estimate is smaller than the deductible plus the cap combined. All figures are integer cents with no rounding.

### 3.9. IFTA Quarterly Filing

A `ComplianceOfficer` opens an IFTA return for a carrier and reporting period, referencing the lessee through `lessee_id` and supplying the `quarter` as a four-digit year followed by `Q` and a quarter digit one through four (for example `2026Q1`). A return begins `DRAFT`, with its computed `fleet_mpg` and `net_tax_due_cents` at 0. Filing — the `DRAFT` to `FILED` transition, permitted only from `DRAFT` — is gated on there being qualifying fuel: the total qualified gallons in the quarter must be strictly greater than zero, meaning at least one `POSTED` fuel transaction tied to a qualified vehicle in that quarter exists; otherwise filing is rejected with `ERR_NO_QUALIFIED_FUEL` (HTTP 409). Filing pins `fleet_mpg` and `net_tax_due_cents` and increments the return's `version` by 1.

The computation considers only qualified vehicles — those whose `class` is `MEDIUM_DUTY` or `HEAVY_DUTY` — and only data within the return's quarter (telematics by `recorded_at`, fuel by `purchased_at`). First sum the `segment_miles` of all telematics readings for qualified vehicles in the quarter to get the total qualified miles, and sum the `gallons` of all `POSTED` fuel transactions on the cards of qualified vehicles in the quarter to get the total qualified gallons. The `fleet_mpg` is the total qualified miles divided by the total qualified gallons, rounded half-up to three decimals. Then, for each of the six jurisdictions in turn, gather the miles driven in that jurisdiction (the sum of `segment_miles` where the reading's `jurisdiction` is that jurisdiction) and the gallons purchased there (the sum of `gallons` where the transaction's `jurisdiction` is that jurisdiction). The taxable gallons for the jurisdiction are its miles divided by the `fleet_mpg`, rounded half-up to three decimals. The tax owed for the jurisdiction is its taxable gallons multiplied by that jurisdiction's tax rate, rounded half-up to two decimals (dollars); the tax already paid is its purchased gallons multiplied by the same rate, rounded half-up to two decimals; and the net for the jurisdiction is tax owed minus tax paid, rounded half-up to two decimals. The per-jurisdiction tax rates, in dollars per gallon, are 0.40 for `CA`, 0.27 for `NV`, 0.26 for `AZ`, 0.38 for `OR`, 0.20 for `TX`, and 0.49 for `WA`. The rounding order is fixed: round each jurisdiction's figures first, then sum the per-jurisdiction nets across all jurisdictions, and finally convert that dollar sum to an integer number of cents (multiply by one hundred and round half-up) to obtain `net_tax_due_cents`.

### 3.10. The Lessee Ledger

The lessee's `outstanding_balance_cents` is a running tally of what the customer owes the lessor and is reconciled on each charging event. Two events add to it: finalizing an overage settlement adds that settlement's `net_charge_cents`, and settling a total-loss repair adds that repair order's `lessee_responsible_cents`. The balance is exposed whenever a lessee is read so that the customer and the lessor see a consistent picture.

## 4. Endpoint Definitions

All endpoints are mounted under the `/fleet` prefix. Creating a new resource returns HTTP 201; reads and state-changing actions on existing resources return HTTP 200. Request bodies, computed side effects, and the precise rules behind each action are described in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /fleet/lessees | Register a leasing customer company | FleetManager |
| GET | /fleet/lessees/{id} | Fetch a lessee (includes computed outstanding balance) | FleetManager, ComplianceOfficer, Lessee |
| POST | /fleet/lessees/{id}/suspend | Suspend a lessee account | FleetManager |
| POST | /fleet/drivers | Register a driver under a lessee | FleetManager, Lessee |
| GET | /fleet/drivers/{id} | Fetch a driver | FleetManager, ComplianceOfficer, Lessee |
| GET | /fleet/drivers | List drivers, optionally filtered by lessee | FleetManager, ComplianceOfficer, Lessee |
| POST | /fleet/drivers/{id}/suspend-license | Mark a driver license suspended | FleetManager |
| POST | /fleet/vehicles | Register a fleet vehicle | FleetManager |
| GET | /fleet/vehicles/{id} | Fetch a vehicle | FleetManager, ComplianceOfficer, Lessee |
| GET | /fleet/vehicles/{id}/telematics-readings | List telematics readings for a vehicle | FleetManager, ComplianceOfficer, TelematicsGateway |
| GET | /fleet/vehicles/{id}/maintenance-orders | List maintenance orders for a vehicle | FleetManager, Lessee |
| POST | /fleet/leases | Create a lease in DRAFT | FleetManager |
| GET | /fleet/leases/{id} | Fetch a lease | FleetManager, ComplianceOfficer, Lessee |
| GET | /fleet/leases | List leases, optionally filtered by lessee or vehicle | FleetManager, ComplianceOfficer, Lessee |
| POST | /fleet/leases/{id}/activate | Activate a draft lease | FleetManager |
| POST | /fleet/leases/{id}/cancel | Cancel a draft lease | FleetManager |
| POST | /fleet/leases/{id}/initiate-return | Begin lease-end return | FleetManager |
| POST | /fleet/allocations | Assign a vehicle to a driver for a window | FleetManager |
| GET | /fleet/allocations/{id} | Fetch an allocation | FleetManager, Lessee |
| GET | /fleet/allocations | List allocations filtered by lease or driver | FleetManager, Lessee |
| POST | /fleet/allocations/{id}/release | Release an allocation | FleetManager |
| POST | /fleet/fuel-cards | Issue a fuel card against a lease | FleetManager |
| GET | /fleet/fuel-cards/{id} | Fetch a fuel card (includes computed gallons) | FleetManager, Lessee |
| GET | /fleet/fuel-cards | List fuel cards filtered by lease | FleetManager, Lessee |
| POST | /fleet/fuel-transactions | Post a fuel purchase against a card | FleetManager, Lessee |
| GET | /fleet/fuel-transactions/{id} | Fetch a fuel transaction | FleetManager, ComplianceOfficer, Lessee |
| GET | /fleet/fuel-transactions | List fuel transactions filtered by card | FleetManager, ComplianceOfficer, Lessee |
| POST | /fleet/fuel-transactions/{id}/void | Void a posted fuel transaction | FleetManager |
| POST | /fleet/telematics-readings | Ingest a telematics reading | TelematicsGateway, FleetManager |
| POST | /fleet/maintenance-orders | Schedule a maintenance order | FleetManager |
| GET | /fleet/maintenance-orders/{id} | Fetch a maintenance order | FleetManager, Lessee |
| POST | /fleet/maintenance-orders/{id}/start | Begin maintenance | FleetManager |
| POST | /fleet/maintenance-orders/{id}/complete | Complete maintenance | FleetManager |
| POST | /fleet/maintenance-orders/{id}/cancel | Cancel a scheduled maintenance order | FleetManager |
| POST | /fleet/repair-orders | Report a collision repair | FleetManager |
| GET | /fleet/repair-orders/{id} | Fetch a repair order | FleetManager, ComplianceOfficer, Lessee |
| GET | /fleet/repair-orders | List repair orders filtered by vehicle or lease | FleetManager, ComplianceOfficer, Lessee |
| POST | /fleet/repair-orders/{id}/assess | Adjuster assessment | FleetManager |
| POST | /fleet/repair-orders/{id}/approve | Approve repair (not a total loss) | FleetManager |
| POST | /fleet/repair-orders/{id}/declare-total-loss | Declare total loss | FleetManager |
| POST | /fleet/repair-orders/{id}/complete | Complete an approved repair | FleetManager |
| POST | /fleet/repair-orders/{id}/settle-total-loss | Settle a total loss | FleetManager |
| POST | /fleet/repair-orders/{id}/reject | Reject a repair claim | FleetManager |
| POST | /fleet/overage-settlements | Open the settlement for a returned lease | FleetManager |
| GET | /fleet/overage-settlements/{id} | Fetch a settlement (includes computed charges) | FleetManager, ComplianceOfficer, Lessee |
| GET | /fleet/overage-settlements | List settlements filtered by lease | FleetManager, ComplianceOfficer, Lessee |
| POST | /fleet/overage-settlements/{id}/finalize | Finalize the settlement | FleetManager |
| POST | /fleet/ifta-returns | Open an IFTA return for a lessee/quarter | ComplianceOfficer |
| GET | /fleet/ifta-returns/{id} | Fetch an IFTA return | ComplianceOfficer, FleetManager, Lessee |
| GET | /fleet/ifta-returns | List IFTA returns filtered by lessee | ComplianceOfficer, FleetManager, Lessee |
| POST | /fleet/ifta-returns/{id}/file | File the return | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_DUPLICATE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_VEHICLE_NOT_AVAILABLE | 409 |
| ERR_DRIVER_LICENSE_INVALID | 409 |
| ERR_LEASE_NOT_ACTIVE | 409 |
| ERR_ALLOCATION_OVERLAP | 409 |
| ERR_MAINTENANCE_OVERLAP | 409 |
| ERR_ODOMETER_REGRESSION | 409 |
| ERR_FUEL_CARD_NOT_ACTIVE | 409 |
| ERR_ACTIVE_ALLOCATION_EXISTS | 409 |
| ERR_OPEN_BLOCKERS | 409 |
| ERR_NO_QUALIFIED_FUEL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_TOTAL_LOSS | 409 |
| ERR_IS_TOTAL_LOSS | 409 |
