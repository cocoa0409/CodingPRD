# Karaoke Private Room Booking API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Karaoke Private Room Booking API, a back-of-house platform that lets a karaoke venue sell time inside its private singing rooms while keeping the floor, the song queue, the bar tab, and the cash drawer in agreement at every moment. A venue is more than a list of rooms: it is a pricing engine that knows when the evening rush begins and ends, a deposit policy that protects against no-shows, a food-and-beverage minimum that keeps each room profitable, and a settlement process that reconciles what a party was quoted at booking time against what they actually consumed once the lights come up.

The platform serves three distinct constituencies whose interests must be balanced. A guest wants to reserve a room of the right size for the right hours, confirm it with a deposit, line up songs to sing, order drinks, and pay a fair, predictable bill. The front desk wants to seat arriving parties, run the in-room queue, void mistaken orders, and close out sessions — billing honestly for the minutes a room was actually occupied, including any overtime past the booked window. The venue's management wants to define the room inventory and its size tiers, set the hourly rates and peak surcharges, publish group packages, and run the nightly sweeps that expire abandoned holds and flag the parties that never arrived. The central design tension this API resolves is the gap between a forward-looking **quote** — what a booking is expected to cost if everything runs to plan — and a chronological **settlement** — what it actually costs once real check-in and close timestamps are known. Getting that reconciliation exactly right, while never double-booking a room and never losing track of a deposit, is the heart of the system.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity in which they are acting. The system recognizes exactly three roles, spelled precisely as follows: `VenueManager`, `FrontDesk`, and `Customer`. If either header is missing, or if `X-User-Role` carries a value that is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The three roles divide responsibility along ownership lines. When `X-User-Role` is `VenueManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server treats it as a floor-management credential and does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may use it to authorize floor operations but does not match it against any stored record. When `X-User-Role` is `Customer`, by contrast, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`. A `Customer` may act only on reservations whose `customer_id` equals their own `X-User-ID`, and on the child resources (queue entries, food-and-beverage orders, extensions) of those reservations. An attempt by a `Customer` to operate on a reservation they do not own is rejected with `ERR_FORBIDDEN`.

A `VenueManager` configures the venue and its catalog: creating venues, room types, rooms, and group packages, and toggling room maintenance are operations only a `VenueManager` may perform. A `FrontDesk` operator runs the floor: checking parties in, closing and settling sessions, playing and skipping queued songs, and voiding food-and-beverage lines are operations only a `FrontDesk` operator may perform. A `Customer` books and manages their own reservations: creating, confirming, cancelling, and extending a reservation, queuing songs, cancelling their own queued songs, and placing food-and-beverage orders are all operations a `Customer` may perform on their own bookings, and a `FrontDesk` operator may perform the same booking-side operations on a customer's behalf. Both `VenueManager` and `FrontDesk` may add songs to the catalog, set the venue clock, and run the ops sweep. Registering a customer may be done by a `Customer` (self-registration) or by `FrontDesk`. All read operations (every `GET`) are available to all three roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it may range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page; when omitted it defaults to 0.

Unless an endpoint explicitly states otherwise, all list responses return their resources sorted by creation timestamp (`created_at`) in ascending order. The one deliberate exception is the queue listing, which is ordered by playback position as described in the queue narrative; even there, the underlying tie-break among entries of equal priority is `created_at` ascending.

Every list response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it serves as identity only and is never supplied by the client. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the moment of the last mutation; it is refreshed on every mutation, including mutations driven by cascades from another resource. The `version` field is an integer that starts at 1 when the resource is created and increases by exactly 1 on each mutation; it underpins the optimistic concurrency mechanism described in §2.7.

Two entities are deliberately leaner. A `Song` and a `Payment` are immutable once written: each carries only an `id` and a `created_at`, and neither has an `updated_at` field nor a `version` field. A `Song` is a catalog record that is never edited in place, and a `Payment` is an append-only ledger event; for both, the absence of `updated_at` and `version` is intentional and must not be synthesized. All other entities — `Venue`, `RoomType`, `Room`, `GroupPackage`, `Customer`, `Reservation`, `Extension`, `QueueEntry`, and `FbOrder` — carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Cascading Consistency and Hierarchical Mutation

The system maintains immediate, strong consistency across the relationships that bind reservations to their rooms, queues, orders, and payments. When a reservation transition produces a secondary effect on another entity — a room becoming occupied, a queue being force-terminated, a customer's strike count advancing, or a payment being appended — that secondary effect is applied within the same operation, not deferred. Every entity that is mutated as part of such a cascade has its own `updated_at` refreshed and its own `version` incremented by 1, exactly as if it had been mutated directly. A single close operation, for example, advances the reservation's `version`, advances the freed room's `version`, and advances the `version` of each queue entry it skips.

When a request targets a child resource that is addressed only through its own identifier (for example, a queue entry or a food-and-beverage order), the server still resolves the chain of ownership up to the venue before applying any business rule, validating the existence of each referenced resource left to right. Resources are validated in this order: venue, then room or room type or package or customer, then reservation, then the child resource itself. The first identifier in that chain that does not resolve to an existing in-scope resource causes the request to be rejected with `ERR_NOT_FOUND` before any later validation runs.

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are integers denominated in cents — there are no fractional-cent fields exposed by the API. Internally, however, several calculations work in exact rational arithmetic before producing a final cent figure, and the order of rounding is significant. The governing rule for room pricing is **sum-then-round**: exact per-minute or per-segment costs are accumulated at full precision first, and the accumulated total is rounded exactly once, at the end, to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up to the larger cent). Per-minute base rates are derived by dividing the hourly rate by 60 and are never rounded early; rounding occurs only on the final sum. The deposit figure is likewise produced by a single round-half-up step. Threshold-driven amounts that are already integer-on-integer (such as the food-and-beverage shortfall, which subtracts one integer cent figure from another) need no rounding.

### 2.7. Optimistic Concurrency Control

Two write operations in this system guard against acting on a stale view of a parent resource, because both can legitimately race against other writers contending for the same room timeline.

The first is reservation creation. Booking a room occupies a half-open time interval on that room, and a previously created booking on the same room may legitimately occupy an overlapping interval; a second create issued against a stale picture of the room must be refused rather than allowed to double-book. Accordingly, a reservation-create request must carry `expected_room_version`, a non-optional field holding the `version` of the target `Room` that the client last read. If that value does not match the room's current `version` — because, since the client read it, a booking was created against the room, the room was taken out of service, or it was otherwise mutated — the create is rejected with `ERR_STALE_ROOM_VERSION` (HTTP 412). This protects the client from overwriting a room timeline it has not observed.

The second is extension creation. Extending a reservation lengthens its booked interval and must re-run overlap detection against the room's latest timeline; a stale reservation view (one where another extension has already moved the end time, or the reservation has since been checked in) would compute against an outdated interval. An extension-create request must therefore carry `expected_reservation_version`, a non-optional field holding the `version` of the target `Reservation` that the client last read. If that value does not match the reservation's current `version`, the extension is rejected with `ERR_STALE_RESERVATION_VERSION` (HTTP 412), and no `Extension` row is written. No other endpoint takes a version field; only these two creates participate in optimistic concurrency control.

### 2.8. The Order of Validation

When several checks apply to a single request, they are evaluated in a fixed priority order so that the most fundamental failures surface first and a deeper failure is never masked by a shallower one. The order is as follows. First, authentication: the `X-User-Role` and `X-User-ID` headers must be present and the role must be known, failing which the request is rejected with `ERR_UNAUTHENTICATED`. Second, authorization: the acting role must be permitted for the operation (and, for a `Customer`, must own the targeted reservation), failing which the request is rejected with `ERR_FORBIDDEN`. Third, existence: every path- and body-referenced resource must exist in scope, validated left to right as described in §2.5, failing which the request is rejected with `ERR_NOT_FOUND`. Fourth, request well-formedness: required fields must be present, enums must be valid, `slot_end_utc` must be strictly after `slot_start_utc`, and numeric fields must lie within their declared ranges, failing which the request is rejected with `ERR_INVALID_REQUEST`. Fifth, state: the target resource must be in a state from which the requested transition is legal, failing which the request is rejected with `ERR_INVALID_STATE`.

After those five gates, the remaining business rules apply in their own priority order. Sixth comes the optimistic-concurrency check on `expected_room_version` or `expected_reservation_version` against the parent's current `version`, yielding the stale-version errors of §2.7. Seventh come the timing-window checks for confirm, check-in, and close, which yield `ERR_TIMING_WINDOW`. Eighth is the capacity check, which yields `ERR_CAPACITY_EXCEEDED`. Ninth is the room/room-type matching check, which yields `ERR_ROOM_TYPE_MISMATCH`. Tenth is the room double-booking overlap check, which yields `ERR_ROOM_DOUBLE_BOOKED`. Eleventh is the extension overlap check, which yields `ERR_EXTENSION_CONFLICT`. Twelfth is the room-availability check for maintenance, which yields `ERR_ROOM_NOT_AVAILABLE`. Thirteenth is the head-of-queue check for playback, which yields `ERR_NOT_QUEUE_HEAD`. A defensive catch-all, `ERR_VALIDATION`, covers any residual field-level type error not caught by a more specific 422. This ordering is normative: where two checks could both fire on the same request, the lower-numbered one is the one that is returned.

### 2.9. Peak Windows, Rates, and the Venue Clock

Each venue defines a single peak window in local time, expressed as two minute-of-day values. The `peak_start_minute` is the minute of the day (in the range 0 through 1439 inclusive) at which the peak window opens, and the `peak_end_minute` is the minute of the day (no greater than 1439) at which it closes. The window is half-open: a minute counts as peak when its local minute-of-day is at or after `peak_start_minute` and strictly before `peak_end_minute`. In this version the window never wraps past midnight, so `peak_start_minute` must be strictly less than `peak_end_minute`. Peak and off-peak classification of any reservation's minutes is computed against the venue's local calendar, identified by the venue's IANA `timezone` (for example, `America/Los_Angeles`). A minute that falls inside the peak window is charged at the room size's base rate multiplied by the venue's `peak_multiplier`, which must be at least 1.0; off-peak minutes are charged at the plain base rate.

Because all timing windows (confirmation deadlines, grace periods, no-show sweeps, overage thresholds) depend on the current moment, the system maintains a venue-scoped logical clock that can be set explicitly for deterministic operation. Setting the clock writes the supplied `now_utc` as the server's notion of `current_utc` for that venue's timing checks. The ops sweep, described in §3, reads this same clock to decide which holds have expired and which confirmed bookings have become no-shows.

## 3. Business Logic & Workflows

### 3.1. Configuring the Venue, Its Sizes, and Its Rooms

Everything begins with a **venue**, created by a `VenueManager`. A venue is created with a display `name` and an IANA `timezone`, together with the two peak-window boundaries `peak_start_minute` and `peak_end_minute`. The remaining policy levers are optional and fall back to documented defaults: the `peak_multiplier` defaults to 1.5 (and may never be below 1.0); the `deposit_pct`, the fraction of the quoted room subtotal collected as a deposit at confirmation, defaults to 0.2 and must be greater than 0 and at most 1; the `cancellation_cutoff_hours`, the number of hours before a slot's start within which cancelling a confirmed booking forfeits the deposit, defaults to 24 and must be zero or greater; the `grace_minutes`, the number of minutes after a slot's start during which a confirmed party may still check in before the sweep marks it a no-show, defaults to 15 and must be zero or greater; and the `overage_grace_minutes`, the number of minutes a checked-in session may run past its booked end before overage billing begins, defaults to 10 and must be zero or greater. A new venue is born at `version` 1.

A `VenueManager` then defines the venue's size tiers as **room types**. A room type belongs to a venue (identified on creation by `venue_id`) and carries a `name` drawn from the fixed set `SMALL`, `MEDIUM`, `LARGE`, and `VIP`; a `capacity` giving the maximum party the size accommodates, which must be at least 1; a `base_hourly_rate_cents`, the off-peak hourly rate in cents for rooms of this size, which must be zero or greater; an optional `fb_minimum_cents`, the required food-and-beverage spend floor for any reservation on this size, which defaults to 0 and must be zero or greater; and an optional `active` flag, defaulting to true, that controls whether new reservations may target this size. Physical **rooms** are then created against a size tier: each room is created with its owning `venue_id`, the `room_type_id` of the size it belongs to, and a human `label` such as "Room 3". A room is born `AVAILABLE` at `version` 1, and its `status` is one of `AVAILABLE`, `OCCUPIED`, or `OUT_OF_SERVICE`.

A room's lifecycle on the floor is mostly automatic — occupancy follows from check-in and close (see §3.4) — but maintenance is a manual toggle reserved to a `VenueManager`. The maintenance operation carries a `target` field naming the desired status. Taking a room out of service moves it from `AVAILABLE` to `OUT_OF_SERVICE`, and this is only permitted while the room is `AVAILABLE`; an attempt to take an `OCCUPIED` room out of service is rejected with `ERR_ROOM_NOT_AVAILABLE`. Returning a room to service moves it from `OUT_OF_SERVICE` back to `AVAILABLE` and is only permitted while the room is `OUT_OF_SERVICE`. Either toggle increments the room's `version` by 1.

### 3.2. Group Packages, Customers, and the Song Catalog

A `VenueManager` may publish **group packages** that replace hourly pricing with a flat deal for a particular size. A package is created with its owning `venue_id`, a display `name` such as "Birthday Bash", a `flat_price_cents` (the flat room charge that replaces hourly pricing for the included block, which must be zero or greater), an `included_hours` value (the hours of room time the flat price covers, which must be greater than 0; time beyond it is billed as overage), the `included_room_type_id` naming the size the package is sold for, an optional `included_fb_credit_cents` (a food-and-beverage credit counting toward the size's food-and-beverage minimum, defaulting to 0 and zero or greater), and an optional `active` flag defaulting to true. A package, like the other configuration entities, starts at `version` 1.

A **customer** record is registered with a `full_name`, a contact `email` (which must be unique), and a contact `phone`. A customer's `id` is the value carried in `X-User-ID` when that customer acts. Each customer tracks a `no_show_strikes` count, a computed field that begins at 0 and is incremented whenever one of their reservations ends in `NO_SHOW`; it equals the total number of that customer's reservations currently in `NO_SHOW`.

The **song catalog** is a per-venue list. A `VenueManager` or a `FrontDesk` operator adds a song with its owning `venue_id`, a `title`, a performing `artist`, a `duration_seconds` (track length in seconds, which must be at least 1), and a `language` drawn from the fixed set `EN`, `JP`, `KR`, `ZH`, `ES`, and `OTHER`. A song is a thin, immutable catalog record: it carries only `id` and `created_at`, and that creation timestamp doubles as the tie-break key when two queued songs share a priority.

### 3.3. Booking a Room: Holds, Quotes, and Deposits

A guest, or a `FrontDesk` operator acting for one, books a room by creating a **reservation**. The create payload names the `venue_id`, the `room_id` of the physical room to occupy, the `customer_id` of the booking party, the `party_size`, the half-open interval boundaries `slot_start_utc` and `slot_end_utc`, and the `expected_room_version` required for the concurrency check of §2.7; it may optionally name a `group_package_id` to book the slot as a package rather than à la carte. A reservation is born in `HELD` status at `version` 1. At create time the server copies the room's size tier into the reservation's denormalized `room_type_id`, pinning the `base_hourly_rate_cents`, `fb_minimum_cents`, and `capacity` that will govern this booking even if the tier is later edited. The reservation also records its owning `venue_id` and, once known, the lifecycle timestamps `checked_in_at` and `actual_end_utc` (both null until the relevant transition occurs).

Several gates guard a create. The `party_size` must be at least 1 and must not exceed the capacity of the reservation's room type; a party larger than the room allows is rejected with `ERR_CAPACITY_EXCEEDED`. The chosen room must actually belong to the requested room type, that room type must be active, and — when a package is named — the package's `included_room_type_id` must equal the room's `room_type_id`; any of these mismatches is rejected with `ERR_ROOM_TYPE_MISMATCH`. The requested interval `[slot_start_utc, slot_end_utc)` must not overlap any active reservation on the same room, where "active" means a reservation in `HELD`, `CONFIRMED`, or `CHECKED_IN`; intervals are half-open, so two bookings that merely touch (one ending exactly when the next begins) do not overlap and are both allowed, while any genuine overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`. The interval itself must be well-formed, with `slot_end_utc` strictly after `slot_start_utc`. Upon a successful create the server computes a forward-looking preview of `quoted_room_subtotal_cents` and `deposit_cents` so the guest can see the price, though no money changes hands while the booking is merely `HELD`.

Confirmation is the act of committing to a held booking and putting down a deposit. Confirming requires the reservation to be in `HELD` status; confirming anything else is rejected with `ERR_INVALID_STATE`. It also requires that the slot has not already started — the current venue time must be strictly before `slot_start_utc`, and confirming a slot whose start has already passed is rejected with `ERR_TIMING_WINDOW`. The party-versus-capacity check applies here too, again yielding `ERR_CAPACITY_EXCEEDED` if violated. A successful confirm transitions the reservation `HELD → CONFIRMED`, recomputes `quoted_room_subtotal_cents`, recomputes `deposit_cents` as that subtotal multiplied by the venue's `deposit_pct` and rounded half-up to whole cents, appends a deposit payment event (a `Payment` of kind `DEPOSIT` whose `amount_cents` equals `deposit_cents`), and increments the reservation's `version` by 1.

**Computing the quote.** The `quoted_room_subtotal` is forward-looking: it prices the booked interval `[slot_start_utc, slot_end_utc)` as if the whole booking runs exactly as planned, with peak and off-peak split computed in the venue's local calendar. When the reservation carries a `group_package_id`, the quote is simply the package's `flat_price_cents`; the package's included hours and any potential overage are not charged at quote time, because the forward-looking quote assumes the party stays within plan. When there is no package (the à la carte case), the server first counts the whole minutes in the booked interval as `booked_minutes`, then counts how many of those minutes have a local minute-of-day inside the half-open peak window `[peak_start_minute, peak_end_minute)` as the peak minutes, with the remaining minutes treated as off-peak. The per-minute base rate is the room size's `base_hourly_rate_cents` divided by 60, kept as an exact value with no early rounding. The off-peak cost is the off-peak minute count times that per-minute base; the peak cost is the peak minute count times that per-minute base times the venue's `peak_multiplier`. The two exact segment costs are summed first, and only that sum is rounded — once, half-up, to whole cents — to yield `quoted_room_subtotal_cents`. The input to this calculation is the single booked interval of this reservation alone: no extensions and no actual run time enter the quote.

### 3.4. Seating the Party: Check-In, the Session, and Close

When the party arrives, a `FrontDesk` operator checks them in. Check-in requires the reservation to be in `CONFIRMED` status (otherwise `ERR_INVALID_STATE`), requires the current venue time to be no later than `slot_start_utc` plus the venue's `grace_minutes` — that is, within the grace window — failing which the attempt is rejected with `ERR_TIMING_WINDOW`, and requires the assigned room to be `AVAILABLE` rather than `OCCUPIED` or `OUT_OF_SERVICE`. A successful check-in transitions the reservation `CONFIRMED → CHECKED_IN`, stamps `checked_in_at` with the current venue time, drives the room from `AVAILABLE → OCCUPIED` (incrementing the room's `version` by 1), and increments the reservation's `version` by 1.

Closing a session is where the real bill is computed. Closing requires the reservation to be in `CHECKED_IN` status (otherwise `ERR_INVALID_STATE`) and requires the supplied `actual_end_utc` to be at or after `checked_in_at`; a close whose `actual_end_utc` falls before check-in is rejected with `ERR_TIMING_WINDOW`. A successful close transitions the reservation `CHECKED_IN → CLOSED`, records `actual_end_utc`, recomputes the settled room subtotal, recomputes the food-and-beverage figures, computes the final total, appends a settlement payment, force-skips any songs still waiting in the queue, frees the room, and increments the reservation's `version` by 1. Concretely: every still-`PENDING` `QueueEntry` on the reservation cascades to `SKIPPED` (each such entry having its `play_order` neighborhood recomputed and its own `version` incremented), the room moves `OCCUPIED → AVAILABLE` (incrementing the room's `version`), and a `Payment` of kind `SETTLEMENT` is appended whose `amount_cents` equals the reservation's `final_total_cents`.

**Computing the settlement.** The `settled_room_subtotal` is chronological: it prices the actually occupied interval, from `checked_in_at` up to `actual_end_utc`, walked minute by minute in time order, so a session that drifted into or out of the peak window is charged for the real minutes it used rather than the planned ones — this is precisely why settled can diverge from quoted. The billable interval runs from `checked_in_at` (inclusive) to `actual_end_utc` (exclusive). Overage is defined by a threshold: the first minutes past the booked end are free, specifically the minutes from `slot_end_utc` up to `slot_end_utc` plus the venue's `overage_grace_minutes`; only minutes at or after that overage threshold attract the overage surcharge. Walking each whole minute of the occupied interval, the base per-minute rate is again `base_hourly_rate_cents` divided by 60 held exactly; if the minute's local minute-of-day lies inside `[peak_start_minute, peak_end_minute)` the rate is multiplied by the venue's `peak_multiplier`; and if the minute is at or after the overage threshold the rate is additionally multiplied by the overage multiplier of 2.0. Each minute's exact adjusted rate is accumulated. For an à la carte session, the accumulated exact total is rounded once, half-up, to whole cents to give `settled_room_subtotal_cents`. For a package session, the package covers a number of minutes equal to the package's `included_hours` times 60 (rounded to whole minutes), measured from `checked_in_at`; those first covered minutes are charged nothing, only the minutes beyond them are billed (still adjusted for peak and overage exactly as above), and the subtotal is the package's `flat_price_cents` plus the round-half-up of the accumulated exact rates for the uncovered minutes. A session whose `actual_end_utc` is at or before `slot_end_utc` plus `overage_grace_minutes` incurs no overage multiplier at all (pure peak/off-peak on the actual minutes); a session that runs past that point has its minutes from the overage threshold onward billed at the overage multiplier on top of peak/off-peak.

**Food and beverage and the final total.** During a checked-in session, food and drink are ordered as line items (see §3.6). At close, the server recomputes the consumed total and any shortfall. The consumed amount `fb_consumed_cents` is the sum of `line_total_cents` across the reservation's food-and-beverage orders that are still `PLACED` (voided lines are excluded). The package credit is the package's `included_fb_credit_cents` when a package is attached, and 0 otherwise; the effective food-and-beverage figure is the consumed amount plus that credit. The required floor is the reservation room type's `fb_minimum_cents`. The shortfall is charged only when the effective figure is strictly below the required floor: when the effective figure is below the floor, `fb_shortfall_cents` is the floor minus the effective figure; when the effective figure equals or exceeds the floor, `fb_shortfall_cents` is 0. An effective figure exactly equal to the floor means the minimum is precisely met and the shortfall is 0. Finally, `final_total_cents` is the settled room subtotal plus the consumed food-and-beverage amount plus the food-and-beverage shortfall, less the already-collected `deposit_cents` (the deposit is credited against the bill), with the result never allowed to fall below 0 — if that arithmetic would be negative, the final total is 0.

### 3.5. Extending a Live Booking

A guest who wants more time, or a `FrontDesk` operator acting for them, applies an **extension** to push the reservation's end out. The extension payload supplies the proposed `new_slot_end_utc`, which must be strictly after the reservation's current `slot_end_utc`, and the `expected_reservation_version` for the concurrency check. The number of whole minutes added, recorded as `added_minutes`, is the difference between `new_slot_end_utc` and the prior `slot_end_utc` expressed in whole minutes. Before anything is written, the server re-runs overlap detection on the room over just the newly claimed window — the half-open interval from the old end up to the new end — and if that window collides with a later active reservation on the same room (adjacency, where one ends exactly as the other begins, remaining allowed), the extension is rejected with `ERR_EXTENSION_CONFLICT`. The optimistic-concurrency check of §2.7 also applies: a mismatched `expected_reservation_version` yields `ERR_STALE_RESERVATION_VERSION` and writes nothing.

An extension is recorded only on success. When it succeeds, an `Extension` row is persisted in `APPLIED` status at `version` 1, the reservation's `slot_end_utc` is advanced to `new_slot_end_utc`, the forward-looking `quoted_room_subtotal_cents` and `deposit_cents` previews are recomputed against the lengthened interval, and the reservation's `version` is incremented by 1. When the extension is rejected for a conflict or a stale version, the request fails with the appropriate HTTP error and no `Extension` row exists — the only status an `Extension` ever holds is `APPLIED`.

### 3.6. The Song Queue

Inside a session, songs are lined up as **queue entries**. A guest (on their own reservation) or a `FrontDesk` operator queues a song by naming the `song_id` and, optionally, a `priority`; a lower priority number is sung sooner, and when omitted the priority defaults to 100. A queue entry is born `PENDING` at `version` 1, and its `status` is one of `PENDING`, `PLAYED`, `SKIPPED`, or `CANCELLED`. The playback position, `play_order`, is a computed 1-based rank: among all `PENDING` entries on the reservation, the entries are sorted by `priority` ascending and then, for entries of equal priority, by `created_at` ascending — the creation timestamp is the deterministic tie-break, never the `id` — and positions 1, 2, 3, and so on are assigned in that order. The queue listing surfaces entries in this `play_order`. Whenever the queue changes — an entry created, played, skipped, or cancelled, or force-terminated by a reservation cascade — `play_order` is recomputed across the remaining `PENDING` entries.

A `FrontDesk` operator plays songs from the head of the queue. Playing requires the entry to be `PENDING`, requires the parent reservation to be `CHECKED_IN`, and requires the entry to be the current head — that is, the entry whose `play_order` equals 1 among the `PENDING` entries. Playing an entry that is not the head is rejected with `ERR_NOT_QUEUE_HEAD`; playing a non-`PENDING` entry, or playing when the parent session is not `CHECKED_IN`, is rejected with `ERR_INVALID_STATE`. A successful play moves the entry `PENDING → PLAYED`, recomputes `play_order` for the remaining `PENDING` entries, and increments the entry's `version` by 1. A `FrontDesk` operator may also skip a `PENDING` entry, moving it `PENDING → SKIPPED`; and a guest may remove their own `PENDING` entry, moving it `PENDING → CANCELLED`. Both skip and cancel require the entry to be `PENDING`, both recompute `play_order` over the remaining `PENDING` entries, and both increment the entry's `version` by 1. The system itself force-terminates `PENDING` entries through reservation cascades, as described next.

### 3.7. Cancellation, Abandonment, and the Nightly Sweep

A held or confirmed booking can be cancelled by its owning `Customer` (or by `FrontDesk`). Cancelling a `HELD` reservation simply transitions it `HELD → CANCELLED`; because no deposit is ever collected at the held stage, no payment is appended, and any `PENDING` queue entries on the reservation cascade to `CANCELLED`, with the reservation's `version` incremented by 1. Cancelling a `CONFIRMED` reservation transitions it `CONFIRMED → CANCELLED` and turns on the deposit policy: if the current venue time is at or before `slot_start_utc` minus the venue's `cancellation_cutoff_hours` (that is, the guest is cancelling outside the cutoff window), the deposit is returned by appending a `Payment` of kind `REFUND` whose `amount_cents` equals `deposit_cents`; otherwise the guest is cancelling inside the cutoff and forfeits the deposit, recorded by appending a `Payment` of kind `FORFEIT` whose `amount_cents` equals `deposit_cents`. In either confirmed-cancellation case, all `PENDING` queue entries cascade to `CANCELLED` and the reservation's `version` is incremented by 1.

Some bookings are simply abandoned, and the **ops sweep** cleans them up. A `VenueManager` or `FrontDesk` operator runs the sweep for a venue, and it reads the venue clock to make two kinds of decision. First, any reservation still `HELD` whose `slot_start_utc` has already passed (the current venue time is strictly after `slot_start_utc`) — a hold that was never confirmed — is expired: it transitions `HELD → EXPIRED`, its `PENDING` queue entries cascade to `CANCELLED`, and its `version` is incremented by 1. No payment is involved, since a held booking never collected a deposit. Second, any reservation still `CONFIRMED` past the grace window — where the current venue time is strictly after `slot_start_utc` plus the venue's `grace_minutes`, and the party never checked in — is treated as a no-show: it transitions `CONFIRMED → NO_SHOW`, the deposit is forfeited by appending a `Payment` of kind `FORFEIT` whose `amount_cents` equals `deposit_cents`, the booking party's `no_show_strikes` is incremented by 1 (and that count, by definition, equals the number of that customer's reservations now in `NO_SHOW`), its `PENDING` queue entries cascade to `CANCELLED`, and its `version` is incremented by 1. Both `EXPIRED` and `NO_SHOW`, like `CLOSED` and `CANCELLED`, are terminal states from which no further transition is possible.

### 3.8. Food and Beverage Orders and the Payment Ledger

Food and drink are tracked as **food-and-beverage orders** placed against a reservation. A guest (on their own booking) or a `FrontDesk` operator places an order line by supplying a `description` such as "2x Lager", a `unit_price_cents` (per-unit price, zero or greater), and a `quantity` (number of units, at least 1). The line is born `PLACED` at `version` 1, its `line_total_cents` is computed as `unit_price_cents` multiplied by `quantity`, and the reservation's `fb_consumed_cents` and `fb_shortfall_cents` previews are recomputed so the running food-and-beverage position is visible. A `FrontDesk` operator may void a line that is `PLACED`, moving it `PLACED → VOID`; voiding excludes the line from `fb_consumed_cents`, recomputes the reservation's food-and-beverage previews, and increments the order's `version` by 1. Voiding a line that is not `PLACED` is rejected with `ERR_INVALID_STATE`. An order's `status` is one of `PLACED` or `VOID`.

Every consequential money event is written to an append-only **payment** ledger scoped to a reservation. A `Payment` records its `reservation_id`, a `kind` drawn from `DEPOSIT`, `SETTLEMENT`, `REFUND`, and `FORFEIT`, and a signed-positive `amount_cents` for the event, ordered by `created_at` as the ledger's append order. Deposits are written at confirmation, settlements at close, and refunds or forfeits at cancellation and no-show as described above; the ledger is read-only through the API and is never edited after the fact, which is why a payment carries only `id` and `created_at` and has neither `updated_at` nor `version`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that read a resource, or that modify or transition an existing resource (including the lifecycle transitions, maintenance toggles, voids, queue actions, clock setting, and the ops sweep), return `200 OK`. The table below lists only the method, path, purpose, and authorized roles for each endpoint; the request and response shapes, side effects, and trigger conditions are specified in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/venues` | Create a venue with pricing/policy config | VenueManager |
| GET    | `/venues/{venue_id}` | Get venue config | VenueManager, FrontDesk, Customer |
| POST   | `/venues/{venue_id}/_clock/set` | Set the venue's current UTC clock for timing windows | VenueManager, FrontDesk |
| POST   | `/venues/{venue_id}/_ops/run` | Run the ops sweep: expire stale holds, no-show overdue confirmations | VenueManager, FrontDesk |
| POST   | `/room-types` | Create a room size tier with hourly rate and F&B minimum | VenueManager |
| GET    | `/room-types` | List room types, optionally filtered by venue | VenueManager, FrontDesk, Customer |
| GET    | `/room-types/{room_type_id}` | Get a room type | VenueManager, FrontDesk, Customer |
| POST   | `/rooms` | Create a physical room of a given size | VenueManager |
| GET    | `/rooms` | List rooms, optionally filtered by venue and/or room type | VenueManager, FrontDesk, Customer |
| GET    | `/rooms/{room_id}` | Get a room (read its version for OCC on booking) | VenueManager, FrontDesk, Customer |
| POST   | `/rooms/{room_id}/maintenance` | Toggle a room between available and out-of-service | VenueManager |
| POST   | `/group-packages` | Create a group package (flat price, included hours, F&B credit) | VenueManager |
| GET    | `/group-packages` | List group packages, optionally filtered by venue and/or included room type | VenueManager, FrontDesk, Customer |
| GET    | `/group-packages/{group_package_id}` | Get a group package | VenueManager, FrontDesk, Customer |
| POST   | `/customers` | Register a customer | Customer, FrontDesk |
| GET    | `/customers/{customer_id}` | Get a customer (incl. no-show strikes) | Customer, FrontDesk, VenueManager |
| POST   | `/songs` | Add a song to the venue catalog | VenueManager, FrontDesk |
| GET    | `/songs` | List/search the song catalog, filter by venue and/or language | VenueManager, FrontDesk, Customer |
| GET    | `/songs/{song_id}` | Get a song | VenueManager, FrontDesk, Customer |
| POST   | `/reservations` | Create a held reservation for a time block on a room | Customer, FrontDesk |
| GET    | `/reservations` | List reservations, filtered by venue, room, customer, package, room type, or status | VenueManager, FrontDesk, Customer |
| GET    | `/reservations/{reservation_id}` | Get a reservation (version, computed totals) | VenueManager, FrontDesk, Customer |
| POST   | `/reservations/{reservation_id}/confirm` | Confirm a held reservation; collect deposit | Customer, FrontDesk |
| POST   | `/reservations/{reservation_id}/check-in` | Check in a confirmed reservation within grace; occupy the room | FrontDesk |
| POST   | `/reservations/{reservation_id}/close` | Close a checked-in session; settle room, F&B minimum, overage | FrontDesk |
| POST   | `/reservations/{reservation_id}/cancel` | Cancel a held or confirmed reservation; refund or forfeit deposit | Customer, FrontDesk |
| POST   | `/reservations/{reservation_id}/extensions` | Extend a reservation's end time (OCC, overlap re-checked) | Customer, FrontDesk |
| GET    | `/extensions` | List extensions, filtered by reservation | VenueManager, FrontDesk, Customer |
| GET    | `/extensions/{extension_id}` | Get an extension | VenueManager, FrontDesk, Customer |
| POST   | `/reservations/{reservation_id}/queue` | Queue a song in a reservation session | Customer, FrontDesk |
| GET    | `/queue-entries` | List queue entries, filtered by reservation and/or song, optionally by status | VenueManager, FrontDesk, Customer |
| GET    | `/queue-entries/{queue_entry_id}` | Get a queue entry | VenueManager, FrontDesk, Customer |
| POST   | `/queue-entries/{queue_entry_id}/play` | Mark the head-of-queue song played (parent must be checked in) | FrontDesk |
| POST   | `/queue-entries/{queue_entry_id}/skip` | Skip a pending queue entry | FrontDesk |
| DELETE | `/queue-entries/{queue_entry_id}` | Cancel (remove) a pending queue entry | Customer, FrontDesk |
| POST   | `/reservations/{reservation_id}/fb-orders` | Add a food & beverage order line toward the F&B minimum | Customer, FrontDesk |
| GET    | `/fb-orders` | List F&B orders, filtered by reservation, optionally by status | VenueManager, FrontDesk, Customer |
| GET    | `/fb-orders/{fb_order_id}` | Get an F&B order | VenueManager, FrontDesk, Customer |
| POST   | `/fb-orders/{fb_order_id}/void` | Void an F&B order line (excludes it from consumed F&B) | FrontDesk |
| GET    | `/payments` | List the append-only payment ledger, filtered by reservation | VenueManager, FrontDesk, Customer |
| GET    | `/payments/{payment_id}` | Get a payment ledger entry | VenueManager, FrontDesk, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ROOM_VERSION` | 412 |
| `ERR_STALE_RESERVATION_VERSION` | 412 |
| `ERR_TIMING_WINDOW` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_ROOM_TYPE_MISMATCH` | 422 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_EXTENSION_CONFLICT` | 409 |
| `ERR_ROOM_NOT_AVAILABLE` | 409 |
| `ERR_NOT_QUEUE_HEAD` | 409 |
| `ERR_VALIDATION` | 422 |
