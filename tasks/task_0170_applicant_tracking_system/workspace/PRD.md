# Applicant Tracking System API — Product Requirements Document

## 1. Introduction

Hiring at scale is a multi-party negotiation that is also an audit trail. A recruiter must shepherd a requisition through approval, attract candidates, schedule interviews, and produce an offer; a hiring manager must defend the spend; compensation and executive reviewers must keep total first-year cost inside policy bands; compliance must ensure that EEO/OFCCP self-identification data is captured before sensitive decisions, and that background-check outcomes reliably flow back into the pipeline even after a hire has been recorded. Each of these actors works on a different clock, with a different view of the data, and yet the system must serialize their decisions into a single consistent story.

This document specifies the Applicant Tracking System (ATS) API that makes that story possible. The API is mounted under `/requisitions` as the canonical resource root, with adjacent resource trees for candidates, applications, interviews, offers, background checks, referral bonuses, and diversity goals. It is consumed by recruiters, hiring managers, interviewers, candidates themselves, downstream compensation and executive approvers, compliance officers, payroll operators, and platform administrators. The benchmark deliberately exercises multi-party state machines (a cyclic offer-approval renegotiation, a compound application stage machine, a branching requisition lifecycle), version-pinning on approval, optimistic concurrency, and a cascade that fires from a single `BackgroundCheck` FAIL all the way back up to reopening a `CLOSED` requisition.

The design priority is that every audit-relevant outcome — who approved what, with which version pinned, at what posted compensation amounts, against which diversity goal — is reconstructible from the persisted state. The API therefore prefers explicit state transitions over silent edits, pins versions at decision points rather than reading them live, and emits compensating actions whenever a previously recorded hire must be revoked.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting principal, and `X-User-Role` declaring the role under which the request is being made. If either header is absent or empty, the request is rejected with `ERR_UNAUTHORIZED`. If the headers are present but the declared role is not authorized for the requested endpoint (per the endpoint table in §4), the request is rejected with `ERR_FORBIDDEN`.

The system recognizes nine roles, spelled exactly as follows: `Recruiter`, `HiringManager`, `Interviewer`, `Candidate`, `Compensation`, `Executive`, `ComplianceOfficer`, `PayrollOperator`, and `PlatformAdmin`.

Four of these roles are entity-backed, meaning `X-User-ID` must be the `id` of a persisted entity. When `X-User-Role` is `Recruiter`, `X-User-ID` is the `id` of the acting `Recruiter`, and ownership checks on any resource that references a `Recruiter` compare the resource's foreign-key field (such as a requisition's `recruiter_id`) to `X-User-ID`. The same pattern applies for the other three entity-backed roles: when `X-User-Role` is `HiringManager`, `X-User-ID` is the `id` of the acting `HiringManager` and is compared against a resource's `hiring_manager_id`; when `X-User-Role` is `Interviewer`, `X-User-ID` is the `id` of the acting `Interviewer` and is compared against an interview's `interviewer_id`; when `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate` and is compared against an application's `candidate_id` (and transitively against the candidate referenced by an offer's parent application).

The remaining five roles — `Compensation`, `Executive`, `ComplianceOfficer`, `PayrollOperator`, and `PlatformAdmin` — are opaque operator identities not tied to any persisted entity. For each of them, `X-User-ID` is an opaque identifier; the server may record it on a downstream artifact (for example, as the acting party recorded against an `OfferApprovalStep` whose `approver_role` is `COMPENSATION` or `EXECUTIVE`, where the supplied id is matched against `required_approver_id`) but does not compare it to any entity's `id`. Compliance officers are likewise opaque when they report background-check outcomes, and payroll operators are opaque when paying referral bonuses.

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

All list endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10 if the client omits it; the minimum accepted value is 1 and the maximum is 100. The default `offset` is 0. Lists are returned sorted by `created_at` ascending (oldest first). The `meta` block of a list response always carries `limit`, `offset`, `total_count` (the total number of records matching the filter ignoring pagination), and `has_more` (a boolean that is true when `offset + limit < total_count`).

### 2.4. Common Resource Properties and Versioning

Every resource is identified by an `id` minted by the server as a UUID with no type prefix. Entities with the common-fields treatment — `Recruiter`, `HiringManager`, `Interviewer`, `Requisition`, `Candidate`, `Application`, `Interview`, `Offer`, `BackgroundCheck`, `ReferralBonus`, and `DiversityGoal` — additionally carry `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and a `version` field which is an integer that starts at 1 on creation and increments by one on every mutation, whether direct (a `PATCH`) or indirect (a state transition or computed-field recompute).

Two entities are deliberately exceptions and do NOT carry `updated_at` or `version` — they carry only `id` and `created_at`. These are `EEORecord` (a self-identification snapshot that is immutable once attached to a candidate) and `OfferApprovalStep` (a per-step decision artifact whose only mutation is `PENDING` → `APPROVED`/`REJECTED` which writes `decided_at`); read code must not expect `updated_at` or `version` on either. `InterviewFeedback` likewise carries only `id` and `created_at` and is immutable after submission — `submitted_at` is recorded by the server at creation time.

### 2.5. Optimistic Concurrency Control

Every `PATCH` endpoint accepts an optional `version` field in the request body. When the client supplies `version`, the server compares it to the entity's current `version` and rejects the request with `ERR_VERSION_CONFLICT` if the two do not match. When the client omits `version`, the check is skipped and the mutation proceeds against whatever the current state happens to be. The same `version` semantics underpin the offer renegotiation cycle and the EEO snapshot pinning described below: where the system pins a version at a decision point, later mutations of the source entity do not invalidate the pinned decision, but a stale `PATCH` that supplies an outdated `version` still fails on its own merits.

### 2.6. Nested Resource Retrieval

URL paths are validated left to right. For a path like `/requisitions/{requisition_id}/applications`, the server first resolves the requisition; if it does not exist, the response is `ERR_NOT_FOUND` and the rest of the path is not evaluated. Once every path segment has been resolved, foreign-key fields supplied in the request body are checked next — a missing referenced entity produces `ERR_REFERENCE_NOT_FOUND` (HTTP 422). The distinction matters: a wrong id in the URL is a 404, a wrong id in a request body is a 422.

### 2.7. Status-Code Conventions

Endpoints that create a new persisted resource (a new `Requisition`, `Candidate`, `Application`, `Interview`, `InterviewFeedback`, `Offer`, `BackgroundCheck`, `EEORecord`, or `DiversityGoal`) return HTTP 201. Every other endpoint — including all state-transition triggers, `PATCH` edits, and `GET` reads — returns HTTP 200 on success.

### 2.8. Cascading Side Effects and Version Bumps

Several operations in this system mutate more than one entity. Any successful state transition or computed-field recompute on an entity that carries `version` bumps that entity's `version` by one and refreshes its `updated_at`. When a parent transition has a child side effect (for example, an offer acceptance promoting the application to `HIRED` and incrementing the requisition's `filled_count`), every entity that the operation touches has its `version` and `updated_at` advanced — recruiter clients holding an older requisition payload will see version drift, which is intentional. The single most important cascade is the post-hire revoke chain (described in §3.7): a background-check `FAIL` arriving after an offer has already been accepted unwinds the offer, the application, the requisition's `filled_count`, and even reopens a `CLOSED` requisition.

### 2.9. Validation Priority

When multiple validation conditions could fire on the same request, they are evaluated in a fixed priority order so that the response error reliably identifies the highest-priority failure. The order is: first, header presence (`ERR_UNAUTHORIZED`); then RBAC authorization (`ERR_FORBIDDEN`); then path-resource existence (`ERR_NOT_FOUND`); then request-body foreign-key existence (`ERR_REFERENCE_NOT_FOUND`); then state-machine validity (`ERR_INVALID_STATE`); then optimistic-concurrency mismatch (`ERR_VERSION_CONFLICT`); then the OFCCP EEO-data gate (`ERR_EEO_DATA_MISSING`); then segregation-of-duties enforcement (`ERR_SEGREGATION_OF_DUTIES`); then the referral-source consistency check (`ERR_REFERRAL_REQUIRES_REFERRER`); then the interviewer double-booking check (`ERR_INTERVIEWER_DOUBLE_BOOKED`); then the recruiter open-requisition cap (`ERR_RECRUITER_REQUISITION_CAP`); then duplicate-application detection (`ERR_DUPLICATE_APPLICATION`); then qualifying-feedback gating on offer-stage advance (`ERR_NO_QUALIFYING_FEEDBACK`); then the per-offer requisition-budget cap (`ERR_OFFER_EXCEEDS_REQ_BUDGET`); then the per-manager budget cap (`ERR_MANAGER_BUDGET_EXCEEDED`); then headcount enforcement (`ERR_HEADCOUNT_EXCEEDED`); then the diversity-goal lock check (`ERR_DIVERSITY_GOAL_NOT_MET`); then the offer-expiry-in-past check (`ERR_OFFER_EXPIRES_IN_PAST`); then interview timing gates (`ERR_INTERVIEW_TIMING`); and finally the empty-panel rule (`ERR_EMPTY_PANEL`). Two further errors — `ERR_HEADCOUNT_IMMUTABLE` and `ERR_OFFER_FIELDS_IMMUTABLE` — are field-level immutability rules fired when a `PATCH` attempts to modify a value that is locked by the current entity status.

### 2.10. Monetary Amounts and Rounding

All monetary fields in the system are stored as integer cents (e.g., `budget_cents`, `base_salary_cents`, `sign_on_bonus_cents`, `annual_equity_cents`, `total_first_year_comp_cents`, `base_amount_cents`, `diversity_uplift_cents`, `total_amount_cents`). The default rounding mode wherever rounding is required is round half up (also called arithmetic rounding: a tie rounds away from zero, so 0.5 cents becomes 1 cent). Diversity-goal percentages (`realized_percentage`, `projected_percentage`) are reported with two decimal places, round half up. Where a calculation specifies a stricter precision (such as "whole dollars per component" for offer total compensation, described in §3.5), that precision overrides the default.

### 2.11. Test-Driving the Logical Clock

Because several transitions are time-gated (interview completion eligibility, offer expiration, referral payable accrual), the system exposes a `PlatformAdmin`-only test-driving capability that advances the logical clock to a supplied `to` instant in ISO 8601 UTC, and a parallel capability that emits a system event such as `OFFER_EXPIRY_SWEEP` or `REFERRAL_PAYABLE_SWEEP` identified by an `event_type` field. Advancing the clock auto-transitions any `EXTENDED` offer whose `expires_at` is at or before the new logical now to `EXPIRED`, and any `ACCRUED` referral bonus whose `payable_at` is at or before the new logical now to `PAYABLE`. Sweep events scan idempotently — re-emitting the same sweep when no new entity has become eligible is a no-op. The HTTP contract for these capabilities lives in §4.

## 3. Business Logic & Workflows

### 3.1. Provisioning People

Before any work happens, the platform must know about its participants. A `PlatformAdmin` creates each `Recruiter`, `HiringManager`, and `Interviewer` by supplying the participant's `email` (required to be unique within its role), a `full_name`, and a `department_code` such as `ENG` or `SALES`. A new `Recruiter` is born with `is_active` set to true by default; only active recruiters may own or create requisitions. A new `HiringManager` additionally carries `budget_cents` — the annual hiring budget against which approved offers are debited and rescinded offers are credited back, expressed in USD cents and constrained to be non-negative. A new `Interviewer` carries an `is_certified_for_eeo` flag, defaulting to false, that must be true before that interviewer may score a candidate flagged `is_in_eeo_protected_class`; submitting feedback on such a candidate without that certification is rejected with `ERR_SEGREGATION_OF_DUTIES`.

`Candidate` records are created by either a `Recruiter` or the `PlatformAdmin`. A candidate's `email` is unique, `full_name` is freeform, and `source` is one of `DIRECT`, `AGENCY`, `REFERRAL`, `EVENT`, or `INBOUND`. When `source` is `REFERRAL`, the request body must also include a non-null `referrer_employee_id` pointing to a `Recruiter`, `HiringManager`, or `Interviewer`; conversely, when `source` is anything other than `REFERRAL`, `referrer_employee_id` must be null. The system rejects either violation with `ERR_REFERRAL_REQUIRES_REFERRER`. A candidate may optionally self-identify as being in an EEO-tracked protected class by supplying `is_in_eeo_protected_class` (which defaults to false); this flag drives both the OFCCP gate at offer-stage advance and the diversity-goal progress calculations.

After a candidate exists, an `EEORecord` may be attached — exactly one record per candidate (the `candidate_id` foreign key is unique on `EEORecord`). The record contains `gender` (one of `MALE`, `FEMALE`, `NON_BINARY`, `DECLINE`), `ethnicity` (one of `HISPANIC_LATINO`, `WHITE`, `BLACK_AFRICAN_AMERICAN`, `NATIVE_HAWAIIAN_PI`, `ASIAN`, `AMERICAN_INDIAN_AN`, `TWO_OR_MORE`, `DECLINE`), `veteran_status` (one of `NOT_VETERAN`, `PROTECTED_VETERAN`, `OTHER_VETERAN`, `DECLINE`), and `disability_status` (one of `YES`, `NO`, `DECLINE`). The server stamps `submitted_at` at attachment time. Either the candidate themselves or a `ComplianceOfficer` may attach the record.

`DiversityGoal` records are created by the `PlatformAdmin` and are uniquely identified by the pair (`department_code`, `period_year`); `period_year` must be 2020 or later. The goal's `target_protected_class_percentage` is expressed as a percentage value strictly greater than 0 and at most 100.0 — for example, the value 30.0 means a 30% target.

### 3.2. The Requisition Lifecycle

A `Recruiter` creates a `Requisition` by supplying `recruiter_id` (which must reference an existing active recruiter), `hiring_manager_id`, `job_title`, `department_code`, `seniority_level` (one of `JUNIOR`, `MID`, `SENIOR`, `STAFF`, `PRINCIPAL`), `headcount` (at least 1), `budget_cents` (the maximum total first-year compensation allowed for any single offer under this requisition, at least 0), and optionally `target_diversity_goal_id` if the requisition should count toward a specific diversity goal. The new requisition is born in `DRAFT` with `filled_count` 0, `active_offer_count` 0, `posted_at` null, and `closed_at` null.

While still in `DRAFT`, a recruiter may freely edit `job_title`, `department_code`, `seniority_level`, `headcount`, `budget_cents`, and `target_diversity_goal_id`. Once the requisition has left `DRAFT`, `headcount` is immutable — attempts to modify it through a recruiter edit are rejected with `ERR_HEADCOUNT_IMMUTABLE`. When the recruiter is ready, submitting the requisition advances it from `DRAFT` to `PENDING_APPROVAL`; this is permitted only when the acting recruiter's id matches the requisition's `recruiter_id`, the `headcount` is at least 1, and `budget_cents` is at least 0.

Approval is the hiring manager's prerogative. Approving the requisition advances it `PENDING_APPROVAL` → `OPEN`, sets `posted_at` to the current logical time, and requires that the acting hiring manager match the requisition's `hiring_manager_id` and that the acting hiring manager's `department_code` match the requisition's `department_code`. Approval is also where the recruiter open-requisition cap is enforced: a `Recruiter` may own at most 5 requisitions for which `posted_at` is non-null and `closed_at` is null at any one time — this is a half-open lifetime interval, and the cap counts in aggregate across the recruiter's owned requisitions rather than as pairwise overlap. Breaching the cap rejects the approval with `ERR_RECRUITER_REQUISITION_CAP`. The hiring manager may instead reject the requisition, which reverts it `PENDING_APPROVAL` → `DRAFT` for further editing.

Once `OPEN`, the requisition may be paused or resumed. Going on hold transitions `OPEN` → `ON_HOLD` and is permitted only when no `Application` on the requisition is currently in `OFFER_STAGE`; resuming reverses `ON_HOLD` → `OPEN`. Cancellation transitions `OPEN` → `CANCELLED` or `ON_HOLD` → `CANCELLED`; either transition requires that `filled_count` equals 0, and the `OPEN` → `CANCELLED` variant additionally requires that no application is in `OFFER_STAGE`. Cancellation sets `closed_at` to the current logical time and auto-rejects every non-terminal application on the requisition by transitioning each one to `REJECTED` with `rejection_reason` set to `OTHER`.

The closure path is itself driven by the hire cascade. When an application on this requisition transitions to `HIRED` and that hire causes `filled_count` to reach `headcount`, the requisition automatically transitions `OPEN` → `CLOSED`, sets `closed_at` to the current logical time, and rejects every remaining non-terminal application with `rejection_reason` set to `OTHER`. The requisition's terminal states are therefore `CLOSED` and `CANCELLED`; the in-flight states are `DRAFT`, `PENDING_APPROVAL`, `OPEN`, and `ON_HOLD`.

### 3.3. Applications and the Pipeline

An application is the bridge between a requisition and a candidate. Creating an application on a requisition takes a body with `candidate_id` and is permitted to either the `Recruiter` who owns the requisition or the `Candidate` themselves applying directly. The pair (`requisition_id`, `candidate_id`) is unique whenever the application's `stage` is not in `WITHDRAWN` or `REJECTED`; an attempt to create a second live application for the same pair is rejected with `ERR_DUPLICATE_APPLICATION`. Two recruiters racing to create the same application for the same pair serialize on this uniqueness — the first writer wins and the second receives `ERR_DUPLICATE_APPLICATION`. The newly created application is in `APPLIED` and triggers a recompute of the requisition's diversity goal's projected progress (described in §3.6) if the requisition is tied to one.

Applications progress through five non-terminal stages and three terminal ones. The non-terminal sequence is `APPLIED` → `SCREENING` → `INTERVIEWING` → `OFFER_STAGE` → and finally `HIRED`; the terminal stages are `HIRED`, `REJECTED`, and `WITHDRAWN`. Each forward transition is initiated by the recruiter, who advances the application one stage at a time. Advancing from `APPLIED` to `SCREENING` requires only that the parent requisition is `OPEN`. Advancing from `SCREENING` to `INTERVIEWING` additionally requires that at least one `Interview` already exists under the application in `SCHEDULED` status.

Advancing from `INTERVIEWING` to `OFFER_STAGE` is the most heavily gated transition in the system. It requires (a) the parent requisition is `OPEN`, (b) at least one `Interview` under the application has reached `COMPLETED` and carries at least one `InterviewFeedback` whose `recommendation` is `HIRE` or `STRONG_HIRE` — otherwise the advance is rejected with `ERR_NO_QUALIFYING_FEEDBACK`, (c) the application's `panel_average_score` is no longer null (which means at least one feedback has been submitted on a completed interview, and the rolling mean has been computed), (d) the empty-panel condition does not hold — there must be at least one `COMPLETED` interview overall, otherwise the advance is rejected with `ERR_EMPTY_PANEL`, and (e) the OFCCP gate: if the candidate is flagged `is_in_eeo_protected_class`, an `EEORecord` must already be attached to that candidate; otherwise the advance is rejected with `ERR_EEO_DATA_MISSING`. On a successful advance into `OFFER_STAGE`, the application snapshots the candidate's `version` into `pinned_eeo_snapshot_version`; subsequent edits of the candidate's EEO posture do not retroactively invalidate the approval chain that this application's offer will travel through.

A recruiter may reject any application in `APPLIED`, `SCREENING`, or `INTERVIEWING`. The request body carries `rejection_reason`, one of `NOT_QUALIFIED`, `FAILED_INTERVIEW`, `FAILED_BACKGROUND_CHECK`, `OFFER_DECLINED`, `DUPLICATE`, or `OTHER`. When rejecting an `INTERVIEWING` application, the recorded reason defaults to `FAILED_INTERVIEW` unless the request body specifies otherwise. Candidates withdraw themselves by initiating a `WITHDRAWN` transition, permitted from any of `APPLIED`, `SCREENING`, `INTERVIEWING`, and `OFFER_STAGE`; the acting candidate must match the application's `candidate_id`. When the candidate withdraws from `OFFER_STAGE`, any non-terminal offer on the application is cancelled: if the offer is in `APPROVED` or `EXTENDED`, it transitions to `RESCINDED`; otherwise it falls to `DECLINED`. Both the rejection path and the withdraw path recompute the parent diversity goal's projected progress.

System-initiated terminations of an application are also possible. When the parent requisition transitions to `CANCELLED` or `CLOSED`, every non-terminal application on it auto-transitions to `REJECTED` with `rejection_reason` set to `OTHER`. When an offer on an `OFFER_STAGE` application is declined or rescinded and no other accepted offer exists on the application, the application auto-transitions to `REJECTED` with `rejection_reason` set to `OFFER_DECLINED` (if the offer was declined), `FAILED_BACKGROUND_CHECK` (if the rescind was driven by a background-check fail), or `OTHER`.

### 3.4. Scheduling, Conducting, and Feedback on Interviews

Interviews are scheduled under an application by a recruiter, who supplies `interviewer_id`, `scheduled_start_at`, and `scheduled_end_at` as ISO 8601 UTC instants representing a closed interval; the new `Interview` carries the parent application's id in its `application_id` foreign-key field; `scheduled_end_at` must be strictly after `scheduled_start_at`. The interview is born in `SCHEDULED`. Every newly scheduled or edited interview is checked for double-booking against the assigned interviewer's existing `SCHEDULED` interviews using a 15-minute buffer applied to both sides of each existing interval — that is, an existing scheduled interview from 10:00 to 11:00 effectively occupies 09:45 to 11:15 for collision-detection purposes. Adjacency where one interview's end equals another's start is therefore a conflict. A violation is rejected with `ERR_INTERVIEWER_DOUBLE_BOOKED`. Two recruiters racing to schedule overlapping interviews for the same interviewer serialize on this rule — the first writer wins, the loser receives `ERR_INTERVIEWER_DOUBLE_BOOKED`. The rule also applies on recruiter edits to interviews. An interview cannot be created without an interviewer assigned — empty panels at creation are rejected with `ERR_EMPTY_PANEL`.

Interviews are time-gated. Completing an interview transitions it `SCHEDULED` → `COMPLETED`, but only when the current logical time is at or after `scheduled_end_at`; calling complete before that instant is rejected with `ERR_INTERVIEW_TIMING`. Marking an interview as a no-show transitions it `SCHEDULED` → `NO_SHOW` under the same timing precondition. Cancelling an interview transitions it `SCHEDULED` → `CANCELLED` but only when the current logical time is strictly before `scheduled_start_at`; cancelling at or after the start is rejected with `ERR_INTERVIEW_TIMING`. The interview's terminal states are `COMPLETED`, `NO_SHOW`, and `CANCELLED`. Completion may be performed by either the recruiter or the assigned interviewer; cancellation is recruiter-only; no-show is shared between recruiter and interviewer.

The assigned interviewer alone submits an `InterviewFeedback`; the feedback carries the parent interview's id in its `interview_id` foreign-key field. The submitting `interviewer_id` on the feedback must equal the interview's `interviewer_id`; an interviewer scoring a candidate flagged `is_in_eeo_protected_class` must additionally have `is_certified_for_eeo` set to true, otherwise the submission is rejected with `ERR_SEGREGATION_OF_DUTIES`. The body carries `overall_score` (an integer from 1 to 5 inclusive, where 5 means strong hire) and `recommendation` (one of `STRONG_HIRE`, `HIRE`, `NO_HIRE`, `STRONG_NO_HIRE`); the server stamps `submitted_at`. Every successful submission triggers a recompute of `panel_average_score` on the parent application. Completing the parent interview also triggers the recompute, because completion is what brings the interview into the feedback set's denominator.

The `panel_average_score` on the application is the mean of the `overall_score` values across the set of all `InterviewFeedback` records whose parent interview is `COMPLETED` and belongs to the same application. If that set is empty, the score is null. Otherwise the score is the sum of the in-set scores divided by the count of in-set feedbacks, rounded half up to two decimal places.

### 3.5. The Offer Lifecycle: Approval Chain, Renegotiation, and Compensation

An offer is the financial proposition to a hired-track candidate. A `Recruiter` creates an offer on an application — but only when the application's `stage` is `OFFER_STAGE`. The request body carries `base_salary_cents` (at least 0), optionally `sign_on_bonus_cents` (defaults to 0), optionally `annual_equity_cents` (defaults to 0; this is the annualized equity grant value computed as the four-year vesting amount divided by four), and an `approval_chain` array describing the ordered list of approval steps the offer must pass through. Each entry in the approval chain materializes as an `OfferApprovalStep` with `offer_id` pointing back to the offer, a 1-based `step_order` (the pair (`offer_id`, `step_order`) is unique within the chain), an `approver_role` of `HIRING_MANAGER`, `COMPENSATION`, or `EXECUTIVE`, and a `required_approver_id` identifying the specific approver who must act at that step. For a `HIRING_MANAGER` step, the `required_approver_id` is the corresponding `HiringManager.id`; for `COMPENSATION` and `EXECUTIVE` steps, the id is an opaque operator identity. None of the `required_approver_id` values may equal the `recruiter_id` who created the offer — that violation is a segregation-of-duties failure flagged at approve time. Each step starts with `decision` set to `PENDING` and `decided_at` null. On creation, the offer is in `DRAFT`, the offer's `requisition_id` is set to the parent application's `requisition_id`, `total_first_year_comp_cents` is computed by the offer-total-comp rule below, `negotiation_round` is 0, `pinned_requisition_version` is null, and `expires_at` is null.

Offer total compensation (`total_first_year_comp_cents`) is computed by rounding each component to whole dollars first and then summing — specifically: convert `base_salary_cents` to dollars by dividing by 100 and rounding half up to a whole number, convert `sign_on_bonus_cents` to dollars by dividing by 100 and rounding half up to a whole number, convert `annual_equity_cents` to dollars by dividing by 100 and rounding half up to a whole number, add the three whole-dollar values together, then multiply that sum by 100 to express the final result in cents. Summing the original cents and rounding once at the end is not the same answer and is not what the system computes. The rounding mode is round half up. As a consequence, `total_first_year_comp_cents` always ends in 00 (the cents portion is always zero, since the value is a whole-dollar amount expressed in cents). This recompute fires at offer creation, on every recruiter edit that touches any of the three component fields, and on every `NEGOTIATING` → `PENDING_APPROVAL` transition.

The offer has two views of its total compensation. While the offer is in `DRAFT`, `PENDING_APPROVAL`, or `NEGOTIATING`, the recompute is provisional — it reads the live component fields and is not budget-pinned. Once the offer transitions to `APPROVED`, the value freezes at that moment, and subsequent attempts to edit `base_salary_cents`, `sign_on_bonus_cents`, or `annual_equity_cents` are rejected with `ERR_OFFER_FIELDS_IMMUTABLE` (those fields are editable only while the offer is in `DRAFT` or `NEGOTIATING`). The frozen value is what governs the `APPROVED`, `EXTENDED`, and `ACCEPTED` lifecycle stages.

Submitting an offer transitions it `DRAFT` → `PENDING_APPROVAL` and requires that the parent application is in `OFFER_STAGE`, that its parent requisition is `OPEN`, that the offer's `total_first_year_comp_cents` is at most the requisition's `budget_cents` (otherwise `ERR_OFFER_EXCEEDS_REQ_BUDGET`), and that at least one `OfferApprovalStep` with `step_order` 1 exists. The submit transition snapshots the requisition's `version` into `pinned_requisition_version`; later mutations of the requisition do not invalidate this offer's approval chain, and the post-approval read of the offer carries the version that was current when the approval cycle began. It also increments the parent requisition's `active_offer_count` by one.

Approval walks the chain one step at a time. The request body carries `step_order` identifying which step is being decided. The approver acting on a step must (a) be the role declared by that step's `approver_role`, (b) have an id matching the step's `required_approver_id`, and (c) not be the recruiter who created the offer (segregation of duties — violation is `ERR_SEGREGATION_OF_DUTIES`). Approving a step that is not the highest `step_order` simply sets that step's `decision` to `APPROVED`, stamps `decided_at`, and leaves the offer in `PENDING_APPROVAL`. Approving the final step is what transitions the offer `PENDING_APPROVAL` → `APPROVED`, and that final transition has additional preconditions: every prior step's `decision` is already `APPROVED`, a `BackgroundCheck` for this offer exists with `status` of `PASSED` — the cross-entity offer-to-background-check gate — and the offer's `total_first_year_comp_cents` is still at most the parent requisition's `budget_cents` (otherwise the approval is rejected with `ERR_OFFER_EXCEEDS_REQ_BUDGET`, the same per-offer cap that was enforced at submit and during edits). When the final approval succeeds, the side effect debits the hiring manager's `budget_cents` by the offer's `total_first_year_comp_cents`. If that debit would push the hiring manager's total committed compensation across their `APPROVED`, `EXTENDED`, and `ACCEPTED` offers past their original `budget_cents`, the approval is rejected with `ERR_MANAGER_BUDGET_EXCEEDED`. Two approvers racing on the same step — one approve, one request-revision — serialize on the step's `decision`: the first writer wins, and the loser receives `ERR_INVALID_STATE` because the step is no longer `PENDING`.

The renegotiation loop is what makes the offer state machine cyclic. An approver may request a revision instead of approving, with an optional `reason`. The acting step's `decision` is recorded as `REJECTED`, `decided_at` is stamped, and the offer transitions `PENDING_APPROVAL` → `NEGOTIATING`. The recruiter then edits the offer with revised `base_salary_cents`, `sign_on_bonus_cents`, or `annual_equity_cents` (these are the only mutable fields, and they are mutable only in `DRAFT` and `NEGOTIATING`). An edit submitted against a `NEGOTIATING` offer additionally drives the offer back to `PENDING_APPROVAL`, increments `negotiation_round` by one, recomputes `total_first_year_comp_cents`, resets every `OfferApprovalStep` back to `PENDING` with `decided_at` set to null, and re-checks the requisition budget cap (an edit that drives the new total above the requisition's `budget_cents` is rejected with `ERR_OFFER_EXCEEDS_REQ_BUDGET`). The cycle `NEGOTIATING` → `PENDING_APPROVAL` → `NEGOTIATING` may repeat any number of times.

A `Recruiter` extends an approved offer to the candidate by supplying `expires_at` in the request body, transitioning the offer `APPROVED` → `EXTENDED`. The supplied `expires_at` must be strictly after the current logical time (otherwise `ERR_OFFER_EXPIRES_IN_PAST`), and the offer's `BackgroundCheck` must already be `PASSED`. The candidate then accepts or declines. Accepting transitions the offer `EXTENDED` → `ACCEPTED`; preconditions are that the acting candidate matches the parent application's `candidate_id`, the current logical time is strictly before `expires_at`, the parent requisition is still `OPEN`, and the parent requisition's `filled_count` is strictly less than `headcount` (otherwise `ERR_HEADCOUNT_EXCEEDED`). Declining transitions `EXTENDED` → `DECLINED`. An extended offer whose `expires_at` has passed without acceptance or decline auto-transitions `EXTENDED` → `EXPIRED` on the next clock advance or sweep event. Acceptance, decline, and expiry each decrement the parent requisition's `active_offer_count` by one.

A `Recruiter` may also rescind an offer in `APPROVED` or `EXTENDED`, optionally with a `reason`. Rescinding transitions the offer to `RESCINDED`, decrements `active_offer_count`, credits the hiring manager's `budget_cents` back by the offer's `total_first_year_comp_cents`, and auto-rejects the parent application with `rejection_reason` set to `FAILED_BACKGROUND_CHECK` if the rescind was driven by a background-check fail or `OTHER` otherwise. Two parties racing — one a candidate accept, one a recruiter rescind on the same `EXTENDED` offer — serialize on the offer's status: exactly one transition wins, and the loser receives `ERR_INVALID_STATE`. Declining an `EXTENDED` offer also auto-rejects the parent application with `rejection_reason` set to `OFFER_DECLINED`.

### 3.6. Hiring, the Hire Cascade, and Diversity Goal Reconciliation

When an offer reaches `ACCEPTED`, a three-hop cascade fires. Hop one: the parent application transitions from `OFFER_STAGE` to `HIRED`. Hop two: the parent requisition's `filled_count` is incremented by one — but only if `filled_count` was strictly less than `headcount` at the moment the increment is applied, otherwise the operation is rejected with `ERR_HEADCOUNT_EXCEEDED`. Two candidates racing to fill the last open seat by accepting concurrently issued offers on the same requisition serialize on this increment — the first writer wins, the second receives `ERR_HEADCOUNT_EXCEEDED`. Hop three: if this hire just brought `filled_count` to equal `headcount`, the requisition transitions `OPEN` → `CLOSED`, `closed_at` is set to the current logical time, and every remaining non-terminal application on the requisition is auto-rejected with `rejection_reason` set to `OTHER`.

The accepted offer also triggers reconciliation of any associated `ReferralBonus`. The `ReferralBonus` record exists with `candidate_id` and `requisition_id` matching the hire and is brought to `ACCRUED` at this moment (if not already). Its `base_amount_cents` is computed by looking up the requisition's `seniority_level` in a fixed schedule: `JUNIOR` yields $1,500.00 ($150,000 cents), `MID` yields $2,500.00 ($250,000 cents), `SENIOR` yields $5,000.00 ($500,000 cents), `STAFF` yields $7,500.00 ($750,000 cents), and `PRINCIPAL` yields $10,000.00 ($1,000,000 cents). If the candidate is flagged `is_in_eeo_protected_class`, a diversity uplift is applied: the uplift starts as 50% of the base amount in cents, rounded half up. That value is then capped — the cap is $2,000.00 ($200,000 cents) when the requisition is NOT tied to a `target_diversity_goal_id`, and $4,000.00 ($400,000 cents) when it IS tied to one. The effective uplift is the smaller of the raw 50% value and the applicable cap. If the candidate is not flagged `is_in_eeo_protected_class`, `diversity_uplift_cents` is 0. The `total_amount_cents` is the sum `base_amount_cents + diversity_uplift_cents`. The bonus's `payable_at` is set to the moment of the hire plus a 90-day waiting period. The `referrer_employee_id` on the bonus mirrors the candidate's `referrer_employee_id` at creation time. Referral bonuses may only be created for candidates whose `source` is `REFERRAL`; attempting to create one for any other source is rejected with `ERR_REFERRAL_REQUIRES_REFERRER`.

A referral bonus moves from `ACCRUED` to `PAYABLE` automatically when the logical clock advances past its `payable_at` (subject to the linked application still being `HIRED`). The `REFERRAL_PAYABLE_SWEEP` event is the idempotent test-driving capability that scans for eligible bonuses and applies the transitions. A `PayrollOperator` then transitions the bonus `PAYABLE` → `PAID` by paying it out; the linked application must still be in `HIRED` for this to succeed. The terminal states of a referral bonus are `PAID` and `CLAWED_BACK`.

`DiversityGoal` progress is computed in two variants whenever the underlying application population shifts. The realized variant looks only at applications that are currently in `HIRED`, are tied (through their requisition's `target_diversity_goal_id`) to this goal, and whose `updated_at` falls within the goal's `period_year`. If that set is empty, `realized_percentage` is 0.00. Otherwise it is 100 multiplied by the count of in-set applications whose candidate is `is_in_eeo_protected_class`, divided by the size of the in-set, rounded half up to two decimal places. The realized recompute fires on every transition to `HIRED` and on every reversion from `HIRED`. The projected variant uses a wider denominator: the set of applications whose `stage` is any of `APPLIED`, `SCREENING`, `INTERVIEWING`, `OFFER_STAGE`, or `HIRED`, that are tied to this goal, and whose `created_at` falls within the goal's `period_year`. If that set is empty, `projected_percentage` is 0.00. Otherwise it is 100 multiplied by the count of in-set applications whose candidate is `is_in_eeo_protected_class`, divided by the size of the in-set, rounded half up to two decimal places. The projected recompute fires on every application creation, every application transition into `OFFER_STAGE`, every reversion out of `OFFER_STAGE`, every transition to `REJECTED` or `WITHDRAWN`, and every transition into or out of `HIRED`.

A `PlatformAdmin` may attempt to lock a `DiversityGoal` for its period to certify it as met. The lock succeeds only when `realized_percentage` is greater than or equal to `target_protected_class_percentage` — note that the threshold is met when exactly equal; it is a non-strict comparison. If `realized_percentage` is strictly less than the target, the lock is rejected with `ERR_DIVERSITY_GOAL_NOT_MET`.

### 3.7. Background Checks and the Post-Hire Revoke Cascade

A `Recruiter` orders a `BackgroundCheck` against an offer by supplying `vendor`, one of `ACME_BG`, `VERIFY_INC`, or `FED_CHECKS`. Exactly one background check may be active per offer (the `offer_id` foreign key is unique). The new check is in `PENDING` with `ordered_at` stamped by the server and `result_received_at` null. A `ComplianceOfficer` later reports the outcome by supplying an `outcome` of `PASS` or `FAIL`; the server stamps `result_received_at`. A `PASS` transitions the check to `PASSED`. A `FAIL` transitions it to `FAILED` and then cascades into the offer, which is the most consequential chain in the system.

If the linked offer is in `APPROVED` or `EXTENDED` at the moment of `FAIL`, the offer is forced to `RESCINDED`, the parent requisition's `active_offer_count` is decremented by one, the hiring manager's `budget_cents` is credited back by the offer's `total_first_year_comp_cents`, and the parent application is auto-rejected with `rejection_reason` set to `FAILED_BACKGROUND_CHECK`. If instead the linked offer has already been `ACCEPTED` — that is, the hire has been recorded — the cascade is broader (this is the post-hire revoke chain): the offer transitions `ACCEPTED` → `RESCINDED`; the parent application transitions `HIRED` → `REJECTED` with `rejection_reason` set to `FAILED_BACKGROUND_CHECK`; the parent requisition's `filled_count` is decremented by one; if the requisition was already in `CLOSED`, it is reopened back to `OPEN` and `closed_at` is cleared; the hiring manager's `budget_cents` is credited back by the offer's `total_first_year_comp_cents`; and any `ReferralBonus` tied to this hire is transitioned to `CLAWED_BACK` regardless of whether it was previously `ACCRUED` or `PAYABLE`.

The race between candidate acceptance and background-check `FAIL` is handled deterministically. If the `FAIL` lands first while the offer is `EXTENDED`, the offer rescinds and a subsequent acceptance attempt is rejected with `ERR_INVALID_STATE`. If the acceptance lands first and reaches `ACCEPTED`, the later-arriving `FAIL` still applies and runs the full post-hire revoke chain described above.

A pending background check may also be cancelled by the recruiter, but only when the linked offer is in `NEGOTIATING`, `DECLINED`, `RESCINDED`, or `EXPIRED` (in other words, the offer is no longer a live candidate for a hire). The check transitions `PENDING` → `CANCELLED`. The terminal states of a background check are `PASSED`, `FAILED`, and `CANCELLED`.

## 4. Endpoint Definitions

Endpoints that create a new persisted resource return HTTP 201; all other successful endpoints (including state transitions, edits, and reads) return HTTP 200. Request and response bodies follow the envelope contract in §2.2; field-level semantics live in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/recruiters` | Create a Recruiter | PlatformAdmin |
| GET | `/recruiters/{id}` | Read a Recruiter | PlatformAdmin, Recruiter, HiringManager |
| POST | `/hiring-managers` | Create a HiringManager | PlatformAdmin |
| POST | `/interviewers` | Create an Interviewer | PlatformAdmin |
| POST | `/requisitions` | Create a Requisition in DRAFT | Recruiter |
| GET | `/requisitions` | List Requisitions (filterable by status, recruiter_id, hiring_manager_id, department_code) | PlatformAdmin, Recruiter, HiringManager |
| GET | `/requisitions/{id}` | Read a Requisition | PlatformAdmin, Recruiter, HiringManager |
| PATCH | `/requisitions/{id}` | Edit Requisition fields while in DRAFT | Recruiter |
| POST | `/requisitions/{id}/submit` | DRAFT to PENDING_APPROVAL | Recruiter |
| POST | `/requisitions/{id}/approve` | PENDING_APPROVAL to OPEN | HiringManager |
| POST | `/requisitions/{id}/reject` | PENDING_APPROVAL to DRAFT | HiringManager |
| POST | `/requisitions/{id}/hold` | OPEN to ON_HOLD | Recruiter |
| POST | `/requisitions/{id}/resume` | ON_HOLD to OPEN | Recruiter |
| POST | `/requisitions/{id}/cancel` | OPEN or ON_HOLD to CANCELLED | Recruiter |
| POST | `/candidates` | Create a Candidate | Recruiter, PlatformAdmin |
| GET | `/candidates/{id}` | Read a Candidate | Recruiter, HiringManager, PlatformAdmin |
| POST | `/candidates/{id}/eeo-record` | Attach the EEORecord (one per Candidate) | Candidate, ComplianceOfficer |
| GET | `/candidates/{id}/eeo-record` | Read EEORecord | Candidate, ComplianceOfficer |
| POST | `/requisitions/{id}/applications` | Create an Application on a Requisition | Recruiter, Candidate |
| GET | `/applications/{id}` | Read an Application | Recruiter, HiringManager, Candidate, PlatformAdmin |
| GET | `/requisitions/{id}/applications` | List Applications on a Requisition (filterable by stage) | Recruiter, HiringManager, PlatformAdmin |
| POST | `/applications/{id}/advance` | Advance to the next stage in the pipeline | Recruiter |
| POST | `/applications/{id}/reject` | Reject the application | Recruiter |
| POST | `/applications/{id}/withdraw` | Candidate withdraws | Candidate |
| POST | `/applications/{id}/interviews` | Schedule an Interview | Recruiter |
| GET | `/interviews/{id}` | Read an Interview | Recruiter, HiringManager, Interviewer, PlatformAdmin |
| POST | `/interviews/{id}/complete` | Mark Interview COMPLETED | Recruiter, Interviewer |
| POST | `/interviews/{id}/no-show` | Mark Interview NO_SHOW | Recruiter, Interviewer |
| POST | `/interviews/{id}/cancel` | Cancel SCHEDULED Interview before scheduled_start_at | Recruiter |
| POST | `/interviews/{id}/feedback` | Submit InterviewFeedback | Interviewer |
| GET | `/interviews/{id}/feedback` | List feedback for an Interview | Recruiter, HiringManager, Interviewer |
| POST | `/applications/{id}/offers` | Create an Offer in DRAFT | Recruiter |
| GET | `/offers/{id}` | Read an Offer | Recruiter, HiringManager, Candidate, Compensation, Executive, PlatformAdmin |
| PATCH | `/offers/{id}` | Edit Offer amounts (DRAFT or NEGOTIATING only) | Recruiter |
| POST | `/offers/{id}/submit` | DRAFT to PENDING_APPROVAL | Recruiter |
| POST | `/offers/{id}/approve` | Approve the next pending OfferApprovalStep | HiringManager, Compensation, Executive |
| POST | `/offers/{id}/request-revision` | PENDING_APPROVAL to NEGOTIATING | HiringManager, Compensation, Executive |
| POST | `/offers/{id}/extend` | APPROVED to EXTENDED | Recruiter |
| POST | `/offers/{id}/accept` | EXTENDED to ACCEPTED | Candidate |
| POST | `/offers/{id}/decline` | EXTENDED to DECLINED | Candidate |
| POST | `/offers/{id}/rescind` | APPROVED or EXTENDED to RESCINDED | Recruiter |
| GET | `/offers/{id}/approval-chain` | Read OfferApprovalStep[] for this Offer | Recruiter, HiringManager, Compensation, Executive, PlatformAdmin |
| POST | `/offers/{id}/background-check` | Order a BackgroundCheck for an Offer | Recruiter |
| GET | `/background-checks/{id}` | Read a BackgroundCheck | Recruiter, ComplianceOfficer, PlatformAdmin |
| POST | `/background-checks/{id}/report-result` | Compliance reports the outcome | ComplianceOfficer |
| POST | `/background-checks/{id}/cancel` | Cancel a PENDING BackgroundCheck | Recruiter |
| GET | `/referral-bonuses` | List ReferralBonus records | Recruiter, PayrollOperator, PlatformAdmin |
| GET | `/referral-bonuses/{id}` | Read a ReferralBonus | Recruiter, PayrollOperator, PlatformAdmin |
| POST | `/referral-bonuses/{id}/pay` | PAYABLE to PAID | PayrollOperator |
| POST | `/diversity-goals` | Create a DiversityGoal | PlatformAdmin |
| GET | `/diversity-goals/{id}` | Read a DiversityGoal | PlatformAdmin, Recruiter, HiringManager |
| POST | `/diversity-goals/{id}/lock` | Attempt to lock a goal as 'met' for the period | PlatformAdmin |
| POST | `/_clock/advance` | Advance the server's logical clock | PlatformAdmin |
| POST | `/_events/emit` | Emit a system event (sweep ticks) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHORIZED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_EEO_DATA_MISSING` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_REFERRAL_REQUIRES_REFERRER` | 422 |
| `ERR_INTERVIEWER_DOUBLE_BOOKED` | 409 |
| `ERR_RECRUITER_REQUISITION_CAP` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_NO_QUALIFYING_FEEDBACK` | 409 |
| `ERR_OFFER_EXCEEDS_REQ_BUDGET` | 422 |
| `ERR_MANAGER_BUDGET_EXCEEDED` | 422 |
| `ERR_HEADCOUNT_EXCEEDED` | 409 |
| `ERR_DIVERSITY_GOAL_NOT_MET` | 422 |
| `ERR_OFFER_EXPIRES_IN_PAST` | 422 |
| `ERR_INTERVIEW_TIMING` | 409 |
| `ERR_EMPTY_PANEL` | 409 |
| `ERR_HEADCOUNT_IMMUTABLE` | 422 |
| `ERR_OFFER_FIELDS_IMMUTABLE` | 422 |
