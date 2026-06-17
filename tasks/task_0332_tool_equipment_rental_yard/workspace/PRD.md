# Tool & Equipment Rental Yard API — Product Requirements Document

## 1. Introduction

The Tool & Equipment Rental Yard API powers the back-office and counter operations of a rental business that lends out everything from hand tools to heavy excavators. The system manages a physical fleet of individually tracked units, a pricing catalog that drives daily, weekly, and four-week block rates, contractor accounts with credit limits and ledgered balances, and the full lifecycle of a rental — from a forward-looking reservation, through pickup or truck-based delivery, to the return inspection that finalizes fuel, cleaning, damage, and late charges.

Operationally, the yard must reconcile two competing pressures: keeping equipment earning revenue and keeping it safe and serviceable. A single physical unit may carry many future bookings for non-overlapping intervals while it sits available in the yard, yet the moment it goes out on rent — or is pulled for maintenance — every downstream pricing, availability, and accounting consequence must cascade correctly. This document specifies the entities, lifecycle state machines, tiered pricing and charge calculations, validation ordering, role permissions, endpoints, and error semantics that together guarantee a contractor is never double-charged, a unit is never double-booked, and the account ledger always reflects the true outstanding balance.

Because rental timing is central to nearly every rule, the system runs against a simulated yard clock rather than real wall-clock time. All "today" comparisons — whether a reservation starts in the past, how many days a unit is overdue — read from this controllable clock, allowing deterministic test-driving of multi-day rental scenarios.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, headers, envelopes, and cross-cutting principles that govern every endpoint. Where a rule references a specific charge or transition, the detailed business narrative lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request that mutates state must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the action is taken. Read-only `GET` endpoints are public and do not require these headers; every write endpoint does. A write request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly four roles, spelled precisely as follows: `YardManager`, `RentalAgent`, `Contractor`, and `Inspector`. When a request carries valid headers but the role is not permitted to perform the requested operation per the role matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

- A `YardManager` owns the catalog, pricing, equipment registration, contractor-account opening and suspension, delivery trucks, maintenance, and the test-driving clock. When `X-User-Role` is `YardManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `RentalAgent` is the front-counter operator who creates reservations, dispatches and picks up units, and marks returns. When `X-User-Role` is `RentalAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- An `Inspector` performs the return inspections that finalize charges and close agreements. When `X-User-Role` is `Inspector`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- A `Contractor` is a customer acting on their own account. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorAccount`; ownership checks on any resource that references a `ContractorAccount` compare the resource's `contractor_account_id` to `X-User-ID`. Specifically, when a `Contractor` creates a reservation, cancels a reservation, reads their own account, or pays down a balance, the targeted reservation or account must belong to them — its `contractor_account_id` must equal `X-User-ID`. A mismatch is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and may not be negative. A request whose `limit` is below 1, whose `limit` exceeds 100, or whose `offset` is below 0 is rejected with `ERR_VALIDATION_LIMIT` (HTTP 400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. The account ledger listing and the agreement-scoped ledger listing also return entries in `created_at` ascending order, which is the chronological order in which charges and payments were posted.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Most resources carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and is never supplied by the client. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp that is refreshed on every mutation, including cascaded mutations the server performs on the resource's behalf. The `version` field is an integer that starts at 1 on creation and increments by exactly one on every mutation.

Three entities are append-only or singleton records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version` field at all. These are the `DamageCharge` (an immutable record of an assessed damage), the `AccountLedgerEntry` (an append-only ledger line), and the `YardClock` (the singleton simulated clock). For these three, neither `updated_at` nor `version` is present on the persisted row or in the response. All other entities — `RateCard`, `RentalCatalogItem`, `EquipmentUnit`, `ContractorAccount`, `DeliveryTruck`, `Reservation`, `RentalAgreement`, `ReturnInspection`, and `MaintenanceTicket` — carry the full `id`/`created_at`/`updated_at`/`version` set.

### 2.5. Nested Resource Retrieval and Reference Validation

Several read endpoints address resources by an owning entity's id in the path and then list related rows — an account's ledger, an account's reservations, an agreement's ledger entries. For any request that references resources by id, whether in the path or the body, the server validates existence left to right in the order the identifiers appear and rejects the first missing reference with `ERR_NOT_FOUND` (HTTP 404). Concretely, the references checked include `rate_card_id`, `catalog_item_id`, `equipment_unit_id`, `contractor_account_id`, `reservation_id`, and `rental_agreement_id`; the first one that does not resolve to an existing resource produces the 404, before any later reference or business rule is evaluated.

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are stored and returned as integer cents — `daily_rate_cents`, `deposit_cents`, `estimated_total_cents`, `final_total_cents`, `amount_cents`, and every other `_cents` field. The tiered block decomposition of a rental charge and the summation of the account balance are exact integer arithmetic and require no rounding. The only calculation that can produce a fractional intermediate is the late fee, because `late_fee_multiplier` may be fractional (for example, 1.5); the late fee is rounded half up to whole cents. Wherever rounding is required, the method is round half up.

### 2.7. The Yard Clock and Temporal Rules

The yard runs on a simulated clock rather than real time. A singleton `YardClock` holds `current_utc`, the simulated current wall clock, which defaults to `1970-01-01T00:00:00.000Z` until set. Every date comparison in the system — whether a reservation's start is in the past, whether a unit may be dispatched yet, how many overdue days an agreement has accrued — reads the date portion of `current_utc`. An admin-only test-driving capability sets the clock to a supplied instant; the request body carries `to_iso8601`, and the server assigns `current_utc` to that value. Date-only rental fields (`rental_start_date`, `rental_end_date`) are `YYYY-MM-DD` strings, and comparisons against "today" use the date portion of the clock.

### 2.8. Equipment Availability and Service Integrity

A physical `EquipmentUnit` carries an `availability_state` that is the single source of truth for whether it can go on rent right now: `AVAILABLE` means present in the yard and bookable, `ON_RENT` means live on a rental, and `OUT_OF_SERVICE` means pulled for maintenance. A crucial distinction governs the whole booking model: confirming a reservation does **not** change `availability_state`. A unit may simultaneously hold many future reservations for non-overlapping intervals while remaining `AVAILABLE`. Only dispatch or pickup actually moves the physical unit to `ON_RENT`, and only a return inspection or a maintenance resolution moves it back.

Whenever the server changes a unit's `availability_state` — on dispatch, on pickup, on cancel, on return inspection, on a manual maintenance pull, or on a maintenance resolution — it also refreshes that unit's `updated_at` and increments its `version` by one. The same `updated_at`/`version` discipline applies to every entity the server mutates as a side effect of an operation: when a reservation cancel reverses a deposit and frees the unit, when a return inspection closes an agreement and posts ledger lines, each touched resource independently has its `updated_at` refreshed and its `version` incremented (for the entities that carry `version`).

The catalog exposes two computed counts that the server recomputes whenever asked: `unit_count` is the number of `EquipmentUnit` rows whose `catalog_item_id` points at the catalog item, in any availability state; `available_unit_count` is the number of those units whose `availability_state` is `AVAILABLE`. A newly created catalog item has both counts at zero.

### 2.9. The Account Ledger as Source of Truth

A `ContractorAccount`'s `outstanding_balance_cents` is never stored as a free-standing mutable number; it is a full recompute over the account's ledger. Every charge, hold, refund, and payment is an append-only `AccountLedgerEntry` carrying a signed `amount_cents`. Whenever any ledger entry is inserted, the server recomputes the balance from scratch as the sum of `amount_cents` across all `AccountLedgerEntry` rows whose `contractor_account_id` equals the account's `id`, taken in `created_at` ascending order. Charges and holds — `DEPOSIT_HOLD`, `RENTAL_CHARGE`, `FUEL_CHARGE`, `CLEANING_CHARGE`, `LATE_FEE`, and `DAMAGE_CHARGE` — are positive and increase the balance; refunds and payments — `DEPOSIT_REFUND` and `PAYMENT` — are negative and decrease it. The `entry_type` enumerates exactly these eight kinds. The account also exposes `open_reservation_count`, a computed count of the account's reservations whose `reservation_state` is one of `CONFIRMED`, `DISPATCHED_DELIVERY`, `PICKED_UP`, or `ON_RENT`.

### 2.10. Optimistic Concurrency and Conflicting Writes

This domain has no version-token optimistic-concurrency field on any write endpoint. Conflicting writes are instead serialized by state preconditions and temporal-overlap checks evaluated against the committed state at the moment a request is processed. A second reservation on the same unit and overlapping interval is rejected by the double-booking check; a second dispatch, pickup, cancel, return, or inspection on a resource whose state has already advanced is rejected by the state precondition; a second delivery window that collides on the same truck is rejected by the truck-overlap check. No request body carries an expected-version field, and the server performs no version-match rejection.

## 3. Business Logic & Workflows

### 3.1. Pricing Foundations: Rate Cards and the Catalog

Everything the yard charges flows from a `RateCard`, created by a `YardManager`. A rate card is given a human `name` (1 to 80 characters, required) and the full schedule of block rates: `daily_rate_cents`, the charge for each rental-day not absorbed by a larger block; `weekly_rate_cents`, the flat charge for each whole seven-day block; and `four_week_rate_cents`, the flat charge for each whole twenty-eight-day block. It also fixes the financial parameters of a rental: `deposit_cents`, the refundable security deposit held when an agreement opens; `damage_waiver_daily_cents`, the per-rental-day surcharge charged when a contractor purchases the optional damage waiver; `fuel_refill_cents_per_liter`, the per-liter charge to top a tank back up at return; `cleaning_fee_cents`, the flat fee when a unit comes back dirty; and `late_fee_multiplier`, the multiplier applied to the daily rate for each whole overdue day. Every monetary rate must be at least 0, and the late-fee multiplier must be at least 1.0. A newly created card is born active — its `active` flag is true — and remains referenceable by new catalog items until it is retired, at which point `active` becomes false.

A `RentalCatalogItem`, also created by a `YardManager`, binds a pricing card to a class of equipment. It references its `rate_card_id`, which must point at a card that is active at the moment of creation. Each item carries a `sku` (required, unique across all catalog items, 1 to 40 characters), a display `name` (required, 1 to 120 characters), and a `category` that is one of `HAND_TOOL`, `POWER_TOOL`, or `HEAVY_EQUIPMENT`. The optional `requires_delivery` flag (default false) marks equipment that cannot leave by counter pickup. The `fuel_capacity_liters` value is the tank capacity in liters, at least 0, with 0 standing for non-fueled items; this capacity both sets the fuel level when a unit is dispatched full and caps the refill quantity at return. The computed `unit_count` and `available_unit_count` described in Section 2.8 round out the item. If a creation request omits a required field, supplies a bad type, or names an invalid `category`, it is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a duplicate `sku` is rejected with `ERR_DUPLICATE_KEY` (HTTP 409).

### 3.2. The Fleet: Registering and Maintaining Equipment Units

A `YardManager` registers each physical machine as an `EquipmentUnit` against its `catalog_item_id`, giving it an `asset_tag` (required, unique across all units, 1 to 40 characters) and a `service_due_at_days` threshold (at least 1). A freshly registered unit is `AVAILABLE`, with `fuel_level_liters` at 0 and `lifetime_rental_days` at 0. The `fuel_level_liters` field tracks the current fuel in the tank: it is set to the catalog item's `fuel_capacity_liters` (a full tank) at dispatch or pickup, and read at return to compute any refill. The `lifetime_rental_days` field accumulates billed rental-days across all of the unit's closed agreements and is what drives the service-due threshold. A duplicate `asset_tag` is rejected with `ERR_DUPLICATE_KEY` (HTTP 409).

Equipment leaves the rentable pool in two ways. A `YardManager` may manually pull an `AVAILABLE` unit by opening a `MaintenanceTicket` against its `equipment_unit_id` with a `reason` of `SCHEDULED_SERVICE`, `DAMAGE_REPAIR`, or `INSPECTION`. This manual pull is only valid when the unit is currently `AVAILABLE`; it sets the unit's `availability_state` from `AVAILABLE` to `OUT_OF_SERVICE`, increments the unit's `version`, and creates the ticket in the `OPEN` state. A ticket also records `opened_by_agreement_id`, which is set when the ticket was auto-opened by a damaging or service-due return (see Section 3.6) and is otherwise null. Resolving a ticket is a `YardManager` action that moves it from `OPEN` to `RESOLVED`; it requires the ticket be `OPEN`, and only when no other `OPEN` `MaintenanceTicket` remains on that unit does the resolution set the unit's `availability_state` back to `AVAILABLE` and increment its `version`. A unit thus returns to the pool only when its last open ticket clears.

### 3.3. Accounts, Trucks, and Credit Standing

A `YardManager` opens a `ContractorAccount` with a `company_name` (required, 1 to 120 characters) and a `credit_limit_cents` (at least 0), the ceiling on the account's `outstanding_balance_cents`. A new account is `ACTIVE`, with `outstanding_balance_cents` and `open_reservation_count` both at 0. The `account_status` is either `ACTIVE` or `SUSPENDED`; a `YardManager` may suspend an account, which sets `account_status` to `SUSPENDED` and increments the account's `version`. A `SUSPENDED` account cannot open new reservations. Both a `YardManager` and the owning `Contractor` may record a payment against an account; a payment posts an `AccountLedgerEntry` of `entry_type` `PAYMENT` whose `amount_cents` must be strictly negative (a payment reduces the balance). A payment whose `amount_cents` is not strictly below 0 is rejected with `ERR_PAYMENT_NOT_NEGATIVE` (HTTP 422), after which the account's `outstanding_balance_cents` is recomputed.

Delivery is served by a fleet of trucks. A `YardManager` registers a `DeliveryTruck` with a `name` (required, 1 to 60 characters) and a `buffer_minutes` value (at least 0). The buffer is the drive-and-turnaround cushion enforced around every delivery window assigned to that truck: a new window must clear each existing window on the same truck by at least `buffer_minutes` on both sides, as detailed in Section 3.5.

### 3.4. Reserving Equipment

A reservation is a forward-looking booking that holds a deposit but does not yet move any physical unit. Both a `RentalAgent` and a `Contractor` may create one. The request supplies the `contractor_account_id` that will hold the booking, the `catalog_item_id` the contractor wants, an optional `equipment_unit_id` to pin a specific physical unit, a `fulfillment_method` of `PICKUP` or `DELIVERY`, an inclusive `rental_start_date` and `rental_end_date` (date-only `YYYY-MM-DD`, with the end on or after the start), and an optional `damage_waiver_opted` flag (default false). When a `Contractor` is the actor, the `contractor_account_id` must equal their `X-User-ID`, per Section 2.1.

The number of billed days over any rental interval is the inclusive day count: the end date minus the start date, in days, plus one — always at least one day. On confirmation the reservation enters the `CONFIRMED` state and the server computes a forward-looking `estimated_rental_cents` from the full planned interval (the estimate variant of the rental charge described in Section 3.8), an `estimated_total_cents`, and a `delivery_fee_cents`. The delivery fee is a flat amount keyed by the catalog item's category when `fulfillment_method` is `DELIVERY`, and 0 for `PICKUP`: 0 cents for a `HAND_TOOL`, 2500 cents for a `POWER_TOOL`, and 12000 cents for a `HEAVY_EQUIPMENT`. The `estimated_total_cents` is the sum of `estimated_rental_cents`, the estimated waiver amount, and `delivery_fee_cents`. The estimated waiver amount is `damage_waiver_daily_cents` multiplied by the planned billed days when `damage_waiver_opted` is true, and 0 otherwise.

Several checks guard reservation creation, and their relative priority matters because more than one can be true at once. They are evaluated in this order. First, after authentication and authorization, the server confirms every referenced resource exists, rejecting the first missing one with `ERR_NOT_FOUND`. Then it validates the body shape — required fields present and well-typed, valid enum members, the end date on or after the start date, amounts non-negative — rejecting a violation with `ERR_INVALID_REQUEST`. Next comes unit availability: the chosen `EquipmentUnit` must not be `OUT_OF_SERVICE`, since a unit pulled for maintenance cannot accept new bookings; a violation is `ERR_UNIT_NOT_AVAILABLE` (HTTP 409). Then fulfillment compatibility: requesting `PICKUP` for a catalog item whose `requires_delivery` is true is rejected with `ERR_DELIVERY_REQUIRED` (HTTP 422). Then the temporal-overlap check: no other active reservation or agreement on the same `EquipmentUnit` may overlap the requested inclusive `[rental_start_date, rental_end_date]` interval; this is a closed-interval test in which adjacency is not overlap, so one booking ending on the very day another begins is allowed, and a true overlap is rejected with `ERR_UNIT_DOUBLE_BOOKED` (HTTP 409). Then the past-date check: `rental_start_date` must be on or after the yard clock's current date, or the request is rejected with `ERR_START_IN_PAST` (HTTP 422). Then account standing: the `ContractorAccount` must be `ACTIVE`, with a `SUSPENDED` account rejected by `ERR_ACCOUNT_SUSPENDED` (HTTP 409). Finally the credit projection described below, rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

When `equipment_unit_id` is omitted, the server selects a unit by policy: among the `AVAILABLE` units of the named catalog item that carry no overlapping booking for the requested interval, it takes the earliest by `created_at` ascending. If that candidate pool is empty — no available unit of the item is free for the interval — the create is rejected with `ERR_NO_UNIT_AVAILABLE` (HTTP 409). Whichever unit is chosen is always recorded on the persisted `equipment_unit_id`. Confirming a reservation never changes the chosen unit's `availability_state`; it only reserves the future interval.

The credit projection is a risk check on the account, evaluated before the deposit hold is posted. The server computes a would-be balance as the account's current `outstanding_balance_cents` plus the rate card's `deposit_cents` plus the reservation's `estimated_total_cents`, and rejects the reservation when that projected balance would exceed the account's `credit_limit_cents`; the projected balance is permitted to equal the limit but not to exceed it. Once all checks pass, the server posts a `DEPOSIT_HOLD` ledger entry for the deposit amount and recomputes the account's `outstanding_balance_cents`.

A `CONFIRMED` reservation that has not yet been dispatched or picked up may be cancelled by a `RentalAgent` or by the owning `Contractor`. Cancelling moves the reservation to the terminal `CANCELLED` state and posts a `DEPOSIT_REFUND` ledger entry reversing the original deposit hold, after which the account balance is recomputed. Because confirming never changed the unit's `availability_state`, cancellation simply frees the future booking interval. Cancelling a reservation that is not `CONFIRMED` is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Going on Rent: Dispatch and Pickup

A reservation becomes a live rental through one of two mutually exclusive paths, both driven by a `RentalAgent`, and both requiring the reservation to be `CONFIRMED` and the unit to be `AVAILABLE` right now. If at the moment of dispatch or pickup the unit is not `AVAILABLE` — it is already `ON_RENT` or `OUT_OF_SERVICE` — the action is rejected with `ERR_UNIT_NOT_AVAILABLE`. Acting on a reservation that is not in a state from which the transition is defined yields `ERR_INVALID_STATE`.

For a `DELIVERY` reservation, dispatching advances the reservation `CONFIRMED → DISPATCHED_DELIVERY` and immediately onward to `ON_RENT`. The request must target a `DELIVERY` reservation — dispatching a `PICKUP` reservation is rejected with `ERR_WRONG_FULFILLMENT` (HTTP 422) — and the yard clock's current date must be on or after `rental_start_date`. The request supplies the `delivery_truck_id` to assign, plus a `delivery_window_start` and `delivery_window_end` (ISO 8601 UTC), where the end must be strictly after the start; a window whose end is not after its start is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The named truck must exist. The window is checked against the truck's existing commitments using half-open interval semantics expanded by the truck's `buffer_minutes` on each side: the requested `[delivery_window_start, delivery_window_end)` interval, padded by `buffer_minutes` before and after, must not collide with any other assigned window on the same truck — adjacency within the buffer counts as a collision. A collision is rejected with `ERR_TRUCK_DOUBLE_BOOKED` (HTTP 409). On success the server records `delivery_truck_id`, `delivery_window_start`, and `delivery_window_end` on the reservation, sets the unit `availability_state` to `ON_RENT`, sets its `fuel_level_liters` to the catalog item's `fuel_capacity_liters`, increments the unit's `version`, and opens a `RentalAgreement` in `ON_RENT`.

For a `PICKUP` reservation, the counter-pickup action advances the reservation `CONFIRMED → PICKED_UP` and immediately onward to `ON_RENT`. The request must target a `PICKUP` reservation — picking up a `DELIVERY` reservation is rejected with `ERR_WRONG_FULFILLMENT` — and the catalog item's `requires_delivery` must be false, since delivery-only equipment cannot be picked up at the counter; a pickup against a delivery-only item is rejected with `ERR_DELIVERY_REQUIRED`. The yard clock's current date must be on or after `rental_start_date`. On success the server sets the unit `availability_state` to `ON_RENT`, sets its `fuel_level_liters` to the catalog item's `fuel_capacity_liters`, increments the unit's `version`, and opens a `RentalAgreement` in `ON_RENT`. Neither `delivery_truck_id`, `delivery_window_start`, nor `delivery_window_end` is set for a pickup; they remain null.

In both paths the opened `RentalAgreement` copies forward its `reservation_id`, `equipment_unit_id`, and `contractor_account_id`, records `actual_start_date` as the clock's current date, copies `scheduled_end_date` from the reservation's `rental_end_date` as the contractual return deadline, and captures `deposit_held_cents` from the rate card's `deposit_cents`. Exactly one agreement exists per reservation. The agreement's `actual_return_date` stays null while it is `ON_RENT`. As soon as the agreement opens in `ON_RENT`, the linked reservation tracks the live rental by moving from `DISPATCHED_DELIVERY → ON_RENT` (delivery) or `PICKED_UP → ON_RENT` (pickup).

### 3.6. Returning, Inspecting, and Closing

Returning a unit is a two-step settlement. First, a `RentalAgent` marks the physical hand-back, which requires the agreement be `ON_RENT` and the clock's current date be on or after `actual_start_date`, and which advances the agreement `ON_RENT → RETURNED_PENDING_INSPECTION`. This step stamps `actual_return_date` with the clock's current date and computes the agreement's `final_rental_cents` (the final variant of the rental charge, Section 3.8) and its `late_fee_cents` over the actual interval. Marking a return on an agreement that is not `ON_RENT` is rejected with `ERR_INVALID_STATE`.

Second, an `Inspector` records a `ReturnInspection` against the agreement's `rental_agreement_id`, which must be in `RETURNED_PENDING_INSPECTION`; there is exactly one inspection per agreement. The inspection supplies `return_fuel_level_liters` (the fuel measured in the tank at return, at least 0), a `cleanliness` verdict of `CLEAN` or `DIRTY`, and an inspector-assessed `damage_assessed_cents` (at least 0). From these the server computes `fuel_refill_cents` and `net_damage_cents` (Section 3.8), then closes the agreement and settles the account.

The close branches on net damage. When the inspection yields no net damage, the agreement moves `RETURNED_PENDING_INSPECTION → CLOSED`. When the inspection yields positive net damage, it moves `RETURNED_PENDING_INSPECTION → CLOSED_WITH_DAMAGE`, and the server creates a `DamageCharge` recording the `rental_agreement_id`, the `return_inspection_id`, the `gross_cents` (the inspector-assessed gross before waiver), a `waiver_applied` flag, and the `net_cents` actually charged. In both branches the server computes the agreement's `final_total_cents` and posts the settlement ledger lines: a `RENTAL_CHARGE`, a `LATE_FEE` if the late fee is positive, a `FUEL_CHARGE` if the refill is positive, a `CLEANING_CHARGE` if the unit was returned `DIRTY`, and a `DEPOSIT_REFUND` for the full `deposit_held_cents`; in the damage branch an additional `DAMAGE_CHARGE` for the net damage is posted. The account's `outstanding_balance_cents` is then recomputed, and the linked reservation transitions `ON_RENT → FULFILLED`.

The inspection also reconciles the physical unit, and this is where the service threshold bites. The unit accrues this agreement's billed days into `lifetime_rental_days`. If the inspection found no damage (`damage_assessed_cents` is 0) and the unit's `lifetime_rental_days` plus this agreement's billed days remains strictly below `service_due_at_days`, the unit returns to the pool: `availability_state` moves `ON_RENT → AVAILABLE` and its `version` increments. Otherwise — that is, whenever `damage_assessed_cents` is greater than 0, or the unit's `lifetime_rental_days` plus billed days reaches or exceeds `service_due_at_days` — the unit moves `ON_RENT → OUT_OF_SERVICE`, its `version` increments, and the server auto-creates a `MaintenanceTicket` in `OPEN` whose `opened_by_agreement_id` is this agreement and whose `reason` is `DAMAGE_REPAIR` when damage was assessed or `SCHEDULED_SERVICE` when the trigger was the service threshold. Note the deliberate asymmetry around the damage waiver: when damage was assessed but the contractor had opted into the waiver, the net damage charge is zero and the agreement still closes as `CLOSED` rather than `CLOSED_WITH_DAMAGE`, yet the unit still goes `OUT_OF_SERVICE` with a `DAMAGE_REPAIR` ticket because the damage physically occurred. The full cascade therefore reads return → inspection → agreement close → unit out of service → maintenance ticket open.

### 3.7. Account Listings and the Ledger Trail

Reads exist to retrace this entire flow. An account's reservations can be listed by walking `Reservation.contractor_account_id`, optionally filtered by `reservation_state`. An account's ledger lists every `AccountLedgerEntry` in `created_at` ascending order, optionally filtered by `entry_type`. An agreement's ledger entries can be listed by walking `AccountLedgerEntry.rental_agreement_id`, since every settlement line records the `rental_agreement_id` that generated it (manual payments carry a null `rental_agreement_id`). Damage charges can be retraced by their `rental_agreement_id` or `return_inspection_id`, inspections by their `rental_agreement_id`, and maintenance tickets by their `equipment_unit_id`, `opened_by_agreement_id`, or `ticket_state`. Accounts themselves may be filtered by `account_status`, agreements by `reservation_id`, `equipment_unit_id`, `contractor_account_id`, or `agreement_state`, reservations additionally by `equipment_unit_id`, `catalog_item_id`, or `delivery_truck_id`, equipment units by `catalog_item_id` or `availability_state`, and catalog items by `rate_card_id` or `category`.

### 3.8. Charge Calculations

**Tiered rental charge.** The rental line for any interval is computed by greedily decomposing its billed days into blocks and pricing each block. Starting from the billed-day count, the server takes as many whole twenty-eight-day blocks as fit, then as many whole seven-day blocks as fit in the remainder, and the days still left over are loose days. Each twenty-eight-day block is priced at `four_week_rate_cents`, each seven-day block at `weekly_rate_cents`, and each loose day at `daily_rate_cents`; the rental charge is the sum of these three products. A best-rate guard then ensures no partial block costs more than the next whole block, applied in a pinned order: first, if pricing the loose days at the daily rate exceeds `weekly_rate_cents`, charge one week instead of those loose days; second, after that adjustment, if pricing the resulting weeks within the current twenty-eight-day remainder exceeds `four_week_rate_cents`, charge one four-week block instead. The day-to-week cap is applied before the week-to-four-week cap. All of this is exact integer-cent arithmetic.

This rental charge has two variants over different intervals. The **estimate** variant runs at reservation confirm and writes `estimated_rental_cents`; its interval is the full planned `[rental_start_date, rental_end_date]`, assuming an on-time return and ignoring any overdue or late component. The **final** variant runs at the return step and writes `final_rental_cents`; its interval runs from `actual_start_date` to the earlier of `actual_return_date` and `scheduled_end_date` — overdue days are deliberately excluded from the rental rate here and billed instead as a late fee. Because the actual interval can be shorter or capped relative to the plan, the estimate and the final figure diverge whenever the rental does not run exactly as booked.

**Late fee.** The number of overdue days is the whole-day count by which the return runs past the deadline: the actual return date minus the scheduled end date in days, but never below zero. Returning on the scheduled end date yields zero overdue days and therefore no late fee; returning one day later yields one overdue day. The `late_fee_cents` is the overdue-day count multiplied by `daily_rate_cents` multiplied by `late_fee_multiplier`, rounded half up to whole cents.

**Fuel refill.** A unit goes out with a full tank, so its dispatch fuel level equals the catalog item's `fuel_capacity_liters`. The missing liters are the dispatch level minus the `return_fuel_level_liters` reported at inspection, never below zero, and then capped at the tank's `fuel_capacity_liters`. The `fuel_refill_cents` is those capped missing liters multiplied by the rate card's `fuel_refill_cents_per_liter`. If the unit comes back with at least a full tank, the missing liters are zero and there is no fuel charge.

**Net damage.** The gross damage is the inspector's `damage_assessed_cents`. The `net_damage_cents` is zero when the reservation's `damage_waiver_opted` was true and equals the gross otherwise. A boundary holds in both directions: when `damage_assessed_cents` is zero, the net is zero regardless of the waiver, no `DamageCharge` is created, and the agreement closes as `CLOSED`; when `damage_assessed_cents` is greater than zero but the waiver was purchased, the net is zero so no damage ledger line is posted and the agreement closes as `CLOSED`, yet the unit still goes `OUT_OF_SERVICE` as described in Section 3.6.

**Final total.** At close, the server combines the components in a pinned order. It first takes the agreement's `final_rental_cents`; then the waiver amount, which is `damage_waiver_daily_cents` multiplied by the final interval's billed days; then the agreement's `late_fee_cents`; then the inspection's `fuel_refill_cents`; then the cleaning amount, which is `cleaning_fee_cents` when `cleanliness` is `DIRTY` and 0 otherwise; then the `net_damage_cents`; and finally the deposit refund, which is the full `deposit_held_cents`. The `final_total_cents` is the sum of the rental, waiver, late fee, fuel refill, cleaning, and net damage components, with the deposit refund subtracted. The deposit is always fully refunded — damage is posted as its own separate positive charge and is never netted against the deposit — and this `final_total_cents` is the net amount the close posts against the account, since the deposit hold taken at confirm is reversed by the `DEPOSIT_REFUND` line.

**Account balance and credit projection.** As described in Section 2.9, the `outstanding_balance_cents` is recomputed on every ledger insert as the exact signed sum of all the account's `AccountLedgerEntry` rows in `created_at` ascending order. The credit projection at reservation confirm is a distinct forward-looking check on the account: the would-be balance is the current `outstanding_balance_cents` plus `deposit_cents` plus `estimated_total_cents`, and the reservation is rejected when that would exceed `credit_limit_cents`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or transition an existing resource — including state-machine actions such as suspend, cancel, dispatch, pickup, return, and resolve — return `200 OK`. Reads return `200 OK`. Write endpoints require the `X-User-ID` and `X-User-Role` headers; `GET` reads are public.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rental-yard/rate-cards` | Create a rate card | YardManager |
| GET | `/rental-yard/rate-cards/{id}` | Fetch a rate card | YardManager, RentalAgent, Contractor, Inspector |
| GET | `/rental-yard/rate-cards` | List rate cards | YardManager, RentalAgent, Contractor, Inspector |
| POST | `/rental-yard/catalog-items` | Create a catalog item bound to an active rate card | YardManager |
| GET | `/rental-yard/catalog-items/{id}` | Fetch a catalog item with computed availability counts | YardManager, RentalAgent, Contractor, Inspector |
| GET | `/rental-yard/catalog-items` | List/browse catalog items | YardManager, RentalAgent, Contractor, Inspector |
| POST | `/rental-yard/equipment-units` | Register a physical unit for a catalog item | YardManager |
| GET | `/rental-yard/equipment-units/{id}` | Fetch a unit | YardManager, RentalAgent, Contractor, Inspector |
| GET | `/rental-yard/equipment-units` | List units | YardManager, RentalAgent, Contractor, Inspector |
| POST | `/rental-yard/contractor-accounts` | Open a contractor account | YardManager |
| GET | `/rental-yard/contractor-accounts/{id}` | Fetch an account with computed balance/counts | YardManager, RentalAgent, Contractor |
| GET | `/rental-yard/contractor-accounts` | List accounts | YardManager, RentalAgent |
| POST | `/rental-yard/contractor-accounts/{id}/suspend` | Suspend an account | YardManager |
| POST | `/rental-yard/contractor-accounts/{id}/payments` | Record a payment reducing the outstanding balance | YardManager, Contractor |
| GET | `/rental-yard/contractor-accounts/{id}/ledger` | List ledger entries for an account | YardManager, RentalAgent, Contractor |
| GET | `/rental-yard/contractor-accounts/{id}/reservations` | List reservations for an account | YardManager, RentalAgent, Contractor |
| POST | `/rental-yard/delivery-trucks` | Register a delivery truck with a turnaround buffer | YardManager |
| GET | `/rental-yard/delivery-trucks/{id}` | Fetch a delivery truck | YardManager, RentalAgent, Inspector |
| GET | `/rental-yard/delivery-trucks` | List delivery trucks | YardManager, RentalAgent, Inspector |
| POST | `/rental-yard/reservations` | Confirm a future booking, holding a deposit | RentalAgent, Contractor |
| GET | `/rental-yard/reservations/{id}` | Fetch a reservation | YardManager, RentalAgent, Contractor, Inspector |
| GET | `/rental-yard/reservations` | List reservations | YardManager, RentalAgent, Inspector |
| POST | `/rental-yard/reservations/{id}/cancel` | Cancel a CONFIRMED reservation | RentalAgent, Contractor |
| POST | `/rental-yard/reservations/{id}/dispatch` | Dispatch a DELIVERY reservation onto a truck window | RentalAgent |
| POST | `/rental-yard/reservations/{id}/pickup` | Counter pickup for a PICKUP reservation | RentalAgent |
| GET | `/rental-yard/rental-agreements/{id}` | Fetch an agreement with computed final charges | YardManager, RentalAgent, Contractor, Inspector |
| GET | `/rental-yard/rental-agreements` | List agreements | YardManager, RentalAgent, Inspector |
| GET | `/rental-yard/rental-agreements/{id}/ledger-entries` | List ledger entries generated by this agreement | YardManager, RentalAgent, Contractor, Inspector |
| POST | `/rental-yard/rental-agreements/{id}/return` | Mark the unit physically returned | RentalAgent |
| POST | `/rental-yard/return-inspections` | Inspect a returned unit; close the agreement and settle | Inspector |
| GET | `/rental-yard/return-inspections/{id}` | Fetch an inspection | YardManager, RentalAgent, Contractor, Inspector |
| GET | `/rental-yard/return-inspections` | List inspections | YardManager, RentalAgent, Inspector |
| GET | `/rental-yard/damage-charges/{id}` | Fetch a damage charge | YardManager, RentalAgent, Inspector |
| GET | `/rental-yard/damage-charges` | List damage charges | YardManager, RentalAgent, Inspector |
| POST | `/rental-yard/maintenance-tickets` | Manually pull an AVAILABLE unit out of service | YardManager |
| GET | `/rental-yard/maintenance-tickets/{id}` | Fetch a maintenance ticket | YardManager, RentalAgent, Inspector |
| GET | `/rental-yard/maintenance-tickets` | List tickets | YardManager, RentalAgent, Inspector |
| POST | `/rental-yard/maintenance-tickets/{id}/resolve` | Resolve an OPEN ticket; free the unit if it was its last | YardManager |
| POST | `/rental-yard/_clock/set_current_utc` | Set the simulated current UTC clock (test-driving) | YardManager |
| GET | `/rental-yard/_clock` | Read the current simulated clock | YardManager, RentalAgent, Contractor, Inspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_DELIVERY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_UNIT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_TRUCK_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_START_IN_PAST` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WRONG_FULFILLMENT` | 422 Unprocessable Entity |
| `ERR_NO_UNIT_AVAILABLE` | 409 Conflict |
| `ERR_VALIDATION_LIMIT` | 400 Bad Request |
| `ERR_PAYMENT_NOT_NEGATIVE` | 422 Unprocessable Entity |
