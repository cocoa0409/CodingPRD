# Truck Parking Reservation Network API — Product Requirements Document

## 1. Introduction

Long-haul trucking runs on the federally mandated hours-of-service clock: when a driver's legal driving window closes, a safe place to park is not a convenience but a compliance requirement, and the scramble for spaces produces sharp, predictable demand peaks around weekly restart cycles. The Truck Parking Reservation Network exists to turn that scarcity into an orderly market. The network operates parking sites whose inventory is split into a reservable pool that drivers can book ahead and a first-come pool held for walk-ins, prices each night dynamically against real occupancy, bundles amenities such as showers and fuel into the stay, and enforces no-show and overstay discipline through a driver standing system.

This document specifies the API through which drivers, fleet managers, site operators, and network administrators interact with the platform. It covers the full lifecycle — site and rate plan configuration, reservation and walk-in booking, waitlist promotion when stalls free up, incident reporting that can degrade or escalate a site's posture, loyalty accrual, and fleet consolidated billing with credit control and collections. All time-dependent behavior is evaluated against a logical clock so that scheduled sweeps (no-show marking, overstay escalation, offer expiry, overdue-invoice cascades) are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their capacity. Five roles exist, spelled exactly as follows: `Anonymous`, `Driver`, `FleetManager`, `SiteOperator`, and `NetworkAdmin`.

Identity semantics differ by role:

- When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting Driver; ownership checks on any resource that references a Driver — bookings, waitlist entries, amenity lines, authorization requests, driver-authored incident reports — compare the resource's driver foreign-key field (such as `driver_id`, or `reporter_driver_id` on incident reports) to `X-User-ID`.
- When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting FleetAccount; ownership checks on fleet-scoped resources (driver authorizations, invoices, the fleet account read itself, and fleet-billed bookings) compare the resource's `fleet_account_id` to `X-User-ID`.
- When `X-User-Role` is `SiteOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `acknowledged_by_user_id` or `resolved_by_user_id` on incident reports) but never compares it to any entity's `id`.
- When `X-User-Role` is `NetworkAdmin`, `X-User-ID` is likewise an opaque operator identifier, not tied to any persisted entity and not compared to any entity's `id`.
- When `X-User-Role` is `Anonymous`, the caller is unauthenticated in the ordinary sense and may do exactly one thing: register a new driver.

A request whose `X-User-Role` header is missing or not one of the declared roles, or whose `X-User-ID` is missing for an entity-backed role (`Driver`, `FleetManager`), is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the endpoint, or that fails an ownership comparison, is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints paginate via two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Network Sweeps

All temporal rules in this document — arrival windows, grace periods, offer expirations, trailing 90-day lookbacks, invoice due dates — are evaluated against a single logical clock, never against wall-clock time. A `NetworkAdmin` advances the logical clock through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. Until the clock is first set, it reads exactly 2026-08-01T00:00:00Z; the logical clock must never fall back to wall-clock time. Advancing the clock is inert by itself: no sweeps run implicitly as a side effect of setting it. State that derives from the passage of time changes only when an operator explicitly triggers a site ops-run (§3.8) or a fleet ops-run (§3.9).

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in the system — sites, stalls, rate plans, amenity products, drivers, fleet accounts, driver authorizations, bookings, booking amenity lines, waitlist entries, incident reports, and invoices — carries a common set of system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer initialized to 1 and incremented by exactly one on every mutation, serving optimistic concurrency control where the API exposes it (§2.9).

"Mutation" is read broadly: explicit client writes and system-driven cascades alike refresh `updated_at` and increment `version` on each resource actually changed. When a rate plan is activated on a site, for example, the site itself is mutated and its `version` advances by one even though the request targeted the plan.

### 2.6. Nested Paths and Resource Parentage

Requests that address nested resources validate path identifiers left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist. A nested resource must also belong to the parent named in the path: a stall addressed under the wrong site, a rate plan addressed under the wrong site, or an amenity product addressed under the wrong site is likewise `ERR_NOT_FOUND`, indistinguishable from a missing id. Parent existence is always settled before any child-scoped or body-scoped validation runs.

### 2.7. The Request Validation Pipeline

Every mutating request passes through an ordered validation pipeline. The first failing check determines the response; once a check fails, no later check is consulted. The order is fixed as follows:

1. Authentication: `X-User-Role` must be present and a declared role, and `X-User-ID` must be present for the entity-backed roles — otherwise `ERR_UNAUTHENTICATED` (401).
2. Authorization and ownership: the role must be permitted on the endpoint, and ownership must hold — a `Driver` acts only where the resource's `driver_id` equals `X-User-ID`, a `FleetManager` only on their own fleet's authorizations, invoices, and account (where `fleet_account_id` equals `X-User-ID`) — otherwise `ERR_FORBIDDEN` (403).
3. Path existence, left to right, including parentage of nested resources — otherwise `ERR_NOT_FOUND` (404).
4. Body shape: required fields present, enum members valid, value types correct, `quantity` at least 1, `cdl_number` not already registered, and a billing-period close having at least one billable member — otherwise `ERR_VALIDATION` (400). Malformed temporal values are deliberately not shape errors: an unparseable `arrival_date` or a `night_count` below 1 surfaces later, at step 8, as `ERR_WINDOW_INVALID`.
5. The target resource's own state machine must permit the transition — check-in only from `BOOKED`, cancellation only from `BOOKED`, waitlist withdrawal only from `QUEUED`, offer acceptance only from `OFFERED`, invoice dispute only from the payable-or-`PAID` set — otherwise `ERR_INVALID_STATE` (409).
6. Optimistic concurrency: `expected_site_version` on rate-plan activation and `expected_booking_version` on booking extension must match the parent's current `version` — otherwise `ERR_STALE_VERSION` (412).
7. Safety gate: the site must not be `ESCALATED` when new inventory is committed — booking creation and waitlist acceptance — otherwise `ERR_SITE_ESCALATED` (409).
8. Window values on booking creation and waitlist joins (all 422): a `RESERVED` arrival before the clock date is `ERR_WINDOW_IN_PAST`; a `WALK_IN` arrival that is not exactly the clock date is `ERR_WALKIN_NOT_TODAY`; a `night_count` above 14 is `ERR_WINDOW_TOO_LONG`; an unparseable `arrival_date` or a `night_count` below 1 is `ERR_WINDOW_INVALID`.
9. Check-in timing (409): before the window opens is `ERR_CHECKIN_WINDOW_NOT_OPEN`; after the grace boundary is `ERR_CHECKIN_GRACE_ELAPSED`.
10. Interval conflicts (409): an overlapping non-terminal booking on the requested stall is `ERR_STALL_WINDOW_CONFLICT`; an extension window that is not free on the booking's own stall is `ERR_EXTENSION_CONFLICT`; an overlapping non-terminal booking already held by the same driver is `ERR_DRIVER_WINDOW_CONFLICT`.
11. Incident reopen timing: reopens outside the permitted window are `ERR_REOPEN_WINDOW_EXPIRED` (409).
12. Driver standing: a `SUSPENDED` driver may not take on new commitments — booking creation, waitlist join, waitlist accept — otherwise `ERR_DRIVER_SUSPENDED` (409).
13. Fleet billing requires an `ACTIVE` DriverAuthorization for the (driver, fleet) pair — otherwise `ERR_DRIVER_NOT_AUTHORIZED` (403) — on booking creation, waitlist joins, and waitlist accepts.
14. The fleet being billed must itself be `ACTIVE` — otherwise `ERR_FLEET_SUSPENDED` (409) — on booking creation, waitlist joins and accepts, and authorization approvals alike.
15. Referential fit (409, `ERR_STALL_NOT_RESERVABLE`): an explicitly requested `stall_id` must belong to the site, match the pool implied by the booking kind, and match the requested class; an amenity product referenced by a new line must belong to the booking's site and be `ACTIVE`.
16. Capacity and uniqueness (409): the stall selector must find an eligible stall (`ERR_SITE_CAPACITY_FULL`), a driver may hold at most one `QUEUED` or `OFFERED` waitlist entry per site (`ERR_DUPLICATE_WAITLIST_ENTRY`), and `stall_number` must be unique within a site (`ERR_DUPLICATE_STALL_NUMBER`).
17. Amenity nightly capacity must hold for every night of the span — otherwise `ERR_AMENITY_CAPACITY_EXCEEDED` (409).
18. Segregation of duties on incident resolution: the resolver must not be the acknowledger — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
19. Fleet fiscal gate: projected exposure must fit within the fleet's credit limit — otherwise `ERR_FLEET_CREDIT_EXCEEDED` (422).
20. Driver fiscal gate: the per-night average of the quote must fit within the driver's spend cap — otherwise `ERR_SPEND_CAP_EXCEEDED` (422).
21. Payment discipline: a payment requires an amount actually due (`ERR_PAYMENT_NOT_DUE`, 409), must not exceed the remaining balance (`ERR_OVERPAYMENT`, 422), and an invoice must be in a payable status (`ERR_INVOICE_NOT_PAYABLE`, 409).

### 2.8. Money, Percentages, and Rounding Discipline

All monetary quantities are integer cents: rates, quotes, subtotals, discounts, fees, payments, balances, credit limits, and caps. Rounding is always round half up, applied only at pinned points. Each night's dynamic rate is rounded to whole cents before any summation; the loyalty discount and the amenity bundle discount are each rounded once at settlement; the overstay hourly rate is rounded once before being multiplied by billable hours; cancellation fees, spend-cap per-night averages, and invoice volume discounts are rounded half up to whole cents. Per-night rates, once pinned on a booking, are never re-rounded or recomputed. Occupancy percentages used for pricing-tier comparisons are compared as exact ratios — no integer or floor division is permitted before the comparison — while percentages reported by the demand forecast are rounded half up to two decimal places.

### 2.9. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency field, because each is legitimate whenever its own preconditions hold, and a client working from an old read could otherwise silently overwrite the effect of an intervening write it never observed:

- Activating a rate plan requires the request to carry `expected_site_version` equal to the site's current `version`. Activation supersedes whatever plan is currently `ACTIVE`; a request still carrying the site version observed before another activation committed would supersede a plan the client never saw, so it is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Extending a booking requires the request to carry `expected_booking_version` equal to the booking's current `version`. An extension is valid whenever the stall is free for the added window, so a second extension built from a stale observed version would legitimately succeed on its own terms yet diverge the booked window from what the client observed; the stale request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; these two constitute the entire optimistic-concurrency surface of the API.

## 3. Business Logic & Workflows

### 3.1. Building the Network: Sites, Stalls, Rate Plans, and the Amenity Catalog

A `NetworkAdmin` onboards a site by supplying its `name` and `base_nightly_rate_cents` — the anchor price per night before any dynamic multiplier — plus optional enforcement knobs: `no_show_grace_minutes` (default 60 minutes after the check-in window opens before a missing arrival is declared a no-show), `overstay_grace_minutes` (default 30 minutes past the checkout deadline before a guest is marked as overstaying), and `cancellation_free_window_hours` (default 24 hours before window open within which cancellation stops being free). Creation initializes the site's `posture` to `NORMAL` and `ops_run_index` to 0, and automatically mints a default rate plan in `ACTIVE` status populated with the catalog constants described in §3.2; this automatic plan does not count as a site mutation, so the new site's `version` remains 1. Later edits to the site configuration — any subset of `name`, `base_nightly_rate_cents`, `no_show_grace_minutes`, `overstay_grace_minutes`, `cancellation_free_window_hours` — affect future quotes only: per-night rates already pinned on existing bookings never move. Each such edit increments the site's `version` by one.

Stalls are the unit of inventory. Each stall carries a `stall_number` unique within its site (a duplicate is refused with `ERR_DUPLICATE_STALL_NUMBER`), a `stall_class` of `STANDARD` or `OVERSIZED`, and an `is_reservable` flag that splits the lot into two pools: reservable stalls can be booked ahead, while non-reservable stalls form the first-come pool served exclusively by walk-ins. New stalls start with `status` `ACTIVE`. The stall list can be filtered by `status` and `is_reservable`.

Stalls occasionally leave service — damage, resurfacing, utility work. A `SiteOperator` (or `NetworkAdmin`) flips a stall between `ACTIVE` and `OUT_OF_SERVICE` by setting its `status`. Taking a stall out of service triggers a reassignment cascade: every `BOOKED` booking on that stall whose check-in window has not yet opened — `checkin_open_at` still in the future — is moved to a replacement stall chosen from those that are `ACTIVE`, in the same pool (`is_reservable`) and `stall_class`, and free for the booking's entire window, with the lowest `stall_number` in lexicographic order winning; the booking's `stall_id` is updated accordingly. When no eligible replacement exists, the booking is cancelled instead — fee waived, `billing_status` `WAIVED` — and a waitlist offer scan runs. `BOOKED` bookings whose check-in window has already opened keep the dead stall, and their check-in attempt then fails with `ERR_STALL_OUT_OF_SERVICE`; guests already on site (`CHECKED_IN`, `OVERSTAY`) are not displaced. Returning a stall to `ACTIVE` has no cascading effects.

Rate plans express the site's dynamic-pricing curve. Beyond the automatic default, a `NetworkAdmin` may draft additional plans; every field defaults to its catalog constant — `tier2_pct` 60, `tier3_pct` 80, `tier4_pct` 95, `mult_low` 0.9, `mult_mid` 1.0, `mult_high` 1.25, `mult_max` 1.5, `peak_multiplier` 1.2, and `peak_days` of Friday and Saturday — and each may be overridden at creation. A plan is born `DRAFT`. The lifecycle is driven through a transition request whose `to` field names the target state. Activation — `to` equal to `ACTIVE`, carrying the optimistic-concurrency field described in §2.9 — moves the plan `DRAFT` → `ACTIVE`, flips the site's previously `ACTIVE` plan to `SUPERSEDED`, and increments the site `version` by one; exactly one plan is `ACTIVE` per site at all times. Supersession never disturbs history: existing bookings keep their pinned `per_night_rates`, and only future quotes read the new plan. Retirement — `to` equal to `RETIRED` — is permitted for `DRAFT` or `SUPERSEDED` plans and lands the plan in the terminal `RETIRED` state; retiring the currently `ACTIVE` plan is rejected with `ERR_INVALID_STATE`, because a replacement must be activated first — activation supersedes it, after which it may be retired. The rate-plan list accepts a `status` filter.

The amenity catalog is per site. Each product has a `code` — one of `SHOWER`, `FUEL`, `WIFI`, or `POWER`, unique within the site — a display `name`, a `price_cents` list price per unit per night, and an optional `nightly_capacity` capping how many units the site can serve per night (null means uncapacitated). Products start `ACTIVE`. Updating `price_cents` or `nightly_capacity` affects only lines added afterwards; existing lines keep their pinned `unit_price_cents`. Discontinuing a product moves it to the terminal `DISCONTINUED` state: existing `BookingAmenity` lines are unaffected, but attempts to add new lines against the discontinued product are rejected with `ERR_INVALID_STATE`.

### 3.2. Dynamic Nightly Pricing, Availability, and Demand Forecasting

Every quoted night is priced individually against the site's unique `ACTIVE` rate plan. For a night with arrival date d, the system first computes reservable-pool occupancy: among stalls that are `ACTIVE` and `is_reservable`, it counts the distinct stalls occupied by a booking in `BOOKED`, `CHECKED_IN`, or `OVERSTAY` status whose half-open stay interval — from `checkin_open_at` to `checkout_due_at` — overlaps the night's interval, which runs from 15:00:00Z on d to 11:00:00Z the following day. The occupancy percentage is one hundred times that occupied count divided by the total number of reservable `ACTIVE` stalls, and it is compared as an exact ratio — integer or floor division before the comparison is forbidden. A booking in the act of being quoted does not count itself.

The occupancy percentage selects a multiplier from the plan: below `tier2_pct` the night takes `mult_low`; from `tier2_pct` up to but not including `tier3_pct` it takes `mult_mid`; from `tier3_pct` up to but not including `tier4_pct` it takes `mult_high`; and at or above `tier4_pct` it takes `mult_max`. Tier boundaries are inclusive on the left — with the default plan, occupancy of exactly 60 percent already triggers `mult_mid`. Surge suppression applies to degraded sites: when the site `posture` is `DEGRADED` (§3.8), the occupancy multiplier for new quotes is capped at 1.00 even where the tier table would yield more. Independently, hours-of-service restart demand is priced in: when the UTC weekday of the night's arrival date falls within the plan's `peak_days` — Friday and Saturday by default — the plan's `peak_multiplier` applies; any other weekday takes a factor of 1.0. The night's rate is the site's `base_nightly_rate_cents` multiplied by the occupancy multiplier and by the peak factor, rounded half up to whole cents, and each night is rounded individually before any summation. This per-night pricing runs identically for each requested night at booking creation, for each added night of an extension, and for each night of a waitlist promotion.

Real-time availability is reported per pool for a caller-supplied window: `window_start` and `window_end` default to the current instant and the next 11:00:00Z turnover when omitted, and a window whose start is not before its end is rejected with `ERR_WINDOW_INVALID`. The response reports `reservable_total`, `reservable_free`, `first_come_total`, and `first_come_free` for the requested window.

The capacity forecast answers a different question — how full will a given night be — in two variants, both returned for a required `date` parameter. Let total stalls be the count of `ACTIVE` stalls across both pools. The confirmed variant counts the distinct stalls holding a booking in `BOOKED`, `CHECKED_IN`, or `OVERSTAY` whose occupancy interval covers the queried night, and reports `confirmed_occupied_stalls` together with `confirmed_occupancy_pct` (one hundred times that count divided by total stalls, rounded half up to two decimal places). The committed variant layers waitlist demand on top: each `QUEUED` entry whose arrival window covers the night weighs one half, each `OFFERED` entry weighs one quarter, and the resulting `committed_weighted_demand` — confirmed occupied stalls plus the weighted waitlist sum — produces `committed_occupancy_pct` by the same rounding. Entries in `WITHDRAWN`, `EXPIRED`, or `PROMOTED` status are excluded, the last because a promoted entry has already materialized as a booking and is counted there. The confirmed variant serves conservative capacity planning; the committed variant, which is strictly greater whenever any waitlist demand exists for the night, serves revenue forecasting. The response also echoes the queried `date`.

### 3.3. Drivers: Standing, Strikes, and the Loyalty Program

Anyone may register a driver — it is the one operation open to `Anonymous` — by supplying a globally unique `cdl_number` (a duplicate fails with `ERR_VALIDATION`) and a `full_name`. A new driver starts with `standing` of `GOOD`, `loyalty_tier` of `STANDARD`, an empty `strike_events` log, and zeroed counters. Reading a driver exposes all computed fields; a `Driver` may read only their own record, while `FleetManager`, `SiteOperator`, and `NetworkAdmin` may read any.

Discipline is tracked through `strike_events`, an append-only log whose entries each record the instant `at`, the `kind` — `NO_SHOW` weighing one strike, `EVICTION` weighing two — and the originating `booking_id`. The `strikes_90d` counter sums the weights of entries whose `at` falls on or after the clock minus 90 days. Standing derives from it: `strikes_90d` of 3 or more means `SUSPENDED`, exactly 2 means `PROBATION`, and anything less means `GOOD`. A `SUSPENDED` driver cannot create bookings, join waitlists, or accept waitlist offers — each attempt is rejected with `ERR_DRIVER_SUSPENDED` — and the moment a driver crosses into `SUSPENDED`, a cascade cancels their not-yet-open bookings (§3.5).

Loyalty runs on settled nights. The `settled_nights_90d` counter sums the `night_count` of the driver's bookings whose `billing_status` is `PAID` and whose `checked_out_at` falls on or after the clock minus 90 days. Tier thresholds are inclusive: at least 12 settled nights earns `SILVER`, at least 30 earns `GOLD`, and at least 60 earns `PLATINUM`; below that the driver is `STANDARD`. At settlement the tier discounts the parking subtotal — 5 percent for `SILVER`, 10 percent for `GOLD`, 15 percent for `PLATINUM` — with `STANDARD` receiving no discount.

Separately, the loyalty points ledger credits `loyalty_points_balance` with 10 points per booked night each time one of the driver's bookings reaches `billing_status` `PAID`, whether the driver paid directly or a fleet invoice covering the booking was paid in full. If a booking that had reached `PAID` later moves to `WAIVED` — through an invoice write-off, for example — the same 10 points per night are clawed back; the balance is allowed to go negative and has no floor. The ledger invariant is exact: the balance always equals ten points per night across bookings that reached `PAID`, minus ten points per night across bookings that were waived after having been paid.

### 3.4. Creating a Booking: Reservations, Walk-Ins, and Fleet Billing

A `Driver` creates a booking for themselves: the payload's `driver_id` must equal the caller's `X-User-ID`, along with `site_id`, a `booking_kind` of `RESERVED` or `WALK_IN`, an `arrival_date` in YYYY-MM-DD form, a `night_count`, a `payment_mode`, and optionally `stall_id` and `stall_class`. The booking's window derives from these inputs: `checkin_open_at` is 15:00:00Z on `arrival_date`, and `checkout_due_at` is 11:00:00Z on the day `night_count` nights later. Creation requires an `ACTIVE` rate plan at the site — which always exists, since site creation mints one and the active plan can never be retired directly. Creation also refuses to commit inventory against an `ESCALATED` site (`ERR_SITE_ESCALATED`) or for a `SUSPENDED` driver (`ERR_DRIVER_SUSPENDED`).

Window discipline comes next. A `RESERVED` booking's `arrival_date` must not fall before the clock date (`ERR_WINDOW_IN_PAST`); a `WALK_IN` booking's `arrival_date` must equal the clock date exactly (`ERR_WALKIN_NOT_TODAY`); a `night_count` above 14 is rejected with `ERR_WINDOW_TOO_LONG`; an unparseable `arrival_date` or a `night_count` below 1 is rejected with `ERR_WINDOW_INVALID`. Two bookings on the same stall may never overlap in time — intervals are half-open, so the daily 11:00Z-to-15:00Z turnover gap makes same-day back-to-back stays legal — and an overlapping non-terminal booking on the requested stall is `ERR_STALL_WINDOW_CONFLICT`. The same driver may not hold two overlapping non-terminal bookings anywhere (`ERR_DRIVER_WINDOW_CONFLICT`).

Unless the caller pins a specific `stall_id`, the stall selector assigns one. Eligible stalls are `ACTIVE`, belong to the pool implied by `booking_kind` — reservable stalls for `RESERVED`, first-come stalls for `WALK_IN` — match the requested `stall_class` (`STANDARD` when unspecified), and are free of any booking in `BOOKED`, `CHECKED_IN`, or `OVERSTAY` status overlapping the requested window. Among the eligible stalls the winner is the smallest `stall_number` in lexicographic order; because `stall_number` is unique per site, no further tie-break exists. An explicitly supplied `stall_id` is validated against the same pool, class, and site rules, with mismatches rejected as `ERR_STALL_NOT_RESERVABLE` and window conflicts as `ERR_STALL_WINDOW_CONFLICT`. When the eligible set is empty, creation fails with `ERR_SITE_CAPACITY_FULL` for both kinds.

Payment mode decides who pays. `DRIVER_DIRECT` bookings are settled by the driver at checkout; `FLEET_BILL` bookings require `fleet_account_id` — which is forbidden on `DRIVER_DIRECT` — plus an `ACTIVE` DriverAuthorization for the (driver, fleet) pair (`ERR_DRIVER_NOT_AUTHORIZED`) and an `ACTIVE` fleet (`ERR_FLEET_SUSPENDED`). Two fiscal gates then apply, both evaluated against the provisional quote: the fleet's projected exposure — its `current_balance_cents`, plus for each of the fleet's `FLEET_BILL` bookings still `UNBILLED` the `final_total_cents` where set and otherwise the `quoted_total_cents`, plus this booking's `quoted_total_cents` — must be at most the fleet's `credit_limit_cents`, with equality allowed and any excess rejected as `ERR_FLEET_CREDIT_EXCEEDED`; and when the authorization carries a non-null `spend_cap_per_night_cents`, the quote divided by `night_count`, rounded half up, must be at most the cap, otherwise `ERR_SPEND_CAP_EXCEEDED`.

A successful `RESERVED` creation lands in `BOOKED` with `billing_status` `UNBILLED` — every new booking starts `UNBILLED` — and with its `per_night_rates` pinned — a list pairing each night's date with its dynamically priced `rate_cents` — and a provisional `quoted_total_cents` equal to the parking subtotal minus the loyalty discount at the driver's creation-time tier, with no amenity or fee components. A `WALK_IN` creation instead lands directly in `CHECKED_IN`, with check-in implicit in the walk-in act, and pins every night at the flat `base_nightly_rate_cents`: walk-ins receive no occupancy or peak multiplier, no loyalty discount, and no bundle discount at settlement. Bookings a driver never showed for, system-cancelled bookings, and stays in progress are all reachable through the booking list, which filters on `driver_id`, `site_id`, `stall_id`, `waitlist_entry_id`, `fleet_account_id`, `status`, and `billing_status`; a `Driver` sees only their own bookings, while a `FleetManager` sees the fleet-billed bookings of their own fleet.

### 3.5. The Stay Itself: Check-In, Extension, Settlement, and Enforcement

A booking's lifecycle runs from `BOOKED` (or, for walk-ins, directly from `CHECKED_IN`) toward one of four terminal states — `CHECKED_OUT`, `NO_SHOW`, `CANCELLED`, or `EVICTED`. Its billing dimension runs in parallel, from `UNBILLED` toward the terminal `PAID` or `WAIVED` (passing through `PARTIALLY_PAID` or `INVOICED` along the way), and the two dimensions evolve independently: a lifecycle-terminal booking still moves along `billing_status` as its fees are paid, invoiced, or waived.

Checking in moves a booking `BOOKED` → `CHECKED_IN`. The driver may check in no earlier than `checkin_open_at` (earlier attempts are `ERR_CHECKIN_WINDOW_NOT_OPEN`) and no later than `checkin_open_at` plus the site's `no_show_grace_minutes`, with the late boundary inclusive — a check-in at exactly that instant still succeeds, while anything strictly later is `ERR_CHECKIN_GRACE_ELAPSED` if the ops sweep has not already marked the booking. The assigned stall must still be `ACTIVE`; a stall taken out of service after its booking's window opened rejects check-in with `ERR_STALL_OUT_OF_SERVICE`. A successful check-in stamps `checked_in_at` with the current clock and increments the booking's `version` by one.

Extending a booking is a self-transition on `BOOKED` that mutates the window. The request carries `added_nights` and the `expected_booking_version` guard of §2.9; the stall must be free for the whole extension window (`ERR_EXTENSION_CONFLICT`, which also covers an extension that would push the total beyond 14 nights). The added nights are priced at the current dynamic rate and appended to `per_night_rates`, `night_count` and `checkout_due_at` grow by `added_nights` nights and days respectively, `quoted_total_cents` is recomputed, and the booking's `version` increments.

Cancelling is a driver action on `BOOKED` bookings. At or before `checkin_open_at` minus the site's `cancellation_free_window_hours` — an inclusive boundary — cancellation is free: `fee_cents` is 0 and `billing_status` becomes `WAIVED`. Inside the window, the cancellation fee is half of the first pinned night's rate, rounded half up; `final_total_cents` is set to that fee and `billing_status` remains `UNBILLED`, leaving the fee to be collected. Either way the stall is released for the booking's window and a waitlist offer scan runs at the site. Cancellations issued by the system itself — the fleet-overdue cascade, a fleet closure, the driver-suspension cascade, or a failed stall reassignment — never charge: `fee_cents` and `final_total_cents` are both 0 and `billing_status` becomes `WAIVED`, again releasing the stall and scanning the waitlist.

The no-show sweep is stricter than the check-in boundary suggests: a booking still `BOOKED` once the clock is strictly later than `checkin_open_at` plus `no_show_grace_minutes` becomes `NO_SHOW`. The fee is the full first pinned night's rate, never discounted, and `final_total_cents` equals it while `billing_status` stays `UNBILLED`. The stall is released for the original window, a waitlist offer scan runs, and a `NO_SHOW` strike of weight one is appended to the driver's `strike_events` with standing recomputed. If the recomputed `strikes_90d` reaches at least 3, the driver's `standing` becomes `SUSPENDED` and every other `BOOKED` booking of that driver whose `checkin_open_at` is still in the future is cancelled with `fee_cents` 0 and `billing_status` `WAIVED`, each releasing its stall and triggering its own waitlist offer scan.

A booking still `CHECKED_IN` once the clock passes strictly beyond `checkout_due_at` plus `overstay_grace_minutes` is marked `OVERSTAY` by the site ops-run, stamping `overstayed_at`. If the clock has also passed strictly beyond four hours past that same grace boundary and `incident_escalated` is still false, the sweep auto-creates an incident report with `category` `SECURITY`, `severity` `HIGH`, the offending `booking_id`, a null `reporter_driver_id`, and `status` `OPEN`, then sets `incident_escalated` to true so it happens once; site posture is recomputed, though a single `HIGH` incident alone never escalates a site.

Checking out — from either `CHECKED_IN` or `OVERSTAY` — moves the booking to `CHECKED_OUT`, stamps `checked_out_at`, and runs final settlement in a pinned order. First, `parking_subtotal_cents` is the sum of the pinned `per_night_rates`, each element already rounded when pinned. Second, the loyalty percentage is read from the driver's tier at settlement time — 15 for `PLATINUM`, 10 for `GOLD`, 5 for `SILVER`, 0 for `STANDARD` — which may differ from the tier used for the creation-time quote; `WALK_IN` bookings always take 0. Third, `discount_cents` is the parking subtotal times that percentage, divided by one hundred and rounded half up, and the parking net is the subtotal minus the discount. Fourth, the amenity subtotal sums `unit_price_cents` times `quantity` times `night_count` over lines in `RESERVED` or `FULFILLED` status, excluding `CANCELLED` lines. Fifth, when the lines in that sum span at least two distinct product codes, the bundle discount is 10 percent of the amenity subtotal rounded half up — always 0 for `WALK_IN` — and `amenity_net_cents` is the subtotal minus it. Sixth, `fee_cents` carries the overstay penalty for an `OVERSTAY` checkout, the cancellation or no-show fee where one applies, and 0 otherwise; fees are never discounted. Seventh, `final_total_cents` is the parking net plus `amenity_net_cents` plus `fee_cents`. The provisional quote and the final settlement therefore diverge whenever the driver's tier moved, amenity lines exist, or fees accrued. After checkout the `billing_status` remains `UNBILLED`, the stall is released at the checkout instant, and a waitlist offer scan runs.

The overstay penalty itself is computed from whole minutes: the minutes from `checkout_due_at` plus `overstay_grace_minutes` until `checked_out_at`, floored at zero. Each started hour bills — the minute count divided by 60 is rounded up to a whole hour, so zero minutes bills zero hours — and the hourly rate is one and a half times the last pinned night's rate divided by 20, rounded half up once. The penalty is billable hours times that hourly rate.

Eviction is the forced variant: a `SiteOperator` checks out an `OVERSTAY` booking with `force` set to true, moving it to `EVICTED`. Settlement is identical to a normal checkout including the full overstay penalty, but an `EVICTION` strike of weight two is appended to the driver's `strike_events`, standing is recomputed, and the driver-suspension cascade applies if `strikes_90d` reaches at least 3; the stall is released and a waitlist offer scan runs.

Direct payment applies to `DRIVER_DIRECT` bookings once `final_total_cents` exists. Paying less than the remaining balance moves `billing_status` to `PARTIALLY_PAID` and adds the `amount_cents` to `paid_cents`; paying exactly the remaining balance moves it to `PAID`, sets `paid_cents` equal to `final_total_cents`, and credits the loyalty ledger with 10 points per `night_count`, recomputing `settled_nights_90d` and the tier. Paying more than the remainder is `ERR_OVERPAYMENT`, and paying when nothing is due — billing already `PAID` or `WAIVED`, a `FLEET_BILL` booking, or no final total yet — is `ERR_PAYMENT_NOT_DUE`.

### 3.6. Amenity Bundles and Nightly Capacity

While a booking is `BOOKED` or `CHECKED_IN`, its driver may attach amenity lines by naming an `amenity_product_id` and an optional `quantity` (default 1, and always at least 1 — anything less is `ERR_VALIDATION`). The product must belong to the booking's site and still be `ACTIVE`; a foreign or discontinued product is rejected with `ERR_STALL_NOT_RESERVABLE`. Each new line starts `RESERVED` with `unit_price_cents` pinned from the product's `price_cents` at add time, so later catalog repricing never reaches existing lines. Attempting to add a line to a booking in any other lifecycle state is an invalid transition (`ERR_INVALID_STATE`).

Capacitated products — those with a non-null `nightly_capacity` — are checked night by night across the booking's whole span, from `arrival_date` through `night_count` nights. For each night, consumption is the total `quantity` across lines in `RESERVED` or `FULFILLED` status for the same product whose owning booking's night span covers that night, excluding lines whose booking is `CANCELLED` or `NO_SHOW`. The add is allowed only when consumption plus the new `quantity` is at most `nightly_capacity` for every night of the span — landing exactly on the capacity is permitted — and any single night that would overflow rejects the whole add with `ERR_AMENITY_CAPACITY_EXCEEDED`.

Fulfillment is the operator's acknowledgment that a line was delivered: a `SiteOperator` moves a `RESERVED` line to `FULFILLED`, but only while the owning booking is `CHECKED_IN` or `OVERSTAY`. The driver may instead cancel a `RESERVED` line while the booking is `BOOKED` or `CHECKED_IN`; cancellation moves it to `CANCELLED` and releases its nightly capacity consumption for every night of the booking span. Both fulfillment and cancellation against a line whose booking sits in a disallowed state are `ERR_INVALID_STATE`. Lines can be browsed through a list endpoint filtered by `booking_id`, `amenity_product_id`, or `status`.

The commercial payoff is the bundle discount at settlement (§3.5): when a stay's non-cancelled lines span at least two distinct product codes, the amenity subtotal is discounted by 10 percent. `WALK_IN` stays always pay full list price.

### 3.7. The Waitlist: Queues, Offers, and Promotion

When a site's reservable pool is sold out for a window, a driver may join the waitlist with their own `driver_id`, the `site_id`, the desired `arrival_date` and `night_count`, a `stall_class`, and a `payment_mode` — with `fleet_account_id` required exactly when the mode is `FLEET_BILL`. The same window discipline as booking creation applies (arrival not before the clock date, one to fourteen nights), the driver must not be `SUSPENDED`, fleet-billed entries are authorized and credit-checked at join and then re-authorized and re-checked at accept time, and a driver may hold at most one `QUEUED` or `OFFERED` entry per site — a second active entry is `ERR_DUPLICATE_WAITLIST_ENTRY`. A new entry starts `QUEUED`.

Offers are a system act, never a client call. Any stall release at a site — a cancellation, a no-show, a checkout, an eviction, or a failed reassignment — triggers an offer scan. Candidates are the site's `QUEUED` entries whose driver is not `SUSPENDED`, whose `stall_class` matches the freed stall, and whose whole requested window — from 15:00:00Z on the arrival date to 11:00:00Z after the last night — the freed stall can cover. Candidates rank by loyalty tier descending (`PLATINUM` above `GOLD` above `SILVER` above `STANDARD`), ties broken by `created_at` ascending; that timestamp is the only tie-break and an entry `id` must never be used. The winner moves `QUEUED` → `OFFERED` with `offered_stall_id` pinning the freed stall and `offer_expires_at` set 30 minutes out. When no candidate qualifies, the stall simply returns to general reservable inventory without error.

Acceptance is the driver's: the entry must be `OFFERED` and belong to the caller, the clock must be at or before `offer_expires_at` — an inclusive boundary, with later attempts rejected `ERR_OFFER_EXPIRED` if the sweep has not already expired the entry — the site must not be `ESCALATED` (`ERR_SITE_ESCALATED`), and the driver must not be `SUSPENDED`. For `FLEET_BILL` entries the authorization, fleet status, spend-cap, and credit checks all re-run against the fresh quote, and the interval rules re-apply as well: the pinned stall must still be free of overlapping non-terminal bookings for the entry's window (`ERR_STALL_WINDOW_CONFLICT`), and the driver must not hold an overlapping non-terminal booking elsewhere (`ERR_DRIVER_WINDOW_CONFLICT`). Acceptance moves the entry `OFFERED` → `PROMOTED` and materializes a booking with `booking_kind` `RESERVED`, the offered stall as its `stall_id`, its `waitlist_entry_id` pointing back at the entry, the entry's window, per-night rates quoted at the current dynamic rate, and status `BOOKED`.

An offer left standing dies in the ops sweep: once the clock is strictly past `offer_expires_at`, the entry becomes `EXPIRED` and the pinned stall is immediately re-offered to the next selector winner, if any. A driver may also withdraw, but only from `QUEUED`; withdrawing an `OFFERED` entry is an invalid transition (`ERR_INVALID_STATE`), since the offered stall is already pinned. The waitlist list filters on `driver_id`, `site_id`, `fleet_account_id`, `offered_stall_id`, and `status`.

### 3.8. Incident Reports and Site Posture

Drivers and site staff report what they see: an incident report carries the `site_id`, a `category` of `SECURITY`, `LIGHTING`, or `FACILITY`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a free-text `description`. When the reporter is a `Driver`, `reporter_driver_id` is their own id; when a `SiteOperator` files the report it stays null. Overstay auto-incidents (§3.5) instead carry the offending `booking_id` with a null reporter. New reports open as `OPEN`, and every incident creation or transition recomputes the site's posture.

The working lifecycle runs `OPEN` → `ACKNOWLEDGED` → `INVESTIGATING` → `RESOLVED`, each step taken by a `SiteOperator` through a transition request whose `to` field names the target state (`ACKNOWLEDGED`, `INVESTIGATING`, `RESOLVED`, or `REOPENED` for operators; `DISMISSED` is reserved to `NetworkAdmin`). Acknowledgment records `acknowledged_by_user_id` from the caller's `X-User-ID`. Resolution is segregated: the resolver's `X-User-ID` must differ from `acknowledged_by_user_id`, otherwise the transition is rejected with `ERR_SEGREGATION_OF_DUTIES`; a valid resolution stamps `resolved_by_user_id` and `resolved_at`. A resolved report is not necessarily final — within 72 hours of `resolved_at`, inclusive, a `SiteOperator` may move it to `REOPENED`, incrementing `reopened_count`, after which it flows back through `INVESTIGATING` to a fresh `RESOLVED`; the cycle may repeat while the reopen window holds, and a reopen attempted strictly after the window is `ERR_REOPEN_WINDOW_EXPIRED`. From `OPEN`, `ACKNOWLEDGED`, or `INVESTIGATING`, a `NetworkAdmin` may instead dismiss the report outright as `DISMISSED`. Both `RESOLVED` and `DISMISSED` are terminal. The incident list filters on `site_id`, `reporter_driver_id`, `booking_id`, `category`, and `status`.

Posture is derived, never set directly. Consider the site's non-terminal incidents — those in `OPEN`, `ACKNOWLEDGED`, `INVESTIGATING`, or `REOPENED`. Any `CRITICAL` among them puts the site in `ESCALATED`; otherwise, at least three `LIGHTING` incidents in that set put it in `DEGRADED`; otherwise the site is `NORMAL`. An `ESCALATED` site that clears its `CRITICAL` incidents but still has at least three open `LIGHTING` reports settles into `DEGRADED`, and a site returns to `NORMAL` once neither condition holds. The consequences differ by level: `ESCALATED` blocks new booking creation and waitlist acceptance with `ERR_SITE_ESCALATED` while leaving existing bookings and check-ins untouched; `DEGRADED` suppresses surge pricing by capping the occupancy multiplier at 1.00 for new quotes (§3.2). Posture is recomputed on every incident mutation and on every site ops-run.

The site ops-run is the operator-driven heartbeat, available to `SiteOperator` and `NetworkAdmin`. Each run executes its sweeps in a pinned order: first the no-show sweep, then overstay marking, then overstay escalation (the four-hour auto-incident), then waitlist offer expiry with re-offer, and finally the posture recompute. Each run increments the site's `ops_run_index` by one, giving operators a monotonic audit counter that started at 0.

### 3.9. Fleet Accounts: Authorization, Invoicing, and Collections

A `NetworkAdmin` opens a fleet account with a `company_name`, a `credit_limit_cents` bounding total exposure, and an optional `payment_terms_days` (default 30) measured from period end to invoice due date. New accounts start `ACTIVE` with a zero balance. The `current_balance_cents` is always derived: the sum, over every invoice whose status is not `WRITTEN_OFF`, of `net_cents` minus `paid_cents`. Separately, `credit_cents` accumulates refunded credit from written-off invoices that had collected payments; it is informational and never negative.

Billing a fleet is a privilege a driver must first request. The driver creates an authorization naming their own `driver_id`, the `fleet_account_id`, and optionally a `spend_cap_per_night_cents` (null means uncapped); it starts `PENDING`. The fleet's manager then drives the lifecycle through a transition request whose `to` field names the target state (`ACTIVE`, `REJECTED`, `SUSPENDED`, or `REVOKED`): `PENDING` → `ACTIVE` approves it — permitted only while the fleet itself is `ACTIVE`, else `ERR_FLEET_SUSPENDED` — or `PENDING` → `REJECTED` refuses it. An `ACTIVE` authorization can be suspended in two ways that matter later: a manual `FleetManager` suspension leaves `auto_suspended` false, while the fleet cascade sets it true. Suspension by cascade also cancels every `BOOKED` fleet-billed booking of that driver on that fleet whose `checkin_open_at` is still in the future, waiving fees and moving each to `WAIVED` billing with stalls released and waitlist scans run. Reactivation (`SUSPENDED` → `ACTIVE`) happens only from the fleet reactivation sweep and only when `auto_suspended` is true — manual suspensions never auto-restore — and it clears the flag back to false. From `PENDING`, `ACTIVE`, or `SUSPENDED`, the manager may revoke the authorization outright, and closing the fleet revokes every non-terminal authorization automatically; `REVOKED` and `REJECTED` are terminal. Authorizations are listed with `driver_id`, `fleet_account_id`, and `status` filters, and a `FleetManager` may act only on authorizations of their own fleet.

Invoicing consolidates a calendar month. Closing a billing period takes a `period` in YYYY-MM form and sweeps up the fleet's `FLEET_BILL` bookings that are still `UNBILLED`, have a non-null `final_total_cents`, and settled — reached their terminal state — inside that calendar month. The new invoice starts in `ISSUED` status. The invoice's `gross_cents` is the sum of those members' `final_total_cents` (for fee-only settlements such as no-shows and late cancellations, that final total is exactly the fee). The volume tier is keyed on the gross, never the net: gross of at least 500000 cents earns `discount_pct` 2, at least 2000000 earns 5, and at least 5000000 earns 8, with anything less earning 0. The `discount_cents` is the gross times the percentage over one hundred, rounded half up; `net_cents` is gross minus discount; `due_date` is the last day of the period plus the fleet's `payment_terms_days`. Each member booking's `billing_status` moves `UNBILLED` → `INVOICED` and its id lands in the invoice's `booking_ids`, and the fleet's `current_balance_cents` is recomputed. A period with no billable members creates nothing — the request is rejected with `ERR_VALIDATION` rather than returning success with empty data.

The fleet pays invoices against the remainder: an invoice in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` is payable, and anything else — including `DISPUTED` — is `ERR_INVOICE_NOT_PAYABLE`. A payment smaller than `net_cents` minus `paid_cents` moves the invoice to `PARTIALLY_PAID` and accumulates `paid_cents`; a payment of exactly the remainder moves it to `PAID`, recomputes the fleet balance, and cascades to every booking in `booking_ids`: each flips `INVOICED` → `PAID` and credits its driver 10 loyalty points per night with tier recomputed. Overpayment is `ERR_OVERPAYMENT`. Invoices are listed with `fleet_account_id`, `status`, and `period` filters, visible to a `FleetManager` only for their own fleet.

Collections run through the fleet ops-run, a `NetworkAdmin` capability. When the sweep finds an `ISSUED` or `PARTIALLY_PAID` invoice whose `due_date` end-of-day UTC has passed, the invoice becomes `OVERDUE`, and any `OVERDUE` invoice triggers the fleet-overdue cascade: the fleet account moves `ACTIVE` → `SUSPENDED` with `auto_suspended` set true, every `ACTIVE` authorization on the fleet moves to `SUSPENDED` with `auto_suspended` true, and each of those suspensions cascades as described above — future fleet-billed bookings cancelled fee-free, stalls released, waitlist scans run. When a later sweep finds no invoice in `ISSUED`, `PARTIALLY_PAID`, `OVERDUE`, or `DISPUTED` carrying a past-due date or outstanding balance, and the suspension was automatic, the fleet returns to `ACTIVE`, `auto_suspended` clears, and authorizations flagged `auto_suspended` restore to `ACTIVE`; manual suspensions stay untouched.

Disputes give the fleet a formal objection channel. A `FleetManager` may dispute an invoice of their own fleet in `ISSUED`, `PARTIALLY_PAID`, `OVERDUE`, or `PAID`, supplying a `reason`; the invoice becomes `DISPUTED`. A `NetworkAdmin` then resolves it by `outcome`: `UPHELD` returns the invoice to `ISSUED` with `due_date` unchanged — a due date that has already passed simply flips the invoice to `OVERDUE` at the next fleet ops-run — while `WAIVED` writes the invoice off. A `NetworkAdmin` may also write off an `OVERDUE` invoice directly. Either write-off path moves every booking in `booking_ids` to `WAIVED` billing — clawing back 10 loyalty points per night from any booking that had already reached `PAID` — adds any collected `paid_cents` to the fleet's `credit_cents`, and recomputes `current_balance_cents` with the written-off invoice excluded.

Closing a fleet is the terminal act. A `NetworkAdmin` may close an account only when `current_balance_cents` is exactly 0 and no invoice sits in `ISSUED`, `PARTIALLY_PAID`, `OVERDUE`, or `DISPUTED`; otherwise the close is rejected as an invalid state (`ERR_INVALID_STATE`). Closure moves the account to `CLOSED` and revokes every non-terminal authorization on the fleet.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`: this includes site, stall, rate plan, amenity product, driver, fleet account, driver authorization, booking, amenity line, waitlist entry, and incident creation, as well as posting a payment (which creates a payment record) and closing a billing period (which creates an invoice). Endpoints that modify an existing resource or drive a state transition — check-in, check-out, cancellation, extension, cancellation of an amenity line, offer accept/withdraw, and all transition endpoints — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sites` | Create a site; auto-creates a default `ACTIVE` rate plan | NetworkAdmin |
| GET | `/sites` | List sites | Driver, FleetManager, SiteOperator, NetworkAdmin |
| GET | `/sites/{id}` | Get a site | Driver, FleetManager, SiteOperator, NetworkAdmin |
| PATCH | `/sites/{id}` | Update site configuration; affects future quotes only | NetworkAdmin |
| GET | `/sites/{id}/availability` | Real-time free-stall counts per pool for a window | Driver, SiteOperator, NetworkAdmin |
| GET | `/sites/{id}/forecast` | Capacity forecast for a night, both variants | Driver, SiteOperator, NetworkAdmin |
| POST | `/sites/{id}/ops-run` | Run the site ops sweep in pinned order | SiteOperator, NetworkAdmin |
| POST | `/sites/{id}/stalls` | Create a stall | NetworkAdmin |
| GET | `/sites/{id}/stalls` | List stalls of a site | Driver, SiteOperator, NetworkAdmin |
| PATCH | `/sites/{id}/stalls/{stall_id}` | Set stall status (triggers the reassignment cascade) | SiteOperator, NetworkAdmin |
| POST | `/sites/{id}/rate-plans` | Create a `DRAFT` rate plan | NetworkAdmin |
| GET | `/sites/{id}/rate-plans` | List rate plans of a site | Driver, SiteOperator, NetworkAdmin |
| POST | `/sites/{id}/rate-plans/{rate_plan_id}/transition` | Activate (OCC on site version) or retire a rate plan | NetworkAdmin |
| POST | `/sites/{id}/amenity-products` | Create an amenity product | NetworkAdmin |
| GET | `/sites/{id}/amenity-products` | List amenity products of a site | Driver, SiteOperator, NetworkAdmin |
| PATCH | `/sites/{id}/amenity-products/{amenity_product_id}` | Reprice, recapacitate, or discontinue a product | NetworkAdmin |
| POST | `/drivers` | Register a driver | Anonymous |
| GET | `/drivers/{driver_id}` | Get a driver with computed loyalty and standing fields | Driver, FleetManager, SiteOperator, NetworkAdmin |
| POST | `/fleet-accounts` | Create a fleet account | NetworkAdmin |
| GET | `/fleet-accounts/{fleet_account_id}` | Get a fleet account (FleetManager: own only) | FleetManager, NetworkAdmin |
| POST | `/fleet-accounts/{fleet_account_id}/close` | Close a fleet; revokes its authorizations | NetworkAdmin |
| POST | `/fleet-accounts/{fleet_account_id}/ops-run` | Fleet sweep: overdue marking, suspension cascade, reactivation | NetworkAdmin |
| POST | `/fleet-accounts/{fleet_account_id}/close-billing-period` | Generate the invoice for a YYYY-MM period | NetworkAdmin |
| POST | `/driver-authorizations` | Driver requests fleet billing authorization | Driver |
| GET | `/driver-authorizations` | List authorizations, filterable | Driver, FleetManager, NetworkAdmin |
| GET | `/driver-authorizations/{auth_id}` | Get an authorization | Driver, FleetManager, NetworkAdmin |
| POST | `/driver-authorizations/{auth_id}/transition` | Approve, reject, suspend, or revoke (own fleet) | FleetManager |
| POST | `/bookings` | Create a booking (reserved or walk-in) | Driver |
| GET | `/bookings` | List bookings with filters | Driver, FleetManager, SiteOperator, NetworkAdmin |
| GET | `/bookings/{booking_id}` | Get a booking (Driver: own; FleetManager: own-fleet billed) | Driver, FleetManager, SiteOperator, NetworkAdmin |
| POST | `/bookings/{booking_id}/cancel` | Cancel a `BOOKED` booking | Driver |
| POST | `/bookings/{booking_id}/check-in` | Check in within the allowed window | Driver |
| POST | `/bookings/{booking_id}/check-out` | Check out; force eviction when `force` is true (OVERSTAY only) | Driver, SiteOperator |
| POST | `/bookings/{booking_id}/extend` | Extend a `BOOKED` booking at current rates (OCC) | Driver |
| POST | `/bookings/{booking_id}/payments` | Post a direct-driver payment | Driver |
| POST | `/bookings/{booking_id}/amenities` | Add an amenity line to a booking | Driver |
| GET | `/booking-amenities` | List amenity lines, filterable | Driver, SiteOperator, NetworkAdmin |
| GET | `/booking-amenities/{amenity_line_id}` | Get an amenity line | Driver, SiteOperator, NetworkAdmin |
| PATCH | `/booking-amenities/{amenity_line_id}` | Fulfill a `RESERVED` line | SiteOperator |
| DELETE | `/booking-amenities/{amenity_line_id}` | Cancel a `RESERVED` line | Driver |
| POST | `/waitlist-entries` | Join a site's waitlist for a window | Driver |
| GET | `/waitlist-entries` | List waitlist entries, filterable | Driver, SiteOperator, NetworkAdmin |
| GET | `/waitlist-entries/{entry_id}` | Get a waitlist entry | Driver, SiteOperator, NetworkAdmin |
| POST | `/waitlist-entries/{entry_id}/accept` | Accept an `OFFERED` slot; creates the booking | Driver |
| POST | `/waitlist-entries/{entry_id}/withdraw` | Withdraw a `QUEUED` entry | Driver |
| POST | `/sites/{id}/incidents` | Report a security, lighting, or facility incident | Driver, SiteOperator |
| GET | `/incidents` | List incidents, filterable | Driver, SiteOperator, NetworkAdmin |
| GET | `/incidents/{incident_id}` | Get an incident | Driver, SiteOperator, NetworkAdmin |
| POST | `/incidents/{incident_id}/transition` | Acknowledge, investigate, resolve, reopen (SiteOperator); dismiss (NetworkAdmin) | SiteOperator, NetworkAdmin |
| GET | `/invoices` | List invoices, filterable (FleetManager: own fleet) | FleetManager, NetworkAdmin |
| GET | `/invoices/{invoice_id}` | Get an invoice | FleetManager, NetworkAdmin |
| POST | `/invoices/{invoice_id}/payments` | Post a fleet payment; exact remainder cascades to bookings | FleetManager |
| POST | `/invoices/{invoice_id}/dispute` | Dispute an invoice | FleetManager |
| POST | `/invoices/{invoice_id}/resolve-dispute` | Resolve a dispute: uphold or waive | NetworkAdmin |
| POST | `/invoices/{invoice_id}/write-off` | Write off an `OVERDUE` invoice | NetworkAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | NetworkAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SITE_ESCALATED` | 409 Conflict |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_WALKIN_NOT_TODAY` | 422 Unprocessable Entity |
| `ERR_WINDOW_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CHECKIN_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_CHECKIN_GRACE_ELAPSED` | 409 Conflict |
| `ERR_REOPEN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_STALL_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DRIVER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EXTENSION_CONFLICT` | 409 Conflict |
| `ERR_DRIVER_SUSPENDED` | 409 Conflict |
| `ERR_DRIVER_NOT_AUTHORIZED` | 403 Forbidden |
| `ERR_FLEET_SUSPENDED` | 409 Conflict |
| `ERR_SITE_CAPACITY_FULL` | 409 Conflict |
| `ERR_AMENITY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_WAITLIST_ENTRY` | 409 Conflict |
| `ERR_DUPLICATE_STALL_NUMBER` | 409 Conflict |
| `ERR_STALL_NOT_RESERVABLE` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_FLEET_CREDIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SPEND_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_DUE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |



