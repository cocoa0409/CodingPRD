# Scholarship Review Management API — Product Requirements Document

## 1. Introduction

Universities run scholarship programmes whose end-to-end lifecycle — award design, student application, multi-stage review, public announcement, objection adjudication, and treasury-grade disbursement — currently lives in spreadsheets, paper forms, and a thicket of departmental email threads. The cost of this fragmentation is borne unevenly: students cannot tell whether they double-applied across two awards in the same category, department officers cannot prove that the supporting materials they validated were authentic at the moment of approval, reviewers can unknowingly evaluate applications from their own students, and finance officers are forced to reconcile tax withholding by hand for awards that vary by an order of magnitude in value.

This document specifies the back-end API for a unified Scholarship Review Management System that consolidates the workflow into a single auditable spine. The system models scholarships as configurable awards with eligibility gates, quota slices stratified by department, grade, and special-group attribute, and an explicit lifecycle from `DRAFT` through `OPEN`, `REVIEWING`, `ANNOUNCED`, `FINALIZED`, and ultimately `DISBURSED`. Around that spine, the API governs student application submission with duplicate-application detection, departmental preliminary review with completeness and authenticity checks, conflict-of-interest-aware reviewer assignment with weighted-rubric scoring and outlier trimming, public-announcement objection handling that can flip awards in flight, dynamic quota reallocation, and a segregation-of-duties disbursement pipeline that emits cryptographic-grade audit and external-sync events.

The system is implementation-agnostic with respect to storage technology but its API surface, state semantics, calculation precision, and error contract are normative — downstream test suites assert each rule literally.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which names the role under which the request is being made. When either header is absent or empty, the request is rejected with `ERR_AUTH_MISSING` (HTTP 401). When the supplied role is well-formed but is not authorised for the requested endpoint per the endpoint table in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles are recognised, spelled exactly as follows:

- `SchoolAdmin` — the central scholarship office administrator. Configures scholarships, opens and closes windows, assigns reviewers, rules on objections, and inspects the audit and external-sync logs.
- `DeptOfficer` — department-level officer. Performs preliminary completeness and authenticity review and acts as the first-level disbursement approver.
- `FinanceOfficer` — finance officer. Drafts disbursement plans, approves at the finance level (segregated from `DeptOfficer`), and executes the plan.
- `Student` — applicant. Creates, submits, withdraws, modifies, and corrects applications, and submits objections.
- `Reviewer` — member of the reviewer pool. Submits scores for applications to which they have been assigned.

For `SchoolAdmin`, `DeptOfficer`, `FinanceOfficer`, and `Student`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it in audit and approval-tracking fields — for example, the `dept_approver_id` and `finance_approver_id` fields of a `DisbursementPlan` are written from the acting principal's `X-User-ID` at approval time, and every `AuditEvent` captures `actor_id` from the same header — but it does not compare these opaque identifiers to any entity's `id`. A `Student` principal's `X-User-ID` is, by convention, stamped onto every `Application` they create as the `student_id`, and ownership comparisons (such as withdraw / modify / correct authorisation) compare the application's `student_id` to the requester's `X-User-ID` literally.

For `Reviewer`, `X-User-ID` is the `id` of the acting `Reviewer` entity in the reviewer pool. Ownership checks on score submission compare the target application's `ReviewerAssignment.reviewer_id` to `X-User-ID`; only a reviewer with a live assignment for a given application may submit a `Score` for it.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The default value of `limit` is 10; permitted values are integers from 1 to 100 inclusive. The default value of `offset` is 0 and any non-negative integer is accepted. List responses are sorted by `created_at` in ascending order, so older records appear first. The `meta` object of a list response includes `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when there exist additional records beyond the returned page.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted entity carries a server-minted `id` field. The `id` is a UUID expressed as the canonical hyphenated 36-character string and carries no type prefix; clients must not infer the kind of resource from the shape of its `id`.

Entities of kind `Scholarship`, `QuotaAllocation`, `Reviewer`, `Application`, `Objection`, and `DisbursementPlan` are versioned: in addition to `id`, each carries `created_at` (the ISO 8601 UTC timestamp with three fractional digits at which the entity was first persisted), `updated_at` (the same format, refreshed on every server-side mutation of the entity), and `version` (a non-negative integer initialised to 1 at creation and incremented by exactly one on every server-side mutation, whether direct or via cascade). When any mutating endpoint accepts a request body, that body may carry a `version` field; if it is supplied and does not equal the current `version` of the target entity, the server rejects the request with `ERR_VERSION_MISMATCH` (HTTP 409). Omitting `version` from the request body skips this optimistic-concurrency check.

`ReviewerAssignment`, `Score`, `DisbursementRecord`, `AuditEvent`, and `ExternalSyncEvent` are append-only and unversioned. Each carries only `id` and `created_at`; the fields `updated_at` and `version` are absent from these entities. These rows are never mutated after creation.

### 2.5. Path Hierarchy and Resource Resolution

Many resources are nested under their parent in URL form — for example, a `ReviewerAssignment` lives under its application which in turn lives under its scholarship. The server validates path parameters left to right: when the path begins with `/scholarships/{scholarshipId}`, the server first verifies that a `Scholarship` with that `id` exists. If not, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any further validation runs. If a deeper segment such as `/applications/{applicationId}` follows, the server verifies that an `Application` with that `id` exists and that its `scholarship_id` equals the parent `scholarshipId` from the URL; either failure yields `ERR_NOT_FOUND`. The same rule extends to objections, plans, and disbursement records: a child whose stored parent reference does not match the URL parent is treated as not found, never as a mismatch error.

### 2.6. Validation Priority

When a single request fails multiple checks, the server reports the first failure encountered in the following fixed priority order, evaluated top to bottom. Authentication (`ERR_AUTH_MISSING`) is checked first, then role authorisation (`ERR_FORBIDDEN`), then path existence (`ERR_NOT_FOUND`), then optimistic concurrency (`ERR_VERSION_MISMATCH` for mutating endpoints whose body contains `version`), then parent-scholarship state compatibility (`ERR_INVALID_STATE`), then target-entity state validity for the requested transition (also `ERR_INVALID_STATE`), then time-window enforcement (`ERR_WINDOW_CLOSED` or `ERR_WINDOW_NOT_OPEN` or `ERR_WINDOW_NOT_CLOSED`), then segregation-of-duties (`ERR_SOD_VIOLATION`), then conflict-of-interest on reviewer assignment (`ERR_COI_VIOLATION`), then department-scope match for departmental review (`ERR_DEPT_SCOPE_MISMATCH`), then same-scholarship duplicate-application (`ERR_DUPLICATE_APPLICATION_SAME`), then cross-scholarship same-category duplicate (`ERR_DUPLICATE_APPLICATION_CROSS`), then material completeness (`ERR_MATERIAL_MISSING`), then advisor-recommendation presence (`ERR_ADVISOR_REC_MISSING`), then eligibility (`ERR_ELIGIBILITY_FAIL`), then reviewer-count cardinality (`ERR_REVIEWER_COUNT_INVALID`), then rubric-key match on score submission (`ERR_SCORE_RUBRIC_MISMATCH`), then score over-quota (`ERR_SCORE_OVER_QUOTA`), then rubric-weight sum invariance (`ERR_RUBRIC_WEIGHT_INVALID`), then quota-mismatch at open transition (`ERR_QUOTA_MISMATCH`), then empty-plan check (`ERR_PLAN_EMPTY`), then objection-window enforcement (`ERR_WINDOW_CLOSED` for objection submission), then comment-required (`ERR_COMMENT_REQUIRED`), then cross-scholarship same-category window-overlap on scholarship create or edit (`ERR_SCHOLARSHIP_WINDOW_OVERLAP`). A malformed request body that violates schema-level constraints (wrong types, missing required keys) is rejected with `ERR_BAD_REQUEST` (HTTP 400) before any of the above are evaluated. The priority is what makes it deterministic which error a client receives when several would otherwise apply; the test suite asserts the exact code at every layered-failure boundary.

### 2.7. Monetary Precision and Rounding

Every monetary value crossing the API is expressed in integer cents — fields such as `per_award_amount_cents`, `family_income_ceiling_cents`, `student_family_income_cents`, `total_gross_cents`, `total_tax_cents`, `total_net_cents`, `gross_cents`, `tax_withheld_cents`, and `net_cents` are all integers and never carry a fractional component. Where the tax calculation requires intermediate fractional arithmetic the result of each rounding step yields an integer cent value, using the round-half-up convention (half-cent values are rounded away from zero, so 12.5 cents becomes 13 cents). Scores and GPAs are likewise represented as integers scaled by 100 — `student_gpa_x100`, `gpa_threshold_x100`, `aggregated_score_x100`, `raw_total_x100`, and `outlier_z_threshold_x100` are stored and compared as integers, with the multiplied-by-100 representation accommodating two decimal places of precision in the underlying real-valued quantity.

### 2.8. Audit Trail and External Synchronisation

Every state-changing operation that the system performs — whether driven directly by a request or by a cascade — produces an `AuditEvent` row. Each event captures its `event_type`, drawn from the set `APPLICATION_SUBMITTED`, `APPLICATION_WITHDRAWN`, `DEPT_REVIEW`, `SCORE_SUBMITTED`, `AGGREGATION_DONE`, `FINALIZED`, `OBJECTION_RULED`, `DISBURSEMENT_APPROVED`, `DISBURSEMENT_EXECUTED`, and `EXT_SYNC_EMITTED`, plus the `actor_role` and `actor_id` derived from the request headers (or the literal string "system" when the change is system-driven), the `target_entity` name and `target_id`, and a frozen `payload` snapshot that, for state transitions, contains a before/after pair of state values. Separately, transitions that the outside world must be notified of produce `ExternalSyncEvent` rows. Each carries a `kind` enumerated as one of `ACADEMIC_AFFAIRS_FINALIZED`, `FINANCE_DISBURSED`, `IM_NOTIFY_AWARD`, `IM_NOTIFY_REJECT`, or `IM_NOTIFY_OBJECTION_RULING`, along with the relevant `application_id` (omitted only when the event scope is scholarship-wide) and `scholarship_id`, plus a frozen `payload` snapshot that captures the body delivered to the downstream system. Both event tables are append-only and exposed read-only at the audit list endpoints.

### 2.9. Concurrent-Operation Serialisation

Several operations may race when issued in parallel; in every such race the system guarantees that exactly one writer succeeds and the loser receives a specific, named error. Two concurrent submit calls by the same student on the same scholarship serialise on the uniqueness of `(scholarship_id, student_id)` in `SUBMITTED` status — exactly one application reaches `SUBMITTED`, and the loser receives `ERR_DUPLICATE_APPLICATION_SAME`. Two concurrent score submissions that would each be the third score for the same application serialise on the count of `Score` rows; exactly one is recorded as the third, and the loser is rejected with `ERR_SCORE_OVER_QUOTA`. Two concurrent assign-reviewers calls for the same application serialise on the existence of any `ReviewerAssignment` for the application; exactly one set of three assignments is created, and the loser receives `ERR_REVIEWERS_ALREADY_ASSIGNED`. When a `DeptOfficer` and a `FinanceOfficer` simultaneously approve a `DisbursementPlan`, both expecting to be the first-level approver, exactly one wins on the plan's `status` and the loser receives `ERR_INVALID_STATE`. Two concurrent rulings on the same `Objection` likewise serialise on the objection's `status`, and the loser receives `ERR_INVALID_STATE`.

### 2.10. Time and the Test Clock

Time-gated transitions reference a logical "now" supplied by the server. Production deployments would use wall-clock time; in this specification an admin-only test-driving capability allows a `SchoolAdmin` to set the system's logical "now" to a supplied ISO 8601 datetime via the `to` field of the clock-advance endpoint. A complementary sweep capability runs all pending auto-transitions for any scholarship whose application or announcement window has elapsed against the current logical "now". Both capabilities are required for testability of windowed transitions and are listed in §4.

## 3. Business Logic & Workflows

### 3.1. Designing a Scholarship and its Quota

A new scholarship is brought into being by a `SchoolAdmin`, who supplies the award's identifying `code` (unique across all scholarships, between 3 and 32 characters inclusive), its human-readable `name`, and the `category` — one of `MERIT`, `NEED`, `RESEARCH`, or `SPECIAL_GROUP`. The award value is captured as `per_award_amount_cents`, an integer at least 1, and the total number of recipients across all departments as `total_quota`, also at least 1. Eligibility gates are pre-declared at this stage: `gpa_threshold_x100` is the minimum GPA scaled by 100 (so the value 350 means a GPA of 3.50), `eligible_majors` is an array of major codes (an empty array means all majors are eligible), `eligible_grades` is an array of grade levels (again, empty means all grades), and `family_income_ceiling_cents` is the annual household-income upper bound used only for `NEED` scholarships (it must be null for any non-`NEED` category). The `required_materials` array enumerates the supporting documents an applicant must upload, drawn from the set `TRANSCRIPT`, `AWARD_CERT`, `POVERTY_PROOF`, `ADVISOR_REC`. Three temporal markers fence the lifecycle: `application_window_start` (inclusive UTC ISO 8601 datetime) and `application_window_end` (exclusive UTC ISO 8601 datetime, strictly after the start), plus `announcement_window_end` (exclusive UTC ISO 8601 datetime, strictly after `application_window_end`). The rubric is supplied as `rubric_weights`, an object whose keys name scoring criteria and whose values are non-negative integer weights that must sum to exactly 100; on creation and on subsequent edit, any other sum is rejected with `ERR_RUBRIC_WEIGHT_INVALID`. An optional `outlier_z_threshold_x100` (z-score threshold scaled by 100; default 200, i.e. |z| of 2.00) controls outlier trimming during aggregation.

At the moment a scholarship is created the server checks the application window against every other scholarship of the same `category` whose `status` is not `DISBURSED`. For this check, intervals are half-open `[application_window_start, application_window_end)` — windows that touch exactly at a boundary (one scholarship's `application_window_end` equal to another's `application_window_start`) do not overlap and are accepted. Any non-empty overlap with such a peer scholarship is rejected with `ERR_SCHOLARSHIP_WINDOW_OVERLAP`. The same overlap check is re-run whenever a scholarship in `DRAFT` is edited in a way that changes its window. Note that this scholarship-level overlap rule and the per-student cross-application rule discussed in §3.3 use different interval semantics; do not conflate them.

A new scholarship enters `DRAFT` status. Only while in `DRAFT` may a `SchoolAdmin` add quota slices, edit the scholarship, or otherwise restructure it. Each quota slice is a `QuotaAllocation` row that belongs to a parent scholarship and carries a `department_code`, a `grade` (integer, typically 1 through 4), and a `special_group` qualifier — one of `NONE` (the default), `GENDER_FEMALE`, `GENDER_MALE`, `ETHNIC_MINORITY`, or `DISABILITY`. The `initial_slots` field captures the originally allocated count for this slice (a non-negative integer); `current_slots` is initialised equal to `initial_slots` and may be revised by dynamic adjustment, while `filled_slots` is the running count of applications in the slice with `status` `AWARDED` or `DISBURSED` and starts at zero. A `reallocated_from_ids` array, maintained by the server, records, in chronological order, the ids of donor quota slices whose unfilled slots were moved into this slice during reallocation.

### 3.2. Opening the Application Window

To progress a scholarship from `DRAFT` to `OPEN`, a `SchoolAdmin` invokes the scholarship state-transition capability with target `to_status` of `OPEN`, or the system tick advances when the logical "now" reaches `application_window_start`. Before the transition is permitted, the server checks three preconditions: the `rubric_weights` of the scholarship must sum to exactly 100 (else `ERR_RUBRIC_WEIGHT_INVALID`), the sum of `initial_slots` across all `QuotaAllocation` rows for this scholarship must equal exactly the scholarship's `total_quota` (else `ERR_QUOTA_MISMATCH`), and the logical "now" must be at least `application_window_start` (else `ERR_WINDOW_NOT_OPEN`). The transition itself emits no event; the scholarship simply becomes available to students.

### 3.3. Student Application: Form, Submission, and Duplicate Detection

Students compose applications against an `OPEN` scholarship. An application begins in `DRAFT` and is the only state in which the student may freely revise it. At application-creation time, the `Student` posts payload fields that the server stamps onto the new `Application`: `student_department_code` (which feeds both quota-slice selection and the conflict-of-interest department check), `student_advisor_id` (the `Reviewer` id of the student's academic supervisor), `student_major`, `student_grade`, and `student_gpa_x100`. For `NEED` applications, `student_family_income_cents` must be supplied — the field is otherwise null. An optional `student_special_group` (defaulting to `NONE`) marks an attribute used to pick the quota slice. The `uploaded_materials` array enumerates which of the `required_materials` the student has uploaded for this application. An `advisor_recommendation_id` (the `Reviewer` id who issued the recommendation, required only when the scholarship's `required_materials` contains `ADVISOR_REC`) completes the payload. Creation always succeeds at `status` `DRAFT`; the server records the requester's `X-User-ID` as the application's `student_id`. While in `DRAFT`, the student may edit form fields — `student_major`, `student_grade`, `student_gpa_x100`, `student_family_income_cents`, `uploaded_materials`, `advisor_recommendation_id` — via the application-update capability.

Submission, transitioning the application from `DRAFT` to `SUBMITTED`, performs a layered set of checks. First, the parent scholarship's `status` must be `OPEN`; if it is anything else, the submit is rejected with `ERR_WINDOW_NOT_OPEN`. Second, the logical "now" must be strictly earlier than the scholarship's `application_window_end`; otherwise `ERR_WINDOW_CLOSED`. Third, eligibility is evaluated against four conditions, all of which must hold: the student's `student_gpa_x100` is at least the scholarship's `gpa_threshold_x100` (inclusive); the scholarship's `eligible_majors` is empty or the student's `student_major` is one of its elements; the scholarship's `eligible_grades` is empty or the student's `student_grade` is one of its elements; and, if and only if the scholarship's `category` is `NEED`, the student's `student_family_income_cents` is non-null and is at most the scholarship's `family_income_ceiling_cents` (inclusive). If any of the four fails, `ERR_ELIGIBILITY_FAIL` is returned. Fourth, the student's `uploaded_materials` must be a superset of the scholarship's `required_materials`; missing materials produce `ERR_MATERIAL_MISSING`. Fifth, when `ADVISOR_REC` is among the required materials, `advisor_recommendation_id` must reference a `Reviewer` whose `status` is `ACTIVE`; otherwise `ERR_ADVISOR_REC_MISSING`. Sixth, the student must have no other application against this same scholarship in any non-terminal status — meaning anything other than `WITHDRAWN`, `REVOKED`, `DISBURSED`, or `NOT_AWARDED`; otherwise `ERR_DUPLICATE_APPLICATION_SAME`. Seventh, the student must have no application against another scholarship of the same `category` whose application window collides with this scholarship's under a three-day buffer rule. For the cross-application check, the buffered interval for each scholarship is the closed-closed interval running from its `application_window_start` to its `application_window_end` extended by an additional three days (i.e. `application_window_end + 3 days`, inclusive). Two scholarships of the same category collide when their buffered closed-closed intervals share at least one point in common; if the student already has any non-terminal application against such a colliding peer, the new submission is rejected with `ERR_DUPLICATE_APPLICATION_CROSS`. Note the asymmetry from the scholarship-creation rule discussed in §3.1: that rule uses half-open intervals (boundary touching is allowed); this per-student rule uses three-day-buffered closed-closed intervals (boundary touching of buffered intervals counts as collision).

On successful submission the application transitions `DRAFT → SUBMITTED` and the server records an `AuditEvent` with `event_type` `APPLICATION_SUBMITTED`.

A `SUBMITTED` application may be withdrawn or sent back to `DRAFT` by the same student. The withdraw capability transitions `SUBMITTED → WITHDRAWN` and is permitted only while the logical "now" is strictly earlier than `application_window_end` (else `ERR_WINDOW_CLOSED`); it emits an `AuditEvent` with `event_type` `APPLICATION_WITHDRAWN`. The modify capability transitions `SUBMITTED → DRAFT`, subject to the same window check (`ERR_WINDOW_CLOSED` outside the window), and emits no audit event because it is a precursor to a later re-submission.

When the application window closes — by an admin transitioning the scholarship to `REVIEWING`, or by the system tick when the logical "now" reaches `application_window_end` — every application still in `DRAFT` is moved by cascade to `WITHDRAWN`, and each such cascade records an `AuditEvent` with `event_type` `APPLICATION_WITHDRAWN`. Note that a transition from `OPEN` to `REVIEWING` triggered by an admin call also requires that the logical "now" be at least `application_window_end`; otherwise `ERR_WINDOW_NOT_CLOSED`.

### 3.4. Departmental Preliminary Review and Correction

Once the scholarship is in `REVIEWING`, the `SUBMITTED` applications are subjected to a department-level completeness and authenticity check by a `DeptOfficer`. The officer issues a `decision` of either `PASS` or `REJECT` against an application, plus a `comment`, plus an `is_authentic_flags` map asserting that each item in the application's `uploaded_materials` has been authenticated. The department-review capability is permitted only when the parent scholarship is in `REVIEWING` status (else `ERR_INVALID_STATE`), and only when the officer's own department code matches the application's `student_department_code` (else `ERR_DEPT_SCOPE_MISMATCH`, HTTP 403). On a `PASS`, the server additionally re-checks completeness — `uploaded_materials` must still be a superset of `required_materials`, and every entry in `is_authentic_flags` corresponding to a required material must be true; either failure yields `ERR_MATERIAL_INCOMPLETE`. A successful `PASS` transitions `SUBMITTED → DEPT_PRELIM_PASSED`, overwrites the application's `dept_review_comment` with the supplied `comment` (which may be empty on `PASS`), and records an `AuditEvent` with `event_type` `DEPT_REVIEW` and `payload.decision` equal to `PASS`. On a `REJECT`, the officer's `comment` must be a non-empty string (else `ERR_COMMENT_REQUIRED`); a successful `REJECT` transitions `SUBMITTED → DEPT_PRELIM_REJECTED`, overwrites `dept_review_comment` with the rejecting `comment`, and records the corresponding `DEPT_REVIEW` audit event with `payload.decision` of `REJECT`.

A student whose application is in `DEPT_PRELIM_REJECTED` may issue a correction. The correction capability transitions `DEPT_PRELIM_REJECTED → SUBMITTED` for re-review. It accepts a `replaced_materials` array, each entry of which must already be present in the application's current `uploaded_materials` (else `ERR_MATERIAL_MISSING`); the scholarship must still be in `REVIEWING` status (else `ERR_INVALID_STATE`). The side effect of a successful correction is to clear the application's `dept_review_comment` to null.

### 3.5. Reviewer Assignment and Conflict-of-Interest

The reviewer pool is itself maintained by `SchoolAdmin` actions: a new `Reviewer` is created with a `full_name`, a home `department_code`, and an optional `family_relation_student_ids` array, and enters the pool in `status` `ACTIVE`. The same `SchoolAdmin` may later update a reviewer's `status` (toggling between `ACTIVE` and `SUSPENDED`) or amend the declared `family_relation_student_ids` list.

When an application is in `DEPT_PRELIM_PASSED`, the central scholarship office assigns reviewers. A `SchoolAdmin` calls the assign-reviewers capability with a payload `reviewer_ids` containing exactly three reviewer ids; any other cardinality yields `ERR_REVIEWER_COUNT_INVALID`. The three ids must be distinct from each other; duplicates yield `ERR_REVIEWER_DUPLICATE`. Each of the three reviewers' `status` must equal `ACTIVE`; otherwise `ERR_REVIEWER_NOT_ACTIVE`. Each of the three must also pass three independent conflict-of-interest checks: the reviewer's `department_code` must differ from the application's `student_department_code` (the same-department check), the reviewer's `id` must not equal the application's `student_advisor_id` (the same-supervisor check), and the application's `student_id` must not appear in the reviewer's `family_relation_student_ids` array (the family-relation check). Failure of any of the three checks against any of the three proposed reviewers yields `ERR_COI_VIOLATION`. On success the server creates three `ReviewerAssignment` rows — each carrying `application_id`, `reviewer_id`, and `assigned_at` — and the application transitions `DEPT_PRELIM_PASSED → UNDER_REVIEW`. If any `ReviewerAssignment` already exists for this application, a fresh assign-reviewers call is rejected with `ERR_REVIEWERS_ALREADY_ASSIGNED`.

A `Reviewer` whose assignment for an application is live may then submit a `Score`. The score payload supplies `criterion_scores` — an object whose keys must be exactly the set of keys of the scholarship's `rubric_weights` (the same set, no more and no fewer; any discrepancy yields `ERR_SCORE_RUBRIC_MISMATCH`) and whose values are integers in the range 0 to 100 inclusive — and an optional `comment`. The server computes `raw_total_x100` as the sum, taken over every criterion, of the integer `criterion_scores` value for that criterion multiplied by its `rubric_weights` value; because each weight is between 0 and 100 inclusive and the weights sum to 100, `raw_total_x100` is necessarily a non-negative integer between 0 and 10,000 inclusive. The new score's `is_outlier` flag is initialised to false at write time; outlier flagging happens later during aggregation. If a fourth score submission is attempted for an application that already has three scores, or a reviewer attempts to submit two scores for the same application, the request is rejected with `ERR_SCORE_OVER_QUOTA`.

### 3.6. Score Aggregation: Trimmed vs. Full Mean

The instant the third `Score` row is recorded for an application, the system automatically advances the application from `UNDER_REVIEW` to `REVIEW_COMPLETE` and computes its final `aggregated_score_x100`. Aggregation works as follows. Let the three scores' `raw_total_x100` values be denoted as the inputs. The arithmetic mean of the three is the simple average, and the standard deviation is the population standard deviation taken over the same three values. When the standard deviation is strictly greater than zero, each score is examined for outlier status: a score is marked as an outlier — its `is_outlier` flag flipped to true — when the absolute difference between its `raw_total_x100` and the mean, multiplied by 100, is strictly greater than the scholarship's `outlier_z_threshold_x100` multiplied by the standard deviation (this is the variant referred to as the trimmed-mean variant; equivalent to checking whether the absolute z-score exceeds the configured threshold). Scores that are not flagged as outliers form the kept set. The application's `aggregated_score_x100` is then set to the arithmetic mean of the `raw_total_x100` values across the kept set, rounded half-up to the nearest integer.

The full-mean variant applies in the degenerate case: when the standard deviation across the three scores is zero (every score is identical, including the boundary case of a single-active-reviewer slice that drove all three to the same value), no score is flagged as an outlier and the `aggregated_score_x100` is the round-half-up of the simple mean. In the further-degenerate case where every score is somehow trimmed (which can only happen when the standard deviation is zero and the threshold rule is degenerately satisfied), the `aggregated_score_x100` falls back to the round-half-up of the mean of all three input values. The chosen variant is implicit — selected by whether the standard deviation is positive — and the formula is the same in spirit: average the surviving `raw_total_x100` values and round half-up. Submitting an aggregation result records an `AuditEvent` with `event_type` `AGGREGATION_DONE`.

### 3.7. Dynamic Quota Adjustment

The transition from `OPEN` to `REVIEWING` carries with it a recalculation of the quota slices to reflect actual demand. For each `QuotaAllocation` slice — keyed by the triple of `department_code`, `grade`, and `special_group` — the server counts the demand: the number of applications whose triple matches and whose `status` is one of `SUBMITTED`, `DEPT_PRELIM_PASSED`, or `DEPT_PRELIM_REJECTED` (anything past `SUBMITTED` that has not yet withdrawn). The `current_slots` of every slice begins at the baseline equal to its `initial_slots`.

Adjustment then runs as follows. Any slice whose demand count is less than its `initial_slots` donates its surplus — the difference between `initial_slots` and demand count — into a donor pool; let the donor pool's total be the sum of these per-slice surpluses. Any slice whose demand count strictly exceeds its `initial_slots` is over-demanded; let the over-demand total be the sum, across all over-demanded slices, of the excess demand. For every over-demanded slice with positive over-demand, when the over-demand total is positive, the slice's share of the donor pool is computed as the floor of the donor pool multiplied by that slice's individual excess demand divided by the over-demand total, and that share is added to the slice's `initial_slots` to yield its new `current_slots`. After all over-demanded slices receive their floor-share, any remainder slots from the floor-division step are distributed one at a time to the slices in descending order of demand count, with ties broken by ascending lexical order of the slice's `id`, until the remainder is exhausted. Slices whose demand count is at most their `initial_slots` have their `current_slots` set to exactly the demand count — the system never awards beyond demand. Throughout, slot counts are integers; the floor and remainder steps make this rigorous.

### 3.8. Announcement, Ranking, and Cascading Award Decisions

When the scholarship transitions from `REVIEWING` to `ANNOUNCED` — by `SchoolAdmin` action — every non-rejected application must have reached `REVIEW_COMPLETE` (i.e. every application that is not in `WITHDRAWN`, `DRAFT`, or `DEPT_PRELIM_REJECTED` must be in `REVIEW_COMPLETE`); otherwise the transition is rejected with `ERR_REVIEW_NOT_COMPLETE`. On a permitted transition the system performs two chained calculations.

First, ranking and award: for each slice (keyed by the same triple of `department_code`, `grade`, and `special_group`), the candidates are the `REVIEW_COMPLETE` applications matching the slice. They are sorted in descending order of `aggregated_score_x100`; ties are broken by ascending lexical order of `Application` `id`. Each candidate's `final_rank` is its 1-based position in this sorted list. Every candidate whose `final_rank` is at most the slice's `current_slots` transitions `REVIEW_COMPLETE → AWARDED`, and the slice's `filled_slots` is incremented by one for each. Every candidate whose `final_rank` is strictly greater than `current_slots` transitions `REVIEW_COMPLETE → NOT_AWARDED`. Both transitions are explicit and recorded per application.

Second, unfilled-quota reallocation: after ranking, each slice's `filled_slots` is at most its `current_slots`. The surplus pool is the sum, across every slice, of the difference between `current_slots` and `filled_slots`. Recipient slices are those that still hold at least one `NOT_AWARDED` application whose original rank would qualify under additional headroom. Recipient slices are sorted in ascending order of the ratio `filled_slots` divided by `current_slots` (using a fallback ratio of 1.0 when `current_slots` is zero), with ties broken by ascending lexical order of slice `id`. The waterfall then proceeds slice by slice while the surplus pool remains positive: within each recipient slice, the `NOT_AWARDED` applications are sorted in descending order of `aggregated_score_x100`, ties broken by ascending lexical order of `Application` `id`; the system takes the smaller of the remaining surplus pool and the number of available candidates, promotes those top candidates from `NOT_AWARDED → AWARDED` as cascade promotion, increments the slice's `filled_slots` by one for each promotion, and appends the donor slice's `id` to the slice's `reallocated_from_ids` for each promotion (in chronological order of the reallocation events). The surplus pool is decremented by the number of promotions performed in this slice before the loop advances.

The `REVIEWING → ANNOUNCED` transition itself, after both chained calculations, emits one `ExternalSyncEvent` with `kind` `ACADEMIC_AFFAIRS_FINALIZED` (scholarship-scoped, so its `application_id` is absent), one `IM_NOTIFY_AWARD` external-sync event per `AWARDED` application, one `IM_NOTIFY_REJECT` per `NOT_AWARDED` application, and one `AuditEvent` with `event_type` `FINALIZED`.

### 3.9. Public Announcement and Objections

During the announcement window — the interval from the moment the scholarship enters `ANNOUNCED` until the logical "now" reaches `announcement_window_end` — any student may submit an `Objection` against any application. The objection payload carries the `application_id` of the application being objected to, an `objector_student_id` recording the student raising the objection (which may be the applicant themselves or another student), a `reason_code` of one of `MATERIAL_FALSE`, `SCORING_ERROR`, `ELIGIBILITY_BREACH`, or `COI_BREACH`, and a free-form `description`. An objection may be submitted only while the logical "now" is strictly earlier than the scholarship's `announcement_window_end`; later attempts are rejected with `ERR_WINDOW_CLOSED`. A new objection enters `status` `PENDING`. Its `ruling_comment` is null until adjudication.

A `SchoolAdmin` rules on a `PENDING` objection by issuing a `decision` of `UPHOLD` or `DISMISS`, together with a `ruling_comment`. Both rulings require the parent scholarship to be in `ANNOUNCED` status (else `ERR_INVALID_STATE`), and both require a non-empty `ruling_comment` (else `ERR_COMMENT_REQUIRED`). Upholding additionally requires the logical "now" to be strictly earlier than `announcement_window_end` (else `ERR_WINDOW_CLOSED`); dismissals are not bound by this latter check. An upheld ruling transitions the objection from `PENDING` to `UPHELD`. If the objected-against application is currently in `AWARDED`, that application transitions `AWARDED → REVOKED` by cascade; on revocation the application's `revocation_reason` is set to `OBJECTION_UPHELD` (the only other value `revocation_reason` may take is `AUDIT_FAILURE`, reserved for post-disbursement audit-driven revocations and not produced by any state transition in this specification; for any other path `revocation_reason` remains null), the slice's `filled_slots` is decremented by one, and a single promotion cascade runs: the highest-ranked `NOT_AWARDED` application in the same slice (selected by descending `aggregated_score_x100`, then ascending `student_id` lexically as the tie-break) is flipped to `AWARDED`. The upheld ruling also emits an `ExternalSyncEvent` with `kind` `IM_NOTIFY_OBJECTION_RULING`. A dismissed ruling transitions the objection to `DISMISSED` and emits the same `IM_NOTIFY_OBJECTION_RULING` external-sync event; no cascade follows.

When the scholarship is later moved from `ANNOUNCED` to `FINALIZED` — either by `SchoolAdmin` action or by the system tick when the logical "now" reaches `announcement_window_end` — the server enforces two preconditions: the logical "now" must be at least `announcement_window_end` (else `ERR_WINDOW_NOT_CLOSED`), and no objection against any application of this scholarship may still be in `PENDING` (else `ERR_OBJECTION_PENDING`).

### 3.10. Disbursement Plan: Approval and Execution

After finalisation, a `FinanceOfficer` creates a `DisbursementPlan` for the scholarship. The plan's payload carries the default `payment_channel` of `BANK` or `CAMPUS_CARD`. On creation the server aggregates the set of applications currently in `AWARDED` for this scholarship: `total_gross_cents` is the sum of the scholarship's `per_award_amount_cents` across that set; `total_tax_cents` is the sum of the tax that would be withheld per record per the tax calculation described below; and `total_net_cents` equals `total_gross_cents` minus `total_tax_cents`. These three totals are pinned at create time and are not revised by later approvals; if no application is currently `AWARDED` so that `total_gross_cents` would be zero, the subsequent approval (not the creation itself) is rejected with `ERR_PLAN_EMPTY`. The plan begins in `status` `DRAFT`.

Approval proceeds through two distinct levels. A `DeptOfficer` requests department-level approval with `level` of `DEPT`; the parent scholarship must be in `FINALIZED` status (else `ERR_INVALID_STATE`) and the plan's `total_gross_cents` must be strictly greater than zero (else `ERR_PLAN_EMPTY`). On success the plan transitions `DRAFT → DEPT_APPROVED`, the plan's `dept_approver_id` is set to the requesting `DeptOfficer`'s `X-User-ID`, and an `AuditEvent` with `event_type` `DISBURSEMENT_APPROVED` and `payload.level` of `DEPT` is recorded. While the plan is in `DEPT_APPROVED` the same `DeptOfficer` who approved it (and only that officer) may revert it back to `DRAFT` — a different `DeptOfficer` who attempts to revert is rejected with `ERR_FORBIDDEN`; the revert also requires the scholarship to still be in `FINALIZED` (else `ERR_INVALID_STATE`). On a successful revert the plan transitions `DEPT_APPROVED → DRAFT`, the `dept_approver_id` is cleared back to null, and the snapshotted `total_gross_cents` and `total_tax_cents` remain unchanged — the system never recomputes them after creation, even across revert cycles. A revert records an `AuditEvent` with `event_type` `DISBURSEMENT_APPROVED`, `payload.level` of `DEPT`, and `payload.action` of `REVERT`.

A `FinanceOfficer` then requests finance-level approval with `level` of `FINANCE`; the requester's `X-User-ID` must differ from the plan's `dept_approver_id` (else `ERR_SOD_VIOLATION`). On success the plan transitions `DEPT_APPROVED → FINANCE_APPROVED`, the `finance_approver_id` is set to the requester's `X-User-ID`, and another `DISBURSEMENT_APPROVED` audit event with `payload.level` of `FINANCE` is recorded.

Execution closes the loop. The plan-execute capability is permitted only to the same `FinanceOfficer` whose `X-User-ID` equals the plan's `finance_approver_id` (else `ERR_EXECUTOR_MISMATCH`). On execution the plan transitions `FINANCE_APPROVED → EXECUTED`. For each application currently in `AWARDED`, a single `DisbursementRecord` is created, carrying its parent `plan_id`, the originating `application_id` and the recipient `student_id`, the executed-time fields `gross_cents` (taken from the scholarship's current `per_award_amount_cents`), `tax_withheld_cents` (computed per the tax rule below), `net_cents` (equal to `gross_cents` minus `tax_withheld_cents`), `payment_channel` (determined by the routing rule below), and `executed_at` (the logical "now" at execution time). An `AuditEvent` with `event_type` `DISBURSEMENT_EXECUTED` is recorded.

Tax withholding for each record is computed in two independent components which are each rounded to integer cents individually and then summed. The first component, the tiered base tax, is computed by waterfall over four tiers defined by lower-inclusive and upper-exclusive boundaries: the interval from 0 cents up to 500,000 cents excluded is taxed at 0 percent; from 500,000 cents up to 2,000,000 cents excluded at 3 percent; from 2,000,000 cents up to 5,000,000 cents excluded at 10 percent; and from 5,000,000 cents up to 1,000,000,000 cents excluded at 20 percent. The waterfall walks the tiers in order: in each tier, the slice amount is the smaller of the gross amount in cents and the tier's upper boundary, minus the tier's lower boundary, considered only when this slice amount is positive; the slice amount is multiplied by the tier's rate-percent and divided by 100, then rounded half-up to integer cents, and this per-tier rounded amount is accumulated into the base tax. The walk stops when the gross amount in cents does not exceed the current tier's lower boundary. The second component, the education-fund surcharge, is a flat charge of three-thousandths of the gross amount in cents (in other words, the gross amount multiplied by 3 then divided by 1000), rounded half-up to integer cents as a single rounding. The `tax_withheld_cents` recorded for the record is the sum of the rounded base tax and the rounded surcharge — note the pinned ordering: each component is rounded independently to integer cents first, and then the two integer results are added; the alternative of computing the unrounded sum and rounding once at the end is explicitly forbidden because at fractional-edge gross values the two procedures can differ by one cent.

Channel routing for each record is then applied: when the record's `net_cents` is at least 1,000,000 cents (in other words, when the net payout is at least 10,000.00 yuan in the customary local-currency reading of cents), the record's `payment_channel` is overridden to `BANK`, regardless of the plan's default; otherwise the record's `payment_channel` equals the plan's `payment_channel`. The boundary is inclusive on the `BANK` side: a record whose `net_cents` is exactly 1,000,000 cents routes to `BANK`.

### 3.11. Final Disbursement and Archival

Once a `DisbursementPlan` is in `EXECUTED`, the scholarship may be advanced from `FINALIZED` to `DISBURSED` by a `FinanceOfficer`. The transition requires that a `DisbursementPlan` for this scholarship has reached `EXECUTED` (else `ERR_DISBURSEMENT_NOT_EXECUTED`). On success, every application currently in `AWARDED` for this scholarship transitions `AWARDED → DISBURSED` by cascade, and each cascaded application records its own `AuditEvent` and emits one `ExternalSyncEvent` with `kind` `FINANCE_DISBURSED`. Simultaneously, the `DisbursementPlan` transitions `EXECUTED → ARCHIVED` automatically — no explicit call is required to archive an executed plan; archival is the inevitable consequence of scholarship-level disbursement.

### 3.12. Version Propagation and `updated_at` Discipline

Every direct or cascade-driven mutation of a versioned entity increments its `version` by exactly one and refreshes its `updated_at` to the logical "now". This applies in particular to cascade flows: when an objection is upheld and the cascaded application transitions to `REVOKED`, both the objection and the application have their `version` and `updated_at` updated; when a single promotion follows, the promoted application's `version` and `updated_at` are likewise updated. When a scholarship's transition triggers a cascade affecting many applications and quota allocations, every affected entity has its own `version` and `updated_at` advanced. A client that holds a stale `version` and supplies it in a later mutating call to any of these entities will be rejected with `ERR_VERSION_MISMATCH`.

## 4. Endpoint Definitions

The API uses the conventional HTTP status code rules: a successful new-resource creation returns 201, while a successful modification of an existing resource (state transition, field update, or read) returns 200. Error responses follow the priority ordering described in §2.6 and use the codes catalogued in §5. Bodies and side effects for each endpoint are governed by the narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/scholarships` | Create a new Scholarship (DRAFT) | `SchoolAdmin` |
| GET | `/scholarships/{scholarshipId}` | Get a Scholarship | `SchoolAdmin`, `DeptOfficer`, `FinanceOfficer`, `Student`, `Reviewer` |
| PATCH | `/scholarships/{scholarshipId}` | Update Scholarship (only while DRAFT) | `SchoolAdmin` |
| POST | `/scholarships/{scholarshipId}/state` | Transition Scholarship status | `SchoolAdmin` |
| POST | `/scholarships/{scholarshipId}/quota-allocations` | Create a QuotaAllocation row (only while Scholarship is DRAFT) | `SchoolAdmin` |
| GET | `/scholarships/{scholarshipId}/quota-allocations` | List QuotaAllocations for a Scholarship | `SchoolAdmin`, `DeptOfficer` |
| POST | `/reviewers` | Create a Reviewer (pool entry) | `SchoolAdmin` |
| GET | `/reviewers/{reviewerId}` | Get a Reviewer | `SchoolAdmin`, `DeptOfficer` |
| PATCH | `/reviewers/{reviewerId}` | Update Reviewer (status, family_relation_student_ids) | `SchoolAdmin` |
| POST | `/scholarships/{scholarshipId}/applications` | Create an Application (DRAFT) | `Student` |
| GET | `/scholarships/{scholarshipId}/applications/{applicationId}` | Get an Application | `SchoolAdmin`, `DeptOfficer`, `Reviewer`, `Student` |
| PATCH | `/scholarships/{scholarshipId}/applications/{applicationId}` | Update Application form fields (only while DRAFT) | `Student` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/submit` | Submit an Application (DRAFT→SUBMITTED) | `Student` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/withdraw` | Withdraw an Application (SUBMITTED→WITHDRAWN) | `Student` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/modify` | Send Application back to DRAFT to edit (SUBMITTED→DRAFT) | `Student` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/dept-review` | Department preliminary review | `DeptOfficer` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/correct` | Student corrects after rejection (DEPT_PRELIM_REJECTED→SUBMITTED) | `Student` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/assign-reviewers` | Assign 3 reviewers (DEPT_PRELIM_PASSED→UNDER_REVIEW) | `SchoolAdmin` |
| POST | `/scholarships/{scholarshipId}/applications/{applicationId}/scores` | Submit a reviewer score (1 of 3) | `Reviewer` |
| GET | `/scholarships/{scholarshipId}/applications/{applicationId}/scores` | List Scores for an Application | `SchoolAdmin`, `DeptOfficer` |
| POST | `/scholarships/{scholarshipId}/objections` | Submit an Objection during announcement window | `Student` |
| GET | `/scholarships/{scholarshipId}/objections/{objectionId}` | Get an Objection | `SchoolAdmin`, `Student` |
| POST | `/scholarships/{scholarshipId}/objections/{objectionId}/rule` | Rule on an Objection (PENDING→UPHELD/DISMISSED) | `SchoolAdmin` |
| POST | `/scholarships/{scholarshipId}/disbursement-plans` | Create a DisbursementPlan (DRAFT) | `FinanceOfficer` |
| GET | `/scholarships/{scholarshipId}/disbursement-plans/{planId}` | Get a DisbursementPlan | `SchoolAdmin`, `DeptOfficer`, `FinanceOfficer` |
| POST | `/scholarships/{scholarshipId}/disbursement-plans/{planId}/approve` | Multi-level approval (DRAFT→DEPT_APPROVED→FINANCE_APPROVED) | `DeptOfficer`, `FinanceOfficer` |
| POST | `/scholarships/{scholarshipId}/disbursement-plans/{planId}/revert` | Revert a DEPT_APPROVED plan back to DRAFT (only by dept_approver_id) | `DeptOfficer` |
| POST | `/scholarships/{scholarshipId}/disbursement-plans/{planId}/execute` | Execute plan (FINANCE_APPROVED→EXECUTED) | `FinanceOfficer` |
| GET | `/scholarships/{scholarshipId}/disbursement-plans/{planId}/records` | List DisbursementRecords for a plan | `SchoolAdmin`, `FinanceOfficer` |
| GET | `/audit-events` | List AuditEvents (filterable by `event_type`, `target_entity`, `target_id`) | `SchoolAdmin` |
| GET | `/external-sync-events` | List ExternalSyncEvents emitted (filterable by `kind`, `application_id`, `scholarship_id`) | `SchoolAdmin` |
| POST | `/_clock/advance` | Advance the system clock for time-gated transitions (test-only) | `SchoolAdmin` |
| POST | `/_sweep/run` | Run periodic sweep (auto-transitions for any Scholarship whose window has elapsed) | `SchoolAdmin` |

## 5. Error Code Catalogue

The conditions under which each error is returned are described in §2 and §3 narratives, in the workflow that the error guards.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_WINDOW_CLOSED` | 409 |
| `ERR_WINDOW_NOT_CLOSED` | 409 |
| `ERR_RUBRIC_WEIGHT_INVALID` | 422 |
| `ERR_QUOTA_MISMATCH` | 422 |
| `ERR_ELIGIBILITY_FAIL` | 422 |
| `ERR_MATERIAL_MISSING` | 422 |
| `ERR_MATERIAL_INCOMPLETE` | 422 |
| `ERR_ADVISOR_REC_MISSING` | 422 |
| `ERR_DUPLICATE_APPLICATION_SAME` | 409 |
| `ERR_DUPLICATE_APPLICATION_CROSS` | 409 |
| `ERR_COMMENT_REQUIRED` | 422 |
| `ERR_DEPT_SCOPE_MISMATCH` | 403 |
| `ERR_COI_VIOLATION` | 409 |
| `ERR_REVIEWER_COUNT_INVALID` | 422 |
| `ERR_REVIEWER_DUPLICATE` | 422 |
| `ERR_REVIEWER_NOT_ACTIVE` | 409 |
| `ERR_REVIEWERS_ALREADY_ASSIGNED` | 409 |
| `ERR_SCORE_RUBRIC_MISMATCH` | 422 |
| `ERR_SCORE_OVER_QUOTA` | 409 |
| `ERR_REVIEW_NOT_COMPLETE` | 409 |
| `ERR_OBJECTION_PENDING` | 409 |
| `ERR_DISBURSEMENT_NOT_EXECUTED` | 409 |
| `ERR_PLAN_EMPTY` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_EXECUTOR_MISMATCH` | 403 |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_SCHOLARSHIP_WINDOW_OVERLAP` | 409 |
