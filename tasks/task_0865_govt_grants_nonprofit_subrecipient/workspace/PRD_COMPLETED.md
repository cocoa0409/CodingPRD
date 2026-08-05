# Government Grants-to-Nonprofits & Subrecipient Monitoring API — Product Requirements Document

## 1. Introduction

Federal formula and discretionary funds rarely reach their intended communities directly. Instead, a pass-through agency publishes a funding opportunity, competitively selects nonprofit subrecipients, obligates money through subaward agreements, and then spends the remainder of the award period reimbursing documented expenditures while continuously monitoring each subrecipient for financial and programmatic risk. This API is the system of record for that entire pass-through relationship. It governs the opportunity's publication and intake window, the receipt and panel scoring of applications, the award decision and the fiscal obligation it creates, the reimbursement drawdown ledger, the periodic risk scoring and on-site monitoring regime, the single-audit intake mandated by federal expenditure thresholds, the corrective-action lifecycle for findings, and the eventual closeout of each subaward.

The system serves four distinct constituencies whose duties are deliberately separated: agency program staff who run competitions and control obligations, independent reviewers who score applications, post-award managers who assess risk and adjudicate reimbursements, and the nonprofit grantees themselves. Because public money is at stake, the platform treats every fiscal figure as an integer count of cents, enforces strict segregation-of-duties controls so that no single manager can both assess and pay, and maintains conservation invariants on the funding pool and on each subaward's obligation ledger so that committed and disbursed dollars can never drift from the underlying transactions that produced them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which that principal acts. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. The system recognizes exactly four roles, spelled precisely as `ProgramOfficer`, `Panelist`, `GrantsManager`, and `Subrecipient`. When a role is authenticated but not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Three of the four roles are operator identities not backed by any persisted record. When `X-User-Role` is `ProgramOfficer`, `Panelist`, or `GrantsManager`, the `X-User-ID` is an opaque operator identifier not tied to any stored entity. The server may record such an identifier — for example as `reviewer_user_id` on a `PanelReview`, as `assessed_by_user_id` on a `RiskAssessment`, as `monitor_user_id` on a `MonitoringVisit`, or as `reviewed_by_user_id` and `submitted_by_user_id` on a `Drawdown` — but it never compares that opaque identifier to any entity's `id`. These recorded identifiers nonetheless drive two integrity controls: a `Panelist`'s identifier enforces one-review-per-application uniqueness, and a `GrantsManager`'s identifier is the basis of the drawdown four-eyes rule described in §2.10.

The fourth role is entity-backed. When `X-User-Role` is `Subrecipient`, the `X-User-ID` is the `id` of the acting `Nonprofit`; ownership checks on any resource that references a `Nonprofit` compare that resource's `nonprofit_id` to the caller's `X-User-ID`. A `Subrecipient` acting on an application, subaward, drawdown, performance report, single audit, or finding whose governing `nonprofit_id` differs from its `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter counts how many items to skip and defaults to 0. Unless a subsection states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties and Field Lifecycle

Most top-level resources — `Nonprofit`, `NOFO`, `Application`, `Subaward`, `Drawdown`, `RiskAssessment`, `MonitoringVisit`, `PerformanceReport`, `SingleAudit`, and `Finding` — carry a uniform set of system-managed fields. Each has an `id` formatted as a UUID with no type prefix, a `created_at` ISO 8601 UTC timestamp with three fractional digits recorded at creation, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at 1 and increments by one on every mutation of that resource.

Two entities are deliberately lighter. A `PanelReview` and a `BudgetLine` are immutable ledger-style records: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version`. This should be reflected exactly in their response bodies.

Whenever a derived or ledger field changes — for example when a subaward's `obligated_cents` is debited by a drawdown, when a nonprofit's `cumulative_federal_expenditures_cents` is recomputed, or when a NOFO's `remaining_pool_cents` is debited by an award — that mutation refreshes the owning resource's `updated_at` and increments its `version`, even when the change was triggered indirectly by an operation on a different resource.

### 2.5. Nested Resource Retrieval and Path Validation

Many paths address a resource nested beneath a parent, such as a subaward's budget lines, drawdowns, monitoring visits, performance reports, findings, or risk assessments, and a nonprofit's single audits. For any such request the server validates path identifiers strictly left to right and rejects at the first identifier that does not resolve, returning the not-found error specific to that resource type: `ERR_NONPROFIT_NOT_FOUND`, `ERR_NOFO_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_SUBAWARD_NOT_FOUND`, `ERR_DRAWDOWN_NOT_FOUND`, `ERR_MONITORING_VISIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, or `ERR_SINGLE_AUDIT_NOT_FOUND`, each with HTTP 404. Existence of the parent is always confirmed before any state or business rule on the child is evaluated.

### 2.6. Monetary Values, Precision, and Rounding

All money is stored and returned as an integer number of cents; there are no fractional cents anywhere in the system. Where a calculation multiplies a cent amount by a rate or fraction and must be reduced back to an integer, the system rounds half up to the nearest whole cent. Two calculations pin an explicit rounding discipline that the implementer must not reorder: the per-line federal share rounds each line to the cent and only then sums the rounded line values (never sum-then-round), while the indirect cost recovery rounds a single time after the entire modified-total-direct-cost base has been multiplied by the applicable rate. Rate and fraction inputs such as `indirect_cost_cap_pct`, `negotiated_indirect_rate`, and `federal_share_pct` are dimensionless numbers between 0 and 1 inclusive and retain their supplied precision.

### 2.7. Cascading State Consistency

Several operations mutate more than one resource. The governing principle is that a parent's state change propagates deterministically to its dependent children, and every such secondary mutation independently bumps the affected child's `version` and `updated_at`. Suspending an active subaward returns its pending drawdowns; closing or terminating a subaward denies its leftover drawdowns; conducting a monitoring visit that raises a `CRITICAL` finding cascades a suspension onto the subaward, which in turn returns that subaward's pending drawdowns. Each of these cascades also reconciles the subaward's obligation ledger, crediting back amounts that are no longer obligated. The precise per-transition effects are specified in §3; the invariant here is that no cascade may be skipped and no obligation figure may be left stale after a parent transition.

### 2.8. Optimistic Concurrency Control on Drawdown Creation

Creating a reimbursement drawdown against a subaward is guarded by optimistic concurrency control. The create request must carry `expected_subaward_version`, holding the client's last observed `version` of the target `Subaward`. Because every drawdown submit, approval, and return mutates the subaward's `obligated_cents` and therefore advances the subaward's `version`, a client that read a subaward, created one drawdown, and then attempts a second create while still presenting the earlier version is working from a stale view of the remaining obligation. When `expected_subaward_version` does not equal the subaward's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Drawdown creation is the only endpoint that takes a version field; no other operation accepts or checks one.

### 2.9. The Funding Pool and Obligation Conservation Invariants

The system maintains four running ledger figures that must always reconcile to the transactions beneath them. At the opportunity level, a NOFO's `remaining_pool_cents` begins equal to its `total_pool_cents` and equals that total minus the sum of `awarded_amount_cents` over the opportunity's `AWARDED` applications whose subaward has not been terminated before activation; it is debited when an application is awarded and credited back only when a not-yet-activated subaward is terminated. At the subaward level, `obligated_cents` is the sum of `reimbursable_cents` over that subaward's drawdowns in `SUBMITTED`, `APPROVED`, or `PAID`, and `disbursed_cents` is the sum of `reimbursable_cents` over drawdowns that have reached `PAID`. At the organization level, a nonprofit's `cumulative_federal_expenditures_cents` is the sum of `disbursed_cents` across all of that nonprofit's subawards, recomputed whenever any of its drawdowns reaches `PAID`, and its `latest_risk_tier` is the `risk_tier` of the most recent `RiskAssessment` across its subawards ordered by `created_at` descending, or null when no assessment exists. These figures are never edited directly; they move only as the side effects enumerated in §3.

### 2.10. Segregation of Duties and Review Uniqueness

Two four-eyes controls protect the integrity of scoring and payment. First, a `Panelist` may score a given application at most once: a second review submitted under the same reviewer identifier for the same application is rejected with `ERR_DUPLICATE_REVIEW` (HTTP 409). Second, a `GrantsManager` who authored any `RiskAssessment` on a subaward may not later approve a drawdown against that same subaward; when the approving manager's `X-User-ID` matches the `assessed_by_user_id` of any risk assessment on the subaward, the approval is rejected with `ERR_SOD_CONFLICT` (HTTP 403). Approval by a different manager who never assessed that subaward proceeds normally.

### 2.11. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`), then left-to-right existence of path resources (the `ERR_*_NOT_FOUND` family), then subrecipient ownership (`ERR_NOT_RESOURCE_OWNER`), then whether the target resource is in a legal state for the requested transition (the `ERR_INVALID_*_STATE` family together with `ERR_SUBAWARD_NOT_ACTIVE`, `ERR_INTAKE_CLOSED`, and `ERR_APPLICATION_NOT_SCORED`). Only after those structural checks do the business-specific rules apply, and among them the order is: the drawdown-approval four-eyes conflict (`ERR_SOD_CONFLICT`), duplicate panel review (`ERR_DUPLICATE_REVIEW`), the activation gates in the sequence budget-lines-present (`ERR_NO_BUDGET_LINES`), negotiated-rate-present (`ERR_INDIRECT_RATE_REQUIRED`), then budget-balanced (`ERR_BUDGET_NOT_BALANCED`), then monitoring-visit overlap (`ERR_VISIT_OVERLAP`), then award period overlap (`ERR_PERIOD_OVERLAP`), then open-findings-at-closeout (`ERR_OPEN_FINDINGS`), then the award fiscal gates in the sequence maximum-award (`ERR_MAX_AWARD_EXCEEDED`) then remaining-pool (`ERR_POOL_EXCEEDED`), then drawdown sufficiency (`ERR_INSUFFICIENT_BUDGET`), then the drawdown stale-version check (`ERR_STALE_VERSION`). Field-shape validation of the request body — required fields present, enums valid, amounts positive, period ordering, and the negotiated-rate cap — is evaluated last, surfacing as `ERR_VALIDATION`, `ERR_INVALID_PERIOD`, `ERR_AMOUNT_NOT_POSITIVE`, or `ERR_INDIRECT_RATE_OVER_CAP`.

### 2.12. The Server Logical Clock

All datetime comparisons in the system — intake windows, period overlaps, monitoring windows, and certification-style date checks — are made against a server logical clock rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, that default is used verbatim and is never replaced by real-world time. An administrative capability lets a `ProgramOfficer` advance the clock to a supplied instant by providing a `to_iso8601` value; doing so shifts the reference time used by every subsequent datetime comparison.

## 3. Business Logic & Workflows

### 3.1. Publishing and Closing a Funding Opportunity

A `ProgramOfficer` opens the pipeline by registering subrecipient organizations and publishing opportunities. Registering a `Nonprofit` records its `legal_name`, its `uei` (the SAM.gov Unique Entity Identifier, which must be unique across all nonprofits — a `uei` that duplicates an existing nonprofit is rejected with `ERR_VALIDATION`), and its `ein`; the new organization starts with `cumulative_federal_expenditures_cents` at 0 and a null `latest_risk_tier`.

Publishing a Notice of Funding Opportunity records the opportunity's `title`, its `cfda_number` assistance-listing number, the `total_pool_cents` available to award, the `max_award_cents` ceiling on any single award, the `indirect_cost_cap_pct` capping the negotiated indirect rate any subaward under this opportunity may use, and the intake window bounded by `open_date` and `close_date`. On creation the opportunity's `remaining_pool_cents` is initialized equal to `total_pool_cents` and its `intake_status` is set to `OPEN`. Both `total_pool_cents` and `max_award_cents` must be at least 1, and `indirect_cost_cap_pct` must lie between 0 and 1 inclusive.

Intake remains receptive until a `ProgramOfficer` explicitly closes it, flipping `intake_status` to `CLOSED`. Closing intake governs only the first submission of new draft applications, as described next.

### 3.2. Application Intake, Submission, and the Revision Loop

Acting as itself, a `Subrecipient` files an `Application` under an opportunity. The submission carries the applicant's `nonprofit_id` (which must equal the caller's `X-User-ID`), the `project_title`, the `requested_amount_cents` of federal funds sought, the proposed performance period bounded by `proposed_period_start` and `proposed_period_end`, the elected `indirect_method` of either `DE_MINIMIS` or `NEGOTIATED`, and, when the method is `NEGOTIATED`, a `negotiated_indirect_rate`. The application is created in `DRAFT`. The `requested_amount_cents` must be at least 1, `proposed_period_end` must fall strictly after `proposed_period_start` (otherwise `ERR_INVALID_PERIOD`), and when a `negotiated_indirect_rate` is supplied it must not exceed the opportunity's `indirect_cost_cap_pct` (otherwise `ERR_INDIRECT_RATE_OVER_CAP`); the rate is ignored for a `DE_MINIMIS` election. The opportunity reference is captured as the application's `nofo_id`.

Submitting an application advances it from `DRAFT` to `SUBMITTED`. The acting `Subrecipient` must own the application, and the parent opportunity's `intake_status` must be `OPEN` at this first submission, or the request is rejected with `ERR_INTAKE_CLOSED`. A `ProgramOfficer` then starts review, moving the application from `SUBMITTED` to `UNDER_REVIEW`, and may send it back with an optional `revision_note`, transitioning it from `UNDER_REVIEW` to `REVISION_REQUESTED`. From `REVISION_REQUESTED` the owning `Subrecipient` resubmits, returning it to `SUBMITTED`; this resubmission of an already-existing application does not re-check `intake_status`, so a revision loop may complete even after intake has closed. Across the revision cycle any panel reviews already attached are retained and `review_count` is left unchanged. Any submit attempted from a state other than `DRAFT` or `REVISION_REQUESTED` is rejected with `ERR_INVALID_APPLICATION_STATE`.

### 3.3. Panel Review and Automatic Scoring

While an application sits in `UNDER_REVIEW`, independent panelists score it; a review submitted against an application in any other state is rejected with `ERR_INVALID_APPLICATION_STATE`. A `Panelist` submits a review carrying an integer `score` between 0 and 100 inclusive and optional `comments`; the review records the reviewer's identifier as `reviewer_user_id` and references the application through its `application_id`. Each stored review increments the application's `review_count` and recomputes its `average_score`, which is the mean of the attached reviews' `score` values rounded half up to two decimals and is null while `review_count` is 0. A panelist who has already reviewed a given application cannot review it again; the duplicate is rejected with `ERR_DUPLICATE_REVIEW`.

Scoring completes automatically. When the review just stored brings `review_count` to three, the application transitions from `UNDER_REVIEW` to `SCORED` as a side effect of that third review, with `average_score` recomputed to reflect all three. This threshold of three reviews is the fixed panel quorum.

### 3.4. Award, Rejection, and Subaward Creation

Once an application is `SCORED`, a `ProgramOfficer` renders the decision. Rejecting a scored application, optionally recording a `reason`, moves it from `SCORED` to `REJECTED`. Awarding it moves it from `SCORED` to `AWARDED`; an award or rejection attempted on an application not in `SCORED` is rejected with `ERR_APPLICATION_NOT_SCORED`.

The award decision passes three business gates in order. First, the applicant nonprofit must not already hold another non-terminal subaward (any subaward not in `CLOSED` or `TERMINATED`) under the same opportunity whose performance period overlaps the proposed period; overlap is measured as a closed interval widened by a thirty-day gap on each side, so two periods that come within thirty days of touching are treated as overlapping and the award is rejected with `ERR_PERIOD_OVERLAP`. Next, the `requested_amount_cents` must not exceed the opportunity's `max_award_cents`, or the award is rejected with `ERR_MAX_AWARD_EXCEEDED`. Finally, the `requested_amount_cents` must not exceed the opportunity's `remaining_pool_cents`, or the award is rejected with `ERR_POOL_EXCEEDED`.

On a successful award the system sets the application's `awarded_amount_cents` equal to its `requested_amount_cents`, debits the opportunity's `remaining_pool_cents` by that same amount, and creates a `Subaward` in `DRAFT`. The new subaward copies forward the `application_id`, the `nonprofit_id`, and the `nofo_id`, sets its `period_start` and `period_end` from the application's proposed period, sets `total_budget_cents` equal to the awarded `requested_amount_cents`, and copies the `indirect_method` and `negotiated_indirect_rate`. Its ledger figures `indirect_cost_cents`, `federal_share_cents`, `obligated_cents`, and `disbursed_cents` all begin at 0. The award operation returns the updated `Application` in its `data`; the newly created `Subaward` is retrieved separately through the subaward endpoints.

### 3.5. Building the Budget and Activating the Subaward

Before a subaward can operate it must carry a balanced budget. A `ProgramOfficer` adds one or more `BudgetLine` records to a `DRAFT` subaward; each line references its `subaward_id` and records a `category` drawn from `PERSONNEL`, `FRINGE`, `TRAVEL`, `SUPPLIES`, `EQUIPMENT`, `CONTRACTUAL`, or `OTHER`, an `amount_cents` of at least 1, a `federal_share_pct` between 0 and 1 inclusive giving the fraction of the line borne by federal funds, and an optional `description`.

Activation moves the subaward from `DRAFT` to `ACTIVE` and is gated in three steps. At least one budget line must exist, or activation fails with `ERR_NO_BUDGET_LINES`. If the `indirect_method` is `NEGOTIATED`, a `negotiated_indirect_rate` must be present, or activation fails with `ERR_INDIRECT_RATE_REQUIRED`. Finally the budget must balance exactly: the sum of every line's `amount_cents` plus the computed indirect recovery must equal `total_budget_cents` to the cent, and any nonzero variance — even a single cent — fails with `ERR_BUDGET_NOT_BALANCED`.

On successful activation the system computes and stores two figures. The `indirect_cost_cents` is derived from a modified-total-direct-cost base: iterate the budget lines, excluding any `EQUIPMENT` line from the base entirely, counting each `CONTRACTUAL` line only up to the first 25,000 dollars — that is, the smaller of the line's `amount_cents` and 2,500,000 cents — and counting every other line at its full `amount_cents`. Multiply that base by the applicable rate — a fixed 0.10 when the `indirect_method` is `DE_MINIMIS`, regardless of any stored `negotiated_indirect_rate`, or the subaward's `negotiated_indirect_rate` when the method is `NEGOTIATED` — and round the single product half up to whole cents. Identical budget lines therefore yield a different `indirect_cost_cents` under the two methods. The `federal_share_cents` is computed by taking each budget line in `created_at` ascending order, multiplying its `amount_cents` by its `federal_share_pct`, rounding that line's product half up to the cent, and summing those already-rounded per-line values; the indirect recovery is not a budget line and contributes no federal share.

### 3.6. Reimbursement Drawdowns

Against an `ACTIVE` subaward, the owning `Subrecipient` submits reimbursement drawdowns. A submission carries the `requested_amount_cents` sought, the expenditure window bounded by `period_covered_start` and `period_covered_end` (with the end strictly after the start), and the `expected_subaward_version` required by the concurrency control in §2.8. The subaward it references is captured as `subaward_id`, and the submitting nonprofit is recorded as `submitted_by_user_id`. A drawdown created against a subaward that is not `ACTIVE` is rejected with `ERR_SUBAWARD_NOT_ACTIVE`. The drawdown enters `SUBMITTED`.

At submission the system measures the subaward's available headroom as its `total_budget_cents` minus its `obligated_cents` as they stand immediately before this drawdown contributes anything. If `requested_amount_cents` exceeds that available headroom the submission is rejected with `ERR_INSUFFICIENT_BUDGET`. Otherwise the provisional reimbursable amount, `provisional_reimbursable_cents`, is set to the smaller of `requested_amount_cents` and that available headroom, the drawdown's `reimbursable_cents` is set equal to it, the subaward's `obligated_cents` is debited by that amount, and the subaward's `version` is incremented by one.

A `GrantsManager` who did not assess the subaward adjudicates the submission. Approving it moves the drawdown from `SUBMITTED` to `APPROVED`: the manager may supply a `disallowed_amount_cents` for expenditures whose documentation is unsupported (defaulting to 0), and the final reimbursable amount, `final_reimbursable_cents`, is set to the smaller of `requested_amount_cents` minus `disallowed_amount_cents` and the same available headroom that was measured at submission. The drawdown's `reimbursable_cents` becomes this final value, the subaward's `obligated_cents` is adjusted by the difference between the final and the earlier provisional amount, and the manager's identifier is recorded as `reviewed_by_user_id`. The final amount diverges from the provisional one exactly when `disallowed_amount_cents` is greater than 0. Returning a submitted drawdown instead moves it from `SUBMITTED` to `RETURNED`, optionally recording a `reason`: its `reimbursable_cents` is set to 0, the subaward's `obligated_cents` is credited back by the prior `provisional_reimbursable_cents`, and the reviewing manager is recorded as `reviewed_by_user_id`.

A returned drawdown can be revised and resubmitted by the owning `Subrecipient`, moving it from `RETURNED` back to `SUBMITTED`, provided the subaward is still `ACTIVE` (otherwise `ERR_SUBAWARD_NOT_ACTIVE`). Resubmission is subject to the same sufficiency check as an original submission — if `requested_amount_cents` exceeds the subaward's current available headroom the resubmission is rejected with `ERR_INSUFFICIENT_BUDGET` — and otherwise recomputes `provisional_reimbursable_cents` against that current headroom, sets `reimbursable_cents` to the provisional amount, and re-debits the subaward's `obligated_cents`. A `ProgramOfficer` disburses an approved drawdown by paying it, moving it from `APPROVED` to `PAID`, which adds its `reimbursable_cents` to the subaward's `disbursed_cents` and recomputes the nonprofit's `cumulative_federal_expenditures_cents`. Any drawdown transition attempted from an illegal state is rejected with `ERR_INVALID_DRAWDOWN_STATE`. A drawdown may also reach `RETURNED` or `DENIED` as a cascade from a subaward transition, as detailed in §3.9.

### 3.7. Post-Award Risk Assessment

A `GrantsManager` runs a risk assessment on a subaward, producing a `RiskAssessment` that records the assessing manager as `assessed_by_user_id` and stores four component scores that sum into an overall `risk_score` and a banded `risk_tier`. Running the assessment also refreshes the nonprofit's `latest_risk_tier`.

The `findings_component` counts the nonprofit's open findings — those findings on any of its subawards whose `status` is `OPEN`, `CAP_SUBMITTED`, or `CAP_ACCEPTED`, i.e. not yet `RESOLVED` — multiplies that count by 15, and caps the result at 45. The `audit_component` reflects single-audit posture using the nonprofit's latest single audit, selected as the one with the greatest `fiscal_year` and, on a tie, the most recent `created_at`. When there is no single audit on file and the nonprofit's `cumulative_federal_expenditures_cents` is at least 750,000 dollars (75,000,000 cents), the component is 30, reflecting a delinquent required-but-missing audit; when there is no single audit on file and expenditures fall below that threshold, it is 10; when the latest audit is `ACCEPTED` and its `reported_finding_count` is greater than 0, it is 20; when the latest audit is `ACCEPTED` with no reported findings, it is 0; and when the latest audit is still `SUBMITTED` and not yet accepted, it is 15. The `velocity_component` reflects this subaward's disbursement pace as the ratio of its `disbursed_cents` to its `total_budget_cents`: the component is 20 when that ratio exceeds 0.90, 10 when it is at least 0.50 but not above 0.90, and 0 otherwise. The `size_component` is 10 when the subaward's `total_budget_cents` is at least 500,000 dollars (50,000,000 cents) and 5 otherwise.

The `risk_score` is the sum of the four components capped at 100. The `risk_tier` is `HIGH` when the score is at least 60, `MODERATE` when it is at least 30 but below 60, and `LOW` below 30.

### 3.8. Monitoring, Single Audits, Performance, and Findings

A `GrantsManager` schedules a monitoring visit on a subaward, supplying the window bounded by `scheduled_start` and `scheduled_end` (with the end strictly after the start); the visit records the scheduling manager as `monitor_user_id` and begins in `SCHEDULED`. The system rejects a window that overlaps another visit already scheduled by the same monitor, treating each window as half-open over its start up to but not including its end, so two windows that merely touch at an endpoint are allowed but any interior overlap is rejected with `ERR_VISIT_OVERLAP`. Conducting a visit moves it from `SCHEDULED` to `CONDUCTED` and is permitted only while the subaward is `ACTIVE` or `SUSPENDED`; conducting while the subaward is in any other state is rejected with `ERR_INVALID_SUBAWARD_STATE`. Conducting records an `outcome` of `SATISFACTORY` or `DEFICIENT` and, when a `finding_severity` of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL` is supplied, raises a `Finding` in `OPEN` whose `source_kind` is `MONITORING`, whose `origin_ref_id` points back to this visit, and whose `severity` equals the supplied value; omitting `finding_severity` raises no finding. When the raised finding's `severity` is `CRITICAL`, the system cascades a suspension onto the subaward, transitioning it from `ACTIVE` to `SUSPENDED`, which in turn returns that subaward's pending drawdowns. Conducting a visit not in `SCHEDULED` is rejected with `ERR_INVALID_VISIT_STATE`. The conduct operation returns the updated `MonitoringVisit`; any `Finding` it raises is a side effect retrieved separately.

Separately, a `Subrecipient` submits a `SingleAudit` for its own organization, recording the audited `fiscal_year`, the `total_federal_expenditures_cents` expended that year (at least 0), a `material_weakness` flag (default false), and a `reported_finding_count` (default 0); the audit begins in `SUBMITTED`. On submission the system computes `audit_required`, which is true exactly when `total_federal_expenditures_cents` is at least 750,000 dollars (75,000,000 cents): expenditures of exactly 75,000,000 cents require an audit, while 74,999,999 cents do not. A `GrantsManager` accepts a submitted audit, moving it from `SUBMITTED` to `ACCEPTED`. When the accepted audit's `material_weakness` is true, acceptance raises a `Finding` in `OPEN` whose `source_kind` is `SINGLE_AUDIT`, whose `origin_ref_id` points to this audit, and whose `severity` is `HIGH`, charged against a single selected subaward. The eligible subawards are those whose `nonprofit_id` matches the audited organization and whose `status` is `ACTIVE`; among them the system selects the earliest by `created_at`, breaking ties by `created_at` and then by insertion order. If no subaward of the nonprofit is `ACTIVE`, the audit is still accepted but no finding is created. Accepting an audit not in `SUBMITTED` is rejected with `ERR_INVALID_AUDIT_STATE`.

A `Subrecipient` also files performance reports on its subawards. A `PerformanceReport` records the reporting window bounded by `reporting_period_start` and `reporting_period_end` (with the end strictly after the start), the planned `metric_target`, the achieved `metric_actual`, and an optional `outcome_narrative`. The report's computed `on_track` flag is true exactly when `metric_actual` is greater than or equal to `metric_target`.

Every finding then runs a corrective-action lifecycle. The finding carries a system-generated `description`. The owning `Subrecipient` submits a corrective action plan, moving the finding from `OPEN` to `CAP_SUBMITTED` and storing the supplied `corrective_action_plan` narrative together with an optional `cap_due_date`. A `GrantsManager` either accepts the plan, moving it from `CAP_SUBMITTED` to `CAP_ACCEPTED`, or rejects it with an optional `reason`, moving it from `CAP_SUBMITTED` back to `OPEN` and clearing the stored `corrective_action_plan`. From `CAP_ACCEPTED` the manager resolves the finding, moving it to `RESOLVED`. A finding transition attempted from an illegal state is rejected with `ERR_INVALID_FINDING_STATE`.

### 3.9. Suspension, Reinstatement, Closeout, and Termination

Beyond the cascade path, a `GrantsManager` may directly suspend an `ACTIVE` subaward, optionally recording a `reason`, moving it from `ACTIVE` to `SUSPENDED`. Suspension — whether requested directly or cascaded from a `CRITICAL` finding — transitions each of the subaward's drawdowns that is currently `SUBMITTED` to `RETURNED`, crediting the subaward's `obligated_cents` back by each returned drawdown's prior provisional amount. A suspended subaward can be reinstated by a `GrantsManager`, moving it from `SUSPENDED` back to `ACTIVE`. Any subaward transition attempted from an illegal state is rejected with `ERR_INVALID_SUBAWARD_STATE`.

A `ProgramOfficer` drives closeout. Initiating closeout moves an `ACTIVE` subaward to `CLOSEOUT_PENDING`. Closing it from `CLOSEOUT_PENDING` to `CLOSED` requires that every `Finding` on the subaward be `RESOLVED`, or the close is rejected with `ERR_OPEN_FINDINGS`; on a successful close, each drawdown still in `SUBMITTED` or `RETURNED` transitions to `DENIED`, crediting the subaward's `obligated_cents` back for any amount still provisionally obligated.

Termination is the disposal path and behaves differently depending on the subaward's stage. Terminating a `DRAFT` subaward — one that was awarded but never activated — moves it to `TERMINATED` and credits the opportunity's `remaining_pool_cents` back by the application's `awarded_amount_cents`, reversing the award debit under the pool-conservation invariant. Terminating an already-active or suspended subaward moves it to `TERMINATED` without returning anything to the pool, because the obligation has already been recognized; in that case each drawdown still in `SUBMITTED` or `RETURNED` transitions to `DENIED`. In all denial cascades, a drawdown that was `SUBMITTED` has its `reimbursable_cents` set to 0 with the subaward's `obligated_cents` credited back by its prior provisional amount, while a drawdown already `RETURNED` carries no residual obligation to reverse.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new record to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions and the administrative clock control — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | ProgramOfficer |
| POST | `/nonprofits` | Register a subrecipient organization | ProgramOfficer |
| GET | `/nonprofits/{id}` | Fetch a nonprofit | ProgramOfficer, GrantsManager, Subrecipient, Panelist |
| GET | `/nonprofits/{id}/single-audits` | List a nonprofit's single audits | ProgramOfficer, GrantsManager, Subrecipient |
| POST | `/nofos` | Create a Notice of Funding Opportunity | ProgramOfficer |
| GET | `/nofos/{id}` | Fetch a NOFO | ProgramOfficer, GrantsManager, Subrecipient, Panelist |
| POST | `/nofos/{id}/close-intake` | Close application intake for a NOFO | ProgramOfficer |
| POST | `/nofos/{id}/applications` | File an application under a NOFO | Subrecipient |
| GET | `/applications` | List applications; filter by nofo_id, nonprofit_id, status | ProgramOfficer, GrantsManager, Subrecipient, Panelist |
| GET | `/applications/{id}` | Fetch an application | ProgramOfficer, GrantsManager, Subrecipient, Panelist |
| POST | `/applications/{id}/submit` | Submit or resubmit an application | Subrecipient |
| POST | `/applications/{id}/start-review` | Move a submitted application into review | ProgramOfficer |
| POST | `/applications/{id}/request-revision` | Send an application back for revision | ProgramOfficer |
| POST | `/applications/{id}/award` | Award a scored application; create the subaward | ProgramOfficer |
| POST | `/applications/{id}/reject` | Reject a scored application | ProgramOfficer |
| POST | `/applications/{id}/reviews` | Submit a panel review score | Panelist |
| GET | `/applications/{id}/reviews` | List an application's panel reviews | ProgramOfficer, Panelist |
| GET | `/subawards/{id}` | Fetch a subaward | ProgramOfficer, GrantsManager, Subrecipient, Panelist |
| GET | `/subawards` | List subawards; filter by application_id, nonprofit_id, nofo_id, status | ProgramOfficer, GrantsManager, Subrecipient, Panelist |
| POST | `/subawards/{id}/budget-lines` | Add a budget line to a DRAFT subaward | ProgramOfficer |
| GET | `/subawards/{id}/budget-lines` | List a subaward's budget lines | ProgramOfficer, GrantsManager, Subrecipient |
| POST | `/subawards/{id}/activate` | Activate a subaward | ProgramOfficer |
| POST | `/subawards/{id}/suspend` | Suspend an active subaward | GrantsManager |
| POST | `/subawards/{id}/reinstate` | Reinstate a suspended subaward | GrantsManager |
| POST | `/subawards/{id}/terminate` | Terminate a subaward | ProgramOfficer |
| POST | `/subawards/{id}/initiate-closeout` | Begin closeout | ProgramOfficer |
| POST | `/subawards/{id}/close` | Close a subaward | ProgramOfficer |
| POST | `/subawards/{id}/drawdowns` | Submit a reimbursement drawdown | Subrecipient |
| GET | `/subawards/{id}/drawdowns` | List a subaward's drawdowns; filter by status | ProgramOfficer, GrantsManager, Subrecipient |
| GET | `/drawdowns/{id}` | Fetch a drawdown | ProgramOfficer, GrantsManager, Subrecipient |
| POST | `/drawdowns/{id}/approve` | Approve a drawdown | GrantsManager |
| POST | `/drawdowns/{id}/return` | Return a drawdown for more documentation | GrantsManager |
| POST | `/drawdowns/{id}/resubmit` | Resubmit a returned drawdown | Subrecipient |
| POST | `/drawdowns/{id}/pay` | Disburse an approved drawdown | ProgramOfficer |
| POST | `/subawards/{id}/risk-assessments` | Run a risk assessment on a subaward | GrantsManager |
| GET | `/subawards/{id}/risk-assessments` | List a subaward's risk assessments | ProgramOfficer, GrantsManager |
| POST | `/subawards/{id}/monitoring-visits` | Schedule a monitoring visit | GrantsManager |
| POST | `/monitoring-visits/{id}/conduct` | Conduct a scheduled visit | GrantsManager |
| GET | `/subawards/{id}/monitoring-visits` | List a subaward's monitoring visits; filter by status | ProgramOfficer, GrantsManager, Subrecipient |
| POST | `/subawards/{id}/performance-reports` | Submit a performance report | Subrecipient |
| GET | `/subawards/{id}/performance-reports` | List a subaward's performance reports | ProgramOfficer, GrantsManager, Subrecipient |
| POST | `/nonprofits/{id}/single-audits` | Submit a single audit | Subrecipient |
| POST | `/single-audits/{id}/accept` | Accept a submitted single audit | GrantsManager |
| GET | `/subawards/{id}/findings` | List a subaward's findings; filter by status | ProgramOfficer, GrantsManager, Subrecipient |
| POST | `/findings/{id}/submit-cap` | Submit a corrective action plan | Subrecipient |
| POST | `/findings/{id}/accept-cap` | Accept a corrective action plan | GrantsManager |
| POST | `/findings/{id}/reject-cap` | Reject a corrective action plan | GrantsManager |
| POST | `/findings/{id}/resolve` | Resolve a finding | GrantsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SOD_CONFLICT` | 403 |
| `ERR_NONPROFIT_NOT_FOUND` | 404 |
| `ERR_NOFO_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_SUBAWARD_NOT_FOUND` | 404 |
| `ERR_DRAWDOWN_NOT_FOUND` | 404 |
| `ERR_MONITORING_VISIT_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_SINGLE_AUDIT_NOT_FOUND` | 404 |
| `ERR_INTAKE_CLOSED` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_APPLICATION_NOT_SCORED` | 409 |
| `ERR_DUPLICATE_REVIEW` | 409 |
| `ERR_INVALID_SUBAWARD_STATE` | 409 |
| `ERR_SUBAWARD_NOT_ACTIVE` | 409 |
| `ERR_NO_BUDGET_LINES` | 409 |
| `ERR_INDIRECT_RATE_REQUIRED` | 409 |
| `ERR_BUDGET_NOT_BALANCED` | 409 |
| `ERR_VISIT_OVERLAP` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_OPEN_FINDINGS` | 409 |
| `ERR_MAX_AWARD_EXCEEDED` | 409 |
| `ERR_POOL_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_BUDGET` | 409 |
| `ERR_INVALID_DRAWDOWN_STATE` | 409 |
| `ERR_INVALID_FINDING_STATE` | 409 |
| `ERR_INVALID_VISIT_STATE` | 409 |
| `ERR_INVALID_AUDIT_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_AMOUNT_NOT_POSITIVE` | 422 |
| `ERR_INDIRECT_RATE_OVER_CAP` | 422 |
