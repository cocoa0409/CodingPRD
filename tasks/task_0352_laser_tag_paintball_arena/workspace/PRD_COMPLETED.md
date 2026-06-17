# Laser Tag & Paintball Arena API — Product Requirements Document

## 1. Introduction

This document specifies the Laser Tag & Paintball Arena API, a back-office system that runs the operational core of a multi-field laser tag and paintball venue. A single arena juggles several intertwined concerns at once: it sells timed sessions on physical fields that each hold a limited number of players; it rents out a finite pool of markers and vests against refundable deposits; it meters ammunition, CO2, and miscellaneous add-ons; it enforces waiver and age-of-consent rules before anyone steps onto a field; and it staffs referees for the games that need supervision. On top of day-to-day intake the arena also runs competitive leagues whose rounds advance cyclically and whose standings are scored from the results of real sessions.

The product exists to make those concerns consistent with one another. A booking cannot quietly double-book a field, a marker cannot be handed to two parties for overlapping windows, a deposit cannot drift away from the cash actually held, and a minor cannot be checked in without a guardian-signed waiver. Because so much of the logic is time-sensitive, the arena keeps a deterministic clock that the test harness drives explicitly; every lead-time check, every walk-in "now" window, and every age calculation reads from that clock rather than wall-clock time. The sections that follow define the global contract first (authentication, envelope, pagination, and the cross-cutting consistency rules), then the business workflows in narrative form, and finally the endpoint and error reference tables.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` declares the capacity in which they are acting. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `ArenaManager`, `FrontDesk`, `FieldMarshal`, and `LeagueDirector`. These are peer roles — each owns a distinct slice of the resource surface. `ArenaManager` owns arena configuration: arenas, fields, packages, the equipment pool, equipment restoration, and the clock. `FrontDesk` owns the counter surface for reservations and walk-ins: bookings, waivers, rentals, and add-on orders. `FieldMarshal` owns on-field operations: check-in, completion, no-show, equipment return, and referee assignment. `LeagueDirector` owns the league and event lifecycle: leagues, their rounds, and match scheduling and scoring. All four roles may read (issue `GET` requests against) every resource collection.

Role identity in this system is operational rather than entity-backed. For all four roles — `ArenaManager`, `FrontDesk`, `FieldMarshal`, and `LeagueDirector` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any resource's `id`; there is no per-record ownership check that ties a resource back to the operator who created it. Authorization is therefore decided entirely by `X-User-Role` against the operation, not by matching `X-User-ID` to a stored foreign key.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not go below 1, and may not exceed 100 — a supplied `limit` outside that range is silently clamped into it (values below 1 become 1, values above 100 become 100) rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0. A non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses always carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. Where a list endpoint accepts a filter (for example a `arena_id`, `field_id`, `package_id`, `booking_id`, `equipment_unit_id`, `referee_id`, or `league_id` query parameter), pagination is applied after the filter narrows the collection.

### 2.4. Common Resource Properties

Every entity in this system carries a system-managed `id` formatted as a UUID with no type prefix, plus a `created_at` timestamp rendered as ISO 8601 UTC with three fractional digits. Every entity here also tracks modification: each carries an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at its creation value and increments by one on every mutation. There are no creation-only resources in this domain; all of them participate in the `updated_at` / `version` discipline.

The `version` field is load-bearing in two places — the optimistic concurrency checks of §2.6 — but it is bumped by *every* mutation, not only those two. A computed-field reconciliation (for example, recomputing a field's reserved headcount or an arena's equipment counts) is itself a mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`. Booleans and computed integers such as `minors_present`, `referee_required`, `reserved_headcount`, `marker_available_count`, `vest_available_count`, `deposit_held_cents`, `deposit_refunded_cents`, and `deposit_forfeited_cents` are server-owned; clients never write them directly, and any client-supplied value for them is ignored.

### 2.5. Nested Resource Retrieval and Referential Existence

The topology of this API is flat: every entity is its own top-level collection, and resources are linked to one another through foreign-key fields carried in request bodies rather than through deeply nested URL paths. For discovery, an arena exposes read-only sub-collections of the resources scoped to it, but the canonical write path for, say, a booking is the bookings collection with an `arena_id` and `field_id` in the body.

Whenever a request carries resource identifiers — a path id such as a booking id, or a foreign key such as `arena_id`, `field_id`, `package_id`, `booking_id`, `equipment_unit_id`, `referee_id`, `league_id`, or `match`/league-match id in the body — those identifiers are validated for existence in left-to-right order, arena first and then the more specific references. The first identifier that does not resolve causes the request to be rejected with the matching 404 error: `ERR_ARENA_NOT_FOUND`, `ERR_FIELD_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_RENTAL_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_REFEREE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_LEAGUE_NOT_FOUND`, or `ERR_MATCH_NOT_FOUND`. Existence is checked before any state or business rule, so a stale-state error is never returned for a resource that does not exist.

Once existence is satisfied, payload shape is checked: a write request that omits a required input field, supplies a field of the wrong type, or supplies an enum value outside the declared domain (for example a `game_mode`, `unit_type`, `booking_type`, or `condition_grade` not among its allowed strings) is rejected with `ERR_VALIDATION` (HTTP 400). This shape check sits after the 404 existence pass and before any state-transition or business rule.

### 2.6. Optimistic Concurrency Control on Field and League

Two operations in this system mutate a parent whose state a client may have observed earlier and acted on stale: confirming a booking against a field, and advancing a league to its next round. Both are guarded by optimistic concurrency control, and both require the client to echo back the version it last saw.

Confirming a booking is a write against the booking's field. The confirm request must carry `expected_field_version`, and that value must equal the target field's current `version`. Because confirming a competing booking on the same field bumps that field's `version` (its slot ledger and reserved headcount changed), a confirm that still carries the older `expected_field_version` is observing stale field state and is rejected with `ERR_STALE_FIELD_VERSION` (HTTP 412). Locking a league round also carries `expected_league_version` and is rejected with `ERR_STALE_LEAGUE_VERSION` (HTTP 412) on mismatch. Advancing a league round is a write against the league: the request must carry `expected_league_version` matching the league's current `version`. Because locking the round (a legitimate prior write) increments `League.version`, an advance-round request still carrying the pre-lock `expected_league_version` is observing stale league state and is rejected with `ERR_STALE_LEAGUE_VERSION` (HTTP 412). These three operations — confirm, lock-round, and advance-round — are the only endpoints that take a version field; no other endpoint accepts `expected_field_version` or `expected_league_version`, and none performs an OCC check.

### 2.7. The Equipment Pool and Deposit Ledger

Each arena owns a conserved pool of physical equipment and a deposit ledger that must always reflect the cash actually held against customers. When an arena is created the operator declares `marker_pool_total` and `vest_pool_total` as the count of markers and vests the arena intends to provision; both must be zero or greater. The live availability counts `marker_available_count` and `vest_available_count` are computed: they track how many marker and vest units currently sit in `AVAILABLE` status, and they are reconciled on every rental reserve and every release or return. Provisioning a new unit raises the relevant available count; reserving a unit lowers it; releasing, returning undamaged, or restoring from maintenance raises it again.

The deposit ledger lives on the arena as three computed integer-cent figures. `deposit_held_cents` is the sum of `deposit_hold_cents` across every rental currently in `HELD` or `CHECKED_OUT` state — the money the arena is presently holding. `deposit_refunded_cents` accumulates every cent returned to customers across all settled rentals, and `deposit_forfeited_cents` accumulates every cent retained for damage or loss. These three are conserved quantities: a deposit that enters `deposit_held_cents` at reserve time later leaves it and lands in exactly one of `deposit_refunded_cents` or `deposit_forfeited_cents` (or, when a hold is released before checkout, simply leaves the held total with nothing forfeited). Every reserve, release, return, cancellation, and no-show that touches a deposit reconciles all of these figures atomically within the triggering request, bumping the arena's `version`.

### 2.8. Monetary Values, Points, and Rounding

All money in this system is carried as integer cents — there are no fractional cents and no floating-point currency. Most calculations are therefore exact. Two places require rounding, and in both the method is round half up (ties round away from zero, to the nearest whole cent). The first is the package discount applied to metered ammunition at settlement; the second is the per-line sales tax on the final booking invoice. League standings are scored in whole integer points with no rounding at all. The precise order in which rounding interacts with the surrounding arithmetic is pinned in §3 where each calculation is described, because the order changes the answer by a cent or two and a naive "tax the sum once" or "discount after subtracting" reading is explicitly wrong.

### 2.9. The Deterministic Arena Clock

Time in this system never comes from the wall clock. Each arena carries `current_utc`, a deterministic clock rendered as ISO 8601 UTC with three fractional digits. A dedicated administrative capability sets it to an explicit instant supplied in the request as `to_iso8601`, writing that value onto the arena's `current_utc`. Until it is first set, a freshly created arena's clock sits at the epoch. This clock is the sole reference for three time-sensitive behaviors: the "now" anchor that a walk-in booking must start at, the lead-time floor that a reservation's start must clear, and the age computation that decides whether a participant is a minor. Every comparison described in §3 that mentions "now" or the arena's current time reads `current_utc`.

### 2.10. Cascading Consistency and Reverts

Many operations in this system mutate more than one resource. Cancelling or marking a booking as no-show, for example, fans out across rentals, equipment units, the deposit ledger, add-on orders, and referee staffing in a single atomic request. The governing principle is that derived and dependent state is never left stale: when a booking leaves a live state, its held equipment returns to the pool, its held deposits leave `deposit_held_cents`, its outstanding add-on quotes are voided, its referee is freed, and the field's `reserved_headcount` is recomputed. §3 spells out each cascade hop by hop; the rule to remember globally is that the system performs every dependent transition itself, without requiring the client to issue a separate request against each child, and each touched resource independently refreshes its `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Arena, Fields, Packages, and Equipment

An `ArenaManager` stands up the venue. Creating an arena supplies a `name`, the intended `marker_pool_total` and `vest_pool_total`, and optionally a `timezone` (an IANA zone used only for display; every stored timestamp is UTC regardless; when omitted, `timezone` defaults to `"UTC"`). A new arena opens in `OPEN` status with its equipment available counts at zero — no units exist yet — and its deposit ledger at zero. The manager can later close the arena, moving `status` to `CLOSED`; a `CLOSED` arena blocks new bookings and rentals, surfacing as `ERR_ARENA_CLOSED`. The manager also owns the clock: a test-driving capability sets the arena's `current_utc` to the supplied `to_iso8601` instant.

A **Field** is one playing surface under an arena. The manager creates it with an `arena_id`, a `name`, a `game_mode` of either `LASER_TAG` or `PAINTBALL`, a `capacity_max` of at least one, and an optional `turnaround_minutes` buffer (defaulting to 0, never negative). The `game_mode` constrains downstream rules — paintball sessions always require a referee and only certified referees may marshal them. A field opens in `ACTIVE` status with `reserved_headcount` at zero. Closing a field moves its `status` to `CLOSED`, which rejects new slot holds with `ERR_FIELD_CLOSED`. The `reserved_headcount` is computed: it is the sum of `party_size` over all bookings on the field that currently hold a live slot — those in `HELD`, `CONFIRMED`, or `CHECKED_IN` whose window overlaps the current time — and it is recomputed on every booking transition.

A **PartyPackage** is a pricing template for group bookings, created with an `arena_id`, a `name`, an `included_players` headcount (at least one), an `extra_player_fee_cents` charged per player above that headcount (zero or greater), a flat `base_fee_cents` covering the included players (zero or greater), and optionally `included_ammo_balls` (paintballs or laser credits bundled before metered pricing kicks in, defaulting to 0), a `discount_pct`, and an `active` flag (defaulting to true). The `discount_pct` is a fraction that must be at least 0 and strictly less than 1; it discounts the metered add-on cost at settlement. When `active` is false the package cannot be attached to new bookings.

Equipment is provisioned one unit at a time. An **EquipmentUnit** is created with an `arena_id`, a `unit_type` of either `MARKER` or `VEST`, an `asset_tag` (a human label unique within the arena and unit type), a `deposit_cents` amount required to check it out (zero or greater), and an optional `condition_grade` of `A`, `B`, or `C` (defaulting to `A`). A unit starts `AVAILABLE`, and provisioning it raises the arena's available count for its type. Grade `C` units may never be reserved. Over a unit's life its `status` moves among `AVAILABLE`, `RESERVED`, `CHECKED_OUT`, and `MAINTENANCE` as rentals drive it.

### 3.2. Taking a Booking: Reservations, Walk-Ins, and the Slot Window

A `FrontDesk` operator opens a **Booking** by naming the `arena_id`, the `field_id`, a `booking_type`, a `party_size`, a `window_start`, a `window_end`, and optionally a `package_id`. The booking is created in `HELD` status, the field's `reserved_headcount` is recomputed, and the booking's `minors_present` and `referee_required` flags are computed from its (initially empty) waiver set and its field's game mode. A booking with no `package_id` is an "a la carte" booking; one with a `package_id` draws its field fee from that package.

The session occupies a **half-open time interval** `[window_start, window_end)` — the start instant is inclusive, the end instant is exclusive. Window sanity is enforced first: `window_end` must be strictly later than `window_start`, and a non-positive-length window is rejected with `ERR_INVALID_WINDOW`. The `booking_type` then governs how the window relates to the clock. A `WALK_IN` must begin exactly at the arena's current time — its `window_start` must equal the arena's `current_utc` at create time. A `RESERVATION` is a future booking whose `window_start` must be at least sixty minutes after the arena's current time; the boundary is inclusive, so a `window_start` exactly sixty minutes after `current_utc` satisfies the rule. A `WALK_IN` whose start is not the current instant, or a `RESERVATION` that starts sooner than the sixty-minute floor, is rejected with `ERR_LEAD_TIME_VIOLATION`.

The party must fit the field. A booking's `party_size` may not exceed the field's `capacity_max`, or the create is rejected with `ERR_CAPACITY_EXCEEDED`. If a `package_id` is supplied, the package must be active and must belong to the same arena; an inactive or cross-arena package is rejected with `ERR_PACKAGE_INACTIVE`. Finally the field's calendar is checked: a new `HELD` or `CONFIRMED` booking whose window, extended by the field's `turnaround_minutes` buffer, collides with an existing live booking's window on the same field is rejected with `ERR_FIELD_SLOT_CONFLICT`. The buffer means two sessions on one field must be separated by at least `turnaround_minutes` of clear time between the end of one and the start of the next; the slot-conflict check is applied both at booking creation and again at confirmation. This ordering at booking creation is authoritative when more than one business rule is violated at once: the checks fire in exactly the narrated sequence — window sanity, then lead-time, then capacity, then package-active, then field-slot conflict last — so a create that violates both the capacity limit and the field-slot calendar is rejected with `ERR_CAPACITY_EXCEEDED` (capacity is checked before the slot conflict), not `ERR_FIELD_SLOT_CONFLICT`. The §5 catalogue's listing order does not override this booking-create sequence.

### 3.3. Confirming, Checking In, and the Field Fee

Confirmation is the `FrontDesk` action that turns a `HELD` booking into a `CONFIRMED` one and pins its price. Confirming requires the booking to be `HELD`, the field to be `ACTIVE`, and the arena to be `OPEN`; a booking in any other state is rejected with `ERR_BOOKING_INVALID_STATE` (the booking-state legality is checked first, before the field and arena status). A confirm against a booking whose field is not `ACTIVE` is rejected with `ERR_FIELD_CLOSED`, and a confirm whose arena is not `OPEN` is rejected with `ERR_ARENA_CLOSED`. As described in §2.6, the confirm request carries `expected_field_version` and is rejected with `ERR_STALE_FIELD_VERSION` if it does not match the field's live `version`. On success the booking transitions `HELD → CONFIRMED`, the field fee is computed and pinned onto the booking's `field_fee_cents`, the field's `version` is incremented by one, and `reserved_headcount` is recomputed.

The field fee depends on the package, and the evaluation order is pinned to avoid any circular reading. If the booking has no `package_id`, `field_fee_cents` is zero. Otherwise, the number of extra players is the booking's `party_size` minus the package's `included_players`, floored at zero so a party that fits within the included headcount contributes no extras; the `field_fee_cents` is then the package's `base_fee_cents` plus that extra-player count multiplied by the package's `extra_player_fee_cents`.

Check-in is the `FieldMarshal` action that turns a `CONFIRMED` booking into a `CHECKED_IN` one. It requires the booking to be `CONFIRMED`, the arena's current time to fall within the half-open window `[window_start, window_end)` (at or after the start and strictly before the end), and a supplied `checked_in_count` between 1 and the booking's `party_size` inclusive — a count below 1 or above `party_size` is rejected with `ERR_CAPACITY_EXCEEDED`. The current-time-within-window requirement is treated as a state precondition: a check-in whose current time is outside `[window_start, window_end)` is rejected with `ERR_BOOKING_INVALID_STATE`, and this window check is applied after the two §3.6 safety gates and after the `checked_in_count` capacity check. Two safety gates also apply here and are detailed in §3.6: every minor's waiver on the booking must be signed, and if the booking requires a referee one must be assigned. On success the booking's `checked_in_count` is set from the request, the booking transitions `CONFIRMED → CHECKED_IN`, each `HELD` rental for the booking is checked out (its equipment unit moving to `CHECKED_OUT`), and `reserved_headcount` is recomputed.

### 3.4. Equipment Rental and the Deposit Lifecycle

A **Rental** binds one booking to one equipment unit and carries that unit's deposit through a four-state lifecycle. A `FrontDesk` operator reserves a unit by supplying an `arena_id`, a `booking_id`, and an `equipment_unit_id`. To reserve, the unit must currently be `AVAILABLE` and its `condition_grade` must be `A` or `B`; a unit that is not available, or a grade-`C` unit, is rejected with `ERR_EQUIPMENT_UNAVAILABLE`. The system also guards against handing one physical unit to two overlapping sessions: reserving a unit that already has a live rental whose booking window overlaps the new booking's window is rejected with `ERR_EQUIPMENT_TIME_CONFLICT`. This equipment overlap is checked on closed intervals with no turnaround buffer — unlike the field-slot check, two rentals of the same unit collide whenever their windows touch at all.

On a successful reserve the rental is created in `HELD` status; its `deposit_hold_cents` is snapshotted from the unit's `deposit_cents` at that moment; the unit moves `AVAILABLE → RESERVED`; the arena's `deposit_held_cents` rises by the held amount; and the arena's available count for that unit type drops by one. When the parent booking is checked in, each `HELD` rental for it moves `HELD → CHECKED_OUT` and its unit moves `RESERVED → CHECKED_OUT`.

Returning a checked-out rental is a `FieldMarshal` action that settles the deposit. The return supplies an optional `damage_fee_cents` (defaulting to 0, never negative), and that fee may not exceed the rental's `deposit_hold_cents` — a fee larger than the held deposit is rejected with `ERR_DAMAGE_FEE_EXCEEDS_DEPOSIT`. Settlement is a waterfall: the forfeited amount, `deposit_forfeit_cents`, is the smaller of the held deposit and the damage fee (damage is drawn from the deposit first); the refunded amount, `deposit_refund_cents`, is the held deposit minus that forfeit, which is never negative. The two always sum back exactly to `deposit_hold_cents`. On return the rental moves `CHECKED_OUT → RETURNED`; the unit returns to `AVAILABLE` when `damage_fee_cents` is zero, but moves to `MAINTENANCE` when any damage fee was charged (and its `condition_grade` is downgraded one notch on that path, `A` to `B`, `B` to `C`, with `C` staying `C`); the arena's `deposit_held_cents` falls by the held amount, its `deposit_refunded_cents` rises by the refund, and its `deposit_forfeited_cents` rises by the forfeit, with the available count reconciled.

A `HELD` rental that has not yet been checked out can instead be released. A `FrontDesk` operator may release it directly, and the booking-cancellation and no-show cascades release it automatically. Releasing a `HELD` rental moves it to `RELEASED`, returns its unit to `AVAILABLE`, lowers the arena's `deposit_held_cents` by the held amount, and reconciles the available count; no money is forfeited on a release. A unit that has gone to `MAINTENANCE` is brought back by an `ArenaManager` restoring it, which moves the unit `MAINTENANCE → AVAILABLE` and raises the available count; restoring a unit that is not in `MAINTENANCE` is rejected with `ERR_EQUIPMENT_INVALID_STATE`. A rental transition attempted from a state that does not allow it is rejected with `ERR_RENTAL_INVALID_STATE`.

### 3.5. Add-On Orders: Quote Now, Settle at Completion

Ammunition, CO2, and sundries are sold through **AddOnOrders** attached to a booking. A `FrontDesk` operator creates one with an `arena_id`, a `booking_id`, and any of `ammo_balls` (metered paintballs or laser credits, default 0), `co2_tanks` (default 0), and `misc_cents` (a flat charge for snacks or photos, default 0); all three are zero or greater. The order is created in `QUOTED` status and a provisional price is computed immediately into `quote_total_cents`.

The ammunition price is tiered on the ball count. The first 500 balls are billed at 10 cents each; the next 1500 balls (those from the 501st through the 2000th) at 8 cents each; and every ball beyond 2000 at 6 cents each. Concretely, the tier-one quantity is the ball count capped at 500; the tier-two quantity is whatever remains after removing the first 500, capped at 1500; and the tier-three quantity is whatever remains beyond 2000. The ammunition cost is the tier-one quantity times 10 cents plus the tier-two quantity times 8 cents plus the tier-three quantity times 6 cents. Each CO2 tank adds 700 cents. The miscellaneous charge is added as-is.

The **quote variant** computed at order creation applies no package context: it bills every ball ordered through the tier schedule, adds the CO2 and miscellaneous charges, and stores that exact integer-cent sum as `quote_total_cents`. The **settled variant** is computed later, when the parent booking is completed, and it applies the package. First, the package's `included_ammo_balls` allowance (zero when the booking has no package) is consumed off the top: the billable ball count is the ordered `ammo_balls` minus the included allowance, floored at zero. The ammunition cost is recomputed on that reduced billable count through the same tier schedule, the CO2 and miscellaneous charges are added unchanged, and that gross is the starting point. Then a discount is computed as the package's `discount_pct` times the metered ammunition cost only (the discount never touches CO2 or miscellaneous charges), rounded half up to the nearest cent. The discount is subtracted from the gross to yield `settled_total_cents`. The rounding order is pinned: round the discount term to a whole cent first, then subtract — not the other way around.

### 3.6. Waivers, Age, and the Referee Safety Gates

Every participant who needs a waiver gets a **WaiverProfile** on the booking. A `FrontDesk` operator creates one with an `arena_id`, a `booking_id`, a `participant_name`, a `date_of_birth` (ISO 8601 UTC), and optionally a `guardian_name`. At creation the profile's `age_years` is computed as the full years between `date_of_birth` and the arena's `current_utc`, and `is_minor` is set true when `age_years` is below 18. The profile starts in `DRAFT` status.

Signing a waiver moves it `DRAFT → SIGNED` and is a `FrontDesk` action. Signing requires the profile to be `DRAFT` and the parent booking to be in `HELD` or `CONFIRMED`. The minor-guardian rule bites here: if the profile is for a minor, it must carry a `guardian_name`, and an attempt to sign a minor's waiver that has no guardian on file is rejected with `ERR_MINOR_WAIVER_REQUIRED`. Signing (and voiding) recomputes the booking's `minors_present` and `referee_required` flags. A waiver may be voided from either `DRAFT` or `SIGNED`, moving it to `VOID` and again recomputing those two booking flags; a waiver transition from a disallowed state is rejected with `ERR_WAIVER_INVALID_STATE`.

The booking's `minors_present` flag is true when at least one signed, non-void waiver on the booking is for a minor. That flag, together with the field's game mode and the party size, drives `referee_required`: a booking requires a referee when its `party_size` is at least 12, or when minors are present, or when the field's `game_mode` is `PAINTBALL`. Any one of these three conditions is sufficient.

The minor-waiver safety gate is enforced at check-in: every waiver profile on the booking whose status is not `VOID` and whose `is_minor` is true must be `SIGNED` and carry a `guardian_name`. Adults need no individual waiver row at all to be checked in — only minors who actually have a profile on the booking are gated. A check-in that violates this is rejected with `ERR_MINOR_WAIVER_REQUIRED`. The referee gate is also enforced at check-in: if the booking's `referee_required` is true, an `ASSIGNED` referee assignment must already exist for the booking, or the check-in is rejected with `ERR_REFEREE_REQUIRED`. These two safety checks both carry HTTP 422.

### 3.7. Staffing Referees

A **Referee** is a marshal an `ArenaManager` registers with an `arena_id`, a `name`, and an optional `certified_paintball` flag (defaulting to false). A referee who is not certified for paintball may marshal laser-tag sessions but not paintball ones. A referee's `status` is `AVAILABLE`, `ON_DUTY`, or `OFF_SHIFT`; `ON_DUTY` means currently assigned to a live booking.

A `FieldMarshal` staffs a game by creating a **RefereeAssignment** with an `arena_id`, a `booking_id`, and a `referee_id`. Eligibility is enforced at assignment: assigning a referee whose `status` is not `AVAILABLE` is rejected, and assigning a referee who is not `certified_paintball` to a booking on a `PAINTBALL` field is rejected — both surface as `ERR_REFEREE_NOT_ELIGIBLE`. On a successful assignment the assignment is created in `ASSIGNED` status and the referee moves to `ON_DUTY`. An assignment moves to `RELEASED` when its booking ends or is cancelled, at which point its referee returns to `AVAILABLE`; the booking completion, cancellation, and no-show flows all perform this release automatically.

### 3.8. Closing Out a Booking: Completion, No-Show, and Cancellation

Completion is the `FieldMarshal` action that finalizes a checked-in session. It requires the booking to be `CHECKED_IN` and every rental for it to have been returned — a booking with any rental still `CHECKED_OUT` cannot complete and is rejected with `ERR_BOOKING_INVALID_STATE`. On completion every `QUOTED` add-on order on the booking is settled (its `settled_total_cents` computed by the settled variant of §3.5), the booking's final invoice is computed into `invoice_total_cents`, the booking transitions `CHECKED_IN → COMPLETED`, any referee assignment is released and its referee freed, and `reserved_headcount` is recomputed.

The invoice is built from three lines and taxed line-by-line, and the order is pinned because it changes the answer. The field line is the booking's `field_fee_cents`. The add-on line is the sum of `settled_total_cents` across the booking's add-on orders. The forfeit line is the sum of `deposit_forfeit_cents` across the booking's rentals. Each line is taxed independently at the 8.25 percent sales rate: a line's taxed value is the line plus the line times 0.0825 rounded half up to the nearest cent. The `invoice_total_cents` is then the sum of the three taxed lines. The order is fixed — round each line's tax to a whole cent first, then add the three taxed lines together. Summing the three raw lines and taxing the total once is explicitly not the algorithm and can differ by a cent or two.

A `FieldMarshal` marks a confirmed booking as a no-show once its window has passed. No-show requires the booking to be `CONFIRMED` and the arena's current time to be at or after `window_end`; a no-show attempted while the current time is still before `window_end` is rejected with `ERR_BOOKING_INVALID_STATE`. On success the booking transitions `CONFIRMED → NO_SHOW`, every `HELD` rental for it is released (units back to `AVAILABLE`, `deposit_held_cents` decremented), every `QUOTED` add-on order is voided, any referee assignment is released and its referee freed, and `reserved_headcount` is recomputed.

Cancellation is the `FrontDesk` escape hatch and is permitted while the booking is `HELD` or `CONFIRMED`; a booking in any other state cannot be cancelled and is rejected with `ERR_BOOKING_INVALID_STATE`. Cancellation runs the full cascade in order: first, every rental for the booking that is `HELD` or `CHECKED_OUT` is moved to `RELEASED`; then each of those released rentals' equipment units returns to `AVAILABLE`; then the arena's `deposit_held_cents` is decremented by each released rental's `deposit_hold_cents`; then the arena's equipment available counts are recomputed; every `QUOTED` add-on order on the booking is voided; any referee assignment for the booking is released and its referee returned to `AVAILABLE`; and finally the field's `reserved_headcount` is recomputed. The booking ends in `CANCELLED`. The `HELD → CANCELLED` and `CONFIRMED → CANCELLED` paths run the identical cascade.

### 3.9. Leagues, Rounds, and Standings

A `LeagueDirector` runs competitive play. A **League** is created with an `arena_id`, a `name`, a `total_rounds` count (at least one), and optionally `win_points` (default 3, zero or greater) and `draw_points` (default 1, zero or greater). It starts in `DRAFT` with `current_round` at 0. Opening the league moves it `DRAFT → OPEN` and sets `current_round` to 1. A league's `status` cycles between `OPEN` and `ROUND_LOCKED` across its rounds and ends at `FINALIZED`; an illegal league transition is rejected with `ERR_LEAGUE_INVALID_STATE`.

Within an open round the director schedules matches. A **LeagueMatch** is created with an `arena_id`, a `league_id`, a `booking_id` (the physical session the match is played in), a `home_team`, and an `away_team`. The match is created `SCHEDULED` and its `round_index` is stamped with the league's `current_round` at creation. A result is recorded by supplying `home_score` and `away_score` (each zero or greater); recording requires the match to be `SCHEDULED`, the league to be `OPEN`, the match's `round_index` to equal the league's `current_round`, and the linked booking to be `COMPLETED`. If any one of these four record preconditions fails — the match is not `SCHEDULED`, the league is not `OPEN`, the `round_index` does not equal the league's `current_round`, or the linked booking is not `COMPLETED` — the request is rejected with `ERR_MATCH_INVALID_STATE`; the linked-booking-not-`COMPLETED` failure uses `ERR_MATCH_INVALID_STATE` as well, not a booking-state error. On a successful record the match's scores are persisted, its `outcome` is derived (`HOME` when the home score is greater, `AWAY` when the away score is greater, `DRAW` when they are equal), and the match moves `SCHEDULED → RESULT_RECORDED`. A scheduled match may instead be voided, moving it `SCHEDULED → VOID`; a match transition from a disallowed state is rejected with `ERR_MATCH_INVALID_STATE`.

Locking the current round moves the league `OPEN → ROUND_LOCKED` and is guarded three ways: every match in the current round must already be in `RESULT_RECORDED` or `VOID` (a still-`SCHEDULED` match blocks the lock with `ERR_ROUND_NOT_COMPLETE`), and the request must pass the OCC check of §2.6 carrying `expected_league_version`. On a successful lock the league's `version` is incremented by one and the standings are recomputed. Advancing to the next round moves the league `ROUND_LOCKED → OPEN`: it requires `current_round` to be strictly less than `total_rounds` (an attempt at the last round is rejected with `ERR_ROUND_LIMIT_REACHED`) and again carries `expected_league_version`; on success `current_round` is incremented by one and the league's `version` is incremented by one. Finalizing moves the league `ROUND_LOCKED → FINALIZED` and requires `current_round` to equal `total_rounds`; a finalize attempted before the final round is locked is rejected with `ERR_LEAGUE_NOT_AT_FINAL_ROUND`, and the final standings are frozen.

Standings are computed deterministically and recomputed when a round is locked, and they can also be read at any time. The computation considers every `RESULT_RECORDED` match whose `round_index` is at or below the league's `current_round`; voided matches are excluded entirely. Each distinct team label appearing as a `home_team` or `away_team` starts at zero points. Walking the qualifying matches in chronological order of their creation timestamp, a `DRAW` adds the league's `draw_points` to both teams, a `HOME` outcome adds the league's `win_points` to the home team, and an `AWAY` outcome adds the league's `win_points` to the away team. The standings list is then the teams sorted by points descending, breaking ties by team label ascending — the ordering uses only points and labels, never internal ids, so it is fully deterministic. The standings read returns a single object (`response_type` "object") whose `data` carries a `standings` array, the league's `current_round`, and its `league_version`; each entry in the `standings` array is an object with exactly a `team` string and an integer `points`. Within the chronological walk, matches sharing an identical `created_at` are ordered by their underlying creation sequence so the accumulation is stable.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — every state transition, settlement, clock set, and close — return a `200 OK` status code. Read operations return `200 OK`. The request and response bodies for each endpoint are not repeated here; reconstruct them from the workflow narratives in §3, where every input field and side effect is described.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/arenas` | Create an arena (provisions equipment pool counters) | ArenaManager |
| GET | `/arenas/{arenaId}` | Get an arena with reconciled pool + deposit ledger fields | ArenaManager, FrontDesk, FieldMarshal, LeagueDirector |
| GET | `/arenas` | List arenas | ArenaManager, FrontDesk, FieldMarshal, LeagueDirector |
| POST | `/_clock/set` | Set an arena's deterministic clock | ArenaManager |
| POST | `/arenas/{arenaId}/close` | Close an arena | ArenaManager |
| POST | `/fields` | Create a playing field under an arena | ArenaManager |
| GET | `/fields/{fieldId}` | Get a field | ArenaManager, FrontDesk, FieldMarshal, LeagueDirector |
| GET | `/fields` | List fields (optional `arena_id` filter) | ArenaManager, FrontDesk, FieldMarshal, LeagueDirector |
| POST | `/fields/{fieldId}/close` | Close a field | ArenaManager |
| POST | `/party-packages` | Create a party package | ArenaManager |
| GET | `/party-packages/{packageId}` | Get a party package | ArenaManager, FrontDesk, LeagueDirector, FieldMarshal |
| GET | `/party-packages` | List party packages (optional `arena_id` filter) | ArenaManager, FrontDesk, LeagueDirector, FieldMarshal |
| POST | `/bookings` | Create a booking (HELD) on a field over a half-open window | FrontDesk |
| GET | `/bookings/{bookingId}` | Get a booking with computed fee/invoice/flag fields | ArenaManager, FrontDesk, FieldMarshal, LeagueDirector |
| GET | `/bookings` | List bookings (optional `arena_id`, `field_id`, `package_id` filters) | ArenaManager, FrontDesk, FieldMarshal, LeagueDirector |
| POST | `/bookings/{bookingId}/confirm` | Confirm a HELD booking (OCC on the field version) | FrontDesk |
| POST | `/bookings/{bookingId}/check-in` | Check in a confirmed booking; checks out held rentals | FieldMarshal |
| POST | `/bookings/{bookingId}/complete` | Complete a checked-in booking; settles add-ons and invoice | FieldMarshal |
| POST | `/bookings/{bookingId}/no-show` | Mark a confirmed booking as no-show after its window ends | FieldMarshal |
| POST | `/bookings/{bookingId}/cancel` | Cancel a HELD or CONFIRMED booking (cascade release) | FrontDesk |
| POST | `/waiver-profiles` | Create a waiver profile (DRAFT) for a participant | FrontDesk |
| GET | `/waiver-profiles/{waiverId}` | Get a waiver profile | ArenaManager, FrontDesk, FieldMarshal |
| GET | `/waiver-profiles` | List waiver profiles (optional `arena_id`, `booking_id` filters) | ArenaManager, FrontDesk, FieldMarshal |
| POST | `/waiver-profiles/{waiverId}/sign` | Sign a waiver (enforces guardian rule for minors) | FrontDesk |
| POST | `/waiver-profiles/{waiverId}/void` | Void a waiver | FrontDesk |
| POST | `/equipment-units` | Provision a marker or vest into the arena pool | ArenaManager |
| GET | `/equipment-units/{unitId}` | Get an equipment unit | ArenaManager, FrontDesk, FieldMarshal |
| GET | `/equipment-units` | List equipment units (optional `arena_id` filter) | ArenaManager, FrontDesk, FieldMarshal |
| POST | `/equipment-units/{unitId}/restore` | Restore a unit from MAINTENANCE back to AVAILABLE | ArenaManager |
| POST | `/rentals` | Reserve an equipment unit for a booking (HELD rental; holds deposit) | FrontDesk |
| GET | `/rentals/{rentalId}` | Get a rental | ArenaManager, FrontDesk, FieldMarshal |
| GET | `/rentals` | List rentals (optional `arena_id`, `booking_id`, `equipment_unit_id` filters) | ArenaManager, FrontDesk, FieldMarshal |
| POST | `/rentals/{rentalId}/return` | Return a checked-out rental; settles deposit | FieldMarshal |
| POST | `/rentals/{rentalId}/release` | Release a HELD rental before checkout | FrontDesk |
| POST | `/add-on-orders` | Create an ammo/CO2/misc add-on order (QUOTED) | FrontDesk |
| GET | `/add-on-orders/{orderId}` | Get an add-on order | ArenaManager, FrontDesk, FieldMarshal |
| GET | `/add-on-orders` | List add-on orders (optional `arena_id`, `booking_id` filters) | ArenaManager, FrontDesk, FieldMarshal |
| POST | `/referees` | Create a referee/marshal | ArenaManager |
| GET | `/referees/{refereeId}` | Get a referee | ArenaManager, FrontDesk, FieldMarshal |
| GET | `/referees` | List referees (optional `arena_id` filter) | ArenaManager, FrontDesk, FieldMarshal |
| POST | `/referee-assignments` | Assign an available referee to a booking | FieldMarshal |
| GET | `/referee-assignments/{assignmentId}` | Get a referee assignment | ArenaManager, FrontDesk, FieldMarshal |
| GET | `/referee-assignments` | List referee assignments (optional `arena_id`, `booking_id`, `referee_id` filters) | ArenaManager, FrontDesk, FieldMarshal |
| POST | `/leagues` | Create a league (DRAFT) | LeagueDirector |
| GET | `/leagues/{leagueId}` | Get a league | ArenaManager, FrontDesk, LeagueDirector |
| GET | `/leagues` | List leagues (optional `arena_id` filter) | ArenaManager, FrontDesk, LeagueDirector |
| GET | `/leagues/{leagueId}/standings` | Computed read: current league standings | ArenaManager, FrontDesk, LeagueDirector |
| POST | `/leagues/{leagueId}/open` | Open a league (DRAFT → OPEN, current round 1) | LeagueDirector |
| POST | `/leagues/{leagueId}/lock-round` | Lock the current round (OCC; recomputes standings) | LeagueDirector |
| POST | `/leagues/{leagueId}/advance-round` | Advance to the next round (OCC on league version) | LeagueDirector |
| POST | `/leagues/{leagueId}/finalize` | Finalize the league after the last round is locked | LeagueDirector |
| POST | `/league-matches` | Schedule a match in the current open round | LeagueDirector |
| GET | `/league-matches/{matchId}` | Get a league match | ArenaManager, FrontDesk, LeagueDirector |
| GET | `/league-matches` | List league matches (optional `arena_id`, `league_id`, `booking_id` filters) | ArenaManager, FrontDesk, LeagueDirector |
| POST | `/league-matches/{matchId}/record-result` | Record a match result (requires linked booking COMPLETED) | LeagueDirector |
| POST | `/league-matches/{matchId}/void` | Void a scheduled match | LeagueDirector |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives that govern the operation; this catalogue lists only the identifier and its HTTP status. Validation precedence across all write endpoints runs in this fixed order: missing or malformed user headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 401) first; then role permission (`ERR_FORBIDDEN_ROLE`, 403); then existence of every path id and body foreign key, left-to-right (the 404 family); then required-field presence, type, and enum-domain validity (`ERR_VALIDATION`, 400); then target-state legality for the requested transition (the `*_INVALID_STATE` family, 409); then the optimistic-concurrency version check (`ERR_STALE_FIELD_VERSION` / `ERR_STALE_LEAGUE_VERSION`, 412); then the business safety, referential, temporal, constraint, and fiscal rules. Within that final group the minor-waiver and referee safety gates, the referee-eligibility check, the field-slot and equipment-time conflicts, the lead-time and window checks, the capacity, equipment-availability, and package-active constraints, and the damage-fee bound each apply on the operations named in §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_ARENA_NOT_FOUND` | 404 Not Found |
| `ERR_FIELD_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RENTAL_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_REFEREE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LEAGUE_NOT_FOUND` | 404 Not Found |
| `ERR_MATCH_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_RENTAL_INVALID_STATE` | 409 Conflict |
| `ERR_WAIVER_INVALID_STATE` | 409 Conflict |
| `ERR_EQUIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_LEAGUE_INVALID_STATE` | 409 Conflict |
| `ERR_MATCH_INVALID_STATE` | 409 Conflict |
| `ERR_ARENA_CLOSED` | 409 Conflict |
| `ERR_FIELD_CLOSED` | 409 Conflict |
| `ERR_ROUND_NOT_COMPLETE` | 409 Conflict |
| `ERR_ROUND_LIMIT_REACHED` | 409 Conflict |
| `ERR_LEAGUE_NOT_AT_FINAL_ROUND` | 409 Conflict |
| `ERR_STALE_FIELD_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LEAGUE_VERSION` | 412 Precondition Failed |
| `ERR_MINOR_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_REFEREE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_REFEREE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_FIELD_SLOT_CONFLICT` | 409 Conflict |
| `ERR_EQUIPMENT_TIME_CONFLICT` | 409 Conflict |
| `ERR_LEAD_TIME_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 Conflict |
| `ERR_PACKAGE_INACTIVE` | 409 Conflict |
| `ERR_DAMAGE_FEE_EXCEEDS_DEPOSIT` | 422 Unprocessable Entity |
