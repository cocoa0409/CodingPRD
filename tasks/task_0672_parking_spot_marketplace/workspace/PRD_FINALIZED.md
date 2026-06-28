# Parking-Spot Marketplace API — Product Requirements Document

## 1. Introduction

The Parking-Spot Marketplace API powers a two-sided rental platform in the spirit of SpotHero and Neighbor, where hosts list private parking spaces and drivers reserve them by the hour, by the day, or for a flat monthly block. The platform's job is to turn a messy real-world problem — matching a finite, time-windowed physical resource against demand that surges around events — into a deterministic set of reservations, charges, payouts, and access credentials. Hosts publish a space with its pricing and availability; the platform takes a configurable commission on every completed stay; drivers prepay from a wallet and present a gate credential on arrival.

Several forces pull against each other in this domain, and the API exists to reconcile them. Pricing is dynamic: a zone can be placed under a surge during a concert or a game, and weekend demand lifts rates further, yet a quoted price must be frozen the moment a driver commits so that later events never retroactively change what was promised. Occupancy must be policed: a driver who overstays owes a penalty, a driver who never shows still owes the host, and repeated misbehavior degrades a driver's standing until the platform suspends them. Money must be conserved end-to-end: every cent a driver pays is either earned by a host (net of commission), refunded to a wallet, or escrowed against a live reservation, and a reservation handed off between drivers must leave the escrowed total untouched.

This document specifies the complete contract for that system — the resources, their parallel lifecycles, the pricing and settlement arithmetic, the validation order, and the access-control model — in enough detail that an implementation can be built and verified against it without reference to any other artifact.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request, except the open registration and clock endpoints noted below, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they are acting. When either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Host`, `Driver`, and `PlatformAdmin`.

`Anonymous` is an unauthenticated caller. The three endpoints that do not require authentication headers are host registration, driver registration, and the logical-clock setter; an `Anonymous` caller may register a new host, register a new driver, and set the test clock. Because `Anonymous` is an opaque identity not tied to any persisted entity, its `X-User-ID` (when present) is never compared against any resource.

When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`. Ownership checks on any resource that references a `Host` compare the resource's foreign-key field to `X-User-ID`: a host may list, unlist, or relist only a `Spot` whose `host_id` equals their own `X-User-ID`, and may read the ledger only for their own host record.

When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`. Ownership checks on any resource that references a `Driver` compare the resource's foreign-key field to `X-User-ID`: a driver may check in, check out, cancel, or offer a `Booking` only when its `driver_id` equals their own `X-User-ID`; a driver may accept or decline a transfer offer only when they are its recipient (`to_driver_id` equals `X-User-ID`), and may withdraw an offer only when they are its offeror (`from_driver_id` equals `X-User-ID`). A request by an authenticated user of the correct role who is nonetheless not the owner or holder of the target resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The platform administrator operates pricing events, marks no-shows, reverses payouts, and reviews violations; the server may record the administrator's identity in the course of those actions but does not compare `X-User-ID` to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range of 1 to 100 inclusive, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. Hosts, Drivers, Spots, Pricing Events, Bookings, Violation Records, and Transfer Offers each include:

- `id` — a unique, server-minted identifier formatted as a UUID. It carries no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control described in §2.7.

Two resources are deliberately lighter. An `AccessPass` and a `PayoutLedgerEntry` are append-only records that are never mutated after creation; each carries only an `id` (UUID) and a `created_at` timestamp, and neither carries an `updated_at` field nor a `version` field. Whenever a derived field on a versioned resource changes — for example, a host's `lifetime_payout_cents`, a driver's `wallet_balance_cents`, `violation_points`, `provisional_violation_points`, or `standing_tier`, or a booking's `final_amount_cents` — that change is itself a mutation that refreshes `updated_at` and increments `version` on the owning resource.

### 2.5. Cascading State Changes and Hierarchical Consistency

Many operations in this system touch more than one resource. When that happens, the server applies every downstream effect immediately and synchronously as part of the same operation; there is no eventual consistency. A check-out, for instance, not only advances the booking but may also debit a driver's wallet, mint a violation, post a host ledger entry, and invalidate an access pass — each a distinct mutation that bumps the `version` and refreshes the `updated_at` of the resource it touches. The individual cascades are spelled out in §3 alongside the workflows that trigger them; the governing principle here is that no cascade is optional or deferred, and every resource the cascade mutates has its `version` incremented and `updated_at` refreshed.

### 2.6. Monetary Values, Points, and Precision

All monetary amounts are stored and computed as integer cents; the API never represents money as a fractional currency unit. Where a calculation produces a fractional cent (for example, after applying a basis-point multiplier), the result is rounded to the nearest whole cent using the round-half-up convention — a value exactly halfway between two cents rounds up. Each calculation in §3 states precisely at which step the rounding is applied, because the order of rounding relative to summation is significant and is pinned per calculation. Basis points are the platform's standard fractional unit: 10000 basis points represents a factor of 1.0, so a multiplier expressed in basis points is applied by multiplying by the basis-point value and dividing by 10000. Violation points are whole integers; where a points calculation yields a fraction, it too is rounded half up to a whole number.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by submitting that parent's last-observed `version`. These are the only two endpoints that take a version field; every other endpoint omits it entirely.

Creating a booking is guarded against a stale `Spot`. The create-booking request must carry `expected_spot_version`, holding the client's last observed `version` of the target `Spot`. If that value does not match the spot's current `version` — for instance because a prior accepted booking on the same spot already advanced the spot's `version`, changing which windows remain free — the create is rejected with `ERR_STALE_SPOT_VERSION` (HTTP 412), forcing the client to re-read the spot before booking against a view it has not observed.

Creating a transfer offer is guarded against a stale `Booking`. The create-transfer-offer request must carry `expected_booking_version`, holding the client's last observed `version` of the target `Booking`. If that value does not match the booking's current `version` — for instance because a prior offer creation or a check-in has already advanced the booking's `version` — the create is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412), forcing the offeror to re-read the booking before offering a reservation that may already have moved on. The same `expected_booking_version` field, checked against the booking's current `version` and rejected on mismatch with `ERR_STALE_SPOT_VERSION` semantics for stale parents, also guards the admin payout-reversal operation described in §3.6; that reversal request carries `expected_booking_version` and is rejected on a version mismatch.

### 2.8. Nested Resource Retrieval and Reference Validation

Several read endpoints address a child collection through a parent's identifier — a spot's bookings, a booking's transfer offers, a booking's violations, a booking's access pass, a booking's ledger entries, a host's ledger, and a driver's violations. For any such path, and for any write whose body references other resources, the server validates referenced resources left to right and rejects the first identifier that does not resolve to an existing resource with `ERR_NOT_FOUND` (HTTP 404). This applies to every id-bearing endpoint across Spots, Bookings, Drivers, Hosts, Pricing Events, Violation Records, and Transfer Offers.

### 2.9. The Logical Clock

All time-gated behavior in the system is driven by a server-side logical clock rather than wall-clock time, so that time-dependent transitions can be exercised deterministically. On startup the clock reads exactly `2026-04-01T00:00:00Z`; until it is explicitly set it remains at that default and never falls back to the host's wall clock. The clock-set capability accepts an ISO 8601 UTC instant in a `to_iso8601` field and advances the logical clock to it. Advancing the clock may make reserved bookings whose window has fully elapsed eligible to be marked as no-shows, as described in §3.4.

### 2.10. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. The order, from first-evaluated to last, is: authentication (`ERR_UNAUTHENTICATED`); role permission (`ERR_FORBIDDEN_ROLE`); existence of all referenced resources, left to right (`ERR_NOT_FOUND`); ownership or holdership of the target resource (`ERR_NOT_RESOURCE_OWNER`); then state-machine validity for the requested transition (`ERR_INVALID_STATE`); then optimistic-concurrency version match (`ERR_STALE_SPOT_VERSION` / `ERR_STALE_BOOKING_VERSION`); then the reverse-payout eligibility check (`ERR_NO_REVERSIBLE_PAYOUT`); then the temporal-window checks (`ERR_INVALID_WINDOW`, then `ERR_CHECKIN_WINDOW_CLOSED`); then the business-constraint checks in the order spot time-conflict (`ERR_SPOT_TIME_CONFLICT`), pricing-event zone-conflict (`ERR_EVENT_ZONE_CONFLICT`), gate-pass validity (`ERR_GATE_PASS_INVALID`), spot-listed (`ERR_SPOT_UNLISTED`), driver-not-suspended (`ERR_DRIVER_SUSPENDED`), and transfer-not-to-self (`ERR_TRANSFER_TO_SELF`); then the wallet-funding check (`ERR_INSUFFICIENT_WALLET`); and finally the generic body-shape check (`ERR_INVALID_REQUEST`) and the pagination check (`ERR_INVALID_PAGINATION`). Where a single request is subject to several of these, an earlier check shadows a later one: a request that both references a missing resource and supplies a stale version surfaces the missing-resource error, because existence is evaluated before the version match.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Hosts, Drivers, and Wallet Funding

A host joins the platform by registering with an `email`, which is their login identifier and must be unique across all hosts and non-empty, a public `display_name`, and an opaque `payout_account_ref` token that identifies where their earnings are paid out. A host may also supply `platform_fee_bps`, the platform's commission on this host's gross earnings expressed in basis points; it must be between 0 and 5000 inclusive (that is, between 0% and 50%), and when omitted it defaults to 1500 (15%). A newly created host begins with `lifetime_payout_cents` of 0; that field is a conserved running total maintained by the ledger and is described in §3.7.

A driver joins by registering with a unique, non-empty `email` and a public `display_name`. A new driver starts with a `wallet_balance_cents` of 0, with `violation_points` and `provisional_violation_points` both at 0, and with a `standing_tier` of `GOOD`. The wallet is a prepaid balance in cents that funds bookings; it is never allowed to go negative. Because a new driver has an empty wallet, a funding capability lets a driver (or the platform administrator acting on their behalf) credit a wallet by a specified `amount_cents`, which is added to that driver's `wallet_balance_cents`. The wallet is debited when a booking is confirmed and when an overstay penalty is captured, and credited when a refund is issued or a transfer makes the original holder whole.

### 3.2. Listing a Spot and Managing Its Availability

A `Host` lists a parking space by creating a `Spot`. The creation payload carries the owning `host_id`, a `title`, a `zone_code` (the geographic zone, such as "DT-01", used to match surge pricing events), and the spot's pricing: `base_hourly_cents` (at least 100), `base_daily_cents` (at least 500), and `monthly_flat_cents` (at least 5000). The payload also defines the bookable window with `availability_start`, the inclusive start, and `availability_end`, the exclusive end, both ISO 8601 UTC instants. An optional `overstay_grace_minutes`, the number of minutes after a booking's end time before overstay penalties begin to accrue, may be supplied; it must be between 0 and 120 inclusive and defaults to 15. The `host_id` is fixed at creation and never changes. Every new spot begins LISTED; its `listing_status` is one of `LISTED` or `UNLISTED`.

A spot's listing status cycles. The owning host may unlist a LISTED spot, transitioning `listing_status` from `LISTED` to `UNLISTED`, but only when no booking on that spot is currently in `RESERVED` or `CHECKED_IN` occupancy — an attempt while an active reservation exists, or by a host who does not own the spot, is rejected (ownership failures surface as `ERR_NOT_RESOURCE_OWNER`; an invalid current state surfaces as `ERR_INVALID_STATE`). The host may relist an `UNLISTED` spot, transitioning `listing_status` back from `UNLISTED` to `LISTED`. Each of these transitions increments the spot's `version`. An unlisted spot rejects new bookings, as described in §3.3.

### 3.3. Pricing Events and the Booking Quote

The platform administrator shapes demand-based pricing by creating a `PricingEvent` for a zone and window. The payload carries a `zone_code` matched against a spot's `zone_code`, a `window_start` (inclusive) and `window_end` (exclusive) bounding the surge in UTC, and a `surge_multiplier_bps` between 10000 and 50000 inclusive (10000 being a neutral 1.0x and 25000 being 2.5x). A new event begins with a `status` of `ACTIVE`; the only other status is `CANCELLED`, and only `ACTIVE` events influence pricing.

Pricing events in a single zone may not crowd one another. A new event is rejected with `ERR_EVENT_ZONE_CONFLICT` (HTTP 409) unless there is a gap of at least 3600 seconds (one hour) on both sides between it and every other `ACTIVE` event in the same `zone_code`. Events are treated as closed intervals padded by this one-hour buffer: concretely, the new event conflicts with an existing active event when the new event's `window_start` is earlier than the other event's `window_end` plus 3600 seconds, and the new event's `window_end` plus 3600 seconds is later than the other event's `window_start`. Windows that merely touch, or that sit less than an hour apart on either side, are therefore rejected.

The administrator may cancel an `ACTIVE` pricing event, transitioning its `status` from `ACTIVE` to `CANCELLED` and incrementing its `version`; the transition is permitted only when the event is currently `ACTIVE`, and is otherwise rejected with `ERR_INVALID_STATE`. Cancellation is forward-looking only: it does not re-quote any existing booking, because a booking's quote is frozen at creation. Only future quotes stop seeing the cancelled surge.

A `Driver` reserves a spot by creating a `Booking`. The payload carries the `spot_id`, the `driver_id`, a `rate_kind` of `HOURLY`, `DAILY`, or `MONTHLY`, the inclusive `start_at` and exclusive `end_at` of the reservation, and `expected_spot_version` (see §2.7). At creation the server computes and freezes `quoted_amount_cents` and then debits the driver's wallet, as covered in §3.5; `final_amount_cents` is left null until checkout, `occupancy_status` starts at `RESERVED`, `actual_checkin_at` and `actual_checkout_at` are null, and `transfer_count` starts at 0.

The quote is computed as follows. First the reserved duration in seconds is the difference between `end_at` and `start_at` (with `end_at` exclusive). The base amount depends on `rate_kind`. For an `HOURLY` booking, the duration in seconds is divided by 3600 and rounded up to the next whole hour, and that number of hours is multiplied by the spot's `base_hourly_cents`. For a `DAILY` booking, the duration in seconds is divided by 86400 and rounded up to the next whole 24-hour day, and that number of days is multiplied by the spot's `base_daily_cents`. For a `MONTHLY` booking, the base is simply the spot's `monthly_flat_cents` for a single fixed 30-day block. Next, surge is applied: among the `ACTIVE` pricing events for the spot's `zone_code` whose half-open window from `window_start` (inclusive) to `window_end` (exclusive) contains `start_at`, the server selects the single matching event with the highest `surge_multiplier_bps`, breaking ties by earliest `created_at`; the surge factor in basis points is that event's `surge_multiplier_bps`, or 10000 if no event matches. A weekend uplift then applies only to `HOURLY` and `DAILY` bookings whose `start_at` falls on a Saturday or Sunday in UTC: the weekend factor is 11000 basis points in that case and 10000 otherwise; `MONTHLY` bookings never receive the weekend uplift. The raw amount is the base multiplied by the surge factor divided by 10000 and then multiplied by the weekend factor divided by 10000. This single raw amount is rounded half up to a whole cent (the rounding happens once, after both multipliers are applied — multiply-then-round, never round-then-multiply). Finally, the quoted amount is the greater of that rounded raw amount and the spot's `base_hourly_cents`, so the quote is never below one base hour.

A booking creation is subject to several gating checks beyond the version match. The booking window must be valid: `end_at` must be strictly after `start_at`, the entire window must lie within the spot's availability from `availability_start` (inclusive) to `availability_end` (exclusive), and for a `MONTHLY` booking the window must span exactly 30 days; a violation surfaces as `ERR_INVALID_WINDOW` (HTTP 422). The requested half-open window from `start_at` to `end_at` must not intersect any existing booking on the same spot whose `occupancy_status` is `RESERVED`, `CHECKED_IN`, or `CHECKED_OUT`; two bookings that merely touch at a boundary, where one's `end_at` equals the other's `start_at`, do not conflict because intervals are half-open, but any genuine overlap is rejected with `ERR_SPOT_TIME_CONFLICT` (HTTP 409). The spot's `listing_status` must be `LISTED`; booking an `UNLISTED` spot is rejected with `ERR_SPOT_UNLISTED` (HTTP 409). And the driver's `standing_tier` must not be `SUSPENDED`; a suspended driver attempting to book is rejected with `ERR_DRIVER_SUSPENDED` (HTTP 409).

### 3.4. Occupancy: Check-In, the Access Pass, and the Gate

The occupancy of a booking and its settlement are two independent dimensions that advance on different triggers. The occupancy dimension (`occupancy_status`) moves through `RESERVED`, `CHECKED_IN`, and `CHECKED_OUT`, with branches to `CANCELLED` and `NO_SHOW`; the settlement dimension (`settlement_status`) is one of `UNSETTLED`, `SETTLED`, or `REFUNDED` and evolves independently. A booking begins `RESERVED` and `UNSETTLED`, but on a successful confirmation charge its `settlement_status` is set to `SETTLED` (see §3.5).

A driver who holds the booking checks in, advancing `occupancy_status` from `RESERVED` to `CHECKED_IN`. Check-in is permitted only when the acting driver holds the booking (its `driver_id` equals the caller), the booking is currently `RESERVED`, the booking's `settlement_status` is `SETTLED` (payment was captured at confirmation), and the logical clock sits within the check-in window: at or after `start_at`, and strictly before `end_at` plus the spot's `overstay_grace_minutes`. A check-in attempted before `start_at`, or once the window plus grace has fully elapsed, is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409); a check-in on a booking not in the `RESERVED` state is rejected with `ERR_INVALID_STATE`. On a successful check-in the server sets `actual_checkin_at` to the logical clock, mints an `AccessPass` for the booking, and increments the booking's `version`.

The minted `AccessPass` references its `booking_id`, carries an opaque single-spot `qr_token`, and starts with `gate_opens_remaining` of 2 — the number of times its gate may be opened. A driver opens the gate by redeeming the QR credential, supplying the `qr_token`; each successful redemption decrements that pass's `gate_opens_remaining` by one. Redemption requires a valid access pass with `gate_opens_remaining` greater than 0 that matches the booking; a redemption against a missing pass, a non-matching pass, or a pass whose `gate_opens_remaining` has reached 0 is rejected with `ERR_GATE_PASS_INVALID` (HTTP 409). At checkout the pass is invalidated by setting its `gate_opens_remaining` to 0.

A reserved booking that is never checked in can be marked a no-show. This is driven by the platform administrator, or by the server during a clock advance, once the logical clock reaches or passes `end_at` plus the spot's `overstay_grace_minutes` while the booking is still `RESERVED`. Marking a no-show advances `occupancy_status` from `RESERVED` to `NO_SHOW`, sets `settlement_status` to `SETTLED` (a no-show earns no refund), posts a host earning on the quoted amount as described in §3.7, and increments the booking's `version`. As a cascade, the no-show auto-logs a `ViolationRecord` against the booking with `violation_kind` of `NO_SHOW`, `status` of `OPEN`, and `base_points` of 3, copying the booking's driver into the record; that record's creation re-derives the driver's `provisional_violation_points`, which on this path increases by 9 (the `NO_SHOW` weight of 3 multiplied by the proposed `base_points` of 3, with no escalation while open).

### 3.5. Confirmation Charge, Checkout, and Overstay Settlement

When a booking is created, the freshly computed `quoted_amount_cents` is charged against the driver's wallet: the driver's `wallet_balance_cents` is debited by that amount, the booking's `settlement_status` is set to `SETTLED`, and the spot's `version` is incremented (its availability footprint has changed). The wallet must be able to cover the charge; if the driver's `wallet_balance_cents` is below `quoted_amount_cents`, the booking is rejected before any mutation with `ERR_INSUFFICIENT_WALLET` (HTTP 402).

A driver who holds a `CHECKED_IN` booking checks out, which is the moment the final price is computed. Checkout requires the acting driver to hold the booking and the booking to be currently `CHECKED_IN`; otherwise the state check fails with `ERR_INVALID_STATE`. On checkout the server records `actual_checkout_at` as the logical clock and computes `final_amount_cents`. The final amount is the frozen `quoted_amount_cents` (the base portion is the quote, never re-priced) plus an overstay charge. The overstay portion is determined from the overstay duration in seconds, computed as the actual checkout instant minus the sum of `end_at` and the spot's grace period (the grace expressed in seconds is `overstay_grace_minutes` multiplied by 60); if that overstay duration is zero or negative there is no overstay charge. Otherwise the overstay seconds are divided by 3600 and rounded up to a whole number of overstay hours, and the overstay charge is those hours multiplied by the spot's `base_hourly_cents` multiplied by 15000 basis points divided by 10000 — that is, the overstay is billed at 1.5 times the spot's base hourly rate, never at any surged rate. The overstay charge term alone is rounded half up to a whole cent, and the final amount is that rounded overstay charge added to the integer base portion.

If the resulting `final_amount_cents` exceeds the frozen `quoted_amount_cents`, the difference is an overstay top-up: the driver's `wallet_balance_cents` is debited by the delta, floored at 0 so the wallet never goes negative — any shortfall is recorded as owed but does not block checkout. The checkout then advances `occupancy_status` from `CHECKED_IN` to `CHECKED_OUT` while `settlement_status` stays `SETTLED` (only the occupancy dimension moves), posts a host earning as described in §3.7, invalidates the access pass by setting its `gate_opens_remaining` to 0, and increments the booking's `version`. One further cascade applies when the actual checkout instant is later than `end_at` plus grace: the checkout auto-logs a `ViolationRecord` against the booking with `violation_kind` of `OVERSTAY`, `status` of `OPEN`, and `base_points` of 1, copying the booking's driver into the record. That record's creation re-derives the driver's `provisional_violation_points`, which on this path increases by 1 (the `OVERSTAY` weight of 1 multiplied by the proposed `base_points` of 1, with no escalation while open); the driver's `standing_tier` is unaffected, because only confirmed points move the tier.

### 3.6. Cancellation, Refunds, and Payout Reversal

A driver who holds a `RESERVED` booking may cancel it. Cancellation requires the acting driver to hold the booking and the booking to be currently `RESERVED`; otherwise it is rejected with `ERR_INVALID_STATE`. A cancel advances `occupancy_status` from `RESERVED` to `CANCELLED`, computes a tiered refund of the frozen quote and credits it to the driver's `wallet_balance_cents`, sets `settlement_status` to `REFUNDED`, and increments the booking's `version`. Because a still-`RESERVED` booking has no posted host earning yet, no host ledger reversal occurs on this path. As a cascade, cancelling a `RESERVED` booking that has a `PENDING` transfer offer auto-withdraws that offer by setting its `status` to `WITHDRAWN`, which makes the offer terminal so that no later accept or decline is possible on it.

The refund is tiered by how far ahead of `start_at` the cancel lands, measured against the logical clock at the cancel instant. Let the lead time in seconds be `start_at` minus the logical clock. When the lead time is at least 604800 seconds (7 days), the refund factor is the full 10000 basis points. When the lead time is at least 86400 seconds (1 day) but less than 7 days, the refund factor is 7500 basis points (75%). When the lead time is at least 0 but less than 1 day — that is, still before `start_at` — the refund factor is 5000 basis points (50%). When the lead time is below 0, meaning the clock has reached or passed `start_at`, the refund factor is 0 and no refund is issued. The refund is the frozen `quoted_amount_cents` multiplied by the applicable refund factor divided by 10000, rounded half up to a whole cent. This same tiered refund is used wherever a reservation is unwound by a cancel — including the suspension auto-cancel described in §3.8 — but is deliberately not used on a transfer, which makes the original holder whole at the full quote (§3.9).

The platform administrator can reverse a host's earning on a finalized booking as a dispute-resolution measure. Reverse-payout is not a state-machine transition and performs no separate state check on the booking's `occupancy_status`: eligibility is determined solely from the ledger. Because a posted earning only ever arises when a booking is finalized (at check-out or no-show, §3.7), the eligible target is in practice a booking that has been finalized — its `occupancy_status` is `CHECKED_OUT` or `NO_SHOW` — and that has exactly one posted earning ledger entry with no matching reversal yet; a reversal attempted on a booking with no posted earning — including a booking that is not yet finalized, such as one still in `RESERVED` (which carries no posted earning) — or whose earning was already reversed, is rejected with `ERR_NO_REVERSIBLE_PAYOUT` (HTTP 409), never with `ERR_INVALID_STATE`. The reversal request carries `expected_booking_version` and is subject to the optimistic-concurrency check of §2.7, which (per §2.10) is evaluated before this reverse-payout eligibility check; a version mismatch therefore shadows the eligibility error. A successful reversal posts a `PayoutLedgerEntry` of type `REVERSAL` whose `amount_cents` is the exact negation of the original earning entry's `amount_cents` (no re-derivation), recomputes the host's `lifetime_payout_cents` so that it nets back to its value before this booking's earning, and increments the booking's `version`.

### 3.7. Host Payouts and the Ledger

Whenever a booking is finalized in the host's favor — at checkout, or when a reservation is marked a no-show — the server posts a `PayoutLedgerEntry` of type `EARNING` for the spot's owning host. The entry references the host via `host_id` and the originating booking via `booking_id`, and its `entry_type` is `EARNING` (a positive amount) or `REVERSAL` (a negative amount). The signed `amount_cents` posted to the ledger is computed per booking as follows. The gross is `final_amount_cents` when the booking checked out, or the frozen `quoted_amount_cents` when the booking was a no-show (a no-show bills the quote). The platform fee in cents is the gross multiplied by the host's `platform_fee_bps` divided by 10000, rounded half up to a whole cent at this per-booking step. The net earning is the gross minus that rounded fee, and the `EARNING` entry's `amount_cents` is the positive net earning. A `REVERSAL` entry's `amount_cents` is the exact negation of the original `EARNING` entry's amount for the same booking.

The host's `lifetime_payout_cents` is a conserved total: it is the sum of `amount_cents` over all of that host's ledger entries whose `entry_type` is `EARNING` or `REVERSAL` (reversal rows being negative), and it is recomputed on every ledger mutation. Because the per-booking fee is rounded before being summed into the ledger — rounding each booking's fee individually rather than summing gross amounts and rounding an aggregate fee — the per-line rounding order is pinned and must not be replaced by a sum-then-round approach.

### 3.8. Violations, Scoring, and Driver Standing

A violation against a booking can be logged either automatically (the overstay and no-show cascades above) or manually by a host or the platform administrator. A manually logged `ViolationRecord` carries the `booking_id` it is logged against, a `violation_kind` of `OVERSTAY`, `UNAUTHORIZED_GATE`, or `NO_SHOW`, and `base_points` (the points proposed by the reporter, between 1 and 10 inclusive). On creation the record's `driver_id` is copied from the booking's current driver, its `status` is `OPEN`, its `assessed_points` is null while open, and the affected driver's `provisional_violation_points` is re-derived.

A driver carries two running point totals that diverge until each record is reviewed. The `provisional_violation_points` total includes every `OPEN`, unreviewed record and is computed with no escalation: each open record contributes its `base_points` multiplied by the weight of its `violation_kind`, where the weights are `OVERSTAY` = 1, `UNAUTHORIZED_GATE` = 2, and `NO_SHOW` = 3, with the escalation factor fixed at 10000 basis points (no escalation, because confirmation order is unknown until review). The `violation_points` total counts only `CONFIRMED` records and drives the driver's standing.

The platform administrator reviews each open record. Confirming a record requires it to be `OPEN`; it advances the record's `status` from `OPEN` to `CONFIRMED`, computes its `assessed_points`, and increments the record's `version`. The assessed points are the record's `base_points` multiplied by the weight of its `violation_kind` (the same `OVERSTAY` = 1, `UNAUTHORIZED_GATE` = 2, `NO_SHOW` = 3 weights) multiplied by a repeat-offender escalation factor, then rounded half up to a whole number of points. The escalation factor in basis points is 10000 plus 2500 for each of the driver's already-confirmed records that were created before this one (counting records with `status` `CONFIRMED` and an earlier `created_at`, ordered by `created_at` ascending), capped at 3 such priors — so the escalation runs from 10000 basis points (no priors) up to a maximum of 17500 basis points (three or more priors, a +75% uplift). Dismissing a record instead requires it to be `OPEN`, advances its `status` from `OPEN` to `DISMISSED`, sets its `assessed_points` to 0, leaves the driver's `violation_points` unchanged, and increments the record's `version`. Whether a record is confirmed or dismissed, the driver's `provisional_violation_points` is re-derived because the set of open records has shrunk.

Confirmation cascades into the driver's standing and possibly their reservations. Confirming a record adds its `assessed_points` to the driver's `violation_points`, which recomputes the driver's `standing_tier`: the tier is `SUSPENDED` when `violation_points` is at least 10, `WATCH` when `violation_points` is at least 5 but below 10 (5 is inclusive and maps to `WATCH`, while 4 remains `GOOD`), and `GOOD` otherwise. Provisional points never move the tier — only confirmed points do. When the recomputed tier becomes `SUSPENDED`, a further cascade auto-cancels every booking held by that driver whose `occupancy_status` is still `RESERVED`: each such booking has its `occupancy_status` set to `CANCELLED` and its `settlement_status` set to `REFUNDED`, and the tiered refund of §3.6 is credited to that driver's `wallet_balance_cents`. Because those auto-cancelled bookings were still `RESERVED`, they carry no posted host earning, so no reversal is posted on this path.

### 3.9. Transfer of a Reservation

A driver who holds a `RESERVED` booking can offer it to another driver by creating a `TransferOffer`. The payload carries the `booking_id` being offered, the recipient `to_driver_id`, and `expected_booking_version` for the optimistic-concurrency check of §2.7. On creation the server copies the offering driver into the offer's `from_driver_id`, sets its `status` to `PENDING`, and increments the underlying booking's `version`. The recipient must differ from the current holder; an offer whose recipient equals the current holder is rejected with `ERR_TRANSFER_TO_SELF` (HTTP 422). A transfer offer's `status` is one of `PENDING`, `ACCEPTED`, `DECLINED`, or `WITHDRAWN`.

The recipient may accept a pending offer, advancing its `status` from `PENDING` to `ACCEPTED`. Acceptance is permitted only when the acting driver is the recipient (the offer's `to_driver_id` equals the caller), the offer is `PENDING`, the underlying booking is still `RESERVED`, the logical clock is strictly before `start_at` (a reservation may only be transferred before its window opens), and the recipient's `standing_tier` is not `SUSPENDED` (a suspended recipient is rejected with `ERR_DRIVER_SUSPENDED`); an offer or booking not in the required state is rejected with `ERR_INVALID_STATE`. Acceptance reassigns the reservation by setting the booking's `driver_id` to `to_driver_id`, increments the booking's `transfer_count` by one, and increments both the offer's `version` and the booking's `version`.

Acceptance also settles the two drivers' wallets so that the escrow held for the booking is conserved at exactly the frozen `quoted_amount_cents`. The recipient must be able to pay that frozen quote: if the recipient's `wallet_balance_cents` is below the booking's `quoted_amount_cents`, the accept is rejected before any mutation with `ERR_INSUFFICIENT_WALLET`. Otherwise the recipient's `wallet_balance_cents` is debited by the full `quoted_amount_cents` (the recipient assumes the reservation at its original frozen quote), and the offering driver's `wallet_balance_cents` is credited the full `quoted_amount_cents` (the original holder is made whole). The net change across the two drivers' wallets is exactly zero, and the booking's `quoted_amount_cents` remains the conserved escrow; the tiered refund of §3.6 is deliberately not applied here, because a transfer is a full make-whole rather than a cancellation.

The recipient may instead decline a pending offer, advancing its `status` from `PENDING` to `DECLINED` and incrementing its `version`; declining requires the acting driver to be the recipient and the offer to be `PENDING`. The original offeror may withdraw a pending offer they made, advancing its `status` from `PENDING` to `WITHDRAWN` and incrementing its `version`; withdrawing requires the acting driver to be the offeror (the offer's `from_driver_id` equals the caller) and the offer to be `PENDING`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or perform a read return a `200 OK` status code. The clock-set capability advances the logical clock to a supplied `to_iso8601` instant and returns `200 OK` with no resource body. Request bodies, response bodies, and side effects for each endpoint are specified in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hosts` | Register a host | Anonymous |
| GET | `/hosts/{id}` | Fetch a host | Host, PlatformAdmin |
| GET | `/hosts/{id}/ledger` | List a host's payout ledger entries | Host, PlatformAdmin |
| POST | `/drivers` | Register a driver | Anonymous |
| GET | `/drivers/{id}` | Fetch a driver (wallet, points, standing) | Driver, PlatformAdmin |
| POST | `/drivers/{id}/wallet/topup` | Credit a driver's wallet | Driver, PlatformAdmin |
| GET | `/drivers/{id}/violations` | List violation records for a driver | Driver, PlatformAdmin |
| POST | `/spots` | Create (list) a parking spot | Host |
| GET | `/spots/{id}` | Fetch a spot | Host, Driver, PlatformAdmin |
| GET | `/spots` | List spots; filter by `host_id` and/or `zone_code` | Host, Driver, PlatformAdmin |
| GET | `/spots/{id}/bookings` | List bookings on a spot | Host, PlatformAdmin |
| POST | `/spots/{id}/unlist` | Unlist a spot | Host |
| POST | `/spots/{id}/relist` | Relist an unlisted spot | Host |
| POST | `/pricing-events` | Create a surge pricing event | PlatformAdmin |
| GET | `/pricing-events/{id}` | Fetch a pricing event | PlatformAdmin, Host, Driver |
| GET | `/pricing-events` | List pricing events; filter by `zone_code` | PlatformAdmin, Host, Driver |
| POST | `/pricing-events/{id}/cancel` | Cancel a pricing event | PlatformAdmin |
| POST | `/bookings` | Create a booking on a spot | Driver |
| GET | `/bookings/{id}` | Fetch a booking | Driver, Host, PlatformAdmin |
| GET | `/bookings` | List bookings; filter by `driver_id` and/or `spot_id` | Driver, Host, PlatformAdmin |
| GET | `/bookings/{id}/transfer-offers` | List transfer offers on a booking | Driver, PlatformAdmin |
| GET | `/bookings/{id}/violations` | List violation records on a booking | Driver, Host, PlatformAdmin |
| GET | `/bookings/{id}/access-pass` | Fetch the access pass for a booking | Driver, PlatformAdmin |
| GET | `/bookings/{id}/ledger-entries` | List payout ledger entries for a booking | Host, PlatformAdmin |
| POST | `/bookings/{id}/check-in` | Driver checks in; mints an access pass | Driver |
| POST | `/bookings/{id}/check-out` | Driver checks out; finalizes settlement | Driver |
| POST | `/bookings/{id}/cancel` | Driver cancels a reserved booking | Driver |
| POST | `/bookings/{id}/mark-no-show` | Mark an expired un-checked-in booking as no-show | PlatformAdmin |
| POST | `/bookings/{id}/reverse-payout` | Reverse a posted host earning for a finalized booking | PlatformAdmin |
| POST | `/access-passes/redeem` | Open the gate by redeeming a QR token | Driver |
| POST | `/transfer-offers` | Offer a reserved booking to another driver | Driver |
| GET | `/transfer-offers/{id}` | Fetch a transfer offer | Driver, PlatformAdmin |
| GET | `/transfer-offers` | List transfer offers; filter by `to_driver_id`, `from_driver_id`, `booking_id` | Driver, PlatformAdmin |
| POST | `/transfer-offers/{id}/accept` | Recipient accepts; reassigns the booking | Driver |
| POST | `/transfer-offers/{id}/decline` | Recipient declines a pending offer | Driver |
| POST | `/transfer-offers/{id}/withdraw` | Offeror withdraws a pending offer | Driver |
| POST | `/violations` | Log a violation record against a booking | Host, PlatformAdmin |
| GET | `/violations/{id}` | Fetch a violation record | Host, Driver, PlatformAdmin |
| GET | `/violations` | List violation records; filter by `driver_id`, `booking_id`, `status` | Host, Driver, PlatformAdmin |
| POST | `/violations/{id}/confirm` | Confirm a violation; assess points; cascade | PlatformAdmin |
| POST | `/violations/{id}/dismiss` | Dismiss a violation; no confirmed points | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_SPOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BOOKING_VERSION` | 412 Precondition Failed |
| `ERR_NO_REVERSIBLE_PAYOUT` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SPOT_TIME_CONFLICT` | 409 Conflict |
| `ERR_EVENT_ZONE_CONFLICT` | 409 Conflict |
| `ERR_GATE_PASS_INVALID` | 409 Conflict |
| `ERR_SPOT_UNLISTED` | 409 Conflict |
| `ERR_DRIVER_SUSPENDED` | 409 Conflict |
| `ERR_TRANSFER_TO_SELF` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_WALLET` | 402 Payment Required |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
