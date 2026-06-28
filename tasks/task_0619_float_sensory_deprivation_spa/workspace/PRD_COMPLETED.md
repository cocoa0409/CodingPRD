# Float-Spa API — Product Requirements Document

## 1. Introduction

This document specifies the Float-Spa platform, the operations backbone for a sensory-deprivation float center that runs scarce, perishable tank time against a calendar of bookings. Each float pod is a physical resource that can host exactly one session at a time, and after every session it must sit idle through a sanitation turnover before the next floater can step in. The product exists to keep that turnover honest — no double-booking, no skipped cleaning cycle — while layering on the commercial machinery a modern wellness business needs: monthly memberships that grant and roll over float credits, prepaid gift cards, couples bookings that occupy a dual-chamber tank, first-time orientation with a signed liability waiver, and a deposit regime that protects the center against no-shows and last-minute cancellations.

Three kinds of operator share the system. Members self-serve their own bookings, reschedules, and cancellations; front-desk staff run the daily floor — check-ins, completions, sanitation, orientations, and membership billing; and administrators own configuration (plans, tanks, attendants) plus the override authority that operations occasionally need. Because almost every rule in the building turns on *time* — a cancellation cutoff, a no-show grace period, a sanitation window, a billing cycle — the platform runs on a single server-controlled logical clock rather than wall-clock time, so that the same booking lifecycle can be exercised deterministically. The sections that follow define the global request/response contract first, then the cross-cutting principles (money precision, concurrency, sanitation gating), and finally the detailed business workflows that tie members, tanks, bookings, and ledgers together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, the request/response contract, and the cross-cutting principles that govern every endpoint. Where a rule below names an error identifier, the same identifier reappears in §5's catalogue with its HTTP status.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The platform recognizes exactly three roles, spelled precisely as `Member`, `FrontDesk`, and `Admin`. A request missing either header, or carrying a role the server does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A syntactically valid request whose role is not permitted to perform the requested operation — or a `Member` reaching for a resource it does not own — is rejected with `ERR_FORBIDDEN`.

The three roles form a hierarchical override chain: `Member` is the narrowest (self-service), `FrontDesk` is the operations superset, and `Admin` is the full superset that can do everything `FrontDesk` can plus configuration and override. Anything a narrower role may do, a wider role may also do.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity. Ownership checks compare a resource's owning member to `X-User-ID`: for a `Booking`, `Membership`, or `Orientation`, the resource's `member_id` must equal `X-User-ID`; for a `CreditLedgerEntry` or `Payment`, ownership resolves through the referenced booking or membership back to that member. A `Member` may create a booking only for their own `member_id`, may confirm, reschedule, or cancel only their own bookings, may cancel only their own membership or orientation, and may read only their own bookings, memberships, orientations, payments, and credit-ledger entries (plans, tanks, and gift cards remain readable by id). When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`, and `FrontDesk` may act on resources belonging to any member. When `X-User-Role` is `Admin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, carrying the same non-ownership semantics as `FrontDesk` plus the configuration and clock-control authority described throughout §3.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. An out-of-range `limit` is silently clamped into that range rather than rejected — a value below 1 becomes 1 and a value above 100 becomes 100 — and a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter is the number of items to skip; it defaults to 0, and a negative `offset` is clamped to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, ties broken by insertion order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `has_more` is true exactly when `offset` plus `limit` is less than `total_count`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system are *primary records* and carry a uniform set of system-managed fields: an `id` that is a server-minted UUID (a bare UUID with no type prefix), a `created_at` ISO 8601 UTC timestamp with three fractional digits, an `updated_at` ISO 8601 UTC timestamp updated on every mutation, and a `version` integer that starts at 1 and increments by one with every mutation. Membership plans, members, memberships, tanks, sanitation cycles, attendants, orientations, bookings, and gift cards all carry the full set.

Two ledgers are the exception. A `CreditLedgerEntry` and a `Payment` are append-only audit records: each carries only an `id` (UUID) and a `created_at`, and neither carries an `updated_at` nor a `version`. They are written once and never mutated.

All time-sensitive rules — cancellation cutoffs, the no-show grace period, check-in lead time, reschedule windows, sanitation completion, orientation completion, and billing-cycle boundaries — read a single server logical clock rather than wall-clock time. On startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock is explicitly set it stays at that default and never falls back to wall-clock time. An administrator may advance the clock to a supplied instant; the capability accepts a target instant in the `to_iso8601` field and reports the new clock as `now_utc`. Every deadline computation in §3 is evaluated against this clock value, referred to throughout as the current time.

### 2.5. Monetary and Credit Precision

All money is handled in integer cents — there are no fractional cents anywhere in the system. Whenever a calculation produces a non-integer cent amount (for example, the ninety-minute price multiplier, the member discount, or a prorated refund), the result is rounded to the nearest whole cent using the round-half-up rule, where a value exactly halfway between two cents rounds up. Float credits are whole-number counts and are never fractional; credit arithmetic produces no rounding. A gift card's remaining balance and a membership's credit balance are both derived (reconciled) quantities and are never allowed to go negative under valid play.

### 2.6. Left-to-Right Reference Resolution

Endpoints address resources by an `id` in the path and frequently reference other resources by foreign-key fields in the request body. All such references are resolved left-to-right: the path identifier is checked first, then each body foreign key in the order the workflow consumes them. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any business rule runs. This resolution precedes state, eligibility, timing, and fiscal checks.

### 2.7. Validation Ordering and Precedence

When several checks could fail on the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a request lacking valid headers fails with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else. Authorization is next: a role or ownership violation fails with `ERR_FORBIDDEN` (HTTP 403). Reference existence is third, per §2.6, failing with `ERR_NOT_FOUND` (HTTP 404). Fourth comes request well-formedness — required fields present, enum values in range, `end_utc` strictly after `start_utc`, and `session_minutes` being one of the two allowed lengths — which fails with `ERR_INVALID_REQUEST` (HTTP 422). Immediately after well-formedness, the numeric-range checks on configuration creation (described in §3.1 and §3.6) fail with `ERR_VALIDATION_RANGE` (HTTP 422). Only once a request is authenticated, authorized, resolvable, well-formed, and in-range does the system evaluate state-machine legality, which fails with `ERR_INVALID_STATE` (HTTP 409) when a transition is not defined from the resource's current state. Beyond that point, the domain-specific business checks described in §3 apply, each carrying its own dedicated error and HTTP status; the per-endpoint ordering among those domain checks is called out in the relevant §3 narrative.

### 2.8. Tank Availability: Two Independent Dimensions

Every tank tracks its health along two completely independent axes that evolve separately on the same record. The first is the `operational_status` axis — `IN_SERVICE`, `MAINTENANCE`, or `RETIRED` — which staff and admins drive manually and which reflects whether the pod is physically fit to run. The second is the `sanitation_status` axis — `CLEAN` or `IN_CYCLE` — which the system drives automatically from the sanitation-cycle lifecycle and reflects whether the pod has been turned over since its last session. A tank can be `IN_SERVICE` yet `IN_CYCLE` (operational but mid-cleaning), or `CLEAN` yet `MAINTENANCE` (spotless but pulled from service). A session check-in requires *both* axes to be favorable at once — the tank must be `CLEAN` on the sanitation axis and `IN_SERVICE` on the operational axis; failing either at check-in yields `ERR_TANK_UNAVAILABLE`. Each axis is described in full in §3.4.

### 2.9. Append-Only Ledgers and Derived Balances

The platform keeps two append-only ledgers, and the balances that operators see are always *reconciled from* those ledgers rather than stored independently. A membership's `credit_balance` is, at every moment, the sum of the `delta` values across all `CreditLedgerEntry` rows for that membership; every time a ledger row is inserted, the membership's balance is recomputed from the full set of its entries. Likewise, a gift card's `remaining_balance_cents` is its `initial_balance_cents` minus the sum of `amount_cents` across all `Payment` rows for that card whose `source` is `GIFT_CARD`; because refunds carry negative amounts, a refund payment adds value back to the card. These reconciliation rules are the single source of truth for the two balances, and the workflows in §3 describe which events append which ledger rows.

### 2.10. Optimistic Concurrency on Membership Renewal

Renewing a membership is the one operation guarded by optimistic concurrency control, because a renewal both rolls credits forward and advances the billing window, and a fresh renewal legitimately supersedes any earlier view of the membership a client might still be holding. A renewal request must carry `expected_membership_version`, a non-optional field whose value is the `version` the client last observed on the target membership. If that value does not equal the membership's current `version`, the renewal is rejected as stale with `ERR_STALE_VERSION` (HTTP 412) rather than double-applying the cycle advance. No other endpoint takes a version field, and no other endpoint performs this check.

## 3. Business Logic & Workflows

### 3.1. Configuration: Plans, Tanks, and Attendants

Before any member can float, an administrator lays down the configuration layer. A **membership plan** is created with a `tier` label (unique among plans, such as `SOLO`, `DUO`, or `UNLIMITED`), a recurring `monthly_fee_cents`, the number of `included_floats_per_cycle` granted at the start of each billing cycle, a `rollover_cap` limiting how many unused credits may carry forward, a `retail_float_cents` value that is both the cash drop-in price and the cash value of a single float credit for that tier, an optional `member_discount_pct` (a fraction between 0.0 and 1.0 applied to the retail session price for members on the plan, defaulting to 0.0), and an optional `active` flag (defaulting to true) controlling whether new memberships may be opened on it. At creation the platform enforces numeric sanity: `monthly_fee_cents` must be zero or greater, `included_floats_per_cycle` must be zero or greater, `rollover_cap` must be zero or greater, `member_discount_pct` must be between 0.0 and 1.0 inclusive, and `retail_float_cents` must be strictly greater than zero; any violation is rejected with `ERR_VALIDATION_RANGE`. Plans are readable by everyone and the plan list accepts an `active` filter.

A **tank** (pod) is created with a unique `name`, a `capacity_kind` of either `SINGLE` (one floater) or `DUAL` (a couples pod with two chambers occupied together by one couples booking), and an optional `turnover_buffer_minutes` (defaulting to 30) reserving sanitation time after each session before the pod may be re-booked. A new tank starts `IN_SERVICE` on its operational axis and `CLEAN` on its sanitation axis. When a tank is created, `turnover_buffer_minutes` must be zero or greater. The tank list accepts a `capacity_kind` filter.

An **attendant** is the staff member who supervises first-time orientations; it carries a `full_name` and an optional `active` flag (defaulting to true) governing whether the attendant may be assigned to new orientations. Plans, tanks, and attendants are all administrator-created configuration.

### 3.2. Members, Orientation, and the Waiver Gate

A **member** is registered with a unique `email` and a `full_name`. Every new member starts life with `status` equal to `ACTIVE`, `orientation_completed` set to false, `waiver_signed_version` set to 0, and `no_show_strikes` set to 0. Registration is a staff or admin action; a member cannot self-register.

No member may float until they have completed a first-time **orientation** and signed the current waiver. An orientation is scheduled against a specific member and a specific supervising attendant by providing the `member_id`, the `attendant_id`, a `start_utc`, an `end_utc` (which must be strictly after `start_utc`), and an optional `waiver_version` (the version of the waiver text presented, defaulting to 1, and required to be at least 1). A scheduled orientation begins in `SCHEDULED` status. The platform refuses to schedule an orientation whose `[start_utc, end_utc)` interval overlaps another `SCHEDULED` orientation already booked on the same attendant, rejecting the clash with `ERR_ATTENDANT_TIME_CONFLICT`.

Completing an orientation moves it from `SCHEDULED` to `COMPLETED` and may only happen once the current time has reached the orientation's `start_utc` (the current time is at or after `start_utc`); an attempt before then is an illegal transition. Completion is the moment the waiver is recorded: it writes the orientation's `waiver_version` onto the member's `waiver_signed_version` and flips the member's `orientation_completed` to true. A scheduled orientation may instead be cancelled, moving it from `SCHEDULED` to `CANCELLED` and freeing the attendant's interval so the slot can be reused; the member may cancel their own orientation, and staff or admins may cancel any. Both completion and cancellation are only defined from `SCHEDULED`; attempting them from any other status yields `ERR_INVALID_STATE`.

### 3.3. Memberships, Credits, and the Billing Cycle

A **membership** ties a member to a plan and is opened by staff with a `member_id` and a `plan_id`. It is born in `PENDING` status with `cycle_index` at 0 and `credit_balance` at 0, holding no credits and granting no benefits until it is activated.

**Activation** moves a membership to `ACTIVE`. It is defined from two starting points. From `PENDING`, activation requires that the membership's plan still be open to new memberships — its `active` flag must be true — and a plan that is no longer active rejects activation with `ERR_PLAN_INACTIVE`. A first activation sets `cycle_index` to 0, sets `cycle_start_utc` to the current time, sets `cycle_end_utc` to the current time plus the standard cycle length of thirty days, captures the plan's `monthly_fee_cents` into `monthly_fee_cents_snapshot` (pinned there for later proration math), appends a credit-ledger grant of the plan's `included_floats_per_cycle` (a `GRANT` entry with a positive `delta` equal to that count and no source booking), and recomputes the membership's `credit_balance` from its ledger. The other starting point is a return from `PAST_DUE` to `ACTIVE`, which simply unfreezes credit consumption and does not re-grant floats or move the cycle window.

A membership that has fallen behind is moved from `ACTIVE` to `PAST_DUE` by staff; while `PAST_DUE` the credit balance is frozen and no new consumption is permitted. Returning it to `ACTIVE` (the second activation path above) lifts the freeze.

**Renewal** advances an `ACTIVE` membership by one billing cycle and is the optimistic-concurrency-guarded operation of §2.10: the request carries `expected_membership_version`, which must match the membership's current `version`, failing with `ERR_STALE_VERSION` otherwise. Renewal also requires the membership to be `ACTIVE`. These two checks are ordered per §2.7's general precedence — the `ACTIVE` state requirement is evaluated first (failing a non-`ACTIVE` membership with `ERR_INVALID_STATE`), and only on an `ACTIVE` membership is the `expected_membership_version` compared (failing a mismatch with `ERR_STALE_VERSION`). The credit math at renewal follows a strictly pinned order. First the platform measures the overflow above the cap: the overflow is the pre-renewal `credit_balance` minus the plan's `rollover_cap`, floored at zero. If that overflow is positive, an `EXPIRE` ledger entry is appended first, with a `delta` equal to the negative of the overflow, so that the balance lands exactly on `rollover_cap`. Then a `GRANT` ledger entry is appended for the plan's `included_floats_per_cycle` floats. The net effect is that the post-renewal balance equals the smaller of the pre-renewal balance and the cap, plus the newly granted floats. After the ledger writes, the membership recomputes its `credit_balance`, advances `cycle_index` by one, slides `cycle_start_utc` to the old `cycle_end_utc`, pushes `cycle_end_utc` forward by another thirty days, and increments its `version` by one.

**Cancellation** is available to the owning member or to staff and is defined from any state that is not already `CANCELLED`; cancelling an already-cancelled membership is an illegal transition. Cancellation cascades in order: if the `credit_balance` is positive, a `FORFEIT` ledger entry is appended first with a `delta` equal to the negative of the whole balance, and that insert recomputes the balance to zero; then the platform computes the cancellation's refund value (see §3.7) and, when that value warrants it, emits a refund payment. Cancellation is terminal — a `CANCELLED` membership accepts no further transitions.

Every credit movement in this section is recorded as a `CreditLedgerEntry`. Such an entry names the `membership_id` it adjusts, optionally a `booking_id` (the source booking for a `CONSUME`, and null for `GRANT`, `FORFEIT`, and `EXPIRE`), a `reason` (one of `GRANT`, `CONSUME`, `FORFEIT`, or `EXPIRE`), and a signed `delta` (positive for `GRANT`, negative for `CONSUME`, `FORFEIT`, and `EXPIRE`). The credit-ledger listing is filterable by `membership_id` or `booking_id`.

### 3.4. Tank Health: Operational and Sanitation Axes

The operational axis is staff-of-record territory for admins. A tank moves from `IN_SERVICE` to `MAINTENANCE` when pulled for service, and back from `MAINTENANCE` to `IN_SERVICE` when returned; each transition is defined only from the opposite state. While a tank is `MAINTENANCE` it cannot accept new bookings, independent of its sanitation state. A tank may be retired from either `IN_SERVICE` or `MAINTENANCE`, moving to the terminal `RETIRED` state, but retirement is refused while any booking on that tank is still live — that is, in `RESERVED`, `CONFIRMED`, `RESCHEDULED`, or `CHECKED_IN` — and such an attempt is rejected with `ERR_TANK_HAS_BOOKINGS`. Retiring an already-retired tank is an illegal transition; a `RETIRED` tank is permanently unbookable.

The sanitation axis is system-driven. A tank flips from `CLEAN` to `IN_CYCLE` automatically the moment a sanitation cycle begins running on it, and returns to `CLEAN` only when every running cycle on it has finished. A **sanitation cycle** names its `tank_id`, an optional `booking_id` (the session that triggered the turnover, or null for a manually scheduled deep clean), a `kind` of either `TURNOVER` (the automatic post-session cleaning) or `DEEP_CLEAN` (a manual, scheduled treatment), a `status` that begins at `IN_PROGRESS`, a `started_utc` stamped from the clock at creation, an `ends_utc` equal to `started_utc` plus the cycle's `duration_minutes`, and that `duration_minutes` itself (which for an automatic turnover defaults to the tank's `turnover_buffer_minutes`, and which on a manual cycle defaults to the tank's `turnover_buffer_minutes` when omitted and must be zero or greater — a negative `duration_minutes` is rejected with `ERR_INVALID_REQUEST` as a well-formedness failure rather than `ERR_VALIDATION_RANGE`, since a sanitation cycle is not configuration creation under §3.1/§3.6). Staff may start a manual deep clean directly; doing so creates the cycle `IN_PROGRESS` and flips the tank's `sanitation_status` from `CLEAN` to `IN_CYCLE`.

Completing a sanitation cycle moves it from `IN_PROGRESS` to `COMPLETED` and is gated on time: the current time must have reached the cycle's `ends_utc` (the current time is at or after `ends_utc`), and a premature completion is refused with `ERR_TIMING_NOT_ALLOWED`. On completion, if no other `IN_PROGRESS` cycle remains on the tank, the tank's `sanitation_status` returns to `CLEAN`; if another cycle is still running, the tank stays `IN_CYCLE`. Sanitation listing is filterable by `tank_id` or `booking_id`. The interplay between sanitation and the booking lifecycle — how a completed session spins up a turnover and how that turnover can sweep away conflicting reservations — is detailed in §3.6.

### 3.5. Booking a Float: Creation, Pricing, and the Deposit

A **booking** reserves a specific tank for a specific member over a specific window. Creating one requires a `member_id` (the floater, or the primary member for a couples session), a `tank_id`, a `session_minutes` value of either 60 or 90, a `start_utc`, and a `pay_source` of `CREDIT`, `GIFT_CARD`, or `CASH`. Three more inputs are conditional: an optional `membership_id` (the membership whose credits pay for a `CREDIT` session, null for a cash drop-in), an optional `is_couples` flag (defaulting to false, marking a couples/dual-tank booking), and an optional `gift_card_id` (required when paying by gift card, null otherwise). A new booking is created `RESERVED`, and its `end_utc` is computed as `start_utc` plus `session_minutes`; the tank is treated as occupied across the half-open span from `start_utc` to `end_utc` plus the tank's `turnover_buffer_minutes`, so that the cleaning buffer is reserved along with the session itself. A freshly created booking carries `final_charge_cents` of `0` and `credits_consumed` of `0`; these are populated later, at completion and at a credit-funded check-in respectively.

Several referential rules guard creation. A couples booking (`is_couples` true) must be placed on a `DUAL` tank; a `GIFT_CARD` payment must supply a `gift_card_id`; and a `CREDIT` payment must supply a `membership_id`. Any of these combinations being violated is rejected with `ERR_TANK_KIND_MISMATCH`. When the chosen `pay_source` is `GIFT_CARD`, the referenced card must be `ACTIVE` — neither `VOID` nor `DEPLETED` — and a non-active card is refused with `ERR_GIFT_CARD_INACTIVE`. The booking window must not collide with any other active booking on the same tank: if the new occupancy span (session plus turnover buffer) overlaps the span of another live booking on that tank, creation is rejected with `ERR_TANK_TIME_CONFLICT`. The booking list is filterable by `member_id`, `tank_id`, `membership_id`, `gift_card_id`, and `status`.

At creation the platform computes two amounts and takes a deposit. The **deposit** (`deposit_cents`) is a flat twenty dollars — two thousand cents — and is doubled to four thousand cents for a couples booking. Taking the deposit records a deposit-hold payment whose funding instrument mirrors the booking: a `GIFT_CARD` booking holds the deposit against the card (debiting it), while every other booking holds against `CASH`. The **provisional charge** (`provisional_charge_cents`) is the platform's estimate of the session price, computed once at creation from the booked `session_minutes` and never recomputed afterward. The plan supplying the base figures below is the one resolved through the booking's `membership_id` (the plan its membership is opened on); a booking that carries no `membership_id` has no plan to read, so its `provisional_charge_cents` is `0` and the order below is skipped entirely. When a plan is present it is built up in a fixed order: start from the plan's `retail_float_cents` as the base; if the booked session is 90 minutes, multiply the base by the ninety-minute multiplier of 1.4 and round to the nearest cent; if the booking is couples, double the base; and finally, if the booking carries a membership whose status is `ACTIVE`, multiply by one minus the plan's `member_discount_pct` and round to the nearest cent — the member discount is therefore applied *after* the couples doubling. Each `Payment` row written for a booking carries the `booking_id`, optionally a `gift_card_id` when funded by a card, a `kind` (one of `DEPOSIT_HOLD`, `DEPOSIT_REFUND`, `LATE_FEE`, `NO_SHOW_FEE`, `SESSION_CHARGE`, or `SESSION_REFUND`), a `source` of `GIFT_CARD` or `CASH` mirroring the booking instrument, and a signed `amount_cents` where a positive value is money taken from the member or card and a negative value is money returned. The payment listing is filterable by `booking_id` or `gift_card_id`.

A **gift card** is the prepaid instrument behind the `GIFT_CARD` pay source. Staff issue one with a unique `code` and an `initial_balance_cents` face value that must be strictly greater than zero; the card is born `ACTIVE` with its `remaining_balance_cents` equal to `initial_balance_cents`, and its remaining balance is thereafter reconciled from gift-card payments exactly as described in §2.9. A card's `status` moves to `DEPLETED` automatically when its remaining balance reaches zero, and an administrator may `VOID` a card outright. The depletion is itself reversible: if a later refund payment restores a `DEPLETED` card's remaining balance above zero, the card's `status` automatically returns to `ACTIVE`; a `VOID` card, by contrast, is never auto-revived by a refund. A booking that names a card which is not `ACTIVE` is refused as covered in §3.5. The gift-card list is filterable by `code`.

### 3.6. The Session Lifecycle: Confirm, Reschedule, Check-In, Complete

Before a reserved booking can proceed it must be **confirmed**, moving it from `RESERVED` to `CONFIRMED`. Confirmation is the eligibility gate: the member must have completed orientation (`orientation_completed` true), must have signed a waiver whose version is at least the current waiver version of 1 (the member's `waiver_signed_version` is at or above that number), and must not be suspended (the member's `status` is `ACTIVE`). A booking that fails any of these is refused with `ERR_MEMBER_NOT_ELIGIBLE`. The deposit recorded at creation simply remains held through confirmation. A booking may also be confirmed out of the `RESCHEDULED` state, which cycles it back to `CONFIRMED` after a time change — this is the reschedule cycle, and confirmation is defined from both `RESERVED` and `RESCHEDULED`. The eligibility gate is evaluated *only* on the first-entry `RESERVED`→`CONFIRMED` transition; the `RESCHEDULED`→`CONFIRMED` re-confirmation carries no eligibility precondition and never raises `ERR_MEMBER_NOT_ELIGIBLE`.

A `CONFIRMED` booking may be **rescheduled** to a new start time, supplied as `new_start_utc`, which moves it to `RESCHEDULED` and recomputes its window (`start_utc` and `end_utc` shift to the new times) while leaving the deposit untouched — money is conserved across a reschedule. Rescheduling is allowed only while there is enough lead time: the current time must be at or before the booking's `start_utc` minus the reschedule cutoff of twelve hours. Past that cutoff the reschedule is refused with `ERR_TIMING_NOT_ALLOWED`. The new window is also overlap-checked exactly as creation is — the proposed span plus turnover buffer must not collide with another active booking on the tank, or the move is rejected with `ERR_TANK_TIME_CONFLICT`.

**Check-in** moves a `CONFIRMED` booking to `CHECKED_IN` and is a front-desk action. It may not happen too early: the current time must be at or after the booking's `start_utc` minus the check-in lead of sixty minutes. The tank must be available on both axes — `IN_SERVICE` operationally and `CLEAN` on sanitation — and a tank failing either is refused with `ERR_TANK_UNAVAILABLE`. For a credit-funded session the membership must be `ACTIVE` and must hold enough credits: the credits required are 1 for a solo booking and 2 for a couples booking, and a balance below that requirement is refused with `ERR_INSUFFICIENT_FUNDS`; likewise a gift-card session whose card balance is below the provisional charge is refused with the same insufficient-funds error. On a successful credit check-in the platform appends a `CONSUME` ledger entry whose `delta` is the negative of the credits required, records that count in `credits_consumed`, and recomputes the membership's `credit_balance`. On a successful gift-card check-in the platform records a `SESSION_CHARGE` payment against the card for the provisional charge and recomputes the card's `remaining_balance_cents`.

**Completion** moves a `CHECKED_IN` booking to `COMPLETED` and settles the session. It first computes the **final charge** (`final_charge_cents`) from the realized session length (which defaults to the booked `session_minutes`). The plan supplying the base is resolved through the booking's `membership_id` exactly as the provisional charge is in §3.5; a booking that carries no `membership_id` has no plan to read, so its `final_charge_cents` is `0` and the order below is skipped entirely. When a plan is present: start from the plan's `retail_float_cents`; if the realized session is 90 minutes, multiply by the ninety-minute multiplier of 1.4 and round to the nearest cent; if the booking is couples, double the base and then add the couples surcharge of fifteen hundred cents; and if the booking carries an `ACTIVE` membership, multiply by one minus the plan's `member_discount_pct` and round to the nearest cent. The couples surcharge is applied *only* at final settlement and is absent from the provisional estimate, so for a couples booking that has a plan the final charge and the provisional charge necessarily differ. Completion then runs the turnover cascade in order: it creates a `TURNOVER` sanitation cycle on the tank (carrying the `tank_id` and this `booking_id`, an `IN_PROGRESS` status, and a `duration_minutes` equal to the tank's `turnover_buffer_minutes`); that cycle's creation flips the tank's `sanitation_status` from `CLEAN` to `IN_CYCLE`; and the tank entering `IN_CYCLE` then auto-cancels every still-`RESERVED` booking on that tank whose `start_utc` falls before the new cycle's `ends_utc`, moving each such booking to `CANCELLED` and refunding its deposit with a `DEPOSIT_REFUND` payment. Finally, the completing booking's own deposit is released with a `DEPOSIT_REFUND` payment.

### 3.7. Cancellations, No-Shows, Strikes, and Refund Valuation

A booking that has not yet been used may be **cancelled** by the owning member or by staff. Cancellation is defined from `RESERVED`, `CONFIRMED`, and `RESCHEDULED`; it is deliberately *not* available from `CHECKED_IN`, because by check-in any credits have already been consumed, and an attempt to cancel a checked-in booking is an illegal transition. The deposit outcome turns on timing. A **timely** cancellation — where the current time is at or before the booking's `start_utc` minus the cancellation cutoff of twenty-four hours — refunds the deposit in full, recording a `DEPOSIT_REFUND` payment whose `amount_cents` is the negative of `deposit_cents` against the booking's funding instrument. A **late** cancellation — where the current time is past that twenty-four-hour cutoff — forfeits the deposit in full, recording a `LATE_FEE` payment whose `amount_cents` is the positive `deposit_cents` against the same instrument. When the booking was funded by a gift card, the `DEPOSIT_REFUND` carries a negative amount on the card and thereby restores the card's balance, so that a hold followed by a timely refund leaves the card exactly where it started.

A confirmed booking whose floater never arrives is marked a **no-show**, moving it from `CONFIRMED` to `NO_SHOW`. This is a front-desk action allowed only after the grace period: the current time must be at or after the booking's `start_utc` plus the no-show grace of fifteen minutes, and an early attempt is refused with `ERR_TIMING_NOT_ALLOWED`. A no-show forfeits the deposit by recording a `NO_SHOW_FEE` payment for the positive `deposit_cents`, and it strikes the member: the member's `no_show_strikes` increases by one, and once that count reaches the suspension threshold of three the member's `status` flips to `SUSPENDED`. A suspended member is blocked at the confirmation gate of §3.6 until reinstated.

When a membership is cancelled (per §3.3), the platform values the unused portion of the current cycle to decide the refund. The authoritative valuation is a forward-looking proration of the captured monthly fee: take `monthly_fee_cents_snapshot`, multiply by the number of whole days remaining in the cycle, divide by the total cycle length of thirty days, and round to the nearest cent. The days remaining are computed as the number of whole days from the current time to `cycle_end_utc`, rounded up to the next whole day and floored at zero. This prorated value is the refund amount that is emitted; when it is positive, the cancellation records a `SESSION_REFUND` payment — a `CASH`-source row carrying no `booking_id` and no `gift_card_id`, whose `amount_cents` is the negative of the prorated refund (money returned). (A consumed-basis alternative — the monthly fee minus the retail value of floats already consumed this cycle — is explicitly *not* the figure emitted; the forward-looking proration above is authoritative, and the two diverge for the same inputs.)

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource — including every state-machine transition and the logical-clock control — return `200 OK`. The request body, response body, and side effects of each endpoint are described in §3; the table below is only a routing and authorization summary. Reads of a specific resource and list reads return `200 OK`. Where a role column lists several roles, the hierarchical override of §2.1 applies; "ownership-scoped" notes where a `Member` is additionally limited to their own resources.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |
| POST | `/plans` | Create a membership plan | Admin |
| GET | `/plans/{id}` | Get a plan | Admin, FrontDesk, Member |
| GET | `/plans` | List plans | Admin, FrontDesk, Member |
| POST | `/members` | Register a member | Admin, FrontDesk |
| GET | `/members/{id}` | Get a member | Admin, FrontDesk, Member |
| GET | `/members` | List members | Admin, FrontDesk |
| POST | `/memberships` | Open a membership for a member on a plan | Admin, FrontDesk |
| GET | `/memberships/{id}` | Get a membership | Admin, FrontDesk, Member |
| GET | `/memberships` | List memberships (filter by member or plan) | Admin, FrontDesk, Member |
| POST | `/memberships/{id}/activate` | Activate a PENDING or PAST_DUE membership | Admin, FrontDesk |
| POST | `/memberships/{id}/renew` | Renew (advance one billing cycle); OCC-guarded | Admin, FrontDesk |
| POST | `/memberships/{id}/mark-past-due` | Mark an ACTIVE membership PAST_DUE | Admin, FrontDesk |
| POST | `/memberships/{id}/cancel` | Cancel a membership | Admin, FrontDesk, Member |
| GET | `/credit-ledger/{id}` | Get a single credit-ledger entry | Admin, FrontDesk, Member |
| GET | `/credit-ledger` | List credit-ledger entries (filter by membership or booking) | Admin, FrontDesk, Member |
| POST | `/tanks` | Create a tank/pod | Admin |
| GET | `/tanks/{id}` | Get a tank | Admin, FrontDesk, Member |
| GET | `/tanks` | List tanks | Admin, FrontDesk, Member |
| POST | `/tanks/{id}/maintenance` | Put a tank into MAINTENANCE | Admin |
| POST | `/tanks/{id}/return-to-service` | Return a tank to IN_SERVICE | Admin |
| POST | `/tanks/{id}/retire` | Retire a tank permanently | Admin |
| POST | `/sanitation-cycles` | Start a manual DEEP_CLEAN cycle on a tank | Admin, FrontDesk |
| GET | `/sanitation-cycles/{id}` | Get a sanitation cycle | Admin, FrontDesk |
| GET | `/sanitation-cycles` | List sanitation cycles (filter by tank or booking) | Admin, FrontDesk |
| POST | `/sanitation-cycles/{id}/complete` | Complete a sanitation cycle | Admin, FrontDesk |
| POST | `/attendants` | Create an attendant | Admin |
| GET | `/attendants/{id}` | Get an attendant | Admin, FrontDesk |
| GET | `/attendants` | List attendants | Admin, FrontDesk |
| POST | `/orientations` | Schedule a first-time orientation | Admin, FrontDesk |
| GET | `/orientations/{id}` | Get an orientation | Admin, FrontDesk, Member |
| GET | `/orientations` | List orientations (filter by member or attendant) | Admin, FrontDesk, Member |
| POST | `/orientations/{id}/complete` | Complete an orientation | Admin, FrontDesk |
| POST | `/orientations/{id}/cancel` | Cancel a scheduled orientation | Admin, FrontDesk, Member |
| POST | `/bookings` | Create a booking (RESERVED) | Admin, FrontDesk, Member |
| GET | `/bookings/{id}` | Get a booking | Admin, FrontDesk, Member |
| GET | `/bookings` | List bookings (filter by member, tank, membership, gift card, status) | Admin, FrontDesk, Member |
| POST | `/bookings/{id}/confirm` | Confirm a RESERVED or RESCHEDULED booking | Admin, FrontDesk, Member |
| POST | `/bookings/{id}/reschedule` | Reschedule a CONFIRMED booking | Admin, FrontDesk, Member |
| POST | `/bookings/{id}/check-in` | Check in a CONFIRMED booking | Admin, FrontDesk |
| POST | `/bookings/{id}/complete` | Complete a CHECKED_IN booking | Admin, FrontDesk |
| POST | `/bookings/{id}/no-show` | Mark a CONFIRMED booking NO_SHOW | Admin, FrontDesk |
| POST | `/bookings/{id}/cancel` | Cancel a RESERVED/CONFIRMED/RESCHEDULED booking | Admin, FrontDesk, Member |
| GET | `/payments/{id}` | Get a single payment entry | Admin, FrontDesk, Member |
| GET | `/payments` | List payment entries (filter by booking or gift card) | Admin, FrontDesk, Member |
| POST | `/gift-cards` | Issue a gift card | Admin, FrontDesk |
| GET | `/gift-cards/{id}` | Get a gift card | Admin, FrontDesk, Member |
| GET | `/gift-cards` | List gift cards | Admin, FrontDesk |
| POST | `/gift-cards/{id}/void` | Void a gift card | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_TANK_KIND_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_INACTIVE` | 409 |
| `ERR_GIFT_CARD_INACTIVE` | 409 |
| `ERR_TANK_HAS_BOOKINGS` | 409 |
| `ERR_TANK_UNAVAILABLE` | 409 |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 |
| `ERR_TANK_TIME_CONFLICT` | 409 |
| `ERR_ATTENDANT_TIME_CONFLICT` | 409 |
| `ERR_TIMING_NOT_ALLOWED` | 409 |
| `ERR_STALE_VERSION` | 412 |
