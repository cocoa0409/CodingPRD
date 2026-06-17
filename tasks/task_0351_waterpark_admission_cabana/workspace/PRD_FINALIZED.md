# Waterpark Admission & Cabana API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Waterpark Admission & Cabana platform, the system of record behind a single waterpark's day-of-visit commerce. The park sells two admission products — single-day tickets and full-season passes — and it must do so under a hard ceiling on how many guests can stand inside the gate at any timed-entry slot. The platform therefore sits at the intersection of two disciplines that pull in opposite directions: a quota-allocation engine that hands out a finite pool of timed-entry capacity, and a pricing engine that quotes each party against resident, group, and food-and-beverage adjustments before any money changes hands.

Around that core, the platform manages the rest of a guest's visit: cabana and locker rentals that draw on the same window capacity, wristband bands assigned by height at the gate, and a weather regime that can suspend cabana sales or rain out an entire window. When weather turns, the system must unwind reservations cleanly and compensate affected guests with rain-check vouchers that flow back into a guest wallet. Throughout, the operative concern is consistency under contention: two clerks reading the same window must not both consume its last slot, a refund must release every downstream hold it touched, and a frozen season pass must give back its capacity while it sleeps and re-acquire it on wake. The sections that follow define the contract that keeps those invariants true.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. A request that omits either header, or that carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `Guest`, `GateAgent`, `ParkManager`, and `FinanceClerk`. When a syntactically valid request names a role that is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles differ in how their `X-User-ID` binds to data. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest` entity; ownership checks on any resource that references a `Guest` compare that resource's `guest_id` field to `X-User-ID`. A guest who attempts a state-changing operation against an order or admission whose `guest_id` is not their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `GateAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ParkManager` and when `X-User-Role` is `FinanceClerk`: in both cases `X-User-ID` is an opaque operator identifier that the server does not match against any stored entity's identity.

The role split, in narrative terms: a `Guest` purchases and manages their own orders, admissions, and rentals; a `GateAgent` staffs the gate, binding named guests to admissions and checking them in; a `ParkManager` configures parks, windows, inventory, and pricing, and drives weather, window-posture, and logical-clock operations; and a `FinanceClerk` performs refunds and rain-check settlement. The endpoint table in §4 names the authorized roles for each operation, and the precise ownership semantics above govern which individual `Guest` may act on a given resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0, and a supplied value must be zero or greater. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_PAGINATION_INVALID`.

Unless an endpoint states otherwise, every list is returned sorted by the `created_at` timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching rows before pagination and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Common Resource Properties and Identifiers

Most resources in this system carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` field is an integer that begins at creation and increments by one on every mutation; it is the value clients quote for optimistic concurrency control (see §2.6).

Two entities are deliberately leaner. A `LockerRental` and the singleton `ClockState` carry only `id` and `created_at`; they have no `updated_at` and no `version`. A `LockerRental` is computed once at creation and never mutated thereafter, and `ClockState` is a single mutable bookkeeping row rather than a guest-facing resource. For every other entity — `Park`, `PricingPolicy`, `EntryWindow`, `Cabana`, `Locker`, `Guest`, `Order`, `Admission`, `CabanaRental`, and `RainCheck` — the full quartet of `id`, `created_at`, `updated_at`, and `version` applies.

### 2.5. Nested Resource Retrieval and Reference Resolution

Several endpoints address resources through nested paths — for example, the windows, cabanas, and lockers that hang beneath a park, or the admissions and rentals that hang beneath an order. The server validates every identifier appearing in a path or body from left to right, and the first identifier that does not resolve to a live resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or business rule is consulted. A request for a window under a non-existent park therefore fails on the park, not the window. This resolution rule covers every referenced `park`, `window`, `order`, `admission`, `cabana`, `locker`, `guest`, and `rain-check` identifier.

### 2.6. Optimistic Concurrency on Window Capacity

Two operations write against the shared capacity pool of an `EntryWindow`, and both are guarded by optimistic concurrency control keyed to the window's `version`. The first is renting a cabana for a window; the second is assigning an admission to a window. Each of these two requests must carry `expected_entry_window_version` as a mandatory field whose value is the `version` of the target `EntryWindow` that the client last observed. If that value does not match the window's current `version` at the moment the server processes the request, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no capacity is consumed.

The purpose is to prevent a client from committing against a stale view of the window. Because both a successful assignment and a successful cabana rental increment the window's `version` by one, a client whose `expected_entry_window_version` no longer matches has, by definition, missed an intervening capacity change — another assignment or rental took a slot, or the window's posture changed — and must re-read the window before retrying. No other endpoint accepts or requires a version field; only these two capacity writes participate in the OCC check.

### 2.7. Derived-Field Reconciliation

A handful of fields are never written directly by clients; the server recomputes them from authoritative state and refreshes them as part of the mutating operation. On a `Park`, `open_window_count` is the number of that park's `EntryWindow` children whose `status` is `OPEN`, and it is recomputed on every window status change that adds or removes an `OPEN` window. On an `EntryWindow`, `reserved_count` is the number of admissions and cabana rentals currently holding capacity but not yet checked in, and `admitted_count` is the number of admissions that have passed the gate against that window; both move only through the state transitions described in §3. Whenever the server reconciles such a derived field, the owning resource is mutated: its `updated_at` is refreshed and its `version` increments by one, exactly as for any other change.

### 2.8. Money, Time, and Rounding Conventions

All monetary values in this system are integer cents — `base_price_cents`, `combo_price_cents`, `daily_rate_cents`, `hourly_rate_cents`, `rain_check_value_cents`, `value_cents`, `price_cents`, `ticket_price_cents`, `subtotal_cents`, `total_cents`, `wallet_credit_cents`, and `wallet_credit_used_cents` are all whole numbers of cents, never floating-point dollars. Where a discount produces a fractional cent, the rounding rule is round-half-up to the nearest whole cent, and §3 pins exactly where in each calculation that rounding occurs. Discount percentages such as `resident_discount_pct` and `group_discount_pct` are fractions between 0 and 0.90 inclusive, where 0.20 denotes a twenty-percent reduction.

Time is reckoned against a server-controlled logical clock rather than the wall clock. The current instant is held in the `current_utc` field of the singleton `ClockState`, and every window-boundary comparison and every freeze-day calculation reads that `current_utc` value. An administrative test-driving capability sets the clock by supplying a `to_iso8601` instant. All window and rental boundaries — `starts_at` and `ends_at` — are ISO 8601 UTC timestamps, with `starts_at` treated as inclusive and `ends_at` as exclusive wherever an interval is compared.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the same failing request always yields the same error. Authentication comes first: a request lacking well-formed `X-User-Role` and `X-User-ID` headers fails with `ERR_UNAUTHENTICATED`. Role authorization comes next, rejecting a disallowed role with `ERR_FORBIDDEN_ROLE`. Resource-ownership for guest-scoped order and admission mutations follows, rejecting a guest acting on someone else's resource with `ERR_NOT_RESOURCE_OWNER`. Existence is checked fourth, with any unresolved path or body identifier failing left-to-right with `ERR_NOT_FOUND`. Request-schema validation is fifth — missing required fields, invalid enum values, out-of-range numbers, or an interval whose `starts_at` is not strictly before its `ends_at` fail with `ERR_INVALID_REQUEST`. Only after all five of these pass does the server evaluate state-machine legality and the domain-specific business rules described in §3, in the order those sections lay out. In particular, the state-legality check (that the target resource is in a state from which the requested transition is defined, otherwise `ERR_INVALID_STATE`) and the capacity OCC check (`ERR_STALE_VERSION`) precede the remaining business-safety, temporal, and fiscal checks.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Park, Its Windows, and Its Inventory

A `ParkManager` brings a park into existence by supplying its display `name`, an optional IANA `timezone` used informationally for scheduling that defaults to `America/New_York`, a `total_gate_capacity` of at least 1 that bounds park-wide admittance, an optional list of `resident_zip_prefixes` (defaulting to an empty list) whose entries grant resident pricing, and an optional `rain_check_value_cents` of zero or greater (defaulting to 0) that fixes the flat credit each issued voucher will carry. A freshly created park starts with `weather_status` of `CLEAR` and `open_window_count` of 0.

The park's `weather_status` is a posture the manager recomputes through a dedicated weather operation that accepts a new `weather_status` value of `CLEAR`, `STORM_WATCH`, or `RAINED_OUT`. While the posture is `CLEAR` the park trades normally. `STORM_WATCH` suspends the sale of new cabanas but keeps the gate and check-in open. `RAINED_OUT` closes the gate and arms rain-check eligibility for the day, and it is the precondition that lets a manager subsequently rain out individual windows.

Beneath a park the manager provisions timed-entry windows, each created with a `starts_at`, an `ends_at`, and a `window_capacity` of at least 1; a new window begins in `OPEN` status with `reserved_count` and `admitted_count` both at zero, and creating it recomputes the park's `open_window_count`. The manager also provisions cabanas — each carrying a `label`, a `tier` of `STANDARD`, `PREMIUM`, or `CABANA_SUITE`, a `daily_rate_cents` of zero or greater, and an optional `turnover_buffer_minutes` (defaulting to 30, never negative) that fixes the mandatory cleaning gap between two rentals of that same cabana — and lockers, each carrying a `bank_code` and an `hourly_rate_cents` of zero or greater. Each window, cabana, and locker records the `park_id` of its owning park.

A window's posture changes only along defined paths. Restricting a window moves it from `OPEN` to `RESTRICTED`, which keeps existing reservations valid but blocks new assignment, and recomputes the park's `open_window_count` downward. Reopening moves a window from `RESTRICTED` back to `OPEN` and recomputes `open_window_count` upward. Closing a window moves it from either `OPEN` or `RESTRICTED` to the terminal `CLOSED` status; closing is permitted only when the window's `admitted_count` and `reserved_count` are both zero, unless the caller sets the optional `force` flag, and it recomputes `open_window_count` when the window had been `OPEN`. A transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.2. Pricing Policy and the Quote

Admission pricing is governed by a `PricingPolicy` row, which a `ParkManager` creates for a specific `park_id` and `product_type` of either `DAY_TICKET` or `SEASON_PASS`. A policy fixes the `base_price_cents` (zero or greater), the `resident_discount_pct` for resident guests (a fraction from 0 to 0.90, defaulting to 0), the `group_threshold` party size at or above which a group rate applies (at least 2, defaulting to 10), the `group_discount_pct` applied once that threshold is met (0 to 0.90, defaulting to 0), and the `combo_price_cents` surcharge added per ticket when the party opts into the food-and-beverage combo (zero or greater, defaulting to 0). Each policy carries an `active` flag. Creating a new policy for a given park-and-product-type pairing supersedes any prior policy for that same pairing by setting the prior row's `active` to false, leaving exactly one `active` policy live per pairing. Only the `active` policy may price an order, and a list of policies may be filtered by `park_id`, `product_type`, and `active`.

The quote itself runs when a guest pays for an order, and it is pinned in both its arithmetic and its rounding order. The engine first selects the single `active` `PricingPolicy` for the order's `park_id` and `product_type`; if no such active policy exists the payment is rejected with `ERR_NO_ACTIVE_POLICY`. It then resolves two eligibility flags. Resident eligibility, recorded as `resident_rate_applied`, is true exactly when the purchasing guest's `zip_code` begins with at least one of the park's `resident_zip_prefixes` entries. Group eligibility, recorded as `group_rate_applied`, is true exactly when the order's `party_size` is at least the active policy's `group_threshold`.

Discounts are not stacked. The engine takes the resident discount percentage when the resident flag is set and zero otherwise, takes the group discount percentage when the group flag is set and zero otherwise, and uses the single larger of those two percentages as the effective discount — the maximum of the two, never their product or their sum. It then applies that effective percentage to the base price to obtain the discounted base, and rounds that discounted base to a whole number of cents using round-half-up at this per-ticket step. The combo surcharge — the policy's `combo_price_cents` when the order's `food_beverage_combo` flag is set, otherwise zero — is added to the rounded discounted base to give the per-ticket price; because the combo amount is already an integer, no further rounding occurs. The per-ticket price is then multiplied by `party_size` to give `subtotal_cents`. The order's two derived booleans differentiate the two pricing variants: a party below the group threshold simply carries `group_rate_applied` false so the effective discount reduces to the resident percentage (or zero), whereas a party at or above the threshold carries `group_rate_applied` true and the effective discount becomes the larger of resident and group. The decisive rule, repeated for emphasis, is round-half-up per ticket first, then add the combo, then multiply by the party size.

After the subtotal is fixed, the guest's wallet is applied. The amount of credit consumed, `wallet_credit_used_cents`, is the smaller of the guest's available `wallet_credit_cents` and the `subtotal_cents`, so it never exceeds either the balance or the bill. The final `total_cents` is the subtotal minus the credit consumed. Each minted admission later carries a `ticket_price_cents` equal to the subtotal divided evenly across the party.

### 3.3. The Order Lifecycle: Two Independent Dimensions

An `Order` is purchased by a `Guest` against a park by supplying `park_id`, `guest_id`, `product_type`, `party_size` (at least 1), and an optional `food_beverage_combo` flag defaulting to false. The guest named in `guest_id` is both the purchaser and the party leader, and a guest may act only on orders whose `guest_id` is their own `X-User-ID`. An order tracks two completely independent dimensions of progress. The payment dimension, `payment_status`, begins at `PENDING`. The fulfillment dimension, `fulfillment_status`, begins at `UNFULFILLED`. The two move on separate triggers and neither is derived from the other.

Paying an order advances `payment_status` from `PENDING` to `PAID`. This is permitted only while the order is `PENDING` and only when an `active` `PricingPolicy` exists for its park-and-product pairing; absent that policy the pay is rejected with `ERR_NO_ACTIVE_POLICY`. Paying runs the quote of §3.2, writing `subtotal_cents`, `total_cents`, `wallet_credit_used_cents`, `resident_rate_applied`, and `group_rate_applied` onto the order, then debits the guest's `wallet_credit_cents` by the credit consumed, and increments the order's `version` by one. Cancelling an order is available only while `payment_status` is `PENDING`; it advances payment to the terminal `VOID`, releases any cabana rental still in `HELD` under that order (moving it to `CANCELLED`) and decrements the affected window's `reserved_count` for each released hold, and increments the order's `version`.

Fulfilling an order is the fulfillment-dimension transition: it moves `fulfillment_status` from `UNFULFILLED` to `FULFILLED` and is allowed only once `payment_status` is `PAID` and `fulfillment_status` is still `UNFULFILLED`. An attempt to fulfill an order that is not yet paid is rejected with `ERR_ORDER_NOT_PAID`. Fulfillment mints `party_size` admission rows, each created in `ISSUED` status with a `ticket_price_cents` equal to the order's `subtotal_cents` divided by `party_size`; promotes every cabana rental still `HELD` under the order to `CONFIRMED`; and increments the order's `version`.

Refunding an order is a `FinanceClerk` action available only while `payment_status` is `PAID`, and only when no admission under the order is in `CHECKED_IN` status — a refund attempted after any admission has been consumed at the gate is rejected with `ERR_ALREADY_CONSUMED`. A successful refund credits the guest's `wallet_credit_cents` by the order's `total_cents`, conserving the wallet against the original debit and charge. It then drives a depth-three cascade: every non-terminal admission under the order moves to `CANCELLED`, and each such admission that had been holding a confirmed window slot decrements that window's `reserved_count` by one; every cabana rental under the order in `CONFIRMED` or `HELD` status moves to `CANCELLED`, decrementing the relevant window's `reserved_count`. Finally the order reaches its joint terminal posture of `REFUNDED` payment and `CANCELLED` fulfillment, and its `version` increments. Orders may be listed and filtered by `guest_id`, `park_id`, and `payment_status`, and an order's admissions, cabana rentals, and locker rentals are each retrievable as nested collections.

### 3.4. Guests, Admissions, and the Gate

A `Guest` is registered with a `full_name`, an `email` (not required to be unique within a park), a `zip_code` used to evaluate resident eligibility, and a `height_cm` of zero or greater used later to choose a wristband band. A new guest's `wallet_credit_cents` starts at 0 and is only ever credited by refunds and rain-check settlements — it is never minted on input.

Each admission minted by fulfillment records the `order_id` that produced it, the `park_id` it grants entry to, a `guest_id` that is null until a named guest is bound, an `entry_window_id` that is null until the admission is assigned to a window, and a `product_type` copied from the parent order. An admission moves through a lifecycle that begins at `ISSUED`. Binding a named guest sets the admission's `guest_id` and may be performed by the owning guest or by a `GateAgent` before check-in; it does not by itself change the admission's status.

Assigning an admission to a window advances it from `ISSUED` to `CONFIRMED`. The request supplies the target `entry_window_id` and the `expected_entry_window_version` described in §2.6. Assignment is allowed only when the admission is `ISSUED`, its parent order's `fulfillment_status` is `FULFILLED` (otherwise `ERR_ORDER_NOT_PAID`), the target window's `status` is `OPEN` (otherwise `ERR_WINDOW_NOT_OPEN`), and the window has room — meaning the sum of its `reserved_count` and `admitted_count` is strictly less than its `window_capacity`; a request that would meet or breach capacity is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`. On success the admission's `entry_window_id` is set, the window's `reserved_count` increments by one, and the window's `version` increments by one (the capacity write that the OCC check guards). A stale `expected_entry_window_version` fails with `ERR_STALE_VERSION` before capacity is touched.

Check-in is a `GateAgent` action that advances an admission from `CONFIRMED` to `CHECKED_IN`. It requires that the admission be `CONFIRMED`, that its window's `status` be `OPEN` (otherwise `ERR_WINDOW_NOT_OPEN`), that a `guest_id` be bound (otherwise `ERR_GUEST_NOT_BOUND`), and that the logical clock fall within the window's half-open interval — at or after `starts_at` and strictly before `ends_at`. A clock exactly equal to `starts_at` admits; a clock exactly equal to `ends_at` is too late and, like any out-of-interval check-in, is rejected with `ERR_WINDOW_TIME_VIOLATION`. Check-in assigns the wristband band from the guest's height and records it in `band_color`: a height of at least 122 centimeters earns `GREEN` (all attractions), a height of at least 107 but below 122 centimeters earns `YELLOW` (most attractions), and any lesser height earns `RED` (kiddie area only); the comparison is exact integer-against-floor, so a height equal to a floor takes the higher band. Check-in then decrements the window's `reserved_count` by one and increments its `admitted_count` by one, moving the guest from held to admitted.

An admission may be cancelled while it is `ISSUED`, `CONFIRMED`, or `FROZEN`, moving it to the terminal `CANCELLED`; if the admission had been `CONFIRMED` (holding a window slot), the cancel decrements the window's `reserved_count` by one. Admissions may be listed and filtered by `entry_window_id`, `guest_id`, `park_id`, and `status`.

### 3.5. Season-Pass Freeze and Unfreeze

The freeze cycle applies only to season passes. A guest may freeze an admission that is currently `CONFIRMED`, moving it to `FROZEN`, but only when the admission's `product_type` is `SEASON_PASS`; a freeze (or unfreeze) attempted on a `DAY_TICKET` admission is rejected with `ERR_FREEZE_NOT_ALLOWED`. Freezing is further gated by the cumulative `freeze_days_used`: a freeze whose entry would carry `freeze_days_used` to 30 days or beyond is rejected with `ERR_FREEZE_LIMIT_REACHED` — that is, the freeze is refused whenever the running total already stands at 30 or more before the episode begins. The thirty-day ceiling is the maximum total time a pass may spend frozen across its whole life. On a successful freeze the server stamps `frozen_at` with the current logical clock and releases the held window slot by decrementing the window's `reserved_count` by one, because a sleeping pass should not occupy capacity.

Unfreezing returns a `FROZEN` admission to `CONFIRMED`. It is permitted only when the window's `status` is either `OPEN` or `RESTRICTED`, and only when the window has room — the sum of `reserved_count` and `admitted_count` must be strictly less than `window_capacity`, failing otherwise with `ERR_WINDOW_CAPACITY_EXCEEDED`. Unfreeze performs the freeze-day accounting: it measures the elapsed time of the just-ended episode as the difference between the current logical clock and the recorded `frozen_at`, converts that elapsed time to whole days by rounding up so that any partial day counts as a full day (86,400 seconds make a day), and adds that episode's day count to the running `freeze_days_used`. It then clears `frozen_at` and re-acquires capacity by incrementing the window's `reserved_count` by one. The running total accumulates across every episode: on a pass's first freeze the running total equals just that first episode's days, and on every later episode the total grows by that episode's days. The ceiling is evaluated against the running total at the next freeze, not at unfreeze — so a pass returns from a freeze without limit, but its accumulated days follow it into the next freeze decision.

### 3.6. Cabana Rentals: Capacity, Time, and Weather

Renting a cabana is a guest operation that supplies `cabana_id`, `order_id`, `entry_window_id`, `starts_at`, `ends_at`, and `expected_entry_window_version`; the rental records a convenience copy of the cabana's `park_id`. A new rental is created in `HELD` status. Its `price_cents` is the flat `daily_rate_cents` of the cabana at booking time, charged whole regardless of how much of the day the booking actually spans. Creating the rental holds capacity on the named window: the window's `reserved_count` increments by one and its `version` increments by one. Because that capacity write is one of the two OCC-guarded operations, the request must carry `expected_entry_window_version` matching the window's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from over-committing a window it has not freshly observed. A successful create also counts against the window's capacity pool exactly as an admission assignment does, so a rental that would push the window's combined `reserved_count` and `admitted_count` to or beyond `window_capacity` is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`. When a rental shares its `entry_window_id` with other rentals, it competes against that same shared pool rather than merely against the cabana's own schedule.

Two further guards apply to cabana rentals, and together with the window-capacity check of the prior paragraph they are evaluated in a fixed order: the window-capacity check (`ERR_WINDOW_CAPACITY_EXCEEDED`) is evaluated first, the weather check second, and the time-overlap check third — so on a cabana-rental request that would trip more than one of these, the capacity guard fires before weather, and weather before time-overlap. First, weather: while the park's `weather_status` is `STORM_WATCH` or `RAINED_OUT`, new cabana sales are blocked with `ERR_WEATHER_HOLD`. Second, time-overlap on the same physical cabana: the requested interval must be valid, with `starts_at` strictly before `ends_at`, and it must not collide with any non-terminal rental already on that cabana — any rental in `HELD` or `CONFIRMED` status. The collision test expands each existing rental on its end side by the cabana's `turnover_buffer_minutes`, the mandatory cleaning gap, and treats the new rental as colliding when its `starts_at` falls before the prior rental's `ends_at` plus that buffer and its `ends_at` falls after the prior rental's `starts_at`. A new rental whose start lands exactly at a prior rental's buffered end is adjacent, not overlapping, and is allowed. A genuine collision is rejected with `ERR_CABANA_OVERLAP`.

A cabana rental tracks its own status. It is created `HELD`. When its parent order is fulfilled, the rental is promoted from `HELD` to `CONFIRMED` as a side effect of fulfillment, provided the order's `payment_status` is `PAID`; this promotion changes no capacity, since the slot was already held at `HELD`. A guest or manager may cancel a rental that is `HELD` or `CONFIRMED`, moving it to the terminal `CANCELLED` and decrementing the window's `reserved_count` by one. Cabana rentals may be listed and filtered by `park_id`, `entry_window_id`, `cabana_id`, `order_id`, and `status`, and the rentals on a single cabana may be listed directly.

### 3.7. Locker Rentals

A locker rental is a lightweight, immutable record created by a guest against `locker_id`, `order_id`, `starts_at`, and `ends_at`. Its charge is computed once at creation and never revised. The duration is the difference between `ends_at` and `starts_at`, expressed in hours by dividing the elapsed seconds by 3,600; `hours_billed` is that duration rounded up to the next whole hour, so that every started hour bills a full hour. Exactly sixty minutes bills as one hour, sixty-one minutes bills as two, and a zero-length interval is invalid. The `price_cents` is `hours_billed` multiplied by the locker's `hourly_rate_cents`. Locker rentals under an order, and the rentals on a single locker, are each retrievable as collections.

### 3.8. Weather Rain-Out and the Cascade to Rain-Checks

When the park's `weather_status` has been set to `RAINED_OUT`, a `ParkManager` may rain out an individual window, moving it from `OPEN` or `RESTRICTED` to the terminal `RAINED_OUT` status. This single action is a fan-out trigger feeding two distinct downstream cascades. First, every admission on that window in `CONFIRMED` or `FROZEN` status moves to `RAINED_OUT`; for each, the window's `reserved_count` decrement is accounted, and a rain-check voucher is issued to that admission's guest when a `guest_id` is bound, with the voucher's `source_kind` recorded as `ADMISSION` and its `source_ref_id` pointing at the rained-out admission. Second, every cabana rental on that window in `CONFIRMED` or `HELD` status moves to `RAINED_OUT`, and each issues a rain-check to the order's guest with `source_kind` of `CABANA_RENTAL` and `source_ref_id` pointing at the rained-out rental. After both cascades complete, the window's `reserved_count` is set to zero, and the park's `open_window_count` is recomputed if the window had been `OPEN`.

A `RainCheck` records the issuing `park_id`, the holder's `guest_id`, the `source_kind` discriminator (`ADMISSION` or `CABANA_RENTAL`), and the `source_ref_id` resolved against that discriminator — `source_ref_id` is not a single-target foreign key but a polymorphic reference whose meaning depends on `source_kind`. Each voucher's `value_cents` is set at issuance from the park's `rain_check_value_cents`, and the voucher opens in `ISSUED` status. A `FinanceClerk` settles an `ISSUED` voucher, moving it to the terminal `SETTLED` and crediting the holder's `wallet_credit_cents` by the voucher's `value_cents`, which is the compensating credit that conserves the guest's wallet against forgone gate revenue. Alternatively, a `ParkManager` expires an `ISSUED` voucher, moving it to the terminal `EXPIRED` with no wallet credit. A settle or expire attempted on a voucher that is not in `ISSUED` status is rejected with `ERR_RAINCHECK_NOT_ISSUED`. Rain-checks may be listed and filtered by `guest_id`, `park_id`, and `status`.

### 3.9. The Logical Clock

A `ParkManager` holds an administrative test-driving capability that advances the server's logical clock to a supplied `to_iso8601` instant, written into `ClockState.current_utc`. Every time comparison in the system — the half-open window interval at check-in and the elapsed-time measurement during freeze-day accounting — reads this value rather than the host wall clock, so that scheduling behavior is fully deterministic and reproducible.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource, including the state-transition and weather operations, return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers of §2.1, and the authorized roles for each operation are listed below. Request and response bodies are not restated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parks` | Create a park | ParkManager |
| GET | `/parks/{id}` | Fetch a park | ParkManager, GateAgent, FinanceClerk, Guest |
| GET | `/parks` | List parks | ParkManager, GateAgent, FinanceClerk, Guest |
| POST | `/parks/{id}/weather` | Set park weather posture | ParkManager |
| POST | `/pricing-policies` | Create/supersede the active pricing policy | ParkManager |
| GET | `/pricing-policies` | List pricing policies | ParkManager, Guest |
| GET | `/pricing-policies/{id}` | Fetch a pricing policy | ParkManager, Guest |
| POST | `/parks/{id}/entry-windows` | Create a timed-entry window under a park | ParkManager |
| GET | `/parks/{id}/entry-windows` | List a park's entry windows | ParkManager, GateAgent, Guest |
| GET | `/entry-windows/{id}` | Fetch an entry window | ParkManager, GateAgent, Guest |
| POST | `/entry-windows/{id}/restrict` | Restrict a window | ParkManager |
| POST | `/entry-windows/{id}/reopen` | Reopen a restricted window | ParkManager |
| POST | `/entry-windows/{id}/close` | Close a window | ParkManager |
| POST | `/entry-windows/{id}/rain-out` | Rain out a window; cascade to admissions and rentals | ParkManager |
| POST | `/parks/{id}/cabanas` | Create a cabana under a park | ParkManager |
| GET | `/parks/{id}/cabanas` | List a park's cabanas | ParkManager, Guest |
| GET | `/cabanas/{id}` | Fetch a cabana | ParkManager, Guest |
| POST | `/parks/{id}/lockers` | Create a locker under a park | ParkManager |
| GET | `/parks/{id}/lockers` | List a park's lockers | ParkManager, Guest |
| GET | `/lockers/{id}` | Fetch a locker | ParkManager, Guest |
| POST | `/guests` | Register a guest | Guest, ParkManager |
| GET | `/guests/{id}` | Fetch a guest | Guest, ParkManager, GateAgent, FinanceClerk |
| POST | `/orders` | Create an order | Guest |
| GET | `/orders/{id}` | Fetch an order | Guest, FinanceClerk, ParkManager |
| GET | `/orders` | List orders | Guest, FinanceClerk, ParkManager |
| POST | `/orders/{id}/pay` | Pay an order; run the quote | Guest |
| POST | `/orders/{id}/cancel` | Cancel an unpaid order | Guest |
| POST | `/orders/{id}/fulfill` | Fulfill a paid order | Guest |
| POST | `/orders/{id}/refund` | Refund a paid order; cascade-cancel | FinanceClerk |
| GET | `/orders/{id}/admissions` | List admissions minted by an order | Guest, FinanceClerk, ParkManager, GateAgent |
| GET | `/orders/{id}/cabana-rentals` | List cabana rentals under an order | Guest, FinanceClerk, ParkManager |
| GET | `/orders/{id}/locker-rentals` | List locker rentals under an order | Guest, FinanceClerk, ParkManager |
| GET | `/admissions/{id}` | Fetch an admission | Guest, GateAgent, ParkManager, FinanceClerk |
| GET | `/admissions` | List admissions | Guest, GateAgent, ParkManager, FinanceClerk |
| POST | `/admissions/{id}/bind-guest` | Bind a named guest to an admission | Guest, GateAgent |
| POST | `/admissions/{id}/assign-window` | Assign an admission to a window (OCC-guarded) | Guest |
| POST | `/admissions/{id}/check-in` | Gate check-in; assign band color | GateAgent |
| POST | `/admissions/{id}/freeze` | Freeze a season pass | Guest |
| POST | `/admissions/{id}/unfreeze` | Unfreeze a season pass | Guest |
| POST | `/admissions/{id}/cancel` | Cancel a non-terminal admission | Guest, ParkManager |
| POST | `/cabana-rentals` | Rent a cabana for a window (OCC-guarded) | Guest |
| GET | `/cabana-rentals/{id}` | Fetch a cabana rental | Guest, ParkManager, FinanceClerk |
| GET | `/cabana-rentals` | List cabana rentals | Guest, ParkManager, FinanceClerk |
| GET | `/cabanas/{id}/cabana-rentals` | List rentals on a cabana | Guest, ParkManager |
| POST | `/cabana-rentals/{id}/cancel` | Cancel a cabana rental | Guest, ParkManager |
| POST | `/locker-rentals` | Rent a locker | Guest |
| GET | `/locker-rentals/{id}` | Fetch a locker rental | Guest, ParkManager, FinanceClerk |
| GET | `/lockers/{id}/locker-rentals` | List rentals on a locker | Guest, ParkManager |
| GET | `/rain-checks/{id}` | Fetch a rain-check voucher | Guest, FinanceClerk, ParkManager |
| GET | `/rain-checks` | List rain-checks | Guest, FinanceClerk, ParkManager |
| POST | `/rain-checks/{id}/settle` | Settle a rain-check; credit guest wallet | FinanceClerk |
| POST | `/rain-checks/{id}/expire` | Expire a rain-check without crediting | ParkManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | ParkManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_GUEST_NOT_BOUND` | 409 |
| `ERR_WINDOW_TIME_VIOLATION` | 409 |
| `ERR_CABANA_OVERLAP` | 409 |
| `ERR_FREEZE_NOT_ALLOWED` | 409 |
| `ERR_FREEZE_LIMIT_REACHED` | 409 |
| `ERR_ORDER_NOT_PAID` | 409 |
| `ERR_WEATHER_HOLD` | 409 |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 409 |
| `ERR_ALREADY_CONSUMED` | 409 |
| `ERR_RAINCHECK_NOT_ISSUED` | 409 |
| `ERR_NO_ACTIVE_POLICY` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
