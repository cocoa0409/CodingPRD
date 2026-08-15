# Substitute Teacher Pool API — Product Requirements Document

## 1. Introduction

School districts live and die by coverage. Every morning, teachers call in sick, attend professional development, or serve jury duty, and every one of those absence days must either be filled from a finite pool of qualified substitutes or absorbed by internal staff working extra periods. Districts that run this process over phone trees and spreadsheets lose the race for the best substitutes to faster districts, overpay on hard-to-fill campuses, and discover payroll discrepancies weeks after the work was done. This document specifies an API that runs the entire discipline programmatically: absence intake, district approval of long-term absences, automated callout with ranked offers, substitute self-claim, incentive and premium pay, internal coverage of last resort, timesheet verification with long-term rate conversion, payroll export against school budgets, and the performance record-keeping — reliability scores, flags, and do-not-return lists — that keeps the pool healthy.

The system is built around a few unforgiving realities of the domain. The substitute pool is scarce, so offers are dispatched one at a time against an eligibility-and-ranking selector, and every acceptance commits money against a school's coverage budget before a single day is worked. Time is deterministic: all expiry, streak, and window calculations read a logical clock rather than the wall clock, so district operators and integrators can rehearse an entire semester in an afternoon. Money is accounted in integer cents with pinned rounding order, and every mutating workflow is either idempotent through state checks or guarded by optimistic concurrency, because a substitute claiming a job and a coordinator editing that job are equally legitimate actors whose views of the absence may diverge.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `DistrictAdmin`, `SchoolCoordinator`, `Teacher`, `Substitute`, and `PayrollClerk`. A request with a missing header or an unrecognized role value is rejected with `ERR_MISSING_OR_INVALID_AUTH_CONTEXT`. A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. The same holds for `PayrollClerk`: the identifier is opaque, recorded nowhere as a foreign key, and confers no resource ownership.

When `X-User-Role` is `Teacher`, `X-User-ID` is the `id` of the acting `StaffMember`; a teacher may only report or cancel absences whose `staff_member_id` equals their `X-User-ID`, and any attempt against another teacher's absence is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION`. When `X-User-Role` is `SchoolCoordinator`, `X-User-ID` is likewise the `id` of a `StaffMember` — one whose `is_coordinator` flag is true — and every write the coordinator performs must target a resource of the school whose `id` matches that staff record's `school_id`; acting on another school's resource is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION`. When `X-User-Role` is `Substitute`, `X-User-ID` is the `id` of the acting `Substitute`; ownership checks on assignments and timesheets compare the resource's `substitute_id` to `X-User-ID`, and a substitute responding to, cancelling, or submitting against someone else's assignment is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not a non-negative integer, or a `limit` outside the 1–100 range, is rejected with `ERR_INVALID_REQUEST` (400). Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order, with ties — common under the logical clock, which stamps many resources at the same instant — broken by creation order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — District, School, StaffMember, Substitute, Clearance, SchoolSubstituteMark, Absence, Assignment, InternalCoverage, Timesheet, PayrollPeriod, and PerformanceFlag — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one with every mutation, anchoring optimistic concurrency control.

Mutations include changes to computed fields: when a cascade refreshes an absence's day counters or a school's budget fields, that parent's `updated_at` advances and its `version` increments just as for a direct edit. Two resource types are deliberately lighter: a Qualification and a DispatchBatch carry only `id` and `created_at`. Both `updated_at` and `version` are absent on these two resources — they are immutable records of a grant and of a run, respectively, and are never the target of an optimistic-concurrency check.

### 2.5. The Logical Clock and Lazy Expiry

The server never reads wall-clock time. All temporal logic — offer expiry, clearance expiry, trailing-score windows, lead-time premium tiers, cutoff sweeps — is evaluated against a **logical clock** whose startup default is exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability, restricted to `DistrictAdmin`, sets this clock to a supplied `to_iso8601` instant and answers with the new `current_utc`. The jump may move the clock backward as well as forward; a backward jump is applied as-is and triggers no expiry at all. Forward jumps apply lazy expiry on the affected entities: any offer whose expiry instant has been reached flips to `EXPIRED`, its absence re-running the selector exactly as at a dispatch batch, and any clearance whose validity date has passed flips to `EXPIRED` status only — the suspension cascade of §3.2 never fires on a clock jump, clock-jump detection falling in §3.2's flip-only bucket. Every timestamp the system writes — an offer's `offered_at`, a batch's `executed_at`, a period's `exported_at`, a reliability event's `occurred_at` — is stamped from this logical clock, so a full absence-to-payroll cycle is exactly reproducible.

### 2.6. Money, Rates, and Rounding Discipline

All monetary quantities in the system — pay rates, premiums, payouts, compensation, and every budget field — are integer numbers of cents; fractional cents never appear in any stored value or API response. Where a calculation produces a non-integer, the rounding method is always **round half up**. Rounding order is pinned wherever it is observable: per-day amounts are rounded first and then summed, never the reverse, because the two orders can differ by cents. The premium multiplier frozen onto each offer is kept exact to two decimal places, which is guaranteed by construction since every premium component is itself a two-decimal fraction. Fill-rate analytics are the single non-monetary rounding surface: rates there are rounded to four decimal places, round half up.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency, and each names its guard field explicitly. A substitute claiming an open absence must supply `expected_absence_version` carrying the absence's `version` as the client last observed it; if another writer has advanced the absence's version since that read — a completed claim or an applied edit — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Editing an absence's dates or requirements carries the identical contract: `expected_absence_version` must equal the absence's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a second well-formed edit sent after another edit has fully completed would otherwise legitimately succeed on a stale view. Updating a district's pay-rule configuration requires `expected_district_version` matching the district's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch; sequential configuration updates are each legitimate, so the stale-version check is the only signal. Successful execution of any of the three operations increments the parent resource's `version` by one. Endpoints not named here take no version field at all.

### 2.8. Validation Pipeline and Error Precedence

Every request is evaluated against a fixed validation pipeline, and an earlier failure masks every later one — the pipeline does not collect errors, it stops at the first. The stages, in evaluation order, are:

1. **Auth context.** Both headers present and the role recognized, else `ERR_MISSING_OR_INVALID_AUTH_CONTEXT` (400).
2. **Request body shape.** Required fields present, types valid, enum values within their declared sets, date fields well-formed `yyyy-mm-dd` strings, `hours_worked` between 0.5 and 12.0 in half-hour steps, and `periods` at least 1; any violation yields `ERR_INVALID_REQUEST` (400). A request body that is not a JSON object likewise yields `ERR_INVALID_REQUEST`, while an absent body is treated as an empty object so required-field checks fire uniformly.
3. **Role permission.** The role is listed for the endpoint in §4, else `ERR_FORBIDDEN_ROLE` (403).
4. **Entity-backed ownership.** Teachers act only on their own absences, coordinators only within their own school, substitutes only on their own assignments and timesheets, else `ERR_RESOURCE_OWNERSHIP_VIOLATION` (403).
5. **Path existence, left to right.** Each identifier in the URL is validated in order, and the request is rejected with the per-entity not-found error — one of `ERR_DISTRICT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_SUBSTITUTE_NOT_FOUND`, `ERR_ABSENCE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`, `ERR_MARK_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_TIMESHEET_NOT_FOUND`, `ERR_PAYROLL_PERIOD_NOT_FOUND`, `ERR_PERFORMANCE_FLAG_NOT_FOUND`, or `ERR_DISPATCH_BATCH_NOT_FOUND` — at the first identifier that does not exist (404).
6. **Body foreign-key existence.** References supplied in the request body (`staff_member_id`, `school_id`, `substitute_id`, `absence_id`, `assignment_id`, `district_id`) must exist, else the same per-entity not-found error (404).
7. **Optimistic concurrency.** The `expected_*_version` guard of §2.7, else `ERR_STALE_VERSION` (412).
8. **State preconditions.** The target's state machine must permit the operation, else the appropriate `ERR_ABSENCE_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_SUBSTITUTE_INVALID_STATE`, `ERR_CLEARANCE_INVALID_STATE`, `ERR_MARK_INVALID_STATE`, `ERR_COVERAGE_INVALID_STATE`, `ERR_TIMESHEET_INVALID_STATE`, `ERR_PAYROLL_PERIOD_INVALID_STATE`, or `ERR_PERFORMANCE_FLAG_INVALID_STATE` (409). Two cross-entity state rules live at this stage: submitting a timesheet additionally requires its assignment to be in `WORKED`, failing as `ERR_ASSIGNMENT_INVALID_STATE`; and proposing internal coverage requires the absence's `fill_status` to be `DISPATCHING`, `UNFILLED`, or `COVERED_INTERNALLY`, failing as `ERR_ABSENCE_INVALID_STATE`.
9. **Do-not-return screen.** No `ACTIVE` `DO_NOT_RETURN` mark for the school and substitute, else `ERR_SUBSTITUTE_DO_NOT_RETURN` (409). This screen guards manual offer creation, self-claim, and offer acceptance.
10. **Clearance screen.** Required clearances `VERIFIED` and valid through the relevant date, else `ERR_CLEARANCE_INVALID` (409). This guards manual offers, self-claim, acceptance, substitute activation, and clearance verification itself.
11. **Qualification screen.** The substitute holds the qualification the absence names, else `ERR_QUALIFICATION_MISMATCH` (409), guarding manual offers, self-claim, and acceptance. A substitute who is both barred and unqualified is therefore rejected with the do-not-return code, the safety screens being evaluated before any temporal rule.
12. **Date sanity.** Ranges well-formed and weekday-bearing, else `ERR_INVALID_DATE_RANGE` (422); the specifics live with each workflow in §3.
13. **Absence overlap.** One teacher may not hold two overlapping non-cancelled absences, else `ERR_ABSENCE_DATE_OVERLAP` (409).
14. **Assignment overlap.** One substitute may not hold two overlapping committed assignments, else `ERR_ASSIGNMENT_DATE_OVERLAP` (409).
15. **Coverage capacity.** Daily and weekly period caps for internal coverage, else `ERR_COVERAGE_CAPACITY_EXCEEDED` (409).
16. **Uniqueness.** One `ACTIVE` mark per school, substitute, and mark type; one qualification per substitute, subject, and grade band; one timesheet per assignment and work date — surfacing as `ERR_DUPLICATE_MARK`, `ERR_DUPLICATE_QUALIFICATION`, or `ERR_DUPLICATE_TIMESHEET` (409).
17. **Timesheet range.** The worked date must fall inside the assignment's range, else `ERR_TIMESHEET_OUT_OF_RANGE` (409).
18. **Long-term approval.** An extension that pushes an absence past the district's approval threshold requires prior district approval, else `ERR_LONG_TERM_APPROVAL_REQUIRED` (409).
19. **Budget sufficiency.** The school's available coverage budget must cover the provisional pay of the assignment being accepted, else `ERR_COVERAGE_BUDGET_INSUFFICIENT` (402). This check is deliberately last: a budget shortfall surfaces only once every other rule has passed.

### 2.9. The School Coverage Budget Ledger

Every school carries a coverage budget expressed in three integer-cent fields. `coverage_budget_total_cents` is the allocation set at creation. `coverage_budget_committed_cents` is the provisional reserve: the sum of `provisional_pay_cents` over the school's assignments currently in `ACCEPTED`, `WORKED`, or `VERIFIED` status, initialized to zero. `coverage_budget_spent_cents` accumulates real charges — payouts charged at payroll export and compensation for internal coverage that has reached `COMPENSATED` — likewise initialized to zero. The derived `coverage_budget_available_cents` is the total minus committed minus spent and is carried on every school response. Acceptance-time checks refuse commitments the budget cannot cover, and export-time capping (§3.7) clamps charges to what remains, keeping the figure non-negative on those paths; the one path exempt from a sufficiency check is assignment extension (§3.5), which adjusts the committed figure by the provisional-pay delta and so can push the available figure below zero. Committed funds are released the moment the commitment dissolves — a cancellation of an accepted assignment, a no-show, or the reserve-release leg of payroll export — so the ledger always reflects the school's true exposure.

### 2.10. Substitute Reliability Scoring and the Suspension Policy

Each substitute carries an append-only `reliability_events` log; every entry records an `event_type`, a signed integer `delta`, an `occurred_at` instant stamped from the logical clock, and, where the event stems from an assignment, that assignment's `id`. Six event types exist with pinned deltas: `COMPLETION` at +1, `SUB_CANCEL_EARLY` at −5, `SUB_CANCEL_LATE` at −15, `NO_SHOW` at −25, `FLAG_MINOR` at −3, and `FLAG_MAJOR` at −10. Declining an offer, letting it expire, and every system-initiated cancellation produce no event at all.

Two scores are computed from this log. The `reliability_lifetime_score` starts from a baseline of 100, adds the deltas of every event ever recorded, and is clamped to the inclusive range 0 through 100; it is the score displayed on the substitute's profile, and old events never age out of it. The `reliability_trailing_score` applies the identical baseline, summation, and clamp, but counts only events whose `occurred_at` falls within the trailing window — by default the last 90 days, governed by the district's `reliability_window_days` — so an identical event log yields a different trailing score once events age past the window. The trailing variant, never the lifetime one, drives dispatch ranking and suspension evaluation. Two counters accompany the scores: `completions_lifetime`, the count of the substitute's assignments that have ever reached `VERIFIED`, and `completions_trailing`, the count of completion events inside the trailing window; a newly registered substitute starts with both scores at 100, both counters at 0, and an empty event log. Scores and counters are recomputed lazily whenever a substitute is read, ranked, or appended to, so a clock advance ages events out of the trailing window without any explicit write. In multi-district deployments the trailing window of the district behind the substitute's most recent event governs the recompute; with no events it is the single district's window when exactly one district exists, and the 90-day default otherwise.

Suspension evaluation runs after every reliability event append and every completion-counter change. An `ACTIVE` substitute is automatically suspended when — and only when — their trailing score is strictly below the district's `suspension_score_threshold` (60 by default) and their `completions_trailing` is at least the district's `suspension_min_completions` (5 by default). The boundary is strict: a trailing score exactly equal to the threshold does not suspend. The suspension cascade itself is specified in §3.2.

### 2.11. Dispatch Eligibility, Ranking, and the No-Re-Offer Rule

One selector policy governs every path by which an offer is created — batch pick-up, re-dispatch after a decline, expiry, or cancellation, and the manual-offer preview. A substitute is eligible for an absence only when all of the following hold: the substitute's `status` is `ACTIVE`; a Qualification exists matching the absence's `required_subject` and `required_grade_band`; both required clearances — `BACKGROUND_CHECK` and `TEACHING_CREDENTIAL` — are `VERIFIED` with `expires_on` on or after the absence's `end_date`; no `ACTIVE` `DO_NOT_RETURN` mark exists for the absence's school and this substitute; the substitute holds no `ACCEPTED`, `WORKED`, or `VERIFIED` assignment whose date range intersects the absence's range; no live (`OFFERED` or `ACCEPTED`) assignment already exists for this absence and substitute; and no `DECLINED` or `EXPIRED` assignment exists for this absence and substitute — a substitute who declined or timed out is never re-offered the same absence.

Among eligible candidates, each is scored: the rank score is the substitute's `reliability_trailing_score` plus a flat boost — the district's `preference_rank_boost`, 10 points by default — when the substitute holds an `ACTIVE` `PREFERRED` mark at the absence's school. The boost is flat; a mark's optional `priority_rank` is an ordering hint recorded for coordinators and plays no part in the ranking formula. Candidates are ordered by rank score descending, ties broken by earliest substitute registration (the substitute's `created_at`, ascending). If the eligible pool is empty, no offer is created and the absence simply remains `DISPATCHING`; the cutoff sweep of §3.4 may later mark it `UNFILLED`.

## 3. Business Logic & Workflows

### 3.1. District Configuration and School Setup

Everything in the system is scoped, directly or transitively, to a **District**, whose pay-rule configuration the `DistrictAdmin` authors at creation and may later tune. Creating a district requires only a `name`; every other configuration field is optional and inherits a system default when omitted. The defaults deserve attention because they silently govern every downstream calculation: an offer stays live for `offer_response_window_minutes`, two hours (120 minutes) by default, before auto-expiry; an absence whose length is strictly greater than `long_term_approval_days` (5 days by default) requires district approval; an approved-workday streak at or beyond `long_term_threshold_days` (10 by default) converts to the long-term rate, which is `long_term_rate_multiplier` — 1.15, or 115% of the substitute's base rate — applied per converted day.

Incentives are configured the same way. Schools carry a `hard_to_fill_tier` of `NONE`, `MODERATE`, or `HIGH`, and the district prices each tier through `htf_high_premium_pct` (a 20% premium, 0.20, by default) and `htf_moderate_premium_pct` (10%, 0.10, by default). Notice-based premiums key off lead time: an offer created with strictly less than `short_notice_hours` of lead (24 hours by default) earns `short_notice_premium_pct` (25%, 0.25, by default), while lead time at or above the short threshold but strictly below `moderate_notice_hours` (72 hours by default) earns `moderate_notice_premium_pct` (10%, 0.10, by default). All premiums combined are hard-capped by `premium_cap_multiplier` — 1.50 by default, meaning pay never exceeds 150% of base no matter how many incentives stack. The remaining knobs — `preference_rank_boost` (10), `reliability_window_days` (90), `suspension_score_threshold` (60), `suspension_min_completions` (5), `period_comp_rate_cents` (2,500 cents, i.e. $25.00, per covered period), `daily_period_cap` (8), and `weekly_period_cap` (10) — take their defaults the same way and are interpreted in §2.10, §2.11, and §3.6. A district is born at `version` 1; reconfiguration is an optimistic-concurrency-guarded update per §2.7, where any subset of these fields plus `name` may change and the district's `version` increments by one.

Schools are created inside a district by a `DistrictAdmin`, supplying the owning `district_id`, a `name`, the `coverage_budget_total_cents` allocation, and optionally a `hard_to_fill_tier` that defaults to `NONE`; both budget accumulators start at zero per §2.9. Staff members are then enrolled against a school with `school_id`, `full_name`, primary teaching `subject`, and a `grade_band` of `ELEMENTARY`, `MIDDLE`, or `HIGH`; the `is_coordinator` flag, defaulting to false, is what elevates a staff record into the `SchoolCoordinator` identity of §2.1, so a write bearing a coordinator role whose staff record lacks the flag or belongs to another school fails ownership. Both roles may create staff records — the district admin anywhere, a coordinator within their own school. Schools of a district and staff of a school are listable with the standard `limit` and `offset` parameters.

### 3.2. Onboarding and Managing the Substitute Pool

A `DistrictAdmin` registers a substitute with a `full_name` and a `base_daily_rate_cents` — the daily pay before any premium. The new record starts in `PENDING_CLEARANCE` status with the pristine reliability profile of §2.10, and the substitute pool is listable with an optional `status` filter alongside pagination.

Two credential instruments gate a substitute's working life. A **Qualification** records that a substitute may teach a `subject` within a `grade_band`; it is granted against a `substitute_id`, and granting the same subject-and-band twice is refused with `ERR_DUPLICATE_QUALIFICATION`. A **Clearance** records a compliance artifact of one `clearance_type` — `BACKGROUND_CHECK`, `TEACHING_CREDENTIAL`, or `TB_TEST` — valid through an inclusive `expires_on` date, and starts `PENDING`. A district admin verifies a pending clearance; verification of a clearance in any other status fails with `ERR_CLEARANCE_INVALID_STATE`, and verification of one whose `expires_on` has already passed fails with `ERR_CLEARANCE_INVALID`. Of the three types, `BACKGROUND_CHECK` and `TEACHING_CREDENTIAL` are the *required* pair that activation, dispatch eligibility, and acceptance all demand.

Clearance expiry is clock-driven. When the logical clock's date passes a clearance's `expires_on`, the clearance flips `PENDING` or `VERIFIED` to `EXPIRED`. The flip is applied eagerly at dispatch batches, at substitute activation, and at any validation that reads the clearance, and lazily when a substitute's clearances are listed. Consequences depend on where the expiry is detected: when detection happens at a dispatch batch or at activation, the clearance is a required one, and the substitute is `ACTIVE`, the substitute is suspended with the full cascade below; detection at any other validation flips the clearance's status only.

Activation moves a substitute from `PENDING_CLEARANCE` — or, after discipline, from `SUSPENDED` — to `ACTIVE`, and is a `DistrictAdmin` prerogative. Attempting it from `ACTIVE` is rejected with `ERR_SUBSTITUTE_INVALID_STATE`; attempting it without both required clearances `VERIFIED` and valid through the current clock date is rejected with `ERR_CLEARANCE_INVALID`. Suspension runs in reverse: a manual suspend of an `ACTIVE` substitute, optionally annotated with a `reason` (accepted at the endpoint but not persisted on the substitute record), or the automatic triggers of §2.10 (a trailing score strictly below threshold with enough trailing completions, or a required clearance gone `EXPIRED`). Either way the cascade is total: every `OFFERED` assignment of the substitute is cancelled with `cancel_reason` `SUSPENSION_CANCEL` and its absence, already `DISPATCHING`, simply stays there without a live offer — cancelling an offer never re-runs the selector, so the absence waits for a later batch's cutoff sweep and re-pick-up; every `ACCEPTED` assignment is cancelled the same way and its absence falls back from `ASSIGNED` to `DISPATCHING` and re-dispatches. System cancellations carry no reliability penalty — the score drop that triggered the suspension is penalty enough.

### 3.3. Reporting, Approving, and Editing Absences

An absence enters the system when a `Teacher` reports their own time away, or when a `SchoolCoordinator` or `DistrictAdmin` files on a staff member's behalf. The report names the `staff_member_id` (which for a teacher must equal their `X-User-ID`), the `start_date` and inclusive `end_date`, an `absence_type` of `SICK`, `PERSONAL`, `PROFESSIONAL_DEVELOPMENT`, or `JURY_DUTY`, and the coverage requirement: a `required_subject` and `required_grade_band` the substitute must be qualified for. The absence's `school_id` is denormalized from the staff member's record at creation and never drifts. The system then computes `total_days` — the count of Monday-through-Friday dates inside the inclusive range, weekends never counting — and stamps `fill_status` `REPORTED`.

Date discipline applies at the gate: `end_date` before `start_date`, a `start_date` before the current clock date, or a range containing not a single weekday all fail with `ERR_INVALID_DATE_RANGE`. One teacher may not hold two non-cancelled absences whose date ranges intersect — adjacent ranges are permitted — and a collision fails with `ERR_ABSENCE_DATE_OVERLAP`. Absences are listable with `school_id`, `staff_member_id`, `fill_status`, `from_date`, and `to_date` filters; `from_date` and `to_date` bound the absence's `start_date` inclusively, and a malformed filter date fails with `ERR_INVALID_DATE_RANGE`.

Long absences need district blessing, tracked on a second, parallel state machine: `approval_status`. At creation it computes to `NOT_REQUIRED` when `total_days` is at most the district's `long_term_approval_days`, and to `PENDING` when strictly greater; while it is `PENDING` — or has been `REJECTED` — dispatch batches, manual offers, and self-claims are all blocked, surfacing `ERR_ABSENCE_INVALID_STATE`. A `DistrictAdmin` reviews with a `decision` of `APPROVE` or `REJECT`. Approval moves `approval_status` to `APPROVED` and is permitted from `PENDING` or `NOT_REQUIRED` (approving an already-`APPROVED` or `REJECTED` absence fails with `ERR_ABSENCE_INVALID_STATE`), provided the absence is not `CANCELLED` or `CLOSED`. Rejection is permitted only from `approval_status` `PENDING` or `NOT_REQUIRED` (rejecting an `APPROVED` or already-`REJECTED` absence fails with `ERR_ABSENCE_INVALID_STATE`) and while `fill_status` is `REPORTED`, `DISPATCHING`, or `UNFILLED` — anything further along fails with `ERR_ABSENCE_INVALID_STATE` — and it bites: outstanding `OFFERED` assignments are cancelled with `cancel_reason` `ABSENCE_CANCEL` (no reliability penalty), and a `DISPATCHING` or `UNFILLED` absence falls back to `REPORTED`.

While an absence remains unassigned, a coordinator or district admin may edit its `start_date`, `end_date`, `required_subject`, or `required_grade_band` under the `expected_absence_version` guard of §2.7; editing an absence that has reached assignment or beyond is refused with `ERR_ABSENCE_INVALID_STATE`. A successful edit increments the absence's `version` by one, recomputes `total_days`, and re-runs the approval computation — which cuts both ways: stretching an `APPROVED`, `NOT_REQUIRED`, or even `REJECTED` absence past the approval threshold drops it back to `PENDING`, where it must be re-approved before any further dispatch, offer, or claim; shrinking a `PENDING` absence to within the threshold restores `NOT_REQUIRED`. Overlap and date-sanity rules re-apply on every edit — with one exception: the not-before-the-current-date rule gates only the initial report, so an edit may move the range into the past as long as `end_date` does not precede `start_date` and the range still contains a weekday.

Cancellation closes the loop for plans that change. A teacher may cancel their own absence, and a coordinator or district admin any absence, while its `fill_status` is `REPORTED`, `DISPATCHING`, `UNFILLED`, or `COVERED_INTERNALLY`; from `ASSIGNED`, `COMPLETED`, `CLOSED`, or an existing `CANCELLED` the attempt fails with `ERR_ABSENCE_INVALID_STATE` — an accepted assignment must first be released at the assignment level. Cancelling cascades: `OFFERED` assignments on the absence are cancelled with `cancel_reason` `ABSENCE_CANCEL` and no reliability penalty, and `PROPOSED` or `APPROVED` internal coverages are cancelled with the day counters recomputed per §3.6.

### 3.4. Callout Batches, Offers, and Self-Claim

Auto-callout is driven by dispatch batches, a `DistrictAdmin` operation naming the `district_id` and optionally a `run_for_date` the batch should treat as "today" — when `run_for_date` is omitted, the current logical clock date is used. A batch does four things in one run and records its own audit trail: `executed_at` stamped from the logical clock, the supplied `run_for_date` (null when omitted), plus counters `absences_considered`, `offers_created`, `offers_expired`, and `absences_marked_unfilled`. First, every offer whose `offer_expires_at` has been reached flips from `OFFERED` to `EXPIRED`, triggering the same re-dispatch cascade as a decline. Second, pick-up: eligible `REPORTED` and `UNFILLED` absences — approval clear of `PENDING`/`REJECTED`, `end_date` not before the current clock date (the pick-up guard reads the clock, not `run_for_date`), and zero internal-coverage days — move to `DISPATCHING`, and the selector of §2.11 runs for each, creating at most one offer per absence per batch. Third, the cutoff sweep: a `DISPATCHING` absence whose `start_date` is on or before the batch run date, with no assignment currently in `ACCEPTED`, `WORKED`, or `VERIFIED` status and no live `OFFERED` assignment remaining, is marked `UNFILLED` — running pick-up before the sweep means an absence just picked up into an empty pool is marked `UNFILLED` in the same run. Fourth, the same sweep applies clearance expiry with its suspension cascade. `absences_considered` counts the district's absences the run scanned while they stood in `REPORTED`, `UNFILLED`, or `DISPATCHING`.

An offer is an **Assignment** born in `OFFERED` status. Its `offer_source` records the channel — `AUTO_DISPATCH` from a batch, `MANUAL_OFFER` from a coordinator or district admin naming an `absence_id` and `substitute_id`, or `SELF_CLAIM` from a substitute — and its `offer_sequence` is a per-absence monotonically increasing number starting at 1, so the audit trail of who was asked first is never lost. Creation snapshots everything the pay rules will need later: `offered_at` from the logical clock; `offer_expires_at` exactly `offer_response_window_minutes` after; `start_date` snapshotted from the absence; `end_date` as the currently covered end, which moves if the absence is later extended; `scheduled_days` as the weekday count across that range; `school_id` denormalized from the absence; and the premium machinery below. A manual offer runs the identical eligibility filter as the selector — a coordinator cannot hand a job to a suspended, unqualified, uncleared, barred, double-booked, or already-asked substitute — and a first manual offer moves the absence from `REPORTED` or `UNFILLED` into `DISPATCHING`. The absence side is gated too: it must stand in `REPORTED`, `DISPATCHING`, or `UNFILLED` with approval clear of `PENDING`/`REJECTED`, an `end_date` not before the current clock date, and zero internal-coverage days, any violation surfacing `ERR_ABSENCE_INVALID_STATE`; and naming a substitute who already holds a live (`OFFERED`/`ACCEPTED`) or spent (`DECLINED`/`EXPIRED`) assignment for the absence fails with `ERR_ASSIGNMENT_INVALID_STATE`.

The premium frozen into `premium_multiplier_snapshot` rewards the fills districts struggle with. Lead time is measured from the clock's current instant to midnight UTC of the absence's first day and may be negative for same-day callouts. The hard-to-fill component is the district's high-tier fraction for a `HIGH` school, the moderate-tier fraction for a `MODERATE` school, and zero for `NONE`. The notice component is the short-notice fraction when lead time is strictly below `short_notice_hours`, else the moderate-notice fraction when strictly below `moderate_notice_hours`, else zero — so an offer created exactly 24 hours out earns the moderate tier, and exactly 72 hours out earns none. The snapshot multiplier is one plus the two components, capped at `premium_cap_multiplier`; with defaults, a `HIGH` school posting three hours before the first day prices at 1.45 — 1.00 plus 0.20 plus 0.25 — under the 1.50 ceiling. From the snapshot comes `provisional_pay_cents`: the substitute's `base_daily_rate_cents` is scaled by the snapshot multiplier and that scaled per-day figure is rounded half up to integer cents — a single rounding at offer time — then multiplied by `scheduled_days`; this is the §2.6 per-day-first order, contrasted with the final payout in §3.5, where each approved day is priced and rounded individually before summation.

The owning substitute answers an offer with a `decision` of `ACCEPT` or `DECLINE`. Acceptance is gated in pipeline order: the offer must still be `OFFERED` — and if the clock has reached `offer_expires_at`, the offer auto-flips to `EXPIRED` first (re-running the selector exactly as a batch expiry does), so the late answer fails with `ERR_ASSIGNMENT_INVALID_STATE`; the absence must be `DISPATCHING` and its approval `NOT_REQUIRED` or `APPROVED` (`ERR_ABSENCE_INVALID_STATE`); the substitute `ACTIVE` (`ERR_SUBSTITUTE_INVALID_STATE`); no active do-not-return mark (`ERR_SUBSTITUTE_DO_NOT_RETURN`); both required clearances valid through the absence's `end_date` (`ERR_CLEARANCE_INVALID`); the qualification present (`ERR_QUALIFICATION_MISMATCH`); no overlap with the substitute's other `ACCEPTED`, `WORKED`, or `VERIFIED` assignments, adjacent ranges permitted (`ERR_ASSIGNMENT_DATE_OVERLAP`); and finally the school's `coverage_budget_available_cents` must cover the `provisional_pay_cents` (`ERR_COVERAGE_BUDGET_INSUFFICIENT`). A successful accept moves the offer to `ACCEPTED`, the absence from `DISPATCHING` to `ASSIGNED`, cancels every other `OFFERED` assignment on that absence with `cancel_reason` `ABSENCE_CANCEL` (no penalty — they simply lost the race), and adds the provisional pay into the school's committed budget. A decline flips the offer to `DECLINED` and immediately re-runs the selector: the next candidate receives a fresh offer with an incremented `offer_sequence`, and if the pool is empty the absence simply stays `DISPATCHING`. Neither declining nor expiring writes a reliability event. Offers are flipped to `EXPIRED` only by batches, forward clock jumps, and answer attempts — a plain read of an assignment never expires it.

A substitute need not wait to be asked. Self-claim targets any open absence: the claim must carry `expected_absence_version` per §2.7, and the full acceptance gauntlet applies — the absence `DISPATCHING` with approval clear, the substitute eligible, the budget sufficient — with one distinction: success is atomic, creating the assignment already `ACCEPTED` with `offer_source` `SELF_CLAIM`, moving the absence to `ASSIGNED`, committing the budget, and incrementing the absence's `version` by one. A substitute who was already asked about the absence — holding a live (`OFFERED`/`ACCEPTED`) or spent (`DECLINED`/`EXPIRED`) assignment for it — is rejected with `ERR_ASSIGNMENT_INVALID_STATE`. The claimed assignment is stamped with the same offer-time fields — snapshot, provisional pay, scheduled days — as any dispatched offer before it lands in `ACCEPTED`.

### 3.5. Working the Assignment: Outcomes, Timesheets, Verification, and Extension

Cancellations happen, and who cancels determines the consequences. A substitute may cancel their own `OFFERED` or `ACCEPTED` assignment, and a coordinator or district admin any such assignment; attempting it from any other status fails with `ERR_ASSIGNMENT_INVALID_STATE`. The `cancel_reason` is pinned by the actor: `SUB_CANCEL` for a substitute's self-cancel, `COORDINATOR_CANCEL` for a coordinator or admin, and `DNR_CANCEL`, `SUSPENSION_CANCEL`, or `ABSENCE_CANCEL` for the system cascades — system cancels never write reliability events. Cancelling a mere `OFFERED` assignment touches no budget and does not re-run the selector — the absence simply remains `DISPATCHING` without a live offer until a later batch's cutoff sweep and re-pick-up. Cancelling an `ACCEPTED` one releases the full `provisional_pay_cents` from the school's committed budget, reopens the absence from `ASSIGNED` back to `DISPATCHING`, and re-runs the selector — excluding the departing substitute when the cause was `DNR_CANCEL`. A substitute's self-cancel of an accepted assignment also writes a reliability event: `SUB_CANCEL_LATE` (−15) when the cancellation lands before the absence's first day with strictly less than the district's short-notice lead remaining, otherwise `SUB_CANCEL_EARLY` (−5); either append triggers the suspension evaluation of §2.10.

Once the day arrives, the coordinator (or district admin) reports the outcome by supplying an `outcome` of `WORKED` or `NO_SHOW`. Marking an `ACCEPTED` assignment as worked — permitted only once the clock date has reached the assignment's `start_date`, a premature report failing with `ERR_ASSIGNMENT_INVALID_STATE`, as does reporting on any non-`ACCEPTED` assignment — moves it to `WORKED`. Reporting `NO_SHOW` instead is the harshest event in the system: the provisional reserve is released from the school's committed budget, a `NO_SHOW` reliability event (−25) is appended and suspension evaluation runs, a PerformanceFlag of `flag_type` `NO_SHOW`, `severity` `MAJOR`, status `OPEN`, and `auto_created` true is created against the substitute at that school with its `assignment_id` pointing at the no-show assignment, and the absence falls back from `ASSIGNED` to `DISPATCHING` and re-dispatches to the next eligible candidate.

Pay for worked days is evidenced by timesheets. The substitute submits one per worked date, naming the `assignment_id`, the `work_date`, and `hours_worked` between 0.5 and 12.0 in half-hour steps (violations are `ERR_INVALID_REQUEST`); the submission is only accepted while the assignment is `WORKED` (else `ERR_ASSIGNMENT_INVALID_STATE`), the date must be a weekday inside the assignment's range (`ERR_INVALID_DATE_RANGE`, with the dedicated `ERR_TIMESHEET_OUT_OF_RANGE` guarding the range rule), and a second sheet for the same assignment and date is refused with `ERR_DUPLICATE_TIMESHEET`. The sheet's `substitute_id` is denormalized from its assignment, and it starts `SUBMITTED`. The coordinator reviews with a `decision` of `APPROVE` or `REJECT`: approving requires the sheet `SUBMITTED` (else `ERR_TIMESHEET_INVALID_STATE`) and its assignment still `WORKED` (else `ERR_ASSIGNMENT_INVALID_STATE`); rejecting under the same guards moves it to `REJECTED`, from which the substitute may resubmit corrected `hours_worked`, returning it to `SUBMITTED` — resubmission from any other status fails with `ERR_TIMESHEET_INVALID_STATE`.

Approval is where the long-term machinery turns. On each approval the system runs a full chronological recompute over the assignment's `APPROVED` timesheets, sorted by `work_date` ascending — dates are unique, so no tie-breaking exists. The `streak_index` of the earliest approved date is 1; each subsequent approved date increments it when the date is the next district workday after the previous one — weekend gaps do not break a streak — while any weekday gap (a skipped Monday-through-Friday date with no approved timesheet between two approved dates) resets the index to 1. Each approved date's `day_pay_cents` is then fixed: when its `streak_index` has reached the district's `long_term_threshold_days`, the day pays the substitute's `base_daily_rate_cents` scaled by `long_term_rate_multiplier`; otherwise it pays the base scaled by the offer's `premium_multiplier_snapshot` — each day's amount rounded half up to integer cents individually, before any summation. The assignment's `worked_days_count` refreshes to the number of its approved sheets, and `long_term_converted` flips true once any approved sheet's `streak_index` has reached the threshold.

Verification seals the assignment. A coordinator or district admin verifies a `WORKED` assignment — any other status, or the existence of any still-`SUBMITTED` timesheet, fails with `ERR_ASSIGNMENT_INVALID_STATE`, forcing review to finish first. Verification computes `final_payout_cents` as the sum of the per-day `day_pay_cents` over approved sheets — per-day-then-sum is authoritative precisely because summing first and rounding once would price long-term days differently — appends the `COMPLETION` (+1) reliability event, increments the completion counters, runs suspension evaluation, moves the absence from `ASSIGNED` to `COMPLETED` with `days_covered_sub` set to the assignment's `worked_days_count`, and recomputes `days_uncovered`. The provisional figure is thereby replaced: where `provisional_pay_cents` was a scheduled-day estimate at premium rates, the final payout reflects actually approved days with streak-based long-term conversion.

Absences sometimes grow mid-assignment. A coordinator or district admin may extend an `ACCEPTED` or `WORKED` assignment by supplying a `new_end_date`; extending a terminal assignment fails with `ERR_ASSIGNMENT_INVALID_STATE`, a malformed new range with `ERR_INVALID_DATE_RANGE`, and an extension that would collide with the substitute's other committed assignments with `ERR_ASSIGNMENT_DATE_OVERLAP`. The extension moves both the assignment's and the absence's `end_date`, recomputes `total_days` and `scheduled_days`, recomputes `provisional_pay_cents` from the new schedule, and adjusts the school's committed budget by the delta. The long-term rule applies with teeth: if the extension pushes `total_days` strictly past `long_term_approval_days` and the absence's `approval_status` is not `APPROVED`, the extension is refused outright with `ERR_LONG_TERM_APPROVAL_REQUIRED` — get district approval first, extend second. Assignments are listable with `absence_id`, `substitute_id`, `school_id`, and `status` filters.

### 3.6. Internal Coverage of Unfilled Absences

When the market fails, the building covers itself. A coordinator or district admin proposes internal coverage of one absence date by a staff member, naming the `absence_id`, `staff_member_id`, the `coverage_date`, and the number of `periods` — the covering staff member is not required to belong to the absence's school; the absence must be `DISPATCHING`, `UNFILLED`, or `COVERED_INTERNALLY` (else `ERR_ABSENCE_INVALID_STATE`), the date a weekday inside the absence's range (else `ERR_INVALID_DATE_RANGE`), and `periods` at least 1 (else `ERR_INVALID_REQUEST`). The proposal starts `PROPOSED`, its `school_id` denormalized from the absence, and capacity is validated immediately and re-validated at approval: for the covering staff member, the sum of `periods` across their coverages in `PROPOSED`, `APPROVED`, `WORKED`, or `COMPENSATED` on the same calendar date may not exceed the district's `daily_period_cap` (8 by default), and the same sum across the ISO week (Monday through Sunday) containing that date may not exceed the `weekly_period_cap` (10 by default); a breach is `ERR_COVERAGE_CAPACITY_EXCEEDED`.

A `DistrictAdmin` reviews each proposal with a `decision` of `APPROVE` or `REJECT`. Approval requires the coverage still `PROPOSED` (else `ERR_COVERAGE_INVALID_STATE`), the absence `UNFILLED` or `COVERED_INTERNALLY` (else `ERR_ABSENCE_INVALID_STATE`), and a fresh pass of the capacity check; on success the absence's `days_covered_internal` is recomputed, and the first approved coverage moves the absence from `UNFILLED` to `COVERED_INTERNALLY`. Rejection simply moves the proposal to `REJECTED`. After the day passes, the coordinator confirms the coverage was worked — the coverage must be `APPROVED` and the clock date must have reached the `coverage_date`, both failing as `ERR_COVERAGE_INVALID_STATE` — at which point `compensation_cents` is fixed as `periods` times the district's `period_comp_rate_cents`, the rate read and snapshotted at confirmation time so later district reconfiguration never rewrites history. Coverages may be cancelled by coordinator, admin, or the absence-cancellation cascade while `PROPOSED` or `APPROVED` (else `ERR_COVERAGE_INVALID_STATE`); cancelling an `APPROVED` one decrements the absence's internal-day count, and when that count reaches zero the absence falls back from `COVERED_INTERNALLY` to `UNFILLED`, eligible for dispatch again.

Three day counters keep every absence's arithmetic honest. `days_covered_internal` counts the distinct coverage dates whose coverage stands in `APPROVED`, `WORKED`, or `COMPENSATED`; `days_covered_sub` is the verified assignment's `worked_days_count`, or zero while no assignment has reached `VERIFIED`; and `days_uncovered` is whatever remains. The conservation invariant holds at all times: internal days plus substitute days plus uncovered days exactly equal `total_days`. Coverages are listable per absence or per staff member.

### 3.7. Payroll Periods and the Export Waterfall

Payroll runs district by district. A `PayrollClerk` opens a period with `district_id`, `period_start`, and an inclusive `period_end` that must not precede the start (else `ERR_INVALID_DATE_RANGE`); the period is born `OPEN`, its totals — `total_payout_cents`, `assignments_paid_count`, `coverages_compensated_count`, and `exported_at` — all unset until export. Periods are listable with an optional `district_id` filter, and the timesheets a period exported are listable under it.

Export is the system of record's heaviest transaction, and it refuses to run dirty. The period must be `OPEN`; there must be no `SUBMITTED` timesheet attached to any assignment whose absence belongs to the district; and there must be no assignment still `ACCEPTED` or `WORKED` whose absence's `end_date` falls inside the period window — all three violations surface as `ERR_PAYROLL_PERIOD_INVALID_STATE`, the latter two because export would otherwise strand unreviewed work mid-period.

A clean export runs the waterfall. In scope are the district's `VERIFIED` assignments whose absence's `end_date` falls within the period, processed strictly in order of assignment `created_at` ascending — the pinned tie-break, never `id` — with assignments sharing an identical `created_at` (common under the logical clock) processed in creation order, because each assignment's charge depends on the budget left by those before it. For each, in order: the school's committed budget releases the assignment's full `provisional_pay_cents` reserve; the charge is the assignment's `final_payout_cents` clamped to the school's available budget after that release; the charged amount is added to the school's spent budget; the assignment's `final_payout_cents` itself is left unchanged at its uncapped value while `payout_capped` records whether the charge fell short; and the assignment moves to `PAID`, its `APPROVED` timesheets flipping to `EXPORTED` with `payroll_period_id` set to this period. Then the district's `WORKED` coverages with `coverage_date` inside the period, likewise in `created_at` order, are compensated: each `compensation_cents` is added to school spent — compensation is never capped, capping being a substitute-pay artifact — and the coverage moves to `COMPENSATED`. Every `COMPLETED` absence whose assignment was just paid closes to `CLOSED`. The period records `total_payout_cents` as the sum of charged assignment payouts plus compensation, `assignments_paid_count` and `coverages_compensated_count` as their names promise, and `exported_at` from the logical clock, ending `EXPORTED`.

### 3.8. Performance Flags, School Marks, and Fill-Rate Analytics

The pool polices itself through two instruments. A **PerformanceFlag** is raised by a coordinator (of the school concerned) or district admin against a substitute, naming `substitute_id`, the `school_id` raising it, a `flag_type` of `NO_SHOW`, `CONDUCT`, `QUALITY`, or `TARDINESS`, a `severity` of `MINOR` or `MAJOR`, and optionally the `assignment_id` it relates to. The flag opens `OPEN` with `auto_created` false — only the no-show cascade of §3.5 sets that true — and, significantly, raising one immediately appends the matching reliability event, `FLAG_MINOR` (−3) or `FLAG_MAJOR` (−10), and runs suspension evaluation: flags move scores before any human review. A `DistrictAdmin` later reviews with a `decision` of `RESOLVE` or `ESCALATE` — either way the flag must be `OPEN`, else `ERR_PERFORMANCE_FLAG_INVALID_STATE`. Resolution simply closes it `RESOLVED`. Escalation closes it `ESCALATED` and converts it into exclusion: an `ACTIVE` do-not-return mark is created for that school and substitute with `source_flag_id` pointing back at the flag and a null `reason` — unless one already exists — and the full do-not-return cascade runs.

A **SchoolSubstituteMark** is the direct instrument: a coordinator or district admin marks a substitute `PREFERRED` or `DO_NOT_RETURN` at a school, supplying `school_id`, `substitute_id`, and `mark_type`, with `priority_rank` as an optional ordering hint on preferred marks and `reason` mandatory whenever the mark is `DO_NOT_RETURN` (a missing `reason` fails request-shape validation with `ERR_INVALID_REQUEST`). Marks open `ACTIVE`, with `source_flag_id` null for manually created ones, and one `ACTIVE` mark per school, substitute, and mark type is the ceiling — a duplicate is refused with `ERR_DUPLICATE_MARK`. Creating a `DO_NOT_RETURN` mark fires immediately: the substitute's future-dated `OFFERED` and `ACCEPTED` assignments at that school — those whose `end_date` is on or after the clock date — are cancelled with `cancel_reason` `DNR_CANCEL` and no reliability penalty, and each cancelled accepted assignment's absence reopens from `ASSIGNED` to `DISPATCHING` and re-runs the selector, from which the marked substitute is now excluded by §2.11. Either a coordinator or an admin may lift an `ACTIVE` mark — lifting any other status fails with `ERR_MARK_INVALID_STATE` — restoring the substitute's eligibility at that school, since the selector and the do-not-return screen both ignore `LIFTED` marks. Marks are listable per school or per substitute, with `mark_type` and `status` filters; flags are listable per substitute or per school.

Finally, the district reads its own report card through fill-rate analytics, available to every role given a `from_date`, a `to_date`, and an optional `school_id` filter — a missing or malformed `from_date` or `to_date` fails with `ERR_INVALID_REQUEST`. The endpoint is not paginated: its response `data` is an object carrying a `rows` array, ordered by `school_id` and then `day_of_week`. The population is absences whose `start_date` falls in the range, grouped by school and by the ISO day-of-week of the start date (1 for Monday through 7 for Sunday). Two variants are always returned side by side. The default `SUB_ONLY` variant counts an absence as filled if it ever reached `ASSIGNED` — that is, its `fill_status` stands at `ASSIGNED`, `COMPLETED`, or `CLOSED`. The `ANY_COVERAGE` variant widens filled to also include absences standing at `COVERED_INTERNALLY`. Each returned row carries `school_id`, `day_of_week`, `reported_count`, `sub_only_filled_count`, `sub_only_fill_rate`, `any_coverage_filled_count`, and `any_coverage_fill_rate`; a row exists for every school-and-weekday group containing at least one absence in range, cancelled ones included in the grouping, though `reported_count` and both denominators count only non-`CANCELLED` absences. A rate is the filled count divided by that denominator, rounded to four decimal places round half up — and when a group's denominator is zero, its rate is null rather than zero, and never an error.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger an action on it return `200 OK`, as do all reads. The complete endpoint surface is:

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/districts` | Create a district with pay-rule configuration (defaults applied for omitted config fields) | DistrictAdmin |
| GET | `/districts/{id}` | Get a district | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| PUT | `/districts/{id}` | Update district pay-rule configuration; OCC-guarded | DistrictAdmin |
| POST | `/schools` | Create a school | DistrictAdmin |
| GET | `/schools/{id}` | Get a school | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/districts/{id}/schools` | List schools of a district | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/staff-members` | Create a staff member | DistrictAdmin, SchoolCoordinator |
| GET | `/staff-members/{id}` | Get a staff member | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/schools/{id}/staff-members` | List staff members of a school | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/substitutes` | Register a substitute (starts PENDING_CLEARANCE) | DistrictAdmin |
| GET | `/substitutes/{id}` | Get a substitute | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/substitutes` | List substitutes with optional status filter | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/substitutes/{id}/activate` | Activate from PENDING_CLEARANCE or SUSPENDED; requires valid required clearances | DistrictAdmin |
| POST | `/substitutes/{id}/suspend` | Manually suspend an ACTIVE substitute | DistrictAdmin |
| POST | `/qualifications` | Grant a qualification to a substitute | DistrictAdmin |
| GET | `/substitutes/{id}/qualifications` | List qualifications of a substitute | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/clearances` | Register a clearance record (starts PENDING) | DistrictAdmin |
| POST | `/clearances/{id}/verify` | Verify a pending clearance | DistrictAdmin |
| GET | `/substitutes/{id}/clearances` | List clearances of a substitute (expiry applied lazily on read) | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/marks` | Create a PREFERRED or DO_NOT_RETURN mark; DO_NOT_RETURN creation triggers the DNR cascade | SchoolCoordinator, DistrictAdmin |
| POST | `/marks/{id}/lift` | Lift an ACTIVE mark | SchoolCoordinator, DistrictAdmin |
| GET | `/schools/{id}/marks` | List marks issued by a school | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/substitutes/{id}/marks` | List marks targeting a substitute | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/absences` | Report an absence | Teacher, SchoolCoordinator, DistrictAdmin |
| GET | `/absences/{id}` | Get an absence | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/absences` | List absences with filters | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| PUT | `/absences/{id}` | Edit an absence's dates/requirements while unassigned; OCC-guarded | SchoolCoordinator, DistrictAdmin |
| POST | `/absences/{id}/cancel` | Cancel an unassigned absence | Teacher, SchoolCoordinator, DistrictAdmin |
| POST | `/absences/{id}/review` | District decision on a long-term absence | DistrictAdmin |
| POST | `/absences/{id}/claim` | Substitute self-claims an open absence; creates an ACCEPTED assignment atomically; OCC-guarded | Substitute |
| POST | `/dispatch-batches` | Run an auto-callout batch: expire stale offers, mark cutoff-passed absences UNFILLED, create offers for eligible open absences (one offer per absence per batch) | DistrictAdmin |
| GET | `/dispatch-batches/{id}` | Get a dispatch batch | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/districts/{id}/dispatch-batches` | List dispatch batches of a district | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/assignments` | Manual offer of an absence to a specific substitute (runs the same eligibility checks as the selector) | SchoolCoordinator, DistrictAdmin |
| GET | `/assignments/{id}` | Get an assignment | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/assignments` | List assignments with filters | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/assignments/{id}/respond` | Owning substitute accepts or declines an offer | Substitute |
| POST | `/assignments/{id}/cancel` | Cancel an OFFERED or ACCEPTED assignment | Substitute, SchoolCoordinator, DistrictAdmin |
| POST | `/assignments/{id}/report-outcome` | Coordinator reports the worked outcome of an accepted assignment | SchoolCoordinator, DistrictAdmin |
| POST | `/assignments/{id}/verify` | Verify a worked assignment; computes final payout | SchoolCoordinator, DistrictAdmin |
| POST | `/assignments/{id}/extend` | Extend the covered end date of an ACCEPTED or WORKED assignment (and its absence) | SchoolCoordinator, DistrictAdmin |
| POST | `/internal-coverages` | Propose internal coverage of one absence date | SchoolCoordinator, DistrictAdmin |
| GET | `/internal-coverages/{id}` | Get an internal coverage | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/absences/{id}/internal-coverages` | List coverages of an absence | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/staff-members/{id}/internal-coverages` | List coverages performed by a staff member | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/internal-coverages/{id}/review` | District approves or rejects a proposed coverage | DistrictAdmin |
| POST | `/internal-coverages/{id}/confirm-worked` | Confirm the coverage was worked; snapshots compensation | SchoolCoordinator, DistrictAdmin |
| POST | `/internal-coverages/{id}/cancel` | Cancel a PROPOSED or APPROVED coverage | SchoolCoordinator, DistrictAdmin |
| POST | `/timesheets` | Substitute submits a timesheet for one worked date | Substitute |
| GET | `/timesheets/{id}` | Get a timesheet | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/assignments/{id}/timesheets` | List timesheets of an assignment | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/payroll-periods/{id}/timesheets` | List timesheets exported in a payroll period | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/timesheets/{id}/review` | Coordinator approves or rejects a submitted timesheet | SchoolCoordinator, DistrictAdmin |
| PUT | `/timesheets/{id}` | Resubmit a rejected timesheet with corrected hours | Substitute |
| POST | `/payroll-periods` | Open a payroll period for a district | PayrollClerk |
| GET | `/payroll-periods/{id}` | Get a payroll period | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/payroll-periods` | List payroll periods, optionally filtered by district | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/payroll-periods/{id}/export` | Export the period: pays verified assignments, exports timesheets, compensates worked coverages | PayrollClerk |
| POST | `/performance-flags` | Raise a performance flag against a substitute; appends the reliability event immediately | SchoolCoordinator, DistrictAdmin |
| GET | `/substitutes/{id}/performance-flags` | List flags against a substitute | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| GET | `/schools/{id}/performance-flags` | List flags raised by a school | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/performance-flags/{id}/review` | District resolves or escalates a flag; escalation creates a DO_NOT_RETURN mark and triggers the DNR cascade | DistrictAdmin |
| GET | `/analytics/fill-rate` | Fill-rate analytics grouped by school and day-of-week; both SUB_ONLY and ANY_COVERAGE variants returned | DistrictAdmin, SchoolCoordinator, Teacher, Substitute, PayrollClerk |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO8601 UTC); startup default is exactly 2026-08-01T00:00:00Z; forward jumps apply lazy expiry | DistrictAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_DISTRICT_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOOL_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTITUTE_NOT_FOUND` | 404 Not Found |
| `ERR_ABSENCE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLEARANCE_NOT_FOUND` | 404 Not Found |
| `ERR_MARK_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_NOT_FOUND` | 404 Not Found |
| `ERR_TIMESHEET_NOT_FOUND` | 404 Not Found |
| `ERR_PAYROLL_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_PERFORMANCE_FLAG_NOT_FOUND` | 404 Not Found |
| `ERR_DISPATCH_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ABSENCE_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SUBSTITUTE_INVALID_STATE` | 409 Conflict |
| `ERR_CLEARANCE_INVALID_STATE` | 409 Conflict |
| `ERR_MARK_INVALID_STATE` | 409 Conflict |
| `ERR_COVERAGE_INVALID_STATE` | 409 Conflict |
| `ERR_TIMESHEET_INVALID_STATE` | 409 Conflict |
| `ERR_PAYROLL_PERIOD_INVALID_STATE` | 409 Conflict |
| `ERR_PERFORMANCE_FLAG_INVALID_STATE` | 409 Conflict |
| `ERR_SUBSTITUTE_DO_NOT_RETURN` | 409 Conflict |
| `ERR_CLEARANCE_INVALID` | 409 Conflict |
| `ERR_QUALIFICATION_MISMATCH` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_ABSENCE_DATE_OVERLAP` | 409 Conflict |
| `ERR_ASSIGNMENT_DATE_OVERLAP` | 409 Conflict |
| `ERR_COVERAGE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_MARK` | 409 Conflict |
| `ERR_DUPLICATE_QUALIFICATION` | 409 Conflict |
| `ERR_DUPLICATE_TIMESHEET` | 409 Conflict |
| `ERR_TIMESHEET_OUT_OF_RANGE` | 409 Conflict |
| `ERR_LONG_TERM_APPROVAL_REQUIRED` | 409 Conflict |
| `ERR_COVERAGE_BUDGET_INSUFFICIENT` | 402 Payment Required |
