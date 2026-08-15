# PD Catalog & Credit API — Product Requirements Document

## 1. Introduction

A school district's professional development office runs a perennial balancing act: hundreds of teachers pursuing salary-lane advancement through coursework, a finite pool of seat-limited sections each term, building-level budgets that must never be overspent, and a compliance calendar that carries hard deadlines with escalation consequences. The PD Catalog & Credit API is the system of record for that entire operation. It governs the catalog of courses and their scheduled sections, the registration and waitlist lifecycle against seat capacity, attendance verification and end-of-course evaluation, the conversion of clock hours into district lane credits and state CEUs, external workshop pre-approval and reimbursement under segregation of duties, individual growth plans tied to annual credit targets, required compliance training with overdue escalation, and a transcript audit function capable of posting reversing entries.

The system is built for a district PD office in which several roles act on overlapping data with deliberately separated powers: a `BuildingAdmin` who approves a workshop request must not be the same principal who later reimburses it; an auditor posting a reversal must be able to unwind credit without erasing history; a waitlist promotion must respect both seat order and the fiscal reality of the teacher's building budget. Every rule in this document is written so that a single logical clock — never wall-clock time — drives windows, deadlines, and fiscal-year attribution, allowing the entire district calendar to be replayed deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply to every resource and every endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_CONTEXT` (HTTP 400). If the headers are well-formed but the role is not permitted on the targeted endpoint — including the entity-backed kind check described below — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `Teacher`, `BuildingAdmin`, `Instructor`, `PDCoordinator`, `BusinessOfficer`, and `Auditor`.

Three of the roles are entity-backed. When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting `Employee` record, and that employee must have `employee_kind` equal to `TEACHER`; ownership checks on any resource that references an `Employee` (a registration's `teacher_id`, a workshop request's `teacher_id`, a growth plan's `teacher_id`) compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `BuildingAdmin`, `X-User-ID` is likewise the `id` of an `Employee` whose `employee_kind` must be `ADMIN`; the administrator's scope is the building identified by that employee's `primary_building_id`, and acting on a resource outside that building is rejected with `ERR_BUILDING_SCOPE_VIOLATION`. When `X-User-Role` is `Instructor`, `X-User-ID` is again the `id` of an `Employee`; the instructor may only act on sections whose `instructor_id` equals that `X-User-ID`, and violations surface as `ERR_NOT_RESOURCE_OWNER`. For any of the three entity-backed roles, an `X-User-ID` that names no existing `Employee` at all is likewise rejected with `ERR_FORBIDDEN_ROLE`, before any `employee_kind` comparison.

The remaining three roles are opaque operator identities. When `X-User-Role` is `PDCoordinator`, `BusinessOfficer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `approved_by_user_id` on an approved workshop request, `assigned_by_user_id` on a compliance assignment, `opened_by_user_id` on an audit case, or `recorded_by_user_id` on an attendance record — but it does not compare the value to any entity's `id`.

Segregation of duties cuts across these roles in two places. A `BusinessOfficer` attempting to reimburse or deny reimbursement on a workshop whose `approved_by_user_id` equals the officer's own `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Symmetrically, a `PDCoordinator` attempting to waive a compliance assignment whose `assigned_by_user_id` equals their own `X-User-ID` receives the same `ERR_SEGREGATION_OF_DUTIES`. Both checks compare the recorded actor id from the earlier step against the current request's `X-User-ID`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100 — out-of-range values are clamped into the allowed range rather than rejected, and an unparsable `limit` or `offset` falls back to its default. The `offset` parameter specifies how many items to skip and defaults to 0. Unless a more specific rule is stated, every list endpoint returns its resources sorted by `created_at` ascending, with ties on `created_at` broken by insertion order. Paginated list responses expose `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. In addition, list endpoints accept exact-match query filters on selected scalar fields: buildings by `status`; budgets by `building_id`, `fiscal_year`, and `status`; employees by `primary_building_id`, `status`, and `current_lane`; courses by `status`, `compliance_tag`, and `prerequisite_course_id`; sections by `course_id`, `instructor_id`, `building_id`, `term`, and `status`; registrations by `teacher_id`, `section_id`, `growth_plan_id`, and `status`; workshop requests by `teacher_id`, `building_id`, `status`, and `growth_plan_id`; growth plans by `teacher_id`, `school_year`, and `status`; compliance assignments by `employee_id`, `course_id`, and `status`; and audit cases by `employee_id` and `status`.

### 2.4. The Logical Clock and Fiscal-Year Attribution

The district never trusts wall-clock time. All window checks, deadline comparisons, and fiscal-year attributions are evaluated against a single server-held logical clock, set exclusively through a `PDCoordinator`-only administrative capability that advances the clock to a supplied `to_iso8601` instant; the supplied instant is applied unconditionally, with no forward-only or monotonicity check. Before any such call, the logical clock's startup default is exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter.

Fiscal years follow the district's July-through-June convention: the fiscal year of any dated event is the calendar year of that date when the month is July or later, and the prior calendar year when the month is January through June. This rule applies uniformly — a budget is created for a fiscal year label, a transcript entry is attributed to the fiscal year of its `awarded_at` instant, and a workshop reimbursement's annual cap grouping uses the fiscal year of the workshop's `starts_at`. A growth plan's `school_year` string (format `YYYY-YYYY` naming two consecutive years, so `2026-2027` covers 2026-07-01 through 2027-06-30) must be well-formed and consecutive or the request fails with `ERR_INVALID_REQUEST`.

### 2.5. Common Resource Properties

Every primary resource carries `id` (a server-minted UUID with no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer starting at 1 and incrementing on every mutation of the resource). Any mutation described in this document — a state transition, a ledger recompute, an applied extension — updates `updated_at` and bumps `version` on the resource actually mutated, even when the mutation is system-driven inside a cascade.

One exception is deliberate: a `SurveyResponse` is immutable once submitted and therefore carries only `id` and `created_at`. Both `updated_at` and `version` are absent on that resource.

### 2.6. Credit Precision and the Two Conversion Variants

Clock hours convert to credit in two different units, and the two variants are pinned to different rounding rules. **District lane credit** accrues at fifteen hours per credit and is truncated — floored — to one decimal place per transcript entry, so a 24-hour course yields 1.6 district credits on that entry. **State CEU** accrues at ten hours per CEU and is rounded half-up to two decimal places per entry, so the same 24 hours yield 2.40 CEUs. Monetary amounts are integer cents everywhere; attendance arithmetic is integer-only; lane balances move in 0.1-credit steps.

Rollups never re-round: transcript totals are the sum of the per-entry rounded values, not a conversion applied to summed hours. An employee with a 7-hour entry and an 8-hour entry holds 0.4 plus 0.5 equals 0.9 district credits — not the 1.0 that converting the aggregate 15 hours would produce. The aggregate-then-convert alternative is explicitly forbidden.

### 2.7. Budget Ledger Principles: Encumbrance Basis and Cash Basis

Every building's annual PD allocation is tracked as a `BuildingBudget` row, unique per (`building_id`, `fiscal_year`) pair — attempting to create a second budget for the same pair fails with `ERR_BUDGET_ALREADY_EXISTS`. The budget maintains two denormalized ledgers: `encumbered_cents`, the sum of outstanding commitments (live registration fees and approved-but-unsettled workshop estimates), and `spent_cents`, the sum of settled charges (completed registrations and reimbursed workshops). Together with `allocated_cents` they satisfy a standing invariant at all times: the allocation equals encumbered plus spent plus available.

Availability has two readings, and the system is explicit about which one blocks. The **encumbrance basis** — `available_cents`, computed as the allocation minus both encumbered and spent — is the blocking variant used by every encumbering operation: a seat with a fee, a workshop approval, a waitlist promotion. A budget with 100000 cents allocated and 10000 cents encumbered has 90000 cents of encumbrance-basis availability. The **cash basis** — the allocation minus spent only, which would read 100000 on the same ledger — is a reporting variant exposed only through the budget summary endpoint as `cash_basis_available_cents`; it never gates an operation.

### 2.8. Optimistic Concurrency Control

Two write endpoints guard against stale views of a parent entity by requiring an expected-version field.

Creating a growth plan carries `expected_employee_version`, which must equal the target teacher's current `Employee.version`. Because plan creation supersedes the teacher's existing non-terminal plan for the same school year and bumps the teacher's `version` as part of the cascade, a client whose last read of the employee is out of date is working from a stale view of the teacher's plan state; the create is then rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412).

Extending a compliance assignment's due date carries `expected_assignment_version`, which must equal the assignment's current `version`. An ops-run may have moved the assignment from `ASSIGNED` to `OVERDUE`, or an earlier extension may already have been applied — in either case the version has advanced since the client last observed it, and the extension is rejected as a stale write with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412). No other endpoint in the API accepts a version field.

### 2.9. Nested Resource Retrieval and Left-to-Right Validation

Requests that target nested paths validate identifiers left to right. Each path parameter's existence is confirmed in order, and the first identifier that does not correspond to an existing resource terminates the request with `ERR_NOT_FOUND` (HTTP 404). Body-referenced foreign keys — `teacher_id`, `section_id`, `course_id`, `growth_plan_id`, `building_id`, `transcript_entry_id`, and the like — are validated after path identifiers, and a missing referenced resource likewise yields `ERR_NOT_FOUND`.

### 2.10. Validation Ladder and Priority Ordering

When several validations could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. The order is:

1. **Authentication context** — both headers present and the role declared; otherwise `ERR_MISSING_CONTEXT`.
2. **Role authorization** — the role is permitted on the endpoint, including the entity-backed kind check; otherwise `ERR_FORBIDDEN_ROLE`.
3. **Path existence** — path identifiers exist, left to right; otherwise `ERR_NOT_FOUND`.
4. **Request shape** — required fields present, types, enum membership, ranges, and datetime formats valid, `ends_at` strictly after `starts_at`, `school_year` well-formed; otherwise `ERR_INVALID_REQUEST`.
5. **Body foreign-key existence** — referenced ids in the payload exist; otherwise `ERR_NOT_FOUND`.
6. **Lifecycle state** — the target's current state permits the operation, including terminal-state lockdown (`ERR_INVALID_STATE`, `ERR_SECTION_NOT_OPEN`, `ERR_EMPLOYEE_NOT_ACTIVE`, `ERR_BUDGET_NOT_OPEN`, `ERR_BUDGET_HAS_ENCUMBRANCES`, `ERR_ENTRY_ALREADY_REVERSED`).
7. **Safety and standing** — prerequisite completion (`ERR_PREREQUISITE_NOT_COMPLETED`), compliance hold on lane advancement (`ERR_COMPLIANCE_HOLD`), and both segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`).
8. **Ownership, scope, and alignment** — `ERR_NOT_RESOURCE_OWNER`, `ERR_BUILDING_SCOPE_VIOLATION`, `ERR_PLAN_NOT_APPROVED`, `ERR_PLAN_YEAR_MISMATCH`, `ERR_AUDIT_ENTRY_MISMATCH`.
9. **Temporal windows** — registration window boundaries (`ERR_REGISTRATION_NOT_YET_OPEN`, `ERR_REGISTRATION_WINDOW_CLOSED`), workshop lead and start times (`ERR_PREAPPROVAL_LEAD_TIME`, `ERR_APPROVAL_AFTER_START`, `ERR_WORKSHOP_NOT_STARTED`), lane advancement months (`ERR_ADVANCEMENT_WINDOW_CLOSED`), meeting containment (`ERR_MEETING_OUTSIDE_SECTION`).
10. **Domain constraints** — duplicate registration (`ERR_DUPLICATE_REGISTRATION`), teacher schedule overlap (`ERR_SCHEDULE_CONFLICT`), room turnover (`ERR_ROOM_CONFLICT`), budget uniqueness (`ERR_BUDGET_ALREADY_EXISTS`), one survey per registration (`ERR_SURVEY_ALREADY_SUBMITTED`), revision limit (`ERR_REVISION_LIMIT_EXCEEDED`), capacity floor (`ERR_CAPACITY_BELOW_REGISTERED`), attendance completeness (`ERR_ATTENDANCE_INCOMPLETE`), the three lane gates (`ERR_LANE_MAX_REACHED`, `ERR_ADVANCEMENT_ALREADY_THIS_FY`, `ERR_LANE_CREDITS_INSUFFICIENT`), and the completion gates (`ERR_ATTENDANCE_NOT_VERIFIED` before `ERR_SURVEY_NOT_SUBMITTED`).
11. **Fiscal checks last** — budget exists and is `OPEN` for the charge (`ERR_BUDGET_NOT_OPEN`), then availability on the encumbrance basis (`ERR_BUDGET_INSUFFICIENT`).
12. **OCC** — the expected-version fields of §2.8 (`ERR_STALE_EMPLOYEE_VERSION`, `ERR_STALE_ASSIGNMENT_VERSION`).

Two consequences of this ordering are worth stating plainly. A registration attempt against a section that is not `PUBLISHED` fails at step 6 as `ERR_SECTION_NOT_OPEN` before the window checks of step 9 are even consulted. And completion's two gates have their own internal order within step 10: an attempt with unverified attendance fails with `ERR_ATTENDANCE_NOT_VERIFIED`, and only once attendance is `VERIFIED` does a pending survey surface as `ERR_SURVEY_NOT_SUBMITTED`.

### 2.11. The District Ops Checkpoint

Section windows, waitlist expirations, no-show sweeps, workshop expirations, and compliance escalations are not driven by timers; they advance only when a `PDCoordinator` triggers the district ops checkpoint. The checkpoint executes a pinned seven-step order, each step observing the results of the previous one, and returns six parallel arrays reporting what moved: `transitioned_section_ids`, `promoted_registration_ids`, `expired_registration_ids`, `no_show_registration_ids`, `expired_workshop_ids`, and `transitioned_assignment_ids`. The full sweep semantics are specified in §3.8.

## 3. Business Logic & Workflows

### 3.1. Buildings, Budgets, and the Annual Funding Cycle

A `Building` is the district's organizational atom, created by a `PDCoordinator` with a display `name` and a `building_code` that is unique across all buildings (a duplicate `building_code` is rejected with `ERR_INVALID_REQUEST`); its `status` is `ACTIVE` by default and may be `CLOSED`. Employees — created with a `full_name`, a district-wide unique `email` (a duplicate is rejected with `ERR_INVALID_REQUEST`), an `employee_kind` of `TEACHER`, `ADMIN`, or `SPECIALIST`, a `primary_building_id` naming the home building whose budget pays for their PD, and a `base_lane` — are the actors the catalog serves. An employee is born `ACTIVE`.

Funding flows through the `BuildingBudget`, created by a `BusinessOfficer` for a (`building_id`, `fiscal_year`) pair with an `allocated_cents` amount that may not be negative. A new budget is `DRAFT` with both ledgers at zero. The officer then opens it — `DRAFT` → `OPEN`, version bumped — and only an `OPEN` budget accepts encumbrances. Closing moves `OPEN` → `CLOSED` and is permitted only when `encumbered_cents` is exactly zero; a close attempted with outstanding commitments is rejected with `ERR_BUDGET_HAS_ENCUMBRANCES`. `CLOSED` is terminal. The read-only budget summary reports `allocated_cents`, `encumbered_cents`, `spent_cents`, the blocking `available_cents`, and the reporting-only `cash_basis_available_cents`, per the two availability readings of §2.7.

### 3.2. The Course Catalog: Courses, Sections, and Meetings

A `PDCoordinator` authors the catalog. A `Course` carries a `course_code` that is unique across all courses (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `title`, a `delivery_mode` of `IN_PERSON`, `VIRTUAL`, or `HYBRID`, and a positive `clock_hours` value. The per-registrant `fee_cents` defaults to zero and may not be negative. A course whose `compliance_tag` is set (for example, `SAFETY_101`) is a compliance offering — null means elective — and when `recurrence_months` (a positive integer when set) is also set, satisfying a compliance assignment through this course spawns the next assignment in the cycle (§3.7). A course may name a `prerequisite_course_id`, a self-referential pointer to another catalog course; null means no prerequisite. A course is `ACTIVE` on creation and may later be retired — `ACTIVE` → `TERMINAL RETIRED` — but only when no section of the course stands in `PUBLISHED`, `REGISTRATION_CLOSED`, or `IN_SESSION` — a retire attempted on a non-`ACTIVE` course or while such a section stands is rejected with `ERR_INVALID_STATE`; the retire bumps the course's `version`, and `RETIRED` is terminal.

A `Section` schedules one offering of a course. The coordinator supplies the `course_id`, a `term` label such as `2026-FALL`, the `instructor_id` of the employee who will hold attendance authority, the hosting `building_id` (which is not the billing building — billing always follows the registrant's own primary building), the `room` label used for room-conflict checks, a `seat_capacity` of at least one, the session window `starts_at`/`ends_at`, and the registration window `registration_opens_at`/`registration_closes_at`. A section-level `fee_cents` may be supplied as an override; when omitted it defaults to the course's `fee_cents` at creation time. The section is born `DRAFT`, and its computed `seats_registered` counts registrations currently in `REGISTERED`, while `seats_open` is the capacity minus that count.

Publishing moves `DRAFT` → `PUBLISHED` and is the section's point of no return. Publish requires the parent course to be `ACTIVE`, at least one `SectionMeeting` to exist for the section, and the temporal quadruple to be coherent: the registration open at or before the registration close, the close at or before the session start, and the start strictly before the session end. Failing any of these preconditions — or publishing a section no longer `DRAFT` — is rejected with `ERR_INVALID_STATE`. A `PUBLISHED` section may still be edited — capacity, room, or schedule — but the new `seat_capacity` must be at least the current `seats_registered`, or the edit is rejected with `ERR_CAPACITY_BELOW_REGISTERED`. When a capacity edit increases seats, a synchronous waitlist promotion sweep runs for that section immediately (§3.3). Cancellation moves a `DRAFT`, `PUBLISHED`, or `REGISTRATION_CLOSED` section to terminal `CANCELED` and cascades: every `REGISTERED` registration becomes `DROPPED` with its encumbrance released from the registrant's building budget (bumping that budget's `version`), every `WAITLISTED` registration becomes `EXPIRED`, and no promotion sweep runs because the section is terminal. The remaining lifecycle transitions — `PUBLISHED` → `REGISTRATION_CLOSED` once the logical clock passes `registration_closes_at`, `REGISTRATION_CLOSED` → `IN_SESSION` once the clock reaches `starts_at`, and `IN_SESSION` → terminal `COMPLETED` once the clock passes `ends_at` — are performed only by the ops checkpoint, and a single run may advance a section through several of these steps in sequence.

Each `SectionMeeting` names its `section_id`, its own `starts_at` and `ends_at`, and its `room`. Meetings may be added only while the section stands in `DRAFT` or `PUBLISHED`; adding to a section in any other state is rejected with `ERR_INVALID_STATE`. A meeting's interval must be contained in the section's session window with its end strictly after its start; a meeting outside that window is rejected with `ERR_MEETING_OUTSIDE_SECTION`. Two meetings sharing the same room must respect a thirty-minute turnover gap against every existing meeting in that room — a violation is `ERR_ROOM_CONFLICT` (HTTP 409).

### 3.3. Registration, Seat Allocation, and the Waitlist Waterfall

Registration is the system's central act: a `Teacher` registering themselves — the payload's `teacher_id` must equal the caller's `X-User-ID`, otherwise `ERR_NOT_RESOURCE_OWNER` — or a `PDCoordinator` acting on a teacher's behalf, naming a `section_id` and optionally a `growth_plan_id` with its companion `aligned_focus_area`. The focus-area string is required exactly when a plan is referenced, and the alignment itself is validated per §3.6.

The validation ladder of §2.10 applies in full. Within it, the registration-specific checks run in their priority positions: the employee must be `ACTIVE` (an employee-targeted write against an `ON_LEAVE` or `SEPARATED` employee fails with `ERR_EMPLOYEE_NOT_ACTIVE`); the section must be `PUBLISHED` (`ERR_SECTION_NOT_OPEN`); the logical clock must sit inside the registration window — at or after `registration_opens_at`, else `ERR_REGISTRATION_NOT_YET_OPEN`, and at or before `registration_closes_at`, else `ERR_REGISTRATION_WINDOW_CLOSED`. If the course names a prerequisite, the teacher must hold an `AWARDED` transcript entry of `source_type` `COURSE_COMPLETION` for that prerequisite course, else `ERR_PREREQUISITE_NOT_COMPLETED`. The teacher must not already hold a `REGISTERED` or `WAITLISTED` registration in the same section — a second live registration for the same (`teacher_id`, `section_id`) pair is `ERR_DUPLICATE_REGISTRATION` (HTTP 409). The teacher's existing committed schedule is checked for overlap: the new section's window must not overlap, in half-open fashion, the window of any section the teacher is currently `REGISTERED` in — adjacency is allowed, and a true overlap is `ERR_SCHEDULE_CONFLICT` (HTTP 409).

Only after all of that does the seat waterfall run. If `seats_open` is at least one, the registration is created in `REGISTERED`. If the section's `fee_cents` is greater than zero, the fee is encumbered against the teacher's building budget for the fiscal year of the section's `starts_at`: that budget must exist and be `OPEN` (`ERR_BUDGET_NOT_OPEN`) and its `available_cents` must cover the fee (`ERR_BUDGET_INSUFFICIENT`); the encumbrance raises the budget's `encumbered_cents` by the fee, bumps the budget's `version`, and stamps the registration's `encumbered_cents` with the fee amount. If no seat is open, the registration is created in `WAITLISTED` with `waitlist_seq` set to the next per-section monotonic integer and `encumbered_cents` zero — a waitlisted seat holds no money. In either case, any of the teacher's `ASSIGNED` compliance assignments for this course advance to `IN_PROGRESS` as part of the create cascade.

Seat freeing events — an explicit drop, a capacity increase, or an ops-run transition — trigger the promotion sweep. The sweep considers the section's `WAITLISTED` registrations in `waitlist_seq` ascending order. Each candidate is eligible only while the section is still `PUBLISHED`, a seat is actually open after the freeing event, and — when the fee is greater than zero — the candidate teacher's building budget for the section's fiscal year is `OPEN` with `available_cents` covering the fee. A candidate whose budget fails is skipped and remains `WAITLISTED`; the sweep continues down the list, promoting until no seats remain, and an empty candidate set simply does nothing. Promotion clears the candidate's `waitlist_seq` to null, moves them to `REGISTERED`, encumbers the fee exactly as a fresh registration would, bumps the budget's `version`, and advances their `ASSIGNED` compliance assignments for the course to `IN_PROGRESS`. Note the depth this creates: a drop releases a seat, the release triggers promotion, and the promotion creates a fresh encumbrance — a three-level cascade inside one request.

A registrant exits the live states in several ways. A `REGISTERED` teacher may drop (or be dropped by a coordinator) while the section is `PUBLISHED` or `REGISTRATION_CLOSED`: the registration becomes `DROPPED`, its `encumbered_cents` is subtracted from the budget's `encumbered_cents` and zeroed on the registration (budget `version` bumped), and the freed seat triggers the promotion sweep. A `WAITLISTED` teacher may withdraw the same way, becoming `WITHDRAWN` — withdrawing frees no seat and touches no budget. Employee separation is the heavy cascade: when a `PDCoordinator` moves an employee from `ACTIVE` or `ON_LEAVE` to `SEPARATED`, every `WAITLISTED` registration of that employee becomes `WITHDRAWN`, and every `REGISTERED` registration whose section is `PUBLISHED` or `REGISTRATION_CLOSED` becomes `DROPPED` with its encumbrance released and a promotion sweep run per freed seat. Separating back the other direction, `ON_LEAVE` → `ACTIVE` and `ACTIVE` → `ON_LEAVE`, are simple coordinator-driven status sets on the employee that bump the employee's `version`; `SEPARATED` is terminal.

### 3.4. Attendance, Verification, and the Evaluation Survey

Attendance is recorded per meeting by the section's `Instructor` or a `PDCoordinator`, in bulk: a payload of `records`, each naming a `registration_id` and a `mark` of `PRESENT`, `ABSENT`, or `EXCUSED`, is applied atomically — any invalid item rejects the whole request — and upserts the `AttendanceRecord` for the (`registration_id`, `meeting_id`) pair, which is unique per pair. A record item naming a registration that belongs to a different section than the meeting's is an invalid item, rejecting the whole request with `ERR_INVALID_REQUEST`; a `registration_id` naming no existing registration yields `ERR_NOT_FOUND` per §2.9. Re-recording a meeting overwrites the previous mark, and each write stamps `recorded_by_user_id` with the caller's `X-User-ID`. A successful bulk write reports `recorded_count`.

Verification converts the raw marks into the registration's `attendance_status`. The instructor of record or a coordinator may invoke verification on a `REGISTERED` registration. Every meeting of the section must already hold a record for this registration; if any meeting lacks one, the attempt fails with `ERR_ATTENDANCE_INCOMPLETE`. The rate check itself is integer arithmetic only: the attended count — marks of `PRESENT` or `EXCUSED`, since an excused absence counts as attended — multiplied by five must be at least the total meeting count multiplied by four. Four meetings attended of five passes; three of five fails. Passing sets `attendance_status` to `VERIFIED`; failing sets it to `ABSENT`. Both are terminal for that dimension, and either transition bumps the registration's `version`. Attendance records for a registration or a meeting are readable through the list endpoints with the usual `limit`/`offset` pagination.

The survey runs in parallel as the registration's `survey_status`. The teacher — and only the teacher themselves — submits the evaluation once, while the registration is `REGISTERED` or `COMPLETED`, supplying an `overall_rating` from 1 to 5, a `would_recommend` boolean, and optional free-text `comments`. The submission creates the immutable `SurveyResponse` (see §2.5 for its reduced field set), stamps its `submitted_at`, moves `survey_status` from `PENDING` to `SUBMITTED`, and bumps the registration's `version`; a second survey for the same registration is rejected with `ERR_SURVEY_ALREADY_SUBMITTED` (HTTP 409), and a submission against a registration whose survey stands `WAIVED` is rejected with `ERR_INVALID_STATE`. Alternatively a `PDCoordinator` may waive the requirement, supplying a `reason`, while the registration is `REGISTERED`, moving `survey_status` to `WAIVED`; waiving requires the survey still `PENDING`, so waiving an already-`SUBMITTED` survey is rejected with `ERR_INVALID_STATE`. The survey for a registration is retrievable as a zero-or-one-element list.

### 3.5. Completion and the Transcript

Completion is the coordinator's act that converts a registration into credit. Completing requires the section to be `IN_SESSION` or `COMPLETED`, the registration's `attendance_status` to be `VERIFIED`, and its `survey_status` to be `SUBMITTED` or `WAIVED` — the two gates surfacing, in that order, as `ERR_ATTENDANCE_NOT_VERIFIED` then `ERR_SURVEY_NOT_SUBMITTED` per §2.10. On completion the registration becomes `COMPLETED` with `completed_at` set to the logical now, and a fan-out of effects follows.

First, a `TranscriptEntry` is minted: `source_type` `COURSE_COMPLETION`, `source_id` pointing at the registration, `clock_hours` equal to the course's `clock_hours`, `growth_plan_id` copied from the registration's alignment (null when unaligned), `awarded_at` set to now, `fiscal_year` derived from that instant per §2.4, and `status` `AWARDED`. The entry's `district_credit` and `state_ceu` are computed per the two conversion variants of §2.6 — per-entry floored-to-a-tenth and per-entry rounded-half-up-to-a-hundredth respectively — and its `counts_toward_lane` is `false` when the source course carries a `compliance_tag`, `true` otherwise. Second, money settles: when the registration's `encumbered_cents` is positive, that amount leaves the budget's `encumbered_cents` and lands in its `spent_cents`, bumping the budget's `version`. Third, the employee's `lane_credit_balance` is recomputed per §3.9. Fourth, when the registration was aligned to a plan that stands in `APPROVED` or `FULFILLED`, the plan's `aligned_credits` recompute runs and may flip the plan per §3.6. Fifth, compliance: any of the teacher's assignments for this course standing in `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` become `SATISFIED` with `satisfied_at` set to the completion instant; if the course's `recurrence_months` is set, a successor assignment is spawned in `ASSIGNED` with `due_date` at `completed_at` plus that many calendar months (day clamped to the target month's last day), same employee and course, and inheriting the satisfied assignment's `assigned_by_user_id`; and the employee's `compliance_standing` is recomputed.

A transcript entry itself is addressed by `employee_id`, carries the polymorphic `source_id` (a registration id for `COURSE_COMPLETION`, a workshop request id for `EXTERNAL_WORKSHOP`, or the reversed entry's id for `AUDIT_REVERSAL` — deliberately not a constrained foreign key), and remembers `reversed_by_entry_id` once an audit has reversed it. Transcripts are readable per employee — filterable by `fiscal_year`, by `status`, and by `counts_toward_lane` — per plan through the aligned-entries listing (which returns every entry aligned to the plan regardless of `status`, `REVERSED` originals and compensating `AUDIT_REVERSAL` entries included), and individually by entry id.

### 3.6. Individual Growth Plans

A growth plan binds a teacher's year to a credit target. Creation names the `teacher_id`, the `school_year` string, a non-empty array of `focus_areas`, and a positive `target_credits`, and — per §2.8 — must carry `expected_employee_version` matching the teacher's current `Employee.version`, else `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412). Creating a plan for a teacher-and-year that already has a non-terminal plan supersedes the predecessor: the old plan moves to terminal `SUPERSEDED` with its `version` bumped, and the teacher's `Employee.version` itself increments by one, which is precisely why the OCC field exists. Plans are creatable by the teacher themselves or by a coordinator; a teacher creating for another employee is `ERR_NOT_RESOURCE_OWNER`.

The plan lifecycle is `DRAFT` → `SUBMITTED` (by the teacher or coordinator) → `APPROVED` or back to `DRAFT` (a building-scoped `BuildingAdmin` approve or return, the return carrying a `reason`; an admin acting outside the plan teacher's building is `ERR_BUILDING_SCOPE_VIOLATION`). From `APPROVED`, the plan's computed `aligned_credits` — the sum of `district_credit` over `AWARDED` transcript entries whose `growth_plan_id` is this plan — is watched automatically: when a recomputation pushes the sum to at least `target_credits` (the comparison is inclusive), the plan flips to `FULFILLED`; when an audit reversal drags the sum back below target, a `FULFILLED` plan falls back to `APPROVED`. Both flips bump the plan's `version`. A coordinator may close an `APPROVED` or `FULFILLED` plan at year end, moving it to terminal `CLOSED`.

Alignment is enforced where plans meet activities. Any `growth_plan_id` carried by a registration or a workshop request must belong to the same teacher (a plan belonging to another teacher surfaces as `ERR_PLAN_YEAR_MISMATCH`), must stand in `APPROVED` or `FULFILLED` (else `ERR_PLAN_NOT_APPROVED`), and its school year must contain the activity's date — the section's `starts_at` for a registration, the workshop's window for a request — else `ERR_PLAN_YEAR_MISMATCH`. Containment is judged against the school year's July-to-July window: a registration's section `starts_at` must fall on or after the opening July 1 and strictly before the closing July 1, while a workshop must start on or after the opening July 1 and end at or before the closing July 1 midnight.

### 3.7. Compliance Assignments: Deadlines, Escalation, and Recurrence

Required training enters the system as a `ComplianceAssignment`, created by a `PDCoordinator` naming the `employee_id`, the `course_id` (which must reference a compliance-tagged course — naming one without a compliance tag is rejected with `ERR_INVALID_REQUEST`), and the `due_date` deadline. The assignment is born `ASSIGNED`, stamps `assigned_by_user_id` with the creator's `X-User-ID`, and counts `extension_count` from zero.

The assignment lifecycle is cyclic and deadline-driven. When the assignee becomes `REGISTERED` in a section of the assigned course — by direct registration or by waitlist promotion — the assignment moves `ASSIGNED` → `IN_PROGRESS`. The ops checkpoint moves an `ASSIGNED` or `IN_PROGRESS` assignment past its `due_date` to `OVERDUE`, and an `OVERDUE` assignment more than thirty days past its due date to `ESCALATED`; the escalation recomputes the employee's `compliance_standing` to `NON_COMPLIANT`, bumping the employee's `version`. Satisfaction arrives through completion per §3.5: from any of `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` the assignment lands in terminal `SATISFIED`, spawning the recurring successor when the course's `recurrence_months` is set and recomputing standing. A coordinator may instead waive an assignment from any of those four states into terminal `WAIVED`, supplying a `reason` — but only if the coordinator's `X-User-ID` differs from the assignment's `assigned_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; waiving also recomputes standing. Finally, a coordinator may extend an assignment standing in `ASSIGNED`, `IN_PROGRESS`, or `OVERDUE`: the payload carries `new_due_date`, which must be strictly after the logical now (a `new_due_date` at or before the logical now fails with `ERR_INVALID_REQUEST`), and the OCC field `expected_assignment_version` per §2.8. A successful extension moves the due date, resets the status to `ASSIGNED`, increments both `extension_count` and the assignment's `version`, and recomputes standing.

An employee's `compliance_standing` is `COMPLIANT` by default and `NON_COMPLIANT` exactly while any of their assignments stands in `ESCALATED`; every transition that creates or resolves an `ESCALATED` row recomputes it.

### 3.8. The Ops Checkpoint Sweep

The district ops checkpoint, triggerable only by a `PDCoordinator`, applies the following seven steps in pinned order, each observing the effects of the previous:

1. **Section windows.** Every `PUBLISHED` section whose `registration_closes_at` is now in the past moves to `REGISTRATION_CLOSED`; then every `REGISTRATION_CLOSED` section whose `starts_at` has been reached moves to `IN_SESSION`; then every `IN_SESSION` section whose `ends_at` is now past moves to `COMPLETED`. One run may advance a section through multiple steps.
2. **Waitlist promotion.** For sections still `PUBLISHED`, the promotion waterfall of §3.3 runs.
3. **Waitlist expiry.** `WAITLISTED` registrations in sections now `IN_SESSION`, `COMPLETED`, or `CANCELED` become `EXPIRED`.
4. **No-show sweep.** `REGISTERED` registrations in `COMPLETED` sections whose `attendance_status` is not `VERIFIED` become `NO_SHOW`; a still-`PENDING` attendance dimension is set to `ABSENT`, and the registration's encumbrance is released to the teacher's building budget with the budget's `version` bumped.
5. **Workshop expiry.** An `APPROVED` workshop whose `ends_at` passed more than thirty days ago without completion becomes `EXPIRED`, releasing its encumbrance and bumping the budget's `version`.
6. **Compliance deadlines.** Assignments `ASSIGNED` or `IN_PROGRESS` past `due_date` become `OVERDUE`; assignments `OVERDUE` more than thirty days past `due_date` become `ESCALATED`. A single run applies both transitions in sequence, so an assignment sufficiently far past due may move `ASSIGNED` → `OVERDUE` → `ESCALATED` within one checkpoint.
7. **Standing recompute.** `compliance_standing` is recomputed for every employee touched by step 6, and for any employee with lingering `ESCALATED` rows.

### 3.9. Lane Credits and Salary-Lane Advancement

The employee's `lane_credit_balance` is the engine of advancement: it is the sum of `district_credit` over the employee's `AWARDED` transcript entries that count toward the lane, minus 12.0 for each completed lane advancement. Because the rollup sums per-entry rounded values (§2.6), the balance moves in tenths and never re-rounds. The employee's `current_lane` starts equal to their `base_lane` at hire and is bumped only by advancement; their `last_advancement_fiscal_year` is null until the first advancement occurs.

Lane advancement is a coordinator action gated by six checks, evaluated in order: the employee must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); their `compliance_standing` must be `COMPLIANT` (`ERR_COMPLIANCE_HOLD`); their `current_lane` must not already be `DOC`, the top of the ladder (`ERR_LANE_MAX_REACHED`); the logical clock's month must be August or September (`ERR_ADVANCEMENT_WINDOW_CLOSED`); their `last_advancement_fiscal_year` must differ from the current fiscal year (`ERR_ADVANCEMENT_ALREADY_THIS_FY`); and their `lane_credit_balance` must be at least 12.0 credits (`ERR_LANE_CREDITS_INSUFFICIENT`). Success moves the `current_lane` one step up the fixed ladder — `BA` to `BA15` to `MA` to `MA15` to `MA30` to `DOC` — subtracts 12.0 from the `lane_credit_balance` with any remainder carrying over, stamps `last_advancement_fiscal_year` with the current fiscal year, and bumps the employee's `version`. Note that an audit reversal lowers the balance but never rolls the lane itself back.

### 3.10. External Workshops: Pre-Approval, Evidence, and Reimbursement

Off-catalog learning runs through the `ExternalWorkshopRequest`. A teacher (for themselves) or a coordinator creates a request in `DRAFT` naming the `teacher_id`, a `title`, the external `provider`, the window `starts_at`/`ends_at`, a positive `est_cost_cents`, and a positive `clock_hours_claimed`. The charged `building_id` may be supplied and defaults to the teacher's `primary_building_id`; an optional `growth_plan_id` aligns the activity per §3.6.

Submission — by the teacher or a coordinator — moves `DRAFT` → `SUBMITTED` and enforces the pre-approval lead: the workshop's `starts_at` must be at least fourteen days after the logical now, else `ERR_PREAPPROVAL_LEAD_TIME`. Approval belongs to a `BuildingAdmin` scoped to the request's `building_id` (acting outside that building is `ERR_BUILDING_SCOPE_VIOLATION`). Approval requires the logical now to be strictly before `starts_at` — approving at or after the start is `ERR_APPROVAL_AFTER_START` — and requires the building's budget for the fiscal year of `starts_at` to be `OPEN` (`ERR_BUDGET_NOT_OPEN`) with `available_cents` covering the `est_cost_cents` (`ERR_BUDGET_INSUFFICIENT`). On approval the estimate is encumbered against that budget (bumping its `version`), the request's `approved_by_user_id` is stamped with the approver's `X-User-ID` — the segregation-of-duties anchor — and the request becomes `APPROVED`. Rejection instead moves `SUBMITTED` → `REJECTED`, recording the payload's `reason` into `reject_reason`. A rejected request may be revised back to `DRAFT` by the teacher or a coordinator at most three times: revision overwrites whichever editable fields (`title`, `provider`, `starts_at`, `ends_at`, `est_cost_cents`, `clock_hours_claimed`) appear in the payload, increments `revision_count`, and a fourth attempt is `ERR_REVISION_LIMIT_EXCEEDED`.

After the workshop, completion evidence moves `APPROVED` → `ATTENDED`: the logical now must be at or after `starts_at` (`ERR_WORKSHOP_NOT_STARTED`), and the payload records `actual_hours` (which must be positive) and `receipt_cents` (which must be non-negative). Completion mints a `TranscriptEntry` of `source_type` `EXTERNAL_WORKSHOP` whose `clock_hours` are the `actual_hours` (not the claimed hours), whose `counts_toward_lane` is `true`, whose `growth_plan_id` is copied from the request, and whose credits follow §2.6; the employee's `lane_credit_balance` recomputes, and an aligned `APPROVED` plan recomputes toward auto-fulfillment exactly as §3.6 describes.

Reimbursement is the `BusinessOfficer`'s exclusive domain and is segregated from approval: the officer's `X-User-ID` must differ from the request's `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The reimbursed amount is a nested minimum of three quantities: the `receipt_cents` evidenced, the `est_cost_cents` approved, and the teacher's remaining annual cap. The cap is 250000 cents per fiscal year, where the grouping year is the fiscal year of each workshop's `starts_at`; the remainder is 250000 minus the sum of `reimbursed_cents` over the teacher's workshops already in `REIMBURSED` in that same fiscal year, floored at zero, and it is computed before this reimbursement is applied. Success records `reimbursed_cents`, moves the request to terminal `REIMBURSED`, releases the full `est_cost_cents` from the budget's `encumbered_cents`, adds the reimbursed amount to its `spent_cents`, and bumps the budget's `version`. Denial — also segregated, carrying a `reason` — moves `ATTENDED` to terminal `REIMBURSEMENT_DENIED` and releases the encumbrance the same way, with nothing spent. Finally, an `APPROVED` workshop left incomplete more than thirty days past `ends_at` is expired by the ops checkpoint (§3.8), releasing its encumbrance into the budget.

### 3.11. Transcript Audit and Reversal

The `Auditor` — an opaque, independent identity — opens an `AuditCase` naming the `employee_id` and the `fiscal_year` under review; the case is born `OPEN` with `findings_count` zero and `opened_by_user_id` stamped. From `OPEN` the auditor raises findings, each carrying a `note`, moving the case `OPEN` → `FINDINGS_RAISED` and incrementing `findings_count`.

The heavier instrument is reversal. An auditor may reverse a transcript entry — naming the `transcript_entry_id` and a `reason` — while the case stands in `OPEN` or `FINDINGS_RAISED`, provided the entry belongs to the case's employee and fiscal year (else `ERR_AUDIT_ENTRY_MISMATCH`) and is still `AWARDED` (a second reversal of the same entry is `ERR_ENTRY_ALREADY_REVERSED`). Reversal marks the original entry `REVERSED`, stamps its `reversed_by_entry_id` with the new entry's id, and bumps its `version`; it then mints a compensating `AUDIT_REVERSAL` entry whose `clock_hours`, `district_credit`, and `state_ceu` are the negation of the original's values, whose `counts_toward_lane` mirrors the original, whose `growth_plan_id` mirrors the original's alignment, whose `status` is `AWARDED` — so the compensating entry's negated amounts participate in the `AWARDED`-only rollups of §3.6 and §3.9 alongside the now-excluded original — and whose `fiscal_year` derives from the logical now. The employee's `lane_credit_balance` is recomputed — the lane itself, per §3.9, is not rolled back. If the reversed entry was aligned, the plan's `aligned_credits` recompute runs and may un-fulfill the plan per §3.6. The case itself counts the reversal: `findings_count` increments, an `OPEN` case moves to `FINDINGS_RAISED`, and its `version` bumps.

Closure has two doors. A case in `FINDINGS_RAISED` with at least one finding resolves to terminal `RESOLVED`; a case still `OPEN` with `findings_count` exactly zero closes clean to terminal `CLOSED_CLEAN`. Reversal remains available while a case is `FINDINGS_RAISED`, so findings may accumulate before resolution.

## 4. Endpoint Definitions

Operations that create a new resource — a building, budget, employee, course, section, meeting, registration, survey response, workshop request, growth plan, compliance assignment, or audit case — return `201 Created`. Operations that modify an existing resource, drive a state transition, record attendance, or run an administrative checkpoint return `200 OK`. Every response body follows the envelope of §2.2; list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pd/_clock/set_current_utc` | Set the logical clock | PDCoordinator |
| POST | `/pd/ops-runs` | Run the district ops checkpoint sweep | PDCoordinator |
| POST | `/pd/buildings` | Create a building | PDCoordinator |
| GET | `/pd/buildings` | List buildings | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/buildings/{id}` | Get a building | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/budgets` | Create a building budget for a fiscal year | BusinessOfficer |
| GET | `/pd/budgets` | List budgets (filterable) | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/budgets/{id}` | Get a budget | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/budgets/{id}/open` | Open a budget for commitments | BusinessOfficer |
| POST | `/pd/budgets/{id}/close` | Close a budget (requires zero encumbrances) | BusinessOfficer |
| GET | `/pd/budgets/{id}/summary` | Budget summary with both availability variants | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/employees` | Create an employee | PDCoordinator |
| GET | `/pd/employees` | List employees | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/employees/{id}` | Get an employee | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/employees/{id}/set-status` | Set employee status (ACTIVE/ON_LEAVE/SEPARATED) | PDCoordinator |
| POST | `/pd/employees/{id}/advance-lane` | Advance the employee's salary lane | PDCoordinator |
| GET | `/pd/employees/{id}/transcript` | Transcript entries for an employee | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/courses` | Create a catalog course | PDCoordinator |
| GET | `/pd/courses` | List courses | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/courses/{id}` | Get a course | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/courses/{id}/retire` | Retire a course (no live sections) | PDCoordinator |
| POST | `/pd/sections` | Create a section (DRAFT) | PDCoordinator |
| GET | `/pd/sections` | List sections | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/sections/{id}` | Get a section | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/sections/{id}/publish` | Publish a section | PDCoordinator |
| PATCH | `/pd/sections/{id}` | Edit a PUBLISHED section; capacity increase triggers promotion | PDCoordinator |
| POST | `/pd/sections/{id}/cancel` | Cancel a section; drops/expirations cascade | PDCoordinator |
| POST | `/pd/sections/{id}/meetings` | Add a meeting to a section | PDCoordinator |
| GET | `/pd/sections/{id}/meetings` | List meetings of a section | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/meetings/{id}` | Get a section meeting | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/meetings/{id}/attendance` | Bulk-record attendance for one meeting (atomic) | Instructor, PDCoordinator |
| GET | `/pd/meetings/{id}/attendance` | Attendance records for a meeting | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/registrations` | Register a teacher for a section | Teacher, PDCoordinator |
| GET | `/pd/registrations` | List registrations | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/registrations/{id}` | Get a registration | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/registrations/{id}/attendance` | Attendance records for a registration | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/registrations/{id}/drop` | Drop a REGISTERED registration | Teacher, PDCoordinator |
| POST | `/pd/registrations/{id}/withdraw` | Withdraw a WAITLISTED registration | Teacher, PDCoordinator |
| POST | `/pd/registrations/{id}/verify-attendance` | Compute the attendance rate; sets VERIFIED or ABSENT | Instructor, PDCoordinator |
| POST | `/pd/registrations/{id}/waive-survey` | Waive the evaluation survey requirement | PDCoordinator |
| POST | `/pd/registrations/{id}/complete` | Complete a registration and award credit | PDCoordinator |
| POST | `/pd/registrations/{id}/survey` | Submit the evaluation survey | Teacher |
| GET | `/pd/registrations/{id}/survey` | Get the survey for a registration (0–1 items) | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/workshop-requests` | Create an external workshop request | Teacher, PDCoordinator |
| GET | `/pd/workshop-requests` | List workshop requests | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/workshop-requests/{id}` | Get a workshop request | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/workshop-requests/{id}/submit` | Submit a request for pre-approval | Teacher, PDCoordinator |
| POST | `/pd/workshop-requests/{id}/approve` | Approve a request before its start | BuildingAdmin |
| POST | `/pd/workshop-requests/{id}/reject` | Reject a submitted request | BuildingAdmin |
| POST | `/pd/workshop-requests/{id}/revise` | Revise a rejected request back to DRAFT | Teacher, PDCoordinator |
| POST | `/pd/workshop-requests/{id}/complete` | Submit completion evidence; awards transcript hours | Teacher, PDCoordinator |
| POST | `/pd/workshop-requests/{id}/reimburse` | Reimburse a completed workshop | BusinessOfficer |
| POST | `/pd/workshop-requests/{id}/deny-reimbursement` | Deny reimbursement | BusinessOfficer |
| POST | `/pd/growth-plans` | Create a growth plan (OCC on the employee) | Teacher, PDCoordinator |
| GET | `/pd/growth-plans` | List growth plans | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/growth-plans/{id}` | Get a growth plan | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/growth-plans/{id}/transcript-entries` | Transcript entries aligned to a plan | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/growth-plans/{id}/submit` | Submit a plan | Teacher, PDCoordinator |
| POST | `/pd/growth-plans/{id}/approve` | Approve a plan (building-scoped) | BuildingAdmin |
| POST | `/pd/growth-plans/{id}/return` | Return a plan to DRAFT | BuildingAdmin |
| POST | `/pd/growth-plans/{id}/close` | Close a plan at year end | PDCoordinator |
| POST | `/pd/compliance-assignments` | Assign required compliance training | PDCoordinator |
| GET | `/pd/compliance-assignments` | List assignments | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/compliance-assignments/{id}` | Get an assignment | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/compliance-assignments/{id}/waive` | Waive an assignment (segregated from creator) | PDCoordinator |
| POST | `/pd/compliance-assignments/{id}/extend` | Extend the due date (OCC on the assignment) | PDCoordinator |
| POST | `/pd/audit-cases` | Open a transcript audit case | Auditor |
| GET | `/pd/audit-cases` | List audit cases | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| GET | `/pd/audit-cases/{id}` | Get an audit case | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |
| POST | `/pd/audit-cases/{id}/raise-finding` | Raise a finding | Auditor |
| POST | `/pd/audit-cases/{id}/reverse-entry` | Reverse a transcript entry with a compensating entry | Auditor |
| POST | `/pd/audit-cases/{id}/resolve` | Resolve a case (requires findings) | Auditor |
| POST | `/pd/audit-cases/{id}/close-clean` | Close a case with no findings | Auditor |
| GET | `/pd/transcript-entries/{id}` | Get a transcript entry | Teacher, BuildingAdmin, Instructor, PDCoordinator, BusinessOfficer, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 400 Bad Request |
| `ERR_SECTION_NOT_OPEN` | 400 Bad Request |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 400 Bad Request |
| `ERR_BUDGET_NOT_OPEN` | 400 Bad Request |
| `ERR_BUDGET_HAS_ENCUMBRANCES` | 400 Bad Request |
| `ERR_BUDGET_ALREADY_EXISTS` | 400 Bad Request |
| `ERR_BUDGET_INSUFFICIENT` | 400 Bad Request |
| `ERR_PREREQUISITE_NOT_COMPLETED` | 400 Bad Request |
| `ERR_COMPLIANCE_HOLD` | 400 Bad Request |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_BUILDING_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_PLAN_NOT_APPROVED` | 400 Bad Request |
| `ERR_PLAN_YEAR_MISMATCH` | 400 Bad Request |
| `ERR_AUDIT_ENTRY_MISMATCH` | 400 Bad Request |
| `ERR_ENTRY_ALREADY_REVERSED` | 400 Bad Request |
| `ERR_REGISTRATION_NOT_YET_OPEN` | 400 Bad Request |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 400 Bad Request |
| `ERR_PREAPPROVAL_LEAD_TIME` | 400 Bad Request |
| `ERR_APPROVAL_AFTER_START` | 400 Bad Request |
| `ERR_WORKSHOP_NOT_STARTED` | 400 Bad Request |
| `ERR_ADVANCEMENT_WINDOW_CLOSED` | 400 Bad Request |
| `ERR_MEETING_OUTSIDE_SECTION` | 400 Bad Request |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_ROOM_CONFLICT` | 409 Conflict |
| `ERR_SURVEY_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_REVISION_LIMIT_EXCEEDED` | 400 Bad Request |
| `ERR_CAPACITY_BELOW_REGISTERED` | 400 Bad Request |
| `ERR_ATTENDANCE_INCOMPLETE` | 400 Bad Request |
| `ERR_ATTENDANCE_NOT_VERIFIED` | 400 Bad Request |
| `ERR_SURVEY_NOT_SUBMITTED` | 400 Bad Request |
| `ERR_LANE_MAX_REACHED` | 400 Bad Request |
| `ERR_ADVANCEMENT_ALREADY_THIS_FY` | 400 Bad Request |
| `ERR_LANE_CREDITS_INSUFFICIENT` | 400 Bad Request |
| `ERR_STALE_EMPLOYEE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ASSIGNMENT_VERSION` | 412 Precondition Failed |
