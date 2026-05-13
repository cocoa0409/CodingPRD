# Stock Option Incentive API — Product Requirements Document

## 1. Introduction

A privately held company runs its employee equity programme on a single, auditable ledger. From the moment a board carves out an option pool until each grantee has either exercised, forfeited, or sold their shares, every state change must be traceable, every approval must be reproducibly attributable to a named actor, and every monetary computation must be reconstructable cents-for-cents at audit time. The system described in this document is the source of truth for that ledger.

Three forces shape the design. First, the lifecycle of a grant is long — typically four years from grant date to fully vested, plus a post-exercise tail for tax filings and sale events. Over that period the underlying share economics change (stock splits, dividends, restructurings, change-of-control), and the exercise price each grantee carries must be repriced deterministically so that no grantee can claim ignorance of the adjusted strike. Second, approval workflows for equity compensation are subject to segregation-of-duties rules: the person who drafts a grant cannot also approve it on the board side, and neither of them may approve it on the shareholder side. The platform must enforce this at the API layer, not in policy documents. Third, tax withholding obligations differ by both the plan's jurisdiction and the grantee's tax residency, and they are computed at narrowly defined event boundaries (grant, vest, exercise, sale). Withheld amounts are legally binding once pinned, so the pinning instant — and the rate table active at that instant — must be precisely defined.

The deliverable is a REST API that orchestrates the option-plan lifecycle, the grant-approval workflow, the exercise calendar (with corporate-event blackouts), repricing cascades on corporate events, vesting accrual (cliff plus periodic schedule, with acceleration and performance gating), exercise processing (settled as share issuance or as cash), withholding-tax pinning, and the departure workflow (resignation, termination, retirement, death — with good-leaver / bad-leaver classification). Every mutation that affects equity economics is recorded in an append-only audit ledger.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must include two custom headers: `X-User-ID` (a non-empty string identifying the acting principal) and `X-User-Role` (a non-empty string naming one of the five roles defined below). A request missing either header, or carrying an empty value in either header, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If both headers are present but the role is not authorized for the requested endpoint per the RBAC matrix in §4, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Five roles are defined, with exact spelling: `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `Grantee`, and `AuditViewer`.

`PlanAdministrator` is an operator role that drafts grants, configures batches and windows, advances the plan clock, records corporate events, settles exercises, and finalizes departures. When `X-User-Role` is `PlanAdministrator`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `submitted_by_actor_id` on a `Grant` draft submission, or as the `actor_id` on the resulting `AuditLogEntry`) but never compares it to any entity's `id`.

`BoardSecretary` is the operator who records board-side approval decisions. When `X-User-Role` is `BoardSecretary`, the `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records it as `Grant.board_approval_actor_id` on the board-approval transition but does not match it to any entity row.

`ShareholderRegistrar` is the operator who records shareholder-side approval decisions. When `X-User-Role` is `ShareholderRegistrar`, the `X-User-ID` is again an opaque operator identifier not tied to any persisted entity; the server records it as `Grant.shareholder_approval_actor_id` on the shareholder-approval transition.

`Grantee` is the option recipient. When `X-User-Role` is `Grantee`, the `X-User-ID` equals the `hr_employee_id` of exactly one persisted `Grantee` row; ownership checks on any resource that references a `Grantee` (for example, a `Grant` referencing a `grantee_id`, or an `ExerciseApplication` whose `Grant` belongs to that grantee) compare the resource's foreign-key chain back to the `Grantee` row whose `hr_employee_id` equals `X-User-ID`. A grantee may only sign their own grant agreements, submit exercise applications against their own grants, and cancel their own submitted exercise applications.

`AuditViewer` is a read-only compliance role. When `X-User-Role` is `AuditViewer`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on audit-related read access but does not compare it to any entity's `id`.

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

All list endpoints accept two query-string parameters, `limit` and `offset`. `limit` defaults to 10 and must lie between 1 and 100 inclusive; `offset` defaults to 0 and must be at least 0. List results are sorted by `created_at` in ascending order. Each list response's `meta` object includes `limit`, `offset`, `total_count` (the total number of rows matching the filter, ignoring pagination), and `has_more` (true if more rows exist beyond the returned page).

### 2.4. Common Resource Properties and the Plan Clock

Every resource carries a server-minted UUID in the `id` field; ids do not embed a type prefix. Resources whose lifecycle is mutable carry `created_at` and `updated_at` (ISO 8601 UTC strings with three fractional digits) plus an integer `version` that begins at 1 and increments by exactly one on every successful state-changing mutation. This treatment applies to `OptionPlan`, `GrantBatch`, `Grantee`, `Grant`, `ExerciseWindow`, `ExerciseApplication`, and `DepartureRecord`. Five entities are append-only: `CorporateEvent`, `ExercisePriceVersion`, `VestingRecord`, `TaxEventRecord`, and `AuditLogEntry`. Rows of those five entities carry only `id` and `created_at`; they do not carry `updated_at` and they do not carry `version`.

Time inside an `OptionPlan` does not advance with wall-clock seconds. Each plan has its own logical clock, exposed as `current_clock_ts`, which is initialized when the plan transitions out of `DRAFT` and is moved forward exclusively through an administrator-only test-driving capability that advances the logical clock by a supplied `by_seconds` number of seconds (the activation transition additionally accepts an initial `now_iso` instant; if omitted, server-now is used). Every time-gated computation in the system — vesting accrual, window auto-open and auto-close, blackout expiration, post-departure exercise deadline — reads `current_clock_ts` rather than the operating system clock. Implementations must not consult any other time source for business logic.

### 2.5. Optimistic Concurrency Control

The seven mutable entities listed in §2.4 expose their integer `version` to clients. Any state-changing request body may optionally include a `version` field. When present, the server compares it to the row's current `version` before applying the mutation; on mismatch the request is rejected with `ERR_VERSION_MISMATCH` and no side effects fire. When the `version` field is omitted from the request body the check is skipped and the mutation proceeds against whatever the current value happens to be.

### 2.6. Nested Resource Path Validation

URL paths are validated left to right. Where a path contains multiple resource ids — for example a path naming both a plan id and a batch id, or both a grantee id and a departure-record id — the outer id is resolved first; if it does not refer to any persisted row the response is `ERR_NOT_FOUND` and the inner ids are not examined. Once each id resolves to a row, the rows must form a single ownership chain: a batch's `plan_id` must equal the plan id in the path; a grant's `batch_id` and `plan_id` must equal the corresponding path segments; a window's `plan_id` must match the plan; and an exercise application's grant must belong to the plan referenced in the surrounding path. Any inconsistency yields `ERR_CROSS_RESOURCE_MISMATCH`.

### 2.7. Validation Priority Order

When several validation categories could fail for the same request, the server evaluates them in a fixed order and reports the first one to fail. The order is: (1) presence of the user-context headers, yielding `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role authorization, yielding `ERR_INSUFFICIENT_PERMISSIONS`; (3) existence of path-id resources (left-to-right), yielding `ERR_NOT_FOUND`; (3.5) optimistic-concurrency `version` match when supplied, yielding `ERR_VERSION_MISMATCH`; (4) state-machine precondition (the resource is in a state from which the requested transition is defined), yielding the corresponding state-specific error such as `ERR_GRANT_NOT_IN_DRAFT`, `ERR_GRANT_NOT_BOARD_APPROVED`, `ERR_GRANT_NOT_SHAREHOLDER_APPROVED`, `ERR_GRANT_NOT_LIVE`, `ERR_WINDOW_NOT_OPEN`, `ERR_WINDOW_NOT_CLOSED`, `ERR_BATCH_NOT_OPEN`, `ERR_PLAN_NOT_ACTIVE`, or `ERR_DEPARTURE_NOT_DRAFT`; (5) cross-entity ownership / nested-path consistency, yielding `ERR_CROSS_RESOURCE_MISMATCH`; (6) segregation-of-duties on approval endpoints, yielding `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; (7) temporal-interval shape (window endpoints, corporate-event endpoints, acceleration endpoint), yielding `ERR_INVALID_TIME_INTERVAL`; (8) blackout / window overlap, yielding `ERR_BLACKOUT_OVERLAPS_WINDOW`; (9) grantee employment eligibility for sign-agreement, yielding `ERR_GRANTEE_INELIGIBLE`; (10) window-open / post-departure-window check for exercise submission, yielding `ERR_NOT_IN_EXERCISE_WINDOW`; (11) blackout-active gating for sign-agreement when the caller demands a live grant, yielding `ERR_BLACKOUT_ACTIVE`; (12) exercisable-quantity check, yielding `ERR_INSUFFICIENT_VESTED_QUANTITY`; (13) performance-attestation gate, yielding `ERR_PERFORMANCE_CONDITION_NOT_MET`; (14) plan-pool sufficiency at board approval, yielding `ERR_POOL_INSUFFICIENT`; (15) no-pending-dependents at plan close / batch lock / window archive, yielding either `ERR_PENDING_GRANTS_EXIST` or `ERR_OPEN_EXERCISES_EXIST` depending on the dependent kind; (16) stale-price-version at exercise submission and verification, yielding `ERR_STALE_PRICE_VERSION`; (17) corporate-event input-shape, yielding `ERR_INVALID_REQUEST`; (18) bad-leaver-requires-termination, yielding `ERR_BAD_LEAVER_REQUIRES_TERMINATION`. Generic body-shape failures (negative `pool_total_options`, missing `settlement_mode`, missing `payment_reference` when one is required, and similar) surface as `ERR_INVALID_REQUEST` and are tried after the structural validations above.

### 2.8. Precision and Rounding

All monetary amounts in this system are stored as integer cents (`grant_date_fair_value_cents`, `price_per_option_cents`, `dividend_amount_cents`, `gross_proceeds_cents`, `withholding_tax_cents`, `net_proceeds_cents`, `taxable_amount_cents`, `withheld_amount_cents`, `sale_proceeds_cents`, `cost_basis_cents`). All option counts (`quantity`, `vested_quantity`, `exercised_quantity`, `forfeited_quantity`, `outstanding_quantity`, `tranche_quantity`, `requested_quantity`, `pool_total_options`, `pool_reserved_options`, `pool_remaining_options`, `forfeited_options_total`, `sold_quantity`) are integers. When a calculation produces a fractional result, the rounding mode is fixed per calculation: vesting count truncates toward zero (floor) to an integer option count; stock-split repricing truncates toward zero (floor); cash-dividend repricing is exact subtraction; restructuring repricing multiplies first, divides second, and rounds half up at the final step; withholding-tax computation rounds half up per tier slab and then sums (round-per-slab, then sum — never sum, then round). The order of operations inside each repricing branch is pinned and must not be reversed.

### 2.9. Hierarchical Consistency and Cascades

State changes that touch multiple entities complete inside the triggering request — the consistency model is single-request atomic. When a cascade fires, every affected row's `updated_at` is refreshed and its `version` is bumped by one. The cascades are:

- Recording a corporate event of type `STOCK_SPLIT`, `CASH_DIVIDEND`, or `RESTRUCTURING` appends a new `ExercisePriceVersion` row for every `GrantBatch` under the plan, with `cause` set to the corporate-event type, `corporate_event_id` set to the event's id, `parent_version_id` set to the previous tip of the chain for that batch, and `version_index` set to the previous tip's index plus one. One `AuditLogEntry` with `action_code` `PRICE_VERSION_CREATED` is appended per affected batch. The repricing does not modify `Grant.pinned_price_version_id` on grants that are already past `AGREEMENT_SIGNED`; those grants stay pinned to their captured version.
- Settling a departure refreshes the affected `Grantee` row (`eligibility_status` flips to `DEPARTED`, `departed_at` is set), and may transition each of that grantee's `Grant` rows. Whenever a grant's `forfeited_quantity` is updated, `plan.pool_reserved_options` is decremented by the same amount and the plan row's `version` and `updated_at` are refreshed. For a bad-leaver departure, each affected grant's `status` transitions to `TERMINATED` and every non-terminal `ExerciseApplication` against those grants auto-transitions to `REJECTED` with a forfeiture note.
- Closing an `OptionPlan` causes the next window-sweep operation to flip all `ACTIVE`-or-`SCHEDULED` windows under the plan to `CLOSED` and mark them archived.

Every state-changing transition listed in §3 appends one `AuditLogEntry` whose `actor_id` and `actor_role` are taken from the inbound headers, whose `target_entity` and `target_id` identify the row that transitioned, whose `payload_summary` captures a before/after snapshot of the key fields, and whose `occurred_ts` is the plan clock at the moment of transition.

### 2.10. Concurrency Resolution

Five concurrent-request scenarios have explicit serialization guarantees:

- Two exercise applications submitted by the same grantee against the same `OPEN` window whose combined `requested_quantity` exceeds the grant's exercisable count serialize first-writer-wins on the decrement of the grant's exercisable surplus inside the transaction; the second submission is rejected with `ERR_INSUFFICIENT_VESTED_QUANTITY`.
- A board approval and a draft-rescission attempted concurrently on the same grant serialize first-writer-wins on `Grant.status`; the loser observes `ERR_GRANT_NOT_IN_DRAFT`.
- A corporate-event creation of type `STOCK_SPLIT` racing with a grant agreement signing on the same batch is benign by design: whichever request commits first defines that grant's pinned price version, and the other request still succeeds — no error is produced. The audit ledger is the invariant: exactly one `PRICE_VERSION_CREATED` entry and exactly one `GRANT_AGREEMENT_SIGNED` entry must appear. The only situation in which a `ERR_VERSION_MISMATCH` can be emitted here is the degenerate case where two writers attempt to claim the same `version_index` on the same batch chain at the same instant, which the server prevents by serializing on the monotonic `effective_from_ts` of the new version.
- Two concurrent departure-settle calls on the same grantee serialize first-writer-wins on the `Grantee.eligibility_status` flip from `ELIGIBLE` to `DEPARTED`; the loser receives `ERR_GRANTEE_ALREADY_DEPARTED`.
- A window-archive request racing with the settlement of a still-non-terminal exercise application on that window resolves by row-acquisition order: if the settle commits first, the archive observes the application now in a terminal state and proceeds; if the archive acquires the window row first, the still-open application causes it to fail with `ERR_OPEN_EXERCISES_EXIST`.

## 3. Business Logic & Workflows

### 3.1. Plan Setup, Pool Sizing, and Clock Activation

An option plan begins life when a `PlanAdministrator` creates it by submitting a `name`, a positive integer `pool_total_options`, and a `jurisdiction_code` of `US`, `UK`, `CN`, or `SG`. The plan is created in `DRAFT` with `status` set to `DRAFT`, `pool_reserved_options` initialized to zero, and `current_clock_ts` left unset. Activation by the same administrator transitions the plan from `DRAFT` to `ACTIVE` and is only allowed when `pool_total_options` is at least one — otherwise `ERR_INVALID_REQUEST` is returned. Activation may optionally accept an initial `now_iso` instant which becomes the plan's starting `current_clock_ts`; if the field is omitted, the server's wall-clock-now is used. From activation onward the plan clock advances solely through the administrator-only clock-advance capability, which adds a supplied `by_seconds` integer to `current_clock_ts` and triggers re-evaluation of all time-gated derivations (vesting, blackouts, window state) on read.

Closing the plan is the reverse boundary: an administrator transitioning the plan from `ACTIVE` to `CLOSED` is rejected with `ERR_PENDING_GRANTS_EXIST` if any grant under the plan is currently in `DRAFT`, `BOARD_APPROVED`, or `SHAREHOLDER_APPROVED`, and with `ERR_OPEN_EXERCISES_EXIST` if any exercise application under the plan is currently in `SUBMITTED`, `ELIGIBILITY_VERIFIED`, `PAYMENT_RECEIVED`, or `TAX_WITHHELD`. After a successful close, every `SCHEDULED`-or-`OPEN` exercise window under the plan is flipped to `CLOSED` and archived on the next sweep.

`pool_reserved_options` is a running aggregate: it equals the sum, over every grant under the plan whose `status` is `BOARD_APPROVED`, `SHAREHOLDER_APPROVED`, `AGREEMENT_SIGNED`, `LIVE`, or `FROZEN`, of that grant's `quantity` reduced by its `exercised_quantity` and its `forfeited_quantity`. `pool_remaining_options` is `pool_total_options` minus `pool_reserved_options`; both fields are recomputed on read and exposed to the client.

### 3.2. Batches, Vesting Configuration, and the Initial Price Version

A `GrantBatch` is the unit at which vesting parameters and the price-version chain are anchored. Creating a batch under a plan attaches a unique-within-plan `batch_label`, an integer `cliff_months` (zero means no cliff), an integer `vesting_total_months`, a `vesting_period_months` enum value of `1` (monthly), `3` (quarterly), or `12` (annual), a `vesting_algorithm` enum of `ANNIVERSARY_BATCH` or `CONTINUOUS_DAILY`, an optional `performance_condition_required` flag (defaulting to false), and an `initial_price_per_option_cents` that stages the future v1 price version. The batch is created in `DRAFT`.

Opening the batch transitions it from `DRAFT` to `OPEN_FOR_GRANTS` and is gated by three checks: `cliff_months` must be less than or equal to `vesting_total_months`, `vesting_total_months` must be evenly divisible by `vesting_period_months` (the remainder of the division must be zero), and the owning plan must be `ACTIVE`. The first two failures yield `ERR_INVALID_REQUEST`; the plan-state failure yields `ERR_PLAN_NOT_ACTIVE`. As a side effect, the first `ExercisePriceVersion` for the batch is created with `version_index` 1, `cause` `INITIAL`, `corporate_event_id` null, `parent_version_id` null, `effective_from_ts` set to the plan clock, and `price_per_option_cents` taken from the staged input.

Locking the batch transitions it from `OPEN_FOR_GRANTS` to `LOCKED` and is rejected with `ERR_PENDING_GRANTS_EXIST` if any grant under the batch is still in `DRAFT`, `BOARD_APPROVED`, or `SHAREHOLDER_APPROVED`. `LOCKED` is terminal for the batch — no further grants are accepted, but existing live grants continue to vest and may be exercised.

### 3.3. Grantee Registration

A grantee is registered under a plan with an `hr_employee_id` (the foreign-key handle to the HR system payload), a `full_name`, and a `tax_residency` of `US`, `UK`, `CN`, or `SG`. `eligibility_status` is initialized to `ELIGIBLE` and `departed_at` is left null. Both `eligibility_status` and `tax_residency` participate in downstream gating: `eligibility_status` controls who may sign agreements and submit exercise applications, while the pair (`plan.jurisdiction_code`, `grantee.tax_residency`) drives tax-rate lookups.

### 3.4. Grant Lifecycle: Submission, Dual Approval, and Agreement

A grant draft is submitted by a `PlanAdministrator` against an `OPEN_FOR_GRANTS` batch, naming the recipient `grantee_id`, the positive integer `quantity`, and the per-option `grant_date_fair_value_cents` (at least 1). The submitting administrator's `X-User-ID` is captured as `submitted_by_actor_id`; this captured id is the segregation-of-duties anchor for the rest of the approval flow. The new grant has `status` `DRAFT`, `vested_quantity` 0, `exercised_quantity` 0, `forfeited_quantity` 0, `pinned_price_version_id` null, `board_approval_actor_id` and `shareholder_approval_actor_id` null, `grant_date` null, and `performance_attested_at` null.

Board approval, performed by a `BoardSecretary`, transitions the grant from `DRAFT` to `BOARD_APPROVED`. Four checks fire in order: the acting `X-User-ID` must differ from `submitted_by_actor_id` or the operation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; the grant must be in `DRAFT` or it is rejected with `ERR_GRANT_NOT_IN_DRAFT`; the owning batch must be in `OPEN_FOR_GRANTS` or it is rejected with `ERR_BATCH_NOT_OPEN`; and `quantity` must be less than or equal to `pool_remaining_options` or it is rejected with `ERR_POOL_INSUFFICIENT`. On success, `board_approval_actor_id` is set to the acting `X-User-ID`, `pool_reserved_options` increases by `quantity`, and one audit entry with `action_code` `GRANT_BOARD_APPROVED` is appended.

Shareholder approval, performed by a `ShareholderRegistrar`, transitions the grant from `BOARD_APPROVED` to `SHAREHOLDER_APPROVED`. The acting `X-User-ID` must be neither `submitted_by_actor_id` nor `board_approval_actor_id` — failing this check yields `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — and the grant must be in `BOARD_APPROVED` or the result is `ERR_GRANT_NOT_BOARD_APPROVED`. On success, `shareholder_approval_actor_id` is set to the acting `X-User-ID`, `grant_date` is set to `plan.current_clock_ts`, a `TaxEventRecord` with `event_type` `GRANT` is appended (its `taxable_amount_cents` is zero in every jurisdiction by current rules), and one audit entry with `action_code` `GRANT_SHAREHOLDER_APPROVED` is appended.

The grantee signs the agreement themselves, transitioning the grant from `SHAREHOLDER_APPROVED` to `AGREEMENT_SIGNED`. The acting `X-User-ID` must equal the `hr_employee_id` of the `Grantee` referenced by `grantee_id`, otherwise `ERR_INSUFFICIENT_PERMISSIONS`; the grant must be in `SHAREHOLDER_APPROVED`, otherwise `ERR_GRANT_NOT_SHAREHOLDER_APPROVED`; and the grantee's `eligibility_status` must be `ELIGIBLE`, otherwise `ERR_GRANTEE_INELIGIBLE`. The pivotal side effect is the capture of `pinned_price_version_id`: the server snapshots the current tip of the batch's exercise-price-version chain (the row with the highest `version_index` for that `batch_id`) and locks it onto the grant. From this instant the grantee's strike price is fixed; subsequent corporate-event repricings emit new versions but do not change this grant's pinned id.

Immediately after `AGREEMENT_SIGNED`, the system routes the grant to either `LIVE` or `FROZEN`. The signing request may include an optional `require_live` flag. If any `EARNINGS_BLACKOUT` or `MATERIAL_EVENT_BLACKOUT` corporate event is currently active (its `effective_ts` is at or before the plan clock and its `blackout_end_ts` is strictly after the plan clock), the grant goes to `FROZEN` when `require_live` is false or omitted, or the request fails with `ERR_BLACKOUT_ACTIVE` when `require_live` is true. If no blackout is active, the grant goes to `LIVE`. A `FROZEN` grant remains vesting-eligible (it continues to accrue vested options against the plan clock) but is barred from exercise application submission until the system detects, on the next clock advance crossing every overlapping `blackout_end_ts`, that no blackout overlaps the clock — at that point it auto-transitions to `LIVE`.

### 3.5. Vesting: Cliff, Periodic Schedule, Performance Gating, and Acceleration

Once a grant is `LIVE` or `FROZEN`, the system computes `vested_quantity` against the plan clock every time the grant is read, every time an exercise application is verified, and every time an administrator invokes the manual vesting-recompute capability against the grant. The computation begins by determining the number of whole months elapsed between `grant_date` and `plan.current_clock_ts`. If the elapsed-month count is strictly less than `cliff_months`, the unconditional vested figure is zero — nothing has cleared the cliff. Otherwise the computation branches on `vesting_algorithm`.

For `ANNIVERSARY_BATCH`, tranches vest in lump sums at each `vesting_period_months` boundary after the cliff. The number of completed periods is one plus the integer-part (floor) of the elapsed-months-since-cliff divided by `vesting_period_months`, capped at `vesting_total_months` divided by `vesting_period_months`. The unconditional vested option count is the floor of `quantity` multiplied by the completed-period count multiplied by `vesting_period_months`, all divided by `vesting_total_months`. Between two consecutive period boundaries the vested count is flat — readers observe a step function. For `CONTINUOUS_DAILY`, vesting accrues linearly by day after the cliff. The constant `DAYS_PER_MONTH` is fixed at 30, so the number of days from grant date to cliff is `cliff_months` multiplied by 30 and the number of total vesting days is `vesting_total_months` multiplied by 30; the days-since-cliff is the larger of zero and the day-count between (`grant_date` plus `cliff_months` months) and `plan.current_clock_ts`. The unconditional vested option count is the floor of `quantity` multiplied by the smaller of days-since-cliff and total-vesting-days, divided by total-vesting-days. Mid-period the two algorithms produce different counts on identical inputs.

If the batch's `performance_condition_required` is true and `Grant.performance_attested_at` is null, the gated vested figure is forced to zero — the performance gate suppresses unconditional vesting until a `PlanAdministrator` attests by invoking the performance-attestation capability against the grant, which writes the current plan clock into `performance_attested_at`. If the performance flag is false, or it is true and `performance_attested_at` is non-null, the gated figure equals the unconditional figure.

Independently, acceleration tranches sum any `VestingRecord` rows for this grant whose `cause` is `ACCELERATION_CHANGE_OF_CONTROL` or `ACCELERATION_IPO`. These records are produced by the administrator-only acceleration capability, which takes a `corporate_event_id` referencing an existing event of type `CHANGE_OF_CONTROL` or `IPO` (failure to reference such an event yields `ERR_INVALID_TIME_INTERVAL`) and writes a `VestingRecord` whose `tranche_quantity` is determined by acceleration policy (typically equal to the grant's remaining `outstanding_quantity`), whose `tranche_index` continues the per-grant monotonic counter, whose `vested_ts` is the plan clock, and whose `cause` is the corresponding `ACCELERATION_*` value.

The grant's `vested_quantity` is the smaller of `quantity` and the larger of the gated figure and the acceleration sum. `outstanding_quantity` is `quantity` minus `exercised_quantity` minus `forfeited_quantity`.

The manual vesting-recompute capability additionally emits new `VestingRecord` rows with `cause` `CLIFF` (for the cliff threshold first crossing) or `PERIODIC` (for each periodic boundary newly crossed since the last record) — one row per crossed boundary — each with the next `tranche_index` value, `vested_ts` set to the plan clock, `tranche_quantity` equal to the vested-quantity delta produced by that crossing, and `archived` initialized to false. A separate administrator-only vesting-archive capability flips `archived` to true on every non-archived `VestingRecord` of the grant — used for terminal-state housekeeping. Listings of a grant's vesting records accept an optional `archived` query parameter to scope to archived-only or active-only rows.

### 3.6. Exercise Windows, Blackouts, and the Window Sweep

`ExerciseWindow` rows define the calendar intervals during which exercise applications may be submitted. A window is created with a unique-within-plan `label`, an inclusive `open_ts`, and a strictly-greater exclusive `close_ts`; if `open_ts` is at or after `close_ts` the request is rejected with `ERR_INVALID_TIME_INTERVAL`. The window is born in `SCHEDULED`.

Corporate-event blackouts (`EARNINGS_BLACKOUT` and `MATERIAL_EVENT_BLACKOUT`) define disqualifying intervals: each such event carries an `effective_ts` (inclusive start) and a `blackout_end_ts` (exclusive end, which must be strictly later than `effective_ts`, else `ERR_INVALID_TIME_INTERVAL`). A window may not overlap any blackout using half-open intervals on both sides: the window's `[open_ts, close_ts)` interval must have empty intersection with every blackout's `[effective_ts, blackout_end_ts)` interval. Any non-empty intersection is rejected with `ERR_BLACKOUT_OVERLAPS_WINDOW`. This check fires both when creating the window (against the set of existing blackouts) and when creating a blackout (against the set of existing windows).

A `PlanAdministrator`-invoked window-sweep capability evaluates every non-archived window against `plan.current_clock_ts`. A `SCHEDULED` window auto-transitions to `OPEN` when the plan clock has reached or passed `open_ts` and is strictly before `close_ts`, provided no blackout overlaps the window (otherwise the sweep leaves the window in `SCHEDULED`); the side effect sets `notified_at` to the plan clock and emits a notification audit entry per eligible grantee. An `OPEN` window auto-transitions to `CLOSED` when the plan clock has reached `close_ts`; as a side effect, every `ExerciseApplication` still in `SUBMITTED` for that window auto-transitions to `REJECTED` with note `WINDOW_CLOSED`. Archiving a window transitions it from `CLOSED` to `ARCHIVED` and is rejected with `ERR_WINDOW_NOT_CLOSED` if the window is not in `CLOSED`, and with `ERR_OPEN_EXERCISES_EXIST` if any exercise application against the window remains in a non-terminal state.

### 3.7. Repricing on Corporate Events

Corporate events of type `STOCK_SPLIT`, `CASH_DIVIDEND`, and `RESTRUCTURING` cascade a new `ExercisePriceVersion` per batch under the plan, advancing each batch's version chain by one `version_index` and recording the new `price_per_option_cents`. Each new row carries `cause` equal to the corporate event's type, `corporate_event_id` set to the triggering event, `parent_version_id` set to the previous tip, and `effective_from_ts` set to the plan clock; `disclosed_at` is null until a `PlanAdministrator` invokes the disclose capability against the version, which writes the plan clock into `disclosed_at` and appends an audit entry.

For a stock split, the new per-option price is the floor of the parent version's `price_per_option_cents` multiplied by `split_ratio_denominator`, divided by `split_ratio_numerator`. A 2-for-1 split (`split_ratio_numerator` is 2, `split_ratio_denominator` is 1) therefore halves the price; both ratio fields must be at least 1 or the corporate-event creation is rejected with `ERR_INVALID_REQUEST`.

For a cash dividend, the new per-option price is the parent version's `price_per_option_cents` minus `dividend_amount_cents`, clamped to a minimum of 1 cent (the constant `MIN_PRICE_CENTS`). `dividend_amount_cents` must be at least 1 or the corporate-event creation fails with `ERR_INVALID_REQUEST`.

For a restructuring, the new per-option price is computed by multiplying the parent's `price_per_option_cents` by `restructure_factor_bps`, then dividing by the basis-points divisor of 10000, with rounding half up performed only at the final step — multiplication first, division second, rounding last. The resulting figure is clamped to a minimum of 1 cent. `restructure_factor_bps` must lie between 100 and 100000 inclusive or the creation is rejected with `ERR_INVALID_REQUEST`.

`EARNINGS_BLACKOUT` and `MATERIAL_EVENT_BLACKOUT` events do not emit a new price version — they only assert a window-overlap constraint and gate sign-agreement routing. `CHANGE_OF_CONTROL` and `IPO` events do not emit a new price version either; they exist solely as the referent for acceleration-vesting `VestingRecord` rows.

### 3.8. Exercise Submission, Pricing, Tax Withholding, and Settlement

A grantee submits an exercise application against an `OPEN` window, specifying a `window_id`, a positive integer `requested_quantity`, a `settlement_mode` of `SHARE_ISSUANCE` or `CASH_SETTLEMENT`, and the `pinned_price_version_id` they intend to use. The submitted `pinned_price_version_id` must equal the current tip of the batch's price-version chain at submission instant; if a corporate-event repricing has bumped the chain since the grantee last read, the submission is rejected with `ERR_STALE_PRICE_VERSION`. The new application is created with `status` `SUBMITTED`, the parent `grant_id` and `plan_id` set, the captured pinned-version snapshot recorded, `gross_proceeds_cents` pre-computed, and `withholding_tax_cents` and `net_proceeds_cents` left null. Window must be `OPEN` (else `ERR_NOT_IN_EXERCISE_WINDOW`) and — when the grantee is post-departure — the plan clock must be at or before the `post_departure_exercise_deadline_ts` recorded on the grantee's departure record (otherwise `ERR_NOT_IN_EXERCISE_WINDOW` is again the error). The grantee may cancel their own `SUBMITTED` application themselves; an administrator may reject a `SUBMITTED` or `ELIGIBILITY_VERIFIED` application with an optional `reason` field.

Verification is performed by a `PlanAdministrator` and transitions the application from `SUBMITTED` to `ELIGIBILITY_VERIFIED`. The grant must be in `LIVE` (rejected with `ERR_GRANT_NOT_LIVE` if not — this is the first check that fires inside verify); the window must still be `OPEN` (else `ERR_WINDOW_NOT_OPEN`); the grantee must be `ELIGIBLE`, or `DEPARTED` and within the post-departure deadline (otherwise `ERR_NOT_IN_EXERCISE_WINDOW`); the pinned price version must still match the chain tip (else `ERR_STALE_PRICE_VERSION`); the `requested_quantity` must be at most `vested_quantity` minus `exercised_quantity` (else `ERR_INSUFFICIENT_VESTED_QUANTITY`); and if the batch carries `performance_condition_required` true, `performance_attested_at` must be non-null (else `ERR_PERFORMANCE_CONDITION_NOT_MET`). Vested quantity is freshly recomputed against the plan clock before the comparison.

For `CASH_SETTLEMENT` applications, verification cascades immediately into the `ELIGIBILITY_VERIFIED` → `TAX_WITHHELD` transition, which runs the withholding-tax calculation and pins both `TaxEventRecord` and the application's `withholding_tax_cents`. For `SHARE_ISSUANCE` applications, the administrator must first record payment by supplying a non-empty `payment_reference` (otherwise `ERR_INVALID_REQUEST`), which transitions the application from `ELIGIBILITY_VERIFIED` to `PAYMENT_RECEIVED`; the application's `gross_proceeds_cents` is pinned at this moment as `requested_quantity` multiplied by the pinned version's `price_per_option_cents`. Immediately after `PAYMENT_RECEIVED`, the system auto-transitions to `TAX_WITHHELD` and pins the tax record. Invoking the payment-record capability on a `CASH_SETTLEMENT` application yields `ERR_INVALID_REQUEST` because the cash branch skips that transition entirely.

Settlement, also by a `PlanAdministrator`, finalizes the application from `TAX_WITHHELD` to `SETTLED`. For `SHARE_ISSUANCE`, the settlement request must carry a `share_registry_reference` (otherwise `ERR_INVALID_REQUEST`); for `CASH_SETTLEMENT`, it must carry a `payment_reference` (otherwise `ERR_INVALID_REQUEST`). Settlement increases `Grant.exercised_quantity` by `requested_quantity`, decreases `plan.pool_reserved_options` by the same amount (the options have left the reservation pool because they have been issued or cashed out), and appends an `EXERCISE_SETTLED` audit entry.

`gross_proceeds_cents` is always `requested_quantity` multiplied by the pinned version's `price_per_option_cents` — a single multiplication, no per-line rounding. `net_proceeds_cents` is meaningful only for `CASH_SETTLEMENT` applications, where it is `gross_proceeds_cents` minus `withholding_tax_cents`; for `SHARE_ISSUANCE` applications, `net_proceeds_cents` is left null.

### 3.9. Tax-Event Calculation Across Jurisdictions

Tax events are emitted at four boundaries: grant (created at shareholder approval, with `taxable_amount_cents` always zero), vest (created on demand when the system materialises a vesting event for tax purposes), exercise (created at the `TAX_WITHHELD` transition described above), and sale (created out-of-band by an administrator submitting a sale event with `sale_proceeds_cents`, `cost_basis_cents`, and `sold_quantity` — capturing post-issuance disposal). Each `TaxEventRecord` row carries the originating `grant_id`, the related `exercise_application_id` when the event is an exercise (null for grant and vest events), the `event_type`, the computed `taxable_amount_cents`, the computed `withheld_amount_cents`, the boolean `deferred` flag, the snapshot of the plan's `jurisdiction_code` at event time, the plan-clock `event_ts`, and (after document issuance) a `document_id`.

Taxable amount by event type:

- For a grant event, taxable amount is zero in every jurisdiction.
- For a vest event, taxable amount is the vesting tranche's `tranche_quantity` multiplied by `Grant.grant_date_fair_value_cents` when `plan.jurisdiction_code` is `US` (the US treats vesting of NQSO-style options as ordinary income); for `UK`, `CN`, and `SG` the vest taxable amount is zero.
- For an exercise event, taxable amount is the spread (the larger of zero and the current fair value cents minus the pinned version's `price_per_option_cents`) multiplied by `ExerciseApplication.requested_quantity`.
- For a sale event, taxable amount is the difference (`sale_proceeds_cents` minus `cost_basis_cents`) multiplied by `sold_quantity`.

Effective rate is looked up in a tiered table keyed by (plan jurisdiction, grantee residency, event type). The tiers are marginal rate slabs expressed in basis points (the basis-points divisor `BPS_DIVISOR` is 10000). Representative entries: for plan-jurisdiction `US` and grantee-residency `US` on an exercise, the first 1,000,000 cents of taxable amount is taxed at 2200 basis points (22 percent) and the remainder at 3700 basis points (37 percent); for `US`/`US` on a vest, a single flat slab applies 2200 basis points; for `UK`/`UK` on an exercise, the first 5,000,000 cents is taxed at 2000 basis points (20 percent) and the remainder at 4500 basis points (45 percent); for `CN`/`CN` on an exercise, the first 3,600,000 cents is taxed at 2000 basis points and the remainder at 4500 basis points; for `SG`/`SG` on an exercise, all taxable amount is taxed at a flat 1500 basis points (15 percent); for cross-residency exercises where the plan is in the US and the grantee resides in the UK or CN, a treaty composite rate of 3000 basis points applies as a flat slab; for the US-plan, SG-resident exercise pair, 1500 basis points applies flat. Other plan/residency pairs follow the same mirror structure. For sale events, a long-term-holding discount of 1000 basis points (the constant `LONG_TERM_DISCOUNT_BPS`, which is 10 percentage points) is subtracted from the applicable rate once the holding duration has reached the long-term threshold of 12 months (`LONG_TERM_HOLDING_MONTHS`).

Withholding is computed slab-by-slab and rounded half up at each slab before summing — never sum-then-round. Concretely, the algorithm walks the tiers in order: for each tier (lo, hi, rate_bps), the portion of remaining taxable amount that falls inside the slab is multiplied by the tier's rate, divided by 10000, rounded half up, and added to the accumulator; the cursor advances by the slab size, and the loop stops once the entire taxable amount has been allocated. Reversing the rounding order (summing pre-rounded products) produces different cents and is incorrect.

A deferral exception applies: when `plan.jurisdiction_code` is `UK`, the event type is `EXERCISE`, the grantee's `tax_residency` is `UK`, and a previously approved deferral plan exists for that grantee (recorded as a prior `TaxEventRecord` with `event_type` `GRANT` whose `payload_summary` carries a `deferral_approved` boolean set true), then `deferred` is true and the stored `withheld_amount_cents` is forced to zero — the computed gross withholding is overridden by zero. Otherwise `deferred` is false and `withheld_amount_cents` equals the slab-summed result.

Two evaluation modes share the formula. A provisional mode may be invoked inside verification with intent `provisional` for grantee disclosure; it reads the rate table as of the plan clock at verify time and is never persisted to any `TaxEventRecord` row. The final mode is the one pinned at the `ELIGIBILITY_VERIFIED` to `TAX_WITHHELD` transition and uses the rate table as of the plan clock at that transition instant. Because the two reads can differ — a clock advance between verify and tax-withhold can cross a tier boundary, or the grantee's `tax_residency` can change in the interval — the same logical exercise can produce a different provisional figure than the persisted final figure. The persisted final figure is the legally binding one.

Issuing a tax document is an administrator-only capability that mints a server-side `document_id`, writes it onto the `TaxEventRecord`, and appends an audit entry.

### 3.10. Departure Handling

A departure record is created by a `PlanAdministrator` under the relevant grantee, naming a `departure_type` of `RESIGNATION`, `TERMINATION`, `RETIREMENT`, or `DEATH`, an effective `departed_ts`, and (only when `departure_type` is `TERMINATION`) a `leaver_class` of `GOOD_LEAVER` or `BAD_LEAVER`. Supplying `leaver_class` equal to `BAD_LEAVER` with any `departure_type` other than `TERMINATION` is rejected with `ERR_BAD_LEAVER_REQUIRES_TERMINATION`. For `RESIGNATION` and `RETIREMENT`, `leaver_class` is auto-derived to `GOOD_LEAVER`; for `DEATH`, `leaver_class` is auto-derived to `GOOD_LEAVER`. `BAD_LEAVER` is therefore only producible via `TERMINATION`. The new record is created in `DRAFT`.

At creation, the post-departure window is computed. For `BAD_LEAVER`, `post_departure_window_days` is zero and `post_departure_exercise_deadline_ts` is null — the bad-leaver classification carries no exercise tail. For everyone else, the base window is 90 days for `RESIGNATION`, 180 days for `TERMINATION` (only when `GOOD_LEAVER`), 1095 days (three years) for `RETIREMENT`, and 365 days for `DEATH`. A jurisdiction floor applies: when `leaver_class` is `GOOD_LEAVER` and `plan.jurisdiction_code` is `UK` or `SG`, `post_departure_window_days` is the larger of the base window and 120 days. `post_departure_exercise_deadline_ts` is `departed_ts` plus `post_departure_window_days` days.

Settlement of the departure transitions it from `DRAFT` to `SETTLED` and is gated by two checks: the record must be in `DRAFT` (else `ERR_DEPARTURE_NOT_DRAFT`) and the grantee must still be `ELIGIBLE` (else `ERR_GRANTEE_ALREADY_DEPARTED`). On success, the grantee's `eligibility_status` flips to `DEPARTED` and `departed_at` is set to the record's `departed_ts`. Then the forfeiture cascade runs in lexicographic order across the grantee's `Grant` rows in `LIVE` or `FROZEN` (ordered by `batch_id`, then `grant_date`, then grant `id`):

For each affected grant, vested-at-departure is recomputed at the plan clock equal to `departed_ts` using the active vesting algorithm. The unvested portion (the grant's `quantity` minus vested-at-departure minus existing `forfeited_quantity`) is unconditionally added to `forfeited_quantity` for every leaver class, and `plan.pool_reserved_options` is decreased by the same amount. The outstanding-vested portion (vested-at-departure minus `exercised_quantity`) is treated differently by class. For `GOOD_LEAVER`, the grant stays in `LIVE` or `FROZEN` and the outstanding-vested portion remains exercisable, but only while the plan clock has not yet exceeded `post_departure_exercise_deadline_ts`; new exercise applications submitted after that deadline are rejected with `ERR_NOT_IN_EXERCISE_WINDOW`. For `BAD_LEAVER`, the outstanding-vested portion is also added to `forfeited_quantity` and `plan.pool_reserved_options` is decreased accordingly; the grant transitions from `LIVE` or `FROZEN` to `TERMINATED`; and every still-non-terminal exercise application against that grant (in `SUBMITTED`, `ELIGIBILITY_VERIFIED`, `PAYMENT_RECEIVED`, or `TAX_WITHHELD`) auto-transitions to `REJECTED` with note `BAD_LEAVER_FORFEITURE`. Each grant cascade appends one audit entry with `action_code` `GRANT_TERMINATED` (bad-leaver path only), and the departure-settle itself appends an audit entry with `action_code` `DEPARTURE_SETTLED`. The record's `forfeited_options_total` is the sum of all unvested-forfeited and vested-forfeited across the grants. The grants are processed in the pinned order so that the audit trail records per-grant cause codes deterministically.

### 3.11. Audit Log

Every state-changing operation appends one `AuditLogEntry` whose `action_code` is one of `GRANT_CREATED`, `GRANT_BOARD_APPROVED`, `GRANT_SHAREHOLDER_APPROVED`, `GRANT_AGREEMENT_SIGNED`, `GRANT_TERMINATED`, `EXERCISE_SUBMITTED`, `EXERCISE_SETTLED`, `EXERCISE_REJECTED`, `PRICE_VERSION_CREATED`, or `DEPARTURE_SETTLED`. Each entry captures the `actor_id` and `actor_role` (taken from the inbound `X-User-ID` and `X-User-Role` headers), the `target_entity` name, the affected `target_id`, a `payload_summary` snapshot of the relevant before/after fields, and the `occurred_ts` plan-clock instant. The audit log is append-only; no operation modifies an existing entry. Audit queries accept optional `limit`, `offset`, `action_code`, `target_entity`, and `target_id` filters.

## 4. Endpoint Definitions

All endpoints are mounted under the API prefix `/option-plans` for plan-rooted paths, or directly under `/grants`, `/exercise-applications`, `/exercise-price-versions`, `/tax-events`, and `/grantees` for resource-shortcut paths. Endpoints that create a new resource respond with HTTP 201 and the created resource in `data`; endpoints that modify or transition an existing resource respond with HTTP 200 and the updated resource; endpoints that return collections respond with HTTP 200 and the array of rows in `data` along with pagination fields in `meta`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/option-plans` | Create a new Option Plan in `DRAFT`. | `PlanAdministrator` |
| GET | `/option-plans` | List Option Plans. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| GET | `/option-plans/{planId}` | Get a specific Option Plan. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| POST | `/option-plans/{planId}/activate` | Activate the plan; transitions `DRAFT` to `ACTIVE`. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/close` | Close the plan; transitions `ACTIVE` to `CLOSED`. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/clock/advance` | Advance the plan clock by a supplied number of seconds. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/grant-batches` | Create a Grant Batch under the plan. | `PlanAdministrator` |
| GET | `/option-plans/{planId}/grant-batches` | List Grant Batches under the plan. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| POST | `/option-plans/{planId}/grant-batches/{batchId}/open` | Open batch (`DRAFT` to `OPEN_FOR_GRANTS`); auto-creates v1 price version. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/grant-batches/{batchId}/lock` | Lock batch (`OPEN_FOR_GRANTS` to `LOCKED`). | `PlanAdministrator` |
| POST | `/option-plans/{planId}/grantees` | Register a Grantee under the plan. | `PlanAdministrator` |
| GET | `/option-plans/{planId}/grantees` | List Grantees. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| POST | `/option-plans/{planId}/grant-batches/{batchId}/grants` | Submit a Grant draft. | `PlanAdministrator` |
| GET | `/option-plans/{planId}/grants` | List Grants in the plan. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| GET | `/grants/{grantId}` | Get a Grant (recomputes `vested_quantity`). | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `Grantee`, `AuditViewer` |
| POST | `/grants/{grantId}/board-approve` | Record board approval (`DRAFT` to `BOARD_APPROVED`). | `BoardSecretary` |
| POST | `/grants/{grantId}/shareholder-approve` | Record shareholder approval (`BOARD_APPROVED` to `SHAREHOLDER_APPROVED`). | `ShareholderRegistrar` |
| POST | `/grants/{grantId}/sign-agreement` | Grantee signs agreement (`SHAREHOLDER_APPROVED` to `AGREEMENT_SIGNED`, then `LIVE` or `FROZEN`). | `Grantee` |
| POST | `/grants/{grantId}/accelerate-vesting` | Apply acceleration on `CHANGE_OF_CONTROL` or `IPO`. | `PlanAdministrator` |
| POST | `/grants/{grantId}/attest-performance` | Attest performance condition. | `PlanAdministrator` |
| POST | `/grants/{grantId}/vesting/recompute` | Manually recompute `vested_quantity` and emit `VestingRecord` deltas. | `PlanAdministrator` |
| GET | `/grants/{grantId}/vesting-records` | List a grant's `VestingRecord` rows (active and archived). | `PlanAdministrator`, `Grantee`, `AuditViewer` |
| POST | `/grants/{grantId}/vesting-records/archive` | Archive all non-archived `VestingRecord` rows for a grant. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/exercise-windows` | Create an `ExerciseWindow`. | `PlanAdministrator` |
| GET | `/option-plans/{planId}/exercise-windows` | List exercise windows. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `Grantee`, `AuditViewer` |
| POST | `/option-plans/{planId}/exercise-windows/sweep` | Run the window sweep. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/exercise-windows/{windowId}/archive` | Archive a `CLOSED` window. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/corporate-events` | Record a corporate event. | `PlanAdministrator` |
| GET | `/option-plans/{planId}/corporate-events` | List corporate events. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| GET | `/grant-batches/{batchId}/exercise-price-versions` | List a batch's price-version chain. | `PlanAdministrator`, `Grantee`, `AuditViewer` |
| POST | `/exercise-price-versions/{versionId}/disclose` | Mark a price version disclosed. | `PlanAdministrator` |
| POST | `/grants/{grantId}/exercise-applications` | Submit an exercise application against an `OPEN` window. | `Grantee` |
| GET | `/option-plans/{planId}/exercise-applications` | List exercise applications. | `PlanAdministrator`, `BoardSecretary`, `ShareholderRegistrar`, `AuditViewer` |
| POST | `/exercise-applications/{appId}/verify` | Verify eligibility (`SUBMITTED` to `ELIGIBILITY_VERIFIED`); cascades to `TAX_WITHHELD` for cash settlement. | `PlanAdministrator` |
| POST | `/exercise-applications/{appId}/pay` | Record payment for `SHARE_ISSUANCE` (`ELIGIBILITY_VERIFIED` to `PAYMENT_RECEIVED` to `TAX_WITHHELD`). | `PlanAdministrator` |
| POST | `/exercise-applications/{appId}/settle` | Settle the application (`TAX_WITHHELD` to `SETTLED`). | `PlanAdministrator` |
| POST | `/exercise-applications/{appId}/reject` | Reject application (`SUBMITTED` or `ELIGIBILITY_VERIFIED` to `REJECTED`). | `PlanAdministrator` |
| POST | `/exercise-applications/{appId}/cancel` | Grantee cancels their own `SUBMITTED` application. | `Grantee` |
| POST | `/grants/{grantId}/tax-events` | Record an out-of-band tax event (typically `SALE`). | `PlanAdministrator` |
| GET | `/grants/{grantId}/tax-events` | List tax events for a Grant. | `PlanAdministrator`, `Grantee`, `AuditViewer` |
| POST | `/tax-events/{eventId}/issue-document` | Issue a tax document. | `PlanAdministrator` |
| POST | `/option-plans/{planId}/grantees/{granteeId}/departure-records` | Create a departure record in `DRAFT`. | `PlanAdministrator` |
| POST | `/grantees/{granteeId}/departure-records/{depId}/settle` | Finalize the departure cascade (`DRAFT` to `SETTLED`). | `PlanAdministrator` |
| GET | `/option-plans/{planId}/departure-records` | List departure records. | `PlanAdministrator`, `AuditViewer` |
| GET | `/option-plans/{planId}/audit-log` | Query `AuditLogEntry` rows (append-only). | `PlanAdministrator`, `AuditViewer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_CROSS_RESOURCE_MISMATCH` | 422 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_BATCH_NOT_OPEN` | 409 |
| `ERR_GRANT_NOT_IN_DRAFT` | 409 |
| `ERR_GRANT_NOT_BOARD_APPROVED` | 409 |
| `ERR_GRANT_NOT_SHAREHOLDER_APPROVED` | 409 |
| `ERR_GRANT_NOT_LIVE` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_WINDOW_NOT_CLOSED` | 409 |
| `ERR_DEPARTURE_NOT_DRAFT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |
| `ERR_POOL_INSUFFICIENT` | 402 |
| `ERR_INSUFFICIENT_VESTED_QUANTITY` | 409 |
| `ERR_PERFORMANCE_CONDITION_NOT_MET` | 409 |
| `ERR_BLACKOUT_ACTIVE` | 409 |
| `ERR_BLACKOUT_OVERLAPS_WINDOW` | 409 |
| `ERR_INVALID_TIME_INTERVAL` | 422 |
| `ERR_NOT_IN_EXERCISE_WINDOW` | 409 |
| `ERR_GRANTEE_INELIGIBLE` | 403 |
| `ERR_GRANTEE_ALREADY_DEPARTED` | 409 |
| `ERR_BAD_LEAVER_REQUIRES_TERMINATION` | 422 |
| `ERR_PENDING_GRANTS_EXIST` | 409 |
| `ERR_OPEN_EXERCISES_EXIST` | 409 |
| `ERR_STALE_PRICE_VERSION` | 409 |
