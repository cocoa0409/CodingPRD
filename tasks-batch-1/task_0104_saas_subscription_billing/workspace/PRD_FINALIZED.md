# SaaS Subscription Billing API — Product Requirements Document

## 1. Introduction

This document specifies the SaaS Subscription Billing API, a system that turns recurring software pricing into a fully auditable revenue engine. Billing teams running a multi-tier product face a recurring tension: a plan catalogue with metered overage and add-ons must be priced exactly, while customers continually trial, convert, upgrade, downgrade, pause, and occasionally fail to pay. Each of those events ripples outward — from invoice lines through a revenue-recognition schedule and up into the account's committed monthly recurring revenue — and any drift between these layers shows up as a reconciliation headache at month-end close.

The API is organized around two complementary disciplines. The first is a **pricing engine**: it computes day-granular proration when a customer changes plans, walks marginal tiered bands to price metered overage, and applies coupons and per-jurisdiction tax in a fixed evaluation order. The second is **ledger reconciliation**: every billable event is recorded as an immutable invoice line, finalized invoices feed a ratable revenue schedule, and an account's recurring revenue is continuously recomputed from its live subscription set. A deterministic, test-driven clock and a payment-authorization toggle let operators reproduce renewals, dunning retries, and involuntary churn without waiting for wall-clock time. The result is a contract precise enough that two independent implementations would produce byte-identical invoices, MRR totals, and recognized-revenue figures.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. Where a numeric threshold or formula governs a specific workflow, the precise statement of that rule may also appear in Section 3 alongside the process it controls.

### 2.1. User and Role-Based Access Control

Every request to the API is authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. The system recognizes exactly three roles, spelled precisely as `BillingAdmin`, `AccountOwner`, and `Anonymous`. A request whose `X-User-Role` is missing or malformed — or, for any role other than `Anonymous`, whose `X-User-ID` is missing or malformed — is rejected with `ERR_UNAUTHENTICATED`. A request that is well-authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how `X-User-ID` ties to persisted data. When `X-User-Role` is `AccountOwner`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`. Concretely, an `AccountOwner` may act only on their own account and on subscriptions, invoices, lines, payments, usage records, revenue entries, add-ons, and pause windows that resolve back to that account; an attempt to read or mutate another account's resources is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `BillingAdmin` is the platform operator who owns the plan, add-on, coupon, and tax-jurisdiction catalogues, runs the billing jobs, and may read all data and reporting. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity and is never compared to any entity's `id`; the `Anonymous` role exists solely to register a new account.

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

Endpoints that return collections accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_VALIDATION_RANGE`.

Unless explicitly stated otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits set when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp, likewise to three fractional digits, refreshed on every mutation of the resource. The `version` is an integer that begins at its initial value and increments by one with each mutation; it underpins the optimistic-concurrency mechanism described in Section 2.6.

One entity type is deliberately leaner. A `UsageRecord` is an append-only metering event: it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. Every other entity — `Plan`, `PlanPriceSchedule`, `AddOn`, `Coupon`, `TaxJurisdiction`, `Account`, `Subscription`, `SubscriptionAddOn`, `SubscriptionPauseWindow`, `Invoice`, `InvoiceLine`, `Payment`, and `RevenueScheduleEntry` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer counts of cents; no value is ever represented as a fractional-cent or floating-point number in a response body. Wherever a computation divides — proration over a 30-day cycle, percentage discounts, tax in basis points, and ratable revenue recognition — the result is converted to whole cents using the **round-half-up** rule, meaning a fractional remainder of exactly one-half always rounds upward. Each formula in Section 3 states the exact point at which rounding is applied; rounding is performed once per designated step, never iteratively per line. Tiered overage pricing multiplies integer rates by integer unit counts and therefore needs no rounding at all — its result is exact.

### 2.6. Optimistic Concurrency on Plan Changes

Changing a subscription's plan is the one operation guarded by optimistic concurrency control, because its proration math is computed against the subscription's currently effective plan, its current billing period, and its current add-on set — a basis that a competing plan change would rewrite. The change-plan request must therefore carry `expected_subscription_version`, a non-optional field holding the `version` of the target `Subscription` that the client last observed. If that value does not match the subscription's current `version` — because another change-plan write has since advanced the subscription, legitimately superseding the prior effective plan and rewriting the proration basis — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a client from prorating against a stale basis and overwriting a plan change it never saw. No other endpoint accepts or requires a version field; only change-plan is version-guarded.

### 2.7. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or malformed `X-User-Role` (or `X-User-ID` for non-anonymous callers) yields `ERR_UNAUTHENTICATED`. Authorization is checked next, yielding `ERR_UNAUTHORIZED` when the role is not permitted. The system then confirms that every resource named in the URL path exists, validating identifiers left-to-right (see Section 2.8) and returning `ERR_NOT_FOUND` for the first missing one. After path resolution, any foreign key carried in the request body — `plan_id`, `coupon_id`, or `addon_id` — must resolve to an existing resource, failing with `ERR_REFERENCE_NOT_FOUND`. Next the body itself is validated for well-formedness (required fields present, enums within their allowed sets, numbers within range), failing with `ERR_INVALID_REQUEST`. Uniqueness constraints are then enforced with `ERR_DUPLICATE`. Only after all of the above does the system evaluate state-machine legality, returning `ERR_INVALID_STATE` when the target resource is not in a state that permits the requested transition. The remaining domain-specific business rules — described throughout Section 3 — are evaluated after these foundational checks. The practical consequence is that an existence failure always masks a later state or business failure, and a body-shape failure always masks a later business-rule failure.

### 2.8. Nested Resource Resolution

Several paths address a resource nested beneath a parent — a subscription beneath an account, an add-on or pause window beneath a subscription, lines or payments or a revenue schedule beneath an invoice, price schedules beneath a plan. For any such path the system validates the chain of identifiers strictly left-to-right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve. A request for a subscription under a non-existent account fails on the account before the subscription is ever consulted. Foreign-key references that appear as fields rather than path segments — a subscription's `plan_id`, an account's `tax_jurisdiction_id`, an invoice's `subscription_id`, `coupon_id`, or `tax_jurisdiction_id`, a revenue entry's `subscription_id` — are resolved in the forward direction only and are never reverse-navigated; collections are surfaced exclusively through the dedicated list endpoints of Section 4.

### 2.9. Cascading Reconciliation and Derived Fields

The system maintains two denormalized figures that must always agree with their underlying data. A subscription's `mrr_contribution_cents` is its normalized monthly recurring revenue, and an account's `mrr_cents` is the committed recurring revenue summed across that account's subscriptions. Both are recomputed — never left stale — whenever an event could change them: creating, converting, or canceling a subscription, adding or removing an add-on, or changing a plan. Because a plan change can in a single operation create invoice lines, finalize an invoice, feed the revenue schedule, and shift the account's recurring revenue, the system treats these cascades as one logical unit: when a child fact changes, the parent's derived figure and its `updated_at`/`version` are refreshed in the same operation. Section 3 specifies, for each event, exactly which entities are touched and in which direction the derived totals move.

## 3. Business Logic & Workflows

### 3.1. Building the Catalogue: Plans, Price Schedules, Add-ons, Coupons, and Jurisdictions

A `BillingAdmin` assembles the priceable catalogue before any customer subscribes. A **plan** is created with a `tier` drawn from `BASIC`, `PRO`, or `ENTERPRISE`, a recurring `monthly_fee_cents` that must be zero or greater, a count of `included_usage_units` (zero or greater) that are bundled before any overage applies, and an ordered `overage_tiers` array. It may also carry `trial_days`, the default trial length in days for subscriptions opened on this plan, which is zero or greater and defaults to 0 when omitted. Every plan begins with `status` of `ACTIVE`. A plan's `tier` must be unique among plans that are not archived; a second active plan on the same tier is rejected with `ERR_DUPLICATE`.

The `overage_tiers` array deserves care because it defines marginal pricing. Each band is an object with `up_to_units` and `rate_cents_per_unit`. The `up_to_units` value is a cumulative cap expressed in *overage* units — that is, units counted above `included_usage_units` — and the caps must strictly increase from band to band; the final band carries `up_to_units` of null to denote an unbounded top band. Each band's `rate_cents_per_unit` is the price charged for overage units that fall inside that band. Section 3.6 specifies how these bands are walked at billing time.

To let a plan's price evolve over time, a `BillingAdmin` may attach a **price schedule** to it. Each schedule window records the owning `plan_id`, a scheduled `monthly_fee_cents` (zero or greater) effective during the window, an inclusive `effective_from` instant, and an exclusive `effective_to` instant; the window is the half-open interval that includes `effective_from` and excludes `effective_to`, and `effective_from` must be strictly earlier than `effective_to`. A new window may not overlap any other non-canceled schedule on the same plan by any positive span of time; because the intervals are half-open, two windows that merely touch — where one window's `effective_to` equals the next window's `effective_from` — are permitted, but any overlap of positive measure is rejected with `ERR_PRICE_SCHEDULE_OVERLAP`.

An **add-on** is created with a `code` that must be unique across all add-ons and a recurring `monthly_fee_cents` (zero or greater) that is billed on top of the plan fee; a duplicate code is rejected with `ERR_DUPLICATE`.

A **coupon** carries a `code` unique among coupons that have not expired, a `discount_type` of either `PERCENT` or `FIXED`, and a `duration` of either `ONCE` or `RECURRING`. For a `PERCENT` coupon, `percent_off` is a whole-number percentage between 1 and 100 inclusive and is required, while `amount_off_cents` must be absent; for a `FIXED` coupon, `amount_off_cents` is a cents amount greater than zero and is required, while `percent_off` must be absent. A request that supplies the wrong combination — for example a `PERCENT` coupon missing `percent_off`, or a `FIXED` coupon missing `amount_off_cents`, or `percent_off` outside 1 to 100 — is rejected with `ERR_INVALID_REQUEST`, and a duplicate `code` with `ERR_DUPLICATE`. A `RECURRING` coupon discounts every billing cycle and counts toward recurring revenue, whereas a `ONCE` coupon discounts only the first invoice. A coupon also declares `max_redemptions`, the total number of times it may be redeemed across all accounts, which must be at least 1. The system tracks `redemption_count`, the number of subscriptions that have redeemed the coupon, which starts at 0, and a `status` that begins `ACTIVE` and is automatically set to `EXHAUSTED` once `redemption_count` reaches `max_redemptions`.

A **tax jurisdiction** is created with a `region_code` (such as `US-CA` or `US-NY`) that must be unique, and a `tax_rate_bps` expressed in basis points, where 875 basis points means 8.75 percent; the rate must be at least 0 and at most 10000. A duplicate `region_code` is rejected with `ERR_DUPLICATE`.

Archiving a plan moves its `status` from `ACTIVE` to `ARCHIVED`. An archived plan keeps serving the subscriptions already on it but refuses to accept new subscriptions or to be the target of a plan change; both attempts are rejected with `ERR_PLAN_ARCHIVED` (see Sections 3.2 and 3.5).

### 3.2. Registering Accounts and Opening Subscriptions

Registration is the only `Anonymous` operation. Creating an **account** requires an `email` that is unique across accounts, a `company_name` for display, and a `region_code` that must equal the `region_code` of an existing tax jurisdiction; the optional `payment_method_ok` boolean declares whether the stored card currently authorizes charges and defaults to true. At creation the system resolves the matching jurisdiction and stores its `id` as the account's `tax_jurisdiction_id`; if no jurisdiction has that `region_code` the registration is rejected with `ERR_JURISDICTION_NOT_FOUND`. A duplicate `email` is rejected with `ERR_DUPLICATE`. A new account starts with `status` of `ACTIVE` and `mrr_cents` of 0.

An `AccountOwner` opens a **subscription** on their own account by supplying a `plan_id` and, optionally, a `coupon_id` to redeem. The chosen plan must not be archived, or the request fails with `ERR_PLAN_ARCHIVED`. A subscription tracks two independent status dimensions. The **lifecycle** dimension, `lifecycle_status`, runs `TRIALING`, `ACTIVE`, or `CANCELED` (terminal). The **billing** dimension, `billing_status`, runs `CURRENT`, `PAST_DUE`, or `UNPAID` and evolves on payment outcomes independently of the lifecycle dimension. The subscription also records its `account_id`, the current `period_start` and `period_end`, an optional `trial_end`, the `dunning_attempt` counter, an optional `next_retry_at`, and the computed `mrr_contribution_cents`.

How the subscription opens depends on the plan's trial length. When the plan's `trial_days` is greater than 0, the subscription begins in `TRIALING` with `trial_end` set to the current clock plus `trial_days` days, and no invoice is generated yet; because a trialing subscription's `mrr_contribution_cents` is 0, the account's `mrr_cents` is unchanged. When the plan's `trial_days` is 0, the subscription opens directly in `ACTIVE`: the system sets the billing period, generates and finalizes the first invoice (Section 3.6), attempts the first payment (Section 3.7), recomputes `mrr_contribution_cents`, and bubbles the change up into the account's `mrr_cents`. In either case, if a `coupon_id` was supplied, redeeming it increments the coupon's `redemption_count`, and the coupon flips to `EXHAUSTED` if that increment reaches `max_redemptions`.

A subscription's `coupon_id` may only reference a coupon that is redeemable at redemption time — its `status` is `ACTIVE` (not `EXHAUSTED`) and its `redemption_count` is still below `max_redemptions`. A coupon that is exhausted, or whose `redemption_count` already equals `max_redemptions`, is rejected with `ERR_COUPON_NOT_REDEEMABLE`. The same redeemability rule governs adding a coupon during a plan change.

### 3.3. Converting Trials and the Renewal Tick

A trialing subscription becomes a paying one in one of two ways. An `AccountOwner` may convert early, advancing `lifecycle_status` from `TRIALING` to `ACTIVE` while the subscription is still `TRIALING`; this sets `period_start` to the current clock and `period_end` to the current clock plus 30 days, generates and finalizes the first invoice, attempts the first payment, and recomputes the account's `mrr_cents`. Alternatively the system converts trials automatically during the renewal tick: when the logical clock reaches or passes a subscription's `trial_end`, the same `TRIALING → ACTIVE` transition fires, except `period_start` is set to `trial_end` and `period_end` to `trial_end` plus 30 days. A conversion requires the plan referenced by `plan_id` to still be `ACTIVE`; if a pending plan change had targeted an archived plan the conversion is rejected with `ERR_PLAN_ARCHIVED`. On any conversion the system regenerates the first cycle's invoice, finalizes it, and recomputes `mrr_contribution_cents` and the account's `mrr_cents`, since the subscription now counts as `ACTIVE`.

The renewal tick is an admin-only test-driving capability that drives recurring billing deterministically. On each tick the system performs two passes: it converts every `TRIALING` subscription whose `trial_end` is at or before the current clock, and it renews every `ACTIVE` subscription whose `period_end` is at or before the current clock. Renewing a subscription generates and finalizes the next cycle's invoice — including the usage-overage sweep of Section 3.6 — and advances the billing period by 30 days. The tick reports a count of conversions in `converted_count`, a count of renewals in `renewed_count`, and the list of affected invoice identifiers in `invoice_ids`.

### 3.4. Recording Metered Usage

Either an `AccountOwner` (on their own subscription) or a `BillingAdmin` records a **usage event** by supplying `units`, the number of metered units consumed, which must be greater than 0, and `recorded_at`, the ISO 8601 UTC event time. The event is accepted only if `recorded_at` falls at or after the subscription's current `period_start` and strictly before its `period_end`; an event whose time lies outside that half-open window is rejected with `ERR_USAGE_OUT_OF_PERIOD`. Each accepted event is appended as a usage record carrying its `subscription_id`, the supplied `units` and `recorded_at`, and a `billed` flag that starts false. The `billed` flag is the idempotency guard for metering: a usage record is set to billed only once it has been swept onto a finalized invoice, so the same consumption is never charged twice across successive billing runs.

### 3.5. Changing Plans with Day-Granular Proration

An `AccountOwner` upgrades or downgrades an active subscription by changing its plan. The request supplies the new `plan_id` and the `expected_subscription_version` described in Section 2.6. The target plan must differ from the subscription's current `plan_id` — a no-op change is rejected with `ERR_NO_PLAN_CHANGE` — and it must not be archived, or the change is rejected with `ERR_PLAN_ARCHIVED`. The subscription must be `ACTIVE` for proration to apply.

Proration is computed at day granularity over the fixed 30-day cycle. The system first determines how many full days have already been consumed on the old plan by taking the difference between the current clock and the subscription's `period_start` and discarding any partial day — the floor of that difference in days — to obtain the elapsed-days figure. The remaining days are 30 minus the elapsed days. The system then computes two amounts over these same inputs but in opposite directions. The **credit** is the unused remainder of the old plan: the old plan's `monthly_fee_cents` multiplied by the remaining days, divided by 30, rounded half-up to whole cents. The **charge** is the new plan's cost for that same remainder: the new plan's `monthly_fee_cents` multiplied by the remaining days, divided by 30, rounded half-up to whole cents. Rounding is applied independently to each of the two amounts before either is signed. These surface as two signed invoice lines on a new draft invoice: a `PRORATION_CREDIT` line whose `amount_cents` is the negative of the credit, and a `PRORATION_CHARGE` line whose `amount_cents` is the positive charge; the net proration is the charge minus the credit.

Completing the change increments the subscription's `version` by one, finalizes the proration invoice (Section 3.6), sets the subscription's `plan_id` to the new plan, recomputes `mrr_contribution_cents`, and bubbles the result up into the account's `mrr_cents`. If a coupon is added as part of the change it must be redeemable per Section 3.2, failing otherwise with `ERR_COUPON_NOT_REDEEMABLE`.

### 3.6. Finalizing Invoices: Lines, Overage, Discount, and Tax

An invoice is born in `DRAFT` and is finalized into `OPEN` at renewal, trial conversion, or plan-change settlement. Finalization is where every priced fact lands on the invoice. An invoice records its `account_id`, a `subscription_id` reference, a `coupon_id` snapshot (null when none applies), a `tax_jurisdiction_id` snapshot captured from the account at finalization, the service period it covers in `period_start` and `period_end`, and a `status`. Its money fields — `subtotal_cents`, `discount_cents`, `tax_cents`, `total_cents`, and `amount_paid_cents` — are all 0 until finalization fills them in. Each billable fact is an **invoice line** carrying its `invoice_id`, a `kind` from `SUBSCRIPTION`, `ADDON`, `OVERAGE`, `PRORATION_CREDIT`, or `PRORATION_CHARGE`, a human-readable `description`, and a signed `amount_cents` (proration-credit lines are negative).

**Usage overage** is priced by sweeping the closing cycle's unbilled usage. The system sums the `units` of every usage record whose `billed` flag is false and whose `recorded_at` falls at or after `period_start` and before `period_end`. From that total it subtracts the effective plan's `included_usage_units`; if the difference is negative there is no overage, so the overage-unit count is the larger of zero and that difference. The overage units are then priced by walking `overage_tiers` in order as marginal bands. Starting from a previous cap of zero and the full overage-unit count as the remaining quantity, each band charges its `rate_cents_per_unit` on the units that fall inside it: the band's width is its `up_to_units` minus the previous cap, except the final band (whose `up_to_units` is null) absorbs all that remains; the quantity taken in the band is the smaller of the remaining quantity and the band width; the band's contribution is that taken quantity multiplied by the band's `rate_cents_per_unit`. The remaining quantity is reduced by the amount taken, the previous cap advances to the band's `up_to_units`, and the walk stops once nothing remains. Because integer rates multiply integer unit counts, the resulting `OVERAGE` line amount is exact and needs no rounding. Swept usage records are marked billed so they are never charged again.

Finalization then computes the invoice totals in a **pinned evaluation order**, discount before tax, with a single rounding per step. First, `subtotal_cents` is the signed sum of every line's `amount_cents`, so proration-credit lines reduce it. Second, `discount_cents` is determined from the applied coupon: if there is no coupon, or if the coupon's `duration` is `ONCE` and this is not the subscription's first finalized invoice, the discount is 0; if the coupon's `discount_type` is `PERCENT`, the discount is the subtotal multiplied by the coupon's `percent_off`, divided by 100, rounded half-up to whole cents; if the coupon's `discount_type` is `FIXED`, the discount is the smaller of the coupon's `amount_off_cents` and the subtotal. Third, the taxable base is the subtotal minus the discount. Fourth, `tax_cents` is the taxable base multiplied by the jurisdiction's `tax_rate_bps`, divided by 10000, rounded half-up to whole cents — a single rounding applied to the discounted base, not a per-line rounding. Fifth, `total_cents` is the taxable base plus the tax. The first-invoice distinction matters only for `ONCE` coupons, which discount the first finalized invoice and never again; `RECURRING` coupons discount every cycle's invoice.

When a draft invoice is finalized it transitions `DRAFT → OPEN`, snapshots `tax_jurisdiction_id` from the account, and immediately attempts the first payment as attempt number 1 (Section 3.7).

### 3.7. Payments, Dunning, and Involuntary Churn

Whether a payment succeeds is governed deterministically by the account's `payment_method_ok` flag, which a `BillingAdmin` toggles through a test-driving capability that takes an `account_id` and a `payment_method_ok` value. When the flag is true, a payment attempt clears; when false, it fails. Each **payment** records its `invoice_id`, the `amount_cents` attempted (equal to the invoice's `total_cents` at attempt time), the 1-based `attempt_number` that produced it, and a `status` that begins `PENDING` and resolves once to `CLEARED` or `FAILED`.

When a payment clears, the open invoice transitions `OPEN → PAID`: its `amount_paid_cents` is set to `total_cents` and a revenue schedule entry is created for it (Section 3.8). When a payment fails, dunning begins. Dunning is advanced by an admin-only billing tick that, for each open or past-due invoice whose retry is due — meaning the current clock is at or after `next_retry_at`, or it is the first attempt — attempts a payment and advances the dunning state machine. The tick reports `retried_count`, `cleared_count`, and the list of `canceled_subscription_ids` for subscriptions that were involuntarily canceled.

The retry schedule is keyed off the `dunning_attempt` counter, which counts failed retries consumed on the current open invoice. The retry offsets in days are 0 for the initial attempt, 3 for the first retry, and 7 for the second retry; the maximum number of attempts is 3. On the first failure of an open invoice, the invoice transitions `OPEN → PAST_DUE`, the subscription's `billing_status` mirrors `CURRENT → PAST_DUE`, `dunning_attempt` increments by 1, and `next_retry_at` is set to the first failure time plus the offset indexed by the new `dunning_attempt`. When the next tick is due and a queued retry is about to run, the invoice reverts `PAST_DUE → OPEN` so the attempt can execute. If that retry fails again while `dunning_attempt` is still below the maximum of 3, the self-loop fires: `dunning_attempt` increments, a new failed payment is created, the invoice returns to `PAST_DUE`, and `next_retry_at` advances to the first failure time plus the offset indexed by the new `dunning_attempt`. The boundary is precise: while `dunning_attempt` is 2 the subscription remains `PAST_DUE`, and only when `dunning_attempt` reaches 3 and that final retry still fails does involuntary churn occur.

If a retry clears while the subscription is `PAST_DUE` and the tick is due, the invoice becomes `PAID` with `amount_paid_cents` set to `total_cents`, `billing_status` reverts `PAST_DUE → CURRENT`, `dunning_attempt` resets to 0, `next_retry_at` is cleared, and a revenue schedule entry is created. If instead `dunning_attempt` has reached the maximum of 3 and the retry fails, the subscription is involuntarily canceled: `billing_status` becomes `UNPAID` and, as the cross-effect on the lifecycle dimension, `lifecycle_status` moves `ACTIVE → CANCELED` with `mrr_contribution_cents` set to 0. The open invoice transitions `PAST_DUE → VOID`, and the account's `mrr_cents` is recomputed to drop this subscription — this is the involuntary-churn event.

### 3.8. Recognizing Revenue and Reporting MRR

Two figures describe revenue from opposite vantage points. **Committed MRR** is a forward-looking projection over the subscription/account domain; **recognized revenue** is a chronological, ratable measure over the invoice/revenue-schedule domain.

Committed MRR is recomputed on any subscription create, convert, or cancel, on any add-on add or remove, and on any plan change. A subscription contributes to MRR only while its `lifecycle_status` is `ACTIVE`; a `TRIALING` or `CANCELED` subscription contributes 0. For an active subscription, the base is the plan's `monthly_fee_cents` plus the sum of the `monthly_fee_cents` of every add-on whose `SubscriptionAddOn` status is `ACTIVE`. If the subscription carries a coupon whose `duration` is `RECURRING`, a recurring discount is subtracted: for a `PERCENT` coupon it is the base multiplied by `percent_off`, divided by 100, rounded half-up to whole cents; for a `FIXED` coupon it is the smaller of `amount_off_cents` and the base. A non-recurring coupon or no coupon yields a recurring discount of 0. The subscription's `mrr_contribution_cents` is the base minus that recurring discount, and the account's `mrr_cents` is the sum of `mrr_contribution_cents` across the account's subscriptions whose `lifecycle_status` is `ACTIVE`. This committed figure projects the next full cycle and deliberately ignores partial-period proration and one-time overage.

Recognized revenue is carried on a **revenue schedule entry**, created when an invoice becomes paid. Each entry records its `invoice_id`, a `subscription_id` reference, the recognition window in `service_period_start` and `service_period_end`, the `total_recognizable_cents`, and the computed `recognized_to_date_cents`. The `total_recognizable_cents` is the recurring portion of the paid invoice — only the `SUBSCRIPTION` and `ADDON` line kinds enter it; one-time `OVERAGE`, `PRORATION_CREDIT`, and `PRORATION_CHARGE` lines are excluded. Recognition is ratable over a 30-day window: the elapsed days are the floor of the difference between the current clock and `service_period_start` in days, clamped to the range 0 through 30. The `recognized_to_date_cents` is the `total_recognizable_cents` multiplied by those elapsed days, divided by 30, rounded half-up to whole cents, and then clamped to the range from 0 through `total_recognizable_cents`. The revenue schedule for an invoice is read on demand, and `recognized_to_date_cents` is computed against the current clock at read time.

A `BillingAdmin` reads portfolio health through an MRR report that may take an optional `since` clock anchor. The report returns `total_mrr_cents`, the committed MRR summed across all active accounts; `active_subscription_count`; `churned_subscription_count`, the number of subscriptions that have churned since the anchor; and `churned_mrr_cents`, the recurring revenue lost to that churn.

### 3.9. Add-ons, Pause Windows, and Closing an Account

An `AccountOwner` attaches an **add-on** to their subscription by supplying an `addon_id`. The attachment records its `subscription_id`, the `addon_id`, and a `status` that begins `ACTIVE`. The same add-on may not be attached twice while still active: attaching an `addon_id` that is already `ACTIVE` on the subscription is rejected with `ERR_ADDON_ALREADY_ACTIVE`. Attaching an add-on recomputes the subscription's `mrr_contribution_cents` and the account's `mrr_cents`. Removing an add-on sets its `status` to `REMOVED` (terminal); a removed add-on stops contributing to MRR, so removal likewise recomputes `mrr_contribution_cents` and `mrr_cents`.

An `AccountOwner` may schedule a **pause window** on a subscription by supplying an inclusive `pause_from` instant and an exclusive `pause_to` instant, where `pause_from` must be strictly earlier than `pause_to`. A pause window records its `subscription_id`, `pause_from`, `pause_to`, and a `status` that begins `SCHEDULED`. Pause windows must be spaced apart: a new window must be separated from every still-`SCHEDULED` window on the same subscription by a buffer of at least 7 days. Concretely, the request is rejected with `ERR_PAUSE_WINDOW_CONFLICT` if the new window expanded by 7 days on each side — the interval from 7 days before `pause_from` to 7 days after `pause_to` — intersects an existing scheduled window; this is a buffered-gap rule, not mere non-adjacency, so two windows touching at the edges still conflict. Canceling a scheduled pause window moves its `status` from `SCHEDULED` to `CANCELED` (terminal); once canceled the window no longer occupies the timeline, so a future window that would otherwise have conflicted with it may then be scheduled.

A subscription itself may be **canceled** by its `AccountOwner` as voluntary churn. Canceling an `ACTIVE` subscription moves `lifecycle_status` from `ACTIVE` to `CANCELED`, sets `mrr_contribution_cents` to 0, recomputes the account's `mrr_cents` so the subscription drops out — the voluntary-churn event — voids any invoice on the subscription still in `DRAFT` or `OPEN` whose `amount_paid_cents` is 0, and marks all of the subscription's add-on rows `REMOVED`. Canceling a `TRIALING` subscription likewise moves `lifecycle_status` to `CANCELED`, but because no invoice was ever generated and the subscription was already excluded from MRR, there is no churn delta to apply. Either way, a subscription not in the originating state for these transitions is rejected with `ERR_INVALID_STATE`.

Finally, an `AccountOwner` may **close** their account, moving `status` from `ACTIVE` to `CLOSED` and setting `mrr_cents` to 0. Closing is blocked while the account still has live commitments: if any subscription on the account is `TRIALING` or `ACTIVE`, the close is rejected with `ERR_ACCOUNT_HAS_ACTIVE_SUBS`; if any invoice on the account is `OPEN` or `PAST_DUE`, it is rejected with `ERR_ACCOUNT_HAS_OPEN_INVOICES`. A `BillingAdmin` also controls the simulated clock through a test-driving capability that sets the server's current UTC time to a supplied `to_iso8601` instant and returns the new `now`; advancing the clock does not by itself run any billing — renewals and dunning fire only when their respective ticks are invoked.

## 4. Endpoint Definitions

Operations that create a new standalone resource or add a distinct resource to a collection return `201 Created`. Operations that read a resource, drive a state transition, or otherwise modify an existing resource return `200 OK`. All endpoints honor the authentication, authorization, and validation ordering of Section 2; request and response payloads are reconstructed from the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a subscription plan/tier | BillingAdmin |
| GET | `/plans` | List plans (optional status filter) | BillingAdmin, AccountOwner |
| GET | `/plans/{id}` | Get a plan | BillingAdmin, AccountOwner |
| POST | `/plans/{id}/archive` | Archive a plan | BillingAdmin |
| POST | `/plans/{id}/price-schedules` | Add a scheduled price window to a plan | BillingAdmin |
| GET | `/plans/{id}/price-schedules` | List a plan's price schedules | BillingAdmin, AccountOwner |
| POST | `/add-ons` | Create an add-on | BillingAdmin |
| GET | `/add-ons` | List add-ons | BillingAdmin, AccountOwner |
| POST | `/coupons` | Create a coupon | BillingAdmin |
| GET | `/coupons` | List coupons (optional status filter) | BillingAdmin |
| GET | `/coupons/{id}` | Get a coupon | BillingAdmin |
| POST | `/tax-jurisdictions` | Create a tax jurisdiction | BillingAdmin |
| GET | `/tax-jurisdictions` | List tax jurisdictions | BillingAdmin |
| POST | `/accounts` | Register an account | Anonymous |
| GET | `/accounts/{id}` | Get an account | BillingAdmin, AccountOwner |
| POST | `/accounts/{id}/close` | Close an account | AccountOwner |
| POST | `/accounts/{id}/subscriptions` | Create a subscription | AccountOwner |
| GET | `/accounts/{id}/subscriptions` | List subscriptions for an account | BillingAdmin, AccountOwner |
| GET | `/subscriptions/{id}` | Get a subscription | BillingAdmin, AccountOwner |
| POST | `/accounts/{id}/subscriptions/{sid}/convert` | Convert a trialing subscription to active early | AccountOwner |
| POST | `/accounts/{id}/subscriptions/{sid}/change-plan` | Change plan with day-granular proration | AccountOwner |
| POST | `/accounts/{id}/subscriptions/{sid}/cancel` | Cancel a subscription | AccountOwner |
| POST | `/accounts/{id}/subscriptions/{sid}/addons` | Attach an add-on to a subscription | AccountOwner |
| GET | `/subscriptions/{id}/addons` | List a subscription's add-ons | BillingAdmin, AccountOwner |
| DELETE | `/accounts/{id}/subscriptions/{sid}/addons/{aid}` | Remove an add-on | AccountOwner |
| POST | `/accounts/{id}/subscriptions/{sid}/pause-windows` | Schedule a billing pause window | AccountOwner |
| GET | `/subscriptions/{id}/pause-windows` | List a subscription's pause windows | BillingAdmin, AccountOwner |
| DELETE | `/accounts/{id}/subscriptions/{sid}/pause-windows/{pwid}` | Cancel a scheduled pause window | AccountOwner |
| POST | `/accounts/{id}/subscriptions/{sid}/usage` | Record a metered usage event | AccountOwner, BillingAdmin |
| GET | `/subscriptions/{id}/usage` | List usage records for a subscription | BillingAdmin, AccountOwner |
| GET | `/accounts/{id}/invoices` | List an account's invoices (optional subscription filter) | BillingAdmin, AccountOwner |
| GET | `/invoices/{id}` | Get an invoice | BillingAdmin, AccountOwner |
| GET | `/invoices/{id}/lines` | List invoice lines | BillingAdmin, AccountOwner |
| GET | `/invoices/{id}/payments` | List payment attempts on an invoice | BillingAdmin, AccountOwner |
| GET | `/invoices/{id}/revenue-schedule` | Get the revenue schedule entry for a paid invoice | BillingAdmin, AccountOwner |
| GET | `/reporting/mrr` | Total committed MRR and churn since a clock anchor | BillingAdmin |
| POST | `/_clock/set` | Set the server's current UTC clock (test-driving) | BillingAdmin |
| POST | `/_payments/set-card-state` | Set an account's stored-card authorization state | BillingAdmin |
| POST | `/_billing/run-renewals` | Run the renewal/conversion billing tick | BillingAdmin |
| POST | `/_billing/run-dunning` | Run the dunning/retry billing tick | BillingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_ARCHIVED` | 409 |
| `ERR_COUPON_NOT_REDEEMABLE` | 409 |
| `ERR_NO_PLAN_CHANGE` | 409 |
| `ERR_USAGE_OUT_OF_PERIOD` | 409 |
| `ERR_ADDON_ALREADY_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ACCOUNT_HAS_ACTIVE_SUBS` | 409 |
| `ERR_ACCOUNT_HAS_OPEN_INVOICES` | 409 |
| `ERR_PRICE_SCHEDULE_OVERLAP` | 409 |
| `ERR_PAUSE_WINDOW_CONFLICT` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
