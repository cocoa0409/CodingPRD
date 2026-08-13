# Fractional Jet Ownership API — Product Requirements Document

## 1. Introduction

Fractional jet ownership programs sell aircraft by the share: an owner purchases a fraction of a fleet class — a quarter, an eighth, a sixteenth — and in exchange receives an annual entitlement of occupied flight hours, access to an interchangeable fleet of tails, and a monthly bill that blends management fees, occupied-hour charges, peak-day surcharges, and tax adjustments. The economics are unforgiving of sloppy bookkeeping. Entitlement hours are a contested pool debited provisionally at booking time and reconciled against actual block time after the wheels are down; a substituted larger cabin must be billed under a capped interchange rate rather than the flying class's rack rate; and both secondary-market resale and program exit hinge on a market-value formula whose inputs must be pinned to the cent. The operator additionally carries fiduciary obligations to its owner base — maintenance costs must be allocated across the owners of a class on a defensible basis, and depreciation allowances pass through to owners once per tax year.

This document specifies the Fractional Jet Ownership API, which manages the full life of a share inside such a program: enrollment of owners and fleet, share activation and the entitlement ledger, booking requests and tail assignment, flight completion and monthly invoicing, maintenance cost allocation, transfer listings on the resale market, and program exit with net settlement. Four operator roles with strict segregation of duties drive the system, and a logical, test-drivable clock governs every time-based transition so that expiries, invoice aging, and contract-year rollover are fully deterministic. The requirements below are written for the engineering team implementing the service and are normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two identity headers: `X-User-ID`, naming the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT` (HTTP 400). A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Four roles exist. `ProgramAdmin` is the program operator: it configures programs, aircraft classes, owners, and shares, controls program posture, and drives the logical clock. `FleetOps` registers tails, assigns aircraft to bookings, records flight completion, and manages the maintenance calendar. `FinanceOps` opens and issues invoices, resolves disputes, closes share sales, and values, approves, settles, or rejects program exits. `Owner` is the share owner: it submits, confirms, and cancels bookings, pays and disputes invoices, lists shares for resale, accepts listings as a buyer, and initiates or withdraws exits.

Identity semantics differ by role. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting Owner; ownership checks on any resource that references an Owner — the `owner_id` of a share or invoice, the `buyer_owner_id` presented at listing acceptance, the share's current owner at withdrawal time — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `ProgramAdmin`, `FleetOps`, or `FinanceOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — most importantly to distinguish the `FinanceOps` operator who valued an exit from the one who approves it — but never compares it to any entity's `id`. When an `Owner`-role ownership comparison fails, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); the comparison runs only after the referenced resource's existence has been confirmed.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.4.
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

A request to an unrecognized path, or to a recognized path with an unsupported method, is likewise reported as `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure is reported as `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by ascending `id`.

The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Program Clock

All time-dependent behavior is driven by a logical server clock, never by wall-clock time. At server startup the clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin`-only, test-driving capability sets the clock to a supplied `to_iso8601` instant and echoes the resulting `current_utc`; an unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Advancing the clock fires every due system transition in deterministic fashion: booking requests still sitting in `REQUESTED` whose scheduled departure has been reached move to `EXPIRED`; transfer listings still `LISTED` one hundred eighty days after their creation move to `EXPIRED`; issued invoices sweep to `PAST_DUE` once the clock passes thirty days after `issued_at`; and program-level cascades engage when a wind-down is in effect.

One clock-driven transition deserves special emphasis: the contract-year rollover. When the clock crosses a program's contract-year anniversary — the first day of the month named by the program's `contract_year_start_month`, at 00:00 UTC — every share of that program in `ACTIVE` status rolls into a new contract year. An anniversary fires when it lies strictly after the clock's previous reading and at or before the new reading. The share's `contract_year_index` increments by one, and its `hours_remaining_cy` is reset to the full `annual_entitlement_hours`. Unused hours never carry over into the new contract year.

### 2.5. Common Resource Properties

Primary resources carry a uniform set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock and set once at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock and refreshed on every mutation.
- `version` — an integer that begins at 1, increments by one on every mutation of the resource, and which anchors the optimistic concurrency checks of §2.7.

Three record types are append-only exceptions. A FlightLeg, an InvoiceLine, and a DepreciationSchedule each carry only `id` and `created_at`; both `updated_at` and `version` are absent on all three, because none of them is ever mutated in place after creation.

### 2.6. Money, Hours, and Rounding Discipline

Every monetary amount in the system is an integer number of cents, denominated in the owning program's `currency`. Hour quantities — entitlements, remaining balances, estimated and actual block hours, invoice line quantities — carry exactly two decimal places and round half-up, and they appear on the wire as JSON numbers, never strings, each being the underlying value quantized half-up to two decimal places.

Invoice aggregation obeys a pinned rounding order: each line component is rounded to whole cents individually, and only then are the line amounts summed into invoice totals. Summing raw values and rounding once at the invoice level is forbidden, because the two orders produce different cents.

### 2.7. Optimistic Concurrency Control on Shares and Listings

Three write paths carry a mandatory optimistic concurrency check. In each case the client presents the `version` of the parent entity as it last observed it; if that entity's version has since advanced, the write is rejected so the client cannot act on a stale view.

- Creating a booking request (`POST /bookings`) requires `expected_share_version`, carrying the funding share's `version` as the client last observed it. A mismatch with the share's current `version` — for example because another booking was confirmed or cancelled against the same share and legitimately moved its remaining-hours balance — is rejected with `ERR_STALE_SHARE_VERSION` (HTTP 412).
- Creating a transfer listing (`POST /transfer-listings`) likewise requires `expected_share_version` matching the listed share's current `version`; a mismatch is rejected with `ERR_STALE_SHARE_VERSION` (HTTP 412).
- Accepting a transfer listing (`POST /transfer-listings/{id}/accept`) requires `expected_listing_version` matching the listing's current `version`; if the listing has advanced since the buyer last read it — for example because the seller amended the asking price — the acceptance is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412).

Endpoints other than these three do not accept a version field.

### 2.8. Request Validation Pipeline

Every request passes through a fixed validation pipeline, and a failure at any stage reports that stage's error and masks all later stages. The stages run in this order:

1. Identity headers present and the role recognized — otherwise `ERR_MISSING_OR_INVALID_CONTEXT` (HTTP 400).
2. Role permitted for the endpoint per the access matrix — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. Every resource identifier in the path or in the request body exists, validated left to right — otherwise `ERR_NOT_FOUND` (HTTP 404).
4. The target entity is in a state that permits the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409); attempts to move an entity that has already reached a terminal state are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Share activation, tail assignment, sale closing, invoice issuance, and dispute resolution test only their required source state and report `ERR_INVALID_STATE` even against a terminal target.
5. The program-posture gate, applied to booking creation, booking confirmation, listing creation, and listing acceptance — all requiring the program `ACTIVE` — and to share creation, which `SUSPENDED` does not block but `WINDING_DOWN` and `CLOSED` do — otherwise `ERR_PROGRAM_POSTURE_BLOCKS` (HTTP 409).
6. The owner-standing gate, applied to booking confirmation (the confirming owner must stand `GOOD`) and listing acceptance (the buyer must stand `GOOD`) — otherwise `ERR_OWNER_STANDING_BLOCKS` (HTTP 422); the self-dealing check on listing acceptance runs immediately before this gate — otherwise `ERR_SELF_DEALING` (HTTP 422).
7. Temporal validity, applied to booking creation, booking confirmation, and maintenance scheduling — otherwise `ERR_TEMPORAL_INVALID` (HTTP 422).
8. Aircraft window conflicts, applied to tail assignment — otherwise `ERR_AIRCRAFT_WINDOW_CONFLICT` (HTTP 409).
9. Referential integrity, applied to listing creation, share exit, and exit valuation — otherwise `ERR_REFERENTIAL_CONFLICT` (HTTP 409).
10. The entitlement gate, applied to booking confirmation — otherwise `ERR_ENTITLEMENT_EXHAUSTED` (HTTP 422).
11. Payment exactness, applied to invoice payment — otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422).
12. The optimistic-concurrency version checks of §2.7, applied to booking creation and listing acceptance — otherwise `ERR_STALE_SHARE_VERSION` or `ERR_STALE_LISTING_VERSION` (HTTP 412).
13. Fraction validity, applied to share creation — otherwise `ERR_INVALID_FRACTION` (HTTP 422).

Independent of this pipeline, a malformed request body, a missing required field, or a wrong-typed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Program Posture and Wind-Down

A program's `program_posture` takes one of four values — `ACTIVE`, `SUSPENDED`, `WINDING_DOWN`, or `CLOSED` — and begins at `ACTIVE` when the program is created. Posture is the coarsest gate in the system: it decides which kinds of work may enter the pipeline at all.

A `ProgramAdmin` may suspend an `ACTIVE` program, moving it to `SUSPENDED`. Bookings already in `REQUESTED` are retained, but confirmation and assignment operations are rejected while the suspension holds. Resumption returns a `SUSPENDED` program to `ACTIVE`, and is permitted only while in-progress maintenance events afflict at most half of the tails currently `IN_SERVICE`; a resumption that violates this precondition is rejected with `ERR_INVALID_STATE` (HTTP 409).

Winding down is the irreversible ramp toward closure. A `ProgramAdmin` may move a program from `ACTIVE` or `SUSPENDED` into `WINDING_DOWN`, after which the creation of new shares and new booking requests is rejected, every booking still in `REQUESTED` is expired, and every transfer listing still `LISTED` cascades to `EXPIRED`. Exits remain permitted during wind-down — they are the intended path out for owners.

Closure is terminal. Moving from `WINDING_DOWN` to `CLOSED` requires that no share remain in `ACTIVE` or `LISTED`, that no exit request stand in `SUBMITTED`, `VALUED`, or `APPROVED`, and that no invoice stand in `OPEN`, `ISSUED`, `PAST_DUE`, or `DISPUTED`; unmet preconditions are rejected with `ERR_PROGRAM_NOT_CLOSABLE` (HTTP 409). On closure, every owner of the program transitions to `EXITED`.

### 2.10. Owner Standing and the Deposit Ledger

An owner's `owner_standing` — `GOOD`, `DELINQUENT`, `SUSPENDED`, or `EXITED` — is partly derived and partly administered. Every owner begins in `GOOD` standing. The moment any invoice of theirs enters `PAST_DUE`, standing degrades automatically to `DELINQUENT`, and booking confirmation is rejected while that standing holds. When the last `PAST_DUE` invoice is paid or settled after dispute and none remain, standing returns to `GOOD` without any operator action.

A `ProgramAdmin` may suspend an owner who stands `GOOD` or `DELINQUENT`; suspension blocks booking activity across every share that owner holds. Reinstatement returns a suspended owner to `GOOD` and is permitted only when no invoice of theirs remains `PAST_DUE`; a reinstatement attempted while a `PAST_DUE` invoice remains is rejected with `ERR_INVALID_STATE` (HTTP 409).

The `EXITED` standing is terminal and is reached when the owner's final non-closed share reaches `CLOSED`, or when the program closes (§2.9). On the exit-settlement path — the only path that draws against the refundable `deposit_balance_cents` ledger, which may never hold a negative balance — the ledger is drawn down to exactly zero; program closure does not touch deposit balances.

## 3. Business Logic & Workflows

### 3.1. Building the Program: Classes, Tails, and Calendars

A `ProgramAdmin` founds a program by supplying a `program_code` (carried as an opaque string; the server does not enforce its uniqueness), an ISO 4217 `currency` code (carried as an opaque string without validation) in which every cents-denominated field of the program is interpreted, the `contract_year_start_month` — an integer from 1 to 12 on which every share's contract year begins — and a `peak_day_calendar` of distinct ISO dates designated for surcharge assessment. A `contract_year_start_month` outside 1–12, or a `peak_day_calendar` containing duplicate entries, is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the calendar entries themselves are carried as date strings without format validation. The program code, the currency, and the contract-year start month are immutable once set, and the program opens in `ACTIVE` posture.

Fleet classes come next. Each class is registered inside a program with a `class_code` unique within that program — "LIGHT", "MID", "SUPER_MID", "HEAVY" are typical — an `hourly_rate_cents` occupied-hour billing rate, a `monthly_fee_base_cents` full-share management fee that invoicing prorates by share fraction, a certified passenger `seats` count used by the interchange ranking, and an `interchange_upgrade_multiplier_bp` expressed in basis points where 10000 means parity. The multiplier must be at least 10000 and caps what an upgrade may bill (§3.4); both rates must be positive, the `seats` count must be positive, and the class code cannot change after creation. Violation of any of these constraints, or a `class_code` duplicating one already registered in the same program, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

`FleetOps` registers individual tails against a class, identified by a `tail_number` unique within the program and immutable thereafter — a duplicate tail number within the program is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and the named class must belong to the named program, otherwise `ERR_NOT_FOUND` (HTTP 404). A tail enters service as `IN_SERVICE` with `total_hours_flown` at zero. Its `aircraft_status` may later move to `IN_MAINTENANCE` under a started maintenance event, or be marked `GROUNDED`; only `IN_SERVICE` tails are assignable to bookings. Every tail accumulates block hours across the flight legs it completes.

### 3.2. Owners, Shares, and the Entitlement Ledger

An owner joins the program when a `ProgramAdmin` enrolls them with a `legal_name` and an `initial_deposit_cents` amount that seeds the refundable deposit ledger; the amount must be non-negative — zero is permitted — and a negative amount is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The new owner stands `GOOD`.

Shares are the heart of the system. A `ProgramAdmin` creates a share for an owner against a home fleet class, specifying the ownership fraction as `fraction_numerator` over `fraction_denominator` and the `purchase_price_cents` paid, which must be positive — a non-positive price is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The denominator must be one of 4, 8, 16, or 32, and the numerator must be at least 1 and no greater than the denominator; any other combination is rejected with `ERR_INVALID_FRACTION` (HTTP 422). Creation is rejected with `ERR_PROGRAM_POSTURE_BLOCKS` (HTTP 409) while the program is `WINDING_DOWN` or `CLOSED`; a `SUSPENDED` program still admits new shares. A new share's `share_status` rests at `PENDING_ACTIVATION`, with `annual_entitlement_hours` and `hours_remaining_cy` null until activation, and its home `class_id` becomes immutable once it activates.

Tax depreciation rides along with the share. When the creation payload supplies a `schedule_method` — `STRAIGHT_LINE` or `DOUBLE_DECLINING` — together with a `recovery_years` period of 5 or 7, the share's depreciation schedule is created immediately with `basis_cents` equal to the purchase price; an unrecognized method or recovery period is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The schedule is created at share creation only when both fields are supplied; when either is missing, activation creates the schedule on the same basis with the defaults `STRAIGHT_LINE` and five recovery years. The schedule's `accumulated_depreciation_cents` begins at zero, and its `current_year_allowance_cents` is recomputed each time the December invoice run posts an annual allowance (§3.6).

Activation is a `ProgramAdmin` action gated on three conditions: the share still `PENDING_ACTIVATION`, the program `ACTIVE`, and the owner in `GOOD` or `DELINQUENT` standing — a share in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409), a non-`ACTIVE` program with `ERR_PROGRAM_POSTURE_BLOCKS` (HTTP 409), and a disallowed standing with `ERR_OWNER_STANDING_BLOCKS` (HTTP 422). Upon activation the share's annual entitlement is computed as the ownership fraction multiplied by the 800 block hours a full share carries per contract year, rounded half-up to two decimal places, and `hours_remaining_cy` is initialized to that full `annual_entitlement_hours`. The share's `contract_year_index` starts at zero — a monotonic count of contract years elapsed since activation — and the share's `version` advances by one.

From then on, `hours_remaining_cy` behaves as a ledger with exactly three kinds of movement: confirmation of a booking debits the estimated hours provisionally, cancellation re-credits them, and flight completion reconciles the estimate against actual block time (§3.5). The balance may never be driven negative by confirmation — the entitlement gate of §3.3 sees to that — but the final reconciliation against actual hours is permitted to push it below zero into overdraft. Separately, the clock-driven contract-year rollover described in §2.4 restores the balance to the full entitlement at each anniversary.

### 3.3. Booking Requests and the Confirmation Gate

An owner initiates travel by submitting a booking request naming the funding `share_id`, the `requested_class_id`, a `scheduled_departure_utc` instant, an `estimated_block_hours` figure greater than zero with two decimal places, and — per §2.7 — the `expected_share_version` last observed. Creation does not gate on the share's status or the owner's standing — a request may be opened against a share in any status, including `LISTED` (§3.8); the status and standing gates bite at confirmation and completion. The requested class may be any registered class; the server does not require it to belong to the funding share's program. A non-positive `estimated_block_hours` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a value supplied with finer than two-decimal precision is rounded to two decimals at intake rather than rejected. The request lands with `booking_status` `REQUESTED` and `billing_status` `UNBILLED`, with `notice_tier` null until confirmation and `interchange_direction` beginning at `NONE`, and the share's `version` advances by one. Two gates guard even this first step: the program must be `ACTIVE`, and the departure must lie strictly after the current clock — a departure at or before the present instant is rejected with `ERR_TEMPORAL_INVALID` (HTTP 422). Should the clock reach `scheduled_departure_utc` while the request still sits in `REQUESTED`, the booking expires automatically, moving to `EXPIRED` with no further effect.

Before committing to a departure, the owner or operations staff may read a provisional quote on the booking, which returns a `provisional_total_cents` figure alongside the `notice_tier` that confirmation would freeze; for a booking not yet confirmed the tier is computed against the current clock, while for a confirmed booking the quote echoes the tier frozen at confirmation. The quote prices the owner's `estimated_block_hours` at the requested class's hourly rate regardless of any interchange that may later occur, so it can differ from the final bill whenever actuals differ from estimates or a different class flies the leg.

Confirmation is the owner's commitment, and it is the most heavily gated transition in the system. It requires the booking still `REQUESTED`, the funding share `ACTIVE` (any other share status is rejected with `ERR_INVALID_STATE`, HTTP 409), the owner `GOOD`, the program `ACTIVE`, and the departure still strictly in the future. The entitlement gate then demands that `hours_remaining_cy` be at least `estimated_block_hours` — exact equality is permitted and simply drains the balance to zero — and a shortfall is rejected with `ERR_ENTITLEMENT_EXHAUSTED` (HTTP 422). Upon confirmation the estimated hours are debited provisionally from the share, the share's `version` advances, `billing_status` becomes `PROVISIONALLY_BILLED`, and the booking is stamped with its notice tier: fewer than 72 hours between the confirm-time clock and the scheduled departure classifies as `TIER_24H`, at least 72 hours but fewer than 168 hours classifies as `TIER_72H`, and 168 hours or more classifies as `TIER_7D`. A booking confirmed exactly 72 hours before departure lands in `TIER_72H`, and one confirmed exactly 168 hours out lands in `TIER_7D`. The tier is frozen at confirmation and never moves afterward.

An owner may cancel from either `REQUESTED` or `CONFIRMED`. Cancelling a confirmed booking restores the provisionally debited `estimated_block_hours` to the share's remaining balance — a compensating re-credit that preserves the entitlement invariant — returns `billing_status` to `UNBILLED`, voids any provisional lines for the booking at the next aggregation, and advances the share's `version`.

### 3.4. Tail Assignment and Interchange Economics

Assignment is a `FleetOps` action on a `CONFIRMED` booking, naming an `aircraft_id`. The assigned tail must be `IN_SERVICE` — a tail in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the server does not require the tail to belong to the booking's program. The tail must be free of conflicts: no other `CONFIRMED` booking window and no in-progress maintenance window may overlap the booking's window, where a booking's window runs from its `scheduled_departure_utc` through that instant plus its `estimated_block_hours`, and windows are treated as half-open intervals — one window ending at the exact instant another begins is not a conflict. A conflicting assignment is rejected with `ERR_AIRCRAFT_WINDOW_CONFLICT` (HTTP 409). Successful assignment records `assigned_aircraft_id` — null until this point — and stamps `interchange_direction` by comparing hourly rates alone: `UPGRADE` when the assigned class's hourly rate exceeds the requested class's rate, `DOWNGRADE` when it is lower, and `NONE` when the rates are equal — in particular always `NONE` when the assigned tail belongs to the requested class. Whenever the classes differ, an `INTERCHANGE_ADJUSTMENT` line is prepared for the next invoice aggregation.

To help dispatchers choose a tail, the system offers a ranked suggestion capability to `FleetOps`. Candidate tails are those of the booking's program that are `IN_SERVICE` and free of overlapping confirmed-booking and in-progress-maintenance windows. They are ranked first by ascending absolute difference between the candidate class's `seats` and the requested class's seats, then by ascending `total_hours_flown` to spread wear across the fleet, then by ascending `created_at`, then by ascending `id`. The full ranked list is returned in a single unpaginated response. An empty candidate pool is reported as `ERR_NO_AIRCRAFT_AVAILABLE` (HTTP 409).

Interchange billing follows an owner-friendly cap. On an upgrade, the effective hourly rate billed is the lesser of the flying class's rack rate and the requested class's rate scaled by the assigned class's `interchange_upgrade_multiplier_bp` divided by 10000 — that scaled figure rounded half-up to whole cents before the comparison. The adjustment line then carries the difference between the effective rate and the requested rate, multiplied by the billed hours and rounded half-up: a positive surcharge that never reaches the flying class's full rack rate. On a downgrade the owner simply pays the flying class's lower rate, and the adjustment line carries the difference between the flying and requested rates, multiplied by the billed hours and rounded half-up, as a negative amount — a credit. When no interchange occurs, no adjustment line is produced.

### 3.5. Flight Completion and Entitlement Reconciliation

When the wheels are down, `FleetOps` completes a booking by recording `actual_block_hours` — greater than zero, with two decimal places, and a non-positive figure is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — against it. Completion requires the booking `CONFIRMED` with an `assigned_aircraft_id` recorded, and the funding share still `ACTIVE` — an unconfirmed booking, a missing assignment, or a non-`ACTIVE` share is rejected with `ERR_INVALID_STATE` (HTTP 409): a share that is `LISTED` or `IN_EXIT` blocks completion, even though its bookings could be created and confirmed earlier. Exactly one FlightLeg is created per completed booking, carrying the `booking_id`, the flying `aircraft_id`, the actual hours, a `completed_at` instant stamped from the clock, and a `peak_day_flag` that is set when the scheduled departure's UTC calendar date appears in the program's `peak_day_calendar`.

Completion reconciles the entitlement ledger. The provisional debit is unwound and the actual debit applied in its place: the share's remaining hours are adjusted by the difference between the estimated and actual hours — the estimate added back, the actuals taken out — and this reconciliation is the one movement permitted to push the balance below zero into overdraft. The booking moves to `COMPLETED` with `billing_status` `FINALLY_BILLED`, the tail's `total_hours_flown` grows by the actual hours, and the `version` of both the share and the aircraft advances by one; no invoice work happens at completion, because aggregation runs entirely at issuance (§3.6).

### 3.6. Monthly Billing: Aggregation, Payment, and the Dispute Loop

`FinanceOps` opens an owner's invoice for a calendar month by supplying the `owner_id` and a `billing_period` in YYYY-MM form. One invoice may exist per owner per period; a duplicate is rejected with `ERR_DUPLICATE_INVOICE_PERIOD` (HTTP 409). The invoice opens with `invoice_status` `OPEN` and no lines; every line is computed and persisted at issuance, so an `OPEN` invoice always reads with zero totals.

Issuing the invoice runs the full aggregation, and every line it persists references its parent `invoice_id`, carries a `line_kind`, attributes the charge to a `share_id`, and records the hours it prices in `quantity_hours`. The management-fee component sums, across every share of the owner standing `ACTIVE`, `LISTED`, or `IN_EXIT` at the issuance clock, the class's `monthly_fee_base_cents` scaled by the share's fraction and rounded half-up to whole cents per share; a share standing `PENDING_ACTIVATION` or `CLOSED` at issuance contributes nothing — even if it was active for part of the period — and a mid-period activation is billed for the full month with no proration. These become `MANAGEMENT_FEE` lines, whose `quantity_hours` is zero.

The occupied-hours component sums, for each flight leg of a `FINALLY_BILLED` booking whose funding share belongs to the owner at the issuance clock and whose `completed_at` falls inside the billing month — a half-open interval that includes the first instant of the month and excludes the first instant of the next — a base charge of the leg's actual hours multiplied by the requested class's hourly rate, rounded half-up per line, posted as an `OCCUPIED_HOURS` line. When the leg's `peak_day_flag` is set, a `PEAK_SURCHARGE` line adds 15 percent of that base — 1500 basis points — again rounded half-up per line. Any `INTERCHANGE_ADJUSTMENT` lines prepared at assignment join the same sum. All flight-derived lines carry the originating `booking_id`, the `OCCUPIED_HOURS`, `PEAK_SURCHARGE`, and `INTERCHANGE_ADJUSTMENT` lines carry the leg's actual hours as `quantity_hours`, and `amount_cents` is negative for credits, as on a downgrade adjustment. The per-line rounding order of §2.6 is pinned: rounding once at the invoice level is forbidden because it yields different cents.

Two further components complete the bill. Completed maintenance events whose completion instant falls inside the billing period contribute `MAINTENANCE_ALLOCATION` lines per §3.7, each attributed to the owner's earliest-created share of the tail's class standing `ACTIVE`, `LISTED`, or `IN_EXIT` (a null `share_id` when none qualifies), with zero `quantity_hours` and no `booking_id`. And on the invoice covering the final billing period of a tax year — the December period — depreciation passes through: each of the owner's share schedules yields an annual allowance, excepting schedules of shares that reached `CLOSED` through a settled exit, which are skipped. Under `STRAIGHT_LINE`, the allowance is the basis divided by the recovery years, rounded half-up to whole cents and capped at the remaining undepreciated basis. Under `DOUBLE_DECLINING`, the allowance is the lesser of two values — twice the remaining undepreciated basis divided by the recovery years, rounded half-up, and the remaining undepreciated basis itself — so accumulated depreciation can never exceed the basis. A schedule whose allowance computes to zero posts no line and is left unchanged; posted `DEPRECIATION_PASSTHROUGH` lines carry zero `quantity_hours` and no `booking_id`. The invoice's `tax_adjustment_cents` is the negated sum of these allowances, a credit, posted through `DEPRECIATION_PASSTHROUGH` lines. Evaluation order is pinned: every share's allowance is computed against the accumulated balance as it stood before this year's posting, and only after all allowances are computed are the schedules updated — interleaving computation and update would corrupt the schedules of owners with multiple shares.

The invoice's `total_due_cents` is then exactly `management_fee_cents` plus `occupied_hours_fee_cents` plus `tax_adjustment_cents`. Issuing requires the billing period to have ended relative to the clock — an early issue is rejected with `ERR_INVOICE_PERIOD_OPEN` (HTTP 422) — and the owner must not be `EXITED` — an `EXITED` owner is rejected with `ERR_OWNER_STANDING_BLOCKS` (HTTP 422). An invoice not `OPEN` cannot be issued (`ERR_INVALID_STATE`, HTTP 409). Issuance stamps `issued_at` from the clock and moves the invoice from `OPEN` to `ISSUED`.

Payment is exact. The owner pays an invoice standing `ISSUED` or `PAST_DUE` by tendering `amount_cents` equal to `total_due_cents` to the cent; anything else is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A paid invoice moves to `PAID`, and if that clears the owner's last `PAST_DUE` invoice, their standing returns from `DELINQUENT` to `GOOD`. Left unpaid, an issued invoice rolls to `PAST_DUE` when the clock passes thirty days after `issued_at`, and the owner's standing degrades from `GOOD` to `DELINQUENT` in the same sweep (§2.10).

An owner who disagrees with a bill may dispute it while it stands `ISSUED` or `PAST_DUE`, moving it to `DISPUTED`; if it had been past due, the owner remains `DELINQUENT` until the dispute resolves. `FinanceOps` then resolves the dispute in one of two ways. Supplying an `adjusted_total_cents` — which must be non-negative, a negative value drawing `ERR_INVALID_REQUEST` (HTTP 400) — replaces the invoice total and settles the invoice as `SETTLED_AFTER_DISPUTE`. Supplying the `reject_adjustment` flag instead returns the invoice unchanged to `ISSUED`, or to `PAST_DUE` if that is where it stood before the dispute; when both are supplied, `reject_adjustment` takes precedence. Whenever a resolution leaves the owner with no remaining `PAST_DUE` invoice, standing recovers to `GOOD`.

### 3.7. Maintenance Windows and Cost Allocation

`FleetOps` schedules a maintenance event on a tail by naming the `aircraft_id`, a `window_start_utc`, a `window_end_utc` strictly after the start — anything else is rejected with `ERR_TEMPORAL_INVALID` — a `cost_cents` figure that may be zero but never negative — a negative cost is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and a mandatory boolean `unscheduled_flag` distinguishing unscheduled work, which allocates cost on a different basis. The event stands with `event_status` `SCHEDULED`, and while it has not started it may be cancelled, moving to `CANCELLED`.

Starting the event requires that no other maintenance event is already `IN_PROGRESS` on the same tail; a second in-progress event is rejected with `ERR_MAINTENANCE_OVERLAP` (HTTP 409). The tail moves from `IN_SERVICE` to `IN_MAINTENANCE`, and any `CONFIRMED` booking assigned to it whose window overlaps the maintenance window is unassigned — its `assigned_aircraft_id` is cleared — leaving interchange reassignment to dispatch; the booking otherwise remains `CONFIRMED` and its `interchange_direction` is not reset. Completing the event requires the clock to have reached `window_end_utc`, unless `FleetOps` explicitly passes the `override_early` flag (which must be a boolean, otherwise `ERR_INVALID_REQUEST`, HTTP 400); completion returns the tail to `IN_SERVICE` and triggers cost allocation.

Allocation spreads the event's `cost_cents` across every owner holding at least one `ACTIVE` share in that tail's class at the completion clock. For scheduled events, an owner's weight is the sum of the ownership fractions of their `ACTIVE` shares in the class. For unscheduled events, the basis switches to usage: the sum over those shares of each fraction multiplied by the hours that share has consumed so far in the current contract year — so identical ownership structures produce different allocations depending on who has been flying. Each owner's raw allotment is the pool scaled by their weight over the total weight; raw allotments are floored to whole cents, and the remainder cents are then distributed one at a time in order of decreasing weight, ties broken by the owner's earlier `created_at`, then by ascending owner id, until the remainder is exhausted. If the total weight is zero — possible only for an unscheduled event before any owner has consumed hours — or the cost itself is zero, each candidate owner is allocated zero cents. Should no owner hold an `ACTIVE` share in the class at completion, no allocation is performed: the cost stays held on the event, and no invoice line is ever emitted for it.

### 3.8. The Resale Market: Transfer Listings and Ownership Change

An owner leaves a share without leaving the program by listing it for resale. The listing payload carries the `share_id`, an `asking_price_cents` that must be positive and anchors market value — a non-positive ask is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — a `program_repurchase_flag`, and the `expected_share_version` the seller last observed (§2.7). The program must be `ACTIVE`, and the share must be `ACTIVE` with no other listing of it live — in `LISTED` or `UNDER_OFFER`; a duplicate live listing, or a listing attempted against a share in any other state, is rejected with `ERR_REFERENTIAL_CONFLICT` (HTTP 409). A fresh listing stands with `listing_status` `LISTED`, the share moves from `ACTIVE` to `LISTED`, and the share's `version` advances. While a share is listed, new booking requests against it remain permissible, but completion of its flights is blocked until the share returns to `ACTIVE`. The `program_repurchase_flag` is recorded on the listing and echoed on reads; acceptance and closing follow the same flow whether or not it is set.

A different owner accepts the listing by presenting a `buyer_owner_id` and the `expected_listing_version` last observed. Self-dealing is forbidden — a buyer identical to the share's current owner is rejected with `ERR_SELF_DEALING` (HTTP 422) — the buyer must stand `GOOD`, the program must be `ACTIVE`, and a stale listing version is rejected per §2.7. Acceptance moves the listing from `LISTED` to `UNDER_OFFER`, records the buyer, advances the listing's `version`, and leaves the share `LISTED` pending closing.

`FinanceOps` closes the sale by recording the `final_sale_price_cents`, which must be positive — a non-positive figure is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a listing not `UNDER_OFFER` is rejected with `ERR_INVALID_STATE` (HTTP 409). The listing becomes `SOLD`; the share's ownership is reassigned to the buyer; its `hours_remaining_cy` carries over untouched — the entitlement follows the share, not the owner; the depreciation schedule is rebased with a new basis equal to the final sale price and `accumulated_depreciation_cents` and `current_year_allowance_cents` reset to zero for the buyer; and the share returns from `LISTED` to `ACTIVE` under its new owner, its `version` advancing once more.

Sellers retain an out until the hammer falls: the share's current owner may withdraw a listing in `LISTED` or `UNDER_OFFER`, moving it to `WITHDRAWN`. Separately, a listing still `LISTED` one hundred eighty days after its creation expires, and a program wind-down expires every live listing (§2.9). In each case — withdrawal, expiry, or wind-down cascade — the covered share returns from `LISTED` to `ACTIVE`, unless it has already entered `IN_EXIT`.

### 3.9. Program Exit, Buyout, and Settlement

The formal exit begins when the owner of a share in `ACTIVE` or `LISTED` requests to leave the program — a share in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409), and a listed share's covering listing must first be withdrawn or expired — and no exit request may already stand in `SUBMITTED`, `VALUED`, or `APPROVED` for that share; violations surface as `ERR_REFERENTIAL_CONFLICT` (HTTP 409). Exits are not posture-gated — they remain available while the program is `WINDING_DOWN`, and indeed under any posture. The request opens an ExitRequest with `exit_status` `SUBMITTED` and swings the share into `IN_EXIT`, expiring its `REQUESTED` bookings and cancelling its `CONFIRMED` ones with the usual compensating re-credit of their estimated hours.

Valuation is a `FinanceOps` action requiring that no `CONFIRMED` bookings remain on the share — the `IN_EXIT` cascade has normally cancelled them already; if any remain, the valuation is rejected with `ERR_REFERENTIAL_CONFLICT`. The buyout formula pins its inputs to the cent. Market value is the share's `purchase_price_cents` scaled by an 82 percent residual index — 8200 basis points — rounded half-up to whole cents. When at least three full contract years have elapsed since activation — a `contract_year_index` of three or more — the `early_exit_penalty_cents` is zero. Otherwise the penalty is 20 percent of market value, scaled by the unelapsed fraction of the three-year minimum hold — the years remaining divided by three — rounded half-up to whole cents. The `buyout_amount_cents` is the market value minus the penalty, and both figures remain null until the request reaches `VALUED`; `settlement_cents` likewise remains null until the request reaches `SETTLED`.

Approval enforces segregation of duties: the `FinanceOps` identity approving the exit must differ from the identity that ran the valuation, otherwise the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval or settlement attempted before valuation has run is rejected with `ERR_EXIT_NOT_VALUED` (HTTP 409); settlement of a valued-but-unapproved request is rejected with `ERR_INVALID_STATE` (HTTP 409).

Settlement nets everything. The `settlement_cents` is the buyout amount minus the owner's `outstanding_invoice_balance_cents` plus the owner's `deposit_balance_cents`, where the outstanding balance is the sum of `total_due_cents` across the owner's invoices standing in `OPEN`, `ISSUED`, `PAST_DUE`, or `DISPUTED` as of the settle clock; those invoices are force-closed to `PAID`, netted into the settlement, and settlement performs no owner-standing recomputation. The valuation never feeds itself — no line generated by the exit enters its own outstanding balance. With settlement recorded, the exit request moves to `SETTLED`, the deposit ledger is drawn to zero, the share moves from `IN_EXIT` to `CLOSED`, and if it was the owner's last non-closed share, the owner transitions to `EXITED` per §2.10.

Not every exit completes. `FinanceOps` may reject a request in `SUBMITTED` or `VALUED`, landing it in `REJECTED`, and the owner may withdraw from those same states, landing it in `WITHDRAWN`; in either case the share returns from `IN_EXIT` to `ACTIVE`. Bookings that the entry cascade expired are not restored — re-entry into the program's flight schedule starts fresh.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`: programs, aircraft classes, tails, owners, shares, booking requests, invoices, transfer listings, maintenance events, flight completion (which creates the FlightLeg), and opening an exit on a share (which creates the ExitRequest). Operations that modify an existing resource in place — posture changes, activations, confirmations, assignments, cancellations, issuance, payment, dispute resolution, acceptance, closing, withdrawal, valuation, approval, settlement, rejection — return `200 OK`, as do all reads and the clock-setting capability.

List endpoints accept optional equality filters. Aircraft classes filter by `program_id`. Aircraft filter by `program_id`, `class_id`, and `aircraft_status`. Owners filter by `program_id` and `owner_standing`. Shares filter by `owner_id`, `class_id`, and `share_status`. Bookings filter by `share_id`, `requested_class_id`, `assigned_aircraft_id`, `booking_status`, and `billing_status`. Flight legs filter by `booking_id` and `aircraft_id`. Invoices filter by `owner_id`, `invoice_status`, and `billing_period`. Invoice lines listed across invoices filter by `invoice_id`, `booking_id`, `share_id`, and `line_kind`; the per-invoice line listing is scoped by the path invoice alone. Transfer listings filter by `share_id`, `listing_status`, and `buyer_owner_id`. Maintenance events filter by `aircraft_id` and `event_status`. Depreciation schedules filter by `share_id`. Exit requests filter by `share_id` and `exit_status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical server clock | ProgramAdmin |
| POST | `/programs` | Create a program | ProgramAdmin |
| GET | `/programs/{id}` | Get a program | All roles |
| POST | `/programs/{id}/suspend` | Suspend a program | ProgramAdmin |
| POST | `/programs/{id}/resume` | Resume a suspended program | ProgramAdmin |
| POST | `/programs/{id}/wind-down` | Wind down a program; expires requested bookings and listed listings | ProgramAdmin |
| POST | `/programs/{id}/close` | Close a program (terminal); all owners exit | ProgramAdmin |
| POST | `/aircraft-classes` | Create an aircraft class in a program | ProgramAdmin |
| GET | `/aircraft-classes/{id}` | Get an aircraft class | All roles |
| GET | `/aircraft-classes` | List aircraft classes | All roles |
| POST | `/aircraft` | Register a tail | FleetOps |
| GET | `/aircraft/{id}` | Get an aircraft | All roles |
| GET | `/aircraft` | List aircraft | All roles |
| POST | `/owners` | Create an owner | ProgramAdmin |
| GET | `/owners/{id}` | Get an owner | All roles |
| GET | `/owners` | List owners | All roles |
| POST | `/owners/{id}/suspend` | Suspend an owner | ProgramAdmin |
| POST | `/owners/{id}/reinstate` | Reinstate a suspended owner | ProgramAdmin |
| POST | `/shares` | Create a share (starts pending activation) | ProgramAdmin |
| GET | `/shares/{id}` | Get a share | All roles |
| GET | `/shares` | List shares | All roles |
| POST | `/shares/{id}/activate` | Activate a share; computes entitlement and starts contract year 0 | ProgramAdmin |
| POST | `/shares/{id}/exit` | Open an exit request on the share | Owner |
| POST | `/bookings` | Create a booking request (OCC on the share) | Owner |
| GET | `/bookings/{id}` | Get a booking | All roles |
| GET | `/bookings` | List bookings | All roles |
| GET | `/bookings/{id}/quote` | Provisional billing preview using estimated hours and the requested class rate | All roles |
| GET | `/bookings/{id}/suggest-aircraft` | Ranked candidate tails per the interchange selector rule | FleetOps |
| POST | `/bookings/{id}/confirm` | Confirm a booking: entitlement gate, notice tier frozen, provisional debit | Owner |
| POST | `/bookings/{id}/assign` | Assign an aircraft; computes interchange direction | FleetOps |
| POST | `/bookings/{id}/cancel` | Cancel a booking; compensating re-credit of provisional hours | Owner |
| POST | `/bookings/{id}/complete` | Complete a booking with actual hours; creates the flight leg; reconciles the entitlement delta | FleetOps |
| GET | `/flight-legs` | List flight legs | All roles |
| GET | `/flight-legs/{id}` | Get a flight leg | All roles |
| POST | `/invoices` | Open an invoice for an owner and billing period | FinanceOps |
| GET | `/invoices/{id}` | Get an invoice | All roles |
| GET | `/invoices` | List invoices | All roles |
| GET | `/invoices/{id}/lines` | List the lines of one invoice | All roles |
| GET | `/invoice-lines` | List invoice lines across invoices | All roles |
| GET | `/invoice-lines/{id}` | Get an invoice line | All roles |
| POST | `/invoices/{id}/issue` | Issue an invoice; runs all aggregations | FinanceOps |
| POST | `/invoices/{id}/pay` | Pay an invoice; amount must equal the total due exactly | Owner |
| POST | `/invoices/{id}/dispute` | Dispute an issued or past-due invoice | Owner |
| POST | `/invoices/{id}/resolve-dispute` | Resolve a dispute with an adjusted total or a rejection of the adjustment | FinanceOps |
| POST | `/transfer-listings` | List a share for resale (OCC on the share) | Owner |
| GET | `/transfer-listings/{id}` | Get a transfer listing | All roles |
| GET | `/transfer-listings` | List transfer listings | All roles |
| POST | `/transfer-listings/{id}/accept` | Buyer accepts a listing (OCC on the listing) | Owner |
| POST | `/transfer-listings/{id}/close-sale` | Close a sale: reassigns share ownership and rebases depreciation | FinanceOps |
| POST | `/transfer-listings/{id}/withdraw` | Seller withdraws a listing | Owner |
| POST | `/maintenance-events` | Schedule a maintenance event on an aircraft | FleetOps |
| GET | `/maintenance-events/{id}` | Get a maintenance event | All roles |
| GET | `/maintenance-events` | List maintenance events | All roles |
| POST | `/maintenance-events/{id}/start` | Start maintenance; aircraft to maintenance status; overlapping bookings unassigned | FleetOps |
| POST | `/maintenance-events/{id}/complete` | Complete maintenance; allocates cost across class owners | FleetOps |
| POST | `/maintenance-events/{id}/cancel` | Cancel a scheduled maintenance event | FleetOps |
| GET | `/depreciation-schedules/{id}` | Get a depreciation schedule | All roles |
| GET | `/depreciation-schedules` | List depreciation schedules | All roles |
| GET | `/exit-requests/{id}` | Get an exit request | All roles |
| GET | `/exit-requests` | List exit requests | All roles |
| POST | `/exit-requests/{id}/value` | Value an exit: computes the buyout amount and early-exit penalty | FinanceOps |
| POST | `/exit-requests/{id}/approve` | Approve a valued exit (segregation of duties versus the valuer) | FinanceOps |
| POST | `/exit-requests/{id}/settle` | Settle an exit: nets outstanding invoices and the deposit; closes the share | FinanceOps |
| POST | `/exit-requests/{id}/reject` | Reject an exit; the share returns to active | FinanceOps |
| POST | `/exit-requests/{id}/withdraw` | Owner withdraws an exit; the share returns to active | Owner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_PROGRAM_POSTURE_BLOCKS` | 409 Conflict |
| `ERR_PROGRAM_NOT_CLOSABLE` | 409 Conflict |
| `ERR_OWNER_STANDING_BLOCKS` | 422 Unprocessable Entity |
| `ERR_ENTITLEMENT_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_TEMPORAL_INVALID` | 422 Unprocessable Entity |
| `ERR_AIRCRAFT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_NO_AIRCRAFT_AVAILABLE` | 409 Conflict |
| `ERR_REFERENTIAL_CONFLICT` | 409 Conflict |
| `ERR_SELF_DEALING` | 422 Unprocessable Entity |
| `ERR_INVALID_FRACTION` | 422 Unprocessable Entity |
| `ERR_STALE_SHARE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LISTING_VERSION` | 412 Precondition Failed |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVOICE_PERIOD_OPEN` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INVOICE_PERIOD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_EXIT_NOT_VALUED` | 409 Conflict |
| `ERR_MAINTENANCE_OVERLAP` | 409 Conflict |
