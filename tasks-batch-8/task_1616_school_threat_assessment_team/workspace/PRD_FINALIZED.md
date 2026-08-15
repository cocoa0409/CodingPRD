# School Threat Assessment API — Product Requirements Document

## 1. Introduction

A district behavioral threat assessment team carries a heavy mandate: every report of a potential school threat — whether it arrives through an anonymous tip line or a staff referral — must be intake-stamped, triaged, screened, assessed, and either closed or actively managed under a documented plan, with every decision defensible months or years later. This document specifies the API that serves as the team's system of record for that entire lifecycle: report intake and triage, the initial screening protocol, structured interviews, scored risk assessments with team-lead adjudication, management plans that drive a monitoring cadence, coordination of law-enforcement and mental-health referrals, re-entry planning after a subject is removed from campus, and finally closure, records retention, and district-level annual reporting.

Three design pressures shape every rule that follows. First, confidentiality: cases are pseudonymous, certain documents can be sealed from front-line staff, and the audit trail is restricted to senior roles. Second, segregation of duties: the assessor who drafts an assessment may not finalize it, and the assessor who proposes a re-entry plan may not approve it — the system enforces this rather than trusting convention. Third, time: monitoring check-ins can be missed and referral service-level agreements can lapse, so the server maintains a district-controlled logical clock whose advance applies the automatic transitions that real calendar time would trigger. Implementers should treat this document as the sole source of truth for behavior; where a rule is stated here, it is authoritative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `IntakeCoordinator` (tip-line and front-office intake staff who own report intake, triage, and reopening), `ThreatAssessor` (behavioral threat assessment team members who conduct screenings, interviews, and assessments, draft plans, coordinate referrals, and run monitoring), `TeamLead` (the team chair who finalizes assessments, activates plans, decides removals and closures, and adjudicates re-entry), and `DistrictAdministrator` (district operations staff who manage schools, the logical clock, retention purges, and district reporting). A request missing either header, or carrying a role outside these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where an action calls for attribution — as `created_by_user_id` on a `RiskAssessment`, `ManagementPlan`, or `ReEntryPlan`, as `author_user_id` on a `CaseDocument`, and as `actor_user_id` paired with `actor_role` on every `AuditEvent` — but it never compares the header value to any entity's `id`. Segregation-of-duties checks compare one operator's identifier string against another's (the finalizer's `X-User-ID` against the assessment's `created_by_user_id`, for example), never against a resource identifier.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, and paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — schools, threat cases, interviews, risk assessments, management plans, referrals, monitoring check-ins, and re-entry plans — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource, including mutations caused by cascades from related resources.

Two resources are deliberately narrower. A `CaseDocument` is an append-only log entry and an `AuditEvent` is an immutable, tamper-evident record; both carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on these two types, and the API exposes no update or delete operations for either.

### 2.5. The Logical Clock and Time-Driven Transitions

The server maintains a logical clock rather than reading wall-clock time. At startup, before any operator intervenes, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. Every timestamp the server stamps — `created_at`, `completed_at`, `finalized_at`, `activated_at`, `closed_at`, `sla_due_at`, `purged_at`, and the rest — is taken from this logical clock.

A `DistrictAdministrator` advances the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. The supplied instant must be at or after the current logical time; a backwards move is rejected with `ERR_INVALID_REQUEST`. Advancing the clock is never a pure read of the future: it applies every pending automatic transition whose trigger time has passed. Any monitoring check-in still `SCHEDULED` whose `due_date` falls before the new current calendar date becomes `MISSED`, with the cascades described in §3.5, and any referral still `SENT` whose `sla_due_at` the clock has passed is marked with `sla_breached` set to true, with the escalation cascade described in §3.6.

### 2.6. Optimistic Concurrency Control on Plan Activation

Exactly one operation in the API is guarded by optimistic concurrency control: activating a management plan via `POST /management-plans/{id}/activate`. The request body for that operation must carry `expected_threat_case_version`, holding the `version` of the parent threat case as the client last observed it. If the supplied value does not match the case's current `version` — because another writer has advanced the case since the client last read it, most notably by finalizing an assessment or activating a plan, each of which increments the case's `version` — the activation is rejected with `ERR_STALE_CASE_VERSION` and HTTP status 412. This stale-version check runs before any state or business rule on that operation. No other endpoint accepts a version field; all other mutations proceed without an optimistic-locking check.

### 2.7. Validation Order and Resource Existence

When a request fails several rules at once, the error it receives is deterministic because validation proceeds in a fixed order. First, the presence and validity of the two authentication headers is checked (§2.1). Second, the role's permission for the specific endpoint is checked. Third, the request body's schema is validated — required fields present, types correct, enum values among their declared sets, and non-empty constraints on required strings and arrays such as `conditions`, `decline_reason`, `denial_reason`, and `summary`; any failure here is `ERR_INVALID_REQUEST`. Fourth, path identifiers are resolved left to right, and the first identifier that does not correspond to an existing resource produces a 404: `ERR_CASE_NOT_FOUND` when the missing resource is a threat case (whether referenced in the path or through a body `case_id`), `ERR_SCHOOL_NOT_FOUND` when a body `school_id` references a school that does not exist, `ERR_CONDITION_NOT_FOUND` when a `conditionIndex` path segment falls outside the referenced plan's `conditions` array, and `ERR_NOT_FOUND` for any other missing path resource. Fifth, on the OCC-guarded activation call only, the stale-version check of §2.6 runs. Sixth, entities referenced inside the body (the school on case creation, the case on child-resource creation) must exist. Only then are state preconditions evaluated — the resource being acted upon and the case referenced in the body must each be in a state that permits the operation — and only after those come the business-safety rules (segregation of duties, interview gating, referral prerequisites, closure blockers, re-entry condition completeness), then uniqueness and quota constraints, then cadence-length limits, and finally temporal rules such as interval overlap and past-dated deadlines.

### 2.8. Pseudonymity, Sealed Records, and the Case-Scoped Audit Trail

Cases never carry a real student name. The subject is referenced only through a `subject_alias` such as STU-4821, and even that alias is overwritten with the literal string `PURGED` when records retention finally scrubs the case. Case documents may be marked `sealed`; sealed documents are withheld from list responses for `IntakeCoordinator` and `ThreatAssessor` callers and are visible only to `TeamLead` and `DistrictAdministrator` callers.

Every mutation on a case — whether driven by an operator or by the clock — appends an `AuditEvent` scoped to that case, recording `actor_user_id` and `actor_role` (each the literal string `system` for automatic transitions), an `action`, and a human-readable `detail`. The complete set of actions is: `CASE_CREATED`, `CASE_TRIAGED`, `CASE_SCREENED`, `CASE_REMOVED`, `CASE_CLOSED`, `CASE_REOPENED`, `CASE_PURGED`, `ASSESSMENT_FINALIZED`, `PLAN_ACTIVATED`, `PLAN_SUPERSEDED`, `REFERRAL_SENT`, `REFERRAL_AUTO_CREATED`, `REFERRAL_ACKNOWLEDGED`, `REFERRAL_DECLINED`, `REFERRAL_WITHDRAWN`, `REFERRAL_SLA_BREACHED`, `CHECKIN_COMPLETED`, `CHECKIN_MISSED`, `CHECKIN_RESCHEDULED`, `ESCALATION_RAISED`, `REENTRY_PROPOSED`, `REENTRY_APPROVED`, `REENTRY_DENIED`, and `REENTRY_COMPLETED`. The audit trail is confidential: only `TeamLead` and `DistrictAdministrator` may read it, and the audit list accepts an optional `action` filter.

### 2.9. Numeric Precision, Scores, and Calendar Arithmetic

Screening and assessment scores are whole-number integers; no fractional scores exist anywhere in the system. Where the assessment algorithm multiplies by one and a half, the product is rounded half-up to a whole number before any subsequent step. Rates reported in the district annual report are rounded half-up to exactly two decimal places. Service-level deadlines are datetimes computed to the second, while monitoring schedules and retention windows are pure calendar dates in `YYYY-MM-DD` form with no time-of-day component; a check-in due on a given date remains completable through the end of that day.

## 3. Business Logic & Workflows

### 3.1. School Configuration, Intake, and Triage

Before any case work begins, a `DistrictAdministrator` registers each school with its display `name`, a `school_code`, the current `enrollment_count` headcount (which may be zero but never negative), and optionally a `retention_days` window governing how long a closed case's documents survive before purge eligibility. When `retention_days` is omitted it defaults to 365; a supplied value shorter than 30 days is invalid. The `school_code` is unique across the district and case-sensitive: a second school carrying a code byte-identical to an existing one is rejected with `ERR_DUPLICATE_SCHOOL_CODE`.

Case work begins when an `IntakeCoordinator` files a report. The intake call names the enrolling school via `school_id` — an unknown school yields `ERR_SCHOOL_NOT_FOUND` — along with the pseudonymous `subject_alias`, the `reporter_channel` (`TIP_LINE` or `STAFF_REFERRAL`), and a free-text `summary` of the reported concern. The new case opens in `INTAKE` status, and the system writes a `CASE_CREATED` audit event. The case list supports filtering by `school_id`, by `status`, and by `risk_level`, alongside the standard pagination parameters.

Triage is the coordinator's second decision. It is valid only while the case is in `INTAKE`; any other state draws `ERR_CASE_NOT_IN_INTAKE`. The coordinator supplies a `triage_priority` of `ROUTINE`, `URGENT`, or `EMERGENT` — any other value is `ERR_INVALID_REQUEST` — together with free-text `triage_notes`. A successful triage moves the case from `INTAKE` to `TRIAGED`, stamps the chosen priority onto `triage_priority` (which is null before triage), and writes `CASE_TRIAGED`. An `EMERGENT` triage additionally fires an automatic cascade: the system creates a law-enforcement referral to the agency named `DISTRICT_SRT` at `URGENT` urgency, already in `SENT` status with `auto_created` set to true and its deadline computed at creation, and records `REFERRAL_AUTO_CREATED` in the audit trail.

### 3.2. The Initial Screening

Once a case is `TRIAGED`, a `ThreatAssessor` records the structured initial screening; attempting it in any other case state is rejected with `ERR_CASE_NOT_TRIAGED`. The screening instrument is six boolean factors supplied in the request: `threat_of_violence`, `weapon_mention`, `target_identified`, `plan_described`, `prior_incidents`, and `current_distress`. Any factor whose key is absent counts as false. The case's `screening_score` is the count of factors that are true, an integer from zero to six, and the `screening_outcome` is `SUBSTANTIVE` when the score is at least three and `NON_SUBSTANTIVE` otherwise; both fields are null until a screening is recorded.

The outcome routes the case. A `SUBSTANTIVE` screening moves the case from `TRIAGED` to `UNDER_ASSESSMENT`, opening the full assessment workflow. A `NON_SUBSTANTIVE` screening moves the case from `TRIAGED` to `CLOSED_NO_THREAT`, stamps `closed_at` with the current logical time, and computes `retention_purge_after` as the closure calendar date plus the school's `retention_days`. Either branch writes `CASE_SCREENED` to the audit trail.

### 3.3. The Interview Protocol

While a case is `UNDER_ASSESSMENT`, a `ThreatAssessor` schedules interviews against it; a case in any other state rejects scheduling with `ERR_CASE_NOT_UNDER_ASSESSMENT`. Each interview names its case via `case_id` (an unknown case yields `ERR_CASE_NOT_FOUND`), an `interviewee_type` of `SUBJECT`, `WITNESS`, `PARENT`, or `REPORTER`, and a time window from `starts_at` to `ends_at`, both ISO 8601 UTC instants. The window must be non-degenerate: `ends_at` strictly later than `starts_at`, otherwise `ERR_INVALID_TIME_RANGE`. Interviews for the same case may not overlap — the system treats each window as a half-open interval, so one interview ending at exactly the moment another begins is permitted, while any true intersection with an existing `SCHEDULED` interview for that case is rejected with `ERR_INTERVIEW_OVERLAP`. Two further gates apply at scheduling time. A case may carry at most eight interviews that are not `CANCELLED`; scheduling a ninth is rejected with `ERR_MAX_INTERVIEWS_EXCEEDED`. And a `SUBJECT` interview may not be scheduled until at least one non-`SUBJECT` interview for the same case has reached `COMPLETED`; violating this sequencing is rejected with `ERR_SUBJECT_INTERVIEW_TOO_EARLY`. A successfully scheduled interview begins in `SCHEDULED` status.

Completing an interview — again `ThreatAssessor` work — requires it to still be `SCHEDULED` (`ERR_INTERVIEW_NOT_SCHEDULED` otherwise) and records the assessor's `findings_score`, an integer rating from 0 to 10 inclusive, together with a non-empty `summary`; an out-of-range score or empty summary is `ERR_INVALID_REQUEST`. Completion stamps `completed_at` from the logical clock. A scheduled interview may instead be cancelled, which moves it to `CANCELLED` and frees both the time window and the case's interview quota, since cancelled interviews count toward neither the overlap set nor the eight-interview cap.

### 3.4. Risk Assessment: Drafting, Scoring, and Adjudication

A `ThreatAssessor` drafts a risk assessment for a case that is `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (any other state is `ERR_CASE_NOT_ASSESSABLE`), provided the case does not already have an open assessment — one in `DRAFT` or `SUBMITTED` — in which case the create is rejected with `ERR_OPEN_ASSESSMENT_EXISTS`. The draft names its case via `case_id`, selects a scoring `variant` of `STANDARD` or `EXPEDITED`, and submits a `factors` array whose entries each carry a `factor_code` and an integer `severity` from 0 to 3. The recognized factor codes are `WEAPON_ACCESS`, `PLAN_SPECIFICITY`, `GRIEVANCE_HISTORY`, `PEER_REPORTS`, `BEHAVIORAL_ESCALATION`, and `SUPERVISION_GAP`; codes absent from the array contribute zero. The server records the creator's header identity in `created_by_user_id`, computes `raw_score` and `risk_level` immediately, and leaves the assessment in `DRAFT`.

Scoring works as follows. Each factor code carries a fixed weight: `WEAPON_ACCESS` weighs 20 points, `PLAN_SPECIFICITY` 15, `GRIEVANCE_HISTORY` 10, `BEHAVIORAL_ESCALATION` 10, `SUPERVISION_GAP` 8, and `PEER_REPORTS` 5. Under the `STANDARD` variant, the base score is the sum, over the submitted factors, of each factor's weight multiplied by its severity; if any submitted factor has severity 3, a critical bonus of 10 points is added. Under the `EXPEDITED` variant, only `WEAPON_ACCESS` and `PLAN_SPECIFICITY` contribute: their weighted sum is multiplied by one and a half, the product is rounded half-up to a whole number, and then — if any submitted factor, counted or not, has severity 3 — a critical bonus of 15 points is added. In both variants the resulting base is clamped into the range from 0 to 100 inclusive to produce `raw_score`. The `risk_level` band is then read off the score: `LOW` below 20, `MODERATE` from 20 up to but not including 40, `HIGH` from 40 up to but not including 60, and `IMMINENT` at 60 or above.

While the assessment remains `DRAFT`, the assessor may replace its `variant`, its `factors`, or both; the server recomputes the scores on every such update, and an update attempted on a non-`DRAFT` assessment is `ERR_ASSESSMENT_NOT_DRAFT`. Submitting moves the assessment from `DRAFT` to `SUBMITTED` for team-lead review. A `TeamLead` then has two adjudication paths, each requiring `SUBMITTED` status (`ERR_ASSESSMENT_NOT_SUBMITTED` otherwise). Returning the assessment moves it from `SUBMITTED` back to `DRAFT` and records the supplied `return_reason` in the audit event's `detail`. Finalizing moves it from `SUBMITTED` to `FINALIZED`, but segregation of duties applies: if the finalizer's `X-User-ID` equals the assessment's `created_by_user_id`, the call is rejected with `ERR_SOD_SELF_APPROVAL`.

Finalization is the pivot on which the whole case turns. It stamps `finalized_at`, copies the assessment's `risk_level` onto the case (where `risk_level` was null until the first finalization), increments the case's `version` by one, and writes `ASSESSMENT_FINALIZED`. Any other assessment for the same case that was `FINALIZED` is moved to `SUPERSEDED` with `superseded_at` stamped. And when the finalized level is `IMMINENT`, a cascade fires: unless a law-enforcement referral for the case already exists in `SENT` or `ACKNOWLEDGED` status, the system auto-creates one at `URGENT` urgency addressed to the agency `DISTRICT_SRT` with `auto_created` true, writing `REFERRAL_AUTO_CREATED`; that auto-referral then sets the case's `escalation_flag` to true and writes `ESCALATION_RAISED`; and the escalation, in turn, sets `needs_review` to true on the case's `ACTIVE` management plan if one exists.

### 3.5. Management Plans and the Monitoring Cadence

With a `FINALIZED` assessment on file, a `ThreatAssessor` drafts a management plan. Drafting requires the case to be `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE` otherwise) and requires that some assessment for the case has actually been finalized (`ERR_NO_FINALIZED_ASSESSMENT` otherwise). The draft carries `case_id`, a `cadence_mode` of `FROM_COMPLETION` or `FIXED_ANCHOR`, a non-empty `conditions` array of management-condition description strings, and optionally `cadence_days`. When `cadence_days` is omitted it defaults by the case's current risk level: 3 days for `IMMINENT`, 7 for `HIGH`, 14 for `MODERATE`, and 30 for `LOW`. A supplied `cadence_days` may not exceed the maximum for that level — 7 days for `IMMINENT`, 14 for `HIGH`, 30 for `MODERATE`, and 60 for `LOW` — and an over-long cadence is rejected with `ERR_CADENCE_TOO_LONG` (HTTP 422). New plans are born `DRAFT` with `created_by_user_id` recorded and `needs_review` false.

Activation is a `TeamLead` decision and is the OCC-guarded operation of §2.6: the request must carry `expected_threat_case_version`, and a value that does not match the case's current `version` is rejected with `ERR_STALE_CASE_VERSION` before any state or business rule is consulted. After the stale-version check, the gates evaluate in order: the plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); the case must be `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE`); when the case's `risk_level` is `HIGH` or `IMMINENT`, a law-enforcement referral in `ACKNOWLEDGED` status must exist for the case (`ERR_LE_REFERRAL_REQUIRED`); and a `FINALIZED` assessment must exist for the case (`ERR_NO_FINALIZED_ASSESSMENT`). A successful activation stamps `activated_at`, increments the case's `version` by one, and writes `PLAN_ACTIVATED`. The case's prior `ACTIVE` plan, if any, becomes `SUPERSEDED` with a `PLAN_SUPERSEDED` audit event; a plan that was flagged `needs_review` sheds that flag when a newer plan activates. The case itself moves to `PLAN_ACTIVE`, its `monitoring_cadence_days` is copied from the activated plan's `cadence_days` (the field is null until the first activation), and its `escalation_flag` is cleared to false — plan activation is, along with reopening, the only way that flag comes down. Finally, the first monitoring check-in is auto-created with `auto_created` true, due the current calendar date plus the plan's cadence in days, unless a check-in in `SCHEDULED` or `MISSED` status already exists for that case on that calendar day.

Check-ins may also be scheduled by hand. A `ThreatAssessor` creates one against a `PLAN_ACTIVE` case (`ERR_CASE_NOT_PLAN_ACTIVE` otherwise) by supplying `case_id` and a `due_date` calendar date. A `due_date` earlier than the current logical date is rejected with `ERR_INVALID_DUE_DATE`, and because at most one check-in in `SCHEDULED` or `MISSED` status may exist per case per calendar day, a clashing date draws `ERR_CHECKIN_DAY_CONFLICT`.

Completing a check-in requires it to be `SCHEDULED` (`ERR_CHECKIN_NOT_SCHEDULED`) and takes an `outcome` of `ON_TRACK` or `CONCERNS_ESCALATED` — anything else is `ERR_INVALID_REQUEST` — plus free-text `notes`. Completion stamps `completed_at`, resets the case's `consecutive_missed_count` to zero, and writes `CHECKIN_COMPLETED`. It also chains the next check-in per the `ACTIVE` plan's cadence mode. Under `FROM_COMPLETION`, the next `due_date` is the completion calendar date plus the cadence in days, so a late completion pushes the schedule out by the full cadence from the actual completion date. Under `FIXED_ANCHOR`, due dates stay on the grid anchored at the plan's activation date: the next due date is the earliest grid date — the activation date plus a whole number of cadence intervals — that falls strictly after the completion date, so a late completion does not shift the grid. In either mode the successor is created with `auto_created` true unless a `SCHEDULED` or `MISSED` check-in already exists for the case on that calendar day; `COMPLETED` and `CANCELLED` check-ins do not block creation. An outcome of `CONCERNS_ESCALATED` additionally sets the case's `escalation_flag` to true and writes `ESCALATION_RAISED`.

Check-ins that lapse are caught by the clock advance of §2.5: when the current calendar date moves past a `SCHEDULED` check-in's `due_date`, the check-in becomes `MISSED`, the case's `consecutive_missed_count` increases by one, and `CHECKIN_MISSED` is written; the moment that count reaches two, the case's `escalation_flag` is set and `ESCALATION_RAISED` is written. A missed check-in is not dead weight: a `ThreatAssessor` may reschedule one that is `MISSED` (`ERR_CHECKIN_NOT_MISSED` otherwise) by supplying a `new_due_date` no earlier than the current logical date (`ERR_INVALID_DUE_DATE`) that does not collide with another `SCHEDULED` or `MISSED` check-in for the case on that day (`ERR_CHECKIN_DAY_CONFLICT`). Rescheduling returns the check-in to `SCHEDULED` with its `due_date` updated and writes `CHECKIN_RESCHEDULED`, but it deliberately does not reset `consecutive_missed_count` — the miss history is preserved. The only route to `CANCELLED` is the case-closure cascade of §3.7.

### 3.6. External Referrals and Response SLAs

Referrals formalize the handoff to outside agencies. A `ThreatAssessor` or `TeamLead` creates one by naming `case_id`, a `referral_type` of `LAW_ENFORCEMENT` or `MENTAL_HEALTH`, the receiving `agency_name`, and an `urgency` of `ROUTINE` or `URGENT`. The case must still be open — referral creation is permitted while the case is `TRIAGED`, `UNDER_ASSESSMENT`, `PLAN_ACTIVE`, or `REMOVED`, and anything else is rejected with `ERR_CASE_NOT_OPEN`. Creation is the send: the referral is born in `SENT` status, `auto_created` false, and the system writes `REFERRAL_SENT`. Its response deadline `sla_due_at` is computed at the send instant — 72 hours later for an `URGENT` referral, 240 hours later for a `ROUTINE` one.

From `SENT`, three dispositions exist, each requiring the referral to still be `SENT` (`ERR_REFERRAL_NOT_SENT` otherwise) and each open to either a `ThreatAssessor` or a `TeamLead`. Acknowledgement moves the referral to `ACKNOWLEDGED` and writes `REFERRAL_ACKNOWLEDGED`. Declining requires a non-empty `decline_reason` (`ERR_INVALID_REQUEST` if empty), moves the referral to `DECLINED`, and writes `REFERRAL_DECLINED`. Withdrawing moves it to `WITHDRAWN` and writes `REFERRAL_WITHDRAWN`; withdrawal is the compensating action for the send, returning the count of the case's `SENT` referrals to its pre-send value.

If the receiving agency goes quiet, the clock decides. When a clock advance carries the current time past a referral's `sla_due_at` while the referral is still `SENT`, the server sets `sla_breached` to true, sets the case's `escalation_flag` to true, and writes `REFERRAL_SLA_BREACHED` — a lapsed agency response is an unresolved obligation that will, among other things, block case closure.

### 3.7. Removal, Re-Entry, Closure, and Reopening

When the subject must be taken off campus, a `TeamLead` removes them. The case must be `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (`ERR_CASE_NOT_REMOVABLE` otherwise), and the call supplies a `removal_type` of `EMERGENCY_REMOVAL` or `DISCIPLINARY_EXCLUSION` (any other value is `ERR_INVALID_REQUEST`) along with a free-text `removal_reason`. Removal moves the case to `REMOVED`, stamps `removal_type` (null until this point), and writes `CASE_REMOVED`. Removal is deliberately not an unwind: open check-ins and referrals are not cancelled, monitoring continues during removal, and an `ACTIVE` management plan remains `ACTIVE`.

Re-entry is the managed path back. A `ThreatAssessor` proposes a re-entry plan for a `REMOVED` case (`ERR_CASE_NOT_REMOVED` otherwise), provided no other re-entry plan for the case is still open in `PROPOSED` or `APPROVED` (`ERR_OPEN_REENTRY_PLAN_EXISTS`). The proposal carries `case_id` and a non-empty `conditions` array; the server stores each condition as an object with its `description`, a `status` initially `UNMET`, and an `evidence_note` initially null. The plan is born `PROPOSED` with `created_by_user_id` recorded and `REENTRY_PROPOSED` audited. While the plan is `PROPOSED` or `APPROVED`, a `ThreatAssessor` may verify individual conditions by zero-based `conditionIndex`, attaching an `evidence_note`; the referenced condition's `status` becomes `MET`, and an index outside the array is `ERR_CONDITION_NOT_FOUND`. A `TeamLead` then adjudicates: approval requires the plan to be `PROPOSED` (`ERR_REENTRY_NOT_PROPOSED`), requires the case to be `REMOVED` (`ERR_CASE_NOT_REMOVED`), and enforces segregation of duties — an approver whose `X-User-ID` equals the plan's `created_by_user_id` is rejected with `ERR_SOD_SELF_APPROVAL` — before moving the plan to `APPROVED` and writing `REENTRY_APPROVED`. Denial likewise requires `PROPOSED` and takes a non-empty `denial_reason` (`ERR_INVALID_REQUEST` otherwise), moving the plan to `DENIED` with `REENTRY_DENIED`.

Completing re-entry is the final gate. It requires the plan to be `APPROVED` (`ERR_REENTRY_NOT_APPROVED`), the case to be `REMOVED` (`ERR_CASE_NOT_REMOVED`), and every condition's `status` to be `MET` — a single `UNMET` condition blocks completion with `ERR_REENTRY_CONDITIONS_UNMET`. On success the plan becomes `REENTERED`, `REENTRY_COMPLETED` is audited, and the case reopens: its `removal_type` is cleared to null, `CASE_REOPENED` is written, and it returns to `PLAN_ACTIVE` when an `ACTIVE` management plan exists for it, otherwise to `UNDER_ASSESSMENT`. When the return is to `PLAN_ACTIVE`, a re-entry monitoring check-in is auto-created with `auto_created` true, due the current calendar date plus 30 days.

Closure is the managed end-state for a case that is `PLAN_ACTIVE` (`ERR_CASE_NOT_CLOSABLE` from anywhere else). Three blockers guard it, evaluated in this order: a check-in in `MISSED` status rejects the close with `ERR_OPEN_CHECKINS_EXIST`; a referral still in `SENT` status rejects it with `ERR_OPEN_REFERRALS_EXIST`; and a case whose `escalation_flag` is set rejects it with `ERR_ESCALATION_UNRESOLVED`. A clean close moves the case to `CLOSED_MANAGED`, stamps `closed_at` from the logical clock, computes `retention_purge_after` as the closure calendar date plus the school's `retention_days`, cascades every `ACTIVE` and every `DRAFT` management plan for the case to `CLOSED`, cancels every `SCHEDULED` check-in for the case (the only producer of `CANCELLED` check-ins), and writes `CASE_CLOSED`.

A closed case is not necessarily finished. When a new report arrives concerning a previously closed subject, an `IntakeCoordinator` reopens the case: from either `CLOSED_NO_THREAT` or `CLOSED_MANAGED` (`ERR_CASE_NOT_REOPENABLE` otherwise) the case returns to `TRIAGED`, `closed_at` and `retention_purge_after` are cleared to null, `consecutive_missed_count` resets to zero, `escalation_flag` resets to false, the prior `triage_priority` is preserved, and `CASE_REOPENED` is written.

### 3.8. Case Documentation, Records Retention, and Annual Reporting

Documentation accumulates throughout the case's life. An `IntakeCoordinator`, `ThreatAssessor`, or `TeamLead` may append a document to any case that has not been purged — writing to a `PURGED` case is rejected with `ERR_CASE_PURGED` — supplying a `doc_type` of `INTAKE_NOTE`, `INTERVIEW_SUMMARY`, `PLAN_DOCUMENT`, `LEGAL_HOLD`, or `OTHER`, the document `body`, and optionally `sealed` (defaulting to false). The server records the caller in `author_user_id`. Document lists accept a `doc_type` filter and apply the sealed-visibility rule of §2.8: `sealed` documents are excluded from responses for `IntakeCoordinator` and `ThreatAssessor` and included for `TeamLead` and `DistrictAdministrator`. Sub-resource lists for interviews, risk assessments, management plans, and monitoring check-ins each accept a `status` filter, and the referral list accepts `referral_type` and `status` filters.

Retention is terminal. A `DistrictAdministrator` invokes the district-wide purge, which selects every case in `CLOSED_NO_THREAT` or `CLOSED_MANAGED` whose `purged_at` is still null and whose `retention_purge_after` falls on or before the current logical date — a case whose retention date equals the current date is purged. Each selected case moves to `PURGED` (the case's only terminal state), its `purged_at` is stamped, its `subject_alias` is overwritten with the literal string `PURGED`, every one of its case documents has its `body` scrubbed to null and its `purged` flag set to true, and `CASE_PURGED` is audited. The purge responds with `purged_count` and the list `purged_case_ids`.

Finally, a `TeamLead` or `DistrictAdministrator` may pull the district annual report for a school year named in the `school_year` query parameter in `YYYY-YYYY` form. The reporting window runs from August 1 of the first named year at midnight UTC up to but not including August 1 of the following year. Every threat case whose `created_at` falls inside that half-open window counts, regardless of status — including `PURGED` cases. For each school with at least one such case, the report computes the school's total case count, the count of those cases whose `screening_outcome` is `SUBSTANTIVE`, and a school substantiation rate equal to one hundred times the substantiated count divided by the total count, rounded half-up to two decimal places. The district substantiation rate is then the arithmetic mean of the included schools' already-rounded rates, itself rounded half-up to two decimal places. This rounding order is pinned: per-school rates are rounded first and only then averaged — aggregating raw counts before rounding is not equivalent and is not what the report produces. Schools with no cases in the window are excluded both from the per-school listing and from the mean. The response carries `school_year`, the district-wide raw sums `total_cases` and `substantiated_cases` (counts, not rates), the `per_school` array, and `district_substantiation_rate`.

## 4. Endpoint Definitions

Operations that create a new resource — a school, a threat case, a case document, an interview, a risk assessment, a management plan, a referral, a monitoring check-in, or a re-entry plan — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/schools` | Create a school | DistrictAdministrator |
| GET | `/schools/{id}` | Get a school | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| POST | `/_clock/set_current_utc` | Advance the logical clock and apply time-driven transitions | DistrictAdministrator |
| POST | `/records-retention/purge` | Purge all retention-eligible closed cases | DistrictAdministrator |
| GET | `/annual-reports/district` | Computed district-level annual report for a school year | TeamLead, DistrictAdministrator |
| POST | `/threat-cases` | Intake a threat case from a tip line or staff referral | IntakeCoordinator |
| GET | `/threat-cases` | List threat cases with filters and pagination | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}` | Get a threat case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| POST | `/threat-cases/{id}/triage` | Triage an `INTAKE` case | IntakeCoordinator |
| POST | `/threat-cases/{id}/screening` | Record the initial screening for a `TRIAGED` case | ThreatAssessor |
| POST | `/threat-cases/{id}/remove` | Remove the subject from campus | TeamLead |
| POST | `/threat-cases/{id}/close` | Close a `PLAN_ACTIVE` case as managed | TeamLead |
| POST | `/threat-cases/{id}/reopen` | Reopen a closed case on a new report | IntakeCoordinator |
| GET | `/threat-cases/{id}/interviews` | List interviews for a case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}/risk-assessments` | List risk assessments for a case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}/management-plans` | List management plans for a case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}/referrals` | List referrals for a case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}/monitoring-check-ins` | List monitoring check-ins for a case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}/re-entry-plans` | List re-entry plans for a case | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| GET | `/threat-cases/{id}/documents` | List case documents (sealed documents visible only to TeamLead and DistrictAdministrator) | IntakeCoordinator, ThreatAssessor, TeamLead, DistrictAdministrator |
| POST | `/threat-cases/{id}/documents` | Append a case document (append-only; not allowed on a purged case) | IntakeCoordinator, ThreatAssessor, TeamLead |
| GET | `/threat-cases/{id}/audit-events` | List the case's confidential audit trail | TeamLead, DistrictAdministrator |
| POST | `/interviews` | Schedule an interview for a case | ThreatAssessor |
| POST | `/interviews/{id}/complete` | Complete a scheduled interview with findings | ThreatAssessor |
| POST | `/interviews/{id}/cancel` | Cancel a scheduled interview | ThreatAssessor |
| POST | `/risk-assessments` | Create a draft risk assessment (scores computed immediately) | ThreatAssessor |
| PUT | `/risk-assessments/{id}` | Replace the variant and/or factors of a draft assessment; scores recomputed | ThreatAssessor |
| POST | `/risk-assessments/{id}/submit` | Submit a draft assessment for team-lead review | ThreatAssessor |
| POST | `/risk-assessments/{id}/return` | Return a submitted assessment to draft for revision | TeamLead |
| POST | `/risk-assessments/{id}/finalize` | Finalize a submitted assessment; sets case risk level and fires the imminent cascade | TeamLead |
| POST | `/management-plans` | Draft a management plan for a case with a finalized assessment | ThreatAssessor |
| POST | `/management-plans/{id}/activate` | Activate a draft plan (OCC-guarded; supersedes the prior active plan) | TeamLead |
| POST | `/referrals` | Create and send a law-enforcement or mental-health referral | ThreatAssessor, TeamLead |
| POST | `/referrals/{id}/acknowledge` | Mark a sent referral acknowledged by the receiving agency | ThreatAssessor, TeamLead |
| POST | `/referrals/{id}/decline` | Mark a sent referral declined | ThreatAssessor, TeamLead |
| POST | `/referrals/{id}/withdraw` | Withdraw a sent referral | ThreatAssessor, TeamLead |
| POST | `/monitoring-check-ins` | Manually schedule a check-in for a `PLAN_ACTIVE` case | ThreatAssessor |
| POST | `/monitoring-check-ins/{id}/complete` | Complete a scheduled check-in; chains the next per the active plan's cadence | ThreatAssessor |
| POST | `/monitoring-check-ins/{id}/reschedule` | Reschedule a missed check-in to a new due date | ThreatAssessor |
| POST | `/re-entry-plans` | Propose re-entry conditions for a `REMOVED` case | ThreatAssessor |
| POST | `/re-entry-plans/{id}/approve` | Approve a proposed re-entry plan (approver must differ from proposer) | TeamLead |
| POST | `/re-entry-plans/{id}/deny` | Deny a proposed re-entry plan | TeamLead |
| POST | `/re-entry-plans/{id}/conditions/{conditionIndex}/verify` | Mark one condition (zero-based index) met with evidence | ThreatAssessor |
| POST | `/re-entry-plans/{id}/complete-re-entry` | Complete re-entry; case returns to `PLAN_ACTIVE` or `UNDER_ASSESSMENT` | TeamLead |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_INVALID_DUE_DATE` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOOL_NOT_FOUND` | 404 Not Found |
| `ERR_CONDITION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_CASE_NOT_IN_INTAKE` | 409 Conflict |
| `ERR_CASE_NOT_TRIAGED` | 409 Conflict |
| `ERR_CASE_NOT_UNDER_ASSESSMENT` | 409 Conflict |
| `ERR_CASE_NOT_ASSESSABLE` | 409 Conflict |
| `ERR_CASE_NOT_PLANNABLE` | 409 Conflict |
| `ERR_CASE_NOT_PLAN_ACTIVE` | 409 Conflict |
| `ERR_CASE_NOT_REMOVABLE` | 409 Conflict |
| `ERR_CASE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CASE_NOT_REOPENABLE` | 409 Conflict |
| `ERR_CASE_NOT_REMOVED` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_CASE_PURGED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_REFERRAL_NOT_SENT` | 409 Conflict |
| `ERR_CHECKIN_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CHECKIN_NOT_MISSED` | 409 Conflict |
| `ERR_INTERVIEW_NOT_SCHEDULED` | 409 Conflict |
| `ERR_REENTRY_NOT_PROPOSED` | 409 Conflict |
| `ERR_REENTRY_NOT_APPROVED` | 409 Conflict |
| `ERR_SOD_SELF_APPROVAL` | 403 Forbidden |
| `ERR_SUBJECT_INTERVIEW_TOO_EARLY` | 409 Conflict |
| `ERR_LE_REFERRAL_REQUIRED` | 409 Conflict |
| `ERR_OPEN_CHECKINS_EXIST` | 409 Conflict |
| `ERR_OPEN_REFERRALS_EXIST` | 409 Conflict |
| `ERR_ESCALATION_UNRESOLVED` | 409 Conflict |
| `ERR_REENTRY_CONDITIONS_UNMET` | 409 Conflict |
| `ERR_OPEN_ASSESSMENT_EXISTS` | 409 Conflict |
| `ERR_OPEN_REENTRY_PLAN_EXISTS` | 409 Conflict |
| `ERR_MAX_INTERVIEWS_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_SCHOOL_CODE` | 409 Conflict |
| `ERR_NO_FINALIZED_ASSESSMENT` | 409 Conflict |
| `ERR_CADENCE_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_INTERVIEW_OVERLAP` | 409 Conflict |
| `ERR_CHECKIN_DAY_CONFLICT` | 409 Conflict |
