# Truck Stop & Travel Center Operations API — Product Requirements Document

## 1. Introduction

A modern interstate travel center never sleeps. Around the clock, diesel lanes meter fuel to long-haul tractors, paid parking spots turn over through the night, drivers queue for showers and laundry, a certified scale weighs rigs, the restaurant and retail store ring thousands of small transactions, and a maintenance shop keeps freight moving — sometimes in a bay, sometimes forty miles up the highway on a road-service call. Behind all of it sit bulk tanks of diesel, DEF, and oil whose levels fall with every gallon dispensed, and a cash-control discipline that has to survive three shift changes a day without a discrepancy slipping through.

This document specifies a single REST API that operates such a site end to end. At its heart sits a pricing engine: retail pump prices are posted per fuel type with future-effective windows, fleet customers buy under tiered fuel contracts priced off the diesel rack replacement cost, third-party discount networks shave a fixed per-gallon allowance off the pump price for enrolled drivers, and a loyalty program lets drivers stack points redemptions on top of every one of those mechanisms. Around the pricing engine sit the capacity disciplines of the property — a bounded pool of reservable parking spaces, fixed counts of shower stalls and laundry machines, shop bays with maintenance blackouts — and the fiscal discipline of the fuel desk: registers with standard floats, shifts with a continuously computed expected cash position, controlled drops and payouts, and a closing reconciliation that leaves an auditable trail from drawer to safe.

Two technical commitments shape every workflow below. First, all time inside the system flows from a controllable logical clock rather than the wall clock, so price windows, loyalty-lot expiries, parking grace periods, and no-show deadlines are deterministic and testable. Second, the two objects whose mutation would silently corrupt downstream pricing — the site's fuel-price book and a fleet contract's commercial terms — are guarded by optimistic concurrency, so a writer working from a stale read is refused rather than allowed to overwrite an intervening change. Everything else follows from those two commitments: immediate consistency, derived fields recomputed on every mutation, and a validation pipeline whose order is itself part of the contract.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the acting role. A request with either header missing, or with a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized set is rejected with `ERR_FORBIDDEN` (HTTP 403).

Seven roles exist, spelled exactly as follows:

- `GeneralManager` — the site general manager; the superset role for site configuration, fleet and contract administration, points adjustments, discount-network governance, purchase-order approval, shift lock, and control of the logical clock.
- `ShiftManager` — the shift supervisor; owns the shift lifecycle (open, close, reconcile), approves payouts, and performs voids and refunds.
- `FuelDeskLead` — the fuel desk lead; posts retail fuel prices, takes pumps out of and back into service, and records bulk tank stick readings and deliveries.
- `Cashier` — the front-counter cashier on a shift; rings up fuel, store, parking, service, and scale transactions and records cash drops on their own shift.
- `MaintenanceTech` — a shop technician; operates assigned work orders and their parts.
- `FleetManager` — a fleet company operator; reads its own fleet subtree and approves estimates for its own fleet's work orders.
- `LoyaltyMember` — a driver loyalty member; self-service for reservations, service tickets, vehicles, and discount-network enrollments.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `MaintenanceTech`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's foreign-key field to `X-User-ID` — concretely, starting work and issuing or returning parts are permitted only on work orders whose `technician_id` equals the caller's `X-User-ID`. When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `FleetAccount`; the caller may read only its own fleet subtree (its account, contracts, fuel sales, work orders, and linked loyalty members) and may approve an estimate only on a work order whose `fleet_account_id` equals `X-User-ID`. When `X-User-Role` is `LoyaltyMember`, `X-User-ID` is the `id` of the acting `LoyaltyMember`; the caller may touch only resources whose `loyalty_member_id` equals `X-User-ID` — its own member record, points ledger, vehicles, enrollments, reservations, tickets, and sales. Violations of these entity-backed scoping rules are rejected with `ERR_FORBIDDEN` (HTTP 403).

For the remaining four roles — `GeneralManager`, `ShiftManager`, `FuelDeskLead`, and `Cashier` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it: a shift stamps the opener's `X-User-ID` into `opened_by_manager_id` and the closer's into `closed_by_manager_id`, and a shift carries the owning cashier's opaque id as `cashier_user_id`. The one comparison the server performs with an opaque id, besides the segregation-of-duties rules below, is cash-drop ownership: a `Cashier` may record a drop only on a shift whose `cashier_user_id` equals the caller's `X-User-ID`, and any other cashier attempting it is rejected with `ERR_FORBIDDEN`.

Segregation of duties is enforced on the shift cash lifecycle: the manager closing a shift must not be the manager who opened it, the manager reconciling a shift must not be the manager who closed it, and the manager approving a payout must not be the cashier who owns that shift's drawer. Any of these collisions is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- An undefined path, or an unsupported method on a defined path, is rejected in this same envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints accept two query parameters. `limit` bounds the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips leading records and defaults to 0. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in its `meta` object, where `total_count` is the full filtered result size and `has_more` reports whether records exist beyond the returned page. All list endpoints sort by `created_at` ascending, oldest first, with no alternate sort orders; ties on `created_at` break by insertion order. A non-integer or out-of-range `limit`, a negative or non-integer `offset`, and a filter value outside the endpoint's declared domain are each rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.4. Resource Identity, Timestamps and Versioning

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer starting at 1 that increments by exactly 1 on every mutation of the resource, including mutations caused by cascade side effects from other operations. Request bodies carry only the fields named for each endpoint in §3 and §4; any additional supplied fields — including client-supplied system fields (`id`, `created_at`, `updated_at`, `version`) and server-computed fields such as `is_low_stock` or `points_balance` — are ignored rather than rejected: the server always assigns system fields itself, and computed fields always take their server-computed values regardless of what the request carried. `created_at` and `updated_at` carry three fractional digits; timestamps stamped by workflow transitions (such as `opened_at`, `closed_at`, `checked_in_at`, `finalized_at`, `called_at`, `started_at`, `completed_at`, `checked_out_at`) and echoed window fields (such as `effective_from`, `effective_to`, `earned_at`, `expires_at`) are stored at whole-second precision.

Six record types are deliberately thinner, carrying only `id` and `created_at` with no `updated_at` and no `version`: the `ScaleWeighEvent` (an append-only scale reading), the `CashDrop` (a posted drop), the `ShiftReconciliation` (the record written at shift close), the `SafeDeposit` (the deposit recorded at close), the `BulkDelivery` (a delivery receipt), and the `LoyaltyPointsLot` (a points grant or clawback). These are immutable ledger-style records; once written they are never updated in place.

### 2.5. The Logical Clock and Time Windows

All temporal evaluation in the system — price-window effectiveness, loyalty-lot expiry, parking grace and no-show deadlines, contract windows, rolling fleet volumes — reads a single logical clock. Before it has ever been set, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `GeneralManager` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; any role may read `current_utc`. The clock moves only forward: a `to_iso8601` earlier than the current reading is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Expirations are lazy: points lots, price windows, and grace deadlines are evaluated against the logical clock at the moment of the next read or write that depends on them, not by a background sweeper.

Time windows are half-open unless explicitly stated otherwise: a window runs from its start instant inclusive to its end instant exclusive. This convention governs fuel-price windows (`effective_from` through `effective_to`), contract windows, parking reservation windows (`reserved_from` through `reserved_to`), and work-order schedule windows (`scheduled_from` through `scheduled_to`). The single exception is a bay maintenance block, whose `blocked_from` and `blocked_to` form a closed interval that a schedule window may not even touch.

### 2.6. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency guard; no other endpoint accepts a version field of any kind.

Posting a new retail fuel price against a site requires the request to carry `expected_site_version`, holding the `version` of the `TravelCenterSite` the client last observed. Because creating a price legitimately supersedes or truncates existing `ACTIVE` prices of the same fuel type, a writer working from a stale site read would silently double-supersede; instead, when `expected_site_version` does not match the site's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful price posting increments the site's `version` by 1.

Amending a fleet contract requires the request to carry `expected_contract_version`, holding the `version` of the `FleetContract` the client last observed. An amendment changes `discount_per_gallon_off` or the effective window for future authorizations, and a writer working from a stale contract read would silently overwrite an intervening amendment; when `expected_contract_version` does not match the contract's current `version`, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful amendment increments the contract's `version` by 1.

On both guards the expected-version field is evaluated immediately after the path resource loads, so a stale version masks every later validation failure of the request. A missing or non-integer expected-version field is not a stale read: it is a malformed body, rejected with `ERR_INVALID_REQUEST` (HTTP 400) at the final validation stage.

### 2.7. Precision, Rounding and Measurement Conventions

All money is carried as integer cents. Every rounding of a monetary value uses round half up — a discarded fraction of exactly one half rounds away from zero — and each rounding step is applied at the point its rule specifies, never deferred. Two exceptions carry finer precision by design. Bulk rack pricing for diesel is computed in dollars per gallon with four decimal places, rounded half up at four decimals before conversion to cents; once multiplied by one hundred, the result is rounded half up to integer cents. Volumes are measured in gallons: dispensed fuel and fleet rolling volumes carry three decimal places, tank inventories and reorder arithmetic carry two, and site water-usage accumulation carries two decimal places rounded half up. Where a time quantity must be whole — billed parking hours, case-pack counts — the rule rounds up to the next whole unit. Loyalty points are integers, rounded half up per accrual source as described in §2.9.

### 2.8. The Shift Cash Ledger and Register Posture

Every cash-affecting event on the property is attributed to exactly one open shift, and each shift maintains a continuously computed book position, `expected_cash_cents`. The evaluation order is pinned to remove any circular reading between the expected position and the bank deposit: first, expected cash equals the shift's `opening_float_cents`, plus every cash receipt attributed to the shift (cash fuel payments, cash store sales, cash parking check-in charges, cash service payments, cash scale settlements, and cash work-order collections), minus every approved payout, minus every posted cash drop, minus every cash refund attributed to the shift; second, at close only, the deposit total is the amount by which expected cash exceeds the opening float, floored at zero; third, the variance is the physical count minus the expected position, a positive value being an overage. There is no physical-count view of the drawer during the shift — the book view is the only system function, and only the shift-close operation accepts a counted figure.

Any money-collecting operation — drops, payouts, cash payments of any kind, and close itself — requires its target shift to be `OPEN`; against a closed, reconciled, or locked shift the operation is rejected with `ERR_SHIFT_NOT_OPEN` (HTTP 409). Refund and reversal postings are the exception: the cash decrements applied by refund-voids, paid cancellations, and store-sale refunds post against the attributed shift in whatever state it is, without requiring it to be `OPEN`.

Each register derives a cash posture from the shift currently open on it. Posture is `NEEDS_DROP` when the open shift's expected cash exceeds five times the register's `float_cents`, `LOW_FLOAT` when expected cash has fallen below one times the float (the drawer holds less than its standard float), and `OK` otherwise. A register with no `OPEN` shift always reads `OK`. The posture is recomputed after every event that moves the shift's expected cash — payments, refunds, drops, payouts, open, and close — so the need for a drop or the risk of a thin drawer surfaces immediately.

### 2.9. The Loyalty Points Ledger

Loyalty value lives in an append-only ledger of points lots. Every accrual writes a `LoyaltyPointsLot` recording `points` granted, `remaining_points` initialized to the full grant, the `source_type` of the originating activity — one of `FUEL_SALE`, `STORE_SALE`, `SERVICE`, `PARKING`, or `ADJUSTMENT` — the originating record's identifier as `source_id`, the grant instant as `earned_at`, and an `expires_at` exactly 360 days after the grant. A member's `points_balance` is always the sum of `remaining_points` across lots whose `expires_at` is strictly later than the current logical clock; it is recomputed after every grant, burn, and clawback. Because expiry is lazy, reading a member through `GET /loyalty-members/{id}` re-derives the balance against the current logical clock before responding, so lots that have expired since the last write are already excluded; this read-time derivation is a pure projection, not a mutation — it does not increment the member's `version` or refresh `updated_at`.

Accrual rounding is pinned per source and never deferred: each activity rounds its own points independently — fuel accrues half a point per dollar, while store sales, services, and parking each accrue one full point per dollar — and summing unrounded dollar amounts across sources and rounding once is expressly forbidden, because it produces different totals. The per-source formulas appear with their workflows in §3. An accrual that rounds to zero points writes no lot.

Redemption burns first-expiring-first-out: lots are consumed in order of `earned_at` ascending, ties broken by `created_at` ascending, expired lots skipped, decrementing `remaining_points` as value is applied. A redemption may never exceed the member's redeemable (non-expired) balance; a request that does is rejected with `ERR_NO_POINTS` (HTTP 422), and the balance is re-checked at the moment of finalization as well as at the moment of authorization or creation, because expiry may have drained it in between. An omitted `requested_redeem_points` defaults to zero everywhere it appears, and a request carrying `requested_redeem_points` greater than zero without a `loyalty_member_id` is malformed and rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Clawbacks run newest-first: a negative adjustment decrements `remaining_points` from lots ordered by `earned_at` descending, never driving any lot below zero, and the negative lot itself is recorded with `remaining_points` of zero. Manual adjustments created by a `GeneralManager` use the same machinery: a positive `points_delta` writes a normal lot, a negative `points_delta` claws back newest-first, and every adjustment carries a `reason`. The `points_delta` must be a non-zero integer and the `reason` a non-empty string, else `ERR_INVALID_REQUEST` (HTTP 400); the written lot is returned with status 201, and adjustments are permitted on members in any status.

### 2.10. Validation Pipeline and Nested Resource Retrieval

Requests are validated against a fixed pipeline, and the order is observable because earlier failures mask later ones. Authentication comes first: missing or unknown headers fail with `ERR_UNAUTHENTICATED`. Role authorization follows, failing with `ERR_FORBIDDEN`. Path-identifier existence comes next, validated left to right, each child required to belong to the site or parent scope named in the path, any miss failing with `ERR_NOT_FOUND` (HTTP 404) — with one exception: on `/loyalty-members/{id}` and its subcollection endpoints the path identifier is itself the scoping key, so a mismatched `LoyaltyMember` is refused `ERR_FORBIDDEN` before existence is evaluated. Entity-backed identity scoping, likewise `ERR_FORBIDDEN`, otherwise runs once the record it reads is loaded: a creation payload's `loyalty_member_id` is scoped before body foreign keys resolve, while ownership scoped on a field of an existing record (its fleet, member, technician, or cashier field) is checked after that record loads. Segregation-of-duties collisions fail with `ERR_SEGREGATION_OF_DUTIES` once the target shift is loaded, before its state checks. Foreign keys in the request body — fields such as `pump_id`, `shift_id`, `loyalty_member_id`, `fleet_account_id`, `contract_id`, `stock_item_id`, `bay_id`, `technician_id`, `vendor_id`, `network_program_id`, `register_id`, and `bulk_tank_id` — must then resolve, likewise failing with `ERR_NOT_FOUND`; they are checked for resolution only, and whether a resolved reference belongs to the same site as the path is not cross-checked except where an endpoint narrative says so (work-order scheduling and road dispatch reject another site's bay or technician as `ERR_NOT_FOUND`). State checks come after existence: the generic rule that the target entity must be in a state from which the requested transition exists fails with `ERR_INVALID_STATE` (HTTP 409), followed by the endpoint-specific state guards — pump availability, open shifts, register availability, fleet and contract activity, bay occupancy, member activity. Business rules evaluate last among the semantic checks, in the order safety (water bottoms), referential integrity of the commercial payload (pricing-mode shape, plate registration, contract fuel types), temporal windows (parking, price, bay schedule), capacity and stock constraints, and finally fiscal rules (points balances, contract discount shortfall, credit limits, drop and payout bounds, close-out conditions). Dead last in the pipeline, below every semantic rule, malformed request bodies, missing required fields, invalid enum values, and non-positive quantities are rejected with `ERR_INVALID_REQUEST` (HTTP 400) — so a syntactically bad payload aimed at an unauthorized or nonexistent target surfaces the earlier error, not the malformed-body error.

## 3. Business Logic & Workflows

### 3.1. Site Configuration, Fuel Price Posting and Pump Operations

Everything hangs off a `TravelCenterSite`. A `GeneralManager` creates one with a `name`, the lot's `parking_total_spaces`, the `parking_paid_capacity` — the maximum count of overlapping paid reservations with status `CONFIRMED` or `ACTIVE` allowed at any instant, which must not exceed `parking_total_spaces` (a larger figure is rejected with `ERR_INVALID_REQUEST`, HTTP 400) — plus the `shower_units_count` and `laundry_machines_count` that bound the service queues. A new site starts with `water_usage_gallons` at zero and all three retail price mirrors — `diesel_retail_cents_per_gallon`, `gas_regular_retail_cents_per_gallon`, and `def_retail_cents_per_gallon` — null until prices are posted. Every record scoped to the property — pumps, prices, parking spaces and reservations, queue tickets, scale tickets, stock items, vendors, purchase orders, bays, technicians, registers, shifts, and tanks — carries the owning site's identifier as `site_id`. Site listings support the standard `limit` and `offset` parameters, and a computed operations dashboard returns for managers and the fuel desk `pumps_total` and `pumps_in_use` (the site's pumps, and those in `IN_USE`), `parking_active_count` (reservations in `ACTIVE`), `shower_queue_depth` and `laundry_queue_depth` (tickets in `QUEUED` for the respective service type), and `low_stock_count` (stock items whose `is_low_stock` is true).

Retail pricing is maintained as a book of `FuelPrice` rows per site. A `FuelDeskLead` posts a new price by naming the `fuel_type` — one of `DIESEL`, `GAS_REGULAR`, `GAS_PREMIUM`, or `DEF` — the `retail_cents_per_gallon` in whole cents, and the window `effective_from` (inclusive) to `effective_to` (exclusive), with a null `effective_to` meaning open-ended. The create is guarded by the site's optimistic-concurrency rule from §2.6 via `expected_site_version`. Window shape is validated first: when `effective_to` is given it must lie strictly after `effective_from`, and `effective_from` must not be in the past. Overlap with existing `ACTIVE` prices of the same fuel resolves deterministically. When an existing price starts strictly earlier than the new one and its window actually reaches the new window — its `effective_to` is null or lies strictly after the new `effective_from` — it is truncated: its `effective_to` is rewritten to the new price's `effective_from` and it stays `ACTIVE`. An earlier price whose window already ended at or before the new `effective_from` is left untouched. When an existing price starts strictly later and the new window covers that start, the existing price transitions `ACTIVE → SUPERSEDED`. When the new `effective_from` exactly equals an existing `ACTIVE` same-fuel price's `effective_from`, the duplicate start is rejected outright with `ERR_OVERLAPPING_PRICE_WINDOW` (HTTP 422), as is any malformed window. A successful posting recomputes the site's retail mirrors — each mirror reflects the currently effective `ACTIVE` price for its fuel, or null when none is in force — and bumps the site's `version` by 1. Because window effectiveness is evaluated against the logical clock, a future-dated price simply becomes the selected quote as the clock advances into its window. The mirrors are re-derived lazily — on every site read, and across all sites whenever the logical clock is set — as a pure projection that never bumps the site's `version`; only a successful price posting does. Price listings accept `fuel_type` and `status` filters.

Pumps are created per site with a `pump_number` unique within the site (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400) and the list of `fuel_types` the pump serves, entering service in status `IDLE`. Authorizing a fuel sale reserves the pump, cascading it `IDLE → IN_USE`; dispensing completion or a void frees it back to `IDLE`. A `FuelDeskLead` may take an `IDLE` pump out of service — permitted only while no non-voided sale occupies it in `AUTHORIZED`, `FUELING`, or `PENDING_FINALIZE` — moving it `IDLE → OUT_OF_SERVICE`, and later return it `OUT_OF_SERVICE → IDLE`; any attempt from a posture where the transition does not exist is rejected with `ERR_INVALID_STATE`. Pump listings accept a `status` filter, and each pump exposes the fuel sales authorized on it.

### 3.2. Fuel Sales: Authorization, Dispensing, Finalization, Payment and Void

A fuel sale begins at authorization, created against a site by a `Cashier` or `FuelDeskLead` with `pump_id`, `shift_id`, `pricing_mode`, `fuel_type`, and `tender_type`, plus optional `loyalty_member_id`, `fleet_account_id`, `contract_id`, `requested_redeem_points`, and `max_gallons`. The attribution shift named by `shift_id` must be `OPEN`. The authorized gallon cap `max_gallons` carries three decimals and defaults to 200.000 when omitted; `requested_redeem_points` defaults to 0. The sale is born `AUTHORIZED` with `payment_status` `UNPAID`, and its pump cascades to `IN_USE`.

Authorization enforces its checks in a fixed order, and the order decides which error a multiply-broken request surfaces. State guards run first: the pump must be `IDLE` and must serve the requested `fuel_type`, else `ERR_PUMP_NOT_AVAILABLE` (HTTP 409); the attribution shift named by `shift_id` must then be `OPEN`, else `ERR_SHIFT_NOT_OPEN` (HTTP 409); for a contract sale the named fleet must then be `ACTIVE` (`ERR_FLEET_NOT_ACTIVE`, HTTP 409) and the contract must be `ACTIVE` with the current clock inside its window (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409); and when a member is attached and points are requested, the member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`, HTTP 409). Referential checks follow: the pricing-mode payload must be coherent — `CONTRACT` requires both `fleet_account_id` and `contract_id`, `RETAIL` forbids them, and the `FLEET_BILLING` tender is lawful only on a `CONTRACT` sale, violations being `ERR_INVALID_PRICING_MODE` (HTTP 422) — and a contract sale's requested `fuel_type` must appear in the contract's `applicable_fuel_types` (`ERR_CONTRACT_FUEL_TYPE`, HTTP 422). The fiscal guards evaluate last, after price existence: the member's redeemable balance must cover `requested_redeem_points` (`ERR_NO_POINTS`), then the contract-discount shortfall check, then the fleet credit ceiling — so a sale that fails both its points balance and the fleet's credit check reports the points failure.

The retail quote runs when `pricing_mode` is `RETAIL`. The server selects the site's `ACTIVE` price row for the requested `fuel_type` whose window contains the current clock — `effective_from` at or before now and `effective_to` either null or strictly after now; creation-time overlap rules guarantee at most one match, and none at all is `ERR_NO_ACTIVE_PRICE` (HTTP 422). That row's cents-per-gallon becomes the retail basis, pinned onto the sale as `retail_price_snapshot`. When a member is attached, the network allowance is the largest `discount_per_gallon` among the member's `ACTIVE` enrollments whose network program is also `ACTIVE` and whose network's `applicable_fuel_types` covers the requested fuel — pinned as `network_discount_snapshot`, or zero when nothing qualifies. The redemption count is the smaller of `requested_redeem_points` and the member's `stack_cap_points`, itself pinned as `stack_cap_snapshot`; each point is worth half a cent, so the points allowance is the redemption count multiplied by 0.5 cents, rounded half up to whole cents. The provisional unit price is the retail basis minus the network allowance converted to cents — that subtraction rounded half up to whole cents — then minus the points allowance, floored at zero, and is stored as `authorized_quote_cents_per_gallon`. Multiplying it by `max_gallons` yields `provisional_fuel_total_cents`, the provisional variant of the sale total. A retail sale pins `contract_rate_snapshot_cents` and `contract_discount_snapshot` to null; a contract sale pins `retail_price_snapshot` to null and `network_discount_snapshot` to zero; and `stack_cap_snapshot` is null whenever no member is attached.

The contract quote runs when `pricing_mode` is `CONTRACT`, priced off the site's diesel bulk tank rather than the pump sign. The rack basis is the diesel tank's `rack_price_cents_per_gallon_4dp`, a dollars-per-gallon figure at four-decimal precision. When the site has several `DIESEL` tanks, the quote draws from the earliest-created tank carrying a rack price — or, when none carries one, the earliest-created `DIESEL` tank — and when the site has no diesel rack price at all the authorization fails with `ERR_NO_ACTIVE_PRICE` (HTTP 422). The server adds a freight allowance of 0.1500 dollars per gallon and subtracts the tier margin baked into the contract's own `pricing_tier` — 0.02 dollars per gallon for `T1`, 0.05 for `T2`, and 0.09 for `T3` — rounding the result half up at four decimal places, then multiplying by one hundred and rounding half up to integer cents; that figure is pinned as `contract_rate_snapshot_cents`, and the contract's `discount_per_gallon_off` is pinned as `contract_discount_snapshot`. The contract discount may not exceed the tier margin already inside the rate; a contract whose `discount_per_gallon_off` exceeds its tier's margin is rejected at authorization with `ERR_CONTRACT_DISCOUNT_SHORTFALL` (HTTP 422). Otherwise the discounted rate is the contract rate minus the discount converted to cents, rounded half up. Points enter exactly as in the retail path, and the unit price floors at zero. Two variants of the contract rate exist by design: the authorization always prices the provisional tier recorded on the contract itself, while a fleet-level preview priced at the fleet's current `pricing_tier` can differ once the fleet's rolling volume has crossed a tier breakpoint but the contract still carries its original tier. Before the authorization completes, the fleet's projected balance — `current_balance_cents` plus the new `provisional_fuel_total_cents` — must stay within the fleet's `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

Starting fueling moves the sale `AUTHORIZED → FUELING`. Ending fueling requires the reported `dispensed_gallons` to be greater than zero and no more than the authorized `max_gallons` — a non-positive or over-cap reading is malformed and fails as `ERR_INVALID_REQUEST` — and moves the sale `FUELING → PENDING_FINALIZE`, recording the three-decimal `dispensed_gallons` and cascading the pump `IN_USE → IDLE`.

Finalization moves the sale `PENDING_FINALIZE → COMPLETED`. When the sale carries a member and points were requested, the member must still be `ACTIVE` and the redeemable balance is re-checked against `requested_redeem_points`, since lot expiry may have drained it since authorize — the failures are again `ERR_MEMBER_NOT_ACTIVE` and `ERR_NO_POINTS`. The final unit price is recomputed exclusively from the pinned snapshots — identical arithmetic, frozen inputs — so later price supersessions, network changes, or cap changes cannot move it; the result is stored as `final_unit_price_cents`. The fuel amount is that unit price multiplied by the actual `dispensed_gallons`, rounded half up to whole cents, recorded as `fuel_amount_cents`. Fuel tax is already inside the pump price, so `tax_cents` is always 0 and `total_cents` equals `fuel_amount_cents`; `finalized_at` is stamped from the logical clock. The provisional and final totals therefore differ exactly when dispensed volume differs from the authorized cap. Loyalty then settles both directions: the redemption count — the smaller of `requested_redeem_points` and the pinned `stack_cap_snapshot` — burns FEFO from the member's lots and is recorded as `points_redeemed` with its cent value in `points_discount_cents`, while earned points — the post-redemption `total_cents` divided by one hundred, multiplied by 0.5 points per dollar, rounded half up — are granted as a new lot expiring 360 days out, recorded as `points_earned`, and the member's `points_balance` is recomputed. A contract sale additionally cascades three hops: the contract's `volume_delivered_gallons` grows by `dispensed_gallons`, the fleet's `rolling_30d_gallons` is recomputed, and the fleet tier recompute may flip `pricing_tier` when a 5,000- or 20,000-gallon breakpoint is crossed.

Payment moves `payment_status` from `UNPAID` and requires the sale to be `COMPLETED` with `payment_status` still `UNPAID` — anything else is `ERR_INVALID_STATE` (HTTP 409). The pay payload's own `tender_type` governs: with tender `CASH` or `CARD` the sale becomes `PAID`; with `FLEET_BILLING` — lawful only on contract sales — it becomes `BILLED`. A cash payment requires the sale's attribution shift to still be `OPEN`. Cash moves the shift ledger: `expected_cash_cents` grows by `total_cents` and the register's posture is recomputed, potentially crossing the `NEEDS_DROP` trigger at five times the float. Fleet billing instead grows the fleet's `current_balance_cents` by `total_cents`; the credit ceiling is not re-checked at payment time, having been enforced at authorization.

A `ShiftManager` voids a sale, recording the supplied `reason` — optional, null when omitted — into `void_reason`. Voiding a live but unfinished sale — from `AUTHORIZED`, `FUELING`, or `PENDING_FINALIZE` — requires `payment_status` `UNPAID` and simply moves the sale to `VOIDED`, freeing the pump if it is still held; no money or points ever moved, so nothing reverses. Voiding a `COMPLETED` sale is a refund-void: when payment was `PAID` or `BILLED` it becomes `REFUNDED` (an `UNPAID` completed sale stays `UNPAID`); a cash-paid sale decrements the shift's `expected_cash_cents` by `total_cents` and recomputes posture; a billed sale decrements the fleet's `current_balance_cents` by `total_cents`; loyalty reverses with an `ADJUSTMENT` lot of the redeemed points returned, expiring 360 days out, and a negative lot of the earned points clawed back newest-first; and a contract sale unwinds its cascade — `volume_delivered_gallons` shrinks by `dispensed_gallons`, the fleet's rolling volume is recomputed, and the tier recompute is re-evaluated. Either void branch leaves the sale `VOIDED`. Site fuel-sale listings accept `status` and `pricing_mode` filters.

### 3.3. Fleet Accounts and Tiered Fuel Contracts

A `GeneralManager` opens a `FleetAccount` with a company `name`, a `credit_limit_cents` ceiling on the outstanding billed balance, and an initial `pricing_tier` of `T1`, `T2`, or `T3`. The account is born `ACTIVE` with `current_balance_cents` and `rolling_30d_gallons` both at zero. The outstanding balance is purely derived: it is the sum of `total_cents` across the fleet's fuel sales whose `payment_status` is `BILLED`, and nothing else moves it except fleet-billed collections and their reversals. The credit limit itself may be updated by amendment.

The rolling volume and tier are recomputed on demand through the fleet's tier-recompute action and as a cascade from every contract finalize or refund-void. `rolling_30d_gallons` is the sum of `dispensed_gallons` over the fleet's contract sales that are `COMPLETED` with `finalized_at` inside the trailing 30-day window, both endpoints inclusive — a sale finalized exactly 30 days ago counts, as does one finalized right now. The tier then snaps to `T3` when the rolling volume reaches at least 20,000 gallons, `T2` at least 5,000 gallons, and `T1` below that; the breakpoint comparisons are inclusive, so exactly 5,000 gallons is already `T2`.

Fleet credit posture is manager-controlled. Placing the account on credit hold moves it `ACTIVE → CREDIT_HOLD`, which blocks new contract fuel authorizations and blocks estimate approval on the fleet's work orders. Reinstatement moves it `CREDIT_HOLD → ACTIVE`. Closing the account — permitted from either `ACTIVE` or `CREDIT_HOLD`, and only while `current_balance_cents` is exactly zero, failing with `ERR_INVALID_STATE` (HTTP 409) otherwise — moves it to terminal `CLOSED` and cascades every non-terminal contract of the fleet, whether `PENDING`, `ACTIVE`, or `SUSPENDED`, into `TERMINATED`.

A `FleetContract` is created under a fleet with a `contract_code` unique within that fleet, its own `pricing_tier` (independent of the fleet's rolling tier), a `discount_per_gallon_off` in dollars (carried exactly as supplied and converted to cents, rounded half up, at the point of use) layered on top of the computed contract rate, a non-empty `applicable_fuel_types` subset of diesel, regular gas, premium gas, and DEF, and the commercial window `effective_from` to `effective_to` — both ends required, `effective_to` strictly after `effective_from`, and a `contract_code` duplicated within the fleet rejected, each violation failing as `ERR_INVALID_REQUEST` (HTTP 400). Creation does not inspect the fleet's status and does not apply the discount-versus-tier-margin check, which fires only at authorization and at amendment. The contract is not usable before `effective_from` nor at or after `effective_to`. It is born `PENDING` with `volume_delivered_gallons` at zero — that counter accumulates the dispensed gallons of every completed sale quoting the contract.

Activation moves the contract `PENDING → ACTIVE` only when the current clock sits inside the window and the owning fleet is `ACTIVE`. Suspension moves it `ACTIVE → SUSPENDED`, blocking new authorizations that quote it; resumption returns `SUSPENDED → ACTIVE` under the same window-and-fleet conditions as activation. Expiry moves `ACTIVE` or `SUSPENDED` to terminal `EXPIRED`; termination moves `PENDING`, `ACTIVE`, or `SUSPENDED` to terminal `TERMINATED`, either by explicit manager action or by the fleet-close cascade. Amending a contract's `discount_per_gallon_off` or `effective_to` is the second optimistic-concurrency guard from §2.6: the request must carry `expected_contract_version` matching the contract's current `version`, a stale value is refused with `ERR_STALE_VERSION`, and the amended discount is re-checked against the tier margin — an amendment whose discount exceeds the margin for the contract's tier fails with `ERR_CONTRACT_DISCOUNT_SHORTFALL`. The amended `effective_to` is validated only as a well-formed instant; no window-shape check against `effective_from` is applied at amendment time. A fleet's contracts may be listed with a `status` filter, and each contract exposes the fuel sales that quoted it.

### 3.4. Loyalty Membership, Vehicles and Discount Networks

Drivers register as loyalty members with a `full_name` and `email`; a member may optionally be linked to a fleet via `fleet_account_id`, or remain an independent driver with it null. Each member carries a `stack_cap_points` ceiling on the points redeemable in a single transaction, defaulting to 500 when not supplied. Members are born `ACTIVE` with `points_balance` zero. A `GeneralManager` may suspend a member — `ACTIVE → SUSPENDED` — after which the member can neither redeem nor earn points, while its discount enrollments keep their own statuses; reactivation returns `SUSPENDED → ACTIVE`. Closing a member from either state moves it to terminal `CLOSED`, cancels every enrollment still in `PENDING`, `ACTIVE`, or `SUSPENDED`, and forfeits all remaining points, recomputing `points_balance` to zero. Points adjustments and the member's lot ledger follow §2.9. Any operation that redeems points, accrues points, activates an enrollment, or creates a reservation or service ticket for a member requires that member to be `ACTIVE`; against a suspended or closed member the rejection is `ERR_MEMBER_NOT_ACTIVE`. Fuel authorization and finalization apply this guard only when points are requested, and the accruals that ride along with check-in or service completion are not guarded at all: a member no longer `ACTIVE` at that moment simply earns nothing.

Each member registers vehicles by `plate` and `vehicle_type` — one of `TRACTOR`, `BOX_TRUCK`, `RV`, or `AUTO`. Plates are unique across all members, so a plate already registered to anyone is rejected with `ERR_INVALID_REQUEST` (HTTP 400); parking reservations lean on this registry to prove the driver owns the rig they are booking.

Discount networks are third-party programs created in `DRAFT` with a `name`, a fixed `discount_per_gallon` in dollars (carried exactly as supplied and converted to cents, rounded half up, at the point of use) applied at every site, a non-empty `applicable_fuel_types` subset, and a `program_cap` of at least one bounding the count of simultaneously `ACTIVE` enrollments. Activation moves the network `DRAFT → ACTIVE`, after which enrollments may activate against it. Retirement moves it `ACTIVE → RETIRED` and cascades every enrollment of the network in `PENDING`, `ACTIVE`, or `SUSPENDED` to `RETIRED`; a retired network no longer contributes discounts to any retail quote.

Enrollment begins when a member (or a cashier or manager on the member's behalf) joins a network by `network_program_id`, producing a `PENDING` enrollment. Activation — by a cashier or manager — enforces four gates: the network must be `ACTIVE` (`ERR_NETWORK_NOT_ACTIVE`, HTTP 422), the member must be `ACTIVE`, the member must not already hold an enrollment in the same network in `PENDING`, `ACTIVE`, or `SUSPENDED` (`ERR_DUPLICATE_NETWORK_ENROLLMENT`, HTTP 422 — also enforced at enrollment creation), and the network's count of `ACTIVE` enrollments must be below `program_cap` (`ERR_NETWORK_CAP_REACHED`, HTTP 422). A manager may suspend an `ACTIVE` enrollment — `ACTIVE → SUSPENDED` — after which it contributes no discount and does not count toward the cap; resumption re-checks the network's activity and the cap room before returning `SUSPENDED → ACTIVE`. The member or a manager may cancel from any of `PENDING`, `ACTIVE`, or `SUSPENDED` into terminal `CANCELLED`, and the network-retire cascade carries the same three states into terminal `RETIRED`. A member's enrollments, and a network's roster with its `status` filter, are listable; member fuel sales, parking reservations, service tickets, and store sales are likewise exposed as member-scoped listings.

### 3.5. Driver Services: Paid Parking, Shower and Laundry Queues, and the Weigh Scale

Paid parking starts with the space inventory. A `GeneralManager` creates `ParkingSpace` records per site, each with a free-form string `space_number` unique within the site (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `space_type` of `STANDARD` or `OVERSIZED`, and a required boolean `is_reservable` flag; spaces are born `ACTIVE` and may be `OUT_OF_SERVICE`. Space listings accept `space_type` and `status` filters, and each space exposes the reservations assigned to it.

A reservation is created for a member — by a cashier or the member — naming `loyalty_member_id`, the `vehicle_plate`, the `space_type`, the half-open window `reserved_from` to `reserved_to`, and optionally `requested_redeem_points`. The plate must belong to a `RegisteredVehicle` owned by that same member, else `ERR_PLATE_NOT_REGISTERED` (HTTP 422). The window must be well-formed: `reserved_from` at or after the current clock, `reserved_to` strictly after `reserved_from`, and the whole window no longer than 336 hours — two weeks — else `ERR_INVALID_WINDOW` (HTTP 422). Aggregate capacity is then enforced at every instant of the requested window: the count of overlapping reservations in `CONFIRMED` or `ACTIVE`, windows compared half-open, must stay strictly below the site's `parking_paid_capacity`, else `ERR_PARKING_CAPACITY_FULL` (HTTP 422).

The charge is computed at creation. Total minutes are the window length in whole minutes; the first 15 minutes are a grace allowance, so `paid_minutes` is the total minus 15, floored at zero. `billed_hours` is the paid minutes divided by 60 rounded up to the next whole hour, and the base charge is those hours at 300 cents each. An `OVERSIZED` reservation adds a flat 800-cent `oversize_fee_cents`; a `STANDARD` one adds zero. Points may be burned against the fee at creation: the redemption count is the smaller of `requested_redeem_points` and the member's `stack_cap_points`, worth half a cent each rounded half up, recorded as `points_discount_cents`, and the final `amount_cents` is base plus oversize minus the points value, floored at zero. Requested points are burned FEFO at creation, subject to the balance check of §2.9. The reservation is born `CONFIRMED` with `payment_status` `UNPAID`, its `assigned_space_id`, `shift_id`, `checked_in_at`, and `checked_out_at` all null. Reservation listings accept `status` and `loyalty_member_id` filters.

Check-in is a cashier action requiring the current clock to sit between `reserved_from` inclusive and two hours after it, inclusive, with payment still `UNPAID`; outside that window the check-in is rejected with `ERR_INVALID_STATE` (HTTP 409). The space selector draws from the pool of spaces at the site whose `space_type` matches the reservation, whose status is `ACTIVE`, whose `is_reservable` is true, and to which no other `ACTIVE` reservation is currently assigned, ranked by `space_number` ascending in string order; an empty pool fails with `ERR_PARKING_CAPACITY_FULL`. The chosen space is stamped into `assigned_space_id`, `checked_in_at` is stamped, and the reservation moves `CONFIRMED → ACTIVE`. Payment is taken at the same moment with the payload's `tender_type` and `shift_id`: a `CASH` tender attributes `amount_cents` to the named shift — which must be `OPEN` — growing its expected cash and recomputing register posture, while `CARD` has no cash effect; either way `payment_status` becomes `PAID` and the cash-attribution `shift_id` is recorded. With a member present, parking accrues one point per dollar: `amount_cents` divided by one hundred, multiplied by 1.0, rounded half up, granted as a `PARKING` lot expiring 360 days out.

Check-out moves `ACTIVE → COMPLETED`, stamps `checked_out_at`, and frees the assigned space. Cancellation has two symmetric branches. From `CONFIRMED` — by a cashier or the member themselves, while still `UNPAID` — the reservation moves to `CANCELLED`, its capacity is released, and any points burned at creation are re-credited as an `ADJUSTMENT` lot of the redeemed amount, expiring 360 days out. From `ACTIVE` — an early departure taken by a cashier while `PAID` — the reservation also moves to `CANCELLED`, but the full amount is refunded: `payment_status` becomes `REFUNDED`, a cash payment decrements the shift's expected cash by `amount_cents` with posture recomputed, the earned points are clawed back as a negative lot applied newest-first, and the assigned space is freed. Only a cashier may take this early-departure branch; a member attempting it is refused with `ERR_FORBIDDEN` (HTTP 403). When a driver simply never arrives, a cashier or shift manager marks the reservation `CONFIRMED → NO_SHOW` once the current clock has passed two hours after `reserved_from` — before then the mark is rejected with `ERR_INVALID_STATE` (HTTP 409); capacity is released and nothing else moves.

Shower and laundry queueing runs on `ServiceQueueTicket` records. A cashier or the member creates one for a site with a `service_type` of `SHOWER` or `LAUNDRY`, optionally a `shift_id` naming the attribution shift (which must be `OPEN` when supplied), optionally a `loyalty_member_id` for walk-in versus member service, and optionally `requested_redeem_points`. The ticket joins the back of its lane: `queue_position` is one plus the current maximum `queue_position` among all tickets ever created at this site for this service type. Pricing happens at creation: the `base_price_cents` is 1500 for a shower and 400 for laundry; a ticket created on a Saturday or Sunday (UTC) adds a 300-cent `weekend_surcharge_cents`; one created with its time of day inside the 17:00–22:00 UTC window adds a 150-cent `peak_surcharge_cents`. Points burn as usual — the smaller of requested points and the stack cap at half a cent each, rounded half up — and `total_price_cents` is base plus weekend plus peak minus the points value, floored at zero. The ticket is born `QUEUED` and `UNPAID`. Ticket listings accept `service_type` and `status` filters.

Calling the next customer is a site-level cashier action naming a `service_type`: among `QUEUED` tickets of that type at that site, the lowest `queue_position` is selected and moves `QUEUED → CALLED`, stamping `called_at`; an empty pool is `ERR_QUEUE_EMPTY` (HTTP 422). Starting service moves a `CALLED` ticket to `ACTIVE` and stamps `started_at`, subject to the active-capacity check: the count of `ACTIVE` tickets of the same service type at the site must be below the site capacity — `shower_units_count` for showers, `laundry_machines_count` for laundry. When the lane is full, preemption is attempted: the candidate is the `ACTIVE` ticket of the same type with the longest elapsed time since its `started_at`, ties broken by earliest `created_at`, and it is preemptable only once it has run for at least 15 minutes; a preempted ticket cascades `ACTIVE → NO_SHOW`, forfeiting its place. When no ticket is preemptable, the start fails with `ERR_QUEUE_CAPACITY` (HTTP 422). A called customer who never shows is marked `CALLED → NO_SHOW` by a cashier, and a `NO_SHOW` ticket may be requeued — `NO_SHOW → QUEUED` — which sends it to the back with a fresh `queue_position` of one plus the lane's current maximum.

Completion moves `ACTIVE → COMPLETED` and stamps `completed_at`. A shower completion requires `shower_minutes` greater than zero; a laundry completion requires `laundry_lbs` greater than zero. Water usage is computed at completion, recorded on the ticket as `water_gallons`, and folded into the site's running `water_usage_gallons` at two-decimal precision: a shower meters 2.5 gallons per minute under water, with any time beyond the 45-minute cap counted only up to the cap; laundry meters 2.0 gallons per pound washed. With a member attached, service accrues one point per dollar of `total_price_cents`, rounded half up, granted as a `SERVICE` lot. Payment — while the ticket is `CALLED`, `ACTIVE`, or `COMPLETED` — moves `payment_status` `UNPAID → PAID`; a `CASH` tender is attributed to the effective shift — the payload's `shift_id` when supplied, otherwise the ticket's attribution shift — which must be `OPEN`, growing its expected cash by `total_price_cents` and recomputing posture; a cash payment with neither a payload nor an attribution shift is malformed (`ERR_INVALID_REQUEST`, HTTP 400), and a supplied payload `shift_id` is recorded onto the ticket as its attribution shift. Cancellation by a cashier or the member from `QUEUED` or `CALLED` re-credits any burned points as an `ADJUSTMENT` lot and, when already `PAID`, refunds: `payment_status` cascades to `REFUNDED` and a cash payment decrements the shift's expected cash.

The certified scale runs on `ScaleTicket` records, open to members and non-members alike. A cashier opens one against an `OPEN` shift with a free-text `vehicle_plate`, a `carrier_name`, and a `certified` flag indicating whether a certified weight ticket is requested; the ticket is born `OPEN` with `reweigh_count` and `total_paid_cents` at zero. Each weighing appends a `ScaleWeighEvent` with a `weigh_kind` of `GROSS`, `TARE`, or `REWEIGH` and the scale reading `weight_lbs` — weigh events are accepted while the ticket is `OPEN` or `PAID`, any other state failing with `ERR_INVALID_STATE` (HTTP 409); each event carries its parent ticket's identifier as `scale_ticket_id` and a 1-based append `sequence` within that ticket. A `GROSS` or `REWEIGH` event refreshes the ticket's `gross_lbs`, a `TARE` refreshes `tare_lbs`, `net_lbs` is `gross_lbs` minus `tare_lbs` once both are present, and every `REWEIGH` increments `reweigh_count`. Settlement moves `OPEN → PAID` and requires at least one `GROSS` and at least one `TARE` event on the ticket, else `ERR_SCALE_NOT_CERTIFIABLE` (HTTP 422). The toll is a 1250-cent first-weigh fee plus a 400-cent certified fee when `certified` is true; reweighs are always free. `total_paid_cents` records the toll, and a cash settlement attributes it to the ticket's `OPEN` shift, growing expected cash and recomputing posture. Departure closes the ticket `PAID → CLOSED`. Cancellation splits on payment: an `OPEN` ticket with `total_paid_cents` still zero may be cancelled to `CANCELLED` by a cashier or shift manager, while cancelling a `PAID` ticket — a shift-manager action, refused to a cashier with `ERR_FORBIDDEN` (HTTP 403) — moves it to terminal `REFUNDED`, adds the full `total_paid_cents` into `refund_total_cents`, and reverses the cash out of the shift with posture recomputed; across the ticket's life, the sum of tolls minus refunds is its net revenue.

### 3.6. Store Sales, Inventory and Vendor Purchasing

The restaurant and retail store run on `StockItem` records, created per site with a `sku` unique within the site (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `name`, a `category` of `RESTAURANT`, `RETAIL`, `SHOP_PART`, or `PACKAGED_OIL`, a `unit` of measure label, a `unit_price_cents` sale price (which doubles as the shop's part billing price), and a `reorder_point`. An optional `initial_on_hand_quantity` seeds the shelf — zero when omitted — an optional `vendor_id` names the preferred supplier, and for `PACKAGED_OIL` items an optional `case_pack_gallons` records the gallons per case pack used by reorder rounding (the field is stored only on `PACKAGED_OIL` items and held null on any other category). The on-hand figure `on_hand_quantity` is mutated by receipts, store sales, and shop issues and returns, and may never go negative; `is_low_stock` is true exactly when `on_hand_quantity` is at or below `reorder_point`, recomputed on every mutation. Stock listings accept `category` and `low_stock` filters — the latter taking the strings `true` or `false` (case-insensitive), anything else rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and each item exposes the shop part issues referencing it.

Vendors are registered per site with a `name` and a `category` of `FUEL`, `DEF_OIL`, `FOOD`, or `GENERAL`. Each vendor carries a price list of `VendorPrice` entries — `item_sku` matched to a stock item's `sku` at receiving time, a `unit` label, the vendor's `unit_price_cents` cost, and a `pack_size` defaulting to 1 — plus listings of the stock items preferring the vendor, the purchase orders placed with it, and any bulk deliveries attributed to it.

Purchasing runs on `PurchaseOrder` records created in `DRAFT` with a `vendor_id` and an array of `lines`, each naming a `sku`, a `quantity`, and optionally a `unit_price_cents` that defaults, when omitted, to the vendor's price-list entry for that SKU — the earliest-created matching entry when several exist — and a line with neither a supplied price nor a vendor entry is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the order's `total_cents` is the sum over lines of quantity times unit price. Approval moves the order `DRAFT → APPROVED`. Receiving is permitted only from `APPROVED` or `PARTIALLY_RECEIVED` — anything else fails with `ERR_INVALID_STATE` (HTTP 409) — and may be partial or complete: each receipt names `received_lines` of SKUs and quantities, the quantity carried as `received_quantity` (or `quantity`), and each line's SKU must appear on the order; per SKU the received quantity must not exceed the ordered quantity less what has already been received; an unknown SKU, a non-positive quantity, or an over-receipt is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A received SKU matching no stock item at the site still accumulates on the order but moves no stock. Each receipt grows the matched stock item's `on_hand_quantity` by the received quantity with `is_low_stock` recomputed and accumulates the order's `received_lines`; while any line remains open the order sits in `PARTIALLY_RECEIVED` — repeat partial receipts keep it there — and the receipt that completes every line moves it to terminal `RECEIVED`. A manager may cancel an order from `DRAFT` or `APPROVED` into terminal `CANCELLED`. Order listings accept `status` and `vendor_id` filters.

A store sale is rung up by a cashier against an `OPEN` shift with a `tender_type` of `CASH` or `CARD`, an array of `lines` naming `stock_item_id` and `quantity`, and optionally a `loyalty_member_id`. Each line prices at the item's current `unit_price_cents`; `subtotal_cents` sums quantity times price across lines and `total_cents` equals the subtotal, there being no store tax in this version. Stock sufficiency is enforced per item, aggregating duplicate lines that name the same `stock_item_id` — the aggregated quantity may not exceed what is on hand, and no sale may drive `on_hand_quantity` negative, else `ERR_INSUFFICIENT_STOCK` (HTTP 422) — then stock is decremented and `is_low_stock` recomputed. The sale is born `COMPLETED` with `payment_status` `PAID`; with a member attached, the sale accrues one point per dollar of `total_cents`, rounded half up, granted as a `STORE_SALE` lot and recorded as `points_earned`. A cash sale grows the shift's expected cash by `total_cents` and recomputes posture. A `ShiftManager` may refund a completed sale — `COMPLETED → REFUNDED`, optionally carrying a `reason` (accepted as a string but not persisted on the sale) — which sets `payment_status` to `REFUNDED`, restores each line's quantity to stock with `is_low_stock` recomputed, claws back the earned points as a negative lot applied newest-first, and, for a cash sale, decrements the shift's expected cash by `total_cents` with posture recomputed. Store-sale listings accept a `status` filter.

### 3.7. Maintenance Shop, Road Service and Work Orders

Shop capacity is physical. `ShopBay` records are created per site with a `bay_number` unique within the site, born `IDLE`. A bay under repair is taken `IDLE → MAINTENANCE` by appending a block of `blocked_from`, `blocked_to`, and `reason` to its `maintenance_blocks` — a closed interval, with only a `blocked_to` earlier than `blocked_from` malformed (`ERR_INVALID_REQUEST`, HTTP 400); equal ends are accepted — and is later cleared `MAINTENANCE → IDLE`. `Technician` records carry a `name`, an `hourly_rate_cents` labor billing rate, and free-form `certifications` (an array of strings, empty when omitted), and are born `AVAILABLE` (a technician may otherwise be `OFF_DUTY`). Bay listings accept a `status` filter; bays and technicians each expose the work orders attached to them.

A work order is opened by a cashier, technician, or manager with the customer's free-text `vehicle_plate`, a `complaint`, and an optional `fleet_account_id` when the work will be billed to a fleet; it is born `CREATED` with `payment_status` `UNPAID`. Any `MaintenanceTech` records the labor estimate — no technician is assigned yet at `CREATED`, so the estimate is not identity-scoped — moving `CREATED → ESTIMATED` and stamping `labor_hours_est`, which must be a positive number. Estimate approval moves `ESTIMATED → APPROVED`: a `GeneralManager` may approve any order, retail or fleet-billed, while a `FleetManager` may approve only its own fleet's orders; on fleet-billed work the fleet must be `ACTIVE` — a fleet on hold or closed fails with `ERR_FLEET_NOT_ACTIVE`.

Scheduling moves `APPROVED → SCHEDULED`, binding `bay_id`, `technician_id`, and the half-open window `scheduled_from` to `scheduled_to` — with `scheduled_to` required to lie strictly after `scheduled_from`, else `ERR_INVALID_REQUEST` (HTTP 400). The named bay and technician must both exist and belong to the order's site — a reference to another site's record fails with `ERR_NOT_FOUND` (HTTP 404) — and the technician must be `AVAILABLE`, else `ERR_INVALID_STATE` (HTTP 409). The window must not overlap — half-open on both sides — any non-terminal scheduled window on the same bay, meaning work orders in `SCHEDULED`, `IN_SHOP`, or `IN_PROGRESS`; overlap fails with `ERR_BAY_DOUBLE_BOOKED` (HTTP 422). The window must also not even touch a closed maintenance block on the bay: a conflict exists exactly when `scheduled_from` is at or before the block's `blocked_to` and the block's `blocked_from` is at or before `scheduled_to`, failing with `ERR_BAY_MAINTENANCE_CONFLICT` (HTTP 422).

Arrival moves `SCHEDULED → IN_SHOP` only while the bay is `IDLE`, else `ERR_BAY_OCCUPIED` (HTTP 409); check-in cascades the bay `IDLE → OCCUPIED`. Starting work moves `IN_SHOP → IN_PROGRESS` and is restricted to the assigned technician — the acting `MaintenanceTech` identity must equal the order's `technician_id`. Work in progress may be sent out to an outside vendor — `IN_PROGRESS → WAITING_VENDOR`, bay work only, never a road-service call — recording the payload's `reason` into `vendor_out_reason` (the payload must also carry a `vendor_name`, which is not exposed on the public record), and received back `WAITING_VENDOR → IN_PROGRESS`.

Road service bypasses the bay entirely: dispatching moves an `APPROVED` order straight to `IN_PROGRESS`, assigning the payload's `technician_id` — which must exist at the site and be `AVAILABLE` — setting `is_road_service` true and recording the free-text `location_text` into `road_location_text`; no bay is consumed.

Parts flow from stock. Issuing a part names `stock_item_id` and `quantity`, is permitted only while the order is `IN_PROGRESS` (else `ERR_INVALID_STATE`, HTTP 409), and is restricted to the assigned technician; it is blocked outright while the item's `is_low_stock` is true — replenish first, the rejection being `ERR_LOW_STOCK_APPROVAL_REQUIRED` (HTTP 422) — and the quantity may not exceed what is on hand, else `ERR_INSUFFICIENT_STOCK`. An issue decrements `on_hand_quantity`, recomputes `is_low_stock`, and writes a `WorkOrderPart` bound to its order by `work_order_id`, in status `ISSUED`, with the item's `unit_price_cents` snapshotted and `returned_quantity` starting at zero. Returning is accepted while the order is `IN_PROGRESS` or `WAITING_VENDOR` (else `ERR_INVALID_STATE`, HTTP 409); it names a `quantity` — a positive integer no greater than the issued-but-not-yet-returned remainder, else `ERR_INVALID_REQUEST` (HTTP 400) — grows `returned_quantity`, restores that quantity to stock with `is_low_stock` recomputed, and flips the part line to `RETURNED` once the returned count equals the issued `quantity`.

Completion — `IN_PROGRESS → READY_FOR_PICKUP` — takes two symmetric forms. Bay work completes with a `labor_hours_actual` greater than zero, computes the invoice, and cascades the bay `OCCUPIED → IDLE`; a road-service call completes the same way with its own `labor_hours_actual` greater than zero, computes the same invoice, and frees no bay because none was held. The invoice is computed in a pinned order: `parts_total_cents` first, the exact sum over part lines of issued-minus-returned quantity times the snapshotted `unit_price_cents`; then `labor_total_cents`, the actual hours multiplied by the technician's `hourly_rate_cents`, rounded half up; then `environmental_fee_cents`, 150 cents per net tire — the sum of issued-minus-returned quantities over parts whose stock item's `sku` contains "TIRE", zero otherwise; then `shop_supplies_cents`, three percent of the parts total rounded half up; and finally `invoice_total_cents` as the sum of the four.

Closing collects payment and moves `READY_FOR_PICKUP → CLOSED` while the order is still `UNPAID`. A `CASH` tender requires the payload to name a `shift_id` — omitting it is `ERR_INVALID_REQUEST` (HTTP 400) — and that shift to be `OPEN`; it grows the shift's expected cash by `invoice_total_cents`, recomputes posture, and marks payment `PAID`; a `CARD` simply marks `PAID`. A `FLEET_BILLING` tender requires the order to be fleet-billed — a retail order is refused with `ERR_INVALID_PRICING_MODE` (HTTP 422) — the fleet to be `ACTIVE`, and the projected balance — the fleet's `current_balance_cents` plus this invoice — to stay within `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`; it marks payment `BILLED` and grows the fleet's balance by the invoice. Cancellation from any non-terminal state — `CREATED`, `ESTIMATED`, `APPROVED`, `SCHEDULED`, `IN_SHOP`, `IN_PROGRESS`, `WAITING_VENDOR`, or `READY_FOR_PICKUP` — requires payment still `UNPAID`, returns every issued part line's outstanding quantity to stock with `is_low_stock` recomputed, and frees the bay when the order is cancelled from `IN_SHOP` or `IN_PROGRESS` (a bay held by an order cancelled from `WAITING_VENDOR` is left occupied). Work-order listings accept `status` and `fleet_account_id` filters.

### 3.8. Registers, Shifts and Cash Control

Registers are created per site with a `register_code` unique within the site (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400) and a standard drawer `float_cents`, born with posture `OK`; the derivation of `posture` from the open shift's expected cash is defined in §2.8. A register exposes its shifts, its cash drops, and its safe deposits as listings.

A `ShiftManager` opens a shift on a register by naming `register_id`, the `cashier_user_id` of the cashier who will own the drawer, and a `shift_label` of `DAY`, `NIGHT`, or `GRAVEYARD`. The register must have no other `OPEN` shift, else `ERR_REGISTER_NOT_AVAILABLE` (HTTP 409). The shift is born `OPEN`: `opened_at` is stamped from the logical clock, `opened_by_manager_id` records the opener's `X-User-ID`, `opening_float_cents` snapshots the register's `float_cents`, and `expected_cash_cents` starts exactly at that float. Shift listings accept `status` and `register_id` filters, and each shift exposes its fuel sales, parking reservations, service tickets, scale tickets, and store sales as listings.

During the shift, two controlled outflows move cash off the drawer. The owning cashier records a cash drop to the safe with an `amount_cents` and a `denominations` map from denomination cents to bill count; the map must sum exactly to the declared amount, else `ERR_DROP_MISMATCH` (HTTP 422), and the amount may not exceed the shift's expected cash above its opening float — the drawer always keeps at least the float — else `ERR_DROP_EXCEEDS_EXPECTED` (HTTP 422). The canonical denominations in cents are 10000, 5000, 2000, 1000, 500, 100, 25, 10, 5, and 1, and the canonical greedy form takes as many of each descending denomination as fit; any map summing correctly is accepted regardless of form. A posted drop is a `POSTED` `CashDrop` that decrements the shift's expected cash and recomputes posture. A payout is the manager-approved counterpart: a `ShiftManager` who is not the shift's cashier approves an `amount_cents` with a `reason`, the amount may not exceed the shift's full `expected_cash_cents` else `ERR_PAYOUT_EXCEEDS_EXPECTED` (HTTP 422), and approval decrements expected cash and recomputes posture — a payout may flip the register to `LOW_FLOAT`. The payout response carries its `payout_id`, the `amount_cents`, and the shift's resulting `expected_cash_cents`.

Closing the shift is a different `ShiftManager` than the one who opened it — the segregation rule of §2.1 — and requires the drawer to still hold at least the float: expected cash below `opening_float_cents` is rejected with `ERR_REMAINING_BELOW_FLOAT` (HTTP 422). The closer supplies the physical `counted_cash_cents`; when the absolute difference between counted and expected exceeds 500 cents, the close must explicitly carry `approve_variance` set true, else `ERR_COUNT_SHORTAGE_UNAPPROVED` (HTTP 422). A successful close stamps `closed_at` and `closed_by_manager_id`, moves the shift `OPEN → CLOSED`, and writes the audit trail: a `ShiftReconciliation` capturing the expected figure at close, the counted figure, their signed `variance_cents` (positive meaning overage), a `resolution` of `BALANCED` when the variance is zero, `OVERAGE` when positive, or `SHORTAGE` when negative, and a `deposit_total_cents` of the expected cash above the opening float, floored at zero; and, whenever that deposit total is greater than zero, a `SafeDeposit` in status `RECORDED` for the same amount, attributed to the shift and its register. With no shift left open, the register's posture recomputes to `OK`.

Review then proceeds in two more segregated steps: reconciliation moves `CLOSED → RECONCILED` under a manager different from the closer, and a `GeneralManager` locks a reconciled shift — `RECONCILED → LOCKED` — as the audit-final state. The shift's reconciliations, cash drops, and safe deposits remain listable for audit.

### 3.9. Bulk Fuel, DEF and Oil Supply

Underground and tote inventory is tracked on `BulkTank` records, created per site with a `product_type` of `DIESEL`, `DEF`, or `OIL`, a `capacity_gallons`, a `reorder_threshold_gallons`, a `safety_stock_gallons` buffer, an average `daily_usage_gallons` draw used in projections, and a vendor `lead_time_days`. An optional `initial_gallons` seeds the book inventory — zero when omitted — and for `DIESEL` tanks an optional `rack_price_cents_per_gallon_4dp` records the replacement rack cost at four-decimal precision, the input that feeds contract quoting; it is null for other products. `current_gallons` is the book inventory, and `is_low_stock` is true exactly when `current_gallons` is at or below `reorder_threshold_gallons`. Tank listings accept a `product_type` filter.

Physical reality enters two ways. A stick reading by the fuel desk or a manager carries `reading_gallons` and replaces the book figure outright — `current_gallons` becomes the reading — with `is_low_stock` recomputed; it may also report a `water_bottom_inches`. A delivery records `gallons_delivered`, an optional `vendor_id`, an optional `water_bottom_inches` defaulting to zero, and an optional invoice `rack_price_cents_per_gallon_4dp`; the delivery is written as a `DELIVERED` `BulkDelivery`, the tank's `current_gallons` grows by the delivered quantity, `is_low_stock` recomputes, and — for `DIESEL` tanks only, when the payload carries a rack price — the tank's `rack_price_cents_per_gallon_4dp` is updated, which immediately feeds the next contract quote. Fuel quality gates both paths: a reported water bottom above 1.0 inches is rejected with `ERR_WATER_BOTTOM_EXCEEDED` (HTTP 422). Reorder suggestions are recomputed on every read of the site's suggestion view and conceptually after every delivery or stick reading: for each tank, the projected level is `current_gallons` minus `daily_usage_gallons` multiplied by `lead_time_days`; the target fill is ninety percent of `capacity_gallons`; and the suggestion is the target minus the projection plus the safety stock, floored at zero, emitted only for tanks whose current level is at or below the reorder threshold. For `OIL` product, when the site has a `PACKAGED_OIL` stock item carrying `case_pack_gallons` — the earliest-created such item supplies the pack size — the suggestion is rounded up to whole case packs: the two-decimal-rounded gallon suggestion divided by the pack size and rounded up to the next whole case, then multiplied back by the pack size, so the packaged suggestion is never below the rounded gallon figure. Diesel and DEF tanks receive raw gallon suggestions with no pack rounding. The view responds with an object shaped `{"suggestions": [...]}` — one entry per qualifying tank in tank creation order, each entry carrying `bulk_tank_id`, `product_type`, `current_gallons`, `reorder_threshold_gallons`, `projected_gallons`, `target_gallons`, and `suggested_gallons`, and an oil entry built with pack rounding additionally carrying `case_pack_gallons` and `suggested_cases`.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Operations that create a new resource respond 201 and return the created resource; reads and all modifications — including state-transition actions — respond 200 and return the updated resource. Request and response payloads for every endpoint are reconstructed from the narratives of §2 and §3; the table below is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sites | Create a travel center site | GeneralManager |
| GET | /sites/{id} | Get site detail | GeneralManager, ShiftManager, FuelDeskLead, Cashier, MaintenanceTech, FleetManager, LoyaltyMember |
| GET | /sites | List sites | GeneralManager, ShiftManager, FuelDeskLead, Cashier, MaintenanceTech, FleetManager, LoyaltyMember |
| GET | /sites/{id}/dashboard | Computed operations snapshot | GeneralManager, ShiftManager, FuelDeskLead |
| POST | /sites/{id}/fuel-prices | Post a new retail fuel price; supersedes or truncates overlapping active same-fuel prices; OCC on site version | FuelDeskLead |
| GET | /sites/{id}/fuel-prices | List fuel prices of a site | GeneralManager, FuelDeskLead, ShiftManager |
| GET | /fuel-prices/{id} | Get a fuel price | GeneralManager, FuelDeskLead |
| POST | /sites/{id}/pumps | Create a pump | GeneralManager, FuelDeskLead |
| GET | /sites/{id}/pumps | List pumps | GeneralManager, FuelDeskLead, Cashier, ShiftManager |
| GET | /pumps/{id} | Get pump | GeneralManager, FuelDeskLead, Cashier, ShiftManager |
| POST | /pumps/{id}/out-of-service | Take pump out of service (idle only) | FuelDeskLead |
| POST | /pumps/{id}/return-to-service | Return pump to service | FuelDeskLead |
| GET | /pumps/{id}/fuel-sales | Fuel sales authorized on this pump | GeneralManager, FuelDeskLead, ShiftManager |
| POST | /sites/{id}/fuel-sales | Authorize a fuel sale (retail or contract); pins price snapshots; pump goes in use | Cashier, FuelDeskLead |
| GET | /sites/{id}/fuel-sales | List fuel sales of a site | GeneralManager, FuelDeskLead, ShiftManager, Cashier |
| GET | /fuel-sales/{id} | Get fuel sale | GeneralManager, FuelDeskLead, ShiftManager, Cashier, LoyaltyMember, FleetManager |
| POST | /fuel-sales/{id}/dispensing-start | Begin fueling | Cashier, FuelDeskLead |
| POST | /fuel-sales/{id}/dispensing-complete | End fueling; records dispensed gallons; frees pump | Cashier, FuelDeskLead |
| POST | /fuel-sales/{id}/finalize | Finalize amounts from snapshots; burns and grants loyalty points; contract volume cascade | Cashier, FuelDeskLead |
| POST | /fuel-sales/{id}/pay | Collect payment | Cashier |
| POST | /fuel-sales/{id}/void | Void a sale; refund-void when completed | ShiftManager |
| POST | /sites/{id}/parking-spaces | Create a parking space | GeneralManager |
| GET | /sites/{id}/parking-spaces | List parking spaces | GeneralManager, ShiftManager, Cashier |
| GET | /parking-spaces/{id} | Get parking space | GeneralManager, ShiftManager, Cashier |
| GET | /parking-spaces/{id}/reservations | Reservations assigned to this space | GeneralManager, ShiftManager, Cashier |
| POST | /sites/{id}/parking-reservations | Reserve paid parking; computes amount; validates plate ownership, window, aggregate capacity | Cashier, LoyaltyMember |
| GET | /sites/{id}/parking-reservations | List parking reservations | GeneralManager, ShiftManager, Cashier |
| GET | /parking-reservations/{id} | Get parking reservation | GeneralManager, ShiftManager, Cashier, LoyaltyMember |
| POST | /parking-reservations/{id}/check-in | Check in: assigns space, charges amount, earns points | Cashier |
| POST | /parking-reservations/{id}/check-out | Check out; frees space | Cashier |
| POST | /parking-reservations/{id}/cancel | Cancel reservation; paid cancel refunds in full | Cashier, LoyaltyMember |
| POST | /parking-reservations/{id}/no-show | Mark no-show after the two-hour grace | Cashier, ShiftManager |
| POST | /sites/{id}/service-tickets | Create a shower or laundry queue ticket; price computed with surcharges and points | Cashier, LoyaltyMember |
| GET | /sites/{id}/service-tickets | List service tickets | GeneralManager, ShiftManager, Cashier |
| GET | /service-tickets/{id} | Get service ticket | GeneralManager, ShiftManager, Cashier, LoyaltyMember |
| POST | /sites/{id}/service-queue/call | Call the next queued ticket of a service type | Cashier |
| POST | /service-tickets/{id}/start | Start service; capacity check with overstay preemption | Cashier |
| POST | /service-tickets/{id}/complete | Complete service; computes water usage | Cashier |
| POST | /service-tickets/{id}/pay | Pay for service | Cashier |
| POST | /service-tickets/{id}/cancel | Cancel while queued or called; refunds when paid | Cashier, LoyaltyMember |
| POST | /service-tickets/{id}/no-show | Mark called ticket no-show | Cashier |
| POST | /service-tickets/{id}/requeue | Requeue a no-show ticket to the back of the queue | Cashier |
| POST | /sites/{id}/scale-tickets | Open a scale ticket | Cashier |
| GET | /sites/{id}/scale-tickets | List scale tickets | GeneralManager, ShiftManager, Cashier |
| GET | /scale-tickets/{id} | Get scale ticket | GeneralManager, ShiftManager, Cashier |
| POST | /scale-tickets/{id}/weigh | Append a weigh event (gross, tare, or reweigh) | Cashier |
| GET | /scale-tickets/{id}/weigh-events | List weigh events of a ticket | GeneralManager, ShiftManager, Cashier |
| POST | /scale-tickets/{id}/settle | Settle scale fees (first weigh plus certified fee) | Cashier |
| POST | /scale-tickets/{id}/close | Close a paid ticket at driver departure | Cashier |
| POST | /scale-tickets/{id}/cancel | Cancel: unpaid becomes cancelled; paid becomes refunded in full | Cashier, ShiftManager |
| POST | /sites/{id}/stock-items | Create a stock item | GeneralManager |
| GET | /sites/{id}/stock-items | List stock items | GeneralManager, ShiftManager, Cashier, MaintenanceTech |
| GET | /stock-items/{id} | Get stock item | GeneralManager, ShiftManager, Cashier, MaintenanceTech |
| GET | /stock-items/{id}/work-order-parts | Shop part issues referencing this item | GeneralManager, MaintenanceTech |
| POST | /sites/{id}/vendors | Create a vendor | GeneralManager |
| GET | /sites/{id}/vendors | List vendors | GeneralManager, ShiftManager, MaintenanceTech |
| GET | /vendors/{id} | Get vendor | GeneralManager, ShiftManager, MaintenanceTech |
| POST | /vendors/{id}/price-list | Add a vendor price entry | GeneralManager |
| GET | /vendors/{id}/price-list | List vendor price entries | GeneralManager, MaintenanceTech |
| GET | /vendors/{id}/stock-items | Stock items preferring this vendor | GeneralManager, MaintenanceTech |
| GET | /vendors/{id}/purchase-orders | Purchase orders placed with this vendor | GeneralManager, MaintenanceTech |
| GET | /vendors/{id}/deliveries | Bulk deliveries attributed to this vendor | GeneralManager, FuelDeskLead |
| POST | /sites/{id}/purchase-orders | Create a purchase order in draft | GeneralManager |
| GET | /sites/{id}/purchase-orders | List purchase orders | GeneralManager, MaintenanceTech |
| GET | /purchase-orders/{id} | Get purchase order | GeneralManager, MaintenanceTech |
| POST | /purchase-orders/{id}/approve | Approve purchase order | GeneralManager |
| POST | /purchase-orders/{id}/receive | Receive fully or partially against an order; replenishes stock | GeneralManager, MaintenanceTech |
| POST | /purchase-orders/{id}/cancel | Cancel purchase order (draft or approved only) | GeneralManager |
| POST | /sites/{id}/bays | Create a shop bay | GeneralManager |
| GET | /sites/{id}/bays | List bays | GeneralManager, MaintenanceTech, ShiftManager |
| GET | /bays/{id} | Get bay | GeneralManager, MaintenanceTech, ShiftManager |
| GET | /bays/{id}/work-orders | Work orders scheduled in this bay | GeneralManager, MaintenanceTech |
| POST | /bays/{id}/maintenance-block | Block a bay for maintenance over a closed interval | GeneralManager, MaintenanceTech |
| POST | /bays/{id}/maintenance-clear | Return bay to service | GeneralManager, MaintenanceTech |
| POST | /sites/{id}/technicians | Create a technician | GeneralManager |
| GET | /sites/{id}/technicians | List technicians | GeneralManager, MaintenanceTech, ShiftManager |
| GET | /technicians/{id} | Get technician | GeneralManager, MaintenanceTech, ShiftManager |
| GET | /technicians/{id}/work-orders | Work orders assigned to this technician | GeneralManager, MaintenanceTech |
| POST | /sites/{id}/work-orders | Create a work order | Cashier, MaintenanceTech, GeneralManager |
| GET | /sites/{id}/work-orders | List work orders | GeneralManager, MaintenanceTech, ShiftManager, Cashier |
| GET | /work-orders/{id} | Get work order | GeneralManager, MaintenanceTech, ShiftManager, Cashier, FleetManager |
| POST | /work-orders/{id}/estimate | Record labor estimate | MaintenanceTech |
| POST | /work-orders/{id}/approve-estimate | Approve estimate (general manager for retail; fleet manager for own fleet) | GeneralManager, FleetManager |
| POST | /work-orders/{id}/schedule | Schedule bay, technician, and window; overlap checks | GeneralManager, MaintenanceTech |
| POST | /work-orders/{id}/check-in | Check in to bay (bay must be idle) | MaintenanceTech |
| POST | /work-orders/{id}/start-work | Start work (assigned technician only) | MaintenanceTech |
| POST | /work-orders/{id}/parts | Issue a part from stock to the work order | MaintenanceTech |
| GET | /work-orders/{id}/parts | List parts issued to a work order | GeneralManager, MaintenanceTech, Cashier |
| POST | /work-order-parts/{id}/return | Return issued quantity to stock | MaintenanceTech |
| POST | /work-orders/{id}/dispatch-road | Dispatch as road service (no bay) | GeneralManager, MaintenanceTech |
| POST | /work-orders/{id}/road-complete | Complete a road-service call | MaintenanceTech |
| POST | /work-orders/{id}/send-to-vendor | Send bay work to an outside vendor | MaintenanceTech |
| POST | /work-orders/{id}/return-from-vendor | Receive work back from outside vendor | MaintenanceTech |
| POST | /work-orders/{id}/complete-work | Complete bay work; computes invoice; frees bay | MaintenanceTech |
| POST | /work-orders/{id}/close | Collect payment and close | Cashier, GeneralManager |
| POST | /work-orders/{id}/cancel | Cancel work order; returns issued parts; frees bay | GeneralManager, MaintenanceTech |
| POST | /sites/{id}/registers | Create a register | GeneralManager |
| GET | /sites/{id}/registers | List registers | GeneralManager, ShiftManager |
| GET | /registers/{id} | Get register (posture reflects its open shift) | GeneralManager, ShiftManager |
| GET | /registers/{id}/shifts | Shifts on this register | GeneralManager, ShiftManager |
| GET | /registers/{id}/cash-drops | Cash drops from this register | GeneralManager, ShiftManager |
| GET | /registers/{id}/safe-deposits | Safe deposits from this register | GeneralManager, ShiftManager |
| POST | /sites/{id}/shifts | Open a shift on a register | ShiftManager |
| GET | /sites/{id}/shifts | List shifts | GeneralManager, ShiftManager |
| GET | /shifts/{id} | Get shift | GeneralManager, ShiftManager, Cashier |
| POST | /shifts/{id}/drops | Record a cash drop to the safe (owning cashier only) | Cashier |
| POST | /shifts/{id}/payouts | Approve a cash payout from the drawer (manager other than the cashier) | ShiftManager |
| POST | /shifts/{id}/close | Close shift: counted cash, variance, reconciliation, safe deposit | ShiftManager |
| POST | /shifts/{id}/reconcile | Review-acknowledge a closed shift (manager other than the closer) | ShiftManager |
| POST | /shifts/{id}/lock | Lock a reconciled shift (audit final) | GeneralManager |
| GET | /shifts/{id}/reconciliations | Reconciliation records of a shift | GeneralManager, ShiftManager |
| GET | /shifts/{id}/cash-drops | Cash drops of a shift | GeneralManager, ShiftManager, Cashier |
| GET | /shifts/{id}/safe-deposits | Safe deposits of a shift | GeneralManager, ShiftManager |
| GET | /shifts/{id}/fuel-sales | Fuel sales attributed to a shift | GeneralManager, ShiftManager, Cashier |
| GET | /shifts/{id}/parking-reservations | Paid parking reservations attributed to a shift | GeneralManager, ShiftManager, Cashier |
| GET | /shifts/{id}/service-tickets | Service tickets attributed to a shift | GeneralManager, ShiftManager, Cashier |
| GET | /shifts/{id}/scale-tickets | Scale tickets attributed to a shift | GeneralManager, ShiftManager, Cashier |
| GET | /shifts/{id}/store-sales | Store sales attributed to a shift | GeneralManager, ShiftManager, Cashier |
| POST | /fleet-accounts | Create a fleet account | GeneralManager |
| GET | /fleet-accounts/{id} | Get fleet account | GeneralManager, FleetManager |
| PATCH | /fleet-accounts/{id} | Update credit limit | GeneralManager |
| POST | /fleet-accounts/{id}/credit-hold | Place fleet on credit hold | GeneralManager |
| POST | /fleet-accounts/{id}/credit-reinstate | Reinstate fleet credit | GeneralManager |
| POST | /fleet-accounts/{id}/close | Close fleet (zero balance required); terminates non-terminal contracts | GeneralManager |
| POST | /fleet-accounts/{id}/tier-recompute | Recompute rolling volume and pricing tier | GeneralManager |
| GET | /fleet-accounts/{id}/contracts | Contracts of a fleet | GeneralManager, FleetManager |
| GET | /fleet-accounts/{id}/loyalty-members | Loyalty members linked to a fleet | GeneralManager, FleetManager |
| GET | /fleet-accounts/{id}/fuel-sales | Fuel sales billed to a fleet | GeneralManager, FleetManager |
| GET | /fleet-accounts/{id}/work-orders | Work orders billed to a fleet | GeneralManager, FleetManager, MaintenanceTech |
| POST | /fleet-accounts/{id}/contracts | Create a fuel contract (pending) | GeneralManager |
| GET | /contracts/{id} | Get contract | GeneralManager, FleetManager |
| PATCH | /contracts/{id} | Amend contract discount or window; OCC on contract version; discount shortfall re-checked | GeneralManager |
| POST | /contracts/{id}/activate | Activate contract (window and fleet must permit) | GeneralManager |
| POST | /contracts/{id}/suspend | Suspend contract | GeneralManager |
| POST | /contracts/{id}/resume | Resume contract | GeneralManager |
| POST | /contracts/{id}/expire | Expire contract | GeneralManager |
| POST | /contracts/{id}/terminate | Terminate contract | GeneralManager |
| GET | /contracts/{id}/fuel-sales | Fuel sales quoting this contract | GeneralManager, FleetManager |
| POST | /loyalty-members | Register a loyalty member | Cashier, GeneralManager |
| GET | /loyalty-members/{id} | Get loyalty member | GeneralManager, Cashier, ShiftManager, FuelDeskLead, LoyaltyMember |
| POST | /loyalty-members/{id}/suspend | Suspend member | GeneralManager |
| POST | /loyalty-members/{id}/reactivate | Reactivate member | GeneralManager |
| POST | /loyalty-members/{id}/close | Close member; cancels enrollments; forfeits points | GeneralManager |
| POST | /loyalty-members/{id}/adjustments | Manual points adjustment (positive or negative) | GeneralManager |
| GET | /loyalty-members/{id}/points-ledger | Points lots ledger | GeneralManager, Cashier, LoyaltyMember |
| POST | /loyalty-members/{id}/vehicles | Register a vehicle plate | LoyaltyMember, Cashier, GeneralManager |
| GET | /loyalty-members/{id}/vehicles | List member vehicles | GeneralManager, Cashier, LoyaltyMember |
| POST | /loyalty-members/{id}/discount-enrollments | Enroll member in a discount network (pending) | LoyaltyMember, Cashier, GeneralManager |
| GET | /loyalty-members/{id}/discount-enrollments | List member enrollments | GeneralManager, Cashier, LoyaltyMember |
| GET | /loyalty-members/{id}/fuel-sales | Member fuel sales | GeneralManager, Cashier, LoyaltyMember |
| GET | /loyalty-members/{id}/parking-reservations | Member parking reservations | GeneralManager, Cashier, LoyaltyMember |
| GET | /loyalty-members/{id}/service-tickets | Member service tickets | GeneralManager, Cashier, LoyaltyMember |
| GET | /loyalty-members/{id}/store-sales | Member store sales | GeneralManager, Cashier, LoyaltyMember |
| POST | /discount-networks | Create a discount network program (draft) | GeneralManager |
| GET | /discount-networks/{id} | Get network program | GeneralManager, Cashier, FuelDeskLead |
| GET | /discount-networks/{id}/enrollments | List enrollments of a network | GeneralManager, Cashier |
| POST | /discount-networks/{id}/activate | Activate network | GeneralManager |
| POST | /discount-networks/{id}/retire | Retire network; cascades enrollments to retired | GeneralManager |
| POST | /discount-enrollments/{id}/activate | Activate enrollment (network active, no duplicate, cap room) | Cashier, GeneralManager |
| POST | /discount-enrollments/{id}/suspend | Suspend enrollment | GeneralManager |
| POST | /discount-enrollments/{id}/resume | Resume enrollment (re-checks cap) | GeneralManager |
| POST | /discount-enrollments/{id}/cancel | Cancel enrollment (self or general manager) | LoyaltyMember, GeneralManager |
| POST | /sites/{id}/store-sales | Ring up a restaurant or retail sale; decrements stock; earns points | Cashier |
| GET | /sites/{id}/store-sales | List store sales | GeneralManager, ShiftManager, Cashier |
| GET | /store-sales/{id} | Get store sale | GeneralManager, ShiftManager, Cashier, LoyaltyMember |
| POST | /store-sales/{id}/refund | Refund a store sale; restores stock; claws back points | ShiftManager |
| POST | /sites/{id}/bulk-tanks | Create a bulk tank or tote (diesel, DEF, or oil) | GeneralManager |
| GET | /sites/{id}/bulk-tanks | List bulk tanks | GeneralManager, FuelDeskLead, ShiftManager |
| GET | /bulk-tanks/{id} | Get bulk tank | GeneralManager, FuelDeskLead, ShiftManager |
| POST | /bulk-tanks/{id}/stick-reading | Record a physical stick reading; replaces book inventory | FuelDeskLead, GeneralManager |
| POST | /bulk-tanks/{id}/deliveries | Record a bulk delivery; updates inventory and, for diesel, rack price | FuelDeskLead, GeneralManager |
| GET | /bulk-tanks/{id}/deliveries | List deliveries of a tank | GeneralManager, FuelDeskLead |
| GET | /sites/{id}/reorder-suggestions | Computed diesel, DEF, and oil reorder suggestions | GeneralManager, FuelDeskLead |
| POST | /_clock/set_current_utc | Set the logical clock (ISO 8601 UTC) | GeneralManager |
| GET | /_clock | Read the logical clock | GeneralManager, ShiftManager, FuelDeskLead, Cashier, MaintenanceTech, FleetManager, LoyaltyMember |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 beside the workflows each error guards.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PUMP_NOT_AVAILABLE | 409 |
| ERR_SHIFT_NOT_OPEN | 409 |
| ERR_REGISTER_NOT_AVAILABLE | 409 |
| ERR_FLEET_NOT_ACTIVE | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_BAY_OCCUPIED | 409 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_WATER_BOTTOM_EXCEEDED | 422 |
| ERR_INVALID_PRICING_MODE | 422 |
| ERR_PLATE_NOT_REGISTERED | 422 |
| ERR_CONTRACT_FUEL_TYPE | 422 |
| ERR_INVALID_WINDOW | 422 |
| ERR_OVERLAPPING_PRICE_WINDOW | 422 |
| ERR_BAY_DOUBLE_BOOKED | 422 |
| ERR_BAY_MAINTENANCE_CONFLICT | 422 |
| ERR_NO_ACTIVE_PRICE | 422 |
| ERR_NETWORK_NOT_ACTIVE | 422 |
| ERR_DUPLICATE_NETWORK_ENROLLMENT | 422 |
| ERR_NETWORK_CAP_REACHED | 422 |
| ERR_PARKING_CAPACITY_FULL | 422 |
| ERR_QUEUE_CAPACITY | 422 |
| ERR_QUEUE_EMPTY | 422 |
| ERR_SCALE_NOT_CERTIFIABLE | 422 |
| ERR_LOW_STOCK_APPROVAL_REQUIRED | 422 |
| ERR_INSUFFICIENT_STOCK | 422 |
| ERR_NO_POINTS | 422 |
| ERR_CONTRACT_DISCOUNT_SHORTFALL | 422 |
| ERR_CREDIT_LIMIT_EXCEEDED | 422 |
| ERR_DROP_MISMATCH | 422 |
| ERR_DROP_EXCEEDS_EXPECTED | 422 |
| ERR_PAYOUT_EXCEEDS_EXPECTED | 422 |
| ERR_REMAINING_BELOW_FLOAT | 422 |
| ERR_COUNT_SHORTAGE_UNAPPROVED | 422 |
