# Salary Survey Market Pricing API — Product Requirements Document

## 1. Introduction

Compensation teams live and die by the quality of their market data. Every year, organizations purchase salary surveys from vendors such as Radford, Mercer, and WTW; submit their own incumbent data back to those vendors under strict contractual terms; match their internal jobs to the vendors' benchmark codes; and then distill all of it into a single defensible number per job — the market composite — that anchors pay decisions. Today this work lives in spreadsheets: aging factors are applied inconsistently, geographic differentials vary by analyst, match weights are negotiated over email, and nobody can reconstruct why last quarter's midpoint moved. The Salary Survey Market Pricing API replaces that sprawl with a single, auditable system of record for the entire participation-to-pricing pipeline.

This document specifies that API for the engineering team building it. The system covers survey vendor contract and data-governance management; preparation, submission, and rework of incumbent data packages; job-to-benchmark matching with confidence ratings and segregation of duties; aging, geographic, and industry adjustments blended into published market composites; market-position analysis against strategy percentile targets; off-cycle market adjustment cycles with budget enforcement; and compensation-committee reporting with frozen snapshots. Two design commitments run through everything that follows: every derived number must be reproducible from stated rules, and every state change that matters must leave an audit footprint.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled precisely as follows: `CompAnalyst`, `CompManager`, `HRDirector`, `CompCommitteeReviewer`, and `VendorAdmin`. Access to every operation is restricted by role per the authorization matrix in §4; a caller whose role is valid but not permitted for the requested endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Four of the five roles are entity-backed. When `X-User-Role` is `CompAnalyst`, `CompManager`, `HRDirector`, or `CompCommitteeReviewer`, the `X-User-ID` header carries the `id` of the acting Employee record; wherever a rule compares the caller to a persisted person — for example the segregation-of-duties comparison against `proposed_by_employee_id`, or the retract-permission comparison on an adjustment — the comparison is made between `X-User-ID` and the referenced Employee's `id`. When `X-User-Role` is `VendorAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any Employee's `id`, and audit records produced by `VendorAdmin` actions (or by automatic system transitions) therefore carry a null `actor_employee_id`.

A `CompAnalyst` prepares survey submissions, proposes job-to-benchmark matches, and proposes market adjustments. A `CompManager` reviews and approves matches, manages strategies, composites, and cycles, approves and applies adjustments, and creates and finalizes reports; a `CompManager` may also create employees. An `HRDirector` presents finalized reports to the committee and shares the employee-creation capability with `CompManager`. A `CompCommitteeReviewer` is read-only. A `VendorAdmin` operates the vendor side of the house: creating organizations, vendors, surveys, and benchmarks; opening, closing, accepting, and rejecting surveys; accepting and returning submissions; and controlling the logical clock described in §2.4. All five roles may read any org-scoped resource.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All date-sensitive rules in this document — contract windows, submission deadlines, adjustment effective dates, vendor expiry — are evaluated against a server-side logical clock, never against real wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every evaluation observes that instant, and the clock must never silently fall back to the host's wall clock. A `VendorAdmin` may advance the logical clock through an admin-only test-driving capability that sets it to a supplied ISO 8601 instant `to_iso8601`; the response reports the resulting time in a `current_utc` field. Wherever this document says "current date" or "now," it means this logical clock.

### 2.5. Common Resource Properties

Every primary resource — Organization, MarketStrategyPolicy, Employee, Job, SurveyVendor, Survey, SurveyBenchmark, SurveySubmission, SurveyJobMatch, MarketComposite, MarketAdjustmentCycle, MarketAdjustment, and CompensationReport — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` field is an integer that increments by one on every mutation, including mutations performed by the server itself as side effects of operations on related resources. AuditEvent resources are the deliberate exception: because they are immutable once written, they carry only `id` and `created_at` — both `updated_at` and `version` are absent from an AuditEvent.

### 2.6. Nested Resource Resolution and the Validation Ladder

The API enforces strict hierarchical validation on every nested path. When an endpoint path chains identifiers — an organization containing a vendor containing a survey containing a benchmark, and so on — the server validates path parameters from left to right, confirming each resource exists within the enclosing scope before examining the next. The first identifier that fails to resolve produces an `ERR_NOT_FOUND` (HTTP 404), and no later segment is evaluated after a failure.

Beyond existence, every request walks a single fixed validation ladder, and the ladder's order determines which error surfaces when several rules could reject the same call. The rungs, from first to last, are: (1) presence and well-formedness of the `X-User-ID` and `X-User-Role` headers, failing as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role permission for the endpoint, failing as `ERR_FORBIDDEN_FOR_ROLE`; (3) left-to-right existence of path-referenced resources within the org scope, failing as `ERR_NOT_FOUND`; (4) request well-formedness — the body parses, required input fields are present, enum fields carry declared values, and date fields are valid ISO dates — failing as `ERR_INVALID_REQUEST`; (5) generic state-transition legality for the target resource, failing as `ERR_INVALID_STATE_TRANSITION`; (6) cycle gating, failing as `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_LOCKED`, `ERR_CYCLE_HAS_PENDING`, or `ERR_CYCLE_HAS_UNAPPLIED`; (7) survey-lifecycle gating for submissions, matches, survey acceptance, vendor termination, and adjustment submission, failing as `ERR_SURVEY_NOT_OPEN`, `ERR_SUBMISSIONS_PENDING`, `ERR_VENDOR_HAS_OPEN_SUBMISSIONS`, or `ERR_NO_PUBLISHED_COMPOSITE`; (8) segregation of duties, failing as `ERR_SOD_VIOLATION`; (9) temporal windows — vendor contract windows, submission deadlines, adjustment effective dates — failing as `ERR_VENDOR_CONTRACT_WINDOW`, `ERR_SUBMISSION_WINDOW_CLOSED`, or `ERR_ADJUSTMENT_NOT_YET_EFFECTIVE`; (10) strategy window overlap, failing as `ERR_STRATEGY_WINDOW_OVERLAP`; (11) cycle effective-date overlap, failing as `ERR_CYCLE_EFFECTIVE_OVERLAP`; (12) referential gates — vendor must be `ACTIVE`, vendor data-use scope must permit participation, pinned strategy must be `ACTIVE` — failing as `ERR_VENDOR_NOT_ACTIVE`, `ERR_VENDOR_SCOPE_FORBIDS_SUBMISSION`, or `ERR_STRATEGY_NOT_ACTIVE`; (13) strategy homogeneity at report finalization, failing as `ERR_MIXED_STRATEGY_SOURCES`; (14) the benchmark sample-size floor for match approval, failing as `ERR_SAMPLE_SIZE_TOO_SMALL`; (15) match weight bounds, failing as `ERR_INVALID_WEIGHT`; (16) submission snapshot content, failing as `ERR_EMPTY_SUBMISSION` or `ERR_EMPLOYEE_NOT_ACTIVE`; (17) one-published-composite-per-strategy uniqueness, failing as `ERR_ALREADY_PUBLISHED`; (18) the presence of at least one approved contributing source, failing as `ERR_NO_SOURCES`; (19) custom geo-index coverage, failing as `ERR_GEO_INDEX_MISSING`; (20) optimistic-concurrency freshness, failing as `ERR_STALE_VERSION`; (21) the cycle budget ceiling, failing as `ERR_BUDGET_EXCEEDED`; and (22) proposed-amount bounds, failing as `ERR_INVALID_AMOUNT`. A request rejected at an earlier rung never reaches a later one.

### 2.7. Money, Basis Points, and Rounding

All monetary amounts in this system are integers denominated in whole cents — salaries, budgets, adjustments, and every blended percentile alike — and all monetary arithmetic rounds half-up to zero decimal places (whole cents) at the points the relevant rule specifies; no intermediate term is rounded unless the rule says so. Ratios and multiplicative factors are expressed in basis points, where 10000 basis points is exactly 1.0x; compa-ratios, geographic differentials, industry premiums, and percentile attainments are all basis-point integers rounded half-up to zero decimal places. Percentages carried as inputs (such as `match_weight_pct`) are plain integers. Because every persisted figure is an integer, any two readers of the same resource always agree on its value.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of a parent entity before mutating beneath it. Publishing a market composite requires the request to carry `expected_job_version`, the client's last observed `version` of the parent Job; if the Job's current `version` has advanced past that value, the publish is rejected with `ERR_STALE_VERSION` (HTTP 412). Approving a market adjustment requires the request to carry `expected_cycle_version`, the client's last observed `version` of the parent MarketAdjustmentCycle; if the cycle's current `version` no longer matches, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). These are pure freshness checks — a client that re-reads the parent and retries with the observed `version` proceeds normally. No other endpoint takes a version field; requests to all other endpoints must not include one.

### 2.9. Segregation of Duties

The system enforces a strict separation between proposing and approving wherever money or market data becomes official. The person who approves a survey job match must not be the person who proposed it, and the person who approves a market adjustment must not be the person who proposed it. Both checks compare the caller's `X-User-ID` against the record's `proposed_by_employee_id`, and both reject a self-approval with `ERR_SOD_VIOLATION` (HTTP 409). A related but distinct rule governs retraction: only the proposer of an adjustment may retract it, and a retract attempt by anyone else is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

### 2.10. Audit Trail

Every mutation that changes official state emits an AuditEvent beneath the owning organization. An audit record carries the `org_id` of the owning organization, the `actor_employee_id` of the acting Employee (null when the actor is the system or an opaque role), the machine name of the `action` (for example `SURVEY_SUBMIT` or `MATCH_APPROVE`), the `target_entity` naming the type of the mutated resource, the `target_id` of that resource, and a `payload_hash` equal to the SHA-256 of the canonical JSON of the side-effect payload. Audit events are append-only and read-only through the API; they are created as side effects of the workflows described in §3 and are listed alongside the individual action names there.

### 2.11. Cascading Lifecycle Consistency

Parent and child lifecycles are kept mutually consistent by automatic cascades; the server transitions dependent resources without requiring a separate client request for each one. When a vendor's contract ends — by expiry or termination — its not-yet-final surveys are rejected and their unfinished submission packages are returned to the preparing analysts. When a survey closes, its un-submitted packages are returned. When a new market composite is published for a job, the job's previously published composite is superseded rather than deleted, preserving history. Every such cascade mutates each affected resource normally: `status` changes, `updated_at` refreshes, and `version` increments on every mutated record, so an optimistic-concurrency reader of any cascaded record always observes the change.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Organization and Its Market Strategy

A `VendorAdmin` onboards a client by creating an Organization with its legal `name`, its `base_currency` as an ISO 4217 code such as USD, an optional `fiscal_year_start_month` (an integer from 1 to 12, defaulting to 1 when omitted), and the `market_as_of_date` — the ISO date to which all survey data will be aged during composite computation. The organization's `strategy_policy_id` starts null and remains so until a strategy is first activated; the organization list endpoint supports filtering by `strategy_policy_id` so operators can find every org governed by a given policy.

A `CompManager` then drafts the organization's pricing strategy as a MarketStrategyPolicy. The policy records its `name`; a `target_percentile` for midpoint positioning, which must be one of 25, 50, 65, 75, or 90; a `geo_differential_policy` of `NATIONAL`, `METRO_TIER`, or `CUSTOM_GEO_INDEX`; an `industry_cut` of `ALL_INDUSTRIES`, `HIGH_TECH`, `FINANCIAL_SERVICES`, `HEALTHCARE`, `MANUFACTURING`, or `RETAIL`; and a governing window from `effective_from` (inclusive) to `effective_to` (exclusive). New policies are born in `DRAFT` status.

Activation by a `CompManager` moves a policy from `DRAFT` to `ACTIVE`. Two guards apply, in ladder order: the window must be internally valid — `effective_from` strictly earlier than `effective_to`, failing as `ERR_INVALID_REQUEST` — and no other `ACTIVE` strategy for the same organization may have a window overlapping this policy's `[effective_from, effective_to)` interval, where overlap of the half-open intervals is what matters; a violation fails as `ERR_STRATEGY_WINDOW_OVERLAP`. Activation repoints the organization's `strategy_policy_id` to the newly active policy and increments the Organization's `version` (refreshing its `updated_at`) as a side effect. Retirement moves an `ACTIVE` policy to its terminal `RETIRED` state; if the retiring policy is the one currently referenced by the organization's `strategy_policy_id`, that reference is cleared back to null. Strategy policies can be listed globally with optional `org_id` and `status` filters, or enumerated under their organization.

### 3.2. The Job Architecture and Employee Roster

Before any market data can be priced, the organization needs its internal structure. A `CompManager` creates each Job with a `job_code` that is unique within the org, a `title`, a `job_family` grouping such as ENG, FIN, or HR, a `career_level` drawn from `IC1`, `IC2`, `IC3`, `IC4`, `IC5`, `M1`, `M2`, or `M3`, and an `flsa_status` of `EXEMPT` or `NON_EXEMPT`. A job's `current_market_composite_id` is system-maintained: it starts null and is repointed to the job's latest `PUBLISHED` composite each time one is published (§3.6). Jobs are listable globally — with optional `org_id`, `job_family`, `career_level`, and `current_market_composite_id` filters — or under their organization.

Employees are created by a `CompManager` or an `HRDirector`, with a `full_name`, a work `email` unique within the org, the `job_id` of their current assignment, a `geo_code` location code such as US-SF, US-NYC, or US-REMOTE that later drives geographic differentials, their current `base_salary_annual_cents` as a whole-cent integer, and their `hire_date`. Each employee carries a system-managed `status` of `ACTIVE`, `LEAVE`, or `TERMINATED`; several downstream rules admit only `ACTIVE` employees. The roster can be listed globally with `org_id`, `job_id`, `status`, and `geo_code` filters, under an organization, or as the assignee list of a single job. Both jobs and employees are org-scoped records, each carrying its `org_id` reference.

### 3.3. Vendor Contracts and Survey Data Governance

Survey participation begins with contract administration. A `VendorAdmin` registers a SurveyVendor under an organization with its `vendor_name`, a `contract_start_date` (inclusive) and `contract_end_date` (exclusive) bracketing the contractual window, a `data_use_scope` of `BENCHMARK_ONLY` or `FULL_PARTICIPATION` governing whether the org may submit its own incumbent data to this vendor, and a `confidentiality_tier` of `PUBLIC`, `CONFIDENTIAL`, or `RESTRICTED`. Vendors are born in `DRAFT` and can be listed with `org_id` and `status` filters.

Activation — a `VendorAdmin` moving the vendor from `DRAFT` to `ACTIVE` — is permitted only while the current date falls within the contract window, that is, on or after `contract_start_date` and strictly before `contract_end_date`; otherwise the request fails with `ERR_VENDOR_CONTRACT_WINDOW`. A successful activation emits a `VENDOR_ACTIVATE` audit event. A vendor that reaches its `contract_end_date` is expired automatically by the system: the vendor transitions from `ACTIVE` to `EXPIRED`, every child survey still in `DRAFT` or `OPEN` is rejected, and a `VENDOR_EXPIRE` audit event is emitted. A `VendorAdmin` may instead terminate an `ACTIVE` vendor early, but only when no child survey is sitting in `SUBMITTED` status — a vendor with submissions in flight cannot be cut off, and the attempt fails with `ERR_VENDOR_HAS_OPEN_SUBMISSIONS`. Termination moves the vendor to `TERMINATED`, rejects every child survey in `DRAFT` or `OPEN`, and — because a rejected survey returns its unfinished packages — each of those surveys' submission packages in `DRAFT` or `READY` transitions to `RETURNED` with `rejection_reason` set to the literal `VENDOR_TERMINATED`; a `VENDOR_TERMINATE` audit event is emitted. Expiry and termination are the vendor's two terminal states.

### 3.4. The Survey Participation Cycle: From Submission Package to Vendor Verdict

Within an active vendor, a `VendorAdmin` registers each Survey with the vendor's own `survey_code` (unique per vendor), the `edition_year` such as 2026, the `data_effective_date` as of which the published data is effective (this date feeds the aging calculation of §3.6), the `submission_deadline`, and the `industry_cut_supported` list naming which industry cuts the edition publishes. Each survey belongs to a vendor through `vendor_id` and is also denormalized onto its organization via `org_id`, so surveys can be listed globally with `org_id`, `vendor_id`, `status`, and `edition_year` filters, under a vendor, or under an organization. A survey is born in `DRAFT`.

Opening a survey — a `VendorAdmin` moving it from `DRAFT` to `OPEN` — requires the parent vendor to be `ACTIVE` (failing as `ERR_VENDOR_NOT_ACTIVE`) and requires the current date to be on or before the `submission_deadline` (failing as `ERR_SUBMISSION_WINDOW_CLOSED`); submissions are accepted on the deadline date itself because the window is a closed interval. A survey closes either when a `VendorAdmin` closes it explicitly or automatically on the day after its `submission_deadline`; in both cases the survey moves from `OPEN` to `CLOSED`, and every child submission package still in `DRAFT` or `READY` is returned with `rejection_reason` set to `SURVEY_CLOSED`. Immediately upon closing, the survey's fate is decided by its contents: if at least one child submission is in `SUBMITTED`, the survey advances from `CLOSED` to `SUBMITTED`; if none is, it falls from `CLOSED` to `REJECTED` and is finished.

The submission package itself is the analyst's work product. A `CompAnalyst` creates a SurveySubmission under a survey, naming themselves as `submitted_by_employee_id` and attaching the `incumbent_snapshot` — an array of entries, each containing the `employee_id`, `job_id`, `base_salary_annual_cents`, and `geo_code` of one incumbent to be reported. Packages are born in `DRAFT` with `prepared_at`, `submitted_at`, and `rejection_reason` all null, and can be listed globally with `survey_id`, `submitted_by_employee_id`, and `status` filters, under a survey, or as the preparation history of a single employee.

Marking a package ready — the analyst moving it from `DRAFT` to `READY` — enforces four checks in ladder order: the parent survey must be `OPEN` (`ERR_SURVEY_NOT_OPEN`); the vendor's `data_use_scope` must be `FULL_PARTICIPATION`, since a `BENCHMARK_ONLY` contract forbids incumbent submissions (`ERR_VENDOR_SCOPE_FORBIDS_SUBMISSION`); the `incumbent_snapshot` must contain at least one entry (`ERR_EMPTY_SUBMISSION`); and every snapshot entry must reference an `ACTIVE` employee of this organization (`ERR_EMPLOYEE_NOT_ACTIVE`). Success stamps `prepared_at` with the current logical time. Submitting the ready package — `READY` to `SUBMITTED` — again requires the survey to be `OPEN` and the current date to be on or before the deadline (`ERR_SUBMISSION_WINDOW_CLOSED`); success stamps `submitted_at` and emits a `SURVEY_SUBMIT` audit event.

The vendor then renders verdicts. A `VendorAdmin` may accept an individual `SUBMITTED` package, moving it to `ACCEPTED` and emitting `SUBMISSION_ACCEPT`, or return it with a request-supplied `reason`, moving it to `RETURNED` and recording that text as its `rejection_reason`. Alternatively the vendor adjudicates the whole survey at once: accepting a `SUBMITTED` survey requires that every one of its packages already sit in `SUBMITTED`, `ACCEPTED`, or `RETURNED` — nothing may still be pending in `DRAFT` or `READY`, on pain of `ERR_SUBMISSIONS_PENDING` — and acceptance moves the survey to `ACCEPTED`, cascades every `SUBMITTED` package to `ACCEPTED`, and emits `SURVEY_ACCEPT`. Rejecting a `SUBMITTED` survey takes a `reason` in the request, moves the survey to `REJECTED`, cascades every `SUBMITTED` package to `RETURNED` with that reason recorded as each package's `rejection_reason`, and emits `SURVEY_REJECT`. Survey acceptance and rejection are terminal, as are package acceptance and return — except that a `RETURNED` package may be reworked: the analyst moves it back to `DRAFT`, which requires the parent survey to be `OPEN` again and the deadline still open (`ERR_SUBMISSION_WINDOW_CLOSED`), and which clears `rejection_reason`, `prepared_at`, and `submitted_at` all back to null so the package can begin its cycle anew.

### 3.5. Matching Jobs to Survey Benchmarks

Pricing power comes from matching internal jobs to the right external benchmarks. A `VendorAdmin` loads each SurveyBenchmark under its survey with the vendor's `benchmark_code` and `benchmark_title`, the benchmark's `career_level` (the same IC/M scale jobs use), its `industry_cut`, its `geo_scope` (either the literal `NATIONAL` or a specific geo code), the four percentile anchors `p25_cents`, `p50_cents`, `p75_cents`, and `p90_cents` as whole-cent integers, and the `sample_size` — the number of incumbents contributing to the benchmark. Benchmarks can be listed globally with `survey_id`, `career_level`, and `industry_cut` filters, or under their survey via `survey_id`.

A `CompAnalyst` proposes a SurveyJobMatch under a survey by naming the `job_id` being matched, the `benchmark_id` matched to, a `match_confidence` of `HIGH`, `MEDIUM`, or `LOW`, a `match_weight_pct` expressing this match's weight within the job's blend for this survey, and their own identity as `proposed_by_employee_id`. The weight must be an integer from 1 to 100 inclusive; an out-of-range or non-integer weight is rejected with `ERR_INVALID_WEIGHT` (HTTP 422) both at proposal time and again at review time. Matches are born in `PROPOSED` and can be listed globally with `survey_id`, `job_id`, `benchmark_id`, `proposed_by_employee_id`, `reviewer_employee_id`, and `status` filters, under a survey, or as the match history of a job.

Review is a manager's gate: a `CompManager` moves a match from `PROPOSED` to `REVIEWED`, which requires the parent survey to be in one of `OPEN`, `CLOSED`, `SUBMITTED`, or `ACCEPTED` — matching work may continue while vendor adjudication plays out, but not on surveys that never opened or have already been rejected; the violation surfaces as `ERR_SURVEY_NOT_OPEN` — and re-validates the weight bounds described above. From `REVIEWED`, approval moves the match to `APPROVED` and enforces two checks in ladder order: segregation of duties first, so the approving `X-User-ID` must differ from the match's `proposed_by_employee_id` (`ERR_SOD_VIOLATION`), then the statistical floor requiring the benchmark's `sample_size` to be at least 5 (`ERR_SAMPLE_SIZE_TOO_SMALL`). Approval stamps `reviewer_employee_id` with the approver's identity and emits a `MATCH_APPROVE` audit event. Until a match is approved, its `reviewer_employee_id` remains null. A manager may instead reject a `REVIEWED` match, moving it to `REJECTED` and emitting `MATCH_REJECT`. Rejection and review alike are not dead ends for the analysis: an analyst may send a `REVIEWED` or `REJECTED` match back to `PROPOSED` through revision, clearing the way for a corrected proposal. `APPROVED` and `REJECTED` are the terminal states, and only `APPROVED` matches ever feed a composite.

### 3.6. From Matches to Market: Building and Publishing the Composite

A MarketComposite distills every approved source for a job into four blended percentiles. A `CompManager` creates a composite under a job in `DRAFT` status, pinning the `strategy_policy_id` whose geographic and industry policies will govern the math, and the `job_geo_code` — the location code, such as US-SF, against which the geographic differential will be looked up. If that pinned strategy uses the `CUSTOM_GEO_INDEX` policy and the pinned `job_geo_code` has no entry in the custom index table, creation fails immediately with `ERR_GEO_INDEX_MISSING` (HTTP 422). Composites can be listed globally with `job_id`, `strategy_policy_id`, and `status` filters, under their job, or as the consumers of a strategy.

Computation — whether on demand through the recompute capability or as part of publication readiness — runs four stages in a fixed order, per source. First, aging grows each benchmark percentile from the survey's `data_effective_date` forward to the organization's `market_as_of_date`: the engine counts the whole calendar months between the two dates, counting a month only when the day-of-month of the `market_as_of_date` has reached or passed the day-of-month of the `data_effective_date` in that month, and flooring the count at zero so data is never aged backward when the as-of date precedes the effective date. The aging factor is 1.03 raised to the power of the elapsed months divided by twelve — a three percent annual market escalation compounded monthly — and each of `p25_cents`, `p50_cents`, `p75_cents`, and `p90_cents` is multiplied by it independently, each product rounded half-up to a whole cent exactly once at that final per-percentile multiplication.

Second, the geographic differential is applied per source according to the pinned strategy's `geo_differential_policy`. Under `NATIONAL`, geography is neutral — the aged values pass through unchanged — and the composite records `geo_differential_bp` as null. Under `METRO_TIER`, the factor comes from the metro table: `US-SF` at 12800, `US-NYC` at 12200, `US-SEA` at 11200, `US-AUS` at 10400, and `US-REMOTE` at 9500 basis points; a `job_geo_code` absent from the table falls back to a neutral 10000. Under `CUSTOM_GEO_INDEX`, the factor comes from the custom index — `US-SF` at 13100, `US-NYC` at 12400, `US-CHI` at 10600, and `US-REMOTE` at 9200 basis points — and a missing entry fails the whole computation with `ERR_GEO_INDEX_MISSING`. Each aged percentile is multiplied by the factor and divided by 10000, rounded half-up to a whole cent, and the applied factor is stored on the composite as `geo_differential_bp`.

Third, the industry premium is applied. When the strategy's `industry_cut` is `ALL_INDUSTRIES`, the premium is neutral. When the benchmark's own `industry_cut` matches the strategy's cut, the premium factor comes from the industry table — `HIGH_TECH` at 10800, `FINANCIAL_SERVICES` at 11200, `HEALTHCARE` at 10300, `MANUFACTURING` at 9800, `RETAIL` at 9400 basis points — and when the benchmark's cut does not match the strategy's, the premium is neutral: mismatched sources still contribute, at face value. Each geo-adjusted percentile is multiplied by the premium factor and divided by 10000, rounded half-up to a whole cent.

Fourth, the weighted blend combines the premium-adjusted sources. Only matches count that are themselves `APPROVED`, sit under a survey that has reached `ACCEPTED`, and belong to a vendor that remains `ACTIVE`. Each contributing match's effective weight is the product of three terms: its `match_weight_pct` expressed as a fraction of 100; a confidence factor of 1.00 for `HIGH`, 0.75 for `MEDIUM`, or 0.40 for `LOW`; and a sample factor equal to the benchmark's `sample_size` divided by 30, capped at 1.0 so benchmarks with thirty or more incumbents earn full sample credit. If the effective weights sum to zero, the computation fails with `ERR_NO_SOURCES`. Otherwise the effective weights are normalized to sum to one, and each blended percentile is the weighted sum of the premium-adjusted percentile values across sources, rounded half-up to a whole cent exactly once at the final sum — individual weighted terms are never rounded. The results are written to `blended_p25_cents`, `blended_p50_cents` (the market midpoint), `blended_p75_cents`, and `blended_p90_cents`, and `source_count` records how many approved matches contributed. One variant alters this stage: for executive-level jobs — `career_level` of `M1`, `M2`, or `M3` — the blend is conservative, halving the `LOW` confidence factor to 0.20 and outright excluding any benchmark with fewer than ten incumbents instead of merely discounting it through the sample factor.

Publication is the act that makes a composite official. A `CompManager` publishes a `DRAFT` composite, and the request must carry `expected_job_version` per §2.8. Publication evaluates its guards in ladder order: no other `PUBLISHED` composite for the same job may share this composite's `strategy_policy_id` (`ERR_ALREADY_PUBLISHED`); at least one approved contributing source must exist, meaning `source_count` is at least 1 (`ERR_NO_SOURCES`); and the supplied `expected_job_version` must equal the job's current `version` (`ERR_STALE_VERSION`, HTTP 412) — a client whose view of the job is stale, for example because a colleague has just published a newer composite, is turned away until it re-reads. On success the composite becomes `PUBLISHED` and its `published_at` — null until this moment — is stamped, the job's `current_market_composite_id` is repointed to the new composite and the job's `version` increments, the job's previously `PUBLISHED` composite cascades to `SUPERSEDED` (the only terminal state), and a `COMPOSITE_PUBLISH` audit event is emitted. Supersession is therefore automatic: a `PUBLISHED` composite never loses its status to a direct client call, only to the repointing of its job.

### 3.7. Off-Cycle Adjustments: Cycles, Budgets, and Approvals

When market analysis reveals employees priced below strategy, the correction runs through a governed budget cycle. A `CompManager` opens a MarketAdjustmentCycle with a `name` such as "2026-Q3 off-cycle", the `effective_date` on which adjustments become payable, and the total `budget_cents`. Cycles are born `OPEN`. One uniqueness rule guards creation: a new cycle's `effective_date` must not fall inside the window spanning any other `OPEN` or `LOCKED` cycle's creation date through its own `effective_date` (inclusive at both ends) for the same organization; a collision is rejected with `ERR_CYCLE_EFFECTIVE_OVERLAP`. The cycle's `allocated_cents` is computed, never written directly: it is the sum of `proposed_amount_cents` over child adjustments in `APPROVED` or `APPLIED` status, recomputed eagerly each time an adjustment enters `APPROVED`, and it changes only then. Cycles can be listed globally with `org_id` and `status` filters, or under their organization.

A `CompAnalyst` proposes a MarketAdjustment inside a cycle, supplying the `employee_id` of the recipient, the `proposed_amount_cents`, and their own identity as `proposed_by_employee_id`; the adjustment's `job_id` is denormalized from the employee's current job at creation. Creation requires the parent cycle to be `OPEN` (`ERR_CYCLE_NOT_OPEN`) and the proposed amount to be positive and no greater than fifteen percent of the employee's current base salary (`ERR_INVALID_AMOUNT`, HTTP 422). Adjustments are born in `DRAFT` and can be listed globally with `cycle_id`, `employee_id`, `job_id`, `proposed_by_employee_id`, `approved_by_employee_id`, and `status` filters, under a cycle, per employee, or per job.

Submitting a draft — the analyst moving it from `DRAFT` to `PENDING_APPROVAL` — runs its checks in ladder order: the parent cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`); the employee's job must have a published composite, that is, a non-null `current_market_composite_id` (`ERR_NO_PUBLISHED_COMPOSITE`); the employee must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`); and the amount must again satisfy the positive-and-within-fifteen-percent bounds (`ERR_INVALID_AMOUNT`). On submission the system computes and freezes two compa-ratios in basis points. An employee's compa-ratio is their `base_salary_annual_cents` multiplied by 10000 and divided by the composite's `blended_p50_cents`, rounded half-up to a whole basis point; `pre_adjustment_compa_ratio_bp` freezes this against the current salary, and `post_adjustment_compa_ratio_bp` freezes it with `proposed_amount_cents` added to that salary. The ratio maps to a position band used across reporting and recommendation: below 8000 is `BELOW_RANGE`; at least 8000 but below 9500 is `BELOW_TARGET`; at least 9500 and at most 10500 is `AT_TARGET`; above 10500 and at most 12000 is `ABOVE_TARGET`; above 12000 is `ABOVE_RANGE`.

Submission also produces the provisional recommendation, an advisory figure computed against the composite `PUBLISHED` at submit time. The recommendation targets the blended percentile named by the strategy's `target_percentile` — for example, `blended_p50_cents` when the policy targets the 50th percentile. The raw gap is the amount by which that target exceeds the employee's current salary, floored at zero; the single-adjustment cap is 1500 basis points — fifteen percent — of the current base, rounded half-up to a whole cent. The recommendation itself depends on the compa-ratio band: an employee whose ratio is at least 10500 is recommended zero; an employee below 8000 is recommended the raw gap capped at the fifteen-percent cap; an employee at least at 8000 but below 9500 is recommended the raw gap capped at sixty percent of the cap, with that sixty-percent figure itself rounded half-up to a whole cent; and everyone else is recommended zero. The provisional figure is advisory only — it is never recomputed at approval, and the approved amount is whatever the proposer wrote in `proposed_amount_cents`, which may differ from the recommendation.

Approval is a `CompManager` decision with three guards evaluated in ladder order: segregation of duties first — the approver's `X-User-ID` must differ from `proposed_by_employee_id` (`ERR_SOD_VIOLATION`); then optimistic concurrency — the request must carry `expected_cycle_version` equal to the cycle's current `version` per §2.8 (`ERR_STALE_VERSION`, HTTP 412), because the cycle's version advances on every approval and a stale read would otherwise let successive approvers over-commit the budget; then the budget ceiling — the cycle's current `allocated_cents` is read, the candidate's `proposed_amount_cents` is added to it, and the sum must not exceed `budget_cents` (`ERR_BUDGET_EXCEEDED`), with the amount added only after the check passes. A successful approval moves the adjustment to `APPROVED`, increments the cycle's `allocated_cents` by the approved amount, increments the cycle's `version`, stamps `approved_by_employee_id` — null until approval — with the approver's identity, and emits an `ADJUSTMENT_APPROVE` audit event. A manager may instead reject a `PENDING_APPROVAL` adjustment outright, moving it to `REJECTED` and emitting `ADJUSTMENT_REJECT`. The proposer alone may also retract a `PENDING_APPROVAL` adjustment back to `DRAFT`, provided the parent cycle is still `OPEN` (`ERR_CYCLE_NOT_OPEN`); a retract attempt by anyone other than the proposer is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Cycle governance wraps the individual decisions. Locking a cycle — `OPEN` to `LOCKED`, by a `CompManager` — requires that no child adjustment remain in `PENDING_APPROVAL` (`ERR_CYCLE_HAS_PENDING`) and emits `CYCLE_LOCK`; a locked cycle may be unlocked back to `OPEN` (emitting `CYCLE_UNLOCK`) if further work is needed. Applying an approved adjustment — `APPROVED` to `APPLIED` — requires the parent cycle to be `LOCKED` (`ERR_CYCLE_NOT_LOCKED`) and the current date to be on or after the cycle's `effective_date` (`ERR_ADJUSTMENT_NOT_YET_EFFECTIVE`); application adds `proposed_amount_cents` to the employee's `base_salary_annual_cents`, increments the employee's `version`, and emits `ADJUSTMENT_APPLY`. Finally, closing a `LOCKED` cycle requires every child adjustment to be in a terminal state — `APPLIED` or `REJECTED` — with any approved-but-unapplied adjustment blocking closure as `ERR_CYCLE_HAS_UNAPPLIED`; closure emits `CYCLE_CLOSE`, and `CLOSED` is terminal. `APPLIED` and `REJECTED` are an adjustment's terminal states.

### 3.8. Committee Reporting and the Market Position Snapshot

The compensation committee consumes analysis through frozen reports. A `CompManager` drafts a CompensationReport with a `title`, a `reporting_period_start` (inclusive) and `reporting_period_end` (exclusive), and the `pinned_strategy_policy_id` the report will speak to; reports are born in `DRAFT` and can be listed globally with `org_id`, `status`, and `pinned_strategy_policy_id` filters, or under their organization.

Finalization by a `CompManager` moves a report from `DRAFT` to `FINALIZED` and freezes its `snapshot_payload`, which remains null on the report until this moment. Two guards apply in ladder order: the pinned strategy must be `ACTIVE` at finalize time (`ERR_STRATEGY_NOT_ACTIVE`), and every `PUBLISHED` composite in the organization must either reference that pinned strategy or belong to a job explicitly excluded through the finalize request's optional `exclude_job_ids` list — mixing composites built under different strategies without explicit exclusion is rejected as `ERR_MIXED_STRATEGY_SOURCES`. The snapshot itself contains the pinned `strategy_policy_id`, a `generated_at_utc` timestamp, a per-job array, and an org-wide rollup. The per-job array covers every job in the organization whose `current_market_composite_id` is set and which was not excluded via `exclude_job_ids`; each entry carries the `job_id`, `job_code`, and `career_level`, the composite's `blended_p50_cents`, a `headcount` of `ACTIVE` employees assigned to the job, an `avg_compa_ratio_bp` equal to the mean of the per-employee compa-ratios (computed per §3.7) across those employees rounded half-up to a whole basis point, a `below_target_count` of active employees whose band is `BELOW_RANGE` or `BELOW_TARGET`, an `above_target_count` of those in `ABOVE_TARGET` or `ABOVE_RANGE`, and a `total_market_gap_cents` summing, across active employees, the amount by which the blended midpoint exceeds each salary — with any negative gap counted as zero. The org-wide rollup, `org_wide_avg_compa_ratio_bp`, is the headcount-weighted mean of the per-job average compa-ratios.

Percentile attainment places each employee's salary within the composite's percentile structure, expressed in basis points where 2500 represents the 25th percentile and 9000 the 90th. A salary below `blended_p25_cents` attains 2500 scaled by the salary's fraction of that 25th-percentile value, rounded half-up. A salary at least at the 25th but below the 50th percentile attains 2500 plus 2500 scaled by the salary's progress from `blended_p25_cents` to `blended_p50_cents` across that interval, the inner term rounded half-up. A salary at least at the 50th but below the 75th attains 5000 plus 2500 scaled by its progress from `blended_p50_cents` to `blended_p75_cents`, the inner term rounded half-up. A salary at least at the 75th but below the 90th attains 7500 plus 1500 scaled by its progress from `blended_p75_cents` to `blended_p90_cents`, the inner term rounded half-up. A salary at or above the 90th percentile attains 9000 plus 1000 scaled by the excess over `blended_p90_cents` as a fraction of that value, the inner term rounded half-up and the total capped so the added amount never exceeds 1000. Throughout, denominators use the exact blended cent values with no intermediate rounding of the ratios. Finalization also computes the final recommendation variant per employee using the same rule as §3.7 but against the composite `PUBLISHED` at finalize time; when a newer composite has superseded the submit-time one, the submit-time and finalize-time figures diverge, and that divergence is intentional.

Presentation closes the loop: an `HRDirector` moves a `FINALIZED` report to `PRESENTED`, stamping `presented_at` — null until then — with the current logical time and emitting a `REPORT_PRESENT` audit event. `PRESENTED` is terminal; the frozen `snapshot_payload` remains the immutable record of what the committee saw.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. Request and response payloads for each endpoint are governed by the workflows in §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/orgs` | Create an Organization | VendorAdmin |
| GET | `/orgs/{id}` | Get an Organization | All roles |
| GET | `/orgs` | List Organizations (filterable by `strategy_policy_id`) | All roles |
| POST | `/orgs/{id}/strategies` | Create a MarketStrategyPolicy (DRAFT) under an org | CompManager |
| GET | `/strategies/{id}` | Get a MarketStrategyPolicy | All roles |
| GET | `/strategies` | List MarketStrategyPolicies (filtered) | All roles |
| GET | `/orgs/{id}/strategies` | List Strategies under an Organization | All roles |
| POST | `/strategies/{id}/activate` | Activate a DRAFT strategy | CompManager |
| POST | `/strategies/{id}/retire` | Retire an ACTIVE strategy | CompManager |
| POST | `/orgs/{id}/jobs` | Create a Job under an org | CompManager |
| GET | `/jobs/{id}` | Get a Job | All roles |
| GET | `/jobs` | List Jobs (filtered) | All roles |
| GET | `/orgs/{id}/jobs` | List Jobs under an Organization | All roles |
| POST | `/orgs/{id}/employees` | Create an Employee under an org | CompManager, HRDirector |
| GET | `/employees/{id}` | Get an Employee | All roles |
| GET | `/employees` | List Employees (filtered) | All roles |
| GET | `/orgs/{id}/employees` | List Employees under an Organization | All roles |
| GET | `/jobs/{id}/employees` | List Employees assigned to a Job | All roles |
| POST | `/orgs/{id}/vendors` | Create a SurveyVendor (DRAFT) under an org | VendorAdmin |
| GET | `/vendors/{id}` | Get a SurveyVendor | All roles |
| GET | `/vendors` | List SurveyVendors (filtered) | All roles |
| GET | `/orgs/{id}/vendors` | List Vendors under an Organization | All roles |
| POST | `/vendors/{id}/activate` | Activate a vendor | VendorAdmin |
| POST | `/vendors/{id}/terminate` | Terminate a vendor | VendorAdmin |
| POST | `/vendors/{id}/surveys` | Create a Survey (DRAFT) under a vendor | VendorAdmin |
| GET | `/surveys/{id}` | Get a Survey | All roles |
| GET | `/surveys` | List Surveys (filtered) | All roles |
| GET | `/vendors/{id}/surveys` | List Surveys under a Vendor | All roles |
| GET | `/orgs/{id}/surveys` | List Surveys under an Organization | All roles |
| POST | `/surveys/{id}/open` | Open a Survey for submissions | VendorAdmin |
| POST | `/surveys/{id}/close` | Close a Survey; auto-transitions to SUBMITTED or REJECTED | VendorAdmin |
| POST | `/surveys/{id}/accept` | Vendor accepts a SUBMITTED survey; cascades to submissions | VendorAdmin |
| POST | `/surveys/{id}/reject` | Vendor rejects a SUBMITTED survey | VendorAdmin |
| POST | `/surveys/{id}/benchmarks` | Create a SurveyBenchmark under a survey | VendorAdmin |
| GET | `/benchmarks/{id}` | Get a SurveyBenchmark | All roles |
| GET | `/benchmarks` | List SurveyBenchmarks (filtered) | All roles |
| GET | `/surveys/{id}/benchmarks` | List Benchmarks under a Survey | All roles |
| POST | `/surveys/{id}/submissions` | Create a SurveySubmission (DRAFT) under a survey | CompAnalyst |
| GET | `/submissions/{id}` | Get a SurveySubmission | All roles |
| GET | `/submissions` | List SurveySubmissions (filtered) | All roles |
| GET | `/surveys/{id}/submissions` | List Submissions under a Survey | All roles |
| GET | `/employees/{id}/submissions` | List Submissions prepared by an Employee | All roles |
| POST | `/submissions/{id}/mark_ready` | Mark submission READY | CompAnalyst |
| POST | `/submissions/{id}/submit` | Submit a READY submission to the vendor | CompAnalyst |
| POST | `/submissions/{id}/accept` | Vendor accepts a submission | VendorAdmin |
| POST | `/submissions/{id}/return` | Vendor returns a submission for rework | VendorAdmin |
| POST | `/submissions/{id}/rework` | Re-open a RETURNED submission as DRAFT | CompAnalyst |
| POST | `/surveys/{id}/matches` | Propose a SurveyJobMatch (PROPOSED) under a survey | CompAnalyst |
| GET | `/matches/{id}` | Get a SurveyJobMatch | All roles |
| GET | `/matches` | List SurveyJobMatches (filtered) | All roles |
| GET | `/surveys/{id}/matches` | List Matches under a Survey | All roles |
| GET | `/jobs/{id}/matches` | List Matches that reference a Job | All roles |
| POST | `/matches/{id}/review` | Manager reviews a PROPOSED match | CompManager |
| POST | `/matches/{id}/approve` | Manager approves a REVIEWED match (SoD enforced) | CompManager |
| POST | `/matches/{id}/reject` | Manager rejects a REVIEWED match | CompManager |
| POST | `/matches/{id}/revise` | Analyst sends a REVIEWED or REJECTED match back to PROPOSED | CompAnalyst |
| POST | `/jobs/{id}/composites` | Create a MarketComposite (DRAFT) under a job | CompManager |
| GET | `/composites/{id}` | Get a MarketComposite | All roles |
| GET | `/composites` | List MarketComposites (filtered) | All roles |
| GET | `/jobs/{id}/composites` | List Composites under a Job | All roles |
| GET | `/strategies/{id}/composites` | List Composites that reference a Strategy | All roles |
| POST | `/composites/{id}/recompute` | Recompute blended percentiles (aging → geo → industry → blend) | CompManager |
| POST | `/composites/{id}/publish` | Publish a DRAFT composite; supersedes the prior PUBLISHED one | CompManager |
| POST | `/orgs/{id}/cycles` | Create a MarketAdjustmentCycle (OPEN) under an org | CompManager |
| GET | `/cycles/{id}` | Get a MarketAdjustmentCycle | All roles |
| GET | `/cycles` | List MarketAdjustmentCycles (filtered) | All roles |
| GET | `/orgs/{id}/cycles` | List Cycles under an Organization | All roles |
| POST | `/cycles/{id}/lock` | Lock an OPEN cycle | CompManager |
| POST | `/cycles/{id}/unlock` | Unlock a LOCKED cycle | CompManager |
| POST | `/cycles/{id}/close` | Close a LOCKED cycle | CompManager |
| POST | `/cycles/{id}/adjustments` | Create a MarketAdjustment (DRAFT) under a cycle | CompAnalyst |
| GET | `/adjustments/{id}` | Get a MarketAdjustment | All roles |
| GET | `/adjustments` | List MarketAdjustments (filtered) | All roles |
| GET | `/cycles/{id}/adjustments` | List Adjustments under a Cycle | All roles |
| GET | `/employees/{id}/adjustments` | List Adjustments targeting an Employee | All roles |
| GET | `/jobs/{id}/adjustments` | List Adjustments referencing a Job | All roles |
| POST | `/adjustments/{id}/submit` | Submit a DRAFT adjustment for approval | CompAnalyst |
| POST | `/adjustments/{id}/approve` | Manager approves a PENDING_APPROVAL adjustment (SoD + budget + OCC) | CompManager |
| POST | `/adjustments/{id}/reject` | Manager rejects a PENDING_APPROVAL adjustment | CompManager |
| POST | `/adjustments/{id}/retract` | Analyst retracts a PENDING_APPROVAL adjustment (proposer only) | CompAnalyst |
| POST | `/adjustments/{id}/apply` | Apply an APPROVED adjustment to the employee's salary | CompManager |
| POST | `/orgs/{id}/reports` | Create a CompensationReport (DRAFT) under an org | CompManager |
| GET | `/reports/{id}` | Get a CompensationReport | All roles |
| GET | `/reports` | List CompensationReports (filtered) | All roles |
| GET | `/orgs/{id}/reports` | List Reports under an Organization | All roles |
| POST | `/reports/{id}/finalize` | Finalize a DRAFT report — computes the snapshot | CompManager |
| POST | `/reports/{id}/present` | Present a FINALIZED report to the committee | HRDirector |
| GET | `/audit_events/{id}` | Get an AuditEvent | All roles |
| GET | `/audit_events` | List AuditEvents (filtered) | All roles |
| GET | `/orgs/{id}/audit_events` | List AuditEvents under an Organization | All roles |
| POST | `/_clock/set_current_utc` | Set the logical clock to an ISO 8601 instant | VendorAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only identifiers and status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 409 Conflict |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_VENDOR_SCOPE_FORBIDS_SUBMISSION` | 409 Conflict |
| `ERR_VENDOR_CONTRACT_WINDOW` | 409 Conflict |
| `ERR_VENDOR_HAS_OPEN_SUBMISSIONS` | 409 Conflict |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SURVEY_NOT_OPEN` | 409 Conflict |
| `ERR_SUBMISSIONS_PENDING` | 409 Conflict |
| `ERR_EMPTY_SUBMISSION` | 422 Unprocessable Entity |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_SAMPLE_SIZE_TOO_SMALL` | 409 Conflict |
| `ERR_INVALID_WEIGHT` | 422 Unprocessable Entity |
| `ERR_NO_SOURCES` | 409 Conflict |
| `ERR_ALREADY_PUBLISHED` | 409 Conflict |
| `ERR_GEO_INDEX_MISSING` | 422 Unprocessable Entity |
| `ERR_MIXED_STRATEGY_SOURCES` | 409 Conflict |
| `ERR_STRATEGY_NOT_ACTIVE` | 409 Conflict |
| `ERR_STRATEGY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CYCLE_EFFECTIVE_OVERLAP` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_CYCLE_NOT_LOCKED` | 409 Conflict |
| `ERR_CYCLE_HAS_PENDING` | 409 Conflict |
| `ERR_CYCLE_HAS_UNAPPLIED` | 409 Conflict |
| `ERR_NO_PUBLISHED_COMPOSITE` | 409 Conflict |
| `ERR_ADJUSTMENT_NOT_YET_EFFECTIVE` | 409 Conflict |
