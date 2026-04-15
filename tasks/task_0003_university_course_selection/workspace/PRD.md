# Course Selection API — Product Requirements Document

## 1. Introduction

Every semester, thousands of students compete for limited seats in popular courses, navigating a web of prerequisites, schedule conflicts, and credit-hour restrictions — often under tight registration deadlines. The Course Selection API addresses this challenge by providing a centralized system that manages the complete enrollment lifecycle: from semester planning and course catalog setup through real-time seat allocation, waitlist management, and final enrollment lockdown. The system must enforce a directed acyclic graph of prerequisite dependencies, guard against schedule overlaps down to the minute, and respect per-student credit ceilings that vary by academic standing.

Three distinct stakeholder perspectives converge on the platform. Registrars orchestrate the academic calendar — opening and closing registration windows, granting cross-departmental permissions, and overriding credit limits for honors students. Professors curate their sections, approve or reject enrollment requests that require sign-off, and manage cross-department access for their own departments. Students, the primary consumers, request enrollment in sections, monitor waitlist positions, and drop courses they no longer intend to complete. Balancing these roles while preserving atomicity of seat counts and waitlist ordering under concurrent access is a core architectural concern.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Authentication relies on a combination of identity and role headers attached to every request. Exactly one identity header must be present: `X-Student-Number`, `X-Instructor-Id`, or `X-Registrar-Id`, corresponding to the caller's university identifier. In addition, the `X-Caller-Role` header must specify the caller's operational capacity. The system recognizes three named roles — `Student`, `Professor`, and `Registrar` — plus a pseudo-role `Any` that represents any authenticated caller for read-only catalog access. A request missing any required header or presenting an unrecognized role value is rejected with `ENROLLMENT_AUTH_MISSING`. When the supplied role lacks authorization for the requested operation, the system responds with `ENROLLMENT_ROLE_DENIED`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (2xx status codes) use the following JSON envelope:

```json
{
  "result": {
    "request_id": "csel_7f2a9b4e1d",
    "timestamp": "2026-09-01T08:15:32Z"
  },
  "kind": "single",
  "payload": {
    "id": "dept_3c8e1a",
    "dept_code": "CS",
    "dept_name": "Computer Science",
    "cross_dept_open": false
  }
}
```

For list endpoints, the envelope includes pagination metadata alongside the array payload:

```json
{
  "result": {
    "request_id": "csel_a91bc0de42",
    "timestamp": "2026-09-01T09:00:00Z"
  },
  "kind": "list",
  "payload": [ ],
  "page_size": 20,
  "page_token": null,
  "total_results": 57,
  "next_page_token": "eyJvZmYiOjIwfQ"
}
```

#### Standard Error Response Format

Error responses (4xx status codes) follow an analogous structure:

```json
{
  "result": {
    "request_id": "csel_ee3f17d5c0",
    "timestamp": "2026-09-01T09:05:11Z"
  },
  "kind": "error",
  "payload": {
    "code": "PREREQUISITE_NOT_MET",
    "detail": "Student has not completed CS-201, a transitive prerequisite for CS-401."
  }
}
```

Field semantics:

- `request_id` — a server-generated unique identifier prefixed with `csel_`, assigned to every request for traceability.
- `timestamp` — an ISO 8601 UTC timestamp recording when the server processed the request.
- `kind` — a type discriminator with three possible values: `"single"` for a single resource, `"list"` for a collection, and `"error"` for failure responses.
- `payload` — contains the business data: a resource object for `"single"`, an array of resource objects for `"list"`, or an error descriptor (with `code` and `detail`) for `"error"`.
- Pagination fields `page_size`, `page_token`, `total_results`, and `next_page_token` appear only in `"list"` responses. `next_page_token` is `null` when no further pages remain.

### 2.3. Pagination

List endpoints accept two query parameters for pagination. The `page_size` parameter controls how many items are returned per page; it defaults to **20**, with a minimum of **1** and a maximum of **50**. The `page_token` parameter is an opaque cursor for fetching subsequent pages.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include four metadata fields at the envelope level: `page_size`, `page_token`, `total_results`, and `next_page_token`.

### 2.4. Semester Lifecycle and Registration Phases

A semester progresses through four phases that gate all enrollment activity: `PLANNING`, `OPEN_ENROLLMENT`, `CLOSED_ENROLLMENT`, and `FINALIZED`. During `PLANNING`, the registrar populates the course catalog — departments, courses, sections, instructors, and students are set up, but no enrollment mutations are permitted. Transitioning to `OPEN_ENROLLMENT` requires that at least one department, one course, and one section exist within the semester; otherwise the transition is rejected with `SEMESTER_PHASE_INVALID`.

Once the semester is in `OPEN_ENROLLMENT`, students may request enrollment, professors may approve or reject, and drops are permitted. Closing enrollment triggers two cascade effects: all `PENDING_APPROVAL` enrollments are automatically rejected with the note "Registration period closed", and all `WAITLISTED` enrollments are automatically dropped with the same note. The registrar may briefly reopen enrollment from `CLOSED_ENROLLMENT` back to `OPEN_ENROLLMENT` for a late add/drop window.

Finalization is the terminal phase. Before a semester can transition from `CLOSED_ENROLLMENT` to `FINALIZED`, no `PENDING_APPROVAL` enrollments may remain — any lingering approvals must be resolved first. Once finalized, all enrollment records become immutable.

### 2.5. Hierarchical Path Validation and Nested Resources

The API enforces strict left-to-right validation for every path parameter in nested resource URLs. When a request targets a deeply nested endpoint such as `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments/{enrollmentId}`, the system validates each identifier sequentially: first the semester, then the department (confirming it belongs to that semester), then the course (confirming it belongs to that department), then the section, and finally the enrollment. The request is rejected with the 404 error corresponding to the first missing resource in the chain — `SEMESTER_UNKNOWN`, `DEPARTMENT_UNKNOWN`, `COURSE_UNKNOWN`, `SECTION_UNKNOWN`, or `ENROLLMENT_UNKNOWN` — before any business logic executes.

### 2.6. Common Resource Properties

All primary entities that carry `common_fields` — Semester, Department, Course, Section, Instructor, Student, Enrollment, and CrossDeptPermission — include a standard set of system-managed fields:

- `id` (string): A unique, system-generated identifier for the resource.
- `opened_on` (string): An ISO 8601 UTC timestamp indicating when the resource was created.
- `modified_on` (string): An ISO 8601 UTC timestamp updated whenever the resource's properties change, including changes to derived fields such as `seats_available` or `credits_enrolled`.
- `enrollment_seq` (integer): A monotonic counter incremented on every mutation, used for optimistic concurrency control on entities that track it.

Certain entities are append-only diagnostic or event records — specifically ScheduleConflict, WaitlistPromotion, and PrerequisiteGraph — and do not carry `opened_on`, `modified_on`, or `enrollment_seq`. These records are immutable after creation and serve as an audit trail.

### 2.7. Optimistic Concurrency Control

Enrollment mutations on a section are protected by the `enrollment_seq` field. Each section maintains its own `enrollment_seq` counter, which starts at 1 when the section is created and increments with every enrollment-related change. Clients may include the current `enrollment_seq` value in their request; if the provided value does not match the section's current counter, the request is rejected with `ENROLLMENT_CONFLICT`. When `enrollment_seq` is omitted from the request, the server processes the mutation without an OCC check. The enrollment record itself captures a snapshot of the section's `enrollment_seq` at the time of the last mutation, enabling clients to detect stale data.

### 2.8. Academic Standing and Credit Load Rules

Student credit ceilings vary by academic standing. Under standard load rules, a student in `GOOD` standing may enroll in up to 18 credit hours per semester (the default `max_credits` value). Students on `PROBATION` face a hard cap of 12 credit hours regardless of any higher value recorded on their profile. The registrar may override `max_credits` to allow up to 22 credit hours for honors students, but this override must be set on the student record before enrollment begins. Students whose `academic_standing` is `SUSPENDED` are barred from enrollment entirely — any attempt triggers `STUDENT_SUSPENDED`.

Credit load is computed as the sum of `credit_hours` for all courses where the student holds an enrollment in `ENROLLED` or `PENDING_APPROVAL` status. The derived field `credits_available` reflects how many additional credit hours the student may still claim.

### 2.9. Precision and Rounding

All computed integer fields — credit loads, seat counts, waitlist positions, overlap minutes, prerequisite chain depths — use exact integer arithmetic. No rounding is applied; all values are precise.

### 2.10. Schedule Conflict Detection

Time-based conflict detection operates at minute-level granularity. When evaluating a proposed section for a student, the system compares its `schedule_days` and time window (`schedule_start` to `schedule_end`, both in HH:MM 24-hour format) against every section in which the student is currently `ENROLLED`. Two sections conflict when they share at least one common day and their time intervals overlap — that is, when the proposed section's `schedule_start` is strictly before the existing section's `schedule_end` and the existing section's `schedule_start` is strictly before the proposed section's `schedule_end`. Even a single minute of overlap constitutes a conflict.

When the conflicting sections are in different buildings (different `location` values), a 10-minute travel buffer is applied: a section ending at 10:00 conflicts with a section starting before 10:10 in a different location. This buffer does not apply when both sections share the same location.

## 3. Business Logic & Workflows

### 3.1. Catalog Construction: Departments, Courses, and Sections

Before enrollment opens, the registrar assembles the academic catalog within a semester that is still in `PLANNING` phase. A department is created with a short `dept_code` (such as "CS" or "MATH"), a descriptive `dept_name`, and an optional `cross_dept_open` flag that defaults to `false`. When `cross_dept_open` is set to `true`, any student may enroll in that department's courses without needing an explicit cross-department permission.

Courses are added to a department by providing a `course_code`, a `title`, the number of `credit_hours` the course awards, and a `level` drawn from `INTRODUCTORY`, `INTERMEDIATE`, `ADVANCED`, or `GRADUATE`. A `min_gpa` threshold may be specified; when omitted it defaults to 0.0, imposing no GPA barrier. Each course may declare `prerequisite_ids` — a list of course IDs that students must have already completed — and `corequisite_ids` — courses that students must be taking concurrently or have previously completed. A course also carries a soft-delete flag `is_active`; when toggled to `false` by the registrar, no new sections may be created for it, and any attempt to do so is rejected with `COURSE_INACTIVE`.

Sections represent the schedulable instances of a course. When creating a section, the caller supplies a `section_number` (e.g., "001", "LAB-A"), the `instructor_id` of the teaching professor, a `capacity` ceiling, and an optional `waitlist_cap` that defaults to 10. The meeting pattern is defined by `schedule_days` (e.g., "MWF", "TR"), `schedule_start`, `schedule_end`, and a `location`. If the section requires professor approval before students can enroll, the `requires_approval` flag is set to `true`. Upon creation, `seats_enrolled` and `waitlist_count` initialize to 0, `seats_available` equals `capacity`, and `enrollment_seq` starts at 1.

### 3.2. Registering Participants: Instructors and Students

Instructors are registered within a semester by providing an `employee_number`, a `full_name`, and the `home_department_id` identifying their primary departmental affiliation. An optional `can_approve_cross_dept` flag, defaulting to `false`, determines whether the professor may approve enrollments from students outside their home department. If the referenced instructor does not exist, the system responds with `INSTRUCTOR_UNKNOWN`.

Students are similarly registered with a `student_number`, `full_name`, their `major_department_id`, an `academic_standing` that defaults to `GOOD`, a `cumulative_gpa` from prior semesters, and an optional `max_credits` (default 18). The registrar may also supply `completed_course_ids` — a transcript-derived list of courses the student has already passed. Upon registration, `credits_enrolled` is set to 0 and `credits_available` equals `max_credits`. If the referenced student does not exist in the semester, the system responds with `STUDENT_UNKNOWN`.

### 3.3. The Prerequisite Dependency Graph

Prerequisite relationships form a directed acyclic graph that the system evaluates transitively. When a course is created or its `prerequisite_ids` are updated, the system recomputes the prerequisite graph for every affected course in the semester. For a given course, the algorithm performs a depth-first traversal starting from the course and walking its prerequisite edges to build the transitive closure — the complete set of ancestor courses that must be completed. The result is stored as a `dependency_chain`: a topologically sorted list of all transitive prerequisites. The `depth` field records the longest path from the course to any root node (a course with no prerequisites of its own).

If the depth-first traversal revisits the originating course, a cycle has been detected. The `has_cycle` flag is set to `true`, and the operation that introduced the cycle is rejected with `PREREQUISITE_CYCLE_DETECTED`. This check fires both on course creation and when prerequisite lists are patched.

During enrollment, the system enforces the **strict chain** rule: every course in the `dependency_chain` must appear in the student's `completed_course_ids`. Failure to satisfy any transitive prerequisite results in `PREREQUISITE_NOT_MET`. For `corequisite_ids`, the rule is more lenient — a corequisite is satisfied if the course appears in `completed_course_ids` or if the student currently holds an `ENROLLED` status enrollment in any section of that course. A corequisite that is neither completed nor concurrently enrolled triggers `COREQUISITE_NOT_SATISFIED`.

### 3.4. Enrollment Request and Seat Allocation

When a student (or registrar acting on behalf of a student) submits an enrollment request, the system executes a validation cascade in strict priority order. The semester must be in `OPEN_ENROLLMENT` phase; otherwise the request is rejected with `REGISTRATION_NOT_OPEN`. The student's `academic_standing` must not be `SUSPENDED`. All transitive prerequisites must be satisfied, corequisites must be met, and the student's `cumulative_gpa` must meet or exceed the course's `min_gpa` — failing this last check triggers `GPA_BELOW_MINIMUM`.

Next, the system verifies that the student does not already hold an active enrollment — meaning an enrollment in `ENROLLED`, `PENDING_APPROVAL`, or `WAITLISTED` status — in another section of the same course. Attempting to double-enroll triggers `DUPLICATE_COURSE_ENROLLMENT`. Schedule conflict detection runs against all sections where the student is currently `ENROLLED`, as described in section 2.10; a conflict triggers `SCHEDULE_CONFLICT` and creates a ScheduleConflict record capturing the `student_id`, `section_a_id`, `section_b_id`, the `overlap_days`, and the `overlap_minutes`.

If the course's department differs from the student's `major_department_id`, the enrollment is flagged as cross-departmental and the `is_cross_dept` field is set to `true`. Cross-department enrollment requires either that the department's `cross_dept_open` flag is `true` or that the student holds an `ACTIVE` CrossDeptPermission for `target_department_id` matching the course's department. Without either, the request is rejected with `CROSS_DEPT_NOT_PERMITTED`. When a permission exists, its `courses_used` count must be strictly less than `max_courses`; exceeding this limit triggers `CROSS_DEPT_LIMIT_REACHED`.

Finally, the credit limit check ensures that `credits_enrolled` plus the course's `credit_hours` does not exceed the student's effective `max_credits` (subject to the probation cap of 12). Violation produces `CREDIT_LIMIT_EXCEEDED`.

If the section's `requires_approval` flag is `true`, the enrollment is created in `PENDING_APPROVAL` status, and the student's `credits_enrolled` is immediately incremented by the course's `credit_hours` to reserve capacity. If the section has available seats (`seats_available > 0`) and no approval is required, the enrollment moves directly to `ENROLLED`: `seats_enrolled` increments by one, `seats_available` decrements by one, and the student's `credits_enrolled` increases. If the section is full but the waitlist has not reached `waitlist_cap`, the student is placed on the waitlist in `WAITLISTED` status with a `waitlist_position` equal to the current `waitlist_count` plus one. If both the section and the waitlist are full, the request is rejected with `SECTION_FULL` when the waitlist is also at capacity, or `WAITLIST_FULL` when the section has no seats and the waitlist is specifically at its cap.

### 3.5. Professor Approval and Rejection

Sections marked with `requires_approval` route enrollment requests through the professor for review. Approval is performed by the `Professor` role and may include an optional `approval_note`. When a professor approves a `PENDING_APPROVAL` enrollment and the section still has seats available, the enrollment transitions to `ENROLLED`: `seats_enrolled` and `seats_available` are adjusted, and the student's `credits_enrolled` remains unchanged (credits were already reserved at request time). The enrollment must be in `PENDING_APPROVAL` status; otherwise the action is rejected with `ENROLLMENT_STATE_INVALID`.

If the professor approves but the section has filled since the request was submitted (`seats_available == 0`), the enrollment moves to `WAITLISTED` instead — provided the waitlist has not reached capacity. A `waitlist_position` is assigned as `waitlist_count + 1`, and the section's `waitlist_count` increments. If even the waitlist is full at approval time, the approval action fails with `WAITLIST_FULL`.

Rejection transitions the enrollment from `PENDING_APPROVAL` to `REJECTED`. The professor may attach an `approval_note` explaining the decision. Upon rejection, the system releases the reserved credits: `credits_enrolled` decreases by the course's `credit_hours`, and `credits_available` is recalculated.

Both approval and rejection accept an optional `enrollment_seq` for optimistic concurrency.

### 3.6. Dropping, Withdrawal, and the Waitlist Cascade

A student or registrar may drop an enrollment that is in `ENROLLED`, `WAITLISTED`, or `PENDING_APPROVAL` status. Dropping from `ENROLLED` frees a seat: `seats_enrolled` decreases, `seats_available` increases, and the student's `credits_enrolled` is reduced by the course's `credit_hours`. If the enrollment was cross-departmental, the corresponding CrossDeptPermission's `courses_used` is decremented. Critically, freeing a seat triggers the **waitlist promotion cascade**.

Dropping from `WAITLISTED` reduces the section's `waitlist_count` and causes all students with a higher `waitlist_position` to shift down by one, maintaining a dense, gap-free ordering. Dropping from `PENDING_APPROVAL` releases the reserved credits from the student's load. In all cases the enrollment transitions to `DROPPED` and `dropped_on` is recorded.

Late withdrawal is a registrar-only action that transitions an `ENROLLED` enrollment to `WITHDRAWN`. This action is permitted only when the current date falls between the semester's `registration_closes` and `late_drop_deadline`. If the withdrawal window has passed, the request is rejected with `WITHDRAWAL_WINDOW_CLOSED`. Withdrawal produces the same seat-freeing and waitlist-promotion effects as a drop, and a W grade notation is recorded (outside this system's scope).

When a seat opens — whether through a drop, a withdrawal, or a section capacity increase via PATCH — the **waitlist promotion cascade** engages. Candidates are evaluated in FIFO order based on `waitlist_position` (ascending). For the first candidate in the queue, the system re-validates prerequisites, corequisites, the credit limit, and schedule conflicts. If all checks pass, that candidate's enrollment transitions from `WAITLISTED` to `ENROLLED`: `seats_enrolled` and `seats_available` adjust, `waitlist_count` decreases, `credits_enrolled` increases, and a WaitlistPromotion event is created recording the `enrollment_id`, `section_id`, `previous_position`, the `trigger_event` (e.g., "drop", "withdrawal", "capacity increase"), and `promoted_on`. All remaining waitlisted students shift down by one position.

If the top candidate fails re-validation — for instance, a schedule conflict emerged since they joined the waitlist — the system skips that candidate (who remains `WAITLISTED` at their current position) and evaluates the next in line. Only one seat is filled per drop or withdrawal; a capacity increase that opens multiple seats runs the promotion loop once per new seat.

### 3.7. Cross-Department Enrollment Permissions

When a department does not have `cross_dept_open` set to `true`, students whose `major_department_id` differs from the course's owning department must obtain explicit permission before enrolling. A `Registrar` or `Professor` may grant a CrossDeptPermission by specifying the `student_id`, the `target_department_id`, and an optional `max_courses` limit (defaulting to 2). Upon creation, `courses_used` initializes to 0 and `status` is set to `ACTIVE`.

The `courses_used` counter tracks the number of enrollments (in `ENROLLED`, `PENDING_APPROVAL`, or `WAITLISTED` status) that the student currently holds in courses belonging to the target department. Each qualifying enrollment increments this counter; drops and rejections decrement it.

Revoking a permission transitions its `status` from `ACTIVE` to `REVOKED`. Revocation is blocked if the student currently holds any `ENROLLED` enrollments that depend on the permission — attempting to revoke in this situation triggers `CROSS_DEPT_REVOKE_BLOCKED`. When revocation succeeds, all `WAITLISTED` or `PENDING_APPROVAL` enrollments in that department for the affected student are automatically dropped. If the referenced permission does not exist, the system returns `CROSS_DEPT_PERMISSION_UNKNOWN`.

### 3.8. Section Updates and Cascade Effects

Sections may be updated via PATCH to adjust `capacity`, `waitlist_cap`, schedule fields (`schedule_days`, `schedule_start`, `schedule_end`), `location`, or `requires_approval`. An optional `enrollment_seq` may be provided for concurrency control. When `capacity` is increased, the difference between the new and old capacity represents newly available seats, and the waitlist promotion cascade runs once for each new seat. When the schedule is changed, the system re-evaluates conflicts for every student currently `ENROLLED` in that section, creating ScheduleConflict records where new overlaps are found.

### 3.9. Student Schedule and Diagnostic Views

A student's full schedule — all sections in which they hold `ENROLLED` status — is accessible at the student schedule endpoint. This read-only view returns the section details including times, locations, and instructor information, and is available to the student themselves, professors, and registrars.

The registrar has exclusive access to two diagnostic views. The schedule-conflicts endpoint lists all ScheduleConflict records within a semester, optionally filtered by `student_id`. Each record exposes the two conflicting sections, the `overlap_days`, and `overlap_minutes`. The waitlist-promotions endpoint lists WaitlistPromotion events, optionally filtered by `section_id`, providing a complete audit trail of every automatic seat assignment.

Pagination parameters `page_size` and `page_token` are supported on all list endpoints. Supplying a `page_size` outside the 1–50 range or a malformed `page_token` results in `INVALID_PAGE_PARAMS`.

## 4. Endpoint Definitions

Operations that create new standalone or nested resources return a `201 Created` status code. Operations that modify an existing resource — including state transitions, approvals, rejections, drops, and withdrawals — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------- |
| POST | `/semesters` | Create a new semester | Registrar |
| GET | `/semesters` | List all semesters | Any |
| GET | `/semesters/{semesterId}` | Get semester details | Any |
| POST | `/semesters/{semesterId}/open-enrollment` | Transition semester to OPEN_ENROLLMENT | Registrar |
| POST | `/semesters/{semesterId}/close-enrollment` | Transition semester to CLOSED_ENROLLMENT | Registrar |
| POST | `/semesters/{semesterId}/reopen-enrollment` | Reopen enrollment from CLOSED_ENROLLMENT | Registrar |
| POST | `/semesters/{semesterId}/finalize` | Finalize the semester | Registrar |
| POST | `/semesters/{semesterId}/departments` | Create a department | Registrar |
| GET | `/semesters/{semesterId}/departments` | List departments in a semester | Any |
| GET | `/semesters/{semesterId}/departments/{departmentId}` | Get department details | Any |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses` | Create a course | Registrar, Professor |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses` | List courses in a department | Any |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}` | Get course details | Any |
| PATCH | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}` | Update course fields | Registrar |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/prerequisite-graph` | Get transitive prerequisite graph | Any |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections` | Create a section | Registrar, Professor |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections` | List sections for a course | Any |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}` | Get section details | Any |
| PATCH | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}` | Update section capacity or schedule | Registrar, Professor |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments` | Request enrollment in a section | Student, Registrar |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments` | List enrollments for a section | Any |
| GET | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments/{enrollmentId}` | Get enrollment details | Any |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments/{enrollmentId}/approve` | Approve a pending enrollment | Professor |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments/{enrollmentId}/reject` | Reject a pending enrollment | Professor |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments/{enrollmentId}/drop` | Drop an enrollment | Student, Registrar |
| POST | `/semesters/{semesterId}/departments/{departmentId}/courses/{courseId}/sections/{sectionId}/enrollments/{enrollmentId}/withdraw` | Late withdrawal with W grade | Registrar |
| POST | `/semesters/{semesterId}/instructors` | Register an instructor | Registrar |
| GET | `/semesters/{semesterId}/instructors` | List instructors | Any |
| GET | `/semesters/{semesterId}/instructors/{instructorId}` | Get instructor details | Any |
| POST | `/semesters/{semesterId}/students` | Register a student | Registrar |
| GET | `/semesters/{semesterId}/students` | List students | Any |
| GET | `/semesters/{semesterId}/students/{studentId}` | Get student details | Any |
| PATCH | `/semesters/{semesterId}/students/{studentId}` | Update student record | Registrar |
| GET | `/semesters/{semesterId}/students/{studentId}/schedule` | Get student's enrolled schedule | Student, Registrar, Professor |
| POST | `/semesters/{semesterId}/cross-dept-permissions` | Grant cross-department permission | Registrar, Professor |
| GET | `/semesters/{semesterId}/cross-dept-permissions` | List cross-department permissions | Any |
| GET | `/semesters/{semesterId}/cross-dept-permissions/{permissionId}` | Get permission details | Any |
| POST | `/semesters/{semesterId}/cross-dept-permissions/{permissionId}/revoke` | Revoke a cross-department permission | Registrar, Professor |
| GET | `/semesters/{semesterId}/schedule-conflicts` | List schedule conflicts | Registrar |
| GET | `/semesters/{semesterId}/waitlist-promotions` | List waitlist promotion events | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ENROLLMENT_AUTH_MISSING` | 401 Unauthorized |
| `ENROLLMENT_ROLE_DENIED` | 403 Forbidden |
| `SEMESTER_UNKNOWN` | 404 Not Found |
| `DEPARTMENT_UNKNOWN` | 404 Not Found |
| `COURSE_UNKNOWN` | 404 Not Found |
| `SECTION_UNKNOWN` | 404 Not Found |
| `STUDENT_UNKNOWN` | 404 Not Found |
| `INSTRUCTOR_UNKNOWN` | 404 Not Found |
| `ENROLLMENT_UNKNOWN` | 404 Not Found |
| `CROSS_DEPT_PERMISSION_UNKNOWN` | 404 Not Found |
| `REGISTRATION_NOT_OPEN` | 409 Conflict |
| `ENROLLMENT_STATE_INVALID` | 409 Conflict |
| `SEMESTER_PHASE_INVALID` | 409 Conflict |
| `PREREQUISITE_NOT_MET` | 422 Unprocessable Entity |
| `COREQUISITE_NOT_SATISFIED` | 422 Unprocessable Entity |
| `PREREQUISITE_CYCLE_DETECTED` | 422 Unprocessable Entity |
| `DUPLICATE_COURSE_ENROLLMENT` | 409 Conflict |
| `SCHEDULE_CONFLICT` | 409 Conflict |
| `CROSS_DEPT_NOT_PERMITTED` | 403 Forbidden |
| `CROSS_DEPT_LIMIT_REACHED` | 422 Unprocessable Entity |
| `GPA_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `SECTION_FULL` | 409 Conflict |
| `WAITLIST_FULL` | 409 Conflict |
| `ENROLLMENT_CONFLICT` | 409 Conflict |
| `WITHDRAWAL_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `INVALID_PAGE_PARAMS` | 400 Bad Request |
| `COURSE_INACTIVE` | 409 Conflict |
| `STUDENT_SUSPENDED` | 403 Forbidden |
| `CROSS_DEPT_REVOKE_BLOCKED` | 409 Conflict |
| `WAITLIST_PROMOTION_SKIPPED` | 422 Unprocessable Entity |
