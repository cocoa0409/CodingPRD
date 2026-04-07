# PRD.md

# Product Requirements Document: Gig Marketplace Fulfillment API

## 1. Introduction & Vision

### 1.1 Overview

The Gig Marketplace Fulfillment API provides the core infrastructure for managing the lifecycle of orders, worker assignments, payouts, and quality control across a multi-tenant gig economy platform. This system is designed to support diverse service categories, ranging from delivery and rideshare to specialized home services.

The primary objectives are to ensure efficient order fulfillment, maintain high worker quality through robust risk assessment, and guarantee the financial integrity of tenant payout budgets and worker earnings. The system must handle high concurrency and provide deterministic outcomes for all operations.

### 1.2 Scope

This document outlines the requirements for the Fulfillment API, covering tenant management, listing creation, order processing, worker dispatch, risk modeling, financial settlement, and dispute resolution.

## 2. Foundational Principles

The Fulfillment API adheres to several core principles that govern its behavior across all operations.

### 2.1. Deterministic Operations & Time

The platform operates on a deterministic clock, independent of wall-clock time.

#### 2.1.1 The Period Clock

Each `MarketplaceTenant` maintains its own `current_period_index`, initialized at 0. All temporal logic (SLAs, dispute windows, certification expiry) is measured in these discrete periods. The clock can be advanced manually by Tenant Managers or Platform Admins for operational synchronization by specifying `by_periods`, requiring a positive increment (minimum 1) and capped at a maximum of 365 periods in a single operation to prevent accidental large jumps.

#### 2.1.2 Deterministic Sequencing

To ensure deterministic outcomes, especially under concurrent load, every resource created within a tenant is assigned a tenant-scoped, monotonically increasing sequence number (`created_seq`). This sequence number is global across all resource types within the tenant, establishing a definitive First-In, First-Out (FIFO) order.

In cases of contention or conflict resolution (e.g., competing for limited budget or capacity), the operation associated with the lower `created_seq` prevails. All list endpoints return resources ordered by `created_seq` ascending.

### 2.2. Financial Integrity & Conservation

Financial integrity is paramount. The system guarantees that all monetary movements are conserved and traceable.

#### 2.2.1 Tenant Payout Budget

Each tenant operates within a defined `payout_credit_limit_cents`. The platform advances funds for worker payouts up to this limit. The system must enforce the fundamental conservation law of the payout budget: the sum of consumed payouts (`payout_consumed_cents`), reserved funds for active assignments (`payout_reserved_cents`), and the remaining available capacity (`payout_available_cents`) must always equal the tenant's total payout capacity (credit limit plus any recovered funds, such as from clawbacks). At no point can the `payout_available_cents` become negative.

#### 2.2.2 Worker Debt

Incentives or loans provided to workers must be tracked and recouped systematically. The system maintains the integrity of worker debt such that `debt_repaid_cents` plus `debt_remaining_cents` always equals the worker's total debt obligation (`signup_bonus_debt_cents`). This total obligation may increase if penalties are assessed against the worker, such as clawbacks from dispute resolutions. Once the debt obligation is fully satisfied (`debt_satisfied`), subsequent payouts distribute entirely to the worker. 

#### 2.2.3 Assignment Entitlements

Worker earnings are strictly bounded by the order's value. The total cleared payouts for any assignment cannot exceed that assignment's calculated share of the order's earnings cap.

### 2.3. Quality Assurance & Risk Management

The platform employs a proactive approach to quality and risk. A hybrid risk model evaluates worker performance based on both long-term trends (chronic risk) and immediate incidents (acute risk). This `risk_score` (0-100) dynamically influences worker eligibility and triggers automated interventions to protect the marketplace.

Furthermore, tenant health is monitored by aggregating the risk profiles of their workforce. The `aggregate_risk_score` provides a holistic view of the tenant's operational quality.

### 2.4. System Consistency & Isolation

#### 2.4.1 Tenant Isolation

Strict isolation between tenants is enforced at the data layer. All resources belong to a specific `tenant_id`. Access controls must prevent cross-tenant data leakage. If a resource identifier is valid but belongs to a different tenant than the one specified in the request path, the system must respond as if the resource does not exist (404 Not Found) to prevent enumeration attacks.

#### 2.4.2 Data Precision

All financial calculations involving floating-point numbers (e.g., multipliers, ratios, averages) utilize IEEE-754 double precision. When converting these values to integer cents or scores, the system must always apply floor truncation; rounding to the nearest integer is not permitted.

#### 2.4.3 Immutable Data Protection

The system protects the integrity of derived and immutable data. Fields representing calculated states (e.g., balances, risk scores, statuses) or immutable identifiers (e.g., `created_seq`) cannot be modified directly by API consumers. When a request body includes values for such fields, those values are silently ignored—the request proceeds and updates only the mutable fields, returning success.

## 3. Marketplace Operations

### 3.1. Tenant Lifecycle & Credit Management

Tenants are the primary organizational unit. Platform Administrators onboard new tenants, defining their `name` and initial `payout_credit_limit_cents`.

Tenants begin in an `ACTIVE` state. They may be `SUSPENDED` manually by administrators or automatically due to excessive aggregate risk. A suspended tenant cannot create new orders, assignments, or request new payouts, although existing operations may complete. The terminal state is `CLOSED`.

Administrators may adjust the `payout_credit_limit_cents`. However, reductions must respect the financial conservation principles; the limit cannot be reduced below the current consumed and reserved amounts (net of recoveries).

### 3.2. Budget Monitoring & Exhaustion

The system continuously monitors the tenant's budget utilization.

#### 3.2.1 Critical State

The `is_payout_critical` flag activates when the available payout capacity drops below a small buffer of the total limit—specifically, 5%—signaling imminent exhaustion and potentially triggering specialized payout processing.

#### 3.2.2 Exhaustion

If `payout_available_cents` reaches zero, the budget is exhausted (`is_payout_exhausted`). In this state, any operation that would require new budget reservations (new assignments) or new budget draws (new payouts) is blocked.

#### 3.2.3 Payout Proration Trigger

To ensure fairness when budget is scarce, the system implements proration for pending payouts. Proration is triggered only if the tenant is in a critical state AND their consumed budget has reached 90% or more of their credit limit.

### 3.3. Listings, Categories, and Priority

Tenants create `Listings` to define the services offered. Listings include a `title`, `category` (e.g., DELIVERY, HOME_SERVICE, RIDESHARE, TASK), `base_price_cents`, `surge_multiplier` (minimum 1.0), and `customer_sla_periods`.

#### 3.3.1 Listing Lifecycle

Listings follow a lifecycle: `DRAFT` → `PUBLISHED` ↔ `PAUSED` → `ARCHIVED`. A paused listing can be resumed back to published. Orders can only be created for `PUBLISHED` listings. Archived listings are immutable.

#### 3.3.2 Marketplace Priority

To ensure critical services are prioritized during resource contention, listings are assigned a `priority_tier`. This tier is derived from the service category and the listing's creation sequence. The hierarchy is as follows (highest priority first):

1.  HOME_SERVICE
2.  RIDESHARE
3.  DELIVERY
4.  TASK

Within the same category, earlier listings receive higher priority. The implementation must ensure that the derived `priority_tier` numerically reflects this hierarchy, with lower numbers indicating higher priority. This priority tier influences payout processing under budget contention.

### 3.4. Order Fulfillment Lifecycle

Orders represent customer demand. When created, an `Order` captures the `listing_id` and `external_customer_id`. The system records the `created_period_index` (the tenant's clock at creation time), calculates the `quoted_price_cents` (base price × surge multiplier), and derives `expected_completion_period_index` (`created_period_index` + customer SLA periods). The `worker_earnings_cap_cents` defines the portion of the price available for worker payouts. Each order tracks its `active_assignment_count` (assignments in ACCEPTED or IN_PROGRESS states).

The standard fulfillment flow is:
`CREATED` → `PENDING_MATCHING` → `ASSIGNED` → `IN_PROGRESS` → `COMPLETED`.

Orders may also be `CANCELLED_BY_CUSTOMER` or `CANCELLED_BY_WORKER`. Dispatchers or Tenant Managers can cancel an order by specifying `cancelled_by` (`CUSTOMER` or `SYSTEM`) and an optional `reason`. Completed orders may enter a `DISPUTED` state, potentially leading to `REFUNDED`. The final state is `CLOSED`.

Closing an order is permitted only when the order is in a terminal operational state (Completed, Cancelled, Refunded, etc.), all associated assignments and payouts are finalized, and there are no open disputes.

### 3.5. SLA Management and Lateness

The system tracks order completion against the `expected_completion_period_index`. An order is considered `is_late` if the `completion_period_index` exceeds the expected index by more than 1 period. Lateness constitutes an SLA breach (`is_sla_breached`).

## 4. Workforce Management & Quality Assurance

### 4.1. Worker Onboarding and Status

Tenant Managers onboard `Workers`, specifying their `name`, `skills`, and `certifications`. Workers begin as `ACTIVE`.

Workers may enter `RISK_HOLD` or be `SUSPENDED` due to performance issues, or ultimately be `DEACTIVATED`. Only ACTIVE workers can accept new assignments.

### 4.2. Capacity Management

To prevent overcommitment, each worker has a `max_active_assignments` limit (defaulting to 10). The `active_assignment_count` tracks assignments currently in `ACCEPTED` or `IN_PROGRESS` states.

A worker `is_at_capacity` when their active count reaches the limit. Attempting to accept an assignment while at capacity is prohibited. When an assignment is completed or cancelled, the utilized capacity is released. Tenant Managers may adjust the capacity limit, but it cannot be reduced below the current active assignment count.

### 4.3. Skills and Certifications

Skill and certification requirements are validated when an assignment is created (offered). Assignments cannot be created for workers who do not meet the applicable requirements.

#### 4.3.1. High-Value Skill Requirement

For orders with a high quoted price (50,000 cents or more), the assigned worker must possess a skill matching the listing's category.

#### 4.3.2. Certification Validity

HOME_SERVICE listings mandate a valid `HOME_SERVICE_VERIFIED` certification. Certifications are valid from their `certified_period_index` up to (but not including) their `expiry_period_index`.

### 4.4. Incentives and Debt Recovery

Tenants may offer upfront incentives, recorded as `signup_bonus_debt_cents` (up to a maximum of 100,000 cents). This debt is systematically recouped from the worker's future earnings.

When a payout is processed for a worker with outstanding debt (`debt_remaining_cents` > 0), the approved payout amount is first applied towards the debt.

The payout record details this split:

  * `debt_repayment_portion_cents`: The amount applied to the debt.
  * `cash_portion_cents`: The remaining amount distributed to the worker.

Debt repayment is applied strictly in the order of payout creation (FIFO by `created_seq`). If a payout that contributed to debt repayment is later cancelled or fails, the repayment is reversed, and the debt obligation is restored.

### 4.5. Performance Monitoring & Risk Assessment

The platform employs a hybrid risk model to continuously assess worker quality. The `risk_score` (0-100) combines chronic performance metrics with acute penalties.

#### 4.5.1. Chronic Risk (Weighted Performance)

Chronic risk is a weighted average of three key performance indicators, reflecting long-term behavior. The system tracks each worker's `lifetime_orders_completed`, `late_order_count`, and `cancellation_count` to compute these rates:

1.  **Late Completion Rate:** The proportion of completed assignments that were delivered late (weighted at 40%).
2.  **Cancellation Rate:** The proportion of assignment attempts (completed or cancelled) that ended in worker-initiated cancellation (weighted at 30%).
3.  **Low Rating Rate:** The average deficit from a perfect 5-star rating, normalized to a 0-1 scale by dividing by the maximum possible deficit (weighted at 30%).

#### 4.5.2. Stabilization

To prevent volatility for new workers, the chronic risk score is stabilized. If a worker has fewer than 5 data points (completed or cancelled assignments), their raw chronic risk score is blended with the default starting score (0). The influence of the calculated score increases linearly as the worker completes more assignments, reaching full influence at 5 data points.

#### 4.5.3. Acute Risk (Additive Penalties)

Acute penalties are applied immediately for severe infractions. Each time a worker loses a dispute, an immediate penalty of 25 points is added on top of the stabilized chronic risk score.

The final `risk_score` is the sum of the stabilized chronic risk and acute penalties, capped at 100.

### 4.6. Risk Governance & Automated Actions

The system enforces quality standards through automated actions based on the `risk_score`. When a risk-affecting event occurs (such as dispute resolution), all threshold evaluations are performed atomically against the worker's updated risk score before any state transitions take effect. This ensures that both worker-level and tenant-level thresholds are evaluated consistently.

#### 4.6.1. Risk Hold

If a worker's `risk_score` reaches 70, they are automatically placed in `RISK_HOLD`. This immediately blocks new assignments from being created or accepted for that worker and prevents new payout requests; any existing REQUESTED payouts transition to HELD. Tenant Managers can manually clear a risk hold, restoring the worker to ACTIVE status and releasing held payouts back to their previous state.

#### 4.6.2. Auto-Deactivation

If the `risk_score` reaches 90, the worker is automatically `DEACTIVATED`. Deactivated workers cannot perform any further work on the platform. All pending payout requests are cancelled, and the worker is ineligible for future payouts.

#### 4.6.3. Tenant Aggregate Risk

The platform calculates an `aggregate_risk_score` for each tenant. This is the weighted average of the risk scores of all their non-deactivated workers, weighted by each worker's `lifetime_orders_completed` (with a minimum weight of 1). If a tenant's aggregate risk score reaches the critical threshold of 90, the tenant is automatically `SUSPENDED`.

## 5. Fulfillment & Assignment

### 5.1. Assignment Dispatch and Acceptance

Dispatchers create `Assignments` to match workers to orders in `PENDING_MATCHING` state. An assignment is initially `OFFERED`.

#### 5.1.1 Reservation Requirement

Creating an assignment requires specifying `reserved_earnings_initial_cents`. This action reserves the specified amount from the tenant's payout budget. The reservation must be adequately sized. If the tenant's budget cannot accommodate the reservation, the assignment creation fails.

#### 5.1.2 Acceptance and Activation

Workers accept offers via the WorkerApp, moving the assignment to `ACCEPTED` and the order to `ASSIGNED`. Acceptance is subject to several constraints:

  * The worker must be ACTIVE.
  * The worker must not be at capacity.
  * An order can have at most one active (ACCEPTED or IN_PROGRESS) assignment at any time. If two workers attempt to accept offers for the same order concurrently, the assignment created earlier wins.

### 5.2. Earnings Reservation and Adequacy

The system ensures that funds reserved for assignments are sufficient to cover expected worker earnings.

#### 5.2.1 Reservation Sizing and Adequacy

The `expected_earnings_cents` for an assignment is derived from the order's earnings cap and the assignment's share. The initial reservation must be at least 110% (a factor of 1.1) of the expected earnings. The assignment tracks `reserved_earnings_current_cents` (the current reservation after any releases), `released_earnings_cents` (cumulative amount released back to budget), and `payout_cleared_cents` (cumulative cleared payouts).

The `earnings_adequacy_ratio` monitors the health of the reservation relative to the 110% minimum requirement.

  * If the ratio falls to 0.8 or below, the assignment `requires_adjustment`.
  * If the ratio exceeds 1.5, the assignment `is_surplus_release_eligible`.

For assignments with zero expected earnings (e.g., from zero-price listings), adequacy checks are not applicable—such assignments are considered permanently healthy with both flags false.

#### 5.2.2 Surplus Release

Tenant Managers can manually release surplus funds from eligible assignments by specifying `release_amount_cents`. The `suggested_release_amount_cents` indicates the maximum amount that can be released while maintaining the 110% minimum reservation. Releasing surplus returns funds to the tenant's available budget.

### 5.3. Multi-Worker Earnings Distribution

Orders may be fulfilled by multiple workers sharing the earnings cap.

If shares are used, all assignments on the order must have an explicit `share_percentage` (1-100), and the total across all assignments cannot exceed 100%. Mixing explicit shares and automatic splitting on the same order is prohibited.

If no shares are defined (implicit split), the `share_percentage` field is returned as `null` in API responses, and the system assumes an equal split among the assignments. The distribution must be deterministic: the 100% is divided as evenly as possible using integer percentages, with any remainder allocated to the assignments created earliest (by `created_seq`).

### 5.4. Assignment Execution and Completion

When the worker begins the job, the assignment moves to `IN_PROGRESS`. Upon completion, the worker marks it `COMPLETED`, which also completes the order.

Workers may cancel assignments (`CANCELLED_BY_WORKER`), impacting their risk score. Assignments may also be cancelled by the system (`CANCELLED_BY_SYSTEM`), for instance, if the parent order is cancelled.

## 6. Payouts & Earnings

The payout system manages the disbursement of earnings to workers, respecting entitlements, budget constraints, and debt obligations.

### 6.1. Payout Lifecycle

Finance Officers initiate `Payouts` for `COMPLETED` assignments. Payout requests must specify the `assignment_id`, `requested_amount_cents`, and `payout_type` (NORMAL, INSTANT, ADJUSTMENT, FINAL). All payout requests must be for a minimum of 100 cents.

The standard flow is: `REQUESTED` → `APPROVED` → `SENT` → `CLEARED`. Payouts may also be `CANCELLED`, `FAILED`, or placed on `HELD`. Terminal states (`CLEARED`, `FAILED`, `CANCELLED`) cannot be reversed; once a payout reaches a terminal state, no further transitions are permitted.

### 6.2. Entitlement Check

A payout request cannot exceed the assignment's `remaining_entitlement_cents` (the expected earnings minus previously cleared payouts). If the `payout_type` is FINAL, the requested amount must exactly match the remaining entitlement.

### 6.3. Payout Calculation & Processing

The calculation of the final payout amount is a complex process that ensures fairness and compliance with all financial constraints simultaneously. The system must determine the `approved_amount_cents` and the final `net_payout_cents` by reconciling the following factors:

1.  **Entitlement Limits:** The approved amount cannot exceed the assignment's remaining entitlement.
2.  **Budget Availability:** The approved amount cannot exceed the tenant's available payout budget.
3.  **Proration:** If the tenant budget is critical and heavily utilized, the approved amount may be reduced proportionally.
4.  **Debt Recovery:** If the worker has outstanding debt, a portion of the approved amount is diverted to repayment, resulting in the `cash_portion_cents`.
5.  **Assignment Reservation Draw:** The `cash_portion_cents` defines the `budget_draw_amount_cents`, which must be covered by the assignment's available reservation. This reservation coverage is validated at the time a payout request is created—if the assignment's reservation (minus draws from pending payouts) cannot cover the anticipated cash portion, the request fails.
6.  **Fees:** Applicable fees (e.g., instant payout fees) are calculated based on the cash portion and deducted.

The final `net_payout_cents` is the result of this reconciliation process.

#### 6.3.1. Budget Draw and Finalization

The payout's `budget_draw_amount_cents` represents the draw against the assignment's reservation (the cash portion). When a payout reaches the `CLEARED` state, the provisional reservation is released, and the amount actually disbursed to the worker is reflected in the tenant's consumed budget.

### 6.4. Instant Payouts and Fees

Workers may opt for `INSTANT` payouts for expedited access to funds. Instant payouts incur a transaction fee of 3%, recorded as `instant_payout_fee_cents`. This fee is calculated based on the `cash_portion_cents` of the payout (the amount remaining after any debt repayment) and deducted before the final `net_payout_cents` is determined.

### 6.5. Payout Contention and Proration

When tenant budget availability is low, the system ensures fair allocation of the remaining funds.

#### 6.5.1. Prioritized Processing

If the tenant budget is critical, payouts associated with higher-priority listings are processed first. If priorities are equal, processing follows the payout's creation sequence. This ordering determines which payouts succeed when budget cannot accommodate all pending requests—higher-priority payouts consume available budget before lower-priority ones, and in race conditions where budget allows only some payouts, the higher-priority payout wins.

#### 6.5.2. Proration Mechanism

Proration is triggered when the tenant is in a critical state and their consumed budget has reached the high consumption threshold.

When triggered, the system calculates a `proration_factor` based on the available budget divided by the total unprorated amount of all pending payouts (REQUESTED, APPROVED, HELD). Each payout's unprorated amount is the minimum of its requested amount, its remaining entitlement, and the current budget availability. When this factor falls below 1.0, pending payouts have their `approved_amount_cents` reduced proportionally (multiplied by the factor and floored), record the applied factor, and are flagged as `is_prorated`. When sufficient budget exists (factor at or above 1.0), payouts proceed at their full requested amount without reduction, with `proration_factor` recorded as 1.0.

### 6.6. Idempotency

Payout creation is idempotent to prevent accidental duplicate payments. The `Idempotency-Key` header is required. The key's uniqueness is scoped to the combination of tenant, worker, assignment, and the endpoint path. Subsequent requests with the same key and identical parameters return the original payout; requests with different parameters result in a conflict.

## 7. Disputes & Resolutions

The platform provides a mechanism for handling disagreements regarding order fulfillment.

### 7.1. Dispute Eligibility & Filing

Disputes can be filed against orders in a disputable state (COMPLETED, FAILED, CANCELLED_BY_WORKER, REFUNDED, or DISPUTED).

Eligibility is time-bound. Disputes must be filed within 30 periods of the order's completion (or cancellation/failure) time, tracked by `order_completion_reference_period_index`. An order can have a maximum of 2 disputes filed against it; the order's `dispute_count` tracks how many have been filed. The `can_dispute` flag indicates eligibility based on these constraints.

When filing a dispute, the request must include `raised_by` (`CUSTOMER` or `WORKER`), a `reason` describing the issue, and optionally an `assignment_id` to link the dispute to a specific worker. Each dispute is assigned a `dispute_sequence` number (1 for first, 2 for second). The dispute record also captures the order's status at filing time in `original_order_status`.

Disputes follow a lifecycle: `FILED` → `UNDER_REVIEW` → resolution (`RESOLVED_CUSTOMER`, `RESOLVED_WORKER`) or withdrawal (`CANCELLED`). Unresolved disputes may also `EXPIRED`.

Filing a dispute moves the order to `DISPUTED` status.

### 7.2. Resolution & Impact

Customer Support reviews disputes (`UNDER_REVIEW`) and resolves them.

If resolved in favor of the worker (`RESOLVED_WORKER`), the dispute is closed, and if no other disputes are open, the order returns to its prior state (e.g., COMPLETED).

If resolved in favor of the customer (`RESOLVED_CUSTOMER`), the order moves to `REFUNDED`. This resolution also impacts the worker's risk score; if the dispute is linked to a specific assignment, the associated worker incurs an acute risk penalty.

### 7.3. Financial Adjustments (Refunds & Penalties)

A `RESOLVED_CUSTOMER` outcome requires specifying the `refund_amount_cents` (to the customer) and optionally a `worker_penalty_cents` (a clawback from the worker).

The platform credits the tenant's payout budget by the difference between the refund amount and the worker penalty (if positive). This increases the tenant's `recovered_clawbacks_cents`. The worker penalty is effectively added to the worker's outstanding debt, to be recovered from future payouts.

### 7.4. Ratings & Moderation

Customers may rate completed orders on a scale from 1 to 5. A rating is submitted with the `worker_id` being rated, the `rating_value` (1-5), and an optional `comment`. Ratings begin in a `PENDING_MODERATION` state before being reviewed. Moderators transition ratings by specifying an `action` of `PUBLISH`, `HIDE`, or `REMOVE`. Each order tracks its own `rating_count`, and the system also maintains a `rating_count` for each worker. When a rating is first published, it is recorded in the worker's performance ledger; subsequent moderation actions (hiding, removing, or re-publishing) do not alter the ledger entry. Published ratings influence the Low Rating Rate component of the chronic risk calculation.

## 8. API Contract

### 8.1. Authentication and Roles

All protected endpoints require the following headers:

  * `X-User-ID` (uuid)
  * `X-User-Role` (one of: PlatformAdmin, TenantManager, Dispatcher, WorkerApp, FinanceOfficer, CustomerSupport)

### 8.2. API Conventions

#### 8.2.1 Response Envelope

All API responses (success and error) adhere to a standard envelope structure:

```json
{
  "meta": {
    "api_request_id": "uuid",
    "api_request_period_index": 123
    // pagination fields if applicable
  },
  "response_type": "object" | "array" | "error",
  "data": {} // Resource(s) or error details
}
```

### 8.3. Endpoint Reference

| Method | Path | Description | Roles | Success Code |
| :--- | :--- | :--- | :--- | :--- |
| **Tenants** | | | | |
| POST | /tenants | Create Tenant | PlatformAdmin | 201 |
| GET | /tenants | List Tenants | PlatformAdmin | 200 |
| GET | /tenants/{tenantId} | Get Tenant | Any | 200 |
| PUT | /tenants/{tenantId} | Update Tenant (Credit Limit) | PlatformAdmin | 200 |
| POST | /tenants/{tenantId}/clock/advance | Advance Clock | TenantManager, PlatformAdmin | 200 |
| POST | /tenants/{tenantId}/suspend | Suspend Tenant | PlatformAdmin | 200 |
| POST | /tenants/{tenantId}/reinstate | Reinstate Tenant | PlatformAdmin | 200 |
| **Listings** | | | | |
| POST | /tenants/{tenantId}/listings | Create Listing | TenantManager | 201 |
| GET | /tenants/{tenantId}/listings | List Listings | Any | 200 |
| GET | /tenants/{tenantId}/listings/{listingId} | Get Listing | Any | 200 |
| PUT | /tenants/{tenantId}/listings/{listingId} | Update Listing | TenantManager | 200 |
| POST | /tenants/{tenantId}/listings/{listingId}/publish | Publish Listing | TenantManager | 200 |
| POST | /tenants/{tenantId}/listings/{listingId}/pause | Pause Listing | TenantManager | 200 |
| POST | /tenants/{tenantId}/listings/{listingId}/resume | Resume Listing | TenantManager | 200 |
| POST | /tenants/{tenantId}/listings/{listingId}/archive | Archive Listing | TenantManager | 200 |
| **Orders** | | | | |
| POST | /tenants/{tenantId}/orders | Create Order | Dispatcher, TenantManager | 201 |
| GET | /tenants/{tenantId}/orders | List Orders | Any | 200 |
| GET | /tenants/{tenantId}/orders/{orderId} | Get Order | Any | 200 |
| POST | /tenants/{tenantId}/orders/{orderId}/cancel | Cancel Order | Dispatcher, TenantManager | 200 |
| POST | /tenants/{tenantId}/orders/{orderId}/mark-completed | Mark Order Completed | WorkerApp | 200 |
| POST | /tenants/{tenantId}/orders/{orderId}/close | Close Order | TenantManager, CustomerSupport | 200 |
| **Workers** | | | | |
| POST | /tenants/{tenantId}/workers | Create Worker | TenantManager | 201 |
| GET | /tenants/{tenantId}/workers | List Workers | Any | 200 |
| GET | /tenants/{tenantId}/workers/{workerId} | Get Worker | Any | 200 |
| PUT | /tenants/{tenantId}/workers/{workerId} | Update Worker (Skills/Capacity) | TenantManager | 200 |
| POST | /tenants/{tenantId}/workers/{workerId}/suspend | Suspend Worker | TenantManager | 200 |
| POST | /tenants/{tenantId}/workers/{workerId}/risk-hold/clear | Clear Risk Hold | TenantManager | 200 |
| POST | /tenants/{tenantId}/workers/{workerId}/reinstate | Reinstate Worker | TenantManager | 200 |
| **Assignments** | | | | |
| POST | /tenants/{tenantId}/orders/{orderId}/assignments | Create Assignment (Offer) | Dispatcher, TenantManager | 201 |
| GET | /tenants/{tenantId}/orders/{orderId}/assignments | List Assignments | Any | 200 |
| POST | .../assignments/{assignmentId}/accept | Accept Assignment | WorkerApp | 200 |
| POST | .../assignments/{assignmentId}/start | Start Assignment | WorkerApp | 200 |
| POST | .../assignments/{assignmentId}/complete | Complete Assignment | WorkerApp | 200 |
| POST | .../assignments/{assignmentId}/cancel | Cancel Assignment (Worker) | WorkerApp | 200 |
| POST | .../assignments/{assignmentId}/release-surplus | Release Surplus Reservation | TenantManager | 200 |
| **Payouts** (Requires `Idempotency-Key` header for POST) | | | | |
| POST | /tenants/{tenantId}/workers/{workerId}/payouts | Request Payout | FinanceOfficer | 201 |
| GET | /tenants/{tenantId}/workers/{workerId}/payouts | List Payouts | FinanceOfficer, TenantManager | 200 |
| POST | .../payouts/{payoutId}/approve | Approve Payout | FinanceOfficer | 200 |
| POST | .../payouts/{payoutId}/send | Send Payout | FinanceOfficer | 200 |
| POST | .../payouts/{payoutId}/confirm-cleared | Confirm Payout Cleared | FinanceOfficer | 200 |
| POST | .../payouts/{payoutId}/fail | Mark Payout Failed | FinanceOfficer | 200 |
| POST | .../payouts/{payoutId}/cancel | Cancel Payout | FinanceOfficer | 200 |
| **Disputes** | | | | |
| POST | /tenants/{tenantId}/orders/{orderId}/disputes | File Dispute | CustomerSupport, TenantManager | 201 |
| GET | /tenants/{tenantId}/orders/{orderId}/disputes | List Disputes | Any | 200 |
| POST | .../disputes/{disputeId}/start-review | Start Review | CustomerSupport | 200 |
| POST | .../disputes/{disputeId}/resolve-customer | Resolve (Customer Favour) | CustomerSupport | 200 |
| POST | .../disputes/{disputeId}/resolve-worker | Resolve (Worker Favour) | CustomerSupport | 200 |
| POST | .../disputes/{disputeId}/withdraw | Withdraw Dispute | CustomerSupport | 200 |
| **Ratings** | | | | |
| POST | /tenants/{tenantId}/orders/{orderId}/ratings | Create Rating | Dispatcher, CustomerSupport | 201 |
| GET | /tenants/{tenantId}/orders/{orderId}/ratings | List Ratings | Any | 200 |
| POST | .../ratings/{ratingId}/moderate | Moderate Rating | TenantManager | 200 |

### 8.4. Error Catalog

| Error Code | HTTP Status | Description |
|------------|-------------|-------------|
| ERR_INVALID_REQUEST | 400 | Malformed request body or parameters |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 | Required authentication headers missing |
| ERR_IMMUTABLE_FIELD_MODIFIED | 400 | Attempt to modify read-only field |
| ERR_RESERVATION_BELOW_MINIMUM | 400 | Reservation does not meet required factor |
| ERR_INVALID_SHARE_PERCENTAGES | 400 | Invalid or inconsistent share allocation |
| ERR_RELEASE_EXCEEDS_CURRENT | 400 | Surplus release exceeds available amount |
| ERR_PAYOUT_BELOW_MINIMUM | 400 | Payout request below minimum threshold |
| ERR_TENANT_SUSPENDED | 403 | Tenant is suspended |
| ERR_WORKER_RISK_HOLD_OR_SUSPENDED | 403 | Worker cannot perform operation due to status |
| ERR_WORKER_NOT_ASSIGNED | 403 | Worker not assigned to order |
| ERR_NOT_ASSIGNED_WORKER | 403 | Action requires assignment ownership |
| ERR_TENANT_NOT_FOUND | 404 | Tenant does not exist (or isolation) |
| ERR_LISTING_NOT_FOUND | 404 | Listing does not exist |
| ERR_ORDER_NOT_FOUND | 404 | Order does not exist |
| ERR_WORKER_NOT_FOUND | 404 | Worker does not exist |
| ERR_ASSIGNMENT_NOT_FOUND | 404 | Assignment does not exist |
| ERR_CANNOT_REDUCE_BELOW_CONSUMED | 409 | Credit limit reduction would violate conservation |
| ERR_TENANT_NOT_ACTIVE | 409 | Operation requires active tenant |
| ERR_TENANT_NOT_SUSPENDED | 409 | Operation requires suspended tenant |
| ERR_LISTING_NOT_DRAFT | 409 | Publish requires draft status |
| ERR_LISTING_NOT_PUBLISHED | 409 | Operation requires listing to be published |
| ERR_LISTING_NOT_PAUSED | 409 | Resume requires paused status |
| ERR_LISTING_ALREADY_ARCHIVED | 409 | Listing already archived |
| ERR_LISTING_NOT_EDITABLE | 409 | Archived listing cannot be modified |
| ERR_ORDER_NOT_ASSIGNABLE | 409 | Order not in assignable state |
| ERR_ORDER_NOT_IN_PROGRESS | 409 | Order not in progress |
| ERR_ORDER_NOT_CANCELLABLE | 409 | Order cannot be cancelled |
| ERR_ORDER_NOT_CLOSEABLE | 409 | Order cannot be closed |
| ERR_OPEN_DISPUTE_EXISTS | 409 | Open dispute blocks operation |
| ERR_ORDER_NOT_DISPUTABLE | 409 | Order not eligible for dispute |
| ERR_DISPUTE_WINDOW_EXPIRED | 409 | Dispute window has passed |
| ERR_MAX_DISPUTES_EXCEEDED | 409 | Maximum disputes reached |
| ERR_DISPUTE_NOT_FILED | 409 | Dispute not in filed state |
| ERR_DISPUTE_NOT_UNDER_REVIEW | 409 | Dispute not under review |
| ERR_DISPUTE_NOT_WITHDRAWABLE | 409 | Dispute cannot be withdrawn |
| ERR_DUPLICATE_ACTIVE_ASSIGNMENT | 409 | Duplicate assignment for worker/order |
| ERR_ASSIGNMENT_NOT_OFFERED | 409 | Assignment not in offered state |
| ERR_ASSIGNMENT_NOT_ACCEPTED | 409 | Assignment not accepted |
| ERR_ASSIGNMENT_NOT_IN_PROGRESS | 409 | Assignment not in progress |
| ERR_ASSIGNMENT_NOT_CANCELLABLE | 409 | Assignment cannot be cancelled |
| ERR_ASSIGNMENT_NOT_COMPLETED | 409 | Assignment not completed |
| ERR_WORKER_AT_CAPACITY | 409 | Worker at maximum assignments |
| ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT | 409 | Order has active assignment |
| ERR_WORKER_LACKS_SKILL | 409 | Worker lacks required skill |
| ERR_WORKER_CERTIFICATION_EXPIRED | 409 | Worker certification invalid |
| ERR_WORKER_NOT_ACTIVE_OR_RISK_HOLD | 409 | Worker status does not allow operation |
| ERR_WORKER_NOT_UNDER_RISK_HOLD | 409 | Clear requires risk hold status |
| ERR_WORKER_NOT_SUSPENDED | 409 | Reinstate requires suspended status |
| ERR_CANNOT_REDUCE_BELOW_ACTIVE_ASSIGNMENTS | 409 | Cannot reduce capacity below active |
| ERR_PAYOUT_NOT_REQUESTED | 409 | Payout not in requested state |
| ERR_PAYOUT_NOT_APPROVED | 409 | Payout not approved |
| ERR_PAYOUT_NOT_SENT | 409 | Payout not sent |
| ERR_PAYOUT_ALREADY_TERMINAL | 409 | Payout already in terminal state |
| ERR_PAYOUT_NOT_CANCELLABLE | 409 | Payout cannot be cancelled |
| ERR_FINAL_AMOUNT_MISMATCH | 409 | Final payout amount incorrect |
| ERR_IDEMPOTENCY_CONFLICT | 409 | Idempotency key conflict |
| ERR_ORDER_NOT_COMPLETED | 409 | Rating requires completed order |
| ERR_RATING_NOT_MODERATABLE | 409 | Rating not in moderatable state |
| ERR_INSUFFICIENT_PAYOUT_BUDGET | 402 | Insufficient tenant payout capacity |
| ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION | 402 | Insufficient budget for reservation |
| ERR_PAYOUT_BUDGET_EXHAUSTED_SINCE_REQUEST | 402 | Budget exhausted after request |
| ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT | 402 | Payout exceeds assignment entitlement |
| ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION | 402 | Assignment reservation insufficient |

### 8.5. Error Precedence

When multiple error conditions apply simultaneously, return the first matching error according to this priority:

1. **400** - Request validation (malformed body, missing headers, immutable fields)
2. **401** - Authentication failures
3. **403** - Authorization/state restrictions (suspended tenant, worker hold)
4. **404** - Resource not found (tenant first, then child resources)
5. **409** - Business rule conflicts
6. **402** - Financial constraints

Within each status code category, prefer more specific errors over general ones. For state machine transitions, precondition errors indicating the resource is not in the required source state (e.g., `ERR_PAYOUT_NOT_SENT` for confirm-cleared, `ERR_PAYOUT_NOT_CANCELLABLE` for cancel) take precedence over general terminal state errors.
