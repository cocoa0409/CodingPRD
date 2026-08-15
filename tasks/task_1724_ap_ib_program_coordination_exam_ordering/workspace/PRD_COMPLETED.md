# AP/IB Exam Coordination API — Product Requirements Document

## 1. Introduction

Every spring, a high school's AP/IB coordinator runs a logistical gauntlet: collecting exam registrations against a hard deadline, translating course rosters into a single exam order per administration, securing fee reductions for eligible students, booking rooms and proctors for each sitting, and — after exam day — shepherding scores from release to transcript credit. Each step carries money, deadlines, and compliance consequences. A registration created after the deadline bills the family a late fee; an order submitted late bills the school a late fee on every ordered exam; an exam that was ordered but never used draws a penalty at reconcile time; a course whose last authorized teacher lapses is suspended and its scheduled sittings collapse; an unresolved irregularity report can hold an entire sitting's scores, and a substantiated one can void them.

This document specifies the AP/IB Exam Coordination API, the system of record for that workflow. It governs one exam administration's full lifespan — cycle configuration, teacher training and authorization, student registration and fee-reduction subsidies, the draft-to-reconciled exam order, room and proctor logistics, exam-day attendance and irregularities, score release and transcript posting, and program growth and equity reporting. All time-sensitive behavior is driven by a single logical clock, and the system follows an immediate-consistency model: every mutation is atomic, every derived figure is reconciled as part of the mutation that affects it, and the response to any write reflects the post-mutation state. Four peer roles share the surface — the coordinator runs the program, students register and apply for subsidies, teachers attest their training and file irregularity reports, and the registrar releases scores and posts credit.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. The system recognizes exactly four roles: `ApCoordinator`, `Student`, `Teacher`, and `Registrar`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint, or that violates entity-backed ownership, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ApCoordinator` or `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting Student, and ownership checks on any resource that references a student compare the resource's `student_id` field to `X-User-ID` — this governs creating a registration, cancelling one's own registration, submitting or resubmitting a fee-reduction application, reading one's own statement, and reading filtered lists, where student callers only ever see their own rows. When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting Teacher: training attestation is permitted only on the authorization record whose `teacher_id` equals `X-User-ID`, and an irregularity report may be filed only for a session on which the caller holds an `ASSIGNED` proctor assignment whose `teacher_id` equals `X-User-ID`. These ownership rules are what segregate duties — for example, the coordinator who opens a teacher's authorization record cannot attest the training on that teacher's behalf.

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

List endpoints paginate through query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Filters on list endpoints are exact-match on the named field; a filter value that matches nothing yields an empty page rather than an error, and unrecognized query parameters are ignored.

### 2.4. The Logical Clock

Every deadline comparison, exam-window containment check, authorization expiry, attendance cutoff, and score-release gate in the system reads a single server-side **logical clock** — never the wall clock. Before any client advances it, the logical clock reads exactly `2026-08-01T00:00:00Z`. An `ApCoordinator` advances the logical clock through a test-driving capability that accepts a target instant `to_iso8601`; the response reports the clock's new reading as `current_utc`. The clock accepts any target instant — setting it to an earlier reading is not rejected, and doing so never revives an already-`EXPIRED` authorization. Every clock advance runs the teacher-authorization expiry sweep described in §3.2 before the response is returned, so cascading expirations are already visible by the time the caller sees the new time. Datetime inputs anywhere in the API are accepted in any ISO 8601 form (offsets permitted), normalized to UTC, and stored and compared at one-second precision; responses echo such domain datetimes (deadlines, window bounds, `submitted_at`, session `start_at`/`end_at`, and the like) in `YYYY-MM-DDTHH:MM:SSZ` form.

### 2.5. Common Resource Properties

Every resource in this API — exam cycles, courses, teachers, teacher authorizations, students, fee-reduction applications, registrations, exam orders, exam sessions, proctor assignments, and irregularity reports — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every mutation of the resource.

`created_at` and `updated_at` are wall-clock timestamps; the logical clock of §2.4 governs only the time-sensitive domain rules, never these bookkeeping fields. "Mutation" is read broadly over stored fields: a state transition, a client edit, and a cascade effect that rewrites another resource's stored fields (for example, an assignment released by a session cancellation, or a score record held by an irregularity filing) each count, and each updates `updated_at` and increments `version` on every resource whose stored fields it changes. The derived figures of §2.9 are computed at read time, so a change in a derived figure — a count, balance, fee, rebate, seat tally, or a draft order's live lines and estimate — does not by itself mutate the resource that exposes it or bump its `version`. A read-only fetch never mutates.

### 2.6. Money, Integer Cents, and Pinned Rounding

All monetary values — fees, subsidies, penalties, invoices, balances, rebates, budget caps, and reported income — are represented as integer cents. Fee, invoice, subsidy, and balance arithmetic is exact integer arithmetic with no rounding at any step. Two calculations deviate from pure integer math and follow pinned rounding discipline:

- The **school rebate** is computed per registration first and summed second. Each registration's rebate line is the registration's net fee multiplied by the cycle's rebate rate and rounded half-up to integer cents; the cycle's rebate is the sum of those per-line amounts. Summing net fees first and rounding once is a rejected alternative that yields different cents — for example, three net fees of 1050 cents at a 9% rate produce per-line rebates of 95 cents each (285 total), whereas sum-then-round would produce 284.
- **Equity percentages** (participation rates and the access gap) are rounded half-up to one decimal place.

Monetary inputs are validated as non-negative where the domain requires it: the cycle's `late_fee_cents`, `unused_exam_penalty_cents`, `fee_reduction_cents`, and `budget_cap_cents` each must be greater than or equal to zero, and an application's `annual_income_cents` must be greater than or equal to zero. A course's `exam_fee_cents` must be strictly positive, and a session's `room_capacity` must be strictly positive.

### 2.7. Optimistic Concurrency Control on the Exam Order

Exactly one write in the API is guarded by optimistic concurrency control: editing a draft exam order's adjustments. Such an edit request must carry `expected_exam_order_version`, a non-optional field holding the `version` of the exam order the client last observed. If the presented value does not match the order's current `version` — because another adjustment edit or a lifecycle action has advanced the order since the client's view was taken — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the order and re-apply its adjustments against the fresh version. The version check is applied before the draft-state gate, so an edit carrying a stale version against an order that has since left `DRAFT` is rejected with `ERR_STALE_VERSION`, not `ERR_INVALID_STATE`. No other endpoint accepts a version field; all other writes apply without an OCC check.

### 2.8. Validation Cascade and Error Priority

Every request is validated against a fixed, ordered cascade. Earlier failures mask later ones: a request that fails an earlier check is rejected with that check's error and never evaluated against later checks. The order is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the four recognized roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization and ownership.** The role appears in the endpoint's authorized list; otherwise `ERR_FORBIDDEN` (HTTP 403). Entity-backed ownership rules (§2.1) are enforced at the first point where the entity they compare against is available: on creation payloads carrying a `student_id`, against the raw `student_id` field before the shape checks of step 4; on path-identified resources, immediately after the resource resolves in step 3; and for irregularity filings — where ownership runs through the session's proctor assignments — immediately after the `session_id` reference resolves in step 5.
3. **Path resolution.** Path identifiers resolve to existing resources, validated left to right; the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). Requests to undefined paths, and requests using an unsupported method on a defined path, likewise yield `ERR_NOT_FOUND` (HTTP 404). On the action endpoints that accept no payload fields (cycle open, application approve/deny/resubmit, registration cancel and post-to-transcript, order submit/lock/reconcile, session cancel, proctor release, report resolve and cancel-scores, complete-training), the empty-body check of step 4 is applied before path resolution, so an unexpected body field there surfaces as `ERR_INVALID_REQUEST` even when the path identifier does not resolve; the payload-bearing endpoints with path identifiers (`PATCH /exam-orders/{id}`, administer, score release) resolve the path first.
4. **Request shape.** Required fields are present (required strings must be non-blank — a whitespace-only string is rejected), types are correct, enum values are in range, `end_at` is strictly after `start_at`, `grade_level` is within 9 through 12, and any supplied score is within its program range (1–5 for AP, 1–7 for IB — a check that, for score release, runs immediately after the references of step 5 resolve, since the range depends on the registration's course); unknown or unexpected fields in a payload are rejected. An optional field explicitly set to null is treated as omitted. Violations yield `ERR_INVALID_REQUEST` (HTTP 400).
5. **Body references.** Foreign keys carried in the request body — `cycle_id`, `course_id`, `student_id`, `teacher_id`, `session_id`, and the registration identifiers inside `scores` or `present_registration_ids` — resolve to existing resources; otherwise `ERR_REFERENCE_NOT_FOUND` (HTTP 422).
6. **State gates.** The target entity is in a valid from-state for the requested transition: registrations cancel only from `REGISTERED`, the draft order accepts adjustment edits and submission only from `DRAFT`, sessions administer only from `SCHEDULED`, irregularity reports resolve or cancel scores only from `FILED`, and so on. Creation of registrations, exam orders, and exam sessions additionally requires the cycle to be `OPEN`, and session creation requires the course to be `ACTIVE` with at least one authorized teacher. This step also performs the OCC check of §2.7. Violations surface as `ERR_INVALID_STATE` (HTTP 409), `ERR_TEACHER_NOT_AUTHORIZED` (HTTP 422), or `ERR_STALE_VERSION` (HTTP 412) according to the gate that failed.
7. **Safety gates.** A proctor may not hold an `AUTHORIZED` teacher authorization for the session's course (`ERR_PROCTOR_SUBJECT_CONFLICT`, HTTP 422), and a session's room must support accommodations when any `REGISTERED` registration of the course has an accommodation need (`ERR_ROOM_NOT_ACCOMMODATION_CAPABLE`, HTTP 422).
8. **Temporal gates.** Session windows must lie inside the cycle's exam window (`ERR_OUTSIDE_EXAM_WINDOW`, HTTP 422); a room may not be double-booked (`ERR_ROOM_CONFLICT`, HTTP 409); a proctor's assignments must respect the travel buffer (`ERR_PROCTOR_OVERLAP`, HTTP 409); attendance may be recorded only once the session has ended (`ERR_SESSION_NOT_ENDED`, HTTP 422); and scores may be released only once the release instant has arrived (`ERR_SCORES_NOT_YET_AVAILABLE`, HTTP 422).
9. **Uniqueness and quota gates.** One exam order per cycle (`ERR_ORDER_ALREADY_EXISTS`, HTTP 409); one authorization record per teacher-and-course pair (`ERR_DUPLICATE_AUTHORIZATION`, HTTP 409); one fee-reduction application per student-and-cycle pair (`ERR_DUPLICATE_APPLICATION`, HTTP 409); one non-cancelled registration per student-and-course pair (`ERR_DUPLICATE_REGISTRATION`, HTTP 409); one `ASSIGNED` proctor row per session-and-teacher pair (`ERR_DUPLICATE_PROCTOR`, HTTP 409); one non-cancelled session per course (`ERR_DUPLICATE_SESSION`, HTTP 409); adjustment deltas may not drive an ordered count below zero (`ERR_NEGATIVE_QUANTITY`, HTTP 422); a registration must fit the scheduled session's remaining capacity (`ERR_SESSION_FULL`, HTTP 422); a session's room capacity must cover the course's registered count (`ERR_ROOM_CAPACITY_INSUFFICIENT`, HTTP 422); and a posted score must meet the course's credit threshold (`ERR_SCORE_BELOW_THRESHOLD`, HTTP 422).
10. **Fiscal gate.** Order submission requires the estimate to fit within the cycle's budget cap (`ERR_BUDGET_EXCEEDED`, HTTP 422).
11. **Score-release record gate.** When releasing scores, every listed record must currently be `PENDING`: a `HELD` record rejects the whole request with `ERR_IRREGULARITY_OPEN` (HTTP 409), and a record in any other non-`PENDING` state rejects the whole request with `ERR_INVALID_STATE` (HTTP 409). The release is transactional — on rejection nothing is written.

### 2.9. Derived Fields and Cascade Reconciliation

The system maintains a family of derived figures that are never set directly by clients and are instead reconciled as part of every mutation that affects them: a cycle's `registered_exam_count` and `rebate_cents`; a course's `authorized_teacher_count` and `registered_count`; a student's `balance_cents`, `projected_balance_cents`, and `transcript_posted_count`; a registration's `is_late` and `net_fee_cents`; a session's `seats_reserved`; and an order's `lines`, `estimate_total_cents`, and `final_total_cents`. Because consistency is immediate, the response to any write already reflects every downstream recompute that write triggered — including multi-hop cascades, where one event (for example, a teacher authorization expiring) can reconcile a course, then its sessions, then those sessions' proctor assignments. Each resource whose stored fields a cascade rewrites (in the example: the expiring authorization, the cancelled sessions, the released assignments) is itself mutated, with `updated_at` refreshed and `version` incremented per §2.5; a resource that merely exposes a recomputed derived figure (in the example: the course's `status` and `authorized_teacher_count`) is not itself version-bumped.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Exam Cycle

An `ApCoordinator` begins an administration year by creating an **exam cycle**, supplying a human label `name` (for example, "2027 Spring AP/IB"), three deadline instants, the exam window, and the fee constants that will govern the whole cycle. The `registration_deadline_at` instant separates on-time from late registrations: a registration whose creation time is strictly after this instant is late, while one created exactly at the instant is on time. The `order_deadline_at` instant works the same way for the school's exam order — submission strictly after it is late. The `score_release_at` instant is the earliest moment scores may be released. The `exam_window_start_at` and `exam_window_end_at` instants bound every session: a sitting must start at or after the window start and end at or before the window end.

Five fee constants ride on the cycle. The `late_fee_cents` is a per-exam late fee applied in two distinct places: on a student's bill when their registration is late, and on the school's invoice for every ordered exam when the order itself is submitted late. The `unused_exam_penalty_cents` is the per-exam penalty assessed at reconcile time for exams that were ordered but never used. The `fee_reduction_cents` is the per-exam subsidy granted to students holding an approved fee-reduction application. The `budget_cap_cents` is the school's exam budget, enforced when the order is submitted. The `rebate_rate_bp` is the school's rebate rate expressed in basis points — 900 means 9% — and must lie between 0 and 10000 inclusive.

A new cycle starts in `SETUP` status with `registered_exam_count` at 0 and `rebate_cents` at 0. While a cycle is in `SETUP`, no registrations, exam orders, or exam sessions may be created for it; the coordinator opens the cycle, transitioning its `status` from `SETUP` to `OPEN`, which makes all three kinds of creation available. A cycle has no terminal state — it remains `OPEN` for the rest of the administration. Attempts to create registrations, orders, or sessions against a cycle that is not `OPEN` are rejected with `ERR_INVALID_STATE`.

### 3.2. Courses and the Teacher Authorization Loop

Within a cycle, the coordinator registers each **course** by supplying the owning `cycle_id`, a `subject_code` such as AP_CALC_BC or IB_HIST_HL, the `program` (exactly one of `AP` or `IB`), the per-exam `exam_fee_cents`, and the `credit_threshold` — the minimum score that earns transcript credit, which must lie in the range 1 through 5 for an AP course and 1 through 7 for an IB course. A course's `status` is never set directly. It is derived from staffing: a course is `ACTIVE` when its `authorized_teacher_count` — the number of authorization records for the course currently in `AUTHORIZED` status — is at least 1, and `SUSPENDED` otherwise. A freshly created course therefore starts `SUSPENDED` with an `authorized_teacher_count` of 0 and a `registered_count` of 0. The course listing accepts `cycle_id`, `subject_code`, `program`, and `status` filters, and fetching a single course returns the computed `authorized_teacher_count` and `registered_count` alongside its configured fields.

Teachers themselves are simple registry entries created with a `full_name` and an `email`. What ties a teacher to a course is a **teacher authorization** record, opened by the coordinator with a `teacher_id` and a `course_id`. At most one authorization row ever exists for a given teacher-and-course pair — even an expired row counts — so a duplicate open attempt is rejected with `ERR_DUPLICATE_AUTHORIZATION`; retraining always happens on the existing row. The record starts in `PENDING_TRAINING` status, with `training_completed_at` and `authorized_until` both null.

Training is attested by the teacher on the record, and only by that teacher: the caller's identity must match the record's `teacher_id`, otherwise the attestation is rejected with `ERR_FORBIDDEN`. A successful attestation moves the record from `PENDING_TRAINING` to `AUTHORIZED`, stamps `training_completed_at` with the current logical-clock reading, and sets `authorized_until` to exactly 730 days after `training_completed_at`. The course's `authorized_teacher_count` increases by 1, and when that takes the count from 0 to 1 the course flips from `SUSPENDED` to `ACTIVE`, making it eligible for session scheduling and satisfying the order-lock staffing gate. The authorization records listing supports `teacher_id`, `course_id`, and `status` filters.

Authorization is not permanent. Every advance of the logical clock runs an expiry sweep: every authorization record still in `AUTHORIZED` status whose `authorized_until` is at or before the new clock reading transitions to `EXPIRED` — the boundary is inclusive, so an authorization whose `authorized_until` equals the new time exactly counts as expired. Each expiry decrements the course's `authorized_teacher_count`, and when that takes the count from 1 to 0 the course flips from `ACTIVE` back to `SUSPENDED`. That suspension cascades: every session of the course still in `SCHEDULED` status is cancelled, each cancelled session's `ASSIGNED` proctor assignments are released, and the students' registrations are deliberately left untouched — students remain registered even though their sitting is gone. An `EXPIRED` authorization is not a dead end: the teacher may attest retraining on the same record, moving it from `EXPIRED` back to `AUTHORIZED` with a fresh `training_completed_at`, a fresh 730-day validity horizon, and the same course-reactivation effect as a first-time attestation.

### 3.3. Students, Fee Reduction, and Exam Registration

The coordinator enrolls each **student** with a `full_name`, a `grade_level` between 9 and 12 inclusive, and a `subgroup_code` placing the student in exactly one equity reporting subgroup: `GEN`, `FRL`, `IEP`, or `ELL`. A new student's `balance_cents`, `projected_balance_cents`, and `transcript_posted_count` all start at 0; each is a computed figure reconciled by later events.

A student who qualifies for assistance files a **fee-reduction application**, a payload carrying the `student_id`, the `cycle_id`, an `eligibility_basis` of `FREE_LUNCH`, `REDUCED_LUNCH`, `INCOME`, or `OTHER`, and the household's `annual_income_cents`. Because the applicant role is `Student`, the `student_id` must be the caller's own id, otherwise the filing is rejected with `ERR_FORBIDDEN`. At most one application row ever exists for a student-and-cycle pair; a second filing for the same pair is rejected with `ERR_DUPLICATE_APPLICATION`. The application starts in `SUBMITTED` status, and from the moment it exists the student's `projected_balance_cents` treats it as potentially approved. The coordinator then decides: approval moves the application to `APPROVED`, denial moves it to `DENIED`. Denial changes nothing financially — the subsidy stays at zero — but it is not final: the owning student may resubmit the same row, moving it from `DENIED` back to `SUBMITTED`, at which point the projected balance once again counts the subsidy as potentially approved. Approval, by contrast, has real financial weight and is described with the fee math below. The applications listing accepts `student_id`, `cycle_id`, and `status` filters; student callers only ever see their own applications.

The central act of the cycle is **exam registration**: a student registers for one course's exam with a payload containing their own `student_id`, the `course_id`, and optionally an `accommodation_type` of `NONE`, `EXTENDED_TIME`, or `SEPARATE_ROOM` (omitting it defaults to `NONE`). Registration requires the course's cycle to be `OPEN`, and at most one non-cancelled registration may exist for a student-and-course pair — a duplicate attempt is rejected with `ERR_DUPLICATE_REGISTRATION`, while a previously cancelled registration does not block re-registering. The new registration's `cycle_id` is copied from the course's cycle, its `registration_status` starts at `REGISTERED`, and a parallel score record opens with `score_status` at `PENDING` and a null `score`. These two state dimensions evolve independently from here on: attendance moves `registration_status`, while score processing moves `score_status`, and each dimension gates the other only where stated.

Every registration carries its own fee snapshot, computed at creation. The `fee_cents` field snapshots the course's `exam_fee_cents` at that moment, so later course edits never reprice existing registrations. The `is_late` flag is true when the registration's creation time on the logical clock is strictly after the cycle's `registration_deadline_at`. When `is_late` is true, `late_fee_applied_cents` equals the cycle's `late_fee_cents`; otherwise it is 0. The `subsidy_cents` field is the smaller of the cycle's `fee_reduction_cents` and the sum of `fee_cents` plus `late_fee_applied_cents` when the student holds an `APPROVED` fee-reduction application for the cycle, and 0 otherwise — applications still `SUBMITTED` or already `DENIED` contribute nothing to the subsidy. The `net_fee_cents` is then `fee_cents` plus `late_fee_applied_cents` minus `subsidy_cents`, which is always at least 0 because the subsidy is capped by the fee-plus-late total.

Two balance figures track what a student owes. The `balance_cents` is the provisional, bill-now figure: the sum of `net_fee_cents` over the student's registrations whose `registration_status` is `REGISTERED`, `SAT`, or `NO_SHOW` — cancelled registrations are excluded — with subsidies counted only from `APPROVED` applications. The `projected_balance_cents` answers the question "what would the student owe if the pending application is approved?": it is the same sum, except that an application in `SUBMITTED` status is treated as if approved, so its full subsidy counts. Whenever an undecided application exists, the two figures diverge; once every application is decided, they coincide. A student's statement — readable by the coordinator, the registrar, and the student themselves — reports the `student_id`, `balance_cents`, `projected_balance_cents`, and `transcript_posted_count`.

Approval of a fee-reduction application ripples through this fee structure. The `subsidy_cents` of each of the student's non-cancelled registrations in the cycle is recomputed — registrations created at full price gain their subsidy retroactively — and each recomputed registration in turn triggers reconciliation of the student's `balance_cents` and `projected_balance_cents` and of the cycle's `rebate_cents`. If a draft exam order exists for the cycle, its estimate is recomputed as well, since the subsidy component of the invoice has changed.

The school's rebate accrues per registration. The cycle's `rebate_cents` is the sum, over every registration in the cycle whose `registration_status` is not `CANCELLED`, of that registration's rebate line — and each line is the registration's `net_fee_cents` multiplied by the cycle's `rebate_rate_bp`, divided by 10000, and rounded half-up to integer cents before any summing happens, following the pinned rounding order of §2.6. Anything that changes a registration's `net_fee_cents` — creation, cancellation, or an application decision — recomputes the rebate.

Registration also updates the counts the rest of the system watches. The cycle's `registered_exam_count` and the course's `registered_count` each count non-cancelled registrations, so creation increments both. If a session for the course is already in `SCHEDULED` status, the session's `seats_reserved` recomputes to the course's current `REGISTERED` count — and if the new registration would push that required seat count beyond the session's `room_capacity`, the registration is rejected outright with `ERR_SESSION_FULL`. If a draft exam order exists for the cycle, its estimate recomputes against the new registration.

Cancellation unwinds all of this. Either the owning student or the coordinator may cancel a registration, but only while its `registration_status` is `REGISTERED`; cancellation moves it to `CANCELLED`, a terminal state, and moves the parallel `score_status` to `VOID`. The student's balances recompute, the cycle's `rebate_cents` recomputes, the cycle's `registered_exam_count` and the course's `registered_count` each decrease by 1, a `SCHEDULED` session for the course recomputes its `seats_reserved` down by 1, and a draft order's estimate recomputes. The registrations listing accepts `student_id`, `course_id`, `cycle_id`, `registration_status`, and `score_status` filters; student callers see only their own registrations, and fetching a single registration returns both state dimensions together with the fee fields.

### 3.4. Building, Submitting, and Reconciling the Exam Order

Once registrations are accumulating, the coordinator creates the cycle's **exam order** — the school's single order to the program for the whole administration — with a payload carrying the `cycle_id`. At most one order exists per cycle; a second create attempt is rejected with `ERR_ORDER_ALREADY_EXISTS`, and creation requires the cycle to be `OPEN`. The order starts in `DRAFT` status, and while it remains a draft it is a living document: its `lines` — one per course in the cycle, ordered by course creation ascending, each reporting the `course_id`, the `ordered_count`, the per-exam `fee_cents`, the `late_fee_total_cents`, and the `line_total_cents` — and its `estimate_total_cents` are computed live and recomputed on every registration creation or cancellation, every fee-reduction approval, and every adjustment edit.

The estimate is a forward-looking invoice projection. Each course's `ordered_count` is the count of the course's registrations whose `registration_status` is not `CANCELLED`, plus the course's adjustment delta (zero when no adjustment exists). The invoice estimate is the sum over courses of each `ordered_count` multiplied by the course's `exam_fee_cents`, plus a late component — when the current logical-clock reading is strictly after the cycle's `order_deadline_at`, the late component is the total ordered count across all courses multiplied by the cycle's `late_fee_cents`, and otherwise it is 0 — minus a subsidy component equal to the sum of `subsidy_cents` over every non-cancelled registration in the cycle at evaluation time. No unused-exam penalty appears in the estimate; it is purely a reconcile-time figure.

Manual corrections flow through the order's `adjustments`, an array of per-course entries each pairing a `course_id` with a `delta`. Adjustments are editable only while the order is in `DRAFT` status; an edit against a submitted, locked, or reconciled order is rejected with `ERR_INVALID_STATE`. Every edit is the OCC-guarded write of §2.7: the request must carry `expected_exam_order_version` matching the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The `adjustments` field itself is optional in an edit: omitting it (or passing null) leaves the prior adjustments untouched, though the edit still increments the order's `version`. Within one edit a `course_id` may appear at most once — duplicate entries are rejected with `ERR_INVALID_REQUEST` — and every referenced course must resolve (`ERR_REFERENCE_NOT_FOUND`) and belong to the order's own cycle, a cross-cycle course being rejected with `ERR_INVALID_REQUEST`. A successful edit replaces the prior adjustments array wholesale — it is not a merge — and any entry whose `delta` would drive its course's `ordered_count` below zero is rejected with `ERR_NEGATIVE_QUANTITY`. Each applied edit increments the order's `version` by 1 and recomputes the estimate. The orders listing accepts `cycle_id` and `status` filters, and fetching an order returns its `version` alongside its lines and totals.

Submission crystallizes the draft. The coordinator submits the order, transitioning it from `DRAFT` to `SUBMITTED`, which requires the cycle to still be `OPEN` and requires the `estimate_total_cents` to be less than or equal to the cycle's `budget_cap_cents` — an estimate that exceeds the cap is rejected with `ERR_BUDGET_EXCEEDED`. Submission freezes the `lines` as a snapshot of each course's `ordered_count` at that instant, freezes the `estimate_total_cents`, stamps `submitted_at` with the logical clock, and resolves `submitted_late`: true when `submitted_at` is strictly after the cycle's `order_deadline_at`, false when it is at or before it. Until submission, `submitted_at` and `submitted_late` are null. When `submitted_late` is true, every ordered exam is billed the cycle's `late_fee_cents`, folded into the frozen lines' `late_fee_total_cents`. Before their respective transitions, `locked_at` and `reconciled_at` are likewise null.

Locking is the coordinator's staffing attestation. A submitted order transitions from `SUBMITTED` to `LOCKED` only when every course appearing in the frozen lines with an `ordered_count` greater than 0 has an `authorized_teacher_count` of at least 1; otherwise the lock is rejected with `ERR_TEACHER_NOT_AUTHORIZED`. Locking stamps `locked_at`, and from that point no further quantity changes are possible.

Reconciliation closes the books. A locked order transitions from `LOCKED` to `RECONCILED` — the order's terminal state — only when every registration in the cycle is resolved, meaning each has a `registration_status` of `SAT`, `NO_SHOW`, or `CANCELLED`; an unresolved registration rejects the reconcile with `ERR_INVALID_STATE`. Reconcile computes the `final_total_cents`, null until this moment, as a chronological replay of actual outcomes against the frozen lines: the sum over courses of each frozen `ordered_count` multiplied by the course's `exam_fee_cents`, plus the late component (the total frozen ordered count multiplied by `late_fee_cents` when `submitted_late` is true, otherwise 0), plus the unused-exam component — each course's unused count is the larger of zero and its frozen `ordered_count` minus its count of registrations with `registration_status` equal to `SAT`, and the component is the sum over courses of that unused count multiplied by the cycle's `unused_exam_penalty_cents` — minus the subsidy component evaluated at reconcile time over non-cancelled registrations. Because ordered counts are the submit-time snapshot, cancellations after submission surface as unused exams, and the same underlying data yields an estimate and a final that differ whenever no-shows or post-submit cancellations exist. Reconciliation stamps `reconciled_at`.

### 3.5. Scheduling Rooms and Proctors

Each course's exam is administered in one scheduled sitting. The coordinator schedules an **exam session** with a payload carrying the `course_id`, the `room_name`, the `room_capacity`, the `start_at` and `end_at` instants, and optionally `room_supports_accommodations`, which defaults to false. Scheduling enforces a battery of gates. The course must be `ACTIVE` — a course with no authorized teacher cannot be scheduled, and the attempt is rejected with `ERR_TEACHER_NOT_AUTHORIZED`. At most one non-cancelled session exists per course, so scheduling a second sitting while one is still live is rejected with `ERR_DUPLICATE_SESSION`. The `end_at` must be strictly after `start_at`, on pain of `ERR_INVALID_REQUEST`, and the sitting must lie entirely within the course's cycle exam window — starting at or after `exam_window_start_at` and ending at or before `exam_window_end_at` — otherwise `ERR_OUTSIDE_EXAM_WINDOW`. The `room_capacity` must cover the course's current count of `REGISTERED` registrations; equality is allowed, but a capacity even one seat short is rejected with `ERR_ROOM_CAPACITY_INSUFFICIENT`. When any `REGISTERED` registration of the course carries an `accommodation_type` other than `NONE`, the room must be accommodation-capable — scheduling with `room_supports_accommodations` false is rejected with `ERR_ROOM_NOT_ACCOMMODATION_CAPABLE`. Finally, rooms cannot be double-booked: if another non-cancelled session with the same `room_name` string overlaps the new sitting's time interval, the request is rejected with `ERR_ROOM_CONFLICT`. Overlap is evaluated as a half-open interval — the new sitting's start through, but not including, its end — so two sittings where one ends exactly when the other begins are adjacent, not conflicting. A created session starts in `SCHEDULED` status, with `seats_reserved` equal to the course's count of `REGISTERED` registrations; that figure keeps tracking the course's registered headcount on every registration creation and cancellation while the session remains scheduled. The sessions listing accepts `course_id` and `status` filters.

Staffing the sitting is a separate act: the coordinator creates a **proctor assignment** pairing a `session_id` with a `teacher_id`. The session must still be in `SCHEDULED` status, and the pairing is unique — a teacher who already holds an `ASSIGNED` assignment on that session cannot be assigned again (`ERR_DUPLICATE_PROCTOR`). Two conflict-of-interest and fatigue rules guard the assignment. A teacher who holds an `AUTHORIZED` authorization for the session's own course may not proctor it; the attempt is rejected with `ERR_PROCTOR_SUBJECT_CONFLICT`. And a teacher may not hold two `ASSIGNED` assignments whose session windows are separated by less than 30 minutes — the buffer gives proctors travel and reset time, so a gap of 30 minutes or more between one session's end and the next session's start is allowed, while anything tighter is rejected with `ERR_PROCTOR_OVERLAP`. A created assignment starts in `ASSIGNED` status; releasing it moves it to `RELEASED`, its terminal state, making the teacher available for other sessions whose windows had been buffer-blocked by this one. Session cancellation releases its assignments automatically, per the cascade in §3.6. The assignments listing accepts `session_id`, `teacher_id`, and `status` filters.

### 3.6. Exam Day: Attendance, Cancellation, and Irregularities

After a sitting ends, the coordinator records attendance. Administering a session requires the logical clock to be at or after the session's `end_at` — administering earlier is rejected with `ERR_SESSION_NOT_ENDED` — and requires the session to be in `SCHEDULED` status. The request carries `present_registration_ids`, the list of registrations that actually sat. Every identifier in the list must resolve to an existing registration (`ERR_REFERENCE_NOT_FOUND` otherwise) and must belong to this session's course with a `registration_status` of `REGISTERED` (`ERR_INVALID_STATE` otherwise). Administration then splits the course's roster in two: each listed registration moves from `REGISTERED` to `SAT` with its `score_status` staying `PENDING`, while every `REGISTERED` registration of the course not in the list moves to `NO_SHOW` and its `score_status` moves to `NO_SCORE`. The session itself transitions from `SCHEDULED` to `ADMINISTERED`, and its `seats_reserved` recomputes to 0, since no `REGISTERED` registrations remain for the course. Both `SAT` and `NO_SHOW` are terminal for the registration-status dimension.

A sitting can also be called off. Cancelling a session moves it from `SCHEDULED` to `CANCELLED`, a terminal state; every `ASSIGNED` proctor assignment on the session is released, `seats_reserved` drops to 0, and — importantly — the registrations themselves are not cancelled: students remain registered for the course's exam. The same cancellation cascade fires automatically when a course is suspended by the teacher-authorization expiry sweep of §3.2, with no client call involved.

Exam-day problems are reported through **irregularity reports**. The filing is done by a teacher, and only by a teacher who holds an `ASSIGNED` proctor assignment on the session being reported — anyone else is rejected with `ERR_FORBIDDEN`. The session must be `ADMINISTERED` or already `UNDER_INVESTIGATION`; filing against a session in any other status is rejected with `ERR_INVALID_STATE`. The report carries a `category` — one of `SECURITY_BREACH`, `TIMING_ERROR`, `ACCOMMODATION_VIOLATION`, `MISCONDUCT`, or `MATERIALS` — and free-text `details` (a required string, which may be empty), starts in `FILED` status, and records the filing teacher as its `proctor_teacher_id` taken from the caller's identity. A session may accumulate multiple reports. The first report on an administered session moves it from `ADMINISTERED` to `UNDER_INVESTIGATION` (filing against an already-investigated session leaves the status as is), and every registration of the course whose `registration_status` is `SAT` and whose `score_status` is `PENDING` has its score record moved to `HELD`, blocking score release for those records while the investigation is open. The reports listing accepts `session_id`, `status`, and `proctor_teacher_id` filters.

The coordinator disposes of each filed report in one of two ways, and the two paths diverge sharply. Resolving a report — the finding that scores are unaffected — moves it from `FILED` to `RESOLVED`, a terminal state. When the resolved report was the session's last remaining `FILED` report, the session moves back from `UNDER_INVESTIGATION` to `ADMINISTERED` and the course's `HELD` score records return to `PENDING`, unblocking release; while other `FILED` reports remain on the session, nothing else changes. Cancelling scores is the severe path: the report moves from `FILED` to `SCORES_CANCELLED`, its terminal state, the session — whether `ADMINISTERED` or `UNDER_INVESTIGATION` — moves to `INVALIDATED`, its terminal state, and every `SAT` registration of the course whose `score_status` is `PENDING` or `HELD` moves to `VOID`, meaning those records can never be released or posted. Other `FILED` reports on the session stay `FILED` and may still be resolved individually, with no further effect on the invalidated session.

### 3.7. Score Release and Transcript Credit

Scores arrive in bulk, and release is the registrar's job. The registrar releases scores for a cycle by supplying a `scores` payload listing, for each record being released, the registration and its program-reported score. Several gates guard the release, evaluated in this order: each `scores` entry must be well-formed — a `registration_id` string, an integer `score`, and no other fields — otherwise `ERR_INVALID_REQUEST`; every listed `registration_id` must resolve, otherwise `ERR_REFERENCE_NOT_FOUND`; each supplied score must lie within the registration's course's program range — 1 through 5 for AP, 1 through 7 for IB — otherwise `ERR_INVALID_REQUEST`; and the logical clock must be at or after the addressed cycle's `score_release_at`, otherwise the release is rejected with `ERR_SCORES_NOT_YET_AVAILABLE`. The listed registrations are looked up in the global registry and are not required to belong to the addressed cycle; the timing gate always reads the addressed cycle's `score_release_at`. On top of those, the record gate of §2.8 makes the release transactional: if any listed record's `score_status` is `HELD`, the entire request is rejected with `ERR_IRREGULARITY_OPEN`; if any listed record is in any other non-`PENDING` state — already `RELEASED`, already `POSTED`, `NO_SCORE`, or `VOID` — the entire request is rejected with `ERR_INVALID_STATE`; and on any such rejection nothing at all is written. Any record still in `PENDING` may be released — ordinarily one whose registration sat the exam, but also a `REGISTERED` registration's record if its sitting has not yet been administered, since such records too carry `PENDING`. A successful release moves each listed record from `PENDING` to `RELEASED`, stores the supplied value as the record's `score`, and responds with the `released_count` and the `released_registration_ids`.

Posting is the final step, again the registrar's. Posting a released score to the student's transcript moves the record's `score_status` from `RELEASED` to `POSTED`, its terminal state, and increments the student's `transcript_posted_count` by 1. The gate is the course's credit threshold: the `score` must be greater than or equal to the course's `credit_threshold` — equality posts — otherwise the post is rejected with `ERR_SCORE_BELOW_THRESHOLD`.

### 3.8. Equity and Growth Reporting

The coordinator closes the loop with the cycle's program growth and equity access report. For each subgroup `GEN`, `FRL`, `IEP`, and `ELL` that has at least one student, the report counts the students in the subgroup, counts the distinct students of the subgroup holding at least one registration in this cycle whose `registration_status` is not `CANCELLED`, and computes the subgroup's participation rate as 100 times the participant count divided by the student count, rounded half-up to one decimal place. The report's `total_exams` counts every registration in the cycle whose `registration_status` is not `CANCELLED` — cancelled registrations are excluded from both the participant counts and the exam totals. When the optional `compare_to_cycle_id` parameter is supplied, `growth_exams` is this cycle's `total_exams` minus the comparison cycle's total; otherwise `growth_exams` is null. The `access_gap_pct` is the difference between the highest and lowest subgroup participation rates, rounded half-up to one decimal place. Each `subgroups` entry reports `subgroup_code`, `students`, `participants`, and `participation_rate`, and the entries appear in the fixed order `GEN`, `FRL`, `IEP`, `ELL`. A supplied `compare_to_cycle_id` that does not resolve to an existing cycle is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422). When no students exist at all, `subgroups` is empty and `access_gap_pct` is 0.0. The response carries the `subgroups` array together with `total_exams`, `growth_exams`, and `access_gap_pct`, and is available to the coordinator only.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, attendance recording, score release, adjustment edits, and the clock advance — return `200 OK`. All request and response bodies follow the envelope structure of §2.2, and the narrative of §3 defines the payload contents and side effects of each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the authorization-expiry sweep | ApCoordinator |
| POST | `/exam-cycles` | Create an exam administration cycle with its deadlines and fee constants | ApCoordinator |
| GET | `/exam-cycles/{id}` | Get one cycle including computed registered exam count and rebate | ApCoordinator, Registrar, Teacher, Student |
| POST | `/exam-cycles/{id}/open` | Open the cycle for registrations, orders, and sessions | ApCoordinator |
| GET | `/exam-cycles/{id}/equity-report` | Program growth and equity access report | ApCoordinator |
| POST | `/courses` | Create a course in a cycle | ApCoordinator |
| GET | `/courses` | List courses with optional filters | ApCoordinator, Registrar, Teacher, Student |
| GET | `/courses/{id}` | Get one course including computed staffing and registration counts | ApCoordinator, Registrar, Teacher, Student |
| POST | `/teachers` | Register a teacher | ApCoordinator |
| POST | `/teacher-authorizations` | Open a training/authorization record for a teacher-and-course pair | ApCoordinator |
| GET | `/teacher-authorizations` | List authorization records with optional filters | ApCoordinator, Teacher |
| GET | `/teacher-authorizations/{id}` | Get one authorization record | ApCoordinator, Teacher |
| POST | `/teacher-authorizations/{id}/complete-training` | Attest completed training (initial or retraining) | Teacher |
| POST | `/students` | Register a student | ApCoordinator |
| GET | `/students/{id}/statement` | Student account statement with provisional and projected balances | ApCoordinator, Registrar, Student |
| POST | `/fee-reduction-applications` | Apply for a fee reduction in a cycle | Student |
| GET | `/fee-reduction-applications` | List applications with optional filters (students see only their own) | ApCoordinator, Student |
| GET | `/fee-reduction-applications/{id}` | Get one application (students must own it) | ApCoordinator, Student |
| POST | `/fee-reduction-applications/{id}/approve` | Approve a submitted application | ApCoordinator |
| POST | `/fee-reduction-applications/{id}/deny` | Deny a submitted application | ApCoordinator |
| POST | `/fee-reduction-applications/{id}/resubmit` | Re-open a denied application | Student |
| POST | `/registrations` | Register a student for a course's exam | Student |
| GET | `/registrations` | List registrations with optional filters (students see only their own) | ApCoordinator, Registrar, Teacher, Student |
| GET | `/registrations/{id}` | Get one registration with both state dimensions and fee fields | ApCoordinator, Registrar, Teacher, Student |
| POST | `/registrations/{id}/cancel` | Cancel a registered registration | Student, ApCoordinator |
| POST | `/exam-orders` | Create the cycle's exam order | ApCoordinator |
| GET | `/exam-orders` | List orders with optional filters | ApCoordinator, Registrar |
| GET | `/exam-orders/{id}` | Get one order including version, lines, and totals | ApCoordinator, Registrar |
| PATCH | `/exam-orders/{id}` | Edit a draft order's adjustments (OCC-guarded) | ApCoordinator |
| POST | `/exam-orders/{id}/submit` | Submit a draft order, freezing lines and estimate | ApCoordinator |
| POST | `/exam-orders/{id}/lock` | Lock a submitted order after staffing verification | ApCoordinator |
| POST | `/exam-orders/{id}/reconcile` | Reconcile a locked order, computing the final invoice | ApCoordinator |
| POST | `/exam-sessions` | Schedule a course's exam sitting in a room | ApCoordinator |
| GET | `/exam-sessions` | List sessions with optional filters | ApCoordinator, Registrar, Teacher, Student |
| GET | `/exam-sessions/{id}` | Get one session | ApCoordinator, Registrar, Teacher, Student |
| POST | `/exam-sessions/{id}/administer` | Record attendance after the session ends | ApCoordinator |
| POST | `/exam-sessions/{id}/cancel` | Cancel a scheduled session | ApCoordinator |
| POST | `/proctor-assignments` | Assign a teacher to proctor a session | ApCoordinator |
| GET | `/proctor-assignments` | List proctor assignments with optional filters | ApCoordinator, Teacher |
| GET | `/proctor-assignments/{id}` | Get one proctor assignment | ApCoordinator, Teacher |
| POST | `/proctor-assignments/{id}/release` | Release an assigned proctor | ApCoordinator |
| POST | `/irregularity-reports` | File an exam-day irregularity on an administered session | Teacher |
| GET | `/irregularity-reports` | List irregularity reports with optional filters | ApCoordinator, Teacher, Registrar |
| GET | `/irregularity-reports/{id}` | Get one irregularity report | ApCoordinator, Teacher, Registrar |
| POST | `/irregularity-reports/{id}/resolve` | Resolve a filed report, scores unaffected | ApCoordinator |
| POST | `/irregularity-reports/{id}/cancel-scores` | Cancel scores for a filed report, invalidating the session | ApCoordinator |
| POST | `/exam-cycles/{id}/release-scores` | Bulk score release for the cycle (transactional) | Registrar |
| POST | `/registrations/{id}/post-to-transcript` | Post a released score to the student's transcript | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_IRREGULARITY_OPEN` | 409 |
| `ERR_PROCTOR_SUBJECT_CONFLICT` | 422 |
| `ERR_ROOM_NOT_ACCOMMODATION_CAPABLE` | 422 |
| `ERR_TEACHER_NOT_AUTHORIZED` | 422 |
| `ERR_OUTSIDE_EXAM_WINDOW` | 422 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_PROCTOR_OVERLAP` | 409 |
| `ERR_SESSION_NOT_ENDED` | 422 |
| `ERR_SCORES_NOT_YET_AVAILABLE` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_DUPLICATE_AUTHORIZATION` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_DUPLICATE_PROCTOR` | 409 |
| `ERR_DUPLICATE_SESSION` | 409 |
| `ERR_ORDER_ALREADY_EXISTS` | 409 |
| `ERR_NEGATIVE_QUANTITY` | 422 |
| `ERR_SESSION_FULL` | 422 |
| `ERR_ROOM_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_SCORE_BELOW_THRESHOLD` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
