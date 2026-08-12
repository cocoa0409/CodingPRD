# Paraprofessional Staffing API — Product Requirements Document

## 1. Introduction

School districts live or die by how well they staff their special education mandates. Every student with an Individualized Education Program carries a written entitlement — a number of support minutes per week, sometimes delivered one-on-one, sometimes shared, sometimes transitional as the student moves toward independence — and the district must place qualified paraprofessionals against those entitlements, in specific buildings, on specific days, inside a fixed annual budget. Complicating everything are the daily realities of the school year: a para calls in sick and a gap opens that same morning; a student's IEP is amended mid-year and every assignment built around the old service level has to be unwound; a hard-to-staff building needs a funding premium to attract coverage; and at year end the district must reconcile what it *projected* to spend against what approved timesheets actually prove was worked.

This document specifies the Paraprofessional Staffing API, a REST service mounted under `/sped-staffing`, which manages that entire lifecycle. A district staffing administrator stands up an annual **staffing plan** with a budget and benefit rules, registers buildings and the paraprofessional roster, and versions the funding formulas that translate IEP minutes into per-building allocations. Special education coordinators register students, file and effectuate service change orders, propose and activate assignments, run daily coverage plans, and dispatch a constraint-driven backfill selector when absences land. Paraprofessionals report their own absences, log timesheets, answer backfill offers, and acknowledge or dispute their evaluations, while teachers author those evaluations and building administrators approve timesheets and countersign — a deliberate segregation of duties woven through the model. Because benefit eligibility, projected cost, and final settlement all depend on *when* work happened, the service also exposes an administrator-only logical clock so that every date-sensitive rule in this document is evaluated against a controllable, deterministic "now".

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role the user is acting in. A request missing either header, or carrying a role value that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the caller is authenticated, the role must additionally appear in the endpoint's authorized role list; a caller whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Six roles are declared. `DistrictStaffingAdmin` is the district staffing administrator and owns plans, buildings, the paraprofessional roster and its training records, allocation formulas, allocation computation, service-change-order approval, and the logical clock. `SpecialEdCoordinator` owns students, change-order filing and effectuation, the assignment lifecycle, coverage plans, absence escalation, and backfill offers. `BuildingAdministrator` approves or rejects timesheets and countersigns or resolves evaluations. `Teacher` reports absences and authors and submits evaluations. `Paraprofessional` is the support staff member who reports own absences, logs and submits own timesheets, answers own backfill offers, and acknowledges or disputes own evaluations. `Any` is a read-only aggregate role granted to every authenticated caller and covers all list and detail retrieval endpoints.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Paraprofessional`, `X-User-ID` is the `id` of the acting Paraprofessional; ownership checks on any resource that references a Paraprofessional compare the resource's foreign-key field to `X-User-ID` — for example the `para_id` of a timesheet entry or evaluation, the `substitute_para_id` of a backfill offer, or the `para_id` of the assignment behind an absence report. When `X-User-Role` is `DistrictStaffingAdmin`, `SpecialEdCoordinator`, `BuildingAdministrator`, `Teacher`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `created_by_user_id` or `countersigned_by_user_id` on an evaluation, where the authoring and countersigning actors must be distinguishable) but does not compare it to any entity's `id`. Where a rule needs the caller's role rather than identity, the server records it explicitly — an absence report persists the creator's role in `reported_by_role`.

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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses are always sorted by `created_at` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every date-sensitive rule in this document — qualification expiry, benefit-week boundaries, coverage posture — is evaluated against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it continues to read that default until an administrator explicitly moves it. A `DistrictStaffingAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` timestamp and sets the logical "now" to that instant. Qualification expiry and coverage-posture recomputation are lazy: they observe the new clock value on subsequent reads and writes rather than being swept eagerly at the moment the clock moves.

### 2.5. Common Resource Properties

Every resource in the system — staffing plans, buildings, students, paraprofessionals, service change orders, assignments, coverage plans, absence reports, backfill assignments, timesheet entries, evaluations, allocation formulas, and funding allocations — shares four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three fractional digits; `updated_at` refreshes on every mutation. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource. Several lifecycle operations in this document — plan activation, coverage-plan publication, assignment creation — explicitly note that they increment the parent's `version`; those increments are the optimistic-concurrency currency described in §2.8.

### 2.6. Money, Minutes, and Rounding Discipline

All monetary amounts are integer cents; all wages and cost rates are cents per hour. Times of day are expressed as a minute-of-day integer from 0 through 1439, and durations are integer minutes. Whenever a computation produces a fractional cent or fractional minute result, the system rounds half-up to the nearest integer.

Two different rounding *regimes* exist, and they are deliberately not interchangeable. Assignment costing rounds each service day first and then multiplies by the number of service days in the week — the per-day figure is rounded half-up before any weekly aggregation. Funding-allocation math, by contrast, sums exact values and rounds half-up exactly once at the very end of each variant's computation. Identical underlying minutes therefore legitimately yield different cent totals under the two rules, and an implementation must not "harmonize" them.

### 2.7. Validation Priority: The Order in Which Requests Are Rejected

When several checks could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. First, the authentication check: both context headers must be present and the role must be declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, authorization: the role must be permitted on the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`. Third, existence: path identifiers are resolved left to right, then body foreign-key references, with each miss producing its dedicated not-found error. Fourth come the state checks, in three sub-steps: the plan must be in a state allowing the operation (configuration writes need `DRAFT` or `ACTIVE`; assignment and coverage writes need `ACTIVE`; close needs `RECONCILING`) else `ERR_PLAN_NOT_ACTIVE`, `ERR_PLAN_NOT_DRAFT`, or `ERR_PLAN_NOT_RECONCILING`; then the target entity must sit in exactly the from-state its transition declares (for absence reporting specifically, a coverage plan that is missing or still `DRAFT` yields `ERR_COVERAGE_PLAN_NOT_PUBLISHED` while a `LOCKED` or `RECONCILED` plan yields `ERR_COVERAGE_PLAN_FROZEN`); and then the optimistic-concurrency version match, else `ERR_STALE_VERSION`. Fifth, business safety: qualification currency is enforced as `ERR_QUALIFICATION_NOT_CURRENT`, and segregation of duties on countersigning as `ERR_EVALUATION_SELF_COUNTERSIGN`. Sixth, business constraints: schedule overlap (`ERR_SCHEDULE_OVERLAP`), timesheet double-logging (`ERR_TIMESHEET_OVERLAP`), uniqueness rules (`ERR_DUPLICATE_COVERAGE_PLAN`, `ERR_OPEN_CHANGE_ORDER_EXISTS`, `ERR_ALLOCATIONS_ALREADY_COMPUTED`, `ERR_INVALID_REQUEST`), and the weekly-minutes capacity check (`ERR_WEEKLY_MINUTES_CAP_EXCEEDED`). Seventh, date coherence across all date-bearing payloads, else `ERR_INVALID_DATE_RANGE`. Eighth, aggregate gating: coverage lock and reopen require an `OPEN` posture (`ERR_COVERAGE_GAPS_OPEN`), plan close requires no unresolved timesheets and no unreconciled coverage plans (`ERR_UNRESOLVED_TIMESHEETS`, `ERR_UNRECONCILED_COVERAGE_PLANS`), and plan activation requires at least one building (`ERR_PLAN_HAS_NO_BUILDINGS`). Ninth and last, the fiscal check: budget sufficiency is evaluated only after every other rule has passed, else `ERR_INSUFFICIENT_BUDGET`. Fiscal checks always run last so that a request failing both a structural rule and the budget surfaces the structural error.

### 2.8. Optimistic Concurrency Control on Plan and Coverage Writes

Two write operations carry an explicit optimistic-concurrency contract; no other endpoint takes a version field. Creating an assignment — `POST /sped-staffing/assignments` — requires the request body to carry `expected_plan_version`, the client’s last-observed `version` of the target staffing plan. If the plan’s current `version` has advanced since that observation (because the plan was activated, another assignment was created against it, reconciliation began, or the plan was closed), the create is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from committing budget against a plan state it never saw. Reporting an absence — `POST /sped-staffing/absence-reports` — likewise requires `expected_coverage_plan_version`, the client’s last-observed `version` of the resolved coverage plan; a mismatch with the coverage plan’s current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the caller from filing an absence against a coverage posture that has since been published, reopened, or locked. Both version fields are non-optional on their respective endpoints.

### 2.9. The Plan Cost Ledger: Committed, Settled, and Remaining Budget

Each staffing plan tracks three money figures that together form its fiscal ledger. `committed_cost_cents` is the sum of `projected_weekly_cost_cents` over the plan’s assignments that are in `PROPOSED`, `QUALIFICATION_VERIFIED`, or `ACTIVE`; a `SUSPENDED` assignment’s share has been released at the moment of suspension and is no longer counted. `settled_cost_cents` accumulates the final approved-timesheet labor cost and is posted when the plan closes. `cost_balance_cents` is what remains: the plan’s `total_budget_cents` minus `committed_cost_cents` minus `settled_cost_cents`. Every assignment proposal, activation, suspension, resumption, and ending moves these figures, and the budget gate described in §3.4 and §3.5 is always evaluated against them.

### 2.10. Resource Addressing and Referential Integrity

Resources are addressed by path identifiers such as `planId`, `buildingId`, `studentId`, `orderId`, `paraId`, `assignmentId`, `coveragePlanId`, `absenceId`, `backfillId`, `timesheetId`, `evaluationId`, `formulaId`, and `allocationId`. When a request references several resources, the server validates existence from the leftmost path identifier to the rightmost, and only then validates foreign keys carried in the request body. Each missing resource surfaces its own error: `ERR_PLAN_NOT_FOUND`, `ERR_BUILDING_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_PARAPROFESSIONAL_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COVERAGE_PLAN_NOT_FOUND`, `ERR_ABSENCE_NOT_FOUND`, `ERR_BACKFILL_NOT_FOUND`, `ERR_TIMESHEET_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_FORMULA_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, or `ERR_CHANGE_ORDER_NOT_FOUND` (all HTTP 404). Malformed payloads — a missing required field, a type mismatch, an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400), which also covers violations of the per-plan uniqueness of `building_code`, `student_ref`, and paraprofessional `email`.

List endpoints across the API accept optional equality filters drawn from the resource’s own fields — `plan_id`, `building_id`, `student_id`, `para_id`, `home_building_id`, `status`, `coverage_date`, `assignment_id`, `coverage_plan_id`, `absence_id`, `substitute_para_id`, `formula_id`, and, on the change-order list, `new_building_id` — in addition to the pagination parameters of §2.3.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Staffing Year: Plans, Buildings, and Funding Formulas

A `DistrictStaffingAdmin` begins the year by creating a staffing plan with a display `plan_name`, a `school_year` label such as "2026-27", and a `total_budget_cents` that must be greater than zero. Three policy knobs ride along with sensible defaults: `benefit_threshold_minutes` defaults to 1800 — thirty hours of scheduled work in a week, at or above which a paraprofessional becomes benefit-eligible; `benefit_surcharge_pct` defaults to 0.20, the wage multiplier applied to newly costed assignments while the para is benefit-eligible; and `travel_buffer_minutes` defaults to 30, the required gap between same-day assignments in different buildings. A new plan starts in `DRAFT` with `committed_cost_cents` and `settled_cost_cents` at zero and `cost_balance_cents` equal to the full budget.

Buildings join the plan while it is `DRAFT` or `ACTIVE`; each carries a `name`, a `building_code` unique within its plan, and an optional `hardship_factor`, defaulting to 1.0 and bounded between 0.5 and 2.0, that scales the building’s funding allocation to reflect hard-to-staff postings. A plan with no buildings cannot go live: activation moves the plan from `DRAFT` to `ACTIVE`, requires at least one building (else `ERR_PLAN_HAS_NO_BUILDINGS`), and increments the plan’s `version` by one. Attempting activation from any state other than `DRAFT` is rejected with `ERR_PLAN_NOT_DRAFT`. Later, when the year winds down, beginning reconciliation moves the plan from `ACTIVE` to `RECONCILING`, and reopening moves it from `RECONCILING` back to `ACTIVE` — a revision loop for correcting reconciliation findings, requiring `RECONCILING` (else `ERR_PLAN_NOT_RECONCILING`) — with each transition incrementing the plan’s `version` by one. Configuration writes against a plan that is neither `DRAFT` nor `ACTIVE` fail with `ERR_PLAN_NOT_ACTIVE`.

Funding policy is versioned through allocation formulas, created while the plan is `DRAFT` or `ACTIVE` with a flat per-building `base_grant_cents` of zero or more, a `per_minute_rate_cents` funding rate per IEP minute that must exceed zero, the three service weights `weight_one_to_one`, `weight_shared_support`, and `weight_transitional`, and a `period_weeks` count of weeks in a funding period that must exceed zero. Each formula receives a `version_no` assigned as one more than the highest existing `version_no` for the plan, starting at 1, and begins life in `DRAFT`. Publishing a formula moves it from `DRAFT` to `PUBLISHED` and automatically moves any other `PUBLISHED` formula of the same plan to `SUPERSEDED`, so at most one formula is ever live per plan.

With an `ACTIVE` plan and a `PUBLISHED` formula, the administrator runs the provisional allocation computation, supplying the `formula_id` and a free-form `period_label`. The computation requires the formula to be `PUBLISHED` (else `ERR_FORMULA_NOT_PUBLISHED`) and may run only once per pairing of formula and period label (else `ERR_ALLOCATIONS_ALREADY_COMPUTED`). It produces one funding-allocation row per building of the plan, each pinned to the formula version used at compute time and starting in `PROVISIONAL`. A row’s `provisional_amount_cents` projects entitlement-driven funding: take the building’s students whose status is `REGISTERED`, `ACTIVE_IEP`, or `SERVICE_CHANGE_PENDING` (students who have `EXITED` are excluded), multiply each student’s current `iep_minutes_per_week` by the weight matching their current `iep_service_level`, and sum those weighted minutes into a service sum. The building’s raw amount is the `base_grant_cents` plus that service sum multiplied by `per_minute_rate_cents` and by the formula’s `period_weeks`; this raw amount is rounded half-up to integer cents first, and only then multiplied by the building’s `hardship_factor`, with the product rounded half-up once more to yield `provisional_amount_cents`.

### 3.2. Students, IEP Entitlements, and Service Change Orders

A `SpecialEdCoordinator` registers each student into a plan that is `DRAFT` or `ACTIVE`, supplying the placement `building_id`, a privacy-safe opaque `student_ref` unique within the plan, the `iep_service_level` (`ONE_TO_ONE`, `SHARED_SUPPORT`, or `TRANSITIONAL`), the mandated `iep_minutes_per_week` which must exceed zero, and optionally a `required_qualification` defaulting to `NONE` (the alternatives being `BEHAVIOR_SUPPORT`, `MEDICAL_DELEGATION`, and `SIGN_LANGUAGE`). New students start `REGISTERED`; activating the IEP moves a student from `REGISTERED` to `ACTIVE_IEP`, the only state in which assignments may be activated for them.

Mid-year changes to a student’s service are never edited in place; they flow through a service change order. Filing an order requires the student to be `ACTIVE_IEP` (a student in `SERVICE_CHANGE_PENDING` or already `EXITED` is rejected with `ERR_STUDENT_NOT_ASSIGNABLE`) and requires that no other order for the student is sitting in `FILED` or `APPROVED` (else `ERR_OPEN_CHANGE_ORDER_EXISTS`). The order names the `student_id`, a `change_type` of `MINUTES_CHANGE`, `QUALIFICATION_CHANGE`, `BUILDING_TRANSFER`, or `EXIT`, a free-text `reason`, and the payload matching the type: `new_minutes_per_week` (greater than zero) when minutes change, `new_required_qualification` when the qualification changes, or `new_building_id` for a building transfer; a missing required field for the chosen type is `ERR_INVALID_REQUEST`. Filing succeeds into status `FILED` and immediately moves the student from `ACTIVE_IEP` to `SERVICE_CHANGE_PENDING`.

A `DistrictStaffingAdmin` then reviews the order: approval moves it from `FILED` to `APPROVED`, and returning moves it from `APPROVED` back to `FILED` — a revision loop in which the order’s body is immutable but may be re-approved, with the student remaining `SERVICE_CHANGE_PENDING` throughout. Effectuation, performed by a `SpecialEdCoordinator`, moves an `APPROVED` order to `EFFECTIVE` and is only valid while the student still sits in `SERVICE_CHANGE_PENDING` (else `ERR_CHANGE_ORDER_INVALID_STATE`). On effectuation the student’s record absorbs the order’s new values — minutes, qualification, or building per the `change_type` — and, for every type other than `EXIT`, the student returns to `ACTIVE_IEP`; an `EXIT` order instead moves the student to `EXITED`. Either way, the effectuation fires the three-hop reassignment cascade. Hop one ends each of the student’s assignments in `PROPOSED`, `QUALIFICATION_VERIFIED`, `ACTIVE`, or `SUSPENDED` with `end_reason` `SERVICE_CHANGED`, returning each ended assignment’s `weekly_minutes` to its para’s `weekly_scheduled_minutes` and its `projected_weekly_cost_cents` to the plan’s `committed_cost_cents` (a `SUSPENDED` assignment has already released both, so only its `funding_status` moves). Hop two: the drop in a para’s `weekly_scheduled_minutes` may flip that para’s `benefit_eligible` to false. Hop three: such a flip re-costs the para’s remaining `PROPOSED` and `QUALIFICATION_VERIFIED` assignments at the non-surcharged effective rate — `daily_cost_cents` and `projected_weekly_cost_cents` are recomputed — and the plan’s `committed_cost_cents` is adjusted by the resulting delta. Cancelling an order, from either `FILED` or `APPROVED`, moves it to `CANCELLED` and simply returns the student to `ACTIVE_IEP` with no assignment impact.

### 3.3. The Paraprofessional Roster: Hiring, Training Records, and Employment Status

A `DistrictStaffingAdmin` builds the roster while the plan is `DRAFT` or `ACTIVE`. Each paraprofessional record carries a `home_building_id`, `full_name`, a contact `email` unique within the plan, a `base_hourly_wage_cents` that must exceed zero, a `contracted_max_weekly_minutes` hard weekly cap that must exceed zero, and a `hire_date` in ISO `YYYY-MM-DD` form that later serves as a selector tie-break. New paras start `ACTIVE` with an empty `qualifications` array, `weekly_scheduled_minutes` of zero, `benefit_eligible` false, `confirmed_benefit_eligible` null until plan close, and `benefit_variance_cents` zero until plan close.

Training completions are appended to the `qualifications` array one entry at a time, each entry recording the `qualification` earned, its `completed_on` date, an optional `expires_on` (null for non-expiring credentials), and a `revoked` flag that starts false. A qualification counts as *current* on a given date when its `completed_on` falls on or before that date, its `expires_on` is null or falls after that date, and `revoked` is false. Revoking a qualification sets its entry’s `revoked` flag true and fires a safety cascade: every `ACTIVE` assignment of that para whose `required_qualification_snapshot` equals the revoked credential moves to `SUSPENDED` under the release cascade of §3.5, and for each such assignment, if the current logical weekday is among its `days_of_week` and a `PUBLISHED` coverage plan exists for the assignment’s building and the current date, an absence report is auto-created in `REPORTED` and the coverage plan’s posture is recomputed. The same cascade applies when a qualification expires as observed against the logical clock.

Employment status is managed through a set-status operation carrying the desired `status`. A para moves between `ACTIVE` and `ON_LEAVE` in both directions; while `ON_LEAVE` the para is excluded from the backfill selector’s candidate pool. Moving to `SEPARATED` — from either `ACTIVE` or `ON_LEAVE` — is terminal and ends every non-`ENDED` assignment of the para with `end_reason` `COORDINATOR_ENDED`, running the same minutes-release, benefit-flip, and re-costing cascade as a service change.

### 3.4. Proposing Assignments: Snapshots, Costing, and the Funding Gate

Assignments are proposed by a `SpecialEdCoordinator` against an `ACTIVE` plan, with the optimistic-concurrency field `expected_plan_version` enforced as described in §2.8. The proposal names the `student_id`, `para_id`, and service `building_id`; the service window from `start_date` through `end_date`, where the end must not precede the start (else `ERR_INVALID_DATE_RANGE`); a non-empty `days_of_week` subset of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`; and the daily window from `daily_start_minute` to `daily_end_minute`, where the end must be strictly later than the start. At creation the assignment snapshots three facts that will never again track their sources: `service_level_snapshot` from the student’s current `iep_service_level`, `required_qualification_snapshot` from the student’s current `required_qualification`, and `base_wage_snapshot_cents` from the para’s current `base_hourly_wage_cents`. The assignment’s `weekly_minutes` is the daily window length in minutes multiplied by the number of days in `days_of_week`.

Before the proposal is accepted, four guards run in the priority order of §2.7. The para must hold the `required_qualification_snapshot` current as of the current logical date — completed on or before it, unexpired, unrevoked — else `ERR_QUALIFICATION_NOT_CURRENT` (a snapshot of `NONE` is satisfied by every para). The new window must survive the schedule-overlap rule against the para’s other `ACTIVE` assignments, else `ERR_SCHEDULE_OVERLAP`: two windows on a shared weekday in the *same* building conflict when they genuinely overlap, with bare adjacency (one window’s start equal to the other’s end) explicitly allowed; windows in *different* buildings conflict unless the gap between them is at least the plan’s `travel_buffer_minutes` on both sides — the first window must not begin before the second window’s end plus the buffer, and the second must not begin before the first window’s end plus the buffer. Adding the assignment’s `weekly_minutes` to the para’s `weekly_scheduled_minutes` must not exceed `contracted_max_weekly_minutes`, else `ERR_WEEKLY_MINUTES_CAP_EXCEEDED`. Finally the fiscal guard: the plan’s `committed_cost_cents` plus this candidate’s `projected_weekly_cost_cents` must not exceed `total_budget_cents` minus `settled_cost_cents`, else `ERR_INSUFFICIENT_BUDGET`.

The candidate’s cost is computed in a pinned order. First, project the para’s schedule: the para’s current `weekly_scheduled_minutes` over `ACTIVE` assignments plus this assignment’s own `weekly_minutes` — this assignment’s minutes deliberately count toward the threshold even though its cost is what is being computed. Second, compare that projection to the plan’s `benefit_threshold_minutes`: at or above means benefit-eligible for costing purposes. Third, build the effective hourly rate as `base_wage_snapshot_cents` plus a qualification differential — 0 cents for `NONE`, 150 for `BEHAVIOR_SUPPORT`, 200 for `MEDICAL_DELEGATION`, 250 for `SIGN_LANGUAGE` — plus a one-to-one stipend of 100 cents when the `service_level_snapshot` is `ONE_TO_ONE` (zero otherwise). Fourth, if the projected schedule is benefit-eligible, multiply the effective rate by one plus the plan’s `benefit_surcharge_pct`. Fifth, the `daily_cost_cents` is the daily window length divided by sixty, multiplied by that effective rate, rounded half-up to integer cents — and only then is `projected_weekly_cost_cents` formed by multiplying the rounded day cost by the number of service days. An accepted proposal lands in `PROPOSED` with `funding_status` `PROVISIONALLY_FUNDED`, its projected cost is added to the plan’s `committed_cost_cents`, and the plan’s `version` increments by one.

While an assignment remains non-activated — `PROPOSED` or `QUALIFICATION_VERIFIED` — its cost is not frozen: whenever the para’s `benefit_eligible` flips in either direction, the assignment’s `daily_cost_cents` and `projected_weekly_cost_cents` are recomputed under the rule above and the plan’s committed cost absorbs the delta. A coordinator confirms the credential picture through qualification verification, moving the assignment from `PROPOSED` to `QUALIFICATION_VERIFIED` after re-checking the para’s currency against the `required_qualification_snapshot` (else `ERR_QUALIFICATION_NOT_CURRENT`); attempting any assignment transition from a state that does not declare it is rejected with `ERR_ASSIGNMENT_INVALID_STATE`.

Activation moves a `QUALIFICATION_VERIFIED` assignment to `ACTIVE` behind two gates. The student must currently be `ACTIVE_IEP` (else `ERR_STUDENT_NOT_ASSIGNABLE`), and the funding gate must pass: the assignment’s `funding_status` must still read `PROVISIONALLY_FUNDED`, and the plan’s `committed_cost_cents` — which has included this assignment’s projected cost since proposal — must not exceed `total_budget_cents` minus `settled_cost_cents`. A failed gate rejects with `ERR_INSUFFICIENT_BUDGET` and flips the assignment’s `funding_status` to `UNFUNDED`. A successful activation locks `daily_cost_cents` permanently against any further recompute, moves `funding_status` to `FUNDED`, adds the assignment’s `weekly_minutes` to the para’s `weekly_scheduled_minutes`, and recomputes the para’s `benefit_eligible`.

### 3.5. The Assignment Lifecycle: Suspension, Resumption, Ending, and Automatic Re-Funding

A paraprofessional’s live load, `weekly_scheduled_minutes`, is the sum of `weekly_minutes` over that para’s `ACTIVE` assignments plus the `coverage_minutes` of that para’s `ACCEPTED` backfill assignments whose `absence_date` falls inside the current ISO week — Monday through Sunday — as read from the logical clock. The stored `benefit_eligible` flag is this load compared against the plan’s `benefit_threshold_minutes`: at or above the threshold the flag is true, below it the flag is false. Because activations, suspensions, resumptions, endings, and backfill answers all move the load, the flag is recomputed at each of those moments, and every flip re-costs the para’s non-activated assignments per §3.4.

Suspension moves an `ACTIVE` assignment to `SUSPENDED`, whether a `SpecialEdCoordinator` initiates it directly or the system fires it through the qualification revoke-or-expire cascade of §3.3. Suspension releases the assignment’s `weekly_minutes` from the para’s `weekly_scheduled_minutes`, recomputes the para’s `benefit_eligible`, and subtracts the assignment’s `projected_weekly_cost_cents` from the plan’s `committed_cost_cents`; the `funding_status` stays `FUNDED` throughout.

Resumption from `SUSPENDED` back to `ACTIVE` re-runs four checks, in the §2.7 order: the qualification re-check against the snapshot (else `ERR_QUALIFICATION_NOT_CURRENT`); the schedule re-check against the para’s other `ACTIVE` assignments under the same travel-buffer rule (else `ERR_SCHEDULE_OVERLAP`); the capacity re-check that the para’s `weekly_scheduled_minutes` plus the assignment’s `weekly_minutes` stays within `contracted_max_weekly_minutes` (else `ERR_WEEKLY_MINUTES_CAP_EXCEEDED`); and the budget re-check that the plan’s `committed_cost_cents` plus the assignment’s `projected_weekly_cost_cents` fits within `total_budget_cents` minus `settled_cost_cents` (else `ERR_INSUFFICIENT_BUDGET`, with `funding_status` flipping to `UNFUNDED` on failure). Success re-adds the weekly minutes and recomputes benefit eligibility, and re-adds the projected cost to the plan’s committed figure.

Ending moves an assignment from any non-terminal state to `ENDED`, with `end_reason` set to `COORDINATOR_ENDED` when a coordinator ends it directly, `SERVICE_CHANGED` under a service change order, or `PLAN_CLOSED` at plan close; the field is null on live assignments. The release depends on the departing state: from `PROPOSED` or `QUALIFICATION_VERIFIED`, the plan’s `committed_cost_cents` releases the projected cost; from `ACTIVE`, the para’s `weekly_scheduled_minutes` and benefit flag release and recompute as well; from `SUSPENDED`, both releases already happened at suspension. Every ending, regardless of path, moves `funding_status` to `SETTLED`.

The funding dimension is parallel to and independent of the workflow status. An assignment is born `PROVISIONALLY_FUNDED`; successful activation moves it to `FUNDED`; a failed funding gate at activation moves it to `UNFUNDED`, as does a failed budget re-check at resumption from `FUNDED`; and ending settles it — `PROVISIONALLY_FUNDED` to `SETTLED` when ended from `PROPOSED` or `QUALIFICATION_VERIFIED`, `FUNDED` to `SETTLED` when ended from `ACTIVE` or `SUSPENDED`. One recovery path exists: after every committed-cost release on the plan, the system reconsiders the plan’s `UNFUNDED` assignments in `created_at` order, earliest first, and any whose `projected_weekly_cost_cents` fits again within the remaining budget returns to `PROVISIONALLY_FUNDED`. This bubble-up re-fund is the only way back from `UNFUNDED`; nothing else resurrects it.

### 3.6. Daily Coverage: Absence Reports, the Backfill Selector, and Coverage Posture

Each school day’s coverage for a building is organized through a coverage plan, created by a `SpecialEdCoordinator` against an `ACTIVE` staffing plan with a `building_id` and the `coverage_date` it governs; the pairing of building and date must be unique, else `ERR_DUPLICATE_COVERAGE_PLAN`. A coverage plan starts `DRAFT` with `coverage_posture` `OPEN`. Publication moves it from `DRAFT` to `PUBLISHED` and increments its `version`. Reopening returns a `PUBLISHED` plan to `DRAFT`, and locking moves a `PUBLISHED` plan to `LOCKED` with `coverage_posture` becoming `FROZEN`; both reopen and lock require the posture to be `OPEN` — no linked absence in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` — else `ERR_COVERAGE_GAPS_OPEN`, and both increment the plan’s `version` by one. Reconciliation moves a `LOCKED` plan to `RECONCILED` and sweeps every linked record to a terminal state: linked absences in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` become `UNCOVERED` while a `COVERED` absence stays `COVERED`; linked backfill assignments in `OFFERED` become `CANCELLED` while `ACCEPTED` ones become `COMPLETED` with the substitute’s minutes untouched because the one-off date has already passed; the plan’s `version` increments by one.

The `coverage_posture` itself is derived: `OPEN` when no linked non-terminal absence exists, `GAPS_OPEN` when at least one linked absence sits in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED`, and `FROZEN` whenever the plan is `LOCKED` or `RECONCILED`. Posture recomputes whenever a linked absence is created, covered, or cancelled.

An absence is reported by a `Teacher` or a `Paraprofessional` against an `ACTIVE` assignment, carrying the `assignment_id`, the `absence_date`, a free-text `reason`, and the `expected_coverage_plan_version` of §2.8. The weekday of the absence must be one of the assignment’s `days_of_week` (else `ERR_INVALID_DATE_RANGE`). The server resolves the coverage plan from the assignment’s building and the absence date: a missing plan or one still `DRAFT` rejects with `ERR_COVERAGE_PLAN_NOT_PUBLISHED`, while a `LOCKED` or `RECONCILED` plan rejects with `ERR_COVERAGE_PLAN_FROZEN`. A paraprofessional reporter must own the assignment — `X-User-ID` must equal the assignment’s `para_id` — else `ERR_ABSENCE_NOT_OWN`. The created report derives its `plan_id` from the assignment, links the resolved `coverage_plan_id`, copies the assignment’s daily window length into `absence_minutes`, records the creator’s role in `reported_by_role`, initializes `declined_para_ids` to empty, and lands in `REPORTED`; the coverage plan’s posture recomputes — typically `OPEN` to `GAPS_OPEN` — and the coverage plan’s `version` increments by one.

Filling the gap runs the backfill selector, invoked from a `REPORTED` or `ESCALATED` absence. The candidate pool keeps only paras who are `ACTIVE`; who are not the absent assignment’s own para; whose `id` does not appear in the absence’s `declined_para_ids`; who hold the assignment’s `required_qualification_snapshot` current as of the `absence_date` — completed on or before it, `expires_on` null or after it, not revoked, with a snapshot of `NONE` satisfied by everyone; who have no time conflict, meaning no `ACTIVE` assignment sharing the absence weekday whose window violates the travel-buffer overlap rule against the absent assignment’s window and buildings; and whose `weekly_scheduled_minutes` plus the absence’s `absence_minutes` stays within their `contracted_max_weekly_minutes`. Survivors are ranked ascending by `weekly_scheduled_minutes` (least-loaded first), then by `base_hourly_wage_cents` (cheapest first), then by `hire_date` (earliest hire first), then by `created_at` as the final deterministic fallback — the record `id` is never used as a tie-break. The head of the ranking receives the offer: the absence moves to `BACKFILL_PENDING` and a backfill assignment is created in `OFFERED` with the chosen `substitute_para_id`, the `absence_id`, the derived `plan_id`, and `coverage_minutes` equal to the absence’s `absence_minutes`. An empty pool creates no offer and moves the absence to `ESCALATED` instead; a later selector run from `ESCALATED` retries the same logic, still excluding paras recorded in `declined_para_ids`.

Escalation by a coordinator moves a `REPORTED` or `BACKFILL_PENDING` absence to `ESCALATED` and cancels any `OFFERED` backfill attached to it. Cancelling an absence — from `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` — moves it to `CANCELLED`, cancels any `OFFERED` backfill, and recomputes the coverage posture, which may return to `OPEN`. Absence transitions attempted from a state that does not declare them are rejected with `ERR_ABSENCE_INVALID_STATE`.

The offered para answers personally: both acceptance and decline require `X-User-ID` to equal the offer’s `substitute_para_id`, else `ERR_BACKFILL_NOT_OWN`, and any other backfill transition from a wrong state is `ERR_BACKFILL_INVALID_STATE`. Acceptance moves the offer from `OFFERED` to `ACCEPTED`, the absence to `COVERED`, adds the `coverage_minutes` to the substitute’s `weekly_scheduled_minutes`, recomputes the substitute’s `benefit_eligible`, and recomputes the coverage posture, which may return to `OPEN`. Declining moves the offer to `DECLINED`, appends the substitute’s id to the absence’s `declined_para_ids` — excluding them from all future selector runs for that absence — and leaves the absence in `BACKFILL_PENDING`. A coordinator may also cancel a backfill outright: from `OFFERED` the offer simply becomes `CANCELLED`; from `ACCEPTED` the cancellation additionally subtracts the `coverage_minutes` back out of the substitute’s `weekly_scheduled_minutes`, recomputes their `benefit_eligible`, and re-opens the absence by moving it from `COVERED` back to `BACKFILL_PENDING`.

### 3.7. Timesheets: Logging Work, Double-Log Protection, and Approval

A `Paraprofessional` logs work against their own assignments while the plan is `ACTIVE`, supplying the `assignment_id`, the `work_date`, and the worked window from `start_minute` to `end_minute`. The entry’s `para_id` is always fixed to the caller’s `X-User-ID`, and attempting to log against an assignment owned by a different para is rejected with `ERR_TIMESHEET_NOT_OWN`. The `work_date` must fall within the assignment’s `start_date`-to-`end_date` window, the start must be a minute-of-day from 0 through 1439, and the end must be strictly later than the start; violations are `ERR_INVALID_DATE_RANGE`. The entry’s `minutes_worked` is the window length in minutes, and its `plan_id` derives from the assignment.

Double-logging is policed with closed-interval semantics, a deliberate contrast to the half-open assignment rule: for the same para and `work_date`, a new entry conflicts with any existing entry in `SUBMITTED` or `APPROVED` when the intervals touch or overlap at all — the new start on or before the other’s end, and the other’s start on or before the new end — and touching endpoints count as conflict. Entries still in `DRAFT` do not participate. The check runs at creation and again at submission, and a conflict rejects with `ERR_TIMESHEET_OVERLAP`.

New entries sit in `DRAFT`. Submission moves an entry from `DRAFT` to `SUBMITTED`, requires the caller to be the entry’s para (else `ERR_TIMESHEET_NOT_OWN`), and re-runs the closed-interval overlap check. A `BuildingAdministrator` then approves — `SUBMITTED` to `APPROVED`, terminal — or rejects, which bounces the entry from `SUBMITTED` back to `DRAFT` for correction and resubmission; both decisions are accepted while the plan is `ACTIVE` or `RECONCILING`, and any other transition attempt is `ERR_TIMESHEET_INVALID_STATE`. Approved minutes are the system’s record of truth: they feed the confirmed benefit variant and the final allocation variant computed at plan close (§3.9).

### 3.8. Evaluations: Authoring, Countersigning, Acknowledgement, and Dispute

A `Teacher` authors an evaluation of a paraprofessional while the plan is `ACTIVE`, supplying the `para_id`, the review window from `period_start` to `period_end` (the end must not precede the start, else `ERR_INVALID_DATE_RANGE`), a `professionalism_score` and an `instructional_support_score` each on a 1-to-5 scale, and free-text `comments`. The server stamps the author’s `X-User-ID` into `created_by_user_id`, leaves `countersigned_by_user_id` and `resolution_note` null, and starts the evaluation in `DRAFT`.

Submission moves an evaluation from `DRAFT` to `SUBMITTED` and is restricted to the author — `X-User-ID` must equal `created_by_user_id`, else `ERR_EVALUATION_NOT_OWN`. Countersigning moves a `SUBMITTED` evaluation to `COUNTERSIGNED` under an explicit segregation of duties: the acting `BuildingAdministrator` must not be the author, so `X-User-ID` equal to `created_by_user_id` is rejected with `ERR_EVALUATION_SELF_COUNTERSIGN` (HTTP 403); on success the administrator’s `X-User-ID` is written to `countersigned_by_user_id`. The evaluated para then responds personally — both acknowledgement and dispute require `X-User-ID` to equal the evaluation’s `para_id`, else `ERR_EVALUATION_NOT_OWN` — moving the evaluation from `COUNTERSIGNED` to `ACKNOWLEDGED`, which is terminal, or to `DISPUTED`. A `BuildingAdministrator` resolves a `DISPUTED` evaluation into the terminal `RESOLVED` state, recording the request’s `resolution_note` on the record. Any evaluation transition attempted from a state that does not declare it is `ERR_EVALUATION_INVALID_STATE`.

### 3.9. Closing the Plan: Confirmed Benefits, Final Allocations, and Cost Settlement

When the year’s books are ready, a `DistrictStaffingAdmin` closes the plan, moving it from `RECONCILING` to the terminal `CLOSED`. Close is gated on two aggregate conditions, evaluated in the §2.7 order: no timesheet entry for the plan may remain in `SUBMITTED` (else `ERR_UNRESOLVED_TIMESHEETS`), and no coverage plan may remain in `DRAFT`, `PUBLISHED`, or `LOCKED` — every one must be `RECONCILED` (else `ERR_UNRECONCILED_COVERAGE_PLANS`).

Closing recomputes every projected figure against chronological fact. For each paraprofessional, the confirmed benefit variant replays the year week by week: for each ISO week (Monday through Sunday) from the earliest assignment `start_date` through the close date, the para’s approved minutes are the sum of `minutes_worked` over that para’s `APPROVED` timesheet entries with `work_date` in the week — `DRAFT` and `SUBMITTED` entries never count. The para’s `confirmed_benefit_eligible` is true when at least one such week reached the plan’s `benefit_threshold_minutes`, and false otherwise. The `benefit_variance_cents` claws back surcharge that was provisionally charged but never confirmed: for each ISO week in which the para had at least one assignment `ACTIVE` and the week’s approved minutes fell below the threshold, each such assignment contributes its locked `projected_weekly_cost_cents` minus the same weekly cost recomputed at the non-surcharged effective rate; assignments that were originally costed while the para was ineligible contribute zero, because no surcharge was ever charged on them. Both fields are null and zero respectively until the close computes them.

Each funding-allocation row likewise settles. Its `final_amount_cents` replays approved labor instead of entitlements: sum `minutes_worked` over `APPROVED` timesheets, map each entry through its assignment’s `student_id` to the student whose *current* building is this row’s building, and weight each student’s minutes by the student’s *current* service-level weight. The raw amount is the `base_grant_cents` plus those weighted minutes multiplied by `per_minute_rate_cents` — the formula’s `period_weeks` is deliberately not applied to actuals — rounded half-up once, then multiplied by the building’s `hardship_factor` and rounded half-up once more at the very end, per the round-once regime of §2.6. The row’s `variance_cents` is the final amount minus the provisional amount, negative when delivery fell short of entitlement, and the row moves from `PROVISIONAL` to `FINALIZED`.

The plan’s own ledger settles too. `settled_cost_cents` becomes the sum, over every `APPROVED` timesheet entry in the plan, of the entry’s `minutes_worked` divided by sixty and multiplied by the hourly rate locked into its assignment’s cost at activation — base wage snapshot plus qualification differential and any one-to-one stipend, with the benefit surcharge if it applied at costing time — each entry rounded half-up to integer cents before summing. `cost_balance_cents` is then recomputed per §2.9. Every assignment still `ACTIVE` or `SUSPENDED` is ended with `end_reason` `PLAN_CLOSED` and its committed share released, and the plan’s `version` increments by one.

## 4. Endpoint Definitions

Operations that create a new resource respond with HTTP 201; state transitions, modifications, and the clock-setting operation respond with HTTP 200; reads respond with HTTP 200. Request payloads, preconditions, and side effects for each operation are specified by the narratives of §2 and §3 rather than restated here; the table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving); startup default is exactly 2026-05-01T00:00:00Z | DistrictStaffingAdmin |
| POST | `/sped-staffing/plans` | Create a staffing plan (DRAFT) | DistrictStaffingAdmin |
| GET | `/sped-staffing/plans` | List staffing plans | Any |
| GET | `/sped-staffing/plans/{planId}` | Get one staffing plan | Any |
| POST | `/sped-staffing/plans/{planId}/activate` | DRAFT → ACTIVE (requires at least one building) | DistrictStaffingAdmin |
| POST | `/sped-staffing/plans/{planId}/begin-reconciliation` | ACTIVE → RECONCILING | DistrictStaffingAdmin |
| POST | `/sped-staffing/plans/{planId}/reopen` | RECONCILING → ACTIVE (revision loop) | DistrictStaffingAdmin |
| POST | `/sped-staffing/plans/{planId}/close` | RECONCILING → CLOSED; runs confirmed benefit variant, final allocation variant, settles costs | DistrictStaffingAdmin |
| POST | `/sped-staffing/buildings` | Create a building (plan DRAFT or ACTIVE) | DistrictStaffingAdmin |
| GET | `/sped-staffing/buildings` | List buildings | Any |
| GET | `/sped-staffing/buildings/{buildingId}` | Get one building | Any |
| POST | `/sped-staffing/students` | Register a student (plan DRAFT or ACTIVE); initial REGISTERED | SpecialEdCoordinator |
| GET | `/sped-staffing/students` | List students | Any |
| GET | `/sped-staffing/students/{studentId}` | Get one student | Any |
| POST | `/sped-staffing/students/{studentId}/activate-iep` | REGISTERED → ACTIVE_IEP | SpecialEdCoordinator |
| POST | `/sped-staffing/service-change-orders` | File a service change order; student moves to SERVICE_CHANGE_PENDING | SpecialEdCoordinator |
| GET | `/sped-staffing/service-change-orders` | List service change orders | Any |
| GET | `/sped-staffing/service-change-orders/{orderId}` | Get one service change order | Any |
| POST | `/sped-staffing/service-change-orders/{orderId}/approve` | FILED → APPROVED | DistrictStaffingAdmin |
| POST | `/sped-staffing/service-change-orders/{orderId}/return` | APPROVED → FILED (revision loop) | DistrictStaffingAdmin |
| POST | `/sped-staffing/service-change-orders/{orderId}/effectuate` | APPROVED → EFFECTIVE; applies student changes and ends assignments with the 3-hop cascade | SpecialEdCoordinator |
| POST | `/sped-staffing/service-change-orders/{orderId}/cancel` | FILED or APPROVED → CANCELLED; student back to ACTIVE_IEP | SpecialEdCoordinator |
| POST | `/sped-staffing/paraprofessionals` | Create a paraprofessional (plan DRAFT or ACTIVE); initial ACTIVE | DistrictStaffingAdmin |
| GET | `/sped-staffing/paraprofessionals` | List paraprofessionals | Any |
| GET | `/sped-staffing/paraprofessionals/{paraId}` | Get one paraprofessional | Any |
| POST | `/sped-staffing/paraprofessionals/{paraId}/set-status` | Set para status ACTIVE, ON_LEAVE, or SEPARATED per state machine | DistrictStaffingAdmin |
| POST | `/sped-staffing/paraprofessionals/{paraId}/qualifications` | Record completed training: append qualification, completed_on, optional expires_on | DistrictStaffingAdmin |
| POST | `/sped-staffing/paraprofessionals/{paraId}/qualifications/revoke` | Revoke a qualification; cascades suspension of ACTIVE assignments requiring it | DistrictStaffingAdmin |
| POST | `/sped-staffing/assignments` | Propose an IEP-mandated assignment (plan ACTIVE; OCC on plan version) | SpecialEdCoordinator |
| GET | `/sped-staffing/assignments` | List assignments | Any |
| GET | `/sped-staffing/assignments/{assignmentId}` | Get one assignment | Any |
| POST | `/sped-staffing/assignments/{assignmentId}/verify-qualifications` | PROPOSED → QUALIFICATION_VERIFIED (re-checks qualification currency) | SpecialEdCoordinator |
| POST | `/sped-staffing/assignments/{assignmentId}/activate` | QUALIFICATION_VERIFIED → ACTIVE (student gate and funding gate; locks daily cost) | SpecialEdCoordinator |
| POST | `/sped-staffing/assignments/{assignmentId}/suspend` | ACTIVE → SUSPENDED (releases weekly minutes and committed cost) | SpecialEdCoordinator |
| POST | `/sped-staffing/assignments/{assignmentId}/resume` | SUSPENDED → ACTIVE (re-runs qualification, overlap, cap, and budget checks) | SpecialEdCoordinator |
| POST | `/sped-staffing/assignments/{assignmentId}/end` | Any non-terminal state → ENDED (end_reason COORDINATOR_ENDED) | SpecialEdCoordinator |
| POST | `/sped-staffing/coverage-plans` | Create a daily coverage plan for a building (plan ACTIVE); unique per building and date | SpecialEdCoordinator |
| GET | `/sped-staffing/coverage-plans` | List coverage plans | Any |
| GET | `/sped-staffing/coverage-plans/{coveragePlanId}` | Get one coverage plan | Any |
| POST | `/sped-staffing/coverage-plans/{coveragePlanId}/publish` | DRAFT → PUBLISHED | SpecialEdCoordinator |
| POST | `/sped-staffing/coverage-plans/{coveragePlanId}/reopen` | PUBLISHED → DRAFT (requires posture OPEN) | SpecialEdCoordinator |
| POST | `/sped-staffing/coverage-plans/{coveragePlanId}/lock` | PUBLISHED → LOCKED (requires posture OPEN); posture becomes FROZEN | SpecialEdCoordinator |
| POST | `/sped-staffing/coverage-plans/{coveragePlanId}/reconcile` | LOCKED → RECONCILED; sweeps linked absences and backfills to terminal states | SpecialEdCoordinator |
| POST | `/sped-staffing/absence-reports` | Report an absence against an ACTIVE assignment; resolves the PUBLISHED coverage plan; OCC on coverage plan version | Teacher, Paraprofessional |
| GET | `/sped-staffing/absence-reports` | List absence reports | Any |
| GET | `/sped-staffing/absence-reports/{absenceId}` | Get one absence report | Any |
| POST | `/sped-staffing/absence-reports/{absenceId}/escalate` | REPORTED or BACKFILL_PENDING → ESCALATED; cancels any OFFERED backfill | SpecialEdCoordinator |
| POST | `/sped-staffing/absence-reports/{absenceId}/cancel` | REPORTED, BACKFILL_PENDING, or ESCALATED → CANCELLED; cancels any OFFERED backfill | SpecialEdCoordinator |
| POST | `/sped-staffing/absence-reports/{absenceId}/backfill-offers` | Run the backfill selector; success creates an OFFERED backfill, empty pool escalates | SpecialEdCoordinator |
| GET | `/sped-staffing/backfill-assignments` | List backfill assignments | Any |
| GET | `/sped-staffing/backfill-assignments/{backfillId}` | Get one backfill assignment | Any |
| POST | `/sped-staffing/backfill-assignments/{backfillId}/accept` | OFFERED → ACCEPTED (substitute self only) | Paraprofessional |
| POST | `/sped-staffing/backfill-assignments/{backfillId}/decline` | OFFERED → DECLINED (substitute self only); records decline for selector exclusion | Paraprofessional |
| POST | `/sped-staffing/backfill-assignments/{backfillId}/cancel` | OFFERED or ACCEPTED → CANCELLED; ACCEPTED cancel re-opens the absence and reverts minutes | SpecialEdCoordinator |
| POST | `/sped-staffing/timesheets` | Para logs a work interval (plan ACTIVE; own assignments only); DRAFT | Paraprofessional |
| GET | `/sped-staffing/timesheets` | List timesheets | Any |
| GET | `/sped-staffing/timesheets/{timesheetId}` | Get one timesheet | Any |
| POST | `/sped-staffing/timesheets/{timesheetId}/submit` | DRAFT → SUBMITTED (own only; overlap re-check) | Paraprofessional |
| POST | `/sped-staffing/timesheets/{timesheetId}/approve` | SUBMITTED → APPROVED (plan ACTIVE or RECONCILING) | BuildingAdministrator |
| POST | `/sped-staffing/timesheets/{timesheetId}/reject` | SUBMITTED → DRAFT (bounce-back revision loop; plan ACTIVE or RECONCILING) | BuildingAdministrator |
| POST | `/sped-staffing/evaluations` | Teacher authors an evaluation of a para (plan ACTIVE); DRAFT | Teacher |
| GET | `/sped-staffing/evaluations` | List evaluations | Any |
| GET | `/sped-staffing/evaluations/{evaluationId}` | Get one evaluation | Any |
| POST | `/sped-staffing/evaluations/{evaluationId}/submit` | DRAFT → SUBMITTED (author only) | Teacher |
| POST | `/sped-staffing/evaluations/{evaluationId}/countersign` | SUBMITTED → COUNTERSIGNED (countersigner must differ from author) | BuildingAdministrator |
| POST | `/sped-staffing/evaluations/{evaluationId}/acknowledge` | COUNTERSIGNED → ACKNOWLEDGED (the evaluated para only) | Paraprofessional |
| POST | `/sped-staffing/evaluations/{evaluationId}/dispute` | COUNTERSIGNED → DISPUTED (the evaluated para only) | Paraprofessional |
| POST | `/sped-staffing/evaluations/{evaluationId}/resolve` | DISPUTED → RESOLVED | BuildingAdministrator |
| POST | `/sped-staffing/allocation-formulas` | Create a formula version for a plan (plan DRAFT or ACTIVE) | DistrictStaffingAdmin |
| GET | `/sped-staffing/allocation-formulas` | List allocation formulas | Any |
| GET | `/sped-staffing/allocation-formulas/{formulaId}` | Get one allocation formula | Any |
| POST | `/sped-staffing/allocation-formulas/{formulaId}/publish` | DRAFT → PUBLISHED; supersedes any other PUBLISHED formula of the plan | DistrictStaffingAdmin |
| POST | `/sped-staffing/funding-allocations/compute` | Compute provisional allocations: one row per building pinned to a PUBLISHED formula (plan ACTIVE) | DistrictStaffingAdmin |
| GET | `/sped-staffing/funding-allocations` | List funding allocations | Any |
| GET | `/sped-staffing/funding-allocations/{allocationId}` | Get one funding allocation | Any |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_BUILDING_NOT_FOUND | 404 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_PARAPROFESSIONAL_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_COVERAGE_PLAN_NOT_FOUND | 404 |
| ERR_ABSENCE_NOT_FOUND | 404 |
| ERR_BACKFILL_NOT_FOUND | 404 |
| ERR_TIMESHEET_NOT_FOUND | 404 |
| ERR_EVALUATION_NOT_FOUND | 404 |
| ERR_FORMULA_NOT_FOUND | 404 |
| ERR_ALLOCATION_NOT_FOUND | 404 |
| ERR_CHANGE_ORDER_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_PLAN_NOT_DRAFT | 409 |
| ERR_PLAN_NOT_RECONCILING | 409 |
| ERR_PLAN_HAS_NO_BUILDINGS | 409 |
| ERR_STUDENT_NOT_ASSIGNABLE | 409 |
| ERR_OPEN_CHANGE_ORDER_EXISTS | 409 |
| ERR_CHANGE_ORDER_INVALID_STATE | 409 |
| ERR_QUALIFICATION_NOT_CURRENT | 422 |
| ERR_SCHEDULE_OVERLAP | 409 |
| ERR_WEEKLY_MINUTES_CAP_EXCEEDED | 422 |
| ERR_INSUFFICIENT_BUDGET | 402 |
| ERR_ASSIGNMENT_INVALID_STATE | 409 |
| ERR_DUPLICATE_COVERAGE_PLAN | 409 |
| ERR_COVERAGE_PLAN_NOT_PUBLISHED | 409 |
| ERR_COVERAGE_PLAN_FROZEN | 409 |
| ERR_COVERAGE_GAPS_OPEN | 409 |
| ERR_ABSENCE_INVALID_STATE | 409 |
| ERR_ABSENCE_NOT_OWN | 403 |
| ERR_BACKFILL_INVALID_STATE | 409 |
| ERR_BACKFILL_NOT_OWN | 403 |
| ERR_TIMESHEET_INVALID_STATE | 409 |
| ERR_TIMESHEET_OVERLAP | 409 |
| ERR_TIMESHEET_NOT_OWN | 403 |
| ERR_EVALUATION_INVALID_STATE | 409 |
| ERR_EVALUATION_NOT_OWN | 403 |
| ERR_EVALUATION_SELF_COUNTERSIGN | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_FORMULA_NOT_PUBLISHED | 409 |
| ERR_ALLOCATIONS_ALREADY_COMPUTED | 409 |
| ERR_UNRECONCILED_COVERAGE_PLANS | 409 |
| ERR_UNRESOLVED_TIMESHEETS | 409 |
| ERR_INVALID_DATE_RANGE | 400 |
