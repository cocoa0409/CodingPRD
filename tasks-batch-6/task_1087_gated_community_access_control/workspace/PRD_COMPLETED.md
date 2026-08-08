# Gated-Community Access Control API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Gated-Community Access Control API, a back-office platform that unifies the many overlapping concerns of a modern gated residential community or homeowners' association. A single community must simultaneously keep an accurate resident directory and callbox, register the vehicles and windshield decals that authorize automatic gate passage, issue guest and vendor passes with pre-authorized visiting windows, record every license-plate read the gatehouse cameras produce, schedule patrol shifts and log the incidents patrols uncover, let residents reserve shared amenities such as pools and clubhouses, and cite, adjudicate, and collect on rule violations and their fines. These concerns are not independent: a delinquent fine balance can suspend a resident, and suspension in turn cancels that resident's amenity bookings and revokes their outstanding guest passes; a vehicle being retired cascades into revoking its decal, which in turn changes what the gate will allow.

The platform is built around a small number of peer entities linked by foreign keys, all mounted directly under the `/access` base path. Time is central to almost every rule — pass and decal validity windows, reservation windows, patrol buffers, fine repeat windows, and gate-event timestamps are all evaluated against a server-controlled logical clock rather than wall-clock time, so that automated test scenarios are perfectly reproducible. The remainder of this document defines the global contracts every endpoint honors (Section 2) and then the business workflows in detail (Section 3), followed by the endpoint and error-code reference tables (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation — or a resident attempts to act on another resident's resource — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `CommunityAdmin`, `SecurityOfficer`, and `Resident`.

When `X-User-Role` is `CommunityAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `issued_by_user_id` on a `Violation` the admin issues) but never compares it to any entity's `id`. When `X-User-Role` is `SecurityOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it (again, as `issued_by_user_id` on an issued `Violation`) but does not compare it to any entity's `id`. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks on any resource that references a resident compare that resource's foreign-key field — `resident_id` on a vehicle, reservation, or violation, or `sponsor_resident_id` on a pass — to `X-User-ID`. A resident acting on a resource whose owning resident is not themselves is refused with `ERR_UNAUTHORIZED`.

Note that the `officer_id` recorded on a patrol is an opaque scheduling label, not a user identity; it is never compared against `X-User-ID` for access control.

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

Every list endpoint accepts two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter names how many items to skip from the start of the result set; when omitted it defaults to 0. A `limit` or `offset` outside its permitted range is a malformed request and is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` reflects the full number of matching resources before the page window is applied and `has_more` indicates whether any matching resources remain beyond the current page.

### 2.4. The Logical Clock and Temporal Evaluation

The system does not read wall-clock time for any business rule. Instead it maintains a single server-wide logical clock. At startup, and before any client sets it, the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to real time. A `CommunityAdmin` may advance or reset the clock to a supplied `to_iso8601` instant, and every subsequent window check, expiry evaluation, fee computation, and system timestamp uses the clock's current value. Field values that record "when something happened" — a resident's `issued_at` on a violation, `entry_at` and `exit_at` on a pass, `checkin_at` and `checkout_at` on a reservation, `event_at` on a gate event, and the standard `created_at` and `updated_at` audit fields — are all stamped from this logical clock, never from the host machine's time.

### 2.5. Common Resource Properties and Append-Only Logs

Most resources — `Community`, `Resident`, `Vehicle`, `Decal`, `Pass`, `Amenity`, `AmenityReservation`, `Patrol`, `Incident`, and `Violation` — carry a common set of system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits set at creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and an integer `version` that begins at 1 and increments by one on each mutation of the resource. Any operation that changes a resource's stored state — including server-driven recomputations such as a resident's balance and standing — refreshes `updated_at` and increments `version`.

The `GateEvent` resource is the sole exception: it is an append-only log entry and carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because a recorded gate read is never modified after it is written.

### 2.6. Optimistic Concurrency Control on Decal Issuance

Issuing a decal is the one write in this system guarded by optimistic concurrency control, because a newly issued decal legitimately supersedes the vehicle's prior active decal and the product allows a vehicle to be re-decaled over time. A decal-issuance request must carry `expected_vehicle_version`, a required (non-optional) field whose value is the `version` of the target `Vehicle` the client last observed. When the server processes the request, it compares `expected_vehicle_version` against the vehicle's current `version`. If another writer has already issued a decal for that vehicle — which supersedes the old decal and increments the vehicle's `version` — then a request built from the earlier view carries a stale value that no longer matches, and it is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from issuing a decal against a vehicle state it has not actually observed. No other endpoint accepts or requires a version field.

### 2.7. Monetary Precision and Rounding

All money in the system is represented as an integer number of cents; there are no fractional-cent values in stored fields or responses. Where a rule multiplies a base amount by a decimal factor — a violation's tier multiplier or its late-fee percentage — the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway rounds up) before any subsequent addition or cap is applied. Where a rule converts a span of time into a number of billable hours, any fractional hour is rounded up to the next whole hour (ceiling) before it is multiplied by an hourly rate. These two rounding disciplines are distinct and are applied exactly where the workflow narratives in Section 3 specify.

### 2.8. Cascading State Consistency

State changes in this system frequently propagate across entities, and each propagation is immediate and complete. Three cascade families exist.

First, the **delinquency cascade**: when a resident's outstanding balance rises to or above the delinquency threshold while the resident is `ACTIVE`, the resident is automatically driven from `ACTIVE` to `SUSPENDED`. That suspension itself has two secondary effects — every one of the resident's amenity reservations still in `BOOKED` or `CHECKED_IN` is moved to `CANCELLED`, releasing its `party_size` from the amenity's concurrent load; and every one of the resident's passes that is currently `APPROVED` with presence `OFFSITE` has its `auth_status` set to `REVOKED`.

Second, the **move-out cascade**: when a resident is moved to `MOVED_OUT`, each of the resident's vehicles that is `ACTIVE` is set to `INACTIVE`, and each such vehicle transitioning to `INACTIVE` in turn revokes that vehicle's own `ACTIVE` decal to `REVOKED`. The same two-hop vehicle-then-decal cascade fires whether the resident moves out from `ACTIVE` or from `SUSPENDED`.

Third, the **supersede/retire cascade** around decals: issuing a new decal for a vehicle revokes that vehicle's prior `ACTIVE` decal, and manually transitioning a vehicle to `INACTIVE` revokes its `ACTIVE` decal as well.

Every entity that a cascade mutates has its `updated_at` refreshed and its `version` incremented, exactly as a direct client mutation would.

### 2.9. Left-to-Right Existence Validation

Requests that name resources by identifier — whether a path parameter such as a resident or violation id, or a foreign key inside a request body — are validated for existence in left-to-right order, with path identifiers resolved before body references. The first identifier that does not resolve to an existing resource causes the request to be rejected with that resource's specific not-found error (for example, `ERR_COMMUNITY_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_DECAL_NOT_FOUND`, `ERR_PASS_NOT_FOUND`, `ERR_AMENITY_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_PATROL_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, or `ERR_GATE_EVENT_NOT_FOUND`), before any business rule is evaluated.

### 2.10. Validation Ordering

When several conditions could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: absent or unknown-role headers yield `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the operation, or a resident reaching for another resident's resource, yields `ERR_UNAUTHORIZED`. Existence is checked third, per Section 2.9. Basic body well-formedness — missing required fields, unknown enum values, out-of-range numbers — surfaces as `ERR_VALIDATION`. After those universal checks, operation-specific rules apply in this order: segregation of duties on violation resolution (`ERR_SEGREGATION_OF_DUTIES`); the decal optimistic-concurrency check (`ERR_STALE_VERSION`); whether the target resource's current state permits the requested transition (`ERR_INVALID_STATE`); cross-entity eligibility gates (`ERR_SPONSOR_NOT_ELIGIBLE`, `ERR_VEHICLE_INACTIVE`, `ERR_RESIDENT_NOT_ELIGIBLE`); temporal window and overlap gates (`ERR_PASS_WINDOW_INVALID`, `ERR_RESERVATION_WINDOW_INVALID`, `ERR_PATROL_OVERLAP`); amenity capacity (`ERR_AMENITY_AT_CAPACITY`); and finally the remaining domain guards (`ERR_AMENITY_NOT_RESERVABLE`, `ERR_INVALID_RESOLUTION`). Each Section 3 workflow restates the checks that apply to it and the order in which they fire.

## 3. Business Logic & Workflows

### 3.1. Communities, Residents, the Directory, and Callbox

A `CommunityAdmin` establishes a community by supplying its `name` and, optionally, a `timezone` given as an IANA label; when the timezone is omitted it defaults to `UTC`. The community is the top-level container that residents, amenities, gate events, patrols, incidents, and violations all reference by `community_id`.

Residents are registered by a `CommunityAdmin`. Registration takes the `community_id`, the resident's `full_name`, `email`, and `resident_type` (either `OWNER` or `TENANT`), and optionally a `phone`, a `unit_label`, a `lot_number`, and a `directory_listed` flag; `phone`, `unit_label`, and `lot_number` default to null and `directory_listed` defaults to true. On creation the resident's `status` is `ACTIVE`, `standing` is `GOOD`, and `outstanding_balance_cents` is zero, and the system mints a numeric `callbox_code` used to dial the unit from the gate callbox. The `directory_listed` flag governs whether the resident appears in the community directory and callbox listing, and the resident directory can be listed and filtered by `community_id`, `standing`, `status`, and `directory_listed`.

A resident's `status` moves through a small cycle, driven by a transition request naming the desired `to_status`. A `CommunityAdmin` may suspend an `ACTIVE` resident (`to_status` of `SUSPENDED`), reinstate a `SUSPENDED` resident to `ACTIVE`, or move an `ACTIVE` or `SUSPENDED` resident out to the terminal `MOVED_OUT`. The same `to_status` field names the target state on every other transition endpoint in the system — for vehicles, decals, reservations, patrols, and incidents alike. Suspension also happens automatically as the second hop of the delinquency cascade described below. Reinstating a suspended resident is only permitted when their `outstanding_balance_cents` is strictly below the delinquency threshold; an attempt to reinstate a resident whose balance is at or above that threshold is refused with `ERR_RESIDENT_NOT_ELIGIBLE`. Suspension carries the two secondary effects of Section 2.8 — cancelling the resident's `BOOKED`/`CHECKED_IN` reservations and revoking their `APPROVED`/`OFFSITE` passes — and moving a resident out triggers the vehicle-then-decal cascade.

A resident's financial position is fully derived, never directly written. The `outstanding_balance_cents` is the sum of `assessed_fine_cents` across the resident's violations whose `status` is `ISSUED`, `APPEALED`, `UPHELD`, or `REDUCED`, minus the sum of `paid_amount_cents` across the resident's violations whose `status` is `PAID`. The resident's `standing` is `DELINQUENT` when `outstanding_balance_cents` is greater than or equal to the delinquency threshold of 25,000 cents, and `GOOD` otherwise — the boundary is inclusive, so a balance of exactly 25,000 cents is `DELINQUENT`. Whenever the balance changes and this evaluation flips a resident's standing from `GOOD` to `DELINQUENT` while the resident is `ACTIVE`, the delinquency cascade fires and the resident is auto-suspended to `SUSPENDED`.

### 3.2. Vehicles and Decals

A resident's vehicles are registered either by the resident themselves (acting on their own `resident_id`) or by a `CommunityAdmin`. A vehicle carries the owning `resident_id`, a `plate`, a `plate_state`, and optional `make`, `model`, and `color` (each defaulting to null). A new vehicle's `status` is `ACTIVE`. A `CommunityAdmin` may later flip a vehicle between `ACTIVE` and `INACTIVE`; driving a vehicle to `INACTIVE` revokes its `ACTIVE` decal, if any. Vehicles can be listed and filtered by `resident_id` and `status`.

Decals are the windshield credentials that let the gate recognize a resident vehicle automatically. A `CommunityAdmin` or `SecurityOfficer` issues a decal against a vehicle by supplying the `vehicle_id`, a `tier` (`RESIDENT`, `TENANT`, or `TEMPORARY`), the inclusive `valid_from` and exclusive `valid_until` datetimes bounding the decal's validity window, and the `expected_vehicle_version` required for the optimistic-concurrency check of Section 2.6. Issuance requires the target vehicle to be `ACTIVE`; issuing against an `INACTIVE` vehicle is refused with `ERR_VEHICLE_INACTIVE`. On success the system mints a `decal_number`, sets the decal's `status` to `ACTIVE`, revokes the vehicle's prior `ACTIVE` decal (if one exists) to `REVOKED` as a supersede, and increments the vehicle's `version` by one. Decals can be listed and filtered by `vehicle_id` and `status`.

A decal's `status` can also be moved to `REVOKED` directly by a `CommunityAdmin` or `SecurityOfficer`, or reach `REVOKED` through the vehicle-inactivation and move-out cascades. Separately, a decal is treated as `EXPIRED` when it is evaluated at gate-match time and the gate event's `event_at` is at or after the decal's `valid_until`; an expired decal no longer matches at the gate. Both `REVOKED` and `EXPIRED` are terminal.

### 3.3. Guest and Vendor Passes: The Authorization Axis

A pass pre-authorizes a visitor to enter the community during a planned window. A resident (sponsoring their own `sponsor_resident_id`) or a `CommunityAdmin` creates a pass by supplying the `sponsor_resident_id`, the `pass_type` (`GUEST` or `VENDOR`), the `visitor_name`, the `visitor_plate` that the gate cameras will match, the inclusive `valid_from` and exclusive `valid_until` window bounds, and optionally the visitor's `plate_state` and, for vendor visits, a `vendor_company` (both defaulting to null). A pass carries two independent status axes. The authorization axis, `auth_status`, begins at `PENDING`. The presence axis, `presence_status`, begins at `OFFSITE` and is driven entirely by gate events (Section 3.4). Passes can be listed and filtered by `sponsor_resident_id`, `auth_status`, and `presence_status`.

A `SecurityOfficer` or `CommunityAdmin` authorizes a pending pass by supplying a `decision`. A `decision` of `DENIED` moves `auth_status` from `PENDING` to `DENIED`, a terminal state, with no further effect. A `decision` of `APPROVED` moves `auth_status` from `PENDING` to `APPROVED`, but only after two gates pass: the sponsoring resident must be `ACTIVE` with `standing` of `GOOD`, failing which the request is refused with `ERR_SPONSOR_NOT_ELIGIBLE`; and the pass window must be well-formed and not already past — that is, `valid_from` must be strictly before `valid_until`, and `valid_until` must be strictly after the current clock — failing which the request is refused with `ERR_PASS_WINDOW_INVALID`. On approval the system computes the provisional `estimated_fee_cents` from the planned window: the hourly rate is 500 cents per hour for a `VENDOR` pass and 0 cents per hour for a `GUEST` pass; the planned span from `valid_from` to `valid_until` is converted to hours and rounded up to the next whole hour; and `estimated_fee_cents` is that whole-hour count multiplied by the rate.

An `APPROVED` pass may be revoked by a `SecurityOfficer` or `CommunityAdmin`, moving `auth_status` to the terminal `REVOKED`; the delinquency cascade can also revoke an `APPROVED`/`OFFSITE` pass when its sponsor is suspended. Independently, an `APPROVED` pass is treated as `EXPIRED` when evaluated at gate-match time with the event's instant at or after `valid_until`. The final fee, `final_fee_cents`, is not computed here; it is computed at gate exit as described next, and both `estimated_fee_cents` and `final_fee_cents` are null until their respective computations occur.

### 3.4. Gate Events, License-Plate Recognition, and the Presence Axis

Only a `SecurityOfficer` records gate events, which represent a license-plate-recognition (LPR) camera read at a lane. A gate event is submitted with the `community_id`, the `gate_id`, a `direction` of `ENTRY` or `EXIT`, the `plate_read` string, and optionally the `plate_state` the camera resolved. The server then matches the read against credentials and records the outcome on the event: `matched_type` is `DECAL`, `PASS`, or `UNMATCHED`; `matched_id` is the id of the matched decal or pass (per `matched_type`) or null when unmatched; `decision` is `ALLOW` or `DENY`; `reason` is a human-readable decision reason code; and `event_at` is stamped from the logical clock. Because a gate event is an append-only record, it exposes only `id` and `created_at` beyond these read fields, and it can be listed and filtered by `community_id`, `direction`, `decision`, and `matched_type`.

Matching proceeds as follows. The read is first checked against resident decals: a decal matches when the read equals the plate of the decal's vehicle, the decal's `status` is `ACTIVE`, and the event's `event_at` falls within the decal's window — at or after `valid_from` and before `valid_until`. A decal whose `event_at` is at or after its `valid_until` is expired and does not match. Failing a decal match, the read is checked against passes by `visitor_plate`, where a pass matches when its `auth_status` is `APPROVED` and the event's instant falls at or after `valid_from` and before `valid_until`. A successful decal or pass match yields `decision` of `ALLOW`; a read that matches no valid credential yields `matched_type` of `UNMATCHED` and `decision` of `DENY`. Whenever the matcher encounters a plate-matched `ACTIVE` decal or `APPROVED` pass whose `event_at` is at or after its `valid_until`, it persists that expiry — setting the decal's `status` (or the pass's `auth_status`) to `EXPIRED` and incrementing that credential's `version` — before continuing; such a credential does not match. A denied read is not an error condition: recording the gate event still succeeds with a created (`201`) response carrying `decision` of `DENY`. The `ERR_GATE_ACCESS_DENIED` code is reserved for a future explicit gate-decision error surface and is not raised by the gate-event workflow.

Gate events also drive the pass presence axis. When an `ENTRY` event matches an `APPROVED` pass whose presence is `OFFSITE` and whose window contains the event instant (`valid_from` at or before `event_at`, and `event_at` before `valid_until`), the pass's `presence_status` advances from `OFFSITE` to `ONSITE` and its `entry_at` is set to `event_at`; if the instant is outside the window, the event's decision is `DENY` and presence is unchanged. An `EXIT` event's barrier fields (`matched_type`, `matched_id`, `decision`, `reason`) are produced by the same in-window matcher used for entries, so an `EXIT` recorded at or after the pass's `valid_until` reads `matched_type` of `UNMATCHED` and `decision` of `DENY` (and flips that late `APPROVED` pass to `EXPIRED` as above) even though a departure still occurs. The presence departure is driven independently of the barrier decision and of the window: when an `EXIT` event's `plate_read` matches the `visitor_plate` of a pass whose presence is `ONSITE` — regardless of whether the event instant still falls within that pass's window — the pass advances from `ONSITE` to `DEPARTED`, its `exit_at` is set to `event_at`, and the system computes `final_fee_cents`. The final fee uses the same per-hour rate as the estimate (500 cents for `VENDOR`, 0 for `GUEST`). Billable hours are the span from `entry_at` up to the earlier of `exit_at` and `valid_until`, converted to hours and rounded up to the next whole hour (and never negative). Overstay hours are the span by which `exit_at` exceeds `valid_until`, taken as zero when the exit is not past the window, converted to hours and rounded up to the next whole hour. The `final_fee_cents` is the billable hours multiplied by the rate, plus the overstay hours multiplied by the overstay surcharge of 2,000 cents per hour.

### 3.5. Amenities and Reservations

A `CommunityAdmin` configures an amenity with its `community_id`, `name`, `amenity_type` (`POOL`, `GYM`, `CLUBHOUSE`, or `TENNIS`), an integer `capacity` of at least 1, an `hourly_fee_cents` of at least 0, a refundable `deposit_cents` of at least 0, an `open_hour` in the range 0 through 23, a `close_hour` in the range 1 through 24 (exclusive of the closing hour itself), and a `reservable` flag that defaults to true. Amenities can be listed and filtered by `community_id` and `amenity_type`.

A resident (on their own `resident_id`) or a `CommunityAdmin` books a reservation by supplying the `amenity_id`, the `resident_id`, the inclusive `start_at` and exclusive `end_at` window bounds, and the `party_size` of at least 1 occupants counted against capacity. Booking is refused with `ERR_AMENITY_NOT_RESERVABLE` when the amenity's `reservable` flag is false, and refused with `ERR_RESIDENT_NOT_ELIGIBLE` when the booking resident is not `ACTIVE` with `GOOD` standing. Capacity is enforced as a concurrent-overlap constraint: two reservation windows overlap when the first starts strictly before the second ends and the second starts strictly before the first ends, so windows that merely touch end-to-start do not overlap. The committed load on an amenity at any instant is the sum of `party_size` over that amenity's reservations in `BOOKED` or `CHECKED_IN` status whose windows contain the instant; a booking is refused with `ERR_AMENITY_AT_CAPACITY` when, at the busiest overlapping instant, the existing load plus the new `party_size` would exceed the amenity's `capacity`. These three booking gates fire in the §2.10 order — eligibility (`ERR_RESIDENT_NOT_ELIGIBLE`) first, then capacity (`ERR_AMENITY_AT_CAPACITY`), then reservability (`ERR_AMENITY_NOT_RESERVABLE`); booking itself performs no temporal-window or open-hour/close-hour validation, and `ERR_RESERVATION_WINDOW_INVALID` never arises at booking — that window check is deferred to check-in. A successful booking sets `status` to `BOOKED`, commits the `party_size` to the amenity's load, and computes the provisional `quoted_fee_cents`: the planned span from `start_at` to `end_at` is converted to hours and rounded up to the next whole hour, multiplied by `hourly_fee_cents`, and then the `deposit_cents` is added as a held (not yet charged) deposit. Reservations can be listed and filtered by `amenity_id`, `resident_id`, and `status`.

A reservation moves through its lifecycle by transition. A resident checks in a `BOOKED` reservation, advancing it to `CHECKED_IN`, only when the current clock is at or after `start_at` and strictly before `end_at` — otherwise the check-in is refused with `ERR_RESERVATION_WINDOW_INVALID` — and only when the concurrent committed load including this party does not exceed capacity, the same capacity gate re-applied at check-in and again yielding `ERR_AMENITY_AT_CAPACITY` on breach. Check-in sets `checkin_at` to the current clock. A resident completes a `CHECKED_IN` reservation, advancing it to `COMPLETED`: this sets `checkout_at` to the current clock, releases the `party_size` from the amenity load, and computes the final `settled_fee_cents`. The settled fee takes the base hours as the span from `checkin_at` up to the earlier of `checkout_at` and `end_at`, converted to hours and rounded up to the next whole hour, multiplied by `hourly_fee_cents`; adds an overage term for the span by which `checkout_at` exceeds `end_at` (zero when not past), converted to hours rounded up and multiplied by twice the `hourly_fee_cents`; and releases the deposit (it is not charged). A resident may cancel a `BOOKED` reservation to `CANCELLED`, which releases the committed `party_size` back to the amenity load and releases the deposit without charge; the delinquency cascade can also cancel a `BOOKED` reservation when the resident is suspended. A `CommunityAdmin` may mark a `BOOKED` reservation as `NO_SHOW` (a `Resident` attempting this transition is refused with `ERR_UNAUTHORIZED`), which releases the `party_size` from the load but forfeits the deposit — in that single case `settled_fee_cents` is set equal to the amenity's `deposit_cents`. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

### 3.6. Patrols and Incidents

A `SecurityOfficer` or `CommunityAdmin` schedules a patrol shift by supplying the `community_id`, the `officer_id` (the opaque officer label), the inclusive `start_at` and exclusive `end_at` bounds, and an optional `route` (defaulting to null). A new patrol's `status` is `SCHEDULED`. Scheduling enforces a per-officer buffer: for the same `officer_id`, treating each shift's `[start_at, end_at]` as a closed interval, a new shift is compared against every other of that officer's shifts in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` status, and the gap measured between their nearest endpoints must be at least 60 minutes on either side. A gap of exactly 60 minutes is allowed; a gap of less than 60 minutes — including a direct overlap, which has a negative gap — is refused with `ERR_PATROL_OVERLAP`. Patrols can be listed and filtered by `community_id`, `officer_id`, and `status`.

A `SecurityOfficer` or `CommunityAdmin` advances a patrol from `SCHEDULED` to `IN_PROGRESS`, then from `IN_PROGRESS` to `COMPLETED`, or cancels a `SCHEDULED` patrol to `CANCELLED`; no per-transition role restriction applies beyond the endpoint's authorized roles. `COMPLETED` and `CANCELLED` are terminal.

Incidents are logged by a `SecurityOfficer` or `CommunityAdmin` with the `community_id`, the `incident_type` (`TRESPASS`, `NOISE`, `SPEEDING`, `VANDALISM`, `UNAUTHORIZED_ACCESS`, or `OTHER`), the `severity` (`LOW`, `MEDIUM`, or `HIGH`), a `description`, and optionally the `patrol_id` during which it was observed, a free-text `location`, and a `related_resident_id` subject (each optional field defaulting to null). Of these references only `community_id` and, when supplied, `patrol_id` are existence-validated per §2.9 (yielding `ERR_COMMUNITY_NOT_FOUND` / `ERR_PATROL_NOT_FOUND`); `related_resident_id` is accepted as-is and is never existence-validated, so it may be null or may name no current resident without error. A new incident's `status` is `REPORTED`. A `SecurityOfficer` or `CommunityAdmin` advances it from `REPORTED` to `INVESTIGATING` and from `INVESTIGATING` to `RESOLVED`; only a `CommunityAdmin` may then close it from `RESOLVED` to the terminal `CLOSED`, and a `SecurityOfficer` attempting that close is refused with `ERR_UNAUTHORIZED`. Incidents can be listed and filtered by `community_id`, `patrol_id`, `status`, and `severity`.

### 3.7. Violations, Fines, Appeals, and Segregation of Duties

A `SecurityOfficer` or `CommunityAdmin` issues a violation against a resident by supplying the `community_id`, the cited `resident_id`, the `violation_type` (`SPEEDING`, `NOISE`, `PARKING`, `UNAUTHORIZED_GUEST`, or `GATE_TAILGATING`), the `base_fine_cents` (at least 0), and optionally the originating `incident_id` (defaulting to null). On issuance the system stamps `issued_at` from the logical clock, records the acting `X-User-ID` as `issued_by_user_id`, sets `status` to `ISSUED`, and computes the `assessed_fine_cents`. The `repeat_index` computed for the fine tiering (below) is also persisted on the violation as an integer field and echoed in the violation's representation alongside `assessed_fine_cents`. Violations can be listed and filtered by `community_id`, `resident_id`, `incident_id`, `status`, and `violation_type`.

The assessed fine is tiered by repeat offense and surcharged by standing, then capped. First the system computes `repeat_index`: the count of the same resident's other violations of the same `violation_type` whose `status` is `ISSUED`, `UPHELD`, `REDUCED`, or `PAID` and whose own `issued_at` falls within the 180-day repeat window ending at this issuance (that is, this violation's `issued_at` minus the prior violation's `issued_at` is at most 180 days), excluding the violation being issued. The tier multiplier is 1.0 when `repeat_index` is 0, 1.5 when it is 1, 2.0 when it is 2, and 3.0 when it is 3 or more. The base component is `base_fine_cents` multiplied by the tier multiplier, rounded half-up to a whole cent. A delinquency surcharge of 5,000 cents is added when the cited resident's `standing` is `DELINQUENT` at issuance, and 0 otherwise. Finally `assessed_fine_cents` is the smaller of the fine cap, 50,000 cents, and the rounded base component plus the surcharge. After the fine is assessed, the resident's `outstanding_balance_cents` and `standing` are recomputed, which may trigger the delinquency cascade and auto-suspend the resident.

A cited resident may appeal an `ISSUED` violation, moving its `status` to `APPEALED`, and may withdraw that appeal to return it from `APPEALED` to `ISSUED` — a revision loop that may repeat before resolution. An appeal may carry an optional `reason`. While a violation is `ISSUED`, `APPEALED`, `UPHELD`, or `REDUCED`, its `assessed_fine_cents` counts toward the resident's balance.

A `CommunityAdmin` resolves an `APPEALED` violation by supplying a `resolution` and, for reductions, a `reduced_fine_cents`. Every resolution is subject to segregation of duties: the acting `X-User-ID` must differ from the violation's `issued_by_user_id`, and a resolver who issued the violation is refused with `ERR_SEGREGATION_OF_DUTIES`. A `resolution` of `UPHELD` moves `status` to `UPHELD` and leaves `assessed_fine_cents` and the resident's balance contribution unchanged (the fine is still owed), then recomputes the resident's standing (which may re-trigger auto-suspension). A `resolution` of `DISMISSED` moves `status` to the terminal `DISMISSED` and removes the fine from the balance — the resident's `outstanding_balance_cents` decreases by that violation's `assessed_fine_cents` as a compensating reversal of issuance — then recomputes standing. A `resolution` of `REDUCED` requires `reduced_fine_cents` to be present and between 0 and the current `assessed_fine_cents` inclusive; a missing or out-of-range value is refused with `ERR_INVALID_RESOLUTION`. On a valid reduction the `status` moves to `REDUCED`, `assessed_fine_cents` is set to `reduced_fine_cents`, and the resident's balance and standing are recomputed against the new amount.

A violation is paid by the cited resident (on their own record) or a `CommunityAdmin` from any of the `ISSUED`, `UPHELD`, or `REDUCED` states, by supplying `amount_cents`. The payment must exactly equal the current `assessed_fine_cents`; any other amount is refused with `ERR_INVALID_RESOLUTION`. A valid payment records `paid_amount_cents`, moves `status` to the terminal `PAID`, and decreases the resident's `outstanding_balance_cents` by the assessed amount. `DISMISSED`, `PAID`, and `VOID` are terminal statuses.

### 3.8. Resident Statements and Community Reports

A `CommunityAdmin` or the resident themselves may pull a resident's billing statement, a computed view returning four values: `outstanding_balance_cents`, `accrued_late_fee_cents`, `statement_total_cents`, and the resident's `standing`. The outstanding balance is computed exactly as defined in Section 3.1. The accrued late fee is computed per violation line and then summed: for each of the resident's violations whose `status` is `ISSUED`, `UPHELD`, or `REDUCED`, the system multiplies that violation's `assessed_fine_cents` by the late-fee rate of 1.5 percent (0.015) and rounds the result half-up to a whole cent, and `accrued_late_fee_cents` is the sum of those per-line rounded amounts — the rounding is applied to each line before summation, never to a single combined total. The `statement_total_cents` is the outstanding balance plus the accrued late fee.

A `CommunityAdmin` may also pull two community-level reports. The access-log report accepts optional `from_iso` and `to_iso` bounds and returns `total_events`, `allow_count`, `deny_count`, and `unmatched_count` over the community's gate events whose `event_at` falls within the supplied range (or over all of the community's gate events when no bounds are given), where `allow_count` counts events with `decision` of `ALLOW`, `deny_count` counts those with `decision` of `DENY`, and `unmatched_count` counts those with `matched_type` of `UNMATCHED`. The violations-summary report returns `open_count`, the number of the community's violations still counted in residents' balances (`status` of `ISSUED`, `APPEALED`, `UPHELD`, or `REDUCED`); `total_assessed_cents`, the sum of `assessed_fine_cents` across those same violations; and `delinquent_resident_count`, the number of the community's residents whose `standing` is `DELINQUENT`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, drive a state transition, or return a computed view return `200 OK`. The logical-clock endpoint is an administrative test-driving capability returning `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/access/_clock/set_current_utc` | Set the server logical clock | CommunityAdmin |
| POST | `/access/communities` | Create a community | CommunityAdmin |
| GET | `/access/communities/{communityId}` | Get a community | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/residents` | Register a resident | CommunityAdmin |
| GET | `/access/residents/{residentId}` | Get a resident | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/residents` | List/filter residents (directory) | CommunityAdmin, SecurityOfficer |
| POST | `/access/residents/{residentId}/transition` | Transition resident status | CommunityAdmin |
| GET | `/access/residents/{residentId}/statement` | Computed billing statement | CommunityAdmin, Resident |
| POST | `/access/vehicles` | Register a vehicle | Resident, CommunityAdmin |
| GET | `/access/vehicles/{vehicleId}` | Get a vehicle | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/vehicles` | List/filter vehicles | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/vehicles/{vehicleId}/transition` | Transition vehicle status | CommunityAdmin |
| POST | `/access/decals` | Issue a decal to a vehicle | CommunityAdmin, SecurityOfficer |
| GET | `/access/decals/{decalId}` | Get a decal | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/decals` | List/filter decals | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/decals/{decalId}/transition` | Transition decal status | CommunityAdmin, SecurityOfficer |
| POST | `/access/passes` | Create a guest/vendor pass | Resident, CommunityAdmin |
| GET | `/access/passes/{passId}` | Get a pass | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/passes` | List/filter passes | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/passes/{passId}/authorize` | Approve or deny a pending pass | SecurityOfficer, CommunityAdmin |
| POST | `/access/passes/{passId}/revoke` | Revoke an approved pass | SecurityOfficer, CommunityAdmin |
| POST | `/access/gate-events` | Record an LPR gate read | SecurityOfficer |
| GET | `/access/gate-events/{gateEventId}` | Get a gate event | CommunityAdmin, SecurityOfficer |
| GET | `/access/gate-events` | List/filter gate events | CommunityAdmin, SecurityOfficer |
| POST | `/access/amenities` | Create an amenity | CommunityAdmin |
| GET | `/access/amenities/{amenityId}` | Get an amenity | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/amenities` | List/filter amenities | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/amenity-reservations` | Book an amenity reservation | Resident, CommunityAdmin |
| GET | `/access/amenity-reservations/{reservationId}` | Get a reservation | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/amenity-reservations` | List/filter reservations | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/amenity-reservations/{reservationId}/transition` | Transition a reservation | Resident, CommunityAdmin |
| POST | `/access/patrols` | Schedule a patrol shift | SecurityOfficer, CommunityAdmin |
| GET | `/access/patrols/{patrolId}` | Get a patrol | CommunityAdmin, SecurityOfficer |
| GET | `/access/patrols` | List/filter patrols | CommunityAdmin, SecurityOfficer |
| POST | `/access/patrols/{patrolId}/transition` | Transition a patrol | SecurityOfficer, CommunityAdmin |
| POST | `/access/incidents` | Log an incident | SecurityOfficer, CommunityAdmin |
| GET | `/access/incidents/{incidentId}` | Get an incident | CommunityAdmin, SecurityOfficer |
| GET | `/access/incidents` | List/filter incidents | CommunityAdmin, SecurityOfficer |
| POST | `/access/incidents/{incidentId}/transition` | Transition an incident | SecurityOfficer, CommunityAdmin |
| POST | `/access/violations` | Issue a violation | SecurityOfficer, CommunityAdmin |
| GET | `/access/violations/{violationId}` | Get a violation | CommunityAdmin, SecurityOfficer, Resident |
| GET | `/access/violations` | List/filter violations | CommunityAdmin, SecurityOfficer, Resident |
| POST | `/access/violations/{violationId}/appeal` | Resident appeals a violation | Resident |
| POST | `/access/violations/{violationId}/withdraw-appeal` | Resident withdraws an appeal | Resident |
| POST | `/access/violations/{violationId}/resolve` | Resolve an appealed violation | CommunityAdmin |
| POST | `/access/violations/{violationId}/pay` | Pay a violation fine | Resident, CommunityAdmin |
| GET | `/access/communities/{communityId}/reports/access-log` | Aggregate gate access report | CommunityAdmin |
| GET | `/access/communities/{communityId}/reports/violations-summary` | Aggregate violation/fine report | CommunityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_COMMUNITY_NOT_FOUND` | 404 |
| `ERR_RESIDENT_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_DECAL_NOT_FOUND` | 404 |
| `ERR_PASS_NOT_FOUND` | 404 |
| `ERR_AMENITY_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_PATROL_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_VIOLATION_NOT_FOUND` | 404 |
| `ERR_GATE_EVENT_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VEHICLE_INACTIVE` | 409 |
| `ERR_SPONSOR_NOT_ELIGIBLE` | 409 |
| `ERR_RESIDENT_NOT_ELIGIBLE` | 409 |
| `ERR_PASS_WINDOW_INVALID` | 422 |
| `ERR_RESERVATION_WINDOW_INVALID` | 422 |
| `ERR_PATROL_OVERLAP` | 422 |
| `ERR_AMENITY_AT_CAPACITY` | 409 |
| `ERR_AMENITY_NOT_RESERVABLE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_RESOLUTION` | 422 |
| `ERR_GATE_ACCESS_DENIED` | 409 |
