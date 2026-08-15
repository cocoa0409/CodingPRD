# Propane Wholesale Terminal API — Product Requirements Document

## 1. Introduction

A propane wholesaler lives between two clocks. Upstream, the supply clock runs on rail: supply contracts promise receipt volumes into a terminal across a window, railcars are tendered, move, arrive, and are unloaded into physical storage. Downstream, the demand clock runs on weather: dealers draw product through the winter heating season, and a single cold snap can turn an adequate terminal into a rationed one overnight. This API is the operating system for that business — it tracks every wholesaler-owned gallon in the tank, every gallon promised to a dealer, every truck hour committed to a route, and every cent of credit a dealer has consumed.

The product requirements below cover supply contract and rail-shipment management into terminals, seasonal storage build and winter draw with a season-dependent reserve floor, transport truck scheduling under driver hours-of-service limits, index and fixed-price dealer contracts with a tiered delivered-price engine, dealer credit exposure with an automatic watch/suspension ladder, cold-snap scarcity events that curtail terminals and force pro-rata allocation runs, and a dealer payment ledger with FIFO application and NSF return handling. All of it runs against a server-owned logical clock, so that seasonality, contract windows, and event effective dates are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: identity, envelope shape, pagination, versioning, money and rounding, the logical clock, and the order in which validation layers run.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's capacity. The system recognizes seven roles, spelled exactly: `SupplyAdmin`, `SupplyPlanner`, `PricingDesk`, `CreditManager`, `Dispatcher`, `DealerUser`, and `SystemAdmin`.

A request with missing headers, an undeclared role, or an entity-backed identity that does not resolve is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a request whose shape is malformed — a missing required field, a wrong type, or an invalid enum member — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A caller whose role is not listed among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `DealerUser`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's `dealer_id` foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_DEALER_MISMATCH` (HTTP 403). When `X-User-Role` is `SupplyAdmin`, `SupplyPlanner`, `PricingDesk`, `CreditManager`, `Dispatcher`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning Discipline

Every primary resource — terminals, supply contracts, rail shipments, dealers, dealer contracts, freight zones, trucks, delivery orders, cold-snap events, allocation runs, and dealer payments — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation of the resource's own stored fields.

The one exception is the `PriceIndexPublication`, which is append-only configuration: it carries `id` and `created_at` only. Both `updated_at` and `version` are absent from it, and no update or delete endpoint exists for it.

Version increments have a strict discipline. On a `Terminal`, `version` increments on direct writes and on cascades that change the terminal's own stored fields — `on_hand_gal`, `allocation_posture`, or `ops_epoch`; purely computed aggregates such as `reserved_gal` and `available_to_promise_gal` never bump `version`. On a `Dealer`, `version` increments on direct writes to `credit_limit_cents`, on payment-return fee posting to `fee_balance_cents`, and on contract-activation supersede bookkeeping; computed exposure and status fields never bump it.

### 2.5. The Logical Clock and Seasonal Posture

The server owns a logical clock; wall-clock time is never consulted. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and it continues to read that instant until a `SystemAdmin` sets it. An admin-only test-driving capability accepts a `to_iso8601` instant, moves the clock to it, and answers with the current instant as `now_iso8601`. Derived seasonal state follows the new date on the next read.

The clock drives each terminal's `season_posture`: when the current month falls in October through March the posture is `WINTER_DRAW`; in all other months it is `SUMMER_BUILD`. This is a pure derivation, not a state machine — no write ever sets it directly.

### 2.6. Optimistic Concurrency Control

Two write operations require the caller to present its last observed version of a parent entity, so that a write based on a stale view is rejected instead of silently overwriting a change the caller never saw.

Creating an allocation run requires `expected_terminal_version` as a non-optional input, carrying the caller's last observed `version` of the target `Terminal`. Because creating a run supersedes the terminal's existing open run and bumps `Terminal.version`, a presented value that no longer matches the terminal's current `version` is rejected with `ERR_STALE_TERMINAL_VERSION` (HTTP 412).

Activating a dealer contract requires `expected_dealer_version` as a non-optional input, carrying the caller's last observed `version` of the contract's `Dealer`. Because activation supersedes the dealer's overlapping active contract and bumps `Dealer.version`, a mismatch is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412). Endpoints not named in this section take no version field at all.

### 2.7. Money, Millicents, and Rounding Discipline

Prices are expressed as integer millicents per gallon — one millicent is one-thousandth of a cent — in fields such as `price_mc_per_gal`, `fixed_price_mc_per_gal`, and `freight_mc_per_gal`. Amounts are expressed as integer cents, in fields such as `credit_limit_cents`, `provisional_total_cents`, `final_total_cents`, `open_balance_cents`, `amount_cents`, `fee_balance_cents`, and `min_freight_cents`.

All delivered-price computation rounds half-up to integer cents, and the rounding is applied per segment: the in-band product segment, the overage product segment, the freight segment, and the winter-surcharge segment are each rounded half-up to integer cents individually, and only then summed. Summing unrounded segments and rounding once at the end is forbidden. Gallon and minute arithmetic (ATP, allocation shares, trip estimates) is integer arithmetic with no float intermediates; threshold comparisons on credit use integer cross-multiplication, never floating point.

### 2.8. Terminal Inventory, Reserve Floors, and Available-to-Promise

Each terminal is a physical tank farm with a `storage_capacity_gal`, a `rack_bay_count` of truck loading bays, and two reserve floors: a `reserve_floor_gal` used outside the heating season and a `winter_reserve_floor_gal` used during it, with the winter floor always at least the non-winter floor. The `effective_reserve_floor_gal` is the winter floor while `season_posture` is `WINTER_DRAW`, and the regular floor otherwise.

Wholesaler-owned gallons in storage are tracked in `on_hand_gal`, which starts at 0 and is mutated only by two events: a rail unload adds gallons, and an order load removes them. Both mutations bump `Terminal.version`. Gallons promised but not yet loaded are tracked by `reserved_gal`, the sum of `allocated_gal` over the terminal's orders in `ALLOCATED` or `SCHEDULED`; requests and shorted orders hold nothing. The terminal's `available_to_promise_gal` is `on_hand_gal` minus the effective reserve floor minus `reserved_gal`. It is reported exactly as computed and may be negative before the first inventory arrives; gates that compare against it treat equality as passing. `reserved_gal`, `effective_reserve_floor_gal`, and `available_to_promise_gal` are computed on read and never bump `version`.

### 2.9. Validation Precedence

Every request passes through validation layers in a fixed order, so that an earlier failure masks later ones deterministically. First, authentication and request shape: headers, role membership, and payload well-formedness. Second, role authorization against the endpoint. Third, `DealerUser` ownership checks. Fourth, path identifiers are resolved left-to-right, and the first id that does not exist yields `ERR_NOT_FOUND` (HTTP 404). Fifth, body foreign keys — such as `dealer_contract_id`, `terminal_id`, `freight_zone_id`, `truck_id`, `supply_contract_id`, and `dealer_id` — must resolve to existing entities, else `ERR_REFERENCED_NOT_FOUND` (HTTP 422). Sixth, the optimistic-concurrency checks of §2.6. Seventh, generic transition legality: the entity must be in a valid from-state for the requested action, else `ERR_INVALID_STATE` (HTTP 409). Eighth, cross-entity state gates such as contract-active, dealer-not-suspended, truck-available, terminal-curtailed, and no-other-active-cold-snap. Ninth, safety rules: driver hours-of-service and the reserve-floor check at load. Tenth, capacity, referential, temporal, and uniqueness constraints. Eleventh and last, fiscal gates: the credit gate at order creation, the overpayment cap at payment posting, and index availability for index-exposed gallons.

## 3. Business Logic & Workflows

### 3.1. Building the Physical Estate: Terminals, Freight Zones, and Trucks

A `SupplyAdmin` commissions a terminal by providing its `name`, a `region_code` such as a regional designator, the physical `storage_capacity_gal` (strictly positive), the `reserve_floor_gal` (zero or more), the `winter_reserve_floor_gal` (at least the non-winter floor), and the `rack_bay_count` (at least one). The new terminal starts with `on_hand_gal` at 0, `allocation_posture` of `NORMAL`, an `ops_epoch` of 0, and `version` 1.

Delivered pricing needs destination zones. Against a terminal, a `SupplyAdmin` registers freight zones with a `zone_code` unique within that terminal (a duplicate is rejected with `ERR_DUPLICATE_ZONE_CODE`), a strictly positive `one_way_drive_minutes`, a non-negative `freight_mc_per_gal` rate, and a non-negative `min_freight_cents` per-load floor. A zone belongs to exactly one terminal, and an order naming a zone owned by a different terminal than its own is rejected with `ERR_ZONE_TERMINAL_MISMATCH`.

The fleet is managed likewise: each transport truck is created under a home terminal with a `unit_number` unique per terminal (duplicates rejected with `ERR_DUPLICATE_TRUCK_UNIT`), a strictly positive tank `capacity_gal`, and a strictly positive `weekly_hours_limit_minutes` driver hours-of-service allowance. A truck starts `AVAILABLE`. While a truck is `OUT_OF_SERVICE`, it cannot take new schedules, and taking it out of service returns each of its `SCHEDULED` orders to `ALLOCATED` — `truck_id` and `est_trip_minutes` are cleared and the committed hours and rack occupancy are released. Returning the truck to `AVAILABLE` makes it schedulable again. A truck exposes `weekly_committed_minutes`, computed on read: the sum of `est_trip_minutes` over its orders in `SCHEDULED`, `LOADED`, or `DELIVERED` whose `planned_load_start` falls inside the ISO week (bounded Monday 00:00 UTC) containing the logical clock's current instant.

A computed inventory summary is available for every terminal, reporting `on_hand_gal`, `reserved_gal`, `effective_reserve_floor_gal`, `available_to_promise_gal`, the derived `season_posture`, the current `allocation_posture`, and `open_request_gal`, the gallons sitting in requests still awaiting allocation.

### 3.2. Buying Product: Supply Contracts and Rail Movements

Upstream supply is contracted per receiving terminal. A `SupplyAdmin` creates a supply contract naming the `terminal_id`, the upstream `supplier_name`, a strictly positive `contracted_volume_gal`, and a receipt window bounded by `receipt_window_start` and `receipt_window_end` with the end on or after the start. The contract begins in `DRAFT` with `delivered_volume_gal` at 0.

Activation moves a `DRAFT` contract to `ACTIVE`; the window end must be on or after the window start, or the attempt fails with `ERR_WINDOW_INVALID`. A contract whose window is inverted at creation meets the same rejection. Cancellation is possible from `DRAFT` or `ACTIVE` and moves the contract to `CANCELLED`; its rail shipments still in `TENDERED` or `IN_TRANSIT` are cancelled with it, while shipments already `ARRIVED` or `UNLOADED` are unaffected.

Against a contract, the `SupplyAdmin` tenders rail shipments with a `supply_contract_id`, a strictly positive manifest `volume_gal`, a strictly positive `railcar_count`, and a `scheduled_arrival_date` that must fall inside the contract's receipt window — an arrival date outside it is rejected with `ERR_SHIPMENT_WINDOW_VIOLATION`. At creation the shipment's `terminal_id` is copied from its contract, and the shipment begins in `TENDERED` with `unloaded_at` null.

Rail shipments advance along a strict conveyor: from `TENDERED` to `IN_TRANSIT`, from `IN_TRANSIT` to `ARRIVED`, and from `ARRIVED` to `UNLOADED`, each step requested by the `SupplyAdmin` naming a `to_state`. Any jump outside the legal edges is rejected with `ERR_INVALID_STATE`. A shipment may be cancelled from `TENDERED` or `IN_TRANSIT`, either directly or because its contract was cancelled or defaulted; `ARRIVED` and `UNLOADED` shipments can never be cancelled.

The unload is the moment product becomes inventory. Unloading requires the contract to be `ACTIVE` — otherwise the transition is rejected with `ERR_CONTRACT_NOT_ACTIVE`. On unload, the terminal's `on_hand_gal` increases by the shipment's `volume_gal` (bumping `Terminal.version`), the contract's `delivered_volume_gal` increases by the same amount, and `unloaded_at` is stamped with the current instant. If the delivered volume has now reached or exceeded the `contracted_volume_gal`, the contract transitions to `COMPLETED`, and no further rail shipments may be created or advanced under it.

### 3.3. The Dealer Book: Credit Master Data and Dealer Contracts

A `CreditManager` onboards a dealer with its `legal_name` and a strictly positive `credit_limit_cents`. The dealer begins with `fee_balance_cents` at 0, no orders, and — per the threshold rule below — a `credit_status` of `GOOD_STANDING`. The credit limit may later be raised or lowered; the update bumps `Dealer.version` and immediately re-evaluates the dealer's credit posture, which may flip between `WATCH` and `SUSPENDED` or back to `GOOD_STANDING` as the numbers dictate.

A dealer's exposure is computed on read, never stored, and never bumps `version`. The `ledger_exposure_cents` is the backward-looking view: the sum of `open_balance_cents` over the dealer's orders whose `invoice_status` is `OPEN`. The `committed_exposure_cents` is the forward-looking view used by credit decisions: the `fee_balance_cents`, plus the ledger exposure, plus the sum of `final_total_cents` over the dealer's `LOADED` orders, plus the sum of `provisional_total_cents` over the dealer's `ALLOCATED` and `SCHEDULED` orders. Orders in `REQUESTED`, `SHORTED`, or `CANCELLED` contribute nothing, and a delivered order contributes through its open invoice balance.

Credit posture follows a fixed threshold ladder evaluated with integer cross-multiplication. When `committed_exposure_cents` reaches or exceeds `credit_limit_cents`, the dealer is `SUSPENDED`. Otherwise, when five times the committed exposure reaches or exceeds four times the credit limit — an exposure of exactly eighty percent crosses the line — the dealer is `WATCH`. Below that, the dealer is `GOOD_STANDING`. The posture is re-evaluated after every mutation touching exposure: order creation, cancellation, load, delivery, payment posting, payment return, cold-snap repricing, and credit-limit changes. While a dealer is `WATCH`, every index-exposed gallon it prices carries a credit-watch surcharge of 15 cents per gallon; a dealer never pays the watch surcharge while `SUSPENDED`, because its orders are rejected at creation with `ERR_DEALER_SUSPENDED`.

A `CreditManager` writes dealer contracts against a supply point, providing the `dealer_id`, `terminal_id`, a `pricing_mode` of `INDEX` or `FIXED`, a strictly positive committed band `volume_committed_gal`, and a validity window from `window_start` to `window_end` with the end on or after the start (an inverted window is rejected with `ERR_WINDOW_INVALID`). When `pricing_mode` is `FIXED`, a strictly positive `fixed_price_mc_per_gal` is required; it is the product price for in-band gallons and is absent on `INDEX` contracts. The contract begins in `DRAFT` with `volume_drawn_gal` at 0.

Activation by a `CreditManager` is the guarded write of §2.6: the request must carry `expected_dealer_version` matching the dealer's current `version`, failing with `ERR_STALE_DEALER_VERSION` on a mismatch, and the dealer must not be `SUSPENDED`, failing with `ERR_DEALER_SUSPENDED`. On success the contract's `status` becomes `ACTIVE`, and any other `ACTIVE` contract for the same dealer at the same terminal whose window overlaps the new contract's window moves to `SUPERSEDED`. Supersession cascades: the superseded contract's orders in `REQUESTED` or `ALLOCATED` move to `CANCELLED` (releasing their reserved gallons), its `SCHEDULED` orders are first unscheduled — truck and hours released — and then cancelled. The activation also bumps `Dealer.version` as bookkeeping on the parent. Cancelling a contract from `DRAFT` or `ACTIVE` performs the same order cascade; orders already `LOADED` or `DELIVERED` and any open invoices are unaffected. A contract that outlives its window moves to `EXPIRED` at the daily epoch; its open orders keep their pricing snapshot but can no longer be scheduled, because scheduling requires an `ACTIVE` contract.

### 3.4. Ordering Product: Creation, Pricing Snapshots, and the Credit Gate

A `DealerUser` creates delivery orders; the order's `dealer_id` is copied from the caller's `X-User-ID`, never supplied in the payload. The request names the `terminal_id`, the `freight_zone_id` of the destination, a `requested_gal` of at least 1000 gallons (anything less, or a non-integer, is rejected with `ERR_VOLUME_INVALID`), and optionally a `dealer_contract_id`. Omitting the contract produces a `SPOT` order priced at the index plus a spot premium of 40 cents per gallon. Supplying a contract snapshots its pricing mode onto the order as `FIXED` or `INDEX`; in that case the contract must belong to the calling dealer (`ERR_CONTRACT_DEALER_MISMATCH`), must be anchored at the order's terminal (`ERR_CONTRACT_TERMINAL_MISMATCH`), must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), and the creation date must fall inside the contract window (`ERR_OUTSIDE_CONTRACT_WINDOW`).

What happens next depends on the terminal's posture. At a `NORMAL` terminal, creation is a fast path: the order is allocated immediately, `fulfillment_status` becomes `ALLOCATED`, `allocated_gal` equals `requested_gal`, and `provisional_total_cents` is stamped at once. The fast path requires `requested_gal` to be no greater than the terminal's `available_to_promise_gal` — exactly equal succeeds, one gallon over fails with `ERR_INSUFFICIENT_SUPPLY`. At a `CURTAILED` terminal there is no allocation check at creation: the order lands in `REQUESTED` with `allocated_gal` null and `provisional_total_cents` null, waiting for an allocation run.

Either way, the credit gate runs at creation, in a pinned evaluation order. First, `committed_before` is computed: the dealer's committed exposure excluding the candidate order. Second, the threshold ladder of §3.3 maps `committed_before` to a `status_before`; a `SUSPENDED` dealer is rejected here with `ERR_DEALER_SUSPENDED` and never reaches pricing. Third, if `status_before` is `WATCH`, a watch surcharge of 15 cents per gallon applies to index-exposed gallons; otherwise the surcharge is zero. Fourth, a provisional delivered price is computed — transiently even for curtailed orders that will land in `REQUESTED`. Fifth, the gate itself: if `committed_before` plus the order's provisional total exceeds `credit_limit_cents`, creation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

### 3.5. The Delivered Price Engine

Every order total is the sum of four independently rounded segments — in-band product, overage product, freight, and winter surcharge — each rounded half-up to integer cents before summing (§2.7). The volume priced is `allocated_gal`; at creation, where allocation is still pending, `requested_gal` stands in as the pending allocation.

The index basis for all `INDEX` and `SPOT` pricing is `MT_BELVIEU`. Resolving the index for a reference date means finding the publication for that index whose `effective_date` is the greatest one on or before the reference date; publications are unique per index and date, and a duplicate pair is rejected with `ERR_DUPLICATE_INDEX_PUBLICATION`. A `PricingDesk` publishes prices with an `index_name` of `MT_BELVIEU` or `CONWAY`, an `effective_date`, and a strictly positive `price_mc_per_gal`; the publication log is append-only. A read-only resolution capability answers, for a given `index_name` and `on_date`, the publication in effect. Index resolution inside pricing is lazy: it happens only when an index-exposed gallon exists — any gallon of a `SPOT` order, the band gallons of an `INDEX` contract, or the overage gallons of a `FIXED` contract. When such a gallon exists and no publication is effective on the reference date, the operation fails with `ERR_NO_INDEX_PUBLISHED`.

For a `SPOT` order, the product segment is the volume times the sum of the resolved index price, the 40-cent-per-gallon spot premium, and any applicable watch surcharge, converted from millicents to cents with half-up rounding. For a contract order, the volume splits: `in_band_gal` is the smaller of the priced volume and the remaining committed band (the greater of zero and `volume_committed_gal` minus `volume_drawn_gal`), and `over_gal` is the rest. In-band gallons price at the contract's `fixed_price_mc_per_gal` for `FIXED` contracts, or at the resolved index for `INDEX` contracts — and only `INDEX` in-band gallons carry the watch surcharge, never `FIXED` ones. Overage gallons always price at the index plus an overage premium of 25 cents per gallon, plus the watch surcharge when applicable. The two product segments are rounded separately.

The freight segment is the greater of the zone's `min_freight_cents` and the volume times the zone's `freight_mc_per_gal` converted to cents with half-up rounding. The winter segment applies whenever the terminal's `allocation_posture` is `CURTAILED` at pricing time: the volume times a winter surcharge of 30 cents per gallon, converted with half-up rounding; at a `NORMAL` terminal it is zero.

Two variants of the price exist. The provisional variant is computed at order creation, re-stamped on every entry into `ALLOCATED`, and re-stamped on every `ALLOCATED` or `SCHEDULED` order whenever the terminal's posture flips; its reference date is the current logical-clock date and its winter leg uses the terminal's current posture. The final variant is computed exactly once, at the moment a `SCHEDULED` order is loaded; its reference date is the calendar date of `planned_load_start`, its winter leg uses the posture at the load transition, and the `volume_drawn_gal` used for banding is the value before this load's draw is applied. The provisional lives in `provisional_total_cents` (null while the order is `REQUESTED`), the final in `final_total_cents` (null until loading).

### 3.6. Dispatch: Scheduling, Loading, and Delivery

Scheduling is the `Dispatcher`'s act of placing an `ALLOCATED` order onto a truck and a rack window by supplying a `truck_id`, a `planned_load_start`, and a `planned_load_end`. The window end must be strictly after the window start, else `ERR_WINDOW_INVALID`. Seven checks guard the transition. The truck must be `AVAILABLE` (`ERR_TRUCK_NOT_AVAILABLE`). The truck's home terminal must equal the order's terminal (`ERR_TRUCK_TERMINAL_MISMATCH`). The order's `allocated_gal` must not exceed the truck's `capacity_gal` (`ERR_TRUCK_CAPACITY_EXCEEDED`). The estimated trip must fit the driver-hours budget: the trip estimate is 90 minutes of rack service time plus twice the zone's `one_way_drive_minutes`, and the truck's `weekly_committed_minutes` plus this candidate's `est_trip_minutes` must not exceed `weekly_hours_limit_minutes` — equality is allowed, one minute over is rejected with `ERR_DRIVER_HOURS_EXCEEDED`. The buffered truck window must not overlap any other order on the same truck in `SCHEDULED`, `LOADED`, or `DELIVERED`: each order occupies an interval from 60 minutes before its `planned_load_start` to 60 minutes after its `planned_load_end`, half-open, and two occupied intervals conflict when the later start falls strictly before the earlier end — exact back-to-back at the buffer boundary is fine, one minute of intersection is a conflict rejected with `ERR_TRUCK_SCHEDULE_CONFLICT`. The rack must have a bay: counting the terminal's orders in `SCHEDULED` or `LOADED` whose raw, unbuffered windows overlap the candidate's raw window, the schedule is rejected with `ERR_RACK_CAPACITY_EXCEEDED` when that count already equals `rack_bay_count` — so exactly `rack_bay_count` overlapping windows are permitted and the next one is refused. Finally, if the order carries a contract, the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the calendar date of `planned_load_start` must fall inside the contract window (`ERR_OUTSIDE_CONTRACT_WINDOW`). On success the order becomes `SCHEDULED`, `truck_id` is set, and `est_trip_minutes` is stored.

Unscheduling reverses this: the order returns from `SCHEDULED` to `ALLOCATED`, `truck_id` and `est_trip_minutes` are cleared, and the committed hours and window occupancy are released. The same reversal happens automatically when the assigned truck is taken `OUT_OF_SERVICE`.

Loading is the rack-floor safety gate. A `Dispatcher` may load a `SCHEDULED` order only if, after drawing the order's gallons, the terminal still holds at least its effective reserve floor — that is, `on_hand_gal` minus `allocated_gal` must be at least `effective_reserve_floor_gal`, season-dependent per §2.8 — or the load is rejected with `ERR_RESERVE_FLOOR_BREACH`. Loading stamps `final_total_cents` using the final pricing variant (which can fail with `ERR_NO_INDEX_PUBLISHED` if an index-exposed gallon has no publication), decrements the terminal's `on_hand_gal` by `allocated_gal` (bumping `Terminal.version` and shrinking `reserved_gal`), and adds the in-band gallons — the smaller of `allocated_gal` and the remaining committed band — to the contract's `volume_drawn_gal`; overage gallons are never added to the band draw. The order is now `LOADED`.

Delivery opens the invoice. When a `Dispatcher` delivers a `LOADED` order, `fulfillment_status` becomes `DELIVERED`, the parallel `invoice_status` moves from `NOT_READY` to `OPEN`, `open_balance_cents` is set to `final_total_cents`, and `invoiced_at` is stamped with the current instant; the dealer's ledger exposure grows by the final total.

Cancellation is available from `REQUESTED`, `ALLOCATED`, `SHORTED`, or `SCHEDULED` — never from `LOADED` or beyond, and never from `DELIVERED`. A `DealerUser` may cancel only its own orders (any other attempt is `ERR_DEALER_MISMATCH`); a `Dispatcher` may cancel any. Cancelling a `SCHEDULED` order first performs the unschedule release, then cancels. Cancelling an `ALLOCATED` order releases its reserved gallons. In every case the invoice dimension moves from `NOT_READY` to `VOID`.

### 3.7. Scarcity: Cold Snaps, Curtailment, and Allocation Runs

A `SupplyPlanner` declares a cold-snap event against a terminal with a `severity` of `WATCH`, `WARNING`, or `EMERGENCY`, a `start_date`, and an `end_date` on or after the start. The event begins as `DECLARED`. Activation — manual, or by the daily epoch once `start_date` is reached — requires that no other event on the same terminal is already `ACTIVE`, failing with `ERR_COLD_SNAP_ALREADY_ACTIVE` otherwise.

Activation curtails the terminal: `allocation_posture` flips from `NORMAL` to `CURTAILED`, bumping `Terminal.version`. The cascade is immediate and atomic. Every order of this terminal in `ALLOCATED` or `SCHEDULED` has its `provisional_total_cents` recomputed, now including the 30-cent winter surcharge. Each affected dealer's committed exposure is recomputed from the new provisionals, and credit postures may flip from `GOOD_STANDING` to `WATCH` or `SUSPENDED`. New orders at the curtailed terminal land in `REQUESTED` with no fast-path allocation and no ATP check at creation.

Lifting — manual, or by the daily epoch once `end_date` has passed — moves the event to `LIFTED`, its terminal state, and restores the terminal. The posture flips back to `NORMAL`, provisionals on `ALLOCATED` and `SCHEDULED` orders are re-stamped with the surcharge removed, every `SHORTED` order at the terminal returns to `REQUESTED` with its original `created_at` preserved, and then a FIFO auto-allocation sweep runs: the terminal's `REQUESTED` orders are visited oldest first by `created_at`, ties broken by larger `requested_gal` first, and each order is independently allocated — `allocated_gal` set to `requested_gal`, provisional re-stamped — whenever `available_to_promise_gal` is at least the request; an order that does not fit stays `REQUESTED` and never blocks later orders.

Against a curtailed terminal, the `SupplyPlanner` runs rationing. Creating an allocation run is the terminal-side guarded write of §2.6, requiring `expected_terminal_version`; creation moves any existing `OPEN` or `COMPUTED` run on the same terminal to `SUPERSEDED`, bumps `Terminal.version`, and assigns the next per-terminal `run_index`, starting at 1. A `SUPERSEDED` run rejects every further action with `ERR_INVALID_STATE`. The new run is `OPEN` with `pool_gal` null and `results` empty.

Computing the run requires the terminal to be `CURTAILED` (`ERR_TERMINAL_NOT_CURTAILED`). The pool is a snapshot of `available_to_promise_gal` taken at compute time into `pool_gal`. Eligible orders are the terminal's orders in `REQUESTED` created before the run itself. Allocation proceeds tier by tier: tier 1 holds `FIXED`-contract orders, tier 2 holds `INDEX`-contract orders, tier 3 holds `SPOT` orders. Within tiers 1 and 2 an order's weight is the sum of `volume_committed_gal` over its dealer's `ACTIVE` dealer contracts at this terminal; each tier-3 order has weight 1. For each tier, every unserved candidate's raw share is the pool times its weight divided by the tier's total weight, an exact rational; the order's share is floored and capped at its `requested_gal` — floor first, never above the request. The remainder after flooring is then distributed one gallon at a time to orders still below their request, oldest `created_at` first with larger `requested_gal` breaking ties, looping until the remainder is gone or every order is satisfied. No share ever exceeds the request. The pool is reduced by the tier's allocations before the next tier begins. Any order never reached, or allocated zero, is recorded with outcome `SHORTED`. Each result row carries the `order_id`, its `allocated_gal`, and its outcome.

Ratifying a `COMPUTED` run — attempting it in any other state is `ERR_RUN_NOT_COMPUTED` — applies the results: each order with a positive share moves from `REQUESTED` to `ALLOCATED` with `allocated_gal` set to the share and a provisional stamped, and each zero-share order moves to `SHORTED` with `allocated_gal` 0 and `provisional_total_cents` null. The run becomes `RATIFIED`, a terminal state.

### 3.8. Money In: Payments, FIFO Application, and Returns

A `CreditManager` posts a dealer payment with a `dealer_id`, a strictly positive `amount_cents`, and a `method` of `ACH`, `CHECK`, or `WIRE`. The amount must not exceed the dealer's total open invoice balance — the `ledger_exposure_cents` — or posting is rejected with `ERR_OVERPAYMENT`. On posting, the payment is `POSTED` and is applied FIFO: the dealer's orders with `invoice_status` `OPEN` are visited in `invoiced_at` order, earliest first, ties broken by `created_at`; each receives a slice of the smaller of the remaining payment and that order's `open_balance_cents`, the slice is recorded in the payment's `applications` in application order as `order_id` and `amount_cents` pairs, and any order whose balance reaches zero moves from `OPEN` to `PAID`. The dealer's credit posture is then recomputed.

A returned payment — a bounced check or failed ACH — is unwound by a `CreditManager`. Only a `POSTED` payment can be returned; a second attempt fails with `ERR_PAYMENT_ALREADY_RETURNED`. The return reverses this payment's applications in reverse application order: each order's `open_balance_cents` is increased by its reversed slice, and an order whose balance is restored above zero moves from `PAID` back to `OPEN`. The dealer's `fee_balance_cents` increases by a fixed insufficient-funds fee, bumping `Dealer.version`, and the dealer's exposure and credit posture are recomputed — a dealer may slide from `WATCH` into `SUSPENDED` on the strength of a return.

### 3.9. The Daily Ops Epoch

A `SystemAdmin` advances the daily ops epoch across every terminal in one atomic run. The epoch activates each `DECLARED` cold-snap event whose `start_date` is today or in the past, firing the full curtail cascade per §3.7. It lifts each `ACTIVE` event whose `end_date` has passed, firing the full lift cascade including the FIFO requeue. It expires each `ACTIVE` dealer contract whose `window_end` has passed. It settles each `ACTIVE` supply contract whose `receipt_window_end` has passed: to `COMPLETED` if the delivered volume reached the contracted volume, otherwise to `DEFAULTED`, with its `TENDERED` and `IN_TRANSIT` shipments cancelled (`ARRIVED` shipments are unaffected and may still unload). Finally, every terminal's `ops_epoch` increments by one, bumping `Terminal.version`. The run reports counts: `cold_snaps_activated`, `cold_snaps_lifted`, `dealer_contracts_expired`, `supply_contracts_completed`, `supply_contracts_defaulted`, and `shipments_cancelled`.

Throughout, the two status dimensions of a delivery order evolve independently: `fulfillment_status` walks the physical pipeline while `invoice_status` walks the money pipeline, and neither implies the other except at the two bridges — delivery opens the invoice, and pre-delivery cancellation voids it.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a transition return `200 OK`. Request and response shapes for each operation are governed by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving; startup default 2026-08-01T00:00:00Z) | SystemAdmin |
| POST | `/ops/run_epoch` | Advance the daily ops epoch for every terminal | SystemAdmin |
| POST | `/terminals` | Create a terminal | SupplyAdmin |
| GET | `/terminals/{id}` | Get terminal | SupplyAdmin, SupplyPlanner, Dispatcher, CreditManager, SystemAdmin |
| GET | `/terminals/{id}/inventory-summary` | Computed read of terminal inventory posture | SupplyAdmin, SupplyPlanner, Dispatcher, CreditManager, SystemAdmin |
| POST | `/supply-contracts` | Create a supply contract (DRAFT) | SupplyAdmin |
| GET | `/supply-contracts/{id}` | Get supply contract | SupplyAdmin, SupplyPlanner |
| GET | `/supply-contracts` | List supply contracts (filter by terminal, status) | SupplyAdmin, SupplyPlanner |
| POST | `/supply-contracts/{id}/activate` | Activate a DRAFT supply contract | SupplyAdmin |
| POST | `/supply-contracts/{id}/cancel` | Cancel a supply contract; cascades to open rail shipments | SupplyAdmin |
| POST | `/rail-shipments` | Tender a rail shipment under a supply contract | SupplyAdmin |
| GET | `/rail-shipments/{id}` | Get rail shipment | SupplyAdmin, SupplyPlanner, Dispatcher |
| GET | `/rail-shipments` | List rail shipments (filter by contract, terminal, status) | SupplyAdmin, SupplyPlanner, Dispatcher |
| POST | `/rail-shipments/{id}/transition` | Advance rail shipment along its conveyor, or cancel | SupplyAdmin |
| POST | `/dealers` | Create a dealer | CreditManager |
| GET | `/dealers/{id}` | Get dealer (DealerUser limited to self) | CreditManager, DealerUser |
| GET | `/dealers` | List dealers (filter by credit status) | CreditManager |
| PATCH | `/dealers/{id}` | Update credit limit; re-evaluates credit status | CreditManager |
| POST | `/dealer-contracts` | Create a dealer contract (DRAFT) | CreditManager |
| GET | `/dealer-contracts/{id}` | Get dealer contract (DealerUser limited to own) | CreditManager, DealerUser, SupplyPlanner |
| GET | `/dealer-contracts` | List dealer contracts (filter by dealer, terminal, status) | CreditManager, DealerUser, SupplyPlanner |
| POST | `/dealer-contracts/{id}/activate` | Activate a DRAFT contract (OCC on Dealer.version); supersedes overlapping ACTIVE contract | CreditManager |
| POST | `/dealer-contracts/{id}/cancel` | Cancel a contract; cascades to its non-terminal orders | CreditManager |
| POST | `/price-index-publications` | Publish an index price (append-only) | PricingDesk |
| GET | `/price-index-publications/{id}` | Get one publication | PricingDesk, CreditManager, SupplyPlanner, SupplyAdmin, Dispatcher, DealerUser |
| GET | `/price-index-publications` | List publications (filter by index, effective date) | PricingDesk, CreditManager, SupplyPlanner, SupplyAdmin, Dispatcher, DealerUser |
| GET | `/price-index-publications/resolve` | Resolve the price effective on a date for an index | PricingDesk, CreditManager, SupplyPlanner, SupplyAdmin, Dispatcher, DealerUser |
| POST | `/freight-zones` | Create a freight zone for a terminal | SupplyAdmin |
| GET | `/freight-zones/{id}` | Get freight zone | SupplyAdmin, SupplyPlanner, Dispatcher, CreditManager, DealerUser |
| GET | `/freight-zones` | List freight zones (filter by terminal) | SupplyAdmin, SupplyPlanner, Dispatcher, CreditManager, DealerUser |
| POST | `/trucks` | Create a transport truck | SupplyAdmin |
| GET | `/trucks/{id}` | Get truck | SupplyAdmin, SupplyPlanner, Dispatcher |
| GET | `/trucks` | List trucks (filter by terminal, status) | SupplyAdmin, SupplyPlanner, Dispatcher |
| POST | `/trucks/{id}/transition` | Set truck status; OUT_OF_SERVICE unschedules its SCHEDULED orders | SupplyAdmin, Dispatcher |
| POST | `/delivery-orders` | Dealer creates a delivery order; NORMAL terminal allocates directly, CURTAILED lands REQUESTED | DealerUser |
| GET | `/delivery-orders/{id}` | Get delivery order (DealerUser limited to own) | DealerUser, CreditManager, Dispatcher, SupplyPlanner, SupplyAdmin |
| GET | `/delivery-orders` | List delivery orders (filter by dealer, terminal, contract, truck, zone, statuses) | DealerUser, CreditManager, Dispatcher, SupplyPlanner, SupplyAdmin |
| POST | `/delivery-orders/{id}/schedule` | Schedule an ALLOCATED order onto a truck and rack window | Dispatcher |
| POST | `/delivery-orders/{id}/unschedule` | Unschedule a SCHEDULED order back to ALLOCATED | Dispatcher |
| POST | `/delivery-orders/{id}/load` | Load a SCHEDULED order: final pricing, terminal draw, contract band draw | Dispatcher |
| POST | `/delivery-orders/{id}/deliver` | Deliver a LOADED order: opens the invoice | Dispatcher |
| POST | `/delivery-orders/{id}/cancel` | Cancel a pre-LOADED order (DealerUser own only) | DealerUser, Dispatcher |
| POST | `/cold-snap-events` | Declare a cold-snap event (DECLARED) | SupplyPlanner |
| GET | `/cold-snap-events/{id}` | Get cold-snap event | SupplyPlanner, SupplyAdmin, Dispatcher, CreditManager, DealerUser |
| GET | `/cold-snap-events` | List cold-snap events (filter by terminal, status) | SupplyPlanner, SupplyAdmin, Dispatcher, CreditManager, DealerUser |
| POST | `/cold-snap-events/{id}/activate` | Activate a DECLARED cold snap: curtails the terminal | SupplyPlanner |
| POST | `/cold-snap-events/{id}/lift` | Lift an ACTIVE cold snap: restores the terminal and requeues SHORTED orders | SupplyPlanner |
| POST | `/allocation-runs` | Create an allocation run (OCC on Terminal.version); supersedes existing OPEN/COMPUTED run | SupplyPlanner |
| GET | `/allocation-runs/{id}` | Get allocation run including results | SupplyPlanner, SupplyAdmin |
| GET | `/allocation-runs` | List allocation runs (filter by terminal, status) | SupplyPlanner, SupplyAdmin |
| POST | `/allocation-runs/{id}/compute` | Compute the pro-rata waterfall over eligible REQUESTED orders (terminal must be CURTAILED) | SupplyPlanner |
| POST | `/allocation-runs/{id}/ratify` | Ratify a COMPUTED run: applies allocations to orders | SupplyPlanner |
| POST | `/dealer-payments` | Post a dealer payment; FIFO-applied to OPEN invoices | CreditManager |
| GET | `/dealer-payments/{id}` | Get payment (DealerUser limited to own) | CreditManager, DealerUser |
| GET | `/dealer-payments` | List payments (filter by dealer, status) | CreditManager, DealerUser |
| POST | `/dealer-payments/{id}/return` | Return (NSF) a POSTED payment: reverses applications, posts NSF fee | CreditManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_DEALER_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_NOT_FOUND` | 422 |
| `ERR_STALE_TERMINAL_VERSION` | 412 |
| `ERR_STALE_DEALER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_DEALER_SUSPENDED` | 409 |
| `ERR_TRUCK_NOT_AVAILABLE` | 409 |
| `ERR_TERMINAL_NOT_CURTAILED` | 409 |
| `ERR_COLD_SNAP_ALREADY_ACTIVE` | 409 |
| `ERR_RUN_NOT_COMPUTED` | 409 |
| `ERR_PAYMENT_ALREADY_RETURNED` | 409 |
| `ERR_DRIVER_HOURS_EXCEEDED` | 422 |
| `ERR_RESERVE_FLOOR_BREACH` | 422 |
| `ERR_TRUCK_CAPACITY_EXCEEDED` | 422 |
| `ERR_TRUCK_TERMINAL_MISMATCH` | 422 |
| `ERR_ZONE_TERMINAL_MISMATCH` | 422 |
| `ERR_CONTRACT_TERMINAL_MISMATCH` | 422 |
| `ERR_CONTRACT_DEALER_MISMATCH` | 422 |
| `ERR_TRUCK_SCHEDULE_CONFLICT` | 409 |
| `ERR_RACK_CAPACITY_EXCEEDED` | 422 |
| `ERR_WINDOW_INVALID` | 400 |
| `ERR_OUTSIDE_CONTRACT_WINDOW` | 422 |
| `ERR_SHIPMENT_WINDOW_VIOLATION` | 422 |
| `ERR_DUPLICATE_ZONE_CODE` | 409 |
| `ERR_DUPLICATE_TRUCK_UNIT` | 409 |
| `ERR_DUPLICATE_INDEX_PUBLICATION` | 409 |
| `ERR_VOLUME_INVALID` | 400 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_NO_INDEX_PUBLISHED` | 422 |
| `ERR_INSUFFICIENT_SUPPLY` | 422 |
