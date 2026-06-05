# Shift Scheduling & Fair Workweek API — Product Requirements Document

## 1. Introduction

Retail, hospitality, and care-sector employers increasingly operate under fair-workweek statutes that turn scheduling from a back-office convenience into a regulated, money-bearing activity. A last-minute schedule change is no longer free: posting a shift on short notice, cancelling it once posted, or scheduling a worker too soon after their previous shift can each oblige the employer to pay a predictability premium. At the same time, minors carry hard daily and weekly hour ceilings, overtime inflates labor cost past a weekly threshold, and managers need a guardrail that stops a pay-period's projected cost from quietly blowing past budget.

This API is the system of record for that world. It models locations and their demand forecasts, the workers who staff them, the availability and time-off windows that constrain who can work when, and the full lifecycle of a shift from a draft slot through open bidding, direct assignment, swaps between workers, completion, and no-show handling. Every scheduling decision flows through a single consistent set of fair-workweek, labor-law, and fiscal checks, and every cost consequence is reconciled immediately into the affected pay-period so that a manager always sees an accurate projected and, once locked, finalized labor cost.

The design intent is that the same business event — a worker landing on a shift — is evaluated identically whether it arrived by direct manager assignment, by winning an open-shift bid, or by a manager-approved swap. The sections below define the shared contract first, then walk the business workflows where the scheduling, predictability-pay, and cost rules are spelled out.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly two roles, spelled `Manager` and `Worker`. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted for the target operation — or a `Worker` acting on a resource it does not own — is rejected with `ERR_UNAUTHORIZED`. The test-driving clock endpoint is no exception: it still requires both headers even though it is an operational utility.

The two roles bind to identity in different ways. When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks compare the relevant foreign-key field of the target resource to `X-User-ID`. A worker may confirm only an assignment whose `worker_id` equals `X-User-ID`, withdraw only a bid whose `worker_id` equals `X-User-ID`, cancel only a time-off request whose `worker_id` equals `X-User-ID`, and act in a swap only as the party they actually are (the initiator is the worker of the swap's `from_assignment_id`; the counterparty is the swap's `to_worker_id`). When `X-User-Role` is `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `decided_by_manager_id` on a `TimeOffRequest` it approves or denies, and as `decided_by_manager_id` on a `SwapRequest` it approves — but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100 — an out-of-range `limit` is silently clamped into that range (a value below 1 becomes 1, a value above 100 becomes 100) rather than rejected. The `offset` parameter is the number of items to skip from the front of the result and defaults to 0; a negative `offset` is silently clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in this system are mutable and carry a uniform set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control where that applies. These four properties are present on `Location`, `Worker`, `Availability`, `TimeOffRequest`, `ShiftTemplate`, `Shift`, `Assignment`, `OpenShiftBid`, `SwapRequest`, and `PayPeriod`.

The lone exception is the predictability-pay ledger. A `PredictabilityLedgerEntry` is an append-only event record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified.

### 2.5. Time, the Logical Clock, and Time Zones

All instants persisted by the system — shift starts and ends, availability and time-off windows, pay-period boundaries, the moment a shift was posted — are stored as ISO 8601 UTC instants. Every rule that reasons about "now" (whether a shift has started, whether it has ended, whether a posting or cancellation falls inside the advance-notice window, whether a confirmation is still in time) reads a single server-held logical clock rather than wall-clock time. An administrative test-driving capability sets that clock to a supplied instant; all relative-time checks read from it thereafter.

A location stores its `time_zone` as an IANA zone name. The zone matters in exactly two places: generating a concrete shift from a template, where the template's local start minute and weekday are resolved against the location-local calendar to produce UTC instants, and the minor daily-hours cap, where "the same calendar day" means the same location-local day. Everywhere else, comparisons are performed directly on the stored UTC instants.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many operational endpoints address a resource through a path that names its location first and the target resource second. The server validates path and body identifiers left to right: the `Location` is resolved before the `Shift`, `Assignment`, `Bid`, `Swap`, `TimeOffRequest`, or `PayPeriod` named after it, and any referenced `Worker` or other body resource is resolved in turn. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` immediately, before any later identifier or business rule is evaluated.

### 2.7. Validation Order and Precedence

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every referenced resource (`ERR_NOT_FOUND`), then well-formedness of the request body — required fields present, enums valid, durations greater than zero, headcount at least one (`ERR_INVALID_REQUEST`). The priority-2 `ERR_UNAUTHORIZED` slot is the role-permission check (is the acting role allowed to call this operation at all). The narrower ownership-based `ERR_UNAUTHORIZED` of §2.1 — a `Worker` acting on a worker-owned transition (confirm, withdraw, time-off cancel, swap counter/repropose/accept/reject/cancel) whose owning foreign key does not equal `X-User-ID` — is instead evaluated *after* the target entity's state precondition, so that an out-of-state transition surfaces its per-entity invalid-state error even when the acting worker is also not the owner. After body shape comes the time-window check, that `end_utc` is strictly after `start_utc` on a shift, availability window, time-off request, or pay-period (`ERR_INVALID_TIME_WINDOW`). Only then are state-machine preconditions evaluated (the per-entity invalid-state errors), followed by the pay-period-open check (`ERR_PAY_PERIOD_LOCKED`), then the optimistic-concurrency version check on award (`ERR_STALE_SHIFT_VERSION`), then same-location referential integrity (`ERR_CROSS_LOCATION`).

The remaining business-safety and fiscal checks, where they apply to the same operation, are ordered after the above and among themselves as follows: worker-not-suspended (`ERR_WORKER_SUSPENDED`) is checked before worker-availability (`ERR_WORKER_UNAVAILABLE`), which is checked before the minor hour-cap (`ERR_MINOR_HOUR_CAP_EXCEEDED`), which is checked before the over-staffing guard (`ERR_SHIFT_FULLY_STAFFED`), which is checked before the overtime cost guardrail (`ERR_OVERTIME_GUARDRAIL_EXCEEDED`). This ordering is observable: a request that violates two rules surfaces the higher-precedence error.

### 2.8. Monetary Amounts, Hours, and Rounding

Every monetary amount in the system is an integer count of cents — base rates, costs, guardrails, penalties, and pay-period aggregates alike. Durations are measured in exact hours computed as the difference between two UTC instants divided into hours, kept as exact (non-rounded) floating values for all intermediate arithmetic. Whenever a cost is reduced to a stored cent amount, the reduction happens exactly once, after the regular and overtime portions have been summed — never term by term — using the round-half-up convention. Hour comparisons against caps and thresholds use the exact (unrounded) hour values.

### 2.9. Derived-Field Reconciliation

Several fields are read-only and never accepted from a client: a shift's `headcount_filled` and `duration_hours`; a worker's `no_show_strikes`; an assignment's `clopening_flag`, `provisional_cost_cents`, and `finalized_cost_cents`; and a pay-period's `projected_labor_cost_cents` and `finalized_labor_cost_cents`. These are recomputed by the server as the events that feed them occur. In particular, every assignment mutation that adds, removes, or finalizes labor cost, and every predictability-ledger append, triggers an immediate reconciliation of the owning pay-period's aggregate cost. Such a reconciliation refreshes the pay-period's `updated_at` and increments its `version` only when it actually changes the stored aggregate; a reconciliation that recomputes the identical value leaves `updated_at` and `version` untouched.

### 2.10. Cascading State Propagation

A shift's `status` and its filled headcount are kept in lockstep with the assignments beneath it. When an assignment enters the filled set and that makes the shift fully staffed, the shift auto-advances from `OPEN` to `FULLY_STAFFED` with no explicit request on the shift. When an assignment later leaves the filled set — through cancellation or a no-show — and the filled count drops below the required count, the shift reverts from `FULLY_STAFFED` back to `OPEN` so the seat can be re-staffed. The filled set for a shift is precisely its assignments in `SCHEDULED`, `CONFIRMED`, or `COMPLETED`. Cancelling or completing a shift cascades down to its assignments, and the affected pay-periods are reconciled as part of the same operation. These propagations are detailed in the workflows of §3.

### 2.11. Optimistic Concurrency on Open-Shift Awards

Awarding a seat on an open shift is the one operation guarded by optimistic concurrency control. The award request must carry `expected_shift_version`, the `version` of the target `Shift` that the manager last observed. The server compares it to the shift's current `version`; if another award has advanced the version since the manager read it — for instance, by creating an assignment that consumed an open seat and possibly flipped the shift to `FULLY_STAFFED`, leaving the manager's view of which bids are still `SUBMITTED` stale — the write is refused with `ERR_STALE_SHIFT_VERSION` (HTTP 412). The field is not optional on this operation. No other endpoint takes a version field, and a successful award is itself what increments the shift's `version` by one. When that same award also fills the last seat and the shift auto-advances to `FULLY_STAFFED`, that cascading state transition (§2.10) is a separate mutation that increments `version` again, so an award which flips the shift to `FULLY_STAFFED` advances `version` by two in total.

## 3. Business Logic & Workflows

### 3.1. Locations, Workers, and the Fair-Workweek Dials

A `Manager` stands up a `Location` by supplying its human-readable `name`, its IANA `time_zone`, and the per-pay-period labor-cost ceiling `overtime_cost_guardrail_cents`. A location also holds a set of fair-workweek and overtime dials, each of which a manager may supply or leave to its default. The `predictability_pay_enabled` flag governs whether fair-workweek premiums accrue at all and defaults to enabled. The `advance_notice_days` value defines the fair-workweek notice window in days and defaults to fourteen; a schedule change that lands inside that many days before the affected shift's start is "short notice." The `min_rest_hours_between_shifts` value is the rest gap that defines a clopening and defaults to ten hours. The overtime band is set by `overtime_weekly_threshold_hours`, defaulting to forty hours per pay-week, and `overtime_multiplier`, defaulting to one-and-a-half. On creation a location's `status` is initialized to `ACTIVE`; there is no archival flow, and the field exists so that reads carry a stable status.

A manager registers a `Worker` at a location, providing `full_name`, the login `email` (intended to be unique among workers within a location, though the server does not enforce that uniqueness — a duplicate `email` is accepted and creates a second worker), and `base_hourly_rate_cents`. Whether the worker is a minor is set by `is_minor`, defaulting to not-a-minor. Two minor caps may be supplied or defaulted: `minor_daily_cap_hours` (default eight) bounds scheduled hours on any one location-local calendar day, and `minor_weekly_cap_hours` (default eighteen) bounds scheduled hours across a pay-week. Every new worker starts with a `no_show_strikes` count of zero and a `status` of `ACTIVE`. The strike count is read-only: it is incremented when one of the worker's assignments is marked a no-show and is never decremented. When it reaches three, the worker's `status` is automatically set to `SUSPENDED`. The two worker statuses are exactly `ACTIVE` and `SUSPENDED`.

A worker — or a manager on their behalf — records an `Availability` window by giving its `kind`, `start_utc`, and `end_utc`, where the end must be strictly later than the start. The `kind` is one of `AVAILABLE` or `UNAVAILABLE`. An `UNAVAILABLE` window is a hard block on scheduling: it is treated as a closed interval spanning both endpoints, so a shift that merely touches the boundary instant collides with it. An `AVAILABLE` window is advisory only — it signals bid-eligibility and never blocks a scheduling decision on its own.

### 3.2. Time-Off Requests

A worker submits a `TimeOffRequest` against their own record, supplying `start_utc`, `end_utc` (strictly after the start), and a free-text `reason`. A new request opens in `PENDING` status with `decided_by_manager_id` empty. The request's window is treated as half-open — it covers the start instant up to but not including the end instant — when later used as a scheduling block.

A manager either approves or denies a pending request; either decision stamps `decided_by_manager_id` with the manager's opaque identifier. Approval is permitted only from `PENDING` (otherwise `ERR_INVALID_TIME_OFF_STATE`) and additionally requires that no `SCHEDULED` or `CONFIRMED` assignment for that worker overlaps the requested half-open window; if one does, approval is rejected with `ERR_TIME_OFF_CONFLICTS_ASSIGNMENT`. Once approved, the request moves to `APPROVED` and its window thereafter hard-blocks future assignment exactly as an `UNAVAILABLE` availability window does. Denial moves a `PENDING` request to `DENIED`. A worker may instead cancel their own still-`PENDING` request — permitted only from `PENDING`, and only by the owning worker (else `ERR_UNAUTHORIZED`) — moving it to `CANCELLED`. The four time-off statuses are `PENDING`, `APPROVED`, `DENIED`, and `CANCELLED`.

### 3.3. Demand Forecasting and Shift Creation

Demand planning starts from a `ShiftTemplate`, which a manager creates against a location to forecast recurring staffing. A template names the `role_name` to staff, the `weekday` it recurs on as an integer where zero is Monday through six for Sunday, the `local_start_minute` measured as minutes after location-local midnight in the range zero through 1439, the `duration_minutes` (which must be greater than zero), and the `forecast_headcount` the forecast wants, which must be at least one.

From a template a manager generates a concrete shift for a given week by supplying `week_start_local_date` as a `YYYY-MM-DD` calendar date (a malformed date is rejected with `ERR_INVALID_REQUEST`). The system treats `week_start_local_date` as the Monday — weekday zero — of the target week and adds the template's `weekday` as a day offset to land on the target location-local day; the resolved local day, the template's `local_start_minute`, and `duration_minutes` are then interpreted in the location's time zone to produce the UTC instants. The system creates a single `DRAFT` `Shift` whose `start_utc` and `end_utc` are derived by resolving the template's weekday, local start minute, and duration against the location's time zone for that week; its `headcount_required` is copied from the template's forecast headcount, and its `template_id` records the originating template. A manager may also create an ad-hoc shift directly, supplying `role_name`, `start_utc`, `end_utc` (strictly after the start), `headcount_required` (at least one), and an optional `template_id` (left empty for a genuinely ad-hoc slot, which is why the field is nullable). Every shift belongs to a location via `location_id`. A shift exposes a read-only `duration_hours` equal to the exact, unrounded span between its start and end, and a read-only `headcount_filled` equal to the count of its assignments in `SCHEDULED`, `CONFIRMED`, or `COMPLETED`. A freshly created shift's `posted_utc` is empty and its `status` is `DRAFT`. The five shift statuses are `DRAFT`, `OPEN`, `FULLY_STAFFED`, `COMPLETED`, and `CANCELLED`.

### 3.4. Posting, Completing, and Cancelling Shifts

Posting takes a shift from `DRAFT` to `OPEN`, making it eligible for bidding and assignment; it requires the shift to be in `DRAFT` (otherwise `ERR_INVALID_SHIFT_STATE`) and its `end_utc` to be strictly after its `start_utc` (otherwise `ERR_INVALID_TIME_WINDOW`). Posting stamps `posted_utc` with the current clock instant, which pins the advance-notice baseline. If the location has predictability pay enabled and the gap between the shift's start and the posting instant is less than the advance-notice window, the posting is "short notice"; no premium accrues at post time, but a premium will accrue when the shift is later staffed, as described in §3.7.

Completing a shift is permitted only when it is `OPEN` or `FULLY_STAFFED` (otherwise `ERR_INVALID_SHIFT_STATE`) and only once the current clock instant has reached the shift's `end_utc` (otherwise `ERR_SHIFT_NOT_ENDED`). Completion drives the shift to `COMPLETED` and cascades down: every `SCHEDULED` or `CONFIRMED` assignment on the shift is advanced to `COMPLETED`, each one stamping its `finalized_cost_cents` (computed as in §3.8) and reconciling its pay-period.

Cancellation is permitted from any of `DRAFT`, `OPEN`, or `FULLY_STAFFED` (otherwise `ERR_INVALID_SHIFT_STATE`) and moves the shift to `CANCELLED`. A `DRAFT` shift has no assignments, so nothing cascades. Cancelling an `OPEN` or `FULLY_STAFFED` shift cascades down in three parallel ways: every non-terminal assignment on the shift is moved to `CANCELLED`; every still-`SUBMITTED` open-shift bid on the shift is moved to `REJECTED`; and each affected pay-period is reconciled to remove the cancelled assignments' provisional cost. In addition, if predictability pay is enabled and the gap between the shift's `start_utc` and the current clock is less than the advance-notice window, then for each worker who held a now-cancelled assignment the system appends a short-notice cancellation entry to the predictability ledger and reconciles the pay-period — the same short-notice-cancel accrual described in §3.7.

### 3.5. Direct Assignment and Worker Confirmation

A manager assigns a worker to a shift directly by posting the `shift_id`, the `worker_id`, and an optional `force_over_guardrail` flag. The assignment is created in `SCHEDULED` status with `source` recorded as `DIRECT`. Its owning `pay_period_id` is the location pay-period whose half-open window contains the shift's start; if no pay-period of that location contains the shift's start, the assignment (or award) cannot be placed and the request is rejected with `ERR_INVALID_REQUEST`. The five assignment statuses are `SCHEDULED`, `CONFIRMED`, `COMPLETED`, `NO_SHOW`, and `CANCELLED`; the three assignment sources are `DIRECT`, `BID`, and `SWAP`. Direct assignment targets a posted, non-terminal shift: the target shift must be in `OPEN` or `FULLY_STAFFED` (a `DRAFT`, `COMPLETED`, or `CANCELLED` shift is rejected with `ERR_INVALID_SHIFT_STATE`). A shift that has already auto-advanced to `FULLY_STAFFED` is not rejected on its state — it passes this precondition and falls through to the eligibility battery, where the already-at-headcount case is surfaced by the over-staffing guard as `ERR_SHIFT_FULLY_STAFFED` (§3.9) in its §2.7 precedence slot, so that a higher-precedence eligibility failure (such as a suspended worker) pre-empts it. Creating an assignment runs the full battery of scheduling checks described in §3.9 and §3.10, computes the assignment's `clopening_flag` and `provisional_cost_cents`, accrues any predictability premium, reconciles the pay-period, and — if this assignment makes the filled count reach the required count — bubbles the shift up to `FULLY_STAFFED`.

A worker confirms their own scheduled assignment. Confirmation is permitted only from `SCHEDULED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`), only by the owning worker whose `worker_id` equals `X-User-ID` (otherwise `ERR_UNAUTHORIZED`), and only while the current clock instant is still before the shift's `start_utc` (otherwise `ERR_SHIFT_ALREADY_STARTED`). Confirmation moves the assignment to `CONFIRMED` and changes no cost.

### 3.6. Cancelling Assignments and Handling No-Shows

A manager cancels an individual assignment, permitted only from `SCHEDULED` or `CONFIRMED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`) and only while the assignment's pay-period is `OPEN` (otherwise `ERR_PAY_PERIOD_LOCKED`). Cancellation moves the assignment to `CANCELLED`, removes it from the filled set so the parent shift may bubble down from `FULLY_STAFFED` to `OPEN`, and reconciles the pay-period to remove the assignment's provisional cost. If predictability pay is enabled and the gap between the shift's `start_utc` and the current clock is less than the advance-notice window, the system also appends a short-notice cancellation entry to the predictability ledger and reconciles the pay-period.

A manager marks a no-show on a worker who failed to appear, permitted only from `SCHEDULED` or `CONFIRMED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`) and only once the current clock instant has reached the shift's `start_utc` (otherwise `ERR_SHIFT_NOT_STARTED`). A no-show moves the assignment to `NO_SHOW` and triggers a cross-entity cascade: the worker's `no_show_strikes` is increased by one, and if that brings the count to three the worker's `status` becomes `SUSPENDED`; the assignment leaves the filled set, so the parent shift may bubble down from `FULLY_STAFFED` to `OPEN`; and the pay-period is reconciled to remove the assignment's provisional cost. A no-show does not itself accrue predictability pay.

### 3.7. Predictability Pay: Clopening and Short Notice

Predictability pay is the fair-workweek premium that accrues to a worker through append-only `PredictabilityLedgerEntry` records. Each entry names the `worker_id` it is owed to, the `shift_id` whose change triggered it, the `pay_period_id` it accrues into, a `reason`, and a positive `amount_cents`. The `reason` is one of `CLOPENING`, `SHORT_NOTICE_POST`, or `SHORT_NOTICE_CANCEL`. Every appended entry's amount feeds the pay-period's projected cost immediately. None of this accrues when the location has predictability pay disabled.

A clopening is evaluated whenever an assignment enters `SCHEDULED`. The system finds the worker's nearest prior assignment by shift end — the eligible prior assignment in `SCHEDULED`, `CONFIRMED`, or `COMPLETED` whose shift ends at or before the new shift's start, choosing the one with the latest shift end and breaking ties toward the most recently created. If there is no such prior assignment, the new assignment's `clopening_flag` is false. Otherwise the system computes the rest gap in hours between that prior shift's end and the new shift's start, and sets `clopening_flag` to true exactly when that gap is strictly less than the location's minimum rest hours; a gap equal to the threshold is not a clopening. When the flag is true and predictability pay is enabled, the system appends a clopening ledger entry whose amount is the fixed clopening penalty of five thousand cents.

Short-notice posting accrues when a shift that was first opened inside the advance-notice window is later staffed. The notice gap is the hours between the shift's `start_utc` and its `posted_utc`; the window is the location's advance-notice days converted to hours (its day count multiplied by twenty-four). The posting is short notice exactly when predictability pay is enabled and that notice gap is strictly less than the window. When a worker is then scheduled onto such a shift, a `SHORT_NOTICE_POST` entry accrues whose amount is the shift's duration in hours multiplied by the worker's base hourly rate, then multiplied by the short-notice-post rate of one quarter, with the result rounded half-up to whole cents. Short-notice cancellation accrues when a posted shift or one of its assignments is cancelled inside that same window; the `SHORT_NOTICE_CANCEL` entry's amount is the shift's duration in hours multiplied by the worker's base hourly rate, then multiplied by the short-notice-cancel rate of one half, rounded half-up to whole cents.

### 3.8. Assignment Cost: Provisional and Finalized

Each assignment carries two read-only cost fields. The `provisional_cost_cents` is the forward-looking estimate stamped when the assignment enters `SCHEDULED`; the `finalized_cost_cents` is the realized cost stamped when the assignment is completed, and is empty until then. Both split the assignment's shift hours into a regular portion and an overtime portion around the location's weekly overtime threshold, charge the regular portion at the worker's base rate and the overtime portion at the base rate times the overtime multiplier, and round the summed total half-up to whole cents exactly once. The two differ only in which of the worker's other hours form the baseline that decides where the overtime band begins.

For the provisional estimate, the baseline is the worker's already-scheduled pay-week hours: the sum of `duration_hours` over the worker's other assignments in the same pay-period that are in `SCHEDULED` or `CONFIRMED` (excluding this assignment, and excluding any in `NO_SHOW`, `CANCELLED`, or `COMPLETED`, and any in other pay-periods). Because the worker's shifts are stacked in order of `start_utc` ascending to decide which hours fall in the overtime band, that baseline sum counts only the worker's qualifying assignments whose shift is ordered strictly before this one — that is, whose shift `start_utc` is earlier, or equal with an earlier creation sequence; later-starting qualifying assignments are not part of this assignment's baseline. Consider the shift's hours as the next block stacked on top of that baseline: the regular hours are the overtime threshold minus the prior-week hours, clamped to lie between zero and the shift's hours, and the overtime hours are whatever of the shift's hours remain above that.

For the finalized cost, the baseline is realized rather than projected. Processing the worker's `COMPLETED` assignments in the same pay-period in order of shift `start_utc` ascending (breaking ties by `created_at` ascending), the running total of hours accumulated strictly before this assignment forms the baseline; the regular hours are again the threshold minus that running total clamped between zero and the shift's hours, and the rest are overtime. Because no-showed and cancelled assignments never complete, they contribute zero realized hours — so a worker who no-showed an earlier shift may fall below the overtime threshold and finalize cheaper than the provisional estimate had assumed.

### 3.9. Eligibility Checks at Scheduling Time

The two paths that create a new `SCHEDULED` assignment — direct assignment and the award of an open-shift bid — run the full eligibility battery below, in the precedence fixed in §2.7. The manager approval of a swap reuses these geometries but applies only the narrower subset spelled out in §3.12 (the minor-cap hard check, with clopening soft), not the suspended, worker-free, over-staffing, or guardrail checks. A worker whose `status` is `SUSPENDED` (that is, whose strike count has reached three) cannot be newly assigned, awarded, or allowed to bid; the attempt is rejected with `ERR_WORKER_SUSPENDED`. The worker must be free for the shift, judged under two distinct interval geometries. First, no other non-terminal assignment for the worker may overlap the shift, where overlap is judged on a half-open basis so that exact adjacency — one shift ending precisely as the next begins, a zero gap — is allowed. Second, no `UNAVAILABLE` availability window and no `APPROVED` time-off window may collide with the shift, where those windows are judged on a closed-interval basis so that merely touching a boundary instant is a collision. Either kind of conflict is rejected with `ERR_WORKER_UNAVAILABLE`.

Referential integrity ties the parties to one location: the worker being assigned, awarded, or bidding must belong to the same `location_id` as the shift, and in a swap the counter assignment must belong to the counterparty being asked to take the shift; a mismatch is rejected with `ERR_CROSS_LOCATION`. A shift already at its required headcount cannot take another worker — assigning or awarding when the filled count already equals the required count is rejected with `ERR_SHIFT_FULLY_STAFFED`.

For a worker flagged a minor, two independent hour caps are projected before the assignment is allowed, and both must hold. The daily projection sums the worker's `SCHEDULED` and `CONFIRMED` hours whose shift starts fall on the same location-local calendar day as the new shift, adds the new shift's hours, and the assignment is rejected if that daily total is strictly greater than the worker's daily cap. The weekly projection sums the worker's `SCHEDULED` and `CONFIRMED` hours across the new assignment's pay-period, adds the new shift's hours, and the assignment is rejected if that weekly total is strictly greater than the worker's weekly cap. A total exactly equal to a cap is allowed; only a strict excess violates. Either violation is reported as `ERR_MINOR_HOUR_CAP_EXCEEDED`.

### 3.10. The Overtime Cost Guardrail

Before a new scheduled assignment is committed — whether by direct assignment or by award — the system computes what the assignment's pay-period projected labor cost would become as if the assignment were already committed. A pay-period's projected cost is the sum of `provisional_cost_cents` over its assignments in `SCHEDULED` or `CONFIRMED`, plus the sum of `amount_cents` over every predictability-ledger entry in that pay-period. If the projected total computed with the new assignment included would be strictly greater than the location's `overtime_cost_guardrail_cents`, the assignment is refused with `ERR_OVERTIME_GUARDRAIL_EXCEEDED`. A manager who intends to exceed the ceiling may set `force_over_guardrail` to true on the assignment or award request to bypass this single check; the guardrail is the only check `force_over_guardrail` waives. A pay-period exposes its `projected_labor_cost_cents` as a read-only field reconciled on every assignment or ledger change.

### 3.11. Open-Shift Bidding and Awarding

A worker bids on an `OPEN` shift, optionally supplying a `seniority_score` (which defaults to zero); the bid records its `shift_id` and the bidder's `worker_id` and opens in `SUBMITTED` status. The four bid statuses are `SUBMITTED`, `AWARDED`, `REJECTED`, and `WITHDRAWN`. A worker may withdraw their own bid while it is still `SUBMITTED` (otherwise `ERR_INVALID_BID_STATE`) and only as the owning worker (else `ERR_UNAUTHORIZED`); withdrawal moves it to `WITHDRAWN` and removes it from contention.

A manager awards a seat to the winning bid. The shift must be `OPEN` (otherwise `ERR_INVALID_SHIFT_STATE`), the award must pass the optimistic-concurrency check on `expected_shift_version` described in §2.11 (`ERR_STALE_SHIFT_VERSION`), and the bid named by `bid_id` must in fact be the winner. The winner is selected among the shift's `SUBMITTED` bids only (`AWARDED`, `REJECTED`, and `WITHDRAWN` bids are excluded) by highest `seniority_score`, breaking ties toward the earliest `created_at`; the resource `id` is never used as a tie-break. A manager who names any other bid is rejected with `ERR_BID_NOT_WINNER`. Awarding the winner creates an assignment for that worker with `source` set to `BID` in `SCHEDULED` status — which runs the full scheduling battery of §3.9 and §3.10, computes its clopening flag and provisional cost, and accrues any predictability premium just as a direct assignment does — moves the winning bid to `AWARDED`, and increments the shift's `version` by one. If that new assignment makes the filled count reach the required count, the shift bubbles up to `FULLY_STAFFED`, and as part of that transition every bid still `SUBMITTED` on the shift is moved to `REJECTED`. Independently, whenever a shift becomes `FULLY_STAFFED` or `CANCELLED`, any still-`SUBMITTED` bid on it is closed as `REJECTED`.

### 3.12. Shift Swaps Between Workers

A worker initiates a swap to hand off one of their own assignments, supplying the `from_assignment_id` being given away and the `to_worker_id` asked to take it; the request opens in `PROPOSED` status with `decided_by_manager_id` empty and `counter_assignment_id` unset. The six swap statuses are `PROPOSED`, `COUNTERED`, `ACCEPTED`, `MANAGER_APPROVED`, `REJECTED`, and `CANCELLED`. The negotiation is deliberately cyclic and proceeds through worker actions before a final manager approval.

From `PROPOSED`, the counterparty may counter by offering one of their own assignments back, supplying `counter_assignment_id`. Countering is permitted only from `PROPOSED` (otherwise `ERR_INVALID_SWAP_STATE`), only by the counterparty whose `X-User-ID` equals `to_worker_id` (else `ERR_UNAUTHORIZED`), and only when the offered counter assignment belongs to the acting worker and is itself in `SCHEDULED` or `CONFIRMED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`); it records `counter_assignment_id` and moves the swap to `COUNTERED`. From `COUNTERED`, the initiator may repropose — permitted only from `COUNTERED`, only by the initiator (the worker of `from_assignment_id`, else `ERR_UNAUTHORIZED`) — which clears `counter_assignment_id` and returns the swap to `PROPOSED`, continuing the revision loop.

Acceptance moves the swap to `ACCEPTED` and is permitted from either `PROPOSED` or `COUNTERED` (otherwise `ERR_INVALID_SWAP_STATE`); when accepting from `PROPOSED` the acting worker must be the counterparty (`to_worker_id`), and when accepting from `COUNTERED` the acting worker must be the initiator accepting the counter — anyone else is rejected with `ERR_UNAUTHORIZED`. Acceptance mutates no assignment; it merely awaits manager approval. A party to the swap may reject it from `PROPOSED`, `COUNTERED`, or `ACCEPTED` (otherwise `ERR_INVALID_SWAP_STATE`; a non-party is `ERR_UNAUTHORIZED`), moving it to `REJECTED` with no assignment change. The initiator may cancel from `PROPOSED` or `COUNTERED` (otherwise `ERR_INVALID_SWAP_STATE`; only the initiator, else `ERR_UNAUTHORIZED`), moving it to `CANCELLED` with no assignment change.

A manager approves an accepted swap, permitted only from `ACCEPTED` (otherwise `ERR_INVALID_SWAP_STATE`), requiring the `from_assignment_id` to still be in `SCHEDULED` or `CONFIRMED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`), and requiring the receiving worker to pass the minor-cap hard check for the swapped shift — and, when a counter assignment is present, the original from-worker to likewise pass the minor-cap hard check for the counter shift, each computed as if the worker already held the assignment they are about to receive — a minor-cap violation on either side is rejected with `ERR_MINOR_HOUR_CAP_EXCEEDED`, while clopening here is soft and only sets the flag on each reassigned assignment. Both minor-cap checks are evaluated before any reassignment is committed. Approval drives a cross-entity cascade: the from-assignment's `worker_id` is reassigned to the `to_worker_id` and its `source` is set to `SWAP`; if a counter assignment is present, its `worker_id` is reassigned back to the original from-worker and its `source` is likewise set to `SWAP`; the `clopening_flag` and `provisional_cost_cents` of each reassigned assignment are recomputed; each affected pay-period is reconciled; and `decided_by_manager_id` is stamped with the approving manager. The swap moves to `MANAGER_APPROVED`.

### 3.13. Pay-Periods and Locking

A manager defines a `PayPeriod` for a location by supplying `start_utc` and `end_utc` (strictly after the start, aligned to a pay-week boundary); it belongs to its location via `location_id`, opens in `OPEN` status, and its window is half-open — it covers the start instant up to but not including the end. The two pay-period statuses are `OPEN` and `LOCKED`. An assignment's owning pay-period is the one whose half-open window contains the shift's start. While a pay-period is `OPEN`, the system keeps its read-only `projected_labor_cost_cents` reconciled on every assignment or ledger change as described in §3.10; its `finalized_labor_cost_cents` is empty until the period is locked.

A manager locks a pay-period, permitted only from `OPEN` (otherwise `ERR_PAY_PERIOD_LOCKED`), and only when every assignment whose pay-period is this one is already in a terminal state — `COMPLETED`, `NO_SHOW`, or `CANCELLED` (otherwise `ERR_OPEN_ASSIGNMENTS_EXIST`). Locking computes the period's `finalized_labor_cost_cents` as the sum of `finalized_cost_cents` over the `COMPLETED` assignments in the window plus the total of every predictability-ledger entry's amount in the window, and moves the period to `LOCKED`. Once locked, any further assignment mutation in the window — assigning, cancelling, awarding, or marking a no-show — is refused with `ERR_PAY_PERIOD_LOCKED`.

### 3.14. The Test-Driving Clock

Because every relative-time rule reads the server's logical clock rather than wall time, a manager-only test-driving capability sets that clock to a supplied instant, given as `to_iso8601`. Setting the clock requires authenticated headers like any other request but performs no resource mutation; thereafter all checks that compare against "now" — shift-started, shift-ended, confirmation-in-time, and the advance-notice window — read the new instant.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, including the lifecycle action endpoints, return `200 OK`. List and single-resource reads return `200 OK`. Each endpoint's request payload, response side effects, and business preconditions are described in the §3 workflows above; the table below is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/locations` | Create a location | Manager |
| GET | `/locations/{locId}` | Get a location | Manager, Worker |
| POST | `/locations/{locId}/workers` | Register a worker at a location | Manager |
| GET | `/locations/{id}/workers` | List a location's workers | Manager, Worker |
| GET | `/workers/{workerId}` | Get a worker | Manager, Worker |
| POST | `/workers/{workerId}/availability` | Add an availability/unavailability window | Manager, Worker |
| GET | `/workers/{id}/availability` | List a worker's availability windows | Manager, Worker |
| POST | `/workers/{workerId}/time-off` | Submit a time-off request | Worker |
| GET | `/workers/{id}/time-off` | List a worker's time-off requests | Manager, Worker |
| POST | `/locations/{locId}/time-off/{toId}/approve` | Approve a time-off request | Manager |
| POST | `/locations/{locId}/time-off/{toId}/deny` | Deny a time-off request | Manager |
| POST | `/locations/{locId}/time-off/{toId}/cancel` | Cancel own pending time-off request | Worker |
| POST | `/locations/{locId}/shift-templates` | Create a shift demand-forecast template | Manager |
| GET | `/locations/{id}/shift-templates` | List a location's shift templates | Manager, Worker |
| POST | `/locations/{locId}/shift-templates/{tplId}/generate` | Generate a DRAFT shift from a template | Manager |
| POST | `/locations/{locId}/shifts` | Create an ad-hoc DRAFT shift | Manager |
| GET | `/shifts` | List shifts, filterable by location and template | Manager, Worker |
| GET | `/shifts/{shiftId}` | Get a shift | Manager, Worker |
| POST | `/locations/{locId}/shifts/{shiftId}/post` | Post a DRAFT shift to OPEN | Manager |
| POST | `/locations/{locId}/shifts/{shiftId}/cancel` | Cancel a shift | Manager |
| POST | `/locations/{locId}/shifts/{shiftId}/complete` | Complete a shift after it ends | Manager |
| POST | `/locations/{locId}/shifts/{shiftId}/award` | Award an open shift to the winning bid | Manager |
| POST | `/locations/{locId}/assignments` | Directly assign a worker to an OPEN shift | Manager |
| GET | `/assignments` | List assignments, filterable by shift, worker, or pay-period | Manager, Worker |
| GET | `/assignments/{asgId}` | Get an assignment | Manager, Worker |
| POST | `/locations/{locId}/assignments/{asgId}/confirm` | Worker confirms own scheduled assignment | Worker |
| POST | `/locations/{locId}/assignments/{asgId}/cancel` | Manager cancels an assignment | Manager |
| POST | `/locations/{locId}/assignments/{asgId}/no-show` | Mark a started assignment as a no-show | Manager |
| POST | `/locations/{locId}/shifts/{shiftId}/bids` | Worker bids on an OPEN shift | Worker |
| GET | `/bids` | List open-shift bids, filterable by shift or worker | Manager, Worker |
| GET | `/bids/{bidId}` | Get an open-shift bid | Manager, Worker |
| POST | `/locations/{locId}/bids/{bidId}/withdraw` | Worker withdraws own submitted bid | Worker |
| POST | `/locations/{locId}/swaps` | Initiate a shift swap | Worker |
| GET | `/swaps` | List swap requests, filterable by from-assignment, to-worker, or counter-assignment | Manager, Worker |
| GET | `/swaps/{swapId}` | Get a swap request | Manager, Worker |
| POST | `/locations/{locId}/swaps/{swapId}/counter` | Counterparty counters with their own assignment | Worker |
| POST | `/locations/{locId}/swaps/{swapId}/repropose` | Initiator clears the counter and reproposes | Worker |
| POST | `/locations/{locId}/swaps/{swapId}/accept` | Accept the swap | Worker |
| POST | `/locations/{locId}/swaps/{swapId}/reject` | Reject the swap | Worker |
| POST | `/locations/{locId}/swaps/{swapId}/cancel` | Initiator cancels the swap | Worker |
| POST | `/locations/{locId}/swaps/{swapId}/approve` | Manager approves an accepted swap | Manager |
| POST | `/locations/{locId}/pay-periods` | Create a pay-period window | Manager |
| GET | `/locations/{id}/pay-periods` | List a location's pay-periods | Manager, Worker |
| GET | `/pay-periods/{ppId}` | Get a pay-period | Manager, Worker |
| POST | `/locations/{locId}/pay-periods/{ppId}/lock` | Lock a pay-period once all its assignments are terminal | Manager |
| GET | `/predictability-ledger` | List predictability-pay ledger entries, filterable by worker, shift, or pay-period | Manager, Worker |
| GET | `/predictability-ledger/{ledgerId}` | Get a predictability-pay ledger entry | Manager, Worker |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_INVALID_SHIFT_STATE` | 409 |
| `ERR_INVALID_ASSIGNMENT_STATE` | 409 |
| `ERR_INVALID_BID_STATE` | 409 |
| `ERR_INVALID_SWAP_STATE` | 409 |
| `ERR_INVALID_TIME_OFF_STATE` | 409 |
| `ERR_SHIFT_NOT_ENDED` | 409 |
| `ERR_SHIFT_NOT_STARTED` | 409 |
| `ERR_SHIFT_ALREADY_STARTED` | 409 |
| `ERR_PAY_PERIOD_LOCKED` | 409 |
| `ERR_OPEN_ASSIGNMENTS_EXIST` | 409 |
| `ERR_STALE_SHIFT_VERSION` | 412 |
| `ERR_BID_NOT_WINNER` | 409 |
| `ERR_CROSS_LOCATION` | 409 |
| `ERR_WORKER_SUSPENDED` | 409 |
| `ERR_WORKER_UNAVAILABLE` | 409 |
| `ERR_MINOR_HOUR_CAP_EXCEEDED` | 409 |
| `ERR_SHIFT_FULLY_STAFFED` | 409 |
| `ERR_OVERTIME_GUARDRAIL_EXCEEDED` | 409 |
| `ERR_TIME_OFF_CONFLICTS_ASSIGNMENT` | 409 |
