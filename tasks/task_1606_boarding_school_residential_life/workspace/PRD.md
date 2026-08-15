# Boarding School Residential Life API — Product Requirements Document

## 1. Introduction

A New England boarding school runs its residential program on a small set of interlocking obligations: students must sleep somewhere every night, parents must know where their children are on weekends, medications must be administered on schedule with an auditable trail, discipline must follow due process, and every break period converts the campus into a different operating mode. This document specifies the Boarding School Residential Life API — the backend service on which dorm-parent duty rosters, leave permissions, health-center medication ledgers, discipline hearings, and break-period housing and storage all run.

The system is designed around two recurring tensions. First, authority is deliberately fragmented: a home parent approves the family half of a leave, a dorm parent approves the school half, a nurse alone touches medications, a dean who reported a discipline case is barred from adjudicating it, and only a school administrator may mint configuration. Second, time is a first-class actor: the server keeps its own logical clock (initialized to `2026-08-01T00:00:00Z` before any test sets it), and sweeping that clock forward is what marks leaves overdue, expires unsigned departures, opens and closes break periods, and flags missed duty shifts.

The API is mounted under `/reslife`. Every resource lives at the top level of that prefix; relationships between resources are expressed through foreign keys carried in request bodies and query filters rather than through nested URLs.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming one of the declared roles. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized list, or that violates the ownership and scoping rules below, is rejected with `ERR_FORBIDDEN` (HTTP 403). These two checks run before any resource lookup: authentication first, authorization second, existence third.

The system recognizes eight roles, spelled exactly: `SchoolAdmin`, `Student`, `Parent`, `Guardian`, `DormParent`, `Nurse`, `Dean`, `FrontDesk`.

Identity is resolved differently per role, and this resolution is what binds `X-User-ID` to resource ownership:

- When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.
- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; any student-scoped action (filing or cancelling a leave, filing an appeal, requesting break housing, reserving or cancelling storage) is authorized only on records whose `student_id` equals `X-User-ID`.
- When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Parent`; family decisions on leave requests are authorized only for students whose `parent_id` equals `X-User-ID`.
- When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian`; family decisions on leave requests are authorized only for students whose `guardian_id` equals `X-User-ID` and whose guardian record is `APPROVED`.
- When `X-User-Role` is `DormParent`, `Nurse`, `Dean`, or `FrontDesk`, `X-User-ID` is the `id` of the acting `StaffMember` whose `staff_role` field matches the role (`DORM_PARENT`, `NURSE`, `DEAN`, or `FRONT_DESK` respectively). Dorm-scoped decisions compare the acting staff member's `dorm_id` against the dorm of the student's confirmed residency; shift-scoped actions compare `X-User-ID` against the shift's `staff_id` or `swap_requested_to_id`; recording a sign event stamps `recorded_by_staff_id` with the acting `X-User-ID`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. All list responses are sorted by `created_at` ascending. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Sweeps

The server maintains its own logical clock; it never reads the wall clock. Before any clock-set call, the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock runs every time-based sweep in a single pass:

- A `BreakPeriod` whose `starts_on` has been reached or passed moves from `UPCOMING` to `ACTIVE`; one whose `ends_on` has passed moves from `ACTIVE` to `CLOSED`, and closing cascades to break housing and storage as described in §3.8.
- An `APPROVED` leave whose six-hour departure grace has lapsed without a sign-out moves to `EXPIRED`.
- A `SIGNED_OUT` leave whose planned return instant has passed moves to `OVERDUE`.
- A `SCHEDULED` duty shift whose `duty_date` is in the past with incomplete checks moves to `MISSED`.

### 2.5. Common Resource Properties and Mutation Semantics

Most resources carry a standard set of system-managed fields: `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (refreshed on every material mutation), and `version` (an integer starting at its initial value and incrementing by exactly 1 on every material mutation of the entity's own stored fields or status, including mutations cascaded onto it by another entity's operation). Pure recomputation of a derived field, with no change to stored fields, does not increment `version`.

Three resources are append-only event records and carry only `id` and `created_at`: `SignEvent`, `NightCheck`, and `MedicationAdministration`. For these three, `updated_at` and `version` are absent entirely.

Foreign-key references such as `student_id`, `room_id`, `term_id`, `dorm_id`, `guardian_id`, `parent_id`, `break_period_id`, `storage_unit_id`, `target_staff_id`, `hearing_officer_id`, `witness_staff_id`, `roommate_assignment_id`, and `leave_request_id` must resolve to existing resources; an unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.6. Validation Order and Request Well-Formedness

Every write request passes through a fixed gauntlet, and the order is observable. Authentication (`ERR_UNAUTHENTICATED`) comes first, then authorization and ownership scoping (`ERR_FORBIDDEN`), then existence resolution of path identifiers and body foreign keys (`ERR_NOT_FOUND`), then structural well-formedness: a missing or malformed required field yields `ERR_MISSING_REQUIRED_FIELD` (HTTP 400), and a field outside its domain — an unknown enum value, a grade outside the nine-to-twelve range, a questionnaire integer outside one to five, `beds` outside one to four, `volume_cuft`, `weeks`, or `doses_total` below 1, a `returns_at` not strictly after `departs_at`, or an `ends_on` not strictly after `starts_on` — yields `ERR_INVALID_FIELD_VALUE` (HTTP 422). Only after all of that does the system check whether the target resource sits in a legitimate from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409), and only after state legality do the business, temporal, and fiscal rules of §3 run, each with the priority spelled out in its narrative. Where two rules could both reject the same request, the narrative names which error wins; the safety-first ordering around medication holds (§3.6) and the OCC-before-conflict ordering around duty shifts (§3.5) are the canonical examples.

### 2.7. Optimistic Concurrency Control

Two write endpoints take a mandatory optimistic-concurrency field naming the client's last-observed `version` of a parent entity; a mismatch with the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

- Creating a dorm assignment requires `expected_student_version`, matching the target student's current `version`. Because creating an assignment supersedes the student's existing `PROPOSED` assignment in the same term, a client whose view of the student predates another writer's change must not be allowed to proceed on a stale picture.
- Creating a duty shift requires `expected_dorm_version`, matching the target dorm's current `version`. Because creating a shift supersedes an existing `SCHEDULED` shift for the same dorm, date, and slot, the version check fires before the shift-conflict rule is evaluated.

### 2.8. Derived Counters, Standing Thresholds, and Monetary Precision

Demerit accounting distinguishes an official total from a provisional one, and both are exposed on the student record. The official `demerit_points` sums three sources: points assessed by night checks, points assessed by curfew-late sign-ins and late leave returns, and the `points_assessed` of discipline cases in `SANCTIONED` or `CLOSED` status. The `demerit_points_provisional` total adds, on top of the official figure, the `points_proposed` of cases still in `REPORTED`, `UNDER_REVIEW`, `HEARING_SCHEDULED`, or `APPEALED` — so identical data always yields a provisional figure at least as large as the official one, and strictly larger whenever a case is pending.

Discipline standing is recomputed after every change to `demerit_points`, from two inclusive thresholds: at least 20 points means `SUSPENDED`; at least 10 but fewer than 20 means `PROBATION`; fewer than 10 means `GOOD`. The boundaries are inclusive at the bottom of each band — exactly 10 points is `PROBATION`, exactly 20 is `SUSPENDED`. Standing moves in both directions: an appeal overturn that removes points can drop a student from `SUSPENDED` back to `PROBATION` or from `PROBATION` back to `GOOD`.

All money in the system is integer cents. Storage fees and break-housing charges round half-up to whole cents, and storage rounding happens per reservation line before any summation — the rejected alternative of summing-then-rounding produces a different total (two early-bird one-cubic-foot, one-week lines total 426 cents when rounded per line, versus 425 cents if rounded only after aggregation).

### 2.9. Cascading Consistency Across the Aggregate

The school's aggregate roots cascade their lifecycle events downward. Closing a term ends or supersedes every assignment in it, clears roommate links on both partners, recomputes room occupancy, and cancels the term's in-flight leave requests. Withdrawing a student ends or supersedes their active-term assignments, cancels their pending leaves and break-housing requests, discontinues their active and held medication orders, and releases their storage reservations. Approving a guardian raises each ward's weekend-leave allowance by the international bonus; suspending a guardian removes that bonus and auto-denies each ward's still-`REQUESTED` leaves. Each cascade increments the `version` of every entity it materially mutates and refreshes that entity's `updated_at`.

Rooms self-regulate their `status`: a confirm that raises `beds_assigned` to equal `beds` flips the room from `AVAILABLE` to `FULL`, and an end or supersede that lowers `beds_assigned` below `beds` flips it back. Only a room with zero current occupants may be moved to `BLOCKED`, which is a manual, administrator-driven state.

## 3. Business Logic & Workflows

### 3.1. Terms, Dorms, and Rooms: Framing the School Year

A school administrator opens the year by creating a `Term` with a `name` (for example `FALL_2026`), a `starts_on`, and an `ends_on` strictly later than `starts_on`. New terms are `UPCOMING`. Activating a term moves it to `ACTIVE` and is refused with `ERR_ACTIVE_TERM_EXISTS` while any other term is already `ACTIVE` — the school runs exactly one term at a time. Term activation, assignment creation, assignment confirmation, leave creation, night checks, and sign events all require an `ACTIVE` term to exist; their absence surfaces as `ERR_TERM_NOT_ACTIVE`.

Closing the active term is the year's big cascade. Every `CONFIRMED` assignment in that term moves to `ENDED` with `check_out_at` stamped to the current logical instant; every `PROPOSED` assignment moves to `SUPERSEDED`. Each ended assignment clears the mutual roommate link — the partner assignment's `roommate_assignment_id` and `compatibility_score` both reset to null. Each affected room recomputes `beds_assigned` and `beds_available`, and a `FULL` room whose confirmed count drops below its capacity flips itself back to `AVAILABLE`. Every leave request of the term's students that is still `REQUESTED`, `PARENT_APPROVED`, or `APPROVED` is cancelled with `denial_reason` set to `TERM_CLOSED`. The term lands in `CLOSED`, which is terminal.

Dorms are created with a `name`, a `gender_policy` of `MALE_ONLY`, `FEMALE_ONLY`, or `ANY`, and two curfew times in 24-hour `HH:MM` local format: `curfew_weekday` governs Sunday-through-Thursday nights and `curfew_weekend` governs Friday and Saturday nights. A dorm's `posture` starts `OPEN`. When a break period is `ACTIVE`, an administrator may close a dorm for break, moving its posture to `CLOSED_FOR_BREAK`; reopening restores `OPEN` and requires nothing further. A closed-for-break dorm refuses new assignment confirmations and refuses ordinary sign-ins — the exception being students holding an `APPROVED` or `CHECKED_IN` break-housing request — while night checks remain allowed; violations surface as `ERR_DORM_CLOSED`.

Rooms belong to a dorm via `dorm_id`, carry a `room_number` unique within the dorm, and sleep between one and four students (`beds`). Three counters describe occupancy: the dorm-level `beds_total` sums `beds` across all its rooms; `occupancy_physical` counts `CONFIRMED` assignments in the dorm's rooms; `occupancy_projected` adds the `PROPOSED` ones on top of physical, so it reads strictly higher whenever proposals are pending; `beds_available` is `beds_total` minus `occupancy_physical`. At room level, `beds_assigned` counts `CONFIRMED` assignments in that room and `beds_available` is `beds` minus `beds_assigned`. An administrator may block an empty room for maintenance — attempting to block a room with any occupant is rejected with `ERR_ROOM_OCCUPIED` — and unblock it later.

### 3.2. People: Parents, Guardians, Staff, and Students

A `Parent` record is just a `full_name` and `email` — the home contact for a domestic student. A `Guardian` is the local guardian of an international student: `full_name`, `email`, `city`, and a `max_wards` capacity that defaults to 3 and may range from 1 to 10. Guardians are created `PENDING`; an administrator approves or suspends them. Approval flips the guardian to `APPROVED` and immediately raises every ward's weekend-leave allowance by the international bonus described in §3.4. Suspension flips the guardian to `SUSPENDED`, removes that bonus, auto-denies every ward's leave still sitting in `REQUESTED` with `denial_reason` set to `GUARDIAN_SUSPENDED`, and reroutes future family decisions for those wards to a dean acting as proxy. The `wards_assigned` counter tracks how many `ENROLLED` or `ON_LEAVE` students reference the guardian.

Staff members carry a `full_name`, a `staff_role` of `DORM_PARENT`, `NURSE`, `DEAN`, or `FRONT_DESK`, an optional `dorm_id` naming the home dorm of a dorm parent (null is allowed for the other roles), and an `is_active` employment flag that defaults to true.

A `Student` record captures `legal_name`, `grade` from 9 to 12, `gender` of `MALE` or `FEMALE`, an `is_international` flag, a `parent_id` pointing at the home parent, and the roommate questionnaire: `sleep_schedule` (1 for an early bird, 5 for a night owl), `cleanliness`, `noise_tolerance`, and `guests_comfort`, each an integer from 1 to 5. An international student must be created with a `guardian_id` (its absence is `ERR_GUARDIAN_REQUIRED`), that guardian must already be `APPROVED` (otherwise `ERR_GUARDIAN_NOT_APPROVED`), and assigning a new ward is refused with `ERR_GUARDIAN_AT_CAPACITY` once the guardian's `wards_assigned` has reached `max_wards`. A domestic student's `guardian_id` must be null. The same guardian-approval gate is re-applied at assignment confirmation: an international student whose guardian is no longer `APPROVED` cannot be confirmed into a room.

Students carry two parallel dimensions on one record. The enrollment axis moves under administrator control through the enrollment transition with a `to_status` of `ON_LEAVE`, `ENROLLED`, `WITHDRAWN`, or `GRADUATED`. `ENROLLED` and `ON_LEAVE` toggle freely in both directions; students `ON_LEAVE` are excluded from required night checks. Withdrawal — reachable from either `ENROLLED` or `ON_LEAVE` — is the big cascade of §2.9: active-term `CONFIRMED` assignments end (and `PROPOSED` ones supersede, roommate links clearing on the partner), pending leaves in `REQUESTED`, `PARENT_APPROVED`, or `APPROVED` cancel with `denial_reason` set to `STUDENT_WITHDRAWN`, medication orders in `ACTIVE` or `HOLD` move to `DISCONTINUED`, break-housing requests in `REQUESTED` or `APPROVED` cancel, and `RESERVED` storage reservations cancel with capacity released. Graduation requires that the student hold no `CONFIRMED` assignment in the active term — the residence must be ended first, for example by term close — otherwise `ERR_ACTIVE_ASSIGNMENT_EXISTS`. The standing axis, `discipline_standing`, is computed rather than commanded: it tracks the official point total against the thresholds of §2.8.

Updating a student's `grade` or any questionnaire field is an administrator action that recomputes downstream values: a `grade` change refreshes `weekend_leave_allowance`, and any questionnaire change recomputes the `compatibility_score` stored on both sides of a linked assignment pair.

### 3.3. Dorm Assignments and Roommate Matching

Housing begins when an administrator proposes a `DormAssignment`, submitting the `student_id`, `room_id`, `term_id`, and the OCC field `expected_student_version` described in §2.7. Creating a new assignment for a student who already has a `PROPOSED` assignment in the same term supersedes the old one — the earlier proposal moves to `SUPERSEDED` and any roommate link it held is cleared on the partner. An optional `roommate_assignment_id` at creation links the new assignment mutually to another: the link target must belong to a different student (`ERR_SELF_ROOMMATE`), must sit in the same room and same term, and must be `PROPOSED` or `CONFIRMED` (`ERR_ROOMMATE_NOT_IN_ROOM`). When a mutual link is made — at creation or later through the link-roommate action, which takes the same `roommate_assignment_id` and applies the same two checks — both assignments store each other's id and both store the same `compatibility_score`.

The compatibility score starts from 100 and subtracts weighted questionnaire distances: twelve points per unit of difference in `sleep_schedule`, eight per unit of difference in `cleanliness`, eight per unit of difference in `noise_tolerance`, and four per unit of difference in `guests_comfort`; the result floors at 0. A student with no linked roommate has a null `compatibility_score`, and any questionnaire update on either partner recomputes the score on both linked assignments.

Confirmation is the gated transition from `PROPOSED` to `CONFIRMED`. The checks run in a deliberate order, and the winning error matters. The term must be `ACTIVE` and the student `ENROLLED` (`ERR_TERM_NOT_ACTIVE`, `ERR_STUDENT_NOT_ENROLLED`); the dorm must be `OPEN` (`ERR_DORM_CLOSED`); the room must not be `BLOCKED` (a blocked room is rejected with `ERR_INVALID_STATE`) and must have at least one bed free — a `FULL` room fails only the fiscal bed check with `ERR_ROOM_FULL`; the dorm's `gender_policy` must accept the student's gender, where `ANY` accepts everyone, `MALE_ONLY` accepts `MALE`, and `FEMALE_ONLY` accepts `FEMALE` (`ERR_DORM_GENDER_MISMATCH`); an international student's guardian must be `APPROVED` (`ERR_GUARDIAN_NOT_APPROVED`); and the student must not already hold another `CONFIRMED` assignment in the same term (`ERR_ACTIVE_ASSIGNMENT_EXISTS`). A successful confirm stamps `check_in_at` to the current logical instant, increments the room's `beds_assigned`, and flips the room to `FULL` when the count reaches capacity.

Ending a `CONFIRMED` assignment — directly, or by cascade from term close or withdrawal — stamps `check_out_at`, decrements the room's `beds_assigned`, flips a `FULL` room back to `AVAILABLE`, and dissolves the roommate link on both sides: the partner's `roommate_assignment_id` and `compatibility_score` reset to null along with this assignment's own link. `SUPERSEDED` and `ENDED` are the terminal states.

### 3.4. Leave Requests: Two Keys, One Door

A leave request is filed by the student who will travel — the acting student's own record is the subject — with a `leave_type` of `WEEKEND_OVERNIGHT`, `DAY_PASS`, or `BREAK_TRAVEL`, a free-text `destination`, a `departs_at` that must lie in the future (`ERR_LEAVE_IN_PAST`), and a `returns_at` strictly after `departs_at`. Filing requires an `ACTIVE` term and an `ENROLLED` student. One student's non-terminal leaves may not overlap in time: the half-open interval from `departs_at` (inclusive) to `returns_at` (exclusive) must not intersect any other non-terminal leave of the same student, though intervals that merely touch at an endpoint are allowed; a collision is rejected with `ERR_LEAVE_WINDOW_OVERLAP`.

Weekend overnight leaves draw on a per-term allowance. The allowance is computed from the student's grade — a base of 4 for grades 9 and 10, 6 for grade 11, and 8 for grade 12 — multiplied by a standing factor: full allowance for `GOOD`, half for `PROBATION` (rounding down to a whole number), and zero for `SUSPENDED`. An international student whose guardian is currently `APPROVED` adds 1 on top of the floored product. The final `weekend_leave_allowance` is capped at 10. The consumption counter `weekend_leaves_used` counts the student's `WEEKEND_OVERNIGHT` requests in the currently active term — measured by `departs_at` falling within the term's `starts_on` to `ends_on` range, both ends inclusive — whose status is `APPROVED`, `SIGNED_OUT`, `OVERDUE`, or `RETURNED`; denied, cancelled, and expired requests do not count. The allowance check is enforced twice: at filing, and again at the dorm-parent approval step, each time requiring usage strictly below the allowance; exhaustion surfaces as `ERR_LEAVE_ALLOWANCE_EXHAUSTED`.

Approval is a two-key process. The family half comes first: for a domestic student, the acting `Parent` must be the student's own `parent_id`; for an international student, the acting `Guardian` must be the student's `guardian_id` and hold `APPROVED` status — except that when the guardian is `SUSPENDED`, a `Dean` may act as proxy. The family decision carries a `decision` of `APPROVE` or `DENY` and an optional `denial_reason`; approval moves the request from `REQUESTED` to `PARENT_APPROVED` and stamps `decided_by_parent_id` with the decider's `X-User-ID`, while denial moves it to `DENIED` with `denial_reason` recorded. The school half is a dorm-parent decision on a `PARENT_APPROVED` request, and it is dorm-scoped: the acting dorm parent's `dorm_id` must match the dorm of the student's `CONFIRMED` assignment in the active term — a student with no confirmed residency at all is rejected with `ERR_NO_CONFIRMED_RESIDENCY`, while a residency in a different dorm is an ordinary scope failure. Approval is refused when the student's standing is `SUSPENDED` (`ERR_STUDENT_SUSPENDED`), and for a weekend overnight the allowance is re-checked. A dorm approval moves the request to `APPROVED`, stamps `decided_by_staff_id`, and consumes one unit of the weekend allowance; a dorm denial moves it to `DENIED`. Either denial records the `denial_reason` supplied with the decision.

Departure happens at the front desk. Signing out is allowed only inside a grace window running from two hours before `departs_at` to six hours after it; outside that window the attempt is rejected with `ERR_SIGN_OUT_WINDOW`. A successful sign-out moves the request to `SIGNED_OUT`, stamps `signed_out_at`, and appends a `SIGN_OUT` sign event linked through `leave_request_id`. If the student never signs out, the logical-clock sweep moves an `APPROVED` request to `EXPIRED` once the six-hour grace has lapsed, releasing the consumed allowance unit. Once signed out, passage of the planned return instant flips the request to `OVERDUE` by sweep.

Return is recorded at the desk from either `SIGNED_OUT` or `OVERDUE`. It stamps `returned_at`, appends a `SIGN_IN` sign event, computes `late_return_minutes` as the whole minutes by which the actual return exceeded the planned `returns_at` (never below zero), and assesses late points against the student's official demerit total: no points when the student is on time, 1 point for up to and including 15 minutes late, 2 points from 16 through 60 minutes, and 3 points beyond 60 minutes. Standing re-evaluation runs afterward, so a late return can flip a student across a threshold. A student may also cancel their own request directly — `X-User-ID` must equal the request's `student_id` — from any of `REQUESTED`, `PARENT_APPROVED`, or `APPROVED`; cancelling an `APPROVED` weekend overnight releases the allowance unit it consumed. `DENIED`, `CANCELLED`, `EXPIRED`, and `RETURNED` are terminal.

### 3.5. Duty Shifts and Night Checks

Duty coverage is scheduled by an administrator one `DutyShift` at a time: a `dorm_id`, an assignee `staff_id` naming a dorm parent, a `duty_date`, a `shift_slot` of `WEEKDAY_NIGHT`, `WEEKEND_DAY`, or `WEEKEND_NIGHT`, and the OCC field `expected_dorm_version` (§2.7). Creating a shift for a dorm, date, and slot that already has a `SCHEDULED` shift supersedes the old one: it moves to `CANCELLED` with `cancel_reason` set to `SUPERSEDED`. A staff member may not hold two non-cancelled shifts on the same date with conflicting slots — the same slot always conflicts, `WEEKEND_DAY` and `WEEKEND_NIGHT` never conflict with each other, and `WEEKDAY_NIGHT` conflicts only with another `WEEKDAY_NIGHT`; a violation is `ERR_SHIFT_CONFLICT`. On a create, the shift being superseded by this very request is excluded from the conflict set, and the dorm version check runs before the conflict check.

A scheduled dorm parent may request a swap by naming a `target_staff_id`. The request must come from the current assignee — `X-User-ID` must equal the shift's `staff_id` — and the target must be an active dorm parent other than the current assignee with no conflicting shift that date, under the same slot-conflict rules; failures are `ERR_SWAP_TARGET_INELIGIBLE`. Requesting a swap moves the shift to `SWAP_PENDING` and stamps `swap_requested_to_id`. The target then responds with `accept` true or false — only the named target may respond, meaning `X-User-ID` must equal `swap_requested_to_id`. Acceptance moves ownership: `staff_id` becomes the target, `swap_requested_to_id` clears, and the shift returns to `SCHEDULED` under its new owner. Declining leaves `staff_id` unchanged, clears `swap_requested_to_id`, and returns the shift to `SCHEDULED`.

During the shift, the on-duty dorm parent records `NightCheck` rows against the shift: a `student_id`, a `check_kind` of `BED_CHECK` or `STUDY_HALL`, and a `result` of `PRESENT`, `LATE_ARRIVAL`, `ABSENT_EXCUSED`, or `ABSENT_UNEXCUSED`; `checked_at` stamps to the logical clock at recording. Recording a night check requires an active term and an `ENROLLED` student who holds a `CONFIRMED` assignment in the shift's dorm for the active term (`ERR_NOT_RESIDENT`), the actor must be the shift's assignee, and only one check per shift, student, and kind may exist (`ERR_CHECK_ALREADY_RECORDED`). Points follow a fixed table: for a bed check, `PRESENT` and `ABSENT_EXCUSED` assess 0, `LATE_ARRIVAL` assesses 1, and `ABSENT_UNEXCUSED` assesses 3; for study hall the same table applies except that `ABSENT_UNEXCUSED` assesses 2. The assessed points land on the check's `points_assessed` and add into the student's official demerit total, after which standing re-evaluation runs — a student pushed to `SUSPENDED` by a night check has every pending leave cancelled with `denial_reason` set to `STANDING_SUSPENDED`.

A shift completes only when every `ENROLLED` student with a confirmed assignment in the shift's dorm has a `BED_CHECK` recorded on that shift; attempting completion early is `ERR_CHECKS_OUTSTANDING`. The completing actor must be the assignee. If the date passes with checks incomplete, the sweep marks the shift `MISSED`. `COMPLETED`, `MISSED`, and `CANCELLED` are terminal.

### 3.6. Health Center: Medication Orders and Administrations

A nurse opens a `MedicationOrder` for an `ENROLLED` student with a `medication_name`, a `dose_mg`, a `slot` of `MORNING`, `NOON`, `EVENING`, or `BEDTIME`, a `doses_total` of at least 1, an optional `refill_threshold` defaulting to 5, an `is_controlled` flag, and the `prescriber_name`. One active order per student, medication, and slot is the limit — a second `ACTIVE` order for the same triple is rejected with `ERR_DUPLICATE_ACTIVE_ORDER`. The order's `doses_remaining` counts down from `doses_total` as administrations are recorded, and `low_stock` turns true when `doses_remaining` falls to or below `refill_threshold` — the boundary is inclusive.

Administrations are the dose ledger. For each scheduled day — at most one administration per order per `scheduled_date`, enforced as `ERR_DOSE_ALREADY_LOGGED` — the nurse records an `outcome` of `ADMINISTERED`, `REFUSED`, or `OMITTED_HOLD`, with an optional free-text `notes`. The acting nurse's `X-User-ID` is stamped as `administered_by_staff_id`. Only `ADMINISTERED` rows decrement `doses_remaining`; refused and held doses leave the count untouched. When an administered dose brings `doses_remaining` to exactly zero, the order flips itself from `ACTIVE` to `COMPLETED`.

Two safety rules outrank the generic state checks, and their priority order is deliberate. An administration attempted on a `DISCONTINUED` or `COMPLETED` order is rejected with `ERR_ORDER_NOT_ACTIVE`. An administration attempted while the order sits in `HOLD` is rejected with `ERR_MEDICATION_ON_HOLD` — a distinct safety error that is evaluated before the duplicate-dose uniqueness check, so that a held order always surfaces the hold rather than a referential collision. For a controlled order (`is_controlled`), an `ADMINISTERED` row must carry a `witness_staff_id` naming an active staff member who is not the administering nurse; a missing witness, a witness equal to the nurse, or an inactive witness is rejected with `ERR_WITNESS_REQUIRED`.

A nurse may place an `ACTIVE` order on `HOLD` with a `reason`, which is recorded as `hold_reason`; resuming returns it to `ACTIVE`, clears `hold_reason`, and leaves `doses_remaining` untouched. Discontinuing — from either `ACTIVE` or `HOLD`, or by cascade when the student withdraws — moves the order to `DISCONTINUED`. `DISCONTINUED` and `COMPLETED` are terminal.

### 3.7. Discipline: Cases, Hearings, and Appeals

A dean or dorm parent reports a discipline case with the `student_id`, a `category` of `MINOR` or `MAJOR`, a free-text `description`, and the `points_proposed`. The reporter's `X-User-ID` is stamped as `reported_by_staff_id`, and the case opens in `REPORTED`. Pending cases feed the provisional demerit total (§2.8) without touching the official one.

Review begins when a dean moves the case to `UNDER_REVIEW`. What happens next depends on category, and the segregation-of-duties rule runs through all of it: the dean who adjudicates must not be the reporter, on pain of `ERR_REPORTER_CANNOT_ADJUDICATE`. For a `MINOR` case, a dean other than the reporter may record an outcome directly from `UNDER_REVIEW`. For a `MAJOR` case, the outcome must wait for a hearing: recording an outcome on a `MAJOR` case still in `UNDER_REVIEW` is rejected with `ERR_HEARING_REQUIRED`. Scheduling a hearing names a `hearing_officer_id` — an active dean who is not the reporter — and a `hearing_at` that must lie in the future (`ERR_HEARING_IN_PAST`), moving the case to `HEARING_SCHEDULED`.

Recording an outcome takes an `outcome` of sanctioned or dismissed, with an optional `sanction_type` and `points_assessed`. From `HEARING_SCHEDULED`, only the named hearing officer may record. A sanctioned outcome sets `sanction_type` to one of `NONE`, `WARNING`, `PROBATION`, `SUSPENSION`, or `EXPULSION`, writes the supplied `points_assessed` onto the case, stamps `decided_at`, adds the points into the student's official demerit total, and runs standing re-evaluation — a threshold crossing into `SUSPENDED` cascade-cancels the student's pending leaves with `denial_reason` set to `STANDING_SUSPENDED`. A dismissed outcome stamps `decided_at`, applies no points, and removes the case from the provisional input set.

The student who is the subject of a `SANCTIONED` case — `X-User-ID` must equal the case's `student_id` — may appeal, once only: a second appeal is rejected with `ERR_APPEAL_LIMIT_REACHED`, and an appeal filed more than 168 hours after `decided_at` is rejected with `ERR_APPEAL_WINDOW_CLOSED`. Appealing moves the case to `APPEALED` and sets `appeal_count` to 1. A dean other than the reporter then decides the appeal, supplying a `decision` of `UPHOLD` or `OVERTURN`. Upholding returns the case to `SANCTIONED` and accepts an optional `adjusted_points`: when provided, `points_assessed` is replaced with the adjusted figure and the student's official total is shifted by the delta between old and new, with standing re-evaluation following. Overturning moves the case to `DISMISSED`, subtracts the case's `points_assessed` from the student's official total exactly as they were added, zeroes the case's `points_assessed`, and re-evaluates standing — the exact reversal is what can drop a student back below a threshold. A `SANCTIONED` case closes once its appeal window has passed or its single appeal has been filed and decided; closing moves it to `CLOSED`. `DISMISSED` and `CLOSED` are terminal.

### 3.8. Breaks, Break Housing, and Storage

Break periods are created with a `name` (for example `THANKSGIVING_2026`), a `kind` of `THANKSGIVING`, `WINTER`, `SPRING`, or `SUMMER`, a `starts_on`, an `ends_on` strictly later, and a `housing_available` flag. Breaks open as `UPCOMING` and are advanced purely by the logical clock: the sweep moves a break to `ACTIVE` when the current date reaches `starts_on`, and to `CLOSED` when the date passes `ends_on`. Closing a break cascades: every break-housing request still `CHECKED_IN` is checked out automatically, and every storage reservation still `RESERVED` moves to `EXPIRED` with its fee retained and its capacity released.

Break housing exists for international students only — a domestic student's request is rejected with `ERR_NOT_ELIGIBLE_BREAK_HOUSING`. The student files a request naming a `break_period_id` with an optional free-text `reason`; one non-terminal request per student per break is the limit (`ERR_DUPLICATE_BREAK_REQUEST`). A dean or school administrator decides. Denial moves the request to `DENIED`. Approval — allowed while the break is `UPCOMING` or `ACTIVE` — moves it to `APPROVED` and computes the full fee breakdown in a pinned evaluation order, so that no figure depends on a later one:

1. `room_charge_cents` is a flat 20000 cents.
2. `storage_total_cents` sums the `fee_cents` of the student's storage reservations for the same break whose status is `RESERVED`, `CHECKED_IN`, or `EXPIRED` — an expired reservation keeps its fee, while retrieved and cancelled reservations are excluded.
3. `deposit_credit_cents` is ten percent of the sum of the room charge and the storage total, rounded half-up to whole cents, and capped at 5000 cents.
4. `fee_cents` is the room charge plus the storage total minus the deposit credit.

Check-in to break housing is a dorm-parent action allowed only while the break is `ACTIVE` (`ERR_BREAK_NOT_ACTIVE`), moving the request from `APPROVED` to `CHECKED_IN`. Check-out, or the break-close sweep, moves it to `CHECKED_OUT`. Withdrawal of the student cancels a `REQUESTED` or `APPROVED` request. In this version of the flow the `room_id` on the request stays null — temporary break rooms are not assigned at approval.

Storage units are created with a `label` and a `capacity_cuft` of at least 1, opening as `OPEN`; a unit may be `SEALED`, and a sealed unit refuses new reservations (`ERR_INVALID_STATE`). A student reserves space by naming a `storage_unit_id`, a `break_period_id`, a `volume_cuft` and a `weeks` count (each at least 1), and a free-text `items_description`. Aggregate capacity is enforced per unit and break: the sum of `volume_cuft` over that unit's reservations for the same break in `RESERVED` or `CHECKED_IN` status, plus the new volume, must not exceed `capacity_cuft` (`ERR_STORAGE_CAPACITY_EXCEEDED`). The unit's `used_cuft` tracks exactly that sum.

Each reservation is priced individually at creation. The base rate is 250 cents per cubic foot per week. A reservation created at least 30 days before its break's `starts_on` earns the `early_bird` flag and a fifteen-percent discount on the rate. The line fee is the volume multiplied by the weeks multiplied by the applicable rate, rounded half-up to whole cents per reservation line — never aggregated before rounding, per §2.8. The `fee_cents` lands on the reservation and later feeds the break-housing storage total.

While the break is `ACTIVE`, a dorm parent or front-desk attendant checks stored items in (`RESERVED` to `CHECKED_IN`; `ERR_BREAK_NOT_ACTIVE` otherwise). Retrieval moves a `CHECKED_IN` reservation to `RETRIEVED` and releases its volume from `used_cuft`. The student may cancel a `RESERVED` reservation — again `X-User-ID` must equal the reservation's `student_id` — which releases capacity and drops the fee from any future break-housing billing. The break-close sweep expires never-checked-in reservations, keeping their fee but releasing their capacity. `RETRIEVED`, `CANCELLED`, and `EXPIRED` are terminal.

### 3.9. Sign Events and Curfew Accounting

Beyond leave-linked movements, the front desk (or a dorm parent for dorm-originated events) records free-standing campus sign-outs and sign-ins: a `student_id`, an `event_type` of `SIGN_OUT` or `SIGN_IN`, an optional `occurred_at` defaulting to the current logical clock when omitted, and an optional `leave_request_id` link. The recorder's `X-User-ID` is stamped as `recorded_by_staff_id`. Recording any sign event requires an active term and an `ENROLLED` student.

A sign-in is where curfew bites. The student must hold a `CONFIRMED` assignment in the active term (`ERR_NOT_RESIDENT`), which fixes the dorm whose curfew applies. The applicable curfew is the dorm's `curfew_weekend` when the event falls on a Friday or Saturday, and `curfew_weekday` otherwise. The `minutes_late` on the event is the whole minutes by which `occurred_at` passed that same-day curfew, never below zero, and always 0 for a sign-out. Late points then ladder into the student's official demerit total on the same schedule as leave returns: 0 points when on time, 1 point for 1 through 15 minutes late, 2 for 16 through 60, and 3 beyond 60 — after which standing re-evaluation runs, with the usual `SUSPENDED` cascade. When the dorm is closed for break, ordinary sign-ins are refused with `ERR_DORM_CLOSED`, the exception being students whose break-housing request is `APPROVED` or `CHECKED_IN`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Request payloads, computed fields, side effects, and failure modes for each endpoint are specified in §2 and §3; the table below is only an index of methods, paths, and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reslife/_clock/set_current_utc` | Advance the logical clock and run all time-based sweeps | SchoolAdmin |
| POST | `/reslife/terms` | Create a term | SchoolAdmin |
| GET | `/reslife/terms` | List terms, optional `status` filter | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| GET | `/reslife/terms/{term_id}` | Get a term | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| POST | `/reslife/terms/{term_id}/activate` | Activate an UPCOMING term | SchoolAdmin |
| POST | `/reslife/terms/{term_id}/close` | Close the active term with full cascade | SchoolAdmin |
| POST | `/reslife/dorms` | Create a dorm | SchoolAdmin |
| GET | `/reslife/dorms` | List dorms, optional `posture` filter | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk, Student |
| GET | `/reslife/dorms/{dorm_id}` | Get a dorm with computed occupancy fields | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk, Student |
| POST | `/reslife/dorms/{dorm_id}/close-for-break` | Set dorm posture to CLOSED_FOR_BREAK | SchoolAdmin |
| POST | `/reslife/dorms/{dorm_id}/reopen` | Set dorm posture to OPEN | SchoolAdmin |
| POST | `/reslife/rooms` | Create a room in a dorm | SchoolAdmin |
| GET | `/reslife/rooms` | List rooms, optional `dorm_id` and `status` filters | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| GET | `/reslife/rooms/{room_id}` | Get a room | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| POST | `/reslife/rooms/{room_id}/block` | Block an empty room | SchoolAdmin |
| POST | `/reslife/rooms/{room_id}/unblock` | Unblock a room | SchoolAdmin |
| POST | `/reslife/parents` | Create a parent record | SchoolAdmin |
| GET | `/reslife/parents/{parent_id}` | Get a parent | SchoolAdmin, Dean, DormParent |
| POST | `/reslife/guardians` | Create a guardian (PENDING) | SchoolAdmin |
| GET | `/reslife/guardians` | List guardians, optional `status` filter | SchoolAdmin, Dean, DormParent |
| GET | `/reslife/guardians/{guardian_id}` | Get a guardian | SchoolAdmin, Dean, DormParent |
| POST | `/reslife/guardians/{guardian_id}/approve` | Approve a guardian | SchoolAdmin |
| POST | `/reslife/guardians/{guardian_id}/suspend` | Suspend a guardian with ward cascade | SchoolAdmin |
| POST | `/reslife/staff` | Create a staff member | SchoolAdmin |
| GET | `/reslife/staff` | List staff, optional `dorm_id`, `staff_role`, `is_active` filters | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| GET | `/reslife/staff/{staff_id}` | Get a staff member | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| POST | `/reslife/students` | Create a student with questionnaire | SchoolAdmin |
| GET | `/reslife/students` | List students, optional `parent_id`, `guardian_id`, `grade`, `discipline_standing`, `enrollment_status` filters | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk |
| GET | `/reslife/students/{student_id}` | Get a student with computed fields | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk, Student, Parent, Guardian |
| PATCH | `/reslife/students/{student_id}` | Update grade or questionnaire fields | SchoolAdmin |
| POST | `/reslife/students/{student_id}/enrollment` | Enrollment transition per `to_status` | SchoolAdmin |
| POST | `/reslife/dorm-assignments` | Propose an assignment (OCC on student) | SchoolAdmin |
| GET | `/reslife/dorm-assignments` | List assignments, optional `student_id`, `room_id`, `term_id`, `status`, `roommate_assignment_id` filters | SchoolAdmin, DormParent, Dean |
| GET | `/reslife/dorm-assignments/{assignment_id}` | Get an assignment | SchoolAdmin, DormParent, Dean, Student |
| POST | `/reslife/dorm-assignments/{assignment_id}/confirm` | Confirm a PROPOSED assignment | SchoolAdmin |
| POST | `/reslife/dorm-assignments/{assignment_id}/end` | End a CONFIRMED assignment | SchoolAdmin |
| POST | `/reslife/dorm-assignments/{assignment_id}/link-roommate` | Mutually link two same-room assignments | SchoolAdmin |
| POST | `/reslife/leave-requests` | Student files a leave request | Student |
| GET | `/reslife/leave-requests` | List leaves, optional `student_id`, `status`, `leave_type` filters | SchoolAdmin, DormParent, Dean, Student, Parent, Guardian |
| GET | `/reslife/leave-requests/{leave_id}` | Get a leave request | SchoolAdmin, DormParent, Dean, Student, Parent, Guardian |
| POST | `/reslife/leave-requests/{leave_id}/parent-decision` | Family decision per `decision` | Parent, Guardian, Dean |
| POST | `/reslife/leave-requests/{leave_id}/dorm-decision` | Dorm-parent decision per `decision` | DormParent |
| POST | `/reslife/leave-requests/{leave_id}/cancel` | Student cancels own non-terminal leave | Student |
| POST | `/reslife/leave-requests/{leave_id}/sign-out` | Record departure in the grace window | FrontDesk, DormParent |
| POST | `/reslife/leave-requests/{leave_id}/return` | Record return and assess late points | FrontDesk, DormParent |
| POST | `/reslife/sign-events` | Record a campus sign-out or sign-in | FrontDesk, DormParent |
| GET | `/reslife/sign-events` | List sign events, optional `student_id`, `leave_request_id`, `recorded_by_staff_id`, `event_type` filters | SchoolAdmin, DormParent, Dean, FrontDesk, Student |
| GET | `/reslife/sign-events/{event_id}` | Get a sign event | SchoolAdmin, DormParent, Dean, FrontDesk, Student |
| POST | `/reslife/duty-shifts` | Schedule a duty shift (OCC on dorm) | SchoolAdmin |
| GET | `/reslife/duty-shifts` | List shifts, optional `dorm_id`, `staff_id`, `duty_date`, `status`, `swap_requested_to_id` filters | SchoolAdmin, DormParent, Dean |
| GET | `/reslife/duty-shifts/{shift_id}` | Get a duty shift | SchoolAdmin, DormParent, Dean |
| POST | `/reslife/duty-shifts/{shift_id}/request-swap` | Assignee requests a swap to `target_staff_id` | DormParent |
| POST | `/reslife/duty-shifts/{shift_id}/swap-respond` | Swap target responds with `accept` | DormParent |
| POST | `/reslife/duty-shifts/{shift_id}/complete` | Complete a shift after all bed checks | DormParent |
| POST | `/reslife/duty-shifts/{shift_id}/night-checks` | Record a bed-check or study-hall result | DormParent |
| GET | `/reslife/night-checks` | List night checks, optional `duty_shift_id`, `student_id`, `check_kind`, `result` filters | SchoolAdmin, DormParent, Dean |
| GET | `/reslife/night-checks/{check_id}` | Get a night check | SchoolAdmin, DormParent, Dean |
| POST | `/reslife/medication-orders` | Create a medication order | Nurse |
| GET | `/reslife/medication-orders` | List orders, optional `student_id`, `status` filters | SchoolAdmin, Nurse, Dean |
| GET | `/reslife/medication-orders/{order_id}` | Get a medication order | SchoolAdmin, Nurse, Dean |
| POST | `/reslife/medication-orders/{order_id}/hold` | Place an order on HOLD with `reason` | Nurse |
| POST | `/reslife/medication-orders/{order_id}/resume` | Resume a HOLD order | Nurse |
| POST | `/reslife/medication-orders/{order_id}/discontinue` | Discontinue an order | Nurse |
| POST | `/reslife/medication-orders/{order_id}/administrations` | Record a dose outcome for a scheduled date | Nurse |
| GET | `/reslife/medication-administrations` | List administrations, optional `order_id`, `administered_by_staff_id`, `witness_staff_id` filters | SchoolAdmin, Nurse, Dean |
| GET | `/reslife/medication-administrations/{administration_id}` | Get an administration | SchoolAdmin, Nurse, Dean |
| GET | `/reslife/medication-orders/{order_id}/administrations` | List administrations of one order | SchoolAdmin, Nurse, Dean |
| POST | `/reslife/discipline-cases` | Report a discipline case | Dean, DormParent |
| GET | `/reslife/discipline-cases` | List cases, optional `student_id`, `status`, `reported_by_staff_id`, `hearing_officer_id` filters | SchoolAdmin, Dean, DormParent |
| GET | `/reslife/discipline-cases/{case_id}` | Get a discipline case | SchoolAdmin, Dean, DormParent, Student |
| POST | `/reslife/discipline-cases/{case_id}/begin-review` | Move a case to UNDER_REVIEW | Dean |
| POST | `/reslife/discipline-cases/{case_id}/schedule-hearing` | Schedule a hearing with `hearing_at` and `hearing_officer_id` | Dean |
| POST | `/reslife/discipline-cases/{case_id}/record-outcome` | Record a sanctioned or dismissed `outcome` | Dean |
| POST | `/reslife/discipline-cases/{case_id}/appeal` | Student appeals a SANCTIONED case | Student |
| POST | `/reslife/discipline-cases/{case_id}/appeal-decision` | Dean upholds (optional `adjusted_points`) or overturns per `decision` | Dean |
| POST | `/reslife/discipline-cases/{case_id}/close` | Close a SANCTIONED case | Dean |
| POST | `/reslife/break-periods` | Create a break period | SchoolAdmin |
| GET | `/reslife/break-periods` | List breaks, optional `status`, `kind` filters | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk, Student |
| GET | `/reslife/break-periods/{break_id}` | Get a break period | SchoolAdmin, DormParent, Nurse, Dean, FrontDesk, Student |
| POST | `/reslife/break-housing-requests` | International student requests break housing | Student |
| GET | `/reslife/break-housing-requests` | List requests, optional `student_id`, `break_period_id`, `status`, `room_id` filters | SchoolAdmin, Dean, DormParent, Student |
| GET | `/reslife/break-housing-requests/{request_id}` | Get a break-housing request | SchoolAdmin, Dean, DormParent, Student |
| POST | `/reslife/break-housing-requests/{request_id}/decide` | Approve or deny per `decision` | Dean, SchoolAdmin |
| POST | `/reslife/break-housing-requests/{request_id}/check-in` | Check into break housing | DormParent |
| POST | `/reslife/break-housing-requests/{request_id}/check-out` | Check out of break housing | DormParent |
| POST | `/reslife/storage-units` | Create a storage unit | SchoolAdmin |
| GET | `/reslife/storage-units` | List storage units, optional `status` filter | SchoolAdmin, DormParent, FrontDesk, Dean, Student |
| GET | `/reslife/storage-units/{unit_id}` | Get a storage unit with used capacity | SchoolAdmin, DormParent, FrontDesk, Dean, Student |
| POST | `/reslife/storage-reservations` | Reserve storage for a break | Student |
| GET | `/reslife/storage-reservations` | List reservations, optional `storage_unit_id`, `student_id`, `break_period_id`, `status` filters | SchoolAdmin, DormParent, FrontDesk, Student |
| GET | `/reslife/storage-reservations/{reservation_id}` | Get a storage reservation | SchoolAdmin, DormParent, FrontDesk, Student |
| POST | `/reslife/storage-reservations/{reservation_id}/check-in` | Check stored items in | DormParent, FrontDesk |
| POST | `/reslife/storage-reservations/{reservation_id}/retrieve` | Retrieve stored items | DormParent, FrontDesk |
| POST | `/reslife/storage-reservations/{reservation_id}/cancel` | Student cancels a RESERVED reservation | Student |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_MISSING_REQUIRED_FIELD` | 400 |
| `ERR_INVALID_FIELD_VALUE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERM_NOT_ACTIVE` | 409 |
| `ERR_STUDENT_NOT_ENROLLED` | 409 |
| `ERR_DORM_CLOSED` | 409 |
| `ERR_ORDER_NOT_ACTIVE` | 409 |
| `ERR_MEDICATION_ON_HOLD` | 422 |
| `ERR_WITNESS_REQUIRED` | 422 |
| `ERR_GUARDIAN_NOT_APPROVED` | 422 |
| `ERR_DOSE_ALREADY_LOGGED` | 409 |
| `ERR_CHECK_ALREADY_RECORDED` | 409 |
| `ERR_DUPLICATE_ACTIVE_ORDER` | 409 |
| `ERR_DUPLICATE_BREAK_REQUEST` | 409 |
| `ERR_SELF_ROOMMATE` | 422 |
| `ERR_ROOMMATE_NOT_IN_ROOM` | 422 |
| `ERR_ACTIVE_ASSIGNMENT_EXISTS` | 409 |
| `ERR_ACTIVE_TERM_EXISTS` | 409 |
| `ERR_DORM_GENDER_MISMATCH` | 422 |
| `ERR_GUARDIAN_REQUIRED` | 422 |
| `ERR_REPORTER_CANNOT_ADJUDICATE` | 422 |
| `ERR_HEARING_REQUIRED` | 422 |
| `ERR_APPEAL_LIMIT_REACHED` | 422 |
| `ERR_NOT_ELIGIBLE_BREAK_HOUSING` | 422 |
| `ERR_NOT_RESIDENT` | 422 |
| `ERR_NO_CONFIRMED_RESIDENCY` | 409 |
| `ERR_CHECKS_OUTSTANDING` | 409 |
| `ERR_SWAP_TARGET_INELIGIBLE` | 422 |
| `ERR_ROOM_OCCUPIED` | 409 |
| `ERR_LEAVE_WINDOW_OVERLAP` | 409 |
| `ERR_LEAVE_IN_PAST` | 422 |
| `ERR_HEARING_IN_PAST` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_SIGN_OUT_WINDOW` | 422 |
| `ERR_SHIFT_CONFLICT` | 409 |
| `ERR_BREAK_NOT_ACTIVE` | 409 |
| `ERR_LEAVE_ALLOWANCE_EXHAUSTED` | 422 |
| `ERR_ROOM_FULL` | 422 |
| `ERR_GUARDIAN_AT_CAPACITY` | 422 |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STUDENT_SUSPENDED` | 409 |
