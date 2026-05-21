# Marina Slip Rental API — Product Requirements Document

## 1. Introduction

Recreational marinas balance two adversarial demands: a fixed inventory of physical slips and a fluid population of boaters whose vessels vary in length, beam, and draft, whose insurance lapses without warning, and whose stays span seasonal price boundaries. The team has historically managed this overlap with paper logs and a whiteboard, which scales poorly the moment liveaboard occupants — boaters who treat a slip as a residence — enter the picture and bring kilowatt-hour metering, water consumption, sewage handling, and a regulated quota onto the dock master's desk.

This API consolidates the marina's day-to-day operations into a single transactional system. It governs slip inventory, vessel dimensions and their compatibility with available berths, reservation lifecycles from intent to settlement, seasonal pricing that may shift mid-stay, the liveaboard quota and its utility billing, scheduled pump-out service, insurance coverage windows, tow-assist contracts, an append-only waitlist that promotes automatically when slips free up, and a slip transfer flow that lets a berthed boater move to a different berth without losing their booking. Two roles drive the system on the dock — a `DockMaster` running operations and a `Boater` self-serving their own bookings — while a third `BillingClerk` role consumes settlement data for invoicing.

A logical clock advances under operator control rather than from wall time, which lets QA scripts and seasonal scenarios be replayed deterministically. A periodic operations sweep expires stale records, promotes waitlist entries against now-available slips, and keeps derived counters in sync.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. The three permitted roles, spelled exactly, are `DockMaster`, `Boater`, and `BillingClerk`. Requests missing either header are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Requests whose role is not permitted to invoke the requested endpoint — or whose ownership check fails for a resource that belongs to a different boater — are rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Boater` role is entity-backed: when `X-User-Role` is `Boater`, the value of `X-User-ID` is the `id` of the acting `Boater`, and ownership checks on any resource that references a boater compare the resource's `boater_id` foreign-key field to `X-User-ID`. A `Boater` may therefore act on their own boater record, their own vessels, reservations, waitlist entries, pump-out jobs, insurance policies, tow contracts, and slip transfer requests, but not on those of any other boater.

The `DockMaster` and `BillingClerk` roles are opaque: when `X-User-Role` is `DockMaster` or `BillingClerk`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example in a request log) but does not compare it to any entity's `id`. Both roles act marina-wide rather than on a single boater's behalf — the `DockMaster` runs slip inventory, reservation approval, check-in and check-out, transfer offers, pump-out completion, meter readings, tow events, the test clock, and the periodic ops sweep; the `BillingClerk` is read-only and exists to consume reservation totals, utility settlements, policies, and tow contracts for invoicing.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0. Any list result is sorted by `created_at` ascending; this ordering is stable across calls within a marina. The `meta` envelope on list responses includes `limit`, `offset`, `total_count` (the total number of matching records, ignoring pagination), and `has_more` (`true` when more records remain beyond the current page).

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` field — a UUID without any type prefix. Most resources also carry `created_at`, `updated_at`, and `version`. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `version` is an integer that starts at 1 on creation and increments by one on every mutation that changes the resource. The `WaitlistEntry`, `UtilityReading`, and `TowEvent` records, however, are immutable append-only artifacts: they carry only `id` and `created_at`, and they have neither an `updated_at` nor a `version` field. A `WaitlistEntry` may move from `QUEUED` to `PROMOTED`, `CANCELLED`, or `EXPIRED` via a server-side selector or explicit cancel, but the system treats each such transition as the entry's terminal observation rather than as a versioned mutation.

### 2.5. Hierarchy and Path Resolution

URLs are nested to express the entity hierarchy: a marina owns slips, boaters, reservations, waitlist entries, transfer requests, pump-out jobs, and a marina-scoped operations counter; a boater owns vessels, insurance policies, and tow-assist contracts; a reservation owns utility readings and utility settlements; a tow contract owns tow events. Path identifiers are validated strictly left to right. If `/marinas/:marina_id` resolves but `/marinas/:marina_id/reservations/:reservation_id` does not, the rejection is `ERR_NOT_FOUND` (HTTP 404) for the reservation. If the reservation exists but belongs to a different marina than the one in the URL, the same `ERR_NOT_FOUND` applies — cross-marina addressing is never resolved. The same rule reaches every nested path: a vessel that does not belong to the named boater, a pump-out job that does not belong to the named reservation, and a tow event whose contract does not match the URL contract all 404.

### 2.6. Optimistic Concurrency

Every `PATCH` or `PUT` request must include an `If-Match` header whose value equals the current integer `version` of the target resource. If the header is missing on such a request, or if its value does not match the stored `version`, the server rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409). State-transition `POST` actions (approve, check-in, accept, etc.) do not require `If-Match`; they serialize on the state column itself, with the loser of any race receiving the more specific business error described in §3 rather than a version conflict.

### 2.7. The Logical Clock and Operations Sweep

Time inside a marina advances only when an operator advances it. A test-driving capability accepts a target instant via the `to` request field and assigns it to the marina's `current_date`; subsequent operations consult this value rather than wall-clock time. A periodic operations sweep — an opaque batch tick — increments `ops_run_index` by one and then performs four cascading housekeeping actions in a single pass: any `ACTIVE` insurance policy whose `expiration_date` has been reached or passed by the marina clock transitions to `EXPIRED`; any `APPROVED` reservation whose `check_in_date` was a full day or more in the past and which never checked in transitions to `EXPIRED` (and the marina's liveaboard count is decremented if the expired reservation was a liveaboard); any transfer request that has been sitting in `OFFERED` past its `offer_expires_at` transitions to `EXPIRED`; the slip-match selector then walks `QUEUED` waitlist entries in ascending `sequence_no` order, promoting those whose vessel can be berthed and expiring those whose `requested_check_out` has been reached or passed.

### 2.8. Pricing Precision and Rounding

All monetary values are stored as integer cents — never floating-point dollars. When a per-night price requires rounding (because a season multiplier produces a fractional cent), the per-night raw amount is rounded half-up to a whole cent before any aggregation across nights. Multi-night totals are then exact integer sums of these rounded per-night amounts. Utility charges (kWh and water) are computed at whole-cent rates and require no rounding; the flat sewage charge is a constant whole-cent amount.

### 2.9. Half-Open Date Intervals

Reservation windows, waitlist windows, and pump-out windows are all expressed as half-open intervals. A reservation runs from inclusive `check_in_date` to exclusive `check_out_date`; back-to-back reservations whose first ends on day D and whose second begins on day D do not overlap. A reservation's number of nights is the whole-day difference between `check_out_date` and `check_in_date`, and `check_out_date` must be strictly after `check_in_date`. Pump-out windows use the open-start, closed-end form `(scheduled_start, scheduled_end]`; two pump-out windows on the same slip overlap when their open intervals share any instant.

### 2.10. Derived Counter Reconciliation

The marina's `liveaboard_active_count` is a derived integer counter equal to the number of reservations on this marina with `liveaboard` set to true and `status` in `APPROVED` or `CHECKED_IN`. It is maintained in lock-step with the reservation state machine — incremented on a liveaboard transition into `APPROVED`, decremented when a liveaboard reservation leaves `APPROVED` for `CANCELLED` or `EXPIRED`, and decremented again when a liveaboard reservation completes `CHECKED_IN → CHECKED_OUT`. Whenever the count changes, the marina's `updated_at` is refreshed and its `version` is bumped.

## 3. Business Logic & Workflows

### 3.1. Marina Bootstrap and the Logical Clock

A marina is the top-level tenant. Creating one requires a `name`, a `timezone` (defaulting to `America/New_York` if omitted; the timezone is used to bucket nights for chronological billing), a `base_daily_rate_cents` per foot of vessel length overall, and a `liveaboard_quota` — the maximum number of simultaneously approved liveaboard reservations the marina will allow. At creation the marina's `current_date` is initialized to `1970-01-01T00:00:00.000Z`, its `ops_run_index` is 0, and its `liveaboard_active_count` is 0.

Because the system is driven by a logical clock rather than wall time, a `DockMaster` advances it explicitly: an operator-only test-driving capability accepts a `to` instant and assigns it to the marina's `current_date`. Every time-gated transition in the rest of this document consults that value. The periodic ops sweep — described in §2.7 — runs only when the dock master invokes it, increments `ops_run_index` by one, and performs the four housekeeping cascades it owns.

### 3.2. Boaters, Vessels, and Their Coverage

A boater is created with a `name`. The new record carries a `deposit_balance_cents` initialized to 0 and a `status` of `ACTIVE`; `ACTIVE` is the only boater status produced in this version of the system, reserved for future suspension semantics. A `Boater` caller's `X-User-ID` must match the resulting boater `id` for all subsequent self-service operations on that boater's owned resources.

Each boater registers one or more vessels. A vessel carries a display `name` and three physical measurements in feet at one decimal place: `loa_feet` (length overall, which must be strictly greater than zero), `beam_feet` (maximum width, strictly greater than zero), and `draft_feet` (depth in the water, strictly greater than zero). The vessel also carries an optional integer `holding_tank_gallons` — the marine sanitation tank capacity. This field is optional at creation but becomes mandatory at reservation approval if the vessel is ever used for a liveaboard reservation; an approval attempt on a liveaboard reservation whose vessel has no `holding_tank_gallons` is rejected with `ERR_LIVEABOARD_POLICY_VIOLATION`.

Before a reservation can be approved, the boater must hold an insurance policy that covers the term. A policy is created against the boater with a `carrier` name, a `liability_limit_cents` per-occurrence limit, and a coverage window expressed as `effective_date` (inclusive) and `expiration_date` (exclusive). New policies enter `ACTIVE`. The ops sweep transitions any `ACTIVE` policy whose `expiration_date` has been reached or passed by the marina clock to `EXPIRED`; once expired, a reservation that still references the lapsed policy continues to exist but its approval will now fail with `ERR_INSURANCE_LAPSED`. A boater may also cancel an `ACTIVE` policy explicitly, transitioning it to `CANCELLED` — but this cancellation is rejected with `ERR_HAS_DEPENDENCIES` if any reservation referencing the policy is currently in `APPROVED` or `CHECKED_IN`.

Independently, a boater may purchase a `TowAssistContract`. The contract carries a `tier` of either `BASIC` or `PREMIUM`. A new contract is created in `ACTIVE` status — the only tow-contract status in this version, a single-state lifecycle reserved for future evolution — and its `tows_remaining` counter starts at 2 for `BASIC` or at -1 for `PREMIUM`, where -1 is a sentinel meaning unlimited. Tow events are recorded by a `DockMaster`, drawing down the counter when appropriate; see §3.8.

### 3.3. Slip Inventory

A `DockMaster` provisions the slip inventory. Each slip carries a human label `code` that is unique within its marina, three dimensional measurements (`length_feet`, `beam_feet`, `depth_feet`) in feet at one decimal place, a `flat_daily_charge_cents` flat per-day rent for occupying that specific slip, and a boolean `liveaboard_allowed` (defaulting to false) that gates whether the slip can host liveaboard reservations. A slip is born with a `status` of `AVAILABLE`. Operators may transition a slip's status — to `MAINTENANCE` while the berth is being worked on or to `RETIRED` once it is permanently out of service — by patching the slip; the status patch is one of the system's true partial-update mutations and is subject to the optimistic concurrency contract from §2.6, requiring an `If-Match` header that equals the slip's current `version`. Two simultaneous status patches against the same slip serialize first-writer-wins; the loser receives `ERR_VERSION_CONFLICT`. Slips in `MAINTENANCE` or `RETIRED` cannot host new approvals, accept transfers, or serve as tow destinations.

### 3.4. Reservation Lifecycle from Draft to Settlement

Creating a reservation drafts a placeholder. The request body carries the booking `boater_id`, the `vessel_id` to be berthed, the target `slip_id`, the `check_in_date` (inclusive, UTC midnight), the `check_out_date` (exclusive, UTC midnight), an optional `liveaboard` boolean (defaulting to false), and the `insurance_policy_id` of the policy that will cover the term. The reservation is born in `status` `DRAFT`. Its `nights` field is the whole-day difference between `check_out_date` and `check_in_date`; the system rejects any creation request where `check_out_date` is not strictly after `check_in_date` with `ERR_INVALID_DATE_RANGE`. A `Boater` may cancel any of their own reservations while still in `DRAFT` at any time, with no preconditions — the reservation transitions `DRAFT → CANCELLED`.

Approval is the consequential step. A `DockMaster` approves a reservation, advancing it from `DRAFT` to `APPROVED`. The approval endpoint enforces nine independent checks, evaluated in priority order so that the first failure surfaces — the implementation must observe this ordering rather than report whichever check happens to be cheaper to evaluate. Authentication and authorization come first (`ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN`), then path existence (`ERR_NOT_FOUND`), then the state precondition that the reservation is in `DRAFT` (`ERR_INVALID_STATE`). After those four pre-business checks, business safety follows in the order: size-match on length (`ERR_LOA_EXCEEDS_SLIP`), size-match on beam (`ERR_BEAM_BUFFER_VIOLATION`), size-match on draft (`ERR_DRAFT_EXCEEDS_DEPTH`), insurance coverage (`ERR_INSURANCE_LAPSED`), liveaboard policy (`ERR_LIVEABOARD_POLICY_VIOLATION`), then liveaboard quota (`ERR_LIVEABOARD_QUOTA_EXCEEDED`), and finally the overlap check on the slip (`ERR_SLIP_OCCUPIED`).

The three size-match preconditions translate directly to physical fit. The slip's `length_feet` must be at least the vessel's `loa_feet`; if the vessel is longer than the slip can berth, approval is rejected with `ERR_LOA_EXCEEDS_SLIP`. The slip's `beam_feet` must be at least two feet greater than the vessel's `beam_feet`, reserving a two-foot buffer on each side for fenders and ingress; a beam violation is rejected with `ERR_BEAM_BUFFER_VIOLATION`. The slip's `depth_feet` must be at least the vessel's `draft_feet`; if the vessel sits too deep for the slip, approval is rejected with `ERR_DRAFT_EXCEEDS_DEPTH`. The same three size-match checks govern the slip-transfer offer endpoint described in §3.7, and the rejection codes are the same there.

The slip must also be currently `AVAILABLE` — a slip in `MAINTENANCE` or `RETIRED` cannot host a new approval — and the referenced insurance policy must be in `ACTIVE` `status` with its coverage window covering the reservation's term, meaning the policy's `effective_date` is at or before `check_in_date` and its `expiration_date` is at or after `check_out_date`. A policy whose status is anything other than `ACTIVE`, or whose coverage window does not span the term, yields `ERR_INSURANCE_LAPSED`.

If the reservation is a liveaboard one, the chosen slip must have `liveaboard_allowed` set to true, the vessel must have a non-null `holding_tank_gallons`, and the marina's `liveaboard_active_count` must be strictly less than its `liveaboard_quota` at the moment of approval. A liveaboard reservation against a slip that does not permit liveaboard occupancy, or against a vessel with no holding tank capacity recorded, is rejected with `ERR_LIVEABOARD_POLICY_VIOLATION`; a liveaboard reservation that would push the marina to or beyond its quota is rejected with `ERR_LIVEABOARD_QUOTA_EXCEEDED`. When two `DockMaster` callers race to approve liveaboard reservations such that only one of them fits under the quota, the operations serialize first-writer-wins on the count, the winning approval transitions and the count moves; the losing approval receives `ERR_LIVEABOARD_QUOTA_EXCEEDED`.

Finally, the slip must be free during the term. No other reservation on the same slip with `status` `APPROVED` or `CHECKED_IN` may overlap the half-open window `[check_in_date, check_out_date)`. Two reservations on the same slip whose windows touch only at the boundary (one's `check_out_date` equal to the other's `check_in_date`) do not overlap and both may be approved. Two `DockMaster` callers racing to approve overlapping reservations on the same slip serialize first-writer-wins on the `DRAFT → APPROVED` transition; the loser receives `ERR_SLIP_OCCUPIED`.

When approval succeeds, the system computes the forward-looking reservation total and stores it on the reservation's `estimated_total_cents`; the formula is described in §3.5. If the reservation is a liveaboard one, the marina's `liveaboard_active_count` is incremented by one as part of the same transition, and the marina's `updated_at` and `version` are refreshed.

Check-in advances `APPROVED` to `CHECKED_IN`. A `DockMaster` performs it, and the only precondition beyond state is that the marina's `current_date` is at or after `check_in_date` — early arrivals must wait for the clock to roll forward before they can step off the dock.

Check-out advances `CHECKED_IN` to `CHECKED_OUT`. A `DockMaster` performs it. The marina's `current_date` must again be at or after `check_in_date`, and all pump-out jobs that reference this reservation must already be in `COMPLETED` or `CANCELLED` — a still-`SCHEDULED` pump-out blocks check-out with `ERR_HAS_DEPENDENCIES`. On success, the system computes the chronological reservation total and stores it on `final_total_cents` (see §3.5), and, only when the reservation's `liveaboard` flag is true, runs the utility settlement (see §3.6). If the reservation is a liveaboard one, the marina's `liveaboard_active_count` is decremented by one, and the marina's `updated_at` and `version` are refreshed. Once a slip's reservation completes, any `QUEUED` waitlist entry whose `[requested_check_in, requested_check_out)` window is now satisfied by the freed window becomes a promotion candidate at the next ops sweep.

A `Boater` may cancel their own reservation directly. From `DRAFT` the cancel is unconditional; from `APPROVED` the only block is `ERR_HAS_DEPENDENCIES` when a `SCHEDULED` pump-out job still references the reservation. Cancellation from `APPROVED` on a liveaboard reservation decrements `liveaboard_active_count` by one and refreshes the marina's `updated_at` and `version`. There is no cancel transition from `CHECKED_IN` — once aboard, the only path forward is check-out.

If the marina clock advances and an `APPROVED` reservation has not been checked in by a full day past its `check_in_date`, the next ops sweep transitions the reservation to `EXPIRED`. The same liveaboard decrement and marina version bump apply if the expired reservation was a liveaboard one. `CHECKED_OUT`, `CANCELLED`, and `EXPIRED` are terminal.

### 3.5. Pricing: Forward-Looking Estimate vs. Chronological Final

Two distinct calculations produce two distinct totals on the reservation: a forward-looking `estimated_total_cents` set at approval, and a chronological `final_total_cents` set at check-out. They share the same per-night ingredients but differ in how the season multiplier is applied across the term.

Seasons are determined by month. The peak season covers June, July, and August and applies a multiplier of 1.50 (one and a half times the base rate). The shoulder season covers April, May, September, and October and applies a multiplier of 1.20. Every other month is the off-season and applies a multiplier of 1.00. The system holds three constants of business consequence: a liveaboard surcharge of 1500 cents per night (fifteen dollars per day), a kilowatt-hour rate of 18 cents, and a water rate of 4 cents per gallon.

The per-night raw amount is built from three additive ingredients. The first is the marina's `base_daily_rate_cents` multiplied by the vessel's `loa_feet` and then multiplied by the season multiplier for that night. The second is the slip's `flat_daily_charge_cents`, a constant added on top regardless of vessel size or season. The third, applied only when the reservation's `liveaboard` flag is true, is the liveaboard surcharge of 1500 cents. The sum of these three is the raw per-night amount; it is then rounded half-up to a whole number of cents to yield the per-night charge.

The forward-looking calculation runs at approval. It looks up the season multiplier for `check_in_date` and freezes it; every night in the term is priced using that same multiplier, regardless of whether the term crosses a season boundary. The per-night charge is computed once with the frozen multiplier, rounded half-up to a whole cent, and then multiplied exactly by the integer `nights` to produce `estimated_total_cents`. By construction this estimate is a forward-looking projection — if a reservation starts in shoulder May at 1.20 and runs into peak June, the estimate continues to apply the 1.20 multiplier to the June nights.

The chronological calculation runs at check-out. It walks every night date in `[check_in_date, check_out_date)` in ascending chronological order, looks up that night's season multiplier, computes the raw per-night amount for that night (`base_daily_rate_cents` times `loa_feet` times that night's multiplier, plus `flat_daily_charge_cents`, plus the 1500-cent surcharge when `liveaboard` is true), rounds it half-up to a whole cent, and adds it to a running total. The accumulated total is `final_total_cents`. A term that crosses a season boundary therefore produces a different number than the forward-looking estimate — the chronological calculation accurately reflects the actual season blend, while the forward-looking estimate is the price the boater saw at approval.

Both calculations are integer-cent arithmetic throughout; rounding happens once per night at the per-night step, never on the running total.

### 3.6. Liveaboard Utilities

When the `liveaboard` flag on a reservation is true, the marina records electricity and water consumption against the reservation as utility readings, and produces a single utility settlement at check-out.

A utility reading is an append-only entry created by a `DockMaster` against a reservation. Each reading carries `read_at` (the UTC instant of the meter read), `kwh_delta` (whole kilowatt-hours consumed since the previous reading, never negative), `water_gallons_delta` (whole gallons consumed since the previous reading, never negative), and a server-controlled `applied_in_settlement` flag that defaults to false. Readings are immutable once written.

A scheduled pump-out job (see §3.8) interacts with this ledger: when a pump-out job on a liveaboard reservation completes, the system appends a synthetic utility reading at `read_at` equal to the job's `scheduled_end`, with `water_gallons_delta` equal to the job's `tank_gallons_drained` and `kwh_delta` equal to zero. This keeps the chronological utility ledger consistent with sewage flow.

The settlement runs as part of the check-out transition, only when the reservation's `liveaboard` is true. It selects every utility reading on the reservation whose `read_at` falls in `[check_in_date, Marina.current_date)` and whose `applied_in_settlement` is false, sorted ascending first by `read_at` and tie-broken by `id`. From those readings it sums `kwh_delta` into `kwh_total` and sums `water_gallons_delta` into `water_gallons_total`. The kilowatt-hour charge is `kwh_total` multiplied by 18 cents; the water charge is `water_gallons_total` multiplied by 4 cents. If `water_gallons_total` is strictly greater than zero, a flat sewage charge of 2500 cents (twenty-five dollars) is added; otherwise the sewage charge is zero. The settlement's `total_cents` is the sum of the kilowatt-hour charge, the water charge, and the sewage charge. All four amounts (`kwh_total`, `water_gallons_total`, `sewage_charge_cents`, and `total_cents`) are recorded on the resulting `UtilitySettlement` record along with the settlement window's `window_start` (`check_in_date`) and `window_end` (the marina's `current_date` at check-out). Every reading included in the settlement is then flagged with `applied_in_settlement` set to true so it cannot double-count if any further settlement is ever produced. Rates are whole-cent constants, so no rounding is required.

A non-liveaboard reservation produces no utility settlement at check-out.

### 3.7. The Waitlist and Slip Transfers

When every suitable slip is occupied for the dates a boater wants, the boater appends themselves to the marina's waitlist. The request carries `boater_id`, `vessel_id`, `requested_check_in`, `requested_check_out`, and an optional `liveaboard` boolean. The system rejects any waitlist creation where `requested_check_out` is not strictly after `requested_check_in` with `ERR_INVALID_DATE_RANGE`. The new entry receives a `sequence_no` assigned atomically — a monotonic integer unique within the marina that determines queue order. When two boaters create waitlist entries at the same instant, both succeed; each receives a distinct `sequence_no` from the marina-scoped sequence counter. The loser of any If-Match version race on a mutable resource (a slip status patch, for example) would receive `ERR_VERSION_CONFLICT`; waitlist creation itself does not contend on `If-Match` because entries are append-only. The new entry's `status` is `QUEUED`, its `promoted_reservation_id` is unset, and it carries only `id` and `created_at` from the common-fields set — no `updated_at` and no `version`. A `Boater` may cancel their own queued entry at any time, transitioning it to `CANCELLED`.

The slip-match selector runs as part of the ops sweep. It walks queued entries on the marina in ascending `sequence_no` order, breaking sequence ties on entry `id` ascending. For each entry it computes the candidate slip set: the slip must belong to this marina, its `status` must be `AVAILABLE`, its `length_feet` must be at least the vessel's `loa_feet`, its `beam_feet` minus two feet must be at least the vessel's `beam_feet`, its `depth_feet` must be at least the vessel's `draft_feet`, and no reservation on this slip in `APPROVED` or `CHECKED_IN` may overlap the entry's `[requested_check_in, requested_check_out)`. If the entry's `liveaboard` is true, the slip must additionally have `liveaboard_allowed` set to true and the marina's `liveaboard_active_count` must be strictly less than its `liveaboard_quota`. Among the eligible candidates, the selector picks the one with the tightest fit, comparing four ranking keys lexicographically in this order: first, the slip's `length_feet` minus the vessel's `loa_feet` (smallest first — tightest length fit); next, the slip's `beam_feet` minus the vessel's `beam_feet` (smallest first — tightest beam fit, no buffer subtraction here, the buffer was already enforced in eligibility); next, the slip's `depth_feet` minus the vessel's `draft_feet` (smallest first — shallowest extra depth); and last, the slip's `code` in ascending lexicographic order as the deterministic tie-breaker. If no candidate exists the entry remains `QUEUED`; otherwise a new reservation is created in `APPROVED` `status` on the chosen slip for the entry's requested dates, the `estimated_total_cents` on the new reservation is computed with the forward-looking formula at the chosen slip's pricing, the waitlist entry transitions to `PROMOTED`, and its `promoted_reservation_id` is set to the new reservation's `id`. If the entry's `requested_check_out` has been reached or passed by the marina clock at sweep time and no promotion was possible, the entry transitions to `EXPIRED` in the same sweep.

A boater who is already berthed but wants to move can submit a slip transfer request. The request carries the source `reservation_id` (the reservation the boater wants to move from) and the `desired_slip_id`. The request is born in `status` `REQUESTED`. A `DockMaster` reviews it and, if the move is acceptable, transitions it to `OFFERED`: the desired slip must currently be `AVAILABLE`, must size-match the source reservation's vessel by the same three checks used in approval (with the same three rejection codes: `ERR_LOA_EXCEEDS_SLIP`, `ERR_BEAM_BUFFER_VIOLATION`, `ERR_DRAFT_EXCEEDS_DEPTH`), must not host any `APPROVED` or `CHECKED_IN` reservation overlapping the remaining term (otherwise `ERR_SLIP_OCCUPIED`), and on success the system sets `offer_expires_at` to the marina's `current_date` plus twenty-four hours.

The boater then has the offer for twenty-four marina-clock hours. Accepting an offer transitions `OFFERED` to `ACCEPTED`: the marina's `current_date` must be strictly less than `offer_expires_at`, the desired slip must still be `AVAILABLE`, and on success the source reservation's `slip_id` is updated to `desired_slip_id` and its `estimated_total_cents` is recomputed using the new slip's `flat_daily_charge_cents` (the season multiplier is re-frozen against the original `check_in_date` to preserve the forward-looking semantics). Two operations racing to acquire the desired slip — a boater accepting the transfer offer while a `DockMaster` simultaneously patches that slip to `MAINTENANCE` — serialize first-writer-wins on the slip's `status`; exactly one operation succeeds and the loser receives `ERR_INVALID_STATE`. Declining an offer transitions `OFFERED` to `DECLINED` with no preconditions. A boater can re-queue a declined request, transitioning `DECLINED` back to `REQUESTED`, provided the source reservation is still in `APPROVED` or `CHECKED_IN`. If the offer expires unaccepted — the marina clock has reached or passed `offer_expires_at` — the next ops sweep transitions it to `EXPIRED`. `ACCEPTED` and `EXPIRED` are terminal.

### 3.8. Pump-Out Service and Tow Assistance

Liveaboard and long-stay boaters periodically need their holding tank pumped. A pump-out job is scheduled against a `CHECKED_IN` reservation by a `Boater` (for their own reservation) or a `DockMaster`. The request carries the `reservation_id`, a `scheduled_start`, and a `scheduled_end`; the job is born in `status` `SCHEDULED`. Two pump-out jobs on the same slip whose windows — expressed as the open-start, closed-end form `(scheduled_start, scheduled_end]` — share any instant cannot both be scheduled; the second attempt is rejected with `ERR_PUMP_OUT_CONFLICT`. A boater or `DockMaster` may cancel a `SCHEDULED` job at any time, transitioning it to `CANCELLED`. A `DockMaster` completes a `SCHEDULED` job by supplying `tank_gallons_drained` (which must be strictly greater than zero); the marina's `current_date` must be at or after `scheduled_start`. On completion, the job transitions to `COMPLETED` and — only when the parent reservation's `liveaboard` is true — a synthetic utility reading is appended as described in §3.6.

A `DockMaster` records tow events against a boater's tow contract. The recorded event is owned by its parent contract and carries that contract's id in its `contract_id` field. The request body carries `occurred_at`, a free-text `from_position`, and the `to_slip_id` of the destination slip. The destination slip must be `AVAILABLE`; otherwise the recording is rejected with `ERR_TOW_DEST_UNAVAILABLE`. The event's `charge_cents` and the contract's `tows_remaining` are then resolved per tier: if the contract's `tier` is `PREMIUM`, `charge_cents` is 0 and `tows_remaining` is unchanged at its -1 sentinel; if the `tier` is `BASIC` and `tows_remaining` is strictly greater than zero, `charge_cents` is 0 and `tows_remaining` is decremented by one; otherwise — the `tier` is `BASIC` and `tows_remaining` is zero — `charge_cents` is set to 25000 cents (a flat two-hundred-fifty-dollar fee) and `tows_remaining` stays at zero.

### 3.9. Concurrency Summary

Four serialization points have already been described in context, and they are summarized here for reinforcement. First, two `DockMaster` callers attempting to approve overlapping reservations on the same slip serialize first-writer-wins on the `DRAFT → APPROVED` transition for that slip and overlap window; the loser receives `ERR_SLIP_OCCUPIED`. Second, two simultaneous liveaboard approvals where the marina would exceed `liveaboard_quota` serialize first-writer-wins on the `liveaboard_active_count` increment; the loser receives `ERR_LIVEABOARD_QUOTA_EXCEEDED`. Third, a boater accepting a transfer offer while a `DockMaster` patches the desired slip to `MAINTENANCE` serialize first-writer-wins on the slip's `status`; the loser receives `ERR_INVALID_STATE`. Fourth, any partial-update or full-replacement mutation whose `If-Match` header does not match the stored `version` is rejected with `ERR_VERSION_CONFLICT`; concurrent waitlist creations both succeed and each receives a distinct `sequence_no` from the marina-scoped counter.

## 4. Endpoint Definitions

Resource creation endpoints return HTTP 201; all other operations — state transitions, reads, list queries, slip status patches, the test-driving clock advance, and the ops sweep — return HTTP 200. All non-2xx outcomes follow the error envelope in §2.2 with one of the `error_id` strings in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /marinas | Create a marina | DockMaster, BillingClerk |
| GET | /marinas/:marina_id | Get a marina | DockMaster, BillingClerk, Boater |
| POST | /marinas/:marina_id/_clock/advance | Advance the marina logical clock to a supplied instant (test-driving) | DockMaster |
| POST | /marinas/:marina_id/_ops/run | Run the ops batch tick (expire policies, expire stale approvals, expire offers, promote and expire waitlist entries) | DockMaster |
| POST | /marinas/:marina_id/boaters | Create a boater | DockMaster |
| GET | /marinas/:marina_id/boaters/:boater_id | Get a boater | DockMaster, BillingClerk, Boater |
| POST | /marinas/:marina_id/boaters/:boater_id/vessels | Create a vessel for a boater | Boater, DockMaster |
| GET | /marinas/:marina_id/vessels/:vessel_id | Get a vessel | Boater, DockMaster, BillingClerk |
| POST | /marinas/:marina_id/slips | Create a slip | DockMaster |
| GET | /marinas/:marina_id/slips/:slip_id | Get a slip | DockMaster, BillingClerk, Boater |
| PATCH | /marinas/:marina_id/slips/:slip_id/status | Change slip status (e.g., MAINTENANCE or RETIRED) | DockMaster |
| POST | /marinas/:marina_id/reservations | Create a reservation in DRAFT | Boater, DockMaster |
| GET | /marinas/:marina_id/reservations/:reservation_id | Get a reservation | DockMaster, BillingClerk, Boater |
| GET | /marinas/:marina_id/reservations | List reservations with optional status, slip_id, boater_id filters | DockMaster, BillingClerk |
| POST | /marinas/:marina_id/reservations/:reservation_id/approve | Approve a reservation (DRAFT to APPROVED) | DockMaster |
| POST | /marinas/:marina_id/reservations/:reservation_id/check-in | Check in (APPROVED to CHECKED_IN) | DockMaster |
| POST | /marinas/:marina_id/reservations/:reservation_id/check-out | Check out (CHECKED_IN to CHECKED_OUT) | DockMaster |
| POST | /marinas/:marina_id/reservations/:reservation_id/cancel | Cancel a reservation (DRAFT or APPROVED to CANCELLED) | Boater, DockMaster |
| POST | /marinas/:marina_id/waitlist | Create a waitlist entry in QUEUED | Boater |
| GET | /marinas/:marina_id/waitlist/:waitlist_id | Get a waitlist entry | Boater, DockMaster |
| POST | /marinas/:marina_id/waitlist/:waitlist_id/cancel | Cancel a queued waitlist entry (QUEUED to CANCELLED) | Boater |
| POST | /marinas/:marina_id/transfer-requests | Create a slip transfer request in REQUESTED | Boater |
| POST | /marinas/:marina_id/transfer-requests/:request_id/offer | Offer a slip transfer (REQUESTED to OFFERED) | DockMaster |
| POST | /marinas/:marina_id/transfer-requests/:request_id/accept | Accept a transfer offer (OFFERED to ACCEPTED) | Boater |
| POST | /marinas/:marina_id/transfer-requests/:request_id/decline | Decline a transfer offer (OFFERED to DECLINED) | Boater |
| POST | /marinas/:marina_id/transfer-requests/:request_id/requeue | Re-queue a declined transfer request (DECLINED to REQUESTED) | Boater |
| POST | /marinas/:marina_id/pump-out-jobs | Schedule a pump-out job against a checked-in reservation | Boater, DockMaster |
| POST | /marinas/:marina_id/pump-out-jobs/:job_id/complete | Complete a pump-out job (SCHEDULED to COMPLETED) | DockMaster |
| POST | /marinas/:marina_id/pump-out-jobs/:job_id/cancel | Cancel a scheduled pump-out job (SCHEDULED to CANCELLED) | Boater, DockMaster |
| POST | /marinas/:marina_id/reservations/:reservation_id/utility-readings | Append a utility reading (kWh and water meter) | DockMaster |
| GET | /marinas/:marina_id/reservations/:reservation_id/utility-settlement | Get the utility settlement for a reservation | DockMaster, BillingClerk, Boater |
| POST | /marinas/:marina_id/boaters/:boater_id/policies | Create an insurance policy | Boater, DockMaster |
| GET | /marinas/:marina_id/policies/:policy_id | Get an insurance policy | Boater, DockMaster, BillingClerk |
| POST | /marinas/:marina_id/policies/:policy_id/cancel | Cancel an insurance policy (ACTIVE to CANCELLED) | Boater, DockMaster |
| POST | /marinas/:marina_id/boaters/:boater_id/tow-contracts | Create a tow-assist contract | Boater, DockMaster |
| GET | /marinas/:marina_id/tow-contracts/:contract_id | Get a tow-assist contract | Boater, DockMaster, BillingClerk |
| POST | /marinas/:marina_id/tow-contracts/:contract_id/tow-events | Record a tow event | DockMaster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_LOA_EXCEEDS_SLIP | 422 |
| ERR_BEAM_BUFFER_VIOLATION | 422 |
| ERR_DRAFT_EXCEEDS_DEPTH | 422 |
| ERR_INSURANCE_LAPSED | 422 |
| ERR_LIVEABOARD_POLICY_VIOLATION | 422 |
| ERR_LIVEABOARD_QUOTA_EXCEEDED | 409 |
| ERR_SLIP_OCCUPIED | 409 |
| ERR_PUMP_OUT_CONFLICT | 409 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_HAS_DEPENDENCIES | 409 |
| ERR_TOW_DEST_UNAVAILABLE | 422 |
| ERR_BAD_REQUEST | 400 |
