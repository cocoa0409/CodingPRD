# Corporate Entity Governance API — Product Requirements Document

## 1. Introduction

Modern corporate secretaries manage an ever-growing portfolio of legal entities across multiple jurisdictions, each with its own filing calendar, franchise-tax regime, and governance rules. Missed annual reports, lapsed registered-agent coverage, or unauthorized signatories can trigger costly penalties, forfeiture of good standing, or involuntary dissolution. This document specifies the Corporate Entity Governance API, a system designed to give the corporate secretary's office a single, auditable source of truth for entity formation, subsidiary ownership, filing compliance, officer appointments, signature authority, and good-standing certificates.

The API is built around a logical-clock model: every time-driven transition — an annual filing becoming overdue, a resolution materializing to effectiveness, a grant expiring, a certificate lapsing — is evaluated against a server-maintained logical clock rather than wall-clock time. This guarantees deterministic behavior for compliance-critical workflows and allows test harnesses to advance time explicitly. All monetary amounts are expressed in integer cents, all dates are ISO calendar dates, and every mutation is immediately visible in the response of the same request.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID` and `X-User-Role`. The system recognizes five roles, spelled exactly as follows: `CorporateSecretary`, `FilingCoordinator`, `AuthorizedOfficer`, `RegisteredAgentUser`, and `ComplianceAuditor`. A request with a missing or malformed header, or with an unrecognized role name, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

Role-to-identity binding is explicit. When `X-User-Role` is `AuthorizedOfficer`, `X-User-ID` must be the `id` of an existing `Officer` record; ownership checks on any resource that references an `Officer` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `RegisteredAgentUser`, `X-User-ID` must be the `id` of an existing `RegisteredAgent` record, and the same comparison rule applies. When `X-User-Role` is `CorporateSecretary`, `FilingCoordinator`, or `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `drafted_by_user_id` on a `Resolution` or `suspended_by_user_id` on a `SignatureAuthorityGrant`) but does not compare it to any entity's `id`.

Access to each operation is restricted by role. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Segregation-of-duties rules further restrict who may complete a two-person control: the adopter of a resolution must differ from its drafter, the acceptor or rejecter of a filing must differ from its submitter, and the reinstater of a suspended grant must differ from its suspender; violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Self-action holder checks require that an officer resigning an appointment present `X-User-ID` equal to that appointment's `officer_id`, and that a registered agent filing a resignation notice present `X-User-ID` equal to that appointment's `agent_id`; mismatches are rejected with `ERR_FORBIDDEN_ACTOR` (HTTP 403).

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many items are skipped; it defaults to 0. All list endpoints sort by `created_at` in ascending order unless otherwise specified. The `meta` object of a list response contains `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits indicating the most recent mutation.
- `version` — an integer that increments by 1 on every mutation of the resource.

`ComplianceEvent` is the sole exception: it is an append-only audit record and carries only `id` and `created_at`; `updated_at` and `version` are absent.

### 2.5. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers, the system validates each identifier from left to right. The request is rejected with a 404 error for the first identifier that does not resolve to an existing resource. Body-supplied foreign keys — such as `jurisdiction_id`, `agent_id`, `officer_id`, `agent_appointment_id`, `parent_entity_id`, `subsidiary_entity_id`, `delegated_from_grant_id`, `supersedes_record_id`, and identifiers inside a resolution's `payload` — are validated for existence after path parameters.

### 2.6. Precision and Rounding

All monetary values are integer cents. Where a calculation produces a fractional cent, the result is rounded to whole cents using round-half-up before any further aggregation. The late-filing penalty calculation rounds each component — the tax component and the report-fee component — to whole cents individually, then sums them and applies the cap. Summing unrounded components and rounding once afterwards is non-conformant. Certificate fees for expedited delivery are computed as 1.5 times the standard certificate fee, rounded half-up to whole cents.

### 2.7. Optimistic Concurrency Control

Two write operations require optimistic concurrency control against the parent `LegalEntity`:

1. Adopting a resolution requires the request body to carry `expected_entity_version`, which must equal the current `version` of the parent `LegalEntity`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. Creating an `OwnershipRecord` requires the request body to carry `expected_entity_version`, which must equal the current `version` of the subsidiary `LegalEntity`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.8. Hierarchical Consistency and Cascading Side Effects

State transitions on a parent entity propagate to dependent children. Dissolving an entity revokes its officer appointments, then revokes the signature grants of those officers, then revokes any delegated grants. A registered-agent resignation that leaves a jurisdiction uncovered triggers a posture recomputation, revokes qualifications in that jurisdiction, and withdraws their future filings. Every such cascade appends a `ComplianceEvent` to the entity's audit trail and increments the entity's `version`.

### 2.9. Segregation of Duties

The system enforces a two-person rule on three control points: resolution adoption versus drafting, filing acceptance or rejection versus submission, and grant reinstatement versus suspension. The same `X-User-ID` may not perform both sides of any of these pairs; violations are rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.10. Validation Ordering

Every request is evaluated against a fixed priority ladder. Authentication and role checks come first (priorities 1 and 2). Existence checks on path and body identifiers come next (priority 3). Body-schema and range validation follow (priority 4). State-machine preconditions are evaluated fifth. Compliance gates and segregation-of-duties checks are sixth. Cross-entity referential checks — such as the presence of an authorizing resolution or an appointed officer — are seventh. Uniqueness and structural constraints — such as duplicate officer emails, overlapping grant windows, and ownership cycles — are eighth. Temporal interval rules — such as coverage continuity and delegation window containment — are ninth. Monetary and aggregate caps are evaluated last (priority 10).

## 3. Business Logic & Workflows

### 3.1. Jurisdictions, Registered Agents, and Officers

A `CorporateSecretary` registers a `Jurisdiction` by supplying `code`, `name`, `annual_report_due_rule`, `grace_period_days`, `franchise_tax_method`, `late_penalty_base_cents`, `late_penalty_cap_cents`, `penalty_day_counting`, `report_fee_cents`, `cert_fee_cents`, `ra_resignation_notice_days`, and `forfeiture_window_days`. When `annual_report_due_rule` is `FIXED_MONTH_DAY`, `annual_report_due_month` and `annual_report_due_day` are required; otherwise both must be null. The `grace_period_days` must be at least 0, `late_penalty_cap_cents` must be at least `late_penalty_base_cents`, and `annual_report_due_month` must be between 1 and 12 inclusive.

A `CorporateSecretary` registers a `RegisteredAgent` by supplying `name`, `jurisdiction_id`, and `address`. The referenced jurisdiction must exist.

A `CorporateSecretary` registers an `Officer` by supplying `full_name` and `email`. The email must be unique; duplicates are rejected with `ERR_DUPLICATE_OFFICER`. An officer begins in `ACTIVE` status. A `CorporateSecretary` may deactivate an officer, transitioning `status` to `DEACTIVATED`; deactivation does not alter existing appointments but blocks future `APPOINT_OFFICER` resolutions from being adopted for that officer.

### 3.2. Entity Registry and Formation

A `CorporateSecretary` creates a `LegalEntity` by supplying `legal_name`, `entity_type`, `formation_jurisdiction_id`, and `formation_date`. The `entity_type` must be one of `CORPORATION`, `LLC`, `LIMITED_PARTNERSHIP`, or `NONPROFIT_CORPORATION`. Optional fields include `fiscal_year_end_month` (default 12) and `authorized_shares` (default 0). The entity begins in `DRAFT` status with `compliance_posture` initialized to `GOOD_STANDING`, `fees_accrued_cents` set to 0, and `version` set to 1.

Submitting the formation package transitions the entity from `DRAFT` to `FORMATION_PENDING`. This step requires an `AUTHORIZE_FORMATION` resolution in `ADOPTED` or `EFFECTIVE` status; otherwise the request is rejected with `ERR_REQUIRED_RESOLUTION_MISSING`. Attempting to submit formation on an entity that is not in `DRAFT` is rejected with `ERR_ENTITY_NOT_DRAFT`.

Confirming formation transitions the entity from `FORMATION_PENDING` to `ACTIVE`. The system requires an `AgentAppointment` covering the entity's formation jurisdiction with status `ACTIVE` or `NOTICE_PENDING` and a `start_date` on or before the current logical date; absence of coverage is rejected with `ERR_AGENT_COVERAGE_GAP`. Upon confirmation, the system generates the initial `AnnualFiling` rows for the formation jurisdiction: one `ANNUAL_REPORT` filing is always generated, and one `FRANCHISE_TAX` filing is generated unless the jurisdiction's `franchise_tax_method` is `NONE`. The first filing `period_year` is the year after `formation_date`. The entity's `compliance_posture` is recomputed, and its `version` increments.

While an entity is `ACTIVE`, a `CorporateSecretary` may update `legal_name`, `authorized_shares`, or `fiscal_year_end_month` via a modification request. Each successful update increments the entity's `version`. Attempting to modify a non-`ACTIVE` entity is rejected with `ERR_ENTITY_NOT_ACTIVE`.

### 3.3. Registered Agent Appointments and Resignation

A `CorporateSecretary` appoints a registered agent for a specific entity and jurisdiction by providing `agent_id`, `jurisdiction_id`, and `start_date`. The referenced `RegisteredAgent` must be authorized in the same jurisdiction as the appointment's `jurisdiction_id`. The appointment begins in `ACTIVE` status with `notice_date` and `effective_end_date` null.

Only one `ACTIVE` appointment may exist per entity and jurisdiction. A second appointment that overlaps an `ACTIVE` incumbent outside a notice window is rejected with `ERR_AGENT_APPOINTMENT_OVERLAP`. When an incumbent is in `NOTICE_PENDING`, a successor appointment's `start_date` must be on or before the incumbent's `effective_end_date`; otherwise the request is rejected with `ERR_AGENT_COVERAGE_GAP`.

A `RegisteredAgentUser` files a resignation notice by presenting `X-User-ID` equal to the appointment's `agent_id`. This transitions the appointment from `ACTIVE` to `NOTICE_PENDING`, sets `notice_date` to the current logical date, and computes `effective_end_date` as `notice_date` plus the jurisdiction's `ra_resignation_notice_days`. Attempting to file notice on a non-`ACTIVE` appointment is rejected with `ERR_AGENT_APPOINTMENT_NOT_ACTIVE`; an actor mismatch is rejected with `ERR_FORBIDDEN_ACTOR`.

Finalizing the resignation — performed by a `CorporateSecretary` — transitions the appointment from `NOTICE_PENDING` to `RESIGNED`. Finalization is blocked until the current logical date is on or after `effective_end_date`; premature finalization is rejected with `ERR_AGENT_RESIGNATION_NOTICE_UNRIPE`. Attempting to finalize a non-`NOTICE_PENDING` appointment is rejected with `ERR_AGENT_APPOINTMENT_NOT_NOTICE_PENDING`. Upon finalization, the system appends a `ComplianceEvent` of type `AGENT_RESIGNED`, recomputes the entity's `compliance_posture`, revokes every `ForeignQualification` in that jurisdiction whose status is `QUALIFIED`, withdraws those qualifications' `SCHEDULED` or `PREPARED` filings, and increments the entity's `version`.

### 3.4. Resolutions and Governance Workflow

Resolutions are drafted under an entity by a `CorporateSecretary` or `FilingCoordinator`. The draft captures `resolution_type`, `payload`, and `effective_date`. The system records `drafted_by_user_id` from `X-User-ID`. A resolution begins in `DRAFT` status.

Submitting a resolution transitions it from `DRAFT` to `SUBMITTED`. Submission is blocked if the parent entity is `DISSOLVED`, in which case the request is rejected with `ERR_ENTITY_ALREADY_DISSOLVED`. A `CorporateSecretary` may return a `SUBMITTED` resolution to `DRAFT` for revision, optionally supplying a `reason`; this loop is unbounded.

Adopting a resolution is the exclusive province of a `CorporateSecretary` and is guarded by three checks in addition to the state gate. First, the resolution must be in `SUBMITTED` status; otherwise the request is rejected with `ERR_RESOLUTION_NOT_SUBMITTED`. Second, the request must carry `expected_entity_version` matching the parent entity's current `version`; a mismatch is rejected with `ERR_STALE_VERSION`. Third, the adopter must differ from the drafter; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. For `APPOINT_OFFICER` resolutions, the referenced officer must be `ACTIVE` and, for single-holder titles, the office must not already be occupied.

Adoption sets `adopted_by_user_id`, transitions the resolution to `ADOPTED`, and increments the parent entity's `version`. The resolution then waits for the logical clock to reach its `effective_date`. When that occurs — either via a system sweep or lazy evaluation on read — the resolution transitions from `ADOPTED` to `EFFECTIVE` and its payload materializes. An `APPOINT_OFFICER` resolution creates the appointment; if a same-title single-holder appointment already exists, the resolution remains `ADOPTED` and a `ComplianceEvent` of type `RESOLUTION_EFFECTIVE_BLOCKED` is appended instead. `REMOVE_OFFICER` and `ACCEPT_RESIGNATION` resolutions transition the referenced appointment to `REMOVED` or `RESIGNED` respectively, set `end_date` to the `effective_date`, and cascade to revoke the officer's grants. `REVOKE_SIGNATURE_AUTHORITY` revokes the referenced grant and its delegated grants. The authorization-type resolutions — `AUTHORIZE_FORMATION`, `AUTHORIZE_DISSOLUTION`, `REVOKE_DISSOLUTION`, `AUTHORIZE_QUALIFICATION`, `AUTHORIZE_WITHDRAWAL` — and `GRANT_SIGNATURE_AUTHORITY` produce no record mutation at `EFFECTIVE`; their purpose is to authorize action endpoints, and `ADOPTED` status alone satisfies those checks.

A `DRAFT` resolution may be withdrawn, transitioning to `WITHDRAWN`. An `ADOPTED` or `EFFECTIVE` resolution may be rescinded by a `CorporateSecretary`. Rescission of an `EFFECTIVE` resolution is permitted only for `APPOINT_OFFICER` and `GRANT_SIGNATURE_AUTHORITY`; other types are rejected with `ERR_RESOLUTION_NOT_RESCINDABLE`. Rescinding an `EFFECTIVE` `APPOINT_OFFICER` resolution removes the created appointment and cascades to grants. Rescinding any `GRANT_SIGNATURE_AUTHORITY` resolution revokes every grant whose `source_resolution_id` matches, including delegated grants. Rescission increments the parent entity's `version`.

### 3.5. Officer Appointments

Appointments are created indirectly through the resolution lifecycle. When an `APPOINT_OFFICER` resolution becomes `EFFECTIVE`, the system creates an `OfficerAppointment` with the `officer_id`, `office_title`, and `start_date` drawn from the resolution's `payload`, and records the originating `resolution_id`. The appointment begins in `APPOINTED` status with `end_date` null. The titles `PRESIDENT`, `SECRETARY`, and `TREASURER` are single-holder offices: adopting an `APPOINT_OFFICER` resolution for one of these titles fails with `ERR_OFFICE_OCCUPIED` if another appointment of the same title at the same entity is already `APPOINTED`. The titles `CEO`, `CFO`, and `DIRECTOR` are not single-holder.

An `AuthorizedOfficer` may resign an appointment by presenting `X-User-ID` equal to the appointment's `officer_id`. Resignation transitions the appointment from `APPOINTED` to `RESIGNED`, sets `end_date` to the current logical date, and triggers the grant cascade described in §3.8. A resignation attempt on a non-`APPOINTED` appointment is rejected with `ERR_APPOINTMENT_NOT_APPOINTED`; a resignation attempt by a user other than the holder is rejected with `ERR_FORBIDDEN_ACTOR`.

Removal of an officer is also resolution-driven. When a `REMOVE_OFFICER` resolution becomes `EFFECTIVE`, the referenced appointment transitions from `APPOINTED` to `REMOVED` with `end_date` set to the resolution's `effective_date`. The same grant cascade applies.

### 3.6. Annual Filing Calendar and Adjudication

The system maintains a filing calendar for each entity. Filings are generated at formation confirmation, at qualification confirmation, and by period rollover when a filing is accepted. Each `AnnualFiling` carries `filing_type` (`ANNUAL_REPORT` or `FRANCHISE_TAX`), `period_year`, `due_date`, `report_fee_cents`, `shares_basis`, `tax_estimated_cents`, `tax_assessed_cents`, `submitted_date`, `submitted_by_user_id`, `days_late`, `penalty_cents`, `fee_cents`, and `status`.

The `due_date` is determined by the jurisdiction's `annual_report_due_rule`. For `FIXED_MONTH_DAY`, the due date is the specified month and day of the `period_year`. For `FORMATION_ANNIVERSARY`, the due date is the anniversary of the entity's `formation_date` in the `period_year`; if the formation date is February 29 and the period year is not a leap year, the due date clamps to February 28. If the computed due date falls on a Saturday or Sunday, it rolls forward to the next Monday. Holidays are not modeled.

A filing begins in `SCHEDULED` status. When the current logical date passes the `due_date`, the filing transitions to `OVERDUE`; a filing on its due date is not yet overdue. Preparing a filing — allowed from `SCHEDULED`, `OVERDUE`, or `REJECTED` — transitions it to `PREPARED` and computes the estimated franchise tax. Preparing an `OVERDUE` filing returns it to `PREPARED`; if it is still past due, the next evaluation flips it back to `OVERDUE`. The prepare response reports the post-transition status. Attempting to prepare from any other status is rejected with `ERR_FILING_NOT_PREPARED`.

Submitting a filing — allowed from `PREPARED` or `OVERDUE` — transitions it to `SUBMITTED`. At submit time, the system computes the actual franchise tax from the entity's current `authorized_shares`, determines `days_late` and `penalty_cents`, and sets `fee_cents` to the sum of `report_fee_cents`, `tax_assessed_cents`, and `penalty_cents`. The submitter's `X-User-ID` is recorded in `submitted_by_user_id`, `submitted_date` is set to the current logical date, and the entity's `fees_accrued_cents` increases by `fee_cents`. Both prepare and submit require the entity to be in `ACTIVE` or `DISSOLUTION_PENDING` status; otherwise the request is rejected with `ERR_ENTITY_NOT_ACTIVE`. Attempting to submit from any other status is rejected with `ERR_FILING_NOT_PREPARED`.

Acceptance and rejection are adjudicated by a `CorporateSecretary` who must differ from the submitter. Acceptance transitions the filing to `ACCEPTED` and generates the next period's filings for the same jurisdiction and filing type, provided none already exist and the entity still owes filings to that jurisdiction. Rejection transitions the filing to `REJECTED` and reverses the fee accrual exactly, decrementing `fees_accrued_cents` by `fee_cents`. Attempting to accept or reject a non-`SUBMITTED` filing is rejected with `ERR_FILING_NOT_SUBMITTED`.

### 3.7. Franchise Tax and Late-Filing Penalty

Franchise tax is computed in two variants. The `ESTIMATED` variant runs at prepare time and uses `shares_basis`: the prior accepted `FRANCHISE_TAX` filing's `shares_basis` for the same entity and jurisdiction, or the entity's `authorized_shares` at formation-confirm time for the first period. The `ACTUAL` variant runs at submit time and uses the entity's current `authorized_shares`. The two diverge whenever shares change between the basis snapshot and submission. For `ANNUAL_REPORT` filings, both variants are zero.

The tax formula depends on entity type and jurisdiction method. For a `NONPROFIT_CORPORATION`, the tax is a flat 2500 cents. For a jurisdiction with `franchise_tax_method` equal to `SHARES_TIERED`, the tax is computed as follows: subtract 5000 free shares from the share count, round up the remainder to whole blocks of 10000 shares, multiply the block count by 8500 cents, add a base of 17500 cents, and cap the result at 2000000 cents. For `FLAT`, the tax is 17500 cents. For `NONE`, no `FRANCHISE_TAX` filing is generated.

Late penalties accrue only after the jurisdiction's grace period. The grace end is `due_date` plus `grace_period_days`. `days_late` counts the days in the half-open interval from the day after grace end through `submitted_date`, inclusive of the submission day. When the jurisdiction's `penalty_day_counting` is `CALENDAR_DAYS`, every day in that interval counts. When it is `BUSINESS_DAYS`, only Monday through Friday count; identical submit dates yield a smaller `days_late` whenever the interval spans a weekend. If `days_late` is zero, `penalty_cents` is zero. Otherwise, the penalty is the lesser of the jurisdiction's `late_penalty_cap_cents` and the sum of the jurisdiction's `late_penalty_base_cents`, a tax component, and a report-fee component. The tax component is `tax_assessed_cents` multiplied by 0.00037 and then by `days_late`, rounded half-up to whole cents. The report-fee component is `report_fee_cents` multiplied by 0.00041 and then by `days_late`, rounded half-up to whole cents. The rounding of each component occurs before summation and application of the cap.

### 3.8. Foreign Qualification and Withdrawal

A `CorporateSecretary` applies for foreign qualification by providing `jurisdiction_id` and `agent_appointment_id`. The jurisdiction must differ from the entity's formation jurisdiction. The referenced `AgentAppointment` must cover the entity and jurisdiction with status `ACTIVE`. The entity's `compliance_posture` must be `GOOD_STANDING`; otherwise the request is rejected with `ERR_POSTURE_NOT_GOOD_STANDING`. An `AUTHORIZE_QUALIFICATION` resolution in `ADOPTED` or `EFFECTIVE` status must exist; otherwise the request is rejected with `ERR_REQUIRED_RESOLUTION_MISSING`. A duplicate qualification for the same entity and jurisdiction in `PENDING`, `QUALIFIED`, or `WITHDRAWAL_PENDING` status is rejected with `ERR_QUALIFICATION_EXISTS`.

The qualification begins in `PENDING` status. Confirming it transitions to `QUALIFIED`, sets `qualified_date`, and generates the jurisdiction's filing calendar: an `ANNUAL_REPORT` filing always, and a `FRANCHISE_TAX` filing unless the jurisdiction's `franchise_tax_method` is `NONE`. The first generated period is the year after `formation_date` if that year is not already past; otherwise the period containing the current logical date. Attempting to confirm a non-`PENDING` qualification is rejected with `ERR_QUALIFICATION_NOT_PENDING`.

Withdrawal is a three-step cycle. Commencing withdrawal transitions from `QUALIFIED` to `WITHDRAWAL_PENDING` and requires an `AUTHORIZE_WITHDRAWAL` resolution with matching `jurisdiction_id` in `ADOPTED` or `EFFECTIVE` status. Attempting to commence withdrawal on a non-`QUALIFIED` qualification is rejected with `ERR_QUALIFICATION_NOT_QUALIFIED`. Aborting withdrawal returns the qualification to `QUALIFIED`. Finalizing withdrawal transitions to `WITHDRAWN` after exit clearance: no filing of this entity in this jurisdiction may be in `OVERDUE`, `SUBMITTED`, or `REJECTED` status; otherwise the request is rejected with `ERR_EXIT_CLEARANCE_FAILED`. Attempting to finalize or abort from a non-`WITHDRAWAL_PENDING` status is rejected with `ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING`. Finalization withdraws any remaining `SCHEDULED` or `PREPARED` filings in the jurisdiction and recomputes posture.

A qualification may also be revoked by the system when agent coverage is lost in its jurisdiction. Revocation transitions the qualification to `REVOKED`, appends a `ComplianceEvent` of type `QUALIFICATION_REVOKED`, and withdraws its future filings.

### 3.9. Signature Authority Grants and Delegation

A `CorporateSecretary` creates a `SignatureAuthorityGrant` by providing `officer_id`, `scope`, `max_amount_cents`, `effective_date`, and `expiry_date`. The `scope` must be one of `BANKING`, `CONTRACTS`, `TAX_FILINGS`, or `GOVERNMENT_FILINGS`. The officer must hold an `APPOINTED` appointment at the entity; otherwise the request is rejected with `ERR_OFFICER_NOT_APPOINTED`. A `GRANT_SIGNATURE_AUTHORITY` resolution in `ADOPTED` or `EFFECTIVE` status must exist; the grant records its `source_resolution_id`. The grant begins in `ACTIVE` status.

The grant's validity window is half-open: it includes `effective_date` and excludes `expiry_date`. `expiry_date` must be strictly later than `effective_date`. `max_amount_cents` must be greater than 0. No two grants for the same entity, officer, and scope may have overlapping windows among `ACTIVE` and `SUSPENDED` statuses; adjacency — where one grant's `expiry_date` equals another's `effective_date` — is permitted. Overlaps are rejected with `ERR_GRANT_WINDOW_OVERLAP`.

A grant may delegate authority by referencing `delegated_from_grant_id`. The delegator must be a direct grant — delegation depth is at most 2 — and must be `ACTIVE` and belong to the same entity. The delegated grant's window must be contained within the delegator's window, and its `max_amount_cents` must not exceed the delegator's `max_amount_cents`. Violations are rejected with `ERR_DELEGATION_DEPTH_EXCEEDED`, `ERR_DELEGATOR_GRANT_INVALID`, `ERR_DELEGATOR_WINDOW_INSUFFICIENT`, or `ERR_DELEGATION_LIMIT_EXCEEDED` respectively.

Suspension is performed by a `ComplianceAuditor` or `CorporateSecretary` and transitions the grant from `ACTIVE` to `SUSPENDED`, recording `suspended_by_user_id`. Attempting to suspend a non-`ACTIVE` grant is rejected with `ERR_GRANT_NOT_ACTIVE`. Reinstatement is performed by a `CorporateSecretary` who must differ from the suspender; it clears `suspended_by_user_id` and returns the grant to `ACTIVE`. Attempting to reinstate a non-`SUSPENDED` grant is rejected with `ERR_GRANT_NOT_SUSPENDED`. Revocation transitions a grant from `ACTIVE` or `SUSPENDED` to `REVOKED` and cascades to any grants that delegate from it. Attempting to revoke a grant that is already terminal is rejected with `ERR_GRANT_ALREADY_TERMINAL`. A grant also transitions to `EXPIRED` when the logical clock reaches its `expiry_date`.

Verification of signature authority is a computed read. Given `entity_id`, `officer_id`, `scope`, `amount_cents`, and `as_of_date`, the system identifies the single `ACTIVE` grant matching the entity, officer, and scope whose half-open window covers `as_of_date`. If none exists, the result is unauthorized with `effective_limit_cents` of 0. If the grant is direct, `effective_limit_cents` is its `max_amount_cents`. If the grant is delegated, the delegator must itself be `ACTIVE` and its window must cover `as_of_date`; otherwise the result is unauthorized. When both are valid, `effective_limit_cents` is the smaller of the two `max_amount_cents` values. Authorization is granted when `effective_limit_cents` is greater than 0 and `amount_cents` is less than or equal to `effective_limit_cents`; equality is authorized.

### 3.10. Good-Standing Certificates

A `CorporateSecretary` requests a good-standing certificate by providing `jurisdiction_id` and `delivery_speed`. The entity's `compliance_posture` must be `GOOD_STANDING` at request time; otherwise the request is rejected with `ERR_POSTURE_NOT_GOOD_STANDING`. The certificate begins in `REQUESTED` status with `requested_date` set to the current logical date. The `fee_cents` is computed from the jurisdiction's `cert_fee_cents`: the full amount for `STANDARD` delivery, or 1.5 times that amount rounded half-up to whole cents for `EXPEDITED` delivery.

Issuing a certificate transitions it from `REQUESTED` to `ISSUED`. The issuing `CorporateSecretary` re-verifies that the entity's `compliance_posture` is `GOOD_STANDING`; a drop is rejected with `ERR_POSTURE_NOT_GOOD_STANDING`. Upon issuance, `issued_date` is set to the current logical date and `valid_until` is set to `issued_date` plus 90 calendar days. A certificate may be denied while `REQUESTED`, either manually by a `CorporateSecretary` supplying a `reason`, or automatically by the system when the entity's posture leaves `GOOD_STANDING`. Denial sets `denial_reason` — to the supplied `reason` for a manual denial, or to `POSTURE_LOST` for a system-initiated denial — and appends a `ComplianceEvent` of type `CERTIFICATE_DENIED`. An issued certificate transitions to `EXPIRED` when the logical clock passes `valid_until`. Attempting to issue or deny a non-`REQUESTED` certificate is rejected with `ERR_CERTIFICATE_NOT_REQUESTED`.

### 3.11. Ownership Chart and Consolidation

Ownership edges are created by a `CorporateSecretary` providing `parent_entity_id`, `subsidiary_entity_id`, `percentage_bps`, and `effective_date`. The parent and subsidiary must differ; self-ownership is rejected with `ERR_SELF_OWNERSHIP`. Both entities must be `ACTIVE`; otherwise the request is rejected with `ERR_ENTITY_NOT_ACTIVE`. The request must carry `expected_entity_version` matching the subsidiary's current `version`; a mismatch is rejected with `ERR_STALE_VERSION`. The `percentage_bps` must be between 1 and 10000 inclusive.

The ownership graph among `ACTIVE` records must remain acyclic; a record that would create a cycle is rejected with `ERR_OWNERSHIP_CYCLE`. For every calendar date, the sum of `percentage_bps` over the subsidiary's `ACTIVE` records whose half-open windows cover that date must not exceed 10000; violations are rejected with `ERR_OWNERSHIP_TOTAL_EXCEEDED`.

A record may supersede an existing record by referencing `supersedes_record_id`. The superseded record transitions to `SUPERSEDED` and its `end_date` is set to the new record's `effective_date`. A record may also be voided, transitioning to `VOIDED` and freeing its percentage from the subsidiary's aggregate at all covered dates. Attempting to void a non-`ACTIVE` record is rejected with `ERR_OWNERSHIP_RECORD_NOT_ACTIVE`.

The ownership chart is a computed read from a root entity. It traverses the directed graph of `ACTIVE` ownership records whose windows cover the current logical date. Each edge contributes its direct `percentage_bps`. Each node carries a `look_through_percentage_bps` computed as the sum over all directed paths from the root of the product of edge percentages, with integer division truncating toward zero applied per edge in path order. The root node is emitted with depth 0 and `look_through_percentage_bps` null. Traversal is breadth-first; nodes at equal depth are ordered by the edge's `effective_date` ascending, then by the edge's `created_at` ascending.

### 3.12. Dissolution and Entity Termination

Commencing dissolution transitions an entity from `ACTIVE` to `DISSOLUTION_PENDING`. This requires an `AUTHORIZE_DISSOLUTION` resolution in `ADOPTED` or `EFFECTIVE` status and requires every `ForeignQualification` of the entity to be in `WITHDRAWN` or `REVOKED` status; open qualifications are rejected with `ERR_OPEN_QUALIFICATIONS_EXIST`. Attempting to commence dissolution on a non-`ACTIVE` entity is rejected with `ERR_ENTITY_NOT_ACTIVE`. Commencement withdraws all `SCHEDULED` and `PREPARED` filings, appends a `ComplianceEvent` of type `DISSOLUTION_COMMENCED`, and increments the entity's `version`.

While `DISSOLUTION_PENDING`, a `CorporateSecretary` may revoke the dissolution, returning the entity to `ACTIVE`. This requires a `REVOKE_DISSOLUTION` resolution in `ADOPTED` or `EFFECTIVE` status. Attempting to revoke from a non-`DISSOLUTION_PENDING` status is rejected with `ERR_ENTITY_NOT_DISSOLUTION_PENDING`. Filings withdrawn at commencement remain `WITHDRAWN`; new periods are generated only by future acceptance-driven rollovers.

Finalizing dissolution transitions the entity from `DISSOLUTION_PENDING` to `DISSOLVED`. Finalization is blocked if any filing is in `SCHEDULED`, `PREPARED`, `OVERDUE`, `SUBMITTED`, or `REJECTED` status, or if any certificate is in `REQUESTED` status; such requests are rejected with `ERR_DISSOLUTION_BLOCKED`. Attempting to finalize from a non-`DISSOLUTION_PENDING` status is rejected with `ERR_ENTITY_NOT_DISSOLUTION_PENDING`. Upon finalization, `dissolved_date` is set to the current logical date, every `APPOINTED` appointment transitions to `REMOVED` with `end_date` set, every grant of those officers transitions to `REVOKED`, delegated grants are revoked, a `ComplianceEvent` of type `DISSOLUTION_COMPLETED` is appended, posture is recomputed, and the entity's `version` increments.

### 3.13. Compliance Posture Derivation

An entity's `compliance_posture` is derived on every read, every sweep, and as a gate inside qualification creation, certificate request, and certificate issue. The derivation first applies lazy overdue evaluation: filings in `SCHEDULED` or `PREPARED` whose `due_date` is before the current logical date become `OVERDUE`.

The registered jurisdictions of an entity are its formation jurisdiction while the entity is `ACTIVE` or `DISSOLUTION_PENDING`, plus the jurisdictions of its qualifications in `PENDING`, `QUALIFIED`, or `WITHDRAWAL_PENDING` status. Coverage is lost in a registered jurisdiction when no `AgentAppointment` covers it with status `ACTIVE` or `NOTICE_PENDING`, `start_date` on or before today, and — for `NOTICE_PENDING` appointments — `effective_end_date` on or after today. A hard overdue exists when any filing is `OVERDUE` and today is strictly more than 30 days past the filing's `due_date` plus the jurisdiction's `grace_period_days`.

If coverage is lost or a hard overdue exists, the entity is in a suspended condition. If `suspended_since` is null, it is set to today. If today is on or after `suspended_since` plus the formation jurisdiction's `forfeiture_window_days`, posture becomes `FORFEITED`; otherwise it becomes `SUSPENDED`. If neither condition holds, `suspended_since` is cleared, and posture is `DELINQUENT` if any filing is `OVERDUE`, else `GOOD_STANDING`.

### 3.14. Compliance Events and Audit Trail

Every significant mutation appends a `ComplianceEvent` to the entity's audit trail. The event carries `entity_id`, `event_type`, `payload`, and `occurred_at`. The `event_type` is one of `POSTURE_CHANGED`, `FILING_OVERDUE`, `FILING_WITHDRAWN`, `QUALIFICATION_REVOKED`, `GRANT_REVOKED`, `CERTIFICATE_DENIED`, `OFFICER_REMOVED`, `OFFICER_RESIGNED`, `AGENT_RESIGNED`, `DISSOLUTION_COMMENCED`, `DISSOLUTION_COMPLETED`, or `RESOLUTION_EFFECTIVE_BLOCKED`. The `occurred_at` timestamp is drawn from the logical clock. The audit trail is append-only and is returned in ascending `occurred_at` order, then ascending `created_at` order.

### 3.15. Time-Driven Transitions and the System Sweep

The server maintains a logical clock. On startup and before any clock-adjustment call, the logical clock reads exactly 2026-08-01T00:00:00Z. Fields typed as dates are ISO calendar dates, and date comparisons use the calendar date of the logical clock in UTC.

Time-driven transitions materialize in two ways: when the system sweep runs, and lazily whenever an affected resource is returned by a read or is the target of a mutation. Both paths apply the identical rule against the logical clock. The sweep response reports `filings_marked_overdue`, `resolutions_made_effective`, `resolutions_blocked`, `grants_expired`, `certificates_expired`, `certificates_auto_denied`, and `posture_changes`. Clock adjustment is an administrative capability restricted to `CorporateSecretary` and accepts `to_iso8601`.

## 4. Endpoint Definitions

Operations that create new resources return 201 Created. Operations that modify existing resources return 200 OK. All endpoints are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | CorporateSecretary |
| POST | `/_system/sweep` | Materialize all time-driven transitions | CorporateSecretary |
| POST | `/api/jurisdictions` | Register a jurisdiction | CorporateSecretary |
| GET | `/api/jurisdictions` | List jurisdictions | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/jurisdictions/{jurisdictionId}` | Get a jurisdiction | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/registered-agents` | Register a registered agent | CorporateSecretary |
| GET | `/api/registered-agents` | List registered agents | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/registered-agents/{agentId}` | Get a registered agent | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/officers` | Register an officer/director | CorporateSecretary |
| GET | `/api/officers` | List officers | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/officers/{officerId}` | Get an officer | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/officers/{officerId}/deactivate` | Deactivate an officer | CorporateSecretary |
| POST | `/api/entities` | Create a LegalEntity in DRAFT | CorporateSecretary |
| GET | `/api/entities` | List entities | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/entities/{entityId}` | Get an entity | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| PATCH | `/api/entities/{entityId}` | Update legal_name, authorized_shares, or fiscal_year_end_month | CorporateSecretary |
| POST | `/api/entities/{id}/submit-formation` | DRAFT to FORMATION_PENDING | CorporateSecretary |
| POST | `/api/entities/{id}/confirm-formation` | FORMATION_PENDING to ACTIVE | CorporateSecretary |
| POST | `/api/entities/{id}/commence-dissolution` | ACTIVE to DISSOLUTION_PENDING | CorporateSecretary |
| POST | `/api/entities/{id}/finalize-dissolution` | DISSOLUTION_PENDING to DISSOLVED | CorporateSecretary |
| POST | `/api/entities/{id}/revoke-dissolution` | DISSOLUTION_PENDING to ACTIVE | CorporateSecretary |
| POST | `/api/entities/{id}/agent-appointments` | Appoint a registered agent | CorporateSecretary |
| GET | `/api/agent-appointments` | List agent appointments | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/agent-appointments/{appointmentId}` | Get an agent appointment | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/agent-appointments/{appointmentId}/file-resignation-notice` | Agent files resignation notice | RegisteredAgentUser |
| POST | `/api/agent-appointments/{appointmentId}/finalize-resignation` | Finalize agent resignation | CorporateSecretary |
| POST | `/api/entities/{id}/resolutions` | Draft a resolution | CorporateSecretary, FilingCoordinator |
| GET | `/api/resolutions` | List resolutions | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/resolutions/{resolutionId}` | Get a resolution | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/resolutions/{resolutionId}/submit` | DRAFT to SUBMITTED | CorporateSecretary, FilingCoordinator |
| POST | `/api/resolutions/{resolutionId}/return` | SUBMITTED to DRAFT | CorporateSecretary |
| POST | `/api/resolutions/{resolutionId}/adopt` | SUBMITTED to ADOPTED | CorporateSecretary |
| POST | `/api/resolutions/{resolutionId}/withdraw` | DRAFT to WITHDRAWN | CorporateSecretary, FilingCoordinator |
| POST | `/api/resolutions/{resolutionId}/rescind` | ADOPTED or EFFECTIVE to RESCINDED | CorporateSecretary |
| GET | `/api/officer-appointments` | List officer appointments | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/officer-appointments/{appointmentId}` | Get an officer appointment | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/officer-appointments/{appointmentId}/resign` | Holder resigns appointment | AuthorizedOfficer |
| GET | `/api/filings` | List filings | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/filings/{filingId}` | Get a filing | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/filings/{filingId}/prepare` | Prepare a filing | FilingCoordinator, CorporateSecretary |
| POST | `/api/filings/{filingId}/submit` | Submit a filing | FilingCoordinator, CorporateSecretary |
| POST | `/api/filings/{filingId}/accept` | Accept a filing | CorporateSecretary |
| POST | `/api/filings/{filingId}/reject` | Reject a filing | CorporateSecretary |
| POST | `/api/entities/{id}/qualifications` | Apply for foreign qualification | CorporateSecretary |
| GET | `/api/qualifications` | List foreign qualifications | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/qualifications/{qualificationId}` | Get a foreign qualification | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/qualifications/{qualificationId}/confirm` | PENDING to QUALIFIED | CorporateSecretary |
| POST | `/api/qualifications/{qualificationId}/commence-withdrawal` | QUALIFIED to WITHDRAWAL_PENDING | CorporateSecretary |
| POST | `/api/qualifications/{qualificationId}/finalize-withdrawal` | WITHDRAWAL_PENDING to WITHDRAWN | CorporateSecretary |
| POST | `/api/qualifications/{qualificationId}/abort-withdrawal` | WITHDRAWAL_PENDING to QUALIFIED | CorporateSecretary |
| POST | `/api/entities/{id}/signature-grants` | Create a signature authority grant | CorporateSecretary |
| GET | `/api/signature-grants` | List signature grants | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/signature-grants/{grantId}` | Get a signature grant | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/signature-grants/verify` | Verify effective signature authority | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, ComplianceAuditor |
| POST | `/api/signature-grants/{grantId}/suspend` | ACTIVE to SUSPENDED | ComplianceAuditor, CorporateSecretary |
| POST | `/api/signature-grants/{grantId}/reinstate` | SUSPENDED to ACTIVE | CorporateSecretary |
| POST | `/api/signature-grants/{grantId}/revoke` | ACTIVE or SUSPENDED to REVOKED | CorporateSecretary |
| POST | `/api/entities/{id}/certificate-requests` | Request a good-standing certificate | CorporateSecretary |
| GET | `/api/certificates` | List certificates | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/certificates/{certificateId}` | Get a certificate | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/certificates/{certificateId}/issue` | REQUESTED to ISSUED | CorporateSecretary |
| POST | `/api/certificates/{certificateId}/deny` | REQUESTED to DENIED | CorporateSecretary |
| POST | `/api/ownership-records` | Create an ownership edge | CorporateSecretary |
| GET | `/api/ownership-records` | List ownership records | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/ownership-records/{recordId}` | Get an ownership record | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| POST | `/api/ownership-records/{recordId}/void` | Void an ownership record | CorporateSecretary |
| GET | `/api/entities/{id}/ownership-chart` | Computed org chart from this root | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |
| GET | `/api/entities/{id}/compliance-events` | Append-only audit trail for the entity | CorporateSecretary, FilingCoordinator, AuthorizedOfficer, RegisteredAgentUser, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_FORBIDDEN_ACTOR | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ENTITY_NOT_FOUND | 404 |
| ERR_JURISDICTION_NOT_FOUND | 404 |
| ERR_AGENT_NOT_FOUND | 404 |
| ERR_OFFICER_NOT_FOUND | 404 |
| ERR_APPOINTMENT_NOT_FOUND | 404 |
| ERR_RESOLUTION_NOT_FOUND | 404 |
| ERR_FILING_NOT_FOUND | 404 |
| ERR_QUALIFICATION_NOT_FOUND | 404 |
| ERR_GRANT_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_OWNERSHIP_RECORD_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_ENTITY_NOT_DRAFT | 409 |
| ERR_ENTITY_NOT_FORMATION_PENDING | 409 |
| ERR_ENTITY_NOT_ACTIVE | 409 |
| ERR_ENTITY_NOT_DISSOLUTION_PENDING | 409 |
| ERR_ENTITY_ALREADY_DISSOLVED | 409 |
| ERR_REQUIRED_RESOLUTION_MISSING | 422 |
| ERR_RESOLUTION_NOT_DRAFT | 409 |
| ERR_RESOLUTION_NOT_SUBMITTED | 409 |
| ERR_RESOLUTION_NOT_ADOPTED | 409 |
| ERR_RESOLUTION_NOT_RESCINDABLE | 409 |
| ERR_OFFICE_OCCUPIED | 409 |
| ERR_OFFICER_NOT_ACTIVE | 409 |
| ERR_OFFICER_NOT_APPOINTED | 422 |
| ERR_DUPLICATE_OFFICER | 409 |
| ERR_FILING_NOT_PREPARED | 409 |
| ERR_FILING_NOT_SUBMITTED | 409 |
| ERR_POSTURE_NOT_GOOD_STANDING | 409 |
| ERR_QUALIFICATION_EXISTS | 409 |
| ERR_QUALIFICATION_NOT_PENDING | 409 |
| ERR_QUALIFICATION_NOT_QUALIFIED | 409 |
| ERR_QUALIFICATION_NOT_WITHDRAWAL_PENDING | 409 |
| ERR_EXIT_CLEARANCE_FAILED | 422 |
| ERR_OPEN_QUALIFICATIONS_EXIST | 409 |
| ERR_DISSOLUTION_BLOCKED | 422 |
| ERR_GRANT_NOT_ACTIVE | 409 |
| ERR_GRANT_NOT_SUSPENDED | 409 |
| ERR_GRANT_ALREADY_TERMINAL | 409 |
| ERR_GRANT_WINDOW_OVERLAP | 409 |
| ERR_DELEGATION_DEPTH_EXCEEDED | 422 |
| ERR_DELEGATOR_GRANT_INVALID | 422 |
| ERR_DELEGATOR_WINDOW_INSUFFICIENT | 422 |
| ERR_DELEGATION_LIMIT_EXCEEDED | 422 |
| ERR_CERTIFICATE_NOT_REQUESTED | 409 |
| ERR_APPOINTMENT_NOT_APPOINTED | 409 |
| ERR_AGENT_APPOINTMENT_NOT_ACTIVE | 409 |
| ERR_AGENT_APPOINTMENT_NOT_NOTICE_PENDING | 409 |
| ERR_AGENT_RESIGNATION_NOTICE_UNRIPE | 409 |
| ERR_AGENT_APPOINTMENT_OVERLAP | 409 |
| ERR_AGENT_COVERAGE_GAP | 422 |
| ERR_SELF_OWNERSHIP | 422 |
| ERR_OWNERSHIP_CYCLE | 422 |
| ERR_OWNERSHIP_TOTAL_EXCEEDED | 422 |
| ERR_OWNERSHIP_RECORD_NOT_ACTIVE | 409 |
