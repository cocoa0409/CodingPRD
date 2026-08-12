# Nonprofit Grant Reporting API — Product Requirements Document

## 1. Introduction

A grants management office inside a mid-sized nonprofit spends the weeks after each reporting period assembling the same artifacts by hand: a budget-versus-actual workbook per award, a narrative report for the funder, match documentation binders, variance explanations written line by line, and a calendar reminder chain for interim and final deadlines. Mistakes surface late — an expense charged to the wrong restricted fund is discovered during the funder's site visit, a no-cost extension is approved by email and the reporting calendar is never rebuilt, a final report goes out without evidence that the required match has been documented and verified. The office also carries an audit exposure: when an external auditor issues a finding of material weakness, work on the affected award should halt immediately, yet in practice expense posting and report submission continue while the finding is being discussed.

This document specifies the Nonprofit Grant Reporting API, a system that organizes the full post-award lifecycle around a single organizing aggregate — the Grant — and treats reporting, fund restriction, modification, match documentation, audit response, and renewal as first-class workflows with explicit state machines. The system is designed around segregation of duties: the staff member who records an expense is never the one who posts it, and the staff member who documents a matching contribution is never the one who verifies it. Funder-side actors (reviewers who accept or return reports, approve or deny modification requests, and decide renewals) authenticate through the same API but are scoped to the grants awarded by their own organization.

A single logical clock drives all time-based behavior, including the opening and lapsing of renewal windows; the server boots with the clock pinned to exactly `2026-05-01T00:00:00Z` and never consults the wall clock. A SystemAdmin-only test-driving capability advances the logical clock to a supplied instant and fires any time-based automatic transitions that fall due. The audience for this PRD is the engineering team building the service; it is the sole authoritative specification of externally visible behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to every endpoint and every entity in the API.

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user or funder organization, and `X-User-Role`, declaring the capacity in which that actor operates. A request missing either header, or presenting a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the acting role must appear in the endpoint's authorized role list; a role mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles, spelled as follows: `SystemAdmin`, `GrantsOfficer`, `FinanceManager`, `ProgramDirector`, `Funder`, and `Auditor`.

- A `GrantsOfficer` is grants management office staff: this role builds the grant structure, drafts and submits reports, records and allocates expenses, documents match contributions, drafts and withdraws modification requests, responds to audit findings, and creates renewal applications.
- A `FinanceManager` is finance staff: this role creates funds, posts and voids expenses, and verifies match contributions. It is deliberately segregated from expense creation and match documentation.
- A `ProgramDirector` is program leadership: this role activates and closes grants, submits modification requests, submits renewal applications, and schedules audit engagements.
- A `Funder` is a funder-side reviewer: this role starts review on, accepts, and returns reports; approves and denies modification requests; and decides renewal applications. When `X-User-Role` is `Funder`, `X-User-ID` is the `id` of the acting `Funder` entity; any funder-scoped action compares the target grant's `funder_id` against `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. A funder never sees another funder's decisions applied to its grants.
- An `Auditor` is an external auditor: this role advances audit engagements through their stages, files findings on conducted engagements, and resolves or reopens grantee responses.
- A `SystemAdmin` is the platform operator: this role registers funders and drives the test clock.

For the five staff-side roles — `GrantsOfficer`, `FinanceManager`, `ProgramDirector`, `Auditor`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on an `Expense`, as `posted_by_user_id` on a posted expense, as `prepared_by_user_id` on an edited report, as `documented_by_user_id` or `verified_by_user_id` on a `MatchContribution`, as `created_by_user_id` or `submitted_by_user_id` on a `ModificationRequest`, or as `created_by_user_id` on an `ExpenseAllocation`), but it does not compare such an identifier to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned in a single page: it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip before the page begins and defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. The reporting-calendar listing of a grant's reports is the one exception to the default presentation ordering: rows are returned ordered by `period_index` ascending. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource in the system — `Funder`, `Grant`, `BudgetLine`, `Fund`, `Expense`, `ExpenseAllocation`, `Report`, `VarianceExplanation`, `MatchContribution`, `ModificationRequest`, `AuditEngagement`, `AuditFinding`, and `RenewalApplication` — carries a standard set of system-managed fields:

- `id` (string): a unique server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, and which anchors the optimistic concurrency control mechanism described in §2.8.

Any mutation that touches derived totals — for example recomputing a grant's `total_expended_cents` after an allocation is created or voided, bumping a budget line's `expended_cents`, or updating a grant's `end_date` on an approved extension — counts as a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Representation, Precision, and Rounding

All monetary values are integers denominated in cents — field names such as `award_amount_cents`, `budgeted_cents`, `adjusted_cents`, `expended_cents`, `allocated_cents`, `remaining_cents`, `amount_cents`, `unallocated_cents`, `total_expended_cents`, `documented_value_cents`, `recognized_value_cents`, `required_match_cents`, `indirect_cap_cents`, `match_verified_only_cents`, `match_pledged_inclusive_cents`, `burn_trailing_cents`, and `burn_cumulative_cents` all carry integer cents, with no fractional rounding anywhere in the ledger. Two derived quantities are non-integer: percentage figures (variance percentages, match progress percentages) are expressed as numbers rounded half-up to exactly 2 decimal places, and the pacing ratio is likewise a number rounded half-up to 2 decimal places. Where a calculation must convert a fractional product back to cents — the volunteer-time recognition rate, the indirect-cost pool, the per-period proration of a budget line, and the burn-rate projections — the rule is stated alongside the calculation in §3; none of these conversions use float arithmetic, and the proration rule in particular rounds down per period.

### 2.6. Hierarchical Consistency and Cascade Semantics

The entity graph is grant-rooted: a `BudgetLine`, `Fund`, `Expense`, `Report`, `MatchContribution`, `ModificationRequest`, `AuditEngagement`, and `RenewalApplication` each belong to exactly one `Grant`, an `ExpenseAllocation` belongs to exactly one `Expense` while also referencing a `BudgetLine` and a `Fund`, a `VarianceExplanation` belongs to a `Report`, and an `AuditFinding` belongs to an `AuditEngagement`. Parent-child consistency is maintained by automatic cascades, not by client bookkeeping. When a grant is suspended because a material weakness has been filed, every report of that grant in `DRAFT` or `RETURNED` is frozen in place and every variance explanation in `DRAFTED` on those reports is locked; when the suspension lifts, the same rows are unfrozen and unlocked in the reverse direction. When a posted expense is voided, every active allocation of that expense is voided with it and the affected budget-line, fund, and grant totals are decremented in the same transaction. When a funder approves an extension or reallocation, the grant's version is bumped as part of the same mutation that applies the side effects. These cascades are the system's mechanism for keeping derived totals (`expended_cents` on lines and funds, `remaining_cents` on funds, `unallocated_cents` on expenses, `total_expended_cents` on grants, `adjusted_cents` on lines, `period_budgets_cents` on lines) continuously reconciled with the underlying activity.

### 2.7. Nested Resource Retrieval

Requests that address a resource through a nested path (for example, an expense reached under its grant, or a finding reached under its engagement) are validated left to right. The server first resolves the leftmost identifier; if it does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any identifier further to the right is examined. Existence checking therefore precedes every business rule: an unknown parent yields 404 even if the payload would also have failed validation. Only after every path identifier has been resolved do role, state, and business validations run, in the priority order described in §2.10.

### 2.8. Optimistic Concurrency Control

Exactly one write endpoint in the API participates in optimistic concurrency control: the funder-side approval of a submitted modification request. Such a request must carry `expected_grant_version` as a non-optional input field, holding the `version` of the parent `Grant` as the approving client last observed it. If the value presented does not equal the grant's current `version` — because, for instance, another modification approval has already mutated the grant's `end_date` or a budget line's `adjusted_cents` and advanced the version — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the approver from deciding against an award baseline it has not observed. No other endpoint accepts or requires a version field; clients must not send `expected_grant_version` anywhere else.

### 2.9. The Segregation-of-Duties Principle

Two workflow pairs are segregated by policy, and the server enforces the separation by comparing the acting `X-User-ID` against the identifier recorded on the resource. Posting an expense requires that the poster differ from the expense's `created_by_user_id`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Verifying a match contribution requires that the verifier differ from the contribution's `documented_by_user_id`; again a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. The comparisons are by opaque user identifier — they do not involve role checks, and two different staff members sharing a role still satisfy the rule as long as their `X-User-ID` values differ.

### 2.10. Validation Priority Order

When a request fails several rules at once, the error the client observes is determined by a fixed priority order; lower-numbered categories are evaluated first. The order is:

1. Authentication — presence and validity of `X-User-Role` and `X-User-ID`, yielding `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is authorized for the endpoint, and for funder-scoped actions the acting `X-User-ID` equals the grant's `funder_id`, yielding `ERR_FORBIDDEN`.
3. Existence — every path identifier resolves, left to right, yielding `ERR_NOT_FOUND`.
4. Segregation of duties — the poster is not the expense creator, and the verifier is not the match documenter, yielding `ERR_SEGREGATION_OF_DUTIES`.
5. State preconditions — the generic state-machine from-state checks plus the named state guards (`ERR_INVALID_STATE`, `ERR_GRANT_NOT_ACTIVE`, `ERR_GRANT_SUSPENDED`, `ERR_REPORT_NOT_EDITABLE`, `ERR_EXPENSE_NOT_POSTED`, `ERR_MODIFICATION_NOT_PENDING`, `ERR_FINDING_NOT_OPEN`, `ERR_RENEWAL_WINDOW_NOT_OPEN`, `ERR_RENEWAL_WINDOW_LAPSED`, `ERR_EXPENSE_LOCKED_BY_REPORT`), and the stale-version check `ERR_STALE_VERSION` on modification approval.
6. Fund restriction — a restricted fund's category gate, yielding `ERR_RESTRICTION_VIOLATION`.
7. Business constraints — uniqueness and capacity rules, yielding `ERR_DUPLICATE_AWARD_NUMBER`, `ERR_ENGAGEMENT_OVERLAP`, `ERR_AUDITOR_CAPACITY`, and `ERR_REALLOCATION_NOT_BALANCED`.
8. Temporal rules — the extension-moves-forward rule, yielding `ERR_EXTENSION_NOT_FORWARD`.
9. Referential and submission-content rules — cross-grant reference checks (`ERR_VALIDATION`), the variance-explanation gate (`ERR_VARIANCE_EXPLANATION_REQUIRED`), the outcome-data gate (`ERR_OUTCOME_DATA_REQUIRED`), the final-report match gate (`ERR_MATCH_SHORTFALL`), and the below-expended reallocation guard (`ERR_REALLOCATION_BELOW_EXPENDED`).
10. Fiscal limits — the per-allocation caps, yielding `ERR_EXPENSE_OVERALLOCATED`, `ERR_BUDGET_LINE_EXCEEDED`, and `ERR_FUND_EXCEEDED`.

A consequence worth internalizing: an unauthorized caller always sees `ERR_FORBIDDEN` before learning whether the resource exists is *not* the behavior — existence at priority 3 is evaluated after authorization, but state and business rules never mask a 404, and a fiscal cap never masks a restriction violation.

### 2.11. The Logical Clock and Time-Based Auto-Transitions

All "current time" evaluations in the system — period-start checks when opening a report, lateness computation at submit, renewal window opening and lapsing — read a single logical clock maintained by the server. At server startup the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A `SystemAdmin` may advance the logical clock by supplying a `to_iso8601` instant; the response carries the resulting `current_utc`. Advancing the clock fires any time-based automatic transitions whose moment has arrived: a renewal application in `NOT_OPEN` whose `window_open` has been reached moves to `ELIGIBLE`, and one in `ELIGIBLE` whose `window_close` has passed without a submission moves to `LAPSED`.

## 3. Business Logic & Workflows

### 3.1. Funders and the Shape of an Award

Before any grant can exist, a `SystemAdmin` registers the awarding organization as a `Funder`, supplying its `name`, a `funder_type` drawn from `FEDERAL`, `STATE`, `FOUNDATION`, or `CORPORATE`, a `contact_email`, and optionally `requires_match`, a boolean that defaults to `false` and records whether awards from this funder customarily carry a match commitment. The funder type is not merely descriptive: when a grant under a `FEDERAL` funder leaves its negotiated indirect rate unset, the de minimis rate applies automatically in the indirect-pool computation (§3.6).

A `GrantsOfficer` then creates the `Grant` itself. The creation payload carries the `funder_id` of the awarding funder, the funder-assigned `award_number`, a `title`, the total `award_amount_cents`, the `start_date` and `end_date` of the award period (dates at UTC midnight), and the `reporting_frequency` — one of `MONTHLY`, `QUARTERLY`, `SEMIANNUAL`, or `ANNUAL`. Five optional knobs tune the reporting and compliance posture: `interim_report_due_days` (default 30), the number of days after a period end that an interim report falls due; `final_report_due_days` (default 90), the analogous lead time for the final report; `variance_threshold_pct` (default 10.0), the absolute period-variance percentage at or above which a budget line demands a written explanation; `renewal_window_days` (default 60), the number of days before `end_date` at which the renewal window opens; and `required_match_cents` (default 0), the match commitment the grantee must document. Two further fields govern indirect costs: `indirect_rate_pct` (default 0, meaning unset) and `indirect_cap_cents` (default null, meaning uncapped).

At creation the server snapshots `end_date` into `original_end_date`; the snapshot is never mutated, even when an approved extension later moves `end_date` forward. A grant is born in `DRAFT` status with `total_expended_cents` equal to zero. One uniqueness rule guards creation: `award_number` must be unique per funder, so two grants from the same funder carrying the same award number are rejected with `ERR_DUPLICATE_AWARD_NUMBER` (HTTP 409).

While the grant is in `DRAFT`, the office structures it. A `GrantsOfficer` adds `BudgetLine` rows, each with a `category` drawn from `PERSONNEL`, `FRINGE`, `TRAVEL`, `EQUIPMENT`, `SUPPLIES`, `CONTRACTUAL`, `INDIRECT`, or `OTHER`, plus the line's `budgeted_cents` authority. In parallel a `FinanceManager` creates `Fund` rows for the same grant, each carrying a `fund_type` of `RESTRICTED` or `UNRESTRICTED`, an `allocated_cents` budget authority, an optional free-text `purpose_restriction` (meaningful for restricted funds), and an `allowed_categories` list naming the budget-line categories the fund may pay for; an empty `allowed_categories` array means every category is allowed. Each fund tracks `expended_cents` (zero at creation) and exposes `remaining_cents`, the difference between its allocated authority and what has been expended against it. Budget lines similarly expose `adjusted_cents` — initially equal to `budgeted_cents`, later moved by approved reallocations — and `expended_cents`, plus a computed `period_budgets_cents` vector described in §3.2. Both budget-line and fund creation are only possible while the grant is in `DRAFT`.

### 3.2. Activation and the Reporting Calendar

A grant becomes operational when a `ProgramDirector` activates it, moving `status` from `DRAFT` to `ACTIVE`. Activation has two structural preconditions, each enforced with `ERR_INVALID_STATE` (HTTP 409): at least one `BudgetLine` must exist for the grant, and at least one `Fund` must exist for the grant.

Activation performs two cascades in a single step. First, the system generates the grant's full reporting calendar: one `Report` row per period implied by the grant's `reporting_frequency`, tiling the inclusive range from `start_date` through `end_date`. Every generated row starts in `SCHEDULED` status. Rows are numbered by a 1-based `period_index`; each carries its `period_start` (inclusive) and `period_end` (inclusive date); the last period of the current calendar is marked `period_type` `FINAL` and every earlier period is `INTERIM`. Each row's `due_date` is computed as its `period_end` plus `interim_report_due_days` for an `INTERIM` row or plus `final_report_due_days` for the `FINAL` row. A fresh report row also carries an empty `narrative_draft` string, an empty `outcome_entries` array, `frozen` set to `false`, a `revision_count` of zero, a null `submitted_at`, `submitted_late` false, a null `prepared_by_user_id`, and a null `returned_reason`.

Second, activation computes every budget line's `period_budgets_cents`, the per-period proration of the line's `adjusted_cents` across the reporting calendar. The proration follows a waterfall with a pinned order. Let the number of report periods be n. The base per-period amount is `adjusted_cents` divided by n, rounded down to a whole cent. The remainder — `adjusted_cents` minus the base times n — is assigned in full to the final period. Concretely, periods 1 through n−1 each receive the base amount, and period n receives the base plus the remainder. This is integer-cent arithmetic with no fractional rounding; the floor-per-period-then-residual-to-final ordering is load-bearing, since rounding each period to the nearest cent would produce a different vector (a line of 10,000,003 cents over 4 periods is the canonical divergence). The same proration recomputes, per affected line, whenever a budget reallocation is approved (§3.7).

A grant whose final report has been accepted moves automatically from `ACTIVE` to `CLOSEOUT`, and a `ProgramDirector` then closes it, moving `CLOSEOUT` to `CLOSED`. Closure is guarded by three checks, each failing with `ERR_INVALID_STATE`: every report of the grant must be in `ACCEPTED`; no audit finding on any engagement of the grant may be `OPEN` or `RESPONSE_SUBMITTED`; and no modification request of the grant may be in `DRAFT` or `SUBMITTED`.

### 3.3. Recording Expenses and Splitting Them Across Lines and Funds

Day-to-day spending begins when a `GrantsOfficer` records an `Expense` against an `ACTIVE` grant, supplying the `expense_date` (which determines which report period the expense belongs to), the payee `vendor`, a free-text `description`, and the total `amount_cents`, which must be greater than zero. Creation is blocked unless the grant is `ACTIVE`: against a grant in `DRAFT`, `CLOSEOUT`, or `CLOSED` the create is rejected with `ERR_GRANT_NOT_ACTIVE` (HTTP 409), and against a `SUSPENDED` grant it is rejected with `ERR_GRANT_SUSPENDED` (HTTP 409). A new expense starts in `DRAFT` status with `unallocated_cents` equal to its full `amount_cents`; the server records the creator's `X-User-ID` as `created_by_user_id`, and `posted_by_user_id` is null.

A `FinanceManager` then posts the expense, moving it from `DRAFT` to `POSTED`. Posting requires the grant to be `ACTIVE` — the same `ERR_GRANT_NOT_ACTIVE` / `ERR_GRANT_SUSPENDED` pair guards it — and enforces segregation of duties: if the acting `X-User-ID` equals the expense's `created_by_user_id`, the post is rejected with `ERR_SEGREGATION_OF_DUTIES`. On success, `posted_by_user_id` is set to the poster's identifier.

Only a `POSTED` expense can be allocated. A `GrantsOfficer` creates an `ExpenseAllocation` row that splits some or all of the expense across a `BudgetLine` and a `Fund`, passing the `budget_line_id`, the `fund_id`, and the `amount_cents` for this split; the allocated amount must be greater than zero. Allocating against an expense still in `DRAFT` is rejected with `ERR_EXPENSE_NOT_POSTED` (HTTP 409). A battery of checks then guards the split, in the priority order of §2.10. The referenced budget line and fund must both belong to the same grant as the expense; a cross-grant reference is rejected with `ERR_VALIDATION` (HTTP 400). If the chosen fund is `RESTRICTED`, the line's `category` must appear in the fund's `allowed_categories` (with an empty array permitting every category); otherwise the allocation is rejected with `ERR_RESTRICTION_VIOLATION` (HTTP 422). Three fiscal caps follow: the allocation may not exceed the expense's `unallocated_cents` (`ERR_EXPENSE_OVERALLOCATED`, 422); it may not push the line's `expended_cents` above its `adjusted_cents` (`ERR_BUDGET_LINE_EXCEEDED`, 422); and it may not push the fund's `expended_cents` above its `allocated_cents` (`ERR_FUND_EXCEEDED`, 422).

Each allocation row carries a system-set `status` of `ACTIVE` and records the allocator's `X-User-ID` as `created_by_user_id`. Its creation has four immediate side effects: the budget line's `expended_cents` increases by the allocated amount, the fund's `expended_cents` increases by the same amount, the grant's `total_expended_cents` is recomputed as the sum over all active allocations on the grant, and the expense's `unallocated_cents` — its `amount_cents` minus the sum over its active allocations — is recomputed. An expense may be split by several allocations across lines and funds until its unallocated remainder reaches zero.

Voiding is the compensating action. A `FinanceManager` may void a `POSTED` expense, but only while none of its active allocations has an `expense_date` falling inside a report period whose `Report` is `SUBMITTED`, `UNDER_REVIEW`, or `ACCEPTED`; if any allocation is so locked, the void is rejected with `ERR_EXPENSE_LOCKED_BY_REPORT` (HTTP 409). A successful void moves the expense to `VOIDED` and cascades: every active allocation of the expense transitions to `VOIDED`; for each voided allocation the corresponding budget line's `expended_cents` and fund's `expended_cents` are decremented by the allocation's amount; and the grant's `total_expended_cents` is recomputed. An `ExpenseAllocation` never transitions on its own — `VOIDED` is reached only via the parent expense's void cascade, and voided allocations contribute nothing to any total or variance computation.

### 3.4. Drafting, Submitting, and Reviewing Reports

When a period begins, a `GrantsOfficer` opens the corresponding `SCHEDULED` report for drafting, moving it to `DRAFT`. Two preconditions guard the transition: the grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`, or `ERR_GRANT_SUSPENDED` when the grant is suspended), and the current logical time must have reached the report's `period_start` (otherwise `ERR_INVALID_STATE`). While in `DRAFT`, the officer edits the report body: the `narrative_draft` free text and the `outcome_entries` array, whose rows are objects with `metric_name`, `target_value`, `actual_value`, and `unit`. Editing is only possible while the report is in `DRAFT` and not frozen; an edit against a report in any other status, or a frozen one, is rejected with `ERR_REPORT_NOT_EDITABLE` (HTTP 409). Each successful edit stamps the editor's `X-User-ID` into `prepared_by_user_id`.

Variance explanations are drafted alongside the narrative. A `GrantsOfficer` records a `VarianceExplanation` on a report by naming a `budget_line_id` and supplying a non-empty `explanation_text`; each budget line admits at most one explanation per report, so a repeat submission for the same line refreshes the existing row rather than adding a sibling. The owning report is identified on the row itself via a system-set `report_id` referencing the parent `Report`. Creating an explanation against a report that is not editable (not in `DRAFT`, or frozen) is likewise rejected with `ERR_REPORT_NOT_EDITABLE`. At the moment of creation the server snapshots the line's period-only variance percentage into `period_variance_pct_snapshot`, computed exactly as the period-only variant of §3.6. A new explanation starts in `DRAFTED` status.

Submitting the report to the funder is the gated transition, moving `DRAFT` to `SUBMITTED`. Its guards, evaluated in the priority order of §2.10, are: the grant must not be `SUSPENDED` and the report must not be frozen — a violation is rejected with `ERR_GRANT_SUSPENDED`; the `narrative_draft` must be non-empty and `outcome_entries` must contain at least one entry — otherwise `ERR_OUTCOME_DATA_REQUIRED` (HTTP 422); every budget line of the grant whose period-only absolute variance percentage is at least the grant's `variance_threshold_pct` must have a `VarianceExplanation` row (with any non-empty text) on this report — otherwise `ERR_VARIANCE_EXPLANATION_REQUIRED` (HTTP 422). The variance gate exempts zero-activity lines: a line whose period actuals are exactly zero is never forced to produce an explanation, regardless of its variance percentage. For the `FINAL` report only, one further gate applies: the verified match total must be at least the grant's `required_match_cents`, otherwise submission is rejected with `ERR_MATCH_SHORTFALL` (HTTP 422). On successful submission, `submitted_at` is set to the current logical time, `submitted_late` is recomputed as whether `submitted_at` falls after the end of the due date's day (23:59:59Z), and every `VarianceExplanation` on the report in `DRAFTED` transitions to `SUBMITTED`.

Review is funder-side. The acting funder starts review, moving `SUBMITTED` to `UNDER_REVIEW`; from there the funder either accepts the report, moving it to `ACCEPTED`, or returns it, moving it to `RETURNED`. All three funder actions are scoped: the acting `Funder`'s `id` must equal the grant's `funder_id`, otherwise the action is rejected with `ERR_FORBIDDEN`. Returning a report requires a `returned_reason` in the payload, which is stored on the report; returning also transitions every `VarianceExplanation` on the report that is in `SUBMITTED` back to `DRAFTED`, so the grantee can rework the explanations alongside the narrative. Accepting the `FINAL` report has a cross-entity cascade: the grant itself transitions from `ACTIVE` to `CLOSEOUT`.

A returned report re-enters the revision loop. A `GrantsOfficer` reopens it, moving `RETURNED` back to `DRAFT`; the grant must not be `SUSPENDED` (else `ERR_GRANT_SUSPENDED`). Each such reopen increments `revision_count` by exactly one. The loop may repeat indefinitely — `RETURNED` to `DRAFT` to `SUBMITTED` and back — until the funder accepts; `ACCEPTED` is the terminal state of the report lifecycle.

### 3.5. Documenting and Verifying the Match

A grant with a positive `required_match_cents` tracks its matching and in-kind pipeline through `MatchContribution` rows. A `GrantsOfficer` records a contribution against an `ACTIVE` grant — creation is rejected with `ERR_GRANT_NOT_ACTIVE` when the grant is not active and with `ERR_GRANT_SUSPENDED` when it is suspended — supplying a `source_name` for the contributor, a `contribution_type` of `CASH`, `IN_KIND_GOODS`, `IN_KIND_SERVICES`, or `VOLUNTEER_TIME`, a `valuation_basis` of `FAIR_MARKET`, `ACTUAL_COST`, or `STANDARD_RATE`, and, depending on the type, a `documented_value_cents` (default 0) or `volunteer_hours` (default 0). The server immediately computes `recognized_value_cents`: for `VOLUNTEER_TIME` contributions, the recognized value is the `volunteer_hours` multiplied by the standard volunteer rate of 3,150 cents per hour, rounded to whole cents; for every other contribution type the recognized value equals the `documented_value_cents`. A new contribution starts in `PLEDGED` status with `documented_by_user_id` and `verified_by_user_id` both null.

Documentation moves a contribution from `PLEDGED` to `DOCUMENTED`. A `GrantsOfficer` performs the transition, attaching a `documentation_ref` pointing at the evidence; the grant must be `ACTIVE`, with the same `ERR_GRANT_NOT_ACTIVE` / `ERR_GRANT_SUSPENDED` pair guarding it. On success the server records the actor's `X-User-ID` as `documented_by_user_id`. Verification moves a `DOCUMENTED` contribution to `VERIFIED` and is performed by a `FinanceManager`; the verifier must differ from the documenter — an acting `X-User-ID` equal to `documented_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` — and on success `verified_by_user_id` is set.

Two progress totals derive from the contribution set and appear in the grant summary. The verified-only total, `match_verified_only_cents`, sums `recognized_value_cents` over contributions in `VERIFIED` status only; this is the compliance position and is the figure the `FINAL` report submit gate compares against `required_match_cents`. The pledged-inclusive total, `match_pledged_inclusive_cents`, sums `recognized_value_cents` over contributions in `PLEDGED`, `DOCUMENTED`, or `VERIFIED`; this is the pipeline view shown to development staff. Each total is also expressed as a percentage of `required_match_cents` — `match_verified_only_pct` and `match_pledged_inclusive_pct` respectively — rounded half-up to 2 decimal places; when `required_match_cents` is zero, both percentages are null.

### 3.6. Budget-versus-Actual, Indirect Pool, and Burn Projections

The grant summary read is a computed view that assembles the office's standard post-period workbook. It is also, internally, the evaluation point for the report submit gating described in §3.4. The summary exposes `grant_id`, `status`, `total_expended_cents`, `indirect_pool_cents`, the two match totals and their percentages, `burn_trailing_cents`, `burn_cumulative_cents`, `pacing_ratio`, and the `bva` array of per-line budget-versus-actual rows.

Each `bva` row compares a budget line's actuals to its budget authority in two variants. In the period-only variant, actuals are the sum of `amount_cents` over `ExpenseAllocation` rows on the line that are `ACTIVE` and whose parent expense's `expense_date` falls between the report period's `period_start` and `period_end` inclusive; the budget figure is the line's `period_budgets_cents` entry for that period index. In the cumulative variant, actuals sum every active allocation on the line whose expense date is on or before the period end, with no lower bound, and the budget figure is the sum of the line's `period_budgets_cents` entries from period 1 through the current period index — the same ledger, different totals. Either variant's variance percentage is computed as actual minus budget, divided by budget, multiplied by 100, and rounded half-up to 2 decimal places; when the budget figure is zero the variance percentage is null. Only `ACTIVE` allocations ever contribute: voided allocations (and hence everything belonging to a voided expense) are excluded, and expenses still in `DRAFT` contribute nothing because allocations cannot exist until the expense is posted. The period-only variant is the one that feeds the submit gate: a line requires an explanation exactly when its period-only actuals are greater than zero and the absolute value of its period-only variance percentage is at least the grant's `variance_threshold_pct` — the comparator is inclusive.

The indirect cost pool tiers off the direct base. The direct base is the sum of `amount_cents` over all `ACTIVE` allocations on the grant whose budget line's `category` is anything other than `INDIRECT`. The applicable rate is the grant's `indirect_rate_pct`; when that rate is zero (unset) and the awarding funder's `funder_type` is `FEDERAL`, the de minimis rate of 10 percent applies instead; when the rate is zero and the funder is not federal, the rate is zero. The uncapped pool is the direct base multiplied by the rate and divided by 100, rounded down to whole cents. When the grant's `indirect_cap_cents` is not null, the pool is the smaller of the uncapped figure and the cap; when the cap is null the pool is the uncapped figure. The result is exposed as `indirect_pool_cents`.

Two burn projections close out the summary, both derived exclusively from the grant's `ACCEPTED` reports ordered by `period_index` ascending; periods not yet accepted contribute nothing, and when no report has been accepted yet both burn figures are zero and `pacing_ratio` is null. The trailing-average variant takes the mean of per-period totals (active allocations by expense date) over the most recent 1 closed period — a deliberately short window reflecting current momentum — and multiplies that average by the total number of report periods, rounding to whole cents, yielding `burn_trailing_cents`. The cumulative-average variant divides the grant's `total_expended_cents` by the number of accepted periods and multiplies by the total number of periods, again rounded to whole cents, yielding `burn_cumulative_cents`. The `pacing_ratio` divides `total_expended_cents` by the pro-rata award — the `award_amount_cents` multiplied by the number of accepted periods and divided by the total number of periods — and rounds half-up to 2 decimal places.

### 3.7. Extensions, Reallocations, and the Award Baseline

When circumstances change mid-award, the office drafts a `ModificationRequest`. A `GrantsOfficer` creates the draft, supplying a `request_type` of `NO_COST_EXTENSION` or `BUDGET_REALLOCATION` and a free-text `justification`. An extension carries a `requested_end_date` (required for that type, null otherwise); a reallocation carries `line_deltas`, an array of objects each pairing a `budget_line_id` with a signed `delta_cents`. A new request is in `DRAFT` status, with `created_by_user_id` recording the drafter and both `submitted_by_user_id` and `decided_by_funder_id` null.

A `ProgramDirector` submits the draft, moving it from `DRAFT` to `SUBMITTED`. Submission requires the grant to be `ACTIVE` (`ERR_GRANT_NOT_ACTIVE` when it is not, `ERR_GRANT_SUSPENDED` when it is suspended), and then applies the type-specific rules in the priority order of §2.10. For a `NO_COST_EXTENSION`, the `requested_end_date` must be strictly after the grant's current `end_date`; a request that does not move the end date forward is rejected with `ERR_EXTENSION_NOT_FORWARD` (HTTP 422). For a `BUDGET_REALLOCATION`, the `delta_cents` values across `line_deltas` must sum to exactly zero — money moves between lines, it is not created — otherwise `ERR_REALLOCATION_NOT_BALANCED` (HTTP 422); and for every delta, the target line's `adjusted_cents` plus the delta must remain at least the line's `expended_cents`, so authority can never be pulled below money already spent, otherwise `ERR_REALLOCATION_BELOW_EXPENDED` (HTTP 422). On successful submission, `submitted_by_user_id` records the submitter.

Decision is funder-side and funder-scoped: the acting `Funder`'s `id` must equal the grant's `funder_id`, otherwise `ERR_FORBIDDEN`. Approving or denying a request that is not in `SUBMITTED` is rejected with `ERR_MODIFICATION_NOT_PENDING` (HTTP 409); withdrawal is possible from `DRAFT` or `SUBMITTED` and is rejected with the same error once the request is terminal. Approval is the OCC-protected write of §2.8: the request body must carry `expected_grant_version` equal to the grant's current `version`, or the approval is rejected with `ERR_STALE_VERSION` (HTTP 412).

An approval applies its side effects atomically and increments the grant's `version` by exactly one. For a `NO_COST_EXTENSION`, the grant's `end_date` is set to the `requested_end_date` and the reporting calendar is regenerated around the new end: an existing `FINAL` report that is still `SCHEDULED` is demoted to `INTERIM`, new `Report` rows are appended to tile the range from the day after the old `end_date` through the `requested_end_date`, with the last appended period marked `FINAL`, and future `SCHEDULED` reports are otherwise unchanged. For a `BUDGET_REALLOCATION`, each affected budget line's `adjusted_cents` is increased by its `delta_cents` and the `period_budgets_cents` vector of every affected line is recomputed by the waterfall proration of §3.2. In both cases `decided_by_funder_id` is set to the acting funder's `id`. Denial is simpler: the request moves `SUBMITTED` to `DENIED`, an optional `denial_reason` may accompany the decision, and `decided_by_funder_id` is set. A `GrantsOfficer` may withdraw a request from either `DRAFT` or `SUBMITTED`, moving it to `WITHDRAWN` with no side effects. `APPROVED`, `DENIED`, and `WITHDRAWN` are all terminal.

### 3.8. Audit Engagements, Findings, and Suspension

Audit preparation starts when a `ProgramDirector` schedules an `AuditEngagement` on an `ACTIVE` grant, supplying an `engagement_type` of `FINANCIAL_AUDIT`, `SITE_VISIT`, or `DESK_REVIEW`, an `auditor_org` identifying the audit firm, and the engagement window as `scheduled_start` (inclusive) and `scheduled_end` (exclusive — the window is a half-open interval). Two capacity and overlap rules guard creation, both in priority tier 7. The window must not overlap any other non-`CLOSED` engagement on the same grant; because intervals are half-open, adjacency is allowed — one engagement ending exactly when another begins is not an overlap. A violation is rejected with `ERR_ENGAGEMENT_OVERLAP` (HTTP 409). Independently, the named `auditor_org` may hold at most 2 mutually-overlapping active engagements across the whole system; if creating this engagement would give the firm a third mutually-overlapping active engagement, creation is rejected with `ERR_AUDITOR_CAPACITY` (HTTP 409).

A new engagement is in `SCHEDULED` status. The assigned `Auditor` advances it one step at a time along a fixed ladder — `SCHEDULED` to `PREPARATION`, then to `READY`, then to `CONDUCTED`, then to `FINDINGS_ISSUED`, and finally to `CLOSED`. The final advance is guarded: every `AuditFinding` of the engagement must be `RESOLVED` before the engagement can close, otherwise `ERR_INVALID_STATE`.

Findings are filed by an `Auditor` while the engagement is `CONDUCTED` or `FINDINGS_ISSUED`, each carrying a `severity` of `OBSERVATION`, `DEFICIENCY`, or `MATERIAL_WEAKNESS` and a free-text `description`. The owning engagement is identified on the finding itself via a system-set `engagement_id` referencing the parent `AuditEngagement`. A new finding is in `OPEN` status with `response_text` null. Filing a `MATERIAL_WEAKNESS` finding against an engagement of an `ACTIVE` grant has an immediate cross-aggregate cascade: the grant transitions automatically from `ACTIVE` to `SUSPENDED`, every report of that grant in `DRAFT` or `RETURNED` has `frozen` set to `true` (blocking both edits and submission), and every `VarianceExplanation` in `DRAFTED` on those reports transitions to `LOCKED`. While a grant is `SUSPENDED`, report submit and revise, expense create and post, match documentation, and modification submit are all rejected with `ERR_GRANT_SUSPENDED`.

The grantee answers a finding through a `GrantsOfficer`, moving it from `OPEN` to `RESPONSE_SUBMITTED` and storing the supplied `response_text`. Responding to a finding that is not `OPEN` is rejected with `ERR_FINDING_NOT_OPEN` (HTTP 409). The auditor then dispositions the response: resolving moves `RESPONSE_SUBMITTED` to `RESOLVED`, while reopening moves it back to `OPEN` — and the reopen loop may repeat, `RESPONSE_SUBMITTED` to `OPEN` to `RESPONSE_SUBMITTED` again, until the auditor is satisfied. Both resolve and reopen require the finding to be in `RESPONSE_SUBMITTED`, otherwise `ERR_FINDING_NOT_OPEN`. Resolution of a `MATERIAL_WEAKNESS` finding has the inverse cascade: if no other `OPEN` or `RESPONSE_SUBMITTED` `MATERIAL_WEAKNESS` finding remains on any engagement of the grant, the grant transitions automatically from `SUSPENDED` back to `ACTIVE`, every frozen report of the grant has `frozen` cleared to `false`, and every `VarianceExplanation` in `LOCKED` transitions back to `DRAFTED`.

### 3.9. The Renewal Window

Each grant admits at most one `RenewalApplication`; attempting to create a second is rejected with `ERR_INVALID_STATE`. A `GrantsOfficer` creates the application with an empty payload, and the server computes its window: `window_open` is the grant's `end_date` minus `renewal_window_days`, taken at 00:00:00Z, and `window_close` is the grant's `end_date` at 23:59:59Z. A fresh application starts in `NOT_OPEN` status with `submitted_at` null.

The window opens and lapses on the logical clock, not on user action. When clock advancement brings the current time to or past `window_open`, an application in `NOT_OPEN` moves automatically to `ELIGIBLE`. When the current time passes `window_close` with no submission having occurred, an `ELIGIBLE` application moves automatically to `LAPSED`.

While the application is `ELIGIBLE`, a `ProgramDirector` submits it; submission stamps `submitted_at` with the current logical time. Submitting from `NOT_OPEN` — before the window has opened — is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409); submitting from `LAPSED` — after the window has closed — is rejected with `ERR_RENEWAL_WINDOW_LAPSED` (HTTP 409). The decision is funder-side and funder-scoped in the usual way (`ERR_FORBIDDEN` when the acting funder does not own the grant): the funder supplies a `decision` of `RENEWED` or `DECLINED`, moving the application from `SUBMITTED` to the corresponding terminal state.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return `201 Created`. Operations that modify an existing resource — state transitions, edits, decisions — return `200 OK`. All request and response bodies conform to the envelope of §2.2, and all list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/funders` | Create a funder | SystemAdmin |
| GET | `/funders/{id}` | Get a funder | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/grants` | Create a grant (status DRAFT); `original_end_date` snapshot taken | GrantsOfficer |
| GET | `/grants` | List grants, optional filters `funder_id`, `status` | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/grants/{id}` | Get a grant | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/grants/{id}/summary` | Computed read: BvA rows (period-only + cumulative per line), indirect pool, match progress (both variants), burn projections, pacing ratio | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/grants/{id}/activate` | Activate grant; generates the Report calendar and recomputes period budgets | ProgramDirector |
| POST | `/grants/{id}/closeout` | Move a CLOSEOUT grant to CLOSED | ProgramDirector |
| POST | `/grants/{id}/budget-lines` | Add a budget line (grant must be DRAFT) | GrantsOfficer |
| GET | `/grants/{id}/budget-lines` | List budget lines of a grant | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/budget-lines/{id}` | Get one budget line | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/budget-lines/{id}/variance-explanations` | List variance explanations recorded against this budget line across reports | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/grants/{id}/funds` | Create a fund (grant must be DRAFT) | FinanceManager |
| GET | `/grants/{id}/funds` | List funds of a grant | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/grants/{id}/expenses` | Create an expense (grant must be ACTIVE, not SUSPENDED) | GrantsOfficer |
| GET | `/grants/{id}/expenses` | List expenses of a grant, optional filter `status` | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/expenses/{id}` | Get an expense (includes `unallocated_cents`) | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/expenses/{id}/post` | Post a DRAFT expense (poster differs from creator) | FinanceManager |
| POST | `/expenses/{id}/void` | Void a POSTED expense; cascades allocations to VOIDED and reconciles totals | FinanceManager |
| POST | `/expenses/{id}/allocations` | Allocate part of a POSTED expense to a budget line and fund | GrantsOfficer |
| GET | `/allocations` | Filtered list of allocations, optional filters `expense_id`, `budget_line_id`, `fund_id` | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Auditor |
| GET | `/allocations/{id}` | Get one allocation | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Auditor |
| GET | `/grants/{id}/reports` | The reporting calendar: Report rows of a grant ordered by `period_index` ascending, optional filter `status` | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/reports/{id}` | Get a report | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| PUT | `/reports/{id}` | Edit `narrative_draft` and/or `outcome_entries` (report DRAFT, not frozen) | GrantsOfficer |
| POST | `/reports/{id}/start` | Open a SCHEDULED report for drafting (period must have started) | GrantsOfficer |
| POST | `/reports/{id}/submit` | Submit report to funder; enforces variance-explanation, outcome-data, and FINAL match gates | GrantsOfficer |
| POST | `/reports/{id}/start-review` | Funder begins review | Funder |
| POST | `/reports/{id}/accept` | Funder accepts; FINAL acceptance moves grant to CLOSEOUT | Funder |
| POST | `/reports/{id}/return` | Funder returns report for revision | Funder |
| POST | `/reports/{id}/revise` | Reopen a RETURNED report for editing | GrantsOfficer |
| POST | `/reports/{id}/variance-explanations` | Create or refresh the variance explanation for a budget line on this report | GrantsOfficer |
| GET | `/reports/{id}/variance-explanations` | List variance explanations of a report | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/grants/{id}/match-contributions` | Record a match or in-kind contribution (grant ACTIVE) | GrantsOfficer |
| GET | `/grants/{id}/match-contributions` | List match contributions of a grant, optional filter `status` | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/match-contributions/{id}/document` | Attach documentation (PLEDGED to DOCUMENTED) | GrantsOfficer |
| POST | `/match-contributions/{id}/verify` | Verify a DOCUMENTED contribution (verifier differs from documenter) | FinanceManager |
| POST | `/grants/{id}/modification-requests` | Draft a no-cost extension or budget reallocation request | GrantsOfficer |
| GET | `/grants/{id}/modification-requests` | List modification requests of a grant, optional filter `status` | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/modification-requests/{id}/submit` | Submit a draft to the funder (validates type-specific rules) | ProgramDirector |
| POST | `/modification-requests/{id}/approve` | Funder approves (OCC on grant version); applies extension or reallocation side effects | Funder |
| POST | `/modification-requests/{id}/deny` | Funder denies | Funder |
| POST | `/modification-requests/{id}/withdraw` | Withdraw a DRAFT or SUBMITTED request | GrantsOfficer |
| POST | `/grants/{id}/audit-engagements` | Schedule an audit engagement or site visit (grant ACTIVE); overlap and auditor-capacity checks | ProgramDirector |
| GET | `/grants/{id}/audit-engagements` | List engagements of a grant | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| GET | `/audit-engagements/{id}` | Get an engagement | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/audit-engagements/{id}/advance` | Advance the engagement one step along its ladder | Auditor |
| POST | `/audit-engagements/{id}/findings` | File a finding (engagement CONDUCTED or FINDINGS_ISSUED); MATERIAL_WEAKNESS suspends the grant | Auditor |
| GET | `/audit-engagements/{id}/findings` | List findings of an engagement | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/audit-findings/{id}/respond` | Grantee responds to an OPEN finding | GrantsOfficer |
| POST | `/audit-findings/{id}/resolve` | Auditor accepts the response; last MATERIAL_WEAKNESS resolution reactivates the grant | Auditor |
| POST | `/audit-findings/{id}/reopen` | Auditor rejects a response (RESPONSE_SUBMITTED back to OPEN) | Auditor |
| POST | `/grants/{id}/renewal-applications` | Create the renewal application for a grant (at most one per grant) | GrantsOfficer |
| GET | `/grants/{id}/renewal-applications` | List renewal applications of a grant (zero or one element) | SystemAdmin, GrantsOfficer, FinanceManager, ProgramDirector, Funder, Auditor |
| POST | `/renewal-applications/{id}/submit` | Submit a renewal while the window is open (status ELIGIBLE) | ProgramDirector |
| POST | `/renewal-applications/{id}/decide` | Funder decides the renewal | Funder |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock; fires time-based auto-transitions | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_GRANT_NOT_ACTIVE` | 409 |
| `ERR_GRANT_SUSPENDED` | 409 |
| `ERR_REPORT_NOT_EDITABLE` | 409 |
| `ERR_EXPENSE_NOT_POSTED` | 409 |
| `ERR_MODIFICATION_NOT_PENDING` | 409 |
| `ERR_FINDING_NOT_OPEN` | 409 |
| `ERR_EXPENSE_LOCKED_BY_REPORT` | 409 |
| `ERR_DUPLICATE_AWARD_NUMBER` | 409 |
| `ERR_ENGAGEMENT_OVERLAP` | 409 |
| `ERR_AUDITOR_CAPACITY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_REALLOCATION_NOT_BALANCED` | 422 |
| `ERR_REALLOCATION_BELOW_EXPENDED` | 422 |
| `ERR_EXTENSION_NOT_FORWARD` | 422 |
| `ERR_RESTRICTION_VIOLATION` | 422 |
| `ERR_BUDGET_LINE_EXCEEDED` | 422 |
| `ERR_FUND_EXCEEDED` | 422 |
| `ERR_EXPENSE_OVERALLOCATED` | 422 |
| `ERR_VARIANCE_EXPLANATION_REQUIRED` | 422 |
| `ERR_OUTCOME_DATA_REQUIRED` | 422 |
| `ERR_MATCH_SHORTFALL` | 422 |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 |
| `ERR_RENEWAL_WINDOW_LAPSED` | 409 |
