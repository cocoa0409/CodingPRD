# Commercial Janitorial Services API — Product Requirements Document

## 1. Introduction

Commercial janitorial contractors juggle a deceptively complex operation: a portfolio of client accounts, each with one or more physical sites that carry their own scope of work, floor types, and quality expectations; recurring nightly routes staffed by rotating crews who clock in and out; periodic deep-cleaning add-ons such as strip-and-wax jobs; client complaints that trigger callback visits and billing credits; and a monthly contract-billing cycle that must reconcile flat recurring charges against periodic add-ons, quality holdbacks, and complaint credits. This document specifies a REST API that ties those moving parts together into a single auditable system of record.

The central tension the system resolves is the gap between what a job is *estimated* to cost in crew labor and what it *actually* costs once the time clock has run, and the gap between a *provisional* running invoice total while a billing period is still open and the *finalized* figures frozen at close. Quality scores from field inspections feed directly into billing through a holdback mechanism, and resolved complaints post credits back into the period that captured the offending visit. Because several operators may act on the same account concurrently, billing-period state changes are guarded by optimistic concurrency control. The sections below define the global contract every endpoint honors, then narrate the business workflows from intake through final invoicing.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (with the sole exception of the test-driving clock endpoint described in §3) must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting principal, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation under the matrix in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `AccountManager`, `FieldSupervisor`, `ClientContact`, and `PlatformAdmin`.

An `AccountManager` owns the commercial relationship: creating and suspending accounts, creating and archiving sites, drafting/activating/terminating contracts, requesting and cancelling periodic jobs, raising complaints, and operating the entire billing lifecycle. A `FieldSupervisor` runs field operations: managing schedules and routes, the full visit lifecycle, the time clock, inspections, periodic dispatch, the complaint-handling workflow, and supply fulfillment. A `ClientContact` is a site's designated client representative who raises and reopens complaints for their own site and reads their own site's records. A `PlatformAdmin` exists only to operate the test-driving clock surface.

All four roles use an **opaque** identity model. When `X-User-Role` is `AccountManager`, `FieldSupervisor`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `ClientContact`, `X-User-ID` is likewise an opaque identifier rather than the `id` of a stored user row — but it carries an ownership meaning: a `ClientContact` may act on a site (and the complaints, visits, and inspections belonging to that site) only when `X-User-ID` equals that site's `contact_user_id`. When a `ClientContact` attempts to raise or reopen a complaint, or to read a site-scoped record, for a site whose `contact_user_id` does not match the caller's `X-User-ID`, the request is rejected with `ERR_NOT_SITE_CONTACT` (HTTP 403). This ownership check is evaluated after authentication and role-permission checks but before resource-existence and business checks.

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

All list endpoints accept two pagination query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Results are always ordered by `created_at` ascending — that is, the oldest matching resource appears first. Each list response carries `limit`, `offset`, `total_count` (the number of resources matching the filter before pagination), and `has_more` (true when more resources remain beyond the current page) inside its `meta` object.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Most resources also carry three common audit properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increases by 1 on every mutation of that resource. The one exception is the `InvoiceLine` resource, which is an immutable append-only ledger row: an `InvoiceLine` carries only `id` and `created_at` — it has no `updated_at` and no `version`, because once written it is never modified (it can only be deleted wholesale when a period is reopened, as described in §3).

### 2.5. Nested Resource Retrieval and Foreign-Key Resolution

Path parameters are validated left-to-right. For an endpoint whose path names a parent resource and then a child, the parent is resolved first; if any path-referenced resource does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404). Separately, when a request body carries a foreign key — for example `account_id`, `site_id`, `contract_id`, `crew_id`, `visit_id`, `schedule_id`, `assigned_crew_id`, `billing_period_id`, or `contact_user_id` references — and that key points at a row that does not exist, the request fails with `ERR_FK_NOT_FOUND` (HTTP 404). Existence of path resources is checked before body foreign keys.

### 2.6. Request Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the most fundamental failure is the one reported. The order is: (1) authentication of the `X-User-ID` / `X-User-Role` headers, yielding `ERR_UNAUTHENTICATED`; (2) role permission for the operation, yielding `ERR_FORBIDDEN`; (3) the `ClientContact` site-ownership check, yielding `ERR_NOT_SITE_CONTACT`; (4) existence of path-referenced resources, yielding `ERR_NOT_FOUND`; (5) existence of body foreign keys, yielding `ERR_FK_NOT_FOUND`; (6) well-formedness of the request body — required fields present, enum values valid, and numeric ranges respected — yielding `ERR_INVALID_REQUEST` (HTTP 422); (7) whether the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE` (HTTP 409); and (8) the cross-entity business preconditions (account active, site active, crew available, callback visit completed, contract active) described throughout §3. Domain-specific business checks such as floor eligibility, shift capacity, crew double-booking, schedule-window conflict, period uniqueness, clock-range validity, and optimistic-concurrency staleness are evaluated within or after the state and referential checks at the point each workflow describes them.

Body well-formedness covers, among others: `cleanable_sqft` must be greater than 0; minutes-of-day fields fall in the range 0 to 1440; inspection `score` and site `quality_target` fall in the range 0 to 100; the percentage fields fall in the range 0.0 to 1.0; a schedule's `window_end_min` must be greater than its `window_start_min`; and a visit's `planned_end_min` must be greater than its `planned_start_min`. Any violation of these well-formedness rules yields `ERR_INVALID_REQUEST`.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation rounds an intermediate or final monetary figure, rounding is **half-up** to the nearest whole cent. Where a formula specifies rounding **per component** — notably the periodic add-on charge — each component is rounded to whole cents on its own and only then summed; the sum is not re-rounded. Labor minutes are integers; wherever the system divides square footage or hours to produce minutes it rounds **up** to the next whole minute (ceiling) exactly where the formula calls for it.

### 2.8. Optimistic Concurrency on Billing-Period Transitions

Closing and reopening a billing period are guarded by optimistic concurrency control keyed on the owning **account's** `version`. Both `POST /billing-periods/{billingPeriodId}/close` and `POST /billing-periods/{billingPeriodId}/reopen` require the caller to supply `expected_account_version` in the request body, carrying the account `version` the client last observed. The server compares it to the owning Account's current `version`. If they do not match — because some other close, reopen, or re-close of any period under that account has advanced the account's `version` since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change or ledger mutation occurs. This protects a client from acting on a billing view that no longer reflects the account's latest billing state. Endpoints that are not billing-period close/reopen do not take an `expected_account_version` field.

### 2.9. Cascade and Reconciliation Discipline

Several operations mutate more than one entity. Whenever a workflow updates a field on a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this applies to the directly targeted resource and to every secondary resource a cascade touches. The billing period's derived figures (`base_cents`, `periodic_cents`, `callback_credit_cents`, `holdback_cents`, `total_cents`, and `mean_quality_score`) are never set directly by a client; they are always recomputed by the system from the visits, complaints, and inspections captured into the period, as detailed in §3. The account-level `open_complaint_count` is likewise a derived count recomputed whenever a complaint on any of the account's sites changes state.

## 3. Business Logic & Workflows

### 3.1. Accounts and Sites: the Service Footprint

A new commercial relationship begins when an `AccountManager` creates an **account**, supplying the client company `name` and the `billing_email` to which invoices are sent. A freshly created account opens in `ACTIVE` `status`, with its derived `open_complaint_count` initialized to 0 and `version` at 1. An account may be moved to `SUSPENDED` status, which blocks the creation of new sites, visits, and contracts beneath it; a suspended (or `CLOSED`) account is no longer `ACTIVE`, and any operation that requires the owning account to be `ACTIVE` will be refused with `ERR_ACCOUNT_NOT_ACTIVE`. Reading an account returns its current `open_complaint_count` and `version`, which is the count of complaints across all of the account's sites whose `status` is any of `OPEN`, `ACKNOWLEDGED`, or `CALLBACK_SCHEDULED`.

Beneath an account live one or more **sites**, each created by an `AccountManager` with an `account_id` naming its owning account. A site records a human-readable `label` such as "HQ Lobby Tower", the `cleanable_sqft` (which must be greater than 0 and drives labor-hour estimation), and a `floor_type` of `CARPET`, `VCT`, `TERRAZZO`, or `CONCRETE`. The optional `quality_target` is the minimum acceptable inspection score in the range 0 to 100; if omitted it defaults to 85. A site also names a `contact_user_id`, the opaque identifier of the `ClientContact` authorized to raise complaints for the site (this is the value matched against `X-User-ID` for the ownership check of §2.1). A site opens in `ACTIVE` status and may be moved to `ARCHIVED`; an archived site accepts no new schedules or visits, and any operation requiring the site to be `ACTIVE` is refused with `ERR_SITE_ARCHIVED`. Of the `VCT`, `TERRAZZO`, `CARPET`, and `CONCRETE` floor types, only `VCT` and `TERRAZZO` are eligible for strip-and-wax periodic work.

### 3.2. Crews, Routes, and the Recurring Schedule

Field labor is performed by **crew members**, created by either an `AccountManager` or a `FieldSupervisor` with a `full_name`. Each crew member carries a `shift_capacity_min` — the maximum minutes the crew may clock in a single local day before overtime gating bites — which must be greater than 0 and defaults to 480 when not supplied. A crew member opens in `AVAILABLE` status. A `FieldSupervisor` may move a crew member to `INACTIVE`; an inactive crew member can neither be assigned to a route nor clocked onto a visit, and any operation that references an inactive crew is refused with `ERR_CREW_INACTIVE`.

To establish a recurring nightly route, a `FieldSupervisor` creates a **recurring schedule** for a site. The schedule names the `site_id`, the `weekday` the route runs as an integer where 0 is Monday through 6 is Sunday (so the value must be between 0 and 6 inclusive), and the service window expressed as minutes-after-midnight local: `window_start_min` (0 to 1439) and `window_end_min` (1 to 1440), where the end must be strictly greater than the start. It also names the `assigned_crew_id`, the crew responsible for that route slot. A schedule opens in `ACTIVE` status. When a new schedule is created, the system rejects any window that overlaps another `ACTIVE` schedule for the **same** crew on the **same** weekday. The conflict test uses closed-interval semantics: the windows `[window_start_min, window_end_min]` are compared inclusively, so two windows that merely touch at a shared boundary minute are treated as a conflict. A conflict yields `ERR_SCHEDULE_WINDOW_CONFLICT`.

A `FieldSupervisor` can pause an `ACTIVE` schedule, transitioning its `status` to `PAUSED`; a paused schedule generates no new visits. A paused schedule can be resumed back to `ACTIVE`, but only when it is currently `PAUSED`; resuming re-checks that the schedule's `assigned_crew_id` crew is `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`) and re-runs the same closed-interval window-conflict test against other `ACTIVE` schedules for that crew and weekday (otherwise `ERR_SCHEDULE_WINDOW_CONFLICT`).

### 3.3. Visits: from Scheduling through Completion

A **visit** is the unit of field work. A `FieldSupervisor` creates a visit naming the `site_id`, the `crew_id` expected to perform it, the `service_date` as a local `YYYY-MM-DD` string (which determines the billing month the visit settles into), and the planned window as `planned_start_min` and `planned_end_min` (the end strictly greater than the start). An optional `schedule_id` ties the visit to a recurring route slot, and an optional `visit_kind` selects `ROUTINE`, `PERIODIC`, or `CALLBACK`, defaulting to `ROUTINE`; `schedule_id` is null for ad-hoc periodic jobs and callbacks. A visit opens in `SCHEDULED` status.

On creation, the system computes a forward labor estimate into `estimated_labor_min` before any clock data exists. The estimate begins with a base figure equal to the site's `cleanable_sqft` divided by a productivity rate of 50 cleanable square feet per crew-minute, rounded up to the next whole minute. For a `ROUTINE` visit, `estimated_labor_min` is exactly that base figure. For a `CALLBACK` visit, the remediation pass is lighter: `estimated_labor_min` is the base figure multiplied by a callback factor of 0.40, rounded up to the next whole minute. For a `PERIODIC` visit, the human-quoted hours drive the estimate and square footage is ignored entirely: `estimated_labor_min` is the linked job's `quoted_hours` multiplied by 60, rounded up to the next whole minute.

At creation time, the system also rejects a visit whose planned interval would double-book the crew. Treating the planned span as the half-open interval from `planned_start_min` up to but not including `planned_end_min`, the system rejects the new visit if it overlaps any existing non-terminal visit — one in `SCHEDULED` or `IN_PROGRESS` status — for the **same** crew on the **same** `service_date`. Adjacency is permitted: when one visit ends exactly at the minute another begins, that shared boundary is not an overlap. A collision yields `ERR_CREW_DOUBLE_BOOKED`. This same crew-double-booking guard applies whenever a `PERIODIC` or `CALLBACK` visit is created as a cascade from a periodic-job dispatch or a complaint callback-scheduling.

A `FieldSupervisor` starts a `SCHEDULED` visit, advancing it `SCHEDULED → IN_PROGRESS`; starting requires that the visit's `crew_id` crew is `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`) and that the site is `ACTIVE` (otherwise `ERR_SITE_ARCHIVED`). From `SCHEDULED`, a visit may instead be marked `MISSED` (no labor is captured and nothing settles into billing; a missed routine visit contributes no inspection and therefore does not affect any period's mean quality score) or `CANCELLED`. Each of these three transitions out of `SCHEDULED` requires the visit to actually be in `SCHEDULED` status; otherwise the transition is refused with `ERR_INVALID_STATE`.

Completing a visit is the system's busiest moment and is described in §3.5 after the time clock is introduced.

### 3.4. The Time Clock

Crew labor is recorded through **time entries**. A `FieldSupervisor` clocks a crew member onto a visit by creating a time entry naming the `visit_id`, the `crew_id`, and the `clock_in_min` (minutes-after-midnight local, 0 to 1439). A new time entry opens in `OPEN` status with `clocked_min` at 0 and `clock_out_min` unset.

To close an entry, a `FieldSupervisor` clocks out, supplying `clock_out_min`. The entry must currently be `OPEN`; the supplied `clock_out_min` must be strictly greater than `clock_in_min` or the request is refused with `ERR_INVALID_CLOCK_RANGE` (HTTP 422); and the parent visit must be `IN_PROGRESS` or the request is refused with `ERR_INVALID_STATE`. There is also a shift-capacity guard: the crew's total clocked minutes for that crew across the visit's service local-day — counting this entry plus the crew's other already-`COMPLETED` entries on the same service date — must not exceed the crew's `shift_capacity_min`; exceeding it yields `ERR_SHIFT_CAPACITY_EXCEEDED`. On a successful clock-out, `clock_out_min` is set, `clocked_min` becomes `clock_out_min` minus `clock_in_min`, and the entry transitions `OPEN → COMPLETED`. An `OPEN` entry may instead be voided, transitioning `OPEN → VOIDED`; a voided entry is excluded from a visit's actual-labor accumulation.

### 3.5. Completing a Visit: Labor Capture and Billing Settlement

A `FieldSupervisor` completes an `IN_PROGRESS` visit, advancing it `IN_PROGRESS → COMPLETED`. Completion is gated by two clock conditions: at least one time entry for the visit must already be `COMPLETED` (otherwise `ERR_NO_TIME_ENTRY`), and no time entry for the visit may still be `OPEN` (otherwise `ERR_OPEN_TIME_ENTRY`).

When those gates pass, the system first recomputes the visit's `actual_labor_min`. It walks the visit's time entries whose `status` is `COMPLETED`, in `created_at` ascending order (the entry `id` is never used for ordering), and accumulates each entry's `clocked_min` into a running sum that becomes `actual_labor_min`; `VOIDED` and `OPEN` entries are excluded. Note that `estimated_labor_min` and `actual_labor_min` are distinct: the former is the forward projection from square footage or quoted hours computed at creation, while the latter is the chronological sum of clocked entries — the same visit, two different subjects, and the difference between them is what drives overage billing.

Completion then settles the visit into billing. The system locates the `OPEN` billing period of the site's contract for the month of the visit's `service_date`; if the contract is `ACTIVE` and no such open period exists yet, one is opened. The completed visit's `billing_period_id` is set to that period. Capturing the visit recomputes the period's running totals: for a `PERIODIC` visit the period's `periodic_cents` grows by the visit's periodic charge (see §3.6), and the period's `total_cents` is recomputed by the provisional total formula of §3.8. Finally, if the visit's `visit_kind` is `PERIODIC`, the linked periodic job is advanced `DISPATCHED → BILLED` as a cascade. Each of these touched resources — the visit, the billing period, and the periodic job — has its `updated_at` and `version` refreshed.

### 3.6. Periodic Add-On Jobs

Strip-and-wax and deep-carpet work are handled as **periodic jobs**, requested by an `AccountManager` for a site. A request names the `site_id`, a `job_type` of either `STRIP_WAX` or `DEEP_CARPET`, the `quoted_hours` of labor (which must be greater than 0 and is billed at the contract's hourly rate), and a `requested_date` as a local `YYYY-MM-DD` target. A periodic job opens in `REQUESTED` status. From `REQUESTED`, an `AccountManager` may cancel it, transitioning it `REQUESTED → CANCELLED`.

A `FieldSupervisor` dispatches a `REQUESTED` periodic job. Dispatch requires the job to be in `REQUESTED` status, the site to be `ACTIVE` (otherwise `ERR_SITE_ARCHIVED`), and the assigned crew to be `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`). When `job_type` is `STRIP_WAX`, the site's `floor_type` must be `VCT` or `TERRAZZO`, since strip-and-wax is only valid on those finishes; a strip-wax dispatch onto any other floor is refused with `ERR_FLOOR_INELIGIBLE`. The dispatch request supplies the `crew_id` who will perform the work, the `service_date`, and the `planned_start_min` and `planned_end_min` of the visit. On success, the system creates a new `PERIODIC` visit in `SCHEDULED` status with its `periodic_job_id` pointing back at the job (subject to the same crew-double-booking guard of §3.3), sets the job's `visit_id` to the new visit, and advances the job `REQUESTED → DISPATCHED`. The new periodic visit's `estimated_labor_min` is computed from `quoted_hours` rather than square footage, as described in §3.3.

When that dispatched periodic visit later completes, the periodic add-on is priced and captured. The add-on is billed on the greater of the quoted and actual labor, with an overage surcharge on the minutes beyond the quote. Concretely: the quoted minutes are `quoted_hours` multiplied by 60, rounded up to a whole minute; the actual minutes are the visit's `actual_labor_min`; the billable minutes are the larger of the two; the overage minutes are the actual minutes minus the quoted minutes, but never less than 0; and the straight minutes are the billable minutes minus the overage minutes. The per-minute rate is the contract's `hourly_rate_cents` divided by 60. The straight portion is the straight minutes multiplied by the per-minute rate, rounded half-up to whole cents; the overage portion is the overage minutes multiplied by the per-minute rate multiplied by an overage multiplier of 1.5, rounded half-up to whole cents; and the periodic charge is the straight portion plus the overage portion — each component rounded first, then summed in that pinned order, never summed and then rounded. That periodic charge is what grows the capturing period's `periodic_cents`, and the job's transition to `BILLED` happens as the cascade of §3.5.

### 3.7. Complaints, Callbacks, and Credits

A **complaint** is raised either by the site's `ClientContact` (for their own site) or by an `AccountManager`. A complaint names the `site_id`, a `severity` of `MINOR` or `MAJOR`, a free-text `description`, and optionally the `visit_id` of the completed visit it concerns. A complaint opens in `OPEN` status; on creation the owning account's `open_complaint_count` is recomputed.

The complaint then moves through a handling cycle driven by a `FieldSupervisor`. Acknowledging an `OPEN` complaint advances it `OPEN → ACKNOWLEDGED` and recomputes the owning account's `open_complaint_count`. From `ACKNOWLEDGED`, scheduling a callback advances it `ACKNOWLEDGED → CALLBACK_SCHEDULED`: this requires the site to be `ACTIVE` (otherwise `ERR_SITE_ARCHIVED`) and the assigned crew to be `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`), and it creates a new `CALLBACK` visit in `SCHEDULED` status whose `complaint_id` points back at the complaint (again under the crew-double-booking guard of §3.3). The schedule-callback request supplies the `crew_id`, `service_date`, `planned_start_min`, and `planned_end_min` for that callback visit. The complaint's `callback_visit_id` is set to the new visit.

Resolving a complaint advances it `CALLBACK_SCHEDULED → RESOLVED`, but only once the callback visit named by `callback_visit_id` is itself `COMPLETED`; resolving while the callback visit is not yet complete is refused with `ERR_CALLBACK_NOT_COMPLETE`. On resolution, the system computes the callback credit and posts it. The credit starts from the contract's `monthly_base_cents` multiplied by the contract's `callback_credit_pct`; if the complaint's `severity` is `MAJOR`, the fraction is increased by a major-severity bonus of 0.05 (five percentage points) before multiplying — a `MINOR` complaint uses the bare contract percentage. That product is rounded half-up to whole cents, and the credit is then capped so it never exceeds one month's base: the posted `credit_applied_cents` is the smaller of the rounded raw credit and `monthly_base_cents`. The credit is posted into the `OPEN` billing period of the site's contract for the month of the callback visit's `service_date`: the period's `callback_credit_cents` grows by the credit and `total_cents` is recomputed via the provisional formula. The complaint's `status` becomes `RESOLVED`, and the owning account's `open_complaint_count` is recomputed.

A resolved complaint may be reopened, but reopening is restricted to the site's `ClientContact` and only for complaints whose `severity` is `MAJOR`; attempting to reopen a `MINOR` resolved complaint is refused with `ERR_REOPEN_NOT_ALLOWED`. Reopening advances the complaint `RESOLVED → OPEN`, clears its `callback_visit_id`, leaves the previously posted credit in place (it is not clawed back), and recomputes the owning account's `open_complaint_count`.

### 3.8. Inspections and the Quality Signal

Quality is captured through **inspections**, recorded by a `FieldSupervisor` against a visit. An inspection names the `visit_id` and a `score` from 0 to 100, with optional `notes`. On creation the system computes `deficient` as true when the `score` is below the site's `quality_target` at the time of inspection, and false otherwise. Inspections of completed routine visits feed the billing period's quality signal: the period's `mean_quality_score` is the mean of the `score` values over inspections of the `COMPLETED` `ROUTINE` visits captured into that period. The system expects one inspection per visit; if a visit somehow carries more than one, the latest by `created_at` ascending tie-break is used. When no such inspection exists, `mean_quality_score` is null and the period is treated as meeting target so that no holdback applies.

### 3.9. Contracts and the Billing Period Lifecycle

A **service contract** binds the recurring commercial terms to a site. An `AccountManager` creates a contract naming the `site_id`, the flat `monthly_base_cents` recurring charge (greater than 0), the `hourly_rate_cents` rate per labor-hour used for periodic add-ons and overage (greater than 0), and two optional fractions in the range 0.0 to 1.0: `callback_credit_pct`, the fraction of the monthly base credited per resolved callback (defaulting to 0.10), and `quality_holdback_pct`, the fraction of the monthly base withheld when a period's mean inspection score falls below the site's quality target (defaulting to 0.05). A contract opens in `DRAFT` status.

Activating a `DRAFT` contract advances it `DRAFT → ACTIVE`; activation requires the site to be `ACTIVE` (otherwise `ERR_SITE_ARCHIVED`) and the owning account to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`). Only an `ACTIVE` contract may back billing periods. Terminating an `ACTIVE` contract advances it `ACTIVE → TERMINATED`, but only when no billing period of the contract is in `OPEN` or `REOPENED` status; a still-open period blocks termination with `ERR_PERIOD_OPEN`. After termination, no further billing periods may open.

A **billing period** is opened by an `AccountManager` for a contract and a month, naming the `contract_id` and the `period_month` as a `YYYY-MM` string. The pair of `contract_id` and `period_month` is unique; opening a duplicate period for the same contract and month is refused with `ERR_DUPLICATE_PERIOD`. A period opens in `OPEN` status; on open the system snapshots the contract's `monthly_base_cents` into the period's `base_cents`, and its `total_cents` starts at that base. Opening a period requires the backing contract to be `ACTIVE`; otherwise the operation is refused with `ERR_CONTRACT_NOT_ACTIVE`.

A period's total is computed by a single pinned-order formula with a provisional variant and a final variant. The evaluation order is fixed to avoid an apparent circular dependency between the holdback and the total. First, `base_cents` is the snapshot taken at open. Second, `periodic_cents` is the sum of the periodic charges over the `PERIODIC` visits captured into this period (those whose `billing_period_id` equals the period's `id`). Third, `callback_credit_cents` is the sum of the `credit_applied_cents` over the `RESOLVED` complaints posted to this period. Fourth, `mean_quality_score` is the mean inspection score over the captured completed routine visits as described in §3.8, or null if there are none (treated as meeting target). Fifth comes the holdback: in the **provisional** variant, used while the period is `OPEN`, `holdback_cents` is forced to 0 because quality is not yet final; in the **final** variant, used when the period closes, `holdback_cents` is `base_cents` multiplied by the contract's `quality_holdback_pct` rounded half-up to whole cents when `mean_quality_score` is non-null and strictly below the site's `quality_target`, and 0 otherwise. Finally, `total_cents` is `base_cents` plus `periodic_cents` minus `callback_credit_cents` minus `holdback_cents`. Because the holdback is keyed off `base_cents` rather than off the running total, the order breaks the apparent cycle. While the period is `OPEN`, this total is provisional and rises or falls as visits complete and credits post; at close it is finalized and frozen into the ledger.

Closing a period is performed by an `AccountManager` and advances it `OPEN → CLOSED`. The caller must supply `expected_account_version` matching the owning account's current `version`, or the close is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.8. The close also requires that no visit captured into this period (any visit whose `billing_period_id` equals the period's `id`) is currently `IN_PROGRESS`; an in-progress captured visit blocks the close with `ERR_VISIT_IN_PROGRESS`. On a successful close, the system recomputes `mean_quality_score`, `holdback_cents`, and `total_cents` using the final variant; emits the immutable invoice-line ledger for the period — a `BASE` line, one `PERIODIC` line for the summed captured periodic charges, one `CALLBACK_CREDIT` line, and one `HOLDBACK` line, each carrying a signed `amount_cents` (positive for charges, negative for credits and holdback), the `billing_period_id`, a `line_type`, and a human-readable `memo`; sets the period's `status` to `CLOSED`; and increments the owning account's `version` by 1.

A `CLOSED` period may be reopened by an `AccountManager`, advancing it `CLOSED → REOPENED`. The reopen likewise requires `expected_account_version` to match the account's current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412). Reopening deletes the invoice lines previously emitted for the period as a compensating action, reverts `total_cents` to a provisional recompute, sets the period's `status` to `REOPENED`, and increments the account's `version` by 1. A `REOPENED` period can be closed again, which requires `expected_account_version` to match, re-checks that no captured visit is `IN_PROGRESS` (otherwise `ERR_VISIT_IN_PROGRESS`), recomputes the final totals, re-emits the four invoice-line rows, advances the period back to `CLOSED`, and once more increments the account's `version` by 1.

Finally, a `CLOSED` period may be invoiced by an `AccountManager`, advancing it `CLOSED → INVOICED`; this is terminal and freezes the figures. Each of these billing-period transitions requires the period to be in the precondition state named, or the request is refused with `ERR_INVALID_STATE`.

### 3.10. Supplies

Consumables are tracked through **supply orders**, placed by either a `FieldSupervisor` or an `AccountManager` for a site. An order names the `site_id`, a `sku` of `PAPER_TOWEL`, `TRASH_LINER`, `FLOOR_FINISH`, or `RESTROOM_KIT`, and a `quantity` of units (which must be greater than 0). An order opens in `REQUESTED` status. A `FieldSupervisor` may fulfill a requested order, advancing it `REQUESTED → FULFILLED`. From `REQUESTED`, either an `AccountManager` or a `FieldSupervisor` may cancel it, advancing it `REQUESTED → CANCELLED`. Each transition requires the order to be in `REQUESTED` status; otherwise it is refused with `ERR_INVALID_STATE`.

### 3.11. The Test-Driving Clock

For test orchestration, a `PlatformAdmin` may set the server's notion of the current local date and time by supplying a `to_iso8601` value. This capability advances the logical clock used when the system derives a visit's settling month and a period's month from a `service_date`. It is the one surface that does not require the standard authentication headers.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a brand-new resource returns HTTP 201; state transitions and other modifications of an existing resource return HTTP 200, as do reads. Error responses carry the appropriate 4xx status and the error envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/accounts` | Create an account | AccountManager |
| GET | `/accounts/{accountId}` | Get an account | AccountManager, FieldSupervisor |
| GET | `/accounts` | List accounts (paginated) | AccountManager |
| POST | `/accounts/{accountId}/suspend` | Suspend an account | AccountManager |
| POST | `/sites` | Create a site under an account | AccountManager |
| GET | `/sites/{siteId}` | Get a site | AccountManager, FieldSupervisor, ClientContact |
| GET | `/sites` | List sites, optionally filtered by account | AccountManager, FieldSupervisor |
| POST | `/sites/{siteId}/archive` | Archive a site | AccountManager |
| POST | `/contracts` | Create a DRAFT service contract for a site | AccountManager |
| GET | `/contracts/{contractId}` | Get a contract | AccountManager |
| GET | `/contracts` | List contracts, optionally filtered by site | AccountManager |
| POST | `/contracts/{contractId}/activate` | Activate a DRAFT contract | AccountManager |
| POST | `/contracts/{contractId}/terminate` | Terminate an ACTIVE contract | AccountManager |
| POST | `/crew` | Create a crew member | AccountManager, FieldSupervisor |
| GET | `/crew/{crewId}` | Get a crew member | AccountManager, FieldSupervisor |
| POST | `/crew/{crewId}/deactivate` | Mark a crew member INACTIVE | FieldSupervisor |
| POST | `/schedules` | Create a recurring schedule for a site | FieldSupervisor |
| GET | `/schedules/{scheduleId}` | Get a schedule | AccountManager, FieldSupervisor |
| GET | `/schedules` | List schedules, optionally filtered by site or crew | AccountManager, FieldSupervisor |
| POST | `/schedules/{scheduleId}/pause` | Pause a schedule | FieldSupervisor |
| POST | `/schedules/{scheduleId}/resume` | Resume a paused schedule | FieldSupervisor |
| POST | `/visits` | Create a visit (ad-hoc or from a schedule) | FieldSupervisor |
| GET | `/visits/{visitId}` | Get a visit | AccountManager, FieldSupervisor, ClientContact |
| GET | `/visits` | List visits with filters | AccountManager, FieldSupervisor |
| POST | `/visits/{visitId}/start` | Start a scheduled visit | FieldSupervisor |
| POST | `/visits/{visitId}/complete` | Complete an in-progress visit | FieldSupervisor |
| POST | `/visits/{visitId}/miss` | Mark a scheduled visit MISSED | FieldSupervisor |
| POST | `/visits/{visitId}/cancel` | Cancel a scheduled visit | FieldSupervisor |
| POST | `/time-entries` | Clock a crew member onto a visit | FieldSupervisor |
| GET | `/time-entries/{timeEntryId}` | Get a time entry | AccountManager, FieldSupervisor |
| GET | `/time-entries` | List time entries, filtered by visit or crew | AccountManager, FieldSupervisor |
| POST | `/time-entries/{timeEntryId}/clock-out` | Clock out (close) a time entry | FieldSupervisor |
| POST | `/time-entries/{timeEntryId}/void` | Void an open time entry | FieldSupervisor |
| POST | `/inspections` | Record a quality inspection for a visit | FieldSupervisor |
| GET | `/inspections/{inspectionId}` | Get an inspection | AccountManager, FieldSupervisor, ClientContact |
| GET | `/inspections` | List inspections, filtered by visit | AccountManager, FieldSupervisor |
| POST | `/periodic-jobs` | Request a periodic add-on for a site | AccountManager |
| GET | `/periodic-jobs/{periodicJobId}` | Get a periodic job | AccountManager, FieldSupervisor |
| GET | `/periodic-jobs` | List periodic jobs, filtered by site | AccountManager, FieldSupervisor |
| POST | `/periodic-jobs/{periodicJobId}/dispatch` | Dispatch a periodic job (creates a PERIODIC visit) | FieldSupervisor |
| POST | `/periodic-jobs/{periodicJobId}/cancel` | Cancel a requested periodic job | AccountManager |
| POST | `/complaints` | Raise a complaint for a site | ClientContact, AccountManager |
| GET | `/complaints/{complaintId}` | Get a complaint | AccountManager, FieldSupervisor, ClientContact |
| GET | `/complaints` | List complaints, filtered by site | AccountManager, FieldSupervisor |
| POST | `/complaints/{complaintId}/acknowledge` | Acknowledge an open complaint | FieldSupervisor |
| POST | `/complaints/{complaintId}/schedule-callback` | Schedule a callback visit | FieldSupervisor |
| POST | `/complaints/{complaintId}/resolve` | Resolve a complaint once its callback is complete | FieldSupervisor |
| POST | `/complaints/{complaintId}/reopen` | Reopen a resolved MAJOR complaint | ClientContact |
| POST | `/billing-periods` | Open a billing period for a contract/month | AccountManager |
| GET | `/billing-periods/{billingPeriodId}` | Get a billing period | AccountManager |
| GET | `/billing-periods` | List billing periods, filtered by contract | AccountManager |
| POST | `/billing-periods/{billingPeriodId}/close` | Close a billing period; finalize and emit lines | AccountManager |
| POST | `/billing-periods/{billingPeriodId}/reopen` | Reopen a closed billing period | AccountManager |
| POST | `/billing-periods/{billingPeriodId}/invoice` | Mark a closed billing period as invoiced | AccountManager |
| GET | `/billing-periods/{billingPeriodId}/invoice-lines` | List the invoice lines for a billing period | AccountManager |
| POST | `/supply-orders` | Order consumables for a site | FieldSupervisor, AccountManager |
| GET | `/supply-orders/{supplyOrderId}` | Get a supply order | AccountManager, FieldSupervisor |
| GET | `/supply-orders` | List supply orders, filtered by site | AccountManager, FieldSupervisor |
| POST | `/supply-orders/{supplyOrderId}/fulfill` | Mark a supply order fulfilled | FieldSupervisor |
| POST | `/supply-orders/{supplyOrderId}/cancel` | Cancel a requested supply order | AccountManager, FieldSupervisor |
| POST | `/_clock/set` | Set the server's current local date/time | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_SITE_CONTACT | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_SITE_ARCHIVED | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_CREW_INACTIVE | 409 |
| ERR_FLOOR_INELIGIBLE | 409 |
| ERR_NO_TIME_ENTRY | 409 |
| ERR_OPEN_TIME_ENTRY | 409 |
| ERR_INVALID_CLOCK_RANGE | 422 |
| ERR_SHIFT_CAPACITY_EXCEEDED | 409 |
| ERR_CREW_DOUBLE_BOOKED | 409 |
| ERR_SCHEDULE_WINDOW_CONFLICT | 409 |
| ERR_CALLBACK_NOT_COMPLETE | 409 |
| ERR_REOPEN_NOT_ALLOWED | 409 |
| ERR_DUPLICATE_PERIOD | 409 |
| ERR_PERIOD_OPEN | 409 |
| ERR_VISIT_IN_PROGRESS | 409 |
| ERR_STALE_VERSION | 412 |
