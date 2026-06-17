# Flooring Sales & Installation API — Product Requirements Document

## 1. Introduction

This document specifies the Flooring Sales & Installation platform, a back-office system that carries a residential flooring project from the first showroom conversation all the way through to a finished, warranted installation. A homeowner browsing hardwood, luxury vinyl plank, tile, or carpet wants a price; the dealer wants that price to be honest about what the floor will actually cost once a crew has measured the rooms, torn out the old surface, accounted for cutting waste, and put a date on the calendar. The hard part is that the cheap, fast quote a salesperson gives over the phone and the binding number the customer signs are computed from different facts — declared square footage versus measured square footage, no waste versus a category-specific overage factor, no tear-out versus haul-away labor — and the system must keep both numbers coherent as the job evolves.

The API is built around a small set of peer resources — products in the catalog, jobs, estimates, material orders, install crews, install slots, and warranty claims — that reference one another by identifier rather than by nesting. Around those resources sits a pricing engine that re-prices on every measurement, a scheduling engine that protects crew capacity and travel time, and a temporal layer that governs lead times, estimate expiry, and warranty windows. Because several roles touch the same job at different stages — a sales rep who owns the paperwork, an estimator who owns the tape measure, a scheduler who owns the crews, a homeowner who signs, and an administrator who owns the catalog and adjudicates claims — the system enforces strict ownership and concurrency rules so that two people working the same job never silently overwrite each other's work.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that govern every endpoint. Unless a later business-logic subsection overrides a detail for a specific workflow, the rules here always apply.

### 2.1. User and Role-Based Access Control

Every request other than the two self-registration calls must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which they are acting. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes five roles, spelled exactly: `Admin`, `SalesRep`, `Estimator`, `Scheduler`, and `Customer`. A sixth designation, `Anonymous`, denotes an unauthenticated caller and applies only to the two registration endpoints, which accept requests with no user-context headers at all. When a recognized user invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of the five roles are tied to a persisted entity, and the rest are operator identities. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare that resource's owning `customer_id` (reached through the job the resource belongs to) to `X-User-ID`. When `X-User-Role` is `SalesRep`, `X-User-ID` is the `id` of the acting `SalesRep`; a job records the rep who owns it in `sales_rep_id`. When `X-User-Role` is `Admin`, `Estimator`, or `Scheduler`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server accepts it for authentication but does not compare it against any entity's `id`. Ownership is enforced specifically when a `Customer` accepts an estimate or files a warranty claim: the acting `X-User-ID` must equal the `customer_id` of the job in question, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single page returns; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system — `Product`, `Job`, `Estimate`, `MaterialOrder`, `InstallCrew`, `InstallSlot`, and `WarrantyClaim` — carry a uniform set of system-managed fields. Every one has an `id` that is a server-minted UUID with no type prefix, used purely as identity and never as a business-decision input. Every one has a `created_at` timestamp, written once at creation as an ISO 8601 UTC instant with three fractional digits. Every one has an `updated_at` timestamp, also ISO 8601 UTC with three fractional digits, refreshed on every mutation — including mutations that happen as a side effect of an operation on a different resource. And every one has a `version`, an integer that begins at 1 when the resource is created and increments by exactly one on each mutation.

Two resources are deliberately lighter. The `Customer` and the `SalesRep` are registration records that, once created, are not mutated through this API: each carries only an `id` (a server-minted UUID, with no type prefix) and a `created_at` timestamp. Neither carries an `updated_at` field nor a `version` field; both are absent for these two resources.

When a resource is created from scratch, the response uses HTTP 201. When an existing resource is modified — including state transitions and computed-field recomputations — the response uses HTTP 200. Whenever the server recomputes a derived field such as `waste_factor_pct` or `warranty_risk_score`, that recomputation is itself a mutation that refreshes `updated_at` and increments `version` on the resource that owns the field.

### 2.5. Cascades, Hierarchical Consistency, and Left-to-Right Path Validation

The resources are peers linked by foreign keys rather than nested under one another, but operations on a job routinely cascade into its dependent estimates, material order, and install slots, all resolved within the single triggering request. When a cascade sets a child resource to a new state, that child is independently mutated: its `updated_at` is refreshed and its `version` is incremented, exactly as if it had been changed directly. The cascading effects of measurement, acceptance, re-measure, and cancellation are described in detail in §3; the principle here is simply that no cascade leaves a touched resource's timestamps or version stale.

For any endpoint whose path carries a resource identifier, the server validates existence left to right: the path identifier is checked first, and only then are foreign keys referenced in the request body resolved. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404), before any business rule is evaluated. List endpoints that hang off a parent — a job's estimates, a job's material orders, a job's install slots, a job's warranty claims, or a crew's install slots — likewise reject with `ERR_NOT_FOUND` when the parent identifier in the path does not exist.

### 2.6. Money, Square-Footage, and Rounding Precision

All monetary amounts are held and returned as integer cents — `material_cost_cents`, `underlayment_cost_cents`, `labor_cost_cents`, and `total_cents` on an estimate, and the per-square-foot rate fields `material_cost_per_sqft_cents`, `labor_rate_per_sqft_cents`, and `underlayment_cost_per_sqft_cents` on a product, are all integers. When a cost line is computed from a real-valued square footage multiplied by a per-square-foot rate, the result is rounded to whole cents using round half up.

Square-footage quantities are real numbers. The waste/overage percentage `waste_factor_pct` is kept to one decimal place using round half up. Where the estimate computation inflates measured area by the waste factor to produce `billable_sqft`, that billable area is rounded to two decimal places using round half up before any cost line is computed from it. The exact ordering of these roundings is part of the pricing contract and is specified in §3.

### 2.7. Optimistic Concurrency on Estimate Issuance

Issuing a measured estimate is the one operation in the system guarded by optimistic concurrency control, because it is the point at which a freshly built estimate supersedes whatever estimate was previously live on the job, and two reps could otherwise clobber each other's work. The issue request must carry `expected_job_version`, the value of the target job's `version` that the client last observed. If that value does not equal the job's current `version` — because another writer has advanced the job since the client read it, for instance by issuing a competing estimate — the issue is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412), so the client cannot supersede an estimate it never saw. No other endpoint takes a version field; only estimate issuance carries `expected_job_version` and only it performs this check.

### 2.8. The Lazy Clock and Time-Gated Operations

Several rules are gated on the passage of time: an estimate expires after its `valid_until` instant, ordered material cannot be received before its `expected_ready_date`, and a warranty claim is only approvable inside its job's warranty window. The system never advances these states on its own through a background process; each fires only when an operation is invoked while the current clock has reached the relevant instant. Estimate expiry in particular is lazy — an estimate moves to `EXPIRED` only when an expire-check is invoked at or after `valid_until`. For deterministic testing, an administrative capability sets the server's current UTC clock to a supplied instant carried as `to_iso8601`; all subsequent time-gated comparisons use that clock.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Products and Their Cost Structure

Everything prices off a catalog `Product`, which an `Admin` creates. A product is registered with a `sku`, a display `name`, a `category` that is one of `HARDWOOD`, `LVP`, `TILE`, or `CARPET`, a wholesale `material_cost_per_sqft_cents`, a base `labor_rate_per_sqft_cents`, and a `warranty_years` count of whole years of manufacturer coverage. Two pricing aspects are optional at create time with defined defaults: `requires_underlayment` defaults to false, and `underlayment_cost_per_sqft_cents` defaults to 0; `lead_time_days`, the vendor lead time in days for a special order (0 meaning the product is stocked), also defaults to 0. The per-square-foot material and labor rates must each be at least 1 cent. The `warranty_years` and `lead_time_days` values must each be at least 0. Underlayment cost must be internally consistent with its flag: when `requires_underlayment` is false the `underlayment_cost_per_sqft_cents` must be 0, and when it is true the underlayment cost must be at least 1 cent. Any violation of these numeric, enum, or consistency bounds — here and on every create or measure endpoint — is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

A product's `sku` must be unique among products that are not discontinued; the codes are case-sensitive, and a create whose `sku` collides with an existing active product is rejected with `ERR_DUPLICATE_KEY` (HTTP 409). A new product comes into the world with `status` of `ACTIVE`. An `Admin` may later retire a product, transitioning its `status` from `ACTIVE` to `DISCONTINUED`, which bumps the product's `version`. That retirement is blocked while any job that references the product is still live — that is, while any referencing job sits in `DRAFT`, `MEASURED`, `RE_MEASURE`, `ESTIMATED`, `ACCEPTED`, or `IN_INSTALL` — so that in-flight estimates are never undermined by a vanished product; an attempt to discontinue from any state other than `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). Products are readable by every authenticated role and can be listed with an optional `category` filter and an optional `status` filter.

### 3.2. Opening a Job and the Provisional Quote

Before a job can be opened, the two human actors it references must exist as records. A homeowner self-registers as a `Customer` with a `full_name`, an install-site `address`, and a contact `email`; the email is unique among customers, compared case-insensitively, and a duplicate is rejected with `ERR_DUPLICATE_KEY`. A sales representative self-registers as a `SalesRep` with a `name`. Both registrations are open to an unauthenticated caller (and to an `Admin`), and each record carries only its `id` and `created_at`.

A `SalesRep` opens a `Job` by supplying a `customer_id`, a `sales_rep_id`, a `product_id`, and a `declared_sqft` — the rough square footage the customer reports before anyone has measured. The declared figure must be greater than 0. The referenced product must be `ACTIVE` at the moment the job is created; if it has been discontinued, the create is rejected with `ERR_PRODUCT_DISCONTINUED` (HTTP 409). A new job starts in `DRAFT` status.

While the job is still in `DRAFT`, a sales rep can produce a fast, non-binding quote by creating an `Estimate` with `variant` `PROVISIONAL`. A provisional estimate prices off the declared area with no waste factor and no tear-out labor: its `billable_sqft` is exactly the job's `declared_sqft`; its `material_cost_cents` is `declared_sqft` multiplied by the product's per-square-foot material rate, rounded to whole cents half up; its `underlayment_cost_cents` is `declared_sqft` multiplied by the product's per-square-foot underlayment rate rounded the same way when the product requires underlayment, and 0 otherwise; its `labor_cost_cents` is `declared_sqft` multiplied by the product's per-square-foot labor rate, rounded to whole cents half up; and its `total_cents` is the sum of those three rounded line items. A provisional estimate may only be created while the job is in `DRAFT`; attempting to create a `PROVISIONAL` estimate for a job that has already been measured (or vice versa, a `MEASURED` estimate for a job still in `DRAFT`) is rejected with `ERR_VARIANT_STATE_MISMATCH` (HTTP 409). Every estimate is created in `DRAFT` status and records the `job_id` it prices and a `valid_until` instant supplied by the caller.

### 3.3. The In-Home Measure and the Waste Factor

An `Estimator` performs the in-home measure, recording three numbers on the job: `measured_sqft`, `tear_out_sqft`, and `room_count`. Measuring a job in `DRAFT` advances it `DRAFT → MEASURED`; the same measure operation also closes the re-measure loop by advancing a job from `RE_MEASURE → MEASURED` (re-measure is described in §3.4). In both cases the supplied geometry is written onto the job — set on the first measure, overwritten on a re-measure — and the operation requires `measured_sqft` greater than 0, `tear_out_sqft` at least 0, and `room_count` at least 1; out-of-bound geometry is rejected with `ERR_INVALID_REQUEST`. A measure attempted from any state other than `DRAFT` or `RE_MEASURE` is rejected with `ERR_INVALID_STATE`. The measure bumps the job's `version`.

The defining product of the measure is the job's `waste_factor_pct`, an overage percentage applied to material area to cover cutting and seams. It is computed and stored at measure time (and recomputed on every re-measure) and is null until the job has been measured. The factor is the sum of three components. First, a category base: 10.0 percent for `HARDWOOD`, 8.0 percent for `LVP`, 12.0 percent for `TILE`, and 5.0 percent for `CARPET`. Second, a seam allowance for multi-room jobs: each room beyond the first adds 1.0 percent — that is, one less than `room_count`, multiplied by 1.0 — but this seam allowance is capped so it can never exceed 6.0 percent. Third, a large-area surcharge: a flat 3.0 percent is added when the product's category is `TILE` or `HARDWOOD` and the measured area is strictly greater than 600 square feet; an area of exactly 600 does not trigger it, and the surcharge is 0 for `LVP` and `CARPET` regardless of area. The three components are summed and the result is kept to one decimal place, rounded half up.

### 3.4. Re-Measure: Disputing the Numbers

When a customer disputes a measurement, a `SalesRep` can send the job back for a re-measure, transitioning it to `RE_MEASURE`. This entry is reachable from two states: from `MEASURED` (the measure was taken but no estimate has yet been issued) and from `ESTIMATED` (an estimate was already issued). In both cases the transition is identical in effect: the job moves to `RE_MEASURE`, the job's `version` is bumped, and as a cascade the job's currently `ISSUED` estimate, if one exists, is voided — moved to `VOIDED`. A request to re-measure a job in any status other than `MEASURED` or `ESTIMATED` is rejected with `ERR_INVALID_STATE`. The loop closes when the estimator measures again, returning the job from `RE_MEASURE → MEASURED` with fresh geometry and a recomputed waste factor. The system remembers whether a job ever passed through `RE_MEASURE`, because that fact feeds the warranty risk score at completion.

### 3.5. The Measured Estimate, Issuance, and Concurrency

Once a job is `MEASURED`, a `SalesRep` builds the binding number by creating an `Estimate` with `variant` `MEASURED`, which may only be created while the job is in `MEASURED` or `ESTIMATED` status; the wrong variant for the job's state is rejected with `ERR_VARIANT_STATE_MISMATCH`. A measured estimate prices off the measured geometry, the waste factor, and the tear-out labor, with the rounding order pinned: each line item is rounded to whole cents first, and only then are the lines summed. The `billable_sqft` is the measured area inflated by the waste factor — measured square footage multiplied by one plus `waste_factor_pct` divided by 100 — and that billable area is rounded to two decimal places (half up) before any cost is computed. The `material_cost_cents` is `billable_sqft` multiplied by the product's per-square-foot material rate, rounded to whole cents half up. The `underlayment_cost_cents` is `billable_sqft` multiplied by the product's per-square-foot underlayment rate rounded to whole cents half up when the product requires underlayment, and 0 otherwise.

Labor on a measured estimate is computed over installed area, not billable area, and adds haul-away. The install-labor portion is the measured square footage — not the waste-inflated `billable_sqft` — multiplied by the product's per-square-foot labor rate, rounded to whole cents half up. The tear-out/haul-away portion is the job's tear-out square footage multiplied by a fixed tear-out labor rate of 150 cents per square foot, rounded to whole cents half up. The estimate's `labor_cost_cents` is the sum of those two rounded labor amounts, and the `total_cents` is the sum of the rounded material, underlayment, and labor lines.

Issuing the estimate is the act that makes it live, and it is the concurrency-guarded operation of §2.7. To issue, a sales rep submits `expected_job_version`. The estimate must be in `DRAFT`, its `variant` must be `MEASURED`, and its `valid_until` must be strictly after the current clock — a `valid_until` at or before now is rejected with `ERR_VALID_UNTIL_IN_PAST` (HTTP 422). The submitted `expected_job_version` must equal the job's current `version`, or the issue is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). When these hold, the estimate moves `DRAFT → ISSUED`, and any estimate that was previously `ISSUED` on the same job is voided to `VOIDED`, because a job may have only one issued estimate at any time. The first issue against a `MEASURED` job bubbles the job up `MEASURED → ESTIMATED`; a subsequent issue against a job already in `ESTIMATED` leaves the job in `ESTIMATED` while superseding the prior issued estimate. Either way the job's `version` increments — which is precisely why a second rep holding a stale view fails the version check. Issuing from a non-`DRAFT` estimate, or when the job is in neither `MEASURED` nor `ESTIMATED`, is rejected with `ERR_INVALID_STATE`.

### 3.6. Acceptance and the Birth of the Material Order

Only the `Customer` who owns the job may accept its estimate, and acceptance is what commits the project. The estimate being accepted must be `ISSUED`, must be of `variant` `MEASURED`, and the current clock must be strictly before its `valid_until`; an acceptance at or after `valid_until` is rejected with `ERR_ESTIMATE_EXPIRED` (HTTP 409), and an acceptance by anyone whose `X-User-ID` is not the job's `customer_id` is rejected with `ERR_NOT_RESOURCE_OWNER`. Acceptance requires the job to be in `ESTIMATED`; otherwise it is rejected with `ERR_INVALID_STATE`. On success, the estimate moves `ISSUED → ACCEPTED`, the job advances `ESTIMATED → ACCEPTED`, and the job's `version` is bumped.

Acceptance forks the workflow by spawning a `MaterialOrder`. The new order starts in `ORDERED` status, records its `job_id` and a `product_id` copied from the job, takes an `order_sqft` copied from the accepted measured estimate's `billable_sqft`, and snapshots a `lead_time_days` copied from the product's lead time at this moment. Its `backorder_count` starts at 0. The order's `expected_ready_date` is computed as the current clock plus `lead_time_days` whole calendar days — that is, the clock instant plus the lead time multiplied by 86,400 seconds — expressed as an ISO 8601 UTC instant with three fractional digits. This ready date is the gate that scheduling must clear before the material can be received.

### 3.7. Special Orders: Backorder, Reorder, and Receipt

A `Scheduler` manages the material order through its special-order lifecycle. When a vendor reports a stock-out, the scheduler moves an order `ORDERED → BACKORDERED`, which increments the order's `backorder_count` by one and bumps its `version`. When stock returns, the scheduler reorders, moving it `BACKORDERED → ORDERED` and recomputing `expected_ready_date` as the current clock plus the snapshotted `lead_time_days` whole days — pushing the ready date out from the moment of reorder. Each backorder cycle is remembered in `backorder_count`, which later feeds the warranty risk score. A backorder is only legal from `ORDERED`, and a reorder only from `BACKORDERED`; the wrong starting state yields `ERR_INVALID_STATE`.

Receiving the material moves it `ORDERED → RECEIVED`, but only once the clock has caught up: the current clock must be at or after the order's `expected_ready_date`. A receipt attempted before the ready date is rejected with `ERR_MATERIAL_NOT_READY` (HTTP 409). Reaching `RECEIVED` is what unlocks the start of installation for the job. Separately, when a job is cancelled, its material order is force-cancelled as part of the teardown described in §3.10.

### 3.8. Crews, Slots, and Protecting Capacity

A `Scheduler` registers an `InstallCrew` with a display `name`, a non-empty `skill_categories` array whose elements are each drawn from `HARDWOOD`, `LVP`, `TILE`, and `CARPET`, a `daily_sqft_capacity` that must be greater than 0, and an optional `buffer_minutes` travel/cleanup buffer that defaults to 0 and must be at least 0. A crew starts `AVAILABLE`. A scheduler may deactivate an `AVAILABLE` crew, moving it `AVAILABLE → INACTIVE`, but only when none of the crew's slots are currently `SCHEDULED`; deactivating a crew that still holds a scheduled slot, or one not in `AVAILABLE`, is rejected with `ERR_INVALID_STATE`.

Scheduling an `InstallSlot` ties a job to a crew over a time window and is the most heavily validated create in the system. The request supplies a `job_id`, a `crew_id`, a `start_at`, and an `end_at`. The new slot starts `SCHEDULED`, and its `scheduled_sqft` — the billable area it consumes against the crew's daily capacity — is copied from the job's accepted measured estimate's `billable_sqft`. The validations are applied in a deliberate order. First, the job must be `ACCEPTED` and must have an accepted measured estimate to source `scheduled_sqft` from; a slot create for a job that is not accepted is rejected with `ERR_JOB_NOT_ACCEPTED` (HTTP 409), and this is checked before slot geometry because `scheduled_sqft` is otherwise undefined. Next, the crew's `skill_categories` must include the job's product category, or the create is rejected with `ERR_CREW_SKILL_MISMATCH` (HTTP 409). Then `start_at` must be strictly before `end_at`, with both present; an inverted or degenerate interval is rejected with `ERR_INVALID_INTERVAL` (HTTP 422).

After the interval is well-formed, two overlap checks and a capacity check follow, in this order. The job must not already have another `SCHEDULED` install slot whose closed interval shares any instant with the candidate's closed interval — a single job cannot be installed in two places at once, treating both endpoints as inclusive — and a collision here is rejected with `ERR_JOB_SLOT_OVERLAP` (HTTP 409). The crew must be free: the candidate's half-open interval from `start_at` up to `end_at` must not overlap any of the crew's `SCHEDULED` slots once each existing slot is expanded by the crew's `buffer_minutes` on each side, so that travel and cleanup time is honored; a conflict is rejected with `ERR_CREW_TIME_CONFLICT` (HTTP 409). Finally, the crew's daily capacity must hold: summing the `scheduled_sqft` of the crew's `SCHEDULED` slots that fall on the same UTC calendar date as the candidate's `start_at`, the existing day load plus the candidate's `scheduled_sqft` must be less than or equal to the crew's `daily_sqft_capacity` — the boundary is inclusive, so a load exactly equal to capacity is admitted and anything beyond it is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409). The day bucket is the UTC calendar date of `start_at`.

A scheduler may cancel a `SCHEDULED` slot, moving it `SCHEDULED → CANCELLED`, which releases its `scheduled_sqft` back to the crew's day capacity — the crew's day load is recomputed from its remaining `SCHEDULED` slots — and bumps the slot's `version`.

### 3.9. Installation and Completion

Installation begins when a `Scheduler` starts a scheduled slot. Starting requires the job to be `ACCEPTED`, the slot to be `SCHEDULED` and belong to that job, and — the cross-entity gate — the job's material order to be `RECEIVED`; a start while the material is not yet received is rejected with `ERR_MATERIAL_NOT_RECEIVED` (HTTP 409). On a successful start the job advances `ACCEPTED → IN_INSTALL` and its `version` is bumped. Completing the slot moves it `SCHEDULED → DONE` and bubbles the job up `IN_INSTALL → COMPLETED`, bumping the job's `version`; a completion is only valid while the slot is `SCHEDULED` and the parent job is `IN_INSTALL`, otherwise `ERR_INVALID_STATE`.

Completion is also the moment the job's `warranty_risk_score` is computed and stored — it is null until then. The score runs from 0 to 100, higher being riskier, and is built by summing additive components and then clamping the total into the range 0 through 100. The category base contributes 30 for `HARDWOOD`, 15 for `LVP`, 40 for `TILE`, and 10 for `CARPET`. Tear-out adds risk: 1 point for every full 50 square feet of the job's tear-out area (the tear-out square footage divided by 50, taking the floor), capped at 20 points. Backorder churn adds risk: 5 points for each backorder recorded on the job's material order — that is, 5 multiplied by the order's `backorder_count` — capped at 25 points. Re-measure churn adds a flat 10 points if the job ever entered `RE_MEASURE` at any point in its history, and 0 otherwise. The four components are summed in that order, and the raw total is then clamped so the stored `warranty_risk_score` is never below 0 nor above 100, kept to one decimal place rounded half up.

### 3.10. Cancelling a Job: The Teardown Cascade

A `SalesRep` may cancel a job from any non-terminal pre-install state — that is, while it is in `DRAFT`, `MEASURED`, `RE_MEASURE`, `ESTIMATED`, or `ACCEPTED` — moving it to `CANCELLED`; a cancel from any other status is rejected with `ERR_INVALID_STATE`. Cancellation is a depth-three teardown that bumps the job's `version` and cascades across all of the job's dependents in the single request. Every non-terminal estimate of the job — any estimate currently in `DRAFT` or `ISSUED` — is voided to `VOIDED`. The job's material order, if it is in `ORDERED` or `BACKORDERED`, is cancelled to `CANCELLED`. And every `SCHEDULED` install slot of the job is cancelled, releasing the crew capacity each was holding. Each child touched by the cascade has its own `updated_at` refreshed and `version` incremented, per §2.5.

### 3.11. The Warranty Window and Claim Adjudication

After a job reaches `COMPLETED`, the owning `Customer` may file a `WarrantyClaim` against it, supplying the `job_id` and a free-text `defect_description`. A claim may only be filed against a job whose status is `COMPLETED`; filing against any other job is rejected with `ERR_JOB_NOT_COMPLETED` (HTTP 409). The filer must own the job — `X-User-ID` equal to the job's `customer_id` — or the file is rejected with `ERR_NOT_RESOURCE_OWNER`. A new claim starts in `FILED` status and snapshots `filed_at` from the current clock at creation.

An `Admin` adjudicates a `FILED` claim, recording a `resolution_note` either way. Denial moves the claim `FILED → DENIED` and is unconditional beyond the claim being `FILED`. Approval moves it `FILED → APPROVED` but is doubly gated. First, the claim's `filed_at` must fall within the job's warranty window, whose end is the job's completion instant plus the product's `warranty_years` whole years; a claim filed after the window has closed is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 409). Second, the job's `warranty_risk_score` must be at most 70 — high-risk installs, those scoring strictly above 70, cannot be auto-approved and are referred to manual denial, with an over-threshold approval rejected by `ERR_RISK_TOO_HIGH` (HTTP 409). Adjudicating a claim that is not `FILED` is rejected with `ERR_INVALID_STATE`. A successful adjudication bumps the claim's `version`.

### 3.12. Validation Ordering Across Endpoints

When several checks guard one operation, they are evaluated in a fixed precedence so that the rejection a client sees is deterministic. Authentication comes first: a missing or unknown user context (`ERR_UNAUTHENTICATED`) is detected before anything else, then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership for customer actions (`ERR_NOT_RESOURCE_OWNER`). Existence of every referenced resource (`ERR_NOT_FOUND`) is checked next, ahead of state and business rules. State legality for a transition (`ERR_INVALID_STATE`) precedes the domain-specific business checks. Within job creation, the discontinued-product check (`ERR_PRODUCT_DISCONTINUED`) and uniqueness checks (`ERR_DUPLICATE_KEY`) sit among these business checks. On estimate issuance the order is: the `valid_until` freshness check (`ERR_VALID_UNTIL_IN_PAST`) and then the concurrency check (`ERR_STALE_JOB_VERSION`). On slot creation the documented order is job-accepted, then crew-skill, then interval well-formedness, then job self-overlap, then crew buffered conflict, then daily capacity. Field-bound and enum violations (`ERR_INVALID_REQUEST`) guard every create and measure endpoint. This ordering matters because an earlier, more fundamental failure must surface as its own error rather than being masked by a later check.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return HTTP 201 Created. Operations that modify an existing resource — state transitions, adjudications, and computed-field recomputations — return HTTP 200 OK. Read operations return 200 OK. Refer back to §2 and §3 for the request payloads, computed fields, cascades, and validation conditions behind each endpoint; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/flooring/customers` | Register a homeowner customer | Anonymous, Admin |
| GET | `/flooring/customers/{id}` | Fetch a customer | Admin, SalesRep, Customer |
| POST | `/flooring/sales-reps` | Register a sales rep | Anonymous, Admin |
| GET | `/flooring/sales-reps/{id}` | Fetch a sales rep | Admin, SalesRep |
| POST | `/flooring/products` | Create a catalog product | Admin |
| GET | `/flooring/products/{id}` | Fetch a product | Admin, SalesRep, Estimator, Scheduler, Customer |
| GET | `/flooring/products` | List products (optional category/status filter) | Admin, SalesRep, Estimator, Scheduler, Customer |
| POST | `/flooring/products/{id}/discontinue` | Discontinue a product | Admin |
| POST | `/flooring/jobs` | Create a flooring job in DRAFT | SalesRep, Admin |
| GET | `/flooring/jobs/{id}` | Fetch a job | Admin, SalesRep, Estimator, Scheduler, Customer |
| GET | `/flooring/jobs` | List jobs (filter by customer/rep/product/status) | Admin, SalesRep, Estimator, Scheduler, Customer |
| POST | `/flooring/jobs/{id}/measure` | Record the in-home measure | Estimator |
| POST | `/flooring/jobs/{id}/request-remeasure` | Send a job back for re-measure | SalesRep, Admin |
| POST | `/flooring/jobs/{id}/cancel` | Cancel a job and tear down its dependents | SalesRep, Admin |
| GET | `/flooring/jobs/{id}/estimates` | List a job's estimates | Admin, SalesRep, Estimator, Customer |
| GET | `/flooring/jobs/{id}/material-orders` | List a job's material orders | Admin, SalesRep, Scheduler |
| GET | `/flooring/jobs/{id}/install-slots` | List a job's install slots | Admin, SalesRep, Scheduler |
| GET | `/flooring/jobs/{id}/warranty-claims` | List a job's warranty claims | Admin, SalesRep, Customer |
| POST | `/flooring/estimates` | Create a DRAFT estimate for a job | SalesRep, Admin |
| GET | `/flooring/estimates/{id}` | Fetch an estimate | Admin, SalesRep, Estimator, Customer |
| GET | `/flooring/estimates` | List estimates (filter by job/status/variant) | Admin, SalesRep, Estimator, Customer |
| POST | `/flooring/estimates/{id}/issue` | Issue a DRAFT MEASURED estimate (OCC on job) | SalesRep, Admin |
| POST | `/flooring/estimates/{id}/accept` | Accept an ISSUED MEASURED estimate | Customer |
| POST | `/flooring/estimates/{id}/expire-check` | Lazily expire an ISSUED estimate past valid_until | SalesRep, Admin, Scheduler |
| GET | `/flooring/material-orders/{id}` | Fetch a material order | Admin, SalesRep, Scheduler |
| GET | `/flooring/material-orders` | List material orders (filter by job/product/status) | Admin, SalesRep, Scheduler |
| POST | `/flooring/material-orders/{id}/backorder` | Mark an ORDERED order BACKORDERED | Scheduler, Admin |
| POST | `/flooring/material-orders/{id}/reorder` | Re-place a BACKORDERED order | Scheduler, Admin |
| POST | `/flooring/material-orders/{id}/receive` | Receive an ORDERED order at/after ready date | Scheduler, Admin |
| POST | `/flooring/install-crews` | Create an install crew | Scheduler, Admin |
| GET | `/flooring/install-crews/{id}` | Fetch a crew | Admin, Scheduler |
| GET | `/flooring/install-crews` | List crews (filter by status) | Admin, Scheduler |
| POST | `/flooring/install-crews/{id}/deactivate` | Deactivate an AVAILABLE crew | Scheduler, Admin |
| GET | `/flooring/install-crews/{id}/install-slots` | List a crew's slots | Admin, Scheduler |
| POST | `/flooring/install-slots` | Schedule an install slot for an ACCEPTED job | Scheduler, Admin |
| GET | `/flooring/install-slots/{id}` | Fetch an install slot | Admin, Scheduler, SalesRep |
| POST | `/flooring/install-slots/{id}/start` | Start install (requires material RECEIVED) | Scheduler, Admin |
| POST | `/flooring/install-slots/{id}/complete` | Complete install; complete the job | Scheduler, Admin |
| POST | `/flooring/install-slots/{id}/cancel` | Cancel a SCHEDULED slot, releasing capacity | Scheduler, Admin |
| POST | `/flooring/warranty-claims` | File a warranty claim against a COMPLETED job | Customer, Admin |
| GET | `/flooring/warranty-claims/{id}` | Fetch a warranty claim | Admin, SalesRep, Customer |
| POST | `/flooring/warranty-claims/{id}/approve` | Approve a FILED claim within window and risk gate | Admin |
| POST | `/flooring/warranty-claims/{id}/deny` | Deny a FILED claim | Admin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_VARIANT_STATE_MISMATCH` | 409 |
| `ERR_VALID_UNTIL_IN_PAST` | 422 |
| `ERR_STALE_JOB_VERSION` | 412 |
| `ERR_ESTIMATE_EXPIRED` | 409 |
| `ERR_CREW_SKILL_MISMATCH` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_CREW_TIME_CONFLICT` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_JOB_SLOT_OVERLAP` | 409 |
| `ERR_JOB_NOT_ACCEPTED` | 409 |
| `ERR_MATERIAL_NOT_READY` | 409 |
| `ERR_MATERIAL_NOT_RECEIVED` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_RISK_TOO_HIGH` | 409 |
| `ERR_JOB_NOT_COMPLETED` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
