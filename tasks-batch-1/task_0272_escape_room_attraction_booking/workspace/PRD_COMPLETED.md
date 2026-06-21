# Escape Room & Attraction Booking API — Product Requirements Document

## 1. Introduction

This document specifies the Escape Room & Attraction Booking API, a backend platform that lets entertainment venues sell timed, room-based experiences while protecting two scarce resources at once: the physical room (which must rest and reset between games) and the human game master who runs each session. The product sits at the intersection of inventory management and a live pricing engine. On one side it tracks an ownership tree of venues, the rooms within them, and the bookable time slots within each room; on the other it runs a booking lifecycle that grabs a slot, quotes a price, applies gift cards, takes payment, and ultimately settles the charge against who actually showed up.

The hardest problems this API solves are temporal and financial. A room cannot host two overlapping games, and a game master cannot run two overlapping sessions, so the system must reason about half-open time intervals that include a reset buffer for rooms but exclude it for staff. Pricing is dual-natured: customers see a forward-looking quote based on the group size they intend to bring, but the venue ultimately bills a settled charge based on the participants who were physically present. Layered on top are peak-hour and large-group multipliers, per-participant gift-card redemption with conserved balances, and a no-show penalty regime that both retains a fee and accumulates strikes against repeat offenders. Because multiple customers may race for the same open slot, the slot-grab and reschedule operations are guarded by optimistic concurrency control on the slot's version.

The intended audience for this document is the engineering team implementing the service. It describes the domain rules first and the HTTP surface second; readers should treat the business-logic narrative in Section 3 as the authoritative source for request payloads, side effects, and validation ordering, and refer back to it when reading the endpoint and error tables in Sections 4 and 5.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting principal, and the `X-User-Role` header declares the operational capacity in which they are acting. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`. When a request is well-formed and authenticated but the declared role is not permitted to perform the operation under the access-control matrix in Section 4, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `PlatformAdmin`, `VenueManager`, `GameMaster`, and `Customer`. An authenticated request whose `X-User-Role` is none of these four is simply treated as a role not permitted for the operation, so it is rejected with `ERR_FORBIDDEN` rather than any dedicated unknown-role error. Their identities relate to persisted entities in two different ways. A `PlatformAdmin` is an opaque operator identifier: `X-User-ID` is not tied to any persisted entity, and while the server may record it for audit purposes it never compares it to any entity's `id`. The same opaque treatment applies to a `VenueManager`: when `X-User-Role` is `VenueManager`, `X-User-ID` is an opaque operator identifier used to authorize venue-configuration actions but is not matched against any stored record.

The remaining two roles are entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's owning foreign key to `X-User-ID`. Concretely, a `Customer` acting on a booking must be the booking's owner — `X-User-ID` must equal the booking's `customer_id`, and a mismatch is an `ERR_FORBIDDEN`. This ownership rule extends to the participants and waivers nested under a booking. When `X-User-Role` is `GameMaster`, `X-User-ID` is the `id` of the acting `GameMaster`; the game-master role runs the on-site experience (marking participants present, checking in, completing, and recording no-shows) within its venue.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range of 1 to 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, every list response is ordered by the `created_at` timestamp in ascending order, and rows sharing an identical `created_at` are further ordered by their `id` in ascending order so the page is fully deterministic. List responses always carry the pagination bookkeeping fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full size of the filtered set and `has_more` indicates whether further pages remain.

### 2.4. Identity, Timestamps, and Versioning of Resources

Every resource is identified by an `id` that the server mints as a UUID with no type prefix; clients never supply it. Most resources also carry a system-managed audit and concurrency triple: `created_at` and `updated_at` are ISO 8601 timestamps in UTC with millisecond (three fractional-digit) precision, and `version` is an integer that begins at 1 on creation and increases by exactly 1 on every mutation of the resource, including mutations caused by cascades originating elsewhere. The `created_at` value is fixed at creation; `updated_at` is refreshed on each mutation.

This full triple applies to venues, rooms, pricing rules, game masters, time slots, customers, bookings, participants, and gift cards. The one exception is the gift-card ledger entry, which is an append-only record: a `GiftCardEntry` carries only an `id` and a `created_at`. It has neither an `updated_at` nor a `version`, because once written it is never mutated.

### 2.5. Optimistic Concurrency Control

Several mutating operations require the client to prove it is acting on a current view of a resource by submitting that resource's last observed `version` in the request body. When the submitted version does not match the server's current `version` for the targeted resource, the mutation is rejected and no side effects occur.

Two of these checks are special because they guard the booking inventory and carry their own error. The slot-grab that occurs when a booking is created requires an `expected_time_slot_version` field carrying the client's last observed `version` of the target `TimeSlot`. If another writer has advanced that slot's `version` since the client read it — for example, by legitimately grabbing the same open slot under the booking flow — the create is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412), so the client never overwrites a slot it has not observed. The reschedule operation applies the same pattern to the slot swap: it requires an `expected_time_slot_version` matching the current (old) slot's `version`, and if that slot's `version` has advanced since the client observed it, the reschedule is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412).

The other versioned mutations operate on non-slot resources and carry a generic stale-version error, `ERR_STALE_VERSION` (HTTP 412), when the submitted version is out of date. Retiring a room requires `expected_room_version`; setting a game master's status requires `expected_game_master_version`; signing, revoking, and marking-present a participant each require `expected_participant_version`; topping up and voiding a gift card each require `expected_gift_card_version`; and confirming, rescheduling, checking in, completing, no-showing, or cancelling a booking each require `expected_booking_version`. Blocking, unblocking, and closing a time slot each require `expected_time_slot_version`, and because these are non-grab slot mutations a mismatch yields `ERR_STALE_VERSION`. The reschedule operation is the one request that carries two version fields at once: `expected_time_slot_version` for the old slot (failing with `ERR_STALE_SLOT_VERSION`) and `expected_booking_version` for the booking itself (failing with `ERR_STALE_VERSION`). Endpoints that simply create a top-level resource or read data take no version field.

### 2.6. Cascading Consistency Across the Resource Hierarchy

The venue sits at the root of an ownership tree: a venue owns its rooms, and each room owns its time slots. Bookings, customers, game masters, and gift cards are peer entities that cross-cut this tree through their foreign keys. Because a single business action frequently mutates several of these entities at once, the system treats each affected entity's mutation as a first-class change: whenever a cascade touches an entity, that entity's `updated_at` is refreshed and its `version` is incremented by 1, exactly as for a direct mutation. The narratives in Section 3 enumerate which entities each operation touches; implementers must apply every listed cascade, not only the primary state change.

A few derived counters are kept continuously consistent with the rows that feed them. A game master's `active_assignment_count` always equals the number of that master's time slots whose status is `HELD` or `BOOKED`; it is recomputed whenever a slot enters or leaves those states. A customer's `no_show_strike_count` always equals the number of that customer's bookings currently in `NO_SHOW`. A gift card's `balance_cents` always equals its `initial_balance_cents` plus the signed sum of every ledger entry written against it.

### 2.7. Nested Resource Retrieval and Existence Ordering

Although most resources are reachable through flat top-level collections, several operations name a chain of resources, and existence is validated strictly left-to-right along the path: the venue first, then the room, then the slot or booking, then the participant. The first identifier in the chain that does not resolve produces `ERR_NOT_FOUND`, and the server does not look further down the chain once a link is missing. The same `ERR_NOT_FOUND` covers body references that fail to resolve — when a booking-create, confirm, reschedule, or pricing-rule-create payload names a `time_slot_id`, `customer_id`, `gift_card_id`, or `room_id` that does not exist, the request is rejected with `ERR_NOT_FOUND`.

### 2.8. Monetary Amounts, Multipliers, and Rounding

All monetary amounts in this system are integer cents; there are no fractional-cent values stored or returned. Per-participant prices are scaled by multipliers expressed in basis points, where 10000 basis points means a factor of exactly 1.0. The pricing pipeline applies a floor (truncation toward zero) after each per-participant multiplier step, in the pinned order described in Section 3, before the per-participant amount is multiplied across the group. Where a calculation calls for rounding rather than flooring — specifically the no-show fee — the system rounds half up to the nearest whole cent. Section 3 specifies, calculation by calculation, exactly which operation rounds and which floors.

### 2.9. Validation Ordering

When a single request could fail several checks, the system evaluates them in a fixed priority so that the returned error is predictable. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a role not permitted for the operation, or a customer acting on a booking it does not own, fails with `ERR_FORBIDDEN`. Existence checks follow — path references are resolved left-to-right and then body references are resolved, each missing reference yielding `ERR_NOT_FOUND`. After existence, the system validates the request shape: required body fields must be present and well-typed, enum values must be valid, and numeric ranges must hold (for instance `group_size` must be an integer and `age` must be at least 0); a violation here is `ERR_INVALID_REQUEST` (HTTP 422). Only then does the system check that the target resource is in a valid state for the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when it is not. Optimistic-concurrency checks are evaluated after the state check. The remaining domain-specific business rules — age, waiver, group size, slot overlap, game-master availability, no-show risk, gift-card usability, and operating hours — are evaluated after those structural layers, each surfacing in the workflow narrative that defines it.

## 3. Business Logic & Workflows

### 3.1. Provisioning Venues, Rooms, and Pricing

A `PlatformAdmin` brings a venue into existence, supplying its `name`, an IANA `timezone` label (informational only — all stored times are UTC), and its daily operating window expressed as minutes from local midnight: `open_minute_of_day` (which must be at least 0 and strictly less than the closing minute) and `close_minute_of_day` (which must be strictly greater than the opening minute and at most 1440). Two financial-policy fields may optionally be supplied at creation. The `no_show_fee_pct` is the fraction of a booking's settled charge the venue retains when a guest fails to appear; it ranges from 0.0 to 1.0 and defaults to 0.5. The `no_show_strike_limit` is the strike count at which a customer becomes barred from new confirmed bookings; it must be at least 1 and defaults to 3.

Within a venue, a `VenueManager` configures the rooms. Creating a room takes the owning `venue_id` plus a `name`, and the group bounds `min_group_size` and `max_group_size`, where the minimum must be at least 1 and no greater than the maximum, and the maximum must be at least the minimum. Pricing and timing are governed by `base_price_cents` (the per-participant price in cents before any rule, at least 0), `game_minutes` (the active play duration, at least 1), and several optional fields: `min_age` (the minimum participant age in whole years, at least 0, where 0 means no age floor, defaulting to 0); `waiver_required` (defaulting to true, meaning every participant must have a signed waiver before the group can be checked in); `private_surcharge_cents` (a flat surcharge added when the whole room is reserved privately, at least 0, defaulting to 0); and `reset_buffer_minutes` (the reset time after the game during which the room is unavailable, at least 0, defaulting to 0). A newly created room starts with `status` of `ACTIVE`. A manager may later retire a room, advancing its `status` from `ACTIVE` to `RETIRED` so that it accepts no new slots or bookings.

Pricing rules let a manager surcharge peak times and large groups for a specific room. Creating a pricing rule names the `venue_id` and the `room_id` it applies to, and defines a peak window and a large-group breakpoint. The peak window is described by `peak_dow_mask` (a bitmask of peak days of week from 0 to 127, where bit 0 is Monday through bit 6 is Sunday, tested against the slot's UTC weekday), `peak_start_minute_of_day` (the inclusive start as minutes from UTC midnight, 0 to 1439), and `peak_end_minute_of_day` (the exclusive end, strictly greater than the start and at most 1440). The peak surcharge itself is `peak_multiplier_bps`, a per-participant multiplier in basis points that must be at least 10000 and defaults to 10000 (no change). The large-group rule fires when the relevant participant count is at least `large_group_threshold` (which must be at least 1) and multiplies the per-participant price by `large_group_multiplier_bps`, again at least 10000 and defaulting to 10000.

### 3.2. Staffing, Slot Inventory, and the Room/Game-Master Time Geometry

A `VenueManager` registers each game master under a venue by supplying the owning `venue_id` and a `full_name`. A new game master starts `AVAILABLE` with an `active_assignment_count` of 0. The manager may toggle a master between `AVAILABLE` and `OFF_DUTY` by submitting the new `status`; only an `AVAILABLE` master is eligible to be assigned to a slot.

The manager also publishes the bookable inventory by creating time slots. A slot is created against a `room_id` with a `start_utc` (the game start instant). On creation the server copies the `venue_id` from the room and computes two derived instants: `game_end_utc`, which is `start_utc` plus the room's `game_minutes`, and `block_end_utc`, which is `start_utc` plus the room's `game_minutes` plus the room's `reset_buffer_minutes`. The interval that the slot occupies the *room* is the half-open span from `start_utc` up to but not including `block_end_utc` — that is, the game plus its reset buffer. A new slot begins with `status` of `OPEN`. A slot may only be created if its game window fits inside the venue's operating window: the slot's start minute-of-day (its UTC hour times sixty plus its UTC minute) must be at least `open_minute_of_day`, and that start minute-of-day plus the room's `game_minutes` must be no greater than `close_minute_of_day`; a slot failing either bound is rejected with `ERR_OUTSIDE_OPERATING_HOURS`. The game-end figure is the start minute-of-day plus `game_minutes` measured on the same day's timeline and is not wrapped modulo 1440, so a game that would run past local midnight exceeds `close_minute_of_day` and is rejected. Only the game window is tested; the reset buffer is not considered for operating hours. Creating a slot on a room whose `status` is `RETIRED` is rejected with `ERR_ROOM_RETIRED`.

Two distinct overlap geometries govern whether a slot can be taken, and the difference between them is deliberate. The **room overlap** uses the full occupied interval including the reset buffer: a slot cannot be grabbed if any other slot of the *same room* that is currently `HELD` or `BOOKED` has a `[start_utc, block_end_utc)` interval that overlaps the target's `[start_utc, block_end_utc)` interval; a clash here is `ERR_SLOT_OVERLAP`. The **game-master overlap** excludes the buffer: a master is only eligible if it has no `HELD` or `BOOKED` slot of *any* room whose game window `[start_utc, game_end_utc)` overlaps the target slot's game window `[start_utc, game_end_utc)`. In other words, a room needs its full reset buffer free of other games, but a game master only needs the active play windows to not collide. Both intervals are closed on the start instant and open on the end instant.

When a master must be chosen for a slot, the candidate set is every game master of the venue whose `status` is `AVAILABLE` and that has no overlapping `HELD` or `BOOKED` game window per the rule just described. The selector ranks candidates by `active_assignment_count` ascending and breaks ties by `created_at` ascending, and any remaining tie by `id` ascending, picking the first. If the candidate set is empty, the operation is rejected with `ERR_NO_GAMEMASTER_AVAILABLE`.

A manager controls slot availability through three lifecycle actions on a slot. Blocking a slot moves it `OPEN → BLOCKED`, taking it out of the bookable pool for maintenance; this is only permitted on an `OPEN` slot. Unblocking reverses that, moving `BLOCKED → OPEN`, and is only permitted on a `BLOCKED` slot. Closing permanently removes a slot from inventory, moving it to `CLOSED`, and is permitted only when the slot is in `OPEN` or `BLOCKED`; a `HELD` or `BOOKED` slot cannot be closed. `CLOSED` is terminal. Each of these three actions increments the slot's `version`. Attempting any of them from a state the action does not allow is an `ERR_INVALID_STATE`.

### 3.3. Customers and the Slot Grab

Customers are registered with an `email` (unique within the system, compared case-insensitively) and a `full_name`. A new customer's `no_show_strike_count` starts at 0. Registering with an email that already exists is rejected with `ERR_DUPLICATE_RESOURCE`. The same duplicate error guards gift-card codes, discussed later.

A booking begins life as a slot grab. A `Customer` initiates one by naming the `time_slot_id` to grab, the `customer_id` who will own the booking, the intended `group_size`, and `expected_time_slot_version` (the client's last observed `version` of that slot); an optional `is_private` flag (defaulting to false) reserves the whole room. This single action advances the slot from `OPEN` to `HELD` and creates a new booking in `lifecycle_status` of `DRAFT` and `payment_status` of `UNPAID`. The grab succeeds only if the slot is currently `OPEN`, the slot's room `status` is `ACTIVE` (otherwise `ERR_ROOM_RETIRED`), the room-overlap check passes (otherwise `ERR_SLOT_OVERLAP`), and an eligible game master exists (otherwise `ERR_NO_GAMEMASTER_AVAILABLE`). The intended `group_size` must lie between the room's `min_group_size` and `max_group_size` inclusive; a value outside that band is `ERR_GROUP_SIZE_INVALID`. If the slot is not `OPEN`, the grab fails with `ERR_INVALID_STATE`; if `expected_time_slot_version` does not match the slot's current `version`, it fails with `ERR_STALE_SLOT_VERSION`. When several of these checks could fire at once, they are evaluated in a fixed order: the slot-`OPEN` state check first, then the slot-version (`ERR_STALE_SLOT_VERSION`) check, then the room-retired (`ERR_ROOM_RETIRED`) check, then the `group_size` band (`ERR_GROUP_SIZE_INVALID`), then the room-overlap (`ERR_SLOT_OVERLAP`) check, and finally game-master availability (`ERR_NO_GAMEMASTER_AVAILABLE`).

When the grab succeeds, the server records several derived facts on the new booking and its dependents. The booking copies `venue_id` and `room_id` from the slot's room and stores the grabbed `time_slot_id`. The slot's `booking_id` is set to the new booking, its `assigned_game_master_id` is set to the selected master, and the slot's `version` is incremented. The selected master's `active_assignment_count` is recomputed (rising by one as the slot enters `HELD`). The booking's `gift_card_id` is left null at grab time; it is supplied later, at confirm.

Consider a scenario where two customers both read the same `OPEN` slot at `version` 4 and both attempt to grab it. The first to be processed advances the slot to `HELD` and to `version` 5. The second, still carrying `expected_time_slot_version` of 4, no longer matches and is rejected with `ERR_STALE_SLOT_VERSION` — the slot grab is a create-with-supersede write resolved by optimistic concurrency on the slot's `version` rather than by a plain state check, because either customer would have been a legitimate winner had they arrived first.

### 3.4. Building the Party: Participants and Waivers

Once a booking exists in `DRAFT` or `CONFIRMED`, its owning `Customer` populates the party. Adding a participant supplies a `display_name` and an `age` in whole years (at least 0); the new participant starts with `waiver_status` of `PENDING` and `checked_in` of false. Each participant belongs to its booking through `booking_id`.

Waivers follow a small cyclic machine. A customer signs a participant's waiver, moving `waiver_status` from `PENDING` or `REVOKED` to `SIGNED`; signing is only allowed while the owning booking is in `DRAFT` or `CONFIRMED`, and the participant's `age` must be at least the owning room's `min_age` — a younger participant is rejected with `ERR_AGE_REQUIREMENT_NOT_MET`. A customer may also revoke a signed waiver, moving `waiver_status` from `SIGNED` to `REVOKED`, again only while the booking is in `DRAFT` or `CONFIRMED`. Each waiver transition increments the participant's `version`.

On game day, before the group is checked in, a `GameMaster` records who actually arrived by marking individual participants present, which sets `checked_in` to true and increments the participant's `version`; mark-present imposes no booking-lifecycle precondition and no participant-`waiver_status` precondition, requiring only that `expected_participant_version` match the participant's current `version`. The set of participants with `checked_in` true is what later drives both the check-in gate and the final settlement.

### 3.5. Confirming a Booking: Quote, Gift Card, and Authorization

A `Customer` confirms a `DRAFT` booking to lock it in. The confirm payload carries `expected_booking_version` and optionally a `gift_card_id` to redeem at this moment. Confirmation requires that the booking is in `DRAFT`, that its held slot is still `HELD`, that the owning customer's `no_show_strike_count` is strictly less than the venue's `no_show_strike_limit` (otherwise `ERR_NO_SHOW_LIMIT_REACHED`), and — when a gift card is supplied — that the gift card's `status` is `ACTIVE`, that its `venue_id` matches the booking's `venue_id`, and that its `balance_cents` is greater than 0 (any of these failing yields `ERR_GIFT_CARD_UNUSABLE`). A confirm attempted on a booking that is not in `DRAFT`, or whose slot is not `HELD`, fails with `ERR_INVALID_STATE`.

Confirmation first computes the forward-looking quote and stores it in `quoted_charge_cents`. The quote uses the *intended* `group_size` rather than who will eventually show up, and it is built in a strictly pinned order. Begin with a per-participant amount equal to the room's `base_price_cents`. Next, if the slot falls in a peak window — meaning there is a pricing rule for the booking's `room_id` (and if more than one rule exists for the room, the earliest-created one, i.e. the first in `created_at` order, is the one consulted for both the peak and large-group steps), the slot's `start_utc` UTC weekday bit is set in that rule's `peak_dow_mask`, and the slot's UTC minute-of-day is at least `peak_start_minute_of_day` and strictly less than `peak_end_minute_of_day` — multiply the per-participant amount by `peak_multiplier_bps`, divide by 10000, and take the floor. Then, if the intended `group_size` is at least `large_group_threshold`, multiply the per-participant amount by `large_group_multiplier_bps`, divide by 10000, and take the floor again. Only after both per-participant multiplier steps have been floored is the per-participant amount multiplied by the `group_size` to form the line total. Finally, if `is_private` is true, add the room's `private_surcharge_cents` to the line total. The resulting line total is `quoted_charge_cents`. If no pricing rule matches the room, both multipliers are treated as 10000 (a factor of 1.0), leaving the base price unchanged.

If a `gift_card_id` was supplied, the system draws against it: `gift_card_applied_cents` is set to the smaller of `quoted_charge_cents` and the gift card's current `balance_cents`. A ledger entry of type `SPEND` is appended to the card with `delta_cents` equal to the negative of `gift_card_applied_cents` and its `related_booking_id` pointing at this booking; the card's `balance_cents` is then recomputed from its full ledger, and if that recomputed balance reaches 0 the card's `status` moves from `ACTIVE` to `DEPLETED`. When no gift card is applied, `gift_card_applied_cents` stays 0. The remaining amount — `quoted_charge_cents` minus `gift_card_applied_cents` — is authorized on the card, moving the booking's `payment_status` from `UNPAID` to `AUTHORIZED`. The held slot advances from `HELD` to `BOOKED`, the booking's `lifecycle_status` becomes `CONFIRMED`, and the booking's `version` is incremented. The slot's `version` is incremented as it moves to `BOOKED`.

### 3.6. Rescheduling a Confirmed Booking

A `Customer` may move a `CONFIRMED` booking to a different slot of the same room. The reschedule payload names the `new_time_slot_id`, an `expected_time_slot_version` for the *current* (old) slot, and an `expected_booking_version` for the booking. The target named by `new_time_slot_id` must be an `OPEN` slot of the same room as the current booking — a target belonging to a different room, or one that is not currently `OPEN`, is rejected with `ERR_INVALID_STATE` — and it must independently pass the same room-overlap and game-master-overlap preconditions that govern a fresh grab — so a reschedule can fail with `ERR_SLOT_OVERLAP` or `ERR_NO_GAMEMASTER_AVAILABLE` exactly as a grab can. These target-slot checks (same-room, then `OPEN`, then overlap, then game-master availability) are evaluated only after the booking's own `CONFIRMED` state check and both version checks have passed. The booking itself must be in `CONFIRMED`; otherwise the request is `ERR_INVALID_STATE`. The old slot's `version` must match `expected_time_slot_version`, or the reschedule is rejected with `ERR_STALE_SLOT_VERSION`; this is the create-with-supersede pattern applied to the slot swap, where a writer that advanced the old slot's `version` after the client read it causes the rejection.

A successful reschedule performs a coordinated swap. The old slot is released `BOOKED → OPEN`: its `booking_id` is cleared, its `assigned_game_master_id` is cleared, the previously assigned master's `active_assignment_count` is recomputed downward, and the old slot's `version` is incremented. The new slot is taken `OPEN → HELD → BOOKED`: a master is chosen by the same selector, the new slot's `assigned_game_master_id` and `booking_id` are set, and its `version` is incremented. The booking's `time_slot_id` and its room-derived fields are updated to the new slot, and `quoted_charge_cents` is recomputed by the same pinned quote pricing — which can change because the new slot may sit in a different peak window — while `group_size` is unchanged. If a gift card had been applied, `gift_card_applied_cents` is *not* changed by a reschedule; only the card-authorized remainder is re-authorized. The booking's `version` is incremented.

### 3.7. Game Day: Check-In, Completion, and Settlement

A `GameMaster` checks in the present group, advancing the booking from `CONFIRMED` to `CHECKED_IN`. Check-in is gated by three party-level rules evaluated against the participants whose `checked_in` is true, applied in this fixed precedence so that the surfaced error is predictable when more than one rule fails at once. First, every checked-in participant must have `age` at least the room's `min_age`; an under-age guest is `ERR_AGE_REQUIREMENT_NOT_MET`. Second, if the room's `waiver_required` is true, every checked-in participant must have `waiver_status` of `SIGNED`; an unsigned waiver among the present group is `ERR_WAIVER_NOT_SIGNED`. Third, the count of checked-in participants must be at least the room's `min_group_size`; too few present is `ERR_GROUP_SIZE_INVALID`. A check-in attempted on a booking that is not `CONFIRMED` is `ERR_INVALID_STATE`. Check-in increments the booking's `version`.

Completing a `CHECKED_IN` booking advances it to `COMPLETED` and settles the charge. Settlement is the chronological counterpart to the forward-looking quote: it bills against the actual count of participants with `checked_in` true (the settled count), which may be fewer than `group_size` if some guests did not arrive. The per-participant pipeline is identical in order to the quote — start at `base_price_cents`; apply the peak step (the same predicate, evaluated against the current slot, multiplying by `peak_multiplier_bps`, dividing by 10000, and flooring); then apply the large-group step, which here fires only when the *settled count* is at least `large_group_threshold` (so a group that booked large but checked in small loses the large-group multiplier), multiplying by `large_group_multiplier_bps`, dividing by 10000, and flooring. The floored per-participant amount is then multiplied by the settled count to form the line total, and if `is_private` is true the room's `private_surcharge_cents` is added. The result is stored in `final_charge_cents`. When every booked participant checked in, the settled count equals `group_size` and `final_charge_cents` equals `quoted_charge_cents`; when some did not, the settled count is lower and the figure may diverge from the quote. Completion captures the card portion of the settled charge — `final_charge_cents` minus `gift_card_applied_cents` — moving `payment_status` from `AUTHORIZED` to `CAPTURED`, and increments the booking's `version`.

### 3.8. No-Shows, Strikes, and Cancellation

When a confirmed group fails to appear, a `GameMaster` records a no-show, moving the booking from `CONFIRMED` to `NO_SHOW`. The retained fee is computed as the booking's `quoted_charge_cents` multiplied by the venue's `no_show_fee_pct`, rounded half up to a whole cent, and stored in `no_show_fee_cents`; `final_charge_cents` is set equal to that fee. The gift-card-funded portion of the original confirmation is not refunded on a no-show — the card portion stays spent — and the card-funded share of the fee is captured while the remaining authorization is voided, so `payment_status` moves from `AUTHORIZED` to `CAPTURED`. The slot that the booking held is released `BOOKED → OPEN`, freeing its game master (the master's `active_assignment_count` is recomputed downward). The owning customer's `no_show_strike_count` is then recomputed, rising by one. The booking's `version` is incremented. Because the strike count gates confirmation, a customer who accumulates strikes equal to or exceeding the venue's `no_show_strike_limit` can no longer drive any future booking from `DRAFT` to `CONFIRMED` at that venue.

A `Customer` may cancel a booking that is in `DRAFT` or `CONFIRMED`, moving it to `CANCELLED`; a cancel from any other state is `ERR_INVALID_STATE`. Cancellation is a compensating action that restores what confirmation consumed. If a gift-card `SPEND` had been applied (only possible for a `CONFIRMED` booking), a `REFUND` ledger entry is appended to that card with `delta_cents` equal to the positive of `gift_card_applied_cents` and `related_booking_id` pointing at this booking; the card's `balance_cents` is recomputed, and if the card had previously been `DEPLETED` and now carries a positive balance its `status` returns to `ACTIVE`. After the refund, the booking's `gift_card_applied_cents` is reset to 0. The booking's `payment_status` becomes `REFUNDED` if it had been `AUTHORIZED` or `CAPTURED`, and otherwise stays `UNPAID`. Any held or booked slot the booking occupied is released to `OPEN`, freeing its game master. The booking's `lifecycle_status` becomes `CANCELLED` and its `version` is incremented. Because the refund magnitude equals the original spend exactly — both derive from the single `gift_card_applied_cents` figure — a confirm-then-cancel cycle returns the card's running balance to its pre-confirm value precisely.

### 3.9. Gift Cards and the Ledger

A `VenueManager` issues a gift card under a venue by supplying the owning `venue_id`, a `code` (unique within the venue, compared case-insensitively, with a clash rejected as `ERR_DUPLICATE_RESOURCE`), and an `initial_balance_cents` of at least 1. The card starts `ACTIVE`, and its `balance_cents` is the running total of `initial_balance_cents` plus the signed sum of every ledger entry written against it — across all entries, with no status filter. Each `GiftCardEntry` records its owning `gift_card_id`, an `entry_type` of `SPEND`, `REFUND`, or `TOPUP`, a signed `delta_cents` (negative for a spend, positive for a refund or top-up), and a `related_booking_id` that points at the booking that caused the entry or is null for a manual top-up. The ledger is append-only; entries are never mutated.

A manager may manually top up a card by submitting an `amount_cents` of at least 1, which appends a `TOPUP` entry and recomputes `balance_cents`; if the card was `DEPLETED` and the top-up drives its balance above 0, its `status` returns to `ACTIVE`. A top-up attempted on a `VOID` card is rejected with `ERR_INVALID_STATE`. A manager may also void a card, moving its `status` to `VOID` from either `ACTIVE` or `DEPLETED`, after which the balance is frozen and no further spend, refund, or top-up is accepted; voiding a card that is already `VOID` is rejected with `ERR_INVALID_STATE`. A void is permitted only when no `CONFIRMED` booking currently holds an outstanding `SPEND` draw against the card (a `CONFIRMED` booking whose `gift_card_id` is this card and whose `gift_card_applied_cents` is greater than 0); if such an authorized draw exists, the void is rejected with `ERR_INVALID_STATE`. This outstanding-draw check is evaluated before the optimistic-concurrency check on `expected_gift_card_version`, so an outstanding draw surfaces `ERR_INVALID_STATE` even when the submitted version is also stale. As described in the confirm and cancel flows, the card's `status` also moves automatically between `ACTIVE` and `DEPLETED` as its balance is driven to 0 by a spend or restored above 0 by a refund.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or that modify an existing resource (including state transitions and lifecycle actions) return `200 OK`. The request payloads, side effects, and validation rules for each action are specified in Section 3; the table below records only the method, path, purpose, and authorized roles. List endpoints accept the `limit` and `offset` query parameters described in Section 2.3 together with the foreign-key filters noted in their descriptions.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue | PlatformAdmin |
| GET | `/venues/{venue_id}` | Read a venue | PlatformAdmin, VenueManager, GameMaster, Customer |
| POST | `/rooms` | Create a room under a venue | VenueManager |
| GET | `/rooms/{room_id}` | Read a room | PlatformAdmin, VenueManager, GameMaster, Customer |
| GET | `/rooms` | List rooms (filter by `venue_id`) | PlatformAdmin, VenueManager, GameMaster, Customer |
| POST | `/rooms/{room_id}/retire` | Retire a room | VenueManager |
| POST | `/pricing-rules` | Create a pricing rule for a room | VenueManager |
| GET | `/pricing-rules/{pricing_rule_id}` | Read a pricing rule | PlatformAdmin, VenueManager, Customer |
| GET | `/pricing-rules` | List pricing rules (filter by `venue_id`, `room_id`) | PlatformAdmin, VenueManager, Customer |
| POST | `/game-masters` | Create a game master under a venue | VenueManager |
| GET | `/game-masters/{game_master_id}` | Read a game master | PlatformAdmin, VenueManager, GameMaster |
| GET | `/game-masters` | List game masters (filter by `venue_id`) | PlatformAdmin, VenueManager, GameMaster |
| POST | `/game-masters/{game_master_id}/set-status` | Set a game master AVAILABLE or OFF_DUTY | VenueManager |
| POST | `/time-slots` | Create a bookable time slot for a room | VenueManager |
| GET | `/time-slots/{slot_id}` | Read a time slot | PlatformAdmin, VenueManager, GameMaster, Customer |
| GET | `/time-slots` | List time slots (filter by `room_id`, `venue_id`, `assigned_game_master_id`, `booking_id`, `status`) | PlatformAdmin, VenueManager, GameMaster, Customer |
| POST | `/time-slots/{slot_id}/block` | Block an OPEN slot | VenueManager |
| POST | `/time-slots/{slot_id}/unblock` | Unblock a BLOCKED slot | VenueManager |
| POST | `/time-slots/{slot_id}/close` | Permanently close an OPEN or BLOCKED slot | VenueManager |
| POST | `/customers` | Register a customer | PlatformAdmin, Customer |
| GET | `/customers/{customer_id}` | Read a customer | PlatformAdmin, VenueManager, Customer |
| POST | `/bookings` | Create a booking by grabbing an OPEN slot | Customer |
| GET | `/bookings/{booking_id}` | Read a booking | PlatformAdmin, VenueManager, GameMaster, Customer |
| GET | `/bookings` | List bookings (filter by `customer_id`, `time_slot_id`, `gift_card_id`, `room_id`, `venue_id`, `lifecycle_status`) | PlatformAdmin, VenueManager, GameMaster, Customer |
| POST | `/bookings/{booking_id}/participants` | Add a participant to a DRAFT/CONFIRMED booking | Customer |
| GET | `/participants/{participant_id}` | Read a participant | PlatformAdmin, VenueManager, GameMaster, Customer |
| GET | `/participants` | List participants (filter by `booking_id`) | PlatformAdmin, VenueManager, GameMaster, Customer |
| POST | `/participants/{participant_id}/sign-waiver` | Sign a participant's waiver | Customer |
| POST | `/participants/{participant_id}/revoke-waiver` | Revoke a participant's waiver | Customer |
| POST | `/participants/{participant_id}/mark-present` | Mark a participant present | GameMaster |
| POST | `/bookings/{booking_id}/confirm` | Confirm a DRAFT booking | Customer |
| POST | `/bookings/{booking_id}/reschedule` | Reschedule a CONFIRMED booking onto a new slot | Customer |
| POST | `/bookings/{booking_id}/check-in` | Check in the present group | GameMaster |
| POST | `/bookings/{booking_id}/complete` | Complete a CHECKED_IN booking | GameMaster |
| POST | `/bookings/{booking_id}/no-show` | Mark a CONFIRMED booking NO_SHOW | GameMaster |
| POST | `/bookings/{booking_id}/cancel` | Cancel a DRAFT/CONFIRMED booking | Customer |
| POST | `/gift-cards` | Issue a gift card under a venue | VenueManager |
| GET | `/gift-cards/{gift_card_id}` | Read a gift card | PlatformAdmin, VenueManager, Customer |
| GET | `/gift-cards` | List gift cards (filter by `venue_id`) | PlatformAdmin, VenueManager, Customer |
| POST | `/gift-cards/{gift_card_id}/top-up` | Top up a gift card balance | VenueManager |
| POST | `/gift-cards/{gift_card_id}/void` | Void a gift card | VenueManager |
| GET | `/gift-card-entries/{entry_id}` | Read a gift card ledger entry | PlatformAdmin, VenueManager, Customer |
| GET | `/gift-card-entries` | List gift card ledger entries (filter by `gift_card_id`, `related_booking_id`) | PlatformAdmin, VenueManager, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SLOT_VERSION` | 412 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AGE_REQUIREMENT_NOT_MET` | 409 |
| `ERR_WAIVER_NOT_SIGNED` | 409 |
| `ERR_GROUP_SIZE_INVALID` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_NO_GAMEMASTER_AVAILABLE` | 409 |
| `ERR_NO_SHOW_LIMIT_REACHED` | 409 |
| `ERR_GIFT_CARD_UNUSABLE` | 409 |
| `ERR_OUTSIDE_OPERATING_HOURS` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_ROOM_RETIRED` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
