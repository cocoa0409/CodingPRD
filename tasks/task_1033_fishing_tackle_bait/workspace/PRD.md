# Fishing, Tackle & Bait Shop API — Product Requirements Document

## 1. Introduction

This document specifies the back-office and storefront platform for a full-service fishing, tackle, and bait shop. A single independent retailer runs an unusually wide mix of operations under one roof: it sells merchandise SKUs over the counter, issues state fishing licenses, keeps live bait alive in aerated tanks, brokers charter trips with independent guides, runs weigh-in tournaments at local venues, and takes in rods and reels for service and re-spooling. Each of these lines of business has its own money, its own lifecycle, and its own compliance rules, yet they all feed a shared customer loyalty program.

The platform exists to make those lines of business consistent and auditable. Prices, deposits, seasonal surcharges, mortality-adjusted bait counts, tournament rankings, and loyalty points must all be reproducible from recorded inputs rather than recomputed by hand at the counter, and every mutation must be traceable to the staff member or customer who performed it. Because bait mortality, license validity, charter seasons, and tournament registration windows all depend on the passage of time, the system reads time exclusively from a server-controlled logical clock so that behavior is deterministic and testable rather than tied to wall-clock time.

The remainder of this document defines the global API contract (Section 2), the business logic and workflows across each line of business (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is missing or malformed, or the role is not one the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles: `Customer`, `ShopClerk`, `Guide`, `TournamentDirector`, and `ShopManager`.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`; a customer may act on and read their own bookings, tournament entries, special orders, licenses, sales, and service orders, and may browse the shared catalog.
- When `X-User-Role` is `Guide`, `X-User-ID` is the `id` of the acting `Guide`. Ownership checks on a charter booking compare the booking's `guide_id` to `X-User-ID`, and a guide may adjust their own availability and rates.
- When `X-User-Role` is `ShopClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures the acting operator — for example, as `clerk_user_id` on a `Sale` and as `issued_by_user_id` on a `FishingLicense` — but never compares it to any entity's `id`.
- When `X-User-Role` is `TournamentDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `ShopManager`, `X-User-ID` is likewise an opaque operator identifier. `ShopManager` is a hierarchical override role: in addition to catalog, tank, guide, venue, batch-delivery, license-void, and sale void/refund powers that are its alone, it may perform every operation available to a `ShopClerk`, a `Guide`, or a `TournamentDirector`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested `limit` above 100 is capped at 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` ascending unless a specific endpoint states otherwise. Every list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true when records remain beyond the current page) inside `meta`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix and serves as identity only; clients never supply it. Every resource also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version`. On creation, `version` starts at 1 and `updated_at` equals `created_at`. Each subsequent mutation of a resource increments its `version` by one and refreshes `updated_at` to the current logical-clock instant. All entities in this system — customers, products, licenses, bait tanks, guides, venues, charter bookings, tournaments, tournament entries, service orders, special orders, and sales — carry this full set of common fields.

Resources are addressed by flat, peer paths; there is no nesting of one resource's `id` inside another's URL. Where an endpoint accepts a path `id` and also references foreign keys in its body, the path resource and every referenced foreign-key `id` must exist; existence is validated left to right, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock and Time-Derived State

The system reads the current time exclusively from a server-controlled logical clock, never from wall-clock time. The clock's startup default is `2026-07-01T00:00:00Z`; before any clock-setting call the clock reads exactly this default and never falls back to real time. A `ShopManager` may advance or rewind the clock by supplying a `to_iso8601` instant. Every rule that depends on "now" — license validity, bait mortality decay, charter season selection, tournament registration windows, and age checks — reads this logical clock.

Several fields are not stored but derived from the clock at read time. A `FishingLicense` exposes a `status` computed each time it is read: `VOID` when it has been voided; otherwise `SCHEDULED` when now is before `valid_from`, `ACTIVE` when now is at or after `valid_from` and strictly before `valid_to`, and `EXPIRED` when now is at or after `valid_to`. A `BaitTank` exposes `available_count` and `status` recomputed against the clock on every read. Because these are derived, reading such a resource at different clock positions can return different `status` values without any explicit mutation.

### 2.6. Monetary and Points Precision

All monetary amounts are integer cents. Wherever a calculation multiplies by a rate, percentage, or multiplier, the result is rounded half up to a whole number of cents, and the rounding is applied once per named intermediate quantity rather than being deferred to the end — for example, a provisional charter total is rounded to whole cents before the deposit percentage is applied to it. Loyalty points are integers and are likewise rounded half up. Where a points calculation sums per-line contributions, each line's contribution is rounded to whole points before the contributions are summed, and any tier multiplier is applied to the summed base and rounded once more; per-line rounding always precedes summation. Bait counts are integers: mortality decay is floored per batch and the surviving counts are summed afterward.

### 2.7. Optimistic Concurrency Control for Bait Deliveries

Recording a new live-bait delivery into a tank is guarded by optimistic concurrency control. A delivery request must carry `expected_bait_tank_version`, which is the `version` of the target `BaitTank` that the client last observed. If that value does not equal the tank's current `version` — because another delivery has already been recorded and advanced the tank's `version` since the client last read it — the delivery is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently stocking the tank twice. A delivery against fresh, unchanged tank state succeeds, because deliveries are additive up to capacity. No other endpoint accepts or requires a version field; only bait delivery is version-guarded.

### 2.8. Request Validation Order and Error Handling

When more than one rule could reject a request, checks are evaluated in a fixed priority order, and the first failing check determines the returned error. The order is:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for this endpoint and action, else `ERR_UNAUTHORIZED` (403).
3. **Request well-formedness** — required fields present, enums and types valid, and quantities, weights, and counts positive where required, else `ERR_INVALID_REQUEST` (400).
4. **Existence** — the path resource and all referenced foreign-key ids exist, validated left to right, else `ERR_NOT_FOUND` (404).
5. **Optimistic concurrency** — for bait delivery, `expected_bait_tank_version` matches the tank's `version`, else `ERR_STALE_VERSION` (412).
6. **State** — the target resource is in a state that permits the requested transition or action, else `ERR_INVALID_STATE` (409).
7. **License compliance** — holder age and residency requirements for license issuance (below), which precede referential checks.
8. **Referential uniqueness** — duplicate-license and duplicate-entry checks (below).
9. **Temporal windows** — guide occupancy, venue occupancy, and tournament registration windows (below).
10. **Capacity and quota** — tank capacity, bait availability, merchandise stock, guide party size, tournament entry cap, and product eligibility (below).

Because this ordering is fixed, a resource that is simultaneously in the wrong state and would also violate a capacity rule surfaces the state error first. Each specific rejection carries the specific error listed with its rule in Section 3; the generic codes above apply where no more specific business rule governs.

### 2.9. The Loyalty Ledger

Every `Customer` owns an append-only `loyalty_ledger`: an ordered list of entries, each an object with `entry_id`, `delta_points`, `reason`, `ref_type`, `ref_id`, and `created_at`. Points are never edited or deleted in place; corrections and reversals are themselves new entries with negative `delta_points`. The customer's `loyalty_points_balance` is a computed field equal to the sum of all `delta_points` in the ledger, and it is never allowed to fall below zero. The customer's `loyalty_tier` — one of `BRONZE`, `SILVER`, or `GOLD` — is derived from `loyalty_points_balance` according to fixed thresholds: the tier is `BRONZE` when the balance is below 500, `SILVER` when the balance is at least 500 but below 2000, and `GOLD` when the balance is 2000 or more; the tier is recomputed whenever the balance changes. A separate computed field, `lifetime_spend_cents`, accumulates the `total_cents` of that customer's sales whose status is `COMPLETED` or `SETTLED`, plus completed charter settlements, and is reduced when a sale is refunded.

Whenever a workflow mints, adjusts, or reverses points, it appends a ledger entry whose `reason` records the cause — `SALE_COMPLETE`, `SALE_SETTLE_ADJUST`, `SALE_REFUND`, `CHARTER_COMPLETE`, `SERVICE_PICKUP`, `SPECIAL_ORDER_FULFILL`, or `TOURNAMENT_PRIZE` — and whose `ref_type` and `ref_id` point back to the originating `Sale`, `CharterBooking`, `ServiceOrder`, `SpecialOrder`, or `Tournament`. After appending, the balance and tier are recomputed together, so a single point-bearing action may carry a customer across a tier boundary in either direction.

## 3. Business Logic & Workflows

### 3.1. Customers and the Loyalty Program

A `Customer` is registered by a `ShopClerk` or `ShopManager` with a `name`, an `email`, a two-letter residency `state_code`, and a `birth_date` given as an ISO date of the form YYYY-MM-DD. At registration the loyalty state is initialized: the `loyalty_ledger` starts empty, `loyalty_points_balance` is zero, `loyalty_tier` is `BRONZE`, and `lifetime_spend_cents` is zero. The `state_code` later governs which licenses the customer may hold, and the `birth_date` drives license age checks, with age computed against the logical clock.

Customers accrue points across every line of business, as described in the workflows below. Because `loyalty_tier` is derived from `loyalty_points_balance`, a customer's tier at the moment a workflow runs affects the money and points that workflow produces — for instance, the tier discount applied when a charter is settled and the tier multiplier applied when sale points are minted both read the holder's tier at that instant. Reads of a customer return the full ledger together with the current computed balance and tier, and customer-scoped listings expose that customer's licenses, service orders, and sales.

### 3.2. Product Catalog and Special Orders

A `ShopManager` maintains the merchandise catalog. Each `Product` carries a unique `sku`, a display `name`, a `category` that is one of `ROD`, `REEL`, `TERMINAL_TACKLE`, `APPAREL`, or `DRY_BAIT`, a `unit_price_cents` shelf price of at least zero, an on-hand `stock_qty` of at least zero, an `is_active` flag defaulting to true, and an `is_special_order_eligible` flag defaulting to false. The `sku` must be unique across all products. Inactive products cannot be added to sales or special-ordered. A manager may later adjust a product's `unit_price_cents`, `stock_qty`, or `is_active` flag; each such update refreshes `updated_at` and increments `version`.

A **special order** lets a customer request merchandise the shop does not stock. A `Customer`, `ShopClerk`, or `ShopManager` opens a `SpecialOrder` referencing a `customer_id`, a `product_id`, and a `quantity` of at least one. The backing product must be active and flagged special-order eligible; a request against an inactive product is rejected with `ERR_PRODUCT_INACTIVE`, and one against a product that is not eligible is rejected with `ERR_NOT_SPECIAL_ORDER_ELIGIBLE`. On creation the order snapshots the product's price into `unit_price_cents`, computes a required `deposit_cents` equal to the unit price times the quantity times one half, rounded half up to whole cents, and enters `REQUESTED`.

A clerk advances the order through its lifecycle. From `REQUESTED` the order moves to `ORDERED` once placed with the supplier, but only if the backing product is still active — otherwise the transition is rejected with `ERR_PRODUCT_INACTIVE`. From `ORDERED` it moves to `ARRIVED` when the goods arrive, and from `ARRIVED` to `FULFILLED` when the customer takes delivery. Fulfillment mints loyalty points: a ledger entry is appended to the customer with `delta_points` equal to the unit price times the quantity divided by 100 and rounded half up, a `reason` of `SPECIAL_ORDER_FULFILL`, and a reference back to the order, after which the customer's balance and tier are recomputed. A special order may be cancelled from either `REQUESTED` or `ORDERED`, moving it to `CANCELLED`. Cancellation computes a `refund_cents`: cancelling from `REQUESTED` refunds the full deposit, while cancelling from `ORDERED` deducts a restock fee equal to the deposit times one fifth, rounded half up, and refunds the deposit minus that fee. The `refund_cents` field is null until the order is cancelled.

### 3.3. Fishing License Issuance and Voiding

A `ShopClerk` or `ShopManager` issues a `FishingLicense` for a customer by supplying `customer_id`, `license_type`, an issuing `state_code`, and a `valid_from` instant. The `license_type` is one of `RESIDENT_ANNUAL`, `NONRESIDENT_ANNUAL`, `ONE_DAY`, or `SENIOR`. On issuance the system computes `valid_to` as `valid_from` plus the license duration for the type — 365 days for `RESIDENT_ANNUAL`, `NONRESIDENT_ANNUAL`, and `SENIOR`, and 1 day for `ONE_DAY` — sets `price_cents` to the fixed price for the license type — 5200 for `RESIDENT_ANNUAL`, 12000 for `NONRESIDENT_ANNUAL`, 1500 for `ONE_DAY`, and 2600 for `SENIOR` — regardless of any client-supplied value, derives `status` from the clock, records the issuing operator as `issued_by_user_id`, and leaves `is_voided` false.

Two compliance checks guard issuance and are evaluated before the referential uniqueness check. First, the holder's age in whole years, computed from the holder's `birth_date` against the logical clock, must be at least the minimum age for the requested `license_type` — 16 for `RESIDENT_ANNUAL`, `NONRESIDENT_ANNUAL`, and `ONE_DAY`, and 65 for `SENIOR`; if it does not, issuance is rejected with `ERR_LICENSE_AGE_RESTRICTION` (HTTP 422). Second, for a `RESIDENT_ANNUAL` or `SENIOR` license, the issuing `state_code` must equal the holder `Customer`'s `state_code`; a mismatch is rejected with `ERR_LICENSE_STATE_MISMATCH` (HTTP 422). Only after both compliance checks pass does the uniqueness check apply: a customer may not hold two `ACTIVE` licenses of the same `license_type`, and an attempt to issue a duplicate is rejected with `ERR_DUPLICATE_LICENSE` (HTTP 409).

A `ShopManager` may void a license from any of the `SCHEDULED`, `ACTIVE`, or `EXPIRED` states. Voiding sets `is_voided` to true and forces `status` to `VOID`, which is the only explicit terminal state; the derived-status rule no longer applies once a license is voided. Attempting to void a license that is already `VOID` is rejected with `ERR_INVALID_STATE` (HTTP 409). Because the duplicate-license rule keys on `ACTIVE` licenses of a given type, voiding an active license frees that customer-and-type slot so a replacement may be issued.

### 3.4. Live-Bait Tanks: Delivery, Decay, Dispensing, and Returns

A `ShopManager` creates a `BaitTank` with a `name`, a `species` of `MINNOW`, `SHINER`, `NIGHTCRAWLER`, or `SHRIMP`, a positive `capacity_units`, and a `mortality_rate_bps_per_day` expressed in basis points per day (for example, 200 basis points means two percent of a batch dies per day). A new tank starts with an empty `batches` list, a `sold_count` of zero, an `available_count` of zero, and `status` of `EMPTY`.

Bait arrives in **batches**. A manager delivers a batch by supplying an `initial_count` and the OCC `expected_bait_tank_version` described in Section 2.7, and may optionally supply a `delivered_at` instant that defaults to the current clock. A successful delivery appends a batch object — carrying `batch_id`, `initial_count`, `delivered_at`, and `created_at` — recomputes the tank's availability and status, and increments the tank's `version`. A delivery is rejected with `ERR_TANK_CAPACITY_EXCEEDED` (HTTP 409) when it would push the tank's current `available_count` plus the delivered `initial_count` above `capacity_units`.

The tank's `available_count` is not stored but computed from mortality decay against the clock. For each batch, its age in whole days is the elapsed time from `delivered_at` to now divided by 86,400 seconds and floored to a whole number of days. The number of dead units in that batch is the batch's `initial_count` multiplied by the daily mortality fraction — the `mortality_rate_bps_per_day` divided by 10,000 — multiplied by the age in days, floored to a whole number; a batch's survivors are its `initial_count` minus its dead units, never below zero. The survivors of all batches are summed, and `available_count` is that sum minus `sold_count`, never below zero. The `low_stock_threshold` is `capacity_units` multiplied by one tenth, rounded up to a whole number. The tank's `status` is `EMPTY` when `available_count` is zero, `LOW` when it is greater than zero but below `low_stock_threshold`, and `HEALTHY` otherwise.

A `ShopClerk` or `ShopManager` dispenses bait by supplying a `qty`, which must be positive and no greater than the current `available_count`; a request exceeding availability is rejected with `ERR_INSUFFICIENT_BAIT` (HTTP 409). Dispensing adds `qty` to `sold_count` and recomputes availability and status. A previously dispensed quantity may be returned by supplying a `qty`, which subtracts from `sold_count`, clamped so `sold_count` never drops below zero, and again recomputes availability and status; returns are the compensating action for a dispense.

### 3.5. Charter Bookings: Quoting, Confirmation, Rescheduling, and Settlement

Charter trips link a customer, an independent guide, and a fishing venue. A `Guide` is created by a `ShopManager` with a `name`, a `guide_license_no`, a `half_day_rate_cents` and `full_day_rate_cents` base rate, a `per_extra_angler_cents` surcharge, a `max_party_size`, and an optional `fuel_surcharge_cents` (defaulting to zero) added only at settlement. A guide's `status` is `AVAILABLE` or `SUSPENDED`; a manager toggles it, and a guide may adjust their own status and rates. Suspending a guide leaves existing confirmed bookings intact but blocks new confirmations while suspended. A `Venue` — created by a manager with a `name`, a `water_type` of `LAKE`, `RIVER`, `SALTWATER`, or `POND`, and an optional informational `daily_permit_cents` — is where a trip launches.

A `Customer`, `ShopClerk`, or `ShopManager` requests a booking with `customer_id`, `guide_id`, `venue_id`, a `trip_type` of `HALF_DAY` or `FULL_DAY`, a `party_size` of at least one, a `start_at` and `end_at`, and an optional `add_equipment_rental` flag defaulting to false. A new booking enters `REQUESTED` with its computed money fields — `season_at_quote`, `provisional_total_cents`, `deposit_cents`, `final_total_cents`, and `points_awarded` — all null.

Each lifecycle step is requested by naming an `action` on the booking, and the same convention applies to service orders, special orders, tournaments, and sales. The booking then moves through a cyclic lifecycle:

- **Quoting** (`REQUESTED → QUOTED`), performed by a `ShopClerk`, first checks that `party_size` does not exceed the guide's `max_party_size`; if it does, the quote is rejected with `ERR_PARTY_TOO_LARGE` (HTTP 409). It records `season_at_quote` as `PEAK` when the logical-clock month is May, June, July, or August, and `OFF` otherwise, then computes the provisional estimate and the deposit. The **components** of a charter are its base plus an extra-angler charge plus optional equipment. The base is the guide's `full_day_rate_cents` for a `FULL_DAY` trip or `half_day_rate_cents` for a `HALF_DAY` trip. The extra-angler charge is the number of anglers above the two included anglers — never below zero — multiplied by `per_extra_angler_cents`. The equipment charge, applied only when `add_equipment_rental` is true, is 2,500 cents per angler multiplied by `party_size`. The provisional seasonal multiplier is 1.20 during peak months and 1.00 otherwise; `provisional_total_cents` is the components multiplied by that multiplier and rounded half up. The `deposit_cents` is `provisional_total_cents` multiplied by one quarter and rounded half up.
- **Confirmation** (`QUOTED → CONFIRMED`), performed by the `Customer`, requires that the guide is `AVAILABLE`; a confirmation against a suspended guide is rejected with `ERR_GUIDE_SUSPENDED` (HTTP 409). It also requires that the guide has no other `CONFIRMED` or `COMPLETED` booking whose time window, taken as the half-open interval from `start_at` to `end_at` and padded on both sides by 60 minutes, overlaps this booking's padded window; an overlap is rejected with `ERR_GUIDE_UNAVAILABLE` (HTTP 409).
- **Rescheduling** (`QUOTED → REQUESTED` or `CONFIRMED → REQUESTED`), performed by the `Customer`, applies a new `start_at` and `end_at`, and optionally a new `trip_type` or `party_size`, then clears `provisional_total_cents`, `deposit_cents`, and `season_at_quote` so the booking must be re-quoted before it can be confirmed again.
- **Completion** (`CONFIRMED → COMPLETED`), performed by the `Guide` who owns the booking, computes the final settlement. The final seasonal multiplier is taken from the month of `start_at` rather than the clock: 1.20 when `start_at` falls in May, June, July, or August, and 1.00 otherwise. The final subtotal is the same components multiplied by that final multiplier and rounded half up. A tier discount is then applied: the final subtotal multiplied by the holder's tier discount rate — zero for `BRONZE`, one twentieth for `SILVER`, and one tenth for `GOLD` — rounded half up. The `final_total_cents` is the final subtotal minus that tier discount plus the guide's `fuel_surcharge_cents`. Completion mints loyalty: `points_awarded` is `final_total_cents` divided by 100 multiplied by the holder's tier multiplier (1.00 for `BRONZE`, 1.10 for `SILVER`, 1.25 for `GOLD`), rounded half up. A ledger entry with that `delta_points`, a `reason` of `CHARTER_COMPLETE`, and a reference back to the booking is appended to the holder, the holder's `loyalty_points_balance` and `loyalty_tier` are recomputed, and `final_total_cents` is added to the holder's `lifetime_spend_cents`.
- **Cancellation** (`REQUESTED → CANCELLED`, `QUOTED → CANCELLED`, or `CONFIRMED → CANCELLED`), performed by the `Customer`, records the optional `cancel_reason`, mints no loyalty, and releases the guide's time slot. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Point-of-Sale Sales: Lines, Completion, Settlement, and Refund

A `ShopClerk` or `ShopManager` opens a `Sale` for a `customer_id`; the sale enters `OPEN` with an empty `lines` list, and the opening operator is recorded as `clerk_user_id`. A clerk adds line items, each supplying a `product_id` and a `qty`; adding a line snapshots the product's current price and appends a line object carrying `line_id`, `product_id`, `qty`, the snapshotted `unit_price_cents`, a `line_total_cents` equal to that unit price times `qty`, and a `refunded` flag initially false. Adding a line recomputes the sale totals: `subtotal_cents` is the sum of `line_total_cents` over non-refunded lines, `tax_cents` is the subtotal multiplied by 800 basis points — that is, divided by 10,000 — and rounded half up, and `total_cents` is the subtotal plus the tax.

Completing a sale (`OPEN → COMPLETED`), performed by a clerk, requires at least one line, else `ERR_EMPTY_SALE` (HTTP 409), and requires that each line's product has `stock_qty` at least the line's `qty`, else `ERR_INSUFFICIENT_STOCK` (HTTP 409). On completion each line's product `stock_qty` is decremented by its `qty`, the totals are recomputed, and provisional points are minted into `points_provisional`. Provisional points are computed by rounding each non-refunded line's `line_total_cents` divided by 100 to whole points, summing those per-line points into a base, then multiplying the base by the holder's tier multiplier and rounding half up. A ledger entry with `delta_points` equal to `points_provisional`, a `reason` of `SALE_COMPLETE`, and a reference to the sale is appended, the holder's balance and tier are recomputed, and `total_cents` is added to the holder's `lifetime_spend_cents`.

Settling a sale (`COMPLETED → SETTLED`), performed by a clerk, reconciles points into `points_final`. The base points are recomputed over the lines still non-refunded at settle using the same per-line-round-then-sum rule, multiplied by the holder's tier multiplier and rounded half up. When the logical-clock month at settle is a peak month (May, June, July, or August), a seasonal bonus is added: that settled base multiplied by the tier multiplier multiplied by one tenth, rounded half up; otherwise the bonus is zero. The `points_final` is the tier-adjusted settled base plus the seasonal bonus. A ledger entry is appended for the difference between `points_final` and `points_provisional`, with a `reason` of `SALE_SETTLE_ADJUST`, and the balance and tier are recomputed.

Refunding a sale (`COMPLETED → REFUNDED`) is a `ShopManager` power. It restocks each line by incrementing its product's `stock_qty` by the line's `qty` and marking the lines `refunded`, appends a compensating ledger entry with `delta_points` equal to the negative of `points_provisional` and a `reason` of `SALE_REFUND` so the sale's net point contribution returns to zero, recomputes the balance and tier, and subtracts `total_cents` from the holder's `lifetime_spend_cents`. Voiding a sale (`OPEN → VOIDED`), also a manager power, discards an open sale and writes no ledger entries because nothing was minted. `SETTLED`, `REFUNDED`, and `VOIDED` are terminal.

### 3.7. Tournaments, Entries, and Weigh-Ins

A `TournamentDirector` or `ShopManager` creates a `Tournament` at a venue, supplying `venue_id`, `name`, `entry_fee_cents`, `registration_open_at`, `registration_close_at`, `start_at`, `end_at`, `max_entries` (which must be positive), `prize_points`, and an optional `bag_limit` defaulting to 5. The tournament occupies its venue for the half-open interval from `start_at` to `end_at`; creation is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 409) when that window overlaps another non-cancelled tournament at the same venue, though windows that merely abut (one ending exactly when the next begins) are allowed. A new tournament enters `SCHEDULED`, with `entry_count` at zero and `winner_entry_id` null.

The director drives the lifecycle. `SCHEDULED → REGISTRATION_OPEN` opens registration. `REGISTRATION_OPEN → IN_PROGRESS` starts the event, closing registration and allowing weigh-ins. `IN_PROGRESS → FINALIZED` scores and settles the event, as described below. The tournament may be cancelled (`SCHEDULED → CANCELLED`, `REGISTRATION_OPEN → CANCELLED`, or `IN_PROGRESS → CANCELLED`), which mints no prize and freezes registrations. `FINALIZED` and `CANCELLED` are terminal.

A `Customer`, `ShopClerk`, or `ShopManager` registers a competitor into a tournament by supplying a `customer_id`. Registration requires that the tournament is `REGISTRATION_OPEN` and that the logical clock is strictly before `registration_close_at` (the close instant is exclusive); a registration when the tournament is not open or when now is at or after the close instant is rejected with `ERR_REGISTRATION_CLOSED` (HTTP 409). A customer may register only once per tournament; a second attempt is rejected with `ERR_DUPLICATE_ENTRY` (HTTP 409). A tournament that already holds `max_entries` registrations rejects further entries with `ERR_MAX_ENTRIES_REACHED` (HTTP 409). A successful registration creates a `TournamentEntry` in `REGISTERED`, records the `tournament_id` of the event and the `customer_id` of the competitor, snapshots the tournament's `entry_fee_cents` into the entry's `entry_fee_paid_cents`, and increments the tournament's `entry_count`. Entries may be listed filtered by `tournament_id` or `customer_id`.

A director records weigh-ins against an entry, each supplying a `species` and a positive `weight_grams`. A weigh-in requires the parent tournament to be `IN_PROGRESS`, else `ERR_TOURNAMENT_NOT_IN_PROGRESS` (HTTP 409); a non-positive `weight_grams` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Each weigh-in appends an object carrying `weigh_in_id`, `species`, `weight_grams`, an `accepted` flag, and `created_at` to the entry's `weigh_ins`. The first accepted weigh-in moves the entry from `REGISTERED` to `WEIGHED`; each subsequent accepted weigh-in leaves it `WEIGHED`. After each weigh-in the entry's `bag_weight_grams` and `big_fish_grams` are recomputed: `bag_weight_grams` is the sum of the heaviest accepted weigh-ins up to the tournament's `bag_limit` (the top-N by `weight_grams`), and `big_fish_grams` is the single heaviest accepted weigh-in, or zero when there are none.

Finalizing the tournament ranks its entries and settles the prize. Only entries with a `bag_weight_grams` greater than zero are ranked; they are ordered primarily by `bag_weight_grams` descending. Ties are broken first by the `created_at` of the last weigh-in that entered the entry's counted bag, earliest first, and then by the entry's own `created_at`, earliest first; ranking never depends on entry `id`. Each ranked entry receives a 1-based `placement`, its status moves from `WEIGHED` to `PLACED`, and the entry ranked first becomes the tournament's `winner_entry_id`. A ledger entry with `delta_points` equal to the tournament's `prize_points`, a `reason` of `TOURNAMENT_PRIZE`, and a reference to the tournament is appended to the winning entry's customer, and that customer's balance and tier are recomputed. An entry whose `bag_weight_grams` is zero receives no `placement`.

### 3.8. Rod & Reel Service Orders

A `ShopClerk` or `ShopManager` takes in a rod or reel for service by opening a `ServiceOrder` with a `customer_id`, an `item_description`, a `service_type` of `SPOOLING`, `REEL_SERVICE`, `ROD_REPAIR`, or `GUIDE_LINE`, a `quoted_cents` estimate, and, for spooling work, an optional `line_length_yards` that must be positive when supplied. The order enters `RECEIVED`.

A clerk drives the service through a cyclic lifecycle. `RECEIVED → IN_PROGRESS` begins the work. While in progress, the order may move to `AWAITING_PARTS` when parts must be sourced and back from `AWAITING_PARTS → IN_PROGRESS` when work resumes, forming a revision loop that may repeat. `IN_PROGRESS → READY` marks the item ready for pickup. `READY → PICKED_UP` captures the charge: `final_cents` is set equal to `quoted_cents`, a ledger entry with `delta_points` equal to `final_cents` divided by 100 and rounded half up, a `reason` of `SERVICE_PICKUP`, and a reference to the order is appended to the customer, and the customer's balance and tier are recomputed. The order may be cancelled from `RECEIVED`, `IN_PROGRESS`, or `AWAITING_PARTS`, moving it to `CANCELLED`. `PICKED_UP` and `CANCELLED` are terminal, and `final_cents` remains null until pickup.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creating a new resource returns HTTP 201; retrievals, list operations, and in-place modifications (including lifecycle transitions and sub-resource actions) return HTTP 200. Request bodies, computed responses, and side effects are described in the Section 3 workflows and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ShopManager |
| POST | `/customers` | Register a customer | ShopClerk, ShopManager |
| GET | `/customers/{id}` | Get a customer | Customer, ShopClerk, Guide, TournamentDirector, ShopManager |
| GET | `/customers` | List customers | ShopClerk, ShopManager |
| GET | `/customers/{id}/licenses` | List a customer's licenses | Customer, ShopClerk, ShopManager |
| GET | `/customers/{id}/service-orders` | List a customer's service orders | Customer, ShopClerk, ShopManager |
| GET | `/customers/{id}/sales` | List a customer's sales | Customer, ShopClerk, ShopManager |
| POST | `/products` | Create a product SKU | ShopManager |
| GET | `/products/{id}` | Get a product | Customer, ShopClerk, Guide, TournamentDirector, ShopManager |
| GET | `/products` | List products | Customer, ShopClerk, Guide, TournamentDirector, ShopManager |
| PATCH | `/products/{id}` | Update product price/stock/active flag | ShopManager |
| POST | `/licenses` | Issue a fishing license | ShopClerk, ShopManager |
| GET | `/licenses/{id}` | Get a license | Customer, ShopClerk, ShopManager |
| POST | `/licenses/{id}/void` | Void a license | ShopManager |
| POST | `/bait-tanks` | Create a live-bait tank | ShopManager |
| GET | `/bait-tanks/{id}` | Get a tank | Customer, ShopClerk, ShopManager |
| GET | `/bait-tanks` | List tanks | Customer, ShopClerk, ShopManager |
| POST | `/bait-tanks/{id}/batches` | Deliver a live-bait batch (OCC-guarded) | ShopManager |
| POST | `/bait-tanks/{id}/dispense` | Dispense live bait | ShopClerk, ShopManager |
| POST | `/bait-tanks/{id}/returns` | Return dispensed bait | ShopClerk, ShopManager |
| POST | `/guides` | Create a charter guide | ShopManager |
| GET | `/guides/{id}` | Get a guide | Customer, ShopClerk, Guide, ShopManager |
| GET | `/guides` | List guides | Customer, ShopClerk, Guide, ShopManager |
| PATCH | `/guides/{id}` | Update guide status and/or rates | Guide, ShopManager |
| POST | `/venues` | Create a fishing venue | ShopManager |
| GET | `/venues/{id}` | Get a venue | Customer, ShopClerk, TournamentDirector, ShopManager |
| GET | `/venues` | List venues | Customer, ShopClerk, TournamentDirector, ShopManager |
| POST | `/charter-bookings` | Request a charter booking | Customer, ShopClerk, ShopManager |
| GET | `/charter-bookings/{id}` | Get a charter booking | Customer, ShopClerk, Guide, ShopManager |
| GET | `/charter-bookings` | List charter bookings | Customer, ShopClerk, Guide, ShopManager |
| POST | `/charter-bookings/{id}/transition` | Drive the booking lifecycle | Customer, ShopClerk, Guide, ShopManager |
| POST | `/tournaments` | Create a tournament | TournamentDirector, ShopManager |
| GET | `/tournaments/{id}` | Get a tournament | Customer, ShopClerk, TournamentDirector, ShopManager |
| GET | `/tournaments` | List tournaments | Customer, ShopClerk, TournamentDirector, ShopManager |
| POST | `/tournaments/{id}/transition` | Drive the tournament lifecycle | TournamentDirector, ShopManager |
| POST | `/tournaments/{id}/entries` | Register a customer into a tournament | Customer, ShopClerk, ShopManager |
| GET | `/tournament-entries/{id}` | Get a tournament entry | Customer, ShopClerk, TournamentDirector, ShopManager |
| GET | `/tournament-entries` | List tournament entries | Customer, ShopClerk, TournamentDirector, ShopManager |
| POST | `/tournament-entries/{id}/weigh-ins` | Record a weigh-in against an entry | TournamentDirector, ShopManager |
| POST | `/service-orders` | Intake a rod/reel service order | ShopClerk, ShopManager |
| GET | `/service-orders/{id}` | Get a service order | Customer, ShopClerk, ShopManager |
| POST | `/service-orders/{id}/transition` | Drive the service lifecycle | ShopClerk, ShopManager |
| POST | `/special-orders` | Request a special order | Customer, ShopClerk, ShopManager |
| GET | `/special-orders/{id}` | Get a special order | Customer, ShopClerk, ShopManager |
| GET | `/special-orders` | List special orders | Customer, ShopClerk, ShopManager |
| POST | `/special-orders/{id}/transition` | Drive the special-order lifecycle | ShopClerk, ShopManager |
| POST | `/sales` | Open a POS sale | ShopClerk, ShopManager |
| GET | `/sales/{id}` | Get a sale | Customer, ShopClerk, ShopManager |
| POST | `/sales/{id}/lines` | Add a line item to an open sale | ShopClerk, ShopManager |
| POST | `/sales/{id}/transition` | Drive the sale lifecycle | ShopClerk, ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_LICENSE_AGE_RESTRICTION | 422 |
| ERR_LICENSE_STATE_MISMATCH | 422 |
| ERR_DUPLICATE_LICENSE | 409 |
| ERR_DUPLICATE_ENTRY | 409 |
| ERR_GUIDE_SUSPENDED | 409 |
| ERR_GUIDE_UNAVAILABLE | 409 |
| ERR_VENUE_DOUBLE_BOOKED | 409 |
| ERR_REGISTRATION_CLOSED | 409 |
| ERR_TOURNAMENT_NOT_IN_PROGRESS | 409 |
| ERR_TANK_CAPACITY_EXCEEDED | 409 |
| ERR_INSUFFICIENT_BAIT | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_PARTY_TOO_LARGE | 409 |
| ERR_MAX_ENTRIES_REACHED | 409 |
| ERR_PRODUCT_INACTIVE | 409 |
| ERR_NOT_SPECIAL_ORDER_ELIGIBLE | 409 |
| ERR_EMPTY_SALE | 409 |
