# Talent Payroll Residuals API — Product Requirements Document

## 1. Introduction

Entertainment payroll operates under a tangle of union agreements, guild rules, tax jurisdictions, and reuse-market obligations that general-purpose payroll systems were never designed to express. A single performer's week on set can trigger meal and rest penalties calibrated to the governing union agreement, withholding obligations that vary by shoot location, pension-health-welfare contributions owed to guild funds, and — months after wrap — residual payments that arrive whenever a production is rebroadcast, syndicated, or licensed to a streaming platform. The cost of getting any of this wrong is not merely financial: unions file grievances, guilds audit, and state agencies levy penalties of their own.

This document specifies a Talent Payroll & Residuals Administration API that an entertainment payroll company operates on behalf of production companies. The system ingests union agreements with their rate-tier tables and penalty schedules, registers productions and performers, processes daily timecards with penalty calculations, determines taxable jurisdiction per shoot location, calculates residuals by reuse market and window, distributes payment through segregated batch workflows, administers garnishment orders and loan-out corporations, remits pension-health-welfare contributions to guild funds, and responds to union audits and grievances.

The design emphasizes three operational realities. First, segregation of duties is structural: the clerk who creates a pay batch may never approve or disburse that same batch. Second, money flows through an explicit lifecycle — no payment is final until a batch is disbursed, and every intermediate state is inspectable. Third, the system distinguishes provisional estimates (calculated at submission time from scheduled hours) from final amounts (calculated at approval time from actual timestamps), because unions routinely dispute the difference and both figures must be reconstructible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. Requests missing either header, carrying an unknown role, or carrying an empty user identifier are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Requests carrying a recognized role that is not permitted for the target endpoint are rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles are recognized, spelled exactly as follows:

- `PayrollAdmin`
- `ProductionAccountant`
- `PayrollClerk`
- `PayrollSupervisor`
- `UnionAuditor`

All five roles are **opaque operator identifiers**: when `X-User-Role` is any of `PayrollAdmin`, `ProductionAccountant`, `PayrollClerk`, `PayrollSupervisor`, or `UnionAuditor`, the value of `X-User-ID` is not tied to any persisted entity. The server records it where relevant — for example, as `created_by_user_id` on a `PayBatch` or `filed_by_user_id` on a `GrievanceCase` — but never compares it to any entity's `id` for ownership checks.

Read access is shared: all GET endpoints are available to every role. Mutations are role-gated per the endpoint table in §4.

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

Requests that match no route are rejected with `ERR_NOT_FOUND` (HTTP 404); a well-formed path with an unsupported method, and any unexpected server-side failure, surface as `ERR_VALIDATION` (HTTP 400) in the same error envelope.

### 2.3. Pagination

List endpoints accept optional `limit` and `offset` query parameters. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and must not be negative. A non-integer value, an out-of-range `limit`, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Results are sorted by `created_at` ascending, with ties broken by `id` ascending. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more` (`has_more` is true exactly when `offset` plus the returned page size is less than `total_count`). List endpoints additionally accept optional exact-match filter query parameters, scoped per resource: union agreements filter by `union_code` and `status`; productions by `union_agreement_id` and `status`; engagements by `production_id`, `performer_id`, `union_agreement_id`, `supersedes_engagement_id`, and `status`; timecards by `engagement_id`, `review_status`, and `payment_status`; penalty assessments by `timecard_id` and `status`; residual obligations by `engagement_id`, `reuse_market`, and `status`; pay lines by `pay_batch_id`, `engagement_id`, and `source_type`; garnishment orders by `performer_id` and `status`; remittance reports by `pay_batch_id`, `union_agreement_id`, and `status`; and grievance cases by `engagement_id`, `pay_line_id`, and `status`. Unrecognized query parameters are ignored.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources additionally carry `updated_at` (same format) and `version` (an integer starting at 1 and incrementing by 1 on every mutation).

Two ledger entities are exceptions. A `PenaltyAssessment` carries only `id` and `created_at`; it has neither `updated_at` nor `version`. A `PayLine` likewise carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Both are immutable once created except for the specific status transitions described in §3.

### 2.5. Monetary Precision and Rounding

All monetary amounts are integer cents. When a calculation produces a fractional cent, the rounding rule is **round half up** — a fraction of exactly one-half cent rounds away from zero. Rounding is applied per component before components are summed, never to the final aggregate. Where a calculation involves multiple steps (gross to tax to disposable to garnishment to net), each step rounds according to its own rule before the next step consumes the result.

### 2.6. Optimistic Concurrency Control

Creating an amendment engagement (a `POST /payroll/engagements` request with `supersedes_engagement_id` set) requires the request to carry `expected_engagement_version`, a non-optional integer field carrying the client's last observed `version` of the target engagement. If the target's current `version` does not match, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.7. Validation Priority

When a request violates multiple rules, the rejection surfaces the highest-priority failure. The ordering, from first to last evaluated, is:

1. Authentication (missing or malformed headers)
2. Authorization (role not permitted for the endpoint)
3. Existence of referenced identifiers (path parameters first, then foreign-key body fields, left to right); a missing identifier is rejected with `ERR_NOT_FOUND` (HTTP 404)
4. State gates on the target resource: batch lifecycle (`ERR_BATCH_INVALID_STATE`), timecard review (`ERR_TIMECARD_INVALID_STATE`), engagement lifecycle (`ERR_ENGAGEMENT_INVALID_STATE`), residual lifecycle (`ERR_RESIDUAL_INVALID_STATE`), small-entity lifecycle (`ERR_RESOURCE_INVALID_STATE`), agreement ratification (`ERR_AGREEMENT_INVALID_STATE`)
5. Business-safety rules (segregation of duties, agreement-ratified gate, engagement-active gate, residual compliance gate, production wrap gate)
6. Temporal shape and containment rules (date ordering, window containment, jurisdiction validity)
7. Business-constraint rules (agreement window overlap, performer double-booking, residual window overlap, duplicate work date, open batch uniqueness)
8. Business-referential rules (tier lookup, loan-out conditional fields, garnishment spec, market base percentage)
9. Business-fiscal rules (batch empty, grievance no-open-batch)
10. Remittance batch-disbursed gate
11. Generic request-shape validation — a missing required field, wrong type, unknown enum member, or negative amount, when no more specific rule above fired, is rejected with `ERR_VALIDATION` (HTTP 400)
12. Optimistic concurrency control

The numbered ordering governs precedence among the domain rules themselves. Generic request-shape validation (item 11) is not a single checkpoint: required-field, scalar-type, and enum checks run while the request body is read — before existence and state checks — while date-format checks run inline at the point each date is consumed, so a request that violates both a shape rule and a domain rule surfaces whichever failure the pipeline reaches first.

### 2.8. Temporal Conventions

All dates are ISO `YYYY-MM-DD`. All timestamps are ISO 8601 UTC with three fractional digits. Date windows described as "half-open" include the start and exclude the end; date windows described as "closed" or "inclusive" include both endpoints. A shared boundary date counts as overlap for closed-interval checks and does not count as overlap for half-open checks.

### 2.9. Polymorphic Pay Line Sources

A `PayLine` records its origin via `source_type` (one of `TIMECARD`, `RESIDUAL`, or `GRIEVANCE_ADJUSTMENT`) and `source_id`. The `source_id` is a polymorphic reference, not a foreign key: it holds a `Timecard.id` when `source_type` is `TIMECARD`, a `ResidualObligation.id` when `source_type` is `RESIDUAL`, and a `GrievanceCase.id` when `source_type` is `GRIEVANCE_ADJUSTMENT`. The `engagement_id` on a pay line is denormalized from the source at creation time so that filtering and year-to-date aggregation do not require joining through the source.

## 3. Business Logic & Workflows

### 3.1. Union Agreement Ingestion and Ratification

A `PayrollAdmin` ingests a union agreement by supplying a `union_code` (one of `SAG_AFTRA`, `WGA`, `DGA`, `AFM`, or `IATSE`), a human-readable `name`, an `effective_from` date, and an `effective_to` date. The agreement is created in `DRAFT` status. The ingestion payload also carries the agreement's rate table and penalty constants: `rate_tiers` (an array where each element has a `tier_code`, a `category` of `PRINCIPAL`, `BACKGROUND`, or `STUNT`, a `day_rate_cents`, an `ot_daily_threshold_minutes`, and an `ot_multiplier`; `tier_code` must be unique within the array), `meal_penalty_cents`, `rest_penalty_cents`, `turnaround_min_hours`, the three PHW percentages `phw_pension_pct`, `phw_health_pct`, `phw_welfare_pct`, and `residual_base_pct_by_market` (a map whose keys are drawn from `NETWORK_REBROADCAST`, `SYNDICATION`, `STREAMING`, `FOREIGN`, `HOME_VIDEO`, with at least one key required). Within `rate_tiers`, `day_rate_cents` must be a positive integer, `ot_daily_threshold_minutes` a positive integer, and `ot_multiplier` a number greater than or equal to 1.0; `meal_penalty_cents` and `rest_penalty_cents` are integers zero or greater; `turnaround_min_hours` and the three PHW percentages are numbers zero or greater; and the values of `residual_base_pct_by_market` must be numbers — shape failures in any of these are generic `ERR_VALIDATION` (HTTP 400) rejections. The `effective_to` must be strictly after `effective_from`; an inverted window is rejected with `ERR_INVALID_TEMPORAL`.

Ratification by a `PayrollAdmin` transitions the agreement from `DRAFT` to `RATIFIED` and increments its `version`. Ratification is refused with `ERR_AGREEMENT_WINDOW_OVERLAP` when another already-`RATIFIED` agreement with the same `union_code` has a half-open effective window overlapping this one. Two windows overlap when each starts before the other ends; adjacency — one agreement's `effective_to` landing exactly on the other's `effective_from` — is permitted and does not block ratification. Attempting to ratify an agreement that is not in `DRAFT` status is rejected with `ERR_AGREEMENT_INVALID_STATE`.

### 3.2. Production Registration and Lifecycle

A `PayrollAdmin` registers a production by supplying `title`, `production_company`, the `union_agreement_id` of the signatory agreement, a `production_type` (one of `FILM`, `TV_SERIES`, `COMMERCIAL`, `NEW_MEDIA`), and a `jurisdictions` array describing shoot-location tax obligations. Each element of `jurisdictions` carries a `jurisdiction_code`, a `tax_pct` (zero or greater), a `valid_from` date, and a `valid_to` date that is exclusive; `jurisdiction_code` must be unique within the array. Registration validates only the shape of each jurisdiction row — a non-empty unique code, a numeric `tax_pct` of zero or greater, and parseable dates; no ordering constraint between `valid_from` and `valid_to` is enforced. The production begins in `PRE_PRODUCTION` status.

Advancing a production moves it through `PRE_PRODUCTION` → `SHOOTING` → `WRAPPED` → `ARCHIVED`. The advance from `SHOOTING` to `WRAPPED` is gated: it is rejected with `ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS` while any engagement of the production remains in `PENDING_APPROVAL` or `AMENDMENT_PENDING`. When the gate passes, the advance cascades — every engagement of the production in `ACTIVE` or `AMENDMENT_PENDING` transitions to `WRAPPED` and has its own `version` incremented — and the production's `version` increments. Advances at other stages have no preconditions beyond the current state. Advancing an `ARCHIVED` production is rejected with `ERR_VALIDATION` (HTTP 400).

### 3.3. Performer Registration

A `PayrollAdmin` registers a performer with a `legal_name`, a `primary_union_code` drawn from the same five guild codes as union agreements, and a `tax_residency_state` (a two-letter state code; the server requires only a non-empty string and performs no format validation on it). The residency state matters later: it becomes the withholding jurisdiction for residual and grievance-adjustment pay lines, which have no shoot location of their own. Two computed fields, `ytd_gross_cents` and `ytd_garnished_cents`, start at zero and accumulate as batches disburse.

### 3.4. Engagement Contracting and Amendment

A `ProductionAccountant` creates an engagement by supplying `production_id`, `union_agreement_id`, `performer_id`, `tier_code`, `payee_type`, `weekly_guarantee_cents`, `guaranteed_days`, `start_date`, and `end_date`. The engagement is created in `DRAFT` status. `weekly_guarantee_cents` and `guaranteed_days` must be integers zero or greater. The `end_date` must be on or after `start_date`; otherwise the create is rejected with `ERR_INVALID_TEMPORAL`. The `tier_code` must match a `tier_code` present in the referenced agreement's `rate_tiers`; a mismatch is rejected with `ERR_TIER_NOT_FOUND`.

The `payee_type` is either `DIRECT` or `LOAN_OUT`. When `payee_type` is `DIRECT`, the performer is paid with tax withholding and garnishment exposure, and both `loan_out_legal_name` and `loan_out_tax_id` must be absent. When `payee_type` is `LOAN_OUT`, the loan-out corporation is paid gross — zero tax withholding, zero garnishment — and both `loan_out_legal_name` and `loan_out_tax_id` are required. Violating either conditional requirement is rejected with `ERR_LOAN_OUT_FIELDS`.

An engagement may be created as an amendment of an existing engagement by setting `supersedes_engagement_id`. The target engagement must exist and must currently be `ACTIVE`; a target in any other status is rejected with `ERR_VALIDATION` (HTTP 400), ahead of the version guard. The create request must also carry `expected_engagement_version` matching the target's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the product legitimately permits a new amendment to supersede the target and the version guard is what prevents a client from overwriting an amendment it has not observed. When the amendment create succeeds, the target engagement transitions from `ACTIVE` to `AMENDMENT_PENDING` and its `version` increments by 1.

Submitting an engagement moves it from `DRAFT` to `PENDING_APPROVAL` and increments its `version`. Submission against an engagement not in `DRAFT` status is rejected with `ERR_ENGAGEMENT_INVALID_STATE`; the same code rejects approve or reject against an engagement not in `PENDING_APPROVAL`. Submission requires the referenced union agreement to be `RATIFIED`; otherwise the submission is rejected with `ERR_AGREEMENT_NOT_RATIFIED`. Submission also runs a performer double-booking check: the submission is rejected with `ERR_PERFORMER_DOUBLE_BOOKED` when another engagement exists for the same performer with status `PENDING_APPROVAL`, `ACTIVE`, or `AMENDMENT_PENDING` and a closed-interval date overlap — that is, the other's `start_date` is on or before this engagement's `end_date` and this engagement's `start_date` is on or before the other's `end_date`, so a shared boundary date counts as a conflict. The engagement named by `supersedes_engagement_id` is excluded from this check, since an amendment is supposed to overlap its target.

Approval by a `PayrollSupervisor` moves the engagement from `PENDING_APPROVAL` to `ACTIVE` and increments its `version`. Approval requires the referenced production to be in `PRE_PRODUCTION` or `SHOOTING`; approval into a wrapped or archived production is rejected with `ERR_ENGAGEMENT_INVALID_STATE` (HTTP 409). If the engagement carries `supersedes_engagement_id`, approval simultaneously transitions the target from `AMENDMENT_PENDING` to `SUPERSEDED` and increments the target's `version`. Rejection by a `PayrollSupervisor` moves the engagement from `PENDING_APPROVAL` back to `DRAFT` and increments its `version`; if the engagement carries `supersedes_engagement_id`, rejection compensates the create-time side effect by transitioning the target from `AMENDMENT_PENDING` back to `ACTIVE` and incrementing the target's `version`.

### 3.5. Timecard Submission, Flagging, and Revision

A `ProductionAccountant` submits a timecard against an engagement by supplying `engagement_id`, `work_date`, `jurisdiction_code`, `call_time`, `first_meal_out`, `first_meal_in`, `wrap_time`, and `scheduled_hours`; `scheduled_hours` must be a number zero or greater. The timecard is created with `review_status` = `SUBMITTED` and `payment_status` = `UNBATCHED`, and its `day_gross_cents` and `final_penalty_cents` are carried as zero until approval.

Submission is gated on several conditions. The engagement must be `ACTIVE`; the production must be `SHOOTING`; a violation of either surfaces as `ERR_ENGAGEMENT_NOT_ACTIVE`. The `work_date` must fall inside the engagement's inclusive `start_date`-to-`end_date` window. The `jurisdiction_code` must match a production jurisdiction whose half-open validity window from `valid_from` to `valid_to` covers the `work_date`. The meal and wrap timestamps must be ordered: `first_meal_in` strictly after `first_meal_out`, and `wrap_time` strictly after `first_meal_in`. Any of these temporal failures is rejected with `ERR_INVALID_TEMPORAL`. Finally, at most one timecard per engagement per `work_date` is permitted; a duplicate is rejected with `ERR_DUPLICATE_WORK_DATE`.

On a successful submission, the server computes `worked_minutes` (the difference between `wrap_time` and `call_time`, minus the meal break duration from `first_meal_out` to `first_meal_in`, expressed in whole minutes with any fractional minute truncated down), `overtime_minutes` (the amount by which `worked_minutes` exceeds the engagement's tier `ot_daily_threshold_minutes`, floored at zero), and `provisional_penalty_cents` (an estimate from `scheduled_hours`; see §3.7).

Flagging by a `PayrollClerk` moves the timecard's `review_status` from `SUBMITTED` to `FLAGGED` and increments `version`; the request carries a mandatory `flag_reason`. The payment dimension is unrestricted by flagging. Revision by a `ProductionAccountant` moves a `FLAGGED` timecard back to `SUBMITTED` and increments `version`; the request carries corrected `call_time`, `first_meal_out`, `first_meal_in`, `wrap_time`, and `scheduled_hours`, and the server recomputes `worked_minutes`, `overtime_minutes`, and `provisional_penalty_cents` from the revised inputs. The revised timestamps are re-validated against the same ordering rules as submission (`first_meal_in` strictly after `first_meal_out`, `wrap_time` strictly after `first_meal_in`), with violations rejected as `ERR_INVALID_TEMPORAL`; the engagement window, the jurisdiction, and the `work_date` are not re-examined on revision. The flag-revise loop may repeat indefinitely until the timecard is approved.

### 3.6. Timecard Approval and Final Penalty Assessment

Approval by a `PayrollClerk` moves the timecard's `review_status` from `SUBMITTED` to `APPROVED` and increments `version`. Approval requires the payment dimension to still be `UNBATCHED` and the referenced engagement to still be `ACTIVE`; a stale or non-active engagement surfaces as `ERR_ENGAGEMENT_NOT_ACTIVE`, and any other state mismatch surfaces as `ERR_TIMECARD_INVALID_STATE`.

Two computations run at approval. First, the daily gross: the server looks up the engagement's tier in the governing agreement's `rate_tiers`, splits `worked_minutes` into regular minutes (the lesser of `worked_minutes` and the tier's `ot_daily_threshold_minutes`) and overtime minutes (the excess, floored at zero), converts the tier's `day_rate_cents` to an hourly rate by dividing by eight (since the day rate represents eight hours), then computes `day_gross_cents` as the sum of two independently rounded components — the regular component (regular minutes divided by sixty, multiplied by the hourly rate, rounded half-up to integer cents) plus the overtime component (overtime minutes divided by sixty, multiplied by the hourly rate, multiplied by the tier's `ot_multiplier`, rounded half-up to integer cents).

Second, the final penalty assessment. Three violation categories are evaluated against the actual timestamps:

- **MEAL**: the delay from `call_time` to `first_meal_out`, in minutes, is compared against a six-hour window. If the delay exceeds 360 minutes, one unit of violation is recorded; otherwise zero. The penalty amount is the unit count multiplied by the agreement's `meal_penalty_cents`.
- **REST**: the break duration from `first_meal_out` to `first_meal_in`, in minutes, is compared against a 30-minute minimum. If the break is shorter than 30 minutes, one unit of violation is recorded; otherwise zero. The penalty amount is the unit count multiplied by the agreement's `rest_penalty_cents`.
- **TURNAROUND**: the server finds the most recent prior timecard of the same engagement (the one with the greatest `work_date` strictly before this timecard's `work_date`; no tie-break is needed because `work_date` is unique per engagement). The gap in hours from the prior card's `wrap_time` to this card's `call_time` is compared against the agreement's `turnaround_min_hours`. If the gap is strictly shorter than the required minimum, the shortfall in hours is rounded up to the next whole hour to yield the violation units; a gap exactly equal to the minimum is not a violation. The penalty amount is the unit count multiplied by the tier's `day_rate_cents` divided by eight and rounded half-up.

The sum of the three amounts becomes `final_penalty_cents`. For each violation category with units greater than zero, a `PenaltyAssessment` row is created with `status` = `CONFIRMED`: the row records the `timecard_id` of the timecard being approved, the `penalty_type` (`MEAL`, `REST`, or `TURNAROUND`), the violation `units`, and the `amount_cents` (units multiplied by the applicable unit price from the governing agreement). The parent engagement's `accrued_penalty_cents` is then recomputed as the sum of `amount_cents` over all its `CONFIRMED` penalty assessments (waived assessments are excluded).

### 3.7. Provisional vs. Final Penalty Estimates

At timecard submission and revision, the server computes `provisional_penalty_cents` from `scheduled_hours` alone: one MEAL unit if `scheduled_hours` exceeds 6, zero otherwise; REST units are always zero in the provisional estimate; TURNAROUND is not estimable at submission and is treated as zero. The provisional estimate is `meal_penalty_cents` multiplied by the provisional MEAL unit count. For identical timestamps, provisional and final penalties routinely differ, because the provisional estimate ignores actual meal timing.

### 3.8. Penalty Waiver

A `PayrollSupervisor` may waive a `CONFIRMED` penalty assessment by supplying a mandatory `waiver_reason`. The waiver transitions the assessment from `CONFIRMED` to `WAIVED` and recomputes the parent engagement's `accrued_penalty_cents` to exclude the waived amount. A waiver against an assessment not in `CONFIRMED` status is rejected with `ERR_RESOURCE_INVALID_STATE`.

### 3.9. Residual Obligation Reporting and Calculation

A `ProductionAccountant` reports a residual obligation by supplying `engagement_id`, `reuse_market` (one of `NETWORK_REBROADCAST`, `SYNDICATION`, `STREAMING`, `FOREIGN`, `HOME_VIDEO`), `window_start`, `window_end`, and `reported_gross_receipts_cents`. The obligation is created in `REPORTED` status. The engagement must be `ACTIVE` or `WRAPPED`; otherwise the create is rejected with `ERR_COMPLIANCE_STATE`. The `window_end` must be on or after `window_start` (the window is a closed interval); an inverted window is rejected with `ERR_INVALID_TEMPORAL`. The chosen `reuse_market` must have a base percentage defined in the engagement's agreement `residual_base_pct_by_market`; a missing entry is rejected with `ERR_MARKET_BASE_PCT_MISSING`. Windows for the same engagement and the same `reuse_market` may not overlap on a closed-interval basis — the other's `window_start` on or before this `window_end` and this `window_start` on or before the other's `window_end` is a conflict, including a shared boundary date — and a violation is rejected with `ERR_RESIDUAL_WINDOW_OVERLAP`.

At creation, the server pins `base_pct` as a snapshot of the agreement's `residual_base_pct_by_market` entry for the chosen market; later edits to the agreement never retroactively change this row. The server also assigns `window_sequence`: the 1-based ordinal of this window among the engagement's obligations for the same `reuse_market`, ordered by `window_start` ascending with ties broken by `created_at` ascending. Finally, the server computes `provisional_amount_cents` as the engagement's tier `day_rate_cents` multiplied by the pinned `base_pct`, rounded half-up to integer cents — the tier day rate stands in as the estimate base until actual receipts are known. `final_amount_cents` is carried on the obligation as zero until the first calculation.

Calculation by a `PayrollClerk` transitions the obligation from `REPORTED` or `DISPUTED` to `CALCULATED` and increments `version`. Calculation against an obligation in any other status, approval against an obligation not in `CALCULATED`, and dispute against an obligation not in `APPROVED` are each rejected with `ERR_RESIDUAL_INVALID_STATE`. Calculation requires the engagement's union agreement to be `RATIFIED`; otherwise the request is rejected with `ERR_COMPLIANCE_STATE`. Calculation runs the final residual computation: `final_amount_cents` is the `reported_gross_receipts_cents` multiplied by the pinned `base_pct` and then by a window discount, with the final amount rounded half-up to integer cents. The window discount starts at full value for the first window and steps down by ten percentage points for each subsequent window — that is, the discount is one minus one-tenth times the zero-based window index — but never drops below one-half regardless of how many windows have been reported. When calculation runs from `DISPUTED`, the same pinned `base_pct` and `window_sequence` are reused, so a recalculation after a dispute reflects only the original snapshot.

Approval by a `PayrollSupervisor` transitions the obligation from `CALCULATED` to `APPROVED` and increments `version`. Dispute by a `UnionAuditor` transitions an `APPROVED` obligation to `DISPUTED` and increments `version`; the request carries a mandatory `dispute_reason`. The residual lifecycle thus permits a dispute loop: `APPROVED` → `DISPUTED` → `CALCULATED` → `APPROVED`, with each recalculation reusing the pinned snapshot.

### 3.10. Garnishment Orders

A `PayrollAdmin` enters a garnishment order against a performer by supplying `performer_id`, `creditor_name`, `order_type` (one of `CHILD_SUPPORT`, `FEDERAL_TAX_LEVY`, `STATE_TAX_LEVY`, `CREDITOR_JUDGMENT`), `priority_rank`, and exactly one of `pct_of_disposable` or `fixed_amount_cents`. Setting both, or neither, is rejected with `ERR_GARNISHMENT_SPEC_INVALID`. `priority_rank` is an integer with no sign constraint; `pct_of_disposable` must be a number and `fixed_amount_cents` an integer, with no further range constraints enforced. On a create request, the optional-pair type checks are evaluated before performer existence, which in turn precedes the exactly-one rule. The order is created in `ACTIVE` status with `total_withheld_cents` starting at zero.

Release by a `PayrollAdmin` transitions an `ACTIVE` order to `RELEASED` and increments its `version`. A released order is excluded from all future batch waterfalls, though its historical `total_withheld_cents` remains on record.

### 3.11. Pay Batch Lifecycle: Open, Close, Approve, Recall, Disburse

A `PayrollClerk` opens a pay batch by supplying `period_label` and `cutoff_date`. At most one batch may be `OPEN` at a time; attempting to open a second is rejected with `ERR_OPEN_BATCH_EXISTS`. The batch records `created_by_user_id` from the requesting `X-User-ID` — this becomes the segregation-of-duties anchor. All five totals (`total_gross_cents`, `total_tax_cents`, `total_garnished_cents`, `total_phw_cents`, `total_net_cents`) are zero while the batch is `OPEN`.

Closing the batch by a `PayrollClerk` transitions it from `OPEN` to `CLOSED` and increments `version`. Close against a batch not in `OPEN` status is rejected with `ERR_BATCH_INVALID_STATE`; the same code rejects approve against a non-`CLOSED` batch, and recall or disburse against a non-`APPROVED` batch. Close sweeps the eligible sources: timecards whose `review_status` is `APPROVED`, whose `payment_status` is `UNBATCHED`, and whose `work_date` is on or before the `cutoff_date`, plus residual obligations whose `status` is `APPROVED` and whose `window_end` is on or before the `cutoff_date`. If the sweep set is empty, the close is rejected with `ERR_BATCH_EMPTY`. For each swept source, a `PayLine` is created and the source's payment dimension advances: swept timecards move from `UNBATCHED` to `BATCHED`, and swept residuals move from `APPROVED` to `BATCHED`. The batch totals are then recomputed as sums over all pay lines of the batch — the newly created sweep lines plus any `GRIEVANCE_ADJUSTMENT` lines added while the batch was `OPEN`.

Approving a `CLOSED` batch by a `PayrollSupervisor` transitions it to `APPROVED` and increments `version`. Segregation of duties is enforced here: the approver's `X-User-ID` must differ from the batch's `created_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Recalling an `APPROVED` batch by a `PayrollSupervisor` is the compensating action: it transitions the batch back to `OPEN`, deletes every pay line of the batch, reverts each swept timecard from `BATCHED` to `UNBATCHED` (its `review_status` stays `APPROVED`), reverts each swept residual from `BATCHED` to `APPROVED`, resets all five batch totals to zero, and increments `version`. Recall never touches year-to-date aggregates, because those are computed only over `PAID` lines.

Disbursing an `APPROVED` batch by a `PayrollSupervisor` transitions it to `DISBURSED` and increments `version`. Disburse is the cascade point: every pay line of the batch flips from `UNPAID` to `PAID`; each flip cascades to the source, moving timecards from `BATCHED` to `PAID` and residuals from `BATCHED` to `PAID`; each source flip triggers a recompute of the parent engagement's `ytd_paid_cents` as the sum of `net_cents` over its `PAID` pay lines; each engagement recompute triggers a recompute of the performer's `ytd_gross_cents` (sum of `gross_cents` over `PAID` pay lines belonging to the performer) and `ytd_garnished_cents` (sum of `garnished_cents` over the same set); and every garnishment order that received an allocation during the waterfall has its `total_withheld_cents` updated. The disburse response returns the updated batch object; the cascaded effects on pay lines, sources, engagements, performers, and garnishment orders are observable through their respective read endpoints.

### 3.12. Pay Line Composition

Every pay line is created during batch close (or, for grievance adjustments, during grievance resolution) with `status` = `UNPAID`. The line's `gross_cents` depends on its `source_type`:

- For `TIMECARD` lines, `gross_cents` is the timecard's `day_gross_cents` plus the sum of `amount_cents` over that timecard's `CONFIRMED` penalty assessments.
- For `RESIDUAL` lines, `gross_cents` is the obligation's `final_amount_cents`.
- For `GRIEVANCE_ADJUSTMENT` lines, `gross_cents` is the grievance's `awarded_amount_cents`.

The line's `jurisdiction_code` is the withholding jurisdiction: for a `TIMECARD` line it is the timecard's `jurisdiction_code`; for `RESIDUAL` and `GRIEVANCE_ADJUSTMENT` lines it is the performer's `tax_residency_state`. The line's `tax_cents`, `garnished_cents`, `phw_cents`, and `net_cents` are computed per the waterfall in §3.13.

### 3.13. Pay Line Calculation Order: Gross, Tax, Disposable, Garnishment, PHW, Net

The evaluation order is pinned to break the apparent circle (the garnishment cap depends on disposable income, which depends on tax, which depends on gross):

1. `gross_cents` is taken from the source as described in §3.12.
2. `tax_cents` is computed from gross. For an engagement whose `payee_type` is `LOAN_OUT`, `tax_cents` is zero regardless of jurisdiction — loan-out corporations are paid gross. Otherwise, the withholding jurisdiction is looked up in the production's `jurisdictions` table, and `tax_cents` is the gross multiplied by that jurisdiction's `tax_pct`, rounded half-up to integer cents. For `RESIDUAL` and `GRIEVANCE_ADJUSTMENT` lines, the jurisdiction is the performer's `tax_residency_state`; if that state has no matching row in the production's jurisdiction table, the effective `tax_pct` is zero.
3. Disposable income is `gross_cents` minus `tax_cents`.
4. `garnished_cents` is allocated by the garnishment waterfall (§3.14).
5. `phw_cents` is computed from gross (§3.15) but is employer-side and never subtracted from the line.
6. `net_cents` is `gross_cents` minus `tax_cents` minus `garnished_cents`; for a `LOAN_OUT` engagement, `net_cents` equals `gross_cents` by construction.

### 3.14. Garnishment Waterfall

Garnishment allocates against disposable income within a single batch, per performer, across that performer's non-exempt lines. Two exemptions apply: lines belonging to a `LOAN_OUT` engagement are exempt, and `GRIEVANCE_ADJUSTMENT` lines are exempt regardless of payee type. Exempt lines always carry `garnished_cents` = 0.

The performer's non-exempt lines are processed in order by source `work_date` or `window_start` ascending, with ties broken by `created_at` ascending. For each line, the line cap is one-quarter of the line's disposable income, rounded half-up to integer cents — total garnished on a single line never exceeds 25 percent of that line's disposable. The waterfall then walks the performer's `ACTIVE` garnishment orders ordered by `priority_rank` ascending with ties broken by `created_at` ascending. For each order, the requested amount is the order's `fixed_amount_cents` if set, otherwise the line's disposable multiplied by the order's `pct_of_disposable`, rounded half-up to integer cents before any allocation. The allocated amount is the lesser of the requested amount and the remaining cap. The allocation is recorded against the order (to be applied to `total_withheld_cents` at disburse), and the remaining cap is reduced. The line's `garnished_cents` is the line cap minus whatever remains after all orders have been considered.

The pinned rounding order — round each order's request first, then allocate against the remaining cap — is load-bearing: it means a percentage-based order can request an amount that, combined with earlier allocations, lands exactly on or below the line cap without drift.

### 3.15. Pension, Health, and Welfare Contributions

The employer-side PHW contribution on a pay line is the sum of three independently rounded components: the gross multiplied by the agreement's `phw_pension_pct` (rounded half-up), the gross multiplied by the agreement's `phw_health_pct` (rounded half-up), and the gross multiplied by the agreement's `phw_welfare_pct` (rounded half-up). The sum of the three rounded components is the line's `phw_cents`. PHW is never subtracted from `net_cents`; it is an employer obligation owed to the guild funds, tracked separately.

### 3.16. Remittance Reports

Once a batch has been disbursed, a `PayrollClerk` creates a remittance report by supplying `pay_batch_id` and `union_agreement_id`. Creation requires the referenced batch to be `DISBURSED`; a batch in any other state is rejected with `ERR_BATCH_NOT_DISBURSED`. No ratification state is required of the referenced agreement. The report aggregates the employer PHW contributions of the disbursed batch for one union agreement: it selects every pay line of the batch whose engagement is governed by the named agreement, and for each of the three funds sums the per-line rounded amounts — pension is the sum over matching lines of each line's gross multiplied by the agreement's `phw_pension_pct` and rounded half-up; health and welfare follow the same pattern with their respective percentages. Because per-line rounding matches the pay-line computation, `pension_cents` plus `health_cents` plus `welfare_cents` equals the sum of `phw_cents` over the matching lines. The report is created in `DRAFT` status.

Submission by a `PayrollClerk` moves the report from `DRAFT` to `SUBMITTED` and increments `version`. Acknowledgement by a `PayrollAdmin` moves the report from `SUBMITTED` to `ACKNOWLEDGED` and increments `version`; acknowledgement records that the guild fund confirmed receipt.

### 3.17. Grievance Cases

A `UnionAuditor` files a grievance by supplying `engagement_id`, an optional `pay_line_id` (when the grievance targets a specific payment), a `category` (one of `UNDERPAYMENT`, `PENALTY_OMITTED`, `RESIDUAL_MISCALC`, `PHW_SHORTAGE`), a `claimed_amount_cents`, and a free-text `description`. The grievance is created in `FILED` status, and the filing auditor's `X-User-ID` is recorded as `filed_by_user_id`. `awarded_amount_cents` is zero until resolution.

Response by a `PayrollClerk` moves the grievance from `FILED` to `UNDER_REVIEW` and increments `version`; the request carries a mandatory `response_note`. Escalation by a `UnionAuditor` moves a grievance from `UNDER_REVIEW` to `ESCALATED` and increments `version`. Resolution by a `PayrollSupervisor` moves a grievance from either `UNDER_REVIEW` or `ESCALATED` to `RESOLVED` and increments `version`; the request carries `awarded_amount_cents`. When the awarded amount is greater than zero, exactly one pay batch must currently be `OPEN` — otherwise the resolution is rejected with `ERR_NO_OPEN_BATCH`. A positive award creates a `GRIEVANCE_ADJUSTMENT` pay line in the open batch, with `source_id` pointing at the grievance, `status` = `UNPAID`, and `gross_cents` equal to the award; the line's `tax_cents` and `phw_cents` are computed at resolution time per §3.13 — tax from the performer's residency jurisdiction, PHW from the governing agreement's percentages — and, since the line is garnishment-exempt, `garnished_cents` is zero and `net_cents` is `gross_cents` minus `tax_cents`. The creation of this line recomputes the engagement's `accrued_adjustment_cents` as the sum of `gross_cents` over its `GRIEVANCE_ADJUSTMENT` pay lines; this recompute happens only at line creation, so a later deletion of the line (for example, by a batch recall) does not recompute it.

## 4. Endpoint Definitions

Endpoints are mounted under `/payroll`. Creating a new resource returns HTTP 201; modifying an existing resource returns HTTP 200. All list endpoints return HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|-------------------|
| POST | /payroll/union-agreements | Ingest a union agreement with its rate-tier table and penalty/PHW constants; created DRAFT | PayrollAdmin |
| GET | /payroll/union-agreements | List agreements | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/union-agreements/{id}/ratify | Ratify a DRAFT agreement; rejects on half-open window overlap with another RATIFIED agreement of the same union_code | PayrollAdmin |
| POST | /payroll/productions | Create a production with its shoot-location jurisdiction table | PayrollAdmin |
| GET | /payroll/productions | List productions | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/productions/{id} | Read one production | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/productions/{id}/advance | Advance PRE_PRODUCTION → SHOOTING → WRAPPED → ARCHIVED; WRAPPED blocked while engagements are open; wrapping cascades engagements ACTIVE/AMENDMENT_PENDING → WRAPPED | PayrollAdmin |
| POST | /payroll/performers | Register a performer | PayrollAdmin |
| GET | /payroll/performers/{id} | Read one performer (including YTD aggregates) | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/engagements | Create an engagement (contract) DRAFT; with supersedes_engagement_id it is an amendment and the target flips ACTIVE → AMENDMENT_PENDING under OCC | ProductionAccountant |
| GET | /payroll/engagements | List engagements | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/engagements/{id} | Read one engagement | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/engagements/{id}/submit | DRAFT → PENDING_APPROVAL; requires RATIFIED agreement; performer double-booking check | ProductionAccountant |
| POST | /payroll/engagements/{id}/approve | PENDING_APPROVAL → ACTIVE; production must be PRE_PRODUCTION or SHOOTING; amendment approval supersedes the target | PayrollSupervisor |
| POST | /payroll/engagements/{id}/reject | PENDING_APPROVAL → DRAFT; a rejected amendment restores its target AMENDMENT_PENDING → ACTIVE | PayrollSupervisor |
| POST | /payroll/timecards | Submit a timecard; computes worked/overtime minutes and provisional penalties; requires engagement ACTIVE, production SHOOTING, valid jurisdiction, unique work_date per engagement | ProductionAccountant |
| GET | /payroll/timecards | List timecards | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/timecards/{id} | Read one timecard | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/timecards/{id}/flag | SUBMITTED → FLAGGED for correction | PayrollClerk |
| POST | /payroll/timecards/{id}/revise | FLAGGED → SUBMITTED with corrected timestamps; recomputes derived fields and provisional penalties | ProductionAccountant |
| POST | /payroll/timecards/{id}/approve | SUBMITTED → APPROVED; requires engagement ACTIVE; computes final day gross and creates CONFIRMED PenaltyAssessments | PayrollClerk |
| GET | /payroll/penalty-assessments | List penalty assessments | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/penalty-assessments/{id} | Read one penalty assessment | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/penalty-assessments/{id}/waive | CONFIRMED → WAIVED with mandatory reason; recomputes engagement accrued penalties | PayrollSupervisor |
| POST | /payroll/residual-obligations | Report a reuse market window; snapshots base_pct, computes window_sequence and provisional amount; rejects overlapping closed windows per engagement+market | ProductionAccountant |
| GET | /payroll/residual-obligations | List residual obligations | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/residual-obligations/{id} | Read one residual obligation | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/residual-obligations/{id}/calculate | REPORTED or DISPUTED → CALCULATED; computes final_amount_cents from reported receipts × pinned base_pct × window discount; requires RATIFIED agreement | PayrollClerk |
| POST | /payroll/residual-obligations/{id}/approve | CALCULATED → APPROVED (eligible for batch sweep) | PayrollSupervisor |
| POST | /payroll/residual-obligations/{id}/dispute | APPROVED → DISPUTED with mandatory reason (union disputes the calculation) | UnionAuditor |
| POST | /payroll/pay-batches | Open a pay batch; at most one OPEN batch at a time | PayrollClerk |
| GET | /payroll/pay-batches/{id} | Read one batch (including totals) | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/pay-batches/{id}/close | OPEN → CLOSED; sweeps eligible timecards and residuals into PayLines, running gross/tax/garnishment/PHW/net per line and batch totals | PayrollClerk |
| POST | /payroll/pay-batches/{id}/approve | CLOSED → APPROVED; approver must differ from creator (segregation of duties) | PayrollSupervisor |
| POST | /payroll/pay-batches/{id}/recall | APPROVED → OPEN; deletes pay lines, reverts sources, zeroes totals (compensating action) | PayrollSupervisor |
| POST | /payroll/pay-batches/{id}/disburse | APPROVED → DISBURSED; cascades PAID down pay lines to sources, recomputes engagement YTD and performer YTD, applies garnishment withholdings | PayrollSupervisor |
| GET | /payroll/pay-lines | List pay lines | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/pay-lines/{id} | Read one pay line | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/garnishment-orders | Enter a garnishment order against a performer; exactly one of pct_of_disposable / fixed_amount_cents | PayrollAdmin |
| GET | /payroll/garnishment-orders | List garnishment orders | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/garnishment-orders/{id} | Read one garnishment order | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/garnishment-orders/{id}/release | ACTIVE → RELEASED; excluded from future batch waterfalls | PayrollAdmin |
| POST | /payroll/remittance-reports | Aggregate PHW contributions of a DISBURSED batch for one union agreement | PayrollClerk |
| GET | /payroll/remittance-reports | List remittance reports | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/remittance-reports/{id} | Read one remittance report | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/remittance-reports/{id}/submit | DRAFT → SUBMITTED to the guild fund | PayrollClerk |
| POST | /payroll/remittance-reports/{id}/acknowledge | SUBMITTED → ACKNOWLEDGED (fund confirmed receipt) | PayrollAdmin |
| POST | /payroll/grievance-cases | Union files a grievance against an engagement (optionally a specific pay line) | UnionAuditor |
| GET | /payroll/grievance-cases | List grievance cases | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| GET | /payroll/grievance-cases/{id} | Read one grievance case | PayrollAdmin, ProductionAccountant, PayrollClerk, PayrollSupervisor, UnionAuditor |
| POST | /payroll/grievance-cases/{id}/respond | FILED → UNDER_REVIEW with a response note | PayrollClerk |
| POST | /payroll/grievance-cases/{id}/escalate | UNDER_REVIEW → ESCALATED (union escalates to arbitration track) | UnionAuditor |
| POST | /payroll/grievance-cases/{id}/resolve | UNDER_REVIEW or ESCALATED → RESOLVED; a positive award creates a GRIEVANCE_ADJUSTMENT pay line in the OPEN batch | PayrollSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-----------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_BATCH_INVALID_STATE | 409 |
| ERR_TIMECARD_INVALID_STATE | 409 |
| ERR_ENGAGEMENT_INVALID_STATE | 409 |
| ERR_RESIDUAL_INVALID_STATE | 409 |
| ERR_RESOURCE_INVALID_STATE | 409 |
| ERR_AGREEMENT_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_AGREEMENT_NOT_RATIFIED | 409 |
| ERR_ENGAGEMENT_NOT_ACTIVE | 409 |
| ERR_COMPLIANCE_STATE | 409 |
| ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS | 409 |
| ERR_INVALID_TEMPORAL | 422 |
| ERR_AGREEMENT_WINDOW_OVERLAP | 409 |
| ERR_PERFORMER_DOUBLE_BOOKED | 409 |
| ERR_RESIDUAL_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE_WORK_DATE | 409 |
| ERR_OPEN_BATCH_EXISTS | 409 |
| ERR_TIER_NOT_FOUND | 422 |
| ERR_LOAN_OUT_FIELDS | 422 |
| ERR_GARNISHMENT_SPEC_INVALID | 422 |
| ERR_MARKET_BASE_PCT_MISSING | 422 |
| ERR_BATCH_EMPTY | 422 |
| ERR_NO_OPEN_BATCH | 422 |
| ERR_BATCH_NOT_DISBURSED | 409 |
