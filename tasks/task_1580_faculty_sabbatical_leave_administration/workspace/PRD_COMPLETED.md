# Faculty Sabbatical Leave API — Product Requirements Document

## 1. Introduction

Universities run sabbatical programs on trust backed by arithmetic: a faculty member earns eligibility month by month, a committee ranks proposals against a finite award quota, the home department must be able to afford replacement teaching, and the institution expects a defined period of return service — or its money back. Today these concerns typically live in disconnected spreadsheets, which makes it nearly impossible to answer simple questions reliably: Is this professor eligible yet? Can the department absorb one more leave this year? What does a departing faculty member owe, and how much has been repaid?

This document specifies a single REST API for faculty sabbatical and leave administration in a university academic-affairs setting. The service manages the entire lifecycle in one place: month-by-month service-credit accrual behind an append-only ledger, an application cycle with committee review and ranked allocation against a cycle award quota, replacement-coverage budgeting per department with a posture signal that throttles new commitments, salary and external-fellowship offset computation at leave activation, and — after the leave — return-service obligations, breach detection, repayment collection, and the report of accomplishments due upon return. Alongside sabbaticals, the same application pipeline handles medical, personal, and professional leave, with explicit precedence rules when leave windows collide.

Three design commitments shape everything that follows. First, time is explicit: the server runs on a logical clock that tests and operations can set, so accrual, overdue detection, and default detection are deterministic. Second, money and months are never fuzzy: every monetary figure is rounded half-up to two decimal places at pinned rounding points, and every service figure is a whole calendar month. Third, duties are segregated by role — an applicant never reviews their own file, a committee member never reviews a colleague from their own department, and a chair never files coverage for their own application.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). If the role is declared but not listed among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows: `Faculty`, `CommitteeMember`, `DepartmentChair`, `ProvostOffice`, and `LeaveAdministrator`.

- When `X-User-Role` is `Faculty`, `X-User-ID` is the `id` of the acting `FacultyMember`; ownership checks on any resource that references a `FacultyMember` — leave applications, external fellowships, accomplishment reports — compare the resource's faculty foreign-key field to `X-User-ID`. A `Faculty` caller acting on another faculty member's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `CommitteeMember`, `X-User-ID` is likewise the `id` of the acting `FacultyMember`; it is recorded as the `reviewer_faculty_id` on any review the caller authors, and ownership checks on reviews compare against it.
- When `X-User-Role` is `DepartmentChair`, `X-User-ID` is the `id` of the acting `FacultyMember`; chair authority over a coverage plan is established by comparing `X-User-ID` to the `chair_faculty_id` of the department the plan belongs to, and a mismatch is rejected with `ERR_CHAIR_DEPARTMENT_MISMATCH` (HTTP 403).
- When `X-User-Role` is `ProvostOffice`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `LeaveAdministrator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

All five roles may read any resource through the list and detail endpoints. Segregation-of-duties rules layered on top of role membership — the reviewer-conflict rule and the rule that a plan's creator may not be the applicant — surface as `ERR_REVIEWER_CONFLICT` and `ERR_SEGREGATION_OF_DUTIES` (both HTTP 403) at the workflow steps described in §3.

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

Requests to a path the API does not define are answered 404, and requests using a method the path does not support are answered 405 — both in this error envelope with `error_id` `ERR_INVALID_REQUEST`; an unexpected server failure is answered 500 with the same `error_id`.

### 2.3. Pagination

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be greater than or equal to 0. A `limit` outside the range 1 through 100, a negative `offset`, or a value for either parameter that does not parse as an integer is rejected with `ERR_INVALID_PAGINATION` (HTTP 400). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Every list endpoint sorts its results by `created_at` in ascending order, breaking ties between resources stamped in the same millisecond by creation (insertion) order.

### 2.4. Common Resource Properties and Mutation Semantics

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, plus a `created_at` timestamp. Resources other than the two ledger-style exceptions below additionally carry `updated_at` and a `version`. Timestamps are ISO 8601 UTC with three fractional digits. The `version` is an integer that starts at 1 when the resource is created and increments by exactly one on every mutation of that resource — including mutations caused as side effects of another resource's transition.

Two resources are deliberately lighter: a `RepaymentPayment` and an `AccrualLedgerEntry` each carry only `id` and `created_at`. Neither has `updated_at`, and neither has a `version`; both are append-only records.

All side effects triggered by a request take effect atomically within that request: if any part of the operation fails, no part of it is persisted.

### 2.5. The Logical Clock and Time-Driven Status Sweeps

The server keeps a logical clock that governs every time-dependent rule in this document — including every `created_at` and `updated_at` it stamps. At server startup the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. A `LeaveAdministrator`-only test-driving capability advances the clock to a supplied `to_iso8601` instant — a missing or unparseable value is `ERR_INVALID_REQUEST`, and any valid instant is accepted, including one earlier than the current reading — and answers with the resulting `current_utc`.

Setting the clock triggers a sweep across two resources. Every accomplishment report still in `DUE` status whose `due_date` has passed flips to `OVERDUE`, and every repayment obligation in `ACTIVE` status whose `due_date` has passed while its `amount_outstanding` remains above zero flips to `DEFAULTED`. The same two transitions are also evaluated lazily on every incoming request, so a stale clock never makes an overdue report or a defaulted repayment look current.

### 2.6. Calendar Months, Semesters, and Half-Open Windows

One semester is exactly six calendar months, and all leave durations are expressed in whole semesters (one or two). Month watermarks used by the accrual and obligation engines are strings in `YYYY-MM` format.

Every dated window in the system — a proposed leave window, an active grant window, a fellowship window — is a half-open interval: the start instant is inclusive and the end instant is exclusive. Two windows in which one ends exactly when the other begins are adjacent, not overlapping, and adjacency never triggers an overlap rejection. When a rule below says a window must span a number of semesters, it means the end date must equal the start date plus that many times six calendar months of calendar arithmetic. Calendar-month addition clamps the day-of-month to the last day of the target month when that month is shorter, so a start of 31 August plus six months lands on the last day of February.

### 2.7. Monetary Precision and Rounding

All monetary amounts are carried at two decimal places, and every rounding performed by the server rounds half up to two decimal places. Where a computation has multiple rounding points, the rounding order is pinned and stated at the workflow that uses it — most notably the per-product rounding inside committee review scoring (§3.4) and the ordered salary computation at grant activation (§3.8). Service months, credit balances, course counts, ranks, and quotas are integers. Department posture thresholds are compared exactly, using integer cross-multiplication rather than floating-point division, so a boundary utilization can never flip because of representation error.

### 2.8. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

Creating a coverage plan requires the request to carry `expected_application_version`, holding the `version` of the target leave application as the caller last observed it. If the application's current `version` has advanced past that value — for example because another writer filed a superseding plan, which itself mutates the application — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because plan creation is not a pure insert: it supersedes the prior non-terminal plan, re-points the application's `current_coverage_plan_id`, and increments the application's `version`, so a writer holding a stale version would otherwise supersede a plan it never saw.

Recording a payment against a repayment obligation requires the request to carry `expected_repayment_version`, holding the obligation's `version` as the caller last observed it. Because every posted payment reduces `amount_outstanding` and increments the obligation's `version`, a payment issued against a version that has since advanced is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read the obligation and issue the payment against the fresh version.

### 2.9. Validation Order and Error Precedence

When a request would violate several rules at once, the server evaluates checks in a fixed order and surfaces the error from the earliest failing tier. The tiers, in evaluation order, are:

1. **Authentication context.** `X-User-ID` and `X-User-Role` are present and the role is declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT`.
2. **Request shape.** Required fields are present, enum values are in range, numbers are in domain — `courses_to_cover` between 1 and 40 inclusive, monetary amounts strictly positive — and pagination parameters are within bounds, else `ERR_INVALID_REQUEST` or `ERR_INVALID_PAGINATION`.
3. **Role membership.** The caller's role is authorized for the endpoint, else `ERR_FORBIDDEN_ROLE`.
4. **Existence.** Path identifiers and body foreign-key references are resolved left to right — department, then faculty, then cycle, then application, then review, then coverage plan, then grant, then fellowship, then obligation, then repayment, then report — and the first missing reference yields its corresponding error: `ERR_DEPARTMENT_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_COVERAGE_PLAN_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_FELLOWSHIP_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND`, `ERR_REPAYMENT_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND`.
5. **Ownership and segregation of duties.** Ownership of the target resource, chair-to-department matching, reviewer conflict, and plan-creator segregation, else `ERR_NOT_RESOURCE_OWNER`, `ERR_CHAIR_DEPARTMENT_MISMATCH`, `ERR_REVIEWER_CONFLICT`, or `ERR_SEGREGATION_OF_DUTIES`. This tier guards the mutating endpoints on owned resources, the authoring of committee reviews, and the creation of coverage plans.
6. **Optimistic concurrency.** The `expected_application_version` or `expected_repayment_version` check of §2.8, else `ERR_STALE_VERSION`.
7. **From-state gates.** The target resource must be in a valid from-state for the requested transition — the cycle gates `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_NOT_CLOSED`, `ERR_CYCLE_NOT_ALLOCATED`, and `ERR_INVALID_CYCLE_STATE`, and the per-resource gates `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_FACULTY_STATE`, `ERR_INVALID_REVIEW_STATE`, `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_GRANT_STATE`, `ERR_INVALID_FELLOWSHIP_STATE`, `ERR_INVALID_REPAYMENT_STATE`, and `ERR_INVALID_REPORT_STATE`.
8. **Standing cross-resource gates.** Evaluated when an application is submitted: no accomplishment report of the faculty may be `OVERDUE` (`ERR_OVERDUE_REPORT_BLOCKS`) and no repayment obligation of the faculty may be `DEFAULTED` (`ERR_DEFAULTED_REPAYMENT_BLOCKS`).
9. **Uniqueness and eligibility.** No second in-flight application per faculty (`ERR_DUPLICATE_ACTIVE_APPLICATION`), one review per reviewer per application (`ERR_DUPLICATE_REVIEW`), the 72-month certified service requirement for sabbaticals (`ERR_INSUFFICIENT_SERVICE_MONTHS`), the duration-and-salary tier table (`ERR_INVALID_DURATION_SALARY_COMBO`), and the rule that `cycle_id` is present exactly when the leave type is sabbatical (`ERR_INVALID_REQUEST`). Within this tier, application creation enforces only the duration-and-salary tier table and the `cycle_id` presence rule — creation never rejects a second in-flight application; the in-flight duplicate rule and the 72-month certified service requirement fire only at application submission; and the one-review-per-reviewer rule fires at review creation.
10. **Temporal and window rules.** Window shape and alignment (`ERR_INVALID_DATE_RANGE`), overlap against active grants under half-open semantics (`ERR_LEAVE_WINDOW_OVERLAP`), the fellowship fifty-percent overlap rule (`ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT`), the grant start-reached gate (`ERR_GRANT_START_NOT_REACHED`), and the department active-leave day-count cap (`ERR_DEPARTMENT_LEAVE_CAPACITY`). This tier applies to application creation and submission, non-sabbatical decisions, fellowship creation and verification, and grant activation, completion, and curtailment.
11. **Fiscal gates.** Sabbatical credit sufficiency at submission (`ERR_INSUFFICIENT_SABBATICAL_CREDITS`), department posture at plan submission and approval (`ERR_DEPARTMENT_FROZEN`), coverage-budget sufficiency at approval (`ERR_INSUFFICIENT_COVERAGE_BUDGET`), payment amounts against the outstanding balance (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), and the replacement-pool floor on department updates (`ERR_POOL_BELOW_COMMITMENTS`).

The HTTP status attached to each error identifier is fixed by the catalogue in §5.

## 3. Business Logic & Workflows

### 3.1. Departments and the Replacement-Teaching Pool

Everything fiscal about coverage begins with the department. A `LeaveAdministrator` creates a department by supplying its `name` and its `replacement_pool` — the total replacement-teaching budget in USD for the planning horizon, which must be strictly positive — and may optionally supply `chair_faculty_id`. The chair reference is nullable at creation, since the chair's own faculty record may not exist yet; once set it must reference an existing faculty member. A new department is born with `reserved_amount` and `spent_amount` both zero, posture `OPEN`, and `version` 1. Departments can be listed — optionally filtered by `chair_faculty_id` — and fetched individually to inspect their budget buckets and posture.

Three derived buckets describe a department's commitments at any moment. `reserved_amount` is the sum of `provisional_cost` over the department's coverage plans whose status is `APPROVED` or `CONFIRMED`. `spent_amount` is the sum of `final_cost` over the department's plans whose status is `SETTLED`. `available_amount` is whatever remains: the pool minus the reserved and spent amounts. An invariant holds at all times — the reserved, spent, and available amounts always sum exactly back to `replacement_pool`.

From these buckets the department derives its `posture`, recomputed and persisted on every mutation of the reserved amount, the spent amount, or the pool itself — that is, on every plan approval, settlement, release, and pool edit. The committed total (reserved plus spent) is compared against the pool using exact integer cross-multiplication: one hundred times the committed total is compared against ninety-five times the pool, and against seventy times the pool, with no floating-point division involved. When the committed total reaches or exceeds ninety-five percent of the pool the posture is `FROZEN`; when it reaches or exceeds seventy percent but stays below ninety-five the posture is `CONSTRAINED`; otherwise the posture is `OPEN`. The boundaries are inclusive: a utilization of exactly seventy percent is `CONSTRAINED`, and exactly ninety-five percent is `FROZEN`. A `FROZEN` department cannot move coverage plans forward — both plan submission and plan approval are rejected with `ERR_DEPARTMENT_FROZEN` — while `CONSTRAINED` is informational and blocks nothing.

A `LeaveAdministrator` may update a department's `name`, `chair_faculty_id` — including clearing it back to null; any non-null chair value must reference an existing faculty member, else `ERR_FACULTY_NOT_FOUND` — or `replacement_pool`. The pool may never be set below the sum of the reserved and spent amounts; such an edit is rejected with `ERR_POOL_BELOW_COMMITMENTS`. A pool change recomputes the posture, and every update — including one that changes no field — increments the department's `version` by one.

### 3.2. Faculty Records, Credit Accrual, and Eligibility

A `LeaveAdministrator` registers a faculty member with an `employee_number` (unique across the institution; a duplicate is rejected with `ERR_INVALID_REQUEST`), `full_name`, the home `department_id`, an `academic_rank` of `ASSISTANT_PROFESSOR`, `ASSOCIATE_PROFESSOR`, or `FULL_PROFESSOR`, the `hire_date`, and a strictly positive `annual_base_salary`. The record is born with `status` `ACTIVE`, `lifetime_service_months` zero, `credit_balance` zero, and `last_accrued_month` initialized to the calendar month immediately before the hire month — the watermark from which accrual begins. Faculty can be listed with optional `department_id` and `status` filters, fetched individually for their balances, and their accrual ledger can be listed as a paginated reverse-reachability view.

A faculty member's `status` moves `ACTIVE` → `ON_LEAVE` when one of their grants is activated, returns `ON_LEAVE` → `ACTIVE` when the grant is completed or curtailed, and ends at `SEPARATED` — the terminal state — when a `LeaveAdministrator` records their separation (§3.9).

Service credit lives in an append-only ledger. Each `AccrualLedgerEntry` references its `faculty_id`, carries an `entry_type` of `EARN`, `CONSUME`, `RESTORE`, or `ADJUST`, a signed integer `credits_delta`, a `month` in `YYYY-MM` format that is set for `EARN` entries and null otherwise, an `affects_lifetime` flag that is false on every entry except an `ADJUST` posted with it true, and an optional `note`. Two balances are pure functions of the ledger: `credit_balance` is the sum of `credits_delta` over all of the faculty's entries, and `lifetime_service_months` is the sum over `EARN` entries plus those `ADJUST` entries whose `affects_lifetime` flag is true. `CONSUME` and `RESTORE` never touch the lifetime figure. A sabbatical award posts a `CONSUME` entry of negative thirty-six credits per semester; a cancellation restores the full thirty-six per semester and a curtailment restores six per unused month, so a consume followed by its matching restore leaves `credit_balance` exactly where it stood before the pair.

Accrual itself is an explicit operational checkpoint rather than a background trickle. When a `LeaveAdministrator` triggers an accrual run, the server computes a through-month equal to the calendar month before the clock's current month, then walks all faculty in `created_at` ascending order. For each member, every whole month after `last_accrued_month` up to and including the through-month is examined: an `EARN` entry of plus one credit with that `month` is written unless the month is covered, blocked, or separated. A month is covered when some grant of the faculty in `ACTIVE`, `COMPLETED`, or `CURTAILED` status has a half-open window containing the first day of that month. A run-time check blocks the member entirely if any of their accomplishment reports is `OVERDUE`, and a member whose status is `SEPARATED` earns nothing. Months that go unearned — leave-covered, overdue-blocked, or post-separation — are never backfilled; regardless of earnings, the member's `last_accrued_month` advances to the through-month. The run reports how many entries it wrote, how many obligation months it credited (§3.9), and how many faculty it processed, via `earn_entries_created`, `obligation_months_credited`, and `faculty_processed`; `faculty_processed` counts every faculty member walked, including those whose watermark was already current.

Corrections enter the ledger only as manual adjustments. A `LeaveAdministrator` posting a manual entry supplies `faculty_id`, `entry_type`, a signed `credits_delta`, an optional `affects_lifetime` flag (default false, controlling whether the delta also counts into `lifetime_service_months`), and an optional `note`. The entry type must be `ADJUST`; anything else is rejected with `ERR_INVALID_REQUEST`. Posting recomputes both balances.

Eligibility comes in two flavors, and conflating them is a classic source of bad promises to faculty. A computed read on a faculty member, given a `proposed_start_date` query parameter (a missing or unparseable value is `ERR_INVALID_REQUEST`), returns `certified_service_months`, `provisional_service_months`, the current `credit_balance`, and two booleans, `eligible_certified` and `eligible_provisional`. The certified figure is the accrued reality — the same chronological actuals carried on `lifetime_service_months` — and the authoritative submission gate (§3.3) requires at least seventy-two certified months for a sabbatical. The provisional figure is forward-looking: it adds to the certified months the whole months from the month after `last_accrued_month` through the month before the proposed start date, assuming the member remains `ACTIVE` throughout. Identical ledger data can therefore yield `eligible_provisional` true while `eligible_certified` is still false; only the certified number opens the submission gate.

### 3.3. The Application Cycle and the Submission Gate

Sabbaticals run inside a cycle. A `ProvostOffice` operator creates one with a display `name`, an `academic_year` label such as 2027-2028, and an `award_quota` — the maximum number of sabbatical applications the cycle may award, at least one. A cycle is born `DRAFT` with `awarded_count` zero. Opening moves it `DRAFT` → `OPEN`, and closing moves it `OPEN` → `CLOSED`; each transition requires its stated from-state (anything else is `ERR_INVALID_CYCLE_STATE`) and increments the cycle's `version` by one. Cycles can be listed with an optional `status` filter. Allocation and finalization are treated in §3.6.

Against an open cycle — or outside any cycle, for the non-sabbatical types — a `Faculty` caller files an application; the server stamps `applicant_faculty_id` from the caller's `X-User-ID`. The payload carries the `leave_type` (`SABBATICAL`, `MEDICAL`, `PERSONAL`, or `PROFESSIONAL`), the `requested_duration_semesters` (one or two), the `requested_salary_pct`, a `proposed_start_date` and `proposed_end_date`, and an optional free-text `proposal_text`. The `cycle_id` field is required exactly when the leave type is `SABBATICAL` and forbidden for every other type; violating either direction is `ERR_INVALID_REQUEST`. The duration and salary percentage must form an allowed tier: a one-semester sabbatical pays only 100 percent, a two-semester sabbatical pays 50 or 75 percent, professional leave always pays 100 percent, and medical or personal leave pays 0 percent. Any other combination is rejected with `ERR_INVALID_DURATION_SALARY_COMBO`. The window must satisfy two shape rules — the end must be strictly after the start, and the end must equal the start plus the requested number of semesters times six calendar months — with violations rejected as `ERR_INVALID_DATE_RANGE`. A new application is born `DRAFT` with `funding_status` `NONE`, its `composite_score` and `final_rank` and `award_outcome` all null, `submitted_review_count` zero, and `quorum_met` false. Applications can be listed filtered by `applicant_faculty_id`, `cycle_id`, `status`, or `leave_type`.

Submitting moves an application from `DRAFT` — or from `REVISION_REQUESTED`, since the cycle has a revision loop — to `UNDER_REVIEW`. Only the owning faculty member may submit (`ERR_NOT_RESOURCE_OWNER`), and only from those two states (`ERR_INVALID_APPLICATION_STATE`). Submission then runs the full gate chain. For a sabbatical the referenced cycle must be `OPEN`, else `ERR_CYCLE_NOT_OPEN`. No other application of the same faculty member may sit in `DRAFT`, `UNDER_REVIEW`, or `REVISION_REQUESTED`; a second in-flight application is `ERR_DUPLICATE_ACTIVE_APPLICATION`, though resubmitting the same application never counts as its own duplicate. The faculty member must carry no `OVERDUE` accomplishment report (`ERR_OVERDUE_REPORT_BLOCKS`) and no `DEFAULTED` repayment obligation (`ERR_DEFAULTED_REPAYMENT_BLOCKS`). A sabbatical demands at least seventy-two certified service months on `lifetime_service_months` (`ERR_INSUFFICIENT_SERVICE_MONTHS`), and the proposed window must not overlap any `ACTIVE` grant of the same faculty under half-open semantics — adjacency is allowed (`ERR_LEAVE_WINDOW_OVERLAP`). Finally, a sabbatical submission requires a `credit_balance` of at least thirty-six credits per requested semester, failing with `ERR_INSUFFICIENT_SABBATICAL_CREDITS` (HTTP 402). A successful submission increments the application's `version` by one. When a previously-revised application is resubmitted, its existing `SUBMITTED` reviews persist, and the recomputed composite therefore comes out unchanged.

The provost's office can send an application back for more work: requesting revision moves `UNDER_REVIEW` → `REVISION_REQUESTED` (any other from-state is `ERR_INVALID_APPLICATION_STATE`) and increments the `version`.

Withdrawal is the applicant's exit. From any of `DRAFT`, `UNDER_REVIEW`, or `REVISION_REQUESTED` — and only the owner may withdraw — the application becomes `WITHDRAWN`, its `funding_status` returns to `NONE`, its `current_coverage_plan_id` is cleared to null, and its `version` increments. Withdrawal cascades into coverage: any of the application's plans still in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` becomes `SUPERSEDED`, while an `APPROVED` plan is released outright — the department's `reserved_amount` drops by that plan's `provisional_cost` and the department posture is recomputed. Withdrawal after an award is impossible; by then only the rescission path of §3.7 and §3.9 applies.

### 3.4. Committee Review and the Composite Score

While an application is `UNDER_REVIEW`, committee members score it. A `CommitteeMember` authors a review by supplying the `application_id` plus three scores — `scholarly_merit`, `curriculum_benefit`, and `feasibility`, each between 0 and 100 with at most one decimal place — and optional `comments`. The server stamps `reviewer_faculty_id` from the caller's `X-User-ID`. Two segregation rules protect the process: the reviewer may not be the applicant and may not belong to the applicant's department (`ERR_REVIEWER_CONFLICT`), and a reviewer may hold at most one review per application in any status, draft included (`ERR_DUPLICATE_REVIEW`). Reviews may be authored only while the application is `UNDER_REVIEW` (`ERR_INVALID_APPLICATION_STATE`). The review is born `DRAFT`, and its `weighted_total` is computed immediately: forty-five percent of the merit score, thirty-five percent of the curriculum score, and twenty percent of the feasibility score, with each of the three products individually rounded half-up to two decimal places before the products are summed. Reviews can be listed filtered by `application_id`, `reviewer_faculty_id`, or `status`.

A review becomes binding when its author submits it — only the review's own reviewer may submit (`ERR_NOT_RESOURCE_OWNER`), only from `DRAFT` (`ERR_INVALID_REVIEW_STATE`), and only while the application is still `UNDER_REVIEW` (`ERR_INVALID_APPLICATION_STATE`). `SUBMITTED` is terminal for a review.

Each submission recomputes the application's committee aggregates over its `SUBMITTED` reviews only — drafts never count. `submitted_review_count` is the number of submitted reviews, and `quorum_met` becomes true once that count reaches three. The `composite_score` applies a drop-lowest rule: when at least four submitted reviews exist, exactly one review carrying the minimum `weighted_total` is discarded (if several reviews share that minimum any of them may be dropped — the resulting sum is identical); the composite is then the sum of the kept `weighted_total` values divided by the number of kept reviews, rounded half-up to two decimal places. Until the first review is submitted, `composite_score` remains null.

### 3.5. Coverage Plans and the Department Budget Waterfall

A sabbatical cannot be awarded until someone answers for the teaching it displaces. A `DepartmentChair` files a coverage plan for an application's home department — the plan's `department_id` is copied from the applicant's record — and the `ProvostOffice` may file as well. The payload names the `application_id`, the `courses_to_cover` (between 1 and 40 inclusive), optionally a `supersedes_plan_id` chaining the plan to the draft it replaces, and — because creation mutates the application — the `expected_application_version` guard of §2.8, with a stale value rejected as `ERR_STALE_VERSION` (HTTP 412). Two duty rules apply before anything is written: the plan's creator may not be the applicant themselves (`ERR_SEGREGATION_OF_DUTIES`), and a chair may file only for the department they chair (`ERR_CHAIR_DEPARTMENT_MISMATCH`). Plans may be filed only for sabbatical applications not yet awarded: a non-sabbatical `application_id` is `ERR_INVALID_REQUEST`, and an application no longer in `DRAFT`, `UNDER_REVIEW`, or `REVISION_REQUESTED` is `ERR_INVALID_APPLICATION_STATE`. A `supersedes_plan_id` naming a plan that belongs to another application is `ERR_INVALID_REQUEST`, and a supersede target — the named plan, or the application's current plan when none is named — that is no longer in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` is `ERR_INVALID_PLAN_STATE`. The plan's `provisional_cost` is computed at creation as the number of courses multiplied by 8,000.00 USD per course.

Filing a new plan supersedes the old one. If the application already has a non-terminal plan — the plan named by `supersedes_plan_id` when given, otherwise the current one — and that plan sits in `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED`, it becomes `SUPERSEDED`; the application's `current_coverage_plan_id` re-points to the new draft and the application's `version` increments by one. When the superseded plan was the application's current plan and funding stood at `COVERAGE_SUBMITTED`, the application's `funding_status` falls back to `NONE`. The canonical link from application to plans is the plan's `application_id`; plans are listed filtered by `application_id` — which is also how the current non-superseded plan is found — as well as by `department_id`, `status`, and `supersedes_plan_id`.

Submission moves a plan `DRAFT` → `SUBMITTED`. The caller must chair the plan's department or be the `ProvostOffice` (`ERR_CHAIR_DEPARTMENT_MISMATCH`), the plan must be `DRAFT` (`ERR_INVALID_PLAN_STATE`), the application must be `UNDER_REVIEW` or `REVISION_REQUESTED` (`ERR_INVALID_APPLICATION_STATE`), and the department must not be `FROZEN` (`ERR_DEPARTMENT_FROZEN`). Submission flips the application's `funding_status` to `COVERAGE_SUBMITTED` and increments the plan's `version`.

Approval is the provost's call and the moment money moves. Approving moves `SUBMITTED` → `APPROVED`; the plan must be `SUBMITTED` (`ERR_INVALID_PLAN_STATE`), the department must not be `FROZEN` (`ERR_DEPARTMENT_FROZEN`), and the department's `available_amount` must be at least the plan's `provisional_cost` (`ERR_INSUFFICIENT_COVERAGE_BUDGET`, HTTP 402). On approval the department's `reserved_amount` increases by the `provisional_cost`, `available_amount` and the posture are recomputed, the application's `funding_status` advances to `COVERAGE_APPROVED`, and the plan's `version` increments. The provost's office may instead send a submitted plan back — `SUBMITTED` → `REVISION_REQUESTED`, requiring the `SUBMITTED` from-state and incrementing `version` — which starts another draft-supersede round when the chair files a corrected plan.

An approved plan that is never confirmed can still be unwound: when the application is withdrawn, the `APPROVED` plan becomes `RELEASED`, the department's `reserved_amount` decreases by the `provisional_cost`, and `available_amount` and posture are recomputed (§3.3). Confirmation, settlement, and grant-driven release are covered in §3.6 and §3.8.

### 3.6. Allocation: Ranking, Awards, and the Credit Consume

Once a cycle is `CLOSED`, the `ProvostOffice` runs the allocation — attempting it from any other state is `ERR_CYCLE_NOT_CLOSED`. Allocation ranks the cycle's sabbatical applications that are still `UNDER_REVIEW` and walks them through a fixed gate sequence, then moves the cycle to `ALLOCATED` and increments the cycle's `version`.

Ranking considers only applications whose `quorum_met` is true. They are ordered by `composite_score` descending; ties break on the applicant's `lifetime_service_months` descending, and remaining ties break on the application's `created_at` ascending. The ranked applications receive a one-based `final_rank`.

Every candidate is then evaluated against four gates in this exact order, and the first failing gate decides its fate. An application without quorum becomes `NOT_AWARDED` with `award_outcome` `INCOMPLETE_REVIEWS`. One lacking a current coverage plan in `APPROVED` status becomes `NOT_AWARDED` with `award_outcome` `NO_APPROVED_COVERAGE`. One whose applicant's `credit_balance` is below thirty-six times the `requested_duration_semesters` becomes `NOT_AWARDED` with `award_outcome` `INSUFFICIENT_CREDITS`. And once `awarded_count` has reached the cycle's `award_quota`, every remaining candidate becomes `NOT_AWARDED` with `award_outcome` `QUOTA_EXCEEDED`.

An application passing all four gates is awarded: its status becomes `AWARDED` with `award_outcome` `AWARDED`, a leave grant is created in `SCHEDULED` status copying the proposed window (`start_date`, `end_date`), the `duration_semesters`, the `salary_pct`, the `leave_type`, the `application_id`, and a denormalized `faculty_id` for filtering — with all salary figures deferred to activation (`gross_salary` and `net_salary` null, `fellowship_offset_total` zero) — the application's `APPROVED` plan becomes `CONFIRMED`, its `funding_status` advances to `COVERAGE_CONFIRMED`, a `CONSUME` ledger entry of negative thirty-six credits per semester posts to the applicant, and the cycle's `awarded_count` increases by one. The quota boundary is inclusive: an application whose `final_rank` is exactly equal to `award_quota` is awarded.

After allocation, the provost's office finalizes the cycle — `ALLOCATED` → `FINALIZED`, the terminal state; finalizing from any other state is `ERR_CYCLE_NOT_ALLOCATED`, and the transition increments the cycle's `version`.

### 3.7. Non-Sabbatical Decisions and Medical Precedence

Medical, personal, and professional applications never wait for allocation. The `ProvostOffice` decides an `UNDER_REVIEW` non-sabbatical application directly, passing a `decision` of `APPROVED` or `DENIED` with optional `comments`. Invoking the decision on a sabbatical application is rejected with `ERR_SABBATICAL_REQUIRES_ALLOCATION` — sabbaticals are decided only by the allocation run — and deciding from any state other than `UNDER_REVIEW` is `ERR_INVALID_APPLICATION_STATE`; the from-state check fires first, so a sabbatical application that is not `UNDER_REVIEW` also draws `ERR_INVALID_APPLICATION_STATE`. Either decision increments the application's `version`.

A denial is terminal and side-effect free: the application rests at `DENIED`.

An approval first checks that the faculty member holds no overlapping `ACTIVE` grant — half-open semantics, adjacency allowed — else `ERR_LEAVE_WINDOW_OVERLAP`. It then creates a leave grant in `SCHEDULED` status carrying the proposed window and terms, with salary figures deferred to activation exactly as in the sabbatical case, and the application moves to `APPROVED`, terminal.

Approving a medical application carries one more consequence, because medical need outranks a planned sabbatical. Any overlapping `SCHEDULED` sabbatical grant of the same faculty member is cancelled, and cancellation is a full unwind: a `RESTORE` ledger entry of plus thirty-six credits per `duration_semesters` posts to the faculty member, the cancelled grant's `CONFIRMED` coverage plan becomes `RELEASED` (the department's `reserved_amount` decreases by the plan's `provisional_cost`, `spent_amount` is untouched, and the posture is recomputed), the cancelled grant's own application moves `AWARDED` → `RESCINDED` with its `funding_status` falling to `COVERAGE_RELEASED`, and any of its `VERIFIED` external fellowships become `DECLINED`. This same cancellation cascade fires on faculty separation (§3.9).

### 3.8. Grant Execution: Activation, Fellowships, Completion, and Curtailment

Grants, however created, are listed filtered by `faculty_id`, `application_id`, or `status`, and fetched individually for their salary figures.

Activation is the `LeaveAdministrator`'s handshake that the leave may begin, moving a grant `SCHEDULED` → `ACTIVE`. Five gates guard it, in the validation order of §2.9: the grant must be `SCHEDULED` (`ERR_INVALID_GRANT_STATE`); the faculty member must be `ACTIVE` (`ERR_INVALID_FACULTY_STATE`); the clock must have reached the grant's `start_date` (`ERR_GRANT_START_NOT_REACHED`); no overlapping `ACTIVE` grant may exist for the same faculty member (`ERR_LEAVE_WINDOW_OVERLAP`); and the department's active-leave capacity must hold — on every calendar day of the new grant's half-open window, counting other `ACTIVE` grants of faculty from the same department whose windows contain that day, the count must stay below two, the department's maximum simultaneous active leaves, or activation fails with `ERR_DEPARTMENT_LEAVE_CAPACITY`. Because windows are half-open, a colleague whose leave ends the very day this one begins does not count against capacity.

Activation is also when money is computed, in a pinned evaluation order that resolves the circularity between salary and offsets. First, `gross_salary` is the member's `annual_base_salary` multiplied by the grant's `salary_pct` divided by one hundred, multiplied by the grant's length in months (its `duration_semesters` times six) divided by twelve, the whole result rounded half-up to two decimal places; medical and personal grants carry a zero percent rate, so their gross is zero. Second, the fellowship offset cap is fifty percent of that gross, rounded half-up to two decimal places. Third, `fellowship_offset_total` is filled from the fellowship waterfall below, bounded by the cap. Fourth, `net_salary` is the gross minus the total offset. Activation then flips the faculty member to `ON_LEAVE` and increments the grant's `version`.

The fellowship waterfall deserves its own paragraph. Eligible at activation are the application's external fellowships still in `VERIFIED` status whose window overlaps the grant window by at least half — the number of overlapping days, counted under half-open semantics, must be at least half the grant window's days, equivalently the overlap doubled must be no less than the window's length. Eligible fellowships are consumed oldest first by `created_at` (timestamps all read the logical clock, so ties on `created_at` are possible and break by creation order): each receives an `applied_offset` equal to the lesser of its own `amount` and the remaining cap, the remaining cap shrinks by that amount, and the fellowship moves `VERIFIED` → `APPLIED`. The sum of all applied offsets becomes `fellowship_offset_total`.

Fellowships enter the system well before activation. A `Faculty` caller reports one by naming a sabbatical application of their own (`application_id` referencing anything else — a non-sabbatical application or another faculty member's application — is `ERR_INVALID_REQUEST`), plus the fellowship's `name`, a strictly positive total `amount`, and a `window_start_date`/`window_end_date` pair whose end must be strictly after its start (`ERR_INVALID_DATE_RANGE`). A fellowship is born `REPORTED` with `applied_offset` zero. A `LeaveAdministrator` verifies a `REPORTED` fellowship — any other from-state is `ERR_INVALID_FELLOWSHIP_STATE` — only when its half-open overlap with the application's proposed window covers at least fifty percent of that window's days, failing with `ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT`; verification increments the fellowship's `version`. The reporting faculty member may decline their own fellowship from either `REPORTED` or `VERIFIED` (`ERR_NOT_RESOURCE_OWNER` for non-owners, `ERR_INVALID_FELLOWSHIP_STATE` from any other state; the `version` increments). The fifty-percent rule is evaluated a second time at activation, against the grant window, before the `VERIFIED` → `APPLIED` transition; and a fellowship still `VERIFIED` when its grant is cancelled becomes `DECLINED`. Fellowships are listed filtered by `faculty_id`, `application_id`, or `status`.

Completion closes a leave at full term. A `LeaveAdministrator` completes a grant only from `ACTIVE` (`ERR_INVALID_GRANT_STATE`) and only once the clock has reached the grant's `end_date` (`ERR_INVALID_DATE_RANGE`). Completion sets `actual_months` to the full planned length — `duration_semesters` times six — and returns the faculty member to `ACTIVE`. Then a three-hop cascade settles the money. Hop one: the application's `CONFIRMED` coverage plan becomes `SETTLED` with `final_cost` equal to the full `provisional_cost`. Hop two: the department's `reserved_amount` decreases by the `provisional_cost` while its `spent_amount` increases by the `final_cost`, and `available_amount` is recomputed. Hop three: the department's posture is recomputed and persisted — though because the final cost equals the full provisional cost, a full-term settlement leaves the committed total (reserved plus spent) unchanged, so completion by itself never moves the posture. For sabbatical and professional grants only, completion also creates a service obligation (`IN_PROGRESS`, with `required_months` equal to `actual_months` and `last_credited_month` initialized to the month before the grant's end month) and an accomplishment report in `DUE` status whose `due_date` falls ninety days after the grant's `end_date`; medical and personal completions create neither. For a sabbatical grant the application's `funding_status` settles at `COVERAGE_SETTLED` — medical, personal, and professional grants carry no coverage plan and leave `funding_status` untouched — and the grant's `version` increments.

Curtailment ends a leave early. The caller supplies an `actual_return_date` that must lie strictly between the grant's `start_date` and `end_date` and must already have been reached by the clock — any other date is `ERR_INVALID_DATE_RANGE` — and the grant must be `ACTIVE` (`ERR_INVALID_GRANT_STATE`). The grant's `actual_months` becomes the whole calendar months between `start_date` and the return date, rounded down, with a minimum of one; the grant's `end_date` is overwritten with the `actual_return_date`; and the faculty member returns to `ACTIVE`. A `RESTORE` ledger entry of plus six credits per unused month — the planned months (semesters times six) minus the months actually served — posts to the faculty member. The sabbatical coverage plan settles `CONFIRMED` → `SETTLED` with a pro-rated `final_cost`: the `provisional_cost` multiplied by the ratio of actual months to planned months, rounded half-up to two decimal places, and the department's buckets and posture recompute as at completion, with the difference between provisional and final flowing back into `available_amount` — and because such a pro-rated settlement lowers the committed total, it can flip a `FROZEN` department back to `CONSTRAINED` or `OPEN`, re-enabling plan submissions there. For sabbatical and professional leaves a service obligation is created with `required_months` equal to the curtailed `actual_months` — but no accomplishment report is ever created on curtailment. For a sabbatical grant the application's `funding_status` reaches `COVERAGE_SETTLED` (other leave types leave it untouched), and the grant's `version` increments.

The fourth way a grant ends is cancellation — `SCHEDULED` → `CANCELLED` — which never happens on request but only as the system cascade already described: on faculty separation, or when an approved medical leave overlaps a scheduled sabbatical. The full unwind — credit restore, plan release, application rescission to `RESCINDED` with `funding_status` `COVERAGE_RELEASED`, fellowship declination — is itemized in §3.7.

### 3.9. Return-Service Obligations, Repayment, and Accomplishment Reports

Every completed or curtailed sabbatical or professional leave leaves a debt of time behind. The service obligation created at settlement references the `faculty_id` and the `grant_id` — exactly one obligation exists per grant — with `required_months` equal to the actual leave months served (the full planned duration on completion, the floored actual months on curtailment), `fulfilled_months` starting at zero, and `last_credited_month` initialized to the calendar month before the grant's end month. Obligations are listed filtered by `faculty_id`, `grant_id`, or `status`.

Accrual runs (§3.2) double as the obligation-crediting engine. For each `IN_PROGRESS` obligation whose faculty member is `ACTIVE`, the run credits one additional `fulfilled_months` for every whole month after `last_credited_month` up to and including the month before the clock's current month, then advances `last_credited_month` to that through-month. The crediting decision is taken per obligation at run time: a member who is `ON_LEAVE` or `SEPARATED` when the run executes is credited nothing for the entire range, yet the watermark still advances past it, so those months are never credited later. When `fulfilled_months` reaches `required_months`, the obligation becomes `FULFILLED`, terminal.

While an obligation is still open, reads expose a `projected_liability`: what the member would owe if employment ended today. It takes a base equal to the grant's `net_salary` plus the coverage plan's `final_cost`, multiplies by the unfulfilled share — the required months minus the fulfilled months, over the required months — and rounds half-up to two decimal places. This proportional estimate deliberately diverges from the chronological breach formula below whenever the base does not divide evenly by the required months: on a base of 100,000.00 over six required months with two months fulfilled, the breach formula yields 66,666.66 while the projection reads 66,666.67.

Separation is the event that converts time-debt into money-debt. A `LeaveAdministrator` separates a faculty member by supplying a `separation_date`; the member must not already be `SEPARATED` (`ERR_INVALID_FACULTY_STATE`). When a member in `ACTIVE` status is separated, every one of their `SCHEDULED` grants is cancelled with the full unwind of §3.7 — credit restore of thirty-six per semester, `CONFIRMED` plan released with the department's `reserved_amount` dropping by the `provisional_cost` and posture recomputed, application rescinded to `RESCINDED` with `funding_status` `COVERAGE_RELEASED`, `VERIFIED` fellowships declined — and every `IN_PROGRESS` service obligation moves to `BREACHED`, each breach creating a repayment obligation as described next. A `SCHEDULED` grant of a non-sabbatical leave unwinds to the bare cancellation — no credits were consumed, no plan confirmed, no fellowships attached — and its application is rescinded from `APPROVED` to `RESCINDED` with `funding_status` unchanged. When a member in `ON_LEAVE` status is separated, the active grant is instead curtailed with `actual_return_date` set to the `separation_date` — no range gate is applied to that date here, unlike §3.8's curtailment, and the curtailed `actual_months` floors at one and caps at the planned length; final cost pro-rated, unused credits restored, plan settled, department buckets and posture recomputed — which, for sabbatical and professional grants, creates a service obligation with `required_months` equal to the curtailed `actual_months` and zero months fulfilled; that obligation moves to `BREACHED` immediately, so its repayment obligation's `amount_owed` equals the full `base_amount`. A curtailed medical or personal grant creates no obligation, exactly as at ordinary curtailment. Any earlier `IN_PROGRESS` obligations move to `BREACHED` as in the `ACTIVE` case. The member's `status` ends at `SEPARATED`, terminal.

A repayment obligation is the canonical, chronological statement of what a separated faculty member owes. It captures the `obligation_id` it sprang from and a denormalized `faculty_id` for filtering; a `base_amount` equal to the grant's `net_salary` plus the settled plan's `final_cost` at breach; a `fulfilled_months_at_breach` snapshot of the obligation's fulfilled months; a `monthly_forgiveness` equal to the base divided by the required months, rounded half-up to two decimal places — the per-month amortization unit; and an `amount_owed` equal to the base minus the monthly forgiveness times the fulfilled-months snapshot. Its `amount_outstanding` is the `amount_owed` minus the sum of all posted payment amounts, its `due_date` falls exactly 365 days after its `created_at`, and it is born `ACTIVE`. Repayments are listed filtered by `faculty_id`, `obligation_id`, or `status`.

Time can sour a repayment. When the clock passes the `due_date` while `amount_outstanding` remains above zero, the obligation flips `ACTIVE` → `DEFAULTED` — through the sweep on clock-setting and lazily on read (§2.5). A `DEFAULTED` repayment is a standing block: its faculty member cannot submit new leave applications while it stands (`ERR_DEFAULTED_REPAYMENT_BLOCKS`).

Payments are the way out. A `LeaveAdministrator` records a payment with an `amount` that must be strictly positive and no greater than the current `amount_outstanding` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), and with the `expected_repayment_version` guard of §2.8 (`ERR_STALE_VERSION`, HTTP 412). The obligation must be `ACTIVE` or `DEFAULTED`; paying against a terminal one is `ERR_INVALID_REPAYMENT_STATE`. Each payment is persisted with its `repayment_id`, its `amount`, and the `resulting_outstanding` — the outstanding balance immediately after this payment — and the obligation's `version` increments by one with every payment; a payment that brings the outstanding balance to zero moves the obligation to `SETTLED`, terminal. A repayment's payment history is listed as a paginated reverse-reachability view, and recall from §2.4 that payment records carry only `id` and `created_at`. The provost's office may instead forgive the balance — waiving moves `ACTIVE` or `DEFAULTED` to `WAIVED` (terminal; any other from-state is `ERR_INVALID_REPAYMENT_STATE`), zeroes the `amount_outstanding`, accepts optional `comments` (which are not persisted), and increments the `version`.

The last artifact of a leave is the report of accomplishments. Created `DUE` at the full-term completion of a sabbatical or professional grant, it references the `grant_id` and a denormalized `faculty_id`, and its `due_date` falls ninety days after the grant's `end_date`. When the clock passes that date the report becomes `OVERDUE` — again via sweep and lazy read — and an overdue report is a standing block: while any report of a faculty member is `OVERDUE`, accrual runs skip that member entirely and their new application submissions are rejected with `ERR_OVERDUE_REPORT_BLOCKS`. Reports are listed filtered by `faculty_id`, `grant_id`, or `status`.

Submitting is the faculty member's act, supplying the `report_text`; only the owner may submit (`ERR_NOT_RESOURCE_OWNER`), and only from `DUE`, `OVERDUE`, or `REVISION_REQUIRED` (`ERR_INVALID_REPORT_STATE`). Each submission stamps `submitted_at` with the current clock time and increments the report's `version`. Lateness is tracked honestly: submitting from `DUE` leaves `submitted_late` false, submitting from `OVERDUE` sets `submitted_late` true — and once true it sticks, surviving any later resubmission — while submitting from `REVISION_REQUIRED` leaves the flag unchanged.

The provost's office closes the loop by reviewing a `SUBMITTED` report (any other state is `ERR_INVALID_REPORT_STATE`), passing a `decision` and optional `comments`. A decision of `ACCEPTED` moves the report to `ACCEPTED`, terminal. A decision of `REJECTED` moves it to `REVISION_REQUIRED` and records the `decision_comments`, inviting another submission. Either decision increments the report's `version`.

## 4. Endpoint Definitions

All endpoints share the envelope of §2.2. Operations that create a new resource respond with 201; operations that modify, transition, or compute against an existing resource respond with 200. Request payloads, side effects, and state gates are specified in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers the OVERDUE/DEFAULTED sweep | LeaveAdministrator |
| POST | `/departments` | Create a department with its replacement-teaching pool | LeaveAdministrator |
| GET | `/departments` | List departments | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/departments/{id}` | Get one department (posture, budget buckets) | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| PATCH | `/departments/{id}` | Update name / chair / pool; pool rejected below reserved plus spent | LeaveAdministrator |
| POST | `/faculty-members` | Create a faculty member | LeaveAdministrator |
| GET | `/faculty-members` | List faculty | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/faculty-members/{id}` | Get one faculty member (balances) | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/faculty-members/{id}/separate` | Mark faculty separated; fires the breach/cancel cascade | LeaveAdministrator |
| GET | `/faculty-members/{id}/eligibility` | Certified vs provisional sabbatical eligibility for a proposed start date | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/faculty-members/{id}/accrual-ledger-entries` | List a faculty member's accrual ledger | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/accrual-runs` | Accrue EARN credits and obligation service months through the month before the clock month | LeaveAdministrator |
| POST | `/accrual-ledger-entries` | Post a manual adjustment entry (ADJUST only) | LeaveAdministrator |
| POST | `/leave-cycles` | Create a cycle (DRAFT) | ProvostOffice |
| GET | `/leave-cycles` | List cycles | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/leave-cycles/{id}` | Get one cycle | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/leave-cycles/{id}/open` | Move a cycle DRAFT to OPEN | ProvostOffice |
| POST | `/leave-cycles/{id}/close` | Move a cycle OPEN to CLOSED | ProvostOffice |
| POST | `/leave-cycles/{id}/allocate` | Rank, award, create grants, confirm plans, consume credits (CLOSED to ALLOCATED) | ProvostOffice |
| POST | `/leave-cycles/{id}/finalize` | Move a cycle ALLOCATED to FINALIZED | ProvostOffice |
| POST | `/leave-applications` | Create a leave application (DRAFT); applicant is the caller | Faculty |
| GET | `/leave-applications` | List applications | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/leave-applications/{id}` | Get one application (scores, rank, funding) | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/leave-applications/{id}/submit` | Submit or resubmit an application (full validation chain) | Faculty |
| POST | `/leave-applications/{id}/request-revision` | Send an UNDER_REVIEW application back for revision | ProvostOffice |
| POST | `/leave-applications/{id}/withdraw` | Withdraw an application; releases/supersedes its plans | Faculty |
| POST | `/leave-applications/{id}/decide` | Approve or deny a non-sabbatical application | ProvostOffice |
| POST | `/committee-reviews` | Author a review (DRAFT) for an UNDER_REVIEW application | CommitteeMember |
| GET | `/committee-reviews` | List reviews | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/committee-reviews/{id}` | Get one review | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/committee-reviews/{id}/submit` | Submit a review; recomputes the application's composite | CommitteeMember |
| POST | `/coverage-plans` | Create a coverage plan (DRAFT); supersedes the prior plan; OCC-guarded | DepartmentChair, ProvostOffice |
| GET | `/coverage-plans` | List coverage plans | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/coverage-plans/{id}` | Get one coverage plan | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/coverage-plans/{id}/submit` | Move a plan DRAFT to SUBMITTED (posture gate) | DepartmentChair, ProvostOffice |
| POST | `/coverage-plans/{id}/approve` | Approve a plan; reserves its provisional cost from the pool | ProvostOffice |
| POST | `/coverage-plans/{id}/request-revision` | Send a SUBMITTED plan back for revision | ProvostOffice |
| GET | `/leave-grants` | List grants | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/leave-grants/{id}` | Get one grant (salary fields) | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/leave-grants/{id}/activate` | Activate a scheduled grant; computes salary and applies fellowship offsets | LeaveAdministrator |
| POST | `/leave-grants/{id}/complete` | Complete an active grant at full term; settles plan, creates obligation and report | LeaveAdministrator |
| POST | `/leave-grants/{id}/curtail` | Curtail an active grant early; pro-rates coverage cost, restores credits | LeaveAdministrator |
| POST | `/external-fellowships` | Report an external fellowship (REPORTED) | Faculty |
| GET | `/external-fellowships` | List fellowships | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/external-fellowships/{id}` | Get one fellowship | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/external-fellowships/{id}/verify` | Verify a fellowship (fifty-percent overlap gate) | LeaveAdministrator |
| POST | `/external-fellowships/{id}/decline` | Decline a fellowship (owner) | Faculty |
| GET | `/service-obligations` | List service obligations (includes projected liability) | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/service-obligations/{id}` | Get one service obligation | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/repayment-obligations` | List repayment obligations | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/repayment-obligations/{id}` | Get one repayment obligation | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/repayment-obligations/{id}/payments` | List the payments of a repayment obligation | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/repayment-obligations/{id}/payments` | Record a payment (partial allowed); OCC-guarded | LeaveAdministrator |
| POST | `/repayment-obligations/{id}/waive` | Waive the outstanding balance | ProvostOffice |
| GET | `/accomplishment-reports` | List accomplishment reports | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| GET | `/accomplishment-reports/{id}` | Get one accomplishment report | Faculty, CommitteeMember, DepartmentChair, ProvostOffice, LeaveAdministrator |
| POST | `/accomplishment-reports/{id}/submit` | Submit report text from DUE, OVERDUE, or REVISION_REQUIRED | Faculty |
| POST | `/accomplishment-reports/{id}/review` | Accept or reject a SUBMITTED report | ProvostOffice |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_CHAIR_DEPARTMENT_MISMATCH` | 403 |
| `ERR_REVIEWER_CONFLICT` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 |
| `ERR_FACULTY_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_COVERAGE_PLAN_NOT_FOUND` | 404 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_FELLOWSHIP_NOT_FOUND` | 404 |
| `ERR_OBLIGATION_NOT_FOUND` | 404 |
| `ERR_REPAYMENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_CYCLE_STATE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_CYCLE_NOT_CLOSED` | 409 |
| `ERR_CYCLE_NOT_ALLOCATED` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_SABBATICAL_REQUIRES_ALLOCATION` | 409 |
| `ERR_INVALID_FACULTY_STATE` | 409 |
| `ERR_INVALID_REVIEW_STATE` | 409 |
| `ERR_INVALID_PLAN_STATE` | 409 |
| `ERR_INVALID_GRANT_STATE` | 409 |
| `ERR_INVALID_FELLOWSHIP_STATE` | 409 |
| `ERR_INVALID_REPAYMENT_STATE` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_OVERDUE_REPORT_BLOCKS` | 409 |
| `ERR_DEFAULTED_REPAYMENT_BLOCKS` | 409 |
| `ERR_DUPLICATE_ACTIVE_APPLICATION` | 409 |
| `ERR_DUPLICATE_REVIEW` | 409 |
| `ERR_INSUFFICIENT_SERVICE_MONTHS` | 422 |
| `ERR_INVALID_DURATION_SALARY_COMBO` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_LEAVE_WINDOW_OVERLAP` | 409 |
| `ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT` | 422 |
| `ERR_GRANT_START_NOT_REACHED` | 409 |
| `ERR_DEPARTMENT_LEAVE_CAPACITY` | 409 |
| `ERR_INSUFFICIENT_SABBATICAL_CREDITS` | 402 |
| `ERR_DEPARTMENT_FROZEN` | 409 |
| `ERR_INSUFFICIENT_COVERAGE_BUDGET` | 402 |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 |
| `ERR_POOL_BELOW_COMMITMENTS` | 422 |
