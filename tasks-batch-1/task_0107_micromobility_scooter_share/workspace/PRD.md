# Micromobility Scooter Share API — Product Requirements Document

## 1. Introduction

Operating a shared scooter and e-bike fleet means reconciling three constituencies whose interests rarely align: riders who want a vehicle to unlock instantly and a fare they can predict; field technicians who keep depleted batteries and stranded vehicles in circulation; and a municipality that grants the right to operate only in exchange for accurate trip data and enforced parking discipline. This API is the backend that holds those interests in balance. It governs the full life of a vehicle from the moment it is registered into the fleet, through every reservation, ride, pause, and parking event, to the point where a depleted battery automatically dispatches a swap task or a misparked vehicle automatically generates a fine.

At the center of the platform is a pricing engine that must reconcile a forward-looking estimate quoted at unlock with the chronological, segment-by-segment fare that is actually charged when the trip ends. Geofence zones modulate where a vehicle may ride, where it may be parked, and how fast it may travel, and they reach into the fare itself through a per-minute discount applied to time ridden inside designated slow areas. Layered on top are an equity program that grants reduced rates and reduced parking penalties to qualifying low-income riders, a prepaid wallet that absorbs every charge and refund, and a regulatory reporting surface that produces time-weighted availability and trip-volume figures for the city.

This document specifies the contract that every implementation must honor: the entities and their fields, the state machines that constrain their transitions, the calculations that produce fares and penalties and reports, the validations that protect the system's invariants, and the precise error semantics returned when a request cannot be satisfied.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API. The whole API is mounted under the `/api` path prefix.

### 2.1. User and Role-Based Access Control

Every request other than self-registration must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles, spelled exactly as follows: `Anonymous`, `Rider`, `Technician`, `PlatformAdmin`, and `CityRegulator`.

- When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider`; ownership checks on any resource that references a `Rider` compare the resource's rider foreign key to `X-User-ID`. Concretely, a `Rider` may only act on a `Trip`, `Fine`, or `LowIncomeApplication` whose `rider_id` equals their own `X-User-ID`, as well as on their own `Rider` record and its wallet ledger; acting on another rider's resource is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on a task that references a technician compare the task's `technician_id` to `X-User-ID`. A technician may only complete a `RebalancingTask` whose `technician_id` equals their own `X-User-ID`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the role's only capability is self-registering a new `Rider`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`; a `PlatformAdmin` is not subject to rider- or technician-ownership checks.
- When `X-User-Role` is `CityRegulator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, used by the municipal data consumer who creates and finalizes regulatory reports.

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

List endpoints accept two query parameters that control the page window. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of leading items skipped and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Identifiers, Timestamps, and Versioning

Most resources in this system carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is first persisted. The `updated_at` field, also an ISO 8601 UTC timestamp, is refreshed on every mutation of the resource. The `version` field is an integer that starts at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control (see §2.7).

Two entities are append-only event records and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field, because they are never mutated after creation: `TripSegment` (the per-segment ride/pause log under a trip) and `WalletTransaction` (the per-entry wallet ledger under a rider). Every other entity — `Plan`, `Zone`, `Vehicle`, `Rider`, `Trip`, `Technician`, `RebalancingTask`, `Fine`, `LowIncomeApplication`, and `MDSReport` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

A subtlety worth stating plainly: when a derived field is recomputed as a side effect of some other operation, that recomputation is itself a mutation of the owning resource. Debiting `Rider.wallet_balance_cents` on a trip charge, adjusting `Rider.outstanding_fine_cents` on a fine event, or freezing an `MDSReport`'s aggregates each refreshes the owning resource's `updated_at` and increments its `version`. Two deliberate exceptions exist where a write does **not** bump the affected vehicle's `version`: the automatic creation of a battery-swap task when a trip ends with a depleted battery (§3.5), and the test-driving battery setter (§3.9). All other vehicle mutations increment `version`.

### 2.5. Zone Resolution and Geofence Behavior

Every geographic point in the service area is governed by exactly one effective `Zone`, but zones may physically overlap, so the platform needs a deterministic rule for which zone wins. Each `Zone` has a `name`, a `zone_type`, an integer `priority`, and — only for slow zones — a `max_speed_kph` ceiling (null otherwise). The `zone_type` is one of `RIDE_OK`, `SLOW`, `NO_RIDE`, or `NO_PARK`. When a vehicle's location falls inside more than one zone, the effective zone is the one whose `priority` integer is smallest; the `priority` must be at least 1. Ties on `priority` are broken by choosing the zone with the earliest `created_at`. This single resolution rule is what is meant throughout this document by a vehicle's or a point's "resolved zone."

The four zone types carry distinct operational meaning. A `RIDE_OK` zone permits both riding and parking with no restriction. A `SLOW` zone permits riding and parking but caps speed at its `max_speed_kph` and, more importantly for billing, applies the rider's plan slow-zone discount to minutes ridden inside it. A `NO_RIDE` zone forbids both starting and ending a trip there. A `NO_PARK` zone permits a trip to end there but treats doing so as a parking violation that raises a fine.

### 2.6. Monetary Values and Rounding

All monetary amounts in this system are expressed as integer cents — wallet balances, fares, fine amounts, plan rates, and top-up amounts alike. Where a calculation produces a fractional cent (for example, a slow-zone discount or a low-income fine reduction), the result is rounded half-up to a whole cent before it is combined with any other amount or stored. The one non-monetary calculation that rounds, the time-weighted availability figure on a regulatory report, is rounded half-up to two decimal places. Durations that feed billing are accumulated in whole seconds and converted to whole minutes by rounding up (see §3.4); minute counts and trip counts are always whole integers.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded against acting on a parent resource that has changed since the client last observed it, and both require an explicit expected-version field that must equal the parent's current `version`.

First, creating a `RebalancingTask` is guarded on the target vehicle. The create request must carry `expected_vehicle_version` matching the current `version` of the `Vehicle` named by `vehicle_id`. If the vehicle's version has advanced since the client last read it — for instance because the vehicle was sent to maintenance, or because an earlier swap task already superseded the operator's intent — the create is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412), preventing the operator from scheduling work against a stale view of the vehicle. A successful create increments the vehicle's `version`.

Second, switching a `Rider`'s plan is guarded on the rider. The change-plan request must carry `expected_rider_version` matching the current `version` of the targeted `Rider`. If another writer has advanced the rider's version since the client last read it — for instance by already changing the plan — the request is rejected with `ERR_STALE_RIDER_VERSION` (HTTP 412). These are the only two endpoints that accept an expected-version field; no other endpoint takes one.

### 2.8. Existence, Ownership, and Validation Ordering

Requests are screened in a fixed priority order so that the same failure always yields the same error. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role permission for the endpoint (`ERR_FORBIDDEN_ROLE`), then, for rider-owned actions on a trip, fine, or low-income application, the ownership check (`ERR_NOT_RESOURCE_OWNER`). Existence is checked next: every resource named in the request path is validated left to right, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`. After path existence, any foreign-key id supplied in the request body is checked against its referenced resource, and a dangling reference yields `ERR_REFERENCE_NOT_FOUND`; this body-reference check applies to creating a trip, creating a rebalancing task, registering a rider, submitting a low-income application, and changing a rider's plan. Only after these gates does the system evaluate state-machine legality (`ERR_INVALID_STATE`), then the domain-specific business rules described in §3, and finally field-level shape validation (`ERR_INVALID_REQUEST`) for missing required fields, invalid enum members, or out-of-range numeric values on any create or action body. The optimistic-concurrency check from §2.7 is evaluated within this flow on the two endpoints that carry an expected-version field.

### 2.9. Cascading Consistency

Several operations mutate more than one entity in a single call, and the secondary effects are as much a part of the contract as the primary state change. Ending a trip is the deepest cascade in the system: it charges the wallet, may raise a fine, and the fine in turn charges the wallet again, while the vehicle transitions out of use and — if its battery is depleted — auto-creates a swap task. Cancelling or completing a rebalancing task reaches across into the vehicle. Waiving a disputed fine refunds the wallet and clears the rider's outstanding balance. Each of these cascades is specified in full in the relevant §3 workflow, and each independent mutation of a resource refreshes that resource's `updated_at` and increments its `version`, with the two vehicle-version exceptions noted in §2.4.

## 3. Business Logic & Workflows

### 3.1. Fleet Configuration: Plans, Zones, and Vehicles

Before any rider can take a trip, a `PlatformAdmin` configures the operating environment. A pricing **Plan** is created with a `code` that is one of `STANDARD` or `LOW_INCOME` and must be unique across all plans. A plan fixes a flat `unlock_fee_cents` charged at the start of every trip, a `per_minute_cents` rate applied to billable minutes, and a `daily_cap_cents` ceiling on the total fare of a single trip; a `daily_cap_cents` of 0 means the trip fare is uncapped. A plan may also set a `slow_zone_discount_pct`, a fraction between 0 and 1 inclusive (defaulting to 0) by which the per-minute charge is reduced for minutes ridden inside a slow zone. The `unlock_fee_cents`, `per_minute_cents`, and `daily_cap_cents` values must each be at least 0. A plan carries an `active` flag (defaulting to true) indicating whether riders may currently be placed on it.

Geofence **Zones** are described in §2.5; an administrator supplies the `name`, the `zone_type`, the `priority`, and the optional `max_speed_kph`.

A **Vehicle** is registered with a `vehicle_type` of either `SCOOTER` or `EBIKE`, a unique `qr_code` scannable for unlock, an initial `battery_pct` (an integer from 0 to 100, defaulting to 100), and a `current_zone_id` naming the zone it is parked in. A vehicle's `status` is one of `AVAILABLE`, `RESERVED`, `IN_USE`, `LOW_BATTERY`, `MAINTENANCE`, or `RETIRED`, beginning at `AVAILABLE`. An administrator may send an `AVAILABLE` or `LOW_BATTERY` vehicle to maintenance, transitioning it to `MAINTENANCE`; attempting this from any other status is rejected as an invalid state transition. A `MAINTENANCE` vehicle may be returned to service, transitioning `MAINTENANCE → AVAILABLE`, but only when its `battery_pct` is at least 20; otherwise the transition is illegal. A `MAINTENANCE` vehicle may instead be retired, transitioning `MAINTENANCE → RETIRED`, which is terminal. Each of these administrative vehicle transitions increments the vehicle's `version`.

### 3.2. Riders, Wallets, and the Low-Income Program

Anyone may self-register as a **Rider** without authentication, supplying an `email` (unique across all riders), a `full_name`, and the `plan_id` of the plan they start on. A rider's `wallet_balance_cents` begins at 0 and tracks prepaid funds; their `outstanding_fine_cents` begins at 0 and equals the sum of `amount_cents` over their fines still in `PENDING` settlement status. A rider's account `status` is `ACTIVE` or `SUSPENDED`, beginning at `ACTIVE`.

A rider — or an administrator acting on their behalf — tops up the prepaid wallet by supplying an `amount_cents` to credit. A top-up creates a wallet ledger entry of type `TOPUP` carrying the positive `amount_cents`, adds that amount to `wallet_balance_cents`, and increments the rider's `version`. The wallet ledger itself is an append-only sequence of **WalletTransaction** records, each stamped with the owning `rider_id`, an optional `trip_id` and optional `fine_id` linking it to the event that produced it (both null for a plain top-up), a `txn_type` of `TOPUP`, `TRIP_CHARGE`, `TRIP_REFUND`, `FINE_CHARGE`, or `FINE_REFUND`, and a signed `amount_cents` — positive for credits (`TOPUP`, `TRIP_REFUND`, `FINE_REFUND`) and negative for debits (`TRIP_CHARGE`, `FINE_CHARGE`).

Riders seeking reduced rates submit a **LowIncomeApplication** naming their `rider_id`, their `household_size` (at least 1), and their declared `annual_income_cents` (at least 0). An application's `status` is `SUBMITTED`, `APPROVED`, or `REJECTED`, beginning at `SUBMITTED`. An administrator approving a `SUBMITTED` application transitions it `SUBMITTED → APPROVED`, but only when the declared annual income does not exceed an income ceiling of 3,000,000 cents per household member — that is, when `annual_income_cents` is at most 3,000,000 multiplied by `household_size`; an application failing that test cannot be approved. An administrator may instead reject a `SUBMITTED` application, transitioning it `SUBMITTED → REJECTED`. Both transitions require the application to be in `SUBMITTED` state.

Changing a rider's plan is the bridge between the application program and pricing. The change-plan request supplies the new `plan_id` together with the `expected_rider_version` described in §2.7. A rider may switch freely to a `STANDARD` plan, but may switch to a `LOW_INCOME` plan only if they hold at least one `LowIncomeApplication` in `APPROVED` status; an attempt to move to a low-income plan without an approved application is rejected with `ERR_NO_APPROVED_APPLICATION`. A successful switch sets the rider's `plan_id` and increments the rider's `version`.

An administrator may suspend an `ACTIVE` rider, transitioning the account `ACTIVE → SUSPENDED`; a suspended rider cannot start trips. Reinstating a `SUSPENDED` rider transitions it `SUSPENDED → ACTIVE`, but only when the rider's `outstanding_fine_cents` is exactly 0; attempting to reinstate a rider who still owes a balance is rejected with `ERR_OUTSTANDING_FINES`. Both transitions increment the rider's `version`.

### 3.3. Starting a Trip: Unlock and the Provisional Estimate

A `Rider` begins a journey by unlocking a vehicle, supplying their own `rider_id` and the `vehicle_id` of the vehicle to unlock. The unlock is gated by several preconditions evaluated together. The vehicle must currently be `AVAILABLE`; a vehicle that is already reserved or in use cannot be unlocked again, and such an attempt is rejected with `ERR_VEHICLE_NOT_AVAILABLE`. The vehicle's resolved current zone must not be a `NO_RIDE` zone; starting on a vehicle parked in a no-ride zone is rejected with `ERR_START_IN_NO_RIDE_ZONE`. The vehicle's `battery_pct` must be at least 20; starting on a vehicle below that minimum is rejected with `ERR_BATTERY_TOO_LOW`. Because a suspended account may not ride, the acting rider must be `ACTIVE`.

When these checks pass, the vehicle momentarily moves `AVAILABLE → RESERVED` and then, once the trip row exists, `RESERVED → IN_USE` within the same unlock call; the `RESERVED` state is a transient internal step and the trip itself is created directly in `ACTIVE` status. The new **Trip** records the acting `rider_id`, the `vehicle_id`, and a `start_zone_id` copied from the vehicle's `current_zone_id` at unlock; its `end_zone_id` is null until the trip ends, its `started_at` is stamped with the server clock, and its `ended_at` is null. The system simultaneously opens the trip's first ride segment (see §3.4).

At unlock the system also computes a provisional, forward-looking fare and stores it in `estimated_fare_cents`. This estimate is purely informational: it assumes a projected ride of 15 minutes at the plan's per-minute rate with no pauses and no slow-zone discount. The estimate is the plan's `unlock_fee_cents` plus 15 multiplied by the plan's `per_minute_cents`; if the plan's `daily_cap_cents` is greater than 0, the estimate is the lesser of that sum and the cap, and if the cap is 0 the sum stands uncapped. This forward-looking figure deliberately diverges from the final fare, which replays the trip's actual segments chronologically; the two will almost always differ.

### 3.4. Riding, Pausing, and Segment Accounting

A trip's elapsed time is recorded as an ordered series of **TripSegment** rows, each owned by its `trip_id` and tagged with a `segment_type` of either `RIDE` or `PAUSE`, a `zone_id` capturing the geofence in effect when the segment opened, a `started_at`, an `ended_at` that stays null while the segment is the trip's open segment, and a `duration_seconds` computed as the whole-second difference between `ended_at` and `started_at` (0 while the segment is still open). `RIDE` segments are billable; `PAUSE` segments are not.

A rider may pause an `ACTIVE` trip, transitioning it `ACTIVE → PAUSED`. Pausing closes the open ride segment — stamping its `ended_at` and computing its `duration_seconds` — and opens a fresh pause segment whose `started_at` is the current clock. Resuming a `PAUSED` trip transitions it `PAUSED → ACTIVE`, closing the open pause segment and opening a new ride segment whose `started_at` is the current clock and whose `zone_id` is the vehicle's current zone. A trip may cycle between `ACTIVE` and `PAUSED` any number of times.

Billable minutes are computed only at trip end, and the order of operations is fixed. The system first sums the `duration_seconds` of every `RIDE` segment of the trip (pause segments contribute nothing), then converts that total to minutes by dividing by 60 and rounding up to the next whole minute; a total of 0 ride-seconds yields 0 billable minutes. This sum-the-seconds-then-round-up order is deliberate and is not the same as rounding each segment to minutes individually and summing — the two diverge at sub-minute boundaries. The resulting whole-minute count is stored in `billable_minutes`.

### 3.5. Ending a Trip: Final Fare, Charge, and the Parking Cascade

Ending a trip is the system's central event. The rider supplies the `end_zone_id` naming the zone where the vehicle is parked. The end is permitted only when the trip is `ACTIVE` or `PAUSED`, when the resolved end zone is not a `NO_RIDE` zone, and when the rider's account is `ACTIVE`; ending in a no-ride zone is rejected with `ERR_END_IN_NO_RIDE_ZONE`, and the rider must walk the vehicle out of such a zone before ending. A valid end closes the trip's open segment (a ride segment when ending from `ACTIVE`, a pause segment when ending from `PAUSED`), stamps `ended_at` with the current clock, records the resolved zone into `end_zone_id`, and transitions the trip `ACTIVE → COMPLETED` or `PAUSED → COMPLETED` accordingly.

The final fare is then computed from the actual ride segments, and this is where the slow-zone discount lands. Each `RIDE` segment carries the `zone_id` that was in effect when it opened. The system partitions billable time into two buckets by whether a ride segment's `zone_id` resolves to a `SLOW` zone, and applies the same sum-then-round-up rule independently to each bucket: the slow minutes are the rounded-up whole minutes from summing the seconds of ride segments in slow zones, and the normal minutes are the rounded-up whole minutes from summing the seconds of ride segments not in slow zones. The normal charge is the normal minutes multiplied by the plan's `per_minute_cents`. The slow charge is the slow minutes multiplied by the plan's `per_minute_cents` multiplied by one minus the plan's `slow_zone_discount_pct`, rounded half-up to a whole cent before it is combined. The gross fare is the plan's `unlock_fee_cents` plus the normal charge plus the slow charge. The fare stored in `final_fare_cents` is that gross figure when the plan's `daily_cap_cents` is 0, and otherwise the lesser of the gross figure and the cap. Riders on a `LOW_INCOME` plan pay this fare under their plan's rates and cap, which yields a lower fare than a `STANDARD` rider would pay for the identical minutes.

Completing the trip triggers a cascade of effects, each of which is part of the contract. First, the wallet is charged: a `WalletTransaction` of type `TRIP_CHARGE` is created carrying the negative `final_fare_cents`, and `Rider.wallet_balance_cents` is reduced by the final fare. Second, if and only if the resolved end zone is a `NO_PARK` zone, a **Fine** is raised against the trip's rider with reason `BAD_PARKING_NO_PARK` and settlement status `PENDING`. Third, raising that fine immediately charges the wallet again: a `WalletTransaction` of type `FINE_CHARGE` is created carrying the negative fine `amount_cents`, `Rider.wallet_balance_cents` is reduced by the fine amount, and `Rider.outstanding_fine_cents` is increased by the fine amount. Finally, the vehicle leaves use: its `current_zone_id` is set to the trip's `end_zone_id`, and if its `battery_pct` is at least 20 it transitions `IN_USE → AVAILABLE`, while if its `battery_pct` is below 20 it transitions `IN_USE → LOW_BATTERY`. A vehicle that lands in `LOW_BATTERY` automatically spawns a battery-swap `RebalancingTask` for itself — a task with `task_type` `SWAP`, a null `target_zone_id` and null `technician_id`, status `OPEN`, a `window_start` of the current clock, and a `window_end` one hour (3,600 seconds) later. This auto-created swap task does not increment the vehicle's `version`.

A trip may also be cancelled instead of ended, but only as an abort shortly after unlock: cancellation is permitted only while the trip is `ACTIVE` and only within 120 seconds of `started_at` (the elapsed time from `started_at` to now must be at most 120 seconds). Cancelling closes all open segments, sets `final_fare_cents` and `billable_minutes` to 0, and returns the vehicle `IN_USE → AVAILABLE` without changing its zone. No wallet charge is created for a cancelled trip.

A `Fine` records the `rider_id` it was issued against (copied from the trip's rider), the `trip_id` whose end raised it, a `reason` that is one of `BAD_PARKING_NO_PARK` or `BAD_PARKING_OUT_OF_ZONE`, the penalty `amount_cents`, and a `settlement_status` of `PENDING`, `SETTLED`, `DISPUTED`, or `WAIVED` beginning at `PENDING`. The penalty amount is a base parking fine of 2,500 cents for a rider on any plan other than `LOW_INCOME`; for a rider whose current plan code is `LOW_INCOME`, the amount is that base reduced by 40 percent — that is, 2,500 multiplied by one minus 0.40 — rounded half-up to a whole cent. The reduction is keyed off the plan the rider holds at the moment the fine is computed, which is only `LOW_INCOME` if an application of theirs was approved beforehand.

### 3.6. Fine Resolution: Settle, Dispute, Reject, and Waive

A fine's wallet debit happens at the moment the fine is created (§3.5), so settling a fine does not move money again — it merely clears the outstanding flag. A rider may settle a `PENDING` fine, transitioning it `PENDING → SETTLED`, but only when their `wallet_balance_cents` is at least the fine's `amount_cents`; an attempt to settle with insufficient balance is rejected with `ERR_INSUFFICIENT_WALLET`. Settling reduces the rider's `outstanding_fine_cents` by the fine amount and increments the rider's `version`.

A rider who contests a fine may dispute a `PENDING` fine, transitioning it `PENDING → DISPUTED` with no monetary effect. From the disputed state, an administrator adjudicates one of two ways. Rejecting the dispute returns the fine `DISPUTED → PENDING`, restoring it to the collectible pool with no monetary effect — and a fine may cycle between `PENDING` and `DISPUTED` repeatedly as it is disputed and rejected. Waiving the fine instead transitions it `DISPUTED → WAIVED`, which is terminal, and reverses the original charge: a `WalletTransaction` of type `FINE_REFUND` is created carrying the positive `amount_cents`, `Rider.wallet_balance_cents` is increased by the fine amount, and `Rider.outstanding_fine_cents` is reduced by the fine amount. Rejecting and waiving both require the fine to be currently `DISPUTED`; settling and disputing both require it to be currently `PENDING`. Any of these actions on a fine in the wrong state is rejected as an invalid state transition.

### 3.7. Rebalancing and Battery Swaps

Keeping the fleet usable falls to **Technicians** and the **RebalancingTask** queue. A technician is registered with a `name`, a `depot_zone_id` naming their home zone, and an `on_shift` flag (defaulting to true) indicating availability for assignment. A rebalancing task names the `vehicle_id` it concerns, a `task_type` of `MOVE` (relocate the vehicle to a target zone) or `SWAP` (replace the battery in place), a `target_zone_id` that is required for a move and null for a swap, and a scheduled on-site window bounded by `window_start` and `window_end`, where `window_end` must be strictly after `window_start` (a non-positive window is rejected with `ERR_INVALID_WINDOW`). A task's `technician_id` is null until assigned, and its `status` is `OPEN`, `ASSIGNED`, `COMPLETED`, or `CANCELLED`, beginning at `OPEN`. Creating a task is guarded by the vehicle optimistic-concurrency rule in §2.7 and increments the vehicle's `version`.

An administrator assigns an `OPEN` task to a technician by supplying the `technician_id`, transitioning the task `OPEN → ASSIGNED` and recording the technician on it. Assignment requires the named technician to be on shift. It also enforces a buffered no-overlap rule: the task's window, widened by 600 seconds on each side to form the closed interval from `window_start` minus 600 seconds through `window_end` plus 600 seconds, must not overlap the (identically buffered) window of any other task already `ASSIGNED` to that same technician; an overlap is rejected with `ERR_TECH_WINDOW_OVERLAP`. An administrator may unassign an `ASSIGNED` task, transitioning it `ASSIGNED → OPEN` and clearing its `technician_id`.

Completing a task is the technician's exclusive action and may only be performed by the technician the task is assigned to. Completion requires the task to be `ASSIGNED`, and it reaches into the vehicle differently per type. For a `SWAP`, the referenced vehicle must currently be `LOW_BATTERY`; completion recharges it by setting `battery_pct` to 100 and transitions the vehicle `LOW_BATTERY → AVAILABLE`. For a `MOVE`, the referenced vehicle must currently be `AVAILABLE`; completion relocates it by setting its `current_zone_id` to the task's `target_zone_id`, leaving the vehicle `AVAILABLE`. Either completion transitions the task to `COMPLETED`. A task may be cancelled by an administrator from either `OPEN` or `ASSIGNED`; cancelling an assigned task clears its `technician_id`, and a cancelled task is terminal.

### 3.8. MDS Regulatory Reporting

The municipality consumes fleet data through **MDSReport** windows created and finalized by a `CityRegulator`. A report defines a reporting window with an inclusive `window_start` and an exclusive `window_end` (both UTC datetimes), where `window_end` must be strictly after `window_start` or the request is rejected with `ERR_INVALID_WINDOW`. A report holds three computed aggregates — `trip_count`, `total_billable_minutes`, and `avg_available_vehicles` — and a `status` of `DRAFT` or `FINALIZED`, beginning at `DRAFT`.

While a report is in `DRAFT`, its aggregates are recomputed live whenever it is fetched. The `trip_count` is the number of `COMPLETED` trips whose `started_at` falls in the half-open window — that is, at or after `window_start` and strictly before `window_end`. The `total_billable_minutes` is the sum of `billable_minutes` over exactly those counted trips. The `avg_available_vehicles` is a time-weighted average of how many vehicles were `AVAILABLE` across the window: the system integrates the count of available vehicles over the window using vehicle status-change events (each status mutation stamps `updated_at`), multiplying each interval's available count by that interval's duration in seconds, summing those products across the window, and dividing by the total number of seconds in the window, then rounding half-up to two decimal places. When no vehicle status changes occur inside the window, the figure is simply the available count held throughout. This time-weighted form deliberately differs from a naive snapshot taken at the window's end. Finalizing a `DRAFT` report transitions it `DRAFT → FINALIZED` and freezes the three aggregates at their then-current computed values; a finalized report is terminal and no longer recomputes.

### 3.9. Test-Driving Capabilities

Two administrator-only capabilities exist to make durations and battery-dependent branches deterministic under test. A clock-setting capability sets the server's logical UTC clock to a supplied instant, expressed through a `to_iso8601` value; every server-stamped timestamp thereafter — trip `started_at`, segment clocks, trip `ended_at`, and report windows — uses that value until it is changed again. A battery-setting capability directly assigns a vehicle's `battery_pct` to a supplied value so that the trip-end low-battery branch reads a pinned charge; this setter does not change the vehicle's `status` and does not increment its `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act on an existing resource return `200 OK`. Request and response bodies are reconstructed from the workflows in §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/plans` | Create a pricing plan | PlatformAdmin |
| GET | `/api/plans/{id}` | Fetch a plan | PlatformAdmin, Rider |
| GET | `/api/plans` | List plans | PlatformAdmin, Rider |
| POST | `/api/zones` | Create a geofence zone | PlatformAdmin |
| GET | `/api/zones/{id}` | Fetch a zone | PlatformAdmin, Rider, Technician |
| GET | `/api/zones` | List zones | PlatformAdmin, Rider, Technician |
| POST | `/api/vehicles` | Register a fleet vehicle | PlatformAdmin |
| GET | `/api/vehicles/{id}` | Fetch a vehicle | PlatformAdmin, Rider, Technician |
| GET | `/api/vehicles` | List vehicles; filter by status or current zone | PlatformAdmin, Rider, Technician |
| POST | `/api/vehicles/{id}/maintenance` | Send a vehicle to maintenance | PlatformAdmin |
| POST | `/api/vehicles/{id}/return-to-service` | Return a maintained vehicle to service | PlatformAdmin |
| POST | `/api/vehicles/{id}/retire` | Permanently retire a vehicle | PlatformAdmin |
| POST | `/api/riders` | Register a rider on a plan | Anonymous |
| GET | `/api/riders/{id}` | Fetch a rider | PlatformAdmin, Rider |
| GET | `/api/riders` | List riders; filter by plan | PlatformAdmin |
| POST | `/api/riders/{id}/topup` | Top up a rider's prepaid wallet | Rider, PlatformAdmin |
| POST | `/api/riders/{id}/change-plan` | Switch the rider's plan (OCC-guarded) | Rider, PlatformAdmin |
| POST | `/api/riders/{id}/suspend` | Suspend a rider account | PlatformAdmin |
| POST | `/api/riders/{id}/reinstate` | Reinstate a suspended rider | PlatformAdmin |
| GET | `/api/riders/{id}/wallet-transactions` | List a rider's wallet ledger | PlatformAdmin, Rider |
| GET | `/api/wallet-transactions/{id}` | Fetch a single wallet transaction | PlatformAdmin, Rider |
| GET | `/api/wallet-transactions` | List wallet transactions; filter by rider, trip, or fine | PlatformAdmin |
| POST | `/api/trips` | Unlock a vehicle and start a trip | Rider |
| GET | `/api/trips/{id}` | Fetch a trip | PlatformAdmin, Rider |
| GET | `/api/trips` | List trips; filter by rider, vehicle, or zone | PlatformAdmin, Rider |
| GET | `/api/trips/{id}/segments` | List a trip's segments | PlatformAdmin, Rider |
| GET | `/api/trip-segments/{id}` | Fetch a single trip segment | PlatformAdmin, Rider |
| GET | `/api/trip-segments` | List trip segments; filter by trip or zone | PlatformAdmin, Rider |
| POST | `/api/trips/{id}/pause` | Pause an active trip | Rider |
| POST | `/api/trips/{id}/resume` | Resume a paused trip | Rider |
| POST | `/api/trips/{id}/end` | End a trip; supply the parking zone | Rider |
| POST | `/api/trips/{id}/cancel` | Cancel a trip within the grace window | Rider |
| POST | `/api/technicians` | Register a field technician | PlatformAdmin |
| GET | `/api/technicians/{id}` | Fetch a technician | PlatformAdmin, Technician |
| GET | `/api/technicians` | List technicians; filter by depot zone | PlatformAdmin, Technician |
| POST | `/api/rebalancing-tasks` | Create a MOVE or SWAP task (OCC-guarded on the vehicle) | PlatformAdmin |
| GET | `/api/rebalancing-tasks/{id}` | Fetch a rebalancing task | PlatformAdmin, Technician |
| GET | `/api/rebalancing-tasks` | List tasks; filter by vehicle, technician, or target zone | PlatformAdmin, Technician |
| POST | `/api/rebalancing-tasks/{id}/assign` | Assign a task to a technician | PlatformAdmin |
| POST | `/api/rebalancing-tasks/{id}/unassign` | Release a task back to OPEN | PlatformAdmin |
| POST | `/api/rebalancing-tasks/{id}/complete` | Mark a task complete | Technician |
| POST | `/api/rebalancing-tasks/{id}/cancel` | Cancel an open or assigned task | PlatformAdmin |
| GET | `/api/fines/{id}` | Fetch a fine | PlatformAdmin, Rider |
| GET | `/api/fines` | List fines; filter by rider or trip | PlatformAdmin, Rider |
| POST | `/api/fines/{id}/settle` | Settle a pending fine | Rider |
| POST | `/api/fines/{id}/dispute` | Dispute a pending fine | Rider |
| POST | `/api/fines/{id}/reject-dispute` | Reject a dispute, returning the fine to PENDING | PlatformAdmin |
| POST | `/api/fines/{id}/waive` | Waive a disputed fine and refund the charge | PlatformAdmin |
| POST | `/api/low-income-applications` | Submit a low-income plan application | Rider |
| GET | `/api/low-income-applications/{id}` | Fetch an application | PlatformAdmin, Rider |
| GET | `/api/low-income-applications` | List applications; filter by rider | PlatformAdmin |
| POST | `/api/low-income-applications/{id}/approve` | Approve an application (income-ceiling check) | PlatformAdmin |
| POST | `/api/low-income-applications/{id}/reject` | Reject an application | PlatformAdmin |
| POST | `/api/mds-reports` | Create a draft MDS reporting window | CityRegulator |
| GET | `/api/mds-reports/{id}` | Fetch an MDS report (recomputes while DRAFT) | CityRegulator, PlatformAdmin |
| POST | `/api/mds-reports/{id}/finalize` | Freeze an MDS report's aggregates | CityRegulator |
| POST | `/api/_clock/set_current_utc` | Set the server's logical UTC clock (test-driving) | PlatformAdmin |
| POST | `/api/_vehicles/{id}/set_battery` | Directly set a vehicle's battery_pct (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_START_IN_NO_RIDE_ZONE` | 422 Unprocessable Entity |
| `ERR_END_IN_NO_RIDE_ZONE` | 422 Unprocessable Entity |
| `ERR_BATTERY_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_VEHICLE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_TECH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_APPROVED_APPLICATION` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_WALLET` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VEHICLE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_RIDER_VERSION` | 412 Precondition Failed |
| `ERR_OUTSTANDING_FINES` | 422 Unprocessable Entity |
