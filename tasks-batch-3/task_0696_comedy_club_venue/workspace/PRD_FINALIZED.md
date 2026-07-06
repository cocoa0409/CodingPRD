# Comedy Club Venue API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Comedy Club & Live-Show Venue platform, a back-office system that runs a small live-comedy room end to end. The venue programs a calendar of shows, lays out seating that mixes general-admission standing room, numbered reserved seats, and table-and-server service, and sells tickets across price tiers — each carrying a per-seat item or drink minimum that the floor must collect on the night. Around that core the platform also negotiates performer contracts through an offer-and-counter loop, manages comp and guest-list seats hosted by performers, supports private buyouts that take a whole show off public sale, and closes each night with a box-office settlement that splits gross revenue between the house and the performers.

Two characteristics make the domain demanding. First, a single reservation carries two independent status dimensions at once — where it sits in the booking lifecycle and where it sits in the money lifecycle — and these evolve on their own schedules. Second, the night is full of cascading consequences: cancelling a show unwinds reservations, releases tables, drops contracts, and voids tickets in one stroke, while a single GA sale can flip a show to sold-out and a single cancellation can flip it back. The system must keep all of these derived facts consistent at every step, settle money to the cent, and reject any action attempted out of turn.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, the response envelope, pagination, and the cross-cutting principles that govern consistency, money, concurrency, and timing across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity they are acting in. A request missing either header is rejected with `ERR_MISSING_AUTH`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_ROLE_FORBIDDEN`.

The system recognizes exactly five roles, spelled `Booker`, `BoxOffice`, `FloorManager`, `Patron`, and `Performer`. A `Booker` programs the calendar: venues, shows, sections, ticket tiers, performers, lineup contracts, and private buyouts. A `BoxOffice` operator sells, collects payment, checks parties in, cancels, and exchanges reservations, and converts guest-list comps into reservations. A `FloorManager` runs the room: registering servers, assigning servers and tables, seating parties, recording consumption, marking no-shows, and opening and finalizing settlements. A `Patron` is the ticket buyer acting on their own reservations. A `Performer` acts on their own lineup contracts and their own guest list.

Four of these roles carry an opaque identity, and one is entity-backed. When `X-User-Role` is `Booker`, `BoxOffice`, `FloorManager`, or `Patron`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The single exception that ties identity to data is the `Patron`: although the patron identifier is opaque, a reservation records the acting buyer's identifier in its `patron_id` field, and ownership checks compare that field to `X-User-ID`. When `X-User-Role` is `Performer`, `X-User-ID` is the `id` of the acting `Performer` entity; ownership checks on any resource that references a `Performer` compare the resource's performer foreign-key field to `X-User-ID`. Concretely, a `Patron` may act only on a `Reservation` whose `patron_id` equals their `X-User-ID`, and a `Performer` may counter only a `LineupSlot` whose `performer_id` equals their `X-User-ID`; a violation of either ownership rule is rejected with `ERR_NOT_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single page returns; it defaults to 10, may be no smaller than 1, and no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless an endpoint explicitly states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and the Money Convention

Every primary resource is addressed by an `id`, which is a server-minted UUID carrying no type prefix and serving as identity only. Most resources also expose three further system-managed fields: `created_at`, an ISO 8601 UTC timestamp with millisecond precision recording when the resource was first created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that arrive only as a side-effect cascade; and `version`, an integer that begins at 1 and increases by 1 on every mutation, used for optimistic concurrency control. These fields are present on the `Venue`, `Show`, `SeatingSection`, `SeatTable`, `Performer`, `LineupSlot`, `TicketTier`, `Reservation`, `GuestListEntry`, `Server`, `PrivateEvent`, and `Settlement` resources.

The `Ticket` resource is the lone exception. A ticket is immutable once issued, so it carries only an `id` and a `created_at` timestamp; it has neither an `updated_at` field nor a `version` field. Its `created_at` doubles as the tie-break that orders ticket scanning.

All monetary amounts in the system are integer cents in the venue's `settlement_currency`, and field names ending in `_cents` are always whole-cent integers. Where a calculation multiplies integers — a per-seat price by a party size, for instance — no rounding is needed and the result is exact. Where a calculation multiplies a fractional rate by a cent amount, such as a deposit percentage or the house cut, the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero, upward). Refund arithmetic never produces a negative number: any refund computation that would fall below zero is floored at zero.

### 2.5. Hierarchical Consistency and Automatic State Propagation

The platform keeps derived state consistent without requiring the client to touch every affected resource. Many operations therefore mutate more than the resource named in the request, and each such secondary mutation independently refreshes that resource's `updated_at` and increments its `version`. When a GA sale fills the last seat of a section, the show itself transitions to `SOLD_OUT` as a server-driven consequence; when a later cancellation frees a seat, the show transitions back from `SOLD_OUT` to `ON_SALE`. When a settlement is finalized, its show advances to `SETTLED` and the venue's posture is recomputed. These propagations are part of the same logical operation that triggered them.

A few derived fields are maintained continuously rather than transitioned. A show's `ga_sold_count` is the running sum of `party_size` across that show's reservations whose section is a GA section and whose `booking_status` is `BOOKED`, `SEATED`, or `CHECKED_IN`; it is recomputed whenever a reservation is created, cancelled, exchanged, or otherwise leaves those states. A show's `is_private` flag reads true exactly while a `PrivateEvent` in `HELD` or `CONFIRMED` status references it, and reverts to false once no such buyout remains. A server's `assigned_table_count` is the number of `SeatTable` rows whose `assigned_server_id` is that server and whose `status` is not `RETIRED`; it is recomputed whenever a table is assigned, released, retired, or its reservation is cancelled. A venue's `posture` is `OPEN` in normal operation, `RECONCILING` while any of the venue's shows is in `SETTLING`, and `CLOSED` only when the venue has been manually closed.

### 2.6. Nested Resource Retrieval and Validation Ordering

Several endpoints address resources through a nested path — a section under a show under a venue, a table under a section under a show under a venue. The system validates path identifiers strictly left to right and rejects the request at the first identifier that does not resolve to an existing resource, returning `ERR_NOT_FOUND`. A request for a table beneath a non-existent show fails on the show before the table is ever consulted. The same left-to-right existence rule applies to identifiers carried in request bodies.

Across every endpoint, validations are applied in a fixed priority order so that the same request always fails for the same reason. The order is: first, that both authentication headers are present (`ERR_MISSING_AUTH`); then, that the declared role is permitted for the operation (`ERR_ROLE_FORBIDDEN`); then, that every referenced resource exists (`ERR_NOT_FOUND`); then, ownership for `Patron` and `Performer` actions (`ERR_NOT_OWNER`); then, request-shape validity — required fields present and well-typed, enum values legal, and the numeric domain rules below (`ERR_INVALID_REQUEST`); then, that the target resource is in a legal state for the operation (`ERR_INVALID_STATE`); then, timing against the logical clock (`ERR_TIMING_NOT_ALLOWED`); then, the venue and show posture gate (`ERR_POSTURE_BLOCKED`); and finally the operation-specific business rules described throughout §3. A check earlier in this order always masks a violation that would be caught later.

### 2.7. The Logical Clock

The system keeps a logical clock rather than reading wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to real time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant. Every time-gated rule in the system — when a settlement may open, when a no-show may be recorded, and whether a patron cancellation falls inside the late window — is evaluated against this logical clock, never against the host's real time.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of a parent resource, and both express the guard as a mandatory version field on the request.

The first is table assignment. A request to assign a `SeatTable` to a reservation must carry `expected_table_version`, holding the `version` of the target `SeatTable` that the client last observed. If another writer has advanced that table's `version` since the client read it — because the table was just assigned to another party or retired — the assignment is rejected with `ERR_STALE_VERSION` and HTTP status 412, since the `AVAILABLE` state the client believed in no longer holds. The second is contract signing. A request to sign a `LineupSlot` must carry `expected_lineup_slot_version`, holding the `version` of the target `LineupSlot` that the client last observed. If a counter or a revised offer has advanced that slot's `version` since the client read it, the fee the signer believes they are freezing is stale, and the signing is rejected with `ERR_STALE_VERSION` and HTTP status 412. Both fields are non-optional on their respective operations. No other endpoint takes a version field; endpoints not named here perform no version check.

### 2.9. Posture and Sale-Window Gating

Beyond per-resource state, two coarse gates govern whether new business may be written at all. When a venue's `posture` is `CLOSED`, no new show and no new reservation may be created at that venue; such an attempt is rejected with `ERR_POSTURE_BLOCKED`. Independently, a reservation may only be created against a show that is actively sellable — that is, a show whose `status` is `ON_SALE` or `SOLD_OUT`. A show in `DRAFT`, `PRIVATE_HELD`, `CANCELLED`, `SETTLING`, or `SETTLED` is not sellable: the sellable-state check itself rejects a reservation against a `DRAFT`, `PRIVATE_HELD`, `CANCELLED`, `SETTLING`, or `SETTLED` show with `ERR_INVALID_STATE`. The posture gate then runs after that sellable-state check has passed, blocking a reservation with `ERR_POSTURE_BLOCKED` when the show has since moved into a settling or settled posture or its venue is closed.

## 3. Business Logic & Workflows

### 3.1. Programming the Venue and Its Shows

A `Booker` opens the system by creating a **Venue**, supplying its `name`, its `settlement_currency` (an ISO currency code such as USD), and optionally its `house_fee_pct` — the house's cut of gross box-office, a fraction between 0 and 1 inclusive that defaults to 0.20 and is applied once at settlement. A freshly created venue takes `posture` `OPEN` and `version` 1. A `Booker` may later close a venue, which drives its `posture` to `CLOSED` and blocks any further show or reservation creation there.

Within an open venue, a `Booker` programs a **Show** in `DRAFT`, supplying a `title`, a `starts_at` instant, an `ends_at` instant that must be strictly after `starts_at`, and optionally a `doors_buffer_minutes` value (default 30) that reserves the room for turnover before the show begins. The show's `venue_id` is taken from the path. Before the show is persisted, the system checks for room conflicts: the window running from `doors_buffer_minutes` before `starts_at` through `ends_at` must not overlap the equivalent window of any other non-`CANCELLED` show at the same venue, or the creation is rejected with `ERR_SHOW_TIME_CONFLICT`. A show progresses through the statuses `DRAFT`, `ON_SALE`, `PRIVATE_HELD`, `SOLD_OUT`, `CANCELLED`, `SETTLING`, and `SETTLED`, with `SETTLED` and `CANCELLED` terminal.

Publishing a show advances it from `DRAFT` to `ON_SALE`, and a `Booker` may do so only when the show already has at least one seating section and at least one ticket tier, when no `PrivateEvent` in `HELD` or `CONFIRMED` references the show, and when the venue's `posture` is not `CLOSED`; once published, reservations may be created against it. Cancelling a show is a `Booker` action permitted from `DRAFT`, `ON_SALE`, `PRIVATE_HELD`, or `SOLD_OUT` — but not once the show is `SETTLING` or `SETTLED`. Cancellation is the system's broadest cascade, and is detailed in §3.8.

Read access to shows includes a list capability filtered by `venue_id` or by `status`, which is how a reader recovers the shows belonging to a venue; each filter is optional and the list is paginated.

### 3.2. Laying Out Seating: Sections and Tables

A `Booker` lays out a show by adding one or more **SeatingSection** rows, each with a `kind` and a `label`. The `kind` is one of `GA` (general standing room), `RESERVED` (numbered seats that are head-counted exactly like GA but carry no table or server), or `TABLE` (table-and-server service). The section's `show_id` is taken from the path. A capacity-tracked section — one whose `kind` is `GA` or `RESERVED` — requires a `ga_capacity` head count; a `TABLE` section must omit `ga_capacity` entirely, leaving it null. Supplying `ga_capacity` for a `TABLE` section, or omitting it for a `GA` or `RESERVED` section, is a request-shape violation rejected with `ERR_INVALID_REQUEST`. Sections may be listed filtered by `show_id`.

Under a `TABLE` section, a `Booker` or a `FloorManager` creates **SeatTable** rows. Each table carries a `table_number` — a human label that must be unique within its section among tables that are not `RETIRED` — a `seats` count that must be at least 1, and an optional `min_items_per_seat` that sets the per-seat item-and-drink minimum for parties seated there, defaulting to the venue-wide value of 2. The table's `section_id` comes from the path, and creating a table beneath a section whose `kind` is not `TABLE` is rejected with `ERR_WRONG_SECTION_KIND`. A new table starts `AVAILABLE`, with `assigned_server_id` null and its `status` drawn from `AVAILABLE`, `HELD`, `OCCUPIED`, and `RETIRED` (the last terminal). Tables may be listed filtered by `section_id` or by `assigned_server_id`. A `FloorManager` may retire a table only while it is `AVAILABLE` with no active hold; retiring it sets `status` to `RETIRED` and, if a server was assigned, recomputes that server's `assigned_table_count`.

### 3.3. Staffing the Floor: Servers and Server Assignment

A `FloorManager` registers a **Server** with a `name` and an optional `max_tables` cap (at least 1, default 4); a new server takes `version` 1. The server's `assigned_table_count` is a derived count of the non-`RETIRED` tables currently pointing at it. Assigning a server to a table records the supplied `server_id` as the table's `assigned_server_id` and recomputes that server's `assigned_table_count`. The assignment is refused if it would push the server's `assigned_table_count` above its `max_tables`, in which case the request is rejected with `ERR_SERVER_OVERLOADED`. The same overload ceiling is re-checked when a table is later assigned to a reservation, since that too leans on the table's server.

### 3.4. Pricing: Ticket Tiers and the Item Minimum

A `Booker` prices a show by creating **TicketTier** rows, each naming the `section_id` it sells into, a `name` (such as "GA Advance" or "VIP Table"), a per-seat `price_cents`, and an optional `min_items_override`. The tier's own `show_id` is taken from the path, and the referenced section must belong to that same show; a tier whose section lives under a different show is rejected with `ERR_CROSS_SHOW_REFERENCE`. The `min_items_override`, when set, replaces the default per-seat item minimum whenever the tier is used. Tiers may be listed filtered by `show_id` or by `section_id`.

The per-seat item minimum follows a strict precedence, taking the first value that is set: the tier's `min_items_override` if present; otherwise, once a table has been assigned to a `TABLE`-section party, that table's `min_items_per_seat`; otherwise the venue default of 2 items per seat. Each required item is valued at a fixed unit price of 1000 cents (ten dollars) of consumption. The minimum a party owes, recorded as `minimum_due_cents`, is therefore the chosen per-seat item count multiplied by 1000 cents and then multiplied by the reservation's `party_size`. A comp reservation whose originating guest-list entry had its minimum waived owes a per-seat minimum of zero, and thus a `minimum_due_cents` of zero.

Because the minimum depends on the assigned table, it is computed in two passes. At reservation creation, before any table is known, the minimum is estimated from the tier override if present and otherwise from the venue default of 2 — the table's own per-seat figure is not yet visible. After a table is assigned to a `TABLE`-section reservation, the minimum is recomputed with that table's `min_items_per_seat` taking its place in the precedence chain; a table whose per-seat minimum is higher than the estimate therefore raises `minimum_due_cents` at assignment time. This recomputed figure is the amount the floor must collect.

### 3.5. Booking and Pricing a Reservation

A `BoxOffice` operator or a `Patron` creates a **Reservation** against a sellable show by supplying its `show_id`, the `section_id` booked into, the `tier_id` (the priced tier used), the `patron_id`, the `party_size` (at least 1), and an optional `is_comp` flag (default false). A reservation begins with `booking_status` `BOOKED` and `settlement_status` `UNCOLLECTED`. Its `tier_id` and `section_id` must belong to the same `show_id`, or the creation is rejected with `ERR_CROSS_SHOW_REFERENCE`. A reservation may target a show only while that show is `ON_SALE` or `SOLD_OUT`, per §2.9, and a `Patron`-created reservation records the acting buyer in `patron_id`.

At creation the system computes the reservation's `ticket_charge_cents`: for a comp reservation it is zero, and otherwise it is the tier's `price_cents` multiplied by `party_size` — an exact integer product needing no rounding. It also computes the pre-seating estimate of `minimum_due_cents` per §3.4. The reservation also carries an `items_consumed_cents` running tab that begins at 0, a `refunded_cents` total that begins at 0, and a nullable `table_id` that is null for GA and RESERVED parties and is set only when a `TABLE` party is later assigned a table.

For a capacity-tracked section, the booking competes for headroom. The section's sold count is the sum of `party_size` over that show's reservations in the same section whose `booking_status` is `BOOKED`, `SEATED`, or `CHECKED_IN`; the section's remaining capacity is its `ga_capacity` minus that sold count. A reservation is admitted only when its `party_size` is less than or equal to the remaining capacity; a `party_size` strictly greater than the remaining capacity is rejected with `ERR_SECTION_SOLD_OUT`. When a GA reservation brings the show's `ga_sold_count` up to a GA section's `ga_capacity` so that no GA section has remaining capacity, the show transitions from `ON_SALE` to `SOLD_OUT`, after which further GA reservation creation is rejected with `ERR_SECTION_SOLD_OUT`. Reservations may be read individually and listed filtered by `show_id`, `section_id`, `tier_id`, `table_id`, or `patron_id`.

### 3.6. Seating the Room: Tables, Service, Collection, and Consumption

Once a `TABLE`-section reservation exists, a `FloorManager` assigns it a table by supplying a `table_id` together with the OCC field `expected_table_version` described in §2.8. The chosen table must sit in the same section as the reservation, must already have a server assigned, and must have at least as many `seats` as the reservation's `party_size`. A table whose section does not match, or an attempt to assign a table to a non-`TABLE` reservation, is rejected with `ERR_WRONG_SECTION_KIND`; a table with no `assigned_server_id` is rejected with `ERR_NO_SERVER_ASSIGNED`; a table whose `seats` fall short of `party_size` is rejected with `ERR_TABLE_TOO_SMALL`; and a table that is not currently `AVAILABLE` — already `HELD`, `OCCUPIED`, or `RETIRED`, including the case where another reservation of the same show already holds it — is rejected with `ERR_TABLE_UNAVAILABLE`. Because a served reservation leans on the table's server, the assignment is also refused with `ERR_SERVER_OVERLOADED` if it would carry that server past its `max_tables`. A successful assignment moves the table from `AVAILABLE` to `HELD`, sets the reservation's `table_id`, recomputes `minimum_due_cents` in its post-seating form, and advances the table's `version`.

Seating a party advances its `booking_status` from `BOOKED` to `SEATED` and, as a server-driven consequence, moves its held table from `HELD` to `OCCUPIED`; this is a `FloorManager` action available only on a `TABLE`-section reservation that already holds a table, while its show is `ON_SALE` or `SOLD_OUT`.

A `BoxOffice` operator collects ticket payment, advancing `settlement_status` from `UNCOLLECTED` to `TICKET_PAID`; this requires the reservation's `booking_status` to be `BOOKED`, `SEATED`, or `CHECKED_IN`, and it issues one **Ticket** per seat in the `ISSUED` scan state. Each ticket records the `reservation_id` it belongs to, a `seat_label` such as "GA" or "T4-S2", and a `scan_state` drawn from `ISSUED`, `SCANNED`, and `VOID`. A `BoxOffice` operator checks a party in, advancing `booking_status` to `CHECKED_IN` from `BOOKED` or `SEATED` while the show is `ON_SALE` or `SOLD_OUT`, but only once the reservation's `settlement_status` is `TICKET_PAID` or the reservation is a comp; check-in moves that reservation's tickets from `ISSUED` to `SCANNED` in ascending `created_at` order.

A `FloorManager` records consumption by submitting a `delta_cents` amount, which is added to the reservation's `items_consumed_cents`. When the running `items_consumed_cents`, after applying the delta, reaches or exceeds the reservation's `minimum_due_cents`, the `settlement_status` advances from `TICKET_PAID` to `MINIMUM_MET`, and the shortfall against the minimum is no longer billable. These two status dimensions are independent: a reservation may already be `TICKET_PAID` while still `BOOKED`, and a `CHECKED_IN` reservation may still owe its minimum.

### 3.7. Cancellation, Exchange, No-Show, and the Refund Rule

A reservation can leave the booking lifecycle three ways, and each computes a refund into `refunded_cents`. The refund starts from a recoverable base: the `ticket_charge_cents` counts toward the base whenever the reservation's `settlement_status` is `TICKET_PAID` or `MINIMUM_MET`, and the collected minimum — the smaller of `items_consumed_cents` and `minimum_due_cents` — counts toward the base only when `settlement_status` is `MINIMUM_MET`; the base is the sum of those two parts.

A `BoxOffice` operator or the owning `Patron` may cancel a reservation while the show is not yet `SETTLED`, from `booking_status` `BOOKED`, `SEATED`, or `CHECKED_IN`. A patron-initiated cancel keeps a cancellation fee unless it lands well before doors: if the logical clock is at or before `starts_at` minus 120 minutes, the full base is refunded; otherwise the refund is the base less a flat cancellation fee of 1500 cents, floored at zero. Cancelling sets `booking_status` to `CANCELLED`, sets `refunded_cents` accordingly, and advances `settlement_status` to `REFUNDED`. It also voids every ticket of the reservation that is currently `ISSUED` or `SCANNED` (moving them to `VOID`); releases the held table back to `AVAILABLE` and recomputes its server's `assigned_table_count` if a `table_id` was set; reverts any `CONVERTED` guest-list entry pointing at this reservation back to `REVOKED`; and recomputes the show's `ga_sold_count`, which may auto-transition the show from `SOLD_OUT` back to `ON_SALE`.

A `BoxOffice` operator or the owning `Patron` may exchange a `BOOKED` reservation for a different tier and section by supplying a `target_section_id` and a `target_tier_id`, available while the show is `ON_SALE` or `SOLD_OUT` and only when the target tier and section exist and the target section has capacity. The old row moves to `booking_status` `EXCHANGED` (terminal) and `settlement_status` `REFUNDED`, and a brand-new `Reservation` is created in `BOOKED` for the target tier carrying the same `party_size`. On exchange the refund is a credit of the difference: the old base minus the ticket charge of the target tier (the target tier's `price_cents` times `party_size`), floored at zero so it is never negative. The exchange voids the old row's `ISSUED` or `SCANNED` tickets, releases the old row's `table_id` if any, and recomputes `ga_sold_count` for both the old and the new section. Because the endpoint is addressed by the old reservation's `{reservation_id}` and the exchange modifies that row, the operation returns the modified old row — now `EXCHANGED`/`REFUNDED` with `refunded_cents` set to the credited difference — as the response resource (per §2.2), not the newly created `BOOKED` row.

A `FloorManager` marks a no-show only once the logical clock has reached `starts_at` plus `doors_buffer_minutes`; before that instant the action is rejected with `ERR_TIMING_NOT_ALLOWED`. A no-show may be marked from `BOOKED`, `SEATED`, or `CHECKED_IN`, sets `booking_status` to `NO_SHOW`, retains the ticket charge with no refund so `refunded_cents` is zero, and releases any held table back to `AVAILABLE`. In all three exits, the move to `settlement_status` `REFUNDED` (where it applies) is itself the system-driven settlement-side transition recorded on the row.

### 3.8. Cancelling a Whole Show

When a `Booker` cancels a show, the system unwinds the night in one cascade. Every reservation for the show whose `booking_status` is `BOOKED`, `SEATED`, or `CHECKED_IN` is moved to `CANCELLED`, each computing a full refund into `refunded_cents` with no cancellation fee deducted — the patron is made whole on the recoverable base — and each advancing `settlement_status` to `REFUNDED`. Each such cancelled reservation that held a `SeatTable` releases it back to `AVAILABLE`. Every `LineupSlot` for the show whose `contract_status` is `OFFERED`, `COUNTERED`, or `SIGNED` is moved to `DROPPED`. Any `PrivateEvent` on the show that is `HELD` or `CONFIRMED` is moved to `CANCELLED`, with its deposit retained per §3.10. A show may be cancelled only when it is not `SETTLING` or `SETTLED`.

### 3.9. Performers, Lineups, and Contract Negotiation

A `Booker` registers a **Performer** with a `stage_name`, an `email`, and a `standard_fee_cents` (the default booking fee the performer asks for); a new performer takes `version` 1, and its `id` equals the `X-User-ID` that performer uses when acting in the system. A `Booker` then offers a **LineupSlot** that links a `show_id` and a `performer_id`, naming a `slot_order` (the lineup position, lower goes on stage first, unique per show among non-`DROPPED` slots), a `role` drawn from `HOST`, `OPENER`, `FEATURE`, and `HEADLINER`, and the `offered_fee_cents` currently on the table. A new slot starts with `contract_status` `OFFERED` and `counter_rounds` 0; its `agreed_fee_cents` stays null until the contract is signed. Lineup slots may be read individually and listed filtered by `show_id` or `performer_id`.

The contract then runs a bounded negotiation loop. The performer who owns the slot may counter the offer, supplying a `counter_fee_cents`; this advances `contract_status` from `OFFERED` to `COUNTERED`, overwrites `offered_fee_cents` with the countered figure, and increases `counter_rounds` by 1. A `Booker` may revise the offer in reply, supplying a `new_offered_fee_cents`; this returns `contract_status` from `COUNTERED` to `OFFERED` and overwrites `offered_fee_cents`, reopening the loop. The loop is capped at three rounds: a counter or a revise-offer attempted once `counter_rounds` has reached 3 is rejected with `ERR_COUNTER_LIMIT_REACHED`. A counter is permitted only to the slot's own performer, identified by matching `X-User-ID` to `performer_id`.

Signing freezes the deal: a `Booker` or the `Performer` may sign a slot that is `OFFERED` or `COUNTERED`, provided the show is in `DRAFT`, `ON_SALE`, `PRIVATE_HELD`, or `SOLD_OUT`. Signing advances `contract_status` to `SIGNED`, copies the current `offered_fee_cents` into `agreed_fee_cents` (frozen), and is guarded by the OCC rule of §2.8 through `expected_lineup_slot_version`. A `Booker` may instead drop a slot from `OFFERED` or `COUNTERED`, moving `contract_status` to `DROPPED` and freeing its `slot_order` for reuse on the show. Both `SIGNED` and `DROPPED` are terminal.

### 3.10. Guest List and Comps

A `Booker` or a `Performer` adds a **GuestListEntry** for a show by naming the `show_id`, the `host_performer_id` who put the guest on the list, the `guest_name`, the `party_size` (at least 1), and an optional `minimum_waived` flag (default false) that waives the item minimum for the comp. A new entry starts `LISTED`, with a null `reservation_id`; its `status` is one of `LISTED`, `CONVERTED`, and `REVOKED`. Guest-list entries may be listed filtered by `show_id`, `host_performer_id`, or `reservation_id`.

A `BoxOffice` operator converts a `LISTED` entry into a comp reservation by supplying a `section_id` and a `tier_id` that belong to the same show, while the show is `ON_SALE` or `SOLD_OUT`. Conversion moves `status` to `CONVERTED`, creates a comp `Reservation` (with `is_comp` true) carrying over the entry's `party_size`, links the new reservation back through `reservation_id`, and waives the minimum when `minimum_waived` is set. Converting or revoking an entry that is not `LISTED` (for convert) is rejected with `ERR_GUEST_LIST_NOT_LISTED`. A `Booker` or `Performer` may revoke an entry from `LISTED` or `CONVERTED`, moving it to `REVOKED`; if a comp reservation was linked and still active, revoking also cancels that reservation. The reverse linkage also holds: when a linked comp reservation is cancelled, its `CONVERTED` guest-list entry reverts to `REVOKED` (its non-terminal nature is what makes this revert possible).

### 3.11. Private Buyouts

A `Booker` takes a `DRAFT` show off public sale by creating a **PrivateEvent**, naming the `show_id` being bought out, the `client_name`, the `buyout_fee_cents` (a flat fee replacing per-ticket revenue), and an optional `deposit_pct` (a fraction between 0 and 1 inclusive, default 0.25) taken as a non-refundable deposit when the buyout is held. A buyout may be created against a `DRAFT` show that has no reservation in `BOOKED`, `SEATED`, or `CHECKED_IN`. Creating it starts the buyout `HELD`, computes its `deposit_cents` as the `deposit_pct` multiplied by `buyout_fee_cents` rounded half-up to whole cents, and as a system consequence moves the show from `DRAFT` to `PRIVATE_HELD` (so `is_private` reads true and public reservation creation is blocked). A private event's `status` is one of `HELD`, `CONFIRMED`, and `CANCELLED`. Private events may be read and listed filtered by `show_id`.

A `Booker` confirms a held buyout while the underlying show is `PRIVATE_HELD`, moving `status` to `CONFIRMED` while the show stays `PRIVATE_HELD` and excluded from public sale. A `Booker` may cancel a buyout from `HELD` or `CONFIRMED`; cancellation moves `status` to `CANCELLED`, retains the `deposit_cents` (it is non-refundable even on cancellation), and — if this was the only `HELD` or `CONFIRMED` buyout on the show — moves the show from `PRIVATE_HELD` back to `ON_SALE` with `is_private` reverting to false.

### 3.12. Box-Office Settlement

After a show has ended, a `FloorManager` opens a **Settlement** for it by naming the `show_id`. Opening is allowed only once the logical clock has reached the show's `ends_at` — an attempt before then is rejected with `ERR_SHOW_NOT_ENDED` — and only when no `OPEN` settlement already exists for the show, a duplicate being rejected with `ERR_SETTLEMENT_EXISTS`. Opening starts the settlement `OPEN`, moves the show to `SETTLING`, recomputes the venue's `posture` to `RECONCILING`, and blocks any new reservation for that show. A settlement's `status` is `OPEN` or `FINALIZED`. Settlements may be read and listed filtered by `show_id`.

A `FloorManager` finalizes the settlement, which freezes its money fields and advances the show to `SETTLED`. Finalization is allowed only while the show is `SETTLING`, and only once every minimum has been resolved: if any reservation for the show is `CHECKED_IN` and `TICKET_PAID` while its `items_consumed_cents` is still below its `minimum_due_cents`, finalization is blocked with `ERR_MINIMUM_NOT_MET`. The settlement aggregates only the show's reservations that attended or forfeited — those whose `booking_status` is `CHECKED_IN` or `NO_SHOW` — excluding cancelled and exchanged rows. From those included reservations, `gross_ticket_cents` is the sum of `ticket_charge_cents` over the rows whose `settlement_status` is `TICKET_PAID` or `MINIMUM_MET`, and `gross_minimum_cents` is the sum, over the rows whose `settlement_status` is `MINIMUM_MET`, of the smaller of each row's `items_consumed_cents` and its `minimum_due_cents`. The `buyout_cents` is the `buyout_fee_cents` of a `CONFIRMED` `PrivateEvent` on the show, or zero if there is none.

The gross box-office is the sum of `gross_ticket_cents`, `gross_minimum_cents`, and `buyout_cents`. The order of operations is pinned: each gross component is computed first and summed into the gross box-office; then the `house_cut_cents` is computed once, as the venue's `house_fee_pct` multiplied by that single gross total, rounded half-up to whole cents — the round happens once on the total, never per reservation, because per-line rounding would drift. The `performer_payout_cents` is the sum of `agreed_fee_cents` over the show's `SIGNED` lineup slots. Finally the `net_to_venue_cents` is the gross box-office minus `house_cut_cents` minus `performer_payout_cents`. For a publicly sold show with no confirmed buyout, `buyout_cents` is zero and the gross is ticket plus minimum revenue only; for a bought-out show, the `buyout_fee_cents` is essentially the whole gross (ticket and minimum streams being near zero) and the house cut is taken on the buyout fee. Finalizing sets `status` to `FINALIZED`, moves the show to `SETTLED`, and recomputes the venue's `posture` — back to `OPEN` if no other show remains `SETTLING`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource — including state transitions and reads — return `200 OK`. The logical-clock setter returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FloorManager, Booker, BoxOffice |
| POST | `/venues` | Create a venue | Booker |
| GET | `/venues/{venue_id}` | Read a venue (includes posture) | Booker, BoxOffice, FloorManager |
| POST | `/venues/{venue_id}/close` | Manually close a venue | Booker |
| POST | `/venues/{venue_id}/shows` | Create a show in DRAFT | Booker |
| GET | `/shows/{show_id}` | Read a show | Booker, BoxOffice, FloorManager |
| GET | `/shows` | List shows, filtered by venue_id or status | Booker, BoxOffice, FloorManager |
| POST | `/venues/{venue_id}/shows/{show_id}/publish` | Publish a DRAFT show to ON_SALE | Booker |
| POST | `/venues/{venue_id}/shows/{show_id}/cancel` | Cancel a show (cascades) | Booker |
| POST | `/venues/{venue_id}/shows/{show_id}/sections` | Create a seating section | Booker |
| GET | `/sections/{section_id}` | Read a seating section | Booker, BoxOffice, FloorManager |
| GET | `/sections` | List sections, filtered by show_id | Booker, BoxOffice, FloorManager |
| POST | `/venues/{venue_id}/shows/{show_id}/sections/{section_id}/tables` | Create a table under a TABLE section | Booker, FloorManager |
| GET | `/tables/{table_id}` | Read a table | Booker, BoxOffice, FloorManager |
| GET | `/tables` | List tables, filtered by section_id or assigned_server_id | Booker, BoxOffice, FloorManager |
| POST | `/tables/{table_id}/assign-server` | Assign a server to a table | FloorManager |
| POST | `/tables/{table_id}/retire` | Retire an AVAILABLE table | FloorManager |
| POST | `/venues/{venue_id}/shows/{show_id}/tiers` | Create a ticket tier | Booker |
| GET | `/tiers/{tier_id}` | Read a ticket tier | Booker, BoxOffice, FloorManager |
| GET | `/tiers` | List tiers, filtered by show_id or section_id | Booker, BoxOffice, FloorManager |
| POST | `/performers` | Register a performer | Booker |
| GET | `/performers/{performer_id}` | Read a performer | Booker, FloorManager, Performer |
| POST | `/lineup-slots` | Offer a lineup slot | Booker |
| GET | `/lineup-slots/{lineup_slot_id}` | Read a lineup slot | Booker, FloorManager, Performer |
| GET | `/lineup-slots` | List lineup slots, filtered by show_id or performer_id | Booker, FloorManager, Performer |
| POST | `/lineup-slots/{lineup_slot_id}/counter` | Performer counters the offer | Performer |
| POST | `/lineup-slots/{lineup_slot_id}/revise-offer` | Booker revises the offer | Booker |
| POST | `/lineup-slots/{lineup_slot_id}/sign` | Sign the contract (OCC-guarded) | Booker, Performer |
| POST | `/lineup-slots/{lineup_slot_id}/drop` | Drop a lineup slot | Booker |
| POST | `/reservations` | Create a reservation | BoxOffice, Patron |
| GET | `/reservations/{reservation_id}` | Read a reservation | BoxOffice, FloorManager, Patron |
| GET | `/reservations` | List reservations, filtered by show_id, section_id, tier_id, table_id, or patron_id | BoxOffice, FloorManager, Patron |
| POST | `/reservations/{reservation_id}/collect-ticket` | Collect ticket payment; issue tickets | BoxOffice |
| POST | `/reservations/{reservation_id}/assign-table` | Assign a table (OCC-guarded) | FloorManager |
| POST | `/reservations/{reservation_id}/seat` | Seat a party | FloorManager |
| POST | `/reservations/{reservation_id}/check-in` | Check a party in; scan tickets | BoxOffice |
| POST | `/reservations/{reservation_id}/record-consumption` | Record items/drinks consumed | FloorManager |
| POST | `/reservations/{reservation_id}/cancel` | Cancel a reservation; refund | BoxOffice, Patron |
| POST | `/reservations/{reservation_id}/exchange` | Exchange a reservation for a new tier/section | BoxOffice, Patron |
| POST | `/reservations/{reservation_id}/no-show` | Mark a no-show | FloorManager |
| GET | `/tickets/{ticket_id}` | Read a single ticket | BoxOffice, FloorManager, Patron |
| GET | `/tickets` | List tickets, filtered by reservation_id | BoxOffice, FloorManager, Patron |
| POST | `/guest-list-entries` | Add a comp/guest-list entry | Booker, Performer |
| GET | `/guest-list-entries/{guest_list_entry_id}` | Read a guest-list entry | Booker, FloorManager, Performer |
| GET | `/guest-list-entries` | List guest-list entries, filtered by show_id, host_performer_id, or reservation_id | Booker, FloorManager, Performer |
| POST | `/guest-list-entries/{guest_list_entry_id}/convert` | Convert a comp to a reservation | BoxOffice |
| POST | `/guest-list-entries/{guest_list_entry_id}/revoke` | Revoke a guest-list entry | Booker, Performer |
| POST | `/servers` | Register a floor server | FloorManager |
| GET | `/servers/{server_id}` | Read a server | FloorManager, Booker |
| POST | `/private-events` | Create a private buyout | Booker |
| GET | `/private-events/{private_event_id}` | Read a private event | Booker, FloorManager |
| GET | `/private-events` | List private events, filtered by show_id | Booker, FloorManager |
| POST | `/private-events/{private_event_id}/confirm` | Confirm a held buyout | Booker |
| POST | `/private-events/{private_event_id}/cancel` | Cancel a buyout | Booker |
| POST | `/settlements` | Open a settlement for a show | FloorManager |
| GET | `/settlements/{settlement_id}` | Read a settlement | FloorManager, Booker |
| GET | `/settlements` | List settlements, filtered by show_id | FloorManager, Booker |
| POST | `/settlements/{settlement_id}/finalize` | Finalize a settlement; cascade Show to SETTLED | FloorManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_CROSS_SHOW_REFERENCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TIMING_NOT_ALLOWED` | 409 |
| `ERR_SHOW_TIME_CONFLICT` | 409 |
| `ERR_POSTURE_BLOCKED` | 409 |
| `ERR_COUNTER_LIMIT_REACHED` | 409 |
| `ERR_SECTION_SOLD_OUT` | 409 |
| `ERR_TABLE_TOO_SMALL` | 409 |
| `ERR_TABLE_UNAVAILABLE` | 409 |
| `ERR_WRONG_SECTION_KIND` | 409 |
| `ERR_SERVER_OVERLOADED` | 409 |
| `ERR_NO_SERVER_ASSIGNED` | 409 |
| `ERR_MINIMUM_NOT_MET` | 409 |
| `ERR_SETTLEMENT_EXISTS` | 409 |
| `ERR_SHOW_NOT_ENDED` | 409 |
| `ERR_GUEST_LIST_NOT_LISTED` | 409 |
| `ERR_INVALID_PAGINATION` | 422 |
</content>
</invoke>
