# Transit Fare Capping API — Product Requirements Document

## 1. Introduction

Modern transit riders rarely buy a paper ticket anymore; they tap a phone or a contactless card at the gate and trust the network to charge them the lowest lawful fare without any further thought. This API is the pricing-and-ledger backend behind that promise. It records every gate tap, prices each one against a stack of overlapping protections — a single-ride fare, a daily spending cap, a weekly spending cap, transfer windows that make a connecting ride free or discounted, a reduced-fare entitlement for seniors, students, and riders with disabilities, and a self-declared low-income discount — and then settles the resulting charge against the rider's mobile payment funding source, optionally drawing on a pre-tax employer commuter benefit allocation known as a Transit FSA.

The two hardest properties the system must hold are *reconciliation* and *order sensitivity*. Every weekly ledger's running total must reconcile exactly with the sum of the charges on the taps that fed it, and that same invariant must survive refunds. Because caps accrue chronologically, the order in which taps are priced is load-bearing: an earlier ride pays full fare and a later ride absorbs the cap credit, never the reverse. The product therefore separates two pricing modes — a canonical, chronological replay used when a payment is actually settled, and a forward-looking estimate used only to quote a fare before a rider taps — and they deliberately diverge whenever a quoted ride would land out of chronological order.

This document specifies the complete contract: the entities and their lifecycles, the pricing and benefit-selection calculations, the validation order, the role model, and the error vocabulary. Unless a rule is stated here, it does not exist; unless a field is named here, it is not part of the payload.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request other than the explicitly public ones must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled precisely as `FareAdmin`, `Rider`, `EmployerAdmin`, `PaymentGateway`, and `Anonymous`. If a protected endpoint is called without both headers, or with an `X-User-Role` that is not one of these five, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed and the role is known but that role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of the public entry points need no credentials: registering a rider and browsing fare products. Registration is performed under the `Anonymous` role, and the fare-product reads are open to every role including `Anonymous`. All other endpoints require authentication.

The roles divide along ownership lines. When `X-User-Role` is `Rider`, the value of `X-User-ID` is the `id` of the acting `Rider` entity; ownership checks on any resource that references a rider compare that resource's `rider_id` to `X-User-ID`. Concretely, when a `Rider` records a tap, fetches a tap, attaches a funding source, applies for a reduced-fare card, or requests a fare quote, the `rider_id` carried by (or implied by) the targeted resource must equal the caller's `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other four roles are operator identities not tied to any persisted entity. When `X-User-Role` is `FareAdmin`, `X-User-ID` is an opaque operator identifier for the transit-authority operator who manages products, fare weeks, card verification, reversals, suspensions, risk review, and the test clock; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `EmployerAdmin`, `X-User-ID` is an opaque identifier for the employer benefits administrator who funds commuter allocations; it likewise is not compared to any entity `id` (the employer's own reference travels in the `employer_ref` field of an allocation, not via the header). When `X-User-Role` is `PaymentGateway`, `X-User-ID` is an opaque identifier for the mobile-payment integration that settles taps, again never matched to an entity `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque, unauthenticated marker that grants only rider registration and public fare-product browsing.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by the resource's `created_at` timestamp in ascending order.

Every list-based response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every entity in this system — `FareProduct`, `Rider`, `FundingSource`, `ReducedFareCard`, `BenefitAllocation`, `FareWeek`, and `Tap` — carries the full standard property set. Each is assigned a unique `id` formatted as a UUID with no type prefix, a `created_at` ISO 8601 UTC timestamp with three fractional digits recording first creation, an `updated_at` ISO 8601 UTC timestamp refreshed on every modification, and an integer `version` that begins at 1 on creation and increments by one with each mutation. The `version` field underpins optimistic concurrency control as described in §2.7.

Any change to a resource — including changes to computed fields such as a fare week's running total or an allocation's consumed amount — is a mutation: it refreshes that resource's `updated_at` and increments its `version`. When a single operation touches several resources at once, each touched resource independently advances its own `updated_at` and `version`.

### 2.5. Money, Precision, and Rounding

All monetary quantities in this system are integer cents; there are no fractional cents anywhere in storage, in request bodies, or in responses. Discount percentages (`transfer_discount_pct`, `reduced_fare_pct`, `low_income_discount_pct`) are the only non-integer numeric inputs, expressed as fractions between 0 and 1.

Wherever a percentage is multiplied into a cent amount — when deriving a per-ride list fare from a base fare, when scaling a daily or weekly cap by a discount, or when computing a transfer discount from a list fare — the product is rounded to the nearest whole cent using the round-half-up convention, and the rounding is applied at each such per-ride multiplication rather than deferred to the end. Caps are compared as integers after they have been scaled and rounded. Because every intermediate amount is already an integer, the cap, transfer, benefit, and out-of-pocket arithmetic that follows is exact integer arithmetic.

### 2.6. The Fare Week Ledger and Reconciliation Invariant

A `FareWeek` is a per-rider weekly ledger that accrues toward the weekly cap. Its `charged_total_cents` is a computed running sum of the out-of-pocket `charge_cents` over the `CAPTURED` taps belonging to that week; it starts at 0, increases by a tap's `charge_cents` when that tap is captured, and decreases by that same amount when a captured tap is later reversed. The reconciliation invariant is absolute: at every moment `charged_total_cents` must equal the sum of `charge_cents` over the week's currently-`CAPTURED` taps, and it is bounded below by 0 and above by the effective weekly cap. Reversal is therefore a true compensating action — it conserves the rider's total out-of-pocket quantity across the week and the benefit-consumed quantity on any allocation it touched.

A fare week also carries the `zone_code` whose caps govern its accrual, copied from the chosen fare product at week creation, and a `status` that is `OPEN` while it accepts activity and `CLOSED` once sealed. A `CLOSED` week rejects new taps as well as settle and reversal attempts.

### 2.7. Optimistic Concurrency Control on Benefit Allocation Supersession

Funding a Transit FSA allocation for a rider and month is the one operation in this system guarded by optimistic concurrency control, and the controlled entity is the `Rider`. A request that funds a new allocation must carry `expected_rider_version`, a non-optional field whose value is the `version` of the target rider that the client last observed. When the request would supersede an existing active allocation for the same rider and month, the server compares `expected_rider_version` against the rider's current `version`; if they do not match — because some other writer has already advanced the rider's `version` since the client read it — the create is rejected with `ERR_STALE_RIDER_VERSION` (HTTP 412), and no allocation is created or superseded. A successful supersede increments the rider's `version` by one, which is precisely why two strictly sequential creates that each present the rider's last-observed version cannot both succeed: the first advances the version, leaving the second presenting a now-stale `expected_rider_version`. No other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.8. Clock, Fare Day, and the Fare Week Window

The system runs against a server clock expressed as a UTC instant. The *fare day* of a tap is the calendar date of its `tapped_at` instant, and the fare-day month is that date's `YYYY-MM`. Clock-dependent behavior — reduced-fare-card expiry, the trailing-week risk window, and the determination of the current fare day — all read this clock. A `FareAdmin` may move the clock to a supplied instant through an administrative test-driving capability that accepts a `to_iso8601` value and reports the new `current_utc`; this is the only way the clock advances.

A fare week opens on a Monday given by `week_start_date` and spans seven calendar days, that Monday through the following Sunday inclusive. A tap accrues into a fare week only when the tap's fare day falls on or after `week_start_date` and on or before the sixth day after `week_start_date`, and the fare week's `zone_code` must match the zone of the product the rider is being priced against; a tap that violates either condition is rejected with `ERR_TAP_WEEK_MISMATCH` (HTTP 422).

### 2.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Role authorization comes second: a known but unpermitted role yields `ERR_FORBIDDEN_ROLE`. Resource ownership comes third: a `Rider` acting on a resource that is not their own yields `ERR_NOT_RESOURCE_OWNER`. Existence comes fourth: every path id and every foreign-key reference in the body is checked left-to-right, and the first that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). Body well-formedness comes fifth: missing required fields, wrong types, or enum values outside their declared sets yield `ERR_INVALID_REQUEST` (HTTP 422). Only after these five layers pass does the system evaluate state-machine legality, week-open status, and the domain-specific business rules described in §3. Within those later layers the relative ordering is also fixed and is stated alongside each workflow where it matters.

### 2.10. Nested Reference Resolution

Several endpoints address a resource by an id in the path and additionally cite other resources by foreign keys in the body. All such references are resolved left-to-right: a path id is checked before body references, and body references are checked in the order they appear, the first unresolved reference producing `ERR_NOT_FOUND`. This ordering means, for example, that recording a tap validates the rider before the fare week, and the fare week before the funding source, so a non-existent rider surfaces ahead of a non-existent funding source.

## 3. Business Logic & Workflows

### 3.1. Fare Products: Defining a Zone's Price Schedule

Everything a rider is charged ultimately derives from a `FareProduct`, the price schedule for a fare zone, created by a `FareAdmin`. A product is created with a `zone_code` — an uppercase alphanumeric identifier that must be unique among products currently in the `ACTIVE` status — and the cent amounts that anchor pricing: the `base_fare_cents`, which is the full single-ride fare before any discount and must be zero or greater; the `daily_cap_cents`, the most a standard rider pays across one calendar day in the zone, which must be at least the base fare; and the `weekly_cap_cents`, the most a standard rider pays across one fare week, which must be at least the daily cap.

A product also configures three discount behaviors, each optional at creation with a defined default. The `transfer_window_minutes`, the number of minutes after a charged tap during which a following tap qualifies as a transfer, must be greater than zero and defaults to 120. The `transfer_discount_pct`, the fraction of the base fare removed from a qualifying transfer tap, must be between 0.0 and 1.0 inclusive and defaults to 1.0, where 1.0 means the transfer is free. The `reduced_fare_pct`, the fraction discount applied to the base fare and to both caps for a rider holding a verified reduced-fare card, must be at least 0.0 and strictly less than 1.0 and defaults to 0.5.

A new product is born `ACTIVE`, the value of its system-managed `status`, which is either `ACTIVE` or `RETIRED`. Only `ACTIVE` products may be referenced by new taps. A `FareAdmin` may retire a product, moving its `status` to `RETIRED`; once retired it can no longer back new taps. Products are listable and individually fetchable by anyone, including unauthenticated callers, and the listing may be filtered by `zone_code` or `status`.

### 3.2. Riders, Their Discounts, and Account State

A rider self-registers — this is the one creation open to the `Anonymous` role — by supplying an `email` that must be non-empty and unique across all riders, a `full_name`, and a `home_zone_code` that must match the `zone_code` of an `ACTIVE` fare product at the time of registration. Two discount-related inputs are optional. The `income_tier` is the rider's self-declared tier, either `STANDARD` or `LOW_INCOME`, defaulting to `STANDARD`. The `low_income_discount_pct` is the fraction discount applied to the base fare and to both caps when the tier is `LOW_INCOME`, ignored otherwise; it must be at least 0.0 and strictly less than 1.0 and defaults to 0.5. A freshly registered rider has `status` `ACTIVE` (the other value being `SUSPENDED`) and `version` 1.

A `FareAdmin` may suspend a rider, moving `status` to `SUSPENDED` and incrementing the rider's `version`; a suspended rider cannot tap. A rider's record is fetchable by a `FareAdmin`, an `EmployerAdmin`, or the rider themselves.

A `FareAdmin` may also pull a rider's behavioral **risk score**, a read-time recompute on the rider domain that yields an integer in the range 0 through 100 used to flag accounts for manual review. The score weights three behavioral signals: each tap recorded in `REJECTED` status (an insufficient-funds rejection) contributes 15 points, each tap in `REVERSED` status contributes 8 points, and a low-balance flag contributes 20 points. The low-balance flag is 1 when the rider's default active funding source holds a `prepaid_balance_cents` below 500, and 0 otherwise. The three contributions are summed, the sum is rounded half up, and the result is then clamped so it never exceeds 100. The endpoint accepts an optional `mode`. In `gross` mode it counts every rejected and every reversed tap ever recorded for the rider. In `trailing_week` mode — the default when `mode` is omitted — it counts only rejected and reversed taps whose `tapped_at` falls within the seven days ending at the current clock instant, which produces a different number than `gross` whenever older incidents exist. The response reports the `rider_id`, the computed `rider_risk_score`, and the `mode` that was applied.

### 3.3. Funding Sources: Mobile Payment and Stored Value

Before a rider can be charged, they attach at least one `FundingSource`, a mobile payment channel that also holds stored value. A `Rider` creates a funding source against their own `rider_id`, choosing a `source_type` of `APPLE_PAY`, `GOOGLE_PAY`, or `CONTACTLESS_CARD`, and optionally marking it as default through `is_default`, which defaults to true; exactly one funding source is the rider's default after registration. A new source starts with `status` `ACTIVE` (the alternative being `REMOVED`) and a `prepaid_balance_cents` of 0.

Stored value is added through a load operation, available to the owning `Rider` and to a `FareAdmin`, which takes an `amount_cents` and increases `prepaid_balance_cents` by that amount while incrementing the source's `version`. The balance is the pool from which captured taps are debited and to which reversed taps are credited; it must never go below 0. Funding sources are listable, filterable by `rider_id`, and individually fetchable — the single fetch surfaces the current `prepaid_balance_cents` — by a `FareAdmin` or the owning rider.

### 3.4. Reduced-Fare Cards: The Verify / Expire Cycle

A rider who is a senior, a student, or a person with a disability may hold a `ReducedFareCard` that unlocks the product's reduced fare. A `Rider` applies for a card against their own `rider_id`, naming the `program_code` — one of `SENIOR`, `DISABILITY`, or `STUDENT` — and an `expires_on` date in `YYYY-MM-DD` form. The card is created in `PENDING_VERIFICATION` status and the server issues a `verification_token`; the lifecycle states are `PENDING_VERIFICATION`, `VERIFIED`, `EXPIRED`, and `REVOKED`. Only a `VERIFIED`, unexpired card grants the reduced fare. Cards are listable (filterable by `rider_id`) and individually fetchable by a `FareAdmin` or the owning rider.

Verification is a `FareAdmin` action. To move a card from `PENDING_VERIFICATION` to `VERIFIED`, the admin must echo back the exact `verification_token` the server issued; a mismatched token is rejected with `ERR_BAD_VERIFICATION_TOKEN` (HTTP 422). The card's `expires_on` must also be on or after the current fare day, otherwise verification is rejected with `ERR_CARD_EXPIRED` (HTTP 409). Verification is also defined out of the `EXPIRED` state under the same two preconditions — matching token and `expires_on` on or after the current fare day — so an expired card can be brought back to `VERIFIED`. Attempting to verify a card that is in neither `PENDING_VERIFICATION` nor `EXPIRED` is an `ERR_INVALID_STATE` (HTTP 409).

A `VERIFIED` card becomes `EXPIRED` when its `expires_on` is strictly before the current fare day. This transition fires when the clock is advanced past the card's expiry, and it can also be forced by a `FareAdmin` through a refresh-expiry capability that re-evaluates a `VERIFIED` card against the current clock and moves it to `EXPIRED` exactly when `expires_on` is strictly before the current fare day. Because expiry is reversible, the lifecycle forms a cycle: a `FareAdmin` may extend a card's `expires_on` (a renewal that updates `expires_on` and increments the card's `version`), after which the card may be verified again, closing the loop `VERIFIED → EXPIRED → VERIFIED`. Finally, a `FareAdmin` may revoke a card from any of `PENDING_VERIFICATION`, `VERIFIED`, or `EXPIRED`, moving it to the terminal `REVOKED` status; a revocation request against a card already `REVOKED` is an `ERR_INVALID_STATE`.

### 3.5. Transit FSA Benefit Allocations and Supersession

An `EmployerAdmin` funds a rider's commuter benefit by creating a `BenefitAllocation`, a pre-tax Transit FSA grant scoped to one calendar month. The create supplies the `rider_id`, an opaque `employer_ref` chosen by the funding employer, a `period_month` in `YYYY-MM` form naming the month the allocation may subsidize, the `allocated_cents` of pre-tax dollars granted, and the `expected_rider_version` required for concurrency control. The allocation also exposes `consumed_cents`, a computed total of how much of the grant has already been applied to captured taps, which begins at 0; it is the sum of `benefit_applied_cents` over the `CAPTURED` taps that cite this allocation, and it is credited back on reversal. A `consumed_cents` value never drops below 0 nor rises above `allocated_cents`. The allocation's `status` is `ACTIVE`, `SUPERSEDED`, or `EXHAUSTED`, beginning `ACTIVE`.

Two business constraints guard the grant amount and the per-month uniqueness. The `allocated_cents` must be greater than 0 and must not exceed the regulatory Transit FSA monthly maximum, which is fixed at 32500 cents; an amount strictly above that 32500-cent ceiling is rejected with `ERR_FSA_CAP_EXCEEDED` (HTTP 422). At most one `ACTIVE` allocation may exist for a given rider and `period_month`. When no active allocation yet exists for that pair, the create simply produces a new `ACTIVE` allocation with `consumed_cents` reset to 0. When an active allocation already exists for the pair, the create legitimately *supersedes* it: the new grant replaces the old. Supersession requires the optimistic-concurrency check of §2.7 — `expected_rider_version` must equal the rider's current `version`, failing which the create is rejected with `ERR_STALE_RIDER_VERSION` (HTTP 412). A valid supersede sets the prior allocation's `status` to `SUPERSEDED`, creates the replacement as `ACTIVE` with its `consumed_cents` reset to 0 (the consumed amount is **not** carried over from the superseded allocation), and increments the rider's `version` by one. Because `expected_rider_version` is a mandatory body field, a create against an existing active allocation always takes the supersede path: a missing or non-integer `expected_rider_version` is caught earlier as `ERR_INVALID_REQUEST` at the body-well-formedness layer, and a present-but-mismatched version fails the optimistic-concurrency check with `ERR_STALE_RIDER_VERSION` (HTTP 412); the create never falls through to a duplicate-rejection branch, so `ERR_DUPLICATE_ALLOCATION` is not emitted by this endpoint. Allocations are listable, filterable by `rider_id` or `period_month`, and individually fetchable — the single fetch surfaces `consumed_cents` and `status` — by a `FareAdmin`, an `EmployerAdmin`, or the rider.

An allocation also moves through two system-driven states tied to tap settlement. When a capture applies benefit and the resulting `consumed_cents` reaches `allocated_cents`, the allocation transitions from `ACTIVE` to `EXHAUSTED` and stops being eligible to subsidize future taps. When a later reversal decrements `consumed_cents` back below `allocated_cents`, an `EXHAUSTED` allocation returns to `ACTIVE`. Both transitions refresh the allocation's `updated_at` and `version`.

### 3.6. Opening a Fare Week and Recording a Tap

A fare week must exist before its taps can be recorded. A `Rider` or a `FareAdmin` opens one by supplying the `rider_id`, the `week_start_date`, which must be a Monday and must be unique per rider and week-start, and the `zone_code` whose product caps will govern the week. The new week is `OPEN` with `charged_total_cents` of 0. Weeks are listable (filterable by `rider_id`) and individually fetchable — the single fetch surfaces `charged_total_cents` — by a `FareAdmin` or the owning rider.

Recording a tap is a `Rider` action against their own account. The tap payload carries the `rider_id`, the `fare_week_id` of the open week the tap accrues into, the `funding_source_id` of the mobile source that will be debited at settle time, and the `tapped_at` instant in ISO 8601 UTC, which fixes the fare day, transfer-window membership, and chronological accrual order. A tap is created in `PENDING` status — the states being `PENDING`, `CAPTURED`, `REJECTED`, and `REVERSED` — and is **not** priced at creation; pricing happens at settle. At creation the system enforces that the cited week is `OPEN`, rejecting a tap against a `CLOSED` week with `ERR_WEEK_CLOSED` (HTTP 409), and that the tap's fare day lies within the week's seven-day window and that the week's `zone_code` matches the rider's product zone, rejecting a mismatch with `ERR_TAP_WEEK_MISMATCH` (HTTP 422). A `Rider` who is `SUSPENDED` cannot tap. Taps are listable — filterable by `rider_id`, `fare_week_id`, `funding_source_id`, `benefit_allocation_id`, or `status` — and individually fetchable by a `FareAdmin` or the owning rider; the single fetch returns the full computed charge breakdown.

### 3.7. Settling a Tap: Chronological Pricing and the Ledger Debit

Settlement is a `PaymentGateway` action that prices a `PENDING` tap and resolves it to either `CAPTURED` or `REJECTED`. Settlement is defined only out of `PENDING` (otherwise `ERR_INVALID_STATE`); it requires the owning rider to be `ACTIVE`, the funding source to be `ACTIVE`, and the cited fare week to be `OPEN` — a settle against a `CLOSED` week is `ERR_WEEK_CLOSED`. The price is computed by chronologically replaying the rider's prior captured taps in the same fare day and the same week, so the result depends on the order in which taps were taken: a later-tapped ride absorbs cap credit while an earlier one pays the fuller fare.

The charge is built in four pinned steps, all in integer cents. **First**, the effective per-ride list fare. The system starts the effective discount fraction at 0. If the rider holds a `VERIFIED` reduced-fare card whose `expires_on` is on or after the fare day, the effective discount becomes the product's `reduced_fare_pct`. If the rider's `income_tier` is `LOW_INCOME`, the effective discount becomes the larger of its current value and the rider's `low_income_discount_pct` — the system takes the larger of the two discounts and never sums them. The `list_fare_cents` is then the base fare multiplied by one minus the effective discount fraction, rounded half up to a whole cent.

**Second**, the transfer discount. The system finds the rider's most recent captured tap whose `tapped_at` is strictly before this tap's `tapped_at`, breaking ties on `created_at` ascending (never on id). If such a prior tap exists and the gap from it to this tap is within the product's `transfer_window_minutes`, the `transfer_discount_cents` is the `list_fare_cents` multiplied by the product's `transfer_discount_pct`, rounded half up to a whole cent; otherwise it is 0. The post-transfer amount is `list_fare_cents` minus `transfer_discount_cents`.

**Third**, the cap credit, daily then weekly, with both caps scaled by the same effective discount fraction. The effective daily cap is the product's `daily_cap_cents` times one minus the effective discount, rounded half up; the effective weekly cap is the product's `weekly_cap_cents` times one minus the effective discount, rounded half up. The day-charged-before amount is the sum of `charge_cents` over this rider's captured taps in the same fare day whose `tapped_at` is strictly before this tap's `tapped_at`; the week-charged-before amount is the fare week's current `charged_total_cents`, which already excludes this still-pending tap. The daily room is the effective daily cap minus the day-charged-before amount, floored at 0; the weekly room is the effective weekly cap minus the week-charged-before amount, floored at 0. The billable amount is the smallest of the post-transfer amount, the daily room, and the weekly room. The `cap_credit_cents` is the post-transfer amount minus the billable amount.

**Fourth**, the benefit application, after caps. The benefit selector (§3.8) picks an allocation or returns nothing. If an allocation is selected, `benefit_applied_cents` is the smaller of the billable amount and that allocation's remaining headroom (its `allocated_cents` minus its `consumed_cents`); otherwise `benefit_applied_cents` is 0. The final out-of-pocket `charge_cents` is the billable amount minus `benefit_applied_cents`, which is non-negative by construction. The selected allocation, if any, is recorded as the tap's `benefit_allocation_id`, which is otherwise null.

Once the charge is known, the funds check decides the branch. If the funding source's `prepaid_balance_cents` is greater than or equal to `charge_cents` — that is, the balance is sufficient — the tap is `CAPTURED`: the system debits `prepaid_balance_cents` by `charge_cents`; if `benefit_applied_cents` is greater than 0 it increments the chosen allocation's `consumed_cents` by `benefit_applied_cents`, and if that brings `consumed_cents` up to `allocated_cents` it sets the allocation's `status` to `EXHAUSTED`; it increases the fare week's `charged_total_cents` by `charge_cents`; and it refreshes `updated_at` and `version` on the tap, the funding source, the fare week, and any allocation it touched. If instead the computed `charge_cents` exceeds the funding source's `prepaid_balance_cents` — insufficient funds — the tap takes the divergent branch: its `status` is set to `REJECTED` with `charge_cents` recording the amount that could not be settled, and there is no debit to the funding source and no change to the fare week's `charged_total_cents` or to any allocation. The HTTP response in this case is `ERR_INSUFFICIENT_FUNDS` (HTTP 402), but the tap is nonetheless persisted as `REJECTED` and is discoverable by fetching it afterward — the rejection is recorded, not silently discarded. Only the funds precondition distinguishes the capture branch from the reject branch; the trigger and the computed charge are identical.

### 3.8. Selecting the Benefit Allocation

The benefit selector runs both at settle time, where it chooses the tap's `benefit_allocation_id`, and inside a fare quote. Its candidate set is the `BenefitAllocation` rows that belong to the tap's rider, are in `ACTIVE` status, have a `period_month` equal to the fare day's `YYYY-MM`, and still have remaining headroom — that is, their `allocated_cents` minus `consumed_cents` is greater than 0. Candidates are ranked by remaining headroom descending so the allocation with the most room is preferred, with ties broken by `created_at` ascending so the oldest allocation wins (never by id). The selector returns the first candidate after this ordering. If the candidate set is empty, it selects nothing and the benefit applied is 0.

### 3.9. Quoting a Fare Before Tapping

A `Rider` may request a forward-looking fare quote for their own account without recording or settling anything; the quote persists nothing. The quote payload carries the `rider_id`, the `fare_week_id`, and the `tapped_at` instant. The estimate uses the same discount, transfer, and weekly-room logic as a real settle, but it differs deliberately in how it treats the day's caps because it is forward-looking rather than chronological. Instead of inserting the hypothetical tap into its chronological position, the quote treats it as appended to today's already-captured set regardless of its `tapped_at`. It computes the day's already-captured out-of-pocket total (the sum of `charge_cents` over today's captured taps) and the day's list-fare total (the sum of those taps' `list_fare_cents`), then estimates the marginal charge as the effective daily cap compared against the day's list-fare total plus this tap's own list fare: it takes the smaller of the effective daily cap and that combined list total, subtracts the day's already-charged total, and floors the result at 0. Because it appends rather than chronologically inserting, a tap quoted with a `tapped_at` earlier than an already-captured tap is estimated as carrying cap-credit forward, whereas a real chronological settle would price that same earlier tap at full fare since it has no captured tap before it in time; the two figures diverge precisely when the quoted tap is out of eventual chronological order. The quote response reports the `rider_id`, the `fare_week_id`, the `estimated_charge_cents`, and the breakdown fields `list_fare_cents`, `transfer_discount_cents`, and `cap_credit_cents`.

### 3.10. Reversing a Captured Tap

A `FareAdmin` may reverse a `CAPTURED` tap, a compensating action that undoes the settle's ledger effects. Reversal is defined only out of `CAPTURED` (otherwise `ERR_INVALID_STATE`) and requires the cited fare week to still be `OPEN`; a reversal against a `CLOSED` week is rejected with `ERR_WEEK_CLOSED`. On reversal the system credits the funding source's `prepaid_balance_cents` by the tap's `charge_cents`, decrements the fare week's `charged_total_cents` by that same `charge_cents` so the weekly reconciliation invariant holds, and — if the tap had applied benefit — decrements the relevant allocation's `consumed_cents` by `benefit_applied_cents`, restoring that allocation's `status` to `ACTIVE` if it had been `EXHAUSTED`. The tap moves to the terminal `REVERSED` status, and `updated_at` and `version` are refreshed on the tap, the funding source, the fare week, and any touched allocation. The conserved quantities are the rider's total out-of-pocket across the week and the benefit-consumed amount on the allocation.

### 3.11. Closing a Fare Week

A `FareAdmin` seals a fare week by closing it, a transition defined only out of `OPEN` (otherwise `ERR_INVALID_STATE`). Closing is permitted only when no tap in `PENDING` status references the week; any pending tap must first be settled or the close is refused. Once `CLOSED`, the week refreshes its `updated_at` and `version`, and from then on rejects new taps, settles, and reversals against it with `ERR_WEEK_CLOSED`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify, transition, retire, suspend, load, verify, refresh, revoke, close, settle, reverse, or otherwise act on an existing resource — as well as read operations and the quote, risk, and clock endpoints — return `200 OK`. Request bodies, response bodies, and side effects are specified in §2 and §3; this table lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fare-products` | Create a fare product for a zone with caps, transfer rules, and discounts | FareAdmin |
| GET | `/fare-products` | List fare products; filter by zone_code or status | FareAdmin, Rider, EmployerAdmin, PaymentGateway, Anonymous |
| GET | `/fare-products/{id}` | Fetch a single fare product | FareAdmin, Rider, EmployerAdmin, PaymentGateway, Anonymous |
| POST | `/fare-products/{id}/retire` | Retire a fare product so no new taps may reference it | FareAdmin |
| POST | `/riders` | Register a rider | Anonymous |
| GET | `/riders/{id}` | Fetch a rider | FareAdmin, Rider, EmployerAdmin |
| GET | `/riders/{id}/risk` | Compute the rider's behavioral risk score | FareAdmin |
| POST | `/riders/{id}/suspend` | Suspend a rider account | FareAdmin |
| POST | `/funding-sources` | Attach a mobile payment funding source to a rider | Rider |
| GET | `/funding-sources` | List funding sources; filter by rider_id | FareAdmin, Rider |
| GET | `/funding-sources/{id}` | Fetch a single funding source including its balance | FareAdmin, Rider |
| POST | `/funding-sources/{id}/load` | Load prepaid stored value onto a funding source | Rider, FareAdmin |
| POST | `/reduced-fare-cards` | Apply for a reduced-fare card | Rider |
| GET | `/reduced-fare-cards` | List reduced-fare cards; filter by rider_id | FareAdmin, Rider |
| GET | `/reduced-fare-cards/{id}` | Fetch a single reduced-fare card | FareAdmin, Rider |
| PATCH | `/reduced-fare-cards/{id}` | Extend a card's expires_on | FareAdmin |
| POST | `/reduced-fare-cards/{id}/verify` | Verify a reduced-fare card by echoing its token | FareAdmin |
| POST | `/reduced-fare-cards/{id}/refresh-expiry` | Re-evaluate a card against the current clock | FareAdmin |
| POST | `/reduced-fare-cards/{id}/revoke` | Revoke a reduced-fare card | FareAdmin |
| POST | `/benefit-allocations` | Fund a Transit FSA allocation; supersedes a prior active one for the same month | EmployerAdmin |
| GET | `/benefit-allocations` | List benefit allocations; filter by rider_id or period_month | FareAdmin, EmployerAdmin, Rider |
| GET | `/benefit-allocations/{id}` | Fetch a single benefit allocation | FareAdmin, EmployerAdmin, Rider |
| POST | `/fare-weeks` | Open a fare-capping week ledger | Rider, FareAdmin |
| GET | `/fare-weeks` | List fare weeks; filter by rider_id | FareAdmin, Rider |
| GET | `/fare-weeks/{id}` | Fetch a fare week including charged_total_cents | FareAdmin, Rider |
| POST | `/fare-weeks/{id}/close` | Close a fare week | FareAdmin |
| POST | `/taps` | Record a tap against an open fare week | Rider |
| GET | `/taps` | List taps; filter by rider_id, fare_week_id, or funding_source_id | FareAdmin, Rider |
| GET | `/taps/{id}` | Fetch a single tap with its computed charge breakdown | FareAdmin, Rider |
| GET | `/taps/quote` | Forward-looking pre-tap fare quote without persistence | Rider |
| POST | `/taps/{id}/settle` | Settle a pending tap: price it, debit funds, accrue caps and benefit | PaymentGateway |
| POST | `/taps/{id}/reverse` | Reverse a captured tap | FareAdmin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant | FareAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WEEK_CLOSED` | 409 |
| `ERR_TAP_WEEK_MISMATCH` | 422 |
| `ERR_BAD_VERIFICATION_TOKEN` | 422 |
| `ERR_CARD_EXPIRED` | 409 |
| `ERR_DUPLICATE_ALLOCATION` | 409 |
| `ERR_FSA_CAP_EXCEEDED` | 422 |
| `ERR_STALE_RIDER_VERSION` | 412 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
</content>
</invoke>
