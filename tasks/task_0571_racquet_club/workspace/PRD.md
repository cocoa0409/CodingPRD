# Racquet Club API — Product Requirements Document

## 1. Introduction

The Racquet Club API is the operational backbone of a combined tennis and pickleball facility. It unifies what are, in most clubs, a dozen loosely-coupled spreadsheets and desk binders: the indoor and outdoor court inventory, the reservation calendar, the recurring membership billing engine, the coaching-pro lesson schedule, league and ladder standings, tournament brackets, and the pro-shop stringing bench. Every one of these workflows touches money — a booked court hour, a guest fee, a lesson charge, a stringing invoice, a tournament entry — and the club's central promise to its members is that every cent is accounted for exactly once, reversed cleanly when a booking is undone, and never double-charged when a court goes down for repairs.

The system is built for three kinds of users working against a shared, immediate-consistency data store: members who book and manage their own play, coaching pros who run their own lessons and clinics, and the front-desk operators who own the club's inventory, billing, and competition machinery. Because so many of the rules are time-sensitive — peak-hour surcharges, advance-booking windows, no-show grace periods, monthly billing cycles — the API is driven by an explicit logical clock rather than wall time, so that every temporal rule is deterministic and testable. This document specifies the complete contract: the resource model, the state machines that govern each entity's lifecycle, the pricing and proration calculations, the layered validation order, and the full endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles: `Member`, `Pro`, and `FrontDesk`. When a well-authenticated caller attempts an operation their role is not permitted to perform — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles differ in how `X-User-ID` binds to the data. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare that resource's member foreign key (its `member_id`) to `X-User-ID`. A member may therefore book, check in, cancel, and reschedule only their own reservations, enroll only themselves, register only themselves as a competitor, request stringing only for themselves, and freeze, unfreeze, change, or cancel only their own subscription. When `X-User-Role` is `Pro`, `X-User-ID` is the `id` of the acting `Pro`; ownership checks on a lesson compare the lesson's `pro_id` to `X-User-ID`, so a pro schedules, confirms, completes, and cancels only their own lessons. When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. `FrontDesk` holds superset operational authority and may act on behalf of any member or pro.

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

### 2.3. Pagination, Listing, and Filtering

Every collection endpoint is paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no less than 1 and no greater than 100. The `offset` parameter defaults to 0 and has a minimum of 0. List results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full number of matching records before the page window is applied and `has_more` indicates whether records remain beyond the current page.

Collections also accept domain filters in addition to `limit` and `offset`. Courts may be filtered by `status` and `location_type`. Membership plans may be filtered by `tier`. Members may be filtered by `status` and `email`. Subscriptions may be filtered by `member_id`, `plan_id`, and `status`. Reservations may be filtered by `court_id`, `member_id`, and `status`. Lessons may be filtered by `pro_id`, `court_id`, and `status`. Enrollments may be filtered by `lesson_id`, `member_id`, and `status`. Competitions may be filtered by `status` and `format`. Participants may be filtered by `competition_id`, `member_id`, and `status`. Stringing jobs may be filtered by `member_id` and `status`.

### 2.4. Resource Identity, Versioning, and Addressing

Every resource carries a server-minted `id` — a UUID that serves as identity only and never encodes a type prefix. Every entity in this system also carries the full set of common audit fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version`. The `created_at` timestamp is fixed at creation. On every mutation of a resource, its `updated_at` is refreshed to the current logical-clock instant and its `version` is incremented by one. A read (GET) never advances `version`.

Single resources are addressed by their identifier in the path: a court by `court_id`, a plan by `plan_id`, a member by `member_id`, a subscription by `subscription_id`, a reservation by `reservation_id`, a pro by `pro_id`, a lesson by `lesson_id`, an enrollment by `enrollment_id`, a competition by `competition_id`, a participant by `participant_id`, and a stringing job by `job_id`. Path identifiers are validated from left to right; the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any later identifier or body reference is examined. Foreign-key identifiers supplied in a request body are likewise required to resolve to existing resources, again under `ERR_NOT_FOUND`.

### 2.5. The Logical Clock and Temporal Windows

Because the club's rules turn on time — advance-booking limits, peak windows, check-in and no-show deadlines, and 30-day billing cycles — the API reads all "current time" from an explicit server logical clock rather than from wall time. At startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time; every deadline and window rule reads this clock. A front-desk operator may advance or set the clock by supplying a `to_iso8601` instant to the clock-setting capability, which repositions the logical clock to that instant. All temporal comparisons described in §3 — whether a reservation lies in the future, whether a check-in falls within its window, whether a no-show grace period has elapsed, whether a billing period has closed — are evaluated against this clock.

### 2.6. Monetary Precision and the Member Ledger

Every monetary amount in the system is an integer number of cents; there are no fractional-cent balances stored anywhere. Where a calculation produces a fractional intermediate — the daily proration rate, or a percentage surcharge — the rounding rule is stated explicitly at the point of calculation in §3: surcharge terms are rounded up to the next whole cent, and daily proration amounts are rounded half-up to the nearest cent on a per-day basis before summation. Each member carries a running ledger balance in `account_balance_cents`, where a positive value represents money owed by the member to the club. Charges add to this balance and refunds or reversals subtract from it; the balance is the sum of all posted charges minus the sum of all posted refunds and payments. The concrete events that post to or reverse against the ledger are described in the workflow narratives of §3.

### 2.7. Optimistic Concurrency Control

Two operations are guarded by optimistic concurrency control (OCC) because they are legitimately repeatable and therefore cannot be protected by a state precondition alone. Changing the plan on a subscription requires the request to carry `expected_subscription_version`, which must equal the target subscription's current `version`. Because a member may move through plans repeatably (for example `BASIC` to `PREMIER` to `ELITE`), a second change carrying a stale version is not blocked by any state check — only by the OCC check. A prior plan change or a renewal reconciliation silently advances the subscription's `version`, so if the version the client last observed no longer matches, the change is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, rescheduling a reservation requires `expected_reservation_version` to equal the reservation's current `version`; because a booked reservation may be moved more than once, a second reschedule carrying a stale version is rejected purely by the OCC check with `ERR_STALE_VERSION` (HTTP 412), never by a state precondition. Endpoints outside these two do not accept a version field.

### 2.8. Layered Validation Order

Every request is evaluated through an ordered chain of ten validation layers. Lower-numbered layers are evaluated first, and the first layer that fails determines the response — a failure at an earlier layer masks any condition a later layer would have raised. The layers are:

1. **Authentication** — headers present and `X-User-Role` known; otherwise `ERR_UNAUTHENTICATED` (401). Applies to all requests.
2. **Authorization** — the acting role is permitted for the operation, and an ownership-scoped role acting on its own resource matches `X-User-ID`; otherwise `ERR_UNAUTHORIZED` (403). Applies to all requests.
3. **Existence** — every path identifier resolves (left to right) and every body foreign key resolves; otherwise `ERR_NOT_FOUND` (404). Applies to all requests.
4. **Body well-formedness** — required fields present, types and enums valid, `end_time` strictly greater than `start_time`, a `draw_size` (where supplied) a power of two; otherwise `ERR_VALIDATION` (400). Applies to all write requests.
5. **Optimistic concurrency** — `expected_subscription_version` or `expected_reservation_version` matches the parent's current `version`; otherwise `ERR_STALE_VERSION` (412). Applies to plan change and reschedule.
6. **State precondition** — the target resource is in a state that admits the requested transition; otherwise `ERR_INVALID_STATE` (409). Applies to all state-transition operations.
7. **Cross-entity referential state** — booking requires the court to be `AVAILABLE` and the booking member to be `ACTIVE`; enrolling requires the member to be `ACTIVE` and their subscription to be `ACTIVE`; credit spend requires an `ACTIVE` subscription. Failures raise `ERR_COURT_NOT_AVAILABLE`, `ERR_MEMBER_SUSPENDED`, or `ERR_SUBSCRIPTION_NOT_ACTIVE` as appropriate (all 409). Applies to booking a reservation and creating an enrollment.
8. **Temporal interval** — the booking or lesson interval satisfies the future, advance-window, overlap, buffer, and clock-window rules; failures raise `ERR_BOOKING_IN_PAST`, `ERR_BOOKING_WINDOW_EXCEEDED`, `ERR_COURT_TIME_CONFLICT`, `ERR_PRO_TIME_CONFLICT`, `ERR_LESSON_COURT_CONFLICT`, `ERR_CHECKIN_WINDOW`, or `ERR_NO_SHOW_TOO_EARLY` (all 409). Applies to booking a reservation, rescheduling, scheduling a lesson, check-in, and mark-no-show.
9. **Uniqueness and configuration** — no duplicate reservation, enrollment, or participant; a manual freeze stays within the plan's freeze limit; a member holds no other non-`CANCELLED` subscription; failures raise `ERR_DUPLICATE_RESERVATION`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_DUPLICATE_PARTICIPANT`, `ERR_FREEZE_LIMIT_REACHED`, or `ERR_SUBSCRIPTION_EXISTS` (all 409). Applies to booking a reservation, creating an enrollment, registering a participant, freezing a subscription, and creating a subscription.
10. **Fiscal ceiling** — the member's outstanding balance is within the allowed maximum; otherwise `ERR_BALANCE_LIMIT_EXCEEDED` (402). Applies to booking a reservation.

### 2.9. Cascading Effects and Compensating Reversals

Several operations mutate more than one entity in a single call, and the club depends on those cascades being exact. Two principles govern them. First, whenever a cascade transitions a child resource, it also bumps that child's `version` and refreshes its `updated_at`, exactly as a direct mutation would. Second, the ledger and the credit pool obey compensation invariants: whenever a reservation that consumed court-time credits or posted a provisional charge is undone by cancellation, its consumed credits are restored to the subscription and its provisional charge is reversed from the member's `account_balance_cents`, so the club's books return precisely to where they stood before the booking. The specific cascades — a court going into maintenance sweeping its future bookings, a no-show driving a member to suspension and freezing their subscription, a lesson cancellation voiding its enrollments — are detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Court Inventory and Availability

The club's playable surface is modeled as a set of courts, each created by the front desk with a `name`, a `surface` of `HARD`, `CLAY`, or `GRASS`, a `location_type` of `INDOOR` or `OUTDOOR`, an `hourly_rate_cents` cash rate (which must be zero or greater), and two ball-machine attributes: `has_ball_machine`, indicating whether a machine is fitted (default false), and `ball_machine_fee_cents`, the flat fee charged per reservation that uses the machine (default 0, zero or greater). A new court opens in `AVAILABLE` status.

A court's lifecycle is cyclic between `AVAILABLE` and `MAINTENANCE`, with a terminal `RETIRED` state. Taking an `AVAILABLE` court out of service moves it `AVAILABLE → MAINTENANCE`; attempting this on a court not currently `AVAILABLE` is rejected with `ERR_INVALID_STATE`. Going into maintenance triggers a two-hop cascade. In the first hop, every reservation on that court that is still in `BOOKED` status and whose `start_time` is at or after the current clock time is transitioned `BOOKED → CANCELLED`. In the second hop, each such cancellation restores that reservation's `credits_used` to the owning subscription's `court_credits_remaining` and reverses its `provisional_fee_cents` from the member's `account_balance_cents`, following the compensation invariant. Returning a court to service moves it `MAINTENANCE → AVAILABLE`, and requires the court to currently be in `MAINTENANCE`. A court may be retired from either `AVAILABLE` or `MAINTENANCE`, moving it to `RETIRED` and making it permanently unbookable; retirement is refused with `ERR_INVALID_STATE` while any reservation on the court remains in `BOOKED` or `CHECKED_IN` status with a `start_time` at or after the current clock time.

### 3.2. Membership Plans, Subscriptions, and Recurring Billing

A membership plan is a pricing template created by the front desk. It carries a `name`, a `tier` of `BASIC`, `PREMIER`, or `ELITE`, a recurring `monthly_fee_cents`, a `monthly_court_credits` grant (where one credit equals one booked hour), a `peak_access` flag governing whether credits may be spent on peak-hour reservations, a per-guest `guest_fee_cents`, and a `freeze_limit` capping how many freezes a subscription may perform over its lifetime. All fee and credit fields are zero or greater.

A member is created by the front desk with a `full_name` and a unique `email`, opening in `ACTIVE` status with `no_show_strikes` at 0 and `account_balance_cents` at 0. A coaching pro is likewise created by the front desk with a `full_name` and an `hourly_rate_cents` coaching rate, and is system-initialized to `ACTIVE`.

A subscription binds a member to a plan. When the front desk creates one by supplying a `member_id` and a `plan_id`, the subscription opens in `ACTIVE` status with `court_credits_remaining` set to the plan's `monthly_court_credits`, `estimated_period_fee_cents` set to the plan's `monthly_fee_cents`, `freeze_count` at 0, and a billing period whose `current_period_start` is the current clock instant and whose `current_period_end` is exactly 30 days later (the period is half-open, inclusive of the start and exclusive of the end). A member may hold only one non-`CANCELLED` subscription at a time; attempting to create a second is rejected with `ERR_SUBSCRIPTION_EXISTS`. The `estimated_period_fee_cents` is a forward-looking projection of the current period's fee assuming no freeze, and at period open it equals the plan's `monthly_fee_cents`.

The subscription lifecycle is cyclic between `ACTIVE` and `FROZEN`, with an `ACTIVE → ACTIVE` renewal self-loop and a terminal `CANCELLED` state. **Freezing** moves an `ACTIVE` subscription to `FROZEN`; a manual freeze is permitted only while the subscription is `ACTIVE` and its `freeze_count` is strictly less than the plan's `freeze_limit`, and a manual freeze that would reach or exceed the limit is rejected with `ERR_FREEZE_LIMIT_REACHED`. A successful manual freeze increments `freeze_count` by one, stamps `frozen_at` to the current clock instant, and pauses credit accrual so that days spent frozen do not count as active days for billing. **Unfreezing** moves a `FROZEN` subscription back to `ACTIVE` and clears `frozen_at` to null.

**Changing the plan** is an `ACTIVE → ACTIVE` self-transition available to the member or the front desk. It requires the subscription to be `ACTIVE` and, per §2.7, requires `expected_subscription_version` to match the subscription's current `version`. On success it sets `plan_id` to the supplied new plan, recomputes `estimated_period_fee_cents` to the new plan's `monthly_fee_cents`, and increments the subscription's `version` by one; notably, `court_credits_remaining` is deliberately left unchanged by a plan change — credits are neither topped up nor trimmed to the new plan's grant.

**Renewal** closes and reopens the billing period and may run from either `ACTIVE` or `FROZEN`; it is refused with `ERR_RENEW_NOT_DUE` unless the current clock time has reached `current_period_end`. On renewal the subscription is charged the chronological actual period fee (defined below), which is posted to the member's `account_balance_cents`; then `court_credits_remaining` is reset to the plan's `monthly_court_credits`, `estimated_period_fee_cents` is reset to the plan's `monthly_fee_cents`, the period is advanced by 30 days, `frozen_at` is cleared, the status is set to `ACTIVE`, and the subscription's `version` is incremented by one. **Cancellation** may run from either `ACTIVE` or `FROZEN` and moves the subscription to the terminal `CANCELLED` state, setting `court_credits_remaining` to 0; it is refused only if the subscription is already `CANCELLED`.

The **chronological period cost** is computed by proration. Each period spans exactly 30 days. The daily rate is the plan's `monthly_fee_cents` divided by 30, held as an exact fractional-cent value and not rounded at this stage. A calendar day within the half-open span from `current_period_start` to `current_period_end` counts as an active day when the subscription is in `ACTIVE` status as of 00:00:00Z at the start of that day; a day that is on or after `frozen_at` while the subscription is still `FROZEN` is not active. The prorated charge is obtained by rounding the daily rate to the nearest cent, half-up, once for each active day, and then summing those per-day rounded amounts. This per-day-rounded-then-summed order is required and is not the same as multiplying the daily rate by the active-day count and rounding a single time. The forward-looking figure surfaced in `estimated_period_fee_cents` simply equals the plan's `monthly_fee_cents` and ignores in-period freezes; the chronological actual charged at renewal is always less than or equal to that forward figure, and the two diverge exactly when a freeze occurred mid-period. The difference between them is the savings the freeze produced.

The value in `court_credits_remaining` is always reconcilable as the plan's `monthly_court_credits` minus the sum of `credits_used` across the member's reservations that are in `BOOKED`, `CHECKED_IN`, `COMPLETED`, or `NO_SHOW` status; it is never allowed to fall below zero. Cancelling a `BOOKED` reservation restores its `credits_used`, whereas a reservation marked as a no-show retains its deduction.

### 3.3. Court Reservations, Pricing, and Rescheduling

Booking is the club's highest-traffic workflow. A member (or the front desk on their behalf) books a court by supplying a `court_id`, a `member_id`, a `start_time`, and an `end_time`; the interval is half-open, covering the start and excluding the end. Two optional inputs shape the charge: `guest_count`, the number of guests declared at booking (default 0, zero or greater), and `uses_ball_machine`, declaring whether the court's ball machine will be used (default false). A new reservation opens in `BOOKED` status.

Before a booking is accepted it must clear the referential, temporal, uniqueness, and fiscal layers of §2.8. The court must be `AVAILABLE`, else `ERR_COURT_NOT_AVAILABLE`; the booking member must be `ACTIVE`, else `ERR_MEMBER_SUSPENDED`. The `start_time` must be strictly after the current clock, else `ERR_BOOKING_IN_PAST`, and no more than 14 days ahead of the current clock, else `ERR_BOOKING_WINDOW_EXCEEDED`. The interval must not half-open-overlap any other non-terminal reservation on the same court, else `ERR_COURT_TIME_CONFLICT`. No other non-terminal reservation may already exist for the same member, court, and `start_time`, else `ERR_DUPLICATE_RESERVATION`. Finally, the member's `account_balance_cents` must not exceed 20000 cents (200 dollars) at the moment of booking; a balance above that ceiling refuses the booking with `ERR_BALANCE_LIMIT_EXCEEDED`.

The **reservation charge** is computed at booking (the provisional variant) and again at completion (the final variant), from the reservation, its court, the booking member, and the member's non-`CANCELLED` subscription and that subscription's plan. First, the billed duration is the whole number of hours in the interval: take the length from `start_time` to `end_time` in minutes, divide by 60 minutes per credit-hour, and round up to the next whole hour, so a 90-minute booking bills as two hours. The reservation is a peak booking, recorded in `is_peak`, when the UTC hour of its `start_time` is at or after 17:00 and before 21:00. The base court charge is the court's `hourly_rate_cents` multiplied by the billed whole-hour duration. For a peak booking, a surcharge of 25 percent of that base court charge is computed on the pre-surcharge base, rounded up to the next whole cent, and added to the base.

The system then decides between credit settlement and cash. The reservation is settled with credits when the member has a non-`CANCELLED` subscription, that subscription is `ACTIVE`, its `court_credits_remaining` is at least the billed whole-hour duration, and either the booking is not a peak booking or the plan grants `peak_access`. When credits settle the reservation, `credits_used` is set to the billed whole-hour duration and the court portion of the charge is zero. Otherwise `credits_used` is zero and the court portion equals the base court charge including any peak surcharge. On top of the court portion, a guest charge equal to the effective guest count multiplied by the plan's `guest_fee_cents` is added — the effective guest count is `guest_count` for the provisional charge and `actual_guest_count` for the final charge. A ball-machine charge equal to the court's `ball_machine_fee_cents` applies only when the reservation's `uses_ball_machine` is true and the court's `has_ball_machine` is true; otherwise it is zero. The total fee is the sum of the court charge, the guest charge, and the ball-machine charge. At booking, this provisional total is stored in `provisional_fee_cents`, posted to the member's `account_balance_cents`, and any `credits_used` are deducted from the subscription.

Once a reservation is under way it is **checked in**, moving `BOOKED → CHECKED_IN`. Check-in is available to the member or the front desk, requires the reservation to be `BOOKED`, and must occur while the current clock is within the window from 30 minutes before `start_time` up to (but not including) `end_time`; outside that window it is rejected with `ERR_CHECKIN_WINDOW`. Check-in records `actual_guest_count`, which defaults to the declared `guest_count` when omitted. **Completion** then moves `CHECKED_IN → COMPLETED` and is a front-desk operation requiring the reservation to be `CHECKED_IN`. At completion the final charge is recomputed using `actual_guest_count`, stored in `final_fee_cents`, and only the delta — the final fee minus the already-posted `provisional_fee_cents` — is posted to the member's `account_balance_cents`. This delta is nonzero exactly when `actual_guest_count` differs from the declared `guest_count`.

A `BOOKED` reservation may instead be **cancelled** (moving `BOOKED → CANCELLED`), which restores its `credits_used` to `court_credits_remaining` and reverses its `provisional_fee_cents` from the member's `account_balance_cents`. The same `BOOKED → CANCELLED` transition is what the court-maintenance cascade drives. **Rescheduling** a reservation moves it to a new interval: the caller supplies a new `start_time`, a new `end_time`, and `expected_reservation_version`. Per §2.7 the version must match, and the new interval is re-validated against the future, advance-window, and court-overlap rules just as at booking; on success the provisional charge is recomputed and the reservation's `version` is incremented by one.

### 3.4. No-Shows, Strikes, and Automatic Suspension

When a booked player fails to appear, the front desk **marks a no-show**, moving the reservation `BOOKED → NO_SHOW`. This is permitted only while the reservation is `BOOKED` and only once the current clock has reached `start_time` plus a 15-minute grace period; an attempt before that instant is rejected with `ERR_NO_SHOW_TOO_EARLY`. A no-show is a penalty state: the `provisional_fee_cents` already posted is retained with no refund, and `credits_used` is not restored to the subscription. Marking the no-show increments the member's `no_show_strikes` by one.

The no-show strike count drives automatic suspension. When `no_show_strikes` reaches at least 3, the member is automatically transitioned `ACTIVE → SUSPENDED` (two strikes do not suspend; the third does). A member may also be suspended directly by the front desk. Either way, entering `SUSPENDED` triggers a further cascade: if the member owns a non-`CANCELLED` subscription that is currently `ACTIVE`, that subscription is transitioned `ACTIVE → FROZEN` and its `frozen_at` is stamped to the current clock instant. This system-driven freeze is not a manual freeze and does not consume the plan's `freeze_limit` nor increment `freeze_count`. **Reinstatement** by the front desk moves the member `SUSPENDED → ACTIVE` and resets `no_show_strikes` to 0; a reinstated member's subscription remains `FROZEN` until it is explicitly unfrozen.

### 3.5. Lessons, Clinics, and Enrollment

Coaching is delivered through lessons. A pro (or the front desk) schedules one by supplying a `pro_id`, a `court_id`, a `kind` of `PRIVATE` or `CLINIC`, a `start_time`, an `end_time`, a `price_cents` charge per enrolled member, and an optional `capacity` (default 1, at least 1). A `PRIVATE` lesson holds a single seat; a `CLINIC` may hold more. A new lesson opens in `SCHEDULED` status. Scheduling re-uses the temporal layer: the lesson occupies its court, so its interval must not half-open-overlap another booking on that court, else `ERR_LESSON_COURT_CONFLICT`; and the assigned pro must have a clear schedule — the lesson interval must be separated from the pro's other non-cancelled lessons by at least a 15-minute buffer and must not overlap them, else `ERR_PRO_TIME_CONFLICT`.

Members join a lesson through enrollment. Creating an enrollment supplies a `lesson_id` and a `member_id`; the enrolling member must be `ACTIVE` (else `ERR_MEMBER_SUSPENDED`) and must hold an `ACTIVE` subscription — a member with no subscription at all is rejected with `ERR_SUBSCRIPTION_REQUIRED`, and one whose subscription exists but is not `ACTIVE` with `ERR_SUBSCRIPTION_NOT_ACTIVE`. A member may not hold a second non-`CANCELLED` enrollment on the same lesson, else `ERR_DUPLICATE_ENROLLMENT`. Seat assignment reads the lesson's `enrolled_count`, defined as the number of enrollments on the lesson currently in `ENROLLED` status. When a new enrollment is created, if `enrolled_count` is strictly less than the lesson's `capacity` the enrollment is admitted directly as `ENROLLED`; once `enrolled_count` equals `capacity`, further enrollments are placed as `WAITLISTED`. Only `ENROLLED` seats count against capacity; `WAITLISTED` seats do not.

Cancelling an enrollment moves it to the terminal `CANCELLED` state. If the cancelled seat was an `ENROLLED` seat and a waitlist exists, the system promotes the earliest `WAITLISTED` enrollment — the one with the earliest `created_at` in ascending order — from `WAITLISTED → ENROLLED`, and the lesson's `enrolled_count` is recomputed. This promotion is the enrollment state machine's re-entry path and fires whenever an `ENROLLED` seat is freed while a waitlisted member is waiting.

A lesson advances from `SCHEDULED` to `CONFIRMED` when a pro or the front desk **confirms** it; confirmation requires the lesson to be `SCHEDULED` and to have an `enrolled_count` of at least 1. **Completion** moves `CONFIRMED → COMPLETED` and, at that moment, posts the lesson's `price_cents` to the `account_balance_cents` of every member whose enrollment is in `ENROLLED` status. A lesson may be **cancelled** from either `SCHEDULED` or `CONFIRMED`, moving it to `CANCELLED`; cancellation transitions every enrollment on the lesson that is `ENROLLED` or `WAITLISTED` to `CANCELLED` and posts no charge.

### 3.6. Competitions: Leagues, Ladders, and Tournaments

The club runs three kinds of competition, distinguished by a `format` of `ROUND_ROBIN`, `LADDER`, or `TOURNAMENT`. The front desk creates one with a `name`, a `format`, an optional `entry_fee_cents` charged to each entrant (default 0, zero or greater), and — for a tournament only — a `draw_size` that must be a power of two (it is null for the other formats). A new competition opens in `REGISTRATION` status and advances linearly `REGISTRATION → IN_PROGRESS → COMPLETED`.

Members register as participants by supplying a `competition_id`, a `member_id`, and, for a tournament, an optional `seed` (1 being the top seed; ignored for non-tournament formats). Registration is accepted only while the competition is in `REGISTRATION` status, else `ERR_COMPETITION_NOT_OPEN`, and a member may not register twice in the same competition, else `ERR_DUPLICATE_PARTICIPANT`. On registration the participant opens in `ACTIVE` standing and the competition's `entry_fee_cents` is posted to the member's `account_balance_cents`. Each participant also tracks `bracket_slot`, `ladder_rank`, `wins`, `losses`, and `points`, all system-maintained and initialized as appropriate.

**Starting** a competition moves it `REGISTRATION → IN_PROGRESS`. For a tournament, the start seeds the bracket: the competition's `draw_size` must be a power of two and must equal the count of `ACTIVE` participants, otherwise the start is rejected with `ERR_INVALID_DRAW_SIZE`. Seeding orders the active participants by `seed` ascending, treating a null seed as ranking after all explicit seeds, and breaks ties by `created_at` ascending (never by `id`); it then assigns `bracket_slot` values 1 through `draw_size` in that order. The round-one pairing places the participant in bracket slot `i` against the participant in slot `draw_size + 1 − i`. For a ladder, the start instead assigns each participant a `ladder_rank` by `created_at` ascending.

**Reporting** a match result records the outcome and updates standings. The report identifies the two contestants as `player1_participant_id` and `player2_participant_id`, the victor as `winner_participant_id`, and optionally the `round`. The winner's `wins` is incremented by one and the loser's `losses` by one. In a round-robin, the winner's `points` gains 3 points for the win (a loss is worth 0). In a tournament, the losing participant's standing is set to `ELIMINATED`. In a ladder, when the winner's `ladder_rank` is a larger number than the loser's — that is, a lower-positioned player has beaten a higher-positioned one — the winner takes the loser's position: the winner's `ladder_rank` becomes the loser's former rank, and every participant currently holding a rank from the loser's rank up to but not including the winner's former rank shifts down by exactly one position. **Closing** a competition moves it `IN_PROGRESS → COMPLETED`.

### 3.7. The Pro-Shop Stringing Bench

The pro shop takes in racquets for stringing. A member (or the front desk) opens a stringing job by supplying a `member_id`, a free-text `racquet_label`, a requested `string_type`, a `tension` in pounds (at least 1), and a `price_cents` charge (zero or greater). The job opens in `RECEIVED` status and its `price_cents` is posted to the member's `account_balance_cents` at intake.

A stringing job advances linearly through its workflow: each advance step moves it one stage along `RECEIVED → IN_PROGRESS → READY → PICKED_UP`, and each step requires the job to be in the immediately preceding state (an advance from any other state is rejected with `ERR_INVALID_STATE`). Before pickup, the job may be **cancelled** from `RECEIVED`, `IN_PROGRESS`, or `READY`, moving it to the terminal `CANCELLED` state; cancellation reverses the job's `price_cents` from the member's `account_balance_cents`. Once a job has been picked up it is terminal and can no longer be advanced or cancelled.

## 4. Endpoint Definitions

All endpoints are mounted under the `/racquet` prefix. Endpoints that create a new resource respond with HTTP 201 and return the created resource; endpoints that modify or transition an existing resource respond with HTTP 200 and return the updated resource; read endpoints respond with HTTP 200. Error responses carry the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/racquet/_clock/set_current_utc` | Set the server logical clock | FrontDesk |
| POST | `/racquet/courts` | Create a court | FrontDesk |
| GET | `/racquet/courts/{court_id}` | Get a court | Member, Pro, FrontDesk |
| GET | `/racquet/courts` | List courts | Member, Pro, FrontDesk |
| POST | `/racquet/courts/{court_id}/maintenance` | Take a court out of service | FrontDesk |
| POST | `/racquet/courts/{court_id}/reopen` | Return a court to service | FrontDesk |
| POST | `/racquet/courts/{court_id}/retire` | Permanently retire a court | FrontDesk |
| POST | `/racquet/membership-plans` | Create a membership plan | FrontDesk |
| GET | `/racquet/membership-plans/{plan_id}` | Get a membership plan | Member, Pro, FrontDesk |
| GET | `/racquet/membership-plans` | List membership plans | Member, Pro, FrontDesk |
| POST | `/racquet/members` | Create a member | FrontDesk |
| GET | `/racquet/members/{member_id}` | Get a member | Member, Pro, FrontDesk |
| GET | `/racquet/members` | List members | FrontDesk |
| POST | `/racquet/members/{member_id}/suspend` | Suspend a member | FrontDesk |
| POST | `/racquet/members/{member_id}/reinstate` | Reinstate a suspended member | FrontDesk |
| POST | `/racquet/subscriptions` | Create a subscription for a member on a plan | FrontDesk |
| GET | `/racquet/subscriptions/{subscription_id}` | Get a subscription | Member, Pro, FrontDesk |
| GET | `/racquet/subscriptions` | List/filter subscriptions | Member, Pro, FrontDesk |
| POST | `/racquet/subscriptions/{subscription_id}/freeze` | Freeze a subscription | Member, FrontDesk |
| POST | `/racquet/subscriptions/{subscription_id}/unfreeze` | Unfreeze a subscription | Member, FrontDesk |
| POST | `/racquet/subscriptions/{subscription_id}/change-plan` | Change the plan on a subscription (OCC-guarded) | Member, FrontDesk |
| POST | `/racquet/subscriptions/{subscription_id}/renew` | Close the current period and renew | FrontDesk |
| POST | `/racquet/subscriptions/{subscription_id}/cancel` | Cancel a subscription | Member, FrontDesk |
| POST | `/racquet/reservations` | Book a court reservation | Member, FrontDesk |
| GET | `/racquet/reservations/{reservation_id}` | Get a reservation | Member, Pro, FrontDesk |
| GET | `/racquet/reservations` | List/filter reservations | Member, Pro, FrontDesk |
| POST | `/racquet/reservations/{reservation_id}/check-in` | Check in a reservation | Member, FrontDesk |
| POST | `/racquet/reservations/{reservation_id}/complete` | Complete a reservation and settle the final charge | FrontDesk |
| POST | `/racquet/reservations/{reservation_id}/cancel` | Cancel a reservation | Member, FrontDesk |
| POST | `/racquet/reservations/{reservation_id}/reschedule` | Move a reservation to a new interval (OCC-guarded) | Member, FrontDesk |
| POST | `/racquet/reservations/{reservation_id}/mark-no-show` | Mark a booked reservation as a no-show after the grace period | FrontDesk |
| POST | `/racquet/pros` | Create a coaching pro | FrontDesk |
| GET | `/racquet/pros/{pro_id}` | Get a pro | Member, Pro, FrontDesk |
| GET | `/racquet/pros` | List pros | Member, Pro, FrontDesk |
| POST | `/racquet/lessons` | Schedule a private lesson or group clinic | Pro, FrontDesk |
| GET | `/racquet/lessons/{lesson_id}` | Get a lesson | Member, Pro, FrontDesk |
| GET | `/racquet/lessons` | List/filter lessons | Member, Pro, FrontDesk |
| POST | `/racquet/lessons/{lesson_id}/confirm` | Confirm a lesson | Pro, FrontDesk |
| POST | `/racquet/lessons/{lesson_id}/complete` | Complete a lesson and charge enrolled members | Pro, FrontDesk |
| POST | `/racquet/lessons/{lesson_id}/cancel` | Cancel a lesson | Pro, FrontDesk |
| POST | `/racquet/enrollments` | Enroll a member in a clinic/lesson | Member, FrontDesk |
| GET | `/racquet/enrollments/{enrollment_id}` | Get an enrollment | Member, Pro, FrontDesk |
| GET | `/racquet/enrollments` | List/filter enrollments | Member, Pro, FrontDesk |
| POST | `/racquet/enrollments/{enrollment_id}/cancel` | Cancel an enrollment | Member, FrontDesk |
| POST | `/racquet/competitions` | Create a league, ladder, or tournament | FrontDesk |
| GET | `/racquet/competitions/{competition_id}` | Get a competition | Member, Pro, FrontDesk |
| GET | `/racquet/competitions` | List competitions | Member, Pro, FrontDesk |
| POST | `/racquet/competitions/{competition_id}/start` | Start a competition; for TOURNAMENT this seeds the bracket | FrontDesk |
| POST | `/racquet/competitions/{competition_id}/report` | Report a match result and update standings | FrontDesk |
| POST | `/racquet/competitions/{competition_id}/close` | Close a competition | FrontDesk |
| POST | `/racquet/participants` | Register a member into a competition | Member, FrontDesk |
| GET | `/racquet/participants/{participant_id}` | Get a participant | Member, Pro, FrontDesk |
| GET | `/racquet/participants` | List/filter participants | Member, Pro, FrontDesk |
| POST | `/racquet/stringing-jobs` | Intake a pro-shop stringing job | Member, FrontDesk |
| GET | `/racquet/stringing-jobs/{job_id}` | Get a stringing job | Member, Pro, FrontDesk |
| GET | `/racquet/stringing-jobs` | List/filter stringing jobs | Member, Pro, FrontDesk |
| POST | `/racquet/stringing-jobs/{job_id}/advance` | Advance a stringing job one workflow step | FrontDesk |
| POST | `/racquet/stringing-jobs/{job_id}/cancel` | Cancel a stringing job before pickup and refund | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_COURT_NOT_AVAILABLE | 409 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 409 |
| ERR_SUBSCRIPTION_REQUIRED | 409 |
| ERR_SUBSCRIPTION_EXISTS | 409 |
| ERR_BOOKING_IN_PAST | 409 |
| ERR_BOOKING_WINDOW_EXCEEDED | 409 |
| ERR_COURT_TIME_CONFLICT | 409 |
| ERR_PRO_TIME_CONFLICT | 409 |
| ERR_LESSON_COURT_CONFLICT | 409 |
| ERR_CHECKIN_WINDOW | 409 |
| ERR_NO_SHOW_TOO_EARLY | 409 |
| ERR_DUPLICATE_RESERVATION | 409 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
| ERR_DUPLICATE_PARTICIPANT | 409 |
| ERR_FREEZE_LIMIT_REACHED | 409 |
| ERR_COMPETITION_NOT_OPEN | 409 |
| ERR_INVALID_DRAW_SIZE | 409 |
| ERR_BALANCE_LIMIT_EXCEEDED | 402 |
| ERR_RENEW_NOT_DUE | 409 |
