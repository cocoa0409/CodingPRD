# Handyman & Appliance Repair Marketplace API — Product Requirements Document

## 1. Introduction

The Handyman & Appliance Repair Marketplace connects homeowners who need a repair done with vetted, background-checked professionals who can do it. The platform's defining tension is that the *same* job can be priced two completely different ways: a customer in a hurry can take a sight-unseen **instant quote** — a single all-in flat number the system computes the moment the request is filed — or they can ask a professional to come out, inspect the appliance, and return an itemized **in-home estimate** built from projected labor and a travel charge. Both paths converge once a window is booked, the work is performed, parts are stocked from the truck or special-ordered, an invoice is issued and paid, and — should the repair not hold — a warranty callback re-opens the job at no charge.

This document specifies the REST API that drives that marketplace end to end. It covers the catalog of service categories and their skill-tag requirements, the vetting of professionals through background and license checks, the scheduling of dispatch windows under travel-buffer and double-booking constraints, the dual-variant pricing engine, the labor-and-parts invoice with its markup and trip-fee rules, the warranty-callback cycle, and the dispute-and-refund machinery that can cascade backward through an invoice, a customer's wallet, and a professional's callback rating. The API is the single source of truth for every actor — customers, professionals, dispatchers, and platform administrators — and all monetary amounts are carried in integer cents to keep the arithmetic exact.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request that is not an open self-registration must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. The platform recognizes exactly five roles: `Customer`, `Pro`, `PlatformAdmin`, `Dispatcher`, and `Anonymous`. If either header is missing, or `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`. The three self-registration endpoints — creating a customer, creating a professional, and creating a service category — are exceptions discussed in §2.1's note below and in the relevant workflows.

The five roles bind to identity as follows:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`. A customer owns the `Job` rows whose `customer_id` is theirs, and by extension the disputes filed against those jobs.
- When `X-User-Role` is `Pro`, `X-User-ID` is the `id` of the acting `Pro`. Ownership checks on any resource that references a `Pro` compare the resource's professional foreign key to `X-User-ID`. A professional owns the `DispatchWindow` rows whose `pro_id` is theirs and the `Invoice` rows attached to jobs assigned to them.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`; administrators are not ownership-scoped.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The dispatcher is a read-only operational role and is never compared to any entity's `id`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque placeholder not tied to any persisted entity; the anonymous role exists only so that prospective customers and professionals can register themselves before they have an identity.

Customer registration, professional registration, and service-category creation do not require authentication headers; every other endpoint does. Beyond the header-presence and role-permission checks, resources that are owned by an entity-backed role are additionally guarded: when a `Customer` or `Pro` acts on a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` even though their role would in principle be allowed to perform the operation.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; when two resources share an identical `created_at`, the tie is broken by their server-side creation order (earlier-created first).

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Cent Convention

Most resources in this system carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; refreshed on every mutation.
- `version` — a system-managed integer that begins at its initial value and increments by one with every modification to the resource.

`ServiceCategory` is the one exception: it is configuration data that, once created, is treated as immutable. A `ServiceCategory` therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field. Every other entity — `Customer`, `Pro`, `Job`, `Quote`, `DispatchWindow`, `LaborLine`, `PartLine`, `WorkVisit`, `Invoice`, `Dispute`, and `BackgroundCheck` — carries the full quartet of common fields.

Every monetary value in the system is an integer number of cents. There are no fractional cents and no floating-point dollars anywhere in a request or response body. The single non-monetary numeric fields are `truck_stock_markup_pct` (a fraction such as 0.35 meaning 35%), `estimated_labor_hours`, `hours_worked`, and `callback_rate`; these are discussed where they are used.

### 2.5. Precision and Rounding

Wherever a computation produces a non-integer number of cents — most notably multiplying labor hours by an hourly rate, or applying a percentage markup to a part's base cost — the result is rounded to a whole number of cents using the **round-half-up** method (a value exactly halfway between two integers rounds up to the larger). The professional callback rate is the only ratio retained as a fraction; it is rounded half-up to exactly four decimal places. No other rounding mode is ever used.

### 2.6. Hierarchical Consistency and Cascading Side Effects

Many operations in this marketplace touch more than one entity at once, and every such cascade is mandatory rather than best-effort. Booking a window does not merely flip the window's occupancy; it also stamps the assigned professional onto the job, advances the job's lifecycle, and bumps the window's `version`. Completing a job resolves the open visit, releases the window, and recomputes the professional's callback statistics. Approving a refund can ripple backward through the invoice, the customer's wallet, the professional's callback counters, and — for incomplete-work disputes — an outstanding callback job. Each affected entity independently has its `updated_at` refreshed and its `version` incremented when it is mutated as part of a cascade, exactly as if it had been the direct target of a request. The specific cascades are spelled out in §3; this subsection establishes that they are atomic and exhaustive.

### 2.7. Nested Resource Retrieval and Left-to-Right Validation

Several endpoints address a resource through a path that names a parent first — for example, the visits, labor lines, part lines, quotes, and invoices that hang off a particular job, or the background checks and dispatch windows that hang off a particular professional. For any such path, the server validates the identifiers left to right. If the parent identifier in the path does not resolve to an existing resource, the request fails with `ERR_NOT_FOUND` for that parent before any child or body reference is examined. Only once the path is fully resolved does the server validate foreign keys carried in the body, again in declaration order, surfacing `ERR_NOT_FOUND` for the first one that does not resolve.

### 2.8. Optimistic Concurrency Control on Window Booking

Booking a job into a dispatch window is the one operation in the system guarded by optimistic concurrency control. A booking request must carry `expected_dispatchwindow_version`, the `version` of the target `DispatchWindow` as the client last observed it; this field is mandatory on that request and appears on no other. If `expected_dispatchwindow_version` does not equal the window's current `version`, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). This is precisely the situation in which another writer has already booked the same window — legitimately moving it from `FREE` to `BOOKED`, which advances its `version` — so the current client's view is stale even though, under naive product semantics, a free-looking window would have accepted the booking. The version check thus prevents a client from overwriting a booking it never observed. Within the booking endpoint the version check is evaluated last, after the state preconditions (job bookable, window `FREE`, accepted quote present and not superseded) and after every domain guard of §3.4 — assignability, ZIP match, travel buffer, and the customer double-booking check — so that all of those errors take precedence over `ERR_STALE_VERSION` when more than one applies. No other endpoint accepts or requires a version field.

### 2.9. Validation Ordering

When several validation conditions guard a single endpoint, they are evaluated in a fixed priority order, and the first one to fail determines the error returned. The global order is: (1) request-body well-formedness, surfacing `ERR_INVALID_REQUEST`; (2) authentication header presence and role recognition, surfacing `ERR_UNAUTHENTICATED`; (3) role permission for the endpoint, surfacing `ERR_UNAUTHORIZED`; (4) existence of every referenced resource, path identifiers before body foreign keys, surfacing `ERR_NOT_FOUND`; (5) semantic body coherence on the create endpoints that have it, surfacing `ERR_VALIDATION`; (6) resource ownership for entity-backed roles, surfacing `ERR_NOT_RESOURCE_OWNER`; (7) state legality for the requested transition, surfacing `ERR_INVALID_STATE`; and then (8) onward, the domain-specific business rules described throughout §3, in the order presented there. The practical consequence is that a malformed body is reported before an auth problem, an auth problem before a missing resource, a missing resource before a state-machine conflict, and a state-machine conflict before any of the safety, scheduling, or fiscal checks. Where §3 enumerates several business checks on one endpoint, the order given there is the order enforced.

## 3. Business Logic & Workflows

### 3.1. The Service Catalog and Skill Tags

Everything begins with the catalog. A `PlatformAdmin` defines each **service category** by supplying a `code` (a stable, unique identifier matching an uppercase letter followed by one to thirty-one further uppercase letters, digits, or underscores — a malformed `code` is rejected with `ERR_INVALID_REQUEST`, and no two categories may share a `code`, a collision being rejected with `ERR_VALIDATION`), a human-readable `name`, and a `pricing_model` that is either `HOURLY` or `FLAT`. The category also declares whether it `requires_license`, defaulting to false; a list of `skill_tags` a professional must carry to serve it, defaulting to an empty list; and a `callback_warranty_days` window, defaulting to 30, that fixes for how many days after completion a customer may open a free callback.

The pricing fields must be coherent with the chosen `pricing_model`, and incoherence is rejected with `ERR_VALIDATION`. A `FLAT` category must carry a non-negative `flat_task_fee_cents` and must leave `hourly_rate_cents` null; an `HOURLY` category must carry a non-negative `hourly_rate_cents` and must leave `flat_task_fee_cents` null. Independently, a category may be flagged `instant_quote_eligible` (defaulting to false). When it is eligible it must carry a non-negative `instant_quote_flat_cents` — the all-in sight-unseen price; when it is not eligible, `instant_quote_flat_cents` must be null. Each category carries `requires_license`, `skill_tags`, and `callback_warranty_days` as described, and all of these defaults apply when the field is omitted from the creation payload.

### 3.2. Customers, Professionals, and Vetting

Anyone may register. A **customer** self-registers with a unique `email`, a `full_name`, and a five-digit `zip_code` (exactly five digits) used later for travel-buffer eligibility; their `wallet_credit_cents` starts at zero and only ever grows through dispute refunds routed to the wallet. A **professional** self-registers with a unique `email`, a `full_name`, a five-digit `home_zip_code` (exactly five digits — jobs in that same ZIP incur no travel buffer), an optional list of `skill_tags` they carry, and an optional `truck_stock_markup_pct`. For both registrations a duplicate `email` is rejected with `ERR_VALIDATION`, while a `zip_code`/`home_zip_code` that is not exactly five digits is rejected with `ERR_INVALID_REQUEST`. That markup fraction defaults to 0.25 and must lie between 0 and 1 inclusive; it is the percentage the professional adds to truck-stock parts. On registration a professional's `background_check_status` is `PENDING` and their `license_status` is `NONE`, with `license_expires_on` null; their `completed_job_count`, `callback_job_count`, and `callback_rate` all start at zero.

A professional cannot be assigned to any job until they are vetted, and vetting is administered by a `PlatformAdmin` who submits **background checks** against the professional. Each check declares a `check_type` of `CRIMINAL`, `IDENTITY`, or `LICENSE`; a `LICENSE` check additionally carries a `license_expires_on` date (a UTC-midnight date), which is null for the other two types. A submitted check is created with a `decision` of `PENDING`. The administrator later records the outcome by deciding the check, supplying a `decision` of `PASS` or `FAIL`.

Recording a decision recomputes the professional's posture. A professional moves from `PENDING` to `CLEARED` exactly when they have at least one background check whose `check_type` is `CRIMINAL` or `IDENTITY` and every such check has a `decision` of `PASS` (a professional with no `CRIMINAL`/`IDENTITY` checks at all remains `PENDING`, even after a `LICENSE` check passes). A professional moves to `FLAGGED` — whether they were `PENDING` or already `CLEARED` — as soon as any check of `check_type` `CRIMINAL` or `IDENTITY` records a `decision` of `FAIL`. The `CLEARED → FLAGGED` transition is not merely a status change: it cancels every one of that professional's `SCHEDULED` jobs (moving each to `CANCELLED`) and releases the dispatch windows those jobs had booked. License posture evolves on a parallel axis: a `LICENSE` check that passes copies its `license_expires_on` onto the professional and sets `license_status` to `VERIFIED` only when that expiry date is strictly after the decision instant — an expiry that is in the past, falls exactly at the decision instant, or is null instead sets `license_status` to `EXPIRED`. (A `LICENSE` check that records a `FAIL` recomputes only the background posture and leaves `license_status` and `license_expires_on` untouched.) Deciding a check may optionally carry `expected_pro_version` for callers who wish to guard against a stale professional record.

### 3.3. Filing a Job and the Two Quoting Paths

A `Customer` files a **job** by naming the `customer_id` placing the request, the `category_id` of the service wanted, and the five-digit `address_zip_code` where the work will happen. A fresh job is born in `REQUESTED` status with `quote_path`, `pro_id`, `agreed_price_cents`, and `parent_job_id` all unset, and `is_warranty_callback` false. From `REQUESTED` the job forks.

**The instant path.** If the category is `instant_quote_eligible` and the job is not a warranty callback, the customer may take the instant quote, advancing the job `REQUESTED → INSTANT_QUOTED`. This produces a `Quote` whose `quote_type` is `INSTANT` and whose `priced_amount_cents` is simply the category's `instant_quote_flat_cents` — a single sight-unseen flat number with no parts, no per-hour labor, and no trip fee folded in — and it sets the job's `quote_path` to `INSTANT`. Requesting an instant quote on a category that is not instant-eligible, or on a warranty-callback job, is rejected with `ERR_INSTANT_QUOTE_INELIGIBLE`.

**The estimate path.** Alternatively the customer requests an in-home estimate, advancing the job `REQUESTED → ESTIMATE_REQUESTED` and setting `quote_path` to `IN_HOME`. A `Pro` then comes out and submits the estimate, advancing the job `ESTIMATE_REQUESTED → ESTIMATED`. The submission may carry `estimated_labor_hours` (required for an `HOURLY` category, null for a `FLAT` one) and produces a `Quote` whose `quote_type` is `IN_HOME`. Its `priced_amount_cents` is an itemized projection: for a `FLAT` category the labor component is the category's `flat_task_fee_cents`; for an `HOURLY` category the labor component is `estimated_labor_hours` multiplied by the category's `hourly_rate_cents`, rounded half-up to whole cents. To that labor component the system adds the trip fee computed for this job and this professional (described in §3.7), and the sum is the quoted total. The trip fee folded into the quote is always the geographic base fee (2,500 cents when the job ZIP equals the professional's `home_zip_code`, otherwise 6,000 cents); the §3.7 waivers for warranty callbacks and large subtotals are applied only when the invoice is issued, never to the quote. Parts are unknown at estimate time and are deliberately excluded from the in-home quote; they appear only later on the invoice. Submitting an estimate is permitted only while the job is in `ESTIMATE_REQUESTED`; once the first estimate has advanced the job to `ESTIMATED`, a further `POST /jobs/{id}/quotes` is rejected with `ERR_INVALID_STATE`. If a prior, not-yet-accepted quote already exists on the job, submitting a new estimate marks that earlier quote `superseded` true. The submitting professional must be assignable to the category — that is, background-cleared, appropriately licensed, and carrying the required skill tags — exactly as described in §3.5; a `Quote` carries `job_id`, `quote_type`, `estimated_labor_hours`, `priced_amount_cents`, `accepted`, and `superseded`, where `accepted` and `superseded` both start false.

**Accepting.** The customer accepts a quote by naming its `quote_id`. Acceptance sets the chosen quote's `accepted` to true and pins the job's `agreed_price_cents` to that quote's `priced_amount_cents`. Acceptance alone does not schedule the job; the job remains `INSTANT_QUOTED` or `ESTIMATED` until a window is booked. An accepted quote must not be superseded for the subsequent booking to proceed.

### 3.4. Dispatch Windows and Booking

A `Pro` advertises availability by publishing a **dispatch window** with their `pro_id`, an inclusive `window_start`, an exclusive `window_end`, and the five-digit `service_zip_code` the window serves. The end must be strictly after the start; a window whose `window_end` is not after its `window_start` is rejected with `ERR_VALIDATION`. A window is created free — its `hold_state` is `FREE`, its `booked_job_id` null. A professional may not publish a window that overlaps any of their own existing windows that are not `RELEASED`; overlap is judged on half-open intervals, so two windows that merely touch at a boundary do not overlap, but any true overlap is rejected with `ERR_WINDOW_OVERLAP`.

Booking is where the accepted quote becomes a scheduled appointment, advancing the job from `INSTANT_QUOTED → SCHEDULED` or from `ESTIMATED → SCHEDULED`. The booking request names the `job_id` to place into the window and carries `expected_dispatchwindow_version` as described in §2.8. For a booking to succeed, the job must already carry a quote that was accepted via `POST /jobs/{id}/accept-quote` — a job with no accepted quote is rejected with `ERR_INVALID_STATE` — and that accepted quote must not be `superseded` (a superseded accepted quote is likewise rejected with `ERR_INVALID_STATE`); the target window's `hold_state` must be `FREE`; the window's owning professional must be assignable to the job's category; and the window's `service_zip_code` must equal the job's `address_zip_code` (a mismatch is rejected with `ERR_ZIP_MISMATCH`). On success the system sets the quote's `accepted` to true, sets the job's `agreed_price_cents` to the quote's `priced_amount_cents`, sets the job's `pro_id` to the window's `pro_id`, flips the window's `hold_state` to `BOOKED`, records the window's `booked_job_id` as the job's id, and increments the window's `version` by one.

Two scheduling guards apply at booking time and both concern overlap in the calendar. First, the **travel buffer**: the window being booked must leave a gap of at least sixty minutes before and after any other already-`BOOKED` window of the same professional whenever the two windows serve *different* ZIP codes; two back-to-back windows of the same professional that serve the *same* ZIP need no buffer. A violation is rejected with `ERR_TRAVEL_BUFFER_CONFLICT`. Second, the **customer double-booking** guard: the booking customer must not already hold another `SCHEDULED` job whose booked window's interval touches or overlaps the interval of the window now being booked. This second check treats the intervals as closed, so even adjacent, back-to-back windows are rejected — a customer cannot be at two sites at once — with `ERR_CUSTOMER_DOUBLE_BOOKED`.

### 3.5. Assignability: Background, License, and Skill Tags

Whether a professional may serve a job is decided by three gates, and they apply both when a professional submits an in-home estimate and when a window owned by that professional is booked. The first gate is the **background gate**: the acting or owning professional's `background_check_status` must be `CLEARED`; otherwise the operation is rejected with `ERR_PRO_NOT_CLEARED`. The second gate is the **license gate**: only when the job's category `requires_license`, the professional's `license_status` must be `VERIFIED` and their `license_expires_on` must be in the future; a missing, unverified, or expired license is rejected with `ERR_LICENSE_REQUIRED`. The third gate is the **skill gate**: the professional's `skill_tags` must be a superset of the category's `skill_tags`, meaning the professional carries every tag the category demands; a shortfall is rejected with `ERR_SKILL_TAG_MISMATCH`. On the estimate-submission and window-booking endpoints these three checks are evaluated background-first, then license, then skill tags.

### 3.6. Performing the Work: Visits, Labor, and Parts

Once a job is `SCHEDULED`, the assigned `Pro` logs arrival to begin the work, advancing the job `SCHEDULED → IN_PROGRESS` and opening a **work visit**. The visit names the `dispatch_window_id` it consumes and the `arrived_at` timestamp; it is created with `outcome` `OPEN`. The acting professional must be the job's assigned professional, the referenced window must be the very one booked for this job (it is `BOOKED` with its `booked_job_id` equal to the job — a referenced window that is not this job's booked window is rejected with `ERR_INVALID_STATE`), and `arrived_at` must fall within the booked window's half-open interval from `window_start` inclusive to `window_end` exclusive; an arrival outside that interval is rejected with `ERR_VISIT_OUTSIDE_WINDOW`.

While the job is in progress, the professional records the materials and effort. **Part lines** are recorded one at a time, each with a `description`, a non-negative `unit_cost_cents` (the professional's wholesale cost), a `quantity` of at least one, and a `from_truck_stock` flag defaulting to false. The line's `line_total_cents` is computed at creation as follows. The base is `unit_cost_cents` multiplied by `quantity`. If the part came `from_truck_stock`, the system computes a markup equal to the base multiplied by the professional's `truck_stock_markup_pct`, rounded half-up to whole cents; that markup is then capped so it never exceeds 5,000 cents, and floored so it is never less than 300 cents; the line total is the base plus this capped-and-floored markup (the cap is applied first, then the floor raises any too-small markup back up to the 300-cent minimum). If the part did not come from truck stock — a special order — there is no percentage markup at all; instead a flat handling fee of 1,500 cents is added to the base to form the line total. **Labor lines** apply only to `HOURLY` categories: each names the `hours_worked`, and at creation the system snapshots the category's hourly rate into `rate_cents_per_hour` and computes `line_total_cents` as `hours_worked` multiplied by `rate_cents_per_hour`, rounded half-up to whole cents. Recording labor hours on a `FLAT` category, or failing to record any labor hours before issuing an `HOURLY` invoice, is a pricing-model violation rejected with `ERR_PRICING_MODEL_MISMATCH`.

### 3.7. Invoicing, Trip Fees, and Payment

When the work is done, the `Pro` creates a draft **invoice** for the in-progress job; it is born in `DRAFT` status with `labor_subtotal_cents`, `parts_subtotal_cents`, `trip_fee_cents`, and `total_cents` not yet computed, `amount_paid_cents` and `refunded_cents` zero. The professional then issues the invoice, advancing it `DRAFT → ISSUED`, which requires that the job still be `IN_PROGRESS` and that the acting professional be the job's professional. Issuing recomputes the money in a pinned order: first the labor subtotal, then the parts subtotal, then the trip fee, then the grand total — the trip fee must be computed after the two subtotals because the waiver test depends on them.

The labor subtotal is the category's `flat_task_fee_cents` for a `FLAT` category; for an `HOURLY` category it is the sum over the job's labor lines, where each line is rounded half-up to whole cents *before* the lines are summed (per-line rounding, then aggregation). The parts subtotal is the sum of every part line's `line_total_cents`. The trip fee starts from a base that depends on geography: if the job's `address_zip_code` equals the professional's `home_zip_code` the base trip fee is 2,500 cents, otherwise it is 6,000 cents. That base is then waived to zero in either of two situations: the job is a warranty callback, or the sum of the labor subtotal and the parts subtotal is at least 40,000 cents. The grand `total_cents` is the labor subtotal plus the parts subtotal plus the (possibly waived) trip fee. Issuing also sets `balance_due_cents` equal to `total_cents`, with `amount_paid_cents` and `refunded_cents` still zero.

The `balance_due_cents` is a derived figure kept continually reconciled as `total_cents` minus `amount_paid_cents` plus `refunded_cents` — refunds add back to what is owed. A `Customer` pays the issued invoice, advancing it `ISSUED → PAID`. Payment must be exact: the supplied `amount_cents` must equal the invoice's current `balance_due_cents`, because only full payment is accepted; any other amount is rejected with `ERR_PARTIAL_PAYMENT`. On payment the system adds `amount_cents` to `amount_paid_cents` and recomputes `balance_due_cents`. The invoice's `job_id` ties it to its job, and its `status` runs through `DRAFT`, `ISSUED`, `PAID`, and the terminal `REFUNDED` and `VOID`.

### 3.8. Completion and the Warranty Callback Cycle

A `Pro` marks an in-progress job complete, advancing it `IN_PROGRESS → COMPLETED`, but only once an invoice for the job exists in `ISSUED` status and the acting professional is the job's professional. Completion resolves the open work visit (its `outcome` becomes `RESOLVED`), releases the booked window by setting its `hold_state` to `RELEASED` while leaving its `booked_job_id` still pointing at the job (unlike a cancellation, completion does not clear `booked_job_id`), and updates the professional's reputation counters: a non-callback completion increments the professional's `completed_job_count` by one, while a warranty-callback completion does not touch `completed_job_count`. In both cases the professional's `callback_rate` is recomputed afterward. The callback rate is zero whenever `completed_job_count` is zero; otherwise it is `callback_job_count` divided by `completed_job_count`, rounded half-up to four decimal places.

Within the warranty window, a `Customer` may open a **callback** against a completed job, advancing the original job `COMPLETED → CALLBACK_OPEN`. A callback may be opened only while the current moment is strictly before the original job's completion instant plus the category's `callback_warranty_days`; past that point the request is rejected with `ERR_WARRANTY_EXPIRED`. A callback may not be opened against a job that is itself a warranty callback — one cannot callback a callback. Opening a callback spawns a brand-new job: this callback job carries `parent_job_id` pointing at the original, has `is_warranty_callback` true, is born already `SCHEDULED`, and reuses the original professional as its `pro_id` — it skips quoting entirely. Opening a callback also increments the professional's `callback_job_count` by one and recomputes their `callback_rate`. Because the denominator (`completed_job_count`) grows on base completions while the numerator (`callback_job_count`) grows on callbacks, the rate falls or holds as honest work accumulates and rises when callbacks pile up.

### 3.9. Cancellation

A `Customer` may cancel a job from several points in its life — specifically from `REQUESTED`, `INSTANT_QUOTED`, `ESTIMATE_REQUESTED`, `ESTIMATED`, `SCHEDULED`, or `IN_PROGRESS` — always landing in the terminal `CANCELLED` state; cancelling from any other state (including the terminal `CANCELLED`, `COMPLETED`, and `CALLBACK_OPEN`) is rejected with `ERR_INVALID_STATE`. Cancelling a `REQUESTED`, `INSTANT_QUOTED`, `ESTIMATE_REQUESTED`, or `ESTIMATED` job has no side effects — nothing has been committed yet. Cancelling a `SCHEDULED` job releases the booked window (its `hold_state` becomes `RELEASED` and its `booked_job_id` is cleared) and clears the job's `pro_id`. Cancelling an `IN_PROGRESS` job is permitted only when no invoice for that job is in `PAID` status; it releases the booked window and voids any still-`DRAFT` or still-`ISSUED` invoice on the job by moving it to `VOID`. An invoice moves to `VOID` from `DRAFT` unconditionally when its job is cancelled, and from `ISSUED` to `VOID` only while its `amount_paid_cents` is zero — a paid invoice is never voided. A request to cancel from a state with no defined cancel transition is rejected with `ERR_INVALID_STATE`.

### 3.10. Disputes, Refunds, and the Backward Cascade

After an invoice has been paid (or already partially refunded), a `Customer` may file a **dispute** against it. Filing itself does not re-check the invoice's `status` — a dispute may be filed referencing an invoice in any status, and the `PAID`-or-`REFUNDED` requirement is instead enforced only when an administrator moves the dispute into review (below). The dispute names the `job_id` and the `invoice_id` in question, a `reason` that is one of `WORK_INCOMPLETE`, `OVERCHARGED`, `DAMAGE`, or `NO_SHOW`, a `requested_refund_cents` of at least one cent, and an optional `refund_destination` of either `ORIGINAL` or `WALLET` (defaulting to `ORIGINAL`). A requested refund below one cent is rejected with `ERR_VALIDATION` at filing time. A dispute is born `OPEN` with `approved_refund_cents` unset.

A `PlatformAdmin` advances a dispute into review (`OPEN → UNDER_REVIEW`), permitted only while the referenced invoice's `status` is `PAID` or `REFUNDED`. The filing customer may withdraw their own dispute at any point while it is `OPEN` or `UNDER_REVIEW`, moving it to the terminal `WITHDRAWN`. From `UNDER_REVIEW` the administrator resolves the dispute by supplying a `decision`. A `decision` of `DENY` moves the dispute to `DENIED` and records `approved_refund_cents` as zero. A `decision` of `APPROVE` requires an `approved_refund_cents` that is strictly greater than zero and no greater than the invoice's `amount_paid_cents` minus its already-`refunded_cents`; a value outside that range is rejected with `ERR_REFUND_EXCEEDS_PAID`.

An approval moves the dispute to `APPROVED` and fires a cascade. The approved amount is recorded on the dispute; the invoice's `refunded_cents` is increased by that amount and its `balance_due_cents` recomputed. If the cumulative refund now equals the invoice's `amount_paid_cents` — a full refund — the invoice transitions `PAID → REFUNDED`; a partial refund leaves the invoice `PAID`. If the dispute's `refund_destination` is `WALLET`, the approved amount is added to the customer's `wallet_credit_cents`. Finally, if the dispute's `reason` is `WORK_INCOMPLETE` and an open warranty callback exists for the job, that callback job is auto-cancelled, the professional's `callback_job_count` is decremented by one, and their `callback_rate` is recomputed. Each entity the cascade touches has its `updated_at` and `version` advanced as in §2.6.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify or transition an existing resource, or that list or fetch resources, return `200 OK`. Every request body and the side effects of each operation are described in §3; the table below is a routing summary only. One administrative test-only capability — setting the server's current UTC clock by supplying a `to_iso8601` instant — pins the logical "now" used for warranty-window and dispatch-window evaluation, and returns `200 OK` with an empty data object.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-categories` | Create a service category / skill-tag definition | PlatformAdmin |
| GET | `/service-categories/{id}` | Fetch a service category | PlatformAdmin, Customer, Pro, Dispatcher |
| GET | `/service-categories` | List service categories | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/customers` | Register a customer | Anonymous |
| GET | `/customers/{id}` | Fetch a customer (includes wallet credit) | PlatformAdmin, Customer |
| POST | `/pros` | Register a professional | Anonymous |
| GET | `/pros/{id}` | Fetch a professional (background/license posture, callback rate) | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/pros/{id}/background-checks` | Submit a background/identity/license check for a professional | PlatformAdmin |
| GET | `/pros/{id}/background-checks` | List a professional's background checks | PlatformAdmin, Pro |
| GET | `/pros/{id}/dispatch-windows` | List a professional's dispatch windows | PlatformAdmin, Pro, Dispatcher, Customer |
| GET | `/pros/{id}/jobs` | List jobs assigned to a professional | PlatformAdmin, Pro, Dispatcher |
| POST | `/background-checks/{id}/decide` | Record PASS/FAIL on a background check | PlatformAdmin |
| POST | `/jobs` | Request a job | Customer |
| GET | `/jobs/{id}` | Fetch a job | PlatformAdmin, Customer, Pro, Dispatcher |
| GET | `/jobs` | List jobs (filter by customer, category, parent job) | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/jobs/{id}/instant-quote` | Produce an instant quote | Customer |
| POST | `/jobs/{id}/request-estimate` | Request an in-home estimate | Customer |
| POST | `/jobs/{id}/quotes` | A professional submits an in-home estimate | Pro |
| GET | `/jobs/{id}/quotes` | List quotes for a job | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/jobs/{id}/accept-quote` | Customer accepts the active quote | Customer |
| POST | `/jobs/{id}/cancel` | Cancel a job | Customer |
| POST | `/jobs/{id}/complete` | Professional marks the job complete | Pro |
| POST | `/jobs/{id}/callbacks` | Customer opens a warranty callback | Customer |
| GET | `/jobs/{id}/visits` | List a job's work visits | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/jobs/{id}/visits` | Professional logs arrival, opening a work visit | Pro |
| GET | `/work-visits/{id}` | Fetch a single work visit | PlatformAdmin, Pro, Dispatcher, Customer |
| GET | `/work-visits` | List work visits (filter by job, dispatch window) | PlatformAdmin, Pro, Dispatcher, Customer |
| POST | `/jobs/{id}/labor-lines` | Professional records labor hours | Pro |
| GET | `/jobs/{id}/labor-lines` | List labor lines for a job | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/jobs/{id}/part-lines` | Professional records a part | Pro |
| GET | `/jobs/{id}/part-lines` | List part lines for a job | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/dispatch-windows` | Professional publishes an availability window | Pro |
| GET | `/dispatch-windows/{id}` | Fetch a dispatch window (includes version, hold state) | PlatformAdmin, Customer, Pro, Dispatcher |
| GET | `/dispatch-windows` | List dispatch windows (filter by pro, ZIP, booked job) | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/dispatch-windows/{id}/book` | Book the accepted job into this window (OCC-guarded) | Customer |
| POST | `/jobs/{id}/invoices` | Professional creates a draft invoice | Pro |
| GET | `/jobs/{id}/invoices` | List invoices for a job | PlatformAdmin, Customer, Pro, Dispatcher |
| GET | `/invoices/{id}` | Fetch an invoice | PlatformAdmin, Customer, Pro, Dispatcher |
| POST | `/invoices/{id}/issue` | Professional issues the invoice | Pro |
| POST | `/invoices/{id}/pay` | Customer pays the issued invoice in full | Customer |
| POST | `/disputes` | Customer files a dispute | Customer |
| GET | `/disputes/{id}` | Fetch a dispute | PlatformAdmin, Customer |
| GET | `/disputes` | List disputes (filter by job, invoice) | PlatformAdmin, Customer |
| POST | `/disputes/{id}/review` | Admin moves a dispute into review | PlatformAdmin |
| POST | `/disputes/{id}/withdraw` | Customer withdraws a dispute | Customer |
| POST | `/disputes/{id}/resolve` | Admin approves or denies a dispute | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-only: set the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_TRAVEL_BUFFER_CONFLICT` | 409 |
| `ERR_CUSTOMER_DOUBLE_BOOKED` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_PRO_NOT_CLEARED` | 422 |
| `ERR_LICENSE_REQUIRED` | 422 |
| `ERR_SKILL_TAG_MISMATCH` | 422 |
| `ERR_INSTANT_QUOTE_INELIGIBLE` | 422 |
| `ERR_ZIP_MISMATCH` | 422 |
| `ERR_VISIT_OUTSIDE_WINDOW` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_PARTIAL_PAYMENT` | 422 |
| `ERR_REFUND_EXCEEDS_PAID` | 422 |
| `ERR_PRICING_MODEL_MISMATCH` | 422 |
| `ERR_STALE_VERSION` | 412 |
