# Ats Applicant Tracking API — Product Requirements Document

## 1. Introduction

Hiring at scale is governed by a tangle of competing interests. Recruiters want to move pipelines forward; hiring managers want to defend headcount; finance owns the budget; legal and compliance own the EEO/OFCCP audit trail; payroll owes referrers their bonuses; and the candidate ultimately decides whether the offer lands. The Applicant Tracking System (ATS) described here exists to coordinate all of these parties through one API surface, where every transition — a requisition opening, an offer being approved, a background check resolving — is observable, reversible where the law requires it, and serialised against concurrent edits.

The product targets companies large enough that no single person is allowed to both submit and approve a requisition, that compensation decisions need two sets of executive eyes, and that diversity outcomes must be measurable per department, per seniority stratum, and per calendar year. The API therefore encodes a strict segregation-of-duties discipline, a two-step offer approval chain with optimistic concurrency, cascading rollbacks when a background check fails, and continuously-recomputed diversity metrics over the applicant pool and the hire cohort. Referral bonuses are deferred and decayed against the elapsed days between offer acceptance and background-check clearance, so that the payroll obligation only crystallises after the hire is truly cleared.

The contract that follows is the sole specification an implementer reads. Every field name, transition, validation, calculation, and role permission is intended to be reconstructible from this document alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present but the named role is not authorised for the requested endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). The sole exception to the authentication requirement is the test-driving clock endpoint, which does not enforce the authentication check.

The system recognises exactly eight roles, each spelled as shown: `PlatformAdmin`, `Recruiter`, `HiringManager`, `CompApprover`, `VP`, `ComplianceOfficer`, `PayrollOfficer`, and `Candidate`. For every one of these roles, `X-User-ID` is an opaque operator identifier and is not the primary key of any persisted entity. The server records the identifier on the resources whose state machines stamp it — for example, as `submitter_user_id` and `approver_user_id` on a job requisition, as `comp_approver_user_id` and `vp_approver_user_id` on an offer, as `panelist_user_id` on interview feedback, and as `referrer_user_id` on a candidate or referral bonus — but it never compares it to any entity's `id`. Ownership-style checks (segregation of duties, panelist independence, background-check independence) are accordingly stated in this PRD as comparisons between `X-User-ID` and the stored stamps, not between `X-User-ID` and an entity primary key.

The endpoint-by-endpoint authorisation matrix is given in §4. The role responsibilities are:

- A `PlatformAdmin` configures the platform itself: departments, diversity goals, and the test-driving clock. Platform admins also have read access to every resource.
- A `Recruiter` is the operational HR persona: creating requisitions and submitting them for approval, registering candidates, opening applications, scheduling and completing interviews, drafting and extending offers, and revoking offers. A recruiter never approves a requisition or an offer they touched.
- A `HiringManager` approves, rejects, or cancels requisitions, and reads the operational pipeline. The hiring manager who approves a requisition must differ from the recruiter who submitted it.
- A `CompApprover` clears the compensation leg of the two-step offer approval and may also reject a pending offer.
- A `VP` clears the executive leg of the two-step offer approval and may also reject a pending offer. The VP must differ from both the recruiter who submitted the offer and the comp approver who cleared the first leg.
- A `ComplianceOfficer` starts and resolves background checks. The resolver must not be the requisition's submitter or approver.
- A `PayrollOfficer` marks payable referral bonuses paid, and may manually void payable bonuses.
- A `Candidate` accepts, declines, or withdraws on their own behalf.

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

Every list endpoint accepts two optional query-string parameters, `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a request that supplies a limit outside that range is a client error. The `offset` defaults to 0 and has no upper bound beyond the natural one of the result set. List endpoints sort results by `created_at` ascending. The `meta` object on a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the unpaginated result set and `has_more` is true when more rows exist beyond the current page.

### 2.4. Common Resource Properties

Every persistent resource carries a server-minted `id` formatted as a UUID with no type prefix. Department, JobRequisition, Candidate, Application, Interview, Offer, BackgroundCheck, ReferralBonus, and DiversityGoal additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, plus an integer `version` that starts at 1 on creation and increments by one on every mutation that the state machines below describe. The `updated_at` timestamp is refreshed on every such mutation as well. The InterviewFeedback resource is a write-once log row and carries only `id` and `created_at`; it has no `updated_at` and no `version`.

When a side effect bumps the `version` of a parent entity, the cascade also bumps the `updated_at` of every entity whose state changes as part of the cascade.

### 2.5. Nested Resource Retrieval and Path Validation

Resource identifiers embedded in URL paths are validated left to right. A request to read a single resource whose `{id}` does not exist is rejected with `ERR_NOT_FOUND` (HTTP 404). When a body payload supplies a foreign-key identifier — `department_id`, `candidate_id`, `requisition_id`, `application_id`, `offer_id`, or `interview_id` — and the referenced row does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). Existence checks are evaluated before state checks; state checks are evaluated before business-safety, business-referential, and business-constraint checks; those in turn precede budget and OCC checks. The full priority order is captured in §2.10.

### 2.6. Precision, Rounding, and Money

All monetary amounts are stored and exchanged as **integer cents** — `hiring_budget_cents`, `committed_offer_cents`, `base_salary_min_cents`, `base_salary_max_cents`, `base_salary_cents`, `signing_bonus_cents`, `estimated_amount_cents`, and `payable_amount_cents`. Intermediate multipliers (band multiplier, diversity uplift, decay percentage) are computed as exact decimals, and the final integer cents amount is obtained by rounding half-up.

Interview aggregate scores are rounded half-up to two decimal places. Diversity percentages — `target_underrepresented_pct`, `pool_underrepresented_pct`, and `hire_underrepresented_pct` — are stored as fractions between 0 and 1 with four decimal places, rounded half-up.

### 2.7. Optimistic Concurrency Control

Two write paths are guarded by optimistic concurrency control. Each requires the client to echo the version of the parent resource it last observed; if the parent's `version` has advanced since that read, the write is rejected.

The first guarded path is the two-step offer approval. A request to approve an offer must carry `expected_offer_version` matching the offer's current `version` at the moment the server processes the request. If another writer has advanced the offer's version since the client last read it — for example, a reject call interleaving between the comp-approver step and the VP step, or a revoke landing between two approval polls — the approve is rejected with `ERR_STALE_VERSION` (HTTP 412). The state-machine precondition alone is insufficient here, because the second leg of approval is legitimately reachable on the observed state; only a version check distinguishes "I am acting on the offer I last read" from "the offer has shifted under me."

The second guarded path is the cancellation of an approved requisition. A request to cancel must carry `expected_requisition_version` matching the requisition's current `version`. If a system auto-transition or any other writer has advanced the requisition's version since the client's last read, the cancel is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field; their state-machine preconditions are sufficient to serialise concurrent writers.

### 2.8. Segregation of Duties and Independence

Three independence rules cut across the workflow and are enforced on every applicable endpoint:

- **Requisition approval and rejection segregation.** A hiring manager attempting to approve or reject a requisition whose `submitter_user_id` matches the calling `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The same rule applies symmetrically to a comp-approver or VP attempting to approve or reject an offer whose `submitter_user_id` matches their `X-User-ID`. On the VP leg, the VP's `X-User-ID` must also differ from the offer's `comp_approver_user_id`; otherwise the same error fires.
- **Panelist independence.** An interview's `panel_user_ids` must not contain the candidate's `referrer_user_id`; if it does, the create is rejected with `ERR_PANELIST_CONFLICT` (HTTP 422).
- **Background-check independence.** The compliance officer resolving a background check must not be the requisition's `submitter_user_id` nor the requisition's `approver_user_id`. A violation is rejected with `ERR_BGC_INDEPENDENCE` (HTTP 403).

### 2.9. Fiscal Discipline

Department budgets are enforced at two distinct moments:

1. **Worst-case headroom at requisition approval.** A requisition cannot be approved unless the department's `hiring_budget_cents` minus its current `committed_offer_cents` is at least `openings` multiplied by `base_salary_max_cents`. If the headroom falls short, the approve is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 422). This check is evaluated after the segregation-of-duties check, so a recruiter trying to self-approve will see the segregation error rather than the budget error even when both would fire.
2. **Net headroom at offer approval.** An offer cannot be approved unless the department's `hiring_budget_cents` minus its `committed_offer_cents` net of this offer's already-included `base_salary_cents`, minus this offer's `base_salary_cents` again, is at least zero. Phrased operationally: the offer's `base_salary_cents` must fit inside the remaining headroom, with the caveat that this offer's contribution to `committed_offer_cents` is excluded before being re-added. The rejection is the same `ERR_BUDGET_EXCEEDED` (HTTP 422). This check is independent of the segregation check.

The denormalised aggregate `committed_offer_cents` on each department is the sum of `base_salary_cents` across all offers on requisitions belonging to that department whose `status` is one of `PENDING_APPROVAL`, `APPROVED`, `EXTENDED`, or `ACCEPTED`. Whenever an offer enters or leaves that active set, the department aggregate is recomputed. Creating an offer adds its `base_salary_cents` to `committed_offer_cents`; rejecting, declining, or revoking an offer subtracts it.

### 2.10. Validation Priority

When multiple checks could fire on a single request, the server evaluates them strictly in the following order, returning the first applicable error:

1. Authentication of the two headers (`ERR_UNAUTHENTICATED`).
2. Role authorisation against §4 (`ERR_FORBIDDEN`).
3. Existence of path-templated `{id}` segments, validated left to right (`ERR_NOT_FOUND`).
4. Existence of foreign-key identifiers in the request body (`ERR_FK_NOT_FOUND`).
5. State-machine declaration: the target resource is in a state from which the requested transition is declared (`ERR_INVALID_STATE`).
6. Cross-entity preconditions — parent or sibling state matches the transition's required guard (`ERR_PRECONDITION_FAILED`), e.g., the requisition is `APPROVED` before an application is screened or an offer extended, and a candidate with an already-accepted offer cannot apply again.
7. Segregation-of-duties on requisition approve/reject and offer approve/reject (`ERR_SEGREGATION_OF_DUTIES`).
8. Panelist independence on interview creation (`ERR_PANELIST_CONFLICT`).
9. Background-check resolver independence (`ERR_BGC_INDEPENDENCE`).
10. Application uniqueness — the `(candidate_id, requisition_id)` pair is unique (`ERR_DUPLICATE_APPLICATION`).
11. At most one offer per application is in the active set `{PENDING_APPROVAL, APPROVED, EXTENDED, ACCEPTED}` (`ERR_DUPLICATE_OFFER`).
12. Interview panel shape: between 1 and 5 distinct `panel_user_ids`, no duplicates, non-empty (`ERR_INVALID_PANEL`).
13. Feedback panelist membership — `panelist_user_id` must belong to the interview's `panel_user_ids` (`ERR_PANELIST_NOT_ASSIGNED`).
14. Interview completion requires every panelist to have submitted feedback (`ERR_FEEDBACK_INCOMPLETE`).
15. Application-level interview overlap (`ERR_INTERVIEW_OVERLAP_APPLICATION`), followed by panelist-level interview overlap (`ERR_INTERVIEW_OVERLAP_PANELIST`).
16. Offer accept must occur strictly before `expires_at` (`ERR_OFFER_EXPIRED`).
17. Offer base salary within band (`ERR_SALARY_OUT_OF_BAND`).
18. Budget headroom at requisition approve, then at offer approve (`ERR_BUDGET_EXCEEDED`).
19. Optimistic concurrency on offer approve and requisition cancel (`ERR_STALE_VERSION`).
20. Manual referral-bonus eligibility (`ERR_NOT_REFERRAL_ELIGIBLE`).

Malformed payloads — missing required fields, wrong types, panel size out of range, score outside the integer range 1 through 5 inclusive, `openings` below 1, salary band where `base_salary_max_cents` is not strictly greater than `base_salary_min_cents` — surface as `ERR_INVALID_REQUEST` (HTTP 400) at the structural layer, before any of the above semantic checks.

## 3. Business Logic & Workflows

### 3.1. Departments and Diversity Goals

A `PlatformAdmin` opens the lifecycle by registering a department. The department record carries a human-readable `name`, a `cost_center_code` that must be unique across departments, and a `hiring_budget_cents` that is floored at zero. The computed `committed_offer_cents` is read alongside the stored fields and starts at zero before any offers exist.

The same admin establishes the diversity targets that the system will continuously measure against. A diversity goal is created for one combination of `department_id`, `target_level`, and `period_year`; that triple is unique. The goal carries a `target_underrepresented_pct` between 0.0 and 1.0 inclusive. Two computed companions, `pool_underrepresented_pct` and `hire_underrepresented_pct`, are recomputed when the goal is read.

The applicant pool metric is computed as follows. Take every candidate who has at least one application against any requisition belonging to the goal's department whose `target_level` matches the goal's stratum, where the application's `created_at` falls in the goal's `period_year` (UTC) and the application's `status` is not `WITHDRAWN`. Deduplicate by `candidate_id`, so a candidate who applied to several in-scope requisitions counts once. The denominator is the size of that deduplicated set. The numerator is the count of those candidates whose `eeo_ethnicity` is one of `BLACK`, `HISPANIC`, `NATIVE`, `PACIFIC`, or `TWO_OR_MORE`, **or** whose `eeo_disability` flag is true, **or** whose `eeo_veteran` flag is true. When the denominator is zero, `pool_underrepresented_pct` is reported as 0.0; otherwise it is the numerator divided by the denominator, rounded half-up to four decimal places.

The hire metric uses the same underrepresented predicate but restricts the cohort to applications whose `status` is `HIRED` and whose `updated_at` year (UTC) matches the goal's `period_year`. The denominator is the count of distinct hired `candidate_id`s in scope; the numerator is the count of those candidates who satisfy the underrepresented predicate. With zero hires, `hire_underrepresented_pct` is 0.0; otherwise it is numerator over denominator rounded half-up to four decimal places.

### 3.2. Requisition Lifecycle

A `Recruiter` drafts a job requisition by supplying the `department_id`, `title`, `target_level` (one of `JUNIOR`, `MID`, `SENIOR`, or `STAFF`), the salary band as `base_salary_min_cents` and `base_salary_max_cents`, and the `openings` headcount. On creation the requisition lands in state `DRAFT` with `version` 1, `filled_count` 0, and both `submitter_user_id` and `approver_user_id` null.

Submission for approval requires `openings` to be at least 1 and `base_salary_max_cents` to be strictly greater than `base_salary_min_cents`. Submitting advances the requisition from `DRAFT` to `PENDING_APPROVAL`, stamps the submitting recruiter's `X-User-ID` as `submitter_user_id`, and bumps `version`.

Approval from `PENDING_APPROVAL` to `APPROVED` is the privilege of a `HiringManager` other than the submitter — the segregation-of-duties check fires first if the same person attempts both roles, as described in §2.8. The worst-case budget headroom check then evaluates whether the department's `hiring_budget_cents` minus its `committed_offer_cents` is at least `openings` times `base_salary_max_cents`. On success, `approver_user_id` is stamped, `approved_at` is set to the current ISO 8601 UTC instant, and `version` is incremented. Rejection by the same hiring manager population transitions `PENDING_APPROVAL` to `REJECTED`, stamps `approver_user_id`, and bumps `version`; no budget check applies to rejection.

A requisition in `APPROVED` reaches `CLOSED` automatically when its computed `filled_count` equals its `openings`. The closure increments `version`; it does not stamp any user.

A hiring manager may also cancel an `APPROVED` requisition. Cancellation requires `expected_requisition_version` matching the requisition's current `version` (the OCC rule from §2.7) and is permitted only if no offer on the requisition is in state `ACCEPTED`. Cancellation drives several cascades in one transaction: every non-terminal application on the requisition transitions to `WITHDRAWN`; every non-terminal offer transitions to `REVOKED`, which in turn cascades any non-terminal background check to `CANCELLED` and any non-`PAID` referral bonus to `VOID`. The requisition's `version` is incremented.

Note that `CLOSED` is not strictly terminal: when a background check on a hire fails, the hire reverses, `filled_count` is decremented, and a previously `CLOSED` requisition re-opens to `APPROVED` (see §3.7).

### 3.3. Candidate Pool and EEO/OFCCP Data

A `Recruiter` adds a candidate by supplying `full_name`, a unique `email`, and a `source_channel` chosen from `DIRECT`, `REFERRAL`, `AGENCY`, or `JOB_BOARD`. When the source is `REFERRAL`, the referring employee's `X-User-ID` must be supplied as `referrer_user_id`; otherwise that field is null.

The candidate may voluntarily self-identify four EEO/OFCCP attributes: `eeo_ethnicity` (one of `WHITE`, `BLACK`, `HISPANIC`, `ASIAN`, `NATIVE`, `PACIFIC`, `TWO_OR_MORE`, or `DECLINED`, defaulting to `DECLINED`), `eeo_gender` (one of `FEMALE`, `MALE`, `NONBINARY`, or `DECLINED`, defaulting to `DECLINED`), `eeo_veteran` (boolean, defaulting to false), and `eeo_disability` (boolean, defaulting to false). These fields are the inputs to the diversity metrics in §3.1 and to the referral-bonus uplift in §3.6.

### 3.4. Application Lifecycle

Opening an application links a `candidate_id` to a `requisition_id`; the pair is unique. The requisition must be in `APPROVED`; otherwise the precondition fails with `ERR_PRECONDITION_FAILED`. The system also rejects a duplicate application against the same (candidate, requisition) pair with `ERR_DUPLICATE_APPLICATION`, and refuses to open a new application for a candidate whose pipeline already contains an accepted offer.

A fresh application starts in state `APPLIED`. The recruiter advances it from `APPLIED` to `SCREENING` once the requisition is still `APPROVED`; the screen call increments the application's `version`. The transition from `SCREENING` to `INTERVIEWING` is system-driven and fires automatically when the first interview is created on the application — see §3.5.

Three terminal pathways exist out of the active states. The recruiter may reject an application from any of `APPLIED`, `SCREENING`, or `INTERVIEWING`, moving it to `REJECTED`. The candidate may withdraw from the same three states, moving the application to `WITHDRAWN`. Both paths increment `version`. The successful pathway out is via offer acceptance: when an offer linked to the application transitions to `ACCEPTED`, the application moves to `HIRED` (see §3.6), which itself bubbles into the requisition's `filled_count` and may auto-close the requisition.

### 3.5. Interviews and Feedback

A recruiter schedules an interview by submitting an `application_id`, the `round_number` (sequential per application starting at 1), the `scheduled_at` ISO 8601 UTC instant, the `duration_minutes` (at least 15), and the `panel_user_ids` array. A new interview lands in state `SCHEDULED`, with both `aggregate_score` and `recommendation` null.

The panel must contain between 1 and 5 distinct entries, with no duplicates; a violation surfaces as `ERR_INVALID_PANEL`. The panel must not contain the candidate's `referrer_user_id`, per the panelist-independence rule of §2.8, which surfaces as `ERR_PANELIST_CONFLICT`.

Two temporal conflicts are detected on creation:

- **Per-application overlap.** Across the same `application_id`, no two `SCHEDULED` interviews may have overlapping intervals. The interval for an interview is half-open at `[scheduled_at, scheduled_at + duration_minutes)`, so adjacency where one interview's end equals another's start is permitted. A violation is rejected with `ERR_INTERVIEW_OVERLAP_APPLICATION`.
- **Per-panelist buffered overlap.** For each panelist appearing on the proposed panel, no other `SCHEDULED` interview containing that panelist may have an overlapping buffered interval. The buffered interval is `[scheduled_at - 15 minutes, scheduled_at + duration_minutes + 15 minutes)`, applying a 15-minute travel buffer on both ends and remaining half-open at the upper end. Adjacency at the buffered boundary is permitted. A violation is rejected with `ERR_INTERVIEW_OVERLAP_PANELIST`.

Scheduling the first interview on an application cascades the application from `SCREENING` to `INTERVIEWING` and bumps the application's `version`.

A panelist submits feedback by supplying the `interview_id`, the `panelist_user_id`, an integer `score` from 1 through 5 inclusive, and free-form `comments`. The `panelist_user_id` must belong to the interview's `panel_user_ids`; otherwise the feedback is rejected with `ERR_PANELIST_NOT_ASSIGNED`. InterviewFeedback rows are append-only; they carry only the server-minted `id` and `created_at`.

A recruiter may cancel a `SCHEDULED` interview at any time, moving it to `CANCELLED` and bumping `version`. Completing an interview moves `SCHEDULED` to `COMPLETED` and is permitted only when every panelist named in `panel_user_ids` has submitted a feedback row — otherwise the call is rejected with `ERR_FEEDBACK_INCOMPLETE`. Completion recomputes `aggregate_score` as the mean of the submitted feedback `score` values, rounded half-up to two decimal places, and assigns `recommendation` from that score: `aggregate_score` of at least 4.50 yields `STRONG_HIRE`; at least 3.50 but strictly less than 4.50 yields `HIRE`; at least 2.50 but strictly less than 3.50 yields `NO_HIRE`; strictly less than 2.50 yields `STRONG_NO_HIRE`. The lower threshold of each band is inclusive; the upper threshold is exclusive, so an `aggregate_score` of exactly 4.50 falls into `STRONG_HIRE` and an `aggregate_score` of exactly 3.50 falls into `HIRE`. Completion increments the interview's `version`.

### 3.6. Offer Approval, Extension, and Acceptance

A recruiter drafts an offer by supplying the `application_id`, the `base_salary_cents`, and the `signing_bonus_cents` (the signing bonus must be at least zero). The `base_salary_cents` must lie within the linked requisition's `[base_salary_min_cents, base_salary_max_cents]` band inclusive; a value outside the band is rejected with `ERR_SALARY_OUT_OF_BAND`. At most one offer per application may exist in the active set `{PENDING_APPROVAL, APPROVED, EXTENDED, ACCEPTED}`; a second active offer triggers `ERR_DUPLICATE_OFFER`. The new offer is stamped with the recruiter's `X-User-ID` as `submitter_user_id`, lands in state `PENDING_APPROVAL` with `version` 1, and adds its `base_salary_cents` to the department's `committed_offer_cents`.

Approval is a two-step ritual on the same endpoint. The first call must be made by a `CompApprover` whose `X-User-ID` differs from the offer's `submitter_user_id`; it stamps `comp_approver_user_id`, increments `version`, and keeps the offer in `PENDING_APPROVAL`. The second call must be made by a `VP` whose `X-User-ID` differs from both `submitter_user_id` and `comp_approver_user_id`; it stamps `vp_approver_user_id`, transitions the offer from `PENDING_APPROVAL` to `APPROVED`, and increments `version`. The comp-approver leg is recognised by `comp_approver_user_id` being null on entry; the VP leg is recognised by `comp_approver_user_id` being non-null on entry. Both legs require `expected_offer_version` in the payload as described in §2.7, and both legs apply the net-headroom budget check from §2.9. Rejection by either a comp-approver or a VP (subject to the same segregation check that `X-User-ID` differs from `submitter_user_id`) moves the offer from `PENDING_APPROVAL` to `REJECTED`, increments `version`, and subtracts the offer's `base_salary_cents` from the department's `committed_offer_cents`.

Extension is initiated by the original recruiter (or any recruiter; the role check, not an identity check, governs). Extending an `APPROVED` offer requires the linked requisition to still be `APPROVED`; on success the offer transitions to `EXTENDED`, `extended_at` is set to the current instant, `expires_at` is set to 14 days after `extended_at`, and the linked application is cascaded from `SCREENING` or `INTERVIEWING` into `OFFER_EXTENDED`. The offer's `version` is incremented.

The candidate then chooses one of three paths. Accepting an `EXTENDED` offer is permitted only while the current instant is strictly less than `expires_at`; if the current instant has reached or passed `expires_at`, the accept is rejected with `ERR_OFFER_EXPIRED` and the offer is treated as `REVOKED`. A successful accept moves the offer from `EXTENDED` to `ACCEPTED`, increments `version`, creates a new background check in state `INITIATED` for the offer and candidate, cascades the linked application to `HIRED`, bubbles the requisition's `filled_count` up by one (and may auto-transition the requisition to `CLOSED` when `filled_count` reaches `openings`), and rejects every other non-terminal application by the same candidate. When the candidate's `source_channel` is `REFERRAL`, the system additionally creates a referral bonus in state `PENDING_BGC` with the recipient's `referrer_user_id` copied from the candidate, the `offer_id` set to this offer, and `estimated_amount_cents` computed as described below; `payable_amount_cents` is left null until the background check resolves.

Declining an `EXTENDED` offer moves it to `DECLINED`, increments `version`, and subtracts the offer's `base_salary_cents` from `committed_offer_cents`. Revocation by a recruiter is permitted from either `APPROVED` or `EXTENDED`; it moves the offer to `REVOKED`, increments `version`, subtracts the offer's `base_salary_cents` from `committed_offer_cents`, and cascades any associated background check to `CANCELLED` and any non-`PAID` referral bonus to `VOID`. The system itself revokes any `EXTENDED` offer whose `expires_at` has been reached or passed; this auto-revoke applies the same cascades as a manual revoke. The mechanism for advancing the system clock is described in §3.8.

The estimated referral bonus is computed from a base, a salary band multiplier, and an optional diversity uplift. The base depends on the requisition's `target_level`: `JUNIOR` corresponds to 100,000 cents (one thousand dollars), `MID` to 200,000 cents (two thousand dollars), `SENIOR` to 400,000 cents (four thousand dollars), and `STAFF` to 600,000 cents (six thousand dollars). The salary band multiplier is read from the offer's `base_salary_cents`: a value strictly less than 10,000,000 cents (one hundred thousand dollars) applies a 1.0 multiplier; a value at or above that threshold but strictly less than 15,000,000 cents (one hundred fifty thousand dollars) applies a 1.25 multiplier; a value at or above that threshold but strictly less than 20,000,000 cents (two hundred thousand dollars) applies a 1.5 multiplier; and a value at or above 20,000,000 cents applies a 1.75 multiplier. The raw amount is the level base multiplied by the band multiplier. If the candidate qualifies as underrepresented — that is, the candidate's `eeo_ethnicity` is one of `BLACK`, `HISPANIC`, `NATIVE`, `PACIFIC`, or `TWO_OR_MORE`, **or** `eeo_disability` is true, **or** `eeo_veteran` is true — the raw amount is multiplied by 1.20 as a diversity uplift. The result is rounded half-up to integer cents and stored as `estimated_amount_cents`.

### 3.7. Background Checks, Hire Confirmation, and Bonus Payable

Acceptance of an offer creates a background check in state `INITIATED` with the offer's `offer_id` and the candidate's `candidate_id` recorded, plus a server-stamped `vendor_reference` synthesised at this moment.

A `ComplianceOfficer` advances the check from `INITIATED` to `IN_PROGRESS` by starting it. The same compliance officer (or any compliance officer subject to the independence rule of §2.8) resolves the check from `IN_PROGRESS` by supplying an `outcome` of either `PASSED` or `FAILED`. The resolver's `X-User-ID` must not be the `submitter_user_id` or `approver_user_id` of the underlying requisition; otherwise the resolution is rejected with `ERR_BGC_INDEPENDENCE`. On either outcome, `completed_at` is set to the current ISO 8601 UTC instant and the background check's `version` is incremented. If the linked offer is itself revoked while the check is still in `INITIATED` or `IN_PROGRESS`, the check is cascaded to `CANCELLED` and its `version` is incremented.

A `PASSED` outcome cascades any linked referral bonus from `PENDING_BGC` to `PAYABLE` and recomputes its `payable_amount_cents`. The recomputation re-runs the estimated-bonus formula against the current state of the offer, candidate, and requisition to produce a baseline, then applies a decay that depends on the elapsed time between the offer's acceptance and the background check's `completed_at`. The elapsed-day count is the integer floor of the difference (in days). When the delay is at most 30 days, the payable equals the baseline. When the delay is more than 30 but at most 60 days, the payable is the baseline multiplied by 0.75 and rounded half-up to integer cents. When the delay is more than 60 but at most 90 days, the payable is the baseline multiplied by 0.50 and rounded half-up to integer cents. When the delay exceeds 90 days, the payable is zero. The referral bonus's `version` is incremented as part of this cascade. The two computed amounts therefore differ in only one circumstance: the estimate captured at offer acceptance implicitly assumes a delay of zero days and always returns the baseline, while the payable captured at background-check clearance uses the actual elapsed delay and may produce a strictly smaller integer when clearance is slow.

A `FAILED` outcome rolls the hire back across multiple entities in one transaction: the linked offer is cascaded from `EXTENDED` or `ACCEPTED` to `REVOKED`; the linked application is cascaded from `HIRED` to `REJECTED`; any linked referral bonus still in `PENDING_BGC` is cascaded to `VOID`; and the requisition's `filled_count` is decremented. If the requisition had previously auto-`CLOSED`, it re-opens to `APPROVED` — `CLOSED` is therefore not strictly terminal under this rollback path. The denormalised `committed_offer_cents` on the affected department is recomputed as the offer leaves the active set.

A `PayrollOfficer` ultimately marks a `PAYABLE` referral bonus as `PAID`, or may manually void a `PAYABLE` bonus to `VOID`; both transitions increment the bonus's `version`. A bonus already in `PAID` is terminal — neither the revoke cascade nor the failure cascade touches it; only bonuses not yet in `PAID` are voided when the upstream offer or background check turns against the candidate.

A manual referral-bonus creation endpoint is reserved for back-fills and surfaces `ERR_NOT_REFERRAL_ELIGIBLE` if invoked against a candidate whose `source_channel` is not `REFERRAL` or whose `referrer_user_id` is null; in the normal cascade path the bonus is created silently and this error is never raised.

### 3.8. Operational Timekeeping

The offer-expiry mechanism depends on a clock. A test-driving capability allows a `PlatformAdmin` to advance the logical clock to a supplied `to_iso8601` instant, returning the new `now` and the list of `revoked_offer_ids` that were auto-revoked as part of the advance. Setting the clock cascades the auto-revoke described in §3.6 on every `EXTENDED` offer whose `expires_at` is now reached or passed, applying the same downstream cascades as a manual revoke. Outside of testing this endpoint is the only way the system experiences the passage of time for the purpose of expiry; it is not authenticated.

## 4. Endpoint Definitions

POST endpoints that create a new resource return HTTP 201; POST endpoints that mutate or transition an existing resource return HTTP 200; GET endpoints return HTTP 200. Error responses use the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/ats/departments` | Create a department | `PlatformAdmin` |
| GET | `/ats/departments/{id}` | Read a department (includes computed `committed_offer_cents`) | `PlatformAdmin`, `HiringManager`, `Recruiter` |
| GET | `/ats/departments` | List departments | `PlatformAdmin`, `HiringManager`, `Recruiter` |
| POST | `/ats/requisitions` | Create a requisition in `DRAFT` | `Recruiter` |
| GET | `/ats/requisitions/{id}` | Read a requisition (includes computed `filled_count`) | `PlatformAdmin`, `HiringManager`, `Recruiter` |
| GET | `/ats/requisitions` | List requisitions, optionally filtered by `department_id` or `status` | `PlatformAdmin`, `HiringManager`, `Recruiter` |
| POST | `/ats/requisitions/{id}/submit` | Submit for approval (`DRAFT` to `PENDING_APPROVAL`) | `Recruiter` |
| POST | `/ats/requisitions/{id}/approve` | Approve (`PENDING_APPROVAL` to `APPROVED`) | `HiringManager` |
| POST | `/ats/requisitions/{id}/reject` | Reject (`PENDING_APPROVAL` to `REJECTED`) | `HiringManager` |
| POST | `/ats/requisitions/{id}/cancel` | Cancel an `APPROVED` requisition, OCC-guarded | `HiringManager` |
| POST | `/ats/candidates` | Add a candidate to the pool | `Recruiter` |
| GET | `/ats/candidates/{id}` | Read a candidate | `Recruiter`, `HiringManager`, `PlatformAdmin` |
| GET | `/ats/candidates` | List candidates | `Recruiter`, `HiringManager`, `PlatformAdmin` |
| POST | `/ats/applications` | Apply a candidate to a requisition | `Recruiter` |
| GET | `/ats/applications/{id}` | Read an application | `Recruiter`, `HiringManager`, `Candidate`, `PlatformAdmin` |
| GET | `/ats/applications` | List applications | `Recruiter`, `HiringManager`, `PlatformAdmin` |
| POST | `/ats/applications/{id}/screen` | Advance `APPLIED` to `SCREENING` | `Recruiter` |
| POST | `/ats/applications/{id}/reject` | Reject an application | `Recruiter` |
| POST | `/ats/applications/{id}/withdraw` | Candidate withdraws | `Candidate` |
| POST | `/ats/interviews` | Schedule an interview for an application | `Recruiter` |
| GET | `/ats/interviews/{id}` | Read an interview | `Recruiter`, `HiringManager`, `PlatformAdmin` |
| GET | `/ats/interviews` | List interviews | `Recruiter`, `HiringManager`, `PlatformAdmin` |
| POST | `/ats/interviews/{id}/complete` | Complete; recomputes `aggregate_score` and `recommendation` | `Recruiter` |
| POST | `/ats/interviews/{id}/cancel` | Cancel a `SCHEDULED` interview | `Recruiter` |
| POST | `/ats/interview-feedback` | Submit a panelist feedback row | `HiringManager`, `Recruiter` |
| GET | `/ats/interview-feedback` | List interview feedback | `Recruiter`, `HiringManager`, `PlatformAdmin` |
| POST | `/ats/offers` | Create an offer in `PENDING_APPROVAL` | `Recruiter` |
| GET | `/ats/offers/{id}` | Read an offer | `Recruiter`, `HiringManager`, `CompApprover`, `VP`, `PlatformAdmin`, `Candidate` |
| GET | `/ats/offers` | List offers | `Recruiter`, `HiringManager`, `CompApprover`, `VP`, `PlatformAdmin` |
| POST | `/ats/offers/{id}/approve` | Two-step approval; OCC-guarded on `expected_offer_version` | `CompApprover`, `VP` |
| POST | `/ats/offers/{id}/reject` | Reject an offer from `PENDING_APPROVAL` | `CompApprover`, `VP` |
| POST | `/ats/offers/{id}/extend` | Extend to candidate (`APPROVED` to `EXTENDED`), 14-day expiry | `Recruiter` |
| POST | `/ats/offers/{id}/accept` | Candidate accepts (`EXTENDED` to `ACCEPTED`) | `Candidate` |
| POST | `/ats/offers/{id}/decline` | Candidate declines an `EXTENDED` offer | `Candidate` |
| POST | `/ats/offers/{id}/revoke` | Recruiter revokes an `APPROVED` or `EXTENDED` offer | `Recruiter` |
| GET | `/ats/background-checks/{id}` | Read a background check | `ComplianceOfficer`, `HiringManager`, `PlatformAdmin` |
| GET | `/ats/background-checks` | List background checks | `ComplianceOfficer`, `HiringManager`, `PlatformAdmin` |
| POST | `/ats/background-checks/{id}/start` | Move `INITIATED` to `IN_PROGRESS` | `ComplianceOfficer` |
| POST | `/ats/background-checks/{id}/resolve` | Resolve to `PASSED` or `FAILED` via `outcome` | `ComplianceOfficer` |
| GET | `/ats/referral-bonuses/{id}` | Read a referral bonus | `PayrollOfficer`, `HiringManager`, `PlatformAdmin` |
| GET | `/ats/referral-bonuses` | List referral bonuses | `PayrollOfficer`, `HiringManager`, `PlatformAdmin` |
| POST | `/ats/referral-bonuses/{id}/pay` | Mark `PAYABLE` as `PAID` | `PayrollOfficer` |
| POST | `/ats/referral-bonuses/{id}/void` | Manually void a `PAYABLE` bonus | `PayrollOfficer` |
| POST | `/ats/diversity-goals` | Create a goal for `(department_id, target_level, period_year)` | `PlatformAdmin` |
| GET | `/ats/diversity-goals/{id}` | Read a goal; recomputes pool and hire percentages | `PlatformAdmin`, `HiringManager` |
| GET | `/ats/diversity-goals` | List diversity goals | `PlatformAdmin`, `HiringManager` |
| POST | `/_clock/set_current_utc` | Test-driving: set the system clock; drives offer-expiry auto-transitions | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRECONDITION_FAILED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PANELIST_CONFLICT` | 422 |
| `ERR_BGC_INDEPENDENCE` | 403 |
| `ERR_DUPLICATE_APPLICATION` | 422 |
| `ERR_DUPLICATE_OFFER` | 422 |
| `ERR_INVALID_PANEL` | 422 |
| `ERR_PANELIST_NOT_ASSIGNED` | 422 |
| `ERR_FEEDBACK_INCOMPLETE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_INTERVIEW_OVERLAP_APPLICATION` | 422 |
| `ERR_INTERVIEW_OVERLAP_PANELIST` | 422 |
| `ERR_SALARY_OUT_OF_BAND` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NOT_REFERRAL_ELIGIBLE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
