# Roofing Storm Restoration API — Product Requirements Document

## 1. Introduction

Storm-restoration roofing is a business where money and trust move in opposite directions: a homeowner whose roof was just torn open by hail or wind signs a contract, the contractor fronts material and labor, and an insurance carrier pays in stages tied to verified progress. The job that follows is long, regulated, and easy to get wrong — a delivery comes up short, a permit lapses, a crew is double-booked, a draw is billed twice, a change order quietly pushes the contract below what has already been paid out. The Roofing Storm Restoration API exists to make that whole arc auditable and mechanical, from the first damage assessment through the workmanship warranty that outlives the roof crew by a decade.

This document specifies the API that backs that workflow. The system tracks a **Job** from an unqualified lead through inspection, aerial or field estimating, contracting, material procurement, permitting, crewed production, progress draws, change orders, completion, and finally warranty. Three operational roles share the work, every monetary figure is held in integer cents, and the Job carries a small conserved ledger so that "how much has been billed, paid, withheld, and remains" is always answerable from a single resource. The sections below define the global contract first (authentication, envelopes, pagination, precision, concurrency), then the business workflows where the real rules live, and close with the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted at the top level — there are no nested resource paths; every child references its parents through identifier fields carried in the request body.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If `X-User-Role` is absent or does not name one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header names a valid role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly three roles, spelled precisely as follows: `FieldAdjuster`, `Estimator`, and `ProductionManager`. A `FieldAdjuster` owns the front of the funnel — creating leads, scheduling and completing inspections, marking the inspection milestone, and abandoning dead leads. An `Estimator` owns scope and measurement — creating estimate records and their line items, finalizing them, advancing the job to the estimated milestone, binding a contract, and proposing change orders. A `ProductionManager` owns everything downstream of the contract — materials, crews, permits, draws, change-order approval and application, warranties, the production milestones, and the test-driving clock.

Role identity binds to resources differently for each role. When `X-User-Role` is `Estimator`, `X-User-ID` is the `id` of the acting `Estimator` record; any ownership check on a resource that references an estimator compares that resource's estimator foreign key to `X-User-ID`. When `X-User-Role` is `FieldAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `ProductionManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. All three roles share read access: any of them may issue GET reads across every collection.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a page returns; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before the page begins; it defaults to 0 and may not be negative. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the count of all matching resources before paging and `has_more` indicates whether further items remain past the current page.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system carry a standard set of server-managed fields. Every such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. Mutable resources additionally carry an `updated_at` timestamp (same format, refreshed on every change) and a `version` — an integer that begins at 1 and increments by one on every mutation. The entities that carry the full set (`id`, `created_at`, `updated_at`, `version`) are Job, Crew, Inspection, Estimate, EstimateLineItem, MaterialOrder, CrewAssignment, Permit, Draw, ChangeOrder, and Warranty.

The **Estimator** entity is the exception: it is immutable reference data, so an Estimator record carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all; those fields are simply absent from an Estimator resource.

Because warranty timing depends on wall-clock arithmetic, the server maintains a single logical UTC clock. An admin-only test-driving capability sets that clock to a supplied instant; the request body carries the target instant in the field `to_iso8601`. The logical clock governs every "current clock" reference in this document — warranty activation stamps it, warranty cancellation measures elapsed months against it, and warranty expiry compares against it.

### 2.5. Monetary Precision and Rounding

Every monetary quantity in the system is stored and returned as an integer number of cents — contract values, ledger balances, line costs, freight, premiums, and refunds alike. There are no fractional cents in any stored or returned value. Wherever a calculation produces a non-integer cent amount, the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up to the larger). The specific points at which rounding is applied — and the order relative to summation and uplift — are pinned per calculation in §3, because for several of these figures the rounding order is observable when fractional cents straddle a boundary.

### 2.6. The Job Ledger and Its Conservation

Each Job carries a small ledger of computed integer-cent fields that together answer "where does the money stand." The anchor is `contract_value_cents`: it is 0 until the job is contracted, then it equals the bound estimate's final total plus the signed sum of every applied change order's delta. Against that anchor the ledger tracks `disbursed_gross_cents` (the gross of all disbursed draws), `disbursed_net_cents` (the net actually paid out), `retainage_held_cents` (gross withheld as retainage and not yet released), and `billed_pct` (the highest cumulative percent-complete reached by any disbursed draw — a strictly increasing billing watermark). The field `remaining_billable_cents` is always `contract_value_cents` minus `disbursed_gross_cents` and is never negative; together with `disbursed_gross_cents` it conserves exactly to `contract_value_cents`. All five computed ledger fields, plus `billed_pct`, initialize to 0 when a job is first created as a lead.

The fraction of each draw's gross that is withheld as retainage is governed by the job's `retainage_pct`, an input supplied at job creation that defaults to 0.10 and must lie between 0 and 0.20 inclusive. A value outside that range is an invalid request.

### 2.7. State Consistency, Versioning, and Cascades

Each lifecycle-bearing resource — Job, Inspection, Estimate, MaterialOrder, CrewAssignment, Permit, Draw, ChangeOrder, and Warranty — carries a `status` field holding its current state-machine state, set by the server through the transitions described in §3 and never written directly by a client. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` increments by one. This applies to explicit state transitions and to derived-field updates alike: when a draw disbursement rewrites a job's ledger fields, that counts as a mutation of the Job and bumps `Job.version`. Several operations mutate more than one resource in a single request; in those cases every affected resource is independently mutated and independently version-bumped. The specific cascades — a change order rippling through the contract value, the remaining-billable figure, and an outstanding material order; a draw disbursement rewriting the job ledger; a passed permit-final inspection closing its permit; a warranty activation releasing retainage — are spelled out in the workflow narratives of §3, and each is immediate and synchronous.

### 2.8. Nested Reference Validation Order

Although every collection is addressed at the top level, many requests still name several resources at once — a path identifier plus foreign keys carried in the body. The server validates these in a fixed order. First it confirms that any resource named by a path identifier exists, rejecting with `ERR_NOT_FOUND` (HTTP 404) if it does not. Then, for create operations and for the contract operation, it confirms that every foreign key in the body resolves — `job_id`, `crew_id`, `estimate_id`, `permit_id`, `assigned_estimator_id`, and the `estimate_id` named when contracting — rejecting with `ERR_FK_NOT_FOUND` (HTTP 404) when any referenced record is missing. Path-identifier existence always takes precedence over body foreign-key resolution.

### 2.9. Request Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. The order is: (1) authentication — `X-User-Role` present and a declared role, else `ERR_UNAUTHENTICATED`; (2) authorization — the role may perform this operation, else `ERR_FORBIDDEN`; (3) path-resource existence, left to right, else `ERR_NOT_FOUND`; (4) body foreign-key resolution, else `ERR_FK_NOT_FOUND`; (5) presence and typing of required body fields, else `ERR_MISSING_FIELD`; (6) enum, numeric-range, and interval validity, else `ERR_INVALID_REQUEST`; (7) whether the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`; (8) cross-entity state preconditions; (9) temporal-overlap rules; (10) fiscal rules; and finally (11) optimistic-concurrency version checks. A check earlier in this order always masks one later in the order, so — for example — an authorization failure surfaces before a stale-version failure even when both conditions hold.

Items (8) through (11) each cover a family of business rules whose specific error identifiers depend on the operation: cross-entity state preconditions may yield `ERR_JOB_NOT_IN_PRODUCTION`, `ERR_MATERIALS_NOT_DELIVERED`, `ERR_PERMIT_NOT_ISSUED`, `ERR_NO_PASSED_ASSESSMENT`, `ERR_NO_FINALIZED_ESTIMATE`, `ERR_CREW_INACTIVE`, or `ERR_JOB_NOT_COMPLETED`; temporal-overlap rules yield `ERR_CREW_DOUBLE_BOOKED` or `ERR_INSPECTION_BUFFER_CONFLICT`; fiscal rules yield `ERR_PCT_NOT_INCREASING` or `ERR_CONTRACT_BELOW_DISBURSED`; and the concurrency check yields `ERR_STALE_JOB_VERSION`. The conditions that trigger each of these live with the workflow they guard in §3.

### 2.10. Optimistic Concurrency on the Job Ledger

Two operations write against the Job ledger under optimistic concurrency control, and both demand a version token. When requesting a draw, the body must carry `expected_job_version` equal to the target job's current `version`. A prior draw against the same job legitimately advances the billing watermark and bumps `Job.version`; a draw request that still carries the older `expected_job_version` is therefore working from a stale view of the ledger, and the system rejects it with `ERR_STALE_JOB_VERSION` (HTTP 412) before any ledger figure is touched. The check guards against a client overwriting a billing position it has not observed.

The same protection guards the application of a change order. Applying an approved change order requires `expected_job_version` in the body to match the job's current `version`; if another ledger mutation — a draw disbursement or another applied change order — has advanced `Job.version` since the client last read it, the apply is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412), because it would otherwise reason from stale contract and disbursement figures. No other endpoint takes a version token. Note that appending an estimate line item accepts an optional `expected_estimate_version` field; when supplied it is checked against the estimate's current `version`, but it is not part of the Job-ledger OCC contract described here.

## 3. Business Logic & Workflows

### 3.1. The Lead and Its Inspection

Everything begins with a lead. A `FieldAdjuster` opens a Job by supplying the homeowner's `customer_name`, the `property_address`, the storm `peril` being claimed, and the `assigned_estimator_id` of the estimator who will own scoping. An **Estimator** is immutable reference data, created with the estimator's `name` and state contractor `license_no`; the `assigned_estimator_id` on a job is the `id` of one such record. The `peril` is one of `HAIL`, `WIND`, `HURRICANE`, or `OTHER`. When the loss is insurance-backed, an `insurance_carrier` name may be supplied, and the `retainage_pct` may be set at creation as described in §2.6; both are optional. A freshly created Job lands in `LEAD` status with a `version` of 1, its bound-estimate reference empty, and its ledger fields zeroed.

To assess storm damage, a `FieldAdjuster` schedules an **Inspection** against a job. Each inspection names its `job_id`, a `kind`, and a closed scheduling window defined by `scheduled_start` and `scheduled_end`, where the end must be strictly later than the start. The `kind` is either `DAMAGE_ASSESSMENT` — the lead inspection that gauges storm damage — or `PERMIT_FINAL`, the municipal final tied to a permit. A `PERMIT_FINAL` inspection must name the `permit_id` it finalizes, and a `DAMAGE_ASSESSMENT` must not carry a `permit_id`; violating either rule is rejected with `ERR_PERMIT_FINAL_NEEDS_PERMIT` (HTTP 422). A new inspection begins in `SCHEDULED` status.

A `FieldAdjuster` later completes a scheduled inspection by supplying an `outcome` of `PASS` or `FAIL`. A `PASS` outcome moves the inspection from `SCHEDULED` to `PASSED`; a `FAIL` outcome moves it from `SCHEDULED` to `FAILED`. When the inspection is a `DAMAGE_ASSESSMENT` being passed, the completing request must also record a `damage_severity` of `MINOR`, `MODERATE`, or `TOTAL_LOSS`; omitting it is rejected with `ERR_SEVERITY_REQUIRED` (HTTP 422). Passing a `PERMIT_FINAL` inspection has a cascade: if the permit it references is currently `ISSUED`, that permit is automatically transitioned to `CLOSED` and its own `version` increments — the inspection's pass is what closes the permit.

Once a `DAMAGE_ASSESSMENT` inspection for a job has reached `PASSED`, a `FieldAdjuster` may advance the job from `LEAD` to `INSPECTED`. If no passed damage-assessment inspection exists for the job, the advance is rejected with `ERR_NO_PASSED_ASSESSMENT`. At any point before a contract is bound — that is, while the job is in `LEAD`, `INSPECTED`, or `ESTIMATED` — a `FieldAdjuster` may abandon the lead, moving the job to the terminal `LOST` status and recording the supplied `lost_reason`. No precondition guards the loss transition.

### 3.2. Scoping the Roof: Estimates and Line Items

An `Estimator` scopes the roof by drafting one or more **Estimate** records against the job. Creating an estimate names its `job_id` and a `source_kind` of either `AERIAL` or `FIELD`, and may carry an `aerial_contingency_pct`. The `source_kind` matters at finalization: an `AERIAL` estimate — measured from imagery — applies a contingency uplift to absorb measurement error, whereas a `FIELD` estimate applies none. The `aerial_contingency_pct` defaults to 0.08 and must lie between 0 and 0.25 inclusive; a value outside that range is an invalid request. A new estimate opens in `DRAFT` status, where it accepts line items.

While an estimate is in `DRAFT`, an `Estimator` appends **Estimate Line Items** to it. Each line item names its parent `estimate_id` and carries a `trade` — one of `SHINGLE`, `UNDERLAYMENT`, `RIDGE_VENT`, `FLASHING`, `DECKING`, or `GUTTER` — the number of `squares` (each square is a 100-square-foot unit), a `unit_price_cents` per square, and an optional `waste_factor_pct` per-line waste uplift. The `squares` must be greater than zero, the `unit_price_cents` must be greater than zero, and the `waste_factor_pct` defaults to 0.10 and must lie between 0 and 0.50 inclusive; violating any of these is an invalid request. The line item may also carry an optional `expected_estimate_version`; when present, it is checked against the parent estimate's current `version`.

Each line item's cost is computed and stored at append time as its `line_cost_cents`: take the `squares`, multiply by one plus the `waste_factor_pct`, multiply by the `unit_price_cents`, and round that product half-up to a whole cent. The rounding happens at the line. Appending a line item also recomputes the parent estimate's running totals: its `line_subtotal_cents` is the sum of every line item's already-rounded `line_cost_cents` for that estimate, and its `final_total_cents` is recomputed by the same source-dependent rule used at finalization (so a `DRAFT` estimate carries the live running `final_total_cents`, not 0). Both totals initialize to 0 at estimate creation and are recomputed on every append; finalization simply freezes whatever values the last append left. The order is pinned — each line is rounded first, and only then are the rounded lines summed (round-per-line-then-sum, never sum-then-round); the distinction is observable when fractional cents straddle a rounding boundary.

An `Estimator` finalizes a draft estimate to lock its scope, moving it from `DRAFT` to `FINALIZED`. Finalization is refused with `ERR_EMPTY_ESTIMATE` if the estimate has no line items. On finalization the estimate's `line_subtotal_cents` and `final_total_cents` are frozen. The `final_total_cents` depends on the source: for an `AERIAL` estimate it is the `line_subtotal_cents` multiplied by one plus the `aerial_contingency_pct`, rounded half-up to a whole cent; for a `FIELD` estimate it is exactly the `line_subtotal_cents` with no uplift. The line-subtotal sum that feeds this draws on every line item belonging to the estimate, with no status filter, since line items have no status and are immutable once the estimate is finalized. Once at least one finalized estimate exists for a job, the `Estimator` may advance the job from `INSPECTED` to `ESTIMATED`; without any finalized estimate the advance is rejected with `ERR_NO_FINALIZED_ESTIMATE`.

### 3.3. Binding the Contract

Contracting is where a scoped job becomes a financial commitment. An `Estimator` binds a finalized estimate to a job by naming the chosen `estimate_id`, advancing the job from `ESTIMATED` to `CONTRACTED`. The named estimate must belong to this job and be `FINALIZED`, otherwise the request is rejected with `ERR_INVALID_STATE`. A job may be contracted only once: if the job already has a bound estimate, the request is rejected with `ERR_ALREADY_CONTRACTED`.

Binding has several synchronous effects. The job records the chosen estimate as its bound estimate (captured in `bound_estimate_id`), and that estimate stays `FINALIZED` while every other finalized estimate for the same job is superseded — moved to the `SUPERSEDED` status with its own `version` bumped. The job's `contract_value_cents` is set to the bound estimate's `final_total_cents`, and `remaining_billable_cents` is set equal to that contract value (nothing has been disbursed yet). The job's `version` increments. From this point the contract value is the conserved anchor the rest of the ledger reconciles against.

### 3.4. Procuring Materials

A `ProductionManager` places a **Material Order** for a contracted job by naming its `job_id`; the order's quantities are derived, not supplied. Sizing draws on the job's bound estimate. First, the effective shingle squares are computed: sum the `squares` of every bound-estimate line item whose `trade` is `SHINGLE`, then add the `extra_shingle_squares` of every applied change order for the job. The bundle count `bundles` is then the effective shingle squares multiplied by one plus the shingle waste allowance of 0.15, multiplied by 3 bundles per square, that product rounded up to the next whole bundle, and finally floored at a minimum of 12 bundles — whichever of the computed count and 12 is larger is the bundle count. The order's `total_weight_lbs` is `bundles` multiplied by 80 pounds per bundle.

Freight is tiered by weight. If `total_weight_lbs` is at most 2000, `freight_cents` is 7500. If it is greater than 2000 but at most 4000, freight is 12500. If it exceeds 4000, freight is 12500 plus 3000 for each whole 1000 pounds (or part thereof) above 4000 — that is, the weight above 4000 divided by 1000, rounded up to a whole number, multiplied by 3000, added to the 12500 base. A new material order opens in `ORDERED` status.

A `ProductionManager` confirms delivery, moving an order from `ORDERED` to `DELIVERED`; this is permitted only while the parent job is `CONTRACTED` or `IN_PRODUCTION`, otherwise `ERR_INVALID_STATE`. The delivery request may carry `delivered_short`, recorded true when the delivery arrived with fewer bundles than ordered; the order's `delivered_short` is null at order creation and is overwritten only when a boolean `delivered_short` is supplied on the delivery request (an omitted `delivered_short` leaves the prior value, i.e. null, unchanged). Alternatively, a `ProductionManager` may cancel an order that is still `ORDERED`, moving it to `CANCELLED`; cancellation has no precondition.

### 3.5. Permitting

Roofing requires a municipal permit, and a `ProductionManager` applies for one by naming the `job_id` and the issuing `municipality`. A new **Permit** opens in `APPLIED` status. When the municipality issues the permit, the `ProductionManager` records the issued `permit_number`, advancing the permit from `APPLIED` to `ISSUED`; the `permit_number` is required and its absence is rejected with `ERR_MISSING_FIELD`. An applied permit that never issues can instead be expired by a `ProductionManager`, moving it from `APPLIED` to the terminal `EXPIRED`.

An issued permit reaches its terminal `CLOSED` status through the inspection cascade described in §3.1: when a `PERMIT_FINAL` inspection referencing it passes, the issued permit is automatically closed. There is no direct close operation — closing is always a consequence of the final inspection passing.

When scheduling `PERMIT_FINAL` inspections, the system enforces a mandatory spacing buffer of 24 hours between any two permit-final windows on the same job, treating each window as a closed interval from `scheduled_start` through `scheduled_end`. The candidates considered are the existing permit-final inspections for that job whose status is `SCHEDULED` or `PASSED`. To test a new window against an existing one, order the two by start time and measure the gap in whole hours from the earlier window's end to the later window's start; if that gap is less than 24 hours the two conflict — and because a negative gap means the windows actually overlap, true overlaps are caught by the same test. A gap of exactly 24 hours is allowed (the boundary is inclusive). Any conflict against any existing permit-final window for the job rejects the new inspection with `ERR_INSPECTION_BUFFER_CONFLICT`.

### 3.6. Starting Production and Scheduling Crews

Before a roof can be worked, two things must be true at once: materials must be on site and the permit must be in hand. A `ProductionManager` advances a contracted job from `CONTRACTED` to `IN_PRODUCTION` only when at least one material order for the job is `DELIVERED` and at least one permit for the job is `ISSUED`. A missing delivery is rejected with `ERR_MATERIALS_NOT_DELIVERED`; a missing issued permit with `ERR_PERMIT_NOT_ISSUED`.

Crews are booked against a job's production window. A `ProductionManager` books a **Crew Assignment** by naming the `job_id`, the `crew_id`, and a half-open time window from `window_start` (inclusive) to `window_end` (exclusive), where the end must be strictly later than the start. A new assignment opens in `BOOKED` status. Before a booking is accepted, the system enforces that the chosen crew is not double-booked. For the target crew, the existing assignments that hold the calendar are those whose status is `BOOKED` or `CHECKED_IN` — cancelled and completed assignments free their windows. Two half-open windows conflict when the new window's start is earlier than the existing window's end and the existing window's start is earlier than the new window's end; if that holds against any existing assignment for the crew, the booking is rejected with `ERR_CREW_DOUBLE_BOOKED`. Because the intervals are half-open, two windows that merely touch — the new window starting exactly when an existing one ends — do not conflict and are allowed.

A `ProductionManager` checks a booked crew in, moving the assignment from `BOOKED` to `CHECKED_IN`. Check-in has two preconditions: the parent job must be `IN_PRODUCTION`, otherwise `ERR_JOB_NOT_IN_PRODUCTION`, and the booked **Crew** must have its `active` flag true, otherwise `ERR_CREW_INACTIVE`. A crew is reference data created by a `ProductionManager` with a `name`, an optional `max_squares_per_day` productivity cap that defaults to 30, and an optional `active` flag that defaults to true. After work, the manager completes a checked-in assignment, moving it from `CHECKED_IN` to `COMPLETED`. A still-`BOOKED` assignment may instead be cancelled, moving it to `CANCELLED` and freeing its half-open window for re-booking. Neither completion nor cancellation carries a precondition beyond the source state.

### 3.7. Progress Draws and the Billing Watermark

Money flows to the contractor through **Draws** — progress payments claimed against percent-complete and disbursed atomically. A `ProductionManager` requests a draw by naming the `job_id`, the `cumulative_pct` of work claimed complete (a fraction greater than 0 and at most 1), and the `expected_job_version` OCC token. A draw is created in `REQUESTED` status and, when every precondition passes, is disbursed in the same request, ending in `DISBURSED`. If a non-version business precondition fails, the draw is instead recorded `REJECTED` with no change to the job ledger; a `REJECTED` draw's computed amount fields — `gross_eligible_cents`, `retainage_cents`, `net_disbursed_cents`, and `is_final` — are left null, since no disbursement was computed. A version (OCC) failure persists no draw at all; only request-shape-valid, business-rejected requests leave a `REJECTED` record.

Four preconditions gate disbursement, and they map to distinct rejections. The parent job must be `IN_PRODUCTION`, else `ERR_JOB_NOT_IN_PRODUCTION`. The claimed `cumulative_pct` must strictly exceed the job's current `billed_pct` — the billing watermark — else `ERR_PCT_NOT_INCREASING`; this is what forbids billing the same progress twice. The `cumulative_pct` must be at most 1.0, else `ERR_PCT_OUT_OF_RANGE` (and a value at or below 0, or above 1 — that is, any `cumulative_pct` outside the open-low, closed-high interval `(0, 1]` — is rejected at the range-validation stage with that same `ERR_PCT_OUT_OF_RANGE`, HTTP 422; only a non-numeric `cumulative_pct` yields `ERR_INVALID_REQUEST`). Finally the `expected_job_version` must equal the job's current `version`, else the stale-version rejection of §2.10 applies.

On disbursement the draw's amounts are computed against the job read at request time. The gross-to-date is the job's `contract_value_cents` multiplied by the claimed `cumulative_pct`, rounded half-up to a whole cent. The draw's `gross_eligible_cents` is that gross-to-date minus the job's `disbursed_gross_cents` already on the books — only the incremental gross is eligible. The draw is final, recorded in `is_final`, exactly when the `cumulative_pct` equals 1.0. For a non-final draw the `retainage_cents` is the `gross_eligible_cents` multiplied by the job's `retainage_pct`, rounded half-up to a whole cent; for a final draw the `retainage_cents` is 0, because the final draw withholds nothing new (the retainage held to date is released separately at warranty activation). The `net_disbursed_cents` is the `gross_eligible_cents` minus the `retainage_cents`.

Disbursement then rewrites the job ledger in one cascade: the job's `disbursed_gross_cents` increases by the draw's `gross_eligible_cents`, its `disbursed_net_cents` increases by the `net_disbursed_cents`, its `retainage_held_cents` increases by the `retainage_cents`, its `billed_pct` is set to the draw's `cumulative_pct` (advancing the watermark), and its `remaining_billable_cents` is recomputed as `contract_value_cents` minus the new `disbursed_gross_cents`. Both the draw's `version` and the job's `version` increment — the job bump is precisely the OCC advance that a subsequent stale draw would collide with.

### 3.8. Change Orders and the Contract Cascade

Roofs hide surprises — rotten decking, extra shingle squares — and a **Change Order** amends a contracted job to absorb them. An `Estimator` or a `ProductionManager` proposes a change order against a `job_id`, recording the `reason` for the scope change, a signed `delta_cents` adjustment to the contract value (which may be negative), and an optional `extra_shingle_squares` count of additional shingle squares to fold into material re-sizing, defaulting to 0 and never negative. A new change order opens in `PROPOSED` status.

A `ProductionManager` approves a proposed change order, moving it from `PROPOSED` to `APPROVED`, permitted only while the parent job is `CONTRACTED` or `IN_PRODUCTION`, otherwise `ERR_INVALID_STATE`. A still-`PROPOSED` or `APPROVED` change order may instead be voided by a `ProductionManager`, moving it to the terminal `VOIDED`; voiding has no precondition beyond the source state.

Applying an approved change order — moving it from `APPROVED` to the terminal `APPLIED` — is the consequential step, and it carries three preconditions in addition to the OCC token. The parent job must be `CONTRACTED` or `IN_PRODUCTION`, else `ERR_INVALID_STATE`. The `expected_job_version` in the body must match the job's current `version`, else `ERR_STALE_JOB_VERSION` as described in §2.10. And the amended contract must not fall below what has already been paid out: the job's `contract_value_cents` plus this order's `delta_cents` must be at least the job's `disbursed_gross_cents`, otherwise the apply is rejected with `ERR_CONTRACT_BELOW_DISBURSED`.

Application cascades through the ledger. First, the job's `contract_value_cents` increases by the `delta_cents` (the signed amount, so a negative delta reduces it). Second, the job's `remaining_billable_cents` is re-derived from the new contract value as `contract_value_cents` minus `disbursed_gross_cents`. Third, when `extra_shingle_squares` is greater than 0, the job's bound-estimate effective shingle squares grow by that amount, and any material order for the job still in `ORDERED` status is re-sized — its `bundles`, `total_weight_lbs`, and `freight_cents` recomputed by the sizing rule of §3.4, which now folds the applied extra squares into the effective shingle total. The job's `version` increments to close the apply.

### 3.9. Completing the Job

A `ProductionManager` completes a job in production, moving it from `IN_PRODUCTION` to the terminal `COMPLETED`, only when three conditions all hold. The job must be fully billed — its `billed_pct` must equal 1.0, meaning a final draw has been disbursed — otherwise `ERR_FINAL_DRAW_MISSING`. A `PERMIT_FINAL` inspection for the job must have reached `PASSED`, otherwise `ERR_FINAL_INSPECTION_MISSING`. And no change order for the job may be open in `PROPOSED` or `APPROVED` status, otherwise `ERR_OPEN_CHANGE_ORDER` — every change order must be resolved (applied or voided) before the job closes. Completing increments the job's `version`.

### 3.10. The Workmanship Warranty

After a roof is finished, a `ProductionManager` writes a **Warranty** against the completed job by naming the `job_id`, the `premium_cents` charged (zero or greater), and an optional `term_months` term that defaults to 120 months and must be greater than zero. A new warranty opens in `PENDING` status; its `start_at` and `refund_cents` are not yet set.

Activation requires the job to be in its terminal `COMPLETED` state, otherwise the activation is rejected with `ERR_JOB_NOT_COMPLETED`. Activating a warranty moves it from `PENDING` to `ACTIVE` and stamps `start_at` to the current logical clock. Activation also triggers the retainage release: the job's `retainage_held_cents` is reset to 0 (released to the homeowner) and that released amount is added to the job's `disbursed_net_cents`, reflecting that the previously withheld funds are now paid out. Both the warranty's `version` and the job's `version` increment.

An active warranty can end one of two ways. A `ProductionManager` may expire it once its term has fully elapsed, moving it from `ACTIVE` to `EXPIRED`; expiry is permitted only when the current logical clock is at or past `start_at` plus `term_months`, otherwise the request is rejected with `ERR_WARRANTY_NOT_EXPIRED`. The expiry instant `start_at` plus `term_months` is computed by calendar-month arithmetic: advance `start_at` by `term_months` whole calendar months, keeping the same day-of-month and time-of-day, and when the target month is shorter than the original day-of-month, clamp down to that month's last valid day. Alternatively, a `ProductionManager` may cancel an active warranty, supplying a `cancel_basis` of either `PRORATED` or `SHORT_RATE`; the basis is required and its absence (or an unrecognized value) is rejected with `ERR_MISSING_FIELD`. Cancellation moves the warranty from `ACTIVE` to `CANCELLED`, computes the `refund_cents`, and bumps the warranty's `version`.

The refund computation runs as follows. Take the whole number of months elapsed between `start_at` and the current logical clock, floored and never below zero — computed by calendar-month arithmetic as `(current.year - start.year) * 12 + (current.month - start.month)`, then decremented by one when the current day-of-month-and-time-of-day has not yet reached the `start_at` day-of-month-and-time-of-day, and finally floored at zero. The remaining months are the `term_months` minus that elapsed count, but never below zero. The prorated refund is the `premium_cents` multiplied by the remaining months, divided by the `term_months`, rounded half-up to a whole cent. On a `PRORATED` basis the `refund_cents` is exactly that prorated figure — the full unearned proration. On a `SHORT_RATE` basis the `refund_cents` is the prorated figure multiplied by 0.90, rounded half-up to a whole cent — a 10 percent short-rate penalty against the proration. The two roundings are applied in that order: first when computing the prorated amount, then again after the short-rate factor.

## 4. Endpoint Definitions

The following table summarizes every endpoint. Operations that create a new standalone resource return `201 Created`; operations that modify or transition an existing resource — including the milestone and lifecycle transitions — return `200 OK`. Request and response bodies are not repeated here; reconstruct them from the workflow narratives in §3. The full envelope is defined in §2.2, and the validation order that decides which error a malformed request receives is in §2.9.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/estimators` | Create an estimator (reference data) | Estimator, ProductionManager |
| GET | `/estimators/{id}` | Get an estimator | FieldAdjuster, Estimator, ProductionManager |
| POST | `/crews` | Create a crew | ProductionManager |
| GET | `/crews/{id}` | Get a crew | FieldAdjuster, Estimator, ProductionManager |
| POST | `/jobs` | Create a storm-restoration job (lead) | FieldAdjuster |
| GET | `/jobs/{id}` | Get a job with computed ledger fields | FieldAdjuster, Estimator, ProductionManager |
| GET | `/jobs` | List jobs (paginated) | FieldAdjuster, Estimator, ProductionManager |
| POST | `/jobs/{id}/mark-inspected` | Advance a job to INSPECTED | FieldAdjuster |
| POST | `/jobs/{id}/mark-estimated` | Advance a job to ESTIMATED | Estimator |
| POST | `/jobs/{id}/contract` | Bind a finalized estimate and advance to CONTRACTED | Estimator |
| POST | `/jobs/{id}/start-production` | Advance a job to IN_PRODUCTION | ProductionManager |
| POST | `/jobs/{id}/complete` | Advance a job to COMPLETED | ProductionManager |
| POST | `/jobs/{id}/lose` | Mark a pre-contract job LOST | FieldAdjuster |
| POST | `/inspections` | Schedule an inspection | FieldAdjuster |
| GET | `/inspections/{id}` | Get an inspection | FieldAdjuster, Estimator, ProductionManager |
| GET | `/inspections` | List inspections | FieldAdjuster, Estimator, ProductionManager |
| POST | `/inspections/{id}/complete` | Complete an inspection with PASS/FAIL | FieldAdjuster |
| POST | `/estimates` | Create a DRAFT estimate for a job | Estimator |
| GET | `/estimates/{id}` | Get an estimate with computed totals | FieldAdjuster, Estimator, ProductionManager |
| GET | `/estimates` | List estimates | FieldAdjuster, Estimator, ProductionManager |
| POST | `/estimates/{id}/line-items` | Append a line item to a DRAFT estimate | Estimator |
| GET | `/estimates/{id}/line-items` | List line items of an estimate | FieldAdjuster, Estimator, ProductionManager |
| POST | `/estimates/{id}/finalize` | Finalize a DRAFT estimate | Estimator |
| POST | `/material-orders` | Place a material order sized from the bound estimate | ProductionManager |
| GET | `/material-orders/{id}` | Get a material order | FieldAdjuster, Estimator, ProductionManager |
| GET | `/material-orders` | List material orders | FieldAdjuster, Estimator, ProductionManager |
| POST | `/material-orders/{id}/deliver` | Mark a material order DELIVERED | ProductionManager |
| POST | `/material-orders/{id}/cancel` | Cancel an ORDERED material order | ProductionManager |
| POST | `/crew-assignments` | Book a crew window for a job | ProductionManager |
| GET | `/crew-assignments/{id}` | Get a crew assignment | FieldAdjuster, Estimator, ProductionManager |
| GET | `/crew-assignments` | List crew assignments | FieldAdjuster, Estimator, ProductionManager |
| POST | `/crew-assignments/{id}/check-in` | Check a crew in on the job | ProductionManager |
| POST | `/crew-assignments/{id}/complete` | Complete a crew assignment | ProductionManager |
| POST | `/crew-assignments/{id}/cancel` | Cancel a booked crew assignment | ProductionManager |
| POST | `/permits` | Apply for a permit on a job | ProductionManager |
| GET | `/permits/{id}` | Get a permit | FieldAdjuster, Estimator, ProductionManager |
| GET | `/permits` | List permits | FieldAdjuster, Estimator, ProductionManager |
| POST | `/permits/{id}/issue` | Issue an applied permit | ProductionManager |
| POST | `/permits/{id}/expire` | Expire an applied permit | ProductionManager |
| POST | `/draws` | Request a progress draw; disbursed atomically when preconditions pass | ProductionManager |
| GET | `/draws/{id}` | Get a draw | FieldAdjuster, Estimator, ProductionManager |
| GET | `/draws` | List draws | FieldAdjuster, Estimator, ProductionManager |
| POST | `/change-orders` | Propose a change order on a job | ProductionManager, Estimator |
| GET | `/change-orders/{id}` | Get a change order | FieldAdjuster, Estimator, ProductionManager |
| GET | `/change-orders` | List change orders | FieldAdjuster, Estimator, ProductionManager |
| POST | `/change-orders/{id}/approve` | Approve a proposed change order | ProductionManager |
| POST | `/change-orders/{id}/apply` | Apply an approved change order | ProductionManager |
| POST | `/change-orders/{id}/void` | Void a proposed or approved change order | ProductionManager |
| POST | `/warranties` | Create a PENDING workmanship warranty | ProductionManager |
| GET | `/warranties/{id}` | Get a warranty | FieldAdjuster, Estimator, ProductionManager |
| GET | `/warranties` | List warranties | FieldAdjuster, Estimator, ProductionManager |
| POST | `/warranties/{id}/activate` | Activate a warranty; releases retainage | ProductionManager |
| POST | `/warranties/{id}/cancel` | Cancel an active warranty; computes refund | ProductionManager |
| POST | `/warranties/{id}/expire` | Expire a warranty whose term has elapsed | ProductionManager |
| POST | `/_clock/set` | Set the server's current UTC clock (test-driving) | ProductionManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_MISSING_FIELD` | 400 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_CONTRACTED` | 409 |
| `ERR_NO_PASSED_ASSESSMENT` | 409 |
| `ERR_NO_FINALIZED_ESTIMATE` | 409 |
| `ERR_EMPTY_ESTIMATE` | 409 |
| `ERR_SEVERITY_REQUIRED` | 422 |
| `ERR_MATERIALS_NOT_DELIVERED` | 409 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_JOB_NOT_IN_PRODUCTION` | 409 |
| `ERR_CREW_INACTIVE` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_INSPECTION_BUFFER_CONFLICT` | 409 |
| `ERR_PERMIT_FINAL_NEEDS_PERMIT` | 422 |
| `ERR_PCT_NOT_INCREASING` | 409 |
| `ERR_PCT_OUT_OF_RANGE` | 422 |
| `ERR_STALE_JOB_VERSION` | 412 |
| `ERR_CONTRACT_BELOW_DISBURSED` | 409 |
| `ERR_FINAL_DRAW_MISSING` | 409 |
| `ERR_FINAL_INSPECTION_MISSING` | 409 |
| `ERR_OPEN_CHANGE_ORDER` | 409 |
| `ERR_JOB_NOT_COMPLETED` | 409 |
| `ERR_WARRANTY_NOT_EXPIRED` | 409 |
| `ERR_VALIDATION` | 400 |
