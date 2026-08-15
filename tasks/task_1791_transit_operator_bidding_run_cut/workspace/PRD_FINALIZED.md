# Transit Operator Bidding & Run-Cut Assignment API — Product Requirements Document

## 1. Introduction

Four times a year, a transit agency's scheduling office runs the same high-stakes exercise: convert the service schedule into legal, payable pieces of operator work; let a unionized roster bid that work in strict seniority order; size an extra board deep enough to absorb the inevitable absences; and then stand behind every minute paid when timekeeping, overtime thresholds, and grievance procedures collide. Each step is governed by collective-bargaining work rules — spread limits, paid-break credits, daily and weekly overtime thresholds — and each award is defensible only if the pick sequence, the board rotation, and the overtime-equalization ledger can be reconstructed after the fact.

This document specifies the Transit Operator Bidding & Run-Cut Assignment API, the system of record for that exercise. It covers run-cut construction and work-rule compliance, the seniority bidding round and pick adjudication, extra-board sizing and absence coverage, overtime distribution and its grievance risk, vacation relief allocation, sign-up implementation, and pay validation — including the mid-pick service change that forces a partially awarded pick to restart on a revised run pool. All endpoints are mounted under `/api`.

Four constituencies hold sharply different powers here: the scheduling office drives the cut-post-pick-lock-implement pipeline; union operators bid, work, dispute, and grieve; payroll clerks close out work and finalize pay; and union representatives adjudicate grievances. Because several workflows depend on a client acting on a current view of a contested resource — the biddable run pool during a service change, the last uncovered absence on the board — every mutable resource is versioned, and optimistic concurrency is enforced at the two points where staleness does the most damage.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. Exactly four roles are recognized, spelled precisely as follows: `SchedulingOfficer`, `Operator`, `PayrollClerk`, and `UnionRep`. A request with a missing or unknown role header, or a missing user header, is rejected with `ERR_UNAUTHENTICATED`. An authenticated role attempting an operation outside its grant is rejected with `ERR_FORBIDDEN`.

Identity semantics differ by role. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting Operator record; ownership checks on any resource that references an Operator — submitting or withdrawing that operator's own bid entries, disputing pay on their own assignments, withdrawing their own grievances, reporting their own absence — compare the resource's operator foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `SchedulingOfficer`, `PayrollClerk`, or `UnionRep`, `X-User-ID` is an opaque staff identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

Endpoints returning lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this API — sign-up periods, runs, operators, bid entries, extra-board slots, daily assignments, absence cases, pay records, vacation slots, and grievance cases alike — carries a standard set of system-managed properties:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by exactly one on every mutation, and which anchors the optimistic-concurrency rules of §2.9.

### 2.5. Nested Resource Retrieval

When an endpoint path addresses a resource nested beneath a parent — a run beneath a sign-up period, a pay-record collection beneath a daily assignment — the server validates each path identifier in strict left-to-right order. The request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, and no later segment is examined. Foreign keys supplied in a request body (`run_id`, `operator_id`, `sign_up_period_id`, and similar references) are resolved after the path; a body reference that does not correspond to an existing resource is rejected with `ERR_REFERENCE_NOT_FOUND`, also a 404.

### 2.6. Validation Order

Every request is evaluated against a fixed ladder, and the first failing rung determines the error returned. Authentication comes first (missing or unknown headers yield `ERR_UNAUTHENTICATED`), followed by role authorization (`ERR_FORBIDDEN`), then left-to-right existence of path-referenced resources (`ERR_NOT_FOUND`), then existence of foreign keys referenced in the body (`ERR_REFERENCE_NOT_FOUND`), then whether the target resource's current state permits the operation at all (`ERR_INVALID_STATE`, HTTP 409). Only after those gates do the endpoint-specific business rules run — the piece-geometry, uniqueness, date-window, balance, capacity, and safety checks narrated in §3 — and the optimistic-concurrency stale-version check (`ERR_STALE_VERSION`, HTTP 412) always comes last, after every other validation has passed. Independently of this ladder, a malformed request body — a missing required field, a wrong-typed value, or a value outside a declared range or enumeration — is rejected with `ERR_VALIDATION` (HTTP 400). Where several business rules guard the same endpoint, §3 states their relative order explicitly.

### 2.7. Time, Money, and Rounding Conventions

Clock times inside a service day are expressed as whole minutes after midnight, and every duration in the system — spreads, platform time, paid time, overtime splits, accumulator totals — is an integer number of minutes. All minute arithmetic is integer arithmetic with no intermediate rounding.

Money is carried in whole cents. Gross pay is rounded half-up to whole cents, and that rounding is applied exactly once, at the final sum of a pay computation — never to intermediate minute splits. The base pay rate is fifty cents per paid minute; minutes classified as overtime are paid at one and a half times that base rate.

### 2.8. Seniority as the Ordering Principle

Each operator carries a `seniority_rank`, where 1 denotes the most senior operator. The rank is computed over the full roster excluding retired operators — operators in `ACTIVE`, `EXTRA_BOARD`, or `SUSPENDED` status are eligible — by ordering the eligible operators by `hire_date` ascending with ties broken by `employee_number` ascending, then taking the 1-based position in that order. Ranks are therefore unique and contiguous from 1. The computation is rerun over the entire roster whenever an operator is registered, suspended, reinstated, or retired. Seniority order drives the pick sequence of §3.4, the overtime-equalization tie-break of §3.7, and relief allocation more broadly.

### 2.9. Optimistic Concurrency Control

Exactly two write operations are version-guarded; every other endpoint takes no version field at all.

- **Submitting a bid entry** requires the non-optional field `expected_sign_up_period_version`, carrying the client's last observed `version` of the target sign-up period. If the period's current `version` has advanced since the client last read it — the canonical case being a mid-pick service change that withdrew previously posted runs — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from bidding against a run pool it has not observed.
- **Covering an absence case** requires the non-optional field `expected_absence_case_version`, carrying the client's last observed `version` of the absence case. A mismatch with the case's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — the case the dispatcher believes uncovered may already have been resolved by another desk.

### 2.10. Cascades and Version Semantics

State changes propagate across entity boundaries. Withdrawing a run withdraws the bids that reference it; suspending an operator withdraws their live bids; locking a pick releases unawarded runs to the board and exhausts unfilled slots; a service change cancels scheduled work whose run disappeared; covering an absence turns the absent operator's assignment into a no-show. Every such mutation — whether invoked directly by a client or produced by a cascade — refreshes the affected resource's `updated_at` and increments its `version` by one.

Two operations additionally advance the parent sign-up period's `version`: creating a run beneath the period, and submitting a bid entry against it. Every lifecycle action on the period itself — cutting, posting, opening the pick, adjudication, locking, implementation, schedule revision, and cancellation — likewise advances the period's `version` by one. The same convention holds across the other aggregates: operator lifecycle actions increment the operator's `version`; withdrawing a bid increments the bid entry's `version`; close-out, no-show marking, pay finalization, and pay dispute each increment the assignment's `version`; cover, declare-uncovered, and close each increment the absence case's `version`; grant and close each increment the vacation slot's `version`; and uphold, dismiss, and withdraw each increment the grievance case's `version`.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Sign-Up: Periods, Rosters, and Work Rules

A `SchedulingOfficer` opens the cycle by creating a sign-up period — think "Fall 2026 Sign-Up" — supplying a human-readable `name`, the `effective_start_date` and `effective_end_date` that bound the service window (the end date must not precede the start date), and the work-rule constants that will govern every run cut under it. `spread_limit_minutes` caps the elapsed time from first report to final release for any run and accepts an integer from 480 (eight hours) up to 900 (fifteen hours). `paid_break_minutes` sets the paid-break credit earned by long-spread runs, between 0 and 120 minutes. `extra_board_ratio_pct` sizes the extra board as a percentage of the posted run count, between 5 and 40. Two overtime thresholds complete the work rules: `daily_ot_threshold_minutes`, the paid minutes in a day beyond which the overtime rate applies — an integer from 420 to 600, defaulting to 480 (eight hours) when omitted — and `weekly_ot_threshold_minutes`, the cumulative straight-time minutes in a week beyond which weekly overtime applies — an integer from 2100 to 2700, defaulting to 2400 (forty hours) when omitted. A new period begins in `DRAFT` with `schedule_revision` at 1 and `picked_through_rank` at 0, and periods can be listed with an optional `status` filter.

The operator roster is maintained independently of any sign-up. Registering an operator requires the agency-issued `employee_number` (unique across the roster), the operator's `full_name`, and the `hire_date` from which seniority derives; a starting `vacation_hours_balance` may be supplied and defaults to 0. Each operator also carries `weekly_ot_minutes_accum`, a running total of overtime minutes paid to them in the current sign-up week, which starts at 0 and is reset by week rollover, and a `board_position` that stays null unless the operator sits on the extra board. An operator enters the roster as `ACTIVE` and may later move to `SUSPENDED` and back to `ACTIVE` at the scheduling desk's hand, or to `RETIRED` — retirement is permitted only when the operator holds no assignment in `SCHEDULED` status, and is rejected with `ERR_INVALID_STATE` otherwise. Suspending an operator cascades: every `SUBMITTED` bid entry of that operator in any `OPEN` or `PICKING` sign-up period transitions to `WITHDRAWN`. An operator demoted to `EXTRA_BOARD` during adjudication may be promoted back to `ACTIVE` once they hold an awarded run in the current sign-up; promotion clears `board_position` to null, and attempting it without an awarded run is `ERR_INVALID_STATE`. Operators can be listed with an optional `status` filter, and each operator's awarded runs, bid entries, board slots, absence cases, vacation weeks, and grievance cases are retrievable through paginated reverse-lookup collections.

A period still in `DRAFT` may be cancelled outright. Cancellation moves the period to `CANCELLED` and withdraws every run of the period still in `CUT` or `VALIDATED`.

### 3.2. Cutting Runs: Pieces, Spread, and Paid Time

Beneath a `DRAFT` period, the `SchedulingOfficer` cuts runs one at a time. Each run carries a roster `run_number`, a `service_date` given as an ISO date, and an ordered list of work `pieces`, where every piece is a triple of `report_minutes`, `release_minutes`, and `platform_minutes` expressed as minutes after midnight. The run records the `sign_up_period_id` it belongs to and the `schedule_revision` under which it was cut, and it enters the world in `CUT` status with `awarded_operator_id` null.

Three business checks guard run creation, evaluated in this order. First, piece geometry: within each piece the `release_minutes` must be later than the `report_minutes`, and across the list the pieces must be non-overlapping and ascending — any overlap, inversion, or equal report-release pair is rejected with `ERR_INVALID_RUN_PIECES`. Second, the `run_number` must be unique within the combination of period and schedule revision — a duplicate is rejected with `ERR_DUPLICATE_RUN_NUMBER`. Third, the `service_date` must fall within the period's effective window from `effective_start_date` through `effective_end_date` — a date outside that window is rejected with `ERR_DATE_OUT_OF_RANGE`. A creation request may additionally carry the query flag `strict`; when `strict` is true the spread work-rule is enforced immediately and an over-spread run is rejected with `ERR_SPREAD_LIMIT_EXCEEDED`, whereas without it an over-spread run is accepted and disposed of automatically when the cut is validated.

Three quantities are computed for every run when it is created, and recomputed whenever its pieces change, all in whole minutes with no rounding. `spread_minutes` is the largest `release_minutes` among the run's pieces minus the smallest `report_minutes` among them — the elapsed span from first report to final release. `platform_minutes` is the sum of the per-piece `platform_minutes`. `paid_minutes` is the platform time plus the break credit: the period's `paid_break_minutes` when the spread reaches ten hours (600 minutes) or more, and zero below that line.

When the cut is complete, the `SchedulingOfficer` validates it as a batch. Validation requires at least one run to exist under the period's current `schedule_revision` — otherwise the attempt is `ERR_INVALID_STATE` — and it disposes of every run of the current revision still in `CUT`: a run whose `spread_minutes` is within the period's `spread_limit_minutes` moves to `VALIDATED`, while a run whose spread exceeds the limit moves straight to `WITHDRAWN`. The period itself advances from `DRAFT` to `RUNS_CUT`. Runs of a period can be listed with optional `status` and `schedule_revision` filters, and the same spread rule fires again after every mid-pick service change (§3.6).

### 3.3. Posting the Cut and Sizing the Extra Board

Posting is the act that makes runs biddable. A `SchedulingOfficer` posts the cut once at least one run stands in `VALIDATED` — with none, the attempt is `ERR_INVALID_STATE` — whereupon every `VALIDATED` run moves to `POSTED` and the period advances from `RUNS_CUT` to `OPEN`.

Posting also sizes the extra board. The number of board slots is the count of runs in `POSTED` status multiplied by the period's `extra_board_ratio_pct`, divided by one hundred, with any fractional result rounded up to the next whole number — a ceiling toward positive infinity taken on the product before division. Only `POSTED` runs count toward the base; runs in `CUT`, `VALIDATED`, or `WITHDRAWN` are excluded. A direct consequence of the ceiling is the ratio floor: whenever at least one run is posted, at least one board slot is created, even when the raw product of ratio and count falls below one hundred. Each slot belongs to the period through its `sign_up_period_id`, receives a 1-based `slot_index` — lower positions are called out sooner — and begins `OPEN` with its `operator_id` null until an operator is demoted onto it. The board slots of a period can be listed with an optional `status` filter.

### 3.4. The Seniority Pick: Bid Sheets and Adjudication

While the period is `OPEN` — and continuing into `PICKING` — operators build their bid sheets. An `Operator` submits a bid entry naming the `operator_id` (for an `Operator` caller this is their own operator `id`, per the identity rule of §2.1), the desired `run_id`, and a `preference_rank`: a positive integer where 1 marks the most-preferred run, unique per operator within the period among that operator's `SUBMITTED` bids. Submission is accepted only while the period is `OPEN` or `PICKING`; against any other period state it fails with `ERR_INVALID_STATE`. Three further rejections guard submission, in order: a `preference_rank` the operator already holds on a live bid in the same period is rejected with `ERR_DUPLICATE_PREFERENCE`; a `run_id` that does not belong to this sign-up period, or that is otherwise not biddable, is rejected with `ERR_RUN_NOT_BIDDABLE`; and the stale-version check of §2.9 closes the ladder. Every accepted submission advances the period's `version` — which is exactly what lets the next bidder's stale `expected_sign_up_period_version` be detected. A bid whose run is later withdrawn by a service change is carried to `WITHDRAWN` by that cascade, and an operator may withdraw their own bid at will while the period remains `OPEN` or `PICKING` — from any other period state the withdrawal is `ERR_INVALID_STATE`. Bid entries of a period can be listed with optional `operator_id` and `status` filters; the bids referencing a particular run, and those filed by a particular operator, are likewise listable with a `status` filter.

The pick round itself begins when the `SchedulingOfficer` opens picking, permitted only while no bid entry of the period is yet `AWARDED` — otherwise `ERR_INVALID_STATE`. The period moves from `OPEN` to `PICKING` and `picked_through_rank` is set to 0.

Adjudication then proceeds one operator per call. Each adjudication selects the `ACTIVE` operator with the smallest `seniority_rank` strictly beyond `picked_through_rank` who still holds at least one `SUBMITTED` bid; since ranks are unique there is never a tie, and if no such operator exists the call is rejected with `ERR_INVALID_STATE`. That operator's sheet is walked in preference order: the `SUBMITTED` entry with the smallest `preference_rank` whose run is still `POSTED` is awarded — the entry moves from `SUBMITTED` to `AWARDED`, and its run moves from `POSTED` to `AWARDED` with `awarded_operator_id` set to the operator — while every other `SUBMITTED` entry of that operator moves to `PASSED`. When none of the operator's remaining bids reference a `POSTED` run, all of them pass and the operator is demoted to the extra board: their status becomes `EXTRA_BOARD`, the `OPEN` board slot with the lowest `slot_index` moves to `FILLED` with its `operator_id` set, and the operator's `board_position` takes that slot's `slot_index`. Either way, `picked_through_rank` advances to the adjudicated operator's rank, and the period's `version` increments by one.

Seniority discipline is enforced even outside the pick itself. Suspending an operator mid-pick withdraws their live bids through the cascade of §3.1, and a demoted operator who later holds an awarded run in the current sign-up may be promoted back to `ACTIVE`, clearing `board_position`.

### 3.5. Locking and Implementation: Materializing the Work

Locking ends the pick. The `SchedulingOfficer` may lock only when every `ACTIVE` operator holding at least one `SUBMITTED` bid has a `seniority_rank` at or below `picked_through_rank` — no bidder with a live sheet may remain unadjudicated — and when every run still `POSTED` has either been awarded or is explicitly released to the board; failing either condition is `ERR_INVALID_STATE`. At lock, each run still `POSTED` moves to `EXTRA_BOARD_HELD`, each board slot still `OPEN` moves to `EXHAUSTED`, and the period moves from `PICKING` to `LOCKED`.

Implementation turns the awarded roster into dated work. It requires every run of the period to stand in `AWARDED`, `EXTRA_BOARD_HELD`, or `WITHDRAWN` — otherwise `ERR_INVALID_STATE` — and then materializes assignments. For every `AWARDED` run, a `DailyAssignment` is created for each of the run's service dates falling inside the period's effective window — the run's `service_date` having already been validated against that window at creation — stamped with the period's `sign_up_period_id`, the awarded `operator_id`, the `run_id`, the `service_date`, a `source` of `BID_AWARD`, `status` `SCHEDULED`, `pay_status` `PROVISIONAL`, and a `scheduled_minutes` snapshot equal to the run's `paid_minutes` at the moment of assignment. For every `FILLED` board slot, a stand-by assignment is created with `run_id` null, `source` `EXTRA_BOARD_FILL`, and `status` `SCHEDULED`. Implementation also exhausts the filled board: every slot in `FILLED` moves to `EXHAUSTED`. A new assignment's `actual_platform_minutes` stays null until timekeeping close-out reports the worked time (§3.8). With the work materialized, the period moves from `LOCKED` to `IMPLEMENTED` — one of its two terminal states, the other being `CANCELLED`. Assignments can be listed filtered by `operator_id`, `sign_up_period_id`, `service_date`, `status`, or `run_id`.

Every assignment is priced the moment it comes into existence: a `PROVISIONAL` pay record is computed from its `scheduled_minutes` under the pricing rules of §3.8.

### 3.6. Mid-Pick Service Change

Service does not always hold still for a pick. While a period is `PICKING`, a `SchedulingOfficer` may post a schedule revision whose payload `new_runs` must be non-empty — an empty or malformed payload is rejected with `ERR_VALIDATION`. The revision increments the period's `schedule_revision` by one and rewrites the biddable pool: every run of the prior revision still `POSTED` moves to `WITHDRAWN`, and every `SUBMITTED` bid entry referencing a withdrawn run moves to `WITHDRAWN` with it, while runs already `AWARDED` are left untouched. Should a run withdrawn this way ever have assignments still `SCHEDULED` against it, those assignments move to `CANCELLED` and their `PROVISIONAL` pay records are deleted. The `new_runs` are then cut under the new revision — subject to the same piece-geometry rules as initial creation (§3.2) — validated by the spread rule so that each new run lands in `VALIDATED` or `WITHDRAWN`, and every `VALIDATED` new run is posted immediately. The pick then restarts on the augmented pool: `picked_through_rank` resets to 0, the period returns from `PICKING` to `RUNS_CUT`, and bid awards made before the revision stay awarded. Because the revision brings new runs into existence, it is answered with 201 rather than 200. This is the precise workflow the bid-submission version check of §2.9 protects: a bidder whose last read predates the revision is bidding on a pool that no longer exists, and their `expected_sign_up_period_version` says so.

### 3.7. Absence Coverage and Overtime Equalization

Absences enter the system as absence cases, reported by a `SchedulingOfficer` or by the affected `Operator` for themselves, carrying `operator_id`, `absence_date`, and a `reason_code` of `SICK`, `PERSONAL`, `VACATION`, or `UNEXCUSED`. The `absence_date` must fall within the sign-up window of the operator's affected assignment — a date outside it is `ERR_DATE_OUT_OF_RANGE`. A new case is `REPORTED`, its `covering_assignment_id` null until coverage exists, and cases can be listed with optional `operator_id`, `status`, and `covering_assignment_id` filters. Separately, the scheduling desk may mark any scheduled assignment as a no-show, moving it from `SCHEDULED` to `NO_SHOW` — the operational signal that typically prompts an absence report and its coverage cascade.

Coverage is the dispatcher's desk, and it is one of the two version-guarded writes of §2.9: the request must carry `expected_absence_case_version` matching the case's current `version`, with a mismatch rejected as `ERR_STALE_VERSION`. Two preconditions precede selection: the absent operator must hold a `SCHEDULED` assignment on the `absence_date` with a non-null `run_id` — otherwise `ERR_INVALID_STATE` — and at least one eligible covering operator must exist. Selection follows one of two paths with equal rigor. The board path considers operators in `EXTRA_BOARD` status, choosing the lowest `board_position` and breaking ties by earlier `hire_date`. The overtime path is available only when the board is empty and the request's `allow_overtime` flag is true; it considers operators in `ACTIVE` status only — board and suspended operators are excluded — choosing the lowest `weekly_ot_minutes_accum` and breaking ties by lower `seniority_rank`, which is the overtime-equalization rule: premium hours steer toward the operator who has received the least of them. When neither path yields a candidate, the cover attempt is rejected with `ERR_NO_COVER_AVAILABLE`.

A successful cover moves the case from `REPORTED` to `COVERED`, creates the covering assignment — carrying the same `run_id` and `service_date` as the absent operator's assignment, a `source` of `EXTRA_BOARD_FILL` on the board path or `OVERTIME_OFFER` on the overtime path, and `status` `SCHEDULED` — records it as the case's `covering_assignment_id`, and moves the absent operator's original assignment from `SCHEDULED` to `NO_SHOW`. When coverage hands a board-held run to the covering operator, the run moves from `EXTRA_BOARD_HELD` to `AWARDED` with `awarded_operator_id` set to that operator. A board operator who covers keeps their place on the board: their slot remains `FILLED` until implementation exhausts it, and their `board_position` is unchanged.

When no cover exists, the dispatcher may instead declare the case uncoverable — permitted only when no eligible covering operator exists, board empty and the overtime path exhausted — moving the case from `REPORTED` to `UNCOVERED` and cancelling the absent operator's assignment from `SCHEDULED` to `CANCELLED`. Either resolved state can later be closed: a `COVERED` case closes once its covering assignment stands in `WORKED` or `CANCELLED` — anything else is `ERR_INVALID_STATE` — while an `UNCOVERED` case closes without conditions. `CLOSED` is the case's final resting state.

### 3.8. Timekeeping Close-Out, Pay Pricing, and Pay Disputes

An assignment carries two parallel state dimensions that evolve independently: `status` tracks the work lifecycle through `SCHEDULED`, `WORKED`, `NO_SHOW`, and `CANCELLED`, while `pay_status` tracks pay validation through `PROVISIONAL`, `FINALIZED`, and `DISPUTED`.

Once the work is done, a `PayrollClerk` closes the assignment out by supplying `actual_platform_minutes`, the platform time actually worked. The state gate fires first: only an assignment in `SCHEDULED` can be closed out, and any other state draws `ERR_INVALID_STATE`. The minutes are validated next: the value must be present in the payload, greater than zero, and no more than 960 — sixteen hours — with any failure rejected as `ERR_INVALID_ACTUAL_MINUTES`. Close-out moves the assignment from `SCHEDULED` to `WORKED`, writes a `FINAL` pay record priced on the actual minutes, and adds that record's `overtime_minutes` to the operator's `weekly_ot_minutes_accum`.

Pay pricing follows a pinned evaluation order for both variants — minutes basis first, then the daily overtime split, then the weekly overtime split, then the price. The basis is `scheduled_minutes` for the `PROVISIONAL` variant, priced when the assignment is created, and `actual_platform_minutes` for the `FINAL` variant, which replaces the provisional record's numbers for the same assignment. Daily overtime is the portion of the basis lying beyond the period's `daily_ot_threshold_minutes` — zero when the basis does not exceed the threshold — and removing it from the basis leaves the post-daily straight time. The weekly room remaining is the period's `weekly_ot_threshold_minutes` minus the operator's prior straight time for the week, floored at zero; prior straight time is the sum of `straight_minutes` across the operator's `FINAL` pay records whose service dates fall in the same ISO week, computed before this record — provisional records never count toward it. Any post-daily straight time exceeding that remaining weekly room is reclassified as additional weekly overtime. The record's `straight_minutes` are what remains of the post-daily straight time after that reclassification, and its `overtime_minutes` are the daily overtime plus the weekly reclassification. Finally, `gross_cents` is the straight minutes times the base rate plus the overtime minutes times the base rate times one and a half, rounded half-up to whole cents at the final sum only, per §2.7. Each pay record references its assignment through `daily_assignment_id` and is stamped with its `variant` — `PROVISIONAL` or `FINAL` — and both records of an assignment are retrievable together.

Pay validation completes through finalization and dispute. A `PayrollClerk` may finalize pay on an assignment in `PROVISIONAL` provided the assignment is `WORKED` and a `FINAL` pay record exists for it — failing either condition is `ERR_INVALID_STATE`; finalization sets `pay_status` to `FINALIZED` and books the difference between the `FINAL` and `PROVISIONAL` gross amounts to the operator's next-week accumulator. The assigned operator — and only that operator, by the identity rule of §2.1 — may dispute the pay, moving `pay_status` from `PROVISIONAL` or `FINALIZED` to `DISPUTED`. A disputed assignment can subsequently be finalized by the clerk once a `FINAL` pay record exists, moving `pay_status` from `DISPUTED` to `FINALIZED`.

### 3.9. Vacation Weeks and Grievances

Relief weeks are managed as vacation slots beneath a sign-up period. A `SchedulingOfficer` creates a slot with its `week_start_date` — the ISO Monday of the vacation week — and a `capacity` of at least one; the slot opens as `OPEN` with `allocated_count` at 0 and `operator_id` null. Granting a week to an operator enforces two checks in order: first the operator's `vacation_hours_balance` must cover a full forty-hour vacation week — a smaller balance is rejected with `ERR_INSUFFICIENT_VACATION_BALANCE` — and then the slot must still have room, `allocated_count` below `capacity`, with a full slot rejected as `ERR_VACATION_SLOT_FULL`. A successful grant increments `allocated_count` by one, debits 40 hours from the operator's balance, and records the grant on the slot's `operator_id`; when the count reaches capacity the slot moves from `OPEN` to `FULLY_ALLOCATED`. Competing grant requests are adjudicated in request order, first come first served until capacity fills. A slot may be closed from either `OPEN` or `FULLY_ALLOCATED`, moving it to its terminal state `CLOSED`. The slots of a period are listable with an optional `status` filter, and each operator's granted weeks appear in their reverse-lookup collection.

Grievances give the union its enforcement channel. A case is filed by an `Operator` or by a `UnionRep` on a member's behalf, carrying `filed_by_operator_id`, the disputed `sign_up_period_id`, a `category` of `OT_EQUALIZATION`, `SENIORITY_BYPASS`, `WORK_RULE_SPREAD`, or `PAY_VALIDATION`, and a free-text `detail`; the case enters `FILED` with `remedy_minutes` at 0, and cases are listable filtered by `status`, `category`, `sign_up_period_id`, or `filed_by_operator_id`. A `UnionRep` may uphold a case — optionally supplying `remedy_minutes` — moving it from `FILED` to `UPHELD` and crediting those remedy minutes to the filing operator's `weekly_ot_minutes_accum` as the compensating make-whole. For the `OT_EQUALIZATION` category an uphold demands evidence: at the time of the overtime assignment there must have existed an `ACTIVE` operator whose `weekly_ot_minutes_accum` was strictly lower than that of the operator who received the overtime; absent that evidence the uphold is rejected with `ERR_GRIEVANCE_PRECONDITION`. A `UnionRep` may instead dismiss the case, moving it from `FILED` to `DISMISSED`, and the filing operator — only that operator — may withdraw it, moving it from `FILED` to `WITHDRAWN`. All three outcomes are terminal.

## 4. Endpoint Definitions

Operations that create new resources — a sign-up period, a run, an operator, a bid entry, an absence case, a vacation slot, a grievance case — return `201 Created`; the mid-pick schedule revision also returns `201 Created` because it brings new runs into existence. Operations that modify an existing resource or drive a lifecycle transition return `200 OK`. Request payloads, computed fields, preconditions, and side effects are defined by the workflows of §3; the table below is the address map, not the full contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/sign-up-periods` | Create a sign-up period in `DRAFT` with work-rule constants | SchedulingOfficer |
| GET | `/api/sign-up-periods` | List sign-up periods with pagination and optional status filter | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| GET | `/api/sign-up-periods/{id}` | Fetch one sign-up period | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| POST | `/api/sign-up-periods/{id}/runs` | Create a run in `CUT` under the period's current schedule revision | SchedulingOfficer |
| GET | `/api/sign-up-periods/{id}/runs` | List runs of a period, filterable by status and schedule revision | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| GET | `/api/runs/{id}` | Fetch one run | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| GET | `/api/runs/{id}/bid-entries` | List bid entries referencing a run | SchedulingOfficer, Operator, UnionRep |
| POST | `/api/sign-up-periods/{id}/cut-runs` | Validate all `CUT` runs against the spread rule | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/post-runs` | Post `VALIDATED` runs and size the extra board | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/open-picking` | Open the seniority pick round | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/adjudicate-next` | Adjudicate the next-most-senior pending bidder | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/lock` | Lock the pick; unawarded `POSTED` runs become board-held | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/implement` | Implement the sign-up; materialize daily assignments | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/schedule-revisions` | Mid-pick service change: bump revision, withdraw stale posted runs, cut replacements | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/cancel` | Cancel a `DRAFT` sign-up period | SchedulingOfficer |
| POST | `/api/operators` | Register an operator | SchedulingOfficer |
| GET | `/api/operators` | List operators with pagination and optional status filter | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| GET | `/api/operators/{id}` | Fetch one operator | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| POST | `/api/operators/{id}/suspend` | Suspend an operator; withdraws their live bids | SchedulingOfficer |
| POST | `/api/operators/{id}/reinstate` | Reinstate a suspended operator | SchedulingOfficer |
| POST | `/api/operators/{id}/retire` | Retire an operator with no scheduled assignments | SchedulingOfficer |
| POST | `/api/operators/{id}/promote` | Promote an `EXTRA_BOARD` operator back to `ACTIVE` after a run award | SchedulingOfficer |
| GET | `/api/operators/{id}/runs` | List runs awarded to an operator | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/operators/{id}/bid-entries` | List bid entries of an operator | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/operators/{id}/extra-board-slots` | List extra board slots held by an operator | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/operators/{id}/absence-cases` | List absence cases of an operator | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/operators/{id}/vacation-slots` | List vacation slots granted to an operator | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/operators/{id}/grievance-cases` | List grievances filed by an operator | SchedulingOfficer, Operator, UnionRep |
| POST | `/api/sign-up-periods/{id}/bid-entries` | Submit a bid entry (version-guarded on the sign-up period) | Operator |
| GET | `/api/sign-up-periods/{id}/bid-entries` | List bid entries of a period, filterable by operator and status | SchedulingOfficer, Operator, UnionRep |
| POST | `/api/bid-entries/{id}/withdraw` | Operator withdraws own `SUBMITTED` bid while the period is open or picking | Operator |
| GET | `/api/sign-up-periods/{id}/extra-board-slots` | List extra board slots of a period | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/daily-assignments` | List daily assignments with filters | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| GET | `/api/daily-assignments/{id}` | Fetch one daily assignment | SchedulingOfficer, Operator, UnionRep, PayrollClerk |
| POST | `/api/daily-assignments/{id}/close-out` | Timekeeping close-out with actual minutes; prices final pay | PayrollClerk |
| POST | `/api/daily-assignments/{id}/mark-no-show` | Mark a scheduled assignment as no-show | SchedulingOfficer |
| POST | `/api/daily-assignments/{id}/finalize-pay` | Finalize pay validation | PayrollClerk |
| POST | `/api/daily-assignments/{id}/dispute-pay` | Assigned operator disputes pay | Operator |
| GET | `/api/daily-assignments/{id}/pay-records` | List pay records of an assignment (provisional and final) | SchedulingOfficer, Operator, PayrollClerk |
| POST | `/api/absence-cases` | Report an operator absence | SchedulingOfficer, Operator |
| GET | `/api/absence-cases` | List absence cases with filters | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/absence-cases/{id}` | Fetch one absence case | SchedulingOfficer, Operator, UnionRep |
| POST | `/api/absence-cases/{id}/cover` | Cover an absence from the extra board or via overtime offer (version-guarded on the case) | SchedulingOfficer |
| POST | `/api/absence-cases/{id}/declare-uncovered` | Declare an absence uncoverable | SchedulingOfficer |
| POST | `/api/absence-cases/{id}/close` | Close a resolved absence case | SchedulingOfficer |
| POST | `/api/sign-up-periods/{id}/vacation-slots` | Create a vacation week slot with capacity | SchedulingOfficer |
| GET | `/api/sign-up-periods/{id}/vacation-slots` | List vacation slots of a period | SchedulingOfficer, Operator, UnionRep |
| POST | `/api/vacation-slots/{id}/grant` | Grant a vacation week to an operator | SchedulingOfficer |
| POST | `/api/vacation-slots/{id}/close` | Close a vacation slot | SchedulingOfficer |
| POST | `/api/grievance-cases` | File a grievance | Operator, UnionRep |
| GET | `/api/grievance-cases` | List grievance cases with filters | SchedulingOfficer, Operator, UnionRep |
| GET | `/api/grievance-cases/{id}` | Fetch one grievance case | SchedulingOfficer, Operator, UnionRep |
| POST | `/api/grievance-cases/{id}/uphold` | Uphold a grievance; credits remedy minutes on overtime equalization | UnionRep |
| POST | `/api/grievance-cases/{id}/dismiss` | Dismiss a grievance | UnionRep |
| POST | `/api/grievance-cases/{id}/withdraw` | Filing operator withdraws a grievance | Operator |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_RUN_PIECES` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RUN_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_PREFERENCE` | 409 Conflict |
| `ERR_DATE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_RUN_NOT_BIDDABLE` | 422 Unprocessable Entity |
| `ERR_SPREAD_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_ACTUAL_MINUTES` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_VACATION_BALANCE` | 422 Unprocessable Entity |
| `ERR_VACATION_SLOT_FULL` | 409 Conflict |
| `ERR_NO_COVER_AVAILABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_GRIEVANCE_PRECONDITION` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |
