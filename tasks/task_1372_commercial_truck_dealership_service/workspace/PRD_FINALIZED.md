# Commercial Truck Dealership API — Product Requirements Document

## 1. Introduction

Running a Freightliner dealership means living inside three clocks at once: the factory's build calendar, which hands out a finite number of production slots per month; the floor-plan lender's interest meter, which accrues on every new truck sitting unsold on the lot; and the service department's downtime promise to fleets whose trucks earn nothing while they sit in a bay. This document specifies a single REST API, mounted under `/dealership`, that models all three clocks — a logical, monotonic clock that an operator drives deterministically — together with the commercial workflows that hang off them: chassis and vocational upfit configuration against factory build-slot pools, order commitment and receiving into floor-planned inventory, trade appraisal negotiation with a strict offer-ceiling discipline, service bay and mobile road-call scheduling with bay-hours and travel-buffer overlap semantics, a two-dimension repair order lifecycle (customer authorization tracked independently of work execution), OEM warranty claim submission, adjudication, appeal, and write-off, and a parts counter with tiered fleet pricing and restocking-fee returns.

The audience is the engineering team building the service. Two design commitments shape everything that follows. First, scarcity is first-class: build slots, service bays, and mobile units are contested pools whose counters and overlap rules are enforced transactionally at write time. Second, the dealership's money story is a ledger: a floor-plan balance is never a free-standing number but always the signed sum of posted entries, and a customer account's open receivable moves only through named business events — invoicing, cancellation fees, payments, warranty adjudications, and parts-sale credits — each of which re-evaluates the account's credit standing.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role string not among the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once headers are well-formed, the role must be permitted on the target endpoint per the authorization table in §4; otherwise the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). A third authorization check applies on specific customer-facing and adjudication flows: a `FleetCustomer` acting on another account's appraisal or repair order is rejected with `ERR_INSUFFICIENT_PERMISSIONS`, and a warranty adjudicator whose identity matches the claim's submitter is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

The declared roles, spelled exactly as clients must send them, are `DealershipAdmin`, `SalesManager`, `SalesConsultant`, `ServiceManager`, `ServiceAdvisor`, `PartsCounterRep`, `WarrantyAdministrator`, `OEMClaimsAdjudicator`, `Controller`, and `FleetCustomer`.

Identity semantics differ by role. When `X-User-Role` is `FleetCustomer`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` compare the resource's foreign-key field to `X-User-ID`. For every other role — `DealershipAdmin`, `SalesManager`, `SalesConsultant`, `ServiceManager`, `ServiceAdvisor`, `PartsCounterRep`, `WarrantyAdministrator`, `OEMClaimsAdjudicator`, and `Controller` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by_user_id` on `WarrantyClaim`, where the submit transition writes it) but does not compare it to any entity's `id`. The single exception to that opacity is the segregation-of-duties anchor: adjudication compares the caller's `X-User-ID` against the claim's stored `submitted_by_user_id`.

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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`. The default sort order on every list endpoint is `created_at` ascending.

### 2.4. The Logical Clock

The dealership runs on a logical clock, not wall-clock time. At server startup the clock reads `2026-08-01T00:00:00Z`, and it never resets to wall-clock time thereafter. A `DealershipAdmin` advances the clock through a test-driving capability that sets the current time to a supplied `to_iso8601` instant; the supplied instant must be strictly after the current clock value, and a regression is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409). Every timestamp the business logic consumes — hold expirations, offer expirations, aging, interest accrual, no-show detection, the build-cycle cadence — reads this logical clock, and timestamps written by the system (`submitted_at`, `adjudicated_at`, `completed_at`, and the like) are stamped from it. The clock endpoint answers 200 with the current time under the key `current_utc`.

### 2.5. Common Resource Properties

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format refreshed on every mutation, and a `version` integer that increments on every mutation. The sole exception is `FloorPlanEntry`, which is an append-only ledger line: it carries `id` and `created_at` but has neither `updated_at` nor `version`. All resources live in a flat URL space directly under `/dealership`; there is no nested path hierarchy, so path-identifier validation is simply confirming that each referenced identifier exists, producing the appropriate `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) from the catalogue in §5.

### 2.6. Monetary Precision and Rounding

All money in the system is integer cents. Wherever a calculation produces a fraction — a percentage discount, a prorated interest charge, a depreciation curve — the result is rounded half-up to integer cents at each rounding step the formula specifies. Two calculations pin their rounding order explicitly and implementers must not reorder: parts counter pricing rounds each line's unit net price before multiplying and summing, and repair order totals evaluate in a fixed dependency order described in §3.7. Interest accrues on a 360-day year.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale client state. Updating an account — the SalesManager's patch of `fleet_tier`, `credit_limit_cents`, or `status` — requires the request to carry `expected_customer_account_version` holding the version of the `CustomerAccount` the client last observed. If the account's current `version` no longer matches — because any write, including the cascaded receivable and credit-posture updates described in §3, has advanced it since the client last read the record — the patch is rejected with `ERR_STALE_VERSION` (HTTP 412). Symmetrically, a `Controller` posting a manual floor-plan adjustment must carry `expected_unit_version` matching the target unit's current `version`; the client computed its adjustment from a balance view that the ledger may since have moved past, so a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes an expected-version field.

### 2.8. The Floor-Plan Ledger

A floor-plan balance is a derived figure, never a stored editable number. For each unit the invariant holds that `floorplan_balance_cents` equals the signed sum of `amount_cents` over all of that unit's `FloorPlanEntry` records. Each entry's `entry_type` is one of five values — `ADVANCE`, `INTEREST_ACCRUAL`, `CURTAILMENT`, `PAYOFF`, and `ADJUSTMENT` — with a sign convention: advances and interest accruals are positive, curtailments and payoffs negative, and adjustments signed either way. Each entry carries its `entry_date` (the logical calendar date, `YYYY-MM-DD`, at posting), a nullable free-text `note` (used for adjustments and curtailments), and a `resulting_balance_cents` giving the running balance after that entry in chronological replay order — entries ordered by `entry_date` ascending, with `created_at` ascending as the tie-break. The ledger for a unit is retrievable in that chronological order.

### 2.9. Credit Posture: The Receivable and the Hold

Each customer account carries a credit ceiling `credit_limit_cents` (defaulting to 0) and a running receivable `open_ar_cents` (starting at 0). The receivable moves only through named events: invoicing a repair order adds `customer_due_cents`; cancelling a committed customer-backed factory order adds the cancellation fee; posting a customer payment subtracts the amount paid; a parts sale to a fleet account adds the sale total; a parts return credits the fleet account's receivable, floored at zero; and warranty adjudication on an invoiced repair order adjusts the receivable by the resulting change in what the customer owes. Every event that moves the receivable re-evaluates credit posture: a `FLEET` account whose `open_ar_cents` exceeds its `credit_limit_cents` is placed on `CREDIT_HOLD`, and when the receivable later falls to at or below the ceiling the account returns to `ACTIVE`. The credit ceiling is only ever checked for `FLEET` accounts; `RETAIL` accounts carry no credit check.

### 2.10. Validation Order

When a request fails several rules, the first failing check by the following fixed priority determines the error returned:

1. Header presence and declared role — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role permitted on the endpoint — `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. Segregation of duties and customer ownership — `ERR_SEGREGATION_OF_DUTIES` (403) for adjudication, `ERR_INSUFFICIENT_PERMISSIONS` (403) for a `FleetCustomer` acting on another account's appraisal or repair order.
4. Body well-formedness: required fields present, enum values valid, numeric ranges valid (`hours` greater than zero, `quantity` at least 1, `capacity` at least 1, `end_at` strictly after `start_at`, `close_hour` strictly after `open_hour`) — `ERR_INVALID_REQUEST` (400).
5. Existence of path and body identifiers — the resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404).
6. Stale-version checks on the two OCC endpoints — `ERR_STALE_VERSION` (412).
7. Target-entity state permitting the transition — the domain state errors at 409.
8. Upfit compatibility — `ERR_UPFIT_INCOMPATIBLE` / `ERR_UPFIT_DEPENDENCY_MISSING` (422).
9. Uniqueness: unit VIN, part SKU, and the build-month-plus-vocation-group pool pair — `ERR_DUPLICATE_VIN` / `ERR_DUPLICATE_SKU` / `ERR_INVALID_REQUEST` (409).
10. Specification freeze on committed orders — `ERR_SPEC_FROZEN` (409).
11. Booking resource selection — `ERR_SERVICE_RESOURCE_SELECTION` (422).
12. Operating-hours and resource-active checks — `ERR_BAY_OUTSIDE_OPERATING_HOURS` (422) / `ERR_RESOURCE_OUT_OF_SERVICE` (409).
13. Vehicle reference on repair order creation — `ERR_VEHICLE_REFERENCE_REQUIRED` (422).
14. Claimed amounts against warranty-eligible line sums, part stock sufficiency, and part active status — `ERR_INVALID_REQUEST` / `ERR_INSUFFICIENT_STOCK` / `ERR_PART_DISCONTINUED` (409). Within this level, when a part fails both stock sufficiency and active status, the stock check is evaluated first and `ERR_INSUFFICIENT_STOCK` is returned.
15. Clock monotonicity — `ERR_CLOCK_REGRESSION` (409).
16. Booking overlap — `ERR_BAY_BOOKING_OVERLAP` / `ERR_MOBILE_BOOKING_OVERLAP` (409).
17. Slot-pool month still open for holds and re-holds — `ERR_SLOT_MONTH_CLOSED` (409).
18. Slot-pool capacity remaining — `ERR_SLOT_POOL_EXHAUSTED` (409).
19. Cross-resource preconditions: referenced appraisal `ACCEPTED` and buyer-owned at sale, a `CHECKED_IN` booking at start-work, an invoiced repair order at claim submission — `ERR_APPRAISAL_STATE` / `ERR_BOOKING_NOT_CHECKED_IN` / `ERR_RO_STATE` (409).
20. Fiscal posture at sale and invoicing — `ERR_CREDIT_LIMIT_EXCEEDED` (402) / `ERR_ACCOUNT_ON_CREDIT_HOLD` (409).
21. Offer, adjudication, payment, and write-off fiscal discipline — `ERR_APPRAISAL_OFFER_EXCEEDS_ACV` / `ERR_APPROVAL_EXCEEDS_CLAIM` / `ERR_PAYMENT_AMOUNT_MISMATCH` (422) / `ERR_WRITEOFF_RULE_VIOLATION` (409).
22. Return quantity against sold-minus-returned — `ERR_RETURN_EXCEEDS_SOLD` (422).

### 2.11. The Daily Ops Sweep

A `DealershipAdmin` triggers an ops-run checkpoint that performs the whole day's housekeeping atomically: it posts one floor-plan interest accrual per eligible unit, recomputes aging buckets and scheduled curtailments, expires factory-order holds whose fourteen-day windows have lapsed, promotes orders through the build cycle (at most one promotion per order per run — an order never moves from `COMMITTED` to `IN_PRODUCTION` and on to `SHIPPED` in a single sweep), expires appraisal offers past their ten-day windows, marks bookings no-show once their start has passed by more than an hour without check-in, and closes slot pools whose build month has passed. Within each entity set the sweep processes records in `stocking_date` ascending then `created_at` ascending order — never by `id`. The sweep responds 200 with a tally of its work under the keys `interest_entries_posted`, `units_rebucketed`, `orders_expired`, `orders_started`, `orders_shipped`, `appraisals_expired`, `bookings_no_show`, and `slot_pools_closed`.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and Fleet Tiers

A `SalesManager` opens a customer account with an `account_name`, an `account_type` of `FLEET` or `RETAIL` (immutable after creation), an optional `fleet_tier` of `STANDARD`, `GOLD`, or `PLATINUM` (defaulting to `STANDARD`), and an optional `credit_limit_cents`. New accounts start `ACTIVE` with an `open_ar_cents` of zero. The fleet tier is not cosmetic: it drives the labor discount on repair order invoicing and the per-line discount at the parts counter, as detailed in §3.5 and §3.7. An account's `status` moves among `ACTIVE`, `CREDIT_HOLD`, and `CLOSED`; the `CREDIT_HOLD` transitions are automatic consequences of receivable movement per §2.9, while a manager may patch `status` directly — though setting `status` to `CLOSED` is refused with `ERR_ACCOUNT_ON_CREDIT_HOLD` while any receivable remains open. Listing accounts supports filtering by `account_type`, `fleet_tier`, and `status`.

### 3.2. Build-Slot Pools and Factory Orders

The factory allocates production capacity to the dealership in monthly pools. A `SalesManager` creates a `FactoryBuildSlot` pool for a `build_month` (a `YYYY-MM` string) and a `vocation_group` of `STANDARD` or `SEVERE`, with a `capacity` of at least one; the month-and-vocation pair must be unique, and a duplicate is rejected with `ERR_INVALID_REQUEST`. Pools track `held_count` (orders currently holding a slot) and `committed_count` (orders committed or beyond), and expose `slots_available` — capacity minus both counts, never negative. A pool begins `OPEN`, becomes `LOCKED` automatically the moment a hold, re-hold, or commit drives availability to zero, and reopens to `OPEN` when a cancellation or expiry release makes availability positive again while the build month is still open; once the sweep sees the logical clock past the end of the build month the pool goes `CLOSED` and every order still `SLOT_HELD` against it is expired with the normal release cascade.

A `SalesConsultant` builds a factory order against an `OPEN` pool by naming the `factory_build_slot_id`, a `chassis_model` of `CASCADIA_126`, `M2_106`, or `SD_114`, an `engine_option` of `DD13`, `DD15`, or `CUMMINS_X15`, an `axle_config` of `A4X2` or `A6X4`, an optional `customer_account_id` (absent means a dealer-stock order), and optional `upfit_lines`, each an embedded `component_code` and `price_cents` pair. Vocational upfit component codes are `DUMP_BODY`, `REEFER_BOX`, `CRANE_PTO`, `LIFTGATE`, and `VAN_BODY`, and compatibility is enforced at order creation and again whenever a line is appended: a `CRANE_PTO` requires the order's vocation group to be `SEVERE`; `REEFER_BOX` and `DUMP_BODY` are mutually exclusive on one order; and a `LIFTGATE` requires a `VAN_BODY` or `REEFER_BOX` on the same order. Violations are rejected with `ERR_UPFIT_INCOMPATIBLE` (422) for the first two rules and `ERR_UPFIT_DEPENDENCY_MISSING` (422) for the missing-body rule. Three temporal checks also apply at creation and re-hold: the pool must not be past its build month (`ERR_SLOT_MONTH_CLOSED`), it must have at least one slot available (`ERR_SLOT_POOL_EXHAUSTED`), and the order state must permit the action (`ERR_ORDER_STATE`).

A created order lands in `SLOT_HELD`, copies its `vocation_group` from the pool, stamps `hold_expires_at` fourteen days out from the clock, computes its `provisional_total_cents` per the pricing rule below, and bumps the pool's `held_count` by one — locking the pool if that consumes the last slot. Additional upfit lines may be appended only while the order remains `SLOT_HELD`; once committed the specification is frozen and a further append is rejected with `ERR_SPEC_FROZEN`. Each appended line re-runs the full compatibility validation against the order's complete line set and recomputes the provisional total.

Pricing a factory order is a pinned sequence. Start with the chassis base: 14,500,000 cents for a `CASCADIA_126`, 9,800,000 cents for an `M2_106`, 12,300,000 cents for an `SD_114`. Add the engine surcharge — nothing for `DD13`, 1,200,000 cents for `DD15`, 1,450,000 cents for `CUMMINS_X15` — and the axle surcharge, nothing for `A4X2` and 850,000 cents for `A6X4` — to form the subtotal. A loyalty rebate then applies based on how many orders the same customer account already holds in `COMMITTED`, `IN_PRODUCTION`, `SHIPPED`, or `DELIVERED` status: at most two such prior orders means no rebate, three through five priors earns a rebate of two percent of the subtotal, and six or more priors earns four percent; the rebate is rounded half-up to integer cents. Dealer-stock orders (no customer account) always count zero priors. The upfit total is the sum of the upfit line prices, multiplied by 1.08 when the order's vocation group is `SEVERE` and by 1.00 otherwise, rounded half-up to integer cents. The final price is the subtotal minus the rebate, plus the upfit total, plus a destination fee of 285,000 cents. This price is computed twice in the order's life with a customer-count snapshot taken at each moment: once at creation, stored as `provisional_total_cents` (the provisional variant), and again at commit, stored as `committed_total_cents` and locked. Because the snapshot is re-taken, the committed total may legitimately differ from the provisional one.

Committing an order — permitted to a `SalesConsultant` while the order is `SLOT_HELD` and the clock is still before `hold_expires_at`; both violations surface `ERR_ORDER_STATE`, a lapsed hold requiring either the sweep's expiry or a re-hold — moves the order to `COMMITTED`, locks `committed_total_cents`, and shifts the pool counters: `held_count` down one, `committed_count` up one. Cancelling is permitted from either `SLOT_HELD` or `COMMITTED` and releases the slot (decrementing whichever counter the order sat in) with the pool-posture re-evaluation described above. Cancelling a `COMMITTED` order that names a customer account additionally charges a cancellation fee of two percent of `committed_total_cents`, rounded half-up, added to that account's `open_ar_cents` — which may itself push a `FLEET` account onto `CREDIT_HOLD` per §2.9. Dealer-stock orders accrue no fee.

The sweep runs the lifecycle's clockwork: a `SLOT_HELD` order whose `hold_expires_at` has been reached goes `EXPIRED` with the slot released; a `COMMITTED` order goes `IN_PRODUCTION` once the clock reaches the first day of its build month, and `IN_PRODUCTION` goes `SHIPPED` once the clock reaches fourteen days after the first of the build month, with at most one promotion per order per sweep. An `EXPIRED` order is not dead: a `SalesConsultant` may re-hold it against a new pool, which updates the order's `factory_build_slot_id`, refreshes `vocation_group` from the new pool, restamps the fourteen-day hold window, and increments the new pool's `held_count`, locking it if full.

Receiving is the `SalesManager`'s act: a `SHIPPED` order is received with a `vin` (rejected with `ERR_ORDER_STATE` if the order is not `SHIPPED`, and with `ERR_DUPLICATE_VIN` if any unit already carries that VIN) and an optional `apr_bp`. The order moves to `DELIVERED`, its `received_unit_id` is set, and a new `Unit` is born: `unit_kind` `NEW`, status `IN_STOCK`, `invoice_cost_cents` equal to the order's `committed_total_cents`, `stocking_date` the current clock date, `floorplan_active` true, `apr_bp` captured from the payload (defaulting to 690 basis points — 6.90 percent — when omitted), and `factory_order_id` linking back. Because the unit is floor-planned, its creation also posts the first ledger entry: an `ADVANCE` equal to `invoice_cost_cents`, establishing `floorplan_balance_cents` at the invoice cost and `last_accrual_date` at the stocking date. Orders may be listed with filters on `customer_account_id`, `factory_build_slot_id`, and `status`; pools may be listed with filters on `build_month` and `status`.

### 3.3. Units: Inspection, Aging, Floor Plan, Sale, Wholesale

Every unit on the lot moves along `IN_STOCK` → `RECONDITIONING` → `READY`, with the reconditioning loop explicit: a `ServiceManager` runs an inspection supplying an `outcome` of `PASS` or `FAIL`. Inspection is permitted while the unit is `IN_STOCK`, `RECONDITIONING`, or `READY` (otherwise `ERR_UNIT_STATE`). A `PASS` moves the unit to `READY` from any of those states; a `FAIL` moves it to `RECONDITIONING` — including from `READY`, and including from `RECONDITIONING` itself — and every `FAIL` increments `recondition_count` by one. Units are listed with filters on `unit_kind`, `status`, `aging_bucket`, `factory_order_id`, and `trade_appraisal_id`.

Aging is a function of the clock: `days_in_stock` is the whole-day difference between the clock date and `stocking_date`, recomputed on read and by the sweep. The `aging_bucket` bands are `B0_90` through day 90, `B91_180` for days 91 to 180, `B181_270` for days 181 to 270, `B271_365` for days 271 to 365, and `OVER_365` from day 366 onward — so day 90 still sits in `B0_90`. Scheduled curtailment follows the same clock: nothing through day 180 (day 180 still owes zero), ten percent of `invoice_cost_cents` rounded half-up once the unit reaches day 181, twenty-five percent rounded half-up at day 271, and the full invoice cost at day 366. The scheduled amount lives on the unit as `curtailment_due_cents`.

Interest accrues on floor-plan-active units in `IN_STOCK`, `RECONDITIONING`, or `READY` that carry a positive balance. At each sweep, for each eligible unit, the number of whole days since `last_accrual_date` is taken (skipping the unit when that count is zero or negative), and one `INTEREST_ACCRUAL` entry posts interest equal to the balance times `apr_bp` divided by 10,000, divided by 360, times the days elapsed, rounded half-up to integer cents; `last_accrual_date` then advances to the clock date. This is the *actual accrual* variant — the balance moves only when the sweep, a sale, or a wholesale posts entries. The *payoff projection* variant is forward-looking and posts nothing: given an optional `as_of_date` (defaulting to the clock date), it projects the same interest formula over the whole days from `last_accrual_date` to that date (floored at zero days), then quotes `payoff_cents` as the current `floorplan_balance_cents` plus `projected_interest_cents` plus `curtailment_due_cents`, returning the quote as `unit_id`, `as_of_date`, `balance_cents`, `projected_interest_cents`, `curtailment_due_cents`, and `payoff_cents`. On a unit with days passed since the last sweep, the projection deliberately exceeds the ledger balance until the next accrual posts.

Two `Controller` operations move the ledger directly. A manual adjustment posts a signed `ADJUSTMENT` entry of the supplied `amount_cents` with an optional `note`, adds that amount to `floorplan_balance_cents`, increments the unit's `version`, and is governed by the `expected_unit_version` OCC rule of §2.7. A curtailment payment posts a `CURTAILMENT` entry of negative `amount_cents` with an optional `note`, reducing the balance; the amount must be positive, no more than `curtailment_due_cents`, and no more than `floorplan_balance_cents`, the unit must be floor-plan-active and in `IN_STOCK`, `RECONDITIONING`, or `READY` (otherwise `ERR_UNIT_STATE`), and the posting increments the unit's `version`.

Selling is a `SalesConsultant`'s action against a `READY` unit — any other state is rejected with `ERR_UNIT_NOT_SELLABLE` — naming the buying `customer_account_id`, the `sale_price_cents`, and optionally a `trade_appraisal_id`. The buyer's account must be `ACTIVE`; a `CREDIT_HOLD` or `CLOSED` buyer is rejected with `ERR_ACCOUNT_ON_CREDIT_HOLD`. When a trade appraisal is referenced it must be `ACCEPTED` and belong to the buyer, otherwise `ERR_APPRAISAL_STATE`. On success the system first brings floor-plan interest current with an `INTEREST_ACCRUAL` entry through the clock date (floor-plan units only), then posts a `PAYOFF` entry of the negative balance, driving `floorplan_balance_cents` to zero; `sold_price_cents` and `sold_at` are set, the unit becomes `SOLD`, and a referenced appraisal is consumed to `CONSUMED`.

Wholesaling is the remarketing escape hatch, restricted to a `SalesManager` and to aged stock: the unit must be `READY` (`ERR_UNIT_NOT_SELLABLE` otherwise) and its `aging_bucket` must be `B181_270`, `B271_365`, or `OVER_365` (`ERR_UNIT_NOT_WHOLESALE_ELIGIBLE` otherwise). The wholesaler supplies `wholesale_price_cents`; the same interest-then-payoff sequence clears the floor plan, the unit becomes `WHOLESALED`, and `wholesale_loss_cents` records the shortfall — the excess of `invoice_cost_cents` over `wholesale_price_cents`, floored at zero.

### 3.4. Trade Appraisals: Book, Offer, Counter, Accept

A trade-in begins when a `SalesConsultant` creates an appraisal naming the `customer_account_id`, the trade vehicle's `trade_vin`, its `model_year`, `mileage`, a `condition_grade` of `A`, `B`, or `C`, and the guide's `base_book_value_cents`. The appraisal lands in `DRAFT` with its book estimate computed immediately. The book variant of the trade allowance works as follows: the vehicle's age is the clock's year minus `model_year`, floored at zero; the book value depreciates twelve percent per year of age from the base book value, never below zero; and the estimate subtracts a mileage penalty of 5 cents for every mile beyond the first 150,000 free miles, rounded half-up to integer cents and floored at zero. The result is stored as `book_estimate_cents`. Appraisals may be listed filtered by `customer_account_id` and `status`.

The market variant fires at offer time. A `SalesManager` makes an offer — from either `DRAFT` or `NEGOTIATING`, otherwise `ERR_APPRAISAL_STATE` — supplying `market_index_bp` (an index where 10,000 represents parity) and `offered_allowance_cents`. The actual cash value is the book estimate scaled by a condition multiplier — 1.10 for grade `A`, 1.00 for `B`, 0.85 for `C` — and by the market index divided by 10,000, rounded half-up to integer cents, and stored as `offer_acv_cents`. The offered allowance may not exceed that ceiling; an over-ceiling offer is rejected with `ERR_APPRAISAL_OFFER_EXCEEDS_ACV`. A successful offer moves the appraisal to `OFFERED`, stores the allowance, stamps `offer_expires_at` ten days out, and increments `offer_round` by one.

From `OFFERED`, the customer decides — and these three actions belong to the `FleetCustomer` whose identity matches the appraisal's `customer_account_id`; anyone else is refused with `ERR_INSUFFICIENT_PERMISSIONS`, and acting on an appraisal not in `OFFERED` is `ERR_APPRAISAL_STATE`. Countering moves the appraisal to `NEGOTIATING`, from which the manager may issue a fresh offer under the same ceiling rule. Declining is terminal at `DECLINED`. Accepting requires the clock still be before `offer_expires_at` and produces the dealership's newest used unit: a `Unit` with `unit_kind` `USED`, status `RECONDITIONING` (it must pass inspection before sale), `vin` equal to `trade_vin`, `invoice_cost_cents` equal to `offered_allowance_cents`, `stocking_date` the clock date, `floorplan_active` false, and `trade_appraisal_id` linking back; the appraisal's `created_unit_id` records it. An offer left standing past its expiry is swept to `EXPIRED`. The two allowance variants intentionally disagree for identical inputs — the book estimate anchors intake while only the market figure disciplines the offer.

### 3.5. Service Resources and Booking

The service department's schedulable resources are `ServiceBay`s — created by a `ServiceManager` with a unique `bay_code`, a `bay_type` of `STANDARD` or `HEAVY_ALIGNMENT`, an `open_hour` defaulting to 7, and a `close_hour` defaulting to 19 that must be later than the open hour — and `MobileServiceUnit`s, created with a unique `unit_code` and a `default_travel_minutes` defaulting to 30. Both resources are born `ACTIVE` and may be set `OUT_OF_SERVICE` by the service manager; existing bookings stand when a resource goes down, but new bookings against it are refused with `ERR_RESOURCE_OUT_OF_SERVICE`. Bays list with a `status` filter, as do mobile units.

A `ServiceAdvisor` creates a booking for a repair order with a `start_at` and an `end_at` strictly after it, reserving exactly one resource: `service_bay_id` or `mobile_service_unit_id`, never both, never neither — a violation is `ERR_SERVICE_RESOURCE_SELECTION`, as is a nonzero `travel_minutes` on a bay booking (travel buffer defaults to zero and applies to mobile bookings only). Bay bookings must additionally respect the bay's day: the start hour must be at or after `open_hour` and the end must fall by `close_hour` of the same day, else `ERR_BAY_OUTSIDE_OPERATING_HOURS`.

Overlap semantics differ by resource kind, and in both cases only bookings in `BOOKED` or `CHECKED_IN` status participate, against the same resource. Bay bookings use half-open intervals: two bay bookings conflict only when the existing one's start is strictly before the new one's end and the new one's start is strictly before the existing one's end — so a booking beginning exactly when another ends is allowed. Violations raise `ERR_BAY_BOOKING_OVERLAP`. Mobile bookings instead expand to a closed interval covering one `travel_minutes` buffer on each side — from `travel_minutes` before the start to `travel_minutes` after the end — and two expanded intervals conflict whenever they touch at all; an exact buffer-to-buffer touch counts as a conflict, so adjacency is not allowed on the road. Violations raise `ERR_MOBILE_BOOKING_OVERLAP`.

A booking begins `BOOKED`. Check-in stamps `checked_in_at` from the clock and moves it to `CHECKED_IN` (only from `BOOKED`, else `ERR_BOOKING_STATE`). Cancellation is allowed from `BOOKED` or `CHECKED_IN` and triggers the repair order demotion described in §3.6. The sweep marks a booking `NO_SHOW` once the clock has passed its start by more than 60 minutes without a check-in — an event that likewise runs the demotion check. Finally, when its repair order's work completes, every `CHECKED_IN` booking on that order is swept to `COMPLETED`. Bookings list with filters on `repair_order_id`, `service_bay_id`, `mobile_service_unit_id`, and `status`.

### 3.6. Repair Orders: Two Independent Dimensions

A repair order carries two state dimensions that move independently. The authorization dimension `auth_status` runs `DRAFT` → `PENDING_APPROVAL` → `APPROVED` (or `DECLINED`, which can loop back to `DRAFT`), and the work dimension `work_status` runs `OPEN` → `SCHEDULED` → `IN_PROGRESS` → `COMPLETED` → `INVOICED` → `PAID`. A `ServiceAdvisor` opens an order with the `customer_account_id`, the customer's `concern` text, the downtime commitment `promised_ready_at`, an optional `labor_rate_cents` defaulting to 16,500 cents per hour, and a vehicle reference: exactly one of `unit_id` (a unit in inventory) or `external_vin` (a customer-owned vehicle the dealership has never stocked); supplying both or neither is `ERR_VEHICLE_REFERENCE_REQUIRED`. The order is born with `auth_status` `DRAFT` and `work_status` `OPEN`, and lists can filter by `customer_account_id`, `unit_id`, `auth_status`, and `work_status`.

Lines come next. The advisor appends labor and part lines — allowed only while `auth_status` is `DRAFT` or `DECLINED` and `work_status` is `OPEN` or `SCHEDULED` — with a `line_type` of `LABOR` or `PART`. A `LABOR` line requires `hours` greater than zero; a `PART` line requires a `part_id` and a `quantity` of at least one, and adding it decrements the part's `on_hand` (insufficient stock is `ERR_INSUFFICIENT_STOCK`; a discontinued part is `ERR_PART_DISCONTINUED`). Every line snapshots its `unit_price_cents` — the order's `labor_rate_cents` for labor, the part's `list_price_cents` for parts — and computes `line_total_cents` as the hours times the rate rounded half-up for labor, or quantity times price for parts. A `warranty_eligible` flag (default false) marks lines that may later appear in a warranty claim; `description` is free text. Adding a line recomputes the order's `labor_sum_cents` and `parts_sum_cents`. Lines list with `repair_order_id` and `part_id` filters.

Estimate authorization begins when the advisor submits the estimate: `auth_status` must be `DRAFT` (otherwise `ERR_RO_NOT_AWAITING_CUSTOMER`) and at least one line must exist (otherwise `ERR_RO_STATE`), moving the order to `PENDING_APPROVAL`. The customer then approves or declines — `FleetCustomer` only, identity matched to the order's `customer_account_id` (`ERR_INSUFFICIENT_PERMISSIONS` otherwise), and only from `PENDING_APPROVAL` (`ERR_RO_NOT_AWAITING_CUSTOMER` otherwise). Approval moves to `APPROVED`; decline moves to `DECLINED`, from which the advisor may revise, returning the order to `DRAFT` provided work has not moved past `OPEN` or `SCHEDULED` (`ERR_RO_STATE` otherwise).

On the work dimension, creating the first booking for an order automatically moves it from `OPEN` to `SCHEDULED`. Starting work requires `auth_status` `APPROVED` (`ERR_RO_NOT_APPROVED`), a `work_status` of `OPEN` or `SCHEDULED` (`ERR_RO_STATE`), and at least one booking of this order sitting in `CHECKED_IN` (`ERR_BOOKING_NOT_CHECKED_IN`); it stamps `work_started_at` and moves the order to `IN_PROGRESS`. Completing work (from `IN_PROGRESS` only, else `ERR_RO_STATE`) stamps `completed_at`, computes the downtime penalty described in §3.7, moves the order to `COMPLETED`, and completes every `CHECKED_IN` booking on the order. Meanwhile the SLA watch is the sweep's job: an order still `IN_PROGRESS` past `promised_ready_at` plus a 120-minute grace is flagged `sla_breached`.

Cancelling an order — advisor-only, and refused once `work_status` is `INVOICED`, `PAID`, or already `CANCELLED` (`ERR_RO_STATE`) — sets both dimensions to `CANCELLED` and cancels every `BOOKED` or `CHECKED_IN` booking on the order. The demotion check runs in the opposite direction as well: whenever a booking is cancelled or marked no-show, if no remaining booking of that order is in `BOOKED` or `CHECKED_IN` and the order's `work_status` is `SCHEDULED`, the order demotes back to `OPEN`.

Invoicing belongs to the `ServiceManager`, from `COMPLETED` only (`ERR_RO_STATE`). Two fiscal guards fire first, in §2.10's order: the account must not be `CLOSED` or on credit hold (`ERR_ACCOUNT_ON_CREDIT_HOLD`), and for a `FLEET` account the order's `customer_due_cents` plus the account's existing `open_ar_cents` must not exceed `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402). On success the totals of §3.7 are computed and frozen, `customer_due_cents` is added to the account's receivable, and the order moves to `INVOICED`. Because the credit check passed on the way in, this particular addition cannot itself trigger a hold — but later warranty adjudications that reduce the customer-due figure do re-run the receivable cascade and can clear an existing hold.

Payment closes the loop: a `Controller` posts `amount_cents`, which must equal `customer_due_cents` exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`), the order moves from `INVOICED` to `PAID`, the receivable drops by the amount, and a `FLEET` account whose receivable has fallen back to at or below its ceiling returns from `CREDIT_HOLD` to `ACTIVE`.

### 3.7. Repair Order Totals and the Downtime Penalty

Invoicing computes the order's money fields in a pinned dependency order — the fee derives from discounted labor, the discount from the fleet tier, and the covered amount from claim outcomes. First `labor_sum_cents` is the sum of `line_total_cents` over `LABOR` lines, and `parts_sum_cents` the same over `PART` lines. Then `discount_cents` is the labor sum times the tier rate — zero for `STANDARD`, ten percent for `GOLD`, twenty percent for `PLATINUM` — rounded half-up; the discount touches labor only, never parts. The `shop_supplies_fee_cents` is five percent of the discounted labor (labor sum minus discount), rounded half-up, capped at 3,500 cents. The `warranty_covered_cents` is the sum of `approved_labor_cents` plus `approved_parts_cents` over the order's claims in `APPROVED`, `SHORT_PAID`, or `PAID` status. Finally `customer_due_cents` is the labor sum minus the discount, plus the parts sum, plus the supplies fee, minus `downtime_penalty_cents`, minus the covered amount — floored at zero. These totals are computed at invoicing and recomputed whenever work completes or a claim adjudication moves the covered amount.

The downtime penalty honors the promised-ready commitment. Lateness is the whole minutes from `promised_ready_at` to `completed_at`, never below zero. The first 120 minutes are grace: an order completed exactly 120 minutes late owes nothing, while 121 minutes late owes a penalty. Chargeable minutes are the lateness beyond the grace window, and the raw penalty is those minutes divided by 60, times the order's `labor_rate_cents`, times 25 percent, rounded half-up — then capped at half of `labor_sum_cents` (that cap itself rounded half-up). The result is stored as `downtime_penalty_cents` at completion.

### 3.8. Warranty Claims: Submission, Adjudication, Appeal, Payment

The dealer side of the warranty desk belongs to the `WarrantyAdministrator`. A claim is drafted against a repair order with `claimed_labor_cents` and `claimed_parts_cents`, each at least zero and each capped by the sum of `line_total_cents` over the order's warranty-eligible lines of the matching type — an over-claim is `ERR_INVALID_REQUEST`. The claim is born `DRAFT` and lists with `repair_order_id` and `status` filters. Submission requires the claim be `DRAFT` (`ERR_CLAIM_STATE`) and the repair order be `INVOICED` (`ERR_RO_STATE`); it stamps `submitted_at` and captures the caller's header into `submitted_by_user_id`, the segregation-of-duties anchor.

Adjudication belongs to the `OEMClaimsAdjudicator` and acts on claims in `SUBMITTED` or `APPEALED` (otherwise `ERR_CLAIM_STATE`), with the hard segregation rule that the adjudicator's identity must differ from `submitted_by_user_id` — a self-adjudication is refused with `ERR_SEGREGATION_OF_DUTIES`. Three outcomes are possible, supplied as `outcome`. `APPROVE` sets `approved_labor_cents` and `approved_parts_cents` equal to the claimed amounts. `SHORT_PAY` stores the supplied approved amounts, which must not exceed their claimed counterparts (`ERR_APPROVAL_EXCEEDS_CLAIM`) and must sum to something positive (`ERR_INVALID_REQUEST`). `DENY` zeroes both approved amounts and requires a `denial_reason` (`ERR_INVALID_REQUEST`). All three stamp `adjudicated_at` and land the claim in `APPROVED`, `SHORT_PAID`, or `DENIED` respectively.

Approval and short-pay fire a four-level cascade: the repair order's `warranty_covered_cents` is recomputed as the approved-total sum over its claims in `APPROVED`, `SHORT_PAID`, or `PAID`; the order's `customer_due_cents` is recomputed from the §3.7 formula; if the order is `INVOICED`, the account's `open_ar_cents` is adjusted by the change in customer-due; and that receivable movement re-evaluates the account's credit posture, clearing a `CREDIT_HOLD` back to `ACTIVE` when the receivable returns to at or below the ceiling.

A denied or short-paid claim can be appealed by the warranty administrator with mandatory `appeal_notes` (`ERR_INVALID_REQUEST` if absent), moving to `APPEALED` and incrementing `appeal_count` by one. Appealing out of `SHORT_PAID` additionally re-runs the covered-and-receivable cascade in reverse, since an `APPEALED` claim no longer counts toward `warranty_covered_cents`. From `APPEALED` the claim is adjudicated again under exactly the same rules as a fresh submission. A `DENIED` claim may instead be closed — terminal `CLOSED`.

Money arrives through the `Controller`: posting a claim payment of `amount_cents` requires the claim be `APPROVED` or `SHORT_PAID` (`ERR_CLAIM_STATE`), a positive amount, and a running total `paid_cents` that may not exceed the approved total (`ERR_PAYMENT_AMOUNT_MISMATCH`); when cumulative payments reach the approved total the claim becomes `PAID`. Alternatively, the controller may write off the residual receivable: the residual (approved total minus `paid_cents`) must be positive, and the write-off is permitted only when the residual is at most 2,500 cents or the logical clock has passed `adjudicated_at` by more than 45 days — violations are `ERR_WRITEOFF_RULE_VIOLATION`. A written-off claim is terminal at `WRITTEN_OFF`, its residual absorbed as variance loss. The dealership's reimbursement variance — claimed total minus approved total — is the shortfall it absorbs.

### 3.9. Parts Counter: Catalog, Sales, Returns

The `PartsCounterRep` maintains the catalog: creating a `Part` with a unique `sku` (duplicates rejected `ERR_DUPLICATE_SKU`), a `part_name`, a `list_price_cents` greater than zero, a `cost_cents` of at least zero, an `on_hand` defaulting to zero, and core-charge attributes `has_core_charge` (default false) and `core_charge_cents` (default zero, and never discounted). Parts are born `ACTIVE` and may be moved to `DISCONTINUED`, which blocks future sales and line references with `ERR_PART_DISCONTINUED`.

A counter sale names the `customer_account_id` and `lines` — each a `part_id` and `quantity` — and every line persists as a `PartsSaleLine`. Pricing is pinned per line, in exact order, and the alternative of summing list prices and discounting once is forbidden because per-line rounding yields different cents. The buyer's fleet tier sets a tier discount — zero for `STANDARD`, ten percent for `GOLD`, twenty percent for `PLATINUM` — and a quantity of at least 10 on a line adds a further five percent; the effective discount is their sum capped at forty percent. The line's `unit_net_price_cents` is the part's list price times one minus the effective discount, rounded half-up to integer cents, and `line_total_cents` is that net unit price times the quantity. At the sale level, `subtotal_cents` sums the per-line totals, `core_total_cents` sums the core charge times quantity over lines whose part carries a core charge, and `total_cents` is subtotal plus cores. Stock decrements per line (`ERR_INSUFFICIENT_STOCK` when short), `sold_at` stamps the clock, the sale is born `INVOICED`, and for a `FLEET` account the total lands on the receivable with the usual credit-posture re-evaluation.

Returns operate on individual sale lines. The counter rep returns a `quantity` against a line of a sale in `INVOICED` or `PARTIALLY_RETURNED` (otherwise `ERR_INVALID_REQUEST`); the quantity must be at least one and, together with the line's `returned_quantity` so far, must not exceed the quantity sold (`ERR_RETURN_EXCEEDS_SOLD`). Each return adds to `returned_quantity`, restores that many units to the part's `on_hand`, and credits the line's `return_credit_cents` with the net value of the returned units — the `unit_net_price_cents` times the quantity, rounded half-up — less a restocking fee of fifteen percent of that value when the clock has passed `sold_at` by more than 30 days (no fee within the window). For a `FLEET` buyer the credit reduces `open_ar_cents`, floored at zero. When some but not all of a sale's quantities have come back the sale sits at `PARTIALLY_RETURNED`; once everything is returned — whether in one call or several — it is `FULLY_RETURNED`. Sales list with `customer_account_id` and `status` filters; sale lines list with `parts_sale_id` and `part_id` filters.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; operations that modify an existing resource (including all state-transition actions) return HTTP 200. Reads return the resource envelope of §2.2 with pagination per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /dealership/_clock/set_current_utc | Advance the logical clock (monotonic) | DealershipAdmin |
| POST | /dealership/ops/run-daily-sweep | Run the daily ops checkpoint: accruals, aging, expiries, build cycle, no-shows, pool closes | DealershipAdmin |
| POST | /dealership/customer-accounts | Create a customer account | SalesManager |
| GET | /dealership/customer-accounts | List customer accounts | all roles |
| GET | /dealership/customer-accounts/{id} | Get one customer account | all roles |
| PATCH | /dealership/customer-accounts/{id} | Update tier/credit limit/status with OCC | SalesManager |
| POST | /dealership/factory-build-slots | Create a build slot pool for a build month + vocation group | SalesManager |
| GET | /dealership/factory-build-slots | List slot pools | all roles |
| GET | /dealership/factory-build-slots/{id} | Get one slot pool | all roles |
| POST | /dealership/factory-orders | Create a factory order; immediately holds one slot in the pool | SalesConsultant |
| GET | /dealership/factory-orders | List factory orders | all roles |
| GET | /dealership/factory-orders/{id} | Get one factory order | all roles |
| POST | /dealership/factory-orders/{id}/upfit-lines | Append one upfit component line (spec freeze at COMMITTED) | SalesConsultant |
| POST | /dealership/factory-orders/{id}/commit | Commit a held order; locks price | SalesConsultant |
| POST | /dealership/factory-orders/{id}/re-hold | Re-hold an EXPIRED order against a new pool | SalesConsultant |
| POST | /dealership/factory-orders/{id}/cancel | Cancel a held/committed order; releases the slot and may charge a 2% fee | SalesConsultant |
| POST | /dealership/factory-orders/{id}/receive | Receive a shipped truck; creates the NEW Unit and floor-plan ADVANCE | SalesManager |
| GET | /dealership/units | List units | all roles |
| GET | /dealership/units/{id} | Get one unit | all roles |
| POST | /dealership/units/{id}/inspect | PDI / reconditioning inspection; PASS -> READY, FAIL -> RECONDITIONING | ServiceManager |
| POST | /dealership/units/{id}/sell | Retail sale of a READY unit; accrues interest then pays off floor plan; may consume a trade appraisal | SalesConsultant |
| POST | /dealership/units/{id}/wholesale | Wholesale (remarket) an aged READY unit | SalesManager |
| POST | /dealership/units/{id}/floor-plan-adjustments | Manual signed floor-plan ADJUSTMENT with OCC on the unit | Controller |
| GET | /dealership/units/{id}/floor-plan-entries | Ledger entries for a unit in chronological order | all roles |
| POST | /dealership/units/{id}/floor-plan-curtailments | Post a CURTAILMENT payment entry against a floor-planned unit | Controller |
| GET | /dealership/units/{id}/payoff-quote | Projected payoff (forward-looking variant) as of a date | all roles |
| POST | /dealership/trade-appraisals | Create an appraisal (BOOK estimate computed) | SalesConsultant |
| GET | /dealership/trade-appraisals | List appraisals | all roles |
| GET | /dealership/trade-appraisals/{id} | Get one appraisal | all roles |
| POST | /dealership/trade-appraisals/{id}/offer | SalesManager issues/re-issues an offer (MARKET ACV caps the allowance) | SalesManager |
| POST | /dealership/trade-appraisals/{id}/counter | Customer counters an offer | FleetCustomer |
| POST | /dealership/trade-appraisals/{id}/accept | Customer accepts; creates the USED unit in RECONDITIONING | FleetCustomer |
| POST | /dealership/trade-appraisals/{id}/decline | Customer declines (terminal) | FleetCustomer |
| POST | /dealership/service-bays | Create a service bay | ServiceManager |
| GET | /dealership/service-bays | List service bays | all roles |
| GET | /dealership/service-bays/{id} | Get one service bay | all roles |
| POST | /dealership/service-bays/{id}/set-status | Set bay ACTIVE or OUT_OF_SERVICE | ServiceManager |
| POST | /dealership/mobile-service-units | Create a mobile service unit (road-call resource) | ServiceManager |
| GET | /dealership/mobile-service-units | List mobile service units | all roles |
| GET | /dealership/mobile-service-units/{id} | Get one mobile service unit | all roles |
| POST | /dealership/mobile-service-units/{id}/set-status | Set mobile unit ACTIVE or OUT_OF_SERVICE | ServiceManager |
| POST | /dealership/repair-orders | Open a repair order (exactly one of unit_id / external_vin) | ServiceAdvisor |
| GET | /dealership/repair-orders | List repair orders | all roles |
| GET | /dealership/repair-orders/{id} | Get one repair order | all roles |
| POST | /dealership/repair-orders/{id}/submit-estimate | Submit estimate to customer (requires at least one line) | ServiceAdvisor |
| POST | /dealership/repair-orders/{id}/approve-estimate | Customer approves estimate (owner only) | FleetCustomer |
| POST | /dealership/repair-orders/{id}/decline-estimate | Customer declines estimate (owner only) | FleetCustomer |
| POST | /dealership/repair-orders/{id}/revise | Return a declined estimate to DRAFT for rework | ServiceAdvisor |
| POST | /dealership/repair-orders/{id}/start-work | Start work; requires APPROVED estimate and a CHECKED_IN booking | ServiceAdvisor |
| POST | /dealership/repair-orders/{id}/complete-work | Complete work; computes downtime penalty; CHECKED_IN bookings complete | ServiceAdvisor |
| POST | /dealership/repair-orders/{id}/invoice | Invoice the RO; computes totals; FLEET credit check; posts AR | ServiceManager |
| POST | /dealership/repair-orders/{id}/post-payment | Post exact customer payment | Controller |
| POST | /dealership/repair-orders/{id}/cancel | Cancel a non-invoiced RO; cancels its open bookings | ServiceAdvisor |
| POST | /dealership/repair-order-lines | Add a labor or part line to an RO | ServiceAdvisor |
| GET | /dealership/repair-order-lines | List RO lines | all roles |
| GET | /dealership/repair-order-lines/{id} | Get one RO line | all roles |
| POST | /dealership/service-bookings | Book a bay or mobile unit for an RO | ServiceAdvisor |
| GET | /dealership/service-bookings | List bookings | all roles |
| GET | /dealership/service-bookings/{id} | Get one booking | all roles |
| POST | /dealership/service-bookings/{id}/check-in | Check the vehicle into the booking | ServiceAdvisor |
| POST | /dealership/service-bookings/{id}/cancel | Cancel a booking; RO demotes when no open bookings remain | ServiceAdvisor |
| POST | /dealership/warranty-claims | Draft a warranty claim against an RO | WarrantyAdministrator |
| GET | /dealership/warranty-claims | List claims | all roles |
| GET | /dealership/warranty-claims/{id} | Get one claim | all roles |
| POST | /dealership/warranty-claims/{id}/submit | Submit claim to OEM (RO must be INVOICED) | WarrantyAdministrator |
| POST | /dealership/warranty-claims/{id}/adjudicate | OEM adjudication: APPROVE, SHORT_PAY, or DENY; cascades into RO totals and AR | OEMClaimsAdjudicator |
| POST | /dealership/warranty-claims/{id}/appeal | Appeal a DENIED or SHORT_PAID claim | WarrantyAdministrator |
| POST | /dealership/warranty-claims/{id}/close | Close a DENIED claim (terminal) | WarrantyAdministrator |
| POST | /dealership/warranty-claims/{id}/post-payment | Post an OEM payment; PAID at full coverage | Controller |
| POST | /dealership/warranty-claims/{id}/write-off | Write off residual receivable (small balance or aged claim) | Controller |
| POST | /dealership/parts | Create a catalog part | PartsCounterRep |
| GET | /dealership/parts | List parts | all roles |
| GET | /dealership/parts/{id} | Get one part | all roles |
| POST | /dealership/parts/{id}/discontinue | Discontinue a part (blocks future sales) | PartsCounterRep |
| POST | /dealership/parts-sales | Counter sale; per-line fleet-tier pricing; decrements stock | PartsCounterRep |
| GET | /dealership/parts-sales | List parts sales | all roles |
| GET | /dealership/parts-sales/{id} | Get one parts sale | all roles |
| GET | /dealership/parts-sale-lines | List parts sale lines | all roles |
| GET | /dealership/parts-sale-lines/{id} | Get one parts sale line | all roles |
| POST | /dealership/parts-sale-lines/{id}/return | Return units from a line; restocking fee after 30 days; restores stock | PartsCounterRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CUSTOMER_ACCOUNT_NOT_FOUND | 404 |
| ERR_FACTORY_BUILD_SLOT_NOT_FOUND | 404 |
| ERR_FACTORY_ORDER_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_TRADE_APPRAISAL_NOT_FOUND | 404 |
| ERR_SERVICE_BAY_NOT_FOUND | 404 |
| ERR_MOBILE_SERVICE_UNIT_NOT_FOUND | 404 |
| ERR_REPAIR_ORDER_NOT_FOUND | 404 |
| ERR_REPAIR_ORDER_LINE_NOT_FOUND | 404 |
| ERR_SERVICE_BOOKING_NOT_FOUND | 404 |
| ERR_WARRANTY_CLAIM_NOT_FOUND | 404 |
| ERR_PART_NOT_FOUND | 404 |
| ERR_PARTS_SALE_NOT_FOUND | 404 |
| ERR_PARTS_SALE_LINE_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_ORDER_STATE | 409 |
| ERR_UNIT_STATE | 409 |
| ERR_UNIT_NOT_SELLABLE | 409 |
| ERR_UNIT_NOT_WHOLESALE_ELIGIBLE | 409 |
| ERR_APPRAISAL_STATE | 409 |
| ERR_RO_STATE | 409 |
| ERR_RO_NOT_AWAITING_CUSTOMER | 409 |
| ERR_RO_NOT_APPROVED | 409 |
| ERR_BOOKING_STATE | 409 |
| ERR_BOOKING_NOT_CHECKED_IN | 409 |
| ERR_CLAIM_STATE | 409 |
| ERR_DUPLICATE_VIN | 409 |
| ERR_DUPLICATE_SKU | 409 |
| ERR_SPEC_FROZEN | 409 |
| ERR_UPFIT_INCOMPATIBLE | 422 |
| ERR_UPFIT_DEPENDENCY_MISSING | 422 |
| ERR_SERVICE_RESOURCE_SELECTION | 422 |
| ERR_BAY_OUTSIDE_OPERATING_HOURS | 422 |
| ERR_BAY_BOOKING_OVERLAP | 409 |
| ERR_MOBILE_BOOKING_OVERLAP | 409 |
| ERR_RESOURCE_OUT_OF_SERVICE | 409 |
| ERR_VEHICLE_REFERENCE_REQUIRED | 422 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_PART_DISCONTINUED | 409 |
| ERR_CLOCK_REGRESSION | 409 |
| ERR_SLOT_MONTH_CLOSED | 409 |
| ERR_SLOT_POOL_EXHAUSTED | 409 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_ACCOUNT_ON_CREDIT_HOLD | 409 |
| ERR_APPRAISAL_OFFER_EXCEEDS_ACV | 422 |
| ERR_APPROVAL_EXCEEDS_CLAIM | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_WRITEOFF_RULE_VIOLATION | 409 |
| ERR_RETURN_EXCEEDS_SOLD | 422 |
