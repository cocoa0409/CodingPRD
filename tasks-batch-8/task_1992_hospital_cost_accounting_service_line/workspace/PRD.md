# Hospital Cost Accounting API — Product Requirements Document

## 1. Introduction

A hospital's finance office can usually answer "what did we spend last quarter" far more easily than "which service lines, surgeons, DRGs, and payers actually made money." Costs hide inside shared overhead pools; two allocation philosophies — time-driven activity-based costing and relative-value-unit costing — produce divergent answers from identical data; and a mid-quarter rate refresh silently invalidates every margin computed under the old rates. Service-line expansion, contract negotiation, and physician-practice decisions end up resting on numbers nobody can reproduce.

The Hospital Cost Accounting API exists to make service-line economics explicit, reproducible, and auditable. It maintains the reference estate of a costing program — service lines, cost centers, physicians, DRG definitions, and payer contracts — and prices individual patient cases under governed cost models that classify every pool as direct, indirect, or overhead and as fixed or variable. Posting a case runs a pinned costing pipeline whose per-line rounding and single-step overhead distribution are fully specified, so two honest implementations given the same inputs arrive at the same penny-level result. Overhead budgets flex with actual volume across three tiers, margins roll up from cases to service lines inside the same request that causes them, and a guarded refresh cycle re-prices in-flight work when general-ledger rates move. A strict approval chain separates the analyst who builds from the controller who approves and locks. All resources are mounted under `/cost-accounting`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representational contracts, and cross-cutting principles that apply uniformly to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. The system recognizes exactly three roles, spelled precisely as `CostAnalyst`, `FinanceController`, and `ServiceLineManager`. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`; the per-endpoint role assignments appear in §4.

The roles divide the work along an approval chain. A `CostAnalyst` builds the costing world: drafting cost models, registering cases, attaching activity lines, implants, and supply lines, proposing model refreshes, and posting or voiding cases. A `FinanceController` owns the reference estate — service lines, cost centers, physicians, DRG definitions, payer contracts, and budget periods — and alone may approve or archive models, approve, reject, or apply refreshes, and lock cases and budget periods. A `ServiceLineManager` is a read-only consumer of entity data and reports. For all three roles — `CostAnalyst`, `FinanceController`, and `ServiceLineManager` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes, but it never compares the header value to any resource's `id`, and no ownership check is derived from it.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Append-Only Ledger Lines

Every primary resource — service lines, cost centers, physicians, DRG definitions, cost models, cost-model refreshes, cases, implants, payer contracts, and budget periods — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource.

A modification is any change to the resource's stored state, including changes driven indirectly by cascades. When posting a case refreshes a service line's rollup fields, the service line's `updated_at` moves and its `version` increments; the same holds when a budget period is recomputed or a cost model's `version` is advanced by an approval or a refresh application.

Two resource kinds are deliberately different. **Activity cost lines** and **supply lines** are append-only ledger lines: they carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them, because a ledger line, once written, is never modified — re-pricing regenerates the line's computed content rather than versioning it.

### 2.5. Monetary Precision and Rounding Discipline

Every computed monetary figure in the system — line allocations, case totals, service-line rollups, flexed overhead amounts, variance figures, report averages, and percentage deltas — is expressed at exactly two decimal places using round-half-up. Where a pipeline produces several intermediate amounts (notably the case-costing pipeline of §3.4), each line-level amount is rounded half-up to two decimal places individually, before any summation takes place; summing unrounded raw values and rounding once at the end is forbidden. Input amounts and rates supplied by clients are persisted exactly as supplied.

### 2.6. Cost Classification and the Two Allocation Bases

Each cost center is classified on two independent axes. Its `cost_type` is one of `DIRECT`, `INDIRECT`, or `OVERHEAD`, describing where the pool sits relative to patient care. Its `cost_behavior` is one of `FIXED` or `VARIABLE`, describing how the pool responds to volume. A cost center also declares a `capacity_measure` of `MINUTES`, `RVU`, or `NONE`; `NONE` is valid only for a center whose `cost_type` is `OVERHEAD`. The measure governs which denominator the center must carry: a center measured in `MINUTES` must supply `practical_capacity_minutes` greater than zero and must not carry `total_rvu`; a center measured in `RVU` must supply `total_rvu` greater than zero and must not carry `practical_capacity_minutes`; a center measured `NONE` carries neither.

A cost model chooses how activity is priced through its `allocation_basis`, either `TDABC` or `RVU`. Under `TDABC`, activity quantities are interpreted as minutes of capacity consumed and each center is rated against its practical capacity in minutes. Under `RVU`, the same quantities are interpreted as relative value units and each center is rated against its total RVU denominator. The two bases are not cosmetic variants: identical financial data costs differently under them, which is precisely why the choice of basis is a governed attribute of the model rather than a report-time switch. The model's `rate_factor` — a non-negative multiplier such as 1.20 — scales every capacity rate the model applies.

### 2.7. Accounting Periods and Effective Windows

All accounting periods in the API are strings in `YYYY-MM` format; a period value that does not match this shape is rejected with `ERR_INVALID_PERIOD_FORMAT`. The `effective_period` on a cost model is the first period the model prices, and the `effective_period` on a payer contract is the first period the contract applies. A case's `period` must never precede the `effective_period` of the cost model that prices it — a violation is rejected with `ERR_CASE_PERIOD_BEFORE_MODEL` — and this window is verified both when the case is created and again when it is posted. A payer contract is eligible to explain a case's reimbursement only when the contract's `effective_period` is on or before the case's `period`.

### 2.8. Ledger Synchronization: Rollups, Compensation, and Recompute Cascades

A service line is more than a label — it is a ledger. Three computed fields are maintained on every service line. `total_direct_cost` is the line's `base_direct_cost` plus the sum of `total_indirect_allocated` across all `POSTED` cases of the line, across all periods. `total_revenue` is the sum of `expected_reimbursement` across those same `POSTED` cases. `contribution_margin` is `total_revenue` minus `total_direct_cost`. These fields are not recomputed lazily on read; they are synchronized eagerly by the events that change them.

Events propagate in hops, and every cascade commits inside the triggering request — there is no asynchronous settlement. Posting a case adds the case's contribution to its service line's rollups (hop 1) and recomputes the affected budget period's flex position (hop 2). Applying a cost-model refresh recomputes the affected cases, then refreshes each recomputed case's service-line rollups, then recomputes each affected budget period (hop 3). Voiding a posted case is a compensation, not a deletion: the service line's `total_direct_cost`, `total_revenue`, and `contribution_margin` are reduced by exactly the contribution the case previously added, and the budget period's actual volume is reduced with its flex and variance recomputed.

Voided cases follow a soft-deletion discipline. A `VOIDED` case remains stored and individually retrievable — including its activity lines, implants, and supply lines — but it is excluded from every rollup, aggregate, and report, as if it had never been posted.

### 2.9. Optimistic Concurrency Control on Model-Priced Writes

Exactly two write operations in the API are guarded by optimistic concurrency control, and both guard the same parent: the governing cost model. Posting a case and approving a cost-model refresh each require the request to carry `expected_model_version`, set to the `version` of the target cost model as the client last observed it. If that value no longer matches the model's current `version` — because another writer has advanced the model in the meantime, whether by approving a model, applying an earlier refresh, or any other version-advancing mutation — the request is rejected with `ERR_STALE_MODEL_VERSION` and HTTP status 412, and no change is applied. The rule is purely one of stale observation: pricing a case against, or gating a refresh on, a model the client has not actually seen is forbidden. Endpoints other than these two do not accept a version field at all.

### 2.10. Validation Order

Every mutating request is validated against a fixed, ordered sequence of rule families, and when several violations coexist the earliest family's error is the one returned. The order is:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization** — the declared role must be permitted on the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence** — path identifiers are validated first, strictly left to right, and only then are foreign keys in the request body checked, in their declared input order; the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`. A request aimed at a child collection of a parent that does not exist therefore fails on the parent before any child handling begins.
4. **Target state** — the addressed resource must be in the state the transition requires (posting requires a `DRAFT` case, refresh approval requires a `PROPOSED` refresh, case locking requires a `POSTED` case, and so on), else `ERR_INVALID_STATE`.
5. **Parent aggregate active** — the referenced service line must be `ACTIVE` when a model is approved or a case is created (`ERR_SERVICE_LINE_NOT_ACTIVE`), and the referenced cost model must be `ACTIVE` when a case is posted or a refresh is approved (`ERR_MODEL_NOT_ACTIVE`).
6. **Cross-reference structural validity** — overhead pools must be `ACTIVE` centers of `cost_type` `OVERHEAD` (`ERR_OVERHEAD_CENTER_INVALID`), activity-line centers must be eligible (`ERR_ACTIVITY_CENTER_INVALID`), supersession targets must be valid (`ERR_SUPERSEDE_TARGET_INVALID`), case physicians must be `ACTIVE` (`ERR_PHYSICIAN_NOT_ACTIVE`), and the case period must respect the model's window (`ERR_CASE_PERIOD_BEFORE_MODEL`).
7. **Refresh governance gates** — variance and data-quality thresholds for refresh approval (`ERR_REFRESH_VARIANCE_EXCEEDED`, `ERR_DATA_QUALITY_TOO_LOW`).
8. **Completeness and freshness constraints** — `ERR_CASE_NO_ACTIVITY`, `ERR_CASE_STALE_MODEL`, `ERR_PERIOD_HAS_STALE_CASES`, `ERR_SERVICE_LINE_HAS_OPEN_CASES`, `ERR_SERVICE_LINE_HAS_ACTIVE_MODEL`, `ERR_MODEL_HAS_OPEN_CASES`, `ERR_MODEL_HAS_OPEN_REFRESH`, `ERR_COST_CENTER_IN_USE`, and `ERR_PHYSICIAN_HAS_OPEN_CASES`.
9. **Temporal windowing** — budget-period uniqueness and period windows (`ERR_DUPLICATE_BUDGET_PERIOD`, `ERR_CASE_PERIOD_BEFORE_MODEL`, `ERR_INVALID_PERIOD_FORMAT`).
10. **Numeric sanity and enum validity** — missing required fields, type mismatches, invalid enum values, and non-positive numbers where a positive value is required all surface as `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. The Reference Estate: Service Lines, Cost Centers, Physicians, DRGs, and Payer Contracts

A `FinanceController` begins by establishing the reference estate. A **service line** is created with a `name` (for example, "Orthopedic Surgery"), a `code` that must be unique across all service lines (for example, "ORTHO"), a non-negative `base_direct_cost` representing the direct fixed-cost baseline allocated to the line each period, and a `budgeted_volume`, an integer greater than zero expressing the budgeted case volume per period. A new service line starts in `ACTIVE` status with its computed rollup fields — `total_direct_cost`, `total_revenue`, and `contribution_margin` — initialized to zero; thereafter the ledger rules of §2.8 take over, under which `total_direct_cost` is the line's `base_direct_cost` plus the allocated indirect totals of its posted cases. The service-line list may be filtered by `status`.

A **cost center** is created with a `name`, a unique `code`, the classification pair `cost_type` and `cost_behavior`, an `allocated_cost` greater than zero representing the period cost pool assigned to the center, a `capacity_measure`, and — exactly as §2.6 requires — `practical_capacity_minutes` or `total_rvu` when the measure calls for one. Centers start `ACTIVE`. The cost-center list may be filtered by `status` and by `cost_type`.

A **physician** is registered with an `npi` (the National Provider Identifier, unique across physicians), a `full_name`, and a `specialty` label such as "Orthopedics", and starts `ACTIVE`. A **DRG definition** carries a unique `drg_code` (for example, "470"), a free-text `description`, a non-negative `target_cost` expressing the target fully-allocated indirect cost per case, and a non-negative `base_rate`, the DRG's base reimbursement rate. A **payer contract** is created against a service line with a `payer_name` (for example, "Medicare"), a `payer_type` of `MEDICARE`, `MEDICAID`, `COMMERCIAL`, or `SELF_PAY`, a `contracted_rate` greater than zero expressing the expected payment per case, and an `effective_period`. Contracts start `ACTIVE`; the payer-contract list may be filtered by `service_line_id` and `status`.

Reference data retires under guard rails. Archiving a service line — a `FinanceController` action moving it from `ACTIVE` to `ARCHIVED` — is refused with `ERR_SERVICE_LINE_HAS_OPEN_CASES` while any case of the line is still in `DRAFT` or `POSTED` (only lines whose cases are all `LOCKED` or `VOIDED` may archive), and refused with `ERR_SERVICE_LINE_HAS_ACTIVE_MODEL` while any cost model of the line remains `ACTIVE`. When archival succeeds, every `ACTIVE` cost model of the line transitions to `ARCHIVED` and every `ACTIVE` payer contract of the line transitions to `TERMINATED`, and the line's `version` increments. Archiving a cost center is refused with `ERR_COST_CENTER_IN_USE` when any cost model other than a `SUPERSEDED` or `ARCHIVED` one references the center as its overhead pool, or when any activity line on a `DRAFT` or `POSTED` case references it. A physician may be deactivated — `ACTIVE` to `INACTIVE` — only while no `DRAFT` or `POSTED` case references them, else `ERR_PHYSICIAN_HAS_OPEN_CASES`; reactivation returns an `INACTIVE` physician to `ACTIVE` without preconditions. Creating a case against an `INACTIVE` physician is rejected with `ERR_PHYSICIAN_NOT_ACTIVE`.

### 3.2. Cost Models: Drafting, Approval, and Supersession

A `CostAnalyst` drafts a **cost model** by naming it (`name`, for example "ORTHO-STD"), binding it to a service line via `service_line_id`, choosing the `allocation_basis` (`TDABC` or `RVU`), setting the `rate_factor` multiplier, designating the overhead pool via `overhead_cost_center_id`, and declaring the `effective_period` from which the model prices. An optional `supersedes_model_id` names the model this one will replace upon approval. A new model is born in `DRAFT` status.

Structural validity is enforced at drafting time and re-verified at approval time. The center named by `overhead_cost_center_id` must be an `ACTIVE` cost center whose `cost_type` is `OVERHEAD`; anything else is rejected with `ERR_OVERHEAD_CENTER_INVALID`. When `supersedes_model_id` is present, it must reference a model that is currently `ACTIVE` and belongs to the same `service_line_id`; otherwise the request fails with `ERR_SUPERSEDE_TARGET_INVALID`.

Approval is the `FinanceController`'s gate and moves the model `DRAFT → ACTIVE`. Three preconditions guard it: the referenced service line must be `ACTIVE` (else `ERR_SERVICE_LINE_NOT_ACTIVE`); the overhead-pool rule above must still hold (else `ERR_OVERHEAD_CENTER_INVALID`); and the supersession target, if any, must still be an `ACTIVE` model of the same service line (else `ERR_SUPERSEDE_TARGET_INVALID`). Upon approval the named supersession target transitions to `SUPERSEDED`, and the newly approved model's `version` increments by one. A `DRAFT` model may be archived without preconditions. An `ACTIVE` model may be archived only when no `DRAFT` or `POSTED` case references it (else `ERR_MODEL_HAS_OPEN_CASES`) and no `PROPOSED` or `APPROVED` refresh references it (else `ERR_MODEL_HAS_OPEN_REFRESH`). The model list may be filtered by `status`, `service_line_id`, `overhead_cost_center_id`, and `supersedes_model_id`.

### 3.3. Capturing a Case: Activity Lines, Implants, and Supplies

Case capture is the `CostAnalyst`'s daily work. A **case** is registered with the service line it belongs to (`service_line_id`), the attending surgeon (`physician_id`), its diagnosis-related group (`drg_id`), the model that will price it (`cost_model_id`), the service `period`, and the `expected_reimbursement` — the expected net revenue for the case, zero or greater. Creation demands a coherent bundle: the service line must be `ACTIVE` (else `ERR_SERVICE_LINE_NOT_ACTIVE`), the physician must be `ACTIVE` (else `ERR_PHYSICIAN_NOT_ACTIVE`), the cost model must be `ACTIVE` and must belong to the same service line as the case's `service_line_id`, and the `period` must be well-formed and no earlier than the model's `effective_period` (else `ERR_INVALID_PERIOD_FORMAT` or `ERR_CASE_PERIOD_BEFORE_MODEL`). A new case starts in `DRAFT` with its computed totals — `total_direct_cost`, `total_indirect_allocated`, `total_cost`, and `margin` — all initialized to zero. The case list may be filtered by `status`, `service_line_id`, `physician_id`, `drg_id`, `period`, and `cost_model_id`.

While the case remains `DRAFT`, the analyst builds its cost footprint line by line; attempting to add any line to a case that has left `DRAFT` is rejected with `ERR_INVALID_STATE`.

Every line an analyst attaches is bound to its case through a `case_id` recorded on the line itself. Three kinds of lines may be added:

- An **activity cost line** names a `cost_center_id` and a `quantity` greater than zero — minutes consumed for a minutes-measured center, RVU amount for an RVU-measured center. The referenced center must be `ACTIVE` and of `cost_type` `INDIRECT` or `OVERHEAD`; a `DIRECT` or archived center is rejected with `ERR_ACTIVITY_CENTER_INVALID`, as is a center whose `capacity_measure` does not match the basis of the case's model (a `TDABC` model prices minutes-measured centers, an `RVU` model prices RVU-measured centers). When the line's center is the model's own overhead pool, the line is flagged with `is_overhead_line` set to true; the flag defaults to false. The line's `allocated_amount` is computed when the case is posted and remains zero until then. Activity lines are append-only ledger lines (§2.4). They can be listed per case, and — for reverse reachability during center audits — all activity lines referencing a given cost center can be listed from the center side as well.
- An **implant** records an `item_code` from the implant catalog, a `vendor`, a `unit_cost` greater than zero, and an integer `quantity` of units implanted, also greater than zero. Implants carry the full common field set, including `updated_at` and `version`.
- A **supply line** records a `supply_code`, a `unit_cost` greater than zero, and an integer `quantity` greater than zero. Supply lines are append-only ledger lines (§2.4).

### 3.4. Posting, Voiding, and Locking: The Pinned Costing Pipeline

Posting turns a `DRAFT` case into a priced, ledger-visible `POSTED` case. The `CostAnalyst` who posts must carry `expected_model_version` matching the current `version` of the case's cost model, per the OCC rule of §2.9; a stale observation is rejected with `ERR_STALE_MODEL_VERSION` (HTTP 412). Three further preconditions guard the transition: at least one activity cost line must exist for the case (else `ERR_CASE_NO_ACTIVITY`); the case's `period` must not precede the model's `effective_period` (else `ERR_CASE_PERIOD_BEFORE_MODEL`); and the model must be `ACTIVE` (else `ERR_MODEL_NOT_ACTIVE`).

When the gate passes, the system prices the case through a seven-step pipeline whose evaluation order is pinned and must not be rearranged:

1. Each non-overhead activity line is priced individually. The line's center provides a capacity rate: the center's `allocated_cost` divided by its `practical_capacity_minutes` for a minutes-measured center, or its `allocated_cost` divided by its `total_rvu` for an RVU-measured center. The line's raw amount is its `quantity` multiplied by that capacity rate, multiplied by the model's `rate_factor`. The line's `allocated_amount` is that raw amount rounded half-up to two decimal places — each line rounded before any summation, per §2.5. Lines flagged `is_overhead_line` are excluded from this step.
2. The case's total activity amount is the sum of the already-rounded `allocated_amount` values of its non-overhead lines.
3. The overhead pool is distributed across the non-overhead lines in a single proportional step. The pool is the `allocated_cost` of the model's overhead cost center. The lines are processed in creation order, earliest `created_at` first, with ties broken by larger `quantity` first. Each line's raw share is the pool multiplied by the line's `allocated_amount` and divided by the total activity amount; that raw share is then truncated down to two decimal places (rounded down to the cent). The remainder — the pool rounded half-up to two decimal places minus the sum of the truncated shares — is assigned in full to the line with the largest raw share, with ties broken by the larger `allocated_amount` and then the earlier `created_at`. Every line keeps its own `allocated_amount` unchanged; its share of the pool is recorded separately per line as `overhead_amount`, equal to its truncated share, plus the remainder on the chosen line.
4. The case's `total_indirect_allocated` is the total activity amount plus the full overhead pool.
5. The case's `total_direct_cost` is its service line's `base_direct_cost` plus the sum of each implant's `unit_cost` multiplied by its `quantity`, plus the sum of each supply line's `unit_cost` multiplied by its `quantity`.
6. The case's `total_cost` is `total_direct_cost` plus `total_indirect_allocated`.
7. The case's `margin` is its `expected_reimbursement` minus `total_cost`.

Posting also stamps the case's `version_at_post` with the cost model's current `version` — a staleness marker used later — and increments the case's own `version` by one. In the same request, the ledger cascades of §2.8 fire: the service line's `total_direct_cost`, `total_revenue`, and `contribution_margin` absorb the case's contribution, and the budget period covering the case's `period` and the model's overhead pool recomputes its actual volume, flexed overhead, and variance.

Voiding moves a `POSTED` case to `VOIDED` with no further preconditions. It is a compensation: the service line's rollups are reduced by exactly the contribution the case added, the budget period's `actual_indirect_volume` is reduced accordingly, and its flexed overhead and variance are recomputed. The case and its lines remain queryable but vanish from every aggregate.

Locking moves a `POSTED` case to `LOCKED` under the `FinanceController`'s hand and is allowed only while the case is priced against the current model: the case's `version_at_post` must equal the cost model's current `version`. A case priced under an outdated model fails with `ERR_CASE_STALE_MODEL` and must be voided and re-posted under current rates rather than locked. `VOIDED` and `LOCKED` are the case's terminal states.

### 3.5. Overhead Pools, Budget Periods, and Volume-Flexed Variance

For every overhead pool it stewards, the finance office opens a **budget period**: a `FinanceController` supplies the `cost_center_id` of the `OVERHEAD` center whose pool is being budgeted, the `period`, and a `static_budget_amount` greater than zero. The pair of `cost_center_id` and `period` is unique across budget periods — a second period opened for the same pool and period is rejected with `ERR_DUPLICATE_BUDGET_PERIOD` — and each budget period carries a system-maintained `constraints_note` documenting that uniqueness. A new budget period starts in `OPEN` status with `actual_indirect_volume` at zero and its flexed overhead and variance initialized against those current actuals. The budget-period list may be filtered by `cost_center_id`, `period`, and `status`.

The period's actual position is derived, never entered. `actual_indirect_volume` is the sum, over all `POSTED` and `LOCKED` cases in the period that were priced by any model drawing on this overhead pool, of each case's pre-overhead activity total — that is, the case's `total_indirect_allocated` minus the overhead pool amount that was added to it at pricing time. `DRAFT` and `VOIDED` cases never count.

Flexing follows three volume tiers. When `actual_indirect_volume` is at or below 6,000 the tier rate is 0.20; when it is above 6,000 and at or below 20,000 the tier rate is 0.30; when it is above 20,000 the tier rate is 0.35. Boundary inclusion is exact: a volume of exactly 6,000.00 flexes at the 0.20 rate and a volume of exactly 20,000.00 at the 0.30 rate. The `flexed_overhead` is the tier rate multiplied by `actual_indirect_volume`, rounded half-up to two decimal places. The `variance_amount` is `flexed_overhead` minus `static_budget_amount`, and the `variance_direction` reads `FAVORABLE` when the variance is negative, `ON_BUDGET` when it is exactly zero, and `UNFAVORABLE` when it is positive. A static view exists alongside the flexed one: when variance is reported against the static budget without flexing, `static_budget_amount` itself serves as the overhead baseline and no tiering applies, so the same period can legitimately report a different budget under the two views.

While a budget period is `OPEN`, its flexed position is recomputed live — on every case posting or voiding that touches it, on every refresh application that reprices its cases, and whenever the period is read. Locking the period — a `FinanceController` action moving it `OPEN → LOCKED` — freezes the final `flexed_overhead` and `variance_amount` against any further recompute. The lock is refused with `ERR_PERIOD_HAS_STALE_CASES` while any `POSTED` case in that period, priced by a model using this pool, carries a `version_at_post` that differs from its model's current `version`; such cases must be resolved first. When the lock succeeds, every `POSTED` case in the period priced by a model using this pool transitions to `LOCKED` alongside it.

### 3.6. Refreshing a Cost Model: Proposal, Governance Gates, and Application

Rates drift as the general ledger closes each month, and the costing estate must be able to move without being torn down. A `CostAnalyst` proposes a **cost-model refresh** against the `ACTIVE` model being refreshed, naming it via `model_id`, declaring the `period` the new rates describe, submitting `proposed_rates` — an array of entries each naming a `cost_center_id`, a proposed `allocated_cost`, and, as the center's measure requires, a proposed `practical_capacity_minutes` or `total_rvu` — and attesting a `data_quality_score` between 0 and 100 summarizing the completeness of the underlying GL feed. The refresh is born `PROPOSED`.

At proposal time the system computes and stores a `variance_report`. For each proposed entry, the current rate is the center's present `allocated_cost` divided by its present denominator — `practical_capacity_minutes` for a minutes-measured center, `total_rvu` for an RVU-measured one — and the proposed rate is the proposed `allocated_cost` divided by the proposed denominator on the same basis. Each report entry records the `cost_center_id`, the `current_rate`, the `proposed_rate`, and the `delta_pct`: the difference between proposed and current rate, divided by the current rate, expressed as a percentage and rounded half-up to two decimal places. The report is visible whenever the refresh is read, and the refresh list may be filtered by `status` and `model_id`.

Approval is a `FinanceController` decision and moves the refresh `PROPOSED → APPROVED` behind three governance gates, evaluated after the state check: the target model must be `ACTIVE` (else `ERR_MODEL_NOT_ACTIVE`); every entry in the `variance_report` must have an absolute `delta_pct` of at most 3.00 percent (else `ERR_REFRESH_VARIANCE_EXCEEDED`); and the `data_quality_score` must be at least 80.00 (else `ERR_DATA_QUALITY_TOO_LOW`). Because approval gates on a model the analyst may have observed some time ago, the approval request must also carry `expected_model_version` per §2.9; if it no longer matches the model's current `version` — for instance because an earlier refresh has since been applied — approval is rejected with `ERR_STALE_MODEL_VERSION` (HTTP 412). A `PROPOSED` refresh may instead be rejected outright, moving it to `REJECTED` with no further preconditions.

Application, again by a `FinanceController`, moves an `APPROVED` refresh to `APPLIED` and is the most consequential action in the system. It requires only that the target model is still `ACTIVE` (else `ERR_MODEL_NOT_ACTIVE`), and then, all within the same request: each referenced cost center's `allocated_cost`, `practical_capacity_minutes`, and `total_rvu` are set to the proposed values; every `POSTED` case priced by the target model whose `period` is on or after the refresh's `period` is recomputed through the pinned pipeline of §3.4, regenerating its activity lines and refreshing its totals; each recomputed case's service line has its rollups refreshed; every affected budget period has its `actual_indirect_volume`, `flexed_overhead`, and variance recomputed; and the target model's `version` increments by one. That final increment is what makes the staleness machinery honest: any case whose `version_at_post` predates it no longer satisfies the freshness check at lock time, and must be voided and re-posted under the new rates before it, or its budget period, can be locked.

### 3.7. Decision-Support Reporting: Margins, Payer Mix, and Implant Variation

Five read-only reports turn the posted ledger into decisions; all three roles may read them. Every report draws exclusively on `POSTED` and `LOCKED` cases — `DRAFT` cases are unpriced and `VOIDED` cases are compensated away, so neither ever appears.

The **physician margin report**, requested with a `physician_id` and a `period`, surveys one surgeon's book. It returns `case_count`, `total_revenue` as the sum of `expected_reimbursement` across the qualifying cases, `total_cost` as the sum of their `total_cost`, and `margin` as revenue minus cost. `margin_per_case` is the `margin` divided by `case_count`, rounded half-up to two decimal places; when no cases qualify, `margin_per_case` is 0 and the returned `cases` list is empty. The case list is ordered worst-first by `margin` ascending, with ties broken by earlier `created_at` first.

The **DRG margin report**, requested with a `drg_id` and a `period`, compares practice to target. It returns `case_count`, `avg_indirect` — the average of `total_indirect_allocated` across the qualifying cases, rounded half-up to two decimal places — the DRG's `target_cost`, and `target_variance` as `avg_indirect` minus `target_cost`. The `compliance` flag reads `OVER` when the variance is positive, `ON_TARGET` when it is exactly zero, and `UNDER` when it is negative. When no cases qualify, `avg_indirect` is 0, `target_variance` is zero minus the DRG's `target_cost`, and `compliance` is reported as `UNDER`.

The **payer-mix report**, requested with a `service_line_id` and a `period`, attributes contribution to payer types. Each qualifying case of the line is matched to a payer contract: candidates are the line's contracts that are `ACTIVE`, whose `effective_period` is on or before the case's `period`, and whose `contracted_rate` equals the case's `expected_reimbursement`; among candidates the contract with the latest `effective_period` wins, with ties broken by the earliest `created_at`. A case with no qualifying contract is excluded from the mix and tallied under `unmatched_count`; the rest are counted in `matched_case_count`. For each `payer_type`, the report computes `revenue_pt` as the sum of `contracted_rate` over its cases, then a cost share `cost_share_pt` — the total `total_cost` of all matched cases, multiplied by that payer type's `revenue_pt`, divided by the total revenue of all matched cases, rounded half-up to two decimal places — and `contribution_pt` as `revenue_pt` minus `cost_share_pt`. Any residual rounding difference between the matched cases' total cost and the sum of the per-type shares is assigned to the payer type with the largest `revenue_pt`, with ties resolved in the fixed payer-type order `MEDICARE`, `MEDICAID`, `COMMERCIAL`, `SELF_PAY`. The response carries the `service_line_id`, `period`, `matched_case_count`, `unmatched_count`, and the per-payer-type breakdown in `payers`.

The **implant variation report**, requested with a `service_line_id`, an `item_code`, and a `period`, exposes surgeon-level cost variation for one implant catalog item. The population is the line's qualifying cases in the period that carry at least one implant with that `item_code`. Per physician, `implant_cost_per_case` is the sum of `unit_cost` multiplied by `quantity` across their matching implants, divided by their number of matching cases, rounded half-up to two decimal places. The `cohort_avg` is the total cost of all matching implants across all physicians divided by the total number of matching cases, rounded half-up to two decimal places. Each physician's `variation_pct` is their `implant_cost_per_case` minus the `cohort_avg`, divided by the `cohort_avg`, expressed as a percentage and rounded half-up to two decimal places; when the `cohort_avg` is zero, `variation_pct` is 0. The response carries the `service_line_id`, `item_code`, `period`, `cohort_avg`, and the per-physician breakdown in `physicians`.

The **service-line profitability report**, requested with a `service_line_id` and a `period`, is the rollup a `ServiceLineManager` reaches for first. It returns the period's `case_count` — the line's `POSTED` and `LOCKED` cases in that period — together with `total_revenue` as the sum of those cases' `expected_reimbursement`, `total_direct_cost` as the sum of their `total_direct_cost`, and `contribution_margin` as `total_revenue` minus `total_direct_cost`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, transition, or lock an existing resource return `200 OK`. The table below is a navigational summary only — request payloads, response shapes, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cost-accounting/service-lines` | Create a service line | FinanceController |
| GET | `/cost-accounting/service-lines` | List service lines | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/service-lines/{id}` | Get one service line (with computed rollups) | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/service-lines/{id}/archive` | Archive a service line (cascades to models and contracts) | FinanceController |
| POST | `/cost-accounting/cost-centers` | Create a cost center | FinanceController |
| GET | `/cost-accounting/cost-centers` | List cost centers | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/cost-centers/{id}` | Get one cost center | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cost-centers/{id}/archive` | Archive a cost center | FinanceController |
| POST | `/cost-accounting/physicians` | Register a physician | FinanceController |
| GET | `/cost-accounting/physicians` | List physicians | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/physicians/{id}` | Get one physician | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/physicians/{id}/deactivate` | Deactivate a physician | FinanceController |
| POST | `/cost-accounting/physicians/{id}/reactivate` | Reactivate a physician | FinanceController |
| POST | `/cost-accounting/drgs` | Create a DRG definition | FinanceController |
| GET | `/cost-accounting/drgs` | List DRGs | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/drgs/{id}` | Get one DRG | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cost-models` | Create a cost model (DRAFT) | CostAnalyst |
| GET | `/cost-accounting/cost-models` | List cost models | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/cost-models/{id}` | Get one cost model | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cost-models/{id}/approve` | Approve a DRAFT model (DRAFT → ACTIVE; supersedes target) | FinanceController |
| POST | `/cost-accounting/cost-models/{id}/archive` | Archive a DRAFT or ACTIVE model | FinanceController |
| POST | `/cost-accounting/cost-model-refreshes` | Propose a cost-model refresh (rates + data-quality gate) | CostAnalyst |
| GET | `/cost-accounting/cost-model-refreshes` | List refreshes | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/cost-model-refreshes/{id}` | Get one refresh (with variance_report) | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cost-model-refreshes/{id}/approve` | Approve a proposed refresh (OCC-guarded on model version) | FinanceController |
| POST | `/cost-accounting/cost-model-refreshes/{id}/reject` | Reject a proposed refresh | FinanceController |
| POST | `/cost-accounting/cost-model-refreshes/{id}/apply` | Apply an approved refresh: update centers, recompute posted cases, rollups, budgets | FinanceController |
| POST | `/cost-accounting/cases` | Create a case (DRAFT) | CostAnalyst |
| GET | `/cost-accounting/cases` | List cases | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/cases/{id}` | Get one case | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cases/{id}/activity-lines` | Add an activity cost line to a DRAFT case | CostAnalyst |
| GET | `/cost-accounting/cases/{id}/activity-lines` | List activity lines of a case | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/cost-centers/{id}/activity-lines` | List activity lines referencing a cost center (reverse reachability) | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cases/{id}/implants` | Add an implant to a DRAFT case | CostAnalyst |
| GET | `/cost-accounting/cases/{id}/implants` | List implants of a case | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cases/{id}/supply-lines` | Add a supply line to a DRAFT case | CostAnalyst |
| GET | `/cost-accounting/cases/{id}/supply-lines` | List supply lines of a case | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/cases/{id}/post` | Post a case: compute all costs, margin, and roll up (OCC-guarded on model version) | CostAnalyst |
| POST | `/cost-accounting/cases/{id}/void` | Void a posted case (compensates all rollups) | CostAnalyst |
| POST | `/cost-accounting/cases/{id}/lock` | Lock a posted case (requires fresh model version) | FinanceController |
| POST | `/cost-accounting/payer-contracts` | Create a payer contract | FinanceController |
| GET | `/cost-accounting/payer-contracts` | List payer contracts | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/payer-contracts/{id}` | Get one payer contract | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/budget-periods` | Create a budget period for an overhead pool | FinanceController |
| GET | `/cost-accounting/budget-periods` | List budget periods | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/budget-periods/{id}` | Get one budget period (with flex + variance) | FinanceController, CostAnalyst, ServiceLineManager |
| POST | `/cost-accounting/budget-periods/{id}/lock` | Lock a budget period and freeze its cases | FinanceController |
| GET | `/cost-accounting/reports/physician-margin` | Physician-level margin report (period-scoped) | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/reports/drg-margin` | DRG-level margin report vs target cost | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/reports/payer-mix` | Payer-mix contribution report for a service line and period | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/reports/implant-variation` | Surgeon-level implant cost variation for an item code | FinanceController, CostAnalyst, ServiceLineManager |
| GET | `/cost-accounting/reports/service-line-profitability` | Service-line profitability decision-support rollup | FinanceController, CostAnalyst, ServiceLineManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the canonical id-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PERIOD_FORMAT` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SERVICE_LINE_NOT_ACTIVE` | 409 Conflict |
| `ERR_MODEL_NOT_ACTIVE` | 409 Conflict |
| `ERR_OVERHEAD_CENTER_INVALID` | 422 Unprocessable Content |
| `ERR_ACTIVITY_CENTER_INVALID` | 422 Unprocessable Content |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 Unprocessable Content |
| `ERR_PHYSICIAN_NOT_ACTIVE` | 422 Unprocessable Content |
| `ERR_CASE_PERIOD_BEFORE_MODEL` | 409 Conflict |
| `ERR_CASE_NO_ACTIVITY` | 409 Conflict |
| `ERR_CASE_STALE_MODEL` | 409 Conflict |
| `ERR_PERIOD_HAS_STALE_CASES` | 409 Conflict |
| `ERR_SERVICE_LINE_HAS_OPEN_CASES` | 409 Conflict |
| `ERR_SERVICE_LINE_HAS_ACTIVE_MODEL` | 409 Conflict |
| `ERR_MODEL_HAS_OPEN_CASES` | 409 Conflict |
| `ERR_MODEL_HAS_OPEN_REFRESH` | 409 Conflict |
| `ERR_COST_CENTER_IN_USE` | 409 Conflict |
| `ERR_PHYSICIAN_HAS_OPEN_CASES` | 409 Conflict |
| `ERR_REFRESH_VARIANCE_EXCEEDED` | 422 Unprocessable Content |
| `ERR_DATA_QUALITY_TOO_LOW` | 422 Unprocessable Content |
| `ERR_DUPLICATE_BUDGET_PERIOD` | 409 Conflict |
| `ERR_STALE_MODEL_VERSION` | 412 Precondition Failed |
