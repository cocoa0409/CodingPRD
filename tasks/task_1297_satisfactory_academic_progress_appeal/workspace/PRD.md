# SAP Appeals API — Product Requirements Document

## 1. Introduction

Every institution that disburses federal student aid must measure Satisfactory Academic Progress — a paired quantitative and qualitative standard — at the close of each term, and must act on the outcome: warn the student, suspend eligibility, hear an appeal grounded in mitigating circumstances, monitor an academic plan term by term, and reinstate aid when the student recovers. The SAP Appeals API implements this compliance workflow end to end. It gives the registrar's office control over programs, terms, and the grade ledger; it gives the financial aid office a deterministic evaluation engine that converts posted grades into official standings; it gives students a structured appeal channel with a committee decision at the end; and it gives federal reviewers a complete, append-only account of everything that happened.

Two design commitments shape every workflow in this document. First, all time-sensitive behavior — appeal windows, reminder scheduling, evaluation timestamps — reads from a single logical clock rather than the wall clock, so that compliance windows are reproducible and testable. Second, every mutation leaves a trace: standings, notifications, plan outcomes, and decisions are all recorded as audit events attributed to the operator whose call caused them, because the entire process exists to survive federal review.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but not permitted for the target endpoint, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles. `Student` is the aid recipient and may act only on their own records. `Registrar` owns reference data and the grade ledger: programs, terms, student registration, enrollment creation, grade posting, and amendment. `AidOfficer` runs term evaluations, screens and queries appeals, creates and revises academic plans, and dispatches communications. `CommitteeMember` is the final step of the approval chain and records appeal decisions. `Auditor` is a read-only federal reviewer with access to every resource including the audit trail. `AidAdministrator` shares that audit-trail read access and additionally controls the logical clock.

Role identity is bound to resources as follows. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a student compare the resource's `student_id` field to `X-User-ID`. A student may therefore read only their own student record, their own advising preview, and their own appeals, plans, checkpoints, evaluations, notifications, and enrollments; list endpoints force the caller's `student_id` as a filter when the caller's role is `Student`, and any single-row read, appeal submission, or resubmission that targets another student's row is rejected with `ERR_OWNERSHIP_VIOLATION`. When `X-User-Role` is `Registrar`, `AidOfficer`, `CommitteeMember`, `Auditor`, or `AidAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on audit rows as `actor_id` but never compares it to any entity's `id`.

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

### 2.3. Pagination and List Ordering

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items: when omitted it defaults to 10, and any supplied value must fall between 1 and 100 inclusive. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. How the Server Selects an Error: The Global Validation Order

A single request can fail several rules at once, so the server evaluates guards in a fixed global order and reports the first failure encountered. Text order in this document is not the contract; the following ladder is. From first to last:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the six declared roles, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the caller's role appears in the endpoint's authorized-role list, else `ERR_UNAUTHORIZED`.
3. **Existence** — every identifier referenced by the path or the body is resolved left to right, else `ERR_NOT_FOUND` for the first identifier that does not resolve (see §2.9).
4. **Ownership** — a `Student` caller may touch only rows whose `student_id` equals `X-User-ID`, else `ERR_OWNERSHIP_VIOLATION`.
5. **Stale-version guard** — where an endpoint declares an optimistic-concurrency field, the supplied version must match, else `ERR_STALE_VERSION` (see §2.8).
6. **From-state validity** — the target resource must be in a valid from-state for the requested transition, else `ERR_INVALID_STATE`.
7. **Evaluation readiness** — a term evaluation requires the term to be grading-closed, else `ERR_TERM_NOT_READY`.
8. **Grading completeness** — closing grading requires that no in-progress enrollments remain, else `ERR_ENROLLMENTS_PENDING`.
9. **Suspension precondition** — an appeal may be submitted only from `SUSPENSION`, else `ERR_STUDENT_NOT_SUSPENDED`.
10. **Review exclusivity** — a new appeal may not be created while one is already under committee review, else `ERR_APPEAL_UNDER_REVIEW`.
11. **Decision readiness** — a committee decision requires the appeal to be under review, else `ERR_DECISION_REQUIRES_REVIEW`.
12. **Plan admissibility** — a plan may be created only against an approved plan-resolution appeal while the student awaits that plan, else `ERR_PLAN_NOT_ALLOWED`.
13. **Appeal window** — the appeal deadline of the referenced evaluation must not have passed, else `ERR_APPEAL_WINDOW_CLOSED`.
14. **Documentation** — an appeal or resubmission must carry at least one document, else `ERR_APPEAL_DOCS_REQUIRED`.
15. **Term date exclusivity** — a new term's date range may not intersect an existing term's, else `ERR_TERM_DATE_OVERLAP`.
16. **Plan coverage exclusivity** — a new plan's term coverage may not intersect another plan's coverage for the same student, else `ERR_PLAN_TERM_OVERLAP`.
17. **Plan credit balance** — checkpoint credit floors must sum to the plan's declared total, else `ERR_PLAN_CREDIT_MISMATCH`.
18. **Checkpoint term validity** — checkpoint terms must be contiguous and must start after the suspension term, else `ERR_CHECKPOINT_TERM_INVALID`.
19. **Program code uniqueness** — else `ERR_PROGRAM_CODE_CONFLICT`.
20. **Student number uniqueness** — else `ERR_STUDENT_NUMBER_CONFLICT`.
21. **Evaluation referential integrity** — the evaluation an appeal cites must be the caller's own official suspension evaluation, else `ERR_EVALUATION_MISMATCH`.
22. **Body well-formedness** — required fields present, enums valid, dates coherent, else `ERR_INVALID_REQUEST`. This check is deliberately last: a malformed body surfaces only after every more specific rule has passed.

Two worked examples illustrate the consequences. On appeal submission, a caller whose student version is stale is rejected first (`ERR_STALE_VERSION`), before any standing, window, or documentation question is asked; a submission that arrives after the appeal deadline with an empty document array fails with `ERR_APPEAL_WINDOW_CLOSED`, never reaching the documentation check; and an appeal that cites a superseded evaluation fails with `ERR_EVALUATION_MISMATCH` only after its documents have passed scrutiny. On resubmission, the ownership screen runs before the from-state check, so a student who touches another student's appeal is refused with `ERR_OWNERSHIP_VIOLATION` even when that appeal is not awaiting information. On term evaluation, a repeat run against an already-evaluated term is rejected as `ERR_INVALID_STATE` before the readiness question is reached, while a first run against a term whose grading is still open fails with `ERR_TERM_NOT_READY`.

### 2.5. Resource Identity and Common Fields

Every primary resource — programs, students, terms, enrollments, evaluations, appeals, plans, checkpoints, and notifications — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments with every modification, including modifications performed by the server itself as cascade side effects.

Recomputing a student's derived fields during grade posting or amendment is a mutation of the student record and therefore refreshes `updated_at` and increments `version`; submitting an appeal likewise increments the student's `version` by exactly one. The audit event is the sole exception to the common-field convention: audit rows are immutable once appended, so an `AuditEvent` carries only `id` and `created_at`, and both `updated_at` and `version` are absent.

### 2.6. Numeric Precision: Credits, Grade Points, and Percentages

Academic metrics are computed with fixed, published precision so that an official figure never drifts between screens. Pace percentages — cumulative or single-term — are rounded half up to exactly 2 decimal places. Grade point averages are rounded half up to exactly 3 decimal places, and they are always derived from the raw cumulative sums with exactly one rounding at the end. Maximum-timeframe arithmetic is performed in whole credits, with the cap rounded down to an integer. Numeric values in API responses are represented as numbers, not strings. Timestamp comparisons in the communication cadence operate at whole-second precision.

### 2.7. The Logical Clock and the Test-Driving Endpoint

The server never reads the wall clock. All system-generated timestamps — `evaluated_at`, `submitted_at`, `decided_at`, `occurred_at`, `scheduled_at`, and `sent_at` — are drawn from a single logical clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An `AidAdministrator` may advance it through a test-driving capability that accepts a target instant `to_iso8601` and responds with the resulting `current_utc`. The clock moves only forward: a target earlier than the current logical time is rejected with `ERR_INVALID_REQUEST`.

### 2.8. Optimistic Concurrency Control on Appeal Submission

Exactly one endpoint participates in optimistic concurrency control. An appeal-submission request — `POST /sap/appeals` — must carry `expected_student_version`, holding the `version` of the appealing student's record as the client last observed it. If the student's current `version` no longer matches the supplied value, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because a successful submission supersedes the student's existing unsubmitted-phase appeal; a client holding a stale version would supersede an appeal it never saw. No other endpoint accepts a version field.

### 2.9. Existence Checks and Left-to-Right Resolution

Whenever a request references resources by identifier — path identifiers, or body-referenced identifiers such as `program_id`, `student_id`, `term_id`, `sap_evaluation_id`, `appeal_id`, `start_term_id`, or the term identifiers inside a checkpoint list — the server validates existence sequentially from left to right. The request is rejected with `ERR_NOT_FOUND` for the first identifier that does not resolve, and no further validation runs. Existence is checked before ownership, state, and all business rules, per §2.4.

### 2.10. The Federal Audit Trail

Every mutation in the system appends one or more `AuditEvent` rows to an append-only trail; no endpoint exists to modify or delete audit rows. Each row records `actor_role` and `actor_id` copied from the triggering call's headers — a synthetic system actor is never used, so effects produced inside a cascade are attributed to the role and id of the call that set the cascade in motion — plus the `action` taken, the mutated row's `entity_type` and `entity_id` (a polymorphic reference, not a foreign key), the affected `student_id` for federal-review scoping (null on `Program` and `Term` rows), a `before_json` snapshot of the row before the change (null on creation), an `after_json` snapshot after the change, and `occurred_at` drawn from the logical clock.

The `action` value comes from a fixed vocabulary of twenty-five verbs: `PROGRAM_CREATED`, `TERM_CREATED`, `TERM_GRADING_CLOSED`, `TERM_EVALUATED`, `STUDENT_CREATED`, `ENROLLMENT_CREATED`, `ENROLLMENT_POSTED`, `ENROLLMENT_AMENDED`, `EVALUATION_POSTED`, `EVALUATION_SUPERSEDED`, `STANDING_CHANGED`, `APPEAL_SUBMITTED`, `APPEAL_SUPERSEDED`, `APPEAL_SCREENED`, `APPEAL_INFO_REQUESTED`, `APPEAL_RESUBMITTED`, `APPEAL_DECIDED`, `PLAN_CREATED`, `PLAN_REVISED`, `CHECKPOINT_EVALUATED`, `PLAN_COMPLETED`, `PLAN_FAILED`, `NOTIFICATION_QUEUED`, `NOTIFICATION_SENT`, and `NOTIFICATION_CANCELLED`. Read access to the trail is restricted to the `Auditor` and `AidAdministrator` roles; the audit-event list accepts `student_id`, `entity_type`, `entity_id`, and `action` filters alongside the standard pagination parameters.

## 3. Business Logic & Workflows

### 3.1. Programs and the Standards They Carry

A `Registrar` begins by registering each academic program with a unique `code` (for example `BS-CSCI`), a display `name`, and the published program length in `required_credits`. That length anchors the maximum-timeframe rule: the student's lifetime cap is one and a half times the `required_credits`, rounded down to a whole credit (§3.3 develops the full arithmetic). A duplicate `code` is rejected with `ERR_PROGRAM_CODE_CONFLICT`, and the creation is recorded with a `PROGRAM_CREATED` audit event.

Four policy knobs ride on the program, each with a federal-practice default. The qualitative standard `min_gpa` defaults to 2.0 and is compared against the student's cumulative GPA at three-decimal precision. The quantitative standard `min_pace_pct` defaults to 67.0 and is compared against the student's pace percentage at two-decimal precision. When a suspension is evaluated, `appeal_window_days` (default 14) fixes how many days the student has to submit an appeal, with the deadline day itself still open. Finally, `reminder_offset_days` (default the two-entry list 7 and 13) fixes the days after a suspension evaluation at which appeal-deadline reminders are scheduled to reach the student.

### 3.2. Students, Terms, and the Enrollment Ledger

Before any enrollment exists, a `Registrar` registers the student with a unique `student_number` — duplicates are rejected with `ERR_STUDENT_NUMBER_CONFLICT` — along with the `full_name` and the `program_id` of the program of enrollment. The new record starts in `GOOD_STANDING` with zeroed cumulative counters and `max_tf_exceeded` false, and any computed or system-managed fields supplied in the creation body are ignored. A `STUDENT_CREATED` audit event is appended. The student list accepts `program_id` and `sap_status` filters; per §2.1 a `Student` caller sees only their own record, whether reading it directly or listing.

Terms are the registrar's calendar spine. Creating a term takes a `code` such as `2026FA`, a monotonically increasing ordinal `seq` that later drives academic-plan coverage arithmetic, and a `start_date`/`end_date` pair interpreted as a closed interval — the start must fall on or before the end, else `ERR_INVALID_REQUEST`. A new term may not intersect any existing term's interval under closed-interval semantics: both boundary days count as occupied, so two ranges that merely touch on a single calendar day still conflict and the create fails with `ERR_TERM_DATE_OVERLAP`. Terms open in `OPEN` status, and creation appends `TERM_CREATED`.

Within an `OPEN` term, the registrar enrolls students with a payload containing the `student_id`, the `term_id`, and the `attempted_credits`. Enrollment into a term that is no longer `OPEN` is rejected with `ERR_INVALID_STATE`. Each enrollment begins `IN_PROGRESS`; its outcome fields `earned_credits`, `quality_points`, and `gpa_hours` remain null while coursework is underway, and its `amendment_count` starts at zero. The attempted-credit figure is fixed at creation — later amendments adjust only outcome fields — and creation appends `ENROLLMENT_CREATED`. The enrollment list accepts `student_id`, `term_id`, and `status` filters.

Grade posting moves an enrollment from `IN_PROGRESS` to `POSTED`, recording the final `earned_credits`, `quality_points`, and `gpa_hours`; posting from any other state is rejected with `ERR_INVALID_STATE`. Posting recomputes the student's cumulative figures from scratch (§3.3), increments the student's `version`, and appends `ENROLLMENT_POSTED`. When a grade is later corrected, amendment moves the enrollment from `POSTED` to `AMENDED` — or from `AMENDED` to `AMENDED` again, since repeat amendments are permitted and each appends its own audit row. Every amendment requires the replacement `earned_credits`, `quality_points`, and `gpa_hours` plus an `amendment_reason`; a missing reason fails with `ERR_INVALID_REQUEST`, and the most recent reason is retained on the record for federal audit. Amending from `IN_PROGRESS` is rejected with `ERR_INVALID_STATE`. The amendment fully reverses the enrollment's prior contribution to the student's cumulative counters and applies the new values, increments `amendment_count`, bumps the student's `version`, and appends `ENROLLMENT_AMENDED`.

Amendment carries one more consequence when the registrar is correcting an already-evaluated term. If an `OFFICIAL` evaluation exists for that student and term, it is superseded — its status becomes `SUPERSEDED` — and the single-student evaluation pipeline of §3.5 re-runs: a replacement `OFFICIAL` evaluation is created from the recomputed metrics, standing is reassigned, notifications are queued, and the corresponding audit rows (`EVALUATION_SUPERSEDED`, then `EVALUATION_POSTED`, then whatever the standing and notification cascade adds) are appended.

### 3.3. Measuring Progress: Pace, GPA, and Maximum Timeframe

All official academic measurement rests on a single basis set: the student's enrollment rows in `POSTED` or `AMENDED` status. Rows still `IN_PROGRESS` never enter official figures. From that basis the student record maintains four cumulative counters — `cumulative_attempted_credits`, `cumulative_earned_credits`, `cumulative_quality_points`, and `cumulative_gpa_hours`, each the simple sum of the corresponding enrollment field over the basis set — and two derived metrics.

The pace metric `pace_pct` is one hundred times the summed earned credits divided by the summed attempted credits, rounded half up to two decimal places; it is null when no attempted credits exist at all. A student passes the quantitative standard when their pace is at least the program's `min_pace_pct` — the boundary is inclusive, so a pace of exactly 67.00 satisfies a 67.0 standard.

The cumulative GPA `cumulative_gpa` is the summed quality points divided by the summed GPA hours, rounded half up to three decimal places, and it is null when the student has no GPA-counting hours. Pass/fail coursework contributes its attempted and earned credits to the pace basis but contributes zero `gpa_hours` and zero `quality_points` to the GPA basis. One rounding rule is pinned because it decides real cases: the cumulative GPA must be computed from the raw cumulative sums and rounded exactly once at the end. Consider a record of two posted rows, one carrying 4.6 quality points over 3 GPA hours and another carrying 13.9 quality points over 9 GPA hours. The official figure divides the raw sums — 18.5 quality points over 12 GPA hours — and rounds once, yielding 1.542. Rounding each term first and then credit-weighting the rounded terms would report 1.541; that recomposition is expressly forbidden. A student passes the qualitative standard when their cumulative GPA is at least the program's `min_gpa` — exactly 2.000 passes a 2.0 standard — and a null GPA is treated as satisfying the qualitative standard.

The maximum-timeframe test projects whether the student can still finish inside the federal cap. The cap is the largest whole number of credits not exceeding one and a half times the program's `required_credits`. The credits still required are the `required_credits` minus `cumulative_earned_credits`, floored at zero — a student who has already earned more than the published length has nothing still required. Headroom, the cap minus `cumulative_attempted_credits`, is snapshotted onto each evaluation as `max_tf_headroom_credits`. The projection is exceeded when the attempted credits plus the credits still required come to strictly more than the cap; a student whose attempted credits exactly equal the cap with nothing left to earn is still within the timeframe. A weaker attempted-only variant exists purely for advising (§3.4): it declares the timeframe blown only when attempted credits alone exceed the cap, so on identical data it fires strictly later than the projection. The student record's `max_tf_exceeded` flag mirrors the projection result of the most recent `OFFICIAL` evaluation and stays false until the first evaluation exists.

### 3.4. The Advising Preview

Before official results exist, an `AidOfficer` — or the student, reading their own record — can request an advising preview of where a student would stand on current data. The preview is read-only, runs no pipeline, and deliberately reports both measurement bases side by side. Its payload carries `pace_pct_official_basis`, the official pace over posted and amended rows only, next to `pace_pct_projected`, a best-case figure that additionally counts every in-progress enrollment's attempted credits as both attempted and earned; on identical inputs the projected figure is never lower than the official one. It reports `cumulative_gpa` under the raw-sums rule of §3.3. And it reports both maximum-timeframe variants: `max_tf_attempted_only_exceeded`, the weaker attempted-only test, and `max_tf_projection_exceeded`, the stricter projection test that the official evaluation will actually apply.

### 3.5. Term-End Evaluation and the Standing Pipeline

When grades for a term are final, a `Registrar` closes grading. The transition from `OPEN` to `GRADING_CLOSED` requires that no enrollment in the term remain `IN_PROGRESS`; any lingering in-progress row fails the close with `ERR_ENROLLMENTS_PENDING`. Closing from a state other than `OPEN` is rejected with `ERR_INVALID_STATE`. Once closed, the term no longer accepts new enrollments, and the close appends `TERM_GRADING_CLOSED`.

Evaluation is the aid office's turn. An `AidOfficer` runs the evaluation pipeline over a `GRADING_CLOSED` term; a run against a term that has not been closed fails with `ERR_TERM_NOT_READY`, and a repeat run against an already `EVALUATED` term fails with `ERR_INVALID_STATE`, since each term is evaluated exactly once before `EVALUATED` becomes terminal. The response summarizes the sweep with four counters: `evaluated_count`, `good_standing_count`, `warning_count`, and `suspension_count`.

The sweep set has two parts: every student with at least one enrollment in this term in `POSTED` or `AMENDED` status, union every student holding an `ACTIVE` academic plan with a `PENDING` checkpoint tied to this term. Students are processed in ascending order of their record `created_at` — deterministic, and never keyed by record `id`. For each swept student the pipeline executes five steps in a pinned order:

1. Recompute the student's cumulative metrics from the official basis — pace, GPA, and the maximum-timeframe projection of §3.3.
2. If an `ACTIVE` plan holds a `PENDING` checkpoint for this term, compute the student's single-term metrics from this term's posted and amended rows, evaluate the checkpoint, and write its actuals and outcome (§3.7).
3. Derive the plan's fate from that checkpoint: a `MISSED` outcome fails the plan, while a `MET` outcome on the plan's final checkpoint completes it.
4. Assign the student's standing per the decision order below.
5. Queue the notifications dictated by the cadence (§3.8) and append the audit rows.

Each swept student receives an official `SapEvaluation` row bound to their `student_id` and the term's `term_id`, snapshotting the official `pace_pct` at two decimals, the `cumulative_gpa` at three decimals from raw sums (null when no GPA hours exist), `max_tf_headroom_credits`, and the projection flag `max_tf_exceeded`. The row records `prior_standing` — the student's standing immediately before the evaluation — and `result_standing`, the standing it assigns; it stamps `evaluated_at` from the logical clock and computes `appeal_deadline_at` as `evaluated_at` plus the program's `appeal_window_days` days. At most one `OFFICIAL` evaluation exists per student and term: an amendment-driven re-run supersedes the prior `OFFICIAL` row and replaces it. Per student the cascade appends `EVALUATION_POSTED`, then — when standing moved — `STANDING_CHANGED`, then one `NOTIFICATION_QUEUED` per queued notification; the term itself closes the run with a single `TERM_EVALUATED`.

Standing assignment follows a fixed decision order, evaluated only after metrics and any checkpoint work:

1. When an `ACTIVE` plan has a checkpoint for this term, the checkpoint outcome governs outright. `MISSED` assigns `SUSPENSION` regardless of pace, GPA, or timeframe. `MET` on the plan's final — greatest-`seq` — checkpoint assigns `GOOD_STANDING`. `MET` while a later `PENDING` checkpoint remains leaves the student in `PLAN_ACTIVE`.
2. Otherwise, when the maximum-timeframe projection is exceeded, the student is assigned `SUSPENSION`. The timeframe failure overrides every prior standing and grants no warning grace, even when pace and GPA both pass.
3. Otherwise, when pace meets the program standard and the qualitative standard is satisfied — GPA null or at least `min_gpa` — the student is assigned `GOOD_STANDING` from any prior standing. This is the reinstatement path: `WARNING` returns to good standing, and `SUSPENSION`, `PROBATION`, and plan completions all return through it.
4. Otherwise the failure is progressive by prior standing: `GOOD_STANDING` moves to `WARNING`; `WARNING` moves to `SUSPENSION`; `SUSPENSION` remains `SUSPENSION`; `PROBATION` falls back to `SUSPENSION`; `PLAN_PENDING` remains `PLAN_PENDING` while the student awaits plan creation.

Two notification subtleties belong to this pipeline. An unchanged standing ordinarily produces neither a standing notification nor a `STANDING_CHANGED` audit — a student who stays in `GOOD_STANDING` simply gets an evaluation row. Continued `SUSPENSION` is the single exception: because the new evaluation carries a new `appeal_deadline_at`, the full suspension cadence — the standing-change notice plus a fresh round of appeal-deadline reminders against the new window — is re-issued, and the `STANDING_CHANGED` audit is appended even though the standing string did not change. A plan student who never enrolled in a checkpoint term is still swept: their single-term metrics default to zero earned credits, zero attempted credits, and a null GPA, so the checkpoint evaluates `MISSED` and the plan fails (§3.7).

### 3.6. The Appeal Lifecycle: Submission to Committee Decision

A suspended student may contest the outcome through a single active appeal. Submission is the student's own act — the caller's identity supplies the appealing `student_id` — and the payload contains the `sap_evaluation_id` of the official suspension evaluation being appealed, a `reason_category` of `MEDICAL`, `FAMILY_EMERGENCY`, `MILITARY`, or `OTHER`, a free-text `statement` of mitigating circumstances, a `documents` array whose every element carries a `doc_type` and a `description`, and the concurrency guard `expected_student_version` described in §2.8.

The submission guards fire in the global order of §2.4, and their business substance is this: the caller must currently stand in `SUSPENSION` (`ERR_STUDENT_NOT_SUSPENDED`); no appeal of theirs may already sit in `UNDER_REVIEW` (`ERR_APPEAL_UNDER_REVIEW`); the referenced evaluation's window must still be open, with the current logical time on or before `appeal_deadline_at` — the deadline instant itself still accepts submissions (`ERR_APPEAL_WINDOW_CLOSED`); at least one document must be attached (`ERR_APPEAL_DOCS_REQUIRED`); and the referenced evaluation must be an `OFFICIAL` row belonging to the caller whose `result_standing` is `SUSPENSION` (`ERR_EVALUATION_MISMATCH`). On success the appeal opens in `SUBMITTED` with `submitted_at` stamped from the logical clock and `decided_at` still null, the student's `version` increments by one, and `APPEAL_SUBMITTED` is audited. Submission also retires the student's older unfinished appeal: one still sitting in `SUBMITTED` moves `SUBMITTED` → `SUPERSEDED`, and one awaiting more documentation moves `MORE_INFO_REQUESTED` → `SUPERSEDED`, with `APPEAL_SUPERSEDED` appended beside the submission's audit row. The appeal list accepts `student_id`, `sap_evaluation_id`, and `status` filters.

Screening begins the office's work: an `AidOfficer` screens a `SUBMITTED` appeal, moving it to `UNDER_REVIEW` and appending `APPEAL_SCREENED`; screening from any other state is rejected with `ERR_INVALID_STATE`. When the file is thin, the officer requests more information, moving the appeal from `UNDER_REVIEW` to `MORE_INFO_REQUESTED`; the supplied `info_request_note` is recorded on the appeal's `rationale` field, and `APPEAL_INFO_REQUESTED` is audited. The student then resubmits — owner only, else `ERR_OWNERSHIP_VIOLATION` — moving the appeal from `MORE_INFO_REQUESTED` back to `SUBMITTED`; resubmission appends at least one new document to the `documents` array (zero documents fail with `ERR_APPEAL_DOCS_REQUIRED`) and may optionally replace the `statement`, with `APPEAL_RESUBMITTED` audited.

The decision belongs to a `CommitteeMember` and requires the appeal to sit in `UNDER_REVIEW`. A decision attempted while the appeal is `SUBMITTED` or back in `MORE_INFO_REQUESTED` fails with `ERR_DECISION_REQUIRES_REVIEW`; one attempted on an appeal that already reached a terminal outcome is rejected with `ERR_INVALID_STATE`. The payload carries the `decision`, an optional `resolution`, and the committee's `rationale`, which is recorded on the appeal along with `decided_at`. An approval must name its `resolution` — `WITH_PLAN` or `PROBATION_ONLY` — and an approval without one fails with `ERR_INVALID_REQUEST`; the field stays null on every appeal that was never approved. The three branches diverge in what they do to the student's standing. Approval `WITH_PLAN` moves the appeal `UNDER_REVIEW` → `APPROVED` and the student from `SUSPENSION` to `PLAN_PENDING`, holding aid until the plan of §3.7 exists. Approval `PROBATION_ONLY` likewise moves the appeal `UNDER_REVIEW` → `APPROVED` but moves the student from `SUSPENSION` to `PROBATION`, restoring eligibility immediately under continued scrutiny. Denial moves the appeal `UNDER_REVIEW` → `DENIED` and changes nothing else: the student remains in `SUSPENSION`, and the standing string, the window, and any queued reminders all stay as they were. Every decision queues an `APPEAL_DECISION` notification at `decided_at` and appends `APPEAL_DECIDED`; an approval additionally appends `STANDING_CHANGED`, and the queued notification adds its `NOTIFICATION_QUEUED` audit. `APPROVED`, `DENIED`, and `SUPERSEDED` are terminal: no further transition leaves them.

### 3.7. Academic Plans and Term-by-Term Checkpoints

An approved `WITH_PLAN` appeal leaves the student in `PLAN_PENDING`, and an `AidOfficer` converts that holding state into a monitored academic plan. The creation payload names the `student_id`, the `appeal_id` of the approved appeal, the `start_term_id` of the first covered term, the plan's credit budget `total_required_credits`, and the `checkpoints` list — each checkpoint carrying a `term_id`, a `required_term_gpa` floor, a `required_term_pace_pct` floor, and a `required_earned_credits` floor. Creation is admissible only while the referenced appeal stands `APPROVED` with resolution `WITH_PLAN` and the student stands `PLAN_PENDING`; anything else fails with `ERR_PLAN_NOT_ALLOWED`.

Three structural rules discipline the checkpoint list, and they are checked in the global order after admissibility. Coverage must not collide: the plan covers the half-open interval of term ordinals from `coverage_start_seq` — the start term's `seq` — up to but not including `coverage_end_seq_exclusive` — one greater than the largest checkpoint term `seq` — and that interval may not intersect the coverage of any other plan of the same student in any status, on pain of `ERR_PLAN_TERM_OVERLAP`; strict adjacency, one plan ending exactly where the next begins, is allowed. The credit budget must balance: `total_required_credits` must equal the sum of the checkpoints' `required_earned_credits`, else `ERR_PLAN_CREDIT_MISMATCH`. And the checkpoint terms must hang together: their `seq` values must be contiguous starting at the start term's `seq`, each referenced term must exist, and the start term's `seq` must be strictly greater than the `seq` of the term whose suspension evaluation triggered the appeal, else `ERR_CHECKPOINT_TERM_INVALID`.

A successfully created plan opens `ACTIVE` with every checkpoint `PENDING`, moves the student from `PLAN_PENDING` to `PLAN_ACTIVE`, and appends `PLAN_CREATED` and `STANDING_CHANGED`. The plan list accepts `student_id`, `appeal_id`, `start_term_id`, and `status` filters; the checkpoint list accepts `plan_id`, `term_id`, and `outcome` filters.

Checkpoints are evaluated only by the term pipeline of §3.5. When the sweep reaches a plan student whose checkpoint covers the evaluated term, the student's single-term actuals are computed from that term's posted and amended rows: `actual_term_gpa` at three-decimal precision (null when the term contributed no GPA hours), `actual_term_pace_pct` at two-decimal precision (null when nothing was attempted), and `actual_earned_credits`. The checkpoint is `MET` when the term GPA is null or at least `required_term_gpa`, and the term pace is non-null and at least `required_term_pace_pct`, and the term earned credits are at least `required_earned_credits` — all three comparisons inclusive, so an actual exactly equal to its floor counts as met. Any shortfall, including a pace that cannot be computed, makes the checkpoint `MISSED`, and a plan student with no enrollment in the checkpoint term evaluates against zeroed actuals and therefore misses. Either way the actuals are written, a `PLAN_RESULT` notification is queued, and `CHECKPOINT_EVALUATED` is audited.

The plan's fate follows the checkpoint. A `MISSED` outcome fails the plan — `ACTIVE` to `FAILED` — and drops the student back to `SUSPENSION` with a fresh appeal window and a fresh round of reminders; `PLAN_FAILED` and `STANDING_CHANGED` join the audit row set. A `MET` outcome on the plan's final checkpoint completes the plan — `ACTIVE` to `COMPLETED` — and restores the student to `GOOD_STANDING`, queuing both the `PLAN_RESULT` and a `REINSTATEMENT` notification while `PLAN_COMPLETED` and `STANDING_CHANGED` are audited. A `MET` outcome with later checkpoints still pending changes neither plan status nor standing: the student remains `PLAN_ACTIVE`, and only the `PLAN_RESULT` notification and `CHECKPOINT_EVALUATED` audit appear. `COMPLETED` and `FAILED` are terminal.

While every checkpoint still stands `PENDING`, an `AidOfficer` may revise the plan, replacing the entire checkpoint list in one motion. Revision on a plan that is no longer `ACTIVE`, or one whose checkpoints have already been evaluated, is rejected with `ERR_INVALID_STATE`. The replacement list must still satisfy the credit invariant — its floors must sum to the unchanged `total_required_credits`, since the budget itself is invariant under revise — and a revision whose checkpoints sum elsewhere is rejected with `ERR_PLAN_CREDIT_MISMATCH`, leaving the plan untouched. A successful revision recomputes the coverage bounds from the replacement list and appends `PLAN_REVISED`.

### 3.8. Communications: Notification Cadence and the Dispatch Sweep

Every message the institution owes a student is materialized as a `Notification` row bound to the recipient's `student_id`, with a `kind` of `STANDING_CHANGE`, `APPEAL_DEADLINE_REMINDER`, `APPEAL_DECISION`, `PLAN_RESULT`, or `REINSTATEMENT`; a human-readable `detail` (for example, a standing transition from `GOOD_STANDING` to `WARNING`); a `scheduled_at` earliest send time; and a `sent_at` that stays null while the row waits. Rows open `QUEUED` and close as `SENT` or `CANCELLED`, each queueing appends a `NOTIFICATION_QUEUED` audit, and the notification list accepts `student_id`, `kind`, and `status` filters.

Queueing follows the evaluation cadence of the pipeline. When an evaluation assigns `SUSPENSION` and that differs from the prior standing — and also, as the lone exception, when a continued `SUSPENSION` is re-affirmed — the office queues a `STANDING_CHANGE` notice at `evaluated_at` and one `APPEAL_DEADLINE_REMINDER` per entry in the program's `reminder_offset_days`, each scheduled at `evaluated_at` plus its offset in days. When an evaluation returns a student to `GOOD_STANDING` from `SUSPENSION`, `PROBATION`, or `PLAN_ACTIVE`, a `REINSTATEMENT` notice is queued at `evaluated_at`. Any other standing change — a fall to `WARNING`, a recovery from `WARNING` — queues a plain `STANDING_CHANGE` at `evaluated_at`. An unchanged standing queues nothing and appends no `STANDING_CHANGED` audit, continued suspension excepted per §3.5. Outside the pipeline, a committee decision queues `APPEAL_DECISION` at `decided_at`, and a checkpoint evaluation queues `PLAN_RESULT` at `evaluated_at`; plan creation itself queues nothing.

Dispatch is an explicit `AidOfficer` sweep, processed in ascending `scheduled_at` order at whole-second precision. Every `QUEUED` row whose scheduled time has arrived — `scheduled_at` on or before the current logical time — is sent: its status becomes `SENT`, `sent_at` is set to the current time, and `NOTIFICATION_SENT` is audited. The same sweep cancels obviated deadline reminders: any `QUEUED` `APPEAL_DEADLINE_REMINDER` whose student now holds an appeal in `SUBMITTED`, `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `APPROVED`, or whose standing is no longer `SUSPENSION`, becomes `CANCELLED` with `NOTIFICATION_CANCELLED` audited. A denied appeal obviates nothing — the student remains suspended and the window reminders still matter. The sweep responds with the two tallies `sent_count` and `cancelled_count`.

## 4. Endpoint Definitions

Operations that create a new resource — a program, term, student, enrollment, appeal, or academic plan — return `201 Created`. Reads, state transitions, and other modifications of existing resources return `200 OK`. The table below summarizes the HTTP contract; the full request and response semantics of each operation are defined by the workflows in §3 and the principles in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sap/programs` | Create a program carrying the SAP policy thresholds | Registrar |
| GET | `/sap/programs/{id}` | Read a program | Any authenticated role |
| POST | `/sap/terms` | Create a term; date-range conflicts with existing terms are rejected | Registrar |
| GET | `/sap/terms/{id}` | Read a term | Any authenticated role |
| POST | `/sap/terms/{id}/close-grading` | Close grading for a term once no in-progress enrollments remain | Registrar |
| POST | `/sap/terms/{id}/evaluate` | Run the SAP evaluation pipeline over the term's sweep set | AidOfficer |
| POST | `/sap/students` | Register a student in a program | Registrar |
| GET | `/sap/students/{id}` | Read a student (Student role: own record only) | Any authenticated role |
| GET | `/sap/students` | List students with filters and pagination (Student role: own record only) | Any authenticated role |
| GET | `/sap/students/{id}/sap-preview` | Read the advising preview of provisional SAP metrics | Student, AidOfficer |
| POST | `/sap/term-enrollments` | Create an in-progress enrollment in an open term | Registrar |
| GET | `/sap/term-enrollments/{id}` | Read an enrollment | Any authenticated role |
| GET | `/sap/term-enrollments` | List enrollments with filters | Any authenticated role |
| POST | `/sap/term-enrollments/{id}/post` | Post final grades for an enrollment | Registrar |
| POST | `/sap/term-enrollments/{id}/amend` | Amend an enrollment's posted outcome fields, re-running evaluation as needed | Registrar |
| GET | `/sap/evaluations/{id}` | Read an evaluation | Any authenticated role |
| GET | `/sap/evaluations` | List evaluations with filters | Any authenticated role |
| POST | `/sap/appeals` | Submit a SAP appeal against an official suspension evaluation | Student |
| GET | `/sap/appeals/{id}` | Read an appeal | Any authenticated role |
| GET | `/sap/appeals` | List appeals with filters | Any authenticated role |
| POST | `/sap/appeals/{id}/screen` | Screen a submitted appeal into review | AidOfficer |
| POST | `/sap/appeals/{id}/request-info` | Request additional documentation on an appeal under review | AidOfficer |
| POST | `/sap/appeals/{id}/resubmit` | Resubmit an appeal with additional documentation (owner only) | Student |
| POST | `/sap/appeals/{id}/decide` | Record the committee's decision on an appeal under review | CommitteeMember |
| POST | `/sap/plans` | Create an academic plan against an approved with-plan appeal | AidOfficer |
| GET | `/sap/plans/{id}` | Read a plan | Any authenticated role |
| GET | `/sap/plans` | List plans with filters | Any authenticated role |
| POST | `/sap/plans/{id}/revise` | Replace the checkpoint list of an unevaluated active plan | AidOfficer |
| GET | `/sap/checkpoints/{id}` | Read a checkpoint | Any authenticated role |
| GET | `/sap/checkpoints` | List checkpoints with filters | Any authenticated role |
| GET | `/sap/notifications/{id}` | Read a notification | Any authenticated role |
| GET | `/sap/notifications` | List notifications with filters | Any authenticated role |
| POST | `/sap/notifications/dispatch` | Send due notifications and cancel obviated deadline reminders | AidOfficer |
| GET | `/sap/audit-events/{id}` | Read one audit event (federal review) | Auditor, AidAdministrator |
| GET | `/sap/audit-events` | List audit events with filters (append-only trail) | Auditor, AidAdministrator |
| POST | `/sap/_clock/set_current_utc` | Advance the logical clock to a supplied instant | AidAdministrator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows and principles above; this table is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TERM_NOT_READY` | 409 Conflict |
| `ERR_ENROLLMENTS_PENDING` | 409 Conflict |
| `ERR_STUDENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_APPEAL_UNDER_REVIEW` | 409 Conflict |
| `ERR_DECISION_REQUIRES_REVIEW` | 409 Conflict |
| `ERR_PLAN_NOT_ALLOWED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPEAL_DOCS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TERM_DATE_OVERLAP` | 409 Conflict |
| `ERR_PLAN_TERM_OVERLAP` | 409 Conflict |
| `ERR_PLAN_CREDIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CHECKPOINT_TERM_INVALID` | 422 Unprocessable Entity |
| `ERR_PROGRAM_CODE_CONFLICT` | 409 Conflict |
| `ERR_STUDENT_NUMBER_CONFLICT` | 409 Conflict |
| `ERR_EVALUATION_MISMATCH` | 409 Conflict |
