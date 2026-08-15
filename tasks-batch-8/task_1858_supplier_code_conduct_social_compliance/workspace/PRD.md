# Supplier Code of Conduct & Social Compliance Audit API — Product Requirements Document

## 1. Introduction

Brands and retailers running responsible-sourcing programs face a concrete operational problem: a portfolio of suppliers spread across countries with very different labor-risk profiles, a Code of Conduct that evolves through versions each supplier must formally acknowledge, audits that must be scheduled against auditor availability and facility spacing rules, findings that must be remediated and independently verified, and worker voices that must reach the program without ever exposing the reporter. This document specifies an API that operationalizes that entire loop — a Supplier Code of Conduct & Social Compliance Audit platform for a responsible sourcing program.

The system governs publication of code versions and their acknowledgment by suppliers with supersede chaining; risk-based facility scoping that blends country exposure, sector, workforce size, and the facility's own audit history into an audit cadence; audit scheduling under announced and semi-announced windows with auditor assignment; finding classification with a zero-tolerance fast lane that fails an audit outright; corrective action plans reviewed by compliance and verified by a second, independent auditor; an anonymized grievance channel alongside worker interview evidence gathered during audits; forced-labor and recruitment-fee reviews backed by a full reimbursement ledger; a dual-variant supplier scorecard that drives consequence tiers and probation; and mutual recognition of external industry audit programs that can extend a facility's audit interval. Global contracts — response envelope, pagination, roles, validation order, concurrency, precision — are defined first; the business workflows follow.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` specifies their operational capacity. A request missing either header, or carrying an invalid one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to each operation is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes six roles. `SourcingProgramAdmin` runs the responsible-sourcing program: code versions, the supplier and facility registry, facility exits, and the logical clock. `AuditCoordinator` schedules audits and manages the auditor pool. `Auditor` conducts assigned audits — start, findings, interviews, the fee review, the report — and verifies corrective action plans of audits led by other auditors. `SupplierContact` is the supplier-side contact who acknowledges code versions, submits corrective action plans, and files mutual-recognition claims. `ComplianceOfficer` is the independent compliance authority: audit report decisions, plan review, grievance triage, violation confirmation, reimbursements, claim decisions, and supplier termination. `WorkerHotline` is the anonymous worker grievance channel intake; it may only file grievances and cannot read anything.

Two roles are entity-backed. When `X-User-Role` is `Auditor`, `X-User-ID` is the `id` of the acting `Auditor`; ownership checks on any resource that references an `Auditor` compare the resource's auditor foreign-key field to `X-User-ID`. When `X-User-Role` is `SupplierContact`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource in a supplier's chain compare the chain's supplier foreign-key field to `X-User-ID`. An entity-backed caller acting on a chain it does not own is rejected with `ERR_OWNERSHIP_VIOLATION`.

The remaining four roles are opaque. When `X-User-Role` is `SourcingProgramAdmin`, `AuditCoordinator`, `ComplianceOfficer`, or `WorkerHotline`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, on resources where a transition writes the acting operator) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted resource carries `id` (a server-minted UUID with no type prefix) and `created_at` (an ISO 8601 UTC timestamp with three fractional digits, taken from the program's logical clock). Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every change, and `version`, a system-managed integer that increments by one on every mutation — including system-driven writes to computed fields, such as a scorecard recompute that lands on a Supplier.

Two registration records are immutable after creation and therefore carry only `id` and `created_at`: the CodeAcknowledgment and the WorkerInterviewRecord. On both, `updated_at` and `version` are absent.

### 2.5. The Program Logical Clock

The program runs on a logical clock, not wall-clock time. Before any client call, the clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `SourcingProgramAdmin` may set the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant; the response echoes the new time as `current_utc`. Every time-dependent rule in this document — audit window shape and start gating, the thirty-day facility spacing rule, remediation due dates, external-audit staleness, and program validity for mutual recognition — evaluates against this clock, and advancing the clock can change whether a previously accepted claim is still within its validity window.

### 2.6. Validation Discipline and Evaluation Order

Every request is evaluated against a fixed sequence of check families; a request that fails an earlier family is rejected without any later family being consulted. The order is:

1. **Identity headers.** `X-User-ID` and `X-User-Role` must be present and valid — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role permission.** The role must be permitted for the operation — `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. **Request schema.** Required fields present, types valid, enum values in range, array minimums honored — a corrective action plan must carry at least one action item, `void_justification` must be at least ten characters, and conditional fields such as `resolution_note` or `rejection_reason` must be present when the chosen action requires them — `ERR_INVALID_REQUEST` (400).
4. **Existence.** Path identifiers and body-referenced identifiers (`facility_id`, `auditor_id`, `finding_id`, `code_version_id`, `linked_grievance_id`) must resolve to existing resources, validated left to right — `ERR_NOT_FOUND` (404).
5. **Ownership.** Entity-backed callers must own the target chain — `ERR_OWNERSHIP_VIOLATION` (403).
6. **Concurrency.** The acknowledgment-creation OCC check of §2.7 — `ERR_STALE_VERSION` (412).
7. **State preconditions.** From-state requirements of every state machine: the `ERR_*_INVALID_STATE` family (`ERR_CODE_VERSION_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_CAP_INVALID_STATE`, `ERR_GRIEVANCE_INVALID_STATE`, `ERR_REVIEW_INVALID_STATE`, `ERR_REIMBURSEMENT_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`) plus `ERR_CODE_VERSION_NOT_PUBLISHED`, `ERR_SUPPLIER_NOT_AUDITABLE`, `ERR_FACILITY_NOT_ACTIVE`, `ERR_AUDITOR_NOT_ACTIVE`, `ERR_SUPPLIER_ALREADY_TERMINATED`, and `ERR_FINDING_NOT_OPEN` — all 409. Within state checks, the parent chain is evaluated before the target entity's own state: supplier before facility before audit.
8. **Business safety.** Zero-tolerance category recognition, verification segregation of duties, unresolved critical grievances, and open zero-tolerance findings — `ERR_ZT_CATEGORY_NOT_RECOGNIZED`, `ERR_VERIFICATION_AUDITOR_CONFLICT`, `ERR_CRITICAL_GRIEVANCE_UNRESOLVED`, `ERR_LINKED_GRIEVANCE_UNRESOLVED`, `ERR_OPEN_ZT_FINDINGS_EXIST`.
9. **Uniqueness and exclusivity.** One open audit per facility, mutual-recognition coverage, country coverage, open-audit blocking of deactivation, one interview record and one fee review per audit, one open plan per finding, external score minimums, interview sample size, and the interview record prerequisite — `ERR_AUDIT_ALREADY_OPEN`, `ERR_COVERED_BY_MUTUAL_RECOGNITION`, `ERR_AUDITOR_COUNTRY_NOT_COVERED`, `ERR_AUDITOR_HAS_OPEN_AUDITS`, `ERR_RECORD_ALREADY_EXISTS`, `ERR_CAP_ALREADY_OPEN`, `ERR_EXTERNAL_SCORE_TOO_LOW`, `ERR_INTERVIEW_SAMPLE_TOO_SMALL`, `ERR_INTERVIEW_RECORD_MISSING`.
10. **Temporal interval rules.** Auditor double-booking, facility spacing, window shape, window-not-open, and external-audit staleness — `ERR_AUDITOR_BOOKING_CONFLICT`, `ERR_FACILITY_AUDIT_GAP_VIOLATION`, `ERR_INVALID_AUDIT_WINDOW`, `ERR_AUDIT_WINDOW_NOT_OPEN`, `ERR_EXTERNAL_AUDIT_STALE`.
11. **Cross-entity link consistency.** A fee review's linked grievance must belong to the same facility as the review's audit — `ERR_GRIEVANCE_FACILITY_MISMATCH` (400). This family is evaluated only after the safety family, so a linked grievance that is not yet resolved surfaces as `ERR_LINKED_GRIEVANCE_UNRESOLVED` rather than being masked by the facility-match check.
12. **Fiscal limits.** Payment amounts against outstanding balances, and outstanding balances against facility exit — `ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING` (422) and `ERR_OUTSTANDING_REIMBURSEMENT` (409) — evaluated last.

### 2.7. Optimistic Concurrency on Supplier Acknowledgment

Exactly one write participates in optimistic concurrency control: creating a code acknowledgment (`POST /code-acknowledgments`). The request must carry `expected_supplier_version`, holding the `version` of the target Supplier as the caller last observed it. If the value does not match the supplier's current `version` — because a successful acknowledgment legitimately supersedes the supplier's current code version and advances `Supplier.version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read the supplier before acknowledging. Endpoints not named here do not accept a version field.

### 2.8. Numeric Precision, Rounding, and Units

Facility risk scores (`risk_score_baseline` and `risk_score_history`) are carried to one decimal place using round-half-up. Supplier scorecard points are integers with a floor of zero — a score never goes negative. Reimbursement money is integer USD cents: foreign-currency fee lines are each rounded half up to zero decimal places (whole cents) before any summation takes place. The worker interview minimum sample is an integer obtained by ceiling. Audit cadence intervals are integer months, and their evaluation order — tier base, then the zero-tolerance-failure cap, then the mutual-recognition validity extension, then the clamp — is pinned and must not be reordered. Remediation due dates are computed by day-granularity datetime addition onto the finding's `created_at`.

### 2.9. Segregation of Duties and Worker Anonymity

Remediation verification is segregated from audit execution: the auditor who verifies a corrective action plan must be an `ACTIVE` auditor whose identity differs from the originating audit's lead `auditor_id`, or the verify is refused with `ERR_VERIFICATION_AUDITOR_CONFLICT` (403). The recording auditor and the verifying auditor are therefore always two different people.

Worker protection is the second pillar. Grievances are stored without any reporter identity — `is_anonymized` is always true — and interviewer `notes` are anonymized before storage. Grievance reads are confidential and restricted to program staff (`SourcingProgramAdmin`, `AuditCoordinator`, `ComplianceOfficer`); auditors, supplier contacts, and the hotline channel itself cannot read grievances.

### 2.10. Cross-Entity Consistency: Cascades, Recomputes, and Compensating Actions

Consistency is immediate: every cascade and recompute described in §3 completes synchronously within the triggering request, and the mutated parent resources refresh `updated_at` and increment `version` like any other mutation. Two zero-tolerance cascades anchor the model — recording a zero-tolerance finding fails its audit and recomputes the supplier scorecard in one hop chain, and terminating a supplier exits its facilities and cancels their open audits. Several operations exist purely as compensating pairs: voiding restores what recording a finding deducted, and reversing restores what recording a reimbursement settled. Two conserved quantities hold at all times: an audit's three finding tallies always sum to its number of non-voided findings, and a review's total always equals its reimbursed plus outstanding cents.

For any endpoint whose path nests one resource beneath another — findings, interview records, and fee reviews are addressed beneath their audit; reimbursements beneath their review — path identifiers are validated left to right, and the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before any business rule runs.

## 3. Business Logic & Workflows

### 3.1. Code of Conduct Versions and Supplier Acknowledgment

A `SourcingProgramAdmin` authors each Code of Conduct version by supplying a human-readable `version_label` (for example, "CoC v3.2"), the `effective_from` date on which the version takes effect, and `zero_tolerance_categories`, the list of finding category values that count as zero-tolerance under that version. A new version begins `DRAFT`. Publishing it — a transition request carrying `to_status` of `PUBLISHED` — moves it `DRAFT → PUBLISHED`; retiring it — `to_status` of `RETIRED` — moves it `PUBLISHED → RETIRED`. Any transition attempted from a from-state that does not allow it, such as publishing a version that is not `DRAFT` or retiring one that is not `PUBLISHED`, is rejected with `ERR_CODE_VERSION_INVALID_STATE`. Retirement is not retroactive: suppliers that already acknowledged the version keep their `current_code_version_id` unchanged, and `RETIRED` is terminal.

Supplier registration is also the admin's work. The registry entry captures the supplier's `legal_name`, the ISO-2 `country_code` of its headquarters, and a `sector` of `APPAREL`, `ELECTRONICS`, `FOOD`, or `HARDLINES`. A new supplier starts `ONBOARDING` with `provisional_score` and `verified_score` both at 100, `consequence_tier` at `PREFERRED`, and `escalation_penalty_points` at 0. The supplier list can be filtered by `status`, `consequence_tier`, and `current_code_version_id`, with the usual `limit` and `offset` pagination.

Acknowledgment is the supplier's signature on a published code version. A `SupplierContact` files an acknowledgment carrying `supplier_id`, `code_version_id`, the authorized signatory's `signer_name` and `signer_title`, and the OCC field `expected_supplier_version` described in §2.7. The referenced code version must be `PUBLISHED` — otherwise the filing is rejected with `ERR_CODE_VERSION_NOT_PUBLISHED` — and the `supplier_id` must equal the caller's `X-User-ID`, since a contact may only acknowledge on behalf of its own supplier (`ERR_OWNERSHIP_VIOLATION`). On success, `acknowledged_at` is stamped from the logical clock, and `supersedes_acknowledgment_id` is set to the supplier's previously latest acknowledgment — the one with the greatest `acknowledged_at`, with ties broken by the greatest `created_at` — remaining null on the supplier's first acknowledgment. The acknowledgment increments the supplier's `version` by one and sets the supplier's `current_code_version_id` to the acknowledged version; a supplier's first acknowledgment also moves it automatically from `ONBOARDING` to `ACTIVE`. Acknowledgments are immutable registration records (§2.4), and the acknowledgment list supports filtering by `supplier_id`, `code_version_id`, and `supersedes_acknowledgment_id` for reverse reachability along the supersede chain.

### 3.2. Facility Registration and Risk-Based Scoping

Facilities are the physical sites the program audits. A `SourcingProgramAdmin` registers one under a supplier by providing `supplier_id`, the facility `name`, the site's ISO-2 `country_code`, the on-site `worker_count` (at least 1), and `processes`, a free-form list of production processes on site. Registration is refused when the owning supplier is already `TERMINATED` (`ERR_SUPPLIER_ALREADY_TERMINATED`). A facility starts `ACTIVE`.

At creation the system computes the facility's baseline risk. The `risk_score_baseline` is the country exposure of the site's `country_code`, multiplied by the sector multiplier of the owning supplier's `sector`, plus a workforce factor derived from `worker_count`. Country exposures are: BD 60, IN 55, VN 50, CN 40, TR 35, US 10. Sector multipliers are: `APPAREL` 1.2, `ELECTRONICS` 1.1, `FOOD` 1.0, `HARDLINES` 0.9. The workforce factor adds 15 when the site employs at least 1000 workers, 8 when it employs at least 300 but fewer than 1000, and 3 when it employs fewer than 300. The baseline is expressed to one decimal place, round half up.

Once any audit of the facility reaches a terminal state — `COMPLETED` or `FAILED_ZT` — the history-adjusted variant activates. Its history component counts the facility's findings on terminal audits that have not been voided, weighted 10 per `ZERO_TOLERANCE`, 4 per `MAJOR`, and 1 per `MINOR`, capped at 100. The `risk_score_history` is then the blend of one half baseline and one half history component, rounded half up to one decimal place. Until the facility's first terminal audit, `risk_score_history` is null, and identical facility inputs can yield a different score than the baseline once history exists.

The `risk_tier` derives from the applicable score — the history variant once available, the baseline otherwise: `HIGH` at 70 or above, `MEDIUM` at 40 or above, otherwise `LOW`, with the band boundaries inclusive on their lower bounds.

Risk drives cadence. The `next_audit_interval_months` starts from the tier base — `HIGH` 6 months, `MEDIUM` 12, `LOW` 24 — and is then adjusted in a pinned order: first, if the facility's latest terminal audit is `FAILED_ZT`, the interval is capped down to at most 3 months by taking the smaller of the two; second, if a valid accepted mutual-recognition claim covers the facility (§3.9), the claim's program validity months are added; third, the result is clamped to no fewer than 3 and no more than 36 months. The `next_audit_due_date` is the latest terminal audit's `scheduled_end` shifted forward by that interval in months, and stays null while the facility has no terminal audit. The latest terminal audit is the facility's audit in `COMPLETED` or `FAILED_ZT` with the greatest `scheduled_end`, ties broken by the greatest `created_at`. The interval and due date recompute at facility creation, whenever an audit of the facility reaches a terminal state, and whenever a mutual-recognition claim is accepted; a clock advance can also change whether a claim still counts as valid. A facility's scoping read surfaces both risk variant scores, the tier, the interval, and the next due date.

When a facility leaves the program, the admin exits it, optionally recording an `exit_reason`. Exit is blocked while any audit at the facility is `SCHEDULED`, `IN_PROGRESS`, or `REPORT_SUBMITTED` (`ERR_AUDIT_ALREADY_OPEN`), and while any fee review on the facility's audits is `VIOLATION_CONFIRMED` with `outstanding_reimbursement_cents` above zero (`ERR_OUTSTANDING_REIMBURSEMENT`). A successful exit moves the facility `ACTIVE → EXITED`, which is terminal; supplier termination forces the same move as a cascade (§3.6). The facility list filters by `supplier_id`, `status`, and `risk_tier`.

### 3.3. The Auditor Pool and Audit Scheduling

An `AuditCoordinator` maintains the auditor pool. Registering an auditor captures `full_name`, the `firm_name`, the auditor's `certifications` (labels such as SA8000 or SMETA), and `country_codes_covered`, the ISO-2 country list the auditor may be assigned to. Auditors start `ACTIVE`. Deactivation moves an auditor `ACTIVE → INACTIVE` but is blocked while the auditor still holds audits in `SCHEDULED`, `IN_PROGRESS`, or `REPORT_SUBMITTED` (`ERR_AUDITOR_HAS_OPEN_AUDITS`).

Scheduling an audit is the coordinator's central act. The request names the `facility_id` and the lead `auditor_id`, declares an `audit_type` of `INITIAL`, `ANNUAL`, `RE_AUDIT`, or `FOLLOW_UP`, chooses an `announcement` of `ANNOUNCED` (exact dates) or `SEMI_ANNOUNCED` (a window), and gives the half-open window `scheduled_start` to `scheduled_end` — the start is inclusive, the end exclusive. A created audit begins `SCHEDULED` with its tallies `zt_count`, `major_count`, and `minor_count` zeroed.

Creation is guarded on several axes. The owning supplier must be `ACTIVE` or `PROBATION` (`ERR_SUPPLIER_NOT_AUDITABLE`), the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), and the assigned auditor must be `ACTIVE` (`ERR_AUDITOR_NOT_ACTIVE`); within these state checks the supplier is evaluated first, then the facility, then the auditor. The facility's `country_code` must appear in the auditor's `country_codes_covered` (`ERR_AUDITOR_COUNTRY_NOT_COVERED`, 422). At most one open audit — one in `SCHEDULED`, `IN_PROGRESS`, or `REPORT_SUBMITTED` — may exist per facility (`ERR_AUDIT_ALREADY_OPEN`). The auditor must not be double-booked: the new half-open window must not intersect any non-`CANCELLED` audit of the same auditor, where a conflict exists exactly when the new start falls before an existing audit's end and the new end falls after that existing audit's start — windows that merely touch at an endpoint are allowed (`ERR_AUDITOR_BOOKING_CONFLICT`). Facility spacing requires the new `scheduled_start` to be at least 30 days after the `scheduled_end` of every non-`CANCELLED` audit at the same facility, with a start exactly 30 days later permitted (`ERR_FACILITY_AUDIT_GAP_VIOLATION`). The window shape itself must be sane — an `ANNOUNCED` audit spans 1 to 10 days, a `SEMI_ANNOUNCED` audit spans 14 to 60 days, and `scheduled_start` must be at or after the current logical clock (`ERR_INVALID_AUDIT_WINDOW`, 422). Finally, an `ANNUAL` audit is refused while a valid accepted mutual-recognition claim covers the facility (`ERR_COVERED_BY_MUTUAL_RECOGNITION`).

When the window opens, the assigned auditor starts the audit. Starting requires the audit to be `SCHEDULED` (`ERR_AUDIT_INVALID_STATE`), the caller to be the audit's own lead — `X-User-ID` must equal the audit's `auditor_id` (`ERR_OWNERSHIP_VIOLATION`) — and the logical clock to have reached `scheduled_start` (`ERR_AUDIT_WINDOW_NOT_OPEN`). The audit moves `SCHEDULED → IN_PROGRESS`.

A coordinator may cancel an audit while it is still `SCHEDULED`, optionally giving a `reason` that is stored on the audit as `cancel_reason`; the audit moves to `CANCELLED`, which is terminal. Supplier termination cancels open audits as a cascade (§3.6).

At the end of fieldwork the assigned auditor submits the report. Submission requires the audit to be `IN_PROGRESS` (`ERR_AUDIT_INVALID_STATE`), the same ownership rule as starting, and the audit's single worker interview record to already exist (`ERR_INTERVIEW_RECORD_MISSING`). The audit moves `IN_PROGRESS → REPORT_SUBMITTED`, and the supplier scorecard recomputes — the provisional variant is the worst-case view the program sees at report time.

A `ComplianceOfficer` then dispositions the report through `decision`. A `COMPLETE` decision moves the audit `REPORT_SUBMITTED → COMPLETED`; it is refused while any grievance at the audit's facility has severity `CRITICAL` and a status of `SUBMITTED`, `UNDER_REVIEW`, or `ESCALATED` (`ERR_CRITICAL_GRIEVANCE_UNRESOLVED`). On completion, the facility's history risk variant activates if this is its first terminal audit, the risk fields, interval, and due date recompute, and the supplier scorecard recomputes. A `RETURN_FOR_CORRECTION` decision instead moves the audit `REPORT_SUBMITTED → IN_PROGRESS`, reopening the report cycle; the existing worker interview record is retained, an optional `correction_note` may accompany the return, and this loop may repeat as often as needed. Either decision attempted from a state other than `REPORT_SUBMITTED` is rejected with `ERR_AUDIT_INVALID_STATE`. The audit list filters by `facility_id`, `auditor_id`, `status`, and `audit_type`.

### 3.4. Findings, the Zero-Tolerance Fast Lane, and Voiding

During an `IN_PROGRESS` audit, the assigned auditor records findings. Each finding is addressed beneath its audit — the path parameter identifies the audit and is stored on the finding as `audit_id` — and carries a `classification` of `ZERO_TOLERANCE`, `MAJOR`, or `MINOR`; a `category` of `FORCED_LABOR`, `CHILD_LABOR`, `WORKING_HOURS`, `WAGES`, `HEALTH_SAFETY`, `ENVIRONMENT`, `HARASSMENT`, or `RECRUITMENT_FEES`; and a narrative `description`. Recording against an audit that is not `IN_PROGRESS` is rejected with `ERR_AUDIT_INVALID_STATE`, and recording by anyone other than the audit's lead auditor is an `ERR_OWNERSHIP_VIOLATION`. A new finding is `OPEN`.

Classification governs the remediation clock. The finding's `remediation_due_date` is its `created_at` plus 30 days for `ZERO_TOLERANCE`, plus 90 days for `MAJOR`, and plus 180 days for `MINOR`. With the default logical clock of 2026-08-01, those three classes fall due on 2026-08-31, 2026-10-30, and 2027-01-28 respectively.

Zero-tolerance is a fast lane with a recognition gate. A finding may only be classified `ZERO_TOLERANCE` when its `category` appears in the `zero_tolerance_categories` of the supplier's current code version; anything else is rejected with `ERR_ZT_CATEGORY_NOT_RECOGNIZED` (422). When a zero-tolerance finding is recorded on an `IN_PROGRESS` audit, a four-hop cascade fires synchronously: first the audit's `zt_count` tally recomputes upward by one; second the audit itself moves `IN_PROGRESS → FAILED_ZT`, because any zero-tolerance finding fails the audit outright; third the supplier scorecard recomputes, both variants dropping 40 points for the newly open zero-tolerance finding; fourth the supplier moves `ACTIVE → PROBATION` under the open-zero-tolerance rule of §3.6. Because `FAILED_ZT` is a terminal audit state, the facility's risk fields also recompute and the history variant activates.

Each audit keeps three tallies: `zt_count` for its non-voided `ZERO_TOLERANCE` findings, `major_count` for non-voided `MAJOR`, and `minor_count` for non-voided `MINOR`. The three always sum to the audit's total number of non-voided findings; recording a finding and voiding it are the compensating pair that keeps this quantity conserved.

Voiding corrects an erroneous finding. The assigned auditor may void a finding that is still `OPEN` (`ERR_FINDING_NOT_OPEN` otherwise) while the parent audit is `IN_PROGRESS`, `REPORT_SUBMITTED`, or `FAILED_ZT` (`ERR_AUDIT_INVALID_STATE`), with the same lead-auditor ownership rule (`ERR_OWNERSHIP_VIOLATION`). The request must include a `void_justification` of at least ten characters (`ERR_INVALID_REQUEST`). Voiding moves the finding `OPEN → VOIDED`, which is terminal; the audit tallies recompute with the finding excluded; the supplier scorecard recomputes with both variants restoring the finding's deduction; the supplier's `PROBATION → ACTIVE` recovery is re-evaluated; and if the parent audit is terminal, the facility's risk recomputes. The findings of an audit can be listed with filters on `classification` and `status`.

### 3.5. Corrective Action Plans and Independent Verification

Every `OPEN` finding enters remediation through a corrective action plan. A `SupplierContact` submits one by naming the `finding_id` and providing `actions`, a list of remediation items each carrying a `description`, an `owner`, and a `due_date`; the list must contain at least one item (`ERR_INVALID_REQUEST`). The finding must be `OPEN` (`ERR_FINDING_NOT_OPEN`), and at most one open plan may exist per finding — open here meaning `SUBMITTED`, `APPROVED`, `REJECTED`, `VERIFICATION_REQUESTED`, or `VERIFICATION_FAILED` (`ERR_CAP_ALREADY_OPEN`). The plan's `supplier_id` is derived from the chain finding → audit → facility → supplier and must equal the caller's `X-User-ID` (`ERR_OWNERSHIP_VIOLATION`). A new plan starts `SUBMITTED` with `escalation_count` at 0.

Review belongs to a `ComplianceOfficer`, who passes a `decision`. `APPROVE` moves the plan `SUBMITTED → APPROVED`. `REJECT` moves it `SUBMITTED → REJECTED` and requires a `rejection_reason` in the payload (`ERR_INVALID_REQUEST`), which is stored on the plan. Either decision from any other state is an `ERR_CAP_INVALID_STATE`.

A rejected plan is not the end of the road. The owning supplier contact resubmits it — the caller's `X-User-ID` must equal the plan's `supplier_id` (`ERR_OWNERSHIP_VIOLATION`) — which is only possible from `REJECTED` (`ERR_CAP_INVALID_STATE`); the plan's `actions` are replaced wholesale with the revised payload and it returns to `SUBMITTED`. This reject/resubmit cycle may repeat.

Once the supplier has executed an approved plan, its contact requests verification. The request is valid from `APPROVED` and equally from `VERIFICATION_FAILED` — a failed verification can be retried — with any other from-state rejected as `ERR_CAP_INVALID_STATE`; ownership is again enforced (`ERR_OWNERSHIP_VIOLATION`). The plan moves to `VERIFICATION_REQUESTED`.

Verification itself is performed by an `Auditor` caller and obeys the segregation of duties of §2.9: the caller's `X-User-ID` must identify an `ACTIVE` auditor different from the originating audit's lead `auditor_id`, or the verify is refused with `ERR_VERIFICATION_AUDITOR_CONFLICT` (403). The verify is only possible from `VERIFICATION_REQUESTED` (`ERR_CAP_INVALID_STATE`), and the payload carries an `outcome` and a `verification_note`.

When the `outcome` is `PASS`, the plan moves to `VERIFIED_PASSED`, which is terminal; the finding flips `OPEN → VERIFIED_CLOSED`; the supplier scorecard recomputes with the verified variant restoring the finding's deduction; the supplier's `PROBATION → ACTIVE` recovery is re-evaluated; and the plan's `verified_by_auditor_id` records the verifying auditor from `X-User-ID`. When the `outcome` is `FAIL`, the plan moves to `VERIFICATION_FAILED`; its `escalation_count` increments by one; once that count is 2 or more, the supplier's `escalation_penalty_points` grows by 5 per failure; the scorecard recomputes with the penalty flowing into both variants; if the verified score has fallen below 60 the supplier moves `ACTIVE → PROBATION`; and `verified_by_auditor_id` likewise records the auditor of this latest verify call. Plans can be listed with filters on `finding_id`, `supplier_id`, and `status`.

### 3.6. The Supplier Scorecard, Consequence Tiers, and Termination

Two score variants travel together on every supplier. Both recompute whenever a finding is recorded or voided, whenever a plan verify resolves `PASS` or `FAIL`, whenever a grievance is filed or triaged, and whenever an audit report is submitted or an audit completes. The counts range over findings on non-`CANCELLED` audits across all of the supplier's facilities, plus grievances at those facilities, plus the supplier's `escalation_penalty_points`.

The `provisional_score` is the worst-case view shown at report-submission time. From 100 it subtracts 40 for every `ZERO_TOLERANCE` finding that has not been voided, 10 for every non-voided `MAJOR` finding, 3 for every non-voided `MINOR` finding, 5 for every unresolved critical grievance — severity `CRITICAL` with status `SUBMITTED`, `UNDER_REVIEW`, or `ESCALATED` — and finally the supplier's `escalation_penalty_points`; the result is floored at 0. Remediation closure gives no credit in this variant: a `VERIFIED_CLOSED` finding still deducts.

The `verified_score` uses the identical weights but counts only findings still `OPEN`: 40 per open `ZERO_TOLERANCE`, 10 per open `MAJOR`, 3 per open `MINOR`, 5 per unresolved critical grievance, and the escalation penalty, again floored at 0. Because verification of a plan closes its finding, the verified variant restores points once remediation is verified, so identical raw data yields a higher verified than provisional score. The verified variant drives both the consequence tier and the supplier's standing.

The `consequence_tier` maps the verified score onto business consequences: `PREFERRED` at 80 or above; `QUALIFIED` from 60 up to 79; `PROBATION_WATCH` from 40 up to 59; and `SOURCING_EXIT` below 40, with each band inclusive on its lower bound. Standing is gated separately from the label: a supplier moves `ACTIVE → PROBATION` whenever the verified score drops below 60 or any `OPEN` zero-tolerance finding exists across its facilities, and recovers `PROBATION → ACTIVE` when the verified score is back at 60 or above and no `OPEN` zero-tolerance finding exists.

A computed scorecard read exposes both variants and the live counts feeding them: `supplier_id`, `provisional_score`, `verified_score`, `consequence_tier`, `escalation_penalty_points`, `open_zt_count`, `open_major_count`, `open_minor_count`, and `unresolved_critical_grievance_count`.

Termination is the program's final sanction. A `ComplianceOfficer` terminates a supplier that is `ACTIVE` or `PROBATION` — any other state is rejected with `ERR_SUPPLIER_ALREADY_TERMINATED` — optionally recording a `termination_reason`. The cascade is synchronous: every facility of the supplier that is `ACTIVE` moves to `EXITED`; every audit of those facilities in `SCHEDULED`, `IN_PROGRESS`, or `REPORT_SUBMITTED` moves to `CANCELLED`, while terminal audits are left untouched; and the supplier's scorecard fields freeze at their last computed values, with no further recompute while the supplier is `TERMINATED`. That state is terminal.

### 3.7. The Worker Grievance Channel and Interview Evidence

Workers reach the program through an anonymized grievance channel. Only the `WorkerHotline` role may file: the intake carries the `facility_id` the grievance concerns, a `channel` of `HOTLINE`, `WORKER_COMMITTEE`, or `AUDIT_INTERVIEW`, a `category` of `WAGES`, `HARASSMENT`, `FORCED_LABOR`, `SAFETY`, `RECRUITMENT_FEES`, or `OTHER`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a `description`. The grievance is stored without reporter identity — `is_anonymized` is always true — and starts `SUBMITTED`. When the severity is `CRITICAL`, filing immediately recomputes the supplier scorecard, deducting 5 points while the grievance remains unresolved. Per §2.9, grievance reads are restricted to program staff, and the grievance list filters by `facility_id`, `status`, `severity`, and `category`.

Triage belongs to a `ComplianceOfficer`, who passes an `action`. `START_REVIEW` moves a `SUBMITTED` grievance to `UNDER_REVIEW`. `ESCALATE` moves an `UNDER_REVIEW` grievance to `ESCALATED` and recomputes the supplier scorecard — an unresolved `CRITICAL` grievance deducts its 5 points whether it sits in `SUBMITTED`, `UNDER_REVIEW`, or `ESCALATED`. `RESOLVE` is valid from `UNDER_REVIEW` or `ESCALATED` and requires a `resolution_note` (`ERR_INVALID_REQUEST`); the grievance moves to `RESOLVED`, which is terminal, the scorecard recomputes with the grievance deduction removed, and the supplier's `PROBATION → ACTIVE` recovery is re-evaluated. Any triage action from a from-state that does not permit it is rejected with `ERR_GRIEVANCE_INVALID_STATE`. The recruitment fee reviews linked to a grievance can be listed from the grievance; the list holds zero or one entries.

Interview evidence is gathered during the audit itself. The assigned auditor records the audit's worker interview sample beneath that audit — the record's `audit_id` ties it there, just as the fee review of §3.8 stores its own `audit_id` — and exactly one such record may exist per audit: a second attempt is rejected with `ERR_RECORD_ALREADY_EXISTS`. The same ownership rule as findings applies — the caller's `X-User-ID` must equal the audit's `auditor_id` (`ERR_OWNERSHIP_VIOLATION`) — and recording from an audit status that does not permit it is rejected with `ERR_AUDIT_INVALID_STATE`. The record carries the `interview_count`, the booleans `forced_labor_indicators` and `recruitment_fee_indicators` reporting what the interviews surfaced, and optional anonymized `notes`. The minimum sample scales with the site: `interview_count` must be at least the square root of the facility's `worker_count` rounded up to a whole number, or the record is rejected with `ERR_INTERVIEW_SAMPLE_TOO_SMALL` (422) — a facility of 100 workers requires exactly 10 interviews, 99 workers still require 10, and 101 workers require 11. The interview record is an immutable registration record carrying only `id` and `created_at` (§2.4); submitting the audit report requires it to exist (§3.3), and a return-for-correction retains it. The audit's interview record can be listed, holding zero or one entries.

### 3.8. Recruitment Fee Reviews and the Reimbursement Ledger

Forced-labor due diligence centers on recruitment fees charged to migrant workers. The assigned auditor records the audit's fee review — again exactly one per audit, with a second attempt rejected as `ERR_RECORD_ALREADY_EXISTS`, the same lead-auditor ownership rule (`ERR_OWNERSHIP_VIOLATION`), and the same rejection from a non-applicable audit status (`ERR_AUDIT_INVALID_STATE`) — providing `workers_assessed` (at least 1), the `fee_items` found, and an optional `linked_grievance_id` pointing at the grievance that triggered the review. Each fee item carries a `worker_ref`, an `amount_minor_units`, and a `currency`.

The reimbursement total is computed at creation. Each fee item is converted at the program's USD-cents-per-minor-unit rates — USD 1.0, EUR 1.08, INR 0.012, BDT 0.0115 — and each line is rounded half up to whole cents first; `total_reimbursement_cents` is the sum of those rounded lines. The rounding order is pinned — per-item rounding, then summation — because the two orders diverge: three items of 300 BDT minor units convert to 3.45 cents each, round to 3 cents each, and total 9, whereas summing first would round 10.35 to 10. When `fee_items` is empty, no fees were found and the review is created directly in `CLEARED`, which is terminal. Otherwise it starts `PENDING_CONFIRMATION` with `reimbursed_cents` at 0 and `outstanding_reimbursement_cents` equal to the total.

Confirmation belongs to a `ComplianceOfficer` and is valid only from `PENDING_CONFIRMATION` (`ERR_REVIEW_INVALID_STATE`). When a `linked_grievance_id` is set, two guards apply in a fixed order: the linked grievance must already be `RESOLVED` (`ERR_LINKED_GRIEVANCE_UNRESOLVED`) — this safety check outranks the second guard — and the grievance's `facility_id` must equal the facility of the review's audit (`ERR_GRIEVANCE_FACILITY_MISMATCH`, 400). Confirmation moves the review to `VIOLATION_CONFIRMED` and sets the outstanding balance to the full total.

Payments then settle the debt. A `ComplianceOfficer` records a reimbursement against a review that is `VIOLATION_CONFIRMED` (`ERR_REVIEW_INVALID_STATE` from any other state), giving an `amount_cents` that must be greater than zero (`ERR_INVALID_REQUEST`) and no more than the review's current `outstanding_reimbursement_cents` (`ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING`, 422), plus an optional `worker_ref` naming the worker the payment settles. The payment's `review_id` ties it to its review. A new reimbursement is `RECORDED`; the review's `reimbursed_cents` is the sum of its `RECORDED` payments and its `outstanding_reimbursement_cents` is the total minus the reimbursed sum. When a recorded payment brings the outstanding balance to exactly zero, the review advances automatically to `REIMBURSED`, which is terminal. The payments of a review can be listed with a `status` filter.

Reversal is the compensating action. A `ComplianceOfficer` may reverse a reimbursement that is `RECORDED` (`ERR_REIMBURSEMENT_INVALID_STATE` otherwise), moving it to `REVERSED`, which is terminal. The review's reimbursed sum decreases and its outstanding sum increases by the reversed `amount_cents`, and if the review had already reached `REIMBURSED` it drops back to `VIOLATION_CONFIRMED` because money is owed again. Recording and reversing thus restore the same balance, and the conserved quantity holds at all times: `total_reimbursement_cents` always equals `reimbursed_cents` plus `outstanding_reimbursement_cents`.

### 3.9. Mutual Recognition of Industry Audit Programs

The program avoids duplicate auditing by recognizing external industry schemes. A `SupplierContact` files a mutual-recognition claim for one of its own facilities — the caller's `X-User-ID` must equal the supplier of the facility's chain (`ERR_OWNERSHIP_VIOLATION`) — providing the `facility_id`, a `program_name` of `BSCI`, `SMETA`, `RBA`, or `WRAP`, the `external_audit_ref` report reference, the `external_audit_date`, and the `external_score`. A new claim starts `SUBMITTED`.

A `ComplianceOfficer` decides the claim with a `decision`, valid only from `SUBMITTED` (`ERR_CLAIM_INVALID_STATE`). Acceptance carries three further preconditions: no `OPEN` zero-tolerance finding may exist at the claim's facility (`ERR_OPEN_ZT_FINDINGS_EXIST`); the `external_score` must meet the program's minimum — `BSCI` 85, `SMETA` 75, `RBA` 80, `WRAP` 80 (`ERR_EXTERNAL_SCORE_TOO_LOW`, 422); and the `external_audit_date` must lie within 12 months of the current logical clock at decision time (`ERR_EXTERNAL_AUDIT_STALE`, 422). An `ACCEPT` decision moves the claim to `ACCEPTED`; a `REJECT` decision moves it to `REJECTED` and stores the payload's `decision_reason` on the claim. Both outcomes are terminal.

Acceptance has teeth. The facility's `next_audit_interval_months` and `next_audit_due_date` recompute with the claim's program validity extension — `BSCI` 24 months, `SMETA` 12, `RBA` 24, `WRAP` 12 — added into the interval at the pinned position of §3.2, after the tier base and any zero-tolerance-failure cap and before the clamp. A claim counts as valid for this extension, and for blocking `ANNUAL` audit creation under `ERR_COVERED_BY_MUTUAL_RECOGNITION` (§3.3), while its `external_audit_date` lies within its program's validity months of the current clock. When several accepted claims are simultaneously valid for one facility, the one with the greatest `external_audit_date` applies, ties broken by the greatest `created_at`. The claim list filters by `facility_id`, `program_name`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that read, modify, or transition an existing resource return a `200 OK` status code. In the table below, "All business roles" means `SourcingProgramAdmin`, `AuditCoordinator`, `ComplianceOfficer`, `Auditor`, and `SupplierContact`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SourcingProgramAdmin |
| POST | `/code-versions` | Create a Code of Conduct version (starts DRAFT) | SourcingProgramAdmin |
| GET | `/code-versions/{id}` | Get a code version | All business roles |
| POST | `/code-versions/{id}/transition` | Publish or retire a code version | SourcingProgramAdmin |
| POST | `/suppliers` | Register a supplier | SourcingProgramAdmin |
| GET | `/suppliers` | List suppliers with filters and pagination | All business roles |
| GET | `/suppliers/{id}` | Get a supplier | All business roles |
| POST | `/suppliers/{id}/terminate` | Terminate a supplier; cascades facilities and open audits | ComplianceOfficer |
| GET | `/suppliers/{id}/scorecard` | Computed scorecard read: both score variants, tier, and live counts | All business roles |
| POST | `/code-acknowledgments` | Supplier acknowledges a published code version (OCC on the supplier) | SupplierContact |
| GET | `/code-acknowledgments` | List acknowledgments with filters | All business roles |
| GET | `/code-acknowledgments/{id}` | Get an acknowledgment | All business roles |
| POST | `/facilities` | Register a facility; baseline risk computed at creation | SourcingProgramAdmin |
| GET | `/facilities` | List facilities with filters | All business roles |
| GET | `/facilities/{id}` | Get a facility | All business roles |
| POST | `/facilities/{id}/exit` | Exit a facility from the program | SourcingProgramAdmin |
| GET | `/facilities/{id}/scoping` | Computed scoping read: risk variants, tier, interval, next due date | All business roles |
| POST | `/auditors` | Register an auditor | AuditCoordinator |
| GET | `/auditors/{id}` | Get an auditor | All business roles |
| POST | `/auditors/{id}/deactivate` | Deactivate an auditor | AuditCoordinator |
| POST | `/audits` | Schedule an audit and assign its lead auditor | AuditCoordinator |
| GET | `/audits` | List audits with filters | All business roles |
| GET | `/audits/{id}` | Get an audit | All business roles |
| POST | `/audits/{id}/start` | Assigned auditor starts the audit | Auditor |
| POST | `/audits/{id}/submit-report` | Assigned auditor submits the audit report | Auditor |
| POST | `/audits/{id}/decide` | Compliance officer completes the audit or returns it for correction | ComplianceOfficer |
| POST | `/audits/{id}/cancel` | Cancel a scheduled audit | AuditCoordinator |
| POST | `/audits/{id}/findings` | Record a finding during the audit | Auditor |
| GET | `/audits/{id}/findings` | List findings of an audit | All business roles |
| GET | `/findings/{id}` | Get a finding | All business roles |
| POST | `/findings/{id}/void` | Assigned auditor voids an erroneous finding | Auditor |
| POST | `/corrective-action-plans` | Supplier submits a corrective action plan for an open finding | SupplierContact |
| GET | `/corrective-action-plans` | List corrective action plans with filters | All business roles |
| GET | `/corrective-action-plans/{id}` | Get a corrective action plan | All business roles |
| POST | `/corrective-action-plans/{id}/review` | Compliance officer approves or rejects a submitted plan | ComplianceOfficer |
| POST | `/corrective-action-plans/{id}/resubmit` | Supplier resubmits a rejected plan with revised actions | SupplierContact |
| POST | `/corrective-action-plans/{id}/request-verification` | Supplier declares remediation complete and requests verification | SupplierContact |
| POST | `/corrective-action-plans/{id}/verify` | A different auditor verifies remediation; failure escalates | Auditor |
| POST | `/grievances` | File an anonymized grievance | WorkerHotline |
| GET | `/grievances` | List grievances (confidential) | SourcingProgramAdmin, AuditCoordinator, ComplianceOfficer |
| GET | `/grievances/{id}` | Get a grievance (confidential) | SourcingProgramAdmin, AuditCoordinator, ComplianceOfficer |
| POST | `/grievances/{id}/triage` | Triage a grievance: start review, escalate, or resolve | ComplianceOfficer |
| GET | `/grievances/{id}/recruitment-fee-reviews` | List fee reviews linked to this grievance | SourcingProgramAdmin, AuditCoordinator, ComplianceOfficer |
| POST | `/audits/{id}/worker-interviews` | Record the audit's worker interview sample | Auditor |
| GET | `/audits/{id}/worker-interviews` | List the audit's interview record | All business roles |
| POST | `/audits/{id}/recruitment-fee-reviews` | Record the audit's recruitment fee review | Auditor |
| GET | `/audits/{id}/recruitment-fee-reviews` | List the audit's fee review | All business roles |
| GET | `/recruitment-fee-reviews/{id}` | Get a recruitment fee review | All business roles |
| POST | `/recruitment-fee-reviews/{id}/confirm-violation` | Compliance officer confirms the fee-charging violation | ComplianceOfficer |
| POST | `/recruitment-fee-reviews/{id}/reimbursements` | Record a reimbursement payment against a confirmed review | ComplianceOfficer |
| GET | `/recruitment-fee-reviews/{id}/reimbursements` | List reimbursements of a review | All business roles |
| POST | `/reimbursements/{id}/reverse` | Reverse a recorded reimbursement | ComplianceOfficer |
| POST | `/mutual-recognition-claims` | Supplier submits an industry-program audit for mutual recognition | SupplierContact |
| GET | `/mutual-recognition-claims` | List mutual recognition claims with filters | All business roles |
| GET | `/mutual-recognition-claims/{id}` | Get a claim | All business roles |
| POST | `/mutual-recognition-claims/{id}/decide` | Compliance officer accepts or rejects a claim | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CODE_VERSION_INVALID_STATE` | 409 Conflict |
| `ERR_CODE_VERSION_NOT_PUBLISHED` | 409 Conflict |
| `ERR_SUPPLIER_NOT_AUDITABLE` | 409 Conflict |
| `ERR_SUPPLIER_ALREADY_TERMINATED` | 409 Conflict |
| `ERR_FACILITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_AUDITOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_AUDITOR_HAS_OPEN_AUDITS` | 409 Conflict |
| `ERR_AUDIT_ALREADY_OPEN` | 409 Conflict |
| `ERR_COVERED_BY_MUTUAL_RECOGNITION` | 409 Conflict |
| `ERR_AUDITOR_COUNTRY_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_AUDITOR_BOOKING_CONFLICT` | 409 Conflict |
| `ERR_FACILITY_AUDIT_GAP_VIOLATION` | 409 Conflict |
| `ERR_INVALID_AUDIT_WINDOW` | 422 Unprocessable Entity |
| `ERR_AUDIT_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_AUDIT_INVALID_STATE` | 409 Conflict |
| `ERR_INTERVIEW_RECORD_MISSING` | 409 Conflict |
| `ERR_INTERVIEW_SAMPLE_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_ZT_CATEGORY_NOT_RECOGNIZED` | 422 Unprocessable Entity |
| `ERR_CRITICAL_GRIEVANCE_UNRESOLVED` | 409 Conflict |
| `ERR_FINDING_NOT_OPEN` | 409 Conflict |
| `ERR_CAP_ALREADY_OPEN` | 409 Conflict |
| `ERR_CAP_INVALID_STATE` | 409 Conflict |
| `ERR_VERIFICATION_AUDITOR_CONFLICT` | 403 Forbidden |
| `ERR_GRIEVANCE_INVALID_STATE` | 409 Conflict |
| `ERR_RECORD_ALREADY_EXISTS` | 409 Conflict |
| `ERR_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_LINKED_GRIEVANCE_UNRESOLVED` | 409 Conflict |
| `ERR_GRIEVANCE_FACILITY_MISMATCH` | 400 Bad Request |
| `ERR_OUTSTANDING_REIMBURSEMENT` | 409 Conflict |
| `ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_REIMBURSEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_EXTERNAL_AUDIT_STALE` | 422 Unprocessable Entity |
| `ERR_EXTERNAL_SCORE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_OPEN_ZT_FINDINGS_EXIST` | 409 Conflict |
