# Crawlspace Waterproofing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Crawlspace Waterproofing API, the system of record for a residential foundation-services business that takes a homeowner from a free moisture-and-structural assessment all the way through scope design, pricing, financing, crew scheduling, installation, transferable warranty, annual service, and post-install claims. The business problem it solves is one of coordination: a single job touches field inspectors, sales estimators, an external financing partner, operations schedulers, install crews, and warranty administrators, each acting at a different moment and each capable of advancing or invalidating the work of the others.

The central record is the **Job**, which represents one property's engagement from first contact to closure. A Job advances along two independent tracks at once — a sales-and-delivery lifecycle and a financing track — and spawns a constellation of peer records (inspections, quotes, financing applications, install orders, crew bookings, warranties, service visits, claims, and foundation referrals) that reference it and one another by identifier rather than by nesting under it. Because pricing is computed twice — once as a quoted estimate and again as a reconciled final on installation — and because warranties remain live for years and can be transferred, claimed against, and lapsed, the system must enforce precise state, fiscal, temporal, and concurrency rules at every step. The sections below define the global contracts that hold everywhere, then the business workflows that move each record through its life.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly six roles: `Homeowner`, `Estimator`, `Inspector`, `Scheduler`, `WarrantyAdmin`, and `FinancePartner`.

`Homeowner` is the only entity-backed role. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner` record; ownership checks on any resource that references a `Homeowner` compare that resource's homeowner foreign key (for a Job, its `homeowner_id`) to `X-User-ID`. The remaining five roles are operational or external identities. When `X-User-Role` is `Estimator`, `Inspector`, `Scheduler`, `WarrantyAdmin`, or `FinancePartner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. `Estimator` handles sales — jobs, quotes, and lost-deal handling. `Inspector` performs field assessments and foundation referrals and quality-gates installs. `Scheduler` manages crews, crew bookings, and the install-order lifecycle. `WarrantyAdmin` issues warranties, schedules service, triages claims, and closes jobs. `FinancePartner` is the external decisioning party that approves or declines financing applications.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter sets how many items to skip from the start of the result set; it defaults to 0 and must be at least 0. A `limit` or `offset` outside those bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless stated otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; clients never supply it. Most resources also carry three system-managed fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, including mutations caused by a cascade from some other operation; and `version`, an integer that starts at 1 and increments by 1 on every mutation.

The `Homeowner` record is the sole exception: it carries only `id` and `created_at`. A `Homeowner` has no `updated_at` and no `version` field at all. Every other entity — Job, Inspection, Quote, FinancingApplication, InstallOrder, CrewBooking, Crew, Warranty, ServiceVisit, Claim, and FoundationReferral — carries the full `created_at` / `updated_at` / `version` trio.

### 2.5. Logical Clock

All time-dependent rules — quote expiry, install-start windows, warranty service due dates, service-visit spacing, and warranty lapse — are evaluated against a server-maintained logical clock rather than wall-clock time. On startup the clock reads exactly `2026-04-01T00:00:00Z` and never falls back to real time before any client sets it. An administrative test-driving capability advances the clock to a supplied instant; the request body field carrying that instant is `to_iso8601`.

### 2.6. Nested Path Resolution

Several operations address a resource through a path that names more than one identifier — for example a finalize that names both a job and an inspection. The system resolves these identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. A finalize naming a non-existent job fails on the job before the inspection is ever consulted. Beyond path identifiers, any foreign-key field supplied in a request body — such as a `homeowner_id`, `job_id`, `quote_id`, `crew_id`, `install_order_id`, `warranty_id`, `claim_id`, or `inspection_id` that names another resource — must reference an existing resource of the correct type; a dangling body reference is rejected with `ERR_FK_NOT_FOUND` (HTTP 422).

### 2.7. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the earliest applicable failure is the one reported. Authentication comes first: a missing header yields `ERR_UNAUTHENTICATED`. Role authorization comes next, yielding `ERR_FORBIDDEN_ROLE`. Then path-resource existence is verified left to right, yielding `ERR_NOT_FOUND`. Then body foreign keys are checked, yielding `ERR_FK_NOT_FOUND`. Then the request's own shape — required fields present and well-typed, enum values legal — is checked, yielding `ERR_INVALID_REQUEST` (HTTP 400). Only after all of those does the system evaluate whether the target resource is in a legal state for the requested transition, yielding `ERR_INVALID_STATE` (HTTP 409); the optimistic-concurrency version check, yielding `ERR_STALE_VERSION` (HTTP 412); and finally the domain-specific business rules described throughout §2 and §3. In short: authentication, then authorization, then path existence, then body foreign keys, then request validity, then state legality, then concurrency, then business rules.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded against acting on a stale view of their parent resource, and each requires the client to declare the parent `version` it last observed.

The install-order creation operation requires a body field `expected_job_version` carrying the `version` of the target Job that the client last read. If that value does not equal the Job's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because a Job can remain in lifecycle status `SOLD` while its `version` is bumped underneath the client — for instance when a financing decision flips `financing_status` from `APPLIED` to `APPROVED` without leaving `SOLD`. A create still carrying the pre-decision Job version is therefore stale and must be refused, even though a create carrying the fresh version against the same `SOLD`, financing-resolved Job would legitimately succeed.

The warranty transfer operation requires a body field `expected_warranty_version` carrying the `version` of the target Warranty that the client last read. If that value does not equal the Warranty's current `version`, the transfer is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against re-applying a transfer against an outdated holder view: once a prior transfer has changed the holder and advanced `transfer_count` and `version`, a second transfer still carrying the old version is refused.

The quote acceptance operation requires a body field `expected_quote_version` carrying the `version` of the target Quote that the client last read; a mismatch with the Quote's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and operations that do not name one of these three are not subject to the concurrency check.

### 2.9. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents — `subtotal_cents`, `discount_cents`, `tax_cents`, `total_cents`, `amount_financed_cents`, `monthly_payment_cents`, `final_total_cents`, and `variance_cents`. Wherever a calculation step produces a fractional cent (the discount step, the tax step, and the monthly-payment amortization step), the result is rounded to the nearest whole cent using the round-half-up rule, and rounding is applied at each such step in the pinned evaluation order rather than only once at the end. The APR is stored in basis points as the integer `apr_bps`.

### 2.10. Cascading State Consistency

Many operations mutate more than one record. When an operation changes a child record in a way that drives a parent's state, the parent is updated in the same request, its `updated_at` refreshed and its `version` incremented; the same holds in reverse when a parent operation reaches down to its children. Two derived counters on the Job are kept reconciled this way: `assessment_severity`, which mirrors the severity of the Job's most recent finalized inspection (and reads `NONE` before any inspection is finalized), and `open_claim_count`, which is always the number of this Job's claims whose status is `OPEN` or `IN_PROGRESS`. Each affected record's own `version` is incremented when it is mutated as part of such a cascade. The specific cascades are described in the workflows of §3.

## 3. Business Logic & Workflows

### 3.1. Establishing the Job and Its Two Tracks

A new engagement begins when an `Estimator` or a `Homeowner` registers the customer and opens a Job. Registering a homeowner — which any back-office operator (`Estimator`, `Scheduler`, or `WarrantyAdmin`) may also do on a customer's behalf — captures the owner's `full_name`, `email`, and `credit_band`, where `credit_band` is one of `PRIME`, `NEAR_PRIME`, or `SUBPRIME` and later drives the financing rate. Opening a Job records the `homeowner_id` of the owner, the `property_address`, the `structure_type` (one of `CRAWLSPACE`, `BASEMENT`, or `COMBINED`), and the `footprint_sqft`, the conditioned floor area used in pricing, which must be at least 1. A footprint below 1 is rejected with `ERR_VALIDATION` (HTTP 422).

A freshly created Job opens in lifecycle status `LEAD` with financing status `NONE`, an `assessment_severity` of `NONE`, and an `open_claim_count` of 0. The Job tracks two pointers that fill in later: `accepted_quote_id`, which stays null until a quote is accepted and the Job becomes `SOLD`, and `install_order_id`, which stays null until an install is scheduled. The Job's `lifecycle_status` moves through `LEAD`, `INSPECTED`, `QUOTED`, `SOLD`, `SCHEDULED`, `INSTALLED`, `WARRANTED`, and finally `CLOSED`, or branches to `LOST`; `CLOSED` and `LOST` are terminal. Independently, its `financing_status` moves among `NONE`, `APPLIED`, `APPROVED`, `DECLINED`, and `CASH`. These two dimensions evolve on their own timelines: a financing decision can advance the financing track while the lifecycle track holds steady.

While a Job is still early — in `LEAD`, `INSPECTED`, or `QUOTED` — an `Estimator` may abandon it, transitioning `lifecycle_status` to `LOST`. Marking a job lost also declines every quote on that Job that is currently in `DRAFT` or `SENT` status, moving each such quote to `DECLINED`, and increments the Job's `version`. A mark-lost attempt from any other lifecycle status is rejected with `ERR_INVALID_STATE`.

### 3.2. Inspection and Severity Assessment

An `Inspector` creates a draft inspection against a Job, recording the measured `moisture_pct` (an ambient moisture percentage between 0 and 100), the `structural_findings_count` (a count of distinct structural defects, at least 0), and whether `standing_water` was observed (defaulting to false). The new inspection's `job_id` ties it to the Job, and it opens in status `DRAFT`. An inspection's `status` is one of `DRAFT`, `FINALIZED`, or `SUPERSEDED`; `SUPERSEDED` is terminal, but `FINALIZED` is not, because a later finalize can supersede an earlier finalized inspection.

Finalizing an inspection — permitted only while it is in `DRAFT`, otherwise rejected with `ERR_INVALID_STATE` — moves it to `FINALIZED` and computes its `severity`. The severity computation runs in a pinned order: first a numeric score is built, then the score is mapped to a base severity band, then a standing-water override is applied. The score starts at zero. Moisture contributes in bands: if `moisture_pct` is at least 80, the score gains 3 points; otherwise, if `moisture_pct` is at least 60, the score gains 1 point; below 60 it contributes nothing. Structural findings contribute next: the `structural_findings_count`, but capped at a maximum of 4 counted findings, is multiplied by 2 points each and added to the score. Standing water deliberately contributes nothing to the score itself.

The accumulated score is then mapped to a base severity: a score of at least 7 maps to `SEVERE`; otherwise a score of at least 4 maps to `MODERATE`; otherwise a score of at least 1 maps to `LOW`; a score of 0 maps to `NONE`. After this mapping, one override is applied: if standing water was observed and there was at least one structural finding and the base mapping landed at `LOW` or `NONE`, the severity is forced up to `MODERATE`. In every other case — no standing water, no structural finding, or a base mapping that already reached `MODERATE` or `SEVERE` — the override does nothing and the base mapping stands. The resulting `severity` is one of `NONE`, `LOW`, `MODERATE`, or `SEVERE`.

The first time any inspection on a Job is finalized, the Job advances from `LEAD` to `INSPECTED`. On every finalize, if a prior `FINALIZED` inspection already exists on the same Job, that earlier inspection is moved to `SUPERSEDED` (with its own `version` incremented), and the Job's `assessment_severity` is set to the severity just computed. Both the inspection's `version` and the Job's `version` are incremented.

### 3.3. Foundation Referrals

When an inspection reveals the most serious conditions, the work is referred to a foundation-repair partner. An `Inspector` drafts a `FoundationReferral` against a Job, supplying the `inspection_id` of the finalized inspection that triggered eligibility and the `partner_name` of the firm the referral will go to. The referral records its `job_id` and opens in status `DRAFT`; its `status` is one of `DRAFT`, `SENT`, `ACCEPTED`, or `REJECTED`, with `ACCEPTED` and `REJECTED` terminal.

Sending a referral moves it from `DRAFT` to `SENT`, but only when the referenced inspection is `FINALIZED` with a severity of exactly `SEVERE`. A send against an inspection that is not finalized-and-severe is rejected with `ERR_REFERRAL_NOT_ELIGIBLE` (HTTP 422); a send from any status other than `DRAFT` is rejected with `ERR_INVALID_STATE`. Once sent, the partner's outcome resolves the referral: resolving with an accept outcome moves it from `SENT` to `ACCEPTED`, and resolving with a reject outcome moves it from `SENT` to `REJECTED`. The body field carrying the partner's decision is `outcome`. Each transition increments the referral's `version`.

### 3.4. Quoting: Scope, Pricing, and the Revision Loop

An `Estimator` creates a draft quote against a Job to capture scope and price. The scope is a set of boolean line-item flags: `includes_vapor_barrier`, `includes_sump`, `includes_dehumidifier`, `includes_drain`, and `includes_battery_backup`, each defaulting to false. When `includes_drain` is set, the quantity of interior drain is given by `drain_linear_ft` (at least 0, defaulting to 0). An optional `discount_code` may be supplied, one of `SPRING10`, `SENIOR15`, or `NONE` (defaulting to `NONE`). A quote carries a `job_id`, a 1-based `revision` index (starting at 1), and opens in status `DRAFT`; its `status` is one of `DRAFT`, `SENT`, `ACCEPTED`, `REVISED`, `EXPIRED`, or `DECLINED`, of which `ACCEPTED`, `EXPIRED`, and `DECLINED` are terminal.

The battery-backup line item is an add-on to the sump system: setting `includes_battery_backup` to true requires `includes_sump` to also be true on the same quote, both at quote creation and at quote revision. A battery-backup flag without a sump on the same quote is rejected with `ERR_BACKUP_REQUIRES_SUMP` (HTTP 422).

**Pricing.** On quote create and on quote revise, the price is computed in a pinned order — line items, then subtotal, then discount, then tax, then total — and recorded into `subtotal_cents`, `discount_cents`, `tax_cents`, and `total_cents`. The line items are built as follows. The base charge is tiered by the Job's `footprint_sqft`: a footprint of at most 800 square feet bases at 250,000 cents; a footprint from 801 through 1500 square feet bases at 400,000 cents; a footprint above 1500 square feet bases at 600,000 cents. If the vapor barrier is included, it adds 180 cents per square foot of `footprint_sqft`; otherwise it adds nothing. If the sump is included, it adds a flat 120,000 cents. If the dehumidifier is included, it adds a flat 165,000 cents. If the battery backup is included, it adds a flat 90,000 cents. The drain charge applies only when the drain is included: the first 20 linear feet are free, so the billable footage is the drain length minus 20 but never below zero, and the billable footage is charged at 4,500 cents per foot. The subtotal is the sum of the base, vapor, sump, dehumidifier, backup, and drain charges.

The discount is a percentage of the subtotal: `SPRING10` is 10 percent, `SENIOR15` is 15 percent, and `NONE` (or any other value) is 0 percent. The discount amount is the subtotal multiplied by that percentage, rounded half up to whole cents, and recorded as `discount_cents`. The discounted subtotal is the subtotal minus the discount. Tax is then computed on the discounted subtotal — not on the pre-discount subtotal — at a rate of 7 percent, rounded half up to whole cents, and recorded as `tax_cents`. The total is the discounted subtotal plus the tax. Pricing draws only on the single quote's own scope flags together with the parent Job's `footprint_sqft`; it never aggregates across quotes.

**Sending and the revision loop.** Sending a draft quote moves it from `DRAFT` to `SENT` and sets `expires_at` to its `created_at` plus 30 days; a send is permitted only while the quote is `DRAFT` and the Job is in `INSPECTED` or `QUOTED`. The first time a quote on a Job is sent, the Job advances from `INSPECTED` to `QUOTED`. A sent quote may be revised: revising moves the current quote from `SENT` to `REVISED` and spawns a brand-new draft quote whose `revision` is one greater than the revised quote's, copying the scope flags forward and recomputing pricing; the new quote opens in `DRAFT` and can itself be sent, looping back into the cycle. Each of these transitions increments the affected quotes' `version`.

A sent quote that the homeowner does not want may be declined by the `Homeowner`, moving it from `SENT` to `DECLINED`. A sent quote may also expire: once the logical clock reaches or passes the quote's `expires_at`, an `Estimator` may expire it (moving `SENT` to `EXPIRED`), and the system likewise treats a sent quote as expired when an accept or read finds the clock at or past `expires_at`.

### 3.5. Acceptance and the Sale

The `Homeowner` accepts a sent quote to turn the deal into a sale. Acceptance is permitted only when the quote is `SENT`, the logical clock is strictly before the quote's `expires_at`, and the Job is in lifecycle `QUOTED`. An accept attempted at or after `expires_at` is rejected with `ERR_QUOTE_EXPIRED` (HTTP 409); an accept of a quote not in `SENT` is rejected with `ERR_INVALID_STATE`. Acceptance is optimistic-concurrency-guarded: the request must carry `expected_quote_version` matching the quote's current `version`, failing which it is rejected with `ERR_STALE_VERSION` (HTTP 412).

A successful acceptance moves the quote from `SENT` to `ACCEPTED`, sets the Job's `accepted_quote_id` to that quote, advances the Job's `lifecycle_status` from `QUOTED` to `SOLD`, and declines every sibling quote on the same Job that is still in `SENT`, moving each to `DECLINED`. The Job's `version` and the affected quotes' `version` are all incremented.

### 3.6. Financing the Sale

Once a Job is `SOLD`, the homeowner resolves how it will be paid. The simplest path is cash: the `Homeowner` elects cash payment, which moves `financing_status` from `NONE` to `CASH`; this is permitted only when the Job is `SOLD` and its `financing_status` is still `NONE`, and it increments the Job's `version`.

Alternatively, the `Homeowner` submits a `FinancingApplication`. The application names the `job_id`, the `quote_id` of the accepted quote being financed, and the `term_months`, which must be one of 12, 24, 36, or 60 (an invalid term is rejected with `ERR_VALIDATION`). Submitting is permitted only when the Job is `SOLD` with `financing_status` of `NONE`; it creates the application in status `SUBMITTED`, moves the Job's `financing_status` from `NONE` to `APPLIED`, and increments the Job's `version`. The application's `status` is one of `SUBMITTED`, `APPROVED`, `DECLINED`, or `WITHDRAWN`, with `APPROVED`, `DECLINED`, and `WITHDRAWN` terminal.

At submission the financed amount is locked: `amount_financed_cents` is pinned to the accepted quote's `total_cents`. The rate and payment are then computed. The APR in basis points, `apr_bps`, is selected by a two-dimensional tier of the homeowner's `credit_band` against a term bucket, where the term bucket is "short" when `term_months` is 24 or fewer and "long" when `term_months` is greater than 24. For a `PRIME` band the APR is 599 basis points short and 799 long; for `NEAR_PRIME` it is 1099 short and 1399 long; for `SUBPRIME` it is 1999 short and 2399 long. The `monthly_payment_cents` is the standard amortized payment of the financed principal at the monthly rate over the term: the monthly rate is `apr_bps` divided by 10,000 and then by 12; with `n` equal to `term_months` and `P` equal to `amount_financed_cents`, when the monthly rate is zero the payment is the principal divided by the number of months, and otherwise the payment is the principal times the monthly rate times the quantity one-plus-the-monthly-rate raised to the number of months, divided by the quantity one-plus-the-monthly-rate raised to the number of months minus one. The result is rounded half up to whole cents.

The `FinancePartner` then decides the application, supplying a `decision` of approve or decline. Approving requires the application to be `SUBMITTED` and the Job's `financing_status` to be `APPLIED`; it moves the application to `APPROVED` and the Job's `financing_status` to `APPROVED`. Declining likewise requires a `SUBMITTED` application and moves it to `DECLINED` while moving the Job's `financing_status` to `DECLINED`. Approval additionally enforces a per-band ceiling: the `amount_financed_cents` must not exceed the maximum the credit band allows — 5,000,000 cents for `PRIME`, 3,000,000 cents for `NEAR_PRIME`, and 1,500,000 cents for `SUBPRIME`. An approval whose financed amount exceeds the band's ceiling is rejected with `ERR_FINANCE_LIMIT_EXCEEDED` (HTTP 422); because the ceiling is lowest for `SUBPRIME`, subprime applications hit this limit soonest. Each decision increments the relevant `version` values.

A homeowner whose application was declined may withdraw it: withdrawing requires the application to be `DECLINED` and the Job's `financing_status` to be `DECLINED`, moves the application from `DECLINED` to `WITHDRAWN`, and resets the Job's `financing_status` from `DECLINED` back to `NONE`, freeing the homeowner to choose cash or reapply. The relevant `version` values are incremented.

### 3.7. Scheduling and Running the Install

With a sale in hand and financing resolved, a `Scheduler` schedules the install by creating an InstallOrder against the Job. This is permitted only when the Job is `SOLD` and its `financing_status` is either `CASH` or `APPROVED`; an attempt while financing is still unresolved (any status other than `CASH` or `APPROVED`) is rejected with `ERR_FINANCING_UNRESOLVED` (HTTP 409). The create is also optimistic-concurrency-guarded per §2.8: it requires `expected_job_version` matching the Job's current `version`, failing which it is rejected with `ERR_STALE_VERSION`. The request supplies the planned `scheduled_start` and `scheduled_end` of the install window, which is treated as half-open from start up to but not including end. On success an InstallOrder is created in status `PLANNED` with its `job_id` set, its `quote_id` pinned to the Job's `accepted_quote_id`, the Job's `install_order_id` pointed at the new order, and the Job advanced from `SOLD` to `SCHEDULED`; the Job's `version` is incremented.

An InstallOrder's `status` moves through `PLANNED`, `DISPATCHED`, `IN_PROGRESS`, `PASSED` or `FAILED`, `COMPLETED`, or `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. Dispatching moves it from `PLANNED` to `DISPATCHED` but only when at least one `CONFIRMED` crew booking exists for that order. Starting moves it from `DISPATCHED` to `IN_PROGRESS`, permitted only when the logical clock is at or past the order's `scheduled_start`. Quality gating then branches: an `Inspector` either passes the work, moving `IN_PROGRESS` to `PASSED`, or fails it, moving `IN_PROGRESS` to `FAILED`. A failed install loops back for rework: starting it again moves `FAILED` to `IN_PROGRESS` (with no clock precondition on the restart). Each of these transitions increments the order's `version`. A transition attempted from the wrong status — dispatching something not `PLANNED`, passing or failing something not `IN_PROGRESS`, and so on — is rejected with `ERR_INVALID_STATE`.

Completing a passed install is the reconciliation moment. Completion is permitted only when the order is `PASSED` and the Job is `SCHEDULED`; the operator may supply `actual_drain_linear_ft`, the drain footage actually installed (at least 0, defaulting to 0). On completion the order moves from `PASSED` to `COMPLETED`, the Job advances from `SCHEDULED` to `INSTALLED`, every crew booking for that order still in `RESERVED` or `CONFIRMED` is released to `RELEASED`, and the final cost is reconciled. The reconciliation re-runs the same pricing formula and pinned order used for the quote, but on the accepted quote's frozen scope flags and substituting `actual_drain_linear_ft` for the quoted `drain_linear_ft`: the billable drain footage is the actual footage minus the 20 free feet but never below zero (and zero if the accepted quote did not include the drain), charged at 4,500 cents per foot; the subtotal re-sums the same base, vapor, sump, dehumidifier, and backup charges plus this reconciled drain charge; the discount re-applies the accepted quote's discount percentage to that subtotal, rounded half up; tax at 7 percent is applied to the discounted subtotal, rounded half up; and the result becomes `final_total_cents`. The `variance_cents` is `final_total_cents` minus the accepted quote's `total_cents`; a positive variance is an overage billed to the homeowner. The order's and Job's `version` are incremented.

A planned or dispatched install may instead be cancelled by the `Scheduler`. Cancelling is permitted only from `PLANNED` or `DISPATCHED`; it moves the order to `CANCELLED`, releases every crew booking for the order still in `RESERVED` or `CONFIRMED` to `RELEASED`, reverts the Job's `lifecycle_status` from `SCHEDULED` back to `SOLD`, clears the Job's `install_order_id` back to null, and increments the relevant `version` values.

### 3.8. Crews and Bookings

A `Scheduler` maintains the install crews. Creating a crew records its `name`, its `home_region` (a region code such as NORTH or SOUTH), its `daily_capacity` (the maximum number of confirmed bookings it may hold on any one calendar day, at least 1), and whether it is `active` and bookable (defaulting to true).

To staff an install, the `Scheduler` reserves a crew by creating a CrewBooking that names the `crew_id` and the `install_order_id` it serves and the booking window via `window_start` and `window_end`, again treated as half-open from start up to but not including end. A new booking opens in status `RESERVED`; a booking's `status` is one of `RESERVED`, `CONFIRMED`, or `RELEASED`, with `RELEASED` terminal.

Confirming a reserved booking moves it from `RESERVED` to `CONFIRMED`, subject to two operational guards. First, the booking must not overlap any existing `CONFIRMED` booking on the same crew: two windows collide when their half-open `window_start`-to-`window_end` intervals intersect, and a colliding confirm is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409). Second, confirming must not push the crew over its `daily_capacity`: the count of the crew's `CONFIRMED` bookings on the booking's calendar day must remain below `daily_capacity`, and a confirm that would exceed it is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409). Confirming something not in `RESERVED` is rejected with `ERR_INVALID_STATE`. A booking in `RESERVED` or `CONFIRMED` may be released — explicitly by the `Scheduler` or automatically by the system when its install order completes or cancels — moving it to `RELEASED`. Each transition increments the booking's `version`.

### 3.9. Warranty Issuance, Transfer, and Lapse

Once an install is complete, a `WarrantyAdmin` issues the transferable warranty on the Job. Issuance is permitted only when the Job is `INSTALLED` and its install order is `COMPLETED`; it creates a Warranty in status `ACTIVE` with its `job_id` set, its `install_order_id` pointing at the completed order, its `holder_homeowner_id` set to the Job's `homeowner_id`, and its `coverage_years` set to the requested coverage length (the lifetime covenant is encoded as 25, which is also the default). The issuance sets the warranty's `next_service_due` to the activation instant plus one year, advances the Job from `INSTALLED` to `WARRANTED`, and increments the Job's `version`. A warranty's `status` is one of `ACTIVE`, `TRANSFERRED`, `VOID`, or `LAPSED`, with `VOID` and `LAPSED` terminal. The warranty also tracks `transfer_count` (starting at 0), `last_service_at` (null until the first completed service), and `next_service_due`.

A warranty may change hands. Transferring it requires the warranty to be `ACTIVE` and its `transfer_count` to be below the ceiling of 3 transfers; a transfer attempted once `transfer_count` has reached 3 is rejected with `ERR_TRANSFER_LIMIT_REACHED` (HTTP 422). The request names the `new_holder_homeowner_id` and carries `expected_warranty_version` for the optimistic-concurrency guard of §2.8 (a mismatch yields `ERR_STALE_VERSION`). A transfer sets `holder_homeowner_id` to the new holder, increments `transfer_count` by 1, and increments the warranty's `version`; the warranty momentarily passes through `TRANSFERRED` and settles back to `ACTIVE` within the same request, ready to be transferred again until the ceiling is reached.

A `WarrantyAdmin` may void an active warranty, moving it from `ACTIVE` to `VOID`; voiding also cancels every `SCHEDULED` service visit on that warranty, moving each to `CANCELLED`, and increments the relevant `version` values. A warranty also lapses when its annual service is overdue: lapsing moves it from `ACTIVE` to `LAPSED`, but only when the logical clock is at or past the warranty's `next_service_due` plus a 30-day grace period; it increments the warranty's `version`. The system may lapse an overdue warranty automatically once that grace window has elapsed.

### 3.10. Annual Service and Claim Repair Visits

Service against a warranty is recorded as a ServiceVisit, scheduled by a `WarrantyAdmin`. A visit names its `warranty_id`, its `visit_type` (either `ANNUAL` for routine maintenance or `CLAIM_REPAIR` to resolve a claim), the `scheduled_for` instant, and, when the type is `CLAIM_REPAIR`, the `claim_id` of the claim it repairs (which is null for `ANNUAL` visits). A visit opens in status `SCHEDULED`; its `status` is one of `SCHEDULED`, `COMPLETED`, or `CANCELLED`, with the latter two terminal.

A `CLAIM_REPAIR` visit must carry a non-null `claim_id` whose claim exists and is `IN_PROGRESS` at scheduling time, and an `ANNUAL` visit must carry no `claim_id`; a `CLAIM_REPAIR` without an in-progress claim, or an `ANNUAL` with a claim attached, is rejected with `ERR_VISIT_CLAIM_MISMATCH` (HTTP 422). Visits on the same warranty must also be spaced apart: a new visit must sit at least 7 calendar days from every other `SCHEDULED` visit on the same warranty. Each visit is treated as a point in time, the gap is the absolute difference between its `scheduled_for` and that of another scheduled visit, and so two scheduled visits within the 7-day buffer — including ones at the very same instant — collide and the new one is rejected with `ERR_VISIT_TOO_CLOSE` (HTTP 409).

Completing a visit is permitted only when the visit is `SCHEDULED` and its warranty is `ACTIVE`; it moves the visit from `SCHEDULED` to `COMPLETED`. The effect depends on the type: completing an `ANNUAL` visit sets the warranty's `last_service_at` to the completion instant and resets its `next_service_due` to the completion instant plus one year, resetting the annual-service clock; completing a `CLAIM_REPAIR` visit drives its referenced claim from `IN_PROGRESS` to `RESOLVED` and recomputes the Job's `open_claim_count`. A scheduled visit may instead be cancelled — explicitly by the `WarrantyAdmin` or automatically when its warranty is voided — moving it from `SCHEDULED` to `CANCELLED`. Each transition increments the visit's `version`.

### 3.11. Claims and the Reopen Cycle

A `Homeowner` or a `WarrantyAdmin` files a Claim against a warranty when something goes wrong after the install. A claim names the `job_id`, the `warranty_id` it is claimed against, its `category` (one of `WATER_INTRUSION`, `PUMP_FAILURE`, or `STRUCTURAL`), and a free-text `description`. Filing creates the claim in status `OPEN`, recomputes the Job's `open_claim_count`, and increments the Job's `version`. A claim's `status` is one of `OPEN`, `IN_PROGRESS`, `RESOLVED`, `DENIED`, or `REOPENED`, of which only `DENIED` is terminal; the claim also tracks a `reopen_count` (starting at 0). Throughout, the Job's `open_claim_count` is kept equal to the number of this Job's claims whose status is `OPEN` or `IN_PROGRESS`.

A `WarrantyAdmin` triages a claim with an `accept` flag. Triaging with accept true moves a claim from `OPEN` (or from `REOPENED`) to `IN_PROGRESS`, but only when the warranty is `ACTIVE` and the claim's category is one the warranty covers — and `STRUCTURAL` claims are explicitly not covered. A triage-accept on a category the warranty does not cover (a `STRUCTURAL` claim) is rejected with `ERR_CLAIM_NOT_COVERED` (HTTP 422). Triaging with accept false moves a claim from `OPEN` to `DENIED`. Either triage outcome recomputes the Job's `open_claim_count` and increments the relevant `version` values.

A claim reaches `RESOLVED` when a `CLAIM_REPAIR` service visit referencing it is completed, as described above; the system performs that transition and recomputes `open_claim_count`. A resolved claim is not necessarily final: a `Homeowner` may reopen it while the warranty is still `ACTIVE`, moving it from `RESOLVED` to `REOPENED`, incrementing its `reopen_count` by 1, recomputing the Job's `open_claim_count`, and incrementing the claim's `version`. A reopened claim can be triaged back into `IN_PROGRESS`, closing the loop.

### 3.12. Closing the Job

When all work and obligations are settled, a `WarrantyAdmin` closes the Job, advancing it from `WARRANTED` to `CLOSED`. Closure is permitted only when the Job has no open claims — that is, when its `open_claim_count` is 0; a close attempted while open claims remain is rejected with `ERR_OPEN_CLAIMS_BLOCK_CLOSE` (HTTP 409), and a close from any status other than `WARRANTED` is rejected with `ERR_INVALID_STATE`. A successful close increments the Job's `version`. `CLOSED`, like `LOST`, is a terminal resting state for the Job.

To keep deep-precondition test setups tractable, two administrative fast-forward capabilities exist. One provisions a Job all the way to lifecycle `SCHEDULED` — composing the full lead-through-inspection-through-quote-through-accept-through-cash-through-install-order chain with a sump-only accepted quote and `CASH` financing and a fresh `PLANNED` install order — taking a `homeowner_id` and returning the new `job_id`, `quote_id`, `install_order_id`, and `job_version`. The other provisions a Job all the way to `WARRANTED`, composing that same chain plus dispatch, start, pass, complete, and warranty issuance, taking a `homeowner_id` and returning the new `job_id`, `warranty_id`, and `install_order_id`, with the resulting warranty held by that homeowner.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. List and read operations return `200 OK`. The administrative clock capability returns `200 OK`; the two seed fast-forwards return `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Scheduler, WarrantyAdmin, Estimator, Inspector, FinancePartner, Homeowner |
| POST | `/_seed/scheduled-job` | Fast-forward a job to SCHEDULED | Scheduler |
| POST | `/_seed/warranted-job` | Fast-forward a job to WARRANTED | WarrantyAdmin |
| POST | `/homeowners` | Register a homeowner | Homeowner, Estimator, Scheduler, WarrantyAdmin |
| GET | `/homeowners/{homeowner_id}` | Get a homeowner | Homeowner, Estimator, WarrantyAdmin |
| POST | `/crews` | Create a crew | Scheduler |
| GET | `/crews/{crew_id}` | Get a crew | Scheduler |
| POST | `/jobs` | Create a job (lead) | Estimator, Homeowner |
| GET | `/jobs/{job_id}` | Get a job | Estimator, Homeowner, Scheduler, WarrantyAdmin, Inspector, FinancePartner |
| GET | `/jobs` | List jobs, filterable by homeowner | Estimator, Scheduler, WarrantyAdmin |
| POST | `/jobs/{job_id}/mark-lost` | Mark a job LOST | Estimator |
| POST | `/jobs/{job_id}/pay-cash` | Mark the job financed by cash | Homeowner |
| POST | `/jobs/{job_id}/install-orders` | Create the install order, moving the job to SCHEDULED | Scheduler |
| POST | `/jobs/{job_id}/warranty` | Issue the transferable warranty | WarrantyAdmin |
| POST | `/jobs/{job_id}/close` | Close a fully-warranted job | WarrantyAdmin |
| POST | `/jobs/{job_id}/inspections` | Create a draft inspection for a job | Inspector |
| GET | `/inspections/{inspection_id}` | Get an inspection | Inspector, Estimator, Homeowner |
| GET | `/inspections` | List inspections, filterable by job | Inspector, Estimator, Homeowner |
| POST | `/jobs/{job_id}/inspections/{inspection_id}/finalize` | Finalize an inspection; compute severity | Inspector |
| POST | `/jobs/{job_id}/quotes` | Create a draft quote | Estimator |
| GET | `/quotes/{quote_id}` | Get a quote | Estimator, Homeowner |
| GET | `/quotes` | List quotes, filterable by job | Estimator, Homeowner |
| POST | `/quotes/{quote_id}/send` | Send a draft quote | Estimator |
| POST | `/quotes/{quote_id}/revise` | Revise a sent quote, spawning a new draft | Estimator |
| POST | `/quotes/{quote_id}/accept` | Accept the quote (OCC-guarded) | Homeowner |
| POST | `/quotes/{quote_id}/decline` | Decline a sent quote | Homeowner |
| POST | `/quotes/{quote_id}/expire` | Expire a sent quote past its expiry | Estimator |
| POST | `/financing-applications` | Submit a financing application | Homeowner |
| GET | `/financing-applications/{app_id}` | Get a financing application | Homeowner, FinancePartner |
| GET | `/financing-applications` | List financing applications, filterable by job | Homeowner, FinancePartner |
| POST | `/financing-applications/{app_id}/decide` | Approve or decline financing | FinancePartner |
| POST | `/financing-applications/{app_id}/withdraw` | Withdraw a declined application | Homeowner |
| GET | `/install-orders/{install_order_id}` | Get an install order | Scheduler, Inspector, WarrantyAdmin |
| GET | `/install-orders` | List install orders, filterable by job | Scheduler, Inspector, WarrantyAdmin |
| POST | `/install-orders/{install_order_id}/dispatch` | Dispatch a planned install | Scheduler |
| POST | `/install-orders/{install_order_id}/start` | Start (or restart after FAIL) the install | Scheduler |
| POST | `/install-orders/{install_order_id}/inspect-pass` | Quality inspection passes | Inspector |
| POST | `/install-orders/{install_order_id}/inspect-fail` | Quality inspection fails | Inspector |
| POST | `/install-orders/{install_order_id}/complete` | Complete a passed install; reconcile cost | Scheduler |
| POST | `/install-orders/{install_order_id}/cancel` | Cancel a planned/dispatched install | Scheduler |
| POST | `/crew-bookings` | Reserve a crew for an install order | Scheduler |
| GET | `/crew-bookings/{booking_id}` | Get a crew booking | Scheduler |
| GET | `/crew-bookings` | List crew bookings, filterable by crew or install order | Scheduler |
| POST | `/crew-bookings/{booking_id}/confirm` | Confirm a reserved booking | Scheduler |
| POST | `/crew-bookings/{booking_id}/release` | Release a reserved or confirmed booking | Scheduler |
| GET | `/warranties/{warranty_id}` | Get a warranty | WarrantyAdmin, Homeowner |
| GET | `/warranties` | List warranties, filterable by job | WarrantyAdmin, Homeowner |
| POST | `/warranties/{warranty_id}/transfer` | Transfer the warranty (OCC-guarded) | WarrantyAdmin |
| POST | `/warranties/{warranty_id}/void` | Void a warranty | WarrantyAdmin |
| POST | `/warranties/{warranty_id}/lapse` | Lapse a warranty overdue past grace | WarrantyAdmin |
| POST | `/warranties/{warranty_id}/service-visits` | Schedule a service visit | WarrantyAdmin |
| GET | `/service-visits/{visit_id}` | Get a service visit | WarrantyAdmin, Homeowner |
| GET | `/service-visits` | List service visits, filterable by warranty | WarrantyAdmin, Homeowner |
| POST | `/service-visits/{visit_id}/complete` | Complete a service visit | WarrantyAdmin |
| POST | `/service-visits/{visit_id}/cancel` | Cancel a scheduled service visit | WarrantyAdmin |
| POST | `/claims` | File a callback/claim against a warranty | Homeowner, WarrantyAdmin |
| GET | `/claims/{claim_id}` | Get a claim | Homeowner, WarrantyAdmin |
| GET | `/claims` | List claims, filterable by job or warranty | Homeowner, WarrantyAdmin |
| POST | `/claims/{claim_id}/triage` | Triage a claim: accept or deny | WarrantyAdmin |
| POST | `/claims/{claim_id}/reopen` | Reopen a resolved claim | Homeowner |
| POST | `/jobs/{job_id}/foundation-referrals` | Draft a foundation-repair referral | Inspector |
| GET | `/foundation-referrals/{referral_id}` | Get a foundation referral | Inspector, Estimator |
| GET | `/foundation-referrals` | List foundation referrals, filterable by job or inspection | Inspector, Estimator |
| POST | `/foundation-referrals/{referral_id}/send` | Send a draft referral | Inspector |
| POST | `/foundation-referrals/{referral_id}/resolve` | Resolve a sent referral | Inspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_CLAIM_NOT_COVERED` | 422 |
| `ERR_REFERRAL_NOT_ELIGIBLE` | 422 |
| `ERR_BACKUP_REQUIRES_SUMP` | 422 |
| `ERR_FINANCING_UNRESOLVED` | 409 |
| `ERR_FINANCE_LIMIT_EXCEEDED` | 422 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_TRANSFER_LIMIT_REACHED` | 422 |
| `ERR_VISIT_CLAIM_MISMATCH` | 422 |
| `ERR_VISIT_TOO_CLOSE` | 409 |
| `ERR_OPEN_CLAIMS_BLOCK_CLOSE` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
