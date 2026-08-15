# Behavioral Intervention Team & Care Referral API — Product Requirements Document

## 1. Introduction

A campus Behavioral Intervention Team (BIT) sits at the intersection of student affairs, counseling, residence life, and campus safety. Faculty and peers observe worrying behavior long before it becomes a crisis, but today those observations travel by hallway conversation and email thread, with no shared record of what was seen, no consistent way to weigh severity, and no auditable trail of who was told what. This document specifies the Behavioral Intervention Team & Care Referral API, the system of record for that entire pipeline: intake of concern reports, rubric-driven risk triage, intervention planning under segregated approval, mandated assessment with a leave-of-absence decision cascade, re-entry evaluation with conditions, scheduled follow-up, and — because a CARE team that cannot prove its patterns cannot ask for resources — aggregate trend reporting by academic term. All resources are exposed under the `/bit` mount.

Two design tensions shape every workflow below. The first is that the people who request an action must never be the people who approve it: the chair who orders a mandated assessment cannot record its outcome, the dean who granted a leave cannot rule on the same student's return, and the case manager who drafts a plan cannot approve it. The second is that student records are partitioned by office, and information crosses those partitions only through explicit, time-boxed disclosure grants — with exactly one emergency exception when a case's assessed risk reaches its most severe tier. The system also runs on a logical clock rather than wall-clock time, so that deadlines, grace periods, and expiry sweeps are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The seven recognized roles are `Reporter`, `CaseManager`, `BITChair`, `CounselingEvaluator`, `DeanOfStudents`, `PrivacyOfficer`, and `SystemAdmin`. A request with either header missing, with a role string outside this set, or — for an entity-backed role — with an `X-User-ID` that does not resolve to an existing staff record is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six of the seven roles are entity-backed by the staff roster. When `X-User-Role` is `Reporter`, `CaseManager`, `BITChair`, `CounselingEvaluator`, `DeanOfStudents`, or `PrivacyOfficer`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a staff member — a report's `reporter_id`, a case's `assigned_case_manager_id`, a plan's `drafted_by`, an assessment's `evaluator_id` or `ordered_by`, a decision's `requested_by` or `decided_by` — compare that foreign-key field against `X-User-ID`. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

All twelve resource types in this API — students, staff members, concern reports, care cases, risk scorings, intervention plans, mandated assessments, leave decisions, re-entry evaluations, follow-up check-ins, disclosure grants, and trend reports — share one set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at its initial value on creation and increments by one on every mutation, including mutations caused by cascades rather than direct client writes.

The three-fractional-digit ISO 8601 UTC form is not limited to `created_at` and `updated_at`: every timestamp-valued field carried on any resource — a report's `observed_at`, an assessment's `due_at` and `completed_at`, a check-in's `due_at` and `completed_at`, a case's `closed_at`, a leave decision's or re-entry evaluation's `decided_at`, a disclosure grant's `effective_from` and `expires_at`, a trend report's `window_start` and `window_end` — is serialized in exactly that same form (for example `2026-08-01T00:00:00.000Z`), and client-supplied timestamps are normalized to it on the way out regardless of the precise string the client sent. The `current_utc` returned by the clock endpoint (§2.5) is serialized in this same form as well.

Cascaded mutations count. When drafting a plan or filing a re-entry petition advances the parent case's state, the case's `version` increments and its `updated_at` refreshes even though the client's request never touched the case directly. Clients that cache a case's `version` and later write against it (§2.9) must therefore treat any workflow activity on the case as a version advance.

### 2.5. The Logical Clock and Automated Expiry Sweeps

Every deadline, window, and sweep in this API is evaluated against a server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; the server never silently falls back to the host clock. A `SystemAdmin`-only test-driving capability advances the logical clock: the request carries a `to_iso8601` field with the target instant (ISO 8601 UTC), and the response returns the resulting `current_utc` string.

Advancing the clock applies three sweeps, each defined fully in §3 but summarized here so the clock's semantics are self-contained. First, any mandated assessment still `SCHEDULED` whose `due_at` is now in the past transitions to `EXPIRED` and triggers the same leave-decision cascade as a `NOT_CLEARED` outcome. Second, any follow-up check-in still `SCHEDULED` whose `due_at` passed more than one full day ago transitions to `MISSED`, resets the case's stability counter, and spawns a successor check-in. Third, any disclosure grant in `APPROVED` whose `expires_at` has been reached or passed transitions to `EXPIRED`. Throughout this document, the word "now" always means the logical clock's current instant.

### 2.6. Risk Quantification and Numeric Precision

All computed scores and percentages in the system — a risk scoring's `score`, a trend report's `closure_rate_pct`, `avg_days_to_close`, and each share inside `category_distribution` — are recorded at exactly one decimal place using round-half-up rounding. Stability tracking (`consecutive_stable_checkins`) and report counts (`total_cases`, `closed_in_window`) are integers. Follow-up scheduling operates at whole-day granularity: a check-in's `due_at` is always a base instant plus an exact whole number of days. A case's `current_risk_score` and `current_risk_tier` remain null until the case has been scored for the first time; consumers must not treat an unscored case as a zero-risk case.

### 2.7. Privacy Partitioning and Cross-Office Disclosure

Reading a care case is the most tightly governed operation in the API. Three outcomes are possible: a full view, a redacted view, or rejection. A `BITChair`, `PrivacyOfficer`, or `DeanOfStudents` always receives the full view. A `CaseManager` receives the full view only when they are the case's current `assigned_case_manager_id`. A `CounselingEvaluator` receives the full view only when they are the `evaluator_id` on a `SCHEDULED` or `COMPLETED` mandated assessment for that case. Anyone else authorized to attempt the read — including a `Reporter` — must hold an `APPROVED`, unexpired disclosure grant issued to their own office for that case: a grant whose `scope` is `FULL_RECORD` yields the full view, while `SUMMARY_ONLY` or `SAFETY_MINIMUM` yields the redacted view. The redacted view contains exactly five fields: `id`, `student_id`, `status`, `current_risk_tier`, and `current_risk_score`. When no role-based path and no qualifying grant exists, the read is rejected with `ERR_PRIVACY_SCOPE_INSUFFICIENT` (HTTP 403).

Disclosure between offices is always bounded in time. A grant's window is half-open: it takes effect at `effective_from` (inclusive) and ends at `expires_at` (exclusive), and the sweeps of §2.5 retire it at the boundary. The mechanics of requesting, approving, denying, revoking, and expiring grants — and the single emergency exception that bypasses PrivacyOfficer approval — are specified in §3.2 and §3.7.

### 2.8. Segregation of Duties and Caseload Ownership

Four steps in the case lifecycle are segregated so that no individual can both initiate and ratify the same decision. A plan's approver must differ from its `drafted_by`. The evaluator recording a mandated assessment's outcome must be the assessment's assigned `evaluator_id` and must differ from its `ordered_by`. A leave decision's decider must differ from its `requested_by`. A re-entry evaluation's decider must differ from the `decided_by` of the leave decision the student is returning from. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Three ownership rules sit beside the segregation rules. Submitting a draft plan for approval is permitted only to the case manager whose `id` matches the plan's `drafted_by`; anyone else is rejected with `ERR_FORBIDDEN`. Completing a follow-up check-in is permitted only to the staff member whose `id` matches the case's `assigned_case_manager_id`; anyone else is rejected with `ERR_NOT_ASSIGNED_CASE_MANAGER` (HTTP 403). A `Reporter` reading a concern report may read only reports whose `reporter_id` matches their own `X-User-ID`; reading another reporter's report is rejected with `ERR_FORBIDDEN`.

### 2.9. Optimistic Concurrency Control on Case-Mutating Writes

Two write operations are guarded by optimistic concurrency control against the `CareCase`, and both name the same field. Drafting an intervention plan and filing a re-entry petition each require the request body to carry `expected_case_version`, holding the `version` of the case as the client last observed it. If the case's current `version` has advanced past that observed value — because any workflow event on the case has mutated it since — the write is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the client from building a plan or petition on a state of the case it never saw. No other endpoint accepts a version field; all other mutations apply without an OCC check.

### 2.10. Order of Validation

When several rules could reject the same request, the server evaluates them in a fixed order and reports the first failure; a failure at an earlier rank always masks every later rank. The ranks, in evaluation order, are:

1. **Request context** — both headers present, the role declared, and entity-backed identities resolving to a real staff record; failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization** — the caller's role listed for the endpoint; failures yield `ERR_FORBIDDEN` (403).
3. **Existence** — path identifiers validated left to right, then body foreign-key targets (`student_id`, `case_id`, `case_manager_id`, `evaluator_id`, `related_report_id`); failures yield `ERR_NOT_FOUND` (404).
4. **Optimistic concurrency** — `expected_case_version` agreement on the two endpoints that declare it; failures yield `ERR_STALE_CASE_VERSION` (412).
5. **State-machine preconditions** — the target transition's state requirements; failures yield the appropriate member of the 409 state family: `ERR_REPORT_NOT_UNDER_REVIEW`, `ERR_CASE_NOT_TRIAGEABLE`, `ERR_PLAN_NOT_DRAFT`, `ERR_PLAN_NOT_PENDING_APPROVAL`, `ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL`, `ERR_CASE_NOT_PLAN_ACTIVE`, `ERR_CASE_NOT_MANDATED_ASSESSMENT`, `ERR_CASE_NOT_ON_LEAVE`, `ERR_ASSESSMENT_NOT_SCHEDULED`, `ERR_DECISION_NOT_PENDING`, `ERR_CHECKIN_NOT_SCHEDULED`, `ERR_GRANT_NOT_REQUESTED`, or `ERR_GRANT_NOT_APPROVED`.
6. **Privacy scope** — the case-read gating of §2.7; failures yield `ERR_PRIVACY_SCOPE_INSUFFICIENT` (403).
7. **Segregation and ownership** — the §2.8 rules; failures yield `ERR_SEGREGATION_OF_DUTIES`, `ERR_NOT_ASSIGNED_CASE_MANAGER`, or `ERR_FORBIDDEN` (all 403).
8. **Enrollment gate** — new concern reports only for students who are not withdrawn; failures yield `ERR_STUDENT_NOT_ACTIVE` (409).
9. **Field and constraint checks** — rubric range, scoring-mode consistency, enum and required-field validity, non-empty `objectives`, evaluator distinct from orderer, disclosure and trend window sanity, non-empty re-entry `conditions`, closure eligibility, open-plan exclusion, and pending-petition exclusion; failures yield `ERR_RUBRIC_SCORE_OUT_OF_RANGE`, `ERR_SCORING_MODE_INVALID`, `ERR_VALIDATION`, `ERR_EVALUATOR_SAME_AS_ORDERER`, `ERR_DISCLOSURE_WINDOW_INVALID`, `ERR_TREND_WINDOW_INVALID`, or `ERR_CONDITIONS_REQUIRED` (all 400), or `ERR_CASE_NOT_CLOSABLE`, `ERR_OPEN_PLAN_EXISTS`, or `ERR_REENTRY_ALREADY_PENDING` (all 409).
10. **Temporal windows** — the assessment due-window and slot-occupation rules and the disclosure overlap rule; failures yield `ERR_ASSESSMENT_DUE_WINDOW_VIOLATION` (422), `ERR_ASSESSMENT_ALREADY_PENDING` (409), or `ERR_DISCLOSURE_WINDOW_OVERLAP` (409).
11. **Cross-reference integrity** — a linked prior report must belong to the same student; failures yield `ERR_RELATED_REPORT_STUDENT_MISMATCH` (422).

The practical consequence: a stale `expected_case_version` surfaces as `ERR_STALE_CASE_VERSION` even when the request would also fail a state check, and a missing student surfaces as `ERR_NOT_FOUND` even when the payload's category is invalid. A further consequence follows for the creation operations that themselves advance the case's state: because drafting a plan moves a `TRIAGED` case to `PLAN_DRAFTING` (§3.3), ordering an assessment moves a `PLAN_ACTIVE` case to `MANDATED_ASSESSMENT` (§3.5), and filing a petition moves an `ON_LEAVE` case to `REENTRY_REVIEW` (§3.6), a second identical creation request against the same case fails at the rank-5 state gate (`ERR_CASE_NOT_PLAN_ACTIVE` or `ERR_CASE_NOT_ON_LEAVE`) before the rank-9 open-plan or pending-petition exclusion — or the rank-10 slot-occupation rule — is ever reached, so those duplicate-resource errors are observable only while the case still sits in the gating state. Each workflow subsection below names the checks relevant to its operations; this ladder decides which one the caller sees first.

## 3. Business Logic & Workflows

### 3.1. Rosters, Enrollment, and Concern Intake

Nothing in the BIT workflow exists until the campus roster does. A `SystemAdmin` registers each student with a campus-unique `external_ref` (the student number) and a `full_name`; the record's `enrollment_status` begins at `ENROLLED`. Thereafter `enrollment_status` moves among three values — `ENROLLED`, `LEAVE_OF_ABSENCE`, and `WITHDRAWN` — but only the first and third are under administrative control: a `SystemAdmin` may correct a record between `ENROLLED` and `WITHDRAWN` in either direction, and each such correction increments the student's `version`. The `LEAVE_OF_ABSENCE` value is owned exclusively by the leave and re-entry cascades of §3.6; a direct administrative edit attempting to set it is rejected as an invalid value with `ERR_VALIDATION`. Staff are registered the same way, with a `full_name`, a home `office` drawn from `FACULTY_AFFAIRS`, `RESIDENCE_LIFE`, `COUNSELING_CENTER`, `DEAN_OF_STUDENTS`, `BIT_OFFICE`, `CAMPUS_SAFETY`, or `PRIVACY_OFFICE`, and an `active` flag that defaults to true. A staff member's `office` is not decorative: it drives the privacy-scope checks of §2.7 and names the target of every disclosure grant in §3.7.

Intake begins when a `Reporter` — a faculty or peer staff member — submits a concern report naming the subject by `student_id`, choosing a primary `category` (`ACADEMIC_DISTRESS`, `BEHAVIORAL_THREAT`, `SELF_HARM_RISK`, `SUBSTANCE_CONCERN`, or `WELLBEING_GENERAL`), writing a free-text `narrative` of the observed behavior, and timestamping the observation in `observed_at` (ISO 8601 UTC). An optional `related_report_id` may thread the new report to a prior report, but only when that prior report concerns the same student; a cross-student link is rejected with `ERR_RELATED_REPORT_STUDENT_MISMATCH` (HTTP 422). Two guards fire before the report exists: the subject student must exist (`ERR_NOT_FOUND`), and a report about a `WITHDRAWN` student is rejected with `ERR_STUDENT_NOT_ACTIVE` (HTTP 409) — a rejection that, per the §2.10 ladder, the caller sees before any cross-reference mismatch. A submitted report starts in `SUBMITTED`, with `reporter_id` captured from the caller's `X-User-ID`, `care_case_id` and `review_rationale` both null, and — while `related_report_id` defaults to null when omitted — the category is not merely administrative: it feeds the trend distribution of §3.8. A `Reporter` may later read back only their own reports (§2.8), while `BITChair`, `CaseManager`, and `PrivacyOfficer` roles may read any report; list views for the triage team can be filtered by `student_id`, `reporter_id`, `related_report_id`, `care_case_id`, or `status`.

Triage of the report itself is the `BITChair`'s exclusive province and moves through a short state machine: `SUBMITTED` → `UNDER_REVIEW` → either `ACCEPTED` or `CLOSED_NO_ACTION`, both terminal. Starting review on a report that is not `SUBMITTED` is rejected with `ERR_REPORT_NOT_UNDER_REVIEW` — the same code that guards the other two transitions, which both require `UNDER_REVIEW`. Acceptance carries a `case_manager_id` payload that must reference an existing staff member (`ERR_NOT_FOUND`, and per the ladder this existence check fires before the report's state check), and it resolves one of two ways. If the student already has a care case in any status other than `CLOSED`, the report is simply linked: its `care_case_id` is set to that case's `id`, and the case itself is left entirely untouched — state unchanged, `version` unchanged, manager assignment unchanged. Otherwise acceptance creates a new `CareCase` in `INTAKE`, copying the report's `student_id`, recording `opened_from_report_id` as the report being accepted, and assigning the referenced case manager as `assigned_case_manager_id`; the report's `care_case_id` then points at the new case. Either way the report lands in `ACCEPTED`. Closing without action instead records the chair's `rationale` into the report's `review_rationale` and lands the report in `CLOSED_NO_ACTION`.

Case-manager assignment is not frozen at acceptance. A `BITChair` may assign or reassign a case's manager at any time by supplying a fresh `case_manager_id`; the case's `assigned_case_manager_id` updates and its `version` increments by one. Reassignment matters most to §3.4, because only the currently assigned manager may complete check-ins.

### 3.2. Risk Scoring and the Triage Rubric

A case in `INTAKE` is a holding pen, not a plan; it becomes workable only after its first risk scoring. Scoring is performed exclusively by a `BITChair`, whose `X-User-ID` is recorded as the scoring's `scored_by`, and each scoring names its `case_id`, a `mode` of `INITIAL` or `REASSESSMENT`, four rubric dimensions, and a free-text `rationale` justifying the numbers. The four dimensions — `harm_to_self`, `harm_to_others`, `academic_disruption`, and `substance_involvement` — are each integers from 0 to 25 inclusive; any dimension outside that range or non-integral is rejected with `ERR_RUBRIC_SCORE_OUT_OF_RANGE` (HTTP 400). Mode must agree with history: `INITIAL` is valid only when no prior scoring exists for the case, and `REASSESSMENT` is valid only when at least one does; a mismatch is rejected with `ERR_SCORING_MODE_INVALID` (HTTP 400). State must agree too: scoring requires the case in `INTAKE` (for `INITIAL`) or `TRIAGED` (for `REASSESSMENT`), with anything else rejected as `ERR_CASE_NOT_TRIAGEABLE` (HTTP 409).

The score is computed in two stages. First, a raw base is formed as four times the weighted sum of the dimensions: `harm_to_self` contributes 35 percent of the weight, `harm_to_others` contributes 35 percent, `academic_disruption` contributes 15 percent, and `substance_involvement` contributes 15 percent; because each dimension tops out at 25, the base runs from 0 to 100. An `INITIAL` scoring records `score` as exactly that base, rounded half-up to one decimal place. A `REASSESSMENT` blends the new base with the case's immediately preceding scoring: six-tenths of the new base plus four-tenths of the previous scoring's `score`, rounded half-up to one decimal place — so identical dimension inputs produce a different reassessment score whenever the previous score differs from the new base. The recorded `tier` derives from the score by threshold: a score of 80 or higher is `IMMINENT`, 60 or higher is `HIGH`, 30 or higher is `MODERATE`, and anything below 30 is `LOW`. One ratchet overrides the thresholds: if the case's `current_risk_tier` immediately before this scoring was `IMMINENT` and the threshold-derived tier from the new score would be `MODERATE` or `LOW`, the recorded tier is floored at `HIGH` — a case at the most severe tier cannot de-escalate below `HIGH` in a single reassessment.

Every completed scoring writes the computed `score` and `tier` back onto the case as `current_risk_score` and `current_risk_tier` — both null until this first write — and increments the case's `version`. The first scoring also advances the case from `INTAKE` to `TRIAGED`; reassessments are a self-loop that leave the case in `TRIAGED`. Scoring history is reviewable through list views filterable by `case_id` or `scored_by`.

A tier of `IMMINENT` is the one place the privacy partition of §2.7 yields automatically. When an `INITIAL` scoring lands at `IMMINENT`, or when a `REASSESSMENT` crosses into `IMMINENT` from any lower tier, the system creates two disclosure grants with no human in the loop: one to `COUNSELING_CENTER` and one to `CAMPUS_SAFETY`, each with `scope` `SAFETY_MINIMUM`, each created directly in `APPROVED` status with `auto_approved` set to true, `requested_by` and `approved_by` left null, the window opening at the moment of creation, and `expires_at` exactly 72 hours later. If the case's previous tier was already `IMMINENT`, a reassessment that keeps it there creates no new grants — the exception fires on the crossing, not on the continuation.

### 3.3. Intervention Planning: Drafting, Approval, and Supersedure

Once a case is `TRIAGED` — or while it is `PLAN_ACTIVE`, when the team revises a working plan — a `CaseManager` drafts an intervention plan. The creation request names the `case_id`, carries the OCC guard `expected_case_version` (§2.9), and supplies `objectives` (a list of objective strings that must be non-empty; an empty list or other malformed payload is rejected with `ERR_VALIDATION`) plus `success_criteria`, the measurable closure text the team will later test the case against. Three rejections guard the draft, surfacing in the §2.10 order: a stale `expected_case_version` yields `ERR_STALE_CASE_VERSION` (412) before any state judgment; a case in `INTAKE` yields `ERR_CASE_NOT_TRIAGEABLE`, and a case in any other state besides `TRIAGED` or `PLAN_ACTIVE` yields `ERR_CASE_NOT_PLAN_ACTIVE` (both 409); and if the case already has a plan in `DRAFT` or `PENDING_APPROVAL`, the draft is refused with `ERR_OPEN_PLAN_EXISTS` (409) — one open drafting effort per case at a time. A created plan starts in `DRAFT` with `drafted_by` taken from the caller's `X-User-ID`, `supersedes_plan_id` null, `reentry_conditions` an empty list, and `revision_note` null. Drafting also mutates the case: a `TRIAGED` case advances to `PLAN_DRAFTING`, while a case already `PLAN_ACTIVE` stays there (the draft is a revision, not a restart), and in both cases the case's `version` increments by one — which is exactly why the OCC guard exists.

The plan then moves through its own review loop. Submitting, permitted only to the drafter (anyone else draws `ERR_FORBIDDEN`), moves `DRAFT` → `PENDING_APPROVAL`; submitting a plan that is not in `DRAFT` draws `ERR_PLAN_NOT_DRAFT`. A `BITChair` reviewing a `PENDING_APPROVAL` plan has two exits. Returning it for revision moves `PENDING_APPROVAL` → `DRAFT` and records the supplied `revision_note` on the plan; the draft-revise loop may repeat as needed. Approval moves `PENDING_APPROVAL` → `ACTIVE` and is the more heavily guarded step, evaluated in order: the plan must be `PENDING_APPROVAL` (`ERR_PLAN_NOT_PENDING_APPROVAL`), the case must be in `PLAN_DRAFTING` or `PLAN_ACTIVE` (`ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL`), and — the §2.8 segregation rule — the approver's `X-User-ID` must differ from the plan's `drafted_by` (`ERR_SEGREGATION_OF_DUTIES`).

Approval's side effects ripple across three aggregates, and every one of them is mandatory. The approved plan becomes `ACTIVE`, and if another plan for the case was `ACTIVE`, that plan is superseded to `SUPERSEDED` (terminal) with the new plan's `supersedes_plan_id` recording its `id`. The case moves `PLAN_DRAFTING` → `PLAN_ACTIVE` — a no-op when the approval ratified a revision on an already-`PLAN_ACTIVE` case — and its `version` increments by one. Finally, follow-up cadence resets: every `SCHEDULED` check-in for the case is `CANCELLED`, and one fresh check-in is created, due exactly the current tier's cadence (§3.4) after the approval instant. Plans are reviewable in list views filterable by `case_id`, `drafted_by`, `supersedes_plan_id`, or `status`. Two further transitions — `ACTIVE` → `SUSPENDED` when a leave is granted, and `SUSPENDED` → `ACTIVE` when re-entry is approved — belong to §3.6, and one more, `ACTIVE` → `SUPERSEDED` on an escalated check-in, belongs to §3.4.

### 3.4. Follow-Up Cadence and Stability Tracking

While a plan is active, the team keeps touching the student on a schedule keyed to the case's current risk tier: an `IMMINENT` case is checked every 2 days, a `HIGH` case every 7 days, a `MODERATE` case every 14 days, and a `LOW` case every 30 days. Five events schedule a check-in: plan approval (§3.3), a denied leave (§3.6), a `STABLE` completion, the `MISSED` sweep, and re-entry approval. Four of the five anchor the new `due_at` to the scheduling moment plus the cadence for the case's `current_risk_tier`; the two exceptions are the `MISSED` sweep, whose successor is anchored to the missed check-in's own `due_at` plus the cadence rather than to the sweep instant, and re-entry approval, which uses a fixed seven-day horizon regardless of tier.

Completing a check-in is the assigned manager's job and nobody else's: the caller's `X-User-ID` must match the case's `assigned_case_manager_id` (`ERR_NOT_ASSIGNED_CASE_MANAGER`), the check-in must still be `SCHEDULED` (`ERR_CHECKIN_NOT_SCHEDULED`), and the case must be `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE`). Completion may happen early — at or before `due_at` — and records an `outcome` of `STABLE` or `ESCALATED` together with a free-text `note`; the check-in lands in `COMPLETED` with `completed_at` set to the completion instant. The two outcomes diverge sharply, and both branches are fully specified. A `STABLE` outcome increments the case's `consecutive_stable_checkins` by one and schedules the successor check-in described above. An `ESCALATED` outcome resets `consecutive_stable_checkins` to zero, creates no successor, supersedes the case's `ACTIVE` plan to `SUPERSEDED`, and pulls the case `PLAN_ACTIVE` → `TRIAGED`, forcing fresh triage before any new plan may be drafted. Check-in history is listable by `case_id` or `status`.

Two system transitions complete the check-in lifecycle. When the logical clock passes more than one full day beyond a `SCHEDULED` check-in's `due_at`, the sweep marks it `MISSED` — `MISSED` is a status, never a recordable completion `outcome` — resets the case's `consecutive_stable_checkins` to zero, and schedules the anchored successor described above. And whenever follow-up cadence is suspended, every `SCHEDULED` check-in for the case is `CANCELLED`: that happens when a leave decision is created for the case (§3.5), when a plan approval resets cadence (§3.3), and when the case closes (§3.8). `COMPLETED`, `MISSED`, and `CANCELLED` are all terminal. Note the interplay with §3.5: ordering a mandated assessment deliberately does not cancel scheduled check-ins — they remain on the calendar and remain sweepable while the case sits in `MANDATED_ASSESSMENT`, even though completion is accepted only in `PLAN_ACTIVE`. A re-entry approval (§3.6) is the third event that zeroes `consecutive_stable_checkins`.

### 3.5. Mandated Assessment and the Leave-Decision Cascade

When the team needs a clinical judgment before it can proceed, a `BITChair` orders a mandated assessment, naming the `case_id`, the `evaluator_id` of the `CounselingEvaluator` who must record the outcome, a `due_at` deadline, and a `rationale` for mandating it. Four checks guard the order, surfacing in §2.10 order: the case must be `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE`); the evaluator must differ from the ordering chair (`ERR_EVALUATOR_SAME_AS_ORDERER`, 400); `due_at` must be strictly later than now and no later than fourteen days from now (`ERR_ASSESSMENT_DUE_WINDOW_VIOLATION`, 422); and no other `SCHEDULED` assessment for the case may occupy the slot — the closed interval from the moment that earlier assessment was ordered through its `due_at` must not cover the current instant (`ERR_ASSESSMENT_ALREADY_PENDING`, 409). A created assessment starts `SCHEDULED` with `ordered_by` taken from the caller's `X-User-ID` and `outcome`, `findings_summary`, and `completed_at` all null; the case advances to `MANDATED_ASSESSMENT` with its `version` incremented by one, and — as §3.4 noted — scheduled check-ins keep running.

Recording the outcome is the assigned evaluator's exclusive act, doubly segregated: the caller's `X-User-ID` must equal the assessment's `evaluator_id` and differ from its `ordered_by`, with any other combination rejected as `ERR_SEGREGATION_OF_DUTIES`. The assessment must still be `SCHEDULED` (`ERR_ASSESSMENT_NOT_SCHEDULED`) and the case still in `MANDATED_ASSESSMENT` (`ERR_CASE_NOT_MANDATED_ASSESSMENT`). The evaluator submits an `outcome` of `CLEARED` or `NOT_CLEARED` with a `findings_summary`, and the two branches diverge completely. `CLEARED` is the short path: the assessment completes — status `COMPLETED`, `completed_at` set — and the case returns to `PLAN_ACTIVE` with `version` incremented by one, leaving the plan and cadence as they were. `NOT_CLEARED` fires a four-link cascade in strict order: first the assessment completes with outcome `NOT_CLEARED`; second, caused by the first, the case moves to `LEAVE_DECISION` with `version` incremented by one; third, caused by the second, the system creates a `LeaveDecision` in `PENDING` naming the case and recording the assessment's `ordered_by` as the decision's `requested_by`, with `decided_by`, `decision`, `rationale`, and `decided_at` all null for now; fourth, caused by the third, the pending leave decision suspends follow-up cadence, cancelling every `SCHEDULED` check-in for the case.

The clock can fire the same cascade without the evaluator. When a sweep (§2.5) finds an assessment still `SCHEDULED` with `due_at` in the past, the assessment transitions to `EXPIRED` — terminal, like `COMPLETED` — and the identical four-link cascade follows: case to `LEAVE_DECISION`, `PENDING` leave decision created with the same `requested_by`, scheduled check-ins cancelled. An expired assessment is thus treated with exactly the severity of a non-clearance. Assessment history is listable by `case_id`, `ordered_by`, `evaluator_id`, or `status`.

### 3.6. Leave of Absence, Re-Entry Petition, and Return to Campus

A `PENDING` leave decision belongs to the `DeanOfStudents`, who submits a `decision` of `GRANT_LEAVE` or `DENY_LEAVE` with a `rationale`. The decision must still be `PENDING` (`ERR_DECISION_NOT_PENDING`), and segregation forbids the dean who decides from being the `requested_by` chair who triggered the underlying assessment (`ERR_SEGREGATION_OF_DUTIES`). The two branches again diverge fully. Granting leave records `decided_by` and `decided_at`, moves the decision to `GRANTED`, and then propagates outward: the case moves `LEAVE_DECISION` → `ON_LEAVE` with `version` incremented by one, the student's `enrollment_status` becomes `LEAVE_OF_ABSENCE` — one of the two cascades that own that value — and the case's `ACTIVE` plan, if any, is `SUSPENDED`. Denying leave moves the decision to `DENIED` (with `decided_by` and `decided_at` likewise recorded), returns the case to `PLAN_ACTIVE` with `version` incremented by one, and restarts follow-up cadence with a fresh check-in due exactly the current tier's cadence after the decision. Both `GRANTED` and `DENIED` are terminal. Leave decisions are listable by `case_id`, `requested_by`, `decided_by`, or `status`.

A student on leave returns only through petition. A `CaseManager` files a re-entry evaluation against an `ON_LEAVE` case (`ERR_CASE_NOT_ON_LEAVE` otherwise), carrying `case_id`, the OCC guard `expected_case_version` (§2.9 — a stale observation is `ERR_STALE_CASE_VERSION`, 412, and surfaces before the state check), and a `petition_summary` of the readiness evidence. Only one petition may be live at a time: if a `PENDING` re-entry evaluation already exists for the case, the filing is rejected with `ERR_REENTRY_ALREADY_PENDING` (409). A filed petition is created in `PENDING` with `petitioned_by` taken from the caller's `X-User-ID`, `leave_decision_id` set to the `GRANTED` leave decision under which the student is on leave, and `decided_by`, `outcome`, `rationale`, and `decided_at` null; the case moves `ON_LEAVE` → `REENTRY_REVIEW` with `version` incremented by one.

The re-entry decision again belongs to the `DeanOfStudents`, with one extra twist of segregation: the deciding dean must differ from the `decided_by` of the original leave decision, so the dean who sent the student home cannot be the dean who readmits them (`ERR_SEGREGATION_OF_DUTIES`). The decision payload carries an `outcome` and a `rationale`, plus `conditions`. Approving requires `outcome` `APPROVED_WITH_CONDITIONS` together with a non-empty `conditions` list — an approval with empty or missing conditions is rejected with `ERR_CONDITIONS_REQUIRED` (400) — and it fires the widest cascade in the system: the evaluation lands in `APPROVED` with `decided_by`, `decided_at`, and the approved `conditions` recorded; the case returns to `PLAN_ACTIVE` with `consecutive_stable_checkins` reset to zero and `version` incremented by one; the student's `enrollment_status` returns to `ENROLLED`; the case's `SUSPENDED` plan is reactivated to `ACTIVE` with its `reentry_conditions` copied from the evaluation's `conditions`; and the first post-re-entry check-in is scheduled at a fixed horizon of exactly seven days from the decision, regardless of tier. Denial is the quiet branch: `outcome` `DENIED` lands the evaluation in `DENIED` and returns the case to `ON_LEAVE` with `version` incremented by one — the re-entry denial loop, leaving the student on leave and free to petition again later. Both `APPROVED` and `DENIED` are terminal for the evaluation. Re-entry evaluations are listable by `case_id`, `petitioned_by`, `decided_by`, `leave_decision_id`, or `status`.

### 3.7. Cross-Office Disclosure Grants and Expiry

Outside the emergency exception of §3.2, information crosses office boundaries only through a disclosure grant. A `CaseManager` requests one by naming the `case_id`, the target `to_office` (one of the seven office values), the `scope`, a window bounded by `effective_from` and `expires_at`, and a `purpose` stating the need-to-know justification; `requested_by` is taken from the caller's `X-User-ID`, and the grant starts in `REQUESTED` with `approved_by` null and `auto_approved` false. The `scope` decides what an approved grant buys at case-read time (§2.7): `FULL_RECORD` opens the unredacted view, while `SUMMARY_ONLY` and `SAFETY_MINIMUM` open only the redacted five-field view. The window is half-open — inclusive at `effective_from`, exclusive at `expires_at` — and two temporal rules guard it: `expires_at` must be later than `effective_from` (`ERR_DISCLOSURE_WINDOW_INVALID`, 400), and the requested window must not intersect any existing `REQUESTED` or `APPROVED` grant for the same `case_id` and `to_office` pair (`ERR_DISCLOSURE_WINDOW_OVERLAP`, 409). Grants are listable by `case_id`, `requested_by`, `approved_by`, `to_office`, or `status`.

Adjudication belongs to the `PrivacyOfficer` and offers three acts. Approving moves `REQUESTED` → `APPROVED` and stamps `approved_by` with the officer's `X-User-ID`; denying moves `REQUESTED` → `DENIED` and records the officer's `rationale`; both require the grant still in `REQUESTED` (`ERR_GRANT_NOT_REQUESTED`). Revoking moves an `APPROVED` grant to `REVOKED` and requires `APPROVED` (`ERR_GRANT_NOT_APPROVED`). Finally, the clock sweep retires any `APPROVED` grant whose `expires_at` has been reached or passed into `EXPIRED`; `DENIED`, `REVOKED`, and `EXPIRED` are all terminal. The §3.2 auto-grants are the only grants that skip this adjudication entirely — they are born `APPROVED`, carry `auto_approved` true, and expire under the same sweep seventy-two hours later.

### 3.8. Case Closure and Aggregate Trend Reporting

Closure is the case's only terminal transition and is deliberately hard to reach. A `BITChair` may close a case only when every element of the eligibility aggregate holds: the case is `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE` otherwise); `consecutive_stable_checkins` is at least three — exactly three qualifies; `current_risk_tier` is `LOW`; no `SCHEDULED` mandated assessment exists for the case; no `PENDING` leave decision exists; and no `PENDING` re-entry evaluation exists. Any failure of the aggregate beyond the state check is rejected as `ERR_CASE_NOT_CLOSABLE` (409). Closure sets the case to `CLOSED`, stamps `closed_at` with the closing instant (null throughout the case's open life), increments `version` by one, and cancels every `SCHEDULED` check-in. Case lists are filterable by `student_id`, `assigned_case_manager_id`, `opened_from_report_id`, or `status`, and the privacy-gated single-case read follows §2.7.

The system's last job is institutional memory. A `SystemAdmin` generates a trend report by naming a `term_code` (an academic-term label such as `2026-FALL`), an inclusive `window_start` and `window_end` — the end must be strictly later than the start, else `ERR_TREND_WINDOW_INVALID` (400) — and a `variant` that selects the inclusion rule. The report is computed immediately and persists its computed fields. `total_cases` counts the input set, where the variant decides membership: `ENTRY_COHORT` includes cases whose `created_at` falls inside the closed window — a cohort analysis of cases opened in the term — while `ACTIVE_IN_WINDOW` includes any case whose `created_at` is on or before `window_end` and which was either never closed or whose `closed_at` is on or after `window_start`, a service-load analysis of everything alive at any point in the term, so identical data yields larger totals and different rates under the second variant. From that set, `closed_in_window` counts cases whose `closed_at` falls inside the closed window; `closure_rate_pct` is one hundred times `closed_in_window` divided by `total_cases`, rounded half-up to one decimal place, and is 0.0 when `total_cases` is zero; and `avg_days_to_close` is the mean, over the closed-in-window cases, of the whole-day span from `created_at` to `closed_at`, rounded half-up to one decimal place, 0.0 when no input-set case closed in the window.

The `category_distribution` map reports each case under the `category` of its opening report — the report named by the case's `opened_from_report_id` — and its rounding order is pinned. Walking the five categories in their declared order, `ACADEMIC_DISTRESS`, `BEHAVIORAL_THREAT`, `SELF_HARM_RISK`, `SUBSTANCE_CONCERN`, then `WELLBEING_GENERAL`, each of the first four shares is one hundred times that category's count divided by `total_cases`, rounded half-up to one decimal place; the last category, `WELLBEING_GENERAL`, receives the residual — one hundred minus the sum of the first four shares, rounded half-up to one decimal place — so the five shares always total 100.0 rather than drifting under independent rounding. When `total_cases` is zero, every share is 0.0. Generated reports are readable by every role.

## 4. Endpoint Definitions

Operations that create a new resource — registering a student or staff member, submitting a concern report, recording a risk scoring, drafting a plan, ordering an assessment, filing a re-entry petition, requesting a disclosure grant, or generating a trend report — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Request bodies, responses, and side effects for each operation are defined by the narratives of §2 and §3; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bit/students` | Register a student record | SystemAdmin |
| GET | `/bit/students/{id}` | Get a student | Reporter, CaseManager, BITChair, CounselingEvaluator, DeanOfStudents, PrivacyOfficer, SystemAdmin |
| PATCH | `/bit/students/{id}` | Administrative enrollment correction (ENROLLED ↔ WITHDRAWN only) | SystemAdmin |
| POST | `/bit/staff` | Register a staff member | SystemAdmin |
| GET | `/bit/staff/{id}` | Get a staff member | Reporter, CaseManager, BITChair, CounselingEvaluator, DeanOfStudents, PrivacyOfficer, SystemAdmin |
| POST | `/bit/concern-reports` | Submit a concern report about a student | Reporter |
| GET | `/bit/concern-reports/{id}` | Get a report (Reporter reads own only) | Reporter, BITChair, CaseManager, PrivacyOfficer |
| GET | `/bit/concern-reports` | List and filter concern reports | BITChair, CaseManager, PrivacyOfficer, DeanOfStudents |
| POST | `/bit/concern-reports/{id}/start-review` | Move a report from SUBMITTED to UNDER_REVIEW | BITChair |
| POST | `/bit/concern-reports/{id}/accept` | Accept a report, linking or creating the student's care case | BITChair |
| POST | `/bit/concern-reports/{id}/close-no-action` | Close a report without opening a case | BITChair |
| GET | `/bit/care-cases/{id}` | Privacy-gated case read (full or redacted view) | Reporter, CaseManager, BITChair, CounselingEvaluator, DeanOfStudents, PrivacyOfficer |
| GET | `/bit/care-cases` | List and filter care cases | CaseManager, BITChair, CounselingEvaluator, DeanOfStudents, PrivacyOfficer |
| POST | `/bit/care-cases/{id}/assign-manager` | Assign or reassign the case manager | BITChair |
| POST | `/bit/care-cases/{id}/close` | Close a case that satisfies closure eligibility | BITChair |
| POST | `/bit/risk-scorings` | Record a rubric scoring (INITIAL on INTAKE, REASSESSMENT on TRIAGED) | BITChair |
| GET | `/bit/risk-scorings/{id}` | Get a risk scoring | BITChair, CaseManager, DeanOfStudents, PrivacyOfficer |
| GET | `/bit/risk-scorings` | List and filter risk scorings | BITChair, CaseManager, DeanOfStudents, PrivacyOfficer |
| POST | `/bit/intervention-plans` | Draft an intervention plan (OCC-guarded on the case) | CaseManager |
| GET | `/bit/intervention-plans/{id}` | Get an intervention plan | CaseManager, BITChair, DeanOfStudents, PrivacyOfficer |
| GET | `/bit/intervention-plans` | List and filter intervention plans | CaseManager, BITChair, DeanOfStudents, PrivacyOfficer |
| POST | `/bit/intervention-plans/{id}/submit` | Submit a draft for approval (drafter only) | CaseManager |
| POST | `/bit/intervention-plans/{id}/approve` | Approve a submitted plan (approver differs from drafter) | BITChair |
| POST | `/bit/intervention-plans/{id}/return` | Return a submitted plan for revision | BITChair |
| POST | `/bit/mandated-assessments` | Order a mandated assessment (case must be PLAN_ACTIVE) | BITChair |
| GET | `/bit/mandated-assessments/{id}` | Get a mandated assessment | BITChair, CounselingEvaluator, DeanOfStudents, CaseManager |
| GET | `/bit/mandated-assessments` | List and filter mandated assessments | BITChair, CounselingEvaluator, DeanOfStudents, CaseManager |
| POST | `/bit/mandated-assessments/{id}/record-outcome` | Evaluator records CLEARED or NOT_CLEARED | CounselingEvaluator |
| GET | `/bit/leave-decisions/{id}` | Get a leave decision | BITChair, DeanOfStudents, CaseManager, PrivacyOfficer |
| GET | `/bit/leave-decisions` | List and filter leave decisions | BITChair, DeanOfStudents, CaseManager, PrivacyOfficer |
| POST | `/bit/leave-decisions/{id}/decide` | Dean decides GRANT_LEAVE or DENY_LEAVE | DeanOfStudents |
| POST | `/bit/reentry-evaluations` | Petition re-entry for an ON_LEAVE case (OCC-guarded) | CaseManager |
| GET | `/bit/reentry-evaluations/{id}` | Get a re-entry evaluation | BITChair, DeanOfStudents, CaseManager, PrivacyOfficer |
| GET | `/bit/reentry-evaluations` | List and filter re-entry evaluations | BITChair, DeanOfStudents, CaseManager, PrivacyOfficer |
| POST | `/bit/reentry-evaluations/{id}/decide` | Dean decides re-entry (segregated from the original leave decider) | DeanOfStudents |
| GET | `/bit/follow-up-checkins/{id}` | Get a follow-up check-in | CaseManager, BITChair, DeanOfStudents, PrivacyOfficer |
| GET | `/bit/follow-up-checkins` | List and filter follow-up check-ins | CaseManager, BITChair, DeanOfStudents, PrivacyOfficer |
| POST | `/bit/follow-up-checkins/{id}/complete` | Assigned case manager completes a SCHEDULED check-in (early completion allowed) | CaseManager |
| POST | `/bit/disclosure-grants` | Request cross-office disclosure for a case | CaseManager |
| GET | `/bit/disclosure-grants/{id}` | Get a disclosure grant | CaseManager, BITChair, PrivacyOfficer, DeanOfStudents, CounselingEvaluator |
| GET | `/bit/disclosure-grants` | List and filter disclosure grants | CaseManager, BITChair, PrivacyOfficer, DeanOfStudents, CounselingEvaluator |
| POST | `/bit/disclosure-grants/{id}/approve` | PrivacyOfficer approves a requested grant | PrivacyOfficer |
| POST | `/bit/disclosure-grants/{id}/deny` | PrivacyOfficer denies a requested grant | PrivacyOfficer |
| POST | `/bit/disclosure-grants/{id}/revoke` | PrivacyOfficer revokes an approved grant | PrivacyOfficer |
| POST | `/bit/trend-reports` | Generate an aggregate trend report for a term window (computed immediately) | SystemAdmin |
| GET | `/bit/trend-reports/{id}` | Get a trend report | Reporter, CaseManager, BITChair, CounselingEvaluator, DeanOfStudents, PrivacyOfficer, SystemAdmin |
| POST | `/bit/_clock/set_current_utc` | Advance the logical clock and apply expiry sweeps | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives beside the workflows they guard; this table is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_REPORT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CASE_NOT_TRIAGEABLE` | 409 Conflict |
| `ERR_SCORING_MODE_INVALID` | 400 Bad Request |
| `ERR_RUBRIC_SCORE_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_OPEN_PLAN_EXISTS` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_PENDING_APPROVAL` | 409 Conflict |
| `ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_CASE_MANAGER` | 403 Forbidden |
| `ERR_CASE_NOT_PLAN_ACTIVE` | 409 Conflict |
| `ERR_CASE_NOT_MANDATED_ASSESSMENT` | 409 Conflict |
| `ERR_CASE_NOT_ON_LEAVE` | 409 Conflict |
| `ERR_REENTRY_ALREADY_PENDING` | 409 Conflict |
| `ERR_CONDITIONS_REQUIRED` | 400 Bad Request |
| `ERR_CASE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_STUDENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRIVACY_SCOPE_INSUFFICIENT` | 403 Forbidden |
| `ERR_DISCLOSURE_WINDOW_INVALID` | 400 Bad Request |
| `ERR_DISCLOSURE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_GRANT_NOT_REQUESTED` | 409 Conflict |
| `ERR_GRANT_NOT_APPROVED` | 409 Conflict |
| `ERR_ASSESSMENT_ALREADY_PENDING` | 409 Conflict |
| `ERR_ASSESSMENT_DUE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_EVALUATOR_SAME_AS_ORDERER` | 400 Bad Request |
| `ERR_ASSESSMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DECISION_NOT_PENDING` | 409 Conflict |
| `ERR_CHECKIN_NOT_SCHEDULED` | 409 Conflict |
| `ERR_TREND_WINDOW_INVALID` | 400 Bad Request |
| `ERR_RELATED_REPORT_STUDENT_MISMATCH` | 422 Unprocessable Entity |
