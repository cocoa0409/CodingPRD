# OSHA Recordkeeping & Workplace Safety API — Product Requirements Document

## 1. Introduction

Employers carry a continuous legal duty to record workplace injuries and illnesses: every incident must be taken in, evaluated for recordability against a seven-day determination clock, carried on the establishment's OSHA 300 log with accurate counts of days away and restricted duty, rolled up into the 300A annual summary, and certified and posted inside a fixed February-to-April window. Alongside the log itself, the safety office must investigate root causes, drive corrective actions to verified completion under segregation of duties, report severe injuries to the agency against unforgiving eight- and twenty-four-hour clocks, and manage inspections, citations, contests, and abatement. Errors compound: a single missed deadline or an unsegregated signature can invalidate a filing or draw a citation of its own.

This document specifies an API for an employer safety office that operates that entire recordkeeping and compliance surface. The system serves four operator roles — platform administrators, safety officers, recordkeeping coordinators, and investigating supervisors — and runs on a controllable logical clock so that deadline-driven behavior (recordability windows, posting windows, contest windows, overdue sweeps) is deterministic. All endpoints are mounted under the `/safety` prefix. The specification covers case intake and classification, day-count accounting with stored and projected variants, annual rate computation and certification, severe-injury reporting, inspection and citation lifecycles, and the derived establishment risk posture that aggregates all of these signals.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. The system recognizes exactly four roles: `PlatformAdmin`, `SafetyOfficer`, `RecordkeepingCoordinator`, and `InvestigatingSupervisor`. A request missing either header, or naming a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. Each operation is then restricted to the roles enumerated in §4; an authenticated operator attempting an operation outside their role's grant is rejected with `ERR_FORBIDDEN`.

For all four roles — `PlatformAdmin`, `SafetyOfficer`, `RecordkeepingCoordinator`, and `InvestigatingSupervisor` alike — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; there is no user resource in the system. The server records the identifier on the resources the operator touches: as `lead_supervisor_id` on an investigation, as `assigned_to`, `completed_by`, and `verified_by` on a corrective action, as `prepared_by` and `certified_by` on an annual summary, and as `approved_by` on an hour log. Segregation-of-duties and lead-identity checks compare those stored fields against the incoming `X-User-ID`; no check ever compares `X-User-ID` against an entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A non-integer value for either parameter, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`; the same rejection applies to any integer-typed filter query parameter (such as `year` or `log_year`) that fails to parse. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order, ties broken by creation order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Scheduled Compliance Sweeps

The system runs on a logical clock, not wall-clock time. At startup the clock reads 2026-08-01T00:00:00Z, and it never silently falls back to wall-clock time thereafter; every server-stamped timestamp (`reported_at`, `opened_at`, `certified_at`, `posted_at`, `closed_on`, and the like) derives from this clock. A `PlatformAdmin` repositions the clock through an administrative capability that accepts a `to_iso8601` instant — earlier or later than the current reading alike — and answers with the resulting `current_utc`.

Every clock repositioning triggers a compliance sweep. Each corrective action whose `due_date` falls before the new clock date and that still sits in `OPEN` or `REOPENED` moves to `OVERDUE`, and each citation whose `abatement_due_date` has passed without abatement moves from `ABATEMENT_PENDING` to `OVERDUE`. Every such transition recomputes the owning establishment's posture and risk score (§2.7), so a single clock advance can move several establishments from `CLEAR` to `WATCH` or beyond. The sweep also refreshes every establishment's `current_year_hours` against the new clock year.

### 2.5. Common Resource Properties and Mutation Semantics

All primary resources — Company, Establishment, Employee, IncidentCase, IncidentInvestigation, CorrectiveAction, AnnualSummary, EstablishmentHourLog, SevereInjuryReport, Inspection, and Citation — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed counter that starts at 1 on creation, increments on every modification, and backs the optimistic concurrency control of §2.8.

Day-count entries are the sole exception: a CaseDayCountEntry carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. Every explicit case operation — classification, reclassification, day-count closure, and finalization — increments the case's `version` by exactly one, and summary certification increments the summary's `version` by exactly one.

### 2.6. Precision, Rounding, and Rate Conventions

Two precision regimes cover the system. Rates and scores — `trir`, `dart_rate`, and the establishment `risk_score` — are published to exactly one decimal place using round-half-up. Day counts, case totals, employment figures, and hours are integers and involve no rounding. The single exception among integer fields is `annual_avg_employment`: the mean of the twelve monthly `employment_count` figures, rounded half-up to a whole number. Monetary penalty amounts (`proposed_penalty_usd`, `final_penalty_usd`) are non-negative numbers.

Incident rates are standardized against a base of 200,000 hours — the equivalent of one hundred full-time employees working a full year — so that establishments of different sizes can be compared on equal footing. When the denominator hours for a year are zero, a published rate is null rather than zero: the annual-summary preparation step treats zero hours as a hard error (§3.7), while the live rate read-out simply returns null rates for that year.

### 2.7. Establishment Posture and the Weighted Risk Score

Each establishment carries a computed `risk_score` and a derived compliance `posture` of `CLEAR`, `WATCH`, or `ELEVATED`; a new establishment starts at `CLEAR` with a score of zero. The score weighs five signals: 2.0 times the live TRIR for the logical clock's current year, plus 3.0 times the live DART rate for that year, plus 5.0 for each corrective action currently in `OVERDUE`, plus 8.0 for each citation currently in `OVERDUE`, plus 10.0 for each severe-injury report filed `LATE` whose `reported_to_agency_at` falls at or after the instant exactly 365 days before the logical clock's current reading. The result is kept to one decimal place, rounding half up. When the establishment has zero approved hours in the current year, the live rates enter this formula as 0.0 — not null.

Posture derives from the score with inclusive boundaries: a score of 50.0 or higher yields `ELEVATED`; a score of 25.0 or higher but below 50.0 yields `WATCH`; anything below 25.0 yields `CLEAR`. Score and posture are recomputed whenever a contributing signal changes — a corrective action or citation turning overdue, a late severe-injury report being filed, a verification, an abatement, a cancellation resolving an open item, or a case classification.

### 2.8. Optimistic Concurrency Control

Two write operations carry explicitly pinned optimistic-concurrency contracts. Classifying a case (the initial determination or a re-determination) requires the request to carry `expected_case_version` holding the case `version` the client last observed; if another writer has advanced the case's version since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the case predates that writer's update. Certifying an annual summary likewise requires `expected_summary_version`: a case mutation after preparation bounces the summary back to `DRAFT` and advances its version, so a client certifying against a pre-mutation version observes exactly this stale-version rejection, also `ERR_STALE_VERSION` (HTTP 412).

The remaining case-mutation operations — opening reclassification, closing the day count, and finalization — also require `expected_case_version` in the request and enforce the same `ERR_STALE_VERSION` (HTTP 412) rejection when the supplied value does not match the case's current `version`. Endpoints not named here do not accept a version field. On every version-guarded operation the version comparison runs after request-body shape validation and before the state-admissibility check, so a mismatched version is reported as `ERR_STALE_VERSION` even when the target no longer sits in a state that admits the transition.

### 2.9. Validation Order and Nested Resource Retrieval

Requests are validated in a fixed order, and a failure at any step short-circuits everything after it. First comes authentication: the presence and validity of the two identity headers, failing with `ERR_UNAUTHENTICATED`. Second, authorization: the acting role must be permitted on the endpoint, failing with `ERR_FORBIDDEN`. Third, resource existence along the URL path, checked left to right — for a nested path such as `/safety/cases/{caseId}/day-entries/{entryId}/void`, the case is located before the entry is, and the first identifier that does not resolve, or that does not belong to the declared parent chain within the establishment scope, fails with `ERR_NOT_FOUND`. Fourth, state admissibility: the target resource must currently sit in a state from which the requested transition exists, failing with `ERR_INVALID_STATE`.

Business rules then run in their pinned order: severe-injury clock consistency (`ERR_SEVERE_REPORT_REQUIRED`); the temporal windows (`ERR_RECORDABILITY_WINDOW_PASSED`, `ERR_POSTING_WINDOW`, `ERR_CONTEST_WINDOW_PASSED`); referential integrity across entities (`ERR_CROSS_COMPANY_REFERENCE`, `ERR_LINKAGE_XOR`, `ERR_INVESTIGATION_OPEN`); uniqueness (`ERR_DUPLICATE`); segregation of duties (`ERR_DUTY_SEGREGATION`); day-interval validity (`ERR_DAY_INTERVAL_INVALID`); hour-log completeness (`ERR_HOURS_INCOMPLETE`); and penalty validity (`ERR_PENALTY_INVALID`). Request-body well-formedness — malformed JSON, missing required fields, enum values outside the declared sets, or unparsable ISO dates and datetimes — is rejected with `ERR_INVALID_REQUEST`; these shape checks are evaluated after the authentication, authorization, and URL-path existence steps, and before state admissibility and any business rule.

## 3. Business Logic & Workflows

### 3.1. Establishing the Organization: Companies, Establishments, and Employees

A `PlatformAdmin` provisions the organizational hierarchy. Creating a company requires `legal_name` and `fein`; the Federal Employer Identification Number must be unique across companies, and a duplicate submission is rejected with `ERR_DUPLICATE`. The establishments and employees of a company can each be listed back from the company resource, the employee listing accepting an optional `employment_status` filter.

Establishments sit beneath companies. Creating one names the owning company via `company_id` and supplies `site_name`, a `naics_code` of exactly six digits, a two-letter `state_code`, and a `size_class` of `SMALL` (1–19 employees), `STANDARD` (20–249 employees), or `LARGE` (250 or more employees) — the size class drives the establishment's electronic-submission duty. An establishment in a low-hazard industry may be flagged `is_partially_exempt` at creation, defaulting to false; an exempt establishment does not maintain a 300 log, which blocks recordability classification outright (§3.2), but it remains obliged to report severe injuries to the agency (§3.6). A new establishment starts with `posture` `CLEAR`, a `risk_score` of zero, and `current_year_hours` of zero.

Employees also belong to a company. A `RecordkeepingCoordinator` or `PlatformAdmin` registers an employee with `company_id`, `full_name`, the `job_title` as it should appear on the 300 log, and a `hire_date` in ISO `YYYY-MM-DD` form; `employment_status` defaults to `ACTIVE`, may be supplied at creation with any declared value, and may later become `SEPARATED`. Updating an employee record accepts any of `full_name`, `job_title`, and `employment_status`. Marking an employee `SEPARATED` carries a recordkeeping consequence: every non-finalized case belonging to that employee immediately treats its day counting as closed (§3.3).

### 3.2. Injury Intake and the Seven-Day Recordability Determination

A `SafetyOfficer` or `RecordkeepingCoordinator` opens an incident case by supplying the `establishment_id` whose 300 log will carry it, the injured worker's `employee_id`, the `occurred_at` instant of injury or illness onset, a free-text `description` of what happened, the affected `body_part`, and an `event_type` of `INJURY`, `SKIN_DISORDER`, `RESPIRATORY`, `POISONING`, `HEARING_LOSS`, or `OTHER_ILLNESS`. The employee must belong to the same company as the establishment; a cross-company pairing is rejected with `ERR_CROSS_COMPANY_REFERENCE`. Two flags ride on intake: `is_privacy_case`, defaulting to false, marks a privacy-concern case whose employee name is withheld from the 300 log with the text 'PRIVACY CASE' substituted, and `is_severe_event`, defaulting to `NONE`, flags a `FATALITY`, `INPATIENT_HOSPITALIZATION`, `AMPUTATION`, or `EYE_LOSS` for the agency-reporting clock of §3.6.

Intake is atomic. As soon as the required intake fields validate, the system moves the case from `INTAKE` to `PENDING_REVIEW`, mints a `case_number` of the form `CASE-<establishment_seq>-<yyyy>-<nnn>` — where `<establishment_seq>` is the establishment's creation-order sequence number, `<yyyy>` is the four-digit calendar year of `occurred_at`, and `<nnn>` is a per-establishment case counter starting at 001 — stamps `reported_at` from the logical clock, fixes `log_year` to the calendar year of `occurred_at` — determining which 300 log carries the case — and computes the `recordability_deadline` as the instant exactly seven days (7 × 24 hours) after `occurred_at`; a determination landing at exactly that instant is still on time, and only a strictly later attempt is late. A fresh case has `classification` `NONE`, `is_recordable` and `is_dart` both false, and `revision_index` zero. The cases of an establishment can be listed with optional `status` and `log_year` filters, and an employee's case history can be listed with an optional `log_year` filter.

The recordability determination itself is a `SafetyOfficer` duty performed against a case in `PENDING_REVIEW`, and the request must carry `expected_case_version` under the concurrency discipline of §2.8. Classifying with `MEDICAL_TREATMENT`, `JOB_TRANSFER_RESTRICTION`, `DAYS_AWAY`, or `DEATH` moves the case to `RECORDABLE`; classifying with `FIRST_AID_ONLY` moves it to `NOT_RECORDABLE`, a terminal state. Three guards apply at determination. An establishment flagged `is_partially_exempt` does not keep a 300 log, so classification there is refused with `ERR_ESTABLISHMENT_EXEMPT` — severe-injury reporting obligations nonetheless remain; this refusal is evaluated before the window check. The determination must land by the `recordability_deadline`; a late attempt fails with `ERR_RECORDABILITY_WINDOW_PASSED`, with a single carve-out: a `DEATH` classification is accepted even after the window. Both the exemption refusal and the window check apply only to the initial determination out of `PENDING_REVIEW`; a re-determination from `RECLASSIFIED` is subject to neither. Privacy status never blocks classification — `is_privacy_case` governs log display only, and the classification request may itself update that flag. A recordable classification sets `is_recordable` true and sets `is_dart` true exactly when the class is `JOB_TRANSFER_RESTRICTION`, `DAYS_AWAY`, or `DEATH`; a first-aid outcome leaves both flags false.

Determinations are not always final. A line-of-duty correction — classifying a `RECORDABLE` case straight to `NOT_RECORDABLE` via `FIRST_AID_ONLY` — is permitted only while `revision_index` is still zero; a case that has already been through the loop must round-trip through `RECLASSIFIED` again, and such a correction voids every `ACTIVE` day entry and zeroes the day counts. The full loop begins when a `SafetyOfficer` opens reclassification on a `RECORDABLE` case, which requires either at least one non-voided day-count entry on the case or a newly discovered fact documented as a `new_classification` in the request; an attempt with neither fails with `ERR_INVALID_STATE`. The case moves to `RECLASSIFIED`, `revision_index` increments, existing `ACTIVE` day entries survive, and fresh entries may still be attached while the case sits in `RECLASSIFIED`. Reclassification is blocked while the annual summary for the case's `log_year` is `POSTED`, failing with `ERR_SUMMARY_LOCKED`, a check evaluated after the entries-or-new-fact requirement.

From `RECLASSIFIED`, a fresh classification with any value different from the current one returns the case to `RECORDABLE` — repeating the current class is rejected with `ERR_INVALID_STATE` — and recomputes `is_recordable`, `is_dart`, and the day-count rollup under the 180-day ceiling of §3.3. A `FIRST_AID_ONLY` outcome from `RECLASSIFIED` instead lands in `NOT_RECORDABLE` unconditionally, voiding all `ACTIVE` day entries and zeroing the counts. Every classification or reclassification also recomputes the totals of any `DRAFT` or `PREPARED` summary covering the case's `log_year` — advancing that summary's `version` by one on each recomputation — bounces a `PREPARED` summary back to `DRAFT` (clearing `prepared_by` and discarding its provisional rates per §3.7), marks a `CERTIFIED` summary for the year as requiring amendment via an internal `amendment_required` flag that is not serialized on the summary resource, and recomputes the establishment's posture.

### 3.3. Counting Days Away and Restricted-Duty Days

Recordable cases accumulate day counts through day-count entries. A `SafetyOfficer` attaches an interval with a `day_type` of `DAYS_AWAY` or `RESTRICTED` and inclusive `start_date` and `end_date` ISO dates; the entry's `calendar_days` is the number of calendar days the interval spans counting both endpoints — a Monday-through-Friday interval counts five days, and counting is by calendar day rather than scheduled work day. An `end_date` earlier than its `start_date` is rejected with `ERR_DAY_INTERVAL_INVALID`, as is an interval that overlaps another `ACTIVE` interval of the same `day_type` on the same case; raw overlapping accrual across the two types is tolerated transiently because the combined ceiling is applied only at rollup. Entries are born `ACTIVE`, and voiding one moves it to `VOIDED` and excludes it from every rollup; voiding is rejected with `ERR_INVALID_STATE` once the case is `FINALIZED`, or when the entry is no longer `ACTIVE`. A case's entries can be listed with an optional `status` filter.

The stored counts on the case follow a pinned rollup. The raw days-away figure is the sum of `calendar_days` over the case's `ACTIVE` entries of type `DAYS_AWAY`, and the raw restricted figure is the analogous sum over `RESTRICTED` entries. A combined ceiling of 180 calendar days then applies to the two figures together: when the two raw sums total 180 or less, `days_away_count` and `restricted_days_count` store the raw sums as they are; when they exceed it, `days_away_count` stores the smaller of the raw days-away sum and 180, and `restricted_days_count` stores whatever of the 180-day allowance remains after that stored days-away figure — days away take precedence over restricted days under the cap. The rollup recomputes on every entry creation, every void, and every reclassification, and each recomputation bounces a `PREPARED` summary for the year back to `DRAFT`.

Alongside the stored counts, reading a case exposes two read-time projections, `projected_days_away_count` and `projected_restricted_days_count`. For any `ACTIVE` entry whose `end_date` lies strictly after the logical clock's current date, the projection counts only the days from `start_date` through the clock date inclusive — an accrual-to-date view — while entries already ended count in full; an entry whose `start_date` still lies after the clock date contributes zero, and the combined 180-day ceiling with days-away precedence is applied after this truncation. Projections are never stored and never feed the annual summary, so identical entries can yield projected figures below the recorded ones while an interval is still running, and the two variants agree once every entry's end lies in the past. The annual summary always consumes the stored `days_away_count` and `restricted_days_count`, never the projections.

Day counting closes — `day_count_closed` turns true — under any of three conditions: a `SafetyOfficer` explicitly closes the count when the worker returns to full duty, a version-checked operation carrying `expected_case_version` admitted only while the case is `RECORDABLE` or `RECLASSIFIED` and failing otherwise with `ERR_INVALID_STATE`; the capped combined count reaches the 180-day ceiling; or the employee's `employment_status` becomes `SEPARATED`, which closes the counts on all of that employee's non-`FINALIZED` cases at once (§3.1). Closure is one of the gates on finalization (§3.9), but it is not a lock on the entries themselves: a further entry may still be attached to a closed case while it remains `RECORDABLE` or `RECLASSIFIED`, and the stored rollup then recomputes as usual.

### 3.4. Investigation and Root-Cause Discipline

Exactly one investigation may be opened per case — a second attempt fails with `ERR_DUPLICATE` — and it may be opened whatever the case's current status. A `SafetyOfficer` opens it by naming the `case_id` and the `lead_supervisor_id`, the opaque operator identifier of the `InvestigatingSupervisor` who will lead; the investigation opens in `OPEN` with `opened_at` stamped from the logical clock. Reading a case's investigation returns a possibly empty array holding at most one element.

Root-cause submission belongs to the recorded lead alone. Submitting a `root_cause` — one of `HUMAN_FACTOR`, `EQUIPMENT`, `PROCESS`, `ENVIRONMENT`, `TRAINING`, or `INDETERMINATE` — together with non-empty `contributing_factors` moves the investigation from `OPEN` to `ROOT_CAUSE_SUBMITTED`; both fields are required to be non-empty at submission. A submission from anyone other than the recorded `lead_supervisor_id` is rejected with `ERR_NOT_INVESTIGATION_LEAD`. If the findings need rework, the same recorded lead may reopen the investigation, returning it to `OPEN`; the previously submitted `root_cause` and `contributing_factors` are retained — clearing them is not permitted.

Closure belongs to a `SafetyOfficer` and proceeds only from `ROOT_CAUSE_SUBMITTED`. One substantive bar applies: a case whose classification is not `DEATH` may not close on an `INDETERMINATE` root cause — such a close fails with `ERR_INVALID_STATE`; only a fatality investigation may close indeterminate. A successful closure stamps `closed_at`, lands the investigation in the terminal `CLOSED` state, and unblocks case finalization (§3.9).

### 3.5. Corrective Actions from Assignment to Verification

Corrective actions track hazard-abatement work on an establishment. A `SafetyOfficer` creates one with `establishment_id`, a `description` of the abatement action, the `assigned_to` operator identifier responsible for completion, a `due_date`, and a `priority` of `LOW`, `MEDIUM`, `HIGH`, or `IMMINENT_DANGER`; the `due_date` must fall strictly after the logical clock's current date at creation, failing otherwise with `ERR_INVALID_REQUEST`. Every action links to exactly one trigger: a `case_id` when it arises from an incident, or a `citation_id` when it arises from a citation — a supplied link that does not resolve, or that belongs to a different establishment than `establishment_id`, fails with `ERR_NOT_FOUND`, and supplying both or neither is rejected with `ERR_LINKAGE_XOR`, the exclusivity check running after link resolution. New actions sit in `OPEN`. The actions of an establishment, those linked to a case, and those linked to a citation can each be listed, the establishment listing accepting an optional `status` filter.

Completion is recorded by a `SafetyOfficer` submitting `completed_by`, which must match the action's `assigned_to` — a mismatch is rejected with `ERR_NOT_ASSIGNEE`. The action moves to `COMPLETED` with `completed_at` stamped and `completed_by` recorded. Verification is a second, segregated duty: the verifying operator is the acting operator identified by `X-User-ID`, who must differ from the operator recorded in `completed_by`, and for case-linked actions must also differ from the linked case's investigation `lead_supervisor_id`; either collision is rejected with `ERR_DUTY_SEGREGATION`. A successful verification stamps `verified_by` with the acting operator's identifier, moves the action to the terminal `VERIFIED` state, and recomputes the establishment's posture. A reviewer who instead rejects the work — again the acting operator, and again someone other than the completer, a collision failing with `ERR_DUTY_SEGREGATION` — moves the action to `REOPENED`, clearing `completed_at` and `completed_by`; from `REOPENED` the assignee completes the action afresh under the same assignee rule, re-stamping `completed_at`. An action still in `OPEN` may instead be cancelled outright, landing in the terminal `CANCELLED` state with a posture recompute.

The logical-clock sweep of §2.4 moves any action whose `due_date` has passed from `OPEN` — or from `REOPENED` — into `OVERDUE`, recomputing posture and feeding the 5.0-per-overdue-action term of the risk score. Requesting any of these transitions from a state that does not support it fails with `ERR_INVALID_STATE`.

### 3.6. Severe-Injury Reporting to the Agency

When a case's `is_severe_event` is anything other than `NONE`, federal reporting clocks apply — even at partially exempt establishments, which keep no 300 log but must still report. A `SafetyOfficer` files the agency report under the case — whatever the case's current status and whatever its `is_severe_event` value — with a `report_kind` of `FATALITY`, `INPATIENT_HOSPITALIZATION`, `AMPUTATION`, or `EYE_LOSS` recorded independently of the case's `is_severe_event`, an `occurred_at` that must equal the case's own `occurred_at`, and the `reported_to_agency_at` instant at which the employer notified the agency. Only one report may exist per case, a duplicate failing with `ERR_DUPLICATE`, and inconsistent report timestamps fail with `ERR_SEVERE_REPORT_REQUIRED`.

The reporting `deadline` is computed at creation: exactly eight hours after `occurred_at` for a `FATALITY`, and exactly twenty-four hours after for the other three kinds. The `within_clock` flag records whether `reported_to_agency_at` fell at or before the deadline — the boundary is inclusive and the comparison is to the second — and the report's `status` is fixed atomically at creation to `TIMELY` or `LATE` accordingly. The report is an immutable record: both values are terminal and no transition exists.

A `LATE` filing is a compliance event in its own right. It recomputes the establishment's posture at creation and contributes ten points per late report within the trailing 365 days to the risk score of §2.7. The report also gates finalization — a case flagged with a severe event cannot finalize until its report exists (§3.9). Reading a case's severe-injury report returns a possibly empty array holding at most one element.

### 3.7. Monthly Hour Logs and the Annual Summary Cycle

The 300A annual summary rests on monthly hour logs. A `RecordkeepingCoordinator` files one log per establishment per month — `establishment_id`, `year`, `month` from 1 through 12, `hours_worked`, and `employment_count`, both counts non-negative — and the combination of establishment, year, and month is unique, duplicates failing with `ERR_DUPLICATE`. Logs are born `DRAFT`; approving one requires non-negative `hours_worked` and `employment_count`, stamps `approved_by`, moves the log to `APPROVED`, and — when the log's year matches the logical clock's current calendar year — recomputes the establishment's `current_year_hours`, the sum of `hours_worked` over `APPROVED` or `LOCKED` logs for that clock year. An approved log can be reopened to `DRAFT` only while no summary for that establishment-year sits in `PREPARED`, `CERTIFIED`, or `POSTED`, failing otherwise with `ERR_SUMMARY_LOCKED`; reopening clears `approved_by` and likewise recomputes `current_year_hours`. An establishment's logs can be listed with optional `year` and `status` filters.

A draft annual summary for an establishment and calendar `year` is created by a `RecordkeepingCoordinator` — one summary per establishment-year, duplicates failing with `ERR_DUPLICATE` — and at creation the system fixes the posting window: `posting_window_open` at 00:00:00 UTC on February 1 of the following year, `posting_window_close` at 23:59:59 UTC on April 30 of that year. Preparation is admitted from `DRAFT` or `AMENDED`, runs the rollup, and is gated twice: every case of the establishment whose `log_year` matches must be out of `INTAKE` and `PENDING_REVIEW`, unresolved cases failing with `ERR_CASES_UNRESOLVED`, and all twelve monthly logs must exist in `APPROVED` or `LOCKED` status with total hours greater than zero, failing otherwise with `ERR_HOURS_INCOMPLETE`. The prepared summary counts `total_recordable_cases` and `total_dart_cases` over the year's cases, sums the per-case capped `days_away_count` and `restricted_days_count` into `total_days_away` and `total_restricted_days` — each case's counts are capped first, then summed, never summed raw and capped afterwards — averages the twelve `employment_count` figures into `annual_avg_employment` rounded half-up to a whole number, and totals `hours_worked` into `total_hours_worked`. Preparation stamps `prepared_by`, moves the summary from `DRAFT` to `PREPARED`, and stores provisional rates: `trir` as the recordable-case count multiplied by 200,000 and divided by the total hours worked, and `dart_rate` as the same expression over the DART-case count, each rounded half-up to one decimal place. While the summary sits in `PREPARED` these rates are live reflections of the underlying cases: any case mutation for the year — a classification, a reclassification, or a day-entry change — bounces the summary back to `DRAFT`, clearing `prepared_by` and discarding the provisional figures.

Certification is the segregated second half of the cycle, performed by a `SafetyOfficer` acting as the certifying company executive, and carries the concurrency discipline of §2.8 via `expected_summary_version`. The certifier must differ from `prepared_by` — a collision fails with `ERR_DUTY_SEGREGATION` — and no case for the establishment-year may have mutated since preparation: the summary's internal `prepared_version_pin` — bookkeeping never serialized on the summary resource — captures the case-set version at preparation as the sum of the year's case `version` counters, and a mismatch at certification fails with `ERR_SUMMARY_STALE`. On success the summary moves to `CERTIFIED`, `certified_by` and `certified_at` are stamped, the rates freeze into their certified snapshot — later case changes never alter a certified summary's `trir` or `dart_rate` — and every `APPROVED` hour log for the year locks automatically to `LOCKED`, the terminal hour-log state.

Posting is the public act: a `RecordkeepingCoordinator` posts a `CERTIFIED` summary only while the logical clock sits inside the posting window, boundaries inclusive; an attempt outside it fails with `ERR_POSTING_WINDOW`, and success stamps `posted_at` and lands the summary in the terminal `POSTED` state. A certified summary can instead be amended once the posting window has passed, or when a case mutation after certification marked it as requiring amendment — amendment is admitted only from `CERTIFIED`, an attempt when neither condition holds failing with `ERR_INVALID_STATE`: amendment moves it to `AMENDED` and recomputes the totals and rates, after which the cycle must run preparation, certification, and posting again inside a window or the summary remains on record as `AMENDED`. The summaries of an establishment can be listed with optional `year` and `status` filters.

Separately from the summary cycle, a live rates read-out answers the live variant for the `year` supplied as a required query parameter — a missing or unparsable `year` failing with `ERR_INVALID_REQUEST` — always recomputed from current data, counting cases by their latest classification — including reclassified cases not yet re-determined — and drawing hours only from `APPROVED` or `LOCKED` logs. It returns `trir`, `dart_rate`, `total_recordable_cases`, `total_dart_cases`, and `total_hours_worked`, with null rates when the year's hours are zero.

### 3.8. Inspections, Citations, Contests, and Abatement

An inspection opens on an establishment with an `opened_on` date, an `inspection_type` of `PROGRAMMED`, `COMPLAINT`, `REFERRAL`, `FATALITY_CATASTROPHE`, or `FOLLOW_UP`, and a `scope` of `COMPREHENSIVE`, `PARTIAL`, or `RECORDS_ONLY`; it sits in `OPEN` until resolved. A `SafetyOfficer` may close an inspection without citations only while none exist — once any citation exists the close fails with `ERR_CITATIONS_EXIST` — and a successful close stamps `closed_on` with the logical clock's current calendar date in ISO `YYYY-MM-DD` form and lands the inspection in the terminal `CLOSED_NO_CITATION` state. The first citation issued under an inspection automatically moves it to the terminal `CITATIONS_ISSUED` state. An establishment's inspections can be listed with an optional `status` filter, and an inspection's citations can be listed the same way.

Issuing a citation is admitted while the inspection is `OPEN` or `CITATIONS_ISSUED` — issuing under a `CLOSED_NO_CITATION` inspection fails with `ERR_INVALID_STATE` — and names the `inspection_id`, the `standard_cited` (for example '29 CFR 1910.134'), a `violation_type` of `OTHER_THAN_SERIOUS`, `SERIOUS`, `WILLFUL`, `REPEAT`, or `FAILURE_TO_ABATE`, a non-negative `proposed_penalty_usd`, and the `abatement_due_date`; a negative proposed penalty fails with `ERR_PENALTY_INVALID`. The citation lands in `ISSUED`, and the system computes its `contest_deadline`: day zero is the citation's creation date itself — or the following Monday when creation falls on a weekend — and counting fifteen working days, Mondays through Fridays only, forward from day zero yields the deadline date, stamped at 23:59:59 UTC. A citation created on Monday 2026-08-03 therefore carries a contest deadline of Monday 2026-08-24 at 23:59:59Z, and one created on Saturday 2026-08-01 starts its count on that same Monday and lands on the same deadline.

From `ISSUED` the employer has two routes. Contesting the citation — only while the logical clock has not passed the `contest_deadline`, failing later with `ERR_CONTEST_WINDOW_PASSED` — stamps `contested_at` and moves the citation to `CONTESTED`. Accepting the citation as a final order is available whether or not the contest window has lapsed: it moves the citation to `FINAL_ORDER`, fixes `final_penalty_usd` at the proposed amount, and starts the abatement clock. A contest resolves in one of three ways supplied as `outcome`. `AFFIRMED` moves the citation to `FINAL_ORDER` with the proposed penalty as the final one. `MODIFIED` also moves it to `FINAL_ORDER` but requires an explicit, non-negative `final_penalty_usd` in the payload — its absence, or a negative value, fails with `ERR_PENALTY_INVALID` — and starts the abatement clock from the resolution date. `VACATED` lands the citation in the terminal `VACATED` state, removes it from penalty totals, and automatically cancels any corrective actions linked to it that are not already `VERIFIED` or `CANCELLED`. Immediately after a citation reaches `FINAL_ORDER` with an `abatement_due_date` set, the system moves it on to `ABATEMENT_PENDING`.

Abatement certification requires a non-empty `abatement_evidence` payload, a missing or empty payload failing with `ERR_INVALID_REQUEST`. Filed while the logical clock date is on or before the `abatement_due_date`, it stamps `abated_at` and lands the citation in the terminal `ABATED` state. The clock sweep of §2.4 moves an unabated citation from `ABATEMENT_PENDING` to `OVERDUE` once the due date passes, recomputing posture and feeding the 8.0-per-overdue-citation term of the risk score; a citation past its due date is therefore abated from `OVERDUE` rather than from `ABATEMENT_PENDING`. Late abatement remains available and still stamps `abated_at`, but it records a `late_abatement` flag and notes `FAILURE_TO_ABATE` exposure on the inspection, both held as internal bookkeeping and not serialized on the resources. Abatement never auto-verifies linked corrective actions — bypassing their segregation-of-duties checks that way is forbidden; the linked actions remain in their own lifecycle and only an `abatement_satisfied` flag, likewise internal and not serialized, is set. Either path to `ABATED` recomputes the establishment's posture.

### 3.9. Case Finalization and Record Locking

Finalization locks a case forever. A `SafetyOfficer` finalizes a `RECORDABLE` case — the request carrying `expected_case_version` per §2.8 — only when every gate passes, the gates evaluated in this pinned order: a case whose `is_severe_event` is not `NONE` has its agency report on file, failing otherwise with `ERR_SEVERE_REPORT_REQUIRED`; the case's investigation exists and is `CLOSED`, failing otherwise with `ERR_INVESTIGATION_OPEN`; `day_count_closed` is true, failing otherwise with `ERR_DAY_COUNT_OPEN`; and every corrective action linked to the case sits in `VERIFIED` or `CANCELLED`, failing otherwise with `ERR_CORRECTIVE_ACTION_OPEN`. A finalized case lands in the terminal `FINALIZED` state: no further day entries and no further reclassification are possible. `NOT_RECORDABLE` is the other terminal state, reserved for cases that never belonged on the log.

## 4. Endpoint Definitions

Operations that create a new resource — a company, establishment, employee, case, day-count entry, investigation, corrective action, summary, hour log, severe-injury report, inspection, or citation — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, response contents, and side effects are defined by the workflows of §3; the table below is the HTTP contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/safety/_clock/set_current_utc` | Set the server logical clock; sweeps overdue transitions | PlatformAdmin |
| POST | `/safety/companies` | Create a company | PlatformAdmin |
| GET | `/safety/companies/{companyId}` | Get a company | All roles |
| GET | `/safety/companies/{id}/employees` | List employees of a company | All roles |
| GET | `/safety/companies/{id}/establishments` | List establishments of a company | All roles |
| POST | `/safety/establishments` | Create an establishment | PlatformAdmin |
| GET | `/safety/establishments/{establishmentId}` | Get an establishment | All roles |
| GET | `/safety/establishments/{establishmentId}/rates` | Live TRIR/DART rates for a year | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| GET | `/safety/establishments/{id}/cases` | List cases of an establishment | All roles |
| GET | `/safety/establishments/{id}/summaries` | List annual summaries of an establishment | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| GET | `/safety/establishments/{id}/hour-logs` | List hour logs of an establishment | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| GET | `/safety/establishments/{id}/inspections` | List inspections of an establishment | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| GET | `/safety/establishments/{id}/corrective-actions` | List corrective actions of an establishment | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/employees` | Create an employee | PlatformAdmin, RecordkeepingCoordinator |
| GET | `/safety/employees/{employeeId}` | Get an employee | All roles |
| PATCH | `/safety/employees/{employeeId}` | Update an employee; separation closes open day counts | PlatformAdmin, RecordkeepingCoordinator |
| GET | `/safety/employees/{id}/cases` | List cases for an employee | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/cases` | Injury intake — create a case | SafetyOfficer, RecordkeepingCoordinator |
| GET | `/safety/cases/{caseId}` | Get a case (with projected day counts) | All roles |
| POST | `/safety/cases/{caseId}/classify` | Recordability determination or re-determination (OCC-guarded) | SafetyOfficer |
| POST | `/safety/cases/{caseId}/reclassify` | Open the reclassification loop | SafetyOfficer |
| POST | `/safety/cases/{caseId}/close-day-count` | Mark day counting closed (worker returned to full duty) | SafetyOfficer |
| POST | `/safety/cases/{caseId}/finalize` | Finalize and lock a case | SafetyOfficer |
| GET | `/safety/cases/{id}/day-entries` | List day-count entries of a case | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/cases/{id}/day-entries` | Add a restricted/lost-day interval | SafetyOfficer |
| POST | `/safety/cases/{caseId}/day-entries/{entryId}/void` | Void a day-count entry | SafetyOfficer |
| GET | `/safety/cases/{id}/investigation` | Get the case's investigation (array of at most one) | All roles |
| GET | `/safety/cases/{id}/severe-reports` | Get the case's severe-injury report (array of at most one) | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| GET | `/safety/cases/{id}/corrective-actions` | List corrective actions linked to a case | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/cases/{id}/severe-reports` | File a severe-injury agency report for a case | SafetyOfficer |
| POST | `/safety/investigations` | Open an investigation for a case | SafetyOfficer |
| GET | `/safety/investigations/{investigationId}` | Get an investigation | All roles |
| POST | `/safety/investigations/{investigationId}/submit-root-cause` | Submit root cause (recorded lead only) | InvestigatingSupervisor |
| POST | `/safety/investigations/{investigationId}/reopen` | Reopen an investigation (recorded lead only) | InvestigatingSupervisor |
| POST | `/safety/investigations/{investigationId}/close` | Close an investigation | SafetyOfficer |
| POST | `/safety/corrective-actions` | Create a corrective action linked to exactly one of case or citation | SafetyOfficer |
| GET | `/safety/corrective-actions/{actionId}` | Get a corrective action | All roles |
| POST | `/safety/corrective-actions/{actionId}/complete` | Mark a corrective action completed | SafetyOfficer |
| POST | `/safety/corrective-actions/{actionId}/verify` | Verify completion (segregation of duties enforced) | SafetyOfficer |
| POST | `/safety/corrective-actions/{actionId}/reject-verification` | Reject verification and reopen | SafetyOfficer |
| POST | `/safety/corrective-actions/{actionId}/cancel` | Cancel an open corrective action | SafetyOfficer |
| POST | `/safety/summaries` | Create a draft annual summary (300A) for an establishment-year | RecordkeepingCoordinator |
| GET | `/safety/summaries/{summaryId}` | Get an annual summary | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/summaries/{summaryId}/prepare` | Run the rollup and store provisional rates | RecordkeepingCoordinator |
| POST | `/safety/summaries/{summaryId}/certify` | Certify a summary (OCC-guarded; segregation of duties) | SafetyOfficer |
| POST | `/safety/summaries/{summaryId}/post` | Post the 300A during the February–April window | RecordkeepingCoordinator |
| POST | `/safety/summaries/{summaryId}/amend` | Amend a certified summary | RecordkeepingCoordinator |
| POST | `/safety/hour-logs` | Create a monthly hour log | RecordkeepingCoordinator |
| GET | `/safety/hour-logs/{hourLogId}` | Get an hour log | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/hour-logs/{hourLogId}/approve` | Approve an hour log | RecordkeepingCoordinator |
| POST | `/safety/hour-logs/{hourLogId}/reopen` | Reopen an approved log (blocked while summary PREPARED or beyond) | RecordkeepingCoordinator |
| POST | `/safety/inspections` | Open an inspection | SafetyOfficer, PlatformAdmin |
| GET | `/safety/inspections/{inspectionId}` | Get an inspection | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/inspections/{inspectionId}/close` | Close an inspection with no citations | SafetyOfficer |
| GET | `/safety/inspections/{id}/citations` | List citations of an inspection | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/citations` | Issue a citation under an inspection | SafetyOfficer |
| GET | `/safety/citations/{citationId}` | Get a citation | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |
| POST | `/safety/citations/{citationId}/contest` | Contest a citation within the 15-working-day window | SafetyOfficer |
| POST | `/safety/citations/{citationId}/accept-final-order` | Accept a citation as a final order without contest | SafetyOfficer |
| POST | `/safety/citations/{citationId}/resolve-contest` | Resolve a contest (affirmed, modified, or vacated) | SafetyOfficer |
| POST | `/safety/citations/{citationId}/abate` | Certify abatement of a cited hazard | SafetyOfficer |
| GET | `/safety/citations/{id}/corrective-actions` | List corrective actions linked to a citation | PlatformAdmin, SafetyOfficer, RecordkeepingCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_ESTABLISHMENT_EXEMPT` | 422 Unprocessable Entity |
| `ERR_RECORDABILITY_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_POSTING_WINDOW` | 422 Unprocessable Entity |
| `ERR_CONTEST_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_SEVERE_REPORT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CASES_UNRESOLVED` | 422 Unprocessable Entity |
| `ERR_HOURS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SUMMARY_LOCKED` | 422 Unprocessable Entity |
| `ERR_SUMMARY_STALE` | 422 Unprocessable Entity |
| `ERR_INVESTIGATION_OPEN` | 422 Unprocessable Entity |
| `ERR_DAY_COUNT_OPEN` | 422 Unprocessable Entity |
| `ERR_CORRECTIVE_ACTION_OPEN` | 422 Unprocessable Entity |
| `ERR_DUTY_SEGREGATION` | 422 Unprocessable Entity |
| `ERR_NOT_INVESTIGATION_LEAD` | 422 Unprocessable Entity |
| `ERR_NOT_ASSIGNEE` | 422 Unprocessable Entity |
| `ERR_DAY_INTERVAL_INVALID` | 422 Unprocessable Entity |
| `ERR_CROSS_COMPANY_REFERENCE` | 422 Unprocessable Entity |
| `ERR_LINKAGE_XOR` | 422 Unprocessable Entity |
| `ERR_CITATIONS_EXIST` | 422 Unprocessable Entity |
| `ERR_PENALTY_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
