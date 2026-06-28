# Supplemental & Voluntary Benefits API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Supplemental & Voluntary Benefits API, a back-office platform that administers Aflac-style worksite insurance: accident, critical-illness, and hospital-indemnity policies that employees elect through payroll deduction and that pay flat, scheduled cash benefits when a covered event occurs. The platform sits between three constituencies whose interests rarely align — the employer that sponsors the program, the carrier that underwrites and pays claims, and the employee who elects coverage and files claims — and it must hold a single, reconciled view of every dollar across all three.

The system models the full arc of voluntary coverage: an employer stands up products and an open-enrollment period; an employee elects a product and has a premium frozen against the guaranteed-issue window; payroll posts deductions that keep the policy funded; the employee files a claim that a carrier adjuster adjudicates against a benefit schedule and an annual cap; an approved claim is disbursed by direct deposit; and, on termination, the policy can be ported to direct-bill billing so coverage survives the job. Two themes run through every workflow and govern the hardest requirements. First, **ledger reconciliation**: benefit dollars paid out, annual caps, and per-pay-period deductions must always reconcile, even when claims are reopened, voided, or returned, so every payout has a precise compensating reversal. Second, **compliance**: Section 125 pre-tax irrevocability, guaranteed-issue versus evidence-of-insurability pricing, lifetime occurrence limits, and account-verification gates are all hard rules the platform enforces rather than advises.

Because the platform serves automated payroll and clock-driven enrollment timing, determinism is a first-class concern: enrollment timing and claim eligibility are decided against a server-controlled logical clock rather than wall-clock time, so the same sequence of calls always yields the same guaranteed-issue decision and the same surcharge.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. All resources live as peer collections under the `/benefits` prefix; the platform exposes no nested URL paths, and every parent-to-child relationship is discovered through a filtered list endpoint rather than a nested route.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognizes five roles, spelled exactly as follows: `BenefitsAdmin`, `ClaimsAdjuster`, `Employee`, `Payroll`, and `System`. `BenefitsAdmin` is the employer-side administrator that manages products, schedule lines, enrollment periods, employees, the enrollment lifecycle, and account verification. `ClaimsAdjuster` is the carrier-side adjuster that reviews, approves, denies, reopens, voids, disburses, and returns claims. `Employee` is the self-service member that enrolls, declines, adds disbursement accounts, files claims, and ports terminated policies. `Payroll` posts payroll-deduction outcomes that drive policy funding. `System` is an automation role that controls the logical clock and may also post payroll deductions. No role can perform another role's exclusive operations.

Role identity binds to resources as follows. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee` entity; ownership checks on any resource that references an `Employee` compare the resource's owning employee to `X-User-ID`. When `X-User-Role` is any of `BenefitsAdmin`, `ClaimsAdjuster`, `Payroll`, or `System`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned and defaults to 10 when omitted; its minimum accepted value is 1 and its maximum is 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0. A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_VALIDATION_PAGINATION`.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the count of all matching records before the page window is applied and `has_more` indicates whether records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits; both `created_at` and `updated_at` are minted from the server logical clock (§2.5), not the host wall-clock. Most resources additionally carry an `updated_at` timestamp (same format), refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by one on every mutation of the resource. These two fields support optimistic concurrency and change tracking and are present on `Employer`, `PlanProduct`, `EnrollmentPeriod`, `Employee`, `DisbursementAccount`, `Enrollment`, `PayrollDeduction`, `Claim`, `Disbursement`, `PortabilityConversion`, and `Section125Election`.

One entity is the exception. A `BenefitScheduleItem` is immutable after creation: it carries only `id` and `created_at`, and it has neither an `updated_at` nor a `version` field. Whenever a derived field on a resource is recomputed — for example, the running benefit ledger on an enrollment or the aggregate deduction total on an employee — that recomputation is itself a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Temporal Determinism

All time-sensitive decisions are made against a server-controlled logical clock rather than the host wall-clock. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and it remains at that instant — never falling back to wall-clock time — until explicitly advanced. An automation capability lets the `System` role advance the clock to a supplied instant; the request supplies the target instant in the `to_iso8601` field, and the clock moves to that value; a missing or non-ISO-8601 `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and a successful set returns `200 OK` with an empty `data` object. The logical clock is what stamps an enrollment's `enrolled_at` and is the reference point against which a claim's `event_date` is judged, so any test scenario can reproduce guaranteed-issue and coverage decisions exactly.

### 2.6. Monetary Precision and Basis-Point Conversion

All monetary amounts are stored and exchanged as integer cents; there are no fractional-cent values in stored fields or response bodies. Two rounding disciplines apply depending on the calculation. Premium assessments that scale a base premium by a basis-point surcharge or load-up are rounded to whole cents using the round-half-up method. Basis points are interpreted against a denominator of 10000, so a value expressed in basis points is converted to a multiplier by dividing it by 10000 and adding one. Per-pay-period deduction amounts use a different discipline: they are computed by flooring to whole cents, with the discarded remainder carried to the final pay period of the benefit year (handled at payroll time). Flat scheduled benefit amounts are already integral cents and require no rounding. Occurrence counts and the consecutive-failure tally are plain integers.

### 2.7. Cross-Aggregate Referential Consistency and Path Resolution

The data model is flat: collections are peers under `/benefits`, linked by foreign-key fields rather than by URL nesting. Because of this, two layers of integrity protection apply to writes.

First, existence: every resource identifier named in a path or request body — employer, product, period, employee, enrollment, claim, account, and the like — must resolve to a real record. Identifiers are validated left-to-right in the order they appear, and the first unresolved identifier short-circuits the request with `ERR_NOT_FOUND`. Second, referential consistency across aggregates: when an enrollment is created, the chosen product must belong to the employer that owns the employee, and the chosen enrollment period must belong to that same employer; when a claim is filed, the named disbursement account must belong to the same employee that owns the enrollment, and the claimed event must resolve against the schedule of the enrolled product. A disbursement-account-to-enrollee mismatch is rejected with `ERR_REFERENCE_MISMATCH`; the failure of the claimed event to resolve against the enrolled product's schedule is instead reported as `ERR_EVENT_NOT_COVERED` (the covered-event gate of §3.8 and §2.10 priority 8), not as `ERR_REFERENCE_MISMATCH`. This referential check is applied when creating an enrollment and when filing a claim.

### 2.8. Parallel State Dimensions and Derived-Field Reconciliation

An `Enrollment` carries two state dimensions that evolve independently on different triggers. The **lifecycle dimension**, `lifecycle_status`, moves a policy through `PENDING`, `ACTIVE`, `TERMINATED`, `PORTED`, and `DECLINED`, of which `DECLINED` and `PORTED` are terminal. The **funding dimension**, `funding_status`, tracks whether premium is being collected and takes the values `UNFUNDED`, `CURRENT`, and `LAPSED`; it is cyclic, because a lapsed policy can be reinstated to current and can lapse again. A new enrollment begins `PENDING` on the lifecycle dimension and `UNFUNDED` on the funding dimension.

Several operations cascade across entities, and each cascade must be applied in full. Activating or terminating an enrollment (the two lifecycle transitions that change its `ACTIVE` membership) forces a recomputation of the owning employee's aggregate weekly deduction; a funding-dimension lapse does not, on its own, trigger this recomputation, because the aggregate sums every lifecycle-`ACTIVE` enrollment regardless of its `funding_status` and a lapse leaves the enrollment lifecycle-`ACTIVE` (so its contribution is unchanged). Terminating an employee cascades termination to that employee's `ACTIVE` enrollments and revokes their locked cafeteria-plan elections. Approving, reopening, voiding, disbursing, or returning a claim mutates the enrollment's benefit ledger. Every one of these cascades mutates the touched resources, refreshing their `updated_at` and incrementing their `version`, exactly as described in §2.4. One exception governs the funding recompute that runs on a payroll posting: the enrollment's `updated_at`/`version` are refreshed only when the posting actually changes `funding_status` to a new value; a posting that recomputes the funding walk but leaves `funding_status` unchanged (for example a first or second consecutive `FAILED`, or a `POSTED` against an already-`CURRENT` policy) does not bump the enrollment's `version`. The system performs these reconciliations on its own whenever the triggering condition is met, without requiring a separate client call against the secondary resource.

### 2.9. Optimistic Concurrency on Portability Conversion

Porting a terminated policy is guarded by optimistic concurrency control on the parent enrollment. A request that creates a portability conversion must carry `expected_enrollment_version`, a non-optional field that holds the `version` of the target `Enrollment` the client last observed. The server compares it to the enrollment's current `version`; if they do not match — because a reinstatement payroll posting or a benefit credit-back advanced the enrollment's `version` after the client's last read, leaving the client's view of the terminated enrollment stale — the create is rejected with `ERR_STALE_ENROLLMENT_VERSION` at HTTP status 412. This is the only endpoint that takes a version field; no other write requires or consults `expected_enrollment_version`.

### 2.10. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or malformed user context (`ERR_MISSING_USER_CONTEXT`, priority 1) is detected before role authorization (`ERR_FORBIDDEN_ROLE`, priority 2). Resource existence is checked next (`ERR_NOT_FOUND`, priority 3), followed by cross-aggregate referential consistency (`ERR_REFERENCE_MISMATCH`, priority 4) and then state-machine eligibility for the requested transition (`ERR_INVALID_STATE`, priority 5). Domain-specific business rules are evaluated after those gates: the Section 125 active-plan rule (`ERR_SECTION125_INACTIVE`, priority 6), the claim temporal-coverage rule (`ERR_EVENT_BEFORE_COVERAGE`, priority 7), the covered-event rule (`ERR_EVENT_NOT_COVERED`, priority 8), the account-verified rule (`ERR_ACCOUNT_NOT_VERIFIED`, priority 9), the lifetime-occurrence rule (`ERR_LIFETIME_MAX_REACHED`, priority 10), the annual-cap rule (`ERR_BENEFIT_EXHAUSTED`, priority 11), the funding rule (`ERR_ENROLLMENT_NOT_FUNDED`, priority 12), the porting-eligibility rule (`ERR_ALREADY_PORTED`, priority 13), the stale-version rule (`ERR_STALE_ENROLLMENT_VERSION`, priority 14), and the duplicate-enrollment rule (`ERR_DUPLICATE_ENROLLMENT`, priority 15). Field-level body validation (`ERR_INVALID_REQUEST`, priority 16) is the lowest-priority check relative to the numbered business-rule gates above, so it is reported only once those higher-priority gates have passed; however, required-body-field presence, type, enum, and field-constraint validation (which also raises `ERR_INVALID_REQUEST` — for example a missing required field, the `gi_window_end` ordering rule, or a non-9-digit `routing_number`) is performed inline while the request body is parsed, and therefore can surface before the existence (`ERR_NOT_FOUND`, priority 3) check of identifiers carried in that same body. The error codes not assigned a number above are operation-local state gates: `ERR_PRODUCT_NOT_OPEN`, `ERR_SCHEDULE_EMPTY`, and `ERR_EMPLOYEE_TERMINATED` occupy the state-eligibility slot (alongside priority 5) and are evaluated after existence and referential checks but before the numbered domain rules; `ERR_ENROLLMENT_NOT_ACTIVE` (payroll posting) and `ERR_CLAIM_ALREADY_PAID` (reopen/void) are likewise evaluated at that state-eligibility point, and the duplicate checks `ERR_DUPLICATE_PAY_PERIOD` and `ERR_DUPLICATE_SCHEDULE_EVENT` are evaluated after their operation's state gate. Lower priority numbers are evaluated first; the first failing check determines the response.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Employer

Every program begins with an employer. A `BenefitsAdmin` creates an `Employer` by supplying its `legal_name`, and the employer is born in `ACTIVE` `status` (the status dimension toggles between `ACTIVE` and `SUSPENDED`). Two configuration choices on the employer shape downstream behavior. The `section_125_plan_active` flag declares whether the employer sponsors a Section 125 cafeteria plan; it defaults to true when omitted and gates pre-tax elections. The `pay_periods_per_year` field sets payroll frequency and defaults to 52 when omitted; it must be one of 52 (weekly), 26 (biweekly), 24 (semimonthly), or 12 (monthly), and it is the divisor that converts a frozen weekly premium into a per-pay-period deduction.

The employer is readable by every role. Its identity anchors the employer-side aggregates — products, enrollment periods, and employees all carry an `employer_id` linking back to it.

### 3.2. Plan Products and the Benefit Schedule

A `BenefitsAdmin` defines the coverage an employer offers as `PlanProduct` records, each linked to its owner through `employer_id`. A product is created with a `policy_type` of `ACCIDENT`, `CRITICAL_ILLNESS`, or `HOSPITAL_INDEMNITY`, a marketing `product_name`, a base `weekly_premium_cents` (the per-week cost at guaranteed issue, before pay-period conversion, which must be zero or greater), and an `annual_benefit_cap_cents` (the maximum total non-wellness benefit the product pays per enrollment per benefit year, which must be zero or greater). Two rate knobs carry defaults: `eoi_surcharge_bps`, the evidence-of-insurability surcharge in basis points applied when an enrollment is created outside the guaranteed-issue window, defaults to 0; and `portability_loadup_bps`, the premium load-up in basis points applied when a policy is ported after termination, defaults to 1000. Both must be zero or greater. A product is created in `DRAFT` `status`.

A product's coverage is itemized by `BenefitScheduleItem` lines, each linked to its product through `plan_product_id`. A schedule line names an `event_code` — a covered-event code such as `FRACTURE_FEMUR`, `HEART_ATTACK`, or `HOSP_ADMIT` — that must be unique within its product; a second line attempting to reuse an `event_code` already present on the product is rejected with `ERR_DUPLICATE_SCHEDULE_EVENT`. Each line sets a `flat_benefit_cents`, the payout per occurrence of that event (zero or greater). It also carries `lifetime_max_occurrences`, the maximum number of times that event can be paid per enrollment over the policy's life, which defaults to 0 where 0 means unlimited and which must be zero or greater. Finally, the `is_wellness` flag (default false) marks the wellness/rider line: a wellness line is paid on its screening event, is exempt from the annual cap, and never touches the running benefit ledger. Schedule lines may be added only while the product is still in `DRAFT`.

A product moves from `DRAFT` to `OPEN` only when at least one `BenefitScheduleItem` exists for it; opening a product with no schedule lines is rejected with `ERR_SCHEDULE_EMPTY`. The `DRAFT` starting-state check is evaluated before the schedule-empty check, so opening a non-`DRAFT` product yields `ERR_INVALID_STATE` even when it also has no schedule lines. A `DRAFT` product cannot be enrolled into; only an `OPEN` product accepts enrollments. Opening requires the product to be in `DRAFT`, and a later close moves it from `OPEN` to the terminal `CLOSED` state, retiring it. Both transitions are performed by a `BenefitsAdmin`, and an attempt to open or close from the wrong starting state is an `ERR_INVALID_STATE`.

### 3.3. Enrollment Periods and the Guaranteed-Issue Window

A `BenefitsAdmin` frames each open-enrollment cycle as an `EnrollmentPeriod`, linked to its employer through `employer_id` and named by a `label` such as "OE-2026". The period defines the temporal envelope that prices every enrollment created within it. Its `gi_window_start` marks the start of the guaranteed-issue window (inclusive) and its `gi_window_end` marks the end (exclusive), with the constraint that `gi_window_end` must be strictly later than `gi_window_start`. A create whose `gi_window_end` is not strictly later than its `gi_window_start` is rejected with `ERR_INVALID_REQUEST`, and this window-ordering check is evaluated during body validation, before the employer-existence (`ERR_NOT_FOUND`) check. Its `benefit_year_start` defines the start of the benefit year against which the annual cap accumulates. A period is created in `SCHEDULED` `status`, is opened by a `BenefitsAdmin` to `OPEN`, and is later closed to the terminal `CLOSED` state; opening requires `SCHEDULED` and closing requires `OPEN`, with any wrong-state attempt rejected as `ERR_INVALID_STATE`.

The guaranteed-issue window is the single most consequential boundary in pricing. An enrollment whose stamped creation instant falls at or after `gi_window_start` and strictly before `gi_window_end` is treated as guaranteed issue, requiring no evidence of insurability and incurring no surcharge. An enrollment created at or after `gi_window_end` — or before `gi_window_start` — falls outside the window and requires evidence of insurability, incurring the product's surcharge. The exact pricing consequences are described in §3.5.

### 3.4. Employees and Disbursement Accounts

A `BenefitsAdmin` registers each worker as an `Employee` under an employer, supplying the `employer_id`, the `full_name`, and an `email` that must be unique among the employer's currently-employed (`EMPLOYED`) staff; a create that reuses such an email is rejected with `ERR_INVALID_REQUEST`. A new employee starts with `employment_status` of `EMPLOYED` (the alternative being `TERMINATED`) and a `total_weekly_deduction_cents` of 0. That last field is computed, not supplied: it is the sum of the per-pay-period deduction across all of the employee's `ACTIVE` enrollments, and it is recomputed whenever one of those enrollments is activated or terminated (a funding-dimension lapse does not itself trigger a recomputation). Concretely, the value is the sum of `weekly_deduction_cents` over every enrollment of this employee whose `lifecycle_status` is `ACTIVE`, irrespective of `funding_status`; enrollments in any other lifecycle state contribute nothing.

To receive claim payouts, an employee needs a direct-deposit target. A `DisbursementAccount` is added — by either a `BenefitsAdmin` or the `Employee` — with the owning `employee_id`, a `routing_number` that must be exactly 9 digits, and the `account_last4` capturing the last four digits of the deposit account (required as a non-empty string, but otherwise stored verbatim with no length or digit check). A non-9-digit routing number is a field-level validation failure (`ERR_INVALID_REQUEST`), and the routing-number format check is evaluated during body validation, before the employee-existence (`ERR_NOT_FOUND`) check. A new account begins with `verification_status` of `UNVERIFIED` and `is_default` false. A `BenefitsAdmin` later verifies an account, moving its `verification_status` to `VERIFIED`; the first account that becomes verified for an employee is also marked as that employee's default by setting `is_default` to true, and at most one verified account is the employee's default at any time. Direct-deposit claim payouts require a `VERIFIED` account, as enforced in §3.8.

### 3.5. Creating an Enrollment and Freezing the Premium

An enrollment is the contract that binds an employee to a product within a period. A `BenefitsAdmin` or an `Employee` creates an `Enrollment` by supplying the `employee_id`, the chosen `plan_product_id`, the `enrollment_period_id` that establishes the guaranteed-issue window and benefit year, and an optional `pretax` flag (default false) electing pre-tax payroll treatment under Section 125. On creation the server stamps `enrolled_at` from the logical clock — this instant alone decides guaranteed-issue membership — sets `lifecycle_status` to `PENDING`, and sets `funding_status` to `UNFUNDED`. An employee may hold at most one non-terminal enrollment per product, where non-terminal means `lifecycle_status` in `PENDING` or `ACTIVE`; a second such enrollment in the same product is rejected with `ERR_DUPLICATE_ENROLLMENT`.

Two computations run at creation and freeze their results onto the enrollment. The first sets `gi_status` and `weekly_premium_cents`. If `enrolled_at` is at or after the period's `gi_window_start` and strictly before its `gi_window_end`, then `gi_status` is `GUARANTEED_ISSUE` and `weekly_premium_cents` is exactly the product's base `weekly_premium_cents`. Otherwise `gi_status` is `EVIDENCE_REQUIRED` and `weekly_premium_cents` is the product base scaled by the surcharge: take the base, multiply it by one plus the product's `eoi_surcharge_bps` divided by 10000, and round the result half-up to whole cents. The second computation converts that frozen weekly premium into a per-pay-period deduction and writes it to `weekly_deduction_cents`: multiply the frozen `weekly_premium_cents` by 52 to obtain the annual amount, then divide that annual amount by the employer's `pay_periods_per_year` and floor the quotient to whole cents (the dropped remainder is carried to the year's final pay period at payroll time). When the employer pays weekly, the per-period deduction equals the weekly premium; when the employer pays monthly, the per-period deduction is the annual amount divided by twelve and floored, a larger per-period figure.

The enrollment's benefit ledger is initialized at creation: `benefit_paid_cents`, the running total of capped benefit dollars paid to this enrollment in the current benefit year (wellness excluded), starts at 0, and `benefit_remaining_cents` is the product's `annual_benefit_cap_cents` minus `benefit_paid_cents`, floored at 0. A read of an enrollment returns its frozen premium, its deduction, both benefit-ledger fields, and its `version`.

### 3.6. Activating, Declining, and Terminating Enrollments; Section 125

A `PENDING` enrollment is brought to life by a `BenefitsAdmin`. Activation moves `lifecycle_status` from `PENDING` to `ACTIVE` and is allowed only when the enrollment is `PENDING`; the product must be `OPEN` (otherwise `ERR_PRODUCT_NOT_OPEN`), the employee must still be `EMPLOYED` (otherwise `ERR_EMPLOYEE_TERMINATED`), and, if the enrollment was elected `pretax`, the employer's `section_125_plan_active` must be true (otherwise `ERR_SECTION125_INACTIVE`). On a successful activation the system recomputes the employee's `total_weekly_deduction_cents`, adding this enrollment's `weekly_deduction_cents` into the aggregate. If the enrollment is pre-tax, activation also creates a `Section125Election` in `LOCKED` `status`, linked through `enrollment_id` and carrying a `plan_year_label` for the cafeteria plan year (set to the four-digit calendar year of the enrollment period's `benefit_year_start`, as a string, falling back to the year of the enrollment's `enrolled_at`); its `qualifying_event` is initialized to `null` and is populated only on later revocation. The election's `annual_pretax_amount_cents` is locked at the enrollment's frozen `weekly_premium_cents` multiplied by 52, representing the irrevocable annual pre-tax election.

Alternatively, a `PENDING` enrollment may be declined by a `BenefitsAdmin` or an `Employee`, moving `lifecycle_status` from `PENDING` to the terminal `DECLINED` state with no further side effects; declining is permitted only from `PENDING`.

An `ACTIVE` enrollment can be terminated, either directly by a `BenefitsAdmin` against the enrollment or as a cascade from terminating the employee. Termination moves `lifecycle_status` from `ACTIVE` to `TERMINATED` and is allowed only from `ACTIVE`. It carries three side effects: the employee's `total_weekly_deduction_cents` is recomputed, removing this enrollment's `weekly_deduction_cents` from the aggregate; if a `LOCKED` `Section125Election` governs this enrollment, it is transitioned to `REVOKED` with its `qualifying_event` set to `TERMINATION`; and the enrollment's `funding_status` is set to `LAPSED`. The Section 125 irrevocability rule means a `LOCKED` election can only flip to `REVOKED` on a qualifying life event, and here that event is precisely the enrollment's `ACTIVE`-to-`TERMINATED` move; the election's `qualifying_event` records the reason (for example `TERMINATION` or `MARRIAGE`) and there is no direct endpoint that mutates an election. When a `BenefitsAdmin` terminates an `Employee`, the employee's `employment_status` becomes `TERMINATED`, each of that employee's `ACTIVE` enrollments undergoes the same `ACTIVE`-to-`TERMINATED` transition with all of its side effects, the governing locked elections are revoked, and the employee's aggregate deduction total is recomputed.

### 3.7. Payroll Deductions and the Funding Dimension

The funding dimension is driven entirely by payroll. A `Payroll` processor — or the `System` automation — posts a deduction outcome against an `ACTIVE` enrollment by supplying a `pay_period_index` and an `outcome`. The `pay_period_index` is a monotonic sequence number within the benefit year and must be unique per enrollment; a second posting reusing an index already recorded for the enrollment is rejected with `ERR_DUPLICATE_PAY_PERIOD`, and the index must be zero or greater. The `outcome` is either `POSTED` (the deduction funds the enrollment) or `FAILED` (the deduction counts toward lapse). Posting a deduction creates a `PayrollDeduction` record linked through `enrollment_id`, whose `amount_cents` equals the enrollment's `weekly_deduction_cents` at posting time. A posting is permitted only while the enrollment's `lifecycle_status` is `ACTIVE`; posting against a non-active enrollment is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`.

The funding state evolves from a chronological walk of the enrollment's deductions, processed in ascending `pay_period_index` order — not by creation order — while maintaining a running count of consecutive failures. A `POSTED` outcome resets the consecutive-failure count to 0 and sets `funding_status` to `CURRENT`, whether the enrollment was previously `UNFUNDED` or `LAPSED`; reinstating a lapsed policy is simply a `POSTED` outcome that returns it to `CURRENT`. A `FAILED` outcome increments the consecutive-failure count; the policy lapses to `LAPSED` only when that count reaches 3. The boundary is exact: the third consecutive `FAILED` deduction lapses the policy, while the second consecutive failure does not. Because a posting can return a lapsed policy to current and a current policy can lapse again, the funding dimension cycles between `CURRENT` and `LAPSED` over the life of the enrollment.

### 3.8. Filing and Adjudicating Claims

A claim is the request to convert a covered event into cash. A `BenefitsAdmin` or an `Employee` files a `Claim` against an enrollment by supplying the `enrollment_id`, the `disbursement_account_id` that names the direct-deposit target for any payout, the `event_code` for the covered event, and the `event_date` on which the event occurred. At filing, the claim is recorded in `SUBMITTED` `status` with a provisional `claimed_cents` equal to the raw scheduled flat benefit for the event — the `flat_benefit_cents` of the matching schedule line — and an `approved_cents` and `paid_cents` of 0; the claim also carries a `denial_reason` field that is initialized to `null` at filing and is populated only when the claim is denied. `claimed_cents` at this stage is the raw schedule amount, not yet limited by any cap or lifetime maximum. Two gates apply at filing. The `event_code` must match a `BenefitScheduleItem` on the enrolled product, or the claim is rejected with `ERR_EVENT_NOT_COVERED`. The `event_date` must fall on or after the enrollment's `enrolled_at` and the enrollment must be `ACTIVE` at filing time, or the claim is rejected with `ERR_EVENT_BEFORE_COVERAGE`.

A `ClaimsAdjuster` works a claim through a branching review machine. Beginning review moves the claim from `SUBMITTED` to `UNDER_REVIEW` (permitted only from `SUBMITTED`). From `UNDER_REVIEW`, the adjuster either denies the claim — moving it to the terminal `DENIED` state and writing the supplied `denial_reason` — or approves it, moving it to `APPROVED`. Both branches require the claim to be `UNDER_REVIEW`.

Approval is the moment the benefit is adjudicated, and three preconditions guard it beyond the state check. The enrollment's `funding_status` must be `CURRENT`, or approval is rejected with `ERR_ENROLLMENT_NOT_FUNDED`. The lifetime-occurrence limit must not already be reached: for a schedule line whose `lifetime_max_occurrences` is greater than 0, the system counts the prior claims on this enrollment for the same `event_code` whose `status` is `APPROVED` or `PAID`; if that count is already at or above `lifetime_max_occurrences`, approval is rejected with `ERR_LIFETIME_MAX_REACHED`. And the adjudicated benefit must be positive: a non-wellness claim whose enrollment has no annual benefit remaining is rejected with `ERR_BENEFIT_EXHAUSTED`.

The adjudication that runs on approval sets `approved_cents` as follows. For a wellness line, the approval is uncapped: `approved_cents` equals `claimed_cents`, the payout bypasses the annual cap entirely, and it does not touch `benefit_paid_cents`. For a non-wellness line, the remaining annual room is the product's `annual_benefit_cap_cents` minus the enrollment's current `benefit_paid_cents`, floored at 0, and `approved_cents` is the lesser of `claimed_cents` and that remaining room; if the remaining room is 0 the adjudication would yield 0, which is exactly the exhausted case rejected above. On a successful non-wellness approval the enrollment's `benefit_paid_cents` is increased by `approved_cents` and `benefit_remaining_cents` is recomputed as the cap minus the new paid total, floored at 0; wellness approvals leave the ledger untouched. All of these amounts are whole cents with no rounding.

### 3.9. Disbursing, Reversing, and Reopening Claims

Once a claim is `APPROVED`, a `ClaimsAdjuster` disburses it by direct deposit. Disbursing requires the claim to be `APPROVED` and the target `DisbursementAccount` to be `VERIFIED`; disbursing to an unverified account is rejected with `ERR_ACCOUNT_NOT_VERIFIED`. Disbursing creates a `Disbursement` record linked through `claim_id` and `disbursement_account_id`, with `amount_cents` equal to the claim's `approved_cents`. The disbursement is created and immediately settles: its `status` is `SETTLED`, and as its settlement side effect it sets the parent claim's `status` to `PAID` and the claim's `paid_cents` to the disbursement's `amount_cents`. The disbursement's lifecycle runs `INITIATED`, `SETTLED`, and `RETURNED`, where `SETTLED` is reached synchronously on creation against a verified account.

Three reversal paths conserve the benefit ledger, each crediting back exactly what was debited. An `APPROVED` claim that has not yet produced a settled disbursement may be **reopened** by a `ClaimsAdjuster`, moving it from `APPROVED` back to `UNDER_REVIEW`; reopening is blocked with `ERR_CLAIM_ALREADY_PAID` if a `SETTLED` disbursement exists for the claim. As its compensating action, reopening credits the enrollment's `benefit_paid_cents` back by the claim's `approved_cents` (wellness claims excluded, since they never debited the ledger), recomputes `benefit_remaining_cents`, and resets the claim's `approved_cents` to 0. Symmetrically, an `APPROVED` claim with no settled disbursement may be **voided** by a `ClaimsAdjuster`, moving it from `APPROVED` to the terminal `VOIDED` state; voiding is likewise blocked with `ERR_CLAIM_ALREADY_PAID` when a `SETTLED` disbursement exists, and it performs the same compensating credit-back of `benefit_paid_cents` (wellness excluded) and recompute of `benefit_remaining_cents` (voiding does not zero the claim's `approved_cents`, which is retained on the terminal `VOIDED` record). Finally, an ACH **return** on a `SETTLED` disbursement is recorded by a `ClaimsAdjuster`, moving the disbursement from `SETTLED` to the terminal `RETURNED` state (permitted only from `SETTLED`); the return credits the enrollment's `benefit_paid_cents` back by the disbursement's `amount_cents` (wellness excluded), recomputes `benefit_remaining_cents`, sets the parent claim's `status` back to `APPROVED`, and resets the claim's `paid_cents` to 0 — leaving the claim re-payable. Across all three reversals the credit-back is the exact inverse of the original debit, so the benefit ledger is conserved.

### 3.10. Porting a Terminated Policy

When coverage outlives employment, an `Employee` ports a terminated policy to direct-bill billing. Creating a `PortabilityConversion` moves the enrollment's `lifecycle_status` from `TERMINATED` to the terminal `PORTED` state. The enrollment must be `TERMINATED`, and there must be no existing `CONVERTED` portability conversion for it; an attempt to port a policy that is not terminated, or that already has a converted conversion, is rejected with `ERR_ALREADY_PORTED`. The request must also carry `expected_enrollment_version` carrying the enrollment `version` the client last observed; if it does not equal the enrollment's current `version`, the create is rejected with `ERR_STALE_ENROLLMENT_VERSION` as described in §2.9.

On success the system creates the `PortabilityConversion` in `CONVERTED` `status` (its terminal lifecycle alternative being `CANCELLED`), linked through `enrollment_id`, records the supplied `expected_enrollment_version` on the conversion record (which is echoed back in the response body), and computes its `direct_bill_weekly_cents`. The ported weekly premium is computed from the product's base `weekly_premium_cents` — deliberately the product base, not the enrollment's surcharged premium — scaled by one plus the product's `portability_loadup_bps` divided by 10000, with the result rounded half-up to whole cents. Creating the conversion also increments the enrollment's `version` by one.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code, while operations that modify an existing resource — including state transitions and reversals — return a `200 OK` status code. The two exceptions among creates are listed below: posting a payroll deduction and disbursing a claim each create a new resource and therefore return `201 Created`. The logical-clock capability returns `200 OK`. All list and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | System |
| POST | `/benefits/employers` | Create an employer | BenefitsAdmin |
| GET | `/benefits/employers/{employerId}` | Get an employer | BenefitsAdmin, ClaimsAdjuster, Payroll, Employee |
| POST | `/benefits/plan-products` | Create a plan product (DRAFT) | BenefitsAdmin |
| GET | `/benefits/plan-products` | List plan products, filterable by employer | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/plan-products/{planProductId}` | Get a plan product | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/plan-products/{planProductId}/open` | Open a product for enrollment | BenefitsAdmin |
| POST | `/benefits/plan-products/{planProductId}/close` | Close a product | BenefitsAdmin |
| POST | `/benefits/schedule-items` | Add a benefit-schedule line to a DRAFT product | BenefitsAdmin |
| GET | `/benefits/schedule-items` | List benefit-schedule lines, filterable by product | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/schedule-items/{scheduleItemId}` | Get a benefit-schedule line | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/enrollment-periods` | Create an enrollment period (SCHEDULED) | BenefitsAdmin |
| GET | `/benefits/enrollment-periods` | List enrollment periods, filterable by employer | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/enrollment-periods/{periodId}` | Get an enrollment period | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/enrollment-periods/{periodId}/open` | Open an enrollment period | BenefitsAdmin |
| POST | `/benefits/enrollment-periods/{periodId}/close` | Close an enrollment period | BenefitsAdmin |
| POST | `/benefits/employees` | Create an employee | BenefitsAdmin |
| GET | `/benefits/employees` | List employees, filterable by employer | BenefitsAdmin, ClaimsAdjuster |
| GET | `/benefits/employees/{employeeId}` | Get an employee | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/employees/{employeeId}/terminate` | Terminate an employee (cascades enrollments and elections) | BenefitsAdmin |
| POST | `/benefits/disbursement-accounts` | Add a direct-deposit account (UNVERIFIED) | BenefitsAdmin, Employee |
| GET | `/benefits/disbursement-accounts` | List disbursement accounts, filterable by employee | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/disbursement-accounts/{accountId}` | Get a disbursement account | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/disbursement-accounts/{accountId}/verify` | Mark a disbursement account VERIFIED | BenefitsAdmin |
| POST | `/benefits/enrollments` | Enroll an employee in a product; freezes premium and GI status | BenefitsAdmin, Employee |
| GET | `/benefits/enrollments` | List enrollments, filterable by employee/product/period | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/enrollments/{enrollmentId}` | Get an enrollment | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/enrollments/{enrollmentId}/activate` | Activate a PENDING enrollment | BenefitsAdmin |
| POST | `/benefits/enrollments/{enrollmentId}/decline` | Decline a PENDING enrollment | BenefitsAdmin, Employee |
| POST | `/benefits/enrollments/{enrollmentId}/terminate` | Terminate an ACTIVE enrollment | BenefitsAdmin |
| POST | `/benefits/enrollments/{enrollmentId}/payroll-deductions` | Post a payroll-deduction outcome | Payroll, System |
| GET | `/benefits/payroll-deductions` | List payroll deductions, filterable by enrollment | BenefitsAdmin, Payroll, Employee |
| GET | `/benefits/payroll-deductions/{deductionId}` | Get a payroll deduction | BenefitsAdmin, Payroll, Employee |
| POST | `/benefits/enrollments/{enrollmentId}/portability-conversions` | Port a TERMINATED enrollment to direct-bill | Employee |
| GET | `/benefits/portability-conversions` | List portability conversions, filterable by enrollment | BenefitsAdmin, Employee |
| GET | `/benefits/portability-conversions/{conversionId}` | Get a portability conversion | BenefitsAdmin, Employee |
| GET | `/benefits/section125-elections` | List Section 125 elections, filterable by enrollment | BenefitsAdmin, Employee |
| GET | `/benefits/section125-elections/{electionId}` | Get a Section 125 election | BenefitsAdmin, Employee |
| POST | `/benefits/claims` | File a claim under an enrollment | Employee, BenefitsAdmin |
| GET | `/benefits/claims` | List claims, filterable by enrollment/account | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/claims/{claimId}` | Get a claim | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/claims/{claimId}/start-review` | Move a claim SUBMITTED to UNDER_REVIEW | ClaimsAdjuster |
| POST | `/benefits/claims/{claimId}/approve` | Approve a claim; adjudicate payout and debit the benefit ledger | ClaimsAdjuster |
| POST | `/benefits/claims/{claimId}/deny` | Deny a claim | ClaimsAdjuster |
| POST | `/benefits/claims/{claimId}/reopen` | Reopen an APPROVED claim; credit-back the ledger | ClaimsAdjuster |
| POST | `/benefits/claims/{claimId}/void` | Void an APPROVED, unpaid claim; credit-back the ledger | ClaimsAdjuster |
| POST | `/benefits/claims/{claimId}/disburse` | Create a direct-deposit disbursement for an APPROVED claim | ClaimsAdjuster |
| GET | `/benefits/disbursements` | List disbursements, filterable by claim/account | BenefitsAdmin, ClaimsAdjuster, Employee |
| GET | `/benefits/disbursements/{disbursementId}` | Get a disbursement | BenefitsAdmin, ClaimsAdjuster, Employee |
| POST | `/benefits/disbursements/{disbursementId}/return` | Record an ACH return on a SETTLED disbursement | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRODUCT_NOT_OPEN` | 409 |
| `ERR_SCHEDULE_EMPTY` | 409 |
| `ERR_EMPLOYEE_TERMINATED` | 409 |
| `ERR_SECTION125_INACTIVE` | 409 |
| `ERR_EVENT_BEFORE_COVERAGE` | 422 |
| `ERR_EVENT_NOT_COVERED` | 422 |
| `ERR_ACCOUNT_NOT_VERIFIED` | 409 |
| `ERR_LIFETIME_MAX_REACHED` | 409 |
| `ERR_BENEFIT_EXHAUSTED` | 409 |
| `ERR_ENROLLMENT_NOT_FUNDED` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_ALREADY_PORTED` | 409 |
| `ERR_STALE_ENROLLMENT_VERSION` | 412 |
| `ERR_CLAIM_ALREADY_PAID` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_DUPLICATE_PAY_PERIOD` | 409 |
| `ERR_DUPLICATE_SCHEDULE_EVENT` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_VALIDATION_PAGINATION` | 422 |
