# Outdoor Camping Co-op API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Outdoor & Camping Co-op API, the operational backbone of a member-owned outdoor retailer modeled on the cooperative store tradition. The platform unifies a broad set of interlocking activities under a single co-op membership: catalog sales of camping gear, day-rate rental of physical gear units, used-gear trade-in and consignment resale, classes and guided trips with seat allocation and waitlists, and finite permit pools for parks and seasons. Members carry a store-credit wallet and a loyalty balance that thread through nearly every transaction, so an action taken at the rental counter, the classroom desk, or the permit window must reconcile a member's financial and loyalty standing immediately and consistently.

The system is deliberately built around two recurring tensions. The first is scarcity: rental units, class seats, and permit pools are all finite, and the API must decide precisely when a request reserves, waitlists, or is turned away. The second is money handled to the cent: rental charges apply tiered discounts and late fees, orders round member discounts line by line, and trade-ins pay out under two competing valuation models. Because several of these flows can be driven concurrently by a member and by store staff, the API applies optimistic concurrency control at the points where two writers could otherwise silently overwrite a shared count.

Two operational actors run the store day to day — the co-op **Member**, who initiates their own rentals, orders, bookings, trade-ins, and permits, and the **StoreStaff** operator, who runs the counter, catalog, appraisals, fulfillment, trips, and permit pools. A third, **Public**, exists only to register new members and to drive the deterministic test clock. Everything below is written so that an implementer can reconstruct the full contract from this document alone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than member registration and setting the test clock must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or unrecognized on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as `Member`, `StoreStaff`, and `Public`. When an authenticated caller's role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles bind to identity differently, and the difference governs ownership checks:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks compare a resource's owning member reference — the `member_id` field it carries — to `X-User-ID`; a `Member` may act only on resources whose `member_id` equals their own `X-User-ID`, and an attempt to read or mutate another member's resource is rejected with `ERR_UNAUTHORIZED`.
- When `X-User-Role` is `StoreStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; store staff act across all members' resources.
- When `X-User-Role` is `Public`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity. The `Public` role may only register a new membership and set the test clock.

Registration and setting the test clock are exempt from authentication and enforce no role check whatsoever — the server does not inspect the `X-User-ID`/`X-User-Role` headers on these two endpoints, so any caller may invoke them regardless of role or of whether the headers are present (`Public` and `StoreStaff` are simply the intended registrars). Counter and catalog operations — registering gear, taking units in and out, appraising and selling trade-ins, fulfilling orders, running trips, checking members in, and creating permit pools — are exclusive to `StoreStaff`. Submitting a trade-in and responding to a trade-in offer are exclusive to `Member`. Quoting rentals, cancelling rentals, creating and paying and returning orders, creating and cancelling bookings, and issuing permit passes are shared between `Member` and `StoreStaff`. All GET reads are available to both `Member` (on their own resources) and `StoreStaff`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter counts how many items to skip from the start of the result set and defaults to 0. A `limit` below 1 or above 100, or a negative `offset`, is silently clamped into range (to 1/100 and to 0 respectively) rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. Unless a specific endpoint states otherwise, every list is ordered by the resource's `created_at` timestamp in ascending order. Each list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — `Member`, `GearSku`, `GearUnit`, `RentalAgreement`, `SalesOrder`, `TradeIn`, `ClassTrip`, `Booking`, `PermitAllocation`, and `PermitPass` — carries a common set of server-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. `version` is an integer that starts at its initial value on creation and increments by one on every mutation; it is the value used for optimistic concurrency control described in §2.7. Whenever a server-side reconciliation changes a derived field — for example a member's wallet balance, a trip's seat counts, or a pool's remaining quota — that change is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Monetary Values, Counts, and Precision

All monetary amounts are stored and returned as integer cents; there are no fractional-cent values in this system. Wherever a rule multiplies an amount by a rate or percentage, the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero to the next whole cent). Seat counts, waitlist counts, quota counts, loyalty points, and rental-day counts are whole integers. Two integer safeguards apply everywhere: a member's `store_credit_cents` and `loyalty_points_balance` are never allowed to go below zero, and derived counts such as `seats_available` and `available_quota` are floored at zero rather than being permitted to become negative.

### 2.6. The Member Wallet and Loyalty Ledger

Each `Member` holds three running balances that the API keeps reconciled in real time. `store_credit_cents` is a wallet balance in cents, funded by trade-in payouts, order refunds, booking refunds, and direct staff adjustments, and debited by pay-with-credit orders, class bookings, and permit purchases. `loyalty_points_balance` accrues on paid orders, rental returns, and class check-ins, and is reversed when the underlying transaction is undone. `lifetime_eligible_spend_cents` is the cumulative eligible spend that rises when an order is paid and falls when that order is returned. These balances are the single source of truth for a member's financial standing; any operation that would drive the wallet or the loyalty balance below zero is either rejected by an upstream fiscal check or is a reversal that cannot exceed what was originally posted.

Store staff may directly correct a wallet through an administrative adjustment that adds a signed `amount_cents` to `store_credit_cents`, optionally annotated with a `reason`; this adjustment increments the member's `version`.

### 2.7. Optimistic Concurrency Control

Two write operations draw down a shared, finite parent count and are therefore guarded by optimistic concurrency control against a stale view of that parent.

Creating a booking against a class or trip requires the client to submit `expected_classtrip_version` carrying the `version` of the target `ClassTrip` that the client last observed. If that value does not match the trip's current `version` — because another writer has since created a booking that advanced the trip's `version` and may have changed whether a fresh request would seat or waitlist — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Issuing a permit pass requires `expected_allocation_version` carrying the last observed `version` of the target `PermitAllocation`; if another writer has since drawn a permit and advanced the pool's `version`, the issue is rejected with `ERR_STALE_VERSION` (HTTP 412). This concurrency check is evaluated after the resource's existence and business preconditions and before any side effect is committed. No other endpoint takes a version field, and endpoints without an `expected_<parent>_version` input perform no concurrency check.

### 2.8. Existence and Left-to-Right Reference Validation

Requests routinely name resources both in the URL path and by foreign-key fields in the body. The system validates existence left to right, in the order the identifiers are encountered — member, gear SKU, gear unit, rental, sales order, trade-in, class or trip, booking, permit allocation, permit pass — and rejects on the first identifier that does not resolve, returning the specific not-found error for that resource type (`ERR_MEMBER_NOT_FOUND`, `ERR_GEAR_SKU_NOT_FOUND`, `ERR_GEAR_UNIT_NOT_FOUND`, `ERR_RENTAL_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`, `ERR_TRADE_IN_NOT_FOUND`, `ERR_CLASS_TRIP_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PERMIT_ALLOCATION_NOT_FOUND`, `ERR_PERMIT_PASS_NOT_FOUND`), each carrying HTTP 404. Because all entities are peer top-level collections, cross-collection reverse reachability is provided by filtered list endpoints rather than nested URLs: gear units filter by `gear_sku_id`; rentals by `member_id` and `gear_unit_id`; orders by `member_id`; trade-ins by `member_id` and `gear_sku_id`; bookings by `member_id` and `class_trip_id`; permit passes by `member_id` and `permit_allocation_id`. Each list also accepts a `status` filter alongside `limit` and `offset`.

Malformed bodies, missing required fields, bad enum values, and non-positive values where a positive number is required are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. The Logical Clock and Time-Driven State

All time-sensitive logic reads a server logical clock rather than wall-clock time. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and it holds that value until explicitly set; it never falls back to real wall-clock time. A test-driving capability sets the clock to a supplied `to_iso8601` instant. The clock governs four deterministic behaviors: rental late-fee computation at return, member schedule-conflict checks for bookings, permit-season validity, and permit-pass expiry. Whenever the clock is advanced, any `PermitPass` whose `entry_date` plus one day is strictly earlier than the new clock value transitions from `ISSUED` to `EXPIRED`; an expired pass is no longer valid, but the pool's `issued_count` is unchanged because a drawn permit consumes its pool's quota for the whole season even after it expires.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first (priority 1), then role authorization including the member-ownership rule (priority 2), then existence of all path and foreign-key resources left to right (priority 3), then whether the target resource is in a legal state for the requested transition (priority 4); a transition attempted from an illegal state that no more specific error covers is rejected with `ERR_INVALID_STATE` (HTTP 409). Business rules follow in this order: membership-active safety checks (priority 5), temporal-window checks (priority 6), the rental rentability referential check (priority 7), the permit quota-capacity check (priority 8), and the store-credit sufficiency fiscal check (priority 9). The optimistic-concurrency stale-version check is evaluated last, after the business checks and before side effects commit (priority 10). A caller who is both unauthenticated and acting on a nonexistent resource, for instance, receives the authentication error, not the not-found error.

## 3. Business Logic and Workflows

### 3.1. Membership, the Catalog, and Physical Units

A membership is opened by supplying an `email` login handle and a `full_name`. Two enumerated attributes may be provided at setup or left to default: `membership_tier` is either `BASIC` or `PREMIER` and defaults to `BASIC`, where a `PREMIER` member earns a ten percent purchase discount that surfaces in rental and order pricing; `membership_status` is either `ACTIVE` or `LAPSED` and defaults to `ACTIVE`. A `LAPSED` member may not pick up rentals, quote rentals, book trips, or buy permits. A new member's `store_credit_cents`, `loyalty_points_balance`, and `lifetime_eligible_spend_cents` all begin at zero.

The catalog is organized as gear SKUs and the physical units beneath them. A gear SKU is created with a `name`, a `category` drawn from `TENT`, `BACKPACK`, `KAYAK`, `STOVE`, or `APPAREL`, and a `retail_price_cents` that must be zero or greater. A SKU also declares whether it is `rentable` (defaulting to false) and, when rentable, a `daily_rental_rate_cents` (defaulting to zero, and never negative) that sets its per-day rental price. A physical `GearUnit` is registered against its parent SKU by supplying that SKU's identifier as `gear_sku_id`, a `serial_number`, and an optional `condition_grade` of `NEW`, `GOOD`, or `FAIR` that defaults to `GOOD`. Every unit begins `AVAILABLE`.

A unit's `status` records physical possession only and takes just two values, `AVAILABLE` and `RENTED_OUT`. Reservations are logical rather than physical: a single `AVAILABLE` unit may back several future, non-overlapping rental agreements at once, and the unit's `status` flips only when gear physically leaves the counter and again when it comes back.

### 3.2. The Rental Lifecycle

A rental is created — "quoted" — by naming the renting member through `member_id`, the reserved unit through `gear_unit_id`, and the reservation window through `start_at` and `due_at`, both ISO 8601 UTC. The request may also set `damage_waiver` (defaulting to false) and a refundable `deposit_cents` security deposit (defaulting to zero, never negative). Quoting is permitted only when the member's `membership_status` is `ACTIVE`; otherwise the quote is rejected with `ERR_MEMBERSHIP_INACTIVE`. The referenced unit's parent SKU must be `rentable`; a quote against a non-rentable SKU is rejected with `ERR_UNIT_NOT_RENTABLE`. The requested window must not collide with any existing non-terminal rental (one in `QUOTED` or `PICKED_UP`) on the same unit: each rental occupies the half-open interval that runs from its `start_at` up to but not including its `due_at` extended by a twenty-four-hour service buffer, and if the requested interval and an existing interval share any instant the quote is rejected with `ERR_UNIT_UNAVAILABLE`. A quote makes no change to the unit's `status`, snapshots the SKU's current daily rental rate into `daily_rate_cents`, and computes `rental_days` together with the provisional `estimated_charge_cents`.

The reservation window drives the day count: `rental_days` is the span from `start_at` to `due_at` expressed in days and rounded up to the next whole day, with a floor of one day so that any rental spans at least one billable day. The estimated charge is built up as follows. The daily subtotal is the snapshotted `daily_rate_cents` multiplied by `rental_days`. When `rental_days` is at least seven, a multi-day discount equal to the daily subtotal multiplied by fifteen percent (rounded to whole cents) is subtracted; below seven days there is no such discount. The member-tier discount is then the discounted amount — the daily subtotal after the multi-day discount — multiplied by the member's tier rate (zero percent for `BASIC`, ten percent for `PREMIER`), rounded to whole cents. If `damage_waiver` is set, a waiver fee equal to the original daily subtotal multiplied by ten percent (rounded to whole cents) is added; note the waiver fee is computed from the daily subtotal before any discount. The `estimated_charge_cents` is the discounted amount minus the member-tier discount, plus the waiver fee. At quote time no late fee is contemplated and `final_charge_cents` remains null.

Picking up a rental is a counter operation reserved for store staff. It is allowed only when the rental is `QUOTED`, when the member's `membership_status` is still `ACTIVE`, and when the reserved unit is currently `AVAILABLE`; if the unit is already out on another rental the pickup is rejected with `ERR_UNIT_NOT_READY`. Pickup advances the rental from `QUOTED` to `PICKED_UP` and flips the unit from `AVAILABLE` to `RENTED_OUT`.

Returning a rental, also a staff counter operation, is allowed only when the rental is `PICKED_UP`. Return advances the rental from `PICKED_UP` to `RETURNED`, stamps `returned_at` from the logical clock, flips the unit from `RENTED_OUT` back to `AVAILABLE`, and computes the final charge. The final charge starts from the previously computed `estimated_charge_cents` and adds a late fee. A rental is late only when `returned_at` falls strictly after `due_at`; in that case the number of late days is the span from `due_at` to `returned_at` in days rounded up to the next whole day, and the late fee is that late-day count multiplied by the snapshotted `daily_rate_cents` multiplied by one and one-half, rounded to whole cents. If the return is on or before `due_at` there is no late fee. The resulting `final_charge_cents` is the estimated charge plus the late fee, and on return the member's `loyalty_points_balance` increases by the final charge divided by one hundred, rounded down to a whole number of points.

Cancelling a rental is available to the member or to staff and is allowed only while the rental is `QUOTED`; it moves the rental from `QUOTED` to `CANCELLED`. Because a quote never debited the wallet and never changed the unit's `status`, cancellation simply releases the logical reservation and the deposit hold with no wallet change and no unit-status revert. `RETURNED` and `CANCELLED` are terminal.

### 3.3. Sales Orders Across Two Independent Axes

A sales order tracks two independent state axes at once: a payment axis in `payment_status` moving through `UNPAID`, `PAID`, and `REFUNDED`, and a fulfillment axis in `fulfillment_status` moving through `UNFULFILLED`, `FULFILLED`, and `RETURNED`. An order is created by naming the purchasing `member_id` and a non-empty `lines` array, where each line pairs a `gear_sku_id` with a `quantity` of at least one; the unit price of each line is snapshotted from the SKU's `retail_price_cents` at create time to drive the order totals below, but that snapshot is not persisted as its own field and the stored line object retains only its `gear_sku_id` and `quantity`. The create may set `use_store_credit` (defaulting to false), which decides whether payment later draws from the wallet. A new order begins `UNPAID` and `UNFULFILLED`.

Order pricing is computed at create with a rounding order that must not be transposed. For each line, the line gross is the snapshotted unit price multiplied by that line's `quantity`. The order `subtotal_cents` is the sum of the line grosses. The `discount_cents` is computed per line and rounded per line before summing: for each line, multiply its line gross by the member's tier rate (zero percent for `BASIC`, ten percent for `PREMIER`), round that line's discount to whole cents, and only then sum the rounded per-line discounts. The order `total_cents` is the subtotal minus the summed discount. The `loyalty_points_earned` on the order is the total divided by one hundred, rounded down to a whole number.

Paying an order, available to the member or to staff, is allowed only while `payment_status` is `UNPAID`. When `use_store_credit` is set, the member's `store_credit_cents` must be at least the order `total_cents`, or the payment is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`. On success the payment axis moves to `PAID`; if `use_store_credit` is set the `total_cents` is deducted from `store_credit_cents`; the member's `loyalty_points_balance` increases by `loyalty_points_earned`; and `lifetime_eligible_spend_cents` increases by `total_cents`. Fulfilling an order is a staff operation on the fulfillment axis alone: it is allowed only while `fulfillment_status` is `UNFULFILLED`, moves that axis to `FULFILLED`, and touches no ledger because the two axes evolve independently.

Returning an order, available to the member or to staff, joins both axes to their terminal values and reverses the money. It requires `payment_status` to be `PAID` and `fulfillment_status` to be `FULFILLED`; if either precondition is unmet the return is rejected with `ERR_ORDER_NOT_PAID`. On success `payment_status` becomes `REFUNDED` and `fulfillment_status` becomes `RETURNED`; the member's `store_credit_cents` increases by `total_cents` as a wallet refund; `loyalty_points_balance` decreases by `loyalty_points_earned`; and `lifetime_eligible_spend_cents` decreases by `total_cents`.

### 3.4. Trade-Ins, the Counter Loop, and Consignment

A member submits a trade-in by naming the `member_id`, the `gear_sku_id` of the model being traded in, a `described_condition` of `LIKE_NEW`, `GOOD`, or `WORN`, and a `payout_method` of either `INSTANT_CREDIT` or `CONSIGNMENT` chosen at submit. A new trade-in begins `SUBMITTED`. Its lifecycle then runs through `OFFERED`, `COUNTERED`, `ACCEPTED`, `LISTED`, `SOLD`, and `REJECTED`, with `SOLD` and `REJECTED` terminal.

Staff appraise the item, which moves it from `SUBMITTED` to `OFFERED` and sets `appraised_value_cents`. Appraisal computes two figures from that value: the `instant_credit_cents`, equal to the appraised value multiplied by forty percent and rounded to whole cents, and the informational `consignment_estimate_cents`, equal to the appraised value multiplied by sixty-five percent and rounded to whole cents.

From `OFFERED`, the member responds with an `action`. A `COUNTER` action requires a `counter_cents` value; it moves the trade-in from `OFFERED` to `COUNTERED` and records the member's `member_counter_cents`. Staff may then re-appraise a `COUNTERED` item, which moves it back to `OFFERED` and updates `appraised_value_cents`, recomputing `instant_credit_cents` and `consignment_estimate_cents`; this pair of edges forms the negotiation cycle and may repeat. A response whose `action` is not valid for the current status — or a `COUNTER` submitted without `counter_cents` — is rejected with `ERR_INVALID_OFFER_RESPONSE`.

Also from `OFFERED`, the member may `ACCEPT` or `REJECT`. A `REJECT` moves the trade-in from `OFFERED` to `REJECTED` and closes it with no payout. An `ACCEPT` moves it to `ACCEPTED`, and its effect depends on the chosen `payout_method`. For `INSTANT_CREDIT`, the `payout_cents` is set to the `instant_credit_cents` and that amount is immediately added to the member's `store_credit_cents`. For `CONSIGNMENT`, no wallet change happens yet; instead the item advances immediately from `ACCEPTED` to `LISTED` for resale.

A consignment item is closed out by staff selling it, which is allowed only while the trade-in is `LISTED` and only when `payout_method` is `CONSIGNMENT`. The sale supplies `resale_price_cents`, moves the trade-in from `LISTED` to `SOLD`, sets `payout_cents` to the resale price multiplied by sixty-five percent and rounded to whole cents, and adds that `payout_cents` to the member's `store_credit_cents`. The two payout variants deliberately diverge for the same item: an instant credit pays forty percent of the staff appraisal up front, while a consignment pays sixty-five percent of the actual resale price only once the item sells.

### 3.5. Classes, Trips, Bookings, and the Waitlist

A class or guided trip is created by staff with a `title`, a `category` of `CLASS` or `GUIDED_TRIP`, a scheduled `start_at` and `end_at`, a `capacity` of at least one confirmed seat, and a per-seat `price_cents` of zero or more. A trip begins `SCHEDULED` with `seats_reserved` at zero, `seats_available` equal to its `capacity`, and `waitlist_count` at zero. These three derived counts are reconciled from the trip's bookings on every booking create, cancel, promotion, check-in, and on trip cancel or complete: `seats_reserved` is the number of bookings in `BOOKED` or `CHECKED_IN`, `seats_available` is the capacity minus `seats_reserved` floored at zero, and `waitlist_count` is the number of bookings in `WAITLISTED`.

A booking is created by naming the `member_id`, the `class_trip_id`, and `expected_classtrip_version`. A create is subject, in order, to the trip being `SCHEDULED` (a booking against a non-scheduled trip is rejected with `ERR_TRIP_NOT_SCHEDULED`), to the member's `membership_status` being `ACTIVE` (else `ERR_MEMBERSHIP_INACTIVE`), to a member schedule check, to a fiscal check, and finally — consistent with §2.7 and §2.10 (priority 10) — to the concurrency check of §2.7, which is evaluated last, after all of the preceding business checks and immediately before side effects commit. The schedule check rejects the booking with `ERR_MEMBER_SCHEDULE_CONFLICT` when the member already holds another non-terminal booking on a trip whose closed interval from `start_at` to `end_at` — inclusive of both endpoints — overlaps this trip. The fiscal check requires the member's `store_credit_cents` to be at least the trip's `price_cents`, even for a booking that will land on the waitlist, so that a later promotion can charge it; if the balance is short the booking is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`. Whether a create seats or waitlists is not an error either way: when `seats_available` is at least one the booking is created `BOOKED`, and when `seats_available` is zero it is created `WAITLISTED`. Both outcomes increment the trip's `version` by one. A `BOOKED` create increments `seats_reserved`, sets `price_paid_cents` to the trip's `price_cents`, and debits that amount from the member's `store_credit_cents`. A `WAITLISTED` create increments `waitlist_count` and sets `price_paid_cents` to zero because a waitlisted seat is not charged until it is promoted.

Checking a member in is a staff operation allowed only while the booking is `BOOKED` and the trip is `SCHEDULED` (a check-in when the trip is no longer `SCHEDULED` is rejected with `ERR_TRIP_NOT_SCHEDULED`); it moves the booking from `BOOKED` to `CHECKED_IN` and adds five points to the member's `loyalty_points_balance`. Cancelling a booking is available to the member or to staff while the booking is `BOOKED` or `WAITLISTED`. Cancellation moves the booking to `CANCELLED` and refunds `price_paid_cents` to the member's `store_credit_cents` — which is zero for a waitlisted booking. If the cancelled booking had been `BOOKED`, its seat is released, `seats_reserved` drops by one, and the earliest `WAITLISTED` booking on the same trip by `created_at` ascending is promoted to `BOOKED`: that promoted booking sets `booked_from_waitlist` to true, increases `seats_reserved` by one, decreases `waitlist_count` by one, sets its `price_paid_cents` to the trip's `price_cents`, and debits that price from the promoted member's `store_credit_cents`. If the cancelled booking had been `WAITLISTED`, only `waitlist_count` decreases by one. `CANCELLED` and `NO_SHOW` are terminal booking states.

Trip-level transitions cascade to bookings. Cancelling a trip is allowed only while it is `SCHEDULED` and moves it to `CANCELLED`; every booking still in `BOOKED`, `WAITLISTED`, or `CHECKED_IN` is cascaded to `CANCELLED`, each such cancellation refunds that booking's `price_paid_cents` to its member and reverses any loyalty earned at check-in (removing the five points awarded to a `CHECKED_IN` booking). Completing a trip is allowed only while it is `SCHEDULED` and moves it to `COMPLETED`; every booking still merely `BOOKED` becomes `NO_SHOW` with no refund, while `CHECKED_IN` bookings remain as they are. `CANCELLED` and `COMPLETED` are terminal trip states.

### 3.6. Permit Pools and Passes

A permit allocation is a finite pool created by staff for a `park_name` and a season, defined by `season_start` and `season_end` — the inclusive first and last valid entry dates — a `total_quota` of issuable permits (zero or greater), and a per-permit `price_cents` (zero or greater). A new pool begins with `issued_count` at zero and `available_quota` equal to `total_quota`. The pool's `issued_count` is the number of permits drawn from it — passes that are `ISSUED`, plus those that have since become `EXPIRED` but were once issued, because a drawn permit consumes quota for the whole season — and `available_quota` is `total_quota` minus `issued_count`, floored at zero.

A pass is issued by naming the `member_id`, the `permit_allocation_id` of the pool it draws from, the requested `entry_date`, and `expected_allocation_version`. Issuance is subject, in order, to the member's `membership_status` being `ACTIVE` (else `ERR_MEMBERSHIP_INACTIVE`), to the temporal season check requiring `entry_date` to fall on or after `season_start` and on or before `season_end` (else `ERR_OUTSIDE_SEASON`), to the pool having at least one permit of `available_quota` remaining (else `ERR_QUOTA_EXHAUSTED`), to the member's `store_credit_cents` being at least the pool's `price_cents` (else `ERR_INSUFFICIENT_STORE_CREDIT`), and finally — consistent with §2.7 and §2.10 (priority 10) — to the concurrency check of §2.7, which is evaluated last, after all of the preceding business checks and immediately before side effects commit. On success the pass is created `ISSUED`; the pool's `version` increments by one; `issued_count` increases by one; the pool's `price_cents` is snapshotted onto the pass's own `price_cents`; and the pool's `price_cents` is debited from the member's `store_credit_cents`. As described in §2.9, when the logical clock advances past a pass's `entry_date` by more than one day, the pass moves from `ISSUED` to `EXPIRED` while the pool's `issued_count` stays put. `EXPIRED` is terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, payments, refunds, and staff adjustments — return `200 OK`. Setting the logical clock returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coop/members` | Register a co-op member | Public, StoreStaff |
| GET | `/coop/members/{id}` | Get a member by id | Member, StoreStaff |
| POST | `/coop/members/{id}/store-credit` | Staff store-credit adjustment | StoreStaff |
| POST | `/coop/gear-skus` | Create a gear SKU | StoreStaff |
| GET | `/coop/gear-skus/{id}` | Get a gear SKU by id | Member, StoreStaff |
| POST | `/coop/gear-units` | Register a physical gear unit | StoreStaff |
| GET | `/coop/gear-units/{id}` | Get a gear unit by id | Member, StoreStaff |
| GET | `/coop/gear-units` | List gear units (filter by gear_sku_id, status) | Member, StoreStaff |
| POST | `/coop/rental-agreements` | Quote/create a rental agreement | Member, StoreStaff |
| GET | `/coop/rental-agreements/{id}` | Get a rental agreement by id | Member, StoreStaff |
| GET | `/coop/rental-agreements` | List rental agreements (filter by member_id, gear_unit_id, status) | Member, StoreStaff |
| POST | `/coop/rental-agreements/{id}/pickup` | Pick up a reserved rental | StoreStaff |
| POST | `/coop/rental-agreements/{id}/return` | Return a picked-up rental | StoreStaff |
| POST | `/coop/rental-agreements/{id}/cancel` | Cancel a quoted rental | Member, StoreStaff |
| POST | `/coop/sales-orders` | Create a sales order | Member, StoreStaff |
| GET | `/coop/sales-orders/{id}` | Get a sales order by id | Member, StoreStaff |
| GET | `/coop/sales-orders` | List sales orders (filter by member_id, payment_status) | Member, StoreStaff |
| POST | `/coop/sales-orders/{id}/pay` | Pay an order | Member, StoreStaff |
| POST | `/coop/sales-orders/{id}/fulfill` | Fulfill an order | StoreStaff |
| POST | `/coop/sales-orders/{id}/return` | Return a paid and fulfilled order | Member, StoreStaff |
| POST | `/coop/trade-ins` | Submit a used-gear trade-in | Member |
| GET | `/coop/trade-ins/{id}` | Get a trade-in by id | Member, StoreStaff |
| GET | `/coop/trade-ins` | List trade-ins (filter by member_id, gear_sku_id, status) | Member, StoreStaff |
| POST | `/coop/trade-ins/{id}/appraise` | Staff appraisal / re-appraisal | StoreStaff |
| POST | `/coop/trade-ins/{id}/respond` | Member response: accept, counter, or reject | Member |
| POST | `/coop/trade-ins/{id}/sell` | Complete a consignment resale | StoreStaff |
| POST | `/coop/class-trips` | Create a class or guided trip | StoreStaff |
| GET | `/coop/class-trips/{id}` | Get a class/trip by id | Member, StoreStaff |
| POST | `/coop/class-trips/{id}/cancel` | Cancel a trip (cascade to bookings) | StoreStaff |
| POST | `/coop/class-trips/{id}/complete` | Complete a trip | StoreStaff |
| POST | `/coop/bookings` | Book a member onto a trip | Member, StoreStaff |
| GET | `/coop/bookings/{id}` | Get a booking by id | Member, StoreStaff |
| GET | `/coop/bookings` | List bookings (filter by member_id, class_trip_id, status) | Member, StoreStaff |
| POST | `/coop/bookings/{id}/cancel` | Cancel a booking (promote waitlist) | Member, StoreStaff |
| POST | `/coop/bookings/{id}/check-in` | Check a member in | StoreStaff |
| POST | `/coop/permit-allocations` | Create a permit pool | StoreStaff |
| GET | `/coop/permit-allocations/{id}` | Get a permit allocation by id | Member, StoreStaff |
| POST | `/coop/permit-passes` | Issue a permit pass | Member, StoreStaff |
| GET | `/coop/permit-passes/{id}` | Get a permit pass by id | Member, StoreStaff |
| GET | `/coop/permit-passes` | List permit passes (filter by member_id, permit_allocation_id, status) | Member, StoreStaff |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreStaff, Public |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_GEAR_SKU_NOT_FOUND` | 404 |
| `ERR_GEAR_UNIT_NOT_FOUND` | 404 |
| `ERR_RENTAL_NOT_FOUND` | 404 |
| `ERR_SALES_ORDER_NOT_FOUND` | 404 |
| `ERR_TRADE_IN_NOT_FOUND` | 404 |
| `ERR_CLASS_TRIP_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_PERMIT_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_PERMIT_PASS_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBERSHIP_INACTIVE` | 403 |
| `ERR_UNIT_NOT_READY` | 409 |
| `ERR_UNIT_UNAVAILABLE` | 409 |
| `ERR_UNIT_NOT_RENTABLE` | 422 |
| `ERR_TRIP_NOT_SCHEDULED` | 409 |
| `ERR_MEMBER_SCHEDULE_CONFLICT` | 409 |
| `ERR_OUTSIDE_SEASON` | 422 |
| `ERR_QUOTA_EXHAUSTED` | 409 |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 402 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_OFFER_RESPONSE` | 409 |
| `ERR_ORDER_NOT_PAID` | 409 |
