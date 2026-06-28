# Device Protection Insurance API — Product Requirements Document

## 1. Introduction

Mobile device protection programs of the Asurion style sit at the intersection of two disciplines that are notoriously difficult to keep reconciled: a billing ledger that accrues monthly premiums onto a carrier's bill, and a multi-stage claims operation that must adjudicate cracked-screen, lost, and stolen-device events while routing each one to the most economical remedy. This API governs that combined surface. It tracks the customers who hold coverage, the plans that price it, the catalogue of refurbished replacement devices that fulfil approved claims, and the full lifecycle of every enrollment, premium invoice, claim, fraud screen, repair order, advanced exchange, and trade-in that flows through the program.

The system is built around immediate consistency: an action that approves a claim, ships a replacement, or grades a returned handset must settle every dependent figure — depreciated replacement value, deductible tier, trade-in credit, non-return fee, customer risk posture, and remaining annual allowance — in the same operation, so that no reader of any resource ever sees a stale derived number. Because adjudication and logistics run as separate roles acting on shared records, the program also leans on optimistic concurrency: writes that depend on a parent's observed state must declare the version they believe they are acting against, and the server rejects any write built on a view the parent has since outgrown. The sections that follow define the global contract first, then the domain workflows where the business rules live, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `Subscriber`, `ClaimsAdjuster`, and `LogisticsAgent`.

- A `PlatformAdmin` is an operator who manages reference data, drives the enrollment lifecycle, issues billing, and runs the logical clock and sweeps. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`.
- A `Subscriber` is an insured customer who acts on their own enrollments and claims. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning `customer_id` (reached directly, or through the parent enrollment for a claim, invoice, or similar child) to `X-User-ID`. A `Subscriber` acting on a `Claim` or `Enrollment` they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.
- A `ClaimsAdjuster` adjudicates claims — screening, approving, routing, and denying them. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- A `LogisticsAgent` handles replacement logistics: exchanges, trade-ins, and repair completion. When `X-User-Role` is `LogisticsAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Authorization is evaluated before any business rule. The presence of valid headers is checked first; the role's permission for the operation is checked second; only then does the system look up referenced resources and apply domain logic.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its permitted range is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; when two resources share the same `created_at` (the logical clock can mint identical timestamps), ties are broken by ascending creation order, so the earlier-created resource sorts first.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits.

Most resources are also versioned and audited. `Customer`, `Enrollment`, `PremiumInvoice`, `Claim`, `RepairOrder`, `AdvancedExchange`, and `TradeIn` additionally carry an `updated_at` timestamp and an integer `version`. The `version` starts at 1 when the resource is created and increments by exactly 1 on every mutation, including mutations that arrive as a side effect of an operation on another resource; `updated_at` is refreshed on every such mutation. By contrast, `Plan`, `ReplacementSku`, and `FraudScreen` are write-once reference or record artifacts: they carry only `id` and `created_at`, and they have neither an `updated_at` field nor a `version` field.

The system runs on a **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock time. A `PlatformAdmin` may advance the clock to a supplied instant; the supplied target is provided as `to_iso8601`, and the response reports the new `current_utc`. Every timestamp the system records (activation time, ship deadlines, incident-window checks, depreciation age) is read from this logical clock.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each pinned to the current `version` of a parent entity that the operation depends on. In both cases the version field is a required input, not an optional hint.

Approving a claim is pinned to its parent enrollment. The approval request must carry `expected_enrollment_version` matching the target enrollment's current `version`. Approval debits the enrollment's annual claim allowance and increments `Enrollment.version`; if another writer has advanced the enrollment's version since the client last read it, the approval is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412) on the stale-version check, before the annual-limit check is re-evaluated, so a client cannot approve a second claim while still carrying an out-of-date enrollment view.

Shipping an advanced exchange is pinned to its parent claim. The ship request must carry `expected_claim_version` matching the target claim's current `version`. If the claim's version has advanced since the client last observed it — for example because the claim was re-routed and mutated — the dispatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), so a superseding ship built on an out-of-date claim view cannot proceed.

Paying a premium invoice also requires `expected_enrollment_version`, because settling an invoice advances the enrollment's paid-through marker and bumps `Enrollment.version`; this is detailed in the billing workflow. No other endpoint accepts or requires a version field, and version fields are never optional where they are required.

### 2.6. Hierarchical Consistency and Cascades

Many operations mutate more than one entity at once, and every such cascade settles immediately and in full. When a claim is approved, the customer's `lifetime_approved_claim_count` is incremented and both the enrollment and the claim are re-versioned in the same operation. When a claim is routed to replacement, the chosen replacement SKU's `stock_on_hand` is decremented as a unit is reserved. When a reserved exchange is cancelled, that same unit is returned to `stock_on_hand` as a compensating restore. When a fraud screen returns an adverse outcome, the customer's `risk_flag` is updated as a cascade. Each affected versioned resource has its `updated_at` refreshed and its `version` incremented by exactly 1 as part of the triggering operation; there is no deferred reconciliation.

### 2.7. Left-to-Right Resource Resolution

Whenever a request names resources — through path identifiers or through foreign-key fields in the body — the system validates their existence in left-to-right order. The first identifier that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any later identifier or business rule is evaluated. This ordering precedes all domain-specific checks except authentication and role authorization.

### 2.8. Monetary Precision and Rounding

All monetary amounts in the system are integer counts of cents. Wherever a calculation multiplies by a basis-point factor or a depreciation rate, the intermediate product is rounded to a whole number of cents using the round-half-up method at each such rounding step, as called out in the individual calculations. Counts (such as fraud velocity tallies and claim allowances) are plain integers. Device age in months is computed by flooring to a whole number of months, as described where it is used.

### 2.9. Fraud Posture and the Risk Flag

Each customer carries a `risk_flag` that gates their ability to have new claims approved. It takes one of three values — `GREEN`, `WATCH`, or `BLOCKED` — and defaults to `GREEN` when a customer is created. The flag is never set directly by a client; it moves only as a consequence of fraud screening and denials, as described in the claims workflow. A `WATCH` posture raises the deductible a customer is quoted; a `BLOCKED` posture prevents any further approvals.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Customers, Plans, and Replacement SKUs

The program rests on three reference roots, all created by a `PlatformAdmin`.

A **customer** is created with a `full_name` and a `carrier_account_number`; the carrier account number must be unique across customers, since it is the billing handle on the carrier's bill; a collision with an existing customer's carrier account number is rejected with `ERR_VALIDATION`. A new customer begins with `risk_flag` set to `GREEN` and `lifetime_approved_claim_count` set to 0, the running tally of how many of that customer's claims have ever reached `APPROVED` or any later status.

A **plan** prices coverage. It is created with a unique `code` (a collision with an existing plan's code is rejected with `ERR_VALIDATION`), a `monthly_premium_cents` add-on billed to the carrier bill each cycle (zero or more), a `base_deductible_cents` that serves as the tier-1 deductible for cracked-screen claims (zero or more), a `loss_deductible_multiplier_bps` expressed in basis points and applied to the base for lost and stolen claims (at least 10000, where 10000 represents a factor of one), an `annual_claim_limit` giving the maximum number of approved-or-beyond claims permitted per enrollment over any rolling twelve months (at least 1), and a `replacement_value_cap_cents` giving the most the plan will ever fund for a single replaced device (strictly greater than zero).

A **replacement SKU** is the refurbished-device catalogue entry used to fulfil replacement claims. It is created with a `model_name`, an `msrp_cents` manufacturer suggested retail price that is the basis for replacement value (strictly greater than zero), a `depreciation_rate_bps_per_month` giving straight-line monthly depreciation in basis points of MSRP (at least 0 and at most 10000, so for example 200 means two percent per month), and a `stock_on_hand` count of refurbished units available for advanced exchange (zero or more).

### 3.2. Enrollment Lifecycle

An enrollment binds a customer, a plan, a specific insured device, and the SKU that will replace it. It is created — by a `PlatformAdmin` or by a `Subscriber` — with `customer_id`, `plan_id`, `imei`, `device_model`, `device_purchase_date`, and `replacement_sku_id`. The `device_purchase_date` is the date the insured device was bought and drives later depreciation age, and `replacement_sku_id` names the SKU used to fulfil any replacement. At creation the `imei` must be exactly 15 digits and pass the Luhn checksum; a value that is not 15 digits or fails Luhn is rejected with `ERR_INVALID_IMEI`. The IMEI must also be unique across all enrollments that are not in `CANCELLED` status; a collision is rejected with `ERR_DUPLICATE_IMEI`.

A freshly created enrollment begins in `PENDING_ELIGIBILITY`. Its `status` ranges over `PENDING_ELIGIBILITY`, `ACTIVE`, `SUSPENDED`, and `CANCELLED`, with `CANCELLED` terminal. Two computed markers ride along: `premium_paid_through_cycle`, the highest billing-cycle index marked paid, which is -1 until any invoice is paid; and `open_claim_id`, the id of the single non-terminal claim currently on the enrollment, or null when there is none. The `enrolled_at` timestamp is null until activation.

Activation, performed by a `PlatformAdmin`, moves an enrollment from `PENDING_ELIGIBILITY` to `ACTIVE`. It is permitted only when the IMEI passed the Luhn and 15-digit format checks at creation, the referenced plan and replacement SKU still exist, and no other non-`CANCELLED` enrollment shares this IMEI (a violation here surfaces as `ERR_DUPLICATE_IMEI`). On success the status becomes `ACTIVE`, `enrolled_at` is set to the current logical clock, and the enrollment's `version` increments by one. Activation begins premium-billing eligibility.

A `PlatformAdmin` may suspend an `ACTIVE` enrollment, moving it to `SUSPENDED` — the lever used, for instance, when the carrier bill goes unpaid. Suspension is permitted only when `open_claim_id` is null, that is, when there is no non-terminal claim outstanding; the status becomes `SUSPENDED` and `version` increments by one. While `SUSPENDED`, the enrollment blocks new claims.

Reinstatement is the revert loop: a `PlatformAdmin` activates a `SUSPENDED` enrollment back to `ACTIVE`. This is permitted only when `premium_paid_through_cycle` covers the current cycle — that is, reinstatement has been paid. The current cycle is the zero-based billing-cycle index of the logical clock since activation, computed as the number of whole 30-day periods elapsed from the enrollment's `enrolled_at` to the current logical clock, floored to a whole number and never below 0 (and treated as 0 if `enrolled_at` is null); `premium_paid_through_cycle` covers it when `premium_paid_through_cycle` is greater than or equal to that current-cycle index. A reinstatement attempted when this precondition is not met is rejected with `ERR_INVALID_STATE`. On success the status returns to `ACTIVE` and `version` increments by one.

Cancellation, available to a `Subscriber` or `PlatformAdmin`, may be applied to an enrollment that is `ACTIVE` or `SUSPENDED`, and is permitted only when `open_claim_id` is null. Cancellation sets the status to `CANCELLED`, and cascades by voiding every premium invoice for this enrollment that is currently in `ISSUED` status (their status becomes `VOID`); the enrollment's `version` increments by one. Any attempt to drive a state transition from a status where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.3. Premium Billing on the Carrier Bill

Premiums accrue cycle by cycle as invoices on the carrier bill. A `PlatformAdmin` issues a **premium invoice** against an enrollment by supplying `enrollment_id` and a `cycle_index` (a zero-based billing-cycle index since activation, zero or more). At issue, the invoice's `amount_cents` is snapshotted from the plan's `monthly_premium_cents` so later plan edits cannot rewrite history, and the invoice begins in `ISSUED` status. An invoice's `status` ranges over `ISSUED`, `PAID`, and `VOID`.

Paying an invoice is open to a `PlatformAdmin` or a `Subscriber`. Because settling an invoice advances the enrollment's paid-through marker, the pay request must carry `expected_enrollment_version` matching the enrollment's current `version`; a mismatch is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412). On success the invoice moves to `PAID`, the enrollment's `premium_paid_through_cycle` is recomputed to the highest cycle index now marked paid, and the enrollment's `version` increments by one. This paid-through marker is what the reinstatement precondition consults when a `SUSPENDED` enrollment seeks to return to `ACTIVE`.

### 3.4. Filing a Claim

A claim represents a single peril event. A `Subscriber` or `PlatformAdmin` submits a claim with `enrollment_id`, a `peril` of `CRACKED`, `LOST`, or `THEFT`, an `incident_at` instant, and — only for theft — a `police_report_number`. The `police_report_number` is required and must be non-empty when `peril` is `THEFT`, and is ignored for `CRACKED` and `LOST`; a missing theft report is rejected with `ERR_POLICE_REPORT_REQUIRED`. The `incident_at` must fall strictly after the enrollment's `enrolled_at` and at or before the current logical clock; an incident before activation or in the future is rejected with `ERR_INCIDENT_OUT_OF_WINDOW`.

A claim may be filed only against an enrollment that is in `ACTIVE` status; submitting against a non-`ACTIVE` enrollment is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The enrollment must also have no existing non-terminal claim — that is, `open_claim_id` must be null — or the submission is rejected with `ERR_OPEN_CLAIM_EXISTS`. These submission checks are evaluated in this order: the enrollment's `ACTIVE` status first, then the `incident_at` window, then the theft `police_report_number` requirement, and finally the open-claim check, so the first failing condition in that sequence determines the rejection. On success the claim is created in `SUBMITTED` status, and the enrollment's `open_claim_id` is set to point at it.

A claim's `status` ranges over `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `ROUTED_REPAIR`, `ROUTED_REPLACE`, `FULFILLED`, `DENIED`, and `WITHDRAWN`, with `FULFILLED`, `DENIED`, and `WITHDRAWN` terminal. Several figures are pinned on the claim as it advances: `routing`, which becomes `REPAIR` or `REPLACE` at routing time and is null before then; `deductible_cents`, quoted at adjudication; `replacement_value_cents` and `net_payout_cents`, computed at adjudication only for replacement routing; and `denial_reason`, set when a claim is denied. The valid denial reasons are `FRAUD`, `INELIGIBLE`, `LIMIT_EXCEEDED`, and `NO_COVERAGE`.

A `Subscriber` who owns the parent enrollment's customer may withdraw a claim while it is still in `SUBMITTED` status, moving it to `WITHDRAWN`; this clears the enrollment's `open_claim_id` and increments the claim's `version` by one. A subscriber who is not the owner is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 3.5. Fraud Screening

Screening is the first adjudication step. A `ClaimsAdjuster` screens a `SUBMITTED` claim, advancing it to `UNDER_REVIEW`. Screening is permitted only when the parent enrollment is `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`) and the claim is the one named by the enrollment's `open_claim_id`. The act of screening creates a **fraud screen** record carrying `claim_id`, a denormalized `customer_id` for the velocity scan, a computed `velocity_count`, and an `outcome` of `PASS`, `REVIEW`, or `BLOCK`.

The velocity count is an aggregation over the customer's claim history. Define the window to open ninety days before this claim's `incident_at` and to close at this claim's `incident_at`, both boundaries inclusive. The `velocity_count` is the number of the customer's claims whose status is anything other than `WITHDRAWN` and whose `incident_at` falls within that closed interval — at or after the window opening and at or before this claim's `incident_at`. The claim being screened counts itself, since it is `SUBMITTED` at screen time. The outcome follows from the count against two thresholds: if the count is at least 3 the outcome is `BLOCK`; otherwise if the count is at least 2 the outcome is `REVIEW`; otherwise the outcome is `PASS`.

The outcome cascades onto the customer's posture. If the outcome is `BLOCK`, the customer's `risk_flag` is set to `BLOCKED`. If the outcome is `REVIEW` and the customer's `risk_flag` is currently `GREEN`, it is raised to `WATCH`; a customer already at `WATCH` or `BLOCKED` is left as is by a `REVIEW`. On success the claim moves to `UNDER_REVIEW` and its `version` increments by one.

### 3.6. Adjudication: Approval and Denial

From `UNDER_REVIEW`, a `ClaimsAdjuster` either approves or denies the claim.

Approval moves the claim to `APPROVED`. It carries `expected_enrollment_version` and is permitted only when all of the following hold: the claim's fraud screen outcome is not `BLOCK`, the customer's `risk_flag` is not `BLOCKED` (either of these conditions failing is rejected with `ERR_FRAUD_BLOCKED`), the enrollment's count of approved-or-beyond claims in the trailing twelve months is strictly below the plan's `annual_claim_limit` (this count tallies the enrollment's claims whose status is `APPROVED`, `ROUTED_REPAIR`, `ROUTED_REPLACE`, or `FULFILLED` and whose `incident_at` falls at or after the logical clock minus 365 days) (a breach is rejected with `ERR_CLAIM_LIMIT_EXCEEDED`), and `expected_enrollment_version` matches the enrollment's current `version` (a mismatch is rejected with `ERR_STALE_ENROLLMENT_VERSION`). These checks are evaluated in order — the fraud/risk gate first, then the annual-limit gate, then the stale-version gate — so that the stale-version rejection in particular shields the limit re-evaluation as described in the concurrency section. On approval the system computes `deductible_cents`, sets the status to `APPROVED`, increments the customer's `lifetime_approved_claim_count` by one, increments the enrollment's `version` by one, and increments the claim's `version` by one.

The **deductible** is quoted at approval in two steps, evaluated in this order. First the tier base is selected by peril: for a `CRACKED` claim the tier base equals the plan's `base_deductible_cents` with no multiplier applied; for a `LOST` or `THEFT` claim the tier base is the plan's `base_deductible_cents` multiplied by the plan's `loss_deductible_multiplier_bps` and divided by 10000, rounded half up to whole cents. Second, a risk surcharge keyed on the customer's `risk_flag` at approval time is added: if the flag is `WATCH`, the surcharge is the tier base multiplied by 2500 basis points and divided by 10000 — that is, twenty-five percent of the tier base — rounded half up to whole cents; for a `GREEN` customer the surcharge is zero (a `BLOCKED` customer never reaches approval). The final `deductible_cents` is the tier base plus the surcharge.

Denial moves the claim from `UNDER_REVIEW` to `DENIED`. A `denial_reason` must be supplied and must be one of the valid reasons; if it is absent or is not one of `FRAUD`, `INELIGIBLE`, `LIMIT_EXCEEDED`, or `NO_COVERAGE`, the request is rejected with `ERR_VALIDATION`. On denial the status becomes `DENIED` with the supplied `denial_reason` recorded, the enrollment's `open_claim_id` is cleared, and the claim's `version` increments by one. As a cascade, when the `denial_reason` is `FRAUD` the customer's `risk_flag` is set to `BLOCKED`.

### 3.7. Routing: Repair versus Replace

An `APPROVED` claim is routed by a `ClaimsAdjuster` to one of two divergent branches. The routing call accepts `repair_cost_cents`, a quoted repair cost that is required for cracked-device routing.

To decide between branches the system first establishes the device's depreciated replacement value (the same figure used to pay a replacement, computed as in the next subsection). For a `CRACKED` claim the route payload must supply `repair_cost_cents`; if it is missing (or not an integer) the request is rejected with `ERR_ROUTE_INPUT_MISSING`, and a supplied `repair_cost_cents` below zero is rejected with `ERR_VALIDATION`. The claim is routed to the **repair** branch — `ROUTED_REPAIR` — when the peril is `CRACKED` and the supplied `repair_cost_cents` is less than or equal to the depreciated replacement value computed for this claim, meaning repair is the economical choice. The claim is routed to the **replace** branch — `ROUTED_REPLACE` — when the peril is `LOST` or `THEFT`, or when the peril is `CRACKED` but the supplied `repair_cost_cents` is strictly greater than the depreciated replacement value computed for this claim.

When routing to repair, the system creates a **repair order** in `OPEN` status carrying the supplied `repair_cost_cents`, pins the claim's `routing` to `REPAIR`, sets the claim status to `ROUTED_REPAIR`, and increments the claim's `version` by one. A repair order's `status` ranges over `OPEN`, `COMPLETED`, and `CANCELLED`, and it carries its own `claim_id` and `repair_cost_cents` (the latter zero or more).

When routing to replace, the system requires that the enrollment's replacement SKU has `stock_on_hand` of at least 1; if no unit is available the request is rejected with `ERR_NO_STOCK`. On success it computes the claim's `replacement_value_cents` and `net_payout_cents`, creates an **advanced exchange** in `RESERVED` status whose `replacement_sku_id` is copied from the enrollment, decrements that SKU's `stock_on_hand` by one as the unit is reserved, pins the claim's `routing` to `REPLACE`, sets the claim status to `ROUTED_REPLACE`, and increments the claim's `version` by one.

### 3.8. Computing Replacement Value and Net Payout

The **replacement value** is a straight-line depreciation of the SKU's MSRP, floored and then capped, computed at routing time and also consulted by the repair-versus-replace decision above. First, the device's age in months is the number of days between the enrollment's `device_purchase_date` and the current logical clock, divided by 30 and floored to a whole number of months, and never below zero (a `device_purchase_date` after the clock yields an age of zero months). Next, the raw value is the SKU's `msrp_cents` minus the depreciation amount, where the depreciation amount is the SKU's `msrp_cents` multiplied by its `depreciation_rate_bps_per_month`, multiplied by the age in months, divided by 10000, and rounded half up to whole cents. The depreciated value is then the greater of that raw value and a minimum residual floor of 5000 cents. Finally, `replacement_value_cents` is the lesser of the depreciated value and the plan's `replacement_value_cap_cents`.

Two outcomes diverge from this single computation for the same device. When the depreciated value is strictly below the plan's `replacement_value_cap_cents`, the claim pays the depreciated book value on a chronological device-age basis. When the depreciated value is at least the plan's `replacement_value_cap_cents`, the claim pays the plan cap instead — a flat replacement basis that diverges from book value.

The `net_payout_cents` is the `replacement_value_cents` minus the claim's `deductible_cents`, floored at zero so it never goes negative.

### 3.9. Fulfilling the Repair Branch

A `LogisticsAgent` completes an `OPEN` repair order. Completion is permitted only when the repair order is in `OPEN` status. On success the repair order moves to `COMPLETED`, the parent claim bubbles up from `ROUTED_REPAIR` to `FULFILLED`, the enrollment's `open_claim_id` is cleared as a cascade, and the claim's `version` increments by one. This is the rejoin point for the repair branch.

### 3.10. Fulfilling the Replace Branch: Advanced Exchange

The replace branch runs through an advanced exchange, handled by a `LogisticsAgent`. An advanced exchange carries `claim_id`, the `replacement_sku_id` copied from the enrollment at dispatch, a computed `return_due_at` deadline for returning the old device (null until shipped), and a computed `nonreturn_fee_cents` (zero until assessed). Its `status` ranges over `RESERVED`, `SHIPPED`, `DELIVERED`, `RETURN_DUE`, `CLOSED`, and `CANCELLED`, with `CLOSED` and `CANCELLED` terminal.

Shipping moves a `RESERVED` exchange to `SHIPPED`, and is permitted only when the parent claim is in `ROUTED_REPLACE` status. As established in the concurrency section, the ship request carries `expected_claim_version` matching the parent claim's current `version`; a mismatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). On success the status becomes `SHIPPED`, `return_due_at` is set to the current logical clock plus the return window of 30 days, and the exchange's `version` increments by one.

Delivery moves a `SHIPPED` exchange to `DELIVERED`; it is permitted only from `SHIPPED` and increments the exchange's `version` by one.

A reserved exchange may be cancelled by a `LogisticsAgent` while it is still in `RESERVED` status, moving it to `CANCELLED`. Cancellation is the compensating action for the stock reservation taken at replace routing: it increments the replacement SKU's `stock_on_hand` by one to restore the reserved unit, and increments the exchange's `version` by one.

Closing moves a `DELIVERED` exchange to `CLOSED`, and is permitted only when a trade-in exists for this exchange in `CREDITED` or `RECYCLED` status. Closing the exchange also bubbles the parent claim from `ROUTED_REPLACE` to `FULFILLED`, clears the enrollment's `open_claim_id`, increments the exchange's `version` by one, and increments the claim's `version` by one. This is the rejoin point for the replace branch.

### 3.11. The Return Sweep and Non-Return Fee

The old device is expected back within the return window. A `PlatformAdmin` runs a return sweep, an admin-only test-driving capability that scans for `DELIVERED` exchanges whose return deadline has lapsed without a return. For each exchange where the current logical clock is strictly past `return_due_at` and no trade-in exists for that exchange, the sweep moves the exchange to `RETURN_DUE`, assesses the non-return fee, and increments the exchange's `version` by one; it returns a `200 OK` envelope whose `data` reports the swept exchange identifiers in a `swept_exchange_ids` array. The **non-return fee** is a flat fraction of the SKU MSRP: the SKU's `msrp_cents` multiplied by 3500 basis points and divided by 10000 — that is, thirty-five percent of MSRP — rounded half up to whole cents, recorded as `nonreturn_fee_cents`.

### 3.12. Trade-Ins, Credits, and E-Waste

When the old device comes back, a `LogisticsAgent` records a **trade-in** against an advanced exchange by supplying `advanced_exchange_id` and a `condition_grade` of `A`, `B`, `C`, or `EWASTE`. The trade-in carries a computed `credit_cents` (zero by default) and a `status` ranging over `RECEIVED`, `GRADED`, `CREDITED`, and `RECYCLED`, with `CREDITED` and `RECYCLED` terminal; it begins in `RECEIVED`.

Grading moves a `RECEIVED` trade-in to `GRADED`, and is permitted only when the parent advanced exchange is in `SHIPPED`, `DELIVERED`, or `RETURN_DUE` status. Grading computes the trade-in **credit**. The basis for the credit is the same depreciated value used by replacement value but taken before the plan cap is applied — the greater of the raw depreciated figure and the 5000-cent minimum residual floor — recomputed at the grade-time clock. The credit is that basis multiplied by a grade factor and divided by 10000, rounded half up to whole cents, where the grade factor in basis points is 6000 for grade `A`, 4000 for grade `B`, 2000 for grade `C`, and 0 for `EWASTE`. On success the status becomes `GRADED` and the trade-in's `version` increments by one.

A `GRADED` trade-in then either earns credit or is recycled, and the two paths are mutually exclusive by grade. Crediting moves the trade-in to `CREDITED` and is permitted only when the `condition_grade` is not `EWASTE`; attempting to credit an `EWASTE` trade-in is rejected with `ERR_GRADE_PATH_MISMATCH`. As a compensating cascade, if the parent advanced exchange is in `RETURN_DUE` status when the credit is applied, the exchange's `nonreturn_fee_cents` is reset to zero and the exchange returns to `DELIVERED` status — a late return reverses the non-return fee. The trade-in's `version` increments by one. Recycling moves the trade-in to `RECYCLED` and is permitted only when the `condition_grade` is `EWASTE`; attempting to recycle a non-`EWASTE` trade-in is rejected with `ERR_GRADE_PATH_MISMATCH`. The e-waste path earns no credit; the device is recycled and the trade-in's `version` increments by one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions, payments, sweeps, and the clock control — return a `200 OK` status code. Each operation enforces the role authorization, ownership, existence, state, and business rules described in the narratives above; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | PlatformAdmin |
| GET | `/customers/{id}` | Get a customer | PlatformAdmin, Subscriber, ClaimsAdjuster |
| POST | `/plans` | Create a plan | PlatformAdmin |
| GET | `/plans/{id}` | Get a plan | PlatformAdmin, Subscriber, ClaimsAdjuster |
| POST | `/replacement-skus` | Create a replacement SKU | PlatformAdmin |
| GET | `/replacement-skus/{id}` | Get a replacement SKU | PlatformAdmin, ClaimsAdjuster, LogisticsAgent |
| POST | `/enrollments` | Create an enrollment | PlatformAdmin, Subscriber |
| GET | `/enrollments/{id}` | Get an enrollment | PlatformAdmin, Subscriber, ClaimsAdjuster |
| GET | `/enrollments` | List/filter enrollments | PlatformAdmin, Subscriber, ClaimsAdjuster |
| POST | `/enrollments/{id}/activate` | Activate an enrollment | PlatformAdmin |
| POST | `/enrollments/{id}/suspend` | Suspend an enrollment | PlatformAdmin |
| POST | `/enrollments/{id}/cancel` | Cancel an enrollment | Subscriber, PlatformAdmin |
| POST | `/premium-invoices` | Issue a premium invoice | PlatformAdmin |
| GET | `/premium-invoices` | List/filter premium invoices | PlatformAdmin, Subscriber |
| GET | `/premium-invoices/{id}` | Get a premium invoice | PlatformAdmin, Subscriber |
| POST | `/premium-invoices/{id}/pay` | Pay a premium invoice | PlatformAdmin, Subscriber |
| POST | `/claims` | Submit a claim | Subscriber, PlatformAdmin |
| GET | `/claims/{id}` | Get a claim | PlatformAdmin, Subscriber, ClaimsAdjuster, LogisticsAgent |
| GET | `/claims` | List/filter claims | PlatformAdmin, Subscriber, ClaimsAdjuster |
| POST | `/claims/{id}/screen` | Screen a claim; run fraud velocity | ClaimsAdjuster |
| POST | `/claims/{id}/approve` | Approve a claim; quote deductible | ClaimsAdjuster |
| POST | `/claims/{id}/route` | Route an approved claim to repair or replace | ClaimsAdjuster |
| POST | `/claims/{id}/deny` | Deny a claim | ClaimsAdjuster |
| POST | `/claims/{id}/withdraw` | Withdraw a claim | Subscriber |
| GET | `/fraud-screens` | List/filter fraud screens | PlatformAdmin, ClaimsAdjuster |
| GET | `/fraud-screens/{id}` | Get a fraud screen | PlatformAdmin, ClaimsAdjuster |
| GET | `/repair-orders` | List/filter repair orders | PlatformAdmin, ClaimsAdjuster, LogisticsAgent |
| GET | `/repair-orders/{id}` | Get a repair order | PlatformAdmin, ClaimsAdjuster, LogisticsAgent |
| POST | `/repair-orders/{id}/complete` | Complete a repair; fulfil the claim | LogisticsAgent |
| GET | `/advanced-exchanges` | List/filter advanced exchanges | PlatformAdmin, ClaimsAdjuster, LogisticsAgent |
| GET | `/advanced-exchanges/{id}` | Get an advanced exchange | PlatformAdmin, ClaimsAdjuster, LogisticsAgent |
| POST | `/advanced-exchanges/{id}/ship` | Ship an exchange; set return deadline | LogisticsAgent |
| POST | `/advanced-exchanges/{id}/deliver` | Mark an exchange delivered | LogisticsAgent |
| POST | `/advanced-exchanges/{id}/close` | Close an exchange; fulfil the claim | LogisticsAgent |
| POST | `/advanced-exchanges/{id}/cancel` | Cancel a reserved exchange; restore stock | LogisticsAgent |
| POST | `/trade-ins` | Record a returned device | LogisticsAgent |
| GET | `/trade-ins` | List/filter trade-ins | PlatformAdmin, LogisticsAgent |
| GET | `/trade-ins/{id}` | Get a trade-in | PlatformAdmin, LogisticsAgent |
| POST | `/trade-ins/{id}/grade` | Grade a trade-in; compute credit | LogisticsAgent |
| POST | `/trade-ins/{id}/credit` | Apply credit; reverse non-return fee if due | LogisticsAgent |
| POST | `/trade-ins/{id}/recycle` | Recycle an e-waste trade-in | LogisticsAgent |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_clock/run_return_sweep` | Sweep lapsed exchanges to return-due and assess fees | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_INVALID_IMEI` | 422 |
| `ERR_DUPLICATE_IMEI` | 409 |
| `ERR_INCIDENT_OUT_OF_WINDOW` | 422 |
| `ERR_POLICE_REPORT_REQUIRED` | 422 |
| `ERR_OPEN_CLAIM_EXISTS` | 409 |
| `ERR_FRAUD_BLOCKED` | 409 |
| `ERR_CLAIM_LIMIT_EXCEEDED` | 409 |
| `ERR_NO_STOCK` | 409 |
| `ERR_STALE_ENROLLMENT_VERSION` | 412 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_ROUTE_INPUT_MISSING` | 422 |
| `ERR_GRADE_PATH_MISMATCH` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 422 |
