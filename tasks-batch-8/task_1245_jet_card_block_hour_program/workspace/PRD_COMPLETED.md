# Jet Card & Block-Hour Program API — Product Requirements Document

## 1. Introduction

Private-aviation membership programs sell blocks of flight hours up front and then reconcile those hours against actual usage, expiration, refund, and conversion events over the card's lifetime. The system described here manages the full lifecycle of a jet card: a member purchases a fixed block of hours against a specific aircraft category, draws those hours down through trip requests, and may eventually refund the unused balance or convert it into a fractional-ownership share. Because every flight debit, every expiration sweep, and every refund touches both an hour bank and a dollar-denominated escrow account, the platform must behave as a pricing engine and a ledger reconciliation system at once.

Two operator concerns shaped the design. First, hour balances and escrow balances are derived state: they must always be reconstructible from an append-only ledger, never stored as authoritative mutable counters. Second, money and hours move in lockstep but at different precisions and on different triggers — a completed trip debits hours and releases escrow proportionally, an expiration sweep forfeits escrow without touching consumed hours, and a refund releases escrow while zeroing hours. Keeping those flows consistent under concurrent writers is why refund and upgrade creation carry optimistic-concurrency fields, and why the system exposes an explicit ops-run sweep rather than relying on wall-clock side effects.

The audience for this document is the engineering team building the API. It specifies the resource model, the role and permission envelope, the pricing and ledger arithmetic, and the state machines that govern cards, trips, refunds, and invoices.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing a recognized role header — or missing the identifier header when the role requires one — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Only the `Member` role requires `X-User-ID`; `Ops` and `Anonymous` requests may omit the identifier header. A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Three roles exist:

- `Ops` — operations and administration. When `X-User-Role` is `Ops`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it against any entity's `id`. Ops has full control over programs, peak and blackout windows, members, cards, aircraft, dispatch, invoicing, refund adjudication, and the ops-run sweep.
- `Member` — a jet-card holding member. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. Members read their own cards, trips, invoices, refunds, ledger entries, and escrow, and they drive the member-facing actions: trip confirmation, trip cancellation, refund submission, invoice dispute, and creation of trips, refunds, and fractional upgrades on their own cards. On collection endpoints scoped beneath a non-member parent — a program's jet cards or an aircraft's trip requests — a `Member` caller receives only the subset of resources they own rather than an authorization error.
- `Anonymous` — unauthenticated catalog reader. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity. Anonymous callers may list and read card programs and their peak and blackout windows, and nothing else.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock rather than the logical clock of §2.10.
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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A `limit` that is not an integer or falls outside the 1–100 range, or an `offset` that is not a non-negative integer, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are always sorted by `created_at` ascending, with ties broken by insertion order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries an `id` that is a server-minted UUID rendered in its canonical dashed string form (for example `3f6b2a1c-7d4e-4f5a-9b8c-0d1e2f3a4b5c`) with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and an integer `version` that starts at 1 on creation and increments by 1 on every mutation of that resource. The single exception is `HourBankLedger`: as an append-only journal it carries only `id` and `created_at`; both `updated_at` and `version` are absent from ledger entries, because entries are never modified after insertion.

`version` is the basis of optimistic concurrency. When a mutation succeeds — including state transitions and cascaded mutations caused by another entity's transition — the owning resource's `version` increments by exactly 1 and its `updated_at` refreshes.

### 2.5. Nested Resource Retrieval

Paths that nest one resource beneath another validate their path parameters left to right. The path-parameter names used across the API are `programId`, `memberId`, `cardId`, `tripId`, `invoiceId`, `refundId`, `aircraftId`, and the generic `id` used by the FK reverse-reachability reads; each segment's identifier must resolve to an existing resource before the next segment is examined, and a child segment must actually belong to the parent named earlier in the path. A failure to resolve any path-referenced resource — program, member, card, trip, invoice, refund, or aircraft — is rejected with `ERR_NOT_FOUND` (HTTP 404). Requests to undefined paths, and requests using an unsupported method on a defined path, likewise surface as `ERR_NOT_FOUND` (HTTP 404). Identifiers supplied in the request body rather than the path (such as `program_id` when purchasing a card, or `dispatched_aircraft_id` at dispatch) are validated after path resolution and fail with `ERR_REFERENCE_NOT_FOUND` (HTTP 422) when they do not resolve.

### 2.6. Money, Hours, and Rounding Discipline

All dollar amounts are stored and transmitted as integer cents. Hours are stored as decimal quantities. Two precision regimes apply across the platform and are never mixed within a single step:

- Hour quantities — `billable_hours`, `debited_hours`, `quoted_hours`, hour balances — are rounded to 2 decimal places, round half up.
- Money quantities — invoice line items, escrow movements, refund amounts — are rounded to 0 decimal places (whole cents), round half up, applied at each arithmetic step rather than once at the end.

When a calculation chains multiple steps (for example invoice subtotal, then surcharge, then discount), each intermediate result is rounded to its regime's precision before feeding the next step.

### 2.7. Optimistic Concurrency Control on Card-Sensitive Writes

Two write endpoints are stale-version guarded because they mutate the card's hour bank and escrow based on the caller's observed balance: refund creation and fractional-upgrade creation, both of which target a specific `JetCard`. Each request must carry `expected_card_version` as a non-optional input field, holding the `version` of the `JetCard` the client last observed. If the value does not match the card's current `version` — for example because a trip completion has since debited hours and advanced the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; attempting to pass one elsewhere is treated as an unrecognized field.

### 2.8. The Hour Bank Ledger as Source of Truth

Every change to a card's usable hours is recorded as an `HourBankLedger` entry with an `entry_kind` drawn from `PURCHASE_GRANT`, `TRIP_DEBIT`, `EXPIRATION_DEBIT`, `REFUND_DEBIT`, `UPGRADE_DEBIT`, or `SWAP_ADJUSTMENT`, a signed `hours_delta` (positive for grants, negative for debits), an `effective_at` timestamp recording when the entry takes effect, and an optional free-text `note`. An entry written without an explicit effective time takes `effective_at` as the current logical time. Entries linked to a specific flight carry that trip's identifier in `trip_id`; all other entries leave `trip_id` null.

The card's `hours_remaining` is derived, never directly written: it equals the sum of `hours_delta` across all ledger entries whose `effective_at` is at or before the current logical time, replayed in `effective_at` ascending order with ties broken by `created_at` ascending. This chronological variant is the persisted balance and drives all trip authorization. A second, forward-looking variant exists for what-if display: it sums entries whose `effective_at` is at or before the earlier of the current time and the card's `expires_at`, thereby forecasting the post-expiry floor. The forward-looking variant is exposed only through the card projection read, which returns the full card object with `hours_remaining` reporting that variant; it never authorizes trips. Both variants are expressed to 2 decimal places.

### 2.9. Escrow Custody of Unused Funds

At card activation the full purchase price is placed into an `EscrowAccount` whose `principal_cents` equals the program's `purchase_price_cents`. From that moment the escrow account — not the card — is the custodian of unused funds. Its `available_cents` decreases on three events: proportional release when a trip completes, payout when a refund settles, and forfeiture when the expiration sweep runs. `released_cents` accumulates funds paid back to the operator or member (consumed hours and refunds paid), while `forfeited_cents` accumulates value lapsed through expiration. The card's `escrow_balance_cents` always mirrors the escrow account's `available_cents`; it is a read-through projection, not an independent balance.

### 2.10. The Logical Clock and Ops-Run Sweeps

The server maintains a logical clock, initialized to 2026-05-01T00:00:00Z. All deadline, expiry, and window rules — expiration, SLA windows, peak windows, blackout windows, refund penalty anniversaries — evaluate against this logical clock, not wall time. An admin-only test-driving capability advances the clock to a supplied `to_iso8601` instant; every subsequent read of "now" uses that value. Time only moves forward through this capability: a request targeting an earlier instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400), re-setting the current instant is permitted, and the response carries the new `current_utc`.

Expiration and closure are not lazy: they are applied by an ops-run sweep that an `Ops` operator invokes explicitly. The sweep examines every card, transitions those past their `expires_at` into `EXPIRED` or `CLOSED` as their balances dictate, and writes the corresponding ledger entries. The sweep responds with an object carrying `expired_card_ids`, `closed_card_ids`, `expired_count`, `closed_count`, and `current_utc`. Because hour balances are derived from ledger entries, a card with hours still remaining cannot transition to `EXPIRED` until the sweep has inserted the offsetting expiration debit; an attempt to force the transition without the debit is rejected with `ERR_EXPIRATION_SWEEP_INCOMPLETE` (HTTP 409).

### 2.11. Validation Ordering

When several guards apply to one endpoint, they are evaluated in a fixed priority order so the surfaced error is deterministic. Authentication comes first (missing or malformed headers yield `ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then path-existence (`ERR_NOT_FOUND`), then body-reference existence (`ERR_REFERENCE_NOT_FOUND`). Only after all four pass do state guards run — card-active (`ERR_CARD_NOT_ACTIVE`), member-active (`ERR_MEMBER_NOT_ACTIVE`), and from-state validity (`ERR_INVALID_STATE`) — followed by business guards in their own order: open-trips (`ERR_OPEN_TRIPS_EXIST`), blackout intersection (`ERR_BLACKOUT_PERIOD`), SLA window (`ERR_SLA_WINDOW_MISSED`), aircraft availability (`ERR_NO_AIRCRAFT_AVAILABLE`), passenger capacity (`ERR_PAX_EXCEEDS_CAPACITY`), hour sufficiency (`ERR_INSUFFICIENT_HOURS` and `ERR_INSUFFICIENT_HOURS_FOR_UPGRADE`), stale version (`ERR_STALE_VERSION`), return-time validity (`ERR_INVALID_RETURN_TIME`), sweep completeness (`ERR_EXPIRATION_SWEEP_INCOMPLETE`), and finally refund non-emptiness (`ERR_NOTHING_TO_REFUND`). A malformed payload that fails schema validation — including a body containing any unrecognized field — surfaces as `ERR_INVALID_REQUEST` (HTTP 400) before any of the above.

## 3. Business Logic & Workflows

### 3.1. Program Setup and the Pricing Parameters Every Card Inherits

An `Ops` operator onboards the product catalog by creating a `CardProgram`. The program's `program_code` is the human-facing unique identifier (for example `WHEELS_UP_25H`) — a duplicate `program_code` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and `aircraft_category` pins the program to one of `LIGHT`, `MIDSIZE`, `SUPER_MID`, or `HEAVY` (tiers rank in that order, lowest to highest, for swap-direction purposes). The commercial terms are fixed at program creation: `hours_purchased` sets the block size on the card face (typically 25, 50, or 100), `purchase_price_cents` is the upfront price, and `expiry_months` defines how long unused hours survive (typically 18 to 24 months).

The same creation call carries the operational constants that later drive billing arithmetic: `taxi_minutes_per_leg` is the fixed taxi-time billed on every leg, and `min_billable_minutes_per_leg` is the floor below which no leg's billable time may fall. Pricing levers arrive on the same payload — `peak_surcharge_pct` is the multiplier applied on top of the subtotal when a trip departs inside a peak window, `round_trip_discount_pct` is the discount granted when a trip qualifies as round-trip, and `early_termination_penalty_pct` governs refund haircuts inside the first year. Category flexibility is expressed through `swap_ratio_to_lower` (a multiplier below 1.0 — a member swapped down a category is debited fewer hours than flown) and `swap_ratio_to_higher` (a multiplier above 1.0 — a member swapped up is debited more). The `availability_window_hours` constant is the program's service-level guarantee: dispatch must occur within that many hours of the requested departure. Finally `fractional_upgrade_ratio` sets the conversion rate from card hours into a fractional share.

Programs are publicly readable — `Anonymous` callers browse the catalog — and two kinds of calendar windows hang off each program. A `PeakCalendar` window is defined by `window_start_utc` (inclusive) and `window_end_utc` (exclusive) plus a human `label` such as "Thanksgiving 2026"; any trip whose `requested_departure_utc` falls inside the window is peak-period. A `BlackoutWindow` carries the same start and end fields plus `applies_to_category` — one of `LIGHT`, `MIDSIZE`, `SUPER_MID`, `HEAVY` — and a free-text `reason`; a blackout only blocks trips requested in that specific category. Both window kinds are created by `Ops` and are listable with the standard pagination parameters, with blackout listings optionally filtered by `applies_to_category`.

### 3.2. Membership and Fleet Registration

Members are registered by `Ops` with an `email` (unique across the platform — a duplicate email is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), a `full_name`, a `tier` of `INDIVIDUAL`, `FAMILY`, or `CORPORATE`, and a `home_base_icao` identifying the member's home airport. A new member starts with `member_status` set to `ACTIVE`. Suspension moves a member to `SUSPENDED` and carries no from-state guard; the terminal state `TERMINATED` exists in the enumeration for lifecycle completeness. Card purchase and trip confirmation both require the member to be `ACTIVE` — a suspended member is rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409) on either operation.

Aircraft registration, also `Ops`-only, captures the `tail_number` (unique — a duplicate tail number is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), the aircraft's `category` from the same four-value enumeration, its `home_base_icao`, its passenger `seats`, and a `reposition_rate_cents_per_nm` used when pricing one-way positioning. A newly registered aircraft starts with `aircraft_status` set to `AVAILABLE`; the other fleet states are `IN_SERVICE`, `MAINTENANCE`, and `GROUNDED`. Only `AVAILABLE` aircraft are dispatch-eligible, and only `Ops` may list the fleet (with optional `category` and `aircraft_status` filters), though both `Ops` and `Member` may read an individual aircraft.

### 3.3. Card Purchase, Activation, and the Birth of Two Balances

A card purchase begins when an `Ops` operator creates a `JetCard` under a member, supplying the `program_id` of the chosen program. The member must be `ACTIVE` at this point. The card is born in `PENDING_PAYMENT` status with its `member_id` bound to the purchasing member and `hours_total` mirroring the program's `hours_purchased`; until activation, `purchased_at` and `expires_at` are null and `hours_remaining`, `hours_consumed`, `hours_expired`, `peak_hours_used`, and `escrow_balance_cents` are all zero.

Activation is the pivotal event. When `Ops` activates the card — which requires only that the referenced program still exists — the card moves from `PENDING_PAYMENT` to `ACTIVE`, `purchased_at` is stamped with the current logical time, and `expires_at` is computed as `purchased_at` plus the program's `expiry_months` (calendar-month addition, clamping the day to the length of the target month). Three financial structures come into existence in the same transaction: a `PURCHASE_GRANT` ledger entry crediting the full `hours_total`, an `EscrowAccount` whose `principal_cents` equals the program's `purchase_price_cents` with `available_cents` equal to the principal and both `released_cents` and `forfeited_cents` at zero, and the card's computed fields initialize — `hours_remaining` equals `hours_total`, `hours_consumed` and `hours_expired` and `peak_hours_used` all start at zero, and `escrow_balance_cents` mirrors the escrow's available funds. The card's `version` increments with the activation.

Suspension and resume are lightweight `Ops` actions that move the card between `ACTIVE` and `SUSPENDED`. A suspended card blocks new trip creation — any attempt is rejected with `ERR_CARD_NOT_ACTIVE` (HTTP 409) — but trips already in `CONFIRMED` status remain dispatchable. Every transition increments the card's `version`.

Both `Ops` and the owning `Member` can read a card, list a member's cards (optionally filtered by `card_status`), and page through the card's ledger entries with an optional `entry_kind` filter.

### 3.4. Quoting a Trip: One-Way, Round-Trip, and the Peak Flag

Trip creation is available to both the owning `Member` and `Ops`, acting on an `ACTIVE` card. The request payload names the `trip_kind` (`ONE_WAY` or `ROUND_TRIP`), the `departure_icao` and `arrival_icao` airport codes, the `requested_departure_utc` timestamp, a `pax_count`, and the `requested_category`. Round-trip requests additionally carry `requested_return_utc`, which must be strictly after `requested_departure_utc`; a round-trip request omitting `requested_return_utc` fails schema validation with `ERR_INVALID_REQUEST` (HTTP 400), and a return time at or before the outbound departure is rejected with `ERR_INVALID_RETURN_TIME` (HTTP 422). One-way requests leave `requested_return_utc` null — any value supplied on a one-way request is discarded.

Creation computes two derived fields immediately. `is_peak_period` is true exactly when `requested_departure_utc` falls inside one of the program's `PeakCalendar` windows (start inclusive, end exclusive). `quoted_hours` is the forward estimate used for authorization: for each leg, the server estimates the flight time as the great-circle distance between the ICAO pair divided by an assumed cruise of 400 knots (airport coordinates come from a fixed lookup table, with a deterministic fallback for unlisted codes), adds the program's taxi time expressed in hours, and rounds the sum half-up to 2 decimal places. This per-leg estimate is then floored at the program's minimum billable time per leg converted to hours and rounded half-up to 2 decimal places. A one-way trip's `quoted_hours` is that floored per-leg value; a round-trip's is twice it.

The new trip lands in `QUOTE` status with `trip_status` set accordingly, `denial_reason` null, and `dispatched_aircraft_id` null. The trip's `card_id` binds it to the paying card. Trip listings for a card can be filtered by `trip_status`.

### 3.5. Confirmation: Where Quotes Become Commitments or Denials

Confirmation is a member-only action on a trip in `QUOTE`; confirming a trip in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) and leaves the trip unchanged — the denial cascade described below applies only to a confirmation attempted from `QUOTE`. Four preconditions stand between `QUOTE` and `CONFIRMED`, and they interact with the global validation order such that state and temporal guards surface before fiscal ones: the card must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), the member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the requested departure must not intersect any `BlackoutWindow` whose `applies_to_category` matches the trip's `requested_category` (`ERR_BLACKOUT_PERIOD`, HTTP 422), and the card's `hours_remaining` must be at least the trip's `quoted_hours` (`ERR_INSUFFICIENT_HOURS`, HTTP 402).

When every precondition holds, the trip transitions to `CONFIRMED` and its `version` increments. When any precondition fails, the trip does not simply error out — it transitions from `QUOTE` to `DENIED`, with `denial_reason` set to the class of the failed check: `INSUFFICIENT_HOURS`, `BLACKOUT`, `AVAILABILITY_WINDOW`, or `PEAK_RESTRICTED`. The four preconditions map onto those classes as follows: a card that is not `ACTIVE` denies the trip with `AVAILABILITY_WINDOW`, a member that is not `ACTIVE` denies it with `PEAK_RESTRICTED`, a blackout intersection denies it with `BLACKOUT`, and insufficient hours deny it with `INSUFFICIENT_HOURS`. A denied trip is terminal. A member may also abandon a quote outright: cancellation from either `QUOTE` or `CONFIRMED` moves the trip to `CANCELED` with no financial side effects.

### 3.6. Dispatch: Aircraft Selection Under the Availability Guarantee

Dispatch is an `Ops` action on a `CONFIRMED` trip, carrying the chosen `dispatched_aircraft_id` in the request body. Two guards apply. The temporal guard requires dispatch to occur no later than the program's `availability_window_hours` after `requested_departure_utc` — dispatch at or before the requested departure always satisfies it; missing the window rejects with `ERR_SLA_WINDOW_MISSED` (HTTP 422). The fleet guard requires the chosen aircraft to be in `AVAILABLE` status; a chosen aircraft in any other status rejects with `ERR_NO_AIRCRAFT_AVAILABLE` (HTTP 422). Category compatibility is not enforced at dispatch: any `AVAILABLE` aircraft may be dispatched, and a difference between its category and the trip's `requested_category` is simply recorded through `swap_applied`. A third check compares `pax_count` against the chosen aircraft's `seats`; when the passenger count exceeds the seat count the dispatch is rejected with `ERR_PAX_EXCEEDS_CAPACITY` (HTTP 422).

The operator selects the dispatch aircraft explicitly through `dispatched_aircraft_id`; the server performs no candidate ranking or eligibility filtering beyond the guards above. The aircraft's `reposition_rate_cents_per_nm` is recorded at registration but enters no billing computation in the current API.

Successful dispatch moves the trip from `CONFIRMED` to `DISPATCHED` and fans out several effects: the chosen aircraft transitions from `AVAILABLE` to `IN_SERVICE`; `sla_met` records whether dispatch occurred within the availability window of the requested departure; `swap_applied` records whether the dispatched aircraft's category differs from `requested_category`; and the trip's `TripLeg` records come into existence in `PLANNED` status — one leg (`leg_seq` 1, outbound) for a one-way trip, two legs (`leg_seq` 1 outbound, `leg_seq` 2 return) for a round-trip. Each leg carries its own `departure_icao`, `arrival_icao`, and `scheduled_departure_utc`, and its `actual_block_minutes` remains null until completion. The trip's `version` increments.

From `DISPATCHED`, an `Ops` operator may mark departure, moving the trip to `IN_FLIGHT`. Two terminal off-ramps also exist at this stage. An `Ops` cancellation of a dispatched trip moves it to `CANCELED`, returns the aircraft to `AVAILABLE`, and marks every leg `CANCELED`. A `Member` attempting to cancel a dispatched trip is rejected with `ERR_UNAUTHORIZED` (HTTP 403), and cancellation from any status other than `QUOTE`, `CONFIRMED`, or `DISPATCHED` is rejected with `ERR_INVALID_STATE` (HTTP 409). A no-show declaration — also `Ops`-only — moves the trip to `NO_SHOW`, bills the minimum trip as a `TRIP_DEBIT` ledger entry equal to the program's minimum billable time per leg converted to hours and multiplied by the swap multiplier implied by the dispatched aircraft's category (a single per-leg minimum, independent of `trip_kind`), returns the aircraft to `AVAILABLE`, and cancels all legs.

### 3.7. Completion: Per-Leg Billing, the Hour Debit, and the Escrow Release

Completion is the system's accounting core. An `Ops` operator completes an `IN_FLIGHT` trip by supplying the `legs` payload — one entry per leg, each entry identifying its leg by `leg_seq` (the leg's `id` is accepted as an alternative key) and carrying that leg's `actual_block_minutes` as a non-negative integer; every leg must report its actual block time or the completion is rejected. Unrecognized entry fields, leg entries that do not match this trip, duplicate leg entries, incomplete leg coverage, and negative or non-integer block times are all rejected with `ERR_INVALID_REQUEST` (HTTP 400). The trip then moves to `COMPLETED` and a chain of calculations runs per leg.

First, per-leg billable time. The raw minutes for a leg are its `actual_block_minutes` plus the program's `taxi_minutes_per_leg`. The leg's `billable_minutes` is that raw figure floored at the program's `min_billable_minutes_per_leg` — a leg whose block-plus-taxi falls short of the floor bills at the floor. `billable_hours` is `billable_minutes` divided by 60, rounded half-up to 2 decimal places.

Second, the swap adjustment. The leg's `swap_multiplier` depends on how the dispatched aircraft's category compares to the trip's `requested_category`. When they match, the multiplier is 1.0 and the member is debited exactly the billable hours. When the dispatched category is a lower tier than requested — a downgrade swap — the multiplier is the program's `swap_ratio_to_lower`, which is below 1.0, so the member is debited fewer hours than flown. When the dispatched category is a higher tier — an upgrade swap — the multiplier is `swap_ratio_to_higher`, above 1.0, and the member is debited more hours. Each leg's `debited_hours` is its `billable_hours` times its `swap_multiplier`, rounded half-up to 2 decimal places.

Third, aggregation and debit. The trip's `final_hours` is the sum of its legs' `debited_hours`. A `TRIP_DEBIT` ledger entry is inserted for negative `final_hours` with the trip recorded in `trip_id`. The card's `hours_consumed` increases by `final_hours` and `hours_remaining` decreases by the same amount; when the trip's `is_peak_period` flag is true, `peak_hours_used` also increases by `final_hours` to support surcharge auditing.

Fourth, the escrow release. The released amount is the proportion of the escrow principal corresponding to the hours just consumed: `final_hours` divided by the card's `hours_total`, multiplied by `principal_cents`, rounded half-up to whole cents. The escrow's `available_cents` decreases by that amount and `released_cents` increases by it; the card's `escrow_balance_cents` follows the available balance down.

Finally, cleanup and invoicing. The aircraft returns from `IN_SERVICE` to `AVAILABLE`, every leg's `leg_status` moves from `PLANNED` to `FLOWN`, and an `Invoice` is created for the trip (§3.8). The trip's `version` increments with the completion.

### 3.8. The Invoice: Subtotal, Peak Surcharge, Round-Trip Discount

Invoice arithmetic runs at completion and produces four money fields, each rounded half-up to whole cents at the step where it is computed. The implied hourly rate of the program is its `purchase_price_cents` divided by its `hours_purchased`. The invoice's `subtotal_cents` is the sum of the trip's per-leg `debited_hours` multiplied by that implied rate, rounded to whole cents.

The peak surcharge is next: when the trip's `is_peak_period` is true, `peak_surcharge_cents` is the subtotal multiplied by the program's `peak_surcharge_pct`, rounded to whole cents; off-peak trips carry a surcharge of zero. The round-trip discount then applies to the combined base: when `trip_kind` is `ROUND_TRIP`, `round_trip_discount_cents` is the sum of `subtotal_cents` and `peak_surcharge_cents`, multiplied by `round_trip_discount_pct`, rounded to whole cents; one-way trips carry a discount of zero. The invoice's `total_cents` is the subtotal plus the surcharge minus the discount.

The four combinations behave as a reader would expect: an off-peak one-way trip bills exactly its subtotal; a peak one-way bills subtotal plus surcharge; an off-peak round-trip bills the subtotal reduced by the discount percentage; a peak round-trip bills subtotal plus surcharge, then reduced by the discount percentage applied to that combined figure.

An invoice is born with `invoice_status` set to `DRAFT` and is immediately issued by the completion cascade — the transition to `ISSUED` stamps `issued_at` with the current time and increments the invoice's `version`. Its `trip_id` binds it to the billed trip; the relationship is one-to-one, and reading a trip's invoice returns an array of zero or one element. From `ISSUED`, two member- and ops-facing paths exist: the member may dispute the invoice, moving it to `DISPUTED`; an `Ops` operator may mark it paid — from either `ISSUED` or `DISPUTED` — moving it to `PAID`, or write it off from either of those states, moving it to `WRITTEN_OFF`. Every transition increments the invoice's `version`.

### 3.9. Expiration and Closure: The Sweep Reclaims Unused Value

Cards do not expire lazily on read; an `Ops`-invoked sweep advances them. When the sweep finds an `ACTIVE` card whose `expires_at` is at or before the current logical time, the card's balance decides its fate. A card whose `hours_remaining` is still positive transitions to `EXPIRED`: an `EXPIRATION_DEBIT` ledger entry is inserted for the negative of the remaining hours with its `effective_at` stamped at the card's `expires_at` — the moment the hours lapse — rather than at the time the sweep runs, the escrow's `forfeited_cents` increases by the full `escrow_balance_cents` while `available_cents` drops to zero, and the card's `hours_expired` reflects the lapsed quantity. A card whose `hours_remaining` has already reached zero transitions to `CLOSED` with no ledger or escrow movement. In both cases the card's `version` increments, and the owning member's `member_status` is deliberately untouched — a member may hold other cards.

Because the hour balance is ledger-derived, the expiration transition and the expiration debit are inseparable: the sweep writes the debit as part of the transition, and any attempt to force a card with a positive balance into `EXPIRED` without that debit is rejected with `ERR_EXPIRATION_SWEEP_INCOMPLETE`.

### 3.10. Refunds: Snapshot, Penalty, Adjudication, Settlement

A refund begins when the owning `Member` or an `Ops` operator creates a `Refund` against a card. This is one of the two OCC-guarded writes: the request must carry `expected_card_version` matching the card's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). The created refund starts in `DRAFT` with its `card_id` bound to the card, and the card's `version` increments as part of the creation.

Submission is a member-only action from `DRAFT` and carries the real arithmetic. Two preconditions guard it, evaluated in the global order: the card must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), and the card must have no trip in `CONFIRMED`, `DISPATCHED`, or `IN_FLIGHT` status (`ERR_OPEN_TRIPS_EXIST`, HTTP 409). A further fiscal guard refuses to refund an empty card: if the computed gross amount is not positive, submission is rejected with `ERR_NOTHING_TO_REFUND` (HTTP 422).

On submission the refund snapshots `hours_at_request` from the card's current `hours_remaining` and stamps `requested_at`. The gross amount is the escrow principal prorated by the snapshot: `hours_at_request` divided by `hours_total`, multiplied by `principal_cents`, rounded half-up to whole cents, stored as `gross_refund_cents`. The early-termination penalty is tiered on the card's age: when submission occurs before the first anniversary of `purchased_at` — within twelve months — `penalty_cents` is the gross amount multiplied by the program's `early_termination_penalty_pct`, rounded half-up to whole cents; on or after the anniversary the penalty is zero. `net_refund_cents` is the gross minus the penalty, floored at zero. The refund transitions to `SUBMITTED` and its `version` increments.

Adjudication is `Ops`-only. Approval moves the refund from `SUBMITTED` to `APPROVED`. Denial moves it from `SUBMITTED` to `DENIED`, recording the operator-supplied `denial_reason`; `DENIED` is terminal. Settlement is the money-moving step: settling an `APPROVED` refund cascades the card from `ACTIVE` to `REFUNDED`, inserts a `REFUND_DEBIT` ledger entry for the negative of `hours_at_request`, reduces the escrow's `available_cents` by `net_refund_cents` while `released_cents` increases by the same amount, and reduces the card's `hours_remaining` by `hours_at_request`. `SETTLED` is terminal, and the refunded card's terminal `REFUNDED` status closes out its lifecycle. Refund listings for a card may be filtered by `refund_status`.

### 3.11. Fractional Upgrade: Converting Hours into a Share

The second OCC-guarded write converts a card's remaining hours into a fractional-ownership share. The owning `Member` or an `Ops` operator creates a `FractionalUpgrade` against an `ACTIVE` card, carrying `expected_card_version`; a mismatch with the card's current `version` rejects with `ERR_STALE_VERSION` (HTTP 412).

The conversion math values the remaining hours at the program's implied hourly rate — `purchase_price_cents` divided by `hours_purchased` — giving a conversion value of `hours_remaining` times that rate, rounded half-up to whole cents; this value is computed at creation solely to test the threshold below and is not persisted on the resource. The cost of one share unit is the program's `fractional_upgrade_ratio` multiplied by its `purchase_price_cents`. The platform's minimum conversion unit is one-sixteenth of a share: when the conversion value reaches at least one-sixteenth of the share cost, the upgrade proceeds with `share_fraction` recorded as the string `1/16` and `hours_converted` equal to the card's full `hours_remaining`; below that threshold the request is rejected with `ERR_INSUFFICIENT_HOURS_FOR_UPGRADE` (HTTP 402).

A successful creation inserts an `UPGRADE_DEBIT` ledger entry draining the converted hours, increments the card's `version`, and lands the `FractionalUpgrade` in `PENDING` status with `upgrade_status` reflecting that state and `applied_at` null. No API action applies or cancels an upgrade: the upgrade remains in `PENDING`, and `APPLIED` and `CANCELED` exist in the enumeration for lifecycle completeness. Upgrades for a card are listable with standard pagination.

## 4. Endpoint Definitions

All endpoints are served from the API root. Endpoints that create a new resource return 201 on success; endpoints that modify an existing resource or perform an action return 200. Action endpoints that define no request schema accept no request body; a non-empty body on such an endpoint is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Error responses carry the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /programs | Create a CardProgram | Ops |
| GET | /programs/{programId} | Get a CardProgram | Ops, Member, Anonymous |
| GET | /programs | List CardPrograms (optional `aircraft_category` filter) | Ops, Member, Anonymous |
| POST | /programs/{programId}/peak_windows | Add a PeakCalendar window | Ops |
| GET | /programs/{programId}/peak_windows | List PeakCalendar windows for a program | Ops, Member, Anonymous |
| POST | /programs/{programId}/blackout_windows | Add a BlackoutWindow | Ops |
| GET | /programs/{programId}/blackout_windows | List BlackoutWindows (optional `applies_to_category` filter) | Ops, Member, Anonymous |
| POST | /members | Register a Member | Ops |
| GET | /members/{memberId} | Get a Member | Ops, Member |
| POST | /members/{memberId}/suspend | Suspend a Member | Ops |
| POST | /members/{memberId}/cards | Purchase a JetCard (starts in PENDING_PAYMENT) | Ops |
| POST | /cards/{cardId}/activate | Activate card (payment cleared) | Ops |
| POST | /cards/{cardId}/suspend | Suspend a card | Ops |
| POST | /cards/{cardId}/resume | Resume a suspended card | Ops |
| GET | /cards/{cardId} | Get card details | Ops, Member |
| GET | /members/{memberId}/cards | List a member's cards (optional `card_status` filter) | Ops, Member |
| GET | /cards/{cardId}/projection | Forward-looking `hours_remaining` projection including future expirations | Ops, Member |
| GET | /cards/{cardId}/ledger | List HourBankLedger entries (optional `entry_kind` filter) | Ops, Member |
| GET | /members/{id}/jet_cards | List JetCards for a Member | Ops, Member |
| GET | /programs/{id}/jet_cards | List JetCards for a CardProgram | Ops, Member |
| GET | /cards/{id}/hour_bank_ledger | List HourBankLedger entries for a card | Ops, Member |
| GET | /trips/{id}/hour_bank_ledger | List HourBankLedger entries for a trip | Ops, Member |
| GET | /cards/{id}/trip_requests | List TripRequests for a card | Ops, Member |
| GET | /aircraft/{id}/trip_requests | List TripRequests dispatched to an aircraft | Ops, Member |
| GET | /trips/{id}/trip_legs | List TripLegs for a trip | Ops, Member |
| GET | /trips/{id}/invoices | List Invoices for a trip | Ops, Member |
| GET | /programs/{id}/peak_calendars | List PeakCalendar windows for a program | Ops, Member |
| GET | /programs/{id}/blackout_windows_fk | List BlackoutWindows for a program | Ops, Member |
| GET | /cards/{id}/escrow_accounts | List EscrowAccount for a card | Ops, Member |
| GET | /cards/{id}/refunds_fk | List Refunds for a card | Ops, Member |
| GET | /cards/{id}/fractional_upgrades_fk | List FractionalUpgrades for a card | Ops, Member |
| POST | /aircraft | Register an Aircraft | Ops |
| GET | /aircraft/{aircraftId} | Get Aircraft | Ops, Member |
| GET | /aircraft | List Aircraft (optional `category`, `aircraft_status` filters) | Ops |
| POST | /cards/{cardId}/trips | Create a TripRequest (QUOTE state) | Member, Ops |
| GET | /trips/{tripId} | Get TripRequest | Ops, Member |
| GET | /cards/{cardId}/trips | List trips for a card (optional `trip_status` filter) | Ops, Member |
| POST | /trips/{tripId}/confirm | Confirm a quoted trip | Member |
| POST | /trips/{tripId}/dispatch | Dispatch an aircraft to a confirmed trip | Ops |
| POST | /trips/{tripId}/depart | Mark trip as departed | Ops |
| POST | /trips/{tripId}/complete | Complete a trip with per-leg actual block minutes | Ops |
| POST | /trips/{tripId}/cancel | Cancel a trip | Member, Ops |
| POST | /trips/{tripId}/no_show | Mark dispatched trip as no-show (bills minimum) | Ops |
| GET | /trips/{tripId}/legs | List legs of a trip | Ops, Member |
| GET | /trips/{tripId}/invoice | Get the invoice for a trip (array of 0 or 1) | Ops, Member |
| POST | /invoices/{invoiceId}/mark_paid | Mark invoice as paid | Ops |
| POST | /invoices/{invoiceId}/dispute | Dispute an invoice | Member |
| POST | /invoices/{invoiceId}/write_off | Write off an invoice | Ops |
| POST | /cards/{cardId}/refunds | Create a Refund (DRAFT) | Member, Ops |
| GET | /cards/{cardId}/refunds | List refunds for a card (optional `refund_status` filter) | Ops, Member |
| POST | /refunds/{refundId}/submit | Submit a refund for review | Member |
| POST | /refunds/{refundId}/approve | Approve a submitted refund | Ops |
| POST | /refunds/{refundId}/deny | Deny a refund | Ops |
| POST | /refunds/{refundId}/settle | Settle an approved refund | Ops |
| POST | /cards/{cardId}/fractional_upgrades | Convert remaining card hours to fractional share | Member, Ops |
| GET | /cards/{cardId}/fractional_upgrades | List fractional upgrades for a card | Ops, Member |
| GET | /cards/{cardId}/escrow | Get escrow account for a card (array of 0 or 1) | Ops, Member |
| POST | /ops/run | Advance ops epoch: expiration sweep, posture recalculation | Ops |
| POST | /_clock/set_current_utc | Set the logical clock | Ops |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_CARD_NOT_ACTIVE | 409 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_OPEN_TRIPS_EXIST | 409 |
| ERR_BLACKOUT_PERIOD | 422 |
| ERR_SLA_WINDOW_MISSED | 422 |
| ERR_NO_AIRCRAFT_AVAILABLE | 422 |
| ERR_PAX_EXCEEDS_CAPACITY | 422 |
| ERR_INSUFFICIENT_HOURS | 402 |
| ERR_INSUFFICIENT_HOURS_FOR_UPGRADE | 402 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_RETURN_TIME | 422 |
| ERR_EXPIRATION_SWEEP_INCOMPLETE | 409 |
| ERR_NOTHING_TO_REFUND | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INTERNAL | 500 |
