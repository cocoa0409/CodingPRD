# College Admissions Consulting API — Product Requirements Document

## 1. Introduction

Independent college admissions counselors run a high-touch practice: each counselor shepherds a roster of students from first intake through application, essay coaching, financial-aid guidance, and final admission decisions. This API is the system of record for that practice. It captures the full student journey — intake and profile-building, school-list strategy that balances reach and safety schools, an essay-coaching loop with versioned drafts, an application-task tracker keyed to early-decision and regular-decision deadlines, recommendation and activity-résumé management, scholarship coordination, and the decision-and-appeal endgame.

Two billing models sit underneath everything. A counselor may engage a student on a flat **PACKAGE** fee amortized across milestones, or on an **HOURLY** time-and-materials basis billed from completed appointments and tasks. The system maintains a per-contract retainer ledger in real time, distinguishes money already spent from money projected to be spent on still-pending work, and refuses to close an engagement while a student owes a balance. Because several actors (a counselor and a student) collaborate on the same records, and because admissions work is governed by hard external deadlines, the platform leans heavily on a server-controlled logical clock, optimistic concurrency on the shared student record, and a strict ordering of validation checks so that the most important objection always surfaces first.

The remainder of this document specifies the global contract that every endpoint honors (Section 2), the business workflows and their interlocking rules (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. The system recognizes exactly three roles: `Counselor`, `Student`, and `PlatformAdmin`. If either header is missing, or if `X-User-Role` is not one of these three values, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation — or is permitted in general but is acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

Ownership is rooted in the identity each role carries. When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting `Counselor`; ownership checks on any resource that references a counselor compare the resource's owning counselor to `X-User-ID`. A counselor may act only on students they own — that is, students whose `counselor_id` equals the caller's `X-User-ID` — and, transitively, only on the contracts, school-list items, applications, tasks, essays, essay versions, recommendations, activities, scholarships, billing entries, and appointments belonging to those students. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; a student may act only on resources where the owning student's `id` equals `X-User-ID`, including their own intake profile, activity résumé, essays and essay-version submissions, and recommendation requests. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`, and a `PlatformAdmin` never asserts ownership over a student. The `PlatformAdmin` role exists to administer the counselor registry and to drive the logical clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response returns; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp (`created_at`) in ascending order.

List responses report pagination state through four fields in the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was first created, and `updated_at` is the ISO 8601 UTC timestamp at which it was last modified. The `version` is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for the optimistic concurrency control described in Section 2.7.

Two entities are immutable append-only records and therefore carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field. The first is `BillingEntry`, each row of which is a permanent ledger posting. The second is `EssayVersion`, each row of which is a permanent snapshot of a submitted draft. Every other entity in the system — counselors, students, contracts, school-list items, applications, tasks, essays, recommendation requests, activity entries, scholarship awards, and appointments — carries the full `created_at`, `updated_at`, and `version` set.

All time-sensitive checks in this system — application deadlines, the appeal window, and whether an appointment has started — are evaluated against a **server logical clock**, never against wall-clock time. At server startup the logical clock reads exactly `2026-04-01T00:00:00Z`, and it holds that value until a `PlatformAdmin` advances it; before any clock-setting call the clock never falls back to real time. A `PlatformAdmin` may move the clock to any supplied instant via the `to_iso8601` field of the clock-setting capability described in Section 3.9.

### 2.5. State Transitions, Cascades, and Derived-Field Reconciliation

Most write operations are state-machine transitions. A transition is permitted only when the target resource is in a state from which that transition is defined; an attempt to transition from any other state is rejected with `ERR_INVALID_STATE`. Several computed fields are reconciled automatically whenever an event affects their inputs, and these reconciliations are themselves mutations: each one refreshes the affected resource's `updated_at` and increments its `version`.

Reconciliation frequently crosses entity boundaries. Completing an application task may post a billing charge to a contract; approving an essay may close out a task on a different entity; requesting an essay revision may demote an application that was already marked ready; submitting a recommendation may close tasks across several applications. Each of these cross-entity effects is spelled out in the workflow narratives of Section 3, and every entity touched by such a cascade has its own `version` incremented and `updated_at` refreshed. Three derived fields are particularly load-bearing and are described in full in Section 3: a student's `profile_strength`, a school's `admit_probability` and resulting `classification`, and a contract's pair of ledger balances `retainer_balance_cents` and `projected_balance_cents`.

### 2.6. Reference Integrity and Cross-Student Isolation

Resources are flat top-level collections linked by foreign keys rather than nested under one another in the URL. Because of this, child resources are discovered through filtered list reads rather than nested paths; several list endpoints additionally accept a `status` filter that narrows results to rows in the requested `status`, alongside foreign-key filters and a `category` or `round` filter where the resource defines one. When a path names a resource by its identifier and no such resource exists, the request is rejected with `ERR_NOT_FOUND`; when a path carries more than one identifier the system validates them left to right and reports the first missing one.

Before any reference check, the request body itself must be well-formed: all required fields present, every enum carrying one of its permitted values, and every numeric field within its allowed range. A malformed body — a missing required field, an unrecognized enum value, or an out-of-range number — is rejected with `ERR_INVALID_REQUEST`.

Creation and reference endpoints accept foreign-key fields in their bodies — for example `counselor_id`, `student_id`, `contract_id`, `school_list_item_id`, `application_id`, `essay_id`, and `source_id`. Each such field must reference a row that actually exists; if it does not, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. The same error is returned when a referenced row exists but belongs to a different student than the one in scope: the system never permits one student's records to point at another student's, so cross-student references are rejected.

### 2.7. Optimistic Concurrency Control on the Student Record

Two operations mutate a student's record as a side effect and are therefore guarded by optimistic concurrency control against that student's `version`. The first is contract activation; the second is selecting a school-list item into the locked list. Each of these write operations requires the request body to carry `expected_student_version`, holding the `version` of the `Student` the client last observed. The server compares `expected_student_version` to the student's current `version`. If they differ — meaning another writer advanced the student's `version` after the client last read it — the write is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412), so the operation never recomputes the student against a snapshot it has not seen.

Contract activation is guarded because it legitimately supersedes the student's onboarding view: it bubbles the student's intake status forward and posts a retainer credit, so it must run against an up-to-date student. School selection is guarded because it recomputes the student's `list_locked` flag; if two selections each computed `list_locked` against an out-of-date list snapshot the result would be wrong, so the second one is rejected as stale. No other endpoint takes a version field; operations outside these two do not require `expected_student_version`.

### 2.8. Money, Counts, and Rounding

Monetary amounts are integer cents throughout. Ledger sums — a contract's `charged_cents`, `credited_cents`, and the derived `retainer_balance_cents` and `projected_balance_cents` — are exact integer arithmetic with no rounding. Where a calculation produces a fractional cent before storage, such as an hourly appointment charge, the result is rounded half up to a whole number of cents in a single rounding step at the end of the calculation, never by rounding intermediate factors first.

Two scoring calculations round to a fixed number of decimal places, both using round-half-up. A student's `profile_strength` is computed to two decimal places with a pinned rounding order described in Section 3.1. A school's `admit_probability` is computed to four decimal places and clamped into the closed range from 0.0 to 1.0, as described in Section 3.4. School `classification` counts and the list-balance booleans are exact integer and boolean results with no rounding.

### 2.9. The Retainer Ledger Principle

Every `EngagementContract` owns an append-only retainer ledger composed of `BillingEntry` rows. A `BillingEntry` is either a `CHARGE` (a debit against the student) or a `CREDIT` (a deposit or refund in the student's favor), and it records what produced it through `source_kind`, which is one of `TASK`, `APPOINTMENT`, `ESSAY`, or `MANUAL`. The ledger is the single source of truth for what a student has been charged and credited; the contract's balance fields are always recomputed from it rather than mutated directly. Because the ledger is append-only and its balances are pure sums, recomputation is order-independent. The distinction between what has actually been posted and what is merely projected — the heart of this system's fiscal discipline — is developed in Section 3.7.

### 2.10. Order of Validation

When more than one objection could apply to a single request, the system evaluates them in a fixed precedence so that the most fundamental failure always surfaces first, regardless of the order in which the conditions appear in this document. The precedence is: first, authentication — missing or unknown headers yield `ERR_UNAUTHENTICATED`; then authorization, including ownership — a role acting where it may not, or on a resource it does not own, yields `ERR_FORBIDDEN`; then the existence of every path-referenced resource, yielding `ERR_NOT_FOUND`; then the existence and same-student scope of body foreign keys, yielding `ERR_REFERENCE_NOT_FOUND`; then general body well-formedness, yielding `ERR_INVALID_REQUEST`; then, where applicable, the contract billing-model coherence check yielding `ERR_BILLING_MODEL_INCOHERENT`; then, on the two optimistic-concurrency writes, the stale-version check yielding `ERR_STALE_STUDENT_VERSION`; then whether the requested state transition is defined from the resource's current state, yielding `ERR_INVALID_STATE`. Only after all of these pass does the system evaluate the operation-specific business rules (temporal windows, capacity, referential gates, and fiscal balance) described in the workflow sections below. Thus, for example, an unauthenticated caller targeting a non-existent resource is told it is unauthenticated, and a transition requested on a resource in the wrong state is rejected for the wrong state before any deeper business rule is consulted.

## 3. Business Logic & Workflows

### 3.1. Student Intake, the Activity Résumé, and Profile Strength

A `Counselor` brings a student into the practice by creating a `Student` record, supplying the `counselor_id` of the owning counselor, the student's `full_name` and `email`, an expected `grad_year` that must be 2026 or later, and an unweighted `gpa` on a scale where the value must be at least 0.0 and at most 4.0. The counselor may also supply `sat_total`; this is either 0, meaning no score has been submitted yet, or a value from 400 through 1600 inclusive, and it defaults to 0. A new student begins life with `intake_status` of `PROSPECT`, a `profile_strength` of 0, and `list_locked` set to false.

The activity résumé feeds the student's profile score. Anyone owning the student — the `Counselor` or the `Student` themselves — may add an `ActivityEntry`, supplying its `title`, a `category` that is one of `ACADEMIC`, `ATHLETIC`, `ARTS`, `SERVICE`, `WORK`, or `LEADERSHIP`, the `hours_per_week` committed (zero or more), the `weeks_per_year` (at least 0 and no more than 52), and a selectivity `tier` from 1 (national) to 4 (local). Adding an activity recomputes the student's `profile_strength`.

**Profile strength** is a 0-to-100 weighted score combining academics and the résumé, and its evaluation order is fixed. The academic portion ranges from 0 to 70 and has two parts. The GPA component is the student's `gpa` divided by 4.0 and then multiplied by 40, yielding 0 to 40. The SAT component is 0 when `sat_total` is 0; otherwise it is the quantity `sat_total` minus 400, divided by 1200, then multiplied by 30, yielding 0 to 30. The academic subtotal is the GPA component plus the SAT component. The résumé portion ranges from 0 to 30. Each activity contributes its `hours_per_week` multiplied by its `weeks_per_year`, divided by 100, then multiplied by a tier weight — 1.0 for tier 1, 0.7 for tier 2, 0.4 for tier 3, and 0.2 for tier 4. These per-activity contributions are summed across every `ActivityEntry` for the student (the résumé has no status filter, so all entries count), and the résumé subtotal is the lesser of that sum and 30. Rounding order is pinned: the academic subtotal is rounded half up to two decimal places, the résumé subtotal is rounded half up to two decimal places, the two rounded subtotals are added, and that sum is rounded half up to two decimal places to produce `profile_strength`.

The intake lifecycle advances through the student transition capability, which accepts a target status in its `to_status` field. The recommendation and scholarship lifecycles described in Section 3.6 likewise take the requested target through `to_status`. Moving a `PROSPECT` student to `ONBOARDED` requires that the student has at least one `ActivityEntry` and that `sat_total` is not 0; if either condition fails the transition is rejected with `ERR_INTAKE_INCOMPLETE`. Onboarding recomputes `profile_strength`. A student reaches `ACTIVE` only through contract activation, as described in Section 3.3 — there is no direct transition into `ACTIVE`. From `ACTIVE` a student may be moved to `GRADUATED`: this requires that every `Application` for the student has a `decision_status` other than `PENDING` or has a `prep_status` of `SUBMITTED`, failing which the transition is rejected with `ERR_APPLICATIONS_IN_FLIGHT`, and it further requires that no `EngagementContract` for the student is currently `ACTIVE`, failing which it is rejected with `ERR_CONTRACT_ALREADY_ACTIVE`. A student may also be moved to `WITHDRAWN` from `PROSPECT` or `ONBOARDED` with no preconditions, or from `ACTIVE` provided no `EngagementContract` for the student is currently `ACTIVE` (otherwise `ERR_CONTRACT_ALREADY_ACTIVE`). `GRADUATED` and `WITHDRAWN` are terminal.

### 3.2. School-List Strategy: Probability, Classification, and the Balance Lock

A `Counselor` builds a student's target list by adding a `SchoolListItem`, supplying the `student_id`, the `school_name`, the published overall `admit_rate` as a fraction greater than 0.0 and at most 1.0, the `median_sat` of admitted students (400 through 1600), and optionally the intended `round`, which is `ED`, `EA`, `RD`, or `NONE` (the default, meaning not yet decided). A new item enters as a `CANDIDATE`, and the system immediately computes its `admit_probability` and `classification`.

**Admit probability** is a per-school estimate in the closed range 0.0 to 1.0. It starts from the school's `admit_rate`. The system computes the SAT gap as the student's `sat_total` minus the school's `median_sat`; if the student's `sat_total` is 0 the gap is treated as 0, contributing no signal. A multiplier is then chosen from the gap: when the gap is 100 or more the multiplier is 1.6; when the gap is at least 0 but less than 100 the multiplier is 1.0 plus the gap divided by 100 then multiplied by 0.6 (interpolating from 1.0 up to 1.6 across a gap of 0 to 100); when the gap is below 0 but strictly greater than −100 the multiplier is 1.0 plus the gap divided by 100 then multiplied by 0.5 (interpolating from 0.5 up to 1.0 across a gap of −100 to 0); and when the gap is −100 or less the multiplier is 0.5. A strength bonus is the student's `profile_strength` minus 50, divided by 100, then multiplied by 0.3, which ranges from −0.15 to +0.15 around a profile strength of 50. The raw probability is the `admit_rate` multiplied by the multiplier, plus the strength bonus. The stored `admit_probability` is that raw value clamped to be no less than 0.0 and no more than 1.0, then rounded half up to four decimal places.

**Classification** is derived from the four-decimal `admit_probability`: if it is 0.60 or greater the item is a `SAFETY`; if it is strictly below 0.20 it is a `REACH`; otherwise — that is, from 0.20 up to but not including 0.60 — it is a `TARGET`. Because `admit_probability` depends on `profile_strength`, the probability and classification of a student's school items are recomputed whenever that student's `profile_strength` changes.

School items move through a small lifecycle. A `CANDIDATE` may be selected into the working list, transitioning it to `SELECTED` (the list-membership state), or a `CANDIDATE` or `SELECTED` item may be dropped, transitioning it to `DROPPED`. Selecting an item recomputes the student's `list_locked` flag and is guarded by optimistic concurrency on the student as described in Section 2.7, requiring `expected_student_version` and rejecting a stale value with `ERR_STALE_STUDENT_VERSION`; selection also increments the student's `version`. Dropping an item likewise recomputes `list_locked`.

The **balance lock** governs `list_locked`. Considering only the items in `SELECTED` status, the system counts how many are classified `SAFETY`, the total number selected, and how many carry a `round` of `ED`. The list is locked — `list_locked` becomes true — exactly when there is at least one `SAFETY`, the total selected count is at least 3, and the number of `ED` selections is at most 1; otherwise `list_locked` is false.

### 3.3. Engagement Contracts and Activation

A `Counselor` formalizes the relationship with an `EngagementContract`. Creating one requires the `student_id`, the `billing_model` (`PACKAGE` or `HOURLY`), and a coverage window given by `coverage_start_utc` and `coverage_end_utc`, where the end must be strictly after the start (both treated as closed boundaries of the window). The contract's `counselor_id` is copied from the student rather than supplied. A new contract begins in `DRAFT` with all computed balances at 0.

Billing-model coherence is checked at creation. A `PACKAGE` contract requires `package_fee_cents` greater than 0 and `package_milestones` greater than 0 (the milestone count over which the flat fee amortizes) and requires `hourly_rate_cents` to be 0. An `HOURLY` contract requires `hourly_rate_cents` greater than 0 and requires both `package_fee_cents` and `package_milestones` to be 0. Each of these four amounts defaults to 0 when omitted. A body that violates the coherence rule for its declared model is rejected with `ERR_BILLING_MODEL_INCOHERENT`. The contract may also carry a `retainer_deposit_cents` paid up front, defaulting to 0.

Contract creation also enforces coverage-window exclusivity per student. Considering every non-`VOID` `EngagementContract` for the same student, each window is a closed interval from its `coverage_start_utc` to its `coverage_end_utc`. The new window conflicts when the new start is strictly before an existing window's end and that existing window's start is strictly before the new end. Windows that merely share a single endpoint instant are adjacent and permitted; only a strict interior overlap is rejected, with `ERR_CONTRACT_COVERAGE_OVERLAP`. There is no buffer on this check.

**Activation** moves a contract from `DRAFT` to `ACTIVE`. It is permitted only when the student's `intake_status` is `ONBOARDED` or `ACTIVE`, failing which it is rejected with `ERR_STUDENT_NOT_ONBOARDED`, and only when no other `EngagementContract` for the student is already `ACTIVE`, failing which it is rejected with `ERR_CONTRACT_ALREADY_ACTIVE`. Activation is guarded by optimistic concurrency on the student: the request must carry `expected_student_version` matching the student's current `version`, or it is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412). On success, if `retainer_deposit_cents` is greater than 0 the system appends a `BillingEntry` that is a `CREDIT` with `source_kind` of `MANUAL` and `amount_cents` equal to the deposit, then recomputes the contract's `credited_cents`, `charged_cents`, `retainer_balance_cents`, and `projected_balance_cents`. If the student's `intake_status` was `ONBOARDED`, activation bubbles it up to `ACTIVE` and increments the student's `version`. Activation increments the contract's `version`.

An `ACTIVE` contract may be **closed**, moving it to `CLOSED`. Closing requires that no `Application` for the student has a `prep_status` of `NOT_STARTED`, `IN_PROGRESS`, or `READY` — every application must be either `SUBMITTED` or have no open prep — failing which it is rejected with `ERR_OPEN_APPLICATIONS`; and it requires that `retainer_balance_cents` is at least 0, so that no money is owed, failing which it is rejected with `ERR_OUTSTANDING_BALANCE`. Closing recomputes the ledger and projected balance one final time and increments the contract's `version`. Separately, a `DRAFT` contract that has accumulated zero `BillingEntry` rows may be **voided** to `VOID`; if it has any billing entries the void is rejected with `ERR_CONTRACT_HAS_ENTRIES`. Voiding increments the contract's `version`. `CLOSED` and `VOID` are terminal.

### 3.4. Building Applications and the Task Tracker

With at least one school selected, a `Counselor` opens an `Application` against it, supplying the `student_id`, the `school_list_item_id` of the targeted school, the `round` (`ED`, `EA`, or `RD`), and the hard `deadline_utc` for that round. An application carries two independent dimensions: a preparation dimension `prep_status` that starts at `NOT_STARTED`, and an outcome dimension `decision_status` that starts at `PENDING`. Its `open_task_count` — the number of this application's tasks in `OPEN` or `BLOCKED` — starts at 0.

A single binding early-decision rule is enforced at application creation. An `ED` application may be created only if the student has no other `Application` with `round` of `ED` whose `prep_status` is `NOT_STARTED`, `IN_PROGRESS`, `READY`, or `SUBMITTED`; a second such binding ED application is rejected with `ERR_ED_CONFLICT`.

The counselor populates the application with `ApplicationTask` rows, each carrying an `application_id`, a `title`, a `task_type` of `ESSAY`, `RECOMMENDATION`, `FORM`, `FEE`, or `TRANSCRIPT`, and a `due_utc`. A task's `due_utc` must be on or before the parent application's `deadline_utc` (equal is allowed); a later due date is rejected with `ERR_TASK_DUE_AFTER_DEADLINE`. Each task may declare an `estimated_cost_cents` (the billable cost if the counselor completes it, defaulting to 0) and a `blocks_submission` flag (defaulting to true) indicating whether it must be resolved before the application can be marked ready. A new task starts in `OPEN`, and creating it recomputes the parent application's `open_task_count`.

Tasks move through their own lifecycle, all driven by the counselor through the task transition capability with the requested target supplied in `to_status`. From `OPEN` a task may go to `IN_PROGRESS`; from `IN_PROGRESS` it may go to `DONE`; from either `OPEN` or `IN_PROGRESS` it may go to `BLOCKED`, and a `BLOCKED` task may return to `OPEN`; and from any non-done state — `OPEN`, `IN_PROGRESS`, or `BLOCKED` — it may be waived to `WAIVED`. `DONE` and `WAIVED` are terminal. Every one of these transitions recomputes the parent application's `open_task_count`. Completing a task to `DONE` additionally has a billing consequence developed in Section 3.7. Marking a task `DONE` also recomputes `open_task_count` as a bubble-up to the parent application.

The preparation dimension advances under the counselor's control. Starting prep moves `prep_status` from `NOT_STARTED` to `IN_PROGRESS`, but only if the `SchoolListItem` referenced by the application's `school_list_item_id` is in `SELECTED` status, otherwise it is rejected with `ERR_SCHOOL_NOT_SELECTED`; starting prep recomputes `open_task_count`. Marking ready moves `prep_status` from `IN_PROGRESS` to `READY`, permitted only when `open_task_count` is 0 — every blocking task `DONE` or `WAIVED` — otherwise rejected with `ERR_OPEN_TASKS_REMAIN`; it recomputes `open_task_count`. Submitting moves `prep_status` from `READY` to `SUBMITTED`, and is permitted only when the logical clock now is strictly before the application's `deadline_utc` (otherwise `ERR_DEADLINE_PASSED`) and only when `open_task_count` is 0 (otherwise `ERR_OPEN_TASKS_REMAIN`). A `READY` application can also be demoted back to `IN_PROGRESS` by the system as a cascade from essay revision, described in Section 3.5; that demotion recomputes `open_task_count`.

### 3.5. Essay Coaching: the Versioned Revision Loop

The essay-coaching workflow is a cyclic revision loop shared between student and counselor. Either a `Counselor` or the `Student` may create an `Essay`, supplying the `student_id`, the essay `prompt`, the `word_limit` (which must be greater than 0), and optionally the `application_id` the essay supports (defaulting to none). A new essay starts in `DRAFTING` with `revision_round` at 0 and `latest_version_no` at 0.

A draft is offered up for review by submitting a version, which moves the essay from `DRAFTING` to `IN_REVIEW`. Either the `Student` or the `Counselor` may submit, providing the `word_count` and the `body` of the draft. The submitted `word_count` must not exceed the essay's `word_limit`, or the submission is rejected with `ERR_WORD_LIMIT_EXCEEDED`. The submission is also gated by the counselor's weekly review capacity: it is blocked when the number of reviews the counselor has already taken on in the current ISO week is at or above the counselor's `weekly_review_capacity`, in which case it is rejected with `ERR_REVIEW_CAPACITY_EXCEEDED`. On success the system appends an `EssayVersion` whose `version_no` is the essay's current `latest_version_no` plus one and whose `submitted_by_role` records whether a `Student` or a `Counselor` submitted it, sets the essay's `latest_version_no` to that new number, and increments the essay's `version`. An `EssayVersion` is an append-only snapshot carrying the `essay_id`, the monotonic per-essay `version_no` (starting at 1), the `word_count`, the full `body`, and the `submitted_by_role`.

A `Counselor` reviews a submitted draft by requesting a revision, moving the essay from `IN_REVIEW` to `REVISION_REQUESTED`; this requires the essay to have at least one `EssayVersion`, otherwise it is rejected with `ERR_NO_VERSION_TO_REVIEW`. Requesting a revision increments the essay's `revision_round`. It also cascades: if the essay has an `application_id` and that application's `prep_status` is `READY`, the application is demoted from `READY` to `IN_PROGRESS` and its `open_task_count` is recomputed. The revision then increments the essay's `version`. From `REVISION_REQUESTED` the `Student` resumes drafting, returning the essay to `DRAFTING` with no preconditions and incrementing the essay's `version` — closing the cycle so the loop may repeat.

A `Counselor` approves an essay from either `DRAFTING` or `IN_REVIEW`, moving it to `APPROVED`. Both approval transitions carry the same two preconditions: the essay's `latest_version_no` must be at least 1 (otherwise `ERR_NO_VERSION_TO_REVIEW`), and the essay's `revision_round` must be at least 1, meaning at least one review cycle has completed (otherwise `ERR_REVISION_REQUIRED`). On approval, if the essay has an `application_id`, the system marks any `ApplicationTask` on that application whose `task_type` is `ESSAY` and whose status is `OPEN`, `IN_PROGRESS`, or `BLOCKED` as `DONE`, and recomputes that application's `open_task_count`. Approval increments the essay's `version`. Separately, an essay may be abandoned to `ABANDONED` from any non-approved state — `DRAFTING`, `IN_REVIEW`, or `REVISION_REQUESTED` — by a `Counselor`, with no preconditions, incrementing the essay's `version`. `APPROVED` and `ABANDONED` are terminal.

### 3.6. Recommendations, Activities Revisited, and Scholarship Coordination

A recommendation is requested by either a `Counselor` or the `Student`, creating a `RecommendationRequest` with the `student_id`, the `recommender_name`, the `recommender_email`, and a `rec_type` of `TEACHER`, `COUNSELOR`, or `OTHER`. It begins in `REQUESTED`. The counselor drives its lifecycle: from `REQUESTED` it may move to `ACCEPTED`, and from `ACCEPTED` it may move to `SUBMITTED`; from either `REQUESTED` or `ACCEPTED` it may move to `DECLINED`. When a recommendation reaches `SUBMITTED`, the system marks any `ApplicationTask` whose `task_type` is `RECOMMENDATION` and whose status is `OPEN`, `IN_PROGRESS`, or `BLOCKED` across all of the student's applications as `DONE`, and recomputes the `open_task_count` of each affected application. `SUBMITTED` and `DECLINED` are terminal.

Scholarship and financial-aid guidance is captured as `ScholarshipAward` records. A `Counselor` records an award with the `student_id`, the `award_name`, an `award_type` of `MERIT`, `NEED`, or `EXTERNAL`, the sticker `gross_amount_cents` (which must be greater than 0), and optionally the `application_id` the award is tied to (defaulting to none for external scholarships). An award begins in `OFFERED`, and recording it recomputes the net amounts for the student's awards. The counselor may move an award from `OFFERED` to `ACCEPTED` or from `OFFERED` to `DECLINED`. Accepting a `MERIT` or `NEED` award requires that the tied application's `decision_status` is `ADMITTED`, otherwise the acceptance is rejected with `ERR_AWARD_NOT_ADMITTED`; an `EXTERNAL` award carries no such precondition. Both accepting and declining recompute the net amounts across all of the student's awards.

**Net aid** is a coordination/stacking waterfall over a fixed family coordination cap of 4,000,000 cents. The student's awards are processed in a pinned order: first by award-type rank, where `MERIT` ranks 0, `EXTERNAL` ranks 1, and `NEED` ranks 2, and within the same rank by `created_at` ascending. Only awards in `ACCEPTED` status consume the cap. Running through the accepted awards in that order with a running total starting at 0, each award's `net_amount_cents` is the lesser of its own `gross_amount_cents` and the cap minus the running total so far; if that quantity would be negative it is taken as 0; the running total then increases by the amount just allocated. An award still in `OFFERED` is informational and its `net_amount_cents` equals its `gross_amount_cents`; a `DECLINED` award has a `net_amount_cents` of 0. `ACCEPTED` and `DECLINED` are terminal.

### 3.7. The Retainer Ledger: Actual Versus Projected Balances

Every contract maintains two balances that diverge by design. The **actual** balance reflects only money already posted: `charged_cents` is the sum of `amount_cents` over all `BillingEntry` rows of type `CHARGE` on the contract, `credited_cents` is the sum of `amount_cents` over all rows of type `CREDIT`, and `retainer_balance_cents` is `credited_cents` minus `charged_cents` — a negative value means the student owes money. These sums are taken over every entry on the contract with none excluded, and because they are pure sums the result does not depend on the order in which entries were posted.

The **projected** balance looks forward by assuming every still-billable pending task will eventually bill. The pending-task cost is the sum of `estimated_cost_cents` over every `ApplicationTask`, across all of the contract's student's applications, that is simultaneously in `OPEN`, `IN_PROGRESS`, or `BLOCKED` status, has a `task_type` other than `ESSAY`, and has an `estimated_cost_cents` greater than 0. The `projected_balance_cents` is `retainer_balance_cents` minus that pending-task cost. The crucial subtlety is that this very set of pending tasks is *included* in the projected balance but *excluded* from the actual ledger — essay tasks never bill in either — so the two balances legitimately differ for identical data. Both balances are recomputed together on every ledger-affecting event: any billing-entry append, contract activation or close, appointment completion, and task completion.

A `Counselor` may post a manual `BillingEntry` to an `ACTIVE` contract directly, supplying the `contract_id`, the `entry_type`, the `source_kind`, the positive `amount_cents`, and optionally a `source_id` (the id of an originating task or appointment, null for manual entries), `minutes` (billable minutes, used when `source_kind` is `APPOINTMENT` under an `HOURLY` contract, otherwise 0), and a free-text `memo` (defaulting to empty). Posting recomputes the contract's actual and projected balances.

Two automatic charges feed the ledger. When a task transitions to `DONE`, then provided its `task_type` is not `ESSAY`, its `estimated_cost_cents` is greater than 0, and the student has an `ACTIVE` contract, the system appends a `CHARGE` `BillingEntry` with `source_kind` of `TASK`, `source_id` set to the task, and `amount_cents` equal to the task's `estimated_cost_cents`, then recomputes the actual and projected balances on that contract. This is the point at which a task that had been inflating the projected shortfall converts into a real posted charge. The second automatic charge comes from appointments, in Section 3.8.

### 3.8. Appointments and Hourly Billing

A `Counselor` books an `Appointment` for a student, supplying the `student_id`, the `start_utc`, the `end_utc` (which must be strictly after the start; the appointment occupies the half-open interval running from the start inclusive to the end exclusive), and a `meeting_type` of `STRATEGY`, `ESSAY_REVIEW`, or `CHECK_IN`. The appointment's `counselor_id` is copied from the student. A new appointment is `BOOKED`, and its `billed_minutes` begins at 0.

Booking enforces a buffered overlap check on the counselor's calendar. The resource under contention is the counselor identified by the appointment's `counselor_id`, and the candidate set is every other appointment for that same counselor whose status is `BOOKED` or `COMPLETED`. A 15-minute buffer is applied symmetrically: the new appointment's effective window runs from 15 minutes before its `start_utc` to 15 minutes after its `end_utc`. The new booking conflicts when that buffered low end is strictly before an existing appointment's `end_utc` and that existing appointment's `start_utc` is strictly before the buffered high end; touching exactly at the buffered boundary does not conflict, but anything closer does. A conflict is rejected with `ERR_APPOINTMENT_OVERLAP`.

A `BOOKED` appointment may be cancelled to `CANCELLED` with no preconditions, incrementing the appointment's `version`. It may instead be completed to `COMPLETED`, but only when the logical clock now is at or after the appointment's `start_utc`, otherwise the completion is rejected with `ERR_APPOINTMENT_NOT_STARTED`. On completion the system sets `billed_minutes` to the whole number of minutes between `start_utc` and `end_utc` — that is, the total seconds of the interval divided by 60 and truncated down to a whole minute. Then, if the student has an `ACTIVE` `HOURLY` contract, the system appends a `CHARGE` `BillingEntry` with `source_kind` of `APPOINTMENT`, `source_id` set to the appointment, `minutes` equal to `billed_minutes`, and `amount_cents` equal to `billed_minutes` divided by 60 and multiplied by the contract's `hourly_rate_cents`, rounded half up to a whole number of cents in a single final rounding step (never per-minute). It then recomputes the contract's actual and projected balances. Completion increments the appointment's `version`. `COMPLETED` and `CANCELLED` are terminal. The counselor's own default `hourly_rate_cents` (positive) and `weekly_review_capacity` (the maximum essay reviews per ISO week across all students, at least 0, defaulting to 10) are set when the counselor is created with their `full_name`, `email`, `hourly_rate_cents`, and `weekly_review_capacity`.

### 3.9. Decisions, Appeals, and Administrative Capabilities

The outcome dimension of an application is advanced by a `Counselor` through the record-decision capability, which carries a `decision`. A `PENDING` application may be recorded as `ADMITTED`, `DENIED`, `WAITLISTED`, or `DEFERRED`, but only once its `prep_status` is `SUBMITTED`; a decision attempted earlier is rejected with `ERR_NOT_SUBMITTED`. Recording a `DEFERRED` outcome is additionally restricted to applications whose `round` is `ED` or `EA` — a regular-decision round cannot be deferred — otherwise it is rejected with `ERR_DEFER_NOT_ALLOWED`.

A `DENIED` application may be appealed by a `Counselor`, moving its `decision_status` to `APPEALING`. The appeal is allowed only while the logical clock now is strictly before the application's `deadline_utc` plus a 30-day appeal window; once that window has closed the appeal is rejected with `ERR_APPEAL_WINDOW_CLOSED`. Appealing appends a system `ApplicationTask` of `task_type` `FORM` titled "Appeal letter" with `blocks_submission` false and status `OPEN`, then recomputes the application's `open_task_count`. From `APPEALING` the counselor records the appeal outcome through the same record-decision capability, moving it to `ADMITTED` or `DENIED` with no further preconditions.

Administrative capabilities round out the system. A `Counselor` registers themselves, and a `PlatformAdmin` may register counselors as well, through counselor creation. A `PlatformAdmin` may read any counselor and list students across counselors. Finally, an admin-only test-driving capability advances the server logical clock to a supplied `to_iso8601` instant; this is the only way the clock moves, and every deadline, appeal-window, and appointment-start check in the system reads from it.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the clock-setting capability — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/counselors` | Create a counselor (operator self-registration) | PlatformAdmin, Counselor |
| GET | `/counselors/{counselorId}` | Get a counselor | PlatformAdmin, Counselor |
| POST | `/students` | Create (intake) a student assigned to a counselor | Counselor |
| GET | `/students/{studentId}` | Get a student with computed profile_strength and list_locked | Counselor, Student |
| GET | `/students` | List students; filterable by counselor_id | Counselor, PlatformAdmin |
| POST | `/students/{studentId}/transition` | Transition the student intake lifecycle | Counselor |
| POST | `/contracts` | Create an EngagementContract in DRAFT | Counselor |
| GET | `/contracts/{contractId}` | Get a contract with computed ledger balances | Counselor, Student |
| GET | `/contracts` | List contracts; filterable by student_id and counselor_id | Counselor, Student |
| POST | `/contracts/{contractId}/activate` | Activate a DRAFT contract (OCC-guarded on student) | Counselor |
| POST | `/contracts/{contractId}/close` | Close an ACTIVE contract | Counselor |
| POST | `/contracts/{contractId}/void` | Void a DRAFT contract with no billing entries | Counselor |
| POST | `/billing-entries` | Append a manual BillingEntry to an ACTIVE contract | Counselor |
| GET | `/billing-entries/{entryId}` | Get a billing entry | Counselor, Student |
| GET | `/billing-entries` | List billing entries; filterable by contract_id | Counselor, Student |
| POST | `/school-list-items` | Add a candidate school | Counselor |
| GET | `/school-list-items/{itemId}` | Get a school-list item | Counselor, Student |
| GET | `/school-list-items` | List school-list items; filterable by student_id and status | Counselor, Student |
| POST | `/school-list-items/{itemId}/select` | Select a CANDIDATE into the list (OCC-guarded on student) | Counselor |
| POST | `/school-list-items/{itemId}/drop` | Drop a school-list item | Counselor |
| POST | `/applications` | Create an Application against a SELECTED school-list item | Counselor |
| GET | `/applications/{applicationId}` | Get an application with computed open_task_count | Counselor, Student |
| GET | `/applications` | List applications; filterable by student_id, school_list_item_id, round | Counselor, Student |
| POST | `/applications/{applicationId}/start-prep` | Begin preparation (NOT_STARTED -> IN_PROGRESS) | Counselor |
| POST | `/applications/{applicationId}/mark-ready` | Mark ready (IN_PROGRESS -> READY) | Counselor |
| POST | `/applications/{applicationId}/submit` | Submit (READY -> SUBMITTED) | Counselor |
| POST | `/applications/{applicationId}/record-decision` | Record/advance the decision dimension | Counselor |
| POST | `/applications/{applicationId}/appeal` | Appeal a denied application (DENIED -> APPEALING) | Counselor |
| POST | `/application-tasks` | Create a task under an application | Counselor |
| GET | `/application-tasks/{taskId}` | Get a task | Counselor, Student |
| GET | `/application-tasks` | List tasks; filterable by application_id and status | Counselor, Student |
| POST | `/application-tasks/{taskId}/transition` | Transition a task status | Counselor |
| POST | `/essays` | Create an essay in DRAFTING | Counselor, Student |
| GET | `/essays/{essayId}` | Get an essay with computed revision_round and latest_version_no | Counselor, Student |
| GET | `/essays` | List essays; filterable by student_id and application_id | Counselor, Student |
| POST | `/essays/{essayId}/submit-version` | Submit a new draft version (DRAFTING -> IN_REVIEW) | Student, Counselor |
| POST | `/essays/{essayId}/request-revision` | Send essay back (IN_REVIEW -> REVISION_REQUESTED) | Counselor |
| POST | `/essays/{essayId}/resume-drafting` | Resume editing (REVISION_REQUESTED -> DRAFTING) | Student, Counselor |
| POST | `/essays/{essayId}/approve` | Approve essay (-> APPROVED) | Counselor |
| POST | `/essays/{essayId}/abandon` | Abandon essay (-> ABANDONED) | Counselor |
| GET | `/essay-versions/{versionId}` | Get an essay version snapshot | Counselor, Student |
| GET | `/essay-versions` | List essay versions; filterable by essay_id | Counselor, Student |
| POST | `/recommendations` | Create a recommendation request | Counselor, Student |
| GET | `/recommendations/{recId}` | Get a recommendation request | Counselor, Student |
| GET | `/recommendations` | List recommendation requests; filterable by student_id and status | Counselor, Student |
| POST | `/recommendations/{recId}/transition` | Transition a recommendation status | Counselor |
| POST | `/activities` | Add an activity-résumé entry | Counselor, Student |
| GET | `/activities/{activityId}` | Get an activity entry | Counselor, Student |
| GET | `/activities` | List activity entries; filterable by student_id and category | Counselor, Student |
| POST | `/scholarships` | Record a scholarship/aid award (OFFERED) | Counselor |
| GET | `/scholarships/{awardId}` | Get a scholarship award | Counselor, Student |
| GET | `/scholarships` | List scholarship awards; filterable by student_id, application_id, status | Counselor, Student |
| POST | `/scholarships/{awardId}/transition` | Accept or decline a scholarship award | Counselor |
| POST | `/appointments` | Book a counselor appointment for a student | Counselor |
| GET | `/appointments/{appointmentId}` | Get an appointment | Counselor, Student |
| GET | `/appointments` | List appointments; filterable by student_id, counselor_id, status | Counselor, Student |
| POST | `/appointments/{appointmentId}/complete` | Complete an appointment; bills minutes on HOURLY contracts | Counselor |
| POST | `/appointments/{appointmentId}/cancel` | Cancel a BOOKED appointment | Counselor |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_BILLING_MODEL_INCOHERENT` | 422 Unprocessable Entity |
| `ERR_STALE_STUDENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STUDENT_NOT_ONBOARDED` | 409 Conflict |
| `ERR_CONTRACT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_HAS_ENTRIES` | 409 Conflict |
| `ERR_OUTSTANDING_BALANCE` | 409 Conflict |
| `ERR_OPEN_APPLICATIONS` | 409 Conflict |
| `ERR_INTAKE_INCOMPLETE` | 409 Conflict |
| `ERR_APPLICATIONS_IN_FLIGHT` | 409 Conflict |
| `ERR_SCHOOL_NOT_SELECTED` | 409 Conflict |
| `ERR_OPEN_TASKS_REMAIN` | 409 Conflict |
| `ERR_DEADLINE_PASSED` | 409 Conflict |
| `ERR_TASK_DUE_AFTER_DEADLINE` | 422 Unprocessable Entity |
| `ERR_ED_CONFLICT` | 409 Conflict |
| `ERR_DEFER_NOT_ALLOWED` | 409 Conflict |
| `ERR_NOT_SUBMITTED` | 409 Conflict |
| `ERR_WORD_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REVIEW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_REVISION_REQUIRED` | 409 Conflict |
| `ERR_NO_VERSION_TO_REVIEW` | 409 Conflict |
| `ERR_AWARD_NOT_ADMITTED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_STARTED` | 409 Conflict |
| `ERR_APPOINTMENT_OVERLAP` | 409 Conflict |
| `ERR_CONTRACT_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
