# Blow-Dry Bar API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Blow-Dry Bar platform, a back-of-house operating system for a Drybar-style styling business. The product coordinates four overlapping concerns that a busy salon juggles every hour: who is sitting in which chair, which stylist is serving them, what the appointment costs after memberships and prepaid credits are applied, and how the resulting money is split between stylist, tip pool, and house. A single appointment therefore touches a published style menu, optional add-ons such as updos and braids, the member's standing balances, chair and stylist availability windows, and — at settlement — commission and gratuity arithmetic.

The platform must also support the messier realities of the trade. Members buy memberships and prepaid credit packages and expect their balances to reconcile exactly. Large parties book bridal and group blocks that hold several chairs over a window and pass through revision rounds before they are confirmed. Walk-ins arrive late or never show, and the business needs to charge late fees, accrue no-show strikes, and suspend repeat offenders. Stylists sell retail product on the side and earn commission on it. Every one of these flows mutates shared balances, so the system favours immediate consistency: each computed field — a member's credit balance, a stylist's earnings, a product's stock — is reconciled the moment a triggering event lands, never lazily.

Because several roles act on the same resources from different angles, the API enforces role-based access control, optimistic concurrency on the resources most prone to lost updates, and a deterministic logical clock so that time-gated behaviour (no-shows, operating windows) can be tested precisely.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than the health probe must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401). The system recognises exactly four roles, spelled precisely as follows: `FrontDesk`, `FinanceManager`, `Stylist`, and `Member`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of these roles are tied to persisted entities, and two are opaque operator identities. When `X-User-Role` is `Stylist`, `X-User-ID` is the `id` of the acting `Stylist`; ownership checks on any appointment compare the appointment's `stylist_id` to `X-User-ID`, so a stylist may only start or complete an appointment assigned to them. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare the resource's `member_id` to `X-User-ID`, so a member may only book or cancel their own appointments and read their own records. When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque front-desk operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `FinanceManager`, `X-User-ID` is an opaque finance-operator identifier not tied to any persisted entity, recorded but never matched against an entity `id`.

Ownership violations are distinguished from plain role denials. A `Member` acting on an appointment that is not theirs is rejected with `ERR_NOT_OWNER` (HTTP 403); a `Stylist` attempting to start or complete an appointment to which they are not assigned is rejected with `ERR_NOT_ASSIGNED_STYLIST` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0 with a minimum of 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource — style services, add-ons, membership plans, members, stylists, chairs, appointments, appointment add-on attachments, event blocks, products, retail sales, and package purchases — carries a system-managed `id` formatted as a UUID with no type prefix, plus a `created_at` timestamp written in ISO 8601 UTC with three fractional digits. All of these entities are mutable, so each also carries an `updated_at` timestamp, refreshed on every change, and an integer `version` that begins at its initial value and increments by one with each mutation, including mutations to purely computed fields such as a member's balances or a stylist's earnings. The `version` field is the basis for the optimistic-concurrency protections described in §2.8.

### 2.5. Money, Time, and Rounding Conventions

All monetary amounts are integers denominated in whole cents; the system never stores fractional cents. Wherever a calculation multiplies a cent amount by a rate or a percentage, the result is rounded to a whole cent using the round-half-up convention (a residue of exactly half a cent rounds away from zero). Several calculations pin the *order* of rounding — for example, membership discounts are rounded per line before the lines are summed, never summed and then rounded — and those orderings are specified with the relevant workflow in §3; they are load-bearing because half-cent residues on multiple lines would otherwise drift the total.

Time is expressed throughout as **minutes-from-midnight UTC**, an integer in the range from 0 up to but not including 1440. Chair opening hours, stylist shifts, appointment start times, and event-block windows all use this representation. The server keeps a **logical clock** whose default at startup is `2026-01-01T00:00:00Z`; before any clock call the clock reads exactly this default and never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied instant, from which the system derives the `current_minute` as minutes-from-midnight UTC. The logical clock governs no-show eligibility and any other time-gated rule.

### 2.6. Derived-Field Reconciliation and Cascading Effects

Many fields are computed rather than supplied, and the system keeps them continuously reconciled. A member's `blowout_credit_balance`, `prepay_balance_cents`, `no_show_strikes`, and `status`; a stylist's `earned_commission_cents` and `earned_tips_cents`; a product's `stock_qty`; an appointment's pricing and split fields; and an event block's `deposit_cents` and `deposit_paid_cents` are all derived values that the system recomputes the instant a triggering event occurs. When one operation legitimately changes more than one entity — settling an appointment, for instance, both debits a member's prepay balance and lifts a stylist's earnings — every affected entity is reconciled, and each such mutation refreshes that entity's `updated_at` and increments its `version`. The specific cascade for each operation is described with its workflow in §3.

### 2.7. Left-to-Right Existence Validation

Requests that reference resources by path id or by foreign-key body field validate those references for existence in a fixed left-to-right order before any business rule runs. For a booking, the order is `member_id`, then `chair_id`, then `stylist_id`, then `style_service_id`, then `event_block_id` (when supplied); attachment and retail flows extend the same idea to `add_on_id` and `product_id`. The first reference that does not resolve aborts the request with the corresponding not-found error — `ERR_MEMBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`, `ERR_STYLIST_NOT_FOUND`, `ERR_STYLE_SERVICE_NOT_FOUND`, `ERR_EVENT_BLOCK_NOT_FOUND`, `ERR_ADD_ON_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, or `ERR_PACKAGE_NOT_FOUND` — each carrying HTTP 404.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to prove they are acting on a current view of a parent resource, and several state-transition operations on versioned entities do the same. In each case the caller supplies an expected version field, and a mismatch with the server's current `version` for that parent is rejected with `ERR_STALE_VERSION` (HTTP 412). These checks are framed entirely in terms of stale versions, not request timing: the rejection fires whenever the client's last-observed version has been overtaken by an intervening write, regardless of how far apart the two writes occurred.

Booking an appointment into an event block requires `expected_event_block_version` to match that event block's current `version`. If a prior writer has reopened or cancelled the block — legitimately superseding its reserved chairs and window — the client's view is stale and the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). A standalone booking that carries no `event_block_id` carries no version field and is not subject to this check.

Purchasing a prepaid credit package requires `expected_member_version` to match the target member's current `version`. If another writer has granted credits, refunded a prior package, or reinstated the member since the client last read it — each of which legitimately changes the credit or prepay ledger — the purchase is rejected with `ERR_STALE_VERSION` (HTTP 412). The member-reinstate, package-refund, and every event-block lifecycle transition (confirm, reopen, close, cancel) likewise require their respective expected-version field (`expected_member_version` or `expected_event_block_version`) and reject a mismatch with the same `ERR_STALE_VERSION` (HTTP 412). Endpoints not enumerated here take no version field.

### 2.9. Validation Ordering

When several checks could fault a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or malformed header yields `ERR_MISSING_AUTH_CONTEXT` (401) before anything else. Role authorisation comes second, yielding `ERR_FORBIDDEN_ROLE` (403). Existence of every referenced resource comes third, yielding the appropriate 404 from §2.7. Request well-formedness comes fourth — required fields present, enum values legal, integers within their declared ranges (for example, durations that must be multiples of five) — yielding `ERR_INVALID_REQUEST` (HTTP 422). Ownership and assignment checks come fifth, yielding `ERR_NOT_OWNER` or `ERR_NOT_ASSIGNED_STYLIST` (403). State preconditions come sixth, yielding the relevant 409 state error. Only after all of these pass does the system evaluate the domain-specific temporal, capacity, and fiscal rules described in §3 (operating windows, chair and stylist overlaps, block membership, stock, and prepay sufficiency). A reader implementing any endpoint should treat this ordering as authoritative: an earlier-priority fault must surface before a later one is even evaluated.

## 3. Business Logic & Workflows

### 3.1. Configuring the Menu: Style Services and Add-Ons

The salon's bookable catalogue begins with **style services**. A `FrontDesk` operator publishes a style service with a `name`, a `base_duration_minutes` value giving the chair-time the service occupies, and a `base_price_cents` list price charged before any discount. The duration must be a multiple of five and lie between 15 and 240 minutes inclusive, and the price must be zero or greater. Each service also declares how many membership or package blowout credits it consumes through `blowout_credit_cost`, which defaults to 1 and must be zero or greater, and whether it is currently bookable through `active`, which defaults to true. An inactive service rejects new appointments.

Alongside services sit **add-ons** — the updos, braids, and extensions a member can attach to a booking. An add-on is created by a `FrontDesk` operator with a `name`, a `category` that must be one of `UPDO`, `BRAID`, or `EXTENSION`, an `extra_duration_minutes` value (a multiple of five from 0 to 120 inclusive) that lengthens chair-time, and a `price_cents` surcharge of zero or greater applied before discount. Two flags govern its commercial behaviour: `discount_eligible`, defaulting to false, decides whether the membership discount may touch this add-on's line, and `active`, defaulting to true, decides whether it can be attached at all. Supplying any out-of-range value, illegal enum, or duration that is not a multiple of five faults the request with `ERR_INVALID_REQUEST`.

### 3.2. Membership Plans, Members, and the Two Balances

A `FinanceManager` configures **membership plans**. A plan names a `tier` of `BASIC`, `PLUS`, or `VIP`, a recurring `monthly_fee_cents` of zero or greater, the number of `included_blowout_credits` granted per cycle (zero or greater), and a `member_discount_pct` between 0 and 1 inclusive that discounts the service and any discount-eligible add-ons. The `active` flag, defaulting to true, controls whether new members may enrol on the plan.

A `FrontDesk` operator registers a **member** with a `full_name` and an `email` that must be unique across all members. Optionally a `membership_plan_id` ties the member to a plan; when omitted (defaulting to null) the member is treated as a walk-in non-member. On registration the member's `status` is `ACTIVE`, the `prepay_balance_cents` is 0, the `no_show_strikes` count is 0, and if a plan was supplied the `blowout_credit_balance` is seeded to that plan's `included_blowout_credits`.

A member carries two balances that the system reconciles continuously. The **blowout credit balance** equals the credits granted to the member — the membership plan's per-cycle grant if they hold a plan, plus the `credits_purchased` summed across all `ACTIVE` package purchases — minus the credits consumed, where consumption is the sum of `credits_applied` across the member's appointments that are not `CANCELLED`. A `NO_SHOW` appointment retains its applied credits as forfeited and so stays counted as consumed; a `CANCELLED` appointment refunds its credits, dropping out of the consumed total. The balance is an integer that is never negative, and when a booking draws credits it draws from the membership grant first and only then from package credits. The **prepay balance** is a stored-value ledger in cents: it is the sum of top-ups recorded against the member, minus the sum of `service_charge_cents` over the member's settled prepay appointments, plus the sum of `price_cents` refunded from any refunded package purchases, plus refunds released back from cancelled prepay appointment holds. It starts at 0 and is never negative.

A `FrontDesk` or `FinanceManager` operator tops up the prepay balance by supplying an `amount_cents`, which is added to `prepay_balance_cents` and increments the member's `version` by one. Topping up is the canonical way stored value enters the ledger.

### 3.3. Stylists and Chairs: The Capacity Resources

A `FrontDesk` operator creates a **stylist** with a `full_name`, a `commission_tier` of `JUNIOR`, `SENIOR`, or `MASTER`, and a shift defined by `shift_start_minute` (from 0 up to but not including 1440) and `shift_end_minute`, which must be strictly greater than the start and at most 1440. The `active` flag, defaulting to true, controls whether the stylist may be assigned. On creation both `earned_commission_cents` and `earned_tips_cents` begin at 0; these are computed fields that the system later reconciles from settled appointments and retail sales. A stylist's `earned_commission_cents` is the sum of `commission_amount_cents` over their settled appointments, reduced by any retail commission reversed when a sale they were credited with is voided; `earned_tips_cents` is the sum of `stylist_tip_cents` over their settled appointments.

A `FrontDesk` operator creates a **chair** (a styling station) with a `label`, an `open_minute` (from 0 up to but not including 1440), and a `close_minute` strictly greater than the open and at most 1440. Each chair also carries a `turnover_buffer_minutes` cleaning buffer, defaulting to 10 and constrained from 0 to 60 inclusive, that must elapse after each appointment before the next one may begin on that chair. The `active` flag, defaulting to true, controls bookability.

### 3.4. Booking an Appointment

Booking is the system's busiest operation, and both `FrontDesk` and `Member` may perform it; when a `Member` books, `X-User-ID` must equal the supplied `member_id`. A booking request supplies a `member_id`, a `chair_id`, a `stylist_id`, a `style_service_id`, a `start_minute` (from 0 up to but not including 1440, on the same logical day as the clock), and a `payment_method` of either `CREDIT` or `PREPAY`. Optionally it supplies an `event_block_id` to attach the booking to an event block, in which case it must also carry `expected_event_block_version` for the optimistic-concurrency check described in §2.8. A new appointment is born with `lifecycle_status` of `BOOKED` and `settlement_status` of `UNSETTLED`.

On booking the system computes the schedule and the price. The `scheduled_duration_minutes` equals the style service's `base_duration_minutes` plus the sum of `extra_duration_minutes` over every attached add-on, and the `end_minute` equals `start_minute` plus `scheduled_duration_minutes`. Several constraints then guard the slot, evaluated after the existence, well-formedness, and state checks of §2.9. The service must be active and the subject member must be `ACTIVE`; an inactive service or add-on (or attempting to attach one) faults with `ERR_SERVICE_OR_ADDON_INACTIVE` (409), and a suspended member faults with `ERR_MEMBER_SUSPENDED` (409). The appointment window must lie within both the chair's operating hours, the half-open interval from `open_minute` up to but not including `close_minute`, and the stylist's shift, the half-open interval from `shift_start_minute` up to but not including `shift_end_minute`; a window outside either faults with `ERR_OUTSIDE_OPERATING_WINDOW` (422). The chair must be free: the half-open interval from `start_minute` up to but not including `end_minute` plus the chair's `turnover_buffer_minutes` must not overlap any non-terminal appointment on that chair — the buffer trails each appointment — and an overlap faults with `ERR_CHAIR_DOUBLE_BOOKED` (409). The stylist must be free too: the half-open interval from `start_minute` up to but not including `end_minute` must not overlap any non-terminal appointment for that stylist, with no buffer, so back-to-back bookings are allowed; an overlap faults with `ERR_STYLIST_DOUBLE_BOOKED` (409).

Event-block bookings carry two extra rules. If an `event_block_id` is supplied, the chosen `chair_id` must be among that block's `reserved_chair_ids` and the appointment window must fall within the block window, and the block must be in `HOLD` or `CONFIRMED` status; a chair or window that does not match faults with `ERR_BLOCK_CHAIR_OR_WINDOW_MISMATCH` (422). Conversely, a standalone booking — one without a matching `event_block_id` — that lands on a chair reserved by a `CONFIRMED` block during that block's window is rejected with `ERR_CHAIR_RESERVED_FOR_BLOCK` (409), because a confirmed block holds its chairs exclusively. When the booking does attach to an event block and passes the version check, the block's `version` increments by one.

### 3.5. Pricing a Booking: Discounts and Blowout Credits

Pricing runs at booking time and again whenever an add-on is attached or removed. The pre-discount `list_amount_cents` is the style service's `base_price_cents` plus the sum of each attached add-on's `captured_price_cents`. The membership `discount_cents` is computed per line and then summed, in that pinned order. If the member has no plan, the discount is zero. Otherwise, take the plan's `member_discount_pct` as the rate: the service line always discounts, contributing the service's `base_price_cents` multiplied by the rate and rounded half-up to a whole cent; each attached add-on contributes its `captured_price_cents` multiplied by the rate and rounded half-up to a whole cent if the add-on is discount-eligible, and contributes zero otherwise. The `discount_cents` is the sum of those individually rounded line discounts — never the rate applied to a combined total — and that distinction matters whenever two discount-eligible lines carry half-cent residues. Each appointment add-on attachment records its own per-line `discount_applied_cents` (zero when the add-on is not discount-eligible or the member has no plan).

The net amount after discount is `list_amount_cents` minus `discount_cents`. Blowout credits then reduce the cash charge, but they cover only the discounted **service** line, never add-ons or fees. The number of `credits_applied` is the lesser of the member's current `blowout_credit_balance` and the service's `blowout_credit_cost`. If that applied count reaches the service's `blowout_credit_cost` and the cost is greater than zero, the discounted service line is fully covered: the system subtracts the discounted service line — the service's `base_price_cents` minus the per-line rounded service discount — from the net amount, and the remainder is the `service_charge_cents`. If the member cannot muster the full credit cost (or the service costs zero credits), then `credits_applied` is zero and the `service_charge_cents` is simply the net amount after discount. A member with too few credits is never rejected for it; they apply zero credits and pay cash. The `service_charge_cents` computed here is the base charge; any late fee assessed at check-in is added on top of it afterward. When `payment_method` is `PREPAY`, a hold is placed against the member's prepay balance at booking.

### 3.6. Attaching Add-Ons After Booking

A `FrontDesk` operator may attach an add-on to an appointment while it is still `BOOKED` by supplying the `add_on_id`. The attachment is recorded as an **appointment add-on** that snapshots the add-on's price into `captured_price_cents` and its duration into `captured_duration_minutes` at attach time, so later edits to the catalogue do not retroactively change a booked appointment. Attaching re-runs the schedule computation — `scheduled_duration_minutes` and `end_minute` are recomputed — and the full pricing computation of §3.5, and it re-validates the chair overlap against the new `end_minute`, since a longer service may now collide with a later booking or the trailing buffer. Attaching an inactive add-on faults with `ERR_SERVICE_OR_ADDON_INACTIVE` (409). The attachment carries `appointment_id` and `add_on_id` as its links.

### 3.7. The Appointment Lifecycle: Check-In Through Completion

An appointment moves along its `lifecycle_status` axis through `BOOKED`, `CHECKED_IN`, `IN_SERVICE`, and finally `COMPLETED`, with `NO_SHOW` and `CANCELLED` as alternative terminal outcomes.

Checking in is a `FrontDesk` action that advances `BOOKED → CHECKED_IN`. It requires the appointment to be `BOOKED` (otherwise `ERR_APPOINTMENT_NOT_BOOKED`, 409) and the subject member to be `ACTIVE` (otherwise `ERR_MEMBER_SUSPENDED`, 409). The caller records the `arrival_status`, which on check-in must be `ON_TIME` or `LATE` (the no-show case has its own path), and may record `late_minutes`; both values are written onto the appointment. When the arrival is `LATE` and the recorded `late_minutes` exceeds the grace allowance, a late fee is computed and added to the appointment's `service_charge_cents`. The grace allowance is ten minutes: arriving ten minutes late or fewer incurs no fee, while eleven minutes late or more does. For a billable late arrival the fee is one dollar (100 cents) for each minute beyond the ten-minute grace — that is, the billable minutes are `late_minutes` minus ten — capped at twenty-five dollars (2,500 cents); the fee added is the lesser of the per-minute charge and that cap. If a block appointment is the one being checked in, its parent event block cascades from `CONFIRMED` to `CHECKED_IN`.

Starting service is a `Stylist` action that advances `CHECKED_IN → IN_SERVICE`. It requires the appointment to be `CHECKED_IN` (otherwise `ERR_APPOINTMENT_NOT_CHECKED_IN`, 409) and the acting stylist's `X-User-ID` to equal the appointment's `stylist_id` (otherwise `ERR_NOT_ASSIGNED_STYLIST`, 403). Completing service is likewise a `Stylist` action that advances `IN_SERVICE → COMPLETED`, requiring the appointment to be `IN_SERVICE` (otherwise `ERR_APPOINTMENT_NOT_IN_SERVICE`, 409) and the same stylist-assignment check. Completion makes the appointment eligible for settlement, but the `settlement_status` remains `UNSETTLED` until a settle action runs.

### 3.8. No-Shows, Strikes, and Suspension

When a member fails to arrive, a `FrontDesk` operator records a no-show, advancing the appointment `BOOKED → NO_SHOW`. This is permitted only while the appointment is `BOOKED` (otherwise `ERR_APPOINTMENT_NOT_BOOKED`, 409) and only once the logical clock has reached the appointment's start, meaning the clock's `current_minute` is at or after the appointment's `start_minute`; calling it before then is rejected with `ERR_NO_SHOW_TOO_EARLY` (409). Recording a no-show sets `arrival_status` to `NO_SHOW`, increments the member's `no_show_strikes` by one, voids the appointment's settlement so no commission or charge is captured (its `settlement_status` becomes `VOIDED`), retains the blowout `credits_applied` as forfeited rather than refunding them, and releases the chair's time window for re-booking.

A member's `no_show_strikes` is the running count of their appointments that are in `NO_SHOW` lifecycle status with `arrival_status` of `NO_SHOW`, less any resets from reinstatement. When this count reaches the suspension threshold of three strikes, the member's `status` cascades to `SUSPENDED`: two strikes leave the member `ACTIVE`, and the third strike (a count of three or more) suspends them. A suspended member can no longer be checked in for new appointments. A `FrontDesk` operator reinstates a suspended member, advancing `SUSPENDED → ACTIVE`; this requires the member to currently be `SUSPENDED` (otherwise `ERR_MEMBER_NOT_SUSPENDED`, 409) and requires `expected_member_version` to match the member's current `version` (otherwise `ERR_STALE_VERSION`, 412). Reinstatement resets `no_show_strikes` to zero, returns `status` to `ACTIVE`, and increments the member's `version` by one.

### 3.9. Cancelling an Appointment

Either a `FrontDesk` operator or the owning `Member` may cancel an appointment, advancing it to `CANCELLED` from either `BOOKED` or `CHECKED_IN`. Cancellation requires the appointment to be in `BOOKED` or `CHECKED_IN` (otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE`, 409); when the actor is a `Member`, their `X-User-ID` must equal the appointment's `member_id` (otherwise `ERR_NOT_OWNER`, 403). Cancellation is compensating: the blowout `credits_applied` are refunded back to the member's `blowout_credit_balance`, any `PREPAY` hold is released back to the member's `prepay_balance_cents`, the appointment's `settlement_status` becomes `VOIDED`, and the chair's time window is released. If the appointment belonged to an event block, freeing its slot does not disturb the block's `party_size` accounting.

### 3.10. Settlement: Tips, Commission, and the House Split

Settlement runs along the appointment's second, independent state axis. The `settlement_status` axis runs `UNSETTLED → SETTLED`, with `VOIDED` reached only by the no-show and cancel paths described above. A `FinanceManager` settles a completed appointment, optionally supplying a `tip_cents` amount (zero or greater, defaulting to 0). Settlement requires, across the two axes, that the appointment's `lifecycle_status` is `COMPLETED` (otherwise `ERR_APPOINTMENT_NOT_COMPLETED`, 409) and its `settlement_status` is `UNSETTLED` (otherwise `ERR_ALREADY_SETTLED`, 409). When `payment_method` is `PREPAY`, the member's `prepay_balance_cents` must be at least the appointment's `service_charge_cents`, or the settlement is rejected with `ERR_INSUFFICIENT_PREPAY` (HTTP 402).

Settlement splits the tip and the service charge. The tip is divided into a direct stylist share and a shared-pool share. For a standalone appointment — one whose `event_block_id` is null — the serving stylist keeps seventy percent of the tip directly, with the remaining thirty percent routed to the pool; the `stylist_tip_cents` is `tip_cents` multiplied by 0.70 and rounded half-up to a whole cent, and the `tip_pool_cents` is whatever remains of the tip after subtracting that direct share, taken as the exact remainder with no second rounding. For an event-block appointment — one whose `event_block_id` is not null — the auto-gratuity context routes a larger share to the pool: the stylist keeps fifty percent directly and fifty percent goes to the pool, so `stylist_tip_cents` is `tip_cents` multiplied by 0.50 rounded half-up, and `tip_pool_cents` is the exact remainder.

Commission is selected by the stylist's tier. The base rate is thirty-five percent for a `JUNIOR` stylist, forty-five percent for a `SENIOR`, and fifty-five percent for a `MASTER`. For an event-block appointment, the effective rate is the lesser of the stylist's base rate and the event rate cap of forty percent — so a `SENIOR` or `MASTER` working an event is capped at forty percent while a `JUNIOR` keeps thirty-five — and for a standalone appointment the effective rate is simply the base rate. The `commission_amount_cents` is the appointment's final `service_charge_cents` (including any late fee already folded in at check-in) multiplied by the effective rate and rounded half-up to a whole cent, and the `house_amount_cents` is the exact remainder of the service charge after subtracting the commission, so the two always sum back to the service charge precisely. Settlement advances `settlement_status` to `SETTLED`. If the appointment was `PREPAY`, the member's `prepay_balance_cents` is debited by the `service_charge_cents`. The serving stylist's `earned_commission_cents` and `earned_tips_cents` are then reconciled to fold in this newly settled appointment.

### 3.11. Event, Group, and Bridal Blocks

Large parties are handled through **event blocks**, which hold several chairs over a window and pass through revision rounds before they go live. A `FrontDesk` operator creates a block by naming an `organizer_member_id`, a `block_type` of `GROUP` or `BRIDAL`, a `window_start_minute` (from 0 up to but not including 1440) and a `window_end_minute` strictly greater than the start and at most 1440, an array of `reserved_chair_ids` held exclusively for the block during that window, a `party_size` from 2 to 20 inclusive, and an optional `gratuity_pct` between 0 and 1 inclusive that defaults to 0.20 and feeds the auto-gratuity routing at settlement. On creation the block enters `HOLD` status with `deposit_paid_cents` at 0, and its required `deposit_cents` is computed: a deposit of twenty dollars (2,000 cents) per expected head — `party_size` multiplied by 2,000 — for a `GROUP` block, and the same per-head amount plus a one-hundred-dollar (10,000-cent) surcharge for a `BRIDAL` block.

Deposits are recorded incrementally. A `FrontDesk` or `FinanceManager` operator records a deposit payment by supplying an `amount_cents`, which is added to `deposit_paid_cents` and increments the block's `version` by one. The block's lifecycle is cyclic between revision and confirmation. Confirming a held block is a `FrontDesk` action advancing `HOLD → CONFIRMED`; it requires the block to be in `HOLD` (otherwise `ERR_EVENT_BLOCK_NOT_HOLD`, 409), requires `deposit_paid_cents` to be at least `deposit_cents` (otherwise `ERR_DEPOSIT_NOT_MET`, 409), requires at least two appointments referencing the block to be in `BOOKED` status (otherwise `ERR_BLOCK_UNDERFILLED`, 409), and requires `expected_event_block_version` to match the current `version` (otherwise `ERR_STALE_VERSION`, 412). Confirmation locks the reserved chairs for the window and increments the block's `version` by one.

A confirmed block can be reopened for revision by a `FrontDesk` operator, advancing `CONFIRMED → HOLD`; this requires the block to be `CONFIRMED` (otherwise `ERR_EVENT_BLOCK_NOT_CONFIRMED`, 409), requires that no appointment in the block has yet reached `CHECKED_IN`, `IN_SERVICE`, or `COMPLETED` (otherwise `ERR_BLOCK_IN_PROGRESS`, 409), and requires `expected_event_block_version` to match the current `version` (otherwise `ERR_STALE_VERSION`, 412); the chairs remain reserved and the `version` increments by one. These reopen preconditions are evaluated in the order listed, so the `CONFIRMED` status check takes precedence over the in-progress check: a block that is no longer `CONFIRMED` — including one the system has already advanced to `CHECKED_IN` because its first appointment checked in — is rejected with `ERR_EVENT_BLOCK_NOT_CONFIRMED`, not `ERR_BLOCK_IN_PROGRESS`. Once the first block appointment checks in, the system itself advances the block `CONFIRMED → CHECKED_IN`, marking it in progress and disabling further reopening. Closing a block is a `FrontDesk` action advancing `CHECKED_IN → CLOSED`; it requires the block to be `CHECKED_IN` (otherwise `ERR_EVENT_BLOCK_NOT_CLOSEABLE`, 409), requires every block appointment to be in a terminal `lifecycle_status` of `COMPLETED`, `NO_SHOW`, or `CANCELLED` (otherwise `ERR_BLOCK_HAS_OPEN_APPOINTMENTS`, 409), and requires `expected_event_block_version` to match (otherwise `ERR_STALE_VERSION`, 412); closing releases the reserved chairs and increments the `version` by one.

Cancelling a block is a `FrontDesk` action permitted from either `HOLD` or `CONFIRMED` (otherwise `ERR_EVENT_BLOCK_NOT_CANCELLABLE`, 409), and it too requires `expected_event_block_version` to match (otherwise `ERR_STALE_VERSION`, 412). Cancellation cascades: every `BOOKED` or `CHECKED_IN` appointment in the block is itself cancelled, each running its own cancellation side effects — credit refund, prepay-hold release, settlement voiding, and chair release. The block's reserved chairs are released, the `deposit_paid_cents` is retained as forfeited rather than refunded, and the block's `version` increments by one. Block appointments are reachable through a block-scoped appointment listing, which validates the block id before returning the appointments that carry its `event_block_id`.

### 3.12. Retail Product and Sales

The salon sells **products** at the front desk. A `FrontDesk` or `FinanceManager` operator creates a product with a unique `sku`, a `name`, a `unit_price_cents` of zero or greater, an `initial_stock` quantity, and an optional `retail_commission_pct` between 0 and 1 inclusive that defaults to 0.10 and sets the stylist's commission rate on attributed sales. The product's `stock_qty` begins at the supplied `initial_stock`; thereafter it equals the initial stock plus all restocks minus the total `quantity` sold across non-voided sales. A `FrontDesk` or `FinanceManager` operator restocks by supplying a `quantity`, raising `stock_qty` accordingly.

A `FrontDesk` operator records a **retail sale** by supplying a `product_id`, the buyer's `member_id`, a `quantity` of at least one, and optionally an `attributed_stylist_id` to credit a stylist with the commission. The sale's `quantity` may not exceed the product's `stock_qty` at sale time, or it is rejected with `ERR_INSUFFICIENT_STOCK` (409). A sale is born `SOLD`. Its `gross_cents` is the product's `unit_price_cents` multiplied by the `quantity`. If no stylist is attributed, the `retail_commission_cents` is zero; otherwise it is the `gross_cents` multiplied by the product's `retail_commission_pct`, rounded half-up to a whole cent. Recording the sale decrements the product's `stock_qty` by the quantity and, when a stylist is attributed, lifts that stylist's `earned_commission_cents`. This retail commission is conceptually the same payout as service commission but computed on a different basis — a flat product rate on the sale's gross rather than a tiered rate on a service charge — so the same dollar gross can produce a different commission than a service of equal value would.

A `FrontDesk` operator voids a sale, advancing `SOLD → VOIDED`; this requires the sale to be `SOLD` (otherwise `ERR_SALE_NOT_VOIDABLE`, 409). Voiding restores the product's `stock_qty` by the sale's `quantity` and reverses the `retail_commission_cents`, recomputing the attributed stylist's `earned_commission_cents` downward.

### 3.13. Prepaid Credit Packages

Beyond memberships, members can buy **package purchases** — prepaid bundles of blowout credits. A `FrontDesk` or `FinanceManager` operator records a purchase for a `member_id` with `credits_purchased` (at least one) and the `price_cents` paid (zero or greater), and must supply `expected_member_version` matching the member's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (412), since an intervening grant, refund, or reinstatement would make the client's view of the member's ledger stale. A purchase is born `ACTIVE`, and it raises the member's `blowout_credit_balance` by `credits_purchased` and increments the member's `version` by one.

A `FinanceManager` refunds an unused package, advancing `ACTIVE → REFUNDED`. The refund requires the package to be `ACTIVE` (otherwise `ERR_PACKAGE_NOT_REFUNDABLE`, 409); it requires the member's `blowout_credit_balance` to be at least the package's `credits_purchased`, meaning the purchased credits are still unconsumed (otherwise `ERR_CREDITS_ALREADY_USED`, 409); and it requires `expected_member_version` to match the member's current `version` (otherwise `ERR_STALE_VERSION`, 412). On refund the member's `blowout_credit_balance` is decremented by `credits_purchased`, so the package's net credit contribution returns to zero, the member's `prepay_balance_cents` is credited by the package's `price_cents` as stored-value refund, and the member's `version` increments by one.

### 3.14. The Logical Clock

A `FrontDesk` or `FinanceManager` operator drives the server's logical clock for testing and operations by supplying a target instant as `to_iso8601`. The response reports the resulting `current_utc` and the derived `current_minute`. Advancing the clock is what makes a no-show eligible (the clock must reach an appointment's `start_minute`) and governs any other time-gated rule. The health probe is the only unauthenticated endpoint and simply reports liveness.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, balance top-ups, deposits, restocks, and settlements — return `200 OK`. The logical-clock and health endpoints also return `200 OK`. Request and response bodies are described in the §3 narratives; the table below lists only method, path, purpose, and the roles permitted to call each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FrontDesk, FinanceManager |
| GET | `/_health` | Liveness probe (no auth) | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/style-services` | Create a style menu item | FrontDesk |
| GET | `/style-services` | List style menu items | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/style-services/{id}` | Get a style menu item | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/add-ons` | Create an add-on | FrontDesk |
| GET | `/add-ons` | List add-ons | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/add-ons/{id}` | Get an add-on | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/membership-plans` | Create a membership plan | FinanceManager |
| GET | `/membership-plans` | List membership plans | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/membership-plans/{id}` | Get a membership plan | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/members` | Register a member | FrontDesk |
| GET | `/members` | List members | FrontDesk, FinanceManager |
| GET | `/members/{id}` | Get a member | FrontDesk, FinanceManager, Member |
| POST | `/members/{id}/prepay` | Top up a member's prepay balance | FrontDesk, FinanceManager |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | FrontDesk |
| POST | `/stylists` | Create a stylist | FrontDesk |
| GET | `/stylists` | List stylists | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/stylists/{id}` | Get a stylist | FrontDesk, FinanceManager, Stylist |
| POST | `/chairs` | Create a chair | FrontDesk |
| GET | `/chairs` | List chairs | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/chairs/{id}` | Get a chair | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/event-blocks` | Create an event/group/bridal block | FrontDesk |
| GET | `/event-blocks` | List event blocks | FrontDesk, FinanceManager |
| GET | `/event-blocks/{id}` | Get an event block | FrontDesk, FinanceManager, Member |
| GET | `/event-blocks/{id}/appointments` | List appointments in a block | FrontDesk, FinanceManager, Member |
| POST | `/event-blocks/{id}/deposit` | Record a deposit payment | FrontDesk, FinanceManager |
| POST | `/event-blocks/{id}/confirm` | Confirm a held block | FrontDesk |
| POST | `/event-blocks/{id}/reopen` | Reopen a confirmed block | FrontDesk |
| POST | `/event-blocks/{id}/close` | Close a block | FrontDesk |
| POST | `/event-blocks/{id}/cancel` | Cancel a block | FrontDesk |
| POST | `/appointments` | Book an appointment | FrontDesk, Member |
| GET | `/appointments` | List appointments | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/appointments/{id}` | Get an appointment | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/appointments/{id}/add-ons` | Attach an add-on to an appointment | FrontDesk |
| GET | `/appointments/{id}/add-ons` | List add-ons on an appointment | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/appointment-add-ons` | List appointment add-on attachments | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/appointment-add-ons/{id}` | Get an appointment add-on attachment | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/appointments/{id}/check-in` | Check in an appointment | FrontDesk |
| POST | `/appointments/{id}/start` | Start service | Stylist |
| POST | `/appointments/{id}/complete` | Complete service | Stylist |
| POST | `/appointments/{id}/no-show` | Mark an appointment as no-show | FrontDesk |
| POST | `/appointments/{id}/cancel` | Cancel an appointment | FrontDesk, Member |
| POST | `/appointments/{id}/settle` | Settle a completed appointment | FinanceManager |
| POST | `/products` | Create a retail product | FrontDesk, FinanceManager |
| GET | `/products` | List products | FrontDesk, FinanceManager, Stylist, Member |
| GET | `/products/{id}` | Get a product | FrontDesk, FinanceManager, Stylist, Member |
| POST | `/products/{id}/restock` | Add units to a product's stock | FrontDesk, FinanceManager |
| POST | `/retail-sales` | Record a retail sale | FrontDesk |
| GET | `/retail-sales` | List retail sales | FrontDesk, FinanceManager, Stylist |
| GET | `/retail-sales/{id}` | Get a retail sale | FrontDesk, FinanceManager, Stylist |
| POST | `/retail-sales/{id}/void` | Void a retail sale | FrontDesk |
| POST | `/package-purchases` | Buy a prepaid blowout-credit package | FrontDesk, FinanceManager |
| GET | `/package-purchases` | List package purchases | FrontDesk, FinanceManager, Member |
| GET | `/package-purchases/{id}` | Get a package purchase | FrontDesk, FinanceManager, Member |
| POST | `/package-purchases/{id}/refund` | Refund an unused package | FinanceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_ASSIGNED_STYLIST` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CHAIR_NOT_FOUND` | 404 |
| `ERR_STYLIST_NOT_FOUND` | 404 |
| `ERR_STYLE_SERVICE_NOT_FOUND` | 404 |
| `ERR_ADD_ON_NOT_FOUND` | 404 |
| `ERR_EVENT_BLOCK_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_SALE_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 |
| `ERR_APPOINTMENT_NOT_CHECKED_IN` | 409 |
| `ERR_APPOINTMENT_NOT_IN_SERVICE` | 409 |
| `ERR_APPOINTMENT_NOT_COMPLETED` | 409 |
| `ERR_APPOINTMENT_NOT_CANCELLABLE` | 409 |
| `ERR_NO_SHOW_TOO_EARLY` | 409 |
| `ERR_ALREADY_SETTLED` | 409 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_MEMBER_NOT_SUSPENDED` | 409 |
| `ERR_EVENT_BLOCK_NOT_HOLD` | 409 |
| `ERR_EVENT_BLOCK_NOT_CONFIRMED` | 409 |
| `ERR_EVENT_BLOCK_NOT_CLOSEABLE` | 409 |
| `ERR_EVENT_BLOCK_NOT_CANCELLABLE` | 409 |
| `ERR_BLOCK_IN_PROGRESS` | 409 |
| `ERR_DEPOSIT_NOT_MET` | 409 |
| `ERR_BLOCK_UNDERFILLED` | 409 |
| `ERR_BLOCK_HAS_OPEN_APPOINTMENTS` | 409 |
| `ERR_SALE_NOT_VOIDABLE` | 409 |
| `ERR_PACKAGE_NOT_REFUNDABLE` | 409 |
| `ERR_CREDITS_ALREADY_USED` | 409 |
| `ERR_OUTSIDE_OPERATING_WINDOW` | 422 |
| `ERR_CHAIR_DOUBLE_BOOKED` | 409 |
| `ERR_STYLIST_DOUBLE_BOOKED` | 409 |
| `ERR_BLOCK_CHAIR_OR_WINDOW_MISMATCH` | 422 |
| `ERR_CHAIR_RESERVED_FOR_BLOCK` | 409 |
| `ERR_SERVICE_OR_ADDON_INACTIVE` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_INSUFFICIENT_PREPAY` | 402 |
| `ERR_STALE_VERSION` | 412 |
