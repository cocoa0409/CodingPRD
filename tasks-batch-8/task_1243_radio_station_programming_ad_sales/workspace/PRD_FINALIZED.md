# Radio Station Ad Sales API — Product Requirements Document

## 1. Introduction

A market cluster operating multiple radio stations runs on a delicate daily choreography: programmers build hour-by-hour format clocks and rotation categories that determine what songs and how many commercials air each hour; the sales organization sells that commercial inventory against a published rate card whose pricing tightens or loosens with the latest ratings book; traffic directors assemble the daily broadcast log, lock it against a pinned clock, and reconcile what actually aired against what was scheduled; billing then issues affidavits, settles make-goods for preempted or missed spots, and accounts for barter and trade deals whose value drifts from cash parity. This document specifies a single API that orchestrates all of it — programming constructs (format clocks, music categories, songs, syndication clearances), commercial inventory (rate card entries, orders, spots, live reads, barter avails, remote-event sponsorships), financial instruments (trade agreements and their append-only ledger), and the daily log lifecycle from draft through affidavit issuance.

The design deliberately separates concerns across five operator roles so that no one person can both sell an order and approve it, or both reconcile a log and issue its affidavit. It also recognizes that broadcast time is perishable and contested: high-demand hours require a demand-sensitive pricing engine, premium advertisers require the ability to preempt lesser buyers, and missed or preempted units must spawn tracked make-good obligations rather than silently disappearing. Underlying everything is a logical clock the operators can set for testing and replay, against which all flight windows, effective ranges, and "is this date in the future" checks are evaluated.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API is authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting operator and `X-User-Role` declares their capacity. The system recognizes five roles, spelled exactly: `ProgramDirector`, `TrafficDirector`, `SalesRep`, `SalesManager`, and `BillingAdmin`. A request missing either header, or carrying a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not authorized for the target operation is rejected with `ERR_ROLE_FORBIDDEN`.

All five roles share an **opaque identity model**: `X-User-ID` is an opaque operator identifier not tied to any persisted entity for any of `ProgramDirector`, `TrafficDirector`, `SalesRep`, `SalesManager`, or `BillingAdmin`. The server records `X-User-ID` on resources where the workflow stamps it — for example `created_by_user_id` on an Order, `reconciled_by_user_id` and `affidavit_issued_by_user_id` on a DailyLog, and `resolved_by_user_id` on a Discrepancy — but it never compares the header value to any entity's `id`. Ownership checks instead compare the recorded stamp: submitting or cancelling one's own Order compares the caller's `X-User-ID` to `created_by_user_id`, and segregation-of-duties checks (approver versus creator, affidavit issuer versus reconciler) compare the two stamped user identifiers.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter specifies the maximum number of items returned and defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, list endpoints sort by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` inside the response's `meta` object.

### 2.4. The Logical Clock

The server maintains a single logical clock value that governs every time-dependent business decision: order and contract activation windows, flight bounds, clearance effective ranges, the "future-only" check on barter avail cancellation during disaffirm, and order-completion timing. At server startup this clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A test-driving capability, callable by any of the five roles, advances the logical clock by setting it to a supplied `to_iso8601` instant. Setting the clock does not eagerly re-evaluate anything; instead, subsequent validations read the new value lazily.

### 2.5. Common Resource Properties

All primary entities — Station, FormatClock, MusicCategory, Song, RatingsBook, RateCardEntry, SyndicationClearance, TradeAgreement, Order, DailyLog, Spot, BarterAvail, EndorsementContract, LiveRead, Discrepancy, and RemoteEvent — carry a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix, rendered in the canonical dashed 8-4-4-4-12 hexadecimal form (for example, `550e8400-e29b-41d4-a716-446655440000`). `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is a system-managed integer incremented on every mutation, used for optimistic concurrency control. Most lifecycle-bearing entities also carry a `status` field holding the entity's current state-machine state (DailyLog uses the synonymously-behaved `posture` field; the two names are not interchangeable). Any change to derived fields (for example, recomputed `units_scheduled` on an Order, recomputed `available_cents` on a TradeAgreement, or a bumped spot-pool occupancy counter on a DailyLog) is a mutation that refreshes `updated_at` and increments `version`.

One entity deviates: TradeLedgerEntry is an append-only event log and carries only `id` and `created_at`. Both `updated_at` and `version` are absent on TradeLedgerEntry because entries are never mutated after being appended.

### 2.6. Monetary Values, Rates, and Rounding

All monetary amounts in the system are integer cents. Where a calculation must round — specifically the spot unit rate, trade valuations, affidavit per-line amounts — the system applies round-half-up to integer cents, applied exactly once at the step the formula specifies. The unit-rate calculation multiplies a base rate by three decimal multipliers and rounds the final product half-up to integer cents. Trade valuation rounds the cash-equivalent-to-trade-dollars conversion half-up to integer cents. Affidavit billing rounds each spot line half-up first, then sums. No intermediate rounding is permitted inside a formula.

### 2.7. Optimistic Concurrency Control

Three write endpoints guard against stale views of a parent aggregate by requiring a non-optional expected-version field; the check is evaluated before any from-state rules so a stale write never silently re-validates against a changed parent.

Booking a spot requires `expected_order_version` matching the target Order's current `version`. Locking a log requires `expected_log_version` matching the target DailyLog's current `version`. Scheduling a barter avail requires `expected_clearance_version` matching the target SyndicationClearance's current `version`. In each case, a mismatch — which signals that another writer has mutated the parent since the client last read it (for example, by booking or cancelling a spot, by appending a music placement, or by scheduling another avail) — is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not enumerated here do not take a version field.

### 2.8. Validation Ordering

When multiple validations apply to one endpoint, they are evaluated in a fixed priority order so the most fundamental problems surface first and are not masked by later checks. The order is: request well-formedness (`ERR_BAD_REQUEST`), then authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_ROLE_FORBIDDEN`), then ownership and segregation-of-duties checks (`ERR_NOT_ORDER_OWNER`, `ERR_SEGREGATION_OF_DUTIES`), then existence of every path id and referenced foreign key validated left-to-right (`ERR_NOT_FOUND`), then the TRADE-agreement-required structural rule (`ERR_TRADE_AGREEMENT_REQUIRED`), then the OCC stale-version check (`ERR_STALE_VERSION`), then generic from-state legality (`ERR_INVALID_STATE`), then the log posture gate (`ERR_LOG_POSTURE_BLOCKED`), order-active gate (`ERR_ORDER_NOT_ACTIVE`), reconcile gate (`ERR_UNRESOLVED_DISCREPANCIES`), and clock-pinning gate (`ERR_NO_ACTIVE_CLOCK`), then compliance gates on referenced entities (`ERR_CLEARANCE_NOT_CLEARED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_SONG_NOT_ACTIVE`, `ERR_CATEGORY_RETIRED`, `ERR_TRADE_AGREEMENT_INACTIVE`), then temporal/window rules in their declared sub-order (song separation, artist separation, clearance window, contract window, daypart-hour, spot-outside-flight, flight-window-at-activate-or-close), then uniqueness and quota rules (`ERR_LOG_ALREADY_EXISTS`, `ERR_CLOCK_WEEKDAY_OVERLAP`, `ERR_RATE_WINDOW_OVERLAP`, `ERR_CLEARANCE_WINDOW_OVERLAP`, `ERR_CATEGORY_SPIN_CAP_EXCEEDED`, `ERR_DISCREPANCY_NOT_WAIVABLE`, `ERR_DAYPART_UNITS_EXHAUSTED`), then hour-pool capacity and preemption-permission (`ERR_PREEMPTION_NOT_ALLOWED`, `ERR_HOUR_CAPACITY_EXCEEDED`), and finally fiscal rules in their declared sub-order (rate-card existence, then rate floor, then trade credit headroom).

Within the temporal tier, the declared sub-order is: (7a) `ERR_SPIN_SEPARATION_VIOLATION`, (7b) `ERR_ARTIST_SEPARATION_VIOLATION`, (7c) `ERR_CLEARANCE_WINDOW_VIOLATION`, (7d) `ERR_CONTRACT_WINDOW_VIOLATION`, (7e) `ERR_DAYPART_HOUR_MISMATCH`, (7f) `ERR_SPOT_OUTSIDE_FLIGHT`, (7g) `ERR_FLIGHT_WINDOW_INVALID`. Within the fiscal tier, the declared sub-order is: (10a) `ERR_NO_RATE_CARD`, (10b) `ERR_RATE_FLOOR_VIOLATION`, (10c) `ERR_TRADE_CREDIT_EXCEEDED`.

### 2.9. Hierarchical Consistency and Cascading Side Effects

When a parent undergoes a state change that affects dependents, the system cascades consistently. Cancelling an Order cascades its `SCHEDULED` and `MAKE_GOOD_PENDING` spots to `CANCELLED`, and for each cancelled TRADE spot appends a REVERSAL ledger entry equal to that spot's original DEBIT — which in turn recomputes the TradeAgreement's available credit and may flip an `EXHAUSTED` agreement back to `ACTIVE`. Disaffirming a clearance cascades its future-scheduled barter avails to `CANCELLED` and recomputes each affected log's occupancy counters (bumping each DailyLog's `version`). Retiring a clock does not disturb already-locked logs because they pinned `clock_id` and `clock_version` at lock time. Retiring a music category deliberately does **not** cascade retirement onto its songs; instead, new placements are blocked by `ERR_CATEGORY_RETIRED`. Cancelling an endorsement contract cascades its `SCHEDULED` live reads to `CANCELLED`. Every cascade that mutates an entity refreshes that entity's `updated_at` and increments its `version`.

### 2.10. Nested Resource Retrieval

The topology is flat — there is no URL nesting except the ledger-list sub-resources under trade agreements and spots. Path identifiers and body foreign-key references (for example `station_id`, `order_id`, `log_id`, `clearance_id`, `contract_id`, `category_id`, `event_id`, `trade_agreement_id`, `spot_id`) are validated for existence left-to-right; the first missing reference is rejected with `ERR_NOT_FOUND` before any further validation runs. Inside the as-run import, every identifier listed in `aired_spot_ids`, `aired_live_read_ids`, or `aired_barter_avail_ids` must belong to the log being imported; an id belonging to a different log or to no resource at all is rejected with `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Stations, Format Clocks, and the Music Library

A `SalesManager` establishes a Station by supplying its `call_sign`, `market_name`, and an optional `default_share_fallback` (used by ratings lookup when no published ratings book covers an air date; when omitted it defaults to 1.0). All other programming and sales entities hang off a station via `station_id`.

A `ProgramDirector` builds a FormatClock by naming it (`name`), declaring which weekdays it applies to (`applies_weekdays`, a non-empty subset of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`), and laying out its `slots` — an array of entries each carrying `slot_type` (one of `MUSIC`, `SPOT_BREAK`, `LIVE_READ_WINDOW`), `hour` (0 through 23), `capacity_units`, and `capacity_seconds`, with at most one slot per (`slot_type`, `hour`) pair. New clocks are `DRAFT`. Activating a clock (a `DRAFT → ACTIVE` transition by a `ProgramDirector`) enforces weekday-set disjointness against the station's other `ACTIVE` clocks: if any existing `ACTIVE` clock's `applies_weekdays` intersects the candidate's, the activation is rejected with `ERR_CLOCK_WEEKDAY_OVERLAP`. Activation increments the clock's `version`. Retiring a clock moves it to `RETIRED` from either `DRAFT` or `ACTIVE`; already-locked logs keep their pinned `clock_id` and `clock_version` — only future log locks stop selecting the retired clock.

Music rotation categories and songs live beside clocks. A MusicCategory carries `code` (unique per station, e.g. POWER, MEDIUM, LIGHT), `min_song_separation_min`, `min_artist_separation_min`, `max_spins_per_day`, and starts `ACTIVE`; a `ProgramDirector` may retire it. Songs carry `category_id`, `title`, `artist`, and `duration_sec`, and likewise start `ACTIVE`. Retiring a category deliberately leaves its songs in place — the separation-rule engine rejects new placements with `ERR_CATEGORY_RETIRED` instead — and retiring a song leaves existing `music_placements` intact on their logs while blocking new placements with `ERR_SONG_NOT_ACTIVE`.

### 3.2. Rate Card, Ratings Books, and the Spot Unit Rate

A `SalesManager` authors the rate card one entry at a time. Each RateCardEntry names a `daypart` (one of `MORNING_DRIVE`, `MIDDAY`, `AFTERNOON_DRIVE`, `EVENING`, `OVERNIGHT`), a `weekday_set`, a `base_rate_cents`, a `min_rate_cents` floor (positive and no greater than `base_rate_cents`), and an effective window from `effective_from` through `effective_to` (inclusive both ends). Creating an entry whose (`station_id`, `daypart`) pair, weekday set, and effective window all intersect an existing `ACTIVE` entry is rejected with `ERR_RATE_WINDOW_OVERLAP`. Retiring an entry leaves already-booked spots untouched because rates are copied onto the Spot at booking.

Ratings books arrive from the survey vendor and are entered as `DRAFT` records with `survey_name`, `period_start`, `period_end`, and `share_value` (strictly positive). Publishing a book (a `DRAFT → PUBLISHED` transition by a `SalesManager`, requiring `period_end` at least `period_start`) triggers a supersede cascade: every other `PUBLISHED` book on the same station whose period intersects the new book's period transitions to `SUPERSEDED`. After every publish, the `PUBLISHED` books of one station have pairwise disjoint periods, so a ratings lookup sees at most one candidate per air date — no tie-break is ever needed.

When the system needs a spot's unit rate — at booking, at make-good reschedule, or during affidavit repricing — it walks a fixed recipe. The **ratings multiplier** looks up the `PUBLISHED` RatingsBook covering the air date (both period bounds inclusive); if none exists, it falls back to the station's `default_share_fallback`. The share is then mapped to a multiplier by lower-bound tiers: a share below 2.0 yields 0.80; at least 2.0 but below 4.0 yields 1.00; at least 4.0 but below 6.0 yields 1.25; at least 6.0 yields 1.50. The **day-of-week factor** is 0.85 when the air date's weekday is `SAT` or `SUN`, and 1.00 otherwise. The **demand multiplier** measures the target hour's utilization before this booking: let `u` be the ratio of scheduled units (spots and barter avails in `SCHEDULED` or `AIRED` status within the daypart's hours on the target log) to capacity units (summed from the pinned clock's `SPOT_BREAK` slots over those hours). A `u` below 0.70 yields 1.00; at least 0.70 but below 0.85 yields 1.15; at least 0.85 yields 1.30 — so a utilization of exactly 0.70 already pushes the multiplier to 1.15, and exactly 0.85 pushes it to 1.30. The raw rate is `base_rate_cents` times these three multipliers; the final `unit_rate_cents` is the greater of `min_rate_cents` and the raw product rounded half-up to integer cents.

Two **reprice variants** govern when this computed rate becomes the billed rate. On a `LOCKED_AT_BOOKING` order, `billed_rate_cents` is pinned to `unit_rate_cents` at booking and never recomputed. On a `REPRICED_AT_AFFIDAVIT` order, `billed_rate_cents` is null at booking and recomputed at affidavit issuance with the then-current published ratings book and then-current demand utilization; a mid-flight ratings change therefore produces a different billed rate for otherwise identical booking inputs.

### 3.3. Trade Agreements and the Barter Ledger

A trade agreement represents a barter line of credit extended to a vendor. A `SalesRep` or `SalesManager` opens one with `vendor_name`, `credit_limit_cents`, and `trade_ratio` (the trade-dollars charged per cash-equivalent cent; strictly positive). The agreement starts `ACTIVE` with `consumed_cents` and `adjustments_cents` at zero, and `available_cents` equal to the credit limit.

The TradeLedgerEntry is an append-only event log on the agreement. Each entry carries a system-stamped `agreement_id` linking it to its owning TradeAgreement, an `entry_kind` (one of `DEBIT`, `REVERSAL`, `ADJUSTMENT`), `amount_cents` (positive for DEBIT and REVERSAL; signed for ADJUSTMENT, where a positive amount restores credit and a negative amount consumes it), an optional `note`, and a system-stamped `entry_seq` that increases monotonically per agreement starting at 1. DEBIT and REVERSAL entries are system-generated from the spot lifecycle and carry the originating `spot_id`; manual ADJUSTMENT entries are appended by a `BillingAdmin` (or by the system at affidavit repricing) and have `spot_id` null.

The agreement's computed fields are rebuilt by replaying its ledger in `entry_seq` order: `consumed_cents` is the sum of DEBIT amounts minus the sum of REVERSAL amounts; `adjustments_cents` is the signed sum of ADJUSTMENT amounts; `available_cents` is `credit_limit_cents` minus `consumed_cents` plus `adjustments_cents`. A hard invariant guards every write: `available_cents` may never go negative. Any write that would drive it below zero — a projected DEBIT at booking, a negative manual ADJUSTMENT, or an affidavit repricing delta — is rejected with `ERR_TRADE_CREDIT_EXCEEDED` (HTTP 402). Two cyclic auto-transitions keep status honest: when recomputation makes `available_cents` exactly zero on an `ACTIVE` agreement, the agreement flips to `EXHAUSTED`; when recomputation makes `available_cents` positive on an `EXHAUSTED` agreement, it flips back to `ACTIVE`.

A `BillingAdmin` may suspend an `ACTIVE` agreement (moving it to `SUSPENDED`), which blocks new trade submits, approvals, and bookings with `ERR_TRADE_AGREEMENT_INACTIVE`. Closing an agreement — from either `ACTIVE` or `SUSPENDED` — is gated on having no spot of any order pointing at this agreement still in `SCHEDULED` status. Trade valuation itself runs in two parallel views of the same booked spot: the cash-equivalent view stores `cash_equivalent_cents` equal to the spot's `unit_rate_cents` (what a cash buyer would pay), and the trade-ledger view appends a DEBIT of `trade_value` equal to the cash-equivalent amount multiplied by the agreement's `trade_ratio`, rounded half-up to integer cents. Whenever `trade_ratio` differs from 1.0, the two views diverge.

### 3.4. Orders, Segregation of Duties, and the Sales Workflow

A `SalesRep` opens an Order by naming the `advertiser_name`, choosing an `order_kind` of `CASH` or `TRADE`, supplying `flight_start` and `flight_end` (with `flight_end` at least `flight_start`), picking a `rate_tier` of `FIXED` or `PREEMPTIBLE`, choosing a `reprice_policy` of `LOCKED_AT_BOOKING` or `REPRICED_AT_AFFIDAVIT`, and laying out `daypart_targets` — a non-empty array of (`daypart`, `units`) pairs with unique dayparts. A TRADE order must reference a `trade_agreement_id`; a CASH order must not carry one — violations are rejected with `ERR_TRADE_AGREEMENT_REQUIRED`. The system stamps `created_by_user_id` from the caller's `X-User-ID`.

Submission (`DRAFT → SUBMITTED`) is restricted to the creator — any other `X-User-ID` is rejected with `ERR_NOT_ORDER_OWNER` — and additionally requires the referenced TradeAgreement to be `ACTIVE` for TRADE orders. Approval (`SUBMITTED → APPROVED`) requires a `SalesManager` whose `X-User-ID` differs from `created_by_user_id`; matching the creator is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval also re-checks that any referenced TradeAgreement is still `ACTIVE`. Rejection moves the order to `REJECTED`, a terminal state. Activation (`APPROVED → ACTIVE`) requires the logical clock's current date to fall inside the flight window — `flight_start` on or before today, and today on or before `flight_end` — else `ERR_FLIGHT_WINDOW_INVALID`. Cancellation (from `APPROVED` or `ACTIVE`) is permitted to the creator `SalesRep` or any `SalesManager`, and on an `ACTIVE` order cascades every `SCHEDULED` spot to `CANCELLED` (with a TRADE REVERSAL ledger entry per cancelled trade spot, possibly reviving an `EXHAUSTED` agreement), and every `MAKE_GOOD_PENDING` spot likewise to `CANCELLED`, voiding those obligations with the order. Completion (`ACTIVE → COMPLETED`) requires the logical clock to be strictly past `flight_end` and no spot of the order remaining in `SCHEDULED` or `MAKE_GOOD_PENDING`.

Two counters summarize fulfillment: `units_scheduled` counts the order's spots in `SCHEDULED` or `AIRED` (make-good successors excluded), and `units_aired` counts the spots in `AIRED`. Both are recomputed on every relevant spot transition, and each recomputation bumps the Order's `version`.

### 3.5. The Daily Log Lifecycle and Music Placements

A `TrafficDirector` opens a DailyLog for a (`station_id`, `log_date`) pair; only one log may exist per station and date, and a duplicate is rejected with `ERR_LOG_ALREADY_EXISTS`. The log's `posture` field starts at `DRAFT` and walks the lifecycle `DRAFT | LOCKED | AS_RUN | RECONCILING | RECONCILED | AFFIDAVIT_ISSUED | CLOSED`. Locking it (`DRAFT → LOCKED`) requires `expected_log_version` matching the log's current `version` (a mismatch is `ERR_STALE_VERSION`, HTTP 412), and the clock-pin-selection rule must find an `ACTIVE` FormatClock whose `applies_weekdays` covers the weekday of `log_date` — activation-time disjointness guarantees at most one candidate, and an empty candidate set rejects the lock with `ERR_NO_ACTIVE_CLOCK`. On success the log pins `clock_id` and `clock_version` from the selected clock; later edits or retirement of that clock never move the pin.

Once `LOCKED`, music placements may be appended. Each placement carries `song_id` and `hour` and is appended to the log's `music_placements` array with the next `placed_seq` (per-log monotonically increasing from 1). Spin compliance is checked in a fixed order — song separation first, then artist separation, then the daily spin cap. Song separation compares the candidate's hour against every existing placement of the same song on this log (never across logs) at hour granularity, treating minute-of-day as hour times 60: if any existing placement of the same song is closer than the category's `min_song_separation_min`, the placement is rejected with `ERR_SPIN_SEPARATION_VIOLATION`. Artist separation applies the same comparison to every existing placement of any song sharing the candidate's exact `artist` string against `min_artist_separation_min`, rejecting with `ERR_ARTIST_SEPARATION_VIOLATION`. Finally, the spin cap rejects with `ERR_CATEGORY_SPIN_CAP_EXCEEDED` when the count of existing placements of the same song on this log, plus the candidate, would exceed `max_spins_per_day`. Placements referencing a retired song are blocked earlier by `ERR_SONG_NOT_ACTIVE`, and placements referencing a song whose category is retired are blocked by `ERR_CATEGORY_RETIRED`.

### 3.6. Spot Inventory, Hour Pools, and Booking with Preemption

The hour-level sellable pool derives from the pinned clock's `SPOT_BREAK` slots at a given hour: `capacity_units` and `capacity_seconds` are each summed across those slots. Occupancy counts both units and seconds across Spots and BarterAvails in `SCHEDULED` or `AIRED` at that (log, hour). A new unit of one count and `duration_sec` seconds fits if and only if occupied units plus one is at most `capacity_units` and occupied seconds plus `duration_sec` is at most `capacity_seconds` — reaching the cap exactly is allowed; exceeding it by any amount rejects with `ERR_HOUR_CAPACITY_EXCEEDED`. A parallel `LIVE_READ_WINDOW` pool uses the same shape over `LIVE_READ_WINDOW` slots but counts only LiveReads in `SCHEDULED` or `AIRED`, and only by units. The daypart hour sets are fixed: `MORNING_DRIVE` covers hours 5 through 8, `MIDDAY` covers 9 through 13, `AFTERNOON_DRIVE` covers 15 through 18, `EVENING` covers 19 through 21, and `OVERNIGHT` covers 0 through 4.

Booking a spot is a dense operation. The caller — a `SalesRep` or `TrafficDirector` — supplies `order_id`, `log_id`, `daypart`, `hour`, `duration_sec` (one of 15, 30, or 60), and `expected_order_version` matching the Order's current `version` (mismatch yields `ERR_STALE_VERSION`). The order must be `ACTIVE` (`ERR_ORDER_NOT_ACTIVE` otherwise), the target log's posture must be `DRAFT` or `LOCKED` (`ERR_LOG_POSTURE_BLOCKED` otherwise), the chosen `hour` must belong to the chosen `daypart` (`ERR_DAYPART_HOUR_MISMATCH` otherwise), the spot's `air_date` (copied from the log's `log_date` at creation) must lie within the order's flight (`ERR_SPOT_OUTSIDE_FLIGHT` otherwise), and the per-(order, daypart) scheduled count must remain below the `units` declared in `daypart_targets` (`ERR_DAYPART_UNITS_EXHAUSTED` otherwise). An optional `event_id` tags the spot as fulfilling a remote-event sponsorship package. On the fiscal side, the system locates an `ACTIVE` RateCardEntry matching the station, daypart, weekday of `air_date`, and effective window — absence yields `ERR_NO_RATE_CARD` — and computes `unit_rate_cents` via the spot-unit-rate recipe (demand tier evaluated before this booking). A caller may pass `unit_rate_override_cents` to override the computed rate; if that override falls below `min_rate_cents`, the booking is rejected with `ERR_RATE_FLOOR_VIOLATION` unless the caller is a `SalesManager` passing `allow_below_floor` as true. For TRADE orders the agreement must be `ACTIVE`, and the projected DEBIT must not exceed `available_cents` (`ERR_TRADE_CREDIT_EXCEEDED` otherwise). On success, the spot is created `SCHEDULED`, `billed_rate_cents` is set at booking when the order's `reprice_policy` is `LOCKED_AT_BOOKING` (null otherwise), `cash_equivalent_cents` is set when the order is TRADE (null otherwise), a TRADE DEBIT ledger entry is appended (possibly flipping the agreement `ACTIVE → EXHAUSTED`), and the order's `units_scheduled` is recomputed with `version` bumped.

When the target hour is full, a `FIXED`-tier order may request `allow_preemption`. Requesting preemption on a `PREEMPTIBLE` order is rejected with `ERR_PREEMPTION_NOT_ALLOWED`. The preemption selector builds the victim pool from spots at the same (log, hour) in `SCHEDULED` status whose order's `rate_tier` is `PREEMPTIBLE`, ranks them by `unit_rate_cents` ascending with ties broken by `created_at` ascending (the `id` is never used as a tiebreak), and preempts the minimum prefix of victims needed for the new unit to fit both units and seconds. If preempting the entire pool still does not free enough capacity, the booking is rejected with `ERR_HOUR_CAPACITY_EXCEEDED` and no partial preemption is committed. Each victim transitions to `MAKE_GOOD_PENDING` with `make_good_reason` `PREEMPTED`; TRADE victims also append a REVERSAL ledger entry, which may flip their agreement `EXHAUSTED → ACTIVE`.

Spots may be individually cancelled from `SCHEDULED` (by a `TrafficDirector`, while the log's posture is `DRAFT` or `LOCKED`), appending a TRADE REVERSAL if applicable and recomputing the order's `units_scheduled`. Spot terminal states are `AIRED`, `RESOLVED`, and `CANCELLED`.

### 3.7. As-Run Import, Discrepancies, and Make-Goods

After broadcast, a `TrafficDirector` imports the as-run log by listing `aired_spot_ids`, `aired_live_read_ids`, and `aired_barter_avail_ids`. Every identifier in these lists must belong to the log being imported; an unknown or foreign id is rejected with `ERR_NOT_FOUND`. The transition moves the log `LOCKED → AS_RUN` and sweeps every holding unit. A spot of this log in `SCHEDULED` whose id appears in `aired_spot_ids` becomes `AIRED` (and the order's `units_aired` and `units_scheduled` are recomputed); a `SCHEDULED` spot not listed becomes `MAKE_GOOD_PENDING` with `make_good_reason` `MISSED` and spawns a Discrepancy of kind `MISSED_SPOT` in `UNRESOLVED` status. Each TRADE spot transitioning to `MAKE_GOOD_PENDING` appends a REVERSAL ledger entry equal to its original DEBIT (possibly reviving an `EXHAUSTED` agreement). A LiveRead of this log in `SCHEDULED` is likewise promoted to `AIRED` when listed (recomputing its contract's `reads_completed`) or to `MAKE_GOOD_PENDING` with a `MISSED_READ` Discrepancy when omitted. A BarterAvail of this log in `SCHEDULED` becomes `AIRED` when listed or `MISSED` when omitted, and a missed avail spawns an `UNFILLED_BARTER` Discrepancy with its `barter_avail_id` set.

An **under-coverage sweep** then runs across every `CLEARED` SyndicationClearance covering the weekday and hour of `log_date` and whose effective range contains `log_date`: if the count of avails `AIRED` at a covered hour is below the clearance's `barter_avails_per_hour`, one `UNFILLED_BARTER` Discrepancy per (clearance, hour) is created with `barter_avail_id` null. Re-imports are permitted after a reopen: a spot already `AIRED` that is omitted from a re-import becomes `MAKE_GOOD_PENDING` (reason `MISSED`) with a fresh Discrepancy, while a spot listed again stays `AIRED`.

A make-good obligation has exactly two resolutions. **Reschedule** — by a `TrafficDirector` for either a spot or a live read — requires the target log's posture be `DRAFT` or `LOCKED`; for spots, the target hour must belong to the target daypart, the target date must lie within the order's flight, and capacity must fit without preemption (make-goods never preempt). Rescheduling a spot takes `target_log_id`, `target_daypart`, `target_hour`, and `duration_sec`, creates a successor Spot in `SCHEDULED` with `makeup_of_spot_id` set to the original's id, computes a fresh `unit_rate_cents`, posts a new DEBIT for TRADE orders, and explicitly does not count the successor against `daypart_targets`. Rescheduling a live read takes `target_log_id` and `target_hour`, requires the contract's program window to be satisfied for the target, and creates a successor with `makeup_of_live_read_id` set. In both cases, the linked `MISSED_SPOT` or `MISSED_READ` Discrepancy auto-transitions `UNRESOLVED → RESOLVED`. **Issue-credit** — by a `BillingAdmin`, optionally carrying a `note` — closes the obligation with no successor; for spots this is straightforward because no billing occurred for non-AIRED spots and any TRADE reversal already posted at `MAKE_GOOD_PENDING` time. Issue-credit also auto-resolves the linked Discrepancy.

The system enforces a make-good conservation invariant after every spot and live-read transition: the count of spots in `MAKE_GOOD_PENDING` plus the count `RESOLVED` always equals the count of `make_good_reason` `PREEMPTED` plus the count `MISSED` — every preemption or miss creates exactly one obligation and every obligation closes exactly once. The same shape holds for live reads, which only ever carry reason `MISSED`.

A Discrepancy records its `discrepancy_kind` (one of `MISSED_SPOT`, `MISSED_READ`, `UNFILLED_BARTER`), its owning `log_id`, its copied `station_id`, and the optional foreign key matching its kind: `spot_id` is set if and only if the kind is `MISSED_SPOT`, `live_read_id` is set if and only if the kind is `MISSED_READ`, and `barter_avail_id` is set for a missed scheduled avail but is null on under-coverage (fewer avails aired than `barter_avails_per_hour`). Every Discrepancy starts in `UNRESOLVED` status.

Explicit discrepancy management is narrow: a `TrafficDirector` may explicitly resolve only an `UNFILLED_BARTER` discrepancy, transitioning it `UNRESOLVED → RESOLVED` (attempting to explicitly resolve a `MISSED_SPOT` or `MISSED_READ` is rejected with `ERR_DISCREPANCY_NOT_WAIVABLE`), and a `BillingAdmin` may waive only an `UNFILLED_BARTER` discrepancy, transitioning it `UNRESOLVED → WAIVED` (any other kind is rejected with the same `ERR_DISCREPANCY_NOT_WAIVABLE`). Both explicit resolution and waiver set `resolved_by_user_id`, accept an optional `resolution_note`, and recompute the owning log's `unresolved_discrepancy_count`. Discrepancies auto-resolved by a linked obligation's resolution record the system as the resolver.

### 3.8. Reconciliation, Affidavit Issuance, and Log Close

Beginning reconciliation moves the log `AS_RUN → RECONCILING`. From `RECONCILING`, a `TrafficDirector` may either reopen the log back to `LOCKED` — which preserves all `MAKE_GOOD_PENDING` obligations and existing discrepancies (obligations are not erased) while re-enabling bookings and edits, with a later as-run-import re-evaluating spots still in `SCHEDULED` or `AIRED` — or reconcile it (`RECONCILING → RECONCILED`), which requires `unresolved_discrepancy_count` to be exactly zero (any positive count is rejected with `ERR_UNRESOLVED_DISCREPANCIES`) and stamps `reconciled_by_user_id` from the caller. Reopening from `RECONCILED` reverts to `RECONCILING` and clears `reconciled_by_user_id` to null.

Issuing the affidavit (`RECONCILED → AFFIDAVIT_ISSUED`) is restricted to a `BillingAdmin` whose `X-User-ID` differs from `reconciled_by_user_id`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. Issuance reprices every `AIRED` spot of a `REPRICED_AT_AFFIDAVIT` order via the spot-unit-rate recipe using the then-current published ratings book and then-current demand; `LOCKED_AT_BOOKING` spots keep their booked `billed_rate_cents`. For each repriced TRADE spot, the system appends an ADJUSTMENT ledger entry equal to the original DEBIT minus the new trade value (signed), recomputing `available_cents` — if that recomputation would drive available below zero the affidavit is rejected with `ERR_TRADE_CREDIT_EXCEEDED`. The affidavit total is computed per order: for each order with at least one `AIRED` spot on the log, the order's net is the sum over those spots of each spot's `billed_rate_cents` multiplied by one minus the agency commission of 0.15, with each per-spot line rounded half-up to integer cents **before** summing. The `affidavit_total_cents` is the sum of those per-order nets. The pinned rounding order is load-bearing: summing first and rounding once is a different and forbidden variant, because two spots each billed 1003 cents yield 853 plus 853 equals 1706 cents under per-line rounding but 1705 cents under sum-then-round. Issuance stamps `affidavit_issued_by_user_id` and stores `affidavit_total_cents` on the log. Closing the log (`AFFIDAVIT_ISSUED → CLOSED`) is the terminal step.

### 3.9. Syndication Clearances and Barter Avails

A `ProgramDirector` registers a SyndicationClearance with `program_name`, `provider`, `weekday_set`, `start_hour`, `duration_hours` (the half-open window from `start_hour` up to but not including `start_hour` plus `duration_hours`, never wrapping past hour 24), `barter_avails_per_hour` (at least 1), and an effective window from `effective_from` through `effective_to`. New clearances start `PENDING`. Clearing one (`PENDING → CLEARED`) is blocked when another `CLEARED` clearance on the same station intersects on all three axes — weekday set, half-open hour window, and effective date range — and is rejected with `ERR_CLEARANCE_WINDOW_OVERLAP`; mere adjacency where one window's end equals the other's start is allowed. Disaffirming (`PENDING → DISAFFIRMED` or `CLEARED → DISAFFIRMED`) cascades: every BarterAvail of this clearance in `SCHEDULED` status whose `air_date` is strictly after the logical clock's current date transitions to `CANCELLED`, and each such cancellation recomputes its owning log's spot-pool occupancy counters and bumps the log's `version`.

Scheduling a barter avail is a `TrafficDirector` operation requiring `clearance_id`, `log_id`, `hour`, `duration_sec`, and `expected_clearance_version` matching the clearance's current `version` (mismatch yields `ERR_STALE_VERSION`, HTTP 412). The clearance must be `CLEARED` (`ERR_CLEARANCE_NOT_CLEARED` otherwise), the weekday of `air_date` must be in the clearance's `weekday_set`, the `hour` must satisfy the half-open window from `start_hour`, and `air_date` must lie inside the effective range — violations yield `ERR_CLEARANCE_WINDOW_VIOLATION`. The target log's posture must be `DRAFT` or `LOCKED`, and the hour's `SPOT_BREAK` pool must fit the avail. On success the avail consumes sellable spot-pool inventory of the hour and the clearance's `version` increments as an OCC write.

### 3.10. Endorsement Contracts and Live Reads

A `SalesRep` drafts an EndorsementContract naming the `advertiser_name` and the `host_name` whose program carries the reads, declaring `program_weekdays`, `program_start_hour`, and `program_end_hour` (the half-open program window from `program_start_hour` up to but not including `program_end_hour`, with `program_end_hour` strictly greater than `program_start_hour` and at most 24), `reads_per_week` (at least 1), and a contract window from `start_date` through `end_date`. At creation the system computes `contracted_reads_total` as `reads_per_week` times the number of whole weeks in the window — that is, the floor of (window length in days) divided by 7, where the window length counts both `start_date` and `end_date`; a partial trailing week does not add reads.

Activation (`DRAFT → ACTIVE`) by a `SalesManager` requires the logical clock's current date to fall inside the contract window, else `ERR_FLIGHT_WINDOW_INVALID`. Closing (from `ACTIVE`) requires the clock to be strictly past `end_date`; if `reads_completed` — the count of this contract's live reads in `AIRED` — is at least `contracted_reads_total`, the contract transitions to `COMPLETED`, otherwise to `BREACHED`. Cancellation from `DRAFT` or `ACTIVE` cascades every `SCHEDULED` live read of the contract to `CANCELLED`.

Scheduling a live read — a `TrafficDirector` operation with `contract_id`, `log_id`, `hour`, and optional `duration_sec` (defaulting to 60; allowed values are 30 and 60) — requires the contract be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE` otherwise), the weekday of `air_date` to be in `program_weekdays`, the `hour` to satisfy the program window, `air_date` to lie inside the contract window (violations yield `ERR_CONTRACT_WINDOW_VIOLATION`), and the target log's posture to be `DRAFT` or `LOCKED`. The hour's `LIVE_READ_WINDOW` pool must fit the unit. A missed live read found at as-run import becomes `MAKE_GOOD_PENDING` with a `MISSED_READ` Discrepancy, and resolves via reschedule or issue-credit as described in §3.7.

### 3.11. Remote Broadcast Events

A `SalesRep` packages a remote broadcast as a RemoteEvent with `event_name`, `sponsor_name`, `event_date`, `spot_units_promised` (at least 1), and `package_price_cents`. The event starts `PLANNED`. Confirmation by a `SalesManager` requires `event_date` to be on or after the logical clock's current date. Cancellation is permitted from `PLANNED` or `CONFIRMED` and does not cancel already-booked spots tagged with this event's `event_id` — those sponsor spots stand.

Settlement (`CONFIRMED → DELIVERED` or `CONFIRMED → DEFAULTED`) is gated cross-entity on the DailyLog for (`station_id`, `event_date`) existing and being in `AFFIDAVIT_ISSUED` or `CLOSED` posture: if no such DailyLog exists the settle is rejected with `ERR_NOT_FOUND`, and if the log's posture is anything other than `AFFIDAVIT_ISSUED` or `CLOSED` the settle is rejected with `ERR_LOG_POSTURE_BLOCKED`. The system counts `spots_delivered` as the number of spots tagged with this event, in `AIRED` status, on the event date's log. When `spots_delivered` is at least `spot_units_promised` — equality delivers — the event transitions to `DELIVERED`; otherwise to `DEFAULTED`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including all state-transition endpoints and the append of music placements to an existing log — return `200 OK`. The single exception among creation endpoints is the manual trade-ledger adjustment entry, which also returns `201 Created`. The logical-clock setter returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/stations` | Create a station | SalesManager |
| GET | `/stations/{id}` | Get a station | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/stations` | List stations (paginated) | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/clocks` | Create a format clock (DRAFT) | ProgramDirector |
| GET | `/clocks/{id}` | Get a clock | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/clocks` | List clocks | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/clocks/{id}/activate` | Activate a DRAFT clock (weekday disjointness enforced) | ProgramDirector |
| POST | `/clocks/{id}/retire` | Retire a clock (pinned logs unaffected) | ProgramDirector |
| POST | `/music-categories` | Create a rotation category (ACTIVE) | ProgramDirector |
| GET | `/music-categories/{id}` | Get a category | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/music-categories` | List categories | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/music-categories/{id}/retire` | Retire a category (songs NOT cascaded) | ProgramDirector |
| POST | `/songs` | Add a song to the station library (ACTIVE) | ProgramDirector |
| GET | `/songs/{id}` | Get a song | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/songs` | List songs | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/songs/{id}/retire` | Retire a song | ProgramDirector |
| POST | `/ratings-books` | Create a ratings book (DRAFT) | SalesManager |
| GET | `/ratings-books/{id}` | Get a ratings book | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/ratings-books` | List ratings books | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/ratings-books/{id}/publish` | Publish a book; overlapping PUBLISHED books are superseded (cascade) | SalesManager |
| POST | `/rate-card-entries` | Create a rate card entry (ACTIVE) | SalesManager |
| GET | `/rate-card-entries/{id}` | Get a rate card entry | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/rate-card-entries` | List rate card entries | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/rate-card-entries/{id}/retire` | Retire a rate card entry | SalesManager |
| POST | `/clearances` | Create a syndication clearance (PENDING) | ProgramDirector |
| GET | `/clearances/{id}` | Get a clearance | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/clearances` | List clearances | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/clearances/{id}/clear` | Clear a PENDING clearance (overlap vs CLEARED set rejected) | ProgramDirector |
| POST | `/clearances/{id}/disaffirm` | Disaffirm a clearance; future SCHEDULED barter avails are cancelled | ProgramDirector |
| POST | `/trade-agreements` | Create a trade agreement (ACTIVE) | SalesRep, SalesManager |
| GET | `/trade-agreements/{id}` | Get a trade agreement | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/trade-agreements` | List trade agreements | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/trade-agreements/{id}/suspend` | Suspend an ACTIVE agreement | BillingAdmin |
| POST | `/trade-agreements/{id}/close` | Close an agreement (no SCHEDULED trade spots may remain) | BillingAdmin |
| POST | `/trade-agreements/{id}/ledger-entries` | Append a manual ADJUSTMENT entry | BillingAdmin |
| GET | `/trade-agreements/{id}/ledger-entries` | List ledger entries of an agreement in entry_seq order | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/spots/{id}/ledger-entries` | List ledger entries generated by a spot in entry_seq order | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/orders` | Create an advertising order (DRAFT) | SalesRep |
| GET | `/orders/{id}` | Get an order | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/orders` | List orders | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/orders/{id}/submit` | Submit a DRAFT order (creator SalesRep only) | SalesRep |
| POST | `/orders/{id}/approve` | Approve a SUBMITTED order (approver must differ from creator) | SalesManager |
| POST | `/orders/{id}/reject` | Reject a SUBMITTED order | SalesManager |
| POST | `/orders/{id}/activate` | Activate an APPROVED order (clock must be inside the flight) | SalesManager |
| POST | `/orders/{id}/cancel` | Cancel an APPROVED/ACTIVE order; cascades spots to CANCELLED with trade REVERSALs | SalesRep, SalesManager |
| POST | `/orders/{id}/complete` | Complete an ACTIVE order after flight end with no open obligations | SalesManager |
| POST | `/logs` | Create a daily log (DRAFT); unique per (station, log_date) | TrafficDirector |
| GET | `/logs/{id}` | Get a log | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/logs` | List logs | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/logs/{id}/lock` | Lock a DRAFT log; pins the ACTIVE clock covering the weekday | TrafficDirector |
| POST | `/logs/{id}/music-placements` | Place a song on a LOCKED log | ProgramDirector, TrafficDirector |
| POST | `/logs/{id}/as-run-import` | Import the as-run log; unlisted SCHEDULED units become missed with discrepancies | TrafficDirector |
| POST | `/logs/{id}/begin-reconciliation` | Move AS_RUN to RECONCILING | TrafficDirector |
| POST | `/logs/{id}/reopen` | Reopen a RECONCILING log to LOCKED, or a RECONCILED log back to RECONCILING | TrafficDirector |
| POST | `/logs/{id}/reconcile` | Reconcile; requires zero unresolved discrepancies | TrafficDirector |
| POST | `/logs/{id}/issue-affidavit` | Issue affidavit (issuer must differ from reconciler); reprices REPRICED spots and computes affidavit total | BillingAdmin |
| POST | `/logs/{id}/close` | Close an AFFIDAVIT_ISSUED log | BillingAdmin |
| POST | `/spots` | Book a spot onto a log | SalesRep, TrafficDirector |
| GET | `/spots/{id}` | Get a spot | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/spots` | List spots (filterable, paginated) | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/spots/{id}/cancel` | Cancel a SCHEDULED spot (log posture permitting) | TrafficDirector |
| POST | `/spots/{id}/reschedule` | Resolve a make-good by creating a successor spot (no preemption allowed) | TrafficDirector |
| POST | `/spots/{id}/issue-credit` | Resolve a make-good by issuing a credit (no successor spot) | BillingAdmin |
| POST | `/barter-avails` | Schedule a network barter avail | TrafficDirector |
| GET | `/barter-avails/{id}` | Get a barter avail | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/barter-avails` | List barter avails | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/endorsement-contracts` | Create an endorsement contract (DRAFT) | SalesRep |
| GET | `/endorsement-contracts/{id}` | Get a contract | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/endorsement-contracts` | List contracts | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/endorsement-contracts/{id}/activate` | Activate a DRAFT contract (clock must be inside the window) | SalesManager |
| POST | `/endorsement-contracts/{id}/close` | Close after end_date: COMPLETED if reads_completed meets contracted total else BREACHED | SalesManager |
| POST | `/endorsement-contracts/{id}/cancel` | Cancel a contract; cascades SCHEDULED live reads to CANCELLED | SalesRep, SalesManager |
| POST | `/live-reads` | Schedule a live read inside the contract's program window | TrafficDirector |
| GET | `/live-reads/{id}` | Get a live read | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/live-reads` | List live reads | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/live-reads/{id}/reschedule` | Resolve a missed live read by creating a successor inside the program window | TrafficDirector |
| POST | `/live-reads/{id}/issue-credit` | Resolve a missed live read with a credit (no successor) | BillingAdmin |
| GET | `/discrepancies/{id}` | Get a discrepancy | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/discrepancies` | List discrepancies | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/discrepancies/{id}/resolve` | Explicitly resolve an UNFILLED_BARTER discrepancy | TrafficDirector |
| POST | `/discrepancies/{id}/waive` | Waive an UNFILLED_BARTER discrepancy | BillingAdmin |
| POST | `/remote-events` | Create a remote broadcast sponsorship package (PLANNED) | SalesRep |
| GET | `/remote-events/{id}` | Get a remote event | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| GET | `/remote-events` | List remote events | ProgramDirector, TrafficDirector, SalesRep, SalesManager, BillingAdmin |
| POST | `/remote-events/{id}/confirm` | Confirm a PLANNED event (event_date must not be in the past) | SalesManager |
| POST | `/remote-events/{id}/cancel` | Cancel a PLANNED/CONFIRMED event (tagged spots stand) | SalesManager |
| POST | `/remote-events/{id}/settle` | Settle a CONFIRMED event once the event date's log has an issued affidavit | SalesManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOG_POSTURE_BLOCKED` | 409 |
| `ERR_ORDER_NOT_ACTIVE` | 409 |
| `ERR_UNRESOLVED_DISCREPANCIES` | 409 |
| `ERR_NO_ACTIVE_CLOCK` | 422 |
| `ERR_TRADE_AGREEMENT_REQUIRED` | 422 |
| `ERR_TRADE_AGREEMENT_INACTIVE` | 409 |
| `ERR_TRADE_CREDIT_EXCEEDED` | 402 |
| `ERR_SONG_NOT_ACTIVE` | 409 |
| `ERR_CATEGORY_RETIRED` | 409 |
| `ERR_CLEARANCE_NOT_CLEARED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_SPIN_SEPARATION_VIOLATION` | 422 |
| `ERR_ARTIST_SEPARATION_VIOLATION` | 422 |
| `ERR_CLEARANCE_WINDOW_VIOLATION` | 422 |
| `ERR_CONTRACT_WINDOW_VIOLATION` | 422 |
| `ERR_DAYPART_HOUR_MISMATCH` | 422 |
| `ERR_SPOT_OUTSIDE_FLIGHT` | 422 |
| `ERR_FLIGHT_WINDOW_INVALID` | 422 |
| `ERR_LOG_ALREADY_EXISTS` | 409 |
| `ERR_CLOCK_WEEKDAY_OVERLAP` | 409 |
| `ERR_RATE_WINDOW_OVERLAP` | 409 |
| `ERR_CLEARANCE_WINDOW_OVERLAP` | 409 |
| `ERR_CATEGORY_SPIN_CAP_EXCEEDED` | 422 |
| `ERR_DISCREPANCY_NOT_WAIVABLE` | 422 |
| `ERR_DAYPART_UNITS_EXHAUSTED` | 422 |
| `ERR_PREEMPTION_NOT_ALLOWED` | 409 |
| `ERR_HOUR_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_RATE_CARD` | 422 |
| `ERR_RATE_FLOOR_VIOLATION` | 422 |
