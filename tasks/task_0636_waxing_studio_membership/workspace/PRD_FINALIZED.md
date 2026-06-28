# Waxing Studio Membership API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Waxing Studio Membership platform — a multi-location reservation and membership system in the style of a European-Wax-Center operation. The platform stitches together a public-facing service menu, a wax-pass membership program built on prepaid credits, a first-service-free introductory offer, technician and treatment-room scheduling, retail product attach, and a no-show/late-cancel deterrent regime, all coordinated across several physical studios.

The hard part of this domain is that money, credits, time, and risk all move at once. A single reservation touches a member's prepaid credit ledger, a technician's calendar, a treatment room's buffered schedule, and — when things go wrong — a member's standing in the no-show strike system. Memberships breathe over time: credits are granted each billing cycle, rolled over up to a cap, frozen and thawed, forfeited on cancellation, and re-valued as store credit. Reservations carry two independent fates at once — what happens to the booking and what happens to the money — and the platform must keep both honest even as a logical clock advances and sweeps stale bookings, expires old strikes, and thaws frozen passes.

This PRD defines the entities, their lifecycles, the calculations that govern credits and charges, the validation order that protects each write, and the API surface. All resources are mounted under the `/studio` path prefix. Because the system is consumed by front-desk operators, technicians, members, and a cross-location administrator simultaneously, the access-control model and the optimistic-concurrency discipline described in Section 2 are load-bearing, not decorative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. The platform recognizes exactly four roles, spelled precisely: `StudioAdmin`, `FrontDesk`, `Technician`, and `Member`. If either header is missing, or if `X-User-Role` is not one of these four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership constraint is violated — the request is rejected with `ERR_UNAUTHORIZED`.

The four roles split along operational lines. A `StudioAdmin` is a cross-location operator and the configuration authority: it creates and edits locations, rooms, technicians, service-menu items, and retail products, waives strikes, and drives the test clock. A `FrontDesk` operator runs a single studio's front desk — registering members, managing memberships, booking and running reservations, and handling retail. A `Technician` is a service provider, and a `Member` is a customer acting on their own resources.

Two of the four roles are tied to a persisted entity, and two are not. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a technician compare the resource's `technician_id` to `X-User-ID`, so a technician may complete only reservations whose `technician_id` equals their own identifier. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare the resource's `member_id` (or, for a membership, the membership's owning `member_id`) to `X-User-ID`, so a member may book, cancel, attach retail, and freeze/unfreeze/cancel only against their own resources. When `X-User-Role` is `StudioAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `FrontDesk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter is the number of items to skip; it defaults to 0 and must be zero or greater. A request whose `limit` falls outside the range 1 through 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Identity, Timestamps, and Resource Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix; clients never supply it. Every resource also carries a `created_at` timestamp, recorded as an ISO 8601 UTC instant with three fractional digits, set once at creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation, including mutations that arise as cascades from operations on other entities. The `version` field starts at 1 when the resource is created and increases by exactly 1 on each mutation; it is the basis for the optimistic-concurrency discipline in Section 2.6. The entities that carry the full quartet of `id`, `created_at`, `updated_at`, and `version` are `Location`, `ServiceType`, `Product`, `Room`, `Technician`, `Member`, `Membership`, `Reservation`, and `RetailSale`.

Two entities are append-only audit records and deliberately omit `updated_at` and `version`: a `CreditLedgerEntry` and a `NoShowStrike` each carry only an `id` and a `created_at`. A `CreditLedgerEntry` is never edited after it is written, and a `NoShowStrike`, once minted, changes only its `status` through the defined transitions without bumping any version counter.

### 2.5. Cascading State Propagation and Derived Fields

Many operations in this system reach beyond their target resource. When a single request mutates more than one entity — for example, when completing a reservation consumes membership credits, or when cancelling a membership releases credits held by open reservations — every affected entity independently records the change: its `updated_at` is refreshed and, where the entity carries one, its `version` is incremented by 1. The server may also drive transitions on its own initiative during clock advancement (Section 3.7); those automatic transitions follow the same rule.

Several fields are not supplied by clients but are recomputed by the server from underlying records. A `Membership` exposes a `credit_balance` projected from its credit ledger. A `Member` exposes `intro_used`, `no_show_strike_count`, and `wallet_credit_cents`, all derived from the member's history. A `Reservation` exposes `end_utc`, `credits_held`, `deposit_held_cents`, and `charged_amount_cents`. A `RetailSale` exposes `gross_cents`, `discount_cents`, and `net_cents`. Whenever an underlying record changes, the owning resource's derived fields are recomputed and the resource's `updated_at`/`version` are advanced accordingly.

### 2.6. Optimistic Concurrency Control

Booking a reservation is the one write in this system that is guarded against acting on stale parent data, and it is guarded against two parents at once. A request to create a reservation must carry `expected_room_version` as a required field whose value equals the current `version` of the target `Room` identified by `room_id`. Holding a slot mutates that room — its `updated_at` and `version` advance as part of holding the slot — so if any writer has advanced the room's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), even when the new request would legitimately fill a different, non-overlapping slot. This prevents a client from booking against a room whose schedule it has not actually observed.

When the reservation is paid by membership credit (Section 3.4), the request must additionally carry `expected_membership_version`, whose value must equal the current `version` of the `Membership` identified by `membership_id`. Each successful credit debit advances the membership's `version`; a create that carries a membership version older than the membership's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), capturing the case where a prior debit has already drawn down credits and advanced the membership the current writer still believes sits at the older version. The `expected_membership_version` field is required precisely when a credit booking is being made and is otherwise absent. No other endpoint in the system takes a parent-version field for concurrency purposes.

### 2.7. Studio Operating Hours and the Booking Window

Each `Location` declares its daily operating window as two integers measured in minutes after midnight UTC: `open_minute_of_day` (default 540, i.e. 09:00Z) and `close_minute_of_day` (default 1200, i.e. 20:00Z). A reservation's slot is evaluated against this window by time-of-day in UTC: the slot's start time-of-day must be at or after `open_minute_of_day`, and the slot's end time-of-day — the start advanced by the service's duration — must be at or before `close_minute_of_day`. In addition, the slot's `start_utc` may not be earlier than the current clock instant. A booking that violates either the operating-hours constraint or the not-in-the-past constraint is rejected with `ERR_OUTSIDE_HOURS`.

### 2.8. Monetary and Credit Precision

All money in this system is expressed as whole integer cents; there are no fractional cents and no separate decimal currency type. The reservation charge calculation works entirely in integer cents and performs no rounding. Where a calculation involves a fraction — specifically the per-unit retail discount and the (unused, alternative) prorated cancellation refund — the fractional result is rounded to a whole number of cents using the round-half-up convention. Wax-pass credits are always whole integers; a membership's `credit_balance`, a service's `credit_cost`, and a reservation's `credits_held` are counted, never rounded.

### 2.9. Nested Reference Resolution and Existence Checks

This is a flat system: resources live in top-level collections and refer to one another by foreign-key fields carried in request bodies rather than through deeply nested URLs. Nonetheless, every path identifier and every foreign-key reference in a request must resolve to an existing resource. References are validated in a fixed left-to-right order across the set of resources a request touches — `Location`, then `Room`, then `Technician`, then `ServiceType`, then `Member`, then `Membership`, then `Product`, then `Reservation` — and the first reference that does not resolve causes the request to be rejected with `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.10. The Logical Clock and Scheduled Sweeps

The platform runs on a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any operator sets it the clock continues to read that exact default — it never falls back to real wall-clock time. A `StudioAdmin` may move the clock forward to a supplied instant, and may also re-run the scheduled sweeps at the current clock without moving it. Advancing the clock (and the standalone sweep capability) runs four deferred housekeeping actions described in Section 3.7: the no-show sweep, strike expiry, freeze auto-expiry, and due renewals. These sweeps are how the passage of time turns abandoned bookings into no-shows, ages out old strikes, thaws frozen passes, and processes renewal cycles.

## 3. Business Logic & Workflows

### 3.1. Configuring a Studio: Locations, Rooms, Technicians, Services, and Products

Before any member can book, a `StudioAdmin` lays down the configuration. A `Location` is created with a display `name` and a two-letter US `state_code` (for example, `CA` or `TX`); its `open_minute_of_day` and `close_minute_of_day` default to 540 and 1200 if omitted, and its `deposit_required_cents` (default 1000) and `no_show_fee_cents` (default 2500) govern the money charged when a member has no covering credit or no deposit on file. A `Room` belongs to a studio through its `location_id` and carries a `label` such as "Room 1"; rooms are bookable by default but an `active` flag set to false takes a room out of service so it cannot host new reservations. A `Technician` is also tied to a studio by `location_id`, carries a `full_name`, an array of `certified_service_ids` listing the services they are qualified to perform, and an `active` flag — an inactive technician cannot be assigned to new reservations.

The service menu is a set of `ServiceType` records, each with a `name` (such as Brazilian, Brow, or Underarm), a positive `duration_minutes` defining the slot length, a `buffer_minutes` cleanup/turnover period appended after the slot (default 5), a walk-in `list_price_cents`, and a `credit_cost` (default 1) counting how many wax-pass credits the service consumes when paid by membership. A service's `intro_eligible` flag (default false) marks whether it may serve as a member's first-service-free visit, and its `active` flag (default true) controls bookability — an inactive service rejects new reservations. A `StudioAdmin` may later edit a service; such an update is an optimistically-guarded write that requires `expected_servicetype_version` and may change `list_price_cents`, `duration_minutes`, `buffer_minutes`, `credit_cost`, `intro_eligible`, or `active`. Retail inventory is captured as `Product` records, each with a `name`, a `unit_price_cents`, a `member_discount_pct` expressed as a fraction (default 0.10, i.e. ten percent), and a `stock_qty` of on-hand units (default 100) that is never allowed to fall below zero.

### 3.2. Registering Members and Issuing Wax-Pass Memberships

A `Member` is registered by a `FrontDesk` operator or a `StudioAdmin` with a `home_location_id` naming their primary studio, a `full_name`, and a unique `email`. Email uniqueness is enforced across all members; a registration whose `email` already exists is rejected with `ERR_DUPLICATE_EMAIL`. At registration the member's computed fields start at their baseline: `intro_used` is false, `no_show_strike_count` is zero, and `wallet_credit_cents` — the prepaid store-credit balance where refunds and forfeits land, never permitted to go negative — is zero.

A wax-pass is modeled as a `Membership` belonging to a member through `member_id`. A `FrontDesk` operator or `StudioAdmin` creates one in the `PENDING` state, choosing a `tier` of `BASIC`, `PLUS`, or `UNLIMITED`, a `monthly_credit_grant` of credits issued each billing cycle (the grant is honored for `BASIC` and `PLUS` and ignored for `UNLIMITED`), a recurring `monthly_fee_cents`, and an optional `max_rollover_credits` cap (default 0) limiting how many credits survive into the next cycle. A new membership starts with `cycle_index` at 0 and `credit_balance` at 0; its `status`, `cycle_anchor_utc`, `freeze_until_utc`, and `frozen_cycle_credits` are all server-managed. The membership progresses through the states `PENDING`, `ACTIVE`, `FROZEN`, `PAST_DUE`, and `CANCELLED`, with `CANCELLED` terminal.

The credit ledger underpins every credit movement. Each `CreditLedgerEntry` names the `membership_id` it mutates, an `entry_type` drawn from `GRANT`, `DEBIT`, `REFUND`, `ROLLOVER_FORFEIT`, `FREEZE_PARK`, and `UNFREEZE_RESTORE`, a signed `delta_credits` (positive for grants and restores, negative for debits, forfeits, and parks), a `source_kind` of either `MEMBERSHIP` or `RESERVATION`, a polymorphic `source_ref_id` that holds the `Membership` `id` when `source_kind` is `MEMBERSHIP` and the `Reservation` `id` when `source_kind` is `RESERVATION`, and the `cycle_index` of the membership at the moment the entry was written. A membership's `credit_balance` is the sum of `delta_credits` across all ledger entries for that `membership_id`, processed in `created_at` ascending order (ties broken by `created_at` and then by write sequence, never by `id`). The balance must never drop below zero — a debit that would drive it negative is refused before it is written (Section 3.4), never silently clamped at the ledger.

### 3.3. The Membership Lifecycle: Activation, Freeze, Renewal, and Cancellation

Activation moves a membership from `PENDING` to `ACTIVE` and is performed by a `FrontDesk` operator or `StudioAdmin`; it is permitted only while the membership is `PENDING`. Activation sets `cycle_anchor_utc` to the current clock instant while leaving `cycle_index` at 0, and writes a `GRANT` ledger entry whose `delta_credits` is the `monthly_credit_grant` for a `BASIC` or `PLUS` pass and 0 for an `UNLIMITED` pass, with `source_kind` `MEMBERSHIP` and `source_ref_id` equal to the membership's own `id` at `cycle_index` 0. The membership's `credit_balance` is then recomputed and its `version` advances by 1.

Freezing is a member-initiated hold (also available to `FrontDesk` and `StudioAdmin`) permitted only while the membership is `ACTIVE`; the request carries `freeze_days`, which must be an integer from 1 through 90 inclusive. Freezing sets `freeze_until_utc` to the current clock instant advanced by `freeze_days` days, parks the current balance by setting `frozen_cycle_credits` to the present `credit_balance`, and writes a `FREEZE_PARK` ledger entry whose `delta_credits` is the negative of that balance (with `source_kind` `MEMBERSHIP` and `source_ref_id` the membership `id`), so the recomputed `credit_balance` is 0 while the pass is `FROZEN`. Unfreezing returns a `FROZEN` membership to `ACTIVE` — driven either by the member (or `FrontDesk`/`StudioAdmin`) or automatically by the server when the clock reaches `freeze_until_utc` — clearing `freeze_until_utc`, writing an `UNFREEZE_RESTORE` ledger entry whose `delta_credits` is the positive `frozen_cycle_credits`, resetting `frozen_cycle_credits` to 0, and recomputing the balance. Both freeze and unfreeze advance the membership's `version` by 1.

Renewal is requested by a `FrontDesk` operator (or run automatically by the server when the clock crosses `cycle_anchor_utc` plus 30 days) and carries a `payment_outcome`. When a renewal on an `ACTIVE` membership reports a `payment_outcome` of `FAILED`, the membership branches to `PAST_DUE`: no `GRANT` is written, the `credit_balance` is left unchanged, and only the `version` advances. A successful renewal — `payment_outcome` of `SUCCEEDED` — applies the cycle rollover settlement described below, then advances `cycle_anchor_utc` by 30 days, increments `cycle_index` by 1, recomputes the balance, and advances `version` by 1. A successful renewal on an `ACTIVE` membership returns it to `ACTIVE` (a self-loop), and a successful renewal on a `PAST_DUE` membership recovers it to `ACTIVE`; both run the identical settlement-then-grant cascade.

The cycle rollover settlement runs in a pinned order, because the carryover depends on the balance before the new grant and the grant itself is appended after the carryover is capped. First, the pre-renewal balance is captured as the membership's `credit_balance` as it stands before this renewal's grant. Second, the surviving carryover is the smaller of that pre-renewal balance and the membership's `max_rollover_credits`. Third, the forfeited amount is the pre-renewal balance minus the surviving carryover — a value that is zero or greater; whenever the forfeit is greater than zero, a `ROLLOVER_FORFEIT` ledger entry is written whose `delta_credits` is the negative of that forfeit. Fourth, the new grant is 0 for an `UNLIMITED` tier and otherwise the membership's `monthly_credit_grant`, written as a `GRANT` ledger entry with a positive `delta_credits`. Fifth, the resulting balance is the surviving carryover plus the grant. An `UNLIMITED` tier never accumulates a numeric balance, so both its carryover and its grant are 0.

Cancellation moves a membership from any of `PENDING`, `ACTIVE`, `FROZEN`, or `PAST_DUE` to `CANCELLED` and is permitted whenever the membership is not already `CANCELLED`; it may be requested by the owning member, a `FrontDesk` operator, or a `StudioAdmin`. Cancellation cascades: every `BOOKED` or `CHECKED_IN` reservation paid by credit on this membership is itself cancelled, releasing its held credits through a `REFUND` ledger entry that re-credits the balance. After those refunds land, the entire remaining `credit_balance` is forfeited to the member's `wallet_credit_cents` at the par rate of 100 cents per credit; this par-value conversion values every surviving credit at 100 cents regardless of where the membership sits in its cycle. The membership's `credit_balance` is then recomputed to 0 and its `version` advances by 1. (An alternative interpretation — refunding the unused monthly fee in proportion to elapsed cycle days — is explicitly **not** the production rule and must not be used; the par-value forfeit is authoritative. For reference, that alternative would have counted the elapsed days as the whole-day count of the interval from `cycle_anchor_utc` to now, taken the unused fraction as thirty minus the elapsed days over thirty but never below zero, multiplied the `monthly_fee_cents` by that fraction, and rounded half up — a different number from the par-value result, which is why proration is rejected.)

### 3.4. Booking a Reservation: Eligibility, Payment, and Slot Holding

A reservation is the heart of the system, and a single create carries a dense payload split across this subsection and the safety rules in Section 3.5. The core booking fields are the `member_id` the reservation is for, the `location_id` of the studio, the `room_id` and `technician_id` being held, the `service_type_id` being booked, the `start_utc` start instant, and the `payment_method`. A reservation may be booked by the member for themselves or by a `FrontDesk` operator; a member acting for themselves may only book where `member_id` equals their own identifier. The slot's `end_utc` is computed as `start_utc` advanced by the service's `duration_minutes`, and the room is held for the window from the slot start through the slot end plus the service's `buffer_minutes`. A new reservation begins with `booking_status` `BOOKED` and a `settlement_status` that depends on how it will be paid.

The `payment_method` is one of `CREDIT`, `DEPOSIT`, `INTRO_FREE`, or `WALK_IN`, and it determines both the settlement axis and the money or credits held. A `CREDIT` booking requires a `membership_id`, which must reference a membership owned by the same member; for any other payment method `membership_id` is null. On a `CREDIT` booking the settlement axis moves from `UNSETTLED` to `CREDIT_HELD`: for a non-`UNLIMITED` tier the system writes a `DEBIT` ledger entry whose `delta_credits` is the negative of the service's `credit_cost` (with `source_kind` `RESERVATION` and `source_ref_id` the reservation's `id`) and sets the reservation's `credits_held` to that `credit_cost`. Because an `UNLIMITED` tier never accumulates a numeric balance and its balance must never drop below zero (Sections 3.2, 3.3), an `UNLIMITED` credit booking writes no `DEBIT` entry and leaves `credits_held` at 0 (its effective balance is treated as unbounded for eligibility, so no debit is held against the ledger). In every case — `UNLIMITED` or not — the settlement axis moves to `CREDIT_HELD` and the membership's `version` advances by 1. A `DEPOSIT` booking moves the settlement axis to `DEPOSIT_HELD` and captures the location's `deposit_required_cents` into the reservation's `deposit_held_cents`. An `INTRO_FREE` or `WALK_IN` booking leaves the settlement axis `UNSETTLED`. Holding the slot mutates the room, advancing its `version` by 1, which is why the create is guarded by `expected_room_version` (Section 2.6).

Creating a reservation runs a long gauntlet of checks, and their relative order matters because a request can violate several at once and the platform must return a deterministic error. The checks are evaluated in this priority order. First come the universal guards shared by all endpoints: authentication (`ERR_UNAUTHENTICATED`), then authorization including ownership (`ERR_UNAUTHORIZED`), then existence of every path and foreign-key reference resolved left to right (`ERR_NOT_FOUND`), then request well-formedness — required fields present, enum values valid, integers in range (`ERR_INVALID_REQUEST`). Next, because booking is not a transition on an existing resource's state field, the state guard (`ERR_INVALID_STATE`) does not bite here, but the optimistic-concurrency check does: a mismatch of `expected_room_version` or `expected_membership_version` against the live parent `version` yields `ERR_STALE_VERSION`. After concurrency, the system checks cross-entity coherence (`ERR_RESOURCE_MISMATCH`): the room's `location_id` and the technician's `location_id` must both equal the reservation's `location_id`; the technician must be certified for the service (its `service_type_id` must appear in `certified_service_ids`); the service, the room, and the technician must all be `active`; and a `membership_id` must be present exactly when `payment_method` is `CREDIT`, with that membership's `member_id` equal to the reservation's `member_id`. Then, for a credit booking, the membership must be `ACTIVE` — a `FROZEN`, `PAST_DUE`, `PENDING`, or `CANCELLED` membership is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`. Next the operating-hours and not-in-the-past window is enforced (`ERR_OUTSIDE_HOURS`, Section 2.7), then intro eligibility (`ERR_INTRO_NOT_ELIGIBLE`, Section 3.5), then deposit gating (`ERR_DEPOSIT_REQUIRED`, Section 3.5). After those, the technician overlap check (`ERR_TECH_DOUBLE_BOOKED`) runs before the room overlap check (`ERR_ROOM_DOUBLE_BOOKED`), and finally the credit-sufficiency check (`ERR_INSUFFICIENT_CREDITS`) runs last among the reservation-create rules.

The two overlap checks differ in a way that matters. The technician double-booking check compares the requested interval from the slot start through the slot end — with no buffer — against the same bare intervals of the technician's other non-terminal reservations, treating each interval as closed at the start and open at the end so that one slot ending exactly when another begins is not a conflict. The room double-booking check instead compares the buffered window — the slot start through the slot end plus the service's `buffer_minutes` — against the buffered windows of the room's other non-terminal reservations, again as closed-open intervals. A reservation counts as non-terminal for both checks while its `booking_status` is `BOOKED` or `CHECKED_IN`.

Eligibility for a credit booking turns on whether the membership can cover the cost. The number of credits needed is the service's `credit_cost`. For an `UNLIMITED` tier the effective balance is treated as unbounded, so a credit booking always has enough; for any other tier the effective balance is the membership's `credit_balance`, and the booking is allowed only when that balance is at least the needed `credit_cost` — otherwise it is rejected with `ERR_INSUFFICIENT_CREDITS`.

### 3.5. The First-Visit Offer and the No-Show Deterrent

The first-service-free introductory offer is a one-time perk. A booking may use `payment_method` `INTRO_FREE` only when the member's `intro_used` flag is still false and the chosen service's `intro_eligible` flag is true; a request that asks for an intro visit when the member has already used their intro, or for a service that is not intro-eligible, is rejected with `ERR_INTRO_NOT_ELIGIBLE`. The `intro_used` flag is not flipped at booking time — it is set true only when the intro reservation actually completes (Section 3.6).

The no-show deterrent gates credit bookings for members who have piled up active strikes. A booking is forced to use a deposit when three conditions hold together: the member's `no_show_strike_count` is at least 2, the `payment_method` is `CREDIT`, and the membership's `tier` is not `UNLIMITED`. When all three are true, the credit booking is rejected with `ERR_DEPOSIT_REQUIRED`, and the member must rebook with `payment_method` `DEPOSIT` instead. An `UNLIMITED` member is never deposit-gated, and a member below the two-strike threshold books on credit normally. The `no_show_strike_count` itself is the number of that member's `NoShowStrike` rows whose `status` is `ACTIVE` and whose `created_at` plus 90 days is still strictly after the current clock instant — a strike sitting exactly at its 90-day mark counts as expired, not active, so the boundary is strict.

### 3.6. Running the Visit: Check-In, Completion, Cancellation, and No-Show

A reservation carries two independent state axes at once. The `booking_status` axis tracks the visit through `BOOKED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, with the last three terminal. The `settlement_status` axis tracks the money through `UNSETTLED`, `DEPOSIT_HELD`, `CREDIT_HELD`, `PAID`, `REFUNDED`, and `FORFEITED`, with the last three terminal. The two axes move on their own schedules: a booking can be `BOOKED` while its money sits in `CREDIT_HELD`, and completing the visit advances both.

Check-in is performed by a `FrontDesk` operator and moves a reservation from `BOOKED` to `CHECKED_IN`. It is permitted only while the reservation is `BOOKED`, and only once the clock has reached at least 30 minutes before `start_utc`; an attempt earlier than that window is rejected with `ERR_CHECKIN_TOO_EARLY`. A check-in attempted on a reservation that is not `BOOKED` is rejected with `ERR_INVALID_STATE`. Check-in advances the reservation's `version` by 1.

Completion is performed by a `FrontDesk` operator or by the assigned technician, and moves a `CHECKED_IN` reservation to `COMPLETED` while the settlement axis advances to `PAID`. Completion finalizes the `charged_amount_cents`. For an `INTRO_FREE` visit the final charge is 0 and the member's `intro_used` flag is set true as a cross-entity effect; for a `CREDIT` visit the final charge is 0 because the held credits are consumed at completion (no refund follows); for a `DEPOSIT` visit the final charge is the service's `list_price_cents` minus the already-held `deposit_held_cents`, floored at 0 so it never goes negative, reflecting the deposit being applied against the service price; and for a `WALK_IN` visit the final charge is simply the service's `list_price_cents`. This final-charge variant differs from the provisional quote computed at booking time, where an `INTRO_FREE` or `CREDIT` hold quoted 0, a `DEPOSIT` hold quoted the location's `deposit_required_cents` (the deposit amount, not the net service price), and a `WALK_IN` hold quoted the service's `list_price_cents`; the difference shows up for `DEPOSIT`, whose final charge nets the deposit out of the list price rather than restating the deposit. Completion advances the reservation's `version` by 1.

Cancellation may be requested by the owning member or a `FrontDesk` operator on a reservation that is `BOOKED` or `CHECKED_IN`, and its consequences branch on timing. A timely cancellation — one made at least 24 hours before `start_utc` — moves the settlement axis to `REFUNDED`: a credit booking writes a `REFUND` ledger entry restoring its `credits_held`, and a deposit booking returns its `deposit_held_cents` to the member's `wallet_credit_cents`. A late cancellation — one made less than 24 hours before `start_utc` — instead mints a `NoShowStrike` of kind `LATE_CANCEL`, moves the settlement axis to `FORFEITED`, and forfeits the money: a deposit booking's `deposit_held_cents` is forfeited rather than refunded, and a credit booking's `credits_held` are forfeited with no `REFUND` entry written. That new strike raises the member's `no_show_strike_count`, which once it crosses the threshold flips the member into deposit-required status for future credit bookings. In either timing branch, any `PENDING` retail sale attached to the reservation is voided and its product restocked, and the reservation's `version` advances by 1.

A no-show is the other terminal outcome. A `FrontDesk` operator may mark a `BOOKED` reservation as a no-show, and the server itself marks one during the sweep when the clock has reached at least 15 minutes past `start_utc` and the reservation is still `BOOKED`; either way the precondition is that the reservation is `BOOKED` and the clock is at or past `start_utc` plus 15 minutes. Marking a no-show mints a `NoShowStrike` of kind `NO_SHOW`, moves the settlement axis to `FORFEITED` (a deposit is forfeited, held credits are forfeited with no `REFUND`), increments the member's `no_show_strike_count`, voids and restocks any `PENDING` attached retail sale, and advances the reservation's `version` by 1. As with late cancellation, once the active strike count crosses two, the member becomes deposit-required for future credit bookings.

Each `NoShowStrike` records the offending `member_id`, the `reservation_id` that minted it, a `strike_kind` of `NO_SHOW` or `LATE_CANCEL`, the `fee_charged_cents` captured at strike time (the forfeited deposit, or the location's `no_show_fee_cents` when no deposit was on file), and a `status` of `ACTIVE`, `EXPIRED`, or `WAIVED`. A `StudioAdmin` may waive an `ACTIVE` strike; waiving refunds the strike's `fee_charged_cents` to the member's `wallet_credit_cents`, moves the strike to `WAIVED`, and recomputes the member's `no_show_strike_count`, which may re-open credit booking without a deposit.

### 3.7. Retail Attach and Confirmation

Retail purchases ride along with a visit. A `RetailSale` is attached to a reservation by the member or a `FrontDesk` operator, naming the `member_id` buyer, the `reservation_id` it attaches to (the attach context, always required), the `product_id`, and a positive `quantity`. The sale begins in `PENDING` and at this point no stock is decremented; the system computes a provisional `gross_cents`, `discount_cents`, and `net_cents` for preview. A `FrontDesk` operator confirms a `PENDING` sale, but only after the attached visit has reached `COMPLETED` (retail finalizes only after the visit completes) and only when the product's `stock_qty` is at least the requested `quantity`; an under-stocked confirm is rejected with `ERR_OUT_OF_STOCK`. Confirmation is an optimistically-guarded write requiring `expected_product_version`, decrements the product's `stock_qty` by the `quantity`, finalizes the money, moves the sale to `CONFIRMED`, and advances the sale's `version` by 1. A `FrontDesk` operator may instead void a `PENDING` sale, moving it to `VOIDED` with no stock change (stock was never decremented while `PENDING`) and advancing its `version` by 1; the server performs the same void automatically when the host reservation is cancelled or marked no-show. The states `PENDING`, `CONFIRMED`, and `VOIDED` are the sale's full lifecycle, with the latter two terminal.

The retail money is computed with a pinned rounding order: round per unit, then multiply. The per-unit discount in cents is the product's `unit_price_cents` multiplied by its `member_discount_pct`, rounded half up to a whole cent; the total `discount_cents` is that per-unit discount multiplied by the `quantity` — the multiplication happens only after the per-unit rounding, never the other way around. The `gross_cents` is the `unit_price_cents` multiplied by the `quantity`, and the `net_cents` is the `gross_cents` minus the `discount_cents`, never below zero. The member discount applies only when the buyer holds a membership whose `status` is `ACTIVE` at confirm time; if the buyer has no active membership, the `member_discount_pct` is treated as zero and the `discount_cents` is zero.

### 3.8. The Passage of Time: Sweeps and Deferred Transitions

Because the system runs on a logical clock, several transitions are not driven by a client request at all but by the advance of time. A `StudioAdmin` advances the clock to a supplied `to_iso8601` instant, or re-runs the sweeps at the current clock without moving it. Each advance (and each standalone sweep run) performs four housekeeping passes across all entities. The no-show sweep finds every reservation still `BOOKED` whose `start_utc` is at least 15 minutes in the past relative to the new clock and drives it to `NO_SHOW` with the full no-show cascade. The strike-expiry sweep finds every `ACTIVE` `NoShowStrike` whose `created_at` plus 90 days has been reached and moves it to `EXPIRED`, recomputing the affected member's `no_show_strike_count` (which may re-open credit booking without a deposit). The freeze-expiry sweep finds every `FROZEN` membership whose `freeze_until_utc` has been reached and thaws it back to `ACTIVE` with the unfreeze restore cascade. And due renewals process memberships whose `cycle_anchor_utc` plus 30 days has arrived. The standalone sweep capability is idempotent — running it again at the same clock makes no further change.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and the clock/sweep utilities — return `200 OK`. All paths are mounted under the `/studio` prefix. The request and response bodies for each operation are described in the Section 3 narratives; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studio/locations` | Create a location/studio | StudioAdmin |
| GET | `/studio/locations/{id}` | Get a location | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/locations` | List locations | StudioAdmin, FrontDesk, Technician, Member |
| POST | `/studio/service-types` | Create a service-menu item | StudioAdmin |
| GET | `/studio/service-types/{id}` | Get a service type | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/service-types` | List service types | StudioAdmin, FrontDesk, Technician, Member |
| PATCH | `/studio/service-types/{id}` | Update a service type | StudioAdmin |
| POST | `/studio/products` | Create a retail product | StudioAdmin |
| GET | `/studio/products/{id}` | Get a product | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/products` | List products | StudioAdmin, FrontDesk, Technician, Member |
| POST | `/studio/rooms` | Create a room at a location | StudioAdmin |
| GET | `/studio/rooms/{id}` | Get a room | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/rooms` | List rooms (filter by location_id) | StudioAdmin, FrontDesk, Technician, Member |
| POST | `/studio/technicians` | Create a technician at a location | StudioAdmin |
| GET | `/studio/technicians/{id}` | Get a technician | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/technicians` | List technicians (filter by location_id) | StudioAdmin, FrontDesk, Technician, Member |
| POST | `/studio/members` | Register a member | StudioAdmin, FrontDesk |
| GET | `/studio/members/{id}` | Get a member | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/members` | List members (filter by home_location_id) | StudioAdmin, FrontDesk |
| POST | `/studio/memberships` | Create a PENDING membership | StudioAdmin, FrontDesk |
| GET | `/studio/memberships/{id}` | Get a membership | StudioAdmin, FrontDesk, Member |
| GET | `/studio/memberships` | List memberships (filter by member_id) | StudioAdmin, FrontDesk, Member |
| POST | `/studio/memberships/{id}/activate` | Activate a PENDING membership | StudioAdmin, FrontDesk |
| POST | `/studio/memberships/{id}/freeze` | Freeze an ACTIVE membership | Member, FrontDesk, StudioAdmin |
| POST | `/studio/memberships/{id}/unfreeze` | Unfreeze a FROZEN membership | Member, FrontDesk, StudioAdmin |
| POST | `/studio/memberships/{id}/renew` | Renew a membership cycle | StudioAdmin, FrontDesk |
| POST | `/studio/memberships/{id}/cancel` | Cancel a membership | Member, FrontDesk, StudioAdmin |
| GET | `/studio/memberships/{id}/ledger` | List a membership's credit ledger | StudioAdmin, FrontDesk, Member |
| POST | `/studio/reservations` | Book a reservation | Member, FrontDesk |
| GET | `/studio/reservations/{id}` | Get a reservation | StudioAdmin, FrontDesk, Technician, Member |
| GET | `/studio/reservations` | List reservations (filter by FKs) | StudioAdmin, FrontDesk, Technician, Member |
| POST | `/studio/reservations/{id}/check-in` | Check a member in | FrontDesk |
| POST | `/studio/reservations/{id}/complete` | Complete a visit | FrontDesk, Technician |
| POST | `/studio/reservations/{id}/cancel` | Cancel a reservation | Member, FrontDesk |
| POST | `/studio/reservations/{id}/mark-no-show` | Mark a reservation a no-show | FrontDesk |
| POST | `/studio/retail-sales` | Attach a retail purchase | Member, FrontDesk |
| GET | `/studio/retail-sales/{id}` | Get a retail sale | StudioAdmin, FrontDesk, Member |
| GET | `/studio/retail-sales` | List retail sales (filter by FKs) | StudioAdmin, FrontDesk, Member |
| POST | `/studio/retail-sales/{id}/confirm` | Confirm a PENDING retail sale | FrontDesk |
| POST | `/studio/retail-sales/{id}/void` | Void a PENDING retail sale | FrontDesk |
| GET | `/studio/no-show-strikes/{id}` | Get a no-show strike | StudioAdmin, FrontDesk, Member |
| GET | `/studio/no-show-strikes` | List no-show strikes (filter by FKs) | StudioAdmin, FrontDesk, Member |
| POST | `/studio/no-show-strikes/{id}/waive` | Waive an ACTIVE strike | StudioAdmin |
| POST | `/studio/_clock/set_current_utc` | Set the logical clock and run sweeps | StudioAdmin |
| POST | `/studio/_clock/run_sweeps` | Re-run scheduled sweeps at the current clock | StudioAdmin |

The list endpoints accept the following filter query parameters in addition to `limit` and `offset`: locations by `state_code`; service types by `active`; rooms by `location_id` and `active`; technicians by `location_id` and `active`; members by `home_location_id` and `email`; memberships by `member_id` and `status`; the membership ledger by `entry_type`; reservations by `member_id`, `location_id`, `room_id`, `technician_id`, `service_type_id`, `membership_id`, and `booking_status`; retail sales by `member_id`, `reservation_id`, `product_id`, and `status`; and no-show strikes by `member_id`, `reservation_id`, and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RESOURCE_MISMATCH` | 409 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_OUTSIDE_HOURS` | 409 |
| `ERR_INTRO_NOT_ELIGIBLE` | 409 |
| `ERR_DEPOSIT_REQUIRED` | 409 |
| `ERR_TECH_DOUBLE_BOOKED` | 409 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_INSUFFICIENT_CREDITS` | 409 |
| `ERR_OUT_OF_STOCK` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_CHECKIN_TOO_EARLY` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
