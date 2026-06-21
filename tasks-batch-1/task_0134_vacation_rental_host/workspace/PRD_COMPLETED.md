# Vacation Rental Host API — Product Requirements Document

## 1. Introduction

Independent short-term-rental hosts juggle a fragmented operational reality: the same calendar is advertised on Airbnb, VRBO, Booking.com, and their own direct site, while nightly prices swing with season and weekend demand, guests arrive with uneven trustworthiness, and money flows in several directions at once — guest charges in, host payouts out, refundable deposits parked in escrow, and the occasional damage claim drawn back against them. This service is the system of record that ties those threads together. It owns a host's listings and their seasonal pricing, mirrors each listing's availability out to the external channels it is connected to, screens incoming booking requests, prices and books stays, holds and settles security deposits, and schedules and releases host payouts.

The platform is built around a small number of long-lived aggregates — a `Host`, the `Listing` entities they own, the `Guest` who books, and the `Booking` that links a guest to a listing for a set of dates — surrounded by satellite records (rate plans, channel connections, calendar blocks, screening results, security deposits, damage claims, payouts, and imported reservations) that hang off those aggregates by foreign key. Because availability and money are both at stake, almost every meaningful action triggers a chain of consequences across several of these records, and the platform guarantees that each such chain either completes in full or not at all within the request that started it. The remainder of this document specifies the global contract every endpoint honors, the business logic that governs each lifecycle, the full endpoint surface, and the error vocabulary.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the open registration and clock endpoints must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. The four recognized roles are `Host`, `Guest`, `PlatformAdmin`, and `Anonymous`. If either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present and well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of the roles are entity-backed. When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`; ownership checks on any resource that references a `Host` compare the resource's owning-host foreign key to `X-User-ID`. Concretely, a listing's `host_id`, and transitively any rate plan, channel connection, calendar block, booking, deposit, claim, or payout that descends from that listing, are owned by the host whose `id` equals the listing's `host_id`. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`; ownership checks on any resource that references a `Guest` compare the resource's `guest_id` to `X-User-ID`, so a guest may act only on a `Booking` whose `guest_id` equals their own `id` and on the deposits and claims descending from it.

The other two roles are opaque. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. `PlatformAdmin` is the operational role that runs channel synchronization, imports reservations, reviews and settles damage claims, manages payouts, and controls the test-driving clock. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity; the anonymous caller may only register a host, register a guest, or set the clock. When an entity-backed caller is authenticated and authorized for the operation's role but is acting on a resource they do not own — a host on a listing whose `host_id` is not their `id`, or a guest on a booking whose `guest_id` is not their `id` — the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and represents the number of leading records to skip. Results are always returned in `created_at` ascending order — that is, oldest first — before pagination is applied. For every list response, the `meta` object carries `limit`, `offset`, `total_count` (the number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and Mutation Semantics

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by exactly 1 each time the resource is mutated. Clients never supply `id`, `created_at`, `updated_at`, or `version`; the server controls all four.

A note on the `Listing` entity is warranted because it tracks two independent counters. Its common `version` field increments on any listing mutation in the usual way. Separately, the `Listing` also carries `calendar_version`, a dedicated optimistic-concurrency counter that starts at 1 and advances by 1 every time an `ACTIVE` calendar block is created on the listing or an `ACTIVE` block is released. These two counters are distinct and move on different events; `calendar_version` exists specifically to detect stale calendar views (see §2.6).

### 2.5. Monetary Precision and Rounding

All money in this system is expressed in integer cents — there are no fractional-cent fields. Wherever a calculation multiplies cents by a multiplier or a rate (always supplied in basis points, where 10000 basis points equals a factor of 1.0), the intermediate product is rounded to the nearest whole cent using round-half-up (a value exactly at the half rounds upward), and the rounding boundaries are pinned per calculation as described in §3. Pure additions and subtractions of already-integer cent amounts are exact and introduce no further rounding. Where a result could otherwise go negative, the specific rule states the floor explicitly.

### 2.6. Optimistic Concurrency on the Calendar

Two write operations are guarded by optimistic concurrency control against the parent `Listing`'s `calendar_version`, because both consume calendar availability and a stale view could place a block on a now-occupied range. Each requires the client to send `expected_listing_calendar_version` carrying the `calendar_version` value the client last observed for the target listing.

When a manual calendar block is created on a listing, the request must include `expected_listing_calendar_version`, and it must equal the live `calendar_version` of that listing. If another writer has created or released an `ACTIVE` block since the client last read the calendar — advancing `calendar_version` — the values disagree and the create is rejected with `ERR_STALE_CALENDAR_VERSION` (HTTP 412). Likewise, creating a booking (which synthesizes a booking-origin calendar block) requires `expected_listing_calendar_version` to equal the listing's live `calendar_version`; if the calendar has moved forward since the guest read availability, the booking request is rejected with `ERR_STALE_CALENDAR_VERSION` (HTTP 412). Endpoints other than these two manual-block and booking creations do not accept or require a calendar-version field.

### 2.7. Cascades, Channel Propagation, and Consistency

Many operations mutate more than one record, and every such cascade completes atomically within the request that triggered it — partial application is never observed. Whenever an `ACTIVE` calendar block is created or released on a listing (whether manually, through a booking, through an import, or through a booking cancellation or decline), the listing's `calendar_version` advances by 1 and, as a propagation hop, every `ChannelConnection` on that listing whose `status` is `CONNECTED` or `ERROR` has its `pending_sync_count` incremented by 1 to record that a local calendar change is awaiting push to that channel. A `ChannelConnection` whose `status` is `DISCONNECTED` or `SYNCING` is not bumped. Each mutated record's `updated_at` is refreshed and its `version` incremented as part of the same atomic step. The full booking-cancellation chain, the damage-claim settlement chain, and the import flow are detailed in §3.

### 2.8. Nested Resource Addressing

Several resources are addressed through a parent path — for example a listing's calendar blocks, a channel connection's imported reservations, or a security deposit's claims. Path parameters are validated left to right: the parent id is resolved first, and if any path-referenced resource does not exist the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any deeper validation runs. Body foreign keys — `listing_id`, `guest_id`, `security_deposit_id`, `channel_connection_id`, and `booking_id` where they appear in a request body — are validated separately: if a body foreign key names a resource that does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.9. Validation Ordering

When several checks could fire on a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path-referenced resource (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_FK_NOT_FOUND`), then resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`), then whether the requested state transition is defined from the resource's current state (`ERR_INVALID_STATE`). Domain-specific business checks are evaluated only after all of the foregoing pass: listing bookability, screening outcome, date-range validity, minimum-night length, availability and gap, rate-plan overlap, claim-amount validity, payout due-time, the cross-entity claim gate on payout release, the calendar optimistic-concurrency check, and finally generic body validation. The precise trigger and code for each business check is stated alongside the workflow it guards in §3; generic structural problems — a missing required field, a wrong type, or an unrecognized enum value — are reported as `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Hosts, Listings, and Seasonal Pricing

A `Host` registers with an `email` (which must be non-empty; uniqueness is not enforced, so two hosts may share an email) and a `display_name`, and may name a `payout_method`; when the payout method is omitted it defaults to `BANK_TRANSFER`, and the only accepted values are `BANK_TRANSFER` and `PAYPAL`. Registration is open to anonymous callers.

A host creates a `Listing` by supplying its `host_id`, a `title`, a `base_nightly_rate_cents` (which must be strictly greater than zero), and a `cleaning_fee_cents` (which must be zero or greater). A number of pricing and policy parameters are optional at creation and take defaults when omitted: `pet_fee_cents` defaults to 0 and must be zero or greater; `tax_rate_bps`, the occupancy-tax rate in basis points, defaults to 0 and must be between 0 and 2000 inclusive; `min_nights` defaults to 1 and must be at least 1; `gap_nights`, the required turnaround buffer between stays, defaults to 0 and must be zero or greater; `cancellation_tier` defaults to `MODERATE` and must be one of `FLEXIBLE`, `MODERATE`, or `STRICT`; `security_deposit_cents` defaults to 0 and must be zero or greater; `platform_commission_bps` defaults to 1500 and must be between 0 and 3000 inclusive; and `payout_delay_days` defaults to 1 and must be zero or greater. A new listing is created in `DRAFT` with its `calendar_version` initialized to 1. The owning host is the principal whose `id` equals `host_id`.

A listing's seasonal pricing is expressed through `RatePlan` records. A host creates a rate plan by naming the `listing_id` it applies to, a human `label` such as a season name, an inclusive `window_start` and an inclusive `window_end` (both ends are part of the window — a closed date interval), and a `seasonal_multiplier_bps` between 1 and 50000 inclusive. An optional `weekend_multiplier_bps`, applied additionally to Friday and Saturday nights, defaults to 10000 (a factor of 1.0) and must likewise be between 1 and 50000 inclusive. Before a rate plan is created its window is checked against the listing's existing rate plans: if the new closed interval `[window_start, window_end]` overlaps the closed interval of any existing rate plan on the same listing, the create is rejected with `ERR_RATE_PLAN_OVERLAP` (HTTP 409). This overlap test treats both endpoints as inclusive and applies no turnaround buffer. The window's own dates must also be valid, with `window_end` strictly after `window_start`; otherwise `ERR_INVALID_DATE_RANGE` (HTTP 422) is returned.

Publishing a listing advances it from `DRAFT` to `LISTED`. The host must own the listing, and the listing must have at least one rate plan whose `[window_start, window_end]` coverage is non-empty; an attempt to publish from a state where the transition is not defined yields `ERR_INVALID_STATE` (HTTP 409). Once `LISTED`, a host may snooze the listing, moving it to `SNOOZED`; a snoozed listing rejects new booking requests but keeps its existing bookings intact. The same publish action un-snoozes a listing, returning it from `SNOOZED` to `LISTED`. Each of these three transitions increments the listing's common `version` by 1. Throughout, only the owning host may publish or snooze; a non-owner is met with `ERR_NOT_RESOURCE_OWNER`.

### 3.2. Channel Connections and Calendar Synchronization

To mirror a listing's availability outward, a host registers a `ChannelConnection` by supplying the `listing_id` and the `channel`, which must be one of `AIRBNB`, `VRBO`, `BOOKINGCOM`, or `DIRECT`. A new connection begins `DISCONNECTED` with `pending_sync_count` at 0 and `last_synced_at` null. The owning host connects it, moving `DISCONNECTED` to `CONNECTED`. The same connect action recovers a connection from `ERROR` back to `CONNECTED`. Each transition that the connection undergoes increments its `version` by 1.

Synchronization is operated by a `PlatformAdmin`. Beginning a sync round moves a connection from `CONNECTED` to `SYNCING`. Finishing the round successfully moves it from `SYNCING` back to `CONNECTED`, and as it lands it sets `pending_sync_count` to 0 and sets `last_synced_at` to the current clock instant. A round that fails moves the connection from `SYNCING` to `ERROR` and, importantly, preserves the accumulated `pending_sync_count` rather than clearing it — the unsynced changes are still pending. A connection in `CONNECTED` or `ERROR` is the set of channels that accrues pending changes: whenever the listing's calendar changes (any `ACTIVE` block created or released), every such connection has its `pending_sync_count` incremented by 1. Any transition attempted from a state where it is not defined returns `ERR_INVALID_STATE`.

A `PlatformAdmin` may import an external reservation onto a connection. The import supplies an `external_ref` (the opaque reservation id from the channel, which must be unique among reservations on the same connection), a `start_date`, and a `end_date` (exclusive, and strictly after the start). If a reservation with the same `external_ref` already exists on that `channel_connection_id`, the import is rejected with `ERR_DUPLICATE_EXTERNAL_REF` (HTTP 409). The imported interval is then tested against the listing's calendar: if the requested `[start_date, end_date)` overlaps any `ACTIVE` calendar block or violates the listing's `gap_nights` turnaround buffer, the `ImportedReservation` is recorded with `import_status` of `REJECTED_OVERLAP` and its `calendar_block_id` left null — no block is created. Otherwise the import succeeds with `import_status` of `ACCEPTED`: a fresh `IMPORTED`-source calendar block is created in `ACTIVE`, the reservation's `calendar_block_id` points at it, the listing's `calendar_version` advances by 1, and every `CONNECTED` or `ERROR` channel on the listing — including the channel the reservation was imported onto, if it is itself `CONNECTED` or `ERROR` — has its `pending_sync_count` bumped by 1.

### 3.3. The Calendar Block as the Availability Primitive

Every claim on a listing's dates — whether from a guest booking, a host's manual block-off, or an imported reservation — is recorded as a `CalendarBlock`. A block names its `listing_id`, its `source` (one of `BOOKING`, `MANUAL`, or `IMPORTED`, distinguishing where the block came from), a `start_date`, and an `end_date`; the occupied interval is half-open, covering `start_date` up to but not including `end_date`, so a checkout day is free for the next arrival. The `end_date` must be strictly after `start_date`, else `ERR_INVALID_DATE_RANGE`. A block begins `ACTIVE` and may later become `RELEASED`; these are its only two states.

A host may create a `MANUAL` block directly on a listing to hold dates off the market. Because this consumes availability, the create is optimistic-concurrency-guarded: the request supplies `source`, `start_date`, `end_date`, and `expected_listing_calendar_version`, and that expected value must equal the listing's live `calendar_version` or the create fails with `ERR_STALE_CALENDAR_VERSION` (HTTP 412), as described in §2.6. Before the block is created, its interval is tested for availability: the requested half-open `[start_date, end_date)` must not overlap any existing `ACTIVE` block on the listing, and it must honor the listing's `gap_nights` buffer on both sides — there must be at least `gap_nights` nights of clearance between this interval and the nearest `ACTIVE` block before it and after it. A violation of either the overlap rule or the gap buffer yields `ERR_DATES_UNAVAILABLE` (HTTP 409). On success the `ACTIVE` block is created, the listing's `calendar_version` advances by 1, the listing's common `version` increments by 1, and each `CONNECTED` or `ERROR` channel's `pending_sync_count` is bumped by 1.

Releasing a block moves it from `ACTIVE` to `RELEASED`. A host may release a `MANUAL` block directly; doing so advances the listing's `calendar_version` by 1, bumps each `CONNECTED` or `ERROR` channel's `pending_sync_count` by 1, and increments the block's own `version` by 1. A block whose `source` is `BOOKING`, however, may never be released through the manual release action — such a block is released only as part of the booking decline or cancel cascade. A manual-release attempt on a booking-origin block is rejected with `ERR_RELEASE_BOOKING_BLOCK` (HTTP 409), and any release attempt on a block not currently `ACTIVE` is rejected with `ERR_INVALID_STATE`. The booking-origin guard is evaluated before the `ACTIVE`-state guard, so a release attempt on a `BOOKING`-source block that is already `RELEASED` still yields `ERR_RELEASE_BOOKING_BLOCK` rather than `ERR_INVALID_STATE`.

### 3.4. Booking Requests: Pricing and Reservation

A `Guest` registers with a non-empty `email` (uniqueness is not enforced, so two guests may share an email) and a `full_name`, and may supply three screening attributes at creation, each defaulting if omitted: `govt_id_verified` (whether the guest completed government-ID verification) defaults to false; `prior_cancellations` (the count of guest-initiated cancellations in the trailing twelve months) defaults to 0 and must be zero or greater; and `chargeback_flag` (whether the guest has an unresolved payment chargeback on file) defaults to false. The guest's `risk_score` is a computed weighted score that remains uncomputed until the guest's first screening run; thereafter it holds a value between 0.00 and 100.00 with two decimal places.

A guest creates a `Booking` by naming the `listing_id`, the `guest_id`, a `check_in` date, a `check_out` date, an optional `pets_count` (defaulting to 0, zero or greater), and `expected_listing_calendar_version`. Several gates apply in turn. The target listing must be `LISTED` — a `SNOOZED` or `DRAFT` listing rejects the request with `ERR_LISTING_NOT_BOOKABLE` (HTTP 409). The `check_out` must be strictly after `check_in` and both must be valid dates, else `ERR_INVALID_DATE_RANGE`. The stay length, `nights`, is the number of nights from check-in to checkout; it must be at least the listing's `min_nights`, and a shorter stay is rejected with `ERR_MIN_NIGHTS` (HTTP 422). The requested half-open interval must not overlap any `ACTIVE` block and must honor the `gap_nights` buffer on both sides, else `ERR_DATES_UNAVAILABLE`. And `expected_listing_calendar_version` must match the listing's live `calendar_version`, else `ERR_STALE_CALENDAR_VERSION`.

When all gates pass, the booking is priced and reserved in one atomic step. The system computes the nightly subtotal by walking each night in the stay — every date from check-in up to but not including checkout. For each such night it selects the rate plan on the listing whose closed window `[window_start, window_end]` contains that date. If two rate plans both contain the date, the booking is rejected with `ERR_RATE_PLAN_OVERLAP`; if no plan contains the date, that night uses a seasonal multiplier of 10000 basis points and a weekend multiplier of 10000 basis points (each a factor of 1.0). With a plan in hand, the seasonal multiplier for the night is the plan's `seasonal_multiplier_bps`, and the weekend multiplier is the plan's `weekend_multiplier_bps` when the date falls on a Friday or Saturday and 10000 basis points otherwise. The price for that single night is the `base_nightly_rate_cents` multiplied by the seasonal multiplier divided by 10000 and then by the weekend multiplier divided by 10000, with that per-night amount rounded to whole cents using round-half-up before it is added in. Each night is rounded individually and then the rounded per-night prices are summed; the resulting sum is the booking's `nightly_subtotal_cents`.

On the same request the booking's fees and tax are computed. The `fees_cents` is the listing's `cleaning_fee_cents` plus, only when `pets_count` is greater than zero, the listing's `pet_fee_cents`; with no pets only the cleaning fee applies. The taxable base is `nightly_subtotal_cents` plus `fees_cents`. The `tax_cents` is that taxable base multiplied by the listing's `tax_rate_bps` divided by 10000, rounded once with round-half-up after the base has been summed (the tax is not rounded per component). The guest grand total, `total_cents`, is the exact integer sum of `nightly_subtotal_cents`, `fees_cents`, and `tax_cents`. At request time the booking also takes `cancellation_tier_snapshot`, a copy of the listing's `cancellation_tier`, so that refunds remain stable even if the listing later changes tier. Reservation completes the step: a fresh `BOOKING`-source calendar block is created `ACTIVE`, the booking's `calendar_block_id` is set to it, the listing's `calendar_version` advances by 1, each `CONNECTED` or `ERROR` channel's `pending_sync_count` is bumped by 1, and the booking enters `REQUESTED`. The booking's `refund_cents` begins at 0 and stays 0 until a cancellation settles it.

A host or guest may preview pricing without booking through a computed quote on a listing for a date range, supplying `check_in`, `check_out`, and an optional `pets_count`. The quote returns `nightly_subtotal_cents`, `fees_cents`, `tax_cents`, and `total_cents` computed by the identical pricing and total rules above, but creates nothing and reserves no dates.

### 3.5. Guest Screening

Screening begins when the owning host moves a booking from `REQUESTED` to `SCREENING`. This is permitted only while the booking is `REQUESTED` and only for the host who owns the booking's listing; otherwise `ERR_INVALID_STATE` or `ERR_NOT_RESOURCE_OWNER` applies. Screening creates a `ScreeningResult` referencing the `booking_id` and the `guest_id`, initially `PENDING`, then runs the guest risk computation and resolves the result to either `PASSED` or `FAILED` within the same request. The booking's `version` increments by 1 as it enters `SCREENING`.

The guest risk computation produces a higher number for a riskier guest. It starts at zero and adds 15 points for each of the guest's `prior_cancellations`, adds 60 points if the guest's `chargeback_flag` is set, and adds 40 points if the guest's `govt_id_verified` is false (a verified guest adds nothing on that count). The running total is then capped at 100 — if it would exceed 100 it is held at 100 — and rounded with round-half-up to two decimal places. This value is written as the guest's `risk_score` and snapshotted onto the screening result's `computed_risk_score`.

The screening result resolves to `PASSED` only when all three conditions hold: the guest's `govt_id_verified` is true, the guest's `chargeback_flag` is false, and the computed risk score is strictly less than 50. On a pass, `status` becomes `PASSED` and `failure_reason` is `NONE`. If any of the three conditions is violated the result is `FAILED`, and its `failure_reason` is set to the single dominant disqualifier chosen by a fixed precedence: an unverified government ID (`ID_UNVERIFIED`) takes precedence over a chargeback (`CHARGEBACK`), which in turn takes precedence over crossing the risk threshold (`RISK_THRESHOLD`). The four recognized values for `failure_reason` are `NONE`, `ID_UNVERIFIED`, `CHARGEBACK`, and `RISK_THRESHOLD`.

From `SCREENING` the host has three moves. The host may bounce the request back for more guest information, returning the booking from `SCREENING` to `REQUESTED`; this discards the latest screening result rather than marking it failed — a subsequent screen run creates a fresh one. The host may approve, advancing `SCREENING` to `APPROVED`, but approval is gated on the booking's latest screening result being `PASSED`; an approve attempt while the latest result is not `PASSED` is rejected with `ERR_SCREENING_NOT_PASSED` (HTTP 409). Or the host may decline, advancing `SCREENING` to `DECLINED` (a terminal state): declining releases the booking's calendar block (the block's `status` becomes `RELEASED` and the booking's `calendar_block_id` is set to null), advances the listing's `calendar_version` by 1, and bumps each `CONNECTED` or `ERROR` channel's `pending_sync_count` by 1. Each of these three transitions increments the booking's `version`. Every screening-related transition requires the acting host to own the booking's listing.

### 3.6. Confirmation, Stay, and Completion

Once a booking is `APPROVED`, the booking's own guest confirms it, advancing `APPROVED` to `CONFIRMED`. Confirmation requires that the acting guest is the booking's `guest_id` and that the booking's calendar block is still `ACTIVE`. Confirmation sets two satellite records in motion in one atomic step. First, a `SecurityDeposit` is created for the booking in `AUTHORIZED`, with its `authorized_cents` snapshotted from the listing's `security_deposit_cents` and its `held_cents` initialized to that same authorized amount. Second, a `Payout` is created for the booking in `SCHEDULED`, naming the `booking_id` and the recipient `host_id`; its `estimated_cents` is set from the estimate variant of the payout computation, and its `release_after` is set to the booking's checkout instant plus the listing's `payout_delay_days`. The booking's `version` increments.

The payout estimate at confirmation is computed as follows. The host gross is the booking's `nightly_subtotal_cents` plus its `fees_cents` — occupancy tax is remitted, not paid to the host, so it is excluded from the gross. The platform commission is that gross multiplied by the listing's `platform_commission_bps` divided by 10000, rounded once with round-half-up. The `estimated_cents` is the gross minus the commission; no deposit deductions are known yet at confirmation, so none are applied.

A confirmed stay starts when the clock reaches check-in. The booking advances from `CONFIRMED` to `IN_STAY` either automatically when the server clock is set to an instant at or after the booking's `check_in`, or through an explicit host check-in action; in both cases the precondition is that the current clock instant is at or after `check_in` and the booking is `CONFIRMED`. When the clock is advanced, every `CONFIRMED` booking whose `check_in` is at or before the new current instant transitions to `IN_STAY`. The booking's `version` increments on the transition.

The owning host completes the stay, advancing `IN_STAY` to `COMPLETED` (terminal), provided the current clock instant is at or after the booking's `check_out`. On completion, if the booking's security deposit has no open damage claim, the deposit is released — its `status` becomes `RELEASED` and `held_cents` drops to 0. The booking's `version` increments. If a claim is still open the deposit is left as-is and its settlement proceeds through the claim lifecycle.

### 3.7. Security Deposits and Damage Claims

A `SecurityDeposit` tracks the refundable hold against a booking. It carries the `booking_id` it secures, the `authorized_cents` fixed at confirmation, and a `held_cents` that begins equal to the authorized amount and is reduced as approved claims debit it. Its lifecycle runs `AUTHORIZED`, `CLAIM_OPEN`, and the terminal `SETTLED` and `RELEASED`.

The owning host files a `DamageClaim` against a deposit, supplying the `security_deposit_id`, an `amount_cents` claimed, and a `reason` describing the damage. A claim may be filed only while the deposit is `AUTHORIZED`, only by the host who owns the booking's listing, and only while the booking is either `IN_STAY` or `COMPLETED`. The `amount_cents` must be strictly greater than zero and the deposit's `authorized_cents` must be strictly greater than zero; otherwise the filing is rejected with `ERR_INVALID_CLAIM_AMOUNT` (HTTP 422). Filing creates the claim in `FILED` with `approved_cents` at 0, and moves the deposit from `AUTHORIZED` to `CLAIM_OPEN`. A claim's lifecycle states are `FILED`, `UNDER_REVIEW`, `APPROVED`, `DISPUTED`, `DENIED`, and `VOID`.

A `PlatformAdmin` moves a claim into review, from `FILED` to `UNDER_REVIEW` (and likewise from `DISPUTED` back to `UNDER_REVIEW`, described below). From `UNDER_REVIEW` the admin may approve or deny. Approval runs a waterfall allocation over the finite deposit pool. The siblings already `APPROVED` on the same deposit, considered in `created_at` ascending order, have consumed some of the pool; the remaining pool is the deposit's `authorized_cents` minus the sum of those already-approved sibling amounts. This claim's `approved_cents` is the smaller of its own `amount_cents` and the remaining pool, where the remaining pool is treated as no less than zero. The deposit's `held_cents` is then set to its `authorized_cents` minus the total of all approved amounts including this one — equivalently, the deposit is debited by this claim's `approved_cents`. If no other non-terminal claim remains on the deposit after this approval, the deposit moves to `SETTLED`. The claim moves to `APPROVED` and its `version` increments. All amounts here are exact integer cents with no rounding.

A guest may dispute a claim. Disputing a claim that is `UNDER_REVIEW` moves it to `DISPUTED`. A guest may also dispute a claim that is already `APPROVED`, which likewise moves it to `DISPUTED` and re-opens the deposit by setting the deposit's `status` back to `CLAIM_OPEN` (a disputed claim is non-terminal again); critically, disputing an approved claim does not yet reverse the earlier `held_cents` debit — that reversal happens only on a subsequent denial. Only the booking's own guest may dispute. From `DISPUTED`, the admin reviews the claim again, returning it to `UNDER_REVIEW`.

Denial is the compensating action for an earlier approval. When the admin denies a claim from `UNDER_REVIEW`, if the claim had previously been approved (its `approved_cents` is greater than zero, the situation that arises after an approve-then-dispute cycle), the deposit's `held_cents` is increased by that `approved_cents` to restore the earlier debit so the deposit balance is conserved; the claim's `approved_cents` is then reset to 0. A claim that was never approved leaves the deposit untouched. If no other non-terminal claim remains on the deposit, the deposit moves to `SETTLED`. The claim moves to the terminal `DENIED` and its `version` increments. Separately, the deposit transitions from `CLAIM_OPEN` to `SETTLED` exactly when no claim on it remains in `FILED`, `UNDER_REVIEW`, or `DISPUTED`, at which point its `held_cents` is recomputed as `authorized_cents` minus the sum of the `approved_cents` of its approved claims, and its `version` increments. The deposit instead transitions directly from `AUTHORIZED` to `RELEASED` — with `held_cents` set to 0 — when it is cascaded closed by a booking completion with no open claim or by a booking cancellation, as long as no claim is open. Every deposit and claim state change increments the respective `version`.

### 3.8. Payout Scheduling, Holds, and Release

A `Payout` settles a booking's earnings to the host. It carries the `booking_id`, the recipient `host_id`, an `estimated_cents` set at confirmation, an `actual_cents` that stays 0 until release, and a `release_after` instant. Its lifecycle runs `SCHEDULED`, `HELD`, `RELEASED`, and the terminal `PAID` and `REVERSED`.

A `PlatformAdmin` may hold a scheduled payout, moving `SCHEDULED` to `HELD`, but only when the booking's security deposit has a damage claim in `FILED`, `UNDER_REVIEW`, or `DISPUTED`. The admin lifts a hold, moving `HELD` back to `SCHEDULED`, only once no damage claim on the deposit remains in `FILED`, `UNDER_REVIEW`, or `DISPUTED`.

Releasing a payout moves `SCHEDULED` to `RELEASED` and is the point at which the host's actual earnings are finalized. Two gates apply beyond the state check. The clock must have reached the payout's `release_after`: a release attempted before the current instant reaches `release_after` is rejected with `ERR_PAYOUT_NOT_DUE` (HTTP 409). And a cross-entity gate applies — if any damage claim on the booking's deposit is in `FILED`, `UNDER_REVIEW`, or `DISPUTED`, the release is blocked with `ERR_CLAIM_BLOCKS_PAYOUT` (HTTP 409). When both gates pass, the actual payout is computed: the same host gross (booking `nightly_subtotal_cents` plus `fees_cents`) minus the same round-half-up commission (gross times `platform_commission_bps` divided by 10000), minus the total of the `approved_cents` of every `APPROVED` damage claim on the deposit, with the result floored at zero. This value is written to `actual_cents`; it may be smaller than the `estimated_cents` recorded at confirmation precisely because of those deposit deductions. The payout's `version` increments. The admin later marks a released payout as paid, moving `RELEASED` to the terminal `PAID`.

### 3.9. Booking Cancellation and Its Cascade

A guest may cancel their own booking from either `REQUESTED` or `CONFIRMED`, both leading to the terminal `CANCELLED`. Cancellation settles the final refund and unwinds the reservation. The refundable base is the booking's `nightly_subtotal_cents` plus its `tax_cents`; cleaning and pet fees are not refundable once confirmed. The lead time is the number of whole hours between the current instant and the booking's `check_in`, taken as zero or greater — if check-in has already passed, the lead time is treated as zero. The refund percentage depends on the booking's `cancellation_tier_snapshot` and the lead time, with all thresholds inclusive at their stated boundary. Under `FLEXIBLE`, a lead time of at least 24 hours refunds 100 percent and anything less refunds 0 percent. Under `MODERATE`, a lead time of at least 120 hours refunds 100 percent, a lead time of at least 24 hours (but under 120) refunds 50 percent, and anything less refunds 0 percent. Under `STRICT`, a lead time of at least 168 hours refunds 50 percent and anything less refunds 0 percent. The final `refund_cents` is the refundable base multiplied by that percentage divided by 100, rounded with round-half-up. This same tier-and-lead-time formula governs a cancellation from `REQUESTED` exactly as it governs one from `CONFIRMED` — `REQUESTED` is not special-cased, so a `REQUESTED` cancellation does not automatically return the full amount; its `refund_cents` is whatever the tier and lead time at the cancel instant yield.

A guest may also obtain a provisional cancellation quote — a what-if at the current clock that does not mutate the booking. The quote returns the `refund_cents` the guest would receive if they cancelled right now, the `applied_pct` (the refund percentage that would apply), and the `lead_hours` measured from the current instant; it writes nothing. Because the lead time is measured at the moment of the call, a provisional quote taken earlier and a final settlement at the actual cancel instant may land in different tier bands and therefore differ for identical booking data — the committed `refund_cents` always reflects the lead time at the cancel instant.

Cancellation drives a cascade whose depth depends on the booking's state. In every cancellation, the booking's calendar block is released (its `status` becomes `RELEASED` and the booking's `calendar_block_id` becomes null), the listing's `calendar_version` advances by 1, and each `CONNECTED` or `ERROR` channel's `pending_sync_count` is bumped by 1. When the cancelled booking was `CONFIRMED`, the cascade reaches further, hop by hop: the booking's payout is reversed — its `status` becomes `REVERSED` and its `actual_cents` is set to 0; that payout reversal then closes the security deposit, whose `status` becomes `RELEASED` and `held_cents` drops to 0; and closing the deposit voids any non-terminal damage claim on it, setting that claim's `status` to `VOID` and its `approved_cents` to 0. The whole chain — refund settlement, block release, calendar-version advance, channel bumps, payout reversal, deposit closure, and claim voiding — completes atomically, and the booking's `version` increments as it lands in `CANCELLED`.

### 3.10. The Test-Driving Clock

The system carries a logical clock that governs every time-dependent rule — stay start, payout due-time, and cancellation lead time. A `PlatformAdmin` (or, for test driving, an anonymous caller) sets the clock by supplying `to_iso8601`, the instant the clock should advance to; the response reports the new `current_utc`. Setting the clock has a side effect: every `CONFIRMED` booking whose `check_in` is at or before the new `current_utc` automatically transitions to `IN_STAY`, exactly as if each had been checked in individually.

## 4. Endpoint Definitions

All endpoints return their result inside the standard envelope of §2.2. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation, including all state transitions and computed reads, returns HTTP 200. The request and response payloads for each endpoint are governed by the narratives in §3; the table below lists only the method, path, purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/hosts` | Register a host | Anonymous |
| GET | `/hosts/{id}` | Fetch a host | Host, PlatformAdmin |
| POST | `/guests` | Register a guest | Anonymous |
| GET | `/guests/{id}` | Fetch a guest (includes computed risk score) | Guest, Host, PlatformAdmin |
| POST | `/listings` | Create a listing | Host |
| GET | `/listings/{id}` | Fetch a listing | Host, Guest, PlatformAdmin |
| GET | `/listings` | List listings, optionally filtered by host | Host, Guest, PlatformAdmin |
| POST | `/listings/{id}/publish` | Publish or un-snooze a listing | Host |
| POST | `/listings/{id}/snooze` | Snooze a listing | Host |
| GET | `/listings/{id}/quote` | Pricing preview for a date range | Host, Guest, PlatformAdmin |
| POST | `/rate-plans` | Create a seasonal rate plan | Host |
| GET | `/rate-plans/{id}` | Fetch a rate plan | Host, Guest, PlatformAdmin |
| GET | `/rate-plans` | List rate plans, filterable by listing | Host, Guest, PlatformAdmin |
| POST | `/listings/{id}/calendar-blocks` | Create a manual calendar block | Host |
| GET | `/calendar-blocks/{id}` | Fetch a calendar block | Host, Guest, PlatformAdmin |
| GET | `/listings/{id}/calendar-blocks` | List a listing's calendar blocks | Host, Guest, PlatformAdmin |
| POST | `/listings/{id}/calendar-blocks/{block_id}/release` | Release a manual calendar block | Host |
| POST | `/channel-connections` | Create a channel connection | Host |
| GET | `/channel-connections/{id}` | Fetch a channel connection | Host, PlatformAdmin |
| GET | `/channel-connections` | List channel connections, filterable by listing | Host, PlatformAdmin |
| POST | `/channel-connections/{id}/connect` | Connect or recover a connection | Host |
| POST | `/channel-connections/{id}/sync` | Begin a sync round | PlatformAdmin |
| POST | `/channel-connections/{id}/sync-complete` | Finish a sync round | PlatformAdmin |
| POST | `/channel-connections/{id}/sync-fail` | Fail a sync round | PlatformAdmin |
| POST | `/channel-connections/{id}/imported-reservations` | Import an external reservation | PlatformAdmin |
| GET | `/imported-reservations/{id}` | Fetch an imported reservation | Host, PlatformAdmin |
| GET | `/channel-connections/{id}/imported-reservations` | List a channel's imported reservations | Host, PlatformAdmin |
| GET | `/imported-reservations` | List imported reservations, filterable by channel or block | Host, PlatformAdmin |
| POST | `/bookings` | Create a booking request | Guest |
| GET | `/bookings/{id}` | Fetch a booking | Guest, Host, PlatformAdmin |
| GET | `/bookings` | List bookings, filterable by listing, guest, block, or status | Guest, Host, PlatformAdmin |
| POST | `/bookings/{id}/screen` | Screen the booking request | Host |
| POST | `/bookings/{id}/request-info` | Bounce the request back for more info | Host |
| POST | `/bookings/{id}/approve` | Approve the booking | Host |
| POST | `/bookings/{id}/decline` | Decline the booking | Host |
| POST | `/bookings/{id}/confirm` | Confirm the booking | Guest |
| POST | `/bookings/{id}/check-in` | Mark the stay started | Host |
| POST | `/bookings/{id}/complete` | Complete the stay | Host |
| GET | `/bookings/{id}/cancellation-quote` | Provisional refund what-if | Guest, Host, PlatformAdmin |
| POST | `/bookings/{id}/cancel` | Cancel the booking | Guest |
| GET | `/bookings/{id}/screening-results` | List a booking's screening results | Guest, Host, PlatformAdmin |
| GET | `/screening-results/{id}` | Fetch a screening result | Guest, Host, PlatformAdmin |
| GET | `/screening-results` | List screening results, filterable by booking or guest | Guest, Host, PlatformAdmin |
| GET | `/security-deposits/{id}` | Fetch a security deposit | Guest, Host, PlatformAdmin |
| GET | `/bookings/{id}/security-deposits` | List a booking's security deposit | Guest, Host, PlatformAdmin |
| POST | `/security-deposits/{id}/claims` | File a damage claim | Host |
| GET | `/damage-claims/{id}` | Fetch a damage claim | Guest, Host, PlatformAdmin |
| GET | `/security-deposits/{id}/claims` | List a deposit's damage claims | Guest, Host, PlatformAdmin |
| POST | `/damage-claims/{id}/review` | Move a claim into review | PlatformAdmin |
| POST | `/damage-claims/{id}/approve` | Approve a claim (waterfall debit) | PlatformAdmin |
| POST | `/damage-claims/{id}/deny` | Deny a claim (compensating restore) | PlatformAdmin |
| POST | `/damage-claims/{id}/dispute` | Dispute a claim | Guest |
| GET | `/payouts/{id}` | Fetch a payout | Host, PlatformAdmin |
| GET | `/bookings/{id}/payouts` | List a booking's payout | Host, PlatformAdmin |
| GET | `/payouts` | List payouts, filterable by host | Host, PlatformAdmin |
| POST | `/payouts/{id}/hold` | Hold a scheduled payout | PlatformAdmin |
| POST | `/payouts/{id}/unhold` | Lift a payout hold | PlatformAdmin |
| POST | `/payouts/{id}/release` | Release a due payout | PlatformAdmin |
| POST | `/payouts/{id}/mark-paid` | Mark a released payout as paid | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server clock | PlatformAdmin, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LISTING_NOT_BOOKABLE` | 409 |
| `ERR_SCREENING_NOT_PASSED` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_MIN_NIGHTS` | 422 |
| `ERR_DATES_UNAVAILABLE` | 409 |
| `ERR_RATE_PLAN_OVERLAP` | 409 |
| `ERR_INVALID_CLAIM_AMOUNT` | 422 |
| `ERR_PAYOUT_NOT_DUE` | 409 |
| `ERR_CLAIM_BLOCKS_PAYOUT` | 409 |
| `ERR_STALE_CALENDAR_VERSION` | 412 |
| `ERR_RELEASE_BOOKING_BLOCK` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE_EXTERNAL_REF` | 409 |
