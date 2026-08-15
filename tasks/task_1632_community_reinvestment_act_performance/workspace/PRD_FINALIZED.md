# CRA Performance Management API — Product Requirements Document

## 1. Introduction

The Community Reinvestment Act obligates every insured bank to help meet the credit needs of the communities it serves, expressly including low- and moderate-income neighborhoods, and it arms regulators with a periodic examination that rates that performance. The rating is anything but ceremonial: a weak composite rating can freeze branch openings, mergers, and other expansion applications, while a strong one clears the regulatory path. Banks therefore manage CRA performance as a continuous discipline rather than an exam-season scramble — delineating assessment areas, building demographic baselines, tracking lending penetration, qualifying community development activity, watching branch distribution, and keeping an immaculate public file.

This document specifies the CRA Performance Management API, the system a bank's CRA office uses to run that discipline day to day. It covers assessment-area delineation and census demographics, small business and small farm loan data collection, community development qualification under segregation of duties, branch lifecycle and access analysis, public file maintenance and public comment handling, the full examination cycle from scheduling through appeal and finalization, and the gate that an adverse rating places on expansion applications. Six roles share the workload — the bank's CRA officer, its compliance analysts, an independent qualification reviewer, the regulatory examiner, bank executives, and a platform administrator — and the system enforces a hard wall between those who submit data and those who judge it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. Exactly six roles are recognized: `CRAOfficer`, `ComplianceAnalyst`, `QualificationReviewer`, `BankExaminer`, `BankExecutive`, and `PlatformAdmin`. A request that is missing either header, or whose role value is not one of these six, is rejected with `ERR_UNAUTHENTICATED`. A properly authenticated request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`. All read endpoints are open to every role; write endpoints are restricted as summarized in §4.

For every one of these roles — `CRAOfficer`, `ComplianceAnalyst`, `QualificationReviewer`, `BankExaminer`, `BankExecutive`, and `PlatformAdmin` alike — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it, for example as `submitted_by_user_id` on a community development activity at submission time or as `reviewed_by_user_id` when a qualification decision is rendered, but it never compares `X-User-ID` against any entity's `id`. The single place a recorded identifier is later consulted is the segregation-of-duties check described in §3.4, which compares the incoming header against a value the server itself recorded earlier.

Responsibilities divide cleanly across the six roles. The `CRAOfficer` owns delineation and demographics, the public file, public comment handling, the performance context narrative, and exam appeals. The `ComplianceAnalyst` records loan data and submits community development documentation. The `QualificationReviewer` renders qualification decisions and is deliberately walled off from submission. The `BankExaminer` drives the examination lifecycle, assigns ratings, and decides expansion applications. The `BankExecutive` files expansion applications and operates the branch network. The `PlatformAdmin` alone drives the logical clock described in §2.5.

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

List endpoints paginate through two query parameters. The `limit` parameter caps how many items a response returns; it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

All nine resource types in this system — assessment areas, demographic profiles, loan records, community development activities, branches, public comments, the public file, exam cycles, and expansion applications — share a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed whenever any property of the resource changes.
- `version` (integer): an optimistic-concurrency counter that starts at 1 when the resource is created and increments by one on every mutation, including mutations driven by automatic cascades rather than a direct client write.

### 2.5. The Logical Clock

All date arithmetic in the system reads a single logical clock, never the host's wall clock. At server startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to wall-clock time. Retirement dates, branch opening and closing dates, comment receipt timestamps, the 90-day closure notice window, and the trailing twelve-month closure window all derive from this clock.

A platform-admin-only capability advances the logical clock to a supplied `to_iso8601` instant; the response echoes the new value as `current_utc`. Only the `PlatformAdmin` role may invoke it.

### 2.6. Nested Resource Retrieval and Existence Ordering

Requests that target resources beneath another resource are validated strictly left to right along the path. The server resolves each path-template identifier in sequence and rejects the request at the first identifier that does not resolve, returning that segment's not-found error: `ERR_ASSESSMENT_AREA_NOT_FOUND` for an assessment area segment, `ERR_LOAN_RECORD_NOT_FOUND` for a loan record, `ERR_ACTIVITY_NOT_FOUND` for a community development activity, `ERR_BRANCH_NOT_FOUND` for a branch, `ERR_PUBLIC_COMMENT_NOT_FOUND` for a public comment, `ERR_PUBLIC_FILE_NOT_FOUND` for the public file, `ERR_EXAM_CYCLE_NOT_FOUND` for an exam cycle, and `ERR_APPLICATION_NOT_FOUND` for an expansion application. A request to list loan records beneath a non-existent assessment area therefore fails with `ERR_ASSESSMENT_AREA_NOT_FOUND` before any loan lookup is even attempted.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the parent assessment area: editing an assessment area's mutable fields, and creating a demographic profile beneath an area. Both requests must carry `expected_assessment_area_version` as a non-optional input field holding the `version` of the area the client most recently observed. When the supplied value no longer matches the area's current `version` — because any intervening area mutation has advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the area and retry on fresh state. No other endpoint accepts a version field.

### 2.8. Monetary Precision and Rounding Conventions

Monetary amounts are represented as integer cents in fields whose names end in `_cents`. Derived ratios — `lmi_population_pct`, `lmi_tract_pct`, `lmi_branch_pct`, and the lending-metric percentages of §3.9 — are rounded half up to four decimal places. Scores and weighted aggregates that carry two-decimal precision, namely `composite_points` and `access_score`, are rounded half up to two decimal places. Qualified community development amounts are whole cents, rounded half up. Where a division would have a zero denominator, the derived percentage is defined as 0 rather than an error; the specific rules appear with each calculation in §3.

### 2.9. Delineation Integrity: Tracts, Periods, and Metropolitan Scoping

Assessment-area delineations obey three integrity rules that hold across the whole system.

First, `area_code` is unique across all assessment areas; an attempt to create an area with an `area_code` that already exists is rejected with `ERR_DUPLICATE_AREA_CODE`.

Second, effective periods may not collide within a metropolitan statistical area. Each area's effective window is half-open: it begins at `effective_start_date` (inclusive) and ends at `effective_end_date` (exclusive). A retired area closes its window at its recorded `effective_end_date`; an area that has not been retired is open-ended. A newly created area's window may not intersect the window of any other area sharing the same `msa_code`; a violation is rejected with `ERR_AREA_PERIOD_OVERLAP`. Adjacency is permitted — a new area whose `effective_start_date` equals another same-`msa_code` area's `effective_end_date` does not overlap it.

Third, census tract exclusivity holds over the live delineations: no census tract may appear in the `census_tracts` of two areas whose status is `ACTIVE` or `UNDER_REVIEW`. The check runs at activation, at review completion, and whenever the tracts of an `UNDER_REVIEW` area are edited, and a violation is rejected with `ERR_TRACT_OVERLAP`. A `DRAFT` area stands outside the constrained set: creating one, or editing a `DRAFT` area's tracts, is never rejected for tract overlap even when a tract collides with an `ACTIVE` or `UNDER_REVIEW` area — the collision is rejected when the `DRAFT` area is later activated. Tracts may only be edited while an area is `DRAFT` or `UNDER_REVIEW`, and the tract list must be non-empty at both activation moments — an empty `census_tracts` at activation or review completion is rejected with `ERR_VALIDATION`.

### 2.10. Public File Posture as the Examination Gate

The public file is a singleton with a derived `posture`. The posture is `COMPLETE` exactly when `branch_list_current` and `aa_list_current` and `disclosure_statement_present` are all true and `pending_comment_count` is zero; otherwise it is `INCOMPLETE`.

Freshness decays automatically as the bank's footprint changes. Opening or closing a branch sets `branch_list_current` to false. Activating an area, completing an area review, or retiring an area sets `aa_list_current` to false. Recording a new public comment increments `pending_comment_count` by one, and publishing a comment decrements it by one. Every one of these cascades recomputes the posture immediately. Because examination fieldwork cannot begin unless the file exists and its posture is `COMPLETE` (§3.7), any of these routine events can close the examination gate until the file is refreshed.

### 2.11. Validation Ordering

When several rules could reject the same request, the server evaluates them in a fixed tier order so that the surfaced error is deterministic:

1. Authentication — missing or undeclared headers yield `ERR_UNAUTHENTICATED`.
2. Authorization — a role not permitted for the endpoint yields `ERR_FORBIDDEN`.
3. Existence and request shape — path identifiers are resolved left to right (their 404 codes per §2.6), and at the same tier malformed bodies, missing required fields, invalid enum values, non-positive amounts, an `lmi_benefit_pct` outside the inclusive range 0 to 1, or an `lmi_population` exceeding `total_population` yield `ERR_VALIDATION`.
4. State legality — a trigger that does not match the resource's current state, or any action on a terminal-state resource, yields `ERR_INVALID_STATE`.
5. Business safety — segregation of duties, the public-file gate, and the expansion rating guard.
6. Business constraint — uniqueness and overlap conflicts, the singleton public file, and the full-count LMI threshold.
7. Business temporal — evaluation-window ordering and the closure-notice period.
8. Business referential — the referenced area must be `ACTIVE`, the loan's tract must belong to the area, and a staged branch's application must be `APPROVED`.
9. Business fiscal — the annual community development budget cap.

The practical consequence is worth an example: on a qualification review, segregation of duties is evaluated before the LMI benefit threshold, which precedes the area-active requirement, which in turn precedes the budget headroom check — a reviewer who submitted the activity themselves will always see `ERR_SEGREGATION_OF_DUTIES` rather than a later check's error.

## 3. Business Logic & Workflows

### 3.1. Delineating and Maintaining Assessment Areas

A `CRAOfficer` delineates an assessment area by supplying an `area_code`, a display `name`, the `msa_code` of the metropolitan statistical area the area sits in, a two-letter `state_code`, the `census_tracts` array that delineates the geography, the `effective_start_date` on which the delineation takes effect, and an `annual_cd_budget_cents` budget — a non-negative integer of cents that caps the community development amounts qualified against the area per calendar year (§3.4). The new area starts in `DRAFT` status with `version` 1, a null `effective_end_date`, and both computed counters — `confirmed_loan_count` and `qualified_cd_total_cents` — at zero.

While an area is `DRAFT` or `UNDER_REVIEW`, the officer may edit its `name` and/or its `census_tracts`; the edit is one of the two OCC-guarded writes of §2.7 and so must carry `expected_assessment_area_version` matching the area's current `version`, failing with `ERR_STALE_VERSION` when it does not. Editing the tracts of an `UNDER_REVIEW` area re-runs the exclusivity check of §2.9, while editing the tracts of a `DRAFT` area does not — a collision there is tolerated until activation — and an edit attempted while the area is `ACTIVE` or `RETIRED` is rejected with `ERR_INVALID_STATE`.

Activation moves the area from `DRAFT` to `ACTIVE`. It requires a non-empty `census_tracts` (an empty list is `ERR_VALIDATION`) and re-verifies that no tract collides with another `ACTIVE` or `UNDER_REVIEW` area (`ERR_TRACT_OVERLAP`). From `ACTIVE`, the officer may move the area to `UNDER_REVIEW` to rework a delineation, and completing that review returns it from `UNDER_REVIEW` to `ACTIVE` subject to the same two checks as activation — the review loop `ACTIVE → UNDER_REVIEW → ACTIVE` may repeat indefinitely. Retiring moves an `ACTIVE` area to `RETIRED`, stamping `effective_end_date` with the logical-clock date as the exclusive end of its window; `RETIRED` is terminal. Activation, review completion, and retirement each invalidate the public file's assessment-area list per §2.10, and every transition increments the area's `version` by one and refreshes `updated_at`.

### 3.2. Demographic Profiles and Census Data Vintages

Against any assessment area, a `CRAOfficer` posts demographic profiles, one vintage per census data year. Each profile carries `data_year`, `total_tracts`, `low_income_tracts`, `moderate_income_tracts`, `total_population`, `lmi_population`, and `median_family_income` in whole dollars — all non-negative integers, with `lmi_population` never exceeding `total_population` (a violation is `ERR_VALIDATION`).

Two percentages are computed at creation. `lmi_population_pct` is the ratio of `lmi_population` to `total_population`, rounded half up to four decimal places, and is 0 when `total_population` is zero. `lmi_tract_pct` is the ratio of the sum of `low_income_tracts` and `moderate_income_tracts` to `total_tracts`, rounded half up to four decimal places, and is 0 when `total_tracts` is zero.

A new profile starts as `CURRENT`. Vintages supersede narrowly: posting a profile whose (`assessment_area_id`, `data_year`) pair matches an existing `CURRENT` profile retires that earlier profile to `SUPERSEDED` — a terminal state — while profiles of different `data_year` vintages for the same area coexist as `CURRENT`. The list of an area's profiles returns both `CURRENT` and `SUPERSEDED` entries and may be filtered by `status` and `data_year`.

Profile creation is the second OCC-guarded write of §2.7: the request must carry `expected_assessment_area_version` equal to the area's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful creation itself mutates the area — its `version` increments by one — so a second profile creation that still carries the earlier expected version is stale and must re-read the area before retrying.

### 3.3. Recording Small Business and Small Farm Lending

`ComplianceAnalyst` operators build the lending dataset one loan at a time. Recording a loan requires the `assessment_area_id` it was booked in, a `loan_type` of `SMALL_BUSINESS` or `SMALL_FARM`, the `loan_amount_cents` (strictly positive), the `borrower_gross_annual_revenue_cents` (non-negative), the `action_date` of origination, the borrower's `census_tract`, and that tract's `tract_income_level` — one of `LOW`, `MODERATE`, `MIDDLE`, or `UPPER`. The record starts in `DRAFT`.

Four derived fields decorate every loan record. `reporting_year` is the four-digit calendar year of `action_date`. `small_revenue_flag` is true exactly when `borrower_gross_annual_revenue_cents` is at or below one million dollars of gross annual revenue, the threshold being inclusive. `lmi_geography_flag` is true exactly when `tract_income_level` is `LOW` or `MODERATE`. `inside_assessment_area` is live-derived at read time — it reflects whether the record's `census_tract` is currently an element of the referenced area's `census_tracts`, so a later delineation edit can flip it without touching the loan.

Confirmation moves a record from `DRAFT` to `CONFIRMED` and is guarded by two referential checks, evaluated in this order: the referenced area must be `ACTIVE` (else `ERR_AREA_NOT_ACTIVE`), and the record's `census_tract` must be an element of that area's `census_tracts` (else `ERR_TRACT_NOT_IN_AREA`). Confirming raises the area's `confirmed_loan_count` by one; the count covers loans in `CONFIRMED` and `REPORTED` alike. Returning a record from `CONFIRMED` to `DRAFT` lowers the count by one, and the correction loop `CONFIRMED → DRAFT → CONFIRMED` may repeat as often as needed. Marking a `CONFIRMED` record as reported moves it to `REPORTED` — the terminal state that places the loan on the CRA register — and leaves the count unchanged, since a reported loan still counts. Every transition increments the record's `version` by one. An area's loan list may be filtered by `status`, `reporting_year`, and `loan_type`.

### 3.4. Community Development Qualification Review

Community development work enters the system through a `ComplianceAnalyst`, who submits an activity with its `assessment_area_id`, an `activity_type` of `CD_LOAN`, `QUALIFIED_INVESTMENT`, or `CD_SERVICE`, the `amount_cents` (strictly positive — the dollar value of services counts too), a `primary_purpose_category` of `AFFORDABLE_HOUSING`, `COMMUNITY_SERVICES_LMI`, `ECONOMIC_DEVELOPMENT`, or `REVITALIZATION_STABILIZATION`, the `lmi_benefit_pct` share of benefit flowing to LMI persons or geographies as a number from 0 to 1 inclusive, and the `activity_date` on which the activity was funded or performed. The activity starts as `SUBMITTED`; the server records the submitter's header value into `submitted_by_user_id`, while `reviewed_by_user_id`, `disqualify_reason`, and `allocation_method` remain null and `qualified_amount_cents` remains 0.

Decisions belong to a `QualificationReviewer`, who renders a review decision carrying a `decision` of `QUALIFY` or `DISQUALIFY`. The guards run in the fixed order of §2.11 — segregation of duties first (a reviewer whose `X-User-ID` equals the activity's `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`), then the full-count benefit threshold, then the area-active requirement, and finally the budget check — so a self-review attempt surfaces before any substantive defect, and a budget overflow is never masked by a stale-area rejection.

A qualifying decision names an `allocation_method`. Under `FULL_COUNT`, permitted only when `lmi_benefit_pct` is at least 0.51 (otherwise `ERR_LMI_THRESHOLD_NOT_MET`), the entire `amount_cents` counts as qualified. Under `PRO_RATA`, always permitted, only the LMI-benefit share counts: `qualified_amount_cents` is `amount_cents` multiplied by `lmi_benefit_pct`, rounded half up to whole cents — so identical inputs yield a strictly smaller qualified amount under `PRO_RATA` whenever `lmi_benefit_pct` lies strictly between 0 and 1. Qualification also requires the referenced area to be `ACTIVE` (`ERR_AREA_NOT_ACTIVE`), and the calendar year of `activity_date` scopes the budget cap: the sum of `qualified_amount_cents` over the area's `QUALIFIED` activities whose `activity_date` falls in that same calendar year, plus this activity's `qualified_amount_cents`, must not exceed the area's `annual_cd_budget_cents` (`ERR_CD_BUDGET_EXCEEDED`). A successful qualification records `reviewed_by_user_id` and the `allocation_method`, computes `qualified_amount_cents`, recomputes the area's `qualified_cd_total_cents` — the all-years sum of qualified amounts over the area's `QUALIFIED` activities — and increments the activity's `version`.

A disqualifying decision instead records the reviewer's `disqualify_reason` and `reviewed_by_user_id` and moves the activity to `DISQUALIFIED`; segregation of duties still applies. Disqualification is not the end: a `ComplianceAnalyst` may resubmit a `DISQUALIFIED` activity, provided the referenced area is `ACTIVE` (`ERR_AREA_NOT_ACTIVE`), which returns it to `SUBMITTED` while clearing `disqualify_reason`, `reviewed_by_user_id`, and `allocation_method` to null and resetting `qualified_amount_cents` to 0. The resubmission loop `DISQUALIFIED → SUBMITTED → QUALIFIED` or `DISQUALIFIED` may repeat indefinitely — the activity has no terminal state. An area's activity list may be filtered by `status` and `activity_type`.

### 3.5. Branch Network Stewardship

A branch enters the system in one of two ways. A `BankExecutive` may create one directly, supplying a `branch_code`, the `assessment_area_id` it operates in, its site's `census_tract`, and the tract's `tract_income_level`; such a branch has a null `expansion_application_id`. Alternatively, a branch-opening expansion application stages one automatically at submission (§3.8), stamped with the application's id. Either way, `branch_code` is unique across all branches and the branch starts as `PROPOSED`.

Opening moves a branch from `PROPOSED` to `OPEN`. When the branch carries a non-null `expansion_application_id`, the referenced application must already be `APPROVED` — opening against an undecided or denied application is rejected with `ERR_APPLICATION_NOT_APPROVED` — while a directly created branch faces no such check. Opening stamps `opened_date` with the logical-clock date, invalidates the public file's branch list per §2.10, and increments the branch's `version`.

Closing requires public notice. The close request carries the `notice_posted_date` on which the bank posted its public closure notice, and at least 90 days must separate that date from the logical-clock date — fewer is rejected with `ERR_CLOSURE_NOTICE_SHORT`. A valid close stamps both `closed_date` and `notice_posted_date`, flips the public file's `branch_list_current` to false with the usual posture recompute, and increments `version`. `CLOSED` is terminal.

The fourth state is system-driven: when an expansion application is denied — by examiner decision or by the finalize cascade of §3.7 — its staged branch moves from `PROPOSED` to `WITHDRAWN`, also terminal, with its `version` incremented. An area's branch list may be filtered by `status` and `tract_income_level`.

### 3.6. The Public File and Public Comment Handling

A `CRAOfficer` creates the CRA public file by supplying the bank's legal `bank_name`. Only one may exist; a second attempt is rejected with `ERR_PUBLIC_FILE_EXISTS`. The file is born with `branch_list_current` and `aa_list_current` true, `disclosure_statement_present` false, and `pending_comment_count` zero — which, under the posture rule of §2.10, means it starts `INCOMPLETE` until the disclosure statement is placed.

Refreshing the file is deliberately conservative. The refresh accepts three optional flags — `branch_list`, `aa_list`, and `disclosure_statement` — and only an explicit true value takes effect; an omitted or false flag leaves the corresponding state untouched. Posture is recomputed after every refresh, and the file's `version` increments by one when any flag actually changes.

Public comments arrive through either a `CRAOfficer` or a `ComplianceAnalyst`, who records the `commenter_name`, the `channel` — `WRITTEN_LETTER`, `EMAIL`, or `PUBLIC_MEETING` — the `subject_area` of `LENDING`, `INVESTMENT`, `SERVICE`, `BRANCH_ACCESS`, or `OTHER`, and the verbatim `content`. The comment starts as `RECEIVED` with `received_at` stamped from the logical clock, and its arrival increments the file's `pending_comment_count` by one with the usual posture recompute. Publishing moves a comment from `RECEIVED` to `PUBLISHED`, decrementing `pending_comment_count` by one; responding moves it from `PUBLISHED` to `RESPONDED` — terminal — recording the bank's `response_text`. Each transition increments the comment's `version`.

### 3.7. The Examination Cycle: From Scheduling to Final Rating

A `BankExaminer` schedules an examination by declaring an `exam_type` of `LARGE_BANK` or `INTERMEDIATE_SMALL_BANK` and a closed evaluation window from `evaluation_window_start` through `evaluation_window_end`, optionally seeding the `performance_context_narrative` (it defaults to an empty string). Two temporal rules guard scheduling, applied in the global order of §2.11 — meaning the overlap conflict surfaces before the window-shape problem. Evaluation windows are closed intervals, so no exam's window may share even a single calendar date with any other exam's window regardless of that exam's status; touching endpoints conflict, and a violation is `ERR_EXAM_WINDOW_OVERLAP`. Independently, `evaluation_window_end` must be on or after `evaluation_window_start`, else `ERR_INVALID_WINDOW`. A valid exam starts as `SCHEDULED`.

The narrative stays editable through the early phases: while the exam is `SCHEDULED`, `DATA_COLLECTION`, or `FIELDWORK`, a `CRAOfficer` may replace the `performance_context_narrative`, incrementing the exam's `version`; once the exam has moved past fieldwork the edit is rejected with `ERR_INVALID_STATE`.

Progression is examiner-driven. Beginning data collection moves `SCHEDULED → DATA_COLLECTION`. Beginning fieldwork moves `DATA_COLLECTION → FIELDWORK` and is gated on the public file: the singleton file must exist and its `posture` must be `COMPLETE`, otherwise the request fails with `ERR_PUBLIC_FILE_INCOMPLETE` — this is where the decay cascades of §2.10 bite. Assigning the preliminary rating moves `FIELDWORK → PRELIMINARY_RATING`; the examiner supplies `lending_test_rating`, `investment_test_rating`, and `service_test_rating`, each one of `OUTSTANDING`, `SATISFACTORY`, `NEEDS_TO_IMPROVE`, or `SUBSTANTIAL_NONCOMPLIANCE`, and the composite is computed immediately.

The composite maps ratings to points — `OUTSTANDING` 10, `SATISFACTORY` 6, `NEEDS_TO_IMPROVE` 2, `SUBSTANTIAL_NONCOMPLIANCE` 0 — and weights lending at one half with investment and service at one quarter each: `composite_points` is one half of the lending points plus one quarter of the investment points plus one quarter of the service points, rounded half up to two decimal places. The `composite_rating` bands are inclusive at their lower boundaries: at least 8.50 is `OUTSTANDING`, at least 5.00 is `SATISFACTORY`, at least 2.50 is `NEEDS_TO_IMPROVE`, and anything below is `SUBSTANTIAL_NONCOMPLIANCE`.

A bank that disputes the preliminary outcome may appeal: a `CRAOfficer` moves the exam from `PRELIMINARY_RATING` to `APPEALED` with a recorded `appeal_reason`, and the examiner may later reopen fieldwork, moving `APPEALED → FIELDWORK`. The appeal cycle `PRELIMINARY_RATING → APPEALED → FIELDWORK → PRELIMINARY_RATING` may repeat, and each fresh rating assignment recomputes the composite from the newly supplied test ratings.

Finalization moves `PRELIMINARY_RATING → FINALIZED`, the terminal state. When the finalized `composite_rating` is `NEEDS_TO_IMPROVE` or `SUBSTANTIAL_NONCOMPLIANCE`, the rating cascades outward in a three-deep chain: every expansion application sitting in `SUBMITTED` flips to `DENIED` with `decision_reason` recorded as `RATING_BLOCK`, and each such application whose `linked_branch_id` is non-null drags its staged branch from `PROPOSED` to `WITHDRAWN`. Favorable ratings finalize with no cascade. Every exam transition increments the exam's `version` by one.

### 3.8. Expansion Applications and the Rating Gate

A `BankExecutive` drafts an expansion application with an `application_type` of `BRANCH_OPENING`, `BRANCH_CLOSURE`, or `MERGER` and a `target_assessment_area_id`. A branch opening additionally requires `branch_code`, `branch_census_tract`, and `branch_tract_income_level` — omitting any of them for that type is a missing-field `ERR_VALIDATION`. The draft starts in `DRAFT` with `linked_branch_id` and `decision_reason` null.

Submission moves the application from `DRAFT` to `SUBMITTED` and is where the bank's CRA track record binds. When any exam cycle has reached `FINALIZED`, the latest of them — the one with the maximum `evaluation_window_end`, with ties broken by the latest `created_at` — must carry a `composite_rating` of `OUTSTANDING` or `SATISFACTORY`; a latest finalized rating of `NEEDS_TO_IMPROVE` or `SUBSTANTIAL_NONCOMPLIANCE` rejects the submission with `ERR_RATING_BLOCKS_EXPANSION`. With no finalized exam on record the guard does not engage. A successful submission of a `BRANCH_OPENING` application also stages the physical branch: a new branch is created in `PROPOSED` with `branch_code`, `census_tract`, `tract_income_level`, and `assessment_area_id` copied from the application's `branch_code`, `branch_census_tract`, `branch_tract_income_level`, and `target_assessment_area_id`, its `expansion_application_id` pointing back at the application, and the application's `linked_branch_id` set to the new branch's `id`. The application's staged-branch list therefore returns at most one element. Submission increments the application's `version`.

Decisions rest with the `BankExaminer`, who renders a `decision` of `APPROVE` or `DENY` with an optional `decision_reason`. Approval moves the application to `APPROVED`; denial moves it to `DENIED` and, when `linked_branch_id` is non-null and that branch is still `PROPOSED`, withdraws the branch to `WITHDRAWN`. Both outcomes are terminal, both record `decision_reason`, and each increments `version`. An area's application list may be filtered by `status` and `application_type`.

### 3.9. Lending Metrics, Register Totals, and Branch Access Analysis

Three computed reads serve the examination; none of them mutates state.

The lending-metrics read answers how the bank's lending penetrates its communities over an exam's evaluation window. The window is the closed interval from `evaluation_window_start` through `evaluation_window_end` matched on each loan's `action_date`, and an optional `basis` selector chooses the population: `CURRENT`, the default and the examiner's working view, includes loans in `CONFIRMED` and `REPORTED`; `SNAPSHOT`, the as-reported register view used for the official submission, includes only `REPORTED`. Whenever any in-window loan is `CONFIRMED` but not yet `REPORTED`, the two bases yield different denominators and different percentages. The response reports `loan_count` plus three penetration ratios — `inside_aa_pct` counting loans whose `inside_assessment_area` is true, `lmi_geography_pct` counting `lmi_geography_flag`, and `lmi_borrower_pct` counting `small_revenue_flag` — each computed as its count divided by `loan_count`, rounded half up to four decimal places, and defined as 0 when `loan_count` is zero.

The same read carries the annual CRA register totals, `small_business_register_total_cents` and `small_farm_register_total_cents`, and their rounding order is pinned. For each `REPORTED` loan in the window, grouped by `loan_type`: first cap the loan's `loan_amount_cents` at one million dollars; then round each capped amount half up to the nearest multiple of one thousand dollars; then sum the per-loan rounded amounts within each type. Summing first and rounding the aggregate is expressly not permitted — the per-loan rounding happens before any addition.

The access-analysis read scores an area's branch distribution. It reports `open_branch_count`, the number of the area's branches in `OPEN`; with no open branches, `access_score` and `lmi_branch_pct` are both 0. Otherwise `lmi_branch_pct` is the share of open branches whose `tract_income_level` is `LOW` or `MODERATE`, rounded half up to four decimal places. The benchmark, `benchmark_lmi_tract_pct`, is the `lmi_tract_pct` of the area's `CURRENT` demographic profile with the latest `data_year`, or 0 when the area has no profile. `lmi_closures_12m` counts the area's branches that are `CLOSED`, sit in `LOW` or `MODERATE` tracts, and whose `closed_date` falls later than the date 365 days before the logical-clock date and on or before the logical-clock date. The raw score starts from a base of 50, adds 100 times the difference between `lmi_branch_pct` and the benchmark, and subtracts 5 points per closure counted in `lmi_closures_12m`; `access_score` is that raw value rounded half up to two decimal places and then clamped to a floor of 0 and a ceiling of 100.

## 4. Endpoint Definitions

All endpoints are mounted under the `/cra` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Successful responses return the created or updated resource — or, for the computed reads, the computed object — in the envelope's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cra/assessment-areas` | Create an assessment area in `DRAFT` | CRAOfficer |
| GET | `/cra/assessment-areas/{id}` | Read one assessment area | All roles |
| PATCH | `/cra/assessment-areas/{id}` | Edit `name` and/or `census_tracts` while `DRAFT` or `UNDER_REVIEW`; OCC-guarded | CRAOfficer |
| POST | `/cra/assessment-areas/{id}/activate` | Move `DRAFT → ACTIVE` | CRAOfficer |
| POST | `/cra/assessment-areas/{id}/begin-review` | Move `ACTIVE → UNDER_REVIEW` | CRAOfficer |
| POST | `/cra/assessment-areas/{id}/complete-review` | Move `UNDER_REVIEW → ACTIVE` | CRAOfficer |
| POST | `/cra/assessment-areas/{id}/retire` | Move `ACTIVE → RETIRED`; stamps `effective_end_date` | CRAOfficer |
| POST | `/cra/assessment-areas/{id}/demographic-profiles` | Create a demographic profile; same-vintage supersedes; OCC-guarded on the area | CRAOfficer |
| GET | `/cra/assessment-areas/{id}/demographic-profiles` | List an area's profiles, both `CURRENT` and `SUPERSEDED` | All roles |
| GET | `/cra/assessment-areas/{id}/access-analysis` | Computed branch distribution and access score for the area | All roles |
| GET | `/cra/assessment-areas/{id}/loan-records` | List an area's loan records | All roles |
| GET | `/cra/assessment-areas/{id}/community-development-activities` | List an area's community development activities | All roles |
| GET | `/cra/assessment-areas/{id}/branches` | List an area's branches | All roles |
| GET | `/cra/assessment-areas/{id}/expansion-applications` | List expansion applications targeting an area | All roles |
| POST | `/cra/loan-records` | Record a small business or small farm loan in `DRAFT` | ComplianceAnalyst |
| GET | `/cra/loan-records/{id}` | Read one loan record | All roles |
| POST | `/cra/loan-records/{id}/confirm` | Move `DRAFT → CONFIRMED` | ComplianceAnalyst |
| POST | `/cra/loan-records/{id}/return-to-draft` | Move `CONFIRMED → DRAFT` (correction loop) | ComplianceAnalyst |
| POST | `/cra/loan-records/{id}/mark-reported` | Move `CONFIRMED → REPORTED` (onto the CRA register) | ComplianceAnalyst |
| POST | `/cra/community-development-activities` | Submit a community development activity as `SUBMITTED` | ComplianceAnalyst |
| POST | `/cra/community-development-activities/{id}/review-decision` | Qualify or disqualify a `SUBMITTED` activity | QualificationReviewer |
| POST | `/cra/community-development-activities/{id}/resubmit` | Move `DISQUALIFIED → SUBMITTED`, clearing review fields | ComplianceAnalyst |
| POST | `/cra/branches` | Directly create a branch in `PROPOSED`, untied to any application | BankExecutive |
| GET | `/cra/branches/{id}` | Read one branch | All roles |
| POST | `/cra/branches/{id}/open` | Move `PROPOSED → OPEN` | BankExecutive |
| POST | `/cra/branches/{id}/close` | Move `OPEN → CLOSED` subject to the 90-day notice check | BankExecutive |
| POST | `/cra/public-comments` | Record a received public comment as `RECEIVED` | CRAOfficer, ComplianceAnalyst |
| POST | `/cra/public-comments/{id}/publish` | Move `RECEIVED → PUBLISHED` (placed into the public file) | CRAOfficer |
| POST | `/cra/public-comments/{id}/respond` | Move `PUBLISHED → RESPONDED` with response text | CRAOfficer |
| POST | `/cra/public-files` | Create the singleton CRA public file | CRAOfficer |
| GET | `/cra/public-files/{id}` | Read the public file including `posture` | All roles |
| POST | `/cra/public-files/{id}/refresh-items` | Mark public-file checklist items current; posture recomputed | CRAOfficer |
| POST | `/cra/exam-cycles` | Schedule an exam in `SCHEDULED` with a non-overlapping closed window | BankExaminer |
| GET | `/cra/exam-cycles/{id}` | Read one exam cycle | All roles |
| PATCH | `/cra/exam-cycles/{id}/performance-context` | Update the performance context narrative during early phases | CRAOfficer |
| POST | `/cra/exam-cycles/{id}/begin-data-collection` | Move `SCHEDULED → DATA_COLLECTION` | BankExaminer |
| POST | `/cra/exam-cycles/{id}/begin-fieldwork` | Move `DATA_COLLECTION → FIELDWORK`; requires a `COMPLETE` public file | BankExaminer |
| POST | `/cra/exam-cycles/{id}/assign-preliminary-rating` | Move `FIELDWORK → PRELIMINARY_RATING`; computes the composite | BankExaminer |
| POST | `/cra/exam-cycles/{id}/appeal` | Move `PRELIMINARY_RATING → APPEALED` | CRAOfficer |
| POST | `/cra/exam-cycles/{id}/reopen-fieldwork` | Move `APPEALED → FIELDWORK` (appeal cycle) | BankExaminer |
| POST | `/cra/exam-cycles/{id}/finalize` | Move `PRELIMINARY_RATING → FINALIZED`; adverse composite cascades to applications and staged branches | BankExaminer |
| GET | `/cra/exam-cycles/{id}/lending-metrics` | Computed lending-test metrics and CRA register totals over the exam window | All roles |
| POST | `/cra/expansion-applications` | Draft an expansion application in `DRAFT` | BankExecutive |
| GET | `/cra/expansion-applications/{id}` | Read one expansion application | All roles |
| POST | `/cra/expansion-applications/{id}/submit` | Move `DRAFT → SUBMITTED`; rating guard applies; branch openings stage a `PROPOSED` branch | BankExecutive |
| POST | `/cra/expansion-applications/{id}/decide` | Move `SUBMITTED → APPROVED` or `DENIED` (regulator decision) | BankExaminer |
| GET | `/cra/expansion-applications/{id}/branches` | List branches staged by this application (zero or one element) | All roles |
| POST | `/cra/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_ASSESSMENT_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_ACTIVITY_NOT_FOUND` | 404 Not Found |
| `ERR_BRANCH_NOT_FOUND` | 404 Not Found |
| `ERR_PUBLIC_COMMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PUBLIC_FILE_NOT_FOUND` | 404 Not Found |
| `ERR_EXAM_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_AREA_CODE` | 409 Conflict |
| `ERR_AREA_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_TRACT_OVERLAP` | 409 Conflict |
| `ERR_EXAM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PUBLIC_FILE_EXISTS` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PUBLIC_FILE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_RATING_BLOCKS_EXPANSION` | 422 Unprocessable Entity |
| `ERR_LMI_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_AREA_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_TRACT_NOT_IN_AREA` | 422 Unprocessable Entity |
| `ERR_APPLICATION_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_CLOSURE_NOTICE_SHORT` | 422 Unprocessable Entity |
| `ERR_CD_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
