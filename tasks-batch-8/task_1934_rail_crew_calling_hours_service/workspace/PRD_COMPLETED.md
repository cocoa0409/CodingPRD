# Rail Crew Calling Hours Service API — Product Requirements Document

## 1. Introduction

A Class I railroad's crew management center lives or dies on a single promise: every bulletined train and yard job departs with a qualified, rested, and legal-to-work crew. Today that promise is kept by callers working seniority-ordered extra boards day and night — telephoning the first-out conductor or engineer, tracking who has marked off, who is on federally mandated rest, who is nearing the monthly hours-of-service ceiling, and who went no-answer and must rotate to the bottom of the board. Every missed call, premature mark-up, or mis-rotated board slot cascades into delayed trains, statutory rest violations, and grievance claims under the collective bargaining agreement.

This document specifies the API for a system that digitizes that operation end to end: extra board rostering and standing-position management, first-out calling with response windows and penalty rotation, statutory rest enforcement with undisturbed-rest accounting, assignment and deadhead transport tracking, a weighted fatigue model that gates calling eligibility, vacation and personal-day leave bidding under a per-craft daily quota, crew shortage declaration and recrew coordination, and agreement-based timekeeping with a two-variant pay calculation. All resources are mounted under `/api`. Three acting roles share the platform — craft employees serving their own calls and claims, crew callers working the boards, and crew managers administering the center — and every temporal rule in the system is evaluated against a controllable logical clock so that compliance windows can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting principal and `X-User-Role` names their role. The declared role names are exactly `Employee`, `CrewCaller`, and `CrewManager`. A request missing either header, presenting a blank value, or naming an undeclared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); header values are trimmed of surrounding whitespace before validation, so a whitespace-only value counts as blank. A request whose role is syntactically valid but not listed among the endpoint's permitted roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403) — a craft employee issuing a call or a caller finalizing pay are canonical examples.

The `Employee` role is entity-backed: when `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee, and ownership checks on any resource that references an Employee compare the resource's employee reference field to `X-User-ID`. The self-service operations bound by this ownership check are exactly eleven: marking up, laying off, and returning from leave on one's own employee record; accepting or declining a call addressed to oneself; going on duty, tying up, or laying off one's own assignment; submitting or resubmitting one's own pay record; and cancelling one's own leave bid. When the header identity does not match the employee the operation targets, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `CrewCaller` or `CrewManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`. A `CrewCaller` is the crew management center caller who issues calls, records no-answers, rescinds offered calls, and completes tied-up assignments. A `CrewManager` is the center supervisor who administers employees, boards, jobs, leave awards and denials, pay disputes and finalization, suspensions and reinstatements, shortage recrew coordination, and the logical clock.

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
- Beyond the workflow errors of §3, a request to an undefined path, or using a method the path does not support, is answered in this same envelope with `ERR_NOT_FOUND` (HTTP 404); a request body that is not valid JSON, or that is not a JSON object, is answered with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Out-of-range values are clamped to the nearest bound rather than rejected, and a non-integer `limit` or `offset` falls back to its default. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope; `has_more` is true exactly when `offset` plus the number of records returned is below `total_count`. Every list endpoint sorts its results by `created_at` ascending, so the oldest record appears first and pagination walks forward in creation order; records created at the same logical instant are ordered by creation sequence. The one exception is the per-board slot listing of §3.1, which sorts by `standing_position`. Filter parameters match literally and are not validated against declared enum sets: an unrecognized filter value simply yields an empty page.

### 2.4. Common Resource Properties and Entity Versioning

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits. All resources except the rest period additionally carry `updated_at`, in the same timestamp format and refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation. Cascades count as mutations: when accepting a call increments a job's `filled_count`, the job's `version` advances by one and its `updated_at` refreshes, even though the request was addressed to the call. The RestPeriod is the sole exception to this pattern — it carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a rest period is stamped once when it opens and once when it closes, with no concurrent writers.

### 2.5. The Logical Clock and Time-Driven Sweeps

Every temporal rule in this system — response windows, rest minimums, report-time windows, leave windows, duty accumulation — is evaluated against a server-side logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `CrewManager`-only administrative capability advances the clock: the request supplies a `to_iso8601` instant, and the response echoes the new time as `now_iso8601` alongside `expired_call_ids`, the list of calls the advance expired. The advance is unconditional: any parseable ISO 8601 instant is adopted as given — even one earlier than the current reading — and a value without an explicit offset is read as UTC. `expired_call_ids` is ordered by `expires_at` ascending, ties broken by call creation order.

Advancing the clock fires the call-expiry sweep: every call still in `OFFERED` whose `expires_at` is at or before the new time transitions from `OFFERED` to `EXPIRED`. The same advance recomputes `undisturbed_minutes` on every open rest period, since undisturbed rest accrues as time passes.

### 2.6. Hours-of-Service Ceilings, Rest Minimums, and Fatigue Gating

Federal and agreement limits are enforced as hard gates throughout the calling and duty workflows; the constants below are fixed and uniform across the railroad.

- **Per-tour duty ceiling.** A single tour may not exceed 720 minutes — twelve hours — of elapsed duty measured from `on_duty_at`. Tying up is never rejected for reaching this ceiling: at or after the cap, tying up is the only permitted path out of `ON_DUTY`.
- **Monthly duty ceiling.** An employee's cumulative duty within one calendar month may not exceed 16,560 minutes — 276 hours. This ceiling gates call acceptance (see §3.4) with an inclusive boundary: a projection landing exactly on the cap passes.
- **Projected tour length.** Because a job's actual length is unknowable at call time, the acceptance gate uses a projected tour length derived from the `job_symbol`: 700 minutes when the symbol ends in `-L` (a long tour), 100 minutes when it ends in `-S` (a short tour), and 480 minutes for every other symbol.
- **Minimum undisturbed rest.** Before marking up from rest, an employee's open rest period must show at least 600 minutes — ten hours — of undisturbed time. The comparison is inclusive: a mark-up exactly 600 minutes after `rest_start` satisfies the requirement. Rest intervals are treated as half-open, including the start instant and excluding the end instant.
- **Early report window.** An employee may go on duty no earlier than 60 minutes before the job's `report_time`.
- **Call response window.** An offered call remains answerable for 120 minutes — two hours — after it is offered, after which it expires.
- **Fatigue block threshold.** An employee whose `fatigue_score` is 80.0 or higher cannot be issued a call at all; the exclusion happens inside callee selection, before any call exists.
- **Leave quota.** At most one awarded leave per craft per terminal may cover any given calendar day.

The `fatigue_score` itself is a weighted index combining three signals: one-half times the employee's month-to-date `cumulative_duty_minutes_month` expressed as a percentage of the 16,560-minute monthly cap; three-tenths times ten points per consecutive duty day; and one-fifth times fifteen points per disturbed rest in the trailing window. The consecutive-duty-day streak counts the run of consecutive UTC calendar days ending today on each of which the employee has at least one assignment whose `on_duty_at` falls on that day; the streak is zero whenever today itself has no such assignment. The disturbed-rest term counts the employee's rest periods with `rest_status` `DISTURBED` whose `rest_start` falls within the trailing 30 days, inclusive at both ends — from exactly thirty days before the current time up to the current time itself. The weighted sum is clamped to the range 0 through 100 and rounded to one decimal place, round-half-up. The score is recomputed when an employee accepts a call and moves onto an assignment, again when that assignment ties up, and — at recrew resolution (§3.7) — for both the relieved and the relieving employee.

### 2.7. Pay Precision and Rounding Conventions

All money is carried as integer cents; all pay rounding is round-half-up. Duty minutes, rest minutes, deadhead minutes, and board positions are integers with no rounding; elapsed-minute computations discard sub-minute remainders, flooring to whole minutes. The fatigue score is the one fractional quantity in the system: it is rounded to one decimal place, round-half-up.

Agreement pay is computed in two pinned variants that differ only in when rounding happens. The **provisional** variant, used when a claim is submitted or resubmitted, rounds each of the three pay components — basic, overtime, deadhead — half-up to integer cents separately, then sums them. The **final** variant, used at finalization, sums the three unrounded exact components and rounds half-up to integer cents once. The variants diverge whenever the components' fractional parts straddle a half-cent boundary: for a claim of 600 duty minutes with 100 deadhead minutes traveled by `TRAIN`, the provisional computation yields 74,867 cents while the final computation yields 74,866 cents. Finalization writes any such delta back into the record (see §3.6).

### 2.8. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard; no other endpoint accepts a version field.

Accepting a call requires the request to carry `expected_job_version`, the job `version` the employee last observed. If the job's current `version` has advanced — for example because another crew seat was just filled and `filled_count` moved — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412), since the employee's view of the remaining seats is stale.

Finalizing a pay record requires the request to carry `expected_pay_record_version`, the record `version` the manager last observed. If the record's current `version` has advanced — for example because the employee just resubmitted the claim, legitimately recomputing `gross_pay_cents` under the provisional variant — the finalization is rejected with `ERR_STALE_VERSION` (HTTP 412). In both cases the client should re-read the resource and retry with the fresh version.

### 2.9. Validation Pipeline and Nested Path Resolution

Every request passes through a fixed validation pipeline, and a failure at any stage short-circuits the stages after it. The order is: first, request well-formedness — the body, when present, must parse as a JSON object; required fields present, types correct, enum values within their declared sets, numeric fields within sign and range constraints such as `crew_required` being at least 1 and `claimed_minutes` never negative — rejected with `ERR_INVALID_REQUEST` (HTTP 400). Second, authentication via the two identity headers, rejected with `ERR_UNAUTHENTICATED`. Third, role authorization, rejected with `ERR_UNAUTHORIZED_ROLE`. Fourth, resource ownership for entity-backed employee self-service operations, rejected with `ERR_NOT_RESOURCE_OWNER`. Fifth, path resolution: every `id` in the URL must resolve, validated left to right — the job before the call, the employee before the slot, and so on — with the first unresolvable segment rejected with `ERR_NOT_FOUND` (HTTP 404). The relative order of the fourth and fifth stages depends on the address shape: for the three operations addressed directly to an employee id in the path — lay-off, mark-up, and return-from-leave — the ownership comparison runs against that path id and therefore precedes resolution, so a non-owner targeting a nonexistent employee is refused as `ERR_NOT_RESOURCE_OWNER`; for operations addressed to a call, assignment, pay record, or leave bid, the addressed resource is resolved first and ownership is then compared against its employee reference, so a nonexistent target surfaces as `ERR_NOT_FOUND` even for a non-owner. Sixth, state validity: the target entity must sit in a from-state listed for the requested transition — a call must be `OFFERED` to accept, decline, rescind, or record no-answer; an assignment must be `MARKED_UP` to go on duty or lay off; a job must be `BULLETINED` or `CALLING` to issue a call — rejected with `ERR_INVALID_STATE` (HTTP 409).

Only after all six generic stages pass do the business rules run, and they too have a fixed relative order: the monthly hours-of-service gate (`ERR_HOS_LIMIT_EXCEEDED`, HTTP 422) first, then rest satisfaction (`ERR_REST_NOT_SATISFIED`, HTTP 422), then temporal windows (`ERR_TEMPORAL_WINDOW`, HTTP 422), then leave conflicts (`ERR_LEAVE_CONFLICT`, HTTP 422), then job capacity (`ERR_JOB_ALREADY_FILLED`, HTTP 422), then referential consistency (`ERR_REFERENTIAL_MISMATCH`, HTTP 422), then calling-pool exhaustion (`ERR_CALL_POOL_EXHAUSTED`, HTTP 422), then uniqueness (`ERR_DUPLICATE`, HTTP 409), then stale-version rejection (`ERR_STALE_VERSION`, HTTP 412), and finally pay completeness (`ERR_PAY_INCOMPLETE`, HTTP 422). The practical consequence is visible on call acceptance: a stale `expected_job_version` surfaces only after the call's state, the hours-of-service projection, and the job's remaining capacity have all been verified, so a client can never mistake a stale read for a legality failure.

## 3. Business Logic & Workflows

### 3.1. Hiring, Crafts, and Extra Board Rostering

A `CrewManager` hires an employee by supplying the craft-unique payroll number `employee_number` (unique across the railroad — a duplicate is rejected with `ERR_DUPLICATE`, HTTP 409), the legal display name `full_name`, the operating `craft` drawn from `CONDUCTOR`, `ENGINEER`, `BRAKEMAN`, or `YARDMASTER`, the `seniority_date` on which the employee established seniority in craft (an earlier date means a more senior employee; supplied as an ISO 8601 date or datetime, read as UTC), and the `home_terminal` station code where the employee reports. A freshly hired employee starts with `availability_status` set to `AVAILABLE`, `cumulative_duty_minutes_month` at 0, and `fatigue_score` at 0. The roster listing can be filtered by `craft` and `availability_status`, and any single employee can be fetched by `id`.

Extra boards are the railroad's standing pools of available craft employees. A manager creates a board with a unique `board_code` such as CHI-CONDR-EB-01 (duplicates again rejected with `ERR_DUPLICATE`), the `craft` the board protects, the `terminal` station code it covers, and `guaranteed_slots`, the agreement-guaranteed board size, recorded as a non-negative integer; the floor is not enforced — no operation is rejected for cutting the pool's count of `ACTIVE` slots below it. Placing an employee on a board requires only the `employee_id` in the request payload; the new slot enters in `ACTIVE` status, appended at the tail of the board at `standing_position` one past the current last position, where position 1 is the first-out position. Placement enforces its integrity rules in pipeline order: the `employee_id` must reference an existing employee, and that employee's craft must equal the board's craft — both otherwise `ERR_REFERENTIAL_MISMATCH` (HTTP 422), existence checked first — and an employee may hold at most one `ACTIVE`-or-`FROZEN` slot per board, otherwise `ERR_DUPLICATE`. A board's slots are listed ordered by `standing_position` — `VACATED` slots, whose position was released, sort last — and the per-board listing also accepts a `slot_status` filter; a global slot listing supports filtering by `board_id`, `employee_id`, and `slot_status`, whose values are `ACTIVE`, `FROZEN`, and `VACATED`.

Standing positions are maintained by a single board-rotation discipline that several workflows share. A penalty rotation — triggered by declining a call, going no-answer, or letting a call expire — moves the offending slot to the last position on its board, and every `ACTIVE` slot that stood behind it shifts up by exactly one position. A freeze, triggered when an employee lays off, flips the slot from `ACTIVE` to `FROZEN` while remembering its position, and the remaining `ACTIVE` slots renumber from 1 upward preserving their relative order. A restore on mark-up flips the slot back to `ACTIVE` at its remembered position, and slots at or below that position shift down one to make room; a remembered position beyond the current tail is clamped, so the slot restores at the tail. A vacate — on leave award or suspension — flips the slot to `VACATED` and releases its position entirely, with the surviving `ACTIVE` slots again renumbered from 1 upward. Returns from leave, reinstatements, and brand-new placements all append at the tail. Returns and reinstatements target the earliest-created board matching the employee's craft and home terminal; when no board matches, the employee comes back with no slot at all.

### 3.2. Mark-Up, Lay-Off, Suspension, and the Statutory Rest Cycle

An employee's `availability_status` cycles through `AVAILABLE`, `MARKED_OFF`, `ON_LEAVE`, `ON_ASSIGNMENT`, `ON_REST`, and `SUSPENDED`, with no terminal state; hired employees begin at `AVAILABLE`.

When an employee books off — `AVAILABLE` to `MARKED_OFF` — every one of their `ACTIVE` board slots flips to `FROZEN` and the board-rotation discipline renumbers the surviving `ACTIVE` slots on each affected board. The freeze deliberately does not vacate the slot, so a later mark-up restores the employee's former standing. Marking back up from `MARKED_OFF` is permitted only when no open rest period exists for the employee whose `undisturbed_minutes` has yet to reach the 600-minute statutory minimum; if such a rest period exists the request is rejected with `ERR_REST_NOT_SATISFIED` (HTTP 422). On success the mark-up closes any open rest period — `rest_end` is stamped with the current time and the period's `rest_status` settles to `SATISFIED` when its `undisturbed_minutes` reached at least 600, otherwise `DISTURBED` — and every `FROZEN` slot flips back to `ACTIVE` at its prior `standing_position`.

Rest itself is entered from duty: when an assignment ties up or an on-duty employee is relieved by recrew, the employee transitions from `ON_ASSIGNMENT` to `ON_REST` and a new rest period opens with `rest_start` stamped at that moment, `rest_status` set to `OPEN`, and `rest_end` unset for as long as the period remains open. By construction an employee has at most one `OPEN` rest period at a time. The period's `undisturbed_minutes` measures the minutes between `rest_start` and the last disturbance — or, while the rest remains undisturbed, between `rest_start` and the close of the period — and it is recomputed as the logical clock advances. Marking up from `ON_REST` requires the open period's `undisturbed_minutes` to be at least 600; the boundary is inclusive, so a mark-up exactly ten hours after `rest_start` succeeds, while anything short is rejected with `ERR_REST_NOT_SATISFIED`. A successful mark-up from `ON_REST` closes the period as `SATISFIED`. Rest compliance is deliberately enforced at mark-up rather than at call time: offering a call to an employee whose most recent completed rest closed as `DISTURBED` within the trailing 24 hours is permitted, and acceptance likewise applies no rest-based gate of any kind. Rest period history can be listed with filters on `employee_id` and `rest_status` — `OPEN`, `SATISFIED`, or `DISTURBED` — or fetched individually.

Suspension is a manager's action that moves an `AVAILABLE` employee to `SUSPENDED`: every `ACTIVE` board slot is `VACATED`, and every call currently `OFFERED` to that employee transitions from `OFFERED` to `RESCINDED` as a system cascade. Reinstatement moves a `SUSPENDED` employee back to `AVAILABLE` and appends them to the tail of the extra board matching their craft and home terminal, at the last `standing_position`.

### 3.3. Job Bulletins and the Seniority Calling Process

Work enters the system when a `CrewManager` bulletins a job: the train or yard assignment `job_symbol` (for example M-CHIGAL1-15A), the required `craft`, the `origin_terminal` on-duty station code, the scheduled `report_time` in UTC, and `crew_required`, the number of crew of that craft the job needs, which must be at least 1. A new job starts in `BULLETINED` status with `filled_count` at 0; the job's lifecycle runs `BULLETINED` to `CALLING` to `FILLED`. Job listings filter by `craft` and `job_status`.

Issuing the next call for a job is the `CrewCaller`'s core action. The job must be `BULLETINED` or `CALLING`; issuing moves it to `CALLING`. Callee selection filters the extra boards to find slots whose board's craft equals the job's `craft` and whose board's terminal equals the job's `origin_terminal`, where the slot is `ACTIVE`, the occupying employee is `AVAILABLE`, and the employee's `fatigue_score` is below the 80.0 block threshold — fatigue gating lives entirely here at selection time, never at acceptance. Among the eligible set — pooled across every matching board when several boards match — the callee is chosen by `standing_position` ascending, first-out first, with ties across boards broken by slot creation order, earliest first. The created call links the job and the selected employee through `job_id` and `employee_id`, enters `OFFERED` status with `offered_at` stamped by the server, and computes `expires_at` as exactly 120 minutes after `offered_at`. When no board exists matching the job's craft and terminal the request fails as a referential mismatch (`ERR_REFERENTIAL_MISMATCH`), and when matching boards exist but the eligible pool is empty — every slot frozen or vacated, every occupant unavailable or fatigue-blocked — no call is created, the issue is rejected with `ERR_CALL_POOL_EXHAUSTED` (HTTP 422), and a crew shortage row is opened automatically with `shortage_status` `OPEN` and its `craft` taken from the job. Recall from §2.9 that the board-existence referential check is evaluated ahead of pool exhaustion in the business-rule order.

A call's terminal states are `DECLINED`, `NO_ANSWER`, `EXPIRED`, and `RESCINDED`; `ACCEPTED` is the successful non-terminal outcome and the accepted call is retained as immutable history. Every call's `responded_at` remains unset for as long as the call is still `OFFERED`, and each outcome stamps it: for an acceptance, a decline, or a no-answer, the moment of the response; for an expiry, the value of `expires_at` itself. Declining — an employee action — rotates the declining employee's slot to the last position on its board under the penalty rule, and if the job's remaining unfilled seats then have no further eligible callee, a crew shortage is opened in `OPEN` status: decline, slot rotation, shortage check, in that order. A no-answer, recorded by the caller, applies the same penalty rotation to the unresponsive employee's slot. Expiry fires from the clock sweep and penalizes identically. In each case the rotation targets the callee's `ACTIVE` slot on a board matching the job's craft and origin terminal — the earliest-created such slot when the employee holds several — and is skipped silently when no such slot exists. Rescinding, by contrast, is railroad-initiated — performed by the caller or cascaded from a suspension — and stamps `responded_at` with no board penalty at all. Calls can be listed per job or globally, filtered by `call_status` and, on the global listing, additionally by `job_id` and `employee_id`.

### 3.4. Assignment Lifecycle: From Accepted Call to Completion

Accepting an offered call is the pivotal employee action, guarded by the strictest check sequence in the system. The call must still be `OFFERED` — accepting a `DECLINED` or `EXPIRED` call is `ERR_INVALID_STATE` — and the logical clock must be strictly before `expires_at`, with an attempt at or after `expires_at` likewise rejected as `ERR_INVALID_STATE` (HTTP 409). The employee must be `AVAILABLE`, otherwise `ERR_INVALID_STATE` (HTTP 409). Then the forward-looking hours-of-service gate runs: the employee's month-to-date `cumulative_duty_minutes_month` plus the job's projected tour minutes (700 for a `-L` symbol, 100 for `-S`, otherwise 480) must not exceed the 16,560-minute monthly cap, with equality passing; otherwise the acceptance is rejected with `ERR_HOS_LIMIT_EXCEEDED` (HTTP 422). Two employees with identical duty histories can therefore see different acceptance outcomes because their target jobs carry different projected tour lengths. Next, the job must still have an open seat — `filled_count` below `crew_required` — or the request fails with `ERR_JOB_ALREADY_FILLED` (HTTP 422). Finally the optimistic-concurrency guard of §2.8 verifies `expected_job_version`, rejecting a stale read with `ERR_STALE_VERSION` (HTTP 412).

A successful acceptance creates an assignment in `MARKED_UP` status carrying the `job_id`, the `employee_id`, and the `call_id` of the accepted call that produced it; the request may optionally attach paid deadhead transport via `deadhead_minutes` and `deadhead_mode` (`NONE`, `TAXI`, `COMPANY_VEHICLE`, or `TRAIN`), which default to 0 and `NONE`; when supplied, `deadhead_minutes` must be a non-negative integer and `deadhead_mode` one of the four declared modes, failing well-formedness (`ERR_INVALID_REQUEST`, HTTP 400) otherwise. The job's `filled_count` increments by one — a mutation that also advances the job's `version` and refreshes `updated_at` — and when `filled_count` reaches `crew_required` the job transitions from `CALLING` to `FILLED`. The employee moves from `AVAILABLE` to `ON_ASSIGNMENT`, the call's `responded_at` is stamped, and the employee's duty accumulation and fatigue score are recomputed.

The assignment lifecycle continues `MARKED_UP` to `ON_DUTY` to `TIE_UP_PENDING` to `COMPLETED`, with `LAID_OFF` and `RECREWED` as the two early terminal exits. Going on duty is allowed no earlier than 60 minutes before the job's `report_time`; an earlier attempt fails with `ERR_TEMPORAL_WINDOW` (HTTP 422). Going on duty stamps `on_duty_at` and starts the running duty accumulator. Duty accumulation is a chronological ledger: it replays the employee's assignments in `ON_DUTY`, `TIE_UP_PENDING`, `COMPLETED`, or `RECREWED` status whose `on_duty_at` falls in the current calendar month — `LAID_OFF` rows contribute nothing — ordered by `on_duty_at` ascending with `created_at` ascending as the tie-break, summing each row's elapsed minutes (to `off_duty_at`, or to the current time for a tour still `ON_DUTY`). The resulting total is the persisted `cumulative_duty_minutes_month`.

Tying up — permitted only from `ON_DUTY`, otherwise `ERR_INVALID_STATE` — ends the tour: `off_duty_at` is stamped, the chronological ledger finalizes the tour's elapsed minutes into `cumulative_duty_minutes_month`, the employee moves from `ON_ASSIGNMENT` to `ON_REST` with a fresh rest period opening, and a pay record is auto-created in `DRAFT` for the employee and assignment with `claimed_minutes` preset to the elapsed tour minutes, `claimed_deadhead_minutes` preset from the assignment's `deadhead_minutes`, and `gross_pay_cents` initialized to 0. Tie-up itself is never rejected on hours grounds — reaching or passing the twelve-hour tour ceiling makes tying up the only permitted path. Completion is the caller's closing act, permitted only from `TIE_UP_PENDING` and only while the assignment's auto-created pay record sits in `SUBMITTED` or `FINALIZED`; completing against a still-`DRAFT` — or currently `DISPUTED` — pay record fails with `ERR_PAY_INCOMPLETE` (HTTP 422), and a successful completion decrements the job's `filled_count` by one without otherwise altering the job's status.

An employee may also lay off a marked-up assignment, but only strictly before the job's `report_time`; at or after report time the attempt fails with `ERR_TEMPORAL_WINDOW`. Laying off decrements `filled_count` by one — and if the job had been `FILLED`, falling below `crew_required` transitions it back from `FILLED` to `CALLING` — and returns the employee from `ON_ASSIGNMENT` to `AVAILABLE` through the mark-up path, with no rest period opening because duty never began. The producing call remains `ACCEPTED` as immutable history, and a fresh call may be issued for the reopened seat. Assignment listings filter by `job_id`, `employee_id`, `call_id`, and `assignment_status` (`MARKED_UP`, `ON_DUTY`, `TIE_UP_PENDING`, `COMPLETED`, `LAID_OFF`, `RECREWED`).

### 3.5. Leave Bidding and Award

Vacation and personal-day bidding begins with the employee submitting a bid carrying their `employee_id`, a `leave_type` of `VACATION` or `PERSONAL_DAY`, and the `start_date` and `end_date` bounding the leave. Both dates are supplied as ISO 8601 instants and interpreted by their UTC calendar day — any time-of-day is accepted and only the date portion participates in the window, overlap, and quota comparisons — and the interval is closed: the end day is itself part of the leave. Submission validates the temporal window: `start_date` must fall on or before `end_date` and its day must not be earlier than the current day, else `ERR_TEMPORAL_WINDOW`. A new bid enters `SUBMITTED` status; the listing filters by `employee_id` and `bid_status`.

Awarding is a manager decision with two conflict gates beyond the bid still being `SUBMITTED`. First, no other `AWARDED` bid for the same employee may overlap the requested window, with closed-interval semantics — a shared boundary day is a conflict. Second, the per-craft-per-day quota: for every day of the requested window, the count of other `AWARDED` bids of the bidder's craft at the bidder's `home_terminal` covering that day must be strictly below the quota of 1 — that is, zero — for every single day of the window. Either violation is rejected with `ERR_LEAVE_CONFLICT` (HTTP 422). A successful award stamps `decided_at` and cascades three levels deep: the employee — who must be `AVAILABLE`, otherwise `ERR_INVALID_STATE` (HTTP 409) — transitions from `AVAILABLE` to `ON_LEAVE`, every `ACTIVE` board slot flips to `VACATED`, and the board-rotation discipline renumbers the survivors. Denying a bid simply stamps `decided_at` and moves it to `DENIED`, a terminal state.

Cancellation belongs to the employee and behaves differently by state. Cancelling a still-`SUBMITTED` bid moves it to `CANCELLED` with no side effects. Cancelling an `AWARDED` bid is permitted only while the logical clock remains strictly before the leave's `start_date` — once the leave has begun, cancellation is rejected with `ERR_INVALID_STATE` (HTTP 409) — and it reverses the award: the employee returns from `ON_LEAVE` to `AVAILABLE` through the same machinery as a return from leave, appended to the tail of their matching board. Returning from leave outside of cancellation is likewise an employee action from `ON_LEAVE`, restoring `AVAILABLE` and appending the employee at the last `standing_position` of the board matching their craft and home terminal, first-in-first-out at the tail.

### 3.6. Timekeeping and Agreement Pay

Every tour's compensation flows through a pay record linking an `employee_id` to an `assignment_id`, with the duty `claimed_minutes` and optionally `claimed_deadhead_minutes` (default 0). Most records arrive automatically in `DRAFT` at tie-up, but an employee may also create one manually — a supplemental claim, for instance — supplying `employee_id`, `assignment_id`, and `claimed_minutes`, with `claimed_deadhead_minutes` optional (default 0); the referenced assignment must exist and belong to that employee, and the employee must exist, otherwise `ERR_REFERENTIAL_MISMATCH`. Either way a `DRAFT` record carries `gross_pay_cents` 0 until first submission. The record lifecycle runs `DRAFT` to `SUBMITTED` to `FINALIZED`, with a dispute loop from `SUBMITTED` to `DISPUTED` and back to `SUBMITTED`; `FINALIZED` is terminal.

Submitting a draft requires `claimed_minutes` strictly greater than zero — otherwise `ERR_PAY_INCOMPLETE` (HTTP 422) — and triggers the provisional pay computation, writing `gross_pay_cents`. Under the rail agreement model, pay is expressed as fractions of a basic day. The basic component is the basic-day rate of 30,010 cents multiplied by the smaller of `claimed_minutes` and 480, divided by 480. The overtime component is 1.5 times the basic-day rate, multiplied by the excess of `claimed_minutes` over 480 (zero when the claim is 480 minutes or less), divided by 480. The deadhead component is the deadhead hourly rate of 18,755 cents multiplied by `claimed_deadhead_minutes` divided by 60, and then multiplied further by 1.075 when the assignment's `deadhead_mode` is `TRAIN` (by 1.0 otherwise). The provisional variant rounds each component half-up to integer cents and then sums the three rounded values.

Consider a claim of 600 duty minutes with 100 deadhead minutes traveled by `TRAIN`. The basic component is exactly 30,010 cents (600 exceeds 480, so the full basic day is paid); the overtime component is 1.5 times 30,010 times 120 over 480, which is 11,253.75 cents exactly and rounds to 11,254; the deadhead component is 18,755 times 100 over 60 times 1.075, which is 33,602.7083… cents and rounds to 33,603. Provisional gross pay is therefore the sum 30,010 + 11,254 + 33,603 = 74,867 cents.

A manager who questions a submitted claim disputes it, moving the record to `DISPUTED` with no other effect. The employee then resubmits with amended `claimed_minutes` and optionally amended `claimed_deadhead_minutes`; resubmission returns the record to `SUBMITTED` and recomputes `gross_pay_cents` under the same provisional variant against the amended figures. An omitted `claimed_deadhead_minutes` retains its prior value, and the strictly-positive `claimed_minutes` gate of submission is not re-applied — a zero-minute amendment is accepted and recomputed like any other.

Finalization is the manager's closing act on a `SUBMITTED` record, guarded by the `expected_pay_record_version` optimistic-concurrency check of §2.8. It recomputes `gross_pay_cents` under the final variant — summing the three exact, unrounded components and rounding half-up to integer cents once — and writes the delta between provisional and final back into `gross_pay_cents`. For the worked example above, the exact sum is 74,866.4583… cents, rounding once to 74,866, one cent below the provisional figure; the record's `gross_pay_cents` is updated accordingly. Finalization increments the record's `version` by one. Recall from §3.4 that an assignment cannot be completed while its pay record is still `DRAFT`. Pay record listings filter by `employee_id`, `assignment_id`, and `record_status`.

### 3.7. Crew Shortages and Recrew Coordination

A crew shortage materializes in three ways: automatically when call issuing finds an empty eligible pool, automatically when a decline leaves a job's remaining seats without a further eligible callee, or manually when a manager declares one on a job — for instance when an on-duty crew member must be relieved mid-tour. No deduplication is performed: every triggering event opens a fresh `OPEN` shortage row, even if an earlier shortage for the same job is still open. A declared shortage opens in `OPEN` status with its `craft` taken from the job and `opened_at` stamped. The shortage lifecycle runs from `OPEN` either to `RECREWING` and then `RESOLVED`, or to the terminal `ESCALATED` from either `OPEN` or `RECREWING`.

Beginning recrew moves an `OPEN` shortage to `RECREWING` with no side effects. Escalation moves an `OPEN` or `RECREWING` shortage to `ESCALATED`, likewise with no side effects.

Resolution is the heavy transition, permitted only from `RECREWING` — resolving an `OPEN` shortage is `ERR_INVALID_STATE` (HTTP 409). The manager supplies the `assignment_id` of the on-duty assignment being relieved, the `relieving_employee_id` of the replacement, and optionally `deadhead_minutes` for the replacement's paid transport (a non-negative integer, default 0). An `assignment_id` or `relieving_employee_id` that does not resolve is rejected with `ERR_NOT_FOUND` (HTTP 404), and an assignment that belongs to a different job than the shortage is `ERR_REFERENTIAL_MISMATCH` (HTTP 422). The target assignment must be `ON_DUTY` and the relieving employee `AVAILABLE`, each otherwise `ERR_INVALID_STATE`, and the relieving employee must pass the hours-of-service projection and fatigue gates, which reject with `ERR_HOS_LIMIT_EXCEEDED` (HTTP 422). A successful resolution stamps `off_duty_at` on the target assignment at the handoff instant and moves it from `ON_DUTY` to `RECREWED`; the relieved employee transitions from `ON_ASSIGNMENT` to `ON_REST` and a rest period opens for them. Simultaneously a replacement assignment is created directly in `ON_DUTY` status for the relieving employee — `on_duty_at` stamped at the handoff instant, no originating call, `deadhead_mode` `NONE`, carrying the request's `deadhead_minutes` — and that employee's availability flips from `AVAILABLE` to `ON_ASSIGNMENT`; the job's `filled_count` is unchanged, and the duty ledger and fatigue score are recomputed for both employees. Finally the shortage's `resolved_at` is stamped and it enters the terminal `RESOLVED` state. Shortage listings filter by `job_id` and `shortage_status` (`OPEN`, `RECREWING`, `RESOLVED`, `ESCALATED`).

## 4. Endpoint Definitions

All endpoints follow the status-code convention that creating a new resource returns 201 — hiring an employee, creating a board, placing a slot, bulletining a job, issuing a call, accepting a call (which creates the assignment), submitting a leave bid, creating a pay record, and declaring a shortage — while modifications, state transitions, reads, and the clock advance return 200. Request payloads, response shapes, and side effects are defined by the workflows in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock; fires the call-expiry sweep | CrewManager |
| POST | /api/employees | Hire/register an employee | CrewManager |
| GET | /api/employees | List employees with optional filters | CrewManager, CrewCaller |
| GET | /api/employees/{id} | Fetch one employee | CrewManager, CrewCaller, Employee |
| POST | /api/employees/{id}/lay-off | Employee books off; freezes board slots | Employee |
| POST | /api/employees/{id}/mark-up | Employee marks up; closes any open rest period | Employee |
| POST | /api/employees/{id}/return-from-leave | Employee returns from awarded leave | Employee |
| POST | /api/employees/{id}/suspend | Suspend an employee; rescinds offered calls, vacates slots | CrewManager |
| POST | /api/employees/{id}/reinstate | Reinstate a suspended employee | CrewManager |
| POST | /api/extra-boards | Create an extra board | CrewManager |
| GET | /api/extra-boards/{id} | Fetch one board | CrewManager, CrewCaller |
| GET | /api/extra-boards/{id}/slots | List a board's slots by standing position | CrewManager, CrewCaller |
| POST | /api/extra-boards/{id}/slots | Place an employee on the board at the tail | CrewManager |
| GET | /api/extra-board-slots | Filtered slot listing | CrewManager, CrewCaller |
| GET | /api/extra-board-slots/{id} | Fetch one slot | CrewManager, CrewCaller |
| POST | /api/jobs | Bulletin a job | CrewManager |
| GET | /api/jobs | List jobs | CrewManager, CrewCaller, Employee |
| GET | /api/jobs/{id} | Fetch one job | CrewManager, CrewCaller, Employee |
| POST | /api/jobs/{id}/calls | Issue the next call for a job | CrewCaller |
| GET | /api/jobs/{id}/calls | List calls issued for a job | CrewManager, CrewCaller |
| GET | /api/calls | Filtered call listing | CrewManager, CrewCaller, Employee |
| GET | /api/calls/{id} | Fetch one call | CrewManager, CrewCaller, Employee |
| POST | /api/calls/{id}/accept | Employee accepts an offered call; creates the assignment | Employee |
| POST | /api/calls/{id}/decline | Employee declines; penalty rotation; may open a shortage | Employee |
| POST | /api/calls/{id}/no-answer | Caller records a no-answer; penalty rotation | CrewCaller |
| POST | /api/calls/{id}/rescind | Caller rescinds an offered call; no penalty | CrewCaller |
| GET | /api/assignments | Filtered assignment listing | CrewManager, CrewCaller, Employee |
| GET | /api/assignments/{id} | Fetch one assignment | CrewManager, CrewCaller, Employee |
| POST | /api/assignments/{id}/on-duty | Employee goes on duty | Employee |
| POST | /api/assignments/{id}/tie-up | Employee ends duty; opens rest; auto-creates draft pay record | Employee |
| POST | /api/assignments/{id}/lay-off | Employee lays off before report time; reopens the seat | Employee |
| POST | /api/assignments/{id}/complete | Caller completes a tied-up assignment once pay is submitted | CrewCaller |
| GET | /api/rest-periods | Filtered rest-period listing | CrewManager, CrewCaller, Employee |
| GET | /api/rest-periods/{id} | Fetch one rest period | CrewManager, CrewCaller, Employee |
| POST | /api/leave-bids | Employee submits a vacation/personal-day bid | Employee |
| GET | /api/leave-bids | Filtered leave-bid listing | CrewManager, CrewCaller, Employee |
| GET | /api/leave-bids/{id} | Fetch one leave bid | CrewManager, CrewCaller, Employee |
| POST | /api/leave-bids/{id}/award | Manager awards a bid (quota and overlap gated) | CrewManager |
| POST | /api/leave-bids/{id}/deny | Manager denies a bid | CrewManager |
| POST | /api/leave-bids/{id}/cancel | Employee cancels a submitted or not-yet-started awarded bid | Employee |
| POST | /api/pay-records | Manually create a draft pay record for an assignment | Employee |
| GET | /api/pay-records | Filtered pay-record listing | CrewManager, CrewCaller, Employee |
| GET | /api/pay-records/{id} | Fetch one pay record | CrewManager, CrewCaller, Employee |
| POST | /api/pay-records/{id}/submit | Employee submits a draft claim; provisional pay computed | Employee |
| POST | /api/pay-records/{id}/dispute | Manager disputes a submitted claim | CrewManager |
| POST | /api/pay-records/{id}/resubmit | Employee amends and resubmits a disputed claim | Employee |
| POST | /api/pay-records/{id}/finalize | Manager finalizes a submitted claim; final pay computed (OCC-guarded) | CrewManager |
| POST | /api/jobs/{id}/crew-shortages | Manager declares a crew shortage on a job | CrewManager |
| POST | /api/crew-shortages/{id}/begin-recrew | Manager begins recrew coordination | CrewManager |
| POST | /api/crew-shortages/{id}/resolve | Manager resolves a shortage by recrewing | CrewManager |
| POST | /api/crew-shortages/{id}/escalate | Manager escalates an open or recrewing shortage | CrewManager |
| GET | /api/crew-shortages | Filtered shortage listing | CrewManager, CrewCaller |
| GET | /api/crew-shortages/{id} | Fetch one crew shortage | CrewManager, CrewCaller |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the workflow narratives of §2 and §3; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_HOS_LIMIT_EXCEEDED | 422 |
| ERR_REST_NOT_SATISFIED | 422 |
| ERR_TEMPORAL_WINDOW | 422 |
| ERR_LEAVE_CONFLICT | 422 |
| ERR_JOB_ALREADY_FILLED | 422 |
| ERR_REFERENTIAL_MISMATCH | 422 |
| ERR_DUPLICATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PAY_INCOMPLETE | 422 |
| ERR_CALL_POOL_EXHAUSTED | 422 |
| ERR_INVALID_REQUEST | 400 |
