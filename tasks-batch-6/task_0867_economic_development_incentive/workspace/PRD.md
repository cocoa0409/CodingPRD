# Economic-Development Incentive & Abatement API — Product Requirements Document

## 1. Introduction

Municipal and county economic-development offices award public money to private projects through a small set of well-understood instruments — tax-increment financing (TIF), property-tax abatement, and cash grants — each attached to binding promises about jobs created and capital invested. The recurring failure of these programs is not the award decision itself but everything that happens afterward: budgets that quietly over-commit, disbursements that outrun their statutory caps, clawback covenants that are never measured, and recapture math that no two analysts compute the same way. This document specifies a REST API that makes the full lifecycle auditable end to end, from a company's first application through eligibility review, agreement execution, annual compliance reporting, period disbursement, default, recapture, and public transparency reporting.

The system is built around segregation of duties: the analyst who authors an eligibility finding may not be the director who approves the deal, the officer who pays money is distinct from the director who governs the agreement, and every material state change is recorded against an immutable ledger. Two conserved quantities anchor the design — a program's appropriated budget is always partitioned into exactly three buckets (available, committed, and disbursed), and an agreement's gross disbursement total is always reconstructable from its current net plus whatever has been clawed back. Every calculation in the platform is expressed in whole cents or in a bounded eligibility score, and every rounding decision is pinned so that an independent auditor reproducing the numbers arrives at the same figure to the cent.

Readers should treat §2 as the binding contract for cross-cutting behavior (authentication, envelopes, pagination, precision, concurrency, and the two ledger invariants) and §3 as the authoritative narrative for each business workflow. §4 and §5 summarize the HTTP surface and the error catalogue but deliberately omit trigger conditions, which live in the prose.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are present but the role is not permitted to perform the requested operation under the matrix below, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled precisely as follows: `Applicant`, `ProgramAnalyst`, `ProgramDirector`, `ComplianceOfficer`, and `PublicViewer`.

- An `Applicant` is an incentive seeker and recipient. They create applications, submit them, file and resubmit compliance reports, and dispute recapture assessments.
- A `ProgramAnalyst` reviews applications and compliance reports, authoring eligibility findings and accepting or returning reports.
- A `ProgramDirector` configures programs and parcels, approves or denies applications, executes and activates agreements, attaches covenants, declares default, and waives covenants and assessments.
- A `ComplianceOfficer` calculates, approves, and pays disbursements, finalizes recapture assessments, and publishes transparency disclosures.
- A `PublicViewer` is a read-only transparency consumer limited to programs, published disclosures, and the portfolio dashboard.

For all five roles, `X-User-ID` is an **opaque** operator identifier that is not tied to any persisted entity's `id`. The server records it where a workflow demands provenance — for example, as the `applicant_user_id` captured when an application is created, as the `reviewer_user_id` pinned on an eligibility review, or as the `certified_by` field stamped when a report is attested — but it never compares `X-User-ID` to any row's `id`. Ownership checks (for instance, that only the applicant who owns an application may submit it, or that only the applicant who owns an agreement's originating application may resubmit a report or dispute an assessment) compare `X-User-ID` against the recorded owner identifier, not against a primary key.

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

### 2.3. Pagination and Filtering

List endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0 and must be at least 0. Results are always returned sorted by `created_at` in ascending order, so the oldest matching record appears first. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filter across all pages), and `has_more` (true when records remain beyond the current page).

Beyond pagination, list endpoints accept resource-specific filters that narrow the result set: programs may be filtered by `incentive_type`; applications by `program_id`, `applicant_user_id`, and `status`; eligibility reviews by `application_id`; agreements by `program_id`, `application_id`, `parcel_id`, and `status`; covenants by `agreement_id`, `covenant_type`, and `status`; compliance reports by `agreement_id` and `status`; disbursements by `agreement_id`, `compliance_report_id`, and `status`; recapture assessments by `agreement_id` and `status`; and disclosures by `agreement_id` and `status`. The portfolio dashboard accepts an optional `program_id` scope.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Most resources additionally carry an `updated_at` timestamp (refreshed on every mutation) and an integer `version` that starts at 1 and increments by one on each mutation. One entity is an exception: an eligibility review is an append-only, immutable determination record — it carries only `id` and `created_at`, and has neither `updated_at` nor `version`.

Nested paths are validated left to right. When a request addresses a resource through a parent segment — for example, attaching a covenant or a compliance report under an agreement, or publishing a disclosure under an agreement — the parent id is resolved first, and if it does not exist the request fails with that parent's not-found error before the child is considered. Each resource type has its own 404 identifier: an unknown program yields `ERR_PROGRAM_NOT_FOUND`, an unknown parcel `ERR_PARCEL_NOT_FOUND`, an unknown application `ERR_APPLICATION_NOT_FOUND`, an unknown eligibility review `ERR_ELIGIBILITY_REVIEW_NOT_FOUND`, an unknown agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown covenant `ERR_COVENANT_NOT_FOUND`, an unknown compliance report `ERR_COMPLIANCE_REPORT_NOT_FOUND`, an unknown disbursement `ERR_DISBURSEMENT_NOT_FOUND`, an unknown recapture assessment `ERR_RECAPTURE_ASSESSMENT_NOT_FOUND`, and an unknown disclosure `ERR_DISCLOSURE_NOT_FOUND`.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Every rounding step in the platform uses **round half up** (a value exactly at the halfway point rounds away from zero). Percent-based and score computations round to their stated number of decimal places: the eligibility score and covenant attainment percentage are rounded to two decimal places, while all cent-valued calculations round to whole cents. Where a formula sums several rounded components, the rounding order is significant and is pinned explicitly in §3; implementers must not substitute a sum-then-round shortcut where a round-then-sum order is specified, because the two can differ by cents.

### 2.6. The Program Budget Partition

Each incentive program owns an appropriated funding pool, `total_budget_cents`, which is a conserved quantity: it never changes after the program is created, and at every instant it equals the sum of three computed buckets — `available_budget_cents`, `committed_cents`, and `disbursed_cents`. At program creation, `committed_cents` and `disbursed_cents` are both 0 and `available_budget_cents` equals `total_budget_cents`.

The three buckets move in lockstep as the lifecycle progresses, always preserving the partition:

- When an agreement is executed, its award cap is moved from available into committed: `committed_cents` increases by the agreement's `max_incentive_cents` and `available_budget_cents` decreases by the same amount.
- When a disbursement is paid, that money moves from committed into disbursed: `committed_cents` decreases by the paid amount and `disbursed_cents` increases by the same amount.
- When a paid disbursement is clawed back during recapture, the money moves from disbursed back into available: `disbursed_cents` decreases by the clawed-back amount and `available_budget_cents` increases by the same amount.
- When an agreement reaches `COMPLETED` or `CLOSED`, any remaining reservation is released: `committed_cents` decreases by the agreement's `max_incentive_cents` and `available_budget_cents` increases by the same amount.

The program's `available_budget_cents` is therefore always derivable as `total_budget_cents` minus `committed_cents` minus `disbursed_cents`.

### 2.7. The Agreement Disbursement Ledger

Each agreement maintains three cent ledgers that together form a second conserved quantity. `gross_disbursed_cents` is monotonic — it is the running total of every amount ever paid against the agreement and never decreases. `clawed_back_cents` accumulates the amounts of disbursements that reached `CLAWED_BACK`. `net_disbursed_cents` is the current cash out the door and always equals `gross_disbursed_cents` minus `clawed_back_cents`. Paying a disbursement adds its amount to both gross and net; clawing a disbursement back subtracts its amount from net and adds it to clawed-back while leaving gross untouched. All three default to 0 on a freshly executed agreement.

### 2.8. Optimistic Concurrency on Agreements

Creating a disbursement is guarded by optimistic concurrency control anchored on the agreement's integer `version`. A create-disbursement request must include `expected_agreement_version` as a required field carrying the client's last observed `version` of the target agreement. If that value does not equal the agreement's current `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). This matters because a disbursement's entitlement is computed against the agreement's current cumulative disbursed ledger; if another writer has already created a disbursement for the agreement and thereby advanced its `version`, the current client's view is stale and the create is refused so it cannot double-count against an outdated cumulative balance. No other endpoint accepts or requires a version field.

The agreement `version` advances on each of the following mutations: activation, covenant attachment, declaring default, creating a disbursement, and paying a disbursement. Clients that intend to create a disbursement should therefore re-read the agreement immediately beforehand to capture a fresh `version`.

### 2.9. Cascading State Propagation

Several operations mutate more than one entity in a single call. Whenever any entity is mutated, its `updated_at` is refreshed and — for entities that carry one — its `version` is incremented. Two named cascades recur throughout §3. The first (default cascade) fires when a director declares default: every currently `ACTIVE` covenant on the agreement is driven to `BREACHED`, and the resulting set of unmet covenants gives rise to a single recapture assessment. The second (compliance cascade) fires when a report is accepted: each governing covenant's attainment is recomputed and covenants advance to `MET` or `BREACHED`, and if that leaves every covenant on the agreement in `MET` or `WAIVED`, the agreement itself bubbles from `ACTIVE` to `COMPLETED`. Recapture finalization drives a third cascade, clawing back every paid disbursement and closing the agreement. Each cascade's monetary side effects are applied bucket by bucket exactly as described in §2.6 and §2.7.

### 2.10. Validation Order and the Logical Clock

When several checks could reject one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first (missing headers yield `ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then existence of every path resource left to right (`ERR_..._NOT_FOUND`), then request-body well-formedness (`ERR_VALIDATION`), then the legality of the requested state transition (`ERR_..._INVALID_STATE`), then the optimistic-concurrency check on the agreement version (`ERR_STALE_AGREEMENT_VERSION`), then the four-eyes segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`), then cross-entity referential preconditions on linked resources, then remaining domain constraints, then interval-overlap checks, and finally fiscal-capacity checks. In other words, a malformed body is reported before an illegal transition, an illegal transition is reported before a stale version, and a budget shortfall is only reported once every structural check has passed.

Body well-formedness (priority 4) requires that all required fields are present, every enum value is in range, integer amounts are non-negative, a covenant's `measurement_end_date` is greater than or equal to its `measurement_start_date`, a report's `period_end_date` is strictly greater than its `period_start_date`, and any `term_years` is at least 1. Any breach of these yields `ERR_VALIDATION` (HTTP 422).

Time in this system is a logical clock rather than wall-clock time. An administrative capability lets a `ProgramDirector` or `ComplianceOfficer` set the current UTC instant by supplying a `to_iso8601` value; the server's startup default is `2026-05-01T00:00:00Z`, which precedes every default fixture date, and the clock never falls back to wall-clock time. Effective dates, cure-window comparisons, and any other temporal evaluation read this logical clock.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program and Registering Parcels

A `ProgramDirector` bootstraps the system by creating an incentive program, which is at once a funding pool and a rate-configuration record. The creation payload supplies a `program_name`, an `incentive_type` — one of `TIF`, `ABATEMENT`, or `GRANT`, which permanently fixes which award and disbursement formulas apply — and the appropriated `total_budget_cents`. It also carries the eligibility and covenant floors used later in the lifecycle: `min_jobs_required` and `min_investment_cents` (the minimum a jobs covenant or an investment covenant may respectively target), `max_term_years` (the ceiling on any agreement's term), and the three rate knobs `abatement_rate_pct` (percent of assessed value abated per year), `grant_per_job_cents` (grant dollars in cents per committed job), and `tif_capture_pct` (percent of the assessed-value increment captured per year). Two optional knobs round out the configuration: `but_for_pass_threshold`, the minimum eligibility score for a passing review, which defaults to 60 when omitted; and `disclosure_threshold_cents`, the award size at or above which a transparency disclosure is expected, which defaults to 0. On creation the program's `committed_cents` and `disbursed_cents` are 0 and its `available_budget_cents` equals `total_budget_cents`.

Parcels are the tax-basis anchors for abatement and TIF math. A director registers a parcel with a `parcel_identifier` (the assessor parcel number), a `jurisdiction`, a `base_assessed_value_cents` (the frozen base-year value from which a TIF increment is measured), and a `current_assessed_value_cents` (the present value, which drives both abatement and TIF calculations). Programs and parcels are peer records; agreements later reference both by their identifiers.

### 3.2. Application Intake, Eligibility Scoring, and the Four-Eyes Review

An `Applicant` opens the pipeline by creating an application in `DRAFT`. The payload names the target program through a `program_id`, records the owning `applicant_user_id` and the legal `applicant_name`, and states the project's `proposed_jobs` and `proposed_investment_cents`. Two optional booleans capture the policy hooks: `but_for_attested` (the applicant's attestation that the project would not proceed but for the incentive, defaulting to false) and `distress_zone` (whether the site sits in a designated economically-distressed zone, defaulting to false).

When the owning applicant submits the application, it advances `DRAFT → SUBMITTED`, and only the applicant whose identifier matches the recorded `applicant_user_id` may do so. Submission computes and stores the application's `but_for_eligibility_score`, a weighted figure on a 100-point scale. The jobs component is thirty times the ratio of `proposed_jobs` to the program's `min_jobs_required`, capped at 30. The investment component is thirty times the ratio of `proposed_investment_cents` to the program's `min_investment_cents`, likewise capped at 30. A but-for bonus of 25 is added when `but_for_attested` is true, and a distress bonus of 15 is added when `distress_zone` is true. The four terms are summed and the total is rounded half up to two decimal places to give `but_for_eligibility_score`.

A `ProgramAnalyst` begins the review, advancing the application `SUBMITTED → UNDER_REVIEW`. This action creates exactly one eligibility review as an immutable record: its `eligibility_score` is a snapshot of the application's `but_for_eligibility_score` at review time, its `reviewer_user_id` is pinned to the analyst's identifier, and its optional `notes` carry the analyst's narrative (defaulting to an empty string). The review's `finding` is set to `PASS` when the snapshot score is greater than or equal to the program's `but_for_pass_threshold`, and to `FAIL` otherwise — the boundary is inclusive.

A `ProgramDirector` then either approves or denies. Approval advances `UNDER_REVIEW → APPROVED` but is doubly guarded: the application's latest eligibility review must carry a `finding` of `PASS`, otherwise the request is rejected with `ERR_ELIGIBILITY_NOT_PASSED` (HTTP 409); and the approving director's identifier must differ from that review's `reviewer_user_id`, enforcing four-eyes segregation of duties — a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Denial advances `UNDER_REVIEW → DENIED` and may carry an optional `reason`. Both `APPROVED` and `DENIED` are terminal for the application. An attempt to submit, start review, approve, or deny from a state where that transition is not legal yields `ERR_APPLICATION_INVALID_STATE`.

### 3.3. Executing an Agreement and Computing the Award Cap

Once an application is `APPROVED`, a `ProgramDirector` executes an agreement from it. The execution payload carries the source `application_id`, the `parcel_id` anchoring the tax math, the `term_years` of the incentive, and the contractual commitment baselines `awarded_jobs` and `awarded_investment_cents`. The source application must be in `APPROVED`; otherwise the request is rejected with `ERR_APPLICATION_NOT_APPROVED` (HTTP 409). The `term_years` must be at least 1 and may not exceed the program's `max_term_years`. On success the agreement copies the `program_id` and the `incentive_type` from the source application's program, records `effective_date` as the current logical clock, and is created in status `EXECUTED`.

Execution computes the award cap `max_incentive_cents` by branching on the program's `incentive_type`:

- For a `GRANT` program, the cap is `awarded_jobs` multiplied by the program's `grant_per_job_cents`.
- For an `ABATEMENT` program, a single year's amount is the parcel's `current_assessed_value_cents` multiplied by the program's `abatement_rate_pct`, divided by 100, and that per-year amount is rounded half up to whole cents. The cap is that rounded per-year amount summed over the term — equivalently, the rounded per-year amount multiplied by `term_years`.
- For a `TIF` program, the increment is the parcel's `current_assessed_value_cents` minus its `base_assessed_value_cents`, floored at zero (never negative). A single year's amount is that increment multiplied by the program's `tif_capture_pct`, divided by 100, and rounded half up to whole cents. The cap is that rounded per-year amount summed over the term.

For both `ABATEMENT` and `TIF`, the rounding order is pinned: round each year's amount to whole cents first, then sum across the term. Summing the raw per-year amounts and rounding once at the end is incorrect and can differ by cents.

Execution reserves budget: it requires that the program's `available_budget_cents` is greater than or equal to the computed `max_incentive_cents`, failing with `ERR_PROGRAM_BUDGET_EXCEEDED` (HTTP 402) when the pool cannot cover the award. On success it moves `max_incentive_cents` from available into committed as described in §2.6. The agreement's `gross_disbursed_cents`, `net_disbursed_cents`, and `clawed_back_cents` all start at 0.

A director activates the agreement, advancing `EXECUTED → ACTIVE` and incrementing the agreement `version`. Activating, declaring default, or otherwise transitioning an agreement from an illegal state yields `ERR_AGREEMENT_INVALID_STATE`. An agreement reaches `COMPLETED` (from `ACTIVE`) or `CLOSED` (from `DEFAULTED`) only through the cascades described below; both are terminal.

### 3.4. Attaching Clawback Covenants

While governing an agreement, a `ProgramDirector` attaches clawback covenants that bind the recipient to measurable outcomes; attaching a covenant increments the agreement `version`. Each covenant declares a `covenant_type` of either `JOBS` or `INVESTMENT`, a `target_value` (a job count for a jobs covenant, or investment cents for an investment covenant), and a closed measurement interval bounded by `measurement_start_date` and `measurement_end_date`, where the end must be on or after the start. An optional `cure_period_days` (defaulting to 0) grants grace days after the measurement window during which a breach may still be cured. A covenant starts `ACTIVE` with `attainment_pct` at 0.

Two guards protect covenant creation. The `target_value` must meet or exceed the program's floor for its type — at least `min_jobs_required` for a `JOBS` covenant, or at least `min_investment_cents` for an `INVESTMENT` covenant — otherwise the request is rejected with `ERR_COVENANT_TARGET_BELOW_MINIMUM` (HTTP 422). And the new covenant's closed measurement window must not overlap the window of any existing covenant of the same `covenant_type` on the same agreement; an overlap is rejected with `ERR_COVENANT_WINDOW_OVERLAP` (HTTP 409). Covenants of different types may overlap freely.

A covenant advances through the compliance cascade to `MET` when its attainment reaches the threshold, or to `BREACHED` when it falls short, and a `BREACHED` covenant may later be cured back to `MET`. Independently, a director may waive a covenant that is `ACTIVE` or `BREACHED`, advancing it to `WAIVED` with an optional `reason`; waiving from any other state yields `ERR_COVENANT_INVALID_STATE`. Both `MET` and `WAIVED` are terminal. Whenever a waive leaves every covenant on the agreement in `MET` or `WAIVED`, the agreement bubbles from `ACTIVE` to `COMPLETED`, and the completion releases the remaining reservation back into the program's available budget as described in §2.6.

### 3.5. Annual Compliance Reporting and Covenant Re-Evaluation

Each year the `Applicant` files a compliance report against the agreement. The submission payload declares the `reporting_year`, a half-open reporting period bounded by `period_start_date` and an exclusive `period_end_date` (which must be strictly after the start), the certified `actual_jobs` and `actual_investment_cents` for the period, and an `attestation` flag (defaulting to false). When `attestation` is true at submission, the submitter's identifier is stamped into `certified_by`. A report is created in `SUBMITTED`.

A `ProgramAnalyst` dispositions the report. Returning it for correction advances `SUBMITTED → RETURNED` with an optional `reason`; the owning applicant may then resubmit, advancing `RETURNED → SUBMITTED` and optionally revising `actual_jobs`, `actual_investment_cents`, and `attestation`. Only the applicant who owns the agreement's originating application may resubmit. Accepting the report advances `SUBMITTED → ACCEPTED` and is guarded twice: the report's `attestation` must be true, otherwise acceptance fails with `ERR_REPORT_NOT_CERTIFIED` (HTTP 422); and the report's half-open period must not overlap the period of any already-`ACCEPTED` report on the same agreement, otherwise it fails with `ERR_REPORTING_PERIOD_OVERLAP` (HTTP 409). Dispositioning a report from an illegal state yields `ERR_COMPLIANCE_REPORT_INVALID_STATE`. `ACCEPTED` is terminal; a returned report cycles back through `SUBMITTED` for another disposition.

Acceptance drives the compliance cascade. For each governing covenant on the agreement, the system recomputes `attainment_pct` from the latest accepted report: the relevant actual is `actual_jobs` for a `JOBS` covenant or `actual_investment_cents` for an `INVESTMENT` covenant, and the attainment percentage is that actual divided by the covenant's `target_value`, multiplied by 100, and rounded half up to two decimal places. A covenant whose recomputed attainment is greater than or equal to 100.00 advances to `MET`; a covenant below 100.00 advances to `BREACHED`. A covenant that had previously breached may be cured back to `MET` by a later accepted report meeting the threshold, but only if the logical clock is still within the cure window — that is, at or before the covenant's `measurement_end_date` plus its `cure_period_days`. If the recomputation leaves every covenant on the agreement in `MET` or `WAIVED`, the agreement bubbles from `ACTIVE` to `COMPLETED` and the remaining reservation is released to available budget.

### 3.6. Disbursing Against Accepted Reports

A `ComplianceOfficer` creates a period disbursement, which references the `agreement_id` and the justifying `compliance_report_id` and must carry `expected_agreement_version`. The linked report must be in `ACCEPTED`; otherwise the create is rejected with `ERR_NO_ACCEPTED_REPORT` (HTTP 409). The optimistic-concurrency guard of §2.8 applies: a mismatch between `expected_agreement_version` and the agreement's current `version` yields `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). On success the disbursement copies `period_year` from the source report's `reporting_year`, is created in status `CALCULATED`, and increments the agreement `version`.

Creation computes two figures. The per-period base is the agreement's `max_incentive_cents` divided by its `term_years`, rounded half up to whole cents. For an `ABATEMENT` or `TIF` agreement, disbursements are automatic and not attainment-adjusted: both `gross_entitlement_cents` and `disbursed_amount_cents` equal the per-period base. For a `GRANT` agreement, the entitlement is attainment-adjusted: `gross_entitlement_cents` is the per-period base, while `disbursed_amount_cents` is the per-period base multiplied by an attainment ratio, then rounded half up to whole cents. That attainment ratio is the report's `actual_jobs` divided by the agreement's `awarded_jobs`, capped at 1.0 — so a grant recipient that meets or exceeds its job commitment receives the full per-period base, while one that falls short receives a proportionally reduced amount.

The officer then approves the disbursement, advancing `CALCULATED → APPROVED`, and pays it, advancing `APPROVED → PAID`. Payment is capped: the agreement's `gross_disbursed_cents` plus this disbursement's `disbursed_amount_cents` must not exceed the agreement's `max_incentive_cents`, otherwise the payment is rejected with `ERR_DISBURSEMENT_EXCEEDS_CAP` (HTTP 402). On payment, the agreement's `gross_disbursed_cents` and `net_disbursed_cents` each increase by the paid amount, the program moves that amount from committed into disbursed, and the agreement `version` increments. Approving or paying a disbursement from an illegal state yields `ERR_DISBURSEMENT_INVALID_STATE`. A `PAID` disbursement is only ever moved to `CLAWED_BACK` by recapture finalization; `CLAWED_BACK` is terminal.

### 3.7. Default, Recapture, Dispute, and Finalization

When a recipient falls out of compliance, a `ProgramDirector` declares default on an `ACTIVE` agreement, optionally supplying a `severity` and a `reason`. Default requires that at least one covenant is not in `MET` or `WAIVED`; if every covenant is already met or waived there is nothing to enforce and the request is rejected with `ERR_NO_BREACH_TO_DEFAULT` (HTTP 409). Declaring default advances the agreement `ACTIVE → DEFAULTED`, increments its `version`, and fires the default cascade in two hops: first, every covenant currently `ACTIVE` is driven to `BREACHED`; second, the resulting set of covenants not in `MET` or `WAIVED` gives rise to exactly one recapture assessment in status `ASSESSED`. That assessment records the `trigger_reason` from the declaration, a `severity` taken from the payload and defaulting to `PARTIAL`, a `breached_covenants_count` equal to the number of covenants not in `MET` or `WAIVED` at default time, and a `total_covenants_count` equal to all covenants on the agreement at default time.

The assessment's `assessed_amount_cents` is the recapture owed and is computed by severity. A `MATERIAL` default is a cliff: the full `net_disbursed_cents` of the agreement is recaptured. A `PARTIAL` default is pro-rata: the agreement's `net_disbursed_cents` is multiplied by the ratio of `breached_covenants_count` to `total_covenants_count`, then rounded half up to whole cents. The two coincide only when every covenant is breached; whenever the breached count is below the total, the partial figure is smaller.

The recapture record has its own lifecycle. The owning applicant may dispute an `ASSESSED` assessment, optionally supplying `grounds`, advancing it `ASSESSED → DISPUTED`. A `ComplianceOfficer` resolves a disputed or assessed record by finalizing it. Finalization carries an optional `reopen` flag: when `reopen` is true against a `DISPUTED` assessment, the officer bounces it back `DISPUTED → ASSESSED` for further review without any clawback. Otherwise finalization advances the record from `ASSESSED` or `DISPUTED` to `FINALIZED` and drives the recapture cascade — every `PAID` disbursement on the agreement moves to `CLAWED_BACK` (each hop subtracting the disbursed amount from the agreement's `net_disbursed_cents`, adding it to `clawed_back_cents`, leaving `gross_disbursed_cents` unchanged, and returning the amount from the program's disbursed bucket into available), and the agreement bubbles `DEFAULTED → CLOSED`. Alternatively a `ProgramDirector` may waive an `ASSESSED` or `DISPUTED` assessment with an optional `reason`, advancing it to `WAIVED` and closing the agreement `DEFAULTED → CLOSED` without any clawback. Both `FINALIZED` and `WAIVED` are terminal; closing an agreement through either path releases its remaining reservation to available budget. Attempting to dispute, finalize, or waive an assessment from an illegal state yields `ERR_RECAPTURE_INVALID_STATE`.

### 3.8. Transparency Disclosures and the Portfolio Dashboard

A `ComplianceOfficer` publishes a transparency disclosure for an agreement, supplying only the `disclosure_year`; the disclosure is created in status `PUBLISHED`, which is its sole and terminal state. Publication snapshots five public facts at the moment of disclosure: `disclosed_recipient_name` from the originating application's `applicant_name`, `disclosed_incentive_type` from the agreement's `incentive_type`, `disclosed_max_incentive_cents` from the agreement's `max_incentive_cents`, `disclosed_net_disbursed_cents` from the agreement's `net_disbursed_cents` at publication, and `disclosed_jobs_committed` from the agreement's `awarded_jobs`. Programs configure a `disclosure_threshold_cents` marking the award size at or above which a disclosure is expected. Published disclosures, along with programs and the portfolio dashboard, are readable by every role including the `PublicViewer`.

The portfolio dashboard is a computed read that aggregates the whole book (optionally scoped to one `program_id`). It reports `active_agreement_count` as the number of agreements in `ACTIVE`, `defaulted_agreement_count` as the number in `DEFAULTED`, `total_committed_cents` as the sum of every program's `committed_cents`, `total_disbursed_cents` as the sum of every program's `disbursed_cents`, and `total_recaptured_cents` as the sum of `assessed_amount_cents` across recapture assessments in status `FINALIZED`. All figures are whole cents over the stated status filters.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; reads and state-transition endpoints return HTTP 200 with the affected or retrieved resource. All endpoints share the response envelope of §2.2 and the validation ordering of §2.10.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/incentive-programs` | Create an incentive program (funding pool + rate config) | ProgramDirector |
| GET | `/incentive-programs` | List incentive programs | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer, PublicViewer |
| GET | `/incentive-programs/{programId}` | Get one incentive program | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer, PublicViewer |
| POST | `/parcels` | Register a parcel with base and current assessed values | ProgramDirector |
| GET | `/parcels` | List parcels | ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/parcels/{parcelId}` | Get one parcel | ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/applications` | Create an incentive application (DRAFT) | Applicant |
| GET | `/applications` | List/filter applications | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/applications/{applicationId}` | Get one application | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/applications/{applicationId}/submit` | Submit a draft application | Applicant |
| POST | `/applications/{applicationId}/start-review` | Begin review; creates the eligibility review | ProgramAnalyst |
| POST | `/applications/{applicationId}/approve` | Approve; enforces PASS review + four-eyes | ProgramDirector |
| POST | `/applications/{applicationId}/deny` | Deny an application | ProgramDirector |
| GET | `/eligibility-reviews` | List/filter eligibility reviews | ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/eligibility-reviews/{reviewId}` | Get one eligibility review | ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/agreements` | Execute an agreement from an approved application | ProgramDirector |
| GET | `/agreements` | List/filter agreements | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/agreements/{agreementId}` | Get one agreement | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/agreements/{agreementId}/activate` | Activate an agreement | ProgramDirector |
| POST | `/agreements/{agreementId}/declare-default` | Declare default; cascade breach + recapture | ProgramDirector |
| POST | `/agreements/{agreementId}/covenants` | Attach a clawback covenant to an agreement | ProgramDirector |
| GET | `/covenants` | List/filter covenants | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/covenants/{covenantId}` | Get one covenant | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/covenants/{covenantId}/waive` | Waive a covenant | ProgramDirector |
| POST | `/agreements/{agreementId}/compliance-reports` | Submit an annual compliance report | Applicant |
| GET | `/compliance-reports` | List/filter compliance reports | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/compliance-reports/{reportId}` | Get one compliance report | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/compliance-reports/{reportId}/accept` | Accept a report; cascade re-evaluates covenants | ProgramAnalyst |
| POST | `/compliance-reports/{reportId}/return` | Return a report for correction | ProgramAnalyst |
| POST | `/compliance-reports/{reportId}/resubmit` | Resubmit a returned report | Applicant |
| POST | `/disbursements` | Create a period disbursement (OCC-guarded) | ComplianceOfficer |
| GET | `/disbursements` | List/filter disbursements | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/disbursements/{disbursementId}` | Get one disbursement | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/disbursements/{disbursementId}/approve` | Approve a disbursement | ComplianceOfficer |
| POST | `/disbursements/{disbursementId}/pay` | Pay a disbursement; updates ledgers | ComplianceOfficer |
| GET | `/recapture-assessments` | List/filter recapture assessments | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| GET | `/recapture-assessments/{assessmentId}` | Get one recapture assessment | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer |
| POST | `/recapture-assessments/{assessmentId}/dispute` | Dispute an assessment | Applicant |
| POST | `/recapture-assessments/{assessmentId}/finalize` | Finalize or reopen; cascade clawback + close | ComplianceOfficer |
| POST | `/recapture-assessments/{assessmentId}/waive` | Waive an assessment; close without clawback | ProgramDirector |
| POST | `/agreements/{agreementId}/disclosures` | Publish a transparency disclosure snapshot | ComplianceOfficer |
| GET | `/disclosures` | List/filter published disclosures | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer, PublicViewer |
| GET | `/disclosures/{disclosureId}` | Get one disclosure | Applicant, ProgramAnalyst, ProgramDirector, ComplianceOfficer, PublicViewer |
| GET | `/portfolio/summary` | Portfolio dashboard aggregates | ProgramAnalyst, ProgramDirector, ComplianceOfficer, PublicViewer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramDirector, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 422 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_PARCEL_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_ELIGIBILITY_REVIEW_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_COVENANT_NOT_FOUND | 404 |
| ERR_COMPLIANCE_REPORT_NOT_FOUND | 404 |
| ERR_DISBURSEMENT_NOT_FOUND | 404 |
| ERR_RECAPTURE_ASSESSMENT_NOT_FOUND | 404 |
| ERR_DISCLOSURE_NOT_FOUND | 404 |
| ERR_APPLICATION_INVALID_STATE | 409 |
| ERR_AGREEMENT_INVALID_STATE | 409 |
| ERR_COVENANT_INVALID_STATE | 409 |
| ERR_COMPLIANCE_REPORT_INVALID_STATE | 409 |
| ERR_DISBURSEMENT_INVALID_STATE | 409 |
| ERR_RECAPTURE_INVALID_STATE | 409 |
| ERR_ELIGIBILITY_NOT_PASSED | 409 |
| ERR_APPLICATION_NOT_APPROVED | 409 |
| ERR_NO_ACCEPTED_REPORT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_REPORT_NOT_CERTIFIED | 422 |
| ERR_COVENANT_TARGET_BELOW_MINIMUM | 422 |
| ERR_COVENANT_WINDOW_OVERLAP | 409 |
| ERR_REPORTING_PERIOD_OVERLAP | 409 |
| ERR_NO_BREACH_TO_DEFAULT | 409 |
| ERR_PROGRAM_BUDGET_EXCEEDED | 402 |
| ERR_DISBURSEMENT_EXCEEDS_CAP | 402 |
| ERR_STALE_AGREEMENT_VERSION | 412 |
