# Shed & Accessory Structure Sales API — Product Requirements Document

## 1. Introduction

A backyard-structure dealer lives and dies by two disciplines: quoting a building correctly the first time, and never dispatching a crew to a site that cannot legally or physically receive the structure. Every sale threads a regulatory gauntlet that varies county by county — permit thresholds measured in square feet, setback minimums on three sides of the lot, wind-code anchoring mandates — and a logistics gauntlet that varies lot by lot: narrow gates, sloped ground, an old shed that must come out before the new one goes in. Layered on top are two ways to pay, outright cash purchase or a rent-to-own contract with monthly installments, plus a twelve-month warranty with its own service economy and crews whose calendars must never be double-booked.

This document specifies the API that runs such a dealership end to end. It covers catalog and jurisdiction setup, order configuration with tiered pricing, the site-suitability assessment, permit determination under a pinned rule set, scheduling and installation, cash collection and cancellation refunds, rent-to-own servicing with a delinquency sweep, and post-installation warranty service. All temporal behavior — scheduling deadlines, grace windows, installment due dates, warranty expiry — is evaluated against a controllable logical clock rather than wall-clock time, so every date-sensitive rule resolves deterministically. The API is mounted under `/api`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the six declared roles — `Customer`, `SalesRep`, `PermitCoordinator`, `InstallCrew`, `FinanceManager`, and `OperationsAdmin`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works as follows. When `X-User-Role` is `Customer`, the `X-User-ID` value is the `id` of the acting `Customer` record; ownership checks on any resource trace through the parent order, comparing the order's `customer_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `SalesRep`, `PermitCoordinator`, `InstallCrew`, `FinanceManager`, or `OperationsAdmin`, the `X-User-ID` value is an opaque staff identifier not tied to any persisted entity; the server may record it (for example, as `recorded_by` on a payment) but never compares it to any entity's `id`. Unless an endpoint states a narrower role set in §4, read endpoints accept any of the six declared roles.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets how many items to skip and defaults to 0. Unless stated otherwise, every list is sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. The order listing additionally accepts the optional filters `customer_id`, `model_id`, `jurisdiction_id`, and `status` alongside `limit` and `offset`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; `updated_at`, an ISO 8601 UTC timestamp refreshed on any change to the resource; and `version`, an integer starting at 1 that increments by exactly one on every mutation, including system-driven state transitions. One exception exists: a recorded payment is immutable, so it carries only `id` and `created_at` — both `updated_at` and `version` are absent from payment resources.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer numbers of cents, conveyed in fields suffixed with `_cents`. Every monetary computation rounds to whole cents using round-half-up. Where a price is assembled from several fee lines, each fee line is individually rounded to whole cents before the lines are summed, tax is computed from already-rounded components, and the total is computed last. This pinned evaluation order is described with the pricing workflow in §3.2.

### 2.6. The Logical Clock

Date and time evaluations never read wall-clock time. The server maintains a logical clock whose startup value is exactly `2026-08-01T00:00:00Z`; before the clock is ever set, it reads this default and never falls back to wall-clock time. An `OperationsAdmin` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`. Scheduling deadlines, assessor visit dates, warranty windows, installment due dates, grace periods, and the delinquency sweep all evaluate against this clock.

### 2.7. Optimistic Concurrency and Rule-Set Version Pinning

Two write operations are guarded by optimistic concurrency. Amending an order requires the request to carry `expected_order_version`, holding the `version` the client last observed for that order; if the order's current `version` has advanced past the supplied value, the amend is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard matters because amending never changes the order's state — a `DRAFT` order stays in `DRAFT` — so a second amend carrying a stale version would otherwise see a perfectly valid state and succeed. Updating a jurisdiction's rule set works the same way with `expected_jurisdiction_version` and the same `ERR_STALE_VERSION` (HTTP 412) rejection: rule edits do not change the jurisdiction's own state, so the version check is the only thing standing between a stale writer and a silent overwrite. No other endpoint accepts a version field.

A related but distinct mechanism protects permit decisions: each permit application pins the `jurisdiction_version` of the rule set in force at determination time, and deciding an application whose pinned version no longer matches the jurisdiction's current `version` is rejected with `ERR_STALE_RULE_SET` (HTTP 409). §3.4 covers this in full.

### 2.8. The Validation Pipeline

Every request is validated in a fixed order, and a failure at any stage masks every later check:

1. **Authentication** — both headers present and the role declared (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role is permitted on the endpoint and, for `Customer` callers, the targeted resource belongs to that customer (`ERR_FORBIDDEN`).
3. **Request shape** — required fields present, value types correct, enum members valid, and conditional requirements satisfied (`ERR_INVALID_REQUEST`). Conditional requirements include `rto_term_months` on a rent-to-own order, `old_structure_area_sqft` when removal is requested, and `prep_cost_cents` when an assessor flags prep work.
4. **Existence** — path identifiers are validated left to right, then body foreign keys (`customer_id`, `model_id`, `jurisdiction_id`, `order_id`) must resolve to existing records (`ERR_NOT_FOUND`).
5. **Stale-version guards** — the OCC checks of §2.7 (`ERR_STALE_VERSION`).
6. **State preconditions** — the target resource must be in a state that allows the requested transition (`ERR_INVALID_STATE`).
7. **Business rules**, in the per-endpoint order stated throughout §3 — for example, on order creation and amendment the anchoring rule is evaluated before dimension bounds, which are evaluated before delivery-mode support.

### 2.9. Idempotent Payment Recording

Both payment-collection endpoints accept an `idempotency_key`. Replaying a key with an identical payload — the same `amount_cents` and `method` on the same order or contract — returns the originally recorded payment row without creating a duplicate. Reusing a key with a different amount or method is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Setting Up the Book: Jurisdictions, Models, and Customers

Before the first order can be quoted, a `PermitCoordinator` authors the rule book for each county the dealership serves. A jurisdiction record carries a display `name`, a two-letter `state_code`, and a `county_name`; the permit rule `permit_threshold_sqft`, an inclusive floor area at or above which a permit is required; the three setback minimums `setback_front_ft`, `setback_side_ft`, and `setback_rear_ft`; a `max_building_height_ft` cap for accessory structures; an `anchoring_required` flag reflecting the local wind code; the two permit-fee components `permit_base_fee_cents` and `permit_per_sqft_cents`; and `tax_rate_bp`, the sales-tax rate in basis points, which applies to the structure and its options only — delivery, foundation, anchoring, site prep, and removal charges are never taxed. A jurisdiction is created at `version` 1. Rule edits go through the OCC-guarded update described in §2.7: each successful edit bumps the jurisdiction's `version`, and every permit application pinned to an older version immediately becomes stale (§3.4).

The sales catalog is maintained by a `SalesRep`. Each structure model declares a `name` and catalog `sku`; the configurable footprint bounds `min_width_ft`, `max_width_ft`, `min_depth_ft`, and `max_depth_ft`, all inclusive; a fixed `wall_height_ft`; the `supported_delivery_modes` the model can be sold with, a subset of `PRE_BUILT` and `ON_SITE_BUILD`; and its price book: `base_price_cents`, which buys the base area — the minimum width times the minimum depth — plus `overage_rate_tier1_cents`, the per-square-foot price of the first forty square feet above the base area, and `overage_rate_tier2_cents`, the per-square-foot price beyond that.

Customers are registered by a `SalesRep` with `full_name`, `email`, `phone`, and the site address fields `street`, `city`, `state_code`, and `zip`. The registered customer's `id` becomes the ownership anchor for everything that customer later touches.

### 3.2. Configuring and Pricing an Order

A `SalesRep` opens a sale by creating an order that references a `customer_id`, a `model_id`, and the governing `jurisdiction_id`, then configures the building itself: `width_ft` and `depth_ft` within the model's inclusive bounds; a `delivery_mode` the model supports; a `foundation_type` of `GRAVEL_PAD`, `CONCRETE_SLAB`, `PIERS`, or `NONE`; an `anchor_type` of `AUGER_STRAP` or `NONE`; and a `purchase_type` of `CASH` or `RTO`. A rent-to-own order must also supply `rto_term_months`, a term of at least 12 and at most 60 months, which is mandatory exactly when the purchase type is `RTO`. The `options` list may carry any subset of `WINDOW`, `LOFT`, `RAMP`, and `ELECTRICAL` and defaults to empty. Removal is off by default; when the crew is to haul away an old structure, `removal_requested` is set and `old_structure_area_sqft`, the old footprint, becomes mandatory. An appraised `trade_in_appraised_cents` may optionally offset the price. A new order starts in `DRAFT` with `structure_state` set to `NOT_INSTALLED`.

Three configuration rules are enforced on both creation and amendment, evaluated in this order: first, when the governing jurisdiction's `anchoring_required` is true, an `anchor_type` of `NONE` is rejected with `ERR_ANCHOR_REQUIRED`; second, dimensions outside the model's bounds are rejected with `ERR_CONFIG_OUT_OF_BOUNDS`; third, a `delivery_mode` absent from the model's supported list is rejected with `ERR_DELIVERY_MODE_UNSUPPORTED`.

Pricing runs at creation, on every amendment, and again at completion. The configured `area_sqft` is the width times the depth. The structure price, recorded as `structure_price_cents`, starts at the model's base price and adds tiered overage: the overage is the amount by which the configured area exceeds the base area, never less than zero; the first forty square feet of overage price at the tier-one rate, and any remainder prices at the tier-two rate. Options add $150.00 for each `WINDOW`, $250.00 for each `LOFT`, $100.00 for each `RAMP`, and $400.00 for each `ELECTRICAL`. Delivery adds a flat $250.00 for `PRE_BUILT` or $450.00 for `ON_SITE_BUILD`. Foundation pricing depends on the type: a `GRAVEL_PAD` costs $8.00 per square foot of configured area; a `CONCRETE_SLAB` costs $15.00 per square foot with a $2,000.00 minimum; `PIERS` are counted by dividing the width in feet by four and rounding up, dividing the depth in feet by four and rounding up, multiplying the two counts, and charging $120.00 per pier; `NONE` costs nothing. Anchoring with `AUGER_STRAP` requires four anchors plus two additional anchors for every full hundred square feet of footprint, at $75.00 per anchor; an `anchor_type` of `NONE` costs nothing. Site prep contributes `site_prep_fee_cents`, which is zero until an assessment files a prep verdict (§3.3). Removal, when requested, adds $300.00 plus $5.00 per square foot of the old structure. The trade-in credit is the lesser of the appraised value — treated as zero when absent — and fifteen percent of the structure price, rounded down to whole cents.

The order of operations is pinned: compute every fee line first and round each to whole cents (half-up), then sum structure price, options, delivery, foundation, anchoring, prep, and removal, subtract the trade-in credit, and floor the subtotal at zero. Tax is then computed on the rounded structure-plus-options sum at the jurisdiction's rate and rounded half-up to whole cents. For a `CASH` purchase, the total is the subtotal plus the tax. For an `RTO` purchase, the subtotal is first multiplied by 1.6 and rounded half-up to whole cents, and the tax is added afterward — identical configurations therefore quote higher under rent-to-own than under cash. The estimate produced at creation and at each amendment is stored as `quoted_total_cents`; the identical formula is recomputed at completion and stored as `final_total_cents`.

Amendment is a `SalesRep` action available only while the order is in `DRAFT`; amending in any other state is rejected with `ERR_INVALID_STATE`. The request must carry `expected_order_version` per §2.7 and may revise `width_ft`, `depth_ft`, `options`, `delivery_mode`, `foundation_type`, `anchor_type`, `rto_term_months`, `removal_requested`, `old_structure_area_sqft`, and `trade_in_appraised_cents`; the customer, model, and jurisdiction anchors are fixed for the life of the order. A successful amend increments the order's `version` and recomputes `area_sqft`, `structure_price_cents`, and `quoted_total_cents`.

Two computed counters round out the order's financial picture: `collected_cents`, the sum of every `DEPOSIT` and `BALANCE` payment recorded against the order, and `refunded_cents`, the sum of every `REFUND` (§3.6). Both start at zero, as does `retained_cents`, and `site_prep_required` starts false.

### 3.3. The Site Assessment: Windows, Measurements, and the Suitability Verdict

When the configuration is ready, a `SalesRep` submits the order for a site suitability check, supplying an `assessor_id`, a `scheduled_date`, and a `window_start_hour`. The visit occupies a half-open two-hour window: the start hour itself is included, the hour two later is not, and the start hour must be at least 6 and at most 20. The order must still be in `DRAFT`, otherwise the submission is rejected with `ERR_INVALID_STATE`. Among the business checks, the assessor's calendar is examined first — if another assessment with the same `assessor_id` on the same date is still in `REQUESTED` and its window overlaps the proposed one, the submission is rejected with `ERR_ASSESSOR_WINDOW_CONFLICT` — and only then is the date validated, with a `scheduled_date` before the current logical date rejected with `ERR_DATE_IN_PAST`. A successful submission moves the order from `DRAFT` to `SITE_REVIEW`, increments the order's `version`, and creates the linked `SiteAssessment` in `REQUESTED`, its `order_id` taken from the order being submitted.

An `InstallCrew` member later files the report — allowed only while the assessment is in `REQUESTED` — recording `measured_access_width_in` (the narrowest delivery access point, in inches), `measured_slope_pct`, the three measured setbacks `setback_front_ft`, `setback_side_ft`, and `setback_rear_ft`, and whether `ground_prep_needed` is true. Flagging prep work makes `prep_cost_cents` mandatory; omitting it is rejected with `ERR_INVALID_REQUEST`. Filing stamps `reported_at` from the logical clock, moves the assessment from `REQUESTED` to `REPORTED`, increments the assessment's `version`, and computes the `verdict`.

The verdict logic compares the filing against the jurisdiction's rule book. The required access width depends on how the building arrives: a `PRE_BUILT` delivery must fit the whole structure through the gate, so the requirement is the order's width converted to inches plus a twelve-inch margin; an `ON_SITE_BUILD` needs only a thirty-six-inch carry-in path for materials — identical site measurements can therefore pass one delivery mode and fail the other. The site hard-fails when any measured setback is strictly less than the jurisdiction's corresponding minimum, when the measured slope is strictly greater than fifteen percent, or when the measured access width is less than the requirement, noting that an access measurement exactly equal to the requirement passes. A hard fail yields a verdict of `UNSUITABLE`. Otherwise, if the measured slope is strictly greater than eight percent or the crew flagged prep work, the verdict is `SUITABLE_WITH_PREP`; anything else is `SUITABLE`.

The verdict drives the order automatically. On `SUITABLE` or `SUITABLE_WITH_PREP`, the order advances from `SITE_REVIEW` to `PERMIT_REVIEW` and a permit application is created as described in §3.4; a `SUITABLE_WITH_PREP` verdict additionally sets `site_prep_required` to true, copies the filed `prep_cost_cents` into `site_prep_fee_cents`, and recomputes `quoted_total_cents`. On `UNSUITABLE`, the order falls back from `SITE_REVIEW` to `DRAFT` for reconfiguration, and a later submission creates an entirely new assessment rather than resurrecting the old one. Each automatic move increments the order's `version` and refreshes `updated_at`.

### 3.4. Permit Determination Under a Pinned Rule Set

Entering `PERMIT_REVIEW` creates the `PermitApplication` as the jurisdiction's determination artifact, keyed back to its order through `order_id`. The application copies `jurisdiction_id` from the order, pins the jurisdiction's current `version` into `jurisdiction_version`, snapshots the order's `area_sqft`, and computes two derived values: `permit_required`, true exactly when the snapshot area is at least the jurisdiction's `permit_threshold_sqft` — an order landing exactly on the threshold needs a permit — and `fee_cents`, which is zero when no permit is required and otherwise the jurisdiction's base fee plus its per-square-foot rate times the area, rounded half-up to whole cents. When no permit is required, the application is recorded directly in `NOT_REQUIRED`, and that creation outcome itself advances the order from `PERMIT_REVIEW` to `READY_TO_SCHEDULE` with no human touch.

Otherwise the application sits in `SUBMITTED`, awaiting a `PermitCoordinator`. Both approval and denial first verify the pin: if the jurisdiction's rule set has been edited since determination, so that the application's `jurisdiction_version` no longer equals the jurisdiction's current `version`, the decision is rejected with `ERR_STALE_RULE_SET` (HTTP 409) — a decision is accepted only while the application still rests on the rule set it was determined under. Approval sets `decided_at` from the logical clock and advances the order from `PERMIT_REVIEW` to `READY_TO_SCHEDULE`. Denial sets `decided_at`, records the coordinator's optional `decision_note`, and reverts the order from `PERMIT_REVIEW` to `DRAFT` for reconfiguration — the denial itself is what triggers that revert. Each automatic order move increments the order's `version`. Applications still `SUBMITTED` when their order is cancelled from `PERMIT_REVIEW` are withdrawn automatically (§3.6). `APPROVED`, `DENIED`, `NOT_REQUIRED`, and `WITHDRAWN` are terminal.

### 3.5. Scheduling, Installation, and Completion

From `READY_TO_SCHEDULE`, a `SalesRep` books the build with a `scheduled_date` and a `crew_id`. Three checks run in order. Crew occupancy comes first: if the crew is already committed on that calendar date — by another order in `SCHEDULED` or `IN_PROGRESS`, or by a service visit in `SCHEDULED` — the booking is rejected with `ERR_CREW_DATE_CONFLICT`. Then the calendar: a `scheduled_date` before the current logical date is rejected with `ERR_DATE_IN_PAST`. Then the money: a `CASH` order may not be scheduled until `collected_cents` reaches at least twenty percent of `quoted_total_cents`, rounded half-up to whole cents — the boundary is inclusive, and a shortfall is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402). Rent-to-own orders are exempt from the deposit gate. A successful booking records the date and crew on the order, moves it from `READY_TO_SCHEDULE` to `SCHEDULED`, and increments its `version`.

On or after the booked date, the `InstallCrew` starts the job; starting before the current logical date has reached the order's `scheduled_date` is rejected. Starting moves the order from `SCHEDULED` to `IN_PROGRESS` and increments its `version`. Completion, likewise declared by the `InstallCrew`, moves the order from `IN_PROGRESS` to `COMPLETED` and settles the financial picture: `completed_at` is stamped from the logical clock, `warranty_ends_at` is set to exactly twelve months after completion, `final_total_cents` is computed through the same pinned pricing pipeline of §3.2, and `structure_state` becomes `INSTALLED`. For a rent-to-own order, completion additionally creates the `RtoContract` described in §3.7 — and that creation itself closes the order, because an order closes automatically the moment it is fully settled: for a cash order, when `collected_cents` minus `refunded_cents` reaches at least `final_total_cents`; for a rent-to-own order, the moment its contract exists in `ACTIVE`. The automatic `COMPLETED` → `CLOSED` transition increments the order's `version`.

### 3.6. Cash Collection, Cancellation, and the Refund Waterfall

Money against an order is recorded by a `FinanceManager` or by the owning `Customer`, supplying `amount_cents` (a positive whole-cent amount), a `method` of `CASH`, `CARD`, or `CHECK`, and an `idempotency_key` per §2.9. Order-level collection is open only while the order's status is one of `SITE_REVIEW`, `PERMIT_REVIEW`, `READY_TO_SCHEDULE`, `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED`; attempts on a `DRAFT`, `CANCELLED`, or `CLOSED` order are rejected with `ERR_INVALID_STATE`. After the state gate, three checks run in order: first, the amount must not exceed the order's outstanding balance — its quoted total, or its final total once completed, net of what has already been collected — with any excess rejected as `ERR_OVERPAYMENT`; second, because rent-to-own balances live on the contract, an order-level payment on an `RTO` order is rejected with `ERR_ORDER_NOT_PAYABLE`; third, a reused `idempotency_key` carrying a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT`.

The first payment recorded against an order takes a `kind` of `DEPOSIT`; every later one takes a `kind` of `BALANCE`. Both carry the order's `order_id`, a null `rto_contract_id`, and `recorded_by` capturing the recorder's `X-User-ID`. Each posting recomputes `collected_cents`, and when a payment pushes a `COMPLETED` cash order to the point where collected-minus-refunded covers `final_total_cents`, the order closes itself as described in §3.5.

Cancellation is available to a `SalesRep` or the owning `Customer` from any state up through `SCHEDULED`, with an optional `reason`; cancelling an order that is `IN_PROGRESS`, `COMPLETED`, or `CLOSED` is rejected with `ERR_INVALID_STATE`. Cancellation settles the account through a fixed waterfall. First, a $50.00 administrative fee is always retained. Second, when the order's latest permit application is still `SUBMITTED` or already `APPROVED` and the order is being cancelled from `PERMIT_REVIEW`, `READY_TO_SCHEDULE`, or `SCHEDULED`, that application's `fee_cents` is retained as a non-refundable permit fee. Third, cancelling from `READY_TO_SCHEDULE` or `SCHEDULED` adds a restocking fee of ten percent of `structure_price_cents`, rounded half-up to whole cents. The amount retained, stored as `retained_cents`, is the smaller of the collected amount and the sum of the three buckets; the remainder of `collected_cents` is the refund, so refund plus retained always equals the collected amount exactly. When the refund is positive, the system records a payment with a `kind` of `REFUND` and `refunded_cents` is updated accordingly.

Cancellation also cleans up in-flight work. An assessment still `REQUESTED` moves to `CANCELLED`, while a `REPORTED` one is left untouched, and a permit application still `SUBMITTED` moves to `WITHDRAWN`. Cancelling a `SCHEDULED` order additionally frees the booked `crew_id` and `scheduled_date`, so the crew day no longer counts as occupied. Every cancellation increments the order's `version`.

### 3.7. Rent-to-Own Contracts and the Delinquency Sweep

Completing a rent-to-own order creates its `RtoContract` in `ACTIVE`, tied to the `order_id`, with `term_months` copied from the order and `total_contract_cents` equal to the RTO-variant total from §3.2. An order produces at most one contract, so reading the contract through its order returns an array containing zero or one element. The installment plan is derived in a pinned order: the regular installment `monthly_payment_cents` is the contract total divided by the term, rounded half-up to whole cents, and `final_payment_cents` is whatever remains after the regular installment has been charged for every month but the last — the rounded monthly installments plus the final installment therefore always sum back to the contract total exactly. The `first_due_date` falls thirty days after the completion date, and installments come due every thirty days after that. The contract also tracks `amount_applied_cents` (principal paid down), `remaining_balance_cents` (the contract total minus principal applied), `accrued_late_fees_cents` (outstanding unpaid late fees), `written_off_cents`, and `delinquency_episodes`, all starting at zero.

Contract payments — recorded by a `FinanceManager` or the owning `Customer` with the same `amount_cents`, `method`, and `idempotency_key` shape as order payments — are recorded with a `kind` of `RTO_PAYMENT` and the contract's `rto_contract_id` set, and apply as a waterfall: the payment first extinguishes accrued late fees, recorded as `applied_to_late_fees_cents`, and the remainder reduces principal, recorded as `applied_to_principal_cents`. The contract's derived figures are then recomputed. Symmetric to the order-side rule, a payment on a contract already `PAID_OFF` or `DEFAULTED` is rejected with `ERR_ORDER_NOT_PAYABLE` — and a cash order never has a contract to pay — while an amount exceeding `remaining_balance_cents` plus accrued late fees is rejected with `ERR_OVERPAYMENT`. When a payment on a `DELINQUENT` contract covers every past-due installment and every accrued late fee, the contract cures from `DELINQUENT` back to `ACTIVE`, with `delinquency_episodes` retained as history. Whenever `remaining_balance_cents` reaches zero, the contract moves to `PAID_OFF`, whether it was `ACTIVE` or `DELINQUENT` at the time.

A `FinanceManager` runs the delinquency sweep against the logical clock. The sweep walks every contract in `ACTIVE` or `DELINQUENT` — `PAID_OFF` and `DEFAULTED` contracts are excluded — in order of earliest `first_due_date`, breaking ties by `created_at`. For each contract, an installment counts as due once its due date plus a seven-day grace period falls strictly before the current logical date, and the covered count is the whole number of monthly installments that the applied principal pays for. An `ACTIVE` contract with more installments due than covered moves from `ACTIVE` to `DELINQUENT`, gains one to `delinquency_episodes`, and accrues one late fee of ten percent of the monthly installment, rounded half-up to whole cents. A `DELINQUENT` contract whose earliest uncovered due date lies at least forty-five days in the past — the boundary is inclusive — moves from `DELINQUENT` to `DEFAULTED`: its `written_off_cents` is set to the full `remaining_balance_cents`, the remaining balance is zeroed, and the order's `structure_state` moves from `INSTALLED` to `REPOSSESSION_PENDING`. After all contracts are evaluated, the sweep executes repossession: every order sitting in `REPOSSESSION_PENDING` moves to `REPOSSESSED`. Throughout, applied principal plus remaining balance plus written-off principal always equals the contract total. The sweep reports how many contracts were newly marked delinquent in `contracts_marked_delinquent` and how many were defaulted in `contracts_defaulted`.

### 3.8. Warranty Service and the Ticket Cycle

Once an order is `COMPLETED` or `CLOSED`, the owning `Customer` or a `SalesRep` can open a `ServiceTicket` by supplying the `order_id` and an `issue_description`; opening a ticket against an order that has not reached one of those states is rejected with `ERR_ORDER_NOT_COMPLETED`. New tickets start `OPEN`. A `SalesRep` then schedules the visit with a `crew_id` and a `scheduled_date`: the crew whole-day occupancy rule is shared with order scheduling — one calendar across orders in `SCHEDULED` or `IN_PROGRESS` and service visits in `SCHEDULED` — with the conflict check evaluated before the date check, conflicts rejected as `ERR_CREW_DATE_CONFLICT`, and a `scheduled_date` before the current logical date rejected as `ERR_DATE_IN_PAST`. Scheduling moves the ticket from `OPEN` to `SCHEDULED`, records the crew and date, and increments the ticket's `version`.

Resolution is filed by the `InstallCrew` with an optional `parts_cents` that defaults to zero. Resolving stamps `resolved_at` from the logical clock, computes `in_warranty` — true when the resolution time is on or before the order's `warranty_ends_at`, the boundary inclusive — and sets `charge_cents`: zero while in warranty, otherwise a $150.00 service-call base plus the declared parts. The ticket moves from `SCHEDULED` to `RESOLVED`, and its `version` increments.

The ticket machine is cyclic. The owning `Customer` may reopen a resolved ticket, but only within thirty days of `resolved_at` and only while the order's warranty is still running; a reopen outside either bound is rejected with `ERR_INVALID_STATE`. Reopening returns the ticket from `RESOLVED` to `OPEN`, increments `reopen_count` from its initial zero, and increments `version`. A ticket may cycle any number of times within the warranty window.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — jurisdictions, models, customers, orders, site-check submissions (which create the assessment), payment records, and service tickets. Operations that modify an existing resource or render a decision return a `200 OK` status code. Every read endpoint accepts all six declared roles; write endpoints name their permitted roles in the table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/jurisdictions` | Create a jurisdiction rule set | PermitCoordinator |
| GET | `/api/jurisdictions/{id}` | Get a jurisdiction | All roles |
| PUT | `/api/jurisdictions/{id}` | Update jurisdiction rules (OCC-guarded); bumps version, which stales pinned permit applications | PermitCoordinator |
| GET | `/api/jurisdictions/{id}/permit-applications` | List permit applications determined under a jurisdiction | All roles |
| POST | `/api/models` | Create a structure model (catalog) | SalesRep |
| GET | `/api/models/{id}` | Get a structure model | All roles |
| POST | `/api/customers` | Register a customer | SalesRep |
| GET | `/api/customers/{id}` | Get a customer | All roles |
| POST | `/api/orders` | Create an order in DRAFT with model configuration | SalesRep |
| GET | `/api/orders` | List orders with filters and pagination | All roles |
| GET | `/api/orders/{id}` | Get an order | All roles |
| PUT | `/api/orders/{id}` | Amend order configuration (DRAFT only, OCC-guarded) | SalesRep |
| POST | `/api/orders/{id}/submit-site-check` | Submit order for site suitability check; creates a SiteAssessment | SalesRep |
| POST | `/api/orders/{id}/schedule` | Book delivery/installation date and crew | SalesRep |
| POST | `/api/orders/{id}/start` | Crew starts delivery/build on or after scheduled_date | InstallCrew |
| POST | `/api/orders/{id}/complete` | Mark installation complete; finalizes pricing, warranty, and creates the RTO contract for RTO orders | InstallCrew |
| POST | `/api/orders/{id}/cancel` | Cancel an order with refund waterfall | SalesRep, Customer |
| POST | `/api/orders/{id}/payments` | Record a cash payment (DEPOSIT if first, else BALANCE); idempotent on idempotency_key | FinanceManager, Customer |
| GET | `/api/orders/{id}/payments` | List payments for an order | All roles |
| GET | `/api/payments/{id}` | Get a payment | All roles |
| GET | `/api/orders/{id}/site-assessments` | List site assessments for an order (one per submit cycle) | All roles |
| GET | `/api/site-assessments/{id}` | Get a site assessment | All roles |
| POST | `/api/site-assessments/{id}/report` | File the assessor's measurements; computes verdict and cascades to the order | InstallCrew |
| GET | `/api/orders/{id}/permit-applications` | List permit applications for an order | All roles |
| GET | `/api/permit-applications/{id}` | Get a permit application | All roles |
| POST | `/api/permit-applications/{id}/approve` | Approve a submitted permit (stale rule sets rejected) | PermitCoordinator |
| POST | `/api/permit-applications/{id}/deny` | Deny a submitted permit; order reverts to DRAFT | PermitCoordinator |
| GET | `/api/orders/{id}/rto-contract` | Get the RTO contract for an order (array of 0 or 1) | All roles |
| GET | `/api/rto-contracts/{id}` | Get an RTO contract | All roles |
| POST | `/api/rto-contracts/{id}/payments` | Record an RTO payment; waterfall late fees then principal; may cure delinquency or pay off | FinanceManager, Customer |
| GET | `/api/rto-contracts/{id}/payments` | List payments applied to an RTO contract | All roles |
| POST | `/api/billing/run` | Run the delinquency sweep as of the logical clock | FinanceManager |
| POST | `/api/service-tickets` | Open a warranty/service ticket for a completed order | Customer, SalesRep |
| GET | `/api/service-tickets/{id}` | Get a service ticket | All roles |
| GET | `/api/orders/{id}/service-tickets` | List service tickets for an order | All roles |
| POST | `/api/service-tickets/{id}/schedule` | Schedule a service visit (crew whole-day occupancy shared with orders) | SalesRep |
| POST | `/api/service-tickets/{id}/resolve` | Resolve a scheduled ticket; warranty determines the charge | InstallCrew |
| POST | `/api/service-tickets/{id}/reopen` | Reopen a resolved ticket within the 30-day window while warranty is active | Customer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO8601); startup default is exactly 2026-08-01T00:00:00Z | OperationsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STALE_RULE_SET` | 409 |
| `ERR_ANCHOR_REQUIRED` | 422 |
| `ERR_CONFIG_OUT_OF_BOUNDS` | 422 |
| `ERR_DELIVERY_MODE_UNSUPPORTED` | 422 |
| `ERR_DATE_IN_PAST` | 422 |
| `ERR_ASSESSOR_WINDOW_CONFLICT` | 409 |
| `ERR_CREW_DATE_CONFLICT` | 409 |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_ORDER_NOT_PAYABLE` | 409 |
| `ERR_ORDER_NOT_COMPLETED` | 409 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
