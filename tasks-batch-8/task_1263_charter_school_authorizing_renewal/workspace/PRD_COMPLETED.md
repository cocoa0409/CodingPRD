# Charter School Authorizing API — Product Requirements Document

## 1. Introduction

A state charter authorizer carries a statutory duty that runs the full length of a school's life. It decides which founding groups may open a school, contracts with the approved ones against measurable performance targets, watches academic, financial, and operational health every year, polices the integrity of enrollment lotteries, steps in with intervention notices and corrective action when a school falters, decides whether a charter is renewed and for how long, and — when a school must close — shepherds its students into new placements. Every one of those decisions is appealable, and every one must survive audit.

Today this work is scattered across spreadsheets, inboxes, and board minutes. Reviewers score rubrics with no enforced separation from interview panels; intervention deadlines slip because nobody computes them from a common clock; renewal term lengths are argued from memory rather than derived from the school's monitoring record; and fee invoices are reconciled by hand against funding formulas that invite rounding disputes.

This document specifies a single HTTP API, mounted under `/authorizer`, that operationalizes the entire oversight lifecycle: application intake with rubric scoring and capacity-interview panels, charter contracts and their performance frameworks, annual monitoring with standing bands, lottery oversight with preference verification, intervention and corrective-action workflows, renewal decisions with derived term lengths, closure protocols with student transition tracking, authorizer fee invoicing, and a uniform appeal process with reversal cascades. Segregation of duties is enforced at every sensitive step, all time-gated rules read a controllable logical clock, and every state transition is recorded so any decision can be reconstructed and defended.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A caller whose role is not in the endpoint's authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Seven roles are declared:

- `Applicant` — a founding-group representative who submits charter applications and may appeal an application denial.
- `AuthorizerStaff` — the authorizer's case-management staff: intake, interview scheduling, contracts, monitoring, lotteries, interventions, plan review, renewal administration, closure administration, invoicing, and hearing scheduling.
- `ApplicationReviewer` — a rubric scorer and capacity-interview panelist, segregated per application.
- `BoardMember` — the authorizer board: application and renewal decisions, intervention escalation, closure initiation, and fee waivers.
- `AppealsOfficer` — an independent hearing officer who rules on appeals.
- `SchoolOperator` — a charter school operator acting for its own school: lottery entries, offer declines, corrective plans, invoice payment, and appeals.
- `AuthorizerAdmin` — the platform administrator for the logical clock.

When `X-User-Role` is `SchoolOperator`, `X-User-ID` is the `id` of the acting `School`; ownership checks on any resource that references a `School` compare the resource's foreign-key field to `X-User-ID`. Concretely, when a `SchoolOperator` adds a lottery entry, declines an offer, submits or resubmits a corrective plan, pays an invoice, or files an appeal, the caller's `X-User-ID` must equal the owning school's `id` — that is, the lottery entry's lottery's `school_id`, the corrective plan's intervention's `school_id`, the invoice's `school_id`, or the appeal's `school_id` — and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403).

When `X-User-Role` is `Applicant`, `AuthorizerStaff`, `ApplicationReviewer`, `BoardMember`, `AppealsOfficer`, or `AuthorizerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on a monitoring report, `issued_by_user_id` on an intervention notice, or `decided_by_user_id` on an application decision — but it does not compare it to any entity's `id`.

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

### 2.3. Pagination and List Filtering

All list endpoints paginate. Two query parameters control the window: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0); a non-integer value, an out-of-range `limit`, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Results are always sorted by `created_at` ascending, with ties broken by `id` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints accept optional equality filters alongside pagination. Applications filter by `status` and `cycle_year`; schools filter by `status`; contracts filter by `school_id`, `prior_contract_id`, and `status`; renewal decisions filter by `school_id`, `contract_id`, and `status`; appeals filter by `school_id` and `status`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system carries four server-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` records the creation instant and `updated_at` records the most recent mutation instant, both as ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource, with `updated_at` refreshed at the same moment. Clients never supply any of the four; they only read them.

### 2.5. The Logical Clock and Calendar Semantics

All time-gated behavior — appeal windows, renewal windows, corrective-action deadlines, contract expiry — reads a logical clock, never the wall clock. At startup the logical clock reads exactly 2026-05-01T00:00:00Z, and before any administrative set it continues to read that default; it never falls back to wall-clock time. An `AuthorizerAdmin` may set the clock by supplying `to_iso8601`; the capability responds with the new `current_utc`, and an unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. Every deadline and window named in §3 is evaluated against this logical clock.

Two interval conventions matter throughout. Capacity interviews occupy half-open intervals: an interview runs from its `scheduled_start` up to but not including its `scheduled_end`, so one interview ending at the exact instant another begins does not overlap it. Contract terms are closed intervals: both `term_start` and `term_end` are inclusive days, so a term beginning on the very day a sibling term ends already overlaps that sibling. Windows described in §3 as inclusive include their final day; a rule that demands the clock be strictly past a boundary says so explicitly.

### 2.6. Precision, Rounding, and Monetary Units

Every score or index the system computes — the rubric mean, the composite score, the compliance index, and the renewal-term average — is carried to one decimal place with round-half-up rounding. Monetary quantities are represented as integer cents, and whenever a rate multiplication produces a fractional cent the result is rounded half-up to a whole cent. Standing-band and tier thresholds are inclusive at the stated lower boundary unless a rule explicitly says otherwise.

### 2.7. Optimistic Concurrency Control

Two write endpoints require the caller to declare the version of a parent entity it last observed, and both are guarded by stale-version rejection.

Creating a charter contract for a school — `POST /authorizer/schools/{id}/contracts` — requires the non-optional field `expected_school_version` in the request body, carrying the school's `version` as the client last read it. If another write has advanced the school's `version` since that read, the create is rejected with `ERR_STALE_SCHOOL_VERSION` (HTTP 412). A contract creation legitimately supersedes the school's current contract set — the new draft becomes the activation candidate — so a writer holding a stale school version must refresh before creating.

Creating a corrective action plan against an intervention notice — `POST /authorizer/interventions/{id}/corrective-plans` — requires the non-optional field `expected_intervention_version`, carrying the notice's `version` as the client last read it. A mismatch with the notice's current `version` is rejected with `ERR_STALE_INTERVENTION_VERSION` (HTTP 412). A new plan legitimately supersedes the notice's prior plan state, so a submission carrying a stale intervention version must refresh first.

Both creates are themselves version-advancing writes: a successful contract creation increments the school's `version` by one, and a successful plan creation increments the notice's `version` by one. No endpoint other than these two accepts a version field.

### 2.8. Segregation of Duties

The authorizer's credibility rests on four standing separations, each enforced by the server:

1. **Rubric versus panel.** No one who scored an application's rubric may sit on its capacity-interview panel: at scheduling time, none of the `panelist_user_ids` may appear as a `reviewer_user_id` in the application's `review_scores`. A conflict is rejected with `ERR_SOD_REVIEWER_PANEL_CONFLICT` (HTTP 403).
2. **Panel scoring.** Only a listed panelist may record an interview's `panel_score`; a scorer whose `X-User-ID` is absent from `panelist_user_ids` is rejected with `ERR_NOT_PANELIST` (HTTP 403).
3. **Notice resolution.** The staff member who issued an intervention notice may not resolve it: the resolver's `X-User-ID` must differ from the notice's `issued_by_user_id`, else `ERR_SOD_NOTICE_SELF_RESOLVE` (HTTP 403).
4. **Appeal independence.** The hearing officer assigned to an appeal must not be the original decider of the contested target, else `ERR_SOD_APPEAL_DECIDER_CONFLICT` (HTTP 403); and the ruling itself may only be entered by the assigned officer, else `ERR_APPEAL_OFFICER_MISMATCH` (HTTP 403).

### 2.9. Validation Layers, Ordering, and Uniqueness

Incoming requests are checked against a fixed sequence of validation layers, and the first failing layer determines the error returned. Identity-header presence and validity come first, then role authorization, then existence of every resource named in the path — validated left to right, so the first missing id yields `ERR_NOT_FOUND` (HTTP 404) — then `SchoolOperator` ownership, then optimistic-concurrency version checks, then state preconditions (the various invalid-state conflicts, plus `ERR_TARGET_NOT_APPEALABLE` and `ERR_SCHOOL_NOT_OPEN`), then segregation-of-duties and panel-integrity rules, then temporal-window rules, then constraint and aggregate rules, and finally the fiscal guards. A request that would fail both an authorization check and a state check therefore always surfaces the authorization error; one that fails both a temporal rule and a constraint rule surfaces the temporal error; and so on down the order. Plain field validation (`ERR_INVALID_REQUEST`) has no layer of its own: each endpoint validates a field at the moment it consumes it, so a missing or malformed body field surfaces only after whichever earlier-layer guards that endpoint evaluates before reading it.

The aggregate layer also enforces the system's uniqueness constraints, each rejected with `ERR_DUPLICATE_RECORD` (HTTP 409): at most one score per application, reviewer, and criterion; at most one monitoring report per school per `fiscal_year`; at most one lottery per school per `academic_year`; at most one fee invoice per school per `fiscal_year`; and at most one performance target per combination of `contract_id`, `domain`, and `metric_code`.

## 3. Business Logic & Workflows

### 3.1. From Application to Charter: Intake, Scoring, the Capacity Interview, and the Board's Decision

A founding group enters the pipeline when an `Applicant` submits a charter application carrying the proposed `school_name`, the `founding_group` behind it, the `cycle_year` of the application cycle, and the `proposed_grades` span (for example, "K-8"). The new application lands in `SUBMITTED` status with an empty `review_scores` list, with `rubric_complete` false, with `rubric_score`, `interview_score`, `composite_score`, and `composite_variant` all null, and with `decided_by_user_id` and `denial_reason` both null. Completeness review is a staff function: when `AuthorizerStaff` accepts intake, the application moves `SUBMITTED` → `UNDER_REVIEW`; attempting intake against an application in any other status is rejected with `ERR_APPLICATION_INVALID_STATE`.

While an application is `UNDER_REVIEW`, each `ApplicationReviewer` posts one score per rubric criterion. A score submission names the `criterion` and the `score`; a `criterion` outside the five declared ones is rejected with `ERR_INVALID_REQUEST`, while the `score` itself is accepted as any number with no range check. The server appends an entry pairing them with the caller's `X-User-ID` as `reviewer_user_id` into the application's `review_scores`. The rubric has five criteria — `ACADEMIC_PLAN`, `FINANCE_PLAN`, `GOVERNANCE`, `OPERATIONS_PLAN`, and `COMMUNITY_SUPPORT` — and a reviewer may score each at most once: a second submission for the same reviewer and criterion is rejected with `ERR_DUPLICATE_RECORD`. Scores are accepted only while the application is `UNDER_REVIEW`; against any other status the submission draws `ERR_APPLICATION_INVALID_STATE`. The flag `rubric_complete` becomes true once every one of the five criteria holds at least one score. The `rubric_score` — null until the rubric is complete — is the mean of the five per-criterion mean scores, rounded half-up to one decimal place.

From the moment the rubric completes until a capacity interview is scored, the application carries the `PROVISIONAL` value of `composite_variant`, and its `composite_score` simply equals the `rubric_score` — the interview contributes nothing yet, and `interview_score` remains null.

Scheduling the capacity interview is a staff action providing `scheduled_start`, `scheduled_end`, and the `panelist_user_ids` who will sit the panel — the list must be a non-empty array of strings, else `ERR_INVALID_REQUEST`; the new interview records its `application_id` and begins life `SCHEDULED` with `panel_score` null. The start must be earlier than the end, else `ERR_INVALID_REQUEST`, and the application may have at most one interview that is not `CANCELLED`, else `ERR_INTERVIEW_ALREADY_ACTIVE`. Two integrity guards from §2.8 also fire at scheduling time: no proposed panelist may appear among the application's rubric scorers (`ERR_SOD_REVIEWER_PANEL_CONFLICT`), and no panelist may already hold a `SCHEDULED` interview whose half-open interval overlaps the new one — under half-open semantics adjacency is allowed, so an interview beginning exactly when another ends is permitted — with overlaps rejected as `ERR_PANEL_TIME_OVERLAP`. Like scoring, scheduling requires the application to be `UNDER_REVIEW`, otherwise `ERR_APPLICATION_INVALID_STATE`.

After the panel convenes, one of its members records the outcome. The caller must be an `ApplicationReviewer` whose `X-User-ID` appears in `panelist_user_ids` (else `ERR_NOT_PANELIST`), the interview must still be `SCHEDULED` (else `ERR_INTERVIEW_INVALID_STATE`), and the `panel_score` must fall between 0 and 100 inclusive (else `ERR_INVALID_REQUEST`). Scoring moves the interview `SCHEDULED` → `SCORED` and ripples back to the application: `interview_score` takes the panel's value, and `composite_variant` flips to `FINAL`. If the rubric is already complete at that moment, `composite_score` is recomputed as six-tenths of the `rubric_score` plus four-tenths of the `interview_score`, rounded half-up to one decimal place. Because interview scheduling and scoring are gated only on `UNDER_REVIEW`, an interview may legitimately be scored before the rubric completes; in that case no composite can yet be formed, so `composite_score` remains null while `composite_variant` already reads `FINAL`, and the `FINAL` composite is computed by the same formula at the moment the rubric later completes. Because the weights differ, the same rubric now produces a different composite whenever the panel score differs from the rubric mean.

Only a complete file may go to the board. Advancing the application `UNDER_REVIEW` → `BOARD_REVIEW` requires both a complete rubric and a `SCORED` interview for the application; if either is missing the advance is rejected with `ERR_BOARD_REVIEW_BLOCKED`, and an application in any other status draws `ERR_APPLICATION_INVALID_STATE`. At this transition the composite is frozen in its `FINAL` variant.

A `BoardMember` then decides the application by naming an `outcome`. Approval requires the application to sit in `BOARD_REVIEW` and its `composite_score` to reach at least 75.0 — the threshold is inclusive — so a composite below 75.0 is rejected with `ERR_COMPOSITE_BELOW_THRESHOLD`. An approval cascades: a new `School` springs into existence in `PRE_OPENING` status carrying the origin `application_id` and the approved `school_name`, with `academic_standing`, `financial_standing`, and `operational_standing` all initialized to `GOOD`, and `current_contract_id` null until a first contract activates. Denial takes the other branch: `denial_reason` must be supplied and non-empty (else `ERR_INVALID_REQUEST`), any `SCHEDULED` interview for the application is cancelled (`SCHEDULED` → `CANCELLED`), and the reason is recorded. Either way the application reaches a terminal state — `APPROVED` or `DENIED` — and `decided_by_user_id` captures the deciding board member. A denial is not necessarily the end: §3.9 shows how an overturned appeal returns the application `DENIED` → `BOARD_REVIEW` with `denial_reason` and `decided_by_user_id` cleared to null.

### 3.2. Charter Contracts and the Performance Framework

A school's charter takes legal shape as a `CharterContract`. `AuthorizerStaff` drafts one against a school by supplying the `framework_version` label, the `term_start` and `term_end` dates, an optional `prior_contract_id` — null for an initial charter, set when the new draft succeeds a renewal or amendment, and otherwise required to name an existing contract, else `ERR_NOT_FOUND` — and, per §2.7, the `expected_school_version` carrying the school's last-observed `version`. Terms are closed intervals: `term_start` must be earlier than `term_end`, and the new term may not overlap any sibling `DRAFT` or `ACTIVE` term — because both boundary days are inclusive, a term beginning on the very day a sibling term ends already overlaps and is rejected with `ERR_CONTRACT_TERM_OVERLAP`. A successful create lands the contract in `DRAFT` with `targets_weight_total` at zero and increments the school's `version` by one, so any writer holding an older read of the school must refresh before its own create.

Against a `DRAFT` contract, staff attach the performance framework one target at a time. Each `PerformanceTarget` names its parent through `contract_id`, a `domain` of `ACADEMIC`, `FINANCIAL`, or `OPERATIONAL`, a `metric_code` unique within its contract and domain (a duplicate is rejected with `ERR_DUPLICATE_RECORD`), the `target_value` to reach, the `floor_value` below which performance is unacceptable, and a `weight` greater than zero and at most one. Every addition recomputes the contract's `targets_weight_total`, the running sum of its targets' weights. Targets may be added only while the contract is `DRAFT`; against any other status the attempt is rejected with `ERR_CONTRACT_INVALID_STATE`.

Activation turns a draft into the school's operative charter, moving it `DRAFT` → `ACTIVE` under three guards, each with its own error: every domain — `ACADEMIC`, `FINANCIAL`, and `OPERATIONAL` — must carry at least one target (`ERR_DOMAIN_TARGET_MISSING`); the target weights must sum to exactly 1.0 (`ERR_TARGET_WEIGHT_TOTAL_INVALID`); and the school must be `PRE_OPENING` or `OPEN` (`ERR_SCHOOL_NOT_OPEN`). A contract not in `DRAFT` cannot activate at all (`ERR_CONTRACT_INVALID_STATE`). Activation then cascades: any other `ACTIVE` contract for the same school is superseded (`ACTIVE` → `SUPERSEDED`), the school's `current_contract_id` is pointed at the newly active contract, and a `PRE_OPENING` school opens its doors (`PRE_OPENING` → `OPEN`).

Once `ACTIVE`, a contract leaves that state only through system events. A successor's activation supersedes it. A renewal finalized in the school's favor moves it `ACTIVE` → `RENEWED` (§3.6). A revocation closure — or the school's final closing — moves it `ACTIVE` → `REVOKED`. And when the logical clock passes `term_end` while the contract is still `ACTIVE` with no renewal pending, an informational sweep moves it `ACTIVE` → `EXPIRED`. `SUPERSEDED`, `RENEWED`, `REVOKED`, and `EXPIRED` are all terminal.

### 3.3. Annual Monitoring and the Standing Dimensions

Oversight in steady state runs on an annual reporting rhythm. For each fiscal year, `AuthorizerStaff` files a `MonitoringReport` against an `OPEN` school — a school in any other status is rejected with `ERR_SCHOOL_NOT_OPEN` — supplying the `fiscal_year` and three domain scores, `academic_score`, `financial_score`, and `operational_score`, each between 0 and 100 (a score outside that range is rejected with `ERR_INVALID_REQUEST`). One report per school per fiscal year is allowed; a duplicate is rejected with `ERR_DUPLICATE_RECORD`. The report is born `SUBMITTED`, stamped with the filer as `submitted_by_user_id`, and with `return_notes` null.

Every report carries the computed `compliance_index`. The base weights are one-half for the academic score and one-quarter each for the financial and operational scores; any domain whose score falls below sixty has its weight doubled, and the index is the weighted sum of the three scores divided by the sum of the (possibly doubled) weights, rounded half-up to one decimal place. When all three scores reach at least sixty this reduces to the plain weighted mean; a failing domain pulls the index toward itself by carrying double weight.

Accepting a report — `SUBMITTED` → `ACCEPTED`, with `ERR_REPORT_INVALID_STATE` for any other status — is where monitoring bites. Each domain score is mapped to a standing band: a score of eighty or above lands `GOOD`, sixty-five up to but not including eighty lands `NOTICE`, fifty up to but not including sixty-five lands `PROBATION`, and below fifty lands `CRITICAL`; boundaries are inclusive at the lower edge of each band, so exactly 80.0 is `GOOD`. The school's `academic_standing`, `financial_standing`, and `operational_standing` are then set from the three bands. These standings are parallel dimensions: they evolve independently of each other and of the school's `status`. The cascade continues further — for every domain the acceptance left newly in `PROBATION` or `CRITICAL`, if no open notice (one in `DRAFT` or `ISSUED`) already exists for that school and domain, the system itself creates an `InterventionNotice` at level `PROBATION`, already in `ISSUED` status, with the accepting staff member recorded as `issued_by_user_id` and a `corrective_due_date` thirty days out from the logical clock.

When a report needs correction, staff return it (`SUBMITTED` → `RETURNED`) with non-empty `return_notes`; missing notes are rejected with `ERR_INVALID_REQUEST`, and the notes are recorded on the report. Resubmission cycles the report `RETURNED` → `SUBMITTED` — any other status draws `ERR_REPORT_INVALID_STATE` — clears `return_notes` to null, and recomputes the `compliance_index` from the current scores. `ACCEPTED` is terminal.

### 3.4. Enrollment Lotteries and Preference Verification

Even before its doors open, a school may prepare admissions. Staff create a lottery for a `PRE_OPENING` or `OPEN` school — anything else is rejected with `ERR_SCHOOL_NOT_OPEN` — supplying an `academic_year`, unique per school under `ERR_DUPLICATE_RECORD`, and a `capacity` of zero or more seats. The lottery starts `DRAFT`. Opening it moves `DRAFT` → `OPEN` and additionally requires the school to be `OPEN` — a lottery drafted during pre-opening waits for the first contract activation — with `ERR_LOTTERY_INVALID_STATE` for a lottery not in `DRAFT` (checked first) and `ERR_SCHOOL_NOT_OPEN` for a school not open.

While the lottery is `OPEN`, the owning `SchoolOperator` enters applicants one at a time, supplying an opaque `student_ref`, the `grade_level` applied for, and any `preference_codes` drawn from `SIBLING`, `DISTRICT_RESIDENT`, and `STAFF_CHILD` — an omitted `preference_codes` is treated as an empty list, and a code outside the declared set is rejected with `ERR_INVALID_REQUEST`. Entry creation enforces ownership per §2.1 (`ERR_RESOURCE_OWNERSHIP_MISMATCH`) and lottery state (`ERR_LOTTERY_INVALID_STATE` when the lottery is not `OPEN`). Each new entry records its `lottery_id`, lands with `outcome` `ENTERED` and `rank_position` null, and has its `preference_status` set immediately: `VERIFIED` at once when `preference_codes` is empty — there is nothing to verify — and `PENDING` otherwise, with `preference_verified_by` null in both cases.

Preference claims ride a track parallel to entry outcomes. Staff adjudicate a `PENDING` claim by passing an `outcome` of `VERIFIED` or `REJECTED`; adjudicating an entry whose preference claim is not `PENDING` is rejected with `ERR_ENTRY_INVALID_STATE`, and the adjudicator is stamped as `preference_verified_by`. This track never changes the entry's `outcome`.

Sealing the lottery (`OPEN` → `SEALED`) freezes the pool and demands that every preference claim be resolved: a single `PENDING` entry blocks the seal with `ERR_UNVERIFIED_PREFERENCE_ENTRIES` — zero is the only acceptable count — and a lottery not `OPEN` draws `ERR_LOTTERY_INVALID_STATE`. Executing a `SEALED` lottery (`SEALED` → `EXECUTED`, same invalid-state guard) runs the assignment. Each entry earns a preference weight of ten when its `preference_status` is `VERIFIED` and it holds at least one preference code, and zero otherwise. Entries are ordered by preference weight descending, then by `created_at` ascending, then by `student_ref` ascending — ties are never broken by `id` — and `rank_position` is assigned 1 through N in that order. Entries whose rank is at most `capacity` become `OFFERED`; ranks beyond capacity become `WAITLISTED`; and a lottery with zero capacity waitlists every entry.

Two conservation laws hold from execution onward: the counts of `OFFERED`, `WAITLISTED`, and `DECLINED` entries always sum to the total entry count, and the `OFFERED` count always equals the smaller of `capacity` and the number of non-`DECLINED` entries. When the owning `SchoolOperator` declines an offered seat — the entry must be `OFFERED`, else `ERR_ENTRY_INVALID_STATE`, and ownership is checked per §2.1 — the entry becomes `DECLINED` and, if any `WAITLISTED` entries remain, the one with the smallest `rank_position` is promoted to `OFFERED`, leaving the offered count unchanged. With an empty waitlist no promotion occurs: the offered count drops by one and the seat remains unfilled.

After execution the lottery is audited. Certifying with an `audit_outcome` of `CERTIFIED` moves the lottery `EXECUTED` → `CERTIFIED`; an `audit_outcome` of `AUDIT_FAILED` moves it `EXECUTED` → `AUDIT_FAILED`; a lottery in any other status is rejected with `ERR_LOTTERY_INVALID_STATE`. Both outcomes are terminal. The darker cascade arrives from outside: when a school moves `OPEN` → `CLOSING`, every lottery still in `DRAFT`, `OPEN`, or `SEALED` is cancelled to `CANCELLED`, and every entry in those lotteries — whether `ENTERED`, `WAITLISTED`, or `OFFERED` — is moved to `VOIDED`. Lotteries already `EXECUTED` or beyond are untouched.

### 3.5. Intervention Notices and Corrective Action

Staff raise an intervention against an `OPEN` school — any other school status is rejected with `ERR_SCHOOL_NOT_OPEN` — by naming a `level` of `NOTICE`, `PROBATION`, or `REVOCATION_REVIEW`, a `domain` of `ACADEMIC`, `FINANCIAL`, `OPERATIONAL`, or `COMPLIANCE`, and the `reason` for intervening. A manually created notice starts in `DRAFT` with `issued_by_user_id` null and `successor_notice_id` null — unlike the auto-created notices of §3.3, which arrive at `PROBATION` level already `ISSUED`.

Issuing a notice (`DRAFT` → `ISSUED`, with `ERR_NOTICE_INVALID_STATE` for any other status) stamps the caller as `issued_by_user_id` and sets the `corrective_due_date` thirty days out from the logical clock. Corrective plans submitted after that date are overdue.

The school's formal response is a `CorrectiveActionPlan`. The owning `SchoolOperator` submits `plan_text` together with `expected_intervention_version`, the optimistic-concurrency field of §2.7; a stale read is rejected with `ERR_STALE_INTERVENTION_VERSION`. Submission also requires the notice to be `ISSUED` (`ERR_NOTICE_INVALID_STATE`), the clock to read at or before the notice's `corrective_due_date` (`ERR_CORRECTIVE_PLAN_OVERDUE`), and no other plan in `SUBMITTED` or `ACCEPTED` to exist for the notice (`ERR_PLAN_ALREADY_ACTIVE`); ownership is verified per §2.1 (`ERR_RESOURCE_OWNERSHIP_MISMATCH`). A successful submission creates the plan in `SUBMITTED`, stamps its `intervention_id`, records `submitted_at` from the clock, leaves `reviewed_by_user_id` and `review_notes` null, and increments the notice's `version` by one.

Staff then review a `SUBMITTED` plan — any other plan status draws `ERR_PLAN_INVALID_STATE` — by naming an `outcome`. `ACCEPTED` closes the loop; `RETURNED` requires non-empty `review_notes` (missing notes are `ERR_INVALID_REQUEST`) and sends the plan back for rework. Either way the reviewer is recorded in `reviewed_by_user_id` and the notes in `review_notes`. A returned plan can be resubmitted by the owning `SchoolOperator`, cycling `RETURNED` → `SUBMITTED`: the plan must be `RETURNED` (`ERR_PLAN_INVALID_STATE`), ownership is verified, and the due date still binds (`ERR_CORRECTIVE_PLAN_OVERDUE`). Resubmission replaces `plan_text`, refreshes `submitted_at` from the clock, and clears `reviewed_by_user_id` and `review_notes` for the next review. `ACCEPTED` is terminal.

Resolving a notice (`ISSUED` → `RESOLVED`) carries two guards beyond the state check (`ERR_NOTICE_INVALID_STATE`). The resolver must differ from the notice's `issued_by_user_id` — the segregation rule of §2.8, rejected as `ERR_SOD_NOTICE_SELF_RESOLVE` — and a notice at `PROBATION` or `REVOCATION_REVIEW` may not resolve until an `ACCEPTED` corrective plan exists for it (`ERR_NO_ACCEPTED_CORRECTIVE_PLAN`); a plain `NOTICE` resolves without one. Resolution records the caller as `resolved_by_user_id` and lifts the school's standing in the notice's domain exactly one step — `CRITICAL` to `PROBATION`, `PROBATION` to `NOTICE`, `NOTICE` to `GOOD`, and `GOOD` unchanged — never more than one step per resolution; a notice in the `COMPLIANCE` domain lifts nothing, the school carrying no compliance standing.

Escalation is a board power. A `BoardMember` escalates an `ISSUED` notice; a notice in any other status, and a notice already at `REVOCATION_REVIEW` with nowhere higher to go, are both rejected with `ERR_NOTICE_INVALID_STATE`. Escalation moves the notice `ISSUED` → `ESCALATED` and spawns its successor one level up — a `NOTICE` begets a `PROBATION`, a `PROBATION` begets a `REVOCATION_REVIEW` — created directly in `ISSUED` status with the same domain and `reason`, the escalating board member as `issued_by_user_id`, and a fresh thirty-day `corrective_due_date`. The original notice's `successor_notice_id` points at the new notice, chaining the escalation history. Should the school reach `CLOSED`, any notice still open — `DRAFT` or `ISSUED` — is rendered `MOOT`; `RESOLVED`, `ESCALATED`, and `MOOT` are terminal.

### 3.6. Renewal Decisions and Term Length

As a contract approaches its end, staff open a renewal decision against the school, naming the `contract_id` of the school's `ACTIVE` contract — a contract that is not `ACTIVE` is rejected with `ERR_CONTRACT_INVALID_STATE`, and an existing contract that belongs to a different school is rejected with `ERR_NOT_FOUND`. Three gates guard the opening. The school must be `OPEN` (`ERR_SCHOOL_NOT_OPEN`). The logical clock must fall inside the renewal window, which runs from 365 days before the contract's `term_end` through 30 days before `term_end`, both bounds inclusive; outside that window the create is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. And at most one renewal decision may be open — in `PENDING` or `DECIDED` — per school (`ERR_RENEWAL_ALREADY_OPEN`). A successful create produces a `RenewalDecision` in `PENDING` status with `decision`, `granted_term_years`, `decided_by_user_id`, and `decided_at` all null.

Creation is also the moment the system snapshots the school's entitlement into `eligible_term_years`, and the number is derived, never typed in. First, the school's average index is computed as the mean of the `compliance_index` values across the school's `ACCEPTED` monitoring reports whose `fiscal_year` falls within the calendar years spanned by the contract's `term_start` and `term_end`, inclusive — a school with no such reports averages zero — rounded half-up to one decimal place before any comparison. Second, the probation count tallies the school's intervention notices at level `PROBATION` or `REVOCATION_REVIEW` whose `created_at` falls between `term_start` and `term_end` inclusive. Third, the school's three current standings are read. The tiers are then evaluated from the top down and the first match wins: an average of at least 90.0 with zero probation-level notices and all three standings `GOOD` earns 10 years; failing that, an average of at least 75.0 with no standing at `CRITICAL` earns 5 years; failing that, an average of at least 60.0 earns 3 years; anything below earns 0, which bars renewal outright. Every tier boundary is inclusive.

The board then decides. A `BoardMember` decides a decision in `PENDING` — or in `REVERTED`, after an appeal overturn — with an `outcome` of `RENEWED`, `RENEWED_WITH_CONDITIONS`, or `DENIED`; a decision in any other status is rejected with `ERR_DECISION_INVALID_STATE`. The outcome is constrained by the snapshot: `RENEWED` requires `eligible_term_years` above zero (`ERR_RENEWAL_NOT_ELIGIBLE`), and `RENEWED_WITH_CONDITIONS` requires `eligible_term_years` of at least 3 (`ERR_TERM_LENGTH_MISMATCH`). Deciding records the outcome in `decision`, the caller in `decided_by_user_id`, and the clock in `decided_at`, and sets `granted_term_years` — equal to `eligible_term_years` for `RENEWED`, fixed at 3 for `RENEWED_WITH_CONDITIONS`, and null for `DENIED`. A re-decide after reversion refreshes all four fields.

A decided renewal ripens only after the appeal window lapses. Finalizing requires the decision to be `DECIDED` (`ERR_DECISION_INVALID_STATE`), the logical clock to read strictly later than thirty days after `decided_at`, and no appeal in `FILED` or `HEARING_SCHEDULED` targeting the decision; a window still open — or an appeal still pending — is rejected with `ERR_APPEAL_WINDOW_OPEN`. Finalization moves the decision `DECIDED` → `FINAL` and then forks. For `RENEWED` or `RENEWED_WITH_CONDITIONS`, the system drafts the successor contract: a new `DRAFT` `CharterContract` whose `prior_contract_id` points at the decided contract, whose `term_start` is the day after the prior term's `term_end`, whose `term_end` is `granted_term_years` years after that start (same calendar month and day; a February 29 start yields February 28 when the target year is not a leap year), and whose `framework_version` is copied from its predecessor; the decided contract itself moves `ACTIVE` → `RENEWED`. For `DENIED`, the closure cascade fires: the school moves `OPEN` → `CLOSING`, a `ClosurePlan` with reason `NON_RENEWAL` is created in `INITIATED` status with `decided_by_user_id` recorded as "system" and `closure_date` null, and the school's lottery cancellation cascade of §3.4 runs. `FINAL` is terminal.

An overturned renewal-denial appeal instead moves the decision `DECIDED` → `REVERTED` (§3.9): `decision`, `decided_by_user_id`, `decided_at`, and `granted_term_years` are retained for audit, and the `REVERTED` status re-arms the decide transition under exactly the same rules as `PENDING`.

### 3.7. Closure Protocol and Student Transition

A closure begins two ways. The renewal-denial cascade of §3.6 creates one automatically; otherwise a `BoardMember` initiates one by supplying a `reason` of `REVOCATION` or `VOLUNTARY` together with the effective `closure_date` — `NON_RENEWAL` is reserved for the system and may not be requested manually, and any other `reason` value, or a missing or empty `closure_date`, is rejected with `ERR_INVALID_REQUEST`. A `REVOCATION` closure additionally requires an open `REVOCATION_REVIEW` intervention notice for the school, else `ERR_NO_REVOCATION_REVIEW_NOTICE`, and at most one open closure plan — in `INITIATED`, `TRANSITION_IN_PROGRESS`, or `RECORDS_COMPLETE` — may exist per school (`ERR_CLOSURE_ALREADY_EXISTS`). Creation lands the plan in `INITIATED`, moves the school `OPEN` → `CLOSING` (firing the lottery cancellation cascade of §3.4), records the creating board member as `decided_by_user_id` — or "system" for cascade-created plans — and, for `REVOCATION`, moves the school's `ACTIVE` contract to `REVOKED`.

Student transitions are tracked one learner at a time. While the plan is `INITIATED` or `TRANSITION_IN_PROGRESS` — any other plan status is rejected with `ERR_CLOSURE_INVALID_STATE` — staff add each affected student by `student_ref`; the transition records its `closure_plan_id` and starts `PENDING`. Placement names a non-empty `destination_school` (missing values draw `ERR_INVALID_REQUEST`) and moves the transition `PENDING` → `PLACED`, recording the destination; a transition not `PENDING` draws `ERR_TRANSITION_INVALID_STATE`. When records have been transferred, staff mark the transition `PLACED` → `RECORDS_SENT` — again `ERR_TRANSITION_INVALID_STATE` for any other status — which is terminal.

The plan itself advances stepwise, each step a staff action guarded by `ERR_CLOSURE_INVALID_STATE`. From `INITIATED` it moves to `TRANSITION_IN_PROGRESS`. From `TRANSITION_IN_PROGRESS` it reaches `RECORDS_COMPLETE` only when zero student transitions remain in `PENDING` or `PLACED` (`ERR_STUDENTS_NOT_TRANSITIONED`). From `RECORDS_COMPLETE` it reaches `CLOSED`, and that final step closes the school itself: the school moves `CLOSING` → `CLOSED`, any contract still `ACTIVE` is moved to `REVOKED`, and every intervention notice still open — `DRAFT` or `ISSUED` — becomes `MOOT`. `CLOSED` is terminal for both plan and school.

One reversal remains: when a `REVOCATION` appeal is overturned (§3.9), a closure plan still in `INITIATED` or `TRANSITION_IN_PROGRESS` is cancelled to `CANCELLED`, the revoked contract returns `REVOKED` → `ACTIVE`, and the school returns `CLOSING` → `OPEN`.

### 3.8. Authorizer Fees and Invoice Settlement

The authorizer funds its oversight through an annual per-school fee. Staff issue a `FeeInvoice` for a school that is `OPEN` or `CLOSING`, supplying the `fiscal_year` — unique per school, with duplicates rejected as `ERR_DUPLICATE_RECORD` — the `estimated_enrollment` (the prior-year audited average daily membership), the state's `base_per_pupil_cents` funding rate in integer cents, and the count of `qualifying_supplemental_pupils`; a negative value in any of these three is rejected with `ERR_INVALID_REQUEST`. The invoice is born in `ESTIMATED` status with `billed_variant` `ESTIMATED`, `audited_enrollment` still null, and `paid_cents` and `waived_cents` both zero.

The funding base is computed in a pinned order, because the supplemental band is keyed on the base alone and never on the total. First, the active enrollment figure — the `estimated_enrollment` for the `ESTIMATED` variant, the `audited_enrollment` for the `FINAL` variant — is multiplied by `base_per_pupil_cents` to yield `base_funding_cents`. Second, that base alone selects the supplemental band: a base under 200,000,000 cents — two million dollars — is the small band with a supplemental rate of 0.12; a base from 200,000,000 cents up to and including 600,000,000 cents — two to six million dollars — is the mid band at 0.08; and a base above 600,000,000 cents is the large band at 0.05. Third, `supplemental_cents` is `qualifying_supplemental_pupils` multiplied by `base_per_pupil_cents` multiplied by the band's rate, rounded half-up to a whole cent. Finally, `total_funding_cents` is the sum of `base_funding_cents` and `supplemental_cents`.

The fee itself is tiered on enrollment: an invoice whose active enrollment is at most 300 pupils bills at a `fee_rate` of 0.025, from 301 through 800 pupils at 0.020, and at 801 or more pupils at 0.015. Rounding order is pinned per month rather than per year: the monthly charge is `total_funding_cents` multiplied by the `fee_rate` and divided by twelve, rounded half-up to a whole cent, and `billed_amount_cents` is twelve times that rounded monthly figure. Rounding the annual product once instead would yield a different cent value whenever the monthly division is fractional; the per-month order is the specified behavior.

When the current-year audited membership arrives, staff finalize the invoice by recording `audited_enrollment` (a negative value is rejected with `ERR_INVALID_REQUEST`): the invoice must be `ESTIMATED` (`ERR_INVOICE_INVALID_STATE`), finalization moves it `ESTIMATED` → `FINALIZED`, flips `billed_variant` to `FINAL`, and recomputes every computed field under the `FINAL` variant — so identical inputs produce a different billed amount whenever the audited and estimated enrollments differ. From that point the invoice obeys a ledger invariant: `paid_cents` plus `waived_cents` plus the outstanding remainder always equals `billed_amount_cents`, and the outstanding remainder never goes negative.

Settlement has three doors. The owning `SchoolOperator` pays a `FINALIZED` invoice — any other status, `ERR_INVOICE_INVALID_STATE`; another school's operator, `ERR_RESOURCE_OWNERSHIP_MISMATCH` — and payment settles in full only: `paid_cents` becomes exactly `billed_amount_cents` and the invoice moves to `PAID`. A `BoardMember` may instead waive a `FINALIZED` invoice, but only while nothing has been paid — a non-zero `paid_cents` is rejected with `ERR_INVOICE_INVALID_STATE` — moving it to `WAIVED` with `waived_cents` set to the full `billed_amount_cents`. The third door is the appeal path of §3.9: filing a fee appeal moves the invoice `FINALIZED` → `DISPUTED`; an upheld ruling returns it `DISPUTED` → `FINALIZED`; an overturned ruling moves it `DISPUTED` → `WAIVED` with `waived_cents` set to `billed_amount_cents` minus whatever `paid_cents` had already been recorded. `PAID` and `WAIVED` are terminal, and through every forward and compensating step the billed amount itself never changes.

### 3.9. Appeals and Reversal Cascades

Every adverse decision in the system can be appealed through one uniform process. A `SchoolOperator` files for its own school — ownership is checked per §2.1 — while an `Applicant` files an `APPLICATION_DENIAL` appeal with `school_id` null, that being the only appeal type without a school. The roles do not mix: an `Applicant` filing any other type, or a `SchoolOperator` filing `APPLICATION_DENIAL`, is rejected with `ERR_INSUFFICIENT_PERMISSIONS`, and the `school_id` of a school-scoped appeal is required and must name an existing school (`ERR_NOT_FOUND`). The filing names the `target_type` — `APPLICATION_DENIAL`, `RENEWAL_DENIAL`, `REVOCATION`, or `FEE_INVOICE` — the `target_id`, a polymorphic reference resolved by the type: a charter application for `APPLICATION_DENIAL`, a renewal decision for `RENEWAL_DENIAL`, a charter contract for `REVOCATION`, and a fee invoice for `FEE_INVOICE`; and the `grounds` for the appeal. The server stamps `filed_by_user_id` with the caller and `filed_at` with the clock.

Three guards stand at filing. The target must exist, match the declared type, and sit in an appealable state — the application must be `DENIED`, the renewal decision `DECIDED`, the contract `REVOKED`, and the invoice `FINALIZED` or `DISPUTED` — otherwise `ERR_TARGET_NOT_APPEALABLE`. At most one open appeal, in `FILED` or `HEARING_SCHEDULED`, may exist per target (`ERR_APPEAL_ALREADY_OPEN`). And the window is finite: `filed_at` must fall at or before thirty days after the target's decision instant — for a renewal decision its `decided_at`, and for the other target types the target's `updated_at` as stamped by the adverse decision itself; the window is inclusive of the final day — else `ERR_APPEAL_WINDOW_EXPIRED`. A fresh appeal lands in `FILED` with `hearing_officer_user_id` and `ruling` null; when the target is a fee invoice, the filing itself moves the invoice `FINALIZED` → `DISPUTED`.

Staff then schedule the hearing, assigning a `hearing_officer_user_id`; an appeal not `FILED` is rejected with `ERR_APPEAL_INVALID_STATE`. The officer must differ from the original decider of the contested target — the application's `decided_by_user_id` for `APPLICATION_DENIAL`, the decision's `decided_by_user_id` for `RENEWAL_DENIAL`, and the closure plan's `decided_by_user_id` for `REVOCATION`; a `FEE_INVOICE` target has no decider, so any officer may be assigned. A conflict draws `ERR_SOD_APPEAL_DECIDER_CONFLICT`. Scheduling moves the appeal `FILED` → `HEARING_SCHEDULED` and records the officer.

Ruling belongs to the assigned `AppealsOfficer` alone: the caller's `X-User-ID` must equal `hearing_officer_user_id` (`ERR_APPEAL_OFFICER_MISMATCH`), and the appeal must be `HEARING_SCHEDULED` (`ERR_APPEAL_INVALID_STATE`). A `ruling` of `UPHELD` moves the appeal to `RULED_UPHELD` and touches only a fee-invoice target, returning it `DISPUTED` → `FINALIZED`; every other target type is left unchanged. A `ruling` of `OVERTURNED` moves the appeal to `RULED_OVERTURNED` and reverses the target, with the cascade depending on the type. For `APPLICATION_DENIAL`, the application returns `DENIED` → `BOARD_REVIEW` with `denial_reason` and `decided_by_user_id` cleared, reopening the board's decision cycle. For `RENEWAL_DENIAL`, the renewal decision moves `DECIDED` → `REVERTED`, its decided fields retained for audit and re-decision enabled per §3.6. For `REVOCATION`, a closure plan still in `INITIATED` or `TRANSITION_IN_PROGRESS` is cancelled to `CANCELLED`, the contract returns `REVOKED` → `ACTIVE`, and the school returns `CLOSING` → `OPEN`. For `FEE_INVOICE`, the invoice moves `DISPUTED` → `WAIVED` with `waived_cents` set to the billed amount minus any amount already paid. `RULED_UPHELD` and `RULED_OVERTURNED` are terminal.

## 4. Endpoint Definitions

Endpoints that create a new resource answer HTTP 201; endpoints that read, modify, or transition an existing resource answer HTTP 200. All responses use the envelopes of §2.2, and all authorization follows §2.1. Request and response field details are specified by the workflows of §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /authorizer/_clock/set_current_utc | Set the logical clock to a supplied instant | AuthorizerAdmin |
| POST | /authorizer/applications | Submit a charter application | Applicant |
| GET | /authorizer/applications | List applications with pagination and optional filters | All roles |
| GET | /authorizer/applications/{id} | Get one application | All roles |
| POST | /authorizer/applications/{id}/accept-intake | Completeness pass: SUBMITTED to UNDER_REVIEW | AuthorizerStaff |
| POST | /authorizer/applications/{id}/scores | Post one rubric criterion score (reviewer id from X-User-ID) | ApplicationReviewer |
| POST | /authorizer/applications/{id}/interviews | Schedule the capacity interview (half-open interval; SOD and overlap checks) | AuthorizerStaff |
| GET | /authorizer/applications/{id}/interviews | List interviews for an application | All roles |
| GET | /authorizer/applications/{id}/schools | List schools originating from this application (0 or 1) | All roles |
| POST | /authorizer/applications/{id}/advance-to-board | UNDER_REVIEW to BOARD_REVIEW when rubric complete and interview scored | AuthorizerStaff |
| POST | /authorizer/applications/{id}/decide | Board decision: APPROVED or DENIED (reason required for denial) | BoardMember |
| POST | /authorizer/interviews/{id}/score | Panelist records the panel score; flips the composite to FINAL | ApplicationReviewer |
| GET | /authorizer/schools | List schools with pagination and optional status filter | All roles |
| GET | /authorizer/schools/{id} | Get one school | All roles |
| POST | /authorizer/schools/{id}/contracts | Create a DRAFT charter contract (OCC via expected_school_version) | AuthorizerStaff |
| GET | /authorizer/contracts | List contracts with optional school, prior-contract, and status filters | All roles |
| GET | /authorizer/contracts/{id} | Get one contract | All roles |
| POST | /authorizer/contracts/{id}/targets | Add a performance target to a DRAFT contract | AuthorizerStaff |
| GET | /authorizer/contracts/{id}/targets | List targets of a contract | All roles |
| POST | /authorizer/contracts/{id}/activate | Activate a DRAFT contract; supersedes the prior ACTIVE contract; opens the school | AuthorizerStaff |
| POST | /authorizer/schools/{id}/monitoring-reports | Create the annual monitoring report (SUBMITTED); unique per school and fiscal year | AuthorizerStaff |
| GET | /authorizer/schools/{id}/monitoring-reports | List monitoring reports for a school | All roles |
| POST | /authorizer/monitoring-reports/{id}/submit | Resubmit a RETURNED report | AuthorizerStaff |
| POST | /authorizer/monitoring-reports/{id}/accept | Accept a SUBMITTED report; applies standing bands; may auto-issue PROBATION notices | AuthorizerStaff |
| POST | /authorizer/monitoring-reports/{id}/return | Return a SUBMITTED report for correction | AuthorizerStaff |
| POST | /authorizer/schools/{id}/lotteries | Create a lottery (DRAFT); unique per school and academic year | AuthorizerStaff |
| GET | /authorizer/schools/{id}/lotteries | List lotteries for a school | All roles |
| GET | /authorizer/lotteries/{id} | Get one lottery | All roles |
| POST | /authorizer/lotteries/{id}/open | DRAFT to OPEN (school must be OPEN) | AuthorizerStaff |
| POST | /authorizer/lotteries/{id}/entries | Add an entry to an OPEN lottery of the operator's own school | SchoolOperator |
| GET | /authorizer/lotteries/{id}/entries | List entries of a lottery | All roles |
| POST | /authorizer/lottery-entries/{id}/verify-preference | Verify or reject a PENDING preference claim | AuthorizerStaff |
| POST | /authorizer/lotteries/{id}/seal | OPEN to SEALED; requires zero PENDING preference entries | AuthorizerStaff |
| POST | /authorizer/lotteries/{id}/execute | SEALED to EXECUTED; runs the rank assignment | AuthorizerStaff |
| POST | /authorizer/lottery-entries/{id}/decline | Decline an OFFERED seat; promotes the smallest-rank WAITLISTED entry if any | SchoolOperator |
| POST | /authorizer/lotteries/{id}/certify | EXECUTED to CERTIFIED or AUDIT_FAILED per the audit outcome | AuthorizerStaff |
| POST | /authorizer/schools/{id}/interventions | Create an intervention notice (DRAFT) for an OPEN school | AuthorizerStaff |
| GET | /authorizer/schools/{id}/interventions | List intervention notices for a school | All roles |
| GET | /authorizer/interventions/{id} | Get one intervention notice | All roles |
| POST | /authorizer/interventions/{id}/issue | DRAFT to ISSUED; sets issuer and corrective due date (clock plus 30 days) | AuthorizerStaff |
| POST | /authorizer/interventions/{id}/escalate | ISSUED to ESCALATED; spawns a successor notice one level up, already ISSUED | BoardMember |
| POST | /authorizer/interventions/{id}/resolve | ISSUED to RESOLVED; resolver must differ from issuer; PROBATION and above need an ACCEPTED plan | AuthorizerStaff |
| POST | /authorizer/interventions/{id}/corrective-plans | Submit a corrective plan (OCC via expected_intervention_version; overdue rejected) | SchoolOperator |
| GET | /authorizer/interventions/{id}/corrective-plans | List corrective plans for a notice | All roles |
| POST | /authorizer/corrective-plans/{id}/review | Review a SUBMITTED plan: ACCEPTED or RETURNED | AuthorizerStaff |
| POST | /authorizer/corrective-plans/{id}/resubmit | Resubmit a RETURNED plan (RETURNED to SUBMITTED) | SchoolOperator |
| POST | /authorizer/schools/{id}/renewal-decisions | Open a renewal decision for the school's ACTIVE contract; snapshots eligible term years | AuthorizerStaff |
| GET | /authorizer/renewal-decisions | List renewal decisions with optional school, contract, and status filters | All roles |
| GET | /authorizer/renewal-decisions/{id} | Get one renewal decision | All roles |
| POST | /authorizer/renewal-decisions/{id}/decide | Board decides: RENEWED, RENEWED_WITH_CONDITIONS, or DENIED | BoardMember |
| POST | /authorizer/renewal-decisions/{id}/finalize | DECIDED to FINAL after the appeal window lapses; spawns the successor contract or the closure cascade | AuthorizerStaff |
| POST | /authorizer/schools/{id}/closure-plans | Initiate closure (REVOCATION needs an open REVOCATION_REVIEW notice; VOLUNTARY free; NON_RENEWAL system-only) | BoardMember |
| GET | /authorizer/schools/{id}/closure-plans | List closure plans for a school | All roles |
| GET | /authorizer/closure-plans/{id} | Get one closure plan | All roles |
| POST | /authorizer/closure-plans/{id}/student-transitions | Add a student to transition (plan INITIATED or TRANSITION_IN_PROGRESS) | AuthorizerStaff |
| GET | /authorizer/closure-plans/{id}/student-transitions | List student transitions of a closure plan | All roles |
| POST | /authorizer/student-transitions/{id}/place | PENDING to PLACED with a destination school | AuthorizerStaff |
| POST | /authorizer/student-transitions/{id}/records-sent | PLACED to RECORDS_SENT | AuthorizerStaff |
| POST | /authorizer/closure-plans/{id}/advance | Stepwise advance INITIATED to TRANSITION_IN_PROGRESS to RECORDS_COMPLETE to CLOSED | AuthorizerStaff |
| POST | /authorizer/schools/{id}/fee-invoices | Issue the annual authorizer fee invoice (ESTIMATED variant); unique per school and fiscal year | AuthorizerStaff |
| GET | /authorizer/schools/{id}/fee-invoices | List fee invoices for a school | All roles |
| POST | /authorizer/fee-invoices/{id}/finalize | ESTIMATED to FINALIZED with audited enrollment; recompute the FINAL variant | AuthorizerStaff |
| POST | /authorizer/fee-invoices/{id}/pay | Pay the operator's own FINALIZED invoice in full | SchoolOperator |
| POST | /authorizer/fee-invoices/{id}/waive | Waive a FINALIZED invoice (nothing paid yet) | BoardMember |
| POST | /authorizer/appeals | File an appeal (30-day inclusive window from the target decision) | SchoolOperator, Applicant |
| GET | /authorizer/appeals | List appeals with optional school and status filters | All roles |
| GET | /authorizer/appeals/{id} | Get one appeal | All roles |
| POST | /authorizer/appeals/{id}/schedule-hearing | FILED to HEARING_SCHEDULED; officer must differ from the original decider | AuthorizerStaff |
| POST | /authorizer/appeals/{id}/rule | Assigned officer rules UPHELD or OVERTURNED; an overturn cascades to the target | AppealsOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified where each rule lives in §2 and §3 rather than repeated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_RESOURCE_OWNERSHIP_MISMATCH | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_SCHOOL_VERSION | 412 |
| ERR_STALE_INTERVENTION_VERSION | 412 |
| ERR_APPLICATION_INVALID_STATE | 409 |
| ERR_INTERVIEW_INVALID_STATE | 409 |
| ERR_CONTRACT_INVALID_STATE | 409 |
| ERR_REPORT_INVALID_STATE | 409 |
| ERR_LOTTERY_INVALID_STATE | 409 |
| ERR_ENTRY_INVALID_STATE | 409 |
| ERR_NOTICE_INVALID_STATE | 409 |
| ERR_PLAN_INVALID_STATE | 409 |
| ERR_DECISION_INVALID_STATE | 409 |
| ERR_CLOSURE_INVALID_STATE | 409 |
| ERR_TRANSITION_INVALID_STATE | 409 |
| ERR_INVOICE_INVALID_STATE | 409 |
| ERR_APPEAL_INVALID_STATE | 409 |
| ERR_SCHOOL_NOT_OPEN | 409 |
| ERR_DUPLICATE_RECORD | 409 |
| ERR_BOARD_REVIEW_BLOCKED | 409 |
| ERR_INTERVIEW_ALREADY_ACTIVE | 409 |
| ERR_SOD_REVIEWER_PANEL_CONFLICT | 403 |
| ERR_PANEL_TIME_OVERLAP | 409 |
| ERR_NOT_PANELIST | 403 |
| ERR_COMPOSITE_BELOW_THRESHOLD | 422 |
| ERR_CONTRACT_TERM_OVERLAP | 409 |
| ERR_DOMAIN_TARGET_MISSING | 422 |
| ERR_TARGET_WEIGHT_TOTAL_INVALID | 422 |
| ERR_UNVERIFIED_PREFERENCE_ENTRIES | 409 |
| ERR_SOD_NOTICE_SELF_RESOLVE | 403 |
| ERR_NO_ACCEPTED_CORRECTIVE_PLAN | 409 |
| ERR_PLAN_ALREADY_ACTIVE | 409 |
| ERR_CORRECTIVE_PLAN_OVERDUE | 422 |
| ERR_RENEWAL_WINDOW_NOT_OPEN | 422 |
| ERR_RENEWAL_ALREADY_OPEN | 409 |
| ERR_RENEWAL_NOT_ELIGIBLE | 422 |
| ERR_TERM_LENGTH_MISMATCH | 422 |
| ERR_APPEAL_WINDOW_OPEN | 409 |
| ERR_NO_REVOCATION_REVIEW_NOTICE | 409 |
| ERR_CLOSURE_ALREADY_EXISTS | 409 |
| ERR_STUDENTS_NOT_TRANSITIONED | 409 |
| ERR_TARGET_NOT_APPEALABLE | 409 |
| ERR_APPEAL_WINDOW_EXPIRED | 422 |
| ERR_APPEAL_ALREADY_OPEN | 409 |
| ERR_SOD_APPEAL_DECIDER_CONFLICT | 403 |
| ERR_APPEAL_OFFICER_MISMATCH | 403 |
