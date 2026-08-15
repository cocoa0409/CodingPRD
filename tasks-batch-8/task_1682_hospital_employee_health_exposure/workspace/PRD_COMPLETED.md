# Hospital Employee Health API — Product Requirements Document

## 1. Introduction

A hospital's employee health office sits at an uncomfortable intersection: it must protect patients from communicable disease carried by staff, protect staff from bloodborne pathogens and workplace injury, and satisfy regulators who audit every missed TB screening, every lapsed fit test, and every late post-exposure prophylaxis dose. Today these obligations are tracked in spreadsheets and paper files, which means the office learns about an overdue annual requirement only after a surveyor does, and a needlestick at 2 a.m. relies on whoever answers the phone remembering the seventy-two-hour prophylaxis window. This document specifies an API that makes compliance state machine-driven and time-aware: the system itself detects lateness, applies compliance holds, and cascades the consequences into each employee's work status without waiting for a human to notice.

The API covers the full portfolio of the employee health office. Pre-placement screening verifies physical examination, tuberculosis baseline, and immunity titers before a new hire may work. An annual requirement cycle drives recurring TB screening and respirator fit testing, with overdue cycles automatically producing compliance holds that suspend the employee until a compliance officer releases them. Bloodborne-pathogen exposure intake classifies risk, manages source-patient testing consent under segregation of duties, times post-exposure prophylaxis against a hard window, and schedules serology follow-ups whose positive results convert a case into seroconversion with automatic work exclusion. Work restrictions and return-to-work clearances govern what an employee may do while recovering. Communicable-disease events among staff drive contact tracing with disease-specific monitoring windows. Injury reports link exposures to workers' compensation claims. Vaccination campaigns track administration, declination, exemption, and delinquency across the workforce.

Two design commitments pervade the system. First, all time-based behavior runs against a logical clock that operators advance explicitly; nothing depends on wall-clock time, which makes every due date, window, and automatic transition deterministic and auditable. Second, authority is segregated: the nurse who records an exposure may not also record the source patient's consent, only a physician clears a screening or a return to work, only a compliance officer releases a hold or runs a vaccination campaign, and an employee's consent-sensitive decisions — declining prophylaxis, declining a vaccination — belong to that employee alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `EmployeeHealthNurse`, `EmployeeHealthPhysician`, `ComplianceOfficer`, `SafetyOfficer`, and `StaffEmployee`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_MISSING_AUTH_CONTEXT`. A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `StaffEmployee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's employee foreign key — or, for a contact-tracing row, its `contact_employee_id` — to `X-User-ID`. A `StaffEmployee` therefore sees only their own rows on list endpoints, may read only their own employee record, and is rejected with `ERR_OWNERSHIP_REQUIRED` when acting on or reading another employee's records. For the employee record itself the path identifier is directly comparable to `X-User-ID`, so this ownership rejection precedes existence validation; for every other employee-owned resource the resource is loaded first, so a `StaffEmployee` targeting a nonexistent identifier receives `ERR_NOT_FOUND`, and `ERR_OWNERSHIP_REQUIRED` surfaces only when the resource exists and belongs to another employee. When `X-User-Role` is `EmployeeHealthNurse`, `EmployeeHealthPhysician`, `ComplianceOfficer`, or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow calls for an audit trail — for example as `recorded_by_user_id` on an exposure case, `decided_by_user_id` on a screening decision or a clearance decision, `requested_by_user_id` on a clearance request, `consent_recorded_by_user_id` on a source-testing consent, or `released_by_user_id` on a released hold — but never compares it to any entity's `id`.

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
- Requests to undefined routes, and requests using an unsupported method on a defined route, are rejected with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Values that are missing, unparsable, or out of range are coerced rather than rejected: an unusable `limit` falls back to 10 before being clamped into [1, 100], and an unusable `offset` falls back to 0 before being clamped to a non-negative value. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Evaluation

The system never reads wall-clock time. All "now" semantics resolve against a logical clock whose startup default is exactly 2026-08-01T00:00:00Z. Only a `ComplianceOfficer` may advance it, through an administrative clock-setting capability that accepts a `to_iso8601` instant; the supplied instant must be strictly after the current logical time, and a regression or equality is rejected with `ERR_CLOCK_REGRESSION`. The clock-setting response reports the resulting `current_utc` and a `transitions_applied` count of automatic transitions the advancement triggered. Each automatic state change of an existing resource — including employee status cascades such as `ACTIVE → SUSPENDED` — counts once toward `transitions_applied`; the automatic creation of a resource (for example a compliance hold) is not itself counted as a transition.

Each clock advancement sweeps every time-driven automation described in this document: annual cycles whose due dates have passed turn `OVERDUE` and cascade compliance holds onto their employees; recommended prophylaxis regimens whose window deadline has passed flip to `WINDOW_EXPIRED`; serology follow-ups open into `DUE` as their windows arrive and lapse into `OVERDUE` once their windows close; monitored contacts whose monitoring period has fully elapsed without reported symptoms clear automatically; and work restrictions whose end date has been reached expire. All timestamp comparisons in these sweeps are evaluated at second precision.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations driven by automatic cascades.

The `TiterResult` resource is the sole exception: it is an append-only laboratory record carrying only `id` and `created_at`. It has no `updated_at` and no `version`, and no endpoint modifies it after creation.

### 2.6. Nested Resource Retrieval and Existence

Requests that target nested resources — for example, opening a pre-placement screening under a specific employee — validate path identifiers sequentially from left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not resolve to an existing resource, before any later identifier or any business rule is considered. Creation and modification under a parent therefore fail early when the parent does not exist, and a missing child under an existing parent surfaces its own not-found rejection. Resource identifiers carried in the request body are validated the same way: a `screening_id` on a titer result, an `exposure_case_id` on a work restriction or injury report, an `index_employee_id` on a communicable event, or a `contact_employee_id` on a contact enrollment that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND`.

### 2.7. Optimistic Concurrency Control

Exactly one write operation participates in optimistic concurrency control: opening a pre-placement screening for an employee. That request must carry `expected_employee_version`, holding the employee `version` the client last observed. A missing or non-integer `expected_employee_version` is rejected with `ERR_INVALID_REQUEST`, surfaced at the same point as the stale-version check. If the employee's current `version` has advanced since that observation, the request is rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412), and this stale-version rejection is evaluated before any business check on the request. The guard exists because opening a screening supersedes — voids — any screening already in progress for the employee; a writer holding a stale employee version must not be allowed to void a screening it never observed. No other endpoint accepts a version field; requests to every other endpoint do not carry one.

### 2.8. Validation Discipline and Priority Order

Every endpoint applies its checks in a single pinned order, and a failure surfaces the error of the earliest failing category rather than a later one. The order is:

1. **Authentication context** — the headers `X-User-ID` and `X-User-Role` are present and the role is one of the five declared roles (`ERR_MISSING_AUTH_CONTEXT`, HTTP 400).
2. **Role authorization** — the acting role appears in the endpoint's authorized role list (`ERR_FORBIDDEN_ROLE`, HTTP 403).
3. **Self-scope and segregation of duties** — a `StaffEmployee` may act only on records belonging to their own employee id (`ERR_OWNERSHIP_REQUIRED`, HTTP 403), and the operator recording a source-patient consent outcome must differ from the operator who recorded the exposure intake (`ERR_SOD_SOURCE_CONSENT`, HTTP 403).
4. **Path existence** — path identifiers resolve, validated left to right (`ERR_NOT_FOUND`, HTTP 404).
5. **Stale employee version** — on screening creation, `expected_employee_version` matches the employee's current `version` (`ERR_STALE_EMPLOYEE_VERSION`, HTTP 412), before any business check.
6. **State legality** — the target resource sits in a valid from-state for the requested transition or action; this family includes `ERR_INVALID_STATE`, `ERR_CYCLE_ALREADY_OPEN`, `ERR_HOLD_NOT_ACTIVE`, `ERR_UNDERLYING_REQUIREMENT_UNMET`, `ERR_CASE_CLOSE_BLOCKED`, `ERR_SOURCE_TESTING_UNRESOLVED`, `ERR_EVENT_CLOSE_BLOCKED`, `ERR_FOLLOWUP_NOT_DUE`, `ERR_RESTRICTION_NOT_ACTIVE`, `ERR_NO_SYMPTOMS_REPORTED`, `ERR_CAMPAIGN_WINDOW_NOT_ENDED`, and `ERR_PARTICIPATION_NOT_PENDING` (all HTTP 409).
7. **Safety gates** — clinical safety rules such as the prophylaxis window (`ERR_PEP_WINDOW_EXPIRED`), the prophylaxis course length (`ERR_PEP_COURSE_INCOMPLETE`), screening component completeness (`ERR_COMPONENT_INCOMPLETE`), immunity establishment (`ERR_IMMUNITY_NOT_ESTABLISHED`), the fit-test requirement gate (`ERR_FIT_TEST_NOT_REQUIRED`), and the active-employee posture gate (`ERR_EMPLOYEE_NOT_ACTIVE`) (all HTTP 422).
8. **Referential coherence** — cross-references belong to the same employee (`ERR_SCREENING_EMPLOYEE_MISMATCH`, `ERR_CASE_EMPLOYEE_MISMATCH`, HTTP 422), a contact is not the event's index case (`ERR_SELF_CONTACT`, HTTP 422), and conditional presence such as `source_patient_ref` agrees with `source_known` (`ERR_INVALID_REQUEST`, HTTP 400).
9. **Temporal ranges** — timestamps are not in the future and fall inside their required windows (`ERR_FUTURE_RESULT_DATE`, `ERR_COMPLETION_OUT_OF_RANGE`, `ERR_ADMINISTER_OUTSIDE_WINDOW`, `ERR_CONTACT_DATE_OUT_OF_RANGE`, `ERR_CLOCK_REGRESSION`, HTTP 422).
10. **Uniqueness and overlap** — duplicate references and conflicting intervals (`ERR_WORK_RESTRICTION_OVERLAP`, `ERR_CAMPAIGN_WINDOW_OVERLAP`, `ERR_DUPLICATE_CONTACT`, `ERR_DUPLICATE_EMPLOYEE_REF`, all HTTP 409).
11. **Field shape** — required fields present, enum values among declared members, interval ends no earlier than starts, and justification lengths (`ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`, `ERR_INSUFFICIENT_JUSTIFICATION`, `ERR_DECLINATION_REASON_REQUIRED`, all HTTP 400).

On endpoints that multiplex several transitions behind a request-field selector (`to_state`, `action`, or `outcome`), the selector is decoded as follows. Where the selected transition is restricted to a subset of the endpoint's roles — the prophylaxis, serology follow-up, contact, and campaign-participation transition endpoints — the per-transition role rejection is decidable from the selector alone and is evaluated with step 2, before path existence. Path existence (step 4) always precedes selector decoding, and an unrecognized selector is then rejected with `ERR_INVALID_ENUM`. Selector decoding otherwise precedes state legality (step 6), with two exceptions: the exposure-case, communicable-event, and vaccination-campaign transition endpoints apply their terminal-state guard first — a `CLOSED` case, event, or campaign, or a `SEROCONVERTED` case, rejects any advance with `ERR_INVALID_STATE` regardless of the submitted selector — and the screening and clearance decision endpoints apply their from-state checks before `outcome` is validated.

### 2.9. Precision, Rounding, and Calendar Arithmetic

Numeric rules in this system are deliberately inhomogeneous, and each rule states its own discipline. Immunity threshold comparisons operate on the raw assay `numeric_value` exactly as supplied, with no rounding of any kind. Campaign coverage percentages are expressed with exactly two decimal places using round-half-up, and the rounding is applied twice — once to each per-department rate and once to the final mean — never to an aggregate-first alternative. Annual rolling-anniversary due dates use calendar-month arithmetic that preserves the day of month; every other window and schedule in the system uses day arithmetic on timestamps evaluated at second precision. Timestamps supplied by clients are interpreted as UTC when they carry no explicit offset, and every supplied timestamp is truncated to second precision on receipt, ahead of storage and of every comparison.

## 3. Business Logic & Workflows

### 3.1. Hiring Into the Health System: Employee Registration and Compliance Posture

An `EmployeeHealthNurse` registers each new hire with the health office by supplying an `employee_ref` — the hospital's unique HR badge reference, rejected with `ERR_DUPLICATE_EMPLOYEE_REF` when it collides with an already-registered reference — together with `full_name`, `job_category` (one of `NURSE`, `PHYSICIAN`, `TECH`, `HOUSEKEEPING`, or `OTHER`), a `department` code such as ICU, ED, or LAB, the `hire_date`, and a `requires_respirator` flag declaring whether the job duties require respirator fit testing. The `hire_date` matters beyond record-keeping: it anchors the employee's first rolling-anniversary compliance cycle (see §3.3). No recency bound applies to `hire_date`. A newly registered employee begins with `status` `PREPLACEMENT`, a `compliance_posture` of `CLEAR`, and both `active_hold_count` and `open_restriction_count` at zero.

The `compliance_posture` field is always derived, never set directly, and the derivation follows a pinned order in which holds dominate restrictions. When the employee's `active_hold_count` is above zero, the posture is `ON_HOLD`. Otherwise, when any `ACTIVE` work restriction of type `FULL_EXCLUSION` exists for the employee, the posture is `WORK_EXCLUDED`. Otherwise, when `open_restriction_count` is above zero, the posture is `RESTRICTED_DUTY`. Failing all three, the posture is `CLEAR`. Every event that changes hold counts, restriction counts, or the type or status of the employee's restrictions recomputes the posture immediately.

The employee `status` field derives on the hold axis only: the employee is `SUSPENDED` exactly while `active_hold_count` is above zero, and returns to `ACTIVE` when the count falls back to zero. This derivation never moves an employee out of `PREPLACEMENT` — only a cleared pre-placement screening does that (see §3.2). Whenever the employee record mutates through these transitions, its `version` increments and its `updated_at` refreshes.

Listing and reading employees is available to all five roles, with two self-scope carve-outs for `StaffEmployee`: their list view contains only their own row, and reading another employee's record is rejected with `ERR_OWNERSHIP_REQUIRED`. The list endpoint accepts the optional filters `status`, `compliance_posture`, and `department`. Throughout the system, list endpoints for employee-owned resources — screenings, titers, cycles, holds, exposure cases, restrictions, and injury reports alike — accept the owning employee's `employee_id` as a filter alongside their resource-specific filters.

### 3.2. Pre-Placement Screening and Immunity Verification

Before a `PREPLACEMENT` employee may become `ACTIVE`, an `EmployeeHealthPhysician` must clear a pre-placement screening. An `EmployeeHealthNurse` opens the screening under the employee's record; the request carries `expected_employee_version` and is governed by the optimistic-concurrency rule of §2.7. Opening a screening is a create-with-supersede: any screening already `IN_PROGRESS` for the same employee automatically becomes `VOID`, the superseded screening's linked titer results remain immutable and still count toward immunity interpretation, and the employee's `version` increments. The new screening begins `IN_PROGRESS`.

A screening collects up to three components, each marked complete by a nurse through a payload naming the `component` — `PHYSICAL`, `TB_BASELINE`, or `MED_EVAL` — and the `completed_at` timestamp, which must not lie in the future (`ERR_COMPLETION_OUT_OF_RANGE`). Each completion stamps the corresponding field: `physical_completed_at`, `tb_baseline_completed_at`, or `med_eval_completed_at`, each of which remains null until its component is completed. Components may be completed only while the screening is `IN_PROGRESS` — completion against a screening in any other status is rejected with `ERR_INVALID_STATE` — and each component may be completed only once; repeating one is likewise rejected with `ERR_INVALID_STATE`. The medical evaluation component is required only for employees whose `requires_respirator` is true.

Immunity is evidenced by `TiterResult` records, which a nurse records under the employee with the `disease` (one of `HEP_B`, `MEASLES`, `MUMPS`, `RUBELLA`, or `VARICELLA`), the `assay_type` (`QUANTITATIVE` or `QUALITATIVE`), and the lab's `resulted_at` timestamp, which must not be after the current logical clock time (`ERR_FUTURE_RESULT_DATE`). A quantitative assay requires `numeric_value`; a qualitative assay requires `qualitative_result` (one of `REACTIVE`, `NON_REACTIVE`, or `EQUIVOCAL`). A titer may optionally carry a `screening_id` linking it to the pre-placement screening it satisfies; when present, that screening must belong to the same employee, or the record is rejected with `ERR_SCREENING_EMPLOYEE_MISMATCH`.

Interpretation happens at record time and lands on the computed `immunity_status`. For a `QUANTITATIVE` assay, the supplied `numeric_value` is compared against a per-disease threshold — 10.0 for `HEP_B`, 1.0 for `MEASLES`, 1.0 for `MUMPS`, 10.0 for `RUBELLA`, and 1.0 for `VARICELLA` — on the raw value with no rounding: a value at or above the threshold yields `IMMUNE`, and a value below it yields `NON_IMMUNE`; the boundary is inclusive, so a value exactly equal to the threshold is `IMMUNE`. For a `QUALITATIVE` assay, the label alone decides: `REACTIVE` becomes `IMMUNE`, `NON_REACTIVE` becomes `NON_IMMUNE`, and `EQUIVOCAL` becomes `EQUIVOCAL`; the `numeric_value` is ignored for qualitative assays even when supplied, so the same numeric data can produce opposite outcomes under the two assay types. Symmetrically, a `qualitative_result` supplied on a quantitative assay is discarded and stored as null.

The physician's clearance decision submits an `outcome` of `CLEARED` or `FAILED`. A `CLEARED` decision requires the screening to be `IN_PROGRESS` (`ERR_INVALID_STATE`), requires `physical_completed_at` and `tb_baseline_completed_at` to be set — plus `med_eval_completed_at` when the employee's `requires_respirator` is true — with any missing component rejected as `ERR_COMPONENT_INCOMPLETE`, and requires immunity to be established for each of the two required diseases, `HEP_B` and `VARICELLA`: the latest titer for the employee and disease — chosen as the row with the greatest `resulted_at`, with ties broken in favor of the row with the greatest `created_at`, and any remaining tie broken in favor of the row recorded last — must have `immunity_status` `IMMUNE`, otherwise the decision is rejected with `ERR_IMMUNITY_NOT_ESTABLISHED`. A successful decision stamps `decided_by_user_id` and `decided_at`, both of which remain null while the screening is `IN_PROGRESS`, and a `CLEARED` decision transitions the employee from `PREPLACEMENT` to `ACTIVE` when the employee is still in `PREPLACEMENT`. A `FAILED` decision also stamps `decided_by_user_id` and `decided_at` but leaves the employee in `PREPLACEMENT`; both `CLEARED` and `FAILED` are terminal, as is the `VOID` state reached through supersession.

### 3.3. The Annual Requirement Cycle and Compliance Holds

Once an employee is `ACTIVE`, a `ComplianceOfficer` opens each year's requirement cycle by supplying the `cycle_year` and a `cycle_mode` of `CALENDAR_YEAR` or `ROLLING_ANNIVERSARY`. The employee must be `ACTIVE` at cycle creation (`ERR_EMPLOYEE_NOT_ACTIVE`), and an employee may have at most one cycle in `OPEN` or `OVERDUE` at a time (`ERR_CYCLE_ALREADY_OPEN`). The cycle tracks two obligations: a TB screening, recorded in `tb_completed_at`, and — only when the employee's `requires_respirator` is true — a respirator fit test, recorded in `fit_test_completed_at`.

Due dates are computed at creation. Under `CALENDAR_YEAR`, `tb_due_date` is pinned to the end of the cycle year — December 31 of `cycle_year` at 23:59:59 UTC — regardless of completion history. Under `ROLLING_ANNIVERSARY`, the system finds an anchor: the greatest `tb_completed_at` among the employee's other cycles whose `status` is `SATISFIED`, or the employee's `hire_date` when no satisfied prior cycle exists; `tb_due_date` is then exactly twelve calendar months after that anchor, preserving the day of month. An employee hired on March 10, 2025 with no satisfied prior cycle therefore falls due on March 10, 2026 — not at the end of the calendar year. The `fit_test_due_date` mirrors `tb_due_date` when the employee requires a respirator and is null otherwise.

A nurse records completions with a `requirement_type` of `TB_SCREENING` or `FIT_TEST` and a `completed_at` timestamp that must not be in the future and must not precede the cycle's creation (`ERR_COMPLETION_OUT_OF_RANGE`). Each requirement can be completed once per cycle; a repeat completion is rejected with `ERR_INVALID_STATE`. Recording a `FIT_TEST` completion for an employee whose `requires_respirator` is false is rejected with `ERR_FIT_TEST_NOT_REQUIRED`. The cycle is satisfied when `tb_completed_at` is set and, for respirator-requiring employees, `fit_test_completed_at` is also set; employees without the respirator requirement satisfy the cycle on TB completion alone. Satisfaction moves the cycle from `OPEN` to `SATISFIED`, or from `OVERDUE` to `SATISFIED` — late completion is allowed — and is re-evaluated after every completion call and every clock advancement.

Lateness is detected on the clock, with a strict boundary: a cycle becomes `OVERDUE` only when the current logical time is strictly later than `tb_due_date` while `tb_completed_at` remains unset, or — for respirator-requiring employees — strictly later than `fit_test_due_date` while `fit_test_completed_at` remains unset; on the due date itself the cycle stays `OPEN`. The overdue transition auto-creates a `ComplianceHold` in `ACTIVE` status for each missing obligation, with `reason` `TB_OVERDUE` or `FIT_TEST_OVERDUE` respectively, the hold's `cycle_id` pointing at the delinquent cycle, and `applied_at` stamped from the logical clock. Each new active hold increments the employee's `active_hold_count` by one; when the count rises from zero and the employee is `ACTIVE`, the employee automatically transitions `ACTIVE → SUSPENDED` and the posture recomputes to `ON_HOLD`, with the employee's `version` incremented and `updated_at` refreshed.

A hold's linkage fields are reason-dependent: `cycle_id` is set only when the `reason` is `TB_OVERDUE` or `FIT_TEST_OVERDUE`, and `participation_id` is set only when the `reason` is `CAMPAIGN_DELINQUENT`; in each case the other field is null. While a hold is `ACTIVE`, its `released_at` and `released_by_user_id` remain null.

Holds are never released by the passage of time or by satisfaction alone. A satisfied cycle makes its cycle-linked active holds releasable, but release remains an explicit `ComplianceOfficer` action. Release requires the hold to be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`); for holds with `reason` `TB_OVERDUE` or `FIT_TEST_OVERDUE` the linked cycle must be `SATISFIED`, and for holds with `reason` `CAMPAIGN_DELINQUENT` the linked `participation_id` must reference a participation in `ADMINISTERED`, `DECLINED`, or `EXEMPTED` — an unmet underlying requirement is rejected with `ERR_UNDERLYING_REQUIREMENT_UNMET`. A successful release transitions the hold `ACTIVE → RELEASED` (the hold's terminal state), stamps `released_at` and `released_by_user_id`, decrements the employee's `active_hold_count` by one, and recomputes the posture; when the count reaches zero and the employee is `SUSPENDED`, the employee automatically returns `SUSPENDED → ACTIVE`.

### 3.4. Exposure Intake, Risk Classification, and Source-Patient Testing

When a staff member suffers a bloodborne-pathogen exposure, an `EmployeeHealthNurse` performs intake under the employee's record, supplying the `exposure_type` (`PERCUTANEOUS`, `MUCOUS_MEMBRANE`, `SKIN_CONTACT`, or `BITE`), the `exposure_datetime` — which must not be after the current logical clock time (`ERR_COMPLETION_OUT_OF_RANGE`) — a `source_known` flag, and the `body_fluid` classification (`BLOOD`, `OTHER_POTENTIALLY_INFECTIOUS`, or `NON_INFECTIOUS`). When `source_known` is true, `source_patient_ref` is required; when false, `source_patient_ref` must be null; a violation of either direction is rejected with `ERR_INVALID_REQUEST`. Intake stamps `reported_at` from the logical clock and records the intake nurse's identity in `recorded_by_user_id` — an anchor later used for segregation of duties. Until source results are recorded, `hiv_result`, `hbv_result`, and `hcv_result` carry the sentinel value `PENDING` and `source_resulted_at` remains null.

The case carries two parallel status dimensions that evolve independently. The clinical dimension, `case_status`, begins at `REPORTED`. The source-testing dimension, `source_test_status`, begins at `CONSENT_PENDING` when the source patient is known and at `NOT_REQUIRED` otherwise.

Risk classification is computed at intake into `risk_classification`, and identical exposure mechanics classify differently depending on whether the source is known. An exposure whose `body_fluid` is `NON_INFECTIOUS` is always `LOW`. Otherwise: a `PERCUTANEOUS` exposure to `BLOOD` with a known source is `HIGH`; the same exposure with an unknown source is `MEDIUM`; a `MUCOUS_MEMBRANE` or `BITE` exposure to `BLOOD` is `MEDIUM`; a `PERCUTANEOUS` exposure to `OTHER_POTENTIALLY_INFECTIOUS` is `MEDIUM`; a `MUCOUS_MEMBRANE` or `BITE` exposure to `OTHER_POTENTIALLY_INFECTIOUS` is `LOW`; and any `SKIN_CONTACT` exposure, regardless of fluid, is `LOW`. When the classification is `HIGH` or `MEDIUM`, the computed `pep_required` flag is true and intake auto-creates one prophylaxis regimen in `RECOMMENDED` status with `medication` defaulting to `HIV_3DRUG`, `recommended_at` stamped from the clock, and a `window_deadline` exactly seventy-two hours after `exposure_datetime`. Regardless of classification, intake always auto-creates one serology follow-up at the `BASELINE` milestone in `SCHEDULED` status (see §3.5).

The physician advances the clinical dimension by submitting a `to_state`. From `REPORTED`, the case moves to `EVALUATION`; any other from-state is rejected with `ERR_INVALID_STATE`. From `EVALUATION` to `MANAGEMENT` there is an additional gate: `source_test_status` must be one of `NOT_REQUIRED`, `RESULTED`, `CONSENT_DECLINED`, or `WAIVED_UNABLE`, so that source testing is resolved before management begins — otherwise the advance is rejected with `ERR_SOURCE_TESTING_UNRESOLVED`. From `MANAGEMENT` to `CLOSED`, three closures must hold: no serology follow-up of the case remains in `SCHEDULED`, `DUE`, or `OVERDUE`; every prophylaxis regimen of the case has reached `COMPLETED`, `DECLINED`, or `WINDOW_EXPIRED`; and no work restriction linked to the case remains `ACTIVE`. Any failure is rejected with `ERR_CASE_CLOSE_BLOCKED`. `CLOSED` is terminal, as is the `SEROCONVERTED` state reached through the cascade of §3.5: a case in either state rejects any further clinical advance with `ERR_INVALID_STATE`, regardless of the submitted `to_state`. An unrecognized `to_state` is otherwise rejected with `ERR_INVALID_ENUM`.

The source-testing dimension is driven by a nurse submitting an `action` of `RECORD_CONSENT` or `RECORD_RESULT`. Consent recording moves `CONSENT_PENDING` to `CONSENT_GRANTED`, `CONSENT_DECLINED`, or `WAIVED_UNABLE` according to the submitted `outcome`, stamps `consent_recorded_by_user_id` (which remains null until a consent outcome is recorded), and enforces segregation of duties: the acting nurse's `X-User-ID` must differ from the case's `recorded_by_user_id`, so the intake nurse can never record the source patient's consent on their own case (`ERR_SOD_SOURCE_CONSENT`). Result recording is permitted only from `CONSENT_GRANTED` (otherwise `ERR_INVALID_STATE`) and requires each of `hiv_result`, `hbv_result`, and `hcv_result` to be one of `NEGATIVE`, `POSITIVE`, or `INDETERMINATE` (`ERR_INVALID_ENUM`), with `source_resulted_at` no later than the current logical time (`ERR_FUTURE_RESULT_DATE`). When the recorded `hiv_result` is `POSITIVE`, `pep_required` becomes true, and if no prophylaxis regimen yet exists for the case one is auto-created in `RECOMMENDED` status with its `window_deadline` recomputed from `exposure_datetime` — a deadline that may already lie in the past, in which case the regimen will flip to `WINDOW_EXPIRED` at the next clock advancement.

### 3.5. Post-Exposure Prophylaxis and the Serology Follow-Up Program

A prophylaxis regimen begins `RECOMMENDED`, with its `window_deadline` set exactly seventy-two hours after the parent case's `exposure_datetime`; `started_at` remains null until the regimen is started. A physician starts the regimen by submitting `to_state` `STARTED` with the first-dose `started_at`. The start may optionally carry a `medication`, one of the three declared values, which then replaces the intake default on the regimen. Starting is eligible only while the current logical time is no later than the window deadline — the boundary is inclusive, so starting exactly at the deadline succeeds, and any later attempt is rejected with `ERR_PEP_WINDOW_EXPIRED`. The `started_at` itself must be no earlier than the exposure and no later than the current logical time (`ERR_COMPLETION_OUT_OF_RANGE`). Two automatic creations accompany a start: serology follow-ups for the `WEEK_6`, `WEEK_12`, and `MONTH_6` milestones appear in `SCHEDULED` status, and an injury report is filed automatically with `origin` `PEP_LINKAGE`, `injury_type` `NEEDLESTICK`, `injury_datetime` taken from the case's `exposure_datetime`, status `FILED`, and the case linked — the workers' compensation linkage described further in §3.8. A regimen's `medication` is one of `HIV_3DRUG`, `HBV_HBIG`, or `HBV_VACCINE_SERIES`.

Completion requires a full course: the physician's transition to `COMPLETED` is permitted only from `STARTED`, and is rejected with `ERR_PEP_COURSE_INCOMPLETE` unless the current logical time has reached or passed the instant twenty-eight days after `started_at` — again an inclusive boundary. Declination, by contrast, belongs to the patient: only the exposed `StaffEmployee` themself may move a `RECOMMENDED` regimen to `DECLINED`, with the acting `X-User-ID` equal to the case's employee id (`ERR_OWNERSHIP_REQUIRED`). If the clock advances strictly past the `window_deadline` while the regimen is still `RECOMMENDED`, the regimen automatically becomes `WINDOW_EXPIRED`. Any regimen transition requested from a status other than the valid from-state — starting a regimen that is not `RECOMMENDED`, completing one that is not `STARTED`, declining one that is not `RECOMMENDED` — is rejected with `ERR_INVALID_STATE`. `COMPLETED`, `DECLINED`, and `WINDOW_EXPIRED` are terminal.

The serology program follows a fixed schedule anchored to the exposure, with each follow-up's `milestone` drawn from `BASELINE`, `WEEK_6`, `WEEK_12`, and `MONTH_6`. The `BASELINE` milestone is scheduled at the `exposure_datetime` itself; `WEEK_6` is scheduled forty-two days after the exposure, `WEEK_12` at eighty-four days, and `MONTH_6` at one hundred eighty-three days — each follow-up's `scheduled_date`. Every follow-up carries a window: `window_open` is seven days before its `scheduled_date` (for `BASELINE`, the `window_open` is the `exposure_datetime`), and `window_close` is twenty-eight days after its `scheduled_date`. As the clock advances, a `SCHEDULED` follow-up becomes `DUE` once the current time reaches its `window_open` — the boundary is inclusive — and a `DUE` follow-up becomes `OVERDUE` only once the current time is strictly later than its `window_close`. When a single advancement lands past both boundaries, the follow-up passes through `DUE` to `OVERDUE` within that one sweep, each step counting as its own transition. Until resulted, a follow-up's `result` field carries the sentinel `PENDING` and its `resulted_at` remains null.

A nurse results a follow-up by submitting `to_state` `RESULTED` with a `result` of `NEGATIVE`, `POSITIVE`, or `INDETERMINATE` and a `resulted_at` no earlier than the case's `exposure_datetime` and no later than the current logical time (`ERR_COMPLETION_OUT_OF_RANGE`). Resulting requires the follow-up to be `DUE` or `OVERDUE`; attempting it from `SCHEDULED` — or from a terminal state — is rejected with `ERR_FOLLOWUP_NOT_DUE`. A physician may instead waive a follow-up from `DUE` or `OVERDUE` by submitting `to_state` `WAIVED` with a `reason` of at least ten characters (`ERR_INSUFFICIENT_JUSTIFICATION`). `RESULTED` and `WAIVED` are terminal.

A `POSITIVE` result on any milestone other than `BASELINE` triggers the seroconversion cascade: the parent case transitions automatically from `REPORTED`, `EVALUATION`, or `MANAGEMENT` to `SEROCONVERTED`; the system auto-creates a work restriction of type `FULL_EXCLUSION` for the employee with `start_date` set to the follow-up's `resulted_at`, no `end_date` (open-ended), and `origin` `SEROCONVERSION`; the employee's `open_restriction_count` increments by one; and the posture recomputes, yielding `WORK_EXCLUDED` unless a hold already places the employee `ON_HOLD`. A positive `BASELINE` result carries no such cascade — the conversion logic applies only to the post-baseline milestones.

### 3.6. Work Restrictions and Return-to-Work Clearance

A physician may impose a work restriction on an employee at any time, supplying a `restriction_type` of `NO_PATIENT_CONTACT`, `NO_PROCEDURES`, `MODIFIED_DUTY`, or `FULL_EXCLUSION`, a `start_date`, and an optional `end_date`; a null `end_date` makes the restriction open-ended, treated as extending without bound. Neither `start_date` nor `end_date` carries a recency bound; both may lie in the future. An optional `exposure_case_id` may link the restriction to the exposure that caused it; when present, the case must belong to the same employee (`ERR_CASE_EMPLOYEE_MISMATCH`). Restrictions occupy a half-open interval that includes the start and excludes the end: a new `ACTIVE` restriction whose interval intersects another `ACTIVE` restriction of the same employee is rejected with `ERR_WORK_RESTRICTION_OVERLAP`, while adjacency — one restriction's end exactly meeting another's start — is permitted because the end is exclusive. The overlap rejection applies only to physician-imposed creation; the automatic restrictions of §3.5 and §3.7 are created without it. Physician-imposed restrictions carry `origin` `MANUAL`; the `SEROCONVERSION` and `CONTACT_CONVERSION` origins belong to the automatic restrictions of §3.5 and §3.7. Creating a restriction increments the employee's `open_restriction_count` by one and recomputes the posture. When a restriction has an `end_date` and the clock reaches or passes it, the restriction automatically becomes `EXPIRED`, decrementing `open_restriction_count` and recomputing the posture.

A restricted employee returns to duty through a clearance. A nurse requests a `ReturnToWorkClearance` against an `ACTIVE` restriction — requesting against a restriction in any other status is rejected with `ERR_RESTRICTION_NOT_ACTIVE` — and the request stamps `requested_by_user_id` and begins `PENDING`. Each request creates a new clearance, so multiple `PENDING` clearances may reference the same `ACTIVE` restriction. Each clearance references the restriction under review through its `restriction_id`, and clearances may be listed filtered by `restriction_id` or `status`. The physician then decides with an `outcome` of `CLEARED` or `DENIED` and an optional `decision_note`. The decision requires the clearance to be `PENDING` (`ERR_INVALID_STATE`) and the linked restriction still `ACTIVE` (`ERR_RESTRICTION_NOT_ACTIVE`), and stamps `decided_by_user_id` and `decided_at`, which — like the optional `decision_note` — remain null while the clearance is `PENDING`. A `CLEARED` decision transitions the restriction `ACTIVE → LIFTED`, decrements `open_restriction_count` by one, and recomputes the posture; a `DENIED` decision leaves the restriction `ACTIVE`. Both decision outcomes are terminal for the clearance.

### 3.7. Communicable-Disease Events and Contact Tracing

When a staff member becomes an index case of a communicable disease, a `SafetyOfficer` opens an event with the `index_employee_id`, the `disease` (`COVID`, `INFLUENZA`, `PERTUSSIS`, `NOROVIRUS`, or `MEASLES`), and the `onset_date`. The `onset_date` is accepted without a recency bound. Two disease-specific constants are derived at creation. The `infectious_start` is the `onset_date` shifted earlier by the disease's incubation offset — two days for `COVID`, one day for `INFLUENZA`, seven days for `PERTUSSIS`, one day for `NOROVIRUS`, and four days for `MEASLES`. The `monitoring_window_days` is the disease's monitoring span — fourteen days for `COVID`, seven for `INFLUENZA`, twenty-one for `PERTUSSIS`, three for `NOROVIRUS`, and twenty-one for `MEASLES`. The event begins `OPEN`.

The `SafetyOfficer` advances the event by submitting a `to_state`: `OPEN → TRACING`, then `TRACING → MONITORING`; any other from-state for these moves is rejected with `ERR_INVALID_STATE`. The safety officer enrolls each exposed staff member as a contact of the event — enrollment is not gated on the event's status — by supplying the `contact_employee_id` and the `contact_date`, the last date of infectious contact. A contact may not be the event's own index case (`ERR_SELF_CONTACT`), the same employee may be enrolled only once per event (`ERR_DUPLICATE_CONTACT`), and the `contact_date` must fall between the event's `infectious_start` and the current logical time, inclusive of both (`ERR_CONTACT_DATE_OUT_OF_RANGE`). Enrollment computes `monitoring_start` equal to the `contact_date` and `monitoring_end` equal to the `contact_date` plus the event's `monitoring_window_days`, and the contact begins `MONITORING` with `symptom_onset_reported` false.

A contact clears only passively and strictly: when the clock is strictly later than `monitoring_end` and `symptom_onset_reported` remains false, the contact automatically becomes `CLEARED`; at the exact instant of `monitoring_end` the contact remains `MONITORING`. Contacts may be listed filtered by `event_id`, `contact_employee_id`, or `status`. If symptoms appear, the employee themself — as a `StaffEmployee` acting on their own contact row — or a nurse reports them with a `symptom_onset_date` — accepted only while the contact is `MONITORING`, otherwise rejected with `ERR_INVALID_STATE` — which sets `symptom_onset_reported` to true and is stored on the contact (null until then) without range validation, a later report overwriting an earlier one. A nurse may then convert a `MONITORING` contact to `CONVERTED_TO_CASE`, but only when symptoms have been reported (`ERR_NO_SYMPTOMS_REPORTED`). Conversion escalates the parent event from `MONITORING` to `ESCALATED` automatically, and auto-creates a `FULL_EXCLUSION` work restriction for the contact employee starting at the current logical time, open-ended, with `origin` `CONTACT_CONVERSION` — incrementing that employee's `open_restriction_count` and recomputing posture. A `SafetyOfficer` may instead move a `MONITORING` contact to `LOST_TO_FOLLOWUP`. Either contact transition requested from a status other than `MONITORING` is rejected with `ERR_INVALID_STATE`. From `ESCALATED`, the safety officer returns the event to `MONITORING` by the same advance mechanism. The event closes only from `MONITORING`, and only when every enrolled contact has reached `CLEARED`, `CONVERTED_TO_CASE`, or `LOST_TO_FOLLOWUP`; closing with any contact still `MONITORING` is rejected with `ERR_EVENT_CLOSE_BLOCKED`. `CLOSED` is terminal, as are `CLEARED`, `CONVERTED_TO_CASE`, and `LOST_TO_FOLLOWUP` for contacts.

### 3.8. Injury Reporting and Workers' Compensation

A `SafetyOfficer` files an injury report under the injured employee with the `injury_type` (`NEEDLESTICK`, `SPLASH`, `FALL`, `LIFT`, or `OTHER`) and the `injury_datetime`, which must not be after the current logical time (`ERR_COMPLETION_OUT_OF_RANGE`). An optional `exposure_case_id` links the injury to an exposure case, which must then belong to the same employee (`ERR_CASE_EMPLOYEE_MISMATCH`). Manually filed reports carry `origin` `MANUAL`, while reports auto-created at prophylaxis start carry `origin` `PEP_LINKAGE` (see §3.5). Every report begins `FILED`.

The `osha_recordable` flag is computed and stored on the report. An injury is recordable when its `injury_type` is `NEEDLESTICK`; or when it is linked to an exposure case whose `risk_classification` is `HIGH`; or when it is linked to an exposure case that has a prophylaxis regimen in `STARTED` or `COMPLETED`. The determination is recomputed on linkage events — including a prophylaxis start or completion on the linked case — so a report's flag can change as the clinical picture develops.

The workers' compensation lifecycle is driven by the safety officer submitting a `to_state`. From `FILED`, the report moves to `WC_SUBMITTED`, and that transition assigns the `wc_claim_number`: the literal prefix `WC-` followed by a six-digit, zero-padded sequence number counting submission transitions in their order of occurrence across the system, starting from one. From either `WC_SUBMITTED` or `APPEALED`, the report may move to `WC_ACCEPTED` — the terminal accepted outcome — or to `WC_DENIED`. A denied report may move from `WC_DENIED` to `APPEALED`, and the deny-and-appeal loop between `WC_DENIED` and `APPEALED` may repeat without bound. Any transition requested from an invalid from-state is rejected with `ERR_INVALID_STATE`.

### 3.9. Vaccination Campaigns, Participation, and Coverage Accounting

A `ComplianceOfficer` creates a vaccination campaign with a `vaccine_type` (`INFLUENZA`, `COVID`, `HEP_B`, or `TDAP`), a `window_start`, a `window_end` no earlier than the start (`ERR_INVALID_REQUEST`), and a `department_scope` listing the department codes in scope — a non-empty list of one or more non-empty codes, with the value `ALL` appearing anywhere in the list declaring a house-wide campaign. The campaign window is a closed interval: both `window_start` and `window_end` are inclusive. Campaigns of the same `vaccine_type` may not have windows that intersect or even touch: a new campaign whose `window_start` falls on or before an existing same-vaccine campaign's `window_end` while its own `window_end` falls on or after that campaign's `window_start` is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`. Windows of different vaccine types may overlap freely. The campaign begins `PLANNED`.

Opening the campaign — the compliance officer's transition from `PLANNED` to `OPEN` — fans out participation: the system auto-creates a `CampaignParticipation` in `PENDING` status for every employee whose `status` is `ACTIVE` and whose `department` is in scope (every `ACTIVE` employee when the scope contains `ALL`). Creation order is deterministic: employees are processed by `created_at` ascending, with ties broken by `employee_ref` ascending. Each participation belongs to its campaign through `campaign_id`, and participations may be listed filtered by `campaign_id`, `employee_id`, or `status`; a `StaffEmployee` sees only their own participation rows.

While the campaign is `OPEN`, each participation resolves in one of three ways, each requiring the participation still be `PENDING` (`ERR_PARTICIPATION_NOT_PENDING`). A nurse records administration by submitting `to_state` `ADMINISTERED` with the `administered_at` timestamp, which must lie within the campaign's closed window — both endpoints inclusive (`ERR_ADMINISTER_OUTSIDE_WINDOW`) — and the employee must be `ACTIVE` at administration time, so a suspended employee cannot be vaccinated into compliance (`ERR_EMPLOYEE_NOT_ACTIVE`); `administered_at` remains null on any participation that has not been administered. The employee themself, acting as a `StaffEmployee` with `X-User-ID` equal to the participation's employee id (`ERR_OWNERSHIP_REQUIRED`), may decline by submitting `to_state` `DECLINED` with a non-empty `declination_reason` (`ERR_DECLINATION_REASON_REQUIRED`); declining stamps `declined_at` from the logical clock, and both `declined_at` and `declination_reason` remain null on participations that have not been declined, just as `exemption_type` remains null unless the participation is exempted. A physician may exempt the employee by submitting `to_state` `EXEMPTED` with an `exemption_type` of `MEDICAL` or `RELIGIOUS` (`ERR_INVALID_ENUM`).

The campaign closes only after its window has fully elapsed: the compliance officer's transition from `OPEN` to `CLOSED` requires the current logical time to be strictly later than `window_end`, and an earlier attempt is rejected with `ERR_CAMPAIGN_WINDOW_NOT_ENDED`. Closing triggers the delinquency cascade. Every participation still `PENDING` becomes `DELINQUENT`; each newly delinquent participation auto-creates a `ComplianceHold` in `ACTIVE` status with `reason` `CAMPAIGN_DELINQUENT` and its `participation_id` set, with `applied_at` stamped from the clock; and each new hold increments that employee's `active_hold_count` by one, so an `ACTIVE` employee whose count rises above zero transitions automatically to `SUSPENDED` with posture `ON_HOLD`. These campaign holds follow the release rules of §3.3: releasable only when the linked participation has reached `ADMINISTERED`, `DECLINED`, or `EXEMPTED`, and releasable only by explicit compliance-officer action.

Coverage reporting exposes, for a campaign, the counts `administered_count`, `declined_count`, `exempted_count`, `delinquent_count`, and `pending_count`, plus the computed `coverage_rate`. The rate is computed per department first: for each department with at least one participation, the department rate is one hundred times the share of that department's participations in `ADMINISTERED` or `EXEMPTED` among all of the department's participations, rounded half-up to two decimal places. The `coverage_rate` is then the mean of those per-department rates, itself rounded half-up to two decimal places, with departments having zero participations excluded from the mean; a campaign with no participations at all reports a `coverage_rate` of 0.0. Computing a single aggregate rate across all rows first and rounding once is forbidden — the rounding order is pinned, and the two orders can differ in the hundredths place for the same data.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, decisions, completions, and consent recordings — return `200 OK`. All endpoints are mounted under the paths below; the clock endpoint is a system-level test-driving capability outside the `/employee-health` prefix. Request payloads, computed fields, side effects, and the exact trigger conditions of every rejection are defined in §2 and §3; this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; triggers all time-based auto-transitions | ComplianceOfficer |
| POST | `/employee-health/employees` | Register an employee with the health office | EmployeeHealthNurse |
| GET | `/employee-health/employees` | List employees; StaffEmployee sees only their own row | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/employees/{id}` | Read one employee; StaffEmployee may read only their own | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/employees/{id}/pre-placement-screenings` | Open a pre-placement screening (OCC; supersedes any in-progress screening) | EmployeeHealthNurse |
| GET | `/employee-health/pre-placement-screenings` | List screenings, filterable by employee and status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/pre-placement-screenings/{id}` | Read one screening | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/pre-placement-screenings/{id}/components/complete` | Mark a screening component (PHYSICAL, TB_BASELINE, MED_EVAL) complete | EmployeeHealthNurse |
| POST | `/employee-health/pre-placement-screenings/{id}/decide` | Physician clearance decision (CLEARED or FAILED) | EmployeeHealthPhysician |
| POST | `/employee-health/employees/{id}/titer-results` | Record an immunity titer (append-only) | EmployeeHealthNurse |
| GET | `/employee-health/titer-results` | List titer results, filterable by employee, screening, disease | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/titer-results/{id}` | Read one titer result | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/employees/{id}/annual-requirement-cycles` | Open the annual TB / fit-test cycle for an ACTIVE employee | ComplianceOfficer |
| GET | `/employee-health/annual-requirement-cycles` | List cycles, filterable by employee and status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/annual-requirement-cycles/{id}` | Read one cycle | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/annual-requirement-cycles/{id}/completions` | Record a TB_SCREENING or FIT_TEST completion | EmployeeHealthNurse |
| GET | `/employee-health/compliance-holds` | List holds, filterable by employee, cycle, participation, status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/compliance-holds/{id}` | Read one hold | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/compliance-holds/{id}/release` | Release an ACTIVE hold after verifying the underlying requirement | ComplianceOfficer |
| POST | `/employee-health/employees/{id}/exposure-cases` | Bloodborne-pathogen exposure intake | EmployeeHealthNurse |
| GET | `/employee-health/exposure-cases` | List exposure cases, filterable by employee and case status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/exposure-cases/{id}` | Read one exposure case | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/exposure-cases/{id}/transition` | Advance the case clinical dimension (EVALUATION, MANAGEMENT, CLOSED) | EmployeeHealthPhysician |
| POST | `/employee-health/exposure-cases/{id}/source-testing` | Record source-patient consent outcome or lab results (segregation of duties) | EmployeeHealthNurse |
| GET | `/employee-health/pep-regimens` | List prophylaxis regimens, filterable by case and status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/pep-regimens/{id}` | Read one prophylaxis regimen | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/pep-regimens/{id}/transition` | PEP lifecycle: STARTED or COMPLETED (physician); DECLINED (the exposed employee) | EmployeeHealthPhysician, StaffEmployee |
| GET | `/employee-health/serology-follow-ups` | List serology follow-ups, filterable by case, status, milestone | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/serology-follow-ups/{id}` | Read one serology follow-up | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/serology-follow-ups/{id}/transition` | RESULTED (nurse) or WAIVED (physician) | EmployeeHealthNurse, EmployeeHealthPhysician |
| POST | `/employee-health/employees/{id}/work-restrictions` | Impose a work restriction (half-open interval; overlap rejected) | EmployeeHealthPhysician |
| GET | `/employee-health/work-restrictions` | List restrictions, filterable by employee, case, status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/work-restrictions/{id}` | Read one restriction | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/work-restrictions/{id}/clearances` | Request return-to-work clearance for an ACTIVE restriction | EmployeeHealthNurse |
| GET | `/employee-health/return-to-work-clearances` | List clearances, filterable by restriction and status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/return-to-work-clearances/{id}` | Read one clearance | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/return-to-work-clearances/{id}/decide` | Physician decision; CLEARED lifts the restriction | EmployeeHealthPhysician |
| POST | `/employee-health/communicable-events` | Open a communicable-disease event for an index staff member | SafetyOfficer |
| GET | `/employee-health/communicable-events` | List events, filterable by index employee, disease, status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/communicable-events/{id}` | Read one event | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/communicable-events/{id}/advance` | Advance the event (TRACING, MONITORING, CLOSED) | SafetyOfficer |
| POST | `/employee-health/communicable-events/{id}/contacts` | Enroll a contact for monitoring | SafetyOfficer |
| GET | `/employee-health/exposure-contacts` | List contacts, filterable by event, contact employee, status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/exposure-contacts/{id}` | Read one contact | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/exposure-contacts/{id}/report-symptom` | Report symptom onset for a MONITORING contact (self or nurse) | StaffEmployee, EmployeeHealthNurse |
| POST | `/employee-health/exposure-contacts/{id}/transition` | CONVERTED_TO_CASE (nurse) or LOST_TO_FOLLOWUP (safety officer) | EmployeeHealthNurse, SafetyOfficer |
| POST | `/employee-health/employees/{id}/injury-reports` | File an injury report with optional exposure linkage | SafetyOfficer |
| GET | `/employee-health/injury-reports` | List injury reports, filterable by employee, case, status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/injury-reports/{id}` | Read one injury report | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/injury-reports/{id}/transition` | Workers' compensation lifecycle (submit, accept, deny, appeal) | SafetyOfficer |
| POST | `/employee-health/vaccination-campaigns` | Create a campaign (closed-interval window; same-vaccine overlap rejected) | ComplianceOfficer |
| GET | `/employee-health/vaccination-campaigns` | List campaigns, filterable by vaccine type and status | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/vaccination-campaigns/{id}` | Read one campaign | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/vaccination-campaigns/{id}/transition` | OPEN (fans out participations) or CLOSED (delinquency cascade) | ComplianceOfficer |
| GET | `/employee-health/vaccination-campaigns/{id}/coverage` | Computed coverage counts and rate (per-department rounding, then mean) | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer |
| GET | `/employee-health/campaign-participations` | List participations, filterable by campaign, employee, status; StaffEmployee sees only own rows | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| GET | `/employee-health/campaign-participations/{id}` | Read one participation | EmployeeHealthNurse, EmployeeHealthPhysician, ComplianceOfficer, SafetyOfficer, StaffEmployee |
| POST | `/employee-health/campaign-participations/{id}/transition` | ADMINISTERED (nurse), DECLINED (the employee themself), or EXEMPTED (physician) | EmployeeHealthNurse, StaffEmployee, EmployeeHealthPhysician |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3 alongside the workflows that raise them; this catalogue lists identity and status only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_REQUIRED` | 403 |
| `ERR_SOD_SOURCE_CONSENT` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_EMPLOYEE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CYCLE_ALREADY_OPEN` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_UNDERLYING_REQUIREMENT_UNMET` | 409 |
| `ERR_CASE_CLOSE_BLOCKED` | 409 |
| `ERR_SOURCE_TESTING_UNRESOLVED` | 409 |
| `ERR_EVENT_CLOSE_BLOCKED` | 409 |
| `ERR_PEP_WINDOW_EXPIRED` | 422 |
| `ERR_PEP_COURSE_INCOMPLETE` | 422 |
| `ERR_FOLLOWUP_NOT_DUE` | 409 |
| `ERR_RESTRICTION_NOT_ACTIVE` | 409 |
| `ERR_NO_SYMPTOMS_REPORTED` | 409 |
| `ERR_CAMPAIGN_WINDOW_NOT_ENDED` | 409 |
| `ERR_PARTICIPATION_NOT_PENDING` | 409 |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 422 |
| `ERR_COMPONENT_INCOMPLETE` | 422 |
| `ERR_IMMUNITY_NOT_ESTABLISHED` | 422 |
| `ERR_FIT_TEST_NOT_REQUIRED` | 422 |
| `ERR_SCREENING_EMPLOYEE_MISMATCH` | 422 |
| `ERR_CASE_EMPLOYEE_MISMATCH` | 422 |
| `ERR_SELF_CONTACT` | 422 |
| `ERR_FUTURE_RESULT_DATE` | 422 |
| `ERR_COMPLETION_OUT_OF_RANGE` | 422 |
| `ERR_ADMINISTER_OUTSIDE_WINDOW` | 422 |
| `ERR_CONTACT_DATE_OUT_OF_RANGE` | 422 |
| `ERR_CLOCK_REGRESSION` | 422 |
| `ERR_WORK_RESTRICTION_OVERLAP` | 409 |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_CONTACT` | 409 |
| `ERR_DUPLICATE_EMPLOYEE_REF` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INSUFFICIENT_JUSTIFICATION` | 400 |
| `ERR_DECLINATION_REASON_REQUIRED` | 400 |
