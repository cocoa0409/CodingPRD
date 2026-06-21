# Bowling Entertainment Center API — Product Requirements Document

## 1. Introduction

A modern bowling and entertainment center juggles far more than open lanes. On any given evening the floor staff are simultaneously seating walk-in families, holding pre-booked birthday parties, renting out shoes and bumpers, ringing up snack-bar orders, and reserving banks of lanes for a recurring bowling league — all against a finite inventory of lanes, arcade bays, and rental equipment whose double-booking would strand a paying guest. This document specifies the API that runs that floor. It governs the full lifecycle of a booking, from a tentative draft, through a priced hold that captures a deposit, to a confirmed and checked-in session, and finally to completion or one of several cancellation outcomes — each with its own refund consequence.

The system serves four constituencies whose interests must be reconciled in software. Customers book and manage their own lanes and bays, order food, and rent equipment. Front-desk staff run the live floor: walk-ins, check-ins, completions, and no-shows. League administrators schedule recurring league nights and record their outcomes. Center managers own the physical and pricing configuration — the lanes, bays, rate cards, party packages, menu, and rental stock — and hold the authority to suspend a delinquent customer. Because lanes and bays are scarce and time-bound, and because money changes hands at every hold and cancellation, the API is built around two disciplines that recur throughout this document: precise temporal-conflict arbitration over a shared resource calendar, and a deposit ledger whose every debit and credit must reconcile.

This specification is the single source of truth for the system's behavior. It defines the resources, their state machines, the pricing and refund calculations, the validation order, and the exact error each rejected request returns.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `FrontDesk`, `LeagueAdmin`, and `CenterManager`. A request missing the `X-User-Role` header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation (per the authorization table in §4) is rejected with `ERR_FORBIDDEN`.

The four roles relate to persisted identity differently. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any reservation, food line, or rental line compare the owning reservation's `customer_id` to `X-User-ID`. A `Customer` who attempts to act on a reservation that is not theirs — that is, one whose `customer_id` does not equal `X-User-ID` — is rejected with `ERR_NOT_RESOURCE_OWNER`. The other three roles carry an opaque operator identity. When `X-User-Role` is `FrontDesk`, `LeagueAdmin`, or `CenterManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it, but it is never compared to any entity's `id` for ownership. Front-desk staff, league administrators, and center managers therefore act on behalf of the center rather than on behalf of a single owned account.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its allowed range is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`. On the reservation, food-line, and rental-line list endpoints, a caller acting as `Customer` sees only resources belonging to their own reservations (a reservation whose `customer_id` equals `X-User-ID`, or a line on such a reservation); this owner scoping is applied before any other filter and before pagination, so `total_count` reflects only the caller's own resources.

### 2.4. Common Resource Properties

Most resources in this system carry a standard set of system-managed fields. Every such resource has an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits recording first creation; an `updated_at` timestamp in the same format recording the last modification; and a `version`, an integer that starts at 1 and increments by one on every mutation to the resource. Optimistic concurrency, described in §2.7, reads this `version`.

Two entities are deliberately leaner. A `FoodOrderLine` carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version`, because a food line is created and deleted rather than revised in place. Every other resource — the rate card, lane, bay, customer, party package, menu item, rental item, reservation, rental line, league, and league night — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations in this system touch more than one resource. When a write provokes a change in a related resource, that secondary change is part of the same operation and the system applies it immediately and atomically. The deposit and inventory consequences described throughout §3 — a customer's held deposit balance rising when a reservation is held, a refund credit appearing when one is cancelled, rental units flowing back into available stock when a line is returned — are all such cascades. Whenever a resource's fields change as part of one of these cascades, its `updated_at` is refreshed and its `version` is incremented by one, exactly as for a direct write.

The deepest of these cascades runs three resources deep. Suspending a customer expires their held reservations; each expiry releases that reservation's deposit and returns its open rentals; and a cancellation or expiry that frees a contended window promotes a waitlisted reservation, which itself captures a fresh deposit. Each hop in such a chain is a real mutation that bumps the affected resource's `version` and `updated_at`.

### 2.6. Request Validation Order and Referenced-Resource Existence

Every request runs through the same ordered gauntlet of checks, and the first one to fail decides the response. Authentication comes first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization follows: a role not permitted for the operation yields `ERR_FORBIDDEN`, and a `Customer` acting on a reservation they do not own yields `ERR_NOT_RESOURCE_OWNER`. Next, every resource referenced in the path or body must exist; identifiers in a path are validated left to right, and the first identifier that names no existing resource produces `ERR_NOT_FOUND` before any later identifier is examined. Only then is the body checked for well-formedness — required fields present, enum values in range, `start_at` strictly before `end_at`, counts positive — with a violation reported as `ERR_INVALID_REQUEST`. State preconditions are evaluated after these structural checks, which is why a cancel on an already checked-in reservation surfaces the state rejection rather than a fiscal one. Cross-entity dependency checks, temporal-conflict and capacity checks, and fiscal checks follow in turn, each described alongside the workflow it guards in §3.

### 2.7. Optimistic Concurrency Control

Two reservation transitions are guarded by optimistic concurrency control, because each can be legitimately superseded by an intervening write that the client never saw. Confirming a held reservation requires the request body to carry `expected_reservation_version`, which must equal the reservation's current `version`. If another writer has advanced the reservation's `version` since the client last read it — for example a revise that re-priced the booking, or a system expiry that fired in the interim — the client's view is stale and the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, revising a confirmed reservation requires `expected_reservation_version` to match the reservation's current `version`; if a competing revise has already superseded the booking under the revision-loop semantics and advanced the `version`, the current writer's view is stale and the revise is rejected with `ERR_STALE_VERSION` (HTTP 412). These are the only two endpoints that take a version field; no other operation requires one.

### 2.8. Monetary Values, Basis Points, and Rounding

Every monetary amount in this system is an integer count of cents. There are no fractional cents in stored or returned values. Several configuration fields are expressed in basis points, where ten thousand basis points equal a factor of one: a `peak_multiplier_bps` of 12500 means a 1.25× surcharge, a `deposit_pct_bps` of 2000 means twenty percent, and the sales-tax rate of 825 basis points means 8.25%. Wherever a calculation multiplies a cent amount by a basis-point factor — the peak surcharge, the deposit percentage, the sales tax, the partial-refund percentage — the system divides by ten thousand and rounds the result to the nearest whole cent using round-half-up (a value ending in exactly half a cent rounds up). Each calculation section in §3 states precisely where this rounding lands, because for several of them the order of rounding relative to summation changes the final cent.

### 2.9. Resource Calendar and Temporal Conflict Arbitration

Lanes and bays share a finite calendar, and the system's core integrity guarantee is that no resource is double-booked. The two resource kinds use different conflict rules. For a lane, booking windows are treated as half-open intervals `[start_at, end_at)`: a new window conflicts with an existing blocking reservation on the same lane when the two intervals overlap, but two bookings that touch exactly — one ending at the precise instant the next begins — are permitted back-to-back. A lane conflict is rejected with `ERR_LANE_TIME_CONFLICT`.

For a bay, the rule is stricter because the bay must be cleaned between sessions. Each bay carries a `cleanup_buffer_minutes` gap that must separate consecutive bookings. A new bay window is in conflict when it starts before a prior booking's end plus the buffer, or when it ends after a following booking's start minus the buffer, on the same bay. A bay conflict is rejected with `ERR_BAY_TIME_CONFLICT`. In both cases a "blocking reservation" is one that still holds its window — that is, one that has not been cancelled, expired, no-showed, or completed away.

A reservation that finds its requested window already contended may instead join a waitlist for that window rather than being rejected outright; the waitlist mechanics and the conflict-driven promotion that follows a cancellation are described in §3.

## 3. Business Logic & Workflows

### 3.1. Configuring the Floor: Rate Cards, Lanes, Bays, and Catalogs

Before any booking can be priced, a `CenterManager` lays down the center's configuration. A **rate card** is the pricing instrument; it is created with a `name` and the two headline prices, `per_game_cents` (charged per game per bowler) and `per_hour_cents` (charged per billable lane-hour block), each of which must be zero or greater. A rate card also carries several tuning fields with sensible defaults: `block_minutes`, the length in minutes of one billable per-hour block, which must be greater than zero and defaults to 60; `peak_multiplier_bps`, the basis-point surcharge applied to per-hour pricing during the peak window, which must be at least 10000 and defaults to 10000 (no surcharge); `peak_start_hour` and `peak_end_hour`, the local hours between 0 and 23 at which the peak window opens (inclusive) and closes (exclusive), defaulting to 18 and 23; and `deposit_pct_bps`, the deposit expressed in basis points of the quoted subtotal, ranging from 0 to 10000 and defaulting to 2000. Each reservation pins the rate card it was quoted against, so later edits to a rate card never silently re-price an existing booking.

A **lane** is a physical bowling lane, created with a unique `number` of at least 1 and an optional `max_bowlers` seating-and-scoring cap that defaults to 6 and must be at least 1. Attempting to create a lane whose `number` is already in use is rejected with `ERR_DUPLICATE_LANE_NUMBER`. A lane's `status` is system-managed and begins `IN_SERVICE`; a manager may toggle it between `IN_SERVICE` and `OUT_OF_SERVICE` by supplying a new `status`, which increments the lane's `version`. An **arcade bay** — laser tag, an escape room, and the like — is created with a unique `name`, an optional `capacity` guest cap defaulting to 12 (at least 1), and the `cleanup_buffer_minutes` idle gap described in §2.9, which defaults to 15 and must be zero or greater. A bay's `status` likewise starts `IN_SERVICE` and may be toggled to `OUT_OF_SERVICE`, bumping its `version`.

The remaining catalogs round out what a booking can include. A **party package** carries a `name`, a flat `base_cents` base price (zero or greater), an `included_guests` count covered by that base (at least 1), an `extra_guest_cents` per-head charge for guests beyond the included count (zero or greater), a `max_guests` hard cap that must be at least the included-guest count, and `included_lane_hours`, the lane-hours bundled in at no extra lane charge, which defaults to 2 and must be zero or greater. A **menu item** for food add-ons carries a `name`, a pre-tax `unit_cents` price (zero or greater), and a `taxable` flag that defaults to true. A **rental item** — shoes, balls, or bumpers — carries a `kind` of `SHOES`, `BALL`, or `BUMPER`, a size-or-variant `label`, a `unit_price_cents` rental price (zero or greater), and a `total_count` of physical units owned (zero or greater). Two further rental fields are system-computed and never supplied on input: `out_on_rent_count`, the number of units currently committed to open rental lines, and `available_count`, defined as `total_count` minus `out_on_rent_count` and never allowed to go negative. At creation a rental item's `out_on_rent_count` is 0 and its `available_count` equals its `total_count`. Across the whole system the rental inventory is conserved: for any rental item, `total_count` always equals `available_count` plus `out_on_rent_count`, where `out_on_rent_count` is the sum of the `quantity` of every open rental line referencing that item across all reservations.

### 3.2. Customers and the Deposit Ledger

A **customer** is registered — by front-desk staff or a manager — with a unique `email` and a `full_name`. A new customer starts with `status` `ACTIVE` and two computed money fields at zero: `deposit_balance_cents`, the total of deposits currently held against the customer, and `wallet_credit_cents`, the refundable credit accumulated from refunded deposits. The deposit balance is not a free-floating number; at all times it equals the sum of `held_deposit_cents` across that customer's reservations in the `HELD`, `CONFIRMED`, and `CHECKED_IN` states. Every transition described below that captures, releases, or refunds a deposit keeps this identity true, and each such adjustment is a mutation that refreshes the customer's `updated_at` and increments its `version`.

A `CenterManager` may suspend a customer, moving `status` from `ACTIVE` to `SUSPENDED`, and may later reinstate a suspended customer back to `ACTIVE`; each transition bumps the customer's `version`. Suspending a customer that is not currently `ACTIVE`, or reinstating one that is not currently `SUSPENDED`, is rejected with `ERR_INVALID_STATE`. Suspension is not a quiet flag flip — it triggers the system's deepest cascade. Every reservation of that customer currently in `HELD` status is driven to `EXPIRED`. Each such expiry releases that reservation's held deposit (debiting `deposit_balance_cents` and crediting the released amount to `wallet_credit_cents`) and returns every open rental line on that reservation, restoring the rented units to their items' `available_count`. A suspended customer cannot place a reservation on hold or take out a rental; either attempt is rejected with `ERR_CUSTOMER_SUSPENDED`.

### 3.3. Booking a Lane or Bay: Draft, Hold, and the Quote

A booking begins as a **reservation** in `DRAFT`. A `Customer` (acting on their own `customer_id`) or a `FrontDesk` operator creates it by supplying the `customer_id` of the owner, the `rate_card_id` to pin pricing against, and a `resource_kind` of either `LANE` or `BAY`. When the kind is `LANE`, a `lane_id` identifies the target lane and `bay_id` is left null; when the kind is `BAY`, a `bay_id` identifies the target bay and `lane_id` is null. The booking may optionally name a `party_package_id` (null for a plain booking) and an `origin` of either `RESERVATION`, for a booked-ahead session, or `WALK_IN`, for a same-day floor seating, defaulting to `RESERVATION`. The pricing path is chosen by `pricing_mode`, either `PER_GAME` or `PER_HOUR`. The window is given by `start_at` and `end_at`, both ISO 8601 UTC instants, with `end_at` strictly after `start_at`. The party is sized by `bowler_count`, which must be at least 1; `game_count`, the games per bowler used only in per-game pricing, defaulting to 0 and never negative; and `guest_count`, the party-package guest tally used only on package bookings, defaulting to 0 and never negative. A draft carries all of its computed money fields at zero — `lane_subtotal_cents`, `package_subtotal_cents`, `food_subtotal_cents`, `rental_subtotal_cents`, `quoted_total_cents`, and `held_deposit_cents` are not priced until the reservation is held. A malformed body — a missing required field, an out-of-range enum, a `start_at` at or after `end_at`, or a non-positive count — is rejected with `ERR_INVALID_REQUEST`.

The pivotal step is the **hold**, available to the owning `Customer` or a `FrontDesk` operator, which moves the reservation from `DRAFT` to `HELD`, prices it, and captures a deposit. A hold may proceed only when the owning customer is `ACTIVE` (otherwise `ERR_CUSTOMER_SUSPENDED`); when the target resource exists and its `status` is `IN_SERVICE` — the lane when `resource_kind` is `LANE`, the bay when it is `BAY` — otherwise `ERR_RESOURCE_OUT_OF_SERVICE`; when the requested window has no temporal-overlap conflict on the target resource per the rules of §2.9; and when the party fits the resource, meaning `bowler_count` does not exceed the lane's `max_bowlers` for a lane booking, or does not exceed the bay's `capacity` for a bay booking. A party that overruns the resource cap, or whose `guest_count` exceeds the chosen package's `max_guests`, is rejected with `ERR_CAPACITY_EXCEEDED`; the specific case of a party `guest_count` above the package's `max_guests` is reported as `ERR_PARTY_GUESTS_EXCEED_MAX`. On a successful hold the system recomputes every subtotal, sets `held_deposit_cents` from the resulting quote, and adds that deposit to the owning customer's `deposit_balance_cents`, then increments the reservation's `version`.

The **lane charge** itself — the value that lands in `lane_subtotal_cents` — depends entirely on `pricing_mode`, and the two modes can yield different totals for the very same lane, window, and party. First compute the booking's duration as the whole number of minutes from `start_at` to `end_at`. Under `PER_GAME` pricing, the lane charge is `per_game_cents` multiplied by `game_count` multiplied by `bowler_count`; the duration and any peak surcharge are ignored entirely. Under `PER_HOUR` pricing, the duration is divided by the rate card's `block_minutes` and rounded up to the next whole block — so a duration equal to one block bills as one block, and a duration one minute over a whole number of blocks bills as one more block. The system then determines whether the window is a peak window: it is peak when any minute of the half-open interval from `start_at` up to `end_at` falls within the local-hour window from `peak_start_hour` (inclusive) to `peak_end_hour` (exclusive). The hourly rate is `per_hour_cents` at off-peak; during peak it is `per_hour_cents` scaled by `peak_multiplier_bps` divided by ten thousand. The per-hour lane charge is the block count multiplied by that hourly rate, rounded half-up to whole cents; `game_count` plays no part in per-hour pricing. When the booking carries a party package that bundles `included_lane_hours`, the first whole blocks covered by those bundled hours — that is, the bundled hours converted to minutes and divided by `block_minutes`, rounded up — are free, and only the blocks in excess of that bundle bill under per-hour pricing.

### 3.4. Party Packages, Food, and Rentals on a Booking

When a reservation names a `party_package_id`, a **package charge** is added to the quote and recorded in `package_subtotal_cents`. The billable guests are computed by first clamping `guest_count` to the package's `max_guests` — taking the smaller of the two — and then subtracting `included_guests`, with the result floored at zero so a small party never produces a negative count. The package charge is the package's `base_cents` plus those billable guests multiplied by `extra_guest_cents`. Because a `guest_count` above `max_guests` is rejected at validation time (see §3.3), the clamp never actually bills guests beyond the cap; it exists so the arithmetic is well-defined. This computation is exact in cents with no rounding.

Food add-ons are attached as **food order lines**, addable to a reservation only while it is in `DRAFT` or `HELD`. A line is created by the owning `Customer` or a `FrontDesk` operator with the `reservation_id` it belongs to, the `food_item_id` ordered, and a `quantity` of at least 1. At creation the system snapshots the menu item's price into `unit_cents_snapshot` and its taxable flag into `taxable_snapshot`, so the line's pricing is frozen even if the catalog later changes. Each line's `line_total_cents` and the reservation's `food_subtotal_cents` follow a rounding order that is pinned and must not be reordered: tax is computed and rounded per line, and only then are the lines summed — rounding per line before summing, never summing first and rounding once. For each food line, the gross is `unit_cents_snapshot` multiplied by `quantity`; if the line is taxable per its `taxable_snapshot`, the tax is that gross multiplied by 825 basis points, divided by ten thousand, and rounded half-up to whole cents, and if it is not taxable the tax is zero; the line's `line_total_cents` is gross plus that rounded tax. The reservation's `food_subtotal_cents` is the sum of those already-rounded line totals. Adding a food line recomputes `food_subtotal_cents` and `quoted_total_cents`, refreshes `held_deposit_cents` if the reservation is already `HELD`, and increments the owning reservation's `version`. A food line may be removed while the reservation is `DRAFT` or `HELD`; removing it likewise recomputes `food_subtotal_cents` and `quoted_total_cents`, refreshes `held_deposit_cents` and reconciles the customer's deposit balance if the reservation is already `HELD`, and bumps the reservation's `version`. The removal operation responds `200 OK` with the removed food-line object in `data`.

Equipment is taken as **rental lines**, which may be taken against a reservation while it is in `DRAFT`, `HELD`, or `CHECKED_IN`. A rental line is created by the owning `Customer` or a `FrontDesk` operator with the `reservation_id`, the `rental_item_id`, and a `quantity` of at least 1; the requested `quantity` may not exceed the item's `available_count`, and a shortfall is rejected with `ERR_RENTAL_UNAVAILABLE`. A suspended customer may not take a rental at all (`ERR_CUSTOMER_SUSPENDED`). At creation the line snapshots the item's price into `unit_price_snapshot`, starts in `status` `OPEN`, and its `line_total_cents` is its `quantity` multiplied by `unit_price_snapshot`. Taking the line raises the item's `out_on_rent_count` by the quantity and lowers its `available_count` accordingly, recomputes the reservation's `rental_subtotal_cents` and `quoted_total_cents`, and increments the reservation's `version`. The reservation's `rental_subtotal_cents` is the sum of `unit_price_snapshot` times `quantity` over every `OPEN` rental line on that reservation; returned lines no longer count. Returning a line moves its `status` from `OPEN` to `RETURNED`, lowers the item's `out_on_rent_count` by the line's quantity and restores its `available_count`, and increments the rental line's own `version`. The returning operation responds `200 OK` with the returned rental-line object. Because the returned line no longer counts, the owning reservation's `rental_subtotal_cents` and `quoted_total_cents` are recomputed to drop it, but — unlike taking a line — returning a line does not bump the reservation's `version` and does not refresh the held deposit even when the reservation is `HELD`.

The reservation's **quoted total**, in `quoted_total_cents`, is simply the sum of the four subtotals — `lane_subtotal_cents` plus `package_subtotal_cents` plus `food_subtotal_cents` plus `rental_subtotal_cents` — computed exactly in cents. The **deposit** captured at hold, `held_deposit_cents`, is the quoted total multiplied by the pinned rate card's `deposit_pct_bps`, divided by ten thousand, and rounded half-up to whole cents.

### 3.5. Confirming, Revising, Checking In, and Completing

Once held, a reservation is confirmed by the owning `Customer` or a `FrontDesk` operator, advancing `HELD → CONFIRMED` while the deposit stays held. Confirmation is the first of the two version-guarded steps: the body must carry `expected_reservation_version` matching the reservation's current `version` (a mismatch yields `ERR_STALE_VERSION`, HTTP 412, per §2.7), the target lane or bay must still be `IN_SERVICE` (otherwise `ERR_RESOURCE_OUT_OF_SERVICE`), and the window must still be free of any temporal-overlap conflict on the target resource. A successful confirm increments the reservation's `version`.

The system supports a **revision loop** so a confirmed booking can be re-opened to change its terms — this is the one cyclic edge in the reservation lifecycle. Revising drives `CONFIRMED → HELD` and is the second version-guarded step: the body carries `expected_reservation_version`, which must match the current `version` (else `ERR_STALE_VERSION`, HTTP 412), and the reservation must not already be `CHECKED_IN`. A revise applies any supplied new `start_at`, `end_at`, `pricing_mode`, `bowler_count`, `game_count`, or `guest_count`; re-runs the temporal-overlap check against the possibly-new window; re-runs the capacity check against the revised party (the same `ERR_CAPACITY_EXCEEDED` / `ERR_PARTY_GUESTS_EXCEED_MAX` rules as a hold, evaluated after the overlap check); recomputes the quoted total and the held deposit; and reconciles the customer's `deposit_balance_cents` by the difference between the new and old deposit. The reservation returns to `HELD` and its `version` is incremented.

Front-desk staff drive the day-of transitions. **Check-in** advances a `CONFIRMED` reservation to `CHECKED_IN` and may occur only within the check-in window: the current UTC time must be at or after `start_at` minus thirty minutes (a guest may arrive up to half an hour early) and at or before `end_at`. **Completion** advances a `CHECKED_IN` reservation to `COMPLETED`, but only once every rental line on that reservation has been returned — any line still `OPEN` blocks completion with `ERR_RENTALS_OUTSTANDING`. On completion the held deposit is applied to the bill and removed from the customer's held balance, debiting `deposit_balance_cents` by `held_deposit_cents`; the reservation's `version` is incremented. Each of these transitions bumps the reservation's `version`. A transition requested against a reservation not in the state that admits it — confirming something that is not `HELD`, checking in something that is not `CONFIRMED`, and so on — is rejected with `ERR_INVALID_STATE`.

### 3.6. Cancellation, Refund Tiers, No-Shows, and Hold Expiry

A reservation in `HELD` or `CONFIRMED` may be cancelled by the owning `Customer` or a `FrontDesk` operator; once a reservation has reached `CHECKED_IN` (or any terminal state) it can no longer be cancelled, and the attempt is rejected with `ERR_INVALID_STATE` — the state precondition is checked ahead of any fiscal computation. Cancellation sets `cancelled_at` to the current time and computes a refund based on how much notice the customer gave. The notice is the whole number of minutes from the cancellation instant (`cancelled_at`) to the booking's `start_at`. The refund tiers are pinned at their boundaries with at-least comparisons: when the notice is at least 1440 minutes (a full 24 hours), the refund credited to `refund_cents` is the entire `held_deposit_cents`; otherwise, when the notice is at least 120 minutes (2 hours), the refund is half the held deposit — `held_deposit_cents` multiplied by 5000 basis points, divided by ten thousand, rounded half-up to whole cents; and with less than 120 minutes of notice the refund is zero and the deposit is forfeited. On cancellation the held deposit leaves the customer's `deposit_balance_cents` and the computed `refund_cents` is added to their `wallet_credit_cents`; every `OPEN` rental line on the reservation is returned, restoring the items' `available_count`; the reservation's resource time-block is released; and as a cascade the earliest eligible waitlisted reservation on the same resource and window is promoted (see §3.7). The reservation moves to `CANCELLED` and its `version` is incremented.

When a confirmed booking's window passes without the guest ever checking in, front-desk staff record a **no-show**, driving `CONFIRMED → NO_SHOW`. This is permitted only when the current time is past `end_at` and the reservation never reached `CHECKED_IN`. A no-show forfeits the deposit entirely: `refund_cents` is zero, the held deposit is removed from `deposit_balance_cents`, and no wallet credit is granted. The resource time-block is released, but because the window has already passed no waitlist promotion is attempted. The reservation's `version` is incremented.

A held reservation that is never confirmed eventually **expires**. There are two paths into `EXPIRED`, and both treat the deposit identically: the entire held deposit is waived back to the customer rather than forfeited — `refund_cents` is set to the full `held_deposit_cents`, that amount is debited from `deposit_balance_cents` and credited to `wallet_credit_cents`, and every `OPEN` rental line is returned to restore availability, before the reservation moves to `EXPIRED` and its `version` is incremented. The first path is the customer-suspension cascade of §3.2. The second is a hold timing out: a `HELD` reservation whose hold has aged at least sixty minutes — measured as the current time minus the moment the hold was placed — is expired by the clock-advance sweep described in §3.9.

### 3.7. Waitlisting and Promotion

When a customer wants a window that is already contended, rather than being turned away they may **join the waitlist** for that resource and window. Joining moves the reservation from `DRAFT` to the `WAITLISTED` state, and crucially captures no deposit — a waitlisted reservation has no `held_deposit_cents` and contributes nothing to the customer's deposit balance. A waitlist join is only meaningful on a genuinely contended window; requesting it on a window that has no active overlap is rejected with `ERR_NOT_WAITLISTED`, since such a booking should simply be held directly. A waitlisted reservation sits outside the main lifecycle until it is promoted; it can, however, be cancelled directly, in which case — because no deposit was ever held — there is no ledger change, `cancelled_at` is stamped, the reservation moves to `CANCELLED`, and its `version` is incremented.

**Promotion** is a system action, never a client call. When a cancellation or an expiry frees a contended window, the system looks for the earliest waitlisted reservation — ordered by `created_at` ascending — among the candidates on that same resource and window whose freed window now has no temporal-overlap conflict, and promotes it from `WAITLISTED` to `HELD`. Promotion prices the booking exactly as a hold would: it recomputes the quoted total and the held deposit, captures that deposit by adding it to the customer's `deposit_balance_cents`, moves the reservation to `HELD`, and increments its `version`. This promotion is the final hop of the three-deep cascade noted in §2.5: the freeing cancellation or expiry is one mutation, the deposit release on the freed reservation is another, and the promoted reservation's fresh deposit capture is the third.

### 3.8. Leagues and League Nights

League play runs on its own lifecycle, owned by a `LeagueAdmin`. A **league** is created with a `name`, the `rate_card_id` whose pricing governs its nights, a `season_night_count` of planned nights (at least 1), a `lanes_per_night` count of lanes reserved for each night (at least 1), and a flat per-night `weekly_fee_cents` charged to the league (zero or greater). A league starts in `DRAFT`. Two computed money fields track its finances: `season_fee_quote_cents`, a forward-looking projection of the whole season's fee, and `season_fee_accrued_cents`, the fee actually accrued from nights that have resolved.

A league night is the unit of play. A `LeagueAdmin` schedules a **league night** under a league with the `league_id`, a `night_index` (a 1-based ordinal that must be unique within its league — a duplicate is rejected with `ERR_DUPLICATE_NIGHT_INDEX`), and a `start_at`/`end_at` window with `end_at` strictly after `start_at`. Scheduling reserves `lanes_per_night` lanes for that window from the available in-service lanes — choosing them in ascending lane `number` order, taking the first such lanes whose window is free of overlap — recording them in the night's system-managed `reserved_lane_ids`, and checks those lanes for overlap just as a reservation would; if fewer than `lanes_per_night` in-service lanes are free for the window, the schedule is rejected with `ERR_LANE_TIME_CONFLICT`. While a night remains `SCHEDULED`, each of its reserved lanes blocks that window against any reservation hold, confirm, or revise on the same lane, exactly as a blocking reservation would. A night starts in `SCHEDULED`.

A league is **activated** by its admin, moving `DRAFT → ACTIVE`, but only if it has at least one league night scheduled; activating a league with no nights is rejected with `ERR_LEAGUE_NO_NIGHTS`. On activation the system computes the forward-looking quote: `season_fee_quote_cents` is `weekly_fee_cents` multiplied by `season_night_count`, the projection that assumes every planned night will accrue its fee regardless of per-night outcome. Activation increments the league's `version`.

Each scheduled night resolves to one of three outcomes, all driven by the `LeagueAdmin` and all requiring the parent league to be `ACTIVE` — a transition attempted while the parent league is not active is rejected with `ERR_LEAGUE_NOT_ACTIVE`, and a night that is not `SCHEDULED` cannot be resolved at all (`ERR_INVALID_STATE`). In all three outcomes, releasing the night's reserved lanes also empties its `reserved_lane_ids` to an empty array, so the resolved night no longer blocks its lanes. Marking a night **played** (`SCHEDULED → PLAYED`) additionally requires the current time to be at or after the night's `start_at`; it sets the night's `night_fee_cents` to the league's `weekly_fee_cents`, adds that fee to the league's `season_fee_accrued_cents` as a chronological accrual, releases the night's reserved lanes back to the calendar, and bumps the night's `version`. Marking a night **forfeited** (`SCHEDULED → FORFEITED`) still owes the fee: it likewise sets `night_fee_cents` to `weekly_fee_cents`, adds it to `season_fee_accrued_cents`, releases the reserved lanes, and bumps the `version`. Marking a night **rained out** (`SCHEDULED → RAINED_OUT`) is the divergent branch: no fee accrues, so `night_fee_cents` is set to zero, the league's `season_fee_accrued_cents` is left unchanged, the reserved lanes are still released, and the night's `version` is incremented.

A league is **closed** by its admin, moving `ACTIVE → CLOSED`, but only once no night remains `SCHEDULED`; closing a league while any scheduled night is still pending is rejected with `ERR_LEAGUE_HAS_SCHEDULED_NIGHTS`. Closing finalizes `season_fee_accrued_cents` as the chronological sum of `night_fee_cents` over every night that actually resolved as `PLAYED` or `FORFEITED`; rained-out nights contribute zero. Because of that, the accrued total falls below the forward-looking quote precisely when one or more nights rained out, even though both figures stem from the same season size. Closing increments the league's `version`.

### 3.9. Deterministic Clock Control

Because check-in windows, no-show eligibility, refund tiers, and hold expiry all turn on the current time, the system exposes two test-driving clock capabilities, available to a `FrontDesk` operator or a `CenterManager`. One capability sets the server's current UTC clock to a supplied `now_utc` instant; the value it sets is the `current_utc` consulted by every check-in, no-show, cancellation-notice, and hold-age computation. The other capability advances the clock forward by a supplied number of `minutes`; advancing the clock also fires the hold-expiry sweep, so that any `HELD` reservation whose hold has aged at least sixty minutes is driven to `EXPIRED` with its deposit released and its rentals returned, exactly as described in §3.6.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource return `201 Created`. Endpoints that modify an existing resource — including every lifecycle transition and every set-status or clock operation — return `200 OK`, with the sole exception of joining the waitlist (`POST /reservations/{id}/waitlist`), which returns `201 Created`. The two clock operations (`POST /_clock/set` and `POST /_clock/advance`) return `200 OK` with an empty object (`{}`) in `data` rather than a resource. The complete request and response shape for each endpoint is reconstructed from the workflow narratives in §3; the table below lists only the method, path, purpose, and the roles authorized to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/rate-cards` | Create a rate card | CenterManager |
| GET    | `/rate-cards/{id}` | Get a rate card | CenterManager, FrontDesk, LeagueAdmin, Customer |
| GET    | `/rate-cards` | List rate cards | CenterManager, FrontDesk, LeagueAdmin, Customer |
| POST   | `/lanes` | Create a lane | CenterManager |
| GET    | `/lanes/{id}` | Get a lane | CenterManager, FrontDesk, Customer, LeagueAdmin |
| GET    | `/lanes` | List lanes | CenterManager, FrontDesk, Customer, LeagueAdmin |
| POST   | `/lanes/{id}/set-status` | Put a lane in or out of service | CenterManager |
| POST   | `/bays` | Create a bay | CenterManager |
| GET    | `/bays/{id}` | Get a bay | CenterManager, FrontDesk, Customer, LeagueAdmin |
| GET    | `/bays` | List bays | CenterManager, FrontDesk, Customer, LeagueAdmin |
| POST   | `/bays/{id}/set-status` | Put a bay in or out of service | CenterManager |
| POST   | `/customers` | Register a customer | FrontDesk, CenterManager |
| GET    | `/customers/{id}` | Get a customer | CenterManager, FrontDesk, Customer |
| GET    | `/customers` | List customers | CenterManager, FrontDesk |
| POST   | `/customers/{id}/suspend` | Suspend a customer | CenterManager |
| POST   | `/customers/{id}/reinstate` | Reinstate a suspended customer | CenterManager |
| POST   | `/party-packages` | Create a party package | CenterManager |
| GET    | `/party-packages/{id}` | Get a party package | CenterManager, FrontDesk, Customer |
| GET    | `/party-packages` | List party packages | CenterManager, FrontDesk, Customer |
| POST   | `/food-items` | Create a menu item | CenterManager |
| GET    | `/food-items/{id}` | Get a menu item | CenterManager, FrontDesk, Customer |
| GET    | `/food-items` | List menu items | CenterManager, FrontDesk, Customer |
| POST   | `/rental-items` | Create a rental inventory item | CenterManager |
| GET    | `/rental-items/{id}` | Get a rental item | CenterManager, FrontDesk, Customer |
| GET    | `/rental-items` | List rental items | CenterManager, FrontDesk, Customer |
| POST   | `/reservations` | Create a DRAFT reservation | Customer, FrontDesk |
| GET    | `/reservations/{id}` | Get a reservation | Customer, FrontDesk, CenterManager |
| GET    | `/reservations` | List/filter reservations | Customer, FrontDesk, CenterManager |
| POST   | `/reservations/{id}/hold` | Place a reservation on HELD and capture a deposit | Customer, FrontDesk |
| POST   | `/reservations/{id}/confirm` | Confirm a HELD reservation | Customer, FrontDesk |
| POST   | `/reservations/{id}/revise` | Re-open a CONFIRMED reservation to HELD with new terms | Customer, FrontDesk |
| POST   | `/reservations/{id}/check-in` | Check a CONFIRMED reservation in | FrontDesk |
| POST   | `/reservations/{id}/complete` | Complete a CHECKED_IN reservation | FrontDesk |
| POST   | `/reservations/{id}/cancel` | Cancel a HELD/CONFIRMED/WAITLISTED reservation | Customer, FrontDesk |
| POST   | `/reservations/{id}/no-show` | Mark a CONFIRMED past-window reservation a no-show | FrontDesk |
| POST   | `/reservations/{id}/waitlist` | Join the waitlist for a contended window | Customer, FrontDesk |
| POST   | `/food-lines` | Add a food add-on line to a reservation | Customer, FrontDesk |
| GET    | `/food-lines/{id}` | Get a food line | Customer, FrontDesk, CenterManager |
| GET    | `/food-lines` | List food lines | Customer, FrontDesk, CenterManager |
| DELETE | `/food-lines/{id}` | Remove a food line | Customer, FrontDesk |
| POST   | `/rental-lines` | Take a rental against a reservation | Customer, FrontDesk |
| GET    | `/rental-lines/{id}` | Get a rental line | Customer, FrontDesk, CenterManager |
| GET    | `/rental-lines` | List rental lines | Customer, FrontDesk, CenterManager |
| POST   | `/rental-lines/{id}/return` | Return a rental line | Customer, FrontDesk |
| POST   | `/leagues` | Create a league | LeagueAdmin |
| GET    | `/leagues/{id}` | Get a league | LeagueAdmin, CenterManager |
| GET    | `/leagues` | List leagues | LeagueAdmin, CenterManager |
| POST   | `/leagues/{id}/activate` | Activate a DRAFT league | LeagueAdmin |
| POST   | `/leagues/{id}/close` | Close an ACTIVE league | LeagueAdmin |
| POST   | `/league-nights` | Schedule a league night | LeagueAdmin |
| GET    | `/league-nights/{id}` | Get a league night | LeagueAdmin, CenterManager |
| GET    | `/league-nights` | List league nights | LeagueAdmin, CenterManager |
| POST   | `/league-nights/{id}/mark-played` | Mark a night PLAYED | LeagueAdmin |
| POST   | `/league-nights/{id}/forfeit` | Mark a night FORFEITED | LeagueAdmin |
| POST   | `/league-nights/{id}/rain-out` | Mark a night RAINED_OUT | LeagueAdmin |
| POST   | `/_clock/set` | Set the server's current UTC clock | CenterManager, FrontDesk |
| POST   | `/_clock/advance` | Advance the server clock and fire the hold-TTL expiry sweep | CenterManager, FrontDesk |

The list endpoints accept the filter and pagination query parameters introduced in §2 and §3: `/lanes`, `/bays`, and `/rental-items` accept a `status` (or `kind` for rental items) filter alongside `limit` and `offset`; `/customers` accepts `status`; `/reservations` accepts `customer_id`, `lane_id`, `bay_id`, `rate_card_id`, `party_package_id`, and `status`; `/food-lines` accepts `reservation_id` and `food_item_id`; `/rental-lines` accepts `reservation_id`, `rental_item_id`, and `status`; `/leagues` accepts `rate_card_id` and `status`; and `/league-nights` accepts `league_id` and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RESOURCE_OUT_OF_SERVICE` | 409 |
| `ERR_RENTALS_OUTSTANDING` | 409 |
| `ERR_LEAGUE_NOT_ACTIVE` | 409 |
| `ERR_LEAGUE_HAS_SCHEDULED_NIGHTS` | 409 |
| `ERR_LEAGUE_NO_NIGHTS` | 409 |
| `ERR_LANE_TIME_CONFLICT` | 409 |
| `ERR_BAY_TIME_CONFLICT` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_RENTAL_UNAVAILABLE` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 409 |
| `ERR_NOT_WAITLISTED` | 409 |
| `ERR_DUPLICATE_LANE_NUMBER` | 409 |
| `ERR_DUPLICATE_NIGHT_INDEX` | 409 |
| `ERR_PARTY_GUESTS_EXCEED_MAX` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
