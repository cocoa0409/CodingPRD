# Private Dining & Supper-Club Experience API — Product Requirements Document

## 1. Introduction

The Private Dining & Supper-Club Experience platform coordinates a boutique hospitality business in which small, curated dinners are sold as ticketed seats rather than open reservations. The product exists to reconcile three concerns that normally live in separate systems: a finite and perishable seat inventory that must be reserved, committed, and released with exact accounting; a scheduling calendar in which chefs and venues cannot be double-booked and require turnover and preparation buffers; and a money workflow in which guests place provisional deposits that later settle into full-price tickets, with tiered refunds when plans change.

A single dinner is modelled as an **Event**, optionally spawned from a recurring **SupperClubSeries** that seeds its defaults. Each Event is staged at a **Venue**, led by a **Chef**, and sold to **Guest** patrons who create **Booking** records against generated **Seat** inventory. Menus are expressed as ordered **MenuCourse** rows carrying wine pairings and allergen tags, and demand beyond capacity is captured through a **WaitlistEntry** queue that is automatically promoted when seats free up. Every movement of money is journalled as an immutable **Payment** ledger entry.

This document is the authoritative specification for the API. It defines the entities and their fields, the parallel state machines that govern Events and Bookings, the deposit/total/refund calculations, the validation ordering and error contract, and the role-based access rules. Amounts are always expressed in integer cents, times are handled against a server-controlled logical clock, and consistency is maintained immediately (synchronously) as each request is processed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the caller is authenticated but the acting role — or the caller's ownership of the target resource — does not permit the operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `PlatformAdmin`, `VenueManager`, `Chef`, `Guest`, and `CustomerService`.

Ownership is tied to `X-User-ID` differently per role:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. `PlatformAdmin` is an operator superset: it seeds catalog records, drives the logical clock, and may perform any Event or Booking operation without an ownership restriction.
- When `X-User-Role` is `VenueManager`, `X-User-ID` is the `id` of the acting `Venue`; ownership checks on any Event compare the Event's `venue_id` to `X-User-ID`. A `VenueManager` may run event operations only for their own venue.
- When `X-User-Role` is `Chef`, `X-User-ID` is the `id` of the acting `Chef`; ownership checks on any Event compare the Event's `chef_id` to `X-User-ID`. A `Chef` owns menu authoring and their own availability only for events assigned to them.
- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`; ownership checks on any Booking or WaitlistEntry compare that resource's `guest_id` to `X-User-ID`. A `Guest` may act only on their own bookings and waitlist entries.
- When `X-User-Role` is `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. `CustomerService` provides operational support and may cancel bookings and withdraw waitlist entries on a guest's behalf, plus perform read operations.

All five roles may perform read (`GET`) operations across the API.

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

The three top-level collection list endpoints — `GET /events`, `GET /bookings`, and `GET /waitlist` — are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the count of items to skip from the front of the result set; when omitted it defaults to 0.

Unless a specific endpoint says otherwise, list endpoints return their resources sorted by `created_at` in ascending order.

List endpoints also accept optional exact-match filter query parameters: `GET /events` by `series_id`, `venue_id`, `chef_id`, and `status`; `GET /bookings` by `event_id`, `guest_id`, and `booking_status`; `GET /waitlist` by `guest_id`, `booking_id`, `event_id`, and `status`; and the nested `GET /events/{id}/seats` and `GET /events/{id}/waitlist` each by `status`. Any unrecognized query parameter is ignored.

Every such paginated list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. The nested sub-resource listings (`GET /events/{id}/seats`, `GET /events/{id}/menu`, `GET /events/{id}/waitlist`, `GET /bookings/{id}/seats`, and `GET /bookings/{id}/payments`) are not paginated: they accept no `limit`/`offset`, return the complete set sorted by `created_at` ascending, and carry no pagination fields in `meta`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of server-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 upon creation and increments by one on every mutation. It is the basis for optimistic concurrency control described in §2.6.

`SupperClubSeries`, `Venue`, `Chef`, `Guest`, `Event`, `Seat`, `MenuCourse`, `Booking`, and `WaitlistEntry` all carry the full set above. The `Payment` ledger entry is the sole exception: a `Payment` is immutable once written, so it carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field.

### 2.5. Monetary Values, Counts, and Rounding

All money is stored and returned as integer numbers of cents; there are no fractional cents anywhere in the system. Fractional deposit percentages and discount rates are applied during computation, but every monetary result is reduced to whole cents using the **round half up** convention (a value exactly halfway between two whole cents rounds up to the larger). Where a calculation both rounds and sums, the pinned order stated in §3 must be followed exactly, because rounding each component before summing can differ from summing before rounding. Derived counts (such as seat tallies) and derived revenue figures are likewise plain integers.

### 2.6. Optimistic Concurrency Control on Repricing

Adjusting an Event's pricing is the one operation guarded by optimistic concurrency control. A repricing request must carry `expected_event_version` holding the `version` the client last observed on the target Event. If `expected_event_version` does not equal the Event's current `version` — meaning another writer has already advanced the Event's `version` since the client read it, superseding the price the client based its request on — the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). Because repricing is not gated on staying in one state (an Event may be repriced repeatedly while `DRAFT` or `SCHEDULED`), a stale `expected_event_version` is the only signal that the client is acting on a price another writer has already replaced. No other endpoint accepts or requires a version field; only repricing performs this check.

### 2.7. Nested Resource Retrieval and Existence Ordering

Many paths address a child through its parent, and several request bodies reference other resources by id. All such identifiers are resolved left-to-right, in the order they appear in the path and then in the body. The first identifier that fails to resolve determines the error: a missing series yields `ERR_SERIES_NOT_FOUND`, a missing venue `ERR_VENUE_NOT_FOUND`, a missing chef `ERR_CHEF_NOT_FOUND`, a missing guest `ERR_GUEST_NOT_FOUND`, a missing event `ERR_EVENT_NOT_FOUND`, a missing seat `ERR_SEAT_NOT_FOUND`, a missing booking `ERR_BOOKING_NOT_FOUND`, a missing menu course `ERR_MENU_COURSE_NOT_FOUND`, and a missing waitlist entry `ERR_WAITLIST_ENTRY_NOT_FOUND`. Every one of these is an HTTP 404. Existence resolution happens after authentication and authorization but before any state or business rule is evaluated.

### 2.8. The Logical Clock

Time-dependent behavior — booking deadlines, event-end checks, and refund tiers — is evaluated against a server-controlled logical clock, never against wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until an operator explicitly advances it; it never silently falls back to real time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant and echoes the new value back in a `now` field. All "now" comparisons in this document refer to this logical clock.

### 2.9. Hierarchical Consistency and Cascades

Events sit at the center of a hierarchy: an Event owns its Seats, MenuCourses, Bookings, and WaitlistEntries, and each Booking owns its Payment ledger. When a parent transition changes the operational reality of its children — an Event being cancelled or completed, a Booking being cancelled or confirmed — the system propagates every dependent change synchronously within the same request, rather than leaving children in a stale state. Each such propagation that mutates a resource refreshes that resource's `updated_at`; every Event lifecycle transition additionally increments the Event's `version` by one. The specific cascades (which children move, in what order, and what money moves with them) are detailed in §3; the governing principle here is that these effects are immediate and complete, never deferred.

### 2.10. Request Validation Order

When more than one rule could reject a request, the checks are evaluated in a fixed precedence so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization and ownership** — the acting role may perform the operation on this resource, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path and body identifier resolves, left-to-right, else the matching `404` from §2.7.
4. **Well-formedness** — required fields present, enum values legal, types correct, else `ERR_VALIDATION` (422). On booking creation, the paired check that `party_size` equals the number of entries in `seat_ids` is enforced at this same tier, failing with `ERR_SEAT_COUNT_MISMATCH` (422).
5. **State legality** — the target Event or Booking is in a status from which the requested transition is legal (`ERR_EVENT_NOT_OPEN`, `ERR_INVALID_EVENT_STATE`, `ERR_EVENT_NOT_ENDED`, `ERR_INVALID_BOOKING_STATE`, `ERR_BOOKING_ALREADY_TERMINAL`, `ERR_WAITLIST_ENTRY_NOT_WAITING`), and the OCC check `ERR_STALE_EVENT_VERSION` (412) for repricing.
6. **Cross-entity readiness** — allergen safety (`ERR_ALLERGEN_CONFLICT`), chef availability at schedule time (`ERR_CHEF_UNAVAILABLE`), and menu presence before opening (`ERR_MENU_REQUIRED`).
7. **Temporal windows** — venue and chef calendar overlaps (`ERR_VENUE_TIME_CONFLICT`, `ERR_CHEF_TIME_CONFLICT`) and the booking-deadline check (`ERR_PAST_BOOKING_DEADLINE`).
8. **Referential seat integrity** — every requested seat belongs to the target event (`ERR_SEAT_NOT_IN_EVENT`, 422).
9. **Availability constraints** — requested seats are actually free (`ERR_SEAT_UNAVAILABLE`), the event is genuinely full before joining a waitlist (`ERR_SEATS_AVAILABLE`), and bring-your-own-bottle counts are permitted (`ERR_BYOB_NOT_ALLOWED`).
10. **Fiscal exactness** — the tendered deposit equals what is owed (`ERR_DEPOSIT_AMOUNT_MISMATCH`, 422).

A lower-numbered tier always decides the outcome before a higher-numbered one is consulted; for example, a mid-flight allergen conflict (tier 6) surfaces before a seat-availability failure (tier 9) on the same booking request.

## 3. Business Logic & Workflows

### 3.1. Seeding the Catalog: Series, Venues, Chefs, and Guests

The catalog is populated by the platform operator. A `SupperClubSeries` captures a recurring dinner concept: it is created with a `name`, a recurrence `cadence` that is one of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, and a culinary `theme`. A series also carries the defaults that later seed its events — `communal_table`, a boolean that defaults to true and expresses whether events default to a shared communal table (true) or a private buyout (false); `default_seat_capacity`, an integer of at least 1; `base_seat_price_cents`, a non-negative per-seat list price; and `default_deposit_pct`, a deposit fraction that must lie between 0 and 1 inclusive. Two beverage defaults round out the series: `byob_allowed`, a boolean defaulting to false, and `corkage_fee_cents`, a non-negative per-bottle fee defaulting to 0.

A `Venue` is created with a `name`, an `address`, a `max_capacity` of at least 1 seats representing the physical ceiling of the room, and a `corkage_policy` that is either `ALLOWED` or `NOT_ALLOWED`, recording whether the room permits outside bottles at all.

A `Chef` is created with a `name` and a cuisine `specialty`. Every chef also carries a `status`, which the system manages and initializes to `AVAILABLE`; a chef may move to `ON_LEAVE` and back. Toggling availability is done by the chef themselves (or the operator) by submitting the desired `status` value; the chef simply advances `AVAILABLE → ON_LEAVE` or `ON_LEAVE → AVAILABLE`.

A `Guest` is registered with a `name`, an `email`, and an optional `phone`.

### 3.2. The Event Lifecycle: Draft, Scheduling, and Seat Generation

A `VenueManager` (or the operator) creates an `Event` in the `DRAFT` state. Creation references the parent records through `series_id`, `venue_id`, and `chef_id`, and supplies a `title`, the seating window `event_start` and `event_end` (where `event_end` must be strictly after `event_start`), and a `booking_deadline` that must be at or before `event_start`. The event fixes its own copies of the commercial terms: `table_mode`, one of `COMMUNAL` or `PRIVATE`; `seat_capacity`, the number of seats to generate, at least 1; `seat_price_cents`, the non-negative per-seat list price; `deposit_pct`, the deposit fraction between 0 and 1 inclusive; and the optional beverage terms `byob_allowed` (default false) and `corkage_fee_cents` (default 0). A freshly created Event exposes derived read-only figures that are all zero until inventory and bookings exist: `confirmed_seat_count`, `available_seat_count`, `gross_deposit_held_cents`, `projected_revenue_cents`, and `realized_revenue_cents` (see §3.8 and §3.9 for how these are derived).

Scheduling an Event advances it `DRAFT → SCHEDULED` and is where seat inventory comes into being. Before the transition is allowed, three preconditions are checked in order. First, the chef referenced by `chef_id` must currently be `AVAILABLE`; if that chef is `ON_LEAVE`, the request fails with `ERR_CHEF_UNAVAILABLE`. Second, no other active Event at the same `venue_id` — where "active" means an Event whose `status` is `SCHEDULED`, `OPEN`, or `SUSPENDED` — may collide with this event on the room's calendar. Venue collision is evaluated on half-open intervals with a turnover buffer: this event occupies from its `event_start` up to but not including its `event_end`, while each existing event is treated as occupying from its `event_start` up to but not including its `event_end` plus a fixed venue turnover buffer of `VENUE_TURNOVER_MINUTES` (30) minutes (the cleaning/reset time after a seating). If these two half-open intervals share any instant, the request fails with `ERR_VENUE_TIME_CONFLICT`. Third, no other active Event with the same `chef_id` may collide on the chef's calendar. Chef collision is evaluated with a preparation buffer applied to both events: each event is treated as occupying from its `event_start` minus a fixed chef preparation buffer of `CHEF_PREP_MINUTES` (60) minutes up to but not including its `event_end`; if this event's prep-extended interval shares any instant with an existing active event's prep-extended interval, the request fails with `ERR_CHEF_TIME_CONFLICT`.

When all three preconditions hold, scheduling generates exactly `seat_capacity` child `Seat` rows, all starting `AVAILABLE`, labelled deterministically `S1` through `SN` in ascending generation order via `seat_label`. The optional `head_table_count` on the schedule request designates how many of the earliest-generated seats are premium: the first `head_table_count` seats receive `seat_type` of `HEAD_TABLE`, and every remaining seat receives `STANDARD`. When `head_table_count` is omitted it is treated as 0, so no head-table seats are produced. The `seat_type` enumeration also includes `ACCESSIBLE`, which is a valid category value even though generation itself only assigns `HEAD_TABLE` and `STANDARD`. Each generated seat also carries `event_id` linking it back to its event, an optional `price_override_cents` (defaulting to null, meaning the seat falls back to the event's `seat_price_cents`; when set it must be non-negative), a `status` beginning at `AVAILABLE`, and a `current_booking_id` (null until a booking holds the seat). Scheduling increments the Event's `version` by one.

An Event may only be scheduled from `DRAFT`; attempting any Event lifecycle transition from a status that does not permit it fails with `ERR_INVALID_EVENT_STATE`.

### 3.3. Menus, Wine Pairings, and Opening for Bookings

The event's `Chef` builds the menu while the Event is being prepared. Each `MenuCourse` is attached to its event (carrying `event_id`) and defined by a `course_number` of at least 1 that orders it within the menu, a `name`, and optional descriptive fields, each defaulting to null when omitted: a free-text `description`, a `paired_wine_name`, and a `wine_varietal` naming the grape; and a `wine_supplement_cents` per-guest pairing supplement (non-negative, defaulting to 0). A course also declares `contains_allergens`, an array (defaulting to empty) drawn from the set `NUTS`, `DAIRY`, `GLUTEN`, `SHELLFISH`, and `SOY`, flagging allergens present in that dish.

Opening an event advances it `SCHEDULED → OPEN`, which is the only state in which the public may book. Opening is refused unless at least one `MenuCourse` already exists for the event; an event with no menu cannot open and the request fails with `ERR_MENU_REQUIRED`. Opening increments the Event's `version` by one.

### 3.4. Suspending, Resuming, and Repricing an Event

Once an event is `OPEN`, a `VenueManager` may temporarily freeze sales by suspending it, advancing it `OPEN → SUSPENDED`. While an event is `SUSPENDED`, new booking attempts against it are rejected with `ERR_EVENT_NOT_OPEN`, exactly as they would be for any non-open status. Resuming reverses this, advancing `SUSPENDED → OPEN`; this suspend/resume cycle is a non-linear edge that may be traversed repeatedly. Both suspending and resuming increment the Event's `version` by one.

Repricing lets a manager change the commercial terms of an event that has not yet sold under them. It is permitted while the event is `DRAFT` (a `DRAFT → DRAFT` self-transition) or `SCHEDULED` (a `SCHEDULED → SCHEDULED` self-transition). The request carries `new_seat_price_cents`, an optional `new_deposit_pct`, and the mandatory `expected_event_version` described in §2.6. When it succeeds, the event's `seat_price_cents` is updated to `new_seat_price_cents` and, if `new_deposit_pct` was supplied, `deposit_pct` is updated as well; any Bookings already created keep the prices computed at their own creation time and are not retroactively re-priced. Repricing increments the Event's `version` by one — which is precisely why a second client holding a now-stale `expected_event_version` will be turned away with `ERR_STALE_EVENT_VERSION`.

### 3.5. Making a Reservation: Booking, Deposits, and Pricing

A `Guest` reserves seats by creating a `Booking`. The request names the `event_id` and the acting `guest_id`, the `party_size` (number of covers, at least 1), and `seat_ids`, the explicit list of seats requested. Optional inputs are `table_preference` (either `COMMUNAL` or `PRIVATE`, defaulting to null when omitted), `dietary_restrictions` (an array, defaulting to empty, drawn from `VEGAN`, `VEGETARIAN`, `GLUTEN_FREE`, `NUT_ALLERGY`, `DAIRY_FREE`, and `PESCATARIAN`), free-text `allergy_notes` (defaulting to null when omitted), and `byob_bottles`, the number of outside bottles the party will bring (non-negative, defaulting to 0).

Creating a booking is only legal when the event is `OPEN`; against any other status the attempt fails with `ERR_EVENT_NOT_OPEN`. The `party_size` must equal the number of entries in `seat_ids`, or the request fails with `ERR_SEAT_COUNT_MISMATCH`. The current logical-clock time must be at or before the event's `booking_deadline`; a later request fails with `ERR_PAST_BOOKING_DEADLINE`. Every seat listed in `seat_ids` must have an `event_id` equal to the target event, or the request fails with `ERR_SEAT_NOT_IN_EVENT`; and every such seat must currently be `AVAILABLE`, or the request fails with `ERR_SEAT_UNAVAILABLE`. If `byob_bottles` is greater than 0, the event's `byob_allowed` must be true, otherwise the request fails with `ERR_BYOB_NOT_ALLOWED`. Finally, as a safety guard, a booking whose `dietary_restrictions` include `NUT_ALLERGY` may not be placed against an event any of whose menu courses lists `NUTS` in `contains_allergens`; such a conflict is rejected with `ERR_ALLERGEN_CONFLICT`.

On success the booking is created with `booking_status` of `PENDING_DEPOSIT` and, on the independent money dimension, `payment_status` of `UNPAID`. Each requested seat transitions `AVAILABLE → HELD` and records the new booking's id in its `current_booking_id`. At creation the system computes and stores three figures on the booking: `deposit_due_cents`, `total_price_cents`, and `corkage_due_cents`.

**Per-seat base price.** Both money calculations begin from a per-seat base price. For a given seat, the base price is the seat's own `price_override_cents` when that override is set, otherwise the event's `seat_price_cents`; then, if that seat's `seat_type` is `HEAD_TABLE`, a head-table supplement of 2000 cents is added on top. Seats of any other type add no supplement.

**Provisional deposit (`deposit_due_cents`).** This is the provisional variant: it applies the deposit fraction and ignores group discounts and corkage entirely. For each seat in `seat_ids`, take that seat's base price, multiply it by the event's `deposit_pct`, and round the result to whole cents using round half up. The per-seat rounded deposits are then summed to yield `deposit_due_cents`. The rounding order is pinned: round each seat individually first, then sum — never sum first and round once.

**Final settlement price (`total_price_cents`).** This is the final full-price variant, computed in a pinned order: subtotal, then group discount, then corkage. The subtotal is the sum of every seat's base price across `seat_ids` (no rounding is needed since base prices are already whole cents). A group discount applies only when the event's `table_mode` is `PRIVATE` and `party_size` is at least 6; otherwise the discount is 0. When it applies, the discount rate is 0.15 if `party_size` is at least 10, and 0.10 otherwise; the raw discount is that rate multiplied by the subtotal, rounded to whole cents using round half up, and then capped so that it never exceeds 15000 cents (the discount is the smaller of the rounded figure and that cap). Corkage is added next: when the event's `byob_allowed` is true, corkage equals `byob_bottles` multiplied by the event's `corkage_fee_cents`; when BYOB is not allowed, corkage is 0. The `total_price_cents` is then the subtotal minus the group discount plus the corkage. The booking's `corkage_due_cents` records that corkage component on its own — `byob_bottles` times the event's `corkage_fee_cents` when the event's `byob_allowed` is true, and 0 otherwise.

Paying the deposit advances the booking `PENDING_DEPOSIT → CONFIRMED`. The request carries `amount_cents`, which must exactly equal the booking's `deposit_due_cents`; any other amount is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`, and attempting to pay a booking that is not currently `PENDING_DEPOSIT` is rejected with `ERR_INVALID_BOOKING_STATE`. On success the money dimension advances `payment_status` from `UNPAID → DEPOSIT_PAID`, the paid amount is added to `deposit_paid_cents`, and a `Payment` ledger entry is appended with `kind` of `DEPOSIT`, `direction` of `CHARGE`, the paid `amount_cents`, and an optional `reason`. Every seat this booking holds transitions `HELD → BOOKED`.

At the door, a `VenueManager` checks a guest in, advancing the booking `CONFIRMED → ATTENDED`, which is terminal. Check-in is permitted only while the owning event's `status` is `OPEN` or `SUSPENDED` and the booking is `CONFIRMED`; from any other booking status it fails with `ERR_INVALID_BOOKING_STATE`.

### 3.6. Cancelling a Booking: Refund Tiers, Seat Release, and Waitlist Promotion

A `Guest` may cancel their own booking, and `CustomerService` may cancel on a guest's behalf. Cancellation is refused if the booking has already reached a terminal outcome — that is, if its `booking_status` is already `ATTENDED`, `CANCELLED`, or `NO_SHOW` — in which case the request fails with `ERR_BOOKING_ALREADY_TERMINAL`. The request may include an optional `reason`.

Cancelling a booking that is still `PENDING_DEPOSIT` advances it `PENDING_DEPOSIT → CANCELLED`. Because nothing was ever paid, `refund_cents` stays 0 and no `Payment` is written. Every seat the booking held transitions `HELD → AVAILABLE` and has its `current_booking_id` cleared.

Cancelling a `CONFIRMED` booking advances it `CONFIRMED → CANCELLED` and triggers the tiered cancellation refund. The refund is a fraction of what the guest actually paid (`deposit_paid_cents`), determined by how far ahead of the seating the cancellation lands. Compute the whole number of days before the event as the difference between the event's `event_start` and the current logical-clock time, divided by 86400 seconds and floored to a whole number of days. If that day count is at least 14, the refund rate is the full 1.00; if it is at least 7 but fewer than 14, the rate is 0.50; if it is at least 2 but fewer than 7, the rate is 0.25; and if it is fewer than 2, the rate is 0.00. The `refund_cents` is `deposit_paid_cents` multiplied by that rate, rounded to whole cents using round half up. A `Payment` entry is appended with `kind` of `REFUND`, `direction` of `REFUND`, and `amount_cents` equal to the refund. The money dimension then moves `payment_status` to `REFUNDED` when the refund equals the full `deposit_paid_cents`, and to `PARTIALLY_REFUNDED` when the refund is smaller than what was paid. Every seat the booking held transitions `BOOKED → AVAILABLE` with `current_booking_id` cleared.

Freeing seats through either cancellation path can trigger a waitlist promotion. Once the seats are released, the system inspects the event's waiting queue and selects the front-most `WAITING` `WaitlistEntry` — the one with the lowest position by `created_at` ascending — whose `party_size` is less than or equal to the number of seats just freed. That entry is promoted `WAITING → PROMOTED`, and the system auto-creates a `Booking` for its guest in `PENDING_DEPOSIT` / `UNPAID`, holding the freed seat(s); the promoted entry's `booking_id` is set to that new booking's id.

### 3.7. The Waitlist Queue

When an event has no seats left, a `Guest` may join its waitlist. A `WaitlistEntry` is created against the event with `event_id`, the acting `guest_id`, and the `party_size` requested (at least 1); its `booking_id` starts null. Joining is legal only while the event is `OPEN` — otherwise the attempt fails with `ERR_EVENT_NOT_OPEN` — and only when the event is genuinely full, meaning its `available_seat_count` is 0; if any seat is still available the request is rejected with `ERR_SEATS_AVAILABLE`. A new entry starts in `WAITING`.

Each waiting entry exposes a derived `position`: among all entries of the same event whose `status` is `WAITING`, ordered by `created_at` ascending, the entry's position is its 1-based rank in that ordering. For any entry not in `WAITING`, the serialized `position` is null. This same ordering drives promotion selection described in §3.6, and the tie-break is strictly `created_at` ascending — entry `id` is never used to break ties.

A guest may withdraw their own waiting entry (and `CustomerService` may do so on their behalf), advancing it `WAITING → WITHDRAWN`. Withdrawal is only legal while the entry is `WAITING`; against any other status it fails with `ERR_WAITLIST_ENTRY_NOT_WAITING`. Entries are also moved to terminal states automatically by their owning event's lifecycle: an event completing or cancelling expires every still-`WAITING` entry, moving it `WAITING → EXPIRED`.

### 3.8. Completing an Event: No-Shows and Revenue Recognition

An event is completed once its seating has ended, advancing it `OPEN → COMPLETED` or `SUSPENDED → COMPLETED`. Completion is refused unless the current logical-clock time is at or after the event's `event_end`; an earlier attempt fails with `ERR_EVENT_NOT_ENDED`. Completion runs a settlement cascade over the event's children. Every `Booking` still `CONFIRMED` at completion is treated as a no-show: it transitions `CONFIRMED → NO_SHOW`, its deposit is forfeited by moving `payment_status` to `FORFEITED`, and the already-collected `deposit_paid_cents` is retained with no refund (so `refund_cents` stays 0). Every `Booking` still `PENDING_DEPOSIT` transitions `PENDING_DEPOSIT → CANCELLED` with `refund_cents` of 0, since no deposit was ever paid. Every still-`WAITING` `WaitlistEntry` transitions `WAITING → EXPIRED`. Completion increments the Event's `version` by one.

Two revenue figures are derived on read for an event. The forward-looking `projected_revenue_cents` sums `total_price_cents` across the event's bookings whose `booking_status` is `PENDING_DEPOSIT` or `CONFIRMED` — the reservations not yet resolved, counted at full price. The chronological `realized_revenue_cents` counts only settled outcomes: it sums `total_price_cents` over bookings whose `booking_status` is `ATTENDED`, plus `deposit_paid_cents` over bookings whose `booking_status` is `NO_SHOW` (the forfeited deposits), and excludes everything still pending.

The event's seat and money tallies are likewise derived on read. `confirmed_seat_count` is the number of the event's seats whose `status` is `BOOKED`; `available_seat_count` is the number whose `status` is `AVAILABLE`; and `gross_deposit_held_cents` is the sum, across all of the event's bookings, of each booking's `deposit_paid_cents` minus its `refund_cents`.

### 3.9. Cancelling an Event: The Three-Hop Cascade

A `VenueManager` may cancel an event outright from any non-terminal status, with an optional `reason`. From `DRAFT` — before any seats exist — cancellation simply advances the event `DRAFT → CANCELLED` and increments its `version`. From `SCHEDULED`, `OPEN`, or `SUSPENDED`, cancellation runs a three-hop cascade before the event settles into `CANCELLED`.

The first hop moves reservations: every `Booking` whose `booking_status` is `PENDING_DEPOSIT` or `CONFIRMED` transitions to `CANCELLED`. The second hop, caused by the first, settles the money for each such booking: the guest receives a full refund, so `refund_cents` is set equal to `deposit_paid_cents` (an event-driven cancellation always refunds 100% of what was paid, regardless of how many days remain before the event), a `Payment` entry with `kind` of `REFUND` and `direction` of `REFUND` is appended for that amount, and `payment_status` becomes `REFUNDED` — or, if nothing had been paid, the booking's `payment_status` simply remains `UNPAID`. The third hop, caused by the second, releases inventory: each seat held by a cancelled booking transitions from `BOOKED` or `HELD` back to `AVAILABLE` and has its `current_booking_id` cleared. After the booking cascade completes, any seat that is still `AVAILABLE` (or was `HELD` by nothing) is taken out of service by transitioning it to `BLOCKED`. Finally, every still-`WAITING` `WaitlistEntry` is expired to `EXPIRED`. The whole cascade increments the Event's `version` by one.

Every immutable `Payment` written across these flows is journalled against its `booking_id` and remains queryable as the booking's ledger; the running held-deposit figure it feeds into is surfaced through the event's `gross_deposit_held_cents`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource, and all reads, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/series` | Create a recurring supper-club series | PlatformAdmin |
| GET | `/series/{id}` | Fetch a series | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/venues` | Create a venue | PlatformAdmin |
| GET | `/venues/{id}` | Fetch a venue | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/chefs` | Create a chef | PlatformAdmin |
| GET | `/chefs/{id}` | Fetch a chef | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/chefs/{id}/set-availability` | Set chef `AVAILABLE`/`ON_LEAVE` | Chef, PlatformAdmin |
| POST | `/guests` | Register a guest | PlatformAdmin |
| GET | `/guests/{id}` | Fetch a guest | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/events` | Create an event in `DRAFT` | VenueManager, PlatformAdmin |
| GET | `/events/{id}` | Fetch an event with derived counts and revenue | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| GET | `/events` | List/filter events | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/events/{id}/schedule` | Schedule an event and generate seats | VenueManager, PlatformAdmin |
| POST | `/events/{id}/open` | Open an event for bookings | VenueManager, PlatformAdmin |
| POST | `/events/{id}/suspend` | Suspend an open event | VenueManager, PlatformAdmin |
| POST | `/events/{id}/resume` | Resume a suspended event | VenueManager, PlatformAdmin |
| POST | `/events/{id}/complete` | Complete an event after its end | VenueManager, PlatformAdmin |
| POST | `/events/{id}/cancel` | Cancel an event and run the cascade | VenueManager, PlatformAdmin |
| POST | `/events/{id}/reprice` | Update pricing under OCC on the event version | VenueManager, PlatformAdmin |
| GET | `/events/{id}/seats` | List seats of an event | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| GET | `/events/{id}/menu` | List menu courses of an event | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| GET | `/events/{id}/waitlist` | List waitlist entries of an event | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/events/{id}/menu-courses` | Add a menu course and wine pairing | Chef, PlatformAdmin |
| POST | `/events/{id}/waitlist` | Join the waitlist of a full event | Guest |
| GET | `/waitlist/{id}` | Fetch a waitlist entry | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| GET | `/waitlist` | List/filter waitlist entries | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/waitlist/{id}/withdraw` | Withdraw a waiting entry | Guest, CustomerService |
| POST | `/bookings` | Create a booking, hold seats, compute prices | Guest |
| GET | `/bookings/{id}` | Fetch a booking | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| GET | `/bookings` | List/filter bookings | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/bookings/{id}/pay-deposit` | Pay the exact deposit and confirm | Guest |
| POST | `/bookings/{id}/check-in` | Check a confirmed booking in | VenueManager, PlatformAdmin |
| POST | `/bookings/{id}/cancel` | Cancel a booking, refund, free seats | Guest, CustomerService |
| GET | `/bookings/{id}/seats` | List seats held by a booking | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| GET | `/bookings/{id}/payments` | List a booking's payment ledger | PlatformAdmin, VenueManager, Chef, Guest, CustomerService |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SERIES_NOT_FOUND` | 404 |
| `ERR_VENUE_NOT_FOUND` | 404 |
| `ERR_CHEF_NOT_FOUND` | 404 |
| `ERR_GUEST_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_SEAT_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_MENU_COURSE_NOT_FOUND` | 404 |
| `ERR_WAITLIST_ENTRY_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_SEAT_COUNT_MISMATCH` | 422 |
| `ERR_EVENT_NOT_OPEN` | 409 |
| `ERR_INVALID_EVENT_STATE` | 409 |
| `ERR_EVENT_NOT_ENDED` | 409 |
| `ERR_INVALID_BOOKING_STATE` | 409 |
| `ERR_BOOKING_ALREADY_TERMINAL` | 409 |
| `ERR_WAITLIST_ENTRY_NOT_WAITING` | 409 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_ALLERGEN_CONFLICT` | 409 |
| `ERR_CHEF_UNAVAILABLE` | 409 |
| `ERR_MENU_REQUIRED` | 409 |
| `ERR_VENUE_TIME_CONFLICT` | 409 |
| `ERR_CHEF_TIME_CONFLICT` | 409 |
| `ERR_PAST_BOOKING_DEADLINE` | 409 |
| `ERR_SEAT_NOT_IN_EVENT` | 422 |
| `ERR_SEAT_UNAVAILABLE` | 409 |
| `ERR_SEATS_AVAILABLE` | 409 |
| `ERR_BYOB_NOT_ALLOWED` | 422 |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 |
