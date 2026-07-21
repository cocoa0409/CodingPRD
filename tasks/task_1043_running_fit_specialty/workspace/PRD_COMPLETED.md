# Running-Fit-Specialty API — Product Requirements Document

## 1. Introduction

The Running & Fit Specialty Store is a multi-channel running retailer whose staff do far more than sell shoes: they run gait-analysis and fitting sessions, coach group training, manage race-day packet logistics, and steward a membership club with loyalty rewards. This document specifies the backend API that ties those activities together into one coherent system of record. It is written for the engineers who will implement the service, and it is the sole authoritative description of the required behavior — every rule the implementation must honor is stated here in prose.

The domain is deliberately broad but flat: stores, staff, members, products, subscriptions, appointments, training sessions, enrollments, race events, registrations, orders, and shoe pairs each live as their own top-level collection, linked to one another only by reference. Several of these resources carry richer behavior than simple CRUD. A race registration, for instance, evolves along two independent axes — whether it has been paid for and whether its packet has been handed out — while a club subscription cycles between good standing and past-due. Two different kinds of calendar contention are enforced: a fitter's appointments must respect a personal buffer, whereas a store's coaching rooms are a shared pool that many overlapping sessions compete for. Money flows through loyalty points, tiered discounts, wallet credit, and refunds, all of which must be computed precisely and reconciled as a member's standing changes.

Because the system drives time-sensitive workflows (appointment scheduling, return windows, subscription periods), it runs on a **logical clock** rather than wall-clock time, so that tests and operators can advance "now" deterministically. The sections that follow define the global contract first — authentication, response envelopes, pagination, precision, and concurrency — and then walk each business workflow in turn.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request except open member self-registration and setting the logical clock must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. The recognized roles are exactly `Anonymous`, `Member`, `Staff`, and `StoreManager`. If either header is missing, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the role is not permitted to perform the requested operation — or an owner-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles differ in how `X-User-ID` binds to persisted data:

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque, unauthenticated identifier not tied to any persisted entity. The only operation available to an anonymous caller is registering a new member.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare that resource's member foreign key (`member_id` on subscriptions, appointments, enrollments, registrations, orders, and shoe pairs) to `X-User-ID`. A member may act only on resources they own, and may read their own resources plus the public catalog (stores, products, events, sessions).
- When `X-User-Role` is `Staff`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare that resource's staff foreign key to `X-User-ID`. In particular, completing a fitting appointment requires that `X-User-ID` equal the appointment's `fitter_id`.
- When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque back-office operator identifier not tied to any persisted entity. The server may accept it for audit purposes but does not compare it to any entity's `id`; a store manager's authority is role-based, not ownership-based.

Members register subscriptions, activate and cancel them, book and cancel fitting appointments, enroll in and cancel training-session seats, register for and pay for and cancel race entries, open carts and place, cancel, and return orders, and register shoe pairs and log runs. Staff complete appointments, cancel sessions, allocate race packets, and fulfill orders. Store managers create stores, staff, products, inventory adjustments, training sessions, and race events, close events, renew subscriptions, and drive the clock. Reads of individual resources and collections are available to the roles noted per endpoint in §4.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are always ordered by `created_at` ascending — never by `id`. Each list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page) inside the `meta` object.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits at creation. All resources in this system are mutable and therefore also carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at 1 when the resource is created and increments by one on each mutation that changes the resource. Newly registered members, for example, are created with `version` 1. Clients never set `id`, `created_at`, `updated_at`, or `version`; the server owns them. Resources that carry a lifecycle also expose a `status` field holding their current state, whose legal values are enumerated per resource in §3 (a registration is the sole exception, splitting its lifecycle across the two separate `payment_status` and `packet_status` fields rather than a single `status`).

### 2.5. The Logical Clock and Temporal Semantics

Time in this system is governed by a logical clock rather than the host wall clock. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any clock-setting call it returns precisely this default and never falls back to real time. A store manager may advance the clock by supplying a target instant (`to_iso8601`); the response reports the new `current_utc`. Every timestamp the system stamps — a subscription's `started_at`, an order's `placed_at` and `fulfilled_at`, a run log's `logged_at` when omitted — is read from this logical clock, and every temporal rule (past-dated booking checks, return windows, subscription periods) is evaluated against it.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a discount or fee is computed from a percentage, the result is rounded half-up to a whole number of cents. In order pricing specifically, rounding is applied **per line item before summing** — each line's discount is rounded to whole cents first, and only then are the rounded per-line discounts added together (round-per-line-then-sum, never sum-then-round). Loyalty points are integers obtained by flooring (rounding down) a cents total divided by a divisor. Shoe mileage is tracked to one decimal place, with kilometer values rounded half-up to one decimal.

### 2.7. Optimistic Concurrency on Member Supersession

Creating a subscription for a member is optimistic-concurrency-guarded on the member's `version`. A create-subscription request must include `expected_member_version` carrying the client's last observed `Member.version`. Because a new subscription legitimately supersedes (and cancels) any prior non-cancelled subscription of that member, and because a successful create advances `Member.version`, a second create issued against a stale view of the member is a genuine supersede race. If `expected_member_version` does not equal the member's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding a subscription state it never observed. No other endpoint takes a version field.

### 2.8. Validation Ordering

When several conditions could reject a request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or unrecognized header pair yields `ERR_UNAUTHENTICATED` (401). Authorization is second: a role not permitted for the operation, or an owner acting on a resource it does not own, yields `ERR_UNAUTHORIZED` (403). Third, request-body well-formedness is checked — required fields present, enum values legal, numeric quantities and amounts at least their declared minimums, `end_at` strictly after `start_at`, and `expected_member_version` present on subscription create — with any violation yielding `ERR_VALIDATION` (400). Fourth, existence of every id referenced in the path and in foreign-key body fields is checked left-to-right, yielding the resource-specific not-found error (404) for the first unresolved id. An owner-scoped role's ownership check on a resource whose owner is discovered only by loading it (an owned resource named directly in the path — a subscription, appointment, enrollment, registration, order, or shoe pair) is therefore applied after that path resource has resolved to exist, so a still-unresolved path id yields its 404 before any 403; an ownership check against a `member_id` supplied in the request body is instead applied at priority two, before the existence of any referenced foreign key. Only after all four of these pass are state, cross-entity, temporal, safety, and capacity rules evaluated; those rules and their error codes are described alongside the workflows they guard in §3, and where two such rules could both apply the narrative there states which takes precedence.

### 2.9. Nested Resource Retrieval and Reverse Lookups

Path parameters are validated left-to-right: for a nested path, each id segment must resolve to an existing resource before the next is considered, and the first unresolved id determines the 404. Several collections expose reverse-lookup reads: a store's staff roster, a member's subscriptions, and filtered lists of appointments (by `member_id` or `fitter_id`), training sessions (by `coach_id` or `store_id`), session enrollments (by `session_id` or `member_id`), race registrations (by `event_id` or `member_id`), orders (by `member_id`), and shoe pairs (by `member_id` or `product_id`). All such filters are optional query parameters that narrow the collection; when omitted, the full collection (subject to role scoping and pagination) is returned. For a caller acting in the `Member` role, every member-scoped list (appointments, session enrollments, race registrations, orders, and shoe pairs) is always narrowed to the caller's own `member_id`: any `member_id` query filter supplied by a member is ignored in favor of the caller's id, so a member never sees another member's rows through these lists (a `fitter_id`, `session_id`, `event_id`, or `product_id` filter still applies on top of that scoping).

## 3. Business Logic & Workflows

### 3.1. Members, Loyalty Standing, and the Store Wallet

Anyone may register as a member by supplying an `email` (unique per member) and a `full_name`; registration is the one endpoint open to an anonymous caller. A freshly registered member starts with `loyalty_points` of 0, a `loyalty_tier` of `BRONZE`, `wallet_credit_cents` of 0, and `version` 1. The member record is later read back by the member themselves, by staff, or by a store manager.

Loyalty accrues from realized spend. Each cent a member spends on fulfilled orders contributes to `loyalty_points`: the earned balance is the total of `final_total_cents` across all of the member's orders in `FULFILLED` status, divided by 100 and rounded down to a whole number of points. A member's persisted `loyalty_tier` is derived from that earned balance: `PLATINUM` once earned points reach 3000, otherwise `GOLD` at 1500 or more, otherwise `SILVER` at 500 or more, otherwise `BRONZE`. This persisted tier is the one used by order and fitting pricing, and it is recomputed whenever `loyalty_points` changes.

A dedicated loyalty-standing view returns both the realized and a forward-looking projection. The `earned_points` figure reflects only `FULFILLED` orders (as above), and `current_tier` is the tier derived from it. The `projected_points` figure adds, to that same fulfilled total, the sum of `provisional_total_cents` across the member's orders currently in `PLACED` status, the combined cents total again divided by 100 and rounded down; `projected_tier` is the tier derived from `projected_points` using the identical thresholds, and it can therefore exceed `current_tier`. Orders in `CART`, `RETURNED`, or `CANCELLED` status contribute to neither figure.

The **store wallet** (`wallet_credit_cents`) is a running store-credit balance. It is increased by race-registration refunds and by order returns, each of which credits a computed amount to the member's wallet as described in the race and returns workflows below. It is never decreased by this API.

### 3.2. Club Subscriptions

A member joins the club by creating a subscription for themselves, choosing a `tier` of either `CLUB_BASIC` or `CLUB_PRO` and supplying `expected_member_version` (see §2.7). The new subscription is created in `PENDING` status. Its `monthly_fee_cents` is derived from the tier — 4000 cents for `CLUB_BASIC`, 8000 cents for `CLUB_PRO` — and its `included_fittings_per_month` is likewise tier-derived: one included fitting per period for `CLUB_BASIC`, three for `CLUB_PRO`. Creating the subscription also supersedes the member's club history: any prior subscription of that member not already in `CANCELLED` transitions to `CANCELLED`, and the member's `version` increments by one. The subscription references its owner through `member_id`. A freshly created subscription carries `fittings_used_this_period` 0 and a null `started_at` and `current_period_end`, which remain null until activation.

Activation moves a subscription from `PENDING` to `ACTIVE` and may be performed only by the owning member on their own `PENDING` subscription (payment is assumed captured). Activation stamps `started_at` from the logical clock, sets `current_period_end` to `started_at` plus 30 days, and resets `fittings_used_this_period` to 0. Attempting to activate a subscription that is not `PENDING` is an invalid transition and is rejected with `ERR_INVALID_STATE` (409).

Subscriptions renew on a cyclic basis driven by the store manager, who submits a `payment_outcome`. A `payment_outcome` of `FAILED` moves an `ACTIVE` subscription to `PAST_DUE`; while `PAST_DUE`, the member loses their club gear and training discounts, so subsequent order and fitting pricing recomputes with the subscription's gear/training contribution treated as zero. A `payment_outcome` of `SUCCEEDED` on a `PAST_DUE` subscription reactivates it to `ACTIVE`, advances `current_period_end` by a further 30 days, and resets `fittings_used_this_period` to 0. This `ACTIVE` ⇄ `PAST_DUE` cycle may repeat. Renewal applies only from the state each half expects; a renewal request against a subscription in an incompatible state is rejected with `ERR_INVALID_STATE` (409).

The owning member may cancel their subscription from either `ACTIVE` or `PAST_DUE`, moving it to the terminal `CANCELLED` status; a cancel attempt from any other state (a still-`PENDING` subscription, or one already `CANCELLED`) is rejected with `ERR_INVALID_STATE` (409). Cancelling from `ACTIVE` reverts the member to non-subscriber pricing (the subscription gear/training discount becomes zero) on future orders and fittings; cancelling from `PAST_DUE` simply closes the subscription with no refund. `CANCELLED` is terminal, and any further transition attempt on it yields `ERR_INVALID_STATE` (409). A member may list their own subscriptions and fetch any one by id.

### 3.3. Gait Analysis and Fitting Appointments

A member books a fitting by naming the member being fitted (`member_id`), the fitter (`fitter_id`, a staff member whose `role_type` is `FITTER` or `BOTH`), a `service_type` of `GAIT_ANALYSIS`, `SHOE_FITTING`, or `FOLLOWUP`, and the appointment window as `start_at` and `end_at` (ISO 8601 UTC, with `end_at` strictly after `start_at`). The appointment is created in `SCHEDULED` status, and its `fitter_id` names the resource whose calendar is protected. Both `gait_result` and `fee_cents` are null on a newly booked appointment and stay null until it is completed.

Two guards apply at booking time. First, no appointment may be booked in the past: `start_at` must be at or after the current logical clock, and an earlier `start_at` is rejected with `ERR_APPOINTMENT_IN_PAST` (422). Second, a fitter's calendar is protected by a personal buffer of 15 minutes: the requested appointment is refused if any other `SCHEDULED` appointment on the same fitter falls within that buffer of the requested window. Concretely, a conflict exists when the requested start is earlier than the other appointment's end extended forward by 15 minutes, and simultaneously the other appointment's start is earlier than the requested end extended forward by 15 minutes; when both conditions hold the booking is rejected with `ERR_FITTER_UNAVAILABLE` (409). Two windows that sit exactly 15 minutes or more apart do not conflict. Cancelling an appointment releases the fitter's buffered window so a later appointment may reuse it.

The owning member may cancel their own `SCHEDULED` appointment, moving it to the terminal `CANCELLED` status and freeing the fitter's window. Only the fitter assigned to the appointment (the staff member whose `id` equals `fitter_id`) may complete it, and only while it is `SCHEDULED`; completion moves it to the terminal `COMPLETED` status, records the `gait_result` supplied in the request body (for example a pronation classification, which stays null until completion), and computes `fee_cents`. Completing or cancelling an appointment that is not `SCHEDULED` yields `ERR_INVALID_STATE` (409).

The fee charged at completion depends on the member's subscription and loyalty standing. The base fee is selected by service type: 6000 cents for a `GAIT_ANALYSIS`, 3000 cents for a `SHOE_FITTING`, and 2000 cents for a `FOLLOWUP`. If the member holds an `ACTIVE` subscription and has not yet used their full monthly allowance — that is, `fittings_used_this_period` is strictly less than `included_fittings_per_month` — the fitting is free (`fee_cents` is 0) and counts as an included fitting: completion increments that subscription's `fittings_used_this_period` by one. Otherwise, if the member holds an `ACTIVE` subscription but the included allowance is exhausted, a discount applies: the subscription's training discount for its tier (10% for `CLUB_BASIC`, 20% for `CLUB_PRO`) is added to the member's loyalty discount (0% at `BRONZE`, 5% at `SILVER`, 10% at `GOLD`, 15% at `PLATINUM`), the sum is capped at 30%, and `fee_cents` is the base fee multiplied by one minus that capped discount, rounded half-up to whole cents; this branch does not consume an included fitting. If the member has no `ACTIVE` subscription (none at all, or one that is `PENDING`, `PAST_DUE`, or `CANCELLED`), the full base fee is charged with no discount. Appointments may be fetched individually and listed, optionally filtered by `member_id` or `fitter_id`.

### 3.4. Group Training Sessions and Enrollment Waitlists

A store manager schedules a group training session by naming the leading coach (`coach_id`, a staff member whose `role_type` is `COACH` or `BOTH`), the hosting store (`store_id`), a difficulty `level` of `BEGINNER`, `INTERMEDIATE`, or `ADVANCED`, the window (`start_at` and `end_at`, with `end_at` strictly after `start_at`), and a seat `capacity` of at least one. The session is created in `SCHEDULED` status with `enrolled_count` 0.

Session scheduling enforces two distinct kinds of calendar contention. The coach's calendar uses a strict overlap check with no buffer: if any other `SCHEDULED` session led by the same coach has a half-open window `[start_at, end_at)` that overlaps the requested window, the request is rejected with `ERR_COACH_UNAVAILABLE` (409); back-to-back sessions that merely touch at an endpoint do not overlap and are allowed. The store's coaching rooms are instead a shared pool sized by `session_room_count` (each store carries this count, defaulting to 1, and it must be at least 1). A new session is admitted only while the number of existing `SCHEDULED` sessions at that store whose half-open windows overlap the requested window is strictly less than `session_room_count`; if admitting it would meet or exceed that room count, the request is rejected with `ERR_SESSION_ROOM_CONFLICT` (409). This aggregate check also uses no buffer.

Members enroll themselves into a session. Enrollment requires the parent session to be `SCHEDULED`; an enrollment attempt against a session that is not `SCHEDULED` is rejected with `ERR_SESSION_NOT_SCHEDULED` (409). A member may not hold more than one live seat per session, so an enrollment create is refused with `ERR_VALIDATION` (400) if the member already has a non-`CANCELLED` enrollment for that session. When the session has room — `enrolled_count` is strictly less than `capacity` — the new enrollment is created `ENROLLED` and `enrolled_count` increments by one. When the session is full — `enrolled_count` equals `capacity` — the new enrollment is created `WAITLISTED` and `enrolled_count` is unchanged. The enrollment references the session it joins (`session_id`) and the enrolling member (`member_id`).

Cancelling an enrollment moves it to the terminal `CANCELLED` status and may be done only by its owning member. Cancelling an `ENROLLED` seat decrements the session's `enrolled_count` by one and then, if any `WAITLISTED` enrollment exists for that session, promotes the one with the earliest `created_at` from `WAITLISTED` to `ENROLLED`, which itself re-increments `enrolled_count` by one — a net-zero swap that hands the freed seat to the longest-waiting member. (Ordering is strictly by `created_at` ascending; no other tie-break is needed since each row's `created_at` is unique.) Cancelling a `WAITLISTED` seat simply closes that enrollment with no change to `enrolled_count` and no promotion, since no occupied seat was freed. The same waitlist promotion also runs, by the same earliest-`created_at` rule, whenever a spot otherwise frees on a session that has waiting members.

A `SCHEDULED` session may be cancelled by staff or by a store manager, moving the session to the terminal `CANCELLED` status; cancelling a session that is not `SCHEDULED` (already `CANCELLED`) is rejected with `ERR_INVALID_STATE` (409). Cancellation cascades: every enrollment of that session currently in `ENROLLED` or `WAITLISTED` transitions to `CANCELLED`, and the session's `enrolled_count` is set to 0. Enrollments may be fetched individually and listed, optionally filtered by `session_id` or `member_id`, and sessions themselves may be fetched or listed, optionally filtered by `coach_id` or `store_id`.

### 3.5. Race Events, Registration, and Packet Allocation

A store manager creates a race event with a `name`, an `event_date`, a finite `packet_capacity` (at least 1), and an `entry_fee_cents` (at least 0). The event opens in `OPEN` status with `packets_allocated` 0 and `active_registrations` 0. Two derived counters track the packet pool against all of the event's registrations: `active_registrations` is the number of registrations whose `packet_status` is either `RESERVED` or `ALLOCATED` (that is, not `RELEASED`), and `packets_allocated` is the number whose `packet_status` is `ALLOCATED`. The invariant is that `active_registrations` must never exceed `packet_capacity`. A manager may close the event, moving it from `OPEN` to the terminal `CLOSED` status, after which further registrations and allocations are refused; closing an event that is not `OPEN` (already `CLOSED`) is rejected with `ERR_INVALID_STATE` (409).

A registration carries two independent state dimensions. The `payment_status` dimension advances `UNPAID` → `PAID` → `REFUNDED`, and the `packet_status` dimension advances from `RESERVED` to either `ALLOCATED` or `RELEASED`; the two evolve independently, and the terminal condition is `packet_status` reaching `RELEASED` (a `RELEASED` registration may still carry `payment_status` `PAID` or `REFUNDED`).

A member registers for an event, which creates a registration owned via `member_id` and `event_id`, with `payment_status` `UNPAID` and `packet_status` `RESERVED`, snapshots the event's current `entry_fee_cents` onto the registration, initializes `amount_paid_cents` and `refund_cents` to 0, and increments the event's `active_registrations`. Three conditions guard registration, checked in this order: the parent event must be `OPEN`, else `ERR_EVENT_CLOSED` (409); the member must not already hold a non-`RELEASED` registration for this event, else `ERR_ALREADY_REGISTERED` (409); and the packet pool must not be exhausted — a registration is admitted only while `active_registrations` is strictly less than `packet_capacity`, and an attempt made when they are already equal is rejected with `ERR_EVENT_FULL` (409).

The owning member pays the entry fee, which moves `payment_status` from `UNPAID` to `PAID` and sets `amount_paid_cents` equal to the snapshotted `entry_fee_cents`; payment is permitted only while the registration is `UNPAID` and its packet is still `RESERVED`. A staff member then allocates the reserved packet, moving `packet_status` from `RESERVED` to `ALLOCATED` and incrementing the event's `packets_allocated`; allocation requires the registration's `payment_status` to be `PAID` — otherwise `ERR_REGISTRATION_NOT_PAID` (409) — and the parent event to still be `OPEN`, otherwise `ERR_EVENT_CLOSED` (409). Attempting to pay or allocate from a packet state where the transition is not defined yields `ERR_INVALID_STATE` (409); for allocation this packet-state check (the packet must be `RESERVED`) is evaluated first, before the payment and event-open checks, so an already-`ALLOCATED` or `RELEASED` packet yields `ERR_INVALID_STATE` even when the registration is unpaid or the event has closed, and the payment check precedes the event-open check.

The owning member may cancel a registration from either `RESERVED` or `ALLOCATED`, which sets `packet_status` to `RELEASED` and decrements the event's `active_registrations`, freeing a slot; if the packet had been `ALLOCATED`, the event's `packets_allocated` is also decremented. When the cancelled registration had been paid, the cancellation additionally refunds the member: `payment_status` becomes `REFUNDED`, `refund_cents` is set to `amount_paid_cents` minus a cancellation fee of 500 cents but never below zero (floored at 0), and that refund amount is credited to the member's `wallet_credit_cents`. Registrations may be fetched individually and listed, optionally filtered by `event_id` or `member_id`.

### 3.6. Retail Orders, Pricing, and Loyalty Accrual

A member opens a new order (`member_id`) as an empty cart in `CART` status with no `lines`, a `subtotal_cents` of 0, a `refund_cents` of 0, and null `provisional_discount_cents`, `provisional_total_cents`, `final_discount_cents`, and `final_total_cents` (the provisional pair is filled at placement, the final pair at fulfillment). While in `CART`, the member appends line items one at a time by supplying a `product_id` and a `qty`. Each appended line snapshots the product's current `price_cents` into `unit_price_cents` and records `line_gross_cents` as `unit_price_cents` multiplied by `qty`; after each append the order's `subtotal_cents` is recomputed as the sum of `line_gross_cents` over all lines. Each line item is thus an object with `product_id`, `qty`, `unit_price_cents`, and `line_gross_cents`. Appending a line returns HTTP 201 with the updated order object.

Placing an order is available to its owning member and requires the order to be in `CART` with at least one line, and every line's product must have `stock_on_hand` at least equal to that line's `qty`; placing an order that is not in `CART` yields `ERR_INVALID_STATE` (409), placing a `CART` order that has no lines is rejected with `ERR_VALIDATION` (400), and if any line is short the placement is rejected with `ERR_INSUFFICIENT_STOCK` (409). On success the order moves from `CART` to `PLACED`: for each line the product's `stock_on_hand` is decreased by the line quantity and its `stock_reserved` increased by the same amount, provisional pricing is computed (below), and `placed_at` is stamped from the logical clock.

**Order pricing** produces a discount and a total from the current lines and the member's standing at the instant it runs. First an effective discount rate is determined: the member's subscription gear/training rate — 10% for a `CLUB_BASIC` subscription, 20% for a `CLUB_PRO` subscription, but only while that subscription is `ACTIVE`, and 0% if the member has no `ACTIVE` subscription — is added to the member's loyalty rate (0% at `BRONZE`, 5% at `SILVER`, 10% at `GOLD`, 15% at `PLATINUM`), and the sum is capped at 35%. The discount is then computed per line and summed: each line's `line_gross_cents` is multiplied by that effective rate and rounded half-up to whole cents, and these rounded per-line discounts are added together to form the order's discount. The order total is `subtotal_cents` minus that summed discount. At placement this fills `provisional_discount_cents` and `provisional_total_cents` (the provisional variant), reading the member's `loyalty_tier` and subscription status as of placement.

Fulfillment is performed by staff on a `PLACED` order and moves it to the terminal `FULFILLED` status. For each line the product's `stock_reserved` is decreased by the line quantity (the units leave inventory for good). Pricing is recomputed as the **final variant** using the member's `loyalty_tier` and subscription state as of the fulfillment instant — which may differ from placement time if the subscription lapsed to `PAST_DUE` or the tier changed — writing `final_discount_cents` and `final_total_cents`; the same lines can therefore yield a `final_total_cents` different from `provisional_total_cents`. The logical clock is recorded in `fulfilled_at`. Fulfillment then awards loyalty: the member's `loyalty_points` is recomputed from scratch as the summed `final_total_cents` of all the member's orders now in `FULFILLED` status divided by 100 and rounded down (per §3.1 — flooring is applied once to the aggregate, not per order, so this may differ from simply adding a floored per-order figure), and the member's `loyalty_tier` is recomputed from that points total. Finally, a cascade runs: if that recomputation changed the member's `loyalty_tier`, every other order of the member still in `PLACED` status has its `provisional_discount_cents` and `provisional_total_cents` recomputed under the new tier, keeping each placed order's provisional pricing reconciled with the member's current standing.

A member may cancel their own order from either `CART` or `PLACED`. Cancelling a `PLACED` order releases its reservation — for each line the product's `stock_reserved` is decreased and its `stock_on_hand` increased by the line quantity — while cancelling a `CART` order releases nothing, since nothing was reserved. Either way the order moves to the terminal `CANCELLED` status. Fulfilling an order that is not `PLACED`, placing one that is not `CART`, or cancelling one already terminal each yields `ERR_INVALID_STATE` (409). Orders may be fetched by their owning member or a store manager and listed, optionally filtered by `member_id`.

### 3.7. Order Returns

A fulfilled order may be returned by its owning member, but only within the return window: the request must arrive no later than `fulfilled_at` plus 30 days as measured on the logical clock. A return requested after that window has closed is rejected with `ERR_RETURN_WINDOW_EXPIRED` (422), and returning an order that is not `FULFILLED` yields `ERR_INVALID_STATE` (409). On a successful return the order moves from `FULFILLED` to the terminal `RETURNED` status. A restocking fee of 15% of `final_total_cents` (rounded half-up to whole cents) is withheld, and the remainder — `final_total_cents` minus that rounded restocking fee — is recorded as the order's `refund_cents` and credited to the member's `wallet_credit_cents`. For each line the returned units are restocked: the product's `stock_on_hand` is increased by the line `qty`. The member may include an optional `reason` with the return.

### 3.8. Shoe Rotation and Mileage Reminders

When a member buys a pair of running shoes, they register it for mileage tracking by naming themselves (`member_id`) and the shoe product (`product_id`). The referenced product must be of `category` `SHOE`; registering against any other category is rejected with `ERR_PRODUCT_NOT_SHOE` (422). On creation the pair copies the product's `max_mileage_km` into its own `reminder_threshold_km`, starts with `total_mileage_km` of 0 and an empty `run_logs`, and opens in `ACTIVE` status.

The member logs runs against the pair by supplying a `distance_km` and an optional `logged_at` (when omitted, the current logical clock is used). Each run appends an entry — an object holding `distance_km` and `logged_at` — to `run_logs`, with the appended `distance_km` itself stored rounded half-up to one decimal place, and the pair's `total_mileage_km` is recomputed as the sum of those stored `distance_km` values across all logged runs, including the one just appended, expressed to one decimal place (rounded half-up). Appending a run log returns HTTP 201 with the updated shoe pair object. A mileage reminder fires when the accumulated distance reaches the threshold: while the pair is `ACTIVE`, if the recomputed `total_mileage_km` is greater than or equal to `reminder_threshold_km`, the pair transitions to `REORDER_DUE` (exactly reaching the threshold triggers it). Shoe pairs may be fetched individually and listed, optionally filtered by `member_id` or `product_id`.

### 3.9. Stores, Staff, and Product Catalog

The physical footprint and inventory are managed by store managers. A store is created with a `name`, a two-letter `region_code`, and an optional `session_room_count` (defaulting to 1, at least 1) that sets how many coaching rooms may host concurrent training sessions — the aggregate capacity used in §3.4. Staff are created against a store by supplying `store_id`, a `full_name`, a `role_type` of `FITTER`, `COACH`, or `BOTH`, and an optional `active` flag (defaulting to true) indicating whether the staff member currently accepts bookings. A store's staff roster can be read back by staff or managers.

Products form the catalog. Each is created with a unique `sku`, a `category` of `SHOE`, `NUTRITION`, `GEAR`, or `APPAREL`, a display `name`, a `price_cents` (at least 0), an optional starting `stock_on_hand` (defaulting to 0, never negative), and — for `SHOE` products — an optional `max_mileage_km` that becomes the mileage-reminder threshold copied onto shoe pairs (null for non-shoe products). The system also tracks `stock_reserved`, the units held by placed-but-not-yet-fulfilled orders, which initializes to 0 at creation and is never negative; on-hand and reserved counts move together through the order lifecycle described in §3.6. A store manager adjusts on-hand stock by posting a signed `delta` (positive for restock, negative for shrinkage); the product's `stock_on_hand` changes by that delta, and an adjustment that would drive `stock_on_hand` below zero is rejected as an invalid request with `ERR_VALIDATION` (400). Products and stores may be fetched by members, staff, and managers as part of the public catalog.

## 4. Endpoint Definitions

Creating a brand-new resource returns HTTP 201; all other successful operations — reads, state transitions, and other in-place modifications — return HTTP 200. Request bodies, response bodies, and side effects are not repeated here; refer to the §3 workflow narratives to reconstruct each operation's inputs and effects.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager |
| POST | `/stores` | Create a store | StoreManager |
| GET | `/stores/{id}` | Fetch one store | Member, Staff, StoreManager |
| GET | `/stores/{id}/staff` | List staff assigned to a store | Staff, StoreManager |
| POST | `/staff` | Create a fitter/coach | StoreManager |
| POST | `/members` | Register a new member (open registration) | Anonymous |
| GET | `/members/{id}` | Fetch one member | Member, Staff, StoreManager |
| GET | `/members/{id}/loyalty` | Computed loyalty standing (earned vs projected) | Member, StoreManager |
| GET | `/members/{id}/subscriptions` | List a member's subscriptions | Member, StoreManager |
| POST | `/members/{id}/subscription` | Create a subscription (supersedes prior; OCC-guarded) | Member |
| GET | `/subscriptions/{id}` | Fetch one subscription | Member, StoreManager |
| POST | `/subscriptions/{id}/activate` | Activate a PENDING subscription | Member |
| POST | `/subscriptions/{id}/renew` | Attempt a renewal charge | StoreManager |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Member |
| POST | `/products` | Create a catalog product | StoreManager |
| GET | `/products/{id}` | Fetch one product | Member, Staff, StoreManager |
| POST | `/products/{id}/inventory-adjustments` | Adjust on-hand stock by a signed delta | StoreManager |
| POST | `/fitting-appointments` | Book a gait-analysis/fitting appointment | Member |
| GET | `/fitting-appointments/{id}` | Fetch one appointment | Member, Staff, StoreManager |
| GET | `/fitting-appointments` | List appointments | Member, Staff, StoreManager |
| POST | `/fitting-appointments/{id}/complete` | Complete an appointment; charge fee | Staff |
| POST | `/fitting-appointments/{id}/cancel` | Cancel a scheduled appointment | Member |
| POST | `/training-sessions` | Schedule a group training session | StoreManager |
| GET | `/training-sessions/{id}` | Fetch one session | Member, Staff, StoreManager |
| GET | `/training-sessions` | List sessions | Member, Staff, StoreManager |
| POST | `/training-sessions/{id}/cancel` | Cancel a session; cascade to enrollments | Staff, StoreManager |
| POST | `/training-sessions/{id}/enrollments` | Enroll the member; ENROLLED or WAITLISTED | Member |
| GET | `/session-enrollments/{id}` | Fetch one enrollment | Member, Staff, StoreManager |
| GET | `/session-enrollments` | List enrollments | Member, Staff, StoreManager |
| POST | `/session-enrollments/{id}/cancel` | Cancel an enrollment; promote waitlist | Member |
| POST | `/race-events` | Create a race event | StoreManager |
| GET | `/race-events/{id}` | Fetch one event | Member, Staff, StoreManager |
| POST | `/race-events/{id}/close` | Close registration for an event | StoreManager |
| POST | `/race-events/{id}/registrations` | Register the member; reserve a packet | Member |
| GET | `/race-registrations/{id}` | Fetch one registration | Member, Staff, StoreManager |
| GET | `/race-registrations` | List registrations | Member, Staff, StoreManager |
| POST | `/race-registrations/{id}/pay` | Pay the entry fee | Member |
| POST | `/race-registrations/{id}/allocate` | Hand out the reserved packet | Staff |
| POST | `/race-registrations/{id}/cancel` | Cancel a registration; release and refund | Member |
| POST | `/orders` | Open a new cart order | Member |
| GET | `/orders/{id}` | Fetch one order | Member, StoreManager |
| GET | `/orders` | List orders | Member, StoreManager |
| POST | `/orders/{id}/lines` | Append a line item to a CART order | Member |
| POST | `/orders/{id}/place` | Place the order; reserve inventory, price | Member |
| POST | `/orders/{id}/fulfill` | Fulfill the order; finalize pricing, award points | Staff |
| POST | `/orders/{id}/cancel` | Cancel a CART or PLACED order | Member |
| POST | `/orders/{id}/return` | Return a FULFILLED order within the window | Member |
| POST | `/shoe-pairs` | Register a purchased shoe pair | Member |
| GET | `/shoe-pairs/{id}` | Fetch one shoe pair | Member, StoreManager |
| GET | `/shoe-pairs` | List shoe pairs | Member, StoreManager |
| POST | `/shoe-pairs/{id}/run-logs` | Append a run log; roll up mileage | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_STAFF_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SHOE_PAIR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SESSION_NOT_SCHEDULED` | 409 |
| `ERR_EVENT_CLOSED` | 409 |
| `ERR_REGISTRATION_NOT_PAID` | 409 |
| `ERR_APPOINTMENT_IN_PAST` | 422 |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_FITTER_UNAVAILABLE` | 409 |
| `ERR_COACH_UNAVAILABLE` | 409 |
| `ERR_SESSION_ROOM_CONFLICT` | 409 |
| `ERR_ALREADY_REGISTERED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_PRODUCT_NOT_SHOE` | 422 |
| `ERR_EVENT_FULL` | 409 |
