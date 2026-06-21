# Health Insurance Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a Health Insurance Marketplace enrollment platform, modeled on the public-exchange experience familiar from systems such as HealthCare.gov. The platform guides a household from initial composition through income capture, federal subsidy determination, plan shopping, enrollment, and — at the close of the plan year — reconciliation of the advance premium tax credit actually drawn against the credit the household was ultimately entitled to.

The business problem is fundamentally one of reconciliation against a moving income figure. A household projects its annual income when it shops; the Marketplace computes an Advance Premium Tax Credit (APTC) subsidy on that projection and advances it month by month against the family's premium; and only at year end does the realized income become known, at which point the advanced credit must be trued up — the household either repays an excess or receives an additional credit. Layered on top of this are temporal rules: applications submitted during Open Enrollment receive a clean first-of-month coverage start, while applications filed during a Special Enrollment Period triggered by a qualifying life event follow event-specific effective-date rules, some of them retroactive. The platform must hold all of these determinations consistent even as household members are added or their incomes corrected, which is why concurrency control sits at the heart of the submission and enrollment flows.

Three classes of actor participate: consumers enrolling their own families, certified assisters who act on a family's behalf, and Marketplace operators who run determinations, adjudicate Special Enrollment requests, effectuate coverage, and perform year-end reconciliation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which that user is acting. The system recognizes exactly three roles, spelled precisely as `Applicant`, `Navigator`, and `MarketplaceAdmin`. If either header is missing, or if `X-User-Role` is not one of these three declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When a request is authenticated but the acting role is not permitted to perform the requested operation, it is rejected with `ERR_FORBIDDEN` (HTTP 403).

A separate ownership layer applies to consumer-owned data. When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque consumer identifier; the server records it as the `applicant_user_id` on any household the applicant creates but does not treat it as the `id` of any persisted entity. Ownership of a household, and transitively of the applications and enrollments beneath it, is determined by comparing the acting `Applicant`'s `X-User-ID` to the owning household's `applicant_user_id`. An `Applicant` who attempts a mutation on a household, application, or enrollment subtree they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `Navigator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; a `Navigator` is a certified assister who may exercise the full applicant write surface and read everything, and who is explicitly exempt from the `applicant_user_id` ownership comparison — a Navigator may assist any household. When `X-User-Role` is `MarketplaceAdmin`, `X-User-ID` is again an opaque operator identifier not tied to any entity; the `MarketplaceAdmin` is the Marketplace operator responsible for running determinations, reviewing Special Enrollment requests, registering plans, effectuating and marking coverage delinquent, performing reconciliation, and driving the test clock. All three roles may issue the read (GET) operations described in §4, with the ownership scoping above governing which households an `Applicant` may see.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. Supplied values that fall outside these bounds are silently clamped rather than rejected — a `limit` below 1 is raised to 1, a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0; only a non-integer `limit` or `offset` is rejected, with `ERR_INVALID_REQUEST` (HTTP 422).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system — `Household`, `HouseholdMember`, `Application`, `EligibilityDetermination`, `Enrollment`, `SepRequest`, and `ReconciliationRecord` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID with no type prefix. It is identity only and is never used as a business-decision input.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations that arrive as a cascaded side effect of an operation on another resource.
- `version` (integer): a system-managed counter that starts at 1 and increments by exactly 1 on every mutation of the resource.

The `HealthPlan` catalog entity is the sole exception. A `HealthPlan` carries only `id` (a server-minted UUID) and `created_at`; it has no `updated_at` and no `version`, because catalog plans are immutable once registered.

### 2.5. Derived-Field Reconciliation and Hierarchical Consistency

Several fields are not supplied by clients but are computed and kept reconciled by the server. A `Household` exposes three such derived fields — `household_magi_cents`, `fpl_percent`, and `countable_size` — all of which begin at 0 before any member exists and are recomputed every time a member is added, updated, or removed. Whenever such a recompute occurs, it is a genuine mutation of the household: `updated_at` is refreshed and `version` increments by 1. Because adding or editing a member changes the household's income picture, the member operation cascades into the household, and the household version advances as a result; this cascade is the linchpin of the concurrency rules in §2.7.

When a single operation mutates more than one entity, every affected entity is individually mutated — its `updated_at` refreshed and its `version` incremented. The system performs these reconciliations immediately and synchronously within the triggering request; there is no eventual-consistency lag.

### 2.6. Nested Resource Retrieval and Referential Existence

The API validates path identifiers strictly left to right. When an endpoint path names more than one resource (for example, a member beneath a household), the system confirms the existence of each identifier in order, and the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) before any deeper lookup or business rule is evaluated. This existence check applies to every endpoint that takes path parameters.

Foreign-key references carried in a request body are checked separately. When a body field such as `household_id`, `application_id`, `plan_id`, or `enrollment_id` points to a resource that does not exist, the request is rejected with `ERR_REFERENCED_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency on Household-Derived State

Two write operations depend on a household's income snapshot being current, and both protect that dependency with an optimistic-concurrency token keyed to the household's `version`.

Submitting an application freezes the household MAGI that the subsequent determination will consume. The submit request must carry `expected_household_version`, a non-optional field holding the `version` of the `Household` the applicant last observed. If a member edit has advanced the household's `version` since the applicant read it, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so that a determination is never run on an income snapshot the applicant never saw.

Creating an enrollment is the create-with-supersede case: the new enrollment locks in a subsidy figure drawn from the determination, so the system requires the applicant's view of the household to be current. The enrollment-create request must carry `expected_household_version`, a non-optional field holding the household `version` the applicant last observed when reviewing their determination. If the household `version` has advanced since then — for instance, because a member income edit triggered a MAGI and FPL recompute that would change the qualified APTC — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field, and operations not described here perform no concurrency check.

### 2.8. Monetary Precision, Percentages, and Rounding

All monetary amounts are stored and exchanged as integer cents; the field names that carry them end in `_cents`. Because inputs are already integer cents, summations of income perform no rounding. Where a calculation divides — computing a monthly contribution from an annual figure, or prorating a partial first month — the result is rounded to whole cents using the round-half-up convention. The household's `fpl_percent` (and the determination's snapshot of it) is carried to exactly two decimal places, round half up. The expected-contribution `applicable_pct` is carried to exactly six decimal places, round half up. Dates produced by the system — coverage effective dates and the SEP window-close date — are plain calendar dates formatted `YYYY-MM-DD`.

### 2.9. The Server Clock

Time-dependent computations — the stamp written when an application is submitted, the open/closed test for a Special Enrollment filing window, and the derivation of coverage effective dates — all read a single server-held current UTC clock. An administrative test-driving capability allows the clock to be set to a supplied instant via the `to_iso8601` field, after which all subsequent time-dependent computations observe that value.

## 3. Business Logic & Workflows

### 3.1. Building the Household and Capturing Income

Everything begins with a **Household**, the aggregate root that an `Applicant` (or an assisting `Navigator`) creates by declaring the `coverage_year` it is shopping for — for example, 2026 — and the `rating_area`, a geographic code such as `RA01` that determines which benchmark plan prices the subsidy. On creation the server stamps `applicant_user_id` from the caller's `X-User-ID`, and initializes the three derived income fields — `household_magi_cents`, `fpl_percent`, and `countable_size` — to 0.

Members are then added one at a time. Each **HouseholdMember** carries a `full_name`, a `relationship` to the primary applicant, and a `tax_filing_status`. The `relationship` is one of `PRIMARY`, `SPOUSE`, or `DEPENDENT`, and a household may contain exactly one `PRIMARY` member — an attempt to add a second `PRIMARY` is rejected with `ERR_DUPLICATE_PRIMARY` (HTTP 409). The `tax_filing_status` is one of `FILER`, `JOINT_FILER`, `DEPENDENT_FILER`, or `DEPENDENT_NONFILER`, and it governs whether a member's income counts toward the household total. A member also supplies `annual_income_cents` — the member's projected annual MAGI income, which must be at least 0 and defaults to 0 if omitted — and `applies_for_coverage`, a boolean (defaulting to true) declaring whether the member is actually seeking coverage. The member record also exposes a computed boolean `is_countable_income`. When a member's income or status is later corrected, the editable attributes are `full_name`, `tax_filing_status`, `annual_income_cents`, and `applies_for_coverage`; on update both the member's own `version` and the household's `version` increment, and the household income fields recompute. The path variables `id` (the household) and `member_id` (the member) address these operations, and member lists are retrievable by walking back from the household.

Each member edit recomputes the household's income picture. The household's countable income is the sum of `annual_income_cents` over the **countable members**. A member is countable for income unless it is simultaneously a `DEPENDENT_NONFILER` and has `annual_income_cents` below the dependent filing threshold of $14,600 (that is, below 1,460,000 cents); the member's `is_countable_income` flag mirrors exactly this predicate, being false only for a `DEPENDENT_NONFILER` whose income is under that threshold and true otherwise. The household's `household_magi_cents` is the sum of `annual_income_cents` across the countable members; because all operands are integer cents, no rounding occurs. Separately, `countable_size` is the count of members whose `applies_for_coverage` is true — note that a `DEPENDENT_NONFILER` excluded from the income sum still adds to `countable_size` if it is applying for coverage, because `countable_size` is the size used as the denominator in the Federal Poverty Level calculation.

The household's `fpl_percent` expresses its income as a percentage of the Federal Poverty Level for its countable size. The FPL annual figure in cents is the base poverty level of $15,000 (1,500,000 cents) for a household of one, plus an additional $5,300 (530,000 cents) for each person beyond the first — that is, the base plus 530,000 cents multiplied by one less than `countable_size`. The `fpl_percent` is then the household MAGI divided by that FPL annual figure, multiplied by 100, rounded half up to two decimal places. When `countable_size` is 0, `fpl_percent` is 0.

### 3.2. Filing the Application and Special Enrollment Requests

An **Application** is the vehicle that carries a household into coverage. It is created in `DRAFT` status against a `household_id`, and it declares its `enrollment_window`: `OEP` for Open Enrollment or `SEP` for a Special Enrollment Period. While `DRAFT`, the application's `submitted_at` is null and its `sep_request_id` is null. Applications are listable by their `household_id` and by `status`.

A `DRAFT` application filed under the `SEP` window cannot proceed until a qualifying life event is approved. The applicant files a **SepRequest** against the `application_id`, declaring a `qualifying_event_type` — one of `BIRTH`, `ADOPTION`, `MARRIAGE`, `LOSS_OF_COVERAGE`, or `PERMANENT_MOVE` — and the `event_date` on which the event occurred (formatted `YYYY-MM-DD`). The request is created in `PENDING` status, and the system computes its `window_close_date`: the last date on which the applicant may still file under this SEP, equal to the `event_date` plus 60 calendar days. SEP requests are listable by `application_id` and by `status`.

A `MarketplaceAdmin` reviews each `PENDING` request, which forks into one of two terminal outcomes. Approval moves the request from `PENDING` to `APPROVED` and is permitted only when the request is still `PENDING`, when the linked application is still in `DRAFT` (the SEP must be resolved before the application is submitted), and when the current clock date falls on or before the request's `window_close_date` — that is, the filing window is still open. If approval is attempted after the window has closed, it is rejected with `ERR_SEP_WINDOW_CLOSED` (HTTP 409). Denial moves a `PENDING` request to `DENIED`; a denied request grants no window, so the linked SEP application can never submit. Both transitions increment the SEP request's `version`.

When the application is submitted, it advances from `DRAFT` to `SUBMITTED`. Submission is permitted only when the application is currently `DRAFT`, when the referenced household has a `countable_size` of at least 1 (meaning at least one `PRIMARY` member exists; a household whose `countable_size` is 0 is rejected with `ERR_INVALID_STATE`, HTTP 409), and — for `SEP`-window applications only — when an `APPROVED` `SepRequest` exists for this application; an `OEP` application skips that SEP precondition entirely. A `SEP` application submitted without an approved request is rejected with `ERR_SEP_NOT_APPROVED` (HTTP 409). Submission also enforces the optimistic-concurrency rule of §2.7: the request carries `expected_household_version`, and a mismatch with the household's current `version` yields `ERR_STALE_VERSION` (HTTP 412). On a successful submit the server sets `submitted_at` to the current UTC clock, sets the application's `sep_request_id` to the `id` of the approved `SepRequest` when the window is `SEP`, increments the household's `version` by 1, and increments the application's `version` by 1.

A submitted application may be cancelled, and so may a draft one: cancellation moves an application that is currently in `DRAFT` or in `SUBMITTED` to the terminal `CANCELLED` state and increments the application's `version`.

### 3.3. Running the Eligibility Determination

Once an application is `SUBMITTED`, a `MarketplaceAdmin` runs the eligibility determination, which advances the application from `SUBMITTED` to `DETERMINED` and creates an **EligibilityDetermination** linked to the `application_id` (one active determination per application). The determination snapshots the household's `fpl_percent` at this instant into `fpl_percent_snapshot` (two decimals) and from it computes four results: `applicable_pct`, `max_aptc_monthly_cents`, `csr_tier`, and the boolean `is_subsidy_eligible`. The application's `version` increments. A determination requires that a benchmark plan exist (see below); if none does, the determination fails with `ERR_NO_BENCHMARK_PLAN` (HTTP 409).

The **applicable percentage** is the share of income the household is expected to contribute toward the benchmark premium, interpolated across Federal Poverty Level bands from the snapshot. Let *p* be `fpl_percent_snapshot`. If *p* is at most 150, the applicable percentage is 0. If *p* is greater than 150 and at most 200, it rises linearly from 0 at 150 to 0.02 at 200 — that is, 0 plus the fraction (p − 150) ÷ (200 − 150) multiplied by (0.02 − 0). If *p* is greater than 200 and at most 250, it is 0.02 plus (p − 200) ÷ (250 − 200) multiplied by (0.04 − 0.02). If *p* is greater than 250 and at most 300, it is 0.04 plus (p − 250) ÷ (300 − 250) multiplied by (0.06 − 0.04). If *p* is greater than 300 and at most 400, it is 0.06 plus (p − 300) ÷ (400 − 300) multiplied by (0.085 − 0.06). If *p* is greater than 400, it is the cap rate of 0.085, with no cliff above 400 percent. Every band's upper edge is inclusive: a snapshot of exactly 200 yields 0.02 (not the next band's interpolation), and a snapshot of exactly 150 yields 0. The result is rounded half up to six decimal places.

The **maximum monthly APTC** is the benchmark premium less the household's expected monthly contribution, floored at zero. The benchmark premium is the `gross_premium_cents` of the single benchmark plan for the household's rating area and coverage year (the one Silver plan flagged as the Second Lowest Cost Silver Plan; see §3.4). The monthly contribution is the household MAGI multiplied by the applicable percentage, divided by 12, rounded half up to whole cents. The maximum monthly APTC stored in `max_aptc_monthly_cents` is the larger of 0 and the benchmark premium minus that monthly contribution. The determination's `is_subsidy_eligible` flag is true exactly when `max_aptc_monthly_cents` is greater than 0.

The **cost-sharing-reduction tier** in `csr_tier` is also drawn from the snapshot *p*. When *p* is at least 100 and at most 150, the tier is `CSR94` — the top "CSR Plus" tier. When *p* is at most 200 but outside the `CSR94` band — that is, *p* is below 100 or *p* is greater than 150 and at most 200 — the tier is `CSR87`; the bands are tested in order, so any snapshot at or below 200 that is not in the `CSR94` band falls into `CSR87`, including a snapshot below 100. When *p* is greater than 200 and at most 250, the tier is `CSR73`. Otherwise — when *p* is above 250 — the tier is `NONE`. The 150 boundary is inclusive in the `CSR94` band: a snapshot of exactly 150 yields `CSR94`, while 150.01 yields `CSR87`. The tier is determined here regardless of plan; cost-sharing reductions only physically attach when the member subsequently enrolls in a Silver plan.

An income correction after determination is handled by reopening the application: an application that is currently `DETERMINED` and that has no enrollment yet may be reverted from `DETERMINED` back to `DRAFT`. Reopening deletes the application's `EligibilityDetermination` as a compensating action, clears `submitted_at` back to null, and increments the application's `version`. This branching-with-revert path is what forces a fresh determination after a member's income is corrected.

### 3.4. The Plan Catalog

A `MarketplaceAdmin` populates the plan catalog. Each **HealthPlan** is registered with the `rating_area` and `coverage_year` it is offered in, a `metal_tier` of `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM`, and a `gross_premium_cents` — the full monthly premium before any APTC, which must be greater than 0. A plan may be flagged with `is_slcsp_benchmark` (defaulting to false); exactly one Silver plan per rating area and coverage year should carry this flag, marking it as the Second Lowest Cost Silver Plan whose premium anchors the APTC calculation. On registration the server computes `csr_eligible`, which is true exactly when the plan's `metal_tier` is `SILVER`, because cost-sharing reductions attach only to Silver plans. Plans are shoppable by filtering on `rating_area`, `coverage_year`, and `metal_tier`.

### 3.5. Enrolling in Coverage

Enrollment is where a determined application becomes coverage. An `Applicant` creates an **Enrollment** by supplying the `application_id`, the chosen `plan_id`, and optionally `elected_aptc_monthly_cents` — the APTC amount the applicant elects to apply each month, which must be at least 0 and defaults to 0. The request also carries `expected_household_version` per the concurrency rule of §2.7. Creating the enrollment advances the application from `DETERMINED` to `ENROLLED` and increments the application's `version`. The new enrollment is born with `lifecycle_status` of `PENDING_EFFECTUATION` and `payment_status` of `AWAITING_BINDER`.

Several preconditions guard the create. The application must currently be `DETERMINED`. The selected plan's `rating_area` and `coverage_year` must both match the household's; a mismatch is rejected with `ERR_PLAN_AREA_MISMATCH` (HTTP 409). The household must have no existing non-terminated enrollment — that is, no enrollment whose `lifecycle_status` is `PENDING_EFFECTUATION` or `ACTIVE` — whose coverage interval overlaps the new one for the same coverage year; coverage intervals run from the effective date to the end of the coverage year and are closed on both ends, so any shared day collides, and a collision is rejected with `ERR_OVERLAPPING_COVERAGE` (HTTP 409). The elected APTC must not exceed the determination's `max_aptc_monthly_cents`; an election above that ceiling is rejected with `ERR_APTC_EXCEEDS_MAX` (HTTP 409). And the carried `expected_household_version` must match the household's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) otherwise.

Creating the enrollment computes its applied subsidy, its premiums, its effective date, and its first-month charge. The **applied APTC** in `applied_aptc_monthly_cents` is the smallest of three figures: the elected amount, the determination's `max_aptc_monthly_cents`, and the plan's `gross_premium_cents`. The **net monthly premium** in `net_premium_monthly_cents` is the plan's `gross_premium_cents` minus the applied APTC. Enrollments are listable by `application_id` and by `plan_id`.

The **effective date**, stored in `effective_date`, depends on how the application was filed. For an `OEP` application, coverage begins on the first day of the month following the month of `submitted_at` (interpreting `submitted_at` by its UTC date). For a `SEP` application, the rule branches on the approved request's `qualifying_event_type`. When the event is `BIRTH` or `ADOPTION`, the effective date is retroactive to the `event_date` itself. When the event is `MARRIAGE` or `PERMANENT_MOVE`, coverage begins prospectively on the first day of the month following the submission month, exactly as for OEP. When the event is `LOSS_OF_COVERAGE`, the regular cutoff rule applies: take the day-of-month of `submitted_at`; the base date is the first day of the month following the submission month; if that day-of-month is at most 15 the effective date is the base date, and if it is greater than 15 the effective date is one month after the base date. A `BIRTH` or `ADOPTION` SEP can therefore produce a mid-month start; every other path produces a first-of-month start.

The **first-month premium** prorates the net premium across the days actually covered in the first month. Let the number of days in the effective date's month be the month length, and let the effective day be the day-of-month of the effective date. If the effective day is 1, the coverage spans the whole month and `first_month_premium_cents` equals `net_premium_monthly_cents` with no proration. Otherwise the covered days are the month length minus the effective day plus 1; the daily rate is the net monthly premium divided by the month length as an exact rational; and `first_month_premium_cents` is the daily rate multiplied by the covered days, rounded half up to whole cents (the rounding is applied once, after multiplying the daily rate by the covered days). A mid-month effective date — such as the one a retroactive `BIRTH` SEP produces — therefore yields a partial, prorated first month that diverges from the full net monthly premium.

### 3.6. Effectuation, Payment, and Termination

An enrollment carries two independent state dimensions that evolve separately. The **payment dimension** (`payment_status`) tracks the binder premium. The applicant pays the binder, moving the enrollment from `AWAITING_BINDER` to `PAID`; this transition is permitted only while `payment_status` is `AWAITING_BINDER`. A `MarketplaceAdmin` may later mark a paid enrollment delinquent, moving `payment_status` from `PAID` to `DELINQUENT`, permitted only while it is `PAID`. Each payment-dimension transition increments the enrollment's `version`.

The **lifecycle dimension** (`lifecycle_status`) tracks coverage activation. A `MarketplaceAdmin` effectuates coverage, moving `lifecycle_status` from `PENDING_EFFECTUATION` to `ACTIVE`; effectuation is permitted only when `lifecycle_status` is `PENDING_EFFECTUATION` and is gated on the payment dimension — the binder must already be paid, so `payment_status` must be `PAID` at that moment. An applicant may terminate coverage: a `PENDING_EFFECTUATION` enrollment or an `ACTIVE` enrollment may be moved to the terminal `TERMINATED` state. Each lifecycle-dimension transition increments the enrollment's `version`.

### 3.7. Year-End Reconciliation

At the close of the plan year a `MarketplaceAdmin` reconciles the credit actually advanced against the credit the household was entitled to, by creating a **ReconciliationRecord** against an `enrollment_id`. The record carries the realized income in `actual_annual_magi_cents` and `months_enrolled`, the number of months coverage was active during the year, which must be between 1 and 12 inclusive. From these it computes three results: `advanced_aptc_total_cents`, `allowed_aptc_total_cents`, and `settlement_cents`.

The **advanced total** is the estimated rollup of what was actually advanced during the year: the enrollment's `applied_aptc_monthly_cents`, drawn from the enrollment-time determination on projected MAGI, multiplied by `months_enrolled`. The **allowed total** is the reconciled figure, recomputed from realized income. Using the same FPL constants together with the linked household's current `countable_size` and the benchmark premium resolved at reconciliation time — the `gross_premium_cents` of the current SLCSP benchmark plan for the household's `rating_area` and `coverage_year`, taken as 0 if no such benchmark plan currently exists — recompute the FPL percentage from `actual_annual_magi_cents` (the realized annual MAGI divided by the FPL annual figure, multiplied by 100, rounded half up to two decimals); from that recompute the applicable percentage by the same band interpolation of §3.3; recompute the monthly contribution as the realized annual MAGI multiplied by that applicable percentage, divided by 12, rounded half up to whole cents; take the allowed monthly APTC as the larger of 0 and the benchmark premium minus that contribution; and multiply the allowed monthly figure by `months_enrolled` to obtain `allowed_aptc_total_cents`. The **settlement** in `settlement_cents` is the advanced total minus the allowed total: a positive settlement is an amount the household must repay, while a negative settlement is an additional credit owed to the household. Because realized income generally differs from the projected income used at enrollment, the allowed total generally differs from the advanced total and the settlement is nonzero. Reconciliation records are listable by `enrollment_id`.

### 3.8. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the most fundamental failures surface first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then the role-permission check (`ERR_FORBIDDEN`), then, for an `Applicant` acting on owned resources, the ownership check (`ERR_NOT_RESOURCE_OWNER`). Existence of path-referenced resources comes next, left to right (`ERR_NOT_FOUND`), followed by existence of foreign-key references in the body (`ERR_REFERENCED_NOT_FOUND`). For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`). Schema validation of the body follows — required fields present, enums valid, and integers non-negative where constrained (`ERR_INVALID_REQUEST`). Only after these structural checks do the domain-specific business rules apply: the single-`PRIMARY` rule (`ERR_DUPLICATE_PRIMARY`), the plan area-and-year match (`ERR_PLAN_AREA_MISMATCH`), the SEP filing-window check (`ERR_SEP_WINDOW_CLOSED`), the SEP-approval-before-submit check (`ERR_SEP_NOT_APPROVED`), the benchmark-plan requirement (`ERR_NO_BENCHMARK_PLAN`), the overlapping-coverage check (`ERR_OVERLAPPING_COVERAGE`), and the elected-APTC ceiling (`ERR_APTC_EXCEEDS_MAX`). The optimistic-concurrency check on the household version (`ERR_STALE_VERSION`) is evaluated last among these.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition action endpoints and the test clock — return `200 OK`. Reads return `200 OK`. The complete request and response payloads for each endpoint are reconstructed from the workflow narratives in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/households` | Create a household shell for the acting applicant | Applicant, Navigator |
| GET | `/households/{id}` | Fetch a household with its computed MAGI/FPL fields | Applicant, Navigator, MarketplaceAdmin |
| GET | `/households` | List households (paginated) | Applicant, Navigator, MarketplaceAdmin |
| POST | `/households/{id}/members` | Add a member; recomputes household MAGI/FPL/size | Applicant, Navigator |
| PATCH | `/households/{id}/members/{member_id}` | Update a member's income/status; recomputes household MAGI/FPL | Applicant, Navigator |
| GET | `/households/{id}/members` | List members of a household | Applicant, Navigator, MarketplaceAdmin |
| POST | `/applications` | Create a DRAFT application for a household | Applicant, Navigator |
| GET | `/applications/{id}` | Fetch an application | Applicant, Navigator, MarketplaceAdmin |
| GET | `/applications` | List applications; filter by household_id, status | Applicant, Navigator, MarketplaceAdmin |
| POST | `/applications/{id}/submit` | Submit a DRAFT application (OCC on household) | Applicant, Navigator |
| POST | `/applications/{id}/determine` | Run eligibility determination on a SUBMITTED application | MarketplaceAdmin |
| POST | `/applications/{id}/reopen` | Revert a DETERMINED application to DRAFT; deletes its determination | Applicant, Navigator |
| POST | `/applications/{id}/cancel` | Cancel a DRAFT or SUBMITTED application | Applicant, Navigator |
| GET | `/applications/{id}/determination` | Fetch the determination(s) for an application | Applicant, Navigator, MarketplaceAdmin |
| POST | `/health-plans` | Register a plan in the catalog | MarketplaceAdmin |
| GET | `/health-plans` | List/shop plans; filter by rating_area, coverage_year, metal_tier | Applicant, Navigator, MarketplaceAdmin |
| GET | `/health-plans/{id}` | Fetch one plan | Applicant, Navigator, MarketplaceAdmin |
| POST | `/sep-requests` | File a Special Enrollment Period request | Applicant, Navigator |
| GET | `/sep-requests/{id}` | Fetch a SEP request | Applicant, Navigator, MarketplaceAdmin |
| GET | `/sep-requests` | List SEP requests; filter by application_id, status | Applicant, Navigator, MarketplaceAdmin |
| POST | `/sep-requests/{id}/approve` | Approve a PENDING SEP request | MarketplaceAdmin |
| POST | `/sep-requests/{id}/deny` | Deny a PENDING SEP request | MarketplaceAdmin |
| POST | `/enrollments` | Create an enrollment from a DETERMINED application + plan (OCC on household) | Applicant, Navigator |
| GET | `/enrollments/{id}` | Fetch an enrollment with computed premium/effective-date fields | Applicant, Navigator, MarketplaceAdmin |
| GET | `/enrollments` | List enrollments; filter by application_id, plan_id | Applicant, Navigator, MarketplaceAdmin |
| POST | `/enrollments/{id}/pay-binder` | Pay the binder premium (AWAITING_BINDER → PAID) | Applicant, Navigator |
| POST | `/enrollments/{id}/effectuate` | Effectuate coverage (PENDING_EFFECTUATION → ACTIVE; requires PAID) | MarketplaceAdmin |
| POST | `/enrollments/{id}/mark-delinquent` | Mark binder payment delinquent (PAID → DELINQUENT) | MarketplaceAdmin |
| POST | `/enrollments/{id}/terminate` | Terminate coverage (lifecycle → TERMINATED) | Applicant, Navigator |
| POST | `/reconciliations` | Year-end reconciliation: recompute allowed APTC and settle | MarketplaceAdmin |
| GET | `/reconciliations/{id}` | Fetch a reconciliation record | Applicant, Navigator, MarketplaceAdmin |
| GET | `/reconciliations` | List reconciliation records; filter by enrollment_id | Applicant, Navigator, MarketplaceAdmin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | MarketplaceAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_PRIMARY` | 409 |
| `ERR_PLAN_AREA_MISMATCH` | 409 |
| `ERR_SEP_WINDOW_CLOSED` | 409 |
| `ERR_SEP_NOT_APPROVED` | 409 |
| `ERR_NO_BENCHMARK_PLAN` | 409 |
| `ERR_APTC_EXCEEDS_MAX` | 409 |
| `ERR_OVERLAPPING_COVERAGE` | 409 |
| `ERR_STALE_VERSION` | 412 |
