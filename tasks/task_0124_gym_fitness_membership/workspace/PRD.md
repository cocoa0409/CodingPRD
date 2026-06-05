# Gym & Fitness Membership API — Product Requirements Document

## 1. Introduction

The Gym & Fitness Membership API is the operational backbone of a multi-location fitness business. It governs the full arc of a member relationship: the moment a prospect signs a contract and is registered against a plan, the recurring monthly dues that keep that relationship in good standing, the day-to-day act of walking through a turnstile, reserving a seat in a popular spin class, or booking a one-on-one session with a trainer, and finally the orderly wind-down when a member decides to leave. The business problem this system solves is that all of these concerns are entangled: a member who stops paying must eventually lose access; a member who freezes their membership for travel should not keep holding seats in classes they cannot attend; a class that fills up must fairly promote the people who have been waiting longest; and a cancellation must settle the books differently depending on whether the member is still inside a legally mandated cooling-off window.

Three independent dimensions of a member's standing must be tracked at once. The **membership lifecycle** describes whether the person is pending activation, actively training, temporarily frozen, or gone. The **dues standing** describes how far behind they are on payments, escalating through a delinquency ladder on a purely time-driven basis. The **contract term** describes where the member sits relative to the cooling-off window and the committed contract length, which is what decides the financial consequences of leaving. These three axes move on their own schedules and must never be conflated; a member can be perfectly current on dues yet frozen, or actively training yet sliding toward suspension for non-payment.

This document specifies every entity, state transition, calculation, validation, and access rule the implementation must honor. Quota allocation (class capacity, waitlists, and the personal-training session pool) and compliance auditing (cooling-off rules, delinquency gating, contract enforcement) are the two pillars; optimistic concurrency, cascading side effects, and dual-variant settlement math are the recurring patterns that make the domain demanding.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across every endpoint. Collections are flat: members, class sessions, bookings, PT packages, dues invoices, guest passes, and check-ins all live at the root of the URL space and reference one another through identifiers rather than being nested under a parent path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they are acting. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, or a member attempts to act on a resource that is not theirs, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly two roles: `StaffManager` and `Member`.

A `StaffManager` is front-desk or operations staff. When `X-User-Role` is `StaffManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`; a `StaffManager` may act on any member's resources without an ownership check.

A `Member` is an enrolled individual acting on their own account. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's member foreign key (for example, a booking's `member_id`, a PT package's `member_id`, a dues invoice's `member_id`, or a guest pass's `member_id`) to `X-User-ID`; when a member targets a member record directly, the record's own `id` must equal `X-User-ID`. A member acting on a resource that belongs to someone else is rejected with `ERR_UNAUTHORIZED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and is never a business-decision input. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every modification. The `version` field is an integer that starts at 1 on creation and increments by exactly one on every mutation, including mutations caused by cascaded side effects rather than a direct request against the resource.

`CheckIn` is the one exception. A check-in is an append-only access event: it carries only `id` and `created_at`. It has no `updated_at` and no `version` field. Its only state change — being closed at checkout — is described in §3 but does not introduce a `version`.

The `version` field is also the basis of optimistic concurrency control, described in §2.7.

### 2.5. The Three Parallel Status Axes of a Member

A member is not described by a single status. Three enumerated axes evolve independently and must each be stored and reported.

The **membership lifecycle** axis is `membership_status`, with values `PENDING`, `ACTIVE`, `FROZEN`, and `CANCELLED`. A newly registered member begins `PENDING`; `CANCELLED` is terminal.

The **delinquency** axis is `dues_status`, with values `CURRENT`, `PAST_DUE`, `DELINQUENT`, and `SUSPENDED`. A new member begins `CURRENT`. This axis is driven entirely by elapsed time since an overdue invoice and moves independently of the lifecycle axis, so a member can be `ACTIVE` on the lifecycle axis while `SUSPENDED` on the dues axis.

The **contract term** axis is `contract_status`, with values `IN_COOLING_OFF`, `IN_TERM`, `FULFILLED`, and `TERMINATED`. A new member begins `IN_COOLING_OFF`; both `FULFILLED` and `TERMINATED` are terminal. This axis decides the financial treatment of a cancellation.

Because these axes are independent, any operation that changes one axis must not silently change another except where this document explicitly states a cross-axis cascade. Each axis transition is itself a mutation of the member, refreshing `updated_at` and incrementing `version`.

### 2.6. Hierarchical Consistency and Cascading Side Effects

Many operations touch more than one entity. When a single operation changes a count, frees a seat, or terminates a parent, the system must propagate every consequence in the same operation rather than leaving derived data stale.

Several fields are **derived** and must be kept reconciled rather than accepted as input. A class session's `booked_count` is the number of bookings on it in `BOOKED` status and never exceeds `capacity`; its `waitlisted_count` is the number in `WAITLISTED` status and never exceeds `waitlist_cap`. A member's `class_credits_remaining`, `guest_passes_remaining`, `wallet_credit_cents`, and `cumulative_freeze_days` are all maintained by the system. A PT package's `sessions_remaining` is its purchased count minus the sessions currently drawing on it. A location's `current_occupancy` is the count of check-ins there in `OPEN` status and is never negative. A booking's `waitlist_position` is recomputed as the waitlist changes.

Whenever a cascade mutates a session (a booking count change, a waitlist promotion) or a package (a deduction or reinstatement), that parent's own `version` increments and `updated_at` refreshes, exactly as a direct mutation would. A single member cancellation may therefore bump the versions of the member, several bookings, several sessions, one or more PT packages, and several PT sessions in one logical operation. The implementation must apply all of these consistently and immediately.

### 2.7. Optimistic Concurrency Control

Two create operations are guarded against acting on a stale view of a shared parent, because both consume a limited pool that another writer may have just exhausted.

Booking a class is guarded against the parent `ClassSession`. A booking-create request must carry `expected_session_version`, which is the `version` of the target session the client last observed. If that value does not equal the session's current `version`, the create is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412). This protects the case where the last open seat was taken by another booking — which advances the session's `version` and changes its `booked_count` — so the current writer's view of available capacity is stale and cannot be trusted.

Scheduling a personal-training session is guarded against the parent `PTPackage`. A PT-session-create request must carry `expected_package_version`, the `version` of the target package the client last observed. If that value does not equal the package's current `version`, the request is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412). This protects the case where the last remaining session was just consumed by another scheduling call — which advances the package's `version` and may flip it to `EXHAUSTED` — leaving the current writer's view of `sessions_remaining` stale.

Two staff-driven session operations and one PT-session cancel are likewise guarded by the parent's version: cancelling a class session and completing a class session both require `expected_session_version` to match the session's current `version`, and cancelling a PT session requires `expected_package_version` to match the package's current `version`. A mismatch on any of these is rejected with HTTP 412 carrying the session-specific or package-specific stale-version error as appropriate (`ERR_STALE_SESSION_VERSION` for sessions, `ERR_STALE_PACKAGE_VERSION` for packages). Endpoints not named here do not take a version field and perform no concurrency check.

### 2.8. Access Control and Occupancy at the Turnstile

Physical access is governed by the facility's `occupancy_cap` and by the entering member's standing. A location's `current_occupancy` counts the check-ins at that location currently in `OPEN` status. An entry is permitted only while occupancy is strictly below the cap: an attempt to enter when `current_occupancy` is at least equal to `occupancy_cap` is rejected with `ERR_OCCUPANCY_FULL` (HTTP 409). Concretely, when the cap is reached the next entry is refused, and an entry while occupancy is one below the cap succeeds and raises occupancy to exactly the cap. Each successful entry adds one to `current_occupancy`; each checkout subtracts one without ever driving the count below zero.

Standing also gates entry. A member may not enter while their dues axis is `SUSPENDED` or while their membership lifecycle is anything other than `ACTIVE`; such an attempt is rejected with `ERR_ACCESS_DENIED_SUSPENDED` (HTTP 403). The same standing requirement applies to a guest entering on that member's sponsorship.

### 2.9. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents — `monthly_dues_cents`, `early_termination_fee_cents`, `gross_amount_cents`, `wallet_applied_cents`, `amount_due_cents`, `list_price_cents`, `price_paid_cents`, and `wallet_credit_cents` are all integers. The cancellation-settlement math operates on integer-cent inputs and requires no rounding. Where a calculation divides — dues proration and the personal-training discount — the result is rounded to a whole number of cents using the round-half-up convention (a fractional half-cent rounds up to the next cent). Money is never represented below zero: `amount_due_cents`, `wallet_credit_cents`, and a location's occupancy all have a hard floor of zero.

### 2.10. Validation Ordering

When a single request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first. Authorization, including the member-ownership check, is checked next (`ERR_UNAUTHORIZED`). Then the existence and non-archived status of every referenced resource is verified, evaluating path identifiers and body foreign keys left to right (`ERR_NOT_FOUND`). Then request-body well-formedness is checked: required fields present and correctly typed, enum values valid, and the temporal invariants that a period's end is strictly after its start and a session's `ends_at` is strictly after its `starts_at` (`ERR_INVALID_REQUEST`). For member registration specifically, email uniqueness (`ERR_DUPLICATE_EMAIL`) is checked, followed by the plan-not-archived check (`ERR_PLAN_ARCHIVED`). Then, on guarded writes, the optimistic-concurrency version check runs (HTTP 412). Then the target resource's state is checked for transition validity (`ERR_INVALID_STATE`), followed by any operation-specific business rules described in §3. The general principle is that cheaper, more fundamental failures surface before deeper business-rule failures, so a request that is both unauthenticated and malformed reports the authentication failure.

### 2.11. The Logical Clock and the Time-Driven Sweep

Time in this system advances only when explicitly told to, which makes delinquency, contract progression, and guest-pass expiry deterministically testable. An administrative capability sets the server's current UTC clock to a supplied instant carried as `to_iso8601`; setting the clock alone runs no entity transitions. A separate administrative sweep capability evaluates time-driven transitions at the current clock: it advances the member delinquency ladder, advances contract-term transitions, and expires guest passes. These two capabilities are described functionally here; their place in the workflow appears in §3.

## 3. Business Logic & Workflows

### 3.1. Configuration: Plans and Locations

Before any member exists, a `StaffManager` configures the catalog. A **membership plan** is created with a `tier` — one of `BASIC`, `PLUS`, or `ELITE`, which must be unique among non-archived plans — together with its commercial terms: the recurring `monthly_dues_cents` (zero or more), the `included_class_credits` granted each billing cycle (zero or more), the `pt_discount_pct` applied to personal-training list prices (a fraction from 0.0 up to and including 0.5, defaulting to 0), the committed `contract_term_months` (at least 1), the flat `early_termination_fee_cents` charged on a mid-term exit (zero or more), the `max_freeze_days_per_term` cap on cumulative freeze days (zero or more), and the `guest_passes_per_cycle` granted each cycle (zero or more). A plan also carries an `archived` flag, which starts false; an archived plan rejects new registrations but is retained for existing members.

A **location** is created with a `name` and an `occupancy_cap` (at least 1). Its `current_occupancy` begins at zero and is maintained by the system as people enter and leave; it is never reported as input and never drops below zero.

### 3.2. Registration and Activation

Registering a member is a `StaffManager` action that establishes the member and their opening invoice in one step. The request supplies the `plan_id` the member is enrolling on, the `home_location_id` that will be their primary facility, their `full_name`, their `email`, and the billing boundaries of the first period — `period_start`, `period_end`, and `due_date`. The email must be unique across non-archived members; a collision is rejected with `ERR_DUPLICATE_EMAIL`. The referenced plan must not be archived; a registration against an archived plan is rejected with `ERR_PLAN_ARCHIVED`.

On successful registration the new member starts with `membership_status` of `PENDING`, `dues_status` of `CURRENT`, and `contract_status` of `IN_COOLING_OFF`. The contract terms are snapshotted onto the member at this instant: `signed_at` is set to the current clock, `contract_term_months` is copied from the plan and thereafter immutable, `cooling_off_ends_at` is set to seven days after `signed_at`, and `term_ends_at` is set to the signing instant advanced by the snapshotted number of contract months. The system simultaneously creates the joining invoice as an `OPEN` `DuesInvoice` whose `gross_amount_cents` is computed by the provisional proration described in §3.8. Until that joining invoice is paid, the member's spendable balances stay at their floor: `class_credits_remaining`, `guest_passes_remaining`, `wallet_credit_cents`, and `cumulative_freeze_days` are all zero.

Activation is the bridge from `PENDING` to `ACTIVE`, performed by a `StaffManager`. It is permitted only once the joining invoice has reached `PAID`; an attempt to activate before that invoice is settled is rejected with `ERR_ACTIVATION_NOT_PAID` (HTTP 409). Activation sets `membership_status` to `ACTIVE` and increments the member's `version`. Activation does not itself touch the contract axis: the member remains `IN_COOLING_OFF` until the clock later passes `cooling_off_ends_at`.

### 3.3. Freezing and Unfreezing

A `StaffManager` may freeze an active membership for a span of days, supplied as `freeze_days`. Freezing is permitted only when the member's `membership_status` is `ACTIVE` and their `dues_status` is either `CURRENT` or `PAST_DUE`. A member whose dues axis has reached `SUSPENDED` cannot be frozen; the attempt is rejected with `ERR_FREEZE_BLOCKED_BY_DUES` (HTTP 409). The requested span is also capped: when the requested `freeze_days` is added to the member's existing `cumulative_freeze_days`, the sum may not exceed the plan's `max_freeze_days_per_term`; a request that would push the total over that cap is rejected with `ERR_FREEZE_CAP_EXCEEDED` (HTTP 409).

When a freeze succeeds, `membership_status` moves to `FROZEN`, the requested span is added to `cumulative_freeze_days`, and the member's `version` increments. Freezing also cleans up commitments the frozen member can no longer honor: every future-dated `BOOKED` booking the member holds on a `SCHEDULED` session that starts after the freeze instant is cancelled. Each such cancellation runs the waitlist-promotion cascade on its session (described in §3.5) and restores one class credit to the member if that booking had `credit_charged` set.

Unfreezing returns a `FROZEN` member to `ACTIVE`. It is permitted only from `FROZEN`, sets `membership_status` back to `ACTIVE`, and increments the member's `version`. It does not retroactively restore the bookings that the freeze cancelled.

### 3.4. The Delinquency Ladder and Contract Progression

A member's dues standing escalates purely with elapsed time, evaluated whenever the administrative sweep runs at the current clock. The trigger that first moves a member off `CURRENT` is the existence of at least one `OPEN` dues invoice whose `due_date` falls strictly before the current clock; when the sweep finds such a member it sets `dues_status` to `PAST_DUE` and stamps `past_due_since` with the due date of that oldest open invoice. While `dues_status` is `CURRENT`, `past_due_since` is null.

From `PAST_DUE` the ladder climbs by whole days elapsed since `past_due_since`. The elapsed span is the difference between the current clock and `past_due_since`, taken as a count of whole days (any partial day is dropped, i.e. the floor of the day count). The boundaries are inclusive: when at least 15 whole days have elapsed the member becomes `DELINQUENT`, and when at least 30 whole days have elapsed the member becomes `SUSPENDED`. Stated against the boundaries directly: 14 whole days elapsed is still `PAST_DUE`, exactly 15 is `DELINQUENT`, 29 is still `DELINQUENT`, and exactly 30 is `SUSPENDED`. Reaching `SUSPENDED` carries a cross-axis consequence — the member's physical access is blocked and class booking is blocked while suspended — but it does not change the membership lifecycle axis; a suspended member's `membership_status` is untouched by the sweep. Each of these dues transitions increments the member's `version`.

The episode clears when the member settles their overdue obligation. Paying an invoice such that the member then has zero `OPEN` invoices with a `due_date` before the current clock resets `dues_status` to `CURRENT` and sets `past_due_since` back to null, incrementing the member's `version`. This recovery is available from `PAST_DUE`, `DELINQUENT`, or `SUSPENDED`.

The contract axis also advances under the sweep. While `contract_status` is `IN_COOLING_OFF`, the first sweep that observes the current clock strictly past `cooling_off_ends_at` moves it to `IN_TERM`. While `IN_TERM`, the first sweep that observes the current clock strictly past `term_ends_at` moves it to `FULFILLED`. Each contract transition increments the member's `version`. The contract axis can also be forced to `TERMINATED` as a consequence of cancellation, described next.

### 3.5. Classes: Scheduling, Booking, Waitlists, and Attendance

A `StaffManager` schedules a class by creating a `ClassSession` at a `location_id`, with a `title`, a start instant `starts_at`, an end instant `ends_at` that must be strictly after `starts_at`, a `capacity` of at least one seated member, and a `waitlist_cap` of zero or more. A new session starts `SCHEDULED` with `booked_count` and `waitlisted_count` both at zero.

Booking a seat is available to a `StaffManager` or to the owning `Member`, and the request carries the `session_id`, the `member_id` of the booking member, and `expected_session_version` for the concurrency check described in §2.7. Several gates apply before a seat is granted. The member must be bookable: booking is permitted only while the member's `membership_status` is `ACTIVE` and their `dues_status` is not `SUSPENDED`; otherwise the request is rejected with `ERR_MEMBER_NOT_BOOKABLE` (HTTP 409). The session's capacity geometry is checked: when the seated pool is full (`booked_count` has reached `capacity`) and the waitlist pool is also full (`waitlisted_count` has reached `waitlist_cap`), the booking is rejected with `ERR_SESSION_FULL` (HTTP 409). The member may not double-book overlapping time: if the member already holds a non-terminal booking — one in `BOOKED` or `WAITLISTED` status — on another session whose half-open time interval from its `starts_at` up to but not including its `ends_at` overlaps this session's interval, the request is rejected with `ERR_BOOKING_TIME_OVERLAP` (HTTP 409).

The initial state of the booking is chosen by capacity. If the seated pool has room (`booked_count` is below `capacity`), the booking is created `BOOKED`: this debits one class credit, so it requires `class_credits_remaining` to be at least one — a member with no remaining credits is rejected with `ERR_NO_CLASS_CREDITS` (HTTP 402) — and on success it sets `credit_charged` to true, sets `booked_at` to the current clock, and decrements the member's `class_credits_remaining`. If the seated pool is full but the waitlist has room, the booking is created `WAITLISTED` instead; waitlisting holds no credit, so `credit_charged` stays false, `booked_at` stays null, and no credit check applies. Either way the session's `version` increments to reflect the count change.

A waitlisted booking's `waitlist_position` is its one-based rank among the session's `WAITLISTED` bookings ordered by `created_at` ascending; because `created_at` carries millisecond precision this ordering is total, and the booking `id` is never used as a tie-break. The position is null unless the booking is waitlisted, and it is recomputed whenever the waitlist changes.

Cancelling a booking is available to a `StaffManager`, the owning `Member`, or the system as a cascade. It is permitted from `BOOKED` or `WAITLISTED`, sets the booking to `CANCELLED`, and — if the booking had `credit_charged` set — restores one class credit to the member and clears `credit_charged`. When the cancelled booking had been a seated (`BOOKED`) booking, a seat has just freed, so the system runs **waitlist promotion** on that session: it promotes the eligible waitlisted booking with the lowest `waitlist_position` (equivalently the earliest `created_at`) into the freed seat. A waitlisted booking is eligible only if its member is `ACTIVE`, not `SUSPENDED` on the dues axis, and holds at least one `class_credits_remaining`; ineligible waitlisted bookings are skipped (their positions are recomputed but they are not promoted). Promotion moves the chosen booking from `WAITLISTED` to `BOOKED`, sets its `booked_at` to the current clock, sets `credit_charged` to true, and debits one class credit from that member. Both the promoted booking's `version` and the session's `version` increment. A booking cancellation always increments the booking's `version` and the session's `version`.

Marking attendance is a `StaffManager` action that moves a `BOOKED` booking to `ATTENDED`. It is permitted only while the booking is `BOOKED`, the owning session is still `SCHEDULED`, and the member currently holds an `OPEN` check-in at that session's location. It increments the booking's `version`.

A `StaffManager` may cancel a scheduled session. Cancellation is permitted only while the session is `SCHEDULED` and the supplied `expected_session_version` matches the session's current `version`. It sets the session's `status` to `CANCELLED`, transitions every `BOOKED` and `WAITLISTED` booking on the session to `CANCELLED`, restores one class credit to each member whose cancelled booking had `credit_charged` set, and increments the session's `version`.

Completing a session is the counterpart for a class that has actually run; it too is a `StaffManager` action gated by `expected_session_version`. It is permitted only while the session is `SCHEDULED` and the current clock has reached `ends_at` (the clock is at or past `ends_at`). On completion the session's `status` becomes `COMPLETED`; every booking still in `BOOKED` becomes `NO_SHOW` because the member never attended — and a no-show forfeits the credit, so no credit is restored — while every `WAITLISTED` booking becomes `CANCELLED` since it never held a credit. The session's `version` increments. (A booking thus reaches `NO_SHOW` only through session completion while still seated; the booking lifecycle's terminal states are `ATTENDED`, `CANCELLED`, and `NO_SHOW`.)

### 3.6. Personal Training: Packages and Sessions

A member may buy a block of personal-training sessions, and the purchase is open to a `StaffManager` or the owning `Member`. The request carries the `member_id` of the owner, the `sessions_purchased` count (at least one), and the pre-discount `list_price_cents` (zero or more). The price actually charged, `price_paid_cents`, is computed by applying the member's plan discount to the whole list price (see §3.9). On creation the package's `sessions_remaining` equals `sessions_purchased` and its `status` is `ACTIVE`.

Scheduling a PT session draws one session from a package and is open to a `StaffManager` or the owning `Member`. The request carries the `package_id`, a `trainer_name`, the session `starts_at`, and `expected_package_version` for the concurrency check in §2.7. Scheduling requires the package to be `ACTIVE` with `sessions_remaining` of at least one; a package that is not active or has no sessions left is rejected with `ERR_NO_PT_SESSIONS` (HTTP 402). The member may not schedule overlapping training time: a fixed sixty-minute busy block is associated with each scheduled session, and a new session's `starts_at` may not fall within the half-open block of any existing `SCHEDULED` PT session for the same member — that is, within the interval from an existing session's `starts_at` up to but not including the instant sixty minutes after it. A clash is rejected with `ERR_PT_TIME_OVERLAP` (HTTP 409). On success the session is created `SCHEDULED` with `deducted` true, one session is deducted from the package (`sessions_remaining` decreases by one), and the package's `version` increments; if the deduction brings `sessions_remaining` to zero the package transitions from `ACTIVE` to `EXHAUSTED`, a further version increment.

A `StaffManager` completes a PT session that has occurred: completion is permitted only while the session is `SCHEDULED` and the current clock has reached `starts_at` (at or past it), sets the session to `COMPLETED`, leaves the deduction standing with `deducted` remaining true, and increments the session's `version`. A `StaffManager` may instead mark a no-show under the same state and timing precondition; a no-show forfeits the session, so it moves to `NO_SHOW`, the deduction stands with `deducted` staying true, and the session's `version` increments.

Cancelling a PT session is open to a `StaffManager` or the owning `Member` and reinstates the deduction, but only outside a cutoff window. Cancellation is permitted only while the session is `SCHEDULED`, only when the current clock is strictly earlier than twenty-four hours before the session's `starts_at`, and only when the supplied `expected_package_version` matches the package's current `version`. A cancel attempted within twenty-four hours of `starts_at` is rejected with `ERR_PT_LATE_CANCEL` (HTTP 409). On a successful cancel the session moves to `CANCELLED`, `deducted` is set to false, and one session is reinstated to the package (`sessions_remaining` increases by one); if that package had been `EXHAUSTED` it returns to `ACTIVE`. Both the session's `version` and the package's `version` increment.

The package's `EXHAUSTED` state is a resting state, not a terminal one: a reinstating cancel can move it back to `ACTIVE`. The only terminal package state is `VOID`, reached when the owning member is cancelled (see §3.7).

### 3.7. Cancelling a Membership and the Settlement Split

Cancelling a membership is open to a `StaffManager` or the owning `Member` and is permitted from any non-terminal lifecycle state — `PENDING`, `ACTIVE`, or `FROZEN` — provided the member is not already `CANCELLED`. Cancellation sets `membership_status` to `CANCELLED` and, unless the contract was already `FULFILLED`, drives `contract_status` to the terminal `TERMINATED`. It then computes the financial settlement (described below), cleans up the member's open commitments, and increments the member's `version`.

The cleanup is broad. Every future-dated booking the member holds in `BOOKED` or `WAITLISTED` status on a `SCHEDULED` session is cancelled; each formerly-`BOOKED` cancellation runs the waitlist-promotion cascade on its session exactly as an ordinary booking cancel would. Every `ACTIVE` PT package the member owns is voided to `VOID`, and each such package's `SCHEDULED` PT sessions are cancelled — the deduction is reinstated on those sessions, but because the package is now `VOID` its `sessions_remaining` is frozen at the voided value rather than continuing to fluctuate.

The settlement itself is a dual-variant calculation keyed off the contract axis at the moment of cancellation, using the current clock as "now." All amounts are integer cents and no rounding is needed. In the **cooling-off variant**, applicable when now is on or before the member's `cooling_off_ends_at`, the member is made whole: the refund equals the sum of `gross_amount_cents` across the member's `PAID` dues invoices (open and voided invoices are excluded), and no early-termination fee is charged. In the **mid-term variant**, applicable when now is strictly after `cooling_off_ends_at` but on or before `term_ends_at`, there is no refund and the flat `early_termination_fee_cents` from the plan is assessed. In the **post-term variant**, applicable when now is strictly after `term_ends_at`, there is no refund and no fee. The net amount owed to the member is the refund minus the fee. When that net is positive, it is added to the member's `wallet_credit_cents`. When that net is negative — which is the mid-term case where the fee applies — an `OPEN` dues invoice is created for the absolute value of the net (the fee is billed); the fee never reduces `wallet_credit_cents` below zero.

### 3.8. Recurring Dues, Payment, and the Proration Split

Beyond the joining invoice created at registration, a `StaffManager` posts recurring dues by creating a `DuesInvoice` for a member, supplying the `member_id`, the covered `period_start` and `period_end` (the end strictly after the start), and the `due_date` that drives the delinquency day-count. The invoice's `gross_amount_cents` is computed by the proration rule below; its `wallet_applied_cents` is the amount of the member's `wallet_credit_cents` consumed against this invoice at posting time, and `amount_due_cents` is the gross minus the wallet applied, never below zero. A new invoice is `OPEN`.

Proration is a dual-variant calculation off the plan's `monthly_dues_cents` as the base. For a **full** period the gross simply equals the base. For a **provisional** first or partial period — the variant pinned at first invoice creation — the system uses the daily calendar method: it counts the covered days as the whole days in the half-open span from `period_start` up to but not including `period_end`, counts the billing days as the whole days in the full calendar month that contains `period_start`, and sets the gross to the base multiplied by covered days divided by billing days, rounded half-up to whole cents. For the **final** reconciliation variant — applied only when the cycle later reconciles — the system instead uses a fixed thirty-day month: the gross is the base multiplied by the covered days divided by thirty, rounded half-up to whole cents. The daily-calendar and fixed-thirty variants deliberately produce different cents for the same partial span; the system pins the provisional daily-calendar value at first creation and only applies the final fixed-thirty value at cycle reconciliation. In every variant `wallet_applied_cents` and `amount_due_cents` follow the computed gross.

Paying an invoice is open to a `StaffManager` or the owning `Member` and is permitted only while the invoice is `OPEN`. Payment moves the invoice to `PAID` and resets the member's cycle allowances for the new cycle: `class_credits_remaining` is reset to the plan's `included_class_credits` and `guest_passes_remaining` to the plan's `guest_passes_per_cycle`. If this payment clears the member's oldest overdue invoice, it also runs the dues-axis recovery to `CURRENT` described in §3.4. The invoice's `version` increments.

A `StaffManager` may instead void an `OPEN` invoice as a write-off; voiding moves it to `VOID`, does not reset the cycle allowances, and increments the invoice's `version`.

### 3.9. The Personal-Training Discount Calculation

The charged price of a PT package is derived once, at purchase, from the member's plan. The discount fraction is the plan's `pt_discount_pct`, a value from 0.0 up to and including 0.5. The evaluation order is pinned: the discount is applied to the whole `list_price_cents` — the package's list price is multiplied by one minus the discount fraction — and the result is rounded half-up to whole cents exactly once. The price is not computed per session and then summed. A per-session figure obtained by dividing `price_paid_cents` by `sessions_purchased` (round-half-up) is a display-only convenience and is never summed back into `price_paid_cents`.

### 3.10. Guest Passes

A member may sponsor a guest, and issuing a pass is open to a `StaffManager` or the owning `Member`. The request carries the `member_id` of the sponsor, the `guest_name`, and the `location_id` the pass admits to. Issuing requires the sponsor to hold at least one `guest_passes_remaining`; with none left the request is rejected with `ERR_NO_GUEST_PASSES` (HTTP 402). On issue the pass is `ISSUED`, its `issued_at` is the current clock, and its `expires_at` is fourteen days after `issued_at`; the sponsor's `guest_passes_remaining` decreases by one.

A guest enters by being checked in against their pass, which redeems it. Redemption — driven through a turnstile entry that supplies the `guest_pass_id` — is permitted only while the pass is `ISSUED`, only while the current clock is at or before the pass's `expires_at`, only while the sponsoring member's `membership_status` is `ACTIVE` and `dues_status` is not `SUSPENDED`, and only while the destination location's `current_occupancy` is below its `occupancy_cap`. A redemption attempted after `expires_at` is rejected with `ERR_GUEST_PASS_EXPIRED` (HTTP 409). On a successful redemption the pass moves to `REDEEMED` and an `OPEN` check-in is created for the guest, raising the location's `current_occupancy` by one.

If a pass is never used it ages out: when the sweep observes the current clock past `expires_at`, an `ISSUED` pass moves to `EXPIRED`. A `StaffManager` may instead revoke an `ISSUED` pass; revocation moves it to `REVOKED` and restores one `guest_passes_remaining` to the sponsoring member.

### 3.11. Turnstile Entry, Check-Out, and the Access Event Log

A turnstile entry is a `StaffManager` action that records access. The request carries the `location_id` and exactly one of two member-or-guest discriminators: a `member_id` for a member entry or a `guest_pass_id` for a guest entry. The resulting `CheckIn` derives its `actor_kind` from which identifier was supplied — `MEMBER` when the member identifier was given, `GUEST` when the guest pass was given — and starts in `OPEN` status with its `created_at` set to the entry instant. Creating the check-in raises the location's `current_occupancy` by one. A member entry is subject to the suspension and occupancy gates of §2.8 (`ERR_ACCESS_DENIED_SUSPENDED` for a suspended or non-active member, `ERR_OCCUPANCY_FULL` at capacity), and a guest entry additionally redeems the supplied pass as described in §3.10.

Checking out closes an entry: a `StaffManager` closes an `OPEN` check-in, moving its `status` to `CLOSED` and lowering the location's `current_occupancy` by one, never below zero.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or drive a state transition on an existing resource return `200 OK`. The two administrative clock operations return `200 OK` and carry no resource body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/membership-plans` | Create a membership plan | StaffManager |
| GET | `/membership-plans/{id}` | Get a plan | StaffManager, Member |
| POST | `/locations` | Create a location | StaffManager |
| GET | `/locations/{id}` | Get a location (incl. current occupancy) | StaffManager, Member |
| POST | `/members` | Register a member and the first dues invoice | StaffManager |
| GET | `/members/{id}` | Get a member | StaffManager, Member |
| GET | `/members` | List members | StaffManager |
| POST | `/members/{id}/activate` | Activate a pending member | StaffManager |
| POST | `/members/{id}/freeze` | Freeze an active membership | StaffManager |
| POST | `/members/{id}/unfreeze` | Resume a frozen membership | StaffManager |
| POST | `/members/{id}/cancel` | Cancel a membership and settle | StaffManager, Member |
| POST | `/class-sessions` | Schedule a class session | StaffManager |
| GET | `/class-sessions/{id}` | Get a class session | StaffManager, Member |
| GET | `/class-sessions` | List class sessions | StaffManager, Member |
| POST | `/class-sessions/{id}/cancel` | Cancel a scheduled session | StaffManager |
| POST | `/class-sessions/{id}/complete` | Complete a session after it ends | StaffManager |
| POST | `/bookings` | Book a class (BOOKED or WAITLISTED) | StaffManager, Member |
| GET | `/bookings/{id}` | Get a booking | StaffManager, Member |
| GET | `/bookings` | List bookings | StaffManager, Member |
| POST | `/bookings/{id}/cancel` | Cancel a booking | StaffManager, Member |
| POST | `/bookings/{id}/attend` | Mark a booking attended | StaffManager |
| POST | `/pt-packages` | Purchase a PT package | StaffManager, Member |
| GET | `/pt-packages/{id}` | Get a PT package | StaffManager, Member |
| GET | `/pt-packages` | List PT packages | StaffManager, Member |
| POST | `/pt-sessions` | Schedule a PT session | StaffManager, Member |
| GET | `/pt-sessions/{id}` | Get a PT session | StaffManager, Member |
| GET | `/pt-sessions` | List PT sessions | StaffManager, Member |
| POST | `/pt-sessions/{id}/complete` | Complete a PT session | StaffManager |
| POST | `/pt-sessions/{id}/no-show` | Mark a PT session no-show | StaffManager |
| POST | `/pt-sessions/{id}/cancel` | Cancel a PT session outside the cutoff | StaffManager, Member |
| POST | `/dues-invoices` | Post a recurring dues invoice | StaffManager |
| GET | `/dues-invoices/{id}` | Get a dues invoice | StaffManager, Member |
| GET | `/dues-invoices` | List dues invoices | StaffManager, Member |
| POST | `/dues-invoices/{id}/pay` | Pay an open invoice | StaffManager, Member |
| POST | `/dues-invoices/{id}/void` | Void an open invoice | StaffManager |
| POST | `/guest-passes` | Issue a guest pass | StaffManager, Member |
| GET | `/guest-passes/{id}` | Get a guest pass | StaffManager, Member |
| GET | `/guest-passes` | List guest passes | StaffManager, Member |
| POST | `/guest-passes/{id}/revoke` | Revoke an issued guest pass | StaffManager |
| POST | `/check-ins` | Turnstile entry (member or guest) | StaffManager |
| GET | `/check-ins/{id}` | Get a check-in | StaffManager |
| GET | `/check-ins` | List check-ins | StaffManager |
| POST | `/check-ins/{id}/checkout` | Close an open check-in | StaffManager |
| POST | `/_clock/set_current_utc` | Set the server clock | StaffManager |
| POST | `/_clock/advance_dues` | Run the time-driven sweep | StaffManager |

The list endpoints accept the following optional query parameters in addition to `limit` and `offset`: members may be filtered by `plan_id`, `home_location_id`, `membership_status`, and `dues_status`; class sessions by `location_id` and `status`; bookings by `session_id`, `member_id`, and `status`; PT packages by `member_id` and `status`; PT sessions by `package_id` and `status`; dues invoices by `member_id` and `status`; guest passes by `member_id`, `location_id`, and `status`; and check-ins by `location_id`, `member_id`, `guest_pass_id`, and `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_PACKAGE_VERSION` | 412 |
| `ERR_ACCESS_DENIED_SUSPENDED` | 403 |
| `ERR_FREEZE_BLOCKED_BY_DUES` | 409 |
| `ERR_FREEZE_CAP_EXCEEDED` | 409 |
| `ERR_MEMBER_NOT_BOOKABLE` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_BOOKING_TIME_OVERLAP` | 409 |
| `ERR_PT_TIME_OVERLAP` | 409 |
| `ERR_NO_CLASS_CREDITS` | 402 |
| `ERR_NO_PT_SESSIONS` | 402 |
| `ERR_NO_GUEST_PASSES` | 402 |
| `ERR_PT_LATE_CANCEL` | 409 |
| `ERR_GUEST_PASS_EXPIRED` | 409 |
| `ERR_OCCUPANCY_FULL` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_PLAN_ARCHIVED` | 409 |
| `ERR_ACTIVATION_NOT_PAID` | 409 |
