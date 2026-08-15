# Religious School Admin API — Product Requirements Document

## 1. Introduction

A congregation's religious school runs on a calendar that never quite matches the public school district's: classes meet on weekends, the year is punctuated by holidays and breaks, tuition is tied to membership in the congregation, and every family owes not only money but volunteer hours. Administrators juggle class placement by grade and language level, teacher hiring and background checks, ceremony readiness for each student, and a tuition ledger that must accommodate sibling discounts, early-bird pricing, need-based assistance, late fees, and mid-year withdrawals — all while a security and safety plan gates whether classes may meet at all.

This document specifies the Religious School Admin API, the system of record for that operation. It covers school-year configuration and opening, the security-plan approval loop, teacher vetting and hiring, section scheduling with room and time conflict detection, enrollment with membership-linked tiered tuition pricing, session and attendance tracking that drives ceremony eligibility, the tuition-assistance review pipeline with enforced segregation of duties, invoicing and payment allocation, family volunteer commitments, and the year-end close that sweeps every loose end into its terminal state. All resources are mounted under the `/school` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly four roles: `SchoolAdmin`, `AssistanceOfficer`, `Teacher`, and `Parent`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, each endpoint admits only the roles listed for it in §4; a caller whose role is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting Family; ownership checks on any family-scoped resource compare the resource's `family_id` (or the family identifier in the path) to `X-User-ID`, and a parent touching another family's subtree is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting Teacher; the only write a teacher may perform is posting attendance, and only for sessions of sections whose `teacher_id` equals `X-User-ID` — otherwise the request fails with `ERR_OWNERSHIP_MISMATCH`.

The remaining two roles use opaque identifiers. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `decided_by_user_id` on an AssistanceApplication when the administrator decides it, but never compares it to any entity's `id` except in the segregation-of-duties check described below. When `X-User-Role` is `AssistanceOfficer`, `X-User-ID` is likewise opaque; it is recorded as `reviewed_by_user_id` when the officer begins reviewing an application, and it participates only in that same segregation-of-duties comparison.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items before returning the page and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Version Semantics

Every resource in the system — SchoolYear, SecurityPlan, CalendarClosure, Family, Student, Teacher, Section, Enrollment, TuitionInvoice, Payment, AssistanceApplication, Session, Milestone, and VolunteerCommitment — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments with every modification.

Cascades count as modifications. When enrolling a student increments the section's `enrolled_count`, the section's `version` bumps and its `updated_at` refreshes; when a teacher separation unstaffs sections, each affected section's `version` bumps. One entity narrows this rule: a Family's `version` bumps **only** on balance-affecting mutations — issuing an invoice, posting or voiding a payment, a late-fee accrual that touches the family, a withdrawal credit, and the year-close buyout fee. Creating students or enrollments for a family does not bump the family's `version`. Consistency is immediate: every mutation and all of its cascade effects are visible in the same response.

### 2.5. The Logical Clock

The server never reads the wall clock. Instead it maintains a logical clock whose value at startup is exactly `2026-08-01T00:00:00Z`. Every timestamp the server mints — `created_at`, `issued_at`, `withdrawn_at`, `approved_at`, entry timestamps — and every date-sensitive rule (early-bird deadline comparisons, session-date validation, late-fee eligibility, withdrawal refund tiers) reads this logical clock. An administrator-only test-driving capability advances the clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents; the API never returns fractional cents. Wherever a calculation produces a fraction — a discounted tuition line, an assistance award, a late fee, a withdrawal credit — the result is rounded half up to whole cents at the step where the scaffold of the calculation calls for rounding, and tuition lines are rounded per line and then summed, never summed unrounded and rounded once at the end. Attendance percentages are the one non-monetary computed quantity with a precision rule: they are rounded half up to exactly two decimal places. Volunteer hours are plain numbers and undergo no rounding.

### 2.7. Optimistic Concurrency Control

Two write endpoints require an explicit optimistic-concurrency field, and no other endpoint takes a version field.

Creating an enrollment under a section (`POST /school/sections/{id}/enrollments`) requires the non-optional request field `expected_section_version`, carrying the section `version` the client last observed. If the section's current `version` has advanced since that observation — for example because another enrollment legitimately claimed a seat — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), since the client's view of remaining capacity is stale.

Issuing a tuition invoice (`POST /school/families/{id}/invoices`) requires the non-optional request field `expected_family_version`, carrying the family `version` the client last observed. A prior invoice issue, payment, void, late-fee accrual, or withdrawal credit legitimately mutates the family's balances; issuing from a stale balance view would supersede the wrong invoice, so a mismatch with the family's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Request Validation Order and Nested Path Resolution

The server evaluates request checks in a fixed priority order, so that earlier failures mask later ones deterministically:

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The caller's role appears in the endpoint's role list; otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Ownership.** On family-scoped endpoints a `Parent` may only reach the subtree whose `family_id` equals their `X-User-ID`, and a `Teacher` may only post attendance for sections they teach; otherwise `ERR_OWNERSHIP_MISMATCH`.
4. **Existence.** Path resources are validated left to right — a request naming a school year and then a closure is rejected with `ERR_NOT_FOUND` for the year before the closure is ever examined.
5. **Request shape.** Required fields are present, types and enum memberships are valid, and ranges hold — `capacity` at least 1, `amount_cents` greater than 0, `hours` greater than 0, a section's `start_time` strictly earlier than its `end_time`, a closure's `start_date` on or before its `end_date`, and the conditional award fields on a decide payload; otherwise `ERR_INVALID_REQUEST`.
6. **Optimistic concurrency.** Where §2.7 applies, `expected_section_version` or `expected_family_version` must equal the parent's current `version`; otherwise `ERR_STALE_VERSION`.
7. **State preconditions.** The requested transition's from-state holds (`ERR_INVALID_STATE`), and operations gated on an open year — enrollment creation, invoice issue, session creation, assistance application creation — find the year in `OPEN`; otherwise `ERR_SCHOOL_YEAR_NOT_OPEN`.
8. **Safety and compliance.** An `ACTIVE` security plan where required (`ERR_SECURITY_PLAN_NOT_ACTIVE`), a cleared background check for vetting (`ERR_BACKGROUND_CHECK_REQUIRED`), and segregation of duties on assistance decisions (`ERR_SEGREGATION_OF_DUTIES`).
9. **Calendar and temporal rules.** Closure overlap (`ERR_CLOSURE_OVERLAP`), a session date inside a closure (`ERR_SESSION_DATE_CLOSED`), a session date outside the year (`ERR_SESSION_DATE_OUT_OF_YEAR`), and holding a future-dated session (`ERR_SESSION_DATE_IN_FUTURE`).
10. **Cross-entity integrity.** An assigned teacher must be `HIRED` (`ERR_TEACHER_NOT_HIRED`), a section must be staffed before sessions are scheduled on it (`ERR_SECTION_UNSTAFFED`), and attendance entries must reference students enrolled in the section (`ERR_STUDENT_NOT_ENROLLED`).
11. **Domain constraints.** Capacity, placement, duplicate-enrollment, room-and-time conflict, capacity-below-enrolled, one-open-application, milestone-eligibility, volunteer-fulfillment, and billable-enrollment checks, each with its dedicated error code (see §5).
12. **Fiscal rules.** Re-issue only against an unpaid invoice (`ERR_INVOICE_HAS_PAYMENTS`), payment void only while the remainder survives in credit (`ERR_CREDIT_ALREADY_APPLIED`), and award parameters consistent with the chosen method (`ERR_AWARD_PARAMS_INVALID`).

### 2.9. Calendar and Time Interval Semantics

Three different interval conventions coexist, and each is load-bearing. Calendar closures use **closed-interval** semantics: a closure covers every day from `start_date` through `end_date`, both inclusive, and two closures overlap whenever those closed intervals intersect — a new closure whose first day is exactly one day after an existing closure's last day is adjacent, not overlapping, and is allowed. Session dates must fall inside the year's own closed window from the year's `start_date` through its `end_date`, again both inclusive. Section meeting times, by contrast, are **half-open**: a section occupies its room from `start_time` up to but not including `end_time`, so two sections in the same room on the same day may be back-to-back — one ending at exactly the minute the other begins — without conflict. Finally, the early-bird rule is strictly-before: an enrollment qualifies for the discount only when its `created_at` is strictly earlier than the year's `early_bird_deadline`; an enrollment created at exactly the deadline instant does not qualify.

### 2.10. Safety, Compliance, and Segregation of Duties

The school's safety posture gates real-world activity. Opening a school year requires at least one `ACTIVE` SecurityPlan covering that year, and holding any class session requires the same; both reject with `ERR_SECURITY_PLAN_NOT_ACTIVE` when no active plan exists. Teacher vetting requires the teacher's `background_check_cleared` flag to be true. Tuition-assistance decisions enforce segregation of duties: the administrator who decides an application must not be the officer who reviewed it, so a decide call whose `X-User-ID` equals the application's recorded `reviewed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 3. Business Logic & Workflows

### 3.1. Configuring the School Year, Its Security Plan, and Its Calendar

Everything begins when a `SchoolAdmin` registers a school year. The creation payload carries the display `name` (for example "2026-27"), the year's `start_date` and `end_date` (the first must be strictly earlier than the second), and the full pricing and policy configuration: `member_tuition_cents` and `non_member_tuition_cents` as the positive per-student base rates; `early_bird_pct`, a discount fraction that must be at least 0 and strictly less than 1, applied against enrollments created before `early_bird_deadline`; `sibling_discount_pcts`, an array of discount fractions indexed by sibling rank (for example first child 0, second child 0.10, third 0.20); `activity_fee_cents`, a non-negative flat per-family fee added to every issued tuition invoice; `volunteer_hours_required`, the positive number of hours each family must log; `volunteer_buyout_fee_cents`, the non-negative fee invoiced when a commitment defaults at year close; `late_fee_pct`, a fraction between 0 and 1 inclusive applied to overdue balances; `late_fee_min_balance_cents`, the non-negative floor below which balances are exempt; `tuition_due_date`, copied onto invoices at issue; `withdrawal_deadline`; `refund_pct_after_deadline`, a fraction between 0 and 1 inclusive; and `attendance_threshold_pct`, the milestone-eligibility threshold, strictly greater than 0 and at most 100 (a typical value is 80, and the comparison is inclusive). A new year starts in `SETUP`.

Before the year can open, the congregation's safety documentation must be in force. An administrator drafts a SecurityPlan for the year by supplying its `plan_document`; the plan starts in `DRAFT`. Submission moves it `DRAFT` → `SUBMITTED`, approval moves it `SUBMITTED` → `ACTIVE` and stamps `approved_at` from the logical clock (`approved_at` is null in every other status), and rejection returns it `SUBMITTED` → `DRAFT` — a revision loop that may repeat as many times as needed. Approving one plan supersedes any other `ACTIVE` plan for the same year, moving it to `SUPERSEDED`, so a year has at most one active plan at a time. An administrator may also retire the active plan directly, moving it `ACTIVE` → `SUPERSEDED` and leaving the year with no `ACTIVE` plan at all; until a new plan is approved, session holds and any further year opens are blocked with `ERR_SECURITY_PLAN_NOT_ACTIVE`.

With an `ACTIVE` plan in place, opening the year moves it `SETUP` → `OPEN`; without one the attempt fails with `ERR_SECURITY_PLAN_NOT_ACTIVE`. Only an `OPEN` year accepts enrollments, invoice issues, session scheduling, and assistance applications — each of those operations rejects with `ERR_SCHOOL_YEAR_NOT_OPEN` against a year in any other status.

Holidays and breaks are recorded as CalendarClosures under the year, each with a `start_date`, an `end_date` on or after it, and a `reason` label, covering the closed interval from first through last day inclusive. A new closure that overlaps an existing one under the closed-interval semantics of §2.9 is rejected with `ERR_CLOSURE_OVERLAP`. Creating a closure also cancels class: every `SCHEDULED` session of every section in the year whose `session_date` falls inside the closure interval moves to `CANCELLED` with `cancel_reason` `CLOSURE`, and for each affected student the attendance figures are recomputed and the milestone re-evaluated as described in §3.4.

### 3.2. Faculty Pipeline and Classroom Scheduling

Teachers enter the system when an administrator registers them with a `full_name`, an `email`, and an optional `background_check_cleared` flag that defaults to false; a new teacher starts in `APPLIED`. Vetting moves a teacher `APPLIED` → `VETTED` and is only permitted once the background check has cleared — vetting a teacher whose `background_check_cleared` is still false fails with `ERR_BACKGROUND_CHECK_REQUIRED`. Hiring moves `VETTED` → `HIRED`, and only `HIRED` teachers may be assigned to sections: an attempt to assign a teacher in `APPLIED`, `VETTED`, or `SEPARATED` status fails with `ERR_TEACHER_NOT_HIRED`.

Separation ends the pipeline from either direction. Separating a `VETTED` teacher simply moves them to `SEPARATED`. Separating a `HIRED` teacher triggers a three-hop cascade that keeps the schedule consistent: first, every section assigned to that teacher in `OPEN` or `FULL` status has its `teacher_id` cleared to null and its `staffing_status` recomputed to `UNSTAFFED`, with each such section's `version` bumping; second, every `SCHEDULED` session of each unstaffed section moves to `CANCELLED` with `cancel_reason` `TEACHER_SEPARATION`; third, for each cancelled session the attendance of the section's enrolled students is recomputed with the cancelled session excluded, and every affected Milestone is re-evaluated against the threshold, flipping between `TRACKING` and `ELIGIBLE` as the numbers dictate.

Sections are the school's classrooms. An administrator creates one under a year by supplying its `grade`, its `hebrew_level`, a `capacity` of at least 1, a `room`, a `day_of_week` (one of `SUN`, `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`), and `start_time` and `end_time` in 24-hour `HH:MM` form with the start strictly before the end. A `teacher_id` may be supplied at creation — the teacher must be `HIRED` or the create fails with `ERR_TEACHER_NOT_HIRED` — or omitted to create a deliberately unstaffed section. Room double-booking is impossible: a new section whose half-open time block intersects an existing section's block in the same `room` on the same `day_of_week` of the same year is rejected with `ERR_ROOM_TIME_CONFLICT`, while back-to-back meetings are permitted. A section starts in `OPEN` with `enrolled_count` 0.

Each section carries two independent status dimensions. The `status` dimension runs `OPEN` ↔ `FULL` → `CLOSED`: when an enrollment raises `enrolled_count` to equal `capacity` the section flips `OPEN` → `FULL`, and when a withdrawal lowers `enrolled_count` back below `capacity` a `FULL` section flips back to `OPEN` — both automatic, no client call involved; year close moves any `OPEN` or `FULL` section to `CLOSED`. The `staffing_status` dimension is purely derived: `STAFFED` exactly when `teacher_id` is set and that teacher's status is `HIRED`, otherwise `UNSTAFFED`. The two dimensions never influence each other. An administrator may later patch a section to reassign its `teacher_id` — again the incoming teacher must be `HIRED`, and setting one makes the section `STAFFED` — or to change its `capacity`, which may not be lowered below the current `enrolled_count` (`ERR_CAPACITY_BELOW_ENROLLED`). Patching a `CLOSED` section is rejected with `ERR_INVALID_STATE`, and every successful patch increments the section's `version`. The sections listing accepts optional `school_year_id`, `teacher_id`, and `status` filters.

### 3.3. Families, Students, and the Enrollment Decision

Before any enrollment, an administrator registers the Family with a `family_name`, a `primary_email`, and a `membership_status` of `MEMBER` or `NON_MEMBER` — a classification frozen for the lifetime of the record in this version, and one that drives which tuition base rate applies. A new family starts with `outstanding_balance_cents` and `credit_balance_cents` at 0 and `version` 1. Students are then created under the family by an administrator or by the parent of that family, each with a `full_name`, a `grade` of `K`, `G1`, `G2`, `G3`, `G4`, `G5`, `G6`, or `G7`, and a `hebrew_level` of `BEGINNER`, `INTERMEDIATE`, or `ADVANCED`; the student's `family_id` comes from the path.

Enrollment joins a student to a section, and either an administrator or the student's own parent may perform it — a parent acting for another family's child is rejected with `ERR_OWNERSHIP_MISMATCH`. The payload carries the `student_id` and the `expected_section_version` required by §2.7; the target section comes from the path. Four domain checks guard placement, all evaluated after the generic pipeline of §2.8: the year must be `OPEN`; the student's `grade` must exactly equal the section's `grade` and the student's `hebrew_level` must exactly equal the section's `hebrew_level`, or the enrollment is rejected with `ERR_PLACEMENT_MISMATCH`; the section must have room, so an enrollment attempted when `enrolled_count` has already reached `capacity` fails with `ERR_SECTION_FULL`; and the student must not already hold an enrollment in the same year in `REGISTERED` or `ACTIVE` status, which fails with `ERR_DUPLICATE_ENROLLMENT`. The enrollments listing accepts optional `family_id`, `student_id`, `section_id`, `school_year_id`, and `status` filters.

A successful enrollment is created in `REGISTERED` status. Its `section_id` comes from the path, while `family_id` is denormalized from the student and `school_year_id` from the section at creation time. The section's `enrolled_count` increases by one and its `version` bumps; if the count now equals `capacity`, the section flips to `FULL`. Two support records appear automatically on first use: the student's first enrollment in a year auto-creates a Milestone in `TRACKING` with `milestone_name` defaulting to `ANNUAL_CEREMONY`, and the family's first enrollment in a year auto-creates a VolunteerCommitment in `OPEN` whose `required_hours` is copied from the year's `volunteer_hours_required`.

Every enrollment freezes a provisional tuition figure at creation in `estimated_tuition_cents`, computed as follows. The base rate is the year's `member_tuition_cents` when the family's `membership_status` is `MEMBER`, otherwise `non_member_tuition_cents`. The family's enrollments in the year with status `REGISTERED`, `ACTIVE`, or `COMPLETED` — `WITHDRAWN` enrollments are excluded — are ranked by `created_at` ascending, with identical timestamps broken by server request-arrival order so the earlier-processed creation ranks first; this enrollment's zero-based position in that ranking is its `sibling_rank`. The sibling discount fraction is the element of the year's `sibling_discount_pcts` array at the index given by the smaller of the `sibling_rank` and the array's last index, so a family with more children than configured tiers keeps the last tier for every additional child. The discounted figure is the base multiplied by one minus that fraction, rounded half up to whole cents. Finally, if the enrollment's `created_at` is strictly earlier than the year's `early_bird_deadline`, the result is multiplied by one minus `early_bird_pct` and rounded half up to whole cents a second time; otherwise the sibling-discounted figure stands. This provisional number is frozen on the enrollment and later serves as the base for withdrawal credits; the invoice-time recomputation in §3.6 runs the same formula against the ranking as it exists at issue, and because withdrawals shift siblings' ranks, the final figure may differ from the frozen estimate.

### 3.4. Sessions, Attendance, and Ceremony Readiness

With a staffed section in an open year, an administrator schedules class Sessions one meeting at a time by supplying the `session_date`; the session's `section_id` comes from the path. Scheduling is refused when the section is `UNSTAFFED` (`ERR_SECTION_UNSTAFFED`), when the year is not `OPEN` (`ERR_SCHOOL_YEAR_NOT_OPEN`), when the date falls outside the year's inclusive `start_date`-to-`end_date` window (`ERR_SESSION_DATE_OUT_OF_YEAR`), or when the date falls inside any of the year's closures (`ERR_SESSION_DATE_CLOSED`). A session begins in `SCHEDULED`, and a section's sessions can be listed through the sessions collection under the section.

Holding a session is the system's acknowledgment that class actually met. The transition `SCHEDULED` → `HELD` is allowed only when the year has an `ACTIVE` security plan (`ERR_SECURITY_PLAN_NOT_ACTIVE`) and the `session_date` is on or before the logical clock's current date — holding a future-dated session fails with `ERR_SESSION_DATE_IN_FUTURE`. When the first session of a section is held, every `REGISTERED` enrollment of that section advances to `ACTIVE`, marking the students as having begun attendance. A session may instead be cancelled: an administrator cancels manually, stamping `cancel_reason` `MANUAL`, while the system cancels with `CLOSURE`, `TEACHER_SEPARATION`, or `YEAR_CLOSE` per the cascades described elsewhere; in all cases `cancel_reason` remains null until the session reaches `CANCELLED`. Cancellation of any kind re-runs the readiness math: each enrolled student's attendance percentage is recomputed with the cancelled session excluded, and any Milestone whose `current_attendance_pct` has fallen below the threshold drops from `ELIGIBLE` back to `TRACKING`. Attendance entries attached to `CANCELLED` sessions are excluded from all calculations.

Attendance is recorded on `HELD` sessions only — posting against a session in any other state is `ERR_INVALID_STATE` — by an administrator or by the teacher who teaches the section. The payload's `entries` array is upserted into the session's embedded `attendance` array, keyed by `student_id` so re-posting a student replaces their prior mark; each entry marks the student `PRESENT`, `ABSENT`, or `EXCUSED`. Every entry must reference a student holding a `REGISTERED` or `ACTIVE` enrollment in the session's section, or the whole post fails with `ERR_STUDENT_NOT_ENROLLED`. Each post re-triggers the attendance recomputation and milestone re-evaluation for the section's enrolled students.

The attendance percentage itself is defined precisely. Only `HELD` sessions with a non-empty `attendance` array count, and only those that were held while the student's enrollment was in `REGISTERED` or `ACTIVE`. Each student's mark in an eligible session contributes a weight: `PRESENT` counts as 1.0, `EXCUSED` as 0.5, `ABSENT` as 0.0, and a student with no entry at all in a posted session is weighted 0.0, treated as absent. The **current** percentage is the sum of weights divided by the number of eligible sessions, multiplied by 100 and rounded half up to two decimal places; when no eligible sessions exist the value is 0.0. This current figure is the only variant consulted for milestone eligibility, and it is stored on the Milestone as `current_attendance_pct`. A second **projected** figure, stored as `projected_attendance_pct`, gives planners the best case: it adds the count of the section's `SCHEDULED` sessions to both the numerator and the denominator of the same formula, as if the student attended every remaining scheduled meeting — identical underlying data, a different value.

Milestones track each student's journey to the year's ceremony. A milestone is auto-created in `TRACKING` on the student's first enrollment of the year, denormalizing `student_id`, `family_id` (kept on the record so the volunteer gate can be checked without a join), and `school_year_id`. Whenever attendance is posted, a session is cancelled or held, or an administrator invokes the evaluate capability, the two percentages are recomputed and the threshold rule is applied: the milestone moves `TRACKING` → `ELIGIBLE` when `current_attendance_pct` reaches or exceeds the year's `attendance_threshold_pct`, and slips back `ELIGIBLE` → `TRACKING` when recomputation drops it below — a cycle that may repeat arbitrarily over the year. The milestones listing accepts optional `student_id`, `family_id`, `school_year_id`, and `status` filters.

Scheduling the ceremony is a deliberate administrative act with two gates, checked in a fixed order: first the milestone must be in `ELIGIBLE` (`ERR_MILESTONE_NOT_ELIGIBLE`), and only then is the family's VolunteerCommitment for the year examined, which must be `FULFILLED` (`ERR_VOLUNTEER_REQUIREMENT_UNMET`) — so an ineligible milestone surfaces the eligibility error even when the family also owes hours. A successful schedule moves the milestone `ELIGIBLE` → `SCHEDULED` and may record an optional `ceremony_date`. The booking is fragile by design: if the family's commitment later regresses from `FULFILLED` to `OPEN` because an entry was voided, every `SCHEDULED` milestone of that family in that year automatically reverts to `ELIGIBLE`. Once the ceremony has taken place, completing the milestone moves it `SCHEDULED` → `COMPLETED`, its terminal state.

### 3.5. Tuition Assistance

A family that cannot meet full tuition applies for assistance through an application created by an administrator or by the parent of that family. The payload names the `school_year_id` and a free-text `reason` statement of need, and may optionally name a `requested_amount_cents` which, when present, must be greater than 0; the `family_id` comes from the path. The target year must be `OPEN` (`ERR_SCHOOL_YEAR_NOT_OPEN`), and a family may have at most one live application per year — any existing application for the same family and year in a status other than `DENIED` causes the new one to be rejected with `ERR_APPLICATION_ALREADY_OPEN`. A new application starts in `SUBMITTED`. The family's applications are listed under the family, and a separate review-queue listing for administrators and officers accepts optional `family_id`, `school_year_id`, and `status` filters.

Review is performed by an `AssistanceOfficer`. Starting review moves the application `SUBMITTED` → `UNDER_REVIEW` and records the caller's `X-User-ID` as `reviewed_by_user_id`, fixing the officer who owns the file. If the committee needs more from the family, requesting information returns the application `UNDER_REVIEW` → `SUBMITTED` while retaining `reviewed_by_user_id` — the reviewing officer remains the segregated party — and the submit/review loop may repeat as needed.

The decision belongs to a different desk. A `SchoolAdmin` decides an `UNDER_REVIEW` application by submitting a `decision` of `APPROVED` or `DENIED`. In both branches, segregation of duties is enforced first: if the deciding administrator's `X-User-ID` equals the recorded `reviewed_by_user_id`, the call is rejected with `ERR_SEGREGATION_OF_DUTIES`. An approval additionally requires the award parameters: `award_method` must be present as either `PERCENT_OF_NET` or `FLAT_CAP`, and the matching field must accompany it — `award_percent`, a fraction greater than 0 and at most 1, for `PERCENT_OF_NET`, or `award_amount_cents`, an amount greater than 0, for `FLAT_CAP`. An approval missing the method or carrying the wrong or invalid award field is rejected with `ERR_AWARD_PARAMS_INVALID`. A valid approval persists the method and award figure as a snapshot on the application and records the decider as `decided_by_user_id`; a denial records only `decided_by_user_id`. Both `APPROVED` and `DENIED` are terminal. Until the corresponding event occurs, `reviewed_by_user_id`, `decided_by_user_id`, `award_method`, `award_percent`, and `award_amount_cents` are all null on the application.

The award materializes at invoice time. When the family has an `APPROVED` application for the year, the invoice's `award_cents` is computed from it and the invoice records the source in `assistance_application_id`; otherwise `award_cents` is 0 and `assistance_application_id` is null. Under `PERCENT_OF_NET` the award is `award_percent` multiplied by the invoice's `gross_cents`, rounded half up to whole cents — the percent applies to gross tuition only, never to the activity fee. Under `FLAT_CAP` the award is the smaller of `award_amount_cents` and `gross_cents`, so the flat award can never exceed the gross. The two methods genuinely diverge: the same gross tuition yields a scaling award under one and a capped flat award under the other.

### 3.6. Billing: Invoices, Payments, and Late Fees

Invoicing is family-scoped and administrator-only. Issuing the family's tuition invoice for a year requires the `school_year_id` and the `expected_family_version` of §2.7; the year must be `OPEN`, and at least one billable enrollment must exist — an enrollment of the family in that year with status `REGISTERED`, `ACTIVE`, or `COMPLETED` — or the issue fails with `ERR_NO_BILLABLE_ENROLLMENTS`. Re-issue is the mechanism for correcting a bill: if the family already has an open tuition invoice for the year (one in `ISSUED` or `PARTIALLY_PAID` status), the re-issue supersedes it, moving it to `VOID` — but only when that open invoice has `paid_cents` of exactly 0. An open invoice that has already collected money blocks the re-issue outright with `ERR_INVOICE_HAS_PAYMENTS`, which is why no transition from `PARTIALLY_PAID` to `VOID` exists at all. Invoices of the volunteer-fee kind are never superseded and never block re-issue.

An issued invoice is fully computed at creation. Its `kind` is `TUITION` for endpoint-issued bills. Its `line_items` array carries one entry per billable enrollment, each entry naming the `enrollment_id`, the `student_id`, and a `line_cents` figure computed by re-running the §3.3 tuition formula against the sibling ranking as it stands at issue time — each line individually rounded half up to whole cents. The `gross_cents` is the sum of those already-rounded lines. The year's `activity_fee_cents` is copied onto the invoice, and any approved assistance award is applied as `award_cents` per §3.5. The `total_due_cents` is the gross plus the activity fee minus the award. The family's available credit is then consumed up front: `credit_applied_cents` is the smaller of the family's `credit_balance_cents` and the total due, and the family's credit is drawn down by that amount. A fresh invoice has `paid_cents` 0 and `late_fees_cents` 0, and its `balance_cents` is the total due minus the credit applied minus payments plus late fees. The invoice is stamped `issued_at` from the logical clock, its `due_date` is copied from the year's `tuition_due_date`, it lands in `ISSUED` status, and the family's `outstanding_balance_cents` — defined as the sum of `balance_cents` across all of the family's invoices in `ISSUED` or `PARTIALLY_PAID` status — is recomputed, with the family's `version` bumping. The invoices listing accepts optional `family_id`, `school_year_id`, `status`, and `assistance_application_id` filters.

Payments may be posted by an administrator or by the parent of the family, with a positive `amount_cents` and a `method` of `CARD`, `CHECK`, or `ACH`; the `family_id` comes from the path and the payment starts `POSTED`. The money allocates by waterfall: the family's open invoices (those in `ISSUED` or `PARTIALLY_PAID`) are ordered by `issued_at` ascending with ties broken by `created_at` ascending, and the payment walks the list from oldest to newest, applying to each invoice the smaller of the remaining payment and that invoice's `balance_cents`. Each application raises the invoice's `paid_cents` and lowers its `balance_cents` by the applied amount; an invoice whose balance reaches 0 flips to `PAID`, while one that received some but not all of its balance moves `ISSUED` → `PARTIALLY_PAID` or stays `PARTIALLY_PAID`. The payment records the allocation in its `applications` array as `invoice_id` and `applied_cents` pairs in waterfall order. Whatever remains after every open invoice is satisfied becomes the payment's `remainder_cents` and is added to the family's `credit_balance_cents`, where it will be consumed by a future invoice issue; the family's balances are recomputed and its `version` bumps.

Voiding a payment is administrator-only and moves it `POSTED` → `VOIDED`. The safeguard is that the payment's remainder must still be sitting in the family's credit: if the family's `credit_balance_cents` is less than the payment's `remainder_cents` — because a later invoice issue already consumed it — the void is rejected with `ERR_CREDIT_ALREADY_APPLIED`. A successful void reverses every application in the waterfall: each affected invoice's `paid_cents` decreases and `balance_cents` increases by the applied amount, and its status regresses accordingly — `PAID` returns to `PARTIALLY_PAID` when a positive balance is restored with payments still on record, and `PARTIALLY_PAID` returns to `ISSUED` when `paid_cents` reaches 0. The remainder is withdrawn from the family's credit, the outstanding balance is recomputed, and the family's `version` bumps.

Late fees accrue through an administrator-triggered checkpoint over a year. One pass examines every invoice of the year in `ISSUED` or `PARTIALLY_PAID` status — `PAID` and `VOID` invoices are exempt — and an invoice is eligible when the logical clock's current date is strictly after its `due_date` and its `balance_cents` is at least the year's `late_fee_min_balance_cents` (balances strictly below that floor are exempt). For each eligible invoice the fee is computed against a snapshot of the balance taken before the fee is added: the snapshot multiplied by the year's `late_fee_pct`, rounded half up to whole cents. The fee is added to the invoice's `late_fees_cents` and to its `balance_cents`, and because the snapshot excludes the fee itself, a single run never compounds its own charges; each pass adds at most one fee per invoice, and a later pass may add another if the invoice is still eligible. The response lists the affected invoices as `accrued_invoice_ids` and the grand total as `total_fees_cents`, and every touched family's `version` bumps.

### 3.7. Withdrawals and Refund Credits

A family may pull a student out mid-year: withdrawal moves an enrollment from `REGISTERED` or `ACTIVE` — the only two states from which withdrawal is permitted, anything else failing with `ERR_INVALID_STATE` — to `WITHDRAWN`, and may be performed by an administrator or by the parent of the withdrawing student's family. The section immediately feels the departure: its `enrolled_count` decreases by one, its `version` bumps, and if the section was `FULL` and the count has fallen below `capacity` it reopens to `OPEN`. The enrollment's `withdrawn_at` is stamped from the logical clock; both `withdrawn_at` and `withdrawal_credit_pct` are null for as long as the enrollment has not been withdrawn.

The refund policy is tiered by timing, and the computed fraction is stored on the enrollment as `withdrawal_credit_pct`. A withdrawal before the year's `withdrawal_deadline` earns a full credit — a fraction of 1.0. A withdrawal on or after the deadline but before the year's `end_date` earns the fraction configured in `refund_pct_after_deadline`. A withdrawal on or after `end_date` earns nothing — a fraction of 0.0. The boundaries belong to the lower tier: exactly at the deadline the second-tier fraction applies, and exactly at `end_date` the credit is zero.

Whether any credit actually lands depends on money having moved. The system looks for a non-`VOID` invoice of the family for the year whose `line_items` contain a positive `line_cents` entry for this enrollment, and requires that invoice's `paid_cents` to be greater than 0 — a billed amount the family actually began paying. Only then, and only if this enrollment's `credit_applied` flag is not already true, is a credit granted: the frozen `estimated_tuition_cents` — the provisional figure from §3.3, not the invoice-time recomputation — multiplied by the `withdrawal_credit_pct`, rounded half up to whole cents, added to the family's `credit_balance_cents`, with `credit_applied` set true and the family's `version` bumping. In every other case the withdrawal records its tier but grants nothing. Because `WITHDRAWN` enrollments drop out of the sibling ranking, a withdrawal also shifts the ranks of the family's remaining children, which is why their invoice-time figures may diverge from their frozen estimates; the granted credit itself sits in the family's credit until the next invoice issue consumes it through `credit_applied_cents`.

### 3.8. Volunteering and the Year-End Close

Each family's volunteer obligation lives on its VolunteerCommitment, auto-created in `OPEN` the first time the family enrolls anyone in the year, with `required_hours` copied from the year's configuration and the family's `family_id` and the `school_year_id` recorded on it. Hours arrive as entries: an administrator or the parent of the family logs a positive number of `hours` with a descriptive `note`, and the entry is appended to the commitment's embedded `entries` array with a server-minted `entry_id`, a `created_at`, and `ACTIVE` status. The commitment's `logged_hours` is always the sum of `hours` over `ACTIVE` entries only — voided entries never count — and the moment that sum reaches or exceeds `required_hours` the commitment flips `OPEN` → `FULFILLED`, unlocking the milestone-scheduling gate of §3.4. The commitments listing accepts optional `family_id`, `school_year_id`, and `status` filters.

Entries can be struck down. An administrator may void an entry, flipping that entry's status to `VOIDED` and recomputing `logged_hours`. When the void drops the family's total back below `required_hours`, the commitment regresses `FULFILLED` → `OPEN`, and — because ceremony bookings were contingent on fulfillment — every `SCHEDULED` milestone of that family in that year automatically reverts to `ELIGIBLE`. Hardship relief is also available: an administrator may waive a commitment in `OPEN` or `DEFAULTED`, moving it to the terminal `WAIVED` state; waiving a `DEFAULTED` commitment additionally voids the buyout-fee invoice that was created when it defaulted.

Closing the year is the final administrative act, moving the year `OPEN` → `CLOSED` and sweeping every aggregate to rest in one atomic gesture. Every `SCHEDULED` session of every section in the year is cancelled with `cancel_reason` `YEAR_CLOSE`. The volunteer ledger is settled: a commitment still `OPEN` whose `logged_hours` fall short of `required_hours` moves to `DEFAULTED`, and for each such family the system creates a fee-only invoice of `kind` `VOLUNTEER_FEE` — empty `line_items`, zero `activity_fee_cents`, zero `gross_cents`, zero `award_cents`, zero `credit_applied_cents`, a `total_due_cents` equal to the year's `volunteer_buyout_fee_cents`, the `due_date` copied from the year's `tuition_due_date`, in `ISSUED` status — which raises the family's `outstanding_balance_cents` and bumps its `version`; a commitment still `OPEN` whose hours meet the requirement instead moves to `FULFILLED` with no fee. Every section in `OPEN` or `FULL` moves to `CLOSED`. And every enrollment still in `REGISTERED` or `ACTIVE` moves to `COMPLETED`, closing the book on the year.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, computed fields, and side effects are specified in the §3 narratives referenced by each description; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/school/school-years` | Create a school year with full pricing and calendar configuration | SchoolAdmin |
| GET | `/school/school-years/{id}` | Get a school year | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| POST | `/school/school-years/{id}/open` | Open the year (`SETUP` → `OPEN`); requires an `ACTIVE` security plan | SchoolAdmin |
| POST | `/school/school-years/{id}/close` | Close the year (`OPEN` → `CLOSED`) with the full year-end sweep | SchoolAdmin |
| POST | `/school/school-years/{id}/accrue-late-fees` | Run one late-fee accrual pass over the year's eligible invoices | SchoolAdmin |
| POST | `/school/school-years/{id}/security-plan` | Create a security plan for the year (`DRAFT`) | SchoolAdmin |
| GET | `/school/school-years/{id}/security-plan` | List the year's security plans | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| POST | `/school/security-plans/{id}/submit` | Submit a plan (`DRAFT` → `SUBMITTED`) | SchoolAdmin |
| POST | `/school/security-plans/{id}/approve` | Approve a plan (`SUBMITTED` → `ACTIVE`), superseding the year's prior active plan | SchoolAdmin |
| POST | `/school/security-plans/{id}/reject` | Return a plan to `DRAFT` for revision | SchoolAdmin |
| POST | `/school/security-plans/{id}/retire` | Retire the active plan (`ACTIVE` → `SUPERSEDED`) | SchoolAdmin |
| POST | `/school/school-years/{id}/closures` | Create a closure; cancels covered `SCHEDULED` sessions | SchoolAdmin |
| GET | `/school/school-years/{id}/closures` | List the year's closures | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| POST | `/school/families` | Create a family | SchoolAdmin |
| GET | `/school/families/{id}` | Get a family (Parent: own family only) | SchoolAdmin, Parent |
| POST | `/school/families/{id}/students` | Create a student under a family | SchoolAdmin, Parent |
| GET | `/school/families/{id}/students` | List a family's students | SchoolAdmin, Parent |
| POST | `/school/teachers` | Create a teacher (`APPLIED`) | SchoolAdmin |
| GET | `/school/teachers/{id}` | Get a teacher | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| POST | `/school/teachers/{id}/vet` | Vet a teacher (`APPLIED` → `VETTED`); requires a cleared background check | SchoolAdmin |
| POST | `/school/teachers/{id}/hire` | Hire a vetted teacher (`VETTED` → `HIRED`) | SchoolAdmin |
| POST | `/school/teachers/{id}/separate` | Separate a teacher (`VETTED`/`HIRED` → `SEPARATED`); unstaffs sections and cancels their sessions | SchoolAdmin |
| POST | `/school/school-years/{id}/sections` | Create a section; room/day/time conflicts rejected | SchoolAdmin |
| GET | `/school/sections/{id}` | Get a section | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| GET | `/school/sections` | List sections with optional filters | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| PATCH | `/school/sections/{id}` | Reassign the teacher and/or change capacity | SchoolAdmin |
| POST | `/school/sections/{id}/enrollments` | Enroll a student (optimistic concurrency on the section) | SchoolAdmin, Parent |
| GET | `/school/enrollments/{id}` | Get an enrollment | SchoolAdmin, Parent |
| GET | `/school/enrollments` | List enrollments with optional filters (Parent: own family only) | SchoolAdmin, Parent |
| POST | `/school/enrollments/{id}/withdraw` | Withdraw an enrollment with the refund-tier credit | SchoolAdmin, Parent |
| POST | `/school/families/{id}/invoices` | Issue or re-issue the family's tuition invoice for a year (optimistic concurrency on the family) | SchoolAdmin |
| GET | `/school/invoices/{id}` | Get an invoice | SchoolAdmin, Parent |
| GET | `/school/invoices` | List invoices with optional filters (Parent: own family only) | SchoolAdmin, Parent |
| POST | `/school/families/{id}/payments` | Post a payment; waterfall allocation to open invoices, remainder to credit | SchoolAdmin, Parent |
| GET | `/school/families/{id}/payments` | List a family's payments | SchoolAdmin, Parent |
| POST | `/school/payments/{id}/void` | Void a posted payment; reverses applications and remainder | SchoolAdmin |
| POST | `/school/families/{id}/assistance-applications` | Apply for tuition assistance (Parent: own family only) | SchoolAdmin, Parent |
| GET | `/school/families/{id}/assistance-applications` | List a family's applications | SchoolAdmin, Parent |
| GET | `/school/assistance-applications/{id}` | Get an application | SchoolAdmin, AssistanceOfficer, Parent |
| GET | `/school/assistance-applications` | List applications with optional filters (review queue) | SchoolAdmin, AssistanceOfficer |
| POST | `/school/assistance-applications/{id}/start-review` | Start review (`SUBMITTED` → `UNDER_REVIEW`) | AssistanceOfficer |
| POST | `/school/assistance-applications/{id}/request-info` | Request more information (`UNDER_REVIEW` → `SUBMITTED`) | AssistanceOfficer |
| POST | `/school/assistance-applications/{id}/decide` | Decide an application (`UNDER_REVIEW` → `APPROVED`/`DENIED`); segregation of duties enforced | SchoolAdmin |
| POST | `/school/sections/{id}/sessions` | Schedule a session; requires a staffed section in an open year, outside closures | SchoolAdmin |
| GET | `/school/sections/{id}/sessions` | List a section's sessions | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| GET | `/school/sessions/{id}` | Get a session including its attendance array | SchoolAdmin, AssistanceOfficer, Teacher, Parent |
| POST | `/school/sessions/{id}/hold` | Mark a session held (`SCHEDULED` → `HELD`); requires an active plan and a reached date | SchoolAdmin |
| POST | `/school/sessions/{id}/cancel` | Cancel a session (`SCHEDULED` → `CANCELLED`, reason `MANUAL`) | SchoolAdmin |
| POST | `/school/sessions/{id}/attendance` | Upsert attendance entries on a `HELD` session (Teacher: own sections only) | SchoolAdmin, Teacher |
| GET | `/school/milestones/{id}` | Get a milestone | SchoolAdmin, Parent |
| GET | `/school/milestones` | List milestones with optional filters (Parent: own family only) | SchoolAdmin, Parent |
| POST | `/school/milestones/{id}/evaluate` | Recompute attendance percentages and re-apply the eligibility threshold | SchoolAdmin |
| POST | `/school/milestones/{id}/schedule` | Schedule the ceremony (`ELIGIBLE` → `SCHEDULED`); requires family volunteer fulfillment | SchoolAdmin |
| POST | `/school/milestones/{id}/complete` | Mark the milestone completed (`SCHEDULED` → `COMPLETED`) | SchoolAdmin |
| GET | `/school/volunteer-commitments/{id}` | Get a commitment including its entries | SchoolAdmin, Parent |
| GET | `/school/volunteer-commitments` | List commitments with optional filters (Parent: own family only) | SchoolAdmin, Parent |
| POST | `/school/volunteer-commitments/{id}/entries` | Log volunteer hours; auto-fulfills at the threshold | SchoolAdmin, Parent |
| POST | `/school/volunteer-commitments/{id}/entries/{entry_id}/void` | Void a volunteer entry; may regress fulfillment and revert scheduled milestones | SchoolAdmin |
| POST | `/school/volunteer-commitments/{id}/waive` | Waive a commitment (`OPEN`/`DEFAULTED` → `WAIVED`); voids the buyout-fee invoice when defaulted | SchoolAdmin |
| POST | `/school/_clock/set_current_utc` | Set the logical clock (test-driving capability) | SchoolAdmin |

## 5. Error Code Catalogue

Trigger conditions for each code are specified in the §2 and §3 narratives above.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SCHOOL_YEAR_NOT_OPEN` | 409 |
| `ERR_SECURITY_PLAN_NOT_ACTIVE` | 409 |
| `ERR_BACKGROUND_CHECK_REQUIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CLOSURE_OVERLAP` | 409 |
| `ERR_SESSION_DATE_CLOSED` | 409 |
| `ERR_SESSION_DATE_OUT_OF_YEAR` | 409 |
| `ERR_SESSION_DATE_IN_FUTURE` | 409 |
| `ERR_TEACHER_NOT_HIRED` | 422 |
| `ERR_SECTION_UNSTAFFED` | 422 |
| `ERR_STUDENT_NOT_ENROLLED` | 422 |
| `ERR_SECTION_FULL` | 409 |
| `ERR_PLACEMENT_MISMATCH` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_ROOM_TIME_CONFLICT` | 409 |
| `ERR_CAPACITY_BELOW_ENROLLED` | 409 |
| `ERR_APPLICATION_ALREADY_OPEN` | 409 |
| `ERR_MILESTONE_NOT_ELIGIBLE` | 409 |
| `ERR_VOLUNTEER_REQUIREMENT_UNMET` | 409 |
| `ERR_NO_BILLABLE_ENROLLMENTS` | 409 |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 |
| `ERR_CREDIT_ALREADY_APPLIED` | 409 |
| `ERR_AWARD_PARAMS_INVALID` | 409 |
