# Zipline Park API — Product Requirements Document

## 1. Introduction

The Aerial Adventure & Zipline Park platform coordinates the day-to-day operation of a high-ropes and zipline attraction where finite time-slot seats are the scarce resource everyone competes for. A visitor books a seat on a guided tour, signs a liability waiver, is checked in and briefed by field staff, is fitted with a harness and helmet, and rides — but only when the weather cooperates, the participant meets weight and age limits, and enough certified guides are on hand to keep the guide-to-guest ratio safe. Behind the scenes, the park sells season passes, runs discounted team-building groups, issues rain-checks when storms force a closure, and files incident reports when something goes wrong on the course.

This document specifies the REST API that governs that entire lifecycle. Its central challenge is consistency under pressure: seats must be held and released correctly as bookings move through their states, gear must never be double-issued across overlapping tour windows, guides must never be scheduled onto two overlapping tours at once, and financial credits must be computed to the exact cent when a customer cancels or a slot is weather-closed. A single logical clock — advanced explicitly for testing rather than read from wall-clock time — drives every time-derived value, from a participant's age to whether a waiver has expired. The sections that follow define the global contracts that every endpoint honors, then descend into the business workflows where the park's operational rules actually live.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `Operator`, `Customer`, and `Guide`.

- An `Operator` is a park operator/admin with superset authority over configuration, scheduling, staffing, gear, season passes, and the booking flow. When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for it, but it never compares it to any entity's `id`.
- A `Customer` is a registered visitor who acts as a participant — booking tours, signing their own waiver, and redeeming their own rain-checks. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a `Participant` compare the resource's participant foreign key to `X-User-ID`.
- A `Guide` is field staff who run tours — checking participants in, briefing them, completing rides, handling gear, and filing incidents. When `X-User-Role` is `Guide`, `X-User-ID` is the `id` of the acting `Guide`; where a workflow associates a guide with a resource, that association compares the resource's guide reference to `X-User-ID`.

Ownership is enforced for `Customer` actions specifically: a `Customer` may only sign the waiver of, redeem a rain-checked booking of, or cancel a booking of the `Participant` whose `id` equals `X-User-ID`. A `Customer` attempting any of these against a participant or booking they do not own is rejected with `ERR_UNAUTHORIZED`. The `Operator` role is a superset and may perform any shared operation; a small set of configuration and staffing operations (creating courses, time slots, guides, guide assignments, gear items, season passes, and opening/closing/completing slots) are exclusive to `Operator`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 or above 100 is clamped into that range, and a non-integer `limit` falls back to the default of 10. The `offset` parameter is the number of items to skip and defaults to 0; a negative or non-integer `offset` falls back to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Almost every resource in the system carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. Both `created_at` and `updated_at` are stamped from the server's real wall-clock time, not from the logical clock of §2.5 (the logical clock governs only the time-derived fields enumerated there and the workflow timestamps that explicitly stamp "the current clock").
- `updated_at` — an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 and increments by one on every mutation of the resource. It is the value used for optimistic concurrency control described in §2.7.

There is one deliberate exception. An `IncidentReport` is an append-only record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after filing. Every other entity — `Course`, `TimeSlot`, `Guide`, `Participant`, `SeasonPass`, `Group`, `Booking`, `GuideAssignment`, `GearItem`, and `GearCheckout` — carries the full set above.

When a system-driven reconciliation changes a resource's persisted state (for example, a booking flipped to `RAINCHECKED` by a weather closure, or a participant's `version` advanced by issuing a season pass), that change is a genuine mutation: it refreshes the affected resource's `updated_at` and increments its `version`, exactly as a client-initiated change would.

### 2.5. The Logical Clock and Time-Derived Fields

The server keeps a single logical clock that is the sole source of "now" for every time-dependent computation. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it stays at that default — it never falls back to wall-clock time. An `Operator` may advance it by supplying a `to_iso8601` instant through the clock-setting capability; doing so immediately changes the values that all time-derived fields resolve to on the next read.

Three families of fields are recomputed against the current clock rather than stored statically:

- A participant's `age_years` is the number of whole (fully completed) years between their `birthdate` and the current clock instant.
- A participant's `waiver_status` reflects the clock: it is `NONE` when a waiver was never signed, `SIGNED` when a waiver has been signed and the clock is at or before `waiver_expires_at`, and `EXPIRED` when a waiver was signed but the clock is strictly after `waiver_expires_at`.
- Season-pass validity (see §3.3) is evaluated against the clock's position within the pass's `valid_from`..`valid_until` window.

### 2.6. Monetary Precision and Rounding

All money is expressed in whole cents as integers. Every fractional intermediate produced by a pricing, credit, or insurance calculation is resolved to whole cents using the round-half-up method (a value whose fractional part is exactly one-half rounds up to the next whole cent). Each calculation in §3 states exactly where its single rounding step occurs; unless a calculation explicitly rounds a per-item figure before aggregating, rounding is applied once, at the end.

### 2.7. Optimistic Concurrency Control

Issuing a season pass to a participant is guarded by optimistic concurrency control on the participant. The season-pass-creation request must carry `expected_participant_version`, a non-optional field holding the `version` of the `Participant` that the client last observed. If that value does not equal the participant's current `version` at the moment the server processes the request, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

The reason this matters is that issuing a new pass legitimately supersedes the participant's prior `ACTIVE` pass and advances the participant's `version`. If another writer has already issued a pass since the client last read the participant, the client's view of the participant is stale — proceeding would let it act on a superseded picture — so the version mismatch stops it. No other endpoint takes a version field; only season-pass creation performs this check.

### 2.8. Cascading State Consistency and Derived Counters

Several operations mutate more than one entity at once, and the system propagates those effects to completion rather than stopping at the first. Weather closures, group cancellations, slot completions, and booking exits all cascade through as many as three levels — from a booking, to its gear checkouts, to the physical gear items — and each affected resource is reconciled in the same operation. The precise cascades are specified in the workflows of §3; the governing principle is that no seat, gear item, or season-pass entitlement is ever left committed to a booking that has left its active states.

A number of fields are derived rather than directly set, and are always kept consistent with the underlying records:

- A `TimeSlot` exposes `booked_count` (how many of its bookings are currently active) and `remaining_capacity` (its `capacity` minus `booked_count`, never allowed to go below zero).
- A `Group` exposes `member_count` and `insurance_total_cents`.
- A `SeasonPass` exposes `uses_committed`, `uses_settled`, and `uses_remaining`.
- A `GearItem` exposes `status`, which reflects whether any of its checkouts is currently outstanding.

Whenever a booking is created, cancelled, rain-checked, marked a no-show, or completed, every counter that references it is recomputed so the slot, group, and pass always tell the truth about the current world.

### 2.9. Nested Resource Retrieval and Validation Ordering

Requests are validated in a fixed priority order, and the first failing check determines the error returned:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, or the request fails with `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role must be permitted for the operation, or the request fails with `ERR_UNAUTHORIZED`.
3. **Existence** — every resource named in the path and every foreign key referenced in the body must exist, validated left-to-right in path order; the first missing one yields `ERR_NOT_FOUND`. A request that targets a resource nested under a parent fails on the parent before the child is ever consulted.
4. **Body well-formedness** — on write endpoints, required fields must be present, enums must hold legal values, numeric fields must be numeric, and where a season pass is issued the window must satisfy `valid_until` strictly after `valid_from`; otherwise `ERR_VALIDATION`.
5. **Ownership** — for the `Customer`-initiated waiver, redeem, and cancel operations, the acting customer must own the target participant or booking, or the request fails with `ERR_UNAUTHORIZED`.
6. **State** — the target resource must be in a legal state for the requested transition, or the request fails with `ERR_INVALID_STATE`; the slot-open gate on check-in and complete is a state check that surfaces as `ERR_SLOT_NOT_OPEN`.
7. **Safety** — weight, age, waiver, and guide-certification limits are enforced next, each with its own error.
8. **Operational constraints** — guide overlap, gear-window overlap, guide-assigned presence, staffing floors, and group-slot agreement are enforced next.
9. **Fiscal/capacity constraints** — seat availability and season-pass validity/exhaustion are enforced.
10. **Concurrency** — the optimistic-concurrency version check is enforced last.

This ordering is deliberate: an authentication failure always masks an authorization failure, existence always precedes body validation, and a state error surfaces before any safety or capacity error on the same request.

## 3. Business Logic & Workflows

### 3.1. Courses and the Time-Slot Backbone

Everything the park sells hangs off a **Course** — a named tour or route that an `Operator` defines. A course records a `name` and a `difficulty_level` from 1 to 5 (a whole number no less than 1 and no greater than 5), which is the minimum guide certification level required to run it. It fixes the participant envelope through `min_weight_kg` and `max_weight_kg` (both inclusive kilogram bounds) and a `min_age_years` (an inclusive whole-year minimum). Commercially it carries a `base_price_cents` (the per-participant base price in cents), a `duration_minutes` (how long the tour runs), a `default_capacity` (seats per slot when a slot omits its own capacity), a `max_participants_per_guide` (the guide ratio), and a `weekend_surcharge_pct` — the fraction of the base added when a slot starts on a Saturday or Sunday in UTC (for example, 0.15 for a fifteen-percent surcharge).

An `Operator` schedules a **TimeSlot** against a course by supplying the `course_id` and a UTC `start_at`, and optionally a `capacity`; when `capacity` is omitted it defaults to the course's `default_capacity`. The slot's `end_at` is computed as `start_at` plus the course's `duration_minutes`. A newly created slot begins in `SCHEDULED` status. Its `booked_count` and `remaining_capacity` are derived counters (see §3.4), and its `closure_reason` is null until a weather closure records one.

A slot moves through a cyclic lifecycle across the states `SCHEDULED`, `OPEN`, `CLOSED`, and `COMPLETED`, with `COMPLETED` terminal. Opening a slot advances it from `SCHEDULED` to `OPEN`, but only if at least one guide is assigned to it in `ASSIGNED` status; with no assigned guide the open is refused with `ERR_NO_GUIDE_ASSIGNED`. The same open action is the cycle edge that brings a weather-closed slot back from `CLOSED` to `OPEN` once the storm passes — it likewise requires at least one `ASSIGNED` guide, and as a side effect it clears `closure_reason` back to null. Reopening does not resurrect bookings that were already rain-checked by the closure; those stay `RAINCHECKED`. Weather closure and slot completion are covered in §3.6.

### 3.2. Guides, Certification, and Staffing Ratios

A **Guide** is created by an `Operator` with a `name` and a `certification_level` from 1 to 5 (a whole number no less than 1 and no greater than 5). To actually staff a slot, an `Operator` creates a **GuideAssignment** linking a `guide_id` to a `time_slot_id`; a fresh assignment starts in `ASSIGNED` status. Two guards apply at assignment time. First, the guide must be certified for the course: the guide's `certification_level` must be at least the course's `difficulty_level`, otherwise the assignment is refused with `ERR_GUIDE_UNCERTIFIED`. Second, a guide may not be double-booked: the assignment is refused with `ERR_GUIDE_DOUBLE_BOOKED` if the guide is already `ASSIGNED` to another slot whose time interval overlaps this slot's interval. Overlap is measured on the half-open interval from `start_at` up to but not including `end_at`, so two tours that merely touch — one ending exactly when the next begins — do not overlap and are allowed.

Staffing sets a ceiling on how many guests a slot can hold. The slot's assigned capacity is the number of its `ASSIGNED` guide assignments multiplied by the course's `max_participants_per_guide`. An assignment can be withdrawn by an `Operator`, moving it from `ASSIGNED` to `CANCELLED`, but only if the slot would still be adequately staffed afterward: with one fewer assigned guide, the remaining assigned capacity — that is, the assigned-guide count minus one, multiplied by `max_participants_per_guide` — must still be greater than or equal to the slot's current `booked_count`. If withdrawing the guide would drop assigned capacity below the number of active bookings, the cancellation is refused with `ERR_UNDERSTAFFED`.

### 3.3. Participants, Waivers, and Season Passes

A **Participant** is registered — by an `Operator` or by a self-serving `Customer` — with a `full_name`, a `weight_kg`, and a `birthdate` (a UTC-midnight date of birth). On registration the participant's `waiver_status` is `NONE` and their `version` is 1. Their `age_years` is derived from `birthdate` against the logical clock, and their `waiver_signed_at` and `waiver_expires_at` are null until a waiver is signed.

Signing the waiver stamps `waiver_signed_at` to the current clock instant, sets `waiver_expires_at` to that instant plus the waiver validity period of 365 days, and drives `waiver_status` to `SIGNED`; the operation also increments the participant's `version`. The request carries a `signature_name`. A waiver can be re-signed to refresh it, which simply re-stamps the two timestamps from the current clock. Because `waiver_status` is evaluated live against the clock, a waiver that was `SIGNED` becomes `EXPIRED` once the clock passes `waiver_expires_at` — the value is `SIGNED` only while the clock is at or before `waiver_expires_at`. A `Customer` may sign only their own waiver, where `X-User-ID` equals the participant's `id`.

A **SeasonPass** is issued to a participant by an `Operator`. The request supplies the `participant_id`, a `tier` of either `STANDARD` or `PREMIUM`, an inclusive UTC `valid_from` and `valid_until` window (where `valid_until` must be strictly after `valid_from`), a `total_uses` entitlement count, and the `expected_participant_version` described in §2.7. A newly issued pass starts `ACTIVE`; as a side effect, any prior `ACTIVE` pass held by the same participant is driven to `SUPERSEDED`, and the participant's `version` is incremented by one. Because that version bump is exactly what the optimistic-concurrency check protects, a stale `expected_participant_version` yields `ERR_STALE_VERSION`.

A pass tracks its consumption through three derived counters. `uses_committed` counts the pass's bookings currently held in the active states `CONFIRMED`, `CHECKED_IN`, or `BRIEFED`. `uses_settled` counts the pass's bookings that have reached `COMPLETED`. `uses_remaining` is the `total_uses` less both `uses_committed` and `uses_settled`, never allowed below zero. Two readings of "remaining" exist and must not be conflated: when gating a new booking, the provisional reading subtracts both the active holds (`uses_committed`) and the settled uses, so a pass with all its entitlements tentatively held reads as exhausted even before any ride is completed; when reporting entitlements actually consumed, only the settled `COMPLETED` bookings count. It is the provisional reading that decides whether a new booking may consume the pass.

### 3.4. Booking a Seat: Pricing, Eligibility, and Capacity

A **Booking** holds one seat on one slot for one participant. It is created by an `Operator` or a `Customer` with a `time_slot_id`, a `participant_id`, an optional `group_id` (null for an individual booking), and an optional `use_season_pass` flag that defaults to false and expresses the client's intent to consume a pass. A new booking starts in `CONFIRMED` status. The system sets `season_pass_id` to the id of the pass consumed when `use_season_pass` is requested and a usable pass exists, and to null otherwise; the submitted `use_season_pass` flag is itself persisted on the booking and echoed back in the booking resource. A booking also carries a `price_cents` computed at creation, a `raincheck_credit_cents` that starts at 0 and is stamped only when the booking exits via a weather or voluntary path, and a `redeemed_from_booking_id` that is null unless the booking was created by redeeming a rain-check.

**Seat capacity.** A slot's `booked_count` is the count of its bookings in the three active states `CONFIRMED`, `CHECKED_IN`, and `BRIEFED`; bookings that are `COMPLETED`, `CANCELLED`, `RAINCHECKED`, `NO_SHOW`, or `REDEEMED` do not occupy a seat. The `remaining_capacity` is the slot's `capacity` minus `booked_count`, floored at zero. A booking is refused with `ERR_SLOT_FULL` unless `remaining_capacity` is at least 1 and admitting it would keep `booked_count` plus one no greater than the smaller of the slot's `capacity` and its assigned capacity (the `ASSIGNED`-guide count times `max_participants_per_guide`). The ceiling is therefore whichever is tighter, the physical seats or the staffing ratio.

**Safety eligibility.** Before a seat is held, the participant must fit the course envelope. Their `weight_kg` must lie within the inclusive range from the course's `min_weight_kg` to `max_weight_kg`, or the booking is refused with `ERR_WEIGHT_OUT_OF_RANGE`. Their `age_years` must be at least the course's `min_age_years`, or the booking is refused with `ERR_AGE_BELOW_MINIMUM`. A booking that names a `group_id` must target the same slot as the group: the group's `time_slot_id` must equal the booking's `time_slot_id`, otherwise the booking is refused with `ERR_GROUP_SLOT_MISMATCH`.

**Pricing.** The charged `price_cents` is computed once at creation as follows. Start from the course's `base_price_cents`. If the slot's `start_at` falls on a Saturday or Sunday in UTC, add a weekend amount equal to the base times the course's `weekend_surcharge_pct`; on Monday through Friday no surcharge applies. Call the base plus any weekend amount the subtotal. If the booking belongs to a group, apply a group discount whose rate is selected by tier from the group's `expected_size`: a size of 1 to 3 gives no discount, a size of 4 to 7 gives a ten-percent discount, and a size of 8 or more gives a twenty-percent discount; an individual booking has no discount. Multiply the subtotal by one minus the selected discount rate to get the discounted amount. Then, if `use_season_pass` was requested and a usable pass exists, the pass covers the ride and `price_cents` is 0 with `season_pass_id` recorded; otherwise `price_cents` is the discounted amount rounded half-up to whole cents in a single final rounding step.

**Pass gating.** When `use_season_pass` is requested, the pass must be usable or the booking is refused. A pass that is not `ACTIVE`, or whose window does not contain the current clock (the clock must be at or after `valid_from` and at or before `valid_until`), is rejected with `ERR_SEASON_PASS_INVALID`; a participant holding no `ACTIVE` pass at all is likewise rejected with `ERR_SEASON_PASS_INVALID`. A pass whose provisional `uses_remaining` is below 1 is rejected with `ERR_SEASON_PASS_EXHAUSTED`.

### 3.5. The Ride: Check-in, Briefing, and Completion

A booking advances through the day of the tour by three staff-driven steps, each performable by an `Operator` or a `Guide`. Checking a booking in advances it from `CONFIRMED` to `CHECKED_IN`, and is gated twice: the slot must currently be `OPEN`, else the request is refused with `ERR_SLOT_NOT_OPEN`, and the participant's `waiver_status` must be `SIGNED`, else it is refused with `ERR_WAIVER_REQUIRED`. Because state is checked before safety, a check-in against a non-open slot surfaces the slot error before the waiver error.

Briefing a booking advances it from `CHECKED_IN` to `BRIEFED`, and requires the slot to still have at least one `ASSIGNED` guide, otherwise the briefing is refused with `ERR_NO_GUIDE_ASSIGNED`. Completing a booking advances it from `BRIEFED` to `COMPLETED` while the slot is `OPEN` (a non-open slot yields `ERR_SLOT_NOT_OPEN`). Completion settles the ride: if the booking carried a `season_pass_id`, that use leaves the provisional `uses_committed` and enters the settled `uses_settled`; and any gear checkout still outstanding on the booking is returned — its checkout flips to `RETURNED` and, once none of the item's checkouts remain outstanding, the underlying gear item returns to `AVAILABLE`.

### 3.6. Weather Closures, Cancellations, and Rain-check Redemption

**Weather closure.** An `Operator` may weather-close a slot from either `SCHEDULED` or `OPEN` into `CLOSED`, optionally supplying a `reason` that is recorded on the slot's `closure_reason`. A closure cascades three levels deep. At the first level, every booking on the slot in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` is driven to `RAINCHECKED`, and each such booking is stamped with a full weather credit: its `raincheck_credit_cents` is set equal to its `price_cents`, unconditionally, regardless of how close to `start_at` the closure happens. At the second level, each of those bookings' gear checkouts that are still outstanding are returned (their `returned_at` set to the current clock and status `RETURNED`). At the third level, each gear item whose last outstanding checkout was just returned reverts to `AVAILABLE`. As the bookings leave their active states, their seats are released — `booked_count` and `remaining_capacity` recompute — and any season-pass commitments they held are released from `uses_committed`.

**Slot completion.** An `Operator` completes a slot from `OPEN` to the terminal `COMPLETED` state to close out the day. Any booking still lingering in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` at that moment is treated as a no-show: it is driven to `NO_SHOW`, its outstanding gear is returned and the gear items freed to `AVAILABLE`, and its seat and any season-pass commitment are released. A no-show earns no credit — its `raincheck_credit_cents` stays 0.

**Voluntary cancellation.** A booking in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` may be voluntarily cancelled — by an `Operator` or by the owning `Customer` — into `CANCELLED`. The credit depends on lead time: let the lead be the hours between the current clock and the slot's `start_at`. If that lead is at least 24 hours, the full `price_cents` is credited to `raincheck_credit_cents`; if the lead is under 24 hours, the credit is `price_cents` multiplied by one-half, rounded half-up to whole cents. Cancellation cascades the same way as a closure at the booking level: outstanding gear checkouts are returned and their gear items freed to `AVAILABLE`, the seat is released, and any season-pass commitment is released.

**Rain-check redemption.** A `RAINCHECKED` booking can be redeemed — by an `Operator` or the owning `Customer` — into a target slot supplied as `time_slot_id`. The redemption succeeds only if the target slot is `SCHEDULED` or `OPEN` with `remaining_capacity` of at least 1 (otherwise `ERR_SLOT_FULL`), and the participant is still eligible for the target slot's course by weight and age (the same `ERR_WEIGHT_OUT_OF_RANGE` and `ERR_AGE_BELOW_MINIMUM` checks as a fresh booking). Redeeming drives the original booking to the terminal `REDEEMED` state and creates a brand-new `CONFIRMED` booking on the target slot whose `redeemed_from_booking_id` points back at the original. The new booking's price is the target slot's freshly computed booking price less the original booking's `raincheck_credit_cents`, floored at zero. The redemption operation returns the newly created booking.

### 3.7. Groups and Team-Building

A **Group** organizes a team-building outing on a single slot. It is created by an `Operator` or a `Customer` with a `name`, the `time_slot_id` it rides on, an `expected_size` declaring the headcount, an `organizer_name` (informational contact only, not a foreign key), and an optional `organizer_participant_id` (an informational reference that may be null and is not treated as a foreign key). A group begins in `OPEN` status. Its `expected_size` is what drives the group discount tier applied uniformly to member bookings, as described in the pricing rules of §3.4.

A group exposes two derived figures. Its `member_count` is the number of bookings tied to it (by `group_id`) in `CONFIRMED`, `CHECKED_IN`, `BRIEFED`, or `COMPLETED` status. Its `insurance_total_cents` is computed by taking, for each active member booking, the course's `base_price_cents` times the insurance rate of 0.0745 rounded half-up to whole cents, and then summing those per-member figures. The order is pinned: each member's insurance fee is rounded to whole cents first, and only then are the rounded figures summed — a single sum-then-round would produce a different total and must not be used. The member bookings that feed this total are those in `CONFIRMED`, `CHECKED_IN`, `BRIEFED`, or `COMPLETED`.

Cancelling a group — by an `Operator` or a `Customer` — drives it to the terminal `CANCELLED` state and cascades three levels. Every member booking in `CONFIRMED`, `CHECKED_IN`, or `BRIEFED` is cancelled; each cancelled booking's outstanding gear checkouts are returned; and each freed gear item reverts to `AVAILABLE`. Each member cancellation applies the voluntary credit rule from §3.6 to that booking's `raincheck_credit_cents`, and releases its seat and any season-pass commitment.

### 3.8. Gear Checkout and Return

Harnesses and helmets are tracked as **GearItem** records, each created by an `Operator` with a `gear_type` of `HARNESS` or `HELMET` and a `size` of `S`, `M`, or `L`. A gear item's `status` is derived, not set: it reads `CHECKED_OUT` whenever at least one of its checkouts is outstanding, and `AVAILABLE` otherwise. A single item may hold several outstanding checkouts at once, provided their service windows never overlap.

A **GearCheckout** issues an item to a booking. An `Operator` or a `Guide` checks gear out by naming the `gear_item_id` and the `booking_id`; the checkout starts `OUT`, stamps `checked_out_at` to the current clock, and leaves `returned_at` null. Its service window is derived from the booking's slot: `window_start` is the slot's `start_at`, and `window_end` is the slot's `end_at` plus a cleaning buffer of 30 minutes. Checkout is refused with `ERR_GEAR_UNAVAILABLE` if the item already has an outstanding checkout whose window overlaps the new booking's window. Overlap is measured on the half-open interval from `window_start` up to but not including `window_end`, so windows that merely touch at their endpoints do not overlap and are allowed — this is what lets one item serve back-to-back tours once the 30-minute cleaning gap is respected.

Returning gear moves a checkout from `OUT` to `RETURNED` — triggered explicitly by an `Operator` or `Guide`, or automatically by the booking cascades of §3.5 and §3.6. Returning stamps `returned_at` to the current clock, and once none of the item's checkouts remain outstanding its `status` recomputes to `AVAILABLE`.

### 3.9. Incident Reporting

When something goes wrong on a course, an `Operator` or a `Guide` files an **IncidentReport** against a booking. The report carries the `booking_id` it concerns, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, a free-text `description`, and a `reported_by_guide_id` naming the filing guide (informational only, not a foreign key). The system stamps `occurred_at` with the current clock at filing. Incident reports are append-only records — they are never updated after creation, and accordingly they carry only an `id` and a `created_at` with no `updated_at` or `version`. The incident reports attached to a booking can be listed back for review.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions such as opening a slot, checking a booking in, or cancelling an assignment — return `200 OK`. The one deliberate exception is rain-check redemption: although it acts on an existing rain-checked booking, it produces a brand-new booking and therefore returns `201 Created`. List endpoints accept the optional filter query parameters shown and return `200 OK`. Setting the logical clock (`POST /_clock/set_current_utc`) creates no resource and returns `200 OK` with an empty data object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Operator |
| POST | `/courses` | Create a course/tour | Operator |
| GET | `/courses/{id}` | Get a course | Operator, Customer, Guide |
| GET | `/courses/{id}/time-slots` | List a course's time slots | Operator, Customer, Guide |
| POST | `/time-slots` | Create a time slot for a course | Operator |
| GET | `/time-slots/{id}` | Get a time slot | Operator, Customer, Guide |
| POST | `/time-slots/{id}/open` | Open a slot (SCHEDULED→OPEN or reopen CLOSED→OPEN) | Operator |
| POST | `/time-slots/{id}/close` | Weather-close a slot; cascades rain-check of active bookings | Operator |
| POST | `/time-slots/{id}/complete` | Complete a slot; leftover active bookings become NO_SHOW | Operator |
| GET | `/time-slots/{id}/groups` | List groups on a slot | Operator, Customer, Guide |
| POST | `/guides` | Create a guide | Operator |
| GET | `/guides/{id}` | Get a guide | Operator, Customer, Guide |
| POST | `/guide-assignments` | Assign a guide to a slot | Operator |
| GET | `/guide-assignments/{id}` | Get a guide assignment | Operator, Customer, Guide |
| GET | `/guide-assignments` | List guide assignments (filter by `guide_id`, `time_slot_id`) | Operator, Customer, Guide |
| POST | `/guide-assignments/{id}/cancel` | Cancel a guide assignment | Operator |
| POST | `/participants` | Register a participant | Operator, Customer |
| GET | `/participants/{id}` | Get a participant | Operator, Customer, Guide |
| POST | `/participants/{id}/waiver` | Sign/refresh the participant waiver | Operator, Customer |
| POST | `/participants/{id}/season-passes` | Issue a season pass to a participant | Operator |
| GET | `/participants/{id}/season-passes` | List a participant's season passes | Operator, Customer, Guide |
| POST | `/gear-items` | Register a gear item | Operator |
| GET | `/gear-items/{id}` | Get a gear item | Operator, Customer, Guide |
| POST | `/groups` | Create a team-building group on a slot | Operator, Customer |
| GET | `/groups/{id}` | Get a group | Operator, Customer, Guide |
| POST | `/groups/{id}/cancel` | Cancel a group; cascades cancel of member bookings | Operator, Customer |
| POST | `/bookings` | Create a booking | Operator, Customer |
| GET | `/bookings/{id}` | Get a booking | Operator, Customer, Guide |
| GET | `/bookings` | List bookings (filter by `time_slot_id`, `participant_id`, `group_id`, `season_pass_id`) | Operator, Customer, Guide |
| POST | `/bookings/{id}/check-in` | Check a booking in | Operator, Guide |
| POST | `/bookings/{id}/brief` | Mark a booking briefed | Operator, Guide |
| POST | `/bookings/{id}/complete` | Complete a booking | Operator, Guide |
| POST | `/bookings/{id}/cancel` | Voluntarily cancel a booking | Operator, Customer |
| POST | `/bookings/{id}/redeem` | Redeem a rain-checked booking into a target slot | Operator, Customer |
| GET | `/bookings/{id}/incident-reports` | List incident reports for a booking | Operator, Customer, Guide |
| POST | `/gear-checkouts` | Check gear out to a booking | Operator, Guide |
| GET | `/gear-checkouts/{id}` | Get a gear checkout | Operator, Customer, Guide |
| GET | `/gear-checkouts` | List gear checkouts (filter by `gear_item_id`, `booking_id`) | Operator, Customer, Guide |
| POST | `/gear-checkouts/{id}/return` | Return checked-out gear | Operator, Guide |
| POST | `/incident-reports` | File an incident report against a booking | Operator, Guide |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SLOT_NOT_OPEN` | 409 |
| `ERR_SLOT_FULL` | 409 |
| `ERR_WEIGHT_OUT_OF_RANGE` | 422 |
| `ERR_AGE_BELOW_MINIMUM` | 422 |
| `ERR_WAIVER_REQUIRED` | 422 |
| `ERR_GUIDE_UNCERTIFIED` | 422 |
| `ERR_GUIDE_DOUBLE_BOOKED` | 409 |
| `ERR_GEAR_UNAVAILABLE` | 409 |
| `ERR_NO_GUIDE_ASSIGNED` | 409 |
| `ERR_UNDERSTAFFED` | 409 |
| `ERR_GROUP_SLOT_MISMATCH` | 422 |
| `ERR_SEASON_PASS_INVALID` | 422 |
| `ERR_SEASON_PASS_EXHAUSTED` | 422 |
| `ERR_STALE_VERSION` | 412 |
