# Gym Membership Management API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the **Gym Membership Management API**, a unified backbone for a nationwide chain of fitness clubs. The API coordinates a tightly interlocked set of modules: member registration and authentication, multi-level membership tiers and access control, subscription billing with automatic renewal and retry, grace-period and refund schedules that differ by US state, cross-store group class and personal training reservations, real-time trainer and equipment-capacity scheduling, waitlist and no-show enforcement, voluntary and involuntary suspension, promotional coupons and referral rewards, and integration with third-party payment processors, access-control gates, and analytics platforms.

The product target is operational rigor under heavy concurrency. Two members racing for the last seat in a class, a payment-gateway webhook arriving during a member-initiated cancellation, a coupon redeemed at the boundary of its `max_redemptions` cap, a sweep job marking a `CONFIRMED` booking `NO_SHOW` at the same instant the member tries to cancel — every one of these races has a deterministic outcome defined here. Equally, the API is the system of record for state-specific compliance: refund schedules in California, New York, and Texas differ; late-payment penalties differ; permissible suspension durations differ. The rules in this document are pinned per `state_code` so the same code base operates legally in every jurisdiction.

Finally, the API is designed to be testable end-to-end without flaky time-of-day dependencies. The system clock is advanced through an explicit, role-restricted capability, sweeps are run on demand, and external webhooks can be simulated synchronously. Where this document describes a transition triggered by "clock advance" or "the periodic sweep," that transition is exercised through the test-driving capabilities exposed in Section 4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the principal's operational capacity. The system recognises five roles, named exactly as follows: `Member`, `Trainer`, `StoreManager`, `BillingAdmin`, and `Any`. A request that omits either header, or that supplies a role string outside this enumeration, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is recognised but is not in the authorising set for the addressed endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The `X-User-ID` header is interpreted differently per role, and this distinction governs every ownership check in the system:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity. Ownership checks on any resource that references a `Member` — a `Subscription`, a `Booking`, a `PaymentAttempt`, a `ReferralReward`, or a wallet view — compare the resource's foreign-key field (typically `member_id`) to `X-User-ID`. A `Member` may only address their own resources through the `/members/{memberId}/...` family of paths.
- When `X-User-Role` is `Trainer`, `X-User-ID` is the `id` of the acting `Trainer` entity. A `Trainer` may read `Bookings` and `ClassSessions` they personally lead; ownership comparisons match the resource's `trainer_id` to `X-User-ID`.
- When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on audit trails but does not compare it against any entity's `id` for ownership.
- When `X-User-Role` is `BillingAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to a persisted entity; it is recorded for audit but is not used for ownership comparison.
- The `Any` role is the public/anonymous surface used for self-registration and read-only store and trainer directories; `X-User-ID` is an opaque caller identifier carrying no resource binding.

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

List endpoints accept two pagination query parameters. The `limit` parameter caps the page size; it defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter is the zero-indexed number of items to skip; it defaults to 0.

Unless explicitly stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope.

### 2.4. Common Resource Properties

Most primary resources — `Member`, `Subscription`, `Store`, `ClassSession`, `Trainer`, `EquipmentPool`, `Booking`, `Coupon`, and `ReferralReward` — share a standard set of system-managed fields:

- **`id`** (string): a unique, system-generated UUID. There is no type prefix; the identifier is a bare UUID, and clients must never assume any structural pattern beyond UUID syntax.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits, recorded at the moment of creation.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, updated on every modification — including modifications driven by cascading side effects and by recomputed derived fields such as `account_posture` or `reserved_seat_count`.
- **`version`** (integer): a system-managed monotonically increasing integer that starts at 1 and increments by one on every mutation. It supports optimistic concurrency control as described in §2.10.

The `PaymentAttempt` entity is the lone exception. Because payment attempts form an append-only event log, a `PaymentAttempt` carries only `id` and `created_at`; it has no `updated_at` field and no `version` field. Once written, a `PaymentAttempt` is immutable.

### 2.5. Nested Resource Retrieval

Many endpoints address resources nested under a parent — `/members/{memberId}/subscriptions/{subId}/payment-attempts`, for instance, has three levels. The server resolves path parameters strictly from left to right and aborts at the first missing identifier. A request to fetch a payment attempt under a non-existent `memberId` is rejected with `ERR_MEMBER_NOT_FOUND` and the server never opens the `Subscription` table; only after the `Member` exists is the `Subscription` identified by `subId` looked up, with `ERR_SUBSCRIPTION_NOT_FOUND` as the next failure mode. The same left-to-right discipline applies to `bookingId`, `sessionId`, `couponId`, `trainerId`, `storeId`, and equipment-pool lookups, each with its own dedicated not-found error (`ERR_BOOKING_NOT_FOUND`, `ERR_CLASS_SESSION_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`, `ERR_TRAINER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_EQUIPMENT_POOL_NOT_FOUND`, and `ERR_REFERRAL_NOT_FOUND` for sponsor-referral lookups).

### 2.6. Parallel Account Dimensions and Derived Posture

A `Member` carries two independent status dimensions that evolve simultaneously on the same row. The first is `billing_status`, which takes one of `CURRENT`, `PAST_DUE`, `GRACE`, `DELINQUENT`, or `REINSTATED`. The second is `access_status`, which takes one of `ACTIVE`, `SUSPENDED`, `FROZEN`, or `CANCELLED`. These are not redundant — a member can be `CURRENT` for billing while `SUSPENDED` for access, or `REINSTATED` for billing while still `ACTIVE` for access.

From these two dimensions the server derives a third, read-only field, `account_posture`, which takes one of `OPEN`, `RESTRICTED`, or `FROZEN`. The derivation is exact and is recomputed on every write to either dimension. If `access_status` is in `SUSPENDED`, `FROZEN`, or `CANCELLED`, the posture is `FROZEN` regardless of billing. Otherwise, if `billing_status` is in `PAST_DUE`, `GRACE`, or `DELINQUENT`, the posture is `RESTRICTED`. Otherwise — that is, when `billing_status` is in `CURRENT` or `REINSTATED` and `access_status` is `ACTIVE` — the posture is `OPEN`. Any other combination resolves to `RESTRICTED` as a safe default.

This posture is the universal gate. New bookings of either `booking_kind` require posture `OPEN`. A posture of `RESTRICTED` still allows a member to *join* a waitlist (so an overdue member can hold their place while catching up), but it does not allow a `RESERVED` or `CONFIRMED` seat. A posture of `FROZEN` blocks both new bookings and waitlist joins; in this case the rejection is `ERR_ACCOUNT_POSTURE_FROZEN`. The access-gate webhook check-in is accepted only when posture is `OPEN`.

### 2.7. State-Specific Compliance Rules

Several monetary and temporal rules are pinned to the member's `state_code` (a two-letter ISO 3166-2:US code captured at registration). California, New York, and Texas each have their own refund schedule and their own late-payment fee percentage; suspension caps and grace-period lengths likewise vary. The specific tables — the refund-percent bands by hours to start, the late-fee percentage, and the grace-period day count — are documented inline with the workflows that consume them in §3. The principle to internalise here is that `state_code` is *pinned at the time of registration* and is never re-derived from a current home store; if a member's home store changes, the refund and penalty rules they registered under remain in force.

### 2.8. Hierarchical Consistency and Cascading Mutations

When a state transition produces side effects on related entities — a member's `access_status` advancing to `SUSPENDED` cascading to cancel their future bookings, a `ClassSession.cancel` cascading to all non-terminal bookings, a `Subscription` rolling into `DELINQUENT` propagating to `Member.access_status` — each affected entity is an independent mutation. Its `updated_at` is refreshed, its `version` is incremented, and its own derived fields (such as `account_posture` on a `Member` or `reserved_seat_count` on a `ClassSession`) are recomputed in the same atomic operation. Cascades chain only one step at a time but compose: a `Subscription` going `GRACE → DELINQUENT` flips `Member.billing_status` to `DELINQUENT`, which flips `Member.access_status` to `SUSPENDED` and then to `FROZEN`, which then cancels all of that member's future bookings with state-specific refunds. All of these mutations carry their own version bumps and timestamp refreshes.

### 2.9. Idempotency for Payment Attempts

Payment-attempt creation is the one mutating operation in the system that is explicitly idempotent. Every `PaymentAttempt` request carries a client-supplied `idempotency_key` (a UUID) and a `gateway_txn_id` from the third-party gateway. The idempotency key is unique per `Subscription`. If a second request arrives with the same `idempotency_key` and the same `subscription_id`, the server does **not** re-contact the gateway and does **not** persist a duplicate row; instead it returns the prior response with the `ERR_IDEMPOTENT_REPLAY` outcome and HTTP 200. This contract holds whether the original attempt succeeded, failed, or declined; the replay reflects the original outcome, the original `attempt_number`, and the original `amount_cents`.

### 2.10. Optimistic Concurrency Control

Endpoints that modify a versioned resource accept an optional `version` field in the request body. When supplied, the server compares the inbound `version` to the current version of the addressed resource. If the values do not match, the request is rejected with `ERR_INVALID_STATE` and HTTP 409 — the resource has been mutated between the client's read and the client's write, and the client must re-read. When the `version` field is omitted from a mutating request, the server skips the check and applies the mutation against the latest state. Because `PaymentAttempt` is immutable after creation, OCC does not apply to it; the idempotency contract in §2.9 is the relevant duplication-defence mechanism for payment attempts.

### 2.11. Concurrent Writer Resolution

Several race scenarios in this system have explicit, named winners.

- **Last-seat race.** Two members submit a booking for the same `ClassSession` whose `reserved_seat_count` is one short of `capacity` at the moment of submission. At most one booking is awarded `RESERVED`; the other is gracefully demoted to `WAITLISTED` and assigned the next `waitlist_position`. Neither caller receives an error; both receive HTTP 201. Serialisation is first-writer-wins on `ClassSession.reserved_seat_count`, ordered by `Booking.created_at` ascending — never by `id`.
- **Cancel-vs-sweep race.** A member submits a booking cancellation at the same instant the periodic sweep marks the same booking `NO_SHOW`. Exactly one transition wins. The loser receives `ERR_INVALID_STATE` with HTTP 409, since the booking has already reached a terminal state by the time the loser is processed.
- **Idempotent payment race.** Two payment-attempt requests bearing the same `idempotency_key` and the same `subscription_id` arrive concurrently. Exactly one row is persisted; the second is folded into the first and returns `ERR_IDEMPOTENT_REPLAY` with HTTP 200.
- **Coupon overflow race.** Two bookings concurrently attempt to redeem the same `Coupon` whose `redemption_count` is one below `max_redemptions`. The first writer's booking is accepted with the coupon applied; the second is rejected with `ERR_COUPON_EXHAUSTED` and HTTP 409. Serialisation is first-writer-wins on `Coupon.redemption_count`, ordered by `Booking.created_at` ascending.
- **Equipment-pool race.** Two `ClassSession` creations request units from the same `EquipmentPool` over overlapping windows that together would exceed `total_units`. The first writer claims the units; the second is rejected with `ERR_EQUIPMENT_UNAVAILABLE` and HTTP 409. Serialisation is first-writer-wins on the overlapping interval reservation, ordered by `ClassSession.created_at` ascending.
- **Cancel-vs-check-in race.** A member cancels their booking at the same instant the access-gate webhook records a check-in. If the gate's `gate_check_in_at` write lands first, the booking proceeds to `ATTENDED` and the cancel request is rejected with `ERR_BOOKING_TERMINAL` and HTTP 409 — the booking has already reached a terminal state. If the cancel wins, the booking moves to `CANCELLED`, the cascade fires, and the subsequent check-in webhook returns `ERR_BOOKING_TERMINAL` with HTTP 409. Serialisation is first-writer-wins on `Booking.gate_check_in_at`.

### 2.12. Monetary Precision

Every monetary value in the system is stored, computed, and returned as an integer count of cents. There are no fractional cents at rest. Rounding occurs only at named steps in §3's calculations — typically when a percentage is applied — and the rounding mode is always *round half up*. Where a calculation has multiple rounding steps (such as the personal-training pricing formula's tier discount and late-booking surcharge), each step rounds independently before feeding the next; the order of those steps is pinned in §3.6 and §3.7 and must not be reordered, because reordering changes cents.

### 2.13. Validation Ordering

When a request would fail more than one check, the server applies them in a fixed order so that the returned `error_id` is deterministic. The order is: (1) presence and recognition of the user-context headers; (2) role authorisation; (3) left-to-right path-resource existence; (4) state preconditions on the target resource; (5) account-posture gate where applicable; (6) cross-store tier permission for bookings; (7) class minimum-tier permission for bookings; (8) member time-conflict for bookings; (9) trainer availability for personal-training bookings; (10) equipment-pool capacity and maintenance for class-session creation; (11) lead-time minima for bookings; (12) coupon validity where a coupon is attached; (13) amount-mismatch for payment attempts; (14) suspension preconditions (subscription active and no future reserved bookings); and (15) self-referral on registration. Tests against later checks rely on earlier checks passing, so a violation of an earlier check masks any later violations and surfaces only the earlier `error_id`. Specifically, a posture-frozen member who would *also* have a trainer conflict receives `ERR_ACCOUNT_POSTURE_FROZEN`, not `ERR_TRAINER_UNAVAILABLE`. A generic malformed body — missing required fields, type errors, or invalid enum values not otherwise specified — surfaces as `ERR_INVALID_REQUEST` with HTTP 400.

### 2.14. Test-Driving Capabilities

Because many transitions are time-gated (grace-period expiry, suspension-window end, class-session lock, no-show sweep), the API exposes three test-driving capabilities, all reserved for `BillingAdmin`. A clock-advance capability takes a `to_timestamp` and advances the logical clock to that ISO 8601 UTC instant, firing every time-gated transition that became eligible: subscriptions advancing `PAST_DUE → GRACE → DELINQUENT`, members coming out of `SUSPENDED` when `suspension_window_end` is crossed, class sessions advancing `SCHEDULED → LOCKED → COMPLETED`. A sweep capability runs the periodic sweep that marks unattended `CONFIRMED` bookings `NO_SHOW` and processes pending waitlist promotions. An event-emission capability simulates an external webhook (a gate-vendor check-in or a payment-gateway outcome) by accepting an `event_kind` and an `event_payload` and synthesising the corresponding internal effect without contacting the third party.

## 3. Business Logic & Workflows

### 3.1. Member Onboarding, Tiers, and Referrals

A new member self-registers by submitting their `email` (a lowercase RFC-5322 address that must be unique across the chain), a `password` (which the server stores only as a `password_hash`, computed with Argon2id and never returned in any response), a `home_store_id` identifying the store of registration, and a `state_code` (two uppercase letters, ISO 3166-2:US, exactly two characters). Optionally the registrant supplies a `referred_by_member_id` naming a sponsoring member, and they may include subscription bootstrap parameters (`plan`, `billing_cycle`, `applied_coupon_code`) in the same request to spin up a subscription in a single round trip.

On creation, a member's `billing_status` is set to `CURRENT`, their `access_status` to `ACTIVE`, and their `account_posture` is computed from these two dimensions and resolves to `OPEN`. Their `no_show_strike_count` starts at zero, their `wallet_credit_cents` starts at zero, and both `suspension_window_start` and `suspension_window_end` are null. Authentication occurs through a separate login endpoint that accepts `email` and `password` and returns a session token bound to the resulting `X-User-ID`.

The `tier` field — taking exactly one of `BASIC`, `PLUS`, or `ELITE` — determines the member's access scope and personal-training discount. It is server-set from the subscription `plan` once a subscription activates: a member subscribed to `BASIC` is tier `BASIC`, a member on `PLUS` is tier `PLUS`, a member on `ELITE` is tier `ELITE`. Tier governs three downstream behaviours: cross-store booking permission (described later in this subsection), the minimum-tier gate on class sessions, and the personal-training tier discount described in §3.6.

A self-referral is forbidden: at registration time, a `referred_by_member_id` that equals the registering member's own id (or any encoding that resolves to a member referring themselves) is rejected with `ERR_SELF_REFERRAL`. When the referral is legitimate, the server creates a `ReferralReward` row linking the sponsor (`sponsor_member_id`) and the invitee (`invitee_member_id`) with `status` of `PENDING`. The reward stays `PENDING` until the invitee's first payment attempt succeeds; at that moment the server transitions the reward to `QUALIFIED`, records the qualifying attempt's id in `qualifying_attempt_id`, pins `reward_value_cents` from a per-plan table (one thousand cents for an invitee on `BASIC`, two thousand five hundred cents for `PLUS`, five thousand cents for `ELITE`), and mints a new `Coupon` to the sponsor. The minted coupon has `kind` of `REFERRAL_REWARD`, `value` equal to the pinned `reward_value_cents`, `applicable_to` of `SUBSCRIPTION`, and a `tied_to_member_id` pointing to the sponsor; the new coupon's id is recorded as `minted_coupon_id` on the reward, and the reward eventually transitions to `PAID_OUT` once the coupon is consumed by the sponsor (or to `VOIDED` if the invitee subsequently cancels before any settlement window closes).

Cross-store booking is permitted only at tier `PLUS` or higher. Specifically, when a member books at a store whose id differs from their `home_store_id`, the server resolves the hosting store from `class_session_id` (for a group class) or `trainer_id` (for personal training); if the resulting `store_id` differs from `home_store_id` and `tier` is `BASIC`, the booking is rejected with `ERR_CROSS_STORE_NOT_ALLOWED_FOR_TIER`. Members on `PLUS` or `ELITE` may book at any store.

### 3.2. Subscriptions, Billing Cycles, and the Two-Axis Status Dance

A `Subscription` is created with a `plan` (`BASIC`, `PLUS`, or `ELITE`), a `billing_cycle` (`MONTHLY` or `ANNUAL`), and an optional `auto_renew` flag that defaults to true. At creation the subscription enters status `PENDING_ACTIVATION`. The `base_price_cents` is pinned from the chain's plan list at the moment of activation and remains fixed for the lifetime of the subscription, immune to subsequent price-list updates. The owning `member_id` is system-set from the path.

Activation occurs when the first payment attempt for the subscription resolves to a `SUCCESS` outcome. At that moment the subscription transitions from `PENDING_ACTIVATION` to `ACTIVE`, `current_period_start` is set to the present clock, and `current_period_end` is set to the period-start plus one billing cycle (one calendar month for `MONTHLY`, one calendar year for `ANNUAL`); the next charge attempt is enqueued at the period-end instant. If the member registered with a sponsor, this same `SUCCESS` triggers the referral qualification described in §3.1.

Once the subscription is `ACTIVE`, the renewal mechanic engages. When the logical clock advances past `current_period_end`, the server enqueues a new payment attempt for the next period. A `SUCCESS` rolls `current_period_start` and `current_period_end` forward by one cycle and the subscription remains `ACTIVE`. A `FAILED` first attempt of a new period moves the subscription to `PAST_DUE` and cascades `Member.billing_status` to `PAST_DUE` as well; the derived `account_posture` recomputes to `RESTRICTED`, which blocks new bookings (waitlist joins are still permitted under `RESTRICTED`, as described in §2.6).

Each subsequent `FAILED` payment attempt within the same period increments the subscription's `failed_payment_attempts` counter. When that counter reaches three — the retry limit — the subscription advances from `PAST_DUE` to `GRACE` and `Member.billing_status` cascades to `GRACE`. The `grace_period_end` is computed as the present clock plus the grace-period day count configured for the member's `state_code`. Simultaneously a late-payment penalty is assessed against the member's wallet: a per-state percentage of the subscription's pinned `base_price_cents` (five percent for `CA`, eight percent for `NY`, three percent for `TX`) is rounded half up to whole cents and subtracted from `Member.wallet_credit_cents`. The wallet balance may go negative; the next successful charge must add the penalty back into its `amount_cents`.

If the clock advances past `grace_period_end` without any `SUCCESS` in the interval, the subscription transitions from `GRACE` to `DELINQUENT`. This cascades into `Member.billing_status` of `DELINQUENT`, which in turn drives `Member.access_status` to `SUSPENDED` and immediately afterward to `FROZEN`; `account_posture` resolves to `FROZEN`. Every future booking of this member in `RESERVED` or `CONFIRMED` is cancelled with the state-specific refund schedule. A `DELINQUENT` subscription can only be brought back through a `BillingAdmin`-only reinstatement after a manual catch-up payment attempt resolves `SUCCESS`: at that moment the subscription returns to `ACTIVE`, `Member.access_status` returns to `ACTIVE`, and `account_posture` recomputes to `OPEN`.

A `SUCCESS` payment recorded while a subscription is `PAST_DUE` or `GRACE` clears the storm without requiring delinquency: the subscription returns to `ACTIVE`, `failed_payment_attempts` resets to zero, `grace_period_end` becomes null, and `Member.billing_status` advances from `PAST_DUE` or `GRACE` to `REINSTATED`. The next clean billing-cycle rollover — the clock crossing the next `current_period_end` plus one second without a failed first attempt — flips `Member.billing_status` from `REINSTATED` back to `CURRENT` with no observable side effects beyond the label change.

The retry contract for the second and later attempts within a single period deserves particular attention. The first attempt of a period applies the full `wallet_credit_cents` balance against the charge before submission to the gateway. If that attempt fails, the wallet credit that was reserved is *not* re-applied to subsequent retry attempts: the retry submits exactly the same `amount_cents` that the first attempt computed, debited again from the wallet. Equivalently, `wallet_credit_cents` is consumed on the first attempt of a period and the retry submits an identical bill regardless of whether the wallet has since changed.

### 3.3. Payment Attempts and Server-Side Amount Verification

A `PaymentAttempt` is recorded by submitting to the payment-attempts collection of a subscription. The request body carries `gateway_txn_id`, `idempotency_key`, `outcome` (one of `SUCCESS`, `FAILED`, or `DECLINED`), and an optional `failure_reason` (a string from the gateway, null on `SUCCESS`). The server assigns `attempt_number` as the next integer within the current period (one, two, or three; the counter resets when the period rolls).

Because clients submit the gateway transaction's outcome, the server independently recomputes the expected `amount_cents` from the subscription, the member's wallet, and any subscription-level coupon, and rejects the attempt with `ERR_AMOUNT_MISMATCH` and HTTP 422 if the client-supplied `amount_cents` (sent in the body or implied by the gateway record) disagrees with the server's calculation. The amount calculation proceeds in a pinned order. Start with `gross_cents` equal to the subscription's `base_price_cents`. Resolve any coupon attached to the subscription whose `applicable_to` is `SUBSCRIPTION` or `BOTH`; if the coupon's `kind` is `PERCENT_OFF`, multiply `gross_cents` by `value` divided by one hundred and round half up to whole cents, calling the result `discount_cents`. If the coupon's `kind` is `FIXED_OFF_CENTS`, take `discount_cents` as the lesser of `value` and `gross_cents`. Otherwise `discount_cents` is zero. Compute `net_after_coupon` as `gross_cents` minus `discount_cents`. Then apply the wallet: `wallet_applied` is the lesser of the member's current `wallet_credit_cents` and `net_after_coupon`. The final `amount_cents` is the larger of zero and `net_after_coupon` minus `wallet_applied`. Coupons must be discounted and rounded *before* the wallet is applied; reordering changes the cents result and is a contract violation.

### 3.4. Voluntary Suspension, Resume, and Cancellation

A member may voluntarily suspend their access through the suspension endpoint, optionally providing `requested_days` to indicate how long they want the suspension to last. Suspension is only permitted when the member's `Subscription.status` is in `ACTIVE` or `REINSTATED` *and* the member has no future booking in status `RESERVED` or `CONFIRMED` whose start instant falls within the requested suspension window; if either condition fails, the request is rejected with `ERR_HAS_FUTURE_BOOKINGS`. On success, `suspension_window_start` is set to the current clock, `suspension_window_end` is set to the present clock plus the maximum number of suspension days the member's `state_code` permits (or the smaller of that per-state cap and `requested_days` when `requested_days` is provided), `access_status` flips to `SUSPENDED`, and `account_posture` resolves to `FROZEN`. The subscription's `auto_renew` is temporarily ignored for the duration of the window — the member is billed at zero during the suspension — even if `auto_renew` is otherwise true.

The system automatically ends the suspension when the clock advances past `suspension_window_end`: `access_status` returns to `ACTIVE`, both window timestamps become null, and `account_posture` recomputes. A member may also resume early through the resume endpoint, which is permitted whenever `access_status` is `SUSPENDED`; the suspension window is cleared and `access_status` flips back to `ACTIVE`.

Cancellation is requested through the cancel endpoint and is permitted from any non-terminal access status. There is one timing precondition: no non-terminal payment attempt may exist within the last two minutes; if one does, the request is rejected with `ERR_PAYMENT_IN_FLIGHT` and HTTP 409 — the system refuses to cancel while a payment may still resolve. On success, `Subscription.cancellation_effective_at` is set to the subscription's `current_period_end` (so cancellation is voluntary and end-of-period, not immediate), `Subscription.auto_renew` is forced to false, and `Member.account_posture` becomes `FROZEN`. The terminal `access_status` of `CANCELLED` is reached at `cancellation_effective_at`.

### 3.5. Scheduling Class Sessions, Trainers, and Equipment

A `StoreManager` schedules a `ClassSession` under a `Store` by providing `class_type` (a string such as `YOGA`, `SPIN`, or `HIIT`), `trainer_id` (the leading `Trainer`), `starts_at` and `ends_at` (ISO 8601 UTC instants with `ends_at` strictly greater than `starts_at`), `capacity` (the maximum reserved seats, excluding any waitlist), and optionally `minimum_tier` (one of `BASIC`, `PLUS`, or `ELITE`, defaulting to `BASIC`), `equipment_pool_id` referencing an `EquipmentPool` reserving `equipment_units_required` units across the `[starts_at, ends_at)` half-open window (if the class needs no shared equipment, `equipment_pool_id` is null and `equipment_units_required` defaults to zero). The server assigns the hosting `store_id`. The new session begins in status `SCHEDULED`, and `reserved_seat_count` is initialised to zero.

Two scheduling invariants are enforced at session creation. First, equipment availability: the sum of `equipment_units_required` across all `SCHEDULED` or `LOCKED` class sessions whose `[starts_at, ends_at)` half-open window overlaps the requested session's window must remain at or below the pool's `total_units`, *and* the requested window must not overlap the pool's `[maintenance_window_start, maintenance_window_end)` half-open maintenance window even partially. A violation of either clause is rejected with `ERR_EQUIPMENT_UNAVAILABLE`. Second, trainer availability — though this check applies to personal-training bookings rather than class sessions per se — the system also rejects with `ERR_EQUIPMENT_UNAVAILABLE` on concurrent allocations that would exceed the pool, with first-writer-wins semantics described in §2.11.

A `Trainer` is registered with `full_name`, a `home_store_id`, an array of `certifications` (strings such as `YOGA`, `SPIN`), and an `hourly_rate_cents` that drives the personal-training pricing formula in §3.6. An `EquipmentPool` is created under a `Store` with `equipment_type` (a string such as `SPIN_BIKE`, `ROWER`, `TRX_RACK`), a `total_units` inventory count, and optional `maintenance_window_start` and `maintenance_window_end` timestamps.

A class session evolves through three transitions before reaching a terminal state. As the clock approaches the start time — specifically, when the clock reaches `starts_at` minus the configured confirmation-cutoff window — the session moves from `SCHEDULED` to `LOCKED`. At that moment, any `Booking` against the session that is still in `RESERVED` (i.e., the member has not yet confirmed) is cancelled as a cascade, and the waitlist-promotion mechanism in §3.7 fires to fill vacated seats. After the session's `ends_at` has passed, the periodic sweep transitions the session from `LOCKED` to `COMPLETED`, and every `CONFIRMED` booking that lacks a `gate_check_in_at` becomes `NO_SHOW`. A `StoreManager` may also cancel the session at any point while it is `SCHEDULED` or `LOCKED`: every non-terminal `Booking` against the session is cancelled with the administrative refund schedule (full refund, no late-cancel penalty), and the equipment-pool reservation for `[starts_at, ends_at)` is released.

### 3.6. Bookings: Creation, Pricing, and the Waitlist

A `Booking` is created through the bookings endpoint with `booking_kind` (one of `GROUP_CLASS` or `PERSONAL_TRAINING`), and the appropriate references — `class_session_id` is required when `booking_kind` is `GROUP_CLASS` (and `trainer_id` is null), while `trainer_id` is required when `booking_kind` is `PERSONAL_TRAINING` (and `class_session_id` is null). The request may carry `starts_at` and `ends_at` (which, for a group class, must equal the corresponding fields on the underlying `ClassSession`) and an optional `applied_coupon_id` to redeem a coupon at booking time. The server sets `member_id` from the path, derives the hosting `store_id` for cross-store query support, and assigns the initial `status`.

Capacity routing happens at creation. For a group-class booking, the server reads the session's `reserved_seat_count`. If the count is below `capacity`, the booking is assigned status `RESERVED`, `reserved_seat_count` is incremented, and `waitlist_position` is null. If the count is already at `capacity`, the booking is assigned status `WAITLISTED` and given the next `waitlist_position` — a 1-indexed FIFO rank computed from `Booking.created_at` ascending within the same session, with ties never broken by id. A personal-training booking that passes its trainer-availability checks is created directly in `RESERVED`.

The `provisional_price_cents` is computed at booking creation, and is recomputed if the booking is later promoted from `WAITLISTED` to `RESERVED` (because by then the present clock may have crossed the late-booking surcharge window). The calculation is pinned and ordered. For a group class, the starting price `base_cents` is the class-type base rate — two thousand cents for `YOGA`, two thousand five hundred cents for `SPIN`, two thousand two hundred cents for `HIIT`. For personal training, `duration_minutes` is the integer number of whole minutes between `ends_at` and `starts_at`, and `base_cents` is the trainer's `hourly_rate_cents` multiplied by `duration_minutes` and divided by sixty, then rounded *up* to the next whole cent (ceiling). Next, the member's tier discount is applied: `tier_discount_pct` is zero for `BASIC`, ten for `PLUS`, twenty for `ELITE`; the discount in cents is `base_cents` times `tier_discount_pct` divided by one hundred, rounded half up; the running total `after_tier` is `base_cents` minus that discount. Then the late-booking check: compute `hours_to_start` as the difference between `ClassSession.starts_at` and the present clock divided by thirty-six hundred. If `hours_to_start` is less than two — the late-booking threshold — apply a surcharge of `after_tier` multiplied by twenty-five percent, rounded half up; otherwise the surcharge is zero. Add the surcharge to `after_tier`. Finally, if `applied_coupon_id` is set and the coupon's `applicable_to` includes `BOOKING`, apply the coupon's discount to the sum (the same `PERCENT_OFF`/`FIXED_OFF_CENTS` semantics described for subscriptions, evaluated at this surcharge-inclusive subtotal). Floor the result at zero. The order — tier discount first, then surcharge, then coupon, then floor — is mandatory; rerounding the sum at the end is forbidden.

A booking's `final_price_cents` is determined only when it reaches a terminal state and reflects post-event adjustments per §3.7.

A few business preconditions apply at creation. The member's `account_posture` must be `OPEN` for a new `RESERVED` or `CONFIRMED` seat (a `RESTRICTED` posture allows a waitlist join only; a `FROZEN` posture rejects entirely with `ERR_ACCOUNT_POSTURE_FROZEN`). The session's `minimum_tier` must be at or below the member's `tier`; for instance, a `BASIC` member who attempts to reserve a `PLUS`-only or `ELITE`-only class is rejected with `ERR_TIER_BELOW_MINIMUM`. The cross-store tier rule from §3.1 applies. The booking must not time-conflict with any other booking of the same member: the requested `[starts_at, ends_at)` half-open interval must not overlap any of the member's other bookings (across all stores), although adjacent intervals (the new booking's `starts_at` exactly equal to another's `ends_at`, or vice versa) are explicitly permitted; an overlap is rejected with `ERR_MEMBER_TIME_CONFLICT`. For personal training, the trainer must be free in the closed-on-both-sides envelope of `[starts_at − 15 minutes, ends_at + 15 minutes]`; another `RESERVED` or `CONFIRMED` PT booking for the same trainer that touches this envelope at any point — including the boundary instants — is a conflict and is rejected with `ERR_TRAINER_UNAVAILABLE`. For group classes, the booking's `starts_at` must be at least the minimum lead time — ten minutes — beyond the present clock and must equal the underlying `ClassSession.starts_at` exactly; a violation is rejected with `ERR_BOOKING_LEAD_TIME`. Finally, if an `applied_coupon_id` is supplied, the coupon's validity is checked: the coupon must exist, its `status` must be `ACTIVE`, the present clock must fall in `[valid_from, valid_until)` (half-open), `redemption_count` must be strictly less than `max_redemptions`, and `applicable_to` must match the booking context (`BOOKING` or `BOTH`); failure surfaces as `ERR_COUPON_INVALID`. A coupon at or above `max_redemptions` is `ERR_COUPON_EXHAUSTED` per the race rules in §2.11.

### 3.7. Booking Lifecycle: Confirmation, Check-In, Cancellation, and No-Show

A `WAITLISTED` booking is promoted to `RESERVED` automatically whenever a seat opens on the same session — typically because a sibling booking is cancelled, or because the session locks and a `RESERVED` booking with no confirmation is auto-cancelled. The promotion selector is strictly first-in-first-out by `created_at` ascending (id is never used as a tie-break) and is further filtered: only `WAITLISTED` bookings whose owner currently has `account_posture` of `OPEN` are promoted; the others are skipped. When a booking is promoted, `reserved_seat_count` increments, `provisional_price_cents` is recomputed at the present clock (so a late-window promotion may now carry the late-booking surcharge), and coupon `redemption_count` is adjusted if a coupon was applied.

A `RESERVED` booking advances to `CONFIRMED` only through an explicit confirmation action by the member, and only when two conditions hold: the member's `account_posture` is `OPEN`, and the present clock is strictly before `ClassSession.starts_at` minus the configured confirmation cutoff. Confirmation has no side effects beyond the state flip.

A `CONFIRMED` booking advances to `ATTENDED` only through the access-gate webhook, which records `gate_check_in_at` at the present clock. The check-in is accepted only when the present clock lies in the inclusive window `[ClassSession.starts_at − 15 minutes, ClassSession.ends_at]` and the member's `account_posture` is `OPEN`. On success, `final_price_cents` equals `provisional_price_cents` (no penalty applies).

A `CONFIRMED` booking that never receives a gate check-in is swept to `NO_SHOW` after `ClassSession.ends_at`. The sweep recomputes the member's `no_show_strike_count` (the count of `NO_SHOW` transitions for the member within a rolling thirty-day window ending at the present clock) and applies a no-show penalty: `final_price_cents` becomes `provisional_price_cents` plus one thousand cents. If the recomputed strike count reaches or exceeds three, a cascade fires: the member's `access_status` is set to `SUSPENDED` for seven days, `suspension_window_start` is the present clock, `suspension_window_end` is the present clock plus seven days, and `account_posture` resolves to `FROZEN`.

A member may cancel a booking through the cancellation endpoint while it is in any non-terminal status — `WAITLISTED`, `RESERVED`, or `CONFIRMED`. The cancellation refund follows the member's `state_code`-pinned schedule applied to the booking's `provisional_price_cents`. For `CA`, the bands are: if `hours_to_start` (the difference between the underlying session's `starts_at` and the cancellation instant, divided by thirty-six hundred) is at least twenty-four, refund one hundred percent; otherwise if `hours_to_start` is at least two, refund fifty percent; otherwise refund zero. For `NY`, the bands are: at least forty-eight hours, one hundred percent; at least six hours, seventy-five percent; at least one hour, twenty-five percent; otherwise zero. For `TX`, the bands are: at least twelve hours, one hundred percent; otherwise zero. The boundary check is inclusive on `hours_to_start` greater than or equal to the threshold — so a `CA` cancellation at exactly `hours_to_start` equal to twenty-four refunds one hundred percent, at exactly two refunds fifty percent, and at one point nine nine nine refunds zero. The refund in cents is `provisional_price_cents` multiplied by the chosen `refund_pct` divided by one hundred, rounded half up; `final_price_cents` is `provisional_price_cents` minus the refund credit, and the refund credit is added to `Member.wallet_credit_cents`. If the cancelled booking had a confirmed seat, `reserved_seat_count` is decremented and the waitlist promotion fires; if the booking had an `applied_coupon_id`, the coupon's `redemption_count` is decremented.

Cancellation by system cascade — when a member's `access_status` enters `SUSPENDED`, `FROZEN`, or `CANCELLED`, or when a `ClassSession` enters `CANCELLED` — uses the administrative refund schedule instead of the member's state schedule: one hundred percent refund regardless of `hours_to_start`, and no `NO_SHOW` penalty applies even if the booking had previously been `CONFIRMED`.

The interaction between the cancel-vs-sweep race and the cancel-vs-check-in race is governed by §2.11; in both cases the loser receives a terminal-state rejection (`ERR_INVALID_STATE` for the sweep race, `ERR_BOOKING_TERMINAL` for the check-in race).

### 3.8. Coupons and the Wallet

Promotional coupons are minted by a `BillingAdmin` through the coupons endpoint. Each coupon carries a human-typed `code` (uppercase A–Z and 0–9, length six to twelve characters, unique across the chain), a `kind` of `PERCENT_OFF`, `FIXED_OFF_CENTS`, or `REFERRAL_REWARD`, a `value` (percent zero through one hundred for `PERCENT_OFF`; cents for `FIXED_OFF_CENTS` or `REFERRAL_REWARD`), an `applicable_to` enumeration of `SUBSCRIPTION`, `BOOKING`, or `BOTH`, a `valid_from` and `valid_until` ISO 8601 instants bounding the redemption window as the half-open interval `[valid_from, valid_until)`, and a `max_redemptions` cap. The server maintains `redemption_count` (the live count of bookings or subscriptions that have consumed the coupon) and `status` (one of `ACTIVE`, `EXHAUSTED`, `EXPIRED`, or `REVOKED`). A coupon minted as a referral reward also carries a non-null `tied_to_member_id` pinning the sponsor — promotional coupons have a null `tied_to_member_id`.

The coupon verification endpoint accepts a `context_kind` and optional `context_id` and reports whether the addressed coupon can be redeemed in that context for the calling member; it is used both interactively and by the third-party analytics platform.

The wallet view exposes a member's `wallet_credit_cents` and recent ledger movement. The wallet is consumed by the next billing run in FIFO order (oldest credit first) and may be debited by late-payment penalties as described in §3.2; a negative wallet balance is permitted at rest and the next successful charge restores it.

### 3.9. Trainer and Store Directories

The `Store` directory exposes each store's `name` (display name), `state_code`, `opens_at_local` and `closes_at_local` (24-hour `HH:MM` strings denoting the store's daily operating window), and `gate_device_id` (the identifier the third-party access-gate vendor expects in webhook callbacks). The trainer directory exposes each trainer's `full_name`, `home_store_id`, `certifications` list, and `hourly_rate_cents`. Both directories are read-only to the public surface and form the entry-point for class discovery and personal-training selection.

Class-session discovery is calendar-bounded. Listing class sessions for a store accepts two optional ISO 8601 UTC query parameters, `from` and `to`, which act as inclusive-start, exclusive-end bounds on `ClassSession.starts_at`. When `from` is omitted, the query reaches back to the earliest scheduled session; when `to` is omitted, it extends forward to the latest. Listing members, listing trainers, listing bookings, listing subscriptions, listing payment attempts, listing coupons, listing equipment pools, and listing referrals each additionally accept filter query parameters as documented inline with their workflows — `tier` and `billing_status` for the member directory, `home_store_id` for trainers, `booking_kind` and `status` for bookings, `state_code` for stores, and `status` for coupons.

## 4. Endpoint Definitions

Operations that create a new resource — registering a member, scheduling a class session, recording a payment attempt, creating a booking, minting a coupon — return HTTP 201 Created. Operations that modify an existing resource — confirming a booking, cancelling, suspending, resuming, reinstating, advancing the test clock — return HTTP 200 OK. Operations that fail validation return the appropriate 4xx status as described in §5.

| Method | Path                                                                  | Description                                                                                  | Authorized Role(s)            |
| ------ | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------- |
| POST   | `/members`                                                            | Register a new Member                                                                        | Any                           |
| POST   | `/members/{memberId}/login`                                           | Authenticate; returns session token bound to X-User-ID                                       | Any                           |
| GET    | `/members`                                                            | List Members                                                                                 | StoreManager, BillingAdmin    |
| GET    | `/members/{memberId}`                                                 | Get a Member                                                                                 | Member, Trainer, StoreManager, BillingAdmin |
| POST   | `/members/{memberId}/suspend`                                         | Voluntary suspend                                                                            | Member, BillingAdmin          |
| POST   | `/members/{memberId}/resume`                                          | Early resume from suspension                                                                 | Member, BillingAdmin          |
| POST   | `/members/{memberId}/cancel`                                          | Cancel membership at end of current period                                                   | Member, BillingAdmin          |
| POST   | `/members/{memberId}/subscriptions`                                   | Create a Subscription (PENDING_ACTIVATION until first SUCCESS payment)                       | Member, BillingAdmin          |
| GET    | `/members/{memberId}/subscriptions`                                   | List Subscriptions for a Member                                                              | Member, BillingAdmin          |
| GET    | `/members/{memberId}/subscriptions/{subId}`                           | Get a Subscription                                                                           | Member, BillingAdmin          |
| POST   | `/members/{memberId}/subscriptions/{subId}/reinstate`                 | Manually reinstate a DELINQUENT subscription                                                 | BillingAdmin                  |
| POST   | `/members/{memberId}/subscriptions/{subId}/payment-attempts`          | Record a payment attempt outcome; idempotent on idempotency_key per Subscription             | system, BillingAdmin          |
| GET    | `/members/{memberId}/subscriptions/{subId}/payment-attempts`          | List PaymentAttempts for a Subscription                                                      | BillingAdmin, Member          |
| GET    | `/stores`                                                             | List Stores                                                                                  | Any                           |
| POST   | `/stores/{storeId}/class-sessions`                                    | Schedule a ClassSession                                                                      | StoreManager                  |
| GET    | `/stores/{storeId}/class-sessions`                                    | List ClassSessions for a Store                                                               | Any                           |
| GET    | `/stores/{storeId}/class-sessions/{sessionId}`                        | Get a ClassSession                                                                           | Any                           |
| POST   | `/stores/{storeId}/class-sessions/{sessionId}/cancel`                 | Cancel a ClassSession; cascades to all non-terminal Bookings                                 | StoreManager                  |
| POST   | `/stores/{storeId}/equipment-pools`                                   | Create an EquipmentPool                                                                      | StoreManager                  |
| GET    | `/stores/{storeId}/equipment-pools`                                   | List EquipmentPools for a Store                                                              | Any                           |
| POST   | `/trainers`                                                           | Register a Trainer                                                                           | StoreManager, BillingAdmin    |
| GET    | `/trainers`                                                           | List Trainers                                                                                | Any                           |
| GET    | `/trainers/{trainerId}`                                               | Get a Trainer                                                                                | Any                           |
| POST   | `/members/{memberId}/bookings`                                        | Create a Booking (GROUP_CLASS or PERSONAL_TRAINING); auto-WAITLIST when capacity full        | Member, StoreManager          |
| GET    | `/members/{memberId}/bookings`                                        | List Bookings for a Member                                                                   | Member, BillingAdmin          |
| GET    | `/members/{memberId}/bookings/{bookingId}`                            | Get a Booking                                                                                | Member, BillingAdmin, StoreManager, Trainer |
| POST   | `/members/{memberId}/bookings/{bookingId}/confirm`                    | Confirm a RESERVED Booking                                                                   | Member                        |
| POST   | `/members/{memberId}/bookings/{bookingId}/check-in`                   | Access-gate webhook callback: records gate_check_in_at                                       | system                        |
| POST   | `/members/{memberId}/bookings/{bookingId}/cancel`                     | Cancel a Booking (computes state-specific refund)                                            | Member, StoreManager          |
| POST   | `/coupons`                                                            | Create a promotional Coupon                                                                  | BillingAdmin                  |
| GET    | `/coupons`                                                            | List Coupons                                                                                 | BillingAdmin, StoreManager    |
| GET    | `/coupons/{couponId}`                                                 | Get a Coupon                                                                                 | BillingAdmin, StoreManager, Member |
| POST   | `/coupons/{couponId}/verify`                                          | Verify a Coupon can be redeemed by a given Member for a given context                        | Member, BillingAdmin, system  |
| GET    | `/members/{memberId}/referrals`                                       | List ReferralRewards where this Member is the sponsor                                        | Member, BillingAdmin          |
| GET    | `/members/{memberId}/wallet`                                          | Read-only view of wallet_credit_cents and recent ledger entries                              | Member, BillingAdmin          |
| POST   | `/_clock/advance`                                                     | Test-only: advances server clock to a given ISO 8601 UTC instant                             | BillingAdmin                  |
| POST   | `/_sweep/run`                                                         | Test-only: runs the periodic sweep                                                           | BillingAdmin                  |
| POST   | `/_events/emit`                                                       | Test-only: simulates an external event (gate-vendor or payment-gateway webhook)              | BillingAdmin                  |

## 5. Error Code Catalogue

| Error ID                                       | HTTP Status Code     |
| ---------------------------------------------- | -------------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`   | 400 Bad Request      |
| `ERR_INSUFFICIENT_PERMISSIONS`                 | 403 Forbidden        |
| `ERR_MEMBER_NOT_FOUND`                         | 404 Not Found        |
| `ERR_SUBSCRIPTION_NOT_FOUND`                   | 404 Not Found        |
| `ERR_BOOKING_NOT_FOUND`                        | 404 Not Found        |
| `ERR_CLASS_SESSION_NOT_FOUND`                  | 404 Not Found        |
| `ERR_COUPON_NOT_FOUND`                         | 404 Not Found        |
| `ERR_TRAINER_NOT_FOUND`                        | 404 Not Found        |
| `ERR_STORE_NOT_FOUND`                          | 404 Not Found        |
| `ERR_EQUIPMENT_POOL_NOT_FOUND`                 | 404 Not Found        |
| `ERR_REFERRAL_NOT_FOUND`                       | 404 Not Found        |
| `ERR_INVALID_STATE`                            | 409 Conflict         |
| `ERR_BOOKING_TERMINAL`                         | 409 Conflict         |
| `ERR_ACCOUNT_POSTURE_FROZEN`                   | 403 Forbidden        |
| `ERR_PAYMENT_IN_FLIGHT`                        | 409 Conflict         |
| `ERR_HAS_FUTURE_BOOKINGS`                      | 409 Conflict         |
| `ERR_IDEMPOTENT_REPLAY`                        | 200 OK               |
| `ERR_CROSS_STORE_NOT_ALLOWED_FOR_TIER`         | 403 Forbidden        |
| `ERR_TIER_BELOW_MINIMUM`                       | 403 Forbidden        |
| `ERR_MEMBER_TIME_CONFLICT`                     | 409 Conflict         |
| `ERR_TRAINER_UNAVAILABLE`                      | 409 Conflict         |
| `ERR_EQUIPMENT_UNAVAILABLE`                    | 409 Conflict         |
| `ERR_BOOKING_LEAD_TIME`                        | 409 Conflict         |
| `ERR_COUPON_INVALID`                           | 400 Bad Request      |
| `ERR_COUPON_EXHAUSTED`                         | 409 Conflict         |
| `ERR_AMOUNT_MISMATCH`                          | 422 Unprocessable Entity |
| `ERR_SELF_REFERRAL`                            | 400 Bad Request      |
| `ERR_INVALID_REQUEST`                          | 400 Bad Request      |
