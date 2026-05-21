# Fmla Pfl Leave Management API — Product Requirements Document

## 1. Introduction

The federal Family and Medical Leave Act (FMLA) and the patchwork of state Paid Family Leave (PFL) programs together impose a deceptively intricate set of obligations on employers. A human-resources team must determine, on demand, whether a given worker has crossed three independent eligibility thresholds; pin the worker's leave-year window to whichever accounting basis the employer chose at enrollment; track every absence — including the highly fragmented "intermittent" absences typical of chronic-condition cases — against a finite hours bucket; chase down medical certifications within a regulator-bound deadline; coordinate a state-level wage-replacement benefit that runs *concurrently* (not additively) with the federal entitlement; invoice the employee monthly for the slice of the group-health premium the employer would normally withhold from a paycheck; and at the end of the cycle decide whether the employee is still legally entitled to be restored to the same job.

This system is the system of record for that lifecycle. Its job is to make every one of those determinations deterministic and auditable: every eligibility check, every quota debit, every cascade triggered by a missed deadline must be traceable to a specific input event and a specific server-clock reading. Because much of the workflow is gated on real-world time (a certification deadline 15 days after submission; a benefit invoice that crosses into grace at 30 days and is forfeited at 45; a leave that automatically becomes active when the requested start date arrives), the system also exposes an administrative time-advancement capability so the regulator-facing audit log can be exercised in tests and tabletop drills without waiting weeks of wall-clock time.

The reader of this document is the engineer who must implement the REST surface, the state machines, the eligibility and quota calculations, the cascading side effects, and the audit trail described below. The reader of every emitted response — and the test harness — is an HR operator, an employee tracking their own case, or a compliance auditor sweeping the audit log; every contract below is written with all three audiences in mind.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (except the public liveness probe) must carry two headers: `X-User-ID` identifying the caller, and `X-User-Role` declaring the caller's role. If either header is missing or empty the request is rejected with `ERR_MISSING_AUTH_HEADERS`. If the `X-User-Role` value is not one of the three recognized roles below, the request is rejected with `ERR_UNKNOWN_ROLE`.

The three roles are spelled exactly as `Employee`, `HRSpecialist`, and `ComplianceOfficer`.

When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` (directly via `employee_id` or transitively via a `LeaveCase`, `PfLClaim`, `LeaveInstance`, `MedicalCertification`, or `BenefitInvoice`) compare the resource's owning `employee_id` to `X-User-ID`. A mismatch surfaces as `ERR_NOT_OWNER`. When `X-User-Role` is `HRSpecialist`, `X-User-ID` is the `id` of the acting `HRSpecialist`; HR specialists may act on resources owned by any employee within the system but their identity must still resolve to a known specialist row. For both entity-backed roles, an `X-User-ID` that does not resolve to a row in the backing entity yields `ERR_UNKNOWN_IDENTITY`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_role` on `AuditEvent`) but does not compare it to any entity's `id`, and the `ERR_UNKNOWN_IDENTITY` check is skipped for compliance-officer requests.

If the caller's role is recognized and identifiable but is not authorized to invoke the endpoint per the role matrix expressed in §4, the request is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters: `limit`, which defaults to 10, and which must lie between 1 and 100 inclusive; and `offset`, which defaults to 0 and must be zero or greater. Out-of-range values surface as `ERR_VALIDATION`. List endpoints sort by `created_at` ascending and return four pagination fields inside `meta`: `limit`, `offset`, `total_count` (the total number of rows matching the query, before the page slice is applied), and `has_more` (a boolean indicating whether at least one further row exists past the current page).

### 2.4. Common Resource Properties and Optimistic Concurrency

Resources of the types `Employer`, `Worksite`, `Employee`, `LeaveCase`, and `PfLClaim` carry the common envelope fields: a server-minted `id` (a UUID string with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp updated on every successful mutation (same format as `created_at`, and equal to `created_at` immediately after creation), and an integer `version` that starts at 1 and increments by 1 on every successful mutation.

Resources of the types `LeaveInstance`, `MedicalCertification`, `BenefitInvoice`, and `AuditEvent` are append-only or are mutated only through their parent's lifecycle; they carry only an `id` (UUID, no type prefix) and a `created_at` timestamp. They do not expose `updated_at` and they do not expose `version`.

Mutating endpoints accept an optional `version` field in the request body. If omitted, the concurrency check is skipped and the mutation proceeds against whatever the current row version is. If supplied, the server compares it to the resource's current `version`; a mismatch terminates the mutation with `ERR_VERSION_CONFLICT`. This is the mechanism by which two `HRSpecialist` users acting on the same `LeaveCase` concurrently are serialized: the loser sees `ERR_VERSION_CONFLICT`.

### 2.5. Path Resolution and Existence Checks

Endpoints with multiple path segments — for example, an instance nested under a case nested under an employee — validate path identifiers left-to-right. The leftmost identifier (`employer_id`, `employee_id`, `leave_case_id`, `pfl_claim_id`, `cert_id`, `invoice_id`, or `instance_id` as it appears in the URL) is resolved first; if it does not exist the request returns `ERR_NOT_FOUND` without examining further segments. Each subsequent segment is then resolved against the previous, and any unresolved identifier likewise returns `ERR_NOT_FOUND`.

### 2.6. Validation Ordering

Multiple validation rules apply to the same endpoint; when several would all be triggered, they are evaluated in a fixed priority order so that the most fundamental cause is reported. The order is, from highest to lowest priority: authentication header presence (`ERR_MISSING_AUTH_HEADERS`); recognized role (`ERR_UNKNOWN_ROLE`); identity resolution against the backing entity for entity-backed roles (`ERR_UNKNOWN_IDENTITY`); endpoint authorization (`ERR_FORBIDDEN`); path existence (`ERR_NOT_FOUND`); ownership for employee-scoped endpoints (`ERR_NOT_OWNER`); state machine preconditions on the target `LeaveCase` (`ERR_INVALID_STATE`); optimistic concurrency on `version` (`ERR_VERSION_CONFLICT`); employee-not-terminated guard on case mutations (`ERR_EMPLOYEE_TERMINATED`); the three FMLA eligibility checks at case submission, evaluated in tenure-then-hours-then-worksite order (`ERR_NOT_ELIGIBLE_TENURE`, then `ERR_NOT_ELIGIBLE_HOURS`, then `ERR_NOT_ELIGIBLE_WORKSITE`); certification-deadline expiry on approval (`ERR_CERT_DEADLINE_MISSED`); certification completeness on approval (`ERR_CERT_INCOMPLETE`); quota sufficiency (`ERR_QUOTA_EXCEEDED`); instance pattern legality (`ERR_INSTANCE_NOT_ALLOWED`); cross-case instance overlap (`ERR_INSTANCE_OVERLAP`); PFL availability (`ERR_PFL_NOT_AVAILABLE`); PFL linkage consistency (`ERR_PFL_MISMATCH`); job-restoration protection (`ERR_JOB_RESTORATION_FORFEITED`); invoice payability (`ERR_INVOICE_NOT_PAYABLE`); LeaveInstance uniqueness on `(leave_case_id, instance_date)` (`ERR_DUPLICATE_INSTANCE_DAY`); and finally request-body schema (`ERR_VALIDATION`).

The reason the body-schema check sits at the bottom is so that an unauthenticated request never reveals the shape of the request body, and so that a case caught by a compliance hold or a quota ceiling surfaces *that* business reason rather than a generic field-type complaint.

### 2.7. Hours, Cents, Whole Days, and Rounding

Three numeric quantities recur throughout the system and each has a fixed representation. Hours are whole integers; the FMLA bucket is denominated in whole hours and a `LeaveInstance` records `hours_used` as a whole-hour count between 1 and 24 inclusive. Monetary amounts (`benefit_premium_share_cents`, `monthly_wage_cents`, `weekly_benefit_cents`, `amount_due_cents`) are integer cents — never floating-point dollars. Calendar days are whole days (an `instance_date` is a whole calendar day; the eligibility tenure threshold is whole calendar months floored to month boundaries). All monetary computations and the job-restoration score use round-half-up at every named step (per-step rounding, never sum-then-round), and the remaining-hours figure in the quota balance is floored at zero (no negative balance is ever exposed).

### 2.8. Hierarchical Consistency and Cascade Semantics

The system treats certain transitions as anchors that propagate consistency through related entities. When a `LeaveCase` is approved, every `PROPOSED` `LeaveInstance` on that case is promoted to `APPROVED` in the same transaction, the case's `hours_charged` is recomputed from the resulting set of `APPROVED` instances, any linked `PfLClaim` advances to its paying state, and the first `BenefitInvoice` for that case is issued. When a case is denied — whether for a clinical reason or because the certification deadline expired — every `LeaveInstance` on that case is voided, `hours_charged` is reset to zero (re-crediting the bucket), and `job_restoration_status` becomes `NOT_APPLICABLE`. When an `HRSpecialist` voids an individual `LeaveInstance` on an already-approved or active case, the parent case's `hours_charged` is recomputed from the surviving `APPROVED` instances; the bucket is re-credited proportionally.

A clock-driven cascade closes the loop: when a `BenefitInvoice` ages past 45 days from its `created_at`, it forfeits, and as part of that transition the parent `LeaveCase.job_restoration_status` cascades to `FORFEITED`. Any subsequent attempt at job restoration on that case is then refused with `ERR_JOB_RESTORATION_FORFEITED`.

Every mutation that modifies an entity carrying `version` and `updated_at` bumps `version` by 1 and refreshes `updated_at` to the server clock; cascades into other versioned entities (for example, the `Employee.employment_status` transition that accompanies an approved case becoming active) likewise bump that entity's `version` and refresh its `updated_at`.

### 2.9. Auditability

Every business-significant event is recorded as an `AuditEvent` row tied to a `leave_case_id`. The captured `event_kind` is drawn from a closed enumeration covering eligibility checks, case creation, certification submission and review, instance logging and voiding, quota recomputation, PFL linkage, the request and forfeiture of job restoration, and benefit-invoice issuance and forfeiture: specifically `ELIGIBILITY_CHECKED`, `CASE_CREATED`, `CERTIFICATION_SUBMITTED`, `CERTIFICATION_REVIEWED`, `INSTANCE_LOGGED`, `INSTANCE_VOIDED`, `QUOTA_RECOMPUTED`, `PFL_LINKED`, `JOB_RESTORATION_REQUESTED`, `JOB_RESTORATION_FORFEITED`, `BENEFIT_INVOICE_ISSUED`, and `BENEFIT_INVOICE_FORFEITED`. Each row captures the `actor_role` (the role header value of the acting caller, or the literal string `system` for clock-driven auto-events) and a free-form `detail_json` payload appropriate to the event kind. Audit rows are append-only; they are never updated or deleted.

### 2.10. The Server Clock and Test-Driving

Time-gated transitions — a case becoming active on its requested start date, a case completing on its expected end date, an invoice aging through grace and into forfeiture, a certification deadline expiring — are driven by the server clock rather than by direct client calls. A dedicated administrative capability advances that clock to a supplied target instant, and as part of that advancement the server fires every transition that is now due. A response indicating the new `now` and the number of `transitions_fired` is returned. This capability is restricted to `ComplianceOfficer` and is intended for tests and tabletop drills; production deployments may attach it to a real wall-clock tick rather than expose it externally, but the contract is unchanged.

## 3. Business Logic & Workflows

### 3.1. Establishing the Employer, Worksite, and Employee

Before any leave can be filed, a compliance officer seeds three things: an `Employer` row carrying the `legal_name`, the `leave_year_basis` (either `CALENDAR` for a January 1 through December 31 reckoning, or `ROLLING_BACKWARD` for a per-leave look-back of the twelve months immediately preceding the requested start date), the `state_pfl_program` value (either `NONE` if the employer is in a jurisdiction without a state paid-family-leave program, or `STATE_PFL_8WEEK` for the eight-week, sixty-percent wage-replacement program that runs concurrently with FMLA family-care leave), and a `benefit_premium_share_cents` value capturing the monthly cents the employee normally pays toward group-health coverage. One or more `Worksite` rows are then created under that employer, each with an `address_line` and an `employee_count_within_75_miles` figure — the number of employees on the employer's payroll at this worksite plus all worksites within seventy-five surface miles of it, counted at the moment the eligibility check runs. This count drives the third FMLA eligibility threshold and can be updated; when it is updated the change is purely forward-looking, with no retroactive effect on existing leave cases.

Employees are then created under an employer with a `worksite_id` linkage, a `full_name`, the `hire_date` capturing the start of continuous employment, the current `hours_worked_trailing_12mo` (a payroll feed snapshot of hours actually worked in the twelve calendar months ending at the server clock's most recent day), and a current `monthly_wage_cents`. An employee's `employment_status` defaults to `ACTIVE` and transitions across the values `ACTIVE`, `ON_LEAVE`, `TERMINATED`, and `RESTORED` as cases progress. A separate HR-driven endpoint refreshes `hours_worked_trailing_12mo` from a payroll feed; the refresh writes the new value with no retroactive recompute of past eligibility decisions.

### 3.2. Determining Eligibility

An employee is eligible to file a new FMLA case only when three conditions hold simultaneously. First, months of service at the moment of evaluation must be at least twelve; the months count is the difference between the server clock's current instant and `hire_date`, floored to whole-month boundaries (a hire date on the same day of the month twelve months earlier exactly satisfies the threshold). Failing this check yields `ERR_NOT_ELIGIBLE_TENURE`. Second, `hours_worked_trailing_12mo` must be at least 1250; failing this check yields `ERR_NOT_ELIGIBLE_HOURS`. Third, the employee's worksite must have an `employee_count_within_75_miles` of at least 50; failing this check yields `ERR_NOT_ELIGIBLE_WORKSITE`. All three thresholds are inclusive on the lower side: exactly twelve months of service passes; exactly 1250 hours passes; exactly 50 employees passes. The three checks are evaluated in the order tenure, hours, worksite, so a worker who fails on tenure does not see a worksite-headcount error.

A synchronous read-only eligibility capability is also exposed: when invoked for a given `employee_id`, it returns an object containing `eligible`, `reason_code` (the specific failing threshold's error id, or null if all three pass), `months_of_service`, `hours_trailing`, and `worksite_headcount`, all computed against the current server clock without persisting any side effect.

### 3.3. Filing the Leave Case

Filing a new case is a POST under an employee, carrying a `reason` drawn from `OWN_SERIOUS_HEALTH`, `FAMILY_SERIOUS_HEALTH`, `BABY_BONDING`, or `MILITARY_EXIGENCY`; a `leave_pattern` of `CONTINUOUS`, `INTERMITTENT`, or `REDUCED_SCHEDULE`; the `requested_start_date` and `expected_end_date` (both ISO 8601 UTC whole days, with `requested_start_date` at or after the current server-clock day and `expected_end_date` at or after `requested_start_date`); and optionally a `pfl_claim_id` linking the case to a previously created state PFL claim. The submission runs the eligibility check first; if the employee's `employment_status` is not `ACTIVE`, no submission is allowed. The case begins in `DRAFT` and on a successful submission transitions immediately to `PENDING_CERTIFICATION`, emitting an `AuditEvent` of kind `ELIGIBILITY_CHECKED` followed by one of kind `CASE_CREATED`.

At that submission the system pins several derived fields. The `certification_status` becomes `AWAITING_DOC` when the case `reason` is one of `OWN_SERIOUS_HEALTH` or `FAMILY_SERIOUS_HEALTH`, and becomes `NOT_REQUIRED` for all other reasons. The `cert_deadline` is set to the case's creation timestamp plus 15 calendar days. The `leave_year_anchor` is pinned based on the employer's `leave_year_basis`: for a `CALENDAR` employer it is set to January 1 of the year containing the `requested_start_date`, and for a `ROLLING_BACKWARD` employer it is set to the `requested_start_date` itself. The `hours_charged` field begins at 0 and the `job_restoration_status` begins as `PROTECTED`.

If a `pfl_claim_id` is supplied at submission, that claim must belong to the same employee, must be on a valid eight-week state PFL program (the employer's `state_pfl_program` must equal `STATE_PFL_8WEEK`; otherwise the submission is refused with `ERR_PFL_NOT_AVAILABLE`), and its `claim_type` must align with the case `reason` — a `claim_type` of `FAMILY_CARE` aligns with a case `reason` of `FAMILY_SERIOUS_HEALTH`, and a `claim_type` of `BABY_BONDING` aligns with a case `reason` of `BABY_BONDING`. Any mismatch — wrong employee or non-aligning category pair — surfaces as `ERR_PFL_MISMATCH`.

A case in `DRAFT` or `PENDING_CERTIFICATION` may be cancelled by the employee, transitioning `case_status` to `CANCELLED`; when cancelling from `PENDING_CERTIFICATION` every `LeaveInstance` on the case is voided and `hours_charged` is reset to 0. Cancellation accepts an optional `version` for optimistic concurrency.

### 3.4. Logging Absences: Intermittent and Reduced-Schedule Cases

For cases with a `leave_pattern` of `INTERMITTENT` or `REDUCED_SCHEDULE`, individual absences are recorded as `LeaveInstance` rows under the case, each carrying an `instance_date` (a whole calendar day) and an integer `hours_used` strictly between 1 and 24 inclusive. A `LeaveInstance` begins in `PROPOSED`; on approval of its parent case every `PROPOSED` instance on that case is promoted to `APPROVED`. A `CONTINUOUS` case does not allow manual instance logging — its consumption is computed from the start and end dates rather than from individual rows; any attempt to log an instance on a continuous case is refused with `ERR_INSTANCE_NOT_ALLOWED`, as is any attempt to log an `hours_used` outside the 1-to-24 range.

Two distinct uniqueness rules guard instance logging. First, a `(leave_case_id, instance_date)` pair must be unique: posting a second instance with the same date on the same case yields `ERR_DUPLICATE_INSTANCE_DAY`, and the first-writer-wins semantics on the underlying constraint also serialize two simultaneous POSTs on the same day to a single winner with the loser receiving the same code. Second, across all of a given employee's cases, no two `LeaveInstance` rows may share the same `instance_date` if both would consume hours in the same leave-year window — this catches the case of an employee posting overlapping absences against two different `LeaveCase` rows; the violation surfaces as `ERR_INSTANCE_OVERLAP`.

An `HRSpecialist` may void a single logged instance on an approved or active case; the void flips `instance_status` to `VOIDED`, recomputes `hours_charged` on the parent case from the surviving `APPROVED` instances, and re-credits the leave-year bucket accordingly.

### 3.5. Medical Certification

For the two case reasons that require medical attestation (`OWN_SERIOUS_HEALTH` and `FAMILY_SERIOUS_HEALTH`), the employee submits a `MedicalCertification` row carrying `serious_health_condition` (a boolean indicating whether the provider attests a serious health condition exists), and for intermittent cases the anticipated `estimated_frequency_per_month` (episodes per month, defaulting to 0 if not supplied) and `estimated_duration_hours` (hours per episode, defaulting to 0 if not supplied). Both estimate fields must be zero or greater. A `submitted_at` timestamp is captured by the server at the moment of posting. Submitting a certification flips the parent case's `certification_status` to `RECEIVED` and creates a new row; if a prior `INSUFFICIENT` certification exists it is preserved for audit and not deleted. A `MedicalCertification` row also records its own `review_outcome` which begins at `PENDING`.

An `HRSpecialist` then reviews the certification with a `decision` of `ACCEPT`, `INSUFFICIENT`, or `REJECT`. An `ACCEPT` decision is allowed only when the certification's `serious_health_condition` is true and the parent case's `certification_status` is `RECEIVED`; on success `review_outcome` becomes `ACCEPTED` and the parent case's `certification_status` becomes `COMPLETE`. A decision of `INSUFFICIENT` is allowed when the parent case is in `RECEIVED`; on success `review_outcome` becomes `INSUFFICIENT`, the parent `certification_status` becomes `INSUFFICIENT`, and the employee has seven calendar days from that moment to cure by re-submitting a fresh certification (the new submission creates a new `MedicalCertification` row beginning at `PENDING`, with the previous `INSUFFICIENT` row preserved; the cure is only accepted while the parent case is still in `PENDING_CERTIFICATION` and the current server clock is no later than the `cert_deadline` plus seven days). A decision of `REJECT` is reserved for the explicit case where the provider's `serious_health_condition` attestation is false; on a `REJECT`, `review_outcome` becomes `REJECTED` and the parent `certification_status` becomes `INSUFFICIENT`.

If the server clock passes the cure window — `cert_deadline` plus seven days — without an acceptable certification on file, the parent case's `certification_status` is locked permanently at `INSUFFICIENT` by the clock sweep.

### 3.6. The Approval Decision

When the certification picture is settled, an `HRSpecialist` decides the case by posting a `decision` of either `APPROVE` or `DENY`. Approval is allowed only when the parent case is in `PENDING_CERTIFICATION`, the case `certification_status` is in either `COMPLETE` or `NOT_REQUIRED`, the certification deadline has not been missed (specifically: it is not the case that `certification_status` is still `AWAITING_DOC` and the server clock is past `cert_deadline` — that combination yields `ERR_CERT_DEADLINE_MISSED`), and the available remaining hours for the employee's leave year are at least the sum of `hours_used` across every `PROPOSED` `LeaveInstance` on the case. Approving a case with a `certification_status` of `INSUFFICIENT` or `AWAITING_DOC` fails the certification-completeness check with `ERR_CERT_INCOMPLETE`; approving when the quota would be exceeded fails with `ERR_QUOTA_EXCEEDED`. On a successful approval the case's `case_status` becomes `APPROVED`, every `PROPOSED` `LeaveInstance` on the case becomes `APPROVED`, `hours_charged` is recomputed as the sum of `hours_used` across all `APPROVED` instances on the case, and an `AuditEvent` of kind `CERTIFICATION_REVIEWED` is emitted.

Three cascade links land at approval. First, the instance promotion described above. Second, if the case has a `pfl_claim_id` set, the case `reason` is one of `FAMILY_SERIOUS_HEALTH` or `BABY_BONDING`, and the employer's `state_pfl_program` is `STATE_PFL_8WEEK`, the linked `PfLClaim.claim_status` advances first to `APPROVED` and then to `PAYING`. Third, the first `BenefitInvoice` for the case is issued, sized for the calendar month containing the case's `requested_start_date` using the calculation described in §3.9.

Denial is the mirror image. A denial decision is allowed when the parent case is in `PENDING_CERTIFICATION` and either the `certification_status` is `INSUFFICIENT` or the `certification_status` is `AWAITING_DOC` and the server clock has passed `cert_deadline`. On a denial the `case_status` becomes `DENIED`, every `LeaveInstance` on the case transitions to `VOIDED`, `hours_charged` is reset to 0 (re-crediting the leave-year bucket entirely), `job_restoration_status` is set to `NOT_APPLICABLE`, and if a `pfl_claim_id` is set the linked `PfLClaim.claim_status` becomes `DENIED`.

Concurrency around the approval decision is sharp. Two `HRSpecialist` users attempting to approve the same case simultaneously serialize via the optimistic-concurrency check on `LeaveCase.version`: the loser receives `ERR_VERSION_CONFLICT`. An employee attempting to cancel the case at the same moment an HR specialist is approving it serializes against `case_status`: exactly one operation completes, and the loser sees `ERR_INVALID_STATE` because the case has already advanced out of the from-state the loser expected. Two leave-case submissions from the same employee that, taken together, would exceed the FMLA bucket are serialized inside the quota debit transaction: the first commit reserves the hours and the second is refused with `ERR_QUOTA_EXCEEDED`, because the quota recompute happens within the same transaction that flips `case_status` to `APPROVED`.

### 3.7. The FMLA Bucket: Quota Accounting Under Two Variants

The federal FMLA entitlement is twelve workweeks per leave year, which the system represents as 480 whole hours per employee per leave year (twelve workweeks of forty hours each). The crucial subtlety is *which* twelve months count as the leave year, and the answer depends on the employer's `leave_year_basis`.

Under the `CALENDAR` variant, the leave-year window is anchored to the calendar year containing the case's `requested_start_date`: the window begins on January 1 of that year (inclusive) and ends on December 31 of that year (inclusive). A leave that begins in late November therefore carries no hours into the new year — at the stroke of January 1 the bucket resets completely. Under the `ROLLING_BACKWARD` variant, the leave-year window is anchored to the case's `requested_start_date` itself and looks 365 days backward: the window begins 365 days before `requested_start_date` (inclusive) and ends on `requested_start_date` (inclusive). Each day's available hours therefore depend on what was used in the 365 days preceding it, and the same employee with identical usage history can have different remaining hours under the two variants on the same date.

Within whichever window applies, the consumed hours figure is the sum of `hours_used` across every `LeaveInstance` whose `instance_status` is `APPROVED`, whose owning `LeaveCase` is in a consumed state — meaning one of `APPROVED`, `ACTIVE`, `COMPLETED`, or `JOB_RESTORED` — and whose `instance_date` falls inside the window inclusive on both ends. The remaining hours figure is then 480 minus that consumed total, floored at zero so that an over-consumed bucket is reported as zero rather than as a negative number.

State PFL participation does *not* add a second bucket. When a case carries a `pfl_claim_id`, has a `reason` of `FAMILY_SERIOUS_HEALTH` or `BABY_BONDING`, and the employer's `state_pfl_program` is `STATE_PFL_8WEEK`, the PFL `weeks_authorized` multiplied by forty hours is *already* included inside the same FMLA bucket because the FMLA and PFL run concurrently — no separate addition is performed. This is the principle that makes the eight-week state benefit "concurrent rather than additive": a state-paid week is also an FMLA week.

The quota balance can be read at any time. The read returns the basis (the employer's `leave_year_basis`), the `window_start` and `window_end` dates (computed using the supplied `as_of_date` query parameter or the current server-clock day if not supplied), the `consumed_hours` figure, and the `remaining_hours` figure. The quota is consulted as a precondition when a leave case is submitted, decremented when the case is approved, re-credited when the case is denied, and recomputed when an instance is voided. Reading it has no side effect.

### 3.8. The State PFL Claim and Weekly Benefit

A state PFL claim is filed independently of the FMLA case it may pair with: a POST with `employee_id`, `claim_type` (either `FAMILY_CARE` or `BABY_BONDING`), and `weeks_authorized` (an integer between 1 and 8 inclusive). On creation the claim begins at `claim_status` of `SUBMITTED` and carries `weeks_paid` of 0. The weekly benefit amount is pinned at creation by a three-step calculation that must be performed with per-step rounding in the order given (per-step rounding, never sum-then-round). Step one converts the employee's `monthly_wage_cents` into a weekly wage in cents by multiplying by twelve, dividing by fifty-two, and rounding half-up to whole cents. Step two applies the wage-replacement ratio of sixty percent by multiplying the result of step one by 0.60 and rounding half-up to whole cents; the result is the raw weekly benefit. Step three applies the program cap: the final `weekly_benefit_cents` is the smaller of the raw weekly benefit and the cap of 162,900 cents (one thousand six hundred twenty-nine dollars). If the raw weekly benefit is less than or equal to the cap the under-cap variant applies and the final value equals the raw weekly benefit; if the raw weekly benefit exceeds the cap the at-cap variant applies and the final value equals the cap. The pinned `weekly_benefit_cents` is captured from the `monthly_wage_cents` value as it stood at the moment the `PfLClaim` row was created, and is frozen thereafter — subsequent wage changes do not retroactively adjust it.

A claim must be filed against a state with a real program: if the employer's `state_pfl_program` is `NONE`, claim creation is refused with `ERR_PFL_NOT_AVAILABLE`, as is any submission with `weeks_authorized` outside the 1-to-8 range. The `claim_status` advances to `APPROVED` and then `PAYING` when a paired FMLA case is approved (see §3.6); it ends at `EXHAUSTED` when all authorized weeks have been paid; and it ends at `DENIED` if the paired FMLA case is denied. The number of `weeks_paid` is computed as the claim progresses.

### 3.9. Benefit Continuation and the Monthly Invoice

While an employee is on approved leave, the employer must continue group-health coverage but the employee is invoiced monthly for the premium share they would normally have paid via payroll deduction. A `BenefitInvoice` row carries the `leave_case_id` it belongs to, the `period_month` (formatted as YYYY-MM, validated by a pattern that requires four digits, a hyphen, and a two-digit month between 01 and 12), an `amount_due_cents` figure, and an `invoice_status` lifecycle that begins at `ISSUED`.

The amount due is the employer's `benefit_premium_share_cents` prorated by the fraction of the calendar month that the employee was actually on leave. First, the days-in-month figure is the number of calendar days in `period_month` (28, 29, 30, or 31 as appropriate). Second, the days-on-leave-in-month figure is computed: for intermittent and reduced-schedule cases it is the count of `LeaveInstance` rows on this case whose `instance_status` is in `APPROVED` or `PROPOSED` and whose `instance_date` falls anywhere between the first and last calendar day of `period_month` inclusive; for continuous cases, an additional bridge count is added — every calendar day from the later of `requested_start_date` or the first day of `period_month`, through the earlier of `expected_end_date` or the last day of `period_month`, inclusive. (For purely continuous cases this bridge term is the entire contribution; for intermittent cases the per-instance count is the entire contribution.) The chronological algorithm processes calendar months in order so each month sees that month's actual on-leave day count. Finally, the `amount_due_cents` is the employer's `benefit_premium_share_cents` multiplied by the days-on-leave-in-month divided by the days-in-month, rounded half-up to whole cents.

The first invoice is issued automatically when the case transitions to `APPROVED`, sized for the calendar month containing `requested_start_date`. Subsequent invoices are issued by the clock sweep as each new calendar-month boundary is crossed while the case remains in `APPROVED` or `ACTIVE`. An invoice may be paid by the employee or by an HR specialist on the employee's behalf, transitioning `invoice_status` from `ISSUED` to `PAID`; payment is allowed when `invoice_status` is in `ISSUED` or `GRACE`, and any other status yields `ERR_INVOICE_NOT_PAYABLE`. An unpaid invoice ages: when the server clock crosses thirty days from the invoice's `created_at` the `invoice_status` transitions from `ISSUED` to `GRACE`; when the server clock crosses forty-five days from the invoice's `created_at` the `invoice_status` transitions from `GRACE` to `FORFEITED`. Forfeiture cascades into the parent `LeaveCase.job_restoration_status`, setting it to `FORFEITED` and emitting `AuditEvent` rows of kind `BENEFIT_INVOICE_FORFEITED` followed by `JOB_RESTORATION_FORFEITED`.

### 3.10. Returning to Work, Job Restoration, and the Restoration Score

When the employee is ready to return to work, the case advances from `ACTIVE` to `COMPLETED`. This advance can be employee-initiated by a posted return, or system-initiated by the clock sweep crossing the `expected_end_date`; in both cases the precondition is that the server clock is at or past `requested_start_date`, and for non-continuous cases that `hours_charged` equals the sum of `hours_used` across all `APPROVED` instances on the case with no `PROPOSED` instances remaining. A continuous case may complete unconditionally once its end date is reached. The same precondition (server clock at or past `requested_start_date`) gates the related system-driven advance from `APPROVED` to `ACTIVE`, which fires when the clock crosses `requested_start_date` and which also flips the parent `Employee.employment_status` to `ON_LEAVE`.

Once the case is `COMPLETED`, an `HRSpecialist` may restore the employee to their job by posting the restore decision; this transitions the `case_status` from `COMPLETED` to `JOB_RESTORED` and the `Employee.employment_status` from `ON_LEAVE` or `ACTIVE` to `RESTORED`. Restoration is allowed only when the `job_restoration_status` is `PROTECTED` and there is no outstanding `BenefitInvoice` on this case in the `FORFEITED` status; any other condition surfaces as `ERR_JOB_RESTORATION_FORFEITED`. If the clock sweep flips `job_restoration_status` to `FORFEITED` (via a benefit invoice aging into forfeiture) at the same moment an HR specialist attempts to restore the job, the clock sweep wins on the underlying field and the restoration attempt is rejected with `ERR_JOB_RESTORATION_FORFEITED`.

The `job_restoration_status` value carried on a case is derived continuously from a job-restoration score that is recomputed at every return event, every benefit-invoice transition, every clock sweep that crosses a `cert_deadline`, and on every read of the case. The score starts at a base of 100 and is then adjusted in three multiplicative steps, in this fixed order, with round-half-up applied after each step (per-step rounding, never sum-then-round). Step one — the certification penalty — multiplies the score by 0.50 if the case's `certification_status` is `INSUFFICIENT` at the moment of evaluation, and otherwise leaves it unchanged. Step two — the invoice penalty — multiplies the score by 0.00 (yielding zero) if any `BenefitInvoice` on the case has `invoice_status` of `FORFEITED`, otherwise multiplies by 0.75 if any has `invoice_status` of `GRACE`, otherwise leaves it unchanged. Step three — the tenure bonus — multiplies the score by 1.10 if the employee's `hours_worked_trailing_12mo` is at least 2000, otherwise leaves it unchanged; after this step the score is rounded half-up and then clamped to a maximum of 100. The final `job_restoration_status` is `PROTECTED` if the resulting score is at least 50, and `FORFEITED` otherwise. A `case_status` of `DENIED` overrides this entire calculation: `job_restoration_status` is set to `NOT_APPLICABLE` on denial regardless of the score.

### 3.11. Cancellation, Termination, and Outright Refusal

A case in `DRAFT` may be cancelled by the employee, advancing `case_status` to `CANCELLED` with no further side effect. A case in `PENDING_CERTIFICATION` may likewise be cancelled by the employee, with the additional effect of voiding every `LeaveInstance` on the case and resetting `hours_charged` to 0. Both transitions accept an optional `version` for optimistic concurrency. Any attempt to mutate a `LeaveCase` while the owning `Employee.employment_status` is `TERMINATED` is refused with `ERR_EMPLOYEE_TERMINATED`. Any attempt to perform a state transition from a `case_status` not in that transition's allowed-from set is refused with `ERR_INVALID_STATE` — this is the catch-all for stale state machines and the loser of a same-target-state race.

## 4. Endpoint Definitions

All endpoints honor the conventions established in §2 (response envelope, pagination, OCC, role-based access, error ordering). New resource creation returns HTTP 201; reads, modifications, and idempotent administrative operations return 200; deletions that produce no response body return 204. Request and response bodies are described in §3's narrative subsections — the table below summarizes the surface area only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /employers | Create an employer. | ComplianceOfficer |
| GET | /employers/{employer_id} | Read an employer. | ComplianceOfficer, HRSpecialist |
| POST | /employers/{employer_id}/worksites | Create a worksite under an employer. | ComplianceOfficer |
| PATCH | /worksites/{worksite_id} | Update worksite headcount; drives forward-looking eligibility. | ComplianceOfficer |
| POST | /employers/{employer_id}/employees | Create an employee. | ComplianceOfficer, HRSpecialist |
| GET | /employees/{employee_id} | Read employee. | ComplianceOfficer, HRSpecialist, Employee |
| POST | /employees/{employee_id}/hours-snapshot | Refresh trailing-twelve-month hours from a payroll feed. | HRSpecialist |
| GET | /employees/{employee_id}/eligibility-snapshot | Synchronous eligibility evaluation at the current server clock. | HRSpecialist, Employee |
| GET | /employees/{employee_id}/quota-balance | FMLA quota balance under the employer's leave-year basis. | HRSpecialist, Employee |
| POST | /employees/{employee_id}/leave-cases | Submit a new FMLA/PFL case. | Employee, HRSpecialist |
| GET | /leave-cases/{leave_case_id} | Read a leave case (includes computed job-restoration score and `hours_charged`). | Employee, HRSpecialist, ComplianceOfficer |
| GET | /employees/{employee_id}/leave-cases | List leave cases for an employee. | Employee, HRSpecialist, ComplianceOfficer |
| POST | /leave-cases/{leave_case_id}/instances | Log a single-day instance under an intermittent or reduced-schedule case. | Employee, HRSpecialist |
| DELETE | /leave-cases/{leave_case_id}/instances/{instance_id} | Void a logged instance. | HRSpecialist |
| POST | /leave-cases/{leave_case_id}/certifications | Submit a medical certification packet. | Employee |
| POST | /leave-cases/{leave_case_id}/certifications/{cert_id}/review | Review a medical certification packet. | HRSpecialist |
| POST | /leave-cases/{leave_case_id}/review | Decide APPROVE or DENY on the case. | HRSpecialist |
| POST | /leave-cases/{leave_case_id}/return | Return to work, ending the leave. | Employee, HRSpecialist |
| POST | /leave-cases/{leave_case_id}/restore-job | Mark the employee restored to position. | HRSpecialist |
| DELETE | /leave-cases/{leave_case_id} | Cancel a case while it is still DRAFT or PENDING_CERTIFICATION. | Employee |
| POST | /pfl-claims | Create a state PFL claim. | Employee, HRSpecialist |
| GET | /pfl-claims/{pfl_claim_id} | Read a PFL claim. | Employee, HRSpecialist, ComplianceOfficer |
| GET | /leave-cases/{leave_case_id}/benefit-invoices | List benefit invoices for a case. | Employee, HRSpecialist |
| POST | /benefit-invoices/{invoice_id}/pay | Mark an invoice paid. | Employee, HRSpecialist |
| GET | /leave-cases/{leave_case_id}/audit-events | Append-only audit log for a case. | HRSpecialist, ComplianceOfficer |
| POST | /_clock/advance | Advance the server clock to a supplied `to_timestamp`, firing all transitions now due. | ComplianceOfficer |
| GET | /_health | Liveness probe; returns the server clock. | * |

## 5. Error Code Catalogue

The trigger conditions for each error code are described inline in §2 and §3, alongside the workflow or constraint that surfaces them. This catalogue lists only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH_HEADERS | 401 |
| ERR_UNKNOWN_ROLE | 401 |
| ERR_UNKNOWN_IDENTITY | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_EMPLOYEE_TERMINATED | 409 |
| ERR_NOT_ELIGIBLE_TENURE | 422 |
| ERR_NOT_ELIGIBLE_HOURS | 422 |
| ERR_NOT_ELIGIBLE_WORKSITE | 422 |
| ERR_CERT_DEADLINE_MISSED | 422 |
| ERR_CERT_INCOMPLETE | 422 |
| ERR_QUOTA_EXCEEDED | 422 |
| ERR_INSTANCE_NOT_ALLOWED | 422 |
| ERR_INSTANCE_OVERLAP | 422 |
| ERR_PFL_NOT_AVAILABLE | 422 |
| ERR_PFL_MISMATCH | 422 |
| ERR_JOB_RESTORATION_FORFEITED | 409 |
| ERR_INVOICE_NOT_PAYABLE | 409 |
| ERR_DUPLICATE_INSTANCE_DAY | 409 |
| ERR_VALIDATION | 400 |
