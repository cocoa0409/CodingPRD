# Science Center & Planetarium API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the operational backbone of a modern science center and planetarium. The institution runs a dome and a theater on timed-entry schedules, teaches multi-day camps and single classes out of its classrooms, rents a private hall for birthdays and parties, sells memberships that carry reciprocal admission privileges at peer institutions, and cultivates a roster of donors and sponsors. Each of these lines of business has its own pricing logic, its own capacity ceiling, and its own lifecycle, yet they all draw on a shared pool of physical venues and a single membership program. The API described here is the system of record that holds these lines of business together.

Two cross-cutting concerns shape almost every workflow. The first is **time**: shows occupy a venue for a fixed window plus a cleaning buffer, holds expire if not confirmed, rentals must not double-book a hall, and memberships lapse a year after they are paid for. Because the benchmark must be reproducible, the system never reads the wall clock — it runs on a **logical clock** that an administrator advances explicitly, and deferred consequences (expiries, hold releases) are applied only when a sweep is run. The second concern is **capacity under contention**: two operators may both try to claim the last seat in a sold-out dome or the last open chair in a full camp, and the system must let exactly one of them win without silently overwriting the other. The sections that follow describe the entities, the state machines that govern them, the money calculations that price every transaction, and the validation order that keeps the whole thing consistent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that hold across every endpoint. Where a rule is specific to one workflow, it is deferred to Section 3.

### 2.1. User and Role-Based Access Control

Every request other than the unauthenticated health probe must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes eight peer roles, each owning a slice of the business: `FacilityAdmin`, `BoxOfficeOperator`, `GroupSalesAgent`, `MembershipClerk`, `ProgramCoordinator`, `EventsManager`, `DevelopmentOfficer`, and `AccessibilityCoordinator`. These roles are peers — none is a superuser, and the permission matrix in Section 4 enumerates exactly which role may invoke each operation.

Every one of these roles is an **opaque operator identity**. When `X-User-Role` names any of the eight roles, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`, and no resource in this system is "owned" by the user who created it. Authorization is therefore purely role-based: the matrix decides access, and the identifier behind `X-User-ID` plays no part in any ownership check.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no upper bound beyond the size of the collection. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp, `created_at`, in ascending order. Each list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system share a common set of server-managed fields. Their `id` is a server-minted UUID, carrying no type prefix. Their `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. Resources that can be modified after creation also carry an `updated_at` timestamp, refreshed on every mutation, and a `version`, an integer that begins at 1 on creation and increments by one on every mutation that touches the resource — including mutations that only recompute a derived count such as `seats_sold` or `enrolled_count`.

One entity departs from this pattern. A **Contribution** is an append-only installment record: once written it is immutable, so it carries only an `id` and a `created_at`. It has no `updated_at` and no `version` of its own. (Its parent Sponsor does carry a `version`, and that is the version the optimistic-concurrency rule in Section 2.6 protects.)

All time in the system is measured against a **logical clock**, never the wall clock. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an administrator advances it the system must treat that instant as "now". An administrator can move the clock to any instant by supplying a `to_iso8601` value. Show start and end times, hold windows, membership expiry, and program start gates are all evaluated against this logical clock.

### 2.5. Deferred Sweeps

Certain consequences are **deferred**: they do not fire the moment the clock passes a threshold, but only when an administrator runs the sweep operation. Two things happen during a sweep, both evaluated at the current logical clock. First, every membership that is `ACTIVE` and whose expiry instant the clock has reached or passed is moved to `EXPIRED`. Second, every show booking still in `HELD` whose hold window has elapsed is released: the booking moves to `CANCELLED`, its seats are returned to the show, and the show reopens from `SOLD_OUT` to `OPEN` if the freed seats bring it back below capacity. Between sweeps, an expired-but-unswept membership and a stale-but-unswept hold retain their last persisted status.

### 2.6. Optimistic Concurrency on Supersede-Style Creates

Three create operations consume a scarce, shared resource — the last seats of a show, the last chair of a program, or the remaining headroom on a sponsor's pledge — and each guards against a stale view of that resource using optimistic concurrency control. In every case the client must echo back the `version` of the parent it last observed, and the server compares it to the parent's live `version` before committing.

When a seat hold is created on a show, the request must carry `expected_show_version` equal to the target ShowEvent's current `version`. If another writer has advanced that version since the client last read the show (by creating a competing hold, for instance, which bumps both `seats_sold` and `version`), the create is rejected with `ERR_STALE_SHOW_VERSION` and HTTP 412, so the client cannot book against a seat count it never saw.

When a participant is registered into a program, the request must carry `expected_session_version` equal to the target ProgramSession's current `version`. If that version has moved on because another writer enrolled into the session, the create is rejected with `ERR_STALE_SESSION_VERSION` and HTTP 412.

When a contribution is recorded against a sponsor, the request must carry `expected_sponsor_version` equal to the target Sponsor's current `version`. If another writer has already recorded an installment that advanced the sponsor toward fulfillment, the create is rejected with `ERR_STALE_SPONSOR_VERSION` and HTTP 412. Only these three create operations take a version field; no other endpoint accepts or requires one.

### 2.7. Hierarchical Consistency and Cascades

Several operations mutate more than one entity. When a parent is cancelled or completed, its children are reconciled and the parent's own bookkeeping is rewritten in the same operation; every such reconciliation that touches a resource carrying a `version` increments that `version` and refreshes `updated_at`. The seat count `seats_sold` on a show and the head count `enrolled_count` on a program are **derived** fields: they are recomputed whenever a booking or registration changes state, and the recompute is itself a mutation of the parent. The detailed cascade chains — a show cancellation rippling down to its bookings and then to their accommodation requests, or a registration cancellation promoting the head of the waitlist and possibly reopening a full session — are described in Section 3 alongside the workflows that trigger them, but the governing principle is uniform: a single client request may legitimately change the state of many resources, and the response returns the primary resource the request targeted.

### 2.8. Nested Resource Retrieval and Existence Order

Several read endpoints address a resource through a path that names a parent first — for example, listing the shows that belong to a particular venue, or listing the contributions recorded against a particular sponsor. For any such path, the system validates each identifier left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. The same left-to-right discipline governs write requests: path identifiers are checked before body foreign keys, and a missing parent is reported before the system looks at anything nested beneath it.

### 2.9. Money, Precision, and Rounding

Every monetary amount in the system is stored and returned as an integer count of cents — there are no fractional cents and no floating-point currency fields. Where a calculation multiplies a price by a discount percentage, the rounding method is **round half up**, and the section that defines each calculation pins exactly when the rounding happens relative to the other arithmetic. The one non-integer figure in the system is a Sponsor's `fulfillment_ratio`, which is a ratio rounded to four decimal places. The deposit figures for group bookings and rentals are produced by taking a percentage of a running total and discarding any fractional cent — they are floored, not rounded.

### 2.10. Venue Capacity, Time Windows, and Buffers

Each venue declares a `seated_capacity` (the most occupants a single session may hold) and, within it, a number of `accessible_seats`. A venue also declares a `turnover_buffer_minutes` — the cleaning and reset time that must elapse after one show ends before the next show may begin in the same venue. Shows are scheduled into a venue as half-open time windows: the window runs from `starts_at` inclusive to `ends_at` exclusive. When a new show is scheduled, its window extended forward by the venue's turnover buffer must not overlap any other non-cancelled show in that same venue; an overlap is rejected with `ERR_SHOW_TIME_CONFLICT`. Rental windows are likewise half-open from `starts_at` inclusive to `ends_at` exclusive, but they carry **no** buffer: a rental may be held only if its bare window overlaps no other held or confirmed rental in the same hall, and an overlap is rejected with `ERR_RENTAL_TIME_CONFLICT`.

## 3. Business Logic & Workflows

### 3.1. Venues: The Shared Physical Inventory

Everything the center sells happens inside a **Venue**, and a `FacilityAdmin` is the only role that may create one. A venue is created with a `name`, a `venue_type`, and a `seated_capacity`, and it may optionally specify a `turnover_buffer_minutes` and an `accessible_seats` count. The `venue_type` is one of `DOME`, `THEATER`, `GALLERY`, `CLASSROOM`, or `RENTAL_HALL`. The `seated_capacity` must be at least 1. The `turnover_buffer_minutes` defaults to 15 minutes when omitted and may not be negative. The `accessible_seats` count defaults to 0 when omitted, may not be negative, and may not exceed the venue's `seated_capacity` — these accessible seats are a subset of the seated capacity, not an addition to it. A venue is born with `status` of `ACTIVE` and stays `ACTIVE`; there is no other venue state.

The type of a venue determines what may be scheduled in it, and the system enforces this when each kind of event is created: a show requires a `DOME` or `THEATER` venue, a program session requires a `CLASSROOM` venue, and a rental requires a `RENTAL_HALL` venue. A mismatch between the requested event and the venue's `venue_type` is rejected with `ERR_VENUE_TYPE_MISMATCH`. Venues can be browsed as a paginated list (optionally filtered by `venue_type`) or fetched one at a time, and three reverse lookups expose the events anchored to a venue: the shows in it, the program sessions in it, and the rentals in it.

### 3.2. Memberships and ASTC Reciprocity

A `MembershipClerk` opens a membership card with a `primary_member_name`, a `tier`, and the member's five-digit `home_zip`; an optional `party_size` rounds out the request. The `tier` is one of `INDIVIDUAL`, `FAMILY`, or `PATRON`. The `party_size` is the number of named admissions on the card and defaults to 1. Tier governs the party composition: an `INDIVIDUAL` card must have a `party_size` of exactly 1, while a `FAMILY` or `PATRON` card may name from 1 to 6 admissions inclusive. A request that violates this composition rule is rejected with `ERR_PARTY_SIZE_INVALID`. A new card begins life in `PENDING` status.

The card also computes a flag, `astc_eligible`, which is true exactly when the tier is `FAMILY` or `PATRON` — only those two tiers carry reciprocal benefits, and an `INDIVIDUAL` card is never ASTC-eligible. When a clerk activates a card, the activation request carries the dues being paid as `dues_cents`. Activation stamps `activated_at` with the current logical-clock instant, sets `expires_at` to exactly 365 days after `activated_at`, adds the paid dues into the running `dues_paid_cents` total, (re)computes `astc_eligible` from the tier, and moves the card from `PENDING` to `ACTIVE`. While a card is `PENDING`, both `activated_at` and `expires_at` are null and `dues_paid_cents` reflects only what has been collected so far (zero by default).

A membership's later life is a cycle. Once the logical clock reaches or passes `expires_at`, the next sweep moves an `ACTIVE` card to `EXPIRED` (Section 2.5). An `EXPIRED` card can be renewed through the same activation operation: renewal re-stamps `activated_at` to the current instant, recomputes `expires_at` as 365 days later, adds the renewal dues into `dues_paid_cents`, and returns the card to `ACTIVE` — so a card may travel `ACTIVE → EXPIRED → ACTIVE` any number of times. A clerk may also cancel a card: cancellation is allowed from `ACTIVE` or `PENDING` and moves the card to the terminal `CANCELLED` state.

Reciprocal admission follows the **ASTC 90-mile rule**, exposed both as a pricing gate when a membership is used to book and as a standalone computed read. A member is admitted free under reciprocity only when their card carries ASTC eligibility, the card is currently `ACTIVE`, and the member's home is outside the 90-mile reciprocal radius of this center. The radius is modeled deterministically by zip prefix: this center's prefix is the first three digits `606`, and a member whose `home_zip` begins with those same first three digits is treated as living within the 90-mile radius and therefore is **not** reciprocal-free here. Concretely, reciprocal admission is granted when the card is ASTC-eligible and `ACTIVE` and the first three characters of `home_zip` are not `606`; if the card is not ASTC-eligible, or is not `ACTIVE`, or its `home_zip` begins with `606`, reciprocal admission is denied. The standalone ASTC-status read reports this determination for a given card.

### 3.3. Scheduling and Running a Show

A `BoxOfficeOperator` schedules a **ShowEvent** into a dome or theater by supplying the `venue_id`, a `title`, the window bounds `starts_at` and `ends_at`, a `base_price_cents`, and an optional `feature_surcharge_cents`. The `base_price_cents` is the per-seat admission price and may not be negative; the `feature_surcharge_cents` is a per-seat premium for special presentations such as a laser-dome feature, defaults to 0, may not be negative, and is added on top of the base price. The end of the window must be strictly after the start, and a window where `ends_at` is not strictly after `starts_at` is rejected with `ERR_INVALID_TIME_WINDOW`. The new show must also clear the venue overlap-plus-buffer test of Section 2.10 (`ERR_SHOW_TIME_CONFLICT`) and the venue-type test (`ERR_VENUE_TYPE_MISMATCH`). A freshly scheduled show starts in `SCHEDULED` status with `seats_sold` at 0 and `version` at 1.

A show is not bookable until it is opened. Opening transitions the show `SCHEDULED → OPEN` and bumps its `version`; it is permitted only while the show is still `SCHEDULED` and the logical clock is still before the show's `starts_at`. Once `OPEN`, the show accrues bookings, and `seats_sold` tracks the sum of `party_size` across the bookings that currently occupy seats — namely those in `HELD` or `CONFIRMED`. When `seats_sold` reaches the venue's `seated_capacity`, the system automatically bubbles the show `OPEN → SOLD_OUT`; when a later cancellation frees a seat and `seats_sold` drops back below capacity, the system bubbles it `SOLD_OUT → OPEN`. This `OPEN ↔ SOLD_OUT` cycle is driven entirely by seat arithmetic, not by an operator action, and every such auto-transition bumps the show's `version`.

An operator can cancel a show from any of `SCHEDULED`, `OPEN`, or `SOLD_OUT`. Cancelling a `SCHEDULED` show that never opened simply moves it to `CANCELLED` and bumps its `version`. Cancelling an `OPEN` or `SOLD_OUT` show runs a depth-three cascade: every booking on the show that is currently `HELD` or `CONFIRMED` is moved to `CANCELLED` (releasing its seats and making its `net_price_cents` refundable); then, for each booking so cancelled, any linked accommodation request that is currently `SUBMITTED` or `APPROVED` is moved to `DENIED`; then the show's `seats_sold` is set to 0, the show is set to `CANCELLED`, and its `version` is incremented. `CANCELLED` is terminal.

Completing a show is the graceful end of its life. Completion is permitted from `OPEN` or `SOLD_OUT` and only once the logical clock has reached or passed the show's `ends_at`. On completion, every booking still merely `HELD` is released to `CANCELLED` as a no-show, while every `CONFIRMED` booking stays `CONFIRMED` (it was consumed at the door); the show then moves to `COMPLETED` and its `version` is incremented. `COMPLETED` is terminal.

### 3.4. Individual Show Bookings: Holds, Pricing, Confirmation, Refunds

The unit of individual admission is a **ShowBooking**, created by a `BoxOfficeOperator` as a seat **hold** on an open show. The create request names the `show_event_id`, a `party_size` (at least 1 seat), and the `expected_show_version` discussed in Section 2.6; it may optionally name a `membership_id` (the card used for member pricing, or null for a walk-up) and an `accessible_seats_requested` count. The `accessible_seats_requested` defaults to 0 and may range from 0 up to the booking's own `party_size`. The hold is rejected with `ERR_SHOW_CAPACITY_EXCEEDED` if the show's current `seats_sold` plus the requested `party_size` would exceed the venue's `seated_capacity`. It is rejected with `ERR_ACCESSIBLE_SEATS_UNAVAILABLE` if the `accessible_seats_requested` exceeds the accessible seats still free on the show's venue. A successful hold records `held_at` as the current logical-clock instant, snapshots the price (below), reserves the seats by recomputing the show's `seats_sold`, bubbles the show to `SOLD_OUT` if it just filled, and increments the show's `version`. The booking begins in `HELD`.

Pricing is snapshotted at hold time onto three fields. The per-seat price is the show's `base_price_cents` plus its `feature_surcharge_cents`. The `gross_price_cents` is the booking's `party_size` multiplied by that per-seat price. The `member_discount_cents` is the member discount, which is 0 for any walk-up (no `membership_id`) and 0 whenever the named card is not currently `ACTIVE`. For an `ACTIVE` card the discount depends on tier, and in every tiered case the per-seat discount is computed and rounded to whole cents **before** multiplying by `party_size` (round each seat first, then sum — never sum then round):

- A `PATRON` card discounts 100% of the base price but never the feature surcharge; its discount is the `party_size` multiplied by the show's `base_price_cents`.
- A `FAMILY` card discounts 50% of the full per-seat total (base plus surcharge): take the per-seat price, multiply by 0.50, round half up to whole cents, then multiply by `party_size`.
- An `INDIVIDUAL` card discounts 25% of the base price only, with the surcharge paid in full: take the `base_price_cents`, multiply by 0.25, round half up to whole cents, then multiply by `party_size`.

The `net_price_cents` is the `gross_price_cents` minus the `member_discount_cents`, snapshotted at hold time and frozen thereafter.

A hold is good for exactly **30 minutes** of logical time. Confirming a hold moves the booking `HELD → CONFIRMED`; it is permitted only while the booking is still `HELD`, the logical clock is still before `held_at` plus 30 minutes, and the linked show is in `OPEN` or `SOLD_OUT`. A confirm attempted after the 30-minute window has elapsed is rejected with `ERR_HOLD_EXPIRED`. Confirmation freezes `net_price_cents` (no recompute), leaves the occupied-seat count unchanged (a held seat and a confirmed seat both occupy), and increments the show's `version`. A held booking that is never confirmed is swept to `CANCELLED` once its window lapses (Section 2.5).

Cancelling a booking is permitted while it is `HELD`. Cancellation releases the booking's `party_size` seats by recomputing the show's `seats_sold`, bubbles the show `SOLD_OUT → OPEN` if the freed seats bring it back below capacity, and increments the show's `version`. Refunding is the corresponding action for a booking that has already been confirmed: refund is permitted only while the booking is `CONFIRMED` and the logical clock is still before the linked show's `starts_at`. A refund releases the `party_size` seats, recomputes `seats_sold`, returns the `net_price_cents` to the buyer under a conserved-quantity invariant (the cents paid in equal the cents paid out), bubbles `SOLD_OUT → OPEN` if seats now fall below capacity, increments the show's `version`, and moves the booking to the terminal `REFUNDED` state. `CANCELLED` and `REFUNDED` are both terminal for a booking.

### 3.5. Field Trips and Group Blocks

A `GroupSalesAgent` reserves a block of seats for a school or organization as a **GroupBooking**. The request names the `show_event_id`, an `organization_name`, a `student_count` (at least 1), and a `chaperone_count` (zero or more). At request time the system computes the block's `total_seats` as the `student_count` plus the `chaperone_count`, and computes a provisional `deposit_cents` as a forward-looking estimate. The booking begins in `REQUESTED`. Because the true head-counts are not known until the trip is confirmed, the deposit is only an estimate; the request also stores it as a snapshot.

The deposit estimate and the final balance share one piece of arithmetic, a **grand total** that takes a student count and a chaperone count and prices them as follows. The per-seat price is again the show's `base_price_cents` plus `feature_surcharge_cents`. Chaperones earn one free admission for every 10 students — divide the student count by 10 and take the whole-number part to get the free-chaperone allowance, and the billable chaperones are the chaperone count minus that allowance, but never fewer than zero. Each student seat is priced at 70% of the per-seat price: multiply the per-seat price by 0.70 — equivalently, apply the 30% group student discount — and round half up to whole cents, then multiply by the student count to get the students' total. Each billable chaperone pays the show's `base_price_cents` only (no surcharge), so the chaperones' total is the billable-chaperone count multiplied by `base_price_cents`. The grand total is the students' total plus the chaperones' total.

The **deposit** runs that grand total over the requested `student_count` and `chaperone_count`, takes 25% of it, and floors the result to whole cents; that figure is stored in `deposit_cents`. When the agent pays the deposit, the booking moves `REQUESTED → DEPOSIT_PAID`: this is permitted only while the booking is `REQUESTED` and the linked show is `OPEN`, and only if the show's `seats_sold` plus the block's `total_seats` would not exceed the venue's `seated_capacity` (otherwise `ERR_SHOW_CAPACITY_EXCEEDED`). Paying the deposit reserves the block by adding `total_seats` into the show's `seats_sold`, bubbles the show to `SOLD_OUT` if the block fills it, and increments the show's `version`.

Confirmation supplies the real head-counts. The confirm request carries `actual_student_count` and `actual_chaperone_count`, which are stored on the booking, and is permitted only from `DEPOSIT_PAID`. At confirm time the system runs the very same grand-total arithmetic, but now over the actual head-counts, and sets `balance_cents` to that final grand total minus the already-collected `deposit_cents`. Because the estimate and the actuals can differ, the final figure is not simply four times the deposit — the forward-looking estimate and the actual-count final are independent computations on the same booking row. Confirmation moves the booking to `CONFIRMED`.

A group booking can be cancelled. Cancelling from `REQUESTED` (before any seats were reserved) simply moves it to `CANCELLED`. Cancelling from `DEPOSIT_PAID` first releases the reserved block by subtracting `total_seats` from the show's `seats_sold`, bubbles the show `SOLD_OUT → OPEN` if it now falls below capacity, increments the show's `version`, and then moves the booking to `CANCELLED`. `CANCELLED` is terminal for a group booking.

### 3.6. Camps, Classes, and the Waitlist

A `ProgramCoordinator` opens a **ProgramSession** — a multi-day camp or a single class — in a classroom by supplying the `venue_id`, a `title`, a `program_kind` of either `CAMP` or `CLASS`, a `min_age` and a `max_age` (the inclusive age band, where `max_age` must be at least `min_age`), a `starts_at`, a `capacity` (at least 1 confirmed enrollment), and a per-participant `tuition_cents` (zero or more). The session opens in `ENROLLING` with `enrolled_count` at 0 and `version` at 1. The session's `enrolled_count` always reflects the number of registrations currently `ENROLLED`, recomputed on every registration change.

Registering a participant creates a **Registration** carrying the `program_session_id`, a `participant_name`, a `participant_age`, the `expected_session_version` of Section 2.6, and optionally a `membership_id`. Enrollment is gated on age: the participant's age must fall within the session's band, that is, at least `min_age` and at most `max_age`; an age outside the band is rejected with `ERR_AGE_INELIGIBLE`. A registration is **never rejected for being full** — instead, when a participant registers and a seat remains (the session's `enrolled_count` is below `capacity`), the registration is enrolled directly; when no seat remains, the registration is accepted but placed on the waitlist. An enrolled registration is `ENROLLED`; a waitlisted one is `WAITLISTED`, and its `waitlist_position` is its 1-based rank among the session's `WAITLISTED` registrations ordered by `created_at` ascending (the position is null while enrolled). The system never honors an explicit force-enroll past capacity; an internal over-capacity force-enroll is the only path that yields `ERR_SESSION_FULL`.

When a registration is enrolled, the system recomputes the session's `enrolled_count`; if that count has reached `capacity`, the session bubbles `ENROLLING → FULL`; and the session's `version` is incremented. The reverse bubble `FULL → ENROLLING` happens only when a freed seat cannot be filled from the waitlist — that is, when `enrolled_count` falls below `capacity` and no `WAITLISTED` registration remains to promote.

Tuition is snapshotted onto `tuition_charged_cents` at enrollment time (only for a registration that actually enrolls). The base is the session's `tuition_cents`. A walk-up (no `membership_id`) or a participant whose card is not currently `ACTIVE` pays the full base. For an `ACTIVE` card, a percentage discount applies first: a `PATRON` card pays 60% of base (a 40% reduction), and a `FAMILY` or `INDIVIDUAL` card pays 85% of base (a 15% reduction) — in each case multiply the base by the surviving fraction and round half up to whole cents. After that percentage step, an **early-bird** reduction may apply: if the session's `enrolled_count` observed immediately before this enrollment is fewer than 3, a further flat 1000 cents is subtracted, with the result floored at 0. The evaluation order is pinned: apply the percentage discount and round it first, then subtract the flat early-bird amount, then floor at 0.

Cancelling a registration is the most intricate cascade in the system. A `WAITLISTED` registration cancelled simply leaves the waitlist, and the `waitlist_position` of every registration behind it shifts down by one. An `ENROLLED` registration may be cancelled only while the session is in `ENROLLING` or `FULL`; doing so runs a depth-three chain: first the session's `enrolled_count` is recomputed downward; then the `WAITLISTED` registration with the lowest `created_at` on that session is promoted to `ENROLLED` to fill the freed seat, and `enrolled_count` is recomputed again; then, if there was no waitlisted registration left to promote and the session was `FULL`, the session reopens `FULL → ENROLLING`. The session's `version` is incremented across this operation. A registration's only terminal state is `CANCELLED`.

The coordinator ends a session in one of two ways. Starting the session is permitted from `ENROLLING` or `FULL` once the logical clock has reached or passed the session's `starts_at`; starting purges the waitlist, moving every `WAITLISTED` registration on the session to `CANCELLED`, sets the session to `STARTED`, and increments its `version`. Cancelling the session is permitted from `ENROLLING` or `FULL` and cascades to every registration that is `ENROLLED` or `WAITLISTED`, moving each to `CANCELLED`, then sets the session's `enrolled_count` to 0, sets the session to `CANCELLED`, and increments its `version`. Both `STARTED` and `CANCELLED` are terminal for a session.

### 3.7. Private Rentals of the Hall

An `EventsManager` handles private rentals of the rental hall as a **RentalEvent**. An inquiry is created with the `venue_id`, a `host_name`, the window bounds `starts_at` and `ends_at`, an estimated `guest_count` (at least 1), and a flat `base_rental_cents` hall fee (zero or more). As with shows, the end of the window must be strictly after the start, and a window failing that is rejected with `ERR_INVALID_TIME_WINDOW`; the venue must be a `RENTAL_HALL` or the inquiry is rejected with `ERR_VENUE_TYPE_MISMATCH`. At inquiry time the system computes and snapshots a provisional `deposit_cents`. The inquiry begins in `INQUIRY`.

Rental pricing uses a marginal two-tier guest charge layered on the flat hall fee. The first 20 guests are charged 500 cents each; every guest beyond the first 20 is charged 300 cents each. Concretely, the tier-one guests are the smaller of the guest count and 20, the tier-two guests are whatever remains above 20 (never below zero), and the guest charge is the tier-one count times 500 cents plus the tier-two count times 300 cents. The grand total is the `base_rental_cents` plus that guest charge. The **deposit** runs this grand total over the estimated `guest_count`, takes 25% of it, and floors to whole cents, storing the result in `deposit_cents`.

Holding the rental moves it `INQUIRY → HELD`; it is permitted only from `INQUIRY`, and only if the rental's bare window overlaps no other `HELD` or `CONFIRMED` rental in the same hall (otherwise `ERR_RENTAL_TIME_CONFLICT`, per Section 2.10). Confirming the rental moves it `HELD → CONFIRMED`: the confirm request supplies the final `actual_guest_count`, which is stored, and the system computes the full final invoice `total_cents` by running the same grand-total arithmetic over the `actual_guest_count` (the full gross invoice, not a deposit fraction). Because the actual guest count can differ from the estimate, the final total is independent of four times the deposit.

A rental can be cancelled. From `INQUIRY` or `HELD`, cancellation simply releases any held window and moves the rental to `CANCELLED`. From `CONFIRMED`, cancellation is permitted only while the logical clock is still before the rental's `starts_at`; it too releases the window and moves the rental to `CANCELLED`. `CANCELLED` is terminal for a rental.

### 3.8. Donors, Sponsors, and Contributions

A `DevelopmentOfficer` records a **Sponsor** — a one-time donor or a recurring sponsor — with an `org_name`, a `sponsor_kind` of either `DONOR` or `SPONSOR`, and a `pledged_cents` amount (zero or more). A sponsor opens in `PLEDGED` with `received_cents` at 0 and `version` at 1. The `received_cents` is the running sum of the amounts of this sponsor's contributions that are `RECEIVED`, and the `fulfillment_ratio` is the `received_cents` divided by the `pledged_cents`, rounded to four decimal places — and defined as 0 whenever `pledged_cents` is 0.

A **Contribution** is a single payment installment recorded against a sponsor. The request carries the `amount_cents` (at least 1) and the `expected_sponsor_version` of Section 2.6. A contribution is born `RECEIVED` and is immutable; it is the only entity that records who supplied it through `sponsor_id` and never changes thereafter. A contribution that would push the sponsor's `received_cents` above its `pledged_cents` is rejected with `ERR_OVERFULFILLMENT` — over-fulfillment is not allowed. Recording a contribution recomputes the sponsor's `received_cents` and `fulfillment_ratio` and increments the sponsor's `version`, and it advances the sponsor's status according to how much of the pledge is now covered:

- From `PLEDGED`, if the new `received_cents` lands strictly above 0 and strictly below `pledged_cents`, the sponsor moves to `PARTIALLY_FULFILLED`.
- From `PLEDGED`, if the very first installment brings `received_cents` to at least `pledged_cents`, the sponsor moves straight to `FULFILLED`.
- From `PARTIALLY_FULFILLED`, when `received_cents` reaches at least `pledged_cents`, the sponsor moves to `FULFILLED`.

A development officer may also mark a pledge lapsed. Lapsing is permitted from `PLEDGED` or `PARTIALLY_FULFILLED`, moves the sponsor to the terminal `LAPSED` state, and increments the sponsor's `version`. A sponsor's contributions can be listed in their own right.

### 3.9. Accessibility Accommodations

An **AccommodationRequest** lets an `AccessibilityCoordinator` attach an accessibility need to one of three subjects. The request names a `subject_type` of `SHOW_BOOKING`, `REGISTRATION`, or `RENTAL`, an `accommodation_kind` of `WHEELCHAIR`, `ASL_INTERPRETER`, `SENSORY_FRIENDLY`, or `ASSISTIVE_LISTENING`, and exactly one matching subject identifier — `show_booking_id` when the subject is a show booking, `registration_id` when it is a registration, or `rental_event_id` when it is a rental. Exactly one of the three identifiers must be present and it must agree with `subject_type`; a mismatch, a missing identifier, or more than one identifier is rejected with `ERR_ACCOMMODATION_SUBJECT_MISMATCH`. A new request begins in `SUBMITTED`.

Approving a request moves it `SUBMITTED → APPROVED`. For a `WHEELCHAIR` accommodation whose subject is a show booking, approval additionally checks that the booking's `accessible_seats_requested` does not exceed the accessible seats still remaining on the show's venue; if it does, approval is rejected with `ERR_ACCESSIBLE_SEATS_UNAVAILABLE`. Denying a request moves it from `SUBMITTED` directly to `DENIED`. An approved request can be fulfilled, moving it `APPROVED → FULFILLED`. Beyond these explicit operator actions, an accommodation can also be denied **by cascade**: when a show cancellation rolls down through a booking cancellation (Section 3.3), a linked accommodation that was `SUBMITTED` or `APPROVED` is forced to `DENIED`. Both `DENIED` and `FULFILLED` are terminal.

### 3.10. The Order in Which Requests Are Checked

When a single request could fail several ways, the checks run in a fixed priority so the reported error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then the role-permission check (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource validated left-to-right through the path and then the body foreign keys (`ERR_NOT_FOUND`), then the structural parse of the body with required fields present and correctly typed (`ERR_INVALID_REQUEST`). Only then come state and business checks: that the target is in a state from which the transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency version match on supersede-style creates (the stale-version family of Section 2.6), then accessibility seat availability (`ERR_ACCESSIBLE_SEATS_UNAVAILABLE`), then program age eligibility (`ERR_AGE_INELIGIBLE`), then the scheduling conflict checks for shows (`ERR_SHOW_TIME_CONFLICT`) and rentals (`ERR_RENTAL_TIME_CONFLICT`), then venue-type compatibility (`ERR_VENUE_TYPE_MISMATCH`), then the strictly-after time-window check (`ERR_INVALID_TIME_WINDOW`), then the hold-expiry check on confirm (`ERR_HOLD_EXPIRED`), then the membership party-size composition (`ERR_PARTY_SIZE_INVALID`), then show seat capacity (`ERR_SHOW_CAPACITY_EXCEEDED`), then the internal session-full guard (`ERR_SESSION_FULL`), then the over-fulfillment guard (`ERR_OVERFULFILLMENT`), then accommodation-subject coherence (`ERR_ACCOMMODATION_SUBJECT_MISMATCH`), then pagination range on list endpoints (`ERR_PAGINATION_INVALID`), and finally the generic numeric and semantic field-range checks (`ERR_VALIDATION`) such as a `seated_capacity` below 1, a negative `base_price_cents` or `pledged_cents`, a `party_size` below 1, or `accessible_seats` exceeding `seated_capacity`. A higher-priority failure is always reported in preference to a lower-priority one.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or run an administrative action return `200 OK`. The request body, response body, and side effects of each operation are described in Section 3 and are deliberately not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue | FacilityAdmin |
| GET | `/venues` | List venues (optional `venue_type` filter) | FacilityAdmin, BoxOfficeOperator, ProgramCoordinator, EventsManager, GroupSalesAgent, MembershipClerk, DevelopmentOfficer, AccessibilityCoordinator |
| GET | `/venues/{id}` | Fetch a single venue | FacilityAdmin, BoxOfficeOperator, ProgramCoordinator, EventsManager, GroupSalesAgent |
| GET | `/venues/{id}/shows` | List shows in a venue | FacilityAdmin, BoxOfficeOperator, GroupSalesAgent |
| GET | `/venues/{id}/programs` | List program sessions in a venue | FacilityAdmin, ProgramCoordinator |
| GET | `/venues/{id}/rentals` | List rentals in a venue | FacilityAdmin, EventsManager |
| POST | `/memberships` | Create a membership in PENDING | MembershipClerk |
| GET | `/memberships` | List memberships (optional `tier`/`status` filter) | MembershipClerk, BoxOfficeOperator |
| GET | `/memberships/{id}` | Fetch a single membership | MembershipClerk, BoxOfficeOperator, ProgramCoordinator |
| POST | `/memberships/{id}/activate` | Activate or renew a membership; pay dues | MembershipClerk |
| POST | `/memberships/{id}/cancel` | Cancel a membership | MembershipClerk |
| GET | `/memberships/{id}/astc-status` | Computed ASTC reciprocal eligibility | MembershipClerk, BoxOfficeOperator |
| POST | `/shows` | Schedule a show in a dome/theater | BoxOfficeOperator |
| GET | `/shows` | List shows (optional `venue_id`/`status` filter) | BoxOfficeOperator, GroupSalesAgent, FacilityAdmin |
| GET | `/shows/{id}` | Fetch a single show | BoxOfficeOperator, GroupSalesAgent, AccessibilityCoordinator |
| POST | `/shows/{id}/open` | Open a show for bookings | BoxOfficeOperator |
| POST | `/shows/{id}/cancel` | Cancel a show; cascade-cancel bookings and deny accommodations | BoxOfficeOperator |
| POST | `/shows/{id}/complete` | Complete a show after it ends; release held bookings | BoxOfficeOperator |
| POST | `/show-bookings` | Create a seat hold on an open show | BoxOfficeOperator |
| GET | `/show-bookings` | List show bookings (optional `show_event_id`/`membership_id`/`status` filter) | BoxOfficeOperator, AccessibilityCoordinator |
| GET | `/show-bookings/{id}` | Fetch a single show booking | BoxOfficeOperator, AccessibilityCoordinator |
| POST | `/show-bookings/{id}/confirm` | Confirm a held booking within its window | BoxOfficeOperator |
| POST | `/show-bookings/{id}/cancel` | Cancel a held booking; release seats | BoxOfficeOperator |
| POST | `/show-bookings/{id}/refund` | Refund a confirmed booking before the show starts | BoxOfficeOperator |
| POST | `/group-bookings` | Request a field-trip/group block; compute deposit | GroupSalesAgent |
| GET | `/group-bookings` | List group bookings (optional `show_event_id`/`status` filter) | GroupSalesAgent, BoxOfficeOperator |
| GET | `/group-bookings/{id}` | Fetch a single group booking | GroupSalesAgent |
| POST | `/group-bookings/{id}/pay-deposit` | Pay deposit; reserve the seat block | GroupSalesAgent |
| POST | `/group-bookings/{id}/confirm` | Confirm with actual head-counts; compute balance | GroupSalesAgent |
| POST | `/group-bookings/{id}/cancel` | Cancel a group booking; release seats | GroupSalesAgent |
| POST | `/programs` | Create a camp/class session in a classroom | ProgramCoordinator |
| GET | `/programs` | List program sessions (optional `venue_id`/`status` filter) | ProgramCoordinator, MembershipClerk |
| GET | `/programs/{id}` | Fetch a single program session | ProgramCoordinator |
| POST | `/programs/{id}/start` | Start the program; purge the waitlist | ProgramCoordinator |
| POST | `/programs/{id}/cancel` | Cancel the program; cascade-cancel registrations | ProgramCoordinator |
| POST | `/registrations` | Register a participant (auto enroll or waitlist) | ProgramCoordinator |
| GET | `/registrations` | List registrations (optional `program_session_id`/`membership_id`/`status` filter) | ProgramCoordinator |
| GET | `/registrations/{id}` | Fetch a single registration | ProgramCoordinator |
| POST | `/registrations/{id}/cancel` | Cancel a registration; promote waitlist | ProgramCoordinator |
| POST | `/rentals` | Create a rental inquiry; compute deposit | EventsManager |
| GET | `/rentals` | List rentals (optional `venue_id`/`status` filter) | EventsManager, FacilityAdmin |
| GET | `/rentals/{id}` | Fetch a single rental | EventsManager |
| POST | `/rentals/{id}/hold` | Hold the rental window | EventsManager |
| POST | `/rentals/{id}/confirm` | Confirm a held rental with final guest count | EventsManager |
| POST | `/rentals/{id}/cancel` | Cancel a rental; release the window | EventsManager |
| POST | `/sponsors` | Create a donor/sponsor pledge | DevelopmentOfficer |
| GET | `/sponsors` | List sponsors (optional `sponsor_kind`/`status` filter) | DevelopmentOfficer |
| GET | `/sponsors/{id}` | Fetch a single sponsor | DevelopmentOfficer |
| POST | `/sponsors/{id}/contributions` | Record a contribution; advance fulfillment | DevelopmentOfficer |
| GET | `/sponsors/{id}/contributions` | List a sponsor's contributions | DevelopmentOfficer |
| POST | `/sponsors/{id}/lapse` | Mark a pledge lapsed | DevelopmentOfficer |
| POST | `/accommodations` | Submit an accommodation request | AccessibilityCoordinator |
| GET | `/accommodations` | List accommodation requests (optional `show_booking_id`/`registration_id`/`rental_event_id`/`status` filter) | AccessibilityCoordinator |
| GET | `/accommodations/{id}` | Fetch a single accommodation request | AccessibilityCoordinator |
| POST | `/accommodations/{id}/approve` | Approve an accommodation (wheelchair seat check) | AccessibilityCoordinator |
| POST | `/accommodations/{id}/deny` | Deny an accommodation request | AccessibilityCoordinator |
| POST | `/accommodations/{id}/fulfill` | Mark an approved accommodation fulfilled | AccessibilityCoordinator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FacilityAdmin |
| POST | `/_sweeps/run` | Run deferred expiry/hold sweeps | FacilityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SHOW_VERSION` | 412 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_SPONSOR_VERSION` | 412 |
| `ERR_ACCESSIBLE_SEATS_UNAVAILABLE` | 409 |
| `ERR_AGE_INELIGIBLE` | 422 |
| `ERR_SHOW_TIME_CONFLICT` | 409 |
| `ERR_RENTAL_TIME_CONFLICT` | 409 |
| `ERR_VENUE_TYPE_MISMATCH` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_PARTY_SIZE_INVALID` | 422 |
| `ERR_SHOW_CAPACITY_EXCEEDED` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_OVERFULFILLMENT` | 422 |
| `ERR_ACCOMMODATION_SUBJECT_MISMATCH` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
