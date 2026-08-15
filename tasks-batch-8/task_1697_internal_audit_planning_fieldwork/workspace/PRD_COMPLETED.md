# Internal Audit Planning & Fieldwork Management API — Product Requirements Document

## 1. Introduction

Internal audit functions live and die by two disciplines: a defensible, risk-based annual plan, and a fieldwork record that survives scrutiny from audit committees, external assessors, and regulators. This document specifies the Internal Audit Planning & Fieldwork Management API, a system that governs the full audit cycle for a corporate internal audit department — from maintaining the audit universe and scoring inherent risk, through drafting and committee-approving the annual plan, staffing and executing engagements, documenting workpapers, negotiating findings with management, tracking remediation commitments, issuing and distributing reports, and reporting posture back to the audit committee. Throughout the cycle the system behaves as a ledger: every derived aggregate is recomputed deterministically from its source records, every pinned value stays pinned, and every state change leaves an auditable trail.

The API serves seven distinct parties — administrators, the chief audit executive, the audit committee, audit managers, field auditors, quality assessors, and management owners — under strict segregation-of-duties rules: no one approves their own plan, reviews their own workpaper, issues their own finding, or assesses an engagement they staffed. All business endpoints are mounted under the `/audit` prefix, and a separate administrator-only capability drives a logical clock so that overdue, aging, and recency derivations are deterministic and testable. Precision is contractual: scoring formulas, rounding order, tier boundaries, and extension caps are specified exactly in the sections that follow, and every rejection carries a stable machine-readable error identifier.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, identity and versioning semantics, the logical clock, the validation pipeline and its priority ordering, concurrency control, precision rules, and the cascading-consistency philosophy that the business workflows in §3 rely on.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request missing either header, or presenting a malformed header, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly seven roles, spelled precisely as follows: `AuditAdmin`, `ChiefAuditExecutive`, `AuditCommittee`, `AuditManager`, `FieldAuditor`, `QualityAssessor`, and `ManagementOwner`. Each endpoint declares the roles permitted to invoke it; a caller whose `X-User-Role` is not in the endpoint's allowed set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `AuditManager`, `FieldAuditor`, or `QualityAssessor`, the role is entity-backed: `X-User-ID` is the `id` of the acting `Auditor` record, and ownership checks on any resource that references an `Auditor` compare the resource's auditor foreign-key field to `X-User-ID`. Because these three roles are backed by the auditor roster, the system additionally enforces role–grade consistency: an `AuditManager` caller's `Auditor` record must carry a `grade` of `MANAGER` or `DIRECTOR`; a `FieldAuditor` caller's record must carry a `grade` of `STAFF`, `SENIOR`, or `MANAGER` (which is what allows a manager-grade auditor to also prepare workpapers); and a `QualityAssessor` caller's record must carry a `grade` of `MANAGER` or `DIRECTOR`. In all three cases the referenced `Auditor` must also have `status` equal to `ACTIVE`. A caller failing this grade-or-status mapping is rejected with `ERR_ROLE_GRADE_MISMATCH` (HTTP 403).

When `X-User-Role` is `AuditAdmin`, `ChiefAuditExecutive`, `AuditCommittee`, or `ManagementOwner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` on an audit plan, `decided_by_user_id` on an extension request, or `responder_user_id` on a management response — but it never compares the value to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100 — a `limit` that is not an integer or falls outside 1 through 100 is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than clamped. The `offset` parameter specifies how many items to skip and defaults to 0; a non-integer or negative `offset` is likewise rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties on `created_at` broken by creation (insertion) order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned in the page is less than `total_count`. Many list endpoints additionally accept filter query parameters named after resource fields — for example `status`, `fiscal_year`, `auditable_entity_id`, `audit_plan_id`, `engagement_id`, `auditor_id`, `supersedes_engagement_id`, `preparer_auditor_id`, `reviewer_auditor_id`, `workpaper_id`, `rating_criteria_config_id`, `severity`, `finding_id`, `action_plan_id`, or `assessor_auditor_id` — each restricting the listing to records whose matching field equals the supplied value; a filter value that cannot be parsed as the field's type (for example, a non-integer `fiscal_year`) is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.4. Common Resource Properties

Every resource in the system — auditable entities, risk assessments, rating criteria configs, audit plans, engagements, auditors, engagement assignments, workpapers, findings, management responses, action plans, extension requests, audit reports, QA reviews, and committee packs — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation.

A mutation is any change to the resource's stored properties, including changes to derived or computed fields. When a workflow causes a parent resource's aggregates to be recomputed — for example, when engagement creation advances a plan's `engagement_count`, or when risk-assessment finalization refreshes an entity's `current_inherent_risk_score` — the parent resource's `updated_at` is refreshed and its `version` is incremented as part of the same atomic operation.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every time-dependent derivation in the system: recency factors in engagement prioritization, overdue-day arithmetic on action plans, aging buckets, and all recorded timestamps such as `finalized_at`, `submitted_at`, `approved_at`, `retired_at`, `signed_off_at`, `issued_at`, `distributed_at`, `activated_at`, `validated_at`, `completed_at`, `presented_at`, and `last_audit_completed_at`. On server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any explicit adjustment it continues to read that default and never silently falls back to wall-clock time. An administrator-only test-driving capability — exposed outside the `/audit` mount and restricted to the `AuditAdmin` role — advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` in its response payload. Wherever this document says "the logical clock now", it refers to this clock. Unless a rule explicitly states otherwise, day differences are computed at whole-day granularity. Timestamps stamped from the logical clock — including the clock endpoint's `current_utc` — are rendered at whole-second precision with a `Z` suffix (for example, `2026-08-01T00:00:00Z`). Client-supplied datetime values may carry any ISO 8601 UTC offset; a value without an offset is read as UTC.

### 2.6. Optimistic Concurrency Control and Version Pinning

Two write operations in the system require optimistic concurrency control against a parent resource, and both are enforced as a stale-version comparison, not as a timing race. Creating a risk assessment requires the request to carry `expected_auditable_entity_version` holding the client last-observed `version` of the target auditable entity; if that value does not equal the entity's current `version` — because, for instance, another assessment was created or finalized against the entity after the client read it — the request is rejected with `ERR_STALE_ENTITY_VERSION` (HTTP 412). Creating an engagement requires the request to carry `expected_audit_plan_version` holding the client last-observed `version` of the target audit plan; engagement creation mutates plan aggregates, so a mismatch with the plan's current `version` is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), preventing a stale client from silently forking the plan roster. Both fields are non-optional on their respective endpoints. Endpoints not named here take no version field at all; all other writes proceed without an OCC check.

Version pinning is a related but distinct principle: certain values are snapshotted at a defining moment and never recomputed afterwards, even when the underlying reference data later changes. A risk assessment pins its `scoring_variant` at creation. A finding pins its `rating_criteria_config_id` — and therefore its severity bands — to the config that is `ACTIVE` at the moment of creation, and is never re-rated when that config is later superseded. A committee pack pins its snapshot aggregates at finalization and never recomputes them. A risk assessment's `inherent_risk_score` is computed at creation and carried unchanged through finalization.

### 2.7. Validation Pipeline and Priority Ordering

Every request passes through a fixed validation pipeline, and the ordering between stages is contractual: when several violations are present, the error surfaced is the one belonging to the earliest stage. Where a workflow narrative in §3 declares a more specific evaluation order among an endpoint's checks, that declared order governs over the default stage ordering here. The stages, in evaluation order, are:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and well-formed, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the presented role is in the endpoint's allowed set, else `ERR_FORBIDDEN_ROLE`.
3. **Role–grade consistency** — for the entity-backed roles (`AuditManager`, `FieldAuditor`, `QualityAssessor`), the caller's `Auditor` record satisfies the grade and `ACTIVE`-status mapping of §2.1, else `ERR_ROLE_GRADE_MISMATCH`.
4. **Existence** — path identifiers are validated left to right, and then body foreign-key fields in their declared input order. Each missing reference surfaces its own not-found error: `ERR_AUDITABLE_ENTITY_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_RATING_CONFIG_NOT_FOUND`, `ERR_AUDIT_PLAN_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WORKPAPER_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_MANAGEMENT_RESPONSE_NOT_FOUND`, `ERR_ACTION_PLAN_NOT_FOUND`, `ERR_EXTENSION_REQUEST_NOT_FOUND`, `ERR_AUDIT_REPORT_NOT_FOUND`, `ERR_QA_REVIEW_NOT_FOUND`, or `ERR_COMMITTEE_PACK_NOT_FOUND` — all HTTP 404. A nested request therefore fails on the first missing identifier in the path before any child is examined.
5. **Request shape and score ranges** — required fields are present, types are valid, enum values are in range, and no unknown or read-only fields were supplied; violations yield `ERR_INVALID_REQUEST` (HTTP 400). A required string field whose value is empty or whitespace-only is treated as missing. Endpoints that declare no request-body fields accept and ignore any request body. Separately, any well-typed numeric score field declared as a 1-to-5 scale — risk `likelihood` and `impact`, finding `likelihood` and `impact`, and the four QA dimension scores — that falls outside 1 through 5 inclusive yields `ERR_SCORE_OUT_OF_RANGE` (HTTP 422).
6. **Optimistic concurrency** — the OCC comparisons of §2.6, yielding `ERR_STALE_ENTITY_VERSION` or `ERR_STALE_PLAN_VERSION`.
7. **State legality** — the target resource must be in a legal from-state for the requested transition. This stage raises the invalid-state family (`ERR_PLAN_INVALID_STATE`, `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_RISK_ASSESSMENT_INVALID_STATE`, `ERR_RATING_CONFIG_INVALID_STATE`, `ERR_AUDITABLE_ENTITY_INVALID_STATE`, `ERR_AUDITOR_INACTIVE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_WORKPAPER_INVALID_STATE`, `ERR_WORKPAPER_LOCKED`, `ERR_FINDING_INVALID_STATE`, `ERR_FINDING_NOT_AWAITING_RESPONSE`, `ERR_RESPONSE_INVALID_STATE`, `ERR_ACTION_PLAN_INVALID_STATE`, `ERR_EXTENSION_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_QA_REVIEW_INVALID_STATE`, `ERR_PACK_INVALID_STATE`), each detailed with its workflow in §3.
8. **Segregation of duties and ownership** — the identity checks of §2.8: `ERR_PLAN_SELF_APPROVAL`, `ERR_WORKPAPER_SELF_REVIEW`, `ERR_NOT_WORKPAPER_PREPARER`, `ERR_FINDING_SELF_ISSUE`, `ERR_QA_ASSESSOR_ASSIGNED`, and `ERR_NOT_QA_ASSESSOR`. Because this stage precedes the business-constraint and referential stages, a caller who fails a segregation check sees that error even when a later rule would also have failed — most notably, the self-review check on workpaper sign-off is evaluated before the budget check, and the self-issue check on finding issuance is evaluated before the referential gate on the linked workpaper.
9. **Business constraints** — uniqueness, emptiness, and cap rules: `ERR_PLAN_EMPTY`, `ERR_PLAN_HAS_OPEN_ENGAGEMENTS`, `ERR_RISK_ASSESSMENT_DRAFT_EXISTS`, `ERR_RISK_ASSESSMENT_ALREADY_FINALIZED`, `ERR_CONFIG_BANDS_INVALID`, `ERR_DUPLICATE_ASSIGNMENT`, `ERR_ASSIGNMENT_OVERLAP`, `ERR_ENGAGEMENT_COOLING_PERIOD`, `ERR_QA_REVIEW_ALREADY_OPEN`, `ERR_EXTENSION_ALREADY_PENDING`, `ERR_EXTENSION_COUNT_EXCEEDED`, `ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED`, `ERR_ENTITY_HAS_OPEN_ENGAGEMENTS`, and `ERR_REPORT_ALREADY_ISSUED`, detailed per workflow in §3.
10. **Temporal rules** — window and monotonicity rules: `ERR_ENGAGEMENT_WINDOW_INVALID`, `ERR_ASSIGNMENT_WINDOW_INVALID`, `ERR_EXTENSION_NOT_MONOTONIC`, and `ERR_DUE_DATE_NOT_FUTURE`.
11. **Referential business gates** — cross-entity precondition rules: `ERR_AUDITABLE_ENTITY_RETIRED`, `ERR_NO_ACTIVE_RATING_CONFIG`, `ERR_WORKPAPER_NOT_SIGNED`, `ERR_PREPARER_NOT_ASSIGNED`, `ERR_NO_LEAD_ASSIGNED`, `ERR_PLAN_NOT_APPROVED`, `ERR_NO_SIGNED_WORKPAPERS`, `ERR_WORKPAPERS_PENDING_REVIEW`, `ERR_REPORT_NOT_ISSUED`, `ERR_QA_REVIEW_OPEN`, `ERR_FINDINGS_NOT_RESOLVED`, `ERR_FINDING_NOT_AGREED`, `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED`, and `ERR_DISTRIBUTION_LIST_EMPTY`.
12. **Fiscal checks** — last of all, the engagement budget check `ERR_BUDGET_HOURS_EXCEEDED`, evaluated only after every earlier stage — including the segregation-of-duties stage — has passed.

### 2.8. Segregation of Duties and Independence

Four duties may never be combined in one operator. The operator who submits an annual plan may not approve it. The auditor who prepared a workpaper may not sign it off or return it. The user who created a finding may not issue it to management. And a quality assessor may not review an engagement on which they hold an active staffing assignment — an independence rule, not merely a grade rule. Two ownership rules run in the opposite direction: only the preparer of a workpaper may submit it or reopen it for revision, and only the assigned assessor of a QA review may complete it. Each rule names its rejection error in the workflow subsections of §3; all six are evaluated at pipeline stage 8 as described above.


### 2.9. Numeric Precision and Rounding

Percentage-valued aggregates — plan coverage, engagement utilization, committee-pack completion — are stored as numbers rounded half-up to exactly two decimal places. Scores and counts — risk scores, priority scores, composite finding scores, negotiation rounds, extension days, overdue counts, snapshot finding counts — are integer arithmetic with no rounding. The single exception to plain summation is the workpaper hours rollup of §3.5, where each workpaper's hours are individually rounded up to the nearest half hour before any sum is taken; the rounding granularity is one half hour, and results are exact to 0.5. No calculation in the system uses fuzzy estimation: every threshold stated in §3 is an inclusive-or-exclusive boundary exactly as written, and a PRD reader should be able to reproduce any computed value from the prose alone.

### 2.10. Cascading Consistency and Ledger Synchronization

The system treats derived aggregates as a ledger that must never drift from its source records. When an event changes the inputs to an aggregate — a workpaper is signed off, an engagement is cancelled, an extension is approved, a finding is finalized — the owning parent's aggregates are recomputed immediately, within the same atomic operation, and the parent's `updated_at` and `version` advance per §2.4. Cascades also run downward: retiring nothing is possible while work is open, cancelling an engagement cancels its staffing, a failed quality review reopens signed workpapers, and issuing a report freezes the underlying fieldwork record. Each cascade is specified with its workflow in §3; the invariant the implementer must hold is that a reader fetching any resource after the operation completes observes every consequence of the operation, never an intermediate state.

### 2.11. Nested Resource Retrieval and Reference Ordering

Requests that address resources through identifying fields validate those references in a strict order: path identifiers first, left to right, and then foreign keys carried in the request body in the order the endpoint declares them. The first reference that does not resolve to an existing resource terminates the request with the corresponding 404 error of pipeline stage 4, before request-shape, state, or business rules are examined. Optional references — such as a follow-up engagement link or an evidence workpaper link on a finding — are validated only when supplied. Existence checks observe identity only; whether the referenced resource is in a usable state is a separate question answered by later pipeline stages.

## 3. Business Logic & Workflows

### 3.1. The Audit Universe and the Risk Assessment Cycle

Everything begins with the audit universe. An `AuditAdmin` registers an **AuditableEntity** — a business unit, process, or site — by supplying its `name` and the accountable executive as `business_owner`. Two optional attributes shape downstream behavior: `regulatory_scrutiny`, a boolean defaulting to `false` that selects the scoring variant described below, and `last_audit_completed_at`, the date the unit's previous audit closed, which may be left null for a never-audited unit and is then treated as infinite recency when engagements are prioritized. A new entity starts with `status` equal to `ACTIVE`, `retired_at` null, and — until a risk assessment is finalized for it — a null `current_inherent_risk_score` and null `current_risk_tier`. Any role may read an entity; a reference to an entity that does not exist fails with `ERR_AUDITABLE_ENTITY_NOT_FOUND`, whether the reference arrives as a path identifier or as the `auditable_entity_id` of another resource's payload.

Retirement is soft archival. When an `AuditAdmin` retires an entity, the transition from `ACTIVE` to `RETIRED` requires the entity to currently be `ACTIVE` — otherwise `ERR_AUDITABLE_ENTITY_INVALID_STATE` — and requires that no engagement of the entity is in `PLANNED`, `SCOPED`, `FIELDWORK`, or `REPORTING` status; open work blocks retirement with `ERR_ENTITY_HAS_OPEN_ENGAGEMENTS`. On retirement the server stamps `retired_at` with the logical clock now. A `RETIRED` entity remains fully readable but rejects new risk assessments and new engagements with `ERR_AUDITABLE_ENTITY_RETIRED`.

Against each active entity, an `AuditManager` records a **RiskAssessment** for a given `fiscal_year`, supplying the entity reference `auditable_entity_id` together with `likelihood` and `impact`, each an integer from 1 to 5 inclusive; a value outside that range is rejected with `ERR_SCORE_OUT_OF_RANGE`. Creation is optimistic-concurrency protected by `expected_auditable_entity_version` as specified in §2.6, and it mutates the entity: the entity's `version` increments by one on assessment creation. Two uniqueness rules guard the (entity, year) pair at creation time: if a `DRAFT` assessment already exists for the same `auditable_entity_id` and `fiscal_year`, creation fails with `ERR_RISK_ASSESSMENT_DRAFT_EXISTS`; if a `FINALIZED` assessment already exists for that pair, creation fails with `ERR_RISK_ASSESSMENT_ALREADY_FINALIZED`.

Scoring happens at creation and is then pinned. The server selects the `scoring_variant` by reading the entity's `regulatory_scrutiny` flag at that moment: `true` selects `CONSERVATIVE`; `false` selects `WEIGHTED`. Under `WEIGHTED`, the `inherent_risk_score` is eight times the `likelihood` plus twelve times the `impact` — so a likelihood of 3 and an impact of 4 produce a score of 72. Under `CONSERVATIVE`, the score is twenty times the larger of `likelihood` and `impact`, a worst-axis-dominance rule under which the same inputs produce 80 rather than 72. Both variants use integer arithmetic with no rounding and always land between 20 and 100. The variant and the score are pinned on the assessment at creation and carried unchanged through finalization, even if the entity's scrutiny flag later changes.

A risk assessment is born in `DRAFT` status. Finalizing it — an `AuditManager` action — requires the assessment to be in `DRAFT` (else `ERR_RISK_ASSESSMENT_INVALID_STATE`) and requires that no other `FINALIZED` assessment exists for the same entity and fiscal year (else `ERR_RISK_ASSESSMENT_ALREADY_FINALIZED`). Finalization stamps `finalized_at` from the logical clock, moves the assessment to its terminal `FINALIZED` status, and performs a ledger sync to the entity: the entity's `version` increments by one, and when the finalized assessment's `fiscal_year` is the maximum among the entity's `FINALIZED` assessments, the entity's `current_inherent_risk_score` is set to this assessment's score and its `current_risk_tier` is recomputed from that score — `CRITICAL` when the score is at least 85, `HIGH` for 70 through 84, `MODERATE` for 40 through 69, and `LOW` below 40, with each lower boundary inclusive. Risk assessments may be listed with `auditable_entity_id`, `fiscal_year`, or `status` filters, and fetched individually; a missing assessment reference yields `ERR_RISK_ASSESSMENT_NOT_FOUND`.

### 3.2. Rating Criteria Governance

Findings are rated against a configurable band scheme, the **RatingCriteriaConfig**, maintained by an `AuditAdmin`. A config is created with a `name` and three optional band thresholds: `critical_min` defaulting to 20, `high_min` defaulting to 12, and `moderate_min` defaulting to 6. The bands must be strictly increasing within the composite-score range: `moderate_min` must be at least 1, `high_min` must be strictly greater than `moderate_min`, `critical_min` must be strictly greater than `high_min`, and `critical_min` may be at most 25. This constraint is enforced both when a config is created and again when it is activated; a violation at either point is rejected with `ERR_CONFIG_BANDS_INVALID` (HTTP 422). A config that does not exist yields `ERR_RATING_CONFIG_NOT_FOUND`.

A new config starts in `DRAFT` status. Activation moves a `DRAFT` config to `ACTIVE` — attempting to activate a config in any other status fails with `ERR_RATING_CONFIG_INVALID_STATE` — and stamps `activated_at` from the logical clock. The system maintains an exactly-one-active invariant: when a config becomes `ACTIVE`, the previously `ACTIVE` config, if one exists, automatically transitions to the terminal `SUPERSEDED` status. Configs are never re-rated retroactively: findings pinned to a superseded config keep their original severity, per the version-pinning principle of §2.6.


### 3.3. The Annual Plan and the Committee Approval Cycle

A `ChiefAuditExecutive` drafts the year's plan by creating an **AuditPlan** with its `fiscal_year` and `title`. The plan is born in `DRAFT` status with `engagement_count` zero, `high_risk_coverage_pct` computed at creation by the coverage formula below — 100.0 when no active entity currently scores at or above 70, and 0.0 otherwise, since a brand-new plan covers nothing yet — and the attribution fields `submitted_by_user_id`, `approved_by_user_id`, `submitted_at`, and `approved_at` all null. A plan that does not exist yields `ERR_AUDIT_PLAN_NOT_FOUND`, whether referenced by path or through the `audit_plan_id` of an engagement or committee pack payload.

The approval cycle is a negotiation loop between the executive and the committee. Submitting the plan is a `ChiefAuditExecutive` action allowed from either `DRAFT` or `RETURNED` status — any other from-state fails with `ERR_PLAN_INVALID_STATE` — and requires the plan to contain at least one engagement: submitting a plan whose `engagement_count` is zero fails with `ERR_PLAN_EMPTY`. On submission the server captures `submitted_by_user_id` from the caller's `X-User-ID` and stamps `submitted_at` from the logical clock; resubmission from `RETURNED` re-captures both, recording the latest round of the negotiation cycle.

While the plan is `SUBMITTED`, the `AuditCommittee` either approves or returns it. Approval enforces segregation of duties: the committee caller's `X-User-ID` must differ from the plan's `submitted_by_user_id`, and a self-approval attempt is rejected with `ERR_PLAN_SELF_APPROVAL` (HTTP 403). A successful approval moves the plan to `APPROVED` and records `approved_by_user_id` and `approved_at`. Returning the plan — also restricted to the `SUBMITTED` state, else `ERR_PLAN_INVALID_STATE` — moves it back to `RETURNED` with no further side effects, ready for the executive to adjust the roster and resubmit.

At year end the executive closes the plan. Closing requires the plan to be `APPROVED` (else `ERR_PLAN_INVALID_STATE`) and requires every engagement of the plan to have reached a terminal state — `CLOSED` or `CANCELLED`; if any engagement remains open the close fails with `ERR_PLAN_HAS_OPEN_ENGAGEMENTS`. A closed plan is terminal.

Two plan aggregates are maintained as ledger entries by the events of §3.4. The `engagement_count` is the number of the plan's engagements whose status is anything other than `CANCELLED`. The `high_risk_coverage_pct` measures coverage of the high-risk universe: take all `ACTIVE` auditable entities whose `current_inherent_risk_score` is at least 70, count how many of them are referenced by at least one non-`CANCELLED` engagement of this plan, and express the share as one hundred times the covered count divided by the universe size, rounded half-up to two decimal places. When no active entity currently scores at or above 70, the universe is empty and the coverage is defined as exactly 100.0. Both aggregates are recomputed at plan creation, whenever an engagement is created under the plan, and whenever one of the plan's engagements is cancelled.

### 3.4. Engagement Scoping, Scheduling, and Staffing

Within a plan, an `AuditManager` creates an **Engagement** by naming the owning plan through `audit_plan_id` and the unit under audit through `auditable_entity_id`, and supplying a `title`, a narrative `scope_summary`, the approved `budget_hours` (which must be greater than zero), and the planned fieldwork window `start_date` through `end_date`. Both window bounds are inclusive, and the window must be non-empty: an `end_date` that is not strictly after the `start_date` is rejected with `ERR_ENGAGEMENT_WINDOW_INVALID`. An optional `supersedes_engagement_id` links the engagement to a prior one as a follow-up reference; when supplied, it must resolve to an existing engagement or the create fails with `ERR_ENGAGEMENT_NOT_FOUND`. Creation is optimistic-concurrency protected by `expected_audit_plan_version` per §2.6, and it mutates the plan: the plan's `version` increments by one and its `engagement_count` and `high_risk_coverage_pct` are recomputed. Engagements may be listed filtered by `audit_plan_id`, `auditable_entity_id`, `supersedes_engagement_id`, or `status`.

Three business gates constrain creation beyond the window check. First, the roster freeze: engagements may be created only while the plan is in `DRAFT`, `RETURNED`, or `APPROVED` status — a plan in `SUBMITTED` or `CLOSED` rejects new engagements with `ERR_PLAN_INVALID_STATE`. Second, the entity must be `ACTIVE`; referencing a retired entity fails with `ERR_AUDITABLE_ENTITY_RETIRED`. Third, the cooling-period rule: for the same auditable entity, the new engagement's window must be separated from every existing non-`CANCELLED` engagement of that entity by a buffer of at least ninety days. Precisely, creation is rejected with `ERR_ENGAGEMENT_COOLING_PERIOD` unless, for each such existing engagement, either the existing engagement's `end_date` plus ninety days falls on or before the new `start_date`, or the new engagement's `end_date` plus ninety days falls on or before the existing engagement's `start_date`; any pair of windows closer than ninety days — including adjacency anywhere inside the buffer — is rejected.

At creation the server computes and stores the engagement's `priority_score`, a forward-looking triage measure built from three components. The risk component is the entity's `current_inherent_risk_score`, or zero when the entity has no finalized score. The recency component depends on the whole calendar months between the entity's `last_audit_completed_at` and the current logical-clock date, computed as twelve times the difference in calendar years plus the difference in calendar month numbers, minus one when the clock date's day-of-month is earlier than the last-audit date's day-of-month; a never-audited entity counts as 999 months. Thirty-six months or more contributes 30 points, twenty-four through thirty-five months contributes 20 points, twelve through twenty-three months contributes 10 points, and fewer than twelve months contributes nothing. Finally, 15 points are added when the entity is under regulatory scrutiny. The priority score is the sum of the three components, capped at 100, and uses integer arithmetic with no rounding.

A new engagement starts in `PLANNED` status with `reserved_hours`, `actual_hours`, `provisional_hours`, `signed_off_workpaper_count`, `open_finding_count`, and `qa_regression_count` all at zero, and both `utilization_final_pct` and `utilization_provisional_pct` at 0.0. Scoping marks it `SCOPED`, a transition allowed only from `PLANNED` — any other from-state fails with `ERR_ENGAGEMENT_INVALID_STATE`. Beginning fieldwork moves `SCOPED` to `FIELDWORK` and carries two cross-entity gates evaluated after the state check: the owning plan must be `APPROVED` (else `ERR_PLAN_NOT_APPROVED`), and the engagement must have at least one `ACTIVE` assignment whose `role_in_engagement` is `LEAD` (else `ERR_NO_LEAD_ASSIGNED`).

The roster behind all of this is the **Auditor** resource, maintained by an `AuditAdmin`. An auditor is registered with a `full_name`, a `grade` of `STAFF`, `SENIOR`, `MANAGER`, or `DIRECTOR`, and an optional list of `skills` tags; a new auditor starts with `status` equal to `ACTIVE`. Deactivation moves an `ACTIVE` auditor to the terminal `INACTIVE` status — deactivating an already-inactive auditor fails with `ERR_AUDITOR_INACTIVE` — and leaves the auditor's existing assignments untouched, while any attempt to create a new assignment for an `INACTIVE` auditor is rejected, as noted below.

Staffing is the **EngagementAssignment** resource. An `AuditManager` assigns an auditor by supplying `engagement_id`, `auditor_id`, the `role_in_engagement` — one of `LEAD`, `STAFF`, or `REVIEWER` — the assignment window `start_date` through `end_date`, and the reserved `allocated_hours`, which must be greater than zero. Assignment windows are half-open: the `start_date` is inclusive and the `end_date` exclusive, and an `end_date` not strictly after the `start_date` fails with `ERR_ASSIGNMENT_WINDOW_INVALID`. Two staffing integrity rules apply. An auditor may hold only one `ACTIVE` assignment on the same engagement; a duplicate fails with `ERR_DUPLICATE_ASSIGNMENT`. And an auditor's assignment windows may not overlap: because ends are exclusive, a collision exists precisely when another `ACTIVE` assignment of the same auditor starts before the new window's end and the new window starts before that existing assignment's end — windows that merely touch, one ending exactly when the other begins, are permitted. A colliding create fails with `ERR_ASSIGNMENT_OVERLAP`. Assigning an auditor whose record is `INACTIVE` is rejected with `ERR_AUDITOR_INACTIVE`, and unknown auditor or assignment references yield `ERR_AUDITOR_NOT_FOUND` and `ERR_ASSIGNMENT_NOT_FOUND` respectively. Assignment creation is permitted only while the engagement is in a working state — `PLANNED`, `SCOPED`, or `FIELDWORK`; once the engagement has advanced to `REPORTING` or beyond, staffing changes fail with `ERR_ENGAGEMENT_INVALID_STATE`. Each creation reserves hours on the engagement: `reserved_hours` increases by the assignment's `allocated_hours`, maintaining the invariant that `reserved_hours` always equals the sum of `allocated_hours` over the engagement's `ACTIVE` assignments. Assignments may be listed filtered by `engagement_id`, `auditor_id`, or `status`.

An assignment may be cancelled while it is `ACTIVE` — a second cancel fails with `ERR_ASSIGNMENT_INVALID_STATE` — and only while its engagement remains in `PLANNED`, `SCOPED`, or `FIELDWORK` (else `ERR_ENGAGEMENT_INVALID_STATE`). Cancellation is a compensating action: the engagement's `reserved_hours` decreases by the released `allocated_hours`, preserving the reservation invariant.

Cancelling a whole engagement is possible from `PLANNED` or `SCOPED` only, moving it to the terminal `CANCELLED` status; any other from-state fails with `ERR_ENGAGEMENT_INVALID_STATE`. Cancellation cascades downward: every `ACTIVE` assignment of the engagement transitions to `CANCELLED` and `reserved_hours` is recomputed, and the plan ledger is synchronized — the plan's `engagement_count` and `high_risk_coverage_pct` are recomputed, with the usual `updated_at` refresh and `version` increment on the plan. Engagement closure is specified in §3.8 alongside reporting.

### 3.5. Fieldwork: Workpapers and Hours Control

During `FIELDWORK`, a `FieldAuditor` documents testing in **Workpaper** records, each created with the owning `engagement_id`, a `reference` code such as A-1, a `title`, and the `hours_worked`, which must be greater than zero. Creation captures `preparer_auditor_id` from the caller's `X-User-ID`, and the caller must hold an `ACTIVE` assignment on that engagement — a preparer without one is rejected with `ERR_PREPARER_NOT_ASSIGNED`. Workpapers can only be created while the engagement is in `FIELDWORK`; attempts in any other engagement state fail with `ERR_ENGAGEMENT_INVALID_STATE`. A new workpaper is `DRAFT`, with `reviewer_auditor_id`, `review_note`, and `signed_off_at` null, and `locked` false. Unknown workpaper references — by path or through a finding's `workpaper_id` — yield `ERR_WORKPAPER_NOT_FOUND`, and workpaper listings accept `engagement_id`, `preparer_auditor_id`, `reviewer_auditor_id`, and `status` filters.

The review pipeline runs `DRAFT` → `SUBMITTED` → `SIGNED_OFF`, with a return loop. Submitting is the preparer's own action: only the auditor whose `id` matches `preparer_auditor_id` may submit, and anyone else is rejected with `ERR_NOT_WORKPAPER_PREPARER`; the workpaper must be `DRAFT` (else `ERR_WORKPAPER_INVALID_STATE`), must not be locked (else `ERR_WORKPAPER_LOCKED`), and the engagement must still be in `FIELDWORK` (else `ERR_ENGAGEMENT_INVALID_STATE`). Submission triggers a ledger sync of the engagement's `provisional_hours`.

Sign-off is an `AuditManager` action on a `SUBMITTED` workpaper, again requiring an unlocked workpaper and a `FIELDWORK` engagement. Segregation of duties applies: the reviewer's `X-User-ID` must differ from `preparer_auditor_id`, and a self-review fails with `ERR_WORKPAPER_SELF_REVIEW`. After the segregation check — and only after it, per the pipeline ordering of §2.7 — the fiscal gate is evaluated: signing off is rejected with `ERR_BUDGET_HOURS_EXCEEDED` when the engagement's current `actual_hours` plus this workpaper's contribution would exceed one hundred and ten percent of `budget_hours`, where the workpaper's contribution is its `hours_worked` rounded up to the nearest half hour. A successful sign-off records `reviewer_auditor_id` from the caller, stamps `signed_off_at` from the logical clock, moves the workpaper to `SIGNED_OFF`, increments the engagement's `signed_off_workpaper_count` by one, and recomputes `actual_hours` and `provisional_hours`.

Returning a workpaper is the reviewer's reject path, available from either `SUBMITTED` or `SIGNED_OFF` — any other from-state fails with `ERR_WORKPAPER_INVALID_STATE` — under the same unlocked, fieldwork-phase, and not-the-preparer rules (`ERR_WORKPAPER_LOCKED`, `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_WORKPAPER_SELF_REVIEW`). The request carries a `note`, which is recorded on the workpaper as `review_note` alongside the caller's `reviewer_auditor_id`. Returning a `SIGNED_OFF` workpaper is a compensating action: `signed_off_at` is cleared to null, the engagement's `signed_off_workpaper_count` decrements by one, and `actual_hours` and `provisional_hours` are recomputed, preserving the invariant that the count always equals the number of `SIGNED_OFF` workpapers. Returning a merely `SUBMITTED` workpaper recomputes `provisional_hours` only. The preparer may then revise: a `RETURNED` workpaper returns to `DRAFT` under the same ownership rule (`ERR_NOT_WORKPAPER_PREPARER`), and its `review_note` is cleared while `reviewer_auditor_id` is retained, completing the revision loop `DRAFT` → `SUBMITTED` → `RETURNED` → `DRAFT`.

The hours rollup has a pinned evaluation order. Each workpaper contributes an item value equal to its `hours_worked` rounded up to the nearest half hour — equivalently, twice the hours rounded up to the next whole number, then halved — and only after this per-item rounding are the values summed. Three workpapers of 1.1 hours each therefore contribute 4.5 hours in aggregate, since each item individually rounds to 1.5; summing the raw hours first and rounding once would yield 3.5, and that alternative order is explicitly not used. The engagement's `actual_hours` sums item values over `SIGNED_OFF` workpapers, while `provisional_hours` sums item values over workpapers in `SUBMITTED` or `SIGNED_OFF`. Both are recomputed on every submit, sign-off, and return. Two utilization measures derive from these rollups, each rounded half-up to two decimal places: `utilization_final_pct` is one hundred times `actual_hours` divided by `budget_hours`, and `utilization_provisional_pct` is one hundred times `provisional_hours` divided by `budget_hours`. The two variants diverge while review is in flight — with 10 signed-off hours and 20 submitted hours against a 100-hour budget, the provisional figure reads 30.0 while the final figure reads 10.0.

Ending fieldwork is the manager's begin-reporting action, moving the engagement from `FIELDWORK` to `REPORTING`. Two gates apply beyond the from-state check. There must be at least one signed-off workpaper: when `signed_off_workpaper_count` is zero the transition fails with `ERR_NO_SIGNED_WORKPAPERS`. And the pipeline must be clean: every workpaper of the engagement must be `SIGNED_OFF`, so any workpaper still `DRAFT`, `SUBMITTED`, or `RETURNED` blocks the transition with `ERR_WORKPAPERS_PENDING_REVIEW`.


### 3.6. Findings, Severity Rating, and Management Negotiation

A `FieldAuditor` raises a **Finding** against an engagement in flight — while it is in `FIELDWORK` or `REPORTING`; creations at other engagement states fail with `ERR_ENGAGEMENT_INVALID_STATE`. The create payload carries the `engagement_id`, a `title`, and `likelihood` and `impact` integers on the 1-to-5 scale (violations yield `ERR_SCORE_OUT_OF_RANGE`). An optional `workpaper_id` links the finding to its evidence; when supplied, the referenced workpaper must belong to the same engagement and must already be `SIGNED_OFF`, otherwise creation fails with `ERR_WORKPAPER_NOT_SIGNED`. Two further gates apply at creation: an `ACTIVE` rating criteria config must exist, since severity cannot be computed without one (`ERR_NO_ACTIVE_RATING_CONFIG`), and no report of the engagement may yet be `ISSUED` or `DISTRIBUTED` — once the report is issued, the finding roster freezes and new findings are rejected with `ERR_REPORT_ALREADY_ISSUED`. A finding that does not exist yields `ERR_FINDING_NOT_FOUND`; listings accept `engagement_id`, `workpaper_id`, `rating_criteria_config_id`, `status`, and `severity` filters.

At creation the server captures `created_by_user_id` from the caller, pins `rating_criteria_config_id` to the currently `ACTIVE` config, and computes the rating. The `composite_score` is the `likelihood` multiplied by the `impact`, an integer from 1 to 25. The `severity` then follows the pinned config's bands, with every boundary inclusive: a composite at or above `critical_min` is `CRITICAL`; otherwise at or above `high_min` is `HIGH`; otherwise at or above `moderate_min` is `MODERATE`; anything lower is `LOW`. Because the config reference is pinned at creation, later supersession of the config never re-rates an existing finding. The new finding starts in `DRAFT` with `negotiation_rounds` at zero, `finalized_at` null, and `open_overdue_action_count` at zero, and its arrival is reflected in the engagement ledger: `open_finding_count` — the count of the engagement's findings not yet in `FINAL` — is recomputed.

Issuing a finding to management is an `AuditManager` action from `DRAFT` to `PENDING_RESPONSE`. The issuer must not be the finding's creator: an `X-User-ID` equal to `created_by_user_id` is rejected with `ERR_FINDING_SELF_ISSUE`, and this segregation check is evaluated before any referential gate, so a self-issue attempt surfaces `ERR_FINDING_SELF_ISSUE` even when other problems exist. A finding in any status other than `DRAFT` fails with `ERR_FINDING_INVALID_STATE`. When the finding carries a `workpaper_id`, issuance re-verifies that the linked workpaper is still `SIGNED_OFF`; a link that has been returned to the preparer in the meantime blocks issuance with `ERR_WORKPAPER_NOT_SIGNED`.

Management's side of the conversation is the **ManagementResponse**. A `ManagementOwner` creates one with the target `finding_id`, a `response_text` narrative, and a `proposed_due_date` for remediation; the responder's `X-User-ID` is recorded as `responder_user_id`, and the response is born `SUBMITTED`. The finding must be awaiting a response — in `PENDING_RESPONSE` or `REBUTTED`; otherwise creation fails with `ERR_FINDING_NOT_AWAITING_RESPONSE`. One exhaustion rule applies even here: if the finding is `REBUTTED` and its `negotiation_rounds` has already reached three, a further response is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, because escalation is the only remaining path. A response that does not exist yields `ERR_MANAGEMENT_RESPONSE_NOT_FOUND`; listings filter by `finding_id` or `status`. Creating a response has an automatic upward effect: the parent finding transitions to `UNDER_REVIEW` — from `PENDING_RESPONSE` on the first response, or from `REBUTTED` on each fresh response of the negotiation cycle.

An `AuditManager` then adjudicates each `SUBMITTED` response; a response in any other status rejects both actions with `ERR_RESPONSE_INVALID_STATE`. Accepting the response moves it to `ACCEPTED`, records the caller as `reviewed_by_user_id`, and bubbles up: the parent finding transitions from `UNDER_REVIEW` to `AGREED`. Rebutting the response carries a `rebuttal_note` and is subject to the negotiation-rounds cap: the parent finding's `negotiation_rounds` must be below three at rebuttal time, else the rebuttal fails with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. A successful rebuttal moves the response to `REBUTTED`, records `reviewed_by_user_id`, and bubbles up: the finding returns from `UNDER_REVIEW` to `REBUTTED` and its `negotiation_rounds` increments by one.

When negotiation deadlocks, the `ChiefAuditExecutive` escalates. Escalation moves a finding from `REBUTTED` to `ESCALATED` — any other from-state fails with `ERR_FINDING_INVALID_STATE` — and requires the negotiation rounds to be exhausted: `negotiation_rounds` must be at least three, and exactly three suffices. Escalating earlier fails with `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED`. Both `AGREED` and `ESCALATED` findings reach their terminal `FINAL` status automatically when the engagement's report is issued, as detailed in §3.8: each such finding is stamped with `finalized_at` from the logical clock, and the engagement's `open_finding_count` is recomputed.

### 3.7. Remediation: Action Plans and Due-Date Extensions

Remediation commitments are tracked as **ActionPlan** records. A `ManagementOwner` creates one against a finding by supplying the `finding_id`, a `description` of the commitment, the responsible `owner_name`, and a `due_date`. The `due_date` must lie strictly after the logical clock's current instant — a date in the present or past fails with `ERR_DUE_DATE_NOT_FUTURE`, and this futurity check is evaluated before the finding-status gate — and the finding must be in `UNDER_REVIEW` or `AGREED`; creating a plan against a finding in any other status fails with `ERR_FINDING_INVALID_STATE`. At creation the server copies `due_date` into `original_due_date`, an immutable record of the initial commitment that later extensions never touch. The plan starts `OPEN`, with `extension_count` and `cumulative_extended_days` at zero and `validated_by_user_id` and `validated_at` null; the parent finding's `open_overdue_action_count` is recomputed. An unknown plan reference yields `ERR_ACTION_PLAN_NOT_FOUND`; listings filter by `finding_id` or `status`.

The remediation lifecycle runs `OPEN` → `IN_PROGRESS` → `SUBMITTED_FOR_VALIDATION` → `VALIDATED`. Starting the work is a `ManagementOwner` action requiring the plan to be `OPEN` (else `ERR_ACTION_PLAN_INVALID_STATE`) and — a cross-entity gate — the parent finding to be `AGREED`; starting remediation on a finding still under negotiation fails with `ERR_FINDING_NOT_AGREED`. When the work is done, the owner submits the plan for validation, moving `IN_PROGRESS` to `SUBMITTED_FOR_VALIDATION` (from any other state, `ERR_ACTION_PLAN_INVALID_STATE`). An `AuditManager` then decides. Validation moves the plan to its terminal `VALIDATED` status, records `validated_by_user_id` from the caller, stamps `validated_at` from the logical clock, and recomputes the parent finding's `open_overdue_action_count`. Rejection — a request carrying a `rejection_note` — returns the plan to `IN_PROGRESS` for rework, a validation-failure loop that may repeat. Both decisions require the plan to be in `SUBMITTED_FOR_VALIDATION`, else `ERR_ACTION_PLAN_INVALID_STATE`.

Overdue tracking is clock-based. An action plan's days overdue are the whole days from its current `due_date` to the logical-clock date, computed calendar-date to calendar-date (not as elapsed 24-hour periods) and floored at zero; a plan due today has zero days overdue and is therefore not overdue — overdue requires at least one full day. For reporting, plans fall into aging buckets: zero days is `CURRENT`, one through thirty days is `AGING_1_30`, thirty-one through ninety days is `AGING_31_90`, and ninety-one days or more is `AGING_91_PLUS`, with each lower boundary inclusive. A finding's `open_overdue_action_count` is the number of its action plans that are not `VALIDATED` and are at least one day overdue; the count is re-evaluated against the logical clock whenever it is read and whenever the committee-pack snapshot of §3.9 is taken, and this read-time re-evaluation refreshes the stored value without advancing the finding's `updated_at` or `version`.

When management cannot meet a date, a `ManagementOwner` files an **ExtensionRequest** carrying the `action_plan_id`, the `requested_due_date`, and a `reason`; the request is born `PENDING`, with `decided_by_user_id` and `approved_days` null. Creation is gated on four rules. The action plan must be in `OPEN` or `IN_PROGRESS`; a plan already submitted for validation or validated rejects new extension requests with `ERR_ACTION_PLAN_INVALID_STATE`. The shift must be strictly monotonic: `requested_due_date` must be strictly after the plan's current `due_date`, else `ERR_EXTENSION_NOT_MONOTONIC`. The plan's `extension_count` must be below two — the cap is two approved extensions per plan — else `ERR_EXTENSION_COUNT_EXCEEDED`. And the cumulative cap must hold: the plan's `cumulative_extended_days` plus the requested whole-day shift must not exceed 180, where the boundary is inclusive — a cumulative total of exactly 180 days is permitted, 181 is not — else `ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED`. Finally, only one request may be in flight per plan: creating a second `PENDING` request fails with `ERR_EXTENSION_ALREADY_PENDING`. An unknown request reference yields `ERR_EXTENSION_REQUEST_NOT_FOUND`; listings filter by `action_plan_id` or `status`.

Decisions belong to the `ChiefAuditExecutive`, and both decision actions require the request to be `PENDING`, else `ERR_EXTENSION_INVALID_STATE`. Denial simply moves the request to `DENIED` and records `decided_by_user_id` from the caller. Approval re-validates the creation-time constraints against current data before mutating anything: the request must still be monotonic against the plan's current `due_date` (`ERR_EXTENSION_NOT_MONOTONIC`), the plan's `extension_count` must still be below two (`ERR_EXTENSION_COUNT_EXCEEDED`), and the cumulative total including this shift must still be at most 180 (`ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED`). Approved requests are applied in chronological order by approval time, with ties broken by earlier `created_at` first. On approval the request records `decided_by_user_id`, and its `approved_days` is computed as the whole days between the plan's prior `due_date` and the `requested_due_date`, flooring the instant difference at 24-hour granularity — a strictly later but sub-day shift therefore yields zero approved days. The approval then cascades: the plan's `due_date` is set to the `requested_due_date`, `extension_count` increments by one, and `cumulative_extended_days` increases by `approved_days`; and because an extended plan may cease to be overdue, the parent finding's `open_overdue_action_count` is recomputed as a second-level effect.


### 3.8. Report Issuance and Engagement Closure

Once an engagement reaches `REPORTING`, an `AuditManager` drafts its **AuditReport** with the `engagement_id`, a `title`, and an optional `overall_conclusion` of `SATISFACTORY`, `NEEDS_IMPROVEMENT`, or `UNSATISFACTORY`. Drafting is possible only while the engagement is in `REPORTING`; otherwise creation fails with `ERR_ENGAGEMENT_INVALID_STATE`. The report is born `DRAFT`, with `issued_at`, `distributed_at`, and `distribution_list` null. An unknown report reference yields `ERR_AUDIT_REPORT_NOT_FOUND`; listings filter by `engagement_id` or `status`.

The report lifecycle runs `DRAFT` → `PENDING_APPROVAL` → `APPROVED` → `ISSUED` → `DISTRIBUTED`, with a revision loop. The manager submits the draft, moving it to `PENDING_APPROVAL` (from any other state, `ERR_REPORT_INVALID_STATE`). The `ChiefAuditExecutive` then approves it to `APPROVED`, or returns it — a return moves the report from `PENDING_APPROVAL` back to `DRAFT` for rework, and both decisions require `PENDING_APPROVAL` as the from-state, else `ERR_REPORT_INVALID_STATE`. As specified in §3.9, a failed quality review can also force a `PENDING_APPROVAL` report back to `DRAFT` automatically.

Issuance is the point of no return, and it is gated accordingly. The report must be `APPROVED` (else `ERR_REPORT_INVALID_STATE`); the engagement must still be in `REPORTING` (else `ERR_ENGAGEMENT_INVALID_STATE`); no other report of the same engagement may already be `ISSUED` or `DISTRIBUTED` (else `ERR_REPORT_ALREADY_ISSUED`); and every finding of the engagement must be resolved into `AGREED`, `ESCALATED`, or `FINAL` — any finding still in an earlier status blocks issuance with `ERR_FINDINGS_NOT_RESOLVED`. On issuance the server stamps `issued_at` from the logical clock and two cascades fire. First, every finding of the engagement in `AGREED` or `ESCALATED` transitions to `FINAL` with its `finalized_at` stamped, and the engagement's `open_finding_count` is recomputed. Second, every workpaper of the engagement is frozen: `locked` is set to true, and from that moment any submit, sign-off, return, or revise attempt on those workpapers is rejected with `ERR_WORKPAPER_LOCKED` — a tamper-evident freeze of the evidence base underlying the issued report.

Distribution is the final step. Distributing requires the report to be `ISSUED` (else `ERR_REPORT_INVALID_STATE`) and requires the request's `distribution_list` to be non-empty; an empty recipient list fails with `ERR_DISTRIBUTION_LIST_EMPTY`. On distribution the server stamps `distributed_at`, records the recipient list on the report's `distribution_list`, and moves the report to its terminal `DISTRIBUTED` status.

With the report out, the manager may close the engagement. Closing moves the engagement from `REPORTING` to `CLOSED` — any other from-state fails with `ERR_ENGAGEMENT_INVALID_STATE` — and requires two cross-entity conditions: an audit report of the engagement must exist in `ISSUED` or `DISTRIBUTED` status (else `ERR_REPORT_NOT_ISSUED`), and no QA review of the engagement may remain in `SCHEDULED` or `IN_PROGRESS` (else `ERR_QA_REVIEW_OPEN`). Closure bubbles up to the audit universe: the entity's `last_audit_completed_at` is set to the logical clock now, refreshing the entity's `updated_at` and incrementing its `version`, which in turn resets the recency component of any future engagement prioritization for that unit.

### 3.9. Quality Assessment and Committee Reporting

Quality assurance over completed fieldwork is the **QAReview**. A `ChiefAuditExecutive` schedules one with the target `engagement_id` and a `scope` of `INTERNAL` or `EXTERNAL`; scheduling requires the engagement to be in `REPORTING` or `CLOSED` — any other engagement state fails with `ERR_ENGAGEMENT_INVALID_STATE` — and requires that no other review of the same engagement is currently `SCHEDULED` or `IN_PROGRESS`, else `ERR_QA_REVIEW_ALREADY_OPEN`. The review is born `SCHEDULED`, with `assessor_auditor_id`, the four dimension scores, `overall_score`, `rating`, and `completed_at` all null. An unknown review reference yields `ERR_QA_REVIEW_NOT_FOUND`; listings filter by `engagement_id`, `assessor_auditor_id`, or `status`.

A `QualityAssessor` begins the review, moving it from `SCHEDULED` to `IN_PROGRESS` — any other from-state fails with `ERR_QA_REVIEW_INVALID_STATE`. Independence is enforced structurally: the caller's `X-User-ID`, interpreted as an `Auditor` id, must not hold an `ACTIVE` assignment on the engagement under review; an assigned assessor is rejected with `ERR_QA_ASSESSOR_ASSIGNED`. On begin, the server captures `assessor_auditor_id` from the caller. Completion is the assessor's own action: only the caller whose `X-User-ID` matches `assessor_auditor_id` may complete the review, and anyone else is rejected with `ERR_NOT_QA_ASSESSOR`; the review must be `IN_PROGRESS` (else `ERR_QA_REVIEW_INVALID_STATE`). The completion payload carries the four dimension scores — `doc_quality_score`, `fieldwork_quality_score`, `reporting_quality_score`, and `independence_score` — each an integer from 1 to 5 inclusive; any score outside that range fails with `ERR_SCORE_OUT_OF_RANGE`.

On completion the server computes the `overall_score` as the mean of the four dimension scores, rounded half-up to two decimal places, stamps `completed_at`, moves the review to `COMPLETED`, and determines the `rating`. The review is a `FAIL` when any single dimension score is 2 or lower, or when the overall score is below 3.0. It is a `PASS` when every dimension score is at least 4 and the overall score is at least 4.0. Anything in between — no dimension at 2 or below, overall at least 3.0, but the `PASS` bar not met — is `PASS_WITH_DEFICIENCIES`. Note the boundaries exactly: an overall score of exactly 3.0 escapes the `FAIL` gate, while `PASS` strictly requires 4.0 or better overall.

A failed review of an engagement still in `REPORTING` triggers the deepest cascade in the system. The engagement regresses from `REPORTING` back to `FIELDWORK` and its `qa_regression_count` increments by one. The regression reopens the evidence base: every workpaper of the engagement that was `SIGNED_OFF` transitions to `RETURNED`, with its `review_note` set to the marker QA_REOPEN, its `signed_off_at` cleared, and its `reviewer_auditor_id` retained — workpapers in `DRAFT` or already `RETURNED` are untouched, as are any merely `SUBMITTED` — and the engagement's `signed_off_workpaper_count`, `actual_hours`, `provisional_hours`, and both utilization percentages are recomputed. Because issuance requires clean workpapers, the report pipeline unwinds too: any report of the engagement sitting in `PENDING_APPROVAL` automatically returns to `DRAFT`. And because the numbers a committee would see have now changed underneath a pack still being drafted, every committee pack of the engagement's plan that is still in `DRAFT` has its `is_stale_snapshot` flag set to true and its `updated_at` and `version` advanced, whether or not the flag was already set. A `FAIL` against an engagement that has already reached `CLOSED` changes nothing downstream — the regression cascade fires only while the engagement is in `REPORTING`.

The board-facing artifact is the **CommitteePack**, created by a `ChiefAuditExecutive` with the reported-on `audit_plan_id`, the `meeting_date`, and a `title`. Pack creation requires the plan to be in `APPROVED` or `CLOSED` status; reporting on a plan still under drafting or negotiation fails with `ERR_PLAN_NOT_APPROVED`. The pack is born `DRAFT`, with `is_stale_snapshot` false, the four snapshot aggregates (`snapshot_plan_completion_pct`, `snapshot_overdue_action_count`, `snapshot_critical_findings`, `snapshot_high_findings`) null until finalization, and `finalized_at` and `presented_at` null. An unknown pack reference yields `ERR_COMMITTEE_PACK_NOT_FOUND`; listings filter by `audit_plan_id` or `status`.

Finalizing the pack — requiring it to be in `DRAFT`, else `ERR_PACK_INVALID_STATE` — computes and permanently pins four snapshot aggregates, stamps `finalized_at`, and moves the pack to `FINALIZED`. The snapshot is never recomputed afterwards, whatever happens to the underlying data. The plan-scope inputs are defined as follows: the plan's engagements for the completion figure are those with status other than `CANCELLED`, while the plan's findings for the remaining figures are the findings of all engagements of the plan, including `CANCELLED` ones. First, `snapshot_plan_completion_pct` is one hundred times the number of the plan's non-cancelled engagements in `CLOSED` status divided by the total number of non-cancelled engagements, rounded half-up to two decimal places; when the plan has no non-cancelled engagements at all, the value is 0.0. Second, `snapshot_overdue_action_count` counts, across the action plans of the plan's findings, those not in `VALIDATED` status that are at least one full day overdue as measured against the logical clock at the moment of finalization. Third and fourth, `snapshot_critical_findings` and `snapshot_high_findings` count the plan's findings whose status is `AGREED`, `ESCALATED`, or `FINAL` and whose severity is `CRITICAL` or `HIGH` respectively.

Presentation is the committee's act: the `AuditCommittee` marks a `FINALIZED` pack as `PRESENTED` — any other from-state fails with `ERR_PACK_INVALID_STATE` — and the server stamps `presented_at` from the logical clock, ending the annual cycle.


## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, decisions, sign-offs, and the clock adjustment — return `200 OK`. The table below is a structural index only: request payloads, response bodies, and side effects are defined by the workflow narratives of §3 and the global rules of §2. The clock capability lives outside the `/audit` mount as its own path. "All roles" in the authorization column means every role enumerated in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/audit/auditable-entities` | Create an audit-universe entry | AuditAdmin |
| GET | `/audit/auditable-entities/{id}` | Get an auditable entity | All roles |
| POST | `/audit/auditable-entities/{id}/retire` | Retire (soft-archive) an entity; blocked while engagements open | AuditAdmin |
| POST | `/audit/risk-assessments` | Create a risk assessment (OCC on entity version); score computed per variant | AuditManager |
| GET | `/audit/risk-assessments` | List risk assessments | All roles |
| GET | `/audit/risk-assessments/{id}` | Get a risk assessment | All roles |
| POST | `/audit/risk-assessments/{id}/finalize` | Finalize a risk assessment; syncs entity risk fields | AuditManager |
| POST | `/audit/rating-criteria-configs` | Create a rating-band config | AuditAdmin |
| GET | `/audit/rating-criteria-configs/{id}` | Get a rating config | All roles |
| POST | `/audit/rating-criteria-configs/{id}/activate` | Activate config; supersedes the previously ACTIVE one | AuditAdmin |
| POST | `/audit/audit-plans` | Create an annual audit plan | ChiefAuditExecutive |
| GET | `/audit/audit-plans/{id}` | Get an audit plan | All roles |
| POST | `/audit/audit-plans/{id}/submit` | Submit plan for committee approval (DRAFT or RETURNED) | ChiefAuditExecutive |
| POST | `/audit/audit-plans/{id}/approve` | Committee approves plan (SoD: approver differs from submitter) | AuditCommittee |
| POST | `/audit/audit-plans/{id}/return` | Committee returns plan for rework (cycle) | AuditCommittee |
| POST | `/audit/audit-plans/{id}/close` | Close plan at year end (all engagements terminal) | ChiefAuditExecutive |
| POST | `/audit/engagements` | Create an engagement under a plan (OCC on plan version; cooling-period and window checks) | AuditManager |
| GET | `/audit/engagements` | List engagements | All roles |
| GET | `/audit/engagements/{id}` | Get an engagement | All roles |
| POST | `/audit/engagements/{id}/scope` | Mark engagement scoped | AuditManager |
| POST | `/audit/engagements/{id}/begin-fieldwork` | Open fieldwork (requires approved plan and LEAD assignment) | AuditManager |
| POST | `/audit/engagements/{id}/begin-reporting` | Open reporting (requires signed workpapers, none pending review) | AuditManager |
| POST | `/audit/engagements/{id}/close` | Close engagement (report issued, QA settled) | AuditManager |
| POST | `/audit/engagements/{id}/cancel` | Cancel a planned/scoped engagement; cascades to assignments | AuditManager |
| POST | `/audit/auditors` | Add an auditor to the roster | AuditAdmin |
| GET | `/audit/auditors/{id}` | Get an auditor | All roles |
| POST | `/audit/auditors/{id}/deactivate` | Deactivate an auditor | AuditAdmin |
| POST | `/audit/engagement-assignments` | Assign an auditor to an engagement (overlap and duplicate checks) | AuditManager |
| GET | `/audit/engagement-assignments` | List assignments | All roles |
| GET | `/audit/engagement-assignments/{id}` | Get an assignment | All roles |
| POST | `/audit/engagement-assignments/{id}/cancel` | Cancel an assignment; releases reserved hours | AuditManager |
| POST | `/audit/workpapers` | Create a workpaper during fieldwork (preparer is the caller) | FieldAuditor |
| GET | `/audit/workpapers` | List workpapers | All roles |
| GET | `/audit/workpapers/{id}` | Get a workpaper | All roles |
| POST | `/audit/workpapers/{id}/submit` | Preparer submits workpaper for review | FieldAuditor |
| POST | `/audit/workpapers/{id}/sign-off` | Reviewer signs off (SoD: reviewer differs from preparer; fiscal budget gate) | AuditManager |
| POST | `/audit/workpapers/{id}/return` | Reviewer returns workpaper (from SUBMITTED or SIGNED_OFF) | AuditManager |
| POST | `/audit/workpapers/{id}/revise` | Preparer reopens a returned workpaper | FieldAuditor |
| POST | `/audit/findings` | Raise a finding (severity pinned via ACTIVE config) | FieldAuditor |
| GET | `/audit/findings` | List findings | All roles |
| GET | `/audit/findings/{id}` | Get a finding | All roles |
| POST | `/audit/findings/{id}/issue` | Issue finding to management (SoD: issuer differs from creator) | AuditManager |
| POST | `/audit/findings/{id}/escalate` | Escalate a deadlocked finding (negotiation rounds exhausted) | ChiefAuditExecutive |
| POST | `/audit/management-responses` | Management responds to a finding (moves finding to UNDER_REVIEW) | ManagementOwner |
| GET | `/audit/management-responses` | List management responses | All roles |
| GET | `/audit/management-responses/{id}` | Get a management response | All roles |
| POST | `/audit/management-responses/{id}/accept` | Audit accepts the response (finding AGREED) | AuditManager |
| POST | `/audit/management-responses/{id}/rebut` | Audit rebuts the response (negotiation round increments) | AuditManager |
| POST | `/audit/action-plans` | Create a remediation action plan for a finding under review or agreed | ManagementOwner |
| GET | `/audit/action-plans` | List action plans | All roles |
| GET | `/audit/action-plans/{id}` | Get an action plan | All roles |
| POST | `/audit/action-plans/{id}/start` | Start remediation (requires finding AGREED) | ManagementOwner |
| POST | `/audit/action-plans/{id}/submit-validation` | Submit completed plan for audit validation | ManagementOwner |
| POST | `/audit/action-plans/{id}/validate` | Audit validates closure evidence | AuditManager |
| POST | `/audit/action-plans/{id}/reject-validation` | Audit rejects closure evidence (rework loop) | AuditManager |
| POST | `/audit/extension-requests` | Request a due-date extension (caps: 2 approvals, 180 cumulative days) | ManagementOwner |
| GET | `/audit/extension-requests` | List extension requests | All roles |
| GET | `/audit/extension-requests/{id}` | Get an extension request | All roles |
| POST | `/audit/extension-requests/{id}/approve` | Approve extension (cascades to action plan due date and finding overdue count) | ChiefAuditExecutive |
| POST | `/audit/extension-requests/{id}/deny` | Deny extension | ChiefAuditExecutive |
| POST | `/audit/audit-reports` | Draft an audit report for an engagement in REPORTING | AuditManager |
| GET | `/audit/audit-reports` | List audit reports | All roles |
| GET | `/audit/audit-reports/{id}` | Get an audit report | All roles |
| POST | `/audit/audit-reports/{id}/submit` | Submit draft report for CAE approval | AuditManager |
| POST | `/audit/audit-reports/{id}/approve` | CAE approves report | ChiefAuditExecutive |
| POST | `/audit/audit-reports/{id}/return` | CAE returns report to draft (revision loop) | ChiefAuditExecutive |
| POST | `/audit/audit-reports/{id}/issue` | Issue report (findings to FINAL, workpapers locked) | ChiefAuditExecutive |
| POST | `/audit/audit-reports/{id}/distribute` | Distribute issued report | ChiefAuditExecutive |
| POST | `/audit/qa-reviews` | Schedule a QA/external assessment for an engagement in REPORTING or CLOSED | ChiefAuditExecutive |
| GET | `/audit/qa-reviews` | List QA reviews | All roles |
| GET | `/audit/qa-reviews/{id}` | Get a QA review | All roles |
| POST | `/audit/qa-reviews/{id}/begin` | Assessor begins review (independence: no assignment on engagement) | QualityAssessor |
| POST | `/audit/qa-reviews/{id}/complete` | Assessor completes review with dimension scores; FAIL regresses engagement | QualityAssessor |
| POST | `/audit/committee-packs` | Create a committee reporting pack for an approved/closed plan | ChiefAuditExecutive |
| GET | `/audit/committee-packs` | List committee packs | All roles |
| GET | `/audit/committee-packs/{id}` | Get a committee pack | All roles |
| POST | `/audit/committee-packs/{id}/finalize` | Finalize pack; pins snapshot aggregates (version pinning) | ChiefAuditExecutive |
| POST | `/audit/committee-packs/{id}/present` | Committee marks pack presented | AuditCommittee |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | AuditAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined in the narrative of §2 and §3, not here. Requests matching no defined endpoint path or method are rejected with `ERR_NOT_FOUND` (HTTP 404), a framework-level fallback outside this catalogue.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_ROLE_GRADE_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SCORE_OUT_OF_RANGE` | 422 |
| `ERR_STALE_ENTITY_VERSION` | 412 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_AUDITABLE_ENTITY_NOT_FOUND` | 404 |
| `ERR_RISK_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_RATING_CONFIG_NOT_FOUND` | 404 |
| `ERR_AUDIT_PLAN_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_AUDITOR_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_WORKPAPER_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_MANAGEMENT_RESPONSE_NOT_FOUND` | 404 |
| `ERR_ACTION_PLAN_NOT_FOUND` | 404 |
| `ERR_EXTENSION_REQUEST_NOT_FOUND` | 404 |
| `ERR_AUDIT_REPORT_NOT_FOUND` | 404 |
| `ERR_QA_REVIEW_NOT_FOUND` | 404 |
| `ERR_COMMITTEE_PACK_NOT_FOUND` | 404 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_ENGAGEMENT_INVALID_STATE` | 409 |
| `ERR_RISK_ASSESSMENT_INVALID_STATE` | 409 |
| `ERR_RATING_CONFIG_INVALID_STATE` | 409 |
| `ERR_AUDITABLE_ENTITY_INVALID_STATE` | 409 |
| `ERR_AUDITOR_INACTIVE` | 409 |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 |
| `ERR_WORKPAPER_INVALID_STATE` | 409 |
| `ERR_WORKPAPER_LOCKED` | 409 |
| `ERR_FINDING_INVALID_STATE` | 409 |
| `ERR_FINDING_NOT_AWAITING_RESPONSE` | 409 |
| `ERR_RESPONSE_INVALID_STATE` | 409 |
| `ERR_ACTION_PLAN_INVALID_STATE` | 409 |
| `ERR_EXTENSION_INVALID_STATE` | 409 |
| `ERR_REPORT_INVALID_STATE` | 409 |
| `ERR_QA_REVIEW_INVALID_STATE` | 409 |
| `ERR_PACK_INVALID_STATE` | 409 |
| `ERR_PLAN_SELF_APPROVAL` | 403 |
| `ERR_WORKPAPER_SELF_REVIEW` | 403 |
| `ERR_NOT_WORKPAPER_PREPARER` | 403 |
| `ERR_FINDING_SELF_ISSUE` | 403 |
| `ERR_QA_ASSESSOR_ASSIGNED` | 403 |
| `ERR_NOT_QA_ASSESSOR` | 403 |
| `ERR_PLAN_EMPTY` | 422 |
| `ERR_PLAN_HAS_OPEN_ENGAGEMENTS` | 409 |
| `ERR_RISK_ASSESSMENT_DRAFT_EXISTS` | 409 |
| `ERR_RISK_ASSESSMENT_ALREADY_FINALIZED` | 409 |
| `ERR_CONFIG_BANDS_INVALID` | 422 |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 |
| `ERR_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_ENGAGEMENT_COOLING_PERIOD` | 409 |
| `ERR_QA_REVIEW_ALREADY_OPEN` | 409 |
| `ERR_EXTENSION_ALREADY_PENDING` | 409 |
| `ERR_EXTENSION_COUNT_EXCEEDED` | 422 |
| `ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED` | 422 |
| `ERR_ENTITY_HAS_OPEN_ENGAGEMENTS` | 409 |
| `ERR_REPORT_ALREADY_ISSUED` | 409 |
| `ERR_ENGAGEMENT_WINDOW_INVALID` | 422 |
| `ERR_ASSIGNMENT_WINDOW_INVALID` | 422 |
| `ERR_EXTENSION_NOT_MONOTONIC` | 422 |
| `ERR_DUE_DATE_NOT_FUTURE` | 422 |
| `ERR_AUDITABLE_ENTITY_RETIRED` | 409 |
| `ERR_NO_ACTIVE_RATING_CONFIG` | 422 |
| `ERR_WORKPAPER_NOT_SIGNED` | 422 |
| `ERR_PREPARER_NOT_ASSIGNED` | 422 |
| `ERR_NO_LEAD_ASSIGNED` | 422 |
| `ERR_PLAN_NOT_APPROVED` | 409 |
| `ERR_NO_SIGNED_WORKPAPERS` | 422 |
| `ERR_WORKPAPERS_PENDING_REVIEW` | 422 |
| `ERR_REPORT_NOT_ISSUED` | 422 |
| `ERR_QA_REVIEW_OPEN` | 422 |
| `ERR_FINDINGS_NOT_RESOLVED` | 422 |
| `ERR_FINDING_NOT_AGREED` | 422 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 422 |
| `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED` | 422 |
| `ERR_DISTRIBUTION_LIST_EMPTY` | 422 |
| `ERR_BUDGET_HOURS_EXCEEDED` | 422 |
