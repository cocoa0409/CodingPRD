# Whistleblower Hotline & Investigations API — Product Requirements Document

## 1. Introduction

Corporate ethics and compliance offices live or die by two promises: that a reporter can come forward without fear, and that every allegation is worked through a defensible, auditable process. This document specifies the Whistleblower Hotline & Investigation Case Management API, the system of record for that process. It covers the full arc of a report — anonymous or identified intake, triage and severity scoring, conflict-screened routing to an investigator, interview documentation and evidence preservation under dual control, substantiation determination with independent review, remediation tracking, post-closure retaliation monitoring, and periodic reporting to the audit committee.

Three design commitments shape everything that follows. First, **confidentiality is a hard boundary, not a display preference**: reporter identity material is write-only, minted credentials are shown exactly once, and no staff-facing response ever carries them. Second, **no consequential step is performed by one person alone**: screening, waiver, review, sealing, verification, and hold release each require a different actor than the person whose work is being checked, and the API enforces this segregation of duties mechanically. Third, **time is a first-class input**: service-level deadlines, monitoring windows, auto-acknowledgement, overdue marking, and risk-score decay are all evaluated against a controllable logical clock so that compliance behavior is deterministic and testable.

The API is mounted under the `/hotline` prefix. All resources are top-level; relationships between them are expressed through identifiers carried in request bodies, and reverse reachability (for example, listing the interviews of a case) is provided through nested list endpoints.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is valid but not permitted for the target endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The declared roles, spelled exactly as the API expects them, are:

- `HotlineReporter` — the person who filed a report, whether anonymous or identified. When `X-User-Role` is `HotlineReporter`, `X-User-ID` is an opaque credential not tied to any persisted entity: it is the `reporter_access_key` minted at intake for one specific case. The server compares it against the case's stored `reporter_access_key` on every reporter self-service call and rejects mismatches with `ERR_REPORTER_ACCESS_DENIED` (HTTP 403).
- `IntakeSpecialist` — hotline intake and triage operator; routes cases and performs conflict screening. When `X-User-Role` is `IntakeSpecialist`, `X-User-ID` is the `id` of the acting `StaffMember`; the referenced staff member must have `employment_status` equal to `ACTIVE` and must carry the `INTAKE` element in `capabilities`, otherwise the request fails with `ERR_CAPABILITY_MISSING` (HTTP 403).
- `Investigator` — assigned case investigator; documents interviews, preserves evidence, and drafts determinations. When `X-User-Role` is `Investigator`, `X-User-ID` is the `id` of the acting `StaffMember`, who must be `ACTIVE` and carry the `INVESTIGATION` capability, otherwise `ERR_CAPABILITY_MISSING` (HTTP 403). Investigator-owned action endpoints additionally require the caller to be the staff member bound to the resource — the case's `assigned_investigator_id`, the interview's `investigator_id`, or the determination's `decided_by_id` — and reject other callers with `ERR_NOT_ASSIGNED_INVESTIGATOR` (HTTP 403).
- `ComplianceOfficer` — ethics and compliance officer; owns waivers, activation and release, determination review, remediation oversight, legal holds, retaliation handling, and reporting. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is the `id` of the acting `StaffMember`, who must be `ACTIVE` and carry the `OFFICER` capability, otherwise `ERR_CAPABILITY_MISSING` (HTTP 403).
- `AuditCommitteeMember` — audit committee reader; consumes reports and inspects the audit trail. When `X-User-Role` is `AuditCommitteeMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `EthicsPlatformAdmin` — platform operator; maintains the staff registry and controls the logical clock. When `X-User-Role` is `EthicsPlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

For the three entity-backed roles (`IntakeSpecialist`, `Investigator`, `ComplianceOfficer`), ownership checks on any resource that references a `StaffMember` compare the resource's relevant foreign-key field to `X-User-ID`, and the server records the caller's identity on audit reference fields such as `triaged_by_id`, `routed_by_id`, `screened_by_id`, `waived_by_id`, `uploaded_by_id`, `sealed_by_id`, `excluded_by_id`, `decided_by_id`, `reviewed_by_id`, `created_by_id`, `verified_by_id`, `placed_by_id`, `released_by_id`, and `dismissed_by_id`. The `generated_by_id` of an audit committee report records whoever created it — a `StaffMember.id` for officer-created reports, or the opaque identifier otherwise.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses are sorted by `created_at` in ascending order unless otherwise stated. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource carries an `id`, minted by the server as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and `version`, an integer that starts at its initial value and is incremented by exactly 1 on each mutating operation applied to that resource. Two resources are exceptions: `CaseClosureNotice` and `CaseStatusEvent` carry only `id` and `created_at` — both `updated_at` and `version` are absent from them.

Where this document states that an operation "increments the case's `version`", the increment is part of the same atomic mutation as the rest of the operation's effects; every mutation in this system is applied atomically within the request that triggered it, and deferred time-driven effects are applied synchronously by the clock sweep described in §2.9.

### 2.5. Confidentiality Firewall and Reporter Identity

Two fields are classified CONFIDENTIAL and are subject to an absolute output firewall. `reporter_contact` is accepted at intake only when the reporter chose to identify themselves, and `reporter_access_key` is minted by the server at intake and returned exactly once — in the response to the intake call itself. Neither field is ever present in any staff-facing response: not in case list payloads, not in single-case reads, not in any child-resource payload. Staff-facing case views are always redacted accordingly. The reporter's own self-service channel authenticates by requiring `X-User-ID` to equal the case's `reporter_access_key`, so the key functions simultaneously as credential and as the reporter's only handle on the case.

### 2.6. Segregation of Duties

Seven separation rules are enforced mechanically; each violation is rejected with HTTP 409 and a dedicated error identifier.

1. The staff member who triaged a case may not become its investigator: an explicit routing override naming the triager fails with `ERR_SOD_TRIAGER_INELIGIBLE`.
2. A candidate investigator may not screen their own assignment: `ERR_SOD_SELF_SCREEN`.
3. The officer waiving a conflict must differ from both the screener who found it and the candidate investigator: `ERR_SOD_SELF_WAIVER`.
4. The officer reviewing a determination must differ from the investigator who decided it: `ERR_SOD_SELF_REVIEW`.
5. The staff member sealing an evidence item must differ from the one who uploaded it: `ERR_SOD_SELF_SEAL`.
6. The officer deciding or verifying a remediation action must differ from the officer who created it: `ERR_SOD_SELF_VERIFY`.
7. The officer releasing a legal hold must differ from the officer who placed it: `ERR_SOD_HOLD_RELEASE`.

### 2.7. Legal Holds and the Frozen Case Posture

Every case has a derived `posture`, which is `FROZEN` whenever at least one `LegalHold` referencing the case has `status` equal to `ACTIVE`, and `NORMAL` otherwise. The posture is recomputed whenever a hold is placed or released; it is never set directly. A `FROZEN` posture gates five operations, each rejected with `ERR_LEGAL_HOLD_FREEZE` (HTTP 409): creating an assignment proposal, activating a cleared assignment, scheduling an interview, excluding an evidence item, and a case's entry into `CLOSURE_READY` — whether that entry is attempted through determination approval or through the automatic remediation close-out evaluation, in which case the evaluation is deferred and re-run when the hold is released.

### 2.8. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control, and both name the same parent entity. When proposing an assignment for a case, the request must carry `expected_case_version` holding the `version` of the case as the client last observed it. When creating a determination draft for a case, the request must likewise carry `expected_case_version`. In both operations, if the supplied value does not match the case's current `version` — meaning the case has been advanced by another write since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This is what prevents a client from proposing an assignment (which legitimately supersedes the prior non-terminal assignment) or drafting a determination (which legitimately supersedes an existing draft) on the basis of a case state it has not observed. Endpoints other than these two take no version field.

### 2.9. The Logical Clock and Scheduled Sweeps

All timestamps in this system — `received_at`, `flagged_at`, `sent_at`, `acknowledged_at`, `conducted_at`, `closed_at`, `closure_ready_at`, due dates, hold intervals, and every deadline computation — are read from a logical clock, never from wall-clock time. Before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z. An `EthicsPlatformAdmin` may advance the logical clock through an administrative capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`.

Advancing the clock applies its deferred effects synchronously, before the response is returned, in one sweep. The sweep: marks any `IN_PROGRESS` remediation action whose `due_date` is now in the past as `OVERDUE`; auto-acknowledges any `SENT` closure notice whose send time lies at least 14 days in the past (which creates the monitoring plan and moves the case to `MONITORING`); performs missed check-in accounting on active monitoring plans; and completes any monitoring plan whose window has ended (which closes the case).

### 2.10. Tamper-Evident Audit Trail

Every case carries an append-only event log of `CaseStatusEvent` rows. Each event records the `case_id`, an `event_type`, the `from_status` and `to_status` involved (each null when not applicable), the `actor_role` and `actor_id` of the triggering call (the literal value `SYSTEM` for both when the clock sweep caused the event), and `occurred_at` from the logical clock. The event type vocabulary is fixed: `CASE_CREATED`, `TRIAGED`, `ASSIGNMENT_PROPOSED`, `SCREENED`, `CONFLICT_WAIVED`, `ASSIGNMENT_ACTIVATED`, `ASSIGNMENT_RELEASED`, `ASSIGNMENT_SUPERSEDED`, `DETERMINATION_DRAFTED`, `DETERMINATION_SUBMITTED`, `DETERMINATION_APPROVED`, `DETERMINATION_RETURNED`, `CLOSURE_READY`, `NOTICE_ACKNOWLEDGED`, `MONITORING_STARTED`, `MONITORING_COMPLETED`, `RETALIATION_ESCALATED`, `CASE_REOPENED`, `CASE_CLOSED`, `CASE_REJECTED`, `CASE_WITHDRAWN`, `LEGAL_HOLD_PLACED`, and `LEGAL_HOLD_RELEASED`. Events are never updated or deleted. Evidence items additionally anchor tamper evidence through a client-supplied `checksum`, which must be the SHA-256 hex digest of the content — exactly 64 lowercase hexadecimal characters.

### 2.11. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. First, header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, whether the role is permitted for the endpoint at all (`ERR_INSUFFICIENT_PERMISSIONS`). Third, for entity-backed roles, the capability and active-employment check (`ERR_CAPABILITY_MISSING`). Fourth, actor-resource binding: reporter access-key equality (`ERR_REPORTER_ACCESS_DENIED`) and investigator ownership (`ERR_NOT_ASSIGNED_INVESTIGATOR`). Fifth, path resource existence, validated left to right along the URL hierarchy (`ERR_NOT_FOUND`). Sixth, request-body well-formedness — required fields present, enum values valid, string length floors met, intervals well-formed, checksum format valid (`ERR_INVALID_REQUEST`, `ERR_INVALID_INTERVAL`). Seventh, optimistic concurrency (`ERR_STALE_VERSION`). Eighth, target-entity state preconditions (the family of state errors such as `ERR_CASE_NOT_RECEIVED`, `ERR_ASSIGNMENT_NOT_PROPOSED`, and their siblings). Ninth, the legal-hold freeze gate (`ERR_LEGAL_HOLD_FREEZE`). Tenth, segregation-of-duties rules (the `ERR_SOD_*` family). Eleventh, routing eligibility and capacity (`ERR_SUBJECT_NAMED_AS_INVESTIGATOR`, `ERR_NO_ELIGIBLE_INVESTIGATOR`, `ERR_INVESTIGATOR_CAPACITY_EXCEEDED`). Twelfth, temporal interval rules (`ERR_INTERVIEW_OVERLAP`, `ERR_LEGAL_HOLD_OVERLAP`). Thirteenth, cross-entity integrity (`ERR_DUPLICATE_TARGET_INVALID`, `ERR_CASE_HAS_CONDUCTED_INTERVIEWS`, `ERR_DETERMINATION_NOT_APPROVED`). Fourteenth and last, completeness gates (`ERR_NO_CONDUCTED_INTERVIEW`, `ERR_UNSEALED_EVIDENCE`, `ERR_MONITORING_WINDOW_INACTIVE`, `ERR_EXTENSION_WINDOW_EXCEEDED`).

### 2.12. Precision and Rounding

Monetary-free but calculation-heavy, this API pins its numeric conventions. Severity scores and workload weights are integers; threshold comparisons on them use "at least" semantics (a score equal to a band boundary belongs to the higher band). Reported averages and rates are rounded half-up: day-count means to 2 decimal places, substantiation rates to 4 decimal places. Where a calculation specifies a rounding order (as the organization-level substantiation rate does), the order is part of the contract and is described with the calculation itself.

## 3. Business Logic & Workflows

### 3.1. Staff Registry, Capabilities, and Capacity

Before any case can be routed, the compliance office maintains its roster. An `EthicsPlatformAdmin` registers a staff member by supplying `display_name`, `email` (which must be unique across all staff), `department`, `capabilities`, and `max_active_cases`; `employment_status` may be supplied but defaults to `ACTIVE`. The `capabilities` array declares what the person may do and must be a subset of `INTAKE`, `INVESTIGATION`, and `OFFICER` — the entity-backed role calls described in §2.1 require the matching capability, so a staff member without `INVESTIGATION` can never act as an `Investigator`, and only `ACTIVE` staff pass those checks at all (`ON_LEAVE` and `TERMINATED` staff are likewise ineligible for routing). `max_active_cases` is the person's capacity cap, an integer of at least 1. The same administrator may later patch a staff member's `department`, `capabilities`, `max_active_cases`, or `employment_status`; each update increments the staff member's `version`. Staff may be listed with optional `employment_status` and `capability` filters alongside the standard `limit` and `offset` parameters.

Two workload figures are maintained on every staff member and recomputed whenever assignment activity changes them. `active_case_count` is the plain count of that person's assignments in `ACTIVE` status — assignments that have been released or superseded do not count. `weighted_caseload` sums a per-case severity weight over exactly the same set of active assignments: a `CRITICAL` case weighs 8, `HIGH` weighs 4, `MEDIUM` weighs 2, and `LOW` weighs 1. The plain count drives the capacity gate at activation time (§3.4); the weighted figure drives the routing selector's ranking. Both start at 0 for a newly registered staff member.

### 3.2. Intake: Filing a Report and the Reporter's Channel

A report enters the system through the hotline's intake channel, invoked by a `HotlineReporter`. The intake payload carries the `channel` through which the report arrived — one of `WEB_PORTAL`, `PHONE`, `EMAIL`, `IN_PERSON`, or `MAIL` — the allegation `category` as reported (one of `FRAUD`, `HARASSMENT`, `SAFETY`, `FINANCIAL_REPORTING`, `DATA_PRIVACY`, `CONFLICT_OF_INTEREST`, or `OTHER`), a free-text `description` of at least 20 characters, and the `region` used for metrics bucketing (`NORTH`, `SOUTH`, `EAST`, or `WEST`). The reporter may name accused individuals through `subject_employee_ids`, a list of employee identifiers that later disqualifies matching staff from routing on this case.

Anonymity is the default: `is_anonymous` defaults to true when omitted. When the reporter sets `is_anonymous` to false, a `reporter_contact` value must be supplied; when the report is anonymous, `reporter_contact` is not allowed at all. Per §2.5, `reporter_contact` is never returned in any staff-facing response.

A successful intake creates the case in `RECEIVED` status, stamps `received_at` from the logical clock, appends a `CASE_CREATED` event, and mints the case's `reporter_access_key`. The key is returned in this intake response and nowhere else, ever again. From then on, the reporter's entire relationship with the system runs through that key. A reporter self-service view answers with exactly four fields — `case_status`, `severity`, `closure_summary`, and `monitoring_active` — and only when `X-User-ID` equals the case's `reporter_access_key`; any other key is refused with `ERR_REPORTER_ACCESS_DENIED`. While the case is still in `RECEIVED` or `TRIAGED`, the reporter may withdraw it, which moves it to `WITHDRAWN` and appends a `CASE_WITHDRAWN` event; withdrawal in any later state fails with `ERR_CASE_NOT_WITHDRAWABLE`, and withdrawal with a wrong key fails with `ERR_REPORTER_ACCESS_DENIED`.

Staff-facing case retrieval — the list and the single-case read — supports filtering the list by `status`, `severity`, `region`, `assigned_investigator_id`, and `duplicate_of_case_id`, plus `limit` and `offset`. Both views obey the confidentiality firewall of §2.5.

### 3.3. Triage, Severity Scoring, and Rejection

Triage is performed by an `IntakeSpecialist` and is only legal while the case is `RECEIVED`; triaging a case in any other state is rejected with `ERR_CASE_NOT_RECEIVED`. The triage payload carries a questionnaire: `confirmed_category` (the category the specialist confirms, drawn from the same vocabulary as the reported `category`), `subject_seniority` (one of `EXECUTIVE`, `MANAGER`, `STAFF`, `UNKNOWN`), `financial_exposure_band` (one of `ABOVE_1M`, `HIGH_1M`, `MID_100K`, `LOW_10K`, `NONE`), `reporter_vulnerability` (one of `DIRECT_REPORT`, `SAME_TEAM`, `NONE`), and the `triage_decision`, which is either `PROCEED` or `REJECT`. A malformed triage payload — missing fields or out-of-vocabulary values — fails with `ERR_INVALID_REQUEST`.

On `PROCEED`, the system computes a severity score from exactly the four questionnaire inputs on this case. The score is the sum of four additive factors: a category base (`FRAUD` 30, `FINANCIAL_REPORTING` 30, `SAFETY` 25, `HARASSMENT` 20, `DATA_PRIVACY` 20, `CONFLICT_OF_INTEREST` 15, `OTHER` 10), a seniority factor (`EXECUTIVE` 25, `MANAGER` 15, `STAFF` 5, `UNKNOWN` 0), an exposure factor (`ABOVE_1M` 30, `HIGH_1M` 20, `MID_100K` 10, `LOW_10K` 5, `NONE` 0), and a vulnerability factor (`DIRECT_REPORT` 15, `SAME_TEAM` 10, `NONE` 0). The integer score maps to a band: at least 75 is `CRITICAL`; 55 through 74 inclusive is `HIGH`; 35 through 54 inclusive is `MEDIUM`; 34 or less is `LOW`. The case's `severity` is set to that band, and its `sla_days` — the calendar-day budget for the investigation — is keyed to the severity: `CRITICAL` 30 days, `HIGH` 60 days, `MEDIUM` 90 days, `LOW` 120 days. Until triage, both `severity` and `confirmed_category` are null. The triage also stamps `triaged_by_id` with the specialist's `X-User-ID` — an audit reference that later bars that person from investigating the case — moves the case to `TRIAGED`, appends a `TRIAGED` event, and increments the case's `version`.

On `REJECT`, the case moves to `REJECTED` and a `CASE_REJECTED` event is appended; the specialist may attach a free-text `reject_reason`. When the rejection is because the report duplicates an existing case, the payload supplies `duplicate_of_case_id`, which is stored on the rejected case; the referenced case must exist and must not be in a terminal state (`CLOSED`, `REJECTED`, or `WITHDRAWN`), otherwise the request fails with `ERR_DUPLICATE_TARGET_INVALID`.

### 3.4. Investigator Routing, Screening, and the Assignment Lifecycle

Once a case is `TRIAGED` (or `REOPENED` after a retaliation escalation), routing proposes a candidate investigator by creating a case assignment. Both `IntakeSpecialist` and `ComplianceOfficer` callers may propose, but only a `ComplianceOfficer` may steer the proposal to a specific person. A proposal in a case state other than `TRIAGED`, `REOPENED`, or the supersede-eligible form of `ASSIGNED` described below is rejected with `ERR_CASE_NOT_TRIAGED_OR_REOPENED`. Because proposing an assignment supersedes the case's prior non-terminal assignment, this operation is OCC-guarded: the payload must carry `expected_case_version` matching the case's current `version`, or the proposal fails with `ERR_STALE_VERSION` per §2.8. A `FROZEN` case cannot be routed at all (`ERR_LEGAL_HOLD_FREEZE`).

Without an explicit target, the **auto selector** runs. A staff member is eligible when all of the following hold: their `employment_status` is `ACTIVE`; `INVESTIGATION` appears in their `capabilities`; they are not the staff member recorded as `triaged_by_id` on this case; neither their `email` nor their `display_name` appears among the case's `subject_employee_ids`; and their `active_case_count` is currently below their `max_active_cases`. The eligible pool is ranked by `weighted_caseload` ascending, ties broken by `active_case_count` ascending, remaining ties broken by the staff member's `created_at` ascending, and the top-ranked member wins. An empty pool is rejected with `ERR_NO_ELIGIBLE_INVESTIGATOR`.

With an explicit `investigator_id` in the payload — the **override path** — the caller must be a `ComplianceOfficer`, should document why in the optional `override_reason`, and the named target must independently satisfy the same eligibility bar, with two checks surfaced distinctly: naming the triager fails with `ERR_SOD_TRIAGER_INELIGIBLE`, and naming a person whose `email` or `display_name` appears in `subject_employee_ids` fails with `ERR_SUBJECT_NAMED_AS_INVESTIGATOR`. The resulting assignment records how it came about in `selection_mode` — `AUTO` for the selector, `OVERRIDE` for an explicit nomination.

A successful proposal creates the assignment in `PROPOSED` status with `routed_by_id` set to the creator, points the case's `assigned_investigator_id` at the candidate, moves the case to `ASSIGNED`, appends an `ASSIGNMENT_PROPOSED` event, and increments the case's `version`. If the case was `ASSIGNED` with an existing assignment still in `PROPOSED`, `CONFLICT_PENDING`, or `CLEARED`, that prior assignment is moved to `SUPERSEDED` in the same operation, with an `ASSIGNMENT_SUPERSEDED` event — this supersede path is the only way a new proposal is legal while the case is already `ASSIGNED`.

Screening comes next, performed by an `IntakeSpecialist` or `ComplianceOfficer` other than the candidate (self-screening fails with `ERR_SOD_SELF_SCREEN`), and only while the assignment is `PROPOSED` (otherwise `ERR_ASSIGNMENT_NOT_PROPOSED`). The screening payload carries an `outcome` and optional free-text `notes`. An outcome of `CLEAR` moves the assignment to `CLEARED`. An outcome of `CONFLICT_FOUND` moves it to `CONFLICT_PENDING` and requires a `conflict_type` — one of `PERSONAL_RELATIONSHIP`, `FINANCIAL_INTEREST`, `PRIOR_INVOLVEMENT`, or `REPORTING_LINE` — which is stored on the assignment; omitting it fails with `ERR_INVALID_REQUEST`. Either way `screened_by_id` records the screener and a `SCREENED` event is appended.

A conflict is not necessarily fatal. A `ComplianceOfficer` may waive it, moving the assignment from `CONFLICT_PENDING` to `CLEARED`; waiving an assignment in any other state fails with `ERR_ASSIGNMENT_NOT_CONFLICT_PENDING`. The waiving officer must differ from both the screener and the candidate (`ERR_SOD_SELF_WAIVER`), and must supply a `waiver_justification` of at least 20 characters. The waiver records `waived_by_id` and appends a `CONFLICT_WAIVED` event.

Activation, by a `ComplianceOfficer`, turns a `CLEARED` assignment into the working assignment: activating from any other state fails with `ERR_ASSIGNMENT_NOT_CLEARED`. Two gates guard it — the case's posture must be `NORMAL` (`ERR_LEGAL_HOLD_FREEZE`), and the candidate's `active_case_count` must currently be below their `max_active_cases`, otherwise the activation fails with `ERR_INVESTIGATOR_CAPACITY_EXCEEDED`. On success the assignment becomes `ACTIVE`, the investigator's `active_case_count` rises by 1 and their `weighted_caseload` is recomputed, the case moves to `UNDER_INVESTIGATION`, an `ASSIGNMENT_ACTIVATED` event is appended, and the case's `version` increments.

Release unwinds an assignment and always returns the case to `TRIAGED`. Releasing a `PROPOSED`, `CONFLICT_PENDING`, or `CLEARED` assignment simply marks it `RELEASED` and clears the case's `assigned_investigator_id`. Releasing an `ACTIVE` assignment additionally requires that no interview of the case has reached `CONDUCTED` — otherwise the release fails with `ERR_CASE_HAS_CONDUCTED_INTERVIEWS` — and decrements the investigator's `active_case_count` by 1 with `weighted_caseload` recomputed. Releasing an assignment already in a terminal state (`RELEASED` or `SUPERSEDED`) fails with `ERR_ASSIGNMENT_NOT_RELEASABLE`. Every release appends an `ASSIGNMENT_RELEASED` event and increments the case's `version`. All assignments of a case can be listed with optional `status` filtering and standard pagination.

### 3.5. Interviews and Evidence Under Investigation

With the case `UNDER_INVESTIGATION`, the assigned investigator builds the record. Scheduling an interview is an `Investigator` operation and requires the caller to be the case's `assigned_investigator_id` — anyone else is refused with `ERR_NOT_ASSIGNED_INVESTIGATOR` — and the case to be `UNDER_INVESTIGATION`, otherwise `ERR_CASE_NOT_UNDER_INVESTIGATION`; a `FROZEN` case blocks scheduling with `ERR_LEGAL_HOLD_FREEZE`. The payload names the case through `case_id` and describes the session: `interviewee_role` (`SUBJECT`, `WITNESS`, or `REPORTER`), a free-text `interviewee_identifier`, and a half-open interval from `scheduled_start` to `scheduled_end`, where the end must be strictly later than the start or the request fails with `ERR_INVALID_INTERVAL`. One investigator's calendar must keep its spacing: the new interval must leave a gap of at least 15 minutes to every other `SCHEDULED` or `CONDUCTED` interview of the same investigator; a violation is rejected with `ERR_INTERVIEW_OVERLAP`. A created interview is `SCHEDULED`, with its `investigator_id` set to the caller.

Concluding an interview moves it out of `SCHEDULED` — concluding from any other state fails with `ERR_INTERVIEW_NOT_SCHEDULED`. The owning investigator may conclude with an `outcome` of `CONDUCTED`, which requires a `summary` of at least 50 characters (otherwise `ERR_INVALID_REQUEST`) and stamps `conducted_at` from the logical clock, or with `NO_SHOW`, which needs no summary. Cancellation — `outcome` `CANCELLED` — may be performed by the investigator or by a `ComplianceOfficer`. A case's interviews can be listed with optional `status` filtering and pagination.

Evidence follows a parallel discipline. The assigned investigator registers an evidence item against a case that is `UNDER_INVESTIGATION` (otherwise `ERR_CASE_NOT_UNDER_INVESTIGATION`; a caller who is not the assigned investigator is refused with `ERR_NOT_ASSIGNED_INVESTIGATOR`), supplying `case_id`, an `evidence_type` (`DOCUMENT`, `PHOTO`, `EMAIL`, `AUDIO`, or `OTHER`), a `description` of at least 10 characters, the `checksum` as specified in §2.10, and `captured_at`, the moment the evidence was originally captured. The item is born `PRESERVED` with `uploaded_by_id` set to the caller.

Sealing is the dual-control step: any of `IntakeSpecialist`, `Investigator`, or `ComplianceOfficer` may seal a `PRESERVED` item, but never the person who uploaded it (`ERR_SOD_SELF_SEAL`); sealing an item in any other state fails with `ERR_EVIDENCE_NOT_PRESERVED`. The seal records `sealed_by_id` and moves the item to `SEALED`. Exclusion, by contrast, is officer-only: a `ComplianceOfficer` may exclude an item that is `PRESERVED` or `SEALED` (otherwise `ERR_EVIDENCE_NOT_EXCLUDABLE`), must supply an `exclusion_reason` of at least 20 characters, and cannot do so while the case is `FROZEN` (`ERR_LEGAL_HOLD_FREEZE`). Exclusion records `excluded_by_id` and moves the item to `EXCLUDED`, its terminal state. A case's evidence can be listed with optional `status` filtering and pagination.

### 3.6. Determinations and Remediation

When the record is built, the assigned investigator drafts a determination. Draft creation requires the case to be `UNDER_INVESTIGATION` (`ERR_CASE_NOT_UNDER_INVESTIGATION`), the caller to be the assigned investigator (`ERR_NOT_ASSIGNED_INVESTIGATOR`), and — because a new draft legitimately supersedes an existing draft — the OCC guard of §2.8: the payload's `expected_case_version` must match the case's current `version`, or the draft is rejected with `ERR_STALE_VERSION`. The draft carries a `finding` (`SUBSTANTIATED`, `UNSUBSTANTIATED`, or `INCONCLUSIVE`) and a `rationale` of at least 50 characters. Creating it moves any existing `DRAFT` determination of the case to `SUPERSEDED`, records `decided_by_id` as the caller, appends a `DETERMINATION_DRAFTED` event, and increments the case's `version`. Determinations of a case can be listed (optional `status` filter, standard pagination), and a single determination can be read directly.

Submitting the draft, again by the deciding investigator personally (a different caller fails with `ERR_NOT_ASSIGNED_INVESTIGATOR`), moves it from `DRAFT` to `SUBMITTED` — submitting from any other state fails with `ERR_DETERMINATION_NOT_DRAFT` — and moves the case to `DETERMINATION_REVIEW`. Two completeness gates guard submission, in this order relative to the other checks per §2.11: at least one interview of the case must have reached `CONDUCTED` (`ERR_NO_CONDUCTED_INTERVIEW`), and no evidence item of the case may still be `PRESERVED` (`ERR_UNSEALED_EVIDENCE`). Submission appends a `DETERMINATION_SUBMITTED` event and increments the case's `version`.

Review belongs to a `ComplianceOfficer` who is not the decider (`ERR_SOD_SELF_REVIEW`) and applies to a `SUBMITTED` determination (`ERR_DETERMINATION_NOT_SUBMITTED`). The review payload carries a `decision` and `review_notes` of at least 10 characters; `reviewed_by_id` records the reviewer. Three outcomes exist. A `RETURN` decision moves the determination to `RETURNED`, sends the case back to `UNDER_INVESTIGATION`, and appends `DETERMINATION_RETURNED`. An `APPROVE` decision on a `SUBSTANTIATED` finding moves the determination to `APPROVED`, sets the case's `determination_finding` to `SUBSTANTIATED`, moves the case to `REMEDIATION`, and appends `DETERMINATION_APPROVED`. An `APPROVE` decision on an `UNSUBSTANTIATED` or `INCONCLUSIVE` finding moves the determination to `APPROVED`, sets `determination_finding` accordingly, stamps `closure_ready_at` from the logical clock, and moves the case directly to `CLOSURE_READY` — but only while the case posture is `NORMAL`, since entry into `CLOSURE_READY` is hold-gated (`ERR_LEGAL_HOLD_FREEZE`). In that direct-to-closure path the review payload must also carry `notice_summary`, from which the system composes the reporter-safe `closure_summary` of the closure notice it creates in `SENT` status with `sent_at` stamped; the events appended are `DETERMINATION_APPROVED` and `CLOSURE_READY`. All review outcomes increment the case's `version`.

A `SUBSTANTIATED` case owes remediation. An officer proposes a remediation action on an `APPROVED` determination whose finding is `SUBSTANTIATED` — any other determination fails with `ERR_DETERMINATION_NOT_APPROVED` — supplying `action_type` (`POLICY_CHANGE`, `DISCIPLINE`, `TRAINING`, `PROCESS_FIX`, or `MONITORING`), the accountable `owner_department`, a `description` of at least 10 characters, and a `due_date`. The action is created `PROPOSED` with `created_by_id` set to the caller, and both `determination_id` and a denormalized `case_id` recorded so actions can be filtered directly by case.

From `PROPOSED`, a different officer than the creator (`ERR_SOD_SELF_VERIFY`) decides the action: deciding from any state other than `PROPOSED` fails with `ERR_REMEDIATION_INVALID_STATE`. Approval moves it to `IN_PROGRESS`; rejection moves it to `REJECTED`. While `IN_PROGRESS`, the clock sweep marks the action `OVERDUE` once the current time passes its `due_date`. An `OVERDUE` action can be brought back to `IN_PROGRESS` by extending it: the new `due_date` must be strictly later than now and no later than 30 days from now, otherwise `ERR_EXTENSION_WINDOW_EXCEEDED`; each successful extension increments the action's `extension_count`. Verification — by an officer other than the creator (`ERR_SOD_SELF_VERIFY`), and only from `IN_PROGRESS` (otherwise `ERR_REMEDIATION_INVALID_STATE`) — moves the action to `VERIFIED` and records `verified_by_id`. A case's remediation actions can be listed with optional `status` filtering and pagination.

Every remediation mutation — decide, verify, extend — and every legal-hold release re-evaluates the case's close-out rule: if the case is in `REMEDIATION`, at least one remediation action exists for it, and zero actions remain in `PROPOSED`, `IN_PROGRESS`, or `OVERDUE`, then the case closes out. A substantiated case with no actions at all therefore stays in `REMEDIATION` until an action is proposed and then decided or verified. If the posture is `FROZEN` at evaluation time, the transition is deferred and re-evaluated when the hold is released. When the rule fires, the case moves to `CLOSURE_READY`, `closure_ready_at` is stamped, a closure notice is created in `SENT` status, a `CLOSURE_READY` event is appended, and the case's `version` increments.

### 3.7. Closure, Monitoring, and Retaliation Escalation

A case in `CLOSURE_READY` has exactly one outstanding closure notice for the cycle; the notices of a case can be listed (there is at most one per closure cycle, and the latest drives monitoring). Acknowledgement moves the notice from `SENT` to `ACKNOWLEDGED` — acknowledging a notice in any other state fails with `ERR_NOTICE_NOT_SENT`. Two paths acknowledge. The reporter acknowledges through the reporter channel, which requires `X-User-ID` to equal the case's `reporter_access_key` (`ERR_REPORTER_ACCESS_DENIED`). Or the clock sweep auto-acknowledges once the current time reaches or passes `sent_at` plus 14 days — the 14-day boundary is inclusive. Either path stamps `acknowledged_at`, and in the same stroke creates the case's monitoring plan and moves the case to `MONITORING`, appending `NOTICE_ACKNOWLEDGED` and `MONITORING_STARTED` events and incrementing the case's `version`.

The monitoring plan — at most one per case, listable from the case — starts its `start_at` at the notice's `acknowledged_at` and computes `end_at` as exactly 365 days later. Check-ins run on a fixed 30-day cadence, recorded in `check_in_interval_days`: `next_check_in_due` is initially `start_at` plus 30 days. An officer records a check-in while the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), which stamps `last_check_in_at` and pushes `next_check_in_due` to 30 days after the check-in moment; `last_check_in_at` is null until the first check-in. The clock sweep performs the missed-check-in accounting: each time the current time passes `next_check_in_due` by more than a 3-day grace while the plan is `ACTIVE`, the sweep increments `missed_checkin_count` by exactly 1 and advances `next_check_in_due` by 30 days, repeating the evaluation so that one sweep catches up several missed intervals. While a plan is `SUSPENDED` or `COMPLETED`, `next_check_in_due` is null. When the sweep reaches a moment at or after `end_at` with the plan still `ACTIVE`, the plan becomes `COMPLETED`, the case's `closed_at` is stamped, and the case moves to `CLOSED` with `MONITORING_COMPLETED` and `CASE_CLOSED` events.

Monitoring exists to catch retaliation. While a case is `MONITORING`, a retaliation flag can be filed against it — filing against a case in any other status fails with `ERR_MONITORING_WINDOW_INACTIVE`. The reporter files through the reporter channel, and that path forces `reported_via` to `REPORTER_CHECKIN`; a `ComplianceOfficer` files with `reported_via` chosen as `HR_SIGNAL` or `MANUAL`. Every flag carries a `description` of at least 10 characters, is created `OPEN` with `flagged_at` stamped, and has a computed `weight`: `REPORTER_CHECKIN` weighs 3, `HR_SIGNAL` 2, `MANUAL` 1.

The case's `retaliation_risk_score` is the sum of the weights of its flags that are `OPEN` and whose `flagged_at` falls inside the rolling window from 90 days ago through now, inclusive of both ends. Creating a flag recomputes the score; if the new total reaches at least 4 while the case is `MONITORING`, the escalation cascade fires atomically: every contributing `OPEN` flag becomes `ESCALATED`; the case moves to `REOPENED`, its `severity` is bumped one band (`LOW` to `MEDIUM` to `HIGH` to `CRITICAL`, with `CRITICAL` remaining `CRITICAL`) and its `sla_days` recomputed against the new severity, `reopen_count` rises by 1, and `assigned_investigator_id` is cleared; the monitoring plan becomes `SUSPENDED` with `next_check_in_due` nulled; `RETALIATION_ESCALATED` and `CASE_REOPENED` events are appended; and the case's `version` increments. A reopened case re-enters routing per §3.4. An officer may instead dismiss an `OPEN` flag (dismissing from any other state fails with `ERR_FLAG_NOT_OPEN`), which records `dismissed_by_id`, moves the flag to `DISMISSED`, and recomputes the score with the dismissed flag excluded. A case's flags can be listed with optional `status` filtering and pagination.

### 3.8. Legal Holds

Legal holds are the compliance office's brake pedal. A `ComplianceOfficer` places a hold by supplying `case_id`, a closed interval from `start_at` to `end_at` — both ends inclusive, with `end_at` no earlier than `start_at` or the request fails with `ERR_INVALID_INTERVAL` — and a `reason` of at least 10 characters. The target case must be non-terminal; placing a hold on a `CLOSED`, `REJECTED`, or `WITHDRAWN` case fails with `ERR_CASE_TERMINAL`. And on a single case, a new hold's closed interval may not touch or overlap the closed interval of any `ACTIVE` hold — a violation fails with `ERR_LEGAL_HOLD_OVERLAP`. The hold is created `ACTIVE` with `placed_by_id` set to the caller, the case's `posture` is recomputed (becoming `FROZEN`), and a `LEGAL_HOLD_PLACED` event is appended. A case's holds can be listed with optional `status` filtering.

Release is deliberately somebody else's job: a `ComplianceOfficer` other than the placer (`ERR_SOD_HOLD_RELEASE`) releases an `ACTIVE` hold (releasing from any other state fails with `ERR_HOLD_NOT_ACTIVE`). The release records `released_by_id`, moves the hold to `RELEASED`, appends a `LEGAL_HOLD_RELEASED` event, and recomputes the case posture — which returns to `NORMAL` if no other `ACTIVE` hold remains. If the case had been sitting in `REMEDIATION` with its close-out deferred by the freeze, the close-out rule of §3.6 is re-evaluated at this point.

### 3.9. Audit Committee Reporting and Case Metrics

Periodic accountability runs through the audit committee report. A `ComplianceOfficer` creates a report by supplying `period_start` and `period_end`, a half-open window with the start inclusive and the end exclusive — the end must be strictly later than the start, otherwise `ERR_INVALID_INTERVAL`. The report is created `DRAFT` with its metric fields computed as of creation; finalization re-computes all metric fields as of the finalize moment and then freezes them — finalizing a report that is not `DRAFT` fails with `ERR_REPORT_NOT_DRAFT`, and after finalization the metrics are immutable. Presentation, by an `AuditCommitteeMember` or a `ComplianceOfficer`, moves a `FINALIZED` report to `PRESENTED` (otherwise `ERR_REPORT_NOT_FINALIZED`). Reports can be listed with optional `status` filtering and pagination; the audit trail endpoint of §2.10 is also open to committee members, filterable by `event_type` with standard pagination.

Eight metrics are computed over the window. `total_received` counts cases whose `received_at` falls inside the window. `total_closures` counts cases — of any region — whose `closure_ready_at` falls inside the window; that closure set includes cases now in `CLOSURE_READY`, `MONITORING`, `CLOSED`, or `REOPENED`, because a reopen does not erase the `closure_ready_at` of the prior cycle. `overdue_remediation_count` counts remediation actions in `OVERDUE` status at computation time. `retaliation_escalation_count` counts flags in `ESCALATED` status whose `flagged_at` falls inside the window.

Two day-count averages are taken over the closure set, each rounded half-up to 2 decimal places and each null when the closure set is empty. `avg_days_to_close_calendar` is the arithmetic mean, over the closure set, of each case's elapsed whole UTC days from `received_at` to `closure_ready_at` (partial days discarded). `avg_days_to_close_hold_adjusted` uses the identical inputs but reduces each case's day count by the number of distinct UTC dates that lie within the case's received-to-closure-ready date range and are covered by at least one of the case's legal holds — `ACTIVE` or `RELEASED`, and a date covered by two holds counts once. The adjusted figure therefore never exceeds the calendar figure.

Two substantiation rates are published for contrast, both rounded half-up to 4 decimal places. `org_substantiation_rate` is computed region-first: for each region that has at least one closure in the window, the region's rate is the count of its `SUBSTANTIATED` closures divided by all of its closures in the window, rounded half-up to 4 decimal places; the report value is then the arithmetic mean of those rounded per-region rates over exactly the regions with closures, itself rounded half-up to 4 decimal places. The rounding order is pinned — per-region rates are rounded first, then averaged, then the average is rounded — because summing all cases first and rounding once yields a different number. That alternative is exposed separately as `pooled_substantiation_rate`: the total count of `SUBSTANTIATED` closures in the window divided by the total closures in the window, rounded half-up to 4 decimal places.

Independent of reporting, every staff-facing read of a case derives its SLA posture on the fly. The evaluation order is fixed: take the case's current `severity` — the band as of the latest of triage time and the most recent reopen, noting that a reopen bump moves the SLA band — then compute a base deadline as the calendar date of `received_at` plus the `sla_days` for that severity, where `received_at` itself never resets even across reopens. Next count the distinct UTC dates covered by any of the case's legal holds, `ACTIVE` or `RELEASED`, that intersect the span from the received date through today, and add that many days to the base deadline. The case is breached when today is later than that adjusted deadline and the case's status is none of `CLOSED`, `REJECTED`, `WITHDRAWN`, `CLOSURE_READY`, or `MONITORING`.

## 4. Endpoint Definitions

All endpoints live under the `/hotline` prefix, except the test-driving clock control. Resource-creating operations return HTTP 201 with the created resource; operations that modify an existing resource, and all reads, return HTTP 200. Request bodies, response shapes, side effects, and error conditions for each endpoint are specified in §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /hotline/staff-members | Register a staff member | EthicsPlatformAdmin |
| GET | /hotline/staff-members | List staff members | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| PATCH | /hotline/staff-members/{id} | Update staff capacity, capabilities, or employment status | EthicsPlatformAdmin |
| POST | /hotline/cases | Anonymous hotline intake; mints the reporter access key | HotlineReporter |
| GET | /hotline/cases | List cases (staff view; reporter identity fields never present) | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| GET | /hotline/cases/{id} | Get a case (staff view, redacted) | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| GET | /hotline/cases/{id}/reporter-status | Reporter self-service case view | HotlineReporter |
| POST | /hotline/cases/{id}/withdraw | Reporter withdraws an un-triaged or un-assigned report | HotlineReporter |
| POST | /hotline/cases/{id}/triage | Triage: compute severity and proceed, or reject (optionally as duplicate) | IntakeSpecialist |
| POST | /hotline/cases/{id}/assignments | Propose an assignment (auto selector or officer override); supersedes non-terminal prior assignment; OCC on case version | IntakeSpecialist, ComplianceOfficer |
| GET | /hotline/cases/{id}/assignments | List assignments of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/assignments/{id}/screen | Record conflict-screening outcome; screener differs from candidate | IntakeSpecialist, ComplianceOfficer |
| POST | /hotline/assignments/{id}/waive-conflict | Officer waives a found conflict; officer differs from screener and candidate | ComplianceOfficer |
| POST | /hotline/assignments/{id}/activate | Activate a cleared assignment; capacity gate; case enters investigation | ComplianceOfficer |
| POST | /hotline/assignments/{id}/release | Release an assignment (pre- or post-activation); case returns to triaged | ComplianceOfficer |
| POST | /hotline/interviews | Schedule an interview (assigned investigator only; 15-minute buffer rule) | Investigator |
| GET | /hotline/cases/{id}/interviews | List interviews of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/interviews/{id}/conclude | Conclude an interview as conducted, no-show, or cancelled | Investigator, ComplianceOfficer |
| POST | /hotline/evidence-items | Register an evidence item (assigned investigator only) | Investigator |
| GET | /hotline/cases/{id}/evidence-items | List evidence of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/evidence-items/{id}/seal | Dual-control seal; sealer differs from uploader | IntakeSpecialist, Investigator, ComplianceOfficer |
| POST | /hotline/evidence-items/{id}/exclude | Exclude evidence; blocked while the case is frozen by a legal hold | ComplianceOfficer |
| POST | /hotline/cases/{id}/determinations | Create a determination draft; supersedes existing draft; OCC on case version | Investigator |
| GET | /hotline/cases/{id}/determinations | List determinations of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| GET | /hotline/determinations/{id} | Get a determination | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/determinations/{id}/submit | Submit a determination; completeness gates; case enters determination review | Investigator |
| POST | /hotline/determinations/{id}/review | Officer approves or returns; reviewer differs from decider | ComplianceOfficer |
| POST | /hotline/determinations/{id}/remediation-actions | Propose a remediation action on an approved substantiated determination | ComplianceOfficer |
| GET | /hotline/cases/{id}/remediation-actions | List remediation actions of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/remediation-actions/{id}/decide | Approve or reject a proposed action; decider differs from creator | ComplianceOfficer |
| POST | /hotline/remediation-actions/{id}/verify | Verify completion; verifier differs from creator; may cascade to closure-ready | ComplianceOfficer |
| POST | /hotline/remediation-actions/{id}/extend | Extend an overdue action within the allowed window | ComplianceOfficer |
| GET | /hotline/cases/{id}/closure-notices | List closure notices of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/closure-notices/{id}/acknowledge | Reporter acknowledges closure; creates the monitoring plan | HotlineReporter |
| GET | /hotline/cases/{id}/monitoring-plans | List monitoring plans of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/monitoring-plans/{id}/check-in | Record a monitoring check-in; resets the next due date | ComplianceOfficer |
| POST | /hotline/cases/{id}/retaliation-flags | File a retaliation signal; reporter channel forces the check-in signal type | HotlineReporter, ComplianceOfficer |
| GET | /hotline/cases/{id}/retaliation-flags | List retaliation flags of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/retaliation-flags/{id}/dismiss | Dismiss an open flag; risk score recomputed | ComplianceOfficer |
| POST | /hotline/legal-holds | Place a legal hold (closed interval; overlap and terminal-case gates) | ComplianceOfficer |
| GET | /hotline/cases/{id}/legal-holds | List legal holds of a case | IntakeSpecialist, Investigator, ComplianceOfficer, EthicsPlatformAdmin |
| POST | /hotline/legal-holds/{id}/release | Release a hold; releaser differs from placer; deferred close-out re-evaluated | ComplianceOfficer |
| POST | /hotline/audit-committee-reports | Create a draft report with a metric snapshot over the window | ComplianceOfficer |
| GET | /hotline/audit-committee-reports | List reports | ComplianceOfficer, AuditCommitteeMember, EthicsPlatformAdmin |
| POST | /hotline/audit-committee-reports/{id}/finalize | Re-compute and freeze metrics | ComplianceOfficer |
| POST | /hotline/audit-committee-reports/{id}/present | Mark a finalized report as presented to the audit committee | AuditCommitteeMember, ComplianceOfficer |
| GET | /hotline/cases/{id}/case-status-events | Read the append-only event log of a case | IntakeSpecialist, Investigator, ComplianceOfficer, AuditCommitteeMember, EthicsPlatformAdmin |
| POST | /_clock/set_current_utc | Set the logical clock; sweep effects applied synchronously | EthicsPlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_CAPABILITY_MISSING | 403 |
| ERR_REPORTER_ACCESS_DENIED | 403 |
| ERR_NOT_ASSIGNED_INVESTIGATOR | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_INTERVAL | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_CASE_NOT_RECEIVED | 409 |
| ERR_CASE_NOT_TRIAGED_OR_REOPENED | 409 |
| ERR_CASE_NOT_UNDER_INVESTIGATION | 409 |
| ERR_CASE_NOT_WITHDRAWABLE | 409 |
| ERR_CASE_TERMINAL | 409 |
| ERR_ASSIGNMENT_NOT_PROPOSED | 409 |
| ERR_ASSIGNMENT_NOT_CONFLICT_PENDING | 409 |
| ERR_ASSIGNMENT_NOT_CLEARED | 409 |
| ERR_ASSIGNMENT_NOT_RELEASABLE | 409 |
| ERR_INTERVIEW_NOT_SCHEDULED | 409 |
| ERR_EVIDENCE_NOT_PRESERVED | 409 |
| ERR_EVIDENCE_NOT_EXCLUDABLE | 409 |
| ERR_DETERMINATION_NOT_DRAFT | 409 |
| ERR_DETERMINATION_NOT_SUBMITTED | 409 |
| ERR_DETERMINATION_NOT_APPROVED | 409 |
| ERR_REMEDIATION_INVALID_STATE | 409 |
| ERR_FLAG_NOT_OPEN | 409 |
| ERR_HOLD_NOT_ACTIVE | 409 |
| ERR_NOTICE_NOT_SENT | 409 |
| ERR_PLAN_NOT_ACTIVE | 409 |
| ERR_REPORT_NOT_DRAFT | 409 |
| ERR_REPORT_NOT_FINALIZED | 409 |
| ERR_LEGAL_HOLD_FREEZE | 409 |
| ERR_SOD_TRIAGER_INELIGIBLE | 409 |
| ERR_SOD_SELF_SCREEN | 409 |
| ERR_SOD_SELF_WAIVER | 409 |
| ERR_SOD_SELF_REVIEW | 409 |
| ERR_SOD_SELF_SEAL | 409 |
| ERR_SOD_SELF_VERIFY | 409 |
| ERR_SOD_HOLD_RELEASE | 409 |
| ERR_INVESTIGATOR_CAPACITY_EXCEEDED | 409 |
| ERR_NO_ELIGIBLE_INVESTIGATOR | 409 |
| ERR_SUBJECT_NAMED_AS_INVESTIGATOR | 409 |
| ERR_INTERVIEW_OVERLAP | 409 |
| ERR_LEGAL_HOLD_OVERLAP | 409 |
| ERR_DUPLICATE_TARGET_INVALID | 409 |
| ERR_CASE_HAS_CONDUCTED_INTERVIEWS | 409 |
| ERR_NO_CONDUCTED_INTERVIEW | 409 |
| ERR_UNSEALED_EVIDENCE | 409 |
| ERR_MONITORING_WINDOW_INACTIVE | 409 |
| ERR_EXTENSION_WINDOW_EXCEEDED | 409 |
