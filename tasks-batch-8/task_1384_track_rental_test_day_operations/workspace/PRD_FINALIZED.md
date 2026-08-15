# Track Rental Test Day API — Product Requirements Document

## 1. Introduction

Road-course operators sell their facility by the block to clubs, race teams, and driving schools, and every test day is a negotiation between revenue and risk: more cars on track means more income and more exposure, insurance certificates and signed waivers decide who may run, instructors must be matched to inexperienced groups, neighbors and noise ordinances bound how loud the day may get, and a single serious incident must be able to stop the circuit cold. Running such a day on phone calls and clipboards loses money and invites mistakes.

This document specifies the Track Rental & Test Day Operations API, a service mounted under `/tracks` that manages the full arc of a rental test day: venue setup and the coaching roster; scheduling days and slicing them into bookable rental blocks with per-block group-size quotas; booking submission, approval, and payment; driver registration, waiver collection, and safety inspection; session race control under green/red/black/checkered flag discipline; incident response, weather holds, and a derived safety posture that gates forward progress; property-line noise monitoring; garage and paddock allocation with utilities; and the cancellation, refund, and end-of-day close-out policies. Four acting roles — track operations, safety officials, renting-group organizers, and coaches — share the surface under a segregation-of-duties model.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request arriving with a missing or unknown `X-User-Role` is rejected with `ERR_UNAUTHENTICATED` (401); a caller whose role is not on an endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (403). Exactly four roles exist, spelled exactly as follows:

- `TrackOps` — the track operations operator: manages the track-day lifecycle, approves and rejects bookings, assigns coaches and facilities, runs race control, and operates the clock and payment test-driving capabilities.
- `SafetyOfficer` — the safety official: investigates and clears incidents, performs driver safety inspections, and holds resume authority after a stoppage.
- `Organizer` — the renting-group organizer: creates bookings and drivers, submits waivers, and cancels the group's own bookings.
- `Coach` — a driving coach: read-only across the API. Coach assignment mutates coach state, but the write itself is performed by `TrackOps`.

Identity semantics differ per role. When `X-User-Role` is `TrackOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `SafetyOfficer`, `X-User-ID` is likewise opaque, though the server records it where a transition writes an actor — for example as `reported_by_user_id` or `cleared_by_user_id` on an incident, or as `inspector_user_id` on a safety inspection — and segregation-of-duties checks compare those recorded values. When `X-User-Role` is `Organizer`, `X-User-ID` is an opaque renter identifier recorded as `organizer_user_id` on each booking the organizer creates; ownership checks — such as an organizer cancelling only their own bookings — compare that stored field to `X-User-ID`. When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting Coach entity; ownership checks on any resource that references a Coach compare the resource's coach foreign-key field to `X-User-ID`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a list endpoint states otherwise, results are ordered by `created_at` ascending — oldest first.

### 2.4. Resource Identity, Timestamps, Versioning, and the Logical Clock

Every persisted resource carries an `id` — a server-minted UUID with no type prefix, rendered in its canonical hyphenated text form (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, lowercase hexadecimal) — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, fixed at creation. Most resources additionally carry `updated_at`, refreshed to the current logical time on every mutation, and `version`, an integer that increments by exactly one on every mutation of that resource. Three record types are append-only evidence and carry only `id` and `created_at`: waivers, safety inspections, and noise readings have neither `updated_at` nor `version`.

The server runs on a logical clock that starts at 2026-08-01T00:00:00Z. Time advances only when a `TrackOps` caller invokes the clock capability at `POST /_clock/set_current_utc` with a `to_iso8601` instant; the response reports the new `current_utc`. Every server-stamped time in the domain — a session's `started_at_utc` and `ended_at_utc`, an inspection's `inspected_at_utc` — and every time-dependent rule — waiver expiry, the noise window, refund notice windows — reads this logical clock.

### 2.5. Nested Resource Paths and Flat Lookup Aliases

Every resource is reachable through a nested path that mirrors the ownership hierarchy. A track (`tid`) owns coaches (`cid`) and track days (`tdid`); a track day owns rental blocks (`rbid`), sessions (`sid`), incidents (`iid`), noise readings (`nrid`), garage assignments (`gid`), and paddock assignments (`pid`); a rental block owns bookings (`bid`); a booking owns drivers (`did`); and a driver owns waivers (`wid`) and safety inspections (`siid`). Path identifiers are validated strictly left to right: each identifier must exist and must belong to the parent established by the identifiers to its left, and any failure is `ERR_NOT_FOUND` (404), never a business-rule error.

In addition to the nested forms, every foreign-keyed child entity is also reachable through a flat canonical lookup by its own `id` and a flat filtered list under the top-level mount. The flat lists accept these optional filters: coaches filter by `track_id`, `cert_level`, and `active`; track days by `track_id`, `date`, and `status`; rental blocks by `track_day_id`; bookings by `rental_block_id`, `coach_id`, and `approval_status`; drivers by `booking_id`; waivers by `driver_id`; safety inspections by `driver_id`; sessions by `track_day_id`, `rental_block_id`, and `status`; incidents by `track_day_id`, `session_id`, `status`, and `severity`; noise readings by `track_day_id`, `session_id`, and `breach`; garage assignments by `track_day_id`, `booking_id`, and `status`; paddock assignments by `track_day_id`, `booking_id`, and `status`. Flat incident reads are restricted to `TrackOps` and `SafetyOfficer`; all other flat reads accept any of the four roles.

### 2.6. Optimistic Concurrency Control

Three writes are guarded by optimistic concurrency control, and each names its guard field as a non-optional request input:

- Approving a booking requires `expected_rental_block_version`, carrying the client's last observed `version` of the rental block. If the block's current `version` has advanced past it — for example because a prior approval consumed the remaining seats and flipped the block to FULL — the request is rejected with `ERR_STALE_VERSION` (412).
- Resuming a stopped track day requires `expected_track_day_version`, matched against the day's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (412), since a prior resume or a fresh incident may already have advanced the day's state.
- Creating a garage assignment requires `expected_track_day_version`, matched against the day's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (412), since a prior assignment may have consumed the last free bay since the client read capacity.

Endpoints not listed here take no version field at all.

### 2.7. Track-Day Posture and Forward-Progress Gating

Every track day exposes a derived `posture` — `NORMAL`, `CAUTION`, or `SUSPENDED` — recomputed from open incidents, recent noise breaches, and the weather flag (the full derivation lives in §3.6 and §3.7). Posture gates forward progress: while a day's `posture` is `SUSPENDED`, booking approvals, session starts, garage assignment creation, and coach assignments are rejected with `ERR_TRACK_SUSPENDED` (409).

Separately, a day whose `status` has reached `CANCELLED` or `CLOSED` accepts no forward progress at all: booking creation and approval, garage and paddock assignment creation, session starts, and incident reports are all rejected with `ERR_TRACK_DAY_NOT_LIVE` (409).

### 2.8. Money, Fees, and Rounding

All monetary amounts in the system are integer cents — no fractional cents appear anywhere. Refund computations that would produce a fractional cent round half-up to the nearest whole cent. Fee and policy constants appear alongside the workflows that use them: garage utility pricing in §3.8, cancellation and refund pricing in §3.9.

### 2.9. Validation Order and Error Selection

When several checks could reject the same request, they are evaluated in the following fixed order, and the first failure wins:

1. Authentication — `X-User-Role` present and a known role, on every endpoint: `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role is permitted to invoke this endpoint, on every endpoint: `ERR_FORBIDDEN_ROLE` (403).
3. Existence — every path identifier exists within its parent scope, on every resource endpoint: `ERR_NOT_FOUND` (404).
4. Request shape — required body fields present, types valid, enum values valid, ids well-formed, on every mutating endpoint: `ERR_INVALID_REQUEST` (400).
5. Optimistic concurrency — the expected-version field matches the parent's current `version`, on the guarded writes of §2.6: `ERR_STALE_VERSION` (412).
6. Track-day liveness — the day is neither `CANCELLED` nor `CLOSED`, on booking create and approve, garage and paddock assignment create, session start, and incident report: `ERR_TRACK_DAY_NOT_LIVE` (409).
7. State-machine preconditions — the resource stands in a state that permits the requested transition, on every state-transition endpoint: `ERR_INVALID_STATE` (409).
8. Posture — the day's `posture` is not `SUSPENDED`, on booking approve, session start, garage assignment create, and coach assign: `ERR_TRACK_SUSPENDED` (409).
9. Segregation of duties — the inspector is not the booking's organizer, and the incident clearer is not its reporter, on driver inspection and incident clear: `ERR_SEGREGATION_OF_DUTIES` (422).
10. Driver clearance — waiver, inspection, approval, and payment prerequisites, on lap attribution and driver start: `ERR_DRIVER_NOT_CLEARED` (422).
11. Coach certificate sufficiency, on coach assign: `ERR_COACH_CERT_INSUFFICIENT` (422).
12. Coach load, on coach assign: `ERR_COACH_OVERLOADED` (409).
13. Rental-block interval overlap, on rental-block create: `ERR_BLOCK_OVERLAP` (409).
14. Garage bay occupancy, on garage assignment create: `ERR_BAY_OCCUPIED` (409).
15. Paddock stall occupancy, on paddock assignment create: `ERR_STALL_OCCUPIED` (409).
16. Group-size cap against the track's capacity, on rental-block create: `ERR_GROUP_SIZE_EXCEEDS_TRACK_CAP` (422).
17. Driver-count bounds, on booking create: `ERR_INVALID_DRIVER_COUNT` (422).
18. Seat availability at approval, on booking approve: `ERR_BLOCK_FULL` (409).
19. Insurance reference presence, on booking approve: `ERR_INSURANCE_MISSING` (422).
20. Payment-capture ordering, on payment capture: `ERR_INVALID_STATE` (409).

## 3. Business Logic & Workflows

### 3.1. Venue Setup: Tracks and the Coaching Roster

Everything begins with the venue. A `TrackOps` operator registers a track with its `name` and four operating parameters: `noise_limit_db`, the maximum permitted decibel level at the property line; `run_group_capacity`, the maximum number of cars allowed on track simultaneously in any run group; `garage_bay_count`, the total rentable garage bays; and `paddock_stall_count`, the total paddock stalls. These numbers are not decorative — later rules enforce them: block group sizes are capped by `run_group_capacity`, bay and stall indices are bounded by the two counts, and every noise reading is judged against `noise_limit_db`.

Coaches are registered against a home track with a `full_name`, a `cert_level` of `BASIC`, `INTERMEDIATE`, or `RACE`, and an optional `active` flag that defaults to true; only active coaches are assignable. A coach's `assigned_booking_ids` is a computed roll of the bookings currently attached to that coach — bookings whose `coach_id` references the coach and whose `approval_status` stands at `APPROVED`. Two qualification rules guard assignment, applied whenever a coach is attached to a booking. Certificate sufficiency: a booking in the `NOVICE` run group requires a coach holding `INTERMEDIATE` or `RACE` certification, and a `RACE` booking requires a `RACE`-certified coach; an under-certified assignment is rejected with `ERR_COACH_CERT_INSUFFICIENT` (422). Load: a coach may serve at most three bookings on the same track day — a fourth simultaneous assignment draws `ERR_COACH_OVERLOADED` (409). The roster of a track can be listed with optional `cert_level` and `active` filters, and individual coaches fetched by id; `Coach` callers themselves are read-only across the entire API.

### 3.2. Scheduling Test Days and Rental Blocks

A `TrackOps` operator schedules a test day by supplying its `date` — an ISO-8601 calendar day in year-month-day form. The day is born `SCHEDULED` with `weather_flag` `CLEAR`, an `ops_run_index` of zero, posture `NORMAL`, and `cancelled_reason` empty — it stays empty until the day is actually cancelled. A track day's `status` walks a seven-value vocabulary: `SCHEDULED`, `OPEN`, `WEATHER_HOLD`, `RUNNING`, `STOPPED`, `CLOSED`, and `CANCELLED`, with `CLOSED` and `CANCELLED` terminal. Days can be listed with optional `date` and `status` filters.

Within a day, `TrackOps` slices the schedule into rental blocks. Each block carries a `block_index` sequencing it within the day and a half-open minute-of-day window — `start_minute` inclusive, `end_minute` exclusive — so two blocks may touch at a boundary without overlapping. An interval that overlaps any other block on the same day is rejected with `ERR_BLOCK_OVERLAP` (409), and this temporal check is evaluated before the capacity check that follows. Each block also declares `max_group_size`, the cap on simultaneous on-track cars for that block, which must not exceed the track's `run_group_capacity`; a block that oversteps the venue cap is rejected with `ERR_GROUP_SIZE_EXCEEDS_TRACK_CAP` (422).

A block is born `OPEN` with `seats_reserved` at zero. Two counters are then derived continuously: `seats_reserved`, the sum of `driver_count` across the block's `APPROVED` bookings, and `seats_available`, `max_group_size` minus `seats_reserved`, floored at zero so it can never report negative. When an approval pushes `seats_reserved` to exactly `max_group_size`, the block flips from `OPEN` to `FULL`, and while a block is `FULL` new booking submissions against it are rejected with `ERR_BLOCK_FULL` (409). When a later cancellation or rejection brings `seats_reserved` back below `max_group_size`, the block returns from `FULL` to `OPEN`. `TrackOps` may also close a block outright — from either `OPEN` or `FULL` — which moves it to the terminal `CLOSED` state and cascades every `PENDING` booking on that block to `REJECTED`.

### 3.3. Bookings: Submission, Approval, and Payment

An `Organizer` opens a booking against a block by submitting `organizer_user_id`, a display `group_name`, a `run_group_class` of `NOVICE`, `INTERMEDIATE`, `ADVANCED`, or `RACE`, a declared `driver_count`, and an `insurance_policy_ref` certificate reference; a `coach_id` may optionally be attached at creation. The booking is born with `approval_status` `PENDING` and `payment_status` `UNPAID`, `refund_cents` at zero, no coach unless one was supplied, and no cancellation snapshot yet. The declared `driver_count` must be at least one and no more than the block's `max_group_size` — violations draw `ERR_INVALID_DRIVER_COUNT` (422) — and the submission itself is rejected with `ERR_BLOCK_FULL` (409) when the block is already `FULL`, or with `ERR_TRACK_DAY_NOT_LIVE` (409) when the day is cancelled or closed. Bookings on a block can be listed with `approval_status` and `run_group_class` filters.

Approval is a `TrackOps` decision and the most heavily gated write in the system. After the universal checks — authentication, authorization, path existence, and body validity, in that order — the gates fire in a fixed sequence. First, optimistic concurrency: the request must carry `expected_rental_block_version` equal to the block's current `version`; a client acting on a stale view — say, one read before a competing approval consumed the last seats — is rejected with `ERR_STALE_VERSION` (412). Second, liveness: a day already `CANCELLED` or `CLOSED` rejects with `ERR_TRACK_DAY_NOT_LIVE` (409). Third, the state gate: the block must not be `CLOSED`, the day must stand at `OPEN` or `RUNNING`, and a coach must already be attached exactly when the booking's `run_group_class` is `NOVICE` — violations are rejected as `ERR_INVALID_STATE` (409). Fourth, posture: a `SUSPENDED` day rejects with `ERR_TRACK_SUSPENDED` (409). Only then come the fiscal checks, in this order: seating, where a `driver_count` exceeding the block's current `seats_available` is rejected with `ERR_BLOCK_FULL` (409); and insurance, where a missing or empty `insurance_policy_ref` is rejected with `ERR_INSURANCE_MISSING` (422).

When several `PENDING` bookings compete for a block's last seats, approval order follows a fixed priority: `NOVICE` bookings outrank `INTERMEDIATE`, which outrank `ADVANCED`, which outrank `RACE`, and ties break toward the earlier-submitted booking by ascending `created_at`. Rank never overrides capacity — a booking is approved only if its `driver_count` fits within `seats_available` at the moment of approval.

A successful approval stamps `approval_status` `APPROVED`, adds the booking's `driver_count` to the block's `seats_reserved` — flipping the block to `FULL` when the seats exactly fill — freezes the cancellation-policy thresholds into `cancel_policy_snapshot`, and advances the block's `version` by one. Rejection — also a `TrackOps` call, available against a `PENDING` booking — moves `approval_status` to `REJECTED`, a terminal state, with no other effect.

Money moves through a `TrackOps`-only payment simulation capability whose request carries `booking_id` and an `outcome`. The `payment_status` vocabulary is `UNPAID`, `AUTHORIZED`, `CAPTURED`, `REFUNDED`, and `FORFEITED`, and the simulation walks it in steps: outcome `AUTHORIZE` moves `UNPAID` to `AUTHORIZED`; `CAPTURE` moves `AUTHORIZED` to `CAPTURED`, and capturing from any other state is rejected with `ERR_INVALID_STATE` (409); `VOID` drops an `AUTHORIZED` payment back to `UNPAID`; `REFUND` moves `CAPTURED` to `REFUNDED`. A driver only becomes cleared once payment is `CAPTURED`, so capture ordering matters to race control.

Coach assignment after creation is a `TrackOps` write carrying `coach_id`. It is refused on a `SUSPENDED` day with `ERR_TRACK_SUSPENDED` (409), refused for an under-certified coach with `ERR_COACH_CERT_INSUFFICIENT` (422), and refused when the coach already serves three bookings on the day with `ERR_COACH_OVERLOADED` (409). Success sets the booking's `coach_id` and refreshes the coach's `assigned_booking_ids`.

### 3.4. Drivers, Waivers, and Safety Inspection

Once a booking exists, the `Organizer` registers its drivers one by one with a `full_name` and a `license_class` of `STREET`, `CLUB`, or `PRO`. A new driver starts with `waiver_status` `PENDING` and `safety_status` `NOT_INSPECTED`.

A signed waiver is submitted — by the `Organizer` or a `TrackOps` operator — with `signed_at_utc` and a `signature_payload_hash` of the e-signature payload. The record's `expires_at_utc` is computed as `signed_at_utc` plus `WAIVER_TTL_HOURS` hours, and the driver's `waiver_status` becomes `SIGNED`. Waivers are append-only evidence records: they carry an `id` and `created_at` but no `updated_at` and no `version`. Expiry is swept by the operations checkpoint described in §3.6 — any waiver whose `expires_at_utc` is strictly earlier than the current logical time flips its driver's `waiver_status` to `EXPIRED`. A driver's waiver history can be listed.

Safety inspection is the `SafetyOfficer`'s domain. The officer submits `inspector_user_id`, `helmet_ok`, and `harness_ok`; the server stamps `inspected_at_utc` from the logical clock and computes the `result` — `PASSED` when both `helmet_ok` and `harness_ok` are true, `FAILED` otherwise — and the driver's `safety_status` follows the `result`. Segregation of duties is enforced: `inspector_user_id` must differ from the booking's `organizer_user_id`, or the submission is rejected with `ERR_SEGREGATION_OF_DUTIES` (422). A driver in `NOT_INSPECTED` may transition to `PASSED` or to `FAILED`; a `FAILED` driver may be re-inspected and, when both equipment checks pass, move to `PASSED`. Inspection requests outside those transitions are rejected with `ERR_INVALID_STATE` (409). Inspection records are append-only like waivers, and a driver's inspection history can be listed.

The two flags meet in `cleared_to_run`, a derived boolean that is true only when the driver's `waiver_status` is `SIGNED`, `safety_status` is `PASSED`, the booking stands `APPROVED`, and `payment_status` is `CAPTURED`; it is recomputed whenever any of those four inputs changes. Race control depends on it: attributing a lap to a driver, or starting a driver, who is not cleared is rejected with `ERR_DRIVER_NOT_CLEARED` (422).

### 3.5. Sessions and Race Control

When the day is live and unblocked, a `TrackOps` operator starts a session by naming its `rental_block_id` and `run_group_class`. The session opens `GREEN` with `started_at_utc` stamped from the logical clock, `lap_count` at zero, and `max_db_observed` at zero. Starting a session on a day that is `CANCELLED` or `CLOSED` draws `ERR_TRACK_DAY_NOT_LIVE` (409); starting one while the day's `posture` is `SUSPENDED` draws `ERR_TRACK_SUSPENDED` (409). The first session to reach `GREEN` flips the day itself from `OPEN` to `RUNNING` automatically, and the day's `version` advances with that cascade. Session `status` uses the flag vocabulary `GREEN`, `RED`, `BLACK`, and `CHECKERED`, with `CHECKERED` terminal. Sessions can be listed with `status` and `rental_block_id` filters.

Laps accumulate through a lap-recording write that increments `lap_count` by one; the driver-clearance rule of §3.4 governs any lap attributed to a driver. When a group has run its allotted driving, `TrackOps` throws the checkered flag — permitted only from `GREEN`, and only once the session has logged at least `MIN_LAPS_FOR_CHECKERED` laps, the configured minimum-lap threshold; a short session is rejected with `ERR_INVALID_STATE` (409). The checkered flag stamps `ended_at_utc` and moves the session to `CHECKERED`.

### 3.6. Incidents, Weather, and the Track-Day Posture

Either a `TrackOps` operator or a `SafetyOfficer` reports an incident with the `session_id` where it occurred, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a `reported_by_user_id`; the day must still be live, or the report is rejected with `ERR_TRACK_DAY_NOT_LIVE` (409). A new incident opens in `OPEN` status and bumps the day's `open_incident_count` by one. Severity drives the cascade: at `MEDIUM`, `HIGH`, or `CRITICAL` the session where it happened drops from `GREEN` to `RED`; at `HIGH` or `CRITICAL` the whole day stops — a `RUNNING` day transitions to `STOPPED`, every `GREEN` session on it cascades to `RED`, and the posture recomputes to `SUSPENDED`. In all cases the posture is recomputed and the day's `version` advances by one.

Incident resolution is `SafetyOfficer` work, with two steps available. Investigation moves an incident from `OPEN` to `INVESTIGATING` with no other effect. Clearing resolves it: from `INVESTIGATING` unconditionally, or directly from `OPEN` only when the `severity` is `LOW`. Segregation of duties is enforced on clear — the supplied `cleared_by_user_id` must differ from the incident's `reported_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (422) — and the state check fires before the segregation check. Clearing decrements `open_incident_count` by one, recomputes posture, advances the day's `version`, and lands the incident in the terminal `CLEARED` state. Incidents can be listed with `status` and `severity` filters.

Weather is `TrackOps`-operated through the `weather_flag`, whose values are `CLEAR`, `WATCH`, and `STOP`. Declaring a weather hold is permitted from `OPEN` or `RUNNING` while the flag stands at `CLEAR` or `WATCH`: the day moves to `WEATHER_HOLD`, the flag becomes `WATCH`, and — when the day had been `RUNNING` — every `GREEN` session drops to `RED`. Clearing the hold is permitted while the flag stands at `WATCH`: the day returns from `WEATHER_HOLD` to `OPEN` and the flag resets to `CLEAR`. Should the flag stand at `STOP`, the day's posture is `SUSPENDED` and resumption is barred until it leaves that state; and if the flag becomes `STOP` while the day is `RUNNING`, the day itself transitions to `STOPPED`, every `GREEN` session on it cascades to `RED`, and the posture recomputes to `SUSPENDED` — the same stoppage a high-severity incident would cause.

The day's `posture` is derived in exactly this order. If `weather_flag` stands at `STOP`, posture is `SUSPENDED`. Otherwise, if at least one incident is open and any `OPEN` incident carries `HIGH` or `CRITICAL` severity, posture is `SUSPENDED`. Otherwise, if the noise breach count is at least 3, posture is `SUSPENDED`. Otherwise, if any incident is open, or the breach count is at least 1, or the weather flag stands at `WATCH`, posture is `CAUTION`. In every other case, posture is `NORMAL`.

Resuming a stopped day is exclusively `SafetyOfficer` authority and is version-guarded: the request carries `expected_track_day_version` matching the day's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (412) — a prior resume or a fresh incident may already have moved the day past the client's last read. Three conditions must all hold for the resume itself: no open incidents, the weather flag not at `STOP`, and the noise breach count below 3; a violation is rejected with `ERR_INVALID_STATE` (409). A successful resume moves the day from `STOPPED` back to `RUNNING`, returns every `RED` session to `GREEN`, recomputes posture — `NORMAL` or `CAUTION` depending on the remaining breach count — and advances the day's `version` by one.

Two more day-level writes round out operations. Opening the day moves `SCHEDULED` to `OPEN`, recomputes posture — `NORMAL` provided nothing is open, breaching, or weather-stopped — and advances the day's `version` by one. The operations checkpoint, a `TrackOps`-run sweep, bumps `ops_run_index` by one, expires every waiver whose `expires_at_utc` is strictly before the current logical time (flipping those drivers' `waiver_status` to `EXPIRED`), recomputes posture, and advances the day's `version` by one.

### 3.7. Noise Compliance at the Property Line

Sound is policed continuously. Either a `TrackOps` operator or a `SafetyOfficer` records a reading with the `session_id` it is attributed to, the observed `db_level`, and the `recorded_at_utc` timestamp. The `breach` flag is computed immediately and strictly: `breach` is true when `db_level` is greater than the track's `noise_limit_db` — a reading exactly equal to the limit is not a breach. The attributed session's `max_db_observed` becomes the greater of its current value and the new `db_level`.

The day's `noise_breach_count` is recomputed on every reading as the number of breaching readings on that day whose `recorded_at_utc` falls within the trailing sixty-minute window — readings taken at least as recently as sixty minutes before the current logical time count; older ones fall out. That count feeds the posture ladder of §3.6: a single breach lifts the day to `CAUTION`, and a third breach inside the window suspends it. Noise readings are append-only records carrying only `id` and `created_at`, and can be listed with `session_id` and `breach` filters. No reactive rejection exists for a breaching reading — enforcement happens server-side through posture recomputation, and `ERR_NOISE_LIMIT_EXCEEDED` (422) is reserved for a future reactive endpoint and remains informational.

### 3.8. Garage Bays and Paddock Stalls

Garage bays are rented per day. A `TrackOps` operator creates an assignment with `booking_id`, a `bay_number` running from 1 up to the track's `garage_bay_count`, a `power_hookups` count of zero or more, a `water_hookup` flag, and — because bay capacity moves fast on event morning — `expected_track_day_version` matching the day's current `version`. The guards fire in order: the version check first, rejecting a stale view with `ERR_STALE_VERSION` (412) since a prior assignment may have consumed the last free bay since the client read capacity; then day liveness with `ERR_TRACK_DAY_NOT_LIVE` (409); then posture with `ERR_TRACK_SUSPENDED` (409); then occupancy, where a bay already `ACTIVE` on the day rejects with `ERR_BAY_OCCUPIED` (409). A successful assignment starts `ACTIVE`, its utility fee is computed and added to the booking, and the day's `version` advances by one.

The utility fee is integer cents, computed as follows: a 15,000-cent base per assignment; power tiered so that the first two hookups cost 2,500 cents each and every hookup beyond the second costs 4,000 cents each — an assignment with two or fewer hookups pays 2,500 cents per hookup, while a larger one pays 5,000 cents for the first pair plus 4,000 cents apiece for the rest; and a flat 3,000 cents when `water_hookup` is true, nothing otherwise. Base, power, and water sum to the total fee.

Releasing a bay — explicitly by `TrackOps`, or implicitly when the booking is cancelled — moves the assignment from `ACTIVE` to the terminal `RELEASED` state and frees the bay for reassignment. Assignments can be listed with `status` and `booking_id` filters.

Paddock stalls follow the same pattern with lighter machinery. A `TrackOps` operator assigns a stall with `booking_id` and a `stall_number` running from 1 up to the track's `paddock_stall_count`; the day must be live — a `CANCELLED` or `CLOSED` day rejects with `ERR_TRACK_DAY_NOT_LIVE` (409) — and a stall already `ACTIVE` on the day rejects with `ERR_STALL_OCCUPIED` (409). The assignment starts `ACTIVE`, and release — explicit by `TrackOps`, or via the booking-cancel cascade — moves it to the terminal `RELEASED` state. Listing supports `status` and `booking_id` filters.

### 3.9. Cancellation, Refunds, and Closing the Day

An `APPROVED` booking can be cancelled by `TrackOps`, or by the `Organizer` who owns it — the caller's `X-User-ID` must match the booking's `organizer_user_id`. Cancelling a booking in any other approval state is rejected with `ERR_INVALID_STATE` (409). Cancellation unwinds everything the booking held: `approval_status` becomes `CANCELLED`; the block's `seats_reserved` drops by the booking's `driver_count` and the block's status is recomputed, so a `FULL` block with freed seats returns to `OPEN`; every garage and paddock assignment on the booking flips to `RELEASED`; the assigned coach, if any, is detached — the booking's `coach_id` is nulled and the coach's `assigned_booking_ids` refreshed; and a refund is computed against the `cancel_policy_snapshot` frozen at approval and recorded as `refund_cents`, which otherwise stays zero until a cancellation actually happens. The optional `reason` input selects the refund variant; when omitted, the `CUSTOMER` chronological variant applies.

The refund math runs on the fee — 35,000 cents per declared driver, multiplied by the booking's `driver_count` — and on the notice window: the whole-hour difference, rounded down, between the current logical time and the block's start (its `start_minute` on the track day's `date`). Three variants exist, and when a whole-day cancellation cascades, the day's `cancelled_reason` forces the variant for every booking. The chronological variant, used for `CUSTOMER`, pays the full fee when at least 72 hours of notice remain, half the fee when at least 24 but fewer than 72 hours remain, and nothing when fewer than 24 hours remain, with the applicable percentage applied to the fee and rounded half-up to whole cents. The weather variant, forced by `WEATHER`, pays three quarters of the fee — rounded half-up — minus a flat 5,000-cent facility fee, floored at zero, independent of notice. The safety variant, forced by `SAFETY`, pays the entire fee, also independent of notice. One override cuts across all three: if the booking's payment stands merely `AUTHORIZED` and never reached `CAPTURED`, `refund_cents` is zero and the authorization is voided instead.

Cancelling the entire day is a `TrackOps` act with three doors, each with its own reason discipline. From `WEATHER_HOLD`, the day may be cancelled with `reason` `WEATHER`. From `OPEN`, the accepted reasons are `CUSTOMER` and `SAFETY`, and a `SAFETY` cancellation requires at least one open incident. From `RUNNING`, the accepted reasons are `WEATHER` and `SAFETY`. A reason that does not fit the day's current state is rejected with `ERR_INVALID_STATE` (409). Every door writes `cancelled_reason`, sets the day `CANCELLED`, and cascades all bookings on the day to `CANCELLED` with refunds computed under the variant the reason forces; cancelling a `RUNNING` day additionally blacks out the session layer, moving every `GREEN` and every `RED` session to `BLACK` with `ended_at_utc` stamped. The day's `version` advances by one. `CANCELLED` is terminal.

Closing is the orderly end: from `RUNNING`, `TrackOps` may close the day only when no incident is open and no session stands at `GREEN` or `RED` — violations are rejected with `ERR_INVALID_STATE` (409). Closing recomputes posture, leaves bookings in place while payments are finalized, advances the day's `version` by one, and lands the day in the terminal `CLOSED` state.

## 4. Endpoint Definitions

Endpoints that create a new resource return 201 with the created resource in the envelope; reads, state transitions, and other modifications return 200 with the affected resource (or resource array) in the envelope. All bodies conform to §2.2, lists paginate per §2.3, and authorization follows §2.1 — a caller whose role is not listed for an endpoint receives `ERR_FORBIDDEN_ROLE` (403). Request payloads and side effects are specified in the §3 workflows referenced by each description.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied ISO-8601 UTC instant (server starts at 2026-08-01T00:00:00Z; the only way to advance time) | TrackOps |
| POST | `/_payments/simulate` | Drive a booking's `payment_status` through AUTHORIZED/CAPTURED transitions | TrackOps |
| POST | `/tracks` | Create a track | TrackOps |
| GET | `/tracks/{tid}` | Get a track | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/coaches` | Register a coach | TrackOps |
| GET | `/tracks/{tid}/coaches/{cid}` | Get a coach | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/coaches` | List coaches (optional `cert_level`, `active` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days` | Create a track day (status `SCHEDULED`) | TrackOps |
| GET | `/tracks/{tid}/track-days/{tdid}` | Get a track day | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days` | List track days (optional `date`, `status` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/open` | Open the track day (`SCHEDULED` → `OPEN`) | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/weather_hold` | Declare a weather hold (`weather_flag` = `WATCH`) | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/weather_clear` | Clear the weather hold | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/resume` | Resume from `STOPPED` (OCC on the day's version) | SafetyOfficer |
| POST | `/tracks/{tid}/track-days/{tdid}/cancel` | Cancel the track day | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/close` | Close the track day (`RUNNING` → `CLOSED`) | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/run_ops` | Ops checkpoint: bump `ops_run_index`, expire stale waivers, recompute posture | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks` | Create a rental block | TrackOps |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}` | Get a rental block | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks` | List rental blocks on a track day | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/close_block` | Close the block (PENDING bookings → `REJECTED`) | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings` | Create a booking (`PENDING`, `UNPAID`) | Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}` | Get a booking | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings` | List bookings for a block (optional `approval_status`, `run_group_class` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/approve` | Approve a booking (OCC on the block's version) | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/reject` | Reject a `PENDING` booking | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/cancel` | Cancel a booking (refund per snapshot and reason) | TrackOps, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/assign_coach` | Assign a coach to the booking | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers` | Register a driver on the booking | Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}` | Get a driver | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers` | List drivers on the booking | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/waiver` | Submit a signed waiver for the driver | Organizer, TrackOps |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/waivers` | List waivers for the driver | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/inspect` | Submit a safety inspection for the driver | SafetyOfficer |
| GET | `/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/inspections` | List safety inspections for the driver | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/sessions` | Start a session (`GREEN`) on a rental block | TrackOps |
| GET | `/tracks/{tid}/track-days/{tdid}/sessions/{sid}` | Get a session | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/sessions` | List sessions (optional `status`, `rental_block_id` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/sessions/{sid}/checkered` | Checkered-flag the session | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/sessions/{sid}/lap_event` | Record a lap (increments `lap_count`) | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/incidents` | Report an incident | TrackOps, SafetyOfficer |
| GET | `/tracks/{tid}/track-days/{tdid}/incidents/{iid}` | Get an incident | TrackOps, SafetyOfficer |
| GET | `/tracks/{tid}/track-days/{tdid}/incidents` | List incidents (optional `status`, `severity` filters) | TrackOps, SafetyOfficer |
| POST | `/tracks/{tid}/track-days/{tdid}/incidents/{iid}/investigate` | Move the incident to `INVESTIGATING` | SafetyOfficer |
| POST | `/tracks/{tid}/track-days/{tdid}/incidents/{iid}/clear` | Clear the incident (segregation of duties enforced) | SafetyOfficer |
| POST | `/tracks/{tid}/track-days/{tdid}/noise-readings` | Record a noise reading | TrackOps, SafetyOfficer |
| GET | `/tracks/{tid}/track-days/{tdid}/noise-readings` | List noise readings (optional `session_id`, `breach` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/garage-assignments` | Assign a garage bay (OCC on the day's version) | TrackOps |
| GET | `/tracks/{tid}/track-days/{tdid}/garage-assignments/{gid}` | Get a garage assignment | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/garage-assignments` | List garage assignments (optional `status`, `booking_id` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/garage-assignments/{gid}/release` | Release the garage assignment | TrackOps |
| POST | `/tracks/{tid}/track-days/{tdid}/paddock-assignments` | Assign a paddock stall | TrackOps |
| GET | `/tracks/{tid}/track-days/{tdid}/paddock-assignments/{pid}` | Get a paddock assignment | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/{tid}/track-days/{tdid}/paddock-assignments` | List paddock assignments (optional `status`, `booking_id` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| POST | `/tracks/{tid}/track-days/{tdid}/paddock-assignments/{pid}/release` | Release the paddock assignment | TrackOps |
| GET | `/tracks/coaches/{cid}` | Flat lookup of a coach by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/coaches` | Flat filtered list of coaches (optional `track_id`, `cert_level`, `active` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/track-days/{tdid}` | Flat lookup of a track day by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/track-days` | Flat filtered list of track days (optional `track_id`, `date`, `status` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/rental-blocks/{rbid}` | Flat lookup of a rental block by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/rental-blocks` | Flat filtered list of rental blocks (optional `track_day_id` filter) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/bookings/{bid}` | Flat lookup of a booking by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/bookings` | Flat filtered list of bookings (optional `rental_block_id`, `coach_id`, `approval_status` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/drivers/{did}` | Flat lookup of a driver by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/drivers` | Flat filtered list of drivers (optional `booking_id` filter) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/waivers/{wid}` | Flat lookup of a waiver by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/waivers` | Flat filtered list of waivers (optional `driver_id` filter) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/safety-inspections/{siid}` | Flat lookup of a safety inspection by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/safety-inspections` | Flat filtered list of safety inspections (optional `driver_id` filter) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/sessions/{sid}` | Flat lookup of a session by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/sessions` | Flat filtered list of sessions (optional `track_day_id`, `rental_block_id`, `status` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/incidents/{iid}` | Flat lookup of an incident by id | TrackOps, SafetyOfficer |
| GET | `/tracks/incidents` | Flat filtered list of incidents (optional `track_day_id`, `session_id`, `status`, `severity` filters) | TrackOps, SafetyOfficer |
| GET | `/tracks/noise-readings/{nrid}` | Flat lookup of a noise reading by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/noise-readings` | Flat filtered list of noise readings (optional `track_day_id`, `session_id`, `breach` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/garage-assignments/{gid}` | Flat lookup of a garage assignment by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/garage-assignments` | Flat filtered list of garage assignments (optional `track_day_id`, `booking_id`, `status` filters) | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/paddock-assignments/{pid}` | Flat lookup of a paddock assignment by id | TrackOps, SafetyOfficer, Coach, Organizer |
| GET | `/tracks/paddock-assignments` | Flat filtered list of paddock assignments (optional `track_day_id`, `booking_id`, `status` filters) | TrackOps, SafetyOfficer, Coach, Organizer |

## 5. Error Code Catalogue

The catalogue below assigns each machine-readable error identifier its HTTP status code. The conditions that trigger each error are specified in the narratives of §2 and §3 where the guarded workflow lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_TRACK_DAY_NOT_LIVE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_TRACK_SUSPENDED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_DRIVER_NOT_CLEARED | 422 |
| ERR_COACH_CERT_INSUFFICIENT | 422 |
| ERR_COACH_OVERLOADED | 409 |
| ERR_BLOCK_OVERLAP | 409 |
| ERR_BAY_OCCUPIED | 409 |
| ERR_STALL_OCCUPIED | 409 |
| ERR_GROUP_SIZE_EXCEEDS_TRACK_CAP | 422 |
| ERR_INVALID_DRIVER_COUNT | 422 |
| ERR_BLOCK_FULL | 409 |
| ERR_INSURANCE_MISSING | 422 |
| ERR_NOISE_LIMIT_EXCEEDED | 422 |
