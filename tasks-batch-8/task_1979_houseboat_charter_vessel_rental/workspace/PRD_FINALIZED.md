# Houseboat Charter Rental API — Product Requirements Document

## 1. Introduction

Lake Powell's houseboat season compresses a full year of revenue into a few intense months, and the operating margins of a charter fleet are decided by how cleanly the business handles the awkward parts of the rental cycle: renters who must prove boating-safety qualification before they ever take the helm, deposits that should scale with a customer's incident history, sudden weather advisories over specific canyons and bays, mechanical failures mid-charter that interrupt a trip and demand prorated refunds, and the end-of-turn settlement where fuel, pump-out, cleaning, late return and damage all have to be reconciled against a held deposit without dispute.

This document specifies the API that runs that operation end to end. It covers fleet administration (vessels in three size classes, season-driven nightly pricing, geographic cruising zones with per-night capacity), renter onboarding and qualification via boating-safety certificates, the booking lifecycle from a 48-hour hold through confirmation, safety orientation, itinerary approval, checkout, on-water interruption, return, cleaning and final settlement, plus the cancellation and weather-refund policy. Because so much of the domain is time-driven — certificate expiry, maintenance windows opening and closing, advisory expiry, hold expiry — the system exposes a deterministic logical clock that drives all of these transitions through a single sweep, making every temporal rule reproducible and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles: `Renter`, `DockStaff`, `FleetManager`, and `Mechanic`. A request with missing headers or an undeclared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles differ in how `X-User-ID` is interpreted:

- When `X-User-Role` is `Renter`, `X-User-ID` is the `id` of the acting `Renter` entity. Ownership checks on any resource that references a renter compare the resource's `renter_id` field to `X-User-ID`: a renter may create a booking only with their own `renter_id`, and may confirm, modify, cancel, submit an itinerary for, sign orientation items on, or report incidents on their own bookings only. On renter-scoped subroutes such as the renter profile and certificate collection, the renter `id` in the path must likewise equal `X-User-ID`. A violation of this ownership rule is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When a `Renter` caller lists bookings, the result is implicitly restricted to their own bookings.
- When `X-User-Role` is `DockStaff`, `FleetManager`, or `Mechanic`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`.

`DockStaff` is the marina dock operator: they countersign orientations, run checkout, return and settlement, inspect cleaning turns, and verify or reject submitted certificates. `FleetManager` administers the fleet and policy surface — vessels, season rates, geo zones, maintenance windows, weather advisories — shares certificate decisions (revocation in particular) with `DockStaff`, and alone may drive the logical clock. `Mechanic` triages and resolves incidents, which is the exclusive trigger for mechanical refunds and the emergency maintenance cascade.

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

List endpoints are paginated through query parameters. The `limit` parameter caps the number of returned items; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Deterministic Sweep

All temporal behavior in the system is governed by a single logical clock — never by wall-clock time. At server startup the clock reads exactly `2026-08-01T00:00:00Z`, and before any clock-setting call it continues to read that default. Throughout this document, "the current date" means the calendar date (in UTC) of this logical clock, and "the current clock" means the full timestamp.

A `FleetManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The response reports the resulting `current_utc` alongside a `sweep_summary` describing what the advance triggered. Setting the clock runs a deterministic sweep with four effects:

1. Every `VERIFIED` safety certificate whose `expires_on` falls before the new current date transitions to `EXPIRED`, with a renter qualification recompute and — when the renter loses their last covering certificate — the full suspension cascade described in §3.3.
2. Every `SCHEDULED` maintenance window whose closed interval now contains the current date transitions to `IN_PROGRESS`, moving its vessel to `IN_MAINTENANCE`; every `IN_PROGRESS` window whose `end_date` has passed transitions to `COMPLETED`, returning the vessel to `AVAILABLE` when no other window of that vessel covers the current date.
3. Every `ACTIVE` weather advisory whose `window_end` now lies before the current clock transitions to `EXPIRED` and stops triggering both the weather cancellation variant and the checkout weather hold.
4. Every booking still in `HELD` whose `hold_expires_at` now lies before the current clock transitions to `EXPIRED`, releasing its (never-captured) deposit.

### 2.5. Common Resource Properties

Every resource in the system — vessels, season rates, geo zones, renters, safety certificates, bookings, itineraries, charges, incidents, maintenance windows, cleaning turns and weather advisories — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments on every modification.

A mutation is any change to the resource's stored fields, whether driven by a client request, a state transition, a cascade from another resource, or the clock sweep. On the booking aggregate, every transition of any of its four parallel dimensions (§2.10) — confirm, expiry, cancellation, checkout, interruption cycles, return, settlement, modification, and each orientation signature or countersignature — increments `Booking.version` by exactly 1 and refreshes `updated_at`.

### 2.6. Nested Resource Retrieval

Requests that address nested resources validate path identifiers strictly from left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in the path that does not correspond to an existing resource, before any later segment is examined. Identifiers referenced inside request payloads — the `vessel_id` and `renter_id` of a booking creation, the `booking_id` carried by itineraries, charges, incidents and cleaning turns, the `zone_ids` of a weather advisory, and each `zone_id` inside an itinerary waypoint — are validated the same way: a reference to a nonexistent resource yields `ERR_NOT_FOUND`.

### 2.7. Money, Integer Cents and the Pinned Rounding Order

All monetary values are represented as integer cents; no fractional cents ever appear in stored fields or responses. Wherever a computation produces a fractional cent result, the value is rounded half up to whole cents. One rounding discipline is pinned across every settlement-style computation: each charge line is computed and rounded to whole cents first, and any total is then the plain sum of those already-rounded lines. The system never sums unrounded components and rounds once at the end. Fuel quantities are the single non-monetary exception with its own rule: gallons owed are rounded half up to one decimal place before being priced. Scores (such as renter risk scores) are exact integers, and nightly-rate weekly discounts use whole-percent inputs so their products are exact without any rounding step.

### 2.8. Optimistic Concurrency Control

Two write operations on the booking aggregate are guarded by optimistic concurrency control: date modification and renter-initiated cancellation. Each request must carry `expected_booking_version`, a non-optional field holding the `version` of the booking as the client last observed it. If another writer has advanced the booking's version since that observation — for example a prior date modification that changed the quote, or a confirm that captured funds — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a booking state it has not observed. This stale-version check is evaluated before any other state preconditions of the operation. No endpoint other than these two accepts a version field.

### 2.9. Calendar Semantics: Half-Open Stays, Closed Windows

Three different interval conventions coexist in the domain, and each comparison must use the convention of its own type:

- A booking's stay is a **half-open** interval: `start_date` is the first occupied night (inclusive) and `end_date` is the checkout day (exclusive), so the nights occupied run from `start_date` through the day before `end_date`, and `total_nights` is the difference between the two dates in days. A single booking may span at most 21 nights. Overlap between two bookings is evaluated under half-open comparison, which means a back-to-back pair where one booking's `end_date` equals the other's `start_date` does **not** conflict — adjacency is allowed.
- Maintenance windows and season rate windows are **closed** intervals: both `start_date` and `end_date` are inclusive, and two closed intervals that merely touch at an endpoint are treated as conflicting.
- Weather advisories use a **half-open** datetime window: `window_start` is inclusive and `window_end` is exclusive.

Certificate coverage has its own inclusive rule: a certificate covers a trip if and only if its `expires_on` falls on or after the booking's `end_date`, so a certificate expiring exactly on the checkout day still covers the trip.

### 2.10. The Booking Aggregate: Four Parallel State Dimensions and the Charge Ledger

A booking is not a single state machine but four independent state dimensions coexisting on one row, each advancing under its own triggers:

- `status` — the lifecycle dimension: `HELD`, `CONFIRMED`, `CHECKED_OUT`, `INTERRUPTED`, `RETURNED`, `CLOSED`, `CANCELLED`, `EXPIRED`. The `CHECKED_OUT` ↔ `INTERRUPTED` pair forms the mechanical-failure cycle; `CLOSED`, `CANCELLED` and `EXPIRED` are terminal.
- `settlement_status` — the settlement dimension: `NONE`, `PROVISIONAL`, `FINALIZED`, advancing independently of the on-water cycle. The estimate fields obey their defining moments: `provisional_estimate_cents` is unset until checkout computes it, and `final_settlement_cents` is unset until settlement finalizes it.
- `deposit_status` — the deposit dimension: `PENDING`, `HELD`, `RELEASED`, `PARTIALLY_APPLIED`, `FULLY_APPLIED`. While the dimension is `PENDING`, `deposit_held_cents` is 0 — nothing has been captured. A hard invariant holds at every terminal state of this dimension: `deposit_applied_cents` plus `deposit_released_cents` always equals `deposit_held_cents`.
- `orientation_status` — the orientation dimension: `NOT_STARTED`, `IN_PROGRESS`, `COMPLETED`, `COUNTERSIGNED`, `CANCELLED`, including a reopen cycle from `COMPLETED` back to `IN_PROGRESS` when staff reject an item.

Money movement is never stored directly on the booking; it lives in an itemized **charge ledger**. Each ledger line carries a `booking_id`, a `line_type` drawn from `RENTAL`, `RENTAL_ADJUSTMENT`, `FUEL`, `PUMP_OUT`, `CLEANING_FEE`, `LATE_RETURN`, `DAMAGE`, `GROUNDING_LIABILITY`, `MECHANICAL_REFUND`, or `CANCELLATION_REFUND`; a signed `amount_cents` where refund lines are negative; a `status` of `POSTED`, `PAID`, `APPLIED_TO_DEPOSIT`, or `REFUNDED`; and a human-readable `note` recording provenance such as a source incident id or a cancellation reason. Lines whose computed amount is zero are never posted. The booking row itself carries the derived money fields `quoted_total_cents`, `deposit_required_cents`, `deposit_held_cents`, `deposit_applied_cents`, `deposit_released_cents`, `refund_issued_cents`, `provisional_estimate_cents`, and `final_settlement_cents`, each populated at the lifecycle moment that defines it.

### 2.11. Validation Priority Order

When several validations guard the same endpoint, they are evaluated in a fixed order so that the surfaced error is deterministic. The global order is:

1. Authentication — missing or unknown headers: `ERR_UNAUTHENTICATED`.
2. Role authorization — the role is not listed for the endpoint: `ERR_FORBIDDEN`.
3. Renter ownership — a `Renter` acting on another renter's resource: `ERR_NOT_RESOURCE_OWNER`.
4. Existence — any path id, or any payload-referenced id, that does not exist: `ERR_NOT_FOUND`.
5. Body well-formedness — missing required fields, type mismatches, unknown enum members, an unknown orientation `item_code`, empty `zone_ids`, a window whose end does not follow its start, a duplicate `zone_code`, or an `occurred_at` in the future or before the booking's start: `ERR_INVALID_REQUEST`.
6. Stale-version OCC on modify and cancel — evaluated before all other state preconditions: `ERR_STALE_VERSION`.
7. Generic transition state — the resource is not in a state that permits the requested transition (confirm on a non-`HELD` booking, checkout on a non-`CONFIRMED` booking, settle on a non-`RETURNED` booking, sign-item on a `COUNTERSIGNED` orientation, inspect on a turn that is not `IN_PROGRESS`, a decision on a non-`SUBMITTED` certificate, a resolve on a non-`REPORTED` incident): `ERR_INVALID_STATE`.
8. Cancellability — cancel attempted from `CHECKED_OUT`, `INTERRUPTED`, `RETURNED`, `CLOSED`, `CANCELLED` or `EXPIRED`: `ERR_BOOKING_NOT_CANCELLABLE`.
9. Business rules, in their own fixed relative order per endpoint family.

Within the booking creation / confirmation / modification family, the business checks fire in this sequence: renter qualification (`ERR_RENTER_NOT_QUALIFIED`) first, then booking date sanity (`ERR_BOOKING_DATES_INVALID`), then the half-open vessel overlap (`ERR_VESSEL_DATE_CONFLICT`), then the closed-interval maintenance conflict (`ERR_MAINTENANCE_DATE_CONFLICT`), then season-rate coverage (`ERR_RATE_NOT_CONFIGURED`), and finally party size (`ERR_PARTY_EXCEEDS_BERTH`). Itinerary submission orders its three business checks as: waypoint date range (`ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE`), then zone size-class permission (`ERR_ZONE_SIZE_CLASS_FORBIDDEN`), then zone capacity (`ERR_ZONE_CAPACITY_EXCEEDED`). Checkout fires the weather hold (`ERR_WEATHER_HOLD_ACTIVE`) ahead of its remaining business gates: itinerary presence (`ERR_ITINERARY_REQUIRED`), orientation countersignature (`ERR_ORIENTATION_NOT_COUNTERSIGNED`), cleaning-turn freedom (`ERR_CLEANING_TURN_INCOMPLETE`), and gauge validity (`ERR_FUEL_GAUGE_INVALID`). Incident resolution legality (`ERR_INCIDENT_RESOLUTION_MISMATCH`) closes the ordering as the final check of the resolve flow.

## 3. Business Logic & Workflows

### 3.1. Fleet Onboarding: Vessels, Season Rates and Cruising Zones

A `FleetManager` builds the rentable fleet one vessel at a time. Registering a vessel takes a display `name`, a `size_class` of `COMPACT_36`, `STANDARD_44`, or `LUXE_56`, a `berth_count` capping the overnight party size, an informational `home_marina`, and a `fuel_tank_capacity_gallons` that must be greater than zero. A new vessel starts `AVAILABLE`. The chosen `size_class` is not cosmetic: it selects which season-rate windows price the vessel's bookings, which base deposit tier applies, and which orientation item set the renter must complete before checkout.

Season pricing is configured per size class through rate windows. Each window names its `size_class`, a `season` label of `PEAK`, `SHOULDER`, or `OFF_PEAK` (informational only), an inclusive `start_date` and `end_date` bracketing the covered nights, a `nightly_rate_cents` that must be greater than zero, and a `weekly_discount_pct` — a whole percent from 0 to 50 granted for each complete run of seven nights falling inside the window. Because rate windows are closed intervals, two windows of the same `size_class` may not overlap at all, not even by sharing a single edge date; an overlapping submission is rejected with `ERR_SEASON_RATE_OVERLAP`.

The lake's cruising geography is divided into zones. Creating a zone requires a unique `zone_code` (a duplicate is rejected with `ERR_INVALID_REQUEST`), a display `name`, a `max_vessels_per_night` aggregate occupancy cap of at least 1, and `allowed_size_classes`, the list of size-class members permitted to overnight there. Zones anchor both itinerary validation and the weather-advisory system.

### 3.2. Planned Maintenance and Weather Advisories

Planned downtime is scheduled as a maintenance window on a specific vessel, with inclusive `start_date` and `end_date` (the end must not precede the start) and an optional free-text `reason`. A scheduled window is born with `source` `SCHEDULED_PLANNED` and status `SCHEDULED` — unless the current date already falls inside the window, in which case it is born `IN_PROGRESS` and immediately moves the vessel from `AVAILABLE` to `IN_MAINTENANCE`. Creation is refused with `ERR_MAINTENANCE_DATE_CONFLICT` in two situations: the window would intersect, under closed-interval comparison, any booking of the same vessel in `CONFIRMED`, `CHECKED_OUT`, `INTERRUPTED`, or `RETURNED` (a window whose `start_date` falls on or before the booking's `end_date` and whose `end_date` falls on or after the booking's `start_date` conflicts, touching endpoints included); or it would overlap another maintenance window of the same vessel, again with touching endpoints counting as a conflict. Thereafter the clock sweep drives the window lifecycle: `SCHEDULED` → `IN_PROGRESS` when the current date enters the interval (vessel to `IN_MAINTENANCE`), and `IN_PROGRESS` → `COMPLETED` once the current date passes `end_date`, returning the vessel to `AVAILABLE` provided no other window of that vessel covers the current date. Emergency windows created by incident resolution carry `source` `INCIDENT_EMERGENCY` and follow the same status machine (§3.7).

Weather advisories are the fleet's early-warning surface. Issuing one takes a `severity` of `WATCH`, `WARNING`, or `STORM`, a non-empty `zone_ids` list in which every referenced zone must exist (`ERR_NOT_FOUND` otherwise), and a half-open datetime window from `window_start` (inclusive) to `window_end` (exclusive, and required to be later than the start, else `ERR_INVALID_REQUEST`). An advisory is `ACTIVE` from creation until the clock sweep moves it to `EXPIRED` once `window_end` lies before the current clock. Only `ACTIVE` advisories have teeth: they feed the checkout weather hold (§3.6) and the 100% weather cancellation variant (§3.9); expired advisories trigger neither.

### 3.3. Renter Registration and Boating-Safety Qualification

A customer self-registers with `full_name`, `email`, and `date_of_birth`. A new renter's `qualification_status` starts at `UNVERIFIED`, with `risk_score_lifetime` and `risk_score_rolling_24m` both at 0 and a `deposit_multiplier` of 1.0. Qualification is not edited directly; it is derived from the renter's boating-safety certificates through a recompute that runs after every certificate state change.

A renter submits a certificate with its `cert_number`, an `issuing_authority` of `NASBLA`, `USCG`, or `STATE`, the `issued_on` date, and the `expires_on` date; the certificate starts `SUBMITTED`. Submission is also the renewal path: after a certificate reaches `REJECTED`, `EXPIRED`, or `REVOKED`, the renter qualifies again only by submitting a new certificate resource. `DockStaff` adjudicates submissions through a `decision` of `VERIFY` or `REJECT` (permitted only while the certificate is `SUBMITTED`, otherwise `ERR_INVALID_STATE`), moving it to `VERIFIED` or `REJECTED`. A later `decision` of `REVOKE` — the `FleetManager`'s prerogative, with the decision endpoint itself shared between `DockStaff` and `FleetManager` — moves a `VERIFIED` certificate to `REVOKED`; revocation of anything not `VERIFIED` is likewise `ERR_INVALID_STATE`. Independently, the clock sweep moves a `VERIFIED` certificate to `EXPIRED` once its `expires_on` falls before the current date.

Every one of these transitions triggers the qualification recompute on the owning renter. The rule is simple: a renter is `QUALIFIED` while at least one of their certificates is `VERIFIED` with `expires_on` on or after the current date. The first verification lifts an `UNVERIFIED` renter to `QUALIFIED`; a fresh verification likewise restores a `SUSPENDED` renter. The moment the last covering certificate is revoked or expires, the renter drops to `SUSPENDED` — and the system does not leave their future charters stranded in limbo. The suspension cascade cancels every booking of the renter that is in `HELD` or `CONFIRMED` with a `start_date` after the current date, stamping `cancellation_reason` `RENTER_SUSPENDED`: confirmed bookings receive a 100% rental refund posted as a negative `CANCELLATION_REFUND` charge, deposits are `RELEASED`, cleaning turns and orientations are `CANCELLED`, and any `APPROVED` itinerary becomes `VOID`, freeing its zone occupancy.

Resolved incidents feed the renter's risk profile. Two scores are maintained and recomputed eagerly whenever one of the renter's incidents reaches `RESOLVED` (rejected incidents never count): `risk_score_lifetime` sums a severity weight — 10 for `MINOR`, 25 for `MAJOR`, 60 for `TOTAL_LOSS` — over every resolved incident on any of the renter's bookings, with no time window; `risk_score_rolling_24m` applies the same sum but only to incidents whose `occurred_at` falls on or after the date exactly 24 months before the current date, boundary inclusive, so an identical history yields a lower score once an old incident ages out. The rolling variant alone drives the deposit tier: a rolling score below 20 means a `deposit_multiplier` of 1.0, a score of at least 20 but below 50 means 1.5, and a score of 50 or more means 2.0. The multiplier is re-derived from future computations only — deposits already snapshotted on existing bookings never move.

### 3.4. Quoting and Booking Creation: The 48-Hour Hold

A `Renter` opens a booking with a payload naming the `vessel_id`, their own `renter_id` (which must equal `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`), the desired `start_date` and `end_date`, and the `party_size`. Validation follows the fixed order of §2.11: the renter must be `QUALIFIED` and hold at least one `VERIFIED` certificate whose `expires_on` reaches the booking's `end_date` (`ERR_RENTER_NOT_QUALIFIED`); `end_date` must follow `start_date`, the stay must not exceed 21 nights, and `start_date` must not lie in the past (`ERR_BOOKING_DATES_INVALID`); the half-open stay interval must not intersect any other booking of the same vessel in `CONFIRMED`, `CHECKED_OUT`, `INTERRUPTED`, or `RETURNED`, with pure adjacency allowed (`ERR_VESSEL_DATE_CONFLICT`); no `SCHEDULED` or `IN_PROGRESS` maintenance window of the vessel may intersect the stay under closed-interval comparison (`ERR_MAINTENANCE_DATE_CONFLICT`); every night of the stay must be covered by a season rate of the vessel's size class (`ERR_RATE_NOT_CONFIGURED`); and `party_size` must be at least 1 and no more than the vessel's `berth_count` (`ERR_PARTY_EXCEEDS_BERTH`).

The quote is computed night by night over the half-open stay. Each night is priced at the `nightly_rate_cents` of the rate window matching the vessel's `size_class` whose closed interval covers that night; a night with no covering rate fails the booking with `ERR_RATE_NOT_CONFIGURED`. The subtotal is the sum of those nightly prices. The weekly discount is then computed per rate window independently: for each window touched by the stay, count the nights of the stay falling within that window's closed interval, take the complete 7-night runs in that count (the count divided by 7, rounded down), and discount each run by seven times the window's nightly rate times its whole-percent `weekly_discount_pct` divided by 100. `quoted_total_cents` is the subtotal minus the sum of the per-window discounts. Weekly runs never span a season boundary: a 15-night stay split 4 nights into one window and 11 into the next earns no discounted run in the first window (4 nights hold no complete run of 7) and exactly one discounted run in the second (11 nights hold one run of 7).

The deposit requirement is computed once, at creation, and snapshotted into `deposit_required_cents`, never to be recomputed afterwards even if the renter's risk score changes later. The base depends on size class — 150,000 cents for `COMPACT_36`, 200,000 cents for `STANDARD_44`, 250,000 cents for `LUXE_56` — and is multiplied by the renter's current `deposit_multiplier` (1.0, 1.5, or 2.0 per the rolling-risk tiers of §3.3).

A created booking lands in `HELD` with `settlement_status` `NONE`, `deposit_status` `PENDING`, and `orientation_status` `NOT_STARTED`; `total_nights` is stored, the quote is pinned, and `hold_expires_at` is set to 48 hours after `created_at`. If the renter never confirms, the clock sweep moves a `HELD` booking whose `hold_expires_at` has passed to `EXPIRED`: since no funds were ever captured, the deposit dimension goes straight from `PENDING` to `RELEASED` with `deposit_held_cents`, `deposit_applied_cents` and `deposit_released_cents` all at 0, and `Booking.version` increments. For planning and reconciliation, the booking list view accepts optional `vessel_id`, `renter_id` and `status` filters alongside pagination; a `Renter` caller only ever sees their own bookings there.

### 3.5. Confirmation, Safety Orientation and Itinerary Approval

Confirmation is the renter's commitment point, and it re-runs the creation-time safety net before any money moves: the booking must still be `HELD`, the renter must still be `QUALIFIED` with a `VERIFIED` certificate covering `end_date` (`ERR_RENTER_NOT_QUALIFIED`), the `start_date` must not have slipped into the past (`ERR_BOOKING_DATES_INVALID`), and the vessel-overlap, maintenance and rate-coverage checks are re-evaluated (`ERR_VESSEL_DATE_CONFLICT`, `ERR_MAINTENANCE_DATE_CONFLICT`, `ERR_RATE_NOT_CONFIGURED`). On success the cascade is extensive. The quote is recomputed and pinned into `quoted_total_cents`; a `RENTAL` charge for that amount is posted already `PAID`; the deposit dimension moves `PENDING` → `HELD` with `deposit_held_cents` set to `deposit_required_cents`; orientation moves `NOT_STARTED` → `IN_PROGRESS` with its item set created from the vessel's size class; a cleaning turn is created for the booking with `scheduled_date` equal to the booking's `end_date`, status `SCHEDULED`, and `re_clean_count` 0; and `Booking.version` increments by 1.

The orientation item set is pinned at confirm time by size class: every vessel requires `SAFETY_BRIEF`, `DOCKING`, `ANCHORING`, and `GENERATOR_OPS`, and a `LUXE_56` adds `THRUSTER_OPS` and `SEWAGE_PUMPOUT`. The `orientation_items` array records each entry as an `item_code` with a `signed` flag, all initially false. The renter signs items one at a time by `item_code`; signing an item requires the orientation to be `IN_PROGRESS` (signing on a `COUNTERSIGNED` orientation is rejected with `ERR_INVALID_STATE`), and each signature increments `Booking.version`. When the last unsigned item is signed, the orientation moves `IN_PROGRESS` → `COMPLETED` automatically. A `DockStaff` member then countersigns with `approved` set to true, moving `COMPLETED` → `COUNTERSIGNED` — or rejects the work by responding with `approved` false and an `item_code` present in the booking's item set (an unknown code is `ERR_INVALID_REQUEST`), which reopens the cycle to `IN_PROGRESS` and resets that item's `signed` flag to false. Both countersignature paths increment `Booking.version`. If the booking is cancelled at any point, an orientation in `IN_PROGRESS`, `COMPLETED`, or `COUNTERSIGNED` moves to `CANCELLED`.

Before the vessel can leave the dock, the renter must also file where they intend to overnight. Submitting the itinerary — allowed only while the booking is `HELD` or `CONFIRMED`, with attempts on a booking in any other state rejected by the generic `ERR_INVALID_STATE` — carries a `waypoints` array, each entry pairing a `zone_id` with a `night_date`. Validation is atomic and ordered per §2.11: every `night_date` must be an actual night of the booking, meaning it falls on or after `start_date` and before `end_date` (`ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE`); every referenced zone must list the vessel's size class in its `allowed_size_classes` (`ERR_ZONE_SIZE_CLASS_FORBIDDEN`); and for every waypoint, the zone's occupancy on that night must remain strictly below its `max_vessels_per_night` (`ERR_ZONE_CAPACITY_EXCEEDED`). Occupancy for a zone-night counts `APPROVED` itineraries — `SUPERSEDED` and `VOID` records never count — whose bookings sit in `CONFIRMED`, `CHECKED_OUT`, `INTERRUPTED`, or `RETURNED` and which contain a waypoint on that zone and night. A booking never counts against itself: submitting a replacement supersedes the booking's prior `APPROVED` itinerary before any counting, so the new record is evaluated against other bookings only. A fully valid submission is created already `APPROVED`, and occupancy immediately reflects only the replacement's waypoints. A later booking cancellation moves the `APPROVED` itinerary to `VOID` and frees its zone-nights.

Dates are not frozen at confirmation. While the booking is `HELD` or `CONFIRMED` — any other state fails the generic state check with `ERR_INVALID_STATE` — the renter may modify `start_date` and `end_date`, provided the request carries `expected_booking_version` matching the booking's current `version` (a mismatch is `ERR_STALE_VERSION`, checked first). The new dates must satisfy the same date sanity (at least one night, at most 21, not starting in the past — `ERR_BOOKING_DATES_INVALID`), the half-open overlap recheck excluding the booking itself (`ERR_VESSEL_DATE_CONFLICT`), the closed-interval maintenance recheck (`ERR_MAINTENANCE_DATE_CONFLICT`), and full season-rate coverage of every new night (`ERR_RATE_NOT_CONFIGURED`). Modification updates the dates, recomputes `total_nights`, and recomputes the quote into `quoted_total_cents`; a `HELD` booking simply stays `HELD`. When a `CONFIRMED` booking's quote changes, the delta is posted as a `RENTAL_ADJUSTMENT` charge equal to the new quote minus the old: a positive delta is posted `PAID` with funds captured immediately, while a negative delta is posted `REFUNDED` and its absolute amount is added to `refund_issued_cents`. The still-`SCHEDULED` cleaning turn of the booking has its `scheduled_date` reset to the new `end_date`, and `Booking.version` increments.

### 3.6. Checkout Under a Weather Watch

Checkout is a `DockStaff` action performed on the day the charter begins: the current date must fall on or after the booking's `start_date` and strictly before its `end_date`, and the booking must be `CONFIRMED`. The gates, in their mandated order after the generic state check, are: no `ACTIVE` weather advisory may cover the current clock while its `zone_ids` intersect the zones of the booking's `APPROVED` itinerary (`ERR_WEATHER_HOLD_ACTIVE`); an `APPROVED` itinerary must exist at all (`ERR_ITINERARY_REQUIRED`); the orientation must stand at `COUNTERSIGNED` (`ERR_ORIENTATION_NOT_COUNTERSIGNED`); no cleaning turn of any booking on the same vessel may be `IN_PROGRESS` (`ERR_CLEANING_TURN_INCOMPLETE`); and the deposit dimension must be `HELD` — a deposit out of order surfaces the generic `ERR_INVALID_STATE`. One gate is deliberately missing: there is no vessel-status check at checkout. Planned maintenance can never overlap a blocking booking because window creation forbids it, and emergency windows cascade-cancel any overlapping booking, so a vessel in `IN_MAINTENANCE` on a checkout day is unreachable by design.

The checkout payload records the vessel's condition at hand-over: `fuel_gauge_percent` — an integer from 0 to 100, anything outside rejected with `ERR_FUEL_GAUGE_INVALID` — and `pump_out_done`, whether the waste tanks were pumped out. These land in `checkout_fuel_gauge_percent` and `checkout_pump_out_done`. Checkout then moves the lifecycle `CONFIRMED` → `CHECKED_OUT` and the settlement dimension `NONE` → `PROVISIONAL`, computing `provisional_estimate_cents` as the provisional settlement variant: fuel is estimated at a 50% burn of the tank — half of `fuel_tank_capacity_gallons`, rounded half up to one decimal place, priced at 700 cents per gallon; the pump-out fee of 15,000 cents is assumed due; the cleaning fee of 25,000 cents is included; and late-return, damage, grounding and mechanical-refund components are all zero. The provisional figure therefore deliberately differs from the eventual final settlement for the same booking. `Booking.version` increments.

### 3.7. On the Water: Incidents, Interruption and Emergency Repair

When something goes wrong mid-charter, the renter reports an incident on their own booking, supplying an `incident_type` of `MECHANICAL_FAILURE`, `GROUNDING`, or `DAMAGE`, the `occurred_at` timestamp — which must fall on or after the booking's `start_date` and not after the current logical clock, otherwise `ERR_INVALID_REQUEST` — and an optional free-text `description`. Reporting is only meaningful on an active or completed charter: the booking must be in `CHECKED_OUT`, `INTERRUPTED`, `RETURNED`, or `CLOSED` (`ERR_INVALID_STATE` otherwise). The incident starts `REPORTED`, with `severity`, `resolution`, `downtime_days`, and `assessed_damage_cents` all unset until a resolution supplies them.

A `Mechanic` resolves it with a `resolution` plus the type-appropriate fields. The legal mapping is strict, and any deviation is `ERR_INCIDENT_RESOLUTION_MISMATCH`: a `MECHANICAL_FAILURE` resolves as `REPAIRED_RESUME` or `REPAIRED_TERMINATE`; a `GROUNDING` resolves only as `GROUNDING_CONFIRMED`; a `DAMAGE` resolves only as `DAMAGE_ASSESSED`. The mechanical resolutions additionally require a `severity` of `MAJOR` or `TOTAL_LOSS` and a `downtime_days` of at least 1 and no more than the nights remaining from the current date to `end_date` — a `MINOR` mechanical failure can never take a `REPAIRED_` resolution and, if chargeable, must instead be reported and resolved as `DAMAGE`. `DAMAGE_ASSESSED` requires an `assessed_damage_cents` of zero or more (`ERR_INVALID_REQUEST` otherwise). Resolving with `resolution` `REJECTED` moves the incident to `REJECTED` with no charges and no state changes on booking or vessel. Every other resolution moves it to `RESOLVED`, recording `severity`, `resolution`, `downtime_days`, and `assessed_damage_cents` as applicable, and firing one of four cascades:

- `REPAIRED_RESUME` — the repair completes on the water. The booking cycles `CHECKED_OUT` → `INTERRUPTED` and back to `CHECKED_OUT`, the settlement dimension stays `PROVISIONAL` throughout, and a prorated mechanical refund is posted as a single negative `MECHANICAL_REFUND` charge: the pinned `quoted_total_cents` times `downtime_days` divided by `total_nights`, rounded half up to whole cents.
- `REPAIRED_TERMINATE` — the charter cannot continue. The booking moves `CHECKED_OUT` → `INTERRUPTED`, and the refund covers only full remaining nights: `quoted_total_cents` times the nights from the current date to `end_date`, divided by `total_nights`, rounded half up — the interruption day itself counts as used. The vessel drops to `IN_MAINTENANCE`, and an emergency maintenance window is born already `IN_PROGRESS` with `source` `INCIDENT_EMERGENCY`, covering the closed interval from the current date through the current date plus `downtime_days`. That window then behaves like any maintenance conflict: every other booking of the vessel in `HELD` or `CONFIRMED` overlapping it under closed-interval comparison is cascade-cancelled with `cancellation_reason` `VESSEL_MECHANICAL` and the full 100% refund treatment.
- `GROUNDING_CONFIRMED` — a positive `GROUNDING_LIABILITY` charge is posted on the booking, sized by severity: 50,000 cents for `MINOR`, 250,000 cents for `MAJOR`, 900,000 cents for `TOTAL_LOSS`.
- `DAMAGE_ASSESSED` — a positive `DAMAGE` charge of `assessed_damage_cents` is posted on the booking.

In every `RESOLVED` case, the renter risk recompute of §3.3 runs for the booking's renter, refreshing both score variants and re-deriving the deposit tier for future bookings only. All of these incident charges sit `POSTED` on the ledger, waiting for settlement to reconcile them.

### 3.8. Return, Cleaning Turn and Final Settlement

Return is the mirror of checkout, again performed by `DockStaff` against a booking in `CHECKED_OUT` or `INTERRUPTED`; a booking in any other state is refused with `ERR_INVALID_STATE`. The payload carries `fuel_gauge_percent` (the same 0–100 rule, `ERR_FUEL_GAUGE_INVALID`), `pump_out_done`, and `actual_return_at`, the physical return timestamp, which must not precede the booking's start (`ERR_INVALID_REQUEST`); the prior checkout readings must already be present. The values are recorded into `return_fuel_gauge_percent`, `return_pump_out_done`, and `actual_return_at`, the lifecycle moves to `RETURNED`, the booking's `SCHEDULED` cleaning turn moves to `IN_PROGRESS` to start the turn-around, and `Booking.version` increments.

The cleaning turn gates settlement. `DockStaff` inspects the in-progress turn with a `passed` verdict: a pass moves it `IN_PROGRESS` → `COMPLETED`; a fail keeps it `IN_PROGRESS` in a self-loop and bumps `re_clean_count` by 1 for the re-clean. Inspecting a turn that is not `IN_PROGRESS` is `ERR_INVALID_STATE`. A turn whose booking is cancelled moves to `CANCELLED` from either `SCHEDULED` or `IN_PROGRESS`.

Settlement closes the charter and is allowed only from `RETURNED`, and only once this booking's own cleaning turn is `COMPLETED` (`ERR_CLEANING_TURN_INCOMPLETE` otherwise). The final settlement nets every incidental against the deposit, computed line by line under the pinned rounding order of §2.7 — each line rounded half up to whole cents first, then plainly summed, with the rental itself excluded because it was prepaid at confirmation:

- **Fuel.** The gauge delta is the checkout gauge minus the return gauge, floored at zero — returning with more fuel than checkout earns no credit. Gallons owed are that delta times `fuel_tank_capacity_gallons` divided by 100, rounded half up to one decimal place, priced at 700 cents per gallon.
- **Pump-out.** The 15,000-cent fee applies when the tanks were pumped at checkout (`checkout_pump_out_done`) but not at return (`return_pump_out_done`); otherwise zero.
- **Cleaning.** The 25,000-cent cleaning fee is always charged.
- **Late return.** The return deadline is 10:00:00Z on the booking's `end_date`. When `actual_return_at` passes the deadline, the excess is rounded up to whole hours and billed at 5,000 cents per hour; an on-time return owes nothing.
- **Incident lines.** Every already-`POSTED` incident charge of the booking is summed in — positive `DAMAGE` and `GROUNDING_LIABILITY` lines, negative `MECHANICAL_REFUND` lines.

Non-zero operational lines are posted to the ledger as `POSTED` charges (the cleaning fee is always posted, and zero-amount lines never are), and `final_settlement_cents` records the net. The deposit waterfall then reconciles the held deposit. When the net is zero or positive, `deposit_applied_cents` becomes the smaller of the net and `deposit_held_cents`, `deposit_released_cents` becomes the remainder of the held amount, and the renter separately owes whatever the net exceeds the deposit by; the deposit dimension lands at `RELEASED` when nothing was applied, `PARTIALLY_APPLIED` when the applied portion is positive but below the held amount, or `FULLY_APPLIED` when the entire deposit was consumed. When the net is negative — refunds exceed charges — nothing is applied, `deposit_released_cents` equals `deposit_held_cents`, and the absolute net is added to `refund_issued_cents`. Ledger hygiene follows: positive incident and operational lines consumed by the deposit are marked `APPLIED_TO_DEPOSIT`, and negative refund lines are marked `REFUNDED`. The settlement dimension moves `PROVISIONAL` → `FINALIZED`, the lifecycle moves `RETURNED` → `CLOSED`, and `Booking.version` increments.

### 3.9. Cancellation and the Weather Refund Policy

A renter may cancel their own booking while it is `HELD` or `CONFIRMED`; from any other state — `CHECKED_OUT`, `INTERRUPTED`, `RETURNED`, `CLOSED`, `CANCELLED`, or `EXPIRED` — the attempt is `ERR_BOOKING_NOT_CANCELLABLE`. The request carries `expected_booking_version` (stale observations are refused with `ERR_STALE_VERSION` before any other check) and an optional `reason`. The `cancellation_reason` field stays unset for the booking's whole life unless it is cancelled, at which point it records one of `RENTER_REQUEST`, `WEATHER`, `RENTER_SUSPENDED`, or `VESSEL_MECHANICAL`. The refund depends on the booking's state and on why the cancellation happens.

From `HELD`, nothing was ever paid and the deposit was never captured, so the refund is zero. From `CONFIRMED`, the standard policy tiers the refund against the pinned `quoted_total_cents` by the whole days between the current date and `start_date`: 30 or more days out refunds 90%; at least 14 but fewer than 30 days refunds 50%; at least 8 but fewer than 14 days refunds 25%; and fewer than 8 days refunds nothing. The weather variant overrides the tiers entirely: if any `ACTIVE` advisory's window overlaps the stay — its `window_start` falls before the booking's `end_date` and its `window_end` after the booking's `start_date` — and its `zone_ids` intersect the zones of the booking's `APPROVED` itinerary, the refund is a flat 100% regardless of timing, and `cancellation_reason` is stamped `WEATHER`. That stamp is honest: it is set only when the weather variant actually applied, and otherwise a renter-initiated cancellation records `RENTER_REQUEST`. The same booking can therefore legitimately yield 0% under the standard policy or 100% under the weather policy depending only on advisory coverage. System-initiated cancellations — `RENTER_SUSPENDED` from the certificate cascade and `VESSEL_MECHANICAL` from the emergency-window cascade — always take the 100% path. Whatever the percentage, the refund amount is the pinned quote times the percentage divided by 100, rounded half up to whole cents.

The cancellation cascade then settles the booking's world. When the booking was `CONFIRMED` and the refund is positive, a negative `CANCELLATION_REFUND` charge is posted already `REFUNDED`, and its amount is added to `refund_issued_cents`. The deposit dimension moves to `RELEASED` with `deposit_released_cents` equal to `deposit_held_cents` and `deposit_applied_cents` at 0. The cleaning turn, if `SCHEDULED` or `IN_PROGRESS`, is `CANCELLED`; the orientation, if `IN_PROGRESS`, `COMPLETED`, or `COUNTERSIGNED`, is `CANCELLED`; and an `APPROVED` itinerary becomes `VOID`, freeing its zone-night occupancy for other renters. `Booking.version` increments, and the lifecycle dimension rests at `CANCELLED`.

## 4. Endpoint Definitions

Operations that create a new resource — vessels, season rates, geo zones, maintenance windows, weather advisories, renters, certificates, bookings, itineraries, and incident reports — return `201 Created`. Operations that act on an existing resource without creating a new one — confirmations, modifications, cancellations, decisions, signatures, checkout, return, settlement, inspections, resolutions, and the clock advance — return `200 OK`, as do all retrievals.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vessels` | Register a vessel in the fleet | FleetManager |
| GET | `/vessels/{id}` | Get vessel details including current status | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/season-rates` | Create a season rate window for a size class | FleetManager |
| POST | `/geo-zones` | Create a geographic zone with nightly capacity and allowed size classes | FleetManager |
| POST | `/vessels/{id}/maintenance-windows` | Schedule a maintenance window (closed interval) | FleetManager |
| GET | `/vessels/{id}/maintenance-windows` | List maintenance windows of a vessel | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/weather-advisories` | Issue a weather advisory over zones and a datetime window | FleetManager |
| POST | `/renters` | Register a renter (self-service) | Renter |
| GET | `/renters/{id}` | Get renter profile including qualification status and both risk-score variants | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/renters/{id}/certificates` | Submit a boating-safety certificate (also the resubmission path) | Renter |
| GET | `/renters/{id}/certificates` | List certificates of a renter | Renter, DockStaff, FleetManager |
| POST | `/certificates/{id}/decision` | Verify or reject a `SUBMITTED` certificate, or revoke a `VERIFIED` one | DockStaff, FleetManager |
| POST | `/bookings` | Create a booking in `HELD` with computed quote and deposit requirement | Renter |
| GET | `/bookings/{id}` | Get a booking with all four parallel state dimensions and ledger fields | Renter, DockStaff, FleetManager, Mechanic |
| GET | `/bookings` | List bookings with filters and pagination | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/bookings/{id}/confirm` | Confirm a `HELD` booking: pin quote, capture rental and deposit, create orientation and cleaning turn | Renter |
| POST | `/bookings/{id}/modify` | Change dates of a `HELD` or `CONFIRMED` booking (OCC-guarded) | Renter |
| POST | `/bookings/{id}/cancel` | Renter-initiated cancel (OCC-guarded) with tiered or weather-variant refund | Renter |
| PUT | `/bookings/{id}/itinerary` | Submit or replace the itinerary; validates atomically and approves | Renter |
| GET | `/bookings/{id}/itinerary` | List itineraries of a booking (current and historical) | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/bookings/{id}/orientation/sign-item` | Sign one orientation item | Renter |
| POST | `/bookings/{id}/orientation/countersign` | Countersign a completed orientation, or reject one item to reopen | DockStaff |
| POST | `/bookings/{id}/checkout` | Check out the vessel: record gauge and pump-out, compute provisional estimate | DockStaff |
| POST | `/bookings/{id}/return` | Check the vessel back in and start the cleaning turn | DockStaff |
| POST | `/bookings/{id}/settle` | Finalize settlement: charge lines, deposit waterfall, refunds | DockStaff |
| GET | `/bookings/{id}/cleaning-turns` | List cleaning turns of a booking | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/cleaning-turns/{id}/inspect` | Inspect an in-progress turn: pass completes, fail re-cleans | DockStaff |
| POST | `/bookings/{id}/incidents` | Report an incident on an active booking | Renter |
| GET | `/bookings/{id}/incidents` | List incidents of a booking | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/incidents/{id}/resolve` | Resolve an incident with type-specific cascades | Mechanic |
| GET | `/bookings/{id}/charges` | List the itemized charge ledger of a booking | Renter, DockStaff, FleetManager, Mechanic |
| POST | `/_clock/set_current_utc` | Advance the test-driving logical clock and run the deterministic sweep | FleetManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_BOOKING_DATES_INVALID` | 422 Unprocessable Entity |
| `ERR_VESSEL_DATE_CONFLICT` | 409 Conflict |
| `ERR_MAINTENANCE_DATE_CONFLICT` | 409 Conflict |
| `ERR_SEASON_RATE_OVERLAP` | 409 Conflict |
| `ERR_RATE_NOT_CONFIGURED` | 422 Unprocessable Entity |
| `ERR_RENTER_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_WEATHER_HOLD_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ITINERARY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ORIENTATION_NOT_COUNTERSIGNED` | 409 Conflict |
| `ERR_CLEANING_TURN_INCOMPLETE` | 409 Conflict |
| `ERR_FUEL_GAUGE_INVALID` | 422 Unprocessable Entity |
| `ERR_ITINERARY_WAYPOINT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ZONE_SIZE_CLASS_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PARTY_EXCEEDS_BERTH` | 422 Unprocessable Entity |
| `ERR_INCIDENT_RESOLUTION_MISMATCH` | 422 Unprocessable Entity |
