# Arcade Card API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a family entertainment center of the "eat-and-play" arcade variety, where guests load stored value onto reusable game cards, play attractions for e-ticket points, redeem those points for physical prizes, and book private party rooms bundled with food-and-beverage combos. The platform must behave as a disciplined value ledger: every credit purchased, every bonus granted, every chip spent, and every point earned or redeemed has to be reconstructible from an immutable transaction trail, because at the end of each business day a manager physically counts the floor's outstanding chip liability and prize inventory and reconciles those counts against what the system believes should be there.

The domain is deceptively rich. A single reload can push a member across a loyalty tier boundary, changing the promotional bonus rate they receive; a party confirmation fans out into a cascade of provisioned cards and bonus grants that must be perfectly reversed if the party is later reverted or cancelled; a prize redemption reserves points and inventory at one price and settles at another if the prize was repriced in between. Because multiple front-desk and floor operators act on the same cards and bookings, the system also has to defend against acting on stale reads, using explicit version checks on the parent resource being consumed.

The requirements below define the entities, their lifecycles, the exact arithmetic of every value calculation, the validation order that governs rejections, and the role-based permissions that gate each operation. Monetary amounts are held in integer cents and points are held as whole integers throughout.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Member`, `Cashier`, `Attendant`, `Coordinator`, and `Manager`.

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. A member is a registered guest acting through self-service kiosks on their own cards. Ownership is enforced: when a `Member` plays an attraction or reserves a redemption against a game card, that card's `owner_member_id` must equal `X-User-ID`, and when a `Member` acts in the context of a party booking, that booking's `host_member_id` must equal `X-User-ID`. An ownership failure is an `ERR_UNAUTHORIZED` (HTTP 403).
- When `X-User-Role` is `Cashier`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A cashier is a front-desk operator responsible for card issuance, activation, reloads, party check-in, extra wristband issuance, and wristband return.
- When `X-User-Role` is `Attendant`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A floor attendant runs gameplay and fulfills or cancels redemptions.
- When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A party coordinator owns the full party booking lifecycle.
- When `X-User-Role` is `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A venue manager owns configuration (attractions, prizes, packages, rooms), card freeze and close authority, daily reconciliation, and the logical clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. A `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100; a non-integer `limit` falls back to the default of 10. The `offset` parameter is the number of items to skip and defaults to 0; a negative or non-integer `offset` falls back to 0.

Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order; items sharing the same `created_at` (as happens when several are created at a single logical-clock instant) are further ordered by their creation sequence, i.e. the order in which they were inserted. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 and increments by one on every mutation. It is the anchor for optimistic concurrency control (§2.8).

Two entities are deliberately leaner. A `CardLedgerEntry` and a `GamePlay` are immutable audit records: each carries only `id` and `created_at`, and neither has an `updated_at` nor a `version` field. Whenever a derived balance or a computed total on a resource changes as a side effect of an operation, that counts as a mutation of the resource — its `updated_at` is refreshed and its `version` increments accordingly.

### 2.5. The Logical Clock and the Business Day

The system runs on a logical clock rather than wall-clock time, so that time-sensitive workflows are deterministic and testable. At server startup the clock reads exactly `2026-05-01T00:00:00Z`; until it is explicitly moved it stays at that default and never falls back to real-world time. A manager may advance the clock by supplying a target instant in the `to_iso8601` field, after which the clock reads that instant.

Every timestamp the server records — a ledger entry's `occurred_at`, a booking's `checked_in_at` and `completed_at` — is read from this logical clock. The `business_day` stamped on ledger entries and game plays is the UTC calendar date (in `YYYY-MM-DD` form) derived from the logical clock at the moment the record is written; a `DailyReconciliation`'s `business_day` is instead the date supplied by the manager when it is opened (§3.8) and is not derived from the clock.

### 2.6. Monetary and Points Precision

All money is stored and computed in integer cents; all e-ticket points are whole integers. There are no fractional cents or fractional points anywhere in the system.

Where a calculation multiplies by a fractional rate — a reload's bonus percentage or a gameplay points multiplier — the result is taken to the whole integer below (floor). Where a calculation converts an elapsed time window into a whole number of hours, any partial hour rounds up to the next whole hour (ceiling). Loyalty tier thresholds are inclusive: a member qualifies for a tier when their cumulative spend is greater than or equal to that tier's threshold. Reconciliation variances are exact integer differences, and the zero-variance boundary is tested exactly.

### 2.7. The Card Ledger Principle

Every game card's three balances are derived, not stored independently. A `CardLedgerEntry` is an append-only line item; entries are never edited or deleted. Each entry records a signed `chip_delta_cents`, a signed `bonus_delta_cents`, and a signed `points_delta` (each defaulting to 0 when that dimension is untouched), plus the `card_id` it belongs to, its `entry_type`, a human-readable `note` describing provenance, the `business_day` it fell on, and its `occurred_at` timestamp. The permitted `entry_type` values are `RELOAD`, `BONUS_GRANT`, `GAMEPLAY_DEBIT`, `POINTS_EARN`, `POINTS_HOLD`, `POINTS_SETTLE`, `POINTS_REFUND`, and `BONUS_CLAWBACK`.

At any moment a card's `chip_balance_cents` equals the sum of `chip_delta_cents` across its entries, its `bonus_chip_balance_cents` equals the sum of `bonus_delta_cents`, and its `ticket_points_balance` equals the sum of `points_delta`. The `chip_balance_cents` represents purchased stored value; the `bonus_chip_balance_cents` represents promotional or party-granted value. When a card is charged for a play, promotional chips are always spent before purchased chips (the waterfall rule of §3.3).

### 2.8. Optimistic Concurrency Control

Two operations consume a shared parent resource and therefore require the caller to prove it is acting on a fresh read of that parent. In both, the caller sends the parent's last-observed `version`, and the server rejects the write if the parent's current `version` has moved on.

Reserving a redemption consumes points on a game card. The request must include `expected_card_version` carrying the client's last-observed `version` of that card. If another writer — a prior redemption or a game play on the same card — has advanced the card's `version` since the client read it, the reservation is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the points available to hold is stale.

Issuing an extra wristband consumes headcount on a party booking. The request must include `expected_booking_version` carrying the client's last-observed `version` of that booking. If another writer has already added a wristband — consuming room and venue headroom and advancing the booking's `version` — the issue is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of remaining headcount is stale.

No other endpoint takes a version field, and none is subject to this check.

### 2.9. Cascading Consistency

Several operations mutate more than one entity in a single atomic step, and every secondary effect is part of the contract. Confirming a party booking provisions wristbands, provisions a fresh card for each wristband, and grants promotional chips onto each of those cards. Reverting or cancelling a confirmed (or checked-in) booking must exactly compensate that fan-out: voiding the wristbands and clawing back the promotional chips that were granted. Redemption transitions move points between a card's balance and a hold, and simultaneously adjust the prize item's reserved and on-hand quantities. Each such cascade appends the appropriate immutable ledger entries and refreshes the `updated_at` and `version` of every entity it touches. The precise per-step effects are described alongside each workflow in Section 3.

### 2.10. Validation Order and Resource Resolution

When several conditions could each reject a request, they are evaluated in a fixed precedence so that the returned error is deterministic:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for this endpoint, and a `Member` owns the card or booking it targets, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every identifier is resolved before any business rule runs. Path identifiers are checked first, left to right, then body foreign keys. The first identifier that resolves to nothing yields the matching `ERR_<ENTITY>_NOT_FOUND` (404): `ERR_MEMBER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, `ERR_ATTRACTION_NOT_FOUND`, `ERR_PRIZE_NOT_FOUND`, `ERR_REDEMPTION_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_WRISTBAND_NOT_FOUND`, or `ERR_RECONCILIATION_NOT_FOUND`.
4. **Body well-formedness** — on write endpoints, required fields must be present, enums valid, and numeric fields such as `quantity`, `guest_count`, and `amount_cents` strictly positive; for bookings, `end_at` must be strictly after `start_at`. A violation is `ERR_VALIDATION` (422).
5. **Card operability** — for a reload, a game play, or a redemption reservation, the target card must be `ACTIVE`. A `FROZEN` card yields `ERR_CARD_FROZEN` (409); an `INACTIVE` or `CLOSED` card yields `ERR_CARD_NOT_ACTIVE` (409).
6. **Transition legality** — an action must be permitted from the target entity's current state, else the matching `ERR_INVALID_<ENTITY>_STATE` (409): `ERR_INVALID_CARD_STATE`, `ERR_INVALID_REDEMPTION_STATE`, `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_WRISTBAND_STATE`, or `ERR_INVALID_RECONCILIATION_STATE`.
7. **Referential status** — the related configuration resource must be in the right status: an attraction must be `OPEN` for a play (`ERR_ATTRACTION_NOT_OPEN`, 409); a prize must be `AVAILABLE` for a new redemption (`ERR_PRIZE_UNAVAILABLE`, 409); a room must be `AVAILABLE` (not `MAINTENANCE`) at check-in (`ERR_ROOM_UNAVAILABLE`, 409).
8. **Concurrency** — the OCC version check of §2.8, else `ERR_STALE_VERSION` (412).
9. **Temporal** — check-in must fall inside the booking window and confirmation must not clash with another room booking (§3.6, §3.5); violations are `ERR_OUTSIDE_BOOKING_WINDOW` and `ERR_ROOM_TIME_CONFLICT` (both 409).
10. **Capacity constraints** — guest count within room capacity (`ERR_GUEST_COUNT_EXCEEDS_ROOM`), aggregate venue occupancy within the venue cap (`ERR_VENUE_CAPACITY_EXCEEDED`), and redemption quantity within available prize units (`ERR_INSUFFICIENT_STOCK`); all 409.
11. **Fiscal sufficiency** — the card must be able to fund the operation: chips for a play (`ERR_INSUFFICIENT_CHIP_BALANCE`, 402), points for a redemption reserve or settlement (`ERR_INSUFFICIENT_POINTS`, 402), and a reload must not breach the per-card purchased-balance cap (`ERR_CARD_BALANCE_CAP_EXCEEDED`, 422).

This ordering is authoritative: for example, a mid-flight freeze that renders a card non-operable surfaces at step 5 as `ERR_CARD_FROZEN` before any transition, concurrency, or fiscal check further down the list is even considered.

## 3. Business Logic & Workflows

### 3.1. Members, Card Issuance, and the Card Lifecycle

A guest becomes a member when a cashier or manager registers them with an `email` (unique among members; a registration whose `email` duplicates an existing member's is rejected with `ERR_VALIDATION`, 422), a `full_name`, and an optional `promo_opt_in` flag indicating enrollment in eat-and-play promotions, which defaults to false when omitted. A new member starts with a `status` of `ACTIVE` (the alternative, `SUSPENDED`, is reserved for future administrative action), a `lifetime_spend_cents` of 0, and a `membership_tier` of `NONE`. The tier and lifetime spend evolve through reloads, described in §3.2.

Stored value lives on a `GameCard`, issued by a cashier. A newly issued card is `INACTIVE` with all three balances — `chip_balance_cents`, `bonus_chip_balance_cents`, and `ticket_points_balance` — at zero. A card may optionally carry an `owner_member_id` linking it to a member; anonymous walk-in cards leave this null. Cards can be listed and filtered by their owner and by status.

The card walks a small lifecycle. A cashier activates an `INACTIVE` card, moving `INACTIVE → ACTIVE`, after which it becomes spendable and reloadable. A manager may freeze an `ACTIVE` card, moving `ACTIVE → FROZEN`, which blocks reload, gameplay, and redemption while it lasts. A card is closed — moving `ACTIVE → CLOSED` or `FROZEN → CLOSED` — by a cashier or a manager; once `CLOSED` its balances are frozen in place and no further ledger entries may ever be appended. `CLOSED` is terminal. Reload, gameplay, and redemption are ordinary operations valid only while a card is `ACTIVE`; they are not lifecycle transitions. Any lifecycle trigger — activate, freeze, or close — attempted from a state the transition table forbids is rejected with `ERR_INVALID_CARD_STATE` (409); each such transition that does succeed increments the card's `version`.

### 3.2. Reloading Stored Value and Loyalty Tiers

When a cashier reloads a card, they supply an `amount_cents` to add and an optional `promo_code`. The `promo_code`, if supplied, is accepted but has no effect on the bonus, the balances, or lifetime spend. The reload both credits the card and, for owned cards, advances the owner's loyalty standing — and the order in which those two effects are computed matters, because the promotional bonus depends on the tier the member held *before* this reload, while the tier itself is recomputed *after* the reload's spend is booked.

The computation proceeds in a pinned order. First, the member's tier is read from their current `lifetime_spend_cents`, before this reload's amount is added. That pre-reload tier selects the bonus rate: a `NONE` member earns no bonus, a `SILVER` member earns five percent, a `GOLD` member earns ten percent, and a `PLATINUM` member earns twenty percent. Second, the bonus in cents is the `amount_cents` multiplied by that rate, taken down to the whole cent below. Third, the purchased credit is applied — `chip_balance_cents` grows by `amount_cents` — and the bonus is applied — `bonus_chip_balance_cents` grows by the bonus. Fourth, and only now, the member's `lifetime_spend_cents` grows by `amount_cents`, and their `membership_tier` is recomputed from that new lifetime spend. Only the reload's purchased `amount_cents` accrues to lifetime spend; granted bonus credits never do.

Tier boundaries are inclusive and expressed against lifetime spend in cents: a member is `PLATINUM` at 500,000 cents or more, otherwise `GOLD` at 200,000 cents or more, otherwise `SILVER` at 50,000 cents or more, otherwise `NONE`. When a card has no owner (`owner_member_id` is null), there is no member to score: the effective tier is `NONE`, the bonus is zero, and no lifetime spend is accrued.

Each successful reload appends a `RELOAD` ledger entry recording the purchased credit, and — only when the bonus is greater than zero — a `BONUS_GRANT` entry recording the promotional credit; the card's `version` increments. A reload is refused if it would push the purchased balance too high: the resulting `chip_balance_cents` must not exceed the per-card cap of 100,000 cents ($1,000.00), and a reload that would breach it is rejected with `ERR_CARD_BALANCE_CAP_EXCEEDED` (422). The cap governs purchased chips only; promotional bonus does not count against it.

### 3.3. Attractions and Playing for Points

A manager configures each `Attraction` with a `name`, a `chip_cost_cents` charged per play (strictly positive), and a `points_award` — the base e-ticket points granted per play before the member multiplier (zero or more). An attraction is `OPEN` on creation and may later be set to `MAINTENANCE` or `RETIRED`, or repriced, through a manager update that increments its `version`. Attractions are readable by everyone.

A play is initiated by an attendant or by the owning member, who supply the `card_id` and the `attraction_id`; the attraction must be `OPEN`, or the play is rejected with `ERR_ATTRACTION_NOT_OPEN` (409). The cost of the play is a snapshot of the attraction's `chip_cost_cents` at play time, recorded on the resulting `GamePlay` as its own `chip_cost_cents`. Before charging, the card's combined promotional and purchased chips must be at least the cost; if `bonus_chip_balance_cents` plus `chip_balance_cents` is less than the cost the play is rejected with `ERR_INSUFFICIENT_CHIP_BALANCE` (402).

The charge follows the waterfall: the portion drawn from bonus, recorded as `chip_from_bonus_cents`, is the smaller of the card's `bonus_chip_balance_cents` and the cost; the remaining cost is drawn from purchased value and recorded as `chip_from_stored_cents`. The card's `bonus_chip_balance_cents` decreases by the bonus portion and its `chip_balance_cents` by the stored portion. When the bonus balance alone covers the whole cost, the stored portion is zero and purchased value is untouched. Points are then awarded: the attraction's `points_award` is multiplied by the member's tier multiplier — 1.0 for `NONE` (which also applies to anonymous cards), 1.1 for `SILVER`, 1.25 for `GOLD`, and 1.5 for `PLATINUM` — and taken down to the whole point below to yield `points_awarded`, which is added to the card's `ticket_points_balance`. A single `GAMEPLAY_DEBIT` ledger entry captures the whole play, with a negative chip delta equal to the stored portion, a negative bonus delta equal to the bonus portion, and a positive points delta equal to the points awarded; the card's `version` increments. Game plays are readable and listable, filterable by card and by attraction; a read of a game-play id that resolves to nothing yields `ERR_GAMEPLAY_NOT_FOUND` (404).

### 3.4. Prizes and the Redemption Lifecycle

A manager stocks the redemption counter with a `PrizeItem` carrying a `name`, a `points_price` (points required per unit, strictly positive), and a `stock_qty` of physical units on hand (zero or more). The system also tracks a `reserved_qty`, the number of units currently held by open reservations, which starts at zero. A prize is `AVAILABLE` on creation; a manager update may reprice it, restock it, or set it `DISCONTINUED`. When an update does not explicitly supply a `status` and the prize is not `DISCONTINUED`, its status is derived from stock: it becomes `OUT_OF_STOCK` when `stock_qty` is zero, and it returns from `OUT_OF_STOCK` to `AVAILABLE` when a restock lifts `stock_qty` above zero; an update that explicitly supplies a `status` is applied as given and suppresses this derivation. Manager updates increment the prize's `version`. Prizes are readable by everyone.

A redemption is created by an attendant or the owning member, who supply the `card_id`, the `prize_item_id`, the `quantity` (strictly positive), and the `expected_card_version` for the concurrency check. Creating a redemption places it in `RESERVED`. Several conditions must hold: the card must be `ACTIVE`; the prize must be `AVAILABLE`, else `ERR_PRIZE_UNAVAILABLE` (409); the prize's available units — its `stock_qty` minus its `reserved_qty` — must be at least the requested `quantity`, else `ERR_INSUFFICIENT_STOCK` (409); the card's `ticket_points_balance` must be at least the points hold, else `ERR_INSUFFICIENT_POINTS` (402); and the card version must match, else `ERR_STALE_VERSION` (412). The `points_hold` is valued at reserve time as the prize's `points_price` at that moment multiplied by the `quantity`. On reservation the card's `ticket_points_balance` decreases by the `points_hold`, a `POINTS_HOLD` ledger entry is appended with a points delta equal to the negative of the hold, the prize's `reserved_qty` increases by the `quantity`, and the card's `version` increments.

From `RESERVED` a redemption forks two ways, both restricted to an attendant. Fulfilling it moves `RESERVED → FULFILLED` and settles at the *current* price: `points_settled` is the prize's `points_price` at fulfill time multiplied by the `quantity`. Because the prize may have been repriced since the reservation, the settlement can differ from the hold. The card is charged the settlement delta — the settled amount minus the original hold — so the card's `ticket_points_balance` decreases by that difference (a negative difference refunds points). The card must be able to cover a positive delta: its `ticket_points_balance` must be at least the settlement delta where that delta is positive (and the requirement is zero when the delta is negative), else `ERR_INSUFFICIENT_POINTS` (402). A `POINTS_SETTLE` ledger entry is appended with a points delta equal to the negative of the settlement delta, the prize's `reserved_qty` decreases by the `quantity`, and its `stock_qty` also decreases by the `quantity`, retiring the physical units. Cancelling instead moves `RESERVED → CANCELLED` and unwinds the reservation cleanly: the full `points_hold` is added back to the card's `ticket_points_balance`, a `POINTS_REFUND` ledger entry is appended with a positive points delta equal to the hold, and the prize's `reserved_qty` decreases by the `quantity` while its `stock_qty` is left unchanged. `points_settled` stays null until a redemption is fulfilled. Fulfilling or cancelling anything not currently `RESERVED` is rejected with `ERR_INVALID_REDEMPTION_STATE` (409); both `FULFILLED` and `CANCELLED` are terminal. Redemptions are readable and listable, filterable by card, prize, and status.

### 3.5. Party Packages, Rooms, and Booking Confirmation

A manager defines a `PartyPackage` — a `name`, a `base_price_cents` (strictly positive), the number of `included_guests` covered before a per-extra-guest surcharge (strictly positive), the number of `included_hours` covered before overage (strictly positive), the `included_chip_cents` of promotional chips loaded onto each provisioned guest card at confirm time (zero or more), a marketing `tier` label of `BRONZE`, `SILVER`, or `GOLD`, and the bundled food-and-beverage combo described by `combo_name` and its retail `combo_value_cents` (zero or more). A manager also configures each `Room` with a `name`, a physical `capacity` (strictly positive), and an `hourly_rate_cents` charged for each hour beyond the package's included hours (zero or more). A room is `AVAILABLE` on creation and may be set to `MAINTENANCE` by a manager update that increments its `version`.

A coordinator opens a `PartyBooking` in `DRAFT` by supplying the `room_id`, the `package_id`, the `host_member_id`, the planned window `start_at` and `end_at` (with `end_at` strictly after `start_at`), and the planned `guest_count` (strictly positive). Its `checked_in_at`, `completed_at`, `provisional_total_cents`, `final_total_cents`, and `actual_guest_count` all begin null. Bookings are readable and listable, filterable by room, package, host, and status.

Confirming a `DRAFT` booking (moving `DRAFT → CONFIRMED`) is the pivotal step, and it runs three gates. First, the booking's half-open window from `start_at` up to but not including `end_at` must not overlap the window of any other non-`CANCELLED` booking on the same room; two windows that merely touch at the boundary, where one ends exactly as the other begins, do not overlap and are allowed. An overlap is rejected with `ERR_ROOM_TIME_CONFLICT` (409). Second, the `guest_count` must not exceed the room's `capacity`, else `ERR_GUEST_COUNT_EXCEEDS_ROOM` (409). Third, the venue as a whole must not be oversubscribed: summing the `guest_count` of every `CONFIRMED` or `CHECKED_IN` booking whose window overlaps this window, plus this booking's own `guest_count`, must not exceed the maximum venue occupancy of 200 guests, else `ERR_VENUE_CAPACITY_EXCEEDED` (409).

On a successful confirm the provisional charge is computed and written to `provisional_total_cents` (the arithmetic is given in §3.7), and a three-hop cascade fires. For each of the `guest_count` guests, the system creates a `Wristband` in `ISSUED` status linked to this booking. Each new wristband in turn provisions a fresh `GameCard` in `ACTIVE` status and links the wristband's `card_id` to it. Each provisioned card is then granted the package's `included_chip_cents` as promotional chips: a `BONUS_GRANT` ledger entry is appended with a bonus delta equal to `included_chip_cents`, and the card's `bonus_chip_balance_cents` grows by that amount. The booking's `version` increments. Confirming a booking that is not `DRAFT` is rejected with `ERR_INVALID_BOOKING_STATE` (409).

A coordinator may revert a `CONFIRMED` booking (moving `CONFIRMED → DRAFT`), which must undo the confirm cascade exactly. The room's window reservation is released, every wristband of the booking is set to `VOID`, each of those voided wristbands' linked cards has the granted promotional chips clawed back — a `BONUS_CLAWBACK` ledger entry with a bonus delta equal to the negative of `included_chip_cents` is appended and the card's `bonus_chip_balance_cents` decreases by that amount — and the booking's `provisional_total_cents` is reset to null. The booking's `version` increments.

### 3.6. Party Check-In, Extra Wristbands, Completion, and Cancellation

A cashier checks in a `CONFIRMED` booking (moving `CONFIRMED → CHECKED_IN`). The room must be `AVAILABLE` and not in `MAINTENANCE`, else `ERR_ROOM_UNAVAILABLE` (409), and the logical clock must fall within the booking window — at or after `start_at` and strictly before `end_at` — else `ERR_OUTSIDE_BOOKING_WINDOW` (409). On check-in the booking's `checked_in_at` is set to the current clock instant, every wristband of the booking moves `ISSUED → ACTIVE`, and the booking's `version` increments.

During a `CONFIRMED` or `CHECKED_IN` booking a cashier may issue an extra wristband, optionally supplying a `card_id` to link and always supplying the `expected_booking_version` for the concurrency check of §2.8. The booking must be in `CONFIRMED` or `CHECKED_IN`, the supplied version must match the booking's current `version` (else `ERR_STALE_VERSION`, 412), and the count of the booking's wristbands currently in `ISSUED` or `ACTIVE` must be strictly less than the room's `capacity`, else the issue is rejected with `ERR_GUEST_COUNT_EXCEEDS_ROOM` (409). A server-minted `band_code` is assigned to the new `ISSUED` wristband, whose `booking_id` points back to this booking, and the booking's `version` increments. A cashier may also return an `ACTIVE` wristband (moving `ACTIVE → RETURNED`), which decommissions the band while leaving its linked card untouched and increments the wristband's `version`; returning a wristband that is not `ACTIVE` is rejected with `ERR_INVALID_WRISTBAND_STATE` (409). Wristbands are readable and listable, filterable by `booking_id`, by `card_id`, and by status.

A coordinator completes a `CHECKED_IN` booking (moving `CHECKED_IN → COMPLETED`). Completion sets `completed_at` to the current clock instant, computes `actual_guest_count` as the count of this booking's wristbands in `ISSUED` or `ACTIVE`, and computes the final charge into `final_total_cents` (§3.7). The booking's `version` increments.

A coordinator may cancel a booking (moving it to the terminal `CANCELLED`) from `DRAFT`, `CONFIRMED`, or `CHECKED_IN`. Cancelling a `DRAFT` booking simply closes it, as no wristbands exist yet. Cancelling a `CONFIRMED` or `CHECKED_IN` booking runs the same compensation as a revert: the room window reservation is released, every wristband of the booking is set to `VOID`, and each voided wristband's linked card has its promotional grant clawed back through a `BONUS_CLAWBACK` ledger entry with a bonus delta equal to the negative of `included_chip_cents`, decreasing that card's `bonus_chip_balance_cents`. The booking's `version` increments. A cancel attempted from any other state is `ERR_INVALID_BOOKING_STATE` (409). Booking terminal states are `COMPLETED` and `CANCELLED`.

### 3.7. Party Charge Arithmetic

The party charge is computed twice for the same booking, once provisionally at confirm and once finally at complete, using the same shape but different inputs. Both draw on the booking, its package, and its room, and both are integer-cent amounts.

At confirm, the provisional total is computed from the planned figures. The planned duration is the window from `start_at` to `end_at`, expressed as a whole number of hours with any partial hour rounded up. The number of extra guests is the planned `guest_count` minus the package's `included_guests`, floored at zero so a small party never goes negative. The number of overage hours is the planned hours minus the package's `included_hours`, likewise floored at zero. The provisional total is the package's `base_price_cents`, plus the extra guests multiplied by the per-extra-guest surcharge of 1,500 cents ($15.00) each, plus the overage hours multiplied by the room's `hourly_rate_cents`. The result is written to `provisional_total_cents`.

At complete, the final total is computed the same way but from the actuals. The actual duration is the window from `checked_in_at` to `completed_at`, again as whole hours rounded up. The extra guests are the `actual_guest_count` minus the package's `included_guests`, floored at zero. The overage hours are the actual hours minus the package's `included_hours`, floored at zero. The final total is the `base_price_cents`, plus the extra guests times 1,500 cents each, plus the overage hours times the room's `hourly_rate_cents`, written to `final_total_cents`. The final total diverges from the provisional whenever the actuals differ from the plan — a different head count of wristbands or a shorter or longer occupied window.

### 3.8. Daily Reconciliation

At the close of trading a manager opens a `DailyReconciliation` for a `business_day` (a `YYYY-MM-DD` UTC date, unique across reconciliations; a duplicate is rejected with `ERR_RECON_DUPLICATE_DAY`, 409). Opening it in `OPEN` snapshots two expected figures. The `expected_chip_liability_cents` is the sum, over every game card whose status is `ACTIVE` or `FROZEN`, of that card's `chip_balance_cents` plus its `bonus_chip_balance_cents`; `CLOSED` cards are excluded. The `expected_prize_units` is the sum, over every prize whose status is `AVAILABLE` or `OUT_OF_STOCK`, of its `stock_qty`; `DISCONTINUED` prizes are excluded. The `counted_chip_liability_cents`, `counted_prize_units`, `variance_chip_cents`, and `variance_prize_units` all begin null.

The manager then submits the physical counts, supplying `counted_chip_liability_cents` and `counted_prize_units` (each zero or more). This is permitted only while the reconciliation is `OPEN`, else `ERR_INVALID_RECONCILIATION_STATE` (409). The system computes `variance_chip_cents` as the counted chip liability minus the expected chip liability, and `variance_prize_units` as the counted prize units minus the expected prize units. The reconciliation then branches on the result: if both variances are exactly zero it moves `OPEN → RECONCILED`; if either variance is non-zero it moves `OPEN → DISCREPANCY`. Both `RECONCILED` and `DISCREPANCY` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Reads return `200 OK`. Request bodies, computed responses, and side effects for each endpoint are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | Manager |
| POST | `/attractions` | Create an attraction | Manager |
| PATCH | `/attractions/{id}` | Update attraction status/pricing | Manager |
| GET | `/attractions/{id}` | Read an attraction | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/prize-items` | Create a redemption prize | Manager |
| PATCH | `/prize-items/{id}` | Reprice, restock, or discontinue a prize | Manager |
| GET | `/prize-items/{id}` | Read a prize item | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/party-packages` | Create a party package | Manager |
| POST | `/rooms` | Create a party room | Manager |
| PATCH | `/rooms/{id}` | Set room status | Manager |
| GET | `/rooms/{id}` | Read a room | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/members` | Register a member | Cashier, Manager |
| GET | `/members/{id}` | Read a member | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/game-cards` | Issue a new game card | Cashier |
| GET | `/game-cards/{id}` | Read a game card | Member, Cashier, Attendant, Coordinator, Manager |
| GET | `/game-cards` | List game cards | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/game-cards/{id}/activate` | Activate an INACTIVE card | Cashier |
| POST | `/game-cards/{id}/reload` | Reload stored value; grant tier bonus | Cashier |
| POST | `/game-cards/{id}/freeze` | Freeze an ACTIVE card | Manager |
| POST | `/game-cards/{id}/close` | Close an ACTIVE or FROZEN card | Cashier, Manager |
| GET | `/game-cards/{id}/ledger` | List a card's ledger entries | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/game-plays` | Play an attraction | Attendant, Member |
| GET | `/game-plays/{id}` | Read a game play | Member, Cashier, Attendant, Coordinator, Manager |
| GET | `/game-plays` | List game plays | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/redemptions` | Reserve a prize redemption | Attendant, Member |
| GET | `/redemptions/{id}` | Read a redemption | Member, Cashier, Attendant, Coordinator, Manager |
| GET | `/redemptions` | List redemptions | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/redemptions/{id}/fulfill` | Fulfill a RESERVED redemption | Attendant |
| POST | `/redemptions/{id}/cancel` | Cancel a RESERVED redemption | Attendant |
| POST | `/party-bookings` | Create a party booking | Coordinator |
| GET | `/party-bookings/{id}` | Read a party booking | Member, Cashier, Attendant, Coordinator, Manager |
| GET | `/party-bookings` | List party bookings | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/party-bookings/{id}/confirm` | Confirm a DRAFT booking | Coordinator |
| POST | `/party-bookings/{id}/revert-to-draft` | Revert a CONFIRMED booking to DRAFT | Coordinator |
| POST | `/party-bookings/{id}/check-in` | Check in a CONFIRMED booking | Cashier |
| POST | `/party-bookings/{id}/complete` | Complete a CHECKED_IN booking | Coordinator |
| POST | `/party-bookings/{id}/cancel` | Cancel a booking | Coordinator |
| POST | `/party-bookings/{id}/wristbands` | Issue an extra wristband | Cashier |
| GET | `/wristbands/{id}` | Read a wristband | Member, Cashier, Attendant, Coordinator, Manager |
| GET | `/wristbands` | List wristbands | Member, Cashier, Attendant, Coordinator, Manager |
| POST | `/wristbands/{id}/return` | Return an ACTIVE wristband | Cashier |
| POST | `/daily-reconciliations` | Open a reconciliation for a business day | Manager |
| GET | `/daily-reconciliations/{id}` | Read a reconciliation | Manager |
| POST | `/daily-reconciliations/{id}/count` | Submit counted figures | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CARD_NOT_FOUND` | 404 |
| `ERR_ATTRACTION_NOT_FOUND` | 404 |
| `ERR_PRIZE_NOT_FOUND` | 404 |
| `ERR_REDEMPTION_NOT_FOUND` | 404 |
| `ERR_GAMEPLAY_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_WRISTBAND_NOT_FOUND` | 404 |
| `ERR_RECONCILIATION_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_CARD_NOT_ACTIVE` | 409 |
| `ERR_INVALID_CARD_STATE` | 409 |
| `ERR_CARD_FROZEN` | 409 |
| `ERR_INVALID_REDEMPTION_STATE` | 409 |
| `ERR_INVALID_BOOKING_STATE` | 409 |
| `ERR_INVALID_WRISTBAND_STATE` | 409 |
| `ERR_INVALID_RECONCILIATION_STATE` | 409 |
| `ERR_ATTRACTION_NOT_OPEN` | 409 |
| `ERR_PRIZE_UNAVAILABLE` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_OUTSIDE_BOOKING_WINDOW` | 409 |
| `ERR_ROOM_TIME_CONFLICT` | 409 |
| `ERR_GUEST_COUNT_EXCEEDS_ROOM` | 409 |
| `ERR_VENUE_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_INSUFFICIENT_CHIP_BALANCE` | 402 |
| `ERR_INSUFFICIENT_POINTS` | 402 |
| `ERR_CARD_BALANCE_CAP_EXCEEDED` | 422 |
| `ERR_RECON_DUPLICATE_DAY` | 409 |
