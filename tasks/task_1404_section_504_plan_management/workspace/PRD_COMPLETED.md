# Section 504 Plan Management API — Product Requirements Document

## 1. Introduction

School districts carry a legal obligation under Section 504 of the Rehabilitation Act to identify students with qualifying disabilities, document the accommodations those students receive, and demonstrate — often years later, under audit — that every procedural safeguard was honored along the way. In practice this work is scattered across spreadsheets, email threads, and filing cabinets: a teacher's referral sits in a drawer, a consent form is never logged, an annual review quietly slips past its deadline, and the district only discovers the gap when a parent files a grievance or a state auditor asks for records nobody can produce.

This document specifies an API that makes the entire Section 504 lifecycle a single, auditable system of record. It covers referral intake and eligibility determination under the two-prong disability definition, plan drafting with parent consent and teacher acknowledgment, day-to-day implementation monitoring with quantitative compliance measurement, the annual review and three-year re-evaluation cadence, district-level approval of testing accommodations, transition into and out of the IEP process, grievance handling with OCR escalation, staff training currency, and a composite school compliance posture derived from all of the above. Every consequential action appends to an append-only compliance audit trail, every time-dependent rule reads a controllable logical clock, and a small set of optimistic-concurrency guards protects workflows whose correctness depends on the writer having observed the latest state of a student, plan, or grievance.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or malformed — including an empty `X-User-ID` or an `X-User-Role` value outside the five recognized roles — is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled precisely as follows: `District504Director`, `Section504Coordinator`, `Teacher`, `SchoolPrincipal`, and `Parent`. Each operation is restricted to a designated set of roles (enumerated per endpoint in §4); an authenticated caller presenting a recognized role that is not permitted for the requested operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `District504Director`, `Section504Coordinator`, `Teacher`, or `SchoolPrincipal`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership and attribution checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID`. This is how the system stamps `submitted_by_staff_id` on a referral, `drafted_by_staff_id` on a plan, `determined_by_staff_id` on an evaluation, `logged_by_staff_id` on an implementation log, `intake_staff_id` and `resolved_by_staff_id` on a grievance, and `reviewed_by_staff_id` on a testing request, and it is how the system decides whether a teacher may respond to a particular acknowledgment row. When `X-User-Role` is `Parent`, `X-User-ID` is an opaque guardian identifier not tied to any persisted entity; the server never compares it to any entity's `id`, and parent attribution on records is carried instead through explicit payload fields such as `filed_by_parent_ref` and `responded_by_parent_ref`.

Broadly, a `District504Director` owns schools, district-level testing decisions, grievance resolution and OCR escalation, and the logical clock; a `Section504Coordinator` runs the school-level workflow from referral review through plan drafting, reviews, accommodations, and grievance intake; a `Teacher` submits referrals, acknowledges plans, and logs implementation; a `SchoolPrincipal` has read access plus staff-registration and training-record duties; and a `Parent` files grievances and reads their own student's records. Deliberate segregation-of-duties constraints (§2.9) prevent the same individual from performing both sides of sensitive pairs.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. Boolean-valued filters (such as `is_active`, `has_active_504_plan`, and `was_implemented_as_planned`) accept the query values `true` and `false` case-insensitively; any other value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Compliance Audit Trail

Every primary resource — School, Student, StaffMember, Section504Referral, EligibilityEvaluation, Section504Plan, Accommodation, TeacherAcknowledgment, ImplementationLog, ReviewEvent, TestingAccommodationRequest, ParentConsentRecord, Grievance, and StaffTrainingRecord — carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer beginning at 1 that increments by exactly 1 on every mutation of the resource, including mutations caused by cascading side effects.

The one exception is the `ComplianceAuditEvent`, the system's append-only compliance ledger. Audit events are created by the server as side effects of workflow actions and are never modified afterward; consequently an audit event carries only `id` and `created_at` — both `updated_at` and `version` are absent. Each event records the `school_id` of the school it belongs to, an `event_type` drawn from a fixed vocabulary, an `entity_ref` holding the `id` of the entity the event pertains to, an `actor_staff_id` identifying the acting `StaffMember` (null when the system itself acted), and an `event_payload` object with event-specific structured details. The event vocabulary is exactly: `REFERRAL_SUBMITTED`, `REFERRAL_REVIEWED`, `EVALUATION_INITIATED`, `CONSENT_GRANTED`, `CONSENT_DENIED`, `DETERMINATION_MADE`, `PLAN_ACTIVATED`, `PLAN_SUSPENDED`, `PLAN_TERMINATED`, `REVIEW_COMPLETED_LATE`, `REVIEW_OVERDUE`, `TEST_ACCOMM_DENIED`, `GRIEVANCE_FILED`, `GRIEVANCE_ESCALATED`, `TRAINING_LAPSED`, `POSTURE_CHANGED`, and `OCC_CONFLICT`. The audit listing is filterable by `school_id`, `event_type`, and `entity_ref`. A write rejected for a stale expected version (§2.7) is recorded in this stream with event type `OCC_CONFLICT`, and every change of a school's computed posture (§2.10) is recorded as `POSTURE_CHANGED`.

### 2.5. The Logical Clock and Scheduled Deferred Actions

The server does not read wall-clock time. All server-stamped fields (`submitted_at`, `requested_at`, `responded_at`, `filed_at`, `completed_at`, and similar) and every time-derived calculation in this document read a logical clock whose value, before it is ever set, defaults to 2026-08-01T00:00:00Z. (The one exception is the response envelope's `meta.api_request_timestamp` of §2.2, which is stamped from wall time and carries no domain meaning.) A `District504Director` may advance the clock through an administrative capability that accepts a `to_iso8601` instant and responds with the resulting `now`; the clock may be set to any instant — no forward-only monotonicity is enforced. Advancing the clock is itself a trigger: after each advance the server flips any review still sitting in `SCHEDULED` past its grace window to `OVERDUE` (emitting a `REVIEW_OVERDUE` event), expires any `TRAINED_CURRENT` training status whose validity has passed (emitting `TRAINING_LAPSED`), and recomputes every affected school's compliance posture (emitting `POSTURE_CHANGED` where the posture moved).

### 2.6. Resource Addressing and Existence Checks

Resources are addressed as flat peers — `/students/{studentId}`, `/plans/{planId}`, and so on — rather than deeply nested URLs, even though ownership relationships exist between them. Whenever a path-templated identifier or a referenced body identifier does not correspond to an existing resource, the request is rejected with HTTP 404: the generic `ERR_NOT_FOUND`, or the resource-specific `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ACCOMMODATION_NOT_FOUND`, `ERR_ACK_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_TESTING_REQUEST_NOT_FOUND`, `ERR_GRIEVANCE_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, or `ERR_CONSENT_RECORD_NOT_FOUND`. Where multiple identifiers appear in one request, existence is confirmed before any business rule is evaluated, so a missing parent surfaces before any state or validation error deeper in the request. A request to an unrecognized path, or with an unsupported method on a recognized path, is rejected with the generic `ERR_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control; each requires a non-optional expected-version field carrying the client's last observed `version` of the relevant parent entity, and each is rejected with HTTP 412 when that value does not match the entity's current `version` — meaning another writer has advanced the entity since the client last read it, and proceeding would let the client act on state it has not observed. Endpoints not listed here take no version field.

- Drafting a new plan for a student requires `expected_student_version` matching that student's current `version`; a mismatch is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412). This captures the case where a parallel evaluation's determination, or a district write-back to the student's IEP status, has mutated the student after the client read it.
- Submitting a drafted plan for parent consent requires `expected_plan_version` matching the plan's current `version`; a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). Because adding an accommodation to a plan increments the plan's `version`, this captures the case where another coordinator has changed the accommodation set since the client last observed the plan.
- Resolving a grievance requires `expected_grievance_version` matching the grievance's current `version`; a mismatch is rejected with `ERR_STALE_GRIEVANCE_VERSION` (HTTP 412). This captures the case where the grievance was escalated from informal resolution to formal investigation between the resolver's read and the resolve call, leaving the resolver's premise — still informal, with the earlier deadline — stale.

### 2.8. Validation Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order so the surfaced error is deterministic rather than an accident of implementation. The order is:

1. Header presence and well-formedness — failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the endpoint — failures yield `ERR_UNAUTHORIZED_ROLE`.
3. Existence of every path-templated and referenced resource — failures yield `ERR_NOT_FOUND` or the resource-specific 404.
4. The school posture gate — a mutation scoped under a school whose `school_posture` is `AUDIT_HOLD` is rejected with `ERR_SCHOOL_UNDER_AUDIT_HOLD` (HTTP 409) before any deeper rule runs.
5. Optimistic-concurrency version matching on the three guarded writes (§2.7) — failures yield the corresponding stale-version error with HTTP 412.
6. Entity state preconditions for the requested transition — failures yield the transition's specific `ERR_<ENTITY>_NOT_<STATE>` error (HTTP 409), such as `ERR_PLAN_NOT_DRAFT` or `ERR_REFERRAL_NOT_UNDER_REVIEW`.
7. Parent-consent gating — failures yield `ERR_PARENT_CONSENT_REQUIRED` (HTTP 422).
8. Segregation-of-duties checks — failures yield `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).
9. The testing-accommodation lead-time check — failures yield `ERR_TESTING_LEAD_TIME_INSUFFICIENT` (HTTP 422).
10. The determination-deadline check — failures yield `ERR_DETERMINATION_DEADLINE_MISSED` (HTTP 422).
11. Referential checks that a testing request's accommodation belongs to the same plan and is test-applicable — failures yield `ERR_ACCOMMODATION_NOT_TEST_APPLICABLE` (HTTP 422).
12. The requirement that an accommodation be `ACTIVE` for implementation logging — failures yield `ERR_ACCOMMODATION_NOT_ACTIVE` (HTTP 422).
13. The one-open-plan-per-student constraint — failures yield `ERR_STUDENT_PLAN_ALREADY_OPEN` (HTTP 409).
14. The one-open-evaluation-per-student constraint — failures yield `ERR_EVALUATION_ALREADY_OPEN` (HTTP 409).
15. The teacher training-currency requirement for acknowledgment — failures yield `ERR_STAFF_TRAINING_NOT_CURRENT` (HTTP 422).
16. The requirement that a plan carry at least one accommodation before consent submission — failures yield `ERR_PLAN_HAS_NO_ACCOMMODATIONS` (HTTP 422).
17. The IEP-active gate on the exit-to-IEP review outcome — failures yield `ERR_IEP_NOT_ACTIVE` (HTTP 422).

Request-body field validation — missing required fields, wrong types, out-of-vocabulary enum values, and out-of-range values, all surfaced as `ERR_INVALID_REQUEST` (HTTP 400) — is evaluated after checks 1–4 and before the state, concurrency, and business checks 5–17; where the set of body-referenced resources depends on validated fields (as with the `plan_id`/`evaluation_id` choice in §3.9), existence of those references is confirmed immediately after the validating checks.

### 2.9. Segregation of Duties

Three sensitive hand-offs must be performed by two different people, and the server enforces this by comparing the acting staff member's identity against the recorded originator, rejecting violations with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). First, the coordinator who records an eligibility determination must not be the staff member who submitted the originating referral (`submitted_by_staff_id`). Second, the district reviewer who approves a testing accommodation request must not be the coordinator who drafted the underlying plan (`drafted_by_staff_id`). Third, the director who resolves a grievance must not be the coordinator who took its intake (`intake_staff_id`). A related ownership rule applies to teacher acknowledgments: only the teacher named on an acknowledgment row may respond to it — a caller whose `X-User-ID` does not map to the row's `staff_id` is rejected with `ERR_ACK_OWNERSHIP_MISMATCH` (HTTP 403).

### 2.10. School Compliance Posture

Every school carries a computed `school_posture` — one of `OPERATIONAL`, `PROBATION`, or `AUDIT_HOLD`, initialized to `OPERATIONAL` at school creation — that summarizes its compliance health and gates mutations (item 4 of §2.8). The posture derives from a composite score built from four weighted inputs, recomputed at every moment one of those inputs can move: when a grievance at the school is filed, resolved, escalated to OCR, or closed; when a review at the school flips to `OVERDUE` or is completed; when training coverage changes (staff registration, training-record recording, or a training lapse); and whenever the logical clock advances:

- Each open grievance at the school — one whose status is `FILED`, `INFORMAL_RESOLUTION`, or `FORMAL_INVESTIGATION` — contributes 20 points.
- If any grievance at the school has reached `ESCALATED_TO_OCR`, a further 50 points are contributed. An OCR escalation therefore forces `AUDIT_HOLD` on its own, regardless of everything else.
- Each review event at the school in `OVERDUE` status contributes 15 points, with the total overdue-review contribution capped at 30 points.
- If the school's staff training coverage ratio (§3.1) falls below 0.95 — strictly less than ninety-five percent — a further 25 points are contributed.

The composite score is the sum of these contributions, capped at 100. A composite score of 60 or more, or any nonzero OCR-escalation contribution, yields `AUDIT_HOLD`. Otherwise, a composite score of 30 or more yields `PROBATION`. Below that, the school is `OPERATIONAL`. The score itself is an integer. A computed snapshot is available per school, reporting `posture`, `training_coverage_pct`, `open_grievance_count`, `overdue_review_count`, and `composite_score`.

### 2.11. Precision, Rounding, and Calendar Arithmetic

All percentages reported by the API — `implementation_compliance_pct`, `training_coverage_pct`, and the compliance-summary variants — are rounded half-up to exactly 2 decimal places. Durations are measured in whole calendar days: the number of days between two instants is the floor of their difference expressed in days, so a boundary stated as "at least 14 days" passes at exactly 14 and fails at 13. Composite posture scores are integers. Calendar offsets such as "plus 15 days", "plus 60 days", "plus 365 days", and "plus 3 years" are anchored to the server-stamped instant named in each rule and read the logical clock, never wall time. ISO 8601 inputs (`trained_at`, `date_of_birth`, `log_date`, `scheduled_for`, `test_date`, `to_iso8601`) may be dates or datetimes, with a `Z` suffix or a numeric offset; a timezone-naive value is read as UTC.

## 3. Business Logic & Workflows

### 3.1. School Onboarding, Staff Registry, and Training Compliance

A district begins by registering each school with its `school_name`, `district_code`, and `current_academic_year` (a label such as "2025-2026" against which the school's cadence reporting is anchored); a new school's `school_posture` starts at `OPERATIONAL`. Staff are then registered against a school by a `District504Director` or `SchoolPrincipal`, supplying `school_id`, an HR-system `staff_external_ref`, the staff member's `full_name`, and a `staff_role` of `TEACHER`, `COORDINATOR`, `PRINCIPAL`, or `DISTRICT_DIRECTOR`; `is_active` defaults to true and marks current employment. The staff roster can be listed with filters on `school_id`, `staff_role`, and `is_active`.

Training compliance is tracked per staff member. Recording a training completion captures the `staff_id`, a `training_topic` of `SECTION_504_BASICS`, `ACCOMMODATION_DELIVERY`, `GRIEVANCE_PROCEDURES`, `TESTING_ACCOMMODATIONS`, or `TRANSITION_PROCEDURES`, and the `trained_at` date; the record's `expires_at` is computed as exactly two calendar years after `trained_at` (a February 29 `trained_at` yields a February 28 `expires_at` in a non-leap year), and its `training_status` is `CURRENT` while the clock precedes `expires_at` and `EXPIRED` thereafter. Training records can be listed filtered by `staff_id` and `training_topic`. Each staff member's `current_training_status` is derived from their latest training record — the one with the latest `trained_at`, ties broken by most recent creation — against the clock: `UNTRAINED` when no record exists, `TRAINED_CURRENT` while the latest record is unexpired, and `TRAINED_EXPIRED` once it lapses — a default of `UNTRAINED` applies to freshly registered staff. A clock advance that pushes a staff member past `expires_at` flips them to `TRAINED_EXPIRED` and emits `TRAINING_LAPSED`.

From these records the system computes each school's training coverage: among active staff (`is_active` true) at the school, the fraction whose `current_training_status` is `TRAINED_CURRENT`, multiplied by 100 and rounded half-up to 2 decimal places; a school with no active staff is treated as fully covered (a ratio of 1.0). Coverage below ninety-five percent feeds the posture score (§2.10), so recording or expiring a single training record can flip a school's posture.

### 3.2. Student Registration and the Referral Pipeline

A `Section504Coordinator` or `SchoolPrincipal` registers a student under a school with `school_id`, a district-SIS `student_external_ref` (recorded as supplied; the server does not enforce its uniqueness), `full_name`, `date_of_birth` (an ISO 8601 date), and `grade_level` as an integer from 0 through 12 inclusive — a value outside that range is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every student carries two parallel status dimensions. The primary `section_504_status` begins at `NONE` and moves through `REFERRED`, `EVALUATING`, `PLAN_ACTIVE`, `PLAN_SUSPENDED`, `EXITED_TO_IEP`, `NOT_ELIGIBLE`, and `TERMINATED` as the workflow proceeds. The independent `iep_status` dimension — `NONE`, `IEP_ACTIVE`, or `IEP_EXITED` — is maintained by the district's special-education workflow through a student update that only a `District504Director` may perform; that update accepts an optional `iep_status`, increments the student's `version` on every call (even when `iep_status` is absent or unchanged), and deliberately triggers no automatic cascade when `iep_status` becomes `IEP_ACTIVE` while a plan is `ACTIVE` — exiting to the IEP always requires an explicit review outcome (§3.6). The derived boolean `has_active_504_plan` is true exactly when the student has exactly one plan in `ACTIVE` status. The student list is filterable by `school_id`, `section_504_status`, `iep_status`, and `has_active_504_plan`.

A 504 referral is submitted for a student by a `Teacher` or `Section504Coordinator`, carrying `student_id`, a free-text `referral_reason`, and a `suspected_disability_category` of `PHYSICAL`, `MENTAL`, `LEARNING`, `CHRONIC_HEALTH`, or `OTHER`. Submission is only valid while the student's `section_504_status` is `NONE`; any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). On acceptance the referral is stamped `submitted_at` from the logical clock, its `review_deadline` is computed as fifteen calendar days after `submitted_at` (driving overdue tracking on the referral queue), the submitter's identity is recorded in `submitted_by_staff_id` from `X-User-ID`, the referral enters `PENDING`, the student moves `NONE` → `REFERRED`, and a `REFERRAL_SUBMITTED` audit event is appended. Referrals are listed with `student_id` and `referral_status` filters.

Coordinator review then drives the referral through a small state machine whose terminal states are `REJECTED` and `WITHDRAWN`. Starting review requires the referral to be `PENDING` (otherwise `ERR_REFERRAL_NOT_PENDING`), the student to be in `REFERRED` (otherwise `ERR_STUDENT_NOT_IN_REFERRED_STATE`), and the school's posture to be anything but `AUDIT_HOLD` (otherwise `ERR_SCHOOL_UNDER_AUDIT_HOLD`); it moves the referral `PENDING` → `UNDER_REVIEW` and emits `REFERRAL_REVIEWED`. From `UNDER_REVIEW` the coordinator has three exits. Initiating an evaluation moves the referral `UNDER_REVIEW` → `EVALUATION_INITIATED`, creates a new EligibilityEvaluation in `INITIATED` linked back through `referral_id`, moves the student `REFERRED` → `EVALUATING`, and emits `EVALUATION_INITIATED`; it is rejected with `ERR_REFERRAL_NOT_UNDER_REVIEW` if the referral is not under review, and with `ERR_EVALUATION_ALREADY_OPEN` if the student already has any evaluation in a non-terminal state. Rejecting the referral (`UNDER_REVIEW` → `REJECTED`, guarded by `ERR_REFERRAL_NOT_UNDER_REVIEW`) returns the student from `REFERRED` to `NONE`. Withdrawing is permitted from either `PENDING` or `UNDER_REVIEW` (otherwise `ERR_REFERRAL_NOT_WITHDRAWABLE`), moves the referral to `WITHDRAWN`, and likewise returns the student `REFERRED` → `NONE`.

### 3.3. Eligibility Evaluation, Consent, and Determination

An EligibilityEvaluation belongs to a student and to the referral that initiated it. Re-evaluations form a self-referential chain: when an evaluation is initiated from a referral the caller may pass a `supersedes_evaluation_id` linking it to the prior evaluation it replaces. The evaluation's lifecycle runs `INITIATED` → `CONSENT_PENDING` → `CONSENT_RECEIVED` → `EVALUATION_IN_PROGRESS` → `DETERMINATION_MADE`, with `CANCELLED` as the consent-denied terminal branch; `DETERMINATION_MADE` and `CANCELLED` are the terminal states. Evaluations are listed with `student_id`, `referral_id`, `supersedes_evaluation_id`, and `evaluation_status` filters.

Requesting parent consent moves an `INITIATED` evaluation (otherwise `ERR_EVALUATION_NOT_INITIATED`) to `CONSENT_PENDING` and creates the linked ParentConsentRecord: its `consent_scope` is `RE_EVALUATION` when `supersedes_evaluation_id` is set and `INITIAL_PLAN` otherwise, and its `evaluation_id` points at this evaluation. The request-consent call returns HTTP 201 carrying the created consent record. Recording the parent's response requires the evaluation to be `CONSENT_PENDING` (otherwise `ERR_EVALUATION_NOT_AWAITING_CONSENT`), takes a `granted` flag plus the opaque `responded_by_parent_ref`, and returns the updated evaluation. When consent is granted, the evaluation moves to `CONSENT_RECEIVED`, `parent_consent_obtained_at` is stamped from the clock, the linked consent record flips to `GRANTED` with its own `responded_at` stamped, and `CONSENT_GRANTED` is emitted. When consent is denied, the linked record flips to `DENIED`, the evaluation is `CANCELLED`, the student falls back `EVALUATING` → `NONE`, and `CONSENT_DENIED` is emitted.

Starting the evaluation requires `CONSENT_RECEIVED` (otherwise `ERR_EVALUATION_NOT_READY_TO_START`); it stamps `evaluation_started_at` from the clock and computes the `determination_deadline` as sixty calendar days later. Recording the determination requires the evaluation to be `EVALUATION_IN_PROGRESS` (otherwise `ERR_EVALUATION_NOT_IN_PROGRESS`) and accepts `determination_outcome` (`ELIGIBLE` or `NOT_ELIGIBLE`) together with the two disability-definition prongs `disability_impairment_found` and `major_life_activity_affected`, both booleans defaulting to false; the determining coordinator is recorded as `determined_by_staff_id`. Three further guards apply in a fixed order. First, if `supersedes_evaluation_id` is set, that prior evaluation must already be in `DETERMINATION_MADE`, otherwise `ERR_PRIOR_EVALUATION_OPEN`. Second, the determining staff member must differ from the referral's `submitted_by_staff_id` — a violation is `ERR_SEGREGATION_OF_DUTIES` (§2.8 item 8). Third, the timeliness rule (§2.8 item 10) forbids denying late: counting whole days from `evaluation_started_at`, a determination made when more than 60 days have elapsed is rejected with `ERR_DETERMINATION_DEADLINE_MISSED` (HTTP 422) if the outcome is `NOT_ELIGIBLE`, while a late `ELIGIBLE` determination is allowed but recorded via a `REVIEW_COMPLETED_LATE` audit event.

The determination's student-facing effect depends on outcome: a `NOT_ELIGIBLE` determination moves the student to `NOT_ELIGIBLE`, while an `ELIGIBLE` determination leaves the student in `EVALUATING` — the status advance waits for a plan to actually activate. Either way, `DETERMINATION_MADE` is emitted. Cadence tracking for re-evaluation keys off the `created_at` of the student's most recent evaluation in `DETERMINATION_MADE`: re-evaluation becomes due once at least 1095 whole days (three years of 365 days) have elapsed since that anchor.

### 3.4. Plan Drafting, Parent Consent, and Teacher Acknowledgment

With an `ELIGIBLE` determination in hand, a `Section504Coordinator` drafts a Section504Plan by naming the `student_id`, the authorizing `evaluation_id`, and the OCC field `expected_student_version` (§2.7). The named evaluation must exist, but the server does not check that it belongs to the named student. Drafting is rejected with `ERR_STUDENT_PLAN_ALREADY_OPEN` whenever the student already has any plan whose status is neither `TERMINATED` nor `EXITED_TO_IEP` — even a suspended plan blocks a new draft. A new plan starts in `DRAFT`, records the drafter as `drafted_by_staff_id` from `X-User-ID`, and increments the student's `version` by 1, since the student is the OCC parent for this write. Plans can be listed filtered by `student_id`, `evaluation_id`, and `plan_status`.

The plan lifecycle is `DRAFT` → `PENDING_PARENT_CONSENT` → `PENDING_TEACHER_ACK` → `ACTIVE`, with `UNDER_ANNUAL_REVIEW`, `SUSPENDED`, and the terminal states `TERMINATED` and `EXITED_TO_IEP` reachable later. Accommodations are added to the plan while it is drafted (§3.5). Submitting the plan for parent consent carries the OCC field `expected_plan_version` and checks, in the precedence order of §2.8, that `expected_plan_version` matches the plan's current `version` (otherwise `ERR_STALE_PLAN_VERSION`, HTTP 412), that the plan is `DRAFT` (otherwise `ERR_PLAN_NOT_DRAFT`), that the linked evaluation's `determination_outcome` is `ELIGIBLE` (otherwise `ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION`), that the student has no other plan in `DRAFT`, `PENDING_PARENT_CONSENT`, `PENDING_TEACHER_ACK`, `ACTIVE`, or `UNDER_ANNUAL_REVIEW` (otherwise `ERR_STUDENT_PLAN_ALREADY_OPEN`), and that the plan carries at least one accommodation (otherwise `ERR_PLAN_HAS_NO_ACCOMMODATIONS`). A successful submission moves the plan to `PENDING_PARENT_CONSENT`, creates a ParentConsentRecord with `consent_scope` `INITIAL_PLAN` and this plan's id, increments the plan's `version` by 1, and returns the updated plan.

Recording the parent's response requires `PENDING_PARENT_CONSENT` (otherwise `ERR_PLAN_NOT_AWAITING_CONSENT`), again takes `granted` with `responded_by_parent_ref`, and returns the updated plan. On denial the consent record flips to `DENIED`, the plan falls back to `DRAFT` for revision, and `CONSENT_DENIED` is emitted. On grant the consent record flips to `GRANTED` with `responded_at` stamped, the plan advances to `PENDING_TEACHER_ACK`, and the server fans out TeacherAcknowledgment rows: one row per active `StaffMember` whose `staff_role` is `TEACHER` at the school of the plan's student, selected in `created_at` ascending order with every matching teacher included. Each row carries the `plan_id`, the teacher's `staff_id`, an `ack_status` starting at `PENDING`, and a stamped `ack_requested_at`; `ack_responded_at` stays null until the teacher responds. The plan's derived `all_teachers_acknowledged` is recomputed at this point and is initially false. Acknowledgment rows can be listed filtered by `plan_id`, `staff_id`, and `ack_status`, and a coordinator may add a replacement row to a plan by naming its `plan_id` and the new teacher's `staff_id` — the remedy when a teacher has declined. Any existing staff member may be named; no role, school, or plan-status validation is applied to a replacement row.

Teachers respond to their own rows; both the acknowledge and decline calls return the updated acknowledgment row. Acknowledging requires the row to be `PENDING` (otherwise `ERR_ACK_NOT_PENDING`), requires the caller to be the teacher named on the row (otherwise `ERR_ACK_OWNERSHIP_MISMATCH`), and requires the teacher's `current_training_status` to be `TRAINED_CURRENT` (otherwise `ERR_STAFF_TRAINING_NOT_CURRENT`). A successful acknowledgment moves the row `PENDING` → `ACKNOWLEDGED`, stamps `ack_responded_at`, increments the plan's `version` by 1, and recomputes the completion gate: `all_teachers_acknowledged` becomes true exactly when the plan has at least one acknowledgment row and no row remains in `PENDING` or `DECLINED`. When that gate flips to true while the plan is `PENDING_TEACHER_ACK`, the plan activates automatically — no separate client call. Activation stamps `plan_effective_date` from the clock, sets `next_annual_review_due` to 365 days after the effective date, sets `next_re_evaluation_due` to three years after the `created_at` of the evaluation linked by the plan's `evaluation_id`, promotes every `DRAFT` accommodation on the plan to `ACTIVE`, moves the student `EVALUATING` → `PLAN_ACTIVE`, recomputes `has_active_504_plan` to true, and emits `PLAN_ACTIVATED`. Declining instead moves the row `PENDING` → `DECLINED` (same pending and ownership guards) and blocks the plan from activating until the coordinator adds a replacement acknowledgment row for another teacher.

### 3.5. Accommodations, Implementation Logging, and Compliance Measurement

An Accommodation is added to a plan by a coordinator with `plan_id`, an `accommodation_type` of `EXTENDED_TIME`, `PREFERENTIAL_SEATING`, `REDUCED_WORKLOAD`, `BREAKS_AS_NEEDED`, `ASSISTIVE_TECH`, `MODIFIED_GRADING`, or `OTHER`, a free-text `description`, and an optional `applies_to_testing` flag defaulting to false that marks the accommodation as referenceable by testing requests. Adding is permitted whatever the plan's current status. A new accommodation starts in `DRAFT` and flips to `ACTIVE` automatically when its parent plan activates; adding one increments the plan's `version` by 1, which is precisely the write the plan-submission OCC guard protects against. Accommodations are listed filtered by `plan_id`, `accommodation_status`, and `accommodation_type`.

While a plan is active, a coordinator may suspend an individual accommodation — the accommodation must be `ACTIVE` (otherwise `ERR_ACCOMMODATION_NOT_ACTIVE` on the suspend transition) and the plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) — moving it to `SUSPENDED`; resuming reverses that move for a `SUSPENDED` accommodation (otherwise `ERR_ACCOMMODATION_NOT_SUSPENDED`) under the same plan-active requirement. Discontinuing is permitted from either `ACTIVE` or `SUSPENDED` (otherwise `ERR_ACCOMMODATION_NOT_DISCONTINUABLE`), regardless of the plan's status, and is terminal: the accommodation lands in `DISCONTINUED`, and every testing request referencing it that is still in `SUBMITTED` or `PENDING_DISTRICT_REVIEW` is automatically denied in the same request.

Day-to-day fidelity is documented through ImplementationLog entries, which a `Teacher` or `Section504Coordinator` files with `plan_id`, the `accommodation_id` being observed, the `log_date` of the observation, and a `was_implemented_as_planned` flag; the logger is recorded as `logged_by_staff_id`. The two references are looked up independently — the server does not check that the accommodation belongs to the named plan. Logging against an accommodation that is not `ACTIVE` is rejected with `ERR_ACCOMMODATION_NOT_ACTIVE`, and whenever `was_implemented_as_planned` is false a `deviation_notes` explanation is mandatory — its absence is rejected with `ERR_DEVIATION_NOTES_REQUIRED` (HTTP 400). Logs are listed filtered by `plan_id`, `accommodation_id`, and `was_implemented_as_planned`.

Each plan's `implementation_compliance_pct` is the percentage of its implementation logs that report fidelity: the count of logs with `was_implemented_as_planned` true, divided by the total number of logs in the window, multiplied by 100 and rounded half-up to 2 decimal places; an empty window yields a ratio of 1.0, i.e. 100 percent. Two windows exist. The default trailing variant, recomputed eagerly whenever a log is filed and surfaced on plan reads, counts only logs whose `log_date` falls within the inclusive window from 30 days before the current clock instant through the instant itself. The cumulative plan-year variant, produced by the plan's compliance summary, counts all logs whose `log_date` falls on or after the plan-year anchor — the later of the plan's `plan_effective_date` and the `completed_at` of its most recently completed `ANNUAL` review. The compliance summary reports `implementation_compliance_pct_trailing_30`, `implementation_compliance_pct_cumulative`, `next_annual_review_due`, and `next_re_evaluation_due`.

A plan's compliance figure is also the lever for suspension. A coordinator may suspend an `ACTIVE` plan (otherwise `ERR_PLAN_NOT_ACTIVE`) by supplying a `justification`, but only when suspension is warranted: either the plan's `implementation_compliance_pct` is strictly below 60, or the school's `school_posture` is `AUDIT_HOLD` — otherwise the request is rejected with `ERR_NO_SUSPENSION_JUSTIFICATION` (HTTP 422). Because `AUDIT_HOLD` is itself a justification, plan suspension is exempt from the school posture gate (item 4 of §2.8). Suspension moves the plan to `SUSPENDED`, moves the student `PLAN_ACTIVE` → `PLAN_SUSPENDED`, sets `has_active_504_plan` to false because a suspended plan does not count, and emits `PLAN_SUSPENDED`. Reinstating requires the plan to be `SUSPENDED` (otherwise `ERR_PLAN_NOT_SUSPENDED`) and the school's posture to be `OPERATIONAL` (otherwise `ERR_SCHOOL_UNDER_AUDIT_HOLD`); it returns the plan to `ACTIVE`, moves the student `PLAN_SUSPENDED` → `PLAN_ACTIVE`, and restores `has_active_504_plan` to true.

### 3.6. Review Cadence, Outcomes, and Plan Exit Paths

An active plan is kept honest by scheduled reviews. Annual-review due-ness is measured from an anchor — the plan's `plan_effective_date` if no `ANNUAL` review has completed, otherwise the latest `completed_at` among completed `ANNUAL` reviews — and a review becomes due once at least 365 whole days have passed since that anchor. It becomes overdue only after a further 14-day grace window, meaning strictly more than 379 days since the anchor. Re-evaluation reviews are stricter: they carry no grace window at all, with the boundary at exactly 1095 days since the anchor, matching the three-year re-evaluation cadence tracked by `next_re_evaluation_due` (itself re-anchored whenever a re-evaluation completes).

Scheduling a review — a coordinator or district director naming the `plan_id`, a `review_type` of `ANNUAL`, `RE_EVALUATION`, `PARENT_REQUESTED`, or `DISTRICT_AUDIT`, and a `scheduled_for` instant — requires the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and requires that no review for the plan already sit in `SCHEDULED` or `IN_PROGRESS` (otherwise `ERR_REVIEW_ALREADY_SCHEDULED`). The plan-state precondition is evaluated before the one-open-review capacity check, so a scheduling request that violates both rules is rejected with `ERR_PLAN_NOT_ACTIVE`. Scheduling creates the ReviewEvent in `SCHEDULED` and moves the plan `ACTIVE` → `UNDER_ANNUAL_REVIEW`; the event's `completed_at` and `outcome` stay null and `was_late` starts false. Reviews are listed filtered by `plan_id`, `review_status`, and `review_type`. If the clock advances past `scheduled_for` plus the grace window applicable to the review's type — fourteen days for an `ANNUAL` review, none for `RE_EVALUATION`, `PARENT_REQUESTED`, or `DISTRICT_AUDIT` reviews — while the review is still `SCHEDULED`, the system flips it to `OVERDUE`, emits `REVIEW_OVERDUE`, and recomputes the school's posture, since overdue reviews feed the composite score.

Starting a review moves it to `IN_PROGRESS`: from `SCHEDULED` it additionally requires the plan to be `UNDER_ANNUAL_REVIEW` (otherwise `ERR_PLAN_NOT_UNDER_REVIEW`), while a review in the wrong state is rejected with `ERR_REVIEW_NOT_SCHEDULED` — the same error that guards the start transition whether the review sits in `SCHEDULED` or `OVERDUE`. Cancelling is permitted only from `SCHEDULED` (otherwise `ERR_REVIEW_NOT_SCHEDULED`) and is a compensation: the review lands in `CANCELLED` and the plan reverts `UNDER_ANNUAL_REVIEW` → `ACTIVE`.

Completing a review requires it to be `IN_PROGRESS` (otherwise `ERR_REVIEW_NOT_IN_PROGRESS`) with the plan `UNDER_ANNUAL_REVIEW` (otherwise `ERR_PLAN_NOT_UNDER_REVIEW`), and takes an `outcome`. Completion stamps `completed_at` from the clock, moves the review to `COMPLETED`, and recomputes `was_late`: a completed `ANNUAL` review is late when `completed_at` falls more than fourteen days after `scheduled_for`, while a completed review of any other type — `RE_EVALUATION`, `PARENT_REQUESTED`, or `DISTRICT_AUDIT` — is late when `completed_at` falls after `scheduled_for` at all. A late completion emits `REVIEW_COMPLETED_LATE`. The four outcomes then drive four distinct plan-side cascades.

With `CONTINUE_PLAN`, the plan returns `UNDER_ANNUAL_REVIEW` → `ACTIVE`. When the review's `review_type` is `ANNUAL`, `next_annual_review_due` is re-anchored to 365 days after `completed_at`. When the type is `RE_EVALUATION`, `next_re_evaluation_due` is set to three years after `completed_at`, and a brand-new EligibilityEvaluation is created in `INITIATED` whose `supersedes_evaluation_id` is the plan's current `evaluation_id` and whose `referral_id` is copied from the superseded evaluation; the plan's `evaluation_id` switches over to the new evaluation once that evaluation reaches `DETERMINATION_MADE` with an `ELIGIBLE` outcome.

With `MODIFY_PLAN`, the plan re-enters `DRAFT` in a cyclic revision loop — `ACTIVE` → `UNDER_ANNUAL_REVIEW` → `DRAFT`. Accommodations remain in whatever states they hold, and accommodations may be added or removed while the plan is back in draft. The plan must then re-traverse the full activation pipeline — consent submission, parent consent, teacher acknowledgments, automatic activation — and the student's `section_504_status` remains `PLAN_ACTIVE` until the plan exits `DRAFT` again.

With `EXIT_TO_IEP`, two extra gates apply on top of the state checks: the student's `iep_status` must be `IEP_ACTIVE` (otherwise `ERR_IEP_NOT_ACTIVE`), and a ParentConsentRecord with `consent_scope` `EXIT_TO_IEP` for this plan must already be `GRANTED` (otherwise `ERR_PARENT_CONSENT_REQUIRED`). The cascade is broad: the student moves to `EXITED_TO_IEP` with `has_active_504_plan` false, every accommodation on the plan is `DISCONTINUED`, every still-`PENDING` TeacherAcknowledgment row flips to `DECLINED`, and every testing request on the plan in `SUBMITTED` or `PENDING_DISTRICT_REVIEW` is automatically denied.

With `TERMINATE_504`, the plan lands in `TERMINATED`, the student moves to `TERMINATED` with `has_active_504_plan` false, all accommodations on the plan are `DISCONTINUED`, and `PLAN_TERMINATED` is emitted.

### 3.7. Testing Accommodation Requests and District Review

When an assessment approaches, a `Section504Coordinator` or `Teacher` submits a TestingAccommodationRequest naming the `plan_id`, the `accommodation_id` to be used, the `test_name`, and the scheduled `test_date`. The referenced accommodation must belong to the same plan and carry `applies_to_testing` true; otherwise the submission is rejected with `ERR_ACCOMMODATION_NOT_TEST_APPLICABLE`. Submission itself imposes no plan-status requirement — the plan must be `ACTIVE` only at forwarding time. A `test_name` beginning with the prefix "State " marks a state-mandated test, a convention the district's retroactive integrity check relies on below. A new request is stamped `submitted_at`, enters `SUBMITTED`, and gets a `review_deadline` seven days after submission. Requests are listed filtered by `plan_id`, `accommodation_id`, and `request_status`.

Forwarding a request to the district requires it to be `SUBMITTED` (otherwise `ERR_TESTING_REQUEST_NOT_SUBMITTED`), requires the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and enforces lead time: the whole-day count from now to `test_date` must be at least 14 — exactly 14 days passes, 13 fails with `ERR_TESTING_LEAD_TIME_INSUFFICIENT`. Forwarding moves the request to `PENDING_DISTRICT_REVIEW`.

The district decision belongs to a `District504Director`. Approving requires `PENDING_DISTRICT_REVIEW` (otherwise `ERR_TESTING_REQUEST_NOT_PENDING`) and applies the segregation rule — the reviewer must differ from the plan's `drafted_by_staff_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — before moving the request to `APPROVED` and recording the reviewer in `reviewed_by_staff_id`. Denying requires the same pending state and moves the request to `DENIED`, emitting `TEST_ACCOMM_DENIED`. Both are terminal — except that an already-`APPROVED` request can later be flagged for state audit: flagging requires `APPROVED` (otherwise `ERR_TESTING_REQUEST_NOT_APPROVED`) and is a retroactive integrity check permitted only when the `test_name` starts with "State " and the underlying accommodation has since reached `DISCONTINUED` — a flagging request that fails either condition is rejected with `ERR_INVALID_STATE` (HTTP 409) — moving the request to `FLAGGED_FOR_STATE_AUDIT`.

### 3.8. Grievance Intake, Escalation, and Resolution

A grievance is filed for a student by a `Parent` or a `Section504Coordinator`, carrying `student_id`, an optional `plan_id` (a grievance may predate any plan), the filer's opaque `filed_by_parent_ref`, a `grievance_category` of `DISCRIMINATION`, `NON_IMPLEMENTATION`, `PROCEDURAL_VIOLATION`, `RETALIATION`, or `OTHER`, and a free-text `description`. Filing stamps `filed_at`, opens the grievance in `FILED`, emits `GRIEVANCE_FILED` (its `actor_staff_id` is null when the filer acts in the `Parent` role), and immediately recomputes the school's posture, since the new open grievance adds to the composite score. All grievance mutations are exempt from the school posture gate (item 4 of §2.8) — the grievance lifecycle is the remediation path by which a school digs out of `AUDIT_HOLD`. Grievances are listed filtered by `student_id`, `plan_id`, and `grievance_status`; their lifecycle runs from `FILED` through `INFORMAL_RESOLUTION` and `FORMAL_INVESTIGATION` to the terminal states `RESOLVED` and `CLOSED`, with `ESCALATED_TO_OCR` as the pre-closure escalation state.

Beginning informal resolution requires `FILED` (otherwise `ERR_GRIEVANCE_NOT_FILED`); the intake coordinator is recorded in `intake_staff_id`, and the `resolution_deadline` is set to thirty days after `filed_at`. Escalating to a formal investigation requires `INFORMAL_RESOLUTION` (otherwise `ERR_GRIEVANCE_NOT_INFORMAL`) and re-anchors the `resolution_deadline` to sixty days after the escalation instant.

Resolution is a district act guarded by optimistic concurrency. From either `INFORMAL_RESOLUTION` or `FORMAL_INVESTIGATION` (any other state yields `ERR_GRIEVANCE_NOT_INFORMAL`), a `District504Director` resolves the grievance by carrying `expected_grievance_version` (§2.7; a mismatch is `ERR_STALE_GRIEVANCE_VERSION`, HTTP 412); the resolver must differ from `intake_staff_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). Resolution records `resolved_by_staff_id`, increments the grievance's `version` by 1, moves it to `RESOLVED`, and recomputes the school's posture as the open-grievance count drops.

Two further district-only moves handle the OCR path. Escalating to OCR requires `FORMAL_INVESTIGATION` (otherwise `ERR_GRIEVANCE_NOT_FORMAL`), moves the grievance to `ESCALATED_TO_OCR`, emits `GRIEVANCE_ESCALATED`, and recomputes posture — the OCR flag alone forces `AUDIT_HOLD`. Closing requires `ESCALATED_TO_OCR` (otherwise `ERR_GRIEVANCE_NOT_ESCALATED`), lands the grievance in `CLOSED`, and recomputes posture again, which may let the school drop back out of `AUDIT_HOLD`.

### 3.9. Parent Consent Records as a General Instrument

Beyond the two consent records created automatically by the evaluation and plan workflows, a coordinator may request parent consent for an ad-hoc scope — any value in the `consent_scope` vocabulary is accepted, though `PLAN_AMENDMENT`, `EXIT_TO_IEP`, and `TESTING_ACCOMMODATION` are the scopes with no other creation path — by naming the `student_id`, the `consent_scope`, and exactly one of `plan_id` or `evaluation_id` — setting both or neither is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The full `consent_scope` vocabulary is `INITIAL_PLAN`, `PLAN_AMENDMENT`, `RE_EVALUATION`, `EXIT_TO_IEP`, and `TESTING_ACCOMMODATION`; a consent record's `evaluation_id` is set when the scope is `RE_EVALUATION` or an evaluation-tied `INITIAL_PLAN`, and its `plan_id` is set when the scope is a plan-tied `INITIAL_PLAN`, `PLAN_AMENDMENT`, `EXIT_TO_IEP`, or `TESTING_ACCOMMODATION`. Every record is stamped `requested_at` and opens in `REQUESTED`; the `consent_status` vocabulary is `REQUESTED`, `GRANTED`, `DENIED`, and `REVOKED`, with `responded_at` null until the parent responds. Recording a response takes `granted` and `responded_by_parent_ref` and imposes no precondition on the record's current `consent_status` — a response overwrites a prior decision: a grant moves the record to `GRANTED`, a denial to `DENIED`, and either way `responded_at` is stamped from the clock. Consent records are listed with `student_id`, `evaluation_id`, `plan_id`, `consent_scope`, and `consent_status` filters. A `GRANTED` record is the unlock key for the gated operations described earlier — initial plan activation flows through the plan's own consent step, re-evaluation consent flows through the evaluation's, and the exit-to-IEP review outcome requires a `GRANTED` `EXIT_TO_IEP`-scoped record, surfacing `ERR_PARENT_CONSENT_REQUIRED` where consent is missing.

## 4. Endpoint Definitions

All endpoints live at the root of the API. Operations that create a new resource return HTTP 201; operations that modify an existing resource, drive a state transition, or perform a read return HTTP 200. Request and response bodies are not repeated here — each endpoint's full contract is defined by the workflow narratives in §3 and the global rules in §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/schools` | Create a school | District504Director |
| GET | `/schools` | List schools | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/schools/{schoolId}` | Get school detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/schools/{schoolId}/compliance-summary` | Computed posture derivation snapshot | District504Director, Section504Coordinator, SchoolPrincipal |
| POST | `/staff-members` | Register a staff member | District504Director, SchoolPrincipal |
| GET | `/staff-members` | List staff (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/staff-members/{staffId}` | Get staff detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/training-records` | Record a training completion | District504Director, SchoolPrincipal, Section504Coordinator |
| GET | `/training-records` | List training records (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/training-records/{recordId}` | Get a single training record | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/students` | Register a student | Section504Coordinator, SchoolPrincipal |
| GET | `/students` | List students (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/students/{studentId}` | Get student detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| PATCH | `/students/{studentId}` | Update student `iep_status` (district special-ed write-back) | District504Director |
| POST | `/referrals` | Submit a 504 referral for a student | Teacher, Section504Coordinator |
| GET | `/referrals` | List referrals (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/referrals/{referralId}` | Get referral detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/referrals/{referralId}/start-review` | Begin coordinator review | Section504Coordinator |
| POST | `/referrals/{referralId}/initiate-evaluation` | Initiate eligibility evaluation from an under-review referral | Section504Coordinator |
| POST | `/referrals/{referralId}/reject` | Reject a referral (no evaluation) | Section504Coordinator |
| POST | `/referrals/{referralId}/withdraw` | Withdraw a referral | Section504Coordinator |
| GET | `/evaluations` | List evaluations (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/evaluations/{evaluationId}` | Get evaluation detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/evaluations/{evaluationId}/request-consent` | Request parent consent for evaluation | Section504Coordinator |
| POST | `/evaluations/{evaluationId}/record-consent` | Record parent response to evaluation consent request | Section504Coordinator |
| POST | `/evaluations/{evaluationId}/start` | Begin evaluation after consent | Section504Coordinator |
| POST | `/evaluations/{evaluationId}/determine` | Record eligibility determination | Section504Coordinator |
| POST | `/plans` | Draft a new 504 plan (OCC-guarded) | Section504Coordinator |
| GET | `/plans` | List plans (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/plans/{planId}` | Get plan detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/plans/{planId}/compliance-summary` | Cumulative implementation compliance snapshot | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/plans/{planId}/submit-for-consent` | Submit plan for parent consent (OCC-guarded) | Section504Coordinator |
| POST | `/plans/{planId}/record-parent-consent` | Record parent response to plan consent request | Section504Coordinator |
| POST | `/plans/{planId}/suspend` | Suspend an active plan | Section504Coordinator |
| POST | `/plans/{planId}/reinstate` | Reinstate a suspended plan | Section504Coordinator |
| POST | `/accommodations` | Add an accommodation to a plan | Section504Coordinator |
| GET | `/accommodations` | List accommodations (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/accommodations/{accommodationId}` | Get accommodation detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| POST | `/accommodations/{accommodationId}/suspend` | Suspend an accommodation | Section504Coordinator |
| POST | `/accommodations/{accommodationId}/resume` | Resume a suspended accommodation | Section504Coordinator |
| POST | `/accommodations/{accommodationId}/discontinue` | Discontinue an accommodation (denies pending testing requests) | Section504Coordinator |
| POST | `/teacher-acks` | Add a replacement acknowledgment row | Section504Coordinator |
| GET | `/teacher-acks` | List acknowledgment rows (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/teacher-acks/{ackId}` | Get acknowledgment detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/teacher-acks/{ackId}/acknowledge` | Teacher acknowledges plan | Teacher |
| POST | `/teacher-acks/{ackId}/decline` | Teacher declines acknowledgment | Teacher |
| POST | `/implementation-logs` | Log an implementation observation | Teacher, Section504Coordinator |
| GET | `/implementation-logs` | List implementation logs (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| GET | `/implementation-logs/{logId}` | Get log detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher |
| POST | `/reviews` | Schedule a review | Section504Coordinator, District504Director |
| GET | `/reviews` | List reviews (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/reviews/{reviewId}` | Get review detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| POST | `/reviews/{reviewId}/start` | Start a scheduled or overdue review | Section504Coordinator |
| POST | `/reviews/{reviewId}/complete` | Complete a review with an outcome | Section504Coordinator |
| POST | `/reviews/{reviewId}/cancel` | Cancel a scheduled review (compensates plan back to active) | Section504Coordinator |
| POST | `/testing-requests` | Submit a testing accommodation request | Section504Coordinator, Teacher |
| GET | `/testing-requests` | List testing requests (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| GET | `/testing-requests/{requestId}` | Get testing request detail | District504Director, Section504Coordinator, SchoolPrincipal, Teacher, Parent |
| POST | `/testing-requests/{requestId}/forward-to-district` | Forward request to district for review | Section504Coordinator |
| POST | `/testing-requests/{requestId}/approve` | District approves testing accommodation | District504Director |
| POST | `/testing-requests/{requestId}/deny` | District denies testing accommodation | District504Director |
| POST | `/testing-requests/{requestId}/flag` | Flag an approved request for state audit | District504Director |
| POST | `/consent-records` | Request parent consent for an ad-hoc scope | Section504Coordinator |
| GET | `/consent-records` | List parent consent records (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Parent |
| GET | `/consent-records/{consentId}` | Get a single consent record | District504Director, Section504Coordinator, SchoolPrincipal, Parent |
| POST | `/consent-records/{consentId}/record-response` | Record parent response to a consent request | Section504Coordinator |
| POST | `/grievances` | File a grievance | Parent, Section504Coordinator |
| GET | `/grievances` | List grievances (filterable) | District504Director, Section504Coordinator, SchoolPrincipal, Parent |
| GET | `/grievances/{grievanceId}` | Get grievance detail | District504Director, Section504Coordinator, SchoolPrincipal, Parent |
| POST | `/grievances/{grievanceId}/begin-informal` | Begin informal resolution | Section504Coordinator |
| POST | `/grievances/{grievanceId}/escalate-to-formal` | Escalate to formal investigation | Section504Coordinator |
| POST | `/grievances/{grievanceId}/resolve` | Resolve a grievance (district level, OCC-guarded) | District504Director |
| POST | `/grievances/{grievanceId}/escalate-to-ocr` | Escalate grievance to OCR | District504Director |
| POST | `/grievances/{grievanceId}/close` | Close an OCR-escalated grievance | District504Director |
| GET | `/audit-events` | List compliance audit events (append-only, filterable) | District504Director, Section504Coordinator, SchoolPrincipal |
| GET | `/audit-events/{eventId}` | Get a single audit event | District504Director, Section504Coordinator, SchoolPrincipal |
| POST | `/_clock/set_current_utc` | Set the logical clock | District504Director |

## 5. Error Code Catalogue

The following table enumerates every error identifier and its HTTP status. The conditions under which each error is raised are defined in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_SCHOOL_NOT_FOUND | 404 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_STAFF_NOT_FOUND | 404 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_EVALUATION_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_ACCOMMODATION_NOT_FOUND | 404 |
| ERR_ACK_NOT_FOUND | 404 |
| ERR_REVIEW_NOT_FOUND | 404 |
| ERR_TESTING_REQUEST_NOT_FOUND | 404 |
| ERR_GRIEVANCE_NOT_FOUND | 404 |
| ERR_TRAINING_RECORD_NOT_FOUND | 404 |
| ERR_CONSENT_RECORD_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DEVIATION_NOTES_REQUIRED | 400 |
| ERR_SCHOOL_UNDER_AUDIT_HOLD | 409 |
| ERR_STUDENT_NOT_IN_REFERRED_STATE | 409 |
| ERR_REFERRAL_NOT_PENDING | 409 |
| ERR_REFERRAL_NOT_UNDER_REVIEW | 409 |
| ERR_REFERRAL_NOT_WITHDRAWABLE | 409 |
| ERR_EVALUATION_ALREADY_OPEN | 409 |
| ERR_EVALUATION_NOT_INITIATED | 409 |
| ERR_EVALUATION_NOT_AWAITING_CONSENT | 409 |
| ERR_EVALUATION_NOT_READY_TO_START | 409 |
| ERR_EVALUATION_NOT_IN_PROGRESS | 409 |
| ERR_PRIOR_EVALUATION_OPEN | 409 |
| ERR_PLAN_NOT_DRAFT | 409 |
| ERR_PLAN_NOT_AWAITING_CONSENT | 409 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_PLAN_NOT_UNDER_REVIEW | 409 |
| ERR_PLAN_NOT_SUSPENDED | 409 |
| ERR_STUDENT_PLAN_ALREADY_OPEN | 409 |
| ERR_PLAN_HAS_NO_ACCOMMODATIONS | 422 |
| ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION | 409 |
| ERR_ACCOMMODATION_NOT_ACTIVE | 422 |
| ERR_ACCOMMODATION_NOT_SUSPENDED | 409 |
| ERR_ACCOMMODATION_NOT_DISCONTINUABLE | 409 |
| ERR_ACCOMMODATION_NOT_TEST_APPLICABLE | 422 |
| ERR_ACK_NOT_PENDING | 409 |
| ERR_ACK_OWNERSHIP_MISMATCH | 403 |
| ERR_REVIEW_ALREADY_SCHEDULED | 409 |
| ERR_REVIEW_NOT_SCHEDULED | 409 |
| ERR_REVIEW_NOT_IN_PROGRESS | 409 |
| ERR_TESTING_REQUEST_NOT_SUBMITTED | 409 |
| ERR_TESTING_REQUEST_NOT_PENDING | 409 |
| ERR_TESTING_REQUEST_NOT_APPROVED | 409 |
| ERR_GRIEVANCE_NOT_FILED | 409 |
| ERR_GRIEVANCE_NOT_INFORMAL | 409 |
| ERR_GRIEVANCE_NOT_FORMAL | 409 |
| ERR_GRIEVANCE_NOT_ESCALATED | 409 |
| ERR_PARENT_CONSENT_REQUIRED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_STAFF_TRAINING_NOT_CURRENT | 422 |
| ERR_IEP_NOT_ACTIVE | 422 |
| ERR_NO_SUSPENSION_JUSTIFICATION | 422 |
| ERR_TESTING_LEAD_TIME_INSUFFICIENT | 422 |
| ERR_DETERMINATION_DEADLINE_MISSED | 422 |
| ERR_STALE_PLAN_VERSION | 412 |
| ERR_STALE_STUDENT_VERSION | 412 |
| ERR_STALE_GRIEVANCE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
