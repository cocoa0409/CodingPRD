# School Counseling & Master Schedule Building API — Product Requirements Document

## 1. Introduction

Every fall, a high school's counseling office confronts the same combinatorial puzzle: hundreds of students hand in course requests, and the office must turn those requests into a master schedule — deciding how many sections of each course to offer, which teacher and room each section occupies, and which bell period it meets — while keeping class sizes balanced, honoring special-program cohort limits, and protecting graduation progress. This document specifies an API that supports that entire workflow for a single school: collecting and tallying course requests, generating and staffing sections, publishing the master grid with automated student placement, running a structured schedule-change window, detecting credit deficiency and placing students into recovery courses, booking counselor appointments, and rebalancing sections after the term locks.

The API revolves around one governing object, the academic term, whose lifecycle posture gates nearly every operation in the system. Three kinds of users interact with it — district administrators, guidance counselors, and students — under a strict segregation-of-duties model in which the counselor who reviews a schedule change may not be the administrator who decides it. All resources are mounted under the `/scheduling` path prefix, with a single administrative exception described in §2.9.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly three roles, spelled exactly as follows: `Administrator`, `Counselor`, and `Student`. A request with a missing or unrecognized `X-User-Role`, or a missing `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles permitted for the target endpoint (see §4) is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the declared role:

- When `X-User-Role` is `Administrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never derives resource ownership from it; its only inspection point is the segregation-of-duties check on schedule-change decisions (§3.5), where it must differ from the reviewing counselor's id.
- When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting `Counselor`; ownership checks on any resource that references a counselor — an appointment's `counselor_id`, a student's `counselor_id`, a change request's `reviewed_by_counselor_id` — compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a student compare the resource's `student_id` to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Academic Term Posture Pipeline

The academic term is the scheduling office's clock of record, and its `posture` field walks a fixed pipeline: `COLLECTING` → `TALLYING` → `BUILDING` → `PUBLISHED` → `CHANGE_WINDOW` → `LOCKED`, with `LOCKED` terminal. A seventh posture, `REBALANCING`, exists only inside a rebalance run: the term leaves `LOCKED` for the duration of the run and settles back to `LOCKED` when the run completes, so `REBALANCING` is never observable outside the run itself. The derived boolean `change_window_open` is true exactly while the posture is `CHANGE_WINDOW` and false in every other posture.

Every child operation is gated on this posture. Course-request submission requires `COLLECTING`; section scheduling requires `BUILDING`; schedule-change workflows require `CHANGE_WINDOW`; rebalance runs require `LOCKED`. An operation attempted under the wrong posture is rejected with `ERR_INVALID_TERM_POSTURE` (HTTP 409). The term's `periods_per_day` — the number of bell-period slots on the master grid — becomes immutable once the posture leaves `COLLECTING`.

### 2.5. Common Resource Properties

Most resources carry four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource.

Three resources are deliberately slimmer. `TeacherQualification`, `CreditAudit`, and `RebalanceRun` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Credit Values, Precision, and Rounding

All credit amounts are fixed-precision decimal numbers carried to exactly two decimal places, and course credit values are additionally constrained to quarter-credit steps. Graduation-pace constants are exact to one half credit. Final computed amounts — credit deficiencies, recovery priority scores, term imbalance scores — are rounded half-up to two decimal places, while counselor utilization is rounded half-up to four decimal places. Where a calculation prescribes an internal rounding order (§3 spells these out per calculation), that order is part of the contract: rounding earlier than prescribed, or summing fractional values before truncating them, is forbidden because it produces different results.

### 2.7. Optimistic Concurrency Control on the Term

Three write operations are guarded by optimistic concurrency control against the academic term's `version`, and each requires a non-optional `expected_term_version` field in the request carrying the term `version` the client last observed:

- Deciding a schedule-change request (approval or rejection by an administrator);
- Scheduling a draft section by assigning its teacher, room, period, and capacity;
- Launching a rebalance run against a locked term.

On each, if `expected_term_version` does not match the term's current `version` — because the term's version has advanced since the client last read it, invalidating the client's view of window caps, seat tallies, conflict maps, or rebalance epoch — the request is rejected with `ERR_STALE_TERM_VERSION` (HTTP 412). Endpoints not named above do not take a version field; all remaining writes process without an OCC check.

### 2.8. Nested Resource Retrieval and the Validation Pipeline

When an endpoint path contains several resource identifiers, existence is validated strictly left to right — a term before the section, entry, or request nested under it, and so on — and the request fails with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same `ERR_NOT_FOUND` covers body-referenced foreign keys such as `student_id`, `course_id`, `section_id`, `drop_entry_id`, `add_section_id`, and `target_course_id`, which are resolved only after every path identifier has been confirmed.

Beyond existence, all validations run in a fixed pipeline order, and a request failing several checks reports the earliest one. Authentication (`ERR_UNAUTHENTICATED`) precedes role authorization (`ERR_UNAUTHORIZED`), which precedes the existence checks above. Once everything exists, the term-posture gate fires (`ERR_INVALID_TERM_POSTURE`), then from-state legality on the target entity (`ERR_INVALID_STATE`, HTTP 409), then ownership (`ERR_FORBIDDEN_OWNERSHIP`, HTTP 403), then segregation of duties on change-request decisions (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), then the no-show booking freeze (`ERR_NO_SHOW_FREEZE`, HTTP 422). Payload-shape validation (`ERR_INVALID_REQUEST`, HTTP 400) follows those guards. Business rules come last, in a fixed relative order wherever several guard the same operation: course eligibility (`ERR_COURSE_INELIGIBLE`) before request caps (`ERR_REQUEST_CAP_EXCEEDED`); section-assignment validity (`ERR_SECTION_ASSIGNMENT_INVALID`) before grid conflicts (`ERR_GRID_CONFLICT`); then, in sequence, appointment conflicts (`ERR_APPOINTMENT_CONFLICT`), student period conflicts (`ERR_STUDENT_PERIOD_CONFLICT`), seat capacity (`ERR_SECTION_FULL`), the credit-load ceiling (`ERR_CREDIT_CEILING_EXCEEDED`), the singleton cap (`ERR_SINGLETON_CAP_EXCEEDED`), the change-request quota (`ERR_CHANGE_QUOTA_EXCEEDED`), and the cohort concentration guard (`ERR_COHORT_CAP_EXCEEDED`); with counselor caseload (`ERR_CASELOAD_FULL`), publish blocking (`ERR_PUBLISH_BLOCKED`), close-window blocking (`ERR_CLOSE_WINDOW_BLOCKED`), and selector emptiness (`ERR_NO_ELIGIBLE_SECTION`, `ERR_RECOVERY_NO_SECTION`) occupying the final positions, so a placement that fails several guards always surfaces the earliest in this order.

### 2.9. The Logical Clock

Time-dependent rules — the no-show lookback window in particular — are evaluated against a server-side logical clock, never against wall-clock time. At startup, before any explicit set, the logical clock reads exactly 2026-05-01T00:00:00Z. An administrator may advance it through a dedicated test-driving capability mounted outside the `/scheduling` prefix — `POST /_clock/set_current_utc` — supplying the target instant as `to_iso8601`; the response echoes the new value as `current_utc`. Once set, the clock must not fall back to wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Laying the Groundwork: Terms, Catalog, and People

An administrator begins by creating the academic term: a unique `code` such as `2026-FALL`, the `periods_per_day` defining the master grid (at least 4 and at most 10), the hard seat ceiling `max_students_per_section` (between 1 and 40), and the soft `class_size_target` used later by balancing (at least 1 and strictly below the seat ceiling). Two optional knobs tune downstream workflows: `singleton_section_cap`, the maximum number of single-section courses one student may hold (default 2; a value of 0 leaves singletons unrestricted, and the cap may not exceed `periods_per_day`), and `change_request_max_per_student`, the cap on approved-but-unexecuted change requests per student per term (default 3, and at least 1). A new term starts in posture `COLLECTING` with `change_window_open` false, `rebalance_epoch` 0, and `total_requested_seats` 0; the term list is filterable by `posture`.

The catalog comes next. A course carries a unique `course_code`, a `title`, a credit value of at least 0.25 and at most 2.00 in quarter-credit steps, and a `subject_area` of `ENGLISH`, `MATH`, `SCIENCE`, `SOCIAL_STUDIES`, `WORLD_LANGUAGE`, `PE_HEALTH`, `ARTS`, or `ELECTIVE`. Sections of the course must occupy rooms matching its `required_room_type` — one of `STANDARD`, `LAB`, `GYM`, or `STUDIO`, defaulting to `STANDARD`. The `singleton` flag (default false) marks a course the school offers exactly once per term, subject to the singleton placement rules of §3.4 and §3.5. Eligibility is framed by `grade_band_min` (between 9 and 12) and `grade_band_max` (no lower than the band minimum and no higher than 12); a `special_program_exclusive` value of `NONE` (the default) leaves the course open to all, while `IEP`, `ELL`, `GIFTED`, or `ATHLETE` restricts it to students carrying the matching cohort tag; and an optional `prerequisite_course_id` — null for entry courses — chains the course behind one other course in the same catalog. The course list can be filtered by `subject_area`, `singleton`, or `prerequisite_course_id`.

Rooms are registered with a unique `room_number`, a physical `capacity` of at least one seat, and a `room_type` from the same four-value set (default `STANDARD`). Teachers carry a `full_name` and a `max_sections` load limit of at least one; their `assigned_section_count` is a computed tally of their sections in state `SCHEDULED` or `PUBLISHED` in the active term, refreshed whenever a section is created, scheduled, cancelled, or touched by a rebalance run. A teacher is cleared to teach a course by recording a qualification naming the `course_id` together with the `qualified_at` timestamp of when the qualification was recorded; when several teachers are eligible for the same section, the earliest `qualified_at` wins as the deterministic tie-break. Qualifications can be listed per teacher, or across the catalog filtered by `teacher_id` or `course_id`, and each qualification row is individually readable.

Counselors are registered with a `full_name` and a `max_caseload` of at least one. Students are enrolled with a unique `external_ref` district number of 4 to 32 characters, a `full_name`, a `grade_level` of 9, 10, 11, or 12, an optional `special_program` cohort tag (default `NONE`), the `counselor_id` of the counselor who owns their caseload, and optionally their lifetime `earned_credits` (default 0, never negative, two decimal places). Assigning a student to a counselor — at creation or on any later reassignment — requires the counselor's `caseload_count` to be strictly below `max_caseload`; a full caseload rejects the assignment with `ERR_CASELOAD_FULL` (HTTP 422). The `caseload_count` itself is computed: it counts the students whose `counselor_id` names this counselor, excluding any students withdrawn from the school, and is recomputed on every assignment and withdrawal. A counselor's roster is readable as a reverse lookup, and the student directory filters by `counselor_id`, `grade_level`, or the computed `credit_deficient` flag.

### 3.2. Collecting Course Requests

While the term sits in `COLLECTING`, students draft and submit course requests. Each request names its `student_id`, `course_id`, and `term_id`, carries a `priority_rank` (1 is highest), and may set the `is_alternate` flag (default false) marking it as a fallback used only when a higher-ranked primary cannot be placed. Among a student's non-alternate requests in a term, the ranks must form a contiguous sequence starting at 1 with no gaps and no duplicates; a malformed sequence — like any missing required field, invalid enum value, or credit value not expressed in quarter steps — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Eligibility is checked when the request is created and again when it is submitted, with any failure surfacing as `ERR_COURSE_INELIGIBLE` (HTTP 422): the student's `grade_level` must fall within the course's grade band inclusive of both ends; a course with a `prerequisite_course_id` demands that the student has either earned credit for the prerequisite course already or holds an `ENROLLED` entry in it this term; a program-exclusive course admits only students whose `special_program` equals the course's `special_program_exclusive` value; and the student may not already hold a non-alternate request for the same course this term.

Submitting moves a request from `DRAFT` to `SUBMITTED` and belongs to the student alone — the acting student's id must match the request's `student_id`, or the attempt is refused with `ERR_FORBIDDEN_OWNERSHIP`. Submission is possible only while the term is `COLLECTING`, and two caps guard it: the student must hold fewer than 8 non-alternate requests in `DRAFT` or `SUBMITTED` for the term, and the total credit load of their primary (non-alternate) requests may not exceed 8.0. Breaching either cap rejects the submission with `ERR_REQUEST_CAP_EXCEEDED` (HTTP 422).

Every request carries a computed `tally_weight`: 1.0 for a primary request in `SUBMITTED` or `LOCKED`, 0.5 for an alternate in one of those states, and 0 in every other case. Submission recomputes the weight upward and refreshes the term's `total_requested_seats`, the running tally over requests in `SUBMITTED` or `LOCKED`; unsubmitting — allowed only while `COLLECTING` lasts, moving the request `SUBMITTED` → `DRAFT` — recomputes the weight to zero and refreshes the tally again. A request still in `DRAFT` may be withdrawn entirely: withdrawal removes the draft row outright as a hard delete (a request already `SUBMITTED` must first be unsubmitted), and it counts as the `DRAFT` → `WITHDRAWN` lifecycle transition, zeroing the weight and recounting the term tally. Request lists filter by `student_id`, `term_id`, `state`, or `course_id`.

Before committing to section counts, an administrator or counselor can read an optimistic tally preview while the term is still `COLLECTING`. The preview runs the same demand math as final generation but additionally counts `DRAFT` requests at halved weight — 0.5 for a primary draft, 0.25 for an alternate draft — on top of the submitted demand, so preview section counts are never lower than the final counts for identical submitted data whenever drafts exist. It returns one row per course with positive demand, each row carrying `course_id`, `course_code`, `demand`, and `projected_sections`.

### 3.3. Closing Collection and Building the Grid

When collection ends, an administrator closes it. The term moves `COLLECTING` → `TALLYING`, every request still in `DRAFT` is swept to `WITHDRAWN` (each such request's `tally_weight` recomputing to zero), `total_requested_seats` is recomputed over the surviving `SUBMITTED` and `LOCKED` requests, and the term's `version` increments by one.

Generation then moves the term `TALLYING` → `BUILDING`. The final tally counts only `SUBMITTED` and `LOCKED` requests at full or alternate weight — drafts are excluded entirely, having been withdrawn at close. For each course, demand is the sum of `tally_weight` over its requests in those states, computed first as an exact value in half-weight increments; that demand is then divided by the term's `class_size_target`, and only then is the quotient rounded up to a whole section count — rounding demand before dividing is forbidden. A `singleton` course yields exactly one section when its demand is positive and zero otherwise; any other course yields the rounded-up count when its demand is positive and zero otherwise; and in either case no course may receive more sections than the term has `periods_per_day`, since a course may not occupy every period of the day. Sections are created in state `DRAFT` with teacher and room unassigned, and only for courses with positive demand and zero existing non-`CANCELLED` sections. As the sweep completes, every `SUBMITTED` request locks — `SUBMITTED` → `LOCKED` — keeping its weight in the tally, and the term's `version` increments again.

Staffing happens section by section while the term is in `BUILDING`. An administrator schedules a draft section by supplying its `teacher_id`, `room_id`, `period`, and `capacity`, together with `expected_term_version` for optimistic concurrency (§2.7); on success the section moves `DRAFT` → `SCHEDULED`, the teacher's `assigned_section_count` recomputes, and both the section's `version` and the term's `version` increment by one. The assignment enforces a battery of guards. The term must be in `BUILDING` (`ERR_INVALID_TERM_POSTURE`) and the section still in `DRAFT` (`ERR_INVALID_STATE`). A qualification row must exist pairing the teacher with the section's course, and the room's `room_type` must equal the course's `required_room_type`; either failure is `ERR_SECTION_ASSIGNMENT_INVALID` (HTTP 422). The teacher's `assigned_section_count` must be strictly below `max_sections` — equivalently, the count after this assignment may not exceed the maximum. The section's `capacity` must be at least 1 and may not exceed the smaller of the term's `max_students_per_section` and the room's physical `capacity`, and the `period` itself is a 1-indexed slot no greater than `periods_per_day`. Finally, the discrete period grid must stay conflict-free: no other non-`CANCELLED` section in the term may occupy the same teacher-and-period slot or the same room-and-period slot. Grid occupancy is point-slot semantics — two sections collide only when they occupy the same period integer for the same resource, so sections in adjacent periods coexist freely. A collision is rejected with `ERR_GRID_CONFLICT` (HTTP 409). A `SCHEDULED` section that proves unnecessary can be cancelled while `BUILDING` continues, provided it still has zero enrolled students; cancellation recomputes the teacher's load. Section lists filter by `term_id`, `course_id`, `teacher_id`, `room_id`, or `state`, and a section's roster reads back its schedule entries, filterable by `state`.

### 3.4. Publication and Auto-Placement

Publication is the point of no return for the grid. An administrator may publish only while the term is in `BUILDING`, only when every non-`CANCELLED` section has reached `SCHEDULED` with both teacher and room assigned, and only when no grid conflicts remain among the term's non-`CANCELLED` sections; a violation blocks publication with `ERR_PUBLISH_BLOCKED` (HTTP 409). On success the term moves `BUILDING` → `PUBLISHED`, every `SCHEDULED` section becomes `PUBLISHED` — visible to placement and to change requests — and the term's `version` increments by one.

Auto-placement then runs for the whole term. Each student's locked requests are walked from the lowest `priority_rank` upward, ties broken by the request's `created_at` ascending. For each request, the placement selector assembles candidate sections of the same course in the same term: only sections in state `PUBLISHED` qualify, only those whose `enrolled_count` is strictly below `capacity` (a section at exactly capacity is ineligible), only those whose `period` does not collide with the period of any of the student's other `ENROLLED` entries this term, and — for program-exclusive courses — only when the student's `special_program` matches the course's `special_program_exclusive` value, with unrestricted courses open to every student. Candidates are ranked lexicographically: first by `enrolled_count` ascending so the emptiest section fills first; then by a cohort penalty — 1 when the student belongs to a special program and that program's entry in the section's `cohort_counts` has already reached half the section's `capacity` rounded up to a whole seat, and 0 otherwise — so no special-program cohort is steered past half of a section; and finally by the section's `created_at` ascending as the deterministic tie-break, never by id. The evaluation order is pinned: eligibility filter first, then ranking, then tie-break, then fallback.

A request the selector satisfies becomes `PLACED`, and the placement writes a `ScheduleEntry` in state `ENROLLED` with `origin` `AUTO_PLACEMENT` and `epoch_placed` 0; the entry also carries its `term_id`, denormalized from its section for query locality. The section's `enrolled_count`, `cohort_counts`, and `under_enrolled` flag recompute, as does the student's `planned_credit_load` — the sum of course `credits` over the student's `ENROLLED` entries for the term, recomputed on every enrollment mutation and starting from 0. When the candidate set is empty for a primary request, the selector falls back to the student's next-higher-ranked untried alternate among that student's `SUBMITTED` or `LOCKED` alternates (the lowest `priority_rank` among those not yet tried, ties broken by `created_at` ascending); only when the primary and every such alternate have failed does the request become `UNPLACED`, with no entry created. Publication closes by running the credit-pace audit of §3.7 for every student with at least one request, writing one `CreditAudit` row per student.

Once published, the administrator opens the change window: `PUBLISHED` → `CHANGE_WINDOW` flips `change_window_open` to true and increments the term's `version` by one.

### 3.5. The Schedule Change Window

While the window is open, a student files change requests of three kinds: `DROP` to leave a section, `ADD` to join one, and `SWAP` to do both atomically. The payload names the `student_id`, `term_id`, and `kind`, plus a free-text `reason` of 10 to 500 characters. A `drop_entry_id` — the schedule entry to leave — is required for `DROP` and `SWAP` and forbidden for `ADD`; an `add_section_id` — the section to join — is required for `ADD` and `SWAP` and forbidden for `DROP`. Filing outside the change window is rejected with `ERR_INVALID_TERM_POSTURE`, and a new request is born in state `SUBMITTED`. Change-request lists filter by `student_id`, `term_id`, `state`, `kind`, `drop_entry_id`, `add_section_id`, or `reviewed_by_counselor_id`.

Review follows a strict relay. The counselor who owns the student's caseload — and only that counselor — claims a `SUBMITTED` request while `change_window_open` is true, moving it `SUBMITTED` → `COUNSELOR_REVIEW`, stamping `reviewed_by_counselor_id` with their own id, and incrementing the request's `version`; anyone else is turned away with `ERR_FORBIDDEN_OWNERSHIP`. The same counselor may hand the request back with a `revision_note`, moving it `COUNSELOR_REVIEW` → `REVISED` — a different counselor cannot, because the actor must match `reviewed_by_counselor_id` — and the student may then resubmit while the window remains open, returning the request `REVISED` → `SUBMITTED` with `reviewed_by_counselor_id` reset to null. Each of these steps increments the request's `version` by one.

Decision belongs to an administrator, never to the reviewing counselor. The decision call carries a `decision` of `APPROVE` or `REJECT` and an `expected_term_version` for optimistic concurrency (§2.7), and it acts only on requests sitting in `COUNSELOR_REVIEW`. Segregation of duties is enforced: the acting administrator's `X-User-ID` must differ from the request's `reviewed_by_counselor_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval additionally requires the student's count of approved-but-not-yet-executed change requests this term to be strictly below the term's `change_request_max_per_student` — a student at the quota is refused with `ERR_CHANGE_QUOTA_EXCEEDED` (HTTP 422) — and re-runs the business checks on the requested change: capacity, period overlap, the singleton cap, program exclusivity, and the credit-load ceiling. Approval moves the request `COUNSELOR_REVIEW` → `APPROVED`, sets `decided_by_admin` to true, and increments the request's `version`; rejection moves it `COUNSELOR_REVIEW` → `REJECTED` and likewise records `decided_by_admin` as true.

Execution is separate from approval, and approval does not freeze the world: executing an `APPROVED` request — again only while `change_window_open` holds — re-validates every business check at execution time. The target section's `period` must not equal the period of any of the student's other `ENROLLED` entries this term (`ERR_STUDENT_PERIOD_CONFLICT`, HTTP 409). Its `enrolled_count` must be strictly below `capacity`, a section at exactly capacity refusing the placement (`ERR_SECTION_FULL`, HTTP 422). The student's `planned_credit_load` plus the incoming course's `credits` must not exceed the 8.0 credit ceiling (`ERR_CREDIT_CEILING_EXCEEDED`, HTTP 422). When the term's `singleton_section_cap` is non-zero, the student's count of `ENROLLED` entries in `singleton` courses after the change must not exceed the cap (`ERR_SINGLETON_CAP_EXCEEDED`, HTTP 422). And adding the student must not push the target section's `cohort_counts` entry for the student's `special_program` above half the section's `capacity` rounded up to a whole seat whenever the student belongs to a special program (`ERR_COHORT_CAP_EXCEEDED`, HTTP 422). If no `PUBLISHED` section of the target course passes the placement selector at all — every candidate period-conflicted, full, cohort-capped, or program-mismatched — execution fails with `ERR_NO_ELIGIBLE_SECTION` (HTTP 422).

An executed `DROP` moves the dropped entry `ENROLLED` → `DROPPED`. An executed `ADD` creates a fresh entry in state `ENROLLED` with `origin` `CHANGE_REQUEST` and `epoch_placed` stamped with the term's current `rebalance_epoch`. An executed `SWAP` does both atomically: the dropped entry becomes `MOVED` with `moved_to_section_id` pointing at the replacement section, and the replacement `ENROLLED` entry is created in the same operation. Source and target sections recompute `enrolled_count`, `cohort_counts`, and `under_enrolled`; the student's `planned_credit_load` recomputes; the request becomes `EXECUTED` and its `version` increments by one. A student may also cancel their own request while it sits in `SUBMITTED` or `REVISED`, moving it to `CANCELLED` and incrementing its `version`.

Closing the window is an administrator action with its own guard: it is refused with `ERR_CLOSE_WINDOW_BLOCKED` (HTTP 409) while any change request of the term remains in `SUBMITTED`, `COUNSELOR_REVIEW`, `REVISED`, or `APPROVED`. When the close succeeds, the term moves `CHANGE_WINDOW` → `LOCKED`, `change_window_open` flips to false, any requests still in `SUBMITTED`, `COUNSELOR_REVIEW`, or `REVISED` are swept to `CANCELLED`, every `PENDING` recovery placement of the term expires (§3.7), and the term's `version` increments by one. A student's schedule for a term — their schedule entries in any state — is readable throughout, filterable by `term_id` and `state`.

### 3.6. Counseling Caseloads and Appointments

Counselors meet students through appointments booked against the logical clock. Either the counselor or the student may book, supplying `counselor_id`, `student_id`, `start_at`, and `end_at`; the end must fall after the start and within the same UTC day, and the appointment is born in state `BOOKED`. Two interference rules guard the counselor's calendar, both surfacing as `ERR_APPOINTMENT_CONFLICT` (HTTP 409): the new interval must not overlap any of the counselor's existing `BOOKED` appointments, and it must keep a buffer of at least 10 minutes on both sides of every existing `BOOKED` interval — back-to-back appointments are forbidden, since adjacency without the buffer is itself a conflict. For the student, plain double-booking is forbidden with no buffer attached: the new interval simply may not overlap any of the student's other `BOOKED` appointments. Appointment lists filter by `counselor_id`, `student_id`, or `state`.

A three-strike freeze protects counselor time. A student's trailing no-show count is the number of their appointments in state `NO_SHOW` whose `start_at` falls within the 90 days before the server's logical now, counted in chronological order; the lookback's lower bound is closed, so a no-show stamped exactly ninety days earlier still counts. When that count has reached three — exactly three engages the freeze; the rule is a threshold met, not exceeded — any new booking for the student is rejected with `ERR_NO_SHOW_FREEZE` (HTTP 422). At booking time the current trailing count is captured into the appointment's `no_show_count_snapshot`.

A booked appointment is resolved by the attending counselor: completing it moves `BOOKED` → `COMPLETED`, and marking a no-show moves `BOOKED` → `NO_SHOW`, which recomputes the student's trailing no-show count and may trip the freeze against future bookings. Cancellation is open to either party — the attending counselor or the student — and moves `BOOKED` → `CANCELLED`. Each of these resolutions increments the appointment's `version` by one.

Workload reporting runs through a computed utilization read over a window supplied as `window_start` and `window_end`. Booked minutes sum the durations of the counselor's `BOOKED` appointments inside the half-open window — an appointment starting exactly at `window_end` is excluded, and one ending exactly at `window_start` is excluded; each appointment's duration is first truncated to whole minutes with seconds discarded rather than rounded, the whole minutes are then summed, and only then is the division performed. Available minutes are the number of weekdays — Monday through Friday — whose date overlaps the window, multiplied by 360, that is, six counselor hours per weekday. The utilization ratio is booked minutes over available minutes, rounded half-up to four decimal places and capped at 1.0000; summing fractional minutes before truncating is forbidden because it would produce a different result. The read returns `counselor_id`, `booked_minutes`, `available_minutes`, and `utilization`.

### 3.7. Credit Audits and Recovery Placement

Graduation pace is defined per grade: a ninth grader must be on pace for 6.0 credits, a tenth grader 12.0, an eleventh grader 18.0, and a twelfth grader 22.0 by the end of that grade's fall term, and the figure for the student's `grade_level` becomes the audit's `required_credits`. The student's `projected_credits` are their lifetime `earned_credits` plus their `planned_credit_load`, and `deficiency_credits` is the shortfall — the greater of zero and the difference between required and projected — rounded half-up to two decimal places. A subject sweep then flags `deficient_subjects`: `ENGLISH` and `MATH` each demand 1.0 credits per grade year and `SCIENCE` and `SOCIAL_STUDIES` 0.5 each, and a subject is deficient when the student's earned-plus-planned credits in that `subject_area` fall below the per-year minimum multiplied by the number of high-school years underway — the student's `grade_level` minus 8. The evaluation order is pinned: `planned_credit_load` is computed first from the student's `ENROLLED` entries, then projected credits, then the deficiency, then the subject sweep, and the sweep consumes `planned_credit_load` as an input rather than re-deriving it. The student's `credit_deficient` flag simply reflects the latest audit: true exactly when that audit's `deficiency_credits` is positive, and false by default before any audit exists. Each audit records the term's `rebalance_epoch` at the moment it ran as its `audit_epoch`, and audits are idempotent within an epoch.

Two variants of the projection exist. While the term is still `COLLECTING`, a provisional credit-projection read replaces `planned_credit_load` with the requested credits of the student's `SUBMITTED` primary requests — alternates excluded — so a student with unplaced requests typically projects higher than the final audit will; the read returns `student_id`, `projected_credits`, `required_credits`, `deficiency_credits`, and `deficient_subjects`. The final-audit variant is what gets written to `CreditAudit` rows at publication and at recovery placement, counting only `ENROLLED` entries, so unplaced requests contribute zero and the final projected total never exceeds the provisional figure whenever any request went `UNPLACED`. A student's latest audit for a term is recomputed on read, and audit rows are also browsable in bulk filtered by `student_id` or `term_id`, each row individually readable by id.

When a student on their caseload comes up credit-deficient, a counselor opens a recovery placement naming the `student_id`, `term_id`, and `target_course_id` chosen to close the gap. The placement is born `PENDING` with its `section_id` null until placed, and it carries a computed `priority_score`: ten points per credit of `deficiency_credits`, plus two points per high-school year underway (`grade_level` minus 8), plus three points when `ENGLISH` is among the deficient subjects and another three when `MATH` is — all drawn from the student's latest audit for the term (the greatest `audit_epoch`, ties broken by the audit's `created_at` descending) and rounded half-up to two decimal places. When recovery sections are scarce, higher scores place first. Recovery placements are listable with filters for `student_id`, `term_id`, `state`, `target_course_id`, or `section_id`.

Placing the student is the counselor's move, valid from `PENDING` while the term posture is `PUBLISHED`, `CHANGE_WINDOW`, or `LOCKED`, and only for the counselor who owns the student's caseload. The recovery selector — the placement selector of §3.4 run for the target course — must return a section, or the placement fails with `ERR_RECOVERY_NO_SECTION` (HTTP 422); and the same execution-time guards as schedule changes apply, including the period-conflict, seat-capacity, credit-ceiling, singleton-cap, and cohort-concentration rules, with the student's `planned_credit_load` plus the target course's `credits` held to the 8.0 ceiling. A successful placement moves `PENDING` → `PLACED`, stamps `section_id` with the selected section, creates an `ENROLLED` entry with `origin` `RECOVERY_PLACEMENT` and `epoch_placed` equal to the term's current `rebalance_epoch`, recomputes the section's counters and the student's `planned_credit_load`, writes a fresh `CreditAudit` for the student, recomputes `credit_deficient` from that audit, and increments the placement's `version` by one. An administrator may instead waive a `PENDING` placement by supplying a `waiver_reason` of 10 to 500 characters; waiving settles the placement as `WAIVED` and recomputes `credit_deficient`, but it does not forgive the deficiency — the flag remains whatever the latest audit says. Placements still `PENDING` when the change window closes are swept to `EXPIRED` with no further effect beyond the state flip.

### 3.8. Mid-Year Rebalancing

After the term locks, an administrator may launch a rebalance run against it — the posture must be `LOCKED` — carrying `expected_term_version` for optimistic concurrency (§2.7). The run increments the term's `rebalance_epoch` by one and writes a `RebalanceRun` row whose `epoch` field holds that new value — the term's previous `rebalance_epoch` plus one — stamped with the server's `executed_at` timestamp. The run measures term-wide imbalance before and after its move sweep. Imbalance is computed over the term's non-`CANCELLED` `PUBLISHED` sections: first the total enrolled seats across all of them, then a per-period target — that total divided by `periods_per_day`, the same target for every period — then the sum over all periods of the absolute gap between each period's actual load and the target, rounded half-up to two decimal places; computing the total before any per-period target is part of the contract. The two measurements are recorded as `imbalance_score_before` and `imbalance_score_after`.

Consolidation comes first. Any under-enrolled `PUBLISHED` section whose `enrolled_count` has fallen to zero is cancelled outright — a section flies the `under_enrolled` flag when its enrollment sits below half its `capacity` rounded up to a whole seat, and the flag drives this consolidation candidacy — and the affected teachers' `assigned_section_count` values recompute. Pure cancellations do not count as moves: the run's `moves_proposed` reflects only students relocated by the sweep, starting from 0 and untouched by the cancellations.

The move sweep then drains over-target sections into under-target sections of the same course. Donors are sections whose `enrolled_count` exceeds `class_size_target`, visited from the largest surplus downward with `created_at` ascending breaking ties. Within a donor, candidate students are ordered with `special_program` `NONE` students first — neutrals move before cohort members — then by `epoch_placed` ascending so students placed in earlier epochs move first, then by the entry's `created_at` ascending; any student whose `epoch_placed` already equals the term's new `rebalance_epoch` is skipped, so no student moves twice in one run. Receivers are `PUBLISHED` sections of the same course sitting below `class_size_target`, ranked by `enrolled_count` ascending with `created_at` ascending as the tie-break. A move executes only when all three guards hold: the receiver's `period` must not collide with any of the student's other `ENROLLED` periods, the donor entry being moved aside; the cohort guard must hold after the move, meaning that for a special-program student the receiver's `cohort_counts` entry for that program must not exceed half the receiver's `capacity` rounded up; and the receiver must still have a free seat after the move. Each donor drains students into its single best receiver until the donor reaches `class_size_target` or runs out of movable students; whatever cannot move stays. The sweep halts when no donor remains above target or no legal moves remain. Every executed move marks the old entry `MOVED` with `moved_to_section_id` set to the receiving section, creates a replacement `ENROLLED` entry with `origin` `REBALANCE` and `epoch_placed` stamped with the new epoch, and recomputes both sections' counters and the student's `planned_credit_load` per move. The term's `version` increments by one as the run completes, the posture returns to `LOCKED`, and past runs remain listable per term. Individual schedule entries are readable on their own, and the collection is filterable by `term_id`, `section_id`, `student_id`, or `state`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all lifecycle transitions — return `200 OK`. The single deletion endpoint returns `204 No Content` with no body. Request and response bodies for every row below are specified by the narratives of §2 and §3; this table is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/scheduling/terms` | Create an AcademicTerm in posture COLLECTING | Administrator |
| GET    | `/scheduling/terms` | List terms, optionally filtered by posture | Administrator, Counselor, Student |
| GET    | `/scheduling/terms/{id}` | Read one term | Administrator, Counselor, Student |
| POST   | `/scheduling/terms/{id}/close-collection` | Close request collection (COLLECTING → TALLYING), withdrawing DRAFT requests | Administrator |
| POST   | `/scheduling/terms/{id}/generate-sections` | Run the section tally, create DRAFT sections, lock SUBMITTED requests (TALLYING → BUILDING) | Administrator |
| POST   | `/scheduling/terms/{id}/publish` | Publish the grid, run auto-placement, write credit audits (BUILDING → PUBLISHED) | Administrator |
| POST   | `/scheduling/terms/{id}/open-change-window` | Open the schedule change window (PUBLISHED → CHANGE_WINDOW) | Administrator |
| POST   | `/scheduling/terms/{id}/close-change-window` | Close the change window (CHANGE_WINDOW → LOCKED), cancelling in-flight requests and expiring pending recovery placements | Administrator |
| GET    | `/scheduling/terms/{id}/tally-preview` | Optimistic tally preview counting DRAFT requests at halved weight, while COLLECTING | Administrator, Counselor |
| POST   | `/scheduling/terms/{id}/rebalance-runs` | Execute a rebalance epoch against a LOCKED term, with OCC on the term version | Administrator |
| GET    | `/scheduling/terms/{id}/rebalance-runs` | List the RebalanceRun rows of a term | Administrator, Counselor |
| POST   | `/scheduling/courses` | Create a Course | Administrator |
| GET    | `/scheduling/courses` | List courses, filterable by subject area, singleton flag, or prerequisite | Administrator, Counselor, Student |
| GET    | `/scheduling/courses/{id}` | Read one course | Administrator, Counselor, Student |
| POST   | `/scheduling/counselors` | Create a Counselor | Administrator |
| GET    | `/scheduling/counselors/{id}` | Read one counselor | Administrator, Counselor |
| GET    | `/scheduling/counselors/{id}/students` | List the students on this counselor's caseload | Administrator, Counselor |
| GET    | `/scheduling/counselors/{id}/utilization` | Computed counselor utilization over a window | Administrator, Counselor |
| POST   | `/scheduling/teachers` | Create a Teacher | Administrator |
| GET    | `/scheduling/teachers/{id}` | Read one teacher | Administrator, Counselor |
| POST   | `/scheduling/teachers/{id}/qualifications` | Record a TeacherQualification for a course | Administrator |
| GET    | `/scheduling/teachers/{id}/qualifications` | List a teacher's qualifications | Administrator, Counselor |
| POST   | `/scheduling/rooms` | Create a Room | Administrator |
| GET    | `/scheduling/rooms/{id}` | Read one room | Administrator, Counselor |
| POST   | `/scheduling/students` | Create a Student and assign them to a counselor (caseload check applies) | Administrator |
| GET    | `/scheduling/students` | List students, filterable by counselor, grade level, or credit deficiency | Administrator, Counselor |
| GET    | `/scheduling/students/{id}` | Read one student | Administrator, Counselor, Student |
| GET    | `/scheduling/students/{id}/schedule` | Read the student's ScheduleEntry rows for a term, in any state | Administrator, Counselor, Student |
| GET    | `/scheduling/students/{id}/credit-audit` | Read the student's latest CreditAudit for a term, recomputed on read | Administrator, Counselor, Student |
| GET    | `/scheduling/students/{id}/credit-projection` | Provisional credit projection over SUBMITTED primaries, while COLLECTING | Administrator, Counselor, Student |
| POST   | `/scheduling/course-requests` | Student creates a DRAFT CourseRequest | Student |
| GET    | `/scheduling/course-requests` | List course requests, filterable by student, term, state, or course | Administrator, Counselor, Student |
| GET    | `/scheduling/course-requests/{id}` | Read one course request | Administrator, Counselor, Student |
| POST   | `/scheduling/course-requests/{id}/submit` | Submit a DRAFT request with full eligibility validation (DRAFT → SUBMITTED) | Student |
| POST   | `/scheduling/course-requests/{id}/unsubmit` | Pull a SUBMITTED request back to DRAFT while COLLECTING | Student |
| DELETE | `/scheduling/course-requests/{id}` | Withdraw a DRAFT request (hard delete; SUBMITTED rows must unsubmit first) | Student |
| GET    | `/scheduling/sections` | List sections, filterable by term, course, teacher, room, or state | Administrator, Counselor, Student |
| GET    | `/scheduling/sections/{id}` | Read one section | Administrator, Counselor, Student |
| PATCH  | `/scheduling/sections/{id}` | Assign teacher, room, period, and capacity to a DRAFT section (DRAFT → SCHEDULED), with OCC on the term | Administrator |
| POST   | `/scheduling/sections/{id}/cancel` | Cancel an empty SCHEDULED section during BUILDING | Administrator |
| GET    | `/scheduling/sections/{id}/roster` | Read a section's ScheduleEntry rows | Administrator, Counselor |
| POST   | `/scheduling/change-requests` | Student files a DROP, ADD, or SWAP change request during CHANGE_WINDOW | Student |
| GET    | `/scheduling/change-requests` | List change requests with filters | Administrator, Counselor, Student |
| GET    | `/scheduling/change-requests/{id}` | Read one change request | Administrator, Counselor, Student |
| POST   | `/scheduling/change-requests/{id}/claim` | Counselor claims a SUBMITTED request (SUBMITTED → COUNSELOR_REVIEW) | Counselor |
| POST   | `/scheduling/change-requests/{id}/return-for-revision` | Counselor returns the request to the student (COUNSELOR_REVIEW → REVISED) | Counselor |
| POST   | `/scheduling/change-requests/{id}/resubmit` | Student resubmits a REVISED request (REVISED → SUBMITTED) | Student |
| POST   | `/scheduling/change-requests/{id}/decide` | Administrator approves or rejects a COUNSELOR_REVIEW request, with OCC on the term and segregation of duties | Administrator |
| POST   | `/scheduling/change-requests/{id}/execute` | Execute an APPROVED request atomically, re-validating all business checks | Administrator |
| POST   | `/scheduling/change-requests/{id}/cancel` | Student cancels their own SUBMITTED or REVISED request | Student |
| POST   | `/scheduling/appointments` | Book an appointment (counselor buffer, student overlap, and no-show freeze checks) | Counselor, Student |
| GET    | `/scheduling/appointments` | List appointments, filterable by counselor, student, or state | Administrator, Counselor, Student |
| GET    | `/scheduling/appointments/{id}` | Read one appointment | Administrator, Counselor, Student |
| POST   | `/scheduling/appointments/{id}/complete` | Mark a BOOKED appointment COMPLETED (attending counselor only) | Counselor |
| POST   | `/scheduling/appointments/{id}/mark-no-show` | Mark a BOOKED appointment NO_SHOW (attending counselor only); may trip the three-strike freeze | Counselor |
| POST   | `/scheduling/appointments/{id}/cancel` | Cancel a BOOKED appointment (attending counselor or the student) | Counselor, Student |
| POST   | `/scheduling/recovery-placements` | Counselor creates a recovery placement for a credit-deficient student on their caseload | Counselor |
| GET    | `/scheduling/recovery-placements` | List recovery placements with filters | Administrator, Counselor, Student |
| GET    | `/scheduling/recovery-placements/{id}` | Read one recovery placement | Administrator, Counselor, Student |
| POST   | `/scheduling/recovery-placements/{id}/place` | Place the deficient student into the selected recovery section | Counselor |
| POST   | `/scheduling/recovery-placements/{id}/waive` | Administrator waives a PENDING recovery placement | Administrator |
| GET    | `/scheduling/schedule-entries/{id}` | Read one ScheduleEntry | Administrator, Counselor, Student |
| GET    | `/scheduling/schedule-entries` | List ScheduleEntry rows, filterable by term, section, student, or state | Administrator, Counselor |
| GET    | `/scheduling/credit-audits/{id}` | Read one CreditAudit by id | Administrator, Counselor |
| GET    | `/scheduling/credit-audits` | List CreditAudit rows, filterable by student or term | Administrator, Counselor |
| GET    | `/scheduling/qualifications/{id}` | Read one TeacherQualification by id | Administrator, Counselor |
| GET    | `/scheduling/qualifications` | List TeacherQualification rows, filterable by teacher or course | Administrator, Counselor |
| POST   | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-05-01T00:00:00Z; never falls back to wall-clock time) | Administrator |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TERM_POSTURE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NO_SHOW_FREEZE` | 422 Unprocessable Entity |
| `ERR_COURSE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_REQUEST_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SECTION_ASSIGNMENT_INVALID` | 422 Unprocessable Entity |
| `ERR_GRID_CONFLICT` | 409 Conflict |
| `ERR_APPOINTMENT_CONFLICT` | 409 Conflict |
| `ERR_STUDENT_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_SECTION_FULL` | 422 Unprocessable Entity |
| `ERR_CREDIT_CEILING_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SINGLETON_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CHANGE_QUOTA_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COHORT_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CASELOAD_FULL` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_SECTION` | 422 Unprocessable Entity |
| `ERR_RECOVERY_NO_SECTION` | 422 Unprocessable Entity |
| `ERR_STALE_TERM_VERSION` | 412 Precondition Failed |
| `ERR_PUBLISH_BLOCKED` | 409 Conflict |
| `ERR_CLOSE_WINDOW_BLOCKED` | 409 Conflict |
