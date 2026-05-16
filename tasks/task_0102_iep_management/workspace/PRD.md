# Special Education IEP Management API — Product Requirements Document

## 1. Introduction

Special education law in the United States places strict procedural duties on a school district: a student suspected of needing services must be evaluated with documented parental consent, an annual Individualized Education Program (IEP) must be drafted in a properly noticed meeting, goal progress must be tracked across reporting periods, related services such as occupational therapy, physical therapy, or speech-language therapy must be delivered against prescribed minutes, the least restrictive environment must be quantified, the eligibility determination must be revisited at least every three years, and transition planning must be in place by the student's sixteenth birthday. Failures at any of these gates carry compliance consequences, and most can only be diagnosed by reconciling state, timing, and consent across multiple cross-aggregate records.

This document specifies the IEP Management API — a multi-tenant system whose tenants are school districts. The API governs the full compliance lifecycle from initial evaluation through annual review and triennial reevaluation, expressed as a network of state machines on Students, EligibilityEvaluations, ParentalConsents, IEPs, IEPGoals, GoalProgressReports, RelatedServices, ServiceSessions, and TransitionPlans. Because almost every rule involves dates ("at least three years", "within ninety days", "on the sixteenth birthday", "after the scheduled review date"), the API exposes a deterministic logical clock that test fixtures and administrators can advance step-by-step in lieu of wall-clock time. Cascades, segregation-of-duties checks, compensatory-service accounting, and least-restrictive-environment classification are all derived from the same authoritative entity model defined below.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers. `X-User-ID` identifies the acting user; `X-User-Role` declares the operational capacity in which that user is acting. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the role declared in `X-User-Role` is not permitted to invoke the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognises exactly five roles, spelled as follows:

- `DistrictAdmin` — district administrator. Manages district records, the deterministic clock, and student rosters. `X-User-ID` for a `DistrictAdmin` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `SchoolPsychologist` — conducts eligibility evaluations. `X-User-ID` for a `SchoolPsychologist` is an opaque operator identifier; the server records it on the evaluation as `evaluator_user_id` when an evaluation is created, but does not compare it to any persisted user entity.
- `SpecialEducationTeacher` — drafts and amends IEPs, owns goals and transition plans, files progress reports. `X-User-ID` for a `SpecialEducationTeacher` is an opaque operator identifier; the server records it on each progress report as `reported_by_user_id` but does not compare it to any persisted user entity.
- `RelatedServiceProvider` — licensed OT/PT/Speech/Counseling/Orientation-and-Mobility provider. `X-User-ID` for a `RelatedServiceProvider` is an opaque operator identifier and is supplied by the teacher as `provider_user_id` when a service is proposed; the server records it but does not compare it to any persisted user entity.
- `Parent` — legally responsible parent or guardian of a student. `X-User-ID` for a `Parent` is an opaque parent identifier, but every `Parent` request additionally requires that the value of `X-User-ID` match the `parent_user_id` recorded on the targeted `Student`. Mismatch is rejected with `ERR_PARENT_OWNERSHIP_MISMATCH`.

Segregation of duties is enforced between `SchoolPsychologist` and `Parent`: the same opaque identifier may not finalize an evaluation on a student for whom it is recorded as `parent_user_id`. Violation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

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

All endpoints that return a collection accept two query parameters. `limit` controls the maximum number of items returned: when omitted it defaults to 10, the minimum accepted value is 1, and the maximum is 100. `offset` controls the number of items skipped: when omitted it defaults to 0.

Unless an endpoint specifies otherwise, list responses are sorted by `created_at` ascending.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary entity in the system — `District`, `Student`, `EligibilityEvaluation`, `IEP`, `IEPGoal`, `RelatedService`, `ServiceSession`, and `TransitionPlan` — carries a uniform set of system-managed fields:

- `id` — a UUID string minted by the server. It is not prefixed with a type tag; clients should not parse or pattern-match on it beyond uniqueness.
- `created_at` — an ISO 8601 timestamp in UTC with exactly three fractional digits (for example, `2025-05-24T10:30:00.123Z`) recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification. Any successful mutation refreshes this field, including system-driven mutations performed as side effects of state transitions on other entities.
- `version` — an integer that begins at 1 on creation and increases by exactly one on every successful mutation, including system-driven mutations.

Two entity types are append-only event records and therefore do not carry `updated_at` or `version`: `ParentalConsent` (a new consent row is created whenever a fresh request must follow an earlier withdrawal) and `GoalProgressReport` (each report covers a distinct reporting window and is never edited). Both still carry `id` and `created_at`.

When a cascading state transition causes the system to mutate multiple entities in one operation — for example, finalizing an evaluation as ineligible may revoke an IEP, suspend its services, and discontinue its goals — every affected entity has its `updated_at` refreshed to the current logical clock and its `version` incremented by exactly one for that operation.

### 2.5. Optimistic Concurrency Control

Mutation endpoints accept an optional `version` field in the request body. When provided, the server compares it against the resource's current `version`; a mismatch is rejected with `ERR_VERSION_MISMATCH`. When the field is omitted from the body, the mutation proceeds without a concurrency check. Concurrent mutations that compete for the same invariant are described in §2.6 and resolve to a first-writer-wins outcome at the storage layer regardless of whether `version` was supplied.

### 2.6. Concurrency and First-Writer-Wins Serialisation

Several invariants in this system are enforced by an atomic, first-writer-wins serialisation point at the storage layer. The losing side observes whatever state the winner left behind and receives a specific error. Five serialisation points are guaranteed:

- Two `SpecialEducationTeacher` operators attempting to activate two different `DRAFT` IEPs for the same student race on the assignment of `Student.current_iep_id`. Exactly one activation wins; the second is rejected with `ERR_IEP_ALREADY_ACTIVE`.
- Two `RelatedServiceProvider` operators attempting to activate two `PROPOSED` related services on the same IEP with the same `service_type` race on the at-most-one-active rule for that `(iep_id, service_type)` pair. Exactly one wins; the loser is rejected with `ERR_SERVICE_TYPE_ALREADY_ACTIVE`.
- A `Parent` attempting to approve and reject the same `PENDING` `ParentalConsent` simultaneously races on the consent leaving `PENDING`. Exactly one decision wins; the loser is rejected with `ERR_CONSENT_NOT_PENDING`.
- A `Parent` withdrawing an `APPROVED` consent while a `RelatedServiceProvider` concurrently activates the gated related service races on the consent's status. If the withdrawal commits first, the activation reads a non-`APPROVED` consent and is rejected with `ERR_SERVICE_CONSENT_NOT_APPROVED`.
- Two progress reports filed concurrently for the same `(iep_goal_id, reporting_period_index)` pair race on the uniqueness of that pair. Exactly one wins; the loser is rejected with `ERR_DUPLICATE_PROGRESS_REPORT`.
- Two service sessions created concurrently on the same `RelatedService` with overlapping time windows race on the no-overlap invariant. Exactly one creation wins; the loser is rejected with `ERR_SERVICE_SESSION_OVERLAP`.

### 2.7. The Deterministic Logical Clock

Every district carries a `current_date` field that functions as the system's authoritative present. All compliance arithmetic — triennial reevaluation maturity, transition-plan age threshold, IEP expiration on the scheduled review date, the service-session "not due yet" gate, and the compensatory-service eligibility window — reads from this clock and never from wall-clock time. When a district is created, its `current_date` is initialised to `2025-01-01T00:00:00.000Z`.

The clock advances only through an admin-only test-driving capability that accepts an integer `by_days` in the request body, validated as an integer between 1 and 3650 inclusive. Advancing the clock has three immediate effects: the district's `current_date` is increased by exactly `by_days` days; for every student in the district, the system recomputes `triennial_status` and `requires_transition_plan` against the new clock; and any IEP currently in `ACTIVE` whose `scheduled_review_date` is at or before the new `current_date` is automatically transitioned to `EXPIRED`, carrying with it the full expiration cascade described in §3.

### 2.8. Path Validation and Nested Resource Retrieval

All endpoints address resources through a strict hierarchical path, beginning with `districtId`, then `studentId`, then optionally `evaluationId`, `consentId`, `iepId`, `goalId`, `serviceId`, or `sessionId`. The system validates each path segment from left to right and rejects the request at the first segment that does not resolve. A request for an IEP under a non-existent student therefore returns `ERR_STUDENT_NOT_FOUND`, not `ERR_IEP_NOT_FOUND`. The specific 404 returned identifies the first missing segment: `ERR_DISTRICT_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_IEP_NOT_FOUND`, `ERR_GOAL_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_TRANSITION_PLAN_NOT_FOUND`, or `ERR_PROGRESS_REPORT_NOT_FOUND`. Cross-aggregate references inside a request body — for example, `consent_id` on a related service or `target_resource_id` on a consent — must additionally resolve to the same district and student as the path; otherwise the request is rejected with `ERR_CROSS_STUDENT_REFERENCE`.

### 2.9. Validation Priority Order

When several validations could reject the same request, the server evaluates them in a fixed priority order so that the resulting `error_id` is deterministic. The order is: (1) header presence, surfaced as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission per §2.1, surfaced as `ERR_INSUFFICIENT_PERMISSIONS`; (3) path-segment existence, surfaced as the appropriate 404 from §2.8; (3.5) parent ownership for any endpoint authorised for `Parent`, surfaced as `ERR_PARENT_OWNERSHIP_MISMATCH`; (4) optimistic concurrency, surfaced as `ERR_VERSION_MISMATCH`; (5) target state, surfaced as the entity-specific state error such as `ERR_IEP_NOT_DRAFT` or `ERR_CONSENT_NOT_PENDING`; (6) cross-aggregate referential integrity, surfaced as `ERR_CROSS_STUDENT_REFERENCE`; (7) segregation of duties on evaluation finalize, surfaced as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; (8) eligibility prerequisite, surfaced as `ERR_STUDENT_NOT_ELIGIBLE`; (9) IEP-implementation consent prerequisite, surfaced as `ERR_IEP_CONSENT_NOT_APPROVED`; (10) related-service consent prerequisite, surfaced as `ERR_SERVICE_CONSENT_NOT_APPROVED`; (11) transition-plan requirement at activation, surfaced as `ERR_TRANSITION_PLAN_REQUIRED`; (12) at-most-one-active IEP per student, surfaced as `ERR_IEP_ALREADY_ACTIVE`; (13) at-most-one-active service per `(iep_id, service_type)`, surfaced as `ERR_SERVICE_TYPE_ALREADY_ACTIVE`; (14) service-session overlap, surfaced as `ERR_SERVICE_SESSION_OVERLAP`; (15) IEP period overlap, surfaced as `ERR_IEP_PERIOD_OVERLAP`; (16) goal-objective weight sum, surfaced as `ERR_OBJECTIVE_WEIGHTS_INVALID`; (17) progress-report objective-set parity, surfaced as `ERR_PROGRESS_OBJECTIVE_SET_MISMATCH`; (18) progress-report uniqueness on `(iep_goal_id, reporting_period_index)`, surfaced as `ERR_DUPLICATE_PROGRESS_REPORT`; and (19) instructional-time cap on related-service activation, surfaced as `ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME`. Generic body shape problems — missing required fields, type mismatches, out-of-range numeric values, transition-plan invitations not documented — are reported as `ERR_INVALID_REQUEST` or, when the issue is specifically the transition-plan invitation flags, as `ERR_TRANSITION_INVITATIONS_MISSING`.

### 2.10. Precision and Rounding

All percentage and weighted-score values stored on the system — `lre_percentage_instructional`, `lre_percentage_school_day`, `mastery_score`, and `utilization_percent` — are computed with full decimal precision and then rounded half-up to two decimal places before being persisted or returned. Compensatory-minutes accounting follows a different precision rule, stated in §3 alongside its rounding-order convention. Day-based compliance thresholds (`triennial_status`, `requires_transition_plan`) use exact calendar-day arithmetic against the deterministic clock, with boundary inclusivity stated in §3.

### 2.11. Least Restrictive Environment Classification

The Least Restrictive Environment (LRE) doctrine requires districts to report how much of a student's instructional week is spent outside the regular education setting. The system maintains this metric on every IEP through two parallel computations, both recomputed whenever a related service activates, suspends, resumes, completes, or whenever an IEP transitions out of `DRAFT` or completes an amendment cycle. The classification rule itself — which buckets a student into `LRE_A`, `LRE_B`, or `LRE_C` — uses only one of the two variants, as described in §3. The other variant is reported alongside it for transparency.

### 2.12. Cascade Semantics

Several state transitions trigger cascades that mutate multiple downstream entities atomically. A consent withdrawal can suspend services, recompute compensatory minutes, and move an IEP into amendment-pending. An ineligibility finding can revoke an active IEP, suspend its services, and discontinue its goals. An IEP expiration cascades to its goals, its services, and its transition plan. A superseding IEP activation transitions the prior IEP and its dependents to terminal states. Every entity touched by a cascade has its `updated_at` refreshed to the current logical clock and its `version` incremented by one for that operation; the specific downstream state values are listed in §3 with each parent transition.

## 3. Business Logic & Workflows

### 3.1. Tenant Bootstrap and the Deterministic Present

The system is multi-tenant. The first thing a `DistrictAdmin` does in a fresh deployment is create the tenant district, which is identified by its `name` and its `state_code` (a two-letter US state code). The server mints the district's `id`, sets its `current_date` to `2025-01-01T00:00:00.000Z`, and returns the resulting district resource. Subsequently, the `DistrictAdmin` registers each student under that district by supplying `external_student_number` (the district-assigned identifier, unique within the district), `date_of_birth` (an ISO 8601 UTC date), and `parent_user_id` (the opaque identifier that will be supplied by the parent on later consent operations). Upon creation, the student's `triennial_status` and `lre_classification` are both set to `NOT_APPLICABLE`, the student's `current_iep_id` and `current_eligibility_evaluation_id` are null, and `triennial_reevaluation_due_date` is null. The student's `district_id` is owned by the server and equals the district in the URL path.

`DistrictAdmin` is also the sole role permitted to advance the deterministic clock. The capability accepts only `by_days` in the body. On success, the district's `current_date` advances by exactly that number of days, every student in the district has its derived compliance fields recomputed (specifically `triennial_status` and `requires_transition_plan`), and any IEP whose `scheduled_review_date` is at or before the new `current_date` and that is still `ACTIVE` is moved to `EXPIRED` with the cascade described in §3.5. The clock never moves backward.

When a student record is read, the server recomputes `triennial_status` and `requires_transition_plan` lazily against the current clock value at read time, so the response always reflects the present even between explicit clock advances.

### 3.2. Eligibility: Evaluation, Consent, and the Three-Year Cycle

Before a student can have any IEP, a `SchoolPsychologist` must produce an eligibility finding. The psychologist creates an `EligibilityEvaluation` for the student by supplying `evaluation_type`, which is one of `INITIAL` (first-ever evaluation), `TRIENNIAL` (the once-every-three-years reevaluation), or `INTERIM` (an out-of-cycle reassessment). The server records `requested_at` to the current clock, mints `evaluator_user_id` from `X-User-ID`, sets the `student_id` and `district_id` from the path, derives `is_reevaluation` as true exactly when `evaluation_type` equals `TRIENNIAL`, and starts the evaluation in `REQUESTED`.

From `REQUESTED`, the psychologist transitions the evaluation by requesting consent: this moves the evaluation to `CONSENT_PENDING` and simultaneously creates a `ParentalConsent` with `scope=EVALUATION`, `target_resource_type=EligibilityEvaluation`, `target_resource_id` equal to the evaluation's `id`, and `status=PENDING`. Attempts to request consent on an evaluation not in `REQUESTED` are rejected with `ERR_EVALUATION_NOT_REQUESTED`.

The gated consent flows independently. A `Parent` approves the consent by acting on it directly: the server stamps `decided_at` from the current clock, moves the consent to `APPROVED`, and — because the scope is `EVALUATION` — automatically advances the gated evaluation to `IN_PROGRESS` and records `consent_received_at` on the evaluation equal to the consent's `decided_at`. A `Parent` may instead reject the consent, in which case `decided_at` is stamped and the consent moves to `REJECTED`; the gated evaluation remains in `CONSENT_PENDING` and no longer has a viable consent path until the psychologist issues a fresh consent request through a new evaluation request-consent action. Both approve and reject require the consent to be in `PENDING` (otherwise `ERR_CONSENT_NOT_PENDING`) and require the acting `Parent`'s `X-User-ID` to equal the student's `parent_user_id` (otherwise `ERR_PARENT_OWNERSHIP_MISMATCH`).

Once the evaluation is `IN_PROGRESS`, the same psychologist (whose `X-User-ID` must equal `evaluator_user_id` on the evaluation) finalizes it. Finalization requires submitting `disability_categories` in the request body. The set of allowed values is fixed: `SLD`, `OHI`, `ASD`, `SI`, `OI`, `ED`, `ID`, `HI`, `VI`, `DB`, `TBI`, `MD`, `DD`. A non-empty `disability_categories` array drives the evaluation to `ELIGIBLE`; an empty array drives it to `INELIGIBLE`. Either way, `finalized_at` is stamped from the current clock and `Student.current_eligibility_evaluation_id` is set to the evaluation's `id`. The two finalize branches are equally specified and must be treated as siblings in implementation:

- `IN_PROGRESS → ELIGIBLE` requires that the evaluation be in `IN_PROGRESS` (else `ERR_EVALUATION_NOT_IN_PROGRESS`), that `disability_categories` be non-empty, and that the acting psychologist not also be the student's `parent_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`). On success the evaluation moves to `ELIGIBLE`, `finalized_at` is set, the student's `current_eligibility_evaluation_id` is updated, `triennial_reevaluation_due_date` is set to `finalized_at` plus three calendar years (preserving the same month and day), and `triennial_status` is recomputed (it becomes `ON_TRACK` immediately after a fresh finalization).

- `IN_PROGRESS → INELIGIBLE` requires that the evaluation be in `IN_PROGRESS` (else `ERR_EVALUATION_NOT_IN_PROGRESS`), that `disability_categories` be empty in the request body, and that the acting psychologist not also be the student's `parent_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`). On success the evaluation moves to `INELIGIBLE`, `finalized_at` is set, the student's `current_eligibility_evaluation_id` is updated, and if the student currently has a non-null `current_iep_id` the system cascades: the active IEP is moved to `REVOKED`, every `RelatedService` on that IEP currently in `ACTIVE` is moved to `SUSPENDED` with its `compensatory_minutes_owed` recomputed per §3.6, every `IEPGoal` on that IEP currently in `ACTIVE` is moved to `DISCONTINUED`, the student's `current_iep_id` is cleared to null, and the student's `lre_classification` is set to `NOT_APPLICABLE`. Every entity touched by the cascade has its `updated_at` refreshed and `version` incremented.

A student's triennial cycle is derived from `triennial_reevaluation_due_date`. When that field is null (no evaluation has ever been finalized), `triennial_status` is `NOT_APPLICABLE`. Otherwise the server computes the integer number of days from the current clock to the due date and classifies the student on these inclusive-exclusive boundaries: if the difference is strictly greater than 90 days, `triennial_status` is `ON_TRACK`; if the difference is between zero days and 90 days inclusive, `triennial_status` is `DUE_SOON`; if the difference is strictly less than zero days, `triennial_status` is `OVERDUE`. The boundary conditions matter: exactly 91 days remaining is `ON_TRACK`, exactly 90 days remaining is `DUE_SOON`, exactly 0 days remaining (due today) is `DUE_SOON`, and one day past due is `OVERDUE`. Recomputation is triggered when an evaluation finalizes, when the clock advances, and lazily on each student read.

The `ParentalConsent` entity itself supports a withdrawal cycle that is described in detail in §3.4, where the consequences of withdrawal across all four consent scopes are enumerated together.

### 3.3. The Annual IEP: From Draft to Active

Once a student has an `ELIGIBLE` evaluation, a `SpecialEducationTeacher` drafts that student's annual IEP. Drafting requires `meeting_held_at` (the datetime of the annual IEP meeting that produced the draft), `effective_start_date` (the date the IEP will become effective once activated), `total_instructional_minutes_per_week` (the denominator for the canonical LRE percentage; for example, 1500 minutes for a school operating five 300-minute instructional days), and `total_school_day_minutes_per_week` (the denominator for the reported-but-not-classifying LRE variant, which includes lunch and recess). On creation the IEP enters `DRAFT`, its `scheduled_review_date` is set to `effective_start_date` plus 365 days, and `special_education_minutes_per_week` starts at zero. The IEP inherits `student_id` and `district_id` from the path.

Inside a `DRAFT` IEP the teacher composes its instructional content. Goals are added with `domain` (one of `ACADEMIC`, `COMMUNICATION`, `MOTOR`, `BEHAVIORAL`, `FUNCTIONAL`, `TRANSITION`), `description` (the measurable annual goal text), and `objectives`. Each objective is a record containing an `objective_id`, a `weight` strictly greater than zero and less than or equal to one, and a `latest_progress_percent` that ranges from 0 through 100 inclusive and defaults to 0 when the goal is created. At least one objective is required, and the sum of all objective `weight` values on a goal must equal exactly 1.00 when rounded half-up to two decimal places; otherwise the goal create or update is rejected with `ERR_OBJECTIVE_WEIGHTS_INVALID`. The goal also carries `iep_id`, `student_id`, and `district_id` set from context, and it begins life in `PROPOSED`. The computed fields `mastery_score` and `mastery_tier` are described in §3.7.

Related services are proposed in the same `DRAFT` window through a separate path described in §3.4; only their proposal happens here. Each proposal supplies `service_type` (one of `OT`, `PT`, `SPEECH`, `COUNSELING`, `ORIENTATION_MOBILITY`), `minutes_per_week` (a strictly positive integer), `provider_user_id` (the opaque identifier of the licensed `RelatedServiceProvider` who will deliver the service), and `location_setting` (one of `PULL_OUT`, `PUSH_IN`, `COMMUNITY`).

If the student qualifies for transition planning at the time of activation, a `TransitionPlan` must also be created and finalized before activation. Transition-plan creation accepts `post_secondary_goal` (a measurable post-secondary goal of length between 10 and 1000 characters inclusive), `required_courses` (a non-empty array of records, each with a `course_code` and a `projected_completion_term`), `outside_agency_referrals` (an array of records each with an `agency_name` and a `contact_role`; may be empty), `parent_invitation_documented` (a boolean), and `student_invitation_documented` (a boolean). The plan inherits `iep_id` and `student_id` and starts in `DRAFT`. To finalize the transition plan to `FINALIZED`, the plan must be in `DRAFT` (else `ERR_TRANSITION_PLAN_NOT_DRAFT`), `post_secondary_goal` must be at least 10 characters long, `required_courses` must be non-empty, both `parent_invitation_documented` and `student_invitation_documented` must be true (else `ERR_TRANSITION_INVITATIONS_MISSING`), and the parent IEP must be in `DRAFT` or `AMENDMENT_PENDING` (else `ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION`). Other shape problems are reported as `ERR_INVALID_REQUEST`.

Activating the IEP transitions it from `DRAFT` to `ACTIVE` and is the system's primary compliance gate. Activation succeeds only when every one of the following holds; otherwise the named error is returned: the IEP is in `DRAFT` (`ERR_IEP_NOT_DRAFT`); the student's `current_eligibility_evaluation_id` resolves to an evaluation in `ELIGIBLE` (`ERR_STUDENT_NOT_ELIGIBLE`); a `ParentalConsent` with `scope=IEP_IMPLEMENTATION`, `target_resource_type=IEP`, and `target_resource_id` equal to this IEP's `id` exists in `APPROVED` (`ERR_IEP_CONSENT_NOT_APPROVED`); `meeting_held_at` is non-null and is at or before the district's `current_date` (`ERR_IEP_MEETING_NOT_HELD`); at least one `IEPGoal` exists on this IEP in `PROPOSED` (`ERR_IEP_NO_GOALS`); if `requires_transition_plan` is true for the student, a `TransitionPlan` for this IEP exists in `FINALIZED` (`ERR_TRANSITION_PLAN_REQUIRED`); the student has no other IEP currently in `ACTIVE` or `AMENDMENT_PENDING` (`ERR_IEP_ALREADY_ACTIVE`); and the proposed `effective_start_date` is strictly later than the `scheduled_review_date` of the most recent prior IEP for the same student under half-open period semantics, where adjacency counts as a forbidden touch (`ERR_IEP_PERIOD_OVERLAP`).

On successful activation the IEP enters `ACTIVE`, every `IEPGoal` on the IEP currently in `PROPOSED` transitions to `ACTIVE`, the student's `current_iep_id` becomes this IEP's `id`, the IEP's `scheduled_review_date` is reaffirmed as `effective_start_date` plus 365 days, the student's `lre_classification` is recomputed via the LRE calculation, and if a `TransitionPlan` for this IEP exists in `FINALIZED` it advances to `ACTIVE`. The IEP captures the value of `Student.requires_transition_plan` at the moment of activation into its own `requires_transition_plan` field and locks that flag thereafter; the IEP's `transition_plan_id` references the linked `TransitionPlan` and is required non-null whenever `requires_transition_plan` is true. If a different IEP for this student was previously in `ACTIVE`, that prior IEP is automatically transitioned to `SUPERSEDED` per §3.5.

Transition-plan eligibility for a student is derived from the student's age relative to the deterministic clock: `requires_transition_plan` becomes true on or after the calendar day equal to `date_of_birth` plus 16 calendar years (same month and day; the comparison is at-or-after, so the sixteenth birthday itself counts) and only when `current_iep_id` is non-null. The field is recomputed when the clock advances, when an IEP activates, and lazily on each student read.

A `SpecialEducationTeacher` may begin an amendment on an `ACTIVE` IEP, moving it to `AMENDMENT_PENDING` (rejected with `ERR_IEP_NOT_ACTIVE` if the IEP is not in `ACTIVE`). While in `AMENDMENT_PENDING`, mutations to its goals and related services that are not part of the amendment-finalize action are locked. Finalizing the amendment moves the IEP back to `ACTIVE` (rejected with `ERR_IEP_NOT_AMENDMENT_PENDING` if not in `AMENDMENT_PENDING`) and triggers a recomputation of the student's `lre_classification`.

### 3.4. Parental Consent: Four Scopes, One Withdrawal Path

A `ParentalConsent` exists in four scopes, distinguished by the `scope` field and paired with a matching `target_resource_type`. The pairings are fixed: `scope=EVALUATION` pairs with `target_resource_type=EligibilityEvaluation`; `scope=IEP_IMPLEMENTATION` pairs with `target_resource_type=IEP`; `scope=RELATED_SERVICE` pairs with `target_resource_type=RelatedService`; `scope=PLACEMENT_CHANGE` pairs with `target_resource_type=Student`. Submitting a mismatched pair is rejected as `ERR_INVALID_REQUEST`. The `target_resource_id` must point to a resource that belongs to the same student and district as the path; otherwise `ERR_CROSS_STUDENT_REFERENCE` applies. The server stamps `requested_at` on creation from the current clock and starts the consent in `PENDING`. Note that consents for `scope=EVALUATION` are not created via the general consent endpoint — they are auto-created as the side effect of the psychologist's request-consent action on the evaluation, as described in §3.2. The general consent-create endpoint is therefore used by `SpecialEducationTeacher` for `scope=IEP_IMPLEMENTATION` consents and by `RelatedServiceProvider` for `scope=RELATED_SERVICE` consents.

Every transition on a `ParentalConsent` is performed by the `Parent` whose `X-User-ID` equals the student's `parent_user_id`. Approve and reject both require the consent to be in `PENDING` (otherwise `ERR_CONSENT_NOT_PENDING`). Approve stamps `decided_at`, moves the consent to `APPROVED`, and triggers a side effect that depends on `scope`:

- `scope=EVALUATION`: the gated `EligibilityEvaluation` advances from `CONSENT_PENDING` to `IN_PROGRESS`; the evaluation's `consent_received_at` is set to the consent's `decided_at`.
- `scope=IEP_IMPLEMENTATION`: nothing changes on the IEP at this moment, but this approval satisfies the consent prerequisite for a later IEP activation.
- `scope=RELATED_SERVICE`: the gated `RelatedService` has its `consent_id` set to this consent's `id`, enabling subsequent activation.
- `scope=PLACEMENT_CHANGE`: the approval is recorded but no further action is triggered in this version of the API.

Reject simply stamps `decided_at` and moves the consent to `REJECTED`; no cascade follows.

Withdrawal applies to a consent currently in `APPROVED` (otherwise `ERR_CONSENT_NOT_APPROVED`). It stamps `withdrawn_at` from the current clock, moves the consent to `WITHDRAWN`, and cascades according to `scope`:

- `scope=RELATED_SERVICE`: every `RelatedService` whose `consent_id` equals this consent is transitioned from `ACTIVE` to `SUSPENDED`. Each such suspension triggers the compensatory-service computation, which sets that service's `compensatory_minutes_owed`. After all dependent services are suspended, the sum of `compensatory_minutes_owed` across all services on the parent IEP is recomputed; if that sum is strictly greater than zero, the parent IEP enters `AMENDMENT_PENDING`. Each affected service has its `updated_at` refreshed and `version` incremented; the parent IEP, if it transitions, also has `updated_at` and `version` updated.
- `scope=IEP_IMPLEMENTATION`: the gated IEP is transitioned to `REVOKED` independently; the full revocation cascade described in §3.5 then runs on that IEP. The withdrawal does not also chain through the IEP's services individually because the revocation is the direct effect.
- `scope=EVALUATION` on an `IN_PROGRESS` evaluation: the evaluation cannot proceed; the psychologist must issue a fresh request-consent action that creates a new `ParentalConsent` row. The evaluation itself remains in `IN_PROGRESS` for the withdrawal step alone.
- `scope=PLACEMENT_CHANGE`: no cascade in this version of the API.

Because consent rows are append-only, `ParentalConsent` does not carry `updated_at` or `version`; a new row is created whenever the parent re-considers after a withdrawal.

### 3.5. IEP Termination Paths and Their Cascades

An `ACTIVE` IEP can leave that state through five paths, each with its own cascade. The cascades operate on the entire dependent graph — goals, services, transition plan, and student summary — atomically.

When the deterministic clock has advanced such that `current_date` is at or after `scheduled_review_date` and no superseding IEP has activated in the meantime, the IEP is automatically moved to `EXPIRED`. Every `IEPGoal` on the IEP currently in `ACTIVE` is transitioned to `NOT_MET`; every `RelatedService` on the IEP currently in `ACTIVE` is transitioned to `SUSPENDED` and has its `compensatory_minutes_owed` computed per §3.6; the student's `current_iep_id` is cleared to null; the student's `lre_classification` is set to `NOT_APPLICABLE`; and any `TransitionPlan` linked to this IEP currently in `ACTIVE` is moved to `SUPERSEDED`.

When an evaluation finalizes as `INELIGIBLE` while the student has a non-null `current_iep_id`, or when a `ParentalConsent` with `scope=IEP_IMPLEMENTATION` for this IEP is withdrawn, the IEP is moved to `REVOKED`. Revocation cascades just like expiration except that goals transition to `DISCONTINUED` rather than `NOT_MET`; services still transition to `SUSPENDED` with `compensatory_minutes_owed` computed, the student's `current_iep_id` clears, `lre_classification` becomes `NOT_APPLICABLE`, and any active transition plan moves to `SUPERSEDED`.

When a different IEP for the same student is successfully activated, the prior IEP is moved to `SUPERSEDED`. Supersession differs from revocation in one consequential way: every `RelatedService` on the prior IEP currently in `ACTIVE` is transitioned to `COMPLETED` rather than `SUSPENDED`, which represents a clean handoff to the new IEP. Concretely, `RelatedService` ACTIVE→COMPLETED on this path sets `compensatory_minutes_owed` to zero; no make-up minutes are accrued because the next IEP picks up the work. Goals on the prior IEP transition to `DISCONTINUED`, and any active transition plan moves to `SUPERSEDED`.

The `IEPGoal` close action covers two further branches that are not cascade-driven. A `SpecialEducationTeacher` closes an `ACTIVE` goal by supplying a `disposition` of either `MET` or `NOT_MET`. Closing as `MET` additionally requires that the goal's `mastery_tier` currently equal `MASTERED`; if the goal is not in `ACTIVE` the request is rejected with `ERR_GOAL_NOT_ACTIVE`, if the parent IEP is not in `ACTIVE` (for example, it is in `AMENDMENT_PENDING`) the request is rejected with `ERR_IEP_NOT_ACTIVE`, and if mastery is insufficient the request is rejected with `ERR_GOAL_NOT_MASTERED`. Closing as `NOT_MET` requires only the goal-in-`ACTIVE` and parent-IEP-in-`ACTIVE` conditions; mastery is not required. The two branches must be implemented with equal care: each requires both the goal-state and parent-IEP-state checks, and each distinguishes itself solely by the `disposition` value and the additional mastery gate.

A `TransitionPlan` can transition through its own cascade. From `FINALIZED`, it advances to `ACTIVE` automatically when its parent IEP transitions `DRAFT → ACTIVE`. From `ACTIVE`, it is moved to `SUPERSEDED` automatically when its parent IEP exits `ACTIVE` for any reason — expiration, revocation, or supersession. From `FINALIZED`, if the parent IEP is moved to `REVOKED` before it ever activates, the transition plan likewise advances to `SUPERSEDED`.

### 3.6. Related Services: Activation, Suspension, Sessions, and Compensatory Accounting

After a service is proposed in `PROPOSED` state (§3.3), the responsible `RelatedServiceProvider` activates it. Activation accepts `consent_id` in the request body and requires that: the service be in `PROPOSED` (else `ERR_SERVICE_NOT_PROPOSED`); the parent IEP be in `ACTIVE` or `AMENDMENT_PENDING` (else `ERR_IEP_NOT_ACTIVE`); the `consent_id` resolve to a `ParentalConsent` in `APPROVED` with `scope=RELATED_SERVICE` (else `ERR_SERVICE_CONSENT_NOT_APPROVED`); the student's `current_eligibility_evaluation_id` resolve to an evaluation in `ELIGIBLE` (else `ERR_STUDENT_NOT_ELIGIBLE`); no other `RelatedService` on the same `iep_id` with the same `service_type` be in `ACTIVE` (else `ERR_SERVICE_TYPE_ALREADY_ACTIVE`); and the resulting `special_education_minutes_per_week` after activation be at most `total_instructional_minutes_per_week` (else `ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME`). On success the service moves to `ACTIVE`, its `consent_id` is persisted, the IEP's `special_education_minutes_per_week` is recomputed by re-summing the `minutes_per_week` of all related services in `ACTIVE` on this IEP, the IEP's `lre_percentage_instructional` and `lre_percentage_school_day` are recomputed per §3.8, and the student's `lre_classification` is recomputed.

A service may be moved from `ACTIVE` to `SUSPENDED` in two ways: a `RelatedServiceProvider` may explicitly suspend it, or the system may cascade it to `SUSPENDED` as part of consent withdrawal (§3.4), evaluation ineligibility (§3.2), IEP revocation (§3.5), or IEP expiration (§3.5). In every case the service must be in `ACTIVE` (else `ERR_SERVICE_NOT_ACTIVE`); on the transition the system computes `compensatory_minutes_owed` per the formula below, recomputes IEP `special_education_minutes_per_week` (subtracting this service's `minutes_per_week`), recomputes both LRE percentage variants, and recomputes the student's `lre_classification`.

A `SUSPENDED` service can be resumed back to `ACTIVE` by the `RelatedServiceProvider` by supplying a `consent_id` in the request body. Resume requires the service to be in `SUSPENDED` (else `ERR_SERVICE_NOT_SUSPENDED`), the resolved consent to be in `APPROVED` (else `ERR_SERVICE_CONSENT_NOT_APPROVED`), and the parent IEP to be in `ACTIVE` (else `ERR_IEP_NOT_ACTIVE`). On success the IEP's `special_education_minutes_per_week`, both LRE percentages, and the student's `lre_classification` are recomputed.

When a service reaches `COMPLETED` through the IEP-supersession path described in §3.5, the parent IEP must already have transitioned to `SUPERSEDED`, the service was in `ACTIVE` immediately prior, and `compensatory_minutes_owed` is set to zero — this is the precise rule that distinguishes a clean handoff from a forced suspension.

**Compensatory-service hours.** When a related service is suspended (by any cause), the system identifies every `ServiceSession` on that service that is still in `SCHEDULED` and whose `scheduled_start` is at or before the district's `current_date` at the moment of suspension. These sessions are deemed missed. Each missed session's `scheduled_minutes` is multiplied by the federal make-up multiplier of 1.5; that per-session raw value is rounded half-up to a whole number of minutes; the resulting whole-minute values are summed; and the sum is recorded as `compensatory_minutes_owed` on the service. The rounding order is pinned: each session is rounded to a whole minute first, then the rounded values are summed. The naive alternative — summing the raw 1.5x products and rounding only at the end — produces a different total whenever an odd number of sessions has odd `scheduled_minutes` (each ending in a half-minute), and that alternative is explicitly not used.

**Service sessions.** A `RelatedServiceProvider` schedules a session on an active service by supplying `scheduled_start` and `scheduled_end`, both ISO 8601 UTC datetimes, with `scheduled_end` strictly greater than `scheduled_start` (else `ERR_INVALID_REQUEST`). The server computes `scheduled_minutes` as the floor of the difference between `scheduled_end` and `scheduled_start` measured in seconds, divided by 60 — this formula is pinned. The session is created in `SCHEDULED` and inherits `related_service_id`, `iep_id`, and `student_id` from the path. Two sessions on the same `related_service_id` may not overlap in time; overlap is checked on closed intervals so that adjacency (one session's `scheduled_end` equal to another's `scheduled_start`) counts as a violation, and a conflicting create is rejected with `ERR_SERVICE_SESSION_OVERLAP`.

A `SCHEDULED` session is delivered by supplying `actual_minutes` in the request body, a non-negative integer at most equal to the session's `scheduled_minutes`. Delivery additionally requires that the session be in `SCHEDULED` (else `ERR_SESSION_NOT_SCHEDULED`), that the parent service be in `ACTIVE` (else `ERR_SERVICE_NOT_ACTIVE`), and that the district's `current_date` be at or after `scheduled_start` (else `ERR_SESSION_NOT_DUE_YET`). On success the session moves to `DELIVERED`, the parent service's `total_delivered_minutes` increases by `actual_minutes`, and the service's `utilization_percent` is recomputed.

A `SCHEDULED` session may instead be cancelled. Cancel requires the session to be in `SCHEDULED` (else `ERR_SESSION_NOT_SCHEDULED`); on success the session moves to `CANCELLED` and the parent service's `total_cancelled_minutes` increases by the session's `scheduled_minutes`.

**Service utilization.** The reported `utilization_percent` on a related service is an aggregate metric, computed but not used to gate any transition. The system computes `weeks_active` as the floor of the number of seconds between the service's first activation and either the district's `current_date` or the moment of suspension (whichever comes first), divided by the number of seconds in seven days. The service's `total_prescribed_minutes_to_date` equals the maximum of `weeks_active` and zero, multiplied by `minutes_per_week`. When `total_prescribed_minutes_to_date` is zero, `utilization_percent` is 0.00. Otherwise `utilization_percent` is 100 multiplied by `total_delivered_minutes`, divided by `total_prescribed_minutes_to_date`, rounded half-up to two decimal places.

### 3.7. Goal Progress, Mastery, and Weighted Scoring

The `SpecialEducationTeacher` reports goal progress through `GoalProgressReport` records. Each report is filed for an `ACTIVE` goal on an `ACTIVE` IEP by supplying `reporting_period_index` (a monotone integer from 1 upward identifying the reporting window), `objective_progress` (an array of records, each carrying an `objective_id` and a `progress_percent` integer between 0 and 100 inclusive), and `narrative` (a free-text narrative whose length is between 1 and 2000 characters inclusive). The server stamps `reported_by_user_id` from `X-User-ID` and inherits `iep_goal_id`, `iep_id`, and `student_id` from the path.

Two strict body-shape rules govern progress reports. First, `objective_progress` must include exactly the set of `objective_id` values declared on the parent goal — no missing entries and no extra entries; mismatch is rejected with `ERR_PROGRESS_OBJECTIVE_SET_MISMATCH`. Second, the pair `(iep_goal_id, reporting_period_index)` must be unique system-wide; a duplicate is rejected with `ERR_DUPLICATE_PROGRESS_REPORT`. As a side effect of accepting a valid report, the matching `latest_progress_percent` is updated on each objective of the parent goal, and the goal's `mastery_score` and `mastery_tier` are recomputed.

The `mastery_score` for a goal is a weighted sum across the goal's objectives: each objective contributes its `weight` multiplied by its `latest_progress_percent`, the products are summed, and the total is rounded half-up to two decimal places. The `mastery_tier` is then derived from the rounded score on these pinned boundaries: a score of at least 80.00 yields `MASTERED`; a score of at least 50.00 and strictly less than 80.00 yields `PROGRESSING`; a score strictly less than 50.00 yields `INSUFFICIENT_PROGRESS`. The constraint that the sum of `weight` values on a goal must equal exactly 1.00 (round half-up to two decimal places) guarantees that the maximum possible weighted score is 100.00 — and this is precisely why a simple unweighted average of progress is not used: when objectives have unequal weights, the unweighted average produces a different number, and the system pins the weighted variant. The mastery computation is also retriggered when an IEP amendment is finalized, so that any objective progress changes during the amendment window are reflected in the post-amendment mastery picture.

### 3.8. Least Restrictive Environment Reporting

The LRE percentages on an IEP are recomputed whenever a related service activates, suspends, resumes, or completes, whenever an IEP transitions from `DRAFT` to `ACTIVE`, and whenever an IEP amendment is finalized. The numerator for both percentage variants is the sum of `minutes_per_week` over every `RelatedService` on this IEP that is currently in `ACTIVE` and whose `location_setting` is either `PULL_OUT` or `COMMUNITY` (services delivered as `PUSH_IN` happen inside the regular classroom and do not contribute). The two variants share this same numerator but differ in their denominator.

`lre_percentage_instructional` is 100 multiplied by the pull-out-minutes numerator, divided by the IEP's `total_instructional_minutes_per_week`, rounded half-up to two decimal places. This is the canonical value used to classify the student. `lre_percentage_school_day` is 100 multiplied by the same numerator, divided by the IEP's `total_school_day_minutes_per_week`, rounded half-up to two decimal places. Because `total_school_day_minutes_per_week` includes non-instructional time such as lunch and recess, it is greater than or equal to `total_instructional_minutes_per_week`, and so `lre_percentage_school_day` is less than or equal to `lre_percentage_instructional` for any identical numerator. The school-day-basis variant is reported alongside the instructional-basis variant but is not used for classification.

The student's `lre_classification` is determined by `lre_percentage_instructional` alone on these pinned inclusive boundaries: if the percentage is at most 20.00, the classification is `LRE_A` (full inclusion, since the student spends at least 80% inside the regular classroom); if the percentage is greater than 20.00 and at most 60.00, the classification is `LRE_B` (resource setting, since the student spends between 40% and 80% inside the regular classroom); otherwise the classification is `LRE_C` (separate setting, since the student spends less than 40% inside the regular classroom). Both variants are computed from identical pull-out minutes — same inputs, two valid algorithms, different outputs — but classification is keyed exclusively to the instructional-basis value. An IEP exposes both variants together along with the classification and the pull-out-minutes numerator (reported as `total_sped_minutes`) through a dedicated read capability, while the standard IEP read returns the same percentage values inline on the IEP resource.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including state transitions, action endpoints, and the clock-advance capability — return `200 OK`. Read operations return `200 OK`.

| Method | Path                                                                                                                | Description                                                                       | Authorized Role(s)                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| POST   | `/districts`                                                                                                        | Create a District                                                                 | `DistrictAdmin`                                                                                 |
| GET    | `/districts/{districtId}`                                                                                           | Get a District                                                                    | `DistrictAdmin`, `SchoolPsychologist`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `Parent` |
| POST   | `/districts/{districtId}/clock/advance`                                                                             | Advance the deterministic clock                                                   | `DistrictAdmin`                                                                                 |
| POST   | `/districts/{districtId}/students`                                                                                  | Create a Student                                                                  | `DistrictAdmin`                                                                                 |
| GET    | `/districts/{districtId}/students`                                                                                  | List Students (filterable by `triennial_status`, `lre_classification`)            | `DistrictAdmin`, `SchoolPsychologist`, `SpecialEducationTeacher`, `RelatedServiceProvider`           |
| GET    | `/districts/{districtId}/students/{studentId}`                                                                      | Get a Student                                                                     | `DistrictAdmin`, `SchoolPsychologist`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `Parent` |
| POST   | `/districts/{districtId}/students/{studentId}/eligibility-evaluations`                                              | Create an EligibilityEvaluation                                                   | `SchoolPsychologist`                                                                            |
| POST   | `/districts/{districtId}/students/{studentId}/eligibility-evaluations/{evaluationId}/request-consent`               | Move an evaluation from REQUESTED to CONSENT_PENDING; auto-create gating consent  | `SchoolPsychologist`                                                                            |
| POST   | `/districts/{districtId}/students/{studentId}/eligibility-evaluations/{evaluationId}/finalize`                      | Finalize an evaluation as ELIGIBLE or INELIGIBLE                                  | `SchoolPsychologist`                                                                            |
| GET    | `/districts/{districtId}/students/{studentId}/eligibility-evaluations`                                              | List evaluations (filterable by `status`)                                         | `DistrictAdmin`, `SchoolPsychologist`, `SpecialEducationTeacher`, `Parent`                       |
| GET    | `/districts/{districtId}/students/{studentId}/eligibility-evaluations/{evaluationId}`                               | Get an evaluation                                                                 | `DistrictAdmin`, `SchoolPsychologist`, `SpecialEducationTeacher`, `Parent`                       |
| POST   | `/districts/{districtId}/students/{studentId}/parental-consents`                                                    | Create a ParentalConsent (IEP_IMPLEMENTATION or RELATED_SERVICE scope)            | `SpecialEducationTeacher`, `RelatedServiceProvider`                                              |
| POST   | `/districts/{districtId}/students/{studentId}/parental-consents/{consentId}/approve`                                | Approve a PENDING consent                                                         | `Parent`                                                                                        |
| POST   | `/districts/{districtId}/students/{studentId}/parental-consents/{consentId}/reject`                                 | Reject a PENDING consent                                                          | `Parent`                                                                                        |
| POST   | `/districts/{districtId}/students/{studentId}/parental-consents/{consentId}/withdraw`                               | Withdraw an APPROVED consent                                                      | `Parent`                                                                                        |
| GET    | `/districts/{districtId}/students/{studentId}/parental-consents`                                                    | List consents (filterable by `scope`, `status`)                                   | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `SchoolPsychologist`, `Parent` |
| POST   | `/districts/{districtId}/students/{studentId}/ieps`                                                                 | Create a DRAFT IEP                                                                | `SpecialEducationTeacher`                                                                       |
| GET    | `/districts/{districtId}/students/{studentId}/ieps`                                                                 | List IEPs (filterable by `status`)                                                | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `SchoolPsychologist`, `Parent` |
| GET    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}`                                                         | Get an IEP                                                                        | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `SchoolPsychologist`, `Parent` |
| GET    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/lre-summary`                                             | Get both LRE percentage variants plus classification and `total_sped_minutes`     | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `SchoolPsychologist`, `Parent` |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/activate`                                                | Activate a DRAFT IEP                                                              | `SpecialEducationTeacher`                                                                       |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/begin-amendment`                                         | Begin an amendment on an ACTIVE IEP                                               | `SpecialEducationTeacher`                                                                       |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/finalize-amendment`                                      | Finalize an amendment, returning to ACTIVE                                        | `SpecialEducationTeacher`                                                                       |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/goals`                                                   | Add a goal to a DRAFT or AMENDMENT_PENDING IEP                                    | `SpecialEducationTeacher`                                                                       |
| GET    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/goals`                                                   | List goals on an IEP (filterable by `status`, `domain`)                           | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `SchoolPsychologist`, `Parent` |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/goals/{goalId}/close`                                    | Close an ACTIVE goal as MET or NOT_MET                                            | `SpecialEducationTeacher`                                                                       |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/goals/{goalId}/progress-reports`                         | File a goal progress report                                                       | `SpecialEducationTeacher`                                                                       |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services`                                        | Propose a related service                                                         | `SpecialEducationTeacher`                                                                       |
| GET    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services`                                        | List related services on an IEP (filterable by `status`, `service_type`)          | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `Parent`                   |
| PUT    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services/{serviceId}/activate`                   | Activate a PROPOSED related service                                               | `RelatedServiceProvider`                                                                        |
| PUT    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services/{serviceId}/suspend`                    | Suspend an ACTIVE related service                                                 | `RelatedServiceProvider`                                                                        |
| PUT    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services/{serviceId}/resume`                     | Resume a SUSPENDED related service                                                | `RelatedServiceProvider`                                                                        |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services/{serviceId}/sessions`                   | Schedule a service session                                                        | `RelatedServiceProvider`                                                                        |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services/{serviceId}/sessions/{sessionId}/deliver` | Mark a session DELIVERED                                                          | `RelatedServiceProvider`                                                                        |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/related-services/{serviceId}/sessions/{sessionId}/cancel`  | Cancel a SCHEDULED session                                                        | `RelatedServiceProvider`                                                                        |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/transition-plan`                                         | Create a DRAFT TransitionPlan                                                     | `SpecialEducationTeacher`                                                                       |
| POST   | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/transition-plan/finalize`                                | Finalize a DRAFT TransitionPlan                                                   | `SpecialEducationTeacher`                                                                       |
| GET    | `/districts/{districtId}/students/{studentId}/ieps/{iepId}/transition-plan`                                         | Get the TransitionPlan for an IEP                                                 | `DistrictAdmin`, `SpecialEducationTeacher`, `RelatedServiceProvider`, `Parent`                   |

## 5. Error Code Catalogue

| Error ID                                          | HTTP Status Code     |
| ------------------------------------------------- | -------------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`      | 400 Bad Request      |
| `ERR_INVALID_REQUEST`                             | 400 Bad Request      |
| `ERR_CROSS_STUDENT_REFERENCE`                     | 400 Bad Request      |
| `ERR_OBJECTIVE_WEIGHTS_INVALID`                   | 400 Bad Request      |
| `ERR_PROGRESS_OBJECTIVE_SET_MISMATCH`             | 400 Bad Request      |
| `ERR_TRANSITION_INVITATIONS_MISSING`              | 400 Bad Request      |
| `ERR_INSUFFICIENT_PERMISSIONS`                    | 403 Forbidden        |
| `ERR_PARENT_OWNERSHIP_MISMATCH`                   | 403 Forbidden        |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION`             | 403 Forbidden        |
| `ERR_DISTRICT_NOT_FOUND`                          | 404 Not Found        |
| `ERR_STUDENT_NOT_FOUND`                           | 404 Not Found        |
| `ERR_EVALUATION_NOT_FOUND`                        | 404 Not Found        |
| `ERR_CONSENT_NOT_FOUND`                           | 404 Not Found        |
| `ERR_IEP_NOT_FOUND`                               | 404 Not Found        |
| `ERR_GOAL_NOT_FOUND`                              | 404 Not Found        |
| `ERR_SERVICE_NOT_FOUND`                           | 404 Not Found        |
| `ERR_SESSION_NOT_FOUND`                           | 404 Not Found        |
| `ERR_TRANSITION_PLAN_NOT_FOUND`                   | 404 Not Found        |
| `ERR_PROGRESS_REPORT_NOT_FOUND`                   | 404 Not Found        |
| `ERR_VERSION_MISMATCH`                            | 409 Conflict         |
| `ERR_DUPLICATE_PROGRESS_REPORT`                   | 409 Conflict         |
| `ERR_SERVICE_SESSION_OVERLAP`                     | 409 Conflict         |
| `ERR_IEP_PERIOD_OVERLAP`                          | 409 Conflict         |
| `ERR_EVALUATION_NOT_REQUESTED`                    | 409 Conflict         |
| `ERR_EVALUATION_NOT_IN_PROGRESS`                  | 409 Conflict         |
| `ERR_CONSENT_NOT_PENDING`                         | 409 Conflict         |
| `ERR_CONSENT_NOT_APPROVED`                        | 409 Conflict         |
| `ERR_IEP_NOT_DRAFT`                               | 409 Conflict         |
| `ERR_IEP_NOT_ACTIVE`                              | 409 Conflict         |
| `ERR_IEP_NOT_AMENDMENT_PENDING`                   | 409 Conflict         |
| `ERR_IEP_NOT_AMENDABLE_FOR_TRANSITION`            | 409 Conflict         |
| `ERR_IEP_NO_GOALS`                                | 409 Conflict         |
| `ERR_IEP_MEETING_NOT_HELD`                        | 409 Conflict         |
| `ERR_GOAL_NOT_ACTIVE`                             | 409 Conflict         |
| `ERR_GOAL_NOT_MASTERED`                           | 409 Conflict         |
| `ERR_SERVICE_NOT_PROPOSED`                        | 409 Conflict         |
| `ERR_SERVICE_NOT_ACTIVE`                          | 409 Conflict         |
| `ERR_SERVICE_NOT_SUSPENDED`                       | 409 Conflict         |
| `ERR_SESSION_NOT_SCHEDULED`                       | 409 Conflict         |
| `ERR_SESSION_NOT_DUE_YET`                         | 409 Conflict         |
| `ERR_TRANSITION_PLAN_NOT_DRAFT`                   | 409 Conflict         |
| `ERR_STUDENT_NOT_ELIGIBLE`                        | 409 Conflict         |
| `ERR_IEP_CONSENT_NOT_APPROVED`                    | 409 Conflict         |
| `ERR_SERVICE_CONSENT_NOT_APPROVED`                | 409 Conflict         |
| `ERR_TRANSITION_PLAN_REQUIRED`                    | 409 Conflict         |
| `ERR_IEP_ALREADY_ACTIVE`                          | 409 Conflict         |
| `ERR_SERVICE_TYPE_ALREADY_ACTIVE`                 | 409 Conflict         |
| `ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME`   | 422 Unprocessable Entity |
