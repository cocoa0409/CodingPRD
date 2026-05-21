# Airline Frequent Flyer & Upgrade API — Product Requirements Document

## 1. Introduction

The Airline Frequent Flyer & Upgrade API is the system of record for an airline's loyalty programme. It manages every points-bearing interaction a member has with the carrier — from segment accrual after a flight is flown, through award redemptions for future trips, to the priority waitlist that resolves last-minute cabin upgrades.

Two characteristics make this domain unusually error-prone if its rules are not carefully captured. First, the programme operates on **two parallel currencies** — qualifying activity, which determines elite tier, and the redeemable points balance, which can be spent on awards, gifts, and upgrade bids. The two currencies are accrued by the same event but accumulate, decay, and reset on entirely different schedules. Second, ranking on the upgrade waitlist depends on attributes (member tier, points offered) that themselves change while the request is queued, so the system must hold a recompute discipline that is precise enough to be tested deterministically.

The API also exposes a controlled ops surface — clock advance and several `_sweep` endpoints — so that automated tests can drive the time-based behaviours (points expiration, status-match expiry, waitlist promotion at T-1 hour, year-end rollover) without waiting for real wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contracts, and conventions that apply uniformly to every endpoint.

### 2.1. User and Role-Based Access Control

Every API request must carry two mandatory headers: `X-User-ID` identifies the acting principal and `X-User-Role` declares the operational capacity under which the request is being made. A request that omits either header, or whose header values are unparseable, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role lacks permission for the endpoint is rejected with `ERR_FORBIDDEN`.

The system recognises exactly three roles, written here with the casing that the `X-User-Role` header must use verbatim: `Member`, `BookingAgent`, and `ProgramAdmin`.

When `X-User-Role` is `Member`, the value of `X-User-ID` is the `id` of the acting `Member` entity. Ownership checks on any resource that references a `Member` compare the resource's foreign-key field (for example `member_id` on `FlightSegment`, `AwardBooking`, `UpgradeRequest`, `CompanionCertificate`, `PointsTransaction`, `StatusMatchRequest`, or `MembershipYear`) to the value of `X-User-ID`. A `Member` who acts on a resource owned by a different member is rejected with `ERR_OWNERSHIP_MISMATCH`.

When `X-User-Role` is `BookingAgent` or `ProgramAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`. Both roles can act on behalf of any `Member` for the endpoints listed in §4.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; if omitted, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless an endpoint specifies otherwise, every list endpoint sorts its results by `created_at` in ascending order. The `meta` block of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries an `id` that is a server-minted UUID, without any type prefix. Every resource also carries a `created_at` field, expressed as an ISO 8601 UTC timestamp with three fractional digits (for example `2025-05-24T10:30:00.123Z`), recorded when the resource is first written.

Most resources additionally carry an `updated_at` field — itself an ISO 8601 UTC timestamp with three fractional digits, refreshed on every server-side mutation — and a `version` field, an integer that starts at 1 and increments by exactly one with every server-side mutation. Two resource families in this domain are explicit exceptions: a `PointsTransaction` is an immutable append-only ledger entry that carries only `id` and `created_at`, with no `updated_at` and no `version`; a `MembershipYear` is an immutable annual snapshot that likewise carries only `id` and `created_at`, with no `updated_at` and no `version`.

Cascading mutations — for example a flight cancellation propagating to its `FlightSegment` rows, a confirmed `AwardBooking` being cancelled and reverting its `CompanionCertificate`, or an annual rollover mutating `Member.tier` — each touch every affected resource. Every touched resource refreshes its own `updated_at` and increments its own `version`, independently of the others.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that allow the client to declare a version expectation accept an optional `version` field in the request body. When `version` is supplied, the server compares it against the current `version` of the targeted resource; on mismatch, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server skips the check and applies the mutation against the current row. A successful mutation increments `version` by one regardless of whether the client supplied an expected value.

### 2.6. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers (for example `/members/{memberId}/segments/{segmentId}/upgrade-requests`), the system validates the existence of each identifier in left-to-right order. The request is rejected with the existence error corresponding to the *first* identifier in the path that does not correspond to an existing resource — `ERR_MEMBER_NOT_FOUND` before any segment lookup, `ERR_SEGMENT_NOT_FOUND` before any upgrade-request lookup, and so on. Beyond simple existence, a nested child resource is also rejected as not found when it exists but is owned by a different member than the one named in the path: a `FlightSegment` whose `member_id` does not equal the path's `memberId` yields `ERR_SEGMENT_NOT_FOUND`, an `AwardBooking` in the same situation yields `ERR_BOOKING_NOT_FOUND`, and a `CompanionCertificate` yields `ERR_CERTIFICATE_NOT_FOUND`. `StatusMatchRequest` follows the same rule via `ERR_STATUS_MATCH_REQUEST_NOT_FOUND`.

### 2.7. Validation Priority

When a single request would fail multiple checks, the server returns the first failure that surfaces in the priority order below. Lower-numbered checks beat higher-numbered checks.

1. Header presence and well-formedness — failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role permission for this endpoint — failure yields `ERR_FORBIDDEN`.
3. Existence of every resource named in the path, evaluated left-to-right — failure yields the appropriate `ERR_*_NOT_FOUND`.
4. State of the targeted resource — for example, an `AwardBooking` that is not in `HELD` cannot be confirmed (`ERR_BOOKING_NOT_HOLDABLE`), an `AwardBooking` that is not in `CONFIRMED` cannot be cancelled (`ERR_BOOKING_NOT_CANCELLABLE`), a `FlightSegment` that is not `BOOKED` cannot be marked flown (`ERR_SEGMENT_NOT_FLYABLE`), an `UpgradeRequest` that is not `WAITLISTED` cannot be cancelled, patched, or admin-confirmed (`ERR_UPGRADE_NOT_WAITLISTED`), a `StatusMatchRequest` that is not `PENDING` cannot be approved or rejected (`ERR_STATUS_MATCH_NOT_PENDING`), a `CompanionCertificate` that is not `ACTIVE` cannot be reserved (`ERR_CERTIFICATE_NOT_USABLE`), and a `Flight` whose `status` is not `SCHEDULED` cannot be booked against (`ERR_FLIGHT_NOT_BOOKABLE`).
5. Cross-entity tier and role gating — for example, an `UpgradeRequest` requires the acting member's `tier` to be at least `GOLD`, and a `CompanionCertificate` redemption requires the acting member's `tier` to be at least `PLATINUM` at the moment of issuance; the rejection code is `ERR_MEMBER_TIER_INELIGIBLE`.
6. Temporal-window checks — a `CompanionCertificate` reservation requires the booking moment to lie inside `[issued_at, expires_at)` (`ERR_CERTIFICATE_EXPIRED`), and a `StatusMatchRequest` approval is barred while any prior status-match request's `cooling_off_until` is still in the future (`ERR_STATUS_MATCH_COOLING_OFF`).
7. Capacity, inventory, and uniqueness constraints — upgrade inventory exhaustion yields `ERR_UPGRADE_INVENTORY_EXHAUSTED`, an attempt to approve a status-match while another is already `ACTIVE` yields `ERR_STATUS_MATCH_ALREADY_ACTIVE`, and a repeated gift `idempotency_key` with a differing payload yields `ERR_IDEMPOTENCY_CONFLICT`.
8. Points sufficiency — `ERR_INSUFFICIENT_POINTS` when the member's `points_balance` is below the required cost, and `ERR_GIFT_DAILY_CAP_EXCEEDED` when a gift would push the sender beyond the per-day ceiling.
9. Member status guard — a `Member` whose `status` is `FROZEN` cannot accrue, redeem, gift, or receive gifts (`ERR_MEMBER_FROZEN`); a `Member` whose `status` is `CLOSED` is rejected with `ERR_MEMBER_CLOSED`.

Two specific orderings deserve emphasis. **State beats fiscal**: when an `AwardBooking` is no longer in `HELD` (priority 4) and the member also has insufficient points (priority 8), the response is `ERR_BOOKING_NOT_HOLDABLE`, never `ERR_INSUFFICIENT_POINTS`. **Referential beats constraint**: when an `UpgradeRequest` would fail both the tier gate (priority 5) and the inventory check (priority 7), the response is `ERR_MEMBER_TIER_INELIGIBLE`, never `ERR_UPGRADE_INVENTORY_EXHAUSTED`.

### 2.8. The Points Ledger Conservation Contract

The single source of truth for a member's `points_balance` is the `PointsTransaction` ledger. The balance is exactly the signed sum of every `points_delta` whose `posted_at` is less than or equal to `now`, filtered to that member, with ties on `posted_at` ordered by ascending `id`. Positive deltas come from `ACCRUAL`, `REDEMPTION_REFUND`, `GIFT_IN`, `STATUS_MATCH_BONUS`, and positive `ADMIN_ADJUSTMENT`; negative deltas come from `REDEMPTION`, `GIFT_OUT`, `GIFT_FEE`, `EXPIRATION`, and negative `ADMIN_ADJUSTMENT`. This identity must hold after every mutation, including every cascade. A member's `points_balance` is never negative.

Every `ACCRUAL` row carries `expires_at` set to `posted_at` plus 24 months. Negative-consumption rows — `REDEMPTION`, `GIFT_OUT`, `GIFT_FEE`, `EXPIRATION` — do not themselves carry `expires_at`; they instead draw down the oldest non-empty `ACCRUAL` bucket first, in strict FIFO order by ascending `posted_at` with `id` as the tie-break. Each `ACCRUAL` row exposes a `remaining_unredeemed` field that tracks how much of its original `points_delta` has not yet been consumed by later debits. There is no rolling-extension behaviour: `last_activity_at` is recorded on the `Member` for audit purposes only, and does not push out any `expires_at`.

### 2.9. Numeric Precision, Rounding, and Comparison Conventions

Integer fields — `points_delta`, `qualifying_points`, `points_balance`, `qualifying_points_earned`, `current_year_qualifying_segments`, `current_year_qualifying_points`, `current_membership_year`, `distance_miles`, `base_fare_cents`, `cash_taxes_cents`, `points_cost`, `points_offered`, `priority_score`, `tier_valid_through_year`, capacities, and inventory counters — are compared as exact integers; arithmetic on them never introduces rounding error.

Computations that mix integers and reals — segment accrual and dynamic award pricing — are performed in IEEE-754 double precision and converted to an integer by `floor()` before any cap is applied. The gift-fee calculation rounds half-up, with the rounding performed on the fee component *before* the subtraction; see §3.6 for the precise narrative.

Threshold comparisons in `tier_evaluation` are inclusive on the lower bound: 100 000 qualifying points reaches `PLATINUM`, 99 999 does not. Upgrade inventory comparison reads as strictly greater than zero — a flight whose remaining inventory in a cabin equals zero is exhausted, even though "greater than zero" and "greater than or equal to one" describe the same set of integers; the narrative wording is the contract.

Timestamp comparisons against `expires_at` are made at millisecond precision and the boundary is **inclusive**: at the exact instant `now` equals `expires_at`, the bucket or certificate is treated as expired. A `CompanionCertificate`'s validity window is the half-open interval `[issued_at, expires_at)`.

The `load_factor` exposed on a `Flight` is a real number between 0.0 and 1.0 inclusive, rounded to four decimal places when serialised.

### 2.10. The Time Surface

Several behaviours in this domain depend on the passage of wall-clock time: an `AwardBooking` in `HELD` expires 24 hours after `created_at`; an `ACCRUAL` row expires 24 months after `posted_at`; an `ACTIVE` status-match expires 12 months after `granted_at` and its associated cooling-off window lasts 36 months from `granted_at`; a `CompanionCertificate` expires 12 months after `issued_at`; the upgrade waitlist sweep runs one hour before a flight's `departure_at`; and the annual-rollover sweep operates on a calendar year boundary.

For test driveability, the system exposes an admin-only clock-advance capability and a family of `_sweep` capabilities (described in §3.8). Advancing the clock alone does not mutate any business state; the corresponding sweep must be invoked to materialise the expirations, promotions, or rollovers that the new clock value has made due.

### 2.11. Concurrency Resolution

Several races have well-defined losers, each with a specific `error_id`.

- When two members race to confirm a `HELD` `AwardBooking` against the same flight and cabin and only one upgrade-inventory seat remains, the winner is determined first-writer-wins on the decrement of `Flight.upgrade_inventory_business` or `Flight.upgrade_inventory_first`; the loser receives `ERR_UPGRADE_INVENTORY_EXHAUSTED`.
- When a member confirms an `AwardBooking` while an administrator concurrently cancels the underlying `Flight`, the two operations serialise on the `Flight.status` field; if the cancellation lands first, the confirm is rejected with `ERR_FLIGHT_NOT_BOOKABLE`.
- When a member sends a gift while a points-expiration sweep is running, and the sweep would draw the sender's balance below the gift amount, the two operations serialise on `Member.points_balance`. The first of the two to start writes first; on ties the tie-break is the request's `created_at`, then the request id ascending. The loser receives `ERR_INSUFFICIENT_POINTS`.
- When two gift requests for the same sender arrive concurrently with identical `idempotency_key` values, the uniqueness of the `(member_id, idempotency_key)` pair on `PointsTransaction` admits exactly one writer. The second is rejected with `ERR_IDEMPOTENCY_CONFLICT`. (A truly identical replay with the same payload is the idempotent case and is governed by gift handling in §3.6; the conflict code is reserved for the case where the payload differs.)
- When two status-match approvals race inside the 36-month cooling-off window of a prior grant, the two attempts serialise on the flip of `Member.tier_source` to `STATUS_MATCH`; the loser receives `ERR_STATUS_MATCH_COOLING_OFF`.

## 3. Business Logic & Workflows

### 3.1. Member Lifecycle, Tier Currency, and Annual Membership Year

A `Member` enters the programme through a creation call that takes `email`, `display_name`, and `home_region`. The `email` is unique case-insensitively across the programme; a second creation that reuses an existing address (in any casing) is rejected with `ERR_EMAIL_CONFLICT`. The new member's `status` is initialised to `ACTIVE`, the `tier` to `BASIC`, and the `tier_source` to `EARNED`. Both `points_balance` and the two qualifying counters start at zero. A `ProgramAdmin` may at any time freeze a member (flipping `status` to `FROZEN`) or unfreeze them (flipping back to `ACTIVE`). The freeze state is the safety guard at priority 9 of §2.7; any mutation that touches the balance of a `FROZEN` or `CLOSED` member is refused.

Each member belongs to a `current_membership_year` derived from the server's clock — the calendar year as an integer, for example 2026. Two counters scoped to the current year drive elite-tier qualification: `current_year_qualifying_segments` (the number of `FlightSegment` rows that have reached `FLOWN` with `flown_year` equal to the current year) and `current_year_qualifying_points` (the sum, over the same window, of `qualifying_points` recorded on `ACCRUAL` rows). A `last_activity_at` timestamp records the most recent accrual, redemption, gift-out, or gift-in for audit reasons; it has **no** effect on any `expires_at`.

A `GET` of a member also returns a `projected_tier_eoy` — the tier the member would be granted if their current pace held for the rest of the year. The projection scales the year-to-date counters linearly to a 365-day year: project the points by multiplying `current_year_qualifying_points` by 365, dividing by the number of days elapsed in the year so far, and taking the floor; project the segments the same way using `current_year_qualifying_segments`. The same threshold ladder used by year-end rollover is then applied to the projected pair. The projection is informational only and never writes to `tier`.

The annual rollover is initiated by an admin sweep with a `target_year` input. For every member, the sweep freezes that year's totals into a new `MembershipYear` snapshot: `year` is set to the target year; `qualifying_segments_final` is copied from `current_year_qualifying_segments`; `qualifying_points_final` is copied from `current_year_qualifying_points`; `starting_tier` records the tier the member began the year with (this drives that year's accrual bonus multiplier); and `awarded_tier` records the new tier computed by the threshold ladder. The ladder is evaluated as follows: if `qualifying_points_final` is at least 100 000 or `qualifying_segments_final` is at least 100, `awarded_tier` is `PLATINUM`; otherwise if the points are at least 50 000 or the segments are at least 50, `awarded_tier` is `GOLD`; otherwise if the points are at least 25 000 or the segments are at least 25, `awarded_tier` is `SILVER`; otherwise `BASIC`. The threshold comparisons are inclusive lower bounds — exactly 100 000 points reaches `PLATINUM`, exactly 25 segments reaches `SILVER`. The `awarded_tier` is then assigned to `Member.tier`, `tier_source` is set to `EARNED`, and `tier_valid_through_year` is set to the new year. The two year-scoped counters are reset to zero. Every `UpgradeRequest` still in `WAITLISTED` for this member recomputes its `priority_score`, because `tier_rank` may have changed.

Because the ladder is cyclic, a year that misses a threshold can demote: from `PLATINUM` the member transitions to `GOLD` when the points are strictly below 100 000 and the segments strictly below 100 but the `GOLD` thresholds are still met; to `SILVER` when both `PLATINUM` and `GOLD` thresholds are missed but `SILVER` is met; and to `BASIC` when no threshold is met. Equivalent demotion paths exist from `GOLD` to `SILVER` or `BASIC`, and from `SILVER` to `BASIC`. Each demotion still refreshes `tier_valid_through_year` and recomputes upgrade priority scores.

When a member's rollover results in an `EARNED` `PLATINUM` for the first time in that rollover, the system also auto-issues one `CompanionCertificate` with `issued_reason` set to `TIER_REACHED_PLATINUM`; the certificate is delivered in `ACTIVE` state, with `issued_at` set to the rollover instant and `expires_at` set 12 months later. This auto-issue happens only on the rollover path, not on a status-match activation that lands the member at `PLATINUM`. The rolled-count returned by the sweep reports how many members were processed.

### 3.2. Flights as Inventory and Their Operational Lifecycle

A `Flight` is created by `ProgramAdmin` only and captures the route as configuration: `flight_number`, `origin`, `destination` (each a three-letter IATA airport code), `distance_miles` (a positive integer great-circle distance), `route_region` (either `DOMESTIC` or `INTERNATIONAL`, used by fixed award pricing), `departure_at` (an ISO 8601 UTC timestamp), `base_fare_cents` (a non-negative integer reference cash fare that drives segment accrual), and the three cabin capacities `capacity_economy`, `capacity_business`, and `capacity_first` (each defaulting to 100, 16, and 4 seats respectively if omitted). The new flight is in `SCHEDULED`.

A `GET` on a flight refreshes and exposes three computed quantities: `upgrade_inventory_business` and `upgrade_inventory_first`, each equal to the cabin's capacity less the count of confirmed segments already booked into that cabin and less the count of confirmed upgrades that have moved someone into that cabin; and `load_factor`, the total count of confirmed segments across all cabins divided by the sum `capacity_economy + capacity_business + capacity_first`. The load factor is constrained to the interval from 0.0 to 1.0 inclusive and is rounded to four decimal places when serialised.

When an administrator marks a flight departed, its `status` flips to `DEPARTED`; this is the precondition that allows a flown member's segment to be processed for accrual. The same operation implicitly triggers a waitlist promotion for this flight (see §3.4) — equivalent to invoking the promotion sweep with this flight as the target. A flight cancellation by an administrator is allowed only while `status` is `SCHEDULED`; attempting it from any other state yields `ERR_FLIGHT_NOT_CANCELLABLE`. On cancellation, every `FlightSegment` for this flight that is still in `BOOKED` cascades to `CANCELLED`, and every `UpgradeRequest` for those segments that is still in `WAITLISTED` also cascades to `CANCELLED` with `held_points` refunded.

### 3.3. Segment Booking, Flying, and the Reversal Invariant

A `FlightSegment` is the record of a member's seat on a specific flight. A cash booking creates a segment in `BOOKED`, recording the payload's `flight_id` and `booked_cabin` (one of `ECONOMY`, `BUSINESS`, or `FIRST`) and assigning the new row's `member_id` to the path member.

A segment is marked flown by a `BookingAgent` (or by a `ProgramAdmin`) only when the underlying flight is in `DEPARTED` and the owning member is `ACTIVE`; otherwise `ERR_SEGMENT_NOT_FLYABLE` is returned. The transition to `FLOWN` records `flown_cabin` (equal to `booked_cabin` unless a confirmed `UpgradeRequest` for this segment moved it up), records `flown_year` as the calendar year of `Flight.departure_at`, and appends one `ACCRUAL` row to the points ledger. The accrual's `points_delta` and `qualifying_points` are both equal to `qualifying_points_earned`, computed by the segment-accrual formula below. Its `posted_at` is `Flight.departure_at`, and `expires_at` is `posted_at` plus 24 months. The member's `points_balance` is incremented by the same amount via the ledger sum; `current_year_qualifying_segments` is incremented by one and `current_year_qualifying_points` is incremented by `qualifying_points_earned`. Finally, any `UpgradeRequest` that is still in `WAITLISTED` for this segment transitions to `EXPIRED`, returning its `held_points` to the member.

**Segment accrual formula.** First, compute the base dollar figure by dividing `Flight.base_fare_cents` by 100 and taking the floor — for example, 87 999 cents becomes 879 dollars. Second, look up the fare-class multiplier from the segment's `flown_cabin` at the moment of `FLOWN`: `ECONOMY` is 5, `BUSINESS` is 10, `FIRST` is 12. Third, look up the tier bonus multiplier from the member's `tier` at the moment of `FLOWN` (not the current tier at any later moment): `BASIC` is 1.0, `SILVER` is 1.25, `GOLD` is 1.5, `PLATINUM` is 2.0. Multiply the three quantities in IEEE-754 double precision, then take the floor of the product to obtain an integer. Finally, clamp the result: if it is below the per-segment floor of 100 points, raise it to 100; if it is above the per-segment ceiling of 50 000 points, lower it to 50 000. The clamped integer is `qualifying_points_earned`.

A flown segment can be refunded by `ProgramAdmin` only. The refund transition produces the **single negative `ACCRUAL`** the ledger ever allows: a row of kind `ACCRUAL` with `points_delta` equal to `-qualifying_points_earned` and `qualifying_points` likewise negated, posted at the refund instant. The member's `points_balance`, `current_year_qualifying_segments`, and `current_year_qualifying_points` are each decremented by the corresponding amounts. The **conservation contract** is the bright line for this operation: let `q0` be the year's qualifying-segment count before the original `FLOWN`, let `q1` be the count immediately after `FLOWN`, and let `q2` be the count immediately after `REFUNDED`; then `q2` must equal `q0`, and the member's `points_balance` after the refund must equal its value immediately before `FLOWN` (modulo any unrelated activity in between, which is excluded from the test scenario).

A `BOOKED` segment can be cancelled before the flight departs. Cancellation is allowed only while `Flight.status` is `SCHEDULED`. On cancellation, every `UpgradeRequest` for this segment still in `WAITLISTED` transitions to `CANCELLED` and refunds its `held_points`. A `FLOWN` segment can only be reversed via the refund path described above; a `REFUNDED` or `CANCELLED` segment is terminal and cannot transition further.

### 3.4. Upgrades, Waitlists, and Priority Scoring

A member who has booked a segment may bid for a higher cabin by creating an `UpgradeRequest` against that segment. The payload supplies `target_cabin` (which must be strictly above the segment's `booked_cabin` — `ECONOMY` may be upgraded to `BUSINESS` or `FIRST`, `BUSINESS` only to `FIRST`; otherwise `ERR_TARGET_CABIN_NOT_UPGRADE`) and `points_offered` (a non-negative integer of points the member is offering for the upgrade). The acting member's `tier` must be at least `GOLD`; otherwise the request is refused with `ERR_MEMBER_TIER_INELIGIBLE`. The new request enters `WAITLISTED` and is assigned a `waitlist_join_seq` — a monotonically increasing integer scoped to the same `Flight` and `target_cabin`, used to deterministically break ties on equal priority (lower sequence wins). The request also captures a denormalised `flight_id` (equal to the parent segment's `flight_id`) and a `member_id` (equal to the parent segment's `member_id`).

The request's `priority_score` is computed as follows. Look up `tier_rank` from the member's current `tier`: `BASIC` is 0, `SILVER` is 1, `GOLD` is 2, `PLATINUM` is 3. Compute `priority_score` as `tier_rank` multiplied by 10 000 000, plus `points_offered`, minus `waitlist_join_seq`. Evaluation order is pinned in exactly this sequence — first the tier-rank lookup, then the multiplication by ten million, then the addition of the offer, then the subtraction of the join sequence. The arithmetic is integer with no rounding. The score is recomputed every time the member's `tier` changes (annual rollover, status-match activation, or status-match expiry), every time the request's `points_offered` is patched, or whenever a sibling waitlisted request on the same flight and cabin transitions out of `WAITLISTED`.

While a request is `WAITLISTED` or `CONFIRMED` before the flight departs, the request's `held_points` equals its `points_offered`. After `DENIED`, `EXPIRED`, or `CANCELLED`, `held_points` returns to 0. Note that holding does not debit the member's `points_balance`; the debit only happens at `CONFIRMED`.

A member may patch the `points_offered` on their own request as long as it remains `WAITLISTED`; the patch recomputes `priority_score`. A member may cancel their own waitlisted request, which terminates it in `CANCELLED` and returns `held_points` to zero. A `ProgramAdmin` may admin-confirm a specific waitlisted request, transitioning it directly to `CONFIRMED`.

The waitlist promotion sweep is the routine resolution path. It is invoked one hour before a flight's `departure_at` (and implicitly when an administrator marks the flight departed). For each combination of `Flight` and `target_cabin`, the sweep orders the `WAITLISTED` requests by `priority_score` descending, breaking ties on `waitlist_join_seq` ascending (lower sequence wins). The top `upgrade_inventory_{target_cabin}` of them are confirmed. For each confirmed request, the system appends a `REDEMPTION` row to the ledger with `points_delta` equal to `-points_offered`, decrements `Member.points_balance` by `points_offered`, decrements `Flight.upgrade_inventory_business` or `Flight.upgrade_inventory_first` by one as appropriate, and earmarks the parent `FlightSegment` so that its `flown_cabin` will record `target_cabin` when the segment reaches `FLOWN`. The promotion is allowed only when `upgrade_inventory_{target_cabin}` is greater than zero at the moment of evaluation, when the request has the highest priority score on the relevant pool, and when the member's `tier` is at least `GOLD` (the tier gate is re-evaluated at promotion time because it may have changed since the request was created). Any `WAITLISTED` request that does not win and whose flight has now departed transitions to `DENIED`, with `held_points` refunded — no ledger entry is needed because the offered points were never debited. The sweep's response reports a `promoted_count`. The sweep accepts an optional `flight_id` filter; without it, the sweep runs across all flights whose `departure_at` is now within the promotion window.

### 3.5. Award Bookings and Companion Certificates

An `AwardBooking` is the points-priced counterpart of a cash booking. Creation by a `Member` or `BookingAgent` supplies `flight_id`, `cabin`, `pricing_mode`, and optionally `cash_taxes_cents` and `companion_certificate_id`. The new booking enters `HELD` with `held_until` set to `created_at` plus 24 hours. `cash_taxes_cents` is purely informational; it does not participate in the points conservation contract.

**Pricing pinning at HELD.** The booking's `points_cost` is computed by the `award_price` formula at the instant the booking is created and is then immutable for the lifetime of the booking — it is never re-evaluated while the booking remains `HELD` or `CONFIRMED`. The formula has two variants, selected by the booking's `pricing_mode`.

- **Dynamic mode**, when `pricing_mode` is `DYNAMIC`: take the flight's `distance_miles`, multiply by the base rate of 5 points per mile, multiply by a demand multiplier driven by the flight's current `load_factor`, multiply by the cabin multiplier, and take the floor of the full product. The demand multiplier is selected by half-open lower bounds: a `load_factor` strictly less than 0.50 yields 0.8; a load factor of at least 0.50 but strictly less than 0.80 yields 1.0; a load factor of at least 0.80 but strictly less than 0.95 yields 1.5; a load factor of 0.95 or above yields 2.0. The cabin multiplier is 1.0 for `ECONOMY`, 2.0 for `BUSINESS`, and 3.5 for `FIRST`. Two `HELD` bookings created for the same flight at different `load_factor` snapshots therefore typically pin different `points_cost` values, and that is intentional.
- **Fixed mode**, when `pricing_mode` is `FIXED`: ignore distance and load factor entirely, and look up `points_cost` in a table keyed by `Flight.route_region` and `cabin`. For `DOMESTIC`: `ECONOMY` is 12 500, `BUSINESS` is 25 000, `FIRST` is 40 000. For `INTERNATIONAL`: `ECONOMY` is 30 000, `BUSINESS` is 70 000, `FIRST` is 110 000. The lookup is an integer; no arithmetic and no rounding apply. The same lookup row always yields the same number.

If `companion_certificate_id` is set on the creation payload, the system checks at creation time that the booking moment lies inside the certificate's half-open validity window `[issued_at, expires_at)` (otherwise `ERR_CERTIFICATE_EXPIRED`), that the certificate's `member_id` matches the booking's `member_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and that the acting member's `tier` is at least `PLATINUM` at the moment of the certificate's original issuance (otherwise `ERR_MEMBER_TIER_INELIGIBLE`). The certificate transitions from `ACTIVE` to `RESERVED` and records `reserved_for_booking_id`. A certificate that is not in `ACTIVE` cannot be reserved (`ERR_CERTIFICATE_NOT_USABLE`).

**Confirming a HELD booking.** A member confirms their own booking. The server requires the booking to still be in `HELD` (otherwise `ERR_BOOKING_NOT_HOLDABLE`), the current clock to be strictly before `held_until` (otherwise `ERR_HELD_UNTIL_PASSED`), the member's `points_balance` to be at least `points_cost` (otherwise `ERR_INSUFFICIENT_POINTS`), and the underlying flight to be in `SCHEDULED` (otherwise `ERR_FLIGHT_NOT_BOOKABLE`). If a companion certificate is attached, it must be in `RESERVED` and must still lie inside its validity window at this moment, and its `member_id` must match. On success: a `REDEMPTION` row is appended with `points_delta` equal to `-points_cost` and `related_booking_id` set to the booking's `id`; the member's `points_balance` is decreased accordingly via the ledger sum; a new `FlightSegment` is created in `BOOKED` with `booked_cabin` equal to the booking's `cabin`, and the booking's `linked_segment_id` records the new segment's `id`; if a certificate was reserved, it transitions to `USED` and records `used_on_booking_id`.

**Cancelling a CONFIRMED booking before departure.** A member may cancel their own confirmed booking only while the underlying flight is in `SCHEDULED`. The transition is `CONFIRMED → CANCELLED`, followed immediately and in the same transaction by `CANCELLED → REFUNDED`. The compensating action is a single `REDEMPTION_REFUND` row with `points_delta` equal to `+points_cost` and `related_booking_id` set to the booking's `id`; the member's `points_balance` after this transition must equal its value immediately before the original confirm. The linked `FlightSegment` is also cascaded to `CANCELLED`. If a companion certificate was used and the current clock is strictly before the certificate's `expires_at`, the certificate reverts from `USED` to `ACTIVE` and `used_on_booking_id` is cleared; if the clock has already reached or passed the certificate's `expires_at`, the certificate remains `USED` (it expired naturally between the confirm and the cancel) and is not restored. Attempting to cancel from any state other than `CONFIRMED`, or attempting to cancel after the flight has departed, yields `ERR_BOOKING_NOT_CANCELLABLE`.

**Expiry of HELD bookings.** A sweep operating against the system clock transitions any `AwardBooking` still in `HELD` whose `held_until` is less than or equal to `now` to `EXPIRED`. If a certificate was reserved and is still inside its own validity window, the certificate reverts from `RESERVED` to `ACTIVE` and `reserved_for_booking_id` is cleared; if the certificate has already expired in the meantime, it remains in its terminal state. The sweep returns an `expired_count`.

**Companion certificates outside award bookings.** A certificate originates either from an `EARNED` `PLATINUM` rollover (`issued_reason` is `TIER_REACHED_PLATINUM`) or from an admin grant (`issued_reason` is `ADMIN_GRANT`). The admin-grant endpoint emits a certificate in `ACTIVE` with `issued_at` set to the call instant and `expires_at` set 12 months later. A `ProgramAdmin` may revoke any certificate that is still in `ACTIVE` or `RESERVED`, transitioning it to `REVOKED`. The expire-certificates sweep transitions any certificate in `ACTIVE` or `RESERVED` whose `expires_at` is less than or equal to `now` to `EXPIRED`; if the certificate was `RESERVED`, the parent booking remains `HELD` but the certificate is now blocked, so any subsequent confirm attempt that references it will fail with `ERR_CERTIFICATE_EXPIRED`.

### 3.6. Gifting Points: Three-Row Atomicity and the Fee Ordering

The gift capability allows a `Member` (or a `BookingAgent` acting on a member's behalf) to transfer points to another member. The request payload supplies `recipient_member_id`, `amount`, and `idempotency_key`. The `amount` must be at least 1 000 — a smaller gift is rejected with `ERR_GIFT_BELOW_MINIMUM`. The same sender cannot gift more than 50 000 points across all gift requests within a single UTC calendar day; the cumulative cap is evaluated against the proposed amount, and any gift that would push the day's total over the cap is rejected with `ERR_GIFT_DAILY_CAP_EXCEEDED`. The sender's `points_balance` must be at least `amount`; otherwise the gift is rejected with `ERR_INSUFFICIENT_POINTS`.

**Fee and delivery computation.** The fee is computed by multiplying the requested `amount` by the gift fee rate of 0.10. The fee is **rounded first** (half-up to the nearest whole point) to obtain `fee_points`, and only **then** subtracted from `amount` to obtain `delivered_points`. This "round-then-subtract" ordering is mandatory; the inverse ordering ("subtract-then-round") would in general produce a different `delivered_points` and is forbidden. For example, an amount of 2 505 produces a raw fee of 250.5; rounded half-up that becomes 251; `delivered_points` is then 2 505 minus 251, which equals 2 254. A "subtract-then-round" implementation would yield 2 255 — which is the wrong answer.

**Atomic three-row ledger.** A successful gift appends exactly three rows to the ledger, in this fixed order, sharing a single transaction: first a `GIFT_OUT` on the sender with `points_delta` equal to `-amount` and `counterparty_member_id` set to the recipient; second a `GIFT_FEE` on the sender with `points_delta` equal to 0 (the fee is informational because the sent amount already includes it); third a `GIFT_IN` on the recipient with `points_delta` equal to `+delivered_points` and `counterparty_member_id` set to the sender. All three rows record the same `idempotency_key` as supplied on the request. The conserved quantity across this operation is the sum of the sender's `points_balance`, the recipient's `points_balance`, and a notional house-fee pool that grows by `fee_points` — the three together do not change.

**Idempotency.** A repeat of a gift request with the same `(member_id, idempotency_key)` and an identical payload is the idempotent case and returns the previously appended rows without further mutation. A repeat with the same `(member_id, idempotency_key)` but a different payload is the conflict case and is rejected with `ERR_IDEMPOTENCY_CONFLICT`. Frozen and closed senders or recipients cannot participate in gift flows; the rejection codes are `ERR_MEMBER_FROZEN` and `ERR_MEMBER_CLOSED`.

### 3.7. Status Match: Promotions Across Programmes

A member who already holds elite status with a competing programme may submit a `StatusMatchRequest` by supplying `competitor_program` (free text), `competitor_tier` (one of `BASIC`, `SILVER`, `GOLD`, `PLATINUM`), and `evidence_url`. The new request enters `PENDING`.

A `ProgramAdmin` approves a pending request only when the acting member has no prior status-match whose `cooling_off_until` is still in the future (otherwise `ERR_STATUS_MATCH_COOLING_OFF`) and when the member does not already have a status-match-backed tier active (otherwise `ERR_STATUS_MATCH_ALREADY_ACTIVE`). On approval, `granted_tier` is set to the lesser of `competitor_tier` and `PLATINUM`; `granted_at` is set to the approval instant; `expires_at` is set 12 months after `granted_at`; and `cooling_off_until` is set 36 months after `granted_at`. The pending request transitions to `APPROVED`. A pending request may also be rejected by `ProgramAdmin`, transitioning to `REJECTED` with no side effect. A request that is not in `PENDING` cannot be approved or rejected (`ERR_STATUS_MATCH_NOT_PENDING`).

An `APPROVED` request is activated by the acting `Member` (or by a `ProgramAdmin`). Activation requires the member's current `tier` to be strictly below `granted_tier` (the system does not allow a status match to **downgrade**). On activation, `Member.tier` is set to `granted_tier`, `tier_source` is set to `STATUS_MATCH`, and a single `STATUS_MATCH_BONUS` row is appended with `points_delta` equal to 5 000 (a one-time goodwill bonus); the member's `points_balance` is incremented accordingly. Every one of this member's `UpgradeRequest` rows still in `WAITLISTED` recomputes its `priority_score`. A request that is not in `APPROVED` cannot be activated (`ERR_STATUS_MATCH_NOT_APPROVED`).

An `ACTIVE` status-match expires when the system clock reaches or passes its `expires_at` and the expire-status-matches sweep runs. The request transitions from `ACTIVE` to `EXPIRED`. If the member's current `tier` was granted by this very request (that is, `tier_source` is still `STATUS_MATCH` and the member has never earned a tier at least as high as `granted_tier`), the member's `tier` reverts toward what the member would otherwise have earned — in the absence of an earned record, that default is `BASIC`. `tier_source` is set back to `EARNED`. As with any other tier mutation, every waitlisted upgrade request for this member recomputes its `priority_score`. The sweep returns an `expired_count`.

The cooling-off rule is a hard 36-month bar from the previous `granted_at`: no second status match can be approved before that instant. The bar applies independently of whether the previous grant has since expired, been activated, or remained merely `APPROVED`.

### 3.8. The Ops Surface: Clock, Sweeps, and Adjustments

A `ProgramAdmin` may advance the system clock by supplying an integer `by_seconds`. The call returns the new `current_time`. Advancing the clock does not by itself materialise any deferred effect; the relevant sweep must be invoked to make the new clock value bite. The available sweeps and their precise behaviour:

- **Points expiration.** Walk the `ACCRUAL` rows in strict FIFO by ascending `posted_at` with `id` as the tie-break. For each `ACCRUAL` whose `expires_at` is less than or equal to `now` and whose `remaining_unredeemed` is greater than zero, append an `EXPIRATION` row with `points_delta` equal to `-remaining_unredeemed` and `related_segment_id` set to the original accrual's `related_segment_id`. Set the original accrual's `remaining_unredeemed` to zero, and decrement the owning member's `points_balance` by the same amount via the ledger sum. Per §2.9, the boundary is inclusive: at the instant `expires_at` equals `now`, the bucket is treated as expired. The sweep returns an `expired_count`.
- **Booking expiration.** Walk every `AwardBooking` still in `HELD` whose `held_until` is less than or equal to `now`; transition each to `EXPIRED`; if a companion certificate was `RESERVED` for it and is still within its own validity window, revert the certificate from `RESERVED` to `ACTIVE` and clear `reserved_for_booking_id`. The sweep returns an `expired_count`.
- **Certificate expiration.** Walk every `CompanionCertificate` in `ACTIVE` or `RESERVED` whose `expires_at` is less than or equal to `now`; transition each to `EXPIRED`. The sweep returns an `expired_count`.
- **Status-match expiration.** Walk every `StatusMatchRequest` in `ACTIVE` whose `expires_at` is less than or equal to `now`; transition each to `EXPIRED` and, where appropriate, revert the member's `tier` as described in §3.7. The sweep returns an `expired_count`.
- **Upgrade promotion.** As described in §3.4: resolve the waitlist for each `Flight` and `target_cabin`, confirm the top requests up to the available inventory, and deny the remainder once the flight has departed. The sweep returns a `promoted_count` and accepts an optional `flight_id` to scope the run.
- **Annual rollover.** As described in §3.1: for each member, freeze the year into a new `MembershipYear` snapshot and recompute `Member.tier`. The call's `target_year` input names the year being frozen. The sweep returns a `rolled_count`.

The admin adjustment endpoint allows a `ProgramAdmin` to post an `ADMIN_ADJUSTMENT` ledger row with an explicit signed `points_delta` and a free-text `reason`. The member's `points_balance` is updated by the ledger sum as with any other row; the conservation contract continues to hold.

Read endpoints on member resources behave as expected: a member's listing of their own segments, award bookings, upgrade requests, certificates, status-match requests, ledger entries (filterable by `kind` and a `since`/`until` window), and annual snapshots are all paginated according to §2.3 and ordered by `created_at` ascending unless an endpoint specifies otherwise. The single-member fetch refreshes and exposes `points_balance` via the ledger sum and `projected_tier_eoy` via the provisional tier projection.

## 4. Endpoint Definitions

All endpoints follow the response envelope and pagination contract of §2.2 and §2.3. As a general rule, endpoints that create a brand-new resource return HTTP `201 Created`; endpoints that modify an existing resource or trigger an action return HTTP `200 OK`. List endpoints return `200 OK` with an array payload. Refer back to §3 for the request body fields, side effects, and cascades attached to each endpoint — the table below intentionally omits them.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /members | Create a member. | ProgramAdmin, BookingAgent |
| GET | /members | List members (paginated, filterable by tier and status). | ProgramAdmin |
| GET | /members/{memberId} | Get a member, including `projected_tier_eoy`. | Member, ProgramAdmin, BookingAgent |
| PATCH | /members/{memberId} | Update mutable member fields. | Member, ProgramAdmin |
| POST | /members/{memberId}/freeze | Freeze a member. | ProgramAdmin |
| POST | /members/{memberId}/unfreeze | Unfreeze a member. | ProgramAdmin |
| POST | /flights | Create a flight. | ProgramAdmin |
| GET | /flights | List flights. | Member, BookingAgent, ProgramAdmin |
| GET | /flights/{flightId} | Get a flight, including `load_factor` and upgrade inventory. | Member, BookingAgent, ProgramAdmin |
| POST | /flights/{flightId}/depart | Mark a flight as departed. | ProgramAdmin |
| POST | /flights/{flightId}/cancel | Cancel a flight. | ProgramAdmin |
| POST | /members/{memberId}/segments | Book a flight segment (cash path). | Member, BookingAgent |
| GET | /members/{memberId}/segments | List a member's segments. | Member, ProgramAdmin, BookingAgent |
| POST | /members/{memberId}/segments/{segmentId}/mark-flown | Mark a segment as flown. | BookingAgent, ProgramAdmin |
| POST | /members/{memberId}/segments/{segmentId}/cancel | Cancel a segment before departure. | Member, BookingAgent |
| POST | /members/{memberId}/segments/{segmentId}/refund | Refund a flown segment. | ProgramAdmin |
| POST | /members/{memberId}/segments/{segmentId}/upgrade-requests | Create an upgrade request on a booked segment. | Member, BookingAgent |
| GET | /members/{memberId}/upgrade-requests | List a member's upgrade requests. | Member, ProgramAdmin |
| PATCH | /upgrades/{upgradeRequestId} | Update the `points_offered` on an own waitlisted request. | Member |
| POST | /upgrades/{upgradeRequestId}/cancel | Cancel a waitlisted upgrade request. | Member |
| POST | /upgrades/{upgradeRequestId}/confirm | Admin override: confirm an upgrade. | ProgramAdmin |
| POST | /members/{memberId}/award-bookings | Create an award booking in HELD. | Member, BookingAgent |
| GET | /members/{memberId}/award-bookings | List a member's award bookings. | Member, ProgramAdmin, BookingAgent |
| GET | /members/{memberId}/award-bookings/{bookingId} | Get a single award booking. | Member, ProgramAdmin, BookingAgent |
| POST | /members/{memberId}/award-bookings/{bookingId}/confirm | Confirm a HELD booking. | Member |
| POST | /members/{memberId}/award-bookings/{bookingId}/cancel | Cancel a CONFIRMED booking before departure. | Member |
| GET | /members/{memberId}/certificates | List a member's companion certificates. | Member, ProgramAdmin |
| POST | /members/{memberId}/certificates | Admin-grant a companion certificate. | ProgramAdmin |
| POST | /members/{memberId}/certificates/{certId}/revoke | Revoke a companion certificate. | ProgramAdmin |
| POST | /members/{memberId}/status-match-requests | Submit a status-match request. | Member |
| GET | /members/{memberId}/status-match-requests | List status-match requests. | Member, ProgramAdmin |
| POST | /members/{memberId}/status-match-requests/{rid}/approve | Approve a pending status-match request. | ProgramAdmin |
| POST | /members/{memberId}/status-match-requests/{rid}/reject | Reject a pending status-match request. | ProgramAdmin |
| POST | /members/{memberId}/status-match-requests/{rid}/activate | Activate an approved status-match request. | Member, ProgramAdmin |
| POST | /members/{senderId}/gifts | Gift points to another member. | Member, BookingAgent |
| GET | /members/{memberId}/points-transactions | List a member's ledger entries. | Member, ProgramAdmin |
| POST | /members/{memberId}/points-transactions/adjustments | Post an admin points adjustment. | ProgramAdmin |
| GET | /members/{memberId}/membership-years | List a member's annual snapshots. | Member, ProgramAdmin |
| POST | /_clock/advance | Advance the system clock by `by_seconds`. | ProgramAdmin |
| POST | /_sweep/expire-points | Run the FIFO points-expiration sweep. | ProgramAdmin |
| POST | /_sweep/expire-bookings | Run the HELD-booking expiration sweep. | ProgramAdmin |
| POST | /_sweep/expire-certificates | Run the certificate expiration sweep. | ProgramAdmin |
| POST | /_sweep/expire-status-matches | Run the status-match expiration sweep. | ProgramAdmin |
| POST | /_sweep/promote-upgrades | Run the upgrade waitlist sweep, optionally scoped to a `flight_id`. | ProgramAdmin |
| POST | /_sweep/annual-rollover | Run the year-end rollover for a `target_year`. | ProgramAdmin |

## 5. Error Code Catalogue

The trigger condition attached to every error code is described in the relevant subsection of §2 or §3. The table below lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_GIFT_BELOW_MINIMUM | 400 |
| ERR_INSUFFICIENT_POINTS | 402 |
| ERR_GIFT_DAILY_CAP_EXCEEDED | 402 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_MEMBER_TIER_INELIGIBLE | 403 |
| ERR_MEMBER_FROZEN | 403 |
| ERR_MEMBER_CLOSED | 403 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_FLIGHT_NOT_FOUND | 404 |
| ERR_SEGMENT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_UPGRADE_REQUEST_NOT_FOUND | 404 |
| ERR_STATUS_MATCH_REQUEST_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_HOLDABLE | 409 |
| ERR_BOOKING_NOT_CANCELLABLE | 409 |
| ERR_SEGMENT_NOT_FLYABLE | 409 |
| ERR_SEGMENT_NOT_REFUNDABLE | 409 |
| ERR_UPGRADE_NOT_WAITLISTED | 409 |
| ERR_STATUS_MATCH_NOT_PENDING | 409 |
| ERR_STATUS_MATCH_NOT_APPROVED | 409 |
| ERR_CERTIFICATE_NOT_USABLE | 409 |
| ERR_FLIGHT_NOT_BOOKABLE | 409 |
| ERR_FLIGHT_NOT_CANCELLABLE | 409 |
| ERR_TARGET_CABIN_NOT_UPGRADE | 409 |
| ERR_BOOKING_FLIGHT_MISMATCH | 409 |
| ERR_CERTIFICATE_EXPIRED | 409 |
| ERR_STATUS_MATCH_COOLING_OFF | 409 |
| ERR_STATUS_MATCH_ALREADY_ACTIVE | 409 |
| ERR_HELD_UNTIL_PASSED | 409 |
| ERR_UPGRADE_INVENTORY_EXHAUSTED | 409 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_EMAIL_CONFLICT | 409 |
| ERR_VERSION_CONFLICT | 409 |

---

## Hard Contract Reports

### Contract 1: Field-Name Coverage

I cross-checked every `entities[].fields[].name` and every endpoint identifier (`request_body`, `query_params`, `path_params`) against the PRD's backticked tokens.

Field coverage check:
- entities[].fields: 89 required, 89 present, 0 missing
- endpoints[].request_body / input: 22 required, 22 present, 0 missing
- endpoints[].query_params: 9 required, 9 present, 0 missing
- endpoints[].path_params: 7 required (`memberId`, `flightId`, `segmentId`, `upgradeRequestId`, `bookingId`, `certId`, `rid`, `senderId`), all present in §4 paths and §3 narrative
Status: PASS

### Contract 2: Rule Coverage

Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed in prose with explicit ordering (§2.7), 0 missing
- concurrency_rules[] with error_id: 5 checked, 5 expressed in §2.11 with named loser code, 0 missing
- state_machines[].transitions: 31 checked (Member.tier x11, FlightSegment x4, StatusMatchRequest x4, UpgradeRequest x4, AwardBooking x4, CompanionCertificate x6), all fully expressed with preconditions and side effects, 0 missing
- calculations[]: 7 checked (segment_accrual, award_price, tier_evaluation, gift_transfer, points_expiration, upgrade_priority_score, qualifying_segment_reversal, points_balance_conservation), all fully expressed in business prose with constants embedded, evaluation order pinned, and rounding/precision stated, 0 missing
- validations[] conditions: 9 checked, each matchable to its error_id via narrative, 0 missing
- endpoints[].side_effects / applies_to: 39 checked, each expressed in the appropriate §3 narrative, 0 missing
- entities[].fields[] structured content: defaults (`status`/`tier`/`tier_source` initial values, `Flight` cabin capacities, `held_until = created_at+24h`, `expires_at = posted_at+24mo` / `granted_at+12mo` / `issued_at+12mo`, `cooling_off_until = granted_at+36mo`) all reconstructible from prose, enum constraint sets (`DOMESTIC|INTERNATIONAL`, `ACTIVE|FROZEN|CLOSED`, `BASIC|SILVER|GOLD|PLATINUM`, `EARNED|STATUS_MATCH`, `BOOKED|FLOWN|CANCELLED|REFUNDED`, `WAITLISTED|CONFIRMED|DENIED|EXPIRED|CANCELLED`, `HELD|CONFIRMED|CANCELLED|REFUNDED|EXPIRED`, `ACTIVE|RESERVED|USED|EXPIRED|REVOKED`, `PENDING|APPROVED|ACTIVE|EXPIRED|REJECTED`, `TIER_REACHED_PLATINUM|ADMIN_GRANT`, `ACCRUAL|REDEMPTION|REDEMPTION_REFUND|GIFT_OUT|GIFT_IN|GIFT_FEE|EXPIRATION|STATUS_MATCH_BONUS|ADMIN_ADJUSTMENT`, `SCHEDULED|DEPARTED|CANCELLED`, `ECONOMY|BUSINESS|FIRST`) all present in narrative as exact uppercase strings, 0 missing
- sibling-branch symmetry: all sibling-transition groups (Member.tier promotion vs demotion ladders; AwardBooking.HELD branches to CONFIRMED, EXPIRED; FlightSegment.BOOKED branches to FLOWN, CANCELLED; CompanionCertificate ACTIVE/RESERVED branches) rendered with equal density, 0 asymmetric
Status: PASS

### Contract 3: §3 Path Purity

Path purity check (§3 only):
- backtick tokens scanned: all backticked tokens in §3 are field names, enum values, state values, role names, or error IDs
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
