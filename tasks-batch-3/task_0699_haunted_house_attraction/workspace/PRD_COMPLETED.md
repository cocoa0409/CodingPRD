# Haunted House Attraction API — Product Requirements Document

## 1. Introduction

Seasonal haunted-house operators run a deceptively complex business: a handful of physical attractions, each gated by timed-entry windows and a finite per-slot throughput, must be sold across three ticket tiers under demand-sensitive pricing, while a parallel operational reality — weather advisories, scare-actor staffing, safety waivers, and age clearances — can pause or shutter the gates at a moment's notice. This document specifies the back-office API that runs such an operation end to end, from venue creation through dynamic-priced reservations, season and group passes, actor scheduling, and the cascading closures that ripple through slots, reservations, and refunds when the weather turns severe or a scare zone falls below its minimum staffing.

The system is built around a logical clock so that entry windows, shift windows, and waiver expiry can all be exercised deterministically. Money is tracked exclusively in integer cents, capacity is reconciled against live occupancy counters, and concurrent capacity races on a single slot are resolved with optimistic concurrency control. The intent is a single source of truth for four distinct operational personas — operations managers who run the venue, box-office staff who sell and admit, scare actors who staff the zones, and guests who buy and attend — each with a narrow, well-defined set of verbs.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_MISSING_AUTH`. The system recognises exactly four roles, spelled precisely as follows: `OpsManager`, `BoxOffice`, `Guest`, and `Actor`. When a role attempts an operation it is not authorised for under the matrix in Section 4, the request is rejected with `ERR_ROLE_FORBIDDEN`.

The four roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest` entity; ownership checks on any guest-owned resource — a `Guest` record, a `Reservation`, a `Waiver`, a `Pass`, or a `Ticket` (whose owner is its reservation's `guest_id`) — compare the resource's owning `guest_id` (or, for the guest record itself, its `id`) to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER`. This `ERR_NOT_OWNER` rejection applies to single-resource reads and mutations; on a list endpoint a `Guest` is not rejected but instead has the returned collection silently scoped to only the resources they own. When `X-User-Role` is `OpsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authorisation but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `BoxOffice`, `X-User-ID` is an opaque operator identifier; box-office staff act on behalf of any guest and are not subject to the ownership check. Finally, when `X-User-Role` is `Actor`, `X-User-ID` is an opaque operator identifier that the server may record on an `ActorShift` as its `actor_user_id` when a shift is scheduled, but it is not compared to any entity's `id` for ownership purposes.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many leading items to skip and defaults to 0.

Unless a particular endpoint states otherwise, every list is returned sorted by the `created_at` timestamp in ascending order. The envelope's `meta` object for any list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and System-Managed Fields

Every top-level resource carries a server-minted `id` formatted as a UUID with no type prefix, plus a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on each mutation; this `version` is the basis for optimistic concurrency control (Section 2.10). The entities that carry the full set — `id`, `created_at`, `updated_at`, and `version` — are `Venue`, `Attraction`, `TimeSlot`, `Guest`, `Waiver`, `Reservation`, `Ticket`, `Pass`, `ScareZone`, `ActorShift`, and `Closure`.

Two entities are immutable after creation and therefore carry only an `id` and a `created_at`, with neither `updated_at` nor `version` present: the `PricingRule` and the `PassProduct`. Pricing rules and pass products are authored once and never mutated in place; to change pricing or a pass offering, operators create a new record rather than editing an existing one.

### 2.5. The Logical Clock and Time-Gated Behaviour

The system reads time from a logical clock rather than the wall clock. At server startup the clock holds exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it reads exactly this default and never falls back to real wall-clock time. An operations manager may advance or rewind the clock to any exact ISO 8601 UTC instant by supplying a `to_iso8601` value; the response reports the new clock as `current_utc`. Three families of rule consult this clock: waiver expiry (a waiver becomes invalid once the clock passes its `expires_at`), timed-entry admission windows, and actor shift windows. Whenever the clock moves, all of these are re-evaluated against the new instant.

### 2.6. Nested Resource Retrieval and Reference Validation

Many paths embed one or more resource identifiers — for example a slot is created under an attraction, a waiver under a guest, an actor shift under a scare zone. The system validates such identifiers strictly left to right: the first identifier in the path that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND`, before any deeper identifier or any request-body foreign key is examined. After path identifiers are resolved, body-level foreign keys are validated in turn, and any unresolved reference likewise yields `ERR_NOT_FOUND`. A request whose body is malformed, omits a required field, or supplies an invalid enumeration value is rejected earlier still with `ERR_INVALID_REQUEST`.

### 2.7. Monetary Values, Counters, and Rounding

All monetary amounts in the system are integer cents — `base_price_cents`, `price_cents`, `subtotal_cents`, `discount_cents`, `total_cents`, `wallet_credit_cents`, and the pass product's `price_cents`. Wherever a price computation introduces a fractional cent (notably demand surcharges and pass discounts), the result is rounded half up to the nearest whole cent. Where a calculation is purely additive or subtractive over whole cents — refunds, wallet draws, subtotals after per-line rounding — the arithmetic is exact and no rounding is required. Occupancy counters (`reserved_count`, `admitted_count`, `checked_in_count`, `open_attraction_count`, `redemptions_used`, `party_size`, `opened_reservation_refunds`) are exact integers, and the derived `demand_ratio` is a real number computed as live occupancy over capacity.

### 2.8. Capacity Reconciliation and Occupancy Counters

Each `TimeSlot` maintains two live occupancy counters that the system keeps reconciled with the reservations referencing it. The `reserved_count` is the number of party members currently held by reservations in the `RESERVED` entry state against that slot; the `admitted_count` is the number already admitted through the gate. The `demand_ratio` is always the sum of `reserved_count` and `admitted_count` divided by the slot's `capacity`, and it drives which dynamic-pricing band is active. These counters move only through the reservation lifecycle transitions described in Section 3 — confirmation raises `reserved_count`, admission shifts a member from `reserved_count` to `admitted_count`, and no-show or cancellation releases `reserved_count` — and any such movement increments the affected slot's `version` and recomputes `demand_ratio`.

### 2.9. Cascading Closures and Hierarchical State Propagation

When an attraction is paused or closed, the effect cascades downward through its slots and the reservations bound to them, and upward to the venue's posture. The precise cascades are specified in Section 3, but three system-wide invariants hold throughout. First, whenever a closure or weather event pauses an attraction, every one of its `SCHEDULED` slots is driven to `CLOSED`, and every reservation holding a ticket on a now-closed slot that is still in the `HELD` or `RESERVED` entry state is cancelled. Second, when such a cancelled reservation had already been paid, its payment is refunded to the owning guest's wallet credit, and the closure records the running tally on its `opened_reservation_refunds`. Third, every entity touched by a cascade has its `updated_at` refreshed and its `version` incremented, exactly as a direct client mutation would — the server performs these reconciliations automatically, without an explicit client request against each affected slot, reservation, or guest.

### 2.10. Optimistic Concurrency Control on Capacity Races

Confirming a reservation consumes slot capacity, and two clients reading the same slot can both believe capacity is free when only one of them can have it. To serialise these writers, the confirmation operation requires a non-optional `expected_time_slot_version` field carrying the client's last observed `version` of each referenced `TimeSlot`; this is supplied as a single integer that is compared against every distinct referenced `TimeSlot`. If any referenced slot's current `version` does not exactly equal the value the client supplied — because another confirmation has since incremented that slot's `reserved_count` and consumed capacity the earlier reader believed available — the confirmation is rejected with `ERR_STALE_TIME_SLOT_VERSION` and HTTP status 412. The client must re-read the slot and retry against the fresh version. No other endpoint takes `expected_time_slot_version`.

Several other write endpoints carry their own version-guard fields against a different parent. Setting venue weather requires `expected_venue_version` matching the venue's current `version`, and a mismatch is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412). Closing an attraction for the season, opening a closure on an attraction, and lifting a closure each require `expected_attraction_version` matching the target attraction's current `version`, and a mismatch is rejected with `ERR_STALE_ATTRACTION_VERSION` (HTTP 412). Revoking a waiver requires `expected_waiver_version` matching the waiver's current `version`, and a mismatch is rejected with `ERR_STALE_WAIVER_VERSION` (HTTP 412).

### 2.11. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed precedence so that the earliest applicable failure is the one reported. Authentication comes first: the presence of both headers (`ERR_MISSING_AUTH`), then role authorisation (`ERR_ROLE_FORBIDDEN`), then, for guest-owned resources, ownership (`ERR_NOT_OWNER`). Existence of every referenced resource follows (`ERR_NOT_FOUND`), then the requirement that the target be in a legal state for the requested transition (`ERR_INVALID_STATE`). Only after these structural gates do domain rules apply, and within the domain rules of a given endpoint the order is: age clearance, then waiver sufficiency, then scare-level clearance, then zone staffing, then the temporal-window checks, then the slot-overlap constraint and after it the capacity/throughput constraint, then sales-posture and pass-eligibility constraints, then referential consistency, then the stale-version guard, and finally the live capacity check. Section 3 places each individual rule beside the workflow it governs; the governing principle is that a structural failure is always surfaced ahead of a business failure, and an earlier-listed business failure ahead of a later one.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Venue and Its Attractions

An operations manager opens the season by creating a `Venue` with a display `name` and an informational `timezone` label. A fresh venue starts with `operational_state` of `OPEN`, `weather_status` of `CLEAR`, an `open_attraction_count` of zero, and `version` 1. Reading a venue returns its derived `operational_state` and live `open_attraction_count` alongside these fields.

Against an open venue, the manager creates each `Attraction` by supplying the parent's identifier, a `name`, a `min_age` that must be zero or greater, a `scare_level` from 1 through 5 expressing intensity, and a `throughput_per_slot` of at least 1 that caps how many guests any one slot of this attraction may admit. An optional `requires_waiver` flag declares whether every ticketed guest must hold a valid waiver to be admitted; when omitted it defaults to true. A new attraction begins life in `status` `OPEN`. Creating an open attraction raises the venue's `open_attraction_count` by one and recomputes the venue's `operational_state`.

The venue's `operational_state` is always derived from its weather and its open attractions: if `weather_status` is `SEVERE` the state is `SHUTDOWN`; otherwise if `weather_status` is `ADVISORY` the state is `RESTRICTED`; otherwise it is `OPEN`. The `open_attraction_count` is exactly the number of attractions under that venue whose `status` is `OPEN` — attractions in `PAUSED` or `CLOSED` are not counted.

### 3.2. Pricing, Slots, and the Shape of Demand

For each attraction the operations manager authors at most one `PricingRule` per ticket tier, naming the `tier` as `GA`, `FAST_PASS`, or `VIP` and a `base_price_cents` of zero or more. Each rule also defines the demand bands through four optional inputs: `low_demand_max_ratio` (the inclusive upper bound of the no-surge LOW band, default 0.5), `high_demand_min_ratio` (the demand level at or above which the HIGH band applies, default 0.8), `mid_surge_pct` (the percentage added in the MID band between those bounds, default 20), and `high_surge_pct` (the percentage added in the HIGH band, default 50). A pricing rule is immutable once written.

Timed-entry inventory is created as `TimeSlot` records under an attraction. The manager supplies the inclusive `window_start` and the exclusive `window_end` of the entry window as ISO 8601 UTC instants, together with a `capacity` of at least 1. A new slot must not overlap any existing `SCHEDULED` slot on the same attraction, and this overlap check is evaluated before the throughput check below. Overlap here uses half-open interval intersection: two slots conflict when one's start falls strictly before the other's end and vice versa; two windows that merely touch — where the existing slot's `window_end` equals the new slot's `window_start` — are permitted with zero buffer. An overlapping slot is rejected with `ERR_SLOT_OVERLAP`. Then, at creation the slot's `capacity` must not exceed the parent attraction's `throughput_per_slot`; a slot whose capacity is larger is rejected with `ERR_CAPACITY_OVER_THROUGHPUT`. A fresh slot starts in `status` `SCHEDULED` with `reserved_count`, `admitted_count`, and `demand_ratio` all zero.

The active pricing band for a ticket is selected from the demand snapshot at the moment of confirmation. Taking the slot's `demand_ratio` as it stands immediately before that confirmation's own capacity increment: if the ratio is at or below the rule's `low_demand_max_ratio`, no surge applies; if the ratio is at or above the rule's `high_demand_min_ratio`, the high surge applies; otherwise — strictly between the two bounds — the mid surge applies. The boundaries are precise: a ratio exactly equal to `low_demand_max_ratio` is treated as LOW, and a ratio exactly equal to `high_demand_min_ratio` is treated as HIGH.

### 3.3. Guests, Waivers, and Scare Clearance

A guest record is registered with a `full_name`, an `age` of zero or greater, and a contact `email`; a new `Guest` starts with `wallet_credit_cents` of zero and `version` 1. Either box-office staff or the guest themselves may create the record, and a guest may thereafter act only on their own resources.

Because most attractions demand a safety waiver, a guest signs a `Waiver` declaring the highest attraction intensity they accept as `max_scare_level`, a value from 1 through 5. At signing, the waiver's `signed_at` is stamped from the logical clock and its `expires_at` is computed as `signed_at` advanced by the standard validity period of fourteen days; the waiver begins in `status` `SIGNED`. A waiver is considered `EXPIRED` the moment the logical clock reaches or passes its `expires_at` — this expiry is derived on read and re-checked at admission rather than written by a transition. A guest or an operations manager may instead deliberately end a waiver early by revoking it, which moves a still-`SIGNED` waiver to the terminal `REVOKED` state and increments its `version`; revoking requires `expected_waiver_version` to match the waiver's current `version`.

Scare clearance threads through ticketing in two places. A ticket records the bearer's `max_scare_level`, which must be at least the attraction's `scare_level`; a ticket whose clearance is below the attraction's intensity is rejected with `ERR_SCARE_LEVEL_TOO_LOW`. Separately, at admission the guest's standing waiver — when the attraction's `requires_waiver` is true — must be `SIGNED`, not expired, and carry a `max_scare_level` at least equal to the attraction's `scare_level`; otherwise admission is rejected with `ERR_WAIVER_REQUIRED`.

### 3.4. Passes: Season and Group Discounts

An operations manager publishes a `PassProduct` under a venue, declaring its `kind` as either `SEASON` (a per-guest, multi-visit product) or `GROUP` (which bundles a minimum party), a flat `price_cents`, a `discount_pct` from 0 through 100 applied to reservation subtotals while the pass is active, a `max_redemptions` of at least 1 capping how many reservations an issued pass may discount, and a `min_party` of at least 1 that for a `GROUP` product is the minimum `party_size` required before the discount applies (it defaults to 1 when omitted, and is persisted as supplied regardless of `kind`; for a `SEASON` product `min_party` is never consulted during discounting, so its stored value does not affect eligibility). Like a pricing rule, a pass product is immutable.

A guest, or box-office staff acting for them, then purchases a `Pass` from a product by naming the `pass_product_id` and the holder's `guest_id`. The issued pass starts with `redemptions_used` of zero and `status` `ACTIVE`. Each confirmation that applies the pass raises `redemptions_used` by one; when it reaches the product's `max_redemptions`, the pass moves to `EXHAUSTED`. Cancelling a reservation that had consumed a redemption returns it: `redemptions_used` is decremented, and a pass that had become `EXHAUSTED` returns to `ACTIVE`. A pass may also be `CANCELLED`. Purchasing a pass is blocked when the venue's `operational_state` is `RESTRICTED` or `SHUTDOWN`.

### 3.5. Building a Reservation: Combo Tickets Across Attractions

A reservation is the cart that ties a guest to a venue and, optionally, to a pass. Box-office staff or the guest create a `Reservation` by supplying the `venue_id`, the owning `guest_id`, and an optional `pass_id` for a discount. It opens in entry state `HELD`, payment state `UNPAID`, with `party_size` zero and `version` 1.

To the held reservation, one ticket is added per party member. Each `Ticket` names the `time_slot_id` it admits into, the bearer's `guest_age`, the bearer's `max_scare_level`, and the `tier` (`GA`, `FAST_PASS`, or `VIP`). Because combo visits across several attractions are allowed, different tickets on the same reservation may point at slots belonging to different attractions — but every such slot must belong to an attraction whose `venue_id` matches the reservation's `venue_id`, or the ticket is rejected with `ERR_TICKET_VENUE_MISMATCH`. The bearer's `guest_age` must be at least the attraction's `min_age`, failing which the ticket is rejected with `ERR_AGE_BELOW_MINIMUM`, and the bearer's `max_scare_level` must clear the attraction's `scare_level` as described in Section 3.3. Adding a ticket raises the reservation's `party_size` by one and sets the ticket's `queue_priority` purely from its tier: `VIP` admits first at priority 0, `FAST_PASS` next at 1, and `GA` last at 2 — a lower number admits earlier. Adding a `VIP` ticket is blocked when the venue's `operational_state` is `RESTRICTED` or `SHUTDOWN`.

### 3.6. Confirming a Reservation: Pricing, Discount, and Capacity

Confirmation is where a held cart becomes a committed booking. Box-office staff or the guest confirm a `HELD` reservation, which must hold at least one ticket — a confirmation against a reservation with zero tickets is rejected with `ERR_EMPTY_RESERVATION`. The confirmation carries the `expected_time_slot_version` guard described in Section 2.10, and it may proceed only while the venue's `operational_state` is not `SHUTDOWN`; a confirmation against a shut-down venue is rejected with `ERR_SALES_BLOCKED`. Every referenced slot must be in `SCHEDULED` status, and the request advances the reservation from `HELD` to `RESERVED`.

Confirmation freezes each ticket's price. For a given ticket the system selects the active `PricingRule` matching its slot's attraction and its `tier` — and where more than one such rule exists, the earliest-created matching rule is used — reads the slot's `demand_ratio` as it stood before this confirmation's increment, and chooses the surge percentage by the banding in Section 3.2. The frozen `price_cents` is the rule's `base_price_cents` multiplied by one hundred plus the chosen surge percentage, divided by one hundred, then rounded half up to a whole cent; when no matching `PricingRule` exists for the ticket's attraction and `tier`, the frozen `price_cents` is zero. The reservation's `subtotal_cents` is the sum of the frozen `price_cents` across its tickets.

The pass discount, recorded as `discount_cents`, is then computed. If the reservation names no `pass_id`, the discount is zero. If the applied pass is not `ACTIVE`, the discount is zero. If the pass's product is of `GROUP` kind and the reservation's `party_size` is below the product's `min_party`, the discount is zero. Otherwise the discount is computed per line item and then summed: for each ticket, multiply its frozen `price_cents` by the product's `discount_pct`, divide by one hundred, and round half up to a whole cent; the `discount_cents` is the sum of those per-ticket rounded amounts. This per-line rounding is deliberate — rounding each ticket before summing yields a different total than summing first and rounding once, and the former is the specified behaviour. The reservation's `total_cents` is its `subtotal_cents` less its `discount_cents`, never allowed below zero.

When a pass is applied at confirmation it must be eligible: the pass must be `ACTIVE` with `redemptions_used` still below the product's `max_redemptions`, or the confirmation is rejected with `ERR_PASS_EXHAUSTED`; and the pass's `guest_id` must equal the reservation's `guest_id`, or it is rejected with `ERR_PASS_NOT_OWNED`. A successful confirmation that applied a pass raises that pass's `redemptions_used` by one, moving it to `EXHAUSTED` if it thereby reaches the product's `max_redemptions`.

Capacity is consumed atomically with the price freeze. For each referenced slot, the confirmation checks that the slot's `reserved_count` plus its `admitted_count` plus the new party members landing on that slot does not exceed the slot's `capacity`; a confirmation that would push a slot past its `capacity` is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`. On success each slot's `reserved_count` is raised by that slot's new party members, the slot's `version` is incremented, and its `demand_ratio` is recomputed.

### 3.7. Paying, Admitting, No-Shows, and Cancellation

Payment and entry evolve as two independent dimensions of the same reservation: its `entry_status` and its `payment_status` advance separately. A reservation may be paid only while its `entry_status` is `RESERVED` and its `payment_status` is `UNPAID`; paying it draws down the guest's wallet first. The amount applied from the wallet is the smaller of the guest's `wallet_credit_cents` and the reservation's `total_cents`; that applied amount is subtracted from `wallet_credit_cents`, and the cash charged is the `total_cents` less the applied amount. Payment moves the reservation to `PAID` and increments its `version`.

Admission takes a `RESERVED`, `PAID` reservation through the gate and is reserved to box-office staff. It is permitted only while the logical clock lies within the reservation's entry window — at or after the earliest ticketed slot's `window_start` and strictly before the latest ticketed slot's `window_end`; outside that window admission is rejected with `ERR_OUTSIDE_ENTRY_WINDOW`. Every scare zone of each ticketed attraction must be `STAFFED`, or admission is rejected with `ERR_ZONE_UNDERSTAFFED`. The waiver sufficiency check of Section 3.3 also applies here, and the waiver evaluated is the one held by the reservation's owning `guest_id` (not a per-ticket bearer): the owning guest must hold at least one currently-`SIGNED`, non-expired `Waiver` whose `max_scare_level` is at least the attraction's `scare_level`, for each ticketed attraction whose `requires_waiver` is true. On success the reservation moves to `ADMITTED`; for each ticket its slot's `reserved_count` drops by one and its `admitted_count` rises by one, each affected slot's `version` increments, and the reservation's `version` increments.

After a reservation's entry window has fully passed — when the logical clock is at or after the latest ticketed slot's `window_end` — a still-`RESERVED` reservation may be marked a no-show by box-office staff, moving it to the terminal `NO_SHOW` state; an attempt made before the clock reaches that `window_end` is rejected with `ERR_INVALID_STATE`. For each ticket the slot's `reserved_count` drops by one, the slot's `version` increments, the slot's `demand_ratio` is recomputed, and the reservation's `version` increments.

Either the guest or box-office staff may cancel a reservation while it is `HELD` or `RESERVED`, moving it to the terminal `CANCELLED` state. If it was `RESERVED`, each ticket's slot has its `reserved_count` decremented, its `version` incremented, and its `demand_ratio` recomputed. If the reservation had been `PAID`, its payment state moves to `REFUNDED` and the full `total_cents` is credited to the guest's `wallet_credit_cents`. If a pass had been applied and the reservation was `RESERVED`, the pass's `redemptions_used` is decremented and, if the pass had been `EXHAUSTED`, it returns to `ACTIVE`. A refund — whether from a guest's own cancellation or from a closure cascade — always credits the guest's wallet with the full `total_cents` that was charged; total cash charged plus wallet credit issued is conserved across the cancellation.

### 3.8. Scare Zones and Actor Shifts

Each attraction is protected by one or more `ScareZone` records, created by the operations manager with a `name` label and a `min_actors` count of at least 1 — the minimum checked-in actors required for the zone to be considered staffed. A new zone starts `UNDERSTAFFED` with `checked_in_count` zero. The zone's `staffing_status` is `STAFFED` exactly when its `checked_in_count` is at least its `min_actors`, and `UNDERSTAFFED` otherwise.

The operations manager schedules an `ActorShift` in a zone by supplying the `actor_user_id` of the assigned actor and the shift's inclusive `shift_start` and exclusive `shift_end` as ISO 8601 UTC instants; the shift begins `SCHEDULED`. A new shift for the same `actor_user_id` must preserve a mandatory thirty-minute rest buffer from every existing non-terminal shift — that is, from any shift in `SCHEDULED` or `CHECKED_IN` status — for that actor. Two shifts conflict when the new shift's `shift_start` falls before the existing shift's `shift_end` extended by thirty minutes, and simultaneously the existing shift's `shift_start` falls before the new shift's `shift_end` extended by thirty minutes; this buffered-interval test means even back-to-back shifts that touch are too close. A conflicting shift is rejected with `ERR_SHIFT_OVERLAP`.

An actor checks in to a `SCHEDULED` shift (the acting `Actor`'s `X-User-ID` is not compared against the shift's `actor_user_id`, per Section 2.1, so any `Actor` may check a shift in or out), permitted only while the logical clock lies within the shift window — at or after `shift_start` and strictly before `shift_end`; outside that window check-in is rejected with `ERR_OUTSIDE_SHIFT_WINDOW`. Check-in moves the shift to `CHECKED_IN`, raises the zone's `checked_in_count` by one, and — if `checked_in_count` thereby reaches the zone's `min_actors` — bubbles the zone up to `STAFFED`; the shift's `version` increments. An actor later checks out of a `CHECKED_IN` shift, moving it to the terminal `CHECKED_OUT` state, lowering the zone's `checked_in_count` by one, and — if `checked_in_count` thereby falls below `min_actors` — bubbling the zone down to `UNDERSTAFFED`. When a check-out drops a zone to `UNDERSTAFFED` and the zone's attraction is currently `OPEN`, the system raises an `ACTIVE` `Closure` on that attraction with reason `UNDERSTAFFED` and runs the attraction's pause cascade described in Section 3.9; if the attraction is not `OPEN` (for example already `PAUSED` or `CLOSED`), no new closure is raised and no cascade runs. The operations manager may instead cancel a `SCHEDULED` shift outright, moving it to the terminal `CANCELLED` state; both check-out and cancellation increment the shift's `version`.

### 3.9. Closures, Weather, and Cascading Refunds

A closure takes an attraction offline temporarily. The operations manager opens a `Closure` on an `OPEN` attraction with a `reason` of `WEATHER`, `SAFETY`, or `UNDERSTAFFED`; the closure begins `ACTIVE` and the request carries `expected_attraction_version`. Opening a closure drives the attraction from `OPEN` to `PAUSED` and runs the pause cascade in three layers. First, every `SCHEDULED` slot of the attraction is set to `CLOSED`. Second — caused by each slot closing — every reservation holding a ticket on a now-closed slot whose entry state is `HELD` or `RESERVED` is moved to `CANCELLED`. Third — caused by each such cancellation where the reservation's payment state was `PAID` — the payment state moves to `REFUNDED` and the reservation's full `total_cents` is added to the owning guest's `wallet_credit_cents`. The closure tallies how many reservations it auto-refunded on its `opened_reservation_refunds`, and the attraction's `version` is incremented.

Lifting reverses the pause. The operations manager lifts an `ACTIVE` closure, carrying `expected_attraction_version`; lifting requires that the venue's `weather_status` is not `SEVERE`, and a lift attempted while the weather is `SEVERE` is rejected with `ERR_INVALID_STATE` (this check is evaluated before the `expected_attraction_version` guard). The closure moves to the terminal `LIFTED` state and its `version` increments. If no other `ACTIVE` closure remains on the attraction, the attraction returns from `PAUSED` to `OPEN`, and every slot whose `window_start` is at or after the current logical clock and is in `CLOSED` status is restored to `SCHEDULED`; the attraction's `version` increments. The attraction may close and reopen repeatedly across the season.

Weather drives the venue's posture and can cascade to every attraction. Setting `weather_status` to `SEVERE` puts the venue into `SHUTDOWN`: every `OPEN` attraction of the venue receives an `ACTIVE` `Closure` with reason `WEATHER` and runs the same pause cascade, all sales are blocked, and the venue's `version` increments. Setting `weather_status` to `ADVISORY` puts the venue into `RESTRICTED`, where new `VIP` tickets and new season or group pass purchases are blocked but `GA` and `FAST_PASS` sales continue. Setting `weather_status` back to `CLEAR` returns the venue's derived `operational_state` to `OPEN` — from `RESTRICTED` and from `SHUTDOWN` alike — immediately and unconditionally, since `operational_state` is derived solely from `weather_status` (Section 3.1) and is not gated on `open_attraction_count`; setting `CLEAR` does not by itself reopen any paused attraction, which remains `PAUSED` until its own closures are lifted separately. Each weather change recomputes `operational_state` and increments the venue's `version`. The terminal close-for-season operation is distinct from a closure: it may be applied to an attraction whose `status` is `OPEN` or `PAUSED` (an attraction already in terminal `CLOSED` status is rejected with `ERR_INVALID_STATE`), and closing an attraction for the season moves it to the terminal `CLOSED` status, drives all its slots to `CLOSED`, decrements the venue's `open_attraction_count` if the attraction had been `OPEN`, recomputes the venue's `operational_state`, and increments the attraction's `version`.

Two sales-posture rules recur across this section and Section 3.4 through 3.6: any sale or confirmation is blocked outright when the venue's `operational_state` is `SHUTDOWN`, and `VIP` ticket additions and pass purchases are additionally blocked when it is `RESTRICTED` — every such block surfaces as `ERR_SALES_BLOCKED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state transition and the clock-setting capability — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to an exact UTC instant | OpsManager |
| POST | `/venues` | Create a venue | OpsManager |
| GET | `/venues/{venue_id}` | Read a venue with derived state and open-attraction count | OpsManager, BoxOffice, Guest, Actor |
| POST | `/venues/{venue_id}/weather` | Set venue weather and drive operational state and closures | OpsManager |
| POST | `/attractions` | Create an attraction under a venue | OpsManager |
| GET | `/attractions/{attraction_id}` | Read an attraction | OpsManager, BoxOffice, Guest, Actor |
| GET | `/attractions` | List attractions, optionally filtered by venue | OpsManager, BoxOffice, Guest, Actor |
| POST | `/attractions/{attraction_id}/close_for_season` | Close an attraction for the season | OpsManager |
| POST | `/attractions/{attraction_id}/pricing-rules` | Create a per-tier pricing rule | OpsManager |
| GET | `/pricing-rules/{pricing_rule_id}` | Read a pricing rule | OpsManager, BoxOffice, Guest, Actor |
| GET | `/pricing-rules` | List pricing rules filtered by attraction | OpsManager, BoxOffice, Guest, Actor |
| POST | `/attractions/{attraction_id}/time-slots` | Create a timed-entry slot | OpsManager |
| GET | `/time-slots/{time_slot_id}` | Read a slot with occupancy counters | OpsManager, BoxOffice, Guest, Actor |
| GET | `/time-slots` | List slots filtered by attraction | OpsManager, BoxOffice, Guest, Actor |
| POST | `/guests` | Register a guest | BoxOffice, Guest |
| GET | `/guests/{guest_id}` | Read a guest with wallet credit | OpsManager, BoxOffice, Guest |
| POST | `/guests/{guest_id}/waivers` | Sign a waiver for a guest | BoxOffice, Guest |
| GET | `/waivers/{waiver_id}` | Read a waiver | OpsManager, BoxOffice, Guest |
| GET | `/waivers` | List waivers filtered by guest | OpsManager, BoxOffice, Guest |
| POST | `/waivers/{waiver_id}/revoke` | Revoke a signed waiver | Guest, OpsManager |
| POST | `/venues/{venue_id}/pass-products` | Create a season/group pass product | OpsManager |
| GET | `/pass-products/{pass_product_id}` | Read a pass product | OpsManager, BoxOffice, Guest |
| GET | `/pass-products` | List pass products filtered by venue | OpsManager, BoxOffice, Guest |
| POST | `/passes` | Issue a pass for a guest | BoxOffice, Guest |
| GET | `/passes/{pass_id}` | Read an issued pass | OpsManager, BoxOffice, Guest |
| GET | `/passes` | List passes filtered by guest or product | OpsManager, BoxOffice, Guest |
| POST | `/reservations` | Create a held reservation | BoxOffice, Guest |
| GET | `/reservations/{reservation_id}` | Read a reservation | OpsManager, BoxOffice, Guest |
| GET | `/reservations` | List reservations filtered by guest or venue | OpsManager, BoxOffice, Guest |
| POST | `/reservations/{reservation_id}/tickets` | Add a ticket to a held reservation | BoxOffice, Guest |
| GET | `/tickets/{ticket_id}` | Read a ticket | OpsManager, BoxOffice, Guest |
| GET | `/tickets` | List tickets filtered by reservation or slot | OpsManager, BoxOffice, Guest |
| POST | `/reservations/{reservation_id}/confirm` | Confirm a reservation under OCC | BoxOffice, Guest |
| POST | `/reservations/{reservation_id}/pay` | Pay a reserved reservation | BoxOffice, Guest |
| POST | `/reservations/{reservation_id}/admit` | Admit a paid reservation | BoxOffice |
| POST | `/reservations/{reservation_id}/mark_no_show` | Mark a reservation a no-show | BoxOffice |
| POST | `/reservations/{reservation_id}/cancel` | Cancel a reservation | Guest, BoxOffice |
| POST | `/attractions/{attraction_id}/scare-zones` | Create a scare zone | OpsManager |
| GET | `/scare-zones/{scare_zone_id}` | Read a scare zone | OpsManager, BoxOffice, Actor |
| GET | `/scare-zones` | List scare zones filtered by attraction | OpsManager, BoxOffice, Actor |
| POST | `/scare-zones/{scare_zone_id}/actor-shifts` | Schedule an actor shift | OpsManager |
| GET | `/actor-shifts/{shift_id}` | Read an actor shift | OpsManager, Actor |
| GET | `/actor-shifts` | List actor shifts filtered by scare zone | OpsManager, Actor |
| POST | `/actor-shifts/{shift_id}/check_in` | Check in to a scheduled shift | Actor |
| POST | `/actor-shifts/{shift_id}/check_out` | Check out of a shift | Actor |
| POST | `/actor-shifts/{shift_id}/cancel` | Cancel a scheduled shift | OpsManager |
| POST | `/attractions/{attraction_id}/closures` | Open a closure on an attraction | OpsManager |
| GET | `/closures/{closure_id}` | Read a closure | OpsManager, BoxOffice |
| GET | `/closures` | List closures filtered by attraction | OpsManager, BoxOffice |
| POST | `/closures/{closure_id}/lift` | Lift an active closure | OpsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AGE_BELOW_MINIMUM` | 422 |
| `ERR_WAIVER_REQUIRED` | 422 |
| `ERR_SCARE_LEVEL_TOO_LOW` | 422 |
| `ERR_ZONE_UNDERSTAFFED` | 409 |
| `ERR_OUTSIDE_ENTRY_WINDOW` | 409 |
| `ERR_OUTSIDE_SHIFT_WINDOW` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_CAPACITY_OVER_THROUGHPUT` | 422 |
| `ERR_SALES_BLOCKED` | 409 |
| `ERR_PASS_EXHAUSTED` | 409 |
| `ERR_PASS_NOT_OWNED` | 422 |
| `ERR_TICKET_VENUE_MISMATCH` | 422 |
| `ERR_STALE_TIME_SLOT_VERSION` | 412 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_VENUE_VERSION` | 412 |
| `ERR_STALE_ATTRACTION_VERSION` | 412 |
| `ERR_STALE_WAIVER_VERSION` | 412 |
| `ERR_EMPTY_RESERVATION` | 422 |
