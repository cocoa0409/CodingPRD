# Forklift Fleet Sales, Rental & Service API — Product Requirements Document

## 1. Introduction

A Toyota Material Handling dealership runs four revenue engines off the same iron: configure-to-order new-unit sales, a short- and long-term rental fleet, a lease portfolio, and a used-equipment pipeline fed by off-lease returns and trade-ins. All four draw on the same physical assets, the same mobile technicians, and the same customer credit lines — which is exactly what makes consistency hard. A forklift cannot be on rent, in the shop, and listed for resale at the same time; a customer whose posted charges have overrun their credit line should not drive another unit off the yard; and a truck whose hour meter has crossed its planned-maintenance interval must not be checked out to the next renter until a technician has serviced it.

This document specifies the API that coordinates those operations end to end. It governs unit configuration and attachment quoting, rental reservations with tiered day/week/month billing and credit holds, planned maintenance triggered by hour-meter telemetry, breakdown dispatch with van-stock part reservation and buffered scheduling windows, operator training and certification tracking, the battery-versus-LP energy program, lease-end inspection and residual settlement, and used-unit reconditioning through quality control to resale. All business resources are served under the `/fleet` mount. The audience is the engineering team building the service; every behavioral rule stated below is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles, spelled as follows: `FleetManager`, `SalesRep`, `RentalCoordinator`, `ServiceDispatcher`, `Technician`, `TrainingRegistrar`, and `LeaseManager`. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` differs by role. For `FleetManager`, `SalesRep`, `RentalCoordinator`, `ServiceDispatcher`, `TrainingRegistrar`, and `LeaseManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's foreign-key field to `X-User-ID`. Concretely, resolving a dispatched service call is permitted only when the call's `technician_id` equals the caller's `X-User-ID`; any other technician attempting the resolve is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Several list endpoints also accept resource-specific filters: the quote list filters by `customer_id`, `unit_id`, or `status`; the rental-contract and lease-contract lists filter by `unit_id`, `customer_id`, or `status`; the service-call list filters by `unit_id`, `customer_id`, `technician_id`, `operator_id`, or `status`; and the reconditioning-order list filters by `unit_id` or `status`.

### 2.4. Common Resource Properties

Primary, top-level resources — customers, units, quotes, rental contracts, service calls, technicians, operators, certifications, lease contracts, and reconditioning orders — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): starts at 1 when the resource is created and increments by exactly 1 on every mutation, including mutations the server applies as side effects of operations on other resources.

Sub-resources that exist only as children of a parent — quote lines, meter readings, fuel events, and lease inspections — carry only `id` and `created_at`. Both `updated_at` and `version` are absent on those four resource types.

### 2.5. Nested Resource Retrieval and Existence Checks

Requests that target nested resources are validated strictly left to right along the URL path. The system confirms each path identifier in sequence and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before examining anything further along the path. Only after every path identifier has been resolved does the system verify resources referenced in the request body — identifiers such as `unit_id`, `customer_id`, `technician_id`, or `operator_id` — each of which likewise yields `ERR_NOT_FOUND` when it does not resolve to an existing resource.

### 2.6. Validation Order and Error Precedence

When several checks could reject the same request, the system evaluates them in one fixed precedence ladder, and the first failing check determines the error returned. From first to last: authentication of the headers; role authorization for the endpoint; request-body shape (required fields present, types correct, enum values valid); existence of referenced resources as described in §2.5; state validity of the requested transition; and then the business gates in this exact order — the unit availability gate, the optimistic-concurrency version check, the planned-maintenance posture gate on checkout, the certified-operator requirement on quote acceptance, the dispatch-time operator certification check, the unit disposition gate, the technician-active requirement, the quote non-emptiness requirement, van-stock sufficiency, fuel-program match, hour-meter monotonicity, the rental window overlap check, the dispatch window overlap check, the quote expiry check, the customer's account standing, and finally whether the charge fits within the customer's available credit.

Two state-level checks share the same rung on the lease settlement path and deserve an explicit tiebreak. If the lease is not in `RETURNED` status at all, the settle attempt fails with `ERR_INVALID_STATE`. Only once the lease is known to be `RETURNED` does the system ask whether exactly one inspection has been approved for it; a returned lease without an approved inspection fails with `ERR_INSPECTION_NOT_APPROVED`.

### 2.7. Monetary Precision and Rounding Discipline

All monetary amounts are integer cents — rates, prices, charges, balances, holds, and settlement totals alike. Whenever a calculation produces a fractional cent (for example, applying a percentage discount or tax), the result is rounded half up to the nearest whole cent. Percentages such as a customer's `discount_pct` are fractions of a whole: a value of 0.10 means ten percent. Hour-meter readings, hour allowances, and kilowatt-hours are plain numbers and may be fractional; they are compared exactly, never pre-rounded. The single quantity that departs from whole-unit precision is the fleet utilization percentage, which is reported rounded half up to one decimal place.

### 2.8. Optimistic Concurrency Control on Unit Version

Exactly one write operation participates in optimistic concurrency control: the creation of a rental contract. The request must carry `expected_unit_version`, a non-optional field holding the `version` of the target unit as the client last observed it. If the unit's current `version` has advanced beyond that value — because an earlier reservation, return, or other mutation touched it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), since contract creation re-derives the unit's reserved windows and utilization and must not proceed from an out-of-date view of the unit. Rental-contract creation itself increments the unit's `version` by 1 as a side effect. No other endpoint accepts a version field; all other mutations run without an optimistic-concurrency check.

### 2.9. The Logical Clock and Scheduled Sweeps

Time inside the system is governed by a logical clock, never the real wall clock. At server startup, before any explicit adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. A `FleetManager`-only test-driving capability advances the clock to a supplied instant given as `to_iso8601` in ISO 8601 UTC. Advancing the clock fires two time-based sweeps: every quote still `SUBMITTED` whose `valid_until` has been passed transitions to `EXPIRED`, and every certification still `ACTIVE` whose `expires_at` has been passed transitions to `EXPIRED`. Features that read "now" — quote submission timestamps, certification issuance, utilization windows, expiry checks — all consult this logical clock.

### 2.10. Credit Exposure and Account Standing

Every customer carries a credit picture composed of four figures. `credit_limit_cents` is the maximum permitted exposure, set at onboarding. `outstanding_balance_cents` accumulates posted charges — quote acceptances, final rental bills, and lease settlements — and starts at 0. `credit_holds_cents` sums the provisional estimates attached to that customer's `RESERVED` rental contracts and likewise starts at 0. `available_credit_cents` is derived as `credit_limit_cents` minus `outstanding_balance_cents` minus `credit_holds_cents`, and it is the figure every credit gate consults.

Whenever a posting raises `outstanding_balance_cents` to strictly more than `credit_limit_cents`, the customer's `account_status` flips from `ACTIVE` to `CREDIT_HOLD`. The flip is itself a cascade trigger: every rental contract of that customer still in `RESERVED` status is automatically cancelled and its credit hold is released from `credit_holds_cents`. While a customer is on `CREDIT_HOLD`, the rental desk is closed to them — both creating a reservation and checking out a unit are rejected with `ERR_ACCOUNT_CREDIT_HOLD`.

### 2.11. The Unit's Two Independent Posture Dimensions

A forklift unit's condition is tracked on two parallel state dimensions that evolve independently. The first, `availability_status`, records where the unit sits in the commercial lifecycle: `AVAILABLE`, `ON_RENT`, `IN_SHOP`, `IN_RECON`, `LISTED`, `SOLD`, or `ON_LEASE`. The second, `maintenance_posture`, records whether the unit is cleared to work: `PM_OK` or `PM_DUE`. The posture dimension is purely derived from the hour meter — the unit is `PM_DUE` if and only if its current `hour_meter` reading is greater than or equal to `next_pm_due_hours`, where `next_pm_due_hours` equals `last_pm_hours` plus the unit's configured `pm_interval_hours`. The boundary is inclusive: a reading of exactly `next_pm_due_hours` means the unit is due. Because the dimensions are parallel, a rule that gates on one dimension (say, checkout requiring `PM_OK`) says nothing about the other, and transitions on one never implicitly move the other except where §3 states so explicitly.

## 3. Business Logic & Workflows

### 3.1. Fleet Intake and Customer Onboarding

Before any contract can be written, the dealership onboards its counterparties and its iron. A `FleetManager` or `SalesRep` creates a customer with a `name`, a `credit_limit_cents`, and an optional `discount_pct` that defaults to 0 and must be at least 0 and strictly less than 1 — a contract-level discount fraction that later flows into quote pricing and rental billing. The new customer begins with `outstanding_balance_cents` and `credit_holds_cents` at 0, and its `account_status` begins `ACTIVE`.

A `FleetManager` registers each forklift with a manufacturer `serial_number` (unique across all units), a `model` code such as 8FGCU25, a `power_type` of either `BATTERY` or `LP`, and a `disposition` of `NEW_SALE`, `RENTAL_FLEET`, or `USED_SALE` that gates which contract types may ever reference the unit. The registration also fixes the commercial rates — `daily_rate_cents` (at least 1), `weekly_rate_cents`, and `monthly_rate_cents` — and the maintenance cadence `pm_interval_hours` (at least 1), expressed in hour-meter hours. From these inputs the system derives the rest: `fuel_program` mirrors `power_type` (battery units take charge and swap events, LP units take refills); `hour_meter` and `last_pm_hours` start at 0, so `next_pm_due_hours` initially equals `pm_interval_hours`; `maintenance_posture` starts `PM_OK`; `availability_status` starts `AVAILABLE`; `resale_price_cents` stays null until a reconditioning order completes with a passing quality check; and `utilization_pct_90d` starts at 0.0 pending any rental history. Reading a unit back always shows the computed posture, the current `next_pm_due_hours`, and the live utilization figure, which is recomputed on every read of the unit and on every rental-contract status change touching that unit.

### 3.2. Quoting: New Configurations and Used Units

A `SalesRep` opens a quote for a `customer_id`, choosing a `kind` of `NEW_CONFIG` (a configure-to-order new unit with attachments) or `USED_UNIT_SALE` (the sale of one specific used unit). The `unit_id` field is required when the kind is `USED_UNIT_SALE` and must be null for `NEW_CONFIG`. Every quote carries a `valid_until` deadline; acceptance is refused once the logical clock has passed it. New quotes begin in `DRAFT` with `subtotal_cents`, `discount_cents`, `tax_cents`, and `total_cents` all at 0, `revision_count` at 0, and `submitted_at` null.

While the quote is `DRAFT`, the `SalesRep` adds lines — one per attachment or configuration item — each carrying a `description`, a `qty` of at least 1, and a `unit_price_cents` of at least 0. Every line echoes its parent `quote_id` and exposes `extended_cents`, exactly `qty` times `unit_price_cents` in integer cents. Lines may be added only while the quote is `DRAFT`; attempting to add one to a quote in any later state is rejected with `ERR_INVALID_STATE`. Each line creation recomputes the parent quote's pricing.

Quote pricing follows a pinned evaluation order. First the system sums every line's `extended_cents` into `subtotal_cents`. Then it selects a volume tier on that subtotal: ten percent when the subtotal is at least 500000 cents ($5,000), five percent when it is at least 100000 cents ($1,000) but below the higher threshold, and nothing below that — the tier boundaries are inclusive. The discount is computed exactly once, at the quote level, as the subtotal times the tier fraction rounded half up to whole cents, and stored as `discount_cents`; rounding the discount per line and summing those roundings is a different algorithm and is not the specification. (To see the difference, consider three lines extending 99980, 10, and 10 cents: the quote-level discount is 5000 cents, while per-line rounding would yield 5001.) Next, `tax_cents` is the discounted amount — subtotal minus discount — times eight percent, rounded half up to whole cents. Finally `total_cents` is the subtotal minus the discount plus the tax. These computed figures are visible whenever the quote is read.

Submitting moves the quote from `DRAFT` to `SUBMITTED` and stamps `submitted_at` with the logical clock; a quote with zero lines cannot be submitted and is rejected with `ERR_QUOTE_EMPTY`. A submitted quote can be pulled back for revision at any time — revising returns it from `SUBMITTED` to `DRAFT`, increments `revision_count` by 1, and clears `submitted_at` back to null — and this submit–revise loop may repeat any number of times.

Acceptance is the point of no return, moving a `SUBMITTED` quote to `ACCEPTED`. The checks run in the ladder order of §2.6: the quote must be in a state that permits acceptance; the customer must have at least one operator holding a certification with status `ACTIVE`, otherwise the accept is rejected with `ERR_NO_CERTIFIED_OPERATOR`; the logical clock must be on or before `valid_until`, otherwise `ERR_QUOTE_EXPIRED`; for a `USED_UNIT_SALE` quote the referenced unit must currently be `LISTED`, otherwise `ERR_UNIT_NOT_LISTED`; and `total_cents` must fit within the customer's `available_credit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED`. On success, the quote's `total_cents` is posted to the customer's `outstanding_balance_cents`, which may in turn flip the account to `CREDIT_HOLD` per §2.10. For a used-unit sale there is a second cascade: the referenced unit moves from `LISTED` to `SOLD`, becomes unreferenceable by any new contract, and thereafter rejects meter readings and fuel events with `ERR_INVALID_STATE`. Should the logical clock advance past `valid_until` while the quote still sits in `SUBMITTED`, the expiry sweep moves it to `EXPIRED` instead, and it is no longer acceptable. Both `ACCEPTED` and `EXPIRED` are terminal.

### 3.3. The Rental Desk: Reservation, Checkout, and Return

A `RentalCoordinator` reserves a unit by supplying `unit_id`, `customer_id`, a `start_date`, an `end_date` strictly later than the start, and the OCC field `expected_unit_version` described in §2.8. The window is half-open: it includes the start date and excludes the end date, and `scheduled_days` is the whole number of days between them. That length determines the `rate_tier`: `DAILY` when the window is shorter than 7 days, `WEEKLY` when it is at least 7 but fewer than 28 days, and `MONTHLY` when it runs 28 days or longer.

Reservation enforces a battery of gates in the §2.6 order. The unit must exist; its `availability_status` must be `AVAILABLE` or `ON_RENT` (a unit already out can be pre-booked for a future window), else `ERR_UNIT_NOT_AVAILABLE`; the `expected_unit_version` must match the unit's current `version`, else `ERR_STALE_VERSION`; the unit's `disposition` must be `RENTAL_FLEET`, else `ERR_UNIT_DISPOSITION_MISMATCH`; the requested window must not intersect any other contract on the same unit whose status is `RESERVED` or `ON_RENT` — because windows are half-open, pure adjacency (one contract's end equaling another's start) is allowed, and `CANCELLED` or `RETURNED` contracts never block — else `ERR_RENTAL_WINDOW_OVERLAP`; the customer's `account_status` must be `ACTIVE`, else `ERR_ACCOUNT_CREDIT_HOLD`; and the provisional estimate must fit within `available_credit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`.

The provisional estimate is a forward-looking projection of the scheduled window. On the `DAILY` tier it is the scheduled days times `daily_rate_cents`. On the `WEEKLY` tier it is the scheduled days divided by 7 and rounded up to whole weeks, times `weekly_rate_cents`. On the `MONTHLY` tier it is the scheduled days divided by 28 and rounded up to whole months, times `monthly_rate_cents`. The customer's `discount_pct` is then applied to that tier amount with round-half-up to whole cents, and the result is floored at one `daily_rate_cents` — a reservation never holds less than a single day's rent. The resulting `provisional_estimate_cents` is placed on the customer as a credit hold: `credit_holds_cents` increases by exactly that amount. Creating the reservation also increments the unit's `version` by 1, and the contract begins life in `RESERVED` with `checkout_hours`, `return_hours`, `actual_return_date`, and `final_charge_cents` all null.

Checkout moves a `RESERVED` contract to `ON_RENT`. Three gates apply, again in ladder order: the unit must currently be `AVAILABLE` (note the asymmetry with reservation, which tolerates `ON_RENT`; the desk can only hand over a physically present unit), else `ERR_UNIT_NOT_AVAILABLE`; the unit's `maintenance_posture` must be `PM_OK` — a `PM_DUE` unit may not go out the door and the attempt is rejected with `ERR_PM_OVERDUE`; and the customer's account must still be `ACTIVE`, else `ERR_ACCOUNT_CREDIT_HOLD`. On success the system captures `checkout_hours` from the unit's current `hour_meter`, and the unit's availability moves from `AVAILABLE` to `ON_RENT`.

Return is the richest transaction on the desk. The coordinator reports a `return_date` and a `return_hours` reading; the latter must be strictly greater than the unit's current `hour_meter`, else the return is rejected with `ERR_HOUR_METER_REGRESSION`. The contract records `return_hours` and `actual_return_date`, settles its billing (below), and moves from `ON_RENT` to `RETURNED`. Final billing is chronological and actual. `actual_days` is the whole days from `start_date` to `actual_return_date`, and any days beyond the scheduled window are overage days — zero when the unit comes back early or on time. The tier portion is billed on the scheduled window: `DAILY` is scheduled days times the daily rate; `WEEKLY` is the whole weeks in the scheduled window (days divided by 7, rounded down) times the weekly rate, plus the leftover days at the daily rate with that leftover charge capped at one weekly rate; `MONTHLY` is the whole 28-day months in the scheduled window times the monthly rate, plus the remaining days priced as whole weeks rounded up at the weekly rate with that remainder capped at one monthly rate. The discount applies only to this tier portion, rounded half up to whole cents. Overage days are never discounted: each costs one and a half times the daily rate, with that single-day overage figure rounded half up to whole cents once and then multiplied by the number of overage days. The sum of discounted tier and undiscounted overage is `final_charge_cents`. Because the provisional and final variants price the weekly tier differently — the provisional rounds a partial week up to a full week while the final charges full weeks plus capped leftover days — identical schedule data yields different numbers: a 10-day reservation on a unit at 15000 cents per day and 70000 cents per week holds 140000 cents provisionally but bills 115000 cents at return when the unit comes back on schedule.

Three cascades fire at return. Financially, the provisional hold is released from `credit_holds_cents` and `final_charge_cents` is posted to `outstanding_balance_cents` (which may flip the account per §2.10). Mechanically, the unit's `hour_meter` is set to `return_hours`, and if that reading is greater than or equal to `next_pm_due_hours` the unit's `maintenance_posture` flips to `PM_DUE`; when the posture becomes `PM_DUE`, the system automatically opens a service call with `call_type` `PM`, the contract's customer, `priority` `STANDARD`, an empty `required_parts` list, `auto_created` set to true, and status `OPEN`. Finally, the unit's availability moves to `IN_SHOP` if the posture flipped to `PM_DUE`, or back from `ON_RENT` to `AVAILABLE` if it stayed `PM_OK`.

Cancellation moves a `RESERVED` contract to `CANCELLED` and releases its provisional hold from `credit_holds_cents`. A coordinator can cancel directly, and the system cancels automatically when the customer flips to `CREDIT_HOLD` — in both cases the hold release is identical. `RETURNED` and `CANCELLED` are terminal.

Fleet utilization is derived from this rental history. For each unit, the system considers the trailing window of 90 calendar days ending at the logical clock, half-open at the right edge, and sums the rented days contributed by contracts in `ON_RENT` or `RETURNED` status. A returned contract contributes the whole days between the later of its `start_date` and the window start, and the earlier of its `actual_return_date` and the clock — never less than zero. An on-rent contract contributes the whole days between the later of its `start_date` and the window start, and the clock — again never less than zero. Dividing the summed rented days by 90 and multiplying by 100, then rounding half up to one decimal place, yields `utilization_pct_90d`; a unit with no qualifying contracts reports 0.0.

### 3.4. Hour-Meter Telemetry, Planned Maintenance, and the Energy Program

Hour-meter readings flow in from telematics under `FleetManager` authority. Each reading names a `reading_hours` value and may carry an optional `note`; the value must be strictly greater than the unit's current `hour_meter`, else the reading is rejected with `ERR_HOUR_METER_REGRESSION`. Every recorded reading echoes its parent `unit_id`, advances the unit's `hour_meter` to the new value, and re-evaluates the planned-maintenance threshold of §2.11: if the meter has reached or passed `next_pm_due_hours`, posture flips from `PM_OK` to `PM_DUE` and the system opens an automatic PM service call (status `OPEN`, `auto_created` true, `priority` `STANDARD`, empty `required_parts`), exactly as in the return cascade — with one exception: when the meter advance came from a PM resolution itself, no new automatic call is created. Meter readings against a `SOLD` unit are rejected with `ERR_INVALID_STATE`.

The energy program prices replenishment differently depending on the unit's `fuel_program`, and the two programs are not interchangeable: an event type that does not match the unit's program is rejected with `ERR_FUEL_PROGRAM_MISMATCH`. A `FleetManager` or `Technician` records a fuel event with an `event_type`, plus `kwh` or `cylinders` as appropriate — each defaults to 0 and must be at least 0. On a `BATTERY` unit, a `CHARGE` event costs the metered `kwh` times 12 cents per kilowatt-hour, rounded half up to whole cents; a `SWAP` event adds a flat 2500-cent exchange fee on top of the same metered energy charge. On an `LP` unit, an `LP_REFILL` costs 4500 cents per cylinder exchanged times `cylinders`, plus a flat 1500-cent delivery fee. The computed `cost_cents` lands on the fuel event record, which echoes its parent `unit_id`. A 100-kWh charge therefore costs 1200 cents, while a two-cylinder LP refill costs 10500 cents — the same replenishment intent priced by two different algorithms. Fuel events against a `SOLD` unit are rejected with `ERR_INVALID_STATE`.

### 3.5. Service Dispatch: Van Stock, Buffered Windows, and Resolution

A `ServiceDispatcher` opens a service call with a `unit_id`, a `customer_id`, a `call_type` of `BREAKDOWN` or `PM`, a `priority` of `EMERGENCY` or `STANDARD`, a `required_parts` list of part numbers and quantities (each entry a `part_number` with a `qty` of at least 0), and optionally an `operator_id` naming the customer's operator who will run the unit during repair verification. A manually opened call begins `OPEN` with `technician_id`, `scheduled_start`, `scheduled_end`, and `used_parts` all null and `auto_created` false. (The automatically created PM calls of §3.3 and §3.4 arrive with `auto_created` true and no parts.)

Dispatch assigns the work. The dispatcher supplies a `technician_id` and a window from `scheduled_start` to `scheduled_end`, moving the call from `OPEN` to `DISPATCHED`. The gates run in ladder order: if an `operator_id` is present on the call, that operator must hold at least one certification with status `ACTIVE` at dispatch time, else `ERR_OPERATOR_CERT_EXPIRED`; the named technician's `status` must be `ACTIVE`, else `ERR_TECHNICIAN_INACTIVE`; the technician's `van_stock` must cover every required part — for each `part_number` and `qty` in `required_parts`, the van's entry must hold at least that quantity — else `ERR_VAN_STOCK_INSUFFICIENT`; and the dispatch window, expanded by 60 minutes on both sides and treated as a closed interval, must not intersect any other `DISPATCHED` call's identically expanded closed interval for the same technician, else `ERR_DISPATCH_WINDOW_OVERLAP`. A successful dispatch records `technician_id`, `scheduled_start`, and `scheduled_end` on the call, decrements the technician's `van_stock` by the required quantities (the parts are loaded onto the job), and — if the unit under service was `AVAILABLE` — moves it to `IN_SHOP`.

Release backs a dispatched call out, returning it from `DISPATCHED` to `OPEN`: the required parts go back onto the van, `technician_id`, `scheduled_start`, and `scheduled_end` are cleared to null, and if this call had moved the unit to `IN_SHOP` the unit returns to `AVAILABLE`. The release-and-redispatch loop may repeat as often as scheduling demands.

Resolution closes the work and is performed by the assigned technician — and only the assigned technician, per the identity rule of §2.1; anyone else is rejected with `ERR_UNAUTHORIZED`. The technician reports `used_parts`, the parts actually consumed, and each used quantity must be no more than the dispatched quantity for that part, else the resolve is rejected with `ERR_INVALID_REQUEST`. The call records `used_parts` and moves from `DISPATCHED` to `CLOSED`, the dispatched-but-unused remainder of each part returns to the technician's `van_stock`, and if this call had moved the unit to `IN_SHOP` the unit returns to `AVAILABLE`. When the resolved call is a PM call, one more cascade runs: the unit's `last_pm_hours` is set to its current `hour_meter`, the `maintenance_posture` clears from `PM_DUE` to `PM_OK`, and `next_pm_due_hours` is recomputed as the new `last_pm_hours` plus `pm_interval_hours`.

Technician administration sits with the dispatcher as well. A technician is created with a `full_name`, a `home_branch` code, and an optional initial `van_stock` that defaults to an empty inventory; their `status` begins `ACTIVE`. Restocking adds a `qty` to the van's count for a `part_number`, creating the entry when the van does not yet carry that part. Deactivation moves a technician from `ACTIVE` to `INACTIVE`, which bars them from new dispatches.

### 3.6. Operator Training and Certification

Customer personnel who will operate equipment must be registered and credentialed, and the `TrainingRegistrar` owns both records. An operator is registered under a `customer_id` with a `full_name` and a `badge_number`. Certifications are then issued under the operator — the record echoes its parent `operator_id` — with a `cert_class` of `SIT_DOWN`, `STAND_UP`, or `ORDER_PICKER`, and an `expires_at` that must be after the logical clock at issuance, else the request is rejected with `ERR_INVALID_REQUEST`. The system stamps `issued_at` with the logical clock, sets `renewed_count` to 0, and starts the certification `ACTIVE`.

Renewal extends a credential's life: given a `new_expires_at` later than the logical clock (else `ERR_INVALID_REQUEST`), the registrar can renew a certification whether it is currently `ACTIVE` or already `EXPIRED`; in both cases `expires_at` moves to the new instant, `renewed_count` increments by 1, and the status becomes `ACTIVE`. Revocation works from either `ACTIVE` or `EXPIRED` and moves the certification to `REVOKED`, which is terminal. And as §2.9 describes, advancing the logical clock past a certification's `expires_at` sweeps it from `ACTIVE` to `EXPIRED` without any manual action. Two downstream gates lean on these statuses: quote acceptance requires the buying customer to have at least one operator holding an `ACTIVE` certification, and dispatching a service call that names an `operator_id` requires that operator to hold at least one `ACTIVE` certification at dispatch time.

### 3.7. Lease Origination, Return Inspection, and Settlement

A `LeaseManager` originates a lease with a `unit_id`, a `customer_id`, a `start_date`, an `end_date` strictly later than the start, an `allowed_hours` contractual hour allowance (at least 0), an `excess_hour_rate_cents` charge per excess hour (at least 0), and a `residual_value_cents` contractual residual at lease end (at least 0). Two gates guard creation: the unit must be `AVAILABLE`, else `ERR_UNIT_NOT_AVAILABLE`, and its `disposition` must be `NEW_SALE` or `RENTAL_FLEET`, else `ERR_UNIT_DISPOSITION_MISMATCH`. On success the unit moves from `AVAILABLE` to `ON_LEASE`, and the lease begins `ACTIVE` with `return_date` null and `settlement_total_cents` null until settlement.

Recording the lease return — with a `return_date` — moves the lease from `ACTIVE` to `RETURNED` and works two changes on the unit: its availability moves from `ON_LEASE` back to `AVAILABLE`, and its `disposition` flips to `USED_SALE`, feeding the used-equipment pipeline of §3.8.

Inspection then documents the returned unit's condition. Recording an inspection requires the lease to be `RETURNED`; against a lease in any other state the attempt is rejected with `ERR_INVALID_STATE`. The inspector reports a `condition_grade` of `A`, `B`, `C`, or `D`, the `hours_at_return` meter reading (at least 0), and an `appraised_value_cents` market value (at least 0). The inspection record echoes its parent `lease_id` and carries a computed `wear_charge_cents` read straight from the grade: 0 cents for grade `A`, 150000 cents for `B`, 400000 cents for `C`, and 900000 cents for `D`. An inspection begins `SUBMITTED`; approving it moves it to `APPROVED`. At most one inspection per lease may be `APPROVED` — approving a second while an approved inspection already exists for that lease is rejected with `ERR_INVALID_STATE`.

Settlement converts the approved inspection into money, moving the lease from `RETURNED` to `SETTLED`. Per §2.6, a lease that is not `RETURNED` fails with `ERR_INVALID_STATE`, while a returned lease lacking an approved inspection fails with `ERR_INSPECTION_NOT_APPROVED`. The settlement assembles three components from the single approved inspection. Excess hours cost the amount by which `hours_at_return` exceeds `allowed_hours` — zero when the unit came back under allowance — times `excess_hour_rate_cents`. Wear is the grade's `wear_charge_cents`. Residual shortfall is `residual_value_cents` minus `appraised_value_cents`, floored at zero when the appraisal meets or beats the residual. Those three components sum to a pre-discount total, and the loyalty tier is selected on that pre-discount figure: ten percent when it is at least 500000 cents, five percent when it is at least 200000 cents but below the higher threshold, and nothing below that, with inclusive boundaries. The `settlement_total_cents` is then the pre-discount total times one minus the tier fraction, rounded half up to whole cents. The evaluation order is pinned: components first, then the sum, then the tier, then the discount — the tier is never re-derived from the discounted result, even when the discount pulls the total back below the threshold that earned it (a 520000-cent pre-discount total settles at 468000 cents under the ten-percent tier, not at 494000 cents under a wrongly re-derived five-percent tier).

Settlement posts `settlement_total_cents` to the customer's `outstanding_balance_cents`. When that posting pushes the balance strictly beyond `credit_limit_cents`, the `account_status` flips to `CREDIT_HOLD`, and the flip in turn auto-cancels every `RESERVED` rental contract the customer holds, releasing each one's credit hold — the three-link cascade from settlement to account status to the rental book, per §2.10.

### 3.8. Reconditioning and Resale of Off-Lease Iron

Used units — trade-ins and the off-lease returns of §3.7 — flow through reconditioning before they can be sold. A `FleetManager` opens a reconditioning order against a `unit_id`, with optional `notes` describing the work scope. Two gates apply: the unit's `disposition` must be `USED_SALE`, else `ERR_UNIT_DISPOSITION_MISMATCH`, and it must be `AVAILABLE`, else `ERR_UNIT_NOT_AVAILABLE`. The order begins `IN_PROGRESS` with `qc_fail_count` at 0 and `listing_price_cents` null, and the unit moves from `AVAILABLE` to `IN_RECON`.

Completion is a quality-control disposition. Completing with a `qc_result` of `FAIL` is a rework loop: the order stays `IN_PROGRESS` and `qc_fail_count` increments by 1, ready for another attempt. Completing with a `qc_result` of `PASS` requires `listing_price_cents` to be present, else the request is rejected with `ERR_INVALID_REQUEST`; on success the order moves to `COMPLETED`, the price is recorded on the order, the unit moves from `IN_RECON` to `LISTED`, and the unit's own `resale_price_cents` is set to the same figure. `COMPLETED` is terminal for the order.

A `LISTED` unit is sellable inventory: a `USED_UNIT_SALE` quote referencing it can be accepted per §3.2, which moves the unit from `LISTED` to `SOLD` and posts the quote total to the buyer's balance. `SOLD` is the terminal point of the unit's availability lifecycle — the unit can no longer be referenced by new contracts, and meter readings and fuel events against it are rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Request bodies, computed fields, side effects, and the gates guarding each operation are defined in §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fleet/customers` | Create a customer | FleetManager, SalesRep |
| GET | `/fleet/customers/{id}` | Read a customer including computed credit fields | All roles |
| GET | `/fleet/customers/{id}/operators` | List operators of a customer | All roles |
| POST | `/fleet/units` | Create a forklift unit | FleetManager |
| GET | `/fleet/units/{id}` | Read a unit including computed posture, next_pm_due_hours, utilization_pct_90d | All roles |
| POST | `/fleet/units/{id}/meter-readings` | Record an hour-meter reading; may cross the PM threshold | FleetManager |
| GET | `/fleet/units/{id}/meter-readings` | List meter readings of a unit | All roles |
| POST | `/fleet/units/{id}/fuel-events` | Record a charge / battery swap / LP refill with program-specific cost | FleetManager, Technician |
| GET | `/fleet/units/{id}/fuel-events` | List fuel events of a unit | All roles |
| POST | `/fleet/quotes` | Create a quote (NEW_CONFIG or USED_UNIT_SALE) | SalesRep |
| GET | `/fleet/quotes/{id}` | Read a quote including computed totals | All roles |
| GET | `/fleet/quotes` | List/filter quotes | All roles |
| POST | `/fleet/quotes/{id}/lines` | Add an attachment/configuration line (DRAFT quotes only) | SalesRep |
| GET | `/fleet/quotes/{id}/lines` | List lines of a quote | All roles |
| POST | `/fleet/quotes/{id}/submit` | Submit a draft quote | SalesRep |
| POST | `/fleet/quotes/{id}/revise` | Pull a submitted quote back to DRAFT for revision | SalesRep |
| POST | `/fleet/quotes/{id}/accept` | Accept a submitted quote | SalesRep |
| POST | `/fleet/rental-contracts` | Create a rental reservation (OCC on unit version) | RentalCoordinator |
| GET | `/fleet/rental-contracts/{id}` | Read a rental contract | All roles |
| GET | `/fleet/rental-contracts` | List/filter rental contracts | All roles |
| POST | `/fleet/rental-contracts/{id}/checkout` | Check out a reserved unit onto rent | RentalCoordinator |
| POST | `/fleet/rental-contracts/{id}/return` | Return a rented unit; final billing plus PM cascade | RentalCoordinator |
| POST | `/fleet/rental-contracts/{id}/cancel` | Cancel a reservation; releases the credit hold | RentalCoordinator |
| POST | `/fleet/service-calls` | Open a service call (breakdown or PM) | ServiceDispatcher |
| GET | `/fleet/service-calls/{id}` | Read a service call | All roles |
| GET | `/fleet/service-calls` | List/filter service calls | All roles |
| POST | `/fleet/service-calls/{id}/dispatch` | Assign a technician and window; loads required parts onto the job | ServiceDispatcher |
| POST | `/fleet/service-calls/{id}/release` | Release a dispatched call back to OPEN; parts return to the van | ServiceDispatcher |
| POST | `/fleet/service-calls/{id}/resolve` | Close a dispatched call; assigned technician only | Technician |
| POST | `/fleet/technicians` | Create a technician with initial van stock | ServiceDispatcher |
| GET | `/fleet/technicians/{id}` | Read a technician including current van stock | All roles |
| POST | `/fleet/technicians/{id}/van-stock` | Restock: add quantity to a part on the van | ServiceDispatcher |
| POST | `/fleet/technicians/{id}/deactivate` | Deactivate a technician | ServiceDispatcher |
| POST | `/fleet/operators` | Register a customer operator | TrainingRegistrar |
| GET | `/fleet/operators/{id}` | Read an operator | All roles |
| POST | `/fleet/operators/{id}/certifications` | Issue a certification to an operator | TrainingRegistrar |
| GET | `/fleet/operators/{id}/certifications` | List certifications of an operator | All roles |
| POST | `/fleet/certifications/{id}/renew` | Renew a certification (ACTIVE or EXPIRED) to a new expiry | TrainingRegistrar |
| POST | `/fleet/certifications/{id}/revoke` | Revoke a certification | TrainingRegistrar |
| POST | `/fleet/lease-contracts` | Create a lease; unit goes ON_LEASE | LeaseManager |
| GET | `/fleet/lease-contracts/{id}` | Read a lease contract | All roles |
| GET | `/fleet/lease-contracts` | List/filter lease contracts | All roles |
| POST | `/fleet/lease-contracts/{id}/return` | Record lease return; unit becomes USED_SALE inventory | LeaseManager |
| POST | `/fleet/lease-contracts/{id}/inspections` | Record a lease-end condition inspection (lease must be RETURNED) | LeaseManager |
| GET | `/fleet/lease-contracts/{id}/inspections` | List inspections of a lease | All roles |
| POST | `/fleet/inspections/{id}/approve` | Approve an inspection (at most one APPROVED per lease) | LeaseManager |
| POST | `/fleet/lease-contracts/{id}/settle` | Settle a returned lease from its approved inspection | LeaseManager |
| POST | `/fleet/reconditioning-orders` | Open a reconditioning order for a USED_SALE unit | FleetManager |
| GET | `/fleet/reconditioning-orders/{id}` | Read a reconditioning order | All roles |
| GET | `/fleet/reconditioning-orders` | List/filter reconditioning orders | All roles |
| POST | `/fleet/reconditioning-orders/{id}/complete` | QC disposition: PASS lists the unit for resale; FAIL loops back for rework | FleetManager |
| POST | `/_clock/set_current_utc` | Set the logical clock; fires quote and certification expiry sweeps | FleetManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PM_OVERDUE` | 422 |
| `ERR_NO_CERTIFIED_OPERATOR` | 422 |
| `ERR_OPERATOR_CERT_EXPIRED` | 422 |
| `ERR_UNIT_DISPOSITION_MISMATCH` | 422 |
| `ERR_TECHNICIAN_INACTIVE` | 422 |
| `ERR_QUOTE_EMPTY` | 422 |
| `ERR_VAN_STOCK_INSUFFICIENT` | 422 |
| `ERR_FUEL_PROGRAM_MISMATCH` | 422 |
| `ERR_HOUR_METER_REGRESSION` | 422 |
| `ERR_RENTAL_WINDOW_OVERLAP` | 409 |
| `ERR_DISPATCH_WINDOW_OVERLAP` | 409 |
| `ERR_QUOTE_EXPIRED` | 422 |
| `ERR_UNIT_NOT_LISTED` | 422 |
| `ERR_ACCOUNT_CREDIT_HOLD` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_INSPECTION_NOT_APPROVED` | 409 |
