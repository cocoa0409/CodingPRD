# Commercial Cleaning Janitorial API — Product Requirements Document

## 1. Introduction

This document specifies a back-office platform for a commercial janitorial sales organization that pursues cleaning contracts from first solicitation through long-term account retention. The business runs a long, multi-disciplinary pipeline: a sales representative captures a request-for-proposal opportunity from a prospect, schedules and runs an on-site walkthrough against a named site contact's availability, and hands the scoped opportunity to a bid estimator. The estimator decomposes the building into service areas, computes a square-footage-driven labor-loading estimate, and builds up a fully burdened monthly bid with a target margin. The sales representative then issues a priced proposal, which may loop through several revision rounds before a buyer accepts or declines it.

Once a proposal is accepted, the work shifts to operations: a contract is drafted and signed, a start-up plan is created, crews are scheduled into shifts until the planned labor hours are fully allocated, supplies and equipment are provisioned against a monthly budget, and the account goes live. Going live is the onboarding handoff — the prospect becomes an active customer owned by an account manager who thereafter manages billing, retention health, renewals, and floor/window upsells. The system must keep two parallel contract axes (operational lifecycle and billing state) consistent, enforce fiscal floors on margin and supply spending, and protect a small set of money-mutating operations with optimistic concurrency control so that a stale view of a budget or contract cannot silently overwrite a committed change.

The platform is the system of record for every stage. Because pricing, hour allocation, budget conservation, and retention-health cascades are all computed server-side, the requirements below pin down each formula, rounding order, threshold, and side effect precisely.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled precisely: `SalesRep`, `BidEstimator`, `OperationsManager`, `AccountManager`, and `PlatformAdmin`. A `SalesRep` owns prospect capture, RFP creation, site-contact creation, walkthrough scheduling and completion, proposal creation and lifecycle (send, revise, accept, decline), and contract creation and signing. A `BidEstimator` owns bid-estimate creation and pricing, and shares service-area creation with the `SalesRep`. An `OperationsManager` owns crew creation and retirement, start-up crewing, mark-ready, go-live and abort actions, crew-shift cancellation, supply-budget creation, and supply-requisition creation, approval, and cancellation. An `AccountManager` owns post-handoff account management: ending a contract, suspending and resuming billing, the full renewal cycle, and contract upsells. A `PlatformAdmin` is an operator who may read every collection and control the server's logical clock.

For ownership semantics, four of the five roles use an opaque identity model. When `X-User-Role` is `SalesRep`, `BidEstimator`, `OperationsManager`, or `PlatformAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `AccountManager`, the identity is entity-backed: `X-User-ID` is the `id` of the acting account owner, and ownership checks on any resource that references an `Account` compare the account's `owner_user_id` field to `X-User-ID`. The `owner_user_id` is set on the account at the onboarding handoff and is null beforehand; at the go-live handoff it is set to the `X-User-ID` of the acting (OperationsManager) user driving go-live, and only when it is still null — an already-set `owner_user_id` is left unchanged.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a `limit` outside the range 1 through 100 inclusive is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422). The `offset` parameter defaults to 0 with a minimum of 0; a non-integer `offset` or an `offset` below 0 is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a non-integer `limit` is likewise rejected with `ERR_VALIDATION_LIMIT` (HTTP 422). All list endpoints return their results sorted by `created_at` in ascending order. The pagination fields `limit`, `offset`, `total_count`, and `has_more` are echoed inside the `meta` object of every list response, where `total_count` is the number of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits, set when the resource is first created. Most resources additionally carry an `updated_at` timestamp (same format), refreshed on every mutation, and an integer `version` that begins at 1 and increments by one on each mutation. Two entities are the exception: `Crew` and `CrewShift` carry only `id` and `created_at` and no `updated_at` or `version`. Wherever this document refers to bumping an entity's `version` or refreshing its `updated_at`, it refers to the standard mutation bookkeeping on entities that carry those fields.

### 2.5. Nested Resource Addressing

Many resources are addressed through nested paths that name their ancestry — an account, then an RFP, then a deeper resource. Path resources are validated left to right: the account is checked first, then the RFP, then any further nested resource. The first segment in the chain that does not resolve produces `ERR_NOT_FOUND` (HTTP 404). The same `ERR_NOT_FOUND` applies when a foreign-key id supplied in a request body — such as `bid_estimate_id`, `proposal_id`, `crew_id`, `site_contact_id`, or `supply_budget_id` — does not reference an existing resource.

### 2.6. Monetary Precision and Hour Rounding

All monetary amounts are stored and computed as integer cents. Every money calculation rounds half up at each step pinned by the formulas in §3; intermediate results are not allowed to carry fractional cents past a pinned rounding point. Labor hours — both per-area weekly hours and the monthly and allocated aggregates — are carried to two decimal places using round-half-up. The order in which rounding is applied relative to summation is significant and is fixed per the loading method described in §3; the system must honor that order exactly because the round-then-sum and sum-then-round paths can diverge in the final cents.

### 2.7. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_UNAUTHORIZED`), then path-resource existence (`ERR_NOT_FOUND`), then existence of referenced foreign-key ids in the body (`ERR_NOT_FOUND`), then presence and typing of required input fields (`ERR_INVALID_REQUEST`), then enum-domain membership (`ERR_INVALID_ENUM`), then numeric and temporal range checks (`ERR_INVALID_RANGE`), then target-state correctness for the transition (`ERR_INVALID_STATE`), then cross-entity state preconditions, then the domain-specific temporal, safety, capacity, fiscal, and concurrency checks described below. In short: who-you-are before what-exists before what-you-sent before what-state-it-is-in before the business rules. Where a more specific rule is named for an operation in §3, it is evaluated after the generic checks above unless §3 states otherwise.

### 2.8. Parallel Contract Axes and Retention-Health Cascades

A `CleaningContract` evolves along two independent axes. Its `lifecycle_status` runs `DRAFT` → `SIGNED` → `STARTUP` → `SERVICING` → `ENDED` and tracks operational progress. Its `billing_status` runs `PENDING` → `ACTIVE` → `SUSPENDED` → `CLOSED` and tracks the money side. The two axes evolve independently: suspending or resuming billing never changes `lifecycle_status`, and most lifecycle transitions leave `billing_status` untouched. There are exactly two cross-axis couplings, both stated in §3: going live moves `billing_status` from `PENDING` to `ACTIVE`, and ending or lapsing a contract moves `billing_status` to `CLOSED`.

An `Account` carries a `health_score` integer that begins at 100 and is bounded to the range 0 through 100. Several operations debit or credit it: it is floored at 0 whenever a debit would drive it negative, and capped at 100 whenever a credit would drive it above 100. Each cascade's magnitude and direction is given in the workflow that triggers it. Every such health change, and every parallel-axis or cross-entity state change, refreshes the affected entity's `updated_at` and bumps its `version`.

### 2.9. Optimistic Concurrency Control

Two money-mutating operations are guarded by optimistic concurrency control against the current `version` of a parent entity. The client must supply the parent's last-observed version, and if the parent's version has advanced since then, the write is rejected rather than allowed to overwrite an unobserved change.

Approving a supply requisition is a write against the parent `SupplyBudget`. The approval request must carry `expected_supply_budget_version` matching the target budget's current `version`. If another approval or cancellation has already advanced the budget's version since the client last read it — for example, a concurrent approval that legitimately reduced `remaining_cents` — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the writer from committing funds against a stale view of the remaining balance.

Accepting a renewal cycle is a write against the parent `CleaningContract`. The accept request must carry `expected_contract_version` matching the contract's current `version`. If another renewal, billing action, or upsell has already advanced the contract's version since the client last read it, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; only these two operations carry an OCC check.

## 3. Business Logic & Workflows

### 3.1. Opening an Opportunity and Capturing the Site

The pipeline begins when a `SalesRep` creates a prospect. A new account is created from a `legal_name` and an `industry`, where `industry` must be one of `OFFICE`, `MEDICAL`, `INDUSTRIAL`, `RETAIL`, or `EDUCATION`. On creation the account's `lifecycle_stage` is `PROSPECT`, its `health_score` is 100, and its `owner_user_id` is null until the onboarding handoff. The account `lifecycle_stage` enumerates `PROSPECT`, `ACTIVE_CUSTOMER`, and `CHURNED`.

Before a walkthrough can be scheduled, the rep records the buyer's on-site contacts. A `SiteContact` is created under an account with a `full_name` and a bookable availability window expressed as `avail_start_at` and `avail_end_at`; both are ISO 8601 timestamps and `avail_end_at` must be strictly after `avail_start_at`, otherwise the create is rejected with `ERR_INVALID_RANGE`. The window is inclusive at both ends. Each site contact carries the `account_id` of the account it belongs to.

The rep opens an RFP opportunity under the account by supplying a `title`, a `due_at` proposal-submission deadline, and an `estimated_total_sqft` that must be greater than zero. A new `RfpOpportunity` records its `account_id` and starts in status `OPEN`. The opportunity `status` field enumerates `OPEN`, `WALKTHROUGH_SCHEDULED`, `BIDDING`, `PROPOSED`, `WON`, and `LOST`, with `WON` and `LOST` terminal. The same `status` field name carries the lifecycle state on the walkthrough, bid estimate, proposal, crew, crew shift, start-up plan, supply requisition, and renewal cycle resources described below.

### 3.2. Scheduling and Completing the Walkthrough

Scheduling a walkthrough advances the opportunity from `OPEN` to `WALKTHROUGH_SCHEDULED`. The `SalesRep` supplies a `site_contact_id`, a `start_at`, and an `end_at`; the resulting `Walkthrough` records its `rfp_id` and is created in status `SCHEDULED`. The walkthrough status enumerates `SCHEDULED`, `COMPLETED`, `NO_SHOW`, and `CANCELLED`. The `end_at` must be strictly after `start_at` (`ERR_INVALID_RANGE`).

Three preconditions gate scheduling, beyond the generic checks. First, the opportunity must currently be `OPEN`; if it is in any other status the request is rejected with `ERR_INVALID_STATE`. Second, the walkthrough's closed interval from `start_at` to `end_at` must lie entirely within the chosen site contact's inclusive availability window from `avail_start_at` to `avail_end_at`; a walkthrough that begins before the contact's availability starts or ends after it ends is rejected with `ERR_OUTSIDE_AVAILABILITY`. Third, the new walkthrough must not overlap any other `SCHEDULED` walkthrough on the same site contact, treating both intervals as closed (touching endpoints count as an overlap); a collision is rejected with `ERR_WALKTHROUGH_OVERLAP`. Additionally, if the supplied `site_contact_id` belongs to a different account than the one the RFP hangs under, the request is rejected with `ERR_SITE_CONTACT_MISMATCH`.

Completing the walkthrough is the bridge into pricing: it sets the walkthrough's status from `SCHEDULED` to `COMPLETED` and advances the opportunity from `WALKTHROUGH_SCHEDULED` to `BIDDING`; the opportunity advance is applied only when the opportunity is currently `WALKTHROUGH_SCHEDULED`, and a parent opportunity already in any other status is left untouched. The walkthrough being completed must currently be `SCHEDULED`, otherwise `ERR_INVALID_STATE` is returned.

### 3.3. Scoping Service Areas and Estimating Labor

With the opportunity in `BIDDING`, the building is decomposed into service areas. A `SalesRep` or a `BidEstimator` adds each `ServiceArea` under the RFP with a `label`, a `sqft` value greater than zero, a `soil_level`, and a `frequency_per_week` that is an integer from 1 through 7 inclusive. A `sqft` of zero or less, or a frequency outside 1 through 7, is rejected with `ERR_INVALID_RANGE`. The `soil_level` must be one of `LIGHT`, `MEDIUM`, or `HEAVY` (`ERR_INVALID_ENUM`); it selects both the production rate used for labor estimation and the supply rate used later in the bid build-up. Each service area records its parent `rfp_id`. Its `weekly_hours` is a read-only computed value: it equals the area's `sqft` divided by the production rate for that soil level, multiplied by the area's `frequency_per_week`, and rounded to two decimal places. This stored per-row `weekly_hours` is always rounded to two decimal places (round half up) at area creation, independent of any bid estimate's loading method; the loading-method round-then-sum versus sum-then-round divergence pinned in §3.4 applies only to the aggregate weekly and monthly totals computed during pricing, not to this per-row display field.

The production rate is a soil-driven throughput in square feet per hour: `LIGHT` cleans at 4000 square feet per hour, `MEDIUM` at 3000, and `HEAVY` at 2000. So a single area's raw weekly hours is its square footage divided by that throughput, then multiplied by the number of cleanings per week.

A `BidEstimator` creates a draft bid estimate under the RFP with a `base_wage_cents` cleaner hourly wage greater than zero, a `target_margin_pct` desired gross margin between 0.00 and 0.90 inclusive, and an optional `loading_method`. A `target_margin_pct` outside 0.00 through 0.90 is rejected with `ERR_INVALID_RANGE`. The `loading_method` must be either `ESTIMATE` or `LOADED` (`ERR_INVALID_ENUM`) and defaults to `ESTIMATE` when omitted; it picks the rounding order for the labor-loading variant. The new `BidEstimate` records its `rfp_id` and is created in status `DRAFT`; the status enumerates `DRAFT` and `PRICED`. Its computed read-only fields — `monthly_labor_hours`, `labor_cost_cents`, `supply_cost_cents`, `total_cost_cents`, and `base_bid_cents` — are populated when the estimate is priced.

### 3.4. Pricing the Bid: Loading, Burden, and Build-Up

Pricing a bid estimate is a `BidEstimator` action that moves it from `DRAFT` to `PRICED` and computes every monetary field. Re-running pricing on an already-`PRICED` estimate recomputes the figures and leaves the status `PRICED` (the recompute is idempotent in state). Pricing must be run against an RFP that has at least one service area; a price run with zero service areas on the RFP is rejected with `ERR_SERVICE_AREA_REQUIRED`. The input set for both the labor load and the build-up is every `ServiceArea` whose `rfp_id` matches the estimate's RFP, with no status filter since service areas have no lifecycle of their own.

**Labor loading.** First the per-area weekly hours are computed as described in §3.3 for every service area. The monthly labor hours then depend on the loading method, and the difference is the rounding order. Under the `ESTIMATE` method (round-then-sum), each area's weekly hours is rounded to two decimal places first, and those rounded per-area values are summed to give the weekly total. Under the `LOADED` method (sum-then-round), the raw unrounded per-area weekly hours are summed first and the single weekly total is then rounded once to two decimal places. In both methods the weekly total is multiplied by 4.33 weeks per month and the product is rounded half up to two decimal places to give `monthly_labor_hours`. The two methods can differ in the trailing cents of every downstream figure, so the method on the estimate must be honored exactly.

**Burden tier.** A labor-burden multiplier is selected from `monthly_labor_hours` against two breakpoints. If the monthly labor hours are at most 160, the burden is 1.20; otherwise if they are at most 320, the burden is 1.28; otherwise the burden is 1.35. The breakpoints are inclusive on the lower tier — exactly 160 hours takes the 1.20 burden and exactly 320 takes the 1.28 burden.

**Build-up.** The loaded hourly wage in cents is the `base_wage_cents` multiplied by the selected burden, rounded half up to a whole cent; the burden multiplies the wage before any labor cost is formed. The `labor_cost_cents` is then `monthly_labor_hours` multiplied by that loaded wage, rounded half up. The `supply_cost_cents` is the sum over every service area of its `sqft` multiplied by the supply rate in cents per square foot for that area's soil level, where `LIGHT` is 1.0 cent per square foot, `MEDIUM` is 1.5, and `HEAVY` is 3.0; that sum is rounded half up to a whole cent. The direct cost is the labor cost plus the supply cost plus a fixed equipment amortization of 7500 cents. Overhead is the direct cost multiplied by 15 percent (0.15), rounded half up. The `total_cost_cents` is the direct cost plus the overhead. Finally the `base_bid_cents` is the total cost divided by the quantity one minus `target_margin_pct`, rounded half up to a whole cent.

### 3.5. Building, Sending, and Revising the Proposal

A `SalesRep` creates a proposal from a priced bid. The create takes a `bid_estimate_id`, which must reference a `BidEstimate` that is in status `PRICED`; if the referenced estimate is not `PRICED`, the create is rejected with `ERR_BID_NOT_PRICED`. The new `Proposal` records its `rfp_id`, starts in status `DRAFT` with `revision_round` equal to 1, and immediately computes its pricing. The proposal status enumerates `DRAFT`, `SENT`, `ACCEPTED`, and `DECLINED`, with `ACCEPTED` and `DECLINED` terminal.

**Proposal pricing.** The pricing reads the referenced bid's `base_bid_cents` and applies a volume discount keyed on that base bid, in a pinned evaluation order: read the base bid, pick the discount tier from the base bid, apply the discount, then recompute the achieved margin on the discounted price. The discount is 0.00 when `base_bid_cents` is below 500000 cents, 0.03 when it is at least 500000 but below 800000 cents, and 0.05 when it is at least 800000 cents. The `monthly_price_cents` is the base bid multiplied by the quantity one minus the discount percentage, rounded half up to a whole cent. The `achieved_margin_pct` is the difference between `monthly_price_cents` and the bid's `total_cost_cents`, divided by `monthly_price_cents`; this ratio is kept to four decimal places internally and is compared, after multiplying by 100, against the margin floor.

**Sending.** Sending a proposal advances it from `DRAFT` to `SENT` and advances the parent opportunity from `BIDDING` to `PROPOSED`. The proposal must currently be `DRAFT` and its parent opportunity must be in `BIDDING`, otherwise `ERR_INVALID_STATE`. The send is gated by a margin floor: the proposal's `achieved_margin_pct` multiplied by 100 must be at least 15.0, the minimum margin percent; if it falls below 15.0 the send is rejected with `ERR_MARGIN_BELOW_FLOOR`.

**Revising.** The pipeline is cyclic. Revising a `SENT` proposal returns it from `SENT` to `DRAFT`, increments its `revision_round` by one, and returns the parent opportunity from `PROPOSED` back to `BIDDING` for re-pricing and re-sending. The proposal must currently be `SENT`, otherwise `ERR_INVALID_STATE`. From `BIDDING` the estimator can re-price and the rep can re-send, looping as many rounds as needed.

**Accepting and declining.** Accepting a `SENT` proposal moves it to `ACCEPTED` and the opportunity from `PROPOSED` to `WON`. Declining a `SENT` proposal moves it to `DECLINED` and the opportunity from `PROPOSED` to `LOST`. Both require the proposal to be `SENT`, otherwise `ERR_INVALID_STATE`. These two branches are symmetric: each is a single state move on the proposal paired with the corresponding terminal move on the opportunity.

### 3.6. Drafting and Signing the Contract

Once a proposal is accepted, a `SalesRep` drafts a `CleaningContract` under the account. The create takes a `proposal_id` and a `term_months` length that must be at least 1 (`ERR_INVALID_RANGE`). The contract records its `account_id`, starts with `lifecycle_status` of `DRAFT` and `billing_status` of `PENDING`, and its `monthly_value_cents` is not yet set.

Signing the contract advances its `lifecycle_status` from `DRAFT` to `SIGNED`. Two preconditions apply beyond the generic checks: the contract must currently be `DRAFT` (`ERR_INVALID_STATE`), and the linked proposal named by `proposal_id` must be in status `ACCEPTED`, otherwise the sign is rejected with `ERR_PROPOSAL_NOT_ACCEPTED`. Signing has two side effects: it snapshots `monthly_value_cents` from the accepted proposal's `monthly_price_cents` (immutable thereafter until a renewal or upsell changes it), and it creates a `StartupPlan` in status `PLANNING` whose `planned_monthly_hours` is snapshotted from the bid estimate's `monthly_labor_hours` reached through the contract's proposal.

### 3.7. Crewing the Start-Up Plan

The `StartupPlan` records its parent `contract_id` and a `go_live_at` target service-start timestamp. The plan is created server-side at contract signing (§3.6), not through a client create call, so no `go_live_at` is supplied or validated against the logical clock at that point; its `go_live_at` is initialized to null and the system performs no "strictly after the current logical time" check on it. Its status enumerates `PLANNING`, `CREWED`, `READY`, `LIVE`, and `ABORTED`, with `LIVE` and `ABORTED` terminal. Its `allocated_hours` is a read-only sum of the hours of its currently assigned crew shifts.

Crews are a top-level resource. An `OperationsManager` creates a `Crew` with a `name` and a `weekly_capacity_hours` maximum greater than zero; a new crew is `AVAILABLE`, and crew status enumerates `AVAILABLE` and `RETIRED`. Retiring a crew sets its status to `RETIRED`; the crew must currently be `AVAILABLE`, otherwise the retire is rejected with `ERR_INVALID_STATE`.

An `OperationsManager` assigns crew by posting a shift to the start-up plan with a `crew_id`, a `start_at`, and an `end_at` (which must be strictly after `start_at`, `ERR_INVALID_RANGE`). The created `CrewShift` records its `startup_plan_id`, starts in status `ASSIGNED`, and has a read-only `shift_hours` equal to the elapsed time from `start_at` to `end_at` expressed in hours to two decimal places. Crew-shift status enumerates `ASSIGNED` and `CANCELLED`.

Assigning the first shift moves the plan from `PLANNING` to `CREWED` and, as a cross-aggregate cascade, advances the parent contract's `lifecycle_status` from `SIGNED` to `STARTUP`. Each subsequent assignment is a self-loop that keeps the plan in `CREWED`. Four preconditions gate assignment, evaluated after the generic checks: the plan must be in `PLANNING` for the first shift (or `CREWED` for an additional shift), otherwise `ERR_INVALID_STATE`; for the first shift the parent contract's `lifecycle_status` must be `SIGNED`, otherwise `ERR_CONTRACT_NOT_SIGNED`; the named crew must be `AVAILABLE`, otherwise `ERR_CREW_UNAVAILABLE`; and the new shift must not overlap any existing `ASSIGNED` shift on the same crew under a half-open interval comparison extended by a fixed crew travel buffer of 30 minutes appended to the end of each interval, otherwise `ERR_SHIFT_OVERLAP`. Concretely, treating each existing shift as the half-open interval `[start_at, end_at + 30min)` and the new shift's end likewise extended by the buffer, the new shift collides when its `start_at` is before an existing shift's buffered end and that existing shift's `start_at` is before the new shift's buffered end. Each assignment recomputes the plan's `allocated_hours`.

**Hour allocation.** The plan's `allocated_hours` is the sum of `shift_hours` over every crew shift on the plan whose status is `ASSIGNED`, rounded half up to two decimal places, with the shifts accumulated in `created_at` ascending order for determinism. The unallocated hours are the planned monthly hours minus the allocated hours, but never below zero. The invariant is that allocated plus unallocated equals `planned_monthly_hours` once the plan is fully crewed.

A shift can be released. Cancelling an `ASSIGNED` shift moves it to `CANCELLED` and, as a compensating release, subtracts that shift's `shift_hours` from the plan's `allocated_hours`, preserving the allocation invariant. The shift must be `ASSIGNED` and its parent plan must not be `LIVE`, otherwise `ERR_INVALID_STATE`.

### 3.8. Readiness, Go-Live, and the Onboarding Handoff

When enough hours are scheduled, the `OperationsManager` marks the plan ready, advancing it from `CREWED` to `READY`. The plan must be `CREWED` (`ERR_INVALID_STATE`) and its `allocated_hours` must be at least its `planned_monthly_hours`; if hours are still short, mark-ready is rejected with `ERR_HOURS_UNDERALLOCATED`.

Going live advances the plan from `READY` to `LIVE` and is the onboarding handoff with several cross-entity cascades. The plan must be `READY`, otherwise `ERR_STARTUP_NOT_READY` (and the parent contract must be in `STARTUP`, otherwise `ERR_INVALID_STATE`). Going live advances the parent contract's `lifecycle_status` from `STARTUP` to `SERVICING`, moves the contract's `billing_status` from `PENDING` to `ACTIVE` as the cross-axis activation, and promotes the account's `lifecycle_stage` from `PROSPECT` to `ACTIVE_CUSTOMER`, completing the handoff to account management.

A plan can instead be aborted. Aborting is permitted while the plan is `PLANNING`, `CREWED`, or `READY`, otherwise `ERR_INVALID_STATE`; it moves the plan to `ABORTED`. Abort cancels every `ASSIGNED` crew shift on the plan, setting each to `CANCELLED` and releasing its `shift_hours` back so the allocation drops accordingly, and it debits the account's `health_score` by the abort penalty of 10 points, floored at 0.

### 3.9. Provisioning Supplies under Budget Conservation

After a contract exists, an `OperationsManager` creates a `SupplyBudget` for it with a `total_cents` monthly budget greater than zero. The budget records its `contract_id`, starts with `committed_cents` of 0, and a `remaining_cents` that is its `total_cents` minus its `committed_cents`. The conservation invariant is that committed plus remaining always equals total.

Within a budget, the manager raises supply requisitions, each with an `item_label` and an `amount_cents` requested spend greater than zero. A new `SupplyRequisition` records its `supply_budget_id` and starts in status `REQUESTED`; the status enumerates `REQUESTED`, `APPROVED`, and `CANCELLED`, with `CANCELLED` terminal.

Approving a requisition moves it from `REQUESTED` to `APPROVED` and commits its funds. The requisition must be `REQUESTED` (`ERR_INVALID_STATE`), its `amount_cents` must not exceed the budget's `remaining_cents`, otherwise `ERR_BUDGET_EXCEEDED`, and the approval must satisfy the optimistic-concurrency check on the budget described in §2.9 — it carries `expected_supply_budget_version` and is rejected with `ERR_STALE_VERSION` if that does not match the budget's current `version`. On approval the budget's `committed_cents` increases by the requisition's `amount_cents`, `remaining_cents` is recomputed, and the budget's `version` increments by one.

Cancelling a requisition has two cases. Cancelling an `APPROVED` requisition is a compensating credit: it moves the requisition to `CANCELLED`, subtracts its `amount_cents` from the budget's `committed_cents` (preserving the committed-plus-remaining-equals-total invariant), and increments the budget's `version` by one. Cancelling a `REQUESTED` requisition simply moves it to `CANCELLED` with no budget change, because nothing was ever committed. A cancel on a requisition in any other status is rejected with `ERR_INVALID_STATE`.

### 3.10. Account Management: Billing, Renewal, Retention, and Upsell

Once the account is an active customer, the `AccountManager` runs the parallel billing axis and the retention lifecycle.

**Billing.** Suspending billing moves `billing_status` from `ACTIVE` to `SUSPENDED`; it requires the contract to currently be `ACTIVE` on the billing axis (`ERR_INVALID_STATE`) and the `lifecycle_status` to be `SERVICING`, otherwise `ERR_CONTRACT_NOT_SERVICING`. Suspension debits the account's `health_score` by the suspend penalty of 5 points, floored at 0, and leaves `lifecycle_status` unchanged. Resuming billing moves `billing_status` from `SUSPENDED` back to `ACTIVE` (the billing axis must be `SUSPENDED`, otherwise `ERR_INVALID_STATE`) and credits the account's `health_score` back by the same suspend penalty of 5 points, capped at 100. The suspend and resume penalties are equal and opposite, so a suspend-then-resume cycle returns the score to where it began (subject to the 0 and 100 bounds).

**Ending.** An `AccountManager` may end a servicing contract, moving its `lifecycle_status` from `SERVICING` to `ENDED` (it must be `SERVICING`, otherwise `ERR_INVALID_STATE`) and its `billing_status` to `CLOSED`. If the account has no other contract still in `SERVICING`, the account's `lifecycle_stage` becomes `CHURNED`.

**Renewal.** Creating a renewal cycle for a contract takes an `escalation_method`, which must be `CPI` or `FLAT` (`ERR_INVALID_ENUM`); the parent contract must be `SERVICING`, otherwise `ERR_CONTRACT_NOT_SERVICING`. A new `RenewalCycle` records its `contract_id`, starts in status `DRAFT`, and computes a `proposed_monthly_cents` escalated price. The status enumerates `DRAFT`, `OFFERED`, `RENEWED`, and `LAPSED`, with `RENEWED` and `LAPSED` terminal. The escalation starts from the contract's current `monthly_value_cents`. Under the `CPI` method the proposed price is that base multiplied by the quantity one plus 0.032 (a 3.2 percent consumer-price escalation), rounded half up to whole cents. Under the `FLAT` method the proposed price is the base plus a fixed increase of 15000 cents. The two methods diverge for the same contract value.

Offering a renewal moves the cycle from `DRAFT` to `OFFERED` (must be `DRAFT`, otherwise `ERR_INVALID_STATE`) and requires the parent contract to be `SERVICING` (`ERR_CONTRACT_NOT_SERVICING`). Accepting an offered renewal moves it from `OFFERED` to `RENEWED` (must be `OFFERED`, otherwise `ERR_INVALID_STATE`); it is guarded by the optimistic-concurrency check on the contract described in §2.9, carrying `expected_contract_version` and rejected with `ERR_STALE_VERSION` on a mismatch. Acceptance sets the contract's `monthly_value_cents` to the cycle's `proposed_monthly_cents` and credits the account's `health_score` by the renewal bonus of 5 points, capped at 100. Lapsing an offered renewal moves it from `OFFERED` to `LAPSED` (must be `OFFERED`, otherwise `ERR_INVALID_STATE`) and churns the relationship: it advances the contract's `lifecycle_status` from `SERVICING` to `ENDED`, sets the contract's `billing_status` to `CLOSED`, marks the account's `lifecycle_stage` as `CHURNED` if no other contract remains in `SERVICING`, and debits the account's `health_score` by the lapse penalty of 10 points, floored at 0. The accept and lapse branches are the symmetric outcomes of an offered cycle — one credits health and raises contract value, the other penalizes health and closes the relationship.

**Upsell.** An `AccountManager` may add a floor or window upsell line to a contract, raising its monthly value. The request carries an `upsell_type`, a `monthly_addon_cents`, and `expected_contract_version`. The contract must be in `SERVICING` and the `monthly_addon_cents` must be greater than zero; otherwise the upsell is rejected with `ERR_UPSELL_INVALID`. The upsell is also guarded by the same optimistic-concurrency check on the contract — a stale `expected_contract_version` is rejected with `ERR_STALE_VERSION`. On success the contract's `monthly_value_cents` increases by `monthly_addon_cents`, the contract's `version` increments by one, and the account's `health_score` is credited by the upsell bonus of 3 points, capped at 100.

### 3.11. Logical Clock

A `PlatformAdmin` may drive the server's logical clock for testing by supplying a `to_iso8601` instant; the clock is then set to that value and reported back. The set returns HTTP 200 with the standard object envelope whose `data` is `{ "now": "<the set instant>" }`, echoing the supplied ISO 8601 string verbatim. A `to_iso8601` that is missing or not a parseable ISO 8601 string is rejected with `ERR_INVALID_REQUEST`. The server's logical clock starts at 2026-03-01T00:00:00Z and reads exactly that default until set; it never falls back to wall-clock time. All "after now" checks — for example a start-up plan's `go_live_at` being strictly after the current time — read this logical clock.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. All responses use the envelope of §2.2. Request bodies, response payloads, and side effects are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/accounts` | Create prospect account | SalesRep |
| GET | `/accounts/{accountId}` | Get account | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| GET | `/accounts` | List accounts | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/site-contacts` | Add a site contact with availability window | SalesRep |
| GET | `/accounts/{accountId}/site-contacts` | List site contacts of account | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/rfps` | Create RFP opportunity | SalesRep |
| GET | `/accounts/{accountId}/rfps/{rfpId}` | Get RFP | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| GET | `/accounts/{accountId}/rfps` | List RFPs of account | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/rfps/{rfpId}/walkthroughs` | Schedule walkthrough | SalesRep |
| GET | `/accounts/{accountId}/rfps/{rfpId}/walkthroughs` | List walkthroughs of RFP | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/rfps/{rfpId}/walkthroughs/{wtId}/complete` | Complete walkthrough | SalesRep |
| POST | `/accounts/{accountId}/rfps/{rfpId}/service-areas` | Add a service area to the RFP scope | SalesRep, BidEstimator |
| GET | `/accounts/{accountId}/rfps/{rfpId}/service-areas` | List service areas of RFP | SalesRep, BidEstimator, OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/rfps/{rfpId}/bid-estimates` | Create a draft bid estimate | BidEstimator |
| GET | `/accounts/{accountId}/rfps/{rfpId}/bid-estimates/{bidId}` | Get bid estimate | BidEstimator, SalesRep, PlatformAdmin |
| GET | `/accounts/{accountId}/rfps/{rfpId}/bid-estimates` | List bid estimates of RFP | BidEstimator, SalesRep, PlatformAdmin |
| POST | `/accounts/{accountId}/rfps/{rfpId}/bid-estimates/{bidId}/price` | Run labor load and bid build-up | BidEstimator |
| POST | `/accounts/{accountId}/rfps/{rfpId}/proposals` | Create proposal from a PRICED bid | SalesRep |
| GET | `/accounts/{accountId}/rfps/{rfpId}/proposals/{proposalId}` | Get proposal | SalesRep, AccountManager, PlatformAdmin |
| GET | `/accounts/{accountId}/rfps/{rfpId}/proposals` | List proposals of RFP | SalesRep, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/rfps/{rfpId}/proposals/{proposalId}/send` | Send proposal (margin floor gate) | SalesRep |
| POST | `/accounts/{accountId}/rfps/{rfpId}/proposals/{proposalId}/revise` | Revise sent proposal | SalesRep |
| POST | `/accounts/{accountId}/rfps/{rfpId}/proposals/{proposalId}/accept` | Accept proposal | SalesRep |
| POST | `/accounts/{accountId}/rfps/{rfpId}/proposals/{proposalId}/decline` | Decline proposal | SalesRep |
| POST | `/accounts/{accountId}/contracts` | Create contract draft from an ACCEPTED proposal | SalesRep |
| GET | `/accounts/{accountId}/contracts/{contractId}` | Get contract | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| GET | `/accounts/{accountId}/contracts` | List contracts of account | SalesRep, OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/contracts/{contractId}/sign` | Sign contract (creates StartupPlan) | SalesRep |
| POST | `/accounts/{accountId}/contracts/{contractId}/end` | End a servicing contract | AccountManager |
| POST | `/accounts/{accountId}/contracts/{contractId}/billing/suspend` | Suspend billing | AccountManager |
| POST | `/accounts/{accountId}/contracts/{contractId}/billing/resume` | Resume billing | AccountManager |
| GET | `/accounts/{accountId}/startup-plans/{planId}` | Get startup plan | OperationsManager, SalesRep, PlatformAdmin |
| GET | `/accounts/{accountId}/startup-plans` | List startup plans | OperationsManager, SalesRep, PlatformAdmin |
| POST | `/accounts/{accountId}/startup-plans/{planId}/crew` | Assign a crew shift | OperationsManager |
| POST | `/accounts/{accountId}/startup-plans/{planId}/mark-ready` | Mark plan READY | OperationsManager |
| POST | `/accounts/{accountId}/startup-plans/{planId}/go-live` | Go live | OperationsManager |
| POST | `/accounts/{accountId}/startup-plans/{planId}/abort` | Abort plan | OperationsManager |
| POST | `/crews` | Create a crew | OperationsManager |
| GET | `/crews/{crewId}` | Get crew | OperationsManager, PlatformAdmin |
| POST | `/crews/{crewId}/retire` | Retire a crew | OperationsManager |
| GET | `/accounts/{accountId}/startup-plans/{planId}/crew-shifts` | List crew shifts of a plan | OperationsManager, SalesRep, PlatformAdmin |
| GET | `/accounts/{accountId}/crew-shifts` | List crew shifts | OperationsManager, PlatformAdmin |
| POST | `/accounts/{accountId}/crew-shifts/{shiftId}/cancel` | Cancel a shift | OperationsManager |
| POST | `/accounts/{accountId}/contracts/{contractId}/supply-budget` | Create supply budget for contract | OperationsManager |
| GET | `/accounts/{accountId}/contracts/{contractId}/supply-budget` | List supply budget of contract | OperationsManager, AccountManager, PlatformAdmin |
| GET | `/accounts/{accountId}/supply-budgets/{budgetId}` | Get supply budget | OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/supply-budgets/{budgetId}/requisitions` | Create a supply requisition | OperationsManager |
| GET | `/accounts/{accountId}/supply-budgets/{budgetId}/requisitions` | List requisitions of a budget | OperationsManager, AccountManager, PlatformAdmin |
| GET | `/accounts/{accountId}/supply-requisitions/{reqId}` | Get requisition | OperationsManager, AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/supply-requisitions/{reqId}/approve` | Approve requisition (OCC on budget) | OperationsManager |
| POST | `/accounts/{accountId}/supply-requisitions/{reqId}/cancel` | Cancel requisition | OperationsManager |
| POST | `/accounts/{accountId}/contracts/{contractId}/renewal-cycles` | Create renewal cycle | AccountManager |
| GET | `/accounts/{accountId}/contracts/{contractId}/renewal-cycles` | List renewal cycles of contract | AccountManager, PlatformAdmin |
| GET | `/accounts/{accountId}/renewal-cycles/{cycleId}` | Get renewal cycle | AccountManager, PlatformAdmin |
| POST | `/accounts/{accountId}/renewal-cycles/{cycleId}/offer` | Offer renewal | AccountManager |
| POST | `/accounts/{accountId}/renewal-cycles/{cycleId}/accept` | Accept renewal (OCC on contract) | AccountManager |
| POST | `/accounts/{accountId}/renewal-cycles/{cycleId}/lapse` | Lapse renewal | AccountManager |
| POST | `/accounts/{accountId}/contracts/{contractId}/upsell` | Add a floor/window upsell line (OCC on contract) | AccountManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROPOSAL_NOT_ACCEPTED` | 409 |
| `ERR_BID_NOT_PRICED` | 409 |
| `ERR_CONTRACT_NOT_SIGNED` | 409 |
| `ERR_CONTRACT_NOT_SERVICING` | 409 |
| `ERR_STARTUP_NOT_READY` | 409 |
| `ERR_HOURS_UNDERALLOCATED` | 409 |
| `ERR_MARGIN_BELOW_FLOOR` | 422 |
| `ERR_BUDGET_EXCEEDED` | 409 |
| `ERR_CREW_UNAVAILABLE` | 409 |
| `ERR_OUTSIDE_AVAILABILITY` | 422 |
| `ERR_WALKTHROUGH_OVERLAP` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_UPSELL_INVALID` | 422 |
| `ERR_SITE_CONTACT_MISMATCH` | 409 |
| `ERR_SERVICE_AREA_REQUIRED` | 409 |
| `ERR_VALIDATION_LIMIT` | 422 |
