# Benefits Open Enrollment API — Product Requirements Document

## 1. Introduction

Benefits administration sits at the intersection of human resources, payroll, and regulatory compliance, and it is unforgiving of bookkeeping drift: a single mis-prorated premium or a mis-timed eligibility flip can ripple into an incorrect carrier feed, a wrong paycheck deduction, or a misfiled federal tax form. This document specifies the Benefits Open Enrollment API, a system that governs the full benefits lifecycle for an employer — from the moment an employee is hired and begins their waiting period, through plan and tier catalog configuration, dependent verification, enrollment election, evidence-of-insurability underwriting for high-value voluntary life coverage, and on to the downstream obligations of payroll deduction synchronization, carrier EDI exchange, and Affordable Care Act reporting.

The platform is built around a strict separation of duties. Distinct operator roles configure the catalog, verify dependents, run payroll, and make compliance decisions, and the system actively prevents any one operator from both initiating and approving the same sensitive change. Qualifying life events — births, marriages, divorces, and losses of other coverage — drive mid-year enrollment changes that can be applied either prospectively or retroactively, with the retroactive path reconstructing already-billed pay periods into a precise ledger of corrections. Throughout, the system treats time as an explicit, advanceable quantity: waiting periods elapse, life-event windows expire, and pay periods accumulate against a logical clock that test-driving operations move forward deterministically.

The remainder of this document defines the global contracts that every endpoint honors (Section 2), the business workflows and their interlocking rules (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`.

The system recognizes exactly four roles: `BenefitsAdmin`, `DependentVerifier`, `PayrollOfficer`, and `ComplianceOfficer`. Each operation permits only a specific subset of these roles; a syntactically valid request made under a role that is not authorized for the requested operation is rejected with `ERR_FORBIDDEN_ROLE`. Section 4 lists the authorized role or roles for every endpoint.

All four roles carry an **opaque** identity. When `X-User-Role` is `BenefitsAdmin`, `DependentVerifier`, `PayrollOfficer`, or `ComplianceOfficer`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`; the server never compares it to an entity primary key for ownership purposes. The server may, however, **record** an operator's `X-User-ID` where a workflow explicitly captures it: a `BenefitsAdmin` who submits a life event has their `X-User-ID` stored as that life event's `submitted_by_user_id`, and a `DependentVerifier` who verifies a dependent has their `X-User-ID` stored as that dependent's `verified_by_user_id`. These recorded values are themselves the basis for the segregation-of-duties checks described in Section 2.4 and Section 3 — the comparison is operator-id against operator-id (or, for dependent verification, operator-id against the dependent's owning employee identifier), never operator-id against an entity's own `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page; it defaults to 0 and may not be negative. A request whose `limit` falls outside the inclusive range from 1 to 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless an endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order. The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of items matching the query before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties, Versioning, and Immutable Ledgers

Most resources in this system are mutable, versioned records. Every such resource carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp recorded when the resource is first created, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that begins at its initial value and increments by exactly one each time the resource is mutated. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits. The Employee, WaitingPeriod, PlanOffering, PlanTier, Dependent, Enrollment, LifeEvent, EOIRequest, and Form1095C resources are all versioned in this way.

Two resources are deliberately **immutable ledger events** and are exceptions to the rule above: a DeductionLine and a CarrierFeedRecord each carry only an `id` and a `created_at` — they have no `updated_at` and no `version`, because once written they are never modified. They are append-only audit records of what was billed and what was sent to the carrier.

Whenever any state transition or computed-field recomputation mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented as part of the same operation. Where an operation cascades across more than one resource — for example, approving a life event that supersedes an old enrollment and mints a new one — each affected mutable resource independently advances its own `updated_at` and `version`.

### 2.5. Nested Resource Resolution

Several endpoints address a resource through a path that names a parent before a child, and several request bodies reference other resources by their identifiers. The system resolves every such reference left to right and front to back: path identifiers are validated in the order they appear, and any foreign-key identifier supplied in the body is validated after the path. The first identifier — in the path or, failing that, in the body — that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any business rule is evaluated. For instance, registering a dependent under an employee id that does not exist fails with `ERR_NOT_FOUND` for the employee, never reaching dependent validation.

### 2.6. Monetary Precision and Rounding Order

All monetary quantities are stored and returned as integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent — that is, a value exactly halfway between two cents rounds to the larger magnitude. Percentages such as `employer_contribution_pct` are decimal fractions between 0 and 1 inclusive and are not themselves rounded; only the cent results derived from them are.

Rounding **order** is contractually pinned in several calculations and must be respected exactly, because an alternative order can differ from the specified result by a cent. When an employer share is subtracted from a premium, the employer share is rounded to whole cents *before* the subtraction. When an annual cost is converted to a per-paycheck amount, the monthly cost is multiplied by twelve *before* it is divided by the number of pay periods. When a carrier premium is prorated, each component line is rounded to whole cents *first* and the rounded lines are *then* summed, never the reverse. Section 3 states each of these orders in its business context.

### 2.7. Eligibility, the Logical Clock, and Waiting Periods

Eligibility to enroll is time-driven and is tracked on each employee through the `eligibility_status` field, which takes one of four values: `WAITING`, `ELIGIBLE`, `INELIGIBLE`, or `TERMINATED`. A newly created employee begins in `WAITING` unless their `employment_type` is `SEASONAL`, in which case they are `INELIGIBLE` from creation and never become eligible to enroll. The two non-seasonal employment types, `FULL_TIME` and `PART_TIME`, are subject to a waiting period before eligibility opens.

The system maintains a single advanceable logical clock. A test-driving capability sets that clock to a supplied absolute instant. Each time the clock advances, the system re-evaluates every waiting period: any WaitingPeriod whose `status` is still `PENDING` and whose `end_date` is at or before the new clock instant flips to `ELAPSED`. Because a waiting period window is half-open with an inclusive `start_date` and an exclusive `end_date`, eligibility opens *at* the `end_date` instant. When a waiting period elapses, the system bubbles the change up to its owning employee: if that employee's `employment_type` is not `SEASONAL`, their `eligibility_status` moves from `WAITING` to `ELIGIBLE` and the employee's `version` is incremented. Seasonal employees are never re-evaluated to eligible.

### 2.8. Optimistic Concurrency on Employee-Gated Writes

Two operations mutate benefit state in a way that depends on the owning employee's current condition, and both are guarded by optimistic concurrency control against the Employee resource. Activating a draft enrollment requires the request body to include `expected_employee_version`, carrying the `version` of the owning Employee that the client last observed. If that value does not equal the employee's current `version` — for example because the employee was terminated, because a clock advance flipped their eligibility, or because a competing enrollment of the same benefit type was just activated and changed the employee's benefit state — the activation is rejected with `ERR_STALE_EMPLOYEE_VERSION` at HTTP 412, before any state change is applied.

Approving a life event is guarded identically. That approval supersedes the employee's current active enrollment of the same benefit type and mints a replacement, so it likewise requires `expected_employee_version` to match the owning Employee's current `version`. If another approved life event has already superseded the enrollment, or a clock advance has changed the employee's state since the approver last read it, the approval is rejected with `ERR_STALE_EMPLOYEE_VERSION` at HTTP 412 — the approver's view of the employee's benefit state is no longer current and the change is refused rather than applied over stale data. No other endpoint takes a version field; only these two carry `expected_employee_version`.

### 2.9. Segregation of Duties

The system enforces separation of duties on the sensitive transitions where an initiator and an approver would otherwise be the same person. The acting operator's `X-User-ID` must differ from the recorded initiator on three operations: approving a life event and rejecting a life event each require that the acting `X-User-ID` differ from the life event's `submitted_by_user_id`; verifying a dependent requires that the verifying `DependentVerifier`'s `X-User-ID` differ from the `id` of the employee who owns that dependent (an employee may not verify their own dependent). A violation of any of these three checks is rejected with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403.

### 2.10. Validation Ordering

When several checks could fail on a single request, the system evaluates them in a fixed priority order so that the returned error is deterministic. Authentication is evaluated first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED` before anything else. Authorization is second: a recognized but unpermitted role yields `ERR_FORBIDDEN_ROLE`. Third, existence of every path and body-referenced resource is confirmed, failing with `ERR_NOT_FOUND` as described in Section 2.5. Fourth, the request body's shape is validated — required fields present, enum values legal, and integers non-negative where constrained — failing with `ERR_INVALID_REQUEST`. Fifth, for any transition endpoint, the target resource must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE`.

Only after these five gates pass are the operation-specific business rules evaluated. Among those, segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) is checked before the EOI routing rule (`ERR_EOI_REQUIRED`), which is checked before the employee-eligibility rule (`ERR_EMPLOYEE_NOT_ELIGIBLE`), which is checked before the life-event window rule (`ERR_LIFE_EVENT_WINDOW_EXPIRED`), which precedes the waiting-period overlap rule (`ERR_WAITING_PERIOD_OVERLAP`), the coverage-overlap rule (`ERR_COVERAGE_OVERLAP`), the dependent-verified rule (`ERR_DEPENDENT_NOT_VERIFIED`), and the archived-plan rule (`ERR_PLAN_ARCHIVED`). The optimistic-concurrency check (`ERR_STALE_EMPLOYEE_VERSION`) is evaluated after all of the foregoing business rules. Each operation in Section 3 names only the rules that apply to it; this ordering governs which error surfaces when more than one would otherwise fire on the same request.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Employee and Opening Eligibility

The lifecycle begins when a `BenefitsAdmin` creates an employee, supplying the employee's `full_name`, their `hire_date` (the ISO 8601 date of hire and the basis from which a waiting period is measured), their `employment_type` — one of `FULL_TIME`, `PART_TIME`, or `SEASONAL` — their `payroll_schedule`, which is either `SEMI_MONTHLY` or `BIWEEKLY`, and their self-reported `monthly_household_income_cents`, a non-negative integer that later feeds affordability testing. At creation the system sets `eligibility_status` to `INELIGIBLE` for a `SEASONAL` hire and to `WAITING` for everyone else, and it initializes `pay_periods_processed` to zero. An employee's `eligibility_status` and `pay_periods_processed` are system-managed and are never supplied by the client.

To open eligibility, a `BenefitsAdmin` attaches one or more waiting-period windows to the employee. Each window is created with a `window_type` of either `INITIAL`, for the new-hire waiting period, or `REINSTATEMENT`, for a return after a leave, together with a `start_date` and an `end_date`. The window is half-open: the `start_date` is inclusive and the `end_date` is exclusive, and eligibility opens at the `end_date`. A new window of any `window_type` may not overlap an existing window for the same employee; because the interval is half-open, two windows that merely abut — where one window's `end_date` equals the next window's `start_date` — are permitted, but any genuine overlap is rejected with `ERR_WAITING_PERIOD_OVERLAP`. Each window tracks its own `status`, which is `PENDING` while the clock is before its `end_date` and becomes `ELAPSED` once the clock reaches or passes it.

The transition from waiting to eligible is driven by the logical clock rather than by a direct request on the employee. When the clock is advanced to an instant at or beyond an active window's `end_date`, that window — provided it is the one `PENDING` window whose `end_date` the clock has now reached — flips to `ELAPSED`, and the owning employee, if not `SEASONAL`, moves from `WAITING` to `ELIGIBLE` with their `version` incremented. The clock-advance capability accepts a single target instant, `to_iso8601`, and sets the server clock to it absolutely.

A `BenefitsAdmin` may terminate an eligible employee. Termination is permitted only when the employee's `eligibility_status` is `ELIGIBLE`; it moves the employee to `TERMINATED` and cascades through the employee's coverage. Every enrollment of that employee currently in the `ACTIVE` state transitions to `SUPERSEDED` with its `coverage_end_date` set to the current clock date, and each such superseded enrollment in turn emits a carrier feed record carrying the `TERM` transaction maintenance type. The employee's `version` is incremented once for the termination.

### 3.2. Building the Plan Catalog

A `BenefitsAdmin` configures the offering catalog independently of any employee. A **plan offering** is created with a `benefit_type` — one of `MEDICAL`, `DENTAL`, `VISION`, or `VOLUNTARY_LIFE` — and a display `name` such as "Gold PPO". Two further attributes matter only for voluntary life: `requires_eoi`, a boolean that defaults to false and is set true for voluntary-life offerings whose elected coverage above a guaranteed-issue ceiling must be underwritten, and `guaranteed_issue_amount_cents`, a non-negative integer defaulting to zero that marks the coverage level at or below which coverage is auto-issued. Coverage above `guaranteed_issue_amount_cents` requires an approved evidence-of-insurability decision; the field is meaningful only when `requires_eoi` is true. An offering begins life with its `status` set to `ACTIVE`.

A `BenefitsAdmin` may archive an offering. Archiving is permitted only from `ACTIVE`, sets the offering's `status` to `ARCHIVED`, and increments its `version`. Once an offering is `ARCHIVED`, any attempt to create an enrollment against one of its tiers is rejected with `ERR_PLAN_ARCHIVED`.

Beneath each offering, a `BenefitsAdmin` defines one or more **plan tiers**. A tier names the offering it belongs to through its `plan_offering_id` and carries a `coverage_level` of `EMPLOYEE_ONLY`, `EMPLOYEE_PLUS_SPOUSE`, `EMPLOYEE_PLUS_CHILDREN`, or `EMPLOYEE_PLUS_FAMILY`. It records the total monthly premium combining employer and employee shares in `monthly_premium_cents` (a positive integer), and the employer's portion of that premium as `employer_contribution_pct`, a decimal fraction no less than 0 and no greater than 1 — for example, 0.70 for a seventy-percent employer contribution. Two more tier fields apply only to voluntary life: `rate_per_1000_monthly_cents`, the monthly premium per one thousand dollars of coverage in cents (defaulting to zero and ignored for medical, dental, and vision), and `is_lowest_cost_self_only`, a boolean defaulting to false that flags the one `MEDICAL` `EMPLOYEE_ONLY` tier used as the benchmark for affordability testing — at most one tier per benefit type may carry this flag. When an enrollment is later created against a tier, its benefit type is copied from that tier's offering.

### 3.3. Dependent Registration and Verification

Dependents follow a verification loop owned by the `DependentVerifier` role. A `BenefitsAdmin` registers a dependent under an employee, supplying the dependent's `relationship` — either `SPOUSE` or `CHILD` — their `full_name`, and their `date_of_birth`. A newly registered dependent starts with `verification_status` set to `PENDING` and `verified_by_user_id` null.

From `PENDING`, the dependent may take any of three paths. A `DependentVerifier` who needs more documentation moves the dependent from `PENDING` to `INFO_REQUESTED`. A `BenefitsAdmin` then resubmits the requested documentation, moving the dependent from `INFO_REQUESTED` back to `PENDING`. This loop is cyclic: a dependent may bounce between `PENDING` and `INFO_REQUESTED` any number of rounds before it is resolved, and each request-info and each resubmit increments the dependent's `version`. Alternatively, from `PENDING` a `DependentVerifier` verifies the dependent, moving it from `PENDING` to `VERIFIED`, which records the verifier's `X-User-ID` into `verified_by_user_id` and increments `version`; verification is subject to the segregation rule that the verifier's `X-User-ID` must differ from the owning employee's identifier, failing otherwise with `ERR_SEGREGATION_OF_DUTIES`. Finally, from `PENDING` a `DependentVerifier` may reject the dependent, moving it from `PENDING` to `REJECTED` and incrementing `version`. Both `VERIFIED` and `REJECTED` are terminal. Each of these four transitions requires the dependent to be in the precise originating state named, and a request from any other state is refused with `ERR_INVALID_STATE`. Only a `VERIFIED` dependent counts toward an enrollment's `covered_dependent_count` and may be attached to an enrollment.

### 3.4. Electing Coverage: Drafting, Underwriting, and Activation

A `BenefitsAdmin` elects coverage for an employee by creating an enrollment against a plan tier. The creation supplies the `plan_tier_id`, the `coverage_start_date` (an inclusive coverage start date), and, for voluntary life only, a `coverage_amount_cents` giving the elected coverage in cents (which defaults to zero and is zero for medical, dental, and vision). The new enrollment is born in `DRAFT`, its `benefit_type` copied from the chosen tier's offering, and is associated with its employee through `employee_id`. Creating an enrollment against a tier whose offering has been archived is rejected with `ERR_PLAN_ARCHIVED`. The computed cost fields `monthly_employee_cost_cents` and `per_paycheck_deduction_cents`, the `covered_dependent_count`, the `coverage_end_date`, the `source_life_event_id`, and the `superseded_by_enrollment_id` are all system-managed and are not part of the creation payload.

A draft enrollment normally proceeds straight to activation, but voluntary-life elections above the guaranteed-issue ceiling must first be underwritten. When the enrollment's `benefit_type` is `VOLUNTARY_LIFE` and its `coverage_amount_cents` exceeds the offering's `guaranteed_issue_amount_cents`, a `BenefitsAdmin` submits the draft for evidence of insurability, moving it from `DRAFT` to `PENDING_EOI`. That submission creates an evidence-of-insurability request linked to the enrollment, with its `decision` set to `PENDING` and its `excess_coverage_cents` computed as the enrollment's `coverage_amount_cents` minus the offering's `guaranteed_issue_amount_cents` — the portion of coverage that must be underwritten. Submitting for evidence of insurability increments the enrollment's `version`. Attempting to activate such an over-ceiling voluntary-life draft directly, without routing through underwriting, is rejected with `ERR_EOI_REQUIRED`.

A `ComplianceOfficer` decides a pending evidence-of-insurability request by supplying a `decision`. The request must currently be `PENDING` and its linked enrollment must currently be in `PENDING_EOI`. When the `decision` is set to `APPROVED`, the request moves from `PENDING` to `APPROVED` and the linked enrollment is carried from `PENDING_EOI` to `ACTIVE`: the enrollment's `monthly_employee_cost_cents` and `per_paycheck_deduction_cents` are recomputed, a carrier feed record with the `ADD` maintenance type is emitted, and the enrollment's `version` is incremented; the request's own `version` is incremented as well. When the `decision` is set to `DENIED`, the request moves from `PENDING` to `DENIED` and, as a compensating action, the linked enrollment reverts from `PENDING_EOI` back to `DRAFT` with its `version` incremented — and, deliberately, no carrier feed record is emitted on denial. Both `APPROVED` and `DENIED` are terminal for the request.

Activation of a draft enrollment is performed by a `BenefitsAdmin` and is the system's central gate. The enrollment must be in `DRAFT`; the owning employee's `eligibility_status` must be `ELIGIBLE`, failing otherwise with `ERR_EMPLOYEE_NOT_ELIGIBLE`; if the enrollment is voluntary life, its `coverage_amount_cents` must not exceed the offering's `guaranteed_issue_amount_cents` (otherwise the EOI route is required and `ERR_EOI_REQUIRED` is returned); and the enrollment's closed coverage interval must not overlap any existing `ACTIVE` enrollment of the same `benefit_type` for that employee. The coverage interval runs inclusively from `coverage_start_date` to `coverage_end_date`; two intervals that merely abut — where a prior interval's end plus one day equals the new interval's start — are allowed, but any genuine overlap is rejected with `ERR_COVERAGE_OVERLAP`. Activation also carries the optimistic-concurrency field `expected_employee_version` and is refused with `ERR_STALE_EMPLOYEE_VERSION` if that value does not match the owning employee's current `version`. On success the enrollment moves from `DRAFT` to `ACTIVE`, its `monthly_employee_cost_cents` and `per_paycheck_deduction_cents` are recomputed, a carrier feed record with the `ADD` maintenance type is emitted, the enrollment's `version` is incremented, and the employee's `version` is incremented as well.

A `BenefitsAdmin` may instead cancel a draft that will not be activated, moving the enrollment from `DRAFT` to `CANCELLED` and incrementing its `version`. `CANCELLED` and `SUPERSEDED` are the two terminal states of an enrollment.

### 3.5. Computing Employee Cost and Paycheck Deductions

The employee's monthly cost is computed when an enrollment activates and again whenever an evidence-of-insurability approval carries a `PENDING_EOI` enrollment to `ACTIVE`. For a medical, dental, or vision enrollment, the employer's share is the tier's `monthly_premium_cents` multiplied by the tier's `employer_contribution_pct`, rounded half up to whole cents, and the employee's `monthly_employee_cost_cents` is the tier's `monthly_premium_cents` minus that rounded employer share — the employer share is rounded *before* the subtraction. For a voluntary-life enrollment, the number of one-thousand-dollar coverage units is the enrollment's `coverage_amount_cents` divided by one hundred thousand, and `monthly_employee_cost_cents` is that unit count multiplied by the tier's `rate_per_1000_monthly_cents`, rounded half up to whole cents.

From the monthly cost the system derives the per-paycheck withholding. The number of pay periods in a year is twenty-four when the employee's `payroll_schedule` is `SEMI_MONTHLY` and twenty-six when it is `BIWEEKLY`. The annual employee cost is `monthly_employee_cost_cents` multiplied by twelve, and `per_paycheck_deduction_cents` is that annual cost divided by the number of pay periods in the year, rounded half up to whole cents. The multiplication by twelve happens before the division, and the deduction is computed only after `monthly_employee_cost_cents` has been established.

### 3.6. Qualifying Life Events and Mid-Year Changes

A `BenefitsAdmin` submits a qualifying life event on behalf of an employee, naming the `event_type` — one of `BIRTH`, `MARRIAGE`, `DIVORCE`, or `LOSS_OF_COVERAGE` — the `event_date` on which the qualifying event occurred (an ISO 8601 date that may lie in the past, which is what drives a retroactive correction), the `requested_plan_tier_id` the employee wishes to move to, a `requested_coverage_amount_cents` (zero outside voluntary life), and an `adjustment_mode` of either `PROSPECTIVE` or `RETROACTIVE`. The life event is created in `SUBMITTED` with its `submitted_by_user_id` captured from the submitting admin's `X-User-ID`.

Approval and rejection of a life event are both restricted to a `BenefitsAdmin` other than the submitter. Each requires the life event to be in `SUBMITTED` and the acting `X-User-ID` to differ from the recorded `submitted_by_user_id`, failing otherwise with `ERR_SEGREGATION_OF_DUTIES`. Rejection simply moves the life event from `SUBMITTED` to `REJECTED` and increments its `version`. Approval is the heavier operation. Beyond segregation of duties, approval requires the owning employee's `eligibility_status` to be `ELIGIBLE` (otherwise `ERR_EMPLOYEE_NOT_ELIGIBLE`) and the life event's `event_date` to fall within thirty days of the current clock date (otherwise `ERR_LIFE_EVENT_WINDOW_EXPIRED`). Approval also carries `expected_employee_version` and is refused with `ERR_STALE_EMPLOYEE_VERSION` when that value does not match the owning employee's current `version`.

A successful approval moves the life event from `SUBMITTED` to `APPROVED` and cascades in a fixed sequence. First, a new enrollment is created for the `requested_plan_tier_id` directly in `ACTIVE`, with its `coverage_start_date` set to the life event's `event_date` and its `source_life_event_id` set to this life event; its `monthly_employee_cost_cents` and `per_paycheck_deduction_cents` are computed as in Section 3.5. Second, the employee's prior `ACTIVE` enrollment of the same benefit type transitions from `ACTIVE` to `SUPERSEDED`, with its `coverage_end_date` set to the new enrollment's `coverage_start_date` minus one day and its `superseded_by_enrollment_id` set to the new enrollment's id. Third, the superseded enrollment emits a carrier feed record with the `TERM` maintenance type and the new enrollment emits one with the `ADD` maintenance type. Fourth, if the life event's `adjustment_mode` is `RETROACTIVE`, the system posts retroactive deduction corrections as described in Section 3.7. Finally, the life event's `version` and the employee's `version` are each incremented.

### 3.7. The Payroll Deduction Ledger: Prospective vs. Retroactive

Payroll runs and life-event corrections both write into an append-only ledger of deduction lines. Each line is immutable and records the `enrollment_id` and `employee_id` it pertains to, the zero-based `pay_period_index` of the period it bills, a `line_type`, and a signed `amount_cents`. A `line_type` of `REGULAR` is an ordinary per-paycheck withholding; a `line_type` of `RETRO_ADJUSTMENT` is a correction posted by a retroactive life event and may be positive (additional amount owed) or negative (a refund).

A `PayrollOfficer` advances an employee's payroll by one period through a test-driving capability that names the `employee_id`. Each run increments the employee's `pay_periods_processed` by one, posts one `REGULAR` deduction line per `ACTIVE` enrollment at that enrollment's `per_paycheck_deduction_cents`, and increments the employee's `version`.

The retroactive-versus-prospective distinction is decided entirely by the life event's `adjustment_mode` and is computed at approval time. Let the prior active enrollment's `per_paycheck_deduction_cents` be the old per-paycheck amount and the new enrollment's `per_paycheck_deduction_cents` be the new per-paycheck amount. Under the **prospective** variant, no `RETRO_ADJUSTMENT` lines are posted against already-processed periods; the net retroactive correction is zero and the new per-paycheck amount simply applies going forward, from the next unprocessed period whose index is at or above the employee's current `pay_periods_processed`. Under the **retroactive** variant, the system walks the already-processed pay periods — those with index from zero up to one less than `pay_periods_processed` — in ascending `pay_period_index` order, and for each period whose billed coverage date falls on or after the life event's `event_date`, it posts exactly one `RETRO_ADJUSTMENT` deduction line whose `amount_cents` is the new per-paycheck amount minus the old per-paycheck amount. The affected periods are processed deterministically in ascending `pay_period_index` order, and the total retroactive correction is that per-period difference multiplied by the number of affected periods.

### 3.8. Carrier EDI Reconciliation

Every enrollment activation, every evidence-of-insurability approval, every life-event supersession, and every termination produces an immutable carrier feed record — the system's representation of an EDI 834 maintenance transaction. Each record names the `enrollment_id` it concerns and carries a `transaction_set` of `ADD` for a newly active enrollment, `TERM` for an enrollment that has been superseded or otherwise terminated, or `CHANGE` for a coverage-amount change. Each record also carries a `reconciled_monthly_premium_cents`, the carrier-side prorated monthly premium for that enrollment.

The reconciled premium is prorated for coverage that begins partway through a month, and it is computed as the sum of two separately rounded component lines. Let the number of calendar days in the month of the enrollment's `coverage_start_date` be the month's day count, and let the number of covered days be that day count minus the day-of-month of the `coverage_start_date` plus one. The employer's monthly share is the tier's `monthly_premium_cents` multiplied by `employer_contribution_pct`, rounded half up to whole cents, and the employee's monthly share is the tier's `monthly_premium_cents` minus that rounded employer share. The prorated employer line is the employer monthly share multiplied by the covered days and divided by the month's day count, rounded half up to whole cents; the prorated employee line is computed the same way from the employee monthly share. The `reconciled_monthly_premium_cents` is the sum of these two already-rounded component lines. Each component line is rounded to whole cents first and the rounded lines are then added — this round-per-line-then-sum order is pinned and is not the same as prorating the combined premium and rounding once at the end, because the two can differ by a cent at certain proration ratios.

### 3.9. Attaching Dependents to Coverage

A `BenefitsAdmin` attaches a dependent to an enrollment by supplying the `dependent_id`. Only a dependent whose `verification_status` is `VERIFIED` may be attached; attempting to attach one that is not verified is rejected with `ERR_DEPENDENT_NOT_VERIFIED`. A successful attachment increments the enrollment's `covered_dependent_count` by one and increments the enrollment's `version`. Symmetrically, a `BenefitsAdmin` may detach a dependent from an enrollment by supplying the `dependent_id`; this decrements the enrollment's `covered_dependent_count` by one and increments the enrollment's `version`.

### 3.10. ACA Reporting and Affordability

A `ComplianceOfficer` generates an Affordable Care Act Form 1095-C for an employee and a given `tax_year`. Generation records the employee it pertains to and computes three derived values. The benchmark tier is the single plan tier whose `is_lowest_cost_self_only` flag is set and whose offering's benefit type is `MEDICAL`. The form's `lowest_cost_monthly_premium_cents` is that benchmark tier's employee monthly cost, computed as the tier's `monthly_premium_cents` minus the half-up-rounded product of `monthly_premium_cents` and `employer_contribution_pct`. The form's `affordability_threshold_cents` is the employee's `monthly_household_income_cents` multiplied by the ACA affordability percentage of 9.02 percent (the decimal factor 0.0902), rounded half up to whole cents. The form's `affordability_indicator` is `AFFORDABLE` when the `lowest_cost_monthly_premium_cents` is less than or equal to the `affordability_threshold_cents`, and `UNAFFORDABLE` otherwise — a cost exactly equal to the threshold counts as `AFFORDABLE`.

A generated form begins with its `status` set to `GENERATED`. A `ComplianceOfficer` may file it, moving the form from `GENERATED` to `FILED`, which increments its `version`. `FILED` is terminal and immutable: any attempt to mutate a form that is already `FILED` is rejected with `ERR_FORM_ALREADY_FILED`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify or transition an existing resource, that fetch a resource, or that drive a test capability return a `200 OK` status code. Every request must carry the `X-User-ID` and `X-User-Role` headers described in Section 2.1, and the authorized roles for each operation are listed below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employees` | Create an employee | BenefitsAdmin |
| GET | `/employees/{id}` | Fetch an employee | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| GET | `/employees` | List employees (paginated) | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| POST | `/employees/{id}/terminate` | Terminate an employee; supersede ACTIVE enrollments and emit TERM feed records | BenefitsAdmin |
| POST | `/employees/{id}/waiting-periods` | Create a waiting-period window for an employee | BenefitsAdmin |
| GET | `/employees/{id}/waiting-periods` | List an employee's waiting-period windows | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| POST | `/plan-offerings` | Create a plan offering | BenefitsAdmin |
| GET | `/plan-offerings/{id}` | Fetch a plan offering | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| POST | `/plan-offerings/{id}/archive` | Archive a plan offering; archived offerings reject new enrollments | BenefitsAdmin |
| POST | `/plan-tiers` | Create a plan tier under an offering | BenefitsAdmin |
| GET | `/plan-tiers/{id}` | Fetch a plan tier | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| GET | `/plan-tiers` | List plan tiers, filterable by offering | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| POST | `/employees/{id}/dependents` | Register a dependent for an employee | BenefitsAdmin |
| GET | `/dependents/{id}` | Fetch a dependent | BenefitsAdmin, DependentVerifier, ComplianceOfficer, PayrollOfficer |
| GET | `/dependents` | List dependents, filterable by employee | BenefitsAdmin, DependentVerifier, ComplianceOfficer, PayrollOfficer |
| POST | `/dependents/{id}/request-info` | Request more info on a dependent | DependentVerifier |
| POST | `/dependents/{id}/resubmit` | Resubmit dependent documentation | BenefitsAdmin |
| POST | `/dependents/{id}/verify` | Verify a dependent | DependentVerifier |
| POST | `/dependents/{id}/reject` | Reject a dependent | DependentVerifier |
| POST | `/employees/{id}/enrollments` | Create a DRAFT enrollment for an employee against a plan tier | BenefitsAdmin |
| GET | `/enrollments/{id}` | Fetch an enrollment | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| GET | `/enrollments` | List enrollments, filterable by employee or plan tier | BenefitsAdmin, PayrollOfficer, ComplianceOfficer, DependentVerifier |
| POST | `/enrollments/{id}/activate` | Activate a DRAFT enrollment; OCC on the owning employee | BenefitsAdmin |
| POST | `/enrollments/{id}/submit-eoi` | Submit an over-GI VOLUNTARY_LIFE enrollment for EOI | BenefitsAdmin |
| POST | `/enrollments/{id}/cancel` | Cancel a DRAFT enrollment | BenefitsAdmin |
| POST | `/enrollments/{id}/add-dependent` | Attach a VERIFIED dependent to an enrollment | BenefitsAdmin |
| POST | `/enrollments/{id}/remove-dependent` | Detach a dependent from an enrollment | BenefitsAdmin |
| GET | `/eoi-requests/{id}` | Fetch an EOI request | BenefitsAdmin, ComplianceOfficer |
| GET | `/eoi-requests` | List EOI requests, filterable by enrollment | BenefitsAdmin, ComplianceOfficer |
| POST | `/eoi-requests/{id}/decide` | Decide an EOI request; APPROVED activates, DENIED reverts to DRAFT | ComplianceOfficer |
| POST | `/employees/{id}/life-events` | Submit a qualifying life event for an employee | BenefitsAdmin |
| GET | `/life-events/{id}` | Fetch a life event | BenefitsAdmin, ComplianceOfficer, PayrollOfficer |
| GET | `/life-events` | List life events, filterable by employee | BenefitsAdmin, ComplianceOfficer, PayrollOfficer |
| POST | `/life-events/{id}/approve` | Approve a life event; supersede, mint new enrollment, post retro lines; OCC and segregation enforced | BenefitsAdmin |
| POST | `/life-events/{id}/reject` | Reject a life event; segregation enforced | BenefitsAdmin |
| POST | `/_payroll/run` | Advance an employee's payroll by one period, posting REGULAR deduction lines | PayrollOfficer |
| GET | `/deduction-lines/{id}` | Fetch a deduction line | PayrollOfficer, BenefitsAdmin, ComplianceOfficer |
| GET | `/deduction-lines` | List deduction lines, filterable by enrollment or employee | PayrollOfficer, BenefitsAdmin, ComplianceOfficer |
| GET | `/carrier-feed-records/{id}` | Fetch a carrier feed record | BenefitsAdmin, ComplianceOfficer, PayrollOfficer |
| GET | `/carrier-feed-records` | List carrier feed records, filterable by enrollment | BenefitsAdmin, ComplianceOfficer, PayrollOfficer |
| POST | `/employees/{id}/form-1095c` | Generate an ACA 1095-C for an employee and tax year | ComplianceOfficer |
| GET | `/form-1095c/{id}` | Fetch a 1095-C | ComplianceOfficer, BenefitsAdmin |
| GET | `/form-1095c` | List 1095-C forms, filterable by employee | ComplianceOfficer, BenefitsAdmin |
| POST | `/form-1095c/{id}/file` | File a 1095-C; terminal | ComplianceOfficer |
| POST | `/_clock/advance` | Set the server clock to an absolute instant; elapse waiting periods and re-evaluate eligibility | BenefitsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_EOI_REQUIRED` | 409 |
| `ERR_EMPLOYEE_NOT_ELIGIBLE` | 409 |
| `ERR_LIFE_EVENT_WINDOW_EXPIRED` | 409 |
| `ERR_WAITING_PERIOD_OVERLAP` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_DEPENDENT_NOT_VERIFIED` | 409 |
| `ERR_STALE_EMPLOYEE_VERSION` | 412 |
| `ERR_PLAN_ARCHIVED` | 409 |
| `ERR_FORM_ALREADY_FILED` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
