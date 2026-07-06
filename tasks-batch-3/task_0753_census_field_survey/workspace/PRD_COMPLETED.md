# Census Field Survey API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Census & Field-Survey Operations API, the backbone system for running a door-to-door census or field survey wave from initial planning through final payroll reconciliation. A single wave brings together many moving parts: geographic assignment areas carved out of a project, a roster of household cases within each area, a hired workforce of field enumerators routed to those cases, a log of contact attempts and their dispositions, the survey responses those attempts eventually capture, a quality-control layer that reinterviews suspicious responses, and a payroll ledger that reimburses enumerators for their time and mileage.

The system's central challenge is keeping many derived truths consistent as field work unfolds. Every attempt logged, every response captured, and every fraud finding ripples outward: case counts on an area shift, coverage rates are recomputed, budgets are committed and released, and pay ledgers accrue and reverse. Operations must respect a strict separation of duties — the enumerator who captures a response can never be the reviewer who reinterviews it — and must guard against stale writes when supervisors reassign cases out from under one another. This specification describes each entity, its lifecycle, the calculations that derive its reportable figures, and the validation order that governs every mutation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. When either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles: `SurveyAdmin`, `FieldSupervisor`, `Enumerator`, and `QCReviewer`. A `SurveyAdmin` is a regional operations administrator responsible for projects, areas, the roster, the enumerator hire pipeline, area freeze/unfreeze, and all payroll. A `FieldSupervisor` assigns and reassigns cases and cancels erroneous attempts. An `Enumerator` is a field worker who logs attempts and captures responses for their own assigned cases. A `QCReviewer` opens, starts, and finalizes reinterviews.

Three of these roles carry an opaque identity. When `X-User-Role` is `SurveyAdmin`, `FieldSupervisor`, or `QCReviewer`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it where a workflow calls for an audit reference, but it is never compared against any entity's `id`. The `Enumerator` role is different: it is entity-backed. When `X-User-Role` is `Enumerator`, `X-User-ID` is the `id` of the acting `Enumerator` record, and ownership checks compare that value against the case's `assigned_enumerator_id`. When an enumerator logs an attempt, the acting enumerator's id is captured onto the attempt as `acting_enumerator_id`; when an enumerator captures a response, it is captured as `capturing_enumerator_id`. Both are audit references, not routable foreign keys.

Every GET (read) endpoint is available to all four roles. The mutating endpoints are restricted as described throughout §3 and summarized in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope; `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in the system — survey projects, assignment areas, enumerators, cases, case assignments, attempts, responses, reinterviews, pay periods, and pay lines — carries a common set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. `version` is an integer that begins at 1 on creation and increments by one on every mutation, and it is the anchor for optimistic concurrency control described in §2.7. Whenever a derived figure on a resource is recomputed as a side effect — an area's counts and coverage rates, an enumerator's pay totals, a case's `attempt_count` — that recomputation is a mutation that refreshes `updated_at` and increments `version` on the resource that changed.

### 2.5. Hierarchical Consistency and Cascades

The entities form a hierarchy — a `SurveyProject` owns its assignment areas, enumerators, and pay periods; an `AssignmentArea` owns its cases; a `Case` owns its assignments, attempts, and response; a `Response` owns its reinterviews; an `Enumerator` owns its pay lines — and the system keeps derived state consistent up and down this hierarchy without requiring the client to touch each affected resource directly. A single operation frequently mutates more than one entity, and every such cascade is described in full in §3. When a change to a child alters the criteria governing a parent's state, the server transitions the parent automatically: for example, completing the last outstanding case in an area bubbles the area up to `COMPLETE`, and a fraud finding that reopens a completed case reverts its area back to `IN_FIELD`. Each entity touched by a cascade independently refreshes its `updated_at` and increments its `version`.

### 2.6. Nested Resource Retrieval

Many endpoints address a resource nested beneath one or more parents in the URL path. The server validates the path identifiers strictly left to right and rejects the request at the first identifier that does not resolve to an existing resource, returning the not-found error for that resource type — `ERR_PROJECT_NOT_FOUND`, `ERR_AREA_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ENUMERATOR_NOT_FOUND`, `ERR_ATTEMPT_NOT_FOUND`, `ERR_RESPONSE_NOT_FOUND`, `ERR_REINTERVIEW_NOT_FOUND`, `ERR_PAY_PERIOD_NOT_FOUND`, or `ERR_PAY_LINE_NOT_FOUND`. A request for a case beneath a non-existent area, for instance, fails with `ERR_AREA_NOT_FOUND` before the case is ever looked up. Beyond path identifiers, foreign keys supplied in a request body are also checked for existence: an `enumerator_id` on an assignment, a `reviewer_enumerator_id` on a reinterview, and an `enumerator_id` on a pay line that reference no enumerator all fail with `ERR_ENUMERATOR_NOT_FOUND`.

### 2.7. Optimistic Concurrency Control

Case assignment is guarded by optimistic concurrency control keyed on the case's `version`. A request that assigns or reassigns a case must carry `expected_case_version` as a required field whose value is the client's last observed `version` of the target `Case`. If that value does not equal the case's current `version` — because another writer has advanced it since the client last read the case, for instance through an earlier assignment or a logged attempt — the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP status 412. This prevents a client acting on a stale view of the case from clobbering an assignment it never observed. No other endpoint takes a version field; only case assignment participates in this check.

### 2.8. Precision, Rounding, and Monetary Representation

All monetary amounts in the system are held as whole integer cents: budgets, mileage rates, hourly rates, pay-line amounts, and every derived pay or budget figure. Wherever a calculation produces a fractional cent, the result is rounded half up to a whole cent. As detailed in §3, the attempt pay commitment rounds each of its two components independently to whole cents before they are summed, and the pay-period overtime reconciliation rounds each enumerator's premium independently before the premiums are summed. Coverage rates are the only non-integer figures: `projected_coverage_rate` and `final_coverage_rate` are numbers rounded half up to four decimal places.

### 2.9. Area Budget Ledger

Each assignment area is provisioned with a fixed field-work budget, `budget_cents`, against which the cost of in-field attempts is committed. The area maintains two derived figures: `budget_committed_cents`, the sum of `pay_committed_cents` across the area's LOGGED (non-cancelled) attempts, and `budget_remaining_cents`, which equals `budget_cents` minus `budget_committed_cents`. Committing an attempt's cost draws down the remaining budget; cancelling an attempt is a compensating reversal that releases its committed cost back to the area. No attempt may be logged whose committed cost would exceed the area's remaining budget.

### 2.10. Language Governance

A wave is multilingual. Each project declares a non-empty `supported_languages` list drawn from the codes `EN`, `ES`, `ZH`, and `VI`, and a `default_language` that must itself be one of those four codes and must be a member of `supported_languages`. A project whose `default_language` is absent from `supported_languages` is rejected with `ERR_UNSUPPORTED_LANGUAGE`. When a case is added to a roster, its `respondent_language` must be one of the parent project's `supported_languages`, or the request is rejected with `ERR_UNSUPPORTED_LANGUAGE`. When a response is captured, its `language_used` must be a valid language code and, further, must be one of the languages the capturing enumerator can interview in (see §3.7).

### 2.11. Validation Order

When several checks guard a single endpoint, they are evaluated in a fixed order so that the reported error is deterministic. The order is: first the authentication headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); then role permission (`ERR_INSUFFICIENT_PERMISSIONS`); then existence of every path-referenced resource, left to right (the appropriate not-found error); then existence of any body-referenced foreign key (`ERR_ENUMERATOR_NOT_FOUND`); then structural input validation — required fields, correct types, valid enum membership, and the rule that an attempt's `window_end` is strictly after its `window_start` (`ERR_VALIDATION`); then language admissibility for project creation and case creation (`ERR_UNSUPPORTED_LANGUAGE`); then the case-version concurrency check on assignment (`ERR_STALE_CASE_VERSION`); then the legal-source-state check for the transition (`ERR_PROJECT_INVALID_STATE`, `ERR_AREA_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_ENUMERATOR_INVALID_STATE`, `ERR_REINTERVIEW_INVALID_STATE`, `ERR_PAY_PERIOD_INVALID_STATE`, or, for attempts and responses, the requirement that the parent area is `IN_FIELD` and not frozen via `ERR_AREA_NOT_IN_FIELD` and `ERR_AREA_FROZEN`); then the acting-enumerator ownership check (`ERR_NOT_ASSIGNED_ENUMERATOR`); then the target-enumerator-active check for assignment (`ERR_ENUMERATOR_NOT_ACTIVE`); then the attempt-boundary check (`ERR_MAX_ATTEMPTS_REACHED`); then the enumerator schedule-conflict check (`ERR_ENUMERATOR_SCHEDULE_CONFLICT`); then the case contact-cooldown check (`ERR_CASE_CONTACT_COOLDOWN`); then the response language-capability check (`ERR_LANGUAGE_NOT_SUPPORTED`); then the contact-made precondition for response capture (`ERR_NO_CONTACT_MADE`); then the reviewer-active and segregation-of-duties checks for reinterviews (`ERR_REVIEWER_NOT_ACTIVE`, then `ERR_SEGREGATION_OF_DUTIES`); and finally the area budget check (`ERR_AREA_BUDGET_EXCEEDED`). For the attempt endpoint specifically, the maximum-attempts boundary check is evaluated before the generic legal-source-state check: a case already in `MAX_ATTEMPTS`, or one whose `attempt_count` has already reached the project's `max_attempts`, surfaces `ERR_MAX_ATTEMPTS_REACHED` rather than a generic state error. Note that a case's `assigned_enumerator_id` is retained through a `MAX_ATTEMPTS` close, so the ownership check still resolves for the assigned enumerator.

## 3. Business Logic & Workflows

### 3.1. Establishing a Survey Wave

A `SurveyAdmin` opens a wave by creating a `SurveyProject`. The creation payload carries a `name` for the wave, a `region_code` identifying the geography, the `default_language`, and the `supported_languages` list, subject to the language rules of §2.10. Three further settings are optional and fall back to defaults when omitted: `fraud_score_threshold`, the score at or above which a captured response is flagged for reinterview, defaults to 60 and must lie between 0 and 100; `max_attempts`, the ceiling on contact attempts per case, defaults to 6 and must be at least 1; and `mileage_rate_cents_per_mile`, the reimbursement rate applied to in-person attempt mileage, defaults to 67 cents and must be non-negative. A newly created project begins in `PLANNING`.

A project's `status` progresses through three states. A `SurveyAdmin` opens the project for field work, moving it from `PLANNING` to `IN_FIELD`; opening a project that is not in `PLANNING` fails with `ERR_PROJECT_INVALID_STATE`. Later the administrator closes the project, moving it from `IN_FIELD` to `CLOSED`; closing a project that is not in `IN_FIELD` likewise fails with `ERR_PROJECT_INVALID_STATE`. `CLOSED` is terminal.

### 3.2. Assignment Areas, the Roster, and Coverage

Within a project, a `SurveyAdmin` carves out one or more assignment areas. Each `AssignmentArea` is created with an `area_code` (stored as provided; the server does not enforce uniqueness within the project) and a `budget_cents` field-work budget that must be non-negative; the area records its parent through `survey_project_id`. A fresh area starts in `DRAFT` with every derived count at zero. An area's lifecycle is `DRAFT`, `IN_FIELD`, `FROZEN`, and `COMPLETE`. A `SurveyAdmin` opens an area for field work, moving it from `DRAFT` to `IN_FIELD`; this is permitted only when the area is in `DRAFT` (otherwise `ERR_AREA_INVALID_STATE`) and only when the parent project is already `IN_FIELD` (otherwise `ERR_PROJECT_NOT_IN_FIELD`). An administrator may freeze an `IN_FIELD` area — optionally supplying a `reason` — moving it to `FROZEN`, and may later unfreeze it back to `IN_FIELD`; freezing a non-`IN_FIELD` area or unfreezing a non-`FROZEN` area fails with `ERR_AREA_INVALID_STATE`. While an area is `FROZEN`, no attempts or responses may be logged against its cases. An area reaches `COMPLETE` automatically, never by direct request, when a case within it completes and no case in the area remains pending or in progress; if a later fraud finding reopens one of its cases, the area automatically reverts from `COMPLETE` to `IN_FIELD`.

A `SurveyAdmin` adds household cases to an area's roster. Each `Case` is created with an `address` and a `respondent_language` that must be a supported language of the parent project, and records its parent through `assignment_area_id`. On creation the case starts in `UNASSIGNED`, the area's `total_case_count` increments by one, its `pending_case_count` increments by one, and the area's coverage rates are recomputed. A case additionally carries `assigned_enumerator_id`, which holds the enumerator id of its current active assignment or null when none is active, and `attempt_count`, the number of its LOGGED (non-cancelled) attempts.

The area maintains a full partition of its cases by status: `total_case_count` over all cases, and one running count each for cases in `UNASSIGNED` or `ASSIGNED` combined (`pending_case_count`), `IN_PROGRESS` (`in_progress_case_count`), `COMPLETE` (`complete_case_count`), `REFUSED` (`refused_case_count`), `VACANT` (`vacant_case_count`), and `MAX_ATTEMPTS` (`max_attempts_case_count`). Two coverage rates are derived from these counts and recomputed on any case-status change that moves a count — the first attempt on a case, a captured response, a refusal, a vacancy determination, a max-attempts close, or a fraud reopen. When the area holds no cases at all, both `projected_coverage_rate` and `final_coverage_rate` are zero. Otherwise the projected rate is the sum of the complete and in-progress case counts divided by the total case count, and the final rate is the complete case count alone divided by the total case count; each is rounded half up to four decimal places. The projected rate treats in-progress cases as expected completions for mid-field dashboards, while the final rate counts only cases actually complete, for coverage sign-off. The same figures are available through an area's coverage report, which returns `area_id`, `total_case_count`, `complete_case_count`, `in_progress_case_count`, `projected_coverage_rate`, and `final_coverage_rate`.

### 3.3. The Enumerator Workforce

A `SurveyAdmin` builds the field workforce under a project. Each `Enumerator` is created with a `full_name`, a non-empty `languages` list of the codes the worker can interview in (each drawn from `EN`, `ES`, `ZH`, `VI`), and an `hourly_rate_cents` pay rate that must be non-negative; the enumerator records its project through `survey_project_id` and begins in `APPLICANT`. The hiring pipeline advances the enumerator's `status` through `APPLICANT`, `HIRED`, and `ACTIVE`: the administrator hires an applicant (`APPLICANT` to `HIRED`), then activates the hire (`HIRED` to `ACTIVE`). An active enumerator may be suspended (`ACTIVE` to `SUSPENDED`), optionally with a `reason`, and later reinstated (`SUSPENDED` to `ACTIVE`). Any hire, activate, suspend, or reinstate attempted from the wrong source state fails with `ERR_ENUMERATOR_INVALID_STATE`.

Suspending an enumerator is not an isolated status change: it cascades to the field. Every `ACTIVE` case assignment held by that enumerator is moved to `RELEASED`, and each affected case has its `assigned_enumerator_id` cleared to null. This is why only an `ACTIVE` enumerator may be the target of a new assignment.

An enumerator also carries three payroll figures and a fraud marker, all derived. `gross_pay_cents` is the running sum of `amount_cents` across every pay line ever created for the enumerator; it is incremented on each pay-line creation and, deliberately, is never decremented by a later reversal. `reversed_pay_cents` is the sum of `amount_cents` across the enumerator's reversed pay lines. `net_pay_cents` is `gross_pay_cents` minus `reversed_pay_cents`. The boolean `fraud_flag` starts false and is set true when a reinterview on one of the enumerator's captured responses finalizes as fraud.

### 3.4. Assigning Cases to Enumerators

A `FieldSupervisor` routes work by assigning a case to an enumerator, which creates a `CaseAssignment` — the junction between a `Case` and an `Enumerator`. The payload names the target through `enumerator_id` and carries `expected_case_version` for the concurrency check of §2.7. The assignment records `case_id` and `enumerator_id` and begins in `ACTIVE`. Assignment is permitted only when the parent area is `IN_FIELD` (otherwise `ERR_AREA_NOT_IN_FIELD`) and the target enumerator is `ACTIVE` (otherwise `ERR_ENUMERATOR_NOT_ACTIVE`), and only when `expected_case_version` matches the case's current `version` (otherwise `ERR_STALE_CASE_VERSION`).

The first assignment on an `UNASSIGNED` case moves it to `ASSIGNED`, creates the `ACTIVE` assignment, sets the case's `assigned_enumerator_id` to the enumerator, and increments the case's `version` by one; because both `UNASSIGNED` and `ASSIGNED` are pending states, the area's `pending_case_count` is unchanged. A subsequent assignment on a case already in `ASSIGNED` is a reassignment: the prior `ACTIVE` assignment is moved to `SUPERSEDED`, a new `ACTIVE` assignment is created, the case's `assigned_enumerator_id` is updated to the new enumerator, the case stays in `ASSIGNED`, and its `version` again increments by one. An assignment's own `status` is `ACTIVE`, `SUPERSEDED`, or `RELEASED`: it becomes `SUPERSEDED` when a newer assignment supersedes it, and `RELEASED` when its case reaches a terminal disposition or its enumerator is suspended.

### 3.5. Logging Contact Attempts

An `Enumerator` records field visits by logging attempts against a case they are assigned to. Each attempt is logged with a `mode` of either `IN_PERSON` or `PHONE`, a planned contact window given by `window_start` and `window_end` (both ISO 8601 UTC, with `window_end` required to be strictly after `window_start`, else `ERR_VALIDATION`), and a `disposition` recording the outcome — one of `NO_ONE_HOME`, `REFUSED`, `VACANT`, `LANGUAGE_BARRIER`, `CONTACT_MADE`, or `APPOINTMENT_SET`. The attempt records its case through `case_id` and its actor through `acting_enumerator_id`, drawn from `X-User-ID`, which must equal the case's `assigned_enumerator_id` or the request is rejected with `ERR_NOT_ASSIGNED_ENUMERATOR`. Attempts may be logged only while the parent area is `IN_FIELD` and not frozen; a frozen area rejects them with `ERR_AREA_FROZEN`. Each logged attempt begins in `LOGGED` and increments the case's `attempt_count` by one.

Attempts drive the case's status. The first logged attempt on an `ASSIGNED` case, carrying a non-terminal disposition, moves the case to `IN_PROGRESS`, decrements the area's `pending_case_count` by one, increments its `in_progress_case_count` by one, and recomputes coverage. A first attempt that instead carries a terminal `REFUSED` or `VACANT` disposition still moves the case out of `ASSIGNED` and closes it directly to `REFUSED` or `VACANT`, with the area's counts and coverage recomputed accordingly. Once a case is `IN_PROGRESS`, a further attempt with `NO_ONE_HOME`, `APPOINTMENT_SET`, `LANGUAGE_BARRIER`, or `CONTACT_MADE` keeps it `IN_PROGRESS` — the revisit loop — and is permitted only while `attempt_count` remains below the project's `max_attempts`; an attempt beyond that boundary is refused with `ERR_MAX_ATTEMPTS_REACHED`. A `REFUSED` disposition on an in-progress case moves it to `REFUSED`, and a `VACANT` disposition moves it to `VACANT`; in either case the area's `in_progress_case_count` decrements by one, the corresponding `refused_case_count` or `vacant_case_count` increments by one, the case's active assignment is released, and coverage is recomputed. When a non-`CONTACT_MADE` attempt pushes `attempt_count` up to the project's `max_attempts` and the case is not otherwise closed, the system auto-closes the case to `MAX_ATTEMPTS`: the area's `in_progress_case_count` decrements by one, its `max_attempts_case_count` increments by one, the active assignment is released, and coverage is recomputed. The states `REFUSED`, `VACANT`, and `MAX_ATTEMPTS` are terminal for a case.

Two scheduling guards protect the attempt log, each evaluated against other LOGGED attempts. First, a new attempt's window must not overlap any other LOGGED attempt by the same enumerator, treating each window as half-open from its start up to but not including its end, so that back-to-back windows sharing an instant (one window's end equal to the next window's start) are allowed with no buffer; an overlap here is rejected with `ERR_ENUMERATOR_SCHEDULE_CONFLICT`. Second, a case enforces a contact cooldown of 240 minutes: taking the new window and every other LOGGED attempt on the same case, two attempts collide when the gap between the earlier window's `window_end` and the later window's `window_start` is less than 240 minutes, and such a collision is rejected with `ERR_CASE_CONTACT_COOLDOWN`.

A `FieldSupervisor` may cancel a logged attempt that was recorded in error, provided it is still `LOGGED`; cancelling anything else fails with `ERR_ATTEMPT_NOT_CANCELLABLE`. Cancellation moves the attempt to `CANCELLED`, decrements the case's `attempt_count` by one, and performs the compensating budget reversal described in §3.6. Pay lines, which live on a separate ledger, are unaffected by an attempt cancellation.

### 3.6. Attempt Cost and Area Budget

Logging an attempt commits a cost to the area budget, recorded on the attempt as `pay_committed_cents`. The commitment has two components computed independently and each rounded to whole cents before they are summed. The attempt's duration in whole minutes is the number of whole minutes in the span from `window_start` to `window_end` — the total seconds between them divided by 60 and rounded down to a whole number. The stipend component is the enumerator's `hourly_rate_cents` multiplied by that whole-minute duration, divided by 60, and rounded half up to whole cents. The mileage component applies only to in-person attempts: when `mode` is `IN_PERSON`, it is the attempt's `mileage_miles` (a non-negative distance, defaulting to 0) multiplied by the project's `mileage_rate_cents_per_mile`, rounded half up to whole cents; when `mode` is `PHONE`, the mileage component is zero regardless of any mileage value. The attempt's `pay_committed_cents` is the sum of the whole-cent stipend and the whole-cent mileage — each rounded first, then added; the two are never summed as fractions and rounded once.

Before an attempt is accepted, its committed cost is checked against the area's remaining budget: the area's `budget_remaining_cents` must be at least the attempt's `pay_committed_cents`, or the attempt is rejected with `ERR_AREA_BUDGET_EXCEEDED`. When the attempt is accepted, the area's `budget_committed_cents` increases by `pay_committed_cents`, and `budget_remaining_cents` is recomputed as `budget_cents` minus `budget_committed_cents`. When a `FieldSupervisor` cancels a logged attempt (§3.5), the area's `budget_committed_cents` is reduced by that attempt's `pay_committed_cents` and `budget_remaining_cents` is recomputed, releasing the commitment.

### 3.7. Capturing Responses and Fraud Scoring

An `Enumerator` captures the survey `Response` for a case, which moves the case from `IN_PROGRESS` to `COMPLETE`. The capture payload carries the `mode` (`IN_PERSON` or `PHONE`), the `language_used`, the interview `duration_minutes` (a non-negative whole number of minutes), the `flagged_answer_count` (the number of internally inconsistent answers, non-negative), and the `gps_variance_meters` (the non-negative distance in meters between the capture GPS and the case address). The response records `case_id` and `capturing_enumerator_id`, the latter drawn from `X-User-ID`, which must equal the case's `assigned_enumerator_id` or the capture is rejected with `ERR_NOT_ASSIGNED_ENUMERATOR`. Capture is permitted only while the parent area is `IN_FIELD` and not frozen (`ERR_AREA_FROZEN` otherwise), only when the case already has at least one LOGGED attempt whose disposition is `CONTACT_MADE` (otherwise `ERR_NO_CONTACT_MADE`), and only when `language_used` is one of the capturing enumerator's `languages` (otherwise `ERR_LANGUAGE_NOT_SUPPORTED`). A newly captured response begins in `CAPTURED`.

On capture the system computes an integer `fraud_score`. It begins from a base of 12 points for each flagged answer. A GPS component applies only to in-person captures: when `mode` is `IN_PERSON`, take the response's `gps_variance_meters`, subtract a tolerance of 50 meters, divide the remainder by 10, round up to the next whole number, and take the greater of that and zero, then multiply by 5 points per step; when `mode` is `PHONE`, the GPS component is zero. A short-duration penalty of 25 points applies when `duration_minutes` is below 8, and is zero otherwise. The raw score is the sum of the flagged-answer base, the GPS component, and the short-duration penalty, and the final `fraud_score` is that raw sum clamped into the range 0 through 100 — never below 0 and never above 100. The response's `needs_reinterview` flag is set true when its `fraud_score` is at or above the project's `fraud_score_threshold`, and false otherwise.

Capturing a response advances the area's tallies: the area's `in_progress_case_count` decrements by one, its `complete_case_count` increments by one, and coverage is recomputed. If after this the area has no case left pending or in progress — that is, its pending and in-progress counts together reach zero — the area bubbles up automatically from `IN_FIELD` to `COMPLETE`. A response's own `status` is `CAPTURED`, `ACCEPTED`, or `INVALIDATED`; the latter two are reached only through the quality-control workflow.

### 3.8. Quality-Control Reinterviews and the Fraud Cascade

A `QCReviewer` opens a `ReinterviewCase` on a captured response to audit its quality. The opening payload names the `reviewer_enumerator_id` conducting the reinterview, a `reason` of `RANDOM_SAMPLE`, `HIGH_FRAUD_SCORE`, or `MANUAL`, and an optional free-text `finding_note`; the reinterview records `response_id` and begins in `OPEN`. Two guards protect the opening. The reviewer must reference an enumerator in `ACTIVE` status, or the request is rejected with `ERR_REVIEWER_NOT_ACTIVE`. And, enforcing segregation of duties, the `reviewer_enumerator_id` must differ from the response's `capturing_enumerator_id` — a reviewer may never audit their own captured response — or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`.

A reviewer starts the reinterview, moving it from `OPEN` to `IN_REVIEW`, then finalizes it with an `outcome`; a start from any state other than `OPEN`, or a finalize from any state other than `IN_REVIEW`, fails with `ERR_REINTERVIEW_INVALID_STATE`. The finalize `outcome` must be one of `CONFIRMED`, `DISCREPANT`, or `FRAUD`; any other value is rejected with `ERR_INVALID_OUTCOME`. An optional `finding_note` may accompany the finalize. The three outcomes branch sharply. A `CONFIRMED` outcome is a benign confirmation: the reinterview moves to `CONFIRMED` and the audited response transitions from `CAPTURED` to `ACCEPTED`. A `DISCREPANT` outcome moves the reinterview to `DISCREPANT`, notes the discrepancy, and triggers no cascade — the response remains `CAPTURED`.

A `FRAUD` outcome moves the reinterview to `FRAUD` and drives a cascade three links deep. First, the audited response transitions from `CAPTURED` to `INVALIDATED`. Second, invalidating the response reopens its parent case from `COMPLETE` back to `IN_PROGRESS`: the area's `complete_case_count` decrements by one, its `in_progress_case_count` increments by one, and coverage is recomputed. Third, if that area had bubbled up to `COMPLETE`, the reopened in-progress case reverts the area from `COMPLETE` back to `IN_FIELD`. Alongside this chain, the capturing enumerator's `fraud_flag` is set true.

### 3.9. Payroll Periods, Pay Lines, and Overtime

A `SurveyAdmin` opens a `PayPeriod` under a project to reconcile field pay. The period is created with a `label` such as a week identifier and an optional `overtime_threshold_cents`, the per-enumerator stipend total above which excess is paid at an overtime premium; the threshold defaults to 200000 cents and must be non-negative. The period records `survey_project_id`, begins in `OPEN` with both totals at zero, and carries two derived figures: `provisional_total_cents`, the running sum of `amount_cents` over the period's non-reversed pay lines, and `final_total_cents`, the reconciled total computed at lock.

While a period is `OPEN`, the administrator adds pay lines to it. Each `PayLine` names an `enumerator_id`, a `line_type` of `STIPEND`, `MILEAGE`, or `BONUS`, and a positive `amount_cents`; a reversal is modeled by flipping a line's status rather than by a negative amount, so the amount must be strictly greater than zero. The line records its `pay_period_id`, begins in `ACCRUED`, adds its `amount_cents` to the period's `provisional_total_cents`, adds its `amount_cents` to the owning enumerator's `gross_pay_cents`, and triggers recomputation of that enumerator's `net_pay_cents`. The administrator may reverse an accrued line while its period is still `OPEN`: reversal requires the line to be in `ACCRUED` (otherwise `ERR_PAY_LINE_ALREADY_REVERSED`) and its parent period to be `OPEN` (otherwise `ERR_PAY_PERIOD_INVALID_STATE`), moves the line to `REVERSED`, subtracts its `amount_cents` from the period's `provisional_total_cents`, adds its `amount_cents` to the enumerator's `reversed_pay_cents`, and recomputes `net_pay_cents`. The enumerator's `gross_pay_cents` is deliberately left untouched by a reversal.

Locking the period reconciles overtime. A `SurveyAdmin` locks an `OPEN` period, moving it to `LOCKED` (a lock from any other state fails with `ERR_PAY_PERIOD_INVALID_STATE`), and at that moment the `final_total_cents` is computed. It starts from the provisional total — the sum of `amount_cents` over the period's accrued (non-reversed) lines — and adds a per-enumerator overtime premium. For each enumerator with at least one accrued line in the period, sum that enumerator's accrued `STIPEND` line amounts (only stipend lines feed overtime; `MILEAGE` and `BONUS` lines do not); if that stipend sum exceeds the period's `overtime_threshold_cents`, the excess above the threshold is multiplied by an overtime premium rate of one half and rounded half up to whole cents to yield that enumerator's premium. Each enumerator's premium is rounded independently and the premiums are summed, and `final_total_cents` is the provisional total plus the sum of the premiums. Finally the administrator marks a locked period paid, moving it from `LOCKED` to `PAID` (a pay from any other state fails with `ERR_PAY_PERIOD_INVALID_STATE`); `PAID` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, including all state-change and reversal actions, return `200 OK`. All GET endpoints return `200 OK` and are available to every role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/survey-projects` | Create a survey/census wave | SurveyAdmin |
| GET | `/survey-projects/{id}` | Get a survey project | All roles |
| POST | `/survey-projects/{id}/open` | Open the project for field work | SurveyAdmin |
| POST | `/survey-projects/{id}/close` | Close the project | SurveyAdmin |
| POST | `/survey-projects/{id}/assignment-areas` | Create an assignment area under a project | SurveyAdmin |
| GET | `/survey-projects/{id}/assignment-areas` | List assignment areas of a project | All roles |
| GET | `/assignment-areas/{id}` | Get an assignment area | All roles |
| POST | `/assignment-areas/{id}/open` | Open an area for field work | SurveyAdmin |
| POST | `/assignment-areas/{id}/freeze` | Freeze an area | SurveyAdmin |
| POST | `/assignment-areas/{id}/unfreeze` | Unfreeze an area | SurveyAdmin |
| GET | `/assignment-areas/{id}/coverage-report` | Computed coverage report for an area | All roles |
| POST | `/assignment-areas/{id}/cases` | Add a case to an area's roster | SurveyAdmin |
| GET | `/assignment-areas/{id}/cases` | List cases in an area | All roles |
| GET | `/cases/{id}` | Get a case | All roles |
| POST | `/cases/{id}/assignments` | Assign / reassign a case to an enumerator | FieldSupervisor |
| GET | `/cases/{id}/assignments` | List a case's assignments | All roles |
| POST | `/survey-projects/{id}/enumerators` | Create (apply) an enumerator | SurveyAdmin |
| GET | `/survey-projects/{id}/enumerators` | List enumerators of a project | All roles |
| GET | `/enumerators/{id}` | Get an enumerator | All roles |
| POST | `/enumerators/{id}/hire` | Hire an applicant | SurveyAdmin |
| POST | `/enumerators/{id}/activate` | Activate a hire | SurveyAdmin |
| POST | `/enumerators/{id}/suspend` | Suspend an enumerator | SurveyAdmin |
| POST | `/enumerators/{id}/reinstate` | Reinstate a suspended enumerator | SurveyAdmin |
| GET | `/enumerators/{id}/case-assignments` | List assignments held by an enumerator | All roles |
| GET | `/enumerators/{id}/pay-lines` | List an enumerator's pay lines | All roles |
| POST | `/cases/{id}/attempts` | Log a contact attempt and its disposition | Enumerator |
| GET | `/cases/{id}/attempts` | List attempts on a case | All roles |
| POST | `/attempts/{id}/cancel` | Cancel a logged attempt | FieldSupervisor |
| POST | `/cases/{id}/responses` | Capture a survey response | Enumerator |
| GET | `/cases/{id}/responses` | List a case's response(s) | All roles |
| GET | `/responses/{id}` | Get a response | All roles |
| POST | `/responses/{id}/reinterviews` | Open a QC reinterview on a captured response | QCReviewer |
| GET | `/responses/{id}/reinterviews` | List reinterviews on a response | All roles |
| GET | `/reinterviews/{id}` | Get a reinterview | All roles |
| POST | `/reinterviews/{id}/start` | Begin the reinterview | QCReviewer |
| POST | `/reinterviews/{id}/finalize` | Finalize QC (confirm, discrepant, or fraud) | QCReviewer |
| POST | `/survey-projects/{id}/pay-periods` | Open a pay period for a project | SurveyAdmin |
| GET | `/survey-projects/{id}/pay-periods` | List pay periods of a project | All roles |
| GET | `/pay-periods/{id}` | Get a pay period | All roles |
| POST | `/pay-periods/{id}/lock` | Lock a pay period and compute the final total | SurveyAdmin |
| POST | `/pay-periods/{id}/pay` | Mark a locked pay period paid | SurveyAdmin |
| POST | `/pay-periods/{id}/pay-lines` | Add a pay line for an enumerator to an open period | SurveyAdmin |
| GET | `/pay-periods/{id}/pay-lines` | List pay lines in a period | All roles |
| POST | `/pay-lines/{id}/reverse` | Reverse an accrued pay line | SurveyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_ENUMERATOR_NOT_FOUND` | 404 Not Found |
| `ERR_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_RESPONSE_NOT_FOUND` | 404 Not Found |
| `ERR_REINTERVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_PAY_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_PAY_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNSUPPORTED_LANGUAGE` | 400 Bad Request |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_PROJECT_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_NOT_IN_FIELD` | 409 Conflict |
| `ERR_AREA_INVALID_STATE` | 409 Conflict |
| `ERR_AREA_NOT_IN_FIELD` | 409 Conflict |
| `ERR_AREA_FROZEN` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_ENUMERATOR_INVALID_STATE` | 409 Conflict |
| `ERR_ATTEMPT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REINTERVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_PAY_PERIOD_INVALID_STATE` | 409 Conflict |
| `ERR_PAY_LINE_ALREADY_REVERSED` | 409 Conflict |
| `ERR_ENUMERATOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_NOT_ASSIGNED_ENUMERATOR` | 403 Forbidden |
| `ERR_MAX_ATTEMPTS_REACHED` | 409 Conflict |
| `ERR_ENUMERATOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CASE_CONTACT_COOLDOWN` | 409 Conflict |
| `ERR_NO_CONTACT_MADE` | 409 Conflict |
| `ERR_LANGUAGE_NOT_SUPPORTED` | 422 Unprocessable Entity |
| `ERR_REVIEWER_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_AREA_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_INVALID_OUTCOME` | 400 Bad Request |
