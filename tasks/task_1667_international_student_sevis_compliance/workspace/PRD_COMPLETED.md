# International Student SEVIS Compliance API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the International Student SEVIS Compliance API, the back-office system used by a university's Designated School Official (DSO) office to manage the full lifecycle of F-1 international student immigration records. The system covers the span from admission through departure: intake and financial-documentation review, issuance of the Form I-20, SEVIS record initialization and per-term registration, reduced-course-load authorizations, CPT/OPT employment recommendation and adjudication tracking, address-reporting compliance, transfers between schools, program extensions, status violations, reinstatement, and travel endorsements.

The office operates under strict federal timelines — registration deadlines, add/drop windows, OPT filing windows, address-reporting deadlines, unemployment-day limits — and every one of them is enforced by the server against its own logical clock rather than by operator judgment. A principal DSO (PDSO) holds exclusive authority over the small number of irreversible actions (record termination, reinstatement resolution), while day-to-day DSOs perform the bulk of the workflow and students themselves submit a narrow set of self-service artifacts (financial documents, address reports, employment periods, OPT filings). Because immigration records interact — a termination must revoke authorizations, cancel the issued I-20, and void its travel endorsements in one coherent step — the system treats state transitions as cascade-aware operations rather than isolated updates.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication and roles, the response envelope, pagination, resource identity, monetary and temporal precision, optimistic concurrency, and the server's logical clock.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes three roles, spelled exactly as follows:

- `PDSO` — Principal Designated School Official. A hierarchical superset of `DSO`: a `PDSO` may perform every `DSO` operation, and additionally holds exclusive authority over two irreversible operations — terminating an ACTIVE SEVIS record, and resolving a reinstatement-pending violation via the `RESOLVE` action. When `X-User-Role` is `PDSO`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it against any entity's `id`.
- `DSO` — Designated School Official. The day-to-day operator for intake, financial-document review, record creation and initialization, I-20 issuance, travel endorsements, term enrollment and registration, reduced-course-load decisions, employment recommendation and adjudication, transfers, program extensions, opening and dismissing violations, address reports, and clock advancement. When `X-User-Role` is `DSO`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- `Student` — an F-1 student acting on their own records. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` resource; ownership checks on any resource that references a student compare the resource's `student_id` foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403). On the collection list endpoints that accept a `student_id` query filter (`/sevis/i20-forms`, `/sevis/term-enrollments`, `/sevis/employment-authorizations`), a `Student` caller's filter is forced to their own id when omitted, and an explicit `student_id` filter naming another student is rejected with `ERR_RESOURCE_NOT_OWNED`.

A request whose role is not permitted on the target endpoint or action — for example a `Student` invoking a DSO-only action, or a `DSO` invoking record termination or `RESOLVE` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

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

A request that matches no defined route — or no defined method on a matched route — is likewise rendered in this envelope as `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order; resources sharing a `created_at` timestamp are ordered by creation (insertion) sequence. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on any mutation of the resource.
- `version` (integer): a system-managed integer that increments on every mutation and serves as the basis for optimistic concurrency control.

Any mutation of a resource — including automatic side effects applied by the server, such as a record transition cascading to an authorization or an endorsement issuance reprinting a form — updates that resource's `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Scheduled Sweeps

The server maintains its own logical clock; business deadlines throughout this document are evaluated against that clock, never against wall-clock time. Before any client call, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it advances only when an authorized operator (`PDSO` or `DSO`) invokes the clock-setting capability with a `to_iso8601` timestamp. The submitted value may be any valid ISO 8601 datetime — a value without an explicit offset is read as UTC, and no monotonicity check is applied — and it is stored verbatim as the new clock value. The clock never falls back to wall-clock time on its own. The capability response reports the resulting `current_utc`, echoed exactly as submitted, and a list `sweeps_applied` naming only the sweep categories that actually applied at least one change during this set — a category that ran but changed nothing is omitted. Category names are `transfer_releases`, `travel_endorsement_expiries`, `enrollment_registration_deadline_sweeps`, `record_completions`, `employment_authorization_completions`, `opt_post_unemployment_limit_checks`, and `enrollment_term_end_completions`.

Each clock set runs all due sweeps, in this fixed order:

1. Transfer releases whose `release_date` has been reached.
2. Travel endorsement expiries past `valid_until`.
3. Enrollment registration-deadline sweeps (enrollments still `PENDING` after their registration window).
4. Record completions past `program_end_date` plus the 60-day grace period.
5. Employment-authorization completions (authorizations still `APPROVED` past their `end_date`).
6. The OPT_POST unemployment-limit violation check.
7. Enrollment term-end completions (enrollments past `term_end_date`).

### 2.6. Nested Resource Retrieval

For endpoints whose path contains multiple resource identifiers, the system validates the existence of each identifier in strict left-to-right order and rejects the request with the first failing identifier's 404 error before considering any subsequent segment. A request naming a nonexistent student is rejected with `ERR_STUDENT_NOT_FOUND`; a request naming a nonexistent non-student resource is rejected with `ERR_NOT_FOUND`. Existence validation precedes all state and business validation for the target resource.

### 2.7. Monetary Values, Dates, and Precision

All monetary quantities are carried as integer cents — never fractional dollars — in fields such as `amount_usd_cents`, `tuition_cents`, `living_cents`, `insurance_cents`, `other_cents`, `estimated_total_cents`, `verified_funding_cents`, and `provisional_funding_cents`. Aggregations over these fields are integer sums with no rounding. The single exception to "no rounding" is the proration performed when a program extension manufactures a replacement I-20: each cost line is first rounded half-up to whole cents individually, and only then are the rounded lines summed — summing raw prorated values and rounding once at the end is a different contract and is not accepted.

All calendar fields are ISO 8601 dates (`YYYY-MM-DD`) unless noted otherwise, and all day-count arithmetic is performed at whole-day granularity. Credit and day counters are integers. Month arithmetic on dates (used for travel-endorsement validity) clamps to the end of the resulting month when the target month lacks the corresponding day.

### 2.8. Optimistic Concurrency Control

Two write operations in the system require an optimistic-concurrency token from the client, and in both cases the version check runs before any business validation:

- Requesting a program extension requires the request to carry `expected_sevis_record_version` equal to the student's SEVIS record's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Issuing a travel endorsement on an I-20 requires the request to carry `expected_i20_form_version` equal to that I20Form's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not take a version field.

### 2.9. Validation Order

When a single request would violate several rules, the system reports the first applicable failure in a fixed priority order rather than an arbitrary one:

1. **Authentication context.** Missing or malformed `X-User-ID` / `X-User-Role` headers produce `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization and ownership.** A role not permitted on the endpoint produces `ERR_INSUFFICIENT_PERMISSIONS`; a `Student` acting on a resource owned by a different student produces `ERR_RESOURCE_NOT_OWNED`. On the employment and violation transition endpoints an action-specific role rule also applies — `FILE` is a student action, `RESOLVE` is a `PDSO` action — but because the action is read from the request body, that rule is evaluated only after existence validation of the path identifiers and after the body parses, not within this band.
3. **Existence.** Path identifiers are validated left-to-right as described in §2.6 (`ERR_STUDENT_NOT_FOUND` / `ERR_NOT_FOUND`, HTTP 404).
4. **Optimistic concurrency.** On the two OCC-guarded writes, a stale `expected_sevis_record_version` or `expected_i20_form_version` produces `ERR_STALE_VERSION` (HTTP 412) before any state or business rule is consulted.
5. **State preconditions.** The target resource must be in the state its transition requires — record `DRAFT`/`ACTIVE`/`TERMINATED` as applicable, enrollment `PENDING`, RCL `REQUESTED`, authorization `DRAFT`/`RECOMMENDED`/`FILED`, violation `OPEN`/`REINSTATEMENT_PENDING`, I-20 `DRAFT`, financial document `SUBMITTED`, transfer `REQUESTED`. Violations surface as the transition-specific errors (`ERR_RECORD_NOT_DRAFT`, `ERR_RECORD_NOT_ACTIVE`, `ERR_RECORD_NOT_TERMINATED`, `ERR_ENROLLMENT_NOT_REGISTERABLE`, `ERR_RCL_NOT_REQUESTED`, `ERR_AUTH_INVALID_STATE`, `ERR_VIOLATION_INVALID_STATE`, `ERR_I20_NOT_DRAFT`, `ERR_DOCUMENT_ALREADY_REVIEWED`, `ERR_TRANSFER_NOT_CANCELLABLE`, `ERR_EXTENSION_NOT_REQUESTED`, HTTP 409). This priority band also applies to reduced-course-load creation, where the parent enrollment must be `PENDING` or `REGISTERED` (`ERR_ENROLLMENT_NOT_REGISTERABLE`).
6. **SEVIS structural preconditions.** Initialization requires an `ISSUED` I-20 (`ERR_NO_ISSUED_I20`); employment recommendation requires an `ISSUED` I-20 (`ERR_I20_NOT_ISSUED`) and an `ACTIVE` record; registration requires the record in `INITIAL` or `ACTIVE`; reinstatement recommendation requires the record `TERMINATED` (`ERR_RECORD_NOT_TERMINATED`).
7. **Uniqueness and overlap.** `sevis_id` uniqueness (`ERR_DUPLICATE_SEVIS_ID`), one SEVIS record per student (`ERR_RECORD_ALREADY_EXISTS`), one enrollment per (`student_id`, `term_code`) pair (`ERR_DUPLICATE_ENROLLMENT`), employment-period day-coverage non-overlap (`ERR_EMPLOYMENT_PERIOD_OVERLAP`), travel-window closed-interval non-overlap (`ERR_ENDORSEMENT_WINDOW_OVERLAP`), and at most one open RCL per enrollment (`ERR_RCL_ALREADY_OPEN`).
8. **Deadline and window rules.** Registration deadline (`ERR_REGISTRATION_DEADLINE_PASSED`), RCL add/drop close (`ERR_RCL_ADD_DROP_CLOSED`), enrollment-credit edits after add/drop (`ERR_ADD_DROP_CLOSED`), OPT filing and OPT_POST start windows (`ERR_OPT_WINDOW_CLOSED`), CPT/OPT_PRE end-date containment (`ERR_AUTH_WINDOW_INVALID`), extension-approval cutoff (`ERR_EXTENSION_WINDOW_CLOSED`), extension forward-progress (`ERR_EXTENSION_NOT_FORWARD`), and the FINAL_TERM containment check (`ERR_RCL_NOT_FINAL_TERM`).
9. **Funding sufficiency.** Verified fresh funding must cover the relevant cost figure at I-20 issuance and at extension approval (`ERR_INSUFFICIENT_VERIFIED_FUNDING`, HTTP 402).
10. **Credit rules.** Full-course-load enforcement at registration and on credit edits (`ERR_BELOW_FULL_COURSE_LOAD`), RCL requested-credit range by category (`ERR_RCL_CREDITS_OUT_OF_RANGE`), and RCL reason-category exhaustion (`ERR_RCL_REASON_EXHAUSTED`).

Malformed request bodies — a missing or null required field, a type mismatch, an invalid enum value, a malformed date, a value below its documented minimum, or a field-pattern violation (such as the `sevis_id`, `country_of_citizenship`, or `state_code` formats) — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) as the body is parsed, ahead of all state and business validation. Cross-field and clock-dependent value rules — an end date not later than its start date, a return date before its departure date, an outbound `release_date` before the clock date — are likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400). A reference named inside the body (for example `student_id`, `enrollment_id`, or `sevis_record_id`) is resolved only after the body parses, so a malformed body outranks a dangling body reference.

### 2.10. Compliance Posture

Every student carries a derived `compliance_posture` field with values `CLEAR`, `AT_RISK`, or `VIOLATION_OPEN`. It is recomputed whenever the underlying facts change — a violation opened, resolved, or dismissed; an address report landing `FLAGGED_LATE`; an OPT_POST unemployment counter moving; an authorization revocation; an enrollment flipping to `NOT_ENROLLED`. The rule is:

- If any of the student's violations is in `OPEN` or `REINSTATEMENT_PENDING` status, the posture is `VIOLATION_OPEN`.
- Otherwise, if any of the student's address reports is `FLAGGED_LATE`, or any of the student's OPT_POST authorizations has `unemployment_days_settled` of at least 75 days, the posture is `AT_RISK`.
- Otherwise the posture is `CLEAR`.

A newly created student starts at `CLEAR`.

## 3. Business Logic & Workflows

### 3.1. Student Intake and Financial Documentation

A DSO begins a student's journey by creating the intake record with `sevis_id`, `full_name`, `email`, `date_of_birth`, `country_of_citizenship`, and `degree_level` (`UNDERGRADUATE` or `GRADUATE`). The `sevis_id` must be unique across the system and match the SEVIS format — the letter N followed by ten digits; a duplicate is rejected with `ERR_DUPLICATE_SEVIS_ID`. The `country_of_citizenship` must be exactly two uppercase ASCII letters. The student's `compliance_posture` is initialized to `CLEAR`.

Financial evidence is gathered as `FinancialDocument` resources under the student. Either a DSO or the student (submitting for their own record only) may submit a document with a `document_type` of `BANK_STATEMENT`, `SCHOLARSHIP_LETTER`, or `SPONSOR_AFFIDAVIT`, an `amount_usd_cents` that is zero or greater, and the `issue_date` on which the issuing institution produced it. Submission lands the document in `SUBMITTED` status. Review is a DSO function: the reviewer supplies a `decision` of `VERIFIED` or `REJECTED` and may attach an optional `note` recorded as `review_note`. Both outcomes are terminal — a document that has already been `VERIFIED` or `REJECTED` cannot be reviewed again, and any attempt to do so is rejected with `ERR_DOCUMENT_ALREADY_REVIEWED`. The list of a student's documents may be filtered by `status` and paginated via `limit` and `offset`.

Freshness matters throughout the funding story. A document counts toward funding totals only when its `issue_date` falls within a 183-day window ending on the current clock date — that is, issued no earlier than 183 days before today and no later than today. Documents dated in the future and documents older than 183 days are excluded from every funding computation.

### 3.2. The SEVIS Record and the I-20

Each student has at most one SEVIS record. A DSO creates it with the `program_start_date` and `program_end_date` — no ordering constraint between the two dates is enforced at creation; the record lands in `DRAFT` status, and a second creation attempt for the same student is rejected with `ERR_RECORD_ALREADY_EXISTS`. Listing a student's records therefore returns an array of zero or one entries.

The I-20 form is the printable evidence attached to the record. A DSO drafts one with a payload containing the `sevis_record_id` it documents, the `program_name` printed on the form, and four cost lines — `tuition_cents`, `living_cents`, `insurance_cents`, and `other_cents`, each zero or greater. The form's `estimated_total_cents` is the integer sum of those four lines. The `program_start_date` and `program_end_date` are optional on creation; when omitted they default from the referenced SEVIS record. A `sevis_record_id` that does not name an existing record of the same student, or a `supersedes_i20_form_id` that does not name an existing form of the same student, is rejected with `ERR_NOT_FOUND`. A program change is expressed by drafting a form whose `supersedes_i20_form_id` names the currently `ISSUED` form it replaces; the field is otherwise unset, and the requirement that the named form be `ISSUED` is enforced at issuance time, not at drafting. New forms land in `DRAFT` status. Forms may be listed with the filters `student_id`, `sevis_record_id`, `supersedes_i20_form_id`, and `status`.

Issuing a draft form is the pivotal gate. Issuance requires the form in `DRAFT` (otherwise `ERR_I20_NOT_DRAFT`), the parent record in `DRAFT`, `INITIAL`, or `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`), and — when `supersedes_i20_form_id` is set — the named prior form currently in `ISSUED` status (otherwise `ERR_I20_NOT_ISSUED`). On top of those state checks stands the funding gate: the form's `verified_funding_cents` must cover its `estimated_total_cents`. Verified funding is the sum of `amount_usd_cents` over the student's documents that are in `VERIFIED` status and within the 183-day freshness window at issuance time; falling short is rejected with `ERR_INSUFFICIENT_VERIFIED_FUNDING` (HTTP 402). A second, advisory figure — `provisional_funding_cents` — is computed the same way but also counts documents still in `SUBMITTED` status, so it is at least as large as the verified figure whenever unverified documents exist. Both figures are snapshotted onto the form at issuance and returned with it thereafter; on a form still in `DRAFT`, the two figures returned are live advisory computations against the current clock rather than stored snapshots.

Issuance also maintains the supersession chain. When the new form names a `supersedes_i20_form_id`, the prior form transitions from `ISSUED` to `SUPERSEDED`, and every `ACTIVE` travel endorsement on the superseded form is voided to `VOIDED`. A form whose record is later terminated transitions from `ISSUED` to `CANCELLED`, with the same endorsement-voiding side effect; `SUPERSEDED` and `CANCELLED` are both terminal.

With an issued I-20 in hand, a DSO can initialize the record, moving it from `DRAFT` to `INITIAL`. Initialization on a record not in `DRAFT` is rejected with `ERR_RECORD_NOT_DRAFT`; initialization without any `ISSUED` form for the record is rejected with `ERR_NO_ISSUED_I20`.

### 3.3. Term Enrollment, Registration, and the Full-Course-Load Rule

Each term of study is represented by a `TermEnrollment`. A DSO creates one with the `student_id`, a `term_code` such as `2026-FALL`, the `term_start_date`, the `term_end_date` (which must be later than the start), and the `enrolled_credits` (zero or greater). One enrollment may exist per (`student_id`, `term_code`) pair; a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT`. New enrollments land in `PENDING`. Enrollments may be listed with the filters `student_id`, `term_code`, and `status`.

The full-course-load floor is captured in the enrollment's derived `effective_min_credits`. With no approved reduced course load, the floor is 12 credits for an `UNDERGRADUATE` student and 9 credits for a `GRADUATE` student. An approved RCL modifies the floor by category, as detailed in §3.4.

Registration is the act that reports the enrollment to SEVIS, transitioning it from `PENDING` to `REGISTERED`. Registration requires the enrollment still `PENDING` (otherwise `ERR_ENROLLMENT_NOT_REGISTERABLE`), the student's record in `INITIAL` or `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`), the `enrolled_credits` at or above the `effective_min_credits` floor — meeting the floor exactly counts as full-time (otherwise `ERR_BELOW_FULL_COURSE_LOAD`, HTTP 422) — and the clock date no later than 30 days after `term_start_date` (otherwise `ERR_REGISTRATION_DEADLINE_PASSED`). The first successful registration for a student also flips their SEVIS record from `INITIAL` to `ACTIVE`.

Credit loads may be revised while the enrollment is `PENDING`, and — once `REGISTERED` — only until the add/drop close, which is 14 days after `term_start_date`. A credit edit against a `REGISTERED` enrollment after that close is rejected with `ERR_ADD_DROP_CLOSED`. A credit edit against an enrollment in any other status (`NOT_ENROLLED` or `COMPLETED`) is rejected with `ERR_ENROLLMENT_NOT_REGISTERABLE`. Any edit that would drop `enrolled_credits` below `effective_min_credits` without an approved RCL is rejected with `ERR_BELOW_FULL_COURSE_LOAD`.

The clock sweep handles the two terminal enrollment outcomes. An enrollment still `PENDING` when the clock passes 30 days after `term_start_date` flips to `NOT_ENROLLED`, and the sweep simultaneously opens a `FAILURE_TO_ENROLL` violation in `OPEN` status for the student — which in turn recomputes the student's `compliance_posture` to `VIOLATION_OPEN`. Separately, an enrollment in `REGISTERED` whose `term_end_date` has passed flips to `COMPLETED`.

### 3.4. Reduced Course Load Authorization

A reduced course load lets a student legitimately enroll below the standard floor. A DSO files the request against a specific enrollment with the `enrollment_id`, a `reason_category` of `ACADEMIC`, `MEDICAL`, or `FINAL_TERM`, and the planned `requested_credits` (zero or greater). The parent enrollment must be in `PENDING` or `REGISTERED` status (otherwise `ERR_ENROLLMENT_NOT_REGISTERABLE`), and each enrollment carries at most one open — `REQUESTED` or `APPROVED` — RCL at a time (otherwise `ERR_RCL_ALREADY_OPEN`). The request itself must be filed by the add/drop close, 14 days after the enrollment's `term_start_date`; later filings are rejected with `ERR_RCL_ADD_DROP_CLOSED`. New requests land in `REQUESTED`.

Each category carries its own eligibility rule, enforced at request time:

- `ACADEMIC` — available at most once per student across the entire program level; if any earlier `ACADEMIC` RCL for the student exists in `REQUESTED` or `APPROVED` status, the new request is rejected with `ERR_RCL_REASON_EXHAUSTED`. The requested credits must be at least the academic floor, which is half the base minimum rounded down, but never below 3 credits in absolute terms — so 6 for an undergraduate and 4 for a graduate. A request below that floor is rejected with `ERR_RCL_CREDITS_OUT_OF_RANGE` (HTTP 422).
- `MEDICAL` — cumulative medical coverage across the student's `REQUESTED` and `APPROVED` medical RCLs may not exceed 12 months. Each RCL's coverage is the span of its enrollment's term, counted in months by rounding the term's day count — plain date subtraction, `term_end_date` minus `term_start_date` — divided by 30 up to the next whole month. A request whose own term would push the cumulative total past 12 months is rejected with `ERR_RCL_REASON_EXHAUSTED`.
- `FINAL_TERM` — the enrollment's term window, from `term_start_date` through `term_end_date`, must contain the record's `program_end_date`; otherwise the request is rejected with `ERR_RCL_NOT_FINAL_TERM`. The requested credits must also be below the base full-time minimum for the student's degree level — a final-term request at or above the standard floor is rejected with `ERR_RCL_CREDITS_OUT_OF_RANGE`.

The decision is a DSO action carrying a `decision` of `APPROVED` or `DENIED` and an optional `note` recorded as `decision_note`. A decision against a request no longer in `REQUESTED` status is rejected with `ERR_RCL_NOT_REQUESTED`. Approval additionally requires the parent enrollment still in `PENDING` or `REGISTERED` — approving against an enrollment that has since left those statuses is rejected with `ERR_ENROLLMENT_NOT_REGISTERABLE`; denial carries no such requirement. Approval recomputes the parent enrollment's `effective_min_credits` by category: for `ACADEMIC`, the larger of 3 credits and half the base minimum rounded down; for `MEDICAL`, exactly the approved `requested_credits`, which may be zero; for `FINAL_TERM`, the larger of 1 credit and the requested amount. `APPROVED` and `DENIED` are both terminal.

### 3.5. Employment Authorization: CPT and OPT

Practical training is tracked through `EmploymentAuthorization` resources. A DSO creates one for a student with the `auth_type` — `CPT`, `OPT_PRE`, or `OPT_POST` — the `hours_per_week` (greater than zero), the authorized `start_date`, and the authorized `end_date`, which must be later than the start. `employer_name` is required for `CPT` and optional for the two OPT flavors. New authorizations land in `DRAFT`. Authorizations may be listed with the filters `student_id`, `auth_type`, and `status`; reading a single OPT_POST authorization recomputes its unemployment counters as of the current clock date.

The authorization lifecycle is driven by a transition operation carrying an `action` and, depending on the action, an `outcome` or a `uscis_receipt_number`; a `note` may be supplied with any action but is accepted without being persisted:

- **RECOMMEND** (DSO) moves `DRAFT` to `RECOMMENDED`. It requires the record `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`), an `ISSUED` I-20 for the student (otherwise `ERR_I20_NOT_ISSUED`), and the training window inside legal bounds: for `CPT` and `OPT_PRE`, the `end_date` must fall on or before the record's `program_end_date` (otherwise `ERR_AUTH_WINDOW_INVALID`); for `OPT_POST`, the `start_date` must fall within the window from the day after `program_end_date` through 60 days after it, inclusive (otherwise `ERR_OPT_WINDOW_CLOSED`). An authorization not in `DRAFT` is rejected with `ERR_AUTH_INVALID_STATE`.
- **REVISE** (DSO) returns a `RECOMMENDED` authorization to `DRAFT` for correction.
- **FILE** (the student, and only on their own authorization — otherwise `ERR_RESOURCE_NOT_OWNED`) moves `RECOMMENDED` to `FILED` and records the `uscis_receipt_number`. Filing applies only to `OPT_PRE` and `OPT_POST`; attempting it on a `CPT` authorization is rejected with `ERR_AUTH_INVALID_STATE`. The clock date at filing must lie within the window from 90 days before `program_end_date` through 60 days after it, inclusive (otherwise `ERR_OPT_WINDOW_CLOSED`).
- **ADJUDICATE** (DSO) carries an `outcome` of `APPROVED` or `DENIED`. The two training flavors adjudicate from different states: a `CPT` authorization moves directly from `RECOMMENDED` to `APPROVED`, while an OPT authorization must pass through `FILED` — adjudicating an OPT authorization still in `RECOMMENDED`, or a CPT authorization from `FILED`, is rejected with `ERR_AUTH_INVALID_STATE`. From `FILED`, `APPROVED` and `DENIED` are both reachable. CPT adjudication only ever reaches `APPROVED`: an `ADJUDICATE` carrying a `DENIED` outcome against a `CPT` authorization is likewise rejected with `ERR_AUTH_INVALID_STATE`. When an `OPT_POST` authorization reaches `APPROVED`, its unemployment day counters begin accruing from its `start_date`.
- **CANCEL** (DSO) abandons an authorization still in `DRAFT` or `RECOMMENDED`, moving it to `CANCELLED`.

`DENIED`, `CANCELLED`, `COMPLETED`, and `REVOKED` are terminal. An `APPROVED` authorization whose `end_date` has passed flips to `COMPLETED` under the clock sweep, as does every `APPROVED` authorization when its student's record completes.

Unemployment accounting applies only to `OPT_POST` authorizations in `APPROVED` or `COMPLETED` status — authorizations in any other status, including `REVOKED`, report zero counters — and it is maintained through `EmploymentPeriod` resources reported under the authorization; each period is bound to its parent through the system-set `authorization_id`. A period carries the `employer_name`, an inclusive `start_date`, an inclusive `end_date` that may be left unset to mark the job ongoing, and the weekly `hours_per_week`. A period may be reported only while the parent authorization is `APPROVED` — reporting against any other status is rejected with `ERR_AUTH_INVALID_STATE` — and this applies to every authorization type; periods reported on a non-`OPT_POST` authorization are accepted but leave the unemployment counters at zero. Periods of one authorization follow day-coverage semantics: no two periods may share a calendar day, while a period starting exactly one day after another period's end is permitted as zero-gap adjacency; a violation is rejected with `ERR_EMPLOYMENT_PERIOD_OVERLAP`. An ongoing period (no `end_date`) is treated as open-ended for this check, so it overlaps any period starting on or after its own start date. An erroneously reported period may be deleted by a DSO, and both reporting and deletion recompute the authorization's unemployment counters; the authorization's `updated_at` and `version` advance on reporting or deletion only when those counters actually change.

Two counters are exposed on the authorization. `unemployment_days_settled` counts through yesterday only: the elapsed figure is the number of days from the authorization's `start_date` through yesterday inclusive — zero if yesterday precedes the start — and the covered figure is the number of distinct calendar days lying within at least one employment period, clipped to the span from the authorization's `start_date` through the same horizon, with an ongoing period contributing through the horizon. The settled counter is elapsed minus covered. `unemployment_days_as_of` is the same computation with today as the horizon, so it counts an uncovered current day and therefore runs exactly one day ahead of the settled figure whenever today is uncovered. For either variant, elapsed always equals covered plus unemployment, and adding then deleting a period leaves the counters unchanged.

The clock sweep watches the settled counter of each `APPROVED` `OPT_POST` authorization: when `unemployment_days_settled` exceeds 90 days, the system opens an `UNEMPLOYMENT_LIMIT_EXCEEDED` violation in `OPEN` status for the student — at most one at a time, so the opening is skipped while such a violation is already `OPEN` or `REINSTATEMENT_PENDING` for that student. The 75-day mark feeds the student's `compliance_posture`, as described in §2.10.

### 3.6. Travel Endorsements

A travel endorsement is the re-entry signature placed on an issued I-20. A DSO issues one against an `ISSUED` form by supplying the intended `travel_departure_date` and `travel_return_date` — the return must fall on or after the departure — together with the OCC token `expected_i20_form_version` described in §2.8. Endorsement issuance is a reprint of the form: it increments the I20Form's `version` by one.

Travel windows on one form follow closed-interval semantics: any intersection with the window of another `ACTIVE` endorsement counts as overlap, and touching endpoints — a new departure equal to an existing endorsement's return date — also count as overlap. A conflicting request is rejected with `ERR_ENDORSEMENT_WINDOW_OVERLAP`.

Each endorsement is bound to its parent form through the system-set `i20_form_id`. The endorsement's `valid_until` is computed at creation. When the student holds any `OPT_POST` authorization in `APPROVED` or `COMPLETED` status, the validity horizon is 6 months from the issue date — the server's logical clock date at issuance — and otherwise it is 12 months, with month arithmetic clamping to month end. The endorsement lands in `ACTIVE` status. Advisory re-entry guidance treats the signature as valid for return while the clock date is on or before `valid_until` and the endorsement remains `ACTIVE`.

Endorsements end in one of two terminal states. The clock sweep moves an `ACTIVE` endorsement to `EXPIRED` once the clock passes `valid_until`. And whenever the parent form is superseded or cancelled, each of its `ACTIVE` endorsements is voided to `VOIDED` — this is how both the program-extension auto-issue in §3.8 and record termination in §3.9 retire outstanding signatures.

### 3.7. Transfers Out and In

A student moving between schools is handled through `TransferRequest` resources carrying a `direction` of `OUT` or `IN`, the other institution's `target_school_code`, and a `release_date` — for an outbound transfer, the date the record is released to the new school; for an inbound one, the date the student is expected. Outbound requests require the student's record `ACTIVE` at creation and a `release_date` on or after the current clock date; inbound requests merely record the expectation. New requests land in `REQUESTED`.

The clock sweep releases outbound transfers: when the clock date reaches the `release_date` of a `REQUESTED` outbound transfer, the transfer moves to `RELEASED` and the student's SEVIS record transitions from `ACTIVE` to `TRANSFERRED_OUT`. That record transition flips each of the student's `PENDING` enrollments to `NOT_ENROLLED`, and each flip recomputes the student's `compliance_posture`. If the record is no longer `ACTIVE` when the release date is reached, the transfer still moves to `RELEASED`, but no record transition or enrollment flip occurs.

A request that has not yet been released may be withdrawn: cancellation by a DSO requires the transfer still `REQUESTED` and the clock date strictly before the `release_date`, and moves it to `CANCELLED`. A transfer already released, already cancelled, or whose release date has been reached is rejected with `ERR_TRANSFER_NOT_CANCELLABLE`. `RELEASED` and `CANCELLED` are terminal.

### 3.8. Program Extensions

When a student cannot finish by the current program end date, a DSO files a `ProgramExtension` with the requested `new_program_end_date`, the academic `reason`, and the OCC token `expected_sevis_record_version` described in §2.8 — the token must equal the record's current `version`, and a stale token is rejected with `ERR_STALE_VERSION` before anything else is examined. Filing requires the student to already have a SEVIS record — its absence is rejected with `ERR_NOT_FOUND` before the version check — and that record must be `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`). The new end date must be strictly later than the record's current `program_end_date` (otherwise `ERR_EXTENSION_NOT_FORWARD`). Filing the request lands it in `REQUESTED` and increments the SEVIS record's `version` by one.

The approval decision is guarded by timing and funding. Approving an extension requires the request in `REQUESTED` (otherwise `ERR_EXTENSION_NOT_REQUESTED`), the student's record `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`), and the clock date on or before the current `program_end_date` — an extension decided after the program has already ended is rejected with `ERR_EXTENSION_WINDOW_CLOSED`. The funding check reuses the verified-fresh-funding computation of §3.2: verified documents within the 183-day freshness window must cover the prorated extension cost, with a shortfall rejected as `ERR_INSUFFICIENT_VERIFIED_FUNDING` (HTTP 402). Denial requires only the `REQUESTED` state; both decisions accept an optional `note` recorded as `decision_note`, and both outcomes are terminal.

The prorated extension cost is computed from the currently `ISSUED` I-20's cost lines — when several `ISSUED` forms exist for the record, the most recently created one is the basis; when none exists, every prorated line is zero and the funding check runs against a zero total. The day gap between the current `program_end_date` and the `new_program_end_date` is converted to whole months by dividing by 30 and rounding up. Each of the four lines — tuition, living, insurance, other — is treated as an annual basis: the line's cents figure is multiplied by the extended month count, divided by 12, and rounded half-up to whole cents, line by line. The replacement form's `estimated_total_cents` is then the integer sum of those four already-rounded lines. The ordering is contractual — per-line rounding first, then summation; summing raw prorated values and rounding once would produce a different cent total.

Approval executes a coordinated multi-entity update. The record's `program_end_date` advances to the approved `new_program_end_date`, and the record's `version` increments again. A new I-20 is auto-created and immediately issued with the prorated cost lines, naming the most recently created previously issued form as its `supersedes_i20_form_id` (unset when there was none); it inherits that form's `program_name` (empty when there was none), carries the record's `program_start_date` and the approved `new_program_end_date`, and snapshots the approval-time funding figures. Every `ISSUED` form of the record then transitions from `ISSUED` to `SUPERSEDED`, and each such form's `ACTIVE` travel endorsements are voided to `VOIDED`.

### 3.9. Termination, Violations, and Reinstatement

Termination of an `ACTIVE` SEVIS record is a `PDSO`-exclusive action carrying a `termination_reason`. Attempting it on a record not in `ACTIVE` is rejected with `ERR_RECORD_NOT_ACTIVE`; attempting it as a `DSO` is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. Termination cascades in one coherent step: every employment authorization of the student in `DRAFT`, `RECOMMENDED`, `FILED`, or `APPROVED` transitions to `REVOKED`; the currently `ISSUED` I-20 of the record transitions to `CANCELLED`; and cancelling that form voids each of its `ACTIVE` travel endorsements to `VOIDED`. Each revocation recomputes the student's `compliance_posture`.

Violations are tracked through `StatusViolation` resources, opened by a DSO with a `violation_type` of `FAILURE_TO_ENROLL`, `UNAUTHORIZED_EMPLOYMENT`, `UNEMPLOYMENT_LIMIT_EXCEEDED`, `ADDRESS_REPORT_OVERDUE`, or `OTHER`, plus a free-text `description`. New violations land in `OPEN`, and their creation recomputes the student's `compliance_posture` — per §2.10, any open violation drives the posture to `VIOLATION_OPEN`. The system also opens violations on its own in two places already described: the registration-deadline sweep opens `FAILURE_TO_ENROLL`, and the unemployment sweep opens `UNEMPLOYMENT_LIMIT_EXCEEDED`.

The violation lifecycle is driven by a transition operation:

- **RECOMMEND_REINSTATEMENT** (DSO) moves an `OPEN` violation to `REINSTATEMENT_PENDING`. It is only meaningful when the student's record is `TERMINATED` — otherwise the request is rejected with `ERR_RECORD_NOT_TERMINATED` — and it flips that record from `TERMINATED` to `REINSTATEMENT_PENDING` as it lands. A violation not in `OPEN` is rejected with `ERR_VIOLATION_INVALID_STATE`.
- **RESOLVE** (`PDSO` only) carries an `outcome` of `REINSTATED` or `DENIED` against a violation in `REINSTATEMENT_PENDING` (otherwise `ERR_VIOLATION_INVALID_STATE`). A `REINSTATED` outcome moves the violation to `RESOLVED_REINSTATED` and flips the record from `REINSTATEMENT_PENDING` back to `ACTIVE`; a `DENIED` outcome moves the violation to `RESOLVED_DENIED` and returns the record to `TERMINATED`. Both resolutions recompute the student's `compliance_posture`.
- **DISMISS** (DSO) closes an `OPEN` violation as `DISMISSED` and recomputes the student's `compliance_posture`.

`RESOLVED_REINSTATED`, `RESOLVED_DENIED`, and `DISMISSED` are terminal. Note the asymmetry of authority: recommending reinstatement and dismissing a violation sit with the general DSO body, but the final resolution of a reinstatement belongs to the principal official alone.

A record left in `ACTIVE` completes under the clock sweep once the clock date passes `program_end_date` plus the 60-day grace period — unless the student holds an `OPT_POST` authorization in `APPROVED` status whose `end_date` is on or after the clock date, in which case post-completion practical training holds the record `ACTIVE`. When the record does complete, every `APPROVED` employment authorization of the student flips to `COMPLETED`, and the student's `compliance_posture` is recomputed. `COMPLETED` and `TRANSFERRED_OUT` are the record's terminal states.

### 3.10. Address Reporting

F-1 regulations require students to report a residential move promptly. An address filing — from a DSO, or from the student for their own record — carries the `move_date`, `address_line1`, `city`, the two-letter uppercase `state_code`, and the `postal_code`. The filing's `status` is computed at creation: it is `REPORTED` when the clock date is no later than 10 days after the `move_date` — filing exactly on the tenth day counts as on time — and `FLAGGED_LATE` otherwise. A late landing recomputes the student's `compliance_posture`, which under §2.10 moves the student to `AT_RISK` in the absence of any open violation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`; the employment-period deletion returns `204 No Content`. All resources are mounted under the `/sevis` prefix, with the clock capability mounted at the server root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock and run due sweeps in fixed order | PDSO, DSO |
| POST | `/sevis/students` | Create a student intake record | PDSO, DSO |
| GET | `/sevis/students/{id}` | Get a student | PDSO, DSO, Student |
| POST | `/sevis/students/{id}/financial-documents` | Submit a financial document for a student | PDSO, DSO, Student |
| GET | `/sevis/students/{id}/financial-documents` | List a student's financial documents | PDSO, DSO, Student |
| POST | `/sevis/financial-documents/{id}/review` | Verify or reject a submitted financial document | PDSO, DSO |
| POST | `/sevis/students/{id}/sevis-records` | Create the student's SEVIS record (1:1) | PDSO, DSO |
| GET | `/sevis/students/{id}/sevis-records` | List the student's SEVIS records | PDSO, DSO, Student |
| POST | `/sevis/sevis-records/{id}/initialize` | Move record DRAFT → INITIAL (requires an ISSUED I-20) | PDSO, DSO |
| POST | `/sevis/sevis-records/{id}/terminate` | Terminate an ACTIVE record; cascades revocation, cancellation, voiding | PDSO |
| POST | `/sevis/students/{id}/i20-forms` | Create a DRAFT I-20 for the student's record | PDSO, DSO |
| GET | `/sevis/i20-forms` | List I-20 forms with filters | PDSO, DSO, Student |
| GET | `/sevis/i20-forms/{id}` | Get an I-20 form | PDSO, DSO, Student |
| POST | `/sevis/i20-forms/{id}/issue` | Issue a DRAFT I-20; snapshots funding; supersedes the named prior form | PDSO, DSO |
| POST | `/sevis/term-enrollments` | Create a term enrollment (unique per student + term_code) | PDSO, DSO |
| GET | `/sevis/term-enrollments` | List term enrollments with filters | PDSO, DSO, Student |
| GET | `/sevis/term-enrollments/{id}` | Get a term enrollment | PDSO, DSO, Student |
| PATCH | `/sevis/term-enrollments/{id}` | Update enrolled_credits while PENDING, or while REGISTERED until add/drop close | PDSO, DSO, Student |
| POST | `/sevis/term-enrollments/{id}/register` | Register the enrollment in SEVIS; first registration activates the record | PDSO, DSO |
| POST | `/sevis/reduced-course-loads` | Request an RCL for an enrollment | PDSO, DSO |
| GET | `/sevis/term-enrollments/{id}/reduced-course-loads` | List RCLs of an enrollment | PDSO, DSO, Student |
| POST | `/sevis/reduced-course-loads/{id}/decision` | Approve or deny a requested RCL | PDSO, DSO |
| POST | `/sevis/employment-authorizations` | Create a CPT/OPT authorization in DRAFT | PDSO, DSO |
| GET | `/sevis/employment-authorizations` | List employment authorizations with filters | PDSO, DSO, Student |
| GET | `/sevis/employment-authorizations/{id}` | Get an employment authorization (recomputes OPT_POST counters) | PDSO, DSO, Student |
| POST | `/sevis/employment-authorizations/{id}/transition` | Drive the authorization state machine (RECOMMEND, REVISE, FILE, ADJUDICATE, CANCEL) | PDSO, DSO, Student |
| POST | `/sevis/employment-authorizations/{id}/employment-periods` | Report an employment period under an authorization | PDSO, DSO, Student |
| GET | `/sevis/employment-authorizations/{id}/employment-periods` | List employment periods of an authorization | PDSO, DSO, Student |
| DELETE | `/sevis/employment-periods/{id}` | Delete an erroneously reported employment period | PDSO, DSO |
| POST | `/sevis/i20-forms/{id}/travel-endorsements` | Issue a travel endorsement on an ISSUED I-20 (OCC on form version) | PDSO, DSO |
| GET | `/sevis/i20-forms/{id}/travel-endorsements` | List travel endorsements of an I-20 | PDSO, DSO, Student |
| POST | `/sevis/students/{id}/transfer-requests` | Create a transfer request (OUT or IN) | PDSO, DSO |
| GET | `/sevis/students/{id}/transfer-requests` | List a student's transfer requests | PDSO, DSO, Student |
| POST | `/sevis/transfer-requests/{id}/cancel` | Cancel a REQUESTED transfer before its release date | PDSO, DSO |
| POST | `/sevis/students/{id}/program-extensions` | Request a program extension (OCC on record version) | PDSO, DSO |
| GET | `/sevis/students/{id}/program-extensions` | List a student's program extensions | PDSO, DSO, Student |
| POST | `/sevis/program-extensions/{id}/decision` | Approve or deny an extension; approval auto-issues a prorated replacement I-20 | PDSO, DSO |
| POST | `/sevis/students/{id}/status-violations` | Open a status violation for a student | PDSO, DSO |
| GET | `/sevis/students/{id}/status-violations` | List a student's status violations | PDSO, DSO, Student |
| POST | `/sevis/status-violations/{id}/transition` | Drive violation lifecycle (RECOMMEND_REINSTATEMENT, RESOLVE, DISMISS) | PDSO, DSO |
| POST | `/sevis/students/{id}/address-reports` | Report a residential address; 10-day timeliness rule applies | PDSO, DSO, Student |
| GET | `/sevis/students/{id}/address-reports` | List a student's address reports | PDSO, DSO, Student |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_RESOURCE_NOT_OWNED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_SEVIS_ID` | 409 Conflict |
| `ERR_RECORD_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_RECORD_NOT_DRAFT` | 409 Conflict |
| `ERR_RECORD_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECORD_NOT_TERMINATED` | 409 Conflict |
| `ERR_NO_ISSUED_I20` | 409 Conflict |
| `ERR_I20_NOT_ISSUED` | 409 Conflict |
| `ERR_I20_NOT_DRAFT` | 409 Conflict |
| `ERR_INSUFFICIENT_VERIFIED_FUNDING` | 402 Payment Required |
| `ERR_ENROLLMENT_NOT_REGISTERABLE` | 409 Conflict |
| `ERR_REGISTRATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_BELOW_FULL_COURSE_LOAD` | 422 Unprocessable Entity |
| `ERR_RCL_NOT_REQUESTED` | 409 Conflict |
| `ERR_RCL_ALREADY_OPEN` | 409 Conflict |
| `ERR_RCL_ADD_DROP_CLOSED` | 409 Conflict |
| `ERR_ADD_DROP_CLOSED` | 409 Conflict |
| `ERR_RCL_NOT_FINAL_TERM` | 409 Conflict |
| `ERR_RCL_CREDITS_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_RCL_REASON_EXHAUSTED` | 409 Conflict |
| `ERR_AUTH_INVALID_STATE` | 409 Conflict |
| `ERR_OPT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_AUTH_WINDOW_INVALID` | 409 Conflict |
| `ERR_EMPLOYMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_ENDORSEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TRANSFER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_EXTENSION_NOT_REQUESTED` | 409 Conflict |
| `ERR_EXTENSION_NOT_FORWARD` | 409 Conflict |
| `ERR_EXTENSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_VIOLATION_INVALID_STATE` | 409 Conflict |
| `ERR_DOCUMENT_ALREADY_REVIEWED` | 409 Conflict |
