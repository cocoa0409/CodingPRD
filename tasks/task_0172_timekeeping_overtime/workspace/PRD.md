# Timekeeping & Overtime API — Product Requirements Document

## 1. Introduction

Wage-and-hour litigation costs U.S. employers billions annually, and the most common root cause is not bad faith but bad bookkeeping: punches that drift, meal breaks that go unrecorded, daily and weekly overtime thresholds that interact in ways the operator never anticipated, and edits to historical time records that arrive without an audit trail. The Timekeeping & Overtime API is the system of record for hourly labor at multi-state employers operating across both federal-only jurisdictions and California, where daily overtime and double-time rules layer on top of the federal 40-hour weekly threshold. It tracks every clock event for non-exempt employees, recomputes pay whenever a time edit lands, applies the tipped-wage rules for staff paid on a subminimum cash wage plus tips, and freezes every workweek behind an explicit lock once payroll runs.

The product organizes work around three roles with deliberately segregated duties: hourly workers who punch and may dispute their own records, front-line supervisors who schedule and approve routine edits, and payroll administrators who finalize shifts, approve fraud-correction edits, revert approved edits when an error is found, and lock the workweek. Compliance pressure runs through every workflow — the same edit that fixes a missed punch is also an audit event, the same finalize that posts pay is also the moment overtime tiers crystalize, and the same lock that closes payroll is also the gate that stops further mutation. The PRD that follows specifies the resources, calculations, validations, and state transitions that this system must implement to be defensible under audit.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (with the sole exception of any health probe) must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting under. Absence of either header is a hard rejection with `ERR_AUTH_REQUIRED` and HTTP status 401. A header value for `X-User-Role` that is not one of the three recognized role names is rejected with `ERR_INVALID_ROLE`, also 401. A well-formed authentication that nonetheless lacks permission for the requested operation — either because the role is not authorized for the endpoint at all, or because the principal does not own the resource being acted upon — is rejected with `ERR_FORBIDDEN` and HTTP status 403.

The three recognized roles are `Employee`, `Supervisor`, and `PayrollAdmin`.

When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee` record; ownership checks on any resource that references an employee compare the resource's `employee_id` field to `X-User-ID`. An `Employee` may punch only against shifts whose `employee_id` matches their own user id, may submit a `TimeEdit` only against their own shifts, may read only their own shifts and workweeks, and may declare tips only on their own shifts.

When `X-User-Role` is `Supervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on `TimeEdit.requested_by_user_id` (and on `AuditEntry.actor_user_id`) when a supervisor takes an action, but does not compare it to any entity's `id`. A `Supervisor` may schedule and void shifts, punch on behalf of an employee they cover, submit time edits, and approve or reject time edits whose `reason_code` is not `FRAUD_CORRECTION`. Supervisors are restricted to employees within their span of coverage; a supervisor acting on an out-of-scope employee receives `ERR_FORBIDDEN`.

When `X-User-Role` is `PayrollAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and is recorded on the same audit and edit fields. A `PayrollAdmin` has unrestricted ownership and is the only role permitted to create employees, patch employees, finalize shifts, approve `FRAUD_CORRECTION` time edits, revert approved time edits, lock workweeks, read the audit log, and drive the test-only clock.

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

Every list endpoint accepts two query parameters: `limit`, defaulting to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100; and `offset`, defaulting to 0, which skips that many records before returning the page. The default sort order on every list endpoint is by `created_at` ascending (oldest first). The list endpoint's response envelope populates `meta.limit`, `meta.offset`, `meta.total_count` (total matching records in the entire collection), and `meta.has_more` (true when more records remain beyond the current page).

### 2.4. Common Resource Properties

Resources of type `Employee`, `Shift`, `TimeEdit`, `TipDeclaration`, and `Workweek` are mutable and carry four common properties on every read: `id` is a server-minted UUID string with no domain prefix; `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, with `created_at` set on insertion and `updated_at` refreshed on every mutation; and `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation. Resources of type `Punch`, `MealBreak`, `DetentionEvent`, and `AuditEntry` are append-only event records — they carry only `id` and `created_at`; neither `updated_at` nor `version` is present on them, because they are never mutated in place (a `Punch` is replaced by an EDIT punch rather than rewritten, and audit rows are immutable by definition).

### 2.5. Optimistic Concurrency Control

The mutation endpoints that accept a body — specifically, employee patch and shift patch where supported — accept an optional `version` field. If the caller supplies a `version` value and it does not match the current persisted `version` of the target resource, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP status 409. If the caller omits the `version` field, the OCC check is skipped and the mutation proceeds. Successful mutations increment `version` by exactly 1 and refresh `updated_at`.

### 2.6. Money and Time Precision

All monetary amounts in this system are stored and returned as integer whole cents — fields ending in `_cents` (such as `base_hourly_rate_cents`, `tipped_cash_rate_cents`, `applicable_minimum_wage_cents`, `meal_break_premium_owed_cents`, `premium_owed_cents`, `declared_tips_cents`, `tip_credit_applied_cents`, `shortfall_topup_cents`, and `gross_pay_cents`) are never fractional. Whenever a calculation produces a fractional cent value as an intermediate result, the value is rounded to the nearest whole cent using the half-up convention (a fractional component of exactly one half rounds away from zero). Hours, by contrast, are kept at full floating-point precision during accumulation across a workweek and are rounded only at the moment they are multiplied into a cents line.

All timestamps in this system are ISO 8601 UTC with three fractional second digits. The server stamps `punched_at` on every punch at the moment it receives the request — punches never trust caller-supplied timestamps. The server also exposes a logical clock for test-driving purposes (see §3.7); production deployments should disable that capability.

### 2.7. Recompute and Cascade Semantics

This system treats the workweek as a derived view over its constituent shifts, and a shift as a derived view over its constituent punches and breaks. Whenever a punch is added, a meal break is closed, an approved edit lands, or an approved edit is reverted, the affected `Shift`'s computed columns — `detention_minutes`, `meal_break_premium_owed_cents`, `actual_end` — are recomputed in place. When the affected shift has already been finalized, the cascade reaches the owning `Workweek`: the approved edit flips the workweek from `POSTED` back to `OPEN`, and the shift itself drops from `FINALIZED` back to `CLOSED`, awaiting a fresh finalize that will re-run the workweek pay engine. Both `updated_at` and `version` are refreshed on the affected resources whenever a recompute writes new values, with a single exception: if the recompute produces values byte-identical to what was already stored, `version` and `updated_at` are still bumped because the recompute event itself is what the system records, not the data delta.

Once a `Workweek` is `LOCKED`, recompute is forbidden. Approve, revert, and finalize all reject with `ERR_WORKWEEK_LOCKED` for any shift whose workweek is locked.

### 2.8. Nested Resource Resolution

Endpoints whose URL contains nested path segments — for example, the punch-recording endpoint nested under a shift, or the tip-declaration endpoint nested under a shift, or the approve/reject/revert endpoints nested under a time-edit id — resolve their path parameters from left to right. The outer id is resolved first; if it does not exist, the response is `ERR_RESOURCE_NOT_FOUND` (404) regardless of whether the inner id would also have been valid. Ownership checks happen after existence checks, so an `Employee` requesting a shift that belongs to someone else receives `ERR_FORBIDDEN` (403), not `ERR_RESOURCE_NOT_FOUND`.

### 2.9. Validation Priority

Validations are evaluated in a fixed priority order, and the first failing check produces the response. The order, from highest to lowest priority, is: authentication header presence (`ERR_AUTH_REQUIRED`), then role-value validity (`ERR_INVALID_ROLE`), then RBAC permission for the endpoint (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_RESOURCE_NOT_FOUND`), then ownership (`ERR_FORBIDDEN`), then shift-state checks (`ERR_SHIFT_INVALID_STATE`), then time-edit-state checks (`ERR_TIME_EDIT_NOT_PENDING`), then workweek-lock checks (`ERR_WORKWEEK_LOCKED`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the fraud-requires-admin check (`ERR_FRAUD_REQUIRES_ADMIN`), then the exempt-not-eligible check (`ERR_EXEMPT_NOT_ELIGIBLE`), then punch-ordering (`ERR_PUNCH_OUT_OF_ORDER`), then meal-break-duplicate (`ERR_MEAL_BREAK_DUPLICATE`), then punch-window (`ERR_PUNCH_OUTSIDE_WINDOW`), then time-edit-range (`ERR_TIME_EDIT_OUT_OF_RANGE`), then workweek-anchor (`ERR_WORKWEEK_BAD_ANCHOR`), then tipped-fields-mismatch (`ERR_TIPPED_FIELDS_MISMATCH`), then tips-not-applicable (`ERR_TIPS_NOT_APPLICABLE`), then below-minimum-wage (`ERR_BELOW_MINIMUM_WAGE`), then OCC version (`ERR_VERSION_CONFLICT`), then idempotency-key (`ERR_DUPLICATE_IDEMPOTENCY_KEY`). When two validations produce different `error_id`s for the same request, the higher-priority one wins. Generic schema validation (missing required field, malformed enum value, malformed timestamp) returns `ERR_INVALID_INPUT` with HTTP status 422 and slots into the existence-tier of the priority order — after auth but before any state check.

### 2.10. Concurrency Serialization

The system serializes four race scenarios with first-writer-wins semantics. When two `IN` punches arrive simultaneously on the same shift in state `SCHEDULED`, exactly one wins the `SCHEDULED → OPEN` transition and the other observes a non-`SCHEDULED` shift state, receiving `ERR_SHIFT_ALREADY_OPEN` with HTTP status 409. When approve and reject are dispatched simultaneously against the same `PENDING` time edit, exactly one transitions the edit and the loser sees a non-`PENDING` state, receiving `ERR_TIME_EDIT_NOT_PENDING` with HTTP status 409. When a workweek lock is issued concurrently with a time-edit approval against one of its shifts, exactly one of the two operations succeeds and the other observes either a frozen workweek or a non-`PENDING` edit, receiving `ERR_WORKWEEK_LOCKED` with HTTP status 409. Finally, when two `POST /timekeeping/time-edits` calls arrive with the same `idempotency_key` against the same shift, the first creates a new `TimeEdit` row and a second call carrying an identical payload returns the already-existing row (idempotent replay, 201 with the original resource); a second call whose payload differs in any input field — `target_punch_id`, `proposed_punched_at`, or `reason_code` — is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY` and HTTP status 409.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Employee

An employee record is the system's anchor for every downstream calculation, and the payroll administrator is the only role permitted to bring one into existence. The create payload carries the employee's legal name in `full_name` (1 to 120 characters), the governing jurisdiction `jurisdiction` whose value must be one of `CA` or `FED`, the FLSA classification `classification` whose value must be one of `EXEMPT` or `NON_EXEMPT`, and the regular hourly wage `base_hourly_rate_cents`. The `base_hourly_rate_cents` is required when `classification` is `NON_EXEMPT` and must be at least 725 (the federal minimum wage in whole cents); for `EXEMPT` employees the field is ignored because exempt staff do not draw hourly pay through this system. Whether an employee customarily earns tips is captured in the boolean `tipped_role`, which defaults to false when omitted.

A tipped employee — one for whom `tipped_role` is true — must also supply `tipped_cash_rate_cents`, the direct cash wage paid before tip credit, and `applicable_minimum_wage_cents`, the full state minimum wage that the tip credit is required to close the gap to. The cash rate must be at least 213 (the federal tipped minimum in whole cents) and the applicable minimum wage must be at least 725. A non-tipped employee must not supply either tipped field; supplying tipped fields on a non-tipped employee, or omitting them on a tipped employee, is rejected with `ERR_TIPPED_FIELDS_MISMATCH`. The configuration-time wage floor check requires that for a tipped employee the sum of `tipped_cash_rate_cents` plus a per-hour tip share could in principle reach `applicable_minimum_wage_cents`; configurations that make this impossible are rejected with `ERR_BELOW_MINIMUM_WAGE`. The HR `status` of a newly created employee is system-set to `ACTIVE`; the alternative value `TERMINATED` is reachable only through a subsequent patch by a payroll administrator. Only employees in `status` `ACTIVE` may produce punches.

Employee updates are likewise restricted to the payroll administrator and accept the same fields plus the optional `status` and `version` for optimistic concurrency. Patching an employee's classification, jurisdiction, or rate affects only future shifts; historical `FINALIZED` workweeks are not retroactively recomputed.

### 3.2. Scheduling, Punching, and Closing a Shift

A `Shift` represents one continuous block of work that an `Employee` is expected to perform, anchored to a planned `scheduled_start` and `scheduled_end` (both ISO 8601 UTC). Scheduling is performed by a supervisor or payroll administrator; the payload carries the `employee_id`, `scheduled_start`, and `scheduled_end`, and the system enforces `scheduled_end` strictly later than `scheduled_start`. A shift created for an employee whose `classification` is `EXEMPT` is rejected with `ERR_EXEMPT_NOT_ELIGIBLE` and HTTP status 422 — exempt employees do not draw hourly time through this system. A newly scheduled shift enters initial state `SCHEDULED`. A supervisor or payroll administrator may void a shift while it is still in `SCHEDULED` and no punch has yet been recorded against it, transitioning it to terminal state `VOIDED`; an attempt to void a shift in any other state, or one against which punches already exist, is rejected with `ERR_SHIFT_INVALID_STATE`.

The shift carries computed columns that the system fills as punches arrive: `actual_start` is stamped when the first `IN` punch lands (and is null on a `SCHEDULED` shift), `actual_end` is stamped when the closing `OUT` punch lands, `state` tracks the lifecycle, `workweek_id` is the foreign-key handle to the `Workweek` bucket the shift's hours roll into (assigned at the moment of the first punch from the UTC Sunday 00:00:00.000 that anchors that calendar week), `requires_meal_break` is derived true when the expected worked hours exceed 5.0 (a California and non-exempt rule), `meal_break_premium_owed_cents` carries the premium owed if the meal break is missed or short, and `detention_minutes` carries the minutes the actual end ran past the scheduled end.

Punches are recorded against the shift one at a time. Each punch carries `shift_id`, a denormalized `employee_id` retained for audit query convenience, and `punch_type` whose value must be one of `IN`, `OUT`, `MEAL_OUT`, or `MEAL_IN`. The server stamps `punched_at` at the moment of request receipt and never accepts a caller-supplied value for it; time edits are how punches change after the fact. Each punch also records its `source`, defaulting to `TIMECLOCK` for live punches and set to `EDIT` only for punches the system creates when an approved time edit applies. A punch that has been retired by an approved edit retains its row for audit and carries `superseded_by_edit_id` pointing back to the time edit that retired it.

The lifecycle of a shift is driven by these punches. The first `IN` punch transitions `SCHEDULED → OPEN`, stamps `actual_start`, assigns `workweek_id`, and is permitted only when the acting employee's `status` is `ACTIVE`, the employee's `classification` is `NON_EXEMPT`, the `punch_type` is `IN`, and the current server time falls within a window extending from 60 minutes before `scheduled_start` through 60 minutes after `scheduled_end` — an `IN` punch outside that window is rejected with `ERR_PUNCH_OUTSIDE_WINDOW`. An `IN` punch on a shift that has already transitioned out of `SCHEDULED` is rejected with `ERR_SHIFT_ALREADY_OPEN`. The closing `OUT` punch transitions `OPEN → CLOSED`, stamps `actual_end`, and is only permitted when any preceding `MEAL_OUT` already has its matching `MEAL_IN` (a dangling meal break blocks the close). Punch ordering is policed against the canonical sequence `IN` then optionally `MEAL_OUT` then `MEAL_IN` then `OUT`, with no second `IN` allowed after the `OUT` has landed; violations are rejected with `ERR_PUNCH_OUT_OF_ORDER`. At most one `MEAL_OUT`/`MEAL_IN` pair is permitted per shift, and a second `MEAL_OUT` is rejected with `ERR_MEAL_BREAK_DUPLICATE`. Punches against a shift in `FINALIZED` or `VOIDED` are rejected with `ERR_SHIFT_INVALID_STATE`.

When the `OUT` punch transitions the shift to `CLOSED`, two computations run inline on that shift: the detention computation, and the meal-break-premium computation. Both are described below.

### 3.3. Meal Breaks and the Meal-Break Premium

A `MealBreak` represents the unpaid 30-minute (or longer) break that California and many other jurisdictions require for shifts longer than five worked hours. Exactly one `MealBreak` row exists per shift that has one; it carries `shift_id`, the foreign-key pointer `meal_out_punch_id` to the `MEAL_OUT` punch that opens the break, the pointer `meal_in_punch_id` to the `MEAL_IN` punch that closes it, the computed `duration_minutes` (the difference between `MEAL_IN.punched_at` and `MEAL_OUT.punched_at` truncated to whole minutes), and the computed boolean `taken_before_fifth_hour`. `taken_before_fifth_hour` is true if and only if the `MEAL_OUT.punched_at` is at or before `actual_start` plus 5 hours (18000 seconds), and `duration_minutes` is at least 30; otherwise it is false.

The meal-break-premium calculation runs whenever the shift transitions `OPEN → CLOSED` and again on every recompute triggered by an approved or reverted time edit. It begins by deriving the shift's worked hours as the difference between `actual_end` and `actual_start`, minus the meal-break duration if one was taken, converted to hours. If the employee's `classification` is `EXEMPT`, or the worked hours are at most five, the premium is zero. Otherwise, if no `MealBreak` row exists for the shift, or one exists but its `duration_minutes` is less than 30, the premium is one hour at the employee's base rate — that is, `base_hourly_rate_cents` rounded to whole cents using the half-up convention (the rounding step is degenerate here because `base_hourly_rate_cents` is already an integer, but the rule is stated explicitly so the same code path generalizes). If a `MealBreak` row exists with sufficient duration but `taken_before_fifth_hour` is false (the break was taken too late), the premium is again one hour at the base rate. Only when a sufficient-duration meal break was taken before the fifth hour of work is the premium zero. The result is written into `Shift.meal_break_premium_owed_cents`.

### 3.4. Shift Detention

When the worked time overruns the originally scheduled end, the system pays a tiered detention premium. A `DetentionEvent` is created (or updated) per shift on the `OPEN → CLOSED` transition and on every recompute. It carries `shift_id`, the computed `minutes_past_scheduled_end`, the computed `premium_owed_cents`, and the computed `tier` whose value must be one of `NONE`, `TIER_1`, `TIER_2`, or `TIER_3`.

The detention calculation is as follows. Compute the raw difference `actual_end` minus `scheduled_end` in seconds; if it is negative, the result is zero. Otherwise, divide by 60 and round up to the next whole minute (a partial minute counts in full). The greater of that value and zero is `minutes_past_scheduled_end` and is also written into `Shift.detention_minutes`. The `tier` is then assigned by a threshold lookup: when `minutes_past_scheduled_end` is below 15, the tier is `NONE`; when it is at least 15 but below 60, the tier is `TIER_1`; when it is at least 60 but below 120, the tier is `TIER_2`; when it is at least 120, the tier is `TIER_3`. The `premium_owed_cents` follows from the tier: `NONE` pays zero; `TIER_1` pays one half of `base_hourly_rate_cents` (equivalent to thirty minutes at half-rate), rounded half-up to whole cents; `TIER_2` pays one full `base_hourly_rate_cents` (one hour at base), rounded half-up to whole cents; `TIER_3` pays two times `base_hourly_rate_cents` (two hours at base), rounded half-up to whole cents.

The detention rules carry a single variant: for an employee whose `classification` is `EXEMPT`, the calculation is bypassed entirely — `tier` is forced to `NONE` and `premium_owed_cents` is forced to zero regardless of `minutes_past_scheduled_end`. (In practice, exempt employees never produce shifts in the first place, but the variant is stated explicitly so any administrative path that ends up generating a detention computation against an exempt employee yields the correct zero.)

### 3.5. Time Edits and Disputes

A `TimeEdit` is the audited mechanism by which a punch's effective `punched_at` is altered after the fact. Anyone (an employee on their own shift, a supervisor on a covered shift, or a payroll administrator on any shift) may submit one by posting the `shift_id`, the `target_punch_id` of the punch being edited (which must belong to the named shift), the `proposed_punched_at` (the new effective timestamp), the `reason_code` whose value must be one of `CLERICAL`, `MISSED_PUNCH`, `EQUIPMENT_FAILURE`, or `FRAUD_CORRECTION`, and an `idempotency_key` of 1 to 64 characters that is unique within `shift_id`. The system records `requested_by_user_id` (the submitter's `X-User-ID`) and `requested_by_role` (their `X-User-Role` at submission time) into the new row; `approved_by_user_id` and `applied_at` are null at submission and populated only when the edit is approved. The `state` of a fresh time edit is `PENDING`.

The `proposed_punched_at` must lie within the window from 4 hours before the shift's `scheduled_start` to 6 hours after the shift's `scheduled_end`; anything outside is rejected with `ERR_TIME_EDIT_OUT_OF_RANGE`. Submitting a time edit against an `OPEN` shift transitions that shift to `DISPUTED`, blocking further punches until the edit resolves; submitting one against a `CLOSED` shift likewise transitions it to `DISPUTED`, holding it back from being finalized. Submitting a time edit against a `FINALIZED` shift does not change the shift's state at submission time — the shift is held in `FINALIZED` until the moment the edit is approved, at which point the approval flips the shift back to `CLOSED` and the workweek back to `OPEN` (see §3.6).

Two operations resolve a `PENDING` time edit. Approving by posting to the time-edit approval action transitions the edit `PENDING → APPROVED`, and is allowed only when the approver's `X-User-ID` does not equal `requested_by_user_id` (segregation of duties — same person rejects with `ERR_SEGREGATION_OF_DUTIES`), the workweek is not `LOCKED`, the shift's `state` is one of `OPEN`, `DISPUTED`, `CLOSED`, or `FINALIZED`, and if the `reason_code` is `FRAUD_CORRECTION` the approver's role is `PayrollAdmin` (a supervisor approving a fraud-correction edit is rejected with `ERR_FRAUD_REQUIRES_ADMIN`). On approval, the system creates a new EDIT punch whose `punched_at` equals the `proposed_punched_at` and whose `source` is `EDIT`, sets the target punch's `superseded_by_edit_id` to the time edit's id, stamps `applied_at` with the server's now, records `approved_by_user_id` as the approver's `X-User-ID`, and recomputes `Shift.detention_minutes` and `Shift.meal_break_premium_owed_cents`. The shift then transitions out of `DISPUTED` back to its prior productive state — typically `CLOSED` — and an audit row is appended with `action` value `TIME_EDIT_APPROVED`. Rejecting by posting to the time-edit reject action transitions the edit `PENDING → REJECTED`, returns the shift to its pre-`DISPUTED` state, and appends an audit row with `action` value `TIME_EDIT_REJECTED`; the segregation-of-duties rule still applies on the reject path — the approver's `X-User-ID` must not equal `requested_by_user_id`. The `REJECTED` state is terminal.

Reverting an already-approved time edit is a payroll-administrator capability that transitions the edit `APPROVED → REVERTED`. It is permitted only when the workweek is not `LOCKED`. The revert removes the EDIT punch, clears `superseded_by_edit_id` on the originally edited target punch (restoring it as the live record), recomputes detention and meal-break premium on the affected shift, and, if the shift was `FINALIZED` at the time the original approval landed, flips the shift back to `CLOSED` and the workweek back to `OPEN`. An audit row is appended with `action` value `TIME_EDIT_REVERTED`, and the `REVERTED` state is terminal. Approve, reject, and revert called against a time edit whose state is not the required pre-transition state are rejected with `ERR_TIME_EDIT_NOT_PENDING` (for approve and reject) or with the same code generalized to mean "not in the expected state" for revert.

The `idempotency_key` deserves separate emphasis. The first submission with a given (`shift_id`, `idempotency_key`) creates a new `TimeEdit` row and returns it. A second submission carrying the same key and a byte-identical input payload returns the originally created row — the operation is treated as a retry and produces the same 201 with the same id. A second submission carrying the same key but any difference in `target_punch_id`, `proposed_punched_at`, or `reason_code` is rejected with `ERR_DUPLICATE_IDEMPOTENCY_KEY` because the key is being reused with a conflicting intent.

### 3.6. Finalization, the Workweek, and the Pay Engine

The `Workweek` is the aggregation bucket that the FLSA's 40-hour overtime threshold applies to. It is anchored to a particular employee in `employee_id` and a particular `week_start` that must be exactly the Sunday 00:00:00.000 UTC of the week — a workweek created (or upserted) with any other anchor is rejected with `ERR_WORKWEEK_BAD_ANCHOR`. The workweek's `payroll_status` starts as `OPEN`, transitions to `POSTED` when every constituent shift has reached `FINALIZED`, and transitions to `LOCKED` only when a payroll administrator explicitly locks it. The workweek carries `total_hours`, `regular_hours`, `overtime_hours`, `double_time_hours`, and `gross_pay_cents`, all computed by the pay engine.

Finalization is a payroll-administrator operation that takes a shift in state `CLOSED` and transitions it to `FINALIZED`. Finalize is permitted only when the shift is in `CLOSED`, the owning workweek is not `LOCKED`, and there are no `PENDING` time edits against the shift — a `PENDING` edit on the shift causes finalize to reject with `ERR_TIME_EDIT_NOT_PENDING`. On finalize, the workweek pay engine runs across every `FINALIZED` shift in the same (`employee_id`, `week_start`), an audit row is appended with `action` value `SHIFT_FINALIZED`, and if every sibling shift in the workweek is now `FINALIZED`, the workweek transitions `OPEN → POSTED` automatically. `DISPUTED` and `VOIDED` shifts are excluded from the pay engine's inputs.

The pay engine operates in four steps. **Step 1 — per-day worked hours.** For each `FINALIZED` shift in the workweek, the system identifies the UTC calendar day the shift started on (by truncating `actual_start` to the start of its UTC day), computes the shift's worked seconds as `actual_end` minus `actual_start` minus the meal-break duration in seconds (zero if no meal break was taken), and accumulates that into a per-day total in hours (worked_seconds divided by 3600). `total_hours` for the workweek is the sum of all per-day totals.

**Step 2 — California daily buckets.** When the employee's `jurisdiction` is `CA`, each day's hours are split into three buckets: the daily-regular bucket is the lesser of 8 hours and the day's total; the daily-overtime bucket is the part of the day's hours above 8 but at or below 12 (so it can be at most 4 hours per day); the daily-doubletime bucket is the part of the day's hours strictly above 12. When the employee's `jurisdiction` is `FED`, no daily carve happens: the day's full total goes into the daily-regular bucket, and the daily-overtime and daily-doubletime buckets are zero for every day. (This is the federal-only variant: identical raw punches in `CA` versus `FED` will produce different `gross_pay_cents`, and that divergence is intentional.)

**Step 3 — federal weekly overtime.** The system then walks the calendar days from Sunday through Saturday in order. It maintains a running cumulative count of regular hours so far. For each day, it takes the daily-regular bucket from Step 2 and splits it: the amount that fits under the remaining capacity to 40 hours (40 minus cumulative_regular_so_far, floored at zero) is classified as regular, and the remainder of the day's daily-regular bucket spills into federal weekly overtime. The cumulative running total then advances by the regular amount classified for that day. After all seven days are processed, `regular_hours` for the workweek is the total classified as regular, and `overtime_hours` for the workweek is the sum of federal weekly overtime accumulated plus the sum across days of the daily-overtime bucket from Step 2. `double_time_hours` for the workweek is the sum across days of the daily-doubletime bucket from Step 2 — which is zero whenever `jurisdiction` is `FED`. This ordering matters: federal weekly overtime is applied only to the daily-regular bucket, never to hours already carved off as daily-overtime or daily-doubletime, so the engine never double-counts an hour as both daily-overtime and weekly-overtime.

**Step 4 — gross pay.** The system computes four cents lines, each rounded half-up to whole cents before being summed: the base line is `regular_hours` multiplied by `base_hourly_rate_cents`, rounded; the overtime line is `overtime_hours` multiplied by `base_hourly_rate_cents` multiplied by 1.5, rounded; the doubletime line is `double_time_hours` multiplied by `base_hourly_rate_cents` multiplied by 2.0, rounded; and the premiums line is the sum across the workweek's shifts of `Shift.meal_break_premium_owed_cents` plus the sum across the workweek's `DetentionEvent` rows of `premium_owed_cents`. To these is added the tip-credit topup, which is the sum across the workweek's `TipDeclaration` rows of `shortfall_topup_cents` (computed in §3.8). The five components — base line, overtime line, doubletime line, premiums, and tip topup — are summed into `Workweek.gross_pay_cents`. Hours remain at full floating-point precision through Steps 1 to 3 and are rounded only at Step 4's per-line conversions to cents.

When an approved time edit causes a constituent shift to recompute after the workweek has already reached `POSTED`, the workweek automatically flips `POSTED → OPEN`, the recomputed shift drops `FINALIZED → CLOSED`, and downstream consumers may not assume `gross_pay_cents` is stable until a fresh finalize runs the engine again. The same automatic flip occurs on revert.

Locking is the irreversible payroll cut. A payroll administrator locks a workweek when its `payroll_status` is `POSTED` and no `PENDING` time edits exist on any constituent shift; the transition `POSTED → LOCKED` freezes the workweek and appends an audit row with `action` value `WORKWEEK_LOCKED`. Once locked, further time-edit approvals on the workweek's shifts are rejected with `ERR_WORKWEEK_LOCKED`, finalize is rejected with the same code, and revert is likewise rejected.

### 3.7. Tip Declarations and the Tip-Credit Shortfall

For employees whose `tipped_role` is true, the system tracks one `TipDeclaration` per shift carrying `shift_id`, `declared_tips_cents` (the employee's declared tips for the shift, at least zero), `tip_credit_applied_cents` (computed), and `shortfall_topup_cents` (computed). At most one `TipDeclaration` may exist per shift; declarations submitted for a non-tipped employee, or carrying a negative `declared_tips_cents`, are rejected with `ERR_TIPS_NOT_APPLICABLE`.

The tip-credit shortfall calculation runs at the moment the shift transitions `CLOSED → FINALIZED`. For that shift it derives worked hours (the same `actual_end` minus `actual_start` minus meal-break-seconds, divided by 3600, as in the pay engine). It then computes two intermediate cents values, each individually rounded half-up to whole cents: the `cash_wage_cents` for the shift is worked hours multiplied by `tipped_cash_rate_cents`, rounded; the minimum-wage-required for the shift is worked hours multiplied by `applicable_minimum_wage_cents`, rounded. The `tip_credit_applied_cents` is the lesser of `declared_tips_cents` and the gap between minimum-wage-required and cash-wage (floored at zero). The `shortfall_topup_cents` is the gap between minimum-wage-required and the sum of cash-wage and `tip_credit_applied_cents`, floored at zero — that is, when declared tips do not bring the employee up to the applicable minimum wage for the worked hours, the employer makes up the difference, and that make-up amount lands in `shortfall_topup_cents`.

The order in which rounding happens is significant and is pinned: both `cash_wage_cents` and minimum-wage-required are rounded to whole cents **first**, and then the subtraction happens. An alternative algorithm that subtracts the per-hour rates first and rounds once at the end (the "sum-then-round" variant) can differ by one cent for non-integer worked hours; the per-line-rounding ordering described here is authoritative, and implementations that produce the sum-then-round result will fail the tip-credit assertion. The result `shortfall_topup_cents` flows into the workweek pay engine's tip-topup component (see §3.6, Step 4) when the workweek is recomputed.

### 3.8. The Audit Trail and the Test Clock

Every state-changing action on `Shift`, `TimeEdit`, and `Workweek` produces an immutable `AuditEntry`. The entry carries `actor_user_id` (the `X-User-ID` of the actor whose action produced the audit), `actor_role` (their role at action time, whose value must be one of `Employee`, `Supervisor`, or `PayrollAdmin`), `action` (one of `TIME_EDIT_SUBMITTED`, `TIME_EDIT_APPROVED`, `TIME_EDIT_REJECTED`, `TIME_EDIT_REVERTED`, `SHIFT_FINALIZED`, or `WORKWEEK_LOCKED`), `subject_entity` (the entity whose state changed, whose value must be one of `Shift`, `TimeEdit`, or `Workweek`), `subject_id` (the id of the subject), and two free-form JSON snapshot objects, `before_snapshot` and `after_snapshot`, capturing the relevant fields prior to and after the action. Only the payroll administrator may read the audit log.

A test-driving capability is exposed for the benchmark harness to reach time-gated states without waiting in real-time. A clock-advance capability accepts an integer `seconds` field and shifts the server's logical now by that many seconds; a clock-set capability accepts an ISO 8601 timestamp `now` and sets the server's logical now to that instant. Both capabilities are restricted to the payroll administrator and affect every time-dependent rule downstream — the punch window, the time-edit range window, the detention computation, and any timestamp the server stamps. Production deployments should disable these capabilities.

## 4. Endpoint Definitions

All endpoints are mounted under the `/timekeeping` prefix. New resources are created with HTTP 201; mutations of existing resources return 200; the void operation on a `SCHEDULED` shift returns 204; every read returns 200. Path parameters are resolved left to right, and absent path resources are reported as `ERR_RESOURCE_NOT_FOUND` (404) before any ownership or state check runs.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/timekeeping/employees` | Create an employee record. | `PayrollAdmin` |
| GET | `/timekeeping/employees/{id}` | Read an employee. | `Employee`, `Supervisor`, `PayrollAdmin` |
| PATCH | `/timekeeping/employees/{id}` | Update employee classification, rate, jurisdiction, tipped configuration, or status. | `PayrollAdmin` |
| GET | `/timekeeping/employees` | List employees (filterable by `status`, `classification`). | `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/shifts` | Schedule a new shift. | `Supervisor`, `PayrollAdmin` |
| GET | `/timekeeping/shifts/{id}` | Read a shift with computed fields. | `Employee`, `Supervisor`, `PayrollAdmin` |
| GET | `/timekeeping/shifts` | List shifts (filterable by `employee_id`, `state`, `week_start`). | `Employee`, `Supervisor`, `PayrollAdmin` |
| DELETE | `/timekeeping/shifts/{id}` | Void a `SCHEDULED` shift. | `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/shifts/{id}/punches` | Record a punch (`IN`, `OUT`, `MEAL_OUT`, `MEAL_IN`); server stamps `punched_at`. | `Employee`, `Supervisor` |
| POST | `/timekeeping/shifts/{id}/finalize` | Finalize a `CLOSED` shift, rolling hours into the workweek and running the pay engine. | `PayrollAdmin` |
| POST | `/timekeeping/shifts/{id}/tip-declaration` | Declare tips for a shift (tipped employees only). | `Employee`, `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/time-edits` | Submit a time-edit request. | `Employee`, `Supervisor`, `PayrollAdmin` |
| GET | `/timekeeping/time-edits/{id}` | Read a time edit with its audit trail. | `Employee`, `Supervisor`, `PayrollAdmin` |
| GET | `/timekeeping/time-edits` | List time edits (filterable by `shift_id`, `state`, `reason_code`). | `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/time-edits/{id}/approve` | Approve a `PENDING` time edit. | `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/time-edits/{id}/reject` | Reject a `PENDING` time edit. | `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/time-edits/{id}/revert` | Revert an `APPROVED` time edit. | `PayrollAdmin` |
| GET | `/timekeeping/workweeks/{id}` | Read a workweek with regular/overtime/doubletime/gross. | `Employee`, `Supervisor`, `PayrollAdmin` |
| GET | `/timekeeping/workweeks` | List workweeks (filterable by `employee_id`, `payroll_status`, `week_start`). | `Supervisor`, `PayrollAdmin` |
| POST | `/timekeeping/workweeks/{id}/lock` | Lock a `POSTED` workweek; payroll-final. | `PayrollAdmin` |
| GET | `/timekeeping/audit` | Read the audit log (filterable by `subject_entity`, `subject_id`, `action`). | `PayrollAdmin` |
| POST | `/timekeeping/_clock/advance` | Test-only — advance the server clock by `seconds`. | `PayrollAdmin` |
| POST | `/timekeeping/_clock/set` | Test-only — set the server clock to a supplied `now` timestamp. | `PayrollAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_INVALID_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_SHIFT_INVALID_STATE` | 409 |
| `ERR_SHIFT_ALREADY_OPEN` | 409 |
| `ERR_TIME_EDIT_NOT_PENDING` | 409 |
| `ERR_WORKWEEK_LOCKED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_FRAUD_REQUIRES_ADMIN` | 403 |
| `ERR_EXEMPT_NOT_ELIGIBLE` | 422 |
| `ERR_PUNCH_OUT_OF_ORDER` | 422 |
| `ERR_MEAL_BREAK_DUPLICATE` | 409 |
| `ERR_PUNCH_OUTSIDE_WINDOW` | 422 |
| `ERR_TIME_EDIT_OUT_OF_RANGE` | 422 |
| `ERR_WORKWEEK_BAD_ANCHOR` | 422 |
| `ERR_TIPPED_FIELDS_MISMATCH` | 422 |
| `ERR_TIPS_NOT_APPLICABLE` | 422 |
| `ERR_BELOW_MINIMUM_WAGE` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_DUPLICATE_IDEMPOTENCY_KEY` | 409 |
| `ERR_INVALID_INPUT` | 422 |
