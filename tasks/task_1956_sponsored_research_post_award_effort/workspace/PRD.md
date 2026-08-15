# Sponsored Research Post-Award & Effort Reporting API — Product Requirements Document

## 1. Introduction

University sponsored-programs offices live under two converging pressures: the federal-uniform-guidance expectation that every dollar charged to a grant be allowable, allocable, reasonable, and consistently treated, and the operational reality that a single post-award ledger touches budgets, payroll effort, subrecipients, sponsor drawdowns, and final closeout all at once. When those threads are tracked in disconnected spreadsheets, the failure modes are predictable — a retroactive cost transfer slips through without a countersignature, an effort certifier attests against salary figures that changed under them, a letter-of-credit draw is priced against a stale pool, or a closeout goes through with an unliquidated receivable still open.

This document specifies a Sponsored Research Post-Award & Effort Reporting API that centralizes those workflows behind a single, audited, logically-clocked service. It covers sponsor and award setup with budget-load by category, expenditure allowability review with salary-cap handling, cost-transfer justification with segregation of duties, cyclical effort certification with key-personnel floors, subaward invoice monitoring, no-cost-extension and rebudget requests, sponsor invoicing and letter-of-credit drawdown with receivable aging, and final closeout with residual deobligation. Every mutation is atomically visible with its cascades, every monetary figure is integer cents, and every clock-dependent rule runs against a logical clock that tests can drive.

The reader is assumed to be an engineer implementing the service. Business narrative is deliberately spread across §3 so that the full contract for any single operation must be reconstructed from its workflow context; §2 pins the cross-cutting rules, §4 lists the HTTP surface, and §5 enumerates error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, presenting a malformed header, or naming a role outside the declared set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorized-role list; a role not permitted on the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A third ownership check applies to the two entity-backed roles and surfaces as `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

Seven roles exist. `SystemAdmin` is the platform operator and owns only the logical-clock test-driving capability. `SponsoredProgramsOfficer` staffs the central sponsored-programs office: it creates sponsors, persons, awards, and subawards, activates awards and subawards, reviews subaward invoices, countersigns retroactive cost transfers, internal-approves modification requests, and schedules report requirements. `GrantCoordinator` is the department research administrator: it loads budget lines, records effort commitments, submits expenditures, records subaward invoices, creates and submits modification requests, and submits reports on behalf of a project. `GrantsAccountant` is the central post-award accountant: it posts and disallows expenditures, approves cost transfers, runs effort cycles, reopens effort statements, creates and submits drawdown requests, bills sponsors through receivables, records payments and disputes, and drives closeout and the final financial report. `SponsorOfficial` is the sponsor-side actor: it suspends, reinstates, and reopens awards, settles or rejects drawdowns, accepts or rejects reports, decides sponsor-review modifications, and accepts or returns final financial reports. `PrincipalInvestigator` and `ResearchStaff` are entity-backed research personnel who certify their own effort statements; `PrincipalInvestigator` additionally submits reports on their own awards. All seven roles may call any GET endpoint.

For the five opaque roles — `SystemAdmin`, `SponsoredProgramsOfficer`, `GrantCoordinator`, `GrantsAccountant`, and `SponsorOfficial` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` on an expenditure or `created_by_user_id` on a cost transfer) but never compares it to an entity `id`. For the two entity-backed roles the story is different: when `X-User-Role` is `PrincipalInvestigator` or `ResearchStaff`, `X-User-ID` is the `id` of the acting `Person`; ownership checks on any resource that references a `Person` compare the resource's foreign-key field to `X-User-ID`. In practice this means a `PrincipalInvestigator` or `ResearchStaff` may only certify an `EffortStatement` whose `person_id` equals `X-User-ID`, and a `PrincipalInvestigator` may only submit a `ReportRequirement` for an award whose `pi_id` equals `X-User-ID`; violations return `ERR_FORBIDDEN_OWNERSHIP`.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; the default `offset` is 0. The response `meta` block carries `limit`, `offset`, `total_count`, and `has_more` so a caller can page deterministically. All list endpoints sort by `created_at` ascending; the sort is stable and never falls back to `id`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` minted by the server as a UUID with no type prefix. With one exception noted below, every resource also carries `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that starts at 1 and increments by one on every mutation of that resource. The exception is `EffortCommitment`: commitments carry only `id` and `created_at`, with no `updated_at` and no `version`, because a commitment is immutable once recorded.

Time inside the system is governed by a logical clock, not the wall clock. At startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `SystemAdmin` may advance the clock to a supplied `to_iso8601` instant; doing so triggers an overdue sweep over report requirements, a posture recompute on every award (with the FROZEN drawdown auto-cancellation cascade), and a recompute of receivable aging and accrued interest. The clock-setting response returns the new value as `current_utc`.

### 2.5. Monetary Representation, Rounding, and Percentages

All money fields are integer cents. Percentages that appear on effort records (`committed_effort_pct`, `charged_effort_pct`, `certified_effort_pct`, `variance_pp`, and the request-side `effort_pct`) carry two decimal places and are rounded half-up; the same two-decimal half-up rule applies to `period_months`. Unless a calculation rule explicitly states otherwise, every derived monetary quantity is rounded half-up to integer cents. Where a multi-step calculation is specified, the rounding order is pinned: intermediate monthly rates are rounded first, then products; fringe is rounded per salary expenditure line before any aggregation; late interest is rounded once per receivable and an aging report sums those per-receivable rounded values rather than rounding a fleet-wide total. Whole-day durations (for example `days_since_posting`, `days_overdue`, `days_outstanding`, `total_disputed_days`) are integer day counts between two logical-clock instants.

### 2.6. Optimistic Concurrency Control

Three write operations take a client-supplied expected version of a parent entity and reject the request when the parent's current `version` has advanced past it. Creating a drawdown request requires `expected_award_version` matching the target award's current `version`; a mismatch is rejected with `ERR_STALE_AWARD_VERSION` (HTTP 412), because the eligible-pool computation the client priced its amount against may have shifted. Creating a modification request likewise requires `expected_award_version` matching the award's current `version`, with the same `ERR_STALE_AWARD_VERSION` (HTTP 412) on mismatch, because rebudget line sets and no-cost-extension arithmetic are computed against the baselines and `current_end_date` the client observed. Certifying an effort statement requires `expected_effort_statement_version` matching the statement's current `version`; a mismatch is rejected with `ERR_STALE_STATEMENT_VERSION` (HTTP 412), because a payroll posting in the cycle window silently recomputes `charged_effort_pct` and bumps the statement's `version`, and the certifier would otherwise attest against a charged figure they never saw. Endpoints not listed here take no version field.

### 2.7. Validation Ordering — First Failure Wins

When several validation rules could fire on the same request, the server evaluates them in a fixed priority order and returns only the first failure. The order is: (1) header authentication (`ERR_UNAUTHENTICATED`); (2) role authorization on the endpoint (`ERR_FORBIDDEN_ROLE`); (3) ownership scoping for entity-backed roles (`ERR_FORBIDDEN_OWNERSHIP`); (4) existence of path ids and body foreign-key references, validated left-to-right — path first, then body fields in declared order — with one 404 error per resource type: `ERR_SPONSOR_NOT_FOUND`, `ERR_PERSON_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_BUDGET_LINE_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_EXPENDITURE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_SUBAWARD_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DRAWDOWN_NOT_FOUND`, `ERR_RECEIVABLE_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, and `ERR_FFR_NOT_FOUND`; (5) optimistic-concurrency version checks (`ERR_STALE_AWARD_VERSION` / `ERR_STALE_STATEMENT_VERSION`); (6) state-machine transition validity, including the per-machine state errors such as `ERR_AWARD_NOT_ACTIVE` and `ERR_CLOSEOUT_INCOMPLETE`; (7) the award posture gate (`ERR_AWARD_RESTRICTED`, `ERR_AWARD_FROZEN`); (8) compliance and safety rules (allowability, segregation of duties, enhanced justification, transferability, audit reference); (9) temporal rules (period-of-performance, invoice period range, NCE timing, closeout timing, cycle openability); (10) structural constraints (window overlaps, uniqueness, zero-sum rebudget, system-managed lines and types, variance note, effort totals); (11) referential mappings (line-award match, category-type mapping, salary commitment, transfer target distinctness, payment-method match); (12) fiscal ceilings and floors (line sufficiency, activation exact-allocation, drawdown pool, subaward cumulative ceiling, receivable overpayment, unliquidated obligations, MTDC-eligible cap, no-uninvoiced-costs); and finally (13) request shape (`ERR_INVALID_REQUEST`). A request that is both malformed and unauthorized therefore returns `ERR_FORBIDDEN_ROLE`, never `ERR_INVALID_REQUEST`.

### 2.8. Money, Pool, and Effort Conservation Invariants

Three invariants hold at all times and are worth internalizing before reading the workflows. First, a cost transfer never creates or destroys direct cost: for a transfer of amount A from source award S to target award G, the sum of `spent_cents` over all budget lines of S plus the sum over all lines of G is identical before and after approval — the source line is credited by A and the target line is debited by A. Second, on letter-of-credit awards the eligible draw pool partitions exactly: `eligible_pool` equals `cumulative_drawn_cents` plus `reserved_draw_cents` plus `available_draw_pool_cents` at every instant; submitting a draw moves amount from available to reserved, settling moves it from reserved to drawn, rejecting or cancelling moves it from reserved back to available, and posting an expenditure adds the amount plus its F&A share to both eligible and available. Third, effort certification distributes a fixed 100% of institutional effort per person per cycle: at cycle close, the sum of `certified_effort_pct` over all of a person's statements (AWARD and NON_SPONSORED together) must equal exactly 100.00.

### 2.9. Derived Award Posture

Alongside its lifecycle `status`, every award carries a derived gating dimension called `posture` with values `OPEN`, `RESTRICTED`, and `FROZEN`. Posture is recomputed whenever the logical clock advances, when a report is submitted, accepted, or rejected, when the final financial report is submitted or accepted, and at initiate-closeout and reinstate. The derivation uses two constants: the final financial report falls due 120 days after the award's `current_end_date`, and a 30-day grace applies to final-report lateness. An award is `FROZEN` when any `FINAL_TECHNICAL` report requirement has `days_overdue` greater than 30, or when the FFR itself is more than 30 days past its due date while the award is in `CLOSEOUT_PENDING` with the FFR not yet `ACCEPTED`. Otherwise it is `RESTRICTED` when any report requirement is `OVERDUE`, or when the FFR is past due by at least one day. Otherwise it is `OPEN`. On entering `FROZEN`, every drawdown request of the award in `DRAFT` or `SUBMITTED` status is cancelled and any reservation is released back to the available pool. The posture gates financial writes: expenditure create and drawdown submit require posture `OPEN` (a `RESTRICTED` award returns `ERR_AWARD_RESTRICTED`, a `FROZEN` award returns `ERR_AWARD_FROZEN`); expenditure post, cost-transfer approve and countersign, and subaward-invoice approve require posture other than `FROZEN` (`ERR_AWARD_FROZEN`). Effort certification and report submission are never posture-gated.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Award: Sponsors, Personnel, and Budget Load

A sponsored-programs engagement begins with the `Sponsor`. A `SponsoredProgramsOfficer` registers the sponsor with its `name`, a `sponsor_type` drawn from `FEDERAL`, `FEDERAL_FLOW_THROUGH`, `INDUSTRY`, `FOUNDATION`, or `STATE`, and a `payment_method` of `LETTER_OF_CREDIT`, `COST_REIMBURSABLE_INVOICE`, or `FIXED_PRICE_SCHEDULE` — the payment method is inherited by every award created under the sponsor. Two rate parameters travel with the sponsor: `f_and_a_rate_bps`, the negotiated indirect rate in basis points applied to the modified total direct cost base, and `late_payment_apr_bps`, an annual-percentage-rate in basis points used for receivable late-interest accrual beyond the grace period (defaulting to 0 when omitted). A federal sponsor may also carry `salary_cap_annual_cents`, a 12-month-equivalent salary rate cap; omitting it or passing null means no cap applies. Personnel are registered as `Person` records with `full_name`, a `role_type` of `PRINCIPAL_INVESTIGATOR` or `RESEARCH_STAFF`, an `institutional_base_salary_annual_cents` strictly greater than zero, and `appointment_months` of either 9 (academic-year) or 12 (calendar-year), which drives the monthly IBS rate used everywhere downstream.

With sponsor and PI in place, the officer creates the `GrantAward` by supplying `sponsor_id`, `pi_id`, a globally unique `award_number` (a duplicate returns `ERR_DUPLICATE_AWARD_NUMBER`), `title`, `project_start_date`, `original_end_date`, `total_obligated_cents` (zero or more), the award's provisional `fringe_rate_bps`, and optionally `cost_share_committed_cents` (default 0). Three fields are copied from the sponsor at creation and pinned to the award forever: `salary_cap_annual_cents`, `f_and_a_rate_bps`, and `payment_method` — later sponsor edits never propagate. The new award starts in `PENDING_SETUP` with `posture` `OPEN`, `current_end_date` equal to `original_end_date`, `nce_count` 0, all computed aggregates (`mtdc_spent_cents`, `f_and_a_accrued_cents`, `total_direct_spent_cents`, `cost_share_met_cents`, `cumulative_drawn_cents`, `reserved_draw_cents`, `available_draw_pool_cents`) at 0, `residual_deobligated_cents` null, and a system-created `F_AND_A` budget line with `authorized_cents` 0.

A `GrantCoordinator` then loads the budget, one `BudgetLine` per category, naming the `award_id`, a `category` from `PERSONNEL_SALARIES`, `FRINGE_BENEFITS`, `EQUIPMENT`, `TRAVEL`, `PARTICIPANT_SUPPORT`, `MATERIALS_SUPPLIES`, `SUBAWARDS`, or `OTHER_DIRECT`, and the `authorized_cents`. Lines may only be loaded while the award is in `PENDING_SETUP`. The `F_AND_A` category is system-managed: attempting to create or modify an `F_AND_A` line by hand is rejected with `ERR_F_AND_A_LINE_SYSTEM_MANAGED`. Instead, after each direct-line load the system recomputes the `F_AND_A` line's authorization over authorized bases: it sums `authorized_cents` over every non-`F_AND_A` line to get directs-authorized, subtracts the authorizations of `EQUIPMENT`, `PARTICIPANT_SUPPORT`, and `SUBAWARDS` lines and adds back the `mtdc_eligible_cents` declared on `SUBAWARDS` lines to get the MTDC-authorized base, multiplies by the award's pinned `f_and_a_rate_bps` (basis points over ten thousand), rounds half-up to cents, and stamps the result as the `F_AND_A` line's `authorized_cents`. On a `SUBAWARDS` line the caller may declare `mtdc_eligible_cents` — the portion counting toward MTDC, typically the first 25,000 USD per planned subaward — which must not exceed the line's `authorized_cents` (`ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED`) and defaults to 0; on any other category the field is meaningless. Each line also tracks `spent_cents` (starting at 0) and a `baseline_authorized_cents` snapshot, and every budget-line load increments the parent award's `version`.

Activation is the gate that turns a loaded budget into a spending instrument. A `SponsoredProgramsOfficer` activates the award only when the grand total — directs-authorized plus the computed `F_AND_A` authorization — equals `total_obligated_cents` exactly; one cent under or over fails with `ERR_BUDGET_NOT_FULLY_ALLOCATED`. Activation also requires at least one non-`F_AND_A` line to exist (otherwise `ERR_INVALID_REQUEST`). On success the award moves `PENDING_SETUP → ACTIVE`, every line's `baseline_authorized_cents` is set equal to its current `authorized_cents` (the sponsor-approved baseline against which later rebudget significance is measured), posture is recomputed, and the award's `version` increments. Thereafter a `SponsorOfficial` may suspend an `ACTIVE` award (recording an optional `reason`), moving it to `SUSPENDED` and blocking all financial writes — expenditure create and post, drawdown create and submit, transfer approve, invoice approve, and modification submit — by state validation; reinstatement returns it to `ACTIVE` with a posture recompute, and reinstating an award that is not `SUSPENDED` fails with `ERR_AWARD_NOT_SUSPENDED`.

### 3.2. Commitments, Expenditures, and the Four-Link Posting Cascade

Effort commitments anchor everything salary-related. A `GrantCoordinator` records an `EffortCommitment` naming `award_id`, `person_id`, `committed_effort_pct` (greater than 0 and at most 100, with two decimal places), and optionally `is_key_personnel` (default false) — key personnel trigger the 75% reduction floor at certification time. Commitments may be recorded while the award is `PENDING_SETUP` or `ACTIVE`, the pair (`award_id`, `person_id`) is unique (a duplicate returns `ERR_DUPLICATE_COMMITMENT`), and — unlike other resources — a commitment carries only `id` and `created_at`, never `updated_at` or `version`.

Expenditures enter through the coordinator as well. Creating an `Expenditure` requires the award's posture to be `OPEN` — a `RESTRICTED` award rejects the create with `ERR_AWARD_RESTRICTED` and a `FROZEN` award with `ERR_AWARD_FROZEN` — and requires the award itself not to be `SUSPENDED`. The payload names `award_id`, `budget_line_id`, an `expenditure_type` of `SALARY`, `TRAVEL`, `EQUIPMENT`, `SUPPLIES`, `PARTICIPANT_SUPPORT`, `OTHER_DIRECT`, or `SUBAWARD_PAYMENT`, the `transaction_date`, and three allowability attestations: `is_allocable`, `is_reasonable`, and `is_consistent`. Optional fields are `description` (free-text memo), `is_cost_share` (default false), and `cash_disbursed` (default false — the flag that gates inclusion in the cash-basis draw pool). The line named by `budget_line_id` must belong to the same award (`ERR_BUDGET_LINE_AWARD_MISMATCH`), and the expenditure type must match the line's category under a fixed mapping: `SALARY` charges a `PERSONNEL_SALARIES` line, `TRAVEL` a `TRAVEL` line, `EQUIPMENT` an `EQUIPMENT` line, `SUPPLIES` a `MATERIALS_SUPPLIES` line, `PARTICIPANT_SUPPORT` a `PARTICIPANT_SUPPORT` line, and `OTHER_DIRECT` an `OTHER_DIRECT` line; any mismatch returns `ERR_CATEGORY_TYPE_MISMATCH`. The `SUBAWARD_PAYMENT` type is system-managed — created only by subaward-invoice approval — and a manual attempt returns `ERR_EXPENDITURE_TYPE_SYSTEM_MANAGED`.

For non-salary types the caller supplies `amount_cents`. For `SALARY` the caller instead supplies `person_id`, `effort_pct` (greater than 0 and at most 100, two decimals), and `period_months` (greater than 0, at most 12, up to two decimals), and the charge is computed; any `amount_cents` input is ignored. The computation first derives the person's monthly IBS rate as their `institutional_base_salary_annual_cents` divided by `appointment_months`, rounded half-up to cents. When the award carries a salary cap, the cap monthly rate is the award's `salary_cap_annual_cents` divided by 12 — the cap is always a 12-month-equivalent rate — rounded half-up, and the billable monthly rate is the lesser of the two monthly rates; when there is no cap, or the IBS monthly rate does not exceed the cap monthly rate, the full IBS monthly rate is billable. The charge `amount_cents` is then the billable monthly rate multiplied by `effort_pct` over 100 multiplied by `period_months`, rounded half-up to cents. The excess `over_cap_cents` — the IBS-monthly-minus-billable-monthly difference multiplied by the same effort fraction and months, rounded half-up — is zero whenever the award is uncapped, and when nonzero it represents institutional cost share that can never be charged to this award. A salary line's `mtdc_eligible_cents` equals its `amount_cents`. At creation the system also stamps `submitted_by_user_id` from `X-User-ID`, and the expenditure lands in `PENDING_REVIEW` with `fringe_cents` and `over_cap_cents` computed (fringe zero for non-salary) and `transferred_from_id`, `disallow_reason`, `posted_at`, and `invoiced_receivable_id` all unset.

Posting is where the ledger moves, and it is a `GrantsAccountant` action on a `PENDING_REVIEW` expenditure (any other state returns `ERR_EXPENDITURE_NOT_REVIEWABLE`). The checks fire in pinned order within the fiscal family: the award must be `ACTIVE` (`ERR_AWARD_NOT_ACTIVE`) and its posture not `FROZEN` (`ERR_AWARD_FROZEN`); all three allowability attestations must be true (`ERR_ALLOWABILITY_INCOMPLETE`); the `transaction_date` must lie within the closed interval from `project_start_date` to `current_end_date` (`ERR_OUTSIDE_PERIOD_OF_PERFORMANCE`); and a salary charge requires that the person hold an `EffortCommitment` on the award (`ERR_SALARY_NO_COMMITMENT`). Line sufficiency is checked in pinned order — the `PERSONNEL_SALARIES` line must fit `amount_cents` first, then the `FRINGE_BENEFITS` line must fit `fringe_cents` — with any shortfall returning `ERR_BUDGET_LINE_EXCEEDED`; for non-salary types the single line's `spent_cents` plus `amount_cents` must not exceed its `authorized_cents`. Cost-share expenditures skip the line checks entirely.

A successful post fires a four-link cascade, atomically. Link one stamps `posted_at` with the logical clock and debits the ledger: a non-cost-share expenditure adds `amount_cents` to its budget line's `spent_cents`, and a salary expenditure additionally computes `fringe_cents` as `amount_cents` times the award's provisional `fringe_rate_bps` over ten thousand, rounded half-up per line, and adds that to the `FRINGE_BENEFITS` line's `spent_cents` (when `fringe_cents` is zero this debit is a no-op and no `FRINGE_BENEFITS` line need exist). The per-line rounding order is pinned — fringe is rounded per expenditure line first, and the `FRINGE_BENEFITS` line total is the sum of those per-line rounded values; summing salary first and rounding once is a different, incorrect algorithm. Link two recomputes the award's aggregates: `mtdc_spent_cents` becomes the sum of `mtdc_eligible_cents` over the award's `POSTED`, non-cost-share expenditures (excluding `TRANSFERRED_OUT` sources, including transfer-in mirrors), `total_direct_spent_cents` becomes the sum of `amount_cents` over the same set, and `f_and_a_accrued_cents` becomes the award's `f_and_a_rate_bps` over ten thousand times `mtdc_spent_cents`, rounded half-up. An expenditure's own `mtdc_eligible_cents` is zero for `EQUIPMENT`, `PARTICIPANT_SUPPORT`, and cost-share entries; the capped subaward portion for `SUBAWARD_PAYMENT`; and `amount_cents` otherwise. Link three recomputes `available_draw_pool_cents` on letter-of-credit awards per the pool rule of §3.6. Link four applies only to salary: every `EffortStatement` for the (person, award) pair whose cycle window covers the `transaction_date` and whose cycle is not `CLOSED` recomputes its `charged_effort_pct`. Cost-share postings bypass the lines and instead add `amount_cents` to the award's `cost_share_met_cents`; separately, a salary posting's `over_cap_cents` always adds to `cost_share_met_cents`, regardless of the `is_cost_share` flag. A posting also increments the parent award's `version`.

Review can also go the other way: the accountant may disallow a pending expenditure, which moves it to `DISALLOWED` and sets `disallow_reason`; a coordinator may later resubmit it — optionally revising `is_allocable`, `is_reasonable`, `is_consistent`, or `amount_cents` — returning it to `PENDING_REVIEW` with the reason cleared.

### 3.3. Cost Transfers: Justification, Retroactivity, and the Mirror Ledger

When a posted cost lands on the wrong award, a `CostTransfer` re-attributes it. Either a `GrantCoordinator` or a `GrantsAccountant` creates the transfer in `DRAFT` by naming the `source_expenditure_id`, the `target_award_id`, the `target_budget_line_id`, and a `justification` of at least 20 characters; the system stamps `created_by_user_id` from `X-User-ID`. The source must be `POSTED` and must not be a salary charge (`ERR_SALARY_NOT_TRANSFERABLE` — salary corrections route through payroll and effort, not transfers) nor a cost-share entry (`ERR_COST_SHARE_NOT_TRANSFERABLE`); the target award must differ from the source expenditure's award (`ERR_TRANSFER_TARGET_SAME_AS_SOURCE`); and the target line's category must match the source line's category (`ERR_CATEGORY_TYPE_MISMATCH`).

Submission freezes the timeliness measurement. On submit the system computes `days_since_posting` as whole days from the source's `posted_at` to the logical clock, and sets `is_retroactive` true exactly when that count exceeds 90 — a transfer submitted precisely 90 days after posting is timely. A retroactive transfer must carry an `enhanced_justification` of at least 50 characters (`ERR_ENHANCED_JUSTIFICATION_REQUIRED`). The submit stamps `submitted_by_user_id` from `X-User-ID` and freezes both `is_retroactive` and `days_since_posting` at that moment; the transfer moves `DRAFT → SUBMITTED`.

Approval enforces segregation of duties: the approving accountant's `X-User-ID` must differ from `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). The target award must have posture other than `FROZEN` (`ERR_AWARD_FROZEN`) and `status` either `ACTIVE` or `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_ACTIVE`), and the target line must fit — its `spent_cents` plus the transferred amount must not exceed `authorized_cents` (`ERR_BUDGET_LINE_EXCEEDED`). From there the path splits on the frozen flag. A non-retroactive transfer approves directly, `SUBMITTED → APPROVED`, and applies the full ledger effects. A retroactive transfer instead moves `SUBMITTED → PENDING_COUNTERSIGN`, recording `approved_by_user_id` but applying no ledger effects yet; a `SponsoredProgramsOfficer` must then countersign — re-checking that the target posture is not `FROZEN` and the target line still fits — to move `PENDING_COUNTERSIGN → APPROVED` and apply the effects, stamping `countersigned_by_user_id`.

The apply-effects step is the same on both paths and preserves money conservation. First the source expenditure transitions `POSTED → TRANSFERRED_OUT` and its line is credited by the amount. Second the system creates a mirror expenditure on the target award: same `amount_cents`, status `POSTED`, `transferred_from_id` pointing back to the source, same expenditure type and category, `cash_disbursed` copied, `transaction_date` copied, and `posted_at` set to now. Third the target line is debited. Fourth both awards recompute their MTDC, F&A accrual, and draw pools — the source award's totals fall, the target's rise, and the combined sum of line spending across the two awards is bit-identical before and after. A transfer in flight can also be denied from `SUBMITTED` or `PENDING_COUNTERSIGN` by either an accountant or an officer, setting `deny_reason`; a denied transfer returns to `DRAFT` via revise — clearing `deny_reason` and optionally replacing `justification` — ready to submit again. Actions attempted from the wrong state return `ERR_TRANSFER_NOT_ACTIONABLE`.

### 3.4. Effort Certification: Cycles, Statements, and the 100% Conservation

Effort reporting runs in cycles. A `GrantsAccountant` creates an `EffortCycle` with a globally unique `cycle_code` such as 2026-H1 (duplicates return `ERR_DUPLICATE_CYCLE_CODE`), a `period_start`, a `period_end` strictly after it, and `cycle_months` between 1 and 12 as the denominator months for charged-effort percentage. Cycle windows are half-open — the window includes `period_start` and excludes `period_end` — and a new cycle's window must not overlap any existing cycle's window, where overlap means the new start falls before the other's end and the new end falls after the other's start; adjacency is allowed, and a violation returns `ERR_CYCLE_PERIOD_OVERLAP`. The cycle is born `SCHEDULED`.

Opening the cycle moves it `SCHEDULED → CERTIFYING` and is gated twice: the logical clock must have reached `period_start` (`ERR_CYCLE_NOT_YET_OPENABLE`), and no other cycle may already be `CERTIFYING` (`ERR_CYCLE_ALREADY_CERTIFYING`). Opening a cycle that is not `SCHEDULED`, or closing one that is not `CERTIFYING`, fails with `ERR_CYCLE_NOT_CERTIFYING`. Opening fans out statements: for every person holding at least one commitment on an award whose period of performance overlaps the cycle window, the system creates one `AWARD` `EffortStatement` per commitment — snapshotting `committed_effort_pct` from the commitment (version-pinned; later commitment edits never propagate) and computing the initial `charged_effort_pct` — plus exactly one `NON_SPONSORED` statement per person as the institutional catch-all for teaching and administration, with both committed and charged set to 0.0 and `award_id` null. Each statement starts `PENDING` with `certified_effort_pct`, `variance_pp`, and `payroll_adjustment_note` unset and `key_reduction_flag` false.

The charged figure answers "what fraction of this person's effort did this award actually buy in the window?" Its numerator is the sum of `amount_cents` over the person's `POSTED`, non-`TRANSFERRED_OUT` salary expenditures on the award whose `transaction_date` falls in the half-open cycle window. Its denominator is the person's monthly IBS rate — annual IBS divided by appointment months, rounded half-up — multiplied by the cycle's `cycle_months`. The charged percentage is one hundred times the numerator over the denominator, rounded half-up to two decimals. Note the cap interaction: the denominator always uses full uncapped IBS while the numerator only ever contains the capped charge, so an over-cap person cannot reach their nominal effort percentage on that award — the gap lands in institutional effort instead. This figure recomputes on every salary posting or transfer touching the (person, award, window) triple.

Certification belongs to the person: a `PrincipalInvestigator` or `ResearchStaff` certifies their own statement, and only their own — an `X-User-ID` other than the statement's `person_id` is rejected with `ERR_FORBIDDEN_OWNERSHIP`. The cycle must be `CERTIFYING` (`ERR_STATEMENT_NOT_CERTIFIABLE`), and the request must carry `expected_effort_statement_version` equal to the statement's current `version` per the OCC rule of §2.6, because payroll postings silently recompute the charged figure. The certifier attests a `certified_effort_pct` between 0.00 and 100.00 inclusive (`ERR_INVALID_REQUEST` outside that range). The system then computes `variance_pp` as the certified value minus the charged value, rounded half-up to two decimals; when the absolute variance exceeds 5.00 percentage points, a `payroll_adjustment_note` of at least 20 characters is required (`ERR_VARIANCE_NOTE_REQUIRED`). The key-personnel floor is evaluated at the same moment: when the underlying commitment's `is_key_personnel` is true and the certified percentage falls below three quarters of the committed percentage, `key_reduction_flag` becomes true — a sponsor prior-approval situation observable on the statement. Certification moves `PENDING → CERTIFIED`, bumps the statement's `version`, and records the variance and flag.

Corrections cycle. When a payroll adjustment lands after certification, an accountant may reopen a `CERTIFIED` statement while the cycle is still `CERTIFYING` (`ERR_STATEMENT_NOT_CERTIFIABLE` otherwise), moving it to `REOPENED`: the charged figure is recomputed, the certified value and variance are cleared, and the version bumps. The certifier then re-certifies through the same path — same preconditions, same OCC field, same variance and floor computations — moving `REOPENED → RECERTIFIED`.

Closing the cycle moves it `CERTIFYING → CLOSED` and enforces two aggregate gates. Every generated statement must sit in `CERTIFIED` or `RECERTIFIED` (`ERR_CYCLE_HAS_UNCERTIFIED_STATEMENTS`), and for each person the sum of `certified_effort_pct` across all their statements — award and non-sponsored together — must equal exactly 100.00 (`ERR_EFFORT_TOTAL_NOT_100`). At close the accountant supplies the cycle's `actual_fringe_rate_bps`, and the fringe true-up runs per award touched by the cycle — that is, per award holding at least one `POSTED` salary expenditure with `transaction_date` in the half-open window. For each such award the base is the sum of `amount_cents` over those salary expenditures (excluding `TRANSFERRED_OUT` sources); the adjustment is that base multiplied by the difference between the cycle's actual rate and the award's provisional `fringe_rate_bps`, in basis points over ten thousand, rounded half-up to cents; a nonzero adjustment is added to the award's `FRINGE_BENEFITS` line `spent_cents`. Line sufficiency is deliberately not re-validated for true-up deltas — they are rate reconciliations, not new spending.

### 3.5. Subawards and Invoice Monitoring

A `Subaward` delegates part of a prime award to a subrecipient institution. An officer creates it in `DRAFT` under `award_id`, naming `subrecipient_name`, a `total_subaward_cents` ceiling strictly greater than zero, a `risk_rating` of `LOW`, `MEDIUM`, or `HIGH`, and the subaward period `start_date` to `end_date` (end strictly after start). Activation requires the prime award to be `ACTIVE` (`ERR_AWARD_NOT_ACTIVE`) and moves the subaward `DRAFT → ACTIVE`. Closing requires no invoices in `RECEIVED` or `UNDER_REVIEW` (`ERR_INVOICE_NOT_REVIEWABLE`) and moves it to `CLOSED`.

Invoices arrive from the subrecipient and are recorded by a coordinator with `subaward_id`, an `invoice_number` unique within the subaward among non-`REJECTED` invoices (`ERR_DUPLICATE_INVOICE_NUMBER`), a billing window `period_start` to `period_end` (end at or after start), `current_period_direct_cents` and `current_period_f_and_a_cents` (both zero or more), and optionally `audit_reference`. Invoice windows are closed intervals — both endpoints included — so two invoices sharing even a boundary day overlap; a new invoice's window must not overlap any non-`REJECTED` invoice of the same subaward (`ERR_INVOICE_PERIOD_OVERLAP`) and must lie fully within the subaward's closed period (`ERR_INVOICE_PERIOD_OUT_OF_RANGE`). The subaward must be `DRAFT` or `ACTIVE` — recording against a `CLOSED` subaward fails with `ERR_SUBAWARD_NOT_ACTIVE`. The cumulative ceiling also bites at record time: the sum of direct plus sub-F&A over the subaward's non-`REJECTED` invoices including this one must not exceed `total_subaward_cents` (`ERR_SUBAWARD_BUDGET_EXCEEDED`).

Two computed fields track the federal MTDC cap on subawards, and they are computed chronologically: order the subaward's non-`REJECTED` invoices by `period_start` ascending, breaking ties by `created_at` ascending — never by id. Each invoice's `cumulative_direct_cents` is the sum of `current_period_direct_cents` over invoices up to and including itself in that order. Its `mtdc_portion_cents` is the slice of this invoice's direct that still fits under the 2,500,000-cent cap: the cumulative direct capped at 2,500,000, minus the cumulative direct excluding this invoice similarly capped. At approval, the subaward's `mtdc_consumed_cents` is set to the approving invoice's capped cumulative direct. The subaward's `invoiced_to_date_cents` sums direct plus sub-F&A over invoices in `RECEIVED`, `UNDER_REVIEW`, `PAID`, or `RETURNED_FOR_REVISION`.

Review is the officer's desk. Beginning review moves `RECEIVED → UNDER_REVIEW`. From there the officer may reject the invoice — terminal, setting `return_reason`, decrementing `invoiced_to_date_cents`, and excluding the invoice from cumulative and overlap checks — or return it for revision, also setting `return_reason`, which lets a coordinator resubmit with revised `current_period_direct_cents` and `current_period_f_and_a_cents` and optionally revised `period_start` and `period_end`. Resubmission re-checks the overlap and cumulative-ceiling rules against the revised figures (`ERR_INVOICE_PERIOD_OVERLAP`, `ERR_SUBAWARD_BUDGET_EXCEEDED`), recomputes `cumulative_direct_cents` and `mtdc_portion_cents`, refreshes `invoiced_to_date_cents`, and moves the invoice back to `UNDER_REVIEW`. Invoice actions attempted from the wrong state return `ERR_INVOICE_NOT_REVIEWABLE`.

Approval pays the invoice and posts the cost onto the prime award in one atomic step. The subaward must be `ACTIVE` (`ERR_SUBAWARD_NOT_ACTIVE`); the prime award must be `ACTIVE` (`ERR_AWARD_NOT_ACTIVE`) with posture other than `FROZEN` (`ERR_AWARD_FROZEN`); a `HIGH`-risk subaward requires `audit_reference` at approval time (`ERR_AUDIT_REFERENCE_REQUIRED`); and the prime award's `SUBAWARDS` line must fit — its `spent_cents` plus the invoice's direct plus sub-F&A must not exceed `authorized_cents` (`ERR_BUDGET_LINE_EXCEEDED`). On success the system creates a prime expenditure of type `SUBAWARD_PAYMENT` with `amount_cents` equal to direct plus sub-F&A, `mtdc_eligible_cents` equal to the invoice's `mtdc_portion_cents`, status `POSTED`, and `cash_disbursed` true; debits the prime `SUBAWARDS` line; recomputes the prime award's MTDC, F&A accrual, and draw pools; updates the subaward's `invoiced_to_date_cents` and `mtdc_consumed_cents`; stamps the invoice's `prime_expenditure_id` with the mirror's id; and moves the invoice to `PAID`.

### 3.6. Cash In: Letter-of-Credit Drawdowns and Cost-Reimbursable Receivables

The two payment methods pull cash through different channels, and both are anchored to the award's pinned `payment_method`: drawdowns are only valid on `LETTER_OF_CREDIT` awards, receivables only on `COST_REIMBURSABLE_INVOICE` awards, and either against the wrong method — or anything at all on `FIXED_PRICE_SCHEDULE` — returns `ERR_PAYMENT_METHOD_MISMATCH`.

The letter-of-credit pool is cash-basis. Its eligible pool is the sum of `amount_cents` over the award's `POSTED`, non-cost-share expenditures with `cash_disbursed` true, plus the F&A share computed as the award's `f_and_a_rate_bps` over ten thousand times the sum of `mtdc_eligible_cents` over that same cash-disbursed set, rounded half-up; undisbursed costs are not drawable. The award's `available_draw_pool_cents` is the eligible pool minus `cumulative_drawn_cents` minus `reserved_draw_cents`, and the conservation invariant of §2.8 keeps the three quantities partitioned exactly. An accountant creates a `DrawdownRequest` in `DRAFT` with `award_id` and `amount_cents` greater than zero, carrying `expected_award_version` per §2.6 — a stale read of the pool is rejected with `ERR_STALE_AWARD_VERSION` — and the create itself increments the award's `version`. Submitting the draw requires the award `ACTIVE` or `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_ACTIVE`) with posture `OPEN` (`ERR_AWARD_RESTRICTED` when restricted, `ERR_AWARD_FROZEN` when frozen), and the amount must not exceed `available_draw_pool_cents` (`ERR_DRAWDOWN_EXCEEDS_ELIGIBLE`). On submit the request moves `DRAFT → SUBMITTED`, the amount moves from available to reserved (`reserved_draw_cents` up, `available_draw_pool_cents` down), and `eligible_pool_at_submission` snapshots the pool for audit while `submitted_at` records the clock. A `SponsorOfficial` then settles the draw — moving it `SUBMITTED → SETTLED`, decrementing reserved, incrementing `cumulative_drawn_cents`, stamping `settled_at`, and bumping the award's `version` — or rejects it with a `reject_reason`, moving it `SUBMITTED → REJECTED_BY_SPONSOR` and releasing the reservation back to available. Drawdown actions attempted from the wrong state return `ERR_DRAWDOWN_NOT_ACTIONABLE`. And per the posture rule, an award entering `FROZEN` auto-cancels every `DRAFT` or `SUBMITTED` draw into `CANCELLED`, releasing any reservation.

Cost-reimbursable invoicing is accrual-basis. An accountant bills the sponsor by creating a `Receivable` with `award_id`, `period_start`, and `period_end`; the award must be invoice-method and not suspended. The invoice amount is computed over the award's `POSTED`, non-cost-share expenditures whose `transaction_date` falls inside the closed billing window and whose `invoiced_receivable_id` is still null — regardless of `cash_disbursed`: the amount is the sum of `amount_cents` over that set plus the F&A share (rate over ten thousand times the set's `mtdc_eligible_cents` sum, rounded half-up). A window containing no uninvoiced posted costs is rejected with `ERR_NO_UNINVOICED_COSTS`. On creation the computed figure becomes the receivable's `amount_cents`, `invoice_date` is stamped with the logical clock, every included expenditure's `invoiced_receivable_id` is set — preventing double-billing — and the award's `version` increments. The receivable opens `OPEN` with `days_outstanding`, `accrued_interest_cents`, `interest_paid_cents`, `principal_paid_cents`, and `total_disputed_days` at zero and `disputed_at` and `dispute_reason` unset.

Aging and interest recompute on every read of the receivable and on every clock advance. `days_outstanding` is the whole-day count from `invoice_date` to the logical clock, never negative by construction. The `aging_bucket` boundaries are pinned: `CURRENT` covers 30 days or fewer, `D31_60` covers 31 through 60, `D61_90` covers 61 through 90, `D91_120` covers 91 through 120, and `OVER_120` covers 121 and beyond — so day 30 is `CURRENT`, day 31 is `D31_60`, day 60 is `D31_60`, and day 61 is `D61_90`. Late interest accrues only after a 60-day grace: the billable days are `days_outstanding` minus 60 minus `total_disputed_days`, floored at zero — exactly 60 days outstanding accrues nothing, day 61 accrues one day. The accrual is the outstanding principal (`amount_cents` minus `principal_paid_cents`) multiplied by the sponsor's `late_payment_apr_bps` over ten thousand, divided by 365, multiplied by billable days, rounded half-up to cents once per receivable. While the receivable is `DISPUTED` accrual pauses: `accrued_interest_cents` stays frozen at the value computed when the dispute opened, and dispute days never accrue even after resolution. The derived `outstanding_total_cents` is `amount_cents` plus `accrued_interest_cents` minus `interest_paid_cents` minus `principal_paid_cents`. A computed aging read for one award returns the bucket sums of per-receivable principal outstanding — `current_cents`, `d31_60_cents`, `d61_90_cents`, `d91_120_cents`, `over_120_cents` — plus `total_outstanding_cents` and `total_accrued_interest_cents`, summing the per-receivable rounded interest values rather than rounding the fleet total.

Payments allocate by waterfall. Recording a payment of `amount_cents` against an `OPEN` or `PARTIALLY_PAID` receivable first checks that the payment does not exceed `outstanding_total_cents` (`ERR_RECEIVABLE_OVERPAYMENT`). The interest portion is the lesser of the payment and the unpaid interest (`accrued_interest_cents` minus `interest_paid_cents`); the remainder goes to principal. `interest_paid_cents` and `principal_paid_cents` accumulate their shares, the principal portion adds to the award's `cumulative_drawn_cents`, and the status becomes `PAID` when the outstanding total reaches zero, else `PARTIALLY_PAID` (including a `PARTIALLY_PAID → PARTIALLY_PAID` step when a partial payment still leaves a balance). An accountant may also dispute an `OPEN` receivable with a `dispute_reason`, moving it to `DISPUTED` and pausing interest; resolving the dispute returns it to `OPEN`, with the days spent disputed accumulated into `total_disputed_days` and excluded from interest thereafter. Payment or dispute actions from the wrong state return `ERR_RECEIVABLE_NOT_OPEN`.

### 3.7. Reports, Posture, and the Overdue Cascade

Every award carries scheduled `ReportRequirement` rows, created by an officer with `award_id`, a `report_type` of `ANNUAL_PROGRESS`, `TECHNICAL_QUARTERLY`, `MILESTONE`, or `FINAL_TECHNICAL`, and a `due_date`. A requirement starts `PENDING` with `days_overdue` 0 and `submitted_at` and `reject_reason` unset. The overdue sweep runs on every logical-clock advance: when the clock passes a `PENDING` requirement's `due_date`, the requirement moves to `OVERDUE`, its `days_overdue` recomputes as whole days from `due_date` to the clock, and the award's posture recomputes per §2.9 — the first cascade link drops the award to `RESTRICTED`, and a `FINAL_TECHNICAL` requirement more than 30 days overdue pushes it to `FROZEN`, which in turn cancels every `DRAFT` or `SUBMITTED` drawdown and releases its reservation.

Submission comes from the project side: a `PrincipalInvestigator` acting on their own award (the award's `pi_id` must equal `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`) or a `GrantCoordinator` may submit a `PENDING` or `OVERDUE` requirement — other states return `ERR_REPORT_NOT_SUBMITTABLE` — optionally with a `submission_note`. Submission stamps `submitted_at` from the clock, moves the requirement to `SUBMITTED`, and recomputes posture, clearing the overdue drag. The sponsor then accepts the report — terminal — or rejects it with a `revised_due_date` and `reject_reason`, returning the requirement to `PENDING` with `due_date` replaced by the revised date and posture recomputed once more.

### 3.8. Modifications: No-Cost Extensions and Rebudgets

Changes after activation run through `ModificationRequest`. A coordinator creates one in `DRAFT` with `award_id`, a `mod_type` of `NO_COST_EXTENSION` or `REBUDGET`, a `justification` of at least 20 characters, and `expected_award_version` per §2.6 (stale reads return `ERR_STALE_AWARD_VERSION`; the create itself bumps the award's `version`). A no-cost extension carries `extension_months` between 1 and 12; a rebudget carries `rebudget_lines`, a list of line-id and `new_authorized_cents` pairs from which `F_AND_A` lines are forbidden. The `requires_sponsor` flag is computed at creation. For a rebudget, each listed line whose value would change is tested against its `baseline_authorized_cents`: the change is significant when the baseline is positive and the absolute change times one hundred exceeds twenty-five times the baseline — exactly 25% is not significant — or when the baseline is zero and the new value is positive. The flag is true when any line is significant, or any listed `EQUIPMENT` line's new value exceeds its current value, or any listed `PARTICIPANT_SUPPORT` line's new value falls below its current value. For a no-cost extension the flag is true when the award's `nce_count` is already at least 1 — the first extension is a grantee-authority action, later ones need the sponsor.

Submission is gated. The award must be `ACTIVE` (`ERR_AWARD_NOT_ACTIVE`). A no-cost extension must be submitted while the logical clock is still before `current_end_date` (`ERR_NCE_AFTER_END_DATE`). A rebudget must satisfy the grand-total invariant: after applying the new authorizations to the listed direct lines and recomputing the `F_AND_A` authorization over authorized bases per §3.1, the grand total must still equal `total_obligated_cents` exactly (`ERR_REBUDGET_NOT_ZERO_SUM`). Because F&A moves with the MTDC base, shifting cents into a non-MTDC category such as equipment demands a compensating boost elsewhere in MTDC-bearing lines — at a 5000-basis-point rate, moving m cents into equipment requires a net boost of m/3 cents across other MTDC-bearing lines. Each `SUBAWARDS` line's new authorization must also remain at least its `mtdc_eligible_cents` (`ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED`). A successful submit moves the request `DRAFT → SUBMITTED`.

Approval forks on the precomputed flag. An officer internal-approves: when `requires_sponsor` is false the request is `APPROVED` immediately under grantee authority and its effects apply; when true it routes to `SPONSOR_REVIEW`, where a `SponsorOfficial` records a `decision` of approve or deny with an optional `reason` — approval applies the effects, denial moves the request to `DENIED` and sets `sponsor_decision_reason`. A coordinator may also withdraw a `SUBMITTED` request before any decision, moving it to `WITHDRAWN`. Actions from the wrong state return `ERR_MODIFICATION_NOT_ACTIONABLE`.

The applied effects differ by type. A no-cost extension adds `extension_months` calendar months to `current_end_date` (the day clamped to month end), increments `nce_count`, shifts the `due_date` of every non-terminal `FINAL_TECHNICAL` report requirement by the same extension, and bumps the award's `version`. A rebudget writes each listed line's `authorized_cents` to its new value, recomputes the `F_AND_A` line's authorization over the new authorized bases, and — only when approval came through the sponsor-decision channel — refreshes every line's `baseline_authorized_cents` to its current `authorized_cents`; grantee-authority approvals leave baselines untouched. Either path bumps the award's `version`.

### 3.9. Closeout and the Final Financial Report

Closeout begins once the period of performance has run its course: an accountant initiates it only when the logical clock has reached `current_end_date` (`ERR_CLOSEOUT_TOO_EARLY`). The award moves `ACTIVE → CLOSEOUT_PENDING`, the system creates the award's single `FinalFinancialReport` in `DRAFT` — discoverable by filtering the final-financial-reports list by `award_id` — posture recomputes with FFR lateness now gating, and the award's `version` bumps. Should the sponsor order a reopen, the officer's action moves the award back to `ACTIVE`, deletes the `DRAFT` or `RETURNED` report (a later initiate-closeout creates a fresh one), recomputes posture, and bumps the version again.

Submitting the final report is the accountant's declaration that the books are clean. The award must be `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_IN_CLOSEOUT`); the declared `unliquidated_obligations_cents` must be exactly zero (`ERR_UNLIQUIDATED_OBLIGATIONS`); no subaward invoice may sit in `RECEIVED` or `UNDER_REVIEW` and no drawdown in `DRAFT` or `SUBMITTED` (either case `ERR_CLOSEOUT_INCOMPLETE`). On submit the system snapshots `total_expenditures_cents` as the award's `total_direct_spent_cents` plus `f_and_a_accrued_cents`, `residual_cents` as `total_obligated_cents` minus `cumulative_drawn_cents`, and `cost_share_shortfall_cents` as the greater of zero and `cost_share_committed_cents` minus `cost_share_met_cents`. On letter-of-credit awards the shortfall immediately reduces the final payment: `available_draw_pool_cents` drops by the shortfall, floored at zero. A `RETURNED` report resubmits through the same path with the same checks and fresh snapshots.

The sponsor's verdict follows. Acceptance moves the report to `ACCEPTED` and recomputes posture with the FFR no longer outstanding; return moves it to `RETURNED` with a `return_reason`. FFR actions from the wrong state return `ERR_FFR_NOT_ACTIONABLE`.

Final close is the accountant's last act and is gated on everything: the final report must be `ACCEPTED`; no receivable may remain `OPEN`, `PARTIALLY_PAID`, or `DISPUTED`; no drawdown may remain in `DRAFT` or `SUBMITTED`; no subaward invoice may remain in `RECEIVED` or `UNDER_REVIEW`; and every report requirement must be `ACCEPTED` — any failure returns `ERR_CLOSEOUT_INCOMPLETE`. On close the award moves `CLOSEOUT_PENDING → CLOSED`, `residual_deobligated_cents` records `total_obligated_cents` minus `cumulative_drawn_cents`, `total_obligated_cents` is reduced to `cumulative_drawn_cents` (the residual is deobligated back to the sponsor), and the award's `version` increments a final time.

## 4. Endpoint Definitions

New resources are created with HTTP 201; all modifications, state transitions, and computed reads return HTTP 200. All endpoints are mounted under `/api`. Request and response payloads are not repeated here — each endpoint's full contract is determined by the workflow narratives of §3 together with the cross-cutting rules of §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/_clock/set_current_utc` | Advance the logical clock; triggers overdue sweep, posture recompute with FROZEN drawdown cascade, and aging/interest recompute | SystemAdmin |
| POST | `/api/sponsors` | Create a sponsor | SponsoredProgramsOfficer |
| GET | `/api/sponsors` | List sponsors (filters: `payment_method`, `sponsor_type`) | All roles |
| GET | `/api/sponsors/{id}` | Get one sponsor | All roles |
| POST | `/api/persons` | Register research personnel | SponsoredProgramsOfficer |
| GET | `/api/persons` | List persons (filter: `role_type`) | All roles |
| GET | `/api/persons/{id}` | Get one person | All roles |
| POST | `/api/awards` | Create an award in PENDING_SETUP; sponsor terms version-pinned onto it | SponsoredProgramsOfficer |
| GET | `/api/awards` | List awards (filters: `sponsor_id`, `pi_id`, `status`, `posture`) | All roles |
| GET | `/api/awards/{id}` | Get one award with all computed aggregates and posture | All roles |
| POST | `/api/awards/{id}/activate` | Activate after budget load; exact-allocation gate; snapshots baselines | SponsoredProgramsOfficer |
| POST | `/api/awards/{id}/suspend` | Sponsor suspension of an ACTIVE award | SponsorOfficial |
| POST | `/api/awards/{id}/reinstate` | Reinstate a SUSPENDED award | SponsorOfficial |
| POST | `/api/awards/{id}/initiate-closeout` | Enter closeout at/after current end date; auto-creates the DRAFT FFR | GrantsAccountant |
| POST | `/api/awards/{id}/reopen` | Reopen from CLOSEOUT_PENDING to ACTIVE; deletes a DRAFT/RETURNED FFR | SponsorOfficial |
| POST | `/api/awards/{id}/close` | Final close; deobligates residual | GrantsAccountant |
| POST | `/api/budget-lines` | Load one budget category line while PENDING_SETUP | GrantCoordinator |
| GET | `/api/budget-lines` | List budget lines (filters: `award_id`, `category`) | All roles |
| GET | `/api/budget-lines/{id}` | Get one budget line | All roles |
| POST | `/api/effort-commitments` | Record committed effort for a person on an award | GrantCoordinator |
| GET | `/api/effort-commitments` | List effort commitments (filters: `award_id`, `person_id`) | All roles |
| GET | `/api/effort-commitments/{id}` | Get one effort commitment | All roles |
| POST | `/api/expenditures` | Submit an expenditure for review | GrantCoordinator |
| GET | `/api/expenditures` | List expenditures (filters: `award_id`, `budget_line_id`, `person_id`, `status`, `transferred_from_id`, `invoiced_receivable_id`, `expenditure_type`) | All roles |
| GET | `/api/expenditures/{id}` | Get one expenditure | All roles |
| POST | `/api/expenditures/{id}/post` | Post after review; fires the four-link ledger cascade | GrantsAccountant |
| POST | `/api/expenditures/{id}/disallow` | Disallow a pending expenditure | GrantsAccountant |
| POST | `/api/expenditures/{id}/resubmit` | Return a DISALLOWED expenditure to PENDING_REVIEW | GrantCoordinator |
| POST | `/api/cost-transfers` | Create a cost transfer in DRAFT | GrantCoordinator, GrantsAccountant |
| GET | `/api/cost-transfers` | List cost transfers (filters: `source_expenditure_id`, `target_award_id`, `target_budget_line_id`, `status`) | All roles |
| GET | `/api/cost-transfers/{id}` | Get one cost transfer | All roles |
| POST | `/api/cost-transfers/{id}/submit` | Submit for review; freezes retroactivity fields | GrantCoordinator, GrantsAccountant |
| POST | `/api/cost-transfers/{id}/approve` | Approve non-retroactive, or route retroactive to countersign | GrantsAccountant |
| POST | `/api/cost-transfers/{id}/countersign` | Second-role approval for retroactive transfers | SponsoredProgramsOfficer |
| POST | `/api/cost-transfers/{id}/deny` | Deny a submitted or countersign-pending transfer | GrantsAccountant, SponsoredProgramsOfficer |
| POST | `/api/cost-transfers/{id}/revise` | Return a DENIED transfer to DRAFT | GrantCoordinator, GrantsAccountant |
| POST | `/api/effort-cycles` | Create a certification cycle | GrantsAccountant |
| GET | `/api/effort-cycles` | List effort cycles (filter: `status`) | All roles |
| GET | `/api/effort-cycles/{id}` | Get one effort cycle | All roles |
| POST | `/api/effort-cycles/{id}/open` | Open certification; generates statements | GrantsAccountant |
| POST | `/api/effort-cycles/{id}/close` | Close the cycle; posts fringe true-up | GrantsAccountant |
| GET | `/api/effort-statements` | List effort statements (filters: `cycle_id`, `person_id`, `award_id`, `status`, `statement_kind`) | All roles |
| GET | `/api/effort-statements/{id}` | Get one effort statement | All roles |
| POST | `/api/effort-statements/{id}/certify` | Certify or re-certify own statement (OCC on statement version) | PrincipalInvestigator, ResearchStaff |
| POST | `/api/effort-statements/{id}/reopen` | Reopen a CERTIFIED statement | GrantsAccountant |
| POST | `/api/subawards` | Create a subaward in DRAFT | SponsoredProgramsOfficer |
| GET | `/api/subawards` | List subawards (filters: `award_id`, `status`, `risk_rating`) | All roles |
| GET | `/api/subawards/{id}` | Get one subaward | All roles |
| POST | `/api/subawards/{id}/activate` | Activate a subaward | SponsoredProgramsOfficer |
| POST | `/api/subawards/{id}/close` | Close a subaward once no invoices are in flight | SponsoredProgramsOfficer |
| POST | `/api/subaward-invoices` | Record a received subrecipient invoice | GrantCoordinator |
| GET | `/api/subaward-invoices` | List subaward invoices (filters: `subaward_id`, `status`, `prime_expenditure_id`) | All roles |
| GET | `/api/subaward-invoices/{id}` | Get one subaward invoice | All roles |
| POST | `/api/subaward-invoices/{id}/begin-review` | Move a received invoice into review | SponsoredProgramsOfficer |
| POST | `/api/subaward-invoices/{id}/approve` | Approve for payment; posts the prime mirror expenditure | SponsoredProgramsOfficer |
| POST | `/api/subaward-invoices/{id}/reject` | Reject an invoice under review (terminal) | SponsoredProgramsOfficer |
| POST | `/api/subaward-invoices/{id}/return-for-revision` | Return an invoice for revision | SponsoredProgramsOfficer |
| POST | `/api/subaward-invoices/{id}/resubmit` | Resubmit a returned invoice with revised amounts/period | GrantCoordinator |
| POST | `/api/report-requirements` | Schedule a report requirement | SponsoredProgramsOfficer |
| GET | `/api/report-requirements` | List report requirements (filters: `award_id`, `status`, `report_type`) | All roles |
| GET | `/api/report-requirements/{id}` | Get one report requirement | All roles |
| POST | `/api/report-requirements/{id}/submit` | Submit a report (PENDING or OVERDUE) | PrincipalInvestigator, GrantCoordinator |
| POST | `/api/report-requirements/{id}/accept` | Sponsor accepts a submitted report | SponsorOfficial |
| POST | `/api/report-requirements/{id}/reject` | Sponsor rejects with a revised due date | SponsorOfficial |
| POST | `/api/drawdown-requests` | Create a drawdown request in DRAFT (OCC on award version) | GrantsAccountant |
| GET | `/api/drawdown-requests` | List drawdown requests (filters: `award_id`, `status`) | All roles |
| GET | `/api/drawdown-requests/{id}` | Get one drawdown request | All roles |
| POST | `/api/drawdown-requests/{id}/submit` | Submit to sponsor; reserves the amount | GrantsAccountant |
| POST | `/api/drawdown-requests/{id}/settle` | Sponsor settles a submitted draw | SponsorOfficial |
| POST | `/api/drawdown-requests/{id}/reject` | Sponsor rejects a submitted draw | SponsorOfficial |
| POST | `/api/receivables` | Bill a cost-reimbursable sponsor for a period | GrantsAccountant |
| GET | `/api/receivables` | List receivables (filters: `award_id`, `status`, `aging_bucket`) | All roles |
| GET | `/api/receivables/{id}` | Get one receivable with recomputed aging and interest | All roles |
| POST | `/api/receivables/{id}/payments` | Record a sponsor payment (waterfall: interest, then principal) | GrantsAccountant |
| POST | `/api/receivables/{id}/dispute` | Dispute an OPEN receivable; pauses interest | GrantsAccountant |
| POST | `/api/receivables/{id}/resolve-dispute` | Resolve a dispute; interest resumes, dispute days excluded | GrantsAccountant |
| GET | `/api/awards/{id}/receivables-aging` | Computed aging-bucket read for one award | All roles |
| POST | `/api/modification-requests` | Create a modification request in DRAFT (OCC on award version) | GrantCoordinator |
| GET | `/api/modification-requests` | List modification requests (filters: `award_id`, `status`, `mod_type`) | All roles |
| GET | `/api/modification-requests/{id}` | Get one modification request | All roles |
| POST | `/api/modification-requests/{id}/submit` | Submit a request (NCE timing / rebudget zero-sum gates) | GrantCoordinator |
| POST | `/api/modification-requests/{id}/internal-approve` | Institutional approval; applies or routes to sponsor review | SponsoredProgramsOfficer |
| POST | `/api/modification-requests/{id}/sponsor-decision` | Sponsor approve (applies effects, refreshes baselines) or deny | SponsorOfficial |
| POST | `/api/modification-requests/{id}/withdraw` | Withdraw a submitted request | GrantCoordinator |
| GET | `/api/final-financial-reports` | List FFRs (filter: `award_id`, `status`) | All roles |
| GET | `/api/final-financial-reports/{id}` | Get one FFR | All roles |
| POST | `/api/final-financial-reports/{id}/submit` | Submit the FFR; snapshots totals; shortfall reduces the pool | GrantsAccountant |
| POST | `/api/final-financial-reports/{id}/accept` | Sponsor accepts the FFR | SponsorOfficial |
| POST | `/api/final-financial-reports/{id}/return` | Sponsor returns the FFR for correction | SponsorOfficial |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narrative of §2 and §3; this table is only the identifier-to-status index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_SPONSOR_NOT_FOUND | 404 |
| ERR_PERSON_NOT_FOUND | 404 |
| ERR_AWARD_NOT_FOUND | 404 |
| ERR_BUDGET_LINE_NOT_FOUND | 404 |
| ERR_COMMITMENT_NOT_FOUND | 404 |
| ERR_EXPENDITURE_NOT_FOUND | 404 |
| ERR_TRANSFER_NOT_FOUND | 404 |
| ERR_CYCLE_NOT_FOUND | 404 |
| ERR_STATEMENT_NOT_FOUND | 404 |
| ERR_SUBAWARD_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_DRAWDOWN_NOT_FOUND | 404 |
| ERR_RECEIVABLE_NOT_FOUND | 404 |
| ERR_MODIFICATION_NOT_FOUND | 404 |
| ERR_FFR_NOT_FOUND | 404 |
| ERR_STALE_AWARD_VERSION | 412 |
| ERR_STALE_STATEMENT_VERSION | 412 |
| ERR_AWARD_NOT_ACTIVE | 409 |
| ERR_AWARD_NOT_SUSPENDED | 409 |
| ERR_AWARD_NOT_IN_CLOSEOUT | 409 |
| ERR_EXPENDITURE_NOT_REVIEWABLE | 409 |
| ERR_TRANSFER_NOT_ACTIONABLE | 409 |
| ERR_CYCLE_NOT_CERTIFYING | 409 |
| ERR_STATEMENT_NOT_CERTIFIABLE | 409 |
| ERR_SUBAWARD_NOT_ACTIVE | 409 |
| ERR_INVOICE_NOT_REVIEWABLE | 409 |
| ERR_REPORT_NOT_SUBMITTABLE | 409 |
| ERR_DRAWDOWN_NOT_ACTIONABLE | 409 |
| ERR_RECEIVABLE_NOT_OPEN | 409 |
| ERR_MODIFICATION_NOT_ACTIONABLE | 409 |
| ERR_FFR_NOT_ACTIONABLE | 409 |
| ERR_AWARD_RESTRICTED | 409 |
| ERR_AWARD_FROZEN | 409 |
| ERR_CLOSEOUT_INCOMPLETE | 409 |
| ERR_CLOSEOUT_TOO_EARLY | 409 |
| ERR_CYCLE_NOT_YET_OPENABLE | 409 |
| ERR_CYCLE_PERIOD_OVERLAP | 409 |
| ERR_INVOICE_PERIOD_OVERLAP | 409 |
| ERR_CYCLE_ALREADY_CERTIFYING | 409 |
| ERR_DUPLICATE_COMMITMENT | 409 |
| ERR_DUPLICATE_INVOICE_NUMBER | 409 |
| ERR_DUPLICATE_AWARD_NUMBER | 409 |
| ERR_DUPLICATE_CYCLE_CODE | 409 |
| ERR_ALLOWABILITY_INCOMPLETE | 422 |
| ERR_ENHANCED_JUSTIFICATION_REQUIRED | 422 |
| ERR_SALARY_NOT_TRANSFERABLE | 422 |
| ERR_COST_SHARE_NOT_TRANSFERABLE | 422 |
| ERR_AUDIT_REFERENCE_REQUIRED | 422 |
| ERR_OUTSIDE_PERIOD_OF_PERFORMANCE | 422 |
| ERR_INVOICE_PERIOD_OUT_OF_RANGE | 422 |
| ERR_NCE_AFTER_END_DATE | 422 |
| ERR_EFFORT_TOTAL_NOT_100 | 422 |
| ERR_CYCLE_HAS_UNCERTIFIED_STATEMENTS | 422 |
| ERR_VARIANCE_NOTE_REQUIRED | 422 |
| ERR_REBUDGET_NOT_ZERO_SUM | 422 |
| ERR_F_AND_A_LINE_SYSTEM_MANAGED | 422 |
| ERR_EXPENDITURE_TYPE_SYSTEM_MANAGED | 422 |
| ERR_BUDGET_LINE_AWARD_MISMATCH | 422 |
| ERR_CATEGORY_TYPE_MISMATCH | 422 |
| ERR_SALARY_NO_COMMITMENT | 422 |
| ERR_TRANSFER_TARGET_SAME_AS_SOURCE | 422 |
| ERR_PAYMENT_METHOD_MISMATCH | 422 |
| ERR_BUDGET_NOT_FULLY_ALLOCATED | 422 |
| ERR_RECEIVABLE_OVERPAYMENT | 422 |
| ERR_UNLIQUIDATED_OBLIGATIONS | 422 |
| ERR_MTDC_ELIGIBLE_EXCEEDS_AUTHORIZED | 422 |
| ERR_NO_UNINVOICED_COSTS | 422 |
| ERR_BUDGET_LINE_EXCEEDED | 402 |
| ERR_DRAWDOWN_EXCEEDS_ELIGIBLE | 402 |
| ERR_SUBAWARD_BUDGET_EXCEEDED | 402 |
| ERR_INVALID_REQUEST | 400 |
