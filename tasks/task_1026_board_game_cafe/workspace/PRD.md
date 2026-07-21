# Board Game Cafe API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a board-game café: a venue that rents tables by the half-hour, lends physical copies of games from a lending library, serves food and drink against a per-table minimum, runs tournaments and leagues, sells and pre-orders retail games, and rents private rooms for parties. The recurring operational challenge in such a venue is that a single visit accumulates charges from several independent streams — table time, a per-head cover, food and beverage, damaged or lost game copies — and staff need a running estimate of what a party owes while they are seated, then a single authoritative bill when the party leaves.

The service exists to make that reconciliation exact and auditable. Every price is expressed in integer cents, every duration is measured against a server-controlled logical clock rather than wall time, and every mutation is versioned so that concurrent operators do not silently overwrite one another. Loyalty is woven throughout: members earn points on what they spend on food and drink, climb through discount tiers, and can redeem points for rewards, while no-shows accumulate strikes that can suspend an account. Around these core flows sit the supporting lifecycles — tournament registration and check-in, private-room holds that supersede one another under optimistic concurrency, and a retail counter that distinguishes in-stock sales from pre-orders.

The reader implementing this service should treat the business narratives in Section 3 as the source of truth for behavior, and Sections 4 and 5 as the transport-level index of endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. The role must be exactly one of `Manager`, `Staff`, or `Member`. If either header is missing, or the role is not one of these three values, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

`Manager` is the operator superset. A `Manager` configures tables, rooms, game copies, and tournaments, adjusts loyalty balances, suspends and reinstates members, advances the logical clock, and may additionally perform every operation available to `Staff` (a hierarchical override). When `X-User-Role` is `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

`Staff` is the front-of-house operator role: booking, seating, and closing sessions, taking food and beverage orders, lending and receiving game copies, checking tournament registrants in, managing private bookings, and running the retail counter. When `X-User-Role` is `Staff`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and is not compared to any entity's `id`.

`Member` is an entity-backed self-service actor. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Membership`; ownership checks on any resource that references a member compare the resource's `membership_id` field to `X-User-ID`. A `Member` may only act on resources it owns — booking and cancelling its own reservations, registering for and withdrawing from tournaments under its own membership, redeeming its own points, and placing or cancelling its own retail orders. When a `Member` attempts to mutate a reservation, registration, redemption, or retail order whose `membership_id` does not equal its `X-User-ID`, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

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

All list endpoints accept two pagination query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may not be negative. A `limit` or `offset` outside these bounds is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400).

List results are always returned sorted by `created_at` in ascending order (oldest first). The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the query before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Versioning, and the Logical Clock

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system also carry an `updated_at` timestamp (same format as `created_at`) and an integer `version` that begins at 1 on creation and increments by one on every mutation that changes the resource; `updated_at` is refreshed to the current logical clock on each such mutation.

Time in this system is governed by a **logical clock**, never by wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z` and stays there until explicitly moved; it never falls back to real time. A `Manager` advances or sets the clock by supplying a `to_iso8601` instant. Every deadline, expiry, duration, and "current time" comparison in this document — cancellation cutoffs, no-show eligibility, elapsed table time, booking windows — reads this logical clock.

### 2.5. Monetary Precision and Rounding

All monetary amounts are integer cents; there are no fractional cents anywhere in the system. Wherever a calculation multiplies a subtotal by a percentage (a loyalty discount, a house cut, a service fee, or a deposit percentage), the product is rounded to the nearest whole cent using **round half up** — a value of exactly one-half cent rounds upward. Where a rule spans multiple priced components, the rounding order is pinned per calculation and is stated with that calculation in Section 3; readers must not reorder rounding relative to summation, because the pinned order is what the bill is reconciled against. Counts of loyalty points are also whole integers, floored per contributing line as described in Section 3.

### 2.6. Optimistic Concurrency on Room Holds

Placing a tentative hold on a private room is guarded by optimistic concurrency keyed on the room's `version`. A request to place a hold must carry `expected_room_version`, the `version` of the target `Room` that the client last observed. Because placing a new hold legitimately supersedes any prior tentative hold on the same room and bumps the room's `version`, a request that carries a stale `expected_room_version` represents a client whose view of the room was already invalidated by an earlier hold. When `expected_room_version` does not equal the room's current `version`, the hold is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite a state it has not observed. A fresh-version hold on the same room would itself succeed; the rejection is on the stale version, not on any state field.

### 2.7. Temporal Conflict Detection

Two families of resource — café tables and private rooms — enforce non-overlap of their booked time windows, but with different rules that must not be conflated.

For **tables**, a requested window `[start_at, end_at)` must be kept clear of a 15-minute turnover buffer around every existing `BOOKED` or `SEATED` reservation on the same table. The buffer is applied on both sides: a requested window conflicts with an existing one when the requested `start_at` is earlier than the existing `end_at` plus 15 minutes, and simultaneously the requested `end_at` plus 15 minutes is later than the existing `start_at`. A gap of exactly 15 minutes between the two windows is acceptable and is not a conflict. A violation is rejected with `ERR_TABLE_TIME_CONFLICT` (HTTP 409).

For **rooms**, there is no buffer at all and only `CONFIRMED` bookings are considered. Windows are half-open: a requested window conflicts with an existing `CONFIRMED` booking on the same room when the requested `start_at` is earlier than the existing `end_at` and the requested `end_at` is later than the existing `start_at`. Two windows that merely touch back-to-back — the existing booking ending at the instant the requested one begins — do not conflict and are accepted. A violation is rejected with `ERR_ROOM_TIME_CONFLICT` (HTTP 409).

### 2.8. Validation Ordering and Error Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed priority order and the first failure is the one reported. Authentication comes first: absent or invalid headers or an unknown role yield `ERR_UNAUTHENTICATED` before anything else is examined. Next is role authorization — whether the role may invoke this endpoint at all — yielding `ERR_UNAUTHORIZED`, followed by the ownership check for a `Member` acting on a resource it does not own, which also yields `ERR_UNAUTHORIZED`. Once the caller is cleared, resource existence is checked: every id in the path and then every foreign-key id in the body must resolve, validated left-to-right along the path first and then the body, failing with `ERR_NOT_FOUND`. Body well-formedness is checked next — required fields present, enums valid, integers within range, `end_at` strictly after `start_at`, `email` unique, `barcode` unique — failing with `ERR_VALIDATION`. Only then are state-machine legality (`ERR_INVALID_STATE`) and the domain-specific business constraints (capacity, suspension, availability, time conflicts, points sufficiency, and the like) evaluated. This ordering matters: a request that is both unauthorized and malformed reports the authorization failure, not the validation failure.

## 3. Business Logic & Workflows

### 3.1. Memberships, Loyalty Tiers, and Point Redemption

A `Membership` is created from an `email` and a `full_name`; the email must be unique across all memberships, and a duplicate is a malformed request. A new membership starts in `ACTIVE` status at the `BRONZE` tier, with `points_balance`, `lifetime_points`, and `no_show_strikes` all zero, and its most-recent-redemption tracking initialized so that `last_redemption_status` is `NONE`, `last_redemption_id` is null, and `last_redemption_points` is zero.

Two point counters live on every membership and behave differently. `points_balance` is the spendable balance and never goes negative. `lifetime_points` is the cumulative earned or granted total; it drives the tier and never decreases when points are spent. Tier is a computed function of `lifetime_points`: a member is `GOLD` once lifetime points reach at least 2000, `SILVER` once they reach at least 500 (but below the gold threshold), and `BRONZE` otherwise. The lower bound is inclusive — a member whose `lifetime_points` is exactly 500 is `SILVER`, and exactly 2000 is `GOLD`. The tier is recomputed whenever `lifetime_points` rises.

A `Manager` can post a loyalty adjustment carrying a `points_delta` and a `reason`. A positive `points_delta` is added to both `points_balance` and `lifetime_points`, and the tier is re-derived from the new lifetime total. A negative `points_delta` is added to `points_balance` only (decreasing it) and leaves `lifetime_points` and therefore the tier untouched.

Redemption spends points for a reward. A redemption request carries a `points_cost` and a `reward_description`. The acting membership must not be `SUSPENDED`; a suspended member attempting to redeem is rejected with `ERR_MEMBERSHIP_SUSPENDED`. The `points_cost` may not exceed the current `points_balance`; an over-redemption is rejected with `ERR_INSUFFICIENT_POINTS`. On success the `points_cost` is subtracted from `points_balance` (lifetime points are unaffected), a new redemption identifier is recorded as `last_redemption_id`, `last_redemption_points` is set to the `points_cost`, and `last_redemption_status` becomes `APPLIED`.

Reversing a redemption credits its points back. Reversal targets the redemption named by the path's `redemption_id`, and it is only valid against the most recent redemption while that redemption is still `APPLIED`. If the named redemption is not the most recent applied one — for instance because it has already been reversed — the request is rejected with `ERR_REDEMPTION_ALREADY_REVERSED`. On success, `last_redemption_points` is added back to `points_balance` and `last_redemption_status` becomes `REVERSED`.

A `Manager` changes a membership's lifecycle by supplying a new `status`. Suspending moves an `ACTIVE` membership to `SUSPENDED`; while suspended, the member cannot redeem points or register for tournaments. Reinstating moves a `SUSPENDED` membership back to `ACTIVE` and resets `no_show_strikes` to zero. Cancelling moves a membership from either `ACTIVE` or `SUSPENDED` to the terminal `CANCELLED` state, after which it is no longer usable. A status change requested from a state where that transition is not defined is rejected with `ERR_INVALID_STATE`.

### 3.2. Booking and Seating Tables

Tables are configured by a `Manager`. A `Table` has a human `label`, a `zone` (one of `MAIN`, `QUIET`, or `PATIO`, defaulting to `MAIN`), a seating capacity `seats` of at least 1, and four monetary settings: `half_hour_rate_cents` charged per started half-hour of table time, `day_pass_cents` which caps the time charge for a single session, `cover_fee_cents` charged per head, and `min_spend_cents`, the food-and-beverage minimum for a session at that table. Each of these amounts is a non-negative integer. A table begins `AVAILABLE`; a `Manager` may later update its rates or `status` — flipping it between `AVAILABLE` and `OUT_OF_SERVICE` — via the table's `half_hour_rate_cents`, `cover_fee_cents`, `min_spend_cents`, `day_pass_cents`, or `status` fields. Tables can be listed and filtered by `zone` and by `status`.

Booking a table creates a `Reservation` in `BOOKED` status. The request supplies the `table_id`, a `party_size` of at least 1, the window's `start_at` and `end_at` (with `end_at` strictly after `start_at`), and optionally a `membership_id` (absent for a non-member walk-in) and a `deposit_cents` held against the booking (defaulting to zero). Booking enforces three business checks against the referenced table: the `party_size` must not exceed the table's `seats`, or the booking is rejected with `ERR_TABLE_CAPACITY_EXCEEDED`; the table must not be `OUT_OF_SERVICE`, or the booking is rejected with `ERR_TABLE_OUT_OF_SERVICE`; and the requested window must clear the 15-minute turnover buffer of every other `BOOKED` or `SEATED` reservation on that table, as detailed in §2.7, or the booking is rejected with `ERR_TABLE_TIME_CONFLICT`. Reservations can be listed and filtered by `table_id`, by `membership_id`, and by `status`.

Seating a party advances a reservation from `BOOKED` to `SEATED`. Seating requires that the referenced table be `AVAILABLE` and that the party — which may be re-stated at seating time via an optional `party_size` — not exceed the table's `seats`; the same `ERR_TABLE_CAPACITY_EXCEEDED` and `ERR_TABLE_OUT_OF_SERVICE` checks that govern booking apply here as well. On seating, `seated_at` is stamped with the current logical clock, and `tier_at_seating` captures a snapshot of the member's current `tier` (left null for a walk-in with no membership). This snapshot, not any later tier change, is what drives the loyalty discount when the bill is computed.

### 3.3. The Running Tab, Food & Beverage, and Closing the Bill

While a party is seated, food and drink are recorded as `FnbOrder` lines against the session. Each order supplies the `reservation_id` it is charged to, a free-text `description`, and a `total_cents` line total of at least zero; a new order is `OPEN`. An order may be voided, moving it from `OPEN` to `VOID`; a `VOID` order is excluded from both the bill and the food-and-beverage minimum. Orders can be listed and filtered by `reservation_id` and by `status`. Only non-`VOID` orders count.

At any moment while a reservation is `SEATED`, reading it returns a live `provisional_bill_total_cents` — a running estimate evaluated against the current logical clock at read time. This provisional figure mirrors the final bill formula below, except that elapsed table time is measured from `seated_at` to the current logical clock rather than to a close time; for a reservation that is not `SEATED`, `provisional_bill_total_cents` is zero.

Closing a session advances the reservation from `SEATED` to `COMPLETED` and finalizes the bill. A session may not be closed while any `Checkout` referencing it is still `ACTIVE`; such an attempt is rejected with `ERR_SESSION_HAS_OPEN_CHECKOUTS`. On a successful close, `closed_at` is stamped with the current logical clock and the bill is computed component by component:

- **Table time.** The elapsed duration is the whole number of minutes from `seated_at` to `closed_at`. That duration is divided into 30-minute blocks, and any started block counts as a full block — the number of blocks is the elapsed minutes divided by 30 and rounded up to the next whole block. The raw time charge is that block count multiplied by the table's `half_hour_rate_cents`, and the final `time_charge_cents` is the smaller of that raw charge and the table's `day_pass_cents` cap.
- **Cover.** `cover_charge_cents` is the `party_size` multiplied by the table's `cover_fee_cents`.
- **Gaming subtotal and member discount.** The gaming subtotal is `time_charge_cents` plus `cover_charge_cents`. The discount percentage is keyed strictly on `tier_at_seating` (treating a null walk-in snapshot as `BRONZE`): `BRONZE` earns no discount, `SILVER` earns 10 percent, and `GOLD` earns 20 percent. `member_discount_cents` is that percentage of the gaming subtotal, rounded half up to whole cents. The discounted gaming amount is the gaming subtotal minus `member_discount_cents`.
- **Food and beverage and the minimum.** `fnb_subtotal_cents` is the sum of `total_cents` across all non-`VOID` food-and-beverage orders on the reservation. `minimum_shortfall_cents` is the amount by which the table's `min_spend_cents` exceeds `fnb_subtotal_cents`, or zero if food-and-beverage spending already met the minimum.
- **Final total.** `bill_total_cents` is the discounted gaming amount plus `fnb_subtotal_cents` plus `minimum_shortfall_cents`. Before a session is closed, `bill_total_cents` is zero.

Closing also awards loyalty points, but only on food and beverage — gaming charges earn nothing. `points_earned` is computed by taking each non-`VOID` food-and-beverage order, converting its `total_cents` to whole points at one point per 100 cents and discarding any remainder on that line, and then summing those per-line whole-point amounts. The per-line flooring is pinned to happen before summation, so multiple small lines do not pool their remainders. Until a session is closed, `points_earned` is zero.

When the closing reservation carries a `membership_id`, the award cascades onto that membership: `points_earned` is added to both `lifetime_points` and `points_balance`, and then the membership's `tier` is recomputed from the new `lifetime_points` (§3.1). Because the discount used at close is the `tier_at_seating` snapshot, this accrual can lift a member into a higher tier without retroactively changing the bill that produced it.

### 3.4. No-Shows, Cancellations, and Deposits

A booked reservation that is never honored can be cancelled or marked a no-show, and the two diverge sharply. Cancelling a reservation moves it from `BOOKED` to `CANCELLED`, but only if the current logical clock is at or before the window's `start_at` minus a two-hour (120-minute) cancellation cutoff; a cancellation at exactly 120 minutes before start is still accepted, while any later attempt is rejected with `ERR_CANCEL_TOO_LATE`. On cancellation, the deposit is released rather than charged, and `deposit_forfeited` stays false. A cancellation may be requested by `Staff`, a `Manager`, or the owning `Member`.

Marking a no-show moves a reservation from `BOOKED` to `NO_SHOW`, and is only permitted once the current logical clock has reached the window's `start_at`. A no-show forfeits the deposit: `deposit_forfeited` is set to true. If the reservation carries a `membership_id`, the no-show cascades onto the member — `no_show_strikes` is incremented by one, and if that increment brings `no_show_strikes` to three or more, the membership's `status` is driven to `SUSPENDED`. This is the same suspension that later blocks redemptions and tournament registration until a `Manager` reinstates the member.

### 3.5. The Lending Library: Checkouts, Returns, and Losses

The library tracks each physical `GameCopy` along two independent dimensions that evolve separately. One dimension is availability `status`: `AVAILABLE`, `CHECKED_OUT`, or the terminal `RETIRED`. The other is `condition`, an ordinal scale from best to worst — `MINT`, `GOOD`, `WORN`, `DAMAGED`, `LOST` — treated as grades 0 through 4 respectively. A game copy is created by a `Manager` with a `title`, a unique `barcode`, and a `replacement_value_cents`, starting `AVAILABLE` with `condition` defaulting to `GOOD`. A `Manager` may later adjust a copy's `condition` or `status` independently; setting `status` to `RETIRED` is terminal and may be applied from either `AVAILABLE` or `CHECKED_OUT`, but not to an already-`RETIRED` copy. Copies can be listed and filtered by `title`, by `status`, and by `condition`.

Lending a copy creates a `Checkout` referencing the `game_copy_id` and the `reservation_id` of the seated session borrowing it. Two conditions gate a checkout. The referenced reservation must be `SEATED` — a game may only be lent to a seated session, and otherwise the request is rejected with `ERR_INVALID_STATE`. The copy must be lendable, meaning its `status` is `AVAILABLE` and its `condition` is one of `MINT`, `GOOD`, or `WORN`; a copy that is checked out, retired, `DAMAGED`, or `LOST` is not lendable and the request is rejected with `ERR_GAME_NOT_AVAILABLE`. On a successful checkout the copy's `status` becomes `CHECKED_OUT` while its condition dimension is unchanged, `checked_out_at` is stamped with the current logical clock, and `checkout_condition` captures the copy's condition at that moment as the baseline for any return fee. A new checkout is `ACTIVE`. Checkouts can be listed and filtered by `game_copy_id`, by `reservation_id`, and by `status`.

Returning a copy moves the checkout from `ACTIVE` to `RETURNED`. The caller reports a `return_condition` (one of `MINT`, `GOOD`, `WORN`, or `DAMAGED`); `returned_at` is stamped, the copy's `status` returns to `AVAILABLE`, and its `condition` is updated to the reported `return_condition`, which may differ from the checkout baseline. The `condition_fee_cents` is computed by comparing the ordinal grades: if the returned grade is at or better than the `checkout_condition` grade (that is, its ordinal value is less than or equal to the baseline's), there is no fee. If the copy comes back worse, the fee is the number of grades it dropped — the returned grade's ordinal minus the checkout grade's ordinal — multiplied by 800 cents per grade of degradation.

Reporting a copy lost moves the checkout from `ACTIVE` to `LOST`. In this case `condition_fee_cents` is the copy's full `replacement_value_cents`, the copy's `condition` is set to `LOST`, and its `status` is driven to the terminal `RETIRED`. A session cannot be closed while a checkout against it remains `ACTIVE`, so every borrowed copy must be returned or reported lost before the bill is finalized.

### 3.6. Tournaments, Leagues, and Registrations

A `Manager` creates a `Tournament` with a `name`, a `game_title`, a `format` (one of `SINGLE_ELIM`, `LEAGUE`, or `CASUAL`), a `capacity` of at least 1, an `entry_fee_cents` funding the prize pool, and a scheduled `start_at`. A tournament begins `SCHEDULED`. Opening it moves it to `OPEN`, the only state in which registrations are accepted. Tournaments can be listed and filtered by `status` and by `format`. Two derived counts are exposed on the tournament: `registered_count` is the number of registrations that are `REGISTERED` or `CHECKED_IN`, and `checked_in_count` is the number that are `CHECKED_IN`.

Registering a member creates a `Registration` referencing the `tournament_id` and the `membership_id`. Registration is subject to several checks: the acting membership must not be `SUSPENDED`, or the request is rejected with `ERR_MEMBERSHIP_SUSPENDED`; the tournament must be `OPEN`, or the request is rejected with `ERR_TOURNAMENT_NOT_OPEN`; the count of registrations that are `REGISTERED` or `CHECKED_IN` must be strictly below the tournament's `capacity`, or the request is rejected with `ERR_TOURNAMENT_FULL`; and the member must not already hold a non-terminal registration (one that is `REGISTERED` or `CHECKED_IN`) for that tournament, or the request is rejected with `ERR_DUPLICATE_REGISTRATION`. A new registration is `REGISTERED`, and its `fee_paid_cents` snapshots the tournament's `entry_fee_cents` at that moment; `refunded_cents` is zero. A member who has withdrawn may register afresh while the tournament is still `OPEN` and not full — a new `REGISTERED` registration is created for the pair, leaving the earlier `WITHDRAWN` row as it is. Registrations can be listed and filtered by `tournament_id`, by `membership_id`, and by `status`.

Checking a registrant in moves the registration from `REGISTERED` to `CHECKED_IN`; this requires the referenced tournament to still be `OPEN` (check-in happens before the tournament starts and freezes its pool), and a check-in attempted when the tournament is not `OPEN` is rejected with `ERR_INVALID_STATE`. Withdrawing moves a registration from `REGISTERED` to `WITHDRAWN`, and is permitted while the tournament is `OPEN` or `SCHEDULED`; on withdrawal `refunded_cents` is set to the `fee_paid_cents`, refunding the entry. A withdrawal may be requested by the owning `Member` or by `Staff`.

The prize pool is derived from entry fees net of a 20 percent house cut. The gross is the number of eligible registrations multiplied by the tournament's `entry_fee_cents`; the `house_cut_cents` is 20 percent of that gross rounded half up; and the pool is the gross minus the house cut. While the tournament is `OPEN`, reading it returns a live `provisional_prize_pool_cents` in which the eligible registrations are those that are `REGISTERED` or `CHECKED_IN`. Starting the tournament moves it from `OPEN` to `RUNNING` and freezes the final figures: the eligible registrations are now only those that are `CHECKED_IN`, and from them `prize_pool_cents` and `house_cut_cents` are computed and frozen. Before a tournament starts, `prize_pool_cents` is zero.

Cancelling a tournament is available while it is `SCHEDULED` or `OPEN` and drives it to the terminal `CANCELLED` state. If it was `OPEN` with registrations, every registration that is `REGISTERED` or `CHECKED_IN` is moved to the terminal `REFUNDED` state with `refunded_cents` set to its `fee_paid_cents`; if it was merely `SCHEDULED`, there are no registrations to refund. A tournament that reaches `RUNNING` is eventually driven to the terminal `COMPLETED` state by the system; that transition is declared for completeness and is not exposed as a v1 operation.

### 3.7. Private Rooms and Party Bookings

Private rooms are configured by a `Manager`. A `Room` has a `name`, a headcount `capacity` of at least 1, and an `hourly_rate_cents` charged per started 60-minute block of room time; it begins `AVAILABLE` and may be taken to `OUT_OF_SERVICE`. A `Manager` may update a room's `status`, `hourly_rate_cents`, or `capacity`. Rooms can be listed and filtered by `status`.

Placing a hold creates a `PrivateBooking` referencing the `room_id`, with a window `start_at` and `end_at` (`end_at` strictly after `start_at`), a `headcount` of at least 1, and the `expected_room_version` required by the optimistic-concurrency rule of §2.6. A hold is only accepted when the room is `AVAILABLE`; a hold against an `OUT_OF_SERVICE` room is rejected with `ERR_ROOM_UNAVAILABLE`. The requested window must not overlap any `CONFIRMED` booking on the room under the zero-buffer half-open rule of §2.7, or the request is rejected with `ERR_ROOM_TIME_CONFLICT`. A room holds at most one active tentative booking: creating a new hold moves any prior `HELD` booking on the same room to the `SUPERSEDED` state, released without charge, and increments the room's `version` by one. A new booking is `HELD`.

At create time the booking's quote is computed and its deposit derived, with each priced component rounded to whole cents before the components are summed. Room time is billed by the hour with any started hour counting fully: the room hours are the whole minutes of the window divided by 60 and rounded up to the next whole hour, and the room charge is those hours multiplied by the room's `hourly_rate_cents`. Catering is the `headcount` multiplied by 1500 cents per head. The service fee is 18 percent of the sum of the room charge and catering, rounded half up. The `quoted_total_cents` is the room charge plus catering plus the service fee. The `deposit_cents` is 25 percent of the `quoted_total_cents`, rounded half up.

Confirming a booking moves it from `HELD` to `CONFIRMED`, but only if the booking's `headcount` does not exceed the referenced room's `capacity`. A confirmed booking becomes firm and participates in the overlap checks against future holds. Cancelling a booking is available while it is `HELD` or `CONFIRMED` and moves it to the terminal `CANCELLED` state. A confirmed booking is eventually driven to the terminal `COMPLETED` state by the system; that transition is declared for completeness and is not exposed as a v1 operation. Private bookings can be listed and filtered by `room_id` and by `status`.

### 3.8. Retail Sales and Pre-Orders

The retail counter sells games either from stock or as pre-orders. A `RetailOrder` is created with a `product_title`, a `fulfillment_type` (`IN_STOCK` for an immediate sale or `PREORDER` for one awaiting stock), a `quantity` of at least 1, a `unit_price_cents`, and optionally a `membership_id` (absent for a walk-in sale). The `total_cents` is computed at create as the `quantity` multiplied by the `unit_price_cents`. An `IN_STOCK` order is immediately `READY`; a `PREORDER` order starts `AWAITING_STOCK`. Orders can be listed and filtered by `membership_id`, by `status`, and by `fulfillment_type`.

Fulfilling an order hands it to the customer and moves it to the terminal `FULFILLED` state; fulfillment is accepted from either `READY` or `AWAITING_STOCK`, so a pre-order can be fulfilled once its stock arrives. Cancelling an order moves it from `READY` or `AWAITING_STOCK` to the terminal `CANCELLED` state. A fulfillment or cancellation requested from a state where that transition is not defined is rejected with `ERR_INVALID_STATE`. The owning `Member` may place and cancel its own retail orders; `Staff` and `Manager` may operate on any.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Creating a new resource returns HTTP 201 with the created resource; reads, list operations, and state-changing actions on existing resources return HTTP 200 with the affected resource (or, for the clock, an empty data object). Every response uses the envelope of §2.2. Request bodies, response payloads, and side effects for each operation are described in Sections 2 and 3; the table below is the transport index only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock | Manager |
| POST | `/tables` | Create a table | Manager |
| GET | `/tables/{id}` | Get a table | Manager, Staff, Member |
| GET | `/tables` | List tables | Manager, Staff, Member |
| PATCH | `/tables/{id}` | Update a table or take it out of service | Manager |
| POST | `/memberships` | Create a membership | Manager, Staff |
| GET | `/memberships/{id}` | Get a membership | Manager, Staff, Member |
| GET | `/memberships` | List memberships | Manager, Staff |
| PATCH | `/memberships/{id}` | Suspend, reinstate, or cancel a membership | Manager |
| POST | `/memberships/{id}/loyalty-adjustments` | Grant or deduct loyalty points | Manager |
| POST | `/memberships/{id}/redemptions` | Redeem loyalty points | Member, Staff |
| POST | `/memberships/{id}/redemptions/{redemption_id}/reverse` | Reverse the most recent redemption | Manager, Staff |
| POST | `/reservations` | Book a table for a time window | Manager, Staff, Member |
| GET | `/reservations/{id}` | Get a reservation | Manager, Staff, Member |
| GET | `/reservations` | List reservations | Manager, Staff, Member |
| POST | `/reservations/{id}/seat` | Seat the party | Manager, Staff |
| POST | `/reservations/{id}/close` | Close the session and finalize the bill | Manager, Staff |
| POST | `/reservations/{id}/cancel` | Cancel a booking before the cutoff | Manager, Staff, Member |
| POST | `/reservations/{id}/no-show` | Mark a no-show | Manager, Staff |
| POST | `/fnb-orders` | Add a food & beverage line | Manager, Staff |
| GET | `/fnb-orders/{id}` | Get an F&B order | Manager, Staff |
| GET | `/fnb-orders` | List F&B orders | Manager, Staff |
| POST | `/fnb-orders/{id}/void` | Void an F&B line | Manager, Staff |
| POST | `/game-copies` | Add a library game copy | Manager |
| GET | `/game-copies/{id}` | Get a game copy | Manager, Staff, Member |
| GET | `/game-copies` | List game copies | Manager, Staff, Member |
| PATCH | `/game-copies/{id}` | Update a game copy's condition or retire it | Manager |
| POST | `/checkouts` | Check out a game copy to a seated session | Manager, Staff |
| GET | `/checkouts/{id}` | Get a checkout | Manager, Staff |
| GET | `/checkouts` | List checkouts | Manager, Staff |
| POST | `/checkouts/{id}/return` | Return a checked-out copy | Manager, Staff |
| POST | `/checkouts/{id}/report-lost` | Report a checked-out copy lost | Manager, Staff |
| POST | `/tournaments` | Create a tournament or league | Manager |
| GET | `/tournaments/{id}` | Get a tournament | Manager, Staff, Member |
| GET | `/tournaments` | List tournaments | Manager, Staff, Member |
| POST | `/tournaments/{id}/open` | Open registration | Manager |
| POST | `/tournaments/{id}/start` | Start the tournament and freeze the pool | Manager |
| POST | `/tournaments/{id}/cancel` | Cancel a tournament | Manager |
| POST | `/registrations` | Register a member for an open tournament | Manager, Staff, Member |
| GET | `/registrations/{id}` | Get a registration | Manager, Staff, Member |
| GET | `/registrations` | List registrations | Manager, Staff, Member |
| POST | `/registrations/{id}/check-in` | Check a registrant in | Manager, Staff |
| POST | `/registrations/{id}/withdraw` | Withdraw a registration and refund the fee | Manager, Staff, Member |
| POST | `/rooms` | Create a private room | Manager |
| GET | `/rooms/{id}` | Get a room | Manager, Staff, Member |
| GET | `/rooms` | List rooms | Manager, Staff, Member |
| PATCH | `/rooms/{id}` | Update a room or take it out of service | Manager |
| POST | `/private-bookings` | Place a hold on a room | Manager, Staff |
| GET | `/private-bookings/{id}` | Get a private booking | Manager, Staff, Member |
| GET | `/private-bookings` | List private bookings | Manager, Staff, Member |
| POST | `/private-bookings/{id}/confirm` | Confirm a held booking | Manager, Staff |
| POST | `/private-bookings/{id}/cancel` | Cancel a held or confirmed booking | Manager, Staff |
| POST | `/retail-orders` | Create a retail sale or pre-order | Manager, Staff, Member |
| GET | `/retail-orders/{id}` | Get a retail order | Manager, Staff, Member |
| GET | `/retail-orders` | List retail orders | Manager, Staff, Member |
| POST | `/retail-orders/{id}/fulfill` | Fulfill or hand over an order | Manager, Staff |
| POST | `/retail-orders/{id}/cancel` | Cancel a retail order | Manager, Staff, Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SESSION_HAS_OPEN_CHECKOUTS` | 409 |
| `ERR_MEMBERSHIP_SUSPENDED` | 409 |
| `ERR_GAME_NOT_AVAILABLE` | 409 |
| `ERR_TABLE_CAPACITY_EXCEEDED` | 409 |
| `ERR_TABLE_OUT_OF_SERVICE` | 409 |
| `ERR_TOURNAMENT_FULL` | 409 |
| `ERR_TOURNAMENT_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_TABLE_TIME_CONFLICT` | 409 |
| `ERR_ROOM_TIME_CONFLICT` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_CANCEL_TOO_LATE` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_REDEMPTION_ALREADY_REVERSED` | 409 |
