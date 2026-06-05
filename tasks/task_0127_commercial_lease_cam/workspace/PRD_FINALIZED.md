# Commercial Lease & CAM Reconciliation API — Product Requirements Document

## 1. Introduction

Commercial real-estate landlords and their tenants live and die by the annual reconciliation. Throughout a lease year a tenant is billed a flat monthly estimate for its share of common-area maintenance (CAM) and operating expenses; at year-end the landlord must reconcile those forward-looking estimates against the actual expenses the property incurred, and either bill the tenant for the shortfall or credit the overage. This document specifies a REST API that governs that entire money trail — from the structure of a property and its leases, through the accrual of recoverable expenses into pools, to the year-end true-up that posts a final charge or credit to the tenant's ledger.

The system is fundamentally a **ledger-reconciliation engine layered on a pricing engine**. The same pool of expenses is run through two different algorithms — an estimated, forward-looking monthly bill and an actual, chronologically reconciled year-end figure — and the signed difference between them is the true-up. Layered on top are the pricing mechanics every commercial lease carries: base rent that escalates by a fixed percentage or a CPI index, percentage rent that kicks in once a tenant's sales clear a breakpoint, a controllable-expense cap that limits year-over-year growth on certain recoveries, a gross-up that protects the landlord in a partially-occupied building, an administrative fee, and a tenant-improvement allowance the tenant draws against. Because money is at stake and several parties touch the same reconciliation, the workflow enforces a strict segregation of duties between the property manager who prepares a reconciliation and the accountant who posts it, an optimistic-concurrency guard so a stale view is never posted, and an estoppel mechanism by which a tenant formally confirms or disputes the landlord's asserted balance.

All amounts of money in this system are integer **cents**. Square footage is integer. Rates, fractions, and index values are decimal numbers. The reader should treat every `_cents` field as an exact integer count of cents and never as a floating dollar value.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly three roles: `PropertyManager`, `Accountant`, and `Tenant`. If either header is missing, or `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

A `PropertyManager` is an opaque operator identity. When `X-User-Role` is `PropertyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for segregation-of-duties bookkeeping (for example, to remember which user submitted a reconciliation) but never compares it to any entity's `id`. The same holds for the `Accountant` role: when `X-User-Role` is `Accountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded where needed for the duties check but never matched against an entity `id`.

The `Tenant` role is entity-backed. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant` entity; ownership checks on any resource that references a `Tenant` compare the resource's tenant foreign key to `X-User-ID`. Concretely, because a `Lease` carries a `tenant_id`, a tenant-restricted action against a reconciliation or estoppel is permitted only when the referenced lease's `tenant_id` equals the caller's `X-User-ID`. A tenant acting on a lease it does not own is rejected with `ERR_NOT_LEASE_OWNER`. This ownership rule guards exactly two tenant-exclusive actions: disputing a posted reconciliation and responding to an estoppel certificate.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless explicitly stated otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. The ledger and several other listings name this ordering explicitly, but it is the default everywhere.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Two Entity Tiers

Every resource is identified by a server-minted `id`, a UUID with no type prefix; the `id` is identity only and is never an input to a business decision. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation.

The system has two tiers of entity. **Mutable entities** — `Property`, `ExpensePool`, `ExpenseLineItem`, `Tenant`, `Lease`, `TiDraw`, `Reconciliation`, and `EstoppelCertificate` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, refreshed on every mutation, including cascaded mutations driven by another entity's transition) and an integer `version` that starts at 1 and increases by exactly one on every mutation. **Append-only entities** — `SalesReport` and `LedgerEntry` — carry only `id` and `created_at`; they have neither an `updated_at` nor a `version` field, because once written they are never modified in place.

The `created_at` timestamp doubles as a tie-break ordering key in two places. When line items are processed for a pool computation they are walked in `created_at` order; and when more than one `SalesReport` exists for the same lease and year, the comparison that selects "the latest" report breaks ties by `created_at`.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents. Every calculation that produces a money figure rounds to whole cents using the **round-half-up** method (a value exactly halfway between two cents rounds up to the larger cent). Square footage is integer; rates such as `admin_fee_pct`, `escalation_rate`, `pct_rent_rate`, `controllable_cap_pct`, and `gross_up_occupancy_pct`, along with index values like `cpi_base_index` and the supplied `current_cpi_index`, are decimal numbers preserved at input precision.

Where a calculation rounds matters as much as that it rounds. Several formulas in §3 deliberately pin the order of rounding — for example, the gross-up rounds each line item before the items are summed, and the tenant's capped and non-capped slices are each rounded before they are added together rather than summed first and rounded once. These pinned orders are part of the contract; they are stated where each calculation is described.

### 2.6. Derived Fields and Cascading Consistency

Several fields are **computed** rather than supplied. The system keeps each one consistent with its inputs at all times and treats every recomputation as a mutation of its owning entity (refreshing `updated_at` and incrementing `version`).

A `Property` exposes `occupied_sqft`, the sum of `leased_sqft` across every `Lease` on that property whose `status` is `ACTIVE` or `HOLDOVER`; it is recomputed whenever a lease activates or terminates. An `ExpensePool` exposes `total_recoverable_cents`, recomputed whenever a line item is added or removed and again when the pool locks. A `Lease` exposes three derived fields: `ti_drawn_cents` (the sum of approved TI-draw amounts), `outstanding_balance_cents` (the running tenant ledger balance), and — at reconciliation post time — has its balance refreshed by the true-up posting. A `Reconciliation` exposes `pro_rata_share_pct`, `reconciled_cam_cents`, `estimated_cam_billed_cents`, and `true_up_cents`, all of which are blank until the reconciliation is posted and are snapshotted onto the record at that moment.

Because a single operation can ripple across several aggregates, the system states each cascade explicitly in §3 rather than leaving it implicit. When posting a reconciliation, for instance, the reconciliation itself, the expense pool, and the lease all mutate in one operation, and each one's `version` advances. The ordering of nested-path validation follows the same discipline: for any request whose URL names more than one resource, the resources are validated left to right, and the first identifier in the path that does not resolve to an existing resource yields `ERR_NOT_FOUND` before any deeper lookup is attempted.

### 2.7. Optimistic Concurrency Control on Reconciliation Posting

Posting a reconciliation is the one operation in this system guarded by optimistic concurrency control. The request to post an `IN_REVIEW` reconciliation must carry `expected_reconciliation_version`, a non-optional field, whose value is the `version` of the target `Reconciliation` that the client last observed. The server compares it to the reconciliation's current `version`; if they do not match, the post is rejected with `ERR_STALE_VERSION` (HTTP 412).

The reason this guard exists is the revision loop. When an accountant returns a reconciliation from `IN_REVIEW` back to `DRAFT` for correction and the property manager re-submits it, the reconciliation's `version` advances each step. A post that carries the pre-cycle version is operating on a stale view of the reconciliation's contents — the figures it would lock in no longer reflect the current draft — so it is rejected rather than allowed to overwrite work it never saw. No other endpoint takes a version field; posting is the sole place an `expected_..._version` is required.

### 2.8. Segregation of Duties

Reconciliation is a controlled, two-person process. The `PropertyManager` who drafts and submits a reconciliation prepares the figures; an `Accountant` independently reviews and posts them. The two roles are distinct, and beyond the role split there is a same-person guard: the `Accountant` who posts a reconciliation must not be the same `X-User-ID` that submitted it. A post by the submitting user, even if that user legitimately holds the `Accountant` role, is rejected with `ERR_SEGREGATION_OF_DUTIES`. This is why the system records the submitting operator's identity when a reconciliation moves into review.

### 2.9. Validation Ordering

When several checks guard one endpoint, they are evaluated in a fixed priority so that the error a client receives is deterministic. Authentication comes first: the presence and validity of the headers (`ERR_UNAUTHENTICATED`) is checked before anything else, then the role's permission to call the endpoint (`ERR_UNAUTHORIZED`), then, for the two tenant-restricted actions, lease ownership (`ERR_NOT_LEASE_OWNER`), then — on the reconciliation post specifically — the segregation-of-duties guard (`ERR_SEGREGATION_OF_DUTIES`). Existence checks come next: path resources are resolved left to right (`ERR_NOT_FOUND`), then foreign keys named in the body — `property_id`, `tenant_id`, `pool_id`, `lease_id`, and `source_reconciliation_id` — are resolved (`ERR_FK_NOT_FOUND`). Only then is the body checked for well-formedness — required fields present, enum values in range, constrained integers non-negative (`ERR_INVALID_REQUEST`). After a well-formed, authorized request reaches the resource, the state guard fires if the target is not in a state that permits the transition (`ERR_INVALID_STATE`), and on the reconciliation post the optimistic-concurrency check (`ERR_STALE_VERSION`) follows. Business-rule checks specific to each operation — year match, pool-lock, denominator, capacity, duplicate period, percentage-rent-already-run, TI allowance, estoppel balance, and dispute-note presence — are evaluated after the structural checks above. `ERR_VALIDATION` (HTTP 422) is the generic fallback for a business-rule violation that no more specific error covers.

## 3. Business Logic & Workflows

### 3.1. Properties, Tenants, and Expense Pools

The system's structural backbone is the **Property**. A property is created by a `PropertyManager` or an `Accountant` with a display `name`, a `total_rentable_sqft` (a strictly positive integer giving the building's total rentable area), and an optional `gross_up_occupancy_pct`. That last value is the assumed occupancy used later when variable expenses are grossed up — for example 0.95 for an assumed 95% occupancy — and must be greater than 0 and at most 1; when omitted it defaults to 0.95. On creation the property's `occupied_sqft` is initialized to 0 and grows only as leases activate.

A **Tenant** is the leaseholder party, created with a `legal_name` and a `contact_email` (the primary billing contact). A tenant's `id` is what a user presents as `X-User-ID` when acting in the `Tenant` role.

An **ExpensePool** aggregates one property's common-area expenses for a single reconciliation year. It is created against a `property_id` and a `pool_year` (the calendar year it covers, an integer no earlier than 2000). Two pricing knobs are set at pool creation. The `pro_rata_denominator` selects which figure becomes the denominator of every tenant's share: `TOTAL_RENTABLE` uses the property's fixed `total_rentable_sqft`, while `OCCUPIED` uses the live `occupied_sqft`; it defaults to `TOTAL_RENTABLE`. The `admin_fee_pct` is an administrative fee layered on top of recoverable expenses — for example 0.15 for 15% — between 0 and 1 inclusive, defaulting to 0.0. A new pool opens in `status` `OPEN` and its `total_recoverable_cents` starts at 0.

### 3.2. Accruing and Recovering Expenses: the Gross-Up Pool

Expenses accrue into an open pool one **ExpenseLineItem** at a time. Each line item is added under a `pool_id` and carries a `category` — one of `LANDSCAPING`, `SECURITY`, `UTILITIES`, `INSURANCE`, `MANAGEMENT`, `TAXES`, `REPAIRS`, or `SNOW_REMOVAL` — and an `amount_cents`, the gross expense as a non-negative integer. Two further attributes drive recovery. The `recoverability` is `RECOVERABLE` (the expense enters the pool), `NON_RECOVERABLE` (it is excluded entirely), or `CAPPED_CONTROLLABLE` (it is recoverable but subject to the controllable-expense cap described in §3.7); it defaults to `RECOVERABLE`. The `is_variable` flag, defaulting to false, marks an expense that varies with occupancy and is therefore eligible for gross-up; a false value marks a fixed expense that is never grossed up.

Whenever a line item is added or removed, and again when the pool is locked at posting time, the pool's `total_recoverable_cents` is recomputed. The recomputation — the **gross-up** — proceeds as follows. First the property's actual occupancy is taken as `occupied_sqft` divided by `total_rentable_sqft`, carried at full precision. The gross-up factor is the pool property's `gross_up_occupancy_pct` divided by that actual occupancy; in an under-occupied building this factor exceeds one, scaling variable costs up so the landlord recovers full variable cost despite vacancy. The system then walks every line item whose `recoverability` is either `RECOVERABLE` or `CAPPED_CONTROLLABLE` (items marked `NON_RECOVERABLE` are skipped). For a variable item, its grossed amount is its `amount_cents` multiplied by the gross-up factor, rounded half-up to whole cents at that line item. For a fixed item, the grossed amount is simply its `amount_cents`, with no gross-up applied. These per-line grossed amounts are summed into a recoverable subtotal. Finally the administrative fee is applied to that subtotal: `total_recoverable_cents` is the recoverable subtotal plus the subtotal multiplied by the pool's `admin_fee_pct`, rounded half-up to whole cents. The order is pinned and load-bearing: each variable line is rounded before the items are summed, and the admin fee is rounded once on the completed sum. Removing a line item, addressed by its `item_id` under the owning pool, is permitted only while the pool is still `OPEN`; the removal returns the pool with its recomputed total.

### 3.3. The Lease and Its Lifecycle

A **Lease** ties a tenant to space in a property and carries the full pricing configuration of the tenancy. A `PropertyManager` creates a lease under a `property_id` and a `tenant_id`, supplying the `leased_sqft` demised to the tenant (a strictly positive integer that becomes the numerator of pro-rata share) and the `base_rent_cents_annual`, the annual base rent in cents for the current lease year. A new lease begins in `status` `DRAFT` with `outstanding_balance_cents` and `ti_drawn_cents` both at 0.

The creation payload also seeds every pricing lever, each optional with a documented default. The escalation configuration is `escalation_type` (`FIXED_PCT`, `CPI`, or `NONE`, defaulting to `NONE`), `escalation_rate` (between 0 and 1 inclusive, defaulting to 0.0), and `cpi_base_index` (the baseline CPI value captured at commencement, defaulting to null). Percentage rent is configured by `pct_rent_rate` (the rate on sales above the breakpoint, 0 to 1 inclusive, default 0.0) and `pct_rent_breakpoint_cents` (the annual sales level in cents above which percentage rent accrues, a non-negative integer defaulting to 0). The controllable-cap levers are `controllable_cap_pct` (the year-over-year cap fraction on capped recoveries, 0 to 1 inclusive, default 0.0, where 0 disables the cap) and `prior_year_capped_base_cents` (the tenant's prior-year capped share that the cap grows from, non-negative integer, default 0). The tenant-improvement allowance is `ti_allowance_cents` (the total allowance the landlord commits, non-negative, default 0). And the CAM estimate is `estimated_cam_cents_monthly` (the flat monthly CAM the tenant is billed during the year, non-negative, default 0) — the forward-looking figure the year-end reconciliation trues up against.

A lease moves through `DRAFT → ACTIVE → HOLDOVER → TERMINATED` (with `TERMINATED` terminal). **Activation**, available to a `PropertyManager`, advances a lease from `DRAFT` to `ACTIVE`. It is permitted only when the lease is `DRAFT`, the referenced property and tenant both exist, and — if the lease's `escalation_type` is `CPI` — its `cpi_base_index` is not null. Activation also checks capacity: the lease's `leased_sqft` must not exceed the property's remaining capacity, which is `total_rentable_sqft` minus `occupied_sqft` at activation time; a lease that would overflow the building is rejected with `ERR_CAPACITY_EXCEEDED`. On success, the lease becomes `ACTIVE`, the property's `occupied_sqft` is increased by `leased_sqft` (recomputed, advancing the property's `version` by one), and a `BASE_RENT` ledger entry of plus the lease's `base_rent_cents_annual` is posted, refreshing `outstanding_balance_cents`.

A `PropertyManager` may move an `ACTIVE` lease into `HOLDOVER`, the state in which a tenant continues to occupy space and accrue charges past the lease term; this is permitted only from `ACTIVE` and simply sets the status. **Termination** advances a lease from `ACTIVE` or `HOLDOVER` to `TERMINATED`. It is blocked while any reconciliation for that lease is still open — that is, in `DRAFT`, `IN_REVIEW`, or `DISPUTED` — so a tenancy cannot be closed out with an unresolved reconciliation pending. On termination the lease becomes `TERMINATED` and the property's `occupied_sqft` is decreased by the lease's `leased_sqft` (recomputed, advancing the property's `version` by one).

### 3.4. Base-Rent Escalation

Each lease year a `PropertyManager` advances a lease to its next year and escalates its base rent. The new base depends on the lease's `escalation_type`. When the type is `NONE`, the base rent is left unchanged. When the type is `FIXED_PCT`, the new base is the current `base_rent_cents_annual` multiplied by one plus the lease's `escalation_rate`, rounded half-up to whole cents — a flat percentage increase regardless of any index.

When the type is `CPI`, the escalation is index-driven and collared. The request supplies `current_cpi_index`, the current index value. The raw increase fraction is the current index minus the lease's `cpi_base_index`, divided by that `cpi_base_index`. Two adjustments are then applied in a pinned order: first a floor, so a raw increase below zero is treated as zero (CPI escalation never decreases rent); then a cap, so the applied increase is the smaller of the floored raw increase and the lease's `escalation_rate`, which serves as the CPI collar. The new base is the current base rent multiplied by one plus that applied increase, rounded half-up to whole cents. Whichever branch runs, the escalation posts a `BASE_RENT` ledger entry for the delta between the new base and the old base, refreshes `outstanding_balance_cents`, and advances the lease's `version` by one.

### 3.5. Sales Reports and Percentage Rent

A tenant's percentage rent is driven by reported sales. A **SalesReport** is filed — by a `PropertyManager`, an `Accountant`, or the `Tenant` — recording a `lease_id`, a `period_year` (the calendar year the figure covers, integer no earlier than 2000), and `gross_sales_cents` (the reported gross sales for the period, a non-negative integer). A sales report is append-only and carries no version. Reports are listable and individually retrievable, optionally filtered by `lease_id` and `period_year`.

Running percentage rent for a period charges the tenant on sales above the breakpoint. A `PropertyManager` or `Accountant` triggers the run for a given `period_year`. The system locates the latest `SalesReport` for that lease and year — "latest" meaning the most recent by creation, with `created_at` as the tie-break when two reports share the period. When no `SalesReport` exists for that lease and year, the run cannot be computed; because a `SalesReport` is neither a path resource nor one of the body foreign keys named in §2.9, this is a business-rule violation with no more specific error and is rejected with `ERR_VALIDATION` (the generic 422 fallback). The excess is the report's `gross_sales_cents` minus the lease's `pct_rent_breakpoint_cents`, and if that difference is negative the excess is zero. The percentage-rent charge is that excess multiplied by the lease's `pct_rent_rate`, rounded half-up to whole cents. The breakpoint boundary is strict: only sales that exceed the breakpoint accrue rent, so sales exactly equal to the breakpoint produce zero excess and zero percentage rent. The run posts a `PCT_RENT` ledger entry of the computed charge, refreshes `outstanding_balance_cents`, and advances the lease's `version`. A second run for a lease-and-year pair that has already been run is rejected with `ERR_PCT_RENT_ALREADY_RUN`.

### 3.6. Tenant-Improvement Draws

Against a lease's committed allowance, a tenant or property manager **requests** a tenant-improvement draw — a **TiDraw** — under a `lease_id` for an `amount_cents` (a strictly positive integer drawn against the allowance). A new draw begins in `status` `REQUESTED` and moves to either `APPROVED` or `REJECTED`, both terminal.

Only an `Accountant` decides a draw. **Approval** is permitted when the draw is `REQUESTED`, the referenced lease is `ACTIVE` or `HOLDOVER`, and the remaining allowance covers it — that is, the lease's current `ti_drawn_cents` plus this draw's `amount_cents` does not exceed the lease's `ti_allowance_cents`. A draw that would push cumulative draws past the allowance is rejected with `ERR_TI_ALLOWANCE_EXCEEDED`. On approval the draw becomes `APPROVED`, the lease's `ti_drawn_cents` is recomputed to include this draw (advancing the lease's `version`), and a `TI_DRAW` ledger entry of minus the draw's `amount_cents` is posted as a landlord-funded credit to the tenant, refreshing `outstanding_balance_cents`. **Rejection**, permitted whenever the draw is still `REQUESTED`, simply sets the draw to `REJECTED` with no ledger effect.

### 3.7. The Year-End Reconciliation and True-Up

The heart of the system is the annual reconciliation, where the estimated CAM a tenant was billed all year is reconciled against the tenant's actual share of the property's recoverable expenses. A `PropertyManager` creates a **Reconciliation** linking a `lease_id`, a `pool_id`, and a `recon_year`. The reconciliation year must equal the referenced pool's `pool_year`; a mismatch is rejected with `ERR_YEAR_MISMATCH`, both at creation and at submission. A second reconciliation for a lease-and-year pair already covered by a posted reconciliation is rejected with `ERR_DUPLICATE_RECON_PERIOD`. A new reconciliation begins in `status` `DRAFT`.

A reconciliation travels a cyclic path: `DRAFT → IN_REVIEW`, with a revision loop back to `DRAFT`, then `IN_REVIEW → POSTED`, a dispute cycle `POSTED → DISPUTED → POSTED`, and a `DISPUTED → VOID` exit (`VOID` terminal). **Submission**, by the `PropertyManager`, advances a `DRAFT` reconciliation to `IN_REVIEW`; it requires that the reconciliation be `DRAFT`, that the referenced lease be `ACTIVE` or `HOLDOVER`, and that the reconciliation year still match the pool year. An `Accountant` may **return** an `IN_REVIEW` reconciliation to `DRAFT` for correction; this revision step sets the status back to `DRAFT` and advances the reconciliation's `version` by one — which is precisely what makes a later post carrying a pre-return version stale (see §2.7).

**Posting**, restricted to an `Accountant`, is the decisive transition from `IN_REVIEW` to `POSTED`. The post must carry `expected_reconciliation_version` matching the reconciliation's current `version`, or it is rejected with `ERR_STALE_VERSION`. The posting accountant must not be the user who submitted the reconciliation, or it is rejected with `ERR_SEGREGATION_OF_DUTIES`. The referenced pool must still be `OPEN`; a pool already locked by another reconciliation yields `ERR_POOL_LOCKED`. The pro-rata denominator must be positive before any share is computed — if the selected denominator (`total_rentable_sqft` or `occupied_sqft` per the pool's `pro_rata_denominator`) is zero, the share is undefined and the post is rejected with `ERR_EMPTY_DENOMINATOR`; the same denominator guard protects the read-only preview.

When all guards pass, the post computes and snapshots four figures, then cascades. **Pro-rata share** is the lease's `leased_sqft` divided by the pool's denominator, where the denominator belongs to the pool's property (the property whose id is the pool's `property_id`, not the lease's) and is the property's `total_rentable_sqft` when the pool's `pro_rata_denominator` is `TOTAL_RENTABLE` or its live `occupied_sqft` when `OCCUPIED`. Choosing `OCCUPIED` yields a smaller denominator and therefore a larger share; a zero occupancy under that basis raises `ERR_EMPTY_DENOMINATOR`. The share is kept at full precision and is not rounded on its own; rounding happens once, at the end, on money.

The **controllable cap** is applied next, to the tenant's share of the capped slice rather than to the pool total. The capped slice is the sum, over the pool's `CAPPED_CONTROLLABLE` line items, of each item's grossed amount exactly as computed in the gross-up (variable items grossed and rounded per line, fixed items at face), with no administrative fee on this slice. The tenant's capped share is the pro-rata share multiplied by that capped slice, rounded half-up. When the lease's `controllable_cap_pct` is greater than zero and its `prior_year_capped_base_cents` is greater than zero, a ceiling is computed as `prior_year_capped_base_cents` multiplied by one plus `controllable_cap_pct`, rounded half-up, and the allowed capped amount is the smaller of the tenant's capped share and that ceiling. The cap binds only when the tenant's capped share strictly exceeds the ceiling; a share exactly equal to the ceiling is allowed in full. When the cap is disabled — either lever at zero — the allowed capped amount is simply the tenant's capped share.

The **reconciled CAM** combines the two slices. The non-capped slice of the pool is its `total_recoverable_cents` less the capped slice's grossed amount and less the administrative fee that would apply to that capped grossed amount (the capped grossed amount multiplied by the pool's `admin_fee_pct`, rounded half-up) — leaving exactly the recoverable-plus-admin amount attributable to ordinary `RECOVERABLE` items. The tenant's non-capped portion is the pro-rata share multiplied by that non-capped pool amount, rounded half-up. The capped portion the tenant actually owes is the allowed capped amount plus its administrative fee (the allowed amount multiplied by `admin_fee_pct`, rounded half-up). The reconciled CAM, `reconciled_cam_cents`, is the sum of those two rounded portions — and the order is pinned: each tenant slice is rounded first, then the two are added, never summed and rounded once.

The **estimated CAM billed**, `estimated_cam_billed_cents`, is twelve times the lease's `estimated_cam_cents_monthly` — the forward-looking estimate the tenant paid in twelve equal monthly installments over the year, independent of actual pool expenses. The **true-up**, `true_up_cents`, is `reconciled_cam_cents` minus `estimated_cam_billed_cents`: a positive figure means the tenant under-paid and now owes the difference (a debit), a negative figure means the tenant over-paid and is owed a credit. These four computed values — `pro_rata_share_pct`, `reconciled_cam_cents`, `estimated_cam_billed_cents`, and `true_up_cents` — are snapshotted onto the reconciliation as it posts. A read-only **preview** computes and returns the same four figures without posting, as a dry run for the property manager or accountant.

Posting then cascades across three aggregates. The reconciliation's status becomes `POSTED` and its `version` advances by one. The pool's `status` is set to `LOCKED`, its `total_recoverable_cents` is recomputed, and its `version` advances by one. And a `CAM_TRUEUP` ledger entry of the signed `true_up_cents` is posted with its `source_reconciliation_id` set to this reconciliation's `id`, after which the lease's `outstanding_balance_cents` is recomputed and the lease's `version` advances by one.

### 3.8. Disputes, Resolution, and Voids

Once a reconciliation is `POSTED`, the tenant on the lease may contest it. **Disputing** is exclusive to the `Tenant`, who must own the referenced lease (its `tenant_id` equal to the caller's `X-User-ID`, else `ERR_NOT_LEASE_OWNER`), and is permitted only from `POSTED`; it sets the reconciliation to `DISPUTED`. From there an `Accountant` has two exits. **Resolving** a dispute re-affirms the posting, returning the reconciliation from `DISPUTED` straight back to `POSTED` with no ledger change — the cyclic `POSTED → DISPUTED → POSTED` path. Alternatively the accountant may **void** a disputed posting, advancing it from `DISPUTED` to the terminal `VOID`. A void is a compensation that exactly reverses the original posting: it posts a `CREDIT_ADJUSTMENT` ledger entry of minus the same `true_up_cents` (the exact reversal of the `CAM_TRUEUP` entry) with `source_reconciliation_id` set to this reconciliation's `id`, recomputes the lease's `outstanding_balance_cents`, and advances the lease's `version`; it also reopens the pool, setting its `status` back to `OPEN`, recomputing `total_recoverable_cents`, and advancing the pool's `version`. The pool's `OPEN → LOCKED` transition therefore happens system-side when a reconciliation against it posts, and the reverse `LOCKED → OPEN` happens when that posting reconciliation is voided.

### 3.9. The Tenant Ledger and Outstanding Balance

Every charge and credit a lease accrues lands on its ledger as a **LedgerEntry**, an append-only record carrying a `lease_id`, an `entry_type`, a signed `amount_cents`, and an optional `source_reconciliation_id`. The `entry_type` is one of `BASE_RENT`, `PCT_RENT`, `CAM_ESTIMATE`, `CAM_TRUEUP`, `TI_DRAW`, `PAYMENT`, or `CREDIT_ADJUSTMENT`. The amount is signed by convention: a positive amount increases the tenant's balance (a charge), a negative amount decreases it (a payment or credit). The `source_reconciliation_id` is set only on a `CAM_TRUEUP` entry and on the reversing `CREDIT_ADJUSTMENT` from a void, linking the entry back to the reconciliation that produced it; it is null on all other entries.

The lease's `outstanding_balance_cents` is the running sum of every ledger entry's `amount_cents` for that lease, recomputed on every posting. The ledger is listable per lease in chronological order — `created_at` ascending — and the entries sourced by a particular reconciliation are separately listable. A tenant **payment** is recorded by a `PropertyManager` or `Accountant` as an `amount_cents`; it posts a `PAYMENT` ledger entry of minus that amount, recomputes `outstanding_balance_cents`, and advances the lease's `version`.

### 3.10. Estoppel Certificates

An estoppel is a formal request for a tenant to confirm the state of its lease. A `PropertyManager` or `Accountant` issues an **EstoppelCertificate** for a `lease_id`, asserting two figures the tenant is asked to confirm: `asserted_balance_cents`, a snapshot of the lease's `outstanding_balance_cents` at issuance, and `asserted_base_rent_cents_annual`, the asserted current annual base rent. A new certificate begins in `status` `ISSUED` with `tenant_response` and `dispute_note` both unset.

Only the owning `Tenant` may **respond**, and only to an `ISSUED` certificate. The response carries `tenant_response`, either `CONFIRMED` or `DISPUTED`. A `CONFIRMED` response is accepted only when the certificate's `asserted_balance_cents` equals the referenced lease's live `outstanding_balance_cents`; if the asserted figure no longer matches the live ledger, the confirmation is rejected with `ERR_ESTOPPEL_BALANCE_MISMATCH`. A successful confirmation sets `tenant_response` to `CONFIRMED` and the certificate `status` to `CONFIRMED`. A `DISPUTED` response requires a non-empty `dispute_note`; a dispute submitted without one is rejected with `ERR_DISPUTE_NOTE_REQUIRED`. A valid dispute sets `tenant_response` to `DISPUTED`, stores the supplied `dispute_note`, and moves the certificate `status` to `DISPUTED`. Both `CONFIRMED` and `DISPUTED` are terminal. As with reconciliation disputes, a tenant responding to an estoppel on a lease it does not own is rejected with `ERR_NOT_LEASE_OWNER`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a property, tenant, expense pool, line item, lease, sales report, TI draw, reconciliation, estoppel, or a ledger entry recorded as a payment) return `201 Created`. Operations that modify an existing resource — every state transition, escalation, percentage-rent run, line-item removal, and the like — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/properties` | Create a property | PropertyManager, Accountant |
| GET | `/properties/{id}` | Fetch a property | PropertyManager, Accountant, Tenant |
| GET | `/properties` | List properties | PropertyManager, Accountant |
| GET | `/properties/{id}/leases` | List leases on a property | PropertyManager, Accountant |
| GET | `/properties/{id}/expense-pools` | List expense pools on a property | PropertyManager, Accountant |
| POST | `/tenants` | Create a tenant | PropertyManager, Accountant |
| GET | `/tenants/{id}` | Fetch a tenant | PropertyManager, Accountant, Tenant |
| GET | `/tenants/{id}/leases` | List leases for a tenant | PropertyManager, Accountant, Tenant |
| POST | `/expense-pools` | Create an expense pool for a property/year | PropertyManager, Accountant |
| GET | `/expense-pools/{id}` | Fetch an expense pool | PropertyManager, Accountant, Tenant |
| POST | `/expense-pools/{id}/line-items` | Add an expense line item to a pool | PropertyManager, Accountant |
| GET | `/expense-pools/{id}/line-items` | List line items on a pool | PropertyManager, Accountant |
| DELETE | `/expense-pools/{id}/line-items/{item_id}` | Remove a line item from an OPEN pool | PropertyManager, Accountant |
| POST | `/leases` | Create a lease in DRAFT | PropertyManager |
| GET | `/leases/{id}` | Fetch a lease | PropertyManager, Accountant, Tenant |
| POST | `/leases/{id}/activate` | Activate a DRAFT lease | PropertyManager |
| POST | `/leases/{id}/holdover` | Move an ACTIVE lease to HOLDOVER | PropertyManager |
| POST | `/leases/{id}/terminate` | Terminate an ACTIVE/HOLDOVER lease | PropertyManager |
| POST | `/leases/{id}/escalate` | Advance the lease one year and escalate base rent | PropertyManager |
| POST | `/leases/{id}/percentage-rent-run` | Run percentage rent for a period | PropertyManager, Accountant |
| GET | `/leases/{id}/ledger` | List ledger entries for a lease (created_at ascending) | PropertyManager, Accountant, Tenant |
| POST | `/leases/{id}/payments` | Record a tenant payment | PropertyManager, Accountant |
| POST | `/sales-reports` | File a gross-sales report for a lease/period | PropertyManager, Accountant, Tenant |
| GET | `/sales-reports/{id}` | Fetch a single sales report | PropertyManager, Accountant, Tenant |
| GET | `/sales-reports` | List sales reports (filterable) | PropertyManager, Accountant, Tenant |
| POST | `/ti-draws` | Request a TI draw against a lease allowance | PropertyManager, Tenant |
| GET | `/ti-draws/{id}` | Fetch a single TI draw | PropertyManager, Accountant, Tenant |
| GET | `/ti-draws` | List TI draws (filterable) | PropertyManager, Accountant, Tenant |
| POST | `/ti-draws/{id}/approve` | Approve a requested TI draw | Accountant |
| POST | `/ti-draws/{id}/reject` | Reject a requested TI draw | Accountant |
| POST | `/reconciliations` | Create a reconciliation (DRAFT) | PropertyManager |
| GET | `/reconciliations/{id}` | Fetch a reconciliation | PropertyManager, Accountant, Tenant |
| GET | `/reconciliations` | List reconciliations (filterable) | PropertyManager, Accountant, Tenant |
| GET | `/reconciliations/{id}/preview` | Preview true-up figures without posting | PropertyManager, Accountant |
| POST | `/reconciliations/{id}/submit` | Submit a DRAFT reconciliation for review | PropertyManager |
| POST | `/reconciliations/{id}/return` | Return an IN_REVIEW reconciliation to DRAFT | Accountant |
| POST | `/reconciliations/{id}/post` | Post an IN_REVIEW reconciliation (OCC + segregation) | Accountant |
| POST | `/reconciliations/{id}/dispute` | Tenant disputes a POSTED reconciliation | Tenant |
| POST | `/reconciliations/{id}/resolve-dispute` | Accountant resolves a dispute, re-affirming POSTED | Accountant |
| POST | `/reconciliations/{id}/void` | Accountant voids a DISPUTED reconciliation | Accountant |
| GET | `/reconciliations/{id}/ledger-entries` | List ledger entries sourced by a reconciliation | PropertyManager, Accountant, Tenant |
| POST | `/estoppels` | Issue an estoppel certificate for a lease | PropertyManager, Accountant |
| GET | `/estoppels/{id}` | Fetch an estoppel certificate | PropertyManager, Accountant, Tenant |
| GET | `/estoppels` | List estoppels (filterable) | PropertyManager, Accountant, Tenant |
| POST | `/estoppels/{id}/respond` | Tenant responds CONFIRMED or DISPUTED | Tenant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_LEASE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_YEAR_MISMATCH` | 422 |
| `ERR_POOL_LOCKED` | 409 |
| `ERR_EMPTY_DENOMINATOR` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_DUPLICATE_RECON_PERIOD` | 409 |
| `ERR_PCT_RENT_ALREADY_RUN` | 409 |
| `ERR_TI_ALLOWANCE_EXCEEDED` | 422 |
| `ERR_ESTOPPEL_BALANCE_MISMATCH` | 422 |
| `ERR_DISPUTE_NOTE_REQUIRED` | 422 |
| `ERR_VALIDATION` | 422 |
