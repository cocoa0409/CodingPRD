# Restaurant Reservation & Waitlist API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a restaurant reservation and waitlist platform in the style of modern booking products such as OpenTable. The system gives a restaurant operator a single source of truth over its physical floor — its dining areas, its individual tables, the turn time each table consumes, and the service periods during which guests may book — and it layers on top of that inventory the booking, deposit, no-show, and waitlist machinery that a busy front-of-house depends on.

Three pain points drive the design. First, **double-seating and over-pacing the kitchen**: a reservation must hold a specific table for a computed dwell window plus a cleanup buffer, and no service-period slot may accept more covers than the kitchen can absorb. Second, **revenue leakage from no-shows and late cancellations**: large parties must back their booking with a refundable card hold, and a guest who fails to honour a confirmed booking accrues strikes, forfeits a fee, and — past a threshold — is blocked, which in turn unwinds their remaining future bookings. Third, **demand that outstrips supply**: when no table is free, guests join a waitlist and are notified by SMS in a fair, deterministic order as tables free up, with a bounded window to claim the offer before it lapses and rolls to the next party.

The platform also supports **private dining**: a private area can be bought out wholesale for an event window, which confirms only after a contracted deposit is computed and which cancels any ordinary reservations that would have collided with the buyout. Three distinct operator perspectives — the guest, the front-of-house host, and the back-of-house manager — share this system with non-overlapping authority over the resources each owns.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to an authenticated endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. The role value must be exactly one of `Customer`, `Host`, or `Manager`. If either header is missing or malformed on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation under the authorization rules of this document, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two endpoints are exceptions to the authentication requirement: customer self-registration accepts requests with no authentication headers, and the test-only clock endpoint is likewise outside the authenticated set.

The `Customer` role is **entity-backed**. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a `Customer` compare that resource's `customer_id` field to `X-User-ID`. A guest registers themselves, books and manages their own reservations, joins and leaves the waitlist, and attaches special requests to their own bookings.

The `Host` role is **opaque**. When `X-User-Role` is `Host`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A host is the front-of-house operator who confirms, seats, completes, and marks no-show on reservations, and who drives the waitlist by notifying, converting, and re-queueing entries.

The `Manager` role is likewise **opaque**: `X-User-ID` for a manager is an operator identifier not tied to any persisted entity and is not compared to any entity's `id`. A manager configures restaurants, dining areas, tables, and service periods, captures and releases deposits, blocks and unblocks customers, owns the full private-dining lifecycle, and operates the test clock.

A guest acting as a `Customer` may only cancel or reschedule a reservation, or cancel a waitlist entry, when that resource's `customer_id` equals their `X-User-ID`; an attempt to act on another guest's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` defaults to 0 and may not be negative. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422). List results are ordered by `created_at` ascending by default. The pagination fields surfaced in the `meta` block of a list response are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filter before pagination and `has_more` indicates whether records beyond the current page remain.

### 2.4. Common Resource Properties and Versioning

Every resource is identified by an `id`, a server-minted UUID carrying no type prefix. Most resources also carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by one on every mutation of the resource. The `created_at` value is fixed at creation; `updated_at` is refreshed on every mutation.

Two resource kinds are append-only records and therefore carry only `id` and `created_at` — they have **no** `updated_at` and **no** `version` field: the `SpecialRequest` and the `Notification`. A `SpecialRequest` does change exactly once when it is acknowledged, but it does not expose a `version`; all other entities (`Restaurant`, `DiningArea`, `Table`, `ServicePeriod`, `Customer`, `Reservation`, `WaitlistEntry`, `DepositHold`, `PrivateDiningEvent`) carry the full `created_at` / `updated_at` / `version` triple.

### 2.5. Time, Slots, and Service-Period Windows

All instants stored and returned by the system are UTC ISO 8601 timestamps with three fractional digits — `reservation_start`, `turn_window_end`, `release_at`, `requested_start`, `joined_at`, `notify_expires_at`, `event_start`, and `event_end` are all UTC. A restaurant nonetheless declares a `timezone` (an IANA zone string, defaulting to `America/New_York`) that governs how a booking's instant is interpreted as a local wall-clock time when it is matched against a service period. Each `ServicePeriod` declares its open and close as local 24-hour `start_local_time` and `end_local_time` strings in `HH:MM` form, where the close must be strictly after the open; the bookable window is half-open, running from the open time inclusive up to but not including the close time. A period also declares a `slot_interval_minutes` granularity — one of 15, 30, or 60, defaulting to 30 — and a booking's local start must align to the grid formed by stepping that interval forward from `start_local_time`. A booking whose local start falls outside every service-period window, or which does not land exactly on a period's slot grid, is rejected with `ERR_OUTSIDE_SERVICE_PERIOD` (HTTP 422).

### 2.6. Precision and Rounding

Monetary amounts are stored as integer cents. Where a calculation multiplies integer cents by an integer count (the standard per-seat deposit), the result is an exact integer product and no rounding occurs. Where a calculation multiplies cents by a fraction (the tiered cancellation fee, and each component of a private-dining deposit), the result is rounded **half up** to a whole cent. The settled reliability score is a percentage rounded **half up** to one decimal place. Durations are expressed in whole minutes; every datetime in a response is rendered as ISO 8601 UTC with three fractional digits.

### 2.7. Hierarchical Consistency and Cascades

Mutations are immediate and atomic: whenever an operation triggers a cascade, every downstream effect completes inside the same request that triggered it, and every entity touched along the way has its `updated_at` refreshed and its `version` incremented (for entities that carry a `version`). There are three principal cascade families. A **table-freeing cascade** runs whenever a table's future slot is released — by an early or late cancellation, by bussing a dirty table, or by a declined waitlist offer — and re-runs waitlist promotion to notify the next eligible party. A **no-show / late-cancel fiscal cascade** runs when a fee-bearing transition fires: it captures or releases the deposit, accrues a strike, recomputes reliability, and — if the strike threshold is reached — blocks the customer, which itself mass-cancels that customer's remaining future bookings. A **buyout cascade** runs when a private-dining event is confirmed: the area is occupied and every colliding reservation is cancelled with its hold released. These chains are described in full in §3.

### 2.8. Nested Retrieval and Foreign-Key Resolution

Several read paths are nested under a parent — for example, listing the special requests attached to a reservation. Path identifiers are validated strictly left to right: the parent `id` in the path is resolved before any child lookup, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). The same rule governs request bodies: every foreign key carried in a body (such as `restaurant_id`, `customer_id`, `table_id`, `dining_area_id`, or `reservation_id`) must resolve to an existing entity, validated in left-to-right order, and the first unresolved reference yields `ERR_NOT_FOUND`. List endpoints expose filter parameters precisely so that records reachable only by foreign key can still be retrieved — for instance, deposit holds by `reservation_id`, reservations by `restaurant_id`, `customer_id`, or `table_id`, waitlist entries additionally by `converted_reservation_id`, and notifications by `subject_type` and `subject_id`. The reservation, deposit-hold, waitlist-entry, and private-dining-event list endpoints additionally accept a `status` filter that narrows results to records in the named lifecycle state — the same `status` field every such entity exposes.

### 2.9. Optimistic Concurrency on Shared Inventory

Two write paths guard against acting on a stale view of shared inventory by means of an optimistic-concurrency token.

When a reservation is created, the request must carry `expected_table_version` holding the `version` of the target `Table` that the client last observed. If that value does not equal the table's current `version` — because a prior create or reschedule has legitimately occupied an overlapping window on that table and advanced its `version` since the client read it — the create is rejected with `ERR_STALE_TABLE_VERSION` (HTTP 412), preventing the client from booking over a slot it never actually saw as free. The same token and the same rejection apply when a reservation is rescheduled onto a (possibly new) table: `expected_table_version` must match that target table's live `version`.

When a private-dining buyout is confirmed, the request must carry `expected_dining_area_version` holding the `version` of the target `DiningArea` that the client last observed. If that value does not equal the area's current `version` — because another buyout has legitimately confirmed and occupied the same area window, advancing its `version` since the client read it — the confirm is rejected with `ERR_STALE_AREA_VERSION` (HTTP 412). Endpoints other than reservation create, reservation reschedule, and buyout confirm do not take a version token.

### 2.10. Validation Ordering

When an endpoint is guarded by several checks, they are evaluated in a fixed priority order so that the rejection a caller receives is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN`), then existence of every path id and body foreign key (`ERR_NOT_FOUND`), then — for transition endpoints — whether the target entity is in a state from which the transition is defined (`ERR_INVALID_STATE`). After those four come the business checks, in this order: resource ownership for a customer actor (`ERR_NOT_RESOURCE_OWNER`), then the blocked-customer safety check (`ERR_CUSTOMER_BLOCKED`), then the restaurant-open check (`ERR_RESTAURANT_CLOSED`), then party-size matching (`ERR_PARTY_SIZE_MISMATCH`), then the service-period/slot check (`ERR_OUTSIDE_SERVICE_PERIOD`), then table overlap (`ERR_TABLE_DOUBLE_BOOKED`), then area-buyout overlap (`ERR_AREA_BOUGHT_OUT`), then pacing (`ERR_PACING_EXCEEDED`), then the deposit-on-confirm check (`ERR_DEPOSIT_REQUIRED`), and finally the optimistic-concurrency token check (`ERR_STALE_TABLE_VERSION` / `ERR_STALE_AREA_VERSION`). A request that fails an earlier check is rejected on that check and the later checks are not consulted. Malformed bodies — a missing required field, a bad enum value, a phone that does not match the required format, a negative integer where a non-negative one is required, or a `deposit_pct` outside the zero-to-one range — are rejected with `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Restaurant and Its Floor

A `Manager` establishes the bookable world. Creating a restaurant fixes its display `name` (which must be non-empty) and a family of policy knobs, each of which may be supplied or left to its default. The `default_turn_time_minutes` is the dwell time a reservation consumes when its table does not override it; it defaults to 90 and must be between 30 and 360 minutes inclusive. The `cleanup_buffer_minutes` is appended after a reservation's dwell window before the same table may be re-occupied; it defaults to 15 and must be between 0 and 60 inclusive. The `late_cancel_cutoff_hours` is the number of hours before a booking's start at or after which a cancellation counts as "late" and becomes fee-bearing; it defaults to 24 and must be between 0 and 168 inclusive. The `no_show_strike_block_threshold` is the strike count at or above which a guest is automatically blocked; it defaults to 3 and must be at least 1. The `per_seat_deposit_cents` is the standard refundable deposit charged per seat and defaults to 2500 (twenty-five dollars), and must be non-negative. The `deposit_required_party_threshold` is the party size at or above which a booking must be backed by a deposit before it can be confirmed; it defaults to 6 and must be at least 1. A restaurant is born `OPEN`; a manager may later close it, which makes it reject all new reservations and waitlist joins, or re-open it.

Under a restaurant a manager lays out **dining areas**. A `DiningArea` carries its parent `restaurant_id`, a non-empty `name` label such as MAIN_ROOM or PATIO, and a `kind` that is either `STANDARD` (hosting ordinary reservations) or `PRIVATE` (a room that can be bought out wholesale); `kind` defaults to `STANDARD`. An area begins `AVAILABLE` and becomes `BOUGHT_OUT` while a confirmed buyout occupies its window. Inside an area a manager places **tables**. A `Table` carries its `dining_area_id`, a `label` that must be unique within its dining area, and the party-size band it will seat: `min_party_size` (defaulting to 1, at least 1) is the smallest party it accepts and `max_party_size` is the largest, which must be greater than or equal to `min_party_size`. A table may override the restaurant's dwell time through `turn_time_minutes`; when this is left null the restaurant default applies, and when supplied it must be between 30 and 360 minutes inclusive. A table is born `AVAILABLE` (and at `version` 1); it becomes `SEATED` while a party dines, `DIRTY` after they leave and before it is bussed, and `OUT_OF_SERVICE` when a manager manually disables it. Taking a table out of service, returning it to service, and bussing a dirty table each set the table's status accordingly and increment the table's `version`; bussing additionally frees the slot and triggers the table-freeing cascade that re-runs waitlist promotion.

Finally a manager defines **service periods**. A `ServicePeriod` carries its `restaurant_id`, a non-empty `name` such as DINNER, the `start_local_time` and `end_local_time` bounding its window, the `slot_interval_minutes` granularity (15, 30, or 60; default 30), and the `pacing_max_covers_per_slot` — the ceiling on how many total covers may have their start land on any one slot-grid time across the whole restaurant, which must be at least 1.

### 3.2. Registering Guests and Tracking Reliability

A guest joins the system by self-registering, which requires no authentication. Registration takes a non-empty `full_name`, a `phone` in E.164 form (it must match a leading plus sign followed by a non-zero digit and then six to fourteen further digits, and must be unique across all customers), and an optional `email` which defaults to null. A registration whose `phone` duplicates an existing customer's is rejected with `ERR_DUPLICATE_PHONE` (HTTP 409); a malformed `phone` is an `ERR_VALIDATION` failure. A new `Customer` is `ACTIVE` with `no_show_strikes` at 0.

Each customer accumulates a settled history. The `lifetime_reservations` field counts bookings that reached `COMPLETED`; the `lifetime_failures` field counts bookings that ended in `NO_SHOW` or in a late `CANCELLED`; and `no_show_strikes` counts the same fee-bearing failures, driving the auto-block. The `settled_reliability_pct` is the customer's score over closed history. It begins at 100.0, and whenever a booking reaches `COMPLETED`, `NO_SHOW`, or a late `CANCELLED`, it is recomputed: let the denominator be the sum of `lifetime_reservations` and `lifetime_failures`; if that denominator is zero the score is 100.0, otherwise the score is one hundred multiplied by `lifetime_reservations` divided by that denominator, rounded half up to one decimal place.

The reliability read offers two variants selected by a `mode` query parameter. In the default **settled** mode the response reports the stored score over closed history only. In **provisional** mode the projection treats every one of the customer's currently `CONFIRMED` (open) reservations as if it will succeed: both the numerator and the denominator add the count of those open confirmed bookings, so the projected score generally differs from the settled score for the same guest. The reliability response is a small object reporting `customer_id`, the selected `mode`, the resulting `reliability_pct`, the underlying `lifetime_reservations` and `lifetime_failures`, and `open_confirmed_count` (the number of open confirmed bookings, which is zero in settled mode and the projected count in provisional mode).

A manager may block a guest directly, and the system blocks a guest automatically when strikes reach the threshold (see §3.5). Blocking sets the customer's status to `BLOCKED` and cascades: for every reservation of that customer that is `CONFIRMED` or `REQUESTED` with a start in the future, the reservation is set `CANCELLED`, its cancellation fee is computed as an early cancellation (which yields zero), and any `HELD` deposit hold backing it is released. A `BLOCKED` guest cannot create or confirm a reservation or join the waitlist; such attempts are rejected with `ERR_CUSTOMER_BLOCKED`. A manager may later unblock the guest, which returns them to `ACTIVE` and clears `no_show_strikes` back to 0.

### 3.3. Booking a Table: Creation, Pacing, and the Turn Window

A guest (acting on their own behalf) or a host books a specific table. The create payload names the `restaurant_id`, the `customer_id`, the chosen `table_id`, the `expected_table_version` optimistic-concurrency token, the `party_size` (at least 1), and the `reservation_start` instant. A new reservation is born `REQUESTED`.

Creation runs a battery of checks in the priority order of §2.10. The acting guest must not be `BLOCKED`. The restaurant must be `OPEN`, else `ERR_RESTAURANT_CLOSED`. The `party_size` must fall within the chosen table's band — at least its `min_party_size` and at most its `max_party_size` — else `ERR_PARTY_SIZE_MISMATCH`. The booking's local start must lie inside a service-period window and align to its slot grid, else `ERR_OUTSIDE_SERVICE_PERIOD`. The booking must not collide on its table or on a buyout (see §3.4), and it must respect pacing. Finally `expected_table_version` must match the table's live `version`, else `ERR_STALE_TABLE_VERSION`.

On a successful create the system computes the booking's dwell window. The **effective turn time** is the table's `turn_time_minutes` when that override is present, and otherwise the restaurant's `default_turn_time_minutes`. The `turn_window_end` is the `reservation_start` plus the effective turn time in minutes, and the `release_at` is `turn_window_end` plus the restaurant's `cleanup_buffer_minutes` — the instant after which the table frees for the next booking. The system also sets `deposit_required` to true exactly when `party_size` is greater than or equal to the restaurant's `deposit_required_party_threshold`. A `cancellation_fee_cents` of 0 is recorded; it stays 0 until a fee-bearing transition fires. Creating the reservation increments the target table's `version` by one.

**Pacing** caps how busy a single slot may get. Floor the booking's `reservation_start` onto the service-period slot grid (the open time stepped forward by whole multiples of `slot_interval_minutes`) to get its slot-grid time. The current load of that slot is the sum of `party_size` over all reservations of the same restaurant that are `REQUESTED`, `CONFIRMED`, or `SEATED` and whose `reservation_start` lands on the same slot-grid time. The projected load is the current load plus this booking's `party_size`. The booking is accepted only when the projected load is less than or equal to the period's `pacing_max_covers_per_slot`; a projected load equal to the cap is allowed, and one greater than the cap is rejected with `ERR_PACING_EXCEEDED`.

**Table overlap** prevents double-booking. A booking's occupied window runs from its `reservation_start` inclusive up to its `release_at` exclusive — the cleanup buffer is already baked into `release_at`. The new window must not intersect the window of any active reservation on the same `table_id`; an intersection is rejected with `ERR_TABLE_DOUBLE_BOOKED`.

### 3.4. Deposits, Confirmation, and Private-Dining Buyouts

When a booking requires a deposit, a guest or host places a credit-card hold against it before it can be confirmed. Placing a hold records the `card_last4` (the four display digits of the card) and computes the held `amount_cents` as the restaurant's `per_seat_deposit_cents` multiplied by the reservation's `party_size` — an exact integer product. The new `DepositHold` references its `reservation_id`, is born `HELD`, and starts with `captured_cents` at 0. A second hold may not be placed on a reservation that already carries a hold that is neither `RELEASED` nor `EXPIRED`; that attempt is rejected with `ERR_DUPLICATE_DEPOSIT_HOLD`.

**Confirmation** is a host action moving a reservation from `REQUESTED` to `CONFIRMED`. It requires that the reservation is `REQUESTED`, that the referenced customer is `ACTIVE`, that the held table is present (the `table_id` is set) and in a status of `AVAILABLE` or `DIRTY` (not `OUT_OF_SERVICE`), and — when `deposit_required` is true — that a `DepositHold` for this reservation exists in `HELD` status. A confirm attempted on a deposit-required booking with no held deposit is rejected with `ERR_DEPOSIT_REQUIRED` (HTTP 402); confirmation places no hold of its own, it merely requires the hold to already exist. A successful confirm sets the reservation `CONFIRMED` and emits a `Notification` with template `RESERVATION_CONFIRMED` to the customer's phone.

**Private dining** lets a manager sell a private area wholesale. Opening an inquiry records the `restaurant_id`, the `dining_area_id` of the target `PRIVATE` area, the host-of-record `customer_id`, the `party_size`, the `event_start` and `event_end` bounding the buyout window, the contracted `food_minimum_cents`, the confirming-deposit fraction `deposit_pct` (defaulting to 0.25, between 0 and 1 inclusive), and the prepaid `service_charge_pct` (defaulting to 0.0, between 0 and 1 inclusive). A `deposit_pct` or `service_charge_pct` outside the zero-to-one range is an `ERR_VALIDATION` failure. The event is born `INQUIRY`.

A manager **proposes** the event, which is allowed only from `INQUIRY` and only when the referenced area's `kind` is `PRIVATE` — proposing on a non-private area is rejected with `ERR_AREA_NOT_PRIVATE`. Proposing computes the `deposit_due_cents` and moves the event to `PROPOSED`. The confirming deposit has **two components, each rounded separately to whole cents and then summed, in that pinned order**: the food component is `food_minimum_cents` multiplied by `deposit_pct`, rounded half up to a whole cent; the service component is `food_minimum_cents` multiplied by `service_charge_pct`, rounded half up to a whole cent; and `deposit_due_cents` is the food component plus the service component. The rounding must be applied to each component before they are added — summing the two raw products and rounding once is incorrect, because the two orders can diverge by a cent. From `PROPOSED` a manager may **revise** the event back to `INQUIRY` to re-price it (a loop that may repeat), or **cancel** it, or **confirm** it.

**Confirming** a buyout requires the event to be `PROPOSED`, the area to be `AVAILABLE`, no other `CONFIRMED` private-dining event on the same `dining_area_id` to overlap the closed window from `event_start` to `event_end`, and `expected_dining_area_version` to match the area's live `version`. On confirm the area is set `BOUGHT_OUT` and its `version` is incremented; every `CONFIRMED` or `REQUESTED` reservation whose `table_id` belongs to this dining area and whose own window from `reservation_start` up to `release_at` intersects the buyout window from `event_start` to `event_end` is cancelled, and each such reservation's `HELD` deposit hold is released; the event becomes `CONFIRMED`. A manager **completes** a `CONFIRMED` event, which returns the area to `AVAILABLE` and sets the event `COMPLETED`. A manager may **cancel** an event from `INQUIRY`, `PROPOSED`, or `CONFIRMED`; cancelling a `CONFIRMED` event additionally returns the area to `AVAILABLE` and increments the area's `version`.

The buyout also constrains ordinary booking. A reservation create or reschedule whose window would intersect a `CONFIRMED` buyout's closed window on the table's dining area is rejected with `ERR_AREA_BOUGHT_OUT`, and likewise a buyout confirm that would collide with an existing confirmed buyout window on the same area is rejected with `ERR_AREA_BOUGHT_OUT`.

### 3.5. Seating, Completion, No-Shows, and the Strike Cascade

Once a booking is `CONFIRMED`, the floor lifecycle is the host's domain. **Seating** a confirmed party requires the reservation to be `CONFIRMED` and its table to be `AVAILABLE` or `DIRTY`; it moves the reservation to `SEATED` and sets the table `SEATED`. **Completing** a `SEATED` reservation moves it to `COMPLETED`, increments the customer's `lifetime_reservations` and recomputes the customer's reliability, sets the table `DIRTY` (so it must be bussed before re-use), and releases any `HELD` deposit hold because the guest honoured the booking.

**No-show** is the punitive path. A host may mark a `CONFIRMED` reservation as a no-show only once the current time is at or after the booking's start plus a fifteen-minute grace; marking earlier is rejected with `ERR_NO_SHOW_TOO_EARLY`. A no-show computes the cancellation fee in its no-show variant — always the full per-seat deposit times the party size — captures that amount on any `HELD` hold by setting its `captured_cents` to the fee and its status to `CAPTURED`, increments the customer's `no_show_strikes` and `lifetime_failures`, recomputes reliability, emits a `Notification` with template `NO_SHOW_FEE_CHARGED`, and sets the reservation `NO_SHOW`. If the increment brings `no_show_strikes` to or above the restaurant's `no_show_strike_block_threshold`, the customer is set `BLOCKED`, which cascades into the mass-cancellation of that customer's remaining future `CONFIRMED` or `REQUESTED` reservations and the release of their held deposits, as described in §3.2.

The **cancellation fee** is computed whenever a confirmed booking is cancelled late or marked as a no-show. Let the per-seat amount be the restaurant's `per_seat_deposit_cents`, let the headcount be the reservation's `party_size`, and let the hours-before-start be the reservation's start minus the current time expressed in hours (which is negative once the start has passed). For a **no-show** the fee is the full per-seat amount times the headcount — one hundred percent — regardless of timing. For a **late cancel** the fee is tiered by how far ahead of the start the cancel lands: if the hours-before-start is greater than or equal to the restaurant's `late_cancel_cutoff_hours` the cancel is early and the fee is 0; otherwise, if the hours-before-start is greater than or equal to 2 the fee is one-half of the per-seat amount times the headcount, rounded half up to a whole cent; otherwise (less than two hours out) the fee is the full per-seat amount times the headcount. In every case, when a `HELD` deposit hold exists, the fee is capped at that hold's `amount_cents` — the captured amount can never exceed what was held.

### 3.6. The Cancellation and Reschedule Loops

A guest or host may **cancel** a reservation that is `REQUESTED` or `CONFIRMED`; a guest acting as `Customer` may only cancel their own (else `ERR_NOT_RESOURCE_OWNER`). Cancelling a `REQUESTED` reservation simply sets it `CANCELLED` and releases any `HELD` hold with no fee, since a request that was never confirmed is treated as an early cancellation yielding a zero fee. Cancelling a `CONFIRMED` reservation computes the cancellation fee per §3.5: if the fee is greater than zero it captures that amount on any `HELD` hold (setting `captured_cents` to the fee and the hold `CAPTURED`), and if the fee is zero it releases the hold instead. A fee-bearing late cancel additionally increments the customer's `no_show_strikes` and `lifetime_failures`, recomputes reliability, and — if strikes reach the threshold — blocks the customer with its mass-cancel cascade. In all cases the reservation is set `CANCELLED` and the table's future slot frees: unless the table is currently `SEATED`, the freeing triggers the table-freeing cascade that promotes and notifies the next eligible waitlist party.

A guest or host may **reschedule** a `CONFIRMED` reservation, which is the cyclic edge back to `REQUESTED`. Reschedule is allowed only outside the late window — the current time must be strictly before the booking's start minus the restaurant's `late_cancel_cutoff_hours`; an attempt at or after that cutoff is rejected with `ERR_RESCHEDULE_TOO_LATE`. The reschedule payload supplies the (possibly new) `table_id`, the `expected_table_version` token for that target table, and the new `reservation_start`. The new start and table are re-checked against party-size matching, the service-period and slot grid, table overlap, area-buyout overlap, pacing, and the optimistic-concurrency token, exactly as on create. On success the system recomputes `turn_window_end` and `release_at` for the new start and table, returns the reservation to `REQUESTED`, and increments the target table's `version`.

### 3.7. Special Requests and Notifications

A guest or host may attach a **special request** to a reservation, naming a `category` — one of `DIETARY`, `SEATING`, `OCCASION`, `ACCESSIBILITY`, or `OTHER` — and a non-empty `note` of at most 500 characters describing the request. The request references its `reservation_id` and is born with `acknowledged` false. A host may acknowledge a request, which sets `acknowledged` true; once acknowledged it is immutable. The special requests for a reservation may be listed off that reservation.

The system records every guest-facing message it sends as a **notification**. A `Notification` is polymorphic: its `subject_type` is either `RESERVATION` or `WAITLIST_ENTRY`, and its `subject_id` resolves to a `Reservation` when the type is `RESERVATION` and to a `WaitlistEntry` when the type is `WAITLIST_ENTRY`. Each notification records its delivery `channel` (`SMS` or `EMAIL`, defaulting to `SMS`), the `template` fired — one of `WAITLIST_TABLE_READY`, `RESERVATION_CONFIRMED`, `RESERVATION_REMINDER`, `NO_SHOW_FEE_CHARGED`, or `RESERVATION_CANCELLED` — and the `to_phone`, a snapshot of the recipient customer's `phone` at send time. Notifications may be listed and filtered by `subject_type`, `subject_id`, and `channel` so that the messages tied to either a reservation or a waitlist entry are retrievable.

### 3.8. The Waitlist: Joining, Promotion, Notification, and Conversion

When no table is free, a guest or host puts the party on the waitlist. Joining records the `restaurant_id`, the `customer_id`, the `party_size` (at least 1), and the `requested_start` — the earliest start the party will accept. The entry is born `WAITING`, its `joined_at` is stamped by the server at join time (the `created_at` mirrors it), and this `joined_at` is the primary ordering key for promotion. A guest may not join a closed restaurant (`ERR_RESTAURANT_CLOSED`) or join while `BLOCKED` (`ERR_CUSTOMER_BLOCKED`).

**Promotion** decides which waiting party is offered a freed table. The candidate set is every `WAITING` entry for the same restaurant whose `party_size` fits some `AVAILABLE` table — that is, there exists an available table whose `min_party_size` is at most and whose `max_party_size` is at least the entry's `party_size`. Among the candidates the winner is the one with the lowest `notify_count`, breaking ties by the earliest `joined_at`; the record `id` is never used as a tie-break. Promotion runs both when a host explicitly notifies an entry and on every table-freeing cascade. Notifying an entry requires it to be `WAITING`, the restaurant to be `OPEN`, and the entry to be the promotion winner; if no `AVAILABLE` table fits the party, the notify is rejected with `ERR_NO_MATCHING_TABLE`. A successful notify moves the entry to `NOTIFIED`, sets its `notify_expires_at` to the current time plus a ten-minute offer window, and emits a `Notification` with template `WAITLIST_TABLE_READY` to the customer's phone.

A `NOTIFIED` entry has a bounded time to claim its table. **Converting** the entry requires it to be `NOTIFIED`, the current time to be at or before `notify_expires_at` (a conversion after the offer window is rejected with `ERR_NOTIFY_WINDOW_EXPIRED`), and an `AVAILABLE` table whose band contains the entry's `party_size` to exist (else `ERR_NO_MATCHING_TABLE`). Conversion takes a `table_id` for the matched table, creates a `CONFIRMED` reservation for that customer and party on that table starting at the current time, sets the entry's `converted_reservation_id` to the new reservation's `id`, and moves the entry to `CONVERTED`.

If the offered party does not respond, a host may **requeue** the entry, or the system requeues it once the offer window lapses; requeue applies from `NOTIFIED` and increments `notify_count` (which penalizes the party's future ordering), clears `notify_expires_at` back to null, and returns the entry to `WAITING`. A guest may **cancel** a waitlist entry that is `WAITING` or `NOTIFIED` (a guest acting as `Customer` only their own, else `ERR_NOT_RESOURCE_OWNER`); cancelling sets the entry `CANCELLED`, and cancelling an entry that was `NOTIFIED` frees that offer and re-runs promotion to notify the next eligible party. Finally, an entry that has been `WAITING` too long expires: when the clock advances past the entry's `requested_start` plus 120 minutes with no table secured, the entry is set `EXPIRED`.

### 3.9. Deposit-Hold Lifecycle and the Test Clock

A `DepositHold` is born `HELD`. It reaches `CAPTURED` either by the no-show or late-cancel cascade or by a manager's explicit capture, which is allowed only when the hold is `HELD` and its referenced reservation is `NO_SHOW` or `CANCELLED` with a `cancellation_fee_cents` greater than zero; capture sets `captured_cents` to that reservation's fee and the hold `CAPTURED`. It reaches `RELEASED` either by the completion or early-cancel cascade or by a manager's explicit release, which sets `captured_cents` to 0 and the hold `RELEASED`. A hold whose authorization window lapses — the clock advancing past the reservation's start plus seven days while the hold is still `HELD` — is set `EXPIRED`.

Because several transitions are time-gated — the fifteen-minute no-show grace, the late-cancel cutoff, the ten-minute waitlist offer window, the 120-minute waitlist expiry, and the seven-day hold expiry — a manager-only test capability pins the server's notion of the current UTC instant to a supplied `to_iso8601` value. Advancing that clock may fire system transitions, expiring overdue waitlist entries and lapsed holds when the affected entities are next touched.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201 with the created resource; reads and state-changing actions on existing resources return HTTP 200 with the affected resource (or, for the reliability and clock endpoints, the computed object). Error responses carry the appropriate 4xx status and an `error_id`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/restaurants` | Create a restaurant with turn/pacing/deposit/no-show policy | Manager |
| GET | `/restaurants/{id}` | Read a restaurant | Manager, Host, Customer |
| POST | `/restaurants/{id}/close` | Close the restaurant (rejects new bookings) | Manager |
| POST | `/restaurants/{id}/open` | Re-open the restaurant | Manager |
| POST | `/dining-areas` | Create a dining area under a restaurant | Manager |
| GET | `/dining-areas/{id}` | Read a dining area | Manager, Host, Customer |
| GET | `/dining-areas` | List dining areas, optionally filtered by restaurant | Manager, Host, Customer |
| POST | `/tables` | Create a table in a dining area | Manager |
| GET | `/tables/{id}` | Read a table | Manager, Host, Customer |
| GET | `/tables` | List tables, optionally filtered by dining area | Manager, Host, Customer |
| POST | `/tables/{id}/out-of-service` | Mark a table OUT_OF_SERVICE | Manager |
| POST | `/tables/{id}/return-to-service` | Return a table to AVAILABLE | Manager, Host |
| POST | `/tables/{id}/bus` | Buss a DIRTY table back to AVAILABLE | Host |
| POST | `/service-periods` | Create a service period with pacing config | Manager |
| GET | `/service-periods/{id}` | Read a service period | Manager, Host, Customer |
| GET | `/service-periods` | List service periods, optionally filtered by restaurant | Manager, Host, Customer |
| POST | `/customers` | Register a customer (self-service; no auth required) | Customer, Manager, Host |
| GET | `/customers/{id}` | Read a customer | Manager, Host, Customer |
| GET | `/customers/{id}/reliability` | Computed reliability score; mode selects settled or provisional | Manager, Host, Customer |
| POST | `/customers/{id}/block` | Manually block a customer | Manager |
| POST | `/customers/{id}/unblock` | Reinstate a blocked customer and clear strikes | Manager |
| POST | `/reservations` | Create a reservation (REQUESTED) on a specific table | Customer, Host |
| GET | `/reservations/{id}` | Read a reservation | Manager, Host, Customer |
| GET | `/reservations` | List reservations; filter by restaurant, customer, table, or status | Manager, Host, Customer |
| POST | `/reservations/{id}/deposit-holds` | Place a credit-card deposit hold for a reservation | Customer, Host |
| POST | `/reservations/{id}/confirm` | Confirm a REQUESTED reservation | Host |
| POST | `/reservations/{id}/reschedule` | Move a CONFIRMED reservation to a new start/table | Customer, Host |
| POST | `/reservations/{id}/cancel` | Cancel a REQUESTED or CONFIRMED reservation | Customer, Host |
| POST | `/reservations/{id}/seat` | Seat a CONFIRMED party | Host |
| POST | `/reservations/{id}/no-show` | Mark a CONFIRMED reservation NO_SHOW after grace | Host |
| POST | `/reservations/{id}/complete` | Complete a SEATED reservation | Host |
| GET | `/deposit-holds/{id}` | Read a deposit hold | Manager, Host, Customer |
| GET | `/deposit-holds` | List deposit holds, filterable by reservation | Manager, Host, Customer |
| POST | `/deposit-holds/{id}/capture` | Capture a HELD deposit against a fee-bearing reservation | Manager |
| POST | `/deposit-holds/{id}/release` | Release/void a HELD deposit | Manager |
| POST | `/waitlist-entries` | Join the waitlist for a restaurant | Customer, Host |
| GET | `/waitlist-entries/{id}` | Read a waitlist entry | Manager, Host, Customer |
| GET | `/waitlist-entries` | List waitlist entries; filter by restaurant, customer, or status | Manager, Host, Customer |
| POST | `/waitlist-entries/{id}/notify` | Notify the promotion-winning WAITING entry | Host |
| POST | `/waitlist-entries/{id}/convert` | Convert a NOTIFIED entry into a CONFIRMED reservation | Host |
| POST | `/waitlist-entries/{id}/requeue` | Return a NOTIFIED entry to WAITING | Host |
| POST | `/waitlist-entries/{id}/cancel` | Customer leaves the waitlist | Customer, Host |
| POST | `/reservations/{id}/special-requests` | Attach a special request to a reservation | Customer, Host |
| GET | `/reservations/{id}/special-requests` | List special requests for a reservation | Manager, Host, Customer |
| POST | `/special-requests/{id}/acknowledge` | Host acknowledges a special request | Host |
| GET | `/notifications/{id}` | Read a notification record | Manager, Host, Customer |
| GET | `/notifications` | List notification records; filter by subject | Manager, Host, Customer |
| POST | `/private-dining-events` | Open a private-dining inquiry for a PRIVATE area window | Manager |
| GET | `/private-dining-events/{id}` | Read a private dining event | Manager, Host, Customer |
| GET | `/private-dining-events` | List private dining events; filter by restaurant, area, or customer | Manager, Host, Customer |
| POST | `/private-dining-events/{id}/propose` | Move INQUIRY → PROPOSED, computing the confirming deposit | Manager |
| POST | `/private-dining-events/{id}/revise` | Send a PROPOSED event back to INQUIRY | Manager |
| POST | `/private-dining-events/{id}/confirm` | Confirm a buyout: occupy the area and cancel conflicts | Manager |
| POST | `/private-dining-events/{id}/complete` | Complete a CONFIRMED buyout, freeing the area | Manager |
| POST | `/private-dining-events/{id}/cancel` | Cancel a private dining event in any non-terminal state | Manager |
| POST | `/_clock/set_current_utc` | Test-only: set the server's notion of current UTC | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_CUSTOMER_BLOCKED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RESTAURANT_CLOSED` | 409 |
| `ERR_TABLE_DOUBLE_BOOKED` | 409 |
| `ERR_AREA_BOUGHT_OUT` | 409 |
| `ERR_PACING_EXCEEDED` | 409 |
| `ERR_NO_SHOW_TOO_EARLY` | 409 |
| `ERR_RESCHEDULE_TOO_LATE` | 409 |
| `ERR_PARTY_SIZE_MISMATCH` | 422 |
| `ERR_OUTSIDE_SERVICE_PERIOD` | 422 |
| `ERR_DEPOSIT_REQUIRED` | 402 |
| `ERR_AREA_NOT_PRIVATE` | 422 |
| `ERR_STALE_TABLE_VERSION` | 412 |
| `ERR_STALE_AREA_VERSION` | 412 |
| `ERR_NOTIFY_WINDOW_EXPIRED` | 409 |
| `ERR_NO_MATCHING_TABLE` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE_PHONE` | 409 |
| `ERR_DUPLICATE_DEPOSIT_HOLD` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
