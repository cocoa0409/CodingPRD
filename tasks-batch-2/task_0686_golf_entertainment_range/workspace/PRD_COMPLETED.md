# Golf Entertainment Range API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Golf Entertainment Range API, the operational backbone for a Topgolf-style golf entertainment venue. The system reconciles a demanding set of concerns that a busy range must juggle simultaneously: reserving climate-controlled hitting bays under dynamic, demand-sensitive pricing; running a fair walk-in queue when no reservation exists; tracking microchip-ball target scoring during live play; selling and redeeming stored-value gift cards and bay-turn game cards; administering membership tiers with wallet balances and loyalty points; and negotiating, confirming, and settling group and corporate event packages with their attendant food-and-beverage tabs.

The platform exists to make the venue's revenue and capacity decisions deterministic and auditable. Every bay-hour is a perishable asset, so the API governs the full lifecycle of a reservation from a short-lived hold through confirmation, play, and settlement, while a parallel walk-in queue lets the front desk seat parties on demand whenever a bay frees up. Money moves through an append-only charge ledger, member wallets, and loyalty accruals that are provisional until play actually concludes, so that a no-show or a void unwinds cleanly. Because several operators may act on the same bay or venue at once, the system layers optimistic concurrency control over the most contended writes and runs a system sweep to retire stale holds, abandoned queue tickets, and unplayed confirmed reservations on a logical clock that the operator controls for deterministic testing.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API. The API is mounted under the `/golf` prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly three roles, spelled precisely: `Guest`, `FrontDesk`, and `RangeManager`. A request that omits `X-User-Role`, or supplies a value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation (per the authorization column of the endpoint table in §4) is rejected with `ERR_FORBIDDEN_ROLE`.

The `Guest` role is entity-backed. When `X-User-Role` is `Guest`, the `X-User-ID` header value is the `id` of the acting `Member`; ownership checks on any member-scoped resource compare the resource's owning member reference — its `member_id` for reservations, queue tickets, lessons, and game cards, or its `organizer_member_id` for event packages — to `X-User-ID`. A `Guest` who attempts to mutate a reservation, queue ticket, lesson, or event package that they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

Both `FrontDesk` and `RangeManager` are opaque operator roles. When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`, and `FrontDesk` is not subject to the member-ownership check. Likewise, when `X-User-Role` is `RangeManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it may be recorded but is never matched against an entity's `id`. The two operator roles hold non-overlapping operational surfaces: the front desk runs sessions, F&B tabs, and walk-in seating, while the range manager provisions venues and bays, runs the sweep, drives the clock, takes bays out of service, voids session billing, and manages event packages.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is accepted only in the inclusive range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of leading items to skip; when omitted it defaults to 0, and its minimum value is 0. A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order. For the immutable `GiftCard` and `Charge` resources, which carry no `updated_at` or `version`, the `created_at` instant is likewise the ordering key. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Concurrency Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; the `id` is identity only and is never supplied by the client. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation, including the cascading mutations the server performs on its own initiative. The `version` field starts at 1 when the resource is created and increases by exactly 1 on each mutation; it is the basis for optimistic concurrency control. The resources that carry `updated_at` and `version` are `Venue`, `Bay`, `Member`, `GameCard`, `Reservation`, `GameSession`, `EventPackage`, `FBTab`, `QueueTicket`, and `Lesson`.

Two resources are deliberate exceptions. The `GiftCard` and the `Charge` are immutable after creation in the sense that they carry only `id` and `created_at` — they have no `updated_at` field and no `version` field at all. A gift card's stored value still changes as it is redeemed, but those changes are recorded on its value fields rather than via a version counter.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent entity whose version may have advanced under another writer. The OCC field is always supplied in the request body and is mandatory — it is never optional — on the two guarded writes below, and is never present on any other endpoint.

Confirming a reservation is guarded against the reserved `Bay`. The confirm request must carry `expected_bay_version`, which is the client's last observed `version` of the bay being reserved. If the bay's current `version` has advanced since the client last read it — for example because another confirmation has just claimed an overlapping window on that bay and bumped the bay's `version` — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), so the writer cannot act on a stale view of the bay.

Seating the next walk-in ticket is guarded against the `Venue`. The seat-next request must carry `expected_venue_version`, the client's last observed `version` of the venue. If the venue's current `version` has advanced since the client last read it — for example because another seating has just consumed an available bay, advancing `available_bay_count` and the venue's `version` — the seating is rejected with `ERR_STALE_VERSION` (HTTP 412), so the operator cannot act on a stale view of venue capacity. No other endpoint accepts a version field, and supplying one elsewhere has no effect.

### 2.6. Validation Ordering and the Error Hierarchy

When several conditions could fail on a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: first, authentication of the role header (`ERR_UNAUTHENTICATED`); then role authorization for the operation (`ERR_FORBIDDEN_ROLE`); then, for a `Guest` acting on a member-scoped resource, the ownership check (`ERR_NOT_RESOURCE_OWNER`); then existence of every path and foreign-key-referenced resource, validated left to right (`ERR_NOT_FOUND`); then request-body well-formedness (`ERR_INVALID_REQUEST`); then the state-precondition check that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); then the bay-window overlap check (`ERR_BAY_WINDOW_CONFLICT`); then bay-availability and lesson-capacity safety (`ERR_BAY_UNAVAILABLE`); then walk-in seating availability (`ERR_NO_BAY_AVAILABLE`); then the queue-head check (`ERR_NOT_QUEUE_HEAD`); then game-card credit sufficiency (`ERR_CARD_DEPLETED`); then funding sufficiency (`ERR_INSUFFICIENT_FUNDS`); and finally the optimistic-concurrency version match (`ERR_STALE_VERSION`). A failure earlier in this chain masks any failure that would have been raised later. In particular, a missing or unrecognized role is reported before any not-found, and a not-found before any state or business-rule error.

### 2.7. Nested Lookups, Filtering, and Left-to-Right Existence

The entity graph is flat: resources are peers linked by foreign keys rather than nested under one another in the URL. A relationship is discovered by filtering a list endpoint on the relevant foreign-key query parameter. Bays may be filtered by `venue_id` or by `current_session_id`, where the `current_session_id` filter is the reverse lookup that finds the bay currently occupied by a given session. Game cards may be filtered by `member_id`. Reservations may be filtered by `venue_id`, `bay_id`, `member_id`, or `charge_id`, the last being the reverse lookup from a charge back to the reservation it paid for. Sessions may be filtered by `bay_id`, `member_id`, `reservation_id`, `queue_ticket_id`, or `charge_id`. Event packages may be filtered by `venue_id` or `organizer_member_id`. F&B tabs may be filtered by `session_id` or `event_package_id`. Queue tickets may be filtered by `venue_id`, `member_id`, `game_card_id`, or `assigned_bay_id`, the last being the reverse lookup from a bay back to the ticket seated on it. Lessons may be filtered by `venue_id`, `bay_id`, or `member_id`. Charges may be filtered by `member_id`.

Whenever a request names resources by path segment or by foreign key in the body, the server validates their existence from left to right and returns `ERR_NOT_FOUND` for the first one that does not resolve, before evaluating any business rule that depends on the resource.

### 2.8. Monetary Precision and Loyalty Rounding

All monetary amounts are stored and returned as whole integer cents. Wherever a calculation introduces a fraction of a cent — a multiplier applied to a base rate, a percentage discount, a gratuity, or a tax — the result is rounded using the round-half-up rule to a whole number of cents. Loyalty points are likewise integers, but they are produced by taking the floor (rounding toward zero, discarding any fraction) rather than rounding half up. Where a calculation pins a specific order of operations — multiplying a whole block before rounding it once, or rounding a gratuity before computing tax on top of it — that order is mandatory and is detailed alongside the relevant calculation in §3.

### 2.9. The Logical Clock and the System Sweep

The server keeps a logical clock that drives every time-dependent rule: hold expiry, the late-cancel boundary, no-show detection, and queue-ticket expiry. At startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant.

A separate administrative sweep capability reconciles all time-expired state for a venue in one idempotent pass against the current clock. The sweep is the only path by which a hold lapses to `EXPIRED`, an abandoned waiting ticket lapses to `EXPIRED`, and a confirmed-but-unplayed reservation lapses to `NO_SHOW`; the details of each transition live with the relevant lifecycle in §3. Running the sweep twice at the same clock instant produces no further changes.

### 2.10. Cascading Mutations and State Propagation

Many operations mutate more than one resource. Seating a walk-in occupies a bay, may consume a game-card credit, and creates a session; confirming a reservation creates a charge and may debit a wallet and accrue provisional loyalty; settling an event applies a deposit waterfall and may refund the organizer. Every entity touched by such an operation independently has its `updated_at` refreshed and its `version` incremented by 1 (for those entities that carry a version). The computed roll-ups a venue exposes — `open_queue_length`, the count of its waiting queue tickets, and `available_bay_count`, its `bay_count` minus the number of its bays that are `OCCUPIED` or `OUT_OF_SERVICE` — always reflect the current state of the bays and tickets beneath it.

## 3. Business Logic & Workflows

### 3.1. Venues and Bays

A `RangeManager` provisions a **venue** by supplying its `name` and its `bay_count`, the number of hitting bays the venue will operate, which must be at least 1. Four further settings may be supplied or left to their defaults: `open_minute_of_day` and `close_minute_of_day`, the daily opening and closing times expressed as minutes since midnight UTC (defaulting to 540 and 1380 respectively, with opening accepted in the range 0 through 1439 and closing in the range 0 through 1440, and closing required to be strictly greater than opening); `base_rate_cents_per_half_hour`, the bay's base price for one 30-minute segment before any multiplier, which defaults to 2500 and may not be negative; and `peak_demand_factor`, an operator-set surge factor folded into the dynamic price, which defaults to 1.0 and must lie between 0.5 and 1.5 inclusive. A `peak_demand_factor` outside that band is rejected with `ERR_VALIDATION_RANGE`. A venue exposes two computed roll-ups, `open_queue_length` and `available_bay_count`, defined in §2.10.

Bays are created separately. A `RangeManager` adds a **bay** to a venue by supplying the `venue_id` it belongs to and a human-readable `label` such as "Bay 12"; the `floor_level` the bay sits on defaults to 1 and must be at least 1, and `has_target_tech`, indicating whether microchip-ball target scoring is installed, defaults to true. A bay's `status` is `AVAILABLE` on creation and otherwise takes the values `OCCUPIED` or `OUT_OF_SERVICE`; its `current_session_id` points at the `GameSession` currently occupying it and is null whenever the bay is `AVAILABLE`. A `RangeManager` may take a bay out of service for maintenance, which moves its `status` to `OUT_OF_SERVICE` and increments the bay's `version` by 1.

### 3.2. Members, Wallets, Game Cards, and Gift Cards

Anyone may register a **member** by supplying an `email`, which must be unique among members, and a `full_name`; a duplicate email is rejected with `ERR_DUPLICATE_EMAIL`. A member's `tier` defaults to `STANDARD` and may also be `GOLD` or `PLATINUM`; the tier sets both the reservation discount and the loyalty multiplier described later. A new member starts with `wallet_balance_cents`, `loyalty_points`, and `pending_loyalty_points` all at 0. The `wallet_balance_cents` is stored value, credited by top-ups and gift-card redemptions and debited by wallet-funded charges, restored when a charge is reversed, and never allowed to go negative. The `loyalty_points` balance holds confirmed points, while `pending_loyalty_points` holds provisional points that are still subject to confirmation or reversal.

A member or an operator may load stored value onto a member's wallet by submitting an `amount_cents`; the amount is added to `wallet_balance_cents` and the member's `version` is incremented by 1.

A **game card** is a bay-turn punch card purchased for a member. It is created with the `member_id` it belongs to and `credits_total`, the number of walk-in bay turns loaded onto it, which must be at least 1. Its `credits_remaining` starts equal to `credits_total` and is the count of credits not yet consumed by walk-in seatings; it is never negative. The card's `status` is `ACTIVE` until `credits_remaining` reaches 0, at which point it becomes `DEPLETED`.

A **gift card** is an immutable stored-value instrument issued with a `face_value_cents` of at least 1. Its `remaining_cents` starts at the face value and is the face value minus the sum of all redemptions, never negative, while `redeemed_total_cents` accumulates every amount redeemed against it, so that `redeemed_total_cents` and `remaining_cents` always sum back to `face_value_cents`. A gift card's `status` is `ISSUED` until `remaining_cents` reaches 0, at which point it becomes `DEPLETED`. Redeeming a gift card takes a target `member_id` and an `amount_cents`: the amount is subtracted from `remaining_cents` and added to `redeemed_total_cents`, and the same `amount_cents` is credited to that member's `wallet_balance_cents` with the member's `version` incremented by 1; if `remaining_cents` reaches 0 the card flips to `DEPLETED`. A redemption whose `amount_cents` exceeds the card's `remaining_cents` is rejected with `ERR_INSUFFICIENT_FUNDS`.

### 3.3. Reserving a Bay: The Dynamic Quote and the Hold

A `Guest` (or a `FrontDesk` operator acting on their behalf) books a bay window by creating a **reservation**, supplying the `venue_id`, the specific `bay_id`, the booking `member_id`, the `start_utc` and `end_utc` instants, and the `time_band`. The `day_type` defaults to `WEEKDAY` (the alternative is `WEEKEND`), the `pay_source` defaults to `CARD_ON_FILE` (the alternative is `WALLET`), and `time_band` must be one of `TWILIGHT`, `OFFPEAK`, or `PEAK`. The window is validated up front: `end_utc` must be strictly after `start_utc`, and the span must be a whole number of 30-minute segments. The window's placement within the venue's open and close minutes is not enforced as a rejection — a window that falls outside the venue's open and close minutes is nonetheless accepted, so the open/close-minute bounds are advisory rather than a hard validation gate. A malformed body — a missing required field, an invalid enum, a non-positive span, or a span that is not a whole number of 30-minute segments — is rejected with `ERR_INVALID_REQUEST`.

On creation the reservation enters `HOLD` status and the server computes its `quoted_price_cents` using the dynamic pricing rule, then stamps `hold_expires_utc` as the creation-clock instant plus the hold time-to-live of 30 minutes; if the hold is not confirmed by then, the sweep will expire it. The reservation also carries a `charge_id` (null until it is confirmed) and a `no_show_fee_cents` (0 unless a late-cancel or no-show path fires).

The **dynamic quote** is computed as follows. First, the number of 30-minute segments is the window length in minutes divided by 30 (already validated to be a whole number). A band multiplier is selected by `time_band`: 0.80 for `TWILIGHT`, 1.00 for `OFFPEAK`, and 1.60 for `PEAK`. A day factor is selected by `day_type`: 1.00 for `WEEKDAY` and 1.25 for `WEEKEND`. The raw multiplier is the band multiplier times the day factor times the venue's `peak_demand_factor`. The effective multiplier is the raw multiplier clamped to lie no lower than 0.80 and no higher than 2.00 — that is, the larger of 0.80 and the smaller of 2.00 and the raw multiplier. The gross amount is then computed by multiplying the venue's `base_rate_cents_per_half_hour` by the number of segments and by the effective multiplier as a single product, rounded half up to whole cents exactly once (the rounding is applied to the whole product, never per segment). A discount percentage is selected by the member's `tier`: 0.00 for `STANDARD`, 0.10 for `GOLD`, and 0.15 for `PLATINUM`. The discount amount is the gross times the discount percentage, rounded half up to whole cents. The `quoted_price_cents` is the gross minus the discount and is never negative.

A reservation may not be created on a bay whose window overlaps an already-`CONFIRMED` reservation or a `SCHEDULED` lesson on that same bay. Overlap is judged on the half-open interval from `start_utc` up to but not including `end_utc`, so two bookings that touch exactly at a boundary are back-to-back and permitted; a genuine overlap is rejected with `ERR_BAY_WINDOW_CONFLICT`.

### 3.4. Confirming, Cancelling, and No-Show

Confirming a hold advances the reservation from `HOLD` to `CONFIRMED`. The confirm request carries `expected_bay_version` (see §2.5) and may restate `pay_source`. Confirmation is permitted only when the reservation is still in `HOLD`; a confirm against a reservation in any other state is rejected with `ERR_INVALID_STATE`. The current clock must be before `hold_expires_utc` — a confirm attempted after the hold has lapsed is rejected with `ERR_HOLD_EXPIRED`. The reserved bay must not be `OUT_OF_SERVICE`, else `ERR_BAY_UNAVAILABLE`. The window must still be free of any `CONFIRMED` reservation or `SCHEDULED` lesson on the bay, re-checked at confirm time and rejected with `ERR_BAY_WINDOW_CONFLICT` on overlap. If `pay_source` is `WALLET`, the member's `wallet_balance_cents` must be at least `quoted_price_cents`, else `ERR_INSUFFICIENT_FUNDS`.

When confirmation succeeds, the server creates a charge of kind `BAY_RESERVATION` for `quoted_price_cents`, drawn from the reservation's `pay_source`, in `SETTLED` status, and records its identifier on the reservation's `charge_id`. If the pay source is `WALLET`, the member's `wallet_balance_cents` is debited by `quoted_price_cents`. Provisional loyalty is accrued on this charge: the member's `pending_loyalty_points` is increased by the provisional earn on `quoted_price_cents`. The reservation's `version` is incremented by 1, and the bay's `version` is incremented by 1 (this is the bump that the OCC guard of a competing confirmation observes).

Cancelling a reservation behaves differently depending on the state it is in. Cancelling a reservation that is still in `HOLD` simply moves it to `CANCELLED` with no charge to reverse and the `version` incremented by 1. Cancelling a reservation that is `CONFIRMED` turns on the late-cancel boundary. If the current clock is at or before `start_utc` minus the late-cancel window of 120 minutes, the cancel is on time: it is a full reversal — the original `BAY_RESERVATION` charge is set to `REVERSED`, and if the pay source was `WALLET` the member's `wallet_balance_cents` is credited back by the charge amount, the provisional loyalty accrued at confirmation is reversed out of `pending_loyalty_points`, and `no_show_fee_cents` stays 0. If instead the current clock is strictly after `start_utc` minus 120 minutes, the cancel is late: `no_show_fee_cents` is set to the no-show fee, which is `quoted_price_cents` times 0.50 rounded half up; the original bay charge is reversed and a new charge of kind `NO_SHOW_FEE` for that fee is created, so the net wallet effect is to debit the fee; and the provisional loyalty is reversed. The boundary is strict: a cancel exactly at `start_utc` minus 120 minutes is on time and incurs no fee, while one minute later is late and does incur the fee. In all cancel paths the reservation's `version` is incremented by 1. A cancel attempted from a state other than `HOLD` or `CONFIRMED` is rejected with `ERR_INVALID_STATE`.

A confirmed reservation that is never played becomes a **no-show** through the sweep. When the sweep runs and finds a `CONFIRMED` reservation whose `end_utc` is at or before the current clock and for which no `GameSession` carries that reservation's identifier, it moves the reservation to `NO_SHOW`. The no-show path sets `no_show_fee_cents` to `quoted_price_cents` times 0.50 rounded half up, but unlike the late cancel it does not create an additional `NO_SHOW_FEE` charge — the original retained bay charge is itself the penalty. The provisional loyalty never confirms and is reversed, and the reservation's `version` is incremented by 1.

### 3.5. The Walk-In Queue and Seating

When a party arrives without a reservation, a `Guest` (or a `FrontDesk` operator) takes a **queue ticket** at a venue by supplying the `venue_id`, the owning `member_id`, an optional `game_card_id` whose credit will be consumed when the turn is seated (omitted if the party will pay cash), and a `party_size` that defaults to 1 and must be at least 1. The ticket is created `WAITING`, and its `position` is computed as its 1-based rank among the venue's `WAITING` tickets ordered by `created_at` ascending. A waiting ticket carries an `assigned_bay_id` that is null until it is seated.

A `FrontDesk` operator seats the head of the queue. Seating targets the venue, carries `expected_venue_version` (see §2.5), and applies to the lowest-position waiting ticket — the one whose `position` is 1. If the targeted operation is attempted when the queue head is some other ticket, it is rejected with `ERR_NOT_QUEUE_HEAD`. There must be at least one bay at the venue whose `status` is `AVAILABLE`; if none is available the seating is rejected with `ERR_NO_BAY_AVAILABLE`. If the ticket names a `game_card_id`, that game card must be `ACTIVE` with `credits_remaining` of at least 1, else `ERR_CARD_DEPLETED`. The ticket must itself be `WAITING`, else `ERR_INVALID_STATE`.

A successful seating chooses, among the venue's `AVAILABLE` bays, the one with the lowest `floor_level`, breaking ties by `created_at` ascending, and sets that bay's `status` to `OCCUPIED`. If a `game_card_id` was supplied, its `credits_remaining` is decremented by 1, and if that reaches 0 the card flips to `DEPLETED`. The server creates a walk-in `GameSession` on the assigned bay with `play_status` of `OPEN` and `billing_status` of `UNBILLED`, sets the bay's `current_session_id` and the ticket's `assigned_bay_id` to wire the two together, moves the ticket to `SEATED`, and increments the ticket's `version` by 1 and the venue's `version` by 1 (the bump the OCC guard of a competing seating observes). A waiting ticket may instead be cancelled by its owner, moving it to `CANCELLED` and incrementing its `version` by 1. A waiting ticket that grows stale is expired by the sweep: when a ticket's `created_at` plus the queue time-to-live of 60 minutes is at or before the current clock, the sweep moves it to `EXPIRED` and increments its `version` by 1.

### 3.6. Game Sessions: Play and Scoring

A **game session** represents one party's play on one bay. A `FrontDesk` operator starts a session directly by supplying the `bay_id` being played and the playing `member_id`, optionally naming the `reservation_id` it realizes; if a `reservation_id` is given, that reservation must be `CONFIRMED`. The session may also carry a `queue_ticket_id` for walk-in sessions created by the seating flow (a directly started session leaves `reservation_id` or `queue_ticket_id` null as appropriate). Starting a session sets `play_status` to `OPEN` and `billing_status` to `UNBILLED`, marks the bay `OCCUPIED`, and records the session on the bay's `current_session_id`. A session also carries a `charge_id` that stays null until billing reaches `CHARGED`.

A session carries two independent status dimensions on the same row. The `play_status` dimension runs from `OPEN` to `ENDED`; the `billing_status` dimension runs from `UNBILLED` to either `CHARGED` or `VOID`, and the two dimensions evolve independently. As play proceeds, a `FrontDesk` operator records shots one at a time by submitting a shot's `points`; a negative `points` value is rejected with `ERR_VALIDATION_RANGE`. Each shot is appended to the session's append-only `shots` array as a record of its sequence and points, and the `total_score` and `shot_count` are recomputed on every append.

Scoring works as follows. The base score is the sum of the `points` of all recorded shots. A one-time streak bonus of 25 points is awarded if, and only if, there exists anywhere in the shot sequence (in `seq` order) a run of at least 5 consecutive shots each scoring at least 10 points; the bonus is added at most once per session regardless of how many qualifying runs occur. The `total_score` is the base plus the bonus, and `shot_count` is the number of shots recorded.

Ending play moves `play_status` from `OPEN` to `ENDED`. On ending, the server recomputes `total_score` one final time, frees the bay by setting its `status` back to `AVAILABLE` and its `current_session_id` to null, and confirms loyalty: it moves the provisional earn into confirmed points by computing the final earn on the session's net amount — where the session's net amount is the realizing reservation's `quoted_price_cents` when the session carries a `reservation_id`, and is otherwise the walk-in bay fee of 0 (so a walk-in session with no reservation earns 0 final loyalty) — adding that to the member's `loyalty_points` and subtracting the matching provisional earn (the same net-amount basis run through the provisional earn rule) from `pending_loyalty_points`. The session's `version` is incremented by 1. A session can be ended only from `OPEN`, else `ERR_INVALID_STATE`.

### 3.7. Loyalty Accrual: Provisional and Final

Loyalty points accrue in two stages keyed to the same divisor. The provisional earn on a net amount in cents is that amount divided by 100, floored — one point per whole 100 cents, independent of tier — and is what accrues to `pending_loyalty_points` at charge time; it is fully reversible. The final earn applies the member's tier multiplier before flooring: it is the net cents divided by 100, multiplied by the tier multiplier, then floored, where the tier multiplier is 1.0 for `STANDARD`, 1.25 for `GOLD`, and 1.5 for `PLATINUM`. The final earn is what lands in `loyalty_points` when a session ends, at which point the matching provisional accrual is cleared from `pending_loyalty_points`. Reversing a provisional earn (on a hold cancel, a late cancel, or a no-show) removes it from `pending_loyalty_points`; reversing a confirmed earn (on a void) removes it from `loyalty_points`.

### 3.8. Session Settlement and Voiding

The billing dimension of a session settles independently of play. A `FrontDesk` operator settles a session — moving `billing_status` from `UNBILLED` to `CHARGED` — only when the session's `play_status` is already `ENDED` and any F&B tab attached to the session is `CLOSED`; a settle attempted while play is still open, or with an open attached tab, is rejected (the open-tab case with `ERR_FBTAB_NOT_CLOSED`, and a settle from a non-`UNBILLED` billing state with `ERR_INVALID_STATE`). The settle request may restate `pay_source`; when it does not, the pay source defaults to `CARD_ON_FILE`. Settlement creates a charge of kind `SESSION_SETTLEMENT` whose `amount_cents` is the session's walk-in bay fee plus the `total_cents` of the closed F&B tab — and the session's walk-in bay fee is 0 cents (no input supplies a non-zero walk-in bay fee, so the closed F&B tab total is the only contribution to the amount) — records it on the session's `charge_id`, and, if the pay source is `WALLET`, debits the member's `wallet_balance_cents` by that amount (an insufficient wallet is rejected with `ERR_INSUFFICIENT_FUNDS`). The session's `version` is incremented by 1.

A `RangeManager` may instead void a session's billing, moving `billing_status` from `UNBILLED` to `VOID`. Voiding reverses any loyalty that has been confirmed for this session — subtracting the final earn from the member's `loyalty_points` — and reverses any outstanding provisional earn still sitting in `pending_loyalty_points`. The session's `version` is incremented by 1. `CHARGED` and `VOID` are mutually exclusive terminal billing states; a void from a non-`UNBILLED` state is rejected with `ERR_INVALID_STATE`.

### 3.9. Food and Beverage Tabs

A `FrontDesk` operator opens an **F&B tab** against either a game session or an event package, supplying `session_id` for a session tab or `event_package_id` for an event tab (a session tab leaves `event_package_id` null and vice versa). A new tab is `OPEN` with all totals at 0. Line items are appended one at a time by submitting a `name`, a `unit_price_cents`, and a `qty` that defaults to 1; each is recorded in the append-only `line_items` array as a record of its sequence, name, unit price, and quantity.

A tab's money fields are recomputed on every append in a pinned order. The `subtotal_cents` is the sum over all line items of `unit_price_cents` times `qty`. The `gratuity_cents` is an auto-gratuity of 18 percent of the subtotal, rounded half up to whole cents on the full subtotal (not per line item). The `tax_cents` is 8.25 percent of the sum of the subtotal and the already-rounded gratuity, rounded half up to whole cents — tax is computed on the subtotal-plus-gratuity, and the gratuity is rounded before the tax is computed. The `total_cents` is the sum of `subtotal_cents`, `gratuity_cents`, and `tax_cents`.

Closing a tab moves it from `OPEN` to `CLOSED` and freezes `subtotal_cents`, `gratuity_cents`, `tax_cents`, and `total_cents` so that they no longer respond to further line-item appends; the tab's `version` is incremented by 1. A close from a non-`OPEN` state is rejected with `ERR_INVALID_STATE`. Closing is the precondition that lets the tab's owning session or event package settle.

### 3.10. Event Packages: Quote, Negotiation, Confirmation, and Settlement

A group or corporate **event package** is quoted by a `Guest` or a `RangeManager` supplying the `venue_id`, the `organizer_member_id`, the `headcount_estimate` used for the provisional quote (at least 1), and the `per_head_package_cents` package price per attendee (which may not be negative). Two further amounts may be supplied or defaulted: `bay_block_cents`, the flat charge for the reserved bay block, defaulting to 15000 and never negative; and `deposit_cents`, the up-front deposit collected at confirmation, defaulting to 0 and never negative. On creation the package is `QUOTED` and its `estimated_total_cents` is computed by the provisional pricing variant: the `headcount_estimate` times `per_head_package_cents`, plus `bay_block_cents`. The package also carries an `actual_attendee_count` that is null until settlement, a `final_total_cents` that is null until settlement, and a `deposit_refund_cents` for the waterfall remainder returned at settlement.

The package moves through a revision loop before it is confirmed. A `RangeManager` may move a `QUOTED` package into `NEGOTIATING`. From `NEGOTIATING`, a `RangeManager` may revise the package — adjusting any of `headcount_estimate`, `per_head_package_cents`, `bay_block_cents`, or `deposit_cents` — which returns it to `QUOTED` and recomputes `estimated_total_cents` from the updated values using the same provisional formula. A `RangeManager` confirms a `QUOTED` package, which requires that `deposit_cents` not exceed the organizer member's `wallet_balance_cents` (else `ERR_INSUFFICIENT_FUNDS`); confirmation debits the organizer's `wallet_balance_cents` by `deposit_cents`, holding it as a deposit, moves the package to `CONFIRMED`, and increments the package's `version` by 1. Each of these transitions increments the package's `version` by 1, and a transition attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

Settlement closes out a `CONFIRMED` package. A `RangeManager` settles by supplying the `actual_attendee_count`, which must be at least 1, and which is permitted only after every F&B tab attached to this event (every tab whose `event_package_id` is this package) is `CLOSED`; a settle with an open event tab is rejected with `ERR_FBTAB_NOT_CLOSED`. Settlement records `actual_attendee_count` and computes `final_total_cents` by the settled pricing variant: the `actual_attendee_count` times `per_head_package_cents`, plus `bay_block_cents`, plus the sum of `total_cents` over all closed F&B tabs for the event. The held deposit is then applied by the deposit waterfall: starting from `deposit_cents` as the remaining amount, three buckets are filled in this fixed order — first the `bay_block_cents`, then the per-head amount (`actual_attendee_count` times `per_head_package_cents`), then the event F&B total — and for each bucket in turn the amount applied is the smaller of the remaining deposit and the bucket's value, with that applied amount subtracted from the remaining. The deposit actually applied is `deposit_cents` minus whatever remains after the three buckets, and that leftover remainder becomes `deposit_refund_cents`. The server creates a charge of kind `EVENT_SETTLEMENT` for the organizer whose amount is `final_total_cents` minus the deposit applied and whose `pay_source` is `CARD_ON_FILE`, credits the organizer's `wallet_balance_cents` by `deposit_refund_cents`, moves the package to `SETTLED`, and increments the package's `version` by 1.

A package may be cancelled from `QUOTED`, `NEGOTIATING`, or `CONFIRMED`. If the package was `CONFIRMED` at the time of cancellation, the full `deposit_cents` is credited back to the organizer's `wallet_balance_cents` as a deposit reversal; from `QUOTED` or `NEGOTIATING` there is no deposit to reverse. Cancellation moves the package to `CANCELLED` and increments its `version` by 1. A cancel from `SETTLED` or `CANCELLED` is rejected with `ERR_INVALID_STATE`.

### 3.11. Lessons, Clinics, and Simulators

A `Guest` or a `FrontDesk` operator schedules a **lesson** on a bay window by supplying the `venue_id`, the `bay_id` (which may be a simulator), the student `member_id`, the `kind`, the `start_utc` and `end_utc` (with `end_utc` strictly after `start_utc`), and the number of `seats` requested, which defaults to 1 and must be at least 1. The `kind` is one of `PRIVATE_LESSON`, `GROUP_CLINIC`, or `SIMULATOR`, and it governs capacity: a `GROUP_CLINIC` may request more than one seat, but a `PRIVATE_LESSON` or a `SIMULATOR` is capped at a single seat, and a request for more than one seat on either of those kinds is rejected with `ERR_BAY_UNAVAILABLE`. A lesson may not be scheduled on a bay whose window overlaps an existing `CONFIRMED` reservation or `SCHEDULED` lesson on that bay, judged on the same half-open interval as reservations, and an overlap is rejected with `ERR_BAY_WINDOW_CONFLICT`; a bay that is `OUT_OF_SERVICE` likewise rejects with `ERR_BAY_UNAVAILABLE`.

A lesson is `SCHEDULED` on creation. A `FrontDesk` operator marks a lesson `COMPLETED`, and a `Guest` or `FrontDesk` operator may instead cancel it, moving it to `CANCELLED`; either transition increments the lesson's `version` by 1, and a transition attempted from a state other than `SCHEDULED` is rejected with `ERR_INVALID_STATE`.

### 3.12. The Charge Ledger

Every movement of money writes an immutable **charge** to an append-only ledger. A charge records the charged `member_id`, its `kind` — one of `BAY_RESERVATION`, `SESSION_SETTLEMENT`, `EVENT_SETTLEMENT`, or `NO_SHOW_FEE` — its `amount_cents`, the `pay_source` (`WALLET` or `CARD_ON_FILE`) the funds were drawn from, and its `status`, which is `SETTLED` when created and becomes `REVERSED` when a compensating reversal fires (as on an on-time cancel or a late cancel's original-charge reversal). Charges are read back individually or listed, and a reservation or session can be traced to its charge through the `charge_id` reverse-lookup filters described in §2.7.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that read a resource, or that drive a state transition or otherwise modify an existing resource, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/golf/venues` | Create a venue | RangeManager |
| GET | `/golf/venues/{venue_id}` | Get a venue with computed queue length and bay availability | Guest, FrontDesk, RangeManager |
| GET | `/golf/venues` | List venues | Guest, FrontDesk, RangeManager |
| POST | `/golf/venues/{venue_id}/seat_next` | Seat the head waiting walk-in ticket onto an available bay | FrontDesk |
| POST | `/golf/venues/{venue_id}/sweep_holds` | Run the system sweep for a venue | RangeManager |
| POST | `/golf/bays` | Create a bay under a venue | RangeManager |
| GET | `/golf/bays/{bay_id}` | Get a bay | Guest, FrontDesk, RangeManager |
| GET | `/golf/bays` | List bays, filterable by venue or current session | Guest, FrontDesk, RangeManager |
| POST | `/golf/bays/{bay_id}/out_of_service` | Take a bay out of service | RangeManager |
| POST | `/golf/members` | Register a member | Guest, FrontDesk, RangeManager |
| GET | `/golf/members/{member_id}` | Get a member with wallet and loyalty balances | Guest, FrontDesk, RangeManager |
| POST | `/golf/members/{member_id}/wallet/topup` | Load stored value onto a member's wallet | Guest, FrontDesk, RangeManager |
| POST | `/golf/game-cards` | Purchase a game card for a member | Guest, FrontDesk, RangeManager |
| GET | `/golf/game-cards/{card_id}` | Get a game card | Guest, FrontDesk, RangeManager |
| GET | `/golf/game-cards` | List game cards, filterable by member | Guest, FrontDesk, RangeManager |
| POST | `/golf/gift-cards` | Issue a gift card | Guest, FrontDesk, RangeManager |
| GET | `/golf/gift-cards/{gift_card_id}` | Get a gift card | Guest, FrontDesk, RangeManager |
| POST | `/golf/gift-cards/{gift_card_id}/redeem` | Redeem gift-card value onto a member's wallet | Guest, FrontDesk, RangeManager |
| POST | `/golf/reservations` | Create a HOLD reservation and compute its dynamic quote | Guest, FrontDesk |
| GET | `/golf/reservations/{reservation_id}` | Get a reservation | Guest, FrontDesk, RangeManager |
| GET | `/golf/reservations` | List reservations, filterable by venue, bay, member, or charge | Guest, FrontDesk, RangeManager |
| POST | `/golf/reservations/{reservation_id}/confirm` | Confirm a HOLD reservation | Guest, FrontDesk |
| POST | `/golf/reservations/{reservation_id}/cancel` | Cancel a HOLD or CONFIRMED reservation | Guest, FrontDesk |
| POST | `/golf/sessions` | Start a game session on a bay | FrontDesk |
| GET | `/golf/sessions/{session_id}` | Get a session with score and shots | Guest, FrontDesk, RangeManager |
| GET | `/golf/sessions` | List sessions, filterable by bay, member, reservation, queue ticket, or charge | Guest, FrontDesk, RangeManager |
| POST | `/golf/sessions/{session_id}/shots` | Record a shot and recompute the score | FrontDesk |
| POST | `/golf/sessions/{session_id}/end` | End play, free the bay, and confirm loyalty | FrontDesk |
| POST | `/golf/sessions/{session_id}/settle` | Settle session billing | FrontDesk |
| POST | `/golf/sessions/{session_id}/void` | Void session billing | RangeManager |
| POST | `/golf/event-packages` | Quote a group or corporate event package | Guest, RangeManager |
| GET | `/golf/event-packages/{event_package_id}` | Get an event package | Guest, FrontDesk, RangeManager |
| GET | `/golf/event-packages` | List event packages, filterable by venue or organizer | Guest, FrontDesk, RangeManager |
| PATCH | `/golf/event-packages/{event_package_id}` | Revise a NEGOTIATING package and return it to QUOTED | RangeManager |
| POST | `/golf/event-packages/{event_package_id}/negotiate` | Move a QUOTED package into NEGOTIATING | RangeManager |
| POST | `/golf/event-packages/{event_package_id}/confirm` | Confirm a package and collect the deposit | RangeManager |
| POST | `/golf/event-packages/{event_package_id}/settle` | Settle a confirmed package | RangeManager |
| POST | `/golf/event-packages/{event_package_id}/cancel` | Cancel a package | RangeManager |
| POST | `/golf/fb-tabs` | Open an F&B tab on a session or event | FrontDesk |
| GET | `/golf/fb-tabs/{fb_tab_id}` | Get an F&B tab with computed totals | Guest, FrontDesk, RangeManager |
| GET | `/golf/fb-tabs` | List F&B tabs, filterable by session or event | Guest, FrontDesk, RangeManager |
| POST | `/golf/fb-tabs/{fb_tab_id}/items` | Append a line item and recompute totals | FrontDesk |
| POST | `/golf/fb-tabs/{fb_tab_id}/close` | Close a tab, freezing its totals | FrontDesk |
| POST | `/golf/queue-tickets` | Take a walk-in queue ticket | Guest, FrontDesk |
| GET | `/golf/queue-tickets/{queue_ticket_id}` | Get a queue ticket with its position | Guest, FrontDesk, RangeManager |
| GET | `/golf/queue-tickets` | List queue tickets, filterable by venue, member, game card, or assigned bay | Guest, FrontDesk, RangeManager |
| POST | `/golf/queue-tickets/{queue_ticket_id}/cancel` | Cancel a WAITING queue ticket | Guest, FrontDesk |
| POST | `/golf/lessons` | Schedule a lesson, clinic, or simulator booking | Guest, FrontDesk |
| GET | `/golf/lessons/{lesson_id}` | Get a lesson | Guest, FrontDesk, RangeManager |
| GET | `/golf/lessons` | List lessons, filterable by venue, bay, or member | Guest, FrontDesk, RangeManager |
| POST | `/golf/lessons/{lesson_id}/complete` | Mark a lesson completed | FrontDesk |
| POST | `/golf/lessons/{lesson_id}/cancel` | Cancel a scheduled lesson | Guest, FrontDesk |
| GET | `/golf/charges/{charge_id}` | Get a charge ledger entry | Guest, FrontDesk, RangeManager |
| GET | `/golf/charges` | List charges, filterable by member | Guest, FrontDesk, RangeManager |
| POST | `/golf/_clock/set_current_utc` | Set the server's logical clock | RangeManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BAY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_BAY_UNAVAILABLE` | 409 Conflict |
| `ERR_NO_BAY_AVAILABLE` | 409 Conflict |
| `ERR_NOT_QUEUE_HEAD` | 409 Conflict |
| `ERR_CARD_DEPLETED` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_HOLD_EXPIRED` | 409 Conflict |
| `ERR_FBTAB_NOT_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION_RANGE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
