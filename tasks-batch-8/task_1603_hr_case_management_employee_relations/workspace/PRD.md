# Employee Relations Case Management API — Product Requirements Document

## 1. Introduction

Allegations of harassment, discrimination, retaliation, and other workplace misconduct reach an employee-relations department through many doors: a hotline call, a web-portal form, a manager's referral, a direct walk-in to HR, or an unsigned letter. What happens next must be defensible. Every report has to be categorized and date-stamped against a service-level commitment, placed with an investigator who is certified for the severity and conflict-free against the people involved, documented through interviews and a chain-of-custody evidence log, and brought to a finding that survives comparison against how similar cases were decided before. When the people involved must be notified, confidentiality tiers constrain what each recipient may read. And when a dispute escalates toward court, counsel needs a case file assembled into a sealed, verifiably complete package.

This document specifies the API that supports that work end to end. The system is organized around the **Case** and its children — interviews, evidence items, credibility assessments, findings with their recommended actions, closure notices, and litigation file packages — surrounded by reference data (employees, investigators, intake channels, the holiday calendar) and by analytics (trend snapshots aggregated by manager or location). Several design commitments cut across everything that follows: writes to a case are guarded by optimistic concurrency so no operator ever acts on a version of the file they have not observed; segregation-of-duties and conflict-of-interest rules are enforced structurally rather than by policy memo; all time-dependent behavior reads from a logical clock rather than the wall clock; and two sanctioned scoring variants govern how witness credibility feeds substantiation. All endpoints are mounted under the `/er` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting disciplines that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-Role`, naming the caller's operational capacity, and `X-User-ID`, identifying the caller. Four roles are recognized, spelled exactly as follows:

- `ERManager` — the employee-relations department manager, who owns intake, assignment, closure, the holiday calendar, and all reference data.
- `Investigator` — a case investigator, who conducts interviews, reviews evidence, drafts findings, and casts calibration votes.
- `LegalCounsel` — legal-department counsel, who assembles litigation packages and suppresses notices under hold.
- `HRAnalyst` — a people-analytics analyst, who computes and reads trend snapshots.

A request whose `X-User-Role` header is missing or does not name one of these roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a missing `X-User-ID` is rejected the same way. A request whose role is not permitted to invoke the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The two headers interact with resource ownership differently per role. When `X-User-Role` is `Investigator`, `X-User-ID` is the `id` of the acting Investigator record; ownership checks on any resource that references an Investigator — a case's assigned investigator, an interview's interviewer, an evidence item's bound reviewer, a finding's author — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `ERManager`, `LegalCounsel`, or `HRAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `assembled_by` on a litigation file package) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items a response returns; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources in the system carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, uniquely identifying the resource.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T09:15:00.000Z`), fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — a system-managed integer that increments by one on every mutation. Clients read it to drive the optimistic concurrency checks described in §2.9.

One resource is exempt from part of this convention: a holiday calendar entry carries only `id` and `created_at`. Because holiday entries are never modified after registration, `updated_at` and `version` are both absent from that resource.

### 2.5. The Logical Clock and the Business-Day Calendar

All timestamps the server stamps, all service-level arithmetic, and all timing validations read from a **logical clock**, never from wall-clock time. At server startup — before any operator intervention — the logical clock reads exactly `2026-08-01T00:00:00Z`. An `ERManager` moves the clock through a dedicated clock-setting capability, supplying the target instant as `to_iso8601`; the response reports the new reading in `current_utc`. Interview completion windows, no-show eligibility, SLA due dates, overdue counters, trend windows, and package seals all observe this single clock.

Business-day arithmetic throughout the system counts only Monday through Friday, and additionally skips every date registered in the company holiday calendar. Registering a holiday records a `holiday_date` — an ISO 8601 date at UTC midnight — together with a human-readable `label`. Holiday dates are unique across the calendar; a duplicate registration is rejected with `ERR_DUPLICATE` (HTTP 409).

### 2.6. Validation Order and Error Precedence

Every request is screened in a fixed order, and the first failing screen determines the error the caller receives. Authentication comes first: a request without a valid `X-User-Role` fails with `ERR_UNAUTHENTICATED`, then a request without `X-User-ID` fails the same way, and only then is the role's permission to invoke the endpoint examined (`ERR_UNAUTHORIZED`). Existence comes next: path identifiers are resolved left to right (§2.11), and a miss fails with `ERR_NOT_FOUND`; after that, identifiers referenced in the request body must resolve to existing rows or the request fails with `ERR_REFERENCED_NOT_FOUND`.

State legality follows existence: the requested transition must be defined from the resource's current state, or the request fails with `ERR_INVALID_STATE` (HTTP 409), and the litigation-hold freeze of §2.7 is applied at the same layer (`ERR_LITIGATION_HOLD`, HTTP 409). Only then do the business rules run, in their own fixed sequence: segregation of duties before investigator-conflict screening; conflict screening before certification checks; then confidentiality rules, the interview overlap window, timing rules, investigator capacity, uniqueness constraints, documentation standards, credibility consistency, closure gates, reopen limits, notice-recipient matching, trend scope resolution, and the trend headcount rule. The optimistic-concurrency version screen (§2.9) runs near the very end — after every business rule above has passed — and syntactic validity (required fields present, values well-typed, enum values within their declared sets, failing with `ERR_INVALID_REQUEST`, HTTP 400) is the final screen of all: a request that trips any earlier rule reports that rule's error even when the payload is also malformed.

### 2.7. The Litigation Hold Freeze

A case's `litigation_hold` flag freezes the case file for litigation readiness. While the flag is true, any mutating transition on the case or on any of its children — interviews, evidence items, credibility assessments, findings, recommended actions, closure notices — is rejected with `ERR_LITIGATION_HOLD` (HTTP 409). Exactly three kinds of operation are exempt from the freeze: assembly actions on litigation file packages, suppression of a queued closure notice, and the case-update operation itself (`PATCH /er/cases/{id}`), because that is the operation through which legal places or lifts the hold.

The hold may be supplied at intake, and afterward it may be toggled only while the case is in `TRIAGE` or `CLOSED`; attempting to change it at any other point in the lifecycle fails with `ERR_INVALID_STATE`. In practice, legal places a hold either when the report first arrives or immediately after closure, when litigation is anticipated.

### 2.8. Segregation of Duties and Conflict-of-Interest Discipline

Two independence disciplines run across the casework, and both are enforced by the server rather than by convention.

Segregation of duties separates the author of work from its approver. The investigator who authored a finding may not cast an approval or rejection vote on it, and on the evidence side the investigator who began reviewing an item is the only investigator permitted to admit or exclude it. These rules guard four actions — finding approval, finding rejection, evidence admission, and evidence exclusion — and a violation on any of them is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

Conflict screening keeps investigators away from people they have a relationship with. Each investigator carries a `conflicted_employee_ids` list naming employees they are conflicted against, whether by personal relationship or prior involvement. The screen guards two operations: investigator assignment and finding approval. If the case's subject employee — or its reporter, when the report is not anonymous — appears in the acting investigator's conflict list, the request fails with `ERR_INVESTIGATOR_CONFLICT` (HTTP 422). On the approval path the segregation check runs first, per §2.6, so an author attempting to approve their own finding sees `ERR_SEGREGATION_OF_DUTIES` even when they are also conflicted.

### 2.9. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency against the parent Case, and each of them requires the request to carry `expected_case_version` — the case `version` the caller last observed. The field is not optional on these operations. The guarded operations are: assigning an investigator (`POST /er/cases/{id}/assign`), removing an assignment (`POST /er/cases/{id}/unassign`), closing a case (`POST /er/cases/{id}/close`), and sealing a litigation file package (`POST /er/litigation-packages/{id}/seal`).

When the case's current `version` no longer equals the supplied `expected_case_version` — because an intervening write of any kind has advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is applied. The caller's view of the case is stale: assignment must not proceed against a case whose state has moved since the manager read it, closure must operate on the writer's current view of findings, notices, and hold status, unassignment must not undo an assignment that has already been superseded, and a seal must pin the manifest to the case-file state counsel actually reviewed. Per §2.6, this version screen runs only after the state, hold, and business checks have all passed. Endpoints outside these four do not take a version field, and their mutations apply no version comparison.

### 2.10. Numerical Precision, Scores, and Rounding

All computed decimal quantities in the system — credibility scores, calibration scores, and trend rates — are rounded half-up to exactly two decimal places. Credibility scores and calibration scores are additionally clamped so they never fall below 0.00 or rise above 1.00, and the rounding is applied after the clamp. Integer quantities (case counts, reopen counters, custody ordinals) are exact and are never rounded.

Two assessor-supplied quantities carry their own precision contract. An evidence item's `weight` is a decimal between 0.0 and 1.0 inclusive, expressed with at most two decimal places. A recommended action's `severity_points` is an integer from 0 to 100 inclusive, where a higher number means a harsher remedy.

Trend rates obey a pinned rounding order. Each per-scope rate is rounded individually as soon as it is computed; when several scopes are combined into a portfolio figure, the unrounded per-scope rates are summed first and the sum is rounded half-up to two decimal places exactly once. Summing already-rounded per-scope rates is forbidden.

### 2.11. Nested Resource Retrieval

Many resources live beneath a parent — an interview beneath a case, a recommended action beneath a finding. When an endpoint path names several identifiers, the system validates them left to right, confirming each resource exists before examining the next. The first identifier that does not resolve determines the outcome: the request fails immediately with `ERR_NOT_FOUND` (HTTP 404), and no later identifier or rule is consulted. A request targeting an interview beneath a case that does not exist therefore reports the missing case, never an interview error.

References supplied inside the request body are a separate layer. An employee id, intake channel id, investigator id, or finding id carried in a payload must resolve to an existing row; one that does not fails with `ERR_REFERENCED_NOT_FOUND` (HTTP 422), and per §2.6 this check runs only after every path identifier has resolved.

## 3. Business Logic & Workflows

### 3.1. People, Investigators, Intake Channels, and the Holiday Calendar

Everything in the department starts from the employee roster. An `ERManager` registers each employee with a unique corporate `employee_number` (fixed forever once created), the employee's `full_name`, a unique work `email`, the `location_code` of their office or site, their `department`, and their `hire_date` as an ISO 8601 date. The roster is a hierarchy: each record may name a `manager_id` pointing at another employee, left empty only at the top of the tree, and the reporting chain must never close into a loop — a manager assignment that would create a cycle is rejected with `ERR_DUPLICATE`, as is any reuse of an existing `employee_number` or `email`. An employee's `employment_status` is one of `ACTIVE`, `ON_LEAVE`, or `TERMINATED`, defaulting to `ACTIVE` when the registration payload omits it. Later edits may change `full_name`, `manager_id`, `location_code`, `department`, or `employment_status` — each edit bumps the record's `version` — but the employee number never changes. A `manager_id` or any other body reference that points at a nonexistent employee fails with `ERR_REFERENCED_NOT_FOUND`.

Some employees are also investigators. Creating an investigator profile binds it to an employee record via `employee_id` — one profile per employee, and the referenced employee must exist. The profile's `certification_level` declares the most severe caseload the investigator may lead: `LEVEL_1` may lead only `LOW` cases, `LEVEL_2` may lead `LOW` and `MEDIUM`, and `LEVEL_3` may lead any severity including `HIGH` and `CRITICAL`. Capacity is explicit: `max_active_cases` (a whole number, at least 1) caps how many non-closed cases the investigator may hold at once, and the derived `active_case_count` tracks the live figure — the number of cases currently assigned to the investigator whose status is one of `TRIAGE`, `ASSIGNED`, `INVESTIGATING`, `FINDINGS_DRAFT`, `CALIBRATION`, or `PENDING_CLOSURE`. Cases on hold, reopened but not yet reassigned, or closed do not count toward the cap. The count starts at zero and is recomputed on every assignment, unassignment, closure, and reopen. Finally, the profile carries the `conflicted_employee_ids` list (empty by default) that drives the conflict screen of §2.8. An `ERManager` may later update a profile's `certification_level`, `max_active_cases`, or `conflicted_employee_ids`, each edit incrementing the investigator's `version`.

Reports arrive through configured intake channels. Each channel configuration carries a unique `channel_code` — one of `HOTLINE`, `WEB_PORTAL`, `MANAGER_REFERRAL`, `HR_DIRECT`, or `ANONYMOUS_LETTER` — plus a human-readable `display_name`, the `default_category` applied when an intake payload omits the allegation category (one of `HARASSMENT`, `DISCRIMINATION`, `RETALIATION`, `POLICY_VIOLATION`, `SAFETY`, `COMPENSATION`, or `OTHER`), and the `default_severity` applied when severity is omitted (one of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, itself defaulting to `MEDIUM` on the channel). Channels differ on anonymity: when `requires_reporter_identity` is true — it defaults to false — every case entering through that channel must identify its reporter. Each channel also declares `sla_business_days`, the target number of business days from intake to closure, a whole number of at least 1; §3.2 shows how it drives the due date. Reusing an existing `channel_code` is rejected with `ERR_DUPLICATE`.

The holiday calendar, described in §2.5, completes the reference data. Its entries are registered by an `ERManager`, carry a unique `holiday_date` and a `label`, and are excluded from every business-day computation in the system.

### 3.2. Case Intake, Service-Level Dating, and Investigator Assignment

A case is born when an `ERManager` intakes a report, naming the `intake_channel_id` it arrived through and the `subject_employee_id` the allegation is against. The `reporter_employee_id` is optional on channels that permit anonymous reports but mandatory whenever the channel's `requires_reporter_identity` is true; omitting a mandatory reporter fails as an invalid request, and a reporter or subject id that does not resolve fails with `ERR_REFERENCED_NOT_FOUND`. When the payload omits `category`, the channel's `default_category` applies; when it omits `severity`, the channel's `default_severity` applies. Litigation risk can be flagged immediately by setting `litigation_hold` at intake (it defaults to false). The server stamps `intake_received_at` from the logical clock, mints a human reference into `case_number` — the letters ER, the four-digit calendar year of intake, and a zero-padded sequence number assigned in creation order within that calendar year, joined by hyphens — and the case enters `TRIAGE`.

The same moment fixes the case's service-level commitment. The `sla_due_date` computation treats the intake day itself as day zero — it never counts toward the allowance, even when it is a business day. Starting from the day after intake, the calendar advances one day at a time; Saturdays, Sundays, and registered holiday dates are skipped, and every remaining day decrements the channel's `sla_business_days` allowance by one. The day on which the allowance reaches zero becomes the due date, stamped at exactly 17:00:00 UTC. The value is persisted at creation and recomputed only if the case's intake channel changes while the case is still in `TRIAGE`. Against this commitment, every case read also reports `overdue_business_days`: zero while the logical clock reads on or before the `sla_due_date`, and otherwise the count of business days — Monday through Friday, skipping holidays — in the interval that opens the day after the due date and closes on the current day, so the first business day after the due date counts as one.

While a case sits in `TRIAGE`, an `ERManager` may still correct the record: a direct edit may change `intake_channel_id`, `category`, or `severity` only in that status, and changing the channel recomputes the due date from the new channel's allowance. The `litigation_hold` flag follows the wider window of §2.7 — editable in `TRIAGE` or `CLOSED` only. Any of these edits attempted at a disallowed status fails with `ERR_INVALID_STATE`, and every successful edit bumps the case's `version`.

Assignment moves a case from `TRIAGE` to `ASSIGNED`, and the same action with the same rules also moves a `REOPENED` case back to `ASSIGNED` — a reopened case behaves exactly as a triage case for assignment purposes. The manager's payload names an `investigator_id` and carries `expected_case_version` per §2.9. Once the case's state and hold status permit the transition at all, the assignment screens run in a fixed order. The conflict screen fires first: if the case's subject — or its reporter, when one exists — appears in the candidate's `conflicted_employee_ids`, the request fails with `ERR_INVESTIGATOR_CONFLICT` before any other business check runs. Certification comes next: the candidate's `certification_level` must cover the case's `severity` per the ladder of §3.1, or the request fails with `ERR_CERTIFICATION_INSUFFICIENT`. Capacity follows: the candidate's `active_case_count` must still be below their `max_active_cases`, or the request fails with `ERR_CAPACITY_EXCEEDED`. Only after all three screens pass is the version compared, with a stale value rejected as `ERR_STALE_VERSION`. A successful assignment writes the investigator into the case's `assigned_investigator_id`, recomputes that investigator's `active_case_count` (it rises by one), and increments the case's `version`. An `investigator_id` that does not resolve to an existing investigator fails earlier, with `ERR_REFERENCED_NOT_FOUND`.

Two further transitions bracket the assignment. Unassigning returns an `ASSIGNED` case to `TRIAGE`; it is available only while no interview on the case has reached `COMPLETED`, it carries `expected_case_version` under the same stale-version rule, and it clears `assigned_investigator_id`, recomputes the departing investigator's `active_case_count` downward by one, and bumps the case `version`. Once assigned, the investigator personally opens the file: beginning the investigation moves `ASSIGNED` to `INVESTIGATING` and is permitted only to the acting user whose `X-User-ID` equals the case's `assigned_investigator_id`, and only while no litigation hold is in force. It increments the case's `version`.

### 3.3. Running the Investigation: Interviews and Evidence

Interviews are scheduled under an `INVESTIGATING` case by its assigned investigator, supplying the `interviewee_employee_id`, a planned `scheduled_start`, and a planned `scheduled_end`, both ISO 8601 UTC instants. Every interview record carries the id of its parent case in `case_id`, and at scheduling time the server binds the interview's `interviewer_investigator_id` to the case's assigned investigator. Two window rules apply, and both fail with `ERR_INTERVIEW_OVERLAP` (HTTP 422): the end must fall strictly after the start, and the new window must not overlap any existing `SCHEDULED` interview of the same interviewer. Overlap is judged on half-open windows — each window contains its start instant but not its end instant — so the windows overlap precisely when each one's start falls strictly before the other's end, while two windows that merely touch at an endpoint do not conflict. New interviews begin in `SCHEDULED` status.

Completion is where the evidentiary value lands. The assigned interviewer — and only that investigator — marks the interview `COMPLETED`, and three conditions must hold: the parent case is still `INVESTIGATING`; the logical clock has reached at least the `scheduled_start` (attempting earlier fails with `ERR_TIMING_VIOLATION`); and the payload carries `documentation_text` of at least fifty characters (a shorter account fails with `ERR_DOCUMENTATION_STANDARD`). A completed interview is stamped with `completed_at` from the logical clock, and the server derives `documentation_word_count` as the whitespace-delimited word count of the submitted text. When an interviewee does not appear, the interviewer marks the interview `NO_SHOW`, but only once the logical clock has passed thirty minutes beyond the `scheduled_end` — earlier attempts fail with `ERR_TIMING_VIOLATION`. A `SCHEDULED` interview may instead be cancelled outright, either by its interviewer or by an `ERManager`, moving it to `CANCELLED`. All three of `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal.

Evidence enters the file through the assigned investigator while the case is `INVESTIGATING` or in `FINDINGS_DRAFT`; at any other case status the logging request is rejected as an invalid state. Each item is tied to its case through `case_id`. Each item records `submitted_by_employee_id`, an `evidence_type` drawn from `DOCUMENT`, `EMAIL`, `CHAT_LOG`, `PHOTO`, `AUDIO`, `VIDEO`, `PHYSICAL`, or `TESTIMONY`, and a free-text `description`. The server assigns the chain-of-custody ordinal `custody_sequence`: it starts at 1 for the case's first item and increments by one per item in creation order, and it is never reused or compacted — even after an item is archived, later items never inherit earlier numbers. New items begin in `LOGGED`.

Review is bound to a single investigator. Moving an item from `LOGGED` to `UNDER_REVIEW` is permitted to the case's assigned investigator while the case is `INVESTIGATING` or in `FINDINGS_DRAFT`, and it writes the acting investigator into the item's `reviewed_by_investigator_id`. From there the segregation rule of §2.8 takes over: only that bound reviewer may admit the item, supplying a `weight` between 0.0 and 1.0 inclusive with at most two decimal places, and only that same reviewer may exclude it, supplying an `exclusion_reason` of at least twenty characters (shorter reasons fail with `ERR_DOCUMENTATION_STANDARD`). Any other investigator attempting either action — or the assigned investigator attempting to admit an item a colleague had bound — is rejected with `ERR_SEGREGATION_OF_DUTIES`. Admission moves the item to `ADMITTED`; exclusion moves it to `EXCLUDED`. Much later, once the parent case has reached `CLOSED`, an `ERManager` may archive an `EXCLUDED` item, moving it to `ARCHIVED`; the remaining items keep their custody numbers untouched. `ADMITTED`, `EXCLUDED`, and `ARCHIVED` are all terminal for the item.

Both interviews and evidence support reverse lookup beyond their parent case: interviews can be listed across cases filtered by `interviewee_employee_id` or `interviewer_investigator_id`, and evidence items across cases filtered by `submitted_by_employee_id` or `reviewed_by_investigator_id`, in addition to the per-case lists.

### 3.4. Credibility Assessment and the Two Scoring Variants

As accounts accumulate, the investigator records a credibility assessment for each person whose account matters — the subject, the reporter, or any witness — supplying the `subject_employee_id` being assessed, the `corroboration_count` of independent corroborating sources, the `contradiction_count` of material contradictions identified, and the `account_age_days` separating the alleged event from the account being given; all three counts are whole numbers of zero or more. The acting investigator is recorded as `assessor_investigator_id`, and the assessment is tied to its case through `case_id`. Every assessment is scored twice at creation, under two sanctioned variants over the same inputs, and the results are stored side by side as `score_corroboration` and `score_recency`. Which of the two scores downstream gates consult is decided by the assessment's `active_variant`, which starts at `CORROBORATION_WEIGHTED` for every case in its first investigation pass.

The `CORROBORATION_WEIGHTED` variant starts from a base of 0.50. It adds 0.10 for each independent corroborating source, counting at most four sources no matter how large the tally runs, and subtracts 0.15 for each material contradiction, counting at most three. The result is then clamped so it never falls below 0.00 and never rises above 1.00, and only after clamping is it rounded half-up to two decimal places. This variant rewards corroboration strongly and takes no account of how stale the testimony is.

The `RECENCY_WEIGHTED` variant starts from the same base of 0.50 but prices staleness in. Corroboration contributes only 0.06 per source (still counting at most four), contradictions subtract 0.10 each (still at most three), and an additional recency decay subtracts 0.005 for each day of account age, counting at most sixty days. The same clamp to the 0.00–1.00 band and the same after-clamp rounding apply. Because the decay term only ever subtracts, identical inputs under the recency variant never score higher than under the corroboration variant whenever the account is at least one day old.

The variant in force flips on reopening. When a case transitions from `CLOSED` to `REOPENED` (§3.6), every credibility assessment on the case has its `active_variant` switched to `RECENCY_WEIGHTED` and both of its scores recomputed from the stored inputs — the rationale being that accounts gathered in a reopened investigation are judged with fresh eyes on how old the underlying memories have grown.

### 3.5. Findings, Recommended Actions, and Calibration

The investigation converges on a finding. Creating the finding draft is itself the transition that moves a case from `INVESTIGATING` to `FINDINGS_DRAFT`, and it is gated on real groundwork: at least one interview on the case must have reached `COMPLETED`, and at least one evidence item must have reached `ADMITTED`. Only the case's assigned investigator may draft it, and that investigator is recorded as the finding's `author_investigator_id`. The draft is born with `substantiation_status` in `DRAFT` and `approval_status` in `PENDING_REVIEW`, carries the author's `rationale_text`, and bumps the case's `version`. The two finding dimensions are independent: `substantiation_status` tracks whether the allegation is substantiated (`DRAFT`, then one of `SUBSTANTIATED`, `UNSUBSTANTIATED`, or `INCONCLUSIVE`), while `approval_status` tracks the calibration workflow (`PENDING_REVIEW`, `CALIBRATED`, `REJECTED`, `APPROVED`). While the substantiation remains `DRAFT`, the author may keep editing `rationale_text` through the finding-edit operation.

Substantiation is the author's call, bounded by the evidence. The substantiate action takes an `outcome` of `SUBSTANTIATED`, `UNSUBSTANTIATED`, or `INCONCLUSIVE`, is permitted only to the author, and demands a `rationale_text` of at least one hundred characters — a shorter narrative fails with `ERR_DOCUMENTATION_STANDARD` before any credibility question is even consulted, per the ordering of §2.6. One consistency gate then applies: when every credibility assessment on the case has its active score — the score named by its `active_variant` — below 0.50, the outcome may not be `SUBSTANTIATED`, and the attempt fails with `ERR_INSUFFICIENT_CREDIBILITY` (HTTP 422). `UNSUBSTANTIATED` and `INCONCLUSIVE` face no such barrier.

Every finding carries one or more recommended actions, each tied to its finding through `finding_id` and proposed by the author with an `action_type` drawn from `NO_ACTION`, `COACHING`, `WRITTEN_WARNING`, `FINAL_WARNING`, `SUSPENSION`, `DEMOTION`, `TERMINATION`, or `POLICY_CHANGE`; a `severity_points` integer from 0 to 100 expressing relative harshness; and a `justification` of at least thirty characters explaining why the remedy is proportionate (shorter justifications fail with `ERR_DOCUMENTATION_STANDARD`). Actions are born `PROPOSED`. While the parent finding's `approval_status` is still `PENDING_REVIEW` or has landed in `REJECTED`, the author may withdraw a proposed action, moving it to `WITHDRAWN`. The other two exits from `PROPOSED` are decided by calibration, as described next.

Submitting for calibration moves the finding's `approval_status` from `PENDING_REVIEW` to `CALIBRATED` and the case from `FINDINGS_DRAFT` to `CALIBRATION`. The author alone may submit, and only when the substantiation has left `DRAFT`, the rationale meets its one-hundred-character standard, and at least one action on the finding remains `PROPOSED`.

Calibration is a vote, not a click. Any investigator other than the author may cast an approval vote on a `CALIBRATED` finding, subject to the §2.8 screens in their fixed order — an author voting on their own finding fails with `ERR_SEGREGATION_OF_DUTIES`, and a voter whose conflict list contains the case's subject or reporter then fails with `ERR_INVESTIGATOR_CONFLICT`. Each accepted vote appends the voter to the finding's `calibrated_by_ids` and advances the case's `version`. When a vote makes `calibrated_by_ids` reach two distinct investigators — neither of whom is the author — quorum is reached, and several things happen together: the finding's `approval_status` becomes `APPROVED`, its `calibration_score` is computed, its actions are settled, and the case moves from `CALIBRATION` to `PENDING_CLOSURE`.

The `calibration_score` measures how the proposed discipline sits against recent practice. The system gathers every other finding whose `approval_status` is `APPROVED`, whose case shares this case's `category`, and whose approval fell within the trailing three hundred sixty-five days of the logical clock; the finding under calibration never counts toward its own history. Each historical finding contributes one number: the highest `severity_points` among its `ACCEPTED` actions, or zero if it has none. When at least three historical findings exist, the reference point is the median of those numbers; when fewer than three exist, a fallback reference stands in — 10 for a `LOW` case, 30 for `MEDIUM`, 60 for `HIGH`, and 85 for `CRITICAL`. The proposal's own number is the highest `severity_points` among its `PROPOSED` actions, or zero when there are none. The deviation is the absolute difference between the proposal's number and the reference point; the score itself is one hundred minus that deviation, floored at zero so it can never go negative, divided by one hundred, and rounded half-up to two decimal places — a value in the 0.00 to 1.00 band where higher means closer to historical practice. The calibration winner is the `PROPOSED` action carrying the highest `severity_points`, with ties broken in favor of the action created earliest; that winner flips to `ACCEPTED`, and every other `PROPOSED` action on the finding flips to `SUPERSEDED`.

Rejection starts the loop over. Any investigator other than the author may reject a `CALIBRATED` finding, supplying a `rejection_reason` of at least twenty characters (shorter reasons fail with `ERR_DOCUMENTATION_STANDARD`). The rejection is recorded by landing the finding's `approval_status` in `REJECTED`, then the revision loop immediately restores it to `PENDING_REVIEW` with `substantiation_status` returned to `DRAFT` and `calibrated_by_ids` cleared, while the case drops back from `CALIBRATION` to `FINDINGS_DRAFT` with its `version` advanced. The author may then edit the rationale, re-substantiate, and submit again.

### 3.6. Holds, Closure Notices, Closure, and Reopening

An `ERManager` may suspend an active investigation: holding a case moves it from `INVESTIGATING` to `ON_HOLD` and requires a `hold_reason` of at least twenty characters (shorter reasons fail with `ERR_DOCUMENTATION_STANDARD`). The hold cascades downward — every `SCHEDULED` interview on the case is cancelled to `CANCELLED` — and for each cancelled interview the interviewer undergoes a fresh `active_case_count` recomputation, a bookkeeping pass that is not expected to change the number but keeps the derived figure current. The case's `version` advances. Resuming is the mirror: a case in `ON_HOLD` returns to `INVESTIGATING` at the manager's hand, provided no litigation hold is in force (otherwise `ERR_LITIGATION_HOLD`), again advancing the `version`. Interviews cancelled by the hold stay cancelled; the investigator schedules anew.

Once the finding is approved and the case reaches `PENDING_CLOSURE`, the people involved must be told. The manager drafts closure notices naming a `recipient_employee_id`, that recipient's `recipient_role` — `REPORTER` or `SUBJECT` — a `confidentiality_tier`, and the notice `body_text`. The recipient must actually be the case's reporter or subject employee; anyone else fails with `ERR_RECIPIENT_MISMATCH` (HTTP 422). Confidentiality is enforced in two rules, both failing with `ERR_CONFIDENTIALITY_VIOLATION` (HTTP 422): a `SUBJECT` recipient may receive at most `TIER_2_LIMITED` — never `TIER_3_FULL` — and a `TIER_1_SUMMARY` notice body must not name other involved employees. Each notice is tied to its case through `case_id` and is stamped with a `closure_sequence` equal to the case's `reopen_count` plus one at drafting time, so the first closure's notices bear sequence 1 and a reopened case's second closure bears sequence 2. Notices are born `QUEUED`.

Delivery is its own small lifecycle. Sending a `QUEUED` notice — allowed only while the parent case is still `PENDING_CLOSURE` and only when the tier remains valid for the recipient role — moves it to `SENT` and stamps `sent_at` from the logical clock. A dispatch problem is recorded by marking the notice `FAILED` with a `failure_reason`, and a failed notice may be retried back into `QUEUED`. Under a litigation hold, `LegalCounsel` may instead suppress a `QUEUED` notice, moving it to `SUPPRESSED` — one of the three exemptions to the §2.7 freeze. `SENT`, `FAILED`, and `SUPPRESSED` are terminal.

Closure itself is gated, and the gates are evaluated before the version screen per §2.6. Closing moves a case from `PENDING_CLOSURE` to `CLOSED` and demands, in order: a finding on the case whose `approval_status` is `APPROVED`; at least one notice to the `SUBJECT` whose `delivery_status` is `SENT`; and at least one `SENT` notice to the `REPORTER` — a requirement skipped entirely for anonymous cases whose `reporter_employee_id` is null. An unmet gate fails with `ERR_CLOSURE_GATE` (HTTP 422), ahead of any staleness concern. The request then carries `expected_case_version` under the §2.9 rule, with a stale value rejected as `ERR_STALE_VERSION`. A successful closure stamps `closed_at` from the logical clock and derives `days_to_close` as the calendar days between `intake_received_at` and `closed_at` for this most recent closure; it recomputes the assigned investigator's `active_case_count` downward by one; it marks every trend snapshot whose scope matches the case's manager chain or `location_code` as stale (§3.7); and it advances the case's `version`.

Closure is not always the end. A `CLOSED` case may be reopened by an `ERManager` at most twice — a case whose `reopen_count` has already reached two refuses with `ERR_REOPEN_LIMIT` (HTTP 422) — and never while a litigation hold is in force. The request carries a `reopen_reason` of at least thirty characters, enforced by the documentation standard. Reopening moves the case to `REOPENED`, increments `reopen_count` by one, retains the prior closure's `closed_at` and `days_to_close` untouched, flips every credibility assessment's `active_variant` to `RECENCY_WEIGHTED` with both scores recomputed (§3.4), marks matching trend snapshots stale, and advances the case's `version`. From `REOPENED` the case flows back through assignment exactly as if it were in `TRIAGE`, per §3.2, and a later closure mints a fresh round of notices under the next `closure_sequence`.

### 3.7. Trend Analysis by Manager and Location

The department watches for concentration: which managers and which sites generate cases. An `HRAnalyst` — or an `ERManager` — computes a trend snapshot by naming a `scope_type` of `MANAGER` or `LOCATION`, a `scope_key`, and a `window_kind` of `ROLLING_90D` or `CALENDAR_QUARTER`. The scope key must resolve: a `MANAGER` scope requires the id of an existing employee, and a `LOCATION` scope requires a `location_code` present on at least one employee; an unresolvable key fails with `ERR_SCOPE_NOT_FOUND` (HTTP 422), ahead of any headcount concern per §2.6. The snapshot is stamped with `as_of` from the logical clock, and it materializes three figures: `closed_case_count`, `substantiated_count`, and `case_rate_per_100`.

Scope membership runs through the subject of each case. A case belongs to a `MANAGER` scope when its subject employee's management chain — walked transitively upward through `manager_id` — includes the `scope_key` employee, or when the subject is that employee. A case belongs to a `LOCATION` scope when its subject's `location_code` equals the `scope_key`. Within the scope, the window decides which closures count: `ROLLING_90D` counts cases whose `closed_at` falls after the instant ninety days before `as_of` and on or before `as_of`, while `CALENDAR_QUARTER` counts cases whose `closed_at` falls on or after the first day of `as_of`'s calendar quarter and on or before `as_of`. A case that was reopened and later closed again contributes once per distinct closure. The `substantiated_count` then tallies, among those closed cases in scope, the ones whose final finding's `substantiation_status` is `SUBSTANTIATED`.

The rate's denominator is where the two window variants diverge. Under `ROLLING_90D`, the headcount is the number of employees in scope — the same manager-chain or location test applied to employee records — whose `employment_status` is `ACTIVE`, evaluated as of the snapshot instant. Under `CALENDAR_QUARTER`, the denominator is wider: employees in scope whose `employment_status` is `ACTIVE` or `ON_LEAVE` and whose `hire_date` falls on or before the quarter's final day. Because the quarterly variant counts more people for identical case data, it generally yields the lower rate. The per-scope `case_rate_per_100` divides the closed-case count by the headcount, multiplies by one hundred, and rounds half-up to two decimal places; cross-scope rollups follow the pinned sum-then-round order of §2.10. A zero headcount is an error only when there is something to explain: with no closed cases in the window the rate is simply 0.00, but with one or more closed cases the request fails with `ERR_TREND_HEADCOUNT_ZERO` (HTTP 422).

Snapshots are persisted, and they age. A snapshot's `is_stale` flag starts false; it is set true whenever an underlying case closes or reopens after the snapshot's `as_of` — the closure and reopen workflows of §3.6 bubble this invalidation up to every snapshot whose scope matches the case's manager chain or location — and it is cleared only by recomputation. Computing a fresh snapshot for an identical triple of `scope_type`, `scope_key`, and `window_kind` supersedes the prior one by marking that prior snapshot `is_stale`. Snapshots are readable by `HRAnalyst`, `ERManager`, and `LegalCounsel`, and may be filtered by `scope_type`, `scope_key`, `window_kind`, or `is_stale`.

### 3.8. Assembling the Litigation-Ready File

When a closed case is heading toward court, `LegalCounsel` assembles a litigation file package. Assembly may begin only on a case that is `CLOSED` with its `litigation_hold` set to true; the package is tied to that case through `case_id`, is born in `ASSEMBLING` status, and has the opaque counsel identifier recorded in `assembled_by`. While the package is assembling, its `package_version` — which starts at 1 — increments whenever the membership of the underlying manifest changes, so counsel can tell whether the file shifted under them.

The manifest is a deterministic projection of the case file. It contains one entry for every evidence item on the case that has not been `ARCHIVED`, one for every `COMPLETED` interview, one for every finding regardless of state, and one for every closure notice that reached `SENT`; the package's `item_count` is simply the number of entries. Entries are ordered by creation timestamp ascending, with ties broken by entry type in the fixed order evidence, then interview, then finding, then notice — an entry's `id` is never used as a sort key. The `manifest_hash` is the SHA-256 digest over the concatenation of one line per entry, each line built as an uppercase entry-type token (`EVIDENCE`, `INTERVIEW`, `FINDING`, or `NOTICE`), a colon, the entry's UUID, a colon, and the entry's `updated_at` in ISO 8601 form, with the lines joined by newline characters.

Finalizing moves the package from `ASSEMBLING` to `READY`: it requires the parent case still `CLOSED` under litigation hold, at least one manifest entry, and it computes the `manifest_hash`. Sealing then moves `READY` to `SEALED`, and it is one of the four optimistic-concurrency operations of §2.9 — the request must carry `expected_case_version` matching the case's current `version`, with a mismatch rejected as `ERR_STALE_VERSION`, because the seal pins the manifest to the case-file state counsel actually reviewed. Sealing recomputes the hash and freezes it, stamps `sealed_at` from the logical clock, and — because the seal mutates the case's file state — increments the parent case's `version`. Finally, a `SEALED` package is moved to `RELEASED` only against external authority: the request must present a `release_authority_reference` — a court order or subpoena identifier — of at least eight characters. Release is terminal for the package.

## 4. Endpoint Definitions

All endpoints below are mounted under the `/er` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource or perform an action return `200 OK`. Request payloads, preconditions, and side effects for each operation are specified in §2 and §3; this table is a navigational summary only. All list endpoints accept the `limit` and `offset` pagination parameters of §2.3 in addition to any filters named below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/er/_clock/set_current_utc` | Set the logical clock driving all timestamps, SLA arithmetic, and timing checks | ERManager |
| POST | `/er/employees` | Create an employee record | ERManager |
| GET | `/er/employees/{id}` | Fetch one employee | ERManager, Investigator, LegalCounsel, HRAnalyst |
| GET | `/er/employees` | List employees; filter by `location_code`, `department`, `employment_status`, `manager_id` | ERManager, Investigator, LegalCounsel, HRAnalyst |
| PATCH | `/er/employees/{id}` | Update mutable employee fields; manager-chain cycle check applies | ERManager |
| POST | `/er/investigators` | Create an investigator profile bound to an employee | ERManager |
| GET | `/er/investigators/{id}` | Fetch one investigator, including the derived `active_case_count` | ERManager, Investigator, LegalCounsel |
| GET | `/er/investigators` | List investigators; filter by `certification_level`, `employee_id` | ERManager, LegalCounsel, HRAnalyst |
| PATCH | `/er/investigators/{id}` | Update certification level, capacity, or conflict list | ERManager |
| POST | `/er/intake-channels` | Create an intake channel configuration | ERManager |
| GET | `/er/intake-channels` | List intake channels | ERManager, Investigator, HRAnalyst |
| POST | `/er/holiday-calendar` | Register a company holiday excluded from SLA business-day arithmetic | ERManager |
| GET | `/er/holiday-calendar` | List holiday entries | ERManager, Investigator, LegalCounsel, HRAnalyst |
| POST | `/er/cases` | Intake a new case; category and severity fall back to channel defaults | ERManager |
| GET | `/er/cases/{id}` | Fetch one case, including the computed `overdue_business_days` | ERManager, Investigator, LegalCounsel, HRAnalyst |
| GET | `/er/cases` | List cases; filter by `status`, `category`, `severity`, `assigned_investigator_id`, `subject_employee_id`, `reporter_employee_id`, `intake_channel_id`, `litigation_hold` | ERManager, Investigator, LegalCounsel, HRAnalyst |
| POST | `/er/cases/{id}/assign` | Assign an investigator; OCC-guarded | ERManager |
| POST | `/er/cases/{id}/unassign` | Remove the assignment, returning the case to triage; OCC-guarded | ERManager |
| POST | `/er/cases/{id}/begin-investigation` | Assigned investigator opens the investigation | Investigator |
| POST | `/er/cases/{id}/hold` | Place an investigating case on hold; cancels its scheduled interviews | ERManager |
| POST | `/er/cases/{id}/resume` | Resume a held case | ERManager |
| POST | `/er/cases/{id}/close` | Close a case; closure gates apply; OCC-guarded | ERManager |
| POST | `/er/cases/{id}/reopen` | Reopen a closed case; at most two reopens; flips credibility variant | ERManager |
| PATCH | `/er/cases/{id}` | Edit mutable case fields; a channel change recomputes the SLA due date | ERManager |
| POST | `/er/cases/{id}/interviews` | Schedule an interview under a case | Investigator |
| GET | `/er/cases/{id}/interviews` | List a case's interviews; filter by `status` | ERManager, Investigator, LegalCounsel |
| GET | `/er/interviews/{id}` | Fetch one interview | ERManager, Investigator, LegalCounsel |
| GET | `/er/interviews` | List interviews across cases; filter by `interviewee_employee_id`, `interviewer_investigator_id`, `status` | ERManager, Investigator, LegalCounsel |
| POST | `/er/interviews/{id}/complete` | Complete an interview with documentation | Investigator |
| POST | `/er/interviews/{id}/mark-no-show` | Mark an interview as a no-show | Investigator |
| POST | `/er/interviews/{id}/cancel` | Cancel a scheduled interview | Investigator, ERManager |
| POST | `/er/cases/{id}/evidence-items` | Log an evidence item under a case | Investigator |
| GET | `/er/cases/{id}/evidence-items` | List a case's evidence items; filter by `status`, `evidence_type` | ERManager, Investigator, LegalCounsel |
| GET | `/er/evidence-items/{id}` | Fetch one evidence item | ERManager, Investigator, LegalCounsel |
| GET | `/er/evidence-items` | List evidence across cases; filter by `submitted_by_employee_id`, `reviewed_by_investigator_id`, `status`, `evidence_type` | ERManager, Investigator, LegalCounsel |
| POST | `/er/evidence-items/{id}/begin-review` | Begin reviewing an item, binding the reviewer | Investigator |
| POST | `/er/evidence-items/{id}/admit` | Admit an item with its evidentiary weight | Investigator |
| POST | `/er/evidence-items/{id}/exclude` | Exclude an item with a reason | Investigator |
| POST | `/er/evidence-items/{id}/archive` | Archive an excluded item after case closure | ERManager |
| POST | `/er/cases/{id}/credibility-assessments` | Record a credibility assessment; both score variants computed | Investigator |
| GET | `/er/cases/{id}/credibility-assessments` | List a case's credibility assessments | ERManager, Investigator, LegalCounsel |
| GET | `/er/credibility-assessments/{id}` | Fetch one credibility assessment | ERManager, Investigator, LegalCounsel |
| GET | `/er/credibility-assessments` | List assessments across cases; filter by `subject_employee_id`, `assessor_investigator_id` | ERManager, Investigator, LegalCounsel |
| POST | `/er/cases/{id}/findings` | Create the finding draft for a case | Investigator |
| GET | `/er/cases/{id}/findings` | List a case's findings | ERManager, Investigator, LegalCounsel |
| GET | `/er/findings/{id}` | Fetch one finding | ERManager, Investigator, LegalCounsel |
| GET | `/er/findings` | List findings across cases; filter by `author_investigator_id`, `substantiation_status`, `approval_status` | ERManager, Investigator, LegalCounsel |
| PATCH | `/er/findings/{id}` | Edit the rationale while the finding is in draft | Investigator |
| POST | `/er/findings/{id}/substantiate` | Set the substantiation outcome; credibility-consistency gate applies | Investigator |
| POST | `/er/findings/{id}/actions` | Propose a recommended action under a finding | Investigator |
| GET | `/er/findings/{id}/actions` | List a finding's recommended actions; filter by `status` | ERManager, Investigator, LegalCounsel |
| POST | `/er/recommended-actions/{id}/withdraw` | Withdraw a proposed action | Investigator |
| POST | `/er/findings/{id}/submit-for-calibration` | Submit the finding into the calibration pool | Investigator |
| POST | `/er/findings/{id}/approve` | Cast a calibration approval vote; the second distinct non-author vote reaches quorum | Investigator |
| POST | `/er/findings/{id}/reject` | Reject a finding in calibration back to draft | Investigator |
| POST | `/er/cases/{id}/closure-notices` | Draft a closure notice for the reporter or subject | ERManager |
| GET | `/er/cases/{id}/closure-notices` | List a case's closure notices; filter by `delivery_status`, `recipient_role` | ERManager, LegalCounsel |
| GET | `/er/closure-notices/{id}` | Fetch one closure notice | ERManager, LegalCounsel |
| GET | `/er/closure-notices` | List notices across cases; filter by `recipient_employee_id`, `delivery_status`, `recipient_role` | ERManager, LegalCounsel |
| POST | `/er/closure-notices/{id}/send` | Send a queued notice | ERManager |
| POST | `/er/closure-notices/{id}/mark-failed` | Mark a queued notice as failed | ERManager |
| POST | `/er/closure-notices/{id}/retry` | Retry a failed notice | ERManager |
| POST | `/er/closure-notices/{id}/suppress` | Suppress a queued notice under litigation hold | LegalCounsel |
| POST | `/er/trend-snapshots` | Compute and persist a trend snapshot for a scope under a window variant | HRAnalyst, ERManager |
| GET | `/er/trend-snapshots` | List trend snapshots; filter by `scope_type`, `scope_key`, `window_kind`, `is_stale` | HRAnalyst, ERManager, LegalCounsel |
| GET | `/er/trend-snapshots/{id}` | Fetch one trend snapshot | HRAnalyst, ERManager, LegalCounsel |
| POST | `/er/cases/{id}/litigation-packages` | Start assembling a litigation-ready file package | LegalCounsel |
| GET | `/er/cases/{id}/litigation-packages` | List a case's litigation packages; filter by `status` | LegalCounsel, ERManager |
| GET | `/er/litigation-packages/{id}` | Fetch one litigation package | LegalCounsel, ERManager |
| POST | `/er/litigation-packages/{id}/finalize` | Finalize the manifest and compute its hash | LegalCounsel |
| POST | `/er/litigation-packages/{id}/seal` | Seal the package, freezing the hash; OCC-guarded on the parent case | LegalCounsel |
| POST | `/er/litigation-packages/{id}/release` | Release a sealed package against external authority | LegalCounsel |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions under which each error is raised are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LITIGATION_HOLD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_INVESTIGATOR_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CONFIDENTIALITY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INTERVIEW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_TIMING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_DOCUMENTATION_STANDARD` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CREDIBILITY` | 422 Unprocessable Entity |
| `ERR_CLOSURE_GATE` | 422 Unprocessable Entity |
| `ERR_REOPEN_LIMIT` | 422 Unprocessable Entity |
| `ERR_RECIPIENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SCOPE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_TREND_HEADCOUNT_ZERO` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
