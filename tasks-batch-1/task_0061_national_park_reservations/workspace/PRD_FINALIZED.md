# National Park Reservations API — Product Requirements Document

## 1. Introduction

The National Park Reservations platform is a Recreation.gov-style backend that lets the public discover, book, and pay for the full range of access products a national-park system sells: vehicle timed-entry reservations, high-demand permit lotteries (such as Half Dome cables or The Wave), backcountry wilderness permits drawn against trailhead and zone quotas, drive-up campground stays with a position-ordered waitlist, and America the Beautiful interagency passes. Each of these products is scarce, time-sensitive, and governed by its own allocation policy, and the system's job is to allocate that scarcity fairly, charge for it correctly, and release it cleanly when plans change.

Three pressures shape every requirement in this document. The first is **fairness under scarcity**: lottery winners must be chosen by a deterministic, reproducible rule, and quota counters (slot capacity, zone party-nights, trailhead exits, lottery persons) must never be over-committed. The second is **money correctness**: every booking moves through an authorize/capture/refund/void payment lifecycle, fees are split into refundable and non-refundable components, and refunds are tiered by how far in advance a visitor cancels. The third is **temporal precision**: bookings open on rolling release windows, holds expire on a fixed timer, lottery and award windows open and close on instants, and a simulation clock drives all of these checks so behaviour is testable rather than wall-clock dependent.

This document is the single authoritative source for the system's behaviour. Where it names a field, an enumerated value, an error identifier, a constant, or a formula, that statement is binding and must be implemented exactly as written.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request that targets a non-public endpoint must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role under which the call is made. The recognized roles are exactly `visitor`, `ranger`, `park_admin`, and `finance`. In addition, an internal `system` operator role exists for test seeding and for driving the simulation clock and the housekeeping sweep; it is not a member of the public-facing role set but is accepted on the endpoints that name it.

When `X-User-Role` is `visitor`, `ranger`, or `park_admin`, `X-User-ID` is the `id` of the acting `Account`; these are entity-backed identities. Ownership checks on any resource that references an `Account` compare the resource's owning foreign-key field (its `account_id`) to `X-User-ID`. For `ranger` and `park_admin`, an additional park-scope check applies: the acting account's `home_park_id` must equal the `park_id` of the resource (or of the resource's parent inventory) being operated on. When `X-User-Role` is `finance`, `X-User-ID` is an opaque back-office operator identifier not tied to any persisted entity; the server accepts it for the operations finance is permitted but does not compare it to any account's `id`.

A request to a non-public endpoint that is missing its role header, or that presents an unknown role, is rejected with `ERR_UNAUTHORIZED`. A request whose role is known but is not permitted the operation — including a visitor acting on another visitor's resource, or a ranger or park_admin acting outside their home park — is rejected with `ERR_FORBIDDEN`. Reads of public inventory (parks, slots, campsites, trailheads, zones, draws) and reads of one's own resources are broadly permitted as detailed in the endpoint catalogue; mutations are always role-gated.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a requested limit above 100 is capped at 100, and a value below 1 is invalid. `offset` defaults to 0 and is the zero-based index of the first item returned. List results are ordered by `created_at` ascending. The `meta` block on list responses reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when more records remain beyond the current page).

### 2.4. Common Resource Properties and Identity

Most resources carry a common envelope of system fields. Every resource has an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Resources that are mutated over their lifetime also carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by one on every mutation. The `Clock` resource is the sole exception: it is a singleton that carries only `id` and `created_at`, and it has neither an `updated_at` nor a `version`.

The simulation clock defines server "now". The `Clock` resource has the literal `id` of `clock`, a `created_at`, and a `now_utc` field holding the current simulated instant in ISO-8601 UTC. Every temporal check in this specification — booking windows, slot release, hold lapse, lottery open/close, award deadlines, waitlist offer expiry, and pass expiry — compares against `now_utc`, never against wall-clock time.

### 2.5. Park-Local Time and Timezone Conversion

Each `Park` declares a fixed `utc_offset_minutes`, its civil offset from UTC (for example, -480 for Pacific Standard Time). A park-local civil time converts to UTC by subtracting this offset from the local time. Whenever a rule is expressed in "park-local date" or "park-local time" — campground check-in/check-out comparisons, the timed-entry rolling window, the timed-entry check-in window, and the cancellation lead-time bands — the comparison is performed after converting `now_utc` into the relevant park's local civil time using that park's offset.

### 2.6. The Payment Ledger: Authorize, Capture, Refund, Void

All money is integer cents; there is no fractional currency and no rounding except where a calculation explicitly invokes rounding. Every charge is represented by a `Payment` record carrying the payer's `account_id`, a `kind` (one of `timed_entry`, `lottery_application`, `lottery_permit`, `backcountry`, `campground`, or `atb_pass`), a `ref_type` naming the entity the payment is for, the `ref_id` of that entity, an authorized `amount_cents` (which must be zero or greater), a `captured_cents` (capped at `amount_cents`, defaulting to 0), a `refunded_cents` (capped at `captured_cents`, defaulting to 0), and a `status` of `authorized`, `captured`, `partially_refunded`, `refunded`, or `voided`, beginning at `authorized`.

A payment may be captured only from `authorized`; on capture its `captured_cents` is set equal to `amount_cents`. A refund may be applied only from `captured` or `partially_refunded`, and the cumulative `refunded_cents` may never exceed `captured_cents`; an attempt that would exceed the captured amount is rejected with `ERR_OVER_REFUND`. A still-authorized (uncaptured) payment is voided rather than refunded, moving it to `voided`. These constraints govern every cancel and void flow described in §3.

### 2.7. Quota and Capacity Accounting

The platform protects four independent kinds of scarce capacity, and each is tracked with its own counters that must never be exceeded. A `TimedEntrySlot` tracks `held_count` (reservations currently in `held`) and `booked_count` (reservations currently `confirmed` or `checked_in`); the invariant is that `held_count` plus `booked_count` never exceeds the slot's `capacity`. A `WildernessZone` tracks `used_by_date`, a map from ISO date to the count of committed party-nights on that date, with each value bounded by the zone's `nightly_party_quota`. A `Trailhead` tracks `exit_used_by_date`, a map from entry date to the count of confirmed permits starting that date, each value bounded by `daily_exit_quota`. A `LotteryDraw` tracks `awarded_count`, the sum of `party_size` across applications in won or awarded status, never exceeding `daily_quota`. Quota for backcountry counts **parties, not persons**: each itinerary element consumes exactly one party-night regardless of `party_size`, and each entry consumes exactly one trailhead exit.

### 2.8. Hold-and-Commit Discipline and Cascading Side Effects

Timed-entry reservations, backcountry permits, and campground reservations are all created as short-lived holds and must be explicitly confirmed. A hold sets `hold_expires_at` to fifteen minutes after `now_utc` and, on confirmation or any terminal transition, that field is cleared to null. The platform distinguishes carefully between capacity that is *provisionally held* and capacity that is *committed*: a timed-entry hold increments the slot's `held_count` immediately, whereas a backcountry hold does **not** touch zone or trailhead counters and only commits them at confirm time. This distinction matters for the side effects of every transition, which always state precisely which counters move and which payment action occurs.

Mutations propagate. Confirming a timed-entry reservation captures its payment and moves one unit from the slot's `held_count` to its `booked_count`. Cancelling or expiring a campground reservation releases its dates and then cascades a waitlist offer to the lowest-position waiting entry for the exact same campsite and date range. Whenever any resource is mutated, its `updated_at` is refreshed and its `version` is incremented; parent counters that a transition touches (slot counts, zone and trailhead maps, draw counts) are likewise updated as part of the same operation.

### 2.9. Optimistic Concurrency on Capacity Parents

Two write operations require the client to prove it is acting on a fresh view of a capacity parent, by submitting that parent's last-observed `version`.

Creating a held timed-entry reservation requires `expected_slot_version` carrying the client's last-observed `version` of the target `TimedEntrySlot`. If the slot's current `version` differs — because another writer has already placed a hold on the same slot and advanced its version, making the client's view of remaining capacity stale — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful create increments the slot's `version` by one.

Joining a campsite waitlist requires `expected_campsite_version` carrying the client's last-observed `version` of the target `Campsite`. If the campsite's current `version` differs — because the requested range just became bookable when a conflicting reservation released its dates and advanced the campsite's version, making the client's "the dates are taken" premise stale — the join is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful join increments the campsite's `version` by one. No other endpoint takes a version field.

### 2.10. Idempotency

Creation endpoints accept an `Idempotency-Key`. Replaying the same key with an identical request body returns the original result rather than creating a duplicate; replaying the same key with a *different* request body is rejected with `ERR_IDEMPOTENCY_CONFLICT`.

### 2.11. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so the returned error is deterministic. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHORIZED`, then role/ownership/park-scope permission yields `ERR_FORBIDDEN`. Existence of every path- and body-referenced resource is checked next, yielding `ERR_NOT_FOUND`. Then idempotency conflicts (`ERR_IDEMPOTENCY_CONFLICT`) are detected, followed by field-level schema validation (`ERR_VALIDATION`). After these come the resource-specific business checks in the order: account email uniqueness (`ERR_EMAIL_TAKEN`), staff home-park requirement (`ERR_HOME_PARK_REQUIRED`), group campsite configuration (`ERR_GROUP_CONFIG_MISSING`), pass age requirement (`ERR_AGE_REQUIREMENT`), pass overlap (`ERR_PASS_OVERLAP`), state validity (`ERR_STATE_INVALID`), hold freshness (`ERR_HOLD_EXPIRED`), the temporal-window checks (`ERR_NOT_YET_RELEASED`, `ERR_OUTSIDE_BOOKING_WINDOW`, `ERR_LOTTERY_CLOSED`, `ERR_DRAW_NOT_READY`, `ERR_AWARD_WINDOW_CLOSED`, `ERR_OFFER_EXPIRED`), the size/itinerary checks (`ERR_INVALID_PARTY_SIZE`, `ERR_INVALID_ITINERARY`, `ERR_OVER_OCCUPANCY`), availability and duplicate checks (`ERR_SITE_UNAVAILABLE`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_RESERVATION`, `ERR_DATES_AVAILABLE`), the optimistic-concurrency check (`ERR_STALE_VERSION`), and finally the capacity/fiscal checks (`ERR_DATE_CONFLICT`, `ERR_SLOT_FULL`, `ERR_ZONE_FULL`, `ERR_TRAILHEAD_FULL`, `ERR_OVER_REFUND`). The practical consequence: state validity is judged before any temporal-window check, and capacity is judged last, so a request that is both in the wrong state and over capacity surfaces the state error.

## 3. Business Logic & Workflows

### 3.1. Accounts, Parks, and Annual Passes

A new principal registers by supplying an `email`, a `full_name`, and a `birth_date` (an ISO `YYYY-MM-DD` date used later for senior-pass age checks), optionally a `role` (defaulting to `visitor`) and a `home_park_id`. The `email` must be unique across all accounts; a collision is rejected with `ERR_EMAIL_TAKEN`. If the requested `role` is `ranger` or `park_admin`, a `home_park_id` is mandatory, and its absence is rejected with `ERR_HOME_PARK_REQUIRED`; for a visitor it is left null. A new account is created with `status` set to `active` (the alternative is `suspended`) and a `credit_balance_cents` of 0 — a never-negative refundable-credit balance that grows whenever a refund is destined to credit.

Parks are seeded by the `system` operator. A `Park` carries a unique short `code` (such as YOSE), a `name`, a `utc_offset_minutes` (defaulting to 0), a `timed_entry_required` boolean flag (defaulting to false, indicating whether vehicles need a timed-entry reservation), and a `status` of `open` or `seasonal_closed` (defaulting to `open`).

An America the Beautiful pass is purchased by a visitor for their own account, supplying `account_id`, `pass_type`, and `valid_from`. The `pass_type` is one of `annual`, `senior_annual`, `senior_lifetime`, `military`, or `access`. The price is snapshotted into `price_cents` at purchase and depends solely on type: an `annual` pass costs 8000 cents, a `senior_annual` costs 2000 cents, a `senior_lifetime` costs 8000 cents, and both `military` and `access` are free at 0 cents. The expiry `valid_to` is computed as the day exactly 365 days after `valid_from` for `annual`, `senior_annual`, `military`, and `access`; for `senior_lifetime` it is null, meaning the pass never expires. The pass is created with `status` set to `active` (other values are `expired` and `voided`). When the price is greater than zero, a captured `Payment` of kind `atb_pass` is created and its id stored in the pass's `payment_id`; for free types `payment_id` is null.

Two business rules guard pass purchase. The senior types — `senior_annual` and `senior_lifetime` — require the purchasing account to be at least 62 years old as of `valid_from`, derived from `birth_date`; a younger applicant is rejected with `ERR_AGE_REQUIREMENT`. And an account may not hold two passes that are both `active` and whose validity ranges overlap, where a `senior_lifetime` pass is treated as open-ended from its `valid_from`; an overlapping purchase is rejected with `ERR_PASS_OVERLAP`.

A pass may be voided by a `finance` operator for a full refund, but only within a narrow window. The pass must currently be `active`; voiding from any other state is rejected with `ERR_STATE_INVALID`. The void is permitted only when `now_utc` is at or before 30 days after the pass's `created_at`, and only when the pass has a non-null `payment_id` — a free pass carries no payment and so cannot be voided for refund; either failing condition yields `ERR_VOID_NOT_ALLOWED`. On a successful void the pass moves `active → voided`, its purchase payment is refunded in full (its `refunded_cents` set equal to `captured_cents` and the payment moved to `refunded`), and the refunded amount is credited to the account's `credit_balance_cents`.

Separately, the housekeeping sweep expires passes whose time has run out: a pass that is `active` and whose `valid_to` is non-null and strictly earlier (by date) than `now_utc` transitions `active → expired`. A `senior_lifetime` pass, having a null `valid_to`, is never expired by this rule.

### 3.2. Timed-Entry: Slots, Booking Windows, and the Vehicle Lifecycle

A `park_admin` creates timed-entry inventory at their home park as a `TimedEntrySlot`, an inventory bucket admitting vehicles for a particular `park_id`, `entry_date`, and time window. The window is bounded by `window_start_local` (the park-local HH:MM at which entry opens, inclusive) and `window_end_local` (the park-local HH:MM at which it closes, exclusive). The slot carries a `capacity` of total vehicle slots, a `release_at` instant (the UTC moment booking opens, supporting rolling daily release), and an `entry_fee_cents` per-vehicle reservation fee that defaults to 200. Its `held_count` and `booked_count` both begin at 0.

A visitor books a vehicle by creating a held `TimedEntryReservation`, supplying `slot_id`, `account_id`, a non-empty `vehicle_plate`, and `expected_slot_version`. Several conditions are checked. Booking is permitted only once the slot has released — `now_utc` must be at or after `release_at`, otherwise `ERR_NOT_YET_RELEASED`. The slot's `entry_date` must fall within a rolling seven-day window measured in park-local dates: the difference between the entry date and today's park-local date must be at least 0 and at most 7, otherwise `ERR_OUTSIDE_BOOKING_WINDOW`. An account may hold at most one active (held or confirmed) reservation per slot; a second is rejected with `ERR_DUPLICATE_RESERVATION`. The slot must have room — `held_count` plus `booked_count` must be strictly less than `capacity` to place a new hold, otherwise `ERR_SLOT_FULL`. And the optimistic-concurrency check on `expected_slot_version` applies as described in §2.9.

On a successful create, the reservation enters `held` with `hold_expires_at` set to fifteen minutes after `now_utc`; the slot's `held_count` is incremented and its `version` advanced; the `fee_cents` is computed; and an authorized `Payment` is created. The reservation fee equals the slot's `entry_fee_cents` outright. Holding an active America the Beautiful pass does **not** waive this reservation fee — the timed-entry fee is charged regardless of any pass — and the fee is entirely **non-refundable**: cancelling a confirmed reservation refunds nothing.

The vehicle reservation lifecycle has states `held`, `confirmed`, `checked_in`, `cancelled`, `expired`, and `no_show`, with `cancelled`, `expired`, and `no_show` terminal. Confirming requires the reservation to be `held` (otherwise `ERR_STATE_INVALID`) and the hold to be unexpired — `now_utc` at or before `hold_expires_at`, otherwise `ERR_HOLD_EXPIRED`; on success it moves `held → confirmed`, captures the payment (setting `captured_cents` equal to `amount_cents` and the payment to `captured`), decrements the slot's `held_count` and increments its `booked_count`, and clears `hold_expires_at`. A `ranger` checks the vehicle in: the reservation must be `confirmed`, `now_utc` must fall within the slot's window in park-local time (at or after the start, before the end), and the ranger's `home_park_id` must equal the slot's `park_id` (otherwise `ERR_FORBIDDEN`); on success it moves `confirmed → checked_in` with no counter or payment change.

A visitor may cancel. Cancelling a `held` reservation moves `held → cancelled`, decrements the slot's `held_count`, and voids the still-authorized payment. Cancelling a `confirmed` reservation moves `confirmed → cancelled` and decrements the slot's `booked_count`, but because the entry fee is non-refundable the payment stays `captured` and `refunded_cents` remains 0. The housekeeping sweep handles two automatic transitions: a `held` reservation whose `hold_expires_at` has passed (`now_utc` strictly after it) moves `held → expired`, decrementing the slot's `held_count` and voiding the payment; and a `confirmed` reservation whose slot window-end (converted to UTC) has passed without a check-in moves `confirmed → no_show`, decrementing the slot's `booked_count` while the payment stays captured.

### 3.3. The Permit Lottery: Applying, Drawing, and Settling

A `park_admin` opens a permit lottery for a high-demand objective at their home park as a `LotteryDraw`, supplying `park_id`, an `objective` label (such as half_dome_cables or the_wave), the `use_date` the awarded permit will be valid for, a `daily_quota` of total permit persons awarded, the application window instants `application_open_at` and `application_close_at` (the latter exclusive), the `draw_at` instant at or after which the draw may run, the per-person `permit_fee_per_person_cents` charged to winners on acceptance, and optionally a `max_group_size` (defaulting to 6) and a non-refundable `application_fee_cents` (defaulting to 1000). The draw is created with `status` `accepting` (other values are `drawn` and `settled`) and `awarded_count` 0.

A visitor applies by supplying `account_id`, a `party_size`, and optionally a `preference_rank`. Applications are accepted only while the draw is `accepting` and `now_utc` is at or after `application_open_at` and strictly before `application_close_at`; outside that window the application is rejected with `ERR_LOTTERY_CLOSED`. The `party_size` must be at least 1 and at most the draw's `max_group_size`; outside that range yields `ERR_INVALID_PARTY_SIZE`. An account may have at most one non-terminal application per draw; a second is rejected with `ERR_DUPLICATE_APPLICATION`. On success the application is created in `submitted` status (its lifecycle states are `submitted`, `won`, `lost`, `awarded`, `declined`, and `withdrawn`, with `lost`, `awarded`, `declined`, and `withdrawn` terminal). The application records the `draw_id` of the draw it belongs to. Its `application_fee_cents` is snapshotted from the draw, a captured `Payment` of kind `lottery_application` is created and its id stored in `application_payment_id`, and `permit_payment_id` and `award_accept_deadline` remain null. The `preference_rank` is the applicant's priority weight where lower wins first; when omitted it defaults to 9999.

A visitor may withdraw a `submitted` application while the draw is still `accepting` and `now_utc` is before `application_close_at`, moving it `submitted → withdrawn`; the non-refundable application fee stays captured. (A withdraw attempt against a non-`submitted` application is an invalid-state condition.)

A `park_admin` runs the draw, which may proceed only when the draw is `accepting` and `now_utc` is at or after `draw_at`; otherwise `ERR_DRAW_NOT_READY`. The selection is deterministic. Take all `submitted` applications for the draw and sort them ascending first by `preference_rank`, then by `created_at`, then by server-assigned creation order (the monotonic sequence in which records were created, so that among entries sharing the same `created_at` the earlier-created application sorts first), and finally by `id` purely as a last-resort total-order tiebreaker — neither creation order nor `id` is ever the primary decider. Begin with the remaining quota equal to `daily_quota`, and walk the sorted list: if an application's `party_size` is less than or equal to the remaining quota, it is selected (moving `submitted → won`) and its `party_size` is subtracted from the remaining quota; otherwise it is not selected (moving `submitted → lost`). An oversized application is skipped without partial award, and a later, smaller application may still win against the leftover quota. Each winning application has its `award_accept_deadline` set to 72 hours after the draw's `draw_at` and adds its `party_size` to the draw's `awarded_count`; each losing application keeps its application fee captured. When the draw completes, the draw itself moves to `drawn`, with `awarded_count` equal to the sum of the winners' party sizes.

A winner has 72 hours to respond. Accepting requires the application to be `won` and `now_utc` to be at or before `award_accept_deadline`, otherwise `ERR_AWARD_WINDOW_CLOSED`; on success it moves `won → awarded` and creates a captured `Payment` of kind `lottery_permit` for the per-person fee times the party — `permit_fee_per_person_cents` multiplied by `party_size` — storing its id in `permit_payment_id`. Declining moves `won → declined` and releases the held persons by subtracting `party_size` from the draw's `awarded_count`. The housekeeping sweep enforces the deadline automatically: a `won` application whose `award_accept_deadline` has passed (`now_utc` strictly after it) is lapsed `won → declined`, likewise subtracting its `party_size` from `awarded_count` to return those persons to the pool.

### 3.4. Backcountry Permits: Itineraries, Zone-Nights, and Trailhead Exits

Backcountry inventory consists of trailheads and wilderness zones, both created by a `park_admin` at their home park. A `Trailhead` is a wilderness entry point with a `name`, a `daily_exit_quota` (the maximum number of parties that may start per entry date), an `exit_used_by_date` usage map beginning empty, a flat per-permit `reservation_fee_cents` that defaults to 500 and is non-refundable, and a refundable `per_person_per_night_cents` that defaults to 800. A `WildernessZone` has a `name` and a `nightly_party_quota` (the maximum committed party-nights per date) with a `used_by_date` usage map beginning empty.

A visitor reserves a wilderness itinerary by creating a held `BackcountryPermit`, supplying `park_id`, `account_id`, `trailhead_id`, an `entry_date` (the park-local date the party enters, which consumes a trailhead exit), a `nights` count, a `party_size`, and a `zone_nights` array. The `zone_nights` array is an ordered list with one element per night, each element naming a `zone_id` and a `date`; each element consumes one party-night of that zone on that date. The itinerary must be internally consistent: `nights` must be between 1 and 14 inclusive, the length of `zone_nights` must equal `nights`, and every element must carry both a zone and a date; any violation is rejected with `ERR_INVALID_ITINERARY`. The `party_size` must be at least 1, otherwise `ERR_INVALID_PARTY_SIZE`.

At create time the system performs a provisional availability check against the zones and trailhead, but a hold does **not** commit any counter. The permit's `fee_cents` is computed as the sum of two parts: a non-refundable reservation flat equal to the trailhead's `reservation_fee_cents`, plus a refundable variable equal to the trailhead's `per_person_per_night_cents` multiplied by `party_size` and then by `nights`. The permit is created in `held` status (its lifecycle states are `held`, `confirmed`, `cancelled`, and `expired`, with `cancelled` and `expired` terminal) with `hold_expires_at` set to fifteen minutes after `now_utc`, an authorized `Payment` of kind `backcountry`, and a `refunded_cents` of 0.

Confirming is where capacity is actually committed, so it re-validates everything. The permit must be `held` (otherwise `ERR_STATE_INVALID`) and the hold unexpired — `now_utc` at or before `hold_expires_at`, otherwise `ERR_HOLD_EXPIRED`. For every itinerary element, the named zone's committed count for that date (`used_by_date` for that date) must be strictly less than the zone's `nightly_party_quota`, otherwise `ERR_ZONE_FULL`. The trailhead's committed exits for `entry_date` (`exit_used_by_date` for that date) must be strictly less than `daily_exit_quota`, otherwise `ERR_TRAILHEAD_FULL`. On success the permit moves `held → confirmed`, the payment is captured, each itinerary element increments its zone's `used_by_date` for its date by one party-night, the trailhead's `exit_used_by_date` for `entry_date` is incremented by one, and `hold_expires_at` is cleared.

Cancellation behaviour depends on the current state. A still-`held` permit that is cancelled moves `held → cancelled` and simply voids its still-authorized payment — there is no committed quota to release because holds never commit. A `confirmed` permit that is cancelled moves `confirmed → cancelled`, releases every committed party-night (decrementing each zone's `used_by_date` for its date) and the trailhead exit (decrementing `exit_used_by_date` for `entry_date`), and issues a tiered refund of the refundable portion: the refundable base is the permit's `fee_cents` minus the trailhead's `reservation_fee_cents` (the reservation flat is never refunded). The computed refund is written to the permit's `refunded_cents`, applied to the payment's `refunded_cents`, and credited to the account's `credit_balance_cents`. The same housekeeping sweep that handles other holds expires a `held` permit whose `hold_expires_at` has passed, moving it `held → expired` and voiding its payment (again, no quota to release).

The cancellation refund tiers are shared with campground cancellations and are defined in §3.6.

### 3.5. Campgrounds, Reservations, and the Stay Lifecycle

A `park_admin` creates a `Campsite` at their home park, supplying `park_id`, a `site_number` (a human label unique within the park), a `site_type` of `tent`, `rv`, or `group`, a `max_occupancy` (the maximum allowed `party_size`), a `base_nightly_cents` per-night price used for tent and rv sites, optionally a `booking_window_days` (the maximum number of days ahead, inclusive, a stay's check-in may begin, defaulting to 180) and a `status` of `active` or `maintenance` (defaulting to `active`). Group sites additionally require all three of `group_base_cents` (the per-night base covering a number of persons), `group_included_persons` (how many persons that base covers), and `group_extra_person_cents` (the per-night surcharge for each person beyond the included count); for a group site, missing any of these three is rejected with `ERR_GROUP_CONFIG_MISSING`, and for non-group sites these three are null.

A visitor books a stay by creating a held `CampReservation`, supplying `campsite_id`, `account_id`, a `check_in` date (park-local arrival, inclusive), a `check_out` date (park-local departure, exclusive), and a `party_size`. The number of nights is `check_out` minus `check_in` in whole days and must be at least 1. The check-in must fall within the booking window: the difference between `check_in` and today's park-local date must be at least 0 and at most the campsite's `booking_window_days`, and `check_out` must be strictly after `check_in`; a violation is rejected with `ERR_OUTSIDE_BOOKING_WINDOW`. The `party_size` must not exceed the campsite's `max_occupancy`, otherwise `ERR_OVER_OCCUPANCY`. The campsite must be bookable — its `status` must be `active`, otherwise `ERR_SITE_UNAVAILABLE`. On success the reservation is created in `held` status with `hold_expires_at` fifteen minutes after `now_utc`, its `total_cents` computed (see §3.6), an authorized `Payment` of kind `campground`, a `refunded_cents` of 0, and an `origin_waitlist_id` of null (set only when the reservation is later born from a claimed waitlist offer).

The stay lifecycle has states `held`, `confirmed`, `checked_in`, `completed`, `cancelled`, and `expired`, with `completed`, `cancelled`, and `expired` terminal. Confirming requires the reservation to be `held` (otherwise `ERR_STATE_INVALID`) and the hold unexpired (otherwise `ERR_HOLD_EXPIRED`), and re-checks for a date conflict: no other reservation in `confirmed` or `checked_in` may overlap the half-open range from `check_in` to `check_out` on the same campsite, otherwise `ERR_DATE_CONFLICT`. (More broadly, the date-conflict rule treats any reservation in `held`, `confirmed`, or `checked_in` as occupying the dates.) On success it moves `held → confirmed`, captures the payment, and clears `hold_expires_at`. A `ranger` checks the visitor in: the reservation must be `confirmed`, the park-local date of `now_utc` must equal `check_in`, and the ranger's `home_park_id` must equal the campsite's `park_id` (otherwise `ERR_FORBIDDEN`); on success it moves `confirmed → checked_in`. A `ranger` completes the stay: the reservation must be `checked_in`, the park-local date of `now_utc` must be at or after `check_out`, and the same home-park scope applies; on success it moves `checked_in → completed`.

Cancellation and the waitlist cascade are central to campground behaviour. A `held` reservation that is cancelled moves `held → cancelled`, voids its still-authorized payment, releases its dates, and makes a waitlist offer to the lowest-position waiting entry whose range exactly matches (see §3.7). A `confirmed` reservation may be cancelled only while the park-local date of `now_utc` is strictly before `check_in`; on success it moves `confirmed → cancelled`, issues the tiered refund of §3.6 (writing `refunded_cents`, increasing the payment's `refunded_cents`, and crediting the account's `credit_balance_cents`), releases its dates, and likewise cascades the waitlist offer. The housekeeping sweep expires a `held` reservation whose `hold_expires_at` has passed, moving it `held → expired`, voiding its payment, releasing its dates, and cascading the same waitlist offer.

### 3.6. Stay Pricing and the Cancellation Refund Ladder

A campground stay's `total_cents` is computed at create time (and again when a waitlist claim creates a reservation) from the campsite's pricing and the stay length, where nights is `check_out` minus `check_in` in whole days. For a `tent` or `rv` site, the total is the campsite's `base_nightly_cents` multiplied by the number of nights. For a `group` site, first compute the number of extra persons as the party size minus `group_included_persons`, floored at zero (never negative); the per-night rate is then `group_base_cents` plus `group_extra_person_cents` multiplied by that extra-person count; and the total is that per-night rate multiplied by the number of nights. All products are exact integer cents with no rounding.

The cancellation refund ladder applies to confirmed campground reservations and confirmed backcountry permits. Let D be the number of whole days from the park-local date of `now_utc` to the start date — `check_in` for a campground stay, `entry_date` for a backcountry permit — computed as the start date minus today's date. The refundable base differs by product: for a campground stay the refundable base is the full `total_cents` (there is no flat non-refundable component); for a backcountry permit the refundable base is `fee_cents` minus the trailhead's `reservation_fee_cents`. The refund percentage is then chosen by band, with the boundaries inclusive exactly as written: when D is 14 or more, 100 percent; when D is between 7 and 13 inclusive, 50 percent; when D is between 2 and 6 inclusive, 25 percent; and when D is 1 or less, 0 percent. The refund in cents is the refundable base multiplied by that percentage and divided by 100, rounded half up to a whole cent at that single multiplication. The resulting amount is recorded on the resource's `refunded_cents`, added to the payment's `refunded_cents`, and added to the account's `credit_balance_cents`.

### 3.7. Campsite Waitlist: Joining, Position, Offers, and Claiming

When a campsite's desired dates are already taken, a visitor joins the waitlist by creating a `WaitlistEntry`, supplying `campsite_id`, `account_id`, a `check_in`, a `check_out`, a `party_size`, and `expected_campsite_version`. A waitlist join is allowed only when the exact half-open range from `check_in` to `check_out` on that campsite is currently *not* bookable — that is, it must overlap an existing reservation in `held`, `confirmed`, or `checked_in`. If the range is in fact currently bookable, the join is refused with `ERR_DATES_AVAILABLE`. The `party_size` must not exceed the campsite's `max_occupancy`, otherwise `ERR_OVER_OCCUPANCY`. The optimistic-concurrency check on `expected_campsite_version` applies as in §2.9, and a successful join increments the campsite's `version` by one.

The entry's `position` is assigned once on creation and never renumbered for the life of the entry, and it is included as a field in the waitlist entry's serialized representation returned by its create, read, and list responses. It is computed as one plus the count of existing waitlist entries in `waiting` or `offered` status for the very same combination of campsite, check-in, and check-out. The entry begins in `waiting` (its lifecycle states are `waiting`, `offered`, `claimed`, `expired`, and `cancelled`, with `claimed`, `expired`, and `cancelled` terminal) and its `offer_expires_at` is null until an offer is made.

Offers are made by cascade, not by request. Whenever a `CampReservation` on the same campsite and exact date range is cancelled or expires and releases its dates, the system makes an offer to the lowest-position entry still in `waiting` for that campsite/check-in/check-out key, moving it `waiting → offered` and setting its `offer_expires_at` to 24 hours after `now_utc`. A visitor claims an active offer: the entry must be `offered` and `now_utc` must be at or before `offer_expires_at`, otherwise `ERR_OFFER_EXPIRED`. Claiming moves the entry `offered → claimed`, creates a `confirmed` `CampReservation` for that campsite, range, and party size with its `origin_waitlist_id` set to this entry and its `total_cents` priced as in §3.6, creates a captured `Payment`, and clears `offer_expires_at`.

When an outstanding offer is not taken, it advances. A visitor may cancel: cancelling a `waiting` entry simply moves it `waiting → cancelled`; cancelling an `offered` entry moves it `offered → cancelled` and advances the offer to the next lowest-position `waiting` entry for the same key (moving that entry `waiting → offered` with a fresh 24-hour `offer_expires_at`). The housekeeping sweep expires an `offered` entry whose `offer_expires_at` has passed, moving it `offered → expired` and advancing the offer to the next lowest-position `waiting` entry for the same key in the same way. Positions are never renumbered when an entry leaves; gaps in the position sequence are tolerated, and offers always go to the lowest-position remaining `waiting` entry.

### 3.8. The Housekeeping Sweep and the Simulation Clock

Two administrative capabilities support testable, time-driven behaviour and are available to the `park_admin`, `finance`, and `system` roles. The first sets the simulation clock to a supplied `now_utc`, which is the instant all temporal checks consult. The second runs the housekeeping sweep, a single pass that performs every time-driven transition described above and returns counts of what it did: `expired_holds` (held timed-entry reservations, backcountry permits, and campground reservations whose `hold_expires_at` has passed, each moved to `expired` with the side effects described in their sections — slot held-count decrement and payment void for timed-entry; payment void for backcountry; payment void, date release, and waitlist cascade for campground), `expired_passes` (active passes past their `valid_to`), `lapsed_awards` (won lottery applications past their `award_accept_deadline`, each declined with its `party_size` returned to the draw's `awarded_count`), `advanced_offers` (offered waitlist entries past `offer_expires_at`, each expired with the offer advanced to the next waiting position), and `no_shows` (confirmed timed-entry reservations past their window end, each moved to `no_show` with the slot's `booked_count` decremented). The clock may also be read by any authenticated role.

## 4. Endpoint Definitions

New resource creations return HTTP 201; all other successful reads and mutations return HTTP 200. Every mutating endpoint enforces the role and scope rules of §2.1, and the per-endpoint authorized roles are listed below. Request and response bodies, side effects, and validation conditions are not repeated here — they live in the §3 workflow narratives — so this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /v1/_clock/set_current_utc | Set the simulation clock | park_admin, finance, system |
| GET | /v1/_clock | Read the simulation clock | visitor, ranger, park_admin, finance, system |
| POST | /v1/_ops/run | Run the housekeeping sweep | park_admin, finance, system |
| POST | /v1/accounts | Register an account | visitor, ranger, park_admin, finance, system |
| GET | /v1/accounts/{id} | Read an account | visitor, ranger, park_admin, finance, system |
| GET | /v1/accounts | List accounts (filter by home_park_id) | park_admin, finance, system |
| POST | /v1/parks | Create a park | system |
| GET | /v1/parks/{id} | Read a park | visitor, ranger, park_admin, finance, system |
| POST | /v1/atb-passes | Purchase an America the Beautiful pass | visitor |
| POST | /v1/atb-passes/{id}/void | Void a pass for a full refund | finance |
| GET | /v1/atb-passes/{id} | Read a pass | visitor, finance, park_admin, system |
| GET | /v1/atb-passes | List passes (filter by account_id, payment_id) | visitor, finance, park_admin, system |
| POST | /v1/timed-entry-slots | Create a timed-entry slot | park_admin |
| GET | /v1/timed-entry-slots/{id} | Read a timed-entry slot | visitor, ranger, park_admin, finance, system |
| GET | /v1/timed-entry-slots | List slots (filter by park_id, entry_date) | visitor, ranger, park_admin, finance, system |
| POST | /v1/timed-entry-reservations | Place a held vehicle reservation | visitor |
| POST | /v1/timed-entry-reservations/{id}/confirm | Confirm a held reservation | visitor |
| POST | /v1/timed-entry-reservations/{id}/check-in | Check in a confirmed reservation | ranger |
| POST | /v1/timed-entry-reservations/{id}/cancel | Cancel a held or confirmed reservation | visitor |
| GET | /v1/timed-entry-reservations/{id} | Read a reservation | visitor, ranger, park_admin, finance, system |
| GET | /v1/timed-entry-reservations | List reservations (filter by slot_id, account_id, payment_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/lottery-draws | Create a lottery draw | park_admin |
| GET | /v1/lottery-draws/{id} | Read a draw | visitor, ranger, park_admin, finance, system |
| GET | /v1/lottery-draws | List draws (filter by park_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/lottery-draws/{id}/applications | Submit a lottery application | visitor |
| POST | /v1/lottery-draws/{id}/draw | Run the deterministic draw | park_admin |
| POST | /v1/lottery-applications/{id}/withdraw | Withdraw a submitted application | visitor |
| POST | /v1/lottery-applications/{id}/accept | Accept a won award | visitor |
| POST | /v1/lottery-applications/{id}/decline | Decline a won award | visitor |
| GET | /v1/lottery-applications/{id} | Read a lottery application | visitor, park_admin, finance, system |
| GET | /v1/lottery-applications | List applications (filter by draw_id, account_id, application_payment_id, permit_payment_id) | visitor, park_admin, finance, system |
| POST | /v1/trailheads | Create a trailhead | park_admin |
| GET | /v1/trailheads/{id} | Read a trailhead | visitor, ranger, park_admin, finance, system |
| GET | /v1/trailheads | List trailheads (filter by park_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/wilderness-zones | Create a wilderness zone | park_admin |
| GET | /v1/wilderness-zones/{id} | Read a wilderness zone | visitor, ranger, park_admin, finance, system |
| GET | /v1/wilderness-zones | List zones (filter by park_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/backcountry-permits | Place a held backcountry permit | visitor |
| POST | /v1/backcountry-permits/{id}/confirm | Confirm a held permit (commit quota) | visitor |
| POST | /v1/backcountry-permits/{id}/cancel | Cancel a held or confirmed permit | visitor |
| GET | /v1/backcountry-permits/{id} | Read a backcountry permit | visitor, ranger, park_admin, finance, system |
| GET | /v1/backcountry-permits | List permits (filter by account_id, trailhead_id, park_id, payment_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/campsites | Create a campsite | park_admin |
| GET | /v1/campsites/{id} | Read a campsite | visitor, ranger, park_admin, finance, system |
| GET | /v1/campsites | List campsites (filter by park_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/camp-reservations | Place a held campground reservation | visitor |
| POST | /v1/camp-reservations/{id}/confirm | Confirm a held reservation | visitor |
| POST | /v1/camp-reservations/{id}/check-in | Check in a confirmed reservation | ranger |
| POST | /v1/camp-reservations/{id}/complete | Complete a checked-in stay | ranger |
| POST | /v1/camp-reservations/{id}/cancel | Cancel a held or confirmed reservation | visitor |
| GET | /v1/camp-reservations/{id} | Read a camp reservation | visitor, ranger, park_admin, finance, system |
| GET | /v1/camp-reservations | List camp reservations (filter by campsite_id, account_id, payment_id, origin_waitlist_id) | visitor, ranger, park_admin, finance, system |
| POST | /v1/waitlist-entries | Join a campsite waitlist | visitor |
| POST | /v1/waitlist-entries/{id}/claim | Claim an active waitlist offer | visitor |
| POST | /v1/waitlist-entries/{id}/cancel | Cancel a waiting or offered entry | visitor |
| GET | /v1/waitlist-entries/{id} | Read a waitlist entry | visitor, ranger, park_admin, finance, system |
| GET | /v1/waitlist-entries | List waitlist entries (filter by campsite_id, account_id) | visitor, ranger, park_admin, finance, system |
| GET | /v1/payments/{id} | Read a payment | visitor, finance, park_admin, system |
| GET | /v1/payments | List payments (filter by account_id) | finance, park_admin, system |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_VALIDATION | 400 |
| ERR_INVALID_PARTY_SIZE | 400 |
| ERR_INVALID_ITINERARY | 400 |
| ERR_GROUP_CONFIG_MISSING | 400 |
| ERR_AGE_REQUIREMENT | 400 |
| ERR_HOME_PARK_REQUIRED | 400 |
| ERR_UNAUTHORIZED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_EMAIL_TAKEN | 409 |
| ERR_DUPLICATE_RESERVATION | 409 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_SLOT_FULL | 409 |
| ERR_ZONE_FULL | 409 |
| ERR_TRAILHEAD_FULL | 409 |
| ERR_DATE_CONFLICT | 409 |
| ERR_DATES_AVAILABLE | 409 |
| ERR_PASS_OVERLAP | 409 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_STATE_INVALID | 409 |
| ERR_HOLD_EXPIRED | 409 |
| ERR_OFFER_EXPIRED | 409 |
| ERR_AWARD_WINDOW_CLOSED | 409 |
| ERR_LOTTERY_CLOSED | 409 |
| ERR_DRAW_NOT_READY | 409 |
| ERR_NOT_YET_RELEASED | 409 |
| ERR_OUTSIDE_BOOKING_WINDOW | 409 |
| ERR_OVER_OCCUPANCY | 409 |
| ERR_SITE_UNAVAILABLE | 409 |
| ERR_VOID_NOT_ALLOWED | 409 |
| ERR_OVER_REFUND | 409 |
| ERR_STALE_VERSION | 412 |
