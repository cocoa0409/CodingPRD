# Plumbing Service Dispatch API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Plumbing Service Dispatch API, a back-office and field-operations platform for a residential and light-commercial plumbing company. The system coordinates the full arc of a service call — from the moment a customer reports a leak, a clogged drain, a failing water heater, or a whole-house repipe, through dispatch and routing of a licensed technician, on-site flat-rate estimating, customer authorization, parts consumption out of truck stock, municipal permitting and inspection, invoicing, and post-job warranty callbacks.

Several forces make this domain non-trivial. Pricing is a flat-rate book affair layered with after-hours multipliers, membership discounts, trip-fee waivers, and emergency surcharges, and the figure quoted to a customer at estimate time is not always the figure billed at completion: estimates price projected parts while invoices price the parts a technician actually drew from the truck. Dispatch must respect a technician's skill ceiling, permit licensing, and an overlap-free route. Permits gate completion, inspectors carry daily capacity limits, and a single accepted warranty callback can unwind an entire completed job — voiding its invoice, restoring consumed stock, and releasing committed customer credit. The API is the system of record that keeps these moving parts consistent.

Four roles share the platform with non-overlapping ownership: a dispatcher owns scheduling, a technician owns field execution and estimating, a customer owns approvals and callbacks, and an office manager owns configuration, permitting, invoicing, and overrides.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API. The API is mounted under the `/plumbing` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. A request that omits either header, or carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `OfficeManager`, `Dispatcher`, `Technician`, and `Customer`. When a well-authenticated principal attempts an operation its role is not permitted to perform — or attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The four roles partition responsibilities cleanly. An `OfficeManager` is the back-office operator: it configures membership plans, the flat-rate book, the parts catalog, technicians, and inspectors; manages truck stock; issues permits and records inspection results; accepts or rejects callbacks; adjusts customer credit; and reads invoices. A `Dispatcher` creates jobs and customers and owns the dispatch lifecycle — proposing, confirming, and cancelling assignments and managing technician availability. A `Technician` is the field worker who drives the depart/arrive flow, builds and presents estimates, and starts and completes jobs. A `Customer` is the service requester who approves or declines presented estimates on its own jobs and files warranty callbacks.

The relationship between `X-User-ID` and persisted entities differs by role. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's technician foreign key to `X-User-ID` — for example, only the technician who owns a job's confirmed assignment may depart, arrive, start, or complete that job. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID` — a customer may only approve, decline, or file callbacks against jobs whose `customer_id` equals its own `X-User-ID`. When `X-User-Role` is `OfficeManager` or `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. Every resource has an `id`, a unique server-minted UUID with no type prefix, generated at creation time and never reused as a meaningful value beyond identity. Every resource also has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when it was first created.

The majority of resources additionally carry an `updated_at` (an ISO 8601 UTC timestamp, three fractional digits, refreshed on every mutation) and a `version` (an integer that begins at its initial value on creation and increments by one on every mutation of that resource). These apply to `Customer`, `Technician`, `Inspector`, `TruckStock`, `ServiceJob`, `DispatchAssignment`, `Estimate`, `EstimateLine`, `Permit`, `InspectionVisit`, `Invoice`, and `Callback`.

A small set of configuration-style resources are immutable after creation and therefore carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field. These are `MembershipPlan`, `FlatRateItem`, and `Part`. Implementations must not emit `updated_at` or `version` for those three.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a path that names one or more identifiers, and some create or list child resources beneath a parent (for example, the estimates of a job, the lines of an estimate, the permits of a job, or the inspections of a permit). For any such request, the system validates each identifier in the path from left to right, rejecting the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. Only after every path identifier resolves does the system validate foreign keys referenced in the request body, likewise rejecting unknown references with `ERR_NOT_FOUND`. This ordering — path identifiers first, left to right, then body references — ensures that a request against a non-existent parent fails on the parent before the system ever looks at the child or the body.

### 2.6. Validation Ordering

When a single request could trip several checks, the system evaluates them in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first: a missing or malformed `X-User-ID`/`X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization comes second: a role not permitted for the operation, or an owner mismatch, yields `ERR_UNAUTHORIZED`. Existence comes third: any referenced resource (path identifier left-to-right, then body foreign key) that does not exist yields `ERR_NOT_FOUND`. Request well-formedness comes fourth: a body that fails to parse, a missing required field, or a value that violates an enum, type, or range constraint yields `ERR_INVALID_REQUEST`. State validity comes fifth: a target resource not in a legal state for the requested transition yields `ERR_INVALID_STATE`. Optimistic-concurrency staleness comes sixth, on the two endpoints that carry a version expectation (see §2.7). Only after all of these pass does the system evaluate the domain-specific business rules — skill, licensing, route overlap, inspector capacity, estimate non-emptiness, stock sufficiency, warranty, and credit — described throughout §3. In other words, structural and state checks always precede business checks, and within the business tier the specific rule that fires is determined by the operation in question.

### 2.7. Optimistic Concurrency Control on Job-Scoped Creation

Two creation operations are guarded against acting on a stale view of their parent `ServiceJob` using optimistic concurrency control. Both require the caller to supply an `expected_job_version` field carrying the `version` of the target `ServiceJob` the client last observed.

The first is the creation of a new `Estimate` against a job. The request body must include `expected_job_version`; if its value does not equal the target job's current `version`, the create is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). This captures the case where another writer has already created a fresh `DRAFT` estimate against the job (which legitimately supersedes the prior estimate workflow) and bumped the job's `version`, so that the current writer's view of the job is stale and the create must not proceed.

The second is the creation of a new `DispatchAssignment`. Its body likewise must include `expected_job_version`; a value that does not equal the target job's current `version` is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). This captures the re-dispatch case where another writer has already proposed an assignment — legitimately superseding the prior dispatch plan — and bumped the job's `version`, making the current writer's view stale.

These are the only two endpoints that take a version field. No other endpoint accepts `expected_job_version` or performs an OCC check; all other state-changing operations proceed without one.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and transmitted as integer cents (whole numbers); there are no fractional-cent fields. Wherever a rounding step is required — when a flat-rate base price is multiplied by the after-hours multiplier, when a line total is formed from a unit price and a quantity, and when the membership discount is taken as a fraction of the labor subtotal — the system uses the round-half-up method to the nearest whole cent. Rounding is pinned at the per-line level and at the discount: each estimate line's unit price and line total are rounded as they are computed, and the line totals are then summed without any further rounding of the sum. The subtotals themselves are never re-rounded.

The technician callback-rate read is the one place outside cost accounting where rounding applies: both the lifetime and rolling callback rates are reported as numbers rounded half-up to four decimal places.

### 2.9. Hierarchical Consistency and Cascades

Several operations in this system mutate more than one resource at once, and the secondary effects are as much a part of the contract as the primary state change. When a job is authorized, completed, cancelled, or reopened, the system propagates the consequences across the related estimate, invoice, truck stock, permits, dispatch assignments, and the customer's committed credit, as detailed in §3. Each resource that the system mutates as part of such a cascade independently refreshes its own `updated_at` and increments its own `version` — a cascade that touches three resources bumps three versions. The system performs these reconciliations itself, without requiring a separate client request against each affected resource. The specific cascades — credit commit and release, permit auto-creation, estimate state linkage, truck-stock decrement and restoration, restock flagging, and the lifetime counters — are described where the workflows that trigger them are described.

## 3. Business Logic & Workflows

### 3.1. Configuration: Plans, the Flat-Rate Book, Parts, People, and Truck Stock

Before any service call can be priced or dispatched, an `OfficeManager` populates the reference data. A **membership plan** is created with a `tier_code` that is one of `NONE`, `SILVER`, or `GOLD` and is unique across all plans, a human-readable `name`, a `labor_discount_pct` expressed as a fraction between 0 and 1 inclusive (for instance 0.20 for a 20% labor discount), a `waives_trip_fee` boolean, and an `annual_fee_cents` integer. A customer whose `membership_plan_id` is null is treated as tier `NONE` for all pricing purposes.

The **flat-rate book** is a catalog of priced labor items. Each `FlatRateItem` carries a `code` that is unique across the book (for example "WH-REPLACE-40"), a `category` that is one of `LEAK`, `DRAIN`, `WATER_HEATER`, `REPIPE`, or `GENERAL`, a `base_price_cents` integer that is at least 0 and represents the normal-hours labor price before any after-hours multiplier or membership discount, a `skill_required` integer between 1 and 5 inclusive that names the minimum technician competency needed to perform the item, and a `requires_permit` boolean (defaulting to false) that, when true, means any job whose approved estimate contains this item needs a permit before it can be completed.

The **parts catalog** holds `Part` records, each with a `sku` unique across all parts, a descriptive `name`, and a `list_price_cents` integer of at least 0 representing the price charged to the customer per unit — a figure that, unlike labor, is never touched by the after-hours multiplier or by membership discounts.

People come in three kinds. A **technician** is created with a `name`, a `skill_level` integer between 1 and 5 inclusive, and an optional `licensed_for_permits` boolean (defaulting to false) governing whether the technician may be assigned to permit-requiring jobs. Each technician carries a system-managed availability `status` — one of `AVAILABLE`, `ON_CALL`, or `OFF_DUTY`, defaulting to `AVAILABLE` — which may be changed through a set-availability operation. A technician also accumulates several computed counters discussed in §3.7 and §3.8: `lifetime_completed_count`, `lifetime_callback_count`, and `needs_restock_skus`, each defaulting to 0. An **inspector** is created with a `name`, a `jurisdiction` code identifying the municipality it serves, and a `max_daily_inspections` integer of at least 1 (defaulting to 4) that caps how many inspection visits it may hold on any single date. A **customer** is created with a `name`, a `service_address`, an optional `membership_plan_id` (nullable, defaulting to null), and an optional `credit_limit_cents` (defaulting to 100000 cents) that caps the total of authorized estimate amounts the customer may have committed at once. The customer's `committed_credit_cents` is a computed running total, starting at 0, of authorized estimate amounts across its jobs; it rises on estimate approval and is released on decline, cancel, or callback reopen. An `OfficeManager` may later adjust a customer's `credit_limit_cents` or `membership_plan_id`; each such adjustment increments the customer's `version`.

**Truck stock** ties technicians to parts. A `TruckStock` row names a `technician_id` (the truck the stock lives on) and a `part_id` (the stocked part), and carries a `quantity` of units currently on the truck, a `reorder_point` integer of at least 0 (defaulting to 2), and a computed `needs_restock` flag. The `quantity` is at least 0; it is set when stock is created or restocked, decremented as parts are consumed on completion, and restored on a callback reopen. The `needs_restock` flag is true exactly when the row's `quantity` is at or below its `reorder_point`. Whenever a truck-stock row is created, restocked, or otherwise has its quantity recomputed, the system re-evaluates `needs_restock` and recomputes the owning technician's `needs_restock_skus`, which is the count of that technician's truck-stock rows currently flagged for restock.

### 3.2. Opening a Service Call and Dispatching a Technician

A `Dispatcher` (or an `OfficeManager`) opens a service call by creating a `ServiceJob` with a `customer_id`, a `category` that is one of `LEAK`, `DRAIN`, `WATER_HEATER`, or `REPIPE`, an optional `priority` that is one of `STANDARD` or `EMERGENCY` (defaulting to `STANDARD`), and an optional requested `window_start` (defaulting to null). The job is born in status `RECEIVED`. It carries several computed fields that start empty: an `after_hours` boolean (initially false), an `authorized_estimate_id` (initially null), an `authorized_amount_cents` (initially 0), and a `completed_at` timestamp (initially null).

Dispatching begins with a **proposed assignment**. A `Dispatcher` creates a `DispatchAssignment` against a job by supplying the `job_id`, the `technician_id`, a `window_start` and `window_end` bounding the on-site window, an `eta` for the arrival within that window, and the `expected_job_version` for the optimistic-concurrency check of §2.7. The `window_end` must be strictly after the `window_start`; a window whose end is at or before its start is rejected with `ERR_VALIDATION`. A newly created assignment begins in status `PROPOSED`, and creating it increments the parent job's `version`.

**Confirming** a proposed assignment is where the scheduling guardrails fire. Confirmation is permitted only when the assignment is in `PROPOSED` status; otherwise the request is rejected with `ERR_INVALID_STATE`. Confirmation then enforces three business gates, each tied to a distinct rejection. First, the assigned technician's availability `status` must be `AVAILABLE` or `ON_CALL` — a technician that is `OFF_DUTY` cannot be confirmed onto the job. Second, the technician's `skill_level` must be greater than or equal to the maximum `skill_required` across the flat-rate work the job intends; if the technician's skill falls below that ceiling, the request is rejected with `ERR_SKILL_INSUFFICIENT`. Third, if the job requires a permit, the technician's `licensed_for_permits` must be true, or the request is rejected with `ERR_LICENSE_REQUIRED`. Finally, the requested window must not collide with the technician's existing route: no other assignment of this technician that is in `CONFIRMED`, `EN_ROUTE`, or `ON_SITE` status may overlap the requested `[window_start, window_end)` interval after that interval is expanded by the travel buffer on each side; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`. The travel buffer between back-to-back jobs is a fixed thirty minutes, applied symmetrically to the start and the end of the requested half-open window, and the comparison treats the window as half-open so that an assignment ending exactly when another begins (buffer aside) does not itself constitute an overlap.

On a successful confirmation the assignment moves to `CONFIRMED`, the confirmation increments both the assignment's `version` and the job's `version`, and — if the job is still in `RECEIVED` — the job transitions `RECEIVED → DISPATCHED`. That `RECEIVED → DISPATCHED` transition is also the moment the job's `after_hours` flag is frozen: `after_hours` is set true when the confirmed assignment's `window_start` falls at or after the after-hours cutoff hour (in UTC) or on a Saturday or Sunday (in UTC), and false otherwise. The after-hours cutoff hour is 18:00 UTC, meaning any confirmed window starting at hour 18 or later in the UTC day counts as after hours. Once frozen at confirmation, `after_hours` does not change and it governs the labor multiplier used by every subsequent estimate on the job.

The technician then drives the field flow. **Departing** is permitted only when the job's confirmed assignment belongs to the acting technician and that assignment is in `CONFIRMED` status; departing advances the assignment `CONFIRMED → EN_ROUTE` and the job `DISPATCHED → EN_ROUTE`. **Arriving** is permitted only when the assignment is `EN_ROUTE`; it advances the assignment `EN_ROUTE → ON_SITE` and the job `EN_ROUTE → ON_SITE`. A `Dispatcher` may **cancel** an assignment while it is in `PROPOSED`, `CONFIRMED`, `EN_ROUTE`, or `ON_SITE`, moving it to `CANCELLED` and freeing the technician's time window for re-dispatch. When the job itself reaches `COMPLETED`, the system closes the on-site assignment automatically, advancing it `ON_SITE → CLOSED`.

### 3.3. Building and Pricing the Estimate

Once a technician is on site, it builds the **flat-rate estimate** that will be presented to the customer. Creating an estimate against a job produces an `Estimate` in `DRAFT` status linked to the job by `job_id`; this create is the OCC-guarded operation of §2.7 and must carry the `expected_job_version` matching the job's current `version`, and it increments the job's `version`. An estimate carries a `status` that is one of `DRAFT`, `PRESENTED`, `REVISED`, `APPROVED`, `DECLINED`, or `CONSUMED`, and a family of computed money fields all defaulting to 0: `labor_subtotal_cents`, `parts_subtotal_cents`, `discount_cents`, `trip_fee_cents`, `emergency_surcharge_cents`, and `estimate_total_cents`.

Each line on an estimate is an `EstimateLine` linked by `estimate_id`, with a `line_type` that is either `FLAT_RATE` or `PART` and a `quantity` of at least 1. A `FLAT_RATE` line must name a `flat_rate_item_id` and leave `part_id` null; a `PART` line must name a `part_id` and leave `flat_rate_item_id` null. A line whose type and reference do not agree — a `FLAT_RATE` line missing its flat-rate item, or a `PART` line missing its part — is rejected with `ERR_INVALID_REQUEST`. Each line also carries computed `unit_price_cents` and `line_total_cents`, both defaulting to 0 until the estimate is priced. Lines may be added while the estimate is in `DRAFT` or `REVISED`.

**Presenting** an estimate moves it `DRAFT → PRESENTED` (or `REVISED → PRESENTED` on a re-presentation). Presentation is permitted only when the job is `ON_SITE` and the estimate is in `DRAFT` or `REVISED`; an estimate with no lines at all cannot be presented and is rejected with `ERR_EMPTY_ESTIMATE`. Presentation triggers a full recomputation of every line and estimate total — the provisional pricing pass — and increments the estimate's `version`.

The **provisional pricing** is computed as follows, in order. For each line, the system first determines a unit price. For a `FLAT_RATE` line, the unit price is the flat-rate item's `base_price_cents` multiplied by the after-hours multiplier and then rounded half-up to a whole cent, where the after-hours multiplier is 1.5 when the job's `after_hours` is true and 1.0 otherwise. For a `PART` line, the unit price is simply the part's `list_price_cents`, untouched by any multiplier. The line total is then the unit price multiplied by the line's `quantity`, rounded half-up to a whole cent — rounding is applied at the line level, before any summation. Next, the labor subtotal is the sum of the already-rounded line totals of the `FLAT_RATE` lines, and the parts subtotal is the sum of the already-rounded line totals of the `PART` lines; neither sum is re-rounded. The membership labor discount applies only to labor: the discount is the labor subtotal multiplied by the customer's plan `labor_discount_pct` (0 when the customer has no plan or is tier `NONE`), rounded half-up, and then capped so that it never exceeds 15000 cents. The labor-after-discount figure is the labor subtotal minus this discount. The trip fee is then decided: the fee is waived — set to 0 — when the customer's plan has `waives_trip_fee` true, or when the labor-after-discount figure is at least the trip-waive threshold of 50000 cents; otherwise the trip fee is the base trip fee of 8900 cents. The emergency surcharge is 12000 cents when the job's `priority` is `EMERGENCY`, and 0 otherwise. Finally, the estimate total is the labor-after-discount figure plus the parts subtotal plus the trip fee plus the emergency surcharge. The `estimate_total_cents` so computed is the amount that will commit the customer's credit on approval.

A presented estimate can travel three ways. A technician may **revise** it, moving it `PRESENTED → REVISED`, which reopens it for line edits and is permitted only from `PRESENTED`; the revised estimate can later be presented again, looping `REVISED → PRESENTED` and re-running the provisional pricing each time. A customer may **decline** it from either `PRESENTED` or `REVISED`, moving it to `DECLINED`. Or a customer may **approve** it, the pivotal step described next.

### 3.4. Authorization, Credit Commitment, and Permit Creation

**Approval** of an estimate is reserved to the owning customer — the acting `Customer` must own the job whose `customer_id` equals the caller's `X-User-ID`, or the request is rejected with `ERR_UNAUTHORIZED`. Approval is permitted only when the estimate is in `PRESENTED` status and the job is `ON_SITE`. Before approval succeeds, the system performs the fiscal check: the customer's available credit, defined as its `credit_limit_cents` minus its `committed_credit_cents`, must be greater than or equal to the estimate's `estimate_total_cents`. When the estimate total would exceed the available credit, approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

On a successful approval, several things happen together. The estimate moves `PRESENTED → APPROVED`, and the job moves `ON_SITE → AUTHORIZED`. The job's `authorized_estimate_id` is set to the approved estimate's `id` and its `authorized_amount_cents` is set to that estimate's `estimate_total_cents`. The customer's `committed_credit_cents` is increased by that same estimate total, reserving the credit. And as a cascade, if any `FLAT_RATE` line on the approved estimate references a flat-rate item whose `requires_permit` is true, the system auto-creates a single `Permit` for the job in status `APPLIED`, with the job's `job_id` and a `jurisdiction` derived from the customer. Each resource touched by this cascade — estimate, job, customer, and any new permit — independently bumps its own `version`.

### 3.5. Performing the Work, Permits, and Inspections

With the job `AUTHORIZED`, the technician **starts work**, moving the job `AUTHORIZED → IN_PROGRESS`. Starting is permitted only when the job is `AUTHORIZED` and its `authorized_estimate_id` is not null and points at an estimate that is in `APPROVED` status — a cross-entity dependency where the job genuinely requires its estimate to be approved before work may begin. Starting work increments the job's `version`.

Where the approved work includes a permit-requiring flat-rate item, the **permit** must be satisfied before the job can complete. A permit carries a `job_id`, a `jurisdiction`, a `status` that is one of `APPLIED`, `ISSUED`, `INSPECTION_SCHEDULED`, `PASSED`, `FAILED`, or `VOIDED`, and a computed `reapply_count` starting at 0. An `OfficeManager` **issues** an applied permit, moving it `APPLIED → ISSUED`. From `ISSUED`, the office manager **schedules an inspection** by naming an `inspector_id` and a `scheduled_date` (a calendar date in YYYY-MM-DD form); this moves the permit `ISSUED → INSPECTION_SCHEDULED` and creates an `InspectionVisit` in `result` `PENDING`. Scheduling enforces two gates: the chosen inspector's `jurisdiction` must equal the permit's `jurisdiction`, or the request is rejected with `ERR_LICENSE_REQUIRED`; and the inspector must currently hold fewer than its `max_daily_inspections` visits in `PENDING` result on that `scheduled_date`, or the request is rejected with `ERR_INSPECTOR_CAPACITY_FULL`. This daily capacity is an aggregate count across all permits, evaluated per the requested date.

An `InspectionVisit` carries a `permit_id`, an `inspector_id`, a `scheduled_date`, and a `result` that is one of `PENDING`, `PASSED`, or `FAILED`. The office manager **records** the result, which is permitted only when the visit is still `PENDING`. Recording a `PASSED` result sets the visit to `PASSED` and moves the permit `INSPECTION_SCHEDULED → PASSED`; recording a `FAILED` result sets the visit to `FAILED` and moves the permit `INSPECTION_SCHEDULED → FAILED`. A failed permit can be reissued: issuing a failed permit moves it `FAILED → ISSUED` and increments its `reapply_count` by one, so the permit can cycle back through scheduling and inspection. Should the underlying job be cancelled, an applied permit is voided automatically, moving `APPLIED → VOIDED`.

**Completing** the job moves it `IN_PROGRESS → COMPLETED` and is the most consequential transition in the system. The technician supplies the actual `consumed_parts` — the parts truly drawn from the truck and the units of each. Completion is permitted only when the job is `IN_PROGRESS`; if any permit exists for the job, that permit's status must be `PASSED` (a cross-entity dependency where the job requires its permit to have passed inspection); and for every consumed part, the acting technician's truck-stock `quantity` for that part must be greater than or equal to the units claimed consumed. A claim to consume more than the truck holds is rejected with `ERR_INSUFFICIENT_STOCK`. On success the system performs a chain of side effects: it sets the job's `completed_at` to the current UTC instant; it links the authorized estimate by moving it `APPROVED → CONSUMED`; for each consumed part it decrements the technician's matching truck-stock `quantity` by the units consumed; for every truck-stock row whose `quantity` then falls at or below its `reorder_point` it sets `needs_restock` true and increments the technician's `needs_restock_skus`; it increments the technician's `lifetime_completed_count` by one, but only if this job has never reached `COMPLETED` before — a reopened job re-completing does not re-increment that lifetime count; and it creates an `Invoice` for the job and finalizes its totals. The completing technician — the one who fires this transition — is the technician credited with completing the job for callback-rate purposes. Completion increments the job's `version`, and each cascaded resource bumps its own version as well.

### 3.6. Invoicing and the Provisional-versus-Final Divergence

Completion creates an `Invoice` linked by `job_id`, born in status `FINALIZED` (the only other invoice status is `VOIDED`). The invoice carries three computed money fields: `final_labor_cents`, `final_parts_cents`, and `final_total_cents`. The invoice is finalized using the same pricing skeleton as the estimate, but with two deliberate differences: it operates on the parts actually consumed rather than the parts projected, and it captures the customer's membership tier as of invoice time.

Concretely, `final_labor_cents` is recomputed from the approved estimate's `FLAT_RATE` lines exactly as the provisional labor was — each line's base price times the after-hours multiplier, rounded half-up per line, then summed without re-rounding — and the membership labor discount is re-applied with the same 15000-cent cap. The `final_parts_cents` is computed from actual consumption: for each distinct consumed part, the part's `list_price_cents` is multiplied by the units actually consumed and rounded half-up, and those per-part figures are summed. Because actual consumption may be fewer units than the estimate projected, `final_parts_cents` — and therefore `final_total_cents` — can diverge from the provisional estimate whenever consumed units differ from estimated units. The trip fee and the emergency surcharge are recomputed with the same constants and the same rules, using the labor-after-discount figure at invoice time to decide the trip-fee waiver: the fee is waived when the plan waives it or when labor-after-discount is at least 50000 cents, otherwise it is 8900 cents; the emergency surcharge is 12000 cents for an `EMERGENCY` job and 0 otherwise. The `final_total_cents` is the labor-after-discount figure plus `final_parts_cents` plus the trip fee plus the emergency surcharge, all in integer cents under the same round-half-up-per-line, never-round-subtotals discipline.

### 3.7. Cancelling a Job

A `Dispatcher` (or an `OfficeManager`) may **cancel** a job at any pre-completion stage — that is, while the job is in `RECEIVED`, `DISPATCHED`, `EN_ROUTE`, `ON_SITE`, or `AUTHORIZED` — moving it to `CANCELLED`, a terminal state. Cancellation unwinds the job's commitments. If the job's `authorized_amount_cents` is greater than 0, that amount is released back to the customer by decreasing the customer's `committed_credit_cents` by it, and the job's `authorized_amount_cents` is reset to 0. Any dispatch assignment of the job that is not already terminal is set to `CANCELLED` — a conditional cascade that leaves already-terminal (`CLOSED` or `CANCELLED`) assignments untouched. Any estimate of the job that is in `PRESENTED` or `APPROVED` status is set to `DECLINED`. And any applied permit on the job is voided. Cancellation increments the job's `version`, and each cascaded resource bumps its own version.

### 3.8. Warranty Callbacks and the Job Reopen Cycle

After a job completes, the customer may file a **warranty callback** if the work proves defective. A `Customer` files a `Callback` against a completed job by supplying the `original_job_id` and a free-text `reason`; the callback is born in status `OPEN` (its other statuses are `ACCEPTED`, `REJECTED`, and `RESOLVED`). A callback may only be filed against a job that is `COMPLETED`; a callback filed against a job in any other state is rejected with `ERR_WARRANTY_EXPIRED`. At creation the system computes the callback's `within_warranty` flag and, on the technician who completed the original job, increments that technician's `lifetime_callback_count` by one.

The `within_warranty` determination is a date calculation. The number of whole days elapsed is the difference between the callback's `created_at` and the original job's `completed_at`, taken in seconds (UTC) and divided by the number of seconds in a day, with any fractional day discarded by flooring. The callback is within warranty when that whole-day count is less than or equal to the warranty period of 90 days; a callback filed exactly 90 days after completion is still within warranty, because the boundary is inclusive.

An `OfficeManager` resolves a callback. **Rejecting** an open callback moves it `OPEN → REJECTED` and does nothing further. **Accepting** an open callback is allowed only when the callback is `OPEN`, its `within_warranty` is true, and the original job is `COMPLETED`; an attempt to accept a callback whose `within_warranty` is false is rejected with `ERR_WARRANTY_EXPIRED`. Acceptance is a compensating reversal of the completed job. It moves the callback `OPEN → ACCEPTED` and the original job `COMPLETED → REOPENED`. It voids the job's invoice, moving it to `VOIDED`. For each part the voided invoice consumed, it restores the technician's truck stock by incrementing the matching `quantity` by the consumed units, then recomputes `needs_restock` and the technician's `needs_restock_skus` accordingly. And it releases the customer's committed credit by the job's `authorized_amount_cents`. Each resource touched bumps its own version.

A reopened job is worked again. The technician **starts work** once more, moving the job `REOPENED → IN_PROGRESS`; this is permitted only when the job is `REOPENED` and its authorized estimate is in `APPROVED` or `CONSUMED` status, and as a side effect it re-arms the authorized estimate back to `APPROVED` so a fresh completion can consume it. The job can then be **completed** again, cycling `IN_PROGRESS → COMPLETED`; on this second completion the technician's `lifetime_completed_count` is not incremented again, because the job has reached `COMPLETED` before. When the reopened job re-enters `COMPLETED`, the system marks the accepted callback `ACCEPTED → RESOLVED`.

### 3.9. Technician Risk: Callback Rates

The system exposes a computed read of a technician's **callback rate** for quality monitoring, reported under two variants. The denominator universe is the technician's completed jobs — those `ServiceJob`s that have reached `COMPLETED` at least once and whose completing technician (the one who fired the `COMPLETED` transition) is this technician. A job "has a callback" when at least one `Callback` row exists with `original_job_id` equal to that job, counting callbacks of any status.

The **lifetime** rate is the technician's `lifetime_callback_count` divided by its `lifetime_completed_count`, reported to four decimal places, and reported as 0.0 when the completed count is 0. The **rolling** rate looks only at recency: it considers the technician's most recent completed jobs, ordered by `completed_at` descending with ties broken by `created_at` descending, and takes the most recent five. The rolling denominator is the smaller of 5 and the technician's `lifetime_completed_count`, and the rolling numerator is the count of those window jobs that have at least one callback. The rolling rate is that numerator over that denominator, reported to four decimal places and as 0.0 when the denominator is 0. Because the rolling window weights recent work, a technician whose quality is improving over time will tend to score lower on the rolling rate than on the lifetime rate for the same history. The computed read returns `lifetime_callback_rate`, `rolling_callback_rate`, `lifetime_completed_count`, and `lifetime_callback_count`.

### 3.10. Test-Driving the Clock

Because warranty windows and after-hours determinations are time-sensitive, an `OfficeManager` has access to an internal clock-control capability that sets the server's notion of the current UTC instant to a supplied `to_iso8601` value. Once set, all subsequent `created_at`, `completed_at`, and current-time reads use that fixed instant until it is changed again. This capability exists to support deterministic setup of time-gated scenarios.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a membership plan, a flat-rate item, a part, a customer, a technician, an inspector, a service job, a dispatch assignment, an estimate, an estimate line, an inspection visit, a truck-stock row, or a callback — return a `201 Created` status code. Operations that modify an existing resource, including all state-transition actions, list reads, and single-resource reads, return a `200 OK` status code. Reconstruct each endpoint's request body, computed effects, and authorization nuances from the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plumbing/membership-plans` | Create a membership plan tier | OfficeManager |
| GET | `/plumbing/membership-plans/{id}` | Read a membership plan | OfficeManager, Dispatcher, Technician, Customer |
| POST | `/plumbing/flat-rate-items` | Add a flat-rate book item | OfficeManager |
| GET | `/plumbing/flat-rate-items/{id}` | Read a flat-rate item | OfficeManager, Dispatcher, Technician, Customer |
| POST | `/plumbing/parts` | Add a part to the catalog | OfficeManager |
| GET | `/plumbing/parts/{id}` | Read a part | OfficeManager, Dispatcher, Technician, Customer |
| POST | `/plumbing/customers` | Create a customer | OfficeManager, Dispatcher |
| GET | `/plumbing/customers/{id}` | Read a customer including committed credit | OfficeManager, Dispatcher, Technician, Customer |
| GET | `/plumbing/customers` | List customers, optionally filtered by membership plan | OfficeManager, Dispatcher |
| PATCH | `/plumbing/customers/{id}` | Adjust a customer's credit limit or membership plan | OfficeManager |
| POST | `/plumbing/technicians` | Create a technician | OfficeManager |
| GET | `/plumbing/technicians/{id}` | Read a technician | OfficeManager, Dispatcher, Technician, Customer |
| POST | `/plumbing/technicians/{id}/set-status` | Set technician availability status | OfficeManager, Dispatcher |
| GET | `/plumbing/technicians/{id}/callback-rate` | Computed read of lifetime and rolling callback rates | OfficeManager, Dispatcher |
| GET | `/plumbing/technicians/{id}/truck-stock` | List a technician's truck-stock rows | OfficeManager, Dispatcher, Technician |
| POST | `/plumbing/truck-stock` | Create or restock a truck-stock row | OfficeManager |
| GET | `/plumbing/truck-stock` | List truck stock, optionally filtered by part or technician | OfficeManager, Dispatcher, Technician |
| GET | `/plumbing/truck-stock/{id}` | Read a truck-stock row | OfficeManager, Dispatcher, Technician |
| POST | `/plumbing/inspectors` | Create an inspector | OfficeManager |
| GET | `/plumbing/inspectors/{id}` | Read an inspector | OfficeManager, Dispatcher |
| POST | `/plumbing/service-jobs` | Create a service call / work order | Dispatcher, OfficeManager |
| GET | `/plumbing/service-jobs/{id}` | Read a service job including computed totals and status | OfficeManager, Dispatcher, Technician, Customer |
| GET | `/plumbing/service-jobs` | List service jobs, optionally filtered | OfficeManager, Dispatcher, Customer |
| POST | `/plumbing/service-jobs/{id}/start-work` | Start work on an authorized or reopened job | Technician |
| POST | `/plumbing/service-jobs/{id}/complete` | Complete a job with actual consumed parts | Technician |
| POST | `/plumbing/service-jobs/{id}/cancel` | Cancel a pre-completion job with cascades | Dispatcher, OfficeManager |
| POST | `/plumbing/dispatch-assignments` | Propose a dispatch assignment (OCC-guarded) | Dispatcher |
| GET | `/plumbing/dispatch-assignments/{id}` | Read a dispatch assignment | OfficeManager, Dispatcher, Technician |
| GET | `/plumbing/dispatch-assignments` | List assignments, optionally filtered | OfficeManager, Dispatcher, Technician |
| POST | `/plumbing/dispatch-assignments/{id}/confirm` | Confirm a proposed assignment | Dispatcher |
| POST | `/plumbing/dispatch-assignments/{id}/depart` | Technician departs for the job | Technician |
| POST | `/plumbing/dispatch-assignments/{id}/arrive` | Technician arrives on site | Technician |
| POST | `/plumbing/dispatch-assignments/{id}/cancel` | Cancel a non-terminal assignment | Dispatcher |
| POST | `/plumbing/service-jobs/{id}/estimates` | Create a draft estimate against a job (OCC-guarded) | Technician |
| GET | `/plumbing/service-jobs/{id}/estimates` | List estimates for a job | OfficeManager, Dispatcher, Technician, Customer |
| GET | `/plumbing/estimates/{id}` | Read an estimate with computed totals | OfficeManager, Dispatcher, Technician, Customer |
| POST | `/plumbing/estimates/{id}/lines` | Add a line to a draft or revised estimate | Technician |
| GET | `/plumbing/estimates/{id}/lines` | List the lines of an estimate | OfficeManager, Dispatcher, Technician, Customer |
| GET | `/plumbing/estimate-lines/{id}` | Read a single estimate line | OfficeManager, Dispatcher, Technician, Customer |
| GET | `/plumbing/estimate-lines` | List estimate lines, optionally filtered | OfficeManager, Dispatcher, Technician |
| POST | `/plumbing/estimates/{id}/present` | Present an estimate to the customer | Technician |
| POST | `/plumbing/estimates/{id}/revise` | Reopen a presented estimate for edits | Technician |
| POST | `/plumbing/estimates/{id}/approve` | Customer approves an estimate | Customer |
| POST | `/plumbing/estimates/{id}/decline` | Customer declines an estimate | Customer |
| GET | `/plumbing/service-jobs/{id}/permits` | List permits for a job | OfficeManager, Dispatcher, Technician |
| GET | `/plumbing/permits/{id}` | Read a permit | OfficeManager, Dispatcher, Technician |
| POST | `/plumbing/permits/{id}/issue` | Issue a permit or reissue after failure | OfficeManager |
| POST | `/plumbing/permits/{id}/inspections` | Schedule an inspection visit | OfficeManager |
| GET | `/plumbing/permits/{id}/inspections` | List inspection visits for a permit | OfficeManager, Dispatcher, Technician |
| GET | `/plumbing/inspections` | List inspection visits, optionally filtered | OfficeManager, Dispatcher |
| GET | `/plumbing/inspections/{id}` | Read an inspection visit | OfficeManager, Dispatcher, Technician |
| POST | `/plumbing/inspections/{id}/record` | Record an inspection result | OfficeManager |
| GET | `/plumbing/service-jobs/{id}/invoices` | List invoices for a job | OfficeManager, Dispatcher, Customer |
| GET | `/plumbing/invoices/{id}` | Read an invoice with final totals | OfficeManager, Dispatcher, Customer |
| POST | `/plumbing/callbacks` | File a warranty callback against a completed job | Customer |
| GET | `/plumbing/callbacks/{id}` | Read a callback | OfficeManager, Dispatcher, Customer |
| GET | `/plumbing/service-jobs/{id}/callbacks` | List callbacks against a job | OfficeManager, Dispatcher, Customer |
| POST | `/plumbing/callbacks/{id}/accept` | Accept a within-warranty callback (reopens the job) | OfficeManager |
| POST | `/plumbing/callbacks/{id}/reject` | Reject a callback | OfficeManager |
| POST | `/plumbing/_clock/set` | Test-driving: set the server's current UTC clock | OfficeManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_JOB_VERSION` | 412 Precondition Failed |
| `ERR_SKILL_INSUFFICIENT` | 409 Conflict |
| `ERR_LICENSE_REQUIRED` | 409 Conflict |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INSPECTOR_CAPACITY_FULL` | 409 Conflict |
| `ERR_EMPTY_ESTIMATE` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
