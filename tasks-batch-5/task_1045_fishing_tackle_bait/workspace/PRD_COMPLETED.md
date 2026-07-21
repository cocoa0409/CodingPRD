# Fishing-Tackle-Bait-Shop API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a full-service fishing, tackle, and bait shop that has outgrown its point-of-sale spreadsheet. The business sells tackle and gear by SKU, issues state fishing licenses across residency and age tiers, books and settles guided charter trips, runs species tournaments with weigh-ins, and takes in rod and reel service and line-spooling jobs — all while running a single loyalty program that spans every counter. Because so many of these activities turn on *when* something happens — whether a license is still in season, whether a guide has enough turnaround time between trips, whether a customer cancels far enough ahead to earn a refund — the platform is built around a server-controlled logical clock so that every window and expiry rule is deterministic and testable.

The API serves five distinct kinds of actor: the walk-in public, registered anglers acting on their own records, front-desk clerks, charter captains (guides) who manage their own trips, and a store manager whose authority is a superset of the clerk's. The sections below fix the global contract every endpoint obeys (Section 2), narrate the business workflows and the calculations behind every dollar figure and loyalty point (Section 3), and close with the consolidated endpoint and error-code references (Sections 4 and 5). Everything an implementer needs is in this document; where a rule naturally belongs to more than one workflow it may be restated from a second angle for reinforcement.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than public self-registration must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. The role value must be one of exactly five recognized strings: `Anonymous`, `Customer`, `ShopClerk`, `Guide`, and `ShopManager`. If either header is missing, or `X-User-Role` is not one of these recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The sole exception is customer self-registration, which the public may call without authentication. When a recognized caller attempts an operation their role is not permitted to perform — or an ownership-scoped role reaches for a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two of the five roles are **entity-backed**, meaning their `X-User-ID` is the identifier of a persisted record and drives ownership checks:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare that resource's `customer_id` to `X-User-ID`. An angler may issue their own licenses, book and pay and cancel their own charter bookings, register and withdraw their own tournament entries, open their own service orders, and read back their own records plus the public catalog.
- When `X-User-Role` is `Guide`, `X-User-ID` is the `id` of the acting `Guide`; ownership checks on any resource that references a `Guide` compare that resource's `guide_id` to `X-User-ID`. A guide may create, reschedule, and cancel their own charters, and check in or complete bookings that sit on their own charters.

The other three roles are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any record's `id`. When `X-User-Role` is `Anonymous`, the caller is an unauthenticated public visitor whose only permitted action is registering a new customer. When `X-User-Role` is `ShopClerk`, the caller is front-desk staff running counter operations (license voids, restocks, check-ins, weigh-ins, service transitions, and the shared create/read operations). When `X-User-Role` is `ShopManager`, the caller is the store manager, a hierarchical superset who may perform every clerk operation plus the manager-exclusive powers (customer suspension and loyalty adjustment, guide creation and suspension, and license-type configuration). Section 4 lists the authorized roles for each endpoint.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and must be at least 0. Results are always returned in ascending order of `created_at` (oldest first). For every list response, the `meta` block carries `limit`, `offset`, `total_count` (the count of all records matching the filter before the limit/offset window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. The Logical Clock and Deterministic Windows

The platform never reads wall-clock time. Instead it maintains a single server-side logical clock that governs every temporal decision: license age-tier and age-requirement evaluation, license season and validity windows, guide turnaround buffers, angler double-booking, charter cancellation refund tiers, and tournament fishing windows. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly advanced it stays at that default rather than ever falling back to real time. A test-driving capability accepts a supplied instant, provided as `to_iso8601`, and advances the clock to it; this capability is available to clerks and managers.

Whenever a rule speaks of "now", "today's date", or "the current time", it means the value of this logical clock. A license's `valid_from` and a tournament weigh-in's `recorded_at`, for example, are both stamped from the clock at the moment of the action.

### 2.5. Common Resource Properties, Versioning, and Optimistic Concurrency

Every resource carries a server-minted `id` (a UUID with no type prefix) and a `created_at` timestamp (ISO 8601 UTC with three fractional digits). Most resources additionally carry an `updated_at` timestamp and an integer `version` that starts at 1 and increments by one on every mutation. Two entities are the exception: `LicenseType` carries only `id` and `created_at` — it has no `updated_at` and no `version`. Every other entity (`Customer`, `Product`, `LicenseSale`, `Guide`, `Charter`, `CharterBooking`, `Tournament`, `TournamentEntry`, `ServiceOrder`) carries the full set. Whenever a mutation changes a resource — including changes driven by a cascade from another entity — that resource's `updated_at` is refreshed and its `version` is incremented.

Rescheduling a charter is guarded by **optimistic concurrency control**. The reschedule request must carry `expected_charter_version`, a non-optional field holding the `version` the client last observed on that charter. Rescheduling has no state precondition that a strictly-later request would trip — a charter may be re-timed from either `OPEN` or `FULL` to any non-overlapping window — so if the charter's `version` has advanced since the client read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to silently overwrite a change the client never saw. Only the charter reschedule endpoint takes a version field; no other endpoint does.

### 2.6. Monetary and Weight Precision

All monetary amounts are stored and returned as integer cents. Where a calculation multiplies by a percentage or prorates by a ratio, the result is rounded **half up** to the nearest whole cent. Calculations that only add or subtract integer cents (license price assembly, service subtotal assembly, provisional charter totals) need no rounding because every input is already an integer. When a single formula rounds at more than one step — as the service order grand total does, rounding the tier discount and then rounding the tax — each rounding step is applied half up independently and in the fixed order stated, and that order is observable in the stored figures. Tournament weights are whole grams throughout.

### 2.7. Loyalty Points and Membership Tiers

Every customer carries three loyalty figures: a spendable `loyalty_points_balance`, a cumulative `lifetime_points_earned`, and a derived `loyalty_tier`, one of `BRONZE`, `SILVER`, or `GOLD`. A new customer starts at zero balance, zero lifetime, and `BRONZE`. Points are earned when a license is issued and when a service order is picked up, and are awarded to a tournament winner at finalize; a manager may also adjust points manually. Both the balance and the lifetime total move up together when points are earned.

The tier is recomputed from `lifetime_points_earned` on every change to that figure. A customer with at least 2,000 lifetime points is `GOLD`; a customer below 2,000 but with at least 500 lifetime points is `SILVER`; anyone below 500 is `BRONZE`. Both thresholds are inclusive — exactly 500 lifetime points is `SILVER`, and exactly 2,000 is `GOLD`. The tier matters downstream because it sets the discount applied to completed charter settlements and to service-order grand totals, described in Section 3.

### 2.8. Cascading State Changes and Consistency

Several operations mutate more than one record. When a manager suspends a customer, every one of that customer's charter bookings that is still `RESERVED` or `WAITLISTED` is cancelled; cancelling a booking that held a seat releases that seat on its charter, which may in turn flip the charter from `FULL` back to `OPEN` and promote a waitlisted booking — a chain up to three hops deep (customer → booking → charter → promoted booking). When a manager suspends a guide, every `OPEN` or `FULL` charter of that guide is cancelled, and each such cancellation cascades to cancel the charter's active bookings and refund those that were paid. Each record touched anywhere in a cascade has its `updated_at` and `version` advanced. All of these effects are applied synchronously and atomically within the triggering request; consistency is immediate.

### 2.9. Validation Order and Error Semantics

When a request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or unrecognized role or id yields `ERR_UNAUTHENTICATED` (401). Authorization is next: a role not permitted for the operation, or an entity-backed role reaching for a resource it does not own, yields `ERR_UNAUTHORIZED` (403). Third, structural validation of the body: required fields present, enum values in range, constrained integers non-negative, and any `end_at` strictly after its `start_at`; a malformed body yields `ERR_VALIDATION` (400). Fourth, existence: every path id and every foreign key in the body is resolved left to right, and the first unresolved reference yields the resource-specific not-found error (HTTP 404) — `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_LICENSE_TYPE_NOT_FOUND`, `ERR_LICENSE_SALE_NOT_FOUND`, `ERR_GUIDE_NOT_FOUND`, `ERR_CHARTER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_TOURNAMENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, or `ERR_SERVICE_ORDER_NOT_FOUND` as appropriate. Fifth, state: the target resource must be in a legal state for the requested transition, otherwise the transition-specific state error applies (see below). Sixth, the optimistic-concurrency version check on charter reschedule (`ERR_STALE_VERSION`, 412). Only after all of these do the domain-specific business rules run — age requirement, season window, guide and angler schedule conflicts, license-held requirement, seat capacity, stock sufficiency, duplicate entry, qualifying-entry gate, and loyalty sufficiency — each carrying its own error, described alongside the workflow it guards in Section 3.

The state-tier error is `ERR_INVALID_STATE` (409) in the general case, but several transitions carry a more specific state error: booking against a charter that is not `OPEN` or `FULL` yields `ERR_CHARTER_NOT_OPEN`; checking a booking in while it is not `PAID` yields `ERR_PAYMENT_REQUIRED`; voiding a license that is already `VOIDED` yields `ERR_ALREADY_VOIDED`; a tournament entry check-in or weigh-in while the tournament is not `IN_PROGRESS` yields `ERR_TOURNAMENT_NOT_IN_PROGRESS`; and any booking or purchase attempted by a suspended customer yields `ERR_CUSTOMER_SUSPENDED`.

## 3. Business Logic & Workflows

### 3.1. Customers, Loyalty, and the Account Lifecycle

Anyone may register as a customer by supplying `full_name`, `email`, `date_of_birth`, and `residency_state`. The `email` is the natural key and must be unique across customers (a duplicate email is rejected with `ERR_VALIDATION`); `date_of_birth` is an ISO date (YYYY-MM-DD) that later drives license age tiers and age-requirement checks, and `residency_state` is the two-letter US state code of residency. A freshly registered account begins `ACTIVE`, with `loyalty_points_balance` and `lifetime_points_earned` at zero and `loyalty_tier` at `BRONZE`. A customer record can be read back by its owner, a clerk, or a manager.

A customer's account status moves between `ACTIVE` and `SUSPENDED`, and only a manager may move it, supplying the desired `status`. Suspending an active account (`ACTIVE → SUSPENDED`) is the root of the depth-three cascade described in Section 2.8: every booking of that customer still in `RESERVED` or `WAITLISTED` is cancelled, releasing held seats, possibly returning charters from `FULL` to `OPEN`, and possibly promoting other customers' waitlisted bookings. Reactivation (`SUSPENDED → ACTIVE`) simply restores the account with no side effects. While a customer is `SUSPENDED`, any attempt by or for them to book a charter or make a purchase is refused with `ERR_CUSTOMER_SUSPENDED`.

Managers may also make a manual loyalty adjustment against a customer, supplying a signed `points_delta` and a `reason`. The delta is added to `loyalty_points_balance`; when the delta is positive it is also added to `lifetime_points_earned`, and either way the tier is recomputed afterward. A deduction may not drive the spendable balance below zero — if it would, the adjustment is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 402).

### 3.2. Products, SKUs, and Inventory

The catalog is built from products, each created by a clerk or manager with a `sku` (unique across products; a duplicate `sku` is rejected with `ERR_VALIDATION`), a `name`, a `category` (one of `TACKLE`, `ROD`, `REEL`, `LINE`, `LIVE_BAIT`, or `MISC`), a `unit_price_cents` that must be zero or greater, and an opening `stock_qty` that must also be zero or greater. A product begins `ACTIVE` and may later be `DISCONTINUED`. Products can be read by anyone with catalog access.

On-hand inventory changes through three paths. A clerk or manager may restock a product by supplying an `add_qty`, which is added to `stock_qty`. Stock is consumed when a spooling service order reaches its ready state (deducting the whole spool units it used), and that same quantity is returned if such an order is later cancelled from the ready state. The stock arithmetic for service orders is detailed in Section 3.8.

### 3.3. Fishing License Configuration and Sales

Only a manager configures a license product, called a **license type**. A license type has no version or `updated_at`; it carries a `code` (for example `CA-ANNUAL-RES`), a `state_code` (the issuing state's two-letter code), a `license_class` of either `RESIDENT` or `NONRESIDENT`, and a `base_price_cents` that is the adult price. Optional age tiers are configured with `youth_max_age` and `youth_price_cents` (a youth qualifies at that age or younger) and `senior_min_age` and `senior_price_cents` (a senior qualifies at that age or older); when the age fields are left null there is no youth or senior tier. A seasonal surcharge is configured with `peak_surcharge_cents` together with a peak window `peak_start_month` and `peak_end_month` (calendar months 1 through 12, inclusive at both ends); when the peak months are null there is no surcharge and `peak_surcharge_cents` defaults to zero. Finally, `min_age` sets the minimum customer age to be issued the license (defaulting to zero), `season_start_date` and `season_end_date` bound the sellable season (inclusive ISO dates), and `validity_days` (which must be greater than zero) is how many days a sold license stays valid counting from its first valid day inclusive.

**Issuing a license.** An angler, clerk, or manager issues a license by supplying just the `customer_id` and the `license_type_id`; everything else is computed at issue. The sale is stamped with an `issued_at` from the logical clock, its `valid_from` is set to the clock's date at issue, and its `valid_until` is the day that is `validity_days` minus one days after `valid_from` (so a 365-day license sold on its first valid day expires 364 days later, inclusive). The sale begins `ACTIVE`, and its `refund_amount_cents` is null until a void computes it.

Before the sale is allowed, two business guards run. The customer's age on `valid_from` must be at least the license type's `min_age`; if the customer is too young the sale is refused with `ERR_AGE_REQUIREMENT_NOT_MET` (HTTP 422). The logical clock's date must also fall on or after `season_start_date` and on or before `season_end_date`; a sale attempted outside that window is refused with `ERR_LICENSE_OUT_OF_SEASON` (HTTP 422).

**Pricing (the `price_paid_cents`).** The price is assembled in two parts. First the age-tier price is selected by computing the customer's age in whole years from `date_of_birth` to `valid_from`: if the type has a youth tier and the age is at or below `youth_max_age`, the youth price applies; otherwise if the type has a senior tier and the age is at or above `senior_min_age`, the senior price applies; otherwise the adult `base_price_cents` applies. Note these are evaluated in that order, so the youth branch is considered before the senior branch. Second, a seasonal surcharge is added: if the type has a peak window and the calendar month of `valid_from` is at or after `peak_start_month` and at or before `peak_end_month`, the `peak_surcharge_cents` is added; otherwise nothing is added. The `price_paid_cents` is the selected tier price plus the surcharge, in whole cents.

**Earning loyalty (the `points_earned`).** At issue the sale earns loyalty points equal to the price paid divided by 100 and rounded down to a whole number of dollars, at a rate of one point per whole dollar. Those `points_earned` are added to the customer's `loyalty_points_balance` and to their `lifetime_points_earned`, and the tier is recomputed.

**Voiding a license.** A clerk or manager may void an active sale (`ACTIVE → VOIDED`); voiding one that is already voided is refused with `ERR_ALREADY_VOIDED`. Voiding computes a `refund_amount_cents` and reverses the loyalty the sale granted: the previously credited `points_earned` are subtracted from both `loyalty_points_balance` and `lifetime_points_earned`, and the tier is recomputed. The refund is a grace-versus-prorated decision keyed on elapsed time. Let elapsed days be the whole number of days from `valid_from` to the clock's current date (never negative). If elapsed days is at most 7, the refund is the full `price_paid_cents`. Otherwise the license is prorated: remaining days are `validity_days` minus elapsed days but never below zero, and the refund is `price_paid_cents` multiplied by remaining days divided by `validity_days`, rounded half up to whole cents. License sales can be read individually and listed with optional filters on `customer_id` and `license_type_id`.

### 3.4. Guides and Charter Scheduling

A guide is created by a manager with a `name` and a `license_no` (the captain's operator license number); the guide begins `AVAILABLE`. A manager may move a guide between `AVAILABLE` and `SUSPENDED` by supplying the desired `status`. Suspending an available guide (`AVAILABLE → SUSPENDED`) cancels each of that guide's `OPEN` or `FULL` charters, which cascades into cancelling and refunding their bookings as described below. Reactivation (`SUSPENDED → AVAILABLE`) has no side effects. A guide record is readable by that guide, a clerk, or a manager.

A charter trip is created by its guide or a manager, referencing the running `guide_id` and supplying a `title`, a `start_at` and `end_at` (ISO 8601 UTC; the end must be strictly after the start), a `capacity` of at least one seat, a `price_per_seat_cents` of zero or greater, and an optional `fuel_surcharge_cents` per seat that defaults to zero. A new charter opens with `status` `OPEN` and `booked_seats` at zero, where `booked_seats` is maintained as the sum of seats over that charter's bookings in `RESERVED`, `CHECKED_IN`, or `COMPLETED`. The charter's status is auto-derived from occupancy: it flips `OPEN → FULL` the moment booked seats reach capacity, and back `FULL → OPEN` whenever a cancellation drops booked seats below capacity (which then triggers waitlist promotion, per Section 3.5).

**Guide turnaround buffer.** A guide may not run two trips back-to-back without breathing room. When a charter is created or rescheduled, its window is compared against every other non-cancelled charter of the same guide, and a required 60-minute turnaround buffer is enforced on both sides of the trip. The request is refused with `ERR_GUIDE_SCHEDULE_CONFLICT` (HTTP 409) when the gap between the two windows is strictly less than 60 minutes; a gap of exactly 60 minutes is allowed. Overlapping windows, having a negative gap, are likewise conflicts.

**Rescheduling.** A guide or manager may reschedule their charter, optionally changing `start_at`, `end_at`, `capacity`, `price_per_seat_cents`, or `fuel_surcharge_cents`, and must supply `expected_charter_version` as described in Section 2.5. A reschedule re-runs the same guide turnaround-buffer check against the new window, and on success updates the fields and increments the charter's `version` by one. If the reschedule changes `capacity`, the charter's status is re-derived from occupancy — `FULL` when `booked_seats` still reaches the new capacity and `OPEN` otherwise — but this re-derivation does not itself run waitlist promotion. A charter may be rescheduled from either `OPEN` or `FULL`. Charters can be read individually and listed with an optional filter on `guide_id`.

**Cancelling a charter.** A guide or manager may cancel a charter that is `OPEN` or `FULL` (`OPEN → CANCELLED` or `FULL → CANCELLED`). Cancellation cancels every booking on the charter that is `RESERVED`, `WAITLISTED`, or `CHECKED_IN`; each such booking that was `PAID` receives a full refund on the shop-initiated path (see Section 3.6). Charter cancellation is terminal.

### 3.5. Charter Bookings: Seats, Waitlist, Payment, and Attendance

A booking is placed by an angler or a clerk, supplying the `charter_id`, the `customer_id`, the number of `seats` requested (at least one), and an optional `waitlist_requested` flag that defaults to false. A booking carries two **independent** status dimensions that evolve separately: an attendance `booking_status` (`RESERVED`, `WAITLISTED`, `CHECKED_IN`, `COMPLETED`, or `CANCELLED`) and a `payment_status` (`UNPAID`, `PAID`, or `REFUNDED`).

Several guards run at booking time, in the priority order of Section 2.9. The target charter must be `OPEN` or `FULL`; a booking against a cancelled charter is refused with `ERR_CHARTER_NOT_OPEN`. The booking's charter window `[start_at, end_at)` must not overlap the window of any other active booking of the same customer; an overlap is refused with `ERR_ANGLER_SCHEDULE_CONFLICT` (HTTP 409). The customer must already hold an `ACTIVE` license whose `[valid_from, valid_until]` range covers the charter's `start_at` date; without such a license the booking is refused with `ERR_LICENSE_REQUIRED` (HTTP 422). Finally, seat availability is checked: the requested seats must be at most the remaining capacity (`capacity` minus `booked_seats`). If they exceed it and `waitlist_requested` is false, the booking is refused with `ERR_INSUFFICIENT_SEATS` (HTTP 409); if `waitlist_requested` is true, the booking is instead created `WAITLISTED` rather than rejected.

A booking that secures its seats is created `RESERVED`, and creating it increments the charter's `booked_seats` by the booked seats, possibly flipping the charter `OPEN → FULL`. A waitlisted booking holds no seat. At create time the booking's `provisional_total_cents` is pinned: it is the gross seat charge, namely the requested `seats` multiplied by the charter's `price_per_seat_cents`, plus the requested `seats` multiplied by the charter's `fuel_surcharge_cents`. The provisional total carries no loyalty discount. At creation `amount_paid_cents` is zero and both `final_total_cents` and `refund_amount_cents` are null.

**Waitlist promotion.** Whenever a charter returns `FULL → OPEN` because seats were released, the system promotes the earliest-created waitlisted booking (by `created_at` ascending) whose `seats` fit within the newly available remaining capacity, moving it `WAITLISTED → RESERVED`. Promotion re-increments the charter's `booked_seats` by that booking's seats and recomputes its `provisional_total_cents`, and because seats were added the charter may immediately flip back `OPEN → FULL`.

**Paying.** An angler or clerk pays a booking, moving the payment dimension `UNPAID → PAID`. Payment is only allowed while the booking is `RESERVED` or `CHECKED_IN` — a cancelled or completed booking cannot be paid. On payment the booking's `amount_paid_cents` is set equal to its `provisional_total_cents`.

**Checking in.** A clerk, or the charter's own guide, checks a booking in, advancing attendance `RESERVED → CHECKED_IN`. Check-in requires that the booking is already `PAID` — an unpaid booking is refused with `ERR_PAYMENT_REQUIRED` — and that the charter is still `OPEN` or `FULL` rather than cancelled. Check-in is the point where the attendance dimension depends on the payment dimension.

**Completing.** After the trip, the charter's guide or a clerk completes a checked-in booking, advancing `CHECKED_IN → COMPLETED`. Completion pins the booking's `final_total_cents` using the final settlement variant: the same gross seat-and-fuel charge as the provisional total, but multiplied by one minus the customer's tier discount, then rounded half up to whole cents. The tier discount is 0% for `BRONZE`, 5% for `SILVER`, and 10% for `GOLD`, so the final total diverges from the provisional total precisely when the customer is not `BRONZE`. Bookings can be read individually and listed with optional filters on `charter_id` and `customer_id`.

### 3.6. Charter Booking Cancellations and Refunds

A booking may be cancelled by its owning angler, a clerk, or a manager, and cancellations also arrive as cascades from customer suspension and charter cancellation. Cancelling a `RESERVED` booking (`RESERVED → CANCELLED`) decrements the charter's `booked_seats` by that booking's seats, and if the charter was `FULL` and now sits below capacity it returns `FULL → OPEN` and promotes the earliest fitting waitlisted booking. Cancelling a `WAITLISTED` booking (`WAITLISTED → CANCELLED`) changes no seat count, because a waitlisted booking never held a seat. A `CHECKED_IN` booking is cancelled only via the charter/guide cancellation cascade (`CHECKED_IN → CANCELLED`), which likewise decrements `booked_seats`.

Whenever a booking that is `PAID` is cancelled, a refund is computed, `refund_amount_cents` is set, and the payment dimension moves `PAID → REFUNDED`. The refund amount depends on who initiated the cancellation. A **shop-initiated** cancellation — a charter cancellation or a guide-suspension cascade — always refunds the full `amount_paid_cents`. A **customer-initiated** cancellation is refunded on a time threshold measured against the charter's `start_at`: compute the hours before start as the difference between `start_at` and the current clock time expressed in hours. If that is at least 48 hours, the refund is the full `amount_paid_cents`; if it is greater than zero but less than 48 hours, the refund is `amount_paid_cents` multiplied by 50%, rounded half up to whole cents; if it is zero or negative (the trip has already started or passed), the refund is zero. An unpaid booking simply cancels with no refund.

### 3.7. Tournaments, Entries, and Weigh-Ins

A tournament is created by a clerk or manager with a `name`, a target `species`, a fishing window `start_at` and `end_at` (ISO 8601 UTC), a `min_qualifying_weight_grams` (zero or greater) that a catch must reach to count, an optional `entry_fee_cents` defaulting to zero, and optional `prize_points` defaulting to zero. A tournament begins `SCHEDULED`. A manager advances the lifecycle by supplying the target `status`: `SCHEDULED → OPEN`, then `OPEN → IN_PROGRESS`, then `IN_PROGRESS → FINALIZED`. A tournament may also be cancelled from `SCHEDULED` (`SCHEDULED → CANCELLED`, no side effects) or from `OPEN` (`OPEN → CANCELLED`), and cancelling an open tournament withdraws every entry that is `REGISTERED`, `CHECKED_IN`, or `WEIGHED`, moving each to `WITHDRAWN`.

Registration is open while the tournament is `OPEN`: an angler or clerk registers by supplying the `tournament_id` and `customer_id`, creating an entry in `REGISTERED`. A customer may not hold two live entries in the same tournament — if they already have an entry in `REGISTERED`, `CHECKED_IN`, `WEIGHED`, or `WINNER`, a second registration is refused with `ERR_DUPLICATE_ENTRY` (HTTP 409). Entries can be read individually and listed with optional filters on `tournament_id` and `customer_id`.

An entry's own lifecycle is driven by supplying a target `status`. An angler or clerk checks an entry in (`REGISTERED → CHECKED_IN`), which is only permitted while the tournament is `IN_PROGRESS`; attempting it otherwise yields `ERR_TOURNAMENT_NOT_IN_PROGRESS`. An entry may be withdrawn from `REGISTERED` or from `CHECKED_IN` (`REGISTERED → WITHDRAWN`, `CHECKED_IN → WITHDRAWN`).

**Weigh-ins.** A clerk records a weigh-in against a checked-in entry — or against an entry that is already `WEIGHED`, which may still receive further weigh-ins — by supplying the `species` and the `weight_grams`. This requires the tournament to be `IN_PROGRESS`, otherwise `ERR_TOURNAMENT_NOT_IN_PROGRESS` applies. Each weigh-in appends an object holding the `species`, the `weight_grams`, and a `recorded_at` stamped from the logical clock onto the entry's append-only `weigh_ins` list. The first qualifying weigh-in advances the entry `CHECKED_IN → WEIGHED` and recomputes the entry's `best_weight_grams`. The `best_weight_grams` of an entry is the maximum weight among its weigh-ins that match the tournament's `species`, are at least the tournament's `min_qualifying_weight_grams`, and whose `recorded_at` falls at or after the tournament `start_at` and at or before its `end_at`; if none qualify, `best_weight_grams` is zero.

**Finalizing and ranking.** Finalizing a tournament (`IN_PROGRESS → FINALIZED`) requires at least one qualifying entry — an entry in `CHECKED_IN` or `WEIGHED` whose `best_weight_grams` is at least the tournament's `min_qualifying_weight_grams`. If no entry qualifies, finalize is refused with `ERR_NO_QUALIFIED_ENTRIES` (HTTP 409). On finalize, the qualifying entries are ranked and each is assigned a one-based `final_rank`: primarily by `best_weight_grams` descending, breaking ties by the earliest qualifying weigh-in's `recorded_at` ascending, and breaking any remaining tie by the entry's `created_at` ascending. The rank-one entry advances `WEIGHED → WINNER`, and its customer is awarded the tournament's `prize_points`: those points are added to the customer's `loyalty_points_balance` and to their `lifetime_points_earned`, and the tier is recomputed.

### 3.8. Rod & Reel Service and Line Spooling

A service order is opened by an angler or a clerk, supplying the `customer_id` who owns the rod or reel, a `service_type` (one of `REEL_REPAIR`, `ROD_REPAIR`, or `SPOOLING`), a `base_service_cents` flat labor base (zero or greater), and — for a spooling job — an optional `product_id` naming the spool-line product to be consumed, an optional `line_price_cents_per_meter`, and an optional `estimated_line_meters`. Pure labor jobs leave `product_id` null. The order opens in `INTAKE`, with `actual_line_meters`, `line_units`, `parts_cents`, and `points_earned` all zero, `stock_consumed` false, and `quoted_cents`, `final_subtotal_cents`, and `grand_total_cents` all null. The workflow is cyclic and is driven by a single transition action that supplies a `to_status`, along with the extra fields noted below where relevant. Orders can be read individually and listed with optional filters on `customer_id` and `product_id`.

The stations of the workflow are as follows. Moving from intake to diagnosis (`INTAKE → DIAGNOSED`) computes and pins the `quoted_cents` from the quoted variant: the `base_service_cents` plus the `estimated_line_meters` multiplied by the `line_price_cents_per_meter`, using estimated meters and excluding parts. From diagnosis the order may advance into the shop (`DIAGNOSED → IN_PROGRESS`), or be sent back for more information (`DIAGNOSED → INTAKE`, which clears `quoted_cents` back to null). Work in progress may be re-diagnosed after a scope change (`IN_PROGRESS → DIAGNOSED`), which recomputes `quoted_cents` from the quoted variant again.

Completing the work moves the order to ready (`IN_PROGRESS → READY`) and is where actual materials are captured: this transition supplies the `actual_line_meters` spooled, the `parts_cents` for any additional parts, and the `line_units` of whole spools drawn from the product's stock. It pins the `final_subtotal_cents` from the final variant: the `base_service_cents` plus the `actual_line_meters` multiplied by the `line_price_cents_per_meter`, plus the `parts_cents`. If `line_units` is greater than zero, the named product must have `stock_qty` of at least `line_units`; if it does not, the transition is refused with `ERR_INSUFFICIENT_STOCK` (HTTP 409). When `line_units` is greater than zero the product's `stock_qty` is decremented by `line_units` and the order's `stock_consumed` flag is set true.

Handing the rod back to the customer moves the order to picked-up (`READY → PICKED_UP`) and computes the `grand_total_cents` in a fixed, observable order from the final subtotal. First take the subtotal, `final_subtotal_cents`. Apply the customer's tier discount — 0% for `BRONZE`, 5% for `SILVER`, 10% for `GOLD` — as a discount amount equal to the subtotal multiplied by the tier percentage, rounded half up; subtract that discount from the subtotal to get the discounted amount. Then apply an 8% sales tax computed as the discounted amount multiplied by 0.08, rounded half up; the grand total is the discounted amount plus that tax. Pickup also credits loyalty: `points_earned` equal to the grand total divided by 100 and rounded down to a whole number (one point per whole dollar) is added to the customer's `loyalty_points_balance` and `lifetime_points_earned`, and the tier is recomputed.

An order may be cancelled from `INTAKE`, `DIAGNOSED`, `IN_PROGRESS`, or `READY` (each to `CANCELLED`). Cancelling from any of the earlier states has no material side effect, but cancelling a `READY` order that already consumed stock (its `stock_consumed` is true) restores the inventory: the product's `stock_qty` is incremented by `line_units` and `stock_consumed` is set back to false. All service transitions are performed by a clerk.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; all other successful operations, including state transitions and reads, return HTTP 200. Request and response bodies are reconstructed from the Section 3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | ShopManager, ShopClerk |
| POST | `/api/customers` | Register a customer | Anonymous, ShopClerk, ShopManager |
| GET | `/api/customers/{id}` | Fetch a customer | Customer, ShopClerk, ShopManager |
| POST | `/api/customers/{id}/status` | Suspend or reactivate a customer | ShopManager |
| POST | `/api/customers/{id}/loyalty-adjustments` | Manual loyalty grant/deduction | ShopManager |
| POST | `/api/products` | Create a product SKU | ShopManager, ShopClerk |
| GET | `/api/products/{id}` | Fetch a product | Customer, ShopClerk, ShopManager |
| POST | `/api/products/{id}/restock` | Increase on-hand stock | ShopClerk, ShopManager |
| POST | `/api/license-types` | Create a license configuration | ShopManager |
| GET | `/api/license-types/{id}` | Fetch a license type | Customer, ShopClerk, ShopManager |
| POST | `/api/license-sales` | Issue a fishing license | Customer, ShopClerk, ShopManager |
| GET | `/api/license-sales/{id}` | Fetch a license sale | Customer, ShopClerk, ShopManager |
| GET | `/api/license-sales` | List license sales | Customer, ShopClerk, ShopManager |
| POST | `/api/license-sales/{id}/void` | Void a license and reverse loyalty | ShopClerk, ShopManager |
| POST | `/api/guides` | Create a guide | ShopManager |
| GET | `/api/guides/{id}` | Fetch a guide | Guide, ShopClerk, ShopManager |
| POST | `/api/guides/{id}/status` | Suspend or reactivate a guide | ShopManager |
| POST | `/api/charters` | Create a charter trip | Guide, ShopManager |
| GET | `/api/charters/{id}` | Fetch a charter | Customer, Guide, ShopClerk, ShopManager |
| GET | `/api/charters` | List charters | Customer, Guide, ShopClerk, ShopManager |
| PUT | `/api/charters/{id}` | Reschedule a charter (OCC on version) | Guide, ShopManager |
| POST | `/api/charters/{id}/cancel` | Cancel a charter and cascade refunds | Guide, ShopManager |
| POST | `/api/charter-bookings` | Book seats on a charter | Customer, ShopClerk |
| GET | `/api/charter-bookings/{id}` | Fetch a booking | Customer, ShopClerk, Guide, ShopManager |
| GET | `/api/charter-bookings` | List bookings | Customer, ShopClerk, Guide, ShopManager |
| POST | `/api/charter-bookings/{id}/pay` | Pay for a booking | Customer, ShopClerk |
| POST | `/api/charter-bookings/{id}/check-in` | Check a booking in | ShopClerk, Guide |
| POST | `/api/charter-bookings/{id}/complete` | Complete a checked-in booking | Guide, ShopClerk |
| POST | `/api/charter-bookings/{id}/cancel` | Cancel a booking and refund if paid | Customer, ShopClerk, ShopManager |
| POST | `/api/tournaments` | Create a tournament | ShopManager, ShopClerk |
| GET | `/api/tournaments/{id}` | Fetch a tournament | Customer, ShopClerk, ShopManager |
| POST | `/api/tournaments/{id}/status` | Advance tournament lifecycle | ShopManager, ShopClerk |
| POST | `/api/tournament-entries` | Register a customer for a tournament | Customer, ShopClerk |
| GET | `/api/tournament-entries/{id}` | Fetch an entry | Customer, ShopClerk, ShopManager |
| GET | `/api/tournament-entries` | List entries | Customer, ShopClerk, ShopManager |
| POST | `/api/tournament-entries/{id}/status` | Check in or withdraw an entry | Customer, ShopClerk |
| POST | `/api/tournament-entries/{id}/weigh-in` | Record a weigh-in | ShopClerk |
| POST | `/api/service-orders` | Open a service or spooling job | Customer, ShopClerk |
| GET | `/api/service-orders/{id}` | Fetch a service order | Customer, ShopClerk, ShopManager |
| GET | `/api/service-orders` | List service orders | Customer, ShopClerk, ShopManager |
| POST | `/api/service-orders/{id}/transition` | Drive the cyclic service workflow | ShopClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_LICENSE_TYPE_NOT_FOUND | 404 |
| ERR_LICENSE_SALE_NOT_FOUND | 404 |
| ERR_GUIDE_NOT_FOUND | 404 |
| ERR_CHARTER_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_TOURNAMENT_NOT_FOUND | 404 |
| ERR_ENTRY_NOT_FOUND | 404 |
| ERR_SERVICE_ORDER_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CHARTER_NOT_OPEN | 409 |
| ERR_PAYMENT_REQUIRED | 409 |
| ERR_ALREADY_VOIDED | 409 |
| ERR_TOURNAMENT_NOT_IN_PROGRESS | 409 |
| ERR_CUSTOMER_SUSPENDED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_AGE_REQUIREMENT_NOT_MET | 422 |
| ERR_LICENSE_OUT_OF_SEASON | 422 |
| ERR_GUIDE_SCHEDULE_CONFLICT | 409 |
| ERR_ANGLER_SCHEDULE_CONFLICT | 409 |
| ERR_LICENSE_REQUIRED | 422 |
| ERR_INSUFFICIENT_SEATS | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_DUPLICATE_ENTRY | 409 |
| ERR_NO_QUALIFIED_ENTRIES | 409 |
| ERR_INSUFFICIENT_POINTS | 402 |
