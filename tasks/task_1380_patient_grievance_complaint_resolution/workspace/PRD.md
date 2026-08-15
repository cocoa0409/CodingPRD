# Patient Grievance Resolution API — Product Requirements Document

## 1. Introduction

Hospitals owe patients more than an apology when something goes wrong. Regulators impose hard clocks on how quickly a grievance must be acknowledged and answered in writing, accreditation bodies expect a traceable escalation path for care concerns, and patient-relations teams are expected to recover goodwill in real time without losing fiscal control. The Patient Grievance Resolution API is the system of record for that entire obligation chain — from the moment a concern arrives by phone, portal, or letter, through classification, investigation, the written response, satisfaction follow-up, and trend reporting to compliance.

The design centers on a single aggregate, the patient case, surrounded by a regulatory clock that runs as a parallel dimension to the case lifecycle, a segregation-of-duties model that keeps investigators, approvers, and adjudicators apart, and derived values that are always recomputed from current inputs rather than cached. This document specifies the global contracts every endpoint shares, the business workflows that drive each state machine, and the complete error catalogue. All business resources are mounted under `/api`; the sole exception is the operator's logical-clock control described in §2.4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Seven roles are declared: `SystemAdmin`, `IntakeCoordinator`, `PatientAdvocate`, `DepartmentInvestigator`, `QualityRiskOfficer`, `PatientRelationsDirector`, and `ComplianceAuditor`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Authorization is then checked against the endpoint's permitted role list; a caller whose role is not listed is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Four roles are entity-backed. When `X-User-Role` is `PatientAdvocate`, `DepartmentInvestigator`, `QualityRiskOfficer`, or `PatientRelationsDirector`, `X-User-ID` is the `id` of the acting `StaffMember`, and that staff member's `capabilities` must contain the mapped capability — `ADVOCATE` for `PatientAdvocate`, `INVESTIGATOR` for `DepartmentInvestigator`, `QRO` for `QualityRiskOfficer`, and `DIRECTOR` for `PatientRelationsDirector` — or authorization fails with `ERR_UNAUTHORIZED_ROLE`. Ownership checks on any resource that references a staff member compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `SystemAdmin`, `IntakeCoordinator`, or `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `decided_by_id` on a classification decision or `assigned_by_id` on an assignment) but never compares it to an entity's `id`.

Certain actions are identity-bound beyond role membership. Completing or cancelling a rounding session requires the caller to be that session's own advocate; booking or cancelling an interview room requires the caller to be the case's active primary investigator; issuing a service-recovery gesture requires an advocate-capable staff member acting as themselves. A caller who passes role authorization but fails the identity binding is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403).

Read operations are open to every declared role: all seven roles may call any list or detail read.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of returned items; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time Semantics

The platform runs on a logical clock rather than wall-clock time. At startup, before any operator intervention, the clock reads exactly 2026-08-01T00:00:00Z, and the server must never silently fall back to wall-clock time. A `SystemAdmin` may set the clock through a dedicated test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `now_iso8601`. Every deadline, breach derivation, tolling computation, and derived status in this document reads this logical clock; after the clock moves, derived values re-evaluate on the next read of the affected resource. All timestamps exchanged with the API are ISO 8601 in UTC with three fractional digits, and all deadline arithmetic operates at second precision.

### 2.5. Common Resource Properties

Most resources carry a standard system-managed quartet. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records the ISO 8601 UTC creation instant. The `updated_at` timestamp is refreshed on every mutation. The `version` is an integer that increments by one on every mutation of the resource and anchors optimistic concurrency control where §2.7 applies.

Three resources are deliberately lighter immutable records: a `ClassificationDecision`, an `InvestigationNote`, and a `HolidayObservance` carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on them.

### 2.6. Validation Precedence

When several violations are detectable on a single request, a fixed precedence ladder decides which rejection the caller sees; the first failing rung wins. The ladder runs as follows.

1. **User context.** Both headers are present and the role is declared, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The role is permitted on the endpoint and, for entity-backed roles, the referenced staff member holds the mapped capability, otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Existence.** Path identifiers resolve left to right, and body references such as `unit_id`, `room_id`, `investigation_id`, `escalation_id`, and `investigator_id` resolve to existing records, otherwise the corresponding 404 from §2.11.
4. **Stale version.** Where an operation requires `expected_case_version`, it is compared to the case's current `version` before any business rule is evaluated, otherwise `ERR_STALE_VERSION` (HTTP 412).
5. **Identity binding.** The resource-bound identity checks of §2.1, otherwise `ERR_IDENTITY_MISMATCH` (HTTP 403).
6. **Case lifecycle state.** The case's `lifecycle_status` permits the operation, otherwise `ERR_CASE_INVALID_STATE` (HTTP 409).
7. **Child entity state.** The targeted child (investigation, letter, assignment, recovery action, escalation, event, rounding session, booking, follow-up, suspension) is in the required state, otherwise the child's dedicated 409 state error.
8. **Safety gates, in order.** Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); then the letter content standard (`ERR_CONTENT_STANDARD_VIOLATION`); then the written-response requirement for grievances (`ERR_GRIEVANCE_REQUIRES_WRITTEN_RESPONSE` or `ERR_FAST_TRACK_COMPLAINT_ONLY`); then staff availability (`ERR_ADVOCATE_ON_LEAVE`); then the open-escalation approval gate (`ERR_OPEN_ESCALATION_BLOCKS_APPROVAL`).
9. **Cross-aggregate integrity.** References across aggregates must be consistent — `ERR_CROSS_REFERENCE_MISMATCH`, `ERR_UNIT_IN_RESTRICTED_POSTURE`, `ERR_EVENT_TRIGGER_NOT_SUPPORTED`, or `ERR_ROOM_INACTIVE` (all HTTP 409).
10. **Uniqueness and occupancy.** One investigation per case, one non-terminal letter per case, one open suspension per case, no duplicate active assignment for the same investigator on a case, rounding overlap and unit capacity, the booking buffer, snapshot-cell uniqueness, holiday-date uniqueness, acknowledgment idempotence, investigator pool and capacity, and evidence sufficiency — the constraint errors of §5, all HTTP 409.
11. **Temporal sanity.** Timestamps must describe plausible windows — `ERR_RECEIVED_AT_IN_FUTURE`, `ERR_ROUNDING_WINDOW_INVALID`, `ERR_BOOKING_WINDOW_INVALID` (HTTP 422).
12. **Fiscal ceiling.** The per-case recovery ceiling, `ERR_RECOVERY_CASE_CAP_EXCEEDED` (HTTP 402).
13. **Schema, evaluated last.** Required fields present, enum values inside their declared sets, integer ranges respected — `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`, or `ERR_FOLLOWUP_SCORE_INVALID` (HTTP 400, and 422 for the score). Domain-specific rejections above take precedence over generic shape errors whenever both were detectable without the malformed field; missing required fields, however, are reported at 400 before existence checks on the dependent references those fields would carry.

### 2.7. Optimistic Concurrency Control

Two write operations are optimistic-concurrency guarded: `POST /api/patient-cases/{id}/classification-decisions` and `POST /api/patient-cases/{id}/assignments`. Each such request must carry `expected_case_version`, the caller's last-observed `version` of the target case. If the case's current `version` differs — because another writer has advanced it since the caller last read the case — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because both operations are legitimately repeatable under product semantics: a second classification decision supersedes the current one, and a new primary assignment supersedes the previous one, so a stale `expected_case_version` is the only signal that the caller's view of the case's classification, dues, or staffing is out of date. No other endpoint accepts a version field; a version submitted anywhere else is not part of the contract.

### 2.8. Calendar and Business-Day Arithmetic

Two calendar dialects coexist. Calendar-day arithmetic adds a number of whole days — each exactly 86,400 seconds — directly to a base instant, ignoring weekends and holidays; it backs the binding regulatory deadlines. Business-day arithmetic counts days beginning the day after the base date, skipping Saturdays, Sundays, and every registered `HolidayObservance` `observance_date`, and lands at the same time of day as the base instant; it backs internal workplan targets and filing windows. An identical base instant therefore yields a business-day due that is strictly later than — or equal to — the calendar due whenever the window contains a non-business day. Because the holiday calendar is editable, removing a holiday causes every business-day-derived value to recompute on the next read; derived values are never cached.

### 2.9. Money, Durations, and Basis-Point Precision

All monetary values are integer cents: `value_cents` on a recovery action, a staff member's `recovery_issuance_limit_cents`, a case's `outstanding_recovery_cents`, and the per-case recovery ceiling of 50,000 cents (five hundred dollars). Durations, deadlines, and tolling credits use second precision with no rounding. Trend analytics are expressed in integer basis points — ten-thousandths of a whole — rounded half-up, under the pinned rounding order described in §3.9. Counts, scores, and the priority score are integers.

### 2.10. Segregation of Duties

Three steps are segregated so that no single staff member can carry both sides of a control. The letter approver must differ from the investigation's findings submitter (`submitted_by_id`). The escalation adjudicator must differ from the escalation's filer (`filed_by_id`), except that a system-filed escalation — one whose filer is recorded as 'system' — may be adjudicated by anyone otherwise authorized. The recovery approver must differ from the issuing advocate (`issued_by_id`). Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.11. Resource Resolution and Cross-Reference Integrity

The API surface is flat: every resource is top-level and addressable by its own `id`, with relationships expressed through payload references rather than deep nesting. Where a path does contain more than one identifier — a case followed by one of its children — identifiers are resolved left to right, and the request is rejected with the 404 corresponding to the first identifier that does not resolve. The not-found catalogue is: `ERR_CASE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_NOTE_NOT_FOUND`, `ERR_LETTER_NOT_FOUND`, `ERR_RECOVERY_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ROUNDING_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_FOLLOWUP_NOT_FOUND`, `ERR_SUSPENSION_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, and `ERR_HOLIDAY_NOT_FOUND`. A child reference that exists but belongs to a different case than the operation's path indicates — a suspension, follow-up, letter, or escalation wired to the wrong case — is a cross-reference violation rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Organizational Setup: Units, Staff, Interview Rooms, and the Holiday Calendar

Before any case can flow, a `SystemAdmin` shapes the organization. A **hospital unit** is registered with a display `name` and a `category` drawn from `INPATIENT`, `EMERGENCY`, `OUTPATIENT`, `SURGICAL`, `ICU`, or `OTHER`. Each unit also carries a `max_concurrent_roundings` capacity — two unless the administrator supplies a different value, and always at least one — and a `posture` that begins at `STANDARD`. Two counters are derived rather than stored: `open_case_count`, the number of cases sitting on the unit whose lifecycle has reached neither `CLOSED` nor `WITHDRAWN`, and `late_filed_event_count`, the number of reportable events on the unit's cases currently standing at `LATE_FILED`. A `PatientRelationsDirector` or `SystemAdmin` may later patch a unit's `posture` or `max_concurrent_roundings`; moving a unit from `RESTRICTED` back to `STANDARD` is refused with `ERR_UNIT_HAS_UNRESOLVED_LATE_EVENTS` while any late-filed event on that unit's cases remains unacknowledged, for reasons §3.7 makes concrete. The unit list accepts `posture` and `category` filters alongside pagination.

Staff registration records a `full_name` and a non-empty `capabilities` set drawn from `ADVOCATE`, `INVESTIGATOR`, `QRO`, and `DIRECTOR` — the four capabilities that gate the entity-backed roles of §2.1. Each staff member has an `on_leave` flag (initially false), a `max_concurrent_assignments` ceiling (five unless supplied otherwise, and always at least one), a derived `open_assignment_count` of that person's currently `ACTIVE` assignments, and a `recovery_issuance_limit_cents` self-approval ceiling that defaults to 10,000 cents. A `SystemAdmin` or `PatientRelationsDirector` may patch `on_leave`, `max_concurrent_assignments`, and `recovery_issuance_limit_cents`; the staff list filters by `on_leave`.

Interview rooms are registered with a `name` and `location`, and carry an `active` flag that starts true. A room whose `active` has been turned off rejects every new booking with `ERR_ROOM_INACTIVE`; existing bookings are untouched.

The holiday calendar drives business-day arithmetic (§2.8). Registering a `HolidayObservance` takes an `observance_date` in `YYYY-MM-DD` form and a `name`; a second observance on the same date is rejected with `ERR_DUPLICATE_HOLIDAY`. Removing a holiday — a 204 No Content operation — causes every business-day-derived deadline to recompute on the next read of any affected case, because business-day dues are derived, never cached.

### 3.2. Case Intake and Classification

An `IntakeCoordinator` opens a case by supplying an opaque `patient_ref` token (deliberately free of PHI), the `unit_id` of the unit where the concern originated, the `received_at` instant, the contact `channel` (`PHONE`, `EMAIL`, `PORTAL`, `IN_PERSON`, or `LETTER`), a free-text `description`, and a `grievance_category` of `BILLING`, `CARE_QUALITY`, `STAFF_CONDUCT`, `ACCESS_DELAY`, `RIGHTS_ABUSE`, `COMMUNICATION`, or `OTHER`. Three optional flags shape everything downstream: `alleged_abuse_flag` and `vulnerable_patient_flag` (both false unless supplied) and `severity_tier` (`STANDARD` unless the coordinator selects `URGENT` or `CRITICAL`). A `received_at` that lies ahead of the logical clock is rejected with `ERR_RECEIVED_AT_IN_FUTURE`. Intake on a unit whose posture is `RESTRICTED` is rejected with `ERR_UNIT_IN_RESTRICTED_POSTURE`. A successfully registered case is born with `lifecycle_status` `INTAKE` and `classification` `UNCLASSIFIED`, and the unit's `open_case_count` rises by one. The case list supports filtering by `unit_id`, `lifecycle_status`, `classification`, `grievance_category`, and `current_classification_decision_id`.

Classification is recorded as an append-only chain of decisions rather than an editable field. Each decision carries a `decision` of `COMPLAINT` or `GRIEVANCE`, a `rationale_code` of `INITIAL_INTAKE`, `PATIENT_REQUEST`, `ESCALATION_OF_CONCERN`, `REGULATORY_REVIEW`, or `DIRECTOR_OVERRIDE`, and an optional free-text `note`; the server stamps `decided_by_id` from the caller and links `supersedes_decision_id` to the case's previously current decision (null on the first). The case's `classification` always mirrors the newest decision, and `current_classification_decision_id` points at it — remaining null for as long as the case is `UNCLASSIFIED`. The very first decision moves the case `INTAKE` → `CLASSIFIED`; later decisions supersede in place. Two restrictions apply: decisions may not be recorded on a `CLOSED` or `WITHDRAWN` case, and a downgrade from `GRIEVANCE` to `COMPLAINT` is accepted only while the case is still in `INTAKE` or `CLASSIFIED` — both violations surface as `ERR_CASE_INVALID_STATE`. Because decisions supersede legitimately, the recording request is OCC-guarded: it must carry `expected_case_version` equal to the case's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) before any business rule runs. Every accepted decision advances the case `version` by one and recomputes the regulatory dues from `received_at`. The decision list filters by `case_id` and `supersedes_decision_id`.

Classification fixes the regulatory window. A `GRIEVANCE` must receive a written response within thirty calendar days of `received_at`; the window shrinks to seven calendar days when the case is `severity_tier` `CRITICAL` or carries `alleged_abuse_flag`. A `COMPLAINT` carries a three-day internal target through the same fields. While a case remains `UNCLASSIFIED`, all dues stay null. Grievances additionally owe the patient an acknowledgment: `ack_due_at` is exactly seven calendar days after `received_at`, always computed on the calendar variant, and stays null for complaints and unclassified cases. Each due is stored in two dialects — `response_due_calendar_at` on calendar arithmetic (the binding regulatory deadline) and `response_due_business_at` on business-day arithmetic (the internal workplan target) — and each binding value is its base plus the case's current `tolling_credit_seconds` (§3.5).

Whenever a `GRIEVANCE` decision is recorded, after the dues are computed, the system runs a systemic-issue sweep across the originating unit and category. It counts cases on the same unit with the same `grievance_category` that are classified `GRIEVANCE` (the newly classified case included), were received within the preceding thirty days, and are not `WITHDRAWN`. When that count reaches three — exactly three triggers the sweep's effect, two does not — and no `SYSTEMIC` escalation on any case of that unit and category currently stands in `FILED`, `IN_REVIEW`, or `REVIEWS_COMPLETE`, the system files a `SYSTEMIC` escalation on the newly classified case itself, with `source` `AUTO_SYSTEMIC_THRESHOLD`, `filed_by_id` recorded as 'system', and status `FILED` (§3.6).

Recording the grievance acknowledgment is an explicit act by an `IntakeCoordinator`. It is accepted only while the case is neither `CLOSED` nor `WITHDRAWN` (otherwise `ERR_CASE_INVALID_STATE`) and only once — a second attempt meets `ERR_ALREADY_ACKNOWLEDGED`. Recording stamps `acknowledged_at` with the current clock and advances the case `version` by one; when the response deadline has not yet been breached, this clears an `ACK_BREACH` reading back to `ON_TRACK` (§3.5).

Every case also carries a derived `priority_score` between zero and one hundred that drives the order in which the assignment selector's candidates are reviewed. The score starts from a severity base — twenty points for `STANDARD`, thirty-five for `URGENT`, fifty for `CRITICAL` — and adds fifteen points when `vulnerable_patient_flag` is true. An urgency component measures time pressure: the system takes the whole number of days remaining until `response_due_calendar_at`, discarding any partial day and treating an unset due as 999 days, subtracts that figure from ten, multiplies the difference by four, and clamps the result so it never falls below zero and never exceeds forty. Finally, a reopen bonus of ten points per reopen — the current `reopen_count` — is added, and the total is capped at one hundred.

### 3.3. Assignment and Investigation

Staffing a case is the `PatientRelationsDirector`'s call. An assignment request may name an `investigator_id` or omit it, may set an `assignment_role` of `PRIMARY` or `SUPPORTING` (`PRIMARY` unless supplied), and must carry `expected_case_version` under the same OCC contract as classification — a stale version is rejected with `ERR_STALE_VERSION` before anything else is evaluated. The case must be in `CLASSIFIED` (`ERR_CASE_INVALID_STATE` otherwise). A named investigator must hold the `INVESTIGATOR` capability, must not be on leave (`ERR_ADVOCATE_ON_LEAVE`), and must have `open_assignment_count` below their `max_concurrent_assignments` (`ERR_INVESTIGATOR_AT_CAPACITY`); naming an investigator who already holds an `ACTIVE` assignment on the same case is rejected with `ERR_DUPLICATE_ACTIVE_ASSIGNMENT`.

When no investigator is named, the auto-assignment selector runs. Eligibility requires the `INVESTIGATOR` capability, `on_leave` false, and assignment headroom; the eligible pool is ranked by `open_assignment_count` ascending, ties break by staff `created_at` ascending — earliest registered first, and the staff `id` is never used as a tiebreaker. An empty pool rejects the request with `ERR_NO_ELIGIBLE_INVESTIGATOR` and the case remains `CLASSIFIED`. A successful creation produces an `ACTIVE` assignment, raises the investigator's `open_assignment_count` by one, stamps `assigned_by_id` with the director's identifier or 'system' when the selector chose, and moves the case `CLASSIFIED` → `ASSIGNED` on the first assignment, advancing the case `version` by one. Supersede semantics govern primacy: when a new `PRIMARY` assignment arrives while an `ACTIVE` `PRIMARY` already exists on the case, the prior assignment is released — status `RELEASED`, `released_at` stamped with the current clock — and the previous investigator's `open_assignment_count` falls by one. The director may also release any `ACTIVE` assignment explicitly (optionally noting a `release_reason`); releasing anything not `ACTIVE` is rejected with `ERR_ASSIGNMENT_INVALID_STATE`, and a release stamps `released_at` and decrements the investigator's count. Assignments reach `COMPLETED` only through case closure (§3.4). The assignment list filters by `case_id`, `investigator_id`, and `status`.

Exactly one **investigation** ever exists for a case. A `DepartmentInvestigator` opens it while the case is `ASSIGNED` (`ERR_CASE_INVALID_STATE` otherwise), and opening requires an `ACTIVE` `PRIMARY` assignment on the case — without one the request fails with `ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT`. The investigation begins `OPEN` and the case moves `ASSIGNED` → `UNDER_INVESTIGATION`.

Evidence accumulates as notes. Each note records a `note_type` of `INTERVIEW`, `DOCUMENT_REVIEW`, `SITE_VISIT`, or `PHONE_CALL` and a free-text `body`; the server stamps `author_id` from the caller. Two derived counters track sufficiency: `note_count` over all of the investigation's notes and `interview_note_count` over those of type `INTERVIEW`; both recompute as notes are appended, and the note list filters by `investigation_id` and `note_type`.

Fieldwork often needs a room. The case's active primary investigator books one by supplying `investigation_id`, `room_id`, `start_at`, and `end_at`; the server records `booked_by_id` from the caller, and a caller who is not the case's `ACTIVE` `PRIMARY` investigator is rejected with `ERR_IDENTITY_MISMATCH`. The window must be sane — `end_at` strictly after `start_at` and `start_at` not before the current clock — or the request fails with `ERR_BOOKING_WINDOW_INVALID`. Bookings on the same room must respect a fifteen-minute turnover: the new booking must end no later than nine hundred seconds before an existing `BOOKED` booking starts, or start no earlier than nine hundred seconds after that booking ends. A gap of exactly nine hundred seconds on a side is allowed; eight hundred ninety-nine seconds, or any overlap, is rejected with `ERR_BOOKING_BUFFER_VIOLATION`. A booking is born `BOOKED`; the booking investigator may cancel it (`BOOKED` → `CANCELLED`), with the same identity binding (`ERR_IDENTITY_MISMATCH`) and a state guard (`ERR_BOOKING_INVALID_STATE`) on anything no longer booked. The booking list filters by `investigation_id`, `room_id`, and `status`.

When the evidence base is ready, the investigator submits findings, supplying `findings_summary` and a `care_concern_flag`. Submission requires the investigation to be `OPEN` (`ERR_INVESTIGATION_INVALID_STATE` otherwise) and an evidence floor of at least two notes in total with at least one `INTERVIEW` note among them — anything thinner is rejected with `ERR_INSUFFICIENT_INVESTIGATION_EVIDENCE`. Acceptance of the submission stamps `submitted_by_id` and `submitted_at`, stores the two payload fields, moves the investigation `OPEN` → `FINDINGS_SUBMITTED`, and bubbles the case `UNDER_INVESTIGATION` → `FINDINGS_REVIEW`.

Review belongs to the `PatientRelationsDirector`, who holds two doors. Returning findings (payload `return_reason`) moves the investigation `FINDINGS_SUBMITTED` → `OPEN`, clears `findings_summary` and `submitted_by_id`, and drops the case back to `UNDER_INVESTIGATION` for another cycle. Accepting findings moves the investigation `FINDINGS_SUBMITTED` → `FINDINGS_ACCEPTED` — a terminal state — and advances the case `FINDINGS_REVIEW` → `RESPONSE_DRAFTING`. Acceptance carries a cascade: when the submitted `care_concern_flag` is true, the system files a `CARE_CONCERN` escalation on the case with `source` `AUTO_CARE_FLAG`, `filed_by_id` taken from the investigation's `submitted_by_id`, and status `FILED` (§3.6). Both doors require `FINDINGS_SUBMITTED`; any other investigation state meets `ERR_INVESTIGATION_INVALID_STATE`.

A case reopened after closure (§3.9) finds its investigation moved from `FINDINGS_ACCEPTED` to `REOPENED` by the cascade. Resuming work is again the investigator's act: resume requires the investigation in `REOPENED` and the case in `REOPENED` (the respective violations are `ERR_INVESTIGATION_INVALID_STATE` and `ERR_CASE_INVALID_STATE`), and it returns the investigation to `OPEN` while the case bubbles `REOPENED` → `UNDER_INVESTIGATION`. The investigation list filters by `case_id` and `status`.

### 3.4. The Written Response, Review Loop, and Closure

Every grievance — and every complaint that was not fast-track closed — ends in a written **response letter**. A `DepartmentInvestigator` drafts the letter with a `sections` array drawn from `PATIENT_SUMMARY`, `INVESTIGATION_STEPS`, `FINDINGS`, `RESOLUTION`, `CONTACT_INFO`, `RISK_DISCLOSURE`, and `QAPI_REFERENCE`, plus a `body_summary`. Drafting presupposes the case has reached `RESPONSE_DRAFTING`: for a grievance that means the investigation has been accepted; for a complaint it means the case arrived by fast-track. The server stamps `drafted_by_id` from the caller. A case may hold only one non-terminal letter at a time — a second draft while one is alive in `DRAFT`, `IN_REVIEW`, or `RETURNED` is rejected with `ERR_ACTIVE_LETTER_EXISTS` — and when a draft follows an earlier superseded letter, `supersedes_letter_id` links to the most recent `SUPERSEDED` letter. Letters begin in `DRAFT`. The letter list filters by `case_id`, `status`, and `supersedes_letter_id`.

Submitting a draft for review is the investigator's act and is accepted from either `DRAFT` or `RETURNED` (any other letter state meets `ERR_LETTER_INVALID_STATE`). Submission enforces the content standard: the five sections `PATIENT_SUMMARY`, `INVESTIGATION_STEPS`, `FINDINGS`, `RESOLUTION`, and `CONTACT_INFO` are always required, and two more — `RISK_DISCLOSURE` and `QAPI_REFERENCE` — become mandatory whenever the case's `requires_qro_cosign` is true or any `CARE_CONCERN` escalation for the case is still open or has been adjudicated substantiated. A letter failing the standard is rejected with `ERR_CONTENT_STANDARD_VIOLATION` (HTTP 422). A compliant submission moves the letter to `IN_REVIEW` and the case `RESPONSE_DRAFTING` → `RESPONSE_REVIEW`.

Review is the director's loop. Returning the letter (payload `return_reason`, which the letter stores on its own `return_reason` field) requires `IN_REVIEW` and moves the letter to `RETURNED` while the case falls back `RESPONSE_REVIEW` → `RESPONSE_DRAFTING`; the pair resubmits through the same content standard. Approval is weightier and is open to a `PatientRelationsDirector` or a `QualityRiskOfficer`. Its gates are evaluated in order: the letter must be `IN_REVIEW` and the case in `RESPONSE_REVIEW` (`ERR_LETTER_INVALID_STATE`, `ERR_CASE_INVALID_STATE`); the approver must not be the investigation's findings submitter (`ERR_SEGREGATION_OF_DUTIES`, §2.10); when the case's `requires_qro_cosign` is true — which holds whenever `severity_tier` is `CRITICAL` or any escalation of the case stands `ADJUDICATED_SUBSTANTIATED` — the approving caller must be a `QualityRiskOfficer` (`ERR_QRO_COSIGN_REQUIRED`, HTTP 403); and no escalation for the case may stand in `FILED`, `IN_REVIEW`, or `REVIEWS_COMPLETE` (`ERR_OPEN_ESCALATION_BLOCKS_APPROVAL`). Approval stamps `approved_by_id`, moves the letter to `APPROVED`, and the case `RESPONSE_REVIEW` → `PENDING_CLOSURE`.

Issuance closes the loop. An `IntakeCoordinator` issues an `APPROVED` letter while the case is `PENDING_CLOSURE` (the two state guards reject otherwise). Issuance stamps `issued_at`, moves the letter `APPROVED` → `ISSUED`, and closes the case: `lifecycle_status` becomes `CLOSED`, `closed_at` takes the current clock, and `closure_note` is copied from the letter's `body_summary`. Timeliness is judged against the binding calendar due — `resolution_timeliness` reads `ON_TIME` when issuance lands on or before `response_due_calendar_at` (equality is on time) and `LATE` otherwise; it had read `NA` until closure. Closure then sweeps the case's dependents: every `ACTIVE` assignment on the case moves to `COMPLETED` and each investigator's `open_assignment_count` falls by one; every `OPEN` clock suspension closes at the closure instant, freezing the tolling credit (§3.5); a satisfaction follow-up is created on the schedule of §3.9; and the unit's `open_case_count` falls by one.

Complaints have a lighter path. While a case is `ASSIGNED`, an `IntakeCoordinator` may fast-track a case whose `classification` is `COMPLAINT` straight to `RESPONSE_DRAFTING` — attempting it on a grievance is rejected with `ERR_FAST_TRACK_COMPLAINT_ONLY`, and the case `version` advances by one on success. From `RESPONSE_DRAFTING`, a complaint may be closed directly with closure documentation: the `closure_note` is required and must run at least twenty characters (`ERR_INVALID_REQUEST` when shorter). A grievance may never take this door — the attempt is rejected with `ERR_GRIEVANCE_REQUIRES_WRITTEN_RESPONSE`, because a grievance closes only through an issued letter. Fast-track closure performs the same closure cascade as issuance: `closed_at` is stamped, timeliness judged against `response_due_calendar_at` with equality on time, active assignments complete, open suspensions close, the follow-up is created, the unit count falls, and the case `version` advances by one.

### 3.5. Clock Suspensions, Tolling Credit, and Breach Derivation

Real cases stall for legitimate reasons — a patient travels, a family deliberates, records crawl in from another facility, an interpreter must be scheduled. An `IntakeCoordinator` suspends the response clock by opening a **clock suspension** with a `reason` of `AWAITING_PATIENT`, `AWAITING_FAMILY`, `AWAITING_RECORDS`, or `LANGUAGE_ACCESS`. The server stamps `started_at` with the current clock. A case may hold only one `OPEN` suspension at a time; a second attempt meets `ERR_DUPLICATE_OPEN_SUSPENSION`. While a suspension is open, the case's regulatory clock reads `SUSPENDED`.

Closing a suspension — the coordinator's act, or the system's when the case closes or is withdrawn — requires it to be `OPEN` (`ERR_SUSPENSION_INVALID_STATE` otherwise). Closure stamps `closed_at` and fixes `credited_seconds` as the number of seconds between start and close. The case's `tolling_credit_seconds` is then recomputed by interval merge: gather every suspension interval of the case — an `OPEN` suspension contributes a provisional interval ending at the current clock reading — sort them by `started_at` ascending, and fuse any pair that overlaps or merely touches, so that when the next interval starts no later than the running interval's end the two become one interval whose end is the later of the two ends. The credit is the sum of the merged durations, in seconds, and both response dues re-extend by it. The suspension list filters by `case_id` and `status`.

The case's `regulatory_clock_status` is a parallel dimension, derived on every read in a pinned order. First the tolling credit is recomputed by the interval merge above; then `response_due_calendar_at` is recomputed as its base plus that credit; only then is the status read off, and the status never feeds back into the first two steps within the same evaluation. The derivation itself runs top-down: a case that is `CLOSED` or `WITHDRAWN`, or still `UNCLASSIFIED`, reads `ON_TRACK`. Otherwise, any `OPEN` suspension makes it read `SUSPENDED`. Otherwise, once the clock passes the tolling-adjusted `response_due_calendar_at`, it reads `RESPONSE_BREACH`. Otherwise, a grievance whose acknowledgment has not been recorded once the clock passes `ack_due_at` reads `ACK_BREACH`. Anything else reads `ON_TRACK`. Two precedences matter: a response breach outranks an acknowledgment breach when both hold, and suspension masks both while open — the acknowledgment clock is not tolled and keeps accruing underneath, re-derived when the suspension closes.

Suspension close therefore resolves to one of three readings: `ON_TRACK` when the re-extended dues are still ahead and the acknowledgment is satisfied or not yet due; `ACK_BREACH` when the acknowledgment remains unsent and its untolled due has already passed; or `RESPONSE_BREACH` when the clock already stands past the re-extended response due. A case sitting in `RESPONSE_BREACH` recovers to `ON_TRACK` when reclassification, an expedite recompute (§3.6), or fresh tolling credit moves the calendar due to the present or later while the case remains unresolved. A computed timeline read on any case exposes `ack_due_at`, `response_due_calendar_at`, `response_due_business_at`, `tolling_credit_seconds`, `regulatory_clock_status`, `priority_score`, and `days_remaining` — the whole days left until the binding calendar due — in one shot.

### 3.6. Quality and Risk Escalations

A **quality/risk escalation** is the bridge from patient relations to the hospital's safety and compliance machinery. A `QualityRiskOfficer` files one manually with an `escalation_type` of `CARE_CONCERN` or `SYSTEMIC`, a `review_track` selection, and an optional `outcome_note`; the filing starts `FILED` with `source` `MANUAL` and `filed_by_id` stamped from the officer. Escalations also arrive automatically, with `filed_by_id` recorded as 'system' or inherited from the findings submitter: the care-concern cascade of §3.3 (`AUTO_CARE_FLAG`) and the systemic-threshold sweep of §3.2 (`AUTO_SYSTEMIC_THRESHOLD`). The escalation list filters by `case_id`, `status`, `filed_by_id`, `adjudicated_by_id`, and `escalation_type`.

Triage moves a `FILED` escalation to `IN_REVIEW` — any other state meets `ERR_ESCALATION_INVALID_STATE` — and stores the `review_track`, which must be one of `COMPLIANCE`, `SAFETY`, or `BOTH`. Review then proceeds per branch. Each completion call names a `review_branch`; marking the compliance branch sets `compliance_review_done`, and marking the safety branch sets `safety_review_done`. The join rule advances the escalation to `REVIEWS_COMPLETE` exactly when the track's required branches are done: a `COMPLIANCE` track completes when the compliance flag is set, a `SAFETY` track when the safety flag is set, and `BOTH` only when both flags stand. Completion calls against an escalation not in `IN_REVIEW` are rejected with `ERR_ESCALATION_INVALID_STATE`.

Adjudication is the terminal act, open to a `QualityRiskOfficer` once the escalation stands `REVIEWS_COMPLETE` (`ERR_ESCALATION_INVALID_STATE` before that). The segregation rule of §2.10 applies: the adjudicator must differ from `filed_by_id`, except when the filer is 'system' (`ERR_SEGREGATION_OF_DUTIES`). The payload's `outcome` selects between a substantiated and an unsubstantiated finding, and an optional `outcome_note` records the rationale. Either outcome stamps `adjudicated_by_id` and `adjudicated_at`.

An unsubstantiated adjudication ends the escalation at `ADJUDICATED_UNSUBSTANTIATED` with no effect on the case. A substantiated one — `ADJUDICATED_SUBSTANTIATED` — fires a three-link cascade. First, the case's `requires_qro_cosign` is recomputed and becomes true. Second, the regulatory dues are expedited: when seven calendar days after `adjudicated_at` falls earlier than the current `response_due_calendar_at`, the calendar due is pulled in to that earlier instant, and the business due is likewise pulled in to seven business days after `adjudicated_at` when that is earlier. Third, when the recomputed calendar due already lies in the past and the case is unresolved, the case's regulatory clock reads `RESPONSE_BREACH` and the system files a reportable event on the case — `trigger_reason` `SUBSTANTIATED_CARE_CONCERN`, `escalation_id` pointing at this escalation, status `PENDING_FILING`, and a filing deadline five business days after `adjudicated_at` (§3.7).

### 3.7. Reportable Events and Unit Posture

Some outcomes must be reported outside the hospital. A `QualityRiskOfficer` registers a **reportable event** on a case with an `authority_code` of `STATE_HEALTH_DEPT`, `CMS_REGIONAL`, or `ACCREDITATION_BODY` and a `trigger_reason` of `ALLEGED_ABUSE`, `SUBSTANTIATED_CARE_CONCERN`, or `SYSTEMIC_ISSUE`. An `escalation_id` reference is required for every trigger except `ALLEGED_ABUSE`; when supplied, the referenced escalation must belong to the case named in the path and must stand `ADJUDICATED_SUBSTANTIATED` — violations are rejected with `ERR_CROSS_REFERENCE_MISMATCH`. An `ALLEGED_ABUSE` event is supported only on a case whose `alleged_abuse_flag` is set; otherwise the registration fails with `ERR_EVENT_TRIGGER_NOT_SUPPORTED`. The event begins `PENDING_FILING`, and its `filing_deadline_at` is fixed at creation: an alleged-abuse event must be filed within exactly forty-eight hours of creation with no calendar adjustment, while any other trigger allows five business days on the §2.8 arithmetic. The event list filters by `case_id`, `escalation_id`, and `status`.

Filing is the officer's act, and the clock decides its character. Filing on or before the deadline — equality counts as on time — moves the event to `FILED` with `filed_at` stamped and `late_filing` false. Filing even one second later moves it to `LATE_FILED` instead: `filed_at` is stamped, `late_filing` reads true, and the late filing cascades onto the unit. The unit's `late_filed_event_count` rises by one; a unit in `STANDARD` posture flips to `RESTRICTED`; and while any unit stands `RESTRICTED`, new case intake on that unit is rejected with `ERR_UNIT_IN_RESTRICTED_POSTURE`. Restoration is earned, not declared: moving the unit back to `STANDARD` is blocked with `ERR_UNIT_HAS_UNRESOLVED_LATE_EVENTS` until every late-filed event on the unit's cases has been acknowledged.

Acknowledgment belongs to the `ComplianceAuditor`, who records the authority's confirmation — optionally carrying an `authority_reference` — moving the event from `FILED` or `LATE_FILED` to `ACKNOWLEDGED`. Acknowledging an event in any other state is rejected with `ERR_EVENT_INVALID_STATE`. Acknowledgment is also the only way a late-filed event stops counting against its unit's posture.

### 3.8. Service Recovery and Patient-Relations Rounding

Service recovery puts goodwill on a ledger. A `PatientAdvocate` issues a gesture on a case by naming an `action_type` — `MEAL_VOUCHER`, `PARKING_COMP`, `BILL_ADJUSTMENT`, `GOODWILL_GESTURE`, or `EXPEDITED_APPOINTMENT` — a `value_cents` that must be a positive integer (`ERR_INVALID_REQUEST` otherwise), and a `justification`. The server stamps `issued_by_id` with the acting advocate's staff identity. Issuance is self-approving up to the advocate's own ceiling: an action whose value does not exceed the issuer's `recovery_issuance_limit_cents` is born `ISSUED` and immediately raises the case's `outstanding_recovery_cents` by its value; an action above the ceiling is born `PENDING_APPROVAL` and touches no ledger until approved. The case's `outstanding_recovery_cents` is a derived figure — the sum of `value_cents` over the case's actions currently `ISSUED`, minus the sum over those currently `REVOKED` — recomputed on every read.

A per-case ceiling of 50,000 cents binds issued value. At creation, the projected total — the sum of `value_cents` across the case's `ISSUED` actions plus the new action's value — is rejected with `ERR_RECOVERY_CASE_CAP_EXCEEDED` (HTTP 402) only when it strictly exceeds the ceiling; a projection landing exactly on 50,000 cents is allowed. Approval is the `PatientRelationsDirector`'s act on a `PENDING_APPROVAL` action (`ERR_RECOVERY_INVALID_STATE` otherwise), segregated from the issuer under §2.10 (`ERR_SEGREGATION_OF_DUTIES`), and it re-checks the ceiling against the then-current issued total, because intervening issuances may have consumed the headroom since the action was queued. Approval stamps `approved_by_id` and moves the action to `ISSUED`, adding its value to the case's outstanding recovery. Rejection — optionally annotated with a `reject_reason` — moves it to `REJECTED`, and the same rejection happens automatically to every pending action when its case is withdrawn. Revocation is the compensating act on an `ISSUED` action: the director supplies a `revoke_reason`, the action moves to `REVOKED`, and the case's outstanding recovery falls by the action's value. The recovery list filters by `case_id`, `issued_by_id`, `approved_by_id`, and `status`.

Rounding keeps advocates visible on the units. A `PatientAdvocate` schedules a session with a `unit_id`, a `start_at` (inclusive), and an `end_at` (exclusive — the window is half-open); the session's `advocate_id` is the caller's own staff identity. The window must be sane — end strictly after start, and start not before the current clock — or it is rejected with `ERR_ROUNDING_WINDOW_INVALID`. An advocate flagged `on_leave` may not schedule at all (`ERR_ADVOCATE_ON_LEAVE`, HTTP 403). Two conflict rules then apply. Pairwise, the new session must not overlap any of the same advocate's other `SCHEDULED` sessions: two windows overlap when the new one begins strictly before the existing one ends and the existing one begins strictly before the new one ends, so back-to-back adjacency is permitted; a conflict is rejected with `ERR_ROUNDING_OVERLAP`. Aggregately, the unit enforces occupancy: when the number of `SCHEDULED` sessions on the unit overlapping the requested window already equals the unit's `max_concurrent_roundings`, the request is rejected with `ERR_UNIT_ROUNDING_CAPACITY`; one fewer than the maximum is accepted. A session is born `SCHEDULED`. Completing it (optionally recording an `outcome_note`) moves it to `COMPLETED`, and cancelling moves it to `CANCELLED`; both acts are bound to the session's own advocate (`ERR_IDENTITY_MISMATCH`) and require the session still `SCHEDULED` (`ERR_ROUNDING_INVALID_STATE`). The session list filters by `unit_id`, `advocate_id`, and `status`.

### 3.9. Satisfaction Follow-Up, Reopening, Withdrawal, and Trend Analysis

Closure is not the end of the relationship. Every closure — by issued letter or by complaint fast-track — spawns a **satisfaction follow-up** in `PENDING`, with `due_at` set five business days after `closed_at` and `expires_at` ten business days after `due_at`, both on the business-day arithmetic of §2.8 at the same time of day as their base. A `PatientAdvocate` records the patient's `score`, an integer from 1 to 5; a score outside that range is rejected with `ERR_FOLLOWUP_SCORE_INVALID` (HTTP 422). Responding requires the follow-up still `PENDING` and the clock not past `expires_at` — a late response is rejected with `ERR_FOLLOWUP_INVALID_STATE`, and a follow-up still pending past its expiry reads `EXPIRED`. A recorded response stamps `responded_at` and moves the follow-up to `RESPONDED`. A score of two or lower is treated as a failed resolution and fires the full reopen cascade on the case. The follow-up list filters by `case_id` and `status`.

Reopening — whether fired by a low score or invoked directly by a `PatientRelationsDirector` with an optional `reopen_reason` — is permitted only from `CLOSED` (`ERR_CASE_INVALID_STATE` otherwise) and unwinds the closure in three cascade links. First, the case moves `CLOSED` → `REOPENED`: `reopen_count` rises by one, `closed_at` is cleared, `resolution_timeliness` returns to `NA`, and the unit's `open_case_count` rises by one. Second, the case's `FINDINGS_ACCEPTED` investigation moves to `REOPENED` and its `ISSUED` letter moves to `SUPERSEDED`. Third, the regulatory dues are re-anchored: `response_due_calendar_at` becomes fifteen calendar days after the reopen instant and `response_due_business_at` fifteen business days after it, with `requires_qro_cosign` recomputed. The case `version` advances by one. From `REOPENED`, the investigation resume of §3.3 carries the case back into `UNDER_INVESTIGATION`, and a fresh draft — linked through `supersedes_letter_id` — begins the response loop again.

Withdrawal is the patient's prerogative, exercised by an `IntakeCoordinator` with an optional `withdraw_reason`. It is available from every non-terminal state except `CLOSED` — `INTAKE`, `CLASSIFIED`, `ASSIGNED`, `UNDER_INVESTIGATION`, `FINDINGS_REVIEW`, `RESPONSE_DRAFTING`, `RESPONSE_REVIEW`, `PENDING_CLOSURE`, and `REOPENED` — and from anywhere else, including the terminal `WITHDRAWN` itself, the request meets `ERR_CASE_INVALID_STATE`. The withdraw cascade releases every `ACTIVE` assignment to `RELEASED` with each investigator's count falling by one, cancels an investigation standing in `OPEN`, `FINDINGS_SUBMITTED`, or `REOPENED` to `CANCELLED`, cancels letters standing in `DRAFT`, `IN_REVIEW`, or `RETURNED` while conspicuously leaving an `APPROVED` letter approved, closes every `OPEN` suspension at the withdrawal instant, rejects every `PENDING_APPROVAL` recovery action, and lowers the unit's `open_case_count` by one. The case `version` advances by one, and `WITHDRAWN` is terminal — nothing leaves it.

Trend reporting is the one place where derivation gives way to materialization. A `PatientRelationsDirector` or `ComplianceAuditor` computes a snapshot for a `period` given as `YYYY-MM`, which must not lie beyond the current month (`ERR_INVALID_REQUEST` otherwise). For each unit-and-category cell with closures in the period, a `TrendSnapshot` row records the `unit_id`, the `case_category` it covers, and five measures. `grievances_closed` and `complaints_closed` count the cases on that unit and category whose `closed_at` falls inside the calendar month — on or after its first instant and strictly before the next month's — split by classification at closure; `breaches` counts those closed cases whose `resolution_timeliness` stands `LATE`; `systemic_new_count` counts the `SYSTEMIC` escalations auto-created for that unit and category whose triggering case closed in the period. Two breach rates follow. The headline `headcount_rate_bp` is the breach count multiplied by ten thousand and divided by the cell's total closures, rounded half-up to an integer basis point, and zero when the cell has no closures. The `exposure_weighted_rate_bp` weights severity of lateness: each late case contributes its days-late — the difference between its `closed_at` and its binding `response_due_calendar_at`, expressed in days — and each closed case contributes its window-days, the difference between its `received_at` and that calendar due measured at closure; the rate is the summed days-late multiplied by ten thousand and divided by the summed window-days, rounded half-up, and zero when the window-day total is zero. A cell that already exists for its unit, category, and period refuses recomputation with `ERR_SNAPSHOT_EXISTS` unless the request passes `force_recompute` true, in which case the row is upserted.

The compute call answers with the `period`, the number of `cells_created`, and a `system_rate_bp` whose rounding order is pinned: each cell's headcount rate is first rounded half-up to an integer basis point, and only then is the mean of those per-cell rounded rates taken across cells with at least one closure, itself rounded half-up. Computing the system rate globally — summing breaches and closures before dividing — is expressly forbidden, because it yields a different figure. The snapshot list filters by `unit_id` and `period`.

## 4. Endpoint Definitions

Operations that create a new resource answer `201 Created`; operations that act on or modify an existing resource answer `200 OK`; the holiday removal answers `204 No Content` with no body. The table below is a navigational index — request fields, response fields, and side effects are defined by the narratives of §2 and §3, not by this table. All read endpoints accept every declared role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |
| POST | `/api/hospital-units` | Create a hospital unit | SystemAdmin |
| GET | `/api/hospital-units` | List units | Any |
| GET | `/api/hospital-units/{id}` | Get a unit | Any |
| PATCH | `/api/hospital-units/{id}` | Update unit posture or rounding capacity | PatientRelationsDirector, SystemAdmin |
| POST | `/api/staff-members` | Register a staff member | SystemAdmin |
| GET | `/api/staff-members` | List staff | Any |
| GET | `/api/staff-members/{id}` | Get a staff member | Any |
| PATCH | `/api/staff-members/{id}` | Update leave status, capacity, or issuance limit | SystemAdmin, PatientRelationsDirector |
| POST | `/api/holiday-observances` | Register a holiday skipped by business-day arithmetic | SystemAdmin |
| GET | `/api/holiday-observances` | List holidays | Any |
| DELETE | `/api/holiday-observances/{id}` | Remove a holiday; business-day dues recompute on next read | SystemAdmin |
| POST | `/api/patient-cases` | Intake a new patient concern | IntakeCoordinator |
| GET | `/api/patient-cases` | List cases with filters | Any |
| GET | `/api/patient-cases/{id}` | Get a case | Any |
| GET | `/api/patient-cases/{id}/timeline` | Computed regulatory timeline read | Any |
| POST | `/api/patient-cases/{id}/acknowledge` | Record grievance acknowledgment sent | IntakeCoordinator |
| POST | `/api/patient-cases/{id}/withdraw` | Withdraw a case | IntakeCoordinator |
| POST | `/api/patient-cases/{id}/reopen` | Manually reopen a closed case | PatientRelationsDirector |
| POST | `/api/patient-cases/{id}/fast-track` | Move an assigned complaint directly to response drafting | IntakeCoordinator |
| POST | `/api/patient-cases/{id}/close` | Complaint fast-track closure with closure documentation | IntakeCoordinator |
| POST | `/api/patient-cases/{id}/classification-decisions` | Record initial classification or reclassify (OCC-guarded) | IntakeCoordinator |
| GET | `/api/classification-decisions` | List classification decisions | Any |
| GET | `/api/classification-decisions/{id}` | Get a classification decision | Any |
| POST | `/api/patient-cases/{id}/assignments` | Assign an investigator, explicit or selector-chosen (OCC-guarded) | PatientRelationsDirector |
| GET | `/api/case-assignments` | List assignments | Any |
| GET | `/api/case-assignments/{id}` | Get an assignment | Any |
| POST | `/api/case-assignments/{id}/release` | Release an active assignment | PatientRelationsDirector |
| POST | `/api/patient-cases/{id}/investigations` | Open the case's single investigation | DepartmentInvestigator |
| GET | `/api/investigations` | List investigations | Any |
| GET | `/api/investigations/{id}` | Get an investigation | Any |
| POST | `/api/investigations/{id}/notes` | Append an investigation note | DepartmentInvestigator |
| POST | `/api/investigations/{id}/submit-findings` | Submit findings for review | DepartmentInvestigator |
| POST | `/api/investigations/{id}/accept-findings` | Accept findings; care concern auto-creates an escalation | PatientRelationsDirector |
| POST | `/api/investigations/{id}/return-findings` | Return findings for revision | PatientRelationsDirector |
| POST | `/api/investigations/{id}/resume` | Resume a reopened investigation | DepartmentInvestigator |
| GET | `/api/investigation-notes` | List notes, filterable by investigation | Any |
| GET | `/api/investigation-notes/{id}` | Get a note | Any |
| POST | `/api/patient-cases/{id}/response-letters` | Draft a response letter | DepartmentInvestigator |
| GET | `/api/response-letters` | List letters | Any |
| GET | `/api/response-letters/{id}` | Get a letter | Any |
| POST | `/api/response-letters/{id}/submit-review` | Submit a letter for review (content standard enforced) | DepartmentInvestigator |
| POST | `/api/response-letters/{id}/approve` | Approve a letter (SoD, co-sign, escalation gate) | PatientRelationsDirector, QualityRiskOfficer |
| POST | `/api/response-letters/{id}/return` | Return a letter to drafting | PatientRelationsDirector |
| POST | `/api/response-letters/{id}/issue` | Issue the approved letter; closes the case | IntakeCoordinator |
| POST | `/api/patient-cases/{id}/recovery-actions` | Issue a service-recovery gesture | PatientAdvocate |
| GET | `/api/recovery-actions` | List recovery actions | Any |
| GET | `/api/recovery-actions/{id}` | Get a recovery action | Any |
| POST | `/api/recovery-actions/{id}/approve` | Approve a pending recovery action (SoD; cap re-checked) | PatientRelationsDirector |
| POST | `/api/recovery-actions/{id}/reject` | Reject a pending recovery action | PatientRelationsDirector |
| POST | `/api/recovery-actions/{id}/revoke` | Revoke an issued recovery action | PatientRelationsDirector |
| POST | `/api/patient-cases/{id}/escalations` | Manually file a quality/risk escalation | QualityRiskOfficer |
| GET | `/api/escalations` | List escalations | Any |
| GET | `/api/escalations/{id}` | Get an escalation | Any |
| POST | `/api/escalations/{id}/triage` | Triage a filed escalation, setting the review track | QualityRiskOfficer |
| POST | `/api/escalations/{id}/complete-review` | Mark one review branch complete; joins when all required branches are done | QualityRiskOfficer |
| POST | `/api/escalations/{id}/adjudicate` | Adjudicate a completed escalation (SoD versus the filer) | QualityRiskOfficer |
| POST | `/api/patient-cases/{id}/reportable-events` | Register a regulatory reportable event | QualityRiskOfficer |
| GET | `/api/reportable-events` | List reportable events | Any |
| GET | `/api/reportable-events/{id}` | Get a reportable event | Any |
| POST | `/api/reportable-events/{id}/file` | File the event with the authority; past deadline triggers the late cascade | QualityRiskOfficer |
| POST | `/api/reportable-events/{id}/acknowledge` | Record authority acknowledgment | ComplianceAuditor |
| POST | `/api/rounding-sessions` | Schedule a rounding session (advocate is the caller) | PatientAdvocate |
| GET | `/api/rounding-sessions` | List rounding sessions | Any |
| GET | `/api/rounding-sessions/{id}` | Get a rounding session | Any |
| POST | `/api/rounding-sessions/{id}/complete` | Complete a rounding session | PatientAdvocate |
| POST | `/api/rounding-sessions/{id}/cancel` | Cancel a rounding session | PatientAdvocate |
| POST | `/api/interview-rooms` | Register an interview room | SystemAdmin |
| GET | `/api/interview-rooms` | List interview rooms | Any |
| GET | `/api/interview-rooms/{id}` | Get an interview room | Any |
| POST | `/api/interview-bookings` | Book an interview room for an investigation (buffer rule) | DepartmentInvestigator |
| GET | `/api/interview-bookings` | List interview bookings | Any |
| GET | `/api/interview-bookings/{id}` | Get a booking | Any |
| POST | `/api/interview-bookings/{id}/cancel` | Cancel a booking | DepartmentInvestigator |
| GET | `/api/follow-ups` | List satisfaction follow-ups | Any |
| GET | `/api/follow-ups/{id}` | Get a follow-up | Any |
| POST | `/api/follow-ups/{id}/respond` | Record the patient satisfaction score; a low score reopens the case | PatientAdvocate |
| POST | `/api/patient-cases/{id}/clock-suspensions` | Suspend the response clock (one open per case) | IntakeCoordinator |
| GET | `/api/clock-suspensions` | List suspensions | Any |
| GET | `/api/clock-suspensions/{id}` | Get a suspension | Any |
| POST | `/api/clock-suspensions/{id}/close` | Close an open suspension; tolling credit applied | IntakeCoordinator |
| POST | `/api/trend-snapshots/compute` | Materialize per-unit-and-category snapshot cells for a period | PatientRelationsDirector, ComplianceAuditor |
| GET | `/api/trend-snapshots` | List snapshots | Any |
| GET | `/api/trend-snapshots/{id}` | Get a snapshot cell | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_FOLLOWUP_SCORE_INVALID` | 422 Unprocessable Entity |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_CLASSIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_NOTE_NOT_FOUND` | 404 Not Found |
| `ERR_LETTER_NOT_FOUND` | 404 Not Found |
| `ERR_RECOVERY_NOT_FOUND` | 404 Not Found |
| `ERR_ESCALATION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUNDING_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_FOLLOWUP_NOT_FOUND` | 404 Not Found |
| `ERR_SUSPENSION_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_HOLIDAY_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_INVESTIGATION_INVALID_STATE` | 409 Conflict |
| `ERR_LETTER_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_RECOVERY_INVALID_STATE` | 409 Conflict |
| `ERR_ESCALATION_INVALID_STATE` | 409 Conflict |
| `ERR_EVENT_INVALID_STATE` | 409 Conflict |
| `ERR_ROUNDING_INVALID_STATE` | 409 Conflict |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_ROOM_INACTIVE` | 409 Conflict |
| `ERR_FOLLOWUP_INVALID_STATE` | 409 Conflict |
| `ERR_SUSPENSION_INVALID_STATE` | 409 Conflict |
| `ERR_NO_ACTIVE_PRIMARY_ASSIGNMENT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CONTENT_STANDARD_VIOLATION` | 422 Unprocessable Entity |
| `ERR_GRIEVANCE_REQUIRES_WRITTEN_RESPONSE` | 409 Conflict |
| `ERR_FAST_TRACK_COMPLAINT_ONLY` | 409 Conflict |
| `ERR_ADVOCATE_ON_LEAVE` | 403 Forbidden |
| `ERR_OPEN_ESCALATION_BLOCKS_APPROVAL` | 409 Conflict |
| `ERR_QRO_COSIGN_REQUIRED` | 403 Forbidden |
| `ERR_CROSS_REFERENCE_MISMATCH` | 409 Conflict |
| `ERR_UNIT_IN_RESTRICTED_POSTURE` | 409 Conflict |
| `ERR_UNIT_HAS_UNRESOLVED_LATE_EVENTS` | 409 Conflict |
| `ERR_EVENT_TRIGGER_NOT_SUPPORTED` | 409 Conflict |
| `ERR_ACTIVE_LETTER_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_SUSPENSION` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` | 409 Conflict |
| `ERR_ROUNDING_OVERLAP` | 409 Conflict |
| `ERR_UNIT_ROUNDING_CAPACITY` | 409 Conflict |
| `ERR_BOOKING_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_NO_ELIGIBLE_INVESTIGATOR` | 409 Conflict |
| `ERR_INVESTIGATOR_AT_CAPACITY` | 409 Conflict |
| `ERR_INSUFFICIENT_INVESTIGATION_EVIDENCE` | 409 Conflict |
| `ERR_ALREADY_ACKNOWLEDGED` | 409 Conflict |
| `ERR_SNAPSHOT_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_HOLIDAY` | 409 Conflict |
| `ERR_RECEIVED_AT_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_ROUNDING_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_BOOKING_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_RECOVERY_CASE_CAP_EXCEEDED` | 402 Payment Required |
