# Scenic Dinner Train Operations API — Product Requirements Document

## 1. Introduction

A tourist railroad lives and dies by a timetable it does not fully own. Excursion and dinner trains run over track belonging to a host railroad, inside negotiated operating windows, with a fleet of vintage locomotives and cars that cycle between service and the shop, staffed by a mix of paid crew and volunteers, and sold to the public as coach seats, first-class seats, and seatings at four-top dining tables. When a storm cell parks itself over the subdivision or a track rights agreement lapses, an entire evening's sold-out train has to be unwound — passengers refunded or handed rain-checks, crew released, and the galley's perishable provisions reconciled against a manifest that may already be locked.

This document specifies the Scenic Dinner Train Operations API, mounted under the `/railroad` prefix, which manages that entire operating cycle: negotiating track rights agreements and carving them into daily operating slots, rostering and maintaining rolling stock, building an excursion's consist and crew, publishing and boarding the train, selling and confirming tickets with surge-priced holiday fares, provisioning the dining cars from a live passenger manifest, and — when things go wrong — cancelling cleanly with refunds and rain-checks. All time inside the system is driven by a testable logical clock rather than the wall clock, so that holds, refund windows, and rain-check expirations behave deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles: `Scheduler`, `Mechanic`, `StationAgent`, `CrewManager`, `CateringManager`, and `OperationsManager`. For every one of these six roles — `Scheduler`, `Mechanic`, `StationAgent`, `CrewManager`, `CateringManager`, and `OperationsManager` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any resource's `id`, and ownership-style checks simply do not exist in this system. Authorization is purely role-based: each write operation is restricted to the roles listed for it in §4 (with some event endpoints split further by `event_type`), and an authenticated operator attempting an operation outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403). All read and list endpoints are shared by all six roles.

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

List endpoints paginate through two query parameters. `limit` caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. All list endpoints sort by `created_at` ascending unless stated otherwise. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — agreements, slots, rolling stock, work orders, excursions, car assignments, bookings, crew members, crew assignments, provisioning manifests, and rain-checks — carries the same four system-managed properties. `id` is a server-minted UUID with no type prefix; it serves identity only and is never an input to any business decision. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including automatic reconciliations.

Mutations are not limited to direct edits. When a consist or roster change touches an excursion, the excursion's own `version` increments and its `updated_at` refreshes, even though the client never wrote to the excursion itself. The same holds for recomputed derived fields: recomputing a DRAFT provisioning manifest's counts is a mutation of the manifest, bumping its `version` by 1. Clients that cache a resource must treat its `version` as the single source of truth for what they have actually observed.

### 2.5. The Logical Clock and Scheduled Sweeps

The system never reads the wall clock. All temporal behavior — hold expirations, refund windows, rain-check validity, service-date gating — is evaluated against a logical clock whose startup value is exactly 2026-08-01T00:00:00Z. An `OperationsManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and reports the new value as `current_utc`.

Every clock advance runs a sweep in a fixed order. First, bookings still in `HELD` whose `expires_at` is at or before the new clock instant are swept to `CANCELLED` with no refund, processed earliest `expires_at` first. Second, rain-checks still `ISSUED` whose `expires_on` is earlier than the new clock date flip to `EXPIRED`, processed earliest `expires_on` first. A freshly created booking's hold lasts 45 minutes: its `expires_at` is its `created_at` plus 45 minutes. A rain-check lives for 365 days: its `expires_on` is its `issued_on` plus 365 days, and it remains redeemable through that date inclusive — only a clock date strictly later than `expires_on` expires it.

### 2.6. Fares, Money, and Rounding Conventions

All money in the system is integer cents; no fractional cents ever appear. Base fares per passenger are fixed by class: 6000 cents for `COACH`, 11000 cents for `FIRST_CLASS`, and 15000 cents for `DINING`. An excursion applies a surge multiplier expressed in basis points over the base fare, where 10000 basis points means exactly the base fare. A `REGULAR` excursion must carry a `surge_multiplier_bp` of exactly 10000; a `HOLIDAY` excursion must carry a value between 12000 and 20000 inclusive. Anything else is rejected with `ERR_SURGE_MULTIPLIER_INVALID` (HTTP 422).

When a fare is quoted, the rounding order is pinned: the unit fare is computed first — the class base fare scaled by the excursion's surge multiplier — rounded half-up to a whole cent, and only then multiplied by the party size to produce the booking total. Rounding the product instead of the unit fare is a specification violation. The same round-half-up convention applies wherever a fractional cent could arise, including the half-refund calculation described in §3.6.

### 2.7. Timetable Time: Service Dates, Minute-of-Day Windows, and the Turnaround Buffer

Three kinds of time windows coexist in the system, and each has its own arithmetic. A **service date** is an ISO calendar date (YYYY-MM-DD) on which a train runs. An **operating slot** is a half-open interval within one service date, expressed as minute-of-day integers: `start_minute` runs from 0 through 1439 and `end_minute` from 1 through 1440, with the interval covering the start minute and excluding the end minute. Because the intervals are half-open, two slots on the same agreement and date may touch — one slot's `end_minute` equal to another's `start_minute` is adjacency, not overlap. A slot's duration in minutes must be at least the `min_slot_minutes` of its agreement, and `min_slot_minutes` itself is never below 30. For refund purposes, a slot's start instant is the service date's midnight UTC plus `start_minute` minutes.

A **maintenance window** is a half-open interval between two ISO datetimes, `window_start` inclusive and `window_end` exclusive, and the end must be strictly later than the start. Unlike slots, maintenance windows on the same unit of rolling stock demand breathing room: between two `SCHEDULED` or `IN_PROGRESS` work orders on the same unit there must be a gap of at least 60 minutes — the turnaround buffer — so mere adjacency without a 60-minute gap is a conflict, not a convenience.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject a stale client view with `ERR_STALE_VERSION` (HTTP 412).

The first guards excursion publication. A publish request must carry `expected_excursion_version`, the `version` of the excursion the client last observed. Because every consist edit and every crew assignment or release increments the excursion's `version`, a client whose view predates any such change holds a stale number; if `expected_excursion_version` does not equal the excursion's current `version`, the publish is rejected with `ERR_STALE_VERSION` and the client must re-read the excursion and re-publish what it actually reviewed.

The second guards manifest locking. A lock request must carry `expected_manifest_version`, the `version` of the provisioning manifest the client last observed. Every booking create, confirm, cancel, or rain-check cascade that recomputes a DRAFT manifest increments that version, so a lock submitted against an older number is rejected with `ERR_STALE_VERSION`, ensuring catering always locks the numbers it actually reviewed. Endpoints other than these two take no version field at all.

### 2.9. Validation Order and Hierarchical Consistency

Requests are validated against a fixed priority pipeline, and when several checks could fail, the earliest tier's error is the one returned. The tiers run in this order:

1. **Authentication**: `X-User-Role` and `X-User-ID` present and the role recognized — otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization**: the role is permitted on this endpoint, and on event endpoints on this particular `event_type` — otherwise `ERR_FORBIDDEN`.
3. **Path existence**: resource identifiers in the URL are validated left to right; the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before anything deeper is examined.
4. **Event/state validity**: the target entity is in a legal from-state for the requested event — events on terminal entities, out-of-order boarding or operation, consist edits on a non-`DRAFT` excursion, starting a work order on a unit that is not `AVAILABLE`, checking in while the excursion is not `BOARDING`, and creating an excursion on a slot that is not `OPEN` all fail here with `ERR_INVALID_STATE` (HTTP 409).
5. **Referenced parent-state gates**: creating a slot under an agreement that is not `ACTIVE` yields `ERR_AGREEMENT_NOT_ACTIVE`; creating a booking on an excursion that is not `PUBLISHED` yields `ERR_EXCURSION_NOT_BOOKABLE`; assigning a car whose unit is `IN_MAINTENANCE` yields `ERR_STOCK_UNAVAILABLE`; any operation targeting an `OUT_OF_SERVICE` unit yields `ERR_STOCK_OUT_OF_SERVICE`.
6. **Optimistic concurrency**: `expected_excursion_version` on publish and `expected_manifest_version` on lock must equal the current versions — otherwise `ERR_STALE_VERSION`.
7. **Body referential integrity**: foreign keys carried in request bodies — `agreement_id`, `slot_id`, `stock_id`, `excursion_id`, `crew_member_id`, `redeemed_rain_check_id` — must resolve to existing resources, otherwise `ERR_INVALID_REFERENCE` (HTTP 422).
8. **Shape and constraint rules**, evaluated in this exact sub-order: (a) surge bounds by `event_type` (`ERR_SURGE_MULTIPLIER_INVALID`); (b) `class_code` versus `stock_type` compatibility (`ERR_CLASS_STOCK_MISMATCH`); (c) the unit not already on this excursion's consist and `position` unique within the excursion (`ERR_STOCK_ALREADY_ASSIGNED` for a duplicate unit, `ERR_VALIDATION` for a duplicate position); (d) crew `position` equal to the member's `role` (`ERR_POSITION_ROLE_MISMATCH`); (e) certification present for `ENGINEER` and `CONDUCTOR` at member creation (`ERR_CERTIFICATION_REQUIRED`); (f) party-size limits — a `DINING` party larger than 4 fails with `ERR_PARTY_TOO_LARGE_FOR_DINING`; (g) conditional-field shape — `dining_service` required exactly when the class is `DINING`, certification null for non-crew roles, capacity and table shape by `stock_type`, volunteers limited to `DOCENT` or `CAR_HOST` — all `ERR_VALIDATION`; (h) slot duration at least `min_slot_minutes` (`ERR_SLOT_DURATION_TOO_SHORT`); (i) consist completeness at publish (`ERR_CONSIST_INCOMPLETE`); (j) crew coverage at publish and boarding (`ERR_CREW_COVERAGE_INCOMPLETE`).
9. **Temporal rules**, in this exact sub-order: (a) slot `service_date` inside the agreement's validity window (`ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW`); (b) slot overlap on the same agreement and date (`ERR_SLOT_OVERLAP`); (c) the daily train cap (`ERR_DAILY_TRAIN_CAP_REACHED`); (d) the maintenance turnaround buffer and its mirror check at car-assign time (`ERR_MAINTENANCE_WINDOW_CONFLICT`); (e) maintenance windows or double-booked units colliding with committed excursions (`ERR_STOCK_COMMITTED`); (f) the same crew member committed to two excursions on one service date (`ERR_CREW_DATE_CONFLICT`); (g) an expired certification at crew-assignment time (`ERR_CERTIFICATION_EXPIRED`); (h) boarding gated to the service date (`ERR_NOT_SERVICE_DATE`).
10. **Money and capacity rules**, in this exact sub-order: (a) conservative class capacity (`ERR_CLASS_FULL`); (b) the dining table pool for the requested service (`ERR_DINING_SERVICE_FULL`); (c) rain-check validity (`ERR_RAIN_CHECK_INVALID`); (d) provisioning shortfall (`ERR_PROVISION_SHORTFALL`).

Beyond validation, the system maintains hierarchical consistency automatically: when a parent resource changes state in a way that strands its children — an agreement terminated, an excursion cancelled, a stock unit retired, a crew member deactivated — the server transitions the dependent resources itself, without waiting for a client to touch each one. Every such reconciliation is a real mutation of each affected resource: its `updated_at` refreshes and its `version` increments by 1.

## 3. Business Logic & Workflows

### 3.1. Track Rights and Operating Slots

Everything begins with the host railroad. A `Scheduler` records a track rights agreement by supplying the `host_railroad_name`, the `subdivision_code` the rights cover, a `valid_from` date, a `valid_until` date that must fall on or after `valid_from`, a `max_trains_per_day` cap of at least 1, and a `min_slot_minutes` floor of at least 30. A new agreement is born in `DRAFT` with `version` 1. Activation by a `Scheduler` moves it `DRAFT → ACTIVE`; an `OperationsManager` may instead terminate it, and termination is possible from either `DRAFT` or `ACTIVE`, landing in the terminal `TERMINATED` state. Agreement events accept an optional free-text `note`. Terminating an `ACTIVE` agreement is never a quiet bookkeeping act — §3.8 covers the cascade it unleashes.

Only an `ACTIVE` agreement can receive operating slots; an attempt under a `DRAFT` or `TERMINATED` agreement fails with `ERR_AGREEMENT_NOT_ACTIVE`. A `Scheduler` carves out a slot by supplying the `agreement_id`, a `service_date`, and the half-open window from `start_minute` to `end_minute`. Three timetable guards apply, in the temporal tier's order: the `service_date` must lie inside the agreement's validity window from `valid_from` through `valid_until` inclusive, otherwise `ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW`; the slot must not overlap any other non-`RELEASED` slot on the same agreement and date — with adjacency expressly allowed — otherwise `ERR_SLOT_OVERLAP`; and the creation must not push the count of slots in `OPEN`, `RESERVED`, or `CONSUMED` status on that date past the agreement's `max_trains_per_day`, otherwise `ERR_DAILY_TRAIN_CAP_REACHED`. The duration floor produces `ERR_SLOT_DURATION_TOO_SHORT` when the window is shorter than `min_slot_minutes`. A freshly created slot is `OPEN`.

A slot's life thereafter is driven by the excursion that holds it. Creating an excursion on a slot moves it `OPEN → RESERVED`. If that excursion is cancelled before it ever operates, the slot returns `RESERVED → OPEN`, rejoining the pool for the same agreement and date. If the train runs, the slot is consumed: `RESERVED → CONSUMED`. And if the underlying agreement is terminated, `OPEN` slots and `RESERVED` slots alike go to the terminal `RELEASED` state, while `CONSUMED` slots — history already written — are left untouched. Every one of these transitions increments the slot's `version`.

### 3.2. Rolling Stock, Maintenance Windows, and Retirement

The `Mechanic` owns the roster. Rostering a unit takes a `unit_code` that must be unique across all rolling stock (roster codes look like LOC-301 or CAR-DINING-2), a `stock_type` of `LOCOMOTIVE`, `COACH_CAR`, `FIRST_CLASS_CAR`, or `DINING_CAR`, a `seat_capacity`, and a `table_count`. The shape rules are strict: a locomotive seats nobody, so its `seat_capacity` must be 0, while every passenger car needs a positive `seat_capacity`; dining tables exist only on dining cars, so `table_count` must be positive for a `DINING_CAR` and 0 for everything else — each table seats up to 4 guests. Violations of these shape rules are `ERR_VALIDATION`. A new unit enters the roster `AVAILABLE`.

Maintenance is scheduled as work orders. A `Mechanic` creates one with a `stock_id`, a `window_start`, a `window_end` strictly after the start, and a `scope` of `INSPECTION`, `REPAIR`, or `OVERHAUL`; the order is born `SCHEDULED`. The referenced unit must exist (`ERR_INVALID_REFERENCE`) and must not already be `OUT_OF_SERVICE` (`ERR_STOCK_OUT_OF_SERVICE`). Two conflict guards protect the schedule, firing in the temporal tier's order: the new window must respect the 60-minute turnaround buffer against every other `SCHEDULED` or `IN_PROGRESS` work order on the same unit — a gap of at least 60 minutes is required, adjacency is not enough — otherwise `ERR_MAINTENANCE_WINDOW_CONFLICT`; and the window must not intersect the `service_date` of a `PUBLISHED` or `BOARDING` excursion whose consist already includes this unit, otherwise `ERR_STOCK_COMMITTED`.

Starting a work order — the `START` event by a `Mechanic` — requires the unit to be `AVAILABLE` and moves the order `SCHEDULED → IN_PROGRESS` while the unit itself flips `AVAILABLE → IN_MAINTENANCE`. Completing it — the `COMPLETE` event — moves the order `IN_PROGRESS → COMPLETED`, and the unit returns to `AVAILABLE` only if no other work order for it remains `IN_PROGRESS`; a unit with overlapping shop stays in the shop until its last open job finishes.

Retirement is the `RETIRE` event, also by a `Mechanic`, accepting an optional `reason`. A unit in `AVAILABLE` or `IN_MAINTENANCE` can be retired to the terminal `OUT_OF_SERVICE` state, but not while any of its work orders is `IN_PROGRESS`, and not while it sits on the consist of a `PUBLISHED` or `BOARDING` excursion — that last case is rejected as `ERR_STOCK_COMMITTED`. Retirement ripples outward: every `SCHEDULED` work order for the unit is cancelled (`SCHEDULED → CANCELLED`), and the unit's car assignments are stripped from any `DRAFT` excursions, with each affected excursion's `version` incrementing by 1. The unit's own `version` increments as well.

### 3.3. Assembling the Train: Excursions, Consists, and Crew

With a slot in hand, a `Scheduler` creates the excursion itself, supplying a `title`, the `slot_id`, an `event_type` of `REGULAR` or `HOLIDAY`, and the `surge_multiplier_bp` whose bounds §2.6 defines. The slot must be `OPEN` — anything else is `ERR_INVALID_STATE` — and creating the excursion reserves it (`OPEN → RESERVED`). The excursion copies its `service_date` from the slot, starts life in `DRAFT`, and is born with a companion: exactly one provisioning manifest per excursion, auto-created in `DRAFT` with zeroed counts, addressed through the excursion.

The consist is built car by car while the excursion remains `DRAFT` — consist edits on an excursion in any other state are `ERR_INVALID_STATE`. Each addition names the `excursion_id`, the `stock_id`, a `class_code`, and a `position` in train order that must be at least 1 and unique within the excursion. The `class_code` must agree with the unit's `stock_type`: a `LOCOMOTIVE` maps to `LOCO`, a `COACH_CAR` to `COACH`, a `FIRST_CLASS_CAR` to `FIRST_CLASS`, and a `DINING_CAR` to `DINING`, with any other pairing rejected as `ERR_CLASS_STOCK_MISMATCH`. The unit must be `AVAILABLE` — `IN_MAINTENANCE` yields `ERR_STOCK_UNAVAILABLE`, `OUT_OF_SERVICE` yields `ERR_STOCK_OUT_OF_SERVICE` — must not already appear in this excursion's consist (`ERR_STOCK_ALREADY_ASSIGNED`), must have no `SCHEDULED` or `IN_PROGRESS` work-order window intersecting the excursion's `service_date` (the mirror image of the work-order guard, likewise `ERR_MAINTENANCE_WINDOW_CONFLICT`), and must not already be assigned to a different excursion on the same `service_date` (`ERR_STOCK_COMMITTED`). At assignment time the unit's `seat_capacity` is snapshotted into the assignment's `effective_capacity`, insulating the excursion's sellable inventory from later roster edits. Every consist change — add or removal — increments the excursion's `version`.

Crewing runs on a parallel track under the `CrewManager`. Rostering a member takes a `name`, a `role` of `ENGINEER`, `CONDUCTOR`, `CAR_HOST`, `CHEF`, `SERVER`, or `DOCENT`, an `is_volunteer` flag, and a `cert_expires_on` date. Volunteers may hold only the `DOCENT` or `CAR_HOST` roles; anything else is `ERR_VALIDATION`. Engineers and conductors are certificate-holders: creating one without `cert_expires_on` is `ERR_CERTIFICATION_REQUIRED`, while for the other four roles the field must be null, again on pain of `ERR_VALIDATION`. Members are born `ACTIVE`. Deactivation (`ACTIVE → INACTIVE`) immediately releases every `ASSIGNED` crew assignment the member holds on excursions still in `DRAFT` or `PUBLISHED`, bumping each affected excursion's `version`; reactivation (`INACTIVE → ACTIVE`) restores the member to the pool but performs no automatic reassignment — staffing is rebuilt by hand.

Assigning crew to an excursion requires the excursion to be in `DRAFT` or `PUBLISHED` and the member to be `ACTIVE`. The assignment's `position` must equal the member's `role`, else `ERR_POSITION_ROLE_MISMATCH`. One person cannot be in two places at once: a member already `ASSIGNED` to another excursion sharing the same `service_date` triggers `ERR_CREW_DATE_CONFLICT`. For `ENGINEER` and `CONDUCTOR` positions, the member's `cert_expires_on` must fall on or after the excursion's `service_date`, else `ERR_CERTIFICATION_EXPIRED`. Each assignment is born `ASSIGNED` and its creation increments the excursion's `version`. Releasing an assignment moves it `ASSIGNED → RELEASED` and likewise bumps the excursion's `version`; when the train finally operates, every still-`ASSIGNED` assignment completes automatically (`ASSIGNED → COMPLETED`).

### 3.4. From Publication to Operation

Publication is the point of no return for planning, and it is guarded accordingly. A `Scheduler` publishes a `DRAFT` excursion — the request carries `expected_excursion_version` under the OCC rule of §2.8, and a stale number is rejected with `ERR_STALE_VERSION`. Two readiness gates follow. The consist must contain at least one assignment with `class_code` `LOCO` and at least one passenger-carrying car — `COACH`, `FIRST_CLASS`, or `DINING` — otherwise `ERR_CONSIST_INCOMPLETE`. Crew coverage must be satisfied by members currently `ASSIGNED`: at least one `ENGINEER`, at least one `CONDUCTOR`, and at least one `CAR_HOST`, and when the consist includes dining cars, at least one `CHEF` plus at least two `SERVER`s per dining car — a consist with two dining cars needs four servers. All thresholds are inclusive; falling one short fails coverage with `ERR_CREW_COVERAGE_INCOMPLETE`. Success moves the excursion `DRAFT → PUBLISHED`.

Boarding begins only on the day itself. A `Scheduler` issues the begin-boarding event, and the excursion moves `PUBLISHED → BOARDING` only when the logical clock's date equals the excursion's `service_date` — any other day is `ERR_NOT_SERVICE_DATE` — and only while crew coverage still holds, otherwise `ERR_CREW_COVERAGE_INCOMPLETE` again. Coverage is re-evaluated at boarding because releases and deactivations may have thinned the roster since publication.

Marking the train operated — `BOARDING → OPERATED`, the excursion's terminal success state — writes the day's outcomes in one sweep: the holding slot moves `RESERVED → CONSUMED`; bookings in `CHECKED_IN` become `COMPLETED`; bookings still merely `CONFIRMED`, their holders never having checked in, become `NO_SHOW` with no refund; and crew assignments still `ASSIGNED` become `COMPLETED`.

Reading an excursion surfaces its committed seat inventory through three computed fields: `coach_seats_available`, `first_class_seats_available`, and `dining_seats_available`. Each is the sum of `effective_capacity` over the consist's assignments of that class minus the party sizes of that class's bookings in `CONFIRMED` or `CHECKED_IN` status. `HELD` bookings are deliberately excluded from this read view — a shopper browsing the excursion sees seats that held bookings may still consume, which is why the stricter gate of §3.5 exists at sale time. The excursion collection supports optional `slot_id`, `status`, and `event_type` filters; the car-assignment collection filters by `excursion_id` and `stock_id`.

### 3.5. Selling Seats: Holds, Fares, and Dining Tables

A `StationAgent` sells against a `PUBLISHED` excursion — any other excursion state is `ERR_EXCURSION_NOT_BOOKABLE`. The booking payload carries the `excursion_id`, the `customer_email` that anchors the guest's identity for rain-check matching, a `class_code` of `COACH`, `FIRST_CLASS`, or `DINING` (`LOCO` is not sellable), a `party_size`, and — only for `DINING` — a `dining_service` of `EARLY` or `LATE`. Party size runs from 1 to 8, but a dining table seats four, so a `DINING` party above 4 is `ERR_PARTY_TOO_LARGE_FOR_DINING`. The `dining_service` field is required exactly when the class is `DINING` and forbidden otherwise; getting that conditional wrong is `ERR_VALIDATION`, as is any malformed body, missing required field, invalid enum value, or unknown `event_type`.

Before a hold is even written, the conservative capacity gate runs: the class's capacity — summed `effective_capacity` of the consist's assignments in that class — must cover not only the `CONFIRMED` and `CHECKED_IN` bookings but also every unexpired `HELD` booking of that class, plus the new party. If the party does not fit, the sale is rejected with `ERR_CLASS_FULL` — and because the read fields of §3.4 exclude holds, this gate can reject even while the excursion still shows open seats. A booking that passes is created in `HELD` with `expires_at` set 45 minutes out, per §2.5; a hold the guest never confirms is swept to `CANCELLED` with no refund when the clock passes it. On `HOLIDAY` excursions, creating the hold also recomputes the still-`DRAFT` manifest — holiday provisioning pre-counts unexpired `HELD` diners — and bumps the manifest's `version`.

Confirmation converts a hold into revenue. The confirm event, again by a `StationAgent`, requires the hold to be unexpired — the logical clock must sit before `expires_at` — and re-runs the same conservative capacity gate (`ERR_CLASS_FULL` on failure). The payload may carry a `redeemed_rain_check_id`; when present, the rain-check must be `ISSUED`, its `customer_email` must match the booking's, and the clock date must be on or before its `expires_on`, with any failure rejected as `ERR_RAIN_CHECK_INVALID`. For `DINING` bookings, confirmation also requires a free table in the requested service, with an empty pool rejected as `ERR_DINING_SERVICE_FULL`.

Pricing follows the fare rule of §2.6 exactly. The `unit_fare_cents` is the class base fare scaled by the excursion's `surge_multiplier_bp`, rounded half-up to whole cents; the `total_price_cents` is that unit fare multiplied by `party_size`. With no rain-check, `paid_cents` equals the total. With a valid rain-check, `paid_cents` is the total minus the rain-check's `value_cents`, floored at zero — and the rain-check is consumed in full even when its value exceeds the new booking's total; no change is given. The redeemed rain-check flips `ISSUED → REDEEMED` with its `redeemed_booking_id` pointing at the booking that consumed it.

Dining seating is assigned by a deterministic selector at confirm time. Consider every consist assignment with `class_code` `DINING`, taken in ascending `position` order; each car offers tables numbered 1 through its `table_count`. A table is free for the requested `dining_service` when no `CONFIRMED` or `CHECKED_IN` booking of this excursion already holds that table in that car for the same service, and when the car's per-service seated load — the party sizes of its `CONFIRMED` and `CHECKED_IN` diners in that service — plus this party stays within the car's `effective_capacity`. The selector walks cars by ascending `position` and tables by ascending number, taking the first free table; because position and table number form a total order over distinct tables, no tie-break is ever needed. If the pool is empty, confirmation fails with `ERR_DINING_SERVICE_FULL`. On success the booking records `dining_table_number` and the chosen car in `dining_car_assignment_id`; both stay null for non-dining bookings.

After any confirm, the excursion's availability fields are recomputed, and the excursion's still-`DRAFT` manifest recomputes its galley numbers with its `version` incrementing; the booking's own `version` increments as well. The booking collection supports optional `excursion_id`, `customer_email`, `status`, and `dining_car_assignment_id` filters.

### 3.6. Cancellations, Refunds, and Rain-Checks

A guest who cancels a mere hold loses nothing: `HELD → CANCELLED` issues no refund, since nothing was ever paid. Cancelling a `CONFIRMED` booking is where money moves. The refund hangs off the 48-hour rule: take the slot's start instant — the `service_date` at midnight UTC plus `start_minute` minutes — and compare it to the logical clock at cancellation time. Cancel at least 48 hours before slot start and `refund_cents` is the full `paid_cents`; the boundary is inclusive, so a cancellation exactly 48 hours and zero seconds before departure still refunds in full. Cancel inside that window and `refund_cents` is half of `paid_cents`, rounded half-up to a whole cent. Bookings cancelled from any other path — swept holds, no-shows, rain-checked passengers — carry `refund_cents` of 0. A cancelled `DINING` booking also frees its table, clearing `dining_table_number` and `dining_car_assignment_id` so the selector can hand the seats to someone else. Either cancel path recomputes the excursion's availability and the still-`DRAFT` manifest (bumping its `version`), and increments the booking's `version`.

Check-in is the `StationAgent`'s day-of action: `CONFIRMED → CHECKED_IN`, permitted only while the excursion is `BOARDING` — attempting it against any other excursion state is `ERR_INVALID_STATE`. From there the train's operation decides the rest, as §3.4 describes: checked-in guests complete, and confirmed-but-absent guests become no-shows with no refund.

Rain-checks exist only because excursions die. When an excursion is cancelled from `PUBLISHED` or `BOARDING`, every `CONFIRMED` or `CHECKED_IN` booking becomes `RAIN_CHECKED`, and the system issues one rain-check per such booking: its `booking_id` points at the source booking, its `customer_email` is copied across, its `value_cents` equals the source booking's `paid_cents`, its `reason` — one of `WEATHER`, `EVENT`, or `TRACK_RIGHTS_LOST` — is copied from the excursion's `cancel_reason`, its `issued_on` is the logical clock's date, and its `expires_on` is 365 days later, redeemable through that date inclusive as §2.5 states. `redeemed_booking_id` stays null until a future confirmation consumes it. Beyond redemption, the only other exit is the clock sweep to `EXPIRED`. The rain-check collection filters by `booking_id`, `redeemed_booking_id`, `customer_email`, and `status`.

An excursion's `cancel_reason` stays null for its whole life until the moment it is cancelled; cancelling the excursion is an `OperationsManager` act, carrying a `cancel_reason` of `WEATHER`, `EVENT`, or `OPERATOR`. From `DRAFT`, the cancellation releases the slot back to `OPEN`, sweeps `HELD` bookings to `CANCELLED` without refunds, releases `ASSIGNED` crew to `RELEASED`, and lets a still-`DRAFT` manifest recompute its now-shrinking counts while a `LOCKED` manifest stands untouched. From `PUBLISHED` or `BOARDING`, all of that happens plus the rain-check issuance above — and yes, a weather stop called mid-boarding still issues rain-checks to guests already checked in. Every booking's excursion-side cascade bumps the booking's `version`, and the excursion's `version` increments as well.

### 3.7. Provisioning the Galley

The `CateringManager` works from the provisioning manifest that every excursion carries from birth — exactly one per excursion, created `DRAFT` with zeroed counts and reachable through the excursion. Two diner counts sit on the manifest: `early_diner_count`, the summed `party_size` of `DINING` bookings in the `EARLY` service, and `late_diner_count`, the same for `LATE`. From these the galley load is derived: each service's diner count is multiplied by 3 units per meal and padded by a 10 percent buffer, the result is rounded up to a whole number of units **per service**, and the two per-service ceilings are then summed into `galley_load_units`. The rounding order is pinned — ceiling first, then sum — because summing first and taking one ceiling can yield a different integer.

Which bookings count depends on the excursion's `event_type`. On `REGULAR` excursions the counts are net: only `CONFIRMED` and `CHECKED_IN` diners are included. On `HOLIDAY` excursions the kitchen preps conservatively: unexpired `HELD` dining bookings are included as well, so identical booking data yields a larger load on a holiday train. The manifest recomputes on every booking create, confirm, cancel, and rain-check cascade — but only while it is `DRAFT`. Locking freezes the numbers: the lock event requires `expected_manifest_version` per §2.8, rejects a stale value with `ERR_STALE_VERSION`, stamps `locked_at` with the logical clock's timestamp — `locked_at` stays null while the manifest is `DRAFT` — and moves the manifest `DRAFT → LOCKED`; later booking changes no longer recompute a `LOCKED` manifest. Finally, marking the manifest provisioned requires the `actual_loaded_units` delivered to the platform to be at least `galley_load_units` — a shortfall is `ERR_PROVISION_SHORTFALL` — stores the figure, which remains unset until this moment, and moves the manifest to its terminal `PROVISIONED` state.

### 3.8. Losing the Railroad: The Termination Cascade

The deepest cascade in the system begins when an `OperationsManager` terminates a track rights agreement, from either `DRAFT` or `ACTIVE`, into the terminal `TERMINATED` state. Every `OPEN` slot under the agreement goes straight to `RELEASED`. Every `RESERVED` slot also goes to `RELEASED`, and the excursion holding it — whether still `DRAFT`, already `PUBLISHED`, or mid-`BOARDING` — is cancelled with `cancel_reason` `TRACK_RIGHTS_LOST`. That cancellation is the full §3.6 cascade with the reason pinned: `HELD` bookings cancel without refund, `CONFIRMED` and `CHECKED_IN` bookings become `RAIN_CHECKED` with a rain-check of reason `TRACK_RIGHTS_LOST` issued for each, `ASSIGNED` crew are released, and a `DRAFT` manifest recomputes while a `LOCKED` one is left alone. Slots already `CONSUMED` — trains that ran — are untouched by the termination. The agreement's `version` increments by 1, as does every resource the cascade mutates along the way.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all event transitions — return `200 OK`. Request and response bodies for each endpoint are as described in the workflow narratives of §3; this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/railroad/agreements` | Create a track rights agreement (DRAFT) | Scheduler |
| GET | `/railroad/agreements/{id}` | Get one agreement | Any |
| POST | `/railroad/agreements/{id}/events` | ACTIVATE (Scheduler) or TERMINATE (OperationsManager); termination cascades to slots, excursions, bookings, and crew | Scheduler, OperationsManager |
| GET | `/railroad/agreements/{id}/slots` | List slots of an agreement | Any |
| POST | `/railroad/slots` | Create an operating slot (OPEN) under an ACTIVE agreement | Scheduler |
| GET | `/railroad/slots/{id}` | Get one slot | Any |
| POST | `/railroad/rolling-stock` | Roster a locomotive or car (AVAILABLE) | Mechanic |
| GET | `/railroad/rolling-stock/{id}` | Get one stock unit | Any |
| POST | `/railroad/rolling-stock/{id}/events` | RETIRE a unit to OUT_OF_SERVICE, cancelling scheduled work and stripping DRAFT consists | Mechanic |
| GET | `/railroad/rolling-stock/{id}/work-orders` | List work orders of a stock unit | Any |
| POST | `/railroad/work-orders` | Schedule a maintenance window (SCHEDULED) | Mechanic |
| POST | `/railroad/work-orders/{id}/events` | START (unit to IN_MAINTENANCE) or COMPLETE (unit back to AVAILABLE if clear) | Mechanic |
| POST | `/railroad/excursions` | Create an excursion (DRAFT) on an OPEN slot; reserves the slot and auto-creates the DRAFT manifest | Scheduler |
| GET | `/railroad/excursions/{id}` | Get one excursion including committed availability fields | Any |
| GET | `/railroad/excursions` | List excursions with optional filters | Any |
| POST | `/railroad/excursions/{id}/events` | PUBLISH (Scheduler, OCC), BEGIN_BOARDING (Scheduler, service-date gated), MARK_OPERATED (Scheduler), CANCEL (OperationsManager, with cancel_reason) | Scheduler, OperationsManager |
| GET | `/railroad/excursions/{id}/provisioning-manifests` | Get the excursion's manifest (array of 0–1) | Any |
| POST | `/railroad/car-assignments` | Add a car or locomotive to a DRAFT excursion's consist; snapshots effective_capacity | Scheduler |
| GET | `/railroad/car-assignments/{id}` | Get one car assignment | Any |
| GET | `/railroad/car-assignments` | List car assignments with optional filters | Any |
| POST | `/railroad/bookings` | Create a booking (HELD, 45-minute expiry) on a PUBLISHED excursion; conservative capacity gate | StationAgent |
| GET | `/railroad/bookings/{id}` | Get one booking | Any |
| GET | `/railroad/bookings` | List bookings with optional filters | Any |
| POST | `/railroad/bookings/{id}/events` | CONFIRM (fare quote, optional rain-check redemption, dining table selector), CANCEL (48-hour refund rule), CHECK_IN (excursion BOARDING) | StationAgent |
| POST | `/railroad/crew-members` | Roster a crew member or volunteer (ACTIVE) | CrewManager |
| GET | `/railroad/crew-members/{id}` | Get one crew member | Any |
| POST | `/railroad/crew-members/{id}/events` | DEACTIVATE (releases ASSIGNED assignments on DRAFT/PUBLISHED excursions) or REACTIVATE | CrewManager |
| POST | `/railroad/crew-assignments` | Assign an ACTIVE crew member to an excursion in DRAFT or PUBLISHED | CrewManager |
| GET | `/railroad/crew-assignments/{id}` | Get one crew assignment | Any |
| GET | `/railroad/crew-assignments` | List crew assignments with optional filters | Any |
| POST | `/railroad/crew-assignments/{id}/events` | RELEASE an assignment | CrewManager |
| GET | `/railroad/manifests/{id}` | Get one provisioning manifest | Any |
| POST | `/railroad/manifests/{id}/events` | LOCK (OCC; freezes counts) or MARK_PROVISIONED (loaded units must cover the galley load) | CateringManager |
| GET | `/railroad/rain-checks/{id}` | Get one rain-check | Any |
| GET | `/railroad/rain-checks` | List rain-checks with optional filters | Any |
| POST | `/railroad/_clock/set_current_utc` | Advance the test-driving logical clock and run the expiry sweep | OperationsManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 where they arise.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SLOT_OUTSIDE_AGREEMENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_SLOT_DURATION_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_DAILY_TRAIN_CAP_REACHED` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_STOCK_COMMITTED` | 409 Conflict |
| `ERR_STOCK_UNAVAILABLE` | 409 Conflict |
| `ERR_STOCK_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_CLASS_STOCK_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STOCK_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_SURGE_MULTIPLIER_INVALID` | 422 Unprocessable Entity |
| `ERR_CONSIST_INCOMPLETE` | 409 Conflict |
| `ERR_CREW_COVERAGE_INCOMPLETE` | 409 Conflict |
| `ERR_POSITION_ROLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CREW_DATE_CONFLICT` | 409 Conflict |
| `ERR_EXCURSION_NOT_BOOKABLE` | 409 Conflict |
| `ERR_CLASS_FULL` | 409 Conflict |
| `ERR_DINING_SERVICE_FULL` | 409 Conflict |
| `ERR_PARTY_TOO_LARGE_FOR_DINING` | 422 Unprocessable Entity |
| `ERR_RAIN_CHECK_INVALID` | 422 Unprocessable Entity |
| `ERR_NOT_SERVICE_DATE` | 409 Conflict |
| `ERR_PROVISION_SHORTFALL` | 409 Conflict |
