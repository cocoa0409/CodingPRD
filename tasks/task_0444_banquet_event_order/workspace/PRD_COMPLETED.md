# Banquet Event Order API — Product Requirements Document

## 1. Introduction

The Banquet Event Order (BEO) API is the system of record for a hotel's catering sales operation, from the first telephone inquiry through to the post-event invoice. A catering sale is a long-lived negotiation: a client first asks whether a ballroom is free on a given date, sales places a soft hold on the space, a menu and an audio-visual package are assembled, a block of sleeping rooms is contracted for out-of-town guests, deposits are scheduled and collected, and — only on the day of the event — the real headcount is finally counted. Each of these milestones changes what the client owes, and the figures must reconcile to the cent. This API exists to make every one of those transitions explicit, auditable, and arithmetically exact.

Four professional roles collaborate on a single event but own different slices of it: a sales manager courts the client and shapes the order, a banquet captain locks the guaranteed headcount and runs the floor on the day, an accounting clerk handles deposits and payments, and a platform administrator manages the shared physical inventory of rooms. Because these actors frequently work the same event concurrently, the system applies optimistic concurrency control on the most contended write paths, enforces a forward-looking *estimate* before the event and a backward-looking *actual* afterward, and cascades every state change down to the dependent bookings, room blocks, and payment allocations so that no figure is ever left stale.

This document specifies the global contracts (Section 2), the business logic and lifecycle workflows (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5). The structural contracts in Section 2 are binding and precise; the business rules in Section 3 are deliberately woven through the narrative of each workflow and must be read in full.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation under the access-control matrix in Section 4, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `SalesManager`, `BanquetCaptain`, and `AccountingClerk`.

A `PlatformAdmin` provides operational override and manages the shared physical inventory — function rooms, hotel room blocks, and the logical clock — but cannot drive any of the event sales-lifecycle transitions. A `SalesManager` owns the event sales lifecycle: inquiry creation, space holds, room bookings, menu and service lines, and cancellation, acting as the booking author. A `BanquetCaptain` owns guarantee locking and post-event actualization, the day-of operations, but may not create inquiries or edit pricing lines. An `AccountingClerk` owns deposits, the payment schedule, payments, and room-block pickup and release accounting, but may not drive sales or guarantee transitions.

All four roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `SalesManager`, `BanquetCaptain`, or `AccountingClerk`, the accompanying `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`, and no resource ownership is derived from it. Authorization is therefore decided purely by role, not by which specific operator is acting.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and an explicitly supplied value must be at least 1 and at most 100. The `offset` parameter specifies how many leading items to skip; when omitted it defaults to 0. A `limit` or `offset` query value that is non-integer or out of these bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order, with ties broken by ascending order of creation (the order in which the resources were inserted).

Every paginated list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system — function rooms, hotel room blocks, events, function-room bookings, menu lines, service lines, room-block links, and payment-schedule items — carry a standard set of system-managed fields. The `id` is a server-minted UUID used purely as identity, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording when the resource was last modified; it is refreshed on every mutation. The `version` field is an integer that begins at its initial value of 1 and increments by one on every mutation of the resource; it underpins the optimistic concurrency control described in Section 2.7.

One entity is deliberately leaner. A **Payment** is an immutable, append-only event-log record: it carries only an `id` and a `created_at`, and has neither an `updated_at` nor a `version` field. Its `created_at` is the ISO 8601 UTC receipt timestamp, and it doubles as the replay ordering key when payments must be re-evaluated. The only mutation a payment ever undergoes is being voided, which flips a status flag rather than rewriting the record.

### 2.5. Hierarchical Consistency and Cascading State

The catering event is an aggregate root. Its function-room bookings, menu lines, service lines, room-block links, payment-schedule items, and payments are all children that reference the event through their `event_id`. Function rooms and hotel room blocks are *shared* resources that live outside any single event: a booking points at a function room through `function_room_id`, and a room-block link points at a hotel room block through `hotel_room_block_id`.

Because figures derived from children live on the parent event, any operation that changes a child must reconcile the parent, and any operation that changes the event headcount must reconcile every dependent child. These reconciliations are immediate and synchronous: the moment a triggering operation completes, all affected totals, allocations, and committed-room counts reflect the new reality. Each entity that is mutated as part of a cascade independently refreshes its own `updated_at` and increments its own `version`. The specific cascades — guarantee locks rippling into per-person menu lines, event cancellation freeing rooms and blocks, payment voids re-running the allocation waterfall, pickup recording shifting a block's committed rooms — are described where the relevant workflow lives in Section 3.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents; the field names that carry them end in `_cents`. Line-level subtotals — the extension of a menu line, the extension of a service line, the rental charge of a booking, and the sums of those — are exact integer additions and multiplications with no rounding.

Percentage-derived charges are the only place rounding occurs. The service charge, the gratuity, and the sales tax are each computed by multiplying a base by a rate and then rounding the result to the nearest whole cent using the round-half-up convention (a fractional cent of exactly one half rounds upward). This rounding is applied **independently to each of the three components, in the fixed order** service charge first, then gratuity, then sales tax — each is rounded to a whole cent *before* it is added into any running total. The system never sums the three at full precision and rounds once at the end. The exact bases each percentage multiplies are specified in Section 3 alongside the charge rollup.

### 2.7. Optimistic Concurrency Control

Two write paths on an event are guarded by optimistic concurrency control, because both legitimately change figures that another actor may be reading at the same moment. On each of these paths the request body must carry a non-optional `expected_event_version` field, which the client populates with the `version` of the event it last observed.

When a `SalesManager` creates a function-room booking on an event, the request must carry `expected_event_version` equal to that event's current `version`. A new booking changes the event's room-hold composition; if another writer has advanced the event's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client cannot append a booking to event state it has not observed. A successful booking create increments the event's `version` by one.

Likewise, when an `AccountingClerk` records a payment on an event, the request must carry `expected_event_version` equal to that event's current `version`. Because each applied payment re-runs the payment allocation and shifts the outstanding balance, a payment carrying a stale event version is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the current balance before paying again. A successful payment record increments the event's `version` by one.

No other endpoint takes a version field; only booking creation and payment recording carry the `expected_event_version` guard. The `ERR_STALE_VERSION` check is evaluated after the Section 2.8 header, role, existence, and body-validation gates have passed — including resolution of any foreign key carried in the body — so a request whose body is malformed or whose referenced resource is missing surfaces that failure (HTTP 400 or 404) ahead of any version mismatch.

### 2.8. Nested Resource Validation and Request Ordering

Every request is validated through a fixed precedence so that failures surface deterministically. The headers are checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED` (HTTP 401). The acting role's permission for the operation is checked next, yielding `ERR_FORBIDDEN` (HTTP 403) when the role is not authorized. Existence is checked third: every resource named in the path is resolved left to right — the event before any booking, link, schedule item, or payment nested beneath it — and every foreign key carried in the body (a `function_room_id` or a `hotel_room_block_id`) must resolve; any unresolved reference yields `ERR_NOT_FOUND` (HTTP 404), reported against the first missing identifier encountered. For write operations, the request body is then checked: it must be present, all required fields supplied with the correct types (a required string field must be a non-empty string, and an integer field must be a genuine integer rather than a boolean or a floating-point value), and every enum-typed value must fall within its declared domain; a malformed, incomplete, mistyped, or out-of-range body yields `ERR_INVALID_REQUEST` (HTTP 400). State is checked next: a transition endpoint whose target resource is not in a valid state for the requested transition — for example, locking the guarantee on an event that is not `DEFINITE`, or voiding a payment that is not `APPLIED` — is rejected with the generic `ERR_INVALID_STATE` (HTTP 409). On a transition endpoint, this state gate is evaluated before any transition-specific body field it accepts (such as `guarantee_count`, `actual_attendance`, or `rooms_picked_up`) is validated, so an out-of-state target surfaces `ERR_INVALID_STATE` even when that body field is also missing or malformed. Only after these gates does the system evaluate the remaining business rules.

When a body field carries a percentage — `overset_pct`, `service_charge_pct`, `gratuity_pct`, or `sales_tax_pct` — that falls outside its permitted range, the request is rejected with `ERR_VALIDATION_RANGE` (HTTP 422). The permitted ranges are stated with each field in Section 3.

### 2.9. The Logical Clock

All "now" reads in the system — most importantly the date against which booking windows and room-block nights are reasoned about — come from a server logical clock, never from wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and it holds that value until a `PlatformAdmin` advances it. An administrative test-driving capability sets the clock to a supplied instant carried in the `to_iso8601` field, and the response echoes the resulting `current_utc`. Before any such call the clock never falls back to the host's real time.

## 3. Business Logic & Workflows

### 3.1. Shared Inventory: Function Rooms and Hotel Room Blocks

Before any event can reserve space, the shared physical inventory must exist. A `PlatformAdmin` or a `SalesManager` creates a **function room** by supplying its `name`, its `max_capacity` (the largest guest count any setup style could seat, which must be at least 1), and its `hourly_rental_cents` (the base rental charged per started hour of a booked window, which must be at least 0). An optional `turnover_buffer_minutes` records the minutes of forced clean-and-reset time that must stay free both immediately before and immediately after every confirmed booking on that room; it defaults to 60 and must be at least 0. A new room is born with `status` set to `ACTIVE`; a room's `status` is either `ACTIVE` or `RETIRED`.

A `PlatformAdmin` or a `SalesManager` creates a **hotel room block** — a contracted batch of sleeping rooms — by supplying its `block_name`, its `total_rooms` (at least 1), and its `nightly_rate_cents` (the negotiated informational nightly rate per room, at least 0). The block tracks two computed figures. The `rooms_committed` count is the number of rooms currently spoken for across all of the block's links, and `rooms_available` is `total_rooms` minus `rooms_committed`, never allowed to go negative. A freshly created block has zero rooms committed and all rooms available. The precise way each link contributes to `rooms_committed` is governed by the room-block accounting in Section 3.6.

Both function rooms and hotel room blocks are addressable on their own and are also reverse-navigable: the bookings made against a particular function room can be listed, and the links made against a particular hotel room block can be listed. Read access to all inventory is open to all four roles.

### 3.2. Opening and Holding an Event

A `SalesManager` opens the sales cycle by creating an **event inquiry**, supplying the client's `account_name`, the `event_date` as an ISO date, the seating `setup_style`, and the planning `expected_attendance` (at least 1). The `setup_style` is one of `ROUNDS`, `THEATER`, `CLASSROOM`, or `RECEPTION`; it determines how many of a room's seats are usable, as described in Section 3.4. Four pricing rates may optionally be supplied at creation, each defaulting and bounded as follows: `overset_pct`, the kitchen overset fraction the venue agrees to prepare above the guarantee, defaults to 0.05 and must be between 0 and 0.10 inclusive; `service_charge_pct`, the taxable service-charge rate, defaults to 0.22 and must be between 0 and 0.30 inclusive; `gratuity_pct`, the non-taxable gratuity rate, defaults to 0.0 and must be between 0 and 0.25 inclusive; and `sales_tax_pct`, the sales-tax rate, defaults to 0.08 and must be between 0 and 0.15 inclusive. A percentage outside its range is rejected with `ERR_VALIDATION_RANGE`.

A new event begins in `INQUIRY` status with `guarantee_count` and `actual_attendance` both null, and with all of its computed totals derived from an empty set of children, which evaluate to zero. An event's lifecycle status is one of `INQUIRY`, `TENTATIVE`, `DEFINITE`, `CONFIRMED`, `COMPLETED`, or `CANCELLED`; the last two are terminal. Beyond the inputs above, an event exposes several computed figures on read: `billable_count` (the headcount that per-person charges bill against), `estimated_total_cents` (the forward-looking grand total), `actualized_total_cents` (the final grand total, null until the event reaches `COMPLETED`), `paid_to_date_cents` (the sum of applied payments), and `balance_due_cents` (the outstanding balance).

The first lifecycle move is placing a soft space hold, taking the event from `INQUIRY` to `TENTATIVE`. A `SalesManager` may do this only once the event has at least one function-room booking and every booking on the event sits in either `HOLD` or `DEFINITE` occupancy; if no non-released booking exists the move is rejected with `ERR_NO_BOOKINGS`. The hold changes no charges — it merely marks the space as soft-held.

Confirming the space advances the event from `TENTATIVE` to `DEFINITE`. The `SalesManager` may do this only when the event has at least one booking — otherwise `ERR_NO_BOOKINGS` — and every booking on the event has been flipped to `DEFINITE` occupancy with none left in `HOLD`; if any booking is still soft-held the move is rejected with `ERR_BOOKING_NOT_ALL_DEFINITE`. On success the event's `estimated_total_cents` is recomputed using the estimate variant of the charge rollup described in Section 3.7.

### 3.3. Booking Function-Room Windows and Their Occupancy

Within an event, a `SalesManager` reserves a slice of a function room's calendar by creating a **booking**, supplying the `function_room_id` of the room, the window's `start_utc` and `end_utc` as ISO 8601 UTC instants (the end must be strictly after the start), and optionally a `setup_diagram_url` pointing at the room's setup diagram, which defaults to null. The booking create is one of the two optimistic-concurrency-guarded writes: it must carry `expected_event_version`, and a stale value is rejected with `ERR_STALE_VERSION` as described in Section 2.7; on success the event's `version` increments by one. A new booking is born in `HOLD` occupancy with its `rental_charge_cents` computed immediately. A booking's `hold_status` occupancy dimension is independent of the event's lifecycle and is one of `HOLD`, `DEFINITE`, or `RELEASED`, the last being terminal.

The room rental of a booking is computed as follows. A released booking — one in `RELEASED` occupancy — always carries a `rental_charge_cents` of zero. Otherwise the rental is charged per *started* hour: the system takes the window's duration in minutes (the gap from `start_utc` to `end_utc`), divides by the 60 minutes in an hour and rounds **up** to a whole number of billed hours, and multiplies that hour count by the room's `hourly_rental_cents`. Because the rounding is upward, a two-hour-and-one-minute window bills three hours, while a window whose duration is an exact multiple of 60 minutes bills no extra hour. The rental is recomputed whenever a booking is made definite, whenever it is created already definite, and is forced to zero when a booking is released.

A `SalesManager` makes a booking definite, advancing its occupancy from `HOLD` to `DEFINITE`, only while the owning event is in `TENTATIVE` or `DEFINITE` status. Making a booking definite is gated by two business checks evaluated in this order. First comes the **buffered double-booking check** (the higher-priority of the two): the candidate booking's window, expanded on *both* sides by the room's `turnover_buffer_minutes` — that is, from `start_utc` minus the buffer to `end_utc` plus the buffer — must not intersect the raw, unexpanded window of any *other* `DEFINITE` booking on the same function room. Overlap is judged by strict inequality, so two windows that touch only at an endpoint after the buffer expansion (the expanded start of one exactly meeting the end of the other) do *not* collide. A genuine intersection is rejected with `ERR_ROOM_DOUBLE_BOOKED`. Second comes the **capacity gate** (described in Section 3.4): the room's effective seated capacity under the event's setup style must be at least the event's `billable_count`, otherwise the make-definite is rejected with `ERR_CAPACITY_EXCEEDED`. Only when both checks pass does the booking flip to `DEFINITE` and its `rental_charge_cents` recompute.

The reverse move, softening a booking, returns its occupancy from `DEFINITE` to `HOLD`, again only while the owning event is `TENTATIVE` or `DEFINITE`; this frees the buffered window so other rooms or bookings may claim it. Releasing a booking moves it from either `HOLD` or `DEFINITE` to the terminal `RELEASED` occupancy: its `rental_charge_cents` is set to zero and its window is freed entirely. A booking may be released by a `SalesManager` directly — permitted in any owning-event status so long as the booking itself is still `HOLD` or `DEFINITE` (a booking already `RELEASED` is rejected with `ERR_INVALID_STATE`) — or automatically by the system when its event is cancelled.

### 3.4. Setup Style and Effective Room Capacity

The capacity gate at make-definite time turns on how the event's `setup_style` reshapes a room's nominal `max_capacity` into usable seats. Each setup style carries a fixed seating factor: `ROUNDS` yields a factor of 0.6, `THEATER` a factor of 1.0, `CLASSROOM` a factor of 0.5, and `RECEPTION` a factor of 0.8. The effective seated capacity is the room's `max_capacity` multiplied by the factor for the event's setup style, with the product floored down to a whole number of seats. The gate then compares this effective capacity against the event's `billable_count`: if the effective capacity is below `billable_count`, making the booking definite is rejected with `ERR_CAPACITY_EXCEEDED`.

### 3.5. Headcount: Estimate, Guarantee, and Actual

The `billable_count` is the headcount every per-person charge bills against, and the system selects it in stages keyed to the event's status. Before any guarantee is locked — while the event is still gathering its order — `billable_count` is simply the planning `expected_attendance`. Once a guarantee has been locked (the event is `CONFIRMED` but not yet completed), `billable_count` becomes the guaranteed headcount inflated by the overset: the `guarantee_count` multiplied by one plus the `overset_pct`, rounded **up** to a whole number of covers — the venue prepares for that many. Once the event is `COMPLETED`, the overset inflation is dropped entirely and `billable_count` becomes the larger of the `guarantee_count` and the counted `actual_attendance`; the venue bills the greater of the firm guarantee and the real count, never the oversetted prep figure. These two readings are the **estimate** and **actual** variants of the headcount: the estimate variant applies while the event is `DEFINITE` or `CONFIRMED` and never reads `actual_attendance`, whereas the actual variant applies once `COMPLETED` and ignores `overset_pct` entirely.

A `BanquetCaptain` locks the guarantee, advancing the event from `DEFINITE` to `CONFIRMED`. This requires that the event currently be in `DEFINITE` status, that a `guarantee_count` of at least 1 be supplied in the request body — absent or below 1 it is rejected with `ERR_GUARANTEE_REQUIRED` — and that the deposit milestone be settled, as detailed in Section 3.8; an unsettled deposit is rejected with `ERR_DEPOSIT_UNSETTLED`. On success the system sets the event's `guarantee_count` to the supplied value, recomputes `billable_count` (now the oversetted guarantee), recomputes `estimated_total_cents` using the estimate variant of the charge rollup, and — because the per-person headcount has changed — recomputes the `extended_cents` of every `PER_PERSON` menu line on the event as a cascade.

A `BanquetCaptain` actualizes the event on the day, advancing it from `CONFIRMED` to the terminal `COMPLETED`. This requires that the event currently be in `CONFIRMED` status and that an `actual_attendance` of at least 0 be supplied in the request body. On success the system sets `actual_attendance` to the supplied value, recomputes `billable_count` (now the larger of guarantee and actual), recomputes the `extended_cents` of every `PER_PERSON` menu line as a cascade from that headcount change, computes `actualized_total_cents` using the actual variant of the charge rollup, and recomputes `balance_due_cents`. Actualization also performs a room-block cleanup: every still-`RESERVED` room-block link on the event that never recorded a pickup is automatically released, which as a second hop returns its rooms to each block's available pool (see Section 3.6).

Between confirmation and the day of the event, a material scope change can force a revision. A `SalesManager` reopens the event, dropping it from `DEFINITE` back to `TENTATIVE`, but only while the event is in `DEFINITE` status and the `guarantee_count` is still null — once a guarantee is locked the event has moved past `DEFINITE` and reopening is no longer available. Reopening reverts every `DEFINITE` booking on the event back to `HOLD` occupancy as a cascade and recomputes `estimated_total_cents` using the estimate variant.

### 3.6. Room-Block Linkage and Per-Night Capacity

To house out-of-town guests, an event is tied to a hotel room block through a **room-block link**, which a `SalesManager` or an `AccountingClerk` may create. The link supplies the `hotel_room_block_id` of the block, the `rooms_reserved` it claims from that block (at least 1), and the night range as a `check_in_date` and a `check_out_date`. The night interval is **half-open**: `check_in_date` is the first occupied night (inclusive), and `check_out_date` is the departure date (exclusive) — the night *of* `check_out_date` is not occupied, and `check_out_date` must be strictly after `check_in_date`. Two links where one departs the morning the other arrives therefore share no occupied night and never conflict. A new link is born in `RESERVED` status with its `rooms_picked_up` null until a pickup is recorded; a link's `link_status` is one of `RESERVED`, `PICKED_UP`, or `RELEASED`, the last being terminal.

Creating a link is gated by a **per-night aggregate-capacity check**. For every night in the candidate's half-open range, the system sums the rooms occupied that night by the block's other active links (those in `RESERVED` or `PICKED_UP` status), where a reserved link contributes its `rooms_reserved` and a picked-up link contributes its `rooms_picked_up`. The candidate is admitted only if, for *every* night in its own range, that night's already-occupied total plus the candidate's `rooms_reserved` does not exceed the block's `total_rooms`. Capacity is judged per night, not over the block's whole lifetime, so a link can be admitted on nights that have room even when the block is full on other nights. If any night in the candidate's range would be overbooked, the create is rejected with `ERR_BLOCK_INSUFFICIENT_ROOMS`. A successful link create recomputes the block's `rooms_committed` and `rooms_available`.

The block's `rooms_committed` is the sum, across all of the block's links, of each link's own contribution by status: a `RESERVED` link contributes its `rooms_reserved` (the optimistic hold), a `PICKED_UP` link contributes its `rooms_picked_up` (the realized count, which is at most the rooms reserved), and a `RELEASED` link contributes nothing. The block's `rooms_available` is `total_rooms` minus `rooms_committed`, never negative.

An `AccountingClerk` records pickup on a link, advancing it from `RESERVED` to `PICKED_UP`, only while the owning event is `CONFIRMED` or `COMPLETED`. The request supplies `rooms_picked_up`, which must fall within zero and the link's `rooms_reserved` inclusive; a value outside that range is rejected with `ERR_PICKUP_EXCEEDS_RESERVED`. On success the link's `rooms_picked_up` is set, and because the link now counts its realized figure instead of its reservation, the block's `rooms_committed` and `rooms_available` are recomputed — which may free rooms back to the available pool.

An `AccountingClerk` may release a link, moving it from either `RESERVED` or `PICKED_UP` to the terminal `RELEASED` status; a released link stops counting toward the block's committed rooms, returning its rooms to the available pool, so the block is recomputed. The system also releases links automatically: when an event is actualized, its un-picked-up reserved links are released, and when an event is cancelled, all of its non-released links are released — each released link, as a second hop, returns its committed rooms to its block's available pool. Links and blocks are reverse-navigable in both directions, and read access is open to all four roles.

### 3.7. Pricing the Order: Menu Lines, Service Lines, and the Charge Rollup

A `SalesManager` builds the food-and-beverage order out of **menu lines**. Each line carries a `name`, a `pricing_mode` of either `PER_PERSON` or `CONSUMPTION`, and a `unit_price_cents` (at least 0). A `PER_PERSON` line is priced off the event's headcount; a `CONSUMPTION` line is priced off a counted quantity. The two modes carry mutually exclusive field requirements: a `CONSUMPTION` line must supply a `consumption_qty` (at least 0 when set), and a `PER_PERSON` line must omit it. Supplying `consumption_qty` on a per-person line, or omitting it on a consumption line, is rejected with `ERR_PRICING_MODE_FIELD_MISMATCH`. A line's `extended_cents` total is its `unit_price_cents` multiplied by the event's `billable_count` for a `PER_PERSON` line, or its `unit_price_cents` multiplied by its `consumption_qty` for a `CONSUMPTION` line. A per-person line's extension therefore moves whenever the event's billable headcount changes, which is why locking the guarantee and actualizing both cascade into every per-person line.

A `SalesManager` adds non-food charges as **service lines**, each carrying a `category` of `AV`, `LABOR`, or `RENTAL_ITEM`, a free-text `description`, a `quantity` (at least 1, representing AV items, labor hours, or rental items), a `unit_price_cents` (at least 0), and a `gratuity_eligible` flag (defaulting to false) marking whether the line enters the service-charge and gratuity base. A service line's `extended_cents` is simply its `quantity` multiplied by its `unit_price_cents`. Menu lines and service lines may be removed while the event is not terminal; removing either recomputes the event's `estimated_total_cents`. Any attempt to edit lines on a `COMPLETED` or `CANCELLED` event is rejected with `ERR_EVENT_TERMINAL`. Adding a line likewise recomputes the event's `estimated_total_cents`.

The grand total is assembled by the **charge rollup**, whose evaluation order is pinned and whose component rounding follows Section 2.6. The system first sums the food-and-beverage subtotal as the total of every menu line's `extended_cents`, and the service subtotal as the total of every service line's `extended_cents`. The **gratuity base** is the food-and-beverage subtotal plus the `extended_cents` of only those service lines whose `gratuity_eligible` flag is true. The **rental subtotal** is the total of `rental_charge_cents` across every booking that is not in `RELEASED` occupancy. The service charge is the gratuity base multiplied by the event's `service_charge_pct`, rounded half-up to a whole cent; it is taxable. The gratuity is the gratuity base multiplied by the event's `gratuity_pct`, rounded half-up to a whole cent; it is not taxable. The taxable base is the food-and-beverage subtotal plus the service subtotal plus the rental subtotal plus the service charge. The sales tax is the taxable base multiplied by the event's `sales_tax_pct`, rounded half-up to a whole cent. The grand total is finally the food-and-beverage subtotal plus the service subtotal plus the rental subtotal plus the service charge plus the gratuity plus the sales tax. The three rounded components are computed in the order service charge, gratuity, sales tax, each rounded before entering the total.

The rollup runs in two variants distinguished only by which headcount feeds the per-person menu lines. The **estimate** variant writes the event's `estimated_total_cents` and applies while the event is `DEFINITE` or `CONFIRMED`, feeding per-person lines with the estimate headcount (the planning attendance, or the oversetted guarantee once locked). The **actual** variant writes the event's `actualized_total_cents` and applies once the event is `COMPLETED`, feeding per-person lines with the actual headcount (the larger of guarantee and actual); for the same line, service, and rental rows it can produce a different grand total whenever the real count differs from the oversetted guarantee. The estimate rollup is triggered on confirm-space, on guarantee lock, and on any menu, service, or booking mutation; the actual rollup is computed at actualization.

### 3.8. Deposits, the Payment Schedule, and the Allocation Waterfall

An `AccountingClerk` lays out the billing plan as a series of **payment-schedule items**, each a milestone carrying a `label`, a `due_date`, and an `amount_due_cents` (at least 1). At create time the system assigns each item a `sequence_no` — a 1-based ordinal that increases monotonically per event and pins the allocation order; the very first item created, with `sequence_no` equal to 1, is by convention the **deposit** milestone. Each item also exposes two computed fields: `allocated_cents`, the portion of paid money assigned to it, and `settled`, a boolean that is true exactly when its `allocated_cents` is at least its `amount_due_cents`.

Payments themselves are recorded by an `AccountingClerk` against the event. A **payment** supplies its `amount_cents` (at least 1) and a `method` of `CARD`, `ACH`, `CHECK`, or `WIRE`; it is born in `APPLIED` status (a payment's `status` is either `APPLIED` or `VOIDED`). Recording a payment is the second optimistic-concurrency-guarded write: it must carry `expected_event_version`, and a stale value is rejected with `ERR_STALE_VERSION` per Section 2.7; on success the event's `version` increments by one. Once recorded, the system recomputes the event's `paid_to_date_cents`, re-runs the allocation waterfall, and recomputes `balance_due_cents`.

The **allocation waterfall** distributes the total of all `APPLIED` payments — which is exactly the event's `paid_to_date_cents` — across the schedule items in ascending `sequence_no` order, filling each item before spilling into the next. Walking the items from `sequence_no` 1 upward, each item is allocated the smaller of the remaining unallocated pool and that item's `amount_due_cents`; the item's `allocated_cents` is set to that amount, its `settled` flag is set true when the amount allocated reaches its `amount_due_cents`, and the pool is reduced by the amount taken. Any pool left over after the last item is unallocated overpayment, which surfaces as a negative balance. Because `sequence_no` is unique per event, the order is unambiguous. The waterfall is re-run whenever a payment is applied, whenever a payment is voided, and whenever a new schedule item is created.

The event's `paid_to_date_cents` is the sum of `amount_cents` over the event's payments in `APPLIED` status. The `balance_due_cents` is the active grand total minus `paid_to_date_cents`: the active total is `actualized_total_cents` once the event is `COMPLETED`, and `estimated_total_cents` otherwise; a negative result means a credit is owed back to the client. Balance is recomputed on every payment apply or void, on guarantee lock, on actualization, and on any charge-rollup recompute.

The deposit gate on guarantee locking ties these together: the deposit milestone (the item whose `sequence_no` is 1) must be settled — its `allocated_cents` at least its `amount_due_cents` — before a `BanquetCaptain` may lock the guarantee, failing otherwise with `ERR_DEPOSIT_UNSETTLED`. An event that has no schedule items at all has no deposit milestone to settle, and lock-guarantee on it is likewise rejected with `ERR_DEPOSIT_UNSETTLED`.

### 3.9. Voiding Payments and Closing Out

An `AccountingClerk` may void a payment, flipping it from `APPLIED` to the terminal `VOIDED` status, but only while that payment is currently `APPLIED` and the owning event is not yet `COMPLETED` — a payment on a closed-out event cannot be voided, and the attempt is rejected with `ERR_EVENT_TERMINAL`. There is a further fiscal guard: a void is refused if removing the payment would leave a previously settled deposit milestone unsettled on a `CONFIRMED` event, because a deposit cannot be clawed back after confirmation; such a void is rejected with `ERR_DEPOSIT_LOCKED`. When a void succeeds, the voided payment is excluded from `paid_to_date_cents`, the allocation waterfall is re-run so every schedule item's `allocated_cents` and `settled` are recomputed, and the event's `balance_due_cents` is recomputed.

The terminal cancellation of an event is driven by a `SalesManager`, who may cancel an event from any non-terminal status — `INQUIRY`, `TENTATIVE`, `DEFINITE`, or `CONFIRMED` — moving it to the terminal `CANCELLED`. Cancellation unwinds the event fully: every non-released booking is released, every non-released room-block link is released (each returning its committed rooms to its block's available pool as a second hop), and both `estimated_total_cents` and `actualized_total_cents` are frozen at their last computed values.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created`. State-transition and mutation operations that act on an existing resource return a `200 OK`. Deletions return a `204 No Content`. The administrative clock-set capability returns a `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/function-rooms` | Create a function room | PlatformAdmin, SalesManager |
| GET | `/function-rooms/{id}` | Get a function room | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/function-rooms` | List function rooms (paginated, filterable by status) | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/function-rooms/{id}/bookings` | List bookings on a function room | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/hotel-room-blocks` | Create a hotel room block | PlatformAdmin, SalesManager |
| GET | `/hotel-room-blocks/{id}` | Get a hotel room block | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/hotel-room-blocks` | List hotel room blocks (paginated) | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/hotel-room-blocks/{id}/room-block-links` | List links on a hotel room block | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/events` | Create an event inquiry | SalesManager |
| GET | `/events/{id}` | Get an event with all computed totals | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/events` | List events (paginated, filterable by status) | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/events/{id}/hold` | Place a soft space hold (INQUIRY → TENTATIVE) | SalesManager |
| POST | `/events/{id}/confirm-space` | Confirm all bookings definite (TENTATIVE → DEFINITE) | SalesManager |
| POST | `/events/{id}/reopen` | Revision loop (DEFINITE → TENTATIVE) | SalesManager |
| POST | `/events/{id}/lock-guarantee` | Lock the guarantee (DEFINITE → CONFIRMED) | BanquetCaptain |
| POST | `/events/{id}/actualize` | Record actual attendance and finalize (CONFIRMED → COMPLETED) | BanquetCaptain |
| POST | `/events/{id}/cancel` | Cancel with full unwind | SalesManager |
| POST | `/events/{id}/bookings` | Create a function-room booking (OCC-guarded) | SalesManager |
| GET | `/events/{id}/bookings` | List bookings for an event | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/bookings` | List bookings filtered by function_room_id or event_id | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/events/{id}/bookings/{booking_id}` | Get one booking | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/events/{id}/bookings/{booking_id}/make-definite` | Claim the buffered window (HOLD → DEFINITE) | SalesManager |
| POST | `/events/{id}/bookings/{booking_id}/soften` | Release the buffered window (DEFINITE → HOLD) | SalesManager |
| POST | `/events/{id}/bookings/{booking_id}/release` | Drop the booking and zero its rental (→ RELEASED) | SalesManager |
| POST | `/events/{id}/menu-lines` | Add an F&B menu line | SalesManager |
| GET | `/events/{id}/menu-lines` | List menu lines for an event | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| DELETE | `/events/{id}/menu-lines/{menu_line_id}` | Remove a menu line | SalesManager |
| POST | `/events/{id}/service-lines` | Add an AV / labor / rental-item service line | SalesManager |
| GET | `/events/{id}/service-lines` | List service lines for an event | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| DELETE | `/events/{id}/service-lines/{service_line_id}` | Remove a service line | SalesManager |
| POST | `/events/{id}/room-block-links` | Link the event to a hotel room block and reserve rooms | SalesManager, AccountingClerk |
| GET | `/events/{id}/room-block-links` | List room-block links for an event | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| GET | `/room-block-links` | List room-block links filtered by hotel_room_block_id or event_id | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/events/{id}/room-block-links/{link_id}/record-pickup` | Record actual rooms picked up (RESERVED → PICKED_UP) | AccountingClerk |
| POST | `/events/{id}/room-block-links/{link_id}/release` | Return rooms to the block (→ RELEASED) | AccountingClerk |
| POST | `/events/{id}/payment-schedule-items` | Add a payment-schedule milestone | AccountingClerk |
| GET | `/events/{id}/payment-schedule-items` | List schedule milestones for an event | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/events/{id}/payments` | Record a received payment (OCC-guarded) | AccountingClerk |
| GET | `/events/{id}/payments` | List payments for an event (filterable by status) | PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk |
| POST | `/events/{id}/payments/{payment_id}/void` | Reverse a payment and re-run the waterfall (APPLIED → VOIDED) | AccountingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PRICING_MODE_FIELD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PICKUP_EXCEEDS_RESERVED` | 422 Unprocessable Entity |
| `ERR_BLOCK_INSUFFICIENT_ROOMS` | 409 Conflict |
| `ERR_DEPOSIT_UNSETTLED` | 409 Conflict |
| `ERR_DEPOSIT_LOCKED` | 409 Conflict |
| `ERR_GUARANTEE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_BOOKINGS` | 409 Conflict |
| `ERR_BOOKING_NOT_ALL_DEFINITE` | 409 Conflict |
| `ERR_EVENT_TERMINAL` | 409 Conflict |
| `ERR_VALIDATION_RANGE` | 422 Unprocessable Entity |
