# Faculty Workload Course Assignment API — Product Requirements Document

## 1. Introduction

Academic departments operate under a dense web of contractual, fiscal, and pedagogical constraints every term. A chair must decide who teaches what before registration opens, must honor union-negotiated overload ceilings, must respect faculty consent when a course is assigned, must track release time bought out by research grants or administrative service, and must be able to demonstrate to the dean's office that every dollar of extra compensation stayed within the term's budget. Doing this on spreadsheets across email threads is the prevailing pain point: assignments go out late, qualifications lapse unnoticed, last-minute cancellations trigger stipend disputes, and nobody can reconstruct who approved what when the union grieves a workload violation.

This document specifies the Faculty Workload & Course Assignment API, a system that treats a teaching term as a governed allocation problem. The API models the full lifecycle — term setup with inline workload policy, faculty and course registries, qualification tracking, section scheduling, assignment proposal and consent, release-time buyouts, overload compensation approval, enrollment census finalization, and term publication — under a strict segregation-of-duties model in which the chair who endorses an overload payment may never be the dean-side approver who funds it. Every rule below exists so that, at any point in the term, a department can answer three questions with confidence: who is teaching what, what are they owed, and was every contractual step followed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly five roles, spelled precisely as follows: `DepartmentChair`, `FacultyMember`, `DeanOffice`, `Registrar`, and `SystemAdmin`. A request whose headers are missing, or whose `X-User-Role` value is not one of these five declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but not permitted for the target endpoint — including per-`to_state` role gates on the shared transition endpoints — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `FacultyMember`, `X-User-ID` is the `id` of the acting `FacultyMember`; ownership checks on any resource that references a `FacultyMember` compare the resource's foreign-key field to `X-User-ID`. This is what enforces faculty consent: a `FacultyMember` caller may confirm or decline an assignment only when the assignment's `faculty_id` equals the caller's `X-User-ID`, and any mismatch is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`. When `X-User-Role` is `DepartmentChair`, `DeanOffice`, `Registrar`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — most notably as `endorsed_by_user_id` on an `OverloadRequest` when a chair endorses — but it does not compare it to any entity's `id`, except for the segregation-of-duties comparison described next.

Segregation of duties governs overload compensation. When a `DeanOffice` operator attempts to move an overload request to `DEAN_APPROVED`, the approver's `X-User-ID` must differ from the request's recorded `endorsed_by_user_id`; a chair may never approve the same request they endorsed, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

Endpoints that return lists of resources are paginated via query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of any list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every top-level resource in the system — terms, faculty members, courses, qualifications, sections, assignments, release-time grants, overload requests, and load sheets — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource. This field is the basis of the optimistic concurrency control rules in §2.5.

Any mutation of a resource — including automatic cascades that touch a resource without an explicit client call on it, such as a section demoting from `STAFFED` to `SCHEDULED`, an assignment being withdrawn by a faculty-leave cascade, or a term's `comp_budget_spent_cents` increasing when a stipend posts — updates that resource's `updated_at` and increments its `version`. A transition call on an entity bumps that entity's `version` by 1 even when the transition carries no other field changes.

### 2.5. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, and each names a required version-bearing input field.

A policy edit on a workload term must carry `expected_term_version`, a non-optional field whose value must equal the term's current `version`. If another writer has advanced the term's version since the client last read it — for example, a fellow chair just committed a policy edit — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the term is stale. This guard applies only while the term is in `DRAFT`; a policy edit attempted against a term in any other state is rejected earlier with `ERR_INVALID_TERM_STATE`.

A registrar enrollment sync on a course section must carry `expected_section_version`, likewise non-optional, whose value must equal the section's current `version`. A sync whose `expected_section_version` no longer matches — because a prior sync already advanced the section's version — is rejected with `ERR_STALE_VERSION` (HTTP 412): the registrar feed is acting on a stale view of the section.

No other endpoint in the system accepts or requires a version field.

### 2.6. Monetary Values, Credits, and Rounding Discipline

Two kinds of quantity flow through the system, each with its own precision contract. Money is always represented as integer cents — never floating-point dollars — in fields such as `comp_budget_cents`, `comp_budget_spent_cents`, `overload_comp_rate_cents`, `late_cancel_stipend_cents`, `flat_release_rate_cents`, `base_salary_cents`, `stipend_cents`, `comp_cents`, and `buyout_value_cents`. Computed monetary values are rounded half-up to whole cents. Workload credits are decimal numbers carried to exactly 2 decimal places, rounded half-up; the assignment credit formula pins its rounding order — each of the three credit components is individually rounded to 2 decimal places first, and only then are the rounded components summed — so an implementation that rounds after summing will diverge. All list and detail responses render credits as numbers with at most 2 decimal places.

### 2.7. The Logical Clock

The system never consults wall-clock time for business rules. A logical clock, settable only by a `SystemAdmin` operator through an administrative capability that accepts a `to_iso8601` instant, supplies the current date and time for every time-dependent rule in this document: qualification expiry, the late-reassignment notice window, and census gating. At server startup, before any clock-set call, the logical clock is exactly `2026-08-01T00:00:00Z`. Time-dependent behaviors triggered by a clock advance (notably lazy qualification expiry) become observable on subsequent reads and validations.

### 2.8. Reference Resolution and Validation Ordering

Every write request passes through a fixed validation cascade, and the ordering matters because earlier failures mask later ones. The cascade runs in this order:

1. **Authentication context.** The headers `X-User-ID` and `X-User-Role` are validated first; failures surface as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission, then ownership, then segregation of duties.** Role gating for the endpoint (and for the requested `to_state` on shared transition endpoints) surfaces as `ERR_INSUFFICIENT_PERMISSIONS`. On the assignment transition endpoint when the target is `CONFIRMED` or `DECLINED`, the faculty ownership check surfaces as `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`. On the overload transition endpoint when the target is `DEAN_APPROVED`, the segregation-of-duties check surfaces as `ERR_SEGREGATION_OF_DUTIES`.
3. **Request shape.** Missing required fields, type mismatches, invalid enum members, out-of-range scalars (for example `credits_released` exceeding the faculty member's contractual load, or `credits_released` not greater than zero), a section `end_minute` that is not strictly greater than its `start_minute`, minutes outside the range 0 through 1439, a negative `enrolled_count`, a grant `end_date` earlier than its `start_date`, or a term whose `census_date` precedes its `start_date` — these surface as `ERR_VALIDATION` or, for the section time-window failures specifically, `ERR_INVALID_TIME_RANGE`.
4. **Existence of referenced resources.** Path identifiers are resolved left to right — the API's path parameters are `termId`, `facultyId`, `courseId`, `qualificationId`, `sectionId`, `assignmentId`, `grantId`, `requestId`, and `loadSheetId` — then body foreign keys in their declared input order (`term_id` before `section_id`, `faculty_id` before `course_id`, and so on). The first missing reference surfaces the corresponding not-found error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or `ERR_LOAD_SHEET_NOT_FOUND`.
5. **State preconditions, then OCC.** State-gating failures surface as one of the 409-family state errors (`ERR_INVALID_TERM_STATE`, `ERR_INVALID_SECTION_TRANSITION`, `ERR_SECTION_NOT_ASSIGNABLE`, `ERR_INVALID_ASSIGNMENT_TRANSITION`, `ERR_INVALID_GRANT_TRANSITION`, `ERR_INVALID_OVERLOAD_TRANSITION`, `ERR_INVALID_FACULTY_STATE`, `ERR_INVALID_QUALIFICATION_TRANSITION`, `ERR_CENSUS_NOT_REACHED`, `ERR_UNSTAFFED_SECTIONS`, `ERR_UNCOVERED_OVERLOAD`, `ERR_DEAN_OVERRIDE_REQUIRED`), and immediately after them the two OCC checks surface as `ERR_STALE_VERSION`.
6. **Qualification.** On assignment creation only, the absence of an `ACTIVE` qualification for the faculty–course pair surfaces as `ERR_NOT_QUALIFIED_FOR_COURSE`.
7. **Temporal overlaps.** Meeting-time conflicts on assignment creation surface as `ERR_MEETING_TIME_CONFLICT`; release-period overlaps on grant creation surface as `ERR_RELEASE_PERIOD_OVERLAP`.
8. **Uniqueness and business constraints.** Duplicate and capacity failures surface as `ERR_DUPLICATE_TERM_CODE`, `ERR_DUPLICATE_FACULTY_EMAIL`, `ERR_DUPLICATE_SECTION`, `ERR_DUPLICATE_QUALIFICATION`, `ERR_MODALITY_NOT_ALLOWED`, `ERR_ENROLLMENT_EXCEEDS_CAP`, `ERR_UNION_OVERLOAD_CAP_EXCEEDED`, `ERR_SECTION_ALREADY_ASSIGNED`, `ERR_NO_OVERLOAD`, or `ERR_OVERLOAD_REQUEST_EXISTS`. Note that within this tier, duplicate and conflict errors carry HTTP 409, while `ERR_MODALITY_NOT_ALLOWED`, `ERR_ENROLLMENT_EXCEEDS_CAP`, `ERR_UNION_OVERLOAD_CAP_EXCEEDED`, and `ERR_NO_OVERLOAD` carry HTTP 422.
9. **Fiscal budget.** Last of all, the compensation-budget check surfaces as `ERR_COMP_BUDGET_EXCEEDED`.

### 2.9. The Term Compensation Ledger

Every workload term carries a compensation budget, `comp_budget_cents`, funding two kinds of outflow: dean-approved overload compensation and late-cancellation stipends. The term tracks actual outflow in `comp_budget_spent_cents`, which starts at 0 when the term is created. The system maintains a hard invariant: at every moment, `comp_budget_spent_cents` equals the sum of `comp_cents` over all of the term's overload requests in `DEAN_APPROVED` status, plus the sum of `stipend_cents` over all of the term's assignments. The remaining budget is simply `comp_budget_cents` minus `comp_budget_spent_cents`. Any operation that would push spending above the budget — approving an overload request, or charging a late stipend through a chair rescind or a late section cancellation — is rejected with `ERR_COMP_BUDGET_EXCEEDED` before any money moves.

### 2.10. The Overload Auto-Withdraw Rule

Whenever a load sheet is recomputed — after any assignment event, any grant approval or revocation, census close, or an edit to a faculty member's contractual load — the system applies a standing rule: if that sheet's `overload_credits` has become 0, then every overload request for the same term-and-faculty pair that is currently in `SUBMITTED` or `CHAIR_ENDORSED` status automatically transitions to `WITHDRAWN`. This is the intended serialization point between workload reduction and compensation approval: a chair or dean acting on a stale overload request after the underlying overload evaporated will find it already withdrawn.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Term and Its Workload Policy

A `DepartmentChair` begins the academic cycle by creating a **workload term**. The chair supplies a `term_code` (unique across all terms, for example `2026-FA`), a display `title`, the `start_date` marking the first day of classes as an ISO date, and the `census_date` at which enrollment is frozen for final workload accounting; the census date must not precede the start date, and a violation is a shape-level `ERR_VALIDATION`. The term's compensation budget arrives as `comp_budget_cents`, an integer-cents amount that caps the term's total overload pay plus late-cancel stipends. A term is always born in `DRAFT` status with `comp_budget_spent_cents` at 0.

The term record also carries the department's workload policy as inline fields, all of which have defaults when omitted at creation: `base_teaching_credits` (default 12) names the department-standard full-time teaching load per term; the credit-equivalency multipliers `lecture_multiplier` (default 1.0), `lab_multiplier` (default 0.75), and `seminar_multiplier` (default 1.25) convert catalog credits into workload credits by course type; `online_premium_credits` (default 0.5) is a flat credit premium added for online sections; `large_class_threshold` (default 40) and `large_class_bonus_credits` (default 1.0) together grant a flat bonus when a section's enrollment reaches the threshold; `overload_comp_rate_cents` (default 150000, i.e., $1,500.00 per overload credit) prices extra compensation; `union_max_overload_credits` (default 6) caps overload for union-covered faculty; `reassignment_notice_days` (default 14) defines the late window for rescinds and cancellations; `late_cancel_stipend_cents` (default 100000, i.e., $1,000.00) is the per-assignment stipend for late cancellations; and `flat_release_rate_cents` (default 80000, i.e., $800.00 per released credit) prices administrative and sabbatical buyouts.

While the term remains in `DRAFT`, the chair may revise the policy — `title`, `census_date`, `base_teaching_credits`, `comp_budget_cents`, any of the equivalency multipliers and premiums, the overload rate and union cap, the notice window, the stipend, and the flat release rate — through a policy edit that must carry `expected_term_version` per §2.5. A duplicate `term_code` anywhere in the system is rejected with `ERR_DUPLICATE_TERM_CODE`.

The term lifecycle then walks a gated corridor. From `DRAFT` the chair opens the term, moving it to `OPEN` and unlocking assignment writes. From `OPEN` the chair may lock it to `LOCKED`, freezing assignment creation while enrollment settles; a locked term can be unlocked back to `OPEN`, and this cyclic reopening re-enables assignment and section writes. From `LOCKED` — and only from `LOCKED` — the chair may publish the term, moving it to the terminal `PUBLISHED` state, at which point the schedule becomes read-only. Publishing is gated by two preconditions evaluated in order: first, no section of the term may remain in `PROPOSED` or `SCHEDULED` status, else the publish is rejected with `ERR_UNSTAFFED_SECTIONS`; second, every load sheet of the term whose `overload_credits` exceeds 0 must have a `DEAN_APPROVED` overload request for the same term-and-faculty pair, else the publish is rejected with `ERR_UNCOVERED_OVERLOAD`. Any other term transition request — for example opening a term that is already `OPEN`, or publishing from `OPEN` — is rejected with `ERR_INVALID_TERM_STATE`.

### 3.2. Faculty Roster, Course Catalog, and Qualifications

The chair maintains the faculty roster. Creating a faculty member takes a `full_name`, an `email` that must be unique across all faculty (duplicates are rejected with `ERR_DUPLICATE_FACULTY_EMAIL`), a `rank` drawn from `ADJUNCT`, `LECTURER`, `ASSISTANT_PROFESSOR`, `ASSOCIATE_PROFESSOR`, or `PROFESSOR`, and the annual `base_salary_cents` in integer cents — the salary that later drives prorated research buyouts. Two policy-flavored fields default when omitted: `is_union_covered` (default true) marks whether the union overload cap applies to this person, and `base_load_credits` (default 12) is the contractual per-term teaching load. The chair may also record `preferred_course_ids`, the list of course ids this faculty member prefers to teach; the list defaults to empty and drives the `matches_preference` flag computed on each new assignment. A faculty member is born `ACTIVE`.

Faculty availability is itself a lifecycle. A chair may place an `ACTIVE` faculty member `ON_LEAVE`, and may later return them to `ACTIVE`; the cyclic return does **not** restore any assignments that were washed out when the leave began. A chair may also move a faculty member to the terminal `SEPARATED` state from either `ACTIVE` or `ON_LEAVE`. A status edit to a state not reachable from the current state is rejected with `ERR_INVALID_FACULTY_STATE`. The same faculty edit surface also accepts `base_load_credits` and `preferred_course_ids` changes; editing the contractual load forces a recompute of that faculty member's load sheets.

The leave and separation events carry a heavy cascade, and it applies identically whether the destination is `ON_LEAVE` or `SEPARATED`. Every `PROPOSED` assignment belonging to the faculty member transitions to `WITHDRAWN` with no stipend. Every `CONFIRMED` assignment transitions to `RESCINDED`, but its `stipend_cents` stays 0 — a leave-driven rescind is not a late chair rescind and never draws the stipend. Each section left without any remaining `CONFIRMED` assignment demotes from `STAFFED` back to `SCHEDULED`. Every affected load sheet is then recomputed, and the overload auto-withdraw rule of §2.10 applies to any sheet whose overload evaporated.

The course catalog is flat: the chair creates a course with a unique `course_code` (such as `CS-301`), a `title`, a `course_type` of `LECTURE`, `LAB`, or `SEMINAR`, the catalog `base_credits` before any equivalency multiplier, a `default_enrollment_cap` that new sections inherit, and `allowed_modalities`, a non-empty subset of `IN_PERSON`, `ONLINE`, and `HYBRID`.

Qualifications bind the roster to the catalog. The chair grants a qualification by naming a `faculty_id`, a `course_id`, and an `expires_on` ISO date; the qualification is born `ACTIVE`. At most one qualification per faculty-and-course pair may be `ACTIVE` at a time — a second grant for the same pair is rejected with `ERR_DUPLICATE_QUALIFICATION`. A chair may revoke a qualification by setting its status to `REVOKED`; attempting any other status value, or patching a qualification that is already terminal, is rejected with `ERR_INVALID_QUALIFICATION_TRANSITION`. Expiry is lazy and clock-driven: whenever a qualification is read or consulted during validation while the logical clock's date is strictly later than its `expires_on`, the system treats and reports it as `EXPIRED`. The boundary is strict — on `expires_on` itself the qualification is still `ACTIVE`; it lapses only the day after.

### 3.3. Building the Section Schedule

Within a term that is still `DRAFT` or `OPEN`, the chair creates course sections. Creating a section takes the `term_id` and `course_id` it belongs to, a `section_number` (unique within its term-and-course pair, e.g. `01`; a collision is rejected with `ERR_DUPLICATE_SECTION`), a `modality` that must be a member of the course's `allowed_modalities` (else `ERR_MODALITY_NOT_ALLOWED`), a weekly `meeting_day` drawn from `MON`, `TUE`, `WED`, `THU`, or `FRI`, and a meeting window expressed as `start_minute` and `end_minute`, minutes since midnight in the range 0 through 1439, where the end must be strictly later than the start (violations surface as `ERR_INVALID_TIME_RANGE`). An explicit `enrollment_cap` may be supplied; when omitted, the cap defaults from the course's `default_enrollment_cap`. A section is born `PROPOSED` with `enrolled_count` 0 and `is_late_cancelled` false. Attempting to create a section while its term is `LOCKED` or `PUBLISHED` is rejected with `ERR_INVALID_TERM_STATE`.

The chair schedules a proposed section, moving it from `PROPOSED` to `SCHEDULED`; this transition is permitted only while the term is in `DRAFT` or `OPEN`, and otherwise fails with `ERR_INVALID_TERM_STATE`. From there the section's staffing state is driven entirely by its child assignments, with no direct chair action: the moment an assignment on the section becomes `CONFIRMED`, the section rises from `SCHEDULED` to `STAFFED`, and the moment the last `CONFIRMED` assignment leaves `CONFIRMED` — by rescind, cancellation, or cascade — the section demotes back to `SCHEDULED`. This cyclic `SCHEDULED` ↔ `STAFFED` oscillation is automatic. Direct transitions the state machine does not define — such as jumping a section straight from `PROPOSED` to `STAFFED`, or acting on a `CANCELLED` section — are rejected with `ERR_INVALID_SECTION_TRANSITION`.

Enrollment arrives exclusively through the registrar's enrollment-sync capability, exercised by a `Registrar` operator. A sync carries the new `enrolled_count` and the OCC field `expected_section_version` described in §2.5. The sync rejects an `enrolled_count` above the section's `enrollment_cap` with `ERR_ENROLLMENT_EXCEEDS_CAP` and a negative count with `ERR_VALIDATION`, and it increments the section's `version` on success. Syncing enrollment never re-prices existing assignments — provisional credits are a snapshot, and only the census close described in §3.7 refreshes them.

### 3.4. Assigning Faculty to Sections

The core act of the system is the chair proposing an **assignment**: a payload naming a `section_id` and a `faculty_id`. Assignment creation is permitted only while the term is `OPEN` — not `DRAFT`, not `LOCKED`, not `PUBLISHED`; the wrong term state surfaces `ERR_INVALID_TERM_STATE`. The target section must be in `SCHEDULED` or `STAFFED` status, else the create is rejected with `ERR_SECTION_NOT_ASSIGNABLE`. A section may carry at most one non-terminal assignment — one in `PROPOSED` or `CONFIRMED` — so proposing onto a section that already has a live assignment is rejected with `ERR_SECTION_ALREADY_ASSIGNED`.

The proposal then runs a gauntlet of business checks, in the fixed order of §2.8. First, qualification: an `ACTIVE` qualification must exist pairing this `faculty_id` with the section's course; a qualification that is missing, `REVOKED`, or lazily `EXPIRED` fails the check and the create is rejected with `ERR_NOT_QUALIFIED_FOR_COURSE`. Second, the schedule-overlap check: for the candidate section and every other section holding a non-terminal assignment (`PROPOSED` or `CONFIRMED`) for the same faculty member in the same term, if the two sections share a `meeting_day` and their meeting windows overlap, the create is rejected with `ERR_MEETING_TIME_CONFLICT`. The overlap test uses half-open interval semantics — the candidate overlaps another section only when the candidate's `start_minute` is before the other's `end_minute` and the other's `start_minute` is before the candidate's `end_minute` — so back-to-back meetings, where one section's `start_minute` equals the other's `end_minute`, do **not** conflict.

Third, the union overload cap, which applies only when the faculty member's `is_union_covered` is true — non-union faculty skip this check entirely. The system projects the faculty member's teaching load as the current load sheet's `teaching_credits` plus the new assignment's provisional `credit_units`, computes the projected overload as the amount by which that projection exceeds the sheet's `effective_obligation_credits` (floored at 0), and rejects the create with `ERR_UNION_OVERLOAD_CAP_EXCEEDED` when the projected overload is strictly greater than the term's `union_max_overload_credits`. Landing exactly on the cap is allowed.

A successful create produces an assignment in `PROPOSED` status whose `term_id` is copied from the section's term. Two values are snapshotted at creation and never recomputed by later enrollment drift: `credit_units`, the provisional workload credits, and `matches_preference`, which is true exactly when the section's `course_id` appears in the faculty member's `preferred_course_ids` at creation time. The `final_credit_units` field starts null and stays null until census close; `stipend_cents` starts at 0.

The provisional credit formula evaluates the section's course and the term's policy. A type multiplier is selected by the course's `course_type` — the term's `lecture_multiplier` for a `LECTURE` course, `lab_multiplier` for a `LAB` course, `seminar_multiplier` for a `SEMINAR` course. The base component is the course's `base_credits` multiplied by that type multiplier, rounded half-up to 2 decimal places. The online component is the term's `online_premium_credits` rounded half-up to 2 decimal places when the section's `modality` is `ONLINE`, and 0 otherwise. The large-class component is the term's `large_class_bonus_credits` rounded half-up to 2 decimal places when the section's current `enrolled_count` is at least the term's `large_class_threshold`, and 0 otherwise. The provisional `credit_units` is the sum of the three individually rounded components — the rounding happens per component, before summation, never after.

Every assignment event touches the faculty member's **load sheet**. A load sheet exists per term-and-faculty pair and is auto-created by the first assignment — or the first release-time grant — for that pair; there is no direct create or update surface, only reads. On every recompute, the sheet's `teaching_credits` is the sum over the pair's assignments in `PROPOSED` or `CONFIRMED` status — terminal assignments in `DECLINED`, `WITHDRAWN`, `RESCINDED`, or `CANCELLED` are excluded — of each assignment's credits, taking `final_credit_units` where it has been populated and `credit_units` otherwise. The sheet's `release_credits` is the sum of `credits_released` over the pair's grants in `APPROVED` status — grants in `REQUESTED`, `DENIED`, or `REVOKED` contribute nothing. From these, `effective_obligation_credits` is the faculty member's `base_load_credits` minus `release_credits`, floored at 0; `overload_credits` is `teaching_credits` minus `effective_obligation_credits`, floored at 0; and `underload_credits` is `effective_obligation_credits` minus `teaching_credits`, floored at 0. After every recompute, the overload auto-withdraw rule of §2.10 fires.

### 3.5. Consent, Withdrawal, and Rescission of Assignments

An assignment in `PROPOSED` awaits the faculty member's consent. The named faculty member — and only that person, verified by comparing the caller's `X-User-ID` to the assignment's `faculty_id` (mismatches fail with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`) — may confirm it, moving the assignment to `CONFIRMED`, or decline it, moving it to the terminal `DECLINED` state. Confirming additionally requires the faculty member's own status to be `ACTIVE`; confirming while `ON_LEAVE` or `SEPARATED` is rejected with `ERR_INVALID_FACULTY_STATE`. The first confirmation on a section bubbles up: the section rises from `SCHEDULED` to `STAFFED`. Declining removes the credit from the load sheet, which is recomputed. Any transition from a state the machine does not allow — including any action on a terminal `DECLINED`, `WITHDRAWN`, `RESCINDED`, or `CANCELLED` assignment — is rejected with `ERR_INVALID_ASSIGNMENT_TRANSITION`.

The chair holds the two corrective levers. Withdrawing works only from `PROPOSED` and moves the assignment to terminal `WITHDRAWN`, recomputing the load sheet with the credit removed; the system also uses `WITHDRAWN` as the cascade target when a section cancel or a faculty leave/separation washes out a still-`PROPOSED` assignment. Rescinding works only from `CONFIRMED` and moves the assignment to terminal `RESCINDED`. Rescission is forbidden once the term is `PUBLISHED` — the attempt is rejected with `ERR_INVALID_TERM_STATE` — and it carries the late-stipend machinery: when the logical clock sits strictly fewer than the term's `reassignment_notice_days` days before the term's `start_date`, or past it, the rescind is late. The boundary is pinned exactly: exactly `reassignment_notice_days` days before `start_date` is **not** late, while one day closer is late. A late rescind first checks the budget — the term's `comp_budget_spent_cents` plus `late_cancel_stipend_cents` must not exceed `comp_budget_cents`, else the rescind is rejected with `ERR_COMP_BUDGET_EXCEEDED` — then sets the assignment's `stipend_cents` to the term's `late_cancel_stipend_cents` and adds that amount to `comp_budget_spent_cents`. Either way, late or not, the rescind recomputes the load sheet, demotes the section from `STAFFED` to `SCHEDULED` when no other `CONFIRMED` assignment remains on it, and applies the overload auto-withdraw rule.

### 3.6. Cancelling Sections and the Late-Cancel Cascade

A chair may cancel a section from any of `PROPOSED`, `SCHEDULED`, or `STAFFED`; `CANCELLED` is terminal. Cancelling while the term is `PUBLISHED` is possible only with dean sign-off — the transition payload must carry `dean_override` set to true, and its absence is rejected with `ERR_DEAN_OVERRIDE_REQUIRED`.

Cancelling a `PROPOSED` section is quiet: there are no confirmed commitments to unwind. Cancelling a `SCHEDULED` section adds one bookkeeping step — the section's `is_late_cancelled` flag is set to true exactly when the logical clock is strictly fewer than `reassignment_notice_days` days before the term's `start_date`, or past it; the same strict boundary as the rescind rule.

Cancelling a `STAFFED` section fires the full cascade. The lateness check runs first, setting `is_late_cancelled` as above. When the cancel is late and at least one `CONFIRMED` assignment exists on the section, the budget is validated up front: the term's `comp_budget_spent_cents` plus `late_cancel_stipend_cents` multiplied by the number of `CONFIRMED` assignments on the section must not exceed `comp_budget_cents`, else the entire cancel is rejected with `ERR_COMP_BUDGET_EXCEEDED` and nothing moves. On success, every `CONFIRMED` assignment on the section transitions to `CANCELLED` — and when the cancel is late, each one has its `stipend_cents` set to the term's `late_cancel_stipend_cents` with the sum added to `comp_budget_spent_cents`. Every `PROPOSED` assignment on the section transitions to `WITHDRAWN` with no stipend. Each affected faculty member's load sheet is recomputed as teaching credits drop, and for each affected faculty member whose `overload_credits` thereby became 0, every non-terminal overload request for that term-and-faculty pair auto-withdraws per §2.10.

### 3.7. Census Close and Final Credit Reconciliation

Enrollment drifts all term long through registrar syncs, but workload accounting needs a fixed point. The chair closes census on a term once the logical clock has reached the term's `census_date`; calling it earlier is rejected with `ERR_CENSUS_NOT_REACHED`, and calling it while the term is still in `DRAFT` is rejected with `ERR_INVALID_TERM_STATE` — the checkpoint is available on `OPEN`, `LOCKED`, and `PUBLISHED` terms alike and is not itself a state transition of the term.

The close performs three steps. First, for every `CONFIRMED` assignment in the term, the exact credit formula of §3.4 is re-evaluated using the section's **current** `enrolled_count`, and the result is stored in the assignment's `final_credit_units`. Second, every load sheet in the term is recomputed, with populated `final_credit_units` taking precedence over provisional `credit_units` — so a class that grew past the large-class threshold between proposal and census now pays the bonus, and one that shrank below it loses it. Third, the overload auto-withdraw rule of §2.10 runs across the term, withdrawing any overload request whose underlying overload disappeared at census.

### 3.8. Release Time: Buyouts, Approval, and Revocation

Faculty buy their way out of teaching through release-time grants, requested by the chair with a `term_id`, a `faculty_id`, a `grant_type` of `RESEARCH_BUYOUT`, `ADMINISTRATIVE`, or `SABBATICAL`, the number of `credits_released`, and a release period bounded by `start_date` and `end_date`, both ISO dates on a **closed** interval, where the end must not precede the start. The credits released must be greater than 0 and no more than the faculty member's `base_load_credits`; a violation of either bound is a shape-level `ERR_VALIDATION`. A grant is born in `REQUESTED` status, and creating one auto-creates the pair's load sheet if none exists yet.

Release periods for the same term-and-faculty pair must not touch. When a grant is created, it is compared against every other grant of the same pair in `REQUESTED` or `APPROVED` status, using closed-interval semantics: the candidate overlaps another grant whenever the candidate's `start_date` is on or before the other's `end_date` and the other's `start_date` is on or before the candidate's `end_date`. Because the interval is closed, two grants sharing even a single calendar day — one ending the day the other begins — **do** overlap, and the create is rejected with `ERR_RELEASE_PERIOD_OVERLAP`. This is deliberately stricter than the half-open meeting-time rule of §3.4, where adjacency is allowed.

The dean's office decides. From `REQUESTED`, a `DeanOffice` operator may approve or deny the grant; any other from-state for these targets is rejected with `ERR_INVALID_GRANT_TRANSITION`. Approval prices the buyout into `buyout_value_cents` using one of two variants. For a `RESEARCH_BUYOUT` grant, the salary-prorate variant applies: the faculty member's `base_salary_cents` is multiplied by `credits_released` and divided by the product of the faculty member's `base_load_credits` and two — two terms per year — with the result rounded half-up to whole cents. For an `ADMINISTRATIVE` or `SABBATICAL` grant, the flat-rate variant applies: `credits_released` is multiplied by the term's `flat_release_rate_cents`, rounded half-up to whole cents. For identical `credits_released`, the two variants generally produce different values. Approval then credits the load sheet — auto-created if absent — by adding `credits_released` to `release_credits`, recomputing the obligation and overload figures, and applying the overload auto-withdraw rule. Denial moves the grant to the terminal `DENIED` state with no side effects.

An approved grant can later be revoked, by either a `DepartmentChair` or a `DeanOffice` operator, moving it from `APPROVED` to the terminal `REVOKED` state. Revocation compensates the load sheet: `credits_released` is subtracted from `release_credits`, and the overload and underload figures are recomputed. The recorded `buyout_value_cents` remains on the grant for audit even though the release credit is returned.

### 3.9. Overload Compensation: Endorsement, Approval, and the Negotiation Loop

When a faculty member's confirmed-plus-proposed teaching exceeds their effective obligation, the chair may seek extra compensation by submitting an **overload request** naming a `term_id` and a `faculty_id`. Submission requires a live overload: the pair's load sheet must exist with `overload_credits` greater than 0, else the submission is rejected with `ERR_NO_OVERLOAD`. Only one non-terminal request may exist per term-and-faculty pair; a second submission while one is still in flight is rejected with `ERR_OVERLOAD_REQUEST_EXISTS`. A successful submission snapshots two computed values onto the request: `overload_credits`, copied from the load sheet at submission time, and `comp_cents`, the product of that overload and the term's `overload_comp_rate_cents`, rounded half-up to whole cents. The request is born `SUBMITTED`.

The approval chain enforces segregation of duties. A chair endorses a `SUBMITTED` request, moving it to `CHAIR_ENDORSED` and recording the endorsing chair's `X-User-ID` in `endorsed_by_user_id`. From `CHAIR_ENDORSED`, a `DeanOffice` operator may approve or deny. Approval runs two preconditions in order: the approver's `X-User-ID` must differ from `endorsed_by_user_id` — a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` — and the term's `comp_budget_spent_cents` plus the request's `comp_cents` must not exceed `comp_budget_cents`, else the approval is rejected with `ERR_COMP_BUDGET_EXCEEDED`. A successful approval adds `comp_cents` to `comp_budget_spent_cents` and lands the request in the terminal `DEAN_APPROVED` state. Denial lands it in `DENIED`.

The negotiation loop is cyclic: a chair may resubmit a `DENIED` request, moving it back to `SUBMITTED` — resubmission is a transition to `SUBMITTED`, not a repeat endorsement — and the act of resubmitting recomputes both snapshot fields from the **current** load sheet, so `overload_credits` and `comp_cents` reflect the workload as it now stands; if the current sheet shows no overload, the resubmit is rejected with `ERR_NO_OVERLOAD`. A chair may also withdraw a request from either `SUBMITTED` or `CHAIR_ENDORSED`, landing it in the terminal `WITHDRAWN` state, and the system does the same automatically whenever §2.10's rule fires. Any transition not described here — acting on a terminal `DEAN_APPROVED`, `DENIED`, or `WITHDRAWN` request, or reaching for a target the from-state does not support — is rejected with `ERR_INVALID_OVERLOAD_TRANSITION`.

### 3.10. Department Load Balancing and Reporting

At any point, any role may read the department's load summary for a term, a report designed for balancing work across the faculty. The summary aggregates over every load sheet of the term whose faculty member is not `SEPARATED`: `total_teaching_credits` is the sum of the sheets' `teaching_credits`; `overloaded_faculty_count` counts sheets whose `overload_credits` exceeds 0; `underloaded_faculty_count` counts sheets whose `underload_credits` exceeds 0; and `fairness_spread_credits` is the difference between the largest and smallest `teaching_credits` across those sheets, or 0 when the term has no qualifying sheets at all. The fiscal picture rides along as `comp_budget_spent_cents` and `comp_budget_remaining_cents`, per the ledger invariant of §2.9. Preference satisfaction is tallied across the term's assignments in `PROPOSED` or `CONFIRMED` status: `preference_satisfied_count` counts those whose `matches_preference` is true, and `preference_unsatisfied_count` counts the rest. The summary's credit figures render at 2 decimal places; its counts and cent figures are integers.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources return a `201 Created` status code. Operations that modify an existing resource — transitions, policy edits, enrollment syncs, status patches — return a `200 OK` status code. All endpoints are mounted at the service root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/workload-terms` | Create a term with inline workload policy fields (defaults applied when omitted) | DepartmentChair |
| GET | `/workload-terms` | List terms, optionally filtered by `status` | Any |
| GET | `/workload-terms/{termId}` | Get one term | Any |
| PATCH | `/workload-terms/{termId}` | Edit policy/equivalency fields while `DRAFT`; OCC via `expected_term_version` | DepartmentChair |
| POST | `/workload-terms/{termId}/transition` | Term lifecycle: `OPEN` (from `DRAFT` or `LOCKED`), `LOCKED` (from `OPEN`), `PUBLISHED` (from `LOCKED`; publish preconditions apply) | DepartmentChair |
| POST | `/workload-terms/{termId}/close-census` | Census checkpoint: freeze `final_credit_units` for all `CONFIRMED` assignments, recompute all load sheets, apply overload auto-withdraw | DepartmentChair |
| GET | `/workload-terms/{termId}/load-summary` | Department load balancing report | Any |
| POST | `/faculty-members` | Create a faculty member | DepartmentChair |
| GET | `/faculty-members` | List faculty, optionally filtered by `status` and `rank` | Any |
| GET | `/faculty-members/{facultyId}` | Get one faculty member | Any |
| PATCH | `/faculty-members/{facultyId}` | Status transitions (`ON_LEAVE`/`ACTIVE`/`SEPARATED`) and `base_load_credits` / `preferred_course_ids` edits | DepartmentChair |
| POST | `/courses` | Create a course | DepartmentChair |
| GET | `/courses` | List courses, optionally filtered by `course_type` | Any |
| GET | `/courses/{courseId}` | Get one course | Any |
| POST | `/qualifications` | Grant a course qualification to a faculty member | DepartmentChair |
| GET | `/qualifications` | List qualifications, optionally filtered by `faculty_id`, `course_id`, and `status` | Any |
| GET | `/qualifications/{qualificationId}` | Get one qualification (lazy expiry applied) | Any |
| PATCH | `/qualifications/{qualificationId}` | Revoke a qualification | DepartmentChair |
| POST | `/course-sections` | Create a section in a `DRAFT` or `OPEN` term | DepartmentChair |
| GET | `/course-sections` | List sections, optionally filtered by `term_id`, `course_id`, and `status` | Any |
| GET | `/course-sections/{sectionId}` | Get one section | Any |
| POST | `/course-sections/{sectionId}/transition` | `SCHEDULED` (from `PROPOSED`) or `CANCELLED` (from `PROPOSED`/`SCHEDULED`/`STAFFED`; late/publish rules and cascades apply) | DepartmentChair |
| POST | `/course-sections/{sectionId}/enrollment-sync` | Registrar enrollment sync; OCC via `expected_section_version` | Registrar |
| POST | `/assignments` | Chair proposes a section assignment; computes provisional credits and auto-creates the load sheet | DepartmentChair |
| GET | `/assignments` | List assignments, optionally filtered by `term_id`, `section_id`, `faculty_id`, and `status` | Any |
| GET | `/assignments/{assignmentId}` | Get one assignment | Any |
| POST | `/assignments/{assignmentId}/transition` | `CONFIRMED`/`DECLINED` (faculty self), `WITHDRAWN` (chair, from `PROPOSED`), `RESCINDED` (chair, from `CONFIRMED`) | DepartmentChair, FacultyMember |
| POST | `/release-time-grants` | Request release time (research buyout / administrative / sabbatical) | DepartmentChair |
| GET | `/release-time-grants` | List grants, optionally filtered by `term_id`, `faculty_id`, and `status` | Any |
| GET | `/release-time-grants/{grantId}` | Get one grant | Any |
| POST | `/release-time-grants/{grantId}/transition` | `APPROVED`/`DENIED` (DeanOffice) or `REVOKED` (chair or DeanOffice, from `APPROVED`) | DepartmentChair, DeanOffice |
| POST | `/overload-requests` | Submit an overload approval request; snapshots current overload and compensation | DepartmentChair |
| GET | `/overload-requests` | List overload requests, optionally filtered by `term_id`, `faculty_id`, and `status` | Any |
| GET | `/overload-requests/{requestId}` | Get one overload request | Any |
| POST | `/overload-requests/{requestId}/transition` | `CHAIR_ENDORSED` (chair), `DEAN_APPROVED`/`DENIED` (DeanOffice), `SUBMITTED` (chair, resubmit from `DENIED`), `WITHDRAWN` (chair) | DepartmentChair, DeanOffice |
| GET | `/load-sheets` | List load sheets, optionally filtered by `term_id` and `faculty_id` | Any |
| GET | `/load-sheets/{loadSheetId}` | Get one load sheet | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC); drives late-cancel windows, qualification expiry, and census gating | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_TERM_NOT_FOUND` | 404 Not Found |
| `ERR_FACULTY_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_QUALIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_OVERLOAD_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_SHEET_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_INVALID_TERM_STATE` | 409 Conflict |
| `ERR_INVALID_SECTION_TRANSITION` | 409 Conflict |
| `ERR_SECTION_NOT_ASSIGNABLE` | 409 Conflict |
| `ERR_INVALID_ASSIGNMENT_TRANSITION` | 409 Conflict |
| `ERR_INVALID_GRANT_TRANSITION` | 409 Conflict |
| `ERR_INVALID_OVERLOAD_TRANSITION` | 409 Conflict |
| `ERR_INVALID_FACULTY_STATE` | 409 Conflict |
| `ERR_INVALID_QUALIFICATION_TRANSITION` | 409 Conflict |
| `ERR_CENSUS_NOT_REACHED` | 409 Conflict |
| `ERR_UNSTAFFED_SECTIONS` | 409 Conflict |
| `ERR_UNCOVERED_OVERLOAD` | 409 Conflict |
| `ERR_DEAN_OVERRIDE_REQUIRED` | 409 Conflict |
| `ERR_NOT_QUALIFIED_FOR_COURSE` | 422 Unprocessable Entity |
| `ERR_MEETING_TIME_CONFLICT` | 409 Conflict |
| `ERR_RELEASE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_TERM_CODE` | 409 Conflict |
| `ERR_DUPLICATE_FACULTY_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_SECTION` | 409 Conflict |
| `ERR_DUPLICATE_QUALIFICATION` | 409 Conflict |
| `ERR_MODALITY_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_UNION_OVERLOAD_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SECTION_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_NO_OVERLOAD` | 422 Unprocessable Entity |
| `ERR_OVERLOAD_REQUEST_EXISTS` | 409 Conflict |
| `ERR_COMP_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
