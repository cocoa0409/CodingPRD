# Employee Stock Purchase Plan (ESPP) API — Product Requirements Document

## 1. Introduction

An Employee Stock Purchase Plan, organized to qualify under Section 423 of the Internal Revenue Code, is one of the most heavily regulated equity-compensation vehicles a public company can offer. Behind the simple participant-facing pitch ("contribute a slice of every paycheck, buy company stock at a discount") sit a dense tangle of obligations: offering periods bounded in length, contribution rates ceilinged by both percentage and an absolute annual accrual cap, a lookback that retroactively determines the purchase price, payroll postings that must be cleanly separable from the operator who triggers the purchase batch, and a tax-reporting trail (Form 3922) that has to be issued and preserved immutably for the IRS.

This API formalizes the full lifecycle of an ESPP — from plan configuration in `DRAFT`, through the rolling sequence of offering periods, the per-pay-period contributions, the period-close purchase batch, the long holding-period maturation, and the eventual taxable disposition reported by the participant. The system is the single source of truth for every dollar of accrual and every share issued, and its calculations directly drive what appears on participants' W-2s and 1099-Bs. Because the same operator must never both fund and exercise a purchase, the system enforces segregation of duties between the payroll function and the plan-administration function as a hard rule, not a policy preference. Because time-gated events (period close, one-year and two-year holding thresholds) must fire deterministically in a server that does not get to assume wall-clock semantics, an explicit logical clock and an explicit sweep operation drive every time-sensitive transition.

The audience for this document is the engineer implementing the API. The audience the API itself serves is fourfold: a plan administrator who configures plans and runs purchase batches; a payroll agent who posts per-pay-period contributions; a participant who enrolls, can change their rate or withdraw, and reports dispositions of shares they have received; and a read-only tax-authority auditor who inspects Form 3922 and disposition records across all participants.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the top-level `/plans` prefix where their natural URL hierarchy starts at a plan; other top-level resources (offering periods, enrollments, contributions, purchases, dispositions, Form 3922 records, the system clock, and the sweep) are exposed at their own paths as enumerated in §4.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity in which that principal is acting. A request missing or carrying an empty value for either header is rejected with `ERR_AUTH_REQUIRED`. A request carrying an `X-User-Role` value outside the recognized set is rejected with `ERR_AUTH_INVALID_ROLE`. Once headers parse, the system checks whether the named role is permitted to invoke the requested operation per the role matrix below; a role mismatch is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled as follows:

- `PlanAdministrator` — configures plans, records grant-date and purchase-date FMVs, runs the purchase batch, generates the dilution preview, advances the logical clock, and triggers the maturation sweep. When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it for the segregation-of-duties check (see §2.4) but does not compare it to any entity's `id`.
- `PayrollAgent` — posts contributions against enrollments. When `X-User-Role` is `PayrollAgent`, `X-User-ID` is likewise an opaque operator identifier; the server records it as the poster of each `Contribution` row so that the segregation-of-duties check at purchase-batch time can detect overlap with the calling `PlanAdministrator`.
- `Participant` — the employee who enrolls, may change their elected rate or withdraw, and reports dispositions on purchases they own. When `X-User-Role` is `Participant`, `X-User-ID` is the participant's own identifier; the `Participant` entity is materialized implicitly, meaning any value supplied via `X-User-ID` for this role is treated as an existing participant id. Ownership checks on any resource that references a participant — specifically the `participant_id` field on `Enrollment`, `Purchase`, `Form3922`, and `Disposition` — compare that foreign-key value to `X-User-ID` and reject mismatches with `ERR_NOT_OWNER`.
- `TaxAuthority` — read-only auditor. When `X-User-Role` is `TaxAuthority`, `X-User-ID` is an opaque auditor identifier not tied to any persisted entity; the role grants visibility across all participants' Form 3922 and Disposition records but no write capability anywhere in the API.

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

List endpoints accept two query parameters that govern pagination. The `limit` parameter sets the maximum number of items to return; when omitted, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip from the start of the result set; when omitted, it defaults to 0. Values outside these bounds are rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every paginated response includes the following fields in the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Validation Ordering and Segregation of Duties

The system evaluates request-level checks in a strict priority order so that the error returned is always the highest-priority unmet condition, not whichever check happened to run last. Authentication (presence of `X-User-ID` and `X-User-Role`) is checked first, then role validity, then per-operation role authorization, then path-identifier existence (see §2.5), then state preconditions on the plan, the offering period, and any other state-bearing entities in the request, and only after all of those have passed does the system reach business-safety, business-constraint, business-fiscal, and business-temporal checks. The optimistic-concurrency check (see §2.10) is evaluated within the state category at priority 17 — after the standard state checks have confirmed the row is in the right state for mutation but before pagination bounds are validated on list endpoints.

A distinguished business-safety rule, evaluated before any business-constraint check, enforces segregation of duties on the purchase batch: the `X-User-ID` invoking the run-purchase operation on an offering period MUST NOT appear as the poster of any `Contribution` whose `enrollment_id` points at an `Enrollment` belonging to that period. The rule applies regardless of whether the same human happens to hold both the `PayrollAgent` and `PlanAdministrator` roles across different requests — the system records the poster of every contribution and compares that recorded id to the caller's `X-User-ID` at batch time. A violation is rejected with `ERR_SOD_VIOLATION`. This is the structural backbone of the API's compliance-audit posture: a single individual cannot both fund and exercise a purchase.

### 2.5. Hierarchical Resource Lookup

Several endpoint paths nest identifiers — for example, the grant-FMV endpoint takes both `plan_id` and `offering_period_id`. The API validates these identifiers strictly left-to-right: the system first resolves `plan_id`, then `offering_period_id`, and so on for any further nested segments. The request is rejected immediately with `ERR_NOT_FOUND` against the first identifier in the path that fails to resolve to an existing row. A nested resource that does exist but does not belong to the parent named earlier in the path is treated as a non-existent child under that parent and likewise yields `ERR_NOT_FOUND` against the child identifier.

This ordering applies to every path identifier the API exposes — `plan_id`, `offering_period_id`, `enrollment_id`, `purchase_id`, `disposition_id`, `participant_id`, and `form_id` — and applies uniformly to GET, POST, PATCH, and DELETE operations.

### 2.6. Common Resource Properties

Most primary resources in this API — `Plan`, `OfferingPeriod`, `Enrollment`, `Purchase`, and `Disposition` — carry a uniform set of system-managed fields:

- `id` is a server-minted UUID string (no type prefix); it is assigned at creation and never changes.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` is an integer that starts at the resource's initial creation value and is incremented by one on every mutation. It supports optimistic concurrency as described in §2.10.

Two entities are excluded from this set. A `Contribution` carries only `id` and `created_at` — both `updated_at` and `version` are absent on contribution rows, reflecting that a contribution's lifecycle status is transitioned by external events (refund on withdrawal, consumption by purchase batch) rather than by client mutation through a dedicated endpoint. A `Form3922` likewise carries only `id` and `created_at` — `updated_at` and `version` are absent because Form 3922 is immutable by design; any `PATCH`, `PUT`, or `DELETE` against a Form 3922 record is rejected with `ERR_FORM_3922_IMMUTABLE`. The `SystemClock` is a singleton with no `id`, `updated_at`, or `version`; it is read or advanced via dedicated endpoints rather than treated as a versioned mutable row.

### 2.7. Money, Shares, and Precision

Every monetary quantity in the API is denominated in integer cents, never in dollars-and-cents floats. Per-pay-period contribution amounts, fair-market-value quotes, per-share purchase prices, sale proceeds per share, accrual charges, and tax-split components are all integers in the unit "cents". Share counts are integers in the unit "whole shares". Two rounding rules govern the few places where rounding is required:

- When the contribution computation multiplies `gross_pay_cents` by `contribution_rate_bp` and divides by ten thousand, the resulting cents value is rounded half-up to the nearest whole cent.
- When the per-share purchase price is computed from the chosen fair-market value and the plan's discount, the per-share cents value is rounded half-up to the nearest whole cent. This rounding happens once, at the per-share level — share-count floors and refund subtractions downstream operate on the rounded per-share price as-is.

Conversion of basis-point rates to fractions uses a denominator of ten thousand throughout: a `contribution_rate_bp` of 1500 means 15.00%, a `discount_bp` of 1500 means a 15.00% discount, and a `max_contribution_rate_bp` ceiling of 1500 means the elected rate may not exceed 15.00%.

### 2.8. Form 3922 Immutability and Tax-Record Hygiene

A Form 3922 record is produced by the system as part of the purchase batch and is, from that moment on, frozen. The record captures, for the participant who received shares: the grant date (`grant_date`), the purchase date (`purchase_date`), the fair-market value on the grant date in cents (`fmv_grant_date_cents`), the fair-market value on the purchase date in cents (`fmv_purchase_date_cents`), the per-share exercise price in cents (`exercise_price_per_share_cents`), the number of shares transferred (`shares_transferred`), the legal-title date (`legal_title_date`, which for these plans equals the purchase date), and a server-assigned `issuance_timestamp`. It also carries the `purchase_id` it documents and a mirrored `participant_id`. Any subsequent attempt to alter or delete the record — via `PATCH`, `PUT`, or `DELETE` against the Form 3922 endpoint — is rejected with `ERR_FORM_3922_IMMUTABLE`. The IRS-reporting trail is therefore append-only by construction.

### 2.9. The System Clock and the Sweep

Because time-gated transitions in this domain (period close, holding-period maturation) cannot rely on wall-clock semantics inside a deterministic test harness, the API exposes a dedicated, server-authoritative `SystemClock` singleton with two fields: `current_time`, the logical UTC wall-clock used by every state machine in the system, and `last_sweep_at`, the timestamp of the most recent maturation sweep. The clock is read through a dedicated capability and is advanced by a `PlanAdministrator`-only capability that accepts a `to_timestamp` field; the supplied timestamp must be strictly greater than the current value, otherwise the request is rejected with `ERR_CLOCK_NOT_ADVANCING`.

A separate sweep capability, also `PlanAdministrator`-only, materializes any time-gated transition whose preconditions have come true since the last invocation. Two classes of transition are driven by the sweep: any `OfferingPeriod` whose `end_date` has been reached and whose `purchase_date_fmv_cents` has been recorded advances from `OPEN` to `CLOSED`; and any `Purchase` in `HELD` disposition status advances its `holding_period_status` across the `WITHIN_BOTH` → `PAST_ONE_YEAR_FROM_PURCHASE` → `QUALIFYING_MATURE` thresholds as the relevant durations elapse. Each invocation refreshes `last_sweep_at`. Side effects within a single sweep are described in their respective lifecycle subsections of §3; the sweep itself does not generate purchases — the purchase batch is a separate, explicit operation that a `PlanAdministrator` invokes per offering period after the period has reached `CLOSED`.

### 2.10. Optimistic Concurrency Control

Endpoints that mutate an existing resource by its identifier accept an optional `version` field in the request body. Specifically, the patch operations on a plan, on an enrollment, on an offering period's purchase-date FMV, and on a disposition all accept `version`. When the client supplies it, the server compares the supplied value to the row's current `version`; if they differ, the request is rejected with `ERR_VERSION_CONFLICT` and the row is not modified. When the client omits `version`, the server processes the mutation without an OCC check and increments `version` as part of the successful write. Every successful mutation refreshes `updated_at` and increments `version` by one. Cross-entity side effects of state transitions (for example, the `Plan` activation creating its first offering period, or the purchase batch updating multiple `Contribution` and `Enrollment` rows) each independently refresh `updated_at` and bump `version` on every row they touch.

### 2.11. State Vocabulary

The state enumerations used throughout the system, in the exact spelling clients and stored rows must use, are:

- `Plan.status`: `DRAFT`, `ACTIVE`, `TERMINATED`.
- `OfferingPeriod.status`: `OPEN`, `CLOSED`, `PURCHASED`. `CLOSED` is the brief window between the period reaching its end date (with FMV recorded) and the purchase batch running. `PURCHASED` is terminal.
- `Enrollment.status`: `ACTIVE`, `WITHDRAWN`, `COMPLETED`. `WITHDRAWN` triggers refund of all posted contributions on the enrollment and excludes the enrollment from that period's purchase batch. `COMPLETED` is set as a side effect of the purchase batch.
- `Contribution.status`: `POSTED`, `REFUNDED`, `CONSUMED`. `POSTED` is the initial state at creation; `REFUNDED` is the state set on every still-`POSTED` contribution when the owning enrollment is withdrawn; `CONSUMED` is set when the purchase batch sweeps a contribution into a purchase.
- `Purchase.holding_period_status`: `WITHIN_BOTH`, `PAST_ONE_YEAR_FROM_PURCHASE`, `QUALIFYING_MATURE`. `WITHIN_BOTH` means the current logical time is within one year of `purchase_date` and within two years of `grant_date`; `PAST_ONE_YEAR_FROM_PURCHASE` means at least one year has elapsed from `purchase_date` but less than two years have elapsed from `grant_date`; `QUALIFYING_MATURE` means at least two years have elapsed from `grant_date` and at least one year has elapsed from `purchase_date`.
- `Purchase.disposition_status`: `HELD`, `DISPOSED_QUALIFYING`, `DISPOSED_DISQUALIFYING`. `HELD` until a `Disposition` row that consumes the remaining undisposed shares is created.
- `Disposition.status`: `REPORTED`, `AMENDED`, `VOIDED`.
- `Disposition.classification`: `QUALIFYING`, `DISQUALIFYING`.

## 3. Business Logic & Workflows

### 3.1. Plan Configuration and Activation

A `PlanAdministrator` creates a new ESPP by submitting a payload with the human-readable `name` (between 1 and 120 characters, unique across the system; duplicate names are rejected with `ERR_DUPLICATE_PLAN_NAME`), the length of each offering period in months as `offering_period_months`, and the UTC `effective_date` at which the plan is to become operational. Four further fields are accepted as optional configuration: `max_contribution_rate_bp`, which caps the participant-elected payroll deduction rate in basis points and defaults to 1500 (15.00%); `annual_accrual_cap_cents`, which caps each participant's Section 423 annual accrual and defaults to 2,500,000 cents (the statutory $25,000 ceiling); `lookback_enabled`, a boolean that determines whether the purchase price will be anchored to the lower of the grant-date and purchase-date fair-market values, defaulting to true; and `discount_bp`, the discount applied to the chosen fair-market value in basis points, defaulting to 1500 (a 15.00% discount). A newly created plan starts in `DRAFT`.

A plan in `DRAFT` may be edited freely through a patch operation that accepts any subset of `name`, `offering_period_months`, `max_contribution_rate_bp`, `annual_accrual_cap_cents`, `lookback_enabled`, `discount_bp`, and `effective_date`, together with an optional `version` for optimistic concurrency. Three constraints are checked on every plan write (whether at creation or on edit): `offering_period_months` must be an integer in the closed interval from 6 through 24, rejected otherwise with `ERR_PERIOD_LENGTH_OUT_OF_RANGE`; `max_contribution_rate_bp` must be a positive integer no greater than 1500 (i.e. strictly greater than 0 and less than or equal to 1500); and `discount_bp` must be an integer in the closed interval from 0 through 1500.

Activation transitions the plan from `DRAFT` to `ACTIVE`. The operation is allowed only if the period-length, max-rate, and discount constraints above are all satisfied, and only if `effective_date` is greater than or equal to the current `SystemClock.current_time` at the moment of activation. As a side effect, the system creates the first offering period under the plan: `sequence_number` is set to 1, `start_date` is set to the plan's `effective_date`, `end_date` is computed as `start_date` plus `offering_period_months` months, and `status` is set to `OPEN`. Activating a `Plan` is the only mechanism by which the first offering period comes into existence — there is no direct create-offering-period endpoint.

Termination transitions the plan from `ACTIVE` to `TERMINATED`. The operation is rejected if any offering period of the plan still has `status` equal to `OPEN`; once allowed, the side effect is that no further offering periods will ever be created under the plan. Any operation against the plan's children (creating enrollments, posting contributions, running the purchase batch) requires the plan to be `ACTIVE`; if the plan is in `DRAFT` or `TERMINATED`, the operation is rejected with `ERR_PLAN_NOT_ACTIVE`.

### 3.2. The Offering Period: Window, Posture, and FMV Capture

An offering period — the unit of time over which a participant accumulates contributions toward a single purchase — is identified by its `plan_id`, its 1-based `sequence_number` within the plan, its `start_date`, and its `end_date`. The grant-date fair-market value of one share, stored in cents as `grant_date_fmv_cents`, is recorded by a dedicated capability that the `PlanAdministrator` invokes on the day the period opens: the operation accepts a `grant_date_fmv_cents` value and is allowed only when the system clock's `current_time` falls on the period's `start_date` and `grant_date_fmv_cents` is still null. Attempts outside that window, or attempts to overwrite an already-set value, are rejected with `ERR_GRANT_FMV_WINDOW`. The recorded value must be a positive integer.

The purchase-date fair-market value, `purchase_date_fmv_cents`, is recorded by a separate patch capability that the `PlanAdministrator` invokes after the period has reached its end date. The supplied value must be a positive integer. The system requires that `SystemClock.current_time` be at or beyond `OfferingPeriod.end_date` at the moment of the patch; an earlier attempt is rejected with `ERR_FMV_BEFORE_PERIOD_END`. This patch operation accepts an optional `version` for optimistic concurrency: two parallel patches with different values serialize so that the first writer wins and the second is rejected with `ERR_VERSION_CONFLICT`.

The period's posture — `OPEN`, `CLOSED`, or `PURCHASED` — gates every operation on its descendants. While `OPEN`, the period accepts new enrollments and new contributions against its enrollments. The transition from `OPEN` to `CLOSED` is driven by the maturation sweep: when the system clock reaches or passes `end_date` and `purchase_date_fmv_cents` has been recorded (not null), the next sweep invocation flips the period to `CLOSED`. From `CLOSED`, any subsequent attempt to create an enrollment referencing the period, or to post a contribution whose enrollment belongs to the period, is rejected with `ERR_PERIOD_NOT_OPEN`. The period remains in `CLOSED` until the purchase batch runs; the batch then drives the period to its terminal `PURCHASED`. The batch is described in §3.5.

### 3.3. Participant Enrollment and Rate Changes

A `Participant` enrolls in an `OPEN` offering period by submitting a payload with their elected `contribution_rate_bp`, a positive integer no greater than the plan's `max_contribution_rate_bp` ceiling. A rate of zero or a rate above the plan ceiling is rejected with `ERR_CONTRIBUTION_RATE_OUT_OF_RANGE`. The system records the enrollment with `offering_period_id` set to the period in the URL, `participant_id` set to the caller's `X-User-ID`, the elected `contribution_rate_bp`, an initial `status` of `ACTIVE`, and an initial `ytd_accrual_cents` of 0. The combination of `offering_period_id` and `participant_id` is unique: a participant cannot hold two enrollments in the same period. Two simultaneous enrollments by the same participant in the same period serialize on this uniqueness invariant — exactly one wins and the loser receives `ERR_DUPLICATE_ENROLLMENT`.

A participant may change their elected rate while the parent offering period is still `OPEN` and the enrollment is still `ACTIVE`. The patch accepts a new `contribution_rate_bp` (subject to the same positive-and-within-ceiling check) and an optional `version` for optimistic concurrency. A patch against an enrollment whose status has already moved to `WITHDRAWN` or `COMPLETED` is rejected with `ERR_INVALID_ENROLLMENT_STATE`.

Withdrawal moves an enrollment from `ACTIVE` to `WITHDRAWN`. The operation is allowed only to the owning `Participant` (`X-User-ID` must equal the enrollment's `participant_id`, otherwise `ERR_NOT_OWNER`) and only while the parent period is still `OPEN`. As a side effect, every `Contribution` on the enrollment whose status is currently `POSTED` is flipped to `REFUNDED`, and the participant is excluded from this period's purchase batch when it eventually runs. Withdrawal is the participant's one-way escape hatch from the period: the system does not re-activate withdrawn enrollments.

A race condition exists between withdrawal and the purchase batch on the same enrollment. Exactly one of the two operations wins. If the purchase batch commits first, the enrollment is `COMPLETED` and the subsequent withdrawal attempt is rejected with `ERR_INVALID_ENROLLMENT_STATE`. If withdrawal commits first, the purchase batch skips this enrollment when it runs.

### 3.4. Payroll Contributions

Contribution posting is the `PayrollAgent`'s exclusive responsibility. For each pay period, the agent submits a payload to the enrollment-scoped contribution endpoint containing `pay_period_end`, the UTC end date of the payroll period, and `gross_pay_cents`, the eligible gross compensation in cents (a non-negative integer). The system computes the contribution amount in two steps, then writes the row with `status` set to `POSTED`.

The first step is the raw rate-driven amount: gross pay in cents is multiplied by the enrollment's `contribution_rate_bp` and divided by ten thousand, with the result rounded half-up to the nearest whole cent. This produces a candidate `amount_cents`.

The second step caps that candidate against the participant's remaining Section 423 annual accrual headroom. The remaining accrual is `Plan.annual_accrual_cap_cents` minus the enrollment's running `ytd_accrual_cents`. Because the statutory cap is measured against grant-FMV-priced accrual rather than against cash withholding, the remaining accrual is translated into a remaining cash-withholding cap as the remaining accrual times the quantity one minus the discount (i.e. `(10000 - discount_bp) / 10000`), with the floor taken to the nearest whole cent. The final `amount_cents` is the smaller of the raw rate-driven amount and the larger of zero and the remaining cash cap.

Two variants of this rule are worth naming explicitly. In the under-cap variant, the raw rate-driven amount is less than or equal to the remaining cash cap, so the full deduction posts. In the capped variant, the raw rate-driven amount exceeds the remaining cash cap, so `amount_cents` is reduced to the remaining cash cap; the excess withholding is not carried forward — it is returned to the participant via payroll outside this API. If even this capped amount would push the projected `ytd_accrual_cents` past `Plan.annual_accrual_cap_cents`, the contribution post is rejected with `ERR_ANNUAL_ACCRUAL_CAP_EXCEEDED`.

A contribution may be posted only when the owning enrollment is in `ACTIVE` status and the parent offering period is `OPEN`; otherwise the post is rejected with `ERR_PERIOD_NOT_OPEN` (if the period is not `OPEN`) or `ERR_INVALID_ENROLLMENT_STATE` (if the enrollment is not `ACTIVE`). The state precondition on the parent plan is also enforced: a post against a contribution under a plan that is not `ACTIVE` is rejected with `ERR_PLAN_NOT_ACTIVE`. Contributions can be listed on an enrollment with a `status` filter that narrows the list to a particular lifecycle stage. The system maintains a clean audit trail of contributions through their three terminal-ish states: `POSTED` while still in the pipeline, `REFUNDED` if the owning enrollment is withdrawn before the batch, and `CONSUMED` once the batch has folded them into a purchase.

### 3.5. The Purchase Batch: Period Close to Purchased

Once the offering period has reached `CLOSED`, a `PlanAdministrator` invokes the per-period purchase-batch capability. Two preconditions are checked: the period's `status` must be exactly `CLOSED` (an `OPEN` or `PURCHASED` period is rejected with `ERR_INVALID_PERIOD_STATE`), and the calling `X-User-ID` must satisfy the segregation-of-duties rule from §2.4 — i.e. must not have posted any contribution against any enrollment in this period — rejected otherwise with `ERR_SOD_VIOLATION`. Two concurrent invocations on the same `CLOSED` period serialize so that exactly one batch executes; the loser observes the period now in `PURCHASED` and is rejected with `ERR_INVALID_PERIOD_STATE`.

The batch processes each `Enrollment` in the period whose status is still `ACTIVE`. (Enrollments already `WITHDRAWN` are skipped, consistent with §3.3.) Per enrollment, the system computes the purchase as a six-step calculation.

Step A is lookback selection: when the plan has `lookback_enabled` equal to true, the chosen per-share fair-market value `chosen_fmv_cents` is the smaller of the period's `grant_date_fmv_cents` and `purchase_date_fmv_cents`; when the plan has `lookback_enabled` equal to false, the chosen value is simply `purchase_date_fmv_cents`. Three sub-variants of this behavior are worth naming: with lookback enabled and the grant FMV at or below the purchase FMV, the price anchors to the cheaper grant FMV; with lookback enabled and the purchase FMV strictly below the grant FMV, the price drops with the stock; and with lookback disabled, the chosen value is always the purchase-date FMV, which can produce a legally different price than the lookback case for the same inputs.

Step B applies the discount and rounds once at the per-share price: `purchase_price_cents` is `chosen_fmv_cents` times the quantity one minus the discount in basis points (i.e. `(10000 - discount_bp) / 10000`), rounded half-up to the nearest whole cent. This is the only rounding step in the entire calculation.

Step C aggregates the consumable contributions: `contributions_used_cents` for the enrollment is the sum of `amount_cents` over every `Contribution` row whose `enrollment_id` matches the enrollment and whose status is currently `POSTED`. Contributions in `REFUNDED` status do not participate, by construction.

Step D floors to whole shares: `shares_purchased` is the integer floor of `contributions_used_cents` divided by `purchase_price_cents`. The leftover, `refund_cents`, equals `contributions_used_cents` minus the product of `shares_purchased` and `purchase_price_cents`.

Step E charges the IRS Section 423 accrual at grant-FMV basis: the proposed accrual charge is `shares_purchased` multiplied by `OfferingPeriod.grant_date_fmv_cents` (deliberately the grant-date FMV, not the purchase price, because the statute measures the cap that way).

Step F reduces share counts that would breach the annual cap: the remaining accrual headroom is `Plan.annual_accrual_cap_cents` minus the enrollment's `ytd_accrual_cents`. If the proposed accrual charge would exceed that headroom, `shares_purchased` is recomputed as the integer floor of the remaining headroom divided by `grant_date_fmv_cents`; `refund_cents` is recomputed against this reduced share count; and the accrual charge is recomputed as the reduced share count times `grant_date_fmv_cents`. The enrollment's `ytd_accrual_cents` is then incremented by the final accrual charge.

The system materializes a `Purchase` row per enrollment with `plan_id`, `offering_period_id`, `enrollment_id`, `participant_id`, `purchase_date` (equal to the period's `end_date`), `contributions_used_cents`, `chosen_fmv_cents`, `purchase_price_cents`, `shares_purchased`, `refund_cents`, an initial `holding_period_status` of `WITHIN_BOTH`, and an initial `disposition_status` of `HELD`. Each consumed `Contribution` is flipped from `POSTED` to `CONSUMED`. Each processed `Enrollment` is flipped from `ACTIVE` to `COMPLETED`. A Form 3922 record is issued immutably per `Purchase`, with its fields mirroring the purchase as described in §2.8: `purchase_id` and `participant_id` from the purchase row; `grant_date` from the period's `start_date`; `purchase_date` from the period's `end_date`; `fmv_grant_date_cents` and `fmv_purchase_date_cents` snapshotted from the period's two FMV fields at issuance; `exercise_price_per_share_cents` snapshotted from `purchase_price_cents` at issuance; `shares_transferred` from `shares_purchased`; `legal_title_date` equal to `purchase_date`; and a server-assigned `issuance_timestamp`.

The batch also performs the period-rollover side effect: the current period's `status` is set to `PURCHASED` (terminal), and a new `OfferingPeriod` is created with `sequence_number` equal to the predecessor's plus one, `start_date` equal to the predecessor's `end_date`, `end_date` computed as the new `start_date` plus `Plan.offering_period_months` months, and `status` equal to `OPEN`. This is how the rolling cadence of offering periods is sustained over the life of a plan — there is no separate next-period-create operation.

Every row touched by the batch has its `updated_at` refreshed and its `version` incremented (with the exception of `Contribution` and `Form3922`, which carry neither field). If during the batch a particular enrollment's projected accrual after Step F would still exceed the annual cap (a defensive edge case that can occur if external accrual state has drifted), the batch rejects that enrollment with `ERR_ANNUAL_ACCRUAL_CAP_EXCEEDED`.

### 3.6. Holding-Period Maturation

Each `Purchase` row carries a parallel holding-period dimension, `holding_period_status`, that advances independently of any disposition activity and is driven exclusively by the maturation sweep. The dimension's initial value at purchase creation is `WITHIN_BOTH`. The sweep advances a purchase from `WITHIN_BOTH` to `PAST_ONE_YEAR_FROM_PURCHASE` when `SystemClock.current_time` has reached or passed `purchase_date` plus one year and is still strictly less than `grant_date` plus two years; the precondition for this side effect is that the purchase's `disposition_status` is still `HELD`. The sweep advances directly from `WITHIN_BOTH` to `QUALIFYING_MATURE` when `SystemClock.current_time` has reached or passed `grant_date` plus two years and has also reached or passed `purchase_date` plus one year; same precondition. From `PAST_ONE_YEAR_FROM_PURCHASE`, the sweep advances to `QUALIFYING_MATURE` once `SystemClock.current_time` has reached or passed `grant_date` plus two years; again, the purchase must still be `HELD`. The implication for participant tax outcomes is captured at §3.7 — once a purchase is `QUALIFYING_MATURE`, any subsequent disposition is qualifying; while a purchase sits in either `WITHIN_BOTH` or `PAST_ONE_YEAR_FROM_PURCHASE`, any subsequent disposition is disqualifying.

A `Purchase` is retrievable individually and also through a per-participant list that supports two filters: `holding_period_status` narrows by holding-period status, and `disposition_status` narrows by disposition status.

### 3.7. Dispositions: Reporting, Classification, and the Tax Split

When a participant sells (or otherwise disposes of) shares they have received from a purchase, they report it through the disposition-creation capability. The payload carries `purchase_id` (the purchase being disposed against, which must belong to the acting participant — otherwise `ERR_NOT_OWNER`), `disposition_date` (a UTC date), `shares_disposed` (a positive integer), and `sale_price_per_share_cents` (a positive integer). Two date-window checks are enforced: `disposition_date` must be at or after the purchase's `purchase_date` and at or before the system clock's `current_time`, otherwise `ERR_DISPOSITION_DATE_OUT_OF_RANGE`. A share-balance check is enforced: `shares_disposed` may not exceed the purchase's `shares_purchased` minus the sum of `shares_disposed` over prior dispositions on the same purchase whose `status` is in either `REPORTED` or `AMENDED` (i.e. excluding voided dispositions), otherwise `ERR_SHARES_EXCEED_BALANCE`. Two parallel disposition creations against the same purchase, each claiming all remaining shares, serialize on this share-balance invariant — exactly one wins; the loser is rejected with `ERR_SHARES_EXCEED_BALANCE`.

Classification is determined at creation from the snapshot of the purchase at `disposition_date`. The disposition is classified as `QUALIFYING` if and only if `disposition_date` is at or after the purchase's `grant_date` plus two years AND at or after the purchase's `purchase_date` plus one year; otherwise it is classified as `DISQUALIFYING`. (In other words, classification follows the same date arithmetic as the maturation sweep, evaluated at the supplied disposition date rather than at the current clock.)

Tax computation then proceeds in a variant-specific way. For a `QUALIFYING` disposition, the system applies the IRC 423(c) lesser-of test: the actual per-share gain is `sale_price_per_share_cents` minus the purchase's `purchase_price_cents`; the theoretical per-share discount is the purchase's `chosen_fmv_cents` multiplied by the plan's `discount_bp` and divided by ten thousand, rounded half-up to the nearest whole cent (this is the only rounding step in the tax split); the per-share ordinary income is the larger of zero and the smaller of the actual gain and the theoretical discount; `ordinary_income_cents` is `shares_disposed` times that per-share ordinary income; the per-share capital basis is the purchase's `purchase_price_cents` plus the per-share ordinary income; and `capital_gain_cents` is `shares_disposed` times the difference between `sale_price_per_share_cents` and the per-share capital basis. The qualifying treatment is taxpayer-favorable: ordinary income is bounded by the smaller of actual gain and theoretical discount.

For a `DISQUALIFYING` disposition, the spread at purchase is recognized as ordinary income regardless of sale price: the per-share ordinary income is the larger of zero and the difference between the purchase's `purchase_date_fmv_cents` and `purchase_price_cents`; `ordinary_income_cents` is `shares_disposed` times that per-share ordinary income; the per-share capital basis is `purchase_price_cents` plus the per-share ordinary income; and `capital_gain_cents` is `shares_disposed` times the difference between `sale_price_per_share_cents` and the per-share capital basis. (Capital gain may be negative, representing a capital loss.) The contrast with the qualifying variant is deliberate and consequential: disqualifying treatment recognizes the full purchase-date spread as ordinary income regardless of whether the participant actually realized that much; qualifying treatment caps ordinary income at the smaller of actual gain or theoretical discount.

A disposition row is written with `status` set to `REPORTED`. When the supplied `shares_disposed` equals the remaining undisposed share count on the purchase, the system also flips the purchase's `disposition_status` from `HELD` to either `DISPOSED_QUALIFYING` or `DISPOSED_DISQUALIFYING`, matching the classification. The disposition row carries a mirrored `participant_id` copied from the purchase. The acting participant remains the sole authorized actor on every subsequent disposition operation.

The owning participant may amend a `REPORTED` disposition through a patch that accepts any subset of `disposition_date`, `shares_disposed`, and `sale_price_per_share_cents`, together with an optional `version` for optimistic concurrency. A patch is allowed only when the disposition's status is `REPORTED` (an `AMENDED` or `VOIDED` disposition is rejected with `ERR_INVALID_DISPOSITION_STATE`). On amendment, the system re-evaluates classification, recomputes `ordinary_income_cents` and `capital_gain_cents` from the current purchase fields, and updates the disposition's status to `AMENDED`. If the classification flips as a result of the amendment, the purchase's `disposition_status` is updated to match the new classification.

The owning participant may also void a disposition through a delete operation. Voiding is allowed from either `REPORTED` or `AMENDED` (it is the one transition shared by both source states); the disposition's status moves to `VOIDED`. As a side effect, the purchase's `disposition_status` is restored to `HELD` if no other non-voided disposition exists on the purchase. A race between an amendment and a void on the same disposition serializes such that exactly one wins; the loser observes the disposition's status outside `REPORTED`/`AMENDED` and is rejected with `ERR_INVALID_DISPOSITION_STATE`.

Dispositions can be listed per participant with two filters: `classification` narrows by qualifying versus disqualifying, and `status` narrows by lifecycle stage. The Form 3922 records issued at purchase time remain unaffected by any disposition activity; per §2.8, they are immutable. A participant's full Form 3922 list for a calendar year is retrievable through a per-participant endpoint that takes a `calendar_year` query parameter.

### 3.8. Accrual Headroom and the Dilution Preview

To support both participant self-service and plan-administrator forecasting, the API exposes a per-participant accrual summary capability and a per-plan dilution-preview capability.

The accrual summary is computed for a `calendar_year` (a required query parameter) and an optional `include_projection` boolean (defaulting to true). The committed component sums `Enrollment.ytd_accrual_cents` over every enrollment for the participant whose owning offering period has a `start_date` whose year matches the requested `calendar_year` and whose `status` is in the set {`ACTIVE`, `COMPLETED`, `WITHDRAWN`}. The projection component, included when `include_projection` is true, estimates the grant-FMV-priced accrual that would result from the contributions already posted on the participant's still-`ACTIVE` enrollments. For each such enrollment, the projection takes the sum of `amount_cents` over its `POSTED` contributions, divides it by the per-share price that would apply if the batch ran right now (computed as the smaller of `grant_date_fmv_cents` and the purchase-date FMV when the latter is non-null — falling back to `grant_date_fmv_cents` if the purchase-date FMV is still null — discounted by the plan's `discount_bp` and rounded half-up at the per-share price), takes the integer floor of that quotient to get projected shares, and multiplies projected shares by `grant_date_fmv_cents` to get the projected accrual contribution. The remaining-headroom value reported by the summary is `Plan.annual_accrual_cap_cents` minus the committed component minus (when included) the projection component. Two variants are exposed: with `include_projection` set to false, only the committed component is reported and projections from in-flight enrollments are excluded; with `include_projection` set to true (the default), the projection is added and the resulting remaining-headroom value is therefore the smaller of the two. All values are integer cents.

The dilution preview is computed for a plan and a `eligible_employee_count` query parameter supplied by the caller. It produces a single weighted score on a 0-to-100 scale that summarizes how diluting the plan is expected to be. The score combines three normalized factors: a rate factor equal to the smaller of 1.0 and `Plan.max_contribution_rate_bp` divided by 1500; a cap factor equal to `Plan.annual_accrual_cap_cents` divided by 2,500,000; and a participation factor equal to the count of `ACTIVE` enrollments attached to the plan's currently-`OPEN` offering period divided by the larger of 1 and the supplied `eligible_employee_count`. The blending rule is gated on the rate factor at the value 0.5. When the rate factor is less than 0.5, the score is one hundred times the sum of three terms: the rate factor weighted at 0.4, the cap factor multiplied by the rate factor squared and weighted at 0.3, and the participation factor multiplied by the rate factor squared and weighted at 0.3 — i.e. the cap and participation contributions are scaled down by the square of the rate factor in the low-rate regime. When the rate factor is at or above 0.5, the score is one hundred times the sum of the rate factor weighted at 0.4, the cap factor weighted at 0.3, and the participation factor weighted at 0.3, with no additional scaling. The final score is rounded half-up to the nearest whole integer in the range from 0 through 100.

## 4. Endpoint Definitions

Operations that create a new, distinct resource (a plan, an offering period created as a side effect, an enrollment, a contribution, a disposition) return `201 Created`. Operations that modify an existing resource, including state-transition actions (activate, terminate, withdraw, run-purchase, advance the clock, run the sweep, record FMVs) and patch operations, return `200 OK`. The delete operation on a disposition is the lone exception: it returns `204 No Content` because the response body would otherwise be redundant with the now-terminal state. Errors follow the §5 catalog with the HTTP status codes listed there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/plans` | Create a Plan in DRAFT | PlanAdministrator |
| GET    | `/plans` | List Plans (paginated; filter by status) | PlanAdministrator, TaxAuthority |
| GET    | `/plans/{plan_id}` | Retrieve a Plan | PlanAdministrator, PayrollAgent, Participant, TaxAuthority |
| PATCH  | `/plans/{plan_id}` | Edit DRAFT plan fields with OCC | PlanAdministrator |
| POST   | `/plans/{plan_id}/activate` | Transition Plan DRAFT to ACTIVE and create the first OfferingPeriod | PlanAdministrator |
| POST   | `/plans/{plan_id}/terminate` | Transition Plan ACTIVE to TERMINATED | PlanAdministrator |
| GET    | `/plans/{plan_id}/dilution-preview` | Compute the dilution warning score for the plan | PlanAdministrator |
| GET    | `/plans/{plan_id}/offering-periods` | List offering periods of the plan (paginated) | PlanAdministrator, PayrollAgent, Participant, TaxAuthority |
| GET    | `/offering-periods/{offering_period_id}` | Retrieve an OfferingPeriod | PlanAdministrator, PayrollAgent, Participant, TaxAuthority |
| POST   | `/plans/{plan_id}/offering-periods/{offering_period_id}/grant-fmv` | Record grant-date FMV on the period | PlanAdministrator |
| PATCH  | `/offering-periods/{offering_period_id}/fmv` | Record purchase-date FMV on the period with OCC | PlanAdministrator |
| POST   | `/offering-periods/{offering_period_id}/run-purchase` | Execute the purchase batch on a CLOSED period | PlanAdministrator |
| POST   | `/offering-periods/{offering_period_id}/enrollments` | Participant enrolls in an OPEN period | Participant |
| GET    | `/enrollments/{enrollment_id}` | Retrieve an Enrollment | PlanAdministrator, PayrollAgent, Participant, TaxAuthority |
| PATCH  | `/enrollments/{enrollment_id}` | Change contribution rate with OCC | Participant |
| POST   | `/enrollments/{enrollment_id}/withdraw` | Withdraw an enrollment | Participant |
| POST   | `/enrollments/{enrollment_id}/contributions` | Post a contribution for a pay period | PayrollAgent |
| GET    | `/enrollments/{enrollment_id}/contributions` | List contributions on an enrollment (paginated) | PlanAdministrator, PayrollAgent, Participant, TaxAuthority |
| GET    | `/purchases/{purchase_id}` | Retrieve a Purchase | PlanAdministrator, Participant, TaxAuthority |
| GET    | `/participants/{participant_id}/purchases` | List a participant's purchases (paginated; filter by holding/disposition status) | PlanAdministrator, Participant, TaxAuthority |
| GET    | `/form-3922/{form_id}` | Retrieve a Form 3922 (immutable) | PlanAdministrator, Participant, TaxAuthority |
| GET    | `/participants/{participant_id}/form-3922` | List Form 3922 records for a participant in a calendar year (paginated) | PlanAdministrator, Participant, TaxAuthority |
| GET    | `/participants/{participant_id}/accrual-summary` | Per-participant accrual summary with optional projection | PlanAdministrator, Participant, TaxAuthority |
| POST   | `/dispositions` | Report a disposition | Participant |
| GET    | `/dispositions/{disposition_id}` | Retrieve a Disposition | PlanAdministrator, Participant, TaxAuthority |
| PATCH  | `/dispositions/{disposition_id}` | Amend a REPORTED Disposition with OCC | Participant |
| DELETE | `/dispositions/{disposition_id}` | Void a Disposition | Participant |
| GET    | `/participants/{participant_id}/dispositions` | List a participant's dispositions (paginated; filter by classification, status) | PlanAdministrator, Participant, TaxAuthority |
| POST   | `/_clock/advance` | Advance SystemClock.current_time to a supplied timestamp | PlanAdministrator |
| GET    | `/_clock` | Return SystemClock | PlanAdministrator, PayrollAgent, Participant, TaxAuthority |
| POST   | `/_sweep/run` | Run the maturation sweep | PlanAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_AUTH_INVALID_ROLE` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_PERIOD_STATE` | 409 Conflict |
| `ERR_INVALID_ENROLLMENT_STATE` | 409 Conflict |
| `ERR_INVALID_DISPOSITION_STATE` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_PLAN_NAME` | 409 Conflict |
| `ERR_PERIOD_LENGTH_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CONTRIBUTION_RATE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ANNUAL_ACCRUAL_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FMV_BEFORE_PERIOD_END` | 409 Conflict |
| `ERR_GRANT_FMV_WINDOW` | 409 Conflict |
| `ERR_DISPOSITION_DATE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_SHARES_EXCEED_BALANCE` | 422 Unprocessable Entity |
| `ERR_FORM_3922_IMMUTABLE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_PAGINATION_INVALID` | 422 Unprocessable Entity |
| `ERR_CLOCK_NOT_ADVANCING` | 422 Unprocessable Entity |
