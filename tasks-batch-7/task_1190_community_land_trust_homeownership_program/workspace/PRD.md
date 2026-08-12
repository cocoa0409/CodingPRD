# Community Land Trust Homeownership Program API — Product Requirements Document

## 1. Introduction

Community land trusts exist to solve a problem that the private housing market cannot solve on its own: how to keep a home permanently affordable for generations of low- and moderate-income buyers, even as the underlying land appreciates far faster than household incomes. The mechanism is a long-term ground lease. A household buys the building (the "improvements" or leasehold interest) at an affordable price; the trust retains ownership of the land; and when the household eventually sells, a resale formula splits the appreciation between the outgoing seller and the trust so the home stays affordable for the next buyer.

This document describes the API for operating one or more such programs. The system manages the full homeownership lifecycle under a community land trust: verifying buyer eligibility through income certification, tracking homebuyer education completion, executing ground leases with subsidy-retention math, billing monthly ground-lease fees, processing fee delinquency through a default/cure pipeline, inspecting occupied units on a recurring cycle, matching the waitlist to resales, and approving household refinances within program-set loan-to-value limits. Several of these concerns are deeply interlocked — a single income recertification can simultaneously flip a household's eligibility, recompute its ground-lease fee, and re-amount the pending fee ledger; a single failed inspection can trigger a maintenance default that escalates to foreclosure if not cured.

The audience for this document is the engineering team building the service. The business domain is heavily regulated and audit-driven; segregation of duties is enforced wherever a financial or compliance decision is recorded, optimistic concurrency control guards every state-changing write whose outcome depends on a recently-read parent entity, and every lifecycle state transition carries an explicit precondition. Where this document introduces a term of art (ground lease, subsidy retention, AMI fraction, resale formula), it does so in narrative and then uses that term consistently thereafter.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API call is authenticated by two headers: `X-User-ID` (the identifier of the acting principal) and `X-User-Role` (the role the principal is acting in). If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the headers are present but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

Seven roles are defined, spelled exactly as follows:

- `PlatformAdmin` — operator of the platform itself; creates new programs and drives the logical clock.
- `ProgramAdmin` — administrator of a specific CLT program; manages education courses, units, and program-wide parameter updates.
- `IntakeSpecialist` — front-line staff; registers households, records education completions, and submits income certifications on behalf of households.
- `ComplianceOfficer` — reviews and decides income certifications; is barred from reviewing a certification they themselves submitted.
- `LeaseManager` — manages ground leases, defaults, resales, and refinances; cannot certify income.
- `Inspector` — performs unit inspections and records their outcomes.
- `Household` — a buyer or applicant household acting on its own resources.

For every role except `Household`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by`, `reviewed_by`, `issued_by`, `recorded_by`, or `inspector_user_id` — but does not compare it against any entity's `id` to resolve ownership.

When `X-User-Role` is `Household`, `X-User-ID` is the `id` of the acting `Household` resource. Ownership checks on any resource that references a `Household` compare the resource's household foreign-key field to `X-User-ID`. A `Household` caller can pay its own lease fees, submit or withdraw its own refinance request, withdraw its own waitlist entry, co-create its own income certification or waitlist entry alongside an `IntakeSpecialist`, and co-list its own leasehold for resale alongside a `LeaseManager`.

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

List endpoints accept two query-string parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. The four pagination fields `limit`, `offset`, `total_count`, and `has_more` are returned inside `meta` on every list response. Sort order is uniform across all list endpoints: results are returned ordered by `created_at` ascending. No list endpoint accepts a sort override parameter.

### 2.4. Common Resource Properties

Every persistent resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Most resources additionally carry an `updated_at` timestamp of the same format and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of the resource.

Two resources do not carry `updated_at` or `version`: `EducationCompletion` and `LeaseFee`. These carry only `id` and `created_at`; their lifecycle is either append-and-observe (education completions) or status-only mutation recorded through `paid_at` and `paid_amount_cents` (fees). Any read of an `EducationCompletion` or `LeaseFee` will find `updated_at` and `version` absent from the representation; implementers must not synthesize them.

### 2.5. Nested Resource Addressing

Most resources in the system live at a nested path that expresses their containment — a `Household` lives under a `CLTProgram`; an `IncomeCertification` lives under a `Household`; a `GroundLease` lives under a `Unit`; a `DefaultNotice`, `LeaseFee`, or `RefinanceRequest` lives under a `GroundLease`; an `InspectionRecord` or `ResaleListing` lives under a `Unit`; a `WaitlistEntry` or `EducationCompletion` lives under a `Household`. Path parameters are validated strictly from left to right: each segment identifier must resolve to an existing resource that is a descendant of the resource identified by the segment before it, all within the same program scope. A mismatch at any level — for example, a `certId` that names a certification belonging to a different `householdId` — returns `ERR_NOT_FOUND`. This rule applies to every nested endpoint.

In addition to the nested addressing, the system exposes a flat top-level alias for every primary resource (`/households/{id}`, `/units/{id}`, `/leases/{id}`, `/income-certifications/{id}`, `/education-courses/{id}`, `/education-completions/{id}`, `/fees/{id}`, `/default-notices/{id}`, `/inspections/{id}`, `/resale-listings/{id}`, `/refinance-requests/{id}`, `/waitlist-entries/{id}`), and a corresponding top-level list endpoint for each collection with optional query filters. These aliases are conveniences for cross-reference reverse-reachability and do not change the underlying containment rule.

### 2.6. Optimistic Concurrency Control

Five write operations are guarded by optimistic concurrency control on a parent entity. Each requires the request body to carry a non-optional `expected_<parent>_version` field naming the version of the parent entity that the client last observed. If the value supplied does not match the parent entity's current `version` at the time the write is attempted, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The five guarded operations, the required field, and the parent they guard are:

- Activating a ground lease requires `expected_unit_version` matching the target `Unit.version`. This catches the case where another actor has just activated a lease on the same unit (which legitimately transitions the unit to `OCCUPIED` and advances its version) and the current writer's view is stale.
- Terminating a ground lease requires `expected_lease_version` matching the `GroundLease.version`. This catches the case where a default notice has just been issued (bumping the lease to `IN_DEFAULT` and incrementing its version) and the terminator's view is stale.
- Foreclosing a ground lease requires `expected_lease_version` matching the `GroundLease.version`. This catches the case where a cure event has just restored the lease to `ACTIVE` and the forecloser's view is stale.
- Running waitlist matching against a resale listing requires `expected_listing_version` matching the `ResaleListing.version`. This catches the case where another operator has just re-priced the listing via recalculation and the matcher's view of `asking_price_cents` is stale.
- Recording an approved refinance against a ground lease requires `expected_lease_version` matching the `GroundLease.version`. This catches the case where a default notice or cure event has mutated the lease between approval and recording.

Endpoints not on this list do not take a version field. In particular, submitting, approving, rejecting, or withdrawing a refinance request does not carry an `expected_lease_version`; only the final recording step does.

### 2.7. Precision and Rounding

All monetary values in the system are stored and transmitted as integer cents (no fractional cents). Wherever a multiplication, division, or other arithmetic operation would produce a fractional cent, the result is rounded half-up to the nearest integer cent. Where a ratio is exposed as a numeric field (most notably `ami_pct`, `ami_pct_at_cert`, and `computed_ltv`), the ratio is rounded half-up to 4 decimal places. The phrase "rounded half-up" means standard commercial rounding: a value whose fractional part is exactly one half of the rounding unit rounds away from zero.

### 2.8. Segregation of Duties

Two decision points in the system require that the person who records a decision not be the person who submitted the underlying material. When a `ComplianceOfficer` approves or rejects an `IncomeCertification`, the acting `X-User-ID` must differ from the certification's `submitted_by`. When a `LeaseManager` approves or rejects a `RefinanceRequest`, the acting `X-User-ID` must differ from the request's `submitted_by`. In both cases, if the acting identifier equals `submitted_by`, the request is rejected with `ERR_SO_DUTY_VIOLATION` (HTTP 409). The system records the deciding operator in the entity's `reviewed_by` field.

### 2.9. Logical Clock

The server maintains a logical clock used for all time-based business rules. At server startup, before any clock operation has been invoked, the logical clock reads exactly `2026-05-01T00:00:00Z`; it must not fall back to real wall-clock time. A dedicated endpoint advances the logical clock, accepting a request body containing `to_iso8601` — an ISO 8601 UTC timestamp naming the instant to advance to — and returning a body containing `now_iso8601`, the new logical time. Advancing the clock is a privileged operation restricted to `PlatformAdmin` and `ProgramAdmin`, and it triggers a re-evaluation of every time-based transition in the system: household `ELIGIBLE` → `EXPIRED` lapses, waitlist entry `ACTIVE` → `EXPIRED` lapses, default notice `OPEN` → `ESCALATED` escalations past the cure deadline, lease fee `PENDING` → `LATE` markings past the grace period, ground lease `ACTIVE` → `EXPIRED` lapses at `end_date`, education completion expiry, and the auto-scheduling of pending inspections whose computed due date has arrived.

### 2.10. Validation Ordering

Every mutating endpoint runs a fixed sequence of checks. The order matters because the visible error code depends on which check fires first. The sequence is:

1. **Authentication and shape** — `X-User-ID` and `X-User-Role` must be present and well-formed; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization** — the named role must be permitted to invoke the operation; otherwise `ERR_UNAUTHORIZED`.
3. **Existence** — every path-template identifier must resolve within its parent scope; otherwise `ERR_NOT_FOUND`.
4. **State** — the target resource must be in a state that permits the requested transition; otherwise `ERR_INVALID_STATE`.
5. **Body referential integrity** — every foreign-key identifier in the request body (for example `course_id`, `household_id`, `lease_id`) must resolve to an existing entity in the same program scope; otherwise `ERR_REFERENCE_NOT_FOUND`.
6. **Segregation of duties** — for approval actions on `IncomeCertification` and `RefinanceRequest`, the actor must differ from `submitted_by`; otherwise `ERR_SO_DUTY_VIOLATION`.
7. **Business-rule checks** — the specific guard clauses enumerated in §3 (cure evidence, arrears clearance, household eligibility, unit blocked, refinance limits, education completeness, cure windows, cert staleness, payment sufficiency, funds confirmation, multi-lease, no-eligible-buyer, unit-occupied).
8. **Optimistic concurrency** — for the five OCC-guarded operations listed in §2.6, the `expected_*_version` must match the parent's current version; otherwise `ERR_STALE_VERSION`.

The remaining checks each bind to a specific endpoint and carry their own `error_id` and HTTP status; the rule text and trigger conditions appear in §3 alongside the workflows they protect.

## 3. Business Logic & Workflows

### 3.1. Program Setup and Parameterization

A `PlatformAdmin` operator creates a new program by supplying its `name`, the `ami_table_effective_date` marking when the current Area Median Income schedule takes effect, the baseline `area_median_income_cents` representing 100% AMI for the metro area as an annual figure in whole cents, and the `max_eligibility_ami_pct` ceiling — for example `0.80` to indicate that households at or below 80% of AMI may qualify. The same create call pins the resale formula in force via `resale_formula_kind`, which is one of `APPRAISAL_BASED` or `INDEXED`, and supplies the `ground_lease_base_fee_cents` — the pre-subsidy monthly ground lease fee in cents.

Several parameters have defaults that may be overridden at creation time. `ground_lease_term_years` defaults to 99. `low_income_fee_reduction_pct` defaults to `0.5` (that is, half the base fee waived for households at or below 50% AMI). `indexed_annual_appreciation_pct` defaults to `0.015` (a 1.5% per year simple appreciation rate used by the `INDEXED` resale formula variant). `appraisal_seller_share_pct` defaults to `0.25` (the seller keeps 25% of market appreciation under the `APPRAISAL_BASED` variant). `max_refi_ltv_pct` defaults to `0.95` (refinances may not push loan-to-value above 95%). `max_equity_withdrawal_cents` defaults to `0` (cash-out refinancing is prohibited unless the program admin raises this cap). `default_cure_window_days` defaults to 30. `inspection_cycle_months` defaults to 24.

A newly created program lands in `ACTIVE` status. A `ProgramAdmin` may suspend it (`ACTIVE` → `SUSPENDED`), reinstate it (`SUSPENDED` → `ACTIVE`), or close it (`ACTIVE` or `SUSPENDED` → `CLOSED`). Suspending a program blocks the creation of new households, new ground leases, and new resale listings; existing households, leases, and listings are not themselves transitioned. Closing a program is allowed only when no `GroundLease` is in `ACTIVE`, `IN_DEFAULT`, or `CURE_PERIOD` status and no `ResaleListing` is in `OPEN`, `MATCHED`, or `UNDER_CONTRACT` status; when closure succeeds, every `WaitlistEntry` still in `ACTIVE` under that program is moved to `EXPIRED`.

A `ProgramAdmin` may also update program parameters in place — including `area_median_income_cents`, `max_eligibility_ami_pct`, `ground_lease_base_fee_cents`, `low_income_fee_reduction_pct`, `resale_formula_kind`, `indexed_annual_appreciation_pct`, `appraisal_seller_share_pct`, `max_refi_ltv_pct`, `max_equity_withdrawal_cents`, `default_cure_window_days`, `inspection_cycle_months`, and the descriptive fields `name` and `ami_table_effective_date`. The update increments the program's `version` by 1 and, crucially, when `area_median_income_cents` changes, the system recomputes every household's `ami_pct`, recomputes every active lease's `monthly_fee_cents`, and re-amounts every `PENDING` `LeaseFee` row whose `due_date` is in the future.

### 3.2. Household Intake and Income Certification

An `IntakeSpecialist` registers a new applicant household by supplying `legal_name`, `household_size`, `annual_gross_income_cents`, and optionally a free-form `notes` string. `household_size` must be at least 1; a value below 1 is rejected with `ERR_INVALID_REQUEST`. The household is created under the target program — its `program_id` field records the owning program's id — with `eligibility_status` set to `PENDING`. It carries `education_required` defaulting to `true`, an initially null `education_completed_at`, null `active_lease_id`, and null `waitlist_entry_id`.

Income verification is handled through a separate `IncomeCertification` record, which an `IntakeSpecialist` or the `Household` itself may submit. The submission captures `tax_year`, the `reported_annual_income_cents` the household self-reported, the `verified_annual_income_cents` after staff verification (which may differ from reported), and the `household_size_at_cert` used for AMI size adjustment on this cert. The server stamps `submitted_by` with the acting `X-User-ID` and computes `ami_pct_at_cert` immediately: the ratio of `verified_annual_income_cents` to the product of the program's `area_median_income_cents` and a household-size adjustment factor, rounded half-up to 4 decimal places.

The size adjustment is a fixed lookup table: a household of 1 uses 0.70; 2 uses 0.80; 3 uses 0.90; 4 uses 1.00; 5 uses 1.08; 6 uses 1.16; 7 uses 1.24; 8 or more uses 1.32. A certification is created in `SUBMITTED` status; a `ComplianceOfficer` moves it `SUBMITTED` → `UNDER_REVIEW`, then `UNDER_REVIEW` → `APPROVED` or `UNDER_REVIEW` → `REJECTED`. Approval requires the segregation-of-duties check (the acting officer's `X-User-ID` must differ from `submitted_by`, otherwise `ERR_SO_DUTY_VIOLATION`), and requires `verified_annual_income_cents` to be at least 0; rejection requires a non-empty `rejection_reason` and the same segregation check. The `decided_at` timestamp is set to now on either terminal decision, and `reviewed_by` records the acting officer.

An approval triggers a cascade of recomputation across the program. The household's `ami_pct` is replaced with the latest approved certification's `ami_pct_at_cert`. The household's `eligibility_status` is re-evaluated against two preconditions: there must be at least one `APPROVED` certification whose `decided_at` falls within the trailing 24 months, and for every `EducationCourse` in the program with `is_required` equal to true, the household must hold an `EducationCompletion` whose `expires_at` lies strictly in the future. If both hold, the household transitions from `PENDING` (or `EXPIRED`, if it had previously lapsed) to `ELIGIBLE`, and `eligibility_expires_at` is set to the latest approved cert's `decided_at` plus 24 months; if the household was already `ELIGIBLE`, it stays `ELIGIBLE` with the expiry extended. If the household's AMI fraction exceeds the program's `max_eligibility_ami_pct`, the household transitions to `INELIGIBLE` (whether it was `PENDING` or `ELIGIBLE`); boundary-inclusive, exactly `0.80` against a `0.80` ceiling remains `ELIGIBLE`. If the household currently holds an active lease, its lease's `monthly_fee_cents` is recomputed under the tiered formula described in §3.3, and every `PENDING` `LeaseFee` row for that lease whose `due_date` is in the future is re-amounted to the new fee. A rejection only transitions the household to `INELIGIBLE` when no other approved certification exists on file. An approved certification may later transition `APPROVED` → `EXPIRED` automatically when a newer approved cert supersedes it or when 24 months have elapsed.

Households also auto-expire their `ELIGIBLE` status: when the logical clock reaches `eligibility_expires_at` and no newer approved cert has extended it, `eligibility_status` moves `ELIGIBLE` → `EXPIRED`. Any `ACTIVE` `WaitlistEntry` rows for the household are moved to `EXPIRED` at the same time. If the household currently occupies a unit (`active_lease_id` is set), the lease remains `ACTIVE` — residents do not lose their home on a certification lapse — but they may not sell or refinance until they are re-certified. A fresh approval meeting the criteria above restores the household from `EXPIRED` back to `ELIGIBLE` and resets the expiry.

A `LeaseManager` may suspend a household (`ELIGIBLE` or `EXPIRED` → `SUSPENDED`), which withdraws any `ACTIVE` waitlist entries the household holds (each moving to `WITHDRAWN`). A suspended household may be reinstated (`SUSPENDED` → `PENDING`), at which point it must re-qualify through the normal approval path. Suspension of a program (see §3.1) blocks new household creation outright with `ERR_INVALID_STATE`.

Homebuyer education is tracked per program through the `EducationCourse` catalog. A `ProgramAdmin` creates a course by supplying its `code` (for example "HOME-101"), `title`, `credit_hours`, an optional `is_required` flag defaulting to true, and an optional `validity_months` defaulting to 24 — the number of months a completion remains valid before it must be re-taken. Courses start in `OFFERED` status and may be retired (`OFFERED` → `RETIRED`); retirement has a forward-only effect: households that have not yet completed the course have the requirement waived going forward, while households with existing completions continue to count them. An `IntakeSpecialist` records a household's course completion by supplying the `course_id`, the `completed_at` timestamp, and the `score_pct` the household achieved, expressed as a fraction between 0.0 and 1.0. A `score_pct` outside the closed interval from 0.0 to 1.0 is rejected with `ERR_INVALID_REQUEST`; a `score_pct` below 0.7 does not count toward satisfying the requirement. The completion's `expires_at` is computed as `completed_at` plus the course's `validity_months`. The `recorded_by` field captures the acting specialist's `X-User-ID`. When every required course in the program has an unexpired completion on file for the household, the household's `education_completed_at` is set to the maximum `completed_at` across the required courses.

### 3.3. Ground Leases, Fee Tiers, and the Monthly Billing Cycle

Units themselves are registered by a `ProgramAdmin`, who supplies the unit's `address`, its `bedrooms` count, the `original_subsidy_cents` (the public or philanthropic subsidy invested at acquisition, locked in at first sale and amortized for resale-formula purposes), and the `original_sale_price_cents` (the initial affordable sale price to the first CLT buyer). A newly created unit lands in `VACANT` `occupancy_status` with `maintenance_flag` set to `OK`, `last_inspection_passed_at` null, `next_inspection_due_at` computed from the program's `inspection_cycle_months`, `current_lease_id` null, and `appraisal_value_cents` initialized to 0.

A `LeaseManager` creates a new `GroundLease` against a `Unit` by supplying `household_id`, `start_date`, and `purchase_price_cents` — the price this household is paying for the improvements. The lease is created in `DRAFT` status with `end_date` computed as `start_date` plus the program's `ground_lease_term_years`. The lease's `unit_id` references the unit being leased. The lease carries `fee_arrears_cents` initialized to 0, `last_fee_charged_at` initially null (it is populated when the first `LeaseFee` row is charged), and `resale_count` initialized to 0; `subsidy_locked_cents` is not populated until activation.

Activating a draft lease is a `LeaseManager` operation guarded by optimistic concurrency on the unit: the request must carry `expected_unit_version` equal to the unit's current `version`, otherwise the activation is rejected with `ERR_STALE_VERSION`. Four preconditions must all hold: the household's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_HOUSEHOLD_INELIGIBLE`); the household's `education_completed_at` must be non-null and every required `EducationCourse` must have an unexpired `EducationCompletion` (otherwise `ERR_EDUCATION_INCOMPLETE`); the unit's `occupancy_status` must be `VACANT` or, in the case of a resale successor lease being activated after a prior `ResaleListing` has closed, `UNDER_CONTRACT` (otherwise `ERR_UNIT_BLOCKED`); and the household must not already hold another `ACTIVE` `GroundLease` in this program (otherwise `ERR_MULTI_LEASE_PROHIBITED`). The unit itself must not already have another active lease — the symmetric check, which returns `ERR_UNIT_OCCUPIED`. Finally, the latest approved certification's `decided_at` must be within the trailing 24 months (otherwise `ERR_CERT_STALE`).

A successful activation performs a bundle of side effects atomically: the lease's `status` becomes `ACTIVE`; the unit's `occupancy_status` becomes `OCCUPIED` and its `current_lease_id` is set to the new lease; the household's `active_lease_id` is set; the lease's `subsidy_locked_cents` is populated with the unit's `original_subsidy_cents` (for an initial sale) or with the retained subsidy computed at resale close (for a resale successor); the lease's `monthly_fee_cents` is computed via the tiered formula below; the first `LeaseFee` row is auto-created for the current month in `PENDING` status; and the unit's `version` is incremented by 1.

The tiered monthly fee formula uses the program's `ground_lease_base_fee_cents` as the base. If the household's `ami_pct` is at most 0.50 (boundary inclusive — an `ami_pct` of exactly 0.50 lands in this tier), the monthly fee is the base multiplied by one minus `low_income_fee_reduction_pct`, rounded half-up to integer cents. If `ami_pct` is greater than 0.50 and at most 0.80 (boundary inclusive — an `ami_pct` of exactly 0.80 lands in this middle tier), the fee is the base multiplied by one minus the product of `low_income_fee_reduction_pct` and the ratio formed by dividing the difference between 0.80 and `ami_pct` by 0.30, again rounded half-up to integer cents. If `ami_pct` is strictly greater than 0.80, the household pays the full base fee. The effect is a linear subsidy taper between 50% and 80% AMI, with full subsidy below 50% and no subsidy above 80%.

Each month the program charges the active lease by creating a `LeaseFee` row recording `period_year` and `period_month` (with `period_month` ranging from 1 to 12). The row's `amount_cents` is the lease's current `monthly_fee_cents`, and its `due_date` is the first day of the period month at 00:00:00 UTC. The row starts in `PENDING` status with `paid_amount_cents` equal to 0. A `Household` may pay a fee by submitting `payment_amount_cents`; if the sum of the existing `paid_amount_cents` and the new `payment_amount_cents` is at least `amount_cents`, the fee transitions to `PAID` with `paid_at` set to now, and the lease's `fee_arrears_cents` is decremented by `amount_cents` (capped so it cannot go below 0). If the sum is less than `amount_cents`, the request is rejected with `ERR_UNDERPAYMENT` and the fee's status is unchanged. A `LeaseManager` may waive a fee in `PENDING` or `LATE` status, moving it to `WAIVED` and decrementing `fee_arrears_cents` by the unpaid balance (the difference between `amount_cents` and `paid_amount_cents`, again capped at 0).

The system automatically transitions a `PENDING` fee to `LATE` at `due_date` plus 5 days of grace. That transition increments the lease's `fee_arrears_cents` by the fee's `amount_cents`, and if the resulting arrears reach or exceed three times the current `monthly_fee_cents`, the system auto-issues a `DefaultNotice` of kind `FEE_ARREARS` against the lease — starting the default pipeline described in §3.4. A `LATE` fee transitions to `DEFAULTED` automatically when its associated lease is foreclosed.

Terminating a lease in good standing is a `LeaseManager` operation. It is permitted only when no `OPEN` `DefaultNotice` rows exist on the lease, and it requires `expected_lease_version` matching the lease's current `version` (otherwise `ERR_STALE_VERSION`). Termination increments both the lease's `version` and the unit's `version` by 1, sets the lease's status to `TERMINATED`, sets the unit's `occupancy_status` to `VACANT` and clears its `current_lease_id`, and clears the household's `active_lease_id`. A lease may also reach `TERMINATED` automatically when a resale closes (see §3.5), in which case the lease's `resale_count` is incremented by 1 — counting the number of times this leasehold has been resold — and `Household.active_lease_id` is cleared.

A lease that reaches its computed `end_date` without renewal transitions automatically from `ACTIVE` to `EXPIRED`, setting the unit's `occupancy_status` to `VACANT` and clearing the household's `active_lease_id`. This transition is evaluated as part of the scheduled system pass driven by the logical clock.

### 3.4. Default, Cure, and Foreclosure

A `LeaseManager` issues a `DefaultNotice` against a lease by supplying `notice_kind` (one of `FEE_ARREARS`, `MAINTENANCE`, `UNAUTHORIZED_REFINANCE`, `OCCUPANCY_VIOLATION`) and `amount_due_cents` (the cents required to cure; 0 for non-monetary notices), with an optional `cure_evidence` string. The notice is created in `OPEN` status, `issued_at` is set to now, `issued_by` records the acting manager's `X-User-ID`, and `cure_deadline_at` is computed as `issued_at` plus the program's `default_cure_window_days` days. Issuing a notice transitions the lease to `IN_DEFAULT` and the unit's `occupancy_status` to `IN_DEFAULT`.

A lease in `IN_DEFAULT` moves to `CURE_PERIOD` automatically when its `DefaultNotice`'s `cure_deadline_at` falls within 7 days, the notice's `amount_due_cents` is greater than 0, and a partial payment has been received toward the arrears. From `CURE_PERIOD`, the lease returns to `ACTIVE` automatically when every `OPEN` notice on the lease has transitioned to `CURED`; that transition also restores the unit to `OCCUPIED` and clears `fee_arrears_cents` to 0. A lease may also recover directly from `IN_DEFAULT` to `ACTIVE` if every notice on it reaches `CURED` or `DISMISSED` before any deadline passes.

Curing a notice is a `LeaseManager` operation that requires a non-empty `cure_evidence` string. The preconditions depend on `notice_kind`. For a `FEE_ARREARS` notice, the lease's `fee_arrears_cents` must equal 0 after any concurrent payment has been applied; if arrears remain, the cure is rejected with `ERR_ARREARS_NOT_CLEARED`. For a `MAINTENANCE` notice, a follow-up `InspectionRecord` with `result` equal to `PASSED` must exist whose `completed_at` is strictly after the notice's `issued_at`; if no such inspection exists (or `cure_evidence` is missing), the cure is rejected with `ERR_CURE_EVIDENCE_MISSING`. On a successful cure the notice transitions `OPEN` → `CURED` with `cured_at` set to now; if this was the last open notice on the lease, the lease returns to `ACTIVE` and the unit returns to `OCCUPIED`. A cure attempted on a notice whose `cure_deadline_at` has already passed (that is, the current time is strictly greater than the deadline) is rejected with `ERR_CURE_WINDOW_EXPIRED`.

A notice that is still `OPEN` when the clock passes `cure_deadline_at` transitions automatically to `ESCALATED` as part of the scheduled system pass; a `LeaseManager` may also escalate a notice early via a dedicated operation, subject to the same deadline precondition on the auto path. Escalation marks the lease eligible for foreclosure — it does not itself foreclose. The scheduled pass processes notices in chronological order of `issued_at`, breaking ties by `created_at` ascending. A `LeaseManager` may dismiss an `OPEN` notice, transitioning it to `DISMISSED`; if dismissal closes the last open notice on the lease, the lease and unit statuses are recomputed accordingly.

Foreclosing a lease is a `LeaseManager` operation permitted when at least one `DefaultNotice` on the lease is `OPEN` and its `cure_deadline_at` has already passed; the operation requires `expected_lease_version` matching the lease's current `version` (otherwise `ERR_STALE_VERSION`). On foreclosure, both the lease's `version` and the unit's `version` increment by 1; the lease's `status` becomes `FORECLOSED`; the unit's `occupancy_status` becomes `FORECLOSED` and its `current_lease_id` is cleared; the household's `active_lease_id` is cleared and its `eligibility_status` is set to `SUSPENDED`; every `OPEN` notice on the lease transitions to `ESCALATED`; and every `PENDING` `LeaseFee` row transitions to `DEFAULTED`.

### 3.5. Resale Listing, Pricing Formula, and Subsidy Retention

A seller — either the occupying `Household` itself or a `LeaseManager` acting on its behalf — opens a `ResaleListing` against the unit by supplying the `seller_lease_id` of the current lease and `appraisal_at_listing_cents`, an independent market appraisal of the leasehold interest at the time of listing. The listing is created in `OPEN` status with `listed_at` set to now. Opening the listing transitions the unit's `occupancy_status` from `OCCUPIED` to `LISTED_FOR_RESALE`. The create is rejected with `ERR_UNIT_BLOCKED` if the unit's `maintenance_flag` is `UNSAFE`, if the unit is not in `OCCUPIED` status, or if any `OPEN` `DefaultNotice` exists on the seller's lease.

The listing's asking price is computed from the program's resale formula. The choice of formula is `resale_formula_kind`, set on the program. Both variants share the same inputs: `purchase_price_cents` from the seller's lease (the price the seller paid, denoted P0), `original_subsidy_cents` from the unit (the initial subsidy, S0), the unit's `appraisal_value_cents` captured at the time of the seller's purchase (A0), the listing's `appraisal_at_listing_cents` (A1), and the integer number of full calendar years between the seller lease's `start_date` and the listing's `listed_at` (Y — computed as the floor of elapsed days divided by 365.25).

Under the `APPRAISAL_BASED` variant, the appreciation is the greater of 0 and the difference A1 minus A0. The seller's share of the appreciation is the appreciation multiplied by the program's `appraisal_seller_share_pct`, rounded half-up to integer cents. The listing's `asking_price_cents` is then the seller's original purchase price P0 plus the seller share. The listing's `subsidy_retained_cents` is the original subsidy S0 plus the portion of appreciation not paid to the seller (that is, the appreciation minus the seller share). The listing's `seller_proceeds_cents` is the asking price minus P0 — which by construction equals the seller share.

Under the `INDEXED` variant, an indexed value is computed first as P0 multiplied by one plus the product of the program's `indexed_annual_appreciation_pct` and the year count Y, rounded half-up to integer cents. The listing's `asking_price_cents` is then the smaller of this indexed value and A1 — the asking price is capped by the current market appraisal. The listing's `subsidy_retained_cents` is S0 plus the greater of 0 and the difference A1 minus the asking price. The listing's `seller_proceeds_cents` is the asking price minus P0, capped by the formula. The evaluation order is pinned: the indexed value is computed before the minimum is applied, and under the appraisal-based variant the seller share is computed before the asking price.

Across both variants a conservation invariant holds: the seller's gain plus the program's retained gain equals the total appreciation. Under `APPRAISAL_BASED` the seller's gain is the seller share and the program's retained gain is the appreciation minus the seller share; under `INDEXED` the seller's gain is the asking price minus P0 and the retained gain is the greater of 0 and A1 minus the asking price. The invariant can also be phrased as: subsidy retained plus seller proceeds, plus P0, equals A1 when appreciation is positive (for the appraisal variant); for the indexed variant, subsidy retained plus seller proceeds equals S0 plus A1 minus P0 whenever A1 exceeds the asking price. Any future change to the resale formula must preserve this invariant for fixed inputs (P0, A0, A1, S0, Y).

The listing also carries a computed `affordability_preserved` flag. The affordability ceiling is defined as the monthly housing budget a household at the maximum eligibility AMI could sustain, multiplied by twelve months per year and by thirty years. Concretely: take the program's `area_median_income_cents` and multiply by `max_eligibility_ami_pct` to get the annual income of a household at the eligibility ceiling; multiply by 0.30 to get the annual housing budget; divide by 12 and round half-up to integer cents to get the monthly housing budget; multiply by 12 and by 30 to get the thirty-year price ceiling. `affordability_preserved` is true exactly when the listing's `asking_price_cents` is at most this ceiling — boundary inclusive, an asking price exactly equal to the ceiling passes.

With the listing `OPEN`, a `LeaseManager` may run the waitlist matching algorithm. The matching run requires `expected_listing_version` matching the listing's current `version` (otherwise `ERR_STALE_VERSION`); it also requires the unit's `maintenance_flag` to differ from `UNSAFE` (otherwise `ERR_UNIT_BLOCKED`), the listing's status to be `OPEN`, and the unit's `occupancy_status` to be `LISTED_FOR_RESALE`. The candidate pool is every `WaitlistEntry` whose status is `ACTIVE`, whose household is `ELIGIBLE` (and whose household's `education_completed_at` is non-null), whose `max_price_cents` is at least the listing's `asking_price_cents`, and whose `desired_bedrooms` is at most the unit's `bedrooms`. Each candidate is ranked by an effective score: the entry's stored `priority_score`, plus a bonus of 50 if the absolute difference between the unit's `bedrooms` and the household's `household_size` is at most 1. The candidate with the highest effective score wins; ties are broken by the entry's `created_at` ascending (earliest first). The entry's `id` is never consulted as a tie-break. If the filtered pool is empty, the run is rejected with `ERR_NO_ELIGIBLE_BUYER` and the listing remains `OPEN`.

A successful match moves the chosen entry to `MATCHED` with `matched_at` set to now, `matched_unit_id` set to the listing's unit, and `match_rank_at_match` set to the entry's rank among active entries at match time (1 = highest priority). The listing moves to `MATCHED` with `matched_waitlist_entry_id` and `buyer_household_id` populated, and the listing's `version` increments by 1. The unit's `occupancy_status` is unchanged — it remains `LISTED_FOR_RESALE`.

From `MATCHED`, a `LeaseManager` may open the purchase contract, moving the listing to `UNDER_CONTRACT`. The buyer household must still be `ELIGIBLE` and must still hold unexpired required education completions; the operation requires `expected_listing_version`. The listing's `version` increments by 1 and the unit's `occupancy_status` transitions to `UNDER_CONTRACT`. From `UNDER_CONTRACT`, the sale closes by a `LeaseManager` operation carrying `expected_listing_version` and a boolean `confirmed_funds`. If `confirmed_funds` is not true, the close is rejected with `ERR_FUNDS_NOT_CONFIRMED`. On a successful close, the listing's `version` increments by 1 and its status becomes `CLOSED`; the seller's `GroundLease` transitions to `TERMINATED` (with `resale_count` incremented and the seller household's `active_lease_id` cleared); seller proceeds are paid out per the resale formula; the retained subsidy per the subsidy-retention calculation is rolled into the buyer's new lease as its `subsidy_locked_cents`; a new buyer `GroundLease` is auto-created in `DRAFT` status (a separate activation step is required before the buyer occupies); the buyer's waitlist entry transitions to `FULFILLED`; and the unit's `occupancy_status` transitions to `VACANT`, where it will sit until the buyer's lease activation moves it to `OCCUPIED`.

A listing in `OPEN` or `MATCHED` may be cancelled by a `LeaseManager`. Cancellation sets the listing's status to `CANCELLED`; if the listing was `MATCHED`, the previously matched waitlist entry is returned to `ACTIVE` with `matched_unit_id`, `matched_at`, and `match_rank_at_match` all cleared. The unit's `occupancy_status` returns to `OCCUPIED` — the seller remains in place. A matched waitlist entry may also be withdrawn by the household or a `LeaseManager`, which returns the listing to `OPEN` (re-listed) and clears the listing's `matched_waitlist_entry_id` and `buyer_household_id`.

### 3.6. Waitlist Creation, Priority Scoring, and Maintenance

An `IntakeSpecialist` or the `Household` itself may create a `WaitlistEntry` for a household by supplying `desired_bedrooms` (the minimum number of bedrooms requested) and `max_price_cents` (the maximum price the household can afford at current AMI). The household's `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_HOUSEHOLD_INELIGIBLE`), the household's `education_completed_at` must be non-null (otherwise `ERR_EDUCATION_INCOMPLETE`), and the latest approved certification's `decided_at` must be within the trailing 24 months (otherwise `ERR_CERT_STALE`). The entry is created in `ACTIVE` status, the household's `waitlist_entry_id` is set to the new entry, and the entry's `priority_score` is computed.

The stored `priority_score` is the sum of two integer components. The need score is one minus the household's `ami_pct`, multiplied by 1000, and rounded to the nearest integer — lower AMI yields a higher need score. The age score is the integer number of days since the entry's `created_at`, capped at 365 days (one year). The stored score does not include the bedroom-size-match bonus; that bonus of 50 points is added only at match evaluation time when the absolute difference between the unit's bedrooms and the household's size is at most 1. Scores are refreshed daily and whenever the household's `ami_pct` changes (for example, on a new approved certification).

An `ACTIVE` entry may be withdrawn by its household or by a `LeaseManager`, moving it to `WITHDRAWN`. As described in §3.5, withdrawing a `MATCHED` entry returns the associated listing to `OPEN`. Entries auto-expire — `ACTIVE` → `EXPIRED` — when the household's `eligibility_status` has been out of `ELIGIBLE` for more than 30 days, or when the program closes. A matched entry's terminal state is `FULFILLED`, reached automatically when the successor ground lease for the matched unit transitions to `ACTIVE`.

### 3.7. Inspections, Maintenance Standards, and Auto-Scheduling

An `Inspector` or a `LeaseManager` schedules an `InspectionRecord` against a unit by supplying `scheduled_for`. The record is created with `result` equal to `PENDING`, `inspector_user_id` set to the acting `X-User-ID`, `findings` defaulting to an empty string, and `follow_up_due_at` and `linked_notice_id` initially null.

The unit's `next_inspection_due_at` is computed as the timestamp of the most recent `PASSED` inspection's `completed_at` (or, if no inspection has ever passed, the lease's `start_date`) plus the program's `inspection_cycle_months`. If the logical clock has advanced past `next_inspection_due_at` and no `PENDING` inspection exists for the unit, the scheduled system pass auto-creates a `PENDING` `InspectionRecord` with `scheduled_for` set to now. If a `PENDING` inspection already exists whose `scheduled_for` falls within 7 days of the newly computed due date, the existing record is reused and no duplicate is created.

An `Inspector` records the outcome of a pending inspection by supplying `result` (one of `PASSED`, `FAILED`, `NEEDS_REPAIR`) and an optional `findings` string. The acting `X-User-ID` must be an `Inspector`. All three outcomes share `completed_at` set to now. On `PASSED`, the unit's `last_inspection_passed_at` is set to now, the unit's `next_inspection_due_at` is recomputed as now plus `inspection_cycle_months`, and the unit's `maintenance_flag` is set to `OK`. On `NEEDS_REPAIR`, the unit's `maintenance_flag` is set to `NEEDS_REPAIR` and the record's `follow_up_due_at` is set to now plus 30 days. On `FAILED`, the unit's `maintenance_flag` is set to `UNSAFE`, and the system auto-issues a `DefaultNotice` with `notice_kind` equal to `MAINTENANCE` and `amount_due_cents` equal to 0 against the unit's `current_lease_id` — which cascades the lease to `IN_DEFAULT` and the unit to `IN_DEFAULT` per the default pipeline — and the record's `linked_notice_id` is set to the new notice's id.

The unit's `maintenance_flag` therefore always reflects the latest recorded inspection outcome: `OK` after a `PASSED`, `NEEDS_REPAIR` after a `NEEDS_REPAIR`, and `UNSAFE` after a `FAILED`. A unit whose flag is `UNSAFE` is blocked from resale listing creation, matching, and contract opening (all rejected with `ERR_UNIT_BLOCKED`) until a subsequent `PASSED` inspection restores it to `OK`.

### 3.8. Refinance Requests and Lender Review

A `Household` submits a `RefinanceRequest` against its active lease by supplying `lender_name`, `requested_loan_cents` (the new loan principal), `requested_cash_out_cents` (cash-out equity requested, defaulting to 0), and `appraised_value_cents` (the lender's appraised value of the leasehold interest). An `appraised_value_cents` of exactly 0 is rejected at input validation with `ERR_INVALID_REQUEST`. The request is created in `SUBMITTED` status with `submitted_by` set to the acting `X-User-ID`, and two fields are computed immediately: `computed_ltv`, the ratio of `requested_loan_cents` to `appraised_value_cents` rounded half-up to 4 decimal places; and `program_max_loan_cents`, the floor of `appraised_value_cents` multiplied by the program's `max_refi_ltv_pct`.

The household then moves the request `SUBMITTED` → `LENDER_REVIEW` via a submit-to-lender action; only the household that owns the lease may do this. From `LENDER_REVIEW`, a `LeaseManager` may approve or reject. Approval requires the segregation-of-duties check (`reviewed_by` must differ from `submitted_by`, otherwise `ERR_SO_DUTY_VIOLATION`); requires `computed_ltv` to be at most `max_refi_ltv_pct` (boundary inclusive) and `requested_cash_out_cents` to be at most `max_equity_withdrawal_cents` (boundary inclusive) — violations of either are rejected with `ERR_REFINANCE_LIMIT_EXCEEDED`; requires the lease to be in `ACTIVE` status; and requires that no `OPEN` `DefaultNotice` exist on the lease. Approval sets `reviewed_by` to the acting manager and refreshes the unit's `appraisal_value_cents` to the request's `appraised_value_cents`. Rejection requires the same segregation check and a non-empty `rejection_reason`, and transitions the request to `REJECTED`. A request in `SUBMITTED` or `LENDER_REVIEW` may be withdrawn by the household, moving it to `WITHDRAWN`.

An approved request is finalized by a `LeaseManager` recording it. The recording operation requires `expected_lease_version` matching the lease's current `version` (otherwise `ERR_STALE_VERSION`); it increments the lease's `version` by 1 and moves the request to `RECORDED`, marking it as final with the lease's terms updated to reflect the new lender.

### 3.9. Household Eligibility Re-Certification and Lapses

Eligibility is not permanent. The 24-month validity window attached to every approved certification creates a recurring re-certification obligation: a household whose latest approved cert ages past 24 months without a replacement will transition `ELIGIBLE` → `EXPIRED` automatically on the next clock tick. As described in §3.2, this does not displace a resident — an occupied unit's lease remains `ACTIVE` — but it freezes the household's ability to sell (opening a resale listing is gated on `ELIGIBLE`), refinance (refinance submission is gated on `ELIGIBLE`), or match against a listing (matching requires `ELIGIBLE` at the moment of the run). A household that wishes to restore full standing submits a new `IncomeCertification`, which flows through the normal `SUBMITTED` → `UNDER_REVIEW` → `APPROVED` pipeline; on approval the household returns to `ELIGIBLE` and `eligibility_expires_at` is reset to the new cert's `decided_at` plus 24 months.

A `LeaseManager` may also administratively suspend a household, which has the side effect of withdrawing all of its `ACTIVE` waitlist entries — each transitions to `WITHDRAWN` and any matched listing is returned to `OPEN` per the cancel/withdraw flow in §3.5. Reinstatement returns the household to `PENDING`, from which it must re-qualify through income certification and education checks in the usual way.

## 4. Endpoint Definitions

Status codes follow two uniform rules: endpoints that create a new resource return 201 Created; endpoints that modify an existing resource or perform a state transition return 200 OK. All list endpoints return 200 OK with pagination metadata as described in §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied `to` instant | PlatformAdmin, ProgramAdmin |
| POST | `/programs` | Create a new CLT program | PlatformAdmin |
| GET | `/programs` | List programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| GET | `/programs/{id}` | Get a program | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| PUT | `/programs/{id}` | Update program parameters (triggers fee/subsidy recalculation) | ProgramAdmin |
| POST | `/programs/{id}/suspend` | Suspend program | ProgramAdmin |
| POST | `/programs/{id}/reinstate` | Reinstate program | ProgramAdmin |
| POST | `/programs/{id}/close` | Close program | ProgramAdmin |
| POST | `/programs/{id}/households` | Create household (buyer applicant) | IntakeSpecialist |
| GET | `/programs/{id}/households` | List households | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist |
| GET | `/programs/{id}/households/{householdId}` | Get household | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| POST | `/programs/{id}/households/{householdId}/suspend` | Suspend household | LeaseManager |
| POST | `/programs/{id}/households/{householdId}/reinstate` | Reinstate suspended household | LeaseManager |
| POST | `/programs/{id}/households/{householdId}/income-certifications` | Submit an income certification | IntakeSpecialist, Household |
| GET | `/programs/{id}/households/{householdId}/income-certifications` | List income certifications for a household | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| GET | `/programs/{id}/households/{householdId}/income-certifications/{certId}` | Get an income certification | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| POST | `/programs/{id}/households/{householdId}/income-certifications/{certId}/start-review` | Move cert to `UNDER_REVIEW` | ComplianceOfficer |
| POST | `/programs/{id}/households/{householdId}/income-certifications/{certId}/approve` | Approve cert (requires segregation of duties) | ComplianceOfficer |
| POST | `/programs/{id}/households/{householdId}/income-certifications/{certId}/reject` | Reject cert | ComplianceOfficer |
| POST | `/programs/{id}/education-courses` | Create education course | ProgramAdmin |
| GET | `/programs/{id}/education-courses` | List courses | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| GET | `/programs/{id}/education-courses/{courseId}` | Get course | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| POST | `/programs/{id}/education-courses/{courseId}/retire` | Retire course | ProgramAdmin |
| POST | `/programs/{id}/households/{householdId}/education-completions` | Record a course completion for a household | IntakeSpecialist |
| GET | `/programs/{id}/households/{householdId}/education-completions` | List education completions for a household | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| POST | `/programs/{id}/units` | Create a unit | ProgramAdmin |
| GET | `/programs/{id}/units` | List units | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| GET | `/programs/{id}/units/{unitId}` | Get unit | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| POST | `/programs/{id}/units/{unitId}/leases` | Create a draft ground lease | LeaseManager |
| GET | `/programs/{id}/units/{unitId}/leases` | List leases for unit | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}` | Get lease | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/activate` | Activate a draft lease | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/terminate` | Terminate an active lease (no default) | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/foreclose` | Foreclose a defaulted lease | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/fees/{feeId}/pay` | Record a payment on a lease fee | Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/fees/{feeId}/waive` | Waive a lease fee | LeaseManager |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}/fees` | List fees for a lease | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}/fees/{feeId}` | Get fee | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/default-notices` | Issue a default notice | LeaseManager |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}/default-notices` | List default notices | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}/default-notices/{noticeId}` | Get default notice | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/default-notices/{noticeId}/cure` | Cure a default notice | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/default-notices/{noticeId}/escalate` | Escalate a default notice | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/default-notices/{noticeId}/dismiss` | Dismiss a default notice | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/inspections` | Schedule an inspection | Inspector, LeaseManager |
| GET | `/programs/{id}/units/{unitId}/inspections` | List inspections for a unit | PlatformAdmin, ProgramAdmin, LeaseManager, Inspector, Household |
| GET | `/programs/{id}/units/{unitId}/inspections/{inspectionId}` | Get inspection | PlatformAdmin, ProgramAdmin, LeaseManager, Inspector, Household |
| POST | `/programs/{id}/units/{unitId}/inspections/{inspectionId}/record-result` | Record inspection result | Inspector |
| POST | `/programs/{id}/households/{householdId}/waitlist-entries` | Create a waitlist entry | IntakeSpecialist, Household |
| GET | `/programs/{id}/waitlist-entries` | List waitlist entries in a program | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist |
| GET | `/programs/{id}/households/{householdId}/waitlist-entries` | List waitlist entries for household | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| GET | `/programs/{id}/waitlist-entries/{entryId}` | Get waitlist entry | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| POST | `/programs/{id}/waitlist-entries/{entryId}/withdraw` | Withdraw waitlist entry | Household, LeaseManager |
| POST | `/programs/{id}/units/{unitId}/resale-listings` | Open a resale listing | LeaseManager, Household |
| GET | `/programs/{id}/units/{unitId}/resale-listings` | List resale listings for unit | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/programs/{id}/units/{unitId}/resale-listings/{listingId}` | Get resale listing | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| POST | `/programs/{id}/units/{unitId}/resale-listings/{listingId}/run-matching` | Run waitlist matching against this listing | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/resale-listings/{listingId}/open-contract` | Open purchase contract with matched buyer | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/resale-listings/{listingId}/close` | Close the sale | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/resale-listings/{listingId}/cancel` | Cancel a listing | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests` | Submit a refinance request | Household |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests` | List refinance requests for a lease | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests/{refiId}` | Get refinance request | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests/{refiId}/submit-to-lender` | Submit to lender review | Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests/{refiId}/approve` | Approve refinance | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests/{refiId}/reject` | Reject refinance | LeaseManager |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests/{refiId}/withdraw` | Withdraw refinance | Household |
| POST | `/programs/{id}/units/{unitId}/leases/{leaseId}/refinance-requests/{refiId}/record` | Record an approved refinance | LeaseManager |
| GET | `/households/{id}` | Get household by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| GET | `/units/{id}` | Get unit by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| GET | `/leases/{id}` | Get ground lease by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/income-certifications/{id}` | Get income certification by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| GET | `/education-courses/{id}` | Get education course by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector, Household |
| GET | `/education-completions/{id}` | Get education completion by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| GET | `/fees/{id}` | Get lease fee by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/default-notices/{id}` | Get default notice by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/inspections/{id}` | Get inspection record by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, LeaseManager, Inspector, Household |
| GET | `/resale-listings/{id}` | Get resale listing by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/refinance-requests/{id}` | Get refinance request by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, Household |
| GET | `/households` | List households across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist |
| GET | `/income-certifications` | List income certifications across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist |
| GET | `/education-completions` | List education completions across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist |
| GET | `/units` | List units across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector |
| GET | `/leases` | List ground leases across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager |
| GET | `/fees` | List lease fees across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager |
| GET | `/default-notices` | List default notices across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager |
| GET | `/inspections` | List inspection records across all programs | PlatformAdmin, ProgramAdmin, LeaseManager, Inspector |
| GET | `/resale-listings` | List resale listings across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager |
| GET | `/refinance-requests` | List refinance requests across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager |
| GET | `/education-courses` | List education courses across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Inspector |
| GET | `/waitlist-entries/{id}` | Get waitlist entry by id (canonical top-level alias) | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist, Household |
| GET | `/waitlist-entries` | List waitlist entries across all programs | PlatformAdmin, ProgramAdmin, ComplianceOfficer, LeaseManager, IntakeSpecialist |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_SO_DUTY_VIOLATION` | 409 |
| `ERR_CURE_EVIDENCE_MISSING` | 422 |
| `ERR_ARREARS_NOT_CLEARED` | 402 |
| `ERR_UNDERPAYMENT` | 402 |
| `ERR_FUNDS_NOT_CONFIRMED` | 402 |
| `ERR_HOUSEHOLD_INELIGIBLE` | 409 |
| `ERR_EDUCATION_INCOMPLETE` | 409 |
| `ERR_CERT_STALE` | 409 |
| `ERR_UNIT_BLOCKED` | 409 |
| `ERR_UNIT_OCCUPIED` | 409 |
| `ERR_MULTI_LEASE_PROHIBITED` | 409 |
| `ERR_NO_ELIGIBLE_BUYER` | 422 |
| `ERR_REFINANCE_LIMIT_EXCEEDED` | 422 |
| `ERR_CURE_WINDOW_EXPIRED` | 409 |
| `ERR_STALE_VERSION` | 412 |
