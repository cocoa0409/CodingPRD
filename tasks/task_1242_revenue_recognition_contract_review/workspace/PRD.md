# Revenue Recognition API — Product Requirements Document

## 1. Introduction

Revenue recognition under ASC 606 is, at its core, a reconciliation problem: for every customer contract, the business must track what it has billed, what it has earned, and why the two differ — and it must be able to explain every movement between those measures to an auditor. This document specifies the Revenue Recognition API, a system that operationalizes the standard's five-step model end to end: identifying contracts and assessing whether near-simultaneous agreements were negotiated as a package, identifying performance obligations and allocating the transaction price across them using standalone selling prices, estimating variable consideration and constraining it by contract risk, determining whether revenue is recognized at a point in time or over time, accounting for contract modifications, and assembling the period-end disclosure data that downstream reporting consumes.

Two design commitments shape everything that follows. First, the system is ledger-oriented: billings (driven by invoices) and recognized revenue (driven by delivery and progress) run as independent measures over the same contract, and the contract asset and deferred revenue balances are nothing more — and nothing less — than the reconciling difference between them; every recognition, billing, void, reversal, modification, and re-estimation re-runs that reconciliation atomically within the request. Second, the system is review-oriented: contracts carrying non-standard terms pass through a claim–recommend–decide workflow, and every consequential approval enforces segregation of duties so that no operator can both propose and approve, recommend and decide, or assemble and finalize the same object. Because period boundaries govern what may post where, all date-sensitive behavior is driven by a controllable logical clock rather than the wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint. All business resources are mounted under the `/revrec` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. The system declares exactly five roles, spelled precisely as follows: `RevenueAccountant`, `RevenueManager`, `ContractReviewer`, `Controller`, and `SystemAdmin`.

- A `RevenueAccountant` is the preparer: this role builds customers, contracts, performance obligations, clauses, estimates, modifications, invoices, cost entries, and reversals, and assembles disclosure packs.
- A `RevenueManager` is the approver: this role approves contract allocations, estimates, and modifications, maintains the standalone-selling-price master, holds and resumes contracts, voids invoices, and runs combination absorptions.
- A `ContractReviewer` performs the legal review of non-standard terms by claiming, recommending on, and deciding review tasks.
- A `Controller` owns the ledger calendar: opening, closing, and reopening accounting periods and finalizing disclosure packs.
- A `SystemAdmin` operates the test harness's logical clock and nothing else — no business operations, no business reads.

A request whose headers are missing or empty, or whose `X-User-Role` does not name one of the five declared roles, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the targeted endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For every one of the five roles — `RevenueAccountant`, `RevenueManager`, `ContractReviewer`, `Controller`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow writes it (for example as `proposed_by_user_id` on an estimate or modification, as `reviewer_user_id` on a claimed review task, or as `finalized_by_user_id` on a disclosure pack) but never compares it against any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Contract Version Counter

Most resources share a standard envelope of system-managed properties. The `id` is a server-minted UUID carrying no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `created_at` is fixed at creation while `updated_at` is refreshed on every mutation. The `version` is an integer that increments by one on every mutation of the resource and underpins the concurrency guard of §2.7.

Two resource kinds are deliberately leaner. A `RevenueEntry` and a `CostEntry` carry only `id` and `created_at` — both `updated_at` and `version` are absent on them, because these records are append-only: entries are never edited in place, and corrections are expressed by posting compensating entries (§3.7).

The contract's `version` is the pivot of the modification concurrency guard, so it matters exactly which operations advance it: submitting, returning, approving, activating, holding, resuming, cancelling, and absorbing a contract; proposing a modification and approving one; approving an estimate; issuing and voiding an invoice; and posting a reversal each increment the owning contract's `version` by one and refresh its `updated_at`. Operations not named here — creating an obligation, a clause, an estimate, or a cost entry; satisfying or recognizing an obligation; assembling or finalizing a pack — do not, by themselves, increment the contract's `version` (though the satisfaction and recognition of obligations, like invoice events, may trigger the auto-completion evaluation of §3.4).

### 2.5. The Logical Clock

Every date-sensitive decision — which accounting period a posting lands in, how many days of a straight-line schedule have elapsed, whether a temporal window is still open — is evaluated against a server-side logical clock, never the wall clock. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and until the first clock-setting call it continues to read that default rather than the wall clock.

A `SystemAdmin`-only test-driving capability, mounted outside the business prefix at `/_clock/set_current_utc`, advances the logical clock to a supplied `to_iso8601` instant and answers with the server's `current_utc`. Business endpoints never accept a caller-supplied "now"; the clock moves only through this capability.

### 2.6. Monetary Precision, Ratios, and Rounding

All money in the system is carried as integer cents — `fixed_consideration_cents`, `amount_cents`, `ssp_cents`, and their aggregates are exact integers, and no monetary figure is ever stored or returned with a fractional part. Where a computation produces a non-integer intermediate — the probability-weighted mean of an expected-value estimate, a per-obligation allocation share, an over-time recognition target — the result is rounded half up to whole cents at exactly the points the business rules of §3 nominate, and not before. Where a rule calls for a floor instead, it says so explicitly: the variable-consideration constraint of §3.5 rounds the cap term down to whole cents.

Calendar dates are exchanged as ISO `yyyy-mm-dd` strings. One ratio is exposed for information only: a performance obligation's `progress_pct` renders its over-time progress rounded half up to six decimal places, while all recognition math uses the unrounded ratio (§3.6).

### 2.7. Optimistic Concurrency Control on Modification Proposals

Exactly one endpoint participates in optimistic concurrency control: the proposal of a contract modification against an existing contract. The request must carry `expected_contract_version` — a non-optional field holding the owning contract's `version` as the client last observed it. When the supplied value does not equal the contract's current `version`, the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412): the contract's consideration, allocation, or lifecycle has advanced since the client read it, and letting the proposal through would act on a contract the client has not observed.

Nothing else takes a version field — no other endpoint accepts or requires an expected-version input. Note also what the guard is not: it is not a mutual-exclusion lock on proposals. Several modifications may legitimately be proposed against the same `ACTIVE` contract, so a second, strictly sequential proposal is rejected only when it carries a stale `expected_contract_version`, never merely because an earlier proposal already exists.

### 2.8. Validation Order of Precedence

Every request passes through a fixed, tiered validation pipeline, and the first failing tier determines the error returned — a request that violates rules from several tiers always surfaces the earliest tier's error, never a later one's. The tiers, in evaluation order:

1. **Request context.** The `X-User-ID` and `X-User-Role` headers must be present and non-empty, and the role must be one of the five declared roles; otherwise `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). Applies to every endpoint.
2. **Authorization.** The caller's role must be permitted on the endpoint per §4; otherwise `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Task ownership is enforced at this same tier: submitting a recommendation on a review task claimed by someone else fails with `ERR_NOT_TASK_OWNER` (HTTP 403).
3. **Existence and request shape.** Path identifiers must resolve to existing resources, validated left to right (§2.9); otherwise `ERR_NOT_FOUND` (HTTP 404). At this same tier, required request fields must be present — including pattern-conditional fields such as the service dates for a straight-line obligation or `estimated_total_cost_cents` for an input-cost obligation — values must be well-formed, and enum fields must hold declared members; failures of this kind return `ERR_INVALID_REQUEST` (HTTP 400).
4. **Optimistic concurrency.** On modification proposals, `expected_contract_version` must equal the contract's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412).
5. **State validity.** The target resource must be in a state from which the attempted operation exists as a transition; otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Operation-specific state failures live at this same tier: `ERR_CONTRACT_NOT_ACTIVE`, `ERR_ENTRY_LOCKED`, and `ERR_PACK_PERIOD_NOT_CLOSED` (all HTTP 409).
6. **Compliance gates.** A contract cannot be approved while clause review is outstanding (`ERR_REVIEW_OUTSTANDING`, HTTP 409), and segregation of duties must hold on every approve, decide, and finalize step (`ERR_SOD_VIOLATION`, HTTP 409).
7. **Temporal windows.** Posting and incurrence dates must land in an open period, period and price-book windows must not collide, and the combination window must hold: `ERR_PERIOD_CLOSED`, `ERR_PERIOD_OVERLAP`, `ERR_PERIOD_REOPEN_LIMIT`, `ERR_SSP_WINDOW_OVERLAP`, and `ERR_COMBINATION_WINDOW_EXCEEDED` (all HTTP 409).
8. **Amounts and structures.** Shape and constraint rules on amounts and payloads: `ERR_SCENARIO_WEIGHTS`, `ERR_INVALID_AMOUNT`, `ERR_RECOGNITION_PATTERN_FORBIDDEN`, and `ERR_NO_PENDING_POB` (all HTTP 422).
9. **Cross-entity references.** References must resolve and be mutually compatible: a covering price-book record must exist (`ERR_SSP_NOT_FOUND`, HTTP 422) and the combination criteria must hold (`ERR_COMBINATION_CRITERIA_NOT_MET`, HTTP 422).
10. **Fiscal caps.** Money ceilings: reallocation may not push an obligation below its recognized amount (`ERR_OVER_RECOGNITION`, HTTP 422), and cumulative billings may not exceed the transaction price (`ERR_BILLING_EXCEEDS_PRICE`, HTTP 422).

Because tiers are evaluated in order, a stale-version failure (tier 4) is reported before any state-transition problem (tier 5); a clause-review or duty-segregation gate (tier 6) is reported before a period-window problem (tier 7); and a malformed scenario set or a forbidden pattern combination (tier 8) is reported before a missing price-book record (tier 9) or a breached fiscal cap (tier 10).

### 2.9. Path Identifier Resolution

Endpoints that address nested or specific resources validate their path identifiers strictly left to right. The first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later identifier — and before any business rule — is examined. The identifier names used across the API are `customer_id`, `contract_id`, `pob_id`, `estimate_id`, `modification_id`, `task_id`, `invoice_id`, `period_id`, `entry_id`, `pack_id`, and `ssp_id`; several collection-creation paths address their parent simply as `id`. A request to list the obligations of a contract that does not exist, for example, fails on the contract identifier regardless of what else is wrong with the request.

### 2.10. Segregation of Duties

A strict propose/approve separation holds on every consequential decision, and all four pairings fail with the same `ERR_SOD_VIOLATION` (HTTP 409):

- A variable consideration estimate may not be approved by the operator who proposed it — the approver's `X-User-ID` must differ from the estimate's `proposed_by_user_id`.
- A contract modification may not be approved by the operator who proposed it — the approver's `X-User-ID` must differ from the modification's `proposed_by_user_id`.
- A review task may not be decided by the reviewer who recommended it — the decider's `X-User-ID` must differ from the task's `recommended_by_user_id`.
- A disclosure pack may not be finalized by the operator who assembled it — the finalizer's `X-User-ID` must differ from the pack's `assembled_by_user_id`.

The server learns who proposed, recommended, or assembled an object exclusively from the `X-User-ID` header captured at that earlier step; there is no way to supply these identities from the outside.

### 2.11. The Dual-Measure Ledger Identity

Every contract runs two independent measures over its lifetime. The first is billings: `billed_to_date_cents` is the sum of `amount_cents` over the contract's `ISSUED` invoices minus the amounts of its `VOIDED` invoices. The second is recognition: `recognized_to_date_cents` is the sum of the signed `amount_cents` over the contract's revenue entries whose status is `POSTED` or `LOCKED`. The contract's reported position is the reconciling difference between the two, floored at zero in each direction: `deferred_revenue_balance_cents` is the larger of zero and billings minus recognition, and `contract_asset_balance_cents` is the larger of zero and recognition minus billings.

An identity follows and holds after every event — invoice issue, invoice void, entry posting of any origin, and reversal alike: billings minus recognition always equals deferred revenue minus contract asset. Both balances can never be positive at once, and neither can ever be negative. Section 3.7 defines how the same identity is read as a per-period rollforward.

## 3. Business Logic & Workflows

### 3.1. Customers and Contract Intake

Work begins with the customer master. A `RevenueAccountant` registers a customer by supplying its `legal_name` and an `external_ref`; the external reference is unique per customer and is how upstream CRM systems reconcile accounts.

Against a registered customer, the accountant opens a contract — the central organizing entity of the system — by providing the `customer_id`, a `contract_ref` (unique per contract), the `signed_date` as an ISO `yyyy-mm-dd` string, the `fixed_consideration_cents` (a non-negative integer count of cents), and the contract's `risk_tier`, which must be one of `STANDARD`, `ELEVATED`, or `HIGH`. An optional `package_negotiated_flag`, defaulting to `false`, records that the contract was negotiated as a package with other contracts — a fact that becomes decisive at combination-assessment time (§3.4), while the risk tier drives the variable-consideration constraint cap of §3.5.

A newly created contract starts in `DRAFT` with its financial measures at their origins: `vc_estimate_cents` is zero, `transaction_price_cents` equals the fixed consideration, and `allocated_total_cents`, `billed_to_date_cents`, `recognized_to_date_cents`, `deferred_revenue_balance_cents`, and `contract_asset_balance_cents` are all zero. The `combined_into_contract_id` and `active_vc_estimate_id` references and the `completed_at` timestamp are null. From `DRAFT`, the contract's `status` walks the review loop `DRAFT → IN_REVIEW → APPROVED → ACTIVE`, with the revision detour `IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW`, the operational pause `ACTIVE → ON_HOLD → ACTIVE`, and the three terminal outcomes `COMPLETED`, `CANCELLED`, and `ABSORBED` described in §3.4. The transaction price is at all times derived, never set directly: `transaction_price_cents` is the sum of `fixed_consideration_cents` and `vc_estimate_cents`, and it is recomputed whenever either component changes. The contract list supports optional `customer_id`, `status`, and `combined_into_contract_id` filters.

### 3.2. Contract Clauses and the Non-Standard Term Review Loop

While a contract is `DRAFT` or `CHANGES_REQUESTED`, a `RevenueAccountant` records its clauses. Each clause carries a `clause_code` unique within its contract, a `clause_type` drawn from `TERMINATION_FOR_CONVENIENCE`, `EXTENDED_PAYMENT_TERMS`, `PENALTY`, `RIGHT_OF_RETURN`, `ACCEPTANCE_CLAUSE`, and `MOST_FAVORED_CUSTOMER`, the boolean `is_non_standard`, and optionally the verbatim `clause_text`. A clause's initial `status` depends entirely on that flag: non-standard clauses start in `PENDING_REVIEW` and must pass legal review, while standard clauses start already `APPROVED`.

Submitting the contract moves it from `DRAFT` to `IN_REVIEW` — or, in the revision loop, from `CHANGES_REQUESTED` back to `IN_REVIEW`. Submission is possible only once at least one performance obligation exists for the contract, and each submission bumps the contract's `version`. As the contract enters review, the system spawns one review task per clause that is non-standard and still `PENDING_REVIEW`; each task is created in `ASSIGNED` status with its `clause_id` pointing at the clause under review, its `contract_id` pointing at the owning contract, and its `reviewer_user_id` still null. Clauses already `APPROVED` keep their status and spawn no new task, so a re-submission after revisions only re-opens review for what actually changed. A `RevenueManager` who is unsatisfied returns the contract — `IN_REVIEW → CHANGES_REQUESTED` — supplying a `reason`; returning also bumps the contract's `version`.

The review task workflow belongs to the `ContractReviewer`. Claiming a task moves it `ASSIGNED → IN_REVIEW` and stamps `reviewer_user_id` with the claimant's `X-User-ID`. The claiming reviewer — and only that reviewer — then submits a `recommendation` of `APPROVE` or `REJECT`, optionally accompanied by a free-text `note`; a recommendation attempted by anyone other than the claiming reviewer is rejected with `ERR_NOT_TASK_OWNER` (HTTP 403). A successful recommendation moves the task `IN_REVIEW → RECOMMENDED` and records `recommended_by_user_id`. A different `ContractReviewer` then decides the task with a `decision` of `APPROVED`, `REJECTED`, or `RETURN`, again with an optional `note`; segregation of duties forbids the recommender from deciding, so a decider whose `X-User-ID` equals `recommended_by_user_id` is rejected with `ERR_SOD_VIOLATION` (§2.10). A decision of `APPROVED` or `REJECTED` moves the task `RECOMMENDED → DECIDED`, records `decided_by_user_id`, and sets the reviewed clause's `status` to `APPROVED` or `REJECTED` accordingly. A decision of `RETURN` is the rework loop: the task moves back `RECOMMENDED → IN_REVIEW`, the `recommendation` and `recommended_by_user_id` are cleared, and the original reviewer keeps the task. The review-task list supports optional `contract_id`, `clause_id`, `status`, and `reviewer_user_id` filters.

### 3.3. Standalone Selling Prices and Performance Obligations

The standalone-selling-price master is maintained by a `RevenueManager`. Each price record pairs a `product_code` with a `region` and sets the `ssp_cents` — which must be greater than zero — together with a coverage window from `effective_from` to `effective_to`. The window is closed at both ends: `effective_from` is the first covered date and `effective_to` the last, and `effective_to` may not precede `effective_from`. Two records for the same product-and-region pair may not have windows that overlap or even touch — a shared boundary date is already a conflict — and any such collision is rejected with `ERR_SSP_WINDOW_OVERLAP` (HTTP 409). Records are created `ACTIVE`; retirement moves a record `ACTIVE → RETIRED`, after which it no longer resolves prices.

While its contract is `DRAFT` or `CHANGES_REQUESTED`, a `RevenueAccountant` adds performance obligations to it. Each obligation is identified by a `pob_ref` unique within its contract and carries an optional free-text `description`, the `product_code` and `region` used to resolve its price, and a `recognition_pattern` of `POINT_IN_TIME`, `OVER_TIME_INPUT_COST`, or `OVER_TIME_STRAIGHT_LINE`. The pattern makes two field groups conditional: a straight-line obligation requires `service_start_date` and `service_end_date`, with the end date after the start date, while an input-cost obligation requires `estimated_total_cost_cents` greater than zero; missing conditional fields fail request validation with `ERR_INVALID_REQUEST`, and non-positive amounts fail with `ERR_INVALID_AMOUNT` (HTTP 422).

At the moment an obligation is created, the server resolves its `ssp_cents` from the `ACTIVE` price record whose closed window covers the obligation's `product_code` and `region` at the contract's `signed_date`, and pins that price onto the obligation — later price-book changes never move an existing obligation. When no active window covers the triple, creation is rejected with `ERR_SSP_NOT_FOUND` (HTTP 422). A new obligation starts `PENDING` with `allocated_amount_cents`, `recognized_revenue_cents`, `costs_incurred_to_date_cents`, and `progress_pct` all zero and `satisfied_at` null; its `contract_id` ties it to the owning contract. From `PENDING`, an obligation advances to `IN_PROGRESS` the first time a `RECOGNITION` or `CATCH_UP_ADJUSTMENT` entry posts against it, and reaches its terminal states `SATISFIED` (earned in full) or `CANCELLED` (only as a cascade of contract cancellation, §3.4).

### 3.4. Approval, Allocation, and the Contract Lifecycle

Approval is the pivot of the contract lifecycle. When a `RevenueManager` approves a contract in `IN_REVIEW`, the system first enforces the review gate: every clause of the contract must be `APPROVED`, so a single clause still `PENDING_REVIEW` or already `REJECTED` blocks approval with `ERR_REVIEW_OUTSTANDING` (HTTP 409). Approval then runs the allocation waterfall that pins the pricing snapshot. The pool is every non-`CANCELLED` obligation of the contract. Each obligation's raw share is the contract's `transaction_price_cents` multiplied by the obligation's pinned `ssp_cents` and divided by the total `ssp_cents` across the pool; obligations are processed in `created_at` ascending order, and each line is rounded half up to whole cents before the next is considered. The residual — the transaction price minus the sum of the rounded lines — is added to the pool obligation with the greatest `ssp_cents`, with ties broken by the earliest `created_at`; resource ids never participate in ordering. After the residual lands, the allocated lines sum exactly to the transaction price, and the contract's `allocated_total_cents` is set to `transaction_price_cents`. Each obligation's `allocated_amount_cents` is written at this moment, and approval bumps the contract's `version`.

Activation moves an `APPROVED` contract to `ACTIVE`; only an `ACTIVE` contract recognizes revenue, takes costs, bills, or accepts modifications. A `RevenueManager` may place an `ACTIVE` contract `ON_HOLD` — which blocks recognition, cost, invoice, and modification operations, each failing with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) while the hold lasts — and later resume it to `ACTIVE`. Activation, hold, and resume each bump the contract's `version`.

Cancellation is the accountant's exit before approval: from `DRAFT`, `IN_REVIEW`, or `CHANGES_REQUESTED`, a `RevenueAccountant` cancels the contract with a `reason`, moving it to the terminal `CANCELLED` state, cascading every obligation still `PENDING` or `IN_PROGRESS` to `CANCELLED`, and bumping the contract's `version`. Absorption is the combination exit: a `RevenueManager` runs the combination assessment on the surviving contract, naming the other contract in the `absorbed_contract_id` field. Two contracts are combinable only when all of the following hold: they belong to the same customer; their `signed_date` values differ by at most thirty days — a gap of exactly thirty days is still combinable, and thirty-one is not; at least one of the two carries `package_negotiated_flag` set to true; and both are still pre-approval, in `DRAFT`, `IN_REVIEW`, or `CHANGES_REQUESTED`. Absorbing across different customers, or with neither contract flagged as package-negotiated, is rejected with `ERR_COMBINATION_CRITERIA_NOT_MET` (HTTP 422); a signature gap beyond thirty days is rejected with `ERR_COMBINATION_WINDOW_EXCEEDED` (HTTP 409); and attempting absorption from any other lifecycle state fails as an invalid state transition. On absorption, the absorbed contract becomes `ABSORBED` with its `combined_into_contract_id` set to the survivor, every one of its obligations has its `contract_id` re-pointed to the survivor, the survivor's `fixed_consideration_cents` is increased by the absorbed contract's fixed consideration, the survivor's `transaction_price_cents` is recomputed, and the surviving contract's `version` is bumped.

Completion needs no human action. After every recognition, every invoice issue, and every invoice void affecting a contract, the system re-evaluates auto-completion: when every non-`CANCELLED` obligation is `SATISFIED` and `billed_to_date_cents` exactly equals `recognized_to_date_cents`, an `ACTIVE` contract moves to the terminal `COMPLETED` state and the server stamps `completed_at`. Any attempt to drive a contract through a transition that does not exist from its current state is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409).

### 3.5. Variable Consideration: Estimation, Constraint, and Approval

Variable consideration enters a contract only through a formal estimate. A `RevenueAccountant` may propose an estimate while the contract is `DRAFT`, `CHANGES_REQUESTED`, `APPROVED`, or `ACTIVE`, supplying the estimation `method` — `EXPECTED_VALUE` or `MOST_LIKELY` — and a `scenarios` array whose members each pair a `probability_bps` weight with an `amount_cents` outcome. The weights across the array must sum to exactly ten thousand basis points — one hundred percent — or the proposal is rejected with `ERR_SCENARIO_WEIGHTS` (HTTP 422).

The unconstrained amount depends on the method. Under `EXPECTED_VALUE`, `unconstrained_amount_cents` is the probability-weighted mean: each scenario's `amount_cents` is multiplied by its `probability_bps`, the products are summed, the sum is divided by ten thousand, and the quotient is rounded half up to whole cents. Under `MOST_LIKELY`, the system selects the single scenario with the greatest `probability_bps` — ties are broken by the earliest position in the array, and random ids never participate in the tie-break — and that scenario's `amount_cents` becomes the unconstrained amount, with every other scenario ignored. Identical scenario sets therefore generally yield different unconstrained amounts under the two methods.

The constraint then caps the includable amount by the contract's `risk_tier`: 85 percent for `STANDARD`, 70 percent for `ELEVATED`, and 50 percent for `HIGH`. The `constrained_amount_cents` is the smaller of the unconstrained amount and the unconstrained amount multiplied by the tier's cap and rounded down to whole cents. The comparison is inclusive: when the rounded-down cap term equals the unconstrained amount, the full unconstrained amount is includable. A new estimate starts `PROPOSED`, with `proposed_by_user_id` recorded from the creator's `X-User-ID` and `approved_by_user_id` null.

Approval, by a `RevenueManager`, moves the estimate `PROPOSED → APPROVED` under two guards. The approver must differ from `proposed_by_user_id` — segregation of duties, failing with `ERR_SOD_VIOLATION` — and, when the contract is `ACTIVE` and the reallocation would post catch-up entries, the period containing the current clock date must be `OPEN` or `REOPENED`, failing otherwise with `ERR_PERIOD_CLOSED`. The cascade on approval is wide. Any previously `APPROVED` estimate of the same contract becomes `SUPERSEDED`. The contract's `active_vc_estimate_id` is set to the newly approved estimate, its `vc_estimate_cents` becomes the estimate's `constrained_amount_cents`, its `transaction_price_cents` is recomputed as fixed plus variable, and the contract's `version` is bumped. When the contract is `APPROVED` or `ACTIVE`, the allocation waterfall of §3.4 re-runs over all non-`CANCELLED` obligations; when the contract is `ACTIVE`, the catch-up machinery of §3.8 additionally posts signed `CATCH_UP_ADJUSTMENT` entries with origin `ESTIMATE` for the obligations whose recognition target moved — subject to the over-recognition guard, which rejects the whole approval with `ERR_OVER_RECOGNITION` (HTTP 422) if any obligation would land with `allocated_amount_cents` below its `recognized_revenue_cents`, mutating nothing. Rejection, also by a `RevenueManager`, simply moves the estimate `PROPOSED → REJECTED`. The estimate list supports an optional `status` filter.

### 3.6. Recognition: Delivery Acceptance, Over-Time Progress, and Cost Entries

Recognition of every kind requires the owning contract to be `ACTIVE`; attempts against a contract in any other state — including `ON_HOLD` — fail with `ERR_CONTRACT_NOT_ACTIVE`. The pattern guard is symmetric: delivery acceptance applies only to `POINT_IN_TIME` obligations, while the recognize run and cost entries apply only to the two over-time patterns, and any mismatch is rejected with `ERR_RECOGNITION_PATTERN_FORBIDDEN` (HTTP 422). Every posting must land in a period that is `OPEN` or `REOPENED`; a posting date that falls in a `CLOSED` period — or in no defined period at all — is rejected with `ERR_PERIOD_CLOSED`.

Delivery acceptance moves a `POINT_IN_TIME` obligation from `PENDING` or `IN_PROGRESS` to `SATISFIED`. It posts a single `RECOGNITION` entry with origin `SATISFY` for the obligation's remaining allocated amount — `allocated_amount_cents` minus `recognized_revenue_cents` — at the current clock date, skipping the entry entirely when that remainder is zero; it stamps `satisfied_at`; and it re-evaluates contract auto-completion per §3.4.

Over-time recognition is driven by a progress ratio that is never rounded before use and never allowed to exceed one. For `OVER_TIME_INPUT_COST`, the ratio is `costs_incurred_to_date_cents` divided by `estimated_total_cost_cents`. For `OVER_TIME_STRAIGHT_LINE`, the total service length is the number of whole days between `service_start_date` and `service_end_date`; the elapsed length is the number of whole days between `service_start_date` and the earlier of the current logical clock date and `service_end_date`, clamped so it is never less than zero; and the ratio is the elapsed length divided by the total length. The recognition target is the obligation's `allocated_amount_cents` multiplied by the unrounded ratio, rounded half up to whole cents; the informational `progress_pct` is the ratio itself, rounded half up to six decimal places. When the ratio reaches exactly one — costs equal to the estimate, or the clock date on or after the service end date — the obligation flips to `SATISFIED`, `satisfied_at` is stamped, and auto-completion is re-evaluated; a cost total a single cent below the estimate does not satisfy the obligation.

The recognize run synchronizes one over-time obligation against the logical clock: it computes the target, and when the target exceeds `recognized_revenue_cents` it posts one `RECOGNITION` entry with origin `RECOGNIZE` for the difference into the period containing the clock date; when the difference is zero the run is a no-op. Recording a cost against an input-cost obligation takes an `amount_cents` greater than zero, an `incurred_date` that must fall in an `OPEN` or `REOPENED` period, and an optional free-text `memo`. The cost is added to `costs_incurred_to_date_cents`, the input-cost ratio is recomputed, and when the recognition target advanced, one `RECOGNITION` entry with origin `COST_ENTRY` posts for the difference — cost-driven entries post at the cost's `incurred_date`, whereas every other entry posts at the current logical clock date.

Every revenue entry records its `contract_id`, its `pob_id`, and the `accounting_period_id` of the period containing its `posting_date`; an `entry_type` of `RECOGNITION`, `CATCH_UP_ADJUSTMENT`, or `REVERSAL`; a signed `amount_cents`; the `posting_date` itself; an `origin` of `COST_ENTRY`, `RECOGNIZE`, `SATISFY`, `MODIFICATION`, `ESTIMATE`, or `REVERSAL`; and a `status` that starts `POSTED` and becomes `LOCKED` when its containing period closes (§3.9). The first `RECOGNITION` or `CATCH_UP_ADJUSTMENT` entry posted for an obligation moves it from `PENDING` to `IN_PROGRESS` automatically. Because entries are append-only, an obligation's `recognized_revenue_cents` is always derivable as the signed sum of its `POSTED` and `LOCKED` entries, and a period's `recognized_total_cents` as the signed sum of its own `POSTED` and `LOCKED` entries.

### 3.7. Billing, Reversals, and the Balance Rollforward

Billing is the second measure of the dual-ledger. A `RevenueAccountant` issues an invoice against an `ACTIVE` contract — any other contract state fails with `ERR_CONTRACT_NOT_ACTIVE` — supplying an `invoice_ref` unique per invoice, an `amount_cents` greater than zero, and an `invoice_date` that must fall inside an `OPEN` or `REOPENED` accounting period, failing with `ERR_PERIOD_CLOSED` otherwise. Non-positive amounts fail with `ERR_INVALID_AMOUNT`. One fiscal ceiling applies at issue time: the cumulative total of issued, non-voided billings may not exceed the contract's current `transaction_price_cents`, and an invoice that would push billings past the price is rejected with `ERR_BILLING_EXCEEDS_PRICE` (HTTP 422). An invoice is created directly in `ISSUED` status; issuing adds the amount to the contract's `billed_to_date_cents`, recomputes the deferred-revenue and contract-asset balances of §2.11, re-evaluates auto-completion, and bumps the contract's `version`.

Voiding is the manager-side correction. A `RevenueManager` voids an `ISSUED` invoice, moving it to the terminal `VOIDED` state; the period containing the current clock date must be `OPEN` or `REOPENED`, failing with `ERR_PERIOD_CLOSED` otherwise. Voiding subtracts the invoice's amount from `billed_to_date_cents`, recomputes both balances, records `voided_by_user_id` from the caller's `X-User-ID`, re-evaluates auto-completion, and bumps the contract's `version`.

The correction path for revenue entries is the reversal. A `RevenueAccountant` may post a compensating entry against any entry still `POSTED`; reversing an entry whose period has already closed — and whose status is therefore `LOCKED` — is rejected with `ERR_ENTRY_LOCKED` (HTTP 409). The reversal takes an optional `reason` and creates a new revenue entry with `entry_type` `REVERSAL`: its `amount_cents` is the exact negation of the reversed entry's amount, its `reversed_entry_id` points at the reversed entry, its `posting_date` is the current clock date, and its `origin` is `REVERSAL`. Posting a reversal recomputes the contract and period aggregates, re-evaluates auto-completion, and bumps the contract's `version`. The entry list supports optional `contract_id`, `pob_id`, `accounting_period_id`, `entry_type`, and `reversed_entry_id` filters.

The per-period rollforward read answers, for one contract and a supplied `accounting_period_id`, how the two measures moved within that period. Movements are attributed by effective date: an invoice contributes its amount positively in the period containing its `invoice_date`; a void contributes the amount negatively in the period containing the void's clock date; each revenue entry contributes its signed amount in the period containing its `posting_date`. The response carries `contract_id` and `accounting_period_id`; the beginning balances `beginning_billed_cents` and `beginning_recognized_cents`, which accumulate every movement whose effective date precedes the period's `start_date`; the period's own movements `billed_cents` and `recognized_cents`; the portions of the period's recognized movement contributed by catch-up adjustments and reversals as `catch_up_cents` and `reversal_cents`; and the ending figures `ending_billed_cents`, `ending_recognized_cents`, `ending_deferred_revenue_cents`, and `ending_contract_asset_cents`. The ending balances combine the beginning balances with the period's movements, and the ending deferred-revenue and contract-asset figures derive from the ending billed and recognized totals under the same floored-difference formulas of §2.11.

### 3.8. Contract Modifications

A signed deal changes through a formal modification. A `RevenueAccountant` proposes one against an `ACTIVE` contract — any other state fails with `ERR_CONTRACT_NOT_ACTIVE` — supplying the `mod_type` (`CUMULATIVE_CATCH_UP`, `PROSPECTIVE`, or `SEPARATE_CONTRACT`), the signed `delta_fixed_consideration_cents` (which must not be zero, failing with `ERR_INVALID_AMOUNT` when it is), the business `effective_date`, the concurrency field `expected_contract_version` of §2.7 (a stale value fails with `ERR_STALE_VERSION`, HTTP 412), and an optional free-text `reason`. A new modification starts `PROPOSED` with `proposed_by_user_id` recorded and `spawned_contract_id` null, and — because proposing a modification is itself a contract mutation — the act of proposing bumps the contract's `version`. Several proposals may therefore coexist against the same contract; what the concurrency guard forbids is proposing from an outdated read of it.

Approval by a `RevenueManager` is where the accounting treatment diverges by type, under two guards common to all three: the owning contract must still be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), and the approver's `X-User-ID` must differ from `proposed_by_user_id` (`ERR_SOD_VIOLATION`). Every approval also records `approved_by_user_id` and bumps the contract's `version`.

For `CUMULATIVE_CATCH_UP`, the period containing the current clock date must be `OPEN` or `REOPENED` (`ERR_PERIOD_CLOSED`), and the evaluation order is pinned so the circular-looking dependency is well-defined. First the delta is applied: `fixed_consideration_cents` is increased by `delta_fixed_consideration_cents`, and `transaction_price_cents` is recomputed. Second, the allocation waterfall of §3.4 re-runs over all non-`CANCELLED` obligations, redistributing the whole new transaction price. Third, the over-recognition guard: if any obligation would land with `allocated_amount_cents` below its `recognized_revenue_cents`, the entire approval is rejected with `ERR_OVER_RECOGNITION` and no field is mutated. Fourth, each over-time obligation's ratio is recomputed per §3.6 from its current costs and the current clock — costs and dates do not change in this step. Fifth, each obligation's target is recomputed as its new allocated amount multiplied by its ratio, rounded half up to whole cents. Sixth, the catch-up for each obligation is its target minus its `recognized_revenue_cents`. Seventh, one `CATCH_UP_ADJUSTMENT` entry with origin `MODIFICATION`, posting at the current clock date, is written per obligation whose catch-up is non-zero; obligations whose target did not move receive no entry.

For `PROSPECTIVE`, at least one obligation must still be `PENDING` to receive the delta, failing otherwise with `ERR_NO_PENDING_POB` (HTTP 422). The delta is applied to `fixed_consideration_cents` and the transaction price recomputed exactly as above, but the distribution is narrower: only the delta is allocated, and only across `PENDING` obligations, pro-rata by their pinned `ssp_cents` — each share rounded half up to whole cents in `created_at` ascending order, the residual going to the `PENDING` obligation with the greatest `ssp_cents` (ties by earliest `created_at`). The shares are added onto the obligations' existing allocated amounts; amounts already recognized are untouched, and no catch-up entries are posted.

For `SEPARATE_CONTRACT`, the original contract is left unchanged. Instead, approval creates a new contract in `DRAFT` for the same `customer_id`, with `signed_date` equal to the modification's `effective_date`, `fixed_consideration_cents` equal to the delta, and `risk_tier` copied from the original; the modification's `spawned_contract_id` is set to the new contract. Rejection, also by a `RevenueManager`, simply moves the modification `PROPOSED → REJECTED`.

### 3.9. The Accounting Calendar and Period-End Disclosure

The ledger calendar belongs to the `Controller`. An accounting period is created with a unique `period_code` (for example, 2026-06), a `start_date`, and an `end_date` that must come after the start. Period windows are half-open: a period covers every date from its `start_date` up to but not including its `end_date`. No two periods may overlap — though adjacency is allowed, so one period's `start_date` may equal another's `end_date` — and an overlapping creation is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409). A new period starts `OPEN` with `reopened_once` false and `recognized_total_cents` zero, the latter tracking the signed sum of the period's `POSTED` and `LOCKED` entries as they post.

Closing moves a period from `OPEN` or `REOPENED` to `CLOSED` and locks its contents: every revenue entry with a `posting_date` inside the period and status `POSTED` becomes `LOCKED`, after which it can no longer be reversed (§3.7). Reopening is the controlled exception, moving a period `CLOSED → REOPENED`, and it is allowed at most once per period and only while no later period — one whose `start_date` comes after this period's — is `CLOSED`; either violation is rejected with `ERR_PERIOD_REOPEN_LIMIT` (HTTP 409). Reopening sets `reopened_once` to true and cascades into disclosures: every `FINALIZED` disclosure pack of the period becomes `SUPERSEDED`, and for each pack superseded this way the system auto-creates one replacement pack for the same period, starting in `DRAFT`.

Disclosure packs assemble a period's reporting figures. A `RevenueAccountant` creates a pack for a period in `DRAFT`; its six figures — `rpo_cents`, `period_revenue_cents`, `revenue_by_region`, `revenue_by_product`, `contract_asset_total_cents`, and `deferred_revenue_total_cents` — stay null until assembly. Assembling moves the pack `DRAFT → ASSEMBLED`, records `assembled_by_user_id`, and computes the figures from a precisely filtered input set. The entry set is every revenue entry with status `POSTED` or `LOCKED` whose `posting_date` falls inside the period's half-open window. The `period_revenue_cents` is the signed sum of that set; `revenue_by_region` maps each region to the sum over the same set of amounts whose obligations carry that `region`, and `revenue_by_product` does the same by `product_code`. The remaining-performance-obligation figure `rpo_cents` sums, over obligations in `PENDING` or `IN_PROGRESS` whose contracts are `ACTIVE` or `ON_HOLD`, each obligation's `allocated_amount_cents` minus its `recognized_revenue_cents`. The `contract_asset_total_cents` and `deferred_revenue_total_cents` sum the per-contract `contract_asset_balance_cents` and `deferred_revenue_balance_cents` over contracts in `ACTIVE`, `ON_HOLD`, or `COMPLETED` at assembly time. Contracts in `DRAFT`, `IN_REVIEW`, `CHANGES_REQUESTED`, `APPROVED`, `CANCELLED`, or `ABSORBED` contribute nothing to any figure.

Finalization, by a `Controller`, moves an `ASSEMBLED` pack to `FINALIZED` under two guards: the pack's accounting period must be `CLOSED` — failing with `ERR_PACK_PERIOD_NOT_CLOSED` (HTTP 409) while the period is anything else — and the finalizer's `X-User-ID` must differ from `assembled_by_user_id`, the segregation-of-duties rule of §2.10, failing with `ERR_SOD_VIOLATION`. Finalization records `finalized_by_user_id`. A `FINALIZED` pack later becomes `SUPERSEDED` automatically if its period is reopened, as described above; `SUPERSEDED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, a contract, an obligation, an estimate, a modification, a clause, an invoice, a cost entry, a period, a reversal entry, a disclosure pack, or a price record — return `201 Created`. Operations that modify an existing resource, including every state transition, and all read endpoints return `200 OK`. In the table below, a role cell reading "All business roles" admits `RevenueAccountant`, `RevenueManager`, `ContractReviewer`, and `Controller`; `SystemAdmin` is excluded from every business endpoint. Request bodies, response payloads, and side effects are defined by the narratives of §3 and are intentionally not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/revrec/customers` | Create a customer | RevenueAccountant |
| GET | `/revrec/customers/{customer_id}` | Get a customer | All business roles |
| POST | `/revrec/contracts` | Create a contract in DRAFT | RevenueAccountant |
| GET | `/revrec/contracts` | List contracts with pagination | All business roles |
| GET | `/revrec/contracts/{contract_id}` | Get a contract | All business roles |
| POST | `/revrec/contracts/{contract_id}/submit` | Submit for review; spawns a review task per non-standard clause still pending review | RevenueAccountant |
| POST | `/revrec/contracts/{contract_id}/return` | Return for changes | RevenueManager |
| POST | `/revrec/contracts/{contract_id}/approve` | Approve pricing/allocation; pins the SSP snapshot and runs the allocation waterfall | RevenueManager |
| POST | `/revrec/contracts/{contract_id}/activate` | Activate an APPROVED contract | RevenueManager |
| POST | `/revrec/contracts/{contract_id}/hold` | Place an ACTIVE contract ON_HOLD | RevenueManager |
| POST | `/revrec/contracts/{contract_id}/resume` | Resume an ON_HOLD contract | RevenueManager |
| POST | `/revrec/contracts/{contract_id}/cancel` | Cancel a contract in DRAFT, IN_REVIEW, or CHANGES_REQUESTED | RevenueAccountant |
| POST | `/revrec/contracts/{contract_id}/absorb` | Combination assessment: absorb another pre-approval contract of the same customer into this surviving contract | RevenueManager |
| POST | `/revrec/contracts/{id}/pobs` | Add a performance obligation while the contract is DRAFT or CHANGES_REQUESTED | RevenueAccountant |
| GET | `/revrec/contracts/{id}/pobs` | List performance obligations of a contract | All business roles |
| GET | `/revrec/pobs/{pob_id}` | Get a performance obligation | All business roles |
| POST | `/revrec/pobs/{pob_id}/satisfy` | Accept delivery of a POINT_IN_TIME obligation | RevenueAccountant |
| POST | `/revrec/pobs/{pob_id}/recognize` | Sync over-time recognition for one obligation against the logical clock | RevenueAccountant |
| POST | `/revrec/pobs/{id}/cost-entries` | Record incurred cost for an OVER_TIME_INPUT_COST obligation | RevenueAccountant |
| GET | `/revrec/pobs/{id}/cost-entries` | List cost entries of an obligation | All business roles |
| POST | `/revrec/contracts/{id}/vc-estimates` | Propose a variable consideration estimate | RevenueAccountant |
| GET | `/revrec/contracts/{id}/vc-estimates` | List variable consideration estimates of a contract | All business roles |
| POST | `/revrec/vc-estimates/{estimate_id}/approve` | Approve an estimate; supersedes the prior approved estimate; reallocates and posts catch-up entries where due | RevenueManager |
| POST | `/revrec/vc-estimates/{estimate_id}/reject` | Reject a PROPOSED estimate | RevenueManager |
| POST | `/revrec/contracts/{id}/modifications` | Propose a modification against an ACTIVE contract (OCC-guarded on the contract's version) | RevenueAccountant |
| GET | `/revrec/contracts/{id}/modifications` | List modifications of a contract | All business roles |
| POST | `/revrec/modifications/{modification_id}/approve` | Approve a PROPOSED modification; applies the accounting treatment for its type | RevenueManager |
| POST | `/revrec/modifications/{modification_id}/reject` | Reject a PROPOSED modification | RevenueManager |
| POST | `/revrec/contracts/{id}/clauses` | Record a contract clause while the contract is DRAFT or CHANGES_REQUESTED | RevenueAccountant |
| GET | `/revrec/contracts/{id}/clauses` | List clauses of a contract | All business roles |
| GET | `/revrec/review-tasks` | List review tasks with pagination | All business roles |
| GET | `/revrec/review-tasks/{task_id}` | Get a review task | All business roles |
| POST | `/revrec/review-tasks/{task_id}/start` | Claim an ASSIGNED review task | ContractReviewer |
| POST | `/revrec/review-tasks/{task_id}/recommend` | Submit a recommendation; only the claiming reviewer | ContractReviewer |
| POST | `/revrec/review-tasks/{task_id}/decide` | Decide a RECOMMENDED task; APPROVED/REJECTED finalize the clause, RETURN loops back for rework | ContractReviewer |
| POST | `/revrec/contracts/{id}/invoices` | Issue an invoice against an ACTIVE contract | RevenueAccountant |
| GET | `/revrec/contracts/{id}/invoices` | List invoices of a contract | All business roles |
| POST | `/revrec/invoices/{invoice_id}/void` | Void an ISSUED invoice | RevenueManager |
| POST | `/revrec/accounting-periods` | Create an accounting period; half-open windows must not overlap (adjacency allowed) | Controller |
| GET | `/revrec/accounting-periods/{period_id}` | Get an accounting period | All business roles |
| POST | `/revrec/accounting-periods/{period_id}/close` | Close an OPEN or REOPENED period; locks its POSTED revenue entries | Controller |
| POST | `/revrec/accounting-periods/{period_id}/reopen` | Reopen a CLOSED period (at most once, and only when no later period is CLOSED) | Controller |
| GET | `/revrec/revenue-entries` | List revenue entries with pagination | All business roles |
| GET | `/revrec/revenue-entries/{entry_id}` | Get a revenue entry | All business roles |
| POST | `/revrec/revenue-entries/{entry_id}/reverse` | Post a compensating REVERSAL entry against a POSTED entry | RevenueAccountant |
| POST | `/revrec/accounting-periods/{id}/disclosure-packs` | Create a DRAFT disclosure pack for a period | RevenueAccountant |
| GET | `/revrec/accounting-periods/{id}/disclosure-packs` | List disclosure packs of a period | All business roles |
| POST | `/revrec/disclosure-packs/{pack_id}/assemble` | Assemble disclosure data | RevenueAccountant |
| POST | `/revrec/disclosure-packs/{pack_id}/finalize` | Finalize an ASSEMBLED pack; period must be CLOSED; finalizer must differ from assembler | Controller |
| POST | `/revrec/ssp-prices` | Create an ACTIVE standalone-selling-price record; closed windows of the same product-and-region pair must not overlap or touch | RevenueManager |
| POST | `/revrec/ssp-prices/{ssp_id}/retire` | Retire an ACTIVE price record | RevenueManager |
| GET | `/revrec/contracts/{contract_id}/rollforward` | Contract asset/liability and deferred revenue rollforward for one period | All business roles |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default is exactly 2026-05-01T00:00:00Z) | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_TASK_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENTRY_LOCKED` | 409 Conflict |
| `ERR_PACK_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_REVIEW_OUTSTANDING` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 409 Conflict |
| `ERR_PERIOD_CLOSED` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_PERIOD_REOPEN_LIMIT` | 409 Conflict |
| `ERR_SSP_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COMBINATION_WINDOW_EXCEEDED` | 409 Conflict |
| `ERR_SCENARIO_WEIGHTS` | 422 Unprocessable Entity |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_RECOGNITION_PATTERN_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_NO_PENDING_POB` | 422 Unprocessable Entity |
| `ERR_SSP_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_COMBINATION_CRITERIA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_OVER_RECOGNITION` | 422 Unprocessable Entity |
| `ERR_BILLING_EXCEEDS_PRICE` | 422 Unprocessable Entity |
