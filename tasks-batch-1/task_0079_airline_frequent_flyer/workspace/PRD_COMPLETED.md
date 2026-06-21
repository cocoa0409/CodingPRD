# Airline Frequent Flyer & Upgrade Program API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for an airline loyalty program that rewards members for the flights they take and lets them spend what they earn. Members accumulate two distinct currencies of value as they fly: redeemable **points**, which are a spendable balance used to book award travel and to gift to other members, and qualifying **segments**, which are a year-scoped count that determines a member's loyalty **tier**. The program is built around several intertwined concerns that the engineering team must implement faithfully: a points-accrual engine that rewards completed segments according to fare paid, distance, fare class, and the member's standing at the moment of accrual; a tiering system whose annual thresholds gate benefits and whose standing can be temporarily lifted by a once-in-a-lifetime status match against a rival airline; an award-pricing engine that supports two different, equally valid pricing algorithms over the same fare inputs; a finite, priority-ranked upgrade waitlist where members compete for a scarce premium cabin; companion certificates and peer-to-peer points gifting that both move conserved quantities and therefore require careful compensating-invariant accounting; and a rolling expiration clock that burns points after a window of account inactivity.

Because so much of the program's behavior is time-driven — expirations, status-match validity windows, the year-end tier reset, and the eligibility of flights and clearing runs — the service exposes a single, deterministic logical clock that a test harness advances explicitly. All temporal decisions read this one clock rather than the host wall time. The reader should treat the clock as the authoritative "now" everywhere this document refers to the current instant.

The audience for this document is the engineer building the REST service. It describes the domain first and the wire contract second; field names, enumerated values, calculation constants, and error identifiers are stated exactly because the implementation and its automated test suite must agree on them precisely.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers that together identify the caller: `X-User-ID` and `X-User-Role`. The `X-User-Role` header must name one of the three recognized roles, spelled exactly as `ProgramAdmin`, `OperationsAgent`, or `Member`. If either header is missing, or if `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The three roles relate to identity differently:

- When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may accept and record it but does not compare it to any entity's `id`. A `ProgramAdmin` is the loyalty-program operator: it registers members, issues companion certificates, grants status matches, advances the clock, and may read any resource in the system.
- When `X-User-Role` is `OperationsAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. An `OperationsAgent` handles flight operations: booking, flying, accruing, and cancelling flight segments, creating flight pools, running upgrade clearing, and marking issued awards as flown.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a `Member` compare the resource's owning member field to `X-User-ID`. A `Member` acts on their own awards, upgrade requests, gifts, and certificate-attached bookings.

Several operations are restricted to the resource's owner. For a `Member` acting on an owned resource — issuing, cancelling, or flying their own award booking; withdrawing their own upgrade request; settling or reversing a gift on which they are the sender — the acting `X-User-ID` must equal the owner identifier recorded on the resource (the award's, request's, or gift's owning member). When a `Member` targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints are paginated through two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

List results are always sorted by their creation timestamp (`created_at`) in ascending order before pagination is applied. Alongside the page of `data`, the response `meta` carries the pagination bookkeeping fields `limit`, `offset`, `total_count` (the total number of records matching the query before the page window is applied), and `has_more` (a boolean that is true when records remain beyond the current window).

### 2.4. Common Resource Properties and Versioning

Most entities carry a common set of system-managed properties. Each such record has an `id` — a server-minted UUID string with no type prefix — together with a `created_at` and an `updated_at` timestamp (both ISO 8601 UTC with millisecond precision) and an integer `version`. The `version` begins at 1 when a record is created and increments by exactly 1 on every mutation of that record; `updated_at` is refreshed to the current clock instant on every mutation. These common properties apply to `Member`, `FlightSegment`, `AwardBooking`, `UpgradeRequest`, `FlightPool`, `CompanionCertificate`, `PointsGift`, and `StatusMatch`.

Two entities are bookkeeping records and do **not** carry the full common set: the `PointsLedger` row and the `ClockState` record carry only `id` and `created_at`; they have neither an `updated_at` nor a `version` field, because they are never mutated in place (ledger rows are append-only and the clock is replaced wholesale).

### 2.5. The Logical Clock and Deterministic Time

The service maintains a single mutable system clock, represented by the `ClockState` record, whose `current_utc` field is the authoritative present instant and whose `program_year` field is the calendar year derived from `current_utc`. Until the clock is advanced for the first time, `current_utc` is `null` and `program_year` is `0`; reading the clock before any advance returns those values, and while the clock is unset all temporal decisions fall back to the host wall-clock time. Every temporal decision in the system — points expiration, certificate and status-match validity windows, the gating of flight and clearing operations, and the year-end tier reset — reads `current_utc`. Advancing the clock is a privileged test-driving capability: it sets `current_utc` to a supplied instant, re-derives `program_year`, and then runs the deferred sweeps described in Section 3.7. The clock may also be read back at any time.

### 2.6. The Points Ledger and Balance Reconciliation

Every movement of points is recorded as an append-only `PointsLedger` row. Each row records the owning `member_id`, a signed `delta` (which must be non-zero — positive for accrual, inbound gifts, and status-match bonuses; negative for redemptions, outbound gifts, and expirations), a `reason` drawn from `ACCRUAL`, `REDEMPTION`, `REDEMPTION_REFUND`, `GIFT_OUT`, `GIFT_IN`, `STATUS_MATCH_BONUS`, and `EXPIRY`, and a polymorphic origin given by `source_type` (one of `FlightSegment`, `AwardBooking`, `PointsGift`, `StatusMatch`, or `System`) together with the originating record's `source_id`. The `source_id` is an identity reference only and is never itself an input to any business decision. Positive lots that can expire — those created by accrual, inbound gifts, and status-match bonuses — also carry an `expires_at` instant; negative rows leave `expires_at` null.

A member's `points_balance` is the conserved running total of non-expired ledger activity and is floored at 0; it never goes negative. The balance moves only through the cascades described in Section 3, and the ledger is the system of record from which it is derived.

### 2.7. Tiering, Effective Tier, and the Status-Match Floor

A member's standing is captured by three related notions that must be kept distinct. The stored `tier` (one of `BASE`, `SILVER`, `GOLD`, `PLATINUM`) is the tier earned from qualifying activity. A separately tracked **effective tier** is the tier that actually governs benefits at any instant: it is the higher of the earned tier and any floor imposed by an active status match. The flags `status_match_active` (true while a granted match is within its validity window) and `status_match_used` (true once the member has ever consumed their single lifetime match) track the status-match state. The exact recomputation procedure that ties these together is given in Section 3.4; the key cross-cutting principle is that earned tier never decreases within a program year — it is a monotonic ratchet — and only the year-end run may lower it.

### 2.8. Precision and Rounding

Points are always whole integers. Wherever a calculation produces a fractional intermediate value, the final result is rounded half-up to the nearest integer at the point indicated in the relevant formula in Section 3. Threshold comparisons for tiering are exact integer comparisons. Monetary fare inputs are ordinary numbers and need not be integers, but every points quantity stored or moved is an integer.

### 2.9. Optimistic Concurrency on Contended Writes

Two write operations guard a shared parent record with an optimistic-concurrency check, because both act on accounting that another writer may have already advanced.

First, joining a flight pool's upgrade waitlist must carry `expected_flightpool_version`, the version of the target `FlightPool` that the client last observed. If that value does not match the pool's current `version` — for example because a clearing run or another joiner has already mutated the pool's seat accounting since the client read it — the create is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412), preventing the client from acting on a stale view of remaining seats.

Second, settling a points gift must carry `expected_member_version`, the version of the sender `Member` that the client last observed. If that value does not match the sender's current `version` — for example because an award redemption or a prior gift settlement has already lowered the sender's `points_balance` since the client read it — the settle is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412), preventing the client from settling against a stale view of available points.

Every other write endpoint does not take a version field and performs no such check.

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership for member-owned operations (`ERR_NOT_RESOURCE_OWNER`). Next, the existence of every path and referenced resource is checked, validated left to right across the path and any foreign keys (`ERR_NOT_FOUND`). After existence comes the legality of the requested state transition (`ERR_INVALID_STATE`), then the optimistic-concurrency version check on contended writes (`ERR_STALE_POOL_VERSION` or `ERR_STALE_MEMBER_VERSION`). The remaining business rules follow in the order: lifetime status-match exhaustion, companion-certificate validity, gift-to-self, departure-not-reached, dynamic-pricing load-factor, single-run pool clearing, sufficient points for a debit, and finally generic input-domain validation (`ERR_VALIDATION`). In short: a missing or malformed identity is reported before any role decision, role and ownership before existence, existence before state, state before staleness, and the domain-specific business constraints last, with raw field-shape validation as the final fallback.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding and the Account Snapshot

A loyalty account is created when a `ProgramAdmin` registers a member, supplying the member's contact `email`, their legal `full_name`, and their `home_airport`. The email is required, non-empty, and unique across all members; a second registration of an already-registered email is rejected with `ERR_DUPLICATE_EMAIL`. The full name is required and non-empty. The home airport is an IATA code of exactly three uppercase letters; a malformed code fails generic input validation. A freshly registered member starts at `BASE` tier with a `points_balance` of 0, a `qualifying_segments_ytd` of 0, both `status_match_active` and `status_match_used` false, and no recorded `last_activity_at`.

Reading a member returns the live account snapshot, including the derived `points_balance`, the earned `tier`, and the effective tier exposed as a distinct `effective_tier` field described in Section 2.7 (the member resource carries `effective_tier` alongside `tier`; the internally tracked `matched_tier` floor is not exposed in the member response). A `ProgramAdmin` may list all members, optionally filtering by `tier`, and may read any single member; a `Member` may read their own account. A member's points history is available as their `PointsLedger` rows, and their flying history as their `FlightSegment` records — both retrievable as owned sub-collections.

### 3.2. The Flight Segment Lifecycle and Points Accrual

A flight is recorded as a `FlightSegment` and progresses through a small branching lifecycle, tracked by its `status` field (and, like every entity in this system whose lifecycle this document describes, each of `AwardBooking`, `UpgradeRequest`, `CompanionCertificate`, `PointsGift`, and `StatusMatch` likewise carries a `status` field holding its current state). An `OperationsAgent` books a segment for a member, supplying the `member_id`, the `origin` and `destination` IATA codes (each exactly three uppercase letters, and the destination must differ from the origin), the `fare_class` (one of `DISCOUNT`, `ECONOMY`, `BUSINESS`, `FIRST`), the `distance_miles` (an integer of at least 1), the `base_fare_usd` (a number of at least 0), and the `scheduled_departure` instant. A newly booked segment is in state `BOOKED`. A booked segment that the member did not take may instead be cancelled, moving `BOOKED → CANCELLED`; only a pre-accrual segment may be cancelled, and because cancellation happens before any points are minted there is never a clawback. Attempting a transition from a state that does not permit it yields `ERR_INVALID_STATE`.

Once travel has happened, the agent marks the segment flown, moving `BOOKED → FLOWN`. This is only permitted once the clock has reached departure: the current instant must be at or after the segment's `scheduled_departure`. An attempt to fly a segment before that instant is rejected with `ERR_DEPARTURE_NOT_REACHED`.

Accrual is the second step and is where value is created. Marking a flown segment accrued moves `FLOWN → ACCRUED` and runs the segment-accrual calculation against the member who flew it (who must still exist). The computed points are stored on the segment as `points_awarded` and frozen there permanently for later compensation accounting, and the segment's `is_qualifying` flag is set to true exactly when the fare class is not `DISCOUNT`. Accrual then drives a three-level cascade:

1. An `ACCRUAL` ledger row is appended for the member with a positive `delta` equal to the awarded points, `source_type` `FlightSegment`, and an `expires_at` of the current instant plus the expiration window (see Section 3.6); the member's `points_balance` increases by that amount and `last_activity_at` is set to the current instant.
2. If the segment is qualifying, the member's `qualifying_segments_ytd` increases by 1, which triggers a tier recomputation.
3. That recomputation may raise the member's `tier`, which in turn raises the effective tier that will feed the priority score of any future upgrade request.

`ACCRUED` is terminal. The amount of points awarded by accrual is governed by the following rule. First, a class multiplier is selected from the fare class: `0.5` for `DISCOUNT`, `1.0` for `ECONOMY`, `1.5` for `BUSINESS`, and `2.0` for `FIRST`. A fare-based figure is the paid `base_fare_usd` multiplied by that class multiplier. Independently, a distance-based floor is computed by multiplying `distance_miles` by the minimum mile rate of `0.5` points per mile and rounding that product **up** to the next whole number. The segment's pre-bonus earning is the larger of the fare-based figure and the distance-based floor — so a cheap long-haul still earns its mile-based minimum, while an expensive short-haul earns on spend. A tier bonus percentage is then selected from the member's **effective tier at the accrual instant**: `0` for `BASE`, `25` for `SILVER`, `50` for `GOLD`, and `100` for `PLATINUM`. The final `points_awarded` is the pre-bonus earning multiplied by one plus that bonus percentage expressed as a fraction (so a 25 percent bonus multiplies by 1.25, and a 100 percent bonus doubles it), with the result rounded half-up to a whole number of points.

### 3.3. Status Match: The One-Time Accelerator

A `ProgramAdmin` may grant a member a status match against a competitor airline, supplying the `member_id`, the `rival_tier` the member holds elsewhere (one of `SILVER`, `GOLD`, `PLATINUM`), and the `valid_until` instant at which the match expires. The match is a once-in-a-lifetime benefit: if the member's `status_match_used` flag is already true, the grant is refused with `ERR_STATUS_MATCH_EXHAUSTED`. A successful grant creates a `StatusMatch` in state `GRANTED`, computes the `matched_tier` the member is floored at, sets the member's `status_match_active` to true and `status_match_used` to true, and runs a tier recomputation so the floor takes effect immediately. Granting a status match credits no points and writes no `PointsLedger` row; the benefit is purely the effective-tier floor (the `STATUS_MATCH_BONUS` reason and `StatusMatch` ledger source type enumerated in Section 2.6 are reserved and never produced by any operation in this service).

The `matched_tier` is derived one rung below the rival tier on the tier ladder `BASE < SILVER < GOLD < PLATINUM`: a `rival_tier` of `SILVER` yields a matched tier of `BASE`, `GOLD` yields `SILVER`, and `PLATINUM` yields `GOLD`. While the match is active, the member's effective tier is floored at this matched tier even if the member has flown zero qualifying segments. A status match expires through the clock sweep described in Section 3.7, after which the floor is removed.

### 3.4. Tier Recomputation and the Effective Tier

Tier is recomputed whenever the member's qualifying-segment count changes, whenever a status match is granted or expires, and during the year-end reset. The recomputation pins an explicit evaluation order to resolve what would otherwise look like a circular dependency among earned tier, the match floor, and the accrual bonus that depends on the effective tier; the effective tier used for an accruing segment's bonus is computed **before** that segment itself is counted.

The procedure is: first determine the **earned tier** as the highest tier whose qualifying-segment threshold the member has reached, comparing `qualifying_segments_ytd` against the thresholds `BASE` at 0, `SILVER` at 15, `GOLD` at 30, and `PLATINUM` at 60 — a tier is reached when the count is at least its threshold. Earned tier within a program year is a monotonic ratchet: it is set to the highest threshold met and is never lowered by a loss of segments mid-year. Second, determine the **match floor**: it is the member's `matched_tier` when `status_match_active` is true, and `BASE` otherwise. The **effective tier** is then the higher-ranked of the earned tier and the match floor, using the rank order `BASE` 0, `SILVER` 1, `GOLD` 2, `PLATINUM` 3. When there is no active match the effective tier equals the earned tier; when a match is active and its matched tier outranks the earned tier, the effective tier is lifted up to the matched tier.

### 3.5. Award Pricing, Issuance, and the Companion Certificate

An award booking lets a member spend points on travel and proceeds through the branching lifecycle `QUOTED → ISSUED → (CANCELLED | FLOWN)`, with `QUOTED` also able to go directly to `CANCELLED`. A `Member` quotes an award by supplying the `member_id`, the `route_code` (an origin-destination token such as `"SFO-NRT"`), the `cabin` (one of `ECONOMY`, `BUSINESS`, `FIRST`), the `pricing_mode` (`DYNAMIC` or `FIXED`), and, for dynamic pricing only, a `load_factor`. The quote computes and **pins** the `points_price`; this pinned price is frozen for the life of the award and is exactly what gets debited on issuance and refunded on cancellation.

The price is computed as follows. A base chart price is read for the cabin: `ECONOMY` is 25000, `BUSINESS` is 60000, and `FIRST` is 100000 points. Under `FIXED` pricing the cabin price is exactly that chart value, independent of demand. Under `DYNAMIC` pricing the cabin price scales with live demand: the chart value is multiplied by the quantity zero-point-eight plus zero-point-eight times the `load_factor`, then rounded half-up — so the multiplier ranges from 0.8 at a load factor of 0 to 1.6 at a load factor of 1, and a load factor of 0.5 yields 1.2 times the chart, diverging from the fixed price for the same route and cabin. If a companion certificate is attached, a companion add-on equal to 50 percent of the cabin price (rounded half-up) is added; otherwise the add-on is zero. The pinned `points_price` is the cabin price plus the companion add-on.

Dynamic pricing requires a `load_factor` and fixed pricing must omit it. A `DYNAMIC` quote with no `load_factor`, a `FIXED` quote that supplies one, or any `load_factor` outside the inclusive range from 0 to 1 is rejected with `ERR_LOAD_FACTOR_REQUIRED`.

A member may attach a companion certificate to the quote by supplying its `companion_certificate_id`. A companion certificate is itself issued by a `ProgramAdmin` to a `member_id` with a validity window bounded by its `valid_from` (inclusive start) and `valid_until` (inclusive end) instants, where `valid_until` must be strictly after `valid_from`. The attachment is only valid when the certificate is in state `ISSUED`, is owned by the acting member, and its validity window from `valid_from` through `valid_until` contains the award's intended travel and the current instant falls within that window; a certificate that is not `ISSUED` or whose window does not cover the travel is rejected with `ERR_CERTIFICATE_NOT_VALID`. A valid attachment moves the certificate `ISSUED → RESERVED` and records the new award's id as the certificate's `attached_award_id`, so the certificate is held against the quote.

Issuing the award (`QUOTED → ISSUED`) is owner-only and requires the member's `points_balance` to be at least the pinned `points_price`; an insufficient balance is rejected with `ERR_INSUFFICIENT_POINTS`. Issuance appends a `REDEMPTION` ledger row with a negative delta equal to the pinned price (`source_type` `AwardBooking`), lowers the member's `points_balance` by that amount, and sets `last_activity_at` to the current instant. If a certificate is attached, the certificate cascades `RESERVED → REDEEMED` as part of the same operation.

Cancellation has two compensating branches. Cancelling a still-`QUOTED` award (`QUOTED → CANCELLED`) never debited points, so no refund row is written; if a certificate was attached it is released back to `ISSUED` and its `attached_award_id` is cleared. Cancelling an already-`ISSUED` award (`ISSUED → CANCELLED`) is a true compensation: a `REDEMPTION_REFUND` ledger row is appended with a positive delta equal to exactly the previously debited `points_price`, the member's `points_balance` rises by that amount and `last_activity_at` is set to the current instant, returning the balance to its pre-issuance value; if a certificate was attached it cascades `REDEEMED → ISSUED` with its `attached_award_id` cleared so it becomes reusable. Both cancellations are owner-only. Finally, an `OperationsAgent` marks an issued award flown (`ISSUED → FLOWN`) once the clock has reached the award's travel date; `FLOWN` is terminal and the points consumption becomes permanent.

### 3.6. Points Gifting Between Members

A `Member` may gift points to another member. The gift is created in two steps so that it can be settled or backed out cleanly. Creating a gift records the `sender_id`, the `recipient_id`, and the integer `amount` (at least 1), and starts the gift in state `PENDING`. The recipient must differ from the sender; a self-gift is rejected with `ERR_GIFT_TO_SELF`. An amount below the minimum of 1 is rejected with `ERR_GIFT_AMOUNT_INVALID`.

Settling a pending gift (`PENDING → SETTLED`) is performed by the sender and carries the optimistic-concurrency field described in Section 2.9. It is permitted only when the sender's `points_balance` is at least the gift `amount`; otherwise it is rejected with `ERR_INSUFFICIENT_POINTS`. Settlement is a conserving transfer: a `GIFT_OUT` ledger row with a negative delta equal to the amount is appended on the sender, the sender's balance drops by the amount and the sender's `last_activity_at` is updated; symmetrically a `GIFT_IN` ledger row with a positive delta equal to the amount and an `expires_at` of the current instant plus the expiration window is appended on the recipient, the recipient's balance rises by the same amount and the recipient's `last_activity_at` is updated. The sender debit exactly equals the recipient credit, so total program points are conserved. Reversing a pending gift (`PENDING → REVERSED`) is also sender-only; because a pending gift moved no points, reversal writes no ledger rows. For read access, a `Member` may fetch or list a gift when they are either its sender or its recipient (not only the sender); a member who is neither party is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 3.7. The Activity Clock: Expiration, Validity, and the Year Roll

Advancing the logical clock to a new instant is a `ProgramAdmin` test-driving capability that, after setting `current_utc` and re-deriving `program_year`, runs three deferred sweeps in turn.

First is the **points expiration sweep**. For each member whose account has been inactive beyond the expiration window of 18 months — that is, the elapsed time from the member's `last_activity_at` to the current instant exceeds 18 months — the sweep expires that member's positive ledger lots whose `expires_at` is at or before the current instant. Lots are processed oldest first, ordered by `expires_at` ascending and, on ties, by `created_at` ascending. For each such lot the amount burned is the smaller of the lot's remaining points and the member's current `points_balance`; an `EXPIRY` ledger row with a negative delta equal to that burn (`source_type` `System`) is appended and the balance is reduced accordingly. Because the burn is capped at the current balance, the balance lands exactly at 0 and never goes negative even when prior spending has already reduced it below the lot size.

Second, **status-match expiration**: any `StatusMatch` in state `GRANTED` whose `valid_until` is now in the past (the current instant is strictly after `valid_until`) moves `GRANTED → EXPIRED`, sets the member's `status_match_active` to false, and triggers a tier recomputation that may drop the effective tier now that the floor is gone. Likewise, any `CompanionCertificate` still in state `ISSUED` whose `valid_until` has passed (the current instant is strictly after `valid_until`) moves `ISSUED → EXPIRED`.

Third, the **year-end run**: when the newly derived `program_year` is greater than the program year under which a member's qualifying count was accumulated, that member's `qualifying_segments_ytd` is reset to 0 and the tier is recomputed from the now-empty count — floored by any still-active status match. This is the only mechanism that can lower a member's earned tier.

Two additional `ProgramAdmin` test-driving capabilities seed scenarios directly. One credits a member's balance by a supplied `amount`, appending an `ACCRUAL` lot (`source_type` `System`) that expires at the current instant plus the expiration window, raising `points_balance`, setting `last_activity_at`, and bumping the member's version. The other sets a member's `qualifying_segments_ytd` to a supplied `count` value (which must be a non-negative integer) and runs an ordinary tier recomputation, to place a member precisely at a tier-threshold boundary; because this is an ordinary recomputation rather than the year-end run, the earned-tier monotonic ratchet still applies, so lowering the count below the member's current earned tier's threshold does not lower the earned `tier`.

### 3.8. The Upgrade Waitlist and Priority Clearing

Premium-cabin upgrades are allocated from a finite pool through a priority-ranked waitlist. An `OperationsAgent` creates a `FlightPool` for a flight by supplying its `flight_number`, its `departure_at` instant, and the `premium_capacity` — the total number of premium seats available for upgrade clearance, which must be a non-negative integer; a negative capacity is rejected with `ERR_POOL_CAPACITY_INVALID`. The pool tracks `seats_cleared` (consumed seats), `seats_remaining` (capacity minus cleared seats), and a `cleared` flag that becomes true once the clearing run has executed. The invariant that cleared plus remaining always equals capacity holds throughout.

A `Member` joins the pool's waitlist by supplying the `member_id`, the `flight_pool_id`, the `booked_fare_class` they hold, and the `expected_flightpool_version` for the optimistic-concurrency check of Section 2.9. The request is created in state `WAITLISTED` with its `requested_at` stamped by the server (this is the waitlist tie-break key) and its `priority_score` computed. Creating the waitlist request itself mutates the target pool by incrementing its `version` by one (the seat-accounting counts `seats_cleared` and `seats_remaining` are not changed at join time, only at clearing), so a subsequent joiner observing the pre-join version must supply the updated value to pass the optimistic-concurrency check. The priority score is the rank of the member's effective tier multiplied by 1000 — using the ranks `BASE` 0, `SILVER` 1, `GOLD` 2, `PLATINUM` 3 — plus a fare-class weight of `0` for `DISCOUNT`, `10` for `ECONOMY`, `20` for `BUSINESS`, and `30` for `FIRST`. Because the 1000-point tier gap exceeds the maximum fare weight of 30, a higher tier always outranks a lower tier regardless of fare. A member may withdraw their own still-waitlisted request (`WAITLISTED → WITHDRAWN`), but only while the pool has not yet been cleared.

An `OperationsAgent` runs the clearing for a pool. The run is gated twice: it may only execute when the pool has not already been cleared and only at or after the pool's `departure_at`; invoking it on an already-cleared pool, or before departure, is rejected with `ERR_POOL_ALREADY_CLEARED`. The run sorts all `WAITLISTED` requests by `priority_score` descending, then by `requested_at` ascending, then by `created_at` ascending — the record id is never consulted as a tie-break. Walking that order, each request is granted a seat (`WAITLISTED → CLEARED`) while seats remain, consuming one seat by incrementing `seats_cleared` and decrementing `seats_remaining`; once the pool is exhausted, every remaining request is denied (`WAITLISTED → DENIED`). The run then marks the pool `cleared`. Upgrade requests for a pool, and a member's own upgrade requests, are retrievable as listed sub-collections.

## 4. Endpoint Definitions

The general rule is that an endpoint creating a brand-new resource responds with HTTP 201, while reads and state-changing operations on existing resources respond with HTTP 200. Request bodies, the precise fields each endpoint accepts, and the side effects each one triggers are described in the Section 3 narratives; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/members` | Register a loyalty member | ProgramAdmin |
| GET | `/members/{id}` | Fetch a member with computed balance and tier | ProgramAdmin, Member |
| GET | `/members` | List members, optionally filtered by tier | ProgramAdmin |
| GET | `/members/{id}/ledger` | List a member's points-ledger rows | ProgramAdmin, Member |
| GET | `/members/{id}/segments` | List a member's flight segments | ProgramAdmin, Member |
| POST | `/flight-segments` | Book a flight segment for a member | OperationsAgent |
| GET | `/flight-segments/{id}` | Fetch a flight segment | ProgramAdmin, OperationsAgent, Member |
| POST | `/flight-segments/{id}/fly` | Mark a booked segment flown | OperationsAgent |
| POST | `/flight-segments/{id}/accrue` | Accrue points and qualifying credit for a flown segment | OperationsAgent |
| POST | `/flight-segments/{id}/cancel` | Cancel a booked segment | OperationsAgent |
| POST | `/award-bookings` | Quote an award booking and pin its price | Member |
| GET | `/award-bookings/{id}` | Fetch an award booking | ProgramAdmin, Member |
| GET | `/award-bookings` | List award bookings, filterable by member or attached certificate | ProgramAdmin, Member |
| POST | `/award-bookings/{id}/issue` | Issue a quoted award; debit points and redeem any certificate | Member |
| POST | `/award-bookings/{id}/cancel` | Cancel a quoted or issued award; refund and release as applicable | Member |
| POST | `/award-bookings/{id}/fly` | Mark an issued award flown | OperationsAgent |
| POST | `/flight-pools` | Create an upgrade pool with finite premium capacity | OperationsAgent |
| GET | `/flight-pools/{id}` | Fetch a flight pool with seat accounting | ProgramAdmin, OperationsAgent, Member |
| GET | `/flight-pools/{id}/upgrade-requests` | List upgrade requests for a pool | ProgramAdmin, OperationsAgent, Member |
| POST | `/upgrade-requests` | Join a pool's upgrade waitlist | Member |
| GET | `/upgrade-requests/{id}` | Fetch an upgrade request | ProgramAdmin, OperationsAgent, Member |
| GET | `/upgrade-requests` | List upgrade requests, filterable by member or pool | ProgramAdmin, OperationsAgent, Member |
| POST | `/upgrade-requests/{id}/withdraw` | Withdraw a waitlisted upgrade request | Member |
| POST | `/flight-pools/{id}/clear-waitlist` | Run priority clearing for a pool | OperationsAgent |
| POST | `/companion-certificates` | Issue a companion certificate with a validity window | ProgramAdmin |
| GET | `/companion-certificates/{id}` | Fetch a companion certificate | ProgramAdmin, Member |
| GET | `/companion-certificates` | List companion certificates, filterable by member or attached award | ProgramAdmin, Member |
| POST | `/points-gifts` | Create a pending points gift | Member |
| GET | `/points-gifts/{id}` | Fetch a points gift | ProgramAdmin, Member |
| GET | `/points-gifts` | List points gifts, filterable by sender or recipient | ProgramAdmin, Member |
| POST | `/points-gifts/{id}/settle` | Settle a pending gift (OCC-guarded on sender) | Member |
| POST | `/points-gifts/{id}/reverse` | Reverse a pending gift | Member |
| POST | `/status-matches` | Grant a one-time lifetime status match | ProgramAdmin |
| GET | `/status-matches/{id}` | Fetch a status match | ProgramAdmin, Member |
| GET | `/status-matches` | List status matches, filterable by member | ProgramAdmin, Member |
| POST | `/_clock/advance` | Set the clock and run expiry/validity/year-roll sweeps | ProgramAdmin |
| GET | `/_clock` | Read the current system clock | ProgramAdmin, OperationsAgent, Member |
| POST | `/_inject/points` | Credit a member's balance directly (test seeding) | ProgramAdmin |
| POST | `/_inject/qualifying_segments` | Set a member's qualifying-segment count directly (test seeding) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_POOL_VERSION` | 412 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
| `ERR_STATUS_MATCH_EXHAUSTED` | 409 |
| `ERR_CERTIFICATE_NOT_VALID` | 422 |
| `ERR_GIFT_TO_SELF` | 422 |
| `ERR_DEPARTURE_NOT_REACHED` | 422 |
| `ERR_LOAD_FACTOR_REQUIRED` | 422 |
| `ERR_POOL_ALREADY_CLEARED` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_VALIDATION` | 400 |
| `ERR_GIFT_AMOUNT_INVALID` | 422 |
| `ERR_POOL_CAPACITY_INVALID` | 400 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
