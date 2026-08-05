# Multifamily Amenity & Resident-Experience Platform API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a Multifamily Amenity & Resident-Experience Platform: a single system that a property-management company uses to run the day-to-day life of an apartment community. It brings amenity booking (gyms, pools, and clubrooms), community events, maintenance service requests and vendor coordination, package and guest-access handling, rent and payment tracking, and resident-satisfaction surveys under one coherent contract.

The platform's central tension is that many independent activities all touch the same resident's financial and behavioral posture. A gym reservation places a refundable deposit hold; a maintenance invoice adds to what the resident owes; a missed rent charge can silently suspend a future pool booking and release its hold; a payment can just as silently restore that booking. The API is therefore built around a small set of shared numeric quantities — a resident's owed balance, deposit holds, prepaid wallet credit, and a derived account posture — that every workflow reads from and writes to. Correctness means that these quantities always reconcile, that concurrent edits to a shared amenity schedule are detected rather than lost, and that the temporal windows governing bookings, guest passes, and events are enforced to the exact boundary.

All times are handled in UTC against a server-controlled logical clock rather than wall-clock time, so that temporal behavior is fully reproducible. Monetary amounts are expressed in whole integer cents throughout.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to invoke the target endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `PropertyManager`, `Resident`, `Vendor`, and `FrontDesk`.

- `PropertyManager` is an operator role. When `X-User-Role` is `PropertyManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — for example, it stores the acting manager's `X-User-ID` as `triaged_by_user_id` and later as `invoice_approved_by_user_id` on a `ServiceRequest` — but it never compares it to any entity's `id` for ownership.
- `FrontDesk` is likewise an opaque staff role: when `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque concierge identifier not tied to any persisted entity and is not compared to any entity's `id`.
- `Resident` is an entity-backed role. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks on any resource that references a resident (through its `resident_id`) compare that resource's resident foreign key to `X-User-ID`. A resident acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- `Vendor` is an entity-backed role. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on a service request compare its `vendor_id` to `X-User-ID`, and a vendor acting on a request assigned to a different vendor is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; a supplied value outside that range is a validation failure. The `offset` parameter defaults to 0 and has a minimum of 0. List results are ordered by `created_at` in ascending order (oldest first). Every list response reports `limit`, `offset`, `total_count` (the total number of matching resources before the page window is applied), and `has_more` (true when further resources remain beyond the current page) inside `meta`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Most resources also carry three managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, a timestamp of the same format refreshed on every mutation; and `version`, an integer that begins at 1 on creation and increments by one on each mutation that changes the resource.

Two resource kinds are deliberately lighter. A `LedgerEntry` and a `SurveyResponse` are immutable records: each carries only `id` and `created_at`. Neither `updated_at` nor `version` exists on those two — they are never mutated after creation, so no version or update timestamp is maintained for them.

Ordering that depends on creation time — most importantly waitlist promotion — relies on `created_at`, which is minted at microsecond precision and is the sole tie-break key; resource `id` is never used to order records.

**Optimistic Concurrency Control.** Creating an amenity booking is guarded against stale reads of the amenity it targets. A booking-creation request must carry `expected_amenity_version`, and the server compares it to the current `version` of the referenced `Amenity`. Every successful booking creation increments that amenity's `version` by one. If another writer has advanced the amenity's `version` since the client last read it, so that `expected_amenity_version` no longer equals the amenity's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from creating a booking against a schedule or configuration it has not observed; a second sequential creation that still carries the pre-increment version fails deterministically. No other endpoint accepts or requires a version field.

### 2.5. The Logical Clock and Temporal Windows

The system keeps a single logical clock in UTC. Before any clock is set, its value is `2026-05-01T00:00:00Z`, and it never falls back to real wall-clock time. An administrative capability lets an operator set the clock to a supplied instant (`to_iso8601`); all temporal preconditions — booking windows, check-in grace, guest-pass spans, package hold expiry, event start/end gating, and retention windows — are evaluated against this clock's current value, referred to throughout as the current time.

Amenity operating hours and peak windows are expressed as minutes from `00:00` UTC. A booking window is the half-open interval from `start_at` (inclusive) to `end_at` (exclusive); an amenity is occupied by a booking for exactly that interval. Guest-pass concurrency likewise treats `arrival_at` as an inclusive window start and `expected_departure_at` as an exclusive window end.

### 2.6. Monetary Precision, the Resident Ledger, and Balance Reconciliation

All money is stored and computed in whole integer cents. Wherever a formula produces a fractional cent, the result is rounded half up to the nearest whole cent. Where a calculation composes several rounded steps, each step is rounded at the point specified for it (for example, a gross amount is rounded before a discount is applied, and the discounted amount is rounded again before any cap); per-line rounding is always performed before lines are summed, never sum-then-round.

Each financially meaningful event appends a `LedgerEntry` for the affected resident. A ledger entry records the `resident_id`, an `entry_type`, a signed `amount_cents`, a `source_type` (a plain label naming the originating resource kind, such as `AmenityBooking`, `ServiceRequest`, `CommunityEvent`, or `Payment`), a `source_id` (a plain reference label to the originating resource, not a validated foreign key), and a human-readable `description`. The `entry_type` is one of `RENT_CHARGE`, `BOOKING_FEE`, `DEPOSIT_FORFEIT`, `EVENT_FEE`, `SERVICE_CHARGE`, `PENALTY`, `PAYMENT`, or `REFUND`. A positive `amount_cents` increases what the resident owes; a negative `amount_cents` decreases it.

A resident's `rent_balance_cents` is a derived quantity and must always equal the greater of zero and the sum of `amount_cents` over that resident's owed-affecting ledger entries — those whose `entry_type` is `RENT_CHARGE`, `BOOKING_FEE`, `DEPOSIT_FORFEIT`, `EVENT_FEE`, `SERVICE_CHARGE`, `PENALTY`, or `PAYMENT`. The balance is never negative and never below zero. `REFUND` entries are excluded from this sum: a refund credits the resident's `wallet_credit_cents` rather than reducing `rent_balance_cents`. It follows that a forward charge of some amount paired with a later compensating reversal of the same amount leaves `rent_balance_cents` unchanged. The `wallet_credit_cents` field accumulates prepaid credit that arises from refunds and from payment overflow (see §3.3); `hold_balance_cents` tracks the sum of currently active booking deposit holds that are not yet owed.

### 2.7. Account Posture and Privilege Gating

Every resident carries a derived `account_status`, one of `GOOD_STANDING`, `DELINQUENT`, or `SUSPENDED`, that gates their amenity and guest privileges. It is recomputed from `rent_balance_cents` immediately after any change to that balance — a rent charge, a payment, a booking fee, a penalty, a deposit forfeit, an event fee, or a service charge. The posture is determined by two thresholds, a delinquency threshold of 50000 cents and a suspension threshold of 150000 cents, each applied with a strict comparison: if the balance is strictly greater than 150000 cents the resident becomes `SUSPENDED`; otherwise, if the balance is strictly greater than 50000 cents the resident becomes `DELINQUENT`; otherwise the resident is `GOOD_STANDING`. A balance of exactly 50000 leaves the resident in `GOOD_STANDING`, and a balance of exactly 150000 leaves the resident `DELINQUENT`.

Because posture is recomputed on every balance change, a resident's status cycles freely among the three values as charges and payments accrue and clear. Crossing into a worse posture and recovering from it drive the booking cascades described in §3.3.

### 2.8. Validation Ordering and Error Precedence

When several checks could reject a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is:

1. **Authentication** — headers present and role recognized; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role may call this endpoint; otherwise `ERR_UNAUTHORIZED` (403).
3. **Body validation** — required fields present, correct types, valid enum members, numeric ranges honored (for a booking, `start_at` earlier than `end_at`; for a guest pass, `arrival_at` earlier than `expected_departure_at`; `satisfaction_score` between 1 and 5 inclusive; amounts strictly positive where required); otherwise `ERR_VALIDATION` (422).
4. **Existence** — every path `id` and every body foreign key resolves to an existing resource, checked left to right along the path; otherwise the resource-specific not-found error (404), such as `ERR_PROPERTY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_AMENITY_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_SERVICE_REQUEST_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_GUEST_PASS_NOT_FOUND`, or `ERR_SURVEY_NOT_FOUND`.
5. **Ownership** — an entity-backed `Resident` or `Vendor` acting on a resource must own it; otherwise `ERR_NOT_RESOURCE_OWNER` (403).
6. **Segregation of duties** — for invoice approval, the approving `X-User-ID` must differ from `triaged_by_user_id`; otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
7. **State** — the target resource is in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE` (409).
8. **Referential compatibility** — for vendor assignment the request's `trade` is a member of the vendor's `trades` (otherwise `ERR_VENDOR_TRADE_MISMATCH`, 422); for an event whose `amenity_id` is set, that amenity belongs to the event's `property_id` (otherwise `ERR_PROPERTY_MISMATCH`, 422); for package pickup the supplied code matches (otherwise `ERR_ACCESS_CODE_MISMATCH`, 422).
9. **Posture gate** — amenity bookings require `GOOD_STANDING` (a `DELINQUENT` or `SUSPENDED` resident is rejected with `ERR_ACCOUNT_DELINQUENT`, 403); guest passes require any posture other than `SUSPENDED` (a `SUSPENDED` resident is rejected with `ERR_ACCOUNT_SUSPENDED`, 403).
10. **Temporal windows** — a booking must lie inside the amenity's operating hours (otherwise `ERR_OUTSIDE_OPERATING_HOURS`, 422) and must not push buffer-expanded single-instant occupancy above the amenity's capacity (otherwise `ERR_BOOKING_OVERLAP`, 409); a guest pass must keep concurrent active passes within the property's guest-parking capacity (otherwise `ERR_GUEST_CAPACITY_EXCEEDED`, 409).
11. **Vendor quota** — a vendor's active job count must be below its active job limit before assignment; otherwise `ERR_VENDOR_AT_CAPACITY` (409).
12. **Optimistic concurrency** — `expected_amenity_version` equals the amenity's current `version`; otherwise `ERR_STALE_VERSION` (412).

Endpoint-specific business rules that do not fall into this general ladder — duplicate event registration, duplicate survey response, submission to a closed survey, and assignment to a suspended vendor — are described alongside their workflows in §3 and carry their own error codes.

### 2.9. Nested Resource Resolution

Endpoints addressed through a nested path resolve their path segments left to right, and the first unresolved segment determines the not-found error. For a resident's ledger or retention view, the resident id in the path is resolved first; for a resident's rent charge, the resident is resolved before the charge is applied. Filtered list endpoints support reverse reachability: units can be filtered by `property_id`; residents by `unit_id`; amenities by `property_id` and `amenity_type`; bookings by `amenity_id`, `resident_id`, and `status`; events by `property_id`, `amenity_id`, and `status`; registrations by `event_id`, `resident_id`, and `status`; service requests by `unit_id`, `resident_id`, `vendor_id`, and `status`; vendors, packages, and guest passes by `status` (packages and guest passes also by `resident_id`); surveys by `property_id` and `status`; and survey responses by `survey_id` and `resident_id`.

## 3. Business Logic & Workflows

### 3.1. Building the Community: Properties, Units, and Residents

A property manager establishes a property by supplying its `name`, `address`, and a `guest_parking_capacity` (the maximum number of guest passes that may be concurrently active across the whole property at any instant, which must be zero or greater). Two further inputs are optional: a `timezone` label, which is informational only and defaults to `America/New_York` while all window math remains in UTC, and a `guest_window_hours` value that caps how long a single guest pass may span, defaulting to 24 hours.

Under a property, the manager creates units by supplying the parent `property_id`, a `unit_number` (a human label unique within the property), and a `bedrooms` count. A unit begins with `occupancy_status` of `VACANT`. When a resident is created on a unit — by supplying the `unit_id`, `full_name`, `email` (unique across all residents), and an optional `membership_tier` that defaults to `STANDARD` and may be `PREMIUM` — that unit's `occupancy_status` flips to `OCCUPIED`.

A newly created resident starts financially clean: `account_status` is `GOOD_STANDING`, `rent_balance_cents`, `hold_balance_cents`, `wallet_credit_cents`, and `no_show_strikes` are all zero, and `retention_score` opens at 50. The `membership_tier` matters at billing time: a `PREMIUM` resident receives a discount on amenity fees, described in §3.2.

### 3.2. Amenity Configuration and the Booking Lifecycle

A property manager configures a bookable amenity by supplying its parent `property_id`, a `name`, an `amenity_type` of `GYM`, `POOL`, or `CLUBROOM`, a `capacity` of at least one (the maximum number of `CONFIRMED` or `CHECKED_IN` bookings that may cover any single instant), and a `base_rate_cents_per_hour` of zero or more. Optional configuration includes a `deposit_cents` (default 0) held per booking, a `buffer_minutes` turnover gap between bookings (default 0), and the daily window as `open_minute` (inclusive) and `close_minute` (exclusive, and strictly greater than `open_minute`), each a minute-of-day from 0 to 1440. Peak pricing is configured by `peak_start_minute`, `peak_end_minute` (both default 0), and a `peak_multiplier` (default 1.0). An amenity's `status` — `OPEN`, `CLOSED`, or `MAINTENANCE`, defaulting to `OPEN` — gates whether it can be booked at all.

**Creating a booking.** A resident (or a manager on their behalf) reserves an amenity by supplying the `amenity_id`, the `resident_id`, the requested `start_at` and `end_at`, and `expected_amenity_version`. The reservation is admitted only when the amenity's `status` is `OPEN`, the resident's `account_status` is `GOOD_STANDING`, the requested window is well-formed with `start_at` before `end_at` and both endpoints falling within the amenity's `[open_minute, close_minute)` operating window on the same UTC day, the booking does not push buffer-expanded single-instant occupancy above the amenity's `capacity`, and `expected_amenity_version` matches the amenity's current `version`. A window outside operating hours or spanning days is rejected with `ERR_OUTSIDE_OPERATING_HOURS`; an occupancy conflict with `ERR_BOOKING_OVERLAP`. On success the booking is created directly in `CONFIRMED` status, its `provisional_fee_cents` is computed (see below), its `deposit_hold_cents` is copied from the amenity's `deposit_cents`, the resident's `hold_balance_cents` is increased by that deposit hold, and the amenity's `version` is incremented by one. The provisional fee is not charged to the resident's balance at this stage — only the deposit is held.

For overlap testing, each occupied interval is expanded by the amenity's `buffer_minutes` so that consecutive bookings must leave at least that gap; occupancy at any instant counts bookings in `CONFIRMED` or `CHECKED_IN` status whose half-open window covers that instant, and this count including the new booking must not exceed `capacity`. A confirm that places a booking and its compensating cancel that releases it leave occupancy unchanged at every instant.

**The booking fee calculation.** A booking's fee is computed by tiered pricing over a window. The window's `duration_hours` is the elapsed time from window start to window end expressed in hours (seconds elapsed divided by 3600). Within that window, `peak_hours` is the number of hours that overlap the amenity's peak window `[peak_start_minute, peak_end_minute)`, and the remaining `offpeak_hours` is `duration_hours` minus `peak_hours`. The gross amount is the amenity's `base_rate_cents_per_hour` multiplied by the sum of the off-peak hours plus the peak hours scaled by the `peak_multiplier`, rounded half up to whole cents. A tier discount is then applied: for a `PREMIUM` resident the discount is twenty percent, and for any other tier it is zero. The discounted amount is the gross multiplied by one minus that discount fraction, rounded half up again. Finally the fee is the lesser of the discounted amount and a daily fee cap of 20000 cents. The gross is rounded before the discount, and the discounted amount is rounded before the cap is applied. The provisional variant uses the requested `[start_at, end_at)` window and is stored as `provisional_fee_cents`; the final variant uses the actual checked-in window and is stored as `final_fee_cents`.

**Check-in and check-out.** Front-desk staff check a resident in, advancing the booking from `CONFIRMED` to `CHECKED_IN`, only while the current time lies from a configured grace period (`CHECK_IN_GRACE_MINUTES`) before `start_at` up to but not including `end_at`; on success `checked_in_at` is set to the current time. Checking out advances a `CHECKED_IN` booking to `COMPLETED`: `checked_out_at` is set to the current time, the final variant of the booking fee is computed over the actual `[checked_in_at, checked_out_at)` window and stored as `final_fee_cents`, that final fee is added to the resident's `rent_balance_cents` with a `BOOKING_FEE` ledger entry for the same positive amount, the resident's `hold_balance_cents` is decreased by the `deposit_hold_cents` (releasing the hold), and the resident's posture is recomputed. Until a booking completes, `final_fee_cents` remains null, as do `checked_in_at` and `checked_out_at` before their respective transitions.

**Cancellation.** A resident may cancel a `CONFIRMED` booking. A late-cancellation penalty is computed from the lead time: the hours before start is the interval from the current time to `start_at` expressed in hours. If that lead time is at least the late-cancel window of 24 hours, the penalty is zero and the full deposit hold is simply released. If it is less than 24 hours, the penalty is the `deposit_hold_cents` multiplied by a forfeit fraction of fifty percent, rounded half up. When the penalty is positive it is added to the resident's `rent_balance_cents` with a `PENALTY` ledger entry, and in all cases the full deposit hold is released by decreasing `hold_balance_cents` by `deposit_hold_cents`; posture is then recomputed. A booking that is currently `SUSPENDED` may also be cancelled, but in that case there is no hold movement — the hold was already released on suspension — and no penalty.

**No-show.** Front desk (or a manager) may mark a `CONFIRMED` booking as `NO_SHOW` once the current time has reached or passed `end_at` and the booking was never checked in (`checked_in_at` is null). This forfeits the deposit: the `deposit_hold_cents` is added to the resident's `rent_balance_cents` with a `DEPOSIT_FORFEIT` ledger entry, `hold_balance_cents` is decreased by the same amount, the resident's `no_show_strikes` is increased by one, and posture is recomputed. The terminal booking states are `COMPLETED`, `CANCELLED`, and `NO_SHOW`.

### 3.3. Rent, Payments, and the Delinquency Cascade

A property manager posts a charge against a resident by supplying an `amount_cents` and an optional `description`. The charge increases the resident's `rent_balance_cents` by that amount and records a `RENT_CHARGE` ledger entry, after which the resident's `account_status` is recomputed and may cascade into booking suspension.

Payments run through a deterministic waterfall. A manager records a payment by supplying the `resident_id`, an `amount_cents`, and a `method`. The payment amount first reduces the resident's `rent_balance_cents` by the lesser of the payment amount and the current balance; whatever remains after the balance reaches zero becomes prepaid credit added to `wallet_credit_cents`. The rent bucket is filled before any wallet overflow and never goes below zero. A `PAYMENT` ledger entry is recorded for the negative of the payment amount, and posture is recomputed, which may cascade into booking re-confirmation.

**The suspension cascade (Cascade A).** When a recompute moves a resident out of `GOOD_STANDING` — into `DELINQUENT` when the balance is strictly above 50000 but not above 150000, or into `SUSPENDED` when the balance is strictly above 150000 — every one of that resident's `CONFIRMED` bookings whose `start_at` is still in the future (strictly after the current time) is transitioned from `CONFIRMED` to `SUSPENDED`. Each such suspension releases that booking's deposit hold by decreasing the resident's `hold_balance_cents` by its `deposit_hold_cents`; this is a hold movement only and writes no ledger entry. A resident already `DELINQUENT` whose balance climbs strictly above 150000 likewise becomes `SUSPENDED`, though at that point future bookings have already been suspended.

**The reverse cascade.** When a payment brings a resident's balance back down so that recompute moves them toward `GOOD_STANDING` — reaching `GOOD_STANDING` when the balance is at or below 50000 — each of that resident's `SUSPENDED` bookings whose `start_at` is still in the future and whose window is still free of capacity and overlap conflicts is transitioned from `SUSPENDED` back to `CONFIRMED`, re-placing its deposit hold by increasing `hold_balance_cents` by `deposit_hold_cents`. A recovering resident may instead land in `DELINQUENT` (balance at or below 150000 but strictly above 50000), which does not itself re-confirm bookings. These two cascades close the `CONFIRMED` ↔ `SUSPENDED` cycle; a suspended booking whose window is no longer free stays suspended and may only be cancelled.

### 3.4. Community Events and Waitlist Management

A property manager drafts a community event by supplying the `property_id`, an optional venue `amenity_id` (an event may be venue-less), a `title`, `start_at` and `end_at`, a `capacity` of at least one, and an optional per-registration `fee_cents` (default 0). An event is created in `DRAFT`; its `reserved_count` and `waitlist_count` both start at zero. Publishing an event moves it from `DRAFT` to `PUBLISHED`, permitted only when the capacity is at least one and the event's `start_at` is still in the future. If the event names an `amenity_id`, that amenity must belong to the same property as the event's `property_id`, or the operation is rejected with `ERR_PROPERTY_MISMATCH`. The event lifecycle terminates in `CANCELLED` or `COMPLETED`.

**Registration and capacity allocation.** A resident registers for a `PUBLISHED` event by supplying their `resident_id`. Registration is admitted only if the resident has no existing non-terminal registration for that event; a duplicate is rejected with `ERR_DUPLICATE_REGISTRATION`. Allocation is by a strict capacity comparison: if the event's `reserved_count` is strictly less than its `capacity`, the registration is created `RESERVED`, its `fee_charged_cents` is set to the event's `fee_cents`, that fee is added to the resident's `rent_balance_cents` with an `EVENT_FEE` ledger entry, the event's `reserved_count` is increased by one, and the resident's posture is recomputed. When `reserved_count` has reached `capacity` (they are equal), the registration is instead created `WAITLISTED` with `fee_charged_cents` of zero and no charge, and the event's `waitlist_count` is increased by one. A registration's terminal states are `ATTENDED`, `NO_SHOW`, and `CANCELLED`.

**Cancelling a registration and waitlist promotion (Cascade B applies to event cancel).** A resident may cancel their own registration. Cancelling a `RESERVED` registration refunds its fee when `fee_charged_cents` is positive — crediting the resident's `wallet_credit_cents` by that amount and recording a `REFUND` ledger entry for the negative of that amount — decreases the event's `reserved_count` by one, and then promotes exactly one waitlisted registration if any exist: the single earliest-created `WAITLISTED` registration for that event, selected by `created_at` ascending (the sole ordering key, never `id`), is moved to `RESERVED`, is charged its fee, and the event's `waitlist_count` is decreased by one while `reserved_count` is increased by one. If the waitlist is empty, no promotion occurs. Cancelling a `WAITLISTED` registration simply decreases the event's `waitlist_count` by one.

**Check-in, completion, and event cancellation.** Front-desk staff check a resident in at a `PUBLISHED` event, moving their `RESERVED` registration to `ATTENDED`. Completing an event — permitted once the current time has reached or passed the event's `end_at` — moves it from `PUBLISHED` to `COMPLETED` and turns every `RESERVED` registration that was never checked in into `NO_SHOW`. Cancelling a `PUBLISHED` event moves it to `CANCELLED` and cascades to its registrations: every registration in `RESERVED` or `WAITLISTED` is transitioned to `CANCELLED`, and any that carried a positive `fee_charged_cents` is refunded by crediting the resident's `wallet_credit_cents` and recording a `REFUND` ledger entry for the negative of that amount.

### 3.5. Maintenance: Vendors and Service Requests

A property manager registers a vendor by supplying a `name`, a `trades` array whose members are drawn from `PLUMBING`, `ELECTRICAL`, `HVAC`, `APPLIANCE`, and `GENERAL`, an `hourly_rate_cents` of zero or more, and an optional `active_job_limit` (default 5). A vendor begins `ACTIVE` with an `active_job_count` of zero; a manager may suspend a vendor, setting its `status` to `SUSPENDED`, which blocks new assignments. A suspended vendor targeted by an assignment is rejected with `ERR_VENDOR_INACTIVE`.

A resident (or manager) submits a maintenance request by supplying the `unit_id`, `resident_id`, required `trade`, an optional `priority` of `ROUTINE`, `URGENT`, or `EMERGENCY` (default `ROUTINE`), and a `description`. The request opens in `SUBMITTED`. Its lifecycle threads through triage, assignment, work, completion, and approval, and terminates in `CLOSED` or `CANCELLED`.

**Triage and assignment (the revision cycle).** A property manager triages a `SUBMITTED` request, advancing it to `TRIAGED`; this records that manager's `X-User-ID` as `triaged_by_user_id` and may optionally overwrite the request's `trade` or `priority` from the request body. From `TRIAGED`, a manager assigns a vendor by supplying the `vendor_id`, an `estimated_hours`, and an optional `estimated_parts_cents`. Assignment is admitted only when the chosen vendor's `status` is `ACTIVE`, the request's `trade` is a member of that vendor's `trades` (otherwise `ERR_VENDOR_TRADE_MISMATCH`), and the vendor's `active_job_count` is strictly below its `active_job_limit` (otherwise `ERR_VENDOR_AT_CAPACITY`). On success the request's `vendor_id` is set, its `estimated_cost_cents` is computed (see below), and the vendor's `active_job_count` is increased by one, moving the request to `ASSIGNED`. A manager may unassign an `ASSIGNED` request, reverting it to `TRIAGED`: the vendor's `active_job_count` is decreased by one and both `vendor_id` and `estimated_cost_cents` are cleared to null. This assign/unassign pair forms the `TRIAGED` ↔ `ASSIGNED` revision cycle.

**Work and completion.** The assigned vendor — and only that vendor, whose `X-User-ID` must equal the request's `vendor_id` — starts the work, moving it from `ASSIGNED` to `IN_PROGRESS`, and later completes it, moving it from `IN_PROGRESS` to `COMPLETED`. Completion is submitted with the actual `labor_hours` and an optional `parts` list, each part carrying a `cents` amount; on completion the actual invoice is computed and stored as `final_invoice_cents`, and the vendor's `active_job_count` is decreased by one.

**The service invoice calculation.** The invoice has two variants. The estimate, produced at assignment, is the vendor's `hourly_rate_cents` multiplied by `estimated_hours` and rounded half up, plus the `estimated_parts_cents` as an untaxed lump; it is stored as `estimated_cost_cents`. The actual invoice, produced at completion, is built line by line: a labor line equal to the vendor's `hourly_rate_cents` multiplied by `labor_hours`, rounded half up; then, for each part, a taxed line equal to that part's `cents` multiplied by one plus a material tax of seven percent, rounded half up. Each line is rounded before the lines are summed — never summed then rounded. The subtotal is the labor line plus the sum of the part lines. A trip fee is added when the request's `priority` is `EMERGENCY`: 7500 cents, and zero otherwise. The final invoice, stored as `final_invoice_cents`, is the subtotal plus that trip fee. Until assignment `estimated_cost_cents` is null, and until completion `final_invoice_cents` is null.

**Invoice approval and segregation of duties.** A property manager approves the invoice on a `COMPLETED` request, moving it to `CLOSED`, but the approving manager's `X-User-ID` must differ from the `triaged_by_user_id` who triaged it; an approver who is the same person as the triager is rejected with `ERR_SEGREGATION_OF_DUTIES`. On approval the approver's `X-User-ID` is recorded as `invoice_approved_by_user_id`, the `final_invoice_cents` is added to the resident's `rent_balance_cents` with a `SERVICE_CHARGE` ledger entry, and the resident's posture is recomputed.

**Cancellation.** A request may be cancelled from `SUBMITTED` (by the resident or a manager), `TRIAGED`, or `ASSIGNED` (by a manager). Cancelling a request that was `ASSIGNED` decreases the vendor's `active_job_count` by one; cancelling from `SUBMITTED` or `TRIAGED` has no vendor-count effect.

### 3.6. Packages, Guest Passes, and Front-Desk Operations

**Packages.** Front-desk staff log a received package by supplying the `resident_id` and the delivery `carrier`. The system mints a six-digit `access_code` and sets `received_at` to the current time; the package opens in `RECEIVED`. Staff mark a `RECEIVED` package `NOTIFIED` to alert the resident. A resident then picks up a `NOTIFIED` package by supplying the `access_code`; the supplied code must match the minted `access_code`, or the pickup is rejected with `ERR_ACCESS_CODE_MISMATCH`. On a successful pickup the package moves to `PICKED_UP` and `picked_up_at` is set to the current time. Alternatively, front-desk staff may return a `NOTIFIED` package to the carrier, but only once the current time has reached or passed `received_at` plus a package hold period (`PACKAGE_HOLD_DAYS` days), moving it to `RETURNED`. The terminal package states are `PICKED_UP` and `RETURNED`; `picked_up_at` stays null until pickup.

**Guest passes.** A resident issues a guest pass by supplying their `resident_id`, the `guest_name`, an `arrival_at`, and an `expected_departure_at`. Issuance requires that the resident's `account_status` is not `SUSPENDED` (a suspended resident is rejected with `ERR_ACCOUNT_SUSPENDED`), that `arrival_at` is before `expected_departure_at` and their span does not exceed the property's `guest_window_hours`, and that admitting this pass keeps the number of concurrently active guest passes over the pass's window within the property's `guest_parking_capacity` (otherwise `ERR_GUEST_CAPACITY_EXCEEDED`). Concurrency counts passes that are active — `ISSUED` or `CHECKED_IN` — whose windows overlap. On success a `pass_code` is minted and the pass opens in `ISSUED`. Front desk checks a guest in, moving `ISSUED` to `CHECKED_IN`, only while the current time lies within `[arrival_at, expected_departure_at)`; if a check-in is attempted once the current time has reached or passed `expected_departure_at`, the system refuses the check-in and instead marks the pass `EXPIRED`. A `CHECKED_IN` pass is later checked out to `DEPARTED`, and a resident may cancel an `ISSUED` pass, moving it to `CANCELLED`. The terminal guest-pass states are `DEPARTED`, `EXPIRED`, and `CANCELLED`.

### 3.7. Surveys, Retention, and Reporting

A property manager creates a survey by supplying the `property_id` and a `title`; it opens in `DRAFT`, with `response_count` at zero. The manager opens a `DRAFT` survey to `OPEN`, and later closes an `OPEN` survey to `CLOSED` (terminal). Responses are accepted only while the survey is `OPEN`. A resident submits a response by supplying their `resident_id`, a `satisfaction_score` from 1 to 5, and an optional `comment`. A response to a survey that is not `OPEN` is rejected with `ERR_SURVEY_NOT_OPEN`, and a resident who has already responded to that survey is rejected with `ERR_DUPLICATE_SURVEY_RESPONSE`. A successful response increases the survey's `response_count` by one.

**Retention scoring.** A resident's `retention_score`, an integer from 0 to 100, is recomputed on read (both when a manager fetches a single resident's retention view and when the property report is generated). It begins from a base of 50. The satisfaction term takes the mean of the resident's `satisfaction_score` values across all their survey responses — or 3.0 when the resident has no responses — divides that mean by 5.0, multiplies by a satisfaction weight of 20, and rounds the result half up. The engagement term is three points per booking the resident completed whose `checked_out_at` falls within the retention window of 90 days before the current time, capped at 30 points. Two penalties are subtracted: an open-service-request penalty of five points for each of the resident's service requests currently in `SUBMITTED`, `TRIAGED`, `ASSIGNED`, or `IN_PROGRESS`, capped at 30 points; and a no-show penalty of ten points for each of the resident's `no_show_strikes`. The score is the base plus engagement plus the satisfaction term minus the open-service-request penalty minus the no-show penalty, then clamped to the range 0 to 100. The single-resident retention view reports the `retention_score`, the `avg_satisfaction`, the count of `completed_bookings_90d`, and the number of `open_service_requests`.

**Property report.** The property report summarizes a property by recomputing each resident's `retention_score` and returning the property's `unit_count`, `resident_count`, `active_bookings`, `open_service_requests`, and the `avg_retention_score` across its residents.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; state transitions, other mutations, and reads return HTTP 200 with the affected or requested resource. All list endpoints honor the pagination and ordering rules of §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /properties | Create a property. | PropertyManager |
| GET | /properties/{id} | Fetch a property. | PropertyManager, Resident, FrontDesk |
| GET | /properties | List properties. | PropertyManager |
| GET | /properties/{id}/report | Property reporting summary. | PropertyManager |
| POST | /units | Create a unit under a property. | PropertyManager |
| GET | /units/{id} | Fetch a unit. | PropertyManager, Resident |
| GET | /units | List/filter units. | PropertyManager |
| POST | /residents | Create a resident on a unit. | PropertyManager |
| GET | /residents/{id} | Fetch a resident. | PropertyManager, Resident |
| GET | /residents | List/filter residents. | PropertyManager |
| GET | /residents/{id}/ledger | List a resident's ledger entries. | PropertyManager, Resident |
| GET | /residents/{id}/retention | Computed retention score for a resident. | PropertyManager |
| POST | /residents/{id}/rent-charges | Post a rent/misc charge; recompute posture. | PropertyManager |
| POST | /payments | Record a payment (waterfall allocation). | PropertyManager |
| POST | /amenities | Create a bookable amenity. | PropertyManager |
| GET | /amenities/{id} | Fetch an amenity. | PropertyManager, Resident, FrontDesk |
| GET | /amenities | List/filter amenities. | PropertyManager, Resident |
| POST | /amenity-bookings | Create and auto-confirm a booking (OCC on amenity version). | Resident, PropertyManager |
| GET | /amenity-bookings/{id} | Fetch a booking. | PropertyManager, Resident, FrontDesk |
| GET | /amenity-bookings | List/filter bookings. | PropertyManager, Resident, FrontDesk |
| POST | /amenity-bookings/{id}/check-in | Check a resident in to their booking. | FrontDesk |
| POST | /amenity-bookings/{id}/check-out | Check out; settle final fee, release deposit. | FrontDesk |
| POST | /amenity-bookings/{id}/cancel | Cancel a booking; apply late-cancel penalty. | Resident, PropertyManager |
| POST | /amenity-bookings/{id}/mark-no-show | Mark an unattended past booking NO_SHOW; forfeit deposit. | FrontDesk, PropertyManager |
| POST | /events | Create a community event (DRAFT). | PropertyManager |
| GET | /events/{id} | Fetch an event. | PropertyManager, Resident |
| GET | /events | List/filter events. | PropertyManager, Resident |
| POST | /events/{id}/publish | Publish an event. | PropertyManager |
| POST | /events/{id}/cancel | Cancel a published event; cascade-cancel registrations and refund. | PropertyManager |
| POST | /events/{id}/complete | Complete an event; no-show unchecked reservations. | PropertyManager |
| POST | /events/{id}/register | Register a resident; RESERVED or WAITLISTED by capacity. | Resident |
| GET | /event-registrations/{id} | Fetch a registration. | PropertyManager, Resident |
| GET | /event-registrations | List/filter registrations. | PropertyManager, Resident |
| POST | /event-registrations/{id}/cancel | Cancel a registration; promote earliest waitlisted. | Resident, PropertyManager |
| POST | /event-registrations/{id}/check-in | Check a resident in at the event. | FrontDesk |
| POST | /vendors | Create a service vendor. | PropertyManager |
| GET | /vendors/{id} | Fetch a vendor. | PropertyManager, Vendor |
| GET | /vendors | List/filter vendors. | PropertyManager |
| POST | /vendors/{id}/suspend | Suspend a vendor. | PropertyManager |
| POST | /service-requests | Submit a maintenance request. | Resident, PropertyManager |
| GET | /service-requests/{id} | Fetch a service request. | PropertyManager, Resident, Vendor |
| GET | /service-requests | List/filter service requests. | PropertyManager, Resident, Vendor |
| POST | /service-requests/{id}/triage | Triage a request. | PropertyManager |
| POST | /service-requests/{id}/assign | Assign a vendor; compute estimate. | PropertyManager |
| POST | /service-requests/{id}/unassign | Unassign vendor; revert to TRIAGED. | PropertyManager |
| POST | /service-requests/{id}/start | Assigned vendor starts work. | Vendor |
| POST | /service-requests/{id}/complete | Vendor completes with invoice line items. | Vendor |
| POST | /service-requests/{id}/approve-invoice | Approve invoice (SoD); charge resident; CLOSED. | PropertyManager |
| POST | /service-requests/{id}/cancel | Cancel a non-terminal request. | Resident, PropertyManager |
| POST | /packages | Log a received package. | FrontDesk |
| GET | /packages/{id} | Fetch a package. | PropertyManager, Resident, FrontDesk |
| GET | /packages | List/filter packages. | PropertyManager, Resident, FrontDesk |
| POST | /packages/{id}/notify | Mark package NOTIFIED. | FrontDesk |
| POST | /packages/{id}/pickup | Resident picks up with access code. | Resident, FrontDesk |
| POST | /packages/{id}/return | Return to carrier after hold period. | FrontDesk |
| POST | /guest-passes | Issue a guest pass; concurrency-checked. | Resident |
| GET | /guest-passes/{id} | Fetch a guest pass. | PropertyManager, Resident, FrontDesk |
| GET | /guest-passes | List/filter guest passes. | PropertyManager, Resident, FrontDesk |
| POST | /guest-passes/{id}/check-in | Check a guest in. | FrontDesk |
| POST | /guest-passes/{id}/check-out | Check a guest out. | FrontDesk |
| POST | /guest-passes/{id}/cancel | Cancel an issued pass. | Resident |
| POST | /surveys | Create a survey (DRAFT). | PropertyManager |
| GET | /surveys/{id} | Fetch a survey. | PropertyManager, Resident |
| GET | /surveys | List/filter surveys. | PropertyManager, Resident |
| POST | /surveys/{id}/open | Open a survey for responses. | PropertyManager |
| POST | /surveys/{id}/close | Close a survey. | PropertyManager |
| POST | /surveys/{id}/responses | Submit a survey response. | Resident |
| GET | /survey-responses/{id} | Fetch a survey response. | PropertyManager |
| GET | /survey-responses | List/filter survey responses. | PropertyManager |
| POST | /_clock/set_current_utc | Set the logical clock. | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 422 |
| ERR_PROPERTY_NOT_FOUND | 404 |
| ERR_UNIT_NOT_FOUND | 404 |
| ERR_RESIDENT_NOT_FOUND | 404 |
| ERR_AMENITY_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_REGISTRATION_NOT_FOUND | 404 |
| ERR_VENDOR_NOT_FOUND | 404 |
| ERR_SERVICE_REQUEST_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_GUEST_PASS_NOT_FOUND | 404 |
| ERR_SURVEY_NOT_FOUND | 404 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_VENDOR_TRADE_MISMATCH | 422 |
| ERR_VENDOR_INACTIVE | 409 |
| ERR_PROPERTY_MISMATCH | 422 |
| ERR_ACCESS_CODE_MISMATCH | 422 |
| ERR_ACCOUNT_DELINQUENT | 403 |
| ERR_ACCOUNT_SUSPENDED | 403 |
| ERR_OUTSIDE_OPERATING_HOURS | 422 |
| ERR_BOOKING_OVERLAP | 409 |
| ERR_GUEST_CAPACITY_EXCEEDED | 409 |
| ERR_VENDOR_AT_CAPACITY | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_REGISTRATION | 409 |
| ERR_SURVEY_NOT_OPEN | 409 |
| ERR_DUPLICATE_SURVEY_RESPONSE | 409 |
