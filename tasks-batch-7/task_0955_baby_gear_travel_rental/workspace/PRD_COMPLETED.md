# Baby Gear Travel Rental API — Product Requirements Document

## 1. Introduction

Families traveling with infants face an awkward choice: haul a crib, a stroller, and a car seat through airports, or arrive without them. This service removes that choice by operating a rental fleet of baby gear — cribs, strollers, and car seats — delivered to a traveler's hotel or home address, set up on arrival, collected at departure, cleaned between rentals, and insured against damage. The system described here is the back-end API that runs that operation end to end: a catalog of rentable products backed by individually tracked physical units, a reservation lifecycle from provisional quote through confirmed booking to settlement, hotel and resort partnerships with commission accounting, route-planned delivery and pickup, cleaning and recall safety workflows, and a deposit ledger that captures damage, late, and cancellation charges before releasing the remainder.

The document is written for the engineers implementing the API. It defines the global contracts every endpoint shares (authentication, response envelopes, pagination, monetary precision, optimistic concurrency), then walks the business workflows in the order a rental actually lives them — quoting, confirmation, delivery, use, return, cleaning, and settlement — and finishes with the endpoint catalogue and the error-code catalogue. Where a rule has a boundary (a grace period, a tier threshold, a capacity limit), the boundary is stated exactly, including which side of the line is inclusive.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the role under which the principal acts. A request missing either header, or presenting a role string that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `Anonymous` — an unauthenticated visitor. `Anonymous` may do exactly one thing: register as a customer. The `X-User-ID` header on an `Anonymous` request is an opaque identifier not tied to any persisted entity.
- `Customer` — the traveler renting gear. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a Customer compare the resource's `customer_id` field to `X-User-ID`. A Customer may only access reservations, reservation lines, extension requests, deposit ledger entries, and damage claims whose reservation's `customer_id` equals their own `X-User-ID`.
- `HotelPartner` — a hotel or resort partner with a read-only view of its own guests' bookings. When `X-User-Role` is `HotelPartner`, `X-User-ID` is the `id` of the acting HotelPartner record; a HotelPartner may only read reservations whose `hotel_partner_id` equals `X-User-ID`.
- `Inspector` — the cleaning and damage inspector. When `X-User-Role` is `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `inspector_user_id` on a CleaningTicket or `filed_by_user_id` on a DamageClaim — but does not compare it to any entity's `id`. An Inspector can file damage claims and resolve cleaning tickets but can never approve or deny a claim.
- `OperationsAdmin` — the platform operator, holding a hierarchical superset of operational powers: catalog, unit, partner, plan, route, and recall administration, settlement, extension and claim adjudication, customer suspension, and the test-driving clock. `X-User-ID` for an `OperationsAdmin` is likewise opaque — it may be recorded (for example, as `decided_by_user_id` on an ExtensionRequest or `reviewed_by_user_id` on a DamageClaim) without being matched to any entity. Segregation of duties still applies to an OperationsAdmin who filed a damage claim: that same id cannot later approve or deny it.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 band, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400). List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `has_more` is true exactly when `offset` plus the number of records returned is less than `total_count`. List endpoints also accept optional equality-filter query parameters on the resource's own scalar fields — `status`, `category`, `zone_code`, `route_date`, `pricing_model`, and foreign-key ids such as `customer_id`, `hotel_partner_id`, `insurance_plan_id`, `reservation_id`, `catalog_item_id`, `assigned_unit_id`, and `route_id` — each supplied parameter restricting the result to exact matches. Unless a more specific ordering applies to an individual record type (stop sequencing on a route, for example, is ordering by time window), every list endpoint returns records sorted by `created_at` ascending.

### 2.4. Resource Identity and Common Properties

Every persisted resource has an `id` that is a server-minted UUID with no type prefix. With one exception, every resource also carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer that starts at 1 on creation and increments by exactly one on every mutation of that record — including mutations driven by a cascade from another entity. The exception is the DepositTransaction ledger entry: it is an append-only record carrying only `id` and `created_at`; it has no `updated_at` and no `version`, because a ledger entry, once written, is never modified.

### 2.5. The Logical Clock and Date Semantics

The server maintains a logical clock rather than reading wall-clock time. At server startup the clock reads exactly 2026-05-01T00:00:00Z, and before any explicit advance it continues to read that default — it never silently falls back to real time. An OperationsAdmin-only test-driving capability advances the clock by submitting a `to_iso8601` instant; the response reports the new `current_utc`. Anywhere this document says "the current logical clock" — stamping `returned_at`, `completed_at`, or `activated_at` — it means this clock. Instants stamped from this clock — `returned_at`, `completed_at`, `activated_at`, the unit's `blocked_until` derived from `returned_at`, and the `current_utc` reported when the clock is advanced — are rendered exactly as the clock reads: ISO 8601 UTC, carrying fractional digits only when the stamped instant itself carries them, so the default clock reading renders as `2026-05-01T00:00:00Z`. The three-fractional-digit requirement of §2.2 and §2.4 covers `api_request_timestamp`, `created_at`, and `updated_at`; it does not apply to these clock-stamped fields.

Rental dates are calendar dates in YYYY-MM-DD form. A reservation's `start_date` is inclusive and its `end_date` is exclusive: the rental is due back at the `end_date` midnight UTC instant, and every committed booking interval used for availability math begins at `start_date` at 00:00:00Z and ends at `end_date` at 00:00:00Z, then extends further by the cleaning-turnaround buffer described in §3.4. Intervals throughout the system are half-open: a window that ends exactly where another begins does not overlap it.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents — fields such as `daily_rate_cents`, `deposit_amount_cents`, `quoted_total_cents`, and every computed charge are whole numbers of cents. Wherever a fractional factor is applied to a monetary amount (the 85% and 70% long-rental tiers, the 120% and 150% extension surcharges, the 15% hourly late rate, the 10% cancellation fee, a commission percentage, a damage severity or condition factor, an insurance percentage), the result is rounded half-up to the nearest integer cent at the point the factor is applied. The rounding order matters and is pinned per calculation in §3: some rules round each line or each unit first and then sum, and summing first and rounding once is a different, incorrect answer. Hour counts derived from late minutes are rounded up to the next whole hour. Weights are compared exactly at one decimal place of kilograms.

### 2.7. Optimistic Concurrency Control

Two write operations on a Reservation are guarded by optimistic concurrency control: amending a quoted reservation's dates, and creating an extension request against a reservation. Both requests must carry `expected_reservation_version`, a non-optional field holding the `version` of the reservation as the client last observed it. If the reservation's current `version` has advanced since that observation — because a prior amend succeeded, an extension approval bumped it, or any other write landed in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The stale-version check runs after the state-machine preconditions have passed: a request that fails both a state precondition and the version check surfaces the state error first. No other endpoint takes a version field.

### 2.8. Validation Order and Nested Resource Resolution

When several checks could reject the same request, they are evaluated in a fixed order, and the first failing check determines the response. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the five declared roles, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization and ownership** — the role must be permitted for the endpoint, and entity-backed ownership checks (Customer to `customer_id`, HotelPartner to `hotel_partner_id`) must pass, else `ERR_FORBIDDEN` (403).
3. **Existence** — every identifier the request references must exist, validated left-to-right: path identifiers first, in the order they appear in the URL, then foreign keys in the request body. A missing reference yields the specific not-found error for that entity: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, or `ERR_TICKET_NOT_FOUND` (all 404). For a nested URL such as a stop being added under a route, the route id is validated before the body references.
4. **Request shape** — required fields present, types valid, enum members from the declared sets, and the uniqueness rules on customer `email`, unit `serial_number`, and plan `code`, else `ERR_INVALID_REQUEST` (400).
5. **Date and window sanity** — `end_date` strictly after `start_date` on reservation creation, an amended `end_date` strictly after the amended `start_date`, a requested extension end strictly after the reservation's current `end_date`, and a stop's time window falling within the route's `route_date` with a start strictly before its end, else `ERR_INVALID_DATE_RANGE` (422).
6. **State-machine preconditions** — the transition must be legal from the current state, terminal states are locked, a stop can only complete on a `DISPATCHED` route, settlement requires a `RETURNED` reservation, claim approval requires a `RETURNED` line and reservation, a route can only complete once every stop is terminal, a recall can only close when no unit of the recalled item remains `QUARANTINED`, and a cleaning ticket can only be opened for a unit that is `AWAITING_CLEANING` or `QUARANTINED` with no other `OPEN` ticket — else `ERR_INVALID_STATE` (409).
7. **Stale version** — the OCC check of §2.7, else `ERR_STALE_VERSION` (412).
8. **Recall safety** — confirmation and reallocation are refused when the catalog item sits under an `ACTIVE` `MANDATORY` recall (`ERR_RECALL_BLOCKED`, 409), and a quarantined unit may never be allocated (`ERR_UNIT_QUARANTINED`, 409).
9. **Temporal overlap** — unit booking windows, extension windows, and stop windows, yielding `ERR_UNIT_UNAVAILABLE`, `ERR_EXTENSION_WINDOW_CONFLICT`, or `ERR_STOP_WINDOW_CONFLICT` (all 409) as described in §3.
10. **Structural constraints** — zone matching (`ERR_ZONE_MISMATCH`, 422), partner standing (`ERR_PARTNER_SUSPENDED`, 409), customer standing at confirmation (`ERR_CUSTOMER_SUSPENDED`, 403), catalog listing state (`ERR_CATALOG_ITEM_DELISTED`, 409), route aggregate capacity (`ERR_ROUTE_CAPACITY_EXCEEDED`, 422), duplicate stops (`ERR_DUPLICATE_STOP`, 409), deep-clean due (`ERR_DEEP_CLEAN_REQUIRED`, 409), and unit eligibility (`ERR_NO_ELIGIBLE_UNIT`, 409).
11. **Segregation of duties** — claim approval and denial require a reviewer different from the filer, else `ERR_SEGREGATION_OF_DUTIES` (403).
12. **Fiscal sanity** — plan and partner rate bounds, else `ERR_INVALID_PLAN_RATE` (422) or `ERR_INVALID_REQUEST` as specified in §3.1 and §3.2.

### 2.9. The Deposit Ledger

Every movement against a reservation's deposit hold is recorded as an immutable DepositTransaction entry with a `txn_type` of `HOLD`, `CAPTURE`, or `RELEASE`, a non-negative `amount_cents` (a capture for an obligation that meets an already-exhausted hold is still appended, recording a zero amount), a `reason` drawn from `HOLD_AT_CONFIRM`, `DAMAGE_CLAIM`, `LATE_FEE`, `CANCELLATION_FEE`, or `RELEASE_REMAINDER`, and a `balance_after_cents` giving the outstanding held balance immediately after the entry is appended — a hold adds to the balance, a capture or release subtracts. The conserved quantity across a reservation's ledger is that the original hold equals the total captured plus the total released; the counters `deposit_captured_cents` and `deposit_released_cents` on the reservation mirror the ledger. Obligations that exceed the remaining hold are absorbed silently — no ledger entry ever takes the balance negative.

## 3. Business Logic & Workflows

### 3.1. Stocking the Fleet: Catalog, Units, and Insurance

An OperationsAdmin builds the rentable fleet in two layers. The catalog layer describes products: each CatalogItem is created with a `name` (for example, "Deluxe Crib"), a `category` of `CRIB`, `STROLLER`, or `CARSEAT`, a `daily_rate_cents` and a `deposit_amount_cents` that must both be greater than zero, a `weight_kg` greater than zero that consumes vehicle capacity on delivery routes, a `cleaning_turnaround_hours` of zero or more — the post-return buffer during which the unit is not bookable — and a `deep_clean_every_cycles` of at least one, the cadence after which standard cleaning passes must give way to a deep clean. New catalog items are born with `status` `LISTED`; an administrator may later update rates and specifications, set the item to `DELISTED`, or re-list it to `LISTED` through a partial update — the two status values may be set in either direction — which bumps the item's `version` by one. A `DELISTED` item can no longer be confirmed into new reservations.

The physical layer is the InventoryUnit. Registering a unit requires the `catalog_item_id` it belongs to, a `serial_number` unique across all units, and a `condition_grade` of `A`, `B`, or `C` — the grade acts as a depreciation factor of 1.0, 0.8, or 0.6 respectively when damage charges are assessed. A unit is born `AVAILABLE` with `cleans_since_deep` at zero and `blocked_until` null. Supplying a duplicate `serial_number` — like a duplicate customer `email` or plan `code` — is a shape violation rejected with `ERR_INVALID_REQUEST`, as is a non-positive rate, deposit, or weight.

Insurance plans are configuration, also admin-managed. Each plan has a unique `code`, a `pricing_model` of `PER_DAY` or `PERCENT_OF_RENTAL`, a `rate_value` whose legal range depends on the model, a `deductible_cents` of zero or more, a `coverage_cap_cents` greater than zero, and `covered_severities`, a subset of `COSMETIC`, `MINOR`, `MAJOR`, and `TOTAL_LOSS`. For a `PER_DAY` plan, `rate_value` is a positive integer — the premium in cents charged per billable day. For a `PERCENT_OF_RENTAL` plan, `rate_value` is a fraction greater than zero and at most 0.25, applied to the gear subtotal. A `rate_value` out of range for its model is rejected with `ERR_INVALID_PLAN_RATE`. The two models are genuinely different algorithms: for identical trip data a per-day plan scales with trip length only, while a percentage plan scales with gear value only, and they produce different premiums.

### 3.2. Customers and Hotel Partners

Anyone on the internet may register: an Anonymous request carrying `full_name`, `email`, and `phone` creates a Customer whose `email` must be unique across customers. New customers are `ACTIVE` with a `risk_score` of zero and both behavioral counters — `late_return_count` and `captured_damage_count` — at zero. The `risk_score` is a weighted sum, capped at 100: fifteen points per settled late return plus twenty-five points per captured damage claim. Two thresholds hang off it. A customer whose score is 70 or more pays a one-and-a-half-times deposit multiplier on every subsequent confirmation (§3.4). A customer whose score reaches 90 is automatically suspended at the settlement that pushed them over — the same `ACTIVE` to `SUSPENDED` transition an OperationsAdmin can trigger manually. Manual suspension requires the customer to be `ACTIVE`, and reinstatement requires the customer to be `SUSPENDED`; either attempted from the wrong state fails with `ERR_INVALID_STATE`. Suspension, however it happens, bumps the customer's `version` and bars the customer from confirming reservations: any confirm attempted while `SUSPENDED` fails with `ERR_CUSTOMER_SUSPENDED`. Reinstatement moves the customer back from `SUSPENDED` to `ACTIVE` and bumps the version again.

Hotel and resort partners are onboarded by an OperationsAdmin with a `name`, the `zone_code` the property sits in, and a `commission_pct` — the fraction of settled line charges the partner earns — which must lie between 0 and 0.30 inclusive; anything outside that band is rejected with `ERR_INVALID_REQUEST`. Partners are born `ACTIVE` and may be suspended or reactivated through a partial update that also touches `name` or `commission_pct` and bumps the partner's `version`. When a reservation names a `hotel_partner_id`, the reservation's own `zone_code` must equal the partner's `zone_code`; a mismatch is rejected with `ERR_ZONE_MISMATCH`. A reservation referencing a `SUSPENDED` partner is rejected with `ERR_PARTNER_SUSPENDED`. A reservation with no `hotel_partner_id` — null — means home delivery, earns no commission, and is invisible to every partner.

### 3.3. Quoting and Amending a Reservation

A Customer creates a reservation by supplying `delivery_address`, `zone_code`, `start_date`, `end_date`, and `lines` — one line per requested physical unit, each naming a `catalog_item_id` — plus optionally a `hotel_partner_id` and an `insurance_plan_id`. The `customer_id` is never accepted from the payload; it is taken from the `X-User-ID` of the creating customer. The reservation is born in the `QUOTED` state with `payment_status` `DEPOSIT_PENDING`, every line `PENDING`, and a provisional quote computed immediately. `lines` must be a non-empty array, else `ERR_INVALID_REQUEST`; a `start_date` or `end_date` that is not a well-formed YYYY-MM-DD value is likewise a shape violation (`ERR_INVALID_REQUEST`, 400), the `ERR_INVALID_DATE_RANGE` check applying only to well-formed dates. The remaining counters — `deposit_hold_cents`, `deposit_captured_cents`, `deposit_released_cents`, `late_fee_cents`, `extension_charge_cents`, `extension_days`, and `commission_cents` — start at zero, `final_total_cents` and `returned_at` are null until settlement and pickup respectively, and each line is born with `assigned_unit_id` null and `unit_rate_cents` zero.

The provisional quote works as follows, and the evaluation order is pinned and non-negotiable. The billable length of the rental is the number of days from `start_date` to the exclusive `end_date`, with a minimum of one billable day. Each line is priced with a marginal tier structure against the catalog item's current `daily_rate_cents`: the first six billable days are charged at the full daily rate; days seven through thirteen are charged per day at the daily rate times 0.85, rounded half-up to the cent; days fourteen and beyond are charged per day at the daily rate times 0.70, also rounded half-up. The per-line result is stored on the line as `line_charge_cents`, and the sum across lines is the reservation's `gear_subtotal_cents`. Only after the subtotal exists is the delivery fee tiered on that subtotal alone — never on the running total: a subtotal under 10000 cents attracts a 2500-cent delivery fee, a subtotal from 10000 up to and including 29999 cents attracts 1500 cents, and a subtotal of 30000 cents or more ships free. A flat 1500-cent setup fee is then added. Finally the insurance premium is computed: for a `PER_DAY` plan it is the plan's `rate_value` rounded half-up, multiplied by the billable days; for a `PERCENT_OF_RENTAL` plan it is the gear subtotal times `rate_value`, rounded half-up; with no plan the premium is zero. The `quoted_total_cents` is the gear subtotal plus the delivery fee plus the setup fee plus the premium.

While `QUOTED`, the customer may amend the rental window by submitting new `start_date` and `end_date` values together with `expected_reservation_version` (the OCC contract of §2.7). The new end must be strictly after the new start, else `ERR_INVALID_DATE_RANGE`; a stale version is rejected with `ERR_STALE_VERSION`. A successful amendment is a self-loop within `QUOTED`: the provisional quote is recomputed end to end — `quoted_total_cents`, `gear_subtotal_cents`, and every line's `line_charge_cents` — and the reservation's `version` increments by one. Because catalog rates are read at quote time but only frozen at confirmation, an amendment after a rate change re-prices the whole booking.

A reservation that is still `QUOTED` may be cancelled outright, either by the owning customer or by an OperationsAdmin. Every `PENDING` line moves to `CANCELLED` with its `version` bumped; no deposit was ever held, so `payment_status` stays `DEPOSIT_PENDING`, no ledger entries are written, and the reservation lands in `CANCELLED` — one of its two terminal states, the other being `SETTLED`.

### 3.4. Confirmation, Allocation, and the Deposit Hold

Confirmation is the point of commitment, and it is guarded by the strictest cluster of checks in the system, evaluated in the priority order of §2.8. The reservation must belong to the requesting customer, whose own record must be `ACTIVE` — a suspended customer is turned away with `ERR_CUSTOMER_SUSPENDED`. No line may reference a catalog item that has been `DELISTED` (`ERR_CATALOG_ITEM_DELISTED`), nor one sitting under an `ACTIVE` recall of `MANDATORY` severity (`ERR_RECALL_BLOCKED`). And for every line, at least one eligible physical unit must exist.

Eligibility is the availability filter, and it recurs throughout the system. A unit is eligible for a requested window when it belongs to the line's catalog item, when its status is one of `AVAILABLE`, `RESERVED`, or `RENTED_OUT` — units in `QUARANTINED`, `AWAITING_CLEANING`, `IN_CLEANING`, or `RETIRED` never count — when its `blocked_until` is either null or no later than the window's start midnight, and when no other reservation in `CONFIRMED` or `DELIVERED` holds a line assigned to that unit whose committed interval overlaps the request. The committed interval runs from the reservation's `start_date` midnight UTC to its `end_date` midnight UTC plus the catalog item's `cleaning_turnaround_hours`; overlap is half-open, so a follow-up rental may begin exactly at the buffered end of a prior commitment. When several units qualify, the allocation selector ranks them by `condition_grade` — `A` before `B` before `C` — breaking ties by `created_at` ascending, and takes the first. The same filter and ranking power the forward-looking availability readout on the catalog, which answers a window query with the catalog item id, the queried `start_date` and `end_date`, and the `available_count` of eligible units. The window query must supply well-formed `start_date` and `end_date` parameters (else `ERR_INVALID_REQUEST`) with `end_date` strictly after `start_date` (else `ERR_INVALID_DATE_RANGE`). A confirm that finds no eligible unit for any line fails, and the error distinguishes the cause. When a failing line has no candidate units at all — no unit of the line's catalog item in `AVAILABLE`, `RESERVED`, or `RENTED_OUT` left unclaimed within that confirm — the confirm fails with `ERR_NO_ELIGIBLE_UNIT`. When candidate units existed but every candidate was excluded because its `blocked_until` was later than the window's start midnight or its committed interval collided with the requested window, the confirm fails with `ERR_UNIT_UNAVAILABLE` under the temporal-overlap rule; because temporal overlap outranks unit eligibility (§2.8 priority 9 above priority 10), `ERR_UNIT_UNAVAILABLE` also settles a confirm whose lines fail for both reasons at once.

On success, each line moves `PENDING` to `ALLOCATED`: its `assigned_unit_id` is set, its `unit_rate_cents` snapshots the catalog item's `daily_rate_cents` at that moment — becoming the permanent basis for late and extension charges even if the catalog price later changes — and the chosen unit moves `AVAILABLE` to `RESERVED` with its `version` bumped. Then the deposit hold is computed. The customer's `risk_score` at confirm time selects the multiplier: 1.5 when the score is 70 or more, otherwise 1.0. Each line's hold is the catalog item's `deposit_amount_cents` times the multiplier, rounded half-up per unit, and the reservation's `deposit_hold_cents` is the sum of those per-unit holds — rounding each unit first and then summing, never the reverse. A `HOLD` ledger entry for the full `deposit_hold_cents` is appended with reason `HOLD_AT_CONFIRM`, `payment_status` moves from `DEPOSIT_PENDING` to `DEPOSIT_HELD`, and the reservation lands in `CONFIRMED` with its `version` bumped.

Cancelling a `CONFIRMED` reservation is heavier. Every `ALLOCATED` line moves to `CANCELLED` and each reserved unit returns to `AVAILABLE`, its `version` bumped, while the line keeps its `assigned_unit_id` for audit; any line still `PENDING` or `PENDING_REALLOCATION` is likewise cancelled, with no unit to release. Every `SCHEDULED` route stop referencing the reservation moves to `SKIPPED`, and each affected route's `planned_weight_kg` is recomputed without the skipped stop's gear. Every `PENDING` extension request on the reservation is `SUPERSEDED`. A cancellation fee of ten percent of `quoted_total_cents`, rounded half-up, is charged against the deposit waterfall: a `CAPTURE` entry with reason `CANCELLATION_FEE` for the lesser of the fee and the outstanding hold, then a `RELEASE` entry with reason `RELEASE_REMAINDER` for whatever is left, if anything. `payment_status` moves to `SETTLED_PAID` when any amount was captured, otherwise to `REFUNDED`, and the reservation is terminally `CANCELLED`.

### 3.5. Routes, Stops, and the Delivery Day

Logistics are organized around the DeliveryRoute, created by an OperationsAdmin with a `route_date`, the `zone_code` it serves, and a `vehicle_capacity_kg` greater than zero. Routes are born `PLANNED` with `planned_weight_kg` zero. Stops are added to a `PLANNED` route one at a time by naming a `reservation_id`, a `stop_type` of `DELIVERY_SETUP` or `PICKUP`, an `address`, and a time window from `time_window_start` to `time_window_end`. Each stop record carries the `route_id` of its owning route alongside its `reservation_id`, so the stops of a route and the stops of a reservation are both reachable through those references. The window must lie within the `route_date` with start strictly before end (`ERR_INVALID_DATE_RANGE`), the stop reservation's zone must equal the route's zone (`ERR_ZONE_MISMATCH`), and — because windows are half-open — the new window may not overlap any other non-`SKIPPED` stop's window on the same route, else `ERR_STOP_WINDOW_CONFLICT`. Two structural rules guard the route as a whole. First, duplicates: the same reservation and `stop_type` pair may not already have a `SCHEDULED` or `COMPLETED` stop on any `PLANNED` or `DISPATCHED` route, else `ERR_DUPLICATE_STOP`. Second, capacity: a stop's weight is the sum of `weight_kg` over its reservation's non-`CANCELLED` lines, and adding it must leave the route's aggregate `planned_weight_kg` at or below `vehicle_capacity_kg` — an exact fit is allowed, any excess is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. Stops in `FAILED` or `SKIPPED` contribute nothing to the load. A successful add updates the route's `planned_weight_kg`, bumps the route's `version`, and assigns the stop its `sequence`: stops not in `SKIPPED` are numbered from 1 in `time_window_start` ascending order, ties broken by `created_at` ascending, never by id, and the numbering is recomputed whenever a stop is added or skipped. A route's stop listing follows this numbering — numbered stops in `sequence` order, with `SKIPPED` stops ordered after all numbered stops — rather than the default `created_at` ordering, and stop time windows are rendered as ISO 8601 UTC timestamps with three fractional digits.

A `PLANNED` route with at least one `SCHEDULED` stop may be dispatched, moving to `DISPATCHED`; an empty route refuses with `ERR_INVALID_STATE`. Dispatch is reversible: so long as no stop on the route is `COMPLETED` yet, the route may be recalled to `PLANNED`. Once every stop sits in a terminal state — `COMPLETED`, `FAILED`, or `SKIPPED` — the route itself may be completed, landing terminally in `COMPLETED`.

Stop execution is where logistics drives the reservation lifecycle. An OperationsAdmin completes a `SCHEDULED` stop only while its route is `DISPATCHED`, and only when the referenced reservation is in the matching state — `CONFIRMED` for a `DELIVERY_SETUP` stop, `DELIVERED` for a `PICKUP` — with any mismatch rejected as `ERR_INVALID_STATE`. Completion stamps `completed_at` from the current logical clock. Completing a `DELIVERY_SETUP` stop moves the reservation `CONFIRMED` to `DELIVERED`: every `ALLOCATED` line goes `OUT` and each assigned unit goes `RESERVED` to `RENTED_OUT`, versions bumping on reservation, lines, and units. Completing a `PICKUP` stop moves the reservation `DELIVERED` to `RETURNED`: `returned_at` is stamped from the same clock, every `OUT` line becomes `RETURNED`, and each assigned unit moves `RENTED_OUT` to `AWAITING_CLEANING` with `blocked_until` set to `returned_at` plus the catalog item's `cleaning_turnaround_hours` — then, per returned unit, a cleaning ticket is auto-created and the unit moves immediately on to `IN_CLEANING`, as §3.6 describes. A stop that cannot be serviced is instead marked `FAILED`, a terminal stop state with no cascade into the reservation. Failing a stop requires the stop to be `SCHEDULED` on a `DISPATCHED` route, else `ERR_INVALID_STATE`; the route's `planned_weight_kg` is then recomputed without the failed stop's gear and the route's `version` bumps.

### 3.6. Cleaning Cycles and Recall Quarantine

Every returned unit passes through cleaning before it can be rented again. The auto-created ticket at pickup chooses its `ticket_type` by the unit's cycle counter: a `DEEP` ticket when the unit's `cleans_since_deep` has already reached the catalog item's `deep_clean_every_cycles`, otherwise `STANDARD`. Inspectors and OperationsAdmins may also open tickets manually for a unit that is `AWAITING_CLEANING` or `QUARANTINED`, naming the `unit_id` and any `ticket_type` — but `RECALL_DECONTAMINATION` is reserved for `QUARANTINED` units, only one `OPEN` ticket may exist per unit at a time (a second open attempt fails with `ERR_INVALID_STATE`), and a manual `STANDARD` ticket is refused with `ERR_DEEP_CLEAN_REQUIRED` when the unit's `cleans_since_deep` has already reached the deep-clean cadence — a deep clean is due and cannot be skipped. Ticket creation, automatic or manual, moves an `AWAITING_CLEANING` unit to `IN_CLEANING`.

An Inspector resolves a ticket as `PASSED` or `FAILED`, optionally attaching a `resolution_note`, and the ticket records the resolving operator in `inspector_user_id`. Resolution requires the unit to be in the matching state — `IN_CLEANING` for a `STANDARD` or `DEEP` ticket, `QUARANTINED` for a `RECALL_DECONTAMINATION` ticket — else `ERR_INVALID_STATE`. Passing a `STANDARD` ticket increments the unit's `cleans_since_deep` by one; passing a `DEEP` or `RECALL_DECONTAMINATION` ticket resets `cleans_since_deep` to zero. A passed ticket returns an `IN_CLEANING` unit to `AVAILABLE`; a passed `RECALL_DECONTAMINATION` ticket additionally lifts a `QUARANTINED` unit back to `AVAILABLE` and clears its `blocked_until` to null. Failing a ticket sends an `IN_CLEANING` unit back to `AWAITING_CLEANING` with `cleans_since_deep` unchanged — the unit must be cleaned again — while a failed `RECALL_DECONTAMINATION` ticket leaves the unit `QUARANTINED`. A unit may also be retired outright, moving from `AVAILABLE` or `QUARANTINED` to the terminal `RETIRED` state.

The recall workflow rides on top of this. An OperationsAdmin files a RecallNotice with the `catalog_item_id` under recall, a manufacturer `recall_code`, a `severity` of `ADVISORY` or `MANDATORY`, and a `description`; the notice is born `DRAFT`. Activating the notice stamps `activated_at` from the current logical clock. An `ADVISORY` activation is informational. A `MANDATORY` activation triggers a three-deep cascade: first, every unit of the recalled catalog item in `AVAILABLE`, `RESERVED`, `RENTED_OUT`, `AWAITING_CLEANING`, or `IN_CLEANING` moves to `QUARANTINED` with its `version` bumped; second, for each quarantined unit that had been `RESERVED`, the holding `ALLOCATED` line drops to `PENDING_REALLOCATION` with its `assigned_unit_id` cleared to null and both line and reservation versions bumped; third, for every reservation holding a now-`PENDING_REALLOCATION` line, any `SCHEDULED` `DELIVERY_SETUP` stop for that reservation moves to `SKIPPED` and its route's `planned_weight_kg` is recomputed. A unit quarantined while `RENTED_OUT` stays with the customer; when the pickup stop later completes, the reservation and line transitions proceed normally, but the quarantined unit itself skips the cleaning cascade — it remains `QUARANTINED`, its `blocked_until` is left unchanged, and no automatic ticket is created for it — and it is decontaminated only through a manually opened `RECALL_DECONTAMINATION` ticket. Recall safety also reaches forward: confirming a reservation whose catalog item sits under an `ACTIVE` `MANDATORY` notice fails with `ERR_RECALL_BLOCKED`, and the reallocation selector never hands out a quarantined unit. Recovery from a quarantined reservation is the reallocate action on the stranded line, available to an OperationsAdmin while the reservation is `CONFIRMED`: the same eligibility filter and `A`-then-`B`-then-`C` ranking as confirmation chooses a replacement — with the reservation's own committed interval excluded from the overlap check — excluding any unit under an `ACTIVE` `MANDATORY` recall; if the only candidates are quarantined the rejection is `ERR_UNIT_QUARANTINED`, if no candidates exist at all it is `ERR_NO_ELIGIBLE_UNIT`, and if non-quarantined candidates exist but every one is excluded by its `blocked_until` or a committed-interval overlap the rejection is `ERR_UNIT_UNAVAILABLE`. Success assigns the new unit, moves it `AVAILABLE` to `RESERVED`, returns the line to `ALLOCATED`, and bumps line, unit, and reservation versions. A recall closes only once no unit of its catalog item remains `QUARANTINED` — attempting closure earlier fails with `ERR_INVALID_STATE` — moving the notice from `ACTIVE` to the terminal `CLOSED`.

### 3.7. Extensions, Damage, and Settlement

A customer whose trip runs long files an extension request naming a `requested_end_date` strictly after the reservation's current `end_date`, carrying `expected_reservation_version` under the OCC contract — a stale view is refused with `ERR_STALE_VERSION`, because a newly created extension legitimately supersedes a prior `PENDING` one and a writer holding an outdated view must not supersede blindly. Creation is refused only when the reservation sits in a terminal state (`SETTLED` or `CANCELLED`, `ERR_INVALID_STATE`); it is accepted from any non-terminal state, though approval will later require `CONFIRMED` or `DELIVERED`. Creation supersedes any prior `PENDING` extension, moving it to `SUPERSEDED`, and bumps the reservation's `version` by one. An OperationsAdmin then decides. Denial moves the request `PENDING` to `DENIED`. Approval requires the reservation to be `CONFIRMED` or `DELIVERED` — anything else is `ERR_INVALID_STATE` — and an availability sweep: for every allocated unit, no other reservation's committed interval, cleaning buffer included, may overlap the extension window running from the current `end_date` to the `requested_end_date`; a collision is rejected with `ERR_EXTENSION_WINDOW_CONFLICT`. On approval the extension charge is computed per allocated line against the `unit_rate_cents` snapshot: the first two extension days are billed per day at the unit rate times 1.20, rounded half-up, and every day from the third onward at the unit rate times 1.50, rounded half-up, and the line charges are summed into the request's `extension_charge_cents`. The reservation then absorbs the extension: `end_date` moves to `requested_end_date`, `extension_days` and `extension_charge_cents` accumulate the new values, and the reservation's `version` bumps. Either way, `decided_by_user_id` records the deciding operator. Because line charges are frozen at quote time, an extension changes the final bill without touching any line's `line_charge_cents`.

Damage is adjudicated through the DamageClaim, filed by an Inspector or OperationsAdmin against a returned line by naming the `reservation_line_id`, a `severity` of `COSMETIC`, `MINOR`, `MAJOR`, or `TOTAL_LOSS`, a `repair_cost_cents` of zero or more, and a `description`; the filer is recorded as `filed_by_user_id`. A claim may only be filed on a `RETURNED` line, and approval additionally requires the reservation itself to be `RETURNED` — violations surface as `ERR_INVALID_STATE`. Segregation of duties binds both approval and denial: the reviewing operator's `X-User-ID` must differ from `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Approval computes the customer-borne `capture_amount_cents` and stamps `reviewed_by_user_id`. The computation starts from a base: for `TOTAL_LOSS` the base is the catalog item's `deposit_amount_cents` — replacement cost — and the assessed `repair_cost_cents` is ignored; for other severities the base is `repair_cost_cents`. Severity scales the base by 0.25 for `COSMETIC`, 0.60 for `MINOR`, or 1.00 for `MAJOR`, while `TOTAL_LOSS` is not severity-scaled. The assigned unit's `condition_grade` at approval time then scales the result by 1.0, 0.8, or 0.6 for grades `A`, `B`, `C`, and the product is rounded half-up to the cent. Insurance then reshapes the charge if the reservation carries a plan and the claim's severity is among the plan's `covered_severities`: the customer pays the lesser of the charged amount and the plan's `deductible_cents`, plus any part of the charged amount exceeding the plan's `coverage_cap_cents` — the insurer absorbs the middle band between deductible and cap. Without applicable coverage the customer bears the full charged amount. Denial likewise stamps `reviewed_by_user_id` and moves the claim to `DENIED` — not terminal. The owning customer may dispute a denied claim, moving it to `DISPUTED`, and an OperationsAdmin may reopen a disputed claim back to `UNDER_REVIEW`, resetting `reviewed_by_user_id` to null for a fresh review.

Settlement closes the books, performed by an OperationsAdmin once the reservation is `RETURNED`. The late fee is computed first, per `RETURNED` line — a line not yet `RETURNED` (for example, one still `PENDING_REALLOCATION`) accrues no fee. The due instant is the reservation's `end_date` at 00:00:00Z — exclusive end, midnight UTC. Lateness is the whole minutes from that instant to `returned_at`, never negative. A grace window of four hours applies: lateness of exactly 240 minutes or less is free, and no late-return counter moves. One minute beyond the grace bills a full first hour: the minutes beyond 240 are rounded up to whole billable hours, each billed at the greater of one cent and the line's `unit_rate_cents` times 0.15 rounded half-up, and each line's fee is capped at twice its `unit_rate_cents`. The per-line fees sum into `late_fee_cents`, and when any lateness beyond the grace window occurred, the customer's `late_return_count` increments by one — once per reservation, no matter how many lines were late. The final charge is then `final_total_cents`, the quoted total plus the accumulated `extension_charge_cents` plus the `late_fee_cents`; identical planned data with an approved extension or a late return therefore settles to a different number than the provisional quote. Claims resolve into the deposit: claims still `UNDER_REVIEW` are simply not captured, while every `APPROVED` claim moves to `CAPTURED`, version bumped, reviewer preserved. The waterfall drains the hold in strict bucket order — first the approved claims, processed in claim `created_at` ascending, each capturing the lesser of its `capture_amount_cents` and the remaining hold under reason `DAMAGE_CLAIM`; then the late fee, capturing the lesser of `late_fee_cents` and the remainder under reason `LATE_FEE`; and finally a single `RELEASE` entry returns whatever is left under reason `RELEASE_REMAINDER`, if anything remains. Any obligation beyond the hold is absorbed silently. When the reservation named a hotel partner, commission is computed per line — each line's `line_charge_cents` times the partner's `commission_pct`, rounded half-up per line, then summed into `commission_cents`; rounding once after summing is a different, incorrect value, and extensions do not enter the base because they never alter line charges. The customer's `captured_damage_count` grows by the number of claims captured, the `risk_score` is recomputed from the updated counters, and if it has reached 90 the customer cascades from `ACTIVE` to `SUSPENDED` there and then. Finally `payment_status` leaves `DEPOSIT_HELD` for `SETTLED_PAID` when anything was captured, else `REFUNDED`, the reservation lands in the terminal `SETTLED` state, and the deposit ledger stands conserved: the hold equals exactly what was captured plus what was released.

## 4. Endpoint Definitions

All endpoints share the envelope, authentication, and pagination contracts of §2. Operations that create a new resource return HTTP 201 with the created resource; operations that modify, transition, or read a resource return HTTP 200. Errors carry the HTTP status listed in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /customers | Register a customer | Anonymous |
| GET | /customers/{id} | Read a customer | Customer, OperationsAdmin |
| GET | /customers | List customers | OperationsAdmin |
| POST | /customers/{id}/suspend | Suspend a customer | OperationsAdmin |
| POST | /customers/{id}/reinstate | Reinstate a suspended customer | OperationsAdmin |
| POST | /catalog-items | Create a catalog item | OperationsAdmin |
| GET | /catalog-items/{id} | Read a catalog item | Customer, HotelPartner, Inspector, OperationsAdmin |
| GET | /catalog-items | List catalog items with filters and pagination | Customer, HotelPartner, Inspector, OperationsAdmin |
| PATCH | /catalog-items/{id} | Update rates/specs or delist | OperationsAdmin |
| GET | /catalog-items/{id}/availability | Computed availability count over a window including cleaning buffer | Customer, HotelPartner, OperationsAdmin |
| GET | /catalog-items/{id}/recalls | Recall notices for a catalog item | Inspector, OperationsAdmin |
| POST | /inventory-units | Register a physical unit | OperationsAdmin |
| GET | /inventory-units/{id} | Read a unit | Inspector, OperationsAdmin |
| GET | /inventory-units | List units | Inspector, OperationsAdmin |
| POST | /inventory-units/{id}/retire | Retire a unit (AVAILABLE or QUARANTINED only) | OperationsAdmin |
| GET | /inventory-units/{id}/cleaning-tickets | Cleaning tickets for a unit | Inspector, OperationsAdmin |
| POST | /hotel-partners | Onboard a hotel/resort partner | OperationsAdmin |
| GET | /hotel-partners/{id} | Read a partner | HotelPartner, OperationsAdmin |
| GET | /hotel-partners | List partners | OperationsAdmin |
| PATCH | /hotel-partners/{id} | Update commission or suspend/reactivate a partner | OperationsAdmin |
| POST | /insurance-plans | Create an insurance plan | OperationsAdmin |
| GET | /insurance-plans | List insurance plans | Customer, HotelPartner, OperationsAdmin |
| GET | /insurance-plans/{id} | Read a plan | Customer, HotelPartner, OperationsAdmin |
| POST | /reservations | Create a quoted reservation with one line per requested unit | Customer |
| GET | /reservations/{id} | Read a reservation | Customer, HotelPartner, OperationsAdmin |
| GET | /reservations | List reservations | Customer, HotelPartner, OperationsAdmin |
| POST | /reservations/{id}/confirm | Confirm a quote: allocate units, take the deposit hold | Customer |
| POST | /reservations/{id}/cancel | Cancel a QUOTED or CONFIRMED reservation (fee from CONFIRMED) | Customer, OperationsAdmin |
| POST | /reservations/{id}/amend-dates | Amend dates of a QUOTED reservation (OCC) | Customer |
| POST | /reservations/{id}/settle | Settle a RETURNED reservation: late fee, claim capture, waterfall, commission, risk score | OperationsAdmin |
| GET | /reservations/{id}/deposit-transactions | Deposit ledger entries for a reservation | Customer, OperationsAdmin |
| GET | /reservations/{id}/extensions | Extension requests for a reservation | Customer, OperationsAdmin |
| POST | /reservations/{id}/extensions | Request an extension (OCC; supersedes any PENDING extension) | Customer |
| GET | /extensions/{id} | Read an extension request | Customer, OperationsAdmin |
| POST | /extensions/{id}/approve | Approve an extension after the availability check | OperationsAdmin |
| POST | /extensions/{id}/deny | Deny an extension | OperationsAdmin |
| GET | /reservation-lines/{id} | Read a reservation line | Customer, Inspector, OperationsAdmin |
| GET | /reservation-lines | List reservation lines | Customer, Inspector, OperationsAdmin |
| GET | /reservation-lines/{id}/damage-claims | Damage claims on a line | Customer, Inspector, OperationsAdmin |
| POST | /reservation-lines/{id}/reallocate | Assign a replacement unit to a PENDING_REALLOCATION line | OperationsAdmin |
| POST | /routes | Create a delivery route | OperationsAdmin |
| GET | /routes/{id} | Read a route | Inspector, OperationsAdmin |
| GET | /routes | List routes | Inspector, OperationsAdmin |
| POST | /routes/{id}/stops | Add a stop to a PLANNED route (capacity and window checks) | OperationsAdmin |
| GET | /routes/{id}/stops | Stops on a route | Inspector, OperationsAdmin |
| POST | /routes/{id}/dispatch | Dispatch a PLANNED route | OperationsAdmin |
| POST | /routes/{id}/recall | Recall a DISPATCHED route back to PLANNED (no completed stops) | OperationsAdmin |
| POST | /routes/{id}/complete | Complete a DISPATCHED route once all stops are terminal | OperationsAdmin |
| GET | /route-stops/{id} | Read a stop | Inspector, OperationsAdmin |
| GET | /route-stops | List stops | Inspector, OperationsAdmin |
| POST | /route-stops/{id}/complete | Complete a stop; cascades delivery or pickup into reservation, units, and cleaning | OperationsAdmin |
| POST | /route-stops/{id}/fail | Mark a stop FAILED | OperationsAdmin |
| POST | /recalls | Create a recall notice (DRAFT) | OperationsAdmin |
| GET | /recalls/{id} | Read a recall | Inspector, OperationsAdmin |
| POST | /recalls/{id}/activate | Activate a recall; MANDATORY quarantines units and cascades | OperationsAdmin |
| POST | /recalls/{id}/close | Close an ACTIVE recall once no units remain QUARANTINED | OperationsAdmin |
| POST | /cleaning-tickets | Manually open a cleaning ticket | Inspector, OperationsAdmin |
| GET | /cleaning-tickets/{id} | Read a cleaning ticket | Inspector, OperationsAdmin |
| POST | /cleaning-tickets/{id}/pass | Pass a ticket; the unit returns to AVAILABLE with cycle-counter update | Inspector |
| POST | /cleaning-tickets/{id}/fail | Fail a ticket; the unit returns to AWAITING_CLEANING (or stays QUARANTINED for RECALL_DECONTAMINATION) | Inspector |
| POST | /damage-claims | File a damage claim against a RETURNED line | Inspector, OperationsAdmin |
| GET | /damage-claims/{id} | Read a damage claim | Customer, Inspector, OperationsAdmin |
| POST | /damage-claims/{id}/approve | Approve a claim (segregation of duties); computes the capture amount | OperationsAdmin |
| POST | /damage-claims/{id}/deny | Deny a claim (segregation of duties) | OperationsAdmin |
| POST | /damage-claims/{id}/dispute | Customer disputes a DENIED claim | Customer |
| POST | /damage-claims/{id}/reopen | Reopen a DISPUTED claim into UNDER_REVIEW | OperationsAdmin |
| POST | /_clock/set_current_utc | Set the logical clock (test-driving endpoint) | OperationsAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_CATALOG_ITEM_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_PARTNER_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_LINE_NOT_FOUND | 404 |
| ERR_ROUTE_NOT_FOUND | 404 |
| ERR_STOP_NOT_FOUND | 404 |
| ERR_EXTENSION_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_RECALL_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_RECALL_BLOCKED | 409 |
| ERR_UNIT_QUARANTINED | 409 |
| ERR_UNIT_UNAVAILABLE | 409 |
| ERR_EXTENSION_WINDOW_CONFLICT | 409 |
| ERR_STOP_WINDOW_CONFLICT | 409 |
| ERR_ZONE_MISMATCH | 422 |
| ERR_PARTNER_SUSPENDED | 409 |
| ERR_CUSTOMER_SUSPENDED | 403 |
| ERR_CATALOG_ITEM_DELISTED | 409 |
| ERR_ROUTE_CAPACITY_EXCEEDED | 422 |
| ERR_DUPLICATE_STOP | 409 |
| ERR_DEEP_CLEAN_REQUIRED | 409 |
| ERR_NO_ELIGIBLE_UNIT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_PLAN_RATE | 422 |
