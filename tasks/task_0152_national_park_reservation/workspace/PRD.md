# National Park Reservation API — Product Requirements Document

## 1. Introduction

The National Park Reservation API is the booking spine for a Recreation.gov-style platform that coordinates entry into America's national parks. A typical park hosts several intersecting access regimes — daily timed-entry windows for vehicles, multi-night campground stays with strict consecutive-night caps, scarce backcountry zones policed by ranger-buffer rules, and high-demand lottery permits (Half Dome, The Wave) that are awarded by random draw weeks in advance. The same visitor often interacts with several of these at once, and the same park may have to retire capacity, suspend new bookings entirely, or simultaneously honour confirmed visits already in the pipeline. The API is the single source of truth for who is allowed in, when, and for what fee.

Beyond simple booking, the system mediates real money. Each visitor carries a credit wallet that is debited at confirmation and credited on refunds, with a complete ledger trail. An America the Beautiful Pass can waive entry fees outright. A no-show on a lottery permit or campground night raises a strike against the visitor; three strikes lock that visitor out of new lottery applications and out of group campsites for the remainder of the calendar year. Mistakes are real — both for the visitor's wallet and for the park's available inventory — so the contract below specifies exactly how concurrent attempts on the last slot of the last window of the last day must serialise, exactly how refunds taper with time-to-go, and exactly how a lottery's award expiration cascades back through the waitlist.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry the two authentication headers `X-User-ID` and `X-User-Role`. Missing, malformed, or unparseable headers result in `ERR_UNAUTHENTICATED`. The system recognises four roles, each spelled exactly as listed: `Visitor`, `ParkAdmin`, `ParkRanger`, and `SystemOperator`. When a caller's role is well-formed but not authorised for the requested endpoint, the request is rejected with `ERR_FORBIDDEN`.

The `Visitor` role is **entity-backed**: when `X-User-Role` is `Visitor`, the supplied `X-User-ID` is the `id` of the acting `Visitor` resource. Ownership checks on any resource that references a visitor (a campground reservation, a timed-entry reservation, a backcountry permit, a lottery application, a waitlist entry, an America the Beautiful Pass, a ledger entry) compare the resource's `visitor_id` to `X-User-ID`, and confirm/cancel/accept/decline actions on a resource owned by another visitor are rejected with `ERR_FORBIDDEN`.

The remaining three roles — `ParkAdmin`, `ParkRanger`, and `SystemOperator` — are **opaque operator identifiers** not tied to any persisted entity. When `X-User-Role` is `ParkAdmin`, `ParkRanger`, or `SystemOperator`, `X-User-ID` is recorded for audit but is not compared to any entity's `id`; these operators may act on any park-scoped resource the RBAC matrix in §4 permits them to act on.

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

List endpoints accept two query parameters. The `limit` query parameter caps the number of items returned; if omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` query parameter is the number of items to skip from the start of the list and defaults to 0.

Unless an endpoint explicitly says otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. `total_count` is the total number of items matching the query, and `has_more` is true when more items exist beyond the current page.

### 2.4. Common Resource Properties

All primary entities — `Park`, `Visitor`, `AmericaTheBeautifulPass`, `Campground`, `LotteryPermit`, `BackcountryZone`, `TimedEntryReservation`, `CampgroundReservation`, `LotteryApplication`, and `BackcountryPermit` — carry the same four system-managed fields:

- `id` is a server-minted UUID with no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of resource creation.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` is a non-negative integer that begins at 1 on creation and increments by one on every mutation.

Two entities are append-only event records and therefore omit the mutation-tracking fields. The `WaitlistEntry` and `LedgerEntry` resources carry only `id` and `created_at` — both `updated_at` and `version` are absent because rows of these kinds are never modified in place; status changes on a `WaitlistEntry` are still recorded by mutating `status` and `promoted_reservation_id`, but neither `updated_at` nor `version` is exposed for them.

Any state-machine transition, side-effect cascade, computed-field recalculation, or PATCH that modifies an entity counts as a mutation and triggers both `updated_at` and `version` to advance.

### 2.5. Optimistic Concurrency Control

PATCH endpoints accept an optional `version` field in their request body. When `version` is supplied and does not equal the resource's current version on the server, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server performs the mutation without an OCC check. The same OCC mechanism is the serialisation point for the concurrent PATCH race: two callers updating the same `Campground` with stale `version` values resolve such that the higher-version writer wins and the stale one receives `ERR_VERSION_CONFLICT`.

### 2.6. Nested Resource Retrieval and Path Validation

Whenever an endpoint path contains nested identifiers — for example a campground reservation referenced under a campground, or a permit under a backcountry zone — the system resolves each identifier in left-to-right order and rejects the request immediately with `ERR_NOT_FOUND` when any one is unknown. A campground reservation requested under a non-existent campground returns `ERR_NOT_FOUND` keyed to the missing campground, without ever attempting to find the reservation.

### 2.7. Park Operational Posture

A park carries a `status` of `OPEN`, `RESTRICTED`, or `FROZEN`. Only a `ParkAdmin` may move a park between these statuses. From `OPEN` the park may be moved to `RESTRICTED` (suspending the most exposed booking flows while leaving campground bookings alive) or directly to `FROZEN`. From `RESTRICTED` the park may be moved back to `OPEN` or onward to `FROZEN`. From `FROZEN` the park may only be returned to `OPEN`. Each transition checks the park's current `status` and rejects mismatched attempts with `ERR_INVALID_STATE`.

When the park is `RESTRICTED`, new timed-entry reservation creation and new backcountry permit creation are blocked with `ERR_PARK_RESTRICTED`, but new campground reservation creation continues to be allowed. When the park is `FROZEN`, every form of new reservation creation, every new lottery application, every new backcountry permit, and lottery draws themselves are blocked with `ERR_PARK_FROZEN`; existing `CONFIRMED` reservations are retained and may still be cancelled.

### 2.8. Monetary Values, Fees, and Precision

All monetary amounts are stored and returned as integer USD cents. Wallet balances, ledger amounts, fees, and refund amounts are integer counts of cents — no floating-point intermediates appear in stored values. Where a calculation produces a fractional cent value (for example, applying a percentage to a fee, or applying tax to a subtotal), the result is **truncated towards zero (floor)** to an integer cent before being written or compared. The `Visitor.wallet_balance_cents` field never goes below zero; debit operations that would do so are rejected with `ERR_INSUFFICIENT_FUNDS`.

### 2.9. Wallet, Ledger, and the Fee Cycle

Every fee event is captured by a `LedgerEntry` row keyed to the affected `Visitor`. A ledger entry carries a `visitor_id`, a `kind` drawn from `{DEPOSIT, FEE_CHARGE, FEE_REFUND, LOTTERY_FEE, PERMIT_FEE, ADJUSTMENT}`, a signed `amount_cents` (positive credits the wallet, negative debits it), a `reference_kind` drawn from `{TimedEntryReservation, CampgroundReservation, BackcountryPermit, LotteryApplication, None}`, and an optional `reference_id` that points at the paired reservation, permit, or application. Deposits and adjustments use `reference_kind` of `None` and leave `reference_id` null. Every successful debit at confirm-time, every refund at cancel-time, every lottery application fee, every accepted lottery-permit fee, and every wallet deposit produces exactly one ledger entry, and `Visitor.wallet_balance_cents` is the running sum of all `amount_cents` values for that visitor.

### 2.10. Park-Local Time and Window Alignment

A park's `timezone` is an IANA zone string (e.g., `"America/Los_Angeles"`) and governs how park-local dates and times are interpreted. Timed-entry windows are park-local: an entry's `entry_date_local` is a `YYYY-MM-DD` string in the park's timezone and `window_start_local` is an `HH:MM` string in the park's timezone. Each park exposes a `timed_entry_window_minutes` (default 60), which must evenly divide 1440, and that value sets the size of every window. A `window_start_local` is valid only when the number of minutes from midnight is an exact multiple of `timed_entry_window_minutes`; misalignment returns `ERR_WINDOW_MISALIGNED`. The computed `window_end_local` is `window_start_local` plus `timed_entry_window_minutes` in the same park-local clock.

The park's `timed_entry_daily_capacity` caps the total number of vehicles admitted across all timed-entry windows on the same local calendar day. The capacity counter is keyed by the tuple of `(park_id, entry_date_local, window_start_local)` for collision purposes (one window's slots are independent of another window's slots), but the daily aggregate cannot exceed `timed_entry_daily_capacity`.

### 2.11. Held-Slot Inventory and Concurrency

Every reservation and permit begins life in a `HELD` status. A `HELD` row holds capacity but has not yet been paid for. Each `HELD` row carries a `held_until` UTC instant computed at creation time:

- A `HELD` `TimedEntryReservation` auto-expires 15 minutes after creation.
- A `HELD` `CampgroundReservation` auto-expires 15 minutes after creation.
- A `HELD` `BackcountryPermit` auto-expires 15 minutes after creation.
- A `HELD` `CampgroundReservation` that is created by waitlist promotion is held for 4 hours after creation (this is the only exception to the 15-minute rule).

Until that instant arrives, the row's inventory remains reserved against new attempts. Once the instant passes — either because a `SystemOperator` runs the sweep or because the visitor cancels — the row transitions to `CANCELLED` and its inventory is released. A confirmation attempt after `held_until` has passed is rejected with `ERR_INVALID_STATE`.

When two visitors race for the last unit of capacity in the same slot, the system serialises them with strict first-writer-wins semantics, and the loser of each race receives a specific `error_id`:

- Two visitors race to hold the last `STANDARD` site for the same nights at the same campground: serialisation is first-writer-wins on the campground's `standard_site_count` counter for that date range; the loser receives `ERR_CAMPGROUND_FULL`.
- Two visitors race to hold the last timed-entry slot in the same `(park_id, entry_date_local, window_start_local)` tuple: serialisation is first-writer-wins on that tuple's counter; the loser receives `ERR_TIMED_ENTRY_FULL`.
- A visitor's confirmation lands concurrently with the sweep's `held_until` expiry of the same `HELD` reservation: serialisation is first-writer-wins on the reservation's `status` exit from `HELD`; if the sweep wins, the visitor receives `ERR_INVALID_STATE`.
- Two `ParkAdmin` operators race two PATCHes on the same `Campground` with overlapping stale `version` values: serialisation is via OCC on `Campground.version`; the higher-version writer wins and the loser receives `ERR_VERSION_CONFLICT`.
- Two simultaneous draws are POSTed against the same `LotteryPermit`: serialisation is first-writer-wins on the lottery's `status` transition from `CLOSED` to `DRAWN`; the second draw receives `ERR_LOTTERY_ALREADY_DRAWN`.
- A visitor simultaneously accepts and declines the same `AWARDED` `LotteryApplication`: serialisation is first-writer-wins on the application's `status` exit from `AWARDED`; the loser receives `ERR_INVALID_STATE`.
- Two `HELD` `BackcountryPermit` creations land overlapping ranger-buffer windows at the same trailhead: serialisation is first-writer-wins on the zone's interval-tree insert by `entry_datetime_local`; the loser receives `ERR_RANGER_BUFFER_VIOLATION`.

### 2.12. Validation Priority

Every endpoint walks its validations in a fixed priority order. The order is observable: when two conditions both fail on the same request, the lower-priority error code surfaces, not the higher-numbered one. The order is:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and well-formed; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role must be permitted for the endpoint per the RBAC matrix; otherwise `ERR_FORBIDDEN`.
3. **Existence.** Every path identifier resolves left-to-right to an existing entity; otherwise `ERR_NOT_FOUND`.
4. **State.** The target entity is in a status that permits the requested transition (e.g., a `HELD` reservation is the only state that may be confirmed); otherwise `ERR_INVALID_STATE`.
5. **Park posture.** Park-level frozen and restricted blocks (`ERR_PARK_FROZEN`, `ERR_PARK_RESTRICTED`) apply before any business-domain checks. A `FROZEN` park blocks every reservation/permit/lottery creation and every lottery draw; a `RESTRICTED` park blocks timed-entry creation and backcountry-permit creation but still permits campground reservations.
6. **Strike-limit gates.** For new lottery applications and for new `GROUP` campground reservations, a `Visitor` whose `lottery_strikes` is 3 is rejected with `ERR_STRIKE_LIMIT_REACHED`. The group-site strike check fires before the capacity check, so a strike-flagged visitor sees `ERR_STRIKE_LIMIT_REACHED` even when the group site has no inventory left.
7. **Pass referential validity.** When a timed-entry reservation includes a `pass_id`, the referenced pass must belong to the requesting visitor and must be `ACTIVE` at `entry_date_local`; otherwise `ERR_PASS_INVALID`.
8. **Business temporal checks.** Timed-entry `entry_date_local` is within 30 days of now in park-local time and not in the past (`ERR_OUT_OF_BOOKING_WINDOW`); `window_start_local` aligns to the window boundary (`ERR_WINDOW_MISALIGNED`); campground `check_out_date_local` is strictly after `check_in_date_local`, the number of nights is strictly greater than zero, and the number of nights does not exceed the campground's `max_consecutive_nights` (`ERR_STAY_TOO_LONG`); lottery application submission time is within the half-open interval `[lottery_open_at, lottery_close_at)` (`ERR_LOTTERY_CLOSED`).
9. **Business constraints.** Campground `party_size` matches `site_kind` (a `STANDARD` site requires `party_size` from 1 through 6 inclusive, a `GROUP` site requires `party_size` from 7 through 40 inclusive); otherwise `ERR_PARTY_SIZE_INVALID`. Lottery `party_size` does not exceed the permit's `per_application_max_party`; otherwise `ERR_PARTY_SIZE_INVALID`. Backcountry confirm checks the ranger-buffer time-collision first (`ERR_RANGER_BUFFER_VIOLATION`) and the nightly people-quota second (`ERR_BACKCOUNTRY_FULL`) — the buffer check always precedes the quota check.
10. **Inventory.** Timed-entry remaining capacity for the `(park, date, window)` triple is greater than zero (`ERR_TIMED_ENTRY_FULL`); campground `site_kind` inventory is available for the full date range (`ERR_CAMPGROUND_FULL`).
11. **Fiscal.** At confirm time and at lottery accept time, `Visitor.wallet_balance_cents` is at least the computed fee; otherwise `ERR_INSUFFICIENT_FUNDS`.
12. **OCC.** On PATCH endpoints, the provided `version` equals the current entity version; otherwise `ERR_VERSION_CONFLICT`.

Generic schema or value-range violations on input fields that do not fit one of the above categories surface as `ERR_VALIDATION`.

### 2.13. The Test Driver: Virtual Clock and Sweep

Because almost every interesting transition is time-gated — a hold expires after 15 minutes, an awarded lottery slot expires 72 hours after the draw, a campground reservation rolls forward to `COMPLETED` after the 11:00 park-local check-out hour — the system exposes a `SystemOperator`-only test-driving capability that advances the logical clock to a supplied `target_iso` instant, and a separate sweep capability that runs the deferred-action sweep at the current clock. Advancing the clock does not by itself trigger any transitions; the sweep is what reconciles state with the new clock. The sweep is idempotent within a single clock instant: running it twice in a row at the same logical instant has the same effect as running it once.

The sweep performs five jobs in a single pass: it expires `HELD` reservations and permits whose `held_until` is now in the past; it forfeits `AWARDED` lottery applications whose `award_expires_at` is now in the past and promotes the next waitlisted application; it advances `CONFIRMED` campground reservations to `NO_SHOW` or `COMPLETED` based on the park-local check-in and check-out hours; it advances `CONFIRMED` timed-entry reservations to `NO_SHOW` past the window-end-plus-one-hour mark; and it promotes eligible `WaitlistEntry` rows whose check-in date is within the campground's `waitlist_window_hours`.

## 3. Business Logic & Workflows

### 3.1. Visitor Identity, Wallets, and the America the Beautiful Pass

A visitor enters the system as a `Visitor` record minted by a `SystemOperator`. The record carries an `email` (RFC 5322 compliant, unique across the system), a `full_name` (1 through 120 characters), and the two computed counters that govern the visitor's commercial standing: `wallet_balance_cents`, which begins at 0, and `lottery_strikes`, which also begins at 0. Strikes accumulate across the calendar year and may reach 3, at which point the visitor is blocked from new lottery applications and from new `GROUP` campground reservations.

A `ParkAdmin` may issue an America the Beautiful Pass to a visitor. The pass carries the owning `visitor_id`, a `pass_type` drawn from `{ANNUAL, SENIOR_ANNUAL, SENIOR_LIFETIME, MILITARY, ACCESS, VOLUNTEER, FOURTH_GRADE}`, a server-minted twelve-character unique `serial`, a `valid_from` UTC instant, a `valid_until` UTC instant, and a `status` of `ACTIVE`, `EXPIRED`, or `REVOKED`. For a `SENIOR_LIFETIME` pass the system stores a sentinel far-future date in `valid_until`. The `ParkAdmin` may also revoke an active pass; the pass status moves to `REVOKED` and the pass is no longer accepted for entry-fee waivers.

A visitor's wallet receives funds via the wallet-deposit capability — either the visitor deposits into their own wallet or a `SystemOperator` tops up any visitor's wallet — with the deposit amount specified in the request body as `amount_cents`. Each deposit writes one `LedgerEntry` with `kind` of `DEPOSIT` and a positive `amount_cents`.

### 3.2. Provisioning Parks, Campgrounds, Zones, and Lottery Permits

A `ParkAdmin` provisions a park by supplying its `name` (1 through 120 characters, unique), its short `code` (2 through 10 characters of uppercase letters and digits, unique, matching the pattern `^[A-Z0-9]+$`), its IANA `timezone`, its `timed_entry_daily_capacity`, and optionally its `timed_entry_window_minutes` (defaulting to 60 when not supplied; must evenly divide 1440). A newly created park starts in the `OPEN` status. The `ParkAdmin` may later update the park's profile through a PATCH that accepts an optional `version` for OCC and an optional `name`, `timed_entry_daily_capacity`, and `timed_entry_window_minutes`.

Under a park, the `ParkAdmin` defines campgrounds. Each `Campground` carries the parent `park_id`, a `name` unique within that park (1 through 120 characters), a `standard_site_count` and a `group_site_count`, the per-night cost of each site class as `nightly_standard_fee_cents` and `nightly_group_fee_cents`, an optional `max_consecutive_nights` (1 through 30, defaulting to 14) that caps how many nights one party may book in a rolling window, and an optional `waitlist_window_hours` (1 through 168, defaulting to 24) that defines how many hours before a desired check-in the waitlist promotion eligibility opens.

The `ParkAdmin` similarly defines backcountry zones. A `BackcountryZone` carries the parent `park_id`, a `name` unique within that park (1 through 80 characters), a `nightly_quota_people` cap on overnight headcount in the zone, an optional `ranger_buffer_minutes` (0 through 720, defaulting to 30) that sets the mandatory minimum gap between two consecutive permits exiting and entering the zone at the same trailhead, and a `per_party_fee_cents` flat permit fee that does not scale with the number of nights.

Lottery permits are the rarest inventory in the system. The `ParkAdmin` creates a `LotteryPermit` against a park by supplying the parent `park_id`, the permit `name` (1 through 80 characters, unique within the park), four UTC instants — `lottery_open_at`, `lottery_close_at`, `draw_at`, and `hike_date` — and the four numeric inputs that drive the draw: `daily_slot_count` (the total number of award slots offered for `hike_date`, at least 1), `per_application_max_party` (the per-application cap on `party_size`, 1 through 12, defaulting to 6), `application_fee_cents` (the non-refundable fee charged at application submission), and `permit_fee_cents` (the fee charged per awarded slot when the visitor accepts). The lottery moves through `OPEN`, `CLOSED`, `DRAWN`, and `ARCHIVED` over its life.

### 3.3. Timed-Entry Reservations

A `Visitor` initiates a timed-entry reservation by supplying their `vehicle_plate` (1 through 10 characters, uppercased on persist), an `entry_date_local`, a `window_start_local`, and an optional `pass_id`. The system stores the parent `park_id`, computes `window_end_local` as `window_start_local` plus the park's `timed_entry_window_minutes`, and decides `entry_fee_cents`: when a valid `pass_id` is supplied and the referenced America the Beautiful Pass belongs to the requesting visitor and is `ACTIVE` at `entry_date_local`, the entry fee is set to 0; otherwise it is the park's standard entry fee. The reservation is created in `HELD` status with `held_until` set to 15 minutes after creation, and the system decrements the remaining capacity counter for the `(park_id, entry_date_local, window_start_local)` tuple.

Several gates fire at creation time. `entry_date_local` must be at least the current park-local date and at most 30 days ahead; outside that window the request is rejected with `ERR_OUT_OF_BOOKING_WINDOW`. The number of minutes from park-local midnight encoded by `window_start_local` must be an exact multiple of `timed_entry_window_minutes`; otherwise the request is rejected with `ERR_WINDOW_MISALIGNED`. The remaining capacity for the `(park, date, window)` triple must be strictly greater than zero; otherwise the request is rejected with `ERR_TIMED_ENTRY_FULL`. If `pass_id` references a pass not owned by the requesting visitor or whose status is not `ACTIVE` at `entry_date_local`, the request is rejected with `ERR_PASS_INVALID`.

Confirming a `HELD` timed-entry reservation requires that the reservation still be in `HELD`, that the current UTC instant precede `held_until`, that the park's `status` be `OPEN`, and that `Visitor.wallet_balance_cents` be at least `entry_fee_cents`. On success the reservation transitions from `HELD` to `CONFIRMED`, the wallet is debited by `entry_fee_cents`, and a `LedgerEntry` of `kind` `FEE_CHARGE` referencing the timed-entry reservation is appended.

A `HELD` reservation may be cancelled at any time; whether by an explicit visitor cancel or by the sweep crossing `held_until`, the row transitions from `HELD` to `CANCELLED` and the system releases the capacity counter for the `(date, window)` pair. A `CONFIRMED` reservation may also be cancelled by the owning visitor at any time strictly before the park-local entry window start; on success the reservation transitions from `CONFIRMED` to `CANCELLED`, the system computes the refund using the timed-entry tiered-refund rule, debits or credits the wallet accordingly via a `LedgerEntry` of `kind` `FEE_REFUND`, and releases the capacity counter.

The timed-entry tiered-refund rule is as follows. Let the "hours to entry" be the number of hours between now (in UTC) and the entry-window start (converted from park-local to UTC). When that number is at least 168 (seven days), the refund is the full `entry_fee_cents`. When the number is at least 48 but less than 168, the refund is `entry_fee_cents` multiplied by one-half, with the result floored to an integer cent. When the number is less than 48, the refund is zero. The full-window constant for this rule is 168 hours, the half-window constant is 48 hours, and the half-rate is one-half. There is one variant: when the original `entry_fee_cents` was zero because a valid pass was supplied at confirm time, the refund is always zero regardless of timing — every tier above collapses to zero because the fee was zero.

A `ParkRanger` may check a `CONFIRMED` timed-entry reservation in at the gate. Check-in is permitted only when the current park-local time falls within the inclusive range `[window_start_local, window_end_local]`; on success the reservation transitions from `CONFIRMED` to `USED`. The sweep itself catches the unattended reservations: when a `CONFIRMED` reservation's park-local time has moved past `window_end_local` by more than 60 minutes, the sweep transitions it from `CONFIRMED` to `NO_SHOW` with no refund issued.

### 3.4. Campground Reservations

A `Visitor` reserves a campsite by submitting `site_kind` (drawn from `{STANDARD, GROUP}`), `party_size`, `check_in_date_local`, and `check_out_date_local` against a campground. The system stores the parent `campground_id`, computes the integer `nights` field as `check_out_date_local` minus `check_in_date_local`, snapshots `nightly_rate_cents` from the campground's `nightly_standard_fee_cents` for a `STANDARD` site or `nightly_group_fee_cents` for a `GROUP` site, computes `total_fee_cents` per the booking-total rule below, places the reservation in `HELD` status, sets `held_until` to 15 minutes after creation, and snapshots `refund_cents` at 0 (it will be populated only if the reservation is later cancelled).

Several gates fire at creation time. `check_out_date_local` must be strictly after `check_in_date_local`, and the resulting `nights` must be strictly greater than zero and not exceed the campground's `max_consecutive_nights`; otherwise the request is rejected with `ERR_STAY_TOO_LONG`. The supplied `party_size` must match the `site_kind`: 1 through 6 inclusive for `STANDARD`, 7 through 40 inclusive for `GROUP`; otherwise the request is rejected with `ERR_PARTY_SIZE_INVALID`. The campground must have `site_kind` inventory available across the entire date range; otherwise the request is rejected with `ERR_CAMPGROUND_FULL`. When `site_kind` is `GROUP`, the strike-limit gate fires first: a visitor with `lottery_strikes` of 3 is rejected with `ERR_STRIKE_LIMIT_REACHED` before the inventory check is run.

The booking-total rule computes `total_fee_cents` as follows. Let `nights` be `check_out_date_local` minus `check_in_date_local` in calendar days. Let `nightly_rate_cents` be `nightly_standard_fee_cents` when `site_kind` is `STANDARD`, otherwise `nightly_group_fee_cents`. Compute the site total as `nightly_rate_cents` multiplied by `nights`; both operands are already integer cents, so the product is exact. Add the fixed booking fee of 800 cents to produce the pre-tax subtotal. Compute the tax amount as the pre-tax subtotal multiplied by the tax rate of 0.08, then floor that tax amount to an integer cent. The `total_fee_cents` value is the pre-tax subtotal plus the floored tax amount. The order is pinned: tax is applied to the rounded-integer pre-tax subtotal, then floored, and only then added — the system never floors each nightly rate independently.

Confirming a `HELD` campground reservation requires that the reservation still be in `HELD`, that the current UTC instant precede `held_until`, that the park's `status` be either `OPEN` or `RESTRICTED` (campgrounds remain bookable in `RESTRICTED`), that `Visitor.wallet_balance_cents` be at least `total_fee_cents`, and — when `site_kind` is `GROUP` — that `Visitor.lottery_strikes` be strictly less than 3 (the strike check applies on confirm for group sites as well as on create, so a strike that accrues between hold and confirm blocks the confirm). On success the reservation transitions from `HELD` to `CONFIRMED`, the wallet is debited by `total_fee_cents`, and a `LedgerEntry` of `kind` `FEE_CHARGE` is appended.

A `HELD` campground reservation may be cancelled at any time; whether by an explicit visitor cancel or by the sweep crossing `held_until`, the row transitions from `HELD` to `CANCELLED`, the system releases site occupancy for the `[check_in_date_local, check_out_date_local)` range, and the system runs a waitlist-promotion sweep on that campground (cascade depth two — the campground's freed inventory may itself create a new `HELD` `CampgroundReservation` for the next eligible waitlisted visitor). A `CONFIRMED` campground reservation may be cancelled by the owning visitor only while the park-local time is strictly before 16:00 on `check_in_date_local`; on success the reservation transitions from `CONFIRMED` to `CANCELLED`, the refund is computed per the campground tiered-refund rule below and written to `refund_cents` on the reservation, a `LedgerEntry` of `kind` `FEE_REFUND` with `amount_cents` equal to the refund credits the wallet, the site occupancy is released, and the waitlist-promotion cascade fires: a fresh `CampgroundReservation` may be created in `HELD` for the next eligible `WaitlistEntry`, and that waitlist entry's `status` is set to `PROMOTED` (cascade depth three — cancel produces freed inventory, which may produce a promoted reservation, which itself flips the waitlist entry's status).

The campground tiered-refund rule is as follows. Let "hours to check-in" be the number of hours between now (in UTC) and the check-in instant (interpreted as `check_in_date_local` at 00:00 park-local, converted to UTC). The fixed booking fee constant is 800 cents. The fourteen-day constant is 336 hours, the three-day constant is 72 hours, and the one-day constant is 24 hours; the half-rate is one-half. The rule is "floor per intermediate" — every percentage step is floored to an integer cent before any other component is added or subtracted.

- When hours to check-in is at least 336 (fourteen days), the refund is `total_fee_cents` minus the 800-cent booking fee, so the visitor forfeits only the booking fee.
- When hours to check-in is at least 72 (three days) but less than 336, the refund is `total_fee_cents` minus 800, then multiplied by one-half, with the multiplication floored to an integer cent.
- When hours to check-in is at least 24 (one day) but less than 72, the refund is `total_fee_cents` minus 800 minus one night's `nightly_rate_cents`, clamped to zero when the result would be negative; one full night is forfeit on top of the booking fee.
- When hours to check-in is less than 24, the refund is zero.

There is one variant. For a `GROUP` site, the booking fee is always forfeit and one full night's `nightly_rate_cents` is held back as a non-refundable deposit regardless of timing: the refund is `total_fee_cents` minus 800 minus `nightly_rate_cents`, clamped to zero when negative. This produces a strictly lower refund than the `STANDARD` variant on identical inputs whenever the `STANDARD` variant would have returned more than `total_fee_cents` minus 800 minus `nightly_rate_cents`.

A `ParkRanger` records the visitor's arrival on a `CONFIRMED` campground reservation via the check-in capability; if no arrival is recorded by 23:00 park-local on `check_in_date_local`, the sweep transitions the reservation from `CONFIRMED` to `NO_SHOW`, increments the visitor's `lottery_strikes` by one (a cascade onto the `Visitor` entity), releases site occupancy for the remaining nights, and runs the waitlist-promotion sweep on that campground. A `CONFIRMED` reservation that survives the check-in window without a no-show is rolled forward by the sweep from `CONFIRMED` to `COMPLETED` once park-local time is at or past 11:00 on `check_out_date_local`.

### 3.5. Waitlists

A `Visitor` joins a campground's waitlist by supplying `site_kind`, `check_in_date_local`, and `nights` (1 through 14 inclusive). The system records the `campground_id`, snapshots a tie-break `priority_score` computed as the integer floor of the number of seconds between the Unix epoch and the entry's `created_at` divided by 60 (so a lower score means an earlier minute-aligned creation and wins), and places the entry in `WAITING` status with `promoted_reservation_id` null. A visitor may also delete their own waitlist entry while it is still `WAITING`; the entry transitions from `WAITING` to `CANCELLED`.

The waitlist-promotion rule fires whenever a campground frees `site_kind` inventory across a date range — either because a `HELD` reservation was released, or because a `CONFIRMED` reservation was cancelled, or because the sweep is running its waitlist scan within the campground's `waitlist_window_hours`. The promotion algorithm is: select every `WaitlistEntry` for that campground whose `status` is `WAITING`, whose `site_kind` matches the freed kind, whose requested date range `[check_in_date_local, check_in_date_local + nights)` overlaps the freed range, and where the current time is within `waitlist_window_hours` of `check_in_date_local`; sort by `priority_score` ascending and then `created_at` ascending; iterate in that order; the first entry for which the campground has `site_kind` capacity across its entire `[check_in_date_local, check_in_date_local + nights)` is promoted. Exactly one promotion runs per freed-inventory event. Promotion creates a fresh `CampgroundReservation` in `HELD` for the same visitor, sets that reservation's `held_until` to 4 hours after the moment of promotion (this is the four-hour promotion-hold constant), writes the new reservation's `id` into the waitlist entry's `promoted_reservation_id`, and transitions the waitlist entry from `WAITING` to `PROMOTED`.

The sweep also expires stale waitlist entries: a `WAITING` entry whose `check_in_date_local` has reached or passed 18:00 park-local is transitioned from `WAITING` to `EXPIRED`.

### 3.6. Lottery Permits and Applications

A `Visitor` applies to a lottery permit by submitting `party_size`. The system writes the parent `lottery_permit_id`, the applicant's `visitor_id`, snapshots `application_fee_cents` from the permit's current `application_fee_cents`, mints a 64-bit unsigned pseudo-random `rank_seed` (lower wins), places the application in `SUBMITTED` status, and immediately appends a `LedgerEntry` of `kind` `LOTTERY_FEE` debiting the visitor's wallet by `application_fee_cents` — this fee is non-refundable regardless of draw outcome. The application's `award_expires_at` is left null until the draw runs.

Several gates fire at application time. The submitting visitor's `lottery_strikes` must be strictly less than 3; otherwise the request is rejected with `ERR_STRIKE_LIMIT_REACHED`. The requested `party_size` must be at least 1 and must not exceed the permit's `per_application_max_party`; otherwise the request is rejected with `ERR_PARTY_SIZE_INVALID`. The current instant must be strictly at or after `lottery_open_at` and strictly before `lottery_close_at` (the closing instant itself is excluded); outside this half-open interval the request is rejected with `ERR_LOTTERY_CLOSED`. The park's `status` must not be `FROZEN`; otherwise the request is rejected with `ERR_PARK_FROZEN`.

The draw is triggered either by a `ParkAdmin` or `SystemOperator` calling the draw capability, or by the sweep crossing the permit's `draw_at` instant. The draw can only run when the permit's `status` is `CLOSED` and the park's `status` is not `FROZEN`. Two simultaneous draws on the same permit serialise so that the second draw receives `ERR_LOTTERY_ALREADY_DRAWN`. The draw algorithm is the waterfall-allocation rule: select every `LotteryApplication` whose `lottery_permit_id` matches and whose `status` is `SUBMITTED` and whose applying visitor's `lottery_strikes` is strictly less than 3; sort by `rank_seed` ascending and then `created_at` ascending as the lexicographic tie-break; initialise the remaining-slot counter to `daily_slot_count`; iterate in sorted order, and for each application, if the remaining-slot counter is at least the application's `party_size`, mark the application `AWARDED` and subtract `party_size` from the counter, otherwise mark the application `WAITLISTED`. On completion, transition the permit from `CLOSED` to `DRAWN` and set each `AWARDED` application's `award_expires_at` to 72 hours after `draw_at`. The maximum-strikes constant for filtering is 3.

A visitor with an `AWARDED` application has 72 hours to either accept or decline. Accepting requires the application still be `AWARDED`, the current instant be strictly before `award_expires_at`, and `Visitor.wallet_balance_cents` be at least `permit_fee_cents` multiplied by `party_size`. On accept the application transitions from `AWARDED` to `ACCEPTED`, the wallet is debited by `permit_fee_cents` multiplied by `party_size`, and a `LedgerEntry` of `kind` `PERMIT_FEE` is appended. Declining requires only that the application be `AWARDED`; on decline the application transitions from `AWARDED` to `DECLINED`, the awarded slot is returned to the permit's pool, and the first remaining `WAITLISTED` application (lowest `rank_seed`, then earliest `created_at`) is promoted from `WAITLISTED` to `AWARDED` — a cascade of depth three from one application's decline, through the permit's slot pool, through to a sibling application's status flip. Accept-versus-decline races on the same application serialise on the application's `status` exit from `AWARDED`; the losing call receives `ERR_INVALID_STATE`.

The sweep handles the third terminal path. When `award_expires_at` has passed on an `AWARDED` application, the sweep transitions it from `AWARDED` to `FORFEITED`, increments the visitor's `lottery_strikes` by one, returns the slot to the pool, and promotes the next `WAITLISTED` application. A `ParkRanger` may also record an `ACCEPTED` application as a no-show after `hike_date` has ended (the park-local time must be after 23:59 on `hike_date`): the application transitions from `ACCEPTED` to `FORFEITED`, no refund of `permit_fee_cents` is issued, and `lottery_strikes` is incremented by one.

### 3.7. Backcountry Permits

A `Visitor` requests a backcountry permit against a zone by supplying `party_size` (1 through 15 inclusive), `entry_datetime_local`, and `exit_datetime_local`; the latter must be strictly after the former. The system stores the parent `zone_id`, computes `nights` as the difference between the entry-date and the exit-date in park-local days, computes `fee_cents` as the zone's `per_party_fee_cents` plus the 800-cent booking fee, places the permit in `HELD` status, and sets `held_until` to 15 minutes after creation. Time is at minute granularity throughout — any sub-minute component on input is truncated.

Confirming the permit transitions it from `HELD` to `CONFIRMED` and requires that the permit still be `HELD`, that now precede `held_until`, that the park's `status` be `OPEN`, that `Visitor.wallet_balance_cents` be at least `fee_cents`, and that the overlap rule below pass. On success the wallet is debited by `fee_cents` via a `LedgerEntry` of `kind` `FEE_CHARGE`, and zone usage is incremented by `party_size` for each overnight night the permit occupies.

The overlap rule treats each permit as a half-open time interval `[entry_datetime_local, exit_datetime_local)` and considers two checks against existing `CONFIRMED` permits in the same zone. The first check is the ranger-buffer time-collision: with `buffer` being the zone's `ranger_buffer_minutes` converted to seconds, a new permit `[a, b)` collides with an existing `[c, d)` exactly when `a` is strictly less than `d` plus `buffer` and `c` is strictly less than `b` plus `buffer`. The interval is closed on the left and open on the right, so equality at `b` equal to `c` passes the test exactly when the gap between them is at least `buffer`. A time collision is reported with `ERR_RANGER_BUFFER_VIOLATION`. The second check is the people-quota: for every overnight night `N` covered by the permit (each night from the entry-date through the exit-date minus one), the sum of `party_size` across all `CONFIRMED` permits overlapping `N` plus the new permit's `party_size` must not exceed the zone's `nightly_quota_people`. A quota overrun is reported with `ERR_BACKCOUNTRY_FULL`. The ranger-buffer check always runs before the nightly-quota check, so a permit that violates both reports the buffer violation.

A `HELD` permit may be cancelled at any time; whether by an explicit visitor cancel or by the sweep crossing `held_until`, the permit transitions from `HELD` to `CANCELLED`. A `CONFIRMED` permit may be cancelled by the owning visitor only while the park-local time is strictly before `entry_datetime_local`; on success the permit transitions from `CONFIRMED` to `CANCELLED`, the refund is computed per the backcountry tiered-refund rule below and credited via a `LedgerEntry` of `kind` `FEE_REFUND`, and zone usage is decremented by `party_size` for each released night.

The backcountry tiered-refund rule is as follows. Let "hours to entry" be the number of hours between now (in UTC) and `entry_datetime_local` converted from park-local to UTC. When the number is at least 168 (seven days, the full-window constant), the refund is the full `fee_cents`. When the number is at least 24 (one day, the half-window constant) but less than 168, the refund is `fee_cents` multiplied by one-half, with the result floored to an integer cent. When the number is less than 24, the refund is zero.

A `ParkRanger` marks the permit `USED` at exit via the check-out capability; this is permitted only when park-local time is at or after `exit_datetime_local`. The transition is from `CONFIRMED` to `USED`.

## 4. Endpoint Definitions

The endpoint table below names the HTTP method, path, description, and authorised roles for every endpoint in the system. The complete request payload, response payload, and side effects for each endpoint are not duplicated here — they live in the §3 narratives above. The success status codes follow the standard convention: operations that create a brand-new top-level resource return 201 Created, operations that modify an existing resource (including all `/confirm`, `/cancel`, `/check-in`, `/check-out`, `/accept`, `/decline`, `/no-show`, `/draw`, `/restrict`, `/freeze`, `/reopen`, and `/revoke` state transitions, as well as all PATCH endpoints) return 200 OK, and deletions return 204 No Content. Operations under `/_clock` and `/_sweep` return 200 OK.

| Method | Path                                                                  | Description                                                                       | Authorized Role(s)                              |
| ------ | --------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------- |
| POST   | `/_clock/advance`                                                     | Advance virtual clock to a supplied UTC instant                                   | SystemOperator                                  |
| POST   | `/_sweep/run`                                                         | Run the deferred-action sweep at the current clock                                | SystemOperator                                  |
| POST   | `/visitors`                                                           | Create a visitor account                                                          | SystemOperator                                  |
| GET    | `/visitors/{visitor_id}`                                              | Read a visitor (with computed wallet balance and strike count)                    | SystemOperator, Visitor                         |
| POST   | `/visitors/{visitor_id}/wallet/deposit`                               | Deposit funds into a visitor's wallet                                             | SystemOperator, Visitor                         |
| GET    | `/visitors/{visitor_id}/ledger`                                       | List ledger entries for a visitor                                                 | SystemOperator, Visitor                         |
| POST   | `/visitors/{visitor_id}/passes`                                       | Issue an America the Beautiful Pass                                               | ParkAdmin                                       |
| GET    | `/visitors/{visitor_id}/passes`                                       | List a visitor's passes                                                           | SystemOperator, Visitor, ParkAdmin              |
| POST   | `/visitors/{visitor_id}/passes/{pass_id}/revoke`                      | Revoke an active pass                                                             | ParkAdmin                                       |
| POST   | `/parks`                                                              | Create a park                                                                     | ParkAdmin                                       |
| GET    | `/parks`                                                              | List parks                                                                        | ParkAdmin, Visitor, ParkRanger, SystemOperator  |
| GET    | `/parks/{park_id}`                                                    | Read a park                                                                       | ParkAdmin, Visitor, ParkRanger, SystemOperator  |
| PATCH  | `/parks/{park_id}`                                                    | Update park configuration with OCC                                                | ParkAdmin                                       |
| POST   | `/parks/{park_id}/restrict`                                           | Transition the park from OPEN to RESTRICTED                                       | ParkAdmin                                       |
| POST   | `/parks/{park_id}/freeze`                                             | Transition the park to FROZEN                                                     | ParkAdmin                                       |
| POST   | `/parks/{park_id}/reopen`                                             | Transition the park back to OPEN                                                  | ParkAdmin                                       |
| POST   | `/parks/{park_id}/timed-entry`                                        | Create a HELD timed-entry reservation                                             | Visitor                                         |
| GET    | `/parks/{park_id}/timed-entry`                                        | List timed-entry reservations                                                     | ParkAdmin, ParkRanger, Visitor                  |
| POST   | `/parks/{park_id}/timed-entry/{id}/confirm`                           | Confirm a HELD timed-entry reservation                                            | Visitor                                         |
| POST   | `/parks/{park_id}/timed-entry/{id}/cancel`                            | Cancel a HELD or CONFIRMED timed-entry reservation                                | Visitor                                         |
| POST   | `/parks/{park_id}/timed-entry/{id}/check-in`                          | Ranger marks the reservation USED at the gate                                     | ParkRanger                                      |
| POST   | `/parks/{park_id}/campgrounds`                                        | Create a campground under a park                                                  | ParkAdmin                                       |
| GET    | `/parks/{park_id}/campgrounds`                                        | List campgrounds in a park                                                        | ParkAdmin, Visitor, ParkRanger                  |
| POST   | `/campgrounds/{campground_id}/reservations`                           | Create a HELD campground reservation                                              | Visitor                                         |
| GET    | `/campgrounds/{campground_id}/reservations`                           | List reservations for a campground                                                | ParkAdmin, ParkRanger, Visitor                  |
| POST   | `/campgrounds/{campground_id}/reservations/{id}/confirm`              | Confirm a HELD campground reservation                                             | Visitor                                         |
| POST   | `/campgrounds/{campground_id}/reservations/{id}/cancel`               | Cancel a campground reservation                                                   | Visitor                                         |
| POST   | `/campgrounds/{campground_id}/reservations/{id}/check-in`             | Ranger records arrival                                                            | ParkRanger                                      |
| POST   | `/campgrounds/{campground_id}/waitlist`                               | Join the waitlist for a campground/date/site_kind                                 | Visitor                                         |
| GET    | `/campgrounds/{campground_id}/waitlist`                               | List waitlist entries                                                             | ParkAdmin, ParkRanger, Visitor                  |
| DELETE | `/campgrounds/{campground_id}/waitlist/{id}`                          | Cancel a waitlist entry                                                           | Visitor                                         |
| POST   | `/parks/{park_id}/lottery-permits`                                    | Create a lottery permit                                                           | ParkAdmin                                       |
| GET    | `/parks/{park_id}/lottery-permits`                                    | List lottery permits for a park                                                   | ParkAdmin, Visitor, ParkRanger                  |
| POST   | `/lottery-permits/{id}/applications`                                  | Submit a lottery application                                                      | Visitor                                         |
| GET    | `/lottery-permits/{permit_id}/applications`                           | List applications under a permit                                                  | ParkAdmin, Visitor                              |
| POST   | `/lottery-permits/{id}/draw`                                          | Trigger the lottery draw                                                          | ParkAdmin, SystemOperator                       |
| POST   | `/lottery-applications/{id}/accept`                                   | Accept an AWARDED slot                                                            | Visitor                                         |
| POST   | `/lottery-applications/{id}/decline`                                  | Decline an AWARDED slot                                                           | Visitor                                         |
| POST   | `/lottery-applications/{id}/no-show`                                  | Ranger marks an ACCEPTED application a no-show                                    | ParkRanger                                      |
| POST   | `/parks/{park_id}/backcountry-zones`                                  | Create a backcountry zone                                                         | ParkAdmin                                       |
| GET    | `/parks/{park_id}/backcountry-zones`                                  | List backcountry zones in a park                                                  | ParkAdmin, Visitor, ParkRanger                  |
| POST   | `/backcountry-zones/{zone_id}/permits`                                | Create a HELD backcountry permit                                                  | Visitor                                         |
| POST   | `/backcountry-zones/{zone_id}/permits/{id}/confirm`                   | Confirm a HELD backcountry permit                                                 | Visitor                                         |
| POST   | `/backcountry-zones/{zone_id}/permits/{id}/cancel`                    | Cancel a backcountry permit                                                       | Visitor                                         |
| POST   | `/backcountry-zones/{zone_id}/permits/{id}/check-out`                 | Ranger marks the permit USED at exit                                              | ParkRanger                                      |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_UNAUTHENTICATED`             | 401              |
| `ERR_FORBIDDEN`                   | 403              |
| `ERR_NOT_FOUND`                   | 404              |
| `ERR_VALIDATION`                  | 422              |
| `ERR_VERSION_CONFLICT`            | 409              |
| `ERR_INVALID_STATE`               | 409              |
| `ERR_PARK_FROZEN`                 | 409              |
| `ERR_PARK_RESTRICTED`             | 409              |
| `ERR_OUT_OF_BOOKING_WINDOW`       | 422              |
| `ERR_WINDOW_MISALIGNED`           | 422              |
| `ERR_TIMED_ENTRY_FULL`            | 409              |
| `ERR_CAMPGROUND_FULL`             | 409              |
| `ERR_BACKCOUNTRY_FULL`            | 409              |
| `ERR_RANGER_BUFFER_VIOLATION`     | 409              |
| `ERR_PASS_INVALID`                | 422              |
| `ERR_PARTY_SIZE_INVALID`          | 422              |
| `ERR_STAY_TOO_LONG`               | 422              |
| `ERR_INSUFFICIENT_FUNDS`          | 402              |
| `ERR_LOTTERY_CLOSED`              | 422              |
| `ERR_LOTTERY_ALREADY_DRAWN`       | 409              |
| `ERR_STRIKE_LIMIT_REACHED`        | 422              |
| `ERR_AWARD_EXPIRED`               | 409              |
