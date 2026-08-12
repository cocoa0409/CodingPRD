# Mobile Coffee Cart Events API — Product Requirements Document

## 1. Introduction

A mobile coffee-cart catering business runs on coordination. Every event ties together a physical cart, a drink package, one or more working baristas, consumable inventory, a travel leg from the depot to the venue, and a trail of money — a deposit to hold the date, a balance after the cups are poured, and occasionally a refund when plans fall apart. This document specifies the Mobile Coffee Cart Events API, the booking and operations backbone for that business, covering the entire arc from a customer's first quote request through event-day service and final settlement. All resources are mounted under the `/coffee-cart` prefix.

Two design pressures shape everything that follows. First, pricing is deliberately dual-variant: a package may be priced flat or metered per cup, and travel may be charged as a banded flat fee or metered per kilometer, with the chosen variants pinned onto the booking at submission so the numbers never drift after the fact. Second, the schedule is adversarial — carts cannot be in two places at once, baristas have weekly hour caps and skill certifications, venues may or may not supply power and water, and cancellations are priced by how much notice was given. A logical clock, rather than the wall clock, drives every time-sensitive rule, so lead times, amendment windows, and automatic event-start transitions are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly three roles: `OperationsManager`, `Client`, and `Barista`. Failure to provide both headers, or supplying a role outside this declared set, results in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400). Access to individual operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with an `ERR_UNAUTHORIZED` error (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `OperationsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client; ownership checks on any resource that references a Client — most importantly an EventBooking's `client_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Barista`, `X-User-ID` is the `id` of the acting Barista; ownership checks on any resource that references a Barista — such as a BaristaAssignment's `barista_id` — compare that foreign-key field to `X-User-ID`.

Ownership is enforced exactly where the acting role's identity matters: a Client may create a booking only for their own `client_id`, may run the Client booking-lifecycle actions (attach an add-on, submit, reopen, amend, cancel, create a payment) only on their own bookings, sees only their own bookings in the bookings list regardless of the `client_id` filter supplied, and may list a booking's child collections (add-ons, assignments, reservations, payments) only for their own bookings; a Barista may accept, decline, or withdraw only their own assignments. Single-resource fetches by id — a booking, client, barista, assignment, or payment — and the per-barista assignment list carry no ownership scoping: any caller holding one of the endpoint's authorized roles may read them.

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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Out-of-range or malformed pagination input — a non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` — is rejected with `ERR_VALIDATION` (HTTP 400), never clamped. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties broken by insertion order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Beyond pagination, several list endpoints accept domain filters — for example `status` on most catalog and lifecycle lists, `skill_level` on the barista roster, `pricing_model` on the package catalog, and `kind` on a booking's payment history; the bookings list itself may be narrowed by `client_id`, `cart_id`, `package_id`, or `travel_zone_id`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-05-01T09:15:00.123Z`) recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp, refreshed upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that starts at 1 on creation and increments with every modification to the resource, serving as the basis for optimistic concurrency control.

Two resource types are exceptions to this convention. A BookingAddOn (the join record attaching an add-on to a booking) and a Payment each carry only `id` and `created_at` — both `updated_at` and `version` are absent from these two resources, because a BookingAddOn is immutable once attached and a Payment's state moves through explicit settlement actions rather than in-place edits.

### 2.5. The Logical Clock and Time-Driven Automation

Every temporal rule in the system reads a server-side logical clock, never the real wall clock. At server startup, before any adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z`; it must not fall back to real wall-clock time. An `OperationsManager`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; the supplied instant is accepted as given, with no forward-only constraint enforced. Setting the clock triggers every automatic transition whose preconditions are met at the new instant — most notably moving a `CONFIRMED` booking to `IN_PROGRESS` once the clock reaches its `event_start`. Automatic transitions are applied only at the moment the clock is set, never lazily during other requests. Booking lead-time checks, the amendment window, the cancellation window, cancellation notice-hours, and weekly hour-cap accounting all evaluate against this same clock.

### 2.6. Money, Precision, and Rounding

All monetary values are represented as integer cents — every field whose name ends in `_cents` holds a whole number of cents, and no monetary field stores a fractional value. Rounding behavior is fixed per calculation and never left to the implementer: the deposit due is rounded half-up to the nearest cent before its bounds are applied; cancellation refunds discard any fractional cent (the floor is taken as the final step); cup estimates and assignment durations are rounded up to the next whole unit. Percentages and fractional factors — the thirty percent deposit rate, the half refund haircut on short notice, the one-and-a-half cups estimated per guest — are applied as exact arithmetic factors, not approximations.

### 2.7. Optimistic Concurrency Control on Booking Submission

Submitting a booking is the one operation that participates in optimistic concurrency control, and it does so against two parent entities at once. The submission request must carry `expected_cart_version`, holding the `version` of the referenced CoffeeCart as the client last observed it, and `expected_primary_barista_version`, holding the `version` of the booking's primary Barista as the client last observed it. If the cart's current `version` has advanced beyond what the client observed — for instance because another booking was confirmed against the same cart, legitimately reducing that cart's effective availability — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, if the primary barista's current `version` has advanced — because another commitment landed against that barista's weekly hours — the submission is rejected with the same `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; endpoints not named here process mutations without an OCC check.

### 2.8. Nested Resource Retrieval

Requests that target nested resources are validated left to right along the path. When a path contains multiple identifiers — for example a booking followed by one of its collections — the server confirms each identifier in sequence, and the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource within its declared parent. The path-parameter identifiers used across the surface are `clientId`, `cartId`, `baristaId`, `packageId`, `addonId`, `zoneId`, `itemId`, `bookingId`, `assignmentId`, `reservationId`, `paymentId`, and the generic `id`. The same 404 rejection applies to foreign keys supplied in a request body — `client_id`, `package_id`, `cart_id`, `travel_zone_id`, `addon_id`, `barista_id`, or `item_id` — that do not resolve to existing entities.

### 2.9. Catalog Status Gating

Bookings are assembled from catalog entities, and every referenced catalog entity must be live at the moment it is used. A Package, CoffeeCart, TravelZone, AddOn, or InventoryItem referenced by a booking creation, a booking submission, a booking amendment, an add-on attach, or a reservation creation must be in `ACTIVE` status. Each entity family carries its own rejection code so operators can tell them apart: a non-`ACTIVE` Package yields `ERR_PACKAGE_NOT_ACTIVE` (HTTP 409), a non-`ACTIVE` CoffeeCart yields `ERR_CART_NOT_ACTIVE`, a non-`ACTIVE` TravelZone yields `ERR_ZONE_NOT_ACTIVE`, a non-`ACTIVE` AddOn yields `ERR_ADDON_NOT_ACTIVE`, and a non-`ACTIVE` InventoryItem yields `ERR_ITEM_NOT_ACTIVE` — all HTTP 409.

### 2.10. Validation Order

When several guards apply to one request, they are evaluated in a fixed global order so that failures surface deterministically. Header context is checked first: a missing or malformed user context yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Role permission comes second (`ERR_UNAUTHORIZED`). Path-identifier existence and parentage come third, and body-supplied foreign-key existence fourth — both reported as `ERR_RESOURCE_NOT_FOUND`. State-level checks come fifth: whether the target entity's status permits the requested transition (`ERR_INVALID_STATE`, HTTP 409) and whether referenced catalog entities are `ACTIVE` (the per-entity codes of §2.9). Business rules are evaluated last, in the endpoint-specific orders stated throughout §3. A request body that is structurally malformed — a missing required field, a wrongly typed value, or an undeclared field — is rejected with the generic `ERR_VALIDATION` (HTTP 400); this structural validation is evaluated after path-identifier existence and before body-supplied foreign-key existence. Ownership checks (§2.1) are applied once the identifiers they compare against have resolved — after the booking path lookup on nested routes, and after the body foreign-key lookups on booking creation.

## 3. Business Logic & Workflows

### 3.1. Stocking the Catalog: Clients, Carts, Baristas, and the Price Menu

An `OperationsManager` begins by onboarding the actors and assets the booking engine will reference. Each customer is registered as a Client with a `company_name` and a `contact_email`, the latter unique per client. A Client's `status` starts at `ACTIVE` and may later move to `SUSPENDED` or `CLOSED`.

Carts are registered with a unique `cart_code` (for example, CART-A), a `max_drinks_per_hour` integer describing the cart's throughput ceiling for capacity checks, two booleans — `requires_power_hookup` and `requires_water_hookup` — declaring whether the cart must plug into venue power and connect to a venue water line, and the depot coordinates `home_base_lat` and `home_base_lng` from which travel distance is measured. A cart's `status` is one of `ACTIVE`, `MAINTENANCE`, or `RETIRED`, starting at `ACTIVE`. Each cart also exposes `committed_event_count`, a read-only figure derived on read: the number of EventBooking rows in `CONFIRMED` or `IN_PROGRESS` status that reference the cart.

Baristas join the roster with a `full_name`, a `skill_level` of `JUNIOR`, `SENIOR`, or `LEAD` — the `LEAD` level being the one the branding add-on demands — a `latte_art_certified` flag, an `hourly_rate_cents` base pay figure in cents, and a `weekly_hour_cap` bounding committed hours per ISO week. A barista's `committed_hours_this_week` is read-only: the sum of `duration_hours` over all of that barista's assignments in `ACCEPTED` or `CONFIRMED` status, regardless of which week their events fall in. A new barista starts with `status` `ACTIVE` and `committed_hours_this_week` at zero; later the status may move to `ON_LEAVE` or `TERMINATED`.

The commercial catalog is four-sided. A Package carries a unique `package_code`, a `pricing_model` of `FLAT` or `PER_CUP` that selects the pricing variant used at quote time, a `base_hours` count of included service hours, an `included_drinks` count (zero for `PER_CUP` packages), a `flat_price_cents` (zero for `PER_CUP`), a `per_cup_price_cents` (zero for `FLAT`), a `per_cup_minimum_cents` acting as the floor of a `PER_CUP` quote (zero for `FLAT`), and a `max_guests` ceiling. An AddOn carries a unique `addon_code` — `LATTE_ART`, `BRANDING`, `EXTRA_HOUR`, or `SYRUP_FLIGHT` — a flat `price_cents`, and two staffing gates: `requires_lead_barista` means at least one assigned barista must hold `skill_level` `LEAD`, and `requires_latte_art_cert` means at least one assigned barista must be `latte_art_certified`. Packages and AddOns share a two-state catalog status of `ACTIVE` or `DISCONTINUED`.

Rounding out the catalog, a TravelZone is defined by a unique `zone_code` (`ZONE-1`, `ZONE-2`, or `ZONE-3`), a `max_distance_km` giving the exclusive upper bound of the zone's distance band, a `banded_fee_cents` flat fee used when the banded travel variant applies, a `per_km_rate_cents` used when the metered variant applies, and a `min_booking_subtotal_cents` that tier-gates the zone: a booking whose pre-travel subtotal falls short of that minimum may not select the zone. An InventoryItem carries a unique `sku`, an `on_hand_units` count of physical units in the depot, a read-only `reserved_units` tallying units held by live reservations, a read-only `consumed_units_lifetime` tallying units consumed by reconciled reservations, and a `reorder_threshold_units` low-stock alert line; new items start `ACTIVE` with both tallies at zero. Finally, a CancellationPolicyTier carries a unique `tier_code` (`T1`, `T2`, or `T3`), a `min_notice_hours` inclusive lower bound and a `max_notice_hours` exclusive upper bound for its notice band — with the sentinel value of minus one meaning unbounded — a `deposit_refund_pct` fraction between zero and one inclusive, and a `balance_waived` flag. TravelZones, InventoryItems, and CancellationPolicyTiers all start `ACTIVE` and may later be `DISCONTINUED`. The uniqueness claimed for `contact_email`, `cart_code`, `package_code`, `addon_code`, `zone_code`, `sku`, and `tier_code`, the illustrative code sets named above (`LATTE_ART`/`BRANDING`/`EXTRA_HOUR`/`SYRUP_FLIGHT`, `ZONE-1`–`ZONE-3`, `T1`–`T3`), and the cross-field zero conventions on Package price fields are declared data conventions for the operator to uphold: the server records what it is given and does not reject duplicates, out-of-set codes, or non-zero values in the conventionally-zero fields.

### 3.2. Opening a Quote and Outfitting the Booking

A `Client` opens a booking by naming its `client_id`, the chosen `package_id`, `cart_id`, and `travel_zone_id`, the service window `event_start` through `event_end` (both ISO 8601 UTC instants), the expected `guest_count`, the venue flags `venue_provides_power` and `venue_provides_water`, and the `distance_km` round-trip distance from the cart's home base to the venue — `distance_km` must be a non-negative integer, anything else failing structural validation with `ERR_VALIDATION` (HTTP 400). The new booking lands in `QUOTE` status, and its financial fields — `quoted_subtotal_cents`, `quoted_travel_fee_cents`, `quoted_total_cents`, and `deposit_due_cents` — stay at zero until the quote is submitted. The `package_id`, `cart_id`, and `travel_zone_id` cannot be edited in place once set; the amendment flow described in §3.8 is the only way to change them, and it works by rolling the booking back to `QUOTE`.

Creation validates in a fixed order. Once identifier existence (§2.8) and catalog liveness (§2.9) are established, the event window is checked: `event_end` must be later than `event_start`, and `event_start` must lie at least twenty-four hours ahead of the logical clock — any violation is rejected with `ERR_EVENT_WINDOW_INVALID` (HTTP 422). Venue compatibility follows: if the cart's `requires_power_hookup` is true then `venue_provides_power` must be true, and if the cart's `requires_water_hookup` is true then `venue_provides_water` must be true, with mismatches rejected as `ERR_VENUE_HOOKUP_MISMATCH` (HTTP 422). Guest count is checked last: `guest_count` must be at least one and at most the package's `max_guests`, otherwise the request fails with `ERR_GUEST_COUNT_OUT_OF_RANGE` (HTTP 422). The package's `max_guests` is a hard validation boundary, never a clamp.

While the booking sits in `QUOTE`, the client outfits it with add-ons by supplying an `addon_id` for each. Attaching creates a BookingAddOn whose `booking_id` ties it to the booking and whose `applied_price_cents` snapshots the AddOn's `price_cents` at attach time — the snapshot is immutable afterwards, so later catalog price changes never retroactively alter a quote. The attach also refreshes the booking's `updated_at`, without incrementing the booking's `version`. The same add-on may be attached to a booking more than once; each attach creates its own BookingAddOn row.

Stock is committed through inventory reservations. An `OperationsManager` creates a reservation against a `QUOTE` booking by supplying an `item_id` and a `qty_units` of at least one. Availability is strict: `qty_units` may not exceed the item's `on_hand_units` minus its `reserved_units`; requesting exactly the available amount is allowed, and requesting one more is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). A new reservation starts in `RESERVED` status, and the item's `reserved_units` immediately grows by `qty_units`. The reservation records `qty_consumed` starting at zero; that field is written later, when consumption is recorded after service.

Staffing begins with an offer. An `OperationsManager` offers the booking to a barista by supplying a `barista_id` and an `is_primary` flag; exactly one assignment per booking may be primary. Offers are accepted while the booking is `QUOTE`, `PENDING_DEPOSIT`, or `CONFIRMED` — any other booking state is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the barista's own `status` is not inspected at offer time. The primary constraint counts only non-terminal (`OFFERED`, `ACCEPTED`, or `CONFIRMED`) primary assignments, and offering a second live primary is rejected with `ERR_VALIDATION` (HTTP 400). The new BaristaAssignment starts in `OFFERED` status, carries the booking's `booking_id`, and exposes a read-only `duration_hours`: the length of the booking's service window measured in hours, with any partial hour rounded up to the next whole hour. This duration is the currency in which weekly hour caps are charged.

### 3.3. Pricing the Event: Subtotals, Travel, and the Deposit

Quote math runs in a fixed order: subtotal first, then the zone's tier gate, then the travel fee, then the total. The ordering resolves what would otherwise look like a circular dependency — the zone gate reads the subtotal, and the travel fee feeds the total.

The subtotal depends on the package's pricing variant, and the variant in force is recorded on the booking as `pricing_variant_used`. Under the `FLAT_PACKAGE` variant — selected when the package's `pricing_model` is `FLAT` — the `quoted_subtotal_cents` is the package's `flat_price_cents` plus the sum of `applied_price_cents` over every add-on attached to the booking. Under the `PER_CUP_METERED` variant — selected when the `pricing_model` is `PER_CUP` — the system estimates consumption at one and a half cups per guest: the `guest_count` is multiplied by one and a half and the result is rounded up to the next whole cup. That cup estimate is multiplied by the package's `per_cup_price_cents` to produce the metered amount; the subtotal is then the greater of the metered amount and the package's `per_cup_minimum_cents`, plus the sum of `applied_price_cents` over the attached add-ons.

The travel fee is dual-variant as well, and the selection is deterministic per booking: when `distance_km` is at most twenty-five kilometers the `METERED` variant applies and the `quoted_travel_fee_cents` is the `distance_km` multiplied by the zone's `per_km_rate_cents`; otherwise the `BANDED` variant applies and the fee is the zone's flat `banded_fee_cents`. The variant in force is recorded as `travel_variant_used`. Before any fee arithmetic runs, the zone's tier gate is evaluated: if the freshly computed `quoted_subtotal_cents` falls short of the zone's `min_booking_subtotal_cents`, the quote is rejected with `ERR_SUBTOTAL_BELOW_ZONE_MINIMUM` (HTTP 422). With subtotal and fee in hand, the `quoted_total_cents` is their sum.

The deposit scales with the total but is bounded. The raw figure is thirty percent of `quoted_total_cents`, rounded half-up to the nearest cent; the result is then clamped so that `deposit_due_cents` is never below one thousand cents and never above fifty thousand cents. Three read-only counters track the money actually received: `deposit_paid_cents` is the sum of succeeded payments of kind `DEPOSIT`, `balance_paid_cents` the sum of succeeded payments of kind `BALANCE`, and `refund_paid_cents` the sum of succeeded payments of kind `REFUND`. The `balance_due_cents` is what remains of the total after receipts: the `quoted_total_cents` minus `deposit_paid_cents` minus `balance_paid_cents`.

### 3.4. Staffing the Event: Offers, Acceptance, and Scheduling Limits

An offered assignment is the barista's to answer. Accepting moves it from `OFFERED` to `ACCEPTED`, and three conditions must hold: the assignment is still `OFFERED`, the barista's own `status` is `ACTIVE`, and the parent booking is in `QUOTE`, `PENDING_DEPOSIT`, or `CONFIRMED`. Two scheduling guards then run, in this order — the double-booking check first, the weekly cap second. The double-booking check treats every booking window as a half-open interval: the candidate's `event_start` up to but not including its `event_end` overlaps another of the same barista's assignments in `ACCEPTED` or `CONFIRMED` status only when the candidate's start falls before the other event's end and the other event's start falls before the candidate's end. Back-to-back events are explicitly allowed — one event ending exactly when the next begins is not an overlap. A genuine overlap is rejected with `ERR_BARISTA_DOUBLE_BOOKED` (HTTP 409). The weekly-cap check then projects the barista's load: the barista's `committed_hours_this_week` plus the candidate's `duration_hours` may land exactly on the `weekly_hour_cap`, but any projection above the cap is rejected with `ERR_WEEKLY_CAP_EXCEEDED` (HTTP 422). A successful accept adds the `duration_hours` to the barista's `committed_hours_this_week` and increments both the barista's `version` and the assignment's `version`.

Declining is simpler: a barista may turn an `OFFERED` assignment to `DECLINED`, optionally leaving a free-text `decline_reason`; the assignment's `version` increments. Withdrawal covers the case where a barista has second thoughts after accepting: an `ACCEPTED` assignment may be withdrawn to `CANCELLED` provided the parent booking has not yet reached `IN_PROGRESS` — there is no walking off mid-event — and the withdrawal subtracts the `duration_hours` from the barista's weekly commitment and increments the barista's `version`.

Several assignment moves are driven by the booking rather than by the barista. When a booking confirms, every assignment in `OFFERED` or `ACCEPTED` moves to `CONFIRMED`. When a booking is cancelled, every assignment in `OFFERED`, `ACCEPTED`, or `CONFIRMED` moves to `CANCELLED`, and cancelling a `CONFIRMED` assignment subtracts its hours from the barista's weekly tally. When a confirmed booking is amended, each `CONFIRMED` assignment returns to `OFFERED` — a re-offer loop that notifies the barista — subtracting its hours for now, to be re-added if the barista re-accepts. Every such booking-driven assignment transition increments the affected assignment's `version`.

After the event, an `OperationsManager` resolves each assignment still in `ACCEPTED` or `CONFIRMED` by logging attendance through the `attended` flag; resolution is only possible while the booking is `IN_PROGRESS` and the logical clock has reached the booking's `event_end`. An attended assignment closes as `COMPLETED`; an unattended one closes as `NO_SHOW`, and a no-show releases the barista's hours, subtracting the `duration_hours` from `committed_hours_this_week`. Resolution increments the assignment's `version` in both cases; a no-show additionally increments the barista's `version`, while an attended completion does not.

### 3.5. Submitting the Quote — and Reopening It

Submission is the moment a quote becomes a financial instrument. A `Client` submits a `QUOTE` booking, and the request must carry the two OCC tokens of §2.7, `expected_cart_version` and `expected_primary_barista_version`. The guards run in a fixed order: booking state first — anything not in `QUOTE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — then catalog liveness of everything the booking references: the package, the cart, the travel zone, every attached add-on, and the item behind each reservation still in `RESERVED` or `COMMITTED` (the per-entity codes of §2.9); then the cart's schedule, then the add-on skill gate, then staffing presence, then the zone minimum, and finally the two stale-version checks.

The cart-schedule guard deserves its own explanation because it is wider than naive overlap. Every booking occupies a buffered interval: its `event_start` minus ninety minutes of travel time through its `event_end` plus ninety minutes. A submission is rejected with `ERR_CART_DOUBLE_BOOKED` (HTTP 409) whenever that buffered window collides with the equally buffered window of any other booking in `PENDING_DEPOSIT`, `CONFIRMED`, or `IN_PROGRESS` status that shares the same cart — collision meaning the candidate's buffered start falls before the other's buffered end and the other's buffered start falls before the candidate's buffered end. Because the buffers extend each side, two events whose raw windows merely touch can still collide once travel time is added. The skill gate then inspects every attached add-on: for each add-on whose `requires_latte_art_cert` is true, at least one of the booking's assignments in `OFFERED`, `ACCEPTED`, or `CONFIRMED` must point to a `latte_art_certified` barista; for each add-on whose `requires_lead_barista` is true, at least one such assignment must point to a barista whose `skill_level` is `LEAD`. A shortfall on either front is rejected with `ERR_ADDON_SKILL_MISSING` (HTTP 422). Staffing presence requires at least one assignment in any non-terminal status, failing as `ERR_NO_BARISTA_ASSIGNED` (HTTP 422). The zone minimum re-checks the subtotal freshly recomputed within the submission request — the repricing of §3.3 runs at this point, before the stale-version checks — against the zone's `min_booking_subtotal_cents` (`ERR_SUBTOTAL_BELOW_ZONE_MINIMUM`), and the stale-version check rejects a mismatch on either OCC token with `ERR_STALE_VERSION` (HTTP 412). The primary-barista token is compared only when a non-terminal primary assignment exists: with no live primary, `expected_primary_barista_version` must still be present in the request but is accepted unchecked.

A successful submission reprices the booking within the same request: `quoted_subtotal_cents`, `quoted_travel_fee_cents`, and `quoted_total_cents` are recomputed per the pricing and travel variants of §3.3, `pricing_variant_used` and `travel_variant_used` are pinned to record which algorithms produced the numbers, and `deposit_due_cents` is recomputed from the fresh total. The booking moves from `QUOTE` to `PENDING_DEPOSIT`, and three versions increment together: the booking's own `version`, the referenced cart's `version`, and the primary barista's `version` — the last only when a live primary assignment exists.

Reopening unwinds a submission that has not yet been paid. A booking in `PENDING_DEPOSIT` returns to `QUOTE` only if no payment of kind `DEPOSIT` has ever succeeded for it — once a deposit has landed, the money must move through the refund path instead, and a reopen attempt is rejected with `ERR_DEPOSIT_ALREADY_PAID` (HTTP 409). Reopening clears the pinned `pricing_variant_used` and `travel_variant_used`, since both will be recomputed on the next submission, and increments the booking's `version`; the quoted figures and `deposit_due_cents` are left intact until that next submission recomputes them.

### 3.6. From Deposit to Event Day

Money moves through Payment rows created under a booking. Either a `Client` or an `OperationsManager` creates a payment by naming its `kind` — `DEPOSIT`, `BALANCE`, or `REFUND` — an `amount_cents` that is positive for every kind (a refund carries its positive magnitude), and a client-supplied `idempotency_key` unique per booking and kind. Every payment starts in `PENDING` status. Amount discipline is enforced at both creation and settlement: a `DEPOSIT` payment's amount must be at least the deposit still outstanding — the `deposit_due_cents` minus the `deposit_paid_cents` — a `BALANCE` payment must equal the `balance_due_cents` at pay time, and a `REFUND` payment must equal the computed cancellation refund; any mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Idempotency is key-scoped, and the idempotency check runs before amount discipline: repeating a creation with an `idempotency_key` whose payment already `SUCCEEDED` or is still `PENDING` returns that existing Payment row with no duplicate state change, a key whose only prior payment `FAILED` may be retried with any payload, and a key reused with a different payload against a `PENDING` or `SUCCEEDED` payment is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409). The `REFUND` amount check applies only once a cancellation has priced a refund; before that, any positive refund amount is accepted. Payments created automatically by the system — the completion-time `BALANCE` and the cancellation-time `REFUND` — carry a server-generated idempotency key rather than a client-supplied one.

Settlement is an `OperationsManager` action with kind-specific gates. Marking a `PENDING` payment succeeded requires, for `DEPOSIT`, that the booking sit in `PENDING_DEPOSIT` — otherwise the rejection is `ERR_BOOKING_NOT_AWAITING_DEPOSIT` (HTTP 409); for `BALANCE`, that the booking be in `CONFIRMED`, `IN_PROGRESS`, or `COMPLETED`; and for `REFUND`, that the booking be in `CANCELLED` — a failed `BALANCE` or `REFUND` gate is rejected with `ERR_INVALID_STATE` (HTTP 409). Two cascades fire off success. When a succeeded deposit pushes the booking's `deposit_paid_cents` to at least its `deposit_due_cents`, the booking automatically moves from `PENDING_DEPOSIT` to `CONFIRMED`: every assignment in `OFFERED` or `ACCEPTED` moves to `CONFIRMED`, every reservation in `RESERVED` moves to `COMMITTED` — still counted in the item's `reserved_units`, but no longer releasable through the amendment flow — the cart's derived `committed_event_count` reflects one more committed event, and each newly confirmed barista's `committed_hours_this_week` reflects the commitment. When a `REFUND` payment succeeds against a `CANCELLED` booking, the booking moves on to `REFUNDED`. Each such cascade also increments the booking's `version` as a marker of the change. A payment that cannot be settled is marked failed, moving from `PENDING` to the terminal `FAILED` status.

The ledger is held to a strict invariant. For every booking, the sum of succeeded `DEPOSIT` amounts plus the sum of succeeded `BALANCE` amounts minus the sum of succeeded `REFUND` amounts always equals that booking's `deposit_paid_cents` plus `balance_paid_cents` minus `refund_paid_cents`; and globally, total cents received minus total cents refunded across all bookings equals the sum of that same per-booking expression over every booking. Any drift from this equality is a bug — the invariant is conserved under every forward and compensating payment pair.

Event day arrives by the clock. When the logical clock reaches a `CONFIRMED` booking's `event_start`, the booking moves automatically to `IN_PROGRESS`, incrementing the booking's `version`; assignments stay `CONFIRMED` until they are individually resolved, since attendance is only known after the fact.

### 3.7. Wrapping Up: Completion, Consumption, and Reconciliation

Completion belongs to the `OperationsManager` and is gated on two clocks and one roster. The booking must be `IN_PROGRESS`, the logical clock must have reached the booking's `event_end` — a completion attempted earlier is rejected with `ERR_INVALID_STATE` (HTTP 409) — and no assignment may remain in `ACCEPTED` or `CONFIRMED`. If unresolved assignments remain, the completion is rejected with `ERR_UNRESOLVED_ASSIGNMENTS` (HTTP 409) — the operator either resolves each one first by logging attendance, or completes the booking once every assignment already sits in `COMPLETED`, `NO_SHOW`, `CANCELLED`, or `DECLINED`. Completion moves the booking to `COMPLETED` and — whenever `balance_due_cents` is still positive — automatically creates a `BALANCE` payment in `PENDING` status for that amount; reservations are left untouched in `COMMITTED` at completion, each moving to `PARTIALLY_CONSUMED` only when consumption is later recorded against it. The booking's `version` increments.

Consumption is recorded per reservation. Against a `COMMITTED` reservation — while its booking is `IN_PROGRESS`, or `COMPLETED` and still pending reconciliation — the operator writes the `qty_consumed`, which must lie between zero and the reservation's `qty_units` inclusive; anything outside that range is rejected with `ERR_CONSUMPTION_OUT_OF_RANGE` (HTTP 422). Recording consumption moves the reservation to `PARTIALLY_CONSUMED` and settles the item's books in one motion: the item's `reserved_units` drops by the full `qty_units` (the reservation is released in its entirety), its `on_hand_units` drops by the `qty_consumed` actually used, its `consumed_units_lifetime` grows by that same `qty_consumed`, and the item's `version` increments. Once the booking stands `COMPLETED`, the operator reconciles each `PARTIALLY_CONSUMED` reservation, moving it to the terminal `RECONCILED` status.

Inventory obeys its own conservation law. For every item, the units that have left the depot — the initial `on_hand_units` minus the current `on_hand_units` — always equal the `consumed_units_lifetime`, and the `reserved_units` always equal the sum of `qty_units` over that item's reservations in `RESERVED` or `COMMITTED` status. Creating a reservation and later releasing it must leave `reserved_units` exactly where it started; recording consumption is never compensated, but it is fully accounted, since `on_hand_units` and `consumed_units_lifetime` move together by the consumed quantity.

### 3.8. Amendment, Cancellation, and the Refund Policy

Amendment is the sanctioned path for changing a locked-in event. A `Client` may amend a `CONFIRMED` booking — revising any of `package_id`, `cart_id`, `travel_zone_id`, `event_start`, `event_end`, `guest_count`, `venue_provides_power`, `venue_provides_water`, or `distance_km` — but only while the event remains more than forty-eight hours ahead of the logical clock; inside that window the amendment is rejected with `ERR_AMEND_WINDOW_CLOSED` (HTTP 409). Every accepted amendment rolls the booking back from `CONFIRMED` to `QUOTE`, regardless of which fields were actually changed; fields not supplied in the request keep their current values. After the window check, the amendment verifies catalog liveness of the merged package, cart, and travel zone (the per-entity codes of §2.9) and then re-runs the creation-time validations on the merged values — event window, venue compatibility, guest range, and the cart's buffered schedule check. The unwind is thorough: every assignment in `CONFIRMED` returns to `OFFERED` in the re-offer loop, every reservation in `COMMITTED` returns to `RESERVED` while still holding its stock, the cart's derived `committed_event_count` drops accordingly, each affected barista's `committed_hours_this_week` is recomputed downward, and any `DEPOSIT` payments remain `SUCCEEDED` — the credit is carried forward, so `deposit_paid_cents` is unchanged. The booking's `version` increments, both the old and the new cart's `version` increment when the cart changed, and each affected barista's `version` increments. The pinned `pricing_variant_used` and `travel_variant_used` are cleared, while the quoted figures and `deposit_due_cents` are left intact until recomputed. The booking then awaits a fresh submission to be repriced.

Cancellation splits by how far the booking had progressed. From `QUOTE`, cancelling moves every assignment in `OFFERED` or `ACCEPTED` to `CANCELLED`, moves every reservation in `RESERVED` to `RELEASED` with each item's `reserved_units` dropping by the released quantity, and computes no refund because nothing was ever paid. From `PENDING_DEPOSIT`, the same cascades apply, but only while no `DEPOSIT` payment has succeeded — a booking with money down must travel the refund path instead.

Cancelling from `CONFIRMED` is the consequential case. It is permitted only while the logical clock still precedes the `event_start` — once service has begun, cancellation is rejected with `ERR_CANCEL_WINDOW_CLOSED` (HTTP 409). The unwind releases everything: assignments in `OFFERED`, `ACCEPTED`, or `CONFIRMED` move to `CANCELLED` with the affected baristas' weekly hours recomputed downward; reservations in `RESERVED` or `COMMITTED` move to `RELEASED` with `reserved_units` decremented per release; and the cart's derived `committed_event_count` drops. The client may attach an optional free-text `cancellation_reason`, and the server stamps `cancelled_at` with the moment of cancellation.

The refund itself is priced by notice. The notice in hours is the whole number of hours between the logical clock and the `event_start` — the difference in seconds, divided by an hour, with any fraction discarded. The applicable tier is the first `ACTIVE` CancellationPolicyTier, in creation order, whose band contains that notice: the `min_notice_hours` is inclusive, so a notice exactly equal to a tier's minimum belongs to that tier, while the `max_notice_hours` is exclusive, so a notice exactly equal to a tier's maximum belongs to the next tier up, and a maximum of minus one leaves the band unbounded above; if no `ACTIVE` tier's band contains the notice, the refund is zero. With at least one hundred sixty-eight hours of notice — seven full days — the refund is the `deposit_paid_cents` multiplied by the tier's `deposit_refund_pct`, with any fractional cent discarded. With less notice than that, the same product is additionally halved — multiplied by a short-notice factor of one half — before the fraction is discarded. Whenever the resulting refund is positive, the cancellation automatically creates a `REFUND` payment in `PENDING` status for exactly that amount, and its eventual success carries the booking from `CANCELLED` to `REFUNDED`. Independently, when the selected tier's `balance_waived` is true, the outstanding balance is waived by writing a `balance_waived_flag` marker that zeroes the booking's `balance_due_cents`.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone catalog entry or a new child resource within a booking — return a `201 Created` status code. Operations that modify an existing resource or drive a state transition return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coffee-cart/clients` | Register a new client | OperationsManager |
| GET | `/coffee-cart/clients` | List clients | OperationsManager |
| GET | `/coffee-cart/clients/{clientId}` | Fetch a client | OperationsManager, Client |
| POST | `/coffee-cart/carts` | Register a new coffee cart | OperationsManager |
| GET | `/coffee-cart/carts` | List carts | OperationsManager, Client |
| GET | `/coffee-cart/carts/{cartId}` | Fetch a cart | OperationsManager, Client |
| POST | `/coffee-cart/baristas` | Register a new barista | OperationsManager |
| GET | `/coffee-cart/baristas` | List baristas | OperationsManager, Barista |
| GET | `/coffee-cart/baristas/{baristaId}` | Fetch a barista (returns `committed_hours_this_week` and `version` for OCC) | OperationsManager, Barista, Client |
| POST | `/coffee-cart/packages` | Create a package catalog entry | OperationsManager |
| GET | `/coffee-cart/packages` | List packages | OperationsManager, Client |
| GET | `/coffee-cart/packages/{packageId}` | Fetch a package | OperationsManager, Client |
| POST | `/coffee-cart/addons` | Create an add-on catalog entry | OperationsManager |
| GET | `/coffee-cart/addons` | List add-ons | OperationsManager, Client |
| GET | `/coffee-cart/addons/{addonId}` | Fetch an add-on | OperationsManager, Client |
| GET | `/coffee-cart/addons/{id}/booking-addons` | List BookingAddOn rows referencing this add-on | OperationsManager |
| POST | `/coffee-cart/travel-zones` | Create a travel zone | OperationsManager |
| GET | `/coffee-cart/travel-zones` | List travel zones | OperationsManager, Client |
| GET | `/coffee-cart/travel-zones/{zoneId}` | Fetch a travel zone | OperationsManager, Client |
| POST | `/coffee-cart/inventory-items` | Create an inventory item | OperationsManager |
| GET | `/coffee-cart/inventory-items` | List inventory items | OperationsManager |
| GET | `/coffee-cart/inventory-items/{itemId}` | Fetch an inventory item | OperationsManager |
| GET | `/coffee-cart/inventory-items/{id}/reservations` | List InventoryReservation rows referencing this item | OperationsManager |
| POST | `/coffee-cart/cancellation-tiers` | Create a cancellation policy tier | OperationsManager |
| GET | `/coffee-cart/cancellation-tiers` | List cancellation policy tiers | OperationsManager, Client |
| POST | `/coffee-cart/bookings` | Create a new EventBooking in `QUOTE` status | Client |
| GET | `/coffee-cart/bookings` | List bookings (filtered) | OperationsManager, Client |
| GET | `/coffee-cart/bookings/{bookingId}` | Fetch a booking (returns `version` for OCC) | OperationsManager, Client, Barista |
| POST | `/coffee-cart/bookings/{id}/addons` | Attach an add-on to a `QUOTE` booking | Client |
| GET | `/coffee-cart/bookings/{id}/addons` | List add-ons attached to a booking | OperationsManager, Client |
| POST | `/coffee-cart/bookings/{id}/assignments` | Offer the booking to a barista (creates a BaristaAssignment in `OFFERED`) | OperationsManager |
| GET | `/coffee-cart/bookings/{id}/assignments` | List assignments for a booking | OperationsManager, Client, Barista |
| GET | `/coffee-cart/baristas/{id}/assignments` | List assignments for a barista | OperationsManager, Barista |
| POST | `/coffee-cart/bookings/{id}/reservations` | Create an InventoryReservation against a `QUOTE` booking | OperationsManager |
| GET | `/coffee-cart/bookings/{id}/reservations` | List inventory reservations for a booking | OperationsManager, Client |
| POST | `/coffee-cart/bookings/{bookingId}/submit` | Submit a `QUOTE` booking: recompute the quote, pin variants, transition to `PENDING_DEPOSIT` | Client |
| POST | `/coffee-cart/bookings/{bookingId}/reopen` | Reopen a `PENDING_DEPOSIT` booking back to `QUOTE` (deposit not yet paid) | Client |
| POST | `/coffee-cart/bookings/{bookingId}/amend` | Amend a `CONFIRMED` booking; rolls it back to `QUOTE` and re-opens assignments and reservations | Client |
| POST | `/coffee-cart/bookings/{bookingId}/cancel` | Cancel a booking from `QUOTE`, `PENDING_DEPOSIT`, or `CONFIRMED`; computes a refund if applicable | Client |
| POST | `/coffee-cart/bookings/{bookingId}/complete` | Mark an `IN_PROGRESS` booking as `COMPLETED` (after `event_end`, all assignments resolved) | OperationsManager |
| GET | `/coffee-cart/assignments/{assignmentId}` | Fetch an assignment | OperationsManager, Barista, Client |
| POST | `/coffee-cart/assignments/{assignmentId}/accept` | Barista accepts an `OFFERED` assignment | Barista |
| POST | `/coffee-cart/assignments/{assignmentId}/decline` | Barista declines an `OFFERED` assignment | Barista |
| POST | `/coffee-cart/assignments/{assignmentId}/withdraw` | Barista withdraws an `ACCEPTED` assignment before the event starts | Barista |
| POST | `/coffee-cart/assignments/{assignmentId}/resolve` | Resolve an assignment after event end (attendance logged) | OperationsManager |
| GET | `/coffee-cart/reservations/{reservationId}` | Fetch a reservation | OperationsManager |
| POST | `/coffee-cart/reservations/{reservationId}/record-consumption` | Record `qty_consumed` against a `COMMITTED` reservation (transitions to `PARTIALLY_CONSUMED`) | OperationsManager |
| POST | `/coffee-cart/reservations/{reservationId}/reconcile` | Reconcile a `PARTIALLY_CONSUMED` reservation after the booking is `COMPLETED` | OperationsManager |
| POST | `/coffee-cart/bookings/{id}/payments` | Create a payment (`DEPOSIT`, `BALANCE`, or `REFUND`); idempotent on `idempotency_key` | Client, OperationsManager |
| GET | `/coffee-cart/bookings/{id}/payments` | List payments for a booking | OperationsManager, Client |
| GET | `/coffee-cart/payments/{paymentId}` | Fetch a payment | OperationsManager, Client |
| POST | `/coffee-cart/payments/{paymentId}/mark-succeeded` | Mark a `PENDING` payment `SUCCEEDED`; cascades booking state if the deposit threshold or refund is reached | OperationsManager |
| POST | `/coffee-cart/payments/{paymentId}/mark-failed` | Mark a `PENDING` payment `FAILED` | OperationsManager |
| POST | `/coffee-cart/_clock/set_current_utc` | Set the logical clock; triggers automatic transitions whose preconditions are met | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PACKAGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CART_NOT_ACTIVE` | 409 Conflict |
| `ERR_ZONE_NOT_ACTIVE` | 409 Conflict |
| `ERR_ADDON_NOT_ACTIVE` | 409 Conflict |
| `ERR_ITEM_NOT_ACTIVE` | 409 Conflict |
| `ERR_EVENT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_VENUE_HOOKUP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CART_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_BARISTA_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_WEEKLY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_GUEST_COUNT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ADDON_SKILL_MISSING` | 422 Unprocessable Entity |
| `ERR_NO_BARISTA_ASSIGNED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |
| `ERR_SUBTOTAL_BELOW_ZONE_MINIMUM` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_AMEND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CANCEL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_UNRESOLVED_ASSIGNMENTS` | 409 Conflict |
| `ERR_CONSUMPTION_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_ALREADY_PAID` | 409 Conflict |
| `ERR_BOOKING_NOT_AWAITING_DEPOSIT` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
