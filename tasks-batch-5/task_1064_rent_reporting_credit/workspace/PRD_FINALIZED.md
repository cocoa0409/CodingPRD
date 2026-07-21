# Rent-Reporting & Credit API — Product Requirements Document

## 1. Introduction

Millions of renters make their single largest monthly payment — the rent — without any of it ever reaching the credit bureaus that gate their access to loans, cards, and future housing. This API powers a rent-reporting and rent-to-credit service that closes that gap. It lets a tenant enrol on a subscription plan, prove a lease through their landlord or property manager, and have on-time rent payments furnished as tri-bureau tradelines to Equifax, Experian, and TransUnion. Around that core furnishing loop the platform layers the operational machinery a regulated credit furnisher needs: paid subscriptions and prorated cancellation, optional back-reporting of historical months, a formal dispute-and-correction workflow with segregation of duties between the analyst who investigates and the officer who resolves, and a running view of each tenant's on-time performance and latest bureau scores.

The system is fundamentally a compliance-and-ledger engine: every furnished tradeline, every dispute correction, and every cancellation must leave the tenant's denormalized statistics and the money ledger in a consistent state, and the audit trail must be reconstructable at any time. Because credit-reporting decisions are time-sensitive, the service runs on a **logical clock** rather than wall-clock time, so that dispute windows, subscription periods, and back-reporting eligibility can be tested deterministically. This document specifies the complete contract: the global conventions every endpoint obeys, the business workflows that move each entity through its lifecycle, the full endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The platform recognises exactly five roles: `Tenant`, `Landlord`, `ComplianceAnalyst`, `ComplianceOfficer`, and `PlatformAdmin`. If either header is missing or `X-User-Role` is not one of these five known roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the acting role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_UNAUTHORIZED`.

Two of the roles are **entity-backed**, meaning their `X-User-ID` is a real persisted identity that drives ownership checks:

- When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`. Ownership checks on any resource that references a tenant compare the resource's tenant foreign key to `X-User-ID`: a tenant may read and act only on their own enrolments, leases, disputes, rent payments, reported items, back-report requests, invoices, credit summary, and score snapshots.
- When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`. Ownership checks compare a lease's `landlord_id` to `X-User-ID`: a landlord may verify only the leases they are named on and may record rent payments only against those leases.

The remaining three roles are **opaque operators**: their `X-User-ID` is an operator identifier not tied to any persisted entity's `id`. The server never compares it to a resource `id`, but it may record it where a workflow demands an audit stamp. When `X-User-Role` is `ComplianceAnalyst`, the operator furnishes tradelines, opens dispute investigations, and completes back-reports; the server records this id as `analyst_user_id` on a dispute when the analyst opens its investigation. When `X-User-Role` is `ComplianceOfficer`, the operator retracts tradelines, resolves disputes, and decides back-reports; the server records this id as `officer_user_id` on a dispute when the officer resolves it. When `X-User-Role` is `PlatformAdmin`, the operator is an operational superuser responsible for onboarding tenants, landlords, and plans, ingesting bureau scores, and driving the logical clock; the platform admin may also act as an operational override on most tenant- and landlord-scoped write operations. None of these three opaque ids are ever matched against an entity `id` for ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response reports the pagination state inside the `meta` object of the envelope through four fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed properties. Every resource has an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recorded when the resource is first created. All resources **except** the score snapshot additionally carry an `updated_at` timestamp — an ISO 8601 UTC value refreshed on every mutation — and a `version`, an integer that starts at 1 and increments by one on each mutation. The score snapshot is an append-only reading and is therefore an exception: it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field, because it is never modified after ingestion.

Time in this system is governed by a **logical clock**, not the host wall-clock. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and until an administrator advances it, every timestamp the server stamps and every "now" comparison uses that fixed instant. A platform administrator advances the clock by supplying a target instant in the `to_iso8601` field; the target must not be strictly before the current clock value, and an attempt to move the clock backwards is rejected with `ERR_CLOCK_BEFORE_CURRENT`. Setting the clock returns the new value under a `current_utc` field. Every logical-clock-derived value in this document — activation instants, cancellation instants, invoice payment instants, dispute deadlines, and payment on-time comparisons — reads from this clock.

### 2.5. Monetary Precision and Rounding

All monetary amounts are expressed as integer cents; there are no fractional-cent values anywhere in the system. Where a calculation produces a non-integer intermediate — the prorated earned revenue at cancellation, or a percentage-based on-time rate — the result is rounded half up to the target granularity: to a whole cent for money, and to a whole integer percent for on-time rates. Rounding half up means a value ending in exactly one-half rounds away from zero to the next integer. Ratios and rates never round down by truncation.

### 2.6. Optimistic Concurrency on Rent-Payment Recording

Recording a rent payment is guarded by optimistic concurrency control against the target `Lease`. Because the rent amount and terms a payment is recorded against are read off a specific version of the lease, and because amending a lease or recording a prior payment both advance the lease's `version`, a client that read the lease earlier may hold a stale view. To close that gap, the request that records a rent payment must carry a non-optional `expected_lease_version` field carrying the client's last observed `version` of the lease. When that value does not equal the lease's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no payment is created. A successful recording itself advances the lease's `version` by one, so a client recording two payments in sequence must re-read the lease (or track the incremented version) between them. This is the only endpoint that takes a version field; no other write requires or accepts one.

### 2.7. Cascading State Consistency and Denormalized Statistics

The platform keeps two denormalized statistics on every tenant that must stay consistent with the underlying tradelines at all times: `reported_on_time_rate_pct`, the tenant's `as_reported` on-time percentage across their effective reported items, and `effective_reported_items`, the count of the tenant's reported items whose `status` is either `REPORTED` or `DISPUTED`. Both are recomputed from scratch on every furnish, retract, correction, or cascade event — never incrementally patched — so that they always reflect the current set of effective tradelines. `reported_on_time_rate_pct` is null when the tenant has no effective reported items, and `effective_reported_items` is zero in that case.

State changes frequently cascade across entities, and each hop independently mutates the entity it touches — refreshing `updated_at` and incrementing `version` where those fields exist. The deepest chain in the system originates at enrolment cancellation: cancelling an `ACTIVE` enrolment terminates the tenant's verified leases, terminating a lease retracts its still-effective tradelines, and retracting those tradelines forces a recompute of the tenant's rate and effective count. Every downstream entity touched by such a cascade is mutated in place, and the tenant statistics are recomputed once the dust settles. These cascades are described in full in the workflow subsections of §3.

### 2.8. Segregation of Duties

Dispute handling enforces a maker–checker separation: the `ComplianceAnalyst` who opens an investigation and the `ComplianceOfficer` who resolves it must be different operators. When an analyst opens an investigation, the server records that analyst's `X-User-ID` as `analyst_user_id` on the dispute. When an officer later resolves the dispute, the server checks that the officer's `X-User-ID` is not equal to that recorded `analyst_user_id`; if they are the same operator, the resolution is rejected with `ERR_SEGREGATION_OF_DUTIES`. Only on a passing check does the server record the officer's `X-User-ID` as `officer_user_id`.

### 2.9. Existence Validation and the Request-Validation Order

For any request that names resources — through a path id or through a foreign-key field in the body — the server validates existence left to right, in the order the identifiers appear, and rejects the first unresolved reference with the matching not-found error (`ERR_TENANT_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_REPORTED_ITEM_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_BACK_REPORT_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`).

Across the whole API, checks are applied in a fixed precedence so that the same request always fails for the same reason. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) authorisation of the role and ownership (`ERR_UNAUTHORIZED`); (3) existence of every referenced resource (the not-found family above); (4) structural request validity — required fields present, enum values in range, and numeric fields within bounds such as a score in the range 300 to 850, a `monthly_due_day` from 1 to 28, cents values at or above zero, and well-formed `YYYY-MM` month and ISO-8601 date strings (`ERR_INVALID_REQUEST`); then the state and business rules specific to each endpoint, which themselves run in a defined order described alongside each workflow in §3. Where several of those endpoint-specific rules could apply to one request, they are evaluated in the priority order stated in their workflow, so that, for example, a lease-verification conflict surfaces before a lower-priority business check on the same call.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Tenants, Landlords, Plans, and Score Ingestion

A platform administrator seeds the reference data the rest of the system depends on. A tenant is onboarded with a legal `full_name`, a contact `email` that must be unique per tenant, and an optional `phone` that defaults to null when omitted. Each tenant also carries two service-maintained figures introduced in §2.7 — the denormalized `reported_on_time_rate_pct` and `effective_reported_items` — which begin null and zero respectively and only move as tradelines are furnished or removed. A landlord or property-management company is onboarded with a `company_name`, an integration `email`, and an optional `contact_name` that defaults to null.

Subscription plans are likewise created by an administrator. A plan has a human-readable `name`, a `tier` that is one of `BASIC`, `PLUS`, or `PREMIUM`, a recurring `monthly_fee_cents` that must be zero or greater, and a `back_reporting_included_months` allowance — the number of historical months that plan bundles free into any back-report — which must also be zero or greater.

Bureau scores are ingested append-only. Each score snapshot names its subject `tenant_id`, the `bureau` that produced the reading (one of `EQUIFAX`, `EXPERIAN`, or `TRANSUNION`), the `score` itself as an integer in the range 300 to 850, and the `as_of_month` the reading reflects in `YYYY-MM` form. Snapshots are never edited after ingestion, which is why they carry no `updated_at` or `version` (see §2.4). A tenant's snapshots can be listed and optionally narrowed to a single `bureau`.

### 3.2. Enrolment, Invoicing, and Activation

A tenant subscribes by enrolling on a plan, supplying the `tenant_id` and the chosen `plan_id`. Enrolment does not by itself grant service: the new enrolment starts in `PENDING_PAYMENT`, its `monthly_fee_cents` is snapshotted from the plan's current fee so that later plan edits cannot change what this tenant owes, and the server simultaneously raises the first invoice — a `SUBSCRIPTION` invoice in `DUE` status whose `amount_cents` equals that snapshotted fee. Enrolments can be listed and filtered by `tenant_id`, `plan_id`, or `status`.

Every invoice records the `enrollment_id` it bills, a `kind` of either `SUBSCRIPTION` or `BACK_REPORT`, an `amount_cents`, a lifecycle `status` of `DUE`, `PAID`, or `VOID`, and a `paid_at` instant that is null until settlement. A `SUBSCRIPTION` invoice also carries the billed `period_month` in `YYYY-MM`, while a `BACK_REPORT` invoice leaves `period_month` null and instead references its originating request through `back_report_request_id` (null on subscription invoices). Invoices can be listed and filtered by `enrollment_id`, `back_report_request_id`, `kind`, or `status`.

Paying an invoice marks it settled: its `status` moves from `DUE` to `PAID` and its `paid_at` is stamped with the current logical clock. Activation of the subscription is driven entirely by this payment rather than by any dedicated endpoint. When the invoice being paid is a `SUBSCRIPTION` invoice and its enrolment is still `PENDING_PAYMENT`, settling it advances the enrolment from `PENDING_PAYMENT` to `ACTIVE`, sets `current_period_start` to the clock's current instant, and sets `current_period_end` to exactly one calendar month after that start (a half-open period used later for proration). Only an enrolment sitting in `PENDING_PAYMENT` activates this way; paying any other invoice simply settles it.

### 3.3. Leases and Landlord Verification

Rent cannot be reported until a lease is proven. A tenant (or an administrator acting operationally) creates a lease naming the `tenant_id`, the verifying `landlord_id`, the normalized `property_address`, the monthly `rent_amount_cents` which must be strictly greater than zero, the `monthly_due_day` on which rent falls due as an integer from 1 to 28, and the term bounds `lease_start` (inclusive) and `lease_end` (exclusive) forming a half-open interval. A new lease is refused if its term overlaps any existing non-terminal lease sharing the same combination of `tenant_id` and `property_address`; because the interval is half-open, a new lease whose `lease_start` equals a prior lease's `lease_end` does not overlap, but any true overlap is rejected with `ERR_LEASE_DATE_OVERLAP`. A fresh lease begins in `verification_status` `PENDING_VERIFICATION`. Leases can be listed and filtered by `tenant_id`, `landlord_id`, or `verification_status`.

Verification is the landlord's exclusive act. The landlord named on the lease submits a `decision` of either `VERIFIED` or `REJECTED`, optionally accompanied by a free-text `note`, and the acting landlord's `X-User-ID` must equal the lease's `landlord_id`. A `VERIFIED` decision moves the lease from `PENDING_VERIFICATION` to `VERIFIED`; a `REJECTED` decision moves it to `REJECTED`; either way the lease's `version` increments by one. Verification is only valid from `PENDING_VERIFICATION` — attempting it on a lease already `VERIFIED`, `REJECTED`, or `TERMINATED` is rejected with `ERR_ALREADY_VERIFIED`. A lease reaches the terminal `TERMINATED` state only through the enrolment-cancellation cascade of §3.8, never by direct request.

### 3.4. Recording Rent Payments

Rent payments are recorded against a lease, ordinarily by the landlord on that lease (an administrator may act operationally). A recording names the `lease_id`, the `period_month` in `YYYY-MM`, the `due_date` on which rent was due for that month, an optional `paid_date` giving when rent was actually paid (null means unpaid or missed), the `amount_paid_cents` the tenant actually paid which must be zero or greater, and the `expected_lease_version` that guards the write under the optimistic-concurrency rule of §2.6. A successful recording creates the payment in `status` `RECORDED` and advances the lease's `version` by one.

At recording time the server stamps the payment's `on_time` flag. If no `paid_date` was supplied, the payment is not on time. Otherwise the payment is on time exactly when the paid date falls on or before the due date plus a five-day grace period, compared at whole-day granularity — a payment made on the fifth day after the due date is still on time, and only a payment later than that is late. Payments can be listed and filtered by `lease_id` or `status`.

### 3.5. Furnishing Tradelines to the Bureaus

Furnishing a recorded payment as a tri-bureau tradeline is the compliance analyst's job (or an administrator's operational override). Before a payment may be furnished, four conditions are checked in order: the payment must still be `RECORDED` and not already furnished (acting on a payment already `REPORTED` is rejected with `ERR_INVALID_STATE`); the lease must be `VERIFIED`, otherwise `ERR_LEASE_NOT_VERIFIED`; the same lease-and-month must not already be covered by a non-retracted tradeline, otherwise `ERR_PERIOD_ALREADY_COVERED`; and the tenant's enrolment must be `ACTIVE`, otherwise `ERR_ENROLLMENT_INACTIVE`. Only when all four hold does furnishing proceed.

Furnishing creates a **reported item** — the tradeline record. It captures the originating `rent_payment_id`, the denormalized `tenant_id` and `lease_id`, the furnished `period_month`, a snapshot of the payment's `on_time` flag, the `amount_reported_cents` sent to the bureaus, a `source` of `MONTHLY` for a directly furnished payment, and a `status` that begins at `REPORTED`. Its `bureau_statuses` object holds one entry per bureau under the keys `EQUIFAX`, `EXPERIAN`, and `TRANSUNION`, each set to `FURNISHED` on creation and each capable of moving to `DELETED` when the tradeline is later retracted. An original tradeline has a null `supersedes_item_id`; that field is set only on a correction's replacement item (see §3.7). The `on_time` snapshot on the reported item is deliberately independent of the payment: a later correction can change the tradeline's `on_time` while the payment's own flag is unchanged. As the tradeline is created, the payment moves from `RECORDED` to `REPORTED`, and the tenant's `reported_on_time_rate_pct` and `effective_reported_items` are recomputed. Reported items can be listed and filtered by `rent_payment_id`, `tenant_id`, `lease_id`, `supersedes_item_id`, or `status`.

Retracting a tradeline is reserved for a compliance officer, who may attach an optional `reason`. Retraction takes a tradeline from `REPORTED` to the terminal `RETRACTED` state, flips every entry in `bureau_statuses` to `DELETED`, and recomputes the tenant's `reported_on_time_rate_pct` and `effective_reported_items`. Because a retracted item is no longer effective, it drops out of both figures.

### 3.6. Back-Reporting Historical Months

A tenant may ask to have past months furnished retroactively by opening a back-report request against a lease, supplying the `lease_id` and a `requested_months` array of `YYYY-MM` strings. Three admissibility rules govern the request. The count of `requested_months` may not exceed the maximum back-reporting horizon of twenty-four months; a longer list is rejected with `ERR_BACK_REPORT_LIMIT_EXCEEDED`. Each individual month must be no older than that same twenty-four-month horizon relative to the current month, must not lie in the future, and must have a `RECORDED` rent payment on the lease; a month failing any of these is rejected with `ERR_BACK_REPORT_MONTHS_INVALID`. And no requested month may already be covered by a non-retracted tradeline, which is rejected with `ERR_PERIOD_ALREADY_COVERED`.

When the request is admissible, the server computes the fee. Let the number of requested months be reduced by the plan's `back_reporting_included_months` allowance, floored at zero, to give the `billable_months`; that is, the billable count is the requested-month count minus the included allowance, or zero if the allowance covers them all. The `fee_cents` is then the billable-month count multiplied by a per-month price of two hundred cents, capped so that the fee never exceeds three thousand cents — the lesser of those two amounts. The request is created in `PENDING`, and a `BACK_REPORT` invoice for `fee_cents` in `DUE` status is raised on the tenant's enrolment. Back-report requests can be listed and filtered by `lease_id` or `status`.

A compliance officer decides the request with a `decision` of `APPROVED` or `REJECTED`, plus an optional `note`. Approval requires that the tenant's enrolment be `ACTIVE` (otherwise `ERR_ENROLLMENT_INACTIVE`), that the `BACK_REPORT` fee invoice already be `PAID` (otherwise `ERR_INVOICE_UNPAID`), and that no requested month has become covered by a non-retracted tradeline since the request was created (otherwise `ERR_PERIOD_ALREADY_COVERED`); on success the request moves from `PENDING` to `APPROVED`. A rejection instead moves it from `PENDING` to the terminal `REJECTED` and voids the `BACK_REPORT` fee invoice.

Completion is the analyst's furnishing step and is only valid from `APPROVED`. It requires the lease to still be `VERIFIED` (otherwise `ERR_LEASE_NOT_VERIFIED`). For each requested month it creates a reported item with `source` `BACK_REPORT` and `status` `REPORTED` drawn from that month's rent payment, and moves that payment from `RECORDED` to `REPORTED`. The request then moves from `APPROVED` to the terminal `COMPLETED`, and the tenant's `reported_on_time_rate_pct` and `effective_reported_items` are recomputed to take in the newly furnished months.

### 3.7. Disputes, Investigation, and Correction

A tenant who believes a tradeline is wrong files a dispute against it, naming the `reported_item_id` and a `reason_code` of `NOT_MINE`, `INCORRECT_AMOUNT`, `INCORRECT_STATUS`, or `PAID_ON_TIME`. Two conditions gate filing. The targeted tradeline must currently be `REPORTED`; a tradeline that is already `DISPUTED`, `CORRECTED`, or `RETRACTED` cannot be disputed and is rejected with `ERR_ITEM_NOT_DISPUTABLE`. And the dispute window must still be open: the current logical clock must be no later than the tradeline's `created_at` plus a thirty-day dispute window, otherwise `ERR_DISPUTE_WINDOW_CLOSED`. On a valid filing the server creates the dispute in `OPEN` status with its `tenant_id` taken from the filer's `X-User-ID`, and moves the tradeline from `REPORTED` to `DISPUTED`, incrementing that item's `version` by one. A `DISPUTED` tradeline still counts as effective, so the tenant's `effective_reported_items` and rate are unchanged by the mere act of filing. Disputes can be listed and filtered by `reported_item_id`, `tenant_id`, or `status`.

An analyst opens an investigation, moving the dispute from `OPEN` to `INVESTIGATING`; the server records that analyst's `X-User-ID` as `analyst_user_id` and stamps an `investigation_deadline` of the current clock plus a thirty-day investigation period. Resolution is the officer's act and is only valid from `INVESTIGATING`, subject to the segregation-of-duties rule of §2.8 (`ERR_SEGREGATION_OF_DUTIES` when the resolving officer is the same operator who investigated). The officer supplies a `resolution` of either `CORRECTED` or `UPHELD`, an optional `note` recorded as `resolution_note`, and — for a correction — optional corrected values `corrected_on_time` and `corrected_amount_cents` (each may be omitted or sent as null). A `CORRECTED` resolution moves the dispute to the terminal `RESOLVED_CORRECTED`, moves the disputed tradeline from `DISPUTED` to `CORRECTED`, and creates a superseding replacement tradeline in `REPORTED` status whose `supersedes_item_id` points back at the corrected original, inheriting the original's `source` and carrying `on_time` and `amount_reported_cents` from the supplied `corrected_on_time` and `corrected_amount_cents` respectively; when a corrected value is omitted or null, the superseding tradeline inherits that field's value from the original (its `on_time` or its `amount_reported_cents`). Because the corrected item leaves the effective set as the superseding item enters it, the tenant's effective count nets out unchanged, but the rate is recomputed to reflect the corrected on-time value. An `UPHELD` resolution instead moves the dispute to the terminal `RESOLVED_UPHELD` and reinstates the tradeline from `DISPUTED` back to `REPORTED`, restoring its `bureau_statuses` to `FURNISHED`, with the rate recomputed. Either resolution stamps the officer's `X-User-ID` as `officer_user_id`.

A tenant may also withdraw their own dispute, provided the acting `X-User-ID` equals the dispute's `tenant_id`. Withdrawal is valid from either `OPEN` or `INVESTIGATING`, moves the dispute to the terminal `WITHDRAWN`, reinstates the tradeline from `DISPUTED` back to `REPORTED`, and recomputes the rate. In every reinstatement path — upheld or withdrawn — the tradeline returns to the exact `REPORTED` state it can be disputed from again, forming the cyclic revision loop `REPORTED → DISPUTED → REPORTED`.

### 3.8. Cancellation, Settlement, and Cascade Termination

A tenant cancels their enrolment, which is always allowed from either `PENDING_PAYMENT` or `ACTIVE` and drives the enrolment to the terminal `CANCELLED` while stamping `cancelled_at` with the current logical clock. Any still-`DUE` invoices on the enrolment are voided.

The financial treatment depends on where the enrolment stood. Cancelling from `PENDING_PAYMENT` — where no period was ever paid — leaves `refund_cents` and `earned_cents` both at zero. Cancelling from `ACTIVE` triggers a prorated settlement. Take the length of the current period as the whole-day count from `current_period_start` to `current_period_end`. Take the days used as the whole-day count from `current_period_start` to `cancelled_at`, clamped to lie between zero and the period length inclusive. The amount actually paid for this period is the enrolment's `monthly_fee_cents` if the current period's `SUBSCRIPTION` invoice is `PAID`, and zero otherwise. The `earned_cents` is the `monthly_fee_cents` multiplied by days used divided by period length, rounded half up to whole cents. The `refund_cents` is the paid-this-period amount minus the earned amount, floored at zero so it is never negative. When the period was paid, earned plus refund exactly equals the paid amount, conserving the money.

Cancelling from `ACTIVE` also unleashes the deepest cascade in the system. Every lease of this tenant currently in `VERIFIED` transitions to the terminal `TERMINATED`. Each such termination in turn retracts that lease's still-effective tradelines: every reported item on the lease whose `status` is `REPORTED` or `DISPUTED` moves to `RETRACTED` with its `bureau_statuses` all set to `DELETED`. And because those retractions change the effective set, the tenant's `reported_on_time_rate_pct` and `effective_reported_items` are recomputed once the cascade settles. Leases that were merely `PENDING_VERIFICATION` or `REJECTED`, and tradelines already `RETRACTED` or `CORRECTED`, are untouched.

### 3.9. Credit Summary and Score Tracking

The credit summary is the tenant-facing rollup, readable by the tenant or an administrator. It returns the `tenant_id`, both on-time-rate variants as `on_time_rate_as_paid_pct` and `on_time_rate_as_reported_pct`, the `total_payments` count, the `effective_reported_items` count, and a `latest_scores` object.

The two rate variants measure different populations and can legitimately diverge. The **as-paid** rate ranges over every rent payment recorded on any of the tenant's leases regardless of whether it was ever furnished: if the tenant has no recorded payments the variant is null, otherwise it is one hundred times the number of on-time payments divided by the total number of payments, rounded half up to a whole percent. `total_payments` is that denominator — the count of all recorded payments. The **as-reported** rate ranges only over the tenant's effective tradelines, those reported items whose `status` is `REPORTED` or `DISPUTED`: if there are none the variant is null, otherwise it is one hundred times the number of effective tradelines whose `on_time` snapshot is true divided by the count of effective tradelines, rounded half up to a whole percent. `effective_reported_items` is that denominator. The two diverge whenever the furnished subset differs from the full payment set — for instance when some payments were never furnished, or when a correction has superseded an original.

The `latest_scores` object reports, for each of `EQUIFAX`, `EXPERIAN`, and `TRANSUNION`, the most recent `score` on file for the tenant from that bureau, or null when that bureau has no snapshot for the tenant. "Most recent" is decided by ranking the tenant's snapshots for that bureau by `as_of_month` descending and breaking ties by `created_at` descending — never by `id` — and taking the winning snapshot's `score`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch, list, or modify an existing resource — including the action endpoints that drive a state machine — return `200 OK`. All paths are mounted under the `/api` prefix. Request and response payloads are not repeated here; reconstruct them from the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/tenants` | Onboard a tenant | PlatformAdmin |
| GET | `/api/tenants/{id}` | Fetch a tenant | PlatformAdmin, Tenant |
| GET | `/api/tenants/{id}/credit-summary` | Computed on-time rates and latest scores | PlatformAdmin, Tenant |
| GET | `/api/tenants/{id}/score-snapshots` | List a tenant's score snapshots | PlatformAdmin, Tenant |
| POST | `/api/landlords` | Onboard a landlord / property manager | PlatformAdmin |
| GET | `/api/landlords/{id}` | Fetch a landlord | PlatformAdmin, Landlord |
| POST | `/api/subscription-plans` | Create a subscription plan | PlatformAdmin |
| GET | `/api/subscription-plans/{id}` | Fetch a plan | PlatformAdmin, Tenant |
| POST | `/api/enrollments` | Enrol a tenant on a plan; issues first invoice | Tenant, PlatformAdmin |
| GET | `/api/enrollments/{id}` | Fetch an enrolment | Tenant, PlatformAdmin |
| GET | `/api/enrollments` | List/filter enrolments | Tenant, PlatformAdmin |
| POST | `/api/enrollments/{id}/cancel` | Cancel an enrolment; settlement + cascade | Tenant |
| POST | `/api/leases` | Create a lease (pending verification) | Tenant, PlatformAdmin |
| GET | `/api/leases/{id}` | Fetch a lease | Tenant, Landlord, PlatformAdmin |
| GET | `/api/leases` | List/filter leases | Tenant, Landlord, PlatformAdmin |
| POST | `/api/leases/{id}/verify` | Landlord verifies or rejects a lease | Landlord, PlatformAdmin |
| POST | `/api/rent-payments` | Record a rent payment (OCC on lease) | Landlord, PlatformAdmin |
| GET | `/api/rent-payments/{id}` | Fetch a rent payment | Tenant, Landlord, PlatformAdmin |
| GET | `/api/rent-payments` | List/filter rent payments | Tenant, Landlord, PlatformAdmin |
| POST | `/api/rent-payments/{id}/report` | Furnish a payment as a tri-bureau tradeline | ComplianceAnalyst, PlatformAdmin |
| GET | `/api/reported-items/{id}` | Fetch a reported tradeline item | Tenant, ComplianceAnalyst, ComplianceOfficer, PlatformAdmin |
| GET | `/api/reported-items` | List/filter reported items | Tenant, ComplianceAnalyst, ComplianceOfficer, PlatformAdmin |
| POST | `/api/reported-items/{id}/retract` | Retract a furnished tradeline | ComplianceOfficer |
| POST | `/api/disputes` | File a dispute against a reported item | Tenant |
| GET | `/api/disputes/{id}` | Fetch a dispute | Tenant, ComplianceAnalyst, ComplianceOfficer, PlatformAdmin |
| GET | `/api/disputes` | List/filter disputes | Tenant, ComplianceAnalyst, ComplianceOfficer, PlatformAdmin |
| POST | `/api/disputes/{id}/investigate` | Analyst opens an investigation | ComplianceAnalyst |
| POST | `/api/disputes/{id}/resolve` | Officer resolves the dispute (SoD enforced) | ComplianceOfficer |
| POST | `/api/disputes/{id}/withdraw` | Tenant withdraws their dispute | Tenant |
| POST | `/api/back-report-requests` | Request back-reporting; computes fee, issues invoice | Tenant, PlatformAdmin |
| GET | `/api/back-report-requests/{id}` | Fetch a back-report request | Tenant, ComplianceAnalyst, ComplianceOfficer, PlatformAdmin |
| GET | `/api/back-report-requests` | List/filter back-report requests | Tenant, ComplianceAnalyst, ComplianceOfficer, PlatformAdmin |
| POST | `/api/back-report-requests/{id}/decision` | Officer approves or rejects a request | ComplianceOfficer |
| POST | `/api/back-report-requests/{id}/complete` | Analyst furnishes approved months | ComplianceAnalyst |
| GET | `/api/invoices/{id}` | Fetch an invoice | Tenant, PlatformAdmin |
| GET | `/api/invoices` | List/filter invoices | Tenant, PlatformAdmin |
| POST | `/api/invoices/{id}/pay` | Pay an invoice; activates enrolment on first sub payment | Tenant, PlatformAdmin |
| POST | `/api/score-snapshots` | Ingest a bureau score reading (append-only) | PlatformAdmin |
| POST | `/api/_clock/set_current_utc` | Advance the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_TENANT_NOT_FOUND` | 404 |
| `ERR_LANDLORD_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_REPORTED_ITEM_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_BACK_REPORT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_ALREADY_VERIFIED` | 409 |
| `ERR_LEASE_NOT_VERIFIED` | 409 |
| `ERR_ITEM_NOT_DISPUTABLE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 |
| `ERR_LEASE_DATE_OVERLAP` | 409 |
| `ERR_PERIOD_ALREADY_COVERED` | 409 |
| `ERR_BACK_REPORT_LIMIT_EXCEEDED` | 422 |
| `ERR_BACK_REPORT_MONTHS_INVALID` | 422 |
| `ERR_ENROLLMENT_INACTIVE` | 402 |
| `ERR_INVOICE_UNPAID` | 402 |
| `ERR_CLOCK_BEFORE_CURRENT` | 422 |

