# Drive-In Cinema API — Product Requirements Document

## 1. Introduction

The Drive-In Cinema API powers the operations of drive-in and outdoor cinema venues, where the product to be sold is not a numbered seat but a finite physical resource: a parking stall for a car, or a square of lawn for a person. Operators must juggle showtime scheduling on shared lots, two fundamentally different ways of pricing admission (per car versus per person), a pool of FM radio frequencies that broadcast each film's audio and that cannot collide in the same airspace, concession pre-orders that ride along with a reservation, gate check-in and scanning, season passes, private lot rentals for events, and the ever-present possibility that weather forces a hold or a cancellation with refunds owed.

This document specifies the behavior an implementer must reproduce exactly. The system is, at its core, a quota-and-allocation engine wrapped around a pricing engine: every reservation consumes capacity that must be reconciled the instant it is created, cancelled, or swept away, and every charge must be computed deterministically to the cent. Because multiple operators and patrons act on the same showtimes and rentals, the system also defends against lost updates through optimistic concurrency, and it propagates cascading consequences — a cancelled showtime must unwind its reservations, its refunds, and its concession orders in a single coherent sweep. A logical clock, settable for deterministic testing, governs every time-gated rule so that check-in windows, no-show sweeps, completions, and refund tiers behave reproducibly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The four recognized roles are `PlatformAdmin`, `VenueOperator`, `GateAttendant`, and `Patron`. When a request is well-authenticated but the acting role is not permitted to invoke the requested operation per the endpoint authorization table in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles differ in how `X-User-ID` relates to persisted data. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `VenueOperator` and when it is `GateAttendant` — in both cases `X-User-ID` is an opaque operator identifier the server does not compare to any entity's `id`. When `X-User-Role` is `Patron`, `X-User-ID` is likewise an opaque identifier — but it carries ownership meaning: it is matched against the `patron_id` recorded on reservations, against the `patron_id` recorded on season passes, and (through the owning reservation) against concession orders. When a `Patron` attempts to mutate a reservation, a concession order, or a season pass whose owning `patron_id` does not equal the caller's `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422).

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order. The pagination bookkeeping fields surfaced in the `meta` object are `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation. The `updated_at` field is an ISO 8601 UTC timestamp of the same format, refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.6.

Two entities are deliberately leaner. A `Film` and a `WeatherEvent` carry only `id` and `created_at`; they have neither an `updated_at` field nor a `version` field, because once created they are never mutated. A `RefundRecord` likewise carries only `id` and `created_at` for the same reason — refunds are issued, not edited. All other resources — venues, lots, showtimes, FM channel assignments, season passes, reservations, concession items, concession orders, and private rentals — carry the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Derived-Count Reconciliation and Monetary Precision

A number of fields are derived rather than supplied, and the system keeps them in lock-step with reality. On a showtime, `reserved_stall_count` is the running number of stalls held by reservations whose `occupancy_status` is `CONFIRMED`, `CHECKED_IN`, or `SCANNED`, and `reserved_person_count` is the running sum of `occupant_count` over those same reservations for a per-person showtime. Both are reconciled on every reservation create, cancel, and no-show sweep. On a season pass, `redemptions_used` is the count of reservations created against that pass that are currently in occupancy `CONFIRMED`, `CHECKED_IN`, or `SCANNED`; it rises and falls as redemptions are made and released. Whenever such a reconciliation mutates a parent resource, that parent's `updated_at` is refreshed and its `version` is incremented.

All money in the system is held in integer cents; the entity fields carrying cents values are exact integers and never fractional. Where a calculation must apply a percentage, fraction, or proration, the result is rounded half up to a whole cent at the exact rounding point each calculation specifies in §3 — never earlier and never later. The phrase "rounded half up" means a value exactly halfway between two integers rounds to the larger magnitude.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded against acting on a stale view of their parent resource, and each requires the client to declare the parent `version` it last observed.

Creating a reservation requires `expected_showtime_version`, carrying the `version` of the target showtime the client last read. If that value does not equal the showtime's current `version` — because some other writer has advanced it since the client read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412) before any capacity check runs. Because a successful reservation create itself advances the showtime's `version` (through the count reconciliation in §2.5), two strictly sequential creates that both carry the same observed showtime `version` cannot both bind the last remaining stall: the first advances the version, and the second — still carrying the now-superseded value — is rejected as stale.

Cancelling a reservation requires `expected_reservation_version`, carrying the `version` of the reservation the client last read; a mismatch with the reservation's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Approving a private rental requires `expected_private_rental_version`, carrying the `version` of the rental the client last read; if the rental's `version` has advanced since — for example because another operator already acted on it — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412) before the interval-overlap check runs. No other endpoint takes a version field; operations not named here perform no concurrency check.

### 2.7. The Order of Rejection

When a single request could fail several checks, the system evaluates them in a fixed precedence so that the surfaced error is deterministic. Authentication comes first: missing or unrecognized headers yield `ERR_UNAUTHENTICATED`. Next, endpoint-level authorization yields `ERR_UNAUTHORIZED` when the role is not permitted. Next, for a `Patron` acting on a reservation, concession order, or season pass that they do not own, `ERR_NOT_RESOURCE_OWNER` is raised. Next, existence of every resource named in the path or body is checked, left to right, with the first missing one yielding `ERR_NOT_FOUND` (HTTP 404). Next, the request body is checked for well-formedness — required fields present, enums drawn from their allowed sets, and numbers within range (an `occupant_count` of at least 1, each `qty` of at least 1, a `promo_pct` between 0 and 1 inclusive, a recognized `pricing_mode`) — with violations yielding `ERR_INVALID_REQUEST` (HTTP 400). Only after all of those does the system evaluate state-machine legality (`ERR_INVALID_STATE`, HTTP 409), then optimistic concurrency (`ERR_STALE_VERSION`, HTTP 412), and finally the domain-specific business rules described throughout §3. This ordering means a stale-version rejection never masks a missing resource, and a business-capacity rejection never masks an illegal state transition.

### 2.8. Nested Resource Retrieval and the Logical Clock

Several paths address a child through its parent — for instance the FM channel of a showtime, the weather events of a showtime, or the concession orders of a reservation. For any such path, identifiers are validated left to right: the parent must exist before the child is sought, and the first identifier in the path that names no existing resource yields `ERR_NOT_FOUND` (HTTP 404) immediately, before any deeper lookup is attempted.

The system runs on a logical clock rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. An administrative capability advances the clock to a supplied `to_iso8601` instant, after which every time-gated rule — check-in windows, no-show sweeps, completion eligibility, refund tiers, and FM time-overlap checks — is evaluated against the clock's current value.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Venues, Lots, Films, and Concession Items

A drive-in begins with a **venue**, created by a `PlatformAdmin`. A venue is given a display `name` and an optional `timezone` (an IANA timezone string in which all showtime windows are interpreted, defaulting to `UTC`). The venue also defines the shared radio airspace through its `fm_channel_pool`: an ordered, non-empty array of distinct FM frequency strings such as `['87.9','88.1','88.3']`, assigned to showtimes in list order. Two operational buffers round out the venue: `turnaround_buffer_minutes`, the required cleanup gap between consecutive showtimes on the same lot, which must be zero or greater and defaults to 30; and `no_show_grace_minutes`, the number of minutes after a showtime's start during which an unscanned but `CONFIRMED` reservation is still honored, which must be zero or greater and defaults to 15.

A **lot** is a parking field within a venue, created by a `PlatformAdmin` or a `VenueOperator`. It records the `venue_id` it belongs to, a `name` such as "North Field", a `stall_count` (the total number of car stalls, at least 1, which is the upper bound on per-car reservations for any one showtime), and a `person_capacity` (the maximum total occupants for a per-person showtime in this lot, at least 1). A lot's `status` is system-managed, begins `OPEN`, and is one of `OPEN` or `CLOSED`; it closes and reopens only through the private-rental lifecycle described in §3.7.

A **film** is a catalog entry created by a `PlatformAdmin` or a `VenueOperator`, carrying a `title`, a `runtime_minutes` of at least 1 (used to derive a showtime's end instant), and a `rating` that is one of `G`, `PG`, `PG13`, or `R`. A **concession item** is a menu entry for a venue, created by a `PlatformAdmin` or a `VenueOperator`, with a `venue_id`, a `name`, a `unit_price_cents` of zero or more, a `tax_rate` expressed as a fraction at least 0 and strictly below 1 (defaulting to 0 for non-taxable items), and an `available` boolean (defaulting to true) that governs whether the item may be added to a new order.

### 3.2. Scheduling a Showtime

A `VenueOperator` schedules a **showtime** on a single lot. The request supplies the `venue_id` hosting the screening, the `lot_id` it occupies, the `primary_film_id` of the first feature, an optional `secondary_film_id`, an `is_double_feature` flag (defaulting to false), the gate-open `start_utc` instant, the `pricing_mode` (one of `PER_CAR` or `PER_PERSON`), and the pricing inputs described in §3.3. A showtime's `status` is system-managed, starts at `SCHEDULED`, and is one of `SCHEDULED`, `WEATHER_HOLD`, `CANCELLED`, or `COMPLETED`.

The system computes the showtime's `end_utc` rather than accepting it: `end_utc` equals `start_utc` plus the primary film's runtime, plus the secondary film's runtime when (and only when) `is_double_feature` is true; for a single feature only the primary runtime is added. This `end_utc` defines the screening's occupancy of the lot.

Two configuration checks guard creation. First, the showtime configuration must be internally consistent: the `lot_id` must belong to the `venue_id`, every referenced film must exist, and `secondary_film_id` must be non-null exactly when `is_double_feature` is true (non-null with a single feature, or null with a double feature, is inconsistent). A violation yields `ERR_SHOWTIME_CONFIG_INVALID` (HTTP 422). Second, the new screening must not collide on its lot: treating each showtime's occupancy as the half-open window from its `start_utc` up to but not including its `end_utc`, and extending that window by the venue's `turnaround_buffer_minutes` of cleanup time, the new window must not overlap that of any other showtime on the same lot whose `status` is `SCHEDULED` or `WEATHER_HOLD`. A collision yields `ERR_SHOWTIME_OVERLAP` (HTTP 409).

A showtime also exposes the two derived occupancy counters introduced in §2.5, `reserved_stall_count` and `reserved_person_count`, both starting at 0.

### 3.3. Pricing a Reservation

When a **reservation** is created (see §3.4), the system computes its `amount_due_cents` from the showtime's pricing configuration and the reservation's party. The relevant showtime inputs are `base_price_cents` (zero or more), `included_occupants` (per-car only, at least 1, defaulting to 2), `per_extra_person_cents` (per-car only, zero or more, defaulting to 0), and `double_feature_surcharge_cents` (a flat surcharge of zero or more, defaulting to 0, added whenever the screening is a double feature). The relevant reservation inputs are `occupant_count` and the optional `promo_pct`.

Three pricing variants apply, selected by whether the reservation rides a season pass and by the showtime's `pricing_mode`:

- **Season-pass redemption** (the reservation supplies a `season_pass_id`): regular admission is waived entirely. The gross is just the `double_feature_surcharge_cents` when the screening is a double feature, and zero otherwise. The `promo_pct` is ignored on a pass redemption, so `amount_due_cents` equals that surcharge gross with no discount applied. A pass redemption may therefore have an `amount_due_cents` of zero.
- **Per-car pricing** (no `season_pass_id`, and `pricing_mode` is `PER_CAR`): the base price covers `included_occupants`; only occupants beyond that threshold are charged. Compute the extra-person count as the larger of zero and `occupant_count` minus `included_occupants` — an `occupant_count` at or below the threshold does not reduce the base. The gross is `base_price_cents`, plus the extra-person count multiplied by `per_extra_person_cents`, plus `double_feature_surcharge_cents` when the screening is a double feature.
- **Per-person pricing** (no `season_pass_id`, and `pricing_mode` is `PER_PERSON`): `included_occupants` and `per_extra_person_cents` are ignored entirely; every occupant is charged. The gross is `occupant_count` multiplied by `base_price_cents`, plus `double_feature_surcharge_cents` when the screening is a double feature.

For the per-car and per-person variants, the optional `promo_pct` discount is then applied to the whole gross in a single step: the discount is the gross multiplied by `promo_pct`, rounded half up once to a whole cent, and `amount_due_cents` is the gross minus that rounded discount. The discount is computed on the entire gross and rounded exactly once (sum-then-round), not per component.

### 3.4. Reserving a Stall or a Lawn Spot, and Paying

A `Patron` creates a reservation against a showtime. The request carries the `showtime_id`, the `patron_id` who will own the reservation, the party's `occupant_count` (at least 1), an optional `season_pass_id`, an optional `promo_pct` (a fraction at least 0 and at most 1, defaulting to 0), and the `expected_showtime_version` required by the concurrency rule in §2.6. On success the reservation's `lot_id` is copied from the showtime for capacity bookkeeping, its `amount_due_cents` is priced per §3.3, its `stalls_used` is set to 1 for a per-car showtime and 0 for a per-person showtime (this is the stall debit the reservation places on the showtime), and a `gate_code` scan token is minted by the server (distinct from the `id`, and presented later at the gate). The reservation's `amount_paid_cents` starts at 0. A reservation evolves along two independent dimensions: its `occupancy_status`, one of `CONFIRMED`, `CHECKED_IN`, `SCANNED`, `NO_SHOW`, or `CANCELLED`, beginning at `CONFIRMED`; and its `payment_status`, one of `UNPAID`, `PAID`, or `REFUNDED`, beginning at `UNPAID`.

Creation enforces several domain rules in addition to the pricing and concurrency logic. A reservation against a per-person showtime must omit the vehicle-only fields; and if a `season_pass_id` is supplied, that pass must be `ACTIVE`, owned by the acting patron, within its validity window, not exhausted, and valid for this screening in the sense that the showtime's `start_utc` is on or before the pass's `valid_to_utc`. The validity-window condition is satisfied solely by this `valid_to_utc` clause: it tests only that the screening's `start_utc` is on or before `valid_to_utc`, and it does not compare the pass's `valid_from_utc` or the logical clock's current value against the window. Thus a pass whose `valid_from_utc` lies in the future, or a screening reserved while the clock falls outside `[valid_from_utc, valid_to_utc]`, remains within its validity window so long as the screening's `start_utc` does not fall after `valid_to_utc`. Any of those pass conditions failing — wrong owner, not `ACTIVE`, outside the window, or a screening after `valid_to_utc` — yields `ERR_PASS_INVALID` (HTTP 422). Separately, a pass-backed create also requires redemption budget: `redemptions_used` must be strictly less than the pass's `max_redemptions`, or the create is rejected with `ERR_PASS_EXHAUSTED` (HTTP 409). For a per-car reservation, the showtime's `reserved_stall_count` must be strictly less than the lot's `stall_count`, otherwise `ERR_LOT_FULL` (HTTP 409). For a per-person reservation, the showtime's `reserved_person_count` plus the new `occupant_count` must be at most the lot's `person_capacity`, otherwise `ERR_PERSON_CAPACITY_EXCEEDED` (HTTP 409). On a successful create, the showtime's `reserved_stall_count` and `reserved_person_count` are increased by this reservation's contribution, the showtime's `version` is incremented, and if a pass was used its `redemptions_used` rises by one.

Paying a reservation, performed by the owning `Patron`, advances `payment_status` from `UNPAID` to `PAID` and is allowed only while `payment_status` is `UNPAID` and `occupancy_status` is `CONFIRMED`; on payment, `amount_paid_cents` is set equal to `amount_due_cents`. A season-pass reservation whose `amount_due_cents` is zero may still be transitioned to `PAID` (a zero capture), which is what allows it to be checked in.

### 3.5. At the Gate: Check-In, Scan, No-Show, and Cancellation

Arriving at the gate, a `Patron` is processed by a `GateAttendant`. **Check-in** advances `occupancy_status` from `CONFIRMED` to `CHECKED_IN`. It is permitted only when the reservation's `occupancy_status` is `CONFIRMED`, its `payment_status` is `PAID`, and the showtime's `status` is `SCHEDULED`. Check-in also has a time window: it may not happen earlier than 60 minutes before the showtime's `start_utc`. An attempt before that point — that is, while the logical clock reads earlier than `start_utc` minus 60 minutes — is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409).

**Scanning** advances `occupancy_status` from `CHECKED_IN` to `SCANNED` and admits the party. The request supplies a `gate_code`, and the transition is permitted only when `occupancy_status` is `CHECKED_IN`. The supplied `gate_code` must equal the reservation's minted `gate_code`; a mismatch is rejected with `ERR_GATE_CODE_MISMATCH` (HTTP 409).

The **no-show sweep** is a system operation, invokable by a `VenueOperator` or a `GateAttendant`, that runs per showtime to forfeit unscanned holds. It may run only once the logical clock has reached the showtime's `start_utc` plus the venue's `no_show_grace_minutes`; an earlier attempt is rejected with `ERR_SWEEP_TOO_EARLY` (HTTP 409). For each reservation on the showtime still in `occupancy_status` `CONFIRMED` once the grace period has elapsed, the sweep sets that reservation's `occupancy_status` to `NO_SHOW`, decrements the showtime's `reserved_stall_count` by the reservation's `stalls_used`, decrements the showtime's `reserved_person_count` by the reservation's `occupant_count` for a per-person showtime, and — if the reservation was created against a season pass — decrements that pass's `redemptions_used` by one, restoring the conserved redemption. Each swept reservation's `version` is incremented. A no-show forfeits the spot and carries no refund.

**Cancellation** is initiated by the owning `Patron` and advances `occupancy_status` to `CANCELLED`. It is allowed only while `occupancy_status` is `CONFIRMED` or `CHECKED_IN` and the showtime's `status` is `SCHEDULED` or `WEATHER_HOLD`, and it requires `expected_reservation_version` to match the reservation's current `version` (the optimistic-concurrency rule of §2.6). On cancellation the system releases capacity exactly as the sweep does — decrementing `reserved_stall_count` by `stalls_used`, decrementing `reserved_person_count` by `occupant_count` for a per-person showtime, and restoring a season-pass redemption when one was used — and increments the reservation's `version`. If the reservation's `payment_status` was `PAID`, the system computes a voluntary-cancel refund (see §3.6), sets `payment_status` to `REFUNDED`, and creates a refund record attributing the refund to the reservation. The cancellation then cascades: any concession order on this reservation whose `status` is `PENDING` or `PAID` is moved to `CANCELLED`, and if such an order was `PAID`, a further refund record for the full order total is created, attributing the refund to the reservation cascade. This is a depth-three unwind — cancelling the reservation refunds the reservation, then cancels and refunds its concession orders.

### 3.6. Refund Policy and Refund Records

The system computes a reservation refund from the reservation's `amount_paid_cents` under one of two policies, selected by the reason for the refund.

For a **voluntary cancellation**, the refund follows a chronological policy tier driven purely by how long before the showtime the cancellation occurs, measured as the hours between the logical clock's current value and the showtime's `start_utc`. At 48 hours or more before start, the full amount is refunded (100 percent). At 24 hours or more but fewer than 48, half is refunded (50 percent). At 2 hours or more but fewer than 24, a quarter is refunded (25 percent). Under 2 hours before start, nothing is refunded (0 percent). The refund is the `amount_paid_cents` multiplied by the applicable tier percentage, rounded half up once to a whole cent.

For a **weather cancellation**, the refund is forward-looking and pro-rated by unscreened features rather than by timing. Let the total feature count be 2 for a double feature and 1 for a single feature; let the remaining features be the smaller of the weather event's `features_remaining` and that total. The refund is the `amount_paid_cents` multiplied by remaining features divided by total features, rounded half up once to a whole cent. A double feature stopped after the first feature thus refunds 50 percent even if the cancellation lands mid-event, independent of how close to start time it is.

Every refund is recorded as a **refund record**, a write-once entity. Its `source_type` is `RESERVATION` or `CONCESSION_ORDER`. When the source is a reservation, its `reservation_id` is set and `concession_order_id` is null; when the source is a concession order, `concession_order_id` is set and `reservation_id` is null. Its `reason` is one of `WEATHER`, `VOLUNTARY_CANCEL`, or `RESERVATION_CASCADE`, and its `amount_cents` is the computed refund for reservation refunds, or the order's full `total_cents` for a cascaded concession refund. A concession order cancelled directly by its owner records reason `VOLUNTARY_CANCEL`, whereas one cancelled because its parent reservation or showtime was cancelled records reason `RESERVATION_CASCADE`.

### 3.7. Private Rentals: Quoting, Approval, and the Exclusive Lot Hold

A `VenueOperator` requests a **private rental** of a lot for an event window. The request supplies the `venue_id`, the `lot_id` to hold exclusively, the `organizer_id`, the inclusive `start_utc` and `end_utc` of the hold, a `flat_venue_fee_cents` base fee (zero or more), and a `per_hour_cents` rate (zero or more). A rental's `status` is system-managed, begins `REQUESTED`, and is one of `REQUESTED`, `APPROVED`, `REJECTED`, or `CANCELLED`. On creation the system computes the rental's `quote_cents`: take the hold's duration, round it up to a whole number of hours (any partial hour bills as a full hour, so a hold of three hours and one minute bills four hours), and set `quote_cents` to the `flat_venue_fee_cents` plus the `per_hour_cents` multiplied by that rounded-up hour count.

Approval, by a `VenueOperator`, advances `status` from `REQUESTED` to `APPROVED`. It is allowed only while `status` is `REQUESTED` and requires `expected_private_rental_version` to match the rental's current `version`. Before the hold can be granted, the lot must be free across the requested window, treated as a closed interval (inclusive of both `start_utc` and `end_utc`) covering the whole lot: there must be no other `APPROVED` private rental on the same lot whose closed window overlaps this one, and no showtime on the same lot whose `status` is `SCHEDULED` or `WEATHER_HOLD` whose interval intersects this hold window. A conflict yields `ERR_RENTAL_CONFLICT` (HTTP 409). On approval the system sets the lot's `status` to `CLOSED`, marking it exclusively held, and increments the rental's `version`. (Note the deliberate contrast with showtime scheduling in §3.2: showtimes use half-open windows extended by a turnaround buffer, while a rental hold is a closed whole-lot interval.)

A rental in `REQUESTED` may instead be **rejected** by a `VenueOperator`, advancing `status` to `REJECTED`. An `APPROVED` rental may later be **cancelled** by a `VenueOperator`, advancing `status` to `CANCELLED` and setting the held lot's `status` back to `OPEN`, releasing the exclusive hold. Each of these transitions increments the rental's `version`.

### 3.8. Concession Pre-Orders

A `Patron` attaches a **concession pre-order** to one of their reservations. The order carries its `reservation_id` and a non-empty `lines` array, where each line is an object of `{concession_item_id, qty}` with a `qty` of at least 1. A concession order's `status` is system-managed, begins `PENDING`, and is one of `PENDING`, `PAID`, `FULFILLED`, or `CANCELLED`. Every referenced concession item must have `available` equal to true and must belong to the same venue as the reservation; otherwise the create is rejected with `ERR_ITEM_UNAVAILABLE` (HTTP 409).

On creation the system computes the order's `subtotal_cents`, `tax_cents`, `service_fee_cents`, and `total_cents` in a pinned order of operations. Iterating the `lines` in request order, each line's amount is the item's `unit_price_cents` multiplied by the line's `qty`; the `subtotal_cents` accumulates these line amounts. For tax, each line's tax is the line amount multiplied by that item's `tax_rate`, rounded half up to a whole cent per line, and `tax_cents` is the sum of those per-line rounded taxes — the rounding happens once per line and the rounded results are summed, which can differ from summing exact taxes and rounding once, so the per-line rounding order is mandatory. The `service_fee_cents` is the `subtotal_cents` multiplied by a five-percent service fee, rounded half up once on the subtotal. Finally, `total_cents` is the `subtotal_cents` plus `tax_cents` plus `service_fee_cents`.

A concession order is **paid** by the owning `Patron`, advancing `status` from `PENDING` to `PAID`; this is allowed only while the order is `PENDING` and the parent reservation's `occupancy_status` is `CONFIRMED`, `CHECKED_IN`, or `SCANNED`. A paid order is **fulfilled** by a `GateAttendant`, advancing `status` from `PAID` to `FULFILLED`; fulfillment is allowed only while the order is `PAID` and — a cross-entity guard — only once the parent reservation's `occupancy_status` is `SCANNED`, ensuring food is handed over only after the patron has physically scanned in. An order in `PENDING` or `PAID` may be **cancelled** by the owning `Patron`, advancing `status` to `CANCELLED`; if the order was `PAID` at cancellation, a refund record for the full `total_cents` is created (reason `VOLUNTARY_CANCEL` when the patron initiates it directly, or `RESERVATION_CASCADE` when it is cancelled as part of a reservation or showtime cascade).

### 3.9. FM Channel Assignment

Each showtime needs a radio frequency on which to broadcast its audio, drawn from the shared venue pool. A `VenueOperator` triggers a waterfall assignment for a showtime, which produces an **FM channel assignment**. The assignment records its `showtime_id`, a denormalized `venue_id` copied from the parent showtime at assignment time (identifying the shared airspace pool), the chosen `frequency`, and a `status` that is one of `ACTIVE` or `RELEASED`, beginning `ACTIVE`. The assigned `frequency` is the first entry of the venue's `fm_channel_pool`, in list order, that is not already assigned to a time-overlapping showtime of the same venue. If every frequency in the pool is occupied by a time-overlapping showtime, the assignment is rejected with `ERR_NO_FM_CHANNEL` (HTTP 409). A showtime's current FM channel assignment is discoverable by listing the assignments for that showtime.

### 3.10. Weather Holds and Cancellations

A `VenueOperator` records a **weather event** against a showtime, supplying a `severity` of `ADVISORY` or `CANCELLATION` and, for a cancellation, a `features_remaining` count of unscreened features at the moment of cancellation (between 0 and 2 inclusive, defaulting to 0; ignored for an advisory). A weather event is a write-once record.

An **advisory** simply puts the showtime on hold: it is permitted only when the showtime's `status` is `SCHEDULED`, and it advances `status` to `WEATHER_HOLD`, incrementing the showtime's `version`. The hold is cyclic and resumable: a `VenueOperator` may **clear** the hold, which is permitted only when `status` is `WEATHER_HOLD` and returns `status` to `SCHEDULED` (again incrementing `version`); a showtime can move between `SCHEDULED` and `WEATHER_HOLD` repeatedly.

A **cancellation** weather event forces the showtime down. For a cancellation, `features_remaining` must lie between 0 and the showtime's total feature count (2 for a double feature, 1 for a single feature); a value outside that range is rejected with `ERR_WEATHER_FEATURES_INVALID` (HTTP 422). A cancellation is permitted when the showtime's `status` is `SCHEDULED` or `WEATHER_HOLD`, and it sets `status` to `CANCELLED` and increments the showtime's `version`. It then cascades across the showtime's bookings: for every reservation on the showtime whose `occupancy_status` is `CONFIRMED`, `CHECKED_IN`, or `SCANNED`, the reservation is moved to `occupancy_status` `CANCELLED`, its stall and person counts are released, and any season-pass redemption it used is restored; and if that reservation's `payment_status` was `PAID`, a weather refund (pro-rated by `features_remaining` per §3.6) is computed, `payment_status` is set to `REFUNDED`, and a refund record with reason `WEATHER` is created. Each such reservation then cascades to its own concession orders exactly as a voluntary cancellation does: any `PENDING` or `PAID` concession order is moved to `CANCELLED`, with a refund record (reason `RESERVATION_CASCADE`) for the full order total when the order was `PAID`. Finally, the showtime's FM channel assignment, if any, is moved to `status` `RELEASED`, freeing the frequency for reuse.

### 3.11. Completing a Showtime, and Season Passes

A `VenueOperator` marks a showtime **completed** once the show is over. Completion is permitted only when the showtime's `status` is `SCHEDULED` and the logical clock has reached the showtime's `end_utc`; an attempt before the clock reaches `end_utc` is rejected with `ERR_COMPLETE_TOO_EARLY` (HTTP 409). Completion sets `status` to `COMPLETED`, releases the showtime's FM channel assignment by setting it to `RELEASED`, and increments the showtime's `version`.

A `VenueOperator` issues a **season pass** to a patron. The pass records the owning `patron_id`, a `tier` of `SILVER` or `GOLD`, a `max_redemptions` count (at least 1) of reservations the pass may cover over its validity window, and the inclusive `valid_from_utc` and `valid_to_utc` bounds of that window — a redemption being valid only when the screening's `start_utc` is on or before `valid_to_utc`. The pass's `redemptions_used` derived counter starts at 0 and tracks live redemptions as described in §2.5. A pass's `status` begins `ACTIVE` and is one of `ACTIVE` or `REVOKED`. A `VenueOperator` may **revoke** a pass, permitted only while `status` is `ACTIVE`, which advances `status` to `REVOKED` and increments the pass's `version`. Revocation only blocks new redemptions; it does not retroactively cancel reservations already created against the pass.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the test-clock and sweep capabilities — return a `200 OK` status code. Every list endpoint accepts the `limit` and `offset` pagination parameters of §2.3 in addition to the filters noted in its description.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue with its FM channel pool and operational buffers | PlatformAdmin |
| GET | `/venues/{id}` | Fetch a venue | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/lots` | Create a parking lot under a venue | PlatformAdmin, VenueOperator |
| GET | `/lots/{id}` | Fetch a lot including derived status | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| GET | `/lots` | List lots, optionally filtered by `venue_id` | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/films` | Create a film in the catalog | PlatformAdmin, VenueOperator |
| GET | `/films/{id}` | Fetch a film | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/concession-items` | Create a concession menu item for a venue | PlatformAdmin, VenueOperator |
| GET | `/concession-items/{id}` | Fetch a single concession item | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| GET | `/concession-items` | List concession items, optionally filtered by `venue_id` | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/showtimes` | Schedule a showtime on a lot | VenueOperator |
| GET | `/showtimes/{id}` | Fetch a showtime including derived counts | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| GET | `/showtimes` | List showtimes, filterable by `venue_id`, `lot_id`, `primary_film_id`, `secondary_film_id` | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/showtimes/{id}/fm-channel` | Waterfall-assign the first free FM frequency | VenueOperator |
| GET | `/showtimes/{id}/fm-channel` | List FM channel assignment(s) for a showtime | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/showtimes/{id}/weather-events` | Record a weather event (advisory hold or cancellation cascade) | VenueOperator |
| GET | `/showtimes/{id}/weather-events` | List weather events for a showtime | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/showtimes/{id}/clear-weather-hold` | Return a held showtime to scheduled | VenueOperator |
| POST | `/showtimes/{id}/complete` | Mark a showtime completed; release FM channel | VenueOperator |
| POST | `/showtimes/{id}/run-no-show-sweep` | Sweep unscanned reservations to no-show | VenueOperator, GateAttendant |
| POST | `/reservations` | Create a reservation against a showtime | Patron |
| GET | `/reservations/{id}` | Fetch a reservation | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| GET | `/reservations` | List reservations, filterable by `showtime_id`, `lot_id`, `patron_id`, `season_pass_id` | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/reservations/{id}/pay` | Capture payment for a reservation | Patron |
| POST | `/reservations/{id}/check-in` | Gate check-in within the pre-show window | GateAttendant |
| POST | `/reservations/{id}/scan` | Validate the gate code and admit | GateAttendant |
| POST | `/reservations/{id}/cancel` | Cancel a reservation with refund and cascade | Patron |
| POST | `/reservations/{id}/concession-orders` | Create a concession pre-order on a reservation | Patron |
| GET | `/reservations/{id}/concession-orders` | List concession orders for a reservation | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/concession-orders/{id}/pay` | Pay a concession order | Patron |
| POST | `/concession-orders/{id}/fulfill` | Fulfill a paid order (requires parent scanned) | GateAttendant |
| POST | `/concession-orders/{id}/cancel` | Cancel a concession order; refund if paid | Patron |
| POST | `/season-passes` | Issue a season pass to a patron | VenueOperator |
| GET | `/season-passes/{id}` | Fetch a season pass including redemptions used | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| GET | `/season-passes` | List season passes, filterable by `patron_id` | PlatformAdmin, VenueOperator, GateAttendant, Patron |
| POST | `/season-passes/{id}/revoke` | Revoke a season pass | VenueOperator |
| POST | `/private-rentals` | Request a private rental of a lot; computes the quote | VenueOperator |
| GET | `/private-rentals/{id}` | Fetch a private rental | PlatformAdmin, VenueOperator, GateAttendant |
| GET | `/private-rentals` | List private rentals, filterable by `venue_id`, `lot_id` | PlatformAdmin, VenueOperator, GateAttendant |
| POST | `/private-rentals/{id}/approve` | Approve a rental; close the lot exclusively | VenueOperator |
| POST | `/private-rentals/{id}/reject` | Reject a rental request | VenueOperator |
| POST | `/private-rentals/{id}/cancel` | Cancel an approved rental; reopen the lot | VenueOperator |
| GET | `/refund-records/{id}` | Fetch a refund record | PlatformAdmin, VenueOperator, Patron |
| GET | `/refund-records` | List refund records, filterable by `reservation_id`, `concession_order_id` | PlatformAdmin, VenueOperator, Patron |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a supplied instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SHOWTIME_CONFIG_INVALID` | 422 |
| `ERR_SHOWTIME_OVERLAP` | 409 |
| `ERR_RENTAL_CONFLICT` | 409 |
| `ERR_PASS_INVALID` | 422 |
| `ERR_PASS_EXHAUSTED` | 409 |
| `ERR_ITEM_UNAVAILABLE` | 409 |
| `ERR_LOT_FULL` | 409 |
| `ERR_PERSON_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_FM_CHANNEL` | 409 |
| `ERR_GATE_CODE_MISMATCH` | 409 |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 |
| `ERR_COMPLETE_TOO_EARLY` | 409 |
| `ERR_SWEEP_TOO_EARLY` | 409 |
| `ERR_WEATHER_FEATURES_INVALID` | 422 |
| `ERR_VALIDATION_LIMIT` | 422 |
