# Boat Club API — Product Requirements Document

## 1. Introduction

The Boat Club platform powers a membership-boating operation modelled on the shared-fleet clubs that let members reserve, take out, and return boats without owning them. Members subscribe under a tier that governs how many boats they may hold at once, how far ahead they may book, and whether they may visit reciprocal partner docks. The club owns a rotating fleet spread across several docks; every trip must be reserved, a boat assigned by a fair rotation policy, checked out, and returned in a serviceable condition. Along the way the system meters fuel, cleaning, late returns, no-shows, and damage, turning each into a fee, and it bills recurring dues that fold those fees into monthly invoices.

This document specifies the REST API that runs that operation. It is written for the engineers who will build the service, and it aims to make the behaviour of every reservation, boat, training session, fee, and invoice unambiguous — including the arithmetic of every charge, the exact preconditions of every state change, and the order in which the system rejects a bad request. The domain is deliberately intricate: a single return can generate three different fees, a single no-show sweep can suspend a member and cascade-cancel their other bookings, and a dues invoice pins two different totals at two different moments in time. Precision in these interactions is the primary requirement.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply across every endpoint: authentication, the response envelope, pagination, identity and common fields, the logical clock, monetary precision, concurrency, and the global ordering in which validations are applied.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is missing or the role is not recognized, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles: `Member`, `DockStaff`, and `ClubAdmin`. When a recognized user invokes an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles form a widening hierarchy of capability. A `Member` acts only on their own reservations, enrollments, and invoices. `DockStaff` run day-to-day dock operations — attendance marking, boat servicing, damage handling, fee waivers. A `ClubAdmin` is a superset operator who can perform every `DockStaff` action, every `Member`-facing action, and the configuration and housekeeping operations besides.

Identity binds differently per role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare that resource's member foreign key to `X-User-ID`. Concretely, a `Member` may only request, confirm, check out, return, or cancel a reservation whose `member_id` equals their `X-User-ID`, may only create an enrollment whose `member_id` equals their `X-User-ID`, and may only pay a dues invoice whose `member_id` equals their `X-User-ID`. A violation of this ownership rule is rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `DockStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`. When `X-User-Role` is `ClubAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order. The `meta` object of any list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Identity, Common Fields, and Reverse-Reachability Lookups

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits marking creation, and `updated_at` is the same format marking the most recent modification. The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation of the resource. Docks, Members, Boats, Reservations, TrainingSessions, Enrollments, DamageReports, Fees, and DuesInvoices all carry this full common set.

One entity is an exception. A `MembershipTier` is a configuration record keyed by its natural code, and it carries only an `id` and a `created_at`; it has no `updated_at` and no `version` field at all. Its `id` holds the same value as its `tier_code` and exists for identity only — it is never itself a business decision input; tiers are always looked up by code.

Because the data model is flat — there are no nested ownership URLs — child collections are discovered by filtering a top-level list endpoint. Boats are found by their `dock_id`; members by their `home_dock_id`; reservations by any of `member_id`, `dock_id`, or `boat_id`; training sessions by their `dock_id`; enrollments by `member_id` or `session_id`; damage reports by `reservation_id` or `boat_id`; fees by `member_id` or `reservation_id`; and dues invoices by `member_id`. Several of these list endpoints additionally accept a `status` filter, and boats accept a `boat_type` filter, members accept a `membership_tier` filter, and fees accept a `fee_type` filter.

### 2.5. The Logical Clock and Housekeeping

All time-dependent behaviour is measured against a server-held logical clock, never against wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, every time comparison uses that default. A `ClubAdmin` may advance or reset the clock by supplying a `to_iso8601` instant; the server records it as the new current clock time.

A separate housekeeping sweep, also driven by a `ClubAdmin`, reconciles the world against the current clock in a single pass. It marks overdue reservations as no-shows and marks past-period unpaid invoices overdue; the precise rules for each appear with their respective workflows below.

### 2.6. Monetary Precision and Rounding

Every monetary amount in the system is an integer number of whole cents; there are no fractional-cent values on any stored field or in any response. Where a calculation multiplies a base amount by a tax rate, the rounding method is "round half up" and it is applied to the individual line before any summation — never to a running or final sum. That per-line-then-sum ordering is a hard rule for dues invoicing and is specified again where the invoice total is defined. Rotation ranking and counts are exact and involve no rounding.

### 2.7. Optimistic Concurrency Control

Issuing a dues invoice for a member is the one write in the system guarded by optimistic concurrency. The issue request must carry `expected_member_version`, a non-optional field whose value is the `version` of the target `Member` as the client last observed it. If `expected_member_version` does not equal the member's current `version` at issue time, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a successful issuance legitimately supersedes any prior unpaid invoice for that member and increments the member's `version` by one, a second issue request that still carries the earlier observed version is acting on a stale view and is refused: two strictly sequential issue requests carrying the same observed member version cannot both succeed, since the second's version is stale. No other endpoint takes a version field, and no other endpoint performs a version check.

### 2.8. Referential Resolution and Validation Ordering

Referenced resources named in a path or in foreign-key body fields are resolved left-to-right in the order they appear, and the first one that does not exist produces that entity's specific not-found error — `ERR_DOCK_NOT_FOUND`, `ERR_TIER_NOT_FOUND`, `ERR_BOAT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_DAMAGE_REPORT_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`, each HTTP 404 — before any deeper business rule is evaluated.

The system evaluates checks in a fixed global priority order, and the first failing check determines the rejection. First, authentication: headers present and the role recognized, else `ERR_UNAUTHENTICATED`. Second, authorization: the acting role is permitted for the endpoint, else `ERR_UNAUTHORIZED`. Third, body well-formedness on write endpoints — required fields present, enum values in range, numeric ranges honoured (for example an end strictly after a start) — else `ERR_VALIDATION` (HTTP 400). Fourth, existence of referenced resources as just described. Fifth, member ownership on member-scoped reservation, enrollment, and invoice-payment endpoints, else `ERR_FORBIDDEN`. Sixth, the target resource being in a valid state for the requested transition. Seventh, safety and certification prerequisites. Eighth, temporal booking constraints. Ninth, the remaining business-constraint checks (reciprocal access, active-reservation cap, weekly quota, duplicate enrollment, session capacity). Tenth, fiscal blocks. Eleventh, the optimistic-concurrency version check on dues issuance. When two checks in different tiers could both fail, the lower-numbered tier's error is the one returned.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding, Certification, and Membership Lifecycle

Before members exist, a `ClubAdmin` configures the tiers themselves. Each `MembershipTier` is created with its `tier_code`, a base `monthly_dues_cents`, a `max_active_reservations` cap, a `reservations_per_week` allowance, a `reciprocal_access_allowed` flag, and an `advance_booking_days_max` horizon.

A `ClubAdmin` enrolls a member by supplying their `full_name`, `email`, `membership_tier`, and `home_dock_id`; the tier must match an existing `MembershipTier.tier_code` (one of `CRUISE`, `SAIL`, or `UNLIMITED`) and the home dock must exist. A newly enrolled member starts in `PENDING_ORIENTATION` status with `certification_level` of `NONE`, `orientation_completed` set to false, and `no_show_strikes` at zero. The `last_reinstated_at` timestamp is null until the member is first reinstated.

A member becomes usable only after completing orientation. Orientation, and the two graded certifications, are earned by attending a training session (see §3.5). Certification is an ordered ladder — `NONE`, then `BASIC`, then `ADVANCED` — and it gates which boats a member may take out: a `CENTER_CONSOLE` requires `ADVANCED`, while a `PONTOON`, `BOWRIDER`, or `DECK_BOAT` requires at least `BASIC`. A booking whose requested type outstrips the member's certification is rejected with `ERR_CERT_INSUFFICIENT` (HTTP 422), and a booking attempted before orientation has been completed is rejected with `ERR_ORIENTATION_REQUIRED` (HTTP 422).

A member's standing is cyclic between `ACTIVE` and `SUSPENDED`. A `ClubAdmin` may suspend an `ACTIVE` member for cause, optionally recording a `reason`; the member moves to `SUSPENDED`. Suspension cascades: each of that member's reservations currently in `CONFIRMED` transitions to `CANCELLED`, and for every such cancelled reservation that held an assigned boat, that assignment is released — the reservation's `boat_id` is cleared and the boat is left `AVAILABLE`. Reservations still in `REQUESTED` are deliberately left intact so they can be resumed after reinstatement. A `ClubAdmin` reinstates a `SUSPENDED` member, moving them back to `ACTIVE`; reinstatement is permitted only when the member's `outstanding_fees_cents` is exactly zero (every fee either paid or waived), and is otherwise rejected with `ERR_OUTSTANDING_FEES` (HTTP 402). On reinstatement the member's `no_show_strikes` is reset to zero and `last_reinstated_at` is set to the current clock. `CANCELLED` is a terminal membership state reserved for full termination and is not reachable through any public endpoint in this version.

A member's read model also exposes several derived counters described in §3.6 and §3.4: the fee ledger totals `outstanding_fees_cents`, `waived_fees_cents`, and `paid_fees_cents`; the weekly usage figures `reservations_used_this_week` and `reservations_remaining_this_week`; and the billing figure `dues_balance_cents`, which is the sum of `final_total_cents` (or `estimated_total_cents` while an invoice is still unpaid) across that member's dues invoices that are neither `PAID` nor `VOID`.

### 3.2. The Fleet: Boats, Servicing, and Rotation

Docks are the physical anchor of the fleet, each created by a `ClubAdmin` with a `name`, a short `location_code`, a slip `capacity` of at least one, and an `is_reciprocal` flag that defaults to false and marks a partner dock rather than a home-club dock. Each boat is created by a `ClubAdmin` against a home `dock_id` and a `boat_type` of `PONTOON`, `BOWRIDER`, `DECK_BOAT`, or `CENTER_CONSOLE`. A new boat starts `AVAILABLE` with `fuel_level_pct` at 100, `usage_count` at zero, and `needs_cleaning` false; its `last_used_at` is null until its first return. A boat's life cycles through `AVAILABLE`, `OUT`, `CLEANING`, and back to `AVAILABLE`, with `MAINTENANCE` as a side branch.

Taking a boat out on checkout advances it from `AVAILABLE` to `OUT`. Returning it advances it from `OUT` to `CLEANING`; on that return the boat's `needs_cleaning` is set true, its `usage_count` is increased by one, its `last_used_at` is set to the current clock, and its `fuel_level_pct` is set to the fuel gauge reading captured at return. `DockStaff` finish the turnaround with a servicing action that carries a boat from `CLEANING` back to `AVAILABLE`, clearing `needs_cleaning` and refuelling the tank so `fuel_level_pct` returns to 100.

`DockStaff` (or a `ClubAdmin`) may pull a boat from any of `AVAILABLE`, `OUT`, or `CLEANING` into `MAINTENANCE`, optionally noting a `reason`; the same maintenance move is triggered automatically when a damage report against the boat is assessed. Sending a boat to `MAINTENANCE` cascades to reservations: each reservation on that boat still in `CONFIRMED` reverts to `REQUESTED` and its `boat_id` is cleared, so the confirmed rider must be re-assigned a boat later. The same servicing action that returns a boat from `CLEANING` also returns a boat from `MAINTENANCE` to `AVAILABLE`, in which case it refuels the tank to 100.

When a reservation is confirmed, a rotation policy chooses the boat, and the choice is deterministic. The candidate set is every boat whose `dock_id` matches the reservation's `dock_id`, whose `boat_type` matches the reservation's requested `boat_type`, whose status is anything other than `MAINTENANCE`, and which is free of any temporal collision. A collision exists when some other reservation on that same boat is in `CONFIRMED` or `CHECKED_OUT` and its window overlaps the new reservation's window under half-open semantics — that is, the new reservation's `start_time` is strictly before the other's `end_time` and the other's `start_time` is strictly before the new reservation's `end_time`. Among the surviving candidates the policy picks the boat with the lowest `usage_count`; ties are broken by the earliest `created_at`, and never by `id`. If no candidate survives, confirmation is rejected with `ERR_NO_BOAT_AVAILABLE` (HTTP 409).

### 3.3. Reserving, Confirming, Checking Out, and Returning a Boat

A reservation is the spine of the operation and moves through `REQUESTED`, `CONFIRMED`, `CHECKED_OUT`, and `RETURNED`, with `NO_SHOW` and `CANCELLED` as terminal off-ramps. A `Member` opens the flow by requesting a boat, supplying their `member_id`, the pickup `dock_id`, the desired `boat_type`, and the window's `start_time` and `end_time`; the window must be half-open with `end_time` strictly after `start_time`, or the request fails body validation. A fresh reservation is `REQUESTED` with no `boat_id` yet assigned, and with `fuel_at_checkout`, `fuel_at_return`, `checkout_time`, `return_time`, and `provisional_fuel_fee_cents` all null.

Confirming a reservation is permitted only when the owning member is `ACTIVE`; a confirm by a member who is not `ACTIVE` is rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409). On a successful confirm the rotation policy of §3.2 assigns a boat, the reservation moves from `REQUESTED` to `CONFIRMED`, its `boat_id` is set to the selected boat, and the member's weekly usage is recomputed to reflect the newly counted reservation.

Checking out is how a member takes possession of a `CONFIRMED` reservation's boat. The member supplies the observed `fuel_at_checkout` gauge reading. Checkout is permitted only when the assigned boat's status is `AVAILABLE`; if the boat is not `AVAILABLE`, the checkout is rejected with `ERR_BOAT_NOT_AVAILABLE` (HTTP 409). On success the reservation advances from `CONFIRMED` to `CHECKED_OUT`, the boat advances from `AVAILABLE` to `OUT`, the reservation records `fuel_at_checkout` and `checkout_time` at the current clock, and a forward-looking `provisional_fuel_fee_cents` is computed. That provisional figure assumes the member will bring the boat back exactly at the fuel floor: if `fuel_at_checkout` is above the 25-percent fuel floor, the provisional fee is 100 cents for every percentage point between `fuel_at_checkout` and 25; if `fuel_at_checkout` is at or below that floor, the provisional fee is zero. The provisional figure is an estimate stored on the reservation and does not itself create a `Fee`.

Returning the boat closes the trip. The member supplies the `fuel_at_return` gauge reading and may include a `cleaning_state`. On return the reservation advances from `CHECKED_OUT` to `RETURNED`, the boat advances from `OUT` to `CLEANING` (with the `usage_count`, `last_used_at`, `needs_cleaning`, and `fuel_level_pct` effects of §3.2), and the reservation records `fuel_at_return` and `return_time` at the current clock. The return then assesses up to three fees, each described in §3.6: a late-return fee if the boat comes back past the grace window, a fuel fee if it comes back below the fuel floor, and a flat cleaning fee if the returned `cleaning_state` is `SOILED`.

A member may cancel a reservation while it is still `REQUESTED` or `CONFIRMED`; a cancel attempted once the reservation is already `CHECKED_OUT`, `RETURNED`, `NO_SHOW`, or `CANCELLED` is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409). Cancelling releases any assigned boat — the `boat_id` is cleared and the boat stays `AVAILABLE` — and, if the reservation had been counted, decrements the member's weekly usage by one.

### 3.4. Booking Eligibility: Windows, Quotas, Caps, and Reciprocity

Requesting and confirming a reservation are both subject to a battery of eligibility rules, and they are checked in the global order of §2.8: certification and orientation first, then the temporal window, then the remaining quota and access constraints, then the fiscal block.

The temporal rules require that `start_time` lie in the future relative to the current clock and no further ahead than the member's tier permits — the tier's `advance_booking_days_max` is the maximum number of days beyond the current clock that a `start_time` may fall. A `start_time` in the past or beyond that horizon is rejected with `ERR_BOOKING_WINDOW` (HTTP 409). A member must also leave a turnaround gap of at least 60 minutes between this reservation and any of their other non-terminal reservations; a request that sits closer than that 60-minute turnaround to an existing booking is rejected with `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409). And a rotation-eligible boat must exist for the requested type, dock, and window with no temporal collision — the absence of one yields `ERR_NO_BOAT_AVAILABLE`.

Access and quota rules follow. A member whose tier does not allow reciprocal access may not reserve a boat at a dock whose `is_reciprocal` flag is true; such an attempt is rejected with `ERR_RECIPROCAL_NOT_ALLOWED` (HTTP 422). A member may hold only up to their tier's `max_active_reservations` reservations concurrently, counting those in `REQUESTED`, `CONFIRMED`, or `CHECKED_OUT`; exceeding that cap is rejected with `ERR_MAX_ACTIVE_RESERVATIONS` (HTTP 409). Separately, the tier's `reservations_per_week` bounds how many reservations a member may run within a single ISO week. That week runs from Monday 00:00 UTC to the following Monday 00:00 UTC and contains the current clock. The member's `reservations_used_this_week` is the count of their reservations whose status is `CONFIRMED`, `CHECKED_OUT`, `RETURNED`, or `NO_SHOW` and whose `start_time` falls within that week; `reservations_remaining_this_week` is the tier's weekly allowance minus that used count, never dropping below zero. A confirm that would push used past the weekly allowance is rejected with `ERR_WEEKLY_QUOTA_EXCEEDED` (HTTP 409). Across a confirm-then-cancel pair the used and remaining counts always sum back to the tier's weekly allowance.

Finally, the fiscal gate: a new reservation is refused when the member's `outstanding_fees_cents` exceeds the 50,000-cent reservation block limit, rejected with `ERR_OUTSTANDING_FEES` (the same code and HTTP 402 that guards reinstatement, which instead requires the outstanding balance to be exactly zero).

### 3.5. Training Sessions and Enrollments

A `ClubAdmin` schedules a training session against a `dock_id`, with a `session_type` of `ORIENTATION`, `BASIC_CERT`, or `ADVANCED_CERT`, a `start_time` and `end_time` (end strictly after start), a `capacity` of at least one, and an `instructor_name`. A session opens in `SCHEDULED` with `enrolled_count` at zero. Its `enrolled_count` is the number of enrollments on it whose status is `ENROLLED` or `ATTENDED`. When enrollments bring `enrolled_count` up to `capacity`, the session automatically moves from `SCHEDULED` to `FULL`; when a later cancellation drops `enrolled_count` back below `capacity`, it automatically returns from `FULL` to `SCHEDULED`. Once every enrollment on a session has had attendance marked, the session moves to `COMPLETED`. Session cancellation to `CANCELLED` is a system placeholder not exposed publicly in this version.

A `Member` enrolls by supplying their own `member_id` and the `session_id`. A new enrollment is `ENROLLED`; it raises the session's `enrolled_count` by one and tips the session to `FULL` if that brings it to capacity. A member may not hold two live enrollments in the same session — a second, non-terminal enrollment is rejected as a duplicate with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409) — and no one may enroll in a session already at capacity, which is rejected with `ERR_SESSION_FULL` (HTTP 409).

`DockStaff` mark attendance on an enrollment, addressed by its `enrollment_id`, by supplying `attended`. The enrollment's session must still be `SCHEDULED` or `FULL` for attendance to be marked. Marking `attended` false moves the enrollment to `NO_SHOW` with no further effect. Marking `attended` true moves it to `ATTENDED` and grants credit according to the session's type, and this is where members climb the certification ladder. For an `ORIENTATION` session, attendance sets the member's `orientation_completed` to true, and if the member was `PENDING_ORIENTATION` they become `ACTIVE`. For a `BASIC_CERT` session, the member must already have completed orientation — otherwise attendance is rejected with `ERR_ORIENTATION_REQUIRED` — and on success the member's `certification_level` is set to `BASIC`. For an `ADVANCED_CERT` session, the member must already hold `certification_level` of `BASIC` — otherwise attendance is rejected with `ERR_CERT_INSUFFICIENT` — and on success the member's `certification_level` is set to `ADVANCED`. Withdrawal of an `ENROLLED` enrollment to `CANCELLED` (which would lower the session's `enrolled_count` and tip a `FULL` session back to `SCHEDULED`) is a system placeholder not exposed publicly in this version.

### 3.6. Fees, Damage Reports, and the Fee Ledger

Fees are the club's meter, and each `Fee` records the owing `member_id`, an originating `reservation_id` (null for non-trip fees), a `fee_type`, an `amount_cents`, a `status` that starts `ASSESSED`, an `assessed_at` clock stamp, and a `source_ref` holding the originating object's id where one applies (for example a damage report id), null otherwise. Fee types are `NO_SHOW`, `LATE_RETURN`, `FUEL`, `CLEANING`, and `DAMAGE`. `DockStaff` may waive an `ASSESSED` fee, addressed by its `fee_id`, moving it to `WAIVED`; a waive attempted on a fee not in `ASSESSED` is rejected with `ERR_FEE_NOT_ASSESSED` (HTTP 409). Across a member's fees, `outstanding_fees_cents` is the sum of `amount_cents` over their fees still `ASSESSED`, `waived_fees_cents` the sum over their `WAIVED` fees, and `paid_fees_cents` the sum over their `PAID` fees; those three partitions always add up to the total of all the member's fee amounts.

Three fees can be born on a single boat return. A late-return fee is charged when the boat comes back past a grace window. The minutes late are the whole minutes between `return_time` and the reservation's `end_time`, rounding any partial minute up, and never less than zero. Exactly 15 minutes late is free; only lateness strictly greater than that 15-minute grace is billable. When it is billable, the fee is 2,500 cents for each started 30-minute block of lateness — that is, 2,500 cents multiplied by the minutes late divided by 30 and rounded up to the next whole block. A fuel fee is charged when `fuel_at_return` comes back below the 25-percent fuel floor: the fee is 100 cents for every percentage point of the drop from `fuel_at_checkout` down to `fuel_at_return`; if the boat returns at or above the floor, there is no fuel fee. A cleaning fee is a flat 4,000 cents, charged only when the returned `cleaning_state` is `SOILED`.

A no-show fee is a flat 5,000 cents, created by the housekeeping sweep described in §3.7. And a damage fee flows from the damage-report workflow. `DockStaff` (or a `ClubAdmin`) file a damage report against a trip by supplying the `reservation_id`, the damaged `boat_id`, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, and an estimated `repair_cost_cents`. A filed report, addressed by its `report_id`, starts `FILED` with `assessed_fee_cents` null. Assessing the report moves it from `FILED` to `ASSESSED`, computes `assessed_fee_cents`, creates a `DAMAGE` fee for the reservation's member, and sends the boat to `MAINTENANCE` — which in turn cascades any `CONFIRMED` reservation on that boat back to `REQUESTED` with its `boat_id` cleared, exactly as in §3.2. The damage fee is the smaller of the reported `repair_cost_cents` and a tier-dependent ceiling: that ceiling is the member's tier deductible — 50,000 cents for `CRUISE`, 30,000 cents for `SAIL`, 10,000 cents for `UNLIMITED` — plus, only when the severity is `SEVERE`, an additional 20,000-cent surcharge. Report dismissal to `DISMISSED` is a system placeholder not exposed publicly in this version.

### 3.7. Housekeeping: The No-Show Sweep

The housekeeping sweep, run by a `ClubAdmin`, advances the world against the current clock in one pass and touches two kinds of stragglers. First, any reservation still in `CONFIRMED` whose start has slipped past a grace window is treated as a no-show: it is marked `NO_SHOW` once the current clock is later than its `start_time` plus the 30-minute no-show grace and it has not been checked out. Marking a no-show creates a flat 5,000-cent `NO_SHOW` fee for the member, increases the member's `no_show_strikes` by one, and releases the assigned boat (the `boat_id` is cleared and the boat stays `AVAILABLE`). Strikes accumulate since the member's most recent reinstatement, and when they reach three the member is suspended: the member transitions from `ACTIVE` to `SUSPENDED`, which itself cascades to cancel the member's other `CONFIRMED` reservations and release their boats, as in §3.1.

Second, the sweep marks billing overdue: any dues invoice still `ISSUED` whose billing period has closed — that is, the current clock has reached or passed its `period_end` — moves from `ISSUED` to `OVERDUE`. An overdue invoice remains fully payable.

### 3.8. Dues Billing: Issuing and Paying Invoices

Dues are billed per member on invoices that pin two totals at two distinct moments. A `ClubAdmin` issues an invoice for a member by supplying the billing `period_start` (inclusive), the `period_end` (exclusive, strictly after the start), and the `expected_member_version` required by the concurrency rule of §2.7. On issue the invoice starts `ISSUED`, snapshots the member's tier monthly dues into `base_dues_cents`, pins a forward-looking `estimated_total_cents`, stamps `issued_at` at the current clock, and leaves `final_total_cents`, `paid_at`, and `rolled_fee_ids` empty until payment. Issuing a new invoice supersedes any prior unpaid invoice for that member by moving it to `VOID`, and it increments the member's `version` by one.

Both totals are built the same way but over different fee sets. The rolled fee amount, `fees_rolled_cents`, is computed by taking each of the member's fees that is `ASSESSED` with an `assessed_at` strictly before the evaluation instant, multiplying that fee's `amount_cents` by one plus the 8.5-percent tax rate, rounding that single line to whole cents with the round-half-up rule, and only then summing the rounded lines — per line first, sum second, never sum first. The invoice total is `base_dues_cents` plus that summed `fees_rolled_cents`. The estimated total is evaluated as of `issued_at`, so it rolls only the fees already assessed at issue and is stored in `estimated_total_cents`. The final total is evaluated as of the payment instant.

A `Member` pays their own invoice, addressed by its `invoice_id`, while it is `ISSUED` or `OVERDUE`; a pay attempt against an invoice in any other state is rejected as an invalid state transition (`ERR_INVALID_STATE`, HTTP 409). Paying recomputes `fees_rolled_cents` chronologically as of `paid_at` — capturing every fee assessed up to payment, including any assessed after the invoice was issued — pins that result into `final_total_cents`, records the ids of the folded fees in `rolled_fee_ids`, sets `paid_at` to the current clock, moves the invoice to `PAID`, and settles each rolled fee that was `ASSESSED` to `PAID`. The final total diverges from the estimate precisely when a fee is assessed in the gap between issue and payment. Throughout, a member's `dues_balance_cents` reflects `final_total_cents` for settled invoices and `estimated_total_cents` for those still outstanding, over all invoices not `PAID` and not `VOID`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or act on an existing resource return `200 OK`. The two administrative test-driving operations (`/_clock/set_current_utc` and `/_ops/run-no-show-sweep`) return `200 OK` and carry no resource body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/docks` | Create a dock | ClubAdmin |
| GET | `/docks/{dock_id}` | Get a dock | Member, DockStaff, ClubAdmin |
| GET | `/docks` | List docks | Member, DockStaff, ClubAdmin |
| POST | `/membership-tiers` | Create a membership tier | ClubAdmin |
| GET | `/membership-tiers/{tier_code}` | Get a tier by code | Member, DockStaff, ClubAdmin |
| GET | `/membership-tiers` | List tiers | Member, DockStaff, ClubAdmin |
| POST | `/boats` | Create a boat | ClubAdmin |
| GET | `/boats/{boat_id}` | Get a boat | Member, DockStaff, ClubAdmin |
| GET | `/boats` | List/filter boats | Member, DockStaff, ClubAdmin |
| POST | `/boats/{boat_id}/maintenance` | Send a boat to maintenance | DockStaff, ClubAdmin |
| POST | `/boats/{boat_id}/clean-complete` | Return a boat to service | DockStaff, ClubAdmin |
| POST | `/members` | Enroll a new member | ClubAdmin |
| GET | `/members/{member_id}` | Get a member (exposes version) | Member, DockStaff, ClubAdmin |
| GET | `/members` | List/filter members | DockStaff, ClubAdmin |
| POST | `/members/{member_id}/suspend` | Suspend an active member | ClubAdmin |
| POST | `/members/{member_id}/reinstate` | Reinstate a suspended member | ClubAdmin |
| POST | `/members/{member_id}/dues-invoices` | Issue a dues invoice | ClubAdmin |
| POST | `/reservations` | Request a boat reservation | Member |
| GET | `/reservations/{reservation_id}` | Get a reservation | Member, DockStaff, ClubAdmin |
| GET | `/reservations` | List/filter reservations | Member, DockStaff, ClubAdmin |
| POST | `/reservations/{reservation_id}/confirm` | Confirm a reservation | Member |
| POST | `/reservations/{reservation_id}/checkout` | Check out the assigned boat | Member |
| POST | `/reservations/{reservation_id}/return` | Return the boat | Member |
| POST | `/reservations/{reservation_id}/cancel` | Cancel a reservation | Member |
| POST | `/training-sessions` | Schedule a training session | ClubAdmin |
| GET | `/training-sessions/{session_id}` | Get a training session | Member, DockStaff, ClubAdmin |
| GET | `/training-sessions` | List/filter sessions | Member, DockStaff, ClubAdmin |
| POST | `/enrollments` | Enroll a member in a session | Member |
| GET | `/enrollments/{enrollment_id}` | Get an enrollment | Member, DockStaff, ClubAdmin |
| GET | `/enrollments` | List/filter enrollments | Member, DockStaff, ClubAdmin |
| POST | `/enrollments/{enrollment_id}/mark-attendance` | Mark attendance; grant certification | DockStaff, ClubAdmin |
| POST | `/damage-reports` | File a damage report | DockStaff, ClubAdmin |
| GET | `/damage-reports/{report_id}` | Get a damage report | Member, DockStaff, ClubAdmin |
| GET | `/damage-reports` | List/filter damage reports | DockStaff, ClubAdmin |
| POST | `/damage-reports/{report_id}/assess` | Assess a damage report | DockStaff, ClubAdmin |
| GET | `/fees/{fee_id}` | Get a fee | Member, DockStaff, ClubAdmin |
| GET | `/fees` | List/filter fees | Member, DockStaff, ClubAdmin |
| POST | `/fees/{fee_id}/waive` | Waive an assessed fee | DockStaff, ClubAdmin |
| GET | `/dues-invoices/{invoice_id}` | Get a dues invoice | Member, DockStaff, ClubAdmin |
| GET | `/dues-invoices` | List/filter dues invoices | Member, DockStaff, ClubAdmin |
| POST | `/dues-invoices/{invoice_id}/pay` | Pay a dues invoice | Member |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ClubAdmin |
| POST | `/_ops/run-no-show-sweep` | Run the housekeeping sweep | ClubAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_DOCK_NOT_FOUND` | 404 |
| `ERR_TIER_NOT_FOUND` | 404 |
| `ERR_BOAT_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_DAMAGE_REPORT_NOT_FOUND` | 404 |
| `ERR_FEE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_BOAT_NOT_AVAILABLE` | 409 |
| `ERR_FEE_NOT_ASSESSED` | 409 |
| `ERR_CERT_INSUFFICIENT` | 422 |
| `ERR_ORIENTATION_REQUIRED` | 422 |
| `ERR_BOOKING_WINDOW` | 409 |
| `ERR_MEMBER_SCHEDULE_CONFLICT` | 409 |
| `ERR_NO_BOAT_AVAILABLE` | 409 |
| `ERR_RECIPROCAL_NOT_ALLOWED` | 422 |
| `ERR_MAX_ACTIVE_RESERVATIONS` | 409 |
| `ERR_WEEKLY_QUOTA_EXCEEDED` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_OUTSTANDING_FEES` | 402 |
| `ERR_STALE_VERSION` | 412 |
