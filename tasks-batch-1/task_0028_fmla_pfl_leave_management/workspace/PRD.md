# FMLA / PFL Leave Management API — Product Requirements Document

## 1. Introduction

Federal Family and Medical Leave Act (FMLA) entitlements interact with a growing patchwork of state Paid Family Leave (PFL) programs, employer-sponsored health-benefit obligations, and statutory notice deadlines in ways that most HR teams cannot manage by hand without dropping a thread. A single leave request is, in practice, a multi-month workflow that simultaneously consumes a federal twelve-week protected-time pool, draws from a state-specific paid pool with its own quota, drives prorated employer/employee health-premium accounting on a monthly cadence, and rests on a chain of statutory notices and medical certifications whose response windows are themselves legally enforceable. Errors at any one of these steps — approving a case against a stale certification, charging the wrong FMLA pool variant, missing the thirty-day delinquency cliff on premium continuation — translate directly into legal exposure for the employer and lost job-restoration protection for the employee.

This document specifies the FMLA / PFL Leave Management API, a service that an employer's HR organisation uses end-to-end: registering employees and healthcare providers, intake of leave requests, eligibility determination against the twelve-month and 1,250-hour federal thresholds, medical certification handling, the dual-pool charge waterfall when state PFL runs concurrently with FMLA, prorated benefit-continuation accounting while the employee is on leave, and the job-restoration decision once the leave completes. The system is the canonical record of every transition that affects a leave case's statutory protections; it is read by HR officers approving cases, by employees checking their own status, by treating providers submitting certifications, and by a deterministic test harness that drives the logical clock forward to verify time-dependent transitions such as the thirty-day premium-delinquency cascade.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API call must carry two HTTP headers: `X-User-ID`, the identifier of the calling principal, and `X-User-Role`, the role the principal is acting under for this request. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` is not on the endpoint's permitted-role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles exist, with exact spelling preserved everywhere the role is referenced:

- `PlatformAdmin` — the platform operator who provisions employers, registers providers, and drives the deterministic-clock test fixtures. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, in audit fields) but does not compare it to any entity's `id`.
- `HRAdmin` — the employer-side HR officer who runs the FMLA / PFL workflow end-to-end: eligibility evaluation, certification lifecycle, case approval and denial, interval recording, benefit-continuation accounting, and recertification. When `X-User-Role` is `HRAdmin`, `X-User-ID` is likewise an opaque operator identifier; the server may record it but does not match it against any entity's `id`.
- `Employee` — a worker submitting a leave request or viewing their own case. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` (a `LeaveCase`, `LeaveInterval`, `BenefitContinuationLedger`, or `Notice`) compare the resource's `employee_id` (or the `employee_id` on its parent `LeaveCase`) to `X-User-ID`.
- `HealthcareProvider` — the treating provider who files medical certifications. When `X-User-Role` is `HealthcareProvider`, `X-User-ID` is the `id` of the acting `HealthcareProvider`; ownership checks on any `CertificationRecord` compare the record's `provider_id` to `X-User-ID`.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). Results are returned in ascending order of `created_at`. The pagination envelope in `meta` carries `limit`, `offset`, `total_count` (the unfiltered-by-window total of rows matching the query), and `has_more` (true when more rows exist after the current page).

### 2.4. Common Resource Properties

Every persisted entity in this system carries a server-minted `id` (a UUID with no type prefix) and a `created_at` timestamp (ISO 8601 UTC with three fractional digits). All entities in this domain also carry `updated_at` (ISO 8601 UTC with three fractional digits, refreshed on every server-side mutation) and `version` (an integer that begins at 1 on creation and increments by exactly one on every server-side mutation that modifies a non-system field of the resource). The `id`, `created_at`, `updated_at`, and `version` are read-only from the client's perspective: they are emitted in every resource payload but never accepted as input.

### 2.5. Nested Resource Retrieval

URLs are validated left-to-right. When a path contains multiple `{id}` segments, each segment is resolved in order; the first unresolved id yields `ERR_NOT_FOUND` (HTTP 404) and short-circuits the remainder of the request. The same `ERR_NOT_FOUND` is returned when a leaf `{id}` resolves to an entity of the wrong type for the endpoint. Foreign-key references embedded in request bodies — any field whose name ends in `_id` — are resolved before any business validation runs; an unresolved body-side reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404).

### 2.6. Validation Precedence

Validation is evaluated in a fixed total order, and the first failing check determines the response. The order is: (1) authentication header presence, returning `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, returning `ERR_FORBIDDEN`; (3) path-id resolution left-to-right, returning `ERR_NOT_FOUND`; (4) request-body foreign-key resolution, returning `ERR_REFERENCED_ENTITY_NOT_FOUND`; (5) entity-state precondition for the requested transition, returning `ERR_INVALID_STATE`; (6) the acting employee is not in `TERMINATED` status for case submission, eligibility evaluation, and case approval, returning `ERR_EMPLOYEE_TERMINATED`; (7) on case approval, the most-recent `CertificationRecord` is `COMPLETE`, returning `ERR_CERTIFICATION_INCOMPLETE`; (8) on certification mark-complete for an `INTERMITTENT` or `REDUCED_SCHEDULE` case, the intermittent fields are populated, returning `ERR_INTERMITTENT_CERT_REQUIRED`; (9) the supplied optimistic-concurrency version field matches the live parent version on the two OCC-guarded endpoints, returning `ERR_STALE_VERSION`; (10) on eligibility evaluation, the employee meets both the twelve-months-of-service and the 1,250-hours thresholds, returning `ERR_INELIGIBLE`; (11) on interval recording, the new interval does not overlap an existing `RECORDED` interval, returning `ERR_INTERVAL_OVERLAP`; (12) on interval recording for an `INTERMITTENT` case, the monthly episode count including this interval does not exceed the certified frequency, returning `ERR_INTERMITTENT_FREQUENCY_EXCEEDED`; (13) on interval recording for an `INTERMITTENT` case, `hours_taken` does not exceed the certified per-episode hours, returning `ERR_INTERMITTENT_HOURS_EXCEEDED`; (14) on recertification request, at least thirty days have passed since the prior `COMPLETE` certification's `received_at`, returning `ERR_RECERT_TOO_SOON`; (15) on payment application, the amount is strictly positive and does not exceed the outstanding balance, returning `ERR_INVALID_PAYMENT_AMOUNT`; (16) request-body well-formedness — required fields present, correct types, valid enum values — returning `ERR_INVALID_REQUEST`. The well-formedness check sits at the tail because earlier checks (notably state, OCC, and business-temporal checks) are designed to surface higher-signal errors first when their structural preconditions are met.

### 2.7. Hierarchical Consistency and Cascading Side Effects

Every transition or mutation in this system bumps `version` by one on the directly-affected resource and refreshes its `updated_at`. Many transitions also cascade: case approval pins `pfl_concurrent` on the case, issues a designation notice, and (when the employee is enrolled in the health plan) seeds the first benefit-continuation ledger row; recording the first interval on an `APPROVED` case advances the case to `ACTIVE` and the employee to `ON_LEAVE`; reversing an interval restores the per-case hours-charged accumulators and may flip `job_restoration_protected` back to true; clock advancement transitions any past-thirty-day past-due ledger row to `DELINQUENT` and clears the corresponding case's restoration protection. The cascades are described in the workflow narratives in §3 — they are normative, not informational. Whenever a cascade modifies a resource, that resource's `version` and `updated_at` are advanced as if it had been modified by a direct call.

### 2.8. Optimistic Concurrency Control

Two endpoints are OCC-guarded; all others are not, and clients should not send a version field to non-guarded endpoints. The first guarded write is case approval: the request must carry `expected_leave_case_version` matching the target case's current `version` at the time the server reads it. If another writer has advanced the case's version since the client last read it — most typically because a fresh recertification request has just rotated which `CertificationRecord` is authoritative — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). The second guarded write is the employee health-enrollment toggle: the request must carry `expected_employee_version` matching the target `Employee`'s current `version`. If a prior writer toggled the same flag and bumped the employee's version (say from 5 to 6) while the current writer is still holding version 5, the second writer is deterministically rejected with `ERR_STALE_VERSION` (HTTP 412). Neither rule is framed in terms of simultaneity: each is a stale-version check evaluated sequentially against the live parent version at request time.

### 2.9. Precision, Rounding, and the Two-Pool Charge Order

FMLA and PFL hours are accounted to one decimal place per interval, rounded half up at the moment the interval is charged; per-case `fmla_hours_charged` and `pfl_hours_charged` are the sum of those rounded per-interval values, never a re-rounding of an underlying raw sum. The federal FMLA pool quota is 480 hours per twelve-week period (twelve weeks times forty hours), measured either as a rolling-backward 365-day window or as a calendar year, pinned per-employer (see §3.2). State PFL pool quotas, applied when `pfl_concurrent` is true on a case, are per-state: 320 hours in CA (eight weeks), 200 hours in RI, 480 hours in NY, NJ, MA, WA, CT, CO, and OR (twelve weeks), and 0 hours in FED. Benefit-continuation premium shares are computed in integer cents and rounded half up; the leave-fraction intermediate is rounded half up to four decimal places before any multiplication, and the employer and employee shares are each rounded half up to whole cents after multiplication. The reversed ordering (multiply then round) drifts by up to one cent per period and is explicitly forbidden.

### 2.10. Notice Lifecycle and Statutory Response Windows

Notices are an auditable record of the statutory communications that an employer must issue. Five categories exist, with exact `notice_type` strings: `ELIGIBILITY_NOTICE` and `RIGHTS_RESPONSIBILITIES_NOTICE` are issued together when a leave case is first created; `DESIGNATION_NOTICE` is issued at case approval; `CERTIFICATION_DEMAND` is issued when the case moves into the certification-pending phase; `RECERTIFICATION_REQUEST` is issued when HR opens a new certification round (whether triggered by an insufficient prior certification or by an explicit recertification request). Each notice carries `sent_at`, recorded at the moment of issuance. The two demand-style notices — `CERTIFICATION_DEMAND` and `RECERTIFICATION_REQUEST` — set `response_due_at` to fifteen days after `sent_at`; the three other notice types leave `response_due_at` null. A notice's `response_received` is true once a corresponding `CertificationRecord` reaches `RECEIVED` no later than `response_due_at`.

## 3. Business Logic & Workflows

### 3.1. Employer Setup, State PFL Mapping, and the FMLA Method

An employer profile is created by a `PlatformAdmin` carrying a `legal_name`, the worksite's `state_code` (one of `CA`, `NY`, `NJ`, `MA`, `WA`, `CT`, `RI`, `CO`, `OR`, `FED`), the employer's monthly health-premium share `employer_premium_share_pct` (a number between 0.00 and 1.00 inclusive, with two-decimal-place precision), and the total monthly health premium `monthly_premium_total_cents` (a non-negative integer in cents). The `fmla_method` is an optional input that defaults to `ROLLING_BACKWARD` and may otherwise be set to `CALENDAR_YEAR`; once any employee under this employer has used FMLA hours, the method is pinned and may not be changed. At creation, the server computes `pfl_enabled` from the worksite state: it is true when `state_code` is one of `CA`, `NY`, `NJ`, `MA`, `WA`, `CT`, `RI`, `CO`, `OR` and false when `state_code` is `FED`; the flag is recomputed whenever `state_code` is updated.

### 3.2. FMLA Quota Mathematics — Two Variants, One per Employer

The federal FMLA entitlement is 480 hours per twelve-week period, but the period is computed differently depending on the employer's pinned `fmla_method`. Under `ROLLING_BACKWARD`, the relevant window for a leave request is from 365 days before the case's `requested_start_at` up to (but not including) `requested_start_at`, and the FMLA hours charged is the sum of `fmla_hours_charged` over every `RECORDED` `LeaveInterval` belonging to the same employee whose `start_datetime` falls in that window; the remaining quota is 480 minus that sum, floored at zero. Under `CALENDAR_YEAR`, the window is the calendar year (UTC) containing `requested_start_at`, the charged hours is the sum of `fmla_hours_charged` across `RECORDED` intervals whose `start_datetime` falls in that year, and remaining is again 480 minus that sum floored at zero; the window resets at January 1 UTC. The variants differ only in how the relevant window is defined and which intervals contribute, not in the quota constant.

When a leave interval straddles a variant boundary — for example, a multi-day interval whose `start_datetime` falls inside the rolling-backward window and whose `end_datetime` falls outside it — the entire `fmla_hours_charged` of that interval is attributed to the window containing `start_datetime`. The implementation must not prorate across the boundary; the rule is pinned.

### 3.3. Employees, Health Enrollment, and the Two Eligibility Thresholds

`HRAdmin` registers each `Employee` against the parent employer via `employer_id`, capturing the worker's `email` (case-insensitive unique within an employer), `full_name`, `hire_date` (UTC midnight), the running `hours_worked_trailing_12mo` count, the work-site `home_state_code`, and the optional `health_plan_enrolled` flag (defaulting to true). The employee's `employment_status` begins at `ACTIVE` and is re-derived by the system: it moves to `ON_LEAVE` when a case becomes `ACTIVE` and returns to `ACTIVE` when the case moves to `COMPLETED`. Termination is performed by an HR officer; if the employee is currently `ON_LEAVE` with `job_restoration_protected` still true, the termination attempt is rejected with `ERR_INVALID_STATE`, otherwise the status becomes `TERMINATED`. Once an acting employee's `employment_status` is `TERMINATED`, the three guarded calls — submitting a new case, evaluating eligibility on an existing case, and approving a case — all return `ERR_EMPLOYEE_TERMINATED`.

Health enrollment is mutated via a dedicated toggle, the only endpoint that updates `health_plan_enrolled` after employee creation. The toggle is OCC-guarded by `expected_employee_version` as described in §2.8.

Eligibility is a two-threshold test that is evaluated only when an HR officer drives an eligibility evaluation against an `ELIGIBILITY_PENDING` case. The first threshold is twelve months of service: the difference between `requested_start_at` and the employee's `hire_date`, expressed in days divided by thirty and floored to a whole number of months, must be at least twelve. The second threshold is hours worked: the employee's `hours_worked_trailing_12mo` must be at least 1250. The case advances to `CERTIFICATION_PENDING` only when both thresholds hold; otherwise the case is moved straight to `DENIED`. Either outcome stamps `eligibility_evaluated` to true, snapshots the tenure as `tenure_months_at_request` (the floored months value), and snapshots the running hours figure as `hours_at_request`. The threshold-failure branch returns `ERR_INELIGIBLE` to the caller when the call was driven against an employee who fails one or both checks at the moment of evaluation. Eligibility evaluation is HR-exclusive.

### 3.4. The Leave-Case Lifecycle, Notice Issuance, and Case Approval

A leave case is opened by an employee or by an HR officer submitting a request with the acting `employee_id`, the `qualifying_reason` (one of `OWN_SERIOUS_HEALTH_CONDITION`, `FAMILY_SERIOUS_HEALTH_CONDITION`, `NEW_CHILD_BONDING`, `MILITARY_CAREGIVER`, `QUALIFYING_EXIGENCY`), the `leave_type` (`CONTINUOUS`, `INTERMITTENT`, or `REDUCED_SCHEDULE`), and the requested span `requested_start_at` to `requested_end_at`. The submission is rejected unless the acting `Employee.employment_status` is `ACTIVE`, the requested start lies in the future of now (no retroactive submission), and the qualifying reason is one of the listed values. On acceptance the case enters `SUBMITTED` and, within the same request, advances to `ELIGIBILITY_PENDING`; an `ELIGIBILITY_NOTICE` and a `RIGHTS_RESPONSIBILITIES_NOTICE` are auto-created at that moment, with `response_due_at` on the eligibility notice set to `sent_at` plus five days and the rights-and-responsibilities notice left with `response_due_at` null.

Eligibility evaluation (§3.3) takes the case to either `DENIED` (a terminal state) or `CERTIFICATION_PENDING`. On entering `CERTIFICATION_PENDING`, the server auto-creates a `CERTIFICATION_DEMAND` notice whose `response_due_at` is fifteen days after `sent_at`; this is the operational deadline by which the employee's treating provider must return a complete certification.

Case approval — the transition from `CERTIFICATION_PENDING` to `APPROVED` — is HR-exclusive and OCC-guarded. The request body carries `expected_leave_case_version`. The most-recent `CertificationRecord` on the case must be in `COMPLETE`; otherwise the approval is rejected with `ERR_CERTIFICATION_INCOMPLETE`. The acting employee must not be `TERMINATED`. On success the server stamps `pfl_concurrent` on the case using the rule: `pfl_concurrent` is true when the employer's `pfl_enabled` is true, the employee's `home_state_code` equals the employer's `state_code`, and the case's `qualifying_reason` is one of `OWN_SERIOUS_HEALTH_CONDITION`, `FAMILY_SERIOUS_HEALTH_CONDITION`, or `NEW_CHILD_BONDING`; the flag is pinned at approval and never changes thereafter. The case's `job_restoration_protected` is set to true. A `DESIGNATION_NOTICE` is auto-issued. If the employee's `health_plan_enrolled` is true, the server creates the first `BenefitContinuationLedger` row covering the period from `requested_start_at` to `requested_start_at` plus one month, with the period-start and period-end shares computed via the premium-continuation calculation in §3.6. The case's `version` is bumped by one and `updated_at` refreshed.

Denial without approval — the `CERTIFICATION_PENDING` → `DENIED` transition driven by HR — is permitted when either no `CertificationRecord` reached `COMPLETE` before the case's certification window expired (now is past the `CERTIFICATION_DEMAND` notice's `response_due_at` and no record on the case is in `COMPLETE`) or the case carries a `CertificationRecord` in `INSUFFICIENT` with no later record having been created.

### 3.5. The Certification Lifecycle and Recertification Cycle

A certification record is submitted by a `HealthcareProvider` (or by HR on the provider's behalf) carrying the target `leave_case_id`, the certifying `provider_id`, the `expected_duration_weeks` the provider attests to, optionally `intermittent_frequency_per_month` and `intermittent_hours_per_episode` for non-`CONTINUOUS` cases, and the `provider_attestation_signed_at` instant. The record is created in `PENDING`. Each `HealthcareProvider` is identified by a case-insensitive unique `license_id`, a `full_name`, and a free-text `specialty`.

When the signed copy reaches HR, HR drives the receive transition: the record's `received_at` is stamped with now, and it moves from `PENDING` to `RECEIVED`. The receive transition is allowed only when the case is in `CERTIFICATION_PENDING` and `provider_attestation_signed_at` is set.

A received record is then either marked complete or marked insufficient. Marking complete advances `RECEIVED` to `COMPLETE`, but only when (a) for an `INTERMITTENT` or `REDUCED_SCHEDULE` case, both `intermittent_frequency_per_month` is at least one and `intermittent_hours_per_episode` is strictly greater than zero — otherwise `ERR_INTERMITTENT_CERT_REQUIRED` is returned; (b) for a `CONTINUOUS` case, `expected_duration_weeks` is strictly greater than zero; and (c) there is no later record on the same case. Marking complete makes this record authoritative and unblocks case approval. Marking insufficient requires a non-empty `insufficient_reason` in the request body, takes the record from `RECEIVED` to `INSUFFICIENT`, and auto-creates a `RECERTIFICATION_REQUEST` notice on the case with `response_due_at` fifteen days after `sent_at`.

Recertification is opened by an HR officer against an `APPROVED` or `ACTIVE` case. The request is rejected with `ERR_RECERT_TOO_SOON` if fewer than thirty days have elapsed since the prior `COMPLETE` certification's `received_at`. On success the server creates a new `CertificationRecord` in `PENDING`, transitions the previous `COMPLETE` record to `RECERTIFICATION_REQUESTED`, and issues a `RECERTIFICATION_REQUEST` notice with `response_due_at` fifteen days after `sent_at`. The previous-record transition is the cycle endpoint: `COMPLETE → RECERTIFICATION_REQUESTED` on the older record runs in parallel with the new record's own `PENDING → RECEIVED → COMPLETE` path. Note that because opening a recertification bumps the case's `version`, any HR officer holding a stale view of the case at this moment will fail OCC on a subsequent approve attempt — this is the precise scenario `ERR_STALE_VERSION` is designed to catch.

`certification_status` ranges over `PENDING`, `RECEIVED`, `INSUFFICIENT`, `COMPLETE`, and `RECERTIFICATION_REQUESTED`. `COMPLETE` is the terminal state for the forward-walking certification path; `RECERTIFICATION_REQUESTED` is the cycle-back state on a superseded prior record.

### 3.6. Recording Intervals, the Two-Pool Charge Waterfall, and Job-Restoration Protection

Leave intervals are recorded by HR after the case is `APPROVED`. Each interval carries the parent `leave_case_id`, a `start_datetime` and `end_datetime` (the end is exclusive), and the `hours_taken` actually used. The first interval recorded against an `APPROVED` case drives the case to `ACTIVE` and sets `Employee.employment_status` to `ON_LEAVE`; at the same moment the server sets the employee's `job_restoration_deadline` to `requested_start_at` plus 84 days (which is twelve weeks). Subsequent intervals leave the case in `ACTIVE`. Recording the first interval is permitted only when now is at or after the case's `requested_start_at`.

No interval may overlap a `RECORDED` interval already on the same case: the rule rejects any new interval whose `start_datetime` is strictly before another's `end_datetime` and whose `end_datetime` is strictly after the other's `start_datetime`, returning `ERR_INTERVAL_OVERLAP`; adjacency (where the new `start_datetime` equals an existing `end_datetime`) is allowed. For `INTERMITTENT` and `REDUCED_SCHEDULE` cases, the count of `RECORDED` intervals already in the calendar month containing `start_datetime`, including this new interval, must not exceed the authoritative certification's `intermittent_frequency_per_month` — otherwise the call is rejected with `ERR_INTERMITTENT_FREQUENCY_EXCEEDED`. For those same cases, `hours_taken` on a single interval must not exceed the certification's `intermittent_hours_per_episode` — otherwise `ERR_INTERMITTENT_HOURS_EXCEEDED`.

On recording, the server runs the two-pool charge waterfall to derive the per-interval `fmla_hours_charged` and `pfl_hours_charged`. The evaluation order is pinned: FMLA is charged first, then PFL is derived from the FMLA charge, never from raw hours. First, the FMLA remaining is the larger of zero and 480 minus the case's pre-existing `fmla_hours_charged`, and the interval's FMLA charge is the smaller of `hours_taken` and that FMLA remaining. Second, when the case's `pfl_concurrent` flag is true, the PFL remaining is the larger of zero and the employee's state-specific PFL quota — 320 for `CA`, 480 for `NY`, 480 for `NJ`, 480 for `MA`, 480 for `WA`, 480 for `CT`, 200 for `RI`, 480 for `CO`, 480 for `OR`, and 0 for `FED` — minus the case's pre-existing `pfl_hours_charged`, and the interval's PFL charge is the smaller of the FMLA charge just computed and that PFL remaining. When `pfl_concurrent` is false, the PFL charge is zero. Third, any hours in `hours_taken` not absorbed by the FMLA charge (the difference between `hours_taken` and the FMLA charge) are taken but not debited to FMLA — they are unprotected hours, and they do not consume job-restoration protection on their own; rather, once the case's cumulative `fmla_hours_charged` reaches 480, `job_restoration_protected` flips to false. Reversing the evaluation order — exhausting PFL before charging FMLA — would produce a different total FMLA balance and a different protection-flip point in the boundary case where the state's PFL quota is less than 480 and `hours_taken` exceeds the PFL remaining; the system explicitly forbids that ordering.

Per-interval hours are rounded half up to one decimal place at the moment the interval is charged. The case-level `fmla_hours_charged` and `pfl_hours_charged` are running sums of those rounded per-interval values, incremented as each interval is recorded; they are never recomputed by re-rounding a raw underlying total. Reversing an interval — a compensating action HR may take within fourteen days of the interval's record date while the case remains `ACTIVE` — transitions the interval's `status` from `RECORDED` to `REVERSED`, subtracts the interval's `fmla_hours_charged` and `pfl_hours_charged` from the case totals, and, if the new cumulative `fmla_hours_charged` is below 480, flips `job_restoration_protected` back to true (the compensating invariant: the case's total FMLA charged equals the sum of `RECORDED` intervals' FMLA charges).

While the case is `ACTIVE`, `job_restoration_deadline` is recomputed on each interval; it is null whenever no protected leave is active. When HR completes the leave (an `ACTIVE` → `COMPLETED` transition requiring at least one `RECORDED` interval), the employee's `employment_status` returns to `ACTIVE`, and the case awaits the restoration decision: HR drives `COMPLETED` → `JOB_RESTORED` when `job_restoration_protected` is true and now is at or before `job_restoration_deadline`, clearing `job_restoration_deadline` on the way; otherwise HR drives `COMPLETED` → `JOB_FORFEITED`, also clearing `job_restoration_deadline`. Both `JOB_RESTORED` and `JOB_FORFEITED` are terminal.

`LeaveCase.status` ranges over `SUBMITTED`, `ELIGIBILITY_PENDING`, `CERTIFICATION_PENDING`, `APPROVED`, `DENIED`, `ACTIVE`, `COMPLETED`, `JOB_RESTORED`, and `JOB_FORFEITED`; `DENIED`, `JOB_RESTORED`, and `JOB_FORFEITED` are terminal. `LeaveInterval.status` ranges over `RECORDED` and `REVERSED`, with `REVERSED` terminal.

### 3.7. Benefit Continuation, the Premium Proration Formula, and Delinquency

When a leave case is approved and the employee is enrolled in the health plan, the server creates the first `BenefitContinuationLedger` row covering one calendar month from `requested_start_at`. On each row the server computes the prorated employer and employee shares of the monthly premium against the actual leave-business-days in the period, then exposes a running outstanding balance.

The proration formula is pinned in evaluation order. First, the server counts the business days (Monday through Friday) in the half-open interval from `period_start` to `period_end`; call this the period's business-day total. Second, the server counts the business days that lie in the intersection of the period and the union of all `RECORDED` `LeaveInterval` ranges on the case; call this the leave-business-day total. Third, the server divides the leave-business-day total by the period business-day total and rounds half up to four decimal places — this is the leave fraction, and the four-decimal-place rounding happens at this step only. Fourth, the server multiplies the employer's `monthly_premium_total_cents` by the employer's `employer_premium_share_pct` and by the leave fraction, rounding half up to whole cents to produce `employer_premium_share_cents`; then multiplies `monthly_premium_total_cents` by (one minus `employer_premium_share_pct`) and by the leave fraction, rounding half up to whole cents to produce `employee_premium_share_cents`. The order matters: the leave fraction is rounded to four decimal places before any multiplication, and the employer and employee shares are each rounded to whole cents after multiplication; the alternative ordering (multiply then sum then round) drifts by up to one cent per period and is explicitly forbidden. The row's `employee_owes_cents` is `employee_premium_share_cents` minus `payments_received_cents`.

The ledger row is recomputed monthly while the case is `ACTIVE`, and once more when the case completes to prorate the final partial month. Each row is keyed by the parent `employee_id` and `leave_case_id` and exposes the prorated `employer_premium_share_cents`, the prorated `employee_premium_share_cents`, the cumulative `payments_received_cents`, the running `employee_owes_cents`, and a `payment_status`. The status ranges over `PENDING`, `PARTIAL`, `PAID`, and `DELINQUENT`; `PAID` and `DELINQUENT` are terminal for the row.

An HR officer applies a payment to a ledger row by supplying `amount_cents`. The amount must be strictly greater than zero and at most the row's outstanding balance — `employee_premium_share_cents` minus `payments_received_cents`. A negative, zero, or over-balance amount is rejected with `ERR_INVALID_PAYMENT_AMOUNT`. When the applied amount is strictly less than the outstanding balance, the row moves from `PENDING` to `PARTIAL` (or remains `PARTIAL`); when the applied amount equals the outstanding balance exactly, the row moves to `PAID` and `employee_owes_cents` is set to zero. The cumulative `payments_received_cents` is bumped by the applied `amount_cents` and `employee_owes_cents` is recomputed on each application.

Delinquency is a clock-driven transition. When the server's logical clock advances past `period_end` plus thirty days and `employee_owes_cents` is strictly greater than zero, the row transitions from `PENDING` or `PARTIAL` to `DELINQUENT`. This transition is terminal for that ledger row. It also cascades: each newly-`DELINQUENT` row sets the corresponding `LeaveCase.job_restoration_protected` to false, because employer-paid coverage has lapsed for the period and statutory restoration protection lapses with it. The cascade may further unset `Employee.job_restoration_deadline` if the affected case's restoration window is now invalid. The clock-advance call returns the list of ledger row ids that flipped to `DELINQUENT` so tests can observe the cascade deterministically.

### 3.8. Test-Driving Capabilities

Two operations exist for deterministic test driving and are `PlatformAdmin`-exclusive. The first is a clock-advance capability that accepts `to_iso8601` and sets the server's logical clock to that instant; on success the response carries the new `current_utc` and the `delinquent_ledger_ids` array of every ledger row that flipped to `DELINQUENT` as a side effect (per §3.7). The second is a historic-interval seeding capability that creates a `LeaveInterval` directly with caller-supplied `fmla_hours_charged` and `pfl_hours_charged`, bypassing the standard waterfall calculation; the seeded values are added directly to the parent case's `fmla_hours_charged` and `pfl_hours_charged` running totals. This second capability is used by tests that need pre-existing FMLA hours in a prior rolling-12-month window to exercise quota-boundary behaviour.

## 4. Endpoint Definitions

The API is mounted under `/leave`. All POST endpoints that create a new resource respond with HTTP 201; all other successful operations respond with HTTP 200. List endpoints accept the pagination and filter query parameters described in §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/leave/employers` | Create an employer profile. | `PlatformAdmin` |
| GET | `/leave/employers/{id}` | Fetch an employer. | `PlatformAdmin`, `HRAdmin` |
| POST | `/leave/employees` | Create an employee under an employer. | `HRAdmin` |
| GET | `/leave/employees/{id}` | Fetch an employee. | `HRAdmin`, `Employee` |
| GET | `/leave/employees` | List employees, optionally filtered by `employer_id`. | `HRAdmin` |
| PATCH | `/leave/employees/{id}/health-enrollment` | Toggle `health_plan_enrolled` (OCC-guarded). | `HRAdmin` |
| POST | `/leave/employees/{id}/terminate` | Mark an employee `TERMINATED`. | `HRAdmin` |
| POST | `/leave/providers` | Register a healthcare provider. | `PlatformAdmin`, `HRAdmin` |
| GET | `/leave/providers/{id}` | Fetch a provider. | `PlatformAdmin`, `HRAdmin`, `HealthcareProvider` |
| POST | `/leave/cases` | Submit a new leave request. | `Employee`, `HRAdmin` |
| GET | `/leave/cases/{id}` | Fetch a leave case. | `HRAdmin`, `Employee` |
| GET | `/leave/cases` | List leave cases, filterable by `employee_id` and `status`. | `HRAdmin`, `Employee` |
| POST | `/leave/cases/{id}/evaluate-eligibility` | Run the eligibility threshold against snapshot fields. | `HRAdmin` |
| POST | `/leave/cases/{id}/approve` | Approve a case once its certification is `COMPLETE` (OCC-guarded). | `HRAdmin` |
| POST | `/leave/cases/{id}/deny` | Deny a case after a failed or missing certification. | `HRAdmin` |
| POST | `/leave/cases/{id}/complete` | Mark an `ACTIVE` case `COMPLETED`. | `HRAdmin` |
| POST | `/leave/cases/{id}/restore` | Restore the employee's job after a protected, completed leave. | `HRAdmin` |
| POST | `/leave/cases/{id}/forfeit-restoration` | Mark restoration forfeited when protection has lapsed or the deadline has passed. | `HRAdmin` |
| POST | `/leave/cases/{id}/request-recertification` | Open a new `PENDING` certification round on an `APPROVED` or `ACTIVE` case. | `HRAdmin` |
| POST | `/leave/certifications` | Submit a medical certification draft. | `HealthcareProvider`, `HRAdmin` |
| GET | `/leave/certifications/{id}` | Fetch a certification record. | `HRAdmin`, `Employee`, `HealthcareProvider` |
| GET | `/leave/certifications` | List certifications, filterable by `leave_case_id` or `provider_id`. | `HRAdmin`, `HealthcareProvider` |
| POST | `/leave/certifications/{id}/receive` | Mark a certification `RECEIVED`. | `HRAdmin` |
| POST | `/leave/certifications/{id}/mark-complete` | Mark a `RECEIVED` certification `COMPLETE`. | `HRAdmin` |
| POST | `/leave/certifications/{id}/mark-insufficient` | Mark a `RECEIVED` certification `INSUFFICIENT`. | `HRAdmin` |
| POST | `/leave/intervals` | Record a taken leave interval. | `HRAdmin` |
| GET | `/leave/intervals/{id}` | Fetch a leave interval. | `HRAdmin`, `Employee` |
| GET | `/leave/intervals` | List leave intervals, filterable by `leave_case_id`. | `HRAdmin`, `Employee` |
| POST | `/leave/intervals/{id}/reverse` | Reverse a recorded interval (compensating action). | `HRAdmin` |
| GET | `/leave/benefit-ledgers/{id}` | Fetch a benefit-continuation ledger row. | `HRAdmin`, `Employee` |
| GET | `/leave/benefit-ledgers` | List ledger rows, filterable by `employee_id` and `leave_case_id`. | `HRAdmin`, `Employee` |
| POST | `/leave/benefit-ledgers/{id}/apply-payment` | Apply an employee payment (`amount_cents`) to the ledger row. | `HRAdmin` |
| GET | `/leave/notices/{id}` | Fetch a notice. | `HRAdmin`, `Employee` |
| GET | `/leave/notices` | List notices, filterable by `leave_case_id` and `notice_type`. | `HRAdmin`, `Employee` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; reports `delinquent_ledger_ids` cascaded. | `PlatformAdmin` |
| POST | `/_intervals/seed-historic` | Seed a historic `LeaveInterval` with caller-supplied charges. | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EMPLOYEE_TERMINATED` | 409 |
| `ERR_CERTIFICATION_INCOMPLETE` | 409 |
| `ERR_INTERMITTENT_CERT_REQUIRED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INELIGIBLE` | 422 |
| `ERR_INTERVAL_OVERLAP` | 409 |
| `ERR_INTERMITTENT_FREQUENCY_EXCEEDED` | 409 |
| `ERR_INTERMITTENT_HOURS_EXCEEDED` | 422 |
| `ERR_RECERT_TOO_SOON` | 409 |
| `ERR_INVALID_PAYMENT_AMOUNT` | 422 |
