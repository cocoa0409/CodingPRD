# Electrical Contractor Dispatch API — Product Requirements Document

## 1. Introduction

Residential and commercial electrical contractors juggle a deceptively complex operation: a customer phones in for a tripped panel or a new EV charger, an estimate must be drawn up and accepted, a licensed technician has to be routed to the right zone within a promised arrival window, permits and inspections have to clear before the work is legally complete, and only then can the job be billed, warrantied, and — when a defect resurfaces — recalled under warranty. This document specifies a back-office and field dispatch API that ties all of those threads together into a single auditable workflow, from the first DRAFT job through final closeout.

The platform serves four distinct constituencies whose surfaces rarely overlap. A back-office **Dispatcher** provisions the catalog, prices the work, routes technicians, files permits, and settles the books. A **Customer** requests work on their own address, accepts or rejects the prices they are quoted, enrolls in a recurring membership, and files warranty callbacks. A field **Technician** drives to the site, records the parts pulled off the truck, and marks the work done. A jurisdiction **Inspector** issues permits and records pass/fail outcomes. The system's value lies in enforcing the contractor's business rules consistently — license gating, zone matching, double-booking prevention, truck-stock balances, dual-mode pricing, and a warranty-callback loop — so that no job can be scheduled, completed, or invoiced out of sequence.

Because pricing is offered in two fundamentally different shapes (a fixed flat-rate book versus a time-and-materials calculation), and because the same job can re-enter the work cycle after a warranty callback, the data model and its state machines are the heart of this specification. The sections below define the global request/response contract first, then the cross-cutting principles that govern every endpoint, and finally the business workflows in detail.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-Role` header must name one of exactly four recognized roles — `Dispatcher`, `Customer`, `Technician`, or `Inspector`. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation according to the authorization rules in this document, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles map to identity differently, and this mapping determines how ownership is enforced. When `X-User-Role` is `Customer`, the `X-User-ID` value is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare that resource's customer foreign key to `X-User-ID`. When `X-User-Role` is `Technician`, the `X-User-ID` value is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare that resource's technician foreign key to `X-User-ID`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

When an entity-backed actor (a `Customer` or a `Technician`) targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). For example, a `Customer` may only accept, reject, cancel, or file callbacks against jobs whose `customer_id` equals their own `X-User-ID`, and a `Technician` may only depart, arrive, or record material against dispatches and trucks tied to their own `X-User-ID`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must be at least 0. List results are returned in ascending order of `created_at` unless a specific endpoint's narrative states otherwise. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` in its `meta` object: `total_count` is the count of all records matching the query before pagination is applied, and `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` that is a UUID with no type prefix. All entities in this system carry the full set of common properties: `id`, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. The `version` field is an integer that begins at 1 when the resource is created and increments by one on every mutation of that resource. Whenever a resource is modified — whether through a direct field change or a state transition — its `updated_at` is refreshed to the current server time and its `version` is incremented.

### 2.5. Optimistic Concurrency on Job-Scoped Creates

Two write operations create child records against a parent `ServiceJob` and therefore guard against operating on a stale view of that job: creating an estimate and creating a dispatch. Each of these requests must include a non-optional `expected_job_version` field carrying the `version` of the parent `ServiceJob` that the client last observed.

When a client submits a request to create an estimate, the supplied `expected_job_version` must equal the target job's current `version`. If another writer has advanced the job's `version` since the client last read it — for instance, by having a competing estimate accepted, which bubbles the job to `QUOTED` and increments its version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from layering an estimate onto a job state it has not seen. Successfully creating an estimate itself increments the parent `ServiceJob.version` by one.

Likewise, when a client submits a request to create a dispatch, the supplied `expected_job_version` must equal the target job's current `version`. If another writer has already scheduled a dispatch — which bubbles the job to `SCHEDULED` and increments its version — a second create carrying the older version is rejected with `ERR_STALE_VERSION` (HTTP 412). Successfully creating a dispatch increments the parent `ServiceJob.version` by one. No other endpoint in this system accepts a version field; the version check applies only to these two job-scoped creates.

### 2.6. Validation Order and Precedence

When multiple checks could reject a single request, they are evaluated in a fixed precedence so that the surfaced error is deterministic. The order is: first authentication (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of every path- and body-referenced resource, validated left-to-right (`ERR_NOT_FOUND`); then resource ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`); then request-body well-formedness (`ERR_INVALID_REQUEST`); then optimistic-concurrency version matching on the two job-scoped creates (`ERR_STALE_VERSION`); then state-transition legality (`ERR_INVALID_STATE`); and finally the domain-specific business checks (license, on-call, zone, double-booking, permit, stock, single-invoice, open-callback, warranty-coverage, and uniqueness). A request that fails an earlier check is rejected with that check's error before any later check is considered.

Request-body well-formedness covers required fields being present, enum-typed fields carrying a recognized value, quantities being strictly greater than zero, and any arrival window having its `window_start` strictly before its `window_end`; any of these failing yields `ERR_INVALID_REQUEST` (HTTP 422).

### 2.7. Nested Resource Resolution

Several endpoints address a resource through a path that names it directly by identifier — for example a permit by `permitId`, a dispatch by `dispatchId`, an estimate by `estimateId`, a job by `jobId`, a usage by `usageId`, a callback by `callbackId`, a stock item by `stockItemId`, a customer by `customerId`, a technician by `technicianId`, a plan by `planId`, a membership by `membershipId`, a SKU by `skuId`, or an invoice by `invoiceId`. Every path identifier is resolved left-to-right; if any referenced resource does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any further processing. The same existence check applies to identifiers carried in request bodies, such as the `customer_id`, `plan_id`, `job_id`, `technician_id`, and `sku_id` foreign keys.

### 2.8. Monetary Precision and Rounding

All monetary amounts in this system are stored and computed as integer cents; there are no fractional-cent values. Wherever a calculation multiplies a quantity by a rate or applies a percentage — labor hours times an hourly rate, a labor subtotal times a membership discount fraction, a taxable base times the tax rate — the result is rounded half up to the nearest whole cent. Each such rounding step is applied independently at the point it occurs; the system rounds at each step and then sums, rather than summing exact intermediate values and rounding once at the end.

### 2.9. The Logical Clock

Time-sensitive behavior in this system — warranty windows, callback coverage, and membership enrollment timestamps — is evaluated against the server's current UTC clock. For deterministic testing, the server exposes an administrative capability that sets the server's current UTC instant to a supplied `to_iso8601` value. Once set, all subsequent time-derived computations (such as the warranty end and whether a callback falls within it) read from this logical clock rather than wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Catalog: Customers, Technicians, Plans, and Parts

Before any work can be dispatched, the back office establishes the reference data. A `Customer` record carries the customer's `full_name`, an `email`, a service-address `service_zip`, and a `phone`. The `email` must be unique across all customers; an attempt to create a second customer with an `email` already in use is rejected with `ERR_DUPLICATE`. The `service_zip` is significant beyond contact information: its ZIP-prefix determines the service zone into which the customer's jobs are routed. This zone is the leading three characters of the customer's `service_zip` (its first three characters); a technician's `service_zone` and the `zone` query parameter of the dispatch queue are each compared for exact string equality against this three-character zone (they are stored and supplied as-is and are not themselves truncated).

A `Technician` record carries a `full_name`, a `license_class` that is either `JOURNEYMAN` or `MASTER`, a `service_zone` expressed as the ZIP-prefix zone the technician covers, an `hourly_rate_cents` labor rate used in time-and-materials pricing, and an `on_call` boolean that defaults to false and marks the technician as eligible for emergency dispatch. Only a `MASTER` technician may be assigned to panel or EV-charger work, and a technician's `service_zone` must match a job's zone for that technician to be dispatchable — both rules are enforced at dispatch time and described in the dispatch workflow below.

Memberships are defined by a `MembershipPlan` and instantiated as a `Membership`. A plan carries a `name`, a `tier` of either `BASIC` or `PREMIER`, a `monthly_fee_cents` recurring fee, a `labor_discount_pct` expressed as a fraction between 0 and 1 that is applied to the labor subtotal on member jobs, a `waives_dispatch_fee` boolean (default false) that — when true — causes the trip fee to be waived on that member's jobs, and a `priority_dispatch` boolean (default false) that — when true — ranks that member's jobs ahead of non-member jobs in the dispatch queue. Enrolling a customer creates a `Membership` referencing the customer via `customer_id` and the chosen plan via `plan_id`; on enrollment the system sets its `status` to `ACTIVE` and stamps `started_at` with the current server time. A membership may later be cancelled, which moves its `status` to `CANCELLED`. A customer may enroll themselves or be enrolled by a dispatcher; a customer may only act on their own membership.

The parts catalog is a set of `MaterialSku` price-book entries, each with a `sku_code`, a human-readable `description`, a `unit_price_cents` sell price, and a `taxable` boolean (default true) indicating whether material lines for that SKU are taxed. The `sku_code` must be unique across all SKUs; a duplicate `sku_code` is rejected with `ERR_DUPLICATE`.

### 3.2. Truck Stock and Material Balances

Each technician's truck inventory is tracked as `TruckStockItem` records, one per part stocked on a given truck. Stocking a part records the `technician_id` whose truck holds it, the `sku_id` of the part, an opening `quantity_on_hand`, and a `reorder_threshold` advisory floor (default 0). The item also exposes a computed `low_stock` flag, which is true exactly when the `quantity_on_hand` is at or below the `reorder_threshold`, and is recomputed on every change to the on-hand quantity. A dispatcher may add units to an existing stock item via a restock that takes an `add_quantity`; the units are added to `quantity_on_hand` and `low_stock` is recomputed.

The on-hand balance moves whenever material is consumed or that consumption is reversed. When a technician records a `MaterialUsage`, the truck-stock item identified by the usage's `technician_id` and `sku_id` has its `quantity_on_hand` decreased by the consumed `quantity`. The on-hand balance may never go negative: a usage whose `quantity` exceeds the current `quantity_on_hand` is rejected with `ERR_INSUFFICIENT_STOCK`. The boundary is inclusive on the side of success — a usage of exactly the current `quantity_on_hand` succeeds and leaves the balance at zero, while a usage of one unit more than the on-hand amount is rejected. After a successful debit, `low_stock` is recomputed. When a usage is voided, the previously consumed `quantity` is added back to the same truck-stock item's `quantity_on_hand` and `low_stock` is recomputed once more.

### 3.3. Opening a Job and Quoting the Work

A service request begins life as a `ServiceJob` in `DRAFT` status. Creating a job records the requesting `customer_id`, the `scope` of work (`OUTLET`, `PANEL`, or `EV_CHARGER`), the `job_class` (`SERVICE` or `INSTALL`), and an optional `priority` that defaults to `STANDARD` and may otherwise be `EMERGENCY`. At creation the system derives several fields: `requires_permit` is set true when the `scope` is either `PANEL` or `EV_CHARGER` and false for `OUTLET` work; `membership_id` is snapshotted from the customer's currently `ACTIVE` membership at the moment of job creation, or left null if the customer has no active membership; `total_due_cents` is initialized to 0; and the job's `status` is `DRAFT`. The `pricing_mode`, `warranty_until`, and `total_due_cents` remain unset or zero until later stages populate them. A customer may open a job for themselves, or a dispatcher may open one on their behalf.

Pricing is captured as one or more `Estimate` records against the job. An estimate names its `job_id`, a `pricing_mode` of either `FLAT_RATE` or `TIME_MATERIALS`, and — depending on the mode — a `flat_rate_cents` quoted price (required for flat-rate, ignored otherwise), an `estimated_labor_hours` figure (required for time-and-materials), and an `estimated_material_cents` quoted material cost. Creating an estimate also requires the `expected_job_version` described in the concurrency principle. On creation the estimate's `status` is `DRAFT` and its `quoted_total_cents` is computed immediately.

The quoted total is a forward-looking projection built only from the estimate's own inputs. When the `pricing_mode` is `FLAT_RATE`, the `quoted_total_cents` equals the `flat_rate_cents` verbatim, and the estimated hours and materials are ignored. When the `pricing_mode` is `TIME_MATERIALS`, the system computes a labor figure by multiplying `estimated_labor_hours` by an hourly rate and rounding the product half up to whole cents, then adds the `estimated_material_cents`; the `flat_rate_cents` is ignored. The hourly rate used here is the dispatched technician's `hourly_rate_cents` if a technician is already known at quote time; if no technician has been dispatched yet, the system uses the default zone rate of 12000 cents per hour. This quote deliberately uses estimated hours and materials, never realized actuals.

### 3.4. From Quote to Schedule: Accepting Estimates and Dispatching

A draft estimate is not visible to the customer until it is sent. A dispatcher sends an estimate, moving it from `DRAFT` to `SENT`; this is permitted only while the estimate is `DRAFT` and the parent job is in `DRAFT` or `QUOTED`. Once sent, the owning customer may accept or reject it. Acceptance is allowed only when the estimate is `SENT` and the accepting customer owns the parent job; on acceptance the estimate moves `SENT → ACCEPTED`, every sibling estimate on the same job that is still in `SENT` or `DRAFT` is moved to `SUPERSEDED`, the parent job's `pricing_mode` is copied from the accepted estimate, and a job in `DRAFT` or `QUOTED` is bubbled to `QUOTED`. Rejection is allowed only when the estimate is `SENT` and the rejecting customer owns the parent job; it simply moves the estimate `SENT → REJECTED` with no effect on siblings or the job. An estimate also reaches `SUPERSEDED` from either `DRAFT` or `SENT` automatically whenever a sibling on the same job is accepted or whenever the job itself is cancelled.

With an accepted estimate in hand, a dispatcher routes a technician by creating a `Dispatch`. A dispatch names the `job_id`, the assigned `technician_id`, and an arrival window bounded by `window_start` (inclusive) and `window_end` (exclusive), and it must carry the `expected_job_version`. On creation the dispatch's `status` is `ASSIGNED` and its `eta` (the promised arrival) defaults to the `window_start`. Creating the first assigned dispatch on a `QUOTED` job bubbles the job from `QUOTED` to `SCHEDULED`. Several preconditions guard dispatch creation, and they are surfaced as distinct errors:

- The job must be `QUOTED` (an estimate must already have been accepted); otherwise the create cannot legally proceed and is rejected with `ERR_INVALID_STATE`.
- The assigned technician's `service_zone` must match the job's zone, derived from the customer's `service_zip` prefix; a mismatch is rejected with `ERR_ZONE_MISMATCH`.
- When the job's `scope` is `PANEL` or `EV_CHARGER`, the assigned technician's `license_class` must be `MASTER`; a `JOURNEYMAN` assigned to such work is rejected with `ERR_LICENSE_INSUFFICIENT`.
- When the job's `priority` is `EMERGENCY`, the assigned technician's `on_call` flag must be true; assigning a technician who is not on call is rejected with `ERR_TECH_NOT_ON_CALL`.
- The new arrival window must not overlap any existing active dispatch on the same technician; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`.

The double-booking test treats windows as half-open intervals spanning from `window_start` up to but not including `window_end`. Two windows on the same technician conflict precisely when the new window's start is earlier than the existing window's end and the existing window's start is earlier than the new window's end. Two windows that merely touch — where the new window's start equals an existing window's end — do not conflict. Only existing dispatches whose `status` is `ASSIGNED`, `EN_ROUTE`, or `ON_SITE` are considered when checking for conflicts; dispatches in `CANCELLED` or `CLEARED` are ignored. Datetime comparisons are made at microsecond resolution.

A dispatcher may reschedule an assigned or en-route dispatch by supplying a new `window_start` and `window_end`; the window is updated, the `eta` is reset to the new `window_start`, and the overlap check is re-run against the technician's other active dispatches. A dispatcher may also cancel a dispatch that is `ASSIGNED` or `EN_ROUTE`, moving it to `CANCELLED` and freeing the technician's occupied window for future overlap checks.

### 3.5. The Field Visit: En Route, On Site, and Completion

Once dispatched, the assigned technician drives the dispatch through its field lifecycle. Departing moves the dispatch from `ASSIGNED` to `EN_ROUTE`, and is permitted only while the dispatch is `ASSIGNED` and only for the technician who is actually assigned to it. Arriving moves the dispatch from `EN_ROUTE` to `ON_SITE`, again only for the assigned technician; arrival on site also bubbles the parent job into the work phase, moving a job in `SCHEDULED` (or in `WARRANTY`, for a re-dispatched warranty visit) to `IN_PROGRESS`. A dispatch in `ON_SITE` is later moved to `CLEARED` by the system when the parent job is completed.

During the on-site phase the technician records the parts consumed as `MaterialUsage` lines, each naming the `job_id`, the technician's own `technician_id`, the `sku_id` consumed, and a `quantity` greater than zero. Each line's `line_total_cents` is computed at the moment of recording as the `quantity` multiplied by that SKU's `unit_price_cents` at usage time, and the debit against truck stock described earlier is applied. A line carries a `voided` flag, false by default; voiding a line sets `voided` to true, restores the truck stock, and excludes the line from any future invoice.

When the work is done, the technician completes the job, supplying the realized `actual_labor_hours` for the visit. Completion is permitted only when the job is `IN_PROGRESS`. If the job's `requires_permit` flag is true, completion is blocked until a `Permit` for the job has reached `PASSED` status; attempting to complete a permitted job whose permit has not passed is rejected with `ERR_PERMIT_NOT_PASSED`. On a successful completion the active dispatch is moved to `CLEARED` and the job's `status` advances from `IN_PROGRESS` to `COMPLETED`.

### 3.6. Permits and Inspections

Jobs whose `scope` is `PANEL` or `EV_CHARGER` require a permit before they can be completed. A dispatcher files a `Permit` naming the `job_id`, the issuing `jurisdiction`, and the external `permit_number`; the permit opens in `APPLIED` status. The lifecycle then runs through several authorities. An inspector issues the permit, moving it from `APPLIED` to `ISSUED`. A dispatcher schedules the inspection by supplying the `inspection_at` time, which records that time on the permit and moves it from `ISSUED` to `INSPECTION_SCHEDULED`. An inspector then records the inspection by supplying a `result`: a `PASS` result moves the permit from `INSPECTION_SCHEDULED` to `PASSED`, which unblocks job completion, while a `FAIL` result moves it from `INSPECTION_SCHEDULED` to `FAILED`. A failed permit is not the end of the road — a dispatcher may schedule a re-inspection on a `FAILED` permit, which again records the new `inspection_at` and returns the permit to `INSPECTION_SCHEDULED`, from which it can be recorded again. Each of these transitions is permitted only from the state named as its source; an attempt from any other state is rejected with `ERR_INVALID_STATE`.

### 3.7. Billing the Job: The Invoice Calculation

Once a job is `COMPLETED`, a dispatcher invoices it. Invoicing is permitted exactly when the job is `COMPLETED`: a `COMPLETED` job is always invoiced, even if an `Invoice` from an earlier billing cycle already exists for it (a job that re-enters the work loop via a warranty callback and returns to `COMPLETED` is re-invoiced, producing a further `Invoice` — see §3.8). When the job is not `COMPLETED`, the single-invoice guard is applied: if an `Invoice` already exists for the job the request is rejected with `ERR_ALREADY_INVOICED`; otherwise (no invoice yet, and the job is not `COMPLETED`) the request is rejected with `ERR_INVALID_STATE`. Invoicing creates an `Invoice` for the job by running the billing calculation, then sets the job's `total_due_cents` to the invoice's grand total, stamps the job's `warranty_until` to the current server time plus the warranty window, and advances the job's `status` from `COMPLETED` to `INVOICED`. The warranty window is 30 days, so `warranty_until` is the invoice instant plus thirty days.

Unlike the forward-looking quote, the invoice is chronological and built from realized work — the non-voided material usages, the accepted estimate, the job's snapshotted membership, and the job's priority. Its component fields are computed in a pinned order, because later steps depend on earlier ones:

1. **Labor subtotal** (`labor_subtotal_cents`): if the accepted estimate's `pricing_mode` is `FLAT_RATE`, the labor subtotal equals the accepted estimate's `flat_rate_cents`. Otherwise, for `TIME_MATERIALS`, the labor subtotal is the `actual_labor_hours` supplied on completion multiplied by the technician's `hourly_rate_cents`, rounded half up to whole cents.
2. **Material subtotal** (`material_subtotal_cents`): the sum of `line_total_cents` across all of the job's `MaterialUsage` lines whose `voided` flag is false, accumulated in ascending `created_at` order for a deterministic running sum.
3. **Dispatch fee** (`dispatch_fee_cents`): the base trip fee is 8900 cents. If the job carries a non-null `membership_id` and that membership's plan has `waives_dispatch_fee` set true, the dispatch fee is 0; otherwise it is the full 8900 cents.
4. **Emergency surcharge** (`emergency_surcharge_cents`): 15000 cents when the job's `priority` is `EMERGENCY`, and 0 otherwise.
5. **Discount** (`discount_cents`): if the job carries a non-null `membership_id`, the discount is the `labor_subtotal_cents` multiplied by that plan's `labor_discount_pct`, rounded half up to whole cents; if the job has no membership, the discount is 0.
6. **Tax** (`tax_cents`): the taxable material base — the sum of `line_total_cents` over the non-voided usages whose SKU has `taxable` set true — multiplied by the tax rate of 0.0825, rounded half up to whole cents.
7. **Grand total** (`total_cents`): the labor subtotal minus the discount, plus the material subtotal, plus the dispatch fee, plus the emergency surcharge, plus the tax.

Each rounding step above is applied independently where it occurs — the system rounds then sums, and never sums exact values and rounds once at the end. A member-billed job (one with a non-null `membership_id`) differs from a non-member job in exactly two ways: the labor discount is subtracted, and the dispatch fee may be waived per the plan's flags; a non-member job receives no discount and always pays the full dispatch fee.

### 3.8. Closing Out, Warranty, and the Callback Loop

After a job is `INVOICED`, a dispatcher closes it, advancing the `status` from `INVOICED` to `CLOSED`. Closing is blocked while any `Callback` for the job is still `OPEN`; an attempt to close a job with an open callback is rejected with `ERR_OPEN_CALLBACK`.

A `Callback` is the warranty mechanism. A customer (or a dispatcher on their behalf) files a callback against an invoiced or closed job, supplying the `job_id` and a free-text `reason` describing the reported defect. On filing, the system computes `covered_by_warranty` as true when the callback is created at or before the job's `warranty_until`, and false otherwise. A callback that is covered opens in `OPEN` status and reopens the job: a job in `INVOICED` or `CLOSED` is moved to `WARRANTY`, re-entering the work cycle. A callback filed after the warranty window has elapsed cannot reopen the job and is rejected with `ERR_NOT_WARRANTY_COVERED`.

A job in `WARRANTY` is serviced exactly like a fresh visit. A technician is re-dispatched, and when that dispatch arrives on site the job moves from `WARRANTY` back into `IN_PROGRESS`, from which it again proceeds to `COMPLETED` and can be re-invoiced — the warranty work re-enters the same work-and-bill loop. An open callback is resolved by a dispatcher once the warranty work is finished: resolution is permitted only when the callback is `OPEN` and the parent job has returned to `COMPLETED` or `INVOICED`, and it moves the callback from `OPEN` to `RESOLVED`. Only after the callback is resolved (so that no callback remains `OPEN`) can the job be closed.

### 3.9. Cancelling a Job

A customer or dispatcher may cancel a job at several points in its life, and the cascade depends on where the job stands. Cancelling a job that is `DRAFT` or `QUOTED` moves it to `CANCELLED` and supersedes any of its estimates still in `SENT` or `DRAFT`. Cancelling a job that is `SCHEDULED` moves it to `CANCELLED`, supersedes its open estimates as above, and also cancels the active dispatch — moving that dispatch to `CANCELLED` and thereby freeing the technician's time window for other bookings. A cancellation requested against a job in any other state is rejected with `ERR_INVALID_STATE`. `CANCELLED` and `CLOSED` are the two terminal resting states of a job.

### 3.10. The Dispatch Queue: Ranking the Next Job

To help a dispatcher decide what to route next, the system exposes a ranked recommendation queue scoped to a `zone`. The candidate set is every `ServiceJob` currently in `QUOTED` status whose zone (the customer's `service_zip` prefix) matches the requested `zone`, with panel and EV-charger jobs included on the understanding that a `MASTER` technician will be assigned. Candidates are ranked by three keys applied in strict order: first, `EMERGENCY`-priority jobs rank ahead of `STANDARD` jobs; second, among jobs of equal priority, jobs belonging to a member whose plan has `priority_dispatch` set true rank ahead of jobs that do not; and third, remaining ties are broken by `created_at` ascending so that the older job comes first. The `created_at` ordering is the final deterministic tie-break; a resource `id` is never used to break ties.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Endpoints that create a new resource return HTTP 201 with the created resource in `data`; endpoints that read or that modify an existing resource (including all state-transition actions) return HTTP 200. Error responses use the status codes catalogued in §5. The request and response bodies for each endpoint are governed by the workflow narratives in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/v1/customers` | Create a customer | Dispatcher |
| GET | `/v1/customers/{customerId}` | Get a customer | Dispatcher, Customer |
| GET | `/v1/customers` | List customers (filterable) | Dispatcher |
| POST | `/v1/technicians` | Create a technician | Dispatcher |
| GET | `/v1/technicians/{technicianId}` | Get a technician | Dispatcher, Technician |
| GET | `/v1/technicians` | List technicians (filter by zone) | Dispatcher |
| POST | `/v1/membership-plans` | Create a membership plan | Dispatcher |
| GET | `/v1/membership-plans/{planId}` | Get a membership plan | Dispatcher, Customer |
| GET | `/v1/membership-plans` | List membership plans | Dispatcher, Customer |
| POST | `/v1/memberships` | Enroll a customer in a plan | Dispatcher, Customer |
| GET | `/v1/memberships/{membershipId}` | Get a membership | Dispatcher, Customer |
| GET | `/v1/memberships` | List memberships (filter by customer or plan) | Dispatcher, Customer |
| POST | `/v1/memberships/{membershipId}/cancel` | Cancel a membership | Dispatcher, Customer |
| POST | `/v1/material-skus` | Create a price-book SKU | Dispatcher |
| GET | `/v1/material-skus/{skuId}` | Get a SKU | Dispatcher, Technician |
| GET | `/v1/material-skus` | List SKUs | Dispatcher, Technician |
| POST | `/v1/truck-stock-items` | Stock a SKU on a technician's truck | Dispatcher |
| GET | `/v1/truck-stock-items/{stockItemId}` | Get a truck-stock item | Dispatcher, Technician |
| GET | `/v1/truck-stock-items` | List truck-stock items (filter by technician or sku) | Dispatcher, Technician |
| POST | `/v1/truck-stock-items/{stockItemId}/restock` | Add units to a truck-stock item | Dispatcher |
| POST | `/v1/service-jobs` | Create a service job (DRAFT) | Dispatcher, Customer |
| GET | `/v1/service-jobs/{jobId}` | Get a service job | Dispatcher, Customer, Technician |
| GET | `/v1/service-jobs` | List service jobs (filter by customer, membership, or status) | Dispatcher, Customer, Technician |
| POST | `/v1/service-jobs/{jobId}/complete` | Mark job work complete | Technician |
| POST | `/v1/service-jobs/{jobId}/invoice` | Generate the invoice and bill the job | Dispatcher |
| POST | `/v1/service-jobs/{jobId}/close` | Close an invoiced job | Dispatcher |
| POST | `/v1/service-jobs/{jobId}/cancel` | Cancel a job | Dispatcher, Customer |
| POST | `/v1/estimates` | Create an estimate for a job | Dispatcher |
| GET | `/v1/estimates/{estimateId}` | Get an estimate | Dispatcher, Customer |
| GET | `/v1/estimates` | List estimates (filter by job) | Dispatcher, Customer |
| POST | `/v1/estimates/{estimateId}/send` | Send a draft estimate to the customer | Dispatcher |
| POST | `/v1/estimates/{estimateId}/accept` | Customer accepts an estimate | Customer |
| POST | `/v1/estimates/{estimateId}/reject` | Customer rejects an estimate | Customer |
| POST | `/v1/dispatches` | Dispatch a technician to a job | Dispatcher |
| GET | `/v1/dispatches/{dispatchId}` | Get a dispatch | Dispatcher, Technician, Customer |
| GET | `/v1/dispatches` | List dispatches (filter by job or technician) | Dispatcher, Technician |
| POST | `/v1/dispatches/{dispatchId}/depart` | Technician departs for the job | Technician |
| POST | `/v1/dispatches/{dispatchId}/arrive` | Technician arrives on site | Technician |
| POST | `/v1/dispatches/{dispatchId}/reschedule` | Reschedule a dispatch window | Dispatcher |
| POST | `/v1/dispatches/{dispatchId}/cancel` | Cancel a dispatch | Dispatcher |
| POST | `/v1/permits` | File a permit for a job | Dispatcher |
| GET | `/v1/permits/{permitId}` | Get a permit | Dispatcher, Inspector |
| GET | `/v1/permits` | List permits (filter by job) | Dispatcher, Inspector |
| POST | `/v1/permits/{permitId}/issue` | Authority issues the permit | Inspector |
| POST | `/v1/permits/{permitId}/schedule-inspection` | Schedule (or re-schedule) the inspection | Dispatcher |
| POST | `/v1/permits/{permitId}/record-inspection` | Inspector records the inspection result | Inspector |
| POST | `/v1/material-usages` | Record material consumed on a job (debits truck stock) | Technician |
| GET | `/v1/material-usages/{usageId}` | Get a material usage | Dispatcher, Technician |
| GET | `/v1/material-usages` | List material usages (filter by job, technician, or sku) | Dispatcher, Technician |
| POST | `/v1/material-usages/{usageId}/void` | Void a material usage (restores truck stock) | Dispatcher, Technician |
| GET | `/v1/invoices/{invoiceId}` | Get an invoice | Dispatcher, Customer |
| GET | `/v1/invoices` | List invoices (filter by job) | Dispatcher, Customer |
| POST | `/v1/callbacks` | File a warranty callback against an invoiced/closed job | Customer, Dispatcher |
| GET | `/v1/callbacks/{callbackId}` | Get a callback | Dispatcher, Customer |
| GET | `/v1/callbacks` | List callbacks (filter by job) | Dispatcher, Customer |
| POST | `/v1/callbacks/{callbackId}/resolve` | Resolve a callback | Dispatcher |
| GET | `/v1/dispatch-queue` | Ranked next-job recommendations for a zone | Dispatcher |
| POST | `/v1/_clock/set` | Set the server's current UTC clock (test-driving) | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LICENSE_INSUFFICIENT` | 409 |
| `ERR_TECH_NOT_ON_CALL` | 409 |
| `ERR_ZONE_MISMATCH` | 409 |
| `ERR_TECH_DOUBLE_BOOKED` | 409 |
| `ERR_PERMIT_NOT_PASSED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_ALREADY_INVOICED` | 409 |
| `ERR_OPEN_CALLBACK` | 409 |
| `ERR_NOT_WARRANTY_COVERED` | 409 |
| `ERR_DUPLICATE` | 409 |
