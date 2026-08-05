# Luggage & Bag Storage Network API — Product Requirements Document

## 1. Introduction

The Luggage & Bag Storage Network API powers a Bounce-style marketplace that connects travelers who need short-term luggage storage with independent hosts who offer secure space at their locations. The platform coordinates the full arc of a storage engagement: a traveler reserves capacity at a host's location for a range of dates, the host physically receives and seals each bag, the bags rest under a documented chain of custody, and the traveler later retrieves them — at which point the platform settles charges, credits the host, and (optionally) collects a rating. Layered on top of this core flow are the marketplace's harder concerns: per-bag daily pricing with oversize surcharges, insurance premiums and damage claims, host payouts net of platform commission and claim deductions, and the temporal and capacity constraints that keep a physical storage room from being oversold.

This document is the single authoritative specification for the API's behavior. It defines the resource model, the state machines that govern each entity's lifecycle, the pricing and payout calculations, the validation precedence that decides which error a malformed request receives, and the concurrency and consistency rules that keep money and capacity conserved. Monetary amounts are represented throughout in integer cents. Time is governed by a server-controlled logical clock rather than wall-clock time, so that date-sensitive behavior (overdue sweeps, late fees, claim windows, payout holds) is deterministic and test-driveable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than traveler self-registration must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request that omits either header, or supplies a malformed one, is rejected with `ERR_MISSING_AUTH_HEADER`. A well-formed request whose role is not permitted for the target operation is rejected with `ERR_INVALID_ROLE`.

The system recognizes four roles: `Anonymous`, `Traveler`, `Host`, and `PlatformAdmin`.

- `Anonymous` is an unauthenticated caller. The only operation it may perform is self-registering a new traveler, which is the sole endpoint that requires no auth headers. Because `Anonymous` is an opaque, non-persisted identity, `X-User-ID` carries no meaning for it and is not compared against any stored resource.
- When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting `Traveler`; ownership checks on any resource that references a `Traveler` compare the resource's traveler foreign-key field to `X-User-ID`. A traveler owns the bookings it created, the bags and extensions under those bookings, the claims it filed, and the ratings it left.
- When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`; ownership checks on any resource that references a `Host` compare the resource's owning-host to `X-User-ID`. A host owns the locations it created and, transitively, the bookings placed at those locations and the payouts derived from them.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The platform admin is the marketplace operator; the server does not compare its `X-User-ID` to any entity's `id`.

Ownership violations are distinguished by actor: a host acting on a location or booking it does not own is rejected with `ERR_NOT_LOCATION_HOST`, and a traveler acting on a booking or claim it does not own is rejected with `ERR_NOT_BOOKING_OWNER`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0 and must be at least 0. A request whose `limit` falls outside the inclusive range of 1 through 100, or whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION`.

List results are always ordered by `created_at` ascending. Each list response reports pagination state through the `meta` object using the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of all matching resources before the page window is applied and `has_more` indicates whether further pages remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Every entity in this system additionally carries an `updated_at` timestamp (same format) and an integer `version`. The `version` begins at 1 when the resource is created and increments by 1 on every mutation that changes the resource; `updated_at` is refreshed to the current logical-clock instant on each such mutation. Read operations never alter `updated_at` or `version`.

Time in this system is a logical clock, not wall-clock time. On startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to real time. A platform admin advances the clock by supplying a target instant as `to_iso8601`; the response reports the new `current_utc` and an `overdue_swept_count`. Advancing the clock has a side effect described in §3.6: it sweeps stored bookings whose scheduled pickup has passed into an overdue state. Booking timestamps that record physical events — `dropoff_at` when bags are received and `pickup_at` when they are returned — are stamped from this logical clock, and both are null until the respective event occurs.

### 2.5. Optimistic Concurrency on Location Version

Creating a booking is guarded by optimistic concurrency against the target location's `version`. A create-booking request must carry `expected_location_version`, a non-optional field holding the `version` of the `Location` the client last observed. Because every booking reserves day-capacity on its location and therefore advances `Location.version`, and because a location status change also advances it, a client whose `expected_location_version` no longer equals the location's current `version` is working from a stale view of remaining capacity. In that case the create is rejected with `ERR_STALE_LOCATION_VERSION` (HTTP 412) before capacity is ever evaluated, so the client cannot overwrite capacity decisions it has not observed. No other endpoint in this system accepts or requires a version field.

### 2.6. Monetary Precision, Rounding, and Ledger Conservation

All money is stored and computed in integer cents. Pure storage, oversize, insurance, and late-fee amounts are products of integer inputs and therefore require no rounding. Rounding enters only where a ratio is applied: the platform commission on a payout and a host's average rating. Wherever rounding is required, the method is round half up.

Commission is rounded per booking, at the moment a payout is created, before that payout's net contribution is folded into any host-level total. Host balances are maintained as the sum of already-rounded per-booking net amounts — the system rounds per booking and then sums, never sums and then rounds. Host money is tracked across three computed totals: `pending_payout_cents` (the sum of net amounts over the host's pending payouts), `payout_balance_cents` (the sum of net amounts over the host's released, not-reversed payouts), and `lifetime_earnings_cents` (the cumulative net ever credited at payout creation). Every payout state change and every claim-driven adjustment moves money between these totals in equal and opposite amounts so that no cents are created or destroyed; a reversal exactly compensates the release that preceded it.

### 2.7. Capacity Conservation and the Reservation Invariant

A location's physical room is finite. `daily_bag_capacity` is the maximum number of bags — standard and oversize combined — that may be stored on any single calendar day, and `oversize_capacity` is a sub-limit within it capping oversize bags on any single day. A booking reserves capacity for every day in its stay, and the platform must guarantee that on no day does the sum of reserved bags exceed `daily_bag_capacity`, nor the sum of reserved oversize bags exceed `oversize_capacity`. Reservations are conserved: when a booking is cancelled its reserved days are released back to the location, and when an extension is confirmed the added days are reserved. Separately, each host carries a network-wide ceiling, `max_concurrent_bookings`, on how many of its bookings may be simultaneously active across all of its locations at once.

### 2.8. Validation Precedence

When more than one condition could reject a request, checks are evaluated in a fixed order so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — auth headers present and well-formed (`ERR_MISSING_AUTH_HEADER`), except on traveler self-registration which is anonymous.
2. **Role authorization** — the acting role is permitted for the endpoint (`ERR_INVALID_ROLE`).
3. **Existence** — every path resource and every foreign-key-referenced resource exists, validated left to right (`ERR_NOT_FOUND`).
4. **Ownership** — the actor owns the target resource (`ERR_NOT_LOCATION_HOST` for hosts, `ERR_NOT_BOOKING_OWNER` for travelers).
5. **Optimistic concurrency** — on booking creation, `expected_location_version` equals the location's current `version` (`ERR_STALE_LOCATION_VERSION`).
6. **State validity** — the resource, and any referenced location, is in a state that permits the operation (`ERR_INVALID_STATE`, `ERR_LOCATION_NOT_OPEN`, `ERR_CANCEL_NOT_ALLOWED`, `ERR_HOST_SUSPENDED`, `ERR_LOCATION_HAS_ACTIVE_BOOKINGS`).
7. **Temporal validity** — date ranges and windows are valid (`ERR_INVALID_DATE_RANGE`, `ERR_EXTENSION_INVALID_DATE`, `ERR_CLAIM_WINDOW_CLOSED`).
8. **Chain-of-custody** — sealing and tamper checks (`ERR_BAG_NOT_SEALED`, `ERR_DUPLICATE_SEAL`, `ERR_SEAL_TAMPERED`).
9. **Capacity** — day-capacity, oversize sub-limit, and host concurrency (`ERR_CAPACITY_EXCEEDED`, `ERR_OVERSIZE_CAPACITY_EXCEEDED`, `ERR_HOST_CONCURRENCY_EXCEEDED`).
10. **Insurance and rating preconditions** (`ERR_NO_INSURANCE_COVERAGE`, `ERR_BOOKING_NOT_COMPLETED`, `ERR_RATING_ALREADY_EXISTS`).
11. **Monetary bounds** on claim amounts (`ERR_CLAIM_AMOUNT_INVALID`, `ERR_COVERAGE_CAP_EXCEEDED`).
12. **Pagination bounds** on list endpoints (`ERR_INVALID_PAGINATION`).

A malformed body or a missing required field that is caught before any domain check surfaces as `ERR_VALIDATION`. The higher-priority (lower-numbered) check always wins: for example, an unauthenticated request to a state-transition endpoint receives the authentication error, never the state error.

### 2.9. Nested Resource Resolution

Several endpoints address resources through a nested path — a bag under a booking, a location under a host, an extension or claim reached through its booking. Path parameters are resolved left to right, and the first segment that names a nonexistent resource causes `ERR_NOT_FOUND` before any deeper segment or foreign key is examined. Foreign keys supplied in a request body are resolved the same way and are equally subject to `ERR_NOT_FOUND`. Only once all referenced resources are confirmed to exist do ownership, state, and domain checks proceed in the order of §2.8.

### 2.10. State Propagation and Cascading Effects

Many operations mutate more than one entity. When they do, every affected entity has its `updated_at` refreshed and its `version` incremented, and the secondary effects are as binding as the primary transition. Two host-level cascades matter especially. First, when a platform admin suspends a host, every location of that host currently in the open state is transitioned to suspended by the system; reactivating the host does **not** automatically reopen those locations — the host must reopen each explicitly. Second, when a claim approval drives a host's pending balance below zero, the system suspends that host and, in the same cascade, suspends each of that host's open locations. These cascades are detailed in §3 alongside the workflows that trigger them.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Hosts, Travelers, Insurance Plans

The marketplace is seeded by the platform operator. A platform admin onboards a host by supplying the host's `display_name` and `email`, and optionally a commission rate and a concurrency ceiling. The commission, `platform_fee_bps`, is expressed in basis points and defaults to 2000 — that is, twenty percent of host-eligible revenue. The concurrency ceiling, `max_concurrent_bookings`, defaults to 5 and limits how many of the host's bookings may be simultaneously active. A freshly onboarded host is `ACTIVE`, and all of its money counters — `pending_payout_cents`, `payout_balance_cents`, `lifetime_earnings_cents` — and its rating counters `rating_sum`, `rating_count`, and `avg_rating` are initialized to zero. A platform admin may later suspend a host, moving it from `ACTIVE` to `SUSPENDED`, or reactivate it back to `ACTIVE`, by supplying the target `to_status`; suspension carries the open-location cascade of §2.10.

Travelers self-register without authentication, providing an `email` and a `full_name`. A traveler is created `ACTIVE` and remains active throughout; there is no traveler suspension in this system. Only travelers may create bookings, and `X-User-ID` on a booking request is the traveler that will own it.

Insurance is defined by the platform admin as reusable plans. Each `InsurancePlan` names a `tier` — one of `NONE`, `BASIC`, or `PREMIUM` — together with `per_bag_coverage_cents`, the maximum approvable claim per bag under the plan, and `premium_cents_per_bag_day`, the premium charged per bag per billable day. For the `NONE` tier both of these are zero. The insurance premium is retained by the platform and is never part of a host's eligible revenue.

### 3.2. Location Lifecycle and Availability

A host, or a platform admin acting on the host's behalf, creates a location by posting to that host under its identifier; the location's `host_id` is taken from the path. Creation supplies the location's `name`, `address`, `daily_bag_capacity`, the `oversize_capacity` sub-limit, the `per_bag_day_rate_cents` storage price, and the `oversize_surcharge_cents_per_day` levied additionally on each oversize bag. A new location starts in `DRAFT` and stores nothing until opened.

A location moves through `DRAFT`, `OPEN`, `SUSPENDED`, and the terminal `CLOSED` state. Opening a draft location — transitioning `DRAFT → OPEN` — requires that the owning host be `ACTIVE`; if the host is suspended the transition is rejected with `ERR_HOST_SUSPENDED`. From `OPEN` a location may be suspended (`OPEN → SUSPENDED`), which a host, a platform admin, or the system may trigger and which carries no precondition. A suspended location may be reopened (`SUSPENDED → OPEN`) by a host or platform admin, again only while the owning host is `ACTIVE`, else `ERR_HOST_SUSPENDED`. A location may be closed from either the open or suspended state (`OPEN → CLOSED` or `SUSPENDED → CLOSED`), but only when no booking on that location is currently in `RESERVED`, `STORED`, or `OVERDUE`; an attempt to close a location that still has such active bookings is rejected with `ERR_LOCATION_HAS_ACTIVE_BOOKINGS`. All of these transitions are requested by supplying the desired `to_status`. Locations can be listed under their host, optionally filtered by `status`; this reverse lookup keys on the location's owning host. A single location is retrievable directly, and its `version` is what a booking client reads for the optimistic-concurrency check.

### 3.3. Creating a Booking

A traveler creates a booking by naming the `location_id` where the bags will be stored, the `traveler_id` that will own the booking, the `insurance_plan_id` selecting a coverage tier, the `check_in_date` (the inclusive drop-off calendar date, `YYYY-MM-DD`), the `check_out_date` (the scheduled pickup date, treated as exclusive for billing), a `bags` array describing each item, and the `expected_location_version` for the concurrency guard of §2.5. Each entry in the `bags` array declares that bag's `declared_value_cents` — the traveler's stated value and the ceiling on any future claim for it — and its `dimension_sum_cm`, the sum of length, width, and height in centimeters. One `Bag` row is minted per array entry, each starting in `AWAITING_DROP`. A bag's `is_oversize` flag is computed, never taken from input: a bag is oversize exactly when its `dimension_sum_cm` is at least 150 centimeters. The booking's `bag_count` is the number of bags minted, and its `oversize_count` is how many of them are oversize. The booking's owning traveler is the `traveler_id` supplied in the request body, which the server records as the owner without comparing it to the caller's `X-User-ID`.

The referenced location must be `OPEN` at creation time, or the request is rejected with `ERR_LOCATION_NOT_OPEN`. The date range must be valid — the `check_out_date` must be strictly after the `check_in_date`, and the check-in must not lie in the past — otherwise `ERR_INVALID_DATE_RANGE`. The booking's `billable_days` is the number of days between check-in and check-out, floored at a minimum of 1 so that even a same-day stay bills one day.

Capacity is enforced across the whole stay. For every day in the half-open interval from `check_in_date` up to `check_out_date`, adding this booking's bags must keep the day's total reserved bags within `daily_bag_capacity` and its reserved oversize bags within `oversize_capacity`; a violation of the former is `ERR_CAPACITY_EXCEEDED` and of the latter `ERR_OVERSIZE_CAPACITY_EXCEEDED`. The host's network-wide `max_concurrent_bookings` must also not be exceeded by the count of simultaneously-active (reserved or stored) bookings across all of that host's locations, else `ERR_HOST_CONCURRENCY_EXCEEDED`. On success the booking is created in `RESERVED`, its day-capacity is reserved on the location for the interval, and the location's `version` is incremented by one — which is precisely why a later booking with a now-stale `expected_location_version` is refused. At creation `overage_days` and `late_fee_cents` are 0 and `final_total_cents` is null; these materialize only at settlement.

At creation the booking's `estimated_total_cents` is computed by the forward-looking estimate. The base storage component is the location's `per_bag_day_rate_cents` multiplied by `bag_count` and by `billable_days`. The oversize component is the location's `oversize_surcharge_cents_per_day` multiplied by `oversize_count` and by `billable_days`. The insurance component is the plan's `premium_cents_per_bag_day` multiplied by `bag_count` and by `billable_days`, and is zero whenever the plan tier is `NONE`. The estimate is the sum of these three components, in whole cents. This provisional estimate uses the requested pickup date and the declared bag sizes; it deliberately ignores any actual pickup date and any late fee, which only materialize at settlement. Bookings can be retrieved individually and listed with reverse-lookup filters on `traveler_id`, `location_id`, `host_id`, `insurance_plan_id`, and `status`.

Before drop-off, a traveler who owns a booking may cancel it, transitioning `RESERVED → CANCELLED`. Cancellation is permitted only while the booking is still `RESERVED` — that is, not yet dropped off; an attempt to cancel a booking that has already been dropped off or has reached a terminal state is rejected with `ERR_CANCEL_NOT_ALLOWED`, and a traveler cancelling a booking they do not own receives `ERR_NOT_BOOKING_OWNER`. Cancellation cascades every bag of the booking to `VOIDED` and releases the booking's reserved day-capacity back to the location, restoring the conservation invariant of §2.7.

### 3.4. Drop-off and Chain of Custody

When the traveler arrives, the host that owns the booking's location receives the bags, transitioning the booking `RESERVED → STORED`. A host acting on a booking whose location it does not own is rejected with `ERR_NOT_LOCATION_HOST`, and if the location is no longer `OPEN` the drop-off is rejected with `ERR_LOCATION_NOT_OPEN`. Drop-off is where the chain of custody begins: the request supplies a `seals` array that must provide exactly one entry per bag, each carrying a non-empty `seal_code` and a non-empty `photo_url`. If the `seals` array does not cover every bag with both a seal code and a photo, the drop-off is rejected with `ERR_BAG_NOT_SEALED`. No supplied `seal_code` may duplicate the seal of another already-sealed bag at the same location; a collision is rejected with `ERR_DUPLICATE_SEAL`. On success each bag transitions `AWAITING_DROP → SEALED`, recording its `seal_code` and its `drop_photo_url` from the matching seal entry, and the booking's `dropoff_at` is stamped from the logical clock.

### 3.5. Extensions

A traveler who owns a booking may request to keep the bags longer by requesting an extension, supplying the desired `new_check_out_date`. The extension is created in `REQUESTED`, capturing the booking's current pickup date as `previous_check_out_date` and computing `added_days` as the number of days between the previous and the new pickup dates. The `new_check_out_date` must be strictly after the current pickup date, or the request is rejected with `ERR_EXTENSION_INVALID_DATE`.

A host that owns the booking's location, or a platform admin, then decides the request by supplying a `decision`. Confirming transitions the extension `REQUESTED → CONFIRMED`; rejecting transitions it `REQUESTED → REJECTED`. A decider who is a host not owning the location is rejected with `ERR_NOT_LOCATION_HOST`. Confirmation additionally requires that the booking be `STORED` — an extension cannot be confirmed on a booking that is not currently in storage, else `ERR_INVALID_STATE` — and that the location's `daily_bag_capacity` hold on every day of the added interval, from the previous pickup date up to the new one, for this booking's bags — and, for the booking's oversize bags, that the `oversize_capacity` sub-limit also hold across that interval; a shortfall of the former is `ERR_CAPACITY_EXCEEDED` and of the latter `ERR_OVERSIZE_CAPACITY_EXCEEDED`. On confirmation the booking's `check_out_date` is advanced to the `new_check_out_date`, the booking's `billable_days` and `estimated_total_cents` are recomputed to include the added days, the location reserves capacity for the added interval, and the extension records its `added_cost_cents`. That incremental cost covers the added days only: it is the sum, over `added_days`, of the per-day storage charge (`per_bag_day_rate_cents` times `bag_count`), the per-day oversize surcharge (`oversize_surcharge_cents_per_day` times `oversize_count`), and the per-day insurance premium (`premium_cents_per_bag_day` times `bag_count`). Rejecting an extension leaves the booking untouched — its pickup date and all derived amounts are unchanged. A booking's extensions can be listed, optionally filtered by `status`.

### 3.6. Overdue Sweep, Pickup, and Final Settlement

Whenever the platform admin advances the logical clock, the system sweeps: every booking still in `STORED` whose scheduled pickup date has passed the new current date — that is, whose `check_out_date` is strictly earlier than the new current calendar date, so a pickup date equal to the current date is not yet swept — is transitioned `STORED → OVERDUE`, and the count of bookings swept is returned as `overdue_swept_count`. Overdue is not terminal — an overdue booking is retrieved normally; it simply signals that pickup is late and a late fee will apply.

The owning host returns the bags at pickup, transitioning the booking to `COMPLETED` from either `STORED` or `OVERDUE`. A host that does not own the booking's location is rejected with `ERR_NOT_LOCATION_HOST`. Pickup may optionally carry `presented_seals`; when supplied, every presented `seal_code` must match the value recorded for that bag at drop-off, and any mismatch is rejected with `ERR_SEAL_TAMPERED`. On success each bag transitions `SEALED → RETRIEVED`, the booking's `pickup_at` is stamped from the logical clock, and the booking's final charges are settled.

Final settlement recomputes the storage, oversize, and insurance components exactly as the estimate does, but on the sealed reality and the actual pickup date, and adds a late fee. The `billable_days` is again the day count between check-in and the (possibly extended) check-out, floored at 1. The base storage component is `per_bag_day_rate_cents` times `bag_count` times `billable_days`; the oversize component is `oversize_surcharge_cents_per_day` times `oversize_count` times `billable_days`, where `oversize_count` reflects the actual sealed classification of the bags; the insurance component is `premium_cents_per_bag_day` times `bag_count` times `billable_days`. The booking's `overage_days` is the number of days between the scheduled check-out date and the actual pickup date, floored at 0 so that an on-time or early pickup incurs none. The `late_fee_cents` is `overage_days` multiplied by a late-fee multiplier of 2, multiplied by `per_bag_day_rate_cents`, multiplied by `bag_count`. The booking's `final_total_cents` is the sum of the base, oversize, insurance, and late-fee components; it is null until the booking completes. This final figure diverges from the earlier estimate whenever the pickup is late or the sealed oversize classification differs from what the traveler declared.

Pickup then triggers a cascade. First, a `Payout` is created for the host in `PENDING` status via the provisional payout calculation of §3.7. Second, that payout's net amount is added to the host's `pending_payout_cents` and to its `lifetime_earnings_cents`. Both the payout creation and the host-balance update are binding side effects of the single pickup operation.

### 3.7. Payouts: Provisional Credit, Release, and Reversal

A payout links a `host_id` to the source `booking_id` and captures the host's earnings from that booking. Its `gross_cents` is the host-eligible revenue: the base storage component plus the oversize component plus the late fee — the insurance premium is excluded, as it belongs to the platform. Its `platform_fee_cents` is the commission, computed as the gross times the host's `platform_fee_bps` divided by 10000, rounded half up to whole cents, and this rounding happens per booking before the net is folded into any host total. Its `claim_deduction_cents` starts at zero. Its `net_cents` is the gross minus the platform fee minus the claim deduction. At creation, with no approved claim yet, the claim deduction is zero and the net is simply gross minus fee; this is the provisional net. After one or more claims on the booking are approved, the deduction grows and the net drops by that same sum — the same gross yielding a different, final net.

A platform admin releases a pending payout, transitioning `PENDING → RELEASED`, but only under two conditions. No claim on the payout's booking may be in `OPEN`, `UNDER_REVIEW`, or `NEEDS_INFO` — an unresolved claim blocks release with `ERR_PAYOUT_HAS_OPEN_CLAIM`. And the release must not be premature: the current date must be at least the booking's pickup date plus a hold of 2 days, otherwise `ERR_PAYOUT_HELD`. Releasing a payout moves its net amount out of the host's `pending_payout_cents` and into its `payout_balance_cents`. A platform admin may afterward reverse a released payout, transitioning `RELEASED → REVERSED`; reversal is a compensation that subtracts the net amount back out of the host's `payout_balance_cents`, leaving the ledger conserved with no drift. Payouts are retrievable individually and listable with reverse-lookup filters on `host_id`, `booking_id`, and `status`.

### 3.8. Claims Lifecycle and Coverage

After a booking completes, a traveler who owns it may file a claim against one of its bags, supplying the affected `bag_id`, a `reason` of `DAMAGE`, `LOSS`, or `THEFT`, a free-text `description`, and a `claimed_amount_cents`. A claim may only be filed on a `COMPLETED` booking — otherwise `ERR_BOOKING_NOT_COMPLETED` — and only when the booking's insurance plan tier is not `NONE`; a claim against an uninsured booking is rejected with `ERR_NO_INSURANCE_COVERAGE`. The claim must be filed within a window of 3 days after the booking's `pickup_at`; a later filing is rejected with `ERR_CLAIM_WINDOW_CLOSED`. The `claimed_amount_cents` must be greater than zero and no more than the bag's `declared_value_cents`, else `ERR_CLAIM_AMOUNT_INVALID`. A filed claim starts in `OPEN`, with `approved_amount_cents` null until it is approved. Claims are retrievable individually and listable with reverse-lookup filters on `booking_id`, `bag_id`, and `status`.

A claim advances through a review cycle. A host or platform admin opens review, transitioning `OPEN → UNDER_REVIEW`. From under review, the reviewer may request more information, transitioning `UNDER_REVIEW → NEEDS_INFO`. The owning traveler then resubmits, transitioning `NEEDS_INFO → UNDER_REVIEW`; a traveler who does not own the claim's booking is rejected with `ERR_NOT_BOOKING_OWNER`. This revision loop may repeat any number of times — a claim may cycle between `UNDER_REVIEW` and `NEEDS_INFO` freely — until an adjudication is reached.

Only a platform admin adjudicates a claim from under review, supplying a `decision`. Rejecting transitions the claim `UNDER_REVIEW → REJECTED` with no payout adjustment. Approving transitions it `UNDER_REVIEW → APPROVED` and requires an `approved_amount_cents`. The approved amount is bounded by a coverage cap: the smallest of the plan's `per_bag_coverage_cents`, the bag's `declared_value_cents`, and the traveler's `claimed_amount_cents`. The supplied `approved_amount_cents` must be greater than zero (a non-positive value is rejected with `ERR_VALIDATION`) and no more than that cap; an amount exceeding the cap is rejected with `ERR_COVERAGE_CAP_EXCEEDED`. On approval the claim's `approved_amount_cents` is recorded, and a three-hop cascade fires. First, the payout whose booking matches the claim's booking has its `claim_deduction_cents` increased by the approved amount and its `net_cents` recomputed downward. Second, the host's `pending_payout_cents` is reduced by the approved amount; if this drives the host's pending balance below zero, the system suspends the host, transitioning it `ACTIVE → SUSPENDED`. Third, upon that host suspension, every location of the host currently in `OPEN` is transitioned to `SUSPENDED` by the system.

### 3.9. Ratings

Once a booking is `COMPLETED`, the traveler who owns it may leave exactly one rating, supplying an integer `score` from 1 through 5 and an optional free-text `comment`. Rating a booking that is not completed is rejected with `ERR_BOOKING_NOT_COMPLETED`, and a second rating on the same booking is rejected with `ERR_RATING_ALREADY_EXISTS`. Recording a rating updates the host's running aggregates: the `score` is added to the host's `rating_sum`, the host's `rating_count` is incremented by one, and the host's `avg_rating` is recomputed as `rating_sum` divided by `rating_count`, rounded half up to two decimals — and is zero whenever the host has no ratings. A booking's rating is retrievable as an array of zero or one entry keyed on the rated booking.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource, and all reads, return HTTP 200. Request and response bodies follow the envelope of §2.2; the specific inputs and side effects of each operation are described in the §3 narratives above rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock; sweep overdue bookings | PlatformAdmin |
| POST | `/hosts` | Onboard a host | PlatformAdmin |
| GET | `/hosts/{id}` | Get a host | Traveler, Host, PlatformAdmin |
| POST | `/hosts/{id}/status` | Suspend or reactivate a host | PlatformAdmin |
| POST | `/travelers` | Self-register a traveler (no auth headers) | Anonymous |
| GET | `/travelers/{id}` | Get a traveler | Traveler, PlatformAdmin |
| POST | `/insurance-plans` | Create an insurance plan tier | PlatformAdmin |
| GET | `/insurance-plans/{id}` | Get an insurance plan | Traveler, Host, PlatformAdmin |
| POST | `/hosts/{id}/locations` | Create a location under a host | Host, PlatformAdmin |
| GET | `/locations/{id}` | Get a location | Traveler, Host, PlatformAdmin |
| GET | `/hosts/{id}/locations` | List a host's locations | Traveler, Host, PlatformAdmin |
| POST | `/locations/{id}/status` | Transition location status | Host, PlatformAdmin |
| POST | `/bookings` | Create a booking | Traveler |
| GET | `/bookings/{id}` | Get a booking | Traveler, Host, PlatformAdmin |
| GET | `/bookings` | List/filter bookings | Traveler, Host, PlatformAdmin |
| POST | `/bookings/{id}/cancel` | Cancel a reserved booking | Traveler |
| POST | `/bookings/{id}/dropoff` | Drop off and seal bags | Host |
| POST | `/bookings/{id}/pickup` | Return bags; settle and create payout | Host |
| GET | `/bags/{id}` | Get a bag | Traveler, Host, PlatformAdmin |
| GET | `/bookings/{id}/bags` | List a booking's bags | Traveler, Host, PlatformAdmin |
| POST | `/bookings/{id}/extensions` | Request an extension | Traveler |
| POST | `/extensions/{id}/decide` | Confirm or reject an extension | Host, PlatformAdmin |
| GET | `/bookings/{id}/extensions` | List a booking's extensions | Traveler, Host, PlatformAdmin |
| POST | `/bookings/{id}/claims` | File a claim on a bag | Traveler |
| GET | `/claims/{id}` | Get a claim | Traveler, Host, PlatformAdmin |
| GET | `/claims` | List/filter claims | Traveler, Host, PlatformAdmin |
| POST | `/claims/{id}/review` | Open review of a claim | Host, PlatformAdmin |
| POST | `/claims/{id}/request-info` | Request more info on a claim | Host, PlatformAdmin |
| POST | `/claims/{id}/resubmit` | Resubmit claim info | Traveler |
| POST | `/claims/{id}/decide` | Adjudicate a claim | PlatformAdmin |
| GET | `/payouts/{id}` | Get a payout | Host, PlatformAdmin |
| GET | `/payouts` | List/filter payouts | Host, PlatformAdmin |
| POST | `/payouts/{id}/release` | Release a pending payout | PlatformAdmin |
| POST | `/payouts/{id}/reverse` | Reverse a released payout | PlatformAdmin |
| POST | `/bookings/{id}/rating` | Rate a completed booking | Traveler |
| GET | `/bookings/{id}/rating` | Get a booking's rating | Traveler, Host, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_INVALID_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_NOT_LOCATION_HOST` | 403 |
| `ERR_NOT_BOOKING_OWNER` | 403 |
| `ERR_STALE_LOCATION_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOCATION_NOT_OPEN` | 409 |
| `ERR_HOST_SUSPENDED` | 409 |
| `ERR_LOCATION_HAS_ACTIVE_BOOKINGS` | 409 |
| `ERR_CANCEL_NOT_ALLOWED` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_EXTENSION_INVALID_DATE` | 422 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_BAG_NOT_SEALED` | 409 |
| `ERR_DUPLICATE_SEAL` | 409 |
| `ERR_SEAL_TAMPERED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_OVERSIZE_CAPACITY_EXCEEDED` | 409 |
| `ERR_HOST_CONCURRENCY_EXCEEDED` | 409 |
| `ERR_NO_INSURANCE_COVERAGE` | 409 |
| `ERR_CLAIM_AMOUNT_INVALID` | 422 |
| `ERR_COVERAGE_CAP_EXCEEDED` | 422 |
| `ERR_PAYOUT_HAS_OPEN_CLAIM` | 409 |
| `ERR_PAYOUT_HELD` | 409 |
| `ERR_BOOKING_NOT_COMPLETED` | 409 |
| `ERR_RATING_ALREADY_EXISTS` | 409 |
