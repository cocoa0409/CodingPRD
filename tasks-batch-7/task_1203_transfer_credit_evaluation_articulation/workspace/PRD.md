# Transfer Credit Evaluation Articulation API — Product Requirements Document

## 1. Introduction

Universities that welcome transfer students carry a persistent operational burden: every incoming transcript must be read against a shifting web of bilateral articulation agreements, catalog rules, and faculty judgment, and every credit decision must survive later audit. This document specifies the Transfer Credit Evaluation & Articulation API, the system of record for a university transfer center. It covers the full arc of the business — registration of partner institutions and their credit systems, maintenance of articulation agreements and course-to-course equivalency rules, intake and verification of external transcripts, automated and manual evaluation of each transferred course, syllabus-based student petitions with faculty adjudication, appeals with segregation of duties, military and prior-learning credit assessment, and the publication of version-pinned transfer guides that prospective students can rely on even as the underlying agreements evolve.

Two design commitments shape everything that follows. First, every credit figure the system reports is reproducible: rounding order is pinned, provisional and final award math deliberately differ, and posted totals are compensable — a reopened evaluation returns the student's ledger to exactly its pre-posting state. Second, authority is segregated: intake staff never evaluate, the evaluator who finalizes an evaluation may not post it, and the faculty member who denied a petition may not review its appeal. The API is mounted under `/api`, and all behavior described here is driven by a controllable logical clock so that time-based expiry and appeal windows are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request with either header missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles:

- `RegistrarAdmin` — the transfer center administrator; owns partner institutions, the internal course catalog, articulation agreements and equivalencies, student records, transfer guides, and the logical clock.
- `TransferCenterStaff` — intake staff; receives, verifies, and rejects transcripts.
- `TransferEvaluator` — the credential evaluator; creates and works evaluations, adopts and denies line items, and verifies, credits, or rejects prior-learning assessments. Maker-checker segregation applies at posting time.
- `FacultyAdjudicator` — faculty reviewer for syllabus petitions and appeals.
- `Student` — a transfer student; files petitions and appeals and submits prior-learning assessments, and may act only on their own records.

When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `TransferStudent`; ownership checks on any resource that references a `TransferStudent` compare the resource's student foreign-key field to `X-User-ID`. A `Student` acting on a resource owned by a different student is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — this guards petition creation, appeal creation, prior-learning submission, and a student's reads of their own resources. When `X-User-Role` is `RegistrarAdmin`, `TransferCenterStaff`, `TransferEvaluator`, or `FacultyAdjudicator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands attribution (for example, as `evaluated_by_id`, `posted_by_id`, or `adjudicator_id`) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — partner institutions, internal courses, articulation agreements, course equivalencies, students, transcripts, evaluations, line items, petitions, appeals, prior-learning assessments, requirement applications, and transfer guides — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation. It is the basis of optimistic concurrency control where such control is declared.

Any mutation described in §3 — including system-driven cascade mutations such as an agreement expiring, an equivalency flipping to `INACTIVE`, or a computed total being recomputed — updates the owning resource's `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Time-Driven Cascades

The server maintains a logical clock that governs all timestamps, window-coverage tests, and deadlines in this document. Before any client sets it, the logical clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A `RegistrarAdmin` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock synchronously evaluates agreement expiry: any agreement in `ACTIVE` or `SUSPENDED` whose half-open effective window has ended transitions to `EXPIRED` as part of the same request, with the full cascade described in §3.2.

### 2.6. Credit Arithmetic, Precision, and Rounding

All rounding in the system is round-half-up, and every rounding boundary is pinned so results are reproducible. Grade points are drawn from a fixed scale of one-decimal-place literals. Provisional credit estimates are rounded to exactly one decimal place, and that rounding happens **before** any cap against a course's credit hours is applied. Final awarded credits are quantized to a multiple of 0.5 by doubling the raw value, rounding half-up to a whole number, and halving again, with the cap applied afterward. Evaluation-level provisional totals sum the already-rounded per-line values and apply no second rounding — summing unrounded raw values and rounding once at the end is forbidden, because it yields a different number. Transfer GPA multiplies are rounded per line to two decimal places first, then summed, then divided, with the quotient rounded half-up to three decimal places. The posting waterfall's inputs are half-step values and its arithmetic is exact to 0.5. Credit-hour inputs that are required to fall on half-credit steps (catalog course hours, PLA claimed credits) are validated as such at the request-schema layer.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two take a version field:

- Creating a course equivalency under an agreement requires `expected_agreement_version` in the request body, carrying the version of the agreement the client last observed. Because every equivalency creation itself increments the parent agreement's `version` by one, a client working from a stale read would otherwise add rules to an agreement whose rule set has already advanced. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a student profile requires `expected_student_version` in the request body, matching the student's current `version`. A mismatch — for example because a posting or reopening cascade advanced the student's credit totals after the client last read the record — is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; all other mutation ordering is enforced through state-machine preconditions.

### 2.8. Request Validation Pipeline

Every request is validated in a fixed pipeline, and a failure at any stage short-circuits the stages after it. The global backbone runs in this order: first, presence of the authentication headers (failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role authorization for the endpoint (`ERR_FORBIDDEN`); third, request-body schema — required fields present, enum values valid, date ranges correctly ordered, numeric domains respected (`ERR_INVALID_REQUEST`); fourth, existence of every path identifier and every body foreign key (`ERR_NOT_FOUND`); fifth, the optimistic-concurrency check on the two endpoints that declare one (`ERR_STALE_VERSION`); sixth, student ownership (`ERR_NOT_RESOURCE_OWNER`); seventh, the invoked transition's from-state precondition (`ERR_INVALID_STATE`). Endpoint-specific cross-entity and business rules then run in the relative order documented alongside each workflow in §3: on evaluation creation the one-evaluation-per-transcript uniqueness check runs **before** the transcript-state check, so a duplicate attempt remains observable even after the transcript has moved on; on line adopt and deny, the line's own from-state precondition is evaluated before the enclosing evaluation's `IN_REVIEW` requirement; segregation-of-duties checks are the last gate on the operations that declare them.

### 2.9. Nested Resource Retrieval

Where an endpoint path nests one resource beneath another — equivalencies are created and listed beneath a parent agreement identified by `agreementId`, and every other resource is addressed by its own `id` — identifiers are validated strictly left to right. A request naming a non-existent agreement is rejected with `ERR_NOT_FOUND` for the agreement before the system considers anything beneath it, and the same discipline applies to any deeper segment.

### 2.10. Cross-Aggregate Consistency and Cascade Invariants

Agreement status is the single source of truth for the usability of its equivalencies, and equivalency status in turn drives the state of evaluation line items that matched against it. When an agreement leaves `ACTIVE`, its equivalencies go `INACTIVE` and dependent open line items are flipped to require a petition; when a suspended agreement is reactivated, exactly the set of equivalencies that was inactivated by the paired suspension is restored — the count of `ACTIVE` equivalencies immediately after reactivation equals the count immediately before the suspension. Compensation is deliberately asymmetric: line items flipped by a cascade are never auto-restored, because an evaluator must re-adopt them. Posted credit is likewise compensable — reopening an evaluation removes exactly the credit its posting added, so the student's posted totals after a paired post-and-reopen equal the totals before it whenever no other writes intervened.

## 3. Business Logic & Workflows

### 3.1. Partner Institutions and the Internal Course Catalog

A `RegistrarAdmin` onboards each sending institution as a partner record carrying its `name`, a unique short `institution_code`, and the `credit_system` in which that partner's credits are denominated — exactly one of `SEMESTER` or `QUARTER`. An optional `state_code` may be recorded. The partner's `credit_system` is not cosmetic: it later selects the conversion factor used when credits are awarded (§3.5). The partner list endpoint accepts an optional `credit_system` filter.

The home catalog is maintained as internal courses, each created with a unique `course_code`, a `title`, its `credit_hours` (a multiple of 0.5, no less than 0.5 and no more than 6.0), a `level` of `LOWER`, `UPPER`, or `GRADUATE`, and the owning `department` code. A course may carry `gened_tags`, a list of zero or one general-education slot tags drawn from `GENED_COMMS`, `GENED_MATH`, `GENED_SCIENCE`, `GENED_HUMANITIES`, and `GENED_SOCIAL`; when present, the natural-slot rule reads the first element. Courses are never hard-deleted. Archiving flips the system-managed `is_active` flag to false: archived courses reject every **new** reference — from equivalency creation, petition filing, or a petition adjudicator's override — with `ERR_COURSE_INACTIVE` (HTTP 422), while existing equivalencies and line items that already reference the course continue to resolve. The catalog list endpoint's archival filter semantics are explicit: with no `is_active` parameter only active courses are returned, and passing `is_active` as false lists the archived rows; a `department` filter is also supported.

### 3.2. Articulation Agreements: Windows, Amendments, and Lifecycle

An articulation agreement records, for a given `partner_institution_id`, a `program_scope` — either the literal `ALL` or a department code restricting the agreement to one major — and a half-open effective window from `effective_start` (inclusive) to `effective_end` (exclusive, and strictly after the start). Window discipline is enforced at creation and again for every amendment: the new window must not overlap any existing agreement for the same partner and scope whose status is `DRAFT`, `ACTIVE`, or `SUSPENDED`; windows that merely touch — the new start equal to an existing end, or the new end equal to an existing start — are allowed, because the half-open convention leaves no shared date. A violation is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` (HTTP 409). Agreements may be filtered in list views by `partner_institution_id`, by `status`, and by `amends_agreement_id`.

A new agreement begins in `DRAFT`. Activation by a `RegistrarAdmin` stamps `activated_at` from the logical clock and produces three side effects: any other `ACTIVE` agreement with the same partner and scope is superseded (moving to `SUPERSEDED`); every equivalency belonging to the newly activated agreement that was `INACTIVE` becomes `ACTIVE`; and the agreement itself becomes the one the auto-match selector may draw from. Activation from `DRAFT` to `ACTIVE` requires the agreement to actually be in `DRAFT`, failing otherwise with `ERR_INVALID_STATE`.

Suspension is the operational brake. Suspending an `ACTIVE` agreement moves it to `SUSPENDED` and fires a three-link cascade: every equivalency of the agreement in `ACTIVE` becomes `INACTIVE`; each line item in `AUTO_MATCHED` whose `equivalency_id` references one of those equivalencies — but only while its owning evaluation is still `DRAFT` or `IN_REVIEW` — flips to `PETITION_REQUIRED` with its `equivalency_id`, `internal_course_id`, and `provisional_credits` all cleared to null; and each affected evaluation recomputes its `provisional_credits_total` and `open_line_count`. Lines inside evaluations that have reached `EVALUATED` or `POSTED` are deliberately not touched by this cascade. Reactivation returns a `SUSPENDED` agreement to `ACTIVE` — provided the logical clock's date is still strictly before `effective_end`, since a window that has already ended cannot be revived (`ERR_INVALID_STATE`) — and restores exactly the equivalency set the suspension inactivated, per the count invariant of §2.10; flipped line items are not restored and must be re-adopted by an evaluator.

Expiry is system-driven: when the logical clock reaches or passes `effective_end`, an `ACTIVE` agreement becomes `EXPIRED` with `expired_at` stamped and the same three-link cascade as suspension; a `SUSPENDED` agreement that expires simply stamps `expired_at`, its equivalencies already being `INACTIVE`. The window's end date itself is not covered by the agreement — coverage ends the moment the clock date reaches `effective_end`. Supersession, finally, fires whenever another agreement with the same partner and scope completes a `DRAFT` to `ACTIVE` transition: the previously active agreement moves to `SUPERSEDED` and its equivalencies cascade exactly as under suspension. `EXPIRED` and `SUPERSEDED` are terminal.

Amendments are how agreements evolve without editing history. Creating an amendment against an existing agreement spawns a new agreement in `DRAFT` that inherits the partner and `program_scope` of the amended record, records the lineage in the new agreement's `amends_agreement_id`, and accepts only a fresh `effective_start` and `effective_end` — the same non-overlap rule applies. At most one `DRAFT` amendment may exist per agreement at a time; a second attempt is rejected with `ERR_AMENDMENT_EXISTS` (HTTP 409). When the amendment is later activated, the supersession rule above retires its predecessor.

### 3.3. Course Equivalencies and the Auto-Match Selector

Within an agreement, a `RegistrarAdmin` authors equivalency rules: each names an `internal_course_id`, the partner's `external_course_code` and `external_title`, the `external_credit_hours` (greater than zero, expressed in the partner's credit units), a closed coverage window from `effective_from` through `effective_until` (both dates inclusive, the end no earlier than the start), and an `equivalency_type` of `DIRECT`, `GENED_ONLY`, or `ELECTIVE` (defaulting to `DIRECT` when omitted). The create call is one of the system's two OCC-guarded writes and must carry `expected_agreement_version` (§2.7); a stale base version is rejected with `ERR_STALE_VERSION`. Equivalencies may be added only while the parent agreement is `DRAFT` or `ACTIVE` — against any other status the write fails with `ERR_AGREEMENT_NOT_EDITABLE` (HTTP 409) — and the referenced internal course must be active (`ERR_COURSE_INACTIVE`). Within one agreement, the closed windows of rules sharing the same `external_course_code` must be strictly disjoint, and here touching endpoints **do** count as overlap — a new rule whose `effective_from` equals a sibling's `effective_until` is rejected with `ERR_EQUIVALENCY_WINDOW_OVERLAP` (HTTP 409). Rules under different agreements may freely share a code and overlapping windows; the selector ranks them at match time. Each creation increments the parent agreement's `version`. A rule's own `status` is system-managed: `ACTIVE` when its agreement is `ACTIVE`, otherwise `INACTIVE`, flipping in step with the parent as described in §3.2. Beyond the nested create and list, a flat filtered list accepts `agreement_id`, `internal_course_id`, `external_course_code`, and `status`.

The auto-match selector runs at evaluation intake for each transferable line. A candidate equivalency is eligible only when **all** of the following hold: its `external_course_code` equals the line's; its own status is `ACTIVE`; its agreement is `ACTIVE`; the agreement's partner matches the transcript's `partner_institution_id`; the agreement's `program_scope` is either `ALL` or equals the student's `declared_major`; the transcript's `term_completed` falls within the rule's closed window, both bounds inclusive; and the referenced internal course is active. Eligible candidates are ranked by a total order that never consults identifiers: first, scope specificity — a rule whose agreement is scoped to the student's declared major beats an `ALL`-scoped rule; second, the latest `effective_from` wins; third, the earliest `created_at` wins; fourth, `equivalency_type` in the order `DIRECT`, then `GENED_ONLY`, then `ELECTIVE`. An empty pool sends the line to `PETITION_REQUIRED`.

### 3.4. Student Registration, Transcript Intake, and Evaluation Creation

Students enter the system through registrar registration: a `RegistrarAdmin` records the student's `full_name`, a unique `email`, the `declared_major` department code, and the `catalog_year`, and the student's two ledger totals — `total_posted_transfer_credits` and `total_posted_pla_credits` — are initialized to zero. Subsequent profile updates are the second OCC-guarded write of §2.7, require `expected_student_version`, and increment the student's `version` by one on success; changing `declared_major` re-derives natural slot assignments on future posting waterfalls only and never rewrites rows already posted.

`TransferCenterStaff` intake an external transcript by naming the `student_id`, the `partner_institution_id` it came from, the `term_completed` date the coursework was finished (the date equivalency window coverage is tested against), and the embedded `courses` array — each entry carrying `external_course_code`, `title`, `credit_hours`, and a letter `grade` drawn from the grade scale. A fresh transcript is `RECEIVED`. Verification stamps `verified_at` and moves it to `VERIFIED`; rejection is possible from either `RECEIVED` or `VERIFIED`, records the supplied `reason` in `rejection_reason`, and lands in `REJECTED`, which like `EXTRACTED` is terminal. Transcript lists accept `student_id`, `partner_institution_id`, and `status` filters.

An evaluation is created by a `TransferEvaluator` against one transcript, supplying `student_id` and `transcript_id`. Three cross-entity gates apply in a documented order: at most one evaluation may ever exist per transcript, and this uniqueness check is deliberately evaluated before the transcript-state check — so once the transcript has moved to `EXTRACTED`, a second attempt still surfaces `ERR_DUPLICATE_EVALUATION` (HTTP 409) rather than a state error; the transcript must be in `VERIFIED`, failing with `ERR_TRANSCRIPT_NOT_VERIFIED` (HTTP 409); and the supplied `student_id` must equal the transcript's own student, failing with `ERR_TRANSCRIPT_STUDENT_MISMATCH` (HTTP 422). On success the transcript advances from `VERIFIED` to `EXTRACTED`, the evaluation is born in `DRAFT`, and one line item is created per transcript course. Evaluation list views accept `student_id`, `transcript_id`, and `status` filters.

Each line item is a system-built copy: `evaluation_id` linking back to its evaluation, plus `external_course_code`, `external_title`, `external_credit_hours` (in partner units), and `grade` transcribed from the transcript entry, with `grade_points` mapped from the letter. Intake then triages each line. The grade scale is fixed: A converts to 4.0, A- to 3.7, B+ to 3.3, B to 3.0, B- to 2.7, C+ to 2.3, C to 2.0, C- to 1.7, D to 1.0, and F to 0.0. A grade is transferable when its points are at least 2.0 — a C exactly meets the threshold; a C- does not. A non-transferable line goes straight to `DENIED` with `resolution` set to `AUTO_GRADE` and `denial_reason` recorded as the below-threshold marker. A transferable line runs the §3.3 selector: a non-empty pool moves it to `AUTO_MATCHED`, stamping `equivalency_id` with the winner and `internal_course_id` from the matched rule, and computing its provisional estimate; an empty pool moves it to `PETITION_REQUIRED`. Throughout, the evaluation's `provisional_credits_total` — the sum of the per-line rounded `provisional_credits` values over lines holding one, with no second rounding — and its `open_line_count`, the count of lines in `PENDING`, `AUTO_MATCHED`, or `PETITION_REQUIRED`, are recomputed whenever any line's provisional value changes, whether at intake, on a cascade flip, or on denial.

### 3.5. Line-Item Resolution and the Two Credit Variants

Work on an evaluation begins when a `TransferEvaluator` starts review, moving it `DRAFT` → `IN_REVIEW`. Line items are then resolved one by one; both adopt and deny require the line to currently be `AUTO_MATCHED` or `PETITION_REQUIRED` (otherwise `ERR_INVALID_STATE`) and, evaluated after that line-state check, the enclosing evaluation to be `IN_REVIEW` (otherwise `ERR_EVALUATION_NOT_IN_REVIEW`, HTTP 409).

The system carries two deliberate credit variants, and identical input data yields different numbers under each. The **provisional variant** is a planning estimate computed when a line becomes `AUTO_MATCHED`: multiply the line's `external_credit_hours` by an estimate factor selected from the partner's `credit_system` — 0.75 for `QUARTER` partners, 1.0 for `SEMESTER` — round the product half-up to one decimal place, and then take the smaller of that rounded value and the matched course's `credit_hours`. The **final variant** governs adoption and finalization: multiply `external_credit_hours` by the exact factor — precisely two-thirds for `QUARTER`, 1.0 for `SEMESTER` — round to the nearest half credit by doubling the product, rounding half-up to a whole number, and halving, then cap at the adopted course's `credit_hours`. The result is always a multiple of 0.5.

Adopting an `AUTO_MATCHED` line is a bare confirmation: `resolution` becomes `AUTO_EQUIVALENCY` and `awarded_credits` is computed under the final variant against the matched course. Adopting a `PETITION_REQUIRED` line is a manual override — the body must name an `internal_course_id` that exists and is active (`ERR_COURSE_INACTIVE`) — setting `resolution` to `MANUAL_OVERRIDE` and computing the final award against the chosen course. (A third adopt path, `resolution` `PETITION`, arrives via adjudication in §3.7.) Denying a line requires a `reason`, which is recorded in `denial_reason`, and clears `provisional_credits` to null. Filtered line-item views accept `equivalency_id`, `internal_course_id`, `status`, and `evaluation_id`.

### 3.6. Finalize, Post, the Credit-Cap Waterfall, and Reopen

Finalization moves an evaluation `IN_REVIEW` → `EVALUATED` and is allowed only when every line item sits in `ADOPTED` or `DENIED` — any unresolved line rejects the call with `ERR_UNRESOLVED_LINE_ITEMS` (HTTP 409). Finalize recomputes each adopted line's `awarded_credits` under the final variant, sums them into `awarded_credits_total`, and records the finisher's header identity in `evaluated_by_id`.

Posting is the fiscal act, and it is maker-checker segregated: the posting evaluator's header identity must differ from `evaluated_by_id`, failing with `ERR_POSTER_IS_EVALUATOR` (HTTP 403) — this segregation check is the last gate evaluated. Posting also demands that every adopted line still carrying an `equivalency_id` references an equivalency whose agreement is currently `ACTIVE`; a single lapsed agreement blocks the post with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). A successful post runs the **credit-cap waterfall** over the adopted lines. The waterfall maintains per-slot need and fill: `MAJOR_CORE` admits 30.0 credits, `MAJOR_ELECTIVE` 12.0, each general-education slot (`GENED_COMMS`, `GENED_MATH`, `GENED_SCIENCE`, `GENED_HUMANITIES`, `GENED_SOCIAL`) admits 6.0, and `FREE_ELECTIVE` admits 24.0; a global purse caps all transfer credit at 60.0. Lines are processed in slot-priority order — `MAJOR_CORE` first, then `MAJOR_ELECTIVE`, then the general-education slots ordered by slot name, then `FREE_ELECTIVE` — with ties broken by the line's `created_at`, earliest first. Each line's natural slot is derived from its course: if the course's `department` equals the student's `declared_major` the natural slot is `MAJOR_CORE`; otherwise, if the course carries a general-education tag, the natural slot is the first element of `gened_tags`; otherwise it is `FREE_ELECTIVE`. For each line, the amount placed into its natural slot is the smallest of the line's `awarded_credits`, that slot's remaining need, and the remaining global purse; any leftover then spills into `FREE_ELECTIVE` — unless the natural slot already is `FREE_ELECTIVE` — again bounded by the leftover, that slot's remaining need, and the remaining global purse. The line's `applied_credits` is the sum placed across both buckets. Every processed line yields a `RequirementApplication` row in its natural slot — even when nothing could be placed, in which case the row records zero — plus a second row in `FREE_ELECTIVE` whenever a spill occurred; each row carries its `student_id`, the `line_item_id` it came from, its `slot`, its `applied_credits`, and a `status` stamped from the line's outcome: `APPLIED` when the full award was placed, `PARTIAL` when some but not all was, `UNAPPLIED` when nothing was. Denied lines produce no rows and consume nothing. Posting then moves every adopted line to `POSTED`, adds the sum of the newly posted `applied_credits` onto the student's `total_posted_transfer_credits`, and records `applied_credits_total`, `posted_by_id`, and `posted_at` on the evaluation.

Reopening unwinds all of it. A `TransferEvaluator` may reopen a `POSTED` evaluation by supplying a `reason`; the same transition fires automatically when an appeal overturns a petition on one of the evaluation's denied lines (§3.7), in which case `reopen_reason` records the appeal-overturn marker. Every posted line returns to `ADOPTED` with `applied_credits` cleared to null, all `RequirementApplication` rows belonging to the evaluation are deleted, the previously applied sum is subtracted from the student's `total_posted_transfer_credits` — full compensation, per the §2.10 invariant — and `applied_credits_total` is zeroed while `posted_by_id` and `posted_at` are nulled. The student's `total_posted_transfer_credits` is, at all times, exactly the sum of `applied_credits` over that student's lines currently in `POSTED`; a post adds exactly its waterfall sum and the paired reopen subtracts exactly the same amount.

### 3.7. Petitions and Appeals

When a line cannot auto-match — or a denial is contested — the student may petition with syllabus evidence. A `Student` files a petition naming the `line_item_id`, the `proposed_internal_course_id` they believe the credit deserves, and a `syllabus_ref` pointing at the supporting document; the petition's `student_id` is derived server-side from the line's evaluation, never taken from the client, and the ownership rule of §2.1 confines students to their own lines. Petitionable lines are exactly those in `PETITION_REQUIRED` or `DENIED` whose evaluation is `IN_REVIEW` or `POSTED`; anything else is rejected with `ERR_LINE_ITEM_NOT_PETITIONABLE` (HTTP 409). The proposed course must be active (`ERR_COURSE_INACTIVE`), and at most one open petition — one in `SUBMITTED` or `UNDER_REVIEW` — may exist per line item, with a duplicate rejected as `ERR_PETITION_ALREADY_OPEN` (HTTP 409); the petitionable-state check is evaluated before the open-petition uniqueness check. Petition lists accept `student_id`, `line_item_id`, `proposed_internal_course_id`, `awarded_internal_course_id`, and `status` filters.

A `FacultyAdjudicator` picks up a `SUBMITTED` petition by starting review, which binds their identity into `adjudicator_id` and moves the petition to `UNDER_REVIEW`. Adjudication takes a `decision` and an `adjudication_note` of at least ten characters, and is only valid while the petition is `UNDER_REVIEW` — otherwise `ERR_PETITION_NOT_UNDER_REVIEW` (HTTP 409). On `APPROVED`, the adjudicator may optionally name an `awarded_internal_course_id` differing from the proposal (which must itself be active, `ERR_COURSE_INACTIVE`); `decided_at` is stamped, and the line item cascades to `ADOPTED` with `resolution` `PETITION`, its `internal_course_id` set to the awarded course when given else the proposed one, and `awarded_credits` computed under the final variant against that course. On `DENIED`, the line remains `PETITION_REQUIRED` and the re-petition loop stays open — the student may file again once no open petition remains. `APPROVED` is a terminal state for a petition.

A denied petition may be appealed once. Filing an appeal requires the petition to be `DENIED` (`ERR_APPEAL_NOT_FILEABLE`, HTTP 409), requires the logical clock to be no later than thirty days after the petition's `decided_at` — the boundary day itself is still timely, after which filing fails with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422) — and tolerates no second appeal per petition (`ERR_APPEAL_ALREADY_EXISTS`, HTTP 409). The student's `grounds` must run at least twenty characters; the appeal's `student_id` is derived from the petition. A new appeal is `FILED`. Starting review binds a reviewer — who must not be the faculty member whose identity sits in the petition's `adjudicator_id`; a self-review attempt is rejected with `ERR_APPEAL_ADJUDICATOR_CONFLICT` (HTTP 403) — and moves the appeal to `UNDER_REVIEW`. Adjudication then lands the appeal in `UPHELD` or `OVERTURNED`, both terminal, stamping `adjudication_note` and `decided_at`. An overturn fires a three-link cascade: the petition moves `DENIED` → `APPROVED`; the line item moves to `ADOPTED` — forcibly from `DENIED` if the evaluation had already posted, or from `PETITION_REQUIRED` otherwise — with `awarded_credits` recomputed under the final variant; and if the owning evaluation is `POSTED`, the evaluation itself is reopened to `IN_REVIEW` with the full compensation of §3.6 and the appeal-overturn reopen marker. Appeal lists accept `petition_id`, `student_id`, and `status` filters.

### 3.8. Prior Learning Assessment and Degree Progress

Military and prior-learning credit runs on a parallel rail. A `Student` submits an assessment with their own `student_id` (ownership-checked against the header), a `source_type` of `MILITARY_JST`, `CLEP`, `AP`, `IB`, or `PORTFOLIO`, a `credential_ref` identifying the credential document, the `claimed_credits` requested (greater than zero and a multiple of 0.5), and optionally a `proposed_internal_course_id` to steer slot placement. The submission is `SUBMITTED`. A `TransferEvaluator` then verifies it, supplying `verified_credits` no greater than the claim — an over-claim verification is rejected with `ERR_VERIFIED_EXCEEDS_CLAIMED` (HTTP 422) — which moves the assessment to `VERIFIED`. Crediting is the capped step: the student's lifetime prior-learning credit is bounded at 30.0, and the credit is allowed exactly when the student's current `total_posted_pla_credits` plus the `verified_credits` does not exceed that bound — landing exactly on 30.0 is permitted, while anything beyond fails with `ERR_PLA_CAP_EXCEEDED` (HTTP 422). A successful credit moves the assessment to `CREDITED`, adds `verified_credits` onto `total_posted_pla_credits`, and creates a `RequirementApplication` row with `pla_id` set, `slot` taken as the natural slot of the proposed course (or `FREE_ELECTIVE` when none was proposed), `applied_credits` equal to `verified_credits`, and status `APPLIED`. Rejection is possible from `SUBMITTED` or `VERIFIED`, records the supplied `reason` in `rejection_reason`, and — from `VERIFIED` — retains the `verified_credits` for audit. `CREDITED` and `REJECTED` are terminal. Assessment lists accept `student_id`, `proposed_internal_course_id`, `status`, and `source_type` filters. Every requirement application row references exactly one credit source — a posted line item via `line_item_id` or a credited assessment via `pla_id`, never both. Requirement applications themselves are read-only, filterable by `student_id`, `line_item_id`, `pla_id`, and `slot`.

The degree-progress read computes a student's standing on demand. It takes a `variant` selector: `CERTIFIED` (the default) counts only certified sources — requirement rows sourced from `POSTED` lines or `CREDITED` assessments; `PROVISIONAL` adds projections for `ADOPTED` lines at their full `awarded_credits` into their natural slot with no waterfall truncation, and for `VERIFIED` assessments at their `verified_credits`, so identical student data yields a larger total under `PROVISIONAL`. The response reports the `variant` used, one entry per slot in `slots` carrying the `slot`, its `required_credits`, `applied_credits`, and `remaining_credits`, plus `total_applied_credits`, the `residency_min_institutional_credits` constant — 30.0 institutional credits the student must still complete in residence — and the `transfer_gpa`. Transfer GPA is computed over the student's `POSTED` lines across all evaluations: each line contributes quality points equal to its `grade_points` times its `awarded_credits`, rounded half-up to two decimal places **before** any summation; the rounded products are summed and divided by the total awarded credits; the quotient is rounded half-up to three decimal places; and when no credits are awarded at all, the GPA is null.

### 3.9. Transfer Guides and Publication Pinning

A transfer guide is the public promise made to prospective students of a given partner and catalog year. A `RegistrarAdmin` drafts one with `partner_institution_id` and `catalog_year`; it begins in `DRAFT`. Publishing requires that at least one agreement for that partner currently be `ACTIVE` — otherwise the publish fails with `ERR_GUIDE_NO_ACTIVE_AGREEMENT` (HTTP 409) — and then pins the agreement set in stone: among the partner's `ACTIVE` agreements the selector picks the one with the latest `effective_start`, breaking ties by earliest `created_at`, and records it as `pinned_agreement_id` together with that agreement's current version integer as `pinned_agreement_version`. The publish stamps `published_at`, captures an immutable `entries_snapshot` of the pinned agreement's equivalency rows — each row preserving its `external_course_code`, `external_title`, `external_credit_hours`, `internal_course_id`, `equivalency_type`, `effective_from`, and `effective_until` exactly as they stood at publish time — and supersedes any other `PUBLISHED` guide for the same partner and catalog year into `ARCHIVED`. A published guide may also be archived manually; `ARCHIVED` is terminal.

Because the snapshot is immutable, later edits, suspensions, or supersessions of the agreement never rewrite a published guide — they merely mark it. A guide's computed `is_stale` flag is true exactly when a `pinned_agreement_id` is set and the pinned agreement is no longer `ACTIVE` or its current version no longer equals `pinned_agreement_version`. The guide's published content is served through a dedicated entries read returning `pinned_agreement_id`, `pinned_agreement_version`, and `entries` equal to the frozen snapshot. Guide lists accept `partner_institution_id`, `pinned_agreement_id`, `status`, and `catalog_year` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. All endpoints are mounted under `/api`. Request and response payloads are not repeated here — they are defined by the workflows of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock; synchronously evaluates agreement expiry cascades | RegistrarAdmin |
| POST | `/api/partner-institutions` | Create a partner institution | RegistrarAdmin |
| GET | `/api/partner-institutions` | List partner institutions (paginated) | Any |
| GET | `/api/partner-institutions/{id}` | Get one partner institution | Any |
| POST | `/api/internal-courses` | Create a catalog course | RegistrarAdmin |
| GET | `/api/internal-courses` | List catalog courses (paginated; archival filter semantics per §3.1) | Any |
| GET | `/api/internal-courses/{id}` | Get one catalog course | Any |
| POST | `/api/internal-courses/{id}/deactivate` | Archive a course (soft delete) | RegistrarAdmin |
| POST | `/api/articulation-agreements` | Create an agreement in DRAFT; window overlap check applies | RegistrarAdmin |
| GET | `/api/articulation-agreements` | List agreements (paginated) | Any |
| GET | `/api/articulation-agreements/{id}` | Get one agreement | Any |
| POST | `/api/articulation-agreements/{id}/activate` | Activate a DRAFT agreement; supersedes same partner+scope | RegistrarAdmin |
| POST | `/api/articulation-agreements/{id}/suspend` | Suspend an ACTIVE agreement (cascades) | RegistrarAdmin |
| POST | `/api/articulation-agreements/{id}/reactivate` | Reactivate a SUSPENDED agreement whose window has not ended | RegistrarAdmin |
| POST | `/api/articulation-agreements/{id}/amendments` | Create a DRAFT amendment of this agreement | RegistrarAdmin |
| POST | `/api/articulation-agreements/{agreementId}/course-equivalencies` | Add an equivalency rule (OCC-guarded on the agreement version) | RegistrarAdmin |
| GET | `/api/articulation-agreements/{agreementId}/course-equivalencies` | List equivalencies under an agreement | Any |
| GET | `/api/course-equivalencies` | Filtered list of equivalencies | Any |
| GET | `/api/course-equivalencies/{id}` | Get one equivalency | Any |
| POST | `/api/students` | Register a transfer student | RegistrarAdmin |
| GET | `/api/students/{id}` | Get one student | Any |
| PATCH | `/api/students/{id}` | Update student profile (OCC-guarded); a `declared_major` change re-derives natural slots on future waterfalls only | RegistrarAdmin |
| GET | `/api/students/{id}/degree-progress` | Computed degree-audit read: per-slot coverage, totals, residency constant, transfer GPA; variant selector | Any |
| POST | `/api/transcripts` | Intake an external transcript with embedded course list | TransferCenterStaff |
| GET | `/api/transcripts` | List transcripts (paginated) | Any |
| GET | `/api/transcripts/{id}` | Get one transcript | Any |
| POST | `/api/transcripts/{id}/verify` | Verify a received transcript | TransferCenterStaff |
| POST | `/api/transcripts/{id}/reject` | Reject a transcript | TransferCenterStaff |
| POST | `/api/transfer-credit-evaluations` | Create an evaluation from a verified transcript; auto-creates line items with grade conversion and auto-match | TransferEvaluator |
| GET | `/api/transfer-credit-evaluations` | List evaluations (paginated) | Any |
| GET | `/api/transfer-credit-evaluations/{id}` | Get one evaluation | Any |
| GET | `/api/transfer-credit-evaluations/{id}/line-items` | List line items of an evaluation | Any |
| POST | `/api/transfer-credit-evaluations/{id}/start-review` | Move an evaluation from DRAFT to IN_REVIEW | TransferEvaluator |
| POST | `/api/transfer-credit-evaluations/{id}/finalize` | Finalize an in-review evaluation; recomputes final awarded credits | TransferEvaluator |
| POST | `/api/transfer-credit-evaluations/{id}/post` | Post an evaluated evaluation; runs the waterfall; maker-checker applies | TransferEvaluator |
| POST | `/api/transfer-credit-evaluations/{id}/reopen` | Reopen a posted evaluation with full compensation | TransferEvaluator |
| GET | `/api/evaluation-line-items` | Filtered list of line items | Any |
| GET | `/api/evaluation-line-items/{id}` | Get one line item | Any |
| POST | `/api/evaluation-line-items/{id}/adopt` | Adopt a line: confirm an auto-match or manually override a petition-required line | TransferEvaluator |
| POST | `/api/evaluation-line-items/{id}/deny` | Deny a line with a reason | TransferEvaluator |
| POST | `/api/petitions` | Student files a syllabus-based petition for a line item | Student |
| GET | `/api/petitions` | List petitions (paginated) | Any |
| GET | `/api/petitions/{id}` | Get one petition | Any |
| POST | `/api/petitions/{id}/start-review` | Start petition review; binds the adjudicator | FacultyAdjudicator |
| POST | `/api/petitions/{id}/adjudicate` | Adjudicate a petition; approval cascades to the line item | FacultyAdjudicator |
| POST | `/api/appeals` | Student appeals a denied petition within the appeal window | Student |
| GET | `/api/appeals` | List appeals (paginated) | Any |
| GET | `/api/appeals/{id}` | Get one appeal | Any |
| POST | `/api/appeals/{id}/start-review` | Start appeal review; reviewer must differ from the petition adjudicator | FacultyAdjudicator |
| POST | `/api/appeals/{id}/adjudicate` | Adjudicate an appeal; overturn cascades petition, line, and evaluation | FacultyAdjudicator |
| POST | `/api/prior-learning-assessments` | Student submits a military/prior-learning credit assessment | Student |
| GET | `/api/prior-learning-assessments` | List assessments (paginated) | Any |
| GET | `/api/prior-learning-assessments/{id}` | Get one assessment | Any |
| POST | `/api/prior-learning-assessments/{id}/verify` | Verify the credential; sets verified credits up to the claim | TransferEvaluator |
| POST | `/api/prior-learning-assessments/{id}/credit` | Credit a verified assessment subject to the lifetime PLA cap | TransferEvaluator |
| POST | `/api/prior-learning-assessments/{id}/reject` | Reject an assessment | TransferEvaluator |
| GET | `/api/requirement-applications` | Filtered list of requirement applications | Any |
| GET | `/api/requirement-applications/{id}` | Get one requirement application | Any |
| POST | `/api/transfer-guides` | Create a transfer guide draft for a partner and catalog year | RegistrarAdmin |
| GET | `/api/transfer-guides` | List transfer guides (paginated) | Any |
| GET | `/api/transfer-guides/{id}` | Get one transfer guide (includes the staleness flag) | Any |
| POST | `/api/transfer-guides/{id}/publish` | Publish: pins the selected ACTIVE agreement and its version; supersedes prior guides | RegistrarAdmin |
| POST | `/api/transfer-guides/{id}/archive` | Manually archive a published guide | RegistrarAdmin |
| GET | `/api/transfer-guides/{id}/entries` | Read the published snapshot content (pinned ids plus frozen entries) | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TRANSCRIPT_NOT_VERIFIED` | 409 Conflict |
| `ERR_TRANSCRIPT_STUDENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EVALUATION` | 409 Conflict |
| `ERR_EVALUATION_NOT_IN_REVIEW` | 409 Conflict |
| `ERR_UNRESOLVED_LINE_ITEMS` | 409 Conflict |
| `ERR_POSTER_IS_EVALUATOR` | 403 Forbidden |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_EDITABLE` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EQUIVALENCY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AMENDMENT_EXISTS` | 409 Conflict |
| `ERR_COURSE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_LINE_ITEM_NOT_PETITIONABLE` | 409 Conflict |
| `ERR_PETITION_ALREADY_OPEN` | 409 Conflict |
| `ERR_PETITION_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_APPEAL_NOT_FILEABLE` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_APPEAL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_APPEAL_ADJUDICATOR_CONFLICT` | 403 Forbidden |
| `ERR_VERIFIED_EXCEEDS_CLAIMED` | 422 Unprocessable Entity |
| `ERR_PLA_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_GUIDE_NO_ACTIVE_AGREEMENT` | 409 Conflict |
