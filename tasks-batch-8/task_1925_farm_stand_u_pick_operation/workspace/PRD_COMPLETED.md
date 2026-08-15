# Farm Stand & U-Pick Operation API — Product Requirements Document

## 1. Introduction

A family U-pick farm lives and dies by a short, intense harvest season: fields open and close as crops ripen and are picked out, guests sign liability waivers at a kiosk, pay gate admission and container fees, weigh their harvest at field stations, and add wagon rides or cafe vouchers to the day. Weather can end a sales day in minutes, and the point-of-sale devices at the field edge must keep working when connectivity drops, reconciling their offline records against the server at closing time. Managing this by hand — tracking how many ounces remain in each field, which waiver version each party signed, whether a party has paid enough to enter the field, and how much of a refund a rained-out afternoon deserves — is error-prone exactly when the farm is busiest.

This document specifies the API for a Farm Stand & U-Pick Operation platform, mounted under the `/farm` prefix. It covers season and pricing-policy administration, crop and field registration with rotation control, sales-day and picking-window scheduling under staffing constraints, gate admission with waiver and capacity gating, staff-attested weigh-out, agritourism add-on booking, payment collection with a single charge-and-refund ledger model, tiered weather-closure refunds, end-of-day sweeps, and an idempotent offline batch channel for edge devices. Global structural contracts (envelope, pagination, clock, concurrency control, and the validation pipeline) are defined in §2; business workflows are narrated in §3; §4 indexes the endpoints and §5 indexes the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The declared roles, spelled exactly as shown, are `FarmManager` (the farm owner/operator; a superset of every operational role plus exclusive administration and manual-refund authority), `GateStaff` (front-gate admission staff), `FieldStaff` (field weigh-station and checkout staff), `KioskDevice` (an offline point-of-sale device uploading end-of-day batches), and `Anonymous` (an unauthenticated public signer at the waiver kiosk).

When `X-User-Role` is `FarmManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same holds when `X-User-Role` is `GateStaff`, when it is `FieldStaff`, and when it is `KioskDevice`: in each case `X-User-ID` is an opaque identifier with no entity backing and no ownership comparison. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise opaque, and it is the one role for which `X-User-ID` may be omitted entirely.

Two authentication failures are distinguished. A missing `X-User-Role`, a role string that names no declared role, or a missing `X-User-ID` for any role other than `Anonymous` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); this check applies to every endpoint except the public waiver-signing endpoint, which accepts headerless kiosk traffic. Separately, when the presented role is not in the endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN` (HTTP 403); this authorization check applies to all endpoints, so a credentialed non-`Anonymous` caller attempting to use the waiver-signing endpoint is forbidden rather than authenticated.

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

List endpoints accept two query parameters: `limit`, which defaults to 10 and must be at least 1 and at most 100, and `offset`, which defaults to 0 and must be at least 0. A non-integer value for either parameter, or a value outside these bounds, is rejected with `ERR_INVALID_REQUEST` (400). List responses are always sorted by `created_at` in ascending order, oldest first. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Logical Clock, Dates, and Units of Measure

All time-sensitive rules in this platform read a server-side logical clock, never wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it advances only when a `FarmManager` invokes the admin-only clock-setting capability with a target instant supplied as `to_iso8601` (an ISO 8601 UTC timestamp); the response body reports the new reading as `current_utc`. Window hours, the open-day date match, weather-refund tiers, and field rest sweeps all evaluate against this clock.

Calendar dates — season boundaries, sales days, window dates, booking dates — are ISO calendar dates in `YYYY-MM-DD` form, and date ranges in this document are inclusive at both ends. Times of day are `HH:MM` strings on the 24-hour UTC clock. All money is integer cents; all weights are integer ounces; sixteen ounces make one pound; and every picking container issued at the gate tares at exactly 4 ounces. Whenever a multiplication-and-division pair would produce a fractional cent, the result is rounded half up — a fractional remainder of exactly one half rounds away from zero. Rates expressed in basis points are divided by ten thousand when applied: ten thousand basis points is the identity multiplier, twelve thousand five hundred basis points is a 1.25x multiplier, and one thousand basis points is ten percent.

### 2.5. Common Resource Properties and Derived-Field Consistency

Every resource in this API carries four common properties. `id` is a server-minted UUID with no type prefix; identifiers never participate in any business decision, and wherever a selector or tie-break is needed the platform uses `created_at` instead. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. `updated_at` is the same timestamp format, refreshed on every mutation of the resource. `version` is an integer that increments by one on every mutation of the resource.

Derived fields — harvest tallies, booked slot and parking aggregates, payment and refund totals, session charges — are never cached stale: each is recomputed immediately inside the mutating request that affects it, so any read after a successful write observes the post-write state.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each naming a parent entity whose `version` the caller must prove it has observed.

Creating a pricing policy supersedes the season's current `ACTIVE` policy, and that supersession itself advances the season's `version` by one. A policy-creation request must therefore carry `expected_season_version` equal to the target season's current `version`; since versions only ever increase, the observable mismatch is a value below the current one, meaning the caller priced against a policy configuration it never observed. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Editing a field's `rotation_order` or `estimated_harvest_oz` is legitimate at any time, but every weigh-out creation, finalization, or void on that field legitimately advances the field's `version` through the harvest-tally side effects, so a caller's view of the tallies may be older than the field's actual state. A field-edit request must carry `expected_field_version` equal to the field's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these two accepts a version field.

### 2.7. Validation Pipeline and Error Precedence

Every request passes through an ordered validation pipeline, and the first failing gate wins — its error is the one returned, even if a later gate would also have failed. The gates, in evaluation order:

1. **Authentication** — the header check of §2.1 (`ERR_UNAUTHENTICATED`, 401), applied to every endpoint except waiver signing.
2. **Authorization** — the acting role must appear in the endpoint's role list (`ERR_FORBIDDEN`, 403), applied to every endpoint.
3. **Path identity resolution** — path-template identifiers are resolved left to right (season before field before window, and so on); an unresolvable path id yields `ERR_NOT_FOUND` (404).
4. **Request shape** — required fields are present, types are correct, enum values are in range, no undeclared fields appear, `close_time` is strictly after `open_time`, `party_size` is at least 1, `amount_cents` is greater than zero, and a batch's `sequence_index` values are unique within the batch with a known `record_type` and a non-empty `records` array. Violations yield `ERR_INVALID_REQUEST` (400).
5. **Body foreign keys** — identifiers carried in the request body (`season_id`, `field_id`, `window_id`, `waiver_id`, `session_id`, `crop_id`, `addon_product_id`) must resolve to existing resources, else `ERR_NOT_FOUND` (404).
6. **Own-state legality** — the addressed resource's own state must permit the requested transition: opening an already `OPEN`, `PICKED_OUT`, or `RETIRED` field, checking out a `CHECKED_OUT` session, manually voiding a harvest line whose session is `CHECKED_OUT`, redeeming a `RELEASED` booking, or manually cancelling a window that is not `SCHEDULED` or that still has bookings all fail here with `ERR_INVALID_STATE` (409). Finalizing a harvest line that is not `PROVISIONAL` fails at this same tier with its dedicated code `ERR_LINE_NOT_PROVISIONAL` (409).
7. **Optimistic concurrency** — the `expected_season_version` or `expected_field_version` gate of §2.6 (`ERR_STALE_VERSION`, 412).
8. **Season-active gate** — operations that require an `ACTIVE` season (field open, sales-day open-day, window creation, window open, session creation) fail with `ERR_SEASON_NOT_ACTIVE` (409).
9. **Waiver trio** — evaluated in this exact relative order: the waiver's stored status must be `SIGNED` (`ERR_WAIVER_VOIDED`, 422); then its `waiver_version_signed` must equal the season's `current_waiver_version` (`ERR_WAIVER_STALE`, 422); then the waiver's `party_member_names` must list at least as many names as the session's `party_size` (`ERR_WAIVER_PARTY_MISMATCH`, 422). These three checks guard session creation, enter-field, and offline session application.
10. **Temporal rules** — sales-day uniqueness and date range on sales-day creation (a duplicate date for the season yields `ERR_SALES_DAY_EXISTS` 409; a date outside the season's inclusive range yields `ERR_DATE_OUTSIDE_SEASON` 422); window date within the field's season range (`ERR_DATE_OUTSIDE_SEASON`, 422); non-overlap of windows (`ERR_WINDOW_OVERLAP`, 422); the field-rest check on field open (`ERR_FIELD_RESTING`, 422); the logical clock lying within the action's time window (`ERR_OUTSIDE_WINDOW_HOURS`, 422); and the existence of an `ACTIVE` pricing policy to pin at session creation (`ERR_NO_ACTIVE_POLICY`, 409).
11. **Capacity and quantity constraints** — window slot capacity (`ERR_WINDOW_CAPACITY_FULL`, 422), parking capacity (`ERR_PARKING_FULL`, 422), staffing sufficiency (`ERR_INSUFFICIENT_STAFFING`, 422), add-on slot capacity (`ERR_ADDON_SLOT_FULL`, 422), field depletion (`ERR_FIELD_DEPLETED`, 422), tare not exceeding gross weight (`ERR_TARE_EXCEEDS_GROSS`, 422), and no unresolved provisional lines at checkout (`ERR_UNRESOLVED_LINES`, 422).
12. **Cross-resource state** — operations that read the state of a resource other than the one addressed: the window must be `OPEN` for session creation and enter-field (`ERR_WINDOW_NOT_OPEN`, 409); the field must be `OPEN` for enter-field and for harvest-line creation and finalization (`ERR_FIELD_NOT_OPEN`, 409); the sales day must be `OPEN` for session creation (`ERR_DAY_NOT_OPEN`, 409); the session must be `FIELD_ACTIVE` for harvest-line creation, and in `CHECKED_IN` or `FIELD_ACTIVE` for payment collection and add-on booking creation (`ERR_SESSION_NOT_ACTIVE`, 409); and a redemption requires the session on-site and the clock date equal to the booking date (`ERR_BOOKING_NOT_REDEEMABLE`, 409).
13. **Cross-scope referential integrity** — referenced entities must belong to one season scope (`ERR_CROSS_SCOPE_REFERENCE`, 422), guarding harvest-line creation and add-on booking creation.
14. **Fiscal rules** — payment amount sanity (`ERR_PAYMENT_AMOUNT_INVALID`, 422), refund cap (`ERR_REFUND_EXCEEDS_PAID`, 422), and the balance gates on enter-field and checkout (`ERR_UNPAID_BALANCE`, 422).

## 3. Business Logic & Workflows

### 3.1. Season Setup, Waiver Lifecycle, and Pricing Policy

A `FarmManager` begins a harvest year by creating a season: a display `name` such as "2026 Harvest", a `start_date` and an `end_date` (both ISO calendar dates, both inclusive, and `end_date` must not fall before `start_date` — a violation yields `ERR_INVALID_REQUEST`, 400), and the `waiver_text` that guests will sign. A new season is born in `DRAFT` status with `current_waiver_version` set to 1. Activation moves the season from `DRAFT` to `ACTIVE` — activating a season in any other status is `ERR_INVALID_STATE` (409); at most one season may be `ACTIVE` at any time, so activation while another season is currently `ACTIVE` is rejected as a conflict, likewise `ERR_INVALID_STATE` (409). The active season becomes the operative season for every season-gating check in the platform (`ERR_SEASON_NOT_ACTIVE` wherever §2.7 requires one). Archiving moves an `ACTIVE` season to the terminal `ARCHIVED` status, and is permitted only when every field of the season rests in `RETIRED`, `DORMANT`, or `ROTATION_REST` and no sales day of the season is `OPEN`; an archive request that violates either condition — or that targets a season not currently `ACTIVE` — is rejected with `ERR_INVALID_STATE` (409).

Waiver text evolves through the season-configuration capability. When a `FarmManager` submits a `waiver_text` that differs from the current text, `current_waiver_version` increases by exactly one; the same capability may also rename the season's `name`. A config request carrying neither `waiver_text` nor `name` is `ERR_INVALID_REQUEST` (400), and resubmitting a `waiver_text` identical to the current text leaves `current_waiver_version` unchanged. Staleness is deliberately never stored on a waiver row: a waiver is stale whenever its `waiver_version_signed` differs from the season's `current_waiver_version`, so bumping the waiver text instantly ages every previously signed waiver by comparison alone, without touching any waiver record.

Waivers themselves are born at the public signing kiosk, the one endpoint that needs no authentication headers. An `Anonymous` signer supplies `season_id`, `signer_name`, `signer_email`, and `party_member_names` — the names of every party member the waiver covers, including the signer. The `signer_email` doubles as the lookup key offline devices use to find a waiver, and the waiver list can be filtered by `season_id` or `signer_email`. A new waiver is `SIGNED` and pins `waiver_version_signed` to the season's `current_waiver_version` at signing time. The only stored status change a waiver ever undergoes is voiding: a `FarmManager` may void a signed waiver, moving it from `SIGNED` to the terminal `VOIDED`.

Each season prices itself through a chain of pricing policies. A policy carries `admission_per_person_cents` (zero or more), `container_fee_cents` (zero or more), `weekend_surge_bps` (at least ten thousand — the surge multiplies only the admission component on weekend sales days), `bundle_discount_bps` (zero or more), and `bundle_cap_cents` (zero or more). The first policy created for a season takes `policy_version` 1 and status `ACTIVE`. Creating a further policy for the same season supersedes the incumbent: the old policy becomes `SUPERSEDED` (terminal), the new one becomes `ACTIVE` with a `policy_version` one higher than its predecessor's, and the season's `version` increments by one because supersession is a mutation of the season. Exactly one policy per season is `ACTIVE` at any moment. Existing visit sessions keep their pinned `pricing_policy_id` — a policy change never re-prices a session already admitted. Because supersession advances the season's version, policy creation is the first of the two concurrency-guarded writes of §2.6 and must carry `expected_season_version`. Policies may be listed with `season_id` and `status` filters.

### 3.2. Crops, Fields, Rotation, and Harvest Tallies

With a season in place, the manager registers what grows where. A crop is registered with `season_id`, `name` (for example "Strawberry"), and `price_per_lb_cents`, a strictly positive integer number of cents per pound; its `season_picked_oz` tally starts at zero. The crop list is filterable by `season_id`. A field is registered with `season_id`, `name`, `rotation_group`, `rotation_order`, and `estimated_harvest_oz` — the estimated total pickable ounces before the field is picked out, strictly positive. The `rotation_group` names a rotation pool, and `rotation_order` (zero or greater) ranks fields within that pool, lower ranks rotating in first. A new field starts `DORMANT` with `committed_picked_oz` at zero and `projected_remaining_oz` equal to its `estimated_harvest_oz` (no lines count against it yet); from then on the two tallies are recomputed immediately inside every mutating request that touches the field's harvest lines, per the formulas below. The field list can be filtered by `season_id`, `rotation_group`, `status`, or `rotation_successor_field_id`.

Two harvest tallies ride on every field, and they answer different questions on purpose. `committed_picked_oz` is the sum of `net_oz` over the field's `FINALIZED` harvest lines only — verified weight, the basis that decides picking-out. `projected_remaining_oz` is the field's `estimated_harvest_oz` minus the sum of `net_oz` over lines in either `PROVISIONAL` or `FINALIZED` status; it is the forward-looking basis and may go negative, since unverified offline weight is counted against the field before anyone has confirmed it. The same crop-level mirror, `season_picked_oz`, accumulates `net_oz` over `FINALIZED` lines across the whole season for that crop.

Opening a field moves it from `DORMANT` to `OPEN`. The season of the field must be `ACTIVE` (`ERR_SEASON_NOT_ACTIVE`), and the field must not be resting: `rest_until` must be null or earlier than the logical clock's current date. Attempting to open a field that is currently in `ROTATION_REST` therefore fails with the temporal `ERR_FIELD_RESTING` (422) rather than a state error, because rest is a time-bound condition; attempting to open a field already `OPEN`, `PICKED_OUT`, or `RETIRED` instead fails with `ERR_INVALID_STATE` (409). A `FarmManager` may also edit a field's `rotation_order` or `estimated_harvest_oz` at any time through the concurrency-guarded field edit of §2.6, which requires `expected_field_version` and increments the field's `version` by one.

Picking-out is automatic. The moment a weigh-out creation or finalization pushes a field's `committed_picked_oz` to equal or exceed its `estimated_harvest_oz`, the field transitions from `OPEN` to `PICKED_OUT` — the triggering line has already updated the tallies — and a cascade fires. Every `SCHEDULED` window of that field is cancelled with `cancel_reason` `DEPLETED`; windows of past dates are untouched, and today's `OPEN` window stays `OPEN` as a grace so on-site sessions can finish picking and weigh out. A `DEPLETED` cancellation processes no sessions, because a `SCHEDULED` window has none. At the same instant the field pins its `rotation_successor_field_id`: among fields sharing the same `season_id` and `rotation_group` that are `DORMANT` and whose `rest_until` is null or not later than the current date, the successor is the field with the lowest `rotation_order`, ties broken by earlier `created_at`; if no field qualifies, `rotation_successor_field_id` stays null.

Rest is enforced by the daily sweeps of §3.8. When a sales day closes normally, every `PICKED_OUT` field of the season moves to `ROTATION_REST` with `rest_until` set to the sales day's `date` plus seven days. When a later sales day is opened, every field of that season in `ROTATION_REST` whose `rest_until` is on or before the opened day's `date` — the comparison is inclusive — returns to `DORMANT` and its `rest_until` is cleared to null. Retirement is the manual end of the line: a `FarmManager` may retire a field from `DORMANT`, `OPEN`, `PICKED_OUT`, or `ROTATION_REST` into the terminal `RETIRED` status, but only when no window of the field is in `SCHEDULED` or `OPEN`.

### 3.3. Sales Days, Picking Windows, and the Availability Calendar

A sales day is planned per season with `season_id`, a `date` that must be unique within the season (`ERR_SALES_DAY_EXISTS`, 409) and must fall inside the season's inclusive range (`ERR_DATE_OUTSIDE_SEASON`, 422), a `day_type` of `WEEKDAY` or `WEEKEND` that drives surge pricing, a `parking_capacity` (zero or more), and a `staff_on_duty` headcount (zero or more) that gates how much picking capacity may be scheduled. A new sales day is `PLANNED` with `booked_parking` and `revenue_cents` at zero. Sales days can be listed with `season_id`, `date`, and `status` filters.

Opening the day moves it from `PLANNED` to `OPEN` and is allowed only when the season is `ACTIVE` and the logical clock's date equals the sales day's `date` exactly (`ERR_OUTSIDE_WINDOW_HOURS`, 422). The open runs the rotation sweep of §3.2, returning rested fields to `DORMANT`.

Within an open day, picking happens in windows. Scheduling a window takes `field_id`, a `date` within the field's season range (`ERR_DATE_OUTSIDE_SEASON`), `open_time` and `close_time` in `HH:MM` UTC with `close_time` strictly after `open_time`, and `picking_capacity_slots`, the maximum number of picker admissions — measured as the sum of `party_size` — the window accepts, strictly positive. Two windows on the same field and date may not overlap: their half-open intervals, each running from its `open_time` up to but not including its `close_time`, must not intersect, though back-to-back adjacency where one window's `close_time` equals the other's `open_time` is allowed; only non-`CANCELLED` windows participate, and a violation is `ERR_WINDOW_OVERLAP` (422). Scheduling is also staffing-gated: the required staff for a date is the total `picking_capacity_slots` over all non-`CANCELLED` windows of that date — including the window being created — divided by 25 slots per staff member and rounded up to a whole number, and creation is rejected with `ERR_INSUFFICIENT_STAFFING` (422) when the sales day's `staff_on_duty` is below that requirement. The boundary divides evenly: a date carrying exactly 50 slots requires exactly 2 staff. The staffing gate applies only when a sales day exists for the window's date; a window scheduled for a date with no sales day faces no staffing check. A new window starts `SCHEDULED` with `booked_slots` at zero; windows can be listed with `field_id`, `date`, and `status` filters.

A `FarmManager` opens a `SCHEDULED` window when three conditions hold, and they are evaluated in this order: the window's field is `OPEN` (`ERR_FIELD_NOT_OPEN`), the sales day of the window's `date` is `OPEN` (`ERR_DAY_NOT_OPEN`), and the logical clock reads within the window's hours — on the window's `date`, at or after `open_time` and strictly before `close_time` (`ERR_OUTSIDE_WINDOW_HOURS`). A window may instead be cancelled manually, which requires it to still be `SCHEDULED` and to have `booked_slots` of zero — either violation is `ERR_INVALID_STATE` (409) — and lands the window in `CANCELLED` with `cancel_reason` `MANUAL`. Windows also leave `SCHEDULED` or `OPEN` for `CANCELLED` through the system triggers of §3.2 and §3.8, with `cancel_reason` `DEPLETED` or `WEATHER` respectively; `cancel_reason` is null unless the window is `CANCELLED`.

Two aggregates keep capacity honest throughout the day. A window's `booked_slots` is the sum of `party_size` over the window's sessions whose `visit_status` is neither `CANCELLED` nor `VOIDED`. A sales day's `booked_parking` applies the same inclusion set across `parking_spaces` on every window of that date, and its `revenue_cents` is the sum over all sessions on the day's windows of each session's `total_paid_cents` minus its `total_refunded_cents`. For guests and staff planning a visit, the availability calendar reads every non-`CANCELLED` window between `from_date` and `to_date` inclusive — both are required query parameters in `YYYY-MM-DD` form, and a missing or malformed value is `ERR_INVALID_REQUEST` (400) — optionally narrowed by a `field_id` filter — and returns a non-paginated object envelope whose `rows` array carries one entry per window, ordered by `date`, then `open_time`, then `created_at` ascending: `date`, `window_id`, `field_id`, `field_name`, `field_status`, `window_status`, `open_time`, `close_time`, `picking_capacity_slots`, `booked_slots`, and `projected_remaining_oz`.

### 3.4. Gate Admission: Party Check-In and Capacity Gates

Admission starts at the front gate, where `GateStaff` (or a `FarmManager`) create a visit session with `window_id`, `waiver_id`, `party_size` (at least 1), `container_count` of picking containers issued (zero or more), `parking_spaces` reserved for the day (zero or more), and `origin`, which must be `ONLINE` at the gate — any other `origin` value here is rejected with `ERR_INVALID_REQUEST`, since `OFFLINE` sessions come into existence only through the batch channel of §3.9. Session lists can be filtered by `window_id`, `waiver_id`, `pricing_policy_id`, or `visit_status`.

Creation walks the §2.7 pipeline, and the business gates fire in this order. The season must be `ACTIVE` (`ERR_SEASON_NOT_ACTIVE`); the waiver trio runs in its fixed order (`ERR_WAIVER_VOIDED`, then `ERR_WAIVER_STALE`, then `ERR_WAIVER_PARTY_MISMATCH`, where the last requires the waiver's `party_member_names` to list at least `party_size` names); the season must have an `ACTIVE` pricing policy to pin (`ERR_NO_ACTIVE_POLICY`); the window's `booked_slots` plus the arriving `party_size` must not exceed `picking_capacity_slots` (`ERR_WINDOW_CAPACITY_FULL`), with equality exactly filling the window and succeeding; the day's `booked_parking` plus `parking_spaces` must not exceed `parking_capacity` (`ERR_PARKING_FULL`); and the window's field must not be projected-picked-out — its `projected_remaining_oz` must be greater than zero (`ERR_FIELD_DEPLETED`), which is why provisional offline weight counts against the field before verification. The cross-resource state checks then confirm the window is `OPEN` (`ERR_WINDOW_NOT_OPEN`) and the sales day is `OPEN` (`ERR_DAY_NOT_OPEN`).

On success the new session is `CHECKED_IN` with `payment_status` `UNPAID`, its `pricing_policy_id` pinned to the season's `ACTIVE` policy at creation, and its `admission_charge_cents` computed once and never recomputed afterwards. The admission charge is the sum of two components: the admission component, which is the pinned policy's `admission_per_person_cents` multiplied by `party_size` and then — only when the sales day's `day_type` is `WEEKEND` — multiplied by `weekend_surge_bps` divided by ten thousand with round-half-up to whole cents applied at that surge multiplication only; and the container component, which is `container_fee_cents` multiplied by `container_count`. Two computed money fields stay zero until life-cycle events move them: `bundle_discount_cents` (set at checkout) and the payment totals `total_paid_cents` and `total_refunded_cents`; `final_total_cents` and `checkout_mode` stay null until checkout, and `sync_outcome` stays null for any `ONLINE` session.

Entering the field moves the session from `CHECKED_IN` to `FIELD_ACTIVE` and is a `FieldStaff` duty. The window must still be `OPEN` (`ERR_WINDOW_NOT_OPEN`), its field must be `OPEN` (`ERR_FIELD_NOT_OPEN`), the waiver trio runs again in the same fixed order, and the party must have paid for admission: the session's `total_paid_cents` minus `total_refunded_cents` must be at least `admission_charge_cents` (`ERR_UNPAID_BALANCE`).

A party that never enters the field can be cancelled by `GateStaff`: cancellation moves a `CHECKED_IN` session to `CANCELLED`, releases its `party_size` and `parking_spaces` from the window and day aggregates, releases every `BOOKED` add-on booking of the session to `RELEASED`, and auto-refunds the full net paid amount to the session's `SETTLED` charge payments oldest first.

Two status dimensions ride on every session row in parallel. `visit_status` (`CHECKED_IN`, `FIELD_ACTIVE`, `CHECKED_OUT`, `CANCELLED`, `VOIDED`) tracks where the party is; `payment_status` (`UNPAID`, `PARTIALLY_PAID`, `PAID`, `PARTIALLY_REFUNDED`, `REFUNDED`) tracks the money. Neither dimension directly mutates the other — only payment and refund writes, and the checkout and weather calculations, move `payment_status`, and only the visit transitions move `visit_status`.

### 3.5. Field Weigh-Out and Harvest Lines

When a party finishes picking, `FieldStaff` weigh the harvest. A weigh-out names `session_id`, `crop_id`, `gross_weight_oz` from the scale (zero or more), and `container_count`, the number of containers used for this line and therefore the tare basis. The session must be `FIELD_ACTIVE` (`ERR_SESSION_NOT_ACTIVE`), the field must be `OPEN` (`ERR_FIELD_NOT_OPEN`), and the crop must belong to the same season as the field, the window, and the session (`ERR_CROSS_SCOPE_REFERENCE`, 422). The line's `field_id` is not supplied by the caller; it is denormalized from the session's window at creation. A line created online by staff is a staff-attested weigh-out and is born directly in `FINALIZED` status; offline-uploaded lines arrive as `PROVISIONAL` and must be verified later. Harvest lines can be listed with `session_id`, `field_id`, `crop_id`, and `status` filters.

Each line computes three values independently. `tare_oz` is `container_count` multiplied by 4 ounces per container. `net_oz` is `gross_weight_oz` minus `tare_oz`; a negative result is impossible to accept and the create is rejected with `ERR_TARE_EXCEEDS_GROSS` (422), while exactly zero is legal. `line_charge_cents` is `net_oz` multiplied by the crop's `price_per_lb_cents` and divided by 16 ounces per pound, rounded half up to whole cents. A session's weigh-out total is the sum of `line_charge_cents` over its `FINALIZED` lines only — `PROVISIONAL` and `VOIDED` lines are excluded — and the rounding order is pinned: round each line first, then sum the already-rounded line charges. Summing first and rounding once is the forbidden alternative, because it produces different cents: two one-ounce lines at 310 cents per pound round to 19 cents each and total 38 cents per line, whereas rounding the combined 38.75 cents once would yield 39.

Every line creation or finalization immediately feeds the tallies of §3.2: the field's `committed_picked_oz` and the crop's `season_picked_oz` each increase by the line's `net_oz`, the `version` of both field and crop increments, `projected_remaining_oz` recomputes, and if the field's committed tally now equals or exceeds its `estimated_harvest_oz` the `PICKED_OUT` cascade fires as described there.

Finalization is how an offline-uploaded `PROVISIONAL` line becomes real: `FieldStaff` verify it, which requires the line's session to be `FIELD_ACTIVE` (`ERR_SESSION_NOT_ACTIVE`) and the line's field to be `OPEN` (`ERR_FIELD_NOT_OPEN`); a line that is not `PROVISIONAL` cannot be finalized and the attempt is rejected with `ERR_LINE_NOT_PROVISIONAL` (409). A successful finalize applies exactly the same tally side effects as a fresh online line, cascade included.

Voiding moves a line from `PROVISIONAL` or `FINALIZED` to the terminal `VOIDED`. A manual void by `FieldStaff` requires the line's session to be anything other than `CHECKED_OUT` (`ERR_INVALID_STATE` if it is); the system also voids lines during weather force-checkout and offline sync voids. When a `FINALIZED` line is voided, its `net_oz` is subtracted back out of the field's `committed_picked_oz` and the crop's `season_picked_oz` as a compensating reversal; `projected_remaining_oz` recomputes in all cases, voided provisional weight included.

### 3.6. Agritourism Add-Ons: Products, Bookings, and Redemption

Beyond picking, the farm sells experiences. An add-on product is created with `season_id`, a `kind` of `WAGON_RIDE` or `CAFE_VOUCHER`, a display `name`, a `price_cents` per booked unit (zero or more), and a `slot_capacity` (strictly positive) bounding the total quantity bookable per product, date, and slot time. Products can be listed with `season_id` and `kind` filters.

`GateStaff` book add-on units against an on-site session by supplying `session_id`, `addon_product_id`, `booking_date`, `slot_time` (the `HH:MM` UTC start of the slot), and `qty` (at least 1). The session's `visit_status` must be `CHECKED_IN` or `FIELD_ACTIVE` (`ERR_SESSION_NOT_ACTIVE`), the product must belong to the session's season and the `booking_date` must equal the date of the session's window (`ERR_CROSS_SCOPE_REFERENCE`, 422), and the slot must have room: the sum of `qty` over bookings sharing the same `addon_product_id`, `booking_date`, and `slot_time` in `BOOKED` or `REDEEMED` status, plus the new `qty`, must not exceed the product's `slot_capacity` — equality exactly fills the slot and succeeds, and overflow is `ERR_ADDON_SLOT_FULL` (422). A new booking is `BOOKED` with `booked_value_cents` pinned at creation as the product's `price_cents` multiplied by `qty`. Bookings can be listed with `session_id`, `addon_product_id`, `booking_date`, and `status` filters.

Redemption is a `FieldStaff` action on the day itself: a `BOOKED` booking becomes `REDEEMED` only while its session's `visit_status` is `CHECKED_IN` or `FIELD_ACTIVE` and the logical clock's date equals the booking's `booking_date`; either failure is `ERR_BOOKING_NOT_REDEEMABLE` (409). Release frees the slot. A manual release by `GateStaff` or a `FarmManager` moves a `BOOKED` booking to `RELEASED`, frees its `qty` from the slot pool, and refunds its `booked_value_cents` at face value into the session's ledger by incrementing `refunded_amount_cents` on the session's `SETTLED` charge payments oldest first. The system releases bookings too — on session checkout, cancellation, or void, and during a weather closure for every `BOOKED` booking whose `booking_date` matches the closure date — and the weather release refunds face value the same way, even when the booking's session has already checked out. Only the manual release and the weather release refund face value. The checkout-time, cancellation-time, and void-time releases refund nothing at release time: the checkout-time release because that value was never charged, the cancellation-time release because the full net-paid auto-refund of §3.4 immediately follows and subsumes any booking value actually paid, and the void-time release because a voided session owes no one anything (§3.9).

### 3.7. Payments, Checkout Settlement, and Refunds

Money enters through a single charge-and-refund ledger. A payment carries `session_id`, a `kind` that in this version is always `CHARGE` — refunds are never separate rows; every refund, whether manual, weather-driven, a checkout overpayment, a cancellation, or an add-on release, is recorded by incrementing `refunded_amount_cents` on existing settled charge payments — those in `SETTLED` or `PARTIALLY_REFUNDED` status that still carry an unrefunded remainder — in `created_at` ascending order, and every reference in this document to refunding a session's `SETTLED` charge payments oldest first names this same mechanic — a `method` of `CASH`, `CARD`, or `OFFLINE_CARD`, an `amount_cents` strictly greater than zero, and an `idempotency_key`. The key is unique per session among charge payments, and replaying a key that session has already used returns the original payment instead of creating a duplicate — the replay short-circuits every later gate (no session-state or amount check runs) and responds with HTTP 201 carrying the original payment. The session's `visit_status` must be `CHECKED_IN` or `FIELD_ACTIVE` (`ERR_SESSION_NOT_ACTIVE`). Payments can be listed with `session_id` and `status` filters.

Collection is sanity-checked against what the session could still owe: `amount_cents` must not exceed the session's outstanding obligation, defined as `admission_charge_cents` plus the sum of `line_charge_cents` over the session's `FINALIZED` harvest lines plus the sum of `booked_value_cents` over the session's `BOOKED` and `REDEEMED` add-on bookings, minus the session's net collected amount (`total_paid_cents` minus `total_refunded_cents`). `PROVISIONAL` and `VOIDED` lines, `RELEASED` bookings, and any bundle discount are deliberately excluded from that obligation; an over-collection is rejected with `ERR_PAYMENT_AMOUNT_INVALID` (422).

Settlement timing depends on the method. A new payment starts `PENDING`; `CASH` and online `CARD` settle immediately, while `OFFLINE_CARD` settles when its offline batch is applied. Settling adds `amount_cents` to the session's `total_paid_cents`, recomputes the sales day's `revenue_cents`, and recomputes the session's `payment_status`. A batch-applied payment instead moves from `PENDING` to `FAILED` when its session has been voided or its record carries a conflict outcome; failed payments are never collected and contribute nothing to any total.

The `payment_status` of a session is derived from its ledger after every payment or refund write, evaluating the following branches in order and taking the first that matches: if `total_paid_cents` is zero, the session is `UNPAID`; otherwise, if `total_refunded_cents` is greater than or equal to `total_paid_cents` (which here means something was paid and then fully returned), the session is `REFUNDED`; otherwise, if `total_refunded_cents` is greater than zero, it is `PARTIALLY_REFUNDED`; otherwise, if checkout has pinned `final_total_cents` and the net paid (`total_paid_cents` minus `total_refunded_cents`) covers it, the session is `PAID`; otherwise, if checkout has not happened and the net paid covers `admission_charge_cents`, it is likewise `PAID`; in every remaining case it is `PARTIALLY_PAID`. The two totals behind this derivation are the sum of `amount_cents` over the session's settled charge payments — those in `SETTLED`, `PARTIALLY_REFUNDED`, or `REFUNDED` status — for `total_paid_cents`, and the sum of `refunded_amount_cents` over all of the session's charge payments for `total_refunded_cents`.

Checkout is the `FieldStaff` close of a visit, moving a session from `CHECKED_IN` or `FIELD_ACTIVE` to `CHECKED_OUT` with `checkout_mode` `NORMAL`. Two gates guard it: no harvest line of the session may still be `PROVISIONAL` (`ERR_UNRESOLVED_LINES`, 422), and the net paid must cover the computed `final_total_cents` (`ERR_UNPAID_BALANCE`, 422). Settlement runs in a pinned evaluation order, because a phrase like "ten percent off the day" is circular without one. First, the add-on total is the sum of `booked_value_cents` over the session's `REDEEMED` bookings. Second, the discount base is `admission_charge_cents` plus that add-on total — harvest charges are excluded from the base. Third, `bundle_discount_cents` is zero unless the session holds at least one `REDEEMED` `WAGON_RIDE` booking and at least one `REDEEMED` `CAFE_VOUCHER` booking; with both present, the discount is the lesser of the policy's `bundle_cap_cents` and the policy's `bundle_discount_bps` multiplied by the discount base and divided by ten thousand, rounded half up to whole cents. Fourth, the harvest total is the weigh-out total of §3.5 over `FINALIZED` lines. Fifth and last, `final_total_cents` is `admission_charge_cents` plus the add-on total plus the harvest total minus `bundle_discount_cents`. Both pinned values are written to the session at this moment.

Checkout's side effects fan out from there. Every still-`BOOKED` add-on booking of the session is released to `RELEASED` without refund, as §3.6 describes. If the net paid exceeds the freshly pinned `final_total_cents`, the excess is auto-refunded to the session's `SETTLED` charge payments oldest first. And the sales day's `revenue_cents` together with the window and parking aggregates recompute.

Manual refunds are a `FarmManager`-only act against a `SETTLED` or `PARTIALLY_REFUNDED` charge payment; a payment in any other status cannot be refunded and the attempt is `ERR_INVALID_STATE` (409). The requested `amount_cents` must not exceed the payment's remaining unrefunded amount — its `amount_cents` minus its `refunded_amount_cents` — else `ERR_REFUND_EXCEEDS_PAID` (422). A refund smaller than the remainder leaves the payment `PARTIALLY_REFUNDED` with `refunded_amount_cents` increased by the refunded amount; a refund exactly equal to the remainder moves the payment to `REFUNDED` with `refunded_amount_cents` equal to its full `amount_cents`. Either way the session's `total_refunded_cents` and `payment_status` recompute, and when every obligation on the session has been refunded the session's `payment_status` becomes `REFUNDED`.

### 3.8. Weather Closure and End-of-Day Sweeps

Two very different endings await an `OPEN` sales day, both invoked by a `FarmManager`.

A normal close moves the day to `CLOSED_NORMAL` and runs three sweeps. Every session still on site — `visit_status` `CHECKED_IN` or `FIELD_ACTIVE` — is force-checked-out to `CHECKED_OUT` with `checkout_mode` `DAY_END_FORCED`: the checkout settlement of §3.7 still computes and pins `final_total_cents` and `bundle_discount_cents` for the record, any `PROVISIONAL` harvest lines of those sessions are voided to `VOIDED`, and no refund of any kind is owed or applied. Every `OPEN` window of the date closes to `CLOSED`. And every `PICKED_OUT` field of the season enters `ROTATION_REST` with `rest_until` set to the closing day's `date` plus seven days.

A weather closure moves the day to `CLOSED_WEATHER` and unfolds as a cascade of three hops. First, `closed_at_time` is pinned from the logical clock's current `HH:MM` UTC reading — it drives the refund tiers — and every window of the date in `SCHEDULED` or `OPEN` is cancelled with `cancel_reason` `WEATHER`. Second, each cancelled window force-checks-out its on-site sessions to `CHECKED_OUT` with `checkout_mode` `WEATHER_FORCED`; sessions already `CHECKED_OUT` keep their state. Third, each forced checkout voids the session's `PROVISIONAL` harvest lines and computes a weather refund applied to its `SETTLED` charge payments in `created_at` ascending order, and every `BOOKED` add-on booking whose `booking_date` equals the closure date is released to `RELEASED` with a face-value refund into its session's ledger — this last step applies even to bookings of sessions that had already checked out. After all refunds post, the day's `revenue_cents` recomputes.

The weather refund for a session is tiered by `closed_at_time`. A closure before 12:00 refunds one hundred percent of the admission component; a closure at or after 12:00 but before 15:00 refunds fifty percent; a closure at or after 15:00 refunds nothing. The admission component refunded against is the session's pinned `admission_charge_cents` excluding the container component — that is, `admission_charge_cents` minus the pinned policy's `container_fee_cents` multiplied by the session's `container_count` — and the tier percentage is applied to that basis and rounded half up to whole cents. The container component itself — `container_fee_cents` multiplied by `container_count` — is refunded in full only when the session has zero `FINALIZED` harvest lines, and not at all otherwise. The add-on portion is the sum of `booked_value_cents` over the session's `BOOKED` bookings dated on the closure date; `REDEEMED` bookings refund zero. The three portions sum to the session's weather refund, which is then applied to its `SETTLED` charge payments oldest first, each payment's `refunded_amount_cents` increased up to its remaining unrefunded amount. A hard cap applies across the whole operation: the total refund applied to a session never exceeds its net collected amount, and any excess is discarded — money is never created. Bundle discounts never enter this computation; the weather refund is defined by these tiers and portions alone, never by any checkout settlement figure. The refund is always computed from the session's pinned policy and its actual `admission_charge_cents` — the paid basis — and never repriced against the season's currently `ACTIVE` policy at closure time, even if the policy was superseded mid-day. For a weather-forced session the §3.7 settlement still computes and pins both `final_total_cents` and `bundle_discount_cents` for the record, but the refund is governed entirely by these weather rules, not by those figures.

### 3.9. Offline Devices, Batch Upload, and Sync Conflicts

Field-edge devices keep selling when the network drops, and reconcile by uploading a batch. A `KioskDevice` (or a `FarmManager`) submits a batch with `device_id`, a client-chosen `batch_id`, and a `records` array; the pair of `device_id` and `batch_id` is the idempotency key. The first upload decides the batch's fate permanently: replaying the same pair returns the stored batch with an identical `results` array and applies nothing a second time. Structural validation runs before the replay check, so a malformed upload fails with `ERR_INVALID_REQUEST` (400) even when its pair was seen before; a well-formed replay responds with HTTP 201 carrying the stored batch.

Structural validity is all-or-nothing. Each record carries a `record_type` of `VISIT_SESSION`, `PAYMENT`, or `HARVEST_LINE`, a `sequence_index` unique within the batch, an `offline_ref`, and a `payload`; the `records` array must be non-empty, every `record_type` known, and no `sequence_index` repeated. Any structural failure rejects the whole batch with `ERR_INVALID_REQUEST` (400) and persists nothing. A well-formed batch is then applied record by record in ascending `sequence_index` order, with the business gates of §2.7 evaluated at apply time. A record whose payload lacks a required field or carries a wrong-typed value is not a structural failure; the record applies as a `SYNC_CONFLICT` with a null `entity_id` and creates nothing.

A `VISIT_SESSION` record creates a session with `origin` `OFFLINE`, carrying the payload's `window_id`, `waiver_id`, `party_size`, `container_count`, `parking_spaces`, and crucially the payload's own `pricing_policy_id` — offline sessions grandfather the policy the device cached rather than the season's current `ACTIVE` one. The record's `offline_ref` and the uploading `device_id` are stored on the session, and `offline_ref` is globally unique across all sessions. The session's `admission_charge_cents` is computed with the same §3.4 formula against the payload's policy; when no sales day exists for the window's date the `WEEKEND` surge simply does not apply. The checks run in pipeline order: the window must exist, else the record is a `SYNC_CONFLICT` and no session is created; the window must not be `CANCELLED` with `cancel_reason` `WEATHER`, the waiver must be valid at apply time (signed, version-current, and covering the party per the trio of §2.7), the session must fit within the offline capacity allowance — the window's `picking_capacity_slots` plus an allowance of 10 extra slots — and the `offline_ref` must never have been seen on any session; each of those four failures creates the session directly in `VOIDED` with `sync_outcome` `SYNC_CONFLICT`. A fifth failure mode, evaluated last, joins them: a payload `pricing_policy_id` that resolves to no existing policy also lands the session in `VOIDED` with `sync_outcome` `SYNC_CONFLICT`, and with no policy to price it such a session's `admission_charge_cents` is 0. A clean application lands the session in `CHECKED_IN` with `payment_status` `UNPAID` and `sync_outcome` `APPLIED`. Voiding a session cascades exactly as §3.4's parallel-dimension rules imply: its `PROVISIONAL` harvest lines are voided, its `BOOKED` add-on bookings are released with no refund owed, and its `OFFLINE_CARD` payments settle to `FAILED` — never collected — so a voided session owes no one anything.

A `PAYMENT` record resolves its session through `session_ref`, which may match either a session's `offline_ref` or its server-minted `id`; its payload is a `method` of `OFFLINE_CARD` and an `amount_cents`. A `method` other than `OFFLINE_CARD`, or an `amount_cents` that is not a positive integer, conflicts with a null `entity_id`. An unknown `session_ref` conflicts; a session that landed `VOIDED` marks the payment `FAILED` and the record conflicts; otherwise the payment settles to `SETTLED` and the record applies. The record's `offline_ref` doubles as the new payment's `idempotency_key`, and when the resolved session already holds a charge payment under that key the record applies (`APPLIED`) against the original payment's id and no duplicate is created.

A `HARVEST_LINE` record likewise resolves its session through `session_ref` and carries `crop_id`, `gross_weight_oz`, and `container_count`. An unknown `session_ref`, a session that is not `FIELD_ACTIVE`, a duplicate line-level `offline_ref` — globally unique across harvest lines — an unknown `crop_id`, or a tare that exceeds the gross weight (a negative `net_oz`) each conflict, in every case with a null `entity_id` and no line created; otherwise the line is created in `PROVISIONAL` status with `tare_oz`, `net_oz`, and `line_charge_cents` computed exactly as §3.5 defines, and no field checks are applied at upload time — verification and the depletion cascade wait for the finalize of §3.5.

The batch row then summarizes itself. Each record contributes one entry to `results`, an array of `offline_ref`, an outcome of `APPLIED` or `SYNC_CONFLICT`, and the affected `entity_id` or null; `applied_count` and `conflict_count` tally the outcomes. A batch whose records all applied is `APPLIED`; any conflict makes it `PARTIALLY_APPLIED`. Batches are append-only and are never mutated after first upload.

## 4. Endpoint Definitions

All endpoints are mounted under the `/farm` prefix. Endpoints that create a new resource respond with HTTP 201; reads, modifications, and lifecycle or action endpoints respond with HTTP 200. Request payloads, side effects, and preconditions are specified by the narratives of §2 and §3 — this table is a navigational index of method, path, summary, and authorized roles only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /farm/seasons | Create a season (DRAFT) | FarmManager |
| GET | /farm/seasons/{id} | Get a season | FarmManager, GateStaff, FieldStaff, KioskDevice |
| POST | /farm/seasons/{id}/activate | Activate a DRAFT season; only one ACTIVE at a time | FarmManager |
| POST | /farm/seasons/{id}/archive | Archive an ACTIVE season (all fields retired/dormant/resting, no open day) | FarmManager |
| POST | /farm/seasons/{id}/config | Bump waiver text (and thereby current_waiver_version) and/or rename | FarmManager |
| POST | /farm/crops | Register a crop for a season | FarmManager |
| GET | /farm/crops/{id} | Get a crop | FarmManager, GateStaff, FieldStaff |
| GET | /farm/crops | List (created_at ASC) crops, filterable by season | FarmManager, GateStaff, FieldStaff |
| POST | /farm/fields | Create a field (DORMANT) | FarmManager |
| GET | /farm/fields/{id} | Get a field | FarmManager, GateStaff, FieldStaff |
| GET | /farm/fields | List (created_at ASC) fields, filterable | FarmManager, GateStaff, FieldStaff |
| PATCH | /farm/fields/{id} | Edit rotation_order / estimated_harvest_oz (OCC-guarded) | FarmManager |
| POST | /farm/fields/{id}/open | Open a DORMANT field for picking | FarmManager |
| POST | /farm/fields/{id}/retire | Retire a field (no SCHEDULED/OPEN windows) | FarmManager |
| POST | /farm/field-day-windows | Schedule a picking window (overlap, staffing, season-range validated) | FarmManager |
| GET | /farm/field-day-windows/{id} | Get a window | FarmManager, GateStaff, FieldStaff |
| GET | /farm/field-day-windows | List (created_at ASC) windows, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/field-day-windows/{id}/open | Open a SCHEDULED window (field OPEN, day OPEN, clock within hours) | FarmManager |
| POST | /farm/field-day-windows/{id}/cancel | Manually cancel a SCHEDULED window with zero bookings | FarmManager |
| POST | /farm/pricing-policies | Create a policy (supersedes the season's ACTIVE policy; OCC on Season.version) | FarmManager |
| GET | /farm/pricing-policies/{id} | Get a policy | FarmManager, GateStaff, FieldStaff |
| GET | /farm/pricing-policies | List (created_at ASC) policies, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/waivers | Public signing kiosk: sign the season's CURRENT waiver text | Anonymous |
| GET | /farm/waivers/{id} | Get a waiver | FarmManager, GateStaff |
| GET | /farm/waivers | List (created_at ASC) waivers, filterable | FarmManager, GateStaff |
| POST | /farm/waivers/{id}/void | Void a signed waiver | FarmManager |
| POST | /farm/visit-sessions | Admit a party at the gate (ONLINE origin only; pins ACTIVE policy; computes admission_charge_cents) | GateStaff, FarmManager |
| GET | /farm/visit-sessions/{id} | Get a session | FarmManager, GateStaff, FieldStaff, KioskDevice |
| GET | /farm/visit-sessions | List (created_at ASC) sessions, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/visit-sessions/{id}/enter-field | Mark party as entered the field | FieldStaff, FarmManager |
| POST | /farm/visit-sessions/{id}/checkout | Normal checkout: settle final_total, release unredeemed addons, auto-refund overpayment | FieldStaff, FarmManager |
| POST | /farm/visit-sessions/{id}/cancel | Cancel a CHECKED_IN session (full auto-refund) | GateStaff, FarmManager |
| POST | /farm/harvest-lines | Staff weigh-out at the field (creates FINALIZED line; updates tallies; may trigger PICKED_OUT cascade) | FieldStaff, FarmManager |
| GET | /farm/harvest-lines/{id} | Get a harvest line | FarmManager, FieldStaff |
| GET | /farm/harvest-lines | List (created_at ASC) harvest lines, filterable | FarmManager, FieldStaff |
| POST | /farm/harvest-lines/{id}/finalize | Verify a PROVISIONAL (offline-uploaded) line | FieldStaff, FarmManager |
| POST | /farm/harvest-lines/{id}/void | Void a line before its session checks out (reverses tallies if FINALIZED) | FieldStaff, FarmManager |
| POST | /farm/addon-products | Create an agritourism add-on (wagon ride / cafe voucher) | FarmManager |
| GET | /farm/addon-products/{id} | Get an add-on product | FarmManager, GateStaff, FieldStaff |
| GET | /farm/addon-products | List (created_at ASC) add-on products, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/addon-bookings | Book add-on units for a session (aggregate slot capacity enforced) | GateStaff, FarmManager |
| GET | /farm/addon-bookings/{id} | Get a booking | FarmManager, GateStaff, FieldStaff |
| GET | /farm/addon-bookings | List (created_at ASC) bookings, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/addon-bookings/{id}/redeem | Redeem a booking on its date while the session is on-site | FieldStaff, FarmManager |
| POST | /farm/addon-bookings/{id}/release | Manually release a BOOKED booking (face-value refund to the session ledger) | GateStaff, FarmManager |
| POST | /farm/payments | Collect a CHARGE payment (CASH/CARD settle immediately; idempotent per idempotency_key) | GateStaff, FieldStaff, FarmManager |
| GET | /farm/payments/{id} | Get a payment | FarmManager, GateStaff, FieldStaff |
| GET | /farm/payments | List (created_at ASC) payments, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/payments/{id}/refund | Refund against a SETTLED/PARTIALLY_REFUNDED CHARGE payment | FarmManager |
| POST | /farm/sales-days | Plan an operating day (unique per season+date) | FarmManager |
| GET | /farm/sales-days/{id} | Get a sales day | FarmManager, GateStaff, FieldStaff |
| GET | /farm/sales-days | List (created_at ASC) sales days, filterable | FarmManager, GateStaff, FieldStaff |
| POST | /farm/sales-days/{id}/open-day | Open the day (clock date must match; runs ROTATION_REST to DORMANT sweep) | FarmManager |
| POST | /farm/sales-days/{id}/close-day | Normal close: force DAY_END checkout of on-site sessions, close windows, sweep PICKED_OUT fields to ROTATION_REST | FarmManager |
| POST | /farm/sales-days/{id}/close-weather | Weather closure: cancels the day's windows, force-checks-out on-site sessions with tiered refunds, releases the day's BOOKED addons | FarmManager |
| POST | /farm/offline-batches | Upload an offline batch (idempotent per (device_id, batch_id)); records apply in sequence_index order | KioskDevice, FarmManager |
| GET | /farm/offline-batches/{id} | Get a batch with per-record results | KioskDevice, FarmManager |
| GET | /farm/availability-calendar | Crop availability calendar: one row per non-CANCELLED window in [from_date, to_date] | FarmManager, GateStaff, FieldStaff |
| POST | /farm/_clock/set_current_utc | Set the server's logical clock (ISO 8601 UTC) | FarmManager |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in the narratives of §2 and §3; this table indexes identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SEASON_NOT_ACTIVE | 409 |
| ERR_FIELD_NOT_OPEN | 409 |
| ERR_WINDOW_NOT_OPEN | 409 |
| ERR_SESSION_NOT_ACTIVE | 409 |
| ERR_LINE_NOT_PROVISIONAL | 409 |
| ERR_BOOKING_NOT_REDEEMABLE | 409 |
| ERR_DAY_NOT_OPEN | 409 |
| ERR_NO_ACTIVE_POLICY | 409 |
| ERR_SALES_DAY_EXISTS | 409 |
| ERR_WAIVER_VOIDED | 422 |
| ERR_WAIVER_STALE | 422 |
| ERR_WAIVER_PARTY_MISMATCH | 422 |
| ERR_WINDOW_OVERLAP | 422 |
| ERR_DATE_OUTSIDE_SEASON | 422 |
| ERR_FIELD_RESTING | 422 |
| ERR_OUTSIDE_WINDOW_HOURS | 422 |
| ERR_WINDOW_CAPACITY_FULL | 422 |
| ERR_PARKING_FULL | 422 |
| ERR_INSUFFICIENT_STAFFING | 422 |
| ERR_ADDON_SLOT_FULL | 422 |
| ERR_FIELD_DEPLETED | 422 |
| ERR_TARE_EXCEEDS_GROSS | 422 |
| ERR_UNRESOLVED_LINES | 422 |
| ERR_CROSS_SCOPE_REFERENCE | 422 |
| ERR_PAYMENT_AMOUNT_INVALID | 422 |
| ERR_REFUND_EXCEEDS_PAID | 422 |
| ERR_UNPAID_BALANCE | 422 |
