# Recording / Rehearsal Studio Booking API — Product Requirements Document

## 1. Introduction

Recording and rehearsal facilities live and die by the calendar. A single mid-sized studio juggles a handful of rooms, a roster of engineers, a cage of rentable gear, and a stream of clients — bands, producers, podcasters — who each want a slice of the same finite hours. The operational pain is twofold: the schedule must never double-book a room or an engineer, and the money must reconcile to the cent across deposits, balances, overtime surcharges, gear add-ons, and refunds. When a session runs long, the bill changes; when a client cancels, a refund must be computed against how much warning they gave; when a studio reserves a room for a recurring lockout, dozens of occurrence bookings must be materialized at once without colliding with anything already on the books.

This API is the system of record for that entire lifecycle. It manages room, engineer, and gear inventory; it holds, confirms, runs, and closes out individual bookings; it assigns engineers and rents gear as add-ons; it tracks deposits and overtime, issues tiered cancellation refunds, supports recurring lockout contracts, and delivers finished session files through a revision loop. A defining characteristic of the domain is that every booking advances along **two independent axes at once** — a calendar lifecycle and a money lifecycle — and the two only meet at a few well-defined moments. Implementers should treat the schedule dimension and the settlement dimension as separate state machines riding on the same record, because nearly all of the subtle behavior in this system comes from the places where they interact.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint. The API is mounted under the `/studio` path prefix.

### 2.1. User and Role-Based Access Control

Every request, except the two open bootstrap operations described below, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. A request that omits either header, or carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. A request that is well-formed but whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `StudioManager`, `Client`, `Engineer`, and `Anonymous`.

- A `StudioManager` operates the facility. This role is the operational superset for inventory and schedule control: it bootstraps studios, creates rooms, engineers, and gear, confirms and cancels bookings, checks sessions in and out, manages gear and engineer assignments, and authors lockout contracts. When `X-User-Role` is `StudioManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`.
- A `Client` books rooms, pays, rents gear, requests revisions, and accepts deliveries. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity; any ownership check on a resource that references a client compares the resource's `client_id` to `X-User-ID`. A client may only act on bookings whose `client_id` equals their own `X-User-ID`.
- An `Engineer` delivers and re-delivers session files for bookings they are assigned to. When `X-User-Role` is `Engineer`, `X-User-ID` is the `id` of the acting `Engineer` entity; an engineer may only act on the delivery of a booking that carries one of their own `EngineerAssignment` records, and ownership is enforced by matching the assignment's `engineer_id` to `X-User-ID`.
- An `Anonymous` caller is unauthenticated. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is never compared to any entity's `id`. The only operations this role may perform are client self-registration and the studio bootstrap; both are deliberately open so that a brand-new client or a brand-new studio can come into existence before any credentialed principal exists.

Ownership violations — a client reaching for someone else's booking, or an engineer reaching for a delivery on a booking they are not assigned to — are rejected with `ERR_FORBIDDEN`, the same code used for a flat role-permission failure.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip from the front of the result set and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response includes the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every primary resource — `Studio`, `Room`, `Engineer`, `GearItem`, `Client`, `Booking`, `GearRental`, `EngineerAssignment`, `Payment`, `LockoutContract`, and `SessionDelivery` — carries a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID. It carries no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: a system-managed integer that begins at its initial value and increments by exactly one on every mutation. It is the basis for optimistic concurrency control (§2.10).

Two entities are deliberately leaner. An `OvertimeRecord` and the `Clock` carry only `id` and `created_at`; they do **not** expose `updated_at` or `version`, because an overtime record is written once at check-out and never mutated, and the clock is a server-controlled singleton. Implementations must not surface `updated_at` or `version` on those two.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a child through its parent — for example, the gear rentals, engineer assignments, payments, overtime records, and delivery of a particular booking. When a path contains more than one identifier, the system validates existence strictly left-to-right: the parent identifier in the path is resolved before the child, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`. After the path identifiers are resolved, any foreign keys carried in the request body are validated in turn; a body that references a non-existent studio, room, engineer, gear item, client, booking, or contract is likewise rejected with `ERR_NOT_FOUND`. This existence sweep runs only after authentication and authorization have passed, so that a caller never learns whether a resource exists unless they were entitled to ask.

### 2.6. Money, Precision, and Rounding

All monetary amounts in this system are integer counts of cents — `hourly_rate_cents`, `block_rate_cents`, `daily_rate_cents`, `base_charge_cents`, `deposit_due_cents`, `overtime_cents`, `total_charge_cents`, `amount_paid_cents`, `amount_cents`, `charge_cents`, `room_surcharge_cents`, `engineer_surcharge_cents`, and `wallet_credit_cents` are all stored and returned as whole-cent integers. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent before it is stored. The order of operations matters and is specified per calculation in §3: where a formula calls for rounding hours or blocks or rental-days up to a whole unit, that ceiling is applied to the time quantity *first*, and only the rounded quantity is multiplied by the per-unit rate. Configuration fractions such as `deposit_pct`, `overtime_multiplier`, and `late_cancel_fee_pct` preserve their input precision and are not themselves rounded.

### 2.7. The Two-Axis Booking Lifecycle

A `Booking` is the pivot of the entire system, and it is unusual in that it carries **two independent status dimensions that evolve separately**. The `schedule_status` field is the calendar lifecycle and takes one of `HELD`, `CONFIRMED`, `IN_SESSION`, `COMPLETED`, or `CANCELLED`. The `settlement_status` field is the money lifecycle and takes one of `AWAITING_DEPOSIT`, `DEPOSIT_PAID`, `BALANCE_DUE`, `SETTLED`, `REFUNDING`, or `REFUNDED`. A single booking row advances on each axis on its own schedule: a `CONFIRMED` booking may be either `DEPOSIT_PAID` or `BALANCE_DUE` depending purely on payment events, and an `IN_SESSION` booking remains `DEPOSIT_PAID` until check-out reconciles the balance. The two axes only synchronize at the moments §3 calls out explicitly — confirmation requires a paid deposit, check-out moves settlement from `DEPOSIT_PAID` to `BALANCE_DUE`, and cancellation drives settlement through the refund branch. State enumeration values throughout this document are exact and case-sensitive.

A booking creation begins both axes at their initial states: `schedule_status` is `HELD` and `settlement_status` is `AWAITING_DEPOSIT`. The terminal calendar states are `COMPLETED` and `CANCELLED`; the terminal settlement states are `SETTLED` and `REFUNDED`. Any attempt to drive a transition that is not defined from the resource's current `schedule_status`, `settlement_status`, contract `status`, or delivery `status` is rejected with `ERR_INVALID_STATE`.

### 2.8. Cascades, Reconciliation, and Version Semantics

Several operations touch more than one entity. Whenever a booking is cancelled, the system does not merely flip its `schedule_status` to `CANCELLED`; it also releases every child of that booking — each `GearRental` moves from `RESERVED` to `RELEASED`, freeing the units it had reserved, and each `EngineerAssignment` moves from `ASSIGNED` to `RELEASED` — and it drives the settlement axis through the refund branch. Each such cascade is a real mutation: the affected child's `updated_at` is refreshed and its `version` increments by one, and the booking's own `version` increments by one as well. Terminating a lockout contract cascades transitively: each future occurrence it cancels in turn releases that occurrence's own gear rentals and engineer assignments. Whenever this document says an operation "increments the version" of a resource, it means exactly that the integer `version` rises by one and `updated_at` is refreshed on the same write.

### 2.9. Room Turnaround and Temporal Occupancy

A room is never instantaneously reusable. Each `Room` carries a `turnaround_minutes` buffer (defaulting to 30) that must elapse after a booking's scheduled end before the room may be occupied again. Consequently, the occupancy footprint of a booking is not `[start_at, end_at)` but `[start_at, end_at + turnaround_minutes)`. Two bookings on the same room conflict whenever those buffered intervals overlap. This buffered footprint is what the confirmation overlap check (§3) evaluates, and it is checked only against bookings whose `schedule_status` is `CONFIRMED` or `IN_SESSION` — a merely `HELD` booking does not yet reserve the calendar.

### 2.10. Optimistic Concurrency Control

Two specific write operations require the client to prove it is acting on a fresh view of a parent resource, using an optimistic-concurrency token.

When a gear rental is added to a booking, the request must carry `expected_booking_version`, which is a non-optional field carrying the client's last observed `version` of the target booking. If that value does not equal the booking's current `version` — because another writer has since added a gear line, recorded a payment, or otherwise cascaded a mutation onto the booking and thereby recomputed its derived totals — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a writer from reserving gear against a stale picture of what the booking already holds and what units remain available for its window.

When a lockout contract is activated, the request must carry `expected_room_version`, a non-optional field carrying the client's last observed `version` of the room the contract targets. If another writer has advanced the room's `version` in the interim — for instance by locking it under a different contract — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), because the activation's belief that the room is still `OPEN` is stale.

No other endpoint accepts or requires a version field; only these two carry an OCC token, and only these two can fail with `ERR_STALE_VERSION`.

### 2.11. The Logical Clock

All time-relative computations — hold expiry, cancellation tiering, the auto-release sweep, and the check that a session has actually started — read a single server-controlled wall clock rather than the host's real time. That clock exposes a `current_utc` instant. A test-driving capability lets an operator set this instant directly by supplying a `to_iso8601` timestamp, and a separate sweep capability advances the system by releasing holds that have outlived their expiry against the current clock value. Because every temporal rule reads `current_utc`, moving the clock forward is the only way "time passes" in this system.

### 2.12. Validation Ordering

Before any of the ordered domain checks run, a request must be structurally well-formed: a payload that omits a required body field, carries a value of the wrong type, supplies an unrecognized enum value, or sends a negative amount where a positive magnitude is required is rejected outright with `ERR_INVALID_REQUEST` (HTTP 400). This structural screen is distinct from `ERR_VALIDATION` (HTTP 422), which is reserved for values that pass type-checking but violate a semantic bound — a `deposit_pct` outside the open-lower, closed-upper unit interval, an empty `weekday_mask`, or a `units` count below one.

When several checks could fire on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first; then role permission (`ERR_FORBIDDEN`); then existence of every path and body resource, left-to-right (`ERR_NOT_FOUND`); then resource ownership for client- and engineer-scoped operations (`ERR_FORBIDDEN`); then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); then the optimistic-concurrency token where one applies (`ERR_STALE_VERSION`); and only then the domain-specific temporal, safety, capacity, and fiscal checks described throughout §3. A consequence worth internalizing: a stale-version rejection can only surface after the target has already passed its state check, and a permission failure always pre-empts any business rule.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Studio and Its Inventory

Everything begins with a `Studio`, brought into being by the bootstrap operation. A studio is created with a `name` and optionally a `timezone` (an IANA zone used to interpret local booking times, defaulting to `UTC`) along with the commercial constants that govern its economics: `deposit_pct` (the fraction of a booking's room charge demanded as a deposit at confirmation, defaulting to 0.30 and constrained to be greater than 0 and at most 1), `overtime_multiplier` (the surcharge factor applied to the room rate for overtime minutes, defaulting to 1.5 and required to be at least 1), `overtime_grace_minutes` (minutes a session may run past its scheduled end before overtime billing begins, defaulting to 10 and required to be zero or greater), `cancellation_tier_hours` (the hours-before-start cutoff separating the full-refund tier from the partial-refund tier, defaulting to 48 and required to be zero or greater), and `late_cancel_fee_pct` (the fraction of the room charge the studio retains as a fee when a client cancels inside the partial tier, defaulting to 0.50 and constrained to be between 0 and 1 inclusive). A value that passes type-checking but violates one of these bounds — a `deposit_pct` outside the open-lower closed-upper range, for example — is rejected with `ERR_VALIDATION`.

Against a studio, a `StudioManager` builds out inventory. A `Room` is created with its parent `studio_id`, a `name`, an `hourly_rate_cents`, a `block_rate_cents` (the flat price of one full block), a `block_hours` count (how many contiguous hours one block covers, defaulting to 8), and the `turnaround_minutes` buffer (defaulting to 30). Every room also carries a computed `status` that is `OPEN` while the room is freely bookable and `LOCKED` while a lockout contract holds it; rooms start `OPEN`. An `Engineer` is created with a `studio_id`, a `full_name`, a `tier` (one of `ASSISTANT`, `STAFF`, or `SENIOR`), an `hourly_rate_cents` labor rate, and an `active` flag (defaulting to true) that gates whether the engineer may be assigned to new work. A `GearItem` is created with a `studio_id`, a `name`, a `total_units` count of how many physical units the studio owns, a `daily_rate_cents` rental rate charged per unit per started rental-day, and a `requires_engineer` flag (defaulting to false) that, when set, means any rental of this item obliges the booking to carry an engineer. All inventory rates and counts are constrained to be non-negative, and `total_units` must be at least one.

A `Client` comes into existence through open self-registration, supplying a `studio_id`, a `display_name` (the band or client name), and an `email`. The email must be unique within the studio; a second registration reusing an email already on file at that studio is rejected with `ERR_DUPLICATE_EMAIL`. Each client also carries a computed `wallet_credit_cents` balance, initialized to 0, which holds refund credit and is later consumed against balance payments — described in §3.6.

### 3.2. Holding, Pricing, and Confirming a Booking

A booking is born when a `StudioManager` or `Client` requests one, supplying the `studio_id`, the `room_id`, the `client_id`, the `booking_kind` (one of `HOURLY`, `BLOCK`, or `LOCKOUT`), and the scheduled window as `start_at` and `end_at` (both ISO 8601 UTC). The `end_at` must be strictly later than `start_at`; a window where the end does not strictly follow the start is rejected with `ERR_INVALID_TIME_RANGE`. On a successful create the booking lands with `schedule_status` `HELD` and `settlement_status` `AWAITING_DEPOSIT`, and the server immediately computes its `base_charge_cents`, derives its `deposit_due_cents`, and stamps a `hold_expires_at` exactly 24 hours after the current clock instant, after which an unconfirmed hold is eligible for auto-release. A standalone booking has a null `parent_series_id`; this foreign key is populated only on occurrences materialized from a recurring anchor (§3.7), and the `is_series_anchor` flag — false by default — marks the one booking that anchors such a series.

The room time charge, `base_charge_cents`, is computed from the scheduled duration and the booking kind. First take the scheduled duration in hours as the difference between `end_at` and `start_at` expressed in hours. For an `HOURLY` booking, round that duration **up to the next whole hour** (any partial hour becomes a full billable hour) and multiply the resulting whole-hour count by the room's `hourly_rate_cents`. For a `BLOCK` or `LOCKOUT` booking, divide the duration in hours by the room's `block_hours`, round that quotient **up to the next whole block** (a session that straddles a block boundary buys another entire block, so a nine-hour booking against an eight-hour block costs two blocks), and multiply the whole-block count by the room's `block_rate_cents`. In both branches the ceiling is applied to the hour or block count before multiplying by the rate, and the result is an integer number of cents.

The deposit, `deposit_due_cents`, is the room charge scaled by the studio's deposit fraction: multiply `base_charge_cents` by the studio's `deposit_pct` and round the product half up to a whole cent.

Confirmation is a `StudioManager` action that advances `schedule_status` from `HELD` to `CONFIRMED`. It is permitted only when the booking is currently `HELD`, when its `settlement_status` is `DEPOSIT_PAID` (the deposit payment has cleared), and when the room is bookable — meaning the room's `status` is `OPEN`, or this booking is itself an occurrence of the very lockout contract that `LOCKED` the room. The confirmation additionally enforces that the room is free: the requested footprint `[start_at, end_at + turnaround_minutes)` must not overlap the footprint of any other booking on the same room whose `schedule_status` is `CONFIRMED` or `IN_SESSION`. A collision is rejected with `ERR_ROOM_UNAVAILABLE`. On success the booking's `hold_expires_at` is cleared to null and its `version` increments by one. If the booking is not in `HELD` when confirmation is attempted, the transition is undefined and the request fails with `ERR_INVALID_STATE`.

### 3.3. Running and Closing the Session

Once a booking is `CONFIRMED`, a `StudioManager` checks the session in, advancing `schedule_status` from `CONFIRMED` to `IN_SESSION`. Check-in is permitted only when the booking is `CONFIRMED`, when the clock has reached or passed `start_at` (the current instant is at or after the scheduled start), and when a crucial safety condition holds: every `GearRental` on the booking whose underlying `GearItem` has `requires_engineer` set to true must be matched by at least one `ASSIGNED` `EngineerAssignment` on the same booking. If a piece of engineer-required gear is reserved with no engineer present, check-in is refused with `ERR_ENGINEER_REQUIRED`. The check-in increments the booking's `version`.

Check-out is the reconciliation moment. A `StudioManager` ends the session by supplying the real end timestamp `actual_end_at`, which must be present and at or after `start_at`. Check-out advances `schedule_status` from `IN_SESSION` to `COMPLETED` and, on the money axis, moves `settlement_status` from `DEPOSIT_PAID` to `BALANCE_DUE`, because the full bill is now known and the balance is owed. Several computations fire here in concert. First an `OvertimeRecord` is created and the overtime surcharge is computed (§3.4). Then each engineer assignment's billed figure is finalized: its `billed_hours` and `charge_cents` are recomputed using the actual overtime hours rather than the original estimate (§3.5). Finally the grand total is reconciled: `total_charge_cents` becomes the sum of `base_charge_cents`, the sum of every `GearRental.charge_cents` on the booking, the sum of every `EngineerAssignment.charge_cents` at its finalized `billed_hours`, and the booking's `overtime_cents`. The booking's `version` increments. The booking must be `IN_SESSION` for check-out to be defined; otherwise `ERR_INVALID_STATE`.

### 3.4. Overtime

Overtime is assessed exactly once, at check-out, and captured in the `OvertimeRecord` for the booking (an overtime record references its `booking_id`). Its purpose is to bill the minutes a session ran past its scheduled end, after a grace allowance.

Begin with the raw overage: the whole number of minutes between `actual_end_at` and `end_at`, floored at zero so that a session ending early contributes nothing. From that raw overage subtract the studio's `overtime_grace_minutes`, and floor the result at zero — this yields the billable `overage_minutes`. The grace is subtracted from the raw minutes *before* any conversion to hours, and billing is triggered only when `overage_minutes` ends up strictly greater than zero (equivalently, only when the raw overage strictly exceeds the grace allowance); a session that runs over by no more than the grace incurs no overtime.

From the billable minutes two surcharges are derived. The `room_surcharge_cents` is the billable minutes expressed as a fraction of an hour (`overage_minutes` divided by 60), multiplied by the room's `hourly_rate_cents`, multiplied by the studio's `overtime_multiplier`, with the product rounded half up to a whole cent. The `engineer_surcharge_cents` is summed across the booking's non-released engineer assignments: for each `ASSIGNED` assignment, take the billable minutes as a fraction of an hour, round that hour figure **up to the next quarter hour**, multiply by that engineer's `hourly_rate_cents`, round half up to a whole cent, and add it to the running total. The booking's `overtime_cents` is the room surcharge plus the summed engineer surcharge.

### 3.5. Engineer Assignments

A `StudioManager` assigns an engineer to a booking by supplying the `engineer_id`; the assignment records its `booking_id` and `engineer_id` and starts in `ASSIGNED` status. An assignment may not be created against an engineer who is inactive (`active` is false), nor against an engineer who already holds an `ASSIGNED` assignment on another booking whose window overlaps this one — either condition is rejected with `ERR_ENGINEER_UNAVAILABLE`. Creating an assignment increments the parent booking's `version`.

At assignment time the system records a forward-looking estimate. The assignment's `scheduled_hours` is the booking's scheduled duration in hours rounded **up to the next quarter hour**: take the difference between `end_at` and `start_at` in hours, multiply by four, round up to a whole number, and divide by four. The estimate `charge_cents` is `scheduled_hours` multiplied by the engineer's `hourly_rate_cents`, rounded half up to a whole cent. This estimate deliberately ignores overtime — it is the figure quoted before the session runs.

At check-out the same assignment is finalized to its actual figure. The `billed_hours` becomes `scheduled_hours` plus the overtime portion, where the overtime portion is the billable overage minutes expressed in hours and rounded **up to the next quarter hour** (the overtime hours multiplied by four, rounded up, divided by four). The final `charge_cents` is `billed_hours` multiplied by the engineer's `hourly_rate_cents`, rounded half up to a whole cent. Because it folds in real overtime, the finalized charge can exceed the original estimate; the estimate is the forward-looking figure quoted at assignment, while the finalized figure is the actual amount billed.

A `StudioManager` may release an assignment, moving it from `ASSIGNED` to `RELEASED`, but only while the parent booking has not advanced into `IN_SESSION` or `COMPLETED` — release is forbidden once the session has begun or closed, and an attempt against a booking already in one of those states is rejected with `ERR_INVALID_STATE`. Releasing increments the assignment's `version`. Assignments are also released automatically as a cascade when their booking is cancelled.

### 3.6. Gear Rentals, Deposits, Balances, and the Wallet

A gear rental is an add-on attached to a booking by a `StudioManager` or `Client`, naming the `gear_item_id`, the number of `units`, and the optimistic-concurrency token `expected_booking_version`. The token must match the booking's current `version` or the add fails with `ERR_STALE_VERSION` (§2.10). The rental records its `booking_id`, starts in `RESERVED` status, and is priced as follows: take the booking's scheduled duration in hours, divide by 24, round **up to the next whole day**, and treat the result as `rental_days` with a floor of one (so any session of 24 hours or less is one rental-day, and each started 24-hour window counts as a full day). The `charge_cents` is `units` multiplied by `rental_days` multiplied by the gear item's `daily_rate_cents`. Adding a rental reserves the units and increments the booking's `version`.

Gear capacity is finite. A rental is refused with `ERR_GEAR_UNAVAILABLE` when the sum of `units` across all `RESERVED` rentals of the same `GearItem` whose booking windows overlap the new booking's window would exceed that item's `total_units`. A `units` value below one fails as `ERR_VALIDATION`. A `StudioManager` may release a rental, moving it from `RESERVED` to `RELEASED` and freeing its reserved units, provided the parent booking has not reached `COMPLETED`; releasing increments the rental's `version`, and rentals are also released as a cascade when their booking is cancelled.

Payments ride the settlement axis. A `Payment` records its `booking_id`, the paying `client_id`, a `kind` (one of `DEPOSIT`, `BALANCE`, or `REFUND`), an `amount_cents` magnitude (at least 1, with direction carried by the kind rather than the sign), and, for refunds, a `refund_destination` (`ORIGINAL` or `WALLET`, defaulting to `ORIGINAL`, and ignored for deposits and balances). A payment also carries a computed `reversed` flag, false by default, set true when a later compensating refund reverses it. Posting a payment recomputes the booking's `amount_paid_cents`, the sum of all non-reversed inbound (`DEPOSIT` and `BALANCE`) payments, and increments the booking's `version`.

A deposit is paid by the `Client` and moves `settlement_status` from `AWAITING_DEPOSIT` to `DEPOSIT_PAID`. The deposit must be exact: its `amount_cents` must equal the booking's `deposit_due_cents`, with no partial deposits accepted, and a mismatch is rejected with `ERR_DEPOSIT_MISMATCH`. A deposit attempted when settlement is not `AWAITING_DEPOSIT` is an undefined transition and fails with `ERR_INVALID_STATE`.

A balance payment settles the bill and moves `settlement_status` from `BALANCE_DUE` to `SETTLED`. The amount owed is settled through a waterfall: the remaining balance is `total_charge_cents` minus `amount_paid_cents`; the client's `wallet_credit_cents` is consumed *first*, applying the smaller of the wallet balance and the remaining balance, and only the residue must be covered by the external payment. The submitted balance `amount_cents` must equal that external residue exactly — that is, the remaining balance minus the wallet amount applied. When the wallet fully covers the remaining balance, the external requirement is zero, and any balance payment with a positive `amount_cents` is therefore rejected; any deviation from the exact external requirement is rejected with `ERR_BALANCE_MISMATCH`. On a successful balance payment the wallet is drained by exactly the amount applied (the client's `wallet_credit_cents` is decremented by the wallet portion), `amount_paid_cents` is recomputed, and the booking's `version` increments. A balance payment attempted when settlement is not `BALANCE_DUE` fails with `ERR_INVALID_STATE`. When the client holds no wallet credit, the external requirement is simply the whole remaining balance.

### 3.7. Cancellation, Refunds, and the Auto-Release Sweep

A booking may be cancelled by a `StudioManager` or `Client` while its `schedule_status` is `HELD` or `CONFIRMED`. Cancelling a `CONFIRMED` booking carries one extra guard: the clock must still be before `start_at`, because a session cannot be cancelled once it has begun; a cancel attempted on a `CONFIRMED` booking at or after `start_at` is rejected with `ERR_CANCEL_TOO_LATE`. A cancel against a booking in any other schedule state is an undefined transition and fails with `ERR_INVALID_STATE`. Cancellation drives `schedule_status` to `CANCELLED`, releases every gear rental and engineer assignment on the booking, computes the refund, and — if any money had been paid — creates a `REFUND` payment whose `refund_destination` is `WALLET` (studio policy issues all cancellation refunds as wallet credit). On the money axis the settlement moves through `REFUNDING` and then to `REFUNDED`, and when the refund lands in the wallet the client's `wallet_credit_cents` is increased by the refunded amount. Each of these mutations bumps the relevant `version`.

The refund amount is tiered. If the booking was never confirmed — it is being cancelled while still `HELD` — the client is refunded in full whatever they had paid: the refund equals `amount_paid_cents`. Otherwise, compute the hours before start as the difference between `start_at` and the current clock instant expressed in hours. If that figure is greater than or equal to the studio's `cancellation_tier_hours`, the cancellation falls in the full-refund tier and the refund again equals `amount_paid_cents`; the boundary is inclusive, so cancelling at exactly the cutoff still earns a full refund. If the hours before start fall short of the cutoff, the cancellation is in the partial tier: the studio retains a fee equal to `base_charge_cents` multiplied by `late_cancel_fee_pct` rounded half up to a whole cent, and the refund is the amount paid minus that fee, floored at zero so the refund never goes negative.

Holds do not live forever. When a booking is created it is stamped with `hold_expires_at` 24 hours out, and a sweep capability releases every still-`HELD` booking whose `hold_expires_at` has fallen before the current clock instant. Each swept booking has its `schedule_status` driven to `CANCELLED` and its children released, and if a deposit had already been paid its settlement moves through `REFUNDING` to `REFUNDED`. The sweep reports how many bookings it released and which ones, returning a `released_count` and the list of `released_booking_ids`.

### 3.8. Recurring Lockout Contracts

A studio that wants to reserve a room for a recurring client — a band that rehearses every Tuesday and Thursday evening for a season — uses a `LockoutContract`. A `StudioManager` drafts one with its `studio_id`, `room_id`, and `client_id`, a `weekday_mask` (a non-empty list of ISO weekday integers from 1 for Monday through 7 for Sunday, each value required to be within that range), a `daily_start_local` and `daily_end_local` as local `HH:MM` strings applied on each masked weekday, and a `window_start_date` and `window_end_date` as UTC-midnight calendar dates bounding the active span inclusively. The `daily_end_local` must be later than `daily_start_local`, or the draft is rejected with `ERR_INVALID_TIME_RANGE`; an empty `weekday_mask` is an `ERR_VALIDATION`. A contract's `status` progresses through `DRAFT`, `ACTIVE`, and the terminal `TERMINATED`. A freshly drafted contract has `status` `DRAFT` and an `occurrences_generated` count of zero.

Activation is where the contract bites. A `StudioManager` activates a `DRAFT` contract, supplying `expected_room_version` to prove a fresh view of the room (§2.10). Activation is permitted only when the contract is `DRAFT` and the room's `status` is `OPEN`, and only when none of the occurrence windows the contract would generate collides with any `CONFIRMED` or `IN_SESSION` booking already on the room. Because lockout occurrences belong to one contract, their windows use closed-interval day boundaries and no turnaround buffer is inserted between same-contract occurrences; a collision against outside bookings is rejected with `ERR_LOCKOUT_CONFLICT`. On success the room's `status` becomes `LOCKED`; the system materializes one anchor booking (with `is_series_anchor` true and `booking_kind` `LOCKOUT`) plus one occurrence booking for each masked weekday falling inside the window, each occurrence pointing back to the anchor through its `parent_series_id` and created already `CONFIRMED` on the schedule axis and `DEPOSIT_PAID` on the settlement axis. The `occurrences_generated` field is set to the count of occurrences materialized, and the contract's `version` increments.

Termination unwinds an `ACTIVE` contract, driving its `status` to `TERMINATED`. A `StudioManager` terminates it, the room's `status` returns to `OPEN`, and every future occurrence booking — each occurrence whose `start_at` is still after the current clock instant — is cancelled, moving its `schedule_status` from `CONFIRMED` to `CANCELLED`. Each such cancellation transitively releases that occurrence's own gear rentals and engineer assignments. The contract's `version` increments. A terminate against a contract that is not `ACTIVE` fails with `ERR_INVALID_STATE`.

### 3.9. Session Delivery and the Revision Loop

After a session is finished and fully paid, the engineer hands over the files through a `SessionDelivery`, which references its `booking_id`, carries a `file_manifest` (a list of delivered file descriptors), a computed `revision_round` counter starting at zero, and a `status` cycling through `DRAFT`, `DELIVERED`, `REVISION_REQUESTED`, and `ACCEPTED`. The delivery is created on the first hand-off and lives one-to-one with its booking.

An `Engineer` performs the initial delivery, which moves the delivery's `status` from `DRAFT` to `DELIVERED`. This is permitted only when the booking's `schedule_status` is `COMPLETED` and its `settlement_status` is `SETTLED`, and only when the `file_manifest` is non-empty; an attempt before the booking is both completed and settled, or after the delivery has already been `ACCEPTED`, is rejected with `ERR_SESSION_NOT_DELIVERABLE`. A successful deliver increments the delivery's `version`.

From `DELIVERED` the client drives the revision loop. A `Client` may request a revision, moving the status from `DELIVERED` to `REVISION_REQUESTED`; the engineer then re-delivers, supplying a non-empty `file_manifest`, which moves the status from `REVISION_REQUESTED` back to `DELIVERED` and increments `revision_round` by one (as well as the delivery's `version`). This loop may repeat until the client is satisfied. Alternatively, from `DELIVERED` the client accepts the delivery, moving the status to the terminal `ACCEPTED` and incrementing the `version`. Any of these delivery actions attempted from a status that does not define the transition fails with `ERR_INVALID_STATE`, and a request-revision or accept is the client's prerogative while deliver and re-deliver belong to the engineer.

### 3.10. Reading the Ledger and the Catalog

Beyond the action endpoints, the API exposes read access throughout. Bookings can be listed and filtered by `studio_id`, `room_id`, `client_id`, `parent_series_id`, or `schedule_status`. Payments can be listed and filtered by `client_id` and `booking_id`, supporting reverse lookup from a client or a booking to the payments that reference it. Gear rentals can be filtered by `gear_item_id` and `booking_id`, engineer assignments by `engineer_id` and `booking_id`, and every inventory list — rooms, engineers, gear items, clients, and lockout contracts — can be filtered by `studio_id` (with contracts additionally filterable by `room_id` and `client_id`). Overtime records are read per booking. A client fetched by id discloses its `wallet_credit_cents` so the client can see the credit available against future balances. All of these reads honor the same pagination and ownership rules described in §2.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, including the inventory and clock reads and the state-advancing actions, return `200 OK`. Request and response bodies are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studio` | Bootstrap a studio | StudioManager |
| GET | `/studio/{id}` | Fetch a studio | StudioManager, Client, Engineer |
| POST | `/studio/rooms` | Create a room | StudioManager |
| GET | `/studio/rooms/{id}` | Fetch a room | StudioManager, Client, Engineer |
| GET | `/studio/rooms` | List rooms; filter by studio | StudioManager, Client, Engineer |
| POST | `/studio/engineers` | Create an engineer | StudioManager |
| GET | `/studio/engineers/{id}` | Fetch an engineer | StudioManager, Client, Engineer |
| GET | `/studio/engineers` | List engineers; filter by studio | StudioManager, Client, Engineer |
| POST | `/studio/gear-items` | Create a gear inventory item | StudioManager |
| GET | `/studio/gear-items/{id}` | Fetch a gear item | StudioManager, Client, Engineer |
| GET | `/studio/gear-items` | List gear items; filter by studio | StudioManager, Client, Engineer |
| POST | `/studio/clients/register` | Register a client (open) | Anonymous, StudioManager |
| GET | `/studio/clients/{id}` | Fetch a client (includes wallet credit) | StudioManager, Client |
| GET | `/studio/clients` | List clients; filter by studio | StudioManager |
| POST | `/studio/bookings` | Create a HELD booking | StudioManager, Client |
| GET | `/studio/bookings/{id}` | Fetch a booking | StudioManager, Client, Engineer |
| GET | `/studio/bookings` | List bookings; filter by studio/room/client/series/status | StudioManager, Client, Engineer |
| POST | `/studio/bookings/{id}/confirm` | Confirm a held booking | StudioManager |
| POST | `/studio/bookings/{id}/cancel` | Cancel a held or confirmed booking | StudioManager, Client |
| POST | `/studio/bookings/{id}/check-in` | Begin the session | StudioManager |
| POST | `/studio/bookings/{id}/check-out` | End the session and reconcile | StudioManager |
| POST | `/studio/bookings/{id}/payments` | Record a deposit, balance, or refund payment | StudioManager, Client |
| GET | `/studio/bookings/{id}/payments` | List payments for a booking | StudioManager, Client |
| GET | `/studio/payments/{id}` | Fetch a single payment | StudioManager, Client |
| GET | `/studio/payments` | List payments; filter by client/booking | StudioManager, Client |
| POST | `/studio/bookings/{id}/gear-rentals` | Add a gear-rental add-on | StudioManager, Client |
| GET | `/studio/bookings/{id}/gear-rentals` | List gear rentals for a booking | StudioManager, Client, Engineer |
| GET | `/studio/gear-rentals/{id}` | Fetch a single gear rental | StudioManager, Client, Engineer |
| GET | `/studio/gear-rentals` | List gear rentals; filter by gear-item/booking | StudioManager, Client, Engineer |
| DELETE | `/studio/bookings/{id}/gear-rentals/{rentalId}` | Release a gear rental | StudioManager |
| POST | `/studio/bookings/{id}/engineer-assignments` | Assign an engineer to a booking | StudioManager |
| GET | `/studio/bookings/{id}/engineer-assignments` | List engineer assignments for a booking | StudioManager, Client, Engineer |
| GET | `/studio/engineer-assignments/{id}` | Fetch a single engineer assignment | StudioManager, Client, Engineer |
| GET | `/studio/engineer-assignments` | List engineer assignments; filter by engineer/booking | StudioManager, Client, Engineer |
| DELETE | `/studio/bookings/{id}/engineer-assignments/{assignId}` | Release an engineer assignment | StudioManager |
| GET | `/studio/bookings/{id}/overtime-records` | List overtime records for a booking | StudioManager, Client |
| POST | `/studio/lockout-contracts` | Create a draft lockout contract | StudioManager |
| GET | `/studio/lockout-contracts/{id}` | Fetch a lockout contract | StudioManager, Client |
| GET | `/studio/lockout-contracts` | List lockout contracts; filter by studio/room/client | StudioManager |
| POST | `/studio/lockout-contracts/{id}/activate` | Activate a contract (lock room, materialize occurrences) | StudioManager |
| POST | `/studio/lockout-contracts/{id}/terminate` | Terminate a contract (unlock room, cancel future occurrences) | StudioManager |
| POST | `/studio/bookings/{id}/delivery/deliver` | Deliver or re-deliver a session package | Engineer |
| POST | `/studio/bookings/{id}/delivery/request-revision` | Request a revision | Client |
| POST | `/studio/bookings/{id}/delivery/accept` | Accept the delivery | Client |
| GET | `/studio/bookings/{id}/delivery` | List the session delivery for a booking | StudioManager, Client, Engineer |
| POST | `/_clock/set_current_utc` | Set the server wall clock (test-driving) | StudioManager |
| POST | `/_sweep/release_expired_holds` | Auto-release expired holds (test-driving) | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_ENGINEER_REQUIRED` | 422 |
| `ERR_ROOM_UNAVAILABLE` | 409 |
| `ERR_LOCKOUT_CONFLICT` | 409 |
| `ERR_GEAR_UNAVAILABLE` | 409 |
| `ERR_ENGINEER_UNAVAILABLE` | 409 |
| `ERR_DEPOSIT_MISMATCH` | 422 |
| `ERR_BALANCE_MISMATCH` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_SESSION_NOT_DELIVERABLE` | 409 |
| `ERR_CANCEL_TOO_LATE` | 409 |
