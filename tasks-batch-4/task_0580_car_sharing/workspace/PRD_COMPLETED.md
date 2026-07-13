# Car Sharing API — Product Requirements Document

## 1. Introduction

This document specifies the Car Sharing API, a peer-to-peer marketplace platform in the spirit of services such as Turo and Getaround. On one side of the market are **hosts**, individuals who list their personal vehicles, publish an availability calendar, and set nightly prices that may vary by date. On the other side are **guests**, who prove their driving eligibility, browse listings, and book trips for a range of nights. Wrapping the two is a platform operator that verifies guests, curates protection-plan tiers, adjudicates damage claims, and settles the money that flows between the parties.

The core difficulty of the domain is that a single booking sets in motion a long chain of interdependent obligations. A trip reserves calendar nights, quotes a price against pricing rules that were in effect at the moment of booking, provisionally reserves host earnings, and — once the car is driven and returned — reconciles that estimate against what actually happened on the road: miles driven beyond the included allowance, fuel returned below the level at pickup, and time held past the return deadline. Damage claims, protection-plan deductibles, host payouts, and guest risk scoring all layer additional monetary and state-machine consequences on top. The system must keep every ledger internally consistent at every step, so this specification is precise about the order in which validations run, how money moves when a state changes, and how concurrent edits to a shared vehicle or host balance are rejected rather than silently applied.

All money in this system is denominated in integer **cents**; all calendar values are dates or timestamps interpreted against a server-controlled logical clock rather than real wall-clock time. The sections below define the global contract every endpoint honors (§2), the business workflows that make up the marketplace (§3), the full endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that hold across every endpoint. Most of it is contract-level: response shape, pagination, identity, precision, concurrency, and the fixed order in which a request is validated.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH_HEADER`. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Anonymous`, `Host`, `Guest`, and `PlatformAdmin`.

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque self-signup identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Anonymous` surface exists solely so that a prospective host or guest can register before they own any record.
- When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host`. Ownership checks on any resource that references a host compare that resource's host foreign key to `X-User-ID`: a host owns a `Vehicle` whose `host_id` equals `X-User-ID`, and transitively owns a `Trip` whose `vehicle_id` points at a vehicle the host owns, as well as that vehicle's availability blocks, pricing rules, extensions, and claims.
- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`. A guest owns a `Trip` whose `guest_id` equals `X-User-ID`, and by extension that trip's check-in/check-out actions, extension requests, and guest-filed claims.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but does not compare it to any entity's `id`. The platform operator verifies guests, manages protection plans, adjudicates claims, settles payouts, and controls the logical clock.

An ownership violation — an `entity_backed` principal acting on a resource it does not own — is rejected with `ERR_OWNERSHIP_VIOLATION`, distinct from a role-level permission failure.

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

List endpoints are paginated through two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many leading items are skipped and defaults to 0. A supplied `limit` below 1 or above 100 is clamped into that range and a negative `offset` is clamped to 0; a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, every list is sorted by each resource's creation timestamp in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources share a common set of system-managed fields. Every `Host`, `Guest`, `Vehicle`, `AvailabilityBlock`, `PricingRule`, `Trip`, `InspectionReport`, `Claim`, `Extension`, and `Payout` carries:

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation.
- `version` — an integer that starts at its initial value and increments by one on every mutation of the resource. It underpins the optimistic concurrency control described in §2.7.

The one exception is the `ProtectionPlan`. A protection plan is effectively immutable configuration once created, so it carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field.

### 2.5. Nested Resource Existence and Left-to-Right Path Validation

Many operations name more than one resource — some by a path identifier, some by a field in the request body. The system resolves every referenced identifier and rejects the request with the specific not-found error for the **first** identifier, read left to right (path before body), that does not correspond to an existing record. The per-entity codes are `ERR_HOST_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_PRICING_RULE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`, and `ERR_PAYOUT_NOT_FOUND`. For example, filing a claim against a trip that does not exist fails with `ERR_TRIP_NOT_FOUND` before the body is inspected.

If the body itself is malformed — not valid JSON, missing a required field, or carrying a value of the wrong type or an invalid enum member — the request is rejected with `ERR_VALIDATION`.

### 2.6. Monetary Amounts, Dates, and the Logical Clock

All monetary fields are integer **cents**; no fractional cents ever appear. Where a calculation multiplies by a fractional rate (a discount percentage, a host-earnings fraction, or the late-fee multiplier), the result is truncated toward zero to whole cents — a floor — at the point the specification names it, never rounded to the nearest cent and never carried as a decimal. Each calculation in §3 states exactly where a floor is applied.

Dates are `YYYY-MM-DD` strings. A trip's date span and an availability block's date span are **half-open**: the interval runs from `start_date` inclusive to `end_date` exclusive, and the number of `nights` equals `end_date` minus `start_date` in whole days. A pricing rule's date span is **closed**: both its `start_date` and its `end_date` are inclusive, so a rule covers every date from the first through the last.

Time-of-day reasoning uses a server-controlled **logical clock** rather than real wall-clock time. Before any client sets it, the clock reads `2026-05-01T00:00:00Z`. A `PlatformAdmin` may advance it by supplying a `to_iso8601` instant; this admin-only test-driving capability moves the logical clock to the supplied value and is the only source of "now" the system consults — for stamping `recorded_at` on inspection reports, for setting a trip's `actual_return_at` at check-out, and for measuring return lateness at check-out by comparing that `actual_return_at` against the trip's `scheduled_return_at`. Guest verification performs no license-expiry comparison against the clock; the verify transition simply advances the status.

### 2.7. Optimistic Concurrency Control

Two write operations act against a shared parent whose state another actor may have changed between the moment a client read it and the moment the client writes. Both use optimistic concurrency control keyed on the parent's `version`.

Booking a trip is a write against the target `Vehicle`. The request must carry `expected_vehicle_version`, the `version` the guest observed when it quoted price and availability. If that value does not equal the vehicle's current `version` — because the host has since edited the vehicle, changed a listing state, or another guest's booking advanced it — the guest's view is stale and the booking is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412), forcing a re-quote rather than a commit against outdated terms.

Requesting a payout is a write against the paying `Host`. The request must carry `expected_host_version`, the `version` the client observed when it read the host ledger. If another payout or a trip or claim settlement has mutated the host ledger since — advancing the host's `version` — then `expected_host_version` no longer matches the host's current `version`, and the request is rejected with `ERR_STALE_HOST_VERSION` (HTTP 412) so the draw can be recomputed against a fresh balance. No other endpoint takes a version field; only booking and payout creation carry this check.

### 2.8. Cascading State Propagation and the Host Ledger

A single state transition frequently mutates several resources at once, and every one of those secondary effects is part of the contract. When a resource is mutated by such a cascade, its `updated_at` is refreshed and its `version` increments just as for a direct edit.

The host ledger is the most heavily cascaded structure. A `Host` carries five running totals, all in cents: `pending_balance_cents` (earnings reserved by trips that are `CONFIRMED` or `CHECKED_IN`), `available_balance_cents` (finalized earnings a host may withdraw), `reserved_payout_cents` (funds locked by payouts that are `REQUESTED` but not yet paid or failed), `lifetime_earnings_cents` (cumulative finalized earnings from completed trips plus claim recoveries), and `lifetime_paid_cents` (cumulative amount actually paid out). These totals obey a conservation rule: `lifetime_earnings_cents` always equals `available_balance_cents` plus `reserved_payout_cents` plus `lifetime_paid_cents`, and neither `available_balance_cents` nor `reserved_payout_cents` ever drops below zero. Guest-borne deductions are the guest's obligation and are never counted as host earnings.

Two aggregate totals are compensating by design. A host's `pending_balance_cents` is the sum of `estimated_host_earnings_cents` across that host's trips currently in `CONFIRMED` or `CHECKED_IN`; approving a trip credits that estimate and cancelling the same confirmed trip debits the identical amount, so an approve-then-cancel round trip returns the balance to its pre-approval value. Likewise a vehicle's `booked_night_count` is the sum of `nights` across that vehicle's `BOOKED` availability blocks that are still `ACTIVE`; a booking adds its nights and a cancellation releases the block out of the sum, so a book-then-cancel round trip returns the count to its pre-booking value.

### 2.9. The Order of Request Validation

When several checks could reject the same request, they are evaluated in a fixed priority so that the returned error is deterministic. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_MISSING_AUTH_HEADER`.
2. **Authorization** — the role must be permitted for the operation per §2.1 and the §4 table, else `ERR_UNAUTHORIZED`.
3. **Existence** — every referenced identifier must resolve, left to right, else the corresponding not-found error from §2.5.
4. **Ownership** — an `entity_backed` actor must own the target resource, else `ERR_OWNERSHIP_VIOLATION`.
5. **Concurrency** — where an OCC field applies, `expected_vehicle_version` or `expected_host_version` must match the parent's current `version`, else `ERR_STALE_VEHICLE_VERSION` or `ERR_STALE_HOST_VERSION`.
6. **State** — the target (and any cross-entity prerequisite) must be in a state that permits the transition, else `ERR_INVALID_STATE` or one of the specific state errors `ERR_GUEST_NOT_VERIFIED`, `ERR_VEHICLE_NOT_LISTED`, `ERR_TRIP_NOT_CLAIMABLE`, or `ERR_HOST_SUSPENDED`.
7. **Value and format constraints** — field-level constraints such as date ranges, odometer monotonicity, fuel bounds, claim amounts, trip length, and payout minimums, each yielding its specific 422 error.
8. **Temporal availability** — the requested window must not collide with an existing occupation, else `ERR_DATES_UNAVAILABLE` or `ERR_PRICING_RULE_OVERLAP`.
9. **Uniqueness and linkage** — open-record uniqueness, else `ERR_DUPLICATE_OPEN_CLAIM` or `ERR_DUPLICATE_OPEN_EXTENSION`.
10. **Fiscal** — a payout must not exceed the available balance, else `ERR_INSUFFICIENT_BALANCE`.

A check earlier in this list always masks a later one: if a host is suspended (a level-6 state failure) at the same time its balance is insufficient (a level-10 fiscal failure), the request surfaces the state failure. The subsections of §3 place each concrete check next to the workflow it guards; this ordering is what disambiguates which error wins when more than one applies.

## 3. Business Logic & Workflows

### 3.1. Hosts, Vehicle Listings, and the Availability Calendar

A host joins the marketplace by registering with a `name`, an `email`, and an optional `payout_method_ref` (an opaque token naming where money should be sent; it defaults to null). A newly registered host is `ACTIVE`, and all five ledger totals start at zero. A host may later be moved to `SUSPENDED` by the platform operator and back to `ACTIVE` by reinstatement; suspension is a bar on new payout activity (see §3.9) but leaves existing trips and bookings untouched. Reading a host returns the full ledger.

A host lists a car by creating a `Vehicle` and supplying `host_id` (which must equal the acting host), `make`, `model`, `year`, `base_daily_price_cents`, and `location_city`. Three optional knobs may be set at creation and otherwise take their defaults: `daily_mileage_limit` (included miles per night before overage, default 200), `weekly_discount_pct` (the fraction off the rental subtotal for medium-length trips, default 0.10), `monthly_discount_pct` (the fraction off for long trips, default 0.25), and `odometer_current` (the car's present odometer reading, default 0). A vehicle also tracks two computed counters, `booked_night_count` and `completed_trip_count`, both starting at zero. A new vehicle begins in `DRAFT`.

A host may edit a vehicle's pricing and configuration — any of `base_daily_price_cents`, `daily_mileage_limit`, `weekly_discount_pct`, `monthly_discount_pct`, `location_city`, or `odometer_current` — while it exists; each such edit increments the vehicle's `version` by one, which is exactly what can invalidate a guest's in-flight quote (§2.7). A vehicle moves through a small state machine driven by the owning host: listing it advances `DRAFT → LISTED` or `SNOOZED → LISTED` and makes it bookable; snoozing advances `LISTED → SNOOZED` while leaving existing bookings valid; and unlisting advances `LISTED → UNLISTED` or `SNOOZED → UNLISTED`, a terminal state. Every one of these transitions requires that the acting host own the vehicle and increments the vehicle's `version` by one. Unlisting additionally requires that no `ACTIVE` `BOOKED` availability block exist on the vehicle; if one does, the unlist attempt is refused with `ERR_INVALID_STATE`. A transition requested from a state the machine does not permit — for instance, snoozing a `DRAFT` vehicle — is likewise refused with `ERR_INVALID_STATE`.

The calendar is expressed through `AvailabilityBlock` records. A host blocks off a window on one of its vehicles by supplying a `start_date`, an `end_date`, and an optional `block_type` that is either `HOST_BLOCKED` (the default) or `MAINTENANCE`; the block's `vehicle_id` is taken from the path, its `trip_id` stays null, its `nights` is computed as `end_date` minus `start_date`, and it begins `ACTIVE`. The window must span at least one night (`end_date` strictly after `start_date`), else `ERR_INVALID_DATE_RANGE`. A requested host block whose window overlaps an existing `ACTIVE` `BOOKED` block on that vehicle under half-open comparison is rejected with `ERR_DATES_UNAVAILABLE`, the same collision guard that protects bookings and extensions. The third `block_type`, `BOOKED`, is never created directly by a host — the system creates a `BOOKED` block on the guest's behalf when a trip is booked, wiring its `trip_id` to the new trip. Host-created and booking-created blocks alike share the same lifecycle: an `ACTIVE` block becomes `RELEASED` when its owning trip is cancelled or declined (or when the host removes the block), and an `ACTIVE` block becomes `CONSUMED` when its owning trip checks out. Releasing a `BOOKED` block removes its nights from the vehicle's `booked_night_count`. Blocks may be read individually or listed and filtered by `vehicle_id`, `trip_id`, or `status`.

### 3.2. Dynamic Pricing Rules

Beyond the flat `base_daily_price_cents`, a host may override the nightly price for specific dates by creating a `PricingRule` naming the `vehicle_id`, a `start_date`, an `end_date`, and the `daily_price_cents` to charge on every covered date. A pricing rule's interval is closed — both endpoints inclusive — and a rule begins `ACTIVE`. The rule's `end_date` must not precede its `start_date` (a single-day rule where the two are equal is permitted), else `ERR_INVALID_DATE_RANGE`. A rule that is no longer in force is `WITHDRAWN` and stops participating in price lookups. Two `ACTIVE` rules may not cover overlapping closed intervals on the same vehicle: a create whose interval overlaps an existing `ACTIVE` rule on that vehicle is rejected with `ERR_PRICING_RULE_OVERLAP`. Pricing rules may be read individually or listed by `vehicle_id`.

When a trip is priced, the nightly price for each date in the trip's half-open span is resolved as follows: if an `ACTIVE` pricing rule on the vehicle has a closed interval containing that date, the rule's `daily_price_cents` applies for that night; otherwise the vehicle's `base_daily_price_cents` applies. This per-night resolution feeds the settlement math in §3.4.

### 3.3. Guest Verification

A guest registers with a `name` and an `email`, and begins with `verification_status` of `UNVERIFIED`, a `driver_risk_score` of 0, an `outstanding_balance_cents` of 0, and the counters `at_fault_claim_count`, `late_return_count`, and `completed_trip_count` all at 0. Booking requires a verified license, so a guest submits verification by providing a `license_number`, a `license_state` (a two-letter jurisdiction), and a `license_expiry_date` (`YYYY-MM-DD`); all three must be present, and on submission they are persisted on the guest and the status advances `UNVERIFIED → PENDING_REVIEW`. The platform operator then either verifies the guest, advancing `PENDING_REVIEW → VERIFIED`, or rejects them, advancing `PENDING_REVIEW → REJECTED` with an optional `reason`. A `REJECTED` guest is not stuck: resubmitting verification overwrites the license fields and advances `REJECTED → PENDING_REVIEW` again, and this reject-resubmit cycle may repeat. `VERIFIED` is terminal. Only a guest whose `verification_status` is `VERIFIED` may book; a booking attempt by any other status fails with `ERR_GUEST_NOT_VERIFIED`.

### 3.4. Booking a Trip and the Estimated Settlement

A verified guest books by creating a `Trip` naming the `vehicle_id`, its own `guest_id`, the chosen `protection_plan_id`, a `start_date`, an `end_date`, and the concurrency token `expected_vehicle_version` described in §2.7. The vehicle must be `LISTED` — a booking against a `DRAFT`, `SNOOZED`, or `UNLISTED` vehicle is rejected with `ERR_VEHICLE_NOT_LISTED` — and the trip window must not overlap any `ACTIVE` `BOOKED` block on that vehicle under half-open comparison, else `ERR_DATES_UNAVAILABLE`. The span must be at least one night (`end_date` strictly after `start_date`), else `ERR_INVALID_DATE_RANGE`, and must not exceed the maximum trip length of 90 nights, else `ERR_TRIP_TOO_LONG`. Among the state-level checks, the guest-verification check is evaluated before the vehicle-listing check, so an unverified guest booking a not-`LISTED` vehicle receives `ERR_GUEST_NOT_VERIFIED`. A new trip enters `REQUESTED`.

A protection plan is platform-curated configuration selected at booking. Each `ProtectionPlan` has a `tier` of `BASIC`, `STANDARD`, or `PREMIUM`; a `deductible_cents` the guest bears per approved claim; a `daily_premium_cents` charged per trip night; a `coverage_limit_cents` capping damage covered per claim; a `host_earnings_pct`, the fraction between 0 and 1 of the discounted rental subtotal the host keeps under this plan; and an `active` flag (default true) indicating whether the plan may be chosen for new trips. Plans may be listed, optionally filtered by `active`, or fetched individually.

At the moment of booking the system locks a full **estimated settlement** onto the trip, assuming an on-time return with no mileage overage and a full tank — so at this stage `mileage_fee_cents`, `fuel_fee_cents`, `late_fee_cents`, and `late_days` are all zero. The estimate is computed as follows. First, `nights` equals `end_date` minus `start_date`. The rental subtotal is the sum, across each night's date in the trip's half-open span, of that night's resolved price (the covering `ACTIVE` pricing rule's `daily_price_cents`, or the vehicle's `base_daily_price_cents` where no rule covers the date, per §3.2). A length discount is then chosen by night count, with the longer threshold taking precedence: if `nights` is at least 28 the monthly discount fraction applies; otherwise if `nights` is at least 7 the weekly discount fraction applies; otherwise the discount is zero. Crucially, the discount is applied to the already-summed subtotal, not to each night individually: `discounted_subtotal_cents` is the floor of the rental subtotal multiplied by one minus the chosen discount fraction. The protection premium, `protection_premium_cents`, is the plan's `daily_premium_cents` times `nights`. The provisional guest charge, `estimated_total_cents`, is `discounted_subtotal_cents` plus `protection_premium_cents`. The provisional host earnings, `estimated_host_earnings_cents`, is the floor of `discounted_subtotal_cents` times the plan's `host_earnings_pct`. Finally `deductible_snapshot_cents` records the plan's `deductible_cents` as of booking, freezing the deductible the guest would owe even if the plan is later reconfigured.

Booking has three immediate side effects beyond persisting the trip: the estimate above is computed and stored; a `BOOKED` `AvailabilityBlock` is created for the trip's window with its `trip_id` set and `status` `ACTIVE`; the vehicle's `booked_night_count` increases by the trip's `nights`; and the vehicle's `version` increments by one. Because booking advances the vehicle's `version`, a second concurrent guest holding the older `expected_vehicle_version` will be turned away at check 5 of §2.9.

The trip also records inspection-derived fields that stay null until check-in and check-out fill them: `checkin_odometer`, `checkin_fuel_pct`, `checkout_odometer`, `checkout_fuel_pct`, and `actual_return_at`. One computed timestamp is fixed at booking: `scheduled_return_at`, the on-time return deadline, is the trip's `end_date` at `T11:00:00Z`. Trips may be read individually or listed and filtered by `vehicle_id`, `guest_id`, `protection_plan_id`, or `status`.

### 3.5. Host Response, Cancellation, and the Pending Ledger

A booking sits in `REQUESTED` until the owning host acts. Approving it advances `REQUESTED → CONFIRMED` and credits the host's `pending_balance_cents` by the trip's `estimated_host_earnings_cents`. Declining it advances `REQUESTED → DECLINED`, releases the linked `BOOKED` block to `RELEASED`, and reduces the vehicle's `booked_night_count` by the trip's `nights`; because a declined trip was never confirmed, there is no pending credit to reverse. Both actions require the acting host to own the trip's vehicle.

Cancellation is available to either party — the guest who owns the trip or the host who owns its vehicle — while the trip is `REQUESTED` or `CONFIRMED`, advancing it to `CANCELLED`. Cancellation drives a two-level cascade: the trip releases its linked `BOOKED` block to `RELEASED` (level one), and that release both reduces the vehicle's `booked_night_count` by the trip's `nights` and — only if the trip was `CONFIRMED` at the moment of cancellation — reduces the host's `pending_balance_cents` by the trip's `estimated_host_earnings_cents` (level two). Cancelling from `REQUESTED` reverses only the night count, because no pending earnings were ever credited. This is the compensating pair described in §2.8: an approve followed by a cancel leaves both the pending balance and the booked-night count exactly where they started. An optional `reason` may accompany a cancellation.

### 3.6. Check-In, Check-Out, and the Final Settlement

Once a trip is `CONFIRMED`, the guest who owns it takes possession by checking in, which advances `CONFIRMED → CHECKED_IN`. Check-in requires that the vehicle not be `UNLISTED`. The guest supplies an `odometer_reading`, a `fuel_level_pct`, and an array of `photo_refs`; the fuel value must lie within 0 to 100 inclusive, else `ERR_INVALID_FUEL_LEVEL`. This creates an `InspectionReport` whose `phase` is `CHECK_IN`, capturing the `odometer_reading`, the `fuel_level_pct`, the `photo_refs`, and a `recorded_at` stamped from the logical clock; the trip copies these into its `checkin_odometer` and `checkin_fuel_pct`.

Returning the car, the guest checks out, advancing `CHECKED_IN → CHECKED_OUT`. Check-out again supplies an `odometer_reading`, a `fuel_level_pct`, and `photo_refs`, and imposes two constraints: the checkout `odometer_reading` must be at least the trip's `checkin_odometer` (a car cannot un-drive miles), else `ERR_INVALID_ODOMETER`, and the `fuel_level_pct` must again be within 0 to 100 inclusive, else `ERR_INVALID_FUEL_LEVEL`. Check-out creates a second `InspectionReport` with `phase` `CHECK_OUT`; sets the trip's `checkout_odometer`, `checkout_fuel_pct`, and `actual_return_at` (the current logical-clock value); consumes the linked `BOOKED` block by moving it to `CONSUMED`; and computes the **final settlement**.

The final settlement reconciles the booking estimate against what actually happened, producing the incidental fees. Miles driven equals `checkout_odometer` minus `checkin_odometer`. Allowed miles equals the vehicle's `daily_mileage_limit` multiplied by the trip's `nights`. Overage miles is the larger of zero and miles driven minus allowed miles — only miles strictly beyond the allowance are charged — and `mileage_fee_cents` is those overage miles multiplied by 50 cents per mile. The fuel deficit is the larger of zero and `checkin_fuel_pct` minus `checkout_fuel_pct`, and `fuel_fee_cents` is that deficit in percentage points multiplied by 500 cents per point. For lateness, the overtime is the difference in seconds between `actual_return_at` and `scheduled_return_at`, less a grace allowance of 2 hours (7,200 seconds); if that overtime is zero or negative there is no lateness and `late_days` is zero, otherwise `late_days` is the overtime seconds divided by 86,400 and rounded up to the next whole day. The `late_fee_cents` is `late_days` multiplied by the floor of the vehicle's `base_daily_price_cents` times a late-fee multiplier of 1.5. The guest's actual charge, `final_total_cents`, is `discounted_subtotal_cents` plus `protection_premium_cents` plus `mileage_fee_cents` plus `fuel_fee_cents` plus `late_fee_cents`. The host's actual earnings, `final_host_earnings_cents`, is `estimated_host_earnings_cents` plus those same three incidental fees — the host keeps the full mileage, fuel, and late charges on top of the locked base earnings. If `late_days` is greater than zero, the guest's `late_return_count` increases by one at check-out.

A `CHECKED_OUT` trip is completed by the owning host, advancing `CHECKED_OUT → COMPLETED`, a terminal state that moves money and updates reputation. The host's ledger shifts the trip out of pending and into finalized: `pending_balance_cents` decreases by the trip's `estimated_host_earnings_cents`, while `available_balance_cents` and `lifetime_earnings_cents` each increase by the trip's `final_host_earnings_cents`. The vehicle's `odometer_current` is set to the trip's `checkout_odometer` and its `completed_trip_count` increases by one. The guest's `completed_trip_count` increases by one and the guest's `driver_risk_score` is recomputed in its finalized form (§3.8). A trip's inspection reports may be listed at any time after they are created.

### 3.7. Extensions

A guest holding a `CONFIRMED` or `CHECKED_IN` trip may request more time by creating an `Extension` naming a `new_end_date`. The extension snapshots the trip's current `end_date` as `previous_end_date`, computes `added_nights` as `new_end_date` minus `previous_end_date`, and starts in `REQUESTED`. The `new_end_date` must be strictly after the trip's current `end_date`, else `ERR_INVALID_DATE_RANGE`. A trip may hold at most one `REQUESTED` extension at a time; a second request while one is still open is rejected with `ERR_DUPLICATE_OPEN_EXTENSION`. Extensions may be read individually or listed by `trip_id`.

The owning host approves or denies. Denial advances `REQUESTED → DENIED` and does nothing else. Approval advances `REQUESTED → APPROVED` only when four preconditions hold: the acting host owns the trip's vehicle; the trip is in `CONFIRMED` or `CHECKED_IN` (else `ERR_INVALID_STATE`); the extended window does not overlap another `ACTIVE` `BOOKED` block on the vehicle under half-open comparison (else `ERR_DATES_UNAVAILABLE`); and the trip's total `nights` after extension does not exceed the 90-night maximum (else `ERR_TRIP_TOO_LONG`).

Approval drives a three-level cascade. At level one the extension mutates the trip: the trip's `end_date` becomes the extension's `new_end_date`, and the trip's `nights`, `discounted_subtotal_cents`, `protection_premium_cents`, `estimated_total_cents`, and `estimated_host_earnings_cents` are recomputed with the same estimated-settlement math of §3.4 over the new, longer night count; the trip's `scheduled_return_at` is also recomputed as `new_end_date` at `T11:00:00Z`. At level two the trip mutation drives the linked `BOOKED` block: its `end_date` becomes the `new_end_date` and its `nights` is recomputed. At level three the block's night growth drives both the vehicle and the host: the vehicle's `booked_night_count` increases by the `added_nights`, and the host's `pending_balance_cents` increases by the extension's `added_earnings_cents`. That `added_earnings_cents` is the difference between the host earnings implied by the re-priced longer trip (the estimated settlement computed over the old night count plus `added_nights`) and the trip's `estimated_host_earnings_cents` before the extension — that is, only the incremental host earnings the extra nights produce.

### 3.8. Incident Claims and Adjudication, and Driver Risk

When a trip has been driven, either party may file a damage claim, but only against a trip whose `status` is `CHECKED_OUT` or `COMPLETED`; a claim against any earlier state is rejected with `ERR_TRIP_NOT_CLAIMABLE`. The claimant supplies `claimant` (either `HOST` or `GUEST`, naming who filed), a `damage_amount_cents` that must be greater than zero (else `ERR_INVALID_CLAIM_AMOUNT`), and a free-text `description`. A new `Claim` begins in `FILED`. A trip may hold at most one open (non-terminal) claim at a time; filing a second while one is still open is rejected with `ERR_DUPLICATE_OPEN_CLAIM`. Claims may be read individually or listed by `trip_id`.

The platform operator drives the claim through review. Starting review advances `FILED → UNDER_REVIEW`. From `UNDER_REVIEW` the operator may request more information, advancing to `NEEDS_INFO`; a party to the trip (the claimant or the counterparty) then provides that information with an optional `note`, advancing `NEEDS_INFO → UNDER_REVIEW`, and this request/provide cycle may repeat. From `UNDER_REVIEW` the operator either denies the claim, advancing to `DENIED` (terminal), or approves it, advancing to `APPROVED`; both may carry an optional `resolution_note`. Approval computes the **claim settlement** against the trip's protection plan: `covered_amount_cents` is the smaller of the assessed `damage_amount_cents` and the plan's `coverage_limit_cents`; `guest_deductible_cents` is the smaller of the plan's `deductible_cents` and the `covered_amount_cents`; `host_recovery_cents` equals the `covered_amount_cents`; and `uncovered_cents` is the larger of zero and the assessed `damage_amount_cents` minus the `covered_amount_cents`.

An `APPROVED` claim is settled by the operator, advancing `APPROVED → SETTLED` (terminal) and moving money: the guest's `outstanding_balance_cents` increases by the claim's `guest_deductible_cents`; the host's `available_balance_cents` and `lifetime_earnings_cents` each increase by the claim's `host_recovery_cents`; and if the claim was filed by the host (`claimant` is `HOST`), the guest's `at_fault_claim_count` increases by one and the guest's `driver_risk_score` is recomputed in its finalized form.

The `driver_risk_score` is a 0-to-100 reputation figure equal to the smaller of 100 and the sum of the guest's `at_fault_claim_count` times 20 plus the guest's `late_return_count` times 5. It exists in two variants. Read at booking time it is **provisional** — it reflects only outcomes from trips already `COMPLETED` and claims already `SETTLED` before this booking, excluding the in-flight trip. Recomputed on trip completion (§3.6) or claim settlement (above) it is **finalized** — it incorporates the just-completed trip's late flag and the just-settled at-fault claim, and therefore diverges from the provisional figure the guest saw when booking.

### 3.9. Host Earnings, Payouts, and Suspension

A host withdraws finalized earnings by requesting a `Payout` naming `host_id`, an `amount_cents`, the concurrency token `expected_host_version`, and an optional `trip_id` identifying the originating trip. Several checks guard the request in the §2.9 order: the host must be `ACTIVE` — a payout against a `SUSPENDED` host is rejected with `ERR_HOST_SUSPENDED`; the `expected_host_version` must match the host's current `version`, else `ERR_STALE_HOST_VERSION`; the `amount_cents` must be at least the minimum payout of 5,000 cents, else `ERR_PAYOUT_BELOW_MINIMUM`; and the `amount_cents` must not exceed the host's `available_balance_cents`, else `ERR_INSUFFICIENT_BALANCE`. On success the payout begins in `REQUESTED`; the host's `available_balance_cents` decreases by the amount, its `reserved_payout_cents` increases by the amount (locking the funds), and the host's `version` increments by one.

The platform operator resolves a requested payout one of two ways. Marking it paid advances `REQUESTED → PAID` (terminal): the host's `reserved_payout_cents` decreases by the amount and its `lifetime_paid_cents` increases by the amount, so the money leaves the reserved bucket and is recorded as lifetime paid. Marking it failed advances `REQUESTED → FAILED` (terminal), optionally recording a `failure_reason`: the host's `reserved_payout_cents` decreases by the amount and its `available_balance_cents` increases by the amount, returning the funds so the host may try again. Payouts may be read individually or listed by `host_id` or `trip_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource return `200 OK`. All endpoints honor the authentication, response-envelope, and validation-ordering rules of §2. To reconstruct the request body, side effects, and computed outputs of any endpoint below, refer to the corresponding workflow narrative in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hosts` | Register a host | Anonymous, PlatformAdmin |
| GET | `/hosts/{id}` | Get host (with ledger) | Host, Guest, PlatformAdmin |
| POST | `/hosts/{id}/suspend` | Suspend a host (blocks payouts) | PlatformAdmin |
| POST | `/hosts/{id}/reinstate` | Reinstate a suspended host | PlatformAdmin |
| POST | `/guests` | Register a guest | Anonymous, PlatformAdmin |
| GET | `/guests/{id}` | Get guest | Host, Guest, PlatformAdmin |
| POST | `/guests/{id}/submit-verification` | Submit license for verification | Guest |
| POST | `/guests/{id}/verify` | Approve guest verification | PlatformAdmin |
| POST | `/guests/{id}/reject` | Reject guest verification | PlatformAdmin |
| POST | `/protection-plans` | Create a protection plan tier | PlatformAdmin |
| GET | `/protection-plans/{id}` | Get protection plan | Host, Guest, PlatformAdmin |
| GET | `/protection-plans` | List protection plans | Host, Guest, PlatformAdmin |
| POST | `/vehicles` | Create a vehicle listing (DRAFT) | Host |
| GET | `/vehicles/{id}` | Get vehicle | Host, Guest, PlatformAdmin |
| GET | `/vehicles` | List/filter vehicles | Host, Guest, PlatformAdmin |
| PUT | `/vehicles/{id}` | Edit vehicle pricing/config | Host |
| POST | `/vehicles/{id}/list` | List the vehicle (make bookable) | Host |
| POST | `/vehicles/{id}/snooze` | Snooze listing | Host |
| POST | `/vehicles/{id}/unlist` | Unlist the vehicle (terminal) | Host |
| POST | `/vehicles/{id}/availability-blocks` | Host blocks a calendar window | Host |
| GET | `/availability-blocks/{id}` | Get availability block | Host, Guest, PlatformAdmin |
| GET | `/availability-blocks` | List blocks by vehicle/trip | Host, Guest, PlatformAdmin |
| POST | `/pricing-rules` | Create a dated price override | Host |
| GET | `/pricing-rules/{id}` | Get pricing rule | Host, Guest, PlatformAdmin |
| GET | `/pricing-rules` | List pricing rules by vehicle | Host, Guest, PlatformAdmin |
| POST | `/trips` | Book a trip (REQUESTED) | Guest |
| GET | `/trips/{id}` | Get trip | Host, Guest, PlatformAdmin |
| GET | `/trips` | List/filter trips | Host, Guest, PlatformAdmin |
| POST | `/trips/{id}/approve` | Host approves booking | Host |
| POST | `/trips/{id}/decline` | Host declines booking | Host |
| POST | `/trips/{id}/cancel` | Cancel a trip | Host, Guest |
| POST | `/trips/{id}/check-in` | Guest checks in (odometer/fuel/photos) | Guest |
| POST | `/trips/{id}/check-out` | Guest checks out; final settlement | Guest |
| POST | `/trips/{id}/complete` | Host completes trip; settle earnings | Host |
| GET | `/trips/{id}/inspections` | List a trip's inspection reports | Host, Guest, PlatformAdmin |
| POST | `/trips/{id}/extensions` | Guest requests a late-return extension | Guest |
| POST | `/extensions/{id}/approve` | Host approves extension (cascade) | Host |
| POST | `/extensions/{id}/deny` | Host denies extension | Host |
| GET | `/extensions/{id}` | Get extension | Host, Guest, PlatformAdmin |
| GET | `/extensions` | List extensions by trip | Host, Guest, PlatformAdmin |
| POST | `/trips/{id}/claims` | File an incident/damage claim | Host, Guest |
| POST | `/claims/{id}/start-review` | Adjudicator starts review | PlatformAdmin |
| POST | `/claims/{id}/request-info` | Request more info | PlatformAdmin |
| POST | `/claims/{id}/provide-info` | Party provides requested info | Host, Guest |
| POST | `/claims/{id}/approve` | Approve claim; compute settlement | PlatformAdmin |
| POST | `/claims/{id}/deny` | Deny claim | PlatformAdmin |
| POST | `/claims/{id}/settle` | Settle approved claim; move funds | PlatformAdmin |
| GET | `/claims/{id}` | Get claim | Host, Guest, PlatformAdmin |
| GET | `/claims` | List claims by trip | Host, Guest, PlatformAdmin |
| POST | `/payouts` | Host requests a payout | Host |
| POST | `/payouts/{id}/mark-paid` | Mark payout paid | PlatformAdmin |
| POST | `/payouts/{id}/mark-failed` | Mark payout failed; return funds | PlatformAdmin |
| GET | `/payouts/{id}` | Get payout | Host, Guest, PlatformAdmin |
| GET | `/payouts` | List payouts by host/trip | Host, Guest, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set logical UTC clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_HOST_NOT_FOUND` | 404 Not Found |
| `ERR_GUEST_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_BLOCK_NOT_FOUND` | 404 Not Found |
| `ERR_PRICING_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_EXTENSION_NOT_FOUND` | 404 Not Found |
| `ERR_PAYOUT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VEHICLE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_HOST_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_GUEST_NOT_VERIFIED` | 409 Conflict |
| `ERR_VEHICLE_NOT_LISTED` | 409 Conflict |
| `ERR_TRIP_NOT_CLAIMABLE` | 409 Conflict |
| `ERR_HOST_SUSPENDED` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_ODOMETER` | 422 Unprocessable Entity |
| `ERR_INVALID_FUEL_LEVEL` | 422 Unprocessable Entity |
| `ERR_INVALID_CLAIM_AMOUNT` | 422 Unprocessable Entity |
| `ERR_TRIP_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_PAYOUT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_DATES_UNAVAILABLE` | 409 Conflict |
| `ERR_PRICING_RULE_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_CLAIM` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_EXTENSION` | 409 Conflict |
| `ERR_INSUFFICIENT_BALANCE` | 402 Payment Required |
