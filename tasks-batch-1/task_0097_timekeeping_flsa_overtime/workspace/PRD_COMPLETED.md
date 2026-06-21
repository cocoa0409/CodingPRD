# Timekeeping & FLSA Overtime API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a Timekeeping and Wage Computation API serving employers whose hourly, non-exempt workforce is governed simultaneously by the federal Fair Labor Standards Act (FLSA) and by a patchwork of stricter state rules. The recurring operational pain it solves is that the same week of punches can be paid two materially different ways: a California-style worksite computes overtime per day (anything beyond eight hours in a calendar day at one-and-a-half times, beyond twelve at double time), while a Texas-style worksite ignores the clock each day and pays overtime only on the weekly total beyond forty hours. A correct paycheck depends on never double-counting the same hour as both daily and weekly overtime, on honoring missed-break premiums and tipped-wage make-up obligations, and on a tamper-evident record of every retroactive time edit.

The system models the full chain from configuration through settlement: an employer and its per-state wage rule sets, worksites and employees, scheduled shifts and the punches that realize them, audited supervisor edits, meal and rest break records, declared and pooled tips, the weekly timesheet that reconciles all of the above into gross wages, and the payroll run that locks approved weeks for payment. Two governance disciplines run through every workflow. The first is **segregation of duties** — the supervisor who edits a punch or submits a timesheet may not be the one who approves it. The second is **optimistic concurrency** — once an approver or a payroll administrator has observed a particular version of a weekly timesheet, any intervening change to that week invalidates the action they were about to take, so they must re-read before they can commit.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing the role header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same `ERR_UNAUTHENTICATED` is returned when an endpoint that an employee performs in their own name is called without an `X-User-ID`. Once authenticated, a caller may only invoke the operations their role permits; any attempt outside that grant is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three roles exist, spelled exactly as follows: `PayrollAdmin`, `Supervisor`, and `Employee`.

A `PayrollAdmin` is the back-office operator who configures employers, wage rule sets, worksites, and employees, and who runs payroll. Its `X-User-ID` is an **opaque operator identifier**, not tied to any persisted entity; the server may record it on the resources it touches but never compares it to any entity's `id`. A `Supervisor` is the floor operator who schedules shifts, records breaks, applies audited punch edits, manages tip pools, and submits, approves, or rejects timesheets. Its `X-User-ID` is likewise an **opaque operator identifier**; the server records it — for example as `submitted_by_user_id` or `approved_by_user_id` on a timesheet week, or as `editor_user_id` on a time edit — to enforce segregation of duties, but it is not the `id` of any stored entity. An `Employee`, by contrast, is **entity-backed**: when `X-User-Role` is `Employee`, the `X-User-ID` is the `id` of the acting `Employee` record. Ownership checks on any resource that references an employee compare that resource's `employee_id` to the caller's `X-User-ID`; a mismatch where ownership is required is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Append-Only Audit Record

Almost every resource in this system — employers, wage rule sets, worksites, employees, shifts, time punches, break records, tip declarations, tip pools, timesheet weeks, and payroll runs — carries a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, recording first creation and most recent modification respectively. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it is the basis for the optimistic-concurrency checks described in §2.6.

One entity is deliberately different. A **time edit** is an append-only audit record: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`, because once written it is immutable and is never modified. This is what makes the edit log tamper-evident — history accumulates, but no prior row can be altered or back-dated.

### 2.5. Money, Time, and Rounding Precision

All monetary amounts are stored and exchanged as integer cents — never as fractional dollars — so fields such as `base_rate_cents`, `declared_cents`, `gross_wages_cents`, and `total_gross_cents` are whole-cent integers. All durations are stored as integer minutes; hours are derived as minutes divided by sixty and that ratio is treated as an exact value during intermediate computation, with no premature rounding.

Rounding happens only where the rules below explicitly call for it, and the method is always **round half up** to the indicated precision. The regular rate of pay is rounded to whole cents before any premium multiplier is applied. Each money component of gross wages is independently rounded to whole cents and only then summed — the round-then-sum order is fixed and must not be reordered into a sum-then-round. Minute aggregates on a timesheet (`regular_minutes`, `ot_minutes`, `dt_minutes`) are produced by multiplying their hour values by sixty and rounding to the nearest whole minute.

### 2.6. Optimistic Concurrency on the Weekly Timesheet

Two timesheet operations are guarded by optimistic concurrency control, and only these two. Approving a submitted week and locking an approved week into a payroll run each require the caller to send `expected_timesheet_week_version` carrying the `version` of the `TimesheetWeek` the caller last observed. The server compares that value to the week's current `version`. If they differ — because a reject-then-resubmit revision loop, a punch-edit cascade, or a fresh approval cycle has advanced the week since the caller read it — the operation is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents an approver from blessing a different set of numbers than the one they reviewed, and prevents payroll from committing a gross figure that a late correction has already superseded. Endpoints not named here take no version field.

### 2.7. Sequential Existence and Left-to-Right Resolution

When a path or request body references other resources, those references are resolved before any business rule runs, and they are resolved left to right. A path identifier that names no existing resource, or a body field naming a missing employer, worksite, employee, shift, punch, pool, week, or run, yields `ERR_NOT_FOUND` (HTTP 404) at the first such missing reference, before later references or downstream validations are evaluated. Listing endpoints that expose a parent's children — an employer's wage rule sets, a shift's punches, a punch's edit trail, and the like — first confirm the parent exists, then return the matching children.

### 2.8. Validation Ordering

Where several checks can fail on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: the presence and validity of `X-User-Role`, then the presence of `X-User-ID` where an employee acts in their own name (both `ERR_UNAUTHENTICATED`). Authorization follows — the role must be permitted for the operation (`ERR_FORBIDDEN`). Existence checks come next: referenced resources must exist (`ERR_NOT_FOUND`), and where a wage rule set is required to govern the work, one must exist for the relevant employer-and-state pair (`ERR_NO_WAGE_RULESET`, HTTP 422). Ownership is then enforced for employee-acting punch operations (`ERR_NOT_RESOURCE_OWNER`). State legality comes after that — the target must be in a state that permits the requested transition (`ERR_INVALID_STATE`), including the frozen-timesheet guard (`ERR_TIMESHEET_FROZEN`) and the open-punch guard on submit (`ERR_OPEN_PUNCH_IN_WEEK`). Only once these structural gates pass does the system evaluate the business-specific constraints — reason requirements, duration positivity, interval overlaps, segregation of duties, concurrency, and generic field-level validity. Two parsing-level checks are the exception to this layering, because they run while the request body is first read, before any referenced-resource existence lookup: malformed, missing, wrong-typed, or invalid-enum fields (`ERR_INVALID_REQUEST`), and the non-negativity of money or duration inputs on create requests — a negative `base_rate_cents` on employee creation, negative `minutes` on a break record, or negative `declared_cents` on a tip declaration (`ERR_VALIDATION`) — both of which therefore mask a later `ERR_NOT_FOUND`. The detailed business rules in §3 must be read against this ordering: an earlier failure always masks a later one.

## 3. Business Logic & Workflows

### 3.1. Configuring the Employer, Its Wage Rules, and Its Workforce

A `PayrollAdmin` stands up an employer by supplying its `legal_name`. Three further attributes may be supplied or left to default: `workweek_start_dow`, the day on which the seven-day FLSA workweek begins, defaulting to `MON` and drawn from the set `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`; `federal_min_wage_cents`, defaulting to 725 (that is, $7.25 per hour); and `federal_tipped_cash_wage_cents`, the federal tipped direct cash wage, defaulting to 213.

Wage behavior is not global — it is keyed by state. The administrator creates a wage rule set by naming the `employer_id` it belongs to and the two-letter `state_code` it governs; a state code must be unique within an employer, and a second rule set for the same employer-and-state pair is rejected with `ERR_DUPLICATE_RULESET`. Each rule set carries a battery of switches and thresholds, all optional with defaults. `daily_ot_enabled` defaults to false; when true, hours past `daily_ot_threshold_hours` (default 8) in a calendar day earn time-and-a-half, and hours past `daily_dt_threshold_hours` (default 12) earn double time — the California pattern. `weekly_ot_threshold_hours` defaults to 40 and is the weekly line above which FLSA overtime applies. `seventh_day_rule_enabled` defaults to false; when true, the seventh consecutive worked day in a workweek is paid at time-and-a-half for its first eight hours and double time beyond. `meal_break_premium_enabled` and `rest_break_premium_enabled` each default to false and control whether a missed break of that kind generates a premium hour. `state_min_wage_cents` defaults to 725 and feeds the tipped true-up. Worksites are created by a `PayrollAdmin` with an `employer_id`, a `name`, and a two-letter `state_code`; the worksite's state code is what selects the governing wage rule set for any work performed there, by matching the employer-and-state pair.

Employees are created by a `PayrollAdmin` against an `employer_id` and a `home_worksite_id` (the default worksite for their shifts and punches), with a `full_name`, an FLSA `classification` of either `EXEMPT` or `NON_EXEMPT`, and a `base_rate_cents` hourly rate that must be zero or greater. The optional `is_tipped` flag defaults to false and only carries meaning for a `NON_EXEMPT` worker. The `classification` is consequential: an `EXEMPT` employee never accrues overtime, double time, or break premiums, as §3.6 makes precise. Every employee's `status` is initialized to `ACTIVE` on creation; there is no termination workflow in scope, so `ACTIVE` is the only value `status` ever holds. Negative money or duration inputs on employee creation — a negative `base_rate_cents`, for instance — are rejected with `ERR_VALIDATION` (HTTP 422), and any write with a missing required field, wrong type, or invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 3.2. Scheduling Shifts and the Punch Lifecycle

A `Supervisor` schedules a shift against an `employee_id` and a `worksite_id`, fixing its `scheduled_start` and `scheduled_end` as ISO 8601 UTC instants; the end must fall strictly after the start, and a schedule that does not satisfy this is rejected with `ERR_INVALID_SCHEDULE`. A new shift may not overlap an existing non-`CANCELLED` shift for the same employee, where shift intervals are treated as **half-open** — the span runs from the start up to but not including the end — so two shifts that meet exactly, one ending at the instant the next begins, do **not** overlap; a genuine overlap is rejected with `ERR_SHIFT_OVERLAP`. A freshly created shift enters `SCHEDULED`. A `Supervisor` may cancel a shift only while it is still `SCHEDULED` with no punch opened, moving it to `CANCELLED`; an attempt to cancel once the shift has progressed is rejected with `ERR_INVALID_STATE`. `CLOSED` and `CANCELLED` are the shift's terminal states.

The acting `Employee` realizes a shift by opening a time punch, supplying a `clock_in` instant. Opening the first punch is permitted only when the shift is `SCHEDULED`, when the caller's own `id` equals the shift's `employee_id`, and when the employee has no other `OPEN` punch anywhere — a second concurrent open is rejected with `ERR_PUNCH_ALREADY_OPEN`. Furthermore, the new punch's interval may not overlap any existing non-`VOIDED`, `CLOSED` punch for the same employee, and here the interval is treated as **closed on both ends**: a new `clock_in` exactly equal to a prior punch's `clock_out` does collide, because a worker cannot be in two places at the instant of changeover. Because an opening punch has no `clock_out` yet, the collision test at open time is whether the new `clock_in` falls within any existing `CLOSED` punch's closed interval — that is, `clock_in` lies between that punch's `clock_in` and `clock_out` inclusive. Such a collision is rejected with `ERR_PUNCH_OVERLAP`. A successful open creates the punch in `OPEN` and advances the shift from `SCHEDULED` to `OPEN`.

The same `Employee` closes the punch by supplying a `clock_out`. Closing is permitted only while the punch is `OPEN`, and the clock-out must fall strictly after the effective clock-in, or the close is rejected with `ERR_NEGATIVE_DURATION`. On a successful close the punch moves `OPEN → CLOSED`; the `clock_out` is stamped, `worked_minutes` is computed as the whole minutes between the effective clock-in and clock-out, and `workday_date` is set to the UTC calendar date (formatted `YYYY-MM-DD`) of the clock-in, which is the bucket key the daily-overtime logic uses. This same close advances the owning shift from `OPEN → CLOSED` — one physical action settles both rows. Closing also recomputes the shift's detention: `detention_minutes` becomes the whole minutes by which the actual clock-out exceeds `scheduled_end`, never going below zero, and `detention_flagged` becomes true precisely when `detention_minutes` exceeds the fifteen-minute grace allowance, marking unauthorized over-detention. Until a punch closes, `detention_minutes` is zero. A punch's `worked_minutes` reads zero while it is `OPEN`. A punch carries a `status` of `OPEN`, `CLOSED`, or `VOIDED`, and `CLOSED` and `VOIDED` are its terminal states.

### 3.3. Audited Edits and Voids

Punches are not free to rewrite. A `Supervisor` corrects a `CLOSED` punch through an audited edit that names the `field` to change — either `CLOCK_IN` or `CLOCK_OUT` — and the `new_value` for it, accompanied by a mandatory `reason`. An empty reason is rejected with `ERR_EDIT_REASON_REQUIRED`. The punch must be `CLOSED`, and the resulting `clock_out` must still fall strictly after the resulting `clock_in`, or the edit is rejected with `ERR_NEGATIVE_DURATION`. Crucially, no edit is permitted while the punch's covering timesheet week is `APPROVED` or `LOCKED`; such an attempt is rejected with `ERR_TIMESHEET_FROZEN`. A permitted edit keeps the punch `CLOSED` (a self-loop) and produces several effects at once: it appends one immutable `TimeEdit` row recording the `punch_id`, the edited `field`, the editor's identity in `editor_user_id` (the supervisor's `X-User-ID`), the prior value snapshotted into `old_value`, and the supplied `new_value` and `reason`; it applies the new value to the punch and recomputes `worked_minutes`, re-derives `workday_date` from the resulting `clock_in` (the UTC calendar date of the post-edit clock-in), and sets the punch's `edited` flag to true; it bumps the punch's `version` (this happens on every successful edit, independent of whether any timesheet week covers it); it recomputes the owning shift's `detention_minutes` and `detention_flagged` whenever the `CLOCK_OUT` was the field changed; and, when a timesheet week in `DRAFT`, `SUBMITTED`, or `REJECTED` covers the punch's `workday_date`, it triggers a recompute of that week's derived wage fields (also bumping that week's `version`).

A `Supervisor` may also void a punch. Voiding an `OPEN` punch sets it to `VOIDED` and, if its shift had no other punch, reverts that shift back to `SCHEDULED`. Voiding a `CLOSED` punch is permitted only while its covering timesheet week is not `APPROVED` or `LOCKED` (else `ERR_TIMESHEET_FROZEN`); it sets the punch to `VOIDED`, forces its `worked_minutes` to zero, and cascades a recompute of the owning timesheet week's derived wage fields so the lost time drops out of the paycheck. Voided punches are excluded from every wage calculation.

### 3.4. Breaks and the Missed-Break Premium

A break is logged against a shift through a break record naming its `shift_id`, the `employee_id`, the `kind` (`MEAL` or `REST`), and whether it was `taken`; when taken, the `minutes` duration may be given and defaults to 0, and a missed break carries 0 minutes. Both a `Supervisor` and the affected `Employee` may file break records, and negative `minutes` are rejected with `ERR_VALIDATION`. The system derives `premium_owed` on each record: it is true exactly when the break was not taken, the governing wage rule set has the matching premium enabled (`meal_break_premium_enabled` for a `MEAL`, `rest_break_premium_enabled` for a `REST`), and the employee is `NON_EXEMPT`. Recording a missed break flagged as a premium against an `EXEMPT` employee is not eligible and is rejected with `ERR_EXEMPT_NOT_ELIGIBLE` (HTTP 422), since exempt workers never earn break premiums; this rejection fires precisely when the break is not `taken`, the employee is `EXEMPT`, and the governing wage rule set has the matching premium (`meal_break_premium_enabled` for a `MEAL`, `rest_break_premium_enabled` for a `REST`) enabled — a missed break for an `EXEMPT` employee whose rule set does not enable that premium (or where no governing rule set exists) is accepted with `premium_owed` false.

Break premiums roll up onto the weekly timesheet as `break_premium_hours`. The roll-up counts at most one premium hour per kind per workday: if an employee misses two meal breaks on the same calendar day, that still yields exactly one meal premium hour for that day, and likewise for rest. The week's `break_premium_hours` is the sum, over every workday-and-kind pair in the week, of one for each pair that owes a premium and zero otherwise — counting only break records whose shift's `scheduled_start` date falls inside the workweek, and only for a `NON_EXEMPT` employee whose governing rule set enables that kind of premium. Each premium hour is later valued at the employee's straight `base_rate_cents`.

### 3.5. Declaring Tips, Pooling, and Distribution

A tip declaration records the `employee_id`, the `workday_date` (formatted `YYYY-MM-DD`) the tips were earned, the `declared_cents` amount (zero or greater), and an optional `pool_id` that defaults to null when the declaration is not contributed to a pool. Both a `Supervisor` and the `Employee` may file declarations. When a declaration names a pool, the owning tip pool's `pooled_cents` is recomputed as the sum of `declared_cents` over every declaration whose `pool_id` points at that pool.

A `Supervisor` opens a tip pool for a worksite-and-day by giving its `worksite_id` and `workday_date`; it enters `OPEN`. The pool exposes a computed `pooled_cents` (the contributing total) and a computed `distributed_cents` (the amount paid out, which equals `pooled_cents` once distribution completes). Distribution, performed by a `Supervisor`, is allowed only from `OPEN` and requires at least one contributing declaration with positive total weight, failing which it is rejected with `ERR_EMPTY_TIP_POOL`. On distribution the pool moves `OPEN → DISTRIBUTED`, `distributed_cents` is set equal to `pooled_cents`, and the pooled money is allocated across the contributing employees in proportion to how much each worked that day.

The allocation is a waterfall that conserves every cent. First, `pooled_cents` is summed from the contributing declarations. For each contributing employee, a weight is computed as the sum of `worked_minutes` over that employee's `CLOSED`, non-`VOIDED` punches whose `workday_date` equals the pool's `workday_date`; the total weight is the sum of those per-employee weights and must be greater than zero. Each employee's raw share is `pooled_cents` multiplied by that employee's weight and divided by the total weight, and the integer-cent share is that raw share rounded down to a whole cent. Because flooring leaves a remainder — `pooled_cents` minus the sum of the floored shares — the leftover cents are handed out one cent at a time to employees ordered by descending weight, breaking ties by the employee's `created_at` ascending (never by `id`), until no remainder remains. A `Supervisor` may instead cancel an `OPEN` pool, moving it `OPEN → CANCELLED` and detaching every contributing declaration by resetting each one's `pool_id` to null. `DISTRIBUTED` and `CANCELLED` are the pool's terminal states.

### 3.6. The Weekly Timesheet: Reconciliation and the Dual-Variant Wage Stack

A `Supervisor` opens a timesheet week for an employee by naming the `employee_id` and the `workweek_start`, an inclusive `YYYY-MM-DD` start date that must align with one of the employer's workweek boundaries — meaning its day of week must equal the employer's `workweek_start_dow`; a `workweek_start` that does not so align is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The week begins in `DRAFT`. The week's computed outputs — `regular_minutes`, `ot_minutes`, `dt_minutes`, `break_premium_hours`, `gross_wages_cents`, and `tip_true_up_cents` — and its `payroll_run_id` are all derived; `payroll_run_id` is null until the week is locked into a run. The full recompute runs whenever the week is submitted or resubmitted, and whenever a punch edit or void cascades into it. Submitting requires the week to be in `DRAFT` (or `REJECTED`, for a resubmission) and requires that no `OPEN` punch exists for the employee anywhere inside the workweek, else the submit is rejected with `ERR_OPEN_PUNCH_IN_WEEK`. A submit recomputes all derived wage fields from the week's punches, breaks, and tips, records the acting supervisor in `submitted_by_user_id`, advances the week `DRAFT → SUBMITTED` (or `REJECTED → SUBMITTED`), and increments `version` by one. Before any wage math runs, a governing wage rule set must exist for the employer-and-state of the work; if none does, submit (and shift creation) is rejected with `ERR_NO_WAGE_RULESET`.

The wage stack is computed in a fixed order. **Daily breakdown comes first.** For each `workday_date` in the workweek, sum `worked_minutes` over the employee's `CLOSED`, non-`VOIDED` punches bearing that date, and treat that total as a number of hours by dividing by sixty. When the governing rule set does not enable daily overtime, the whole day is straight time and the day contributes nothing to daily overtime or double time. When `daily_ot_enabled` is true, the day's straight hours are the lesser of the day's worked hours and `daily_ot_threshold_hours` (default 8); the day's overtime hours are the worked hours capped at `daily_dt_threshold_hours` (default 12) minus the eight-hour line, never below zero — that is, the band between eight and twelve hours; and the day's double-time hours are whatever worked hours exceed twelve, never below zero. The seventh-day rule overrides this when `seventh_day_rule_enabled` is true and the day is the seventh consecutive worked calendar day within the workweek: then the day contributes no straight hours, its overtime hours are the lesser of the day's worked hours and eight, and its double-time hours are whatever exceeds eight. These per-day overtime and double-time hours are summed across the week into the week's daily-overtime and daily-double-time totals.

**Weekly resolution comes second, and exists precisely to avoid paying for the same hour twice.** Take the week's total worked hours (the sum of all `worked_minutes` divided by sixty). The straight-time pool is those total hours minus the hours the daily rule already classified as overtime or double time. Weekly overtime is whatever of that straight-time pool exceeds `weekly_ot_threshold_hours` (default 40), never below zero. The week's regular hours are the straight-time pool minus that weekly-overtime excess; the week's overtime hours are the daily-overtime total plus the weekly-overtime excess; and the week's double-time hours are exactly the daily double-time total. Each of these three hour figures is multiplied by sixty and rounded to the nearest whole minute to populate `regular_minutes`, `ot_minutes`, and `dt_minutes`. Two variants fall out of this single procedure: at a worksite whose rule set enables daily overtime (the California pattern), daily overtime and double time are non-zero and the weekly step captures only non-daily hours beyond forty, so daily and weekly overtime are never double-counted and double time can be non-zero; at a worksite whose rule set leaves daily overtime disabled (the FLSA weekly pattern), the daily totals are zero, so overtime is simply the weekly hours beyond forty and double time is zero.

**The regular rate of pay comes third**, valuing the premiums. Straight earnings are `base_rate_cents` multiplied by the week's total worked hours; there is no nondiscretionary bonus in scope, so that addend is fixed at zero. The regular rate per hour is those straight earnings divided by total worked hours, rounded half up to whole cents before any multiplier is applied; when the week has zero total worked hours the regular rate is zero. Because straight time is already paid on every hour worked, the overtime premium is the **half-time** uplift — a multiplier of 0.5 on the regular rate — and the double-time premium is the **full extra** — a multiplier of 1.0 — layered on top of straight time.

**Gross wages come last, by round-then-sum.** For a `NON_EXEMPT` employee, the straight component is `base_rate_cents` times total worked hours, rounded half up to whole cents; the overtime premium is the regular rate times 0.5 times the overtime hours (`ot_minutes` divided by sixty), rounded half up; the double-time premium is the regular rate times 1.0 times the double-time hours (`dt_minutes` divided by sixty), rounded half up; the break-premium component is `break_premium_hours` times `base_rate_cents`; and the tipped make-up amount is `tip_true_up_cents`. `gross_wages_cents` is the sum of these five independently rounded components. For an `EXEMPT` employee the entire hourly stack is forced to zero: `regular_minutes`, `ot_minutes`, `dt_minutes`, `break_premium_hours`, `tip_true_up_cents`, and `gross_wages_cents` are all zero, because salaried hourly pay is out of scope and exempt workers accrue no overtime, double time, or break premium.

### 3.7. Tipped True-Up Against the Minimum Wage

`tip_true_up_cents` is the employer's make-up obligation when a tipped worker's direct cash plus tips would otherwise fall below the minimum wage, and it is computed only for an employee who is both `is_tipped` and `NON_EXEMPT`; for everyone else it is zero. The applicable minimum is the greater of the governing rule set's `state_min_wage_cents` and the employer's `federal_min_wage_cents`. The week's tips are the sum of `declared_cents` over the employee's tip declarations whose `workday_date` falls in the week. The direct cash is `base_rate_cents` (which, for a tipped worker, stands in as the tipped cash wage) times the week's total worked hours, kept as an exact (unrounded) value at this stage. The required floor is the applicable minimum times the week's total worked hours, rounded half up to whole cents. The make-up is the required floor minus what the worker actually earned (the exact direct cash plus the integer-cent tips), but never below zero — the employer covers a shortfall and never claws back a surplus — and that shortfall is then rounded half up to whole cents to yield `tip_true_up_cents`. The federal default minimum, absent an override, is 725 cents.

### 3.8. Approval, Segregation of Duties, and the Revision Loop

A submitted week is reviewed by a `Supervisor`, who either approves or rejects it, and approval is the point where segregation of duties bites. Approval requires the week to be `SUBMITTED`, and then — in the §2.8 order, segregation before concurrency — requires that the approver's `X-User-ID` differ both from `submitted_by_user_id` and from the `editor_user_id` of every `TimeEdit` applied to any punch in that week (an approver who submitted the week, or who edited any punch feeding it, is rejected with `ERR_SEGREGATION_OF_DUTIES`, HTTP 409), and only after that passes requires the OCC field `expected_timesheet_week_version` to match the week's current `version` (else `ERR_STALE_VERSION`, HTTP 412, per §2.6); when both a segregation violation and a stale version are present, `ERR_SEGREGATION_OF_DUTIES` is returned. A clean approval records `approved_by_user_id`, advances the week `SUBMITTED → APPROVED`, and increments `version`. Rejection, also by a `Supervisor`, requires the week to be `SUBMITTED` and that the rejecter's `X-User-ID` differ from `submitted_by_user_id` (else the same `ERR_SEGREGATION_OF_DUTIES`); it advances the week `SUBMITTED → REJECTED`, clears `submitted_by_user_id`, and increments `version`. A rejected week loops back: resubmission (`REJECTED → SUBMITTED`) recomputes the wage fields, records a fresh `submitted_by_user_id`, and increments `version` again — the same open-punch guard applies. `LOCKED` is the timesheet's terminal state.

### 3.9. Payroll Runs: Locking, Finalizing, and Cancelling

A `PayrollAdmin` opens a payroll run for an employer by naming the `employer_id`, an inclusive `period_start`, and an inclusive `period_end` that is on or after the start, all as `YYYY-MM-DD`; a `period_end` earlier than `period_start` is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The run begins `OPEN` and exposes computed `total_gross_cents` and `included_week_count`, both starting at zero. The administrator locks an approved week into the run by supplying the `timesheet_week_id` and the OCC field `expected_timesheet_week_version`. Locking requires, in the §2.8 order, that the run be `OPEN` and the week be `APPROVED` (each otherwise `ERR_INVALID_STATE`, the run's state checked before the week's), then that the run cover the week — the week's `workweek_start` falls within `[period_start, period_end]`, a week outside that span being rejected with `ERR_WEEK_OUTSIDE_PERIOD` (HTTP 422) — and only after those structural gates pass that `expected_timesheet_week_version` match the week's current `version` (else `ERR_STALE_VERSION`, HTTP 412 — guarding against a late punch void having superseded the gross since it was observed); when both an outside-period condition and a stale version are present, `ERR_WEEK_OUTSIDE_PERIOD` is returned. A successful lock sets the week's `payroll_run_id`, advances it `APPROVED → LOCKED`, increments the week's `version`, increments the run's `included_week_count`, and adds the week's `gross_wages_cents` to the run's `total_gross_cents`.

Finalizing a run, by a `PayrollAdmin`, requires it to be `OPEN` and to hold at least one `LOCKED` week, else it is rejected with `ERR_EMPTY_PAYROLL_RUN`; finalization moves the run `OPEN → FINALIZED`, after which it is immutable. Cancelling an `OPEN` run instead reverts each `LOCKED` week back to `APPROVED` and clears each week's `payroll_run_id`, resets the run's `total_gross_cents` and `included_week_count` to zero, and moves the run `OPEN → CANCELLED`. `FINALIZED` and `CANCELLED` are the run's terminal states.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify or transition an existing resource — including the punch-close, distribute, submit, approve, reject, include, finalize, and cancel actions — return `200 OK`. The audited punch edit is the exception: it creates a new, distinct audit record and therefore returns `201 Created`. The table below lists each endpoint's method, path, purpose, and the roles permitted to call it; request and response bodies are reconstructed from the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employers` | Create employer | PayrollAdmin |
| GET | `/employers/{id}` | Get employer | PayrollAdmin, Supervisor |
| GET | `/employers/{id}/wage-rulesets` | List an employer's wage rule sets | PayrollAdmin, Supervisor |
| POST | `/wage-rulesets` | Create a per-state wage rule set | PayrollAdmin |
| POST | `/worksites` | Create worksite | PayrollAdmin |
| GET | `/worksites` | List/filter worksites | PayrollAdmin, Supervisor |
| GET | `/worksites/{id}` | Get worksite | PayrollAdmin, Supervisor |
| POST | `/employees` | Create employee | PayrollAdmin |
| GET | `/employees` | List/filter employees | PayrollAdmin, Supervisor |
| GET | `/employees/{id}` | Get employee | PayrollAdmin, Supervisor, Employee |
| POST | `/shifts` | Schedule a shift | Supervisor |
| GET | `/shifts` | List/filter shifts | PayrollAdmin, Supervisor, Employee |
| GET | `/shifts/{id}` | Get shift (with detention fields) | PayrollAdmin, Supervisor, Employee |
| POST | `/shifts/{id}/cancel` | Cancel a SCHEDULED shift | Supervisor |
| POST | `/shifts/{id}/punches` | Open a time punch (clock in) for a shift | Employee |
| GET | `/shifts/{id}/punches` | List punches for a shift | PayrollAdmin, Supervisor, Employee |
| GET | `/punches` | List/filter punches | PayrollAdmin, Supervisor, Employee |
| GET | `/punches/{id}` | Get punch | PayrollAdmin, Supervisor, Employee |
| POST | `/punches/{id}/close` | Close a punch (clock out) | Employee |
| POST | `/punches/{id}/edits` | Apply an audited edit to a CLOSED punch | Supervisor |
| GET | `/punches/{id}/edits` | List the audit trail for a punch | PayrollAdmin, Supervisor |
| POST | `/punches/{id}/void` | Void a punch | Supervisor |
| POST | `/break-records` | Record a meal/rest break taken or missed | Supervisor, Employee |
| GET | `/break-records` | List/filter break records | PayrollAdmin, Supervisor, Employee |
| GET | `/break-records/{id}` | Get a break record | PayrollAdmin, Supervisor, Employee |
| POST | `/tip-declarations` | Declare workday tips | Supervisor, Employee |
| GET | `/tip-declarations` | List/filter tip declarations | PayrollAdmin, Supervisor, Employee |
| GET | `/tip-declarations/{id}` | Get a tip declaration | PayrollAdmin, Supervisor, Employee |
| POST | `/tip-pools` | Open a tip pool for a worksite/day | Supervisor |
| GET | `/tip-pools` | List/filter tip pools | PayrollAdmin, Supervisor |
| GET | `/tip-pools/{id}` | Get tip pool | PayrollAdmin, Supervisor |
| POST | `/tip-pools/{id}/distribute` | Distribute pooled tips by worked-minutes share | Supervisor |
| POST | `/tip-pools/{id}/cancel` | Cancel a tip pool | Supervisor |
| POST | `/timesheet-weeks` | Open a draft timesheet week for an employee | Supervisor |
| GET | `/timesheet-weeks` | List/filter timesheet weeks | PayrollAdmin, Supervisor, Employee |
| GET | `/timesheet-weeks/{id}` | Get a timesheet week with computed wage fields | PayrollAdmin, Supervisor, Employee |
| POST | `/timesheet-weeks/{id}/submit` | Submit or resubmit a timesheet week | Supervisor |
| POST | `/timesheet-weeks/{id}/approve` | Approve a submitted timesheet | Supervisor |
| POST | `/timesheet-weeks/{id}/reject` | Reject a submitted timesheet | Supervisor |
| POST | `/payroll-runs` | Open a payroll run for a pay period | PayrollAdmin |
| GET | `/payroll-runs` | List/filter payroll runs | PayrollAdmin, Supervisor |
| GET | `/payroll-runs/{id}` | Get payroll run with totals | PayrollAdmin, Supervisor |
| POST | `/payroll-runs/{id}/include` | Lock an APPROVED timesheet week into this run | PayrollAdmin |
| POST | `/payroll-runs/{id}/finalize` | Finalize an open run | PayrollAdmin |
| POST | `/payroll-runs/{id}/cancel` | Cancel an open run, reverting locked weeks | PayrollAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_NO_WAGE_RULESET` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TIMESHEET_FROZEN` | 409 Conflict |
| `ERR_OPEN_PUNCH_IN_WEEK` | 409 Conflict |
| `ERR_EXEMPT_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EDIT_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NEGATIVE_DURATION` | 422 Unprocessable Entity |
| `ERR_PUNCH_OVERLAP` | 409 Conflict |
| `ERR_PUNCH_ALREADY_OPEN` | 409 Conflict |
| `ERR_INVALID_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_EMPTY_TIP_POOL` | 409 Conflict |
| `ERR_EMPTY_PAYROLL_RUN` | 409 Conflict |
| `ERR_WEEK_OUTSIDE_PERIOD` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RULESET` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
