# Contractor Classification Compliance API — Product Requirements Document

## 1. Introduction

Engaging independent contractors exposes a company to one of the most heavily enforced areas of employment law. Federal and state agencies apply different classification tests — some all-or-nothing, some weighted, some factorial — and the penalties for misclassification compound quarter over quarter, with the burden of proof sitting squarely on the engaging company. This document specifies the Contractor Classification Compliance API, the system of record for a worker classification review board. The platform administers the full compliance lifecycle: engagement intake questionnaires, jurisdiction-specific classification determinations, tiered approval quorums backed by documented exception grants, contract and amendment governance, ongoing monitoring for scope creep, reclassification risk audits with remediation tracking, year-end 1099 reporting and corrections, agency inquiry response and escalation, and the conversion of contractors to employment.

Two design commitments shape every workflow that follows. First, segregation of duties is structural rather than advisory: the manager who opens an engagement never runs its classification test, and the quorum steps of a tiered approval must be performed by distinct principals in a fixed role order. Second, all temporal evaluation — filing deadlines, exception expiries, contract lapse, lateness arithmetic — is driven by a server-side logical clock rather than wall-clock time, so that every date-sensitive rule in this document is deterministic. All business resources are served under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request missing either header, or whose role header does not name a declared role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system declares nine roles: `PlatformAdmin` (jurisdiction configuration and the test-driving clock), `EngagementManager` (business-side owner of engagements, questionnaires, contracts, amendments, activation, and conversion decisions), `ClassificationAnalyst` (classification determinations and the review loop), `HRApprover` (first quorum step on every approval tier; extends conversion offers), `LegalApprover` (second quorum step; adjudicates contract amendments), `ComplianceBoardMember` (third quorum step; grants and revokes classification exceptions), `ComplianceOfficer` (verification decisions, suspensions, monitoring reviews, risk audits, remediation, and conversion case creation), `TaxReportingSpecialist` (the 1099 filing lifecycle), and `AgencyLiaison` (agency inquiry intake, response, and escalation). An authenticated principal attempting an operation outside their role's grant is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For each of these roles — `PlatformAdmin`, `EngagementManager`, `ClassificationAnalyst`, `HRApprover`, `LegalApprover`, `ComplianceBoardMember`, `ComplianceOfficer`, `TaxReportingSpecialist`, and `AgencyLiaison` — the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record it (for example as `granted_by_user_id` on an exception grant, or as the `user_id` inside an engagement's recorded approval entries) but never compares it to any resource's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified for a particular endpoint, list responses are sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every primary resource carries a standard set of system-managed properties:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- **`version` (integer):** a system-managed integer that increments by one on every modification of the resource, including modifications applied by system-driven cascades rather than direct client action.

The ClassificationDetermination is the sole exception to this convention: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from a determination, because determinations are append-only records — a newer determination marks its predecessor through the `superseded` flag rather than by mutating versioned state.

### 2.5. The Logical Clock and Lazy Expiry

All temporal evaluation in the system — filing deadlines, exception expiry, contract lapse, lateness day counts, and the month arithmetic inside risk scoring — is governed by a server-side **logical clock**, never by wall-clock time. At server startup, before any explicit set, the clock reads exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` advances the clock through a test-driving capability that accepts a `to_iso8601` instant and sets the clock to it.

Two resource types expire lazily against this clock. An ExceptionGrant whose `expires_at` lies in the past — the clock instant is strictly later than `expires_at` — is treated as `EXPIRED`; this evaluation happens whenever the grant is read or used as a precondition. A ContractAgreement in `EXECUTED` status whose exclusive `end_date` has passed — the clock's calendar date is strictly later than `end_date` — transitions to `EXPIRED`, evaluated lazily on any read or write of the contract. No background batch job performs these transitions; they materialize at access time. The logical clock also stamps `submitted_at` on questionnaires, `filed_at` on filings, and the `decided_at` instant recorded with each quorum approval.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; endpoints not named here do not accept a version field.

- `POST /api/engagements/{id}/determinations` requires a non-optional `expected_engagement_version` input carrying the client's last observed `version` of the target engagement. If the engagement's current `version` differs — because the questionnaire was resubmitted, a determination was recorded, or any other engagement mutation intervened since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a new determination legitimately supersedes the current one, a writer holding a stale engagement view must re-read before computing.
- `POST /api/contracts/{id}/amendments` requires a non-optional `expected_contract_version` input carrying the client's last observed `version` of the parent contract. If the contract's current `version` differs — for example because another amendment was just proposed or applied, changing the contract's terms — the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), and the amendment must be re-based on the current contract terms.

In both cases the client recovers by re-reading the parent resource and re-issuing the write against the current `version`.

### 2.7. Nested Resources and Existence Ordering

Requests that address nested resources validate path identifiers sequentially, left to right, and reject at the first identifier that does not resolve. A contractor identifier that does not exist yields `ERR_CONTRACTOR_NOT_FOUND` (HTTP 404); an engagement identifier that does not exist yields `ERR_ENGAGEMENT_NOT_FOUND` (HTTP 404); any other resource identifier — whether an `{id}` path segment naming a jurisdiction, contract, amendment, review, audit, remediation action, filing, inquiry, conversion, or exception, or a resource referenced inside a request body — yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Left-to-right ordering means a request aimed at a questionnaire beneath a non-existent engagement fails on the engagement before the child is ever considered.

### 2.8. Money, Scores, and Rounding Conventions

All monetary amounts in the system — rates, insurance coverage, reportable amounts, penalties, exposure estimates, salaries — are represented as integer cents; no monetary field carries a fractional part. Where a calculation produces a fractional intermediate, rounding is always **round half up**. Four precision regimes apply, each stated again beside its owning calculation in §3: the weighted classification score is recorded to two decimal places; risk audit scores, provisional and final, are recorded to one decimal place; the scope creep index is a whole number rounded from a finer intermediate; and the per-quarter conversion amounts and agency exposure components are rounded half up to whole cents at the pinned steps of their respective formulas.

### 2.9. Validation Priority Order

Every request passes through a fixed ladder of validation rungs, evaluated in the order below; a request that fails an earlier rung is rejected immediately and never surfaces a later rung's error.

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role names a declared role (`ERR_UNAUTHENTICATED`, HTTP 401).
2. **Role authorization** — the acting role is permitted on the endpoint (`ERR_UNAUTHORIZED_ROLE`, HTTP 403).
3. **Request shape** — required fields are present, enum values fall within their declared sets, and dates are parseable (`ERR_INVALID_REQUEST`, HTTP 400). Shape rules with conditional force live at this rung: a conversion's `lookback_quarters` must contain exactly four entries; a remediation close whose `outcome` is `WAIVED` must carry a non-empty `close_note`; an inquiry resolution whose `outcome` is `ESCALATE_TO_AUDIT` must carry a `new_response_deadline` in the future; and a filing's `corrects_filing_id` must be present exactly when `kind` is `CORRECTION` and null when `kind` is `ORIGINAL`.
4. **Existence** — path and body references resolve, left to right (the three 404 identifiers of §2.7).
5. **State validity** — the requested transition is defined from the resource's current status. This rung covers the generic `ERR_INVALID_STATE` (HTTP 409) rejection — including terminal lockdown of `REJECTED`, `TERMINATED`, or `CONVERTED` engagements, `VOID` or `SUPERSEDED` filings, `CLOSED` audits and reviews, terminal amendments, `RESOLVED` inquiries, and terminal conversions — alongside the endpoint-specific state rejections (`ERR_DETERMINATION_REQUIRED`, `ERR_ENGAGEMENT_NOT_APPROVAL_PENDING`, `ERR_CONTRACT_NOT_EXECUTED`, `ERR_FILING_NOT_SUBMITTABLE`, `ERR_CORRECTION_REQUIRES_ACCEPTED`, `ERR_AUDIT_NOT_OPEN`, `ERR_AUDIT_ACTIONS_OPEN`, `ERR_CONVERSION_NOT_POSSIBLE`) and the two optimistic-concurrency rejections of §2.6 (`ERR_STALE_VERSION` and `ERR_STALE_CONTRACT_VERSION`, HTTP 412). Entries within a rung share priority.
6. **Business safety gates** — contractor standing, contractor verification, the insurance floor, and the high-tier exception requirement (`ERR_CONTRACTOR_STANDING_SUSPENDED`, `ERR_CONTRACTOR_NOT_VERIFIED`, `ERR_INSURANCE_BELOW_MINIMUM`, `ERR_EXCEPTION_REQUIRED`).
7. **Business constraints** — approval chain order (`ERR_APPROVAL_OUT_OF_ORDER`), segregation of duties (`ERR_APPROVER_ALREADY_ACTED`), questionnaire completeness (`ERR_QUESTIONNAIRE_INCOMPLETE`), filing uniqueness (`ERR_DUPLICATE_FILING`), contract period overlap (`ERR_CONTRACT_PERIOD_OVERLAP`), and review spacing (`ERR_REVIEW_INTERVAL_TOO_SHORT`).
8. **Temporal freshness** — determination staleness at approval submission (`ERR_DETERMINATION_STALE`) and the inquiry response deadline (`ERR_INQUIRY_DEADLINE_PASSED`).
9. **Referential soundness** — exception expiry (`ERR_EXCEPTION_EXPIRED`) and review close linkage (`ERR_REVIEW_NOT_CLOSABLE`).
10. **Fiscal capacity** — the jurisdiction's exception capacity cap (`ERR_EXCEPTION_CAPACITY_REACHED`).

The ordering has observable consequences. A determination request carrying a stale engagement version is rejected with `ERR_STALE_VERSION` even when the questionnaire is also incomplete, because state validity (rung 5) precedes business constraints (rung 7). An approval attempted on an engagement that is not in `APPROVAL_PENDING` is rejected with `ERR_ENGAGEMENT_NOT_APPROVAL_PENDING` before the approval-order, segregation-of-duties, or exception checks are ever evaluated.

### 2.10. Cascading Consistency and Terminal Lockdown

Certain transitions propagate across aggregate boundaries so that dependent records never drift out of alignment with their parents. Three cascade families exist: the suspension cascade (engagement suspension travels through the contract, its amendments, and any linked exception grants, and finally touches contractor standing), the conversion-acceptance cascade (an accepted conversion converts the engagement, converts the contractor's standing, and rejects the contractor's other non-terminal engagements), and correction supersession (submitting a correction filing supersedes its accepted predecessor). In addition, two compound transitions complete within the request that triggers them: an approved amendment is applied immediately, and a finalized audit whose risk level is `HIGH` or `CRITICAL` continues automatically into remediation. One cross-entity creation exists: escalating an agency inquiry opens a fieldwork risk audit. Every mutation caused by a cascade refreshes the mutated resource's `updated_at` and increments its `version` by one. Compensation is deliberately asymmetric — reinstating a suspended engagement restores its contract but does not restore amendments voided or exceptions revoked by the suspension.

## 3. Business Logic & Workflows

### 3.1. Jurisdiction Regimes and the Three Classification Tests

A `PlatformAdmin` configures each classification regime as a **Jurisdiction** resource carrying a unique `code` (values such as US-FED, US-CA, US-MA, or US-TX), a `test_type` naming the classification test the jurisdiction applies — exactly one of `ABC_TEST`, `COMMON_LAW_WEIGHTED`, or `ECONOMIC_REALITY` — and an optional free-text `description` that defaults to empty. Three regime parameters gate later workflows: `state_filing_threshold_cents`, the reportable amount at or above which a state copy of a 1099 is required; `max_active_exceptions`, the capacity cap on simultaneously active exception grants across all engagements governed by the jurisdiction; and `min_insurance_cents`, the minimum contractor liability coverage required to execute a contract there. Each of these three must be zero or greater. A fourth parameter, `employee_score_threshold`, matters only under `COMMON_LAW_WEIGHTED`: it is the weighted-score boundary at or above which an engagement is classified as an employee risk. The boundary must be strictly greater than zero and at most one, and it defaults to 0.60 when not supplied. Jurisdictions may be listed with an optional `test_type` filter.

Because the three tests can disagree on identical answers, the choice of regime is outcome-determinative. Variant selection is driven **only** by the `test_type` of the engagement's jurisdiction; no other attribute of the engagement, the contractor, or the questionnaire influences which variant runs.

Under `COMMON_LAW_WEIGHTED`, six of the eight questionnaire factors are employee-indicative in a specific direction: `CONTROL_METHOD` answered `YES`, `CONTROL_HOURS` answered `YES`, `INTEGRAL_TO_BUSINESS` answered `YES`, `PROFIT_LOSS` answered `NO`, `PERMANENCY` answered `YES`, and `INVESTMENT` answered `NO`. The weighted score sums 0.25 for control of method, 0.20 for control of hours, 0.20 for integral-to-business work, 0.15 for profit-and-loss posture, 0.10 for permanency, and 0.10 for investment — each term contributing its weight only when the corresponding answer is employee-indicative, and contributing zero otherwise. The outcome is `EMPLOYEE_RISK` when the score is greater than or equal to the jurisdiction's `employee_score_threshold` — the boundary is inclusive — and `CONTRACTOR` otherwise. The determination records the score in its `score` field, rounded half up to two decimal places, and records `failed_prongs` as 0. This variant tolerates isolated employee-indicative answers; a combination of answers that fails the ABC test can still pass here.

Under `ABC_TEST`, the evaluation is all-or-nothing across three prongs. Prong A fails when `CONTROL_METHOD` is answered `YES` or `CONTROL_HOURS` is answered `YES`. Prong B fails when `OUTSIDE_USUAL_BUSINESS` is answered `NO`. Prong C fails when `INDEPENDENT_TRADE` is answered `NO`. The outcome is `CONTRACTOR` only when no prong fails; a single failed prong flips the outcome to `EMPLOYEE_RISK` regardless of how favorable the remaining answers are. The determination's `score` and `failed_prongs` both record the failed-prong count, an integer from zero to three.

Under `ECONOMIC_REALITY`, six employee-indicative answers are counted with equal weight: `CONTROL_METHOD` answered `YES`, `INTEGRAL_TO_BUSINESS` answered `YES`, `PROFIT_LOSS` answered `NO`, `INVESTMENT` answered `NO`, `PERMANENCY` answered `YES`, and `OUTSIDE_USUAL_BUSINESS` answered `NO`. The outcome is `EMPLOYEE_RISK` when the count reaches at least two — the threshold is inclusive — and `CONTRACTOR` otherwise. The determination's `score` records the count, and `failed_prongs` is 0. Because this variant weights nothing and thresholds at two, identical answers can diverge from both other variants.

### 3.2. Contractor Onboarding, Verification, and Standing

An `EngagementManager` registers each worker or business entity as a **Contractor** by supplying the `legal_name`, an `entity_type` of `INDIVIDUAL`, `SOLE_PROPRIETOR`, `LLC`, `S_CORP`, or `PARTNERSHIP`, an `ein` (the Employer Identification Number, or the SSN for an `INDIVIDUAL`) that must be unique across all contractors, and the current `insurance_coverage_cents`, which may be zero but never negative. A new contractor begins with `verification_status` of `UNVERIFIED`, `standing_status` of `GOOD_STANDING`, and `lifetime_reported_cents` of 0. Contractors may be listed with optional `standing_status` and `verification_status` filters.

A contractor carries **two parallel status dimensions that evolve independently**. The verification dimension is driven by a `ComplianceOfficer` recording a verification decision whose `outcome` is `VERIFIED` or `FAILED`, optionally annotated with `notes`. From `UNVERIFIED`, a `VERIFIED` outcome moves the contractor to `VERIFIED` and a `FAILED` outcome moves it to `VERIFICATION_FAILED`; a contractor in `VERIFICATION_FAILED` can be re-verified to `VERIFIED` by a later `VERIFIED` decision. Each recorded decision increments the contractor's `version`.

The standing dimension is system-driven and reflects ongoing compliance posture. From `GOOD_STANDING`, standing moves to `WATCH` when a risk audit finalizes at a `HIGH` risk level or when an exception grant revocation is recorded against the contractor. From `WATCH`, standing returns to `GOOD_STANDING` when remediation work clears — specifically when a remediation action closes, bringing its audit's open action count to zero, while no other audit of the same contractor still has open actions. From either `GOOD_STANDING` or `WATCH`, a risk audit finalized at `CRITICAL` drops the contractor to `SUSPENDED_STANDING`. From any non-terminal standing, completion of a conversion case moves the contractor to `CONVERTED_TO_EMPLOYEE`, which is terminal for the standing dimension.

Standing and verification gate other workflows as safety checks. Opening a new engagement for a contractor, activating an approved engagement, and reinstating a suspended engagement each require the contractor's `standing_status` to be `GOOD_STANDING` or `WATCH`; a contractor in `SUSPENDED_STANDING` or `CONVERTED_TO_EMPLOYEE` causes these operations to be rejected with `ERR_CONTRACTOR_STANDING_SUSPENDED` (HTTP 422). Executing a contract and submitting a 1099 filing each require `verification_status` of `VERIFIED`; otherwise the operation is rejected with `ERR_CONTRACTOR_NOT_VERIFIED` (HTTP 422). The `lifetime_reported_cents` total, summarized in §3.8, reconciles continuously as filings move through their lifecycle.

### 3.3. Engagement Intake and the Questionnaire Loop

Work begins when an `EngagementManager` opens an **Engagement**, naming the engaged worker via `contractor_id` and the governing regime via `jurisdiction_id`, and supplying a `title`, a `scope_description` summarizing the statement of work, an `agreed_rate_cents` strictly greater than zero, a `rate_unit` of `HOURLY`, `DAILY`, or `PROJECT`, a `start_date`, an `end_date` no earlier than the start date, and an optional `supervision_level` of `NONE`, `LIGHT`, or `CLOSE` that defaults to `NONE`. Creation is gated by the contractor standing rule of §3.2. A new engagement begins in `DRAFT` with a `scope_creep_index` of 0 and a `scope_creep_tier` of `LOW`; its `risk_tier` stays null until a classification determination exists. Engagements may be listed filtered by `contractor_id`, `jurisdiction_id`, or `status`.

Against an engagement, the `EngagementManager` submits the intake questionnaire — a single upsert operation whose `answers` payload pairs a `factor_key` with an `answer` of `YES` or `NO` for each factor. The eight factor keys are `CONTROL_METHOD`, `CONTROL_HOURS`, `OUTSIDE_USUAL_BUSINESS`, `INDEPENDENT_TRADE`, `PROFIT_LOSS`, `INVESTMENT`, `INTEGRAL_TO_BUSINESS`, and `PERMANENCY`. The questionnaire's `complete` flag is true exactly when the submitted answers cover all eight factor keys exactly once each; fewer than eight factors, or duplicated factor keys, leave it incomplete. The `revision` counter starts at 1 on the first submission and increments by one on every subsequent submission for the same engagement, and `submitted_at` records the logical-clock instant of the latest submission. The owning `engagement_id` is taken from the path. Reading the questionnaire of an engagement returns an array of length zero or one.

Each questionnaire submission also drives the engagement's review loop. The first submission moves the engagement `DRAFT → INTAKE_SUBMITTED`; the transition occurs even when the answers are incomplete, though an incomplete questionnaire will block the later review-submission step. Re-submitting while in `INTAKE_SUBMITTED` keeps the engagement in `INTAKE_SUBMITTED`, increments `revision`, and renders any existing determination stale because its recorded questionnaire revision no longer matches. Submitting while in `CLASSIFIED` likewise increments `revision` and marks the current determination stale until the test is re-run. When a review has been suspended for more information — the engagement sitting in `INFO_REQUESTED` — a questionnaire resubmission answers the request and returns the engagement to `UNDER_REVIEW`. Questionnaire submission from any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Every accepted submission increments the engagement's `version` by one.

### 3.4. Determinations, Risk Tiers, and the Review Pipeline

A `ClassificationAnalyst` runs the classification test against an engagement in `INTAKE_SUBMITTED` or `CLASSIFIED`. This is one of the two optimistic-concurrency-guarded writes of §2.6: the request must carry `expected_engagement_version` matching the engagement's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The questionnaire must also be complete; running the test against an incomplete questionnaire is rejected with `ERR_QUESTIONNAIRE_INCOMPLETE` (HTTP 422). A successful run appends a new **ClassificationDetermination** that snapshots the regime as `jurisdiction_test_type`, records the `questionnaire_revision` it was computed from, and carries the computed `outcome` (`CONTRACTOR` or `EMPLOYEE_RISK`), `score`, and `failed_prongs` per the applicable variant of §3.1. The prior current determination, if one exists, has its `superseded` flag set to true; the engagement's `current_determination_id` — a soft pointer to the non-superseded determination — is updated to the new record, and the engagement transitions to (or remains in) `CLASSIFIED` with its `version` incremented. An engagement's full determination history is retrievable as a list ordered newest first, an exception to the default ascending creation order of §2.3.

The determination fixes the engagement's compliance posture. `risk_tier` is `HIGH` when the current outcome is `EMPLOYEE_RISK`; `ELEVATED` when the outcome is `CONTRACTOR` under a jurisdiction applying `ABC_TEST` or `ECONOMIC_REALITY`; and `STANDARD` when the outcome is `CONTRACTOR` under `COMMON_LAW_WEIGHTED`. The tier in turn fixes `required_approval_count`: `STANDARD` requires one approval, `ELEVATED` requires two, and `HIGH` requires three.

With a determination in hand, an `EngagementManager` submits the engagement for review, moving it `CLASSIFIED → UNDER_REVIEW`. This step requires a current determination to exist — otherwise `ERR_DETERMINATION_REQUIRED` (HTTP 409) — and a complete questionnaire, with the same `ERR_QUESTIONNAIRE_INCOMPLETE` guarding gaps or duplicated factor keys. During review, a `ClassificationAnalyst` may suspend the engagement `UNDER_REVIEW → INFO_REQUESTED` with a `reason`; the loop closes when the questionnaire resubmission of §3.3 returns the engagement to `UNDER_REVIEW`.

When review concludes, the `ClassificationAnalyst` submits the engagement for approval, moving it `UNDER_REVIEW → APPROVAL_PENDING`. Freshness is enforced at this boundary: the current determination's `questionnaire_revision` must equal the questionnaire's current `revision`; a determination computed from an older revision is stale and the submission is rejected with `ERR_DETERMINATION_STALE` (HTTP 409). Entering `APPROVAL_PENDING` resets `approvals_recorded` to an empty list, discarding any entries recorded during a prior approval round, and increments the engagement's `version`.

### 3.5. The Approval Quorum and Exception Grants

Approval is a quorum, not a single decision. The approval sequence is fixed as `HRApprover` first, then `LegalApprover`, then `ComplianceBoardMember`, truncated to the engagement's `required_approval_count`: a `STANDARD` engagement needs only the `HRApprover` step, an `ELEVATED` engagement needs `HRApprover` then `LegalApprover`, and a `HIGH` engagement needs all three in that order. Each approval call is valid only while the engagement is in `APPROVAL_PENDING` — an approval attempted in any other status is rejected with `ERR_ENGAGEMENT_NOT_APPROVAL_PENDING` (HTTP 409) — and the acting principal's role must equal the role at the next unfilled position of the truncated sequence, otherwise the call is rejected with `ERR_APPROVAL_OUT_OF_ORDER` (HTTP 409). Segregation of duties is enforced across the round: a principal whose `X-User-ID` already appears among the recorded approvals cannot act again, and a repeat attempt is rejected with `ERR_APPROVER_ALREADY_ACTED` (HTTP 409). Each accepted approval appends an entry recording the acting `role`, the acting `user_id`, and the `decided_at` instant to `approvals_recorded`; when the entry count reaches `required_approval_count`, the engagement automatically transitions to `APPROVED`. Every approval call increments the engagement's `version`.

High-risk engagements carry an additional gate on the final quorum step. When the approval being recorded is the one that reaches quorum on a `HIGH` tier engagement, an ExceptionGrant with status `ACTIVE` whose `expires_at` has not passed must exist for the engagement. If no such grant exists, the approval is rejected with `ERR_EXCEPTION_REQUIRED` (HTTP 422); if a grant exists but has expired against the logical clock, the rejection is `ERR_EXCEPTION_EXPIRED` (HTTP 422).

An **ExceptionGrant** is the documented decision to proceed despite classification risk. A `ComplianceBoardMember` grants one against an engagement by supplying a `justification` and an `expires_at` instant; the grant records the granting principal as `granted_by_user_id` and begins in `ACTIVE` status. Capacity is capped per regime: the count of `ACTIVE` grants across all engagements of the jurisdiction must be strictly below the jurisdiction's `max_active_exceptions` before another grant is issued, and a grant attempted at capacity is rejected with `ERR_EXCEPTION_CAPACITY_REACHED` (HTTP 422). Grants expire lazily per §2.5, moving from `ACTIVE` to `EXPIRED` when the clock passes `expires_at`. A `ComplianceBoardMember` may also revoke a grant, moving it `ACTIVE → REVOKED`; revocation recomputes the standing of the contractor behind the grant's engagement, moving `GOOD_STANDING` to `WATCH` (a contractor already in `WATCH` or `SUSPENDED_STANDING` is unaffected by this recompute), and increments the grant's `version`. The exception grants of an engagement are retrievable as a list, and reading them re-evaluates lazy expiry.

Rejection is available at two points in the pipeline with different acting roles. From `UNDER_REVIEW`, a `ClassificationAnalyst`, `HRApprover`, `LegalApprover`, or `ComplianceBoardMember` may reject the engagement with a `reason`; from `APPROVAL_PENDING`, the three approver roles — `HRApprover`, `LegalApprover`, and `ComplianceBoardMember` — may reject with a `reason`. Both paths land in the terminal `REJECTED` status and increment the engagement's `version`.

Once `APPROVED`, an engagement becomes operational through activation by an `EngagementManager`. Activation requires a contract in `EXECUTED` status for the engagement — otherwise `ERR_CONTRACT_NOT_EXECUTED` (HTTP 409) — and applies the contractor standing gate of §3.2. A successful activation moves the engagement `APPROVED → ACTIVE` and increments its `version`.

### 3.6. Contracts, Amendments, and the Suspension Cascade

An `EngagementManager` drafts a **ContractAgreement** for an engagement that is `APPROVED` or `ACTIVE`; drafting against any other engagement status is rejected with `ERR_INVALID_STATE`. The draft carries a `start_date`, an `end_date` strictly later than the start date, a `rate_cents` strictly greater than zero, and a `rate_unit` of `HOURLY`, `DAILY`, or `PROJECT`; the contract's `contractor_id` and `jurisdiction_id` are denormalized from the engagement for overlap checking, and its `engagement_id` ties it to the engagement named in the path. Contract periods are half-open intervals — the start date is inclusive and the end date exclusive — and no two contracts for the same `contractor_id` and `jurisdiction_id` pair in `DRAFT`, `EXECUTED`, or `SUSPENDED` status may overlap: a new contract whose period begins before an existing contract's period ends while the existing period begins before the new period ends is rejected with `ERR_CONTRACT_PERIOD_OVERLAP` (HTTP 409). Adjacency is allowed — a new contract whose `start_date` equals an existing contract's `end_date` touches without overlapping. A new contract begins in `DRAFT`. Contracts of an engagement are retrievable as a list, individual contracts are directly readable, and the contract collection may be listed with `contractor_id`, `jurisdiction_id`, `engagement_id`, or `status` filters; reads re-evaluate lazy expiry per §2.5.

Execution moves the contract `DRAFT → EXECUTED` under three gates: the contractor must be `VERIFIED` (else `ERR_CONTRACTOR_NOT_VERIFIED`), the contractor's `insurance_coverage_cents` must be at least the jurisdiction's `min_insurance_cents` (else `ERR_INSURANCE_BELOW_MINIMUM`, HTTP 422), and when the engagement's `risk_tier` is `HIGH` an `ACTIVE`, unexpired ExceptionGrant must exist for the engagement — absent, the rejection is `ERR_EXCEPTION_REQUIRED`; expired, `ERR_EXCEPTION_EXPIRED`. Execution increments the contract's `version`.

Once executed, a contract evolves through **ContractAmendments**. An `EngagementManager` proposes an amendment against the contract named in the path — recorded on the amendment as its `contract_id` — with a required `scope_change_summary` describing the change, an optional `new_rate_cents` (strictly greater than zero when present; null leaves the rate unchanged), an optional `new_end_date` (null leaves the end date unchanged), and an optional `exception_grant_id` softly referencing the grant under which the amendment is made — a reference that must be supplied when the engagement's `risk_tier` is `HIGH`, and that is rejected with `ERR_EXCEPTION_EXPIRED` when the referenced grant has expired. Proposing an amendment is the second optimistic-concurrency-guarded write of §2.6: the request must carry `expected_contract_version` matching the contract's current `version`, with mismatches rejected as `ERR_STALE_CONTRACT_VERSION` (HTTP 412). A proposal begins in `PROPOSED` and increments the parent contract's `version`, so each proposal invalidates any other client's captured contract version. Amendments of a contract are retrievable as a list.

Adjudication belongs to the `LegalApprover`, who records a `decision` of `APPROVED` or `REJECTED`. A rejection moves the amendment `PROPOSED → REJECTED`. An approval requires the parent contract to be in `EXECUTED` status — otherwise `ERR_INVALID_STATE` — and completes as a compound transition within the same request: the amendment moves `PROPOSED → APPROVED → APPLIED`, the contract's `rate_cents` and `end_date` are replaced by `new_rate_cents` and `new_end_date` where supplied, the contract's `version` increments again, and the engagement's `scope_creep_index` is recomputed per §3.7. `APPLIED`, `REJECTED`, and `VOIDED` are the amendment's terminal states.

Suspension is the system's strongest cascade. A `ComplianceOfficer` suspending an `ACTIVE` engagement moves it `ACTIVE → SUSPENDED` and fires four linked effects. Link 1: the engagement's `EXECUTED` contract transitions to `SUSPENDED`. Link 2, caused by the contract mutation: every amendment of that contract in `PROPOSED` or `APPROVED` status transitions to `VOIDED`. Link 3, caused by each voiding: every ExceptionGrant referenced by a newly `VOIDED` amendment through its `exception_grant_id`, while still `ACTIVE`, transitions to `REVOKED`. Link 4, caused by the revocations: the contractor's standing is recomputed, and a contractor in `GOOD_STANDING` with a revoked grant moves to `WATCH`. The engagement's `version` increments, as does the `version` of every resource mutated along the cascade.

Reinstatement reverses only the first link. A `ComplianceOfficer` reinstating a `SUSPENDED` engagement — gated by the contractor standing rule of §3.2 — moves it `SUSPENDED → ACTIVE` and returns the contract from `SUSPENDED` to `EXECUTED`. Amendments voided and exception grants revoked during suspension are **not** restored; this asymmetric compensation is intentional. Termination, also by a `ComplianceOfficer`, moves an engagement from `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED` status, and the engagement's contract — whether `EXECUTED` or `SUSPENDED` — transitions to `TERMINATED` with it. Independently of these flows, a contract in `EXECUTED` lapses to `EXPIRED` when the logical clock passes its exclusive `end_date`, per the lazy evaluation of §2.5; `TERMINATED` and `EXPIRED` are the contract's terminal states.

### 3.7. Monitoring Reviews, Scope Creep, and Risk Audits

Ongoing oversight begins with the **MonitoringReview**. A `ComplianceOfficer` schedules a review against an `ACTIVE` engagement — scheduling against any other status is rejected with `ERR_INVALID_STATE` — by supplying a `scheduled_date`. Reviews of the same engagement must be spaced at least 30 days apart: the new `scheduled_date` must differ from every other review's `scheduled_date`, in either direction and regardless of the other review's status, by no less than 30 calendar days. Exactly 30 days is allowed; 29 days is rejected with `ERR_REVIEW_INTERVAL_TOO_SHORT` (HTTP 409). A scheduled review begins in `SCHEDULED`, and the reviews of an engagement are retrievable as a list.

Closing a review is where findings enter the record. The `ComplianceOfficer` closes a `SCHEDULED` review by supplying `findings` — a list of entries each pairing a `severity` of `LOW`, `MEDIUM`, or `HIGH` with a `description`, which may be an empty list — and `remediation_action_ids`. When findings are present, `remediation_action_ids` must be non-empty and every referenced remediation action must be in `OPEN` status and belong to a risk audit of the same contractor as the review's engagement; otherwise the close is rejected with `ERR_REVIEW_NOT_CLOSABLE` (HTTP 422). At close, `findings_count` records the number of findings supplied, and the review's `outcome` is set to `CLEARED` when that count is zero and `FINDINGS_FILED` when it is one or more. Closing increments the review's `version` and recomputes the engagement's `scope_creep_index`. `CLOSED` is terminal.

The `scope_creep_index` condenses an engagement's drift into a single integer from 0 to 100, recomputed whenever an amendment is applied, whenever a monitoring review is closed, and whenever the engagement itself is mutated in a way that changes its rate, dates, or `supervision_level`. The formula sums three components. First, the number of amendments in `APPLIED` status on the engagement's contract — proposed, rejected, and voided amendments never count — capped at five amendments and multiplied by twelve points each. Second, the relative rate variance: the absolute difference between the contract's current `rate_cents` and its original rate — the rate in force when the contract first reached `EXECUTED` — divided by that original rate, or zero when no contract exists; this fraction is capped at one-half and multiplied by two hundred points. Third, schedule overrun: the calendar days from the engagement's `end_date` to the clock's date, floored at zero before the end date and capped at ninety days, contributing one point per day. Supervision intensity then scales the subtotal: a `supervision_level` of `CLOSE` multiplies it by one and a half, and `LIGHT` multiplies it by one and two-tenths, while `NONE` leaves it unchanged. If the engagement is currently `SUSPENDED`, the result is raised to a floor of seventy whenever it would otherwise fall below seventy. The index is the final value rounded half up to a whole number, capped at one hundred. The `scope_creep_tier` derives from the index: below 25 is `LOW`, 25 through 49 is `MODERATE`, 50 through 74 is `HIGH`, and 75 or more is `CRITICAL`.

A **RiskAudit** formalizes reclassification exposure. A `ComplianceOfficer` opens an audit with a `contractor_id`, an optional `engagement_id` (null produces a portfolio-level audit of the contractor), and an `audit_type` of `SCREENING` or `FIELDWORK`. Creation computes a forward-looking `provisional_risk_score`, rounded half up to one decimal place, from declared data: one-half of the engagement's `scope_creep_index`, plus forty points when the engagement's current determination outcome is `EMPLOYEE_RISK`, plus ten points for each `ACTIVE` exception grant on the engagement, plus two points per full calendar month between the engagement's `start_date` and the clock's date, capped at twelve months. For a portfolio audit the same terms aggregate across the contractor's engagements in `ACTIVE` or `SUSPENDED` status: the scope-creep term uses the maximum index among those engagements (zero when none exist), the determination term contributes forty when any of them has a current outcome of `EMPLOYEE_RISK`, the exception term sums `ACTIVE` grants across all of them, and the month term measures from the earliest `start_date`. A new audit begins in `OPEN` with an `open_action_count` of 0 and a null `final_risk_score`. Audits may be listed with `contractor_id`, `engagement_id`, or `status` filters.

Finalizing an audit replays observed reality against the estimate. The `ComplianceOfficer` supplies `fieldwork_events` and a `findings_summary`; events are replayed in the order supplied, each event type contributing points per occurrence for at most its first three occurrences: `SUPERVISION_OBSERVED` fifteen points, `EQUIPMENT_PROVIDED` ten points, `INTEGRATED_WORKFLOW` fifteen points, and `PAYMENT_REGULARITY` five points. The `final_risk_score` is three-tenths of the provisional score plus the sum of the capped event points, rounded half up to one decimal place. The audit's `risk_level` is computed over the final score once present and over the provisional score before that: below 25 is `LOW`; 25 up to but not including 50 is `MODERATE`; 50 up to but not including 75 is `HIGH`; 75 or more is `CRITICAL`. Finalization moves the audit `OPEN → FINDINGS_FINALIZED` and ripples into contractor standing: a `HIGH` level moves a `GOOD_STANDING` contractor to `WATCH`, and a `CRITICAL` level moves a `GOOD_STANDING` or `WATCH` contractor to `SUSPENDED_STANDING`. When the finalized level is `HIGH` or `CRITICAL`, the audit continues automatically from `FINDINGS_FINALIZED` into `REMEDIATION` within the same request; the audit's `version` increments once.

Remediation work is tracked as **RemediationActions** beneath an audit. A `ComplianceOfficer` creates an action with a `description`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a `due_date`, but only while the owning audit is in `FINDINGS_FINALIZED` or `REMEDIATION`; creation against an audit in any other status is rejected with `ERR_AUDIT_NOT_OPEN` (HTTP 409). Each action begins `OPEN`, its `audit_id` bound from the path, and each creation increments the parent audit's `open_action_count` by one. The actions of an audit are retrievable as a list. Closing an action takes an `outcome` of `CLOSED` or `WAIVED`; a waiver requires a non-empty `close_note` (otherwise `ERR_INVALID_REQUEST`), while a plain close accepts an optional `close_note`. Either outcome decrements the parent audit's `open_action_count` by one and increments the action's `version`, and either can restore standing: when the parent audit's open count reaches zero, the contractor's `standing_status` is `WATCH`, and no other audit of that contractor has any open actions, the contractor returns to `GOOD_STANDING`.

An audit closes under rules that depend on how far it progressed. From `OPEN`, only a `SCREENING` audit may close — attempting to close a `FIELDWORK` audit from `OPEN` is rejected with `ERR_INVALID_STATE` — and only with an `open_action_count` of zero. From `FINDINGS_FINALIZED`, closure requires a `risk_level` of `LOW` or `MODERATE` (a finalized `HIGH` or `CRITICAL` audit lives in `REMEDIATION` and cannot close from this state) and zero open actions. From `REMEDIATION`, closure requires zero open actions. Any close attempted with open actions outstanding is rejected with `ERR_AUDIT_ACTIONS_OPEN` (HTTP 409). `CLOSED` is the audit's terminal status.

### 3.8. 1099 Filings and Lifetime Reconciliation

Year-end reporting centers on the **TaxForm1099Filing**. A `TaxReportingSpecialist` creates a filing with a `contractor_id` naming the recipient, a `state_jurisdiction_id` naming the state regime whose threshold governs the state copy, a `tax_year` no earlier than 2020 and no later than the logical clock's current year, and a list of `payment_line_items`, each entry carrying an `amount_cents`, an ISO `payment_date`, and a `kind` of `SERVICE_FEE` or `EXPENSE_REIMBURSEMENT`. The filing's `kind` is `ORIGINAL` by default; a `kind` of `CORRECTION` must name the filing it corrects via `corrects_filing_id`, while an `ORIGINAL` filing must carry a null `corrects_filing_id` — a mismatch between the two is a shape error, `ERR_INVALID_REQUEST` (HTTP 400). Uniqueness is enforced per recipient and year: at most one `ORIGINAL` filing that is neither `VOID` nor `SUPERSEDED` may exist for a given `contractor_id` and `tax_year`, and a conflicting creation is rejected with `ERR_DUPLICATE_FILING` (HTTP 409). Filings may be listed with `contractor_id`, `state_jurisdiction_id`, `corrects_filing_id`, `tax_year`, or `status` filters.

The reporting math is computed once, at creation, and then fixed on the filing. `reportable_amount_cents` sums the `amount_cents` of every line item whose `kind` is `SERVICE_FEE` and whose `payment_date` falls within the calendar window from January 1 through December 31 of the `tax_year`, both endpoints inclusive; `EXPENSE_REIMBURSEMENT` items and service fees paid outside the window are excluded. `federal_filing_required` is true when the reportable amount is at least 60000 cents — the boundary is inclusive. `state_filing_required` is true when the reportable amount is at least the referenced jurisdiction's `state_filing_threshold_cents`, again inclusive. `signed_amount_cents` is the positive reportable amount for both `ORIGINAL` and `CORRECTION` filings. A new filing begins in `DRAFT` with `filed_at` null and `days_late` and `penalty_cents` at 0.

Submission moves a filing from `DRAFT` — or from `REJECTED_AGENCY`, the resubmission cycle — to `SUBMITTED`; submitting from any other status is rejected with `ERR_FILING_NOT_SUBMITTABLE` (HTTP 409). The contractor verification gate of §3.2 applies (`ERR_CONTRACTOR_NOT_VERIFIED`), and a `CORRECTION` filing additionally requires its `corrects_filing_id` target to be in `ACCEPTED` status, otherwise `ERR_CORRECTION_REQUIRES_ACCEPTED` (HTTP 409). On the first successful submission the filing's `filed_at` is stamped with the logical clock, and `days_late` and `penalty_cents` are computed: the filing deadline is January 31 of the year following the `tax_year`, `days_late` is the number of calendar days from that deadline to the filing date, floored at zero, and the penalty is 0 cents when the filing is on time, 6000 cents when between 1 and 30 days late inclusive, 13000 cents when between 31 and 121 days late inclusive, and 33000 cents when 122 or more days late. Resubmission after an agency rejection recomputes `days_late` and `penalty_cents` against the clock's new position. When a `CORRECTION` filing is submitted, its accepted target transitions `ACCEPTED → SUPERSEDED` — the target's signed amount leaves the contractor's lifetime total and the correction's enters — and every submission or resubmission increments the filing's `version`.

The agency's acknowledgement arrives through the `TaxReportingSpecialist` recording an `outcome`: `ACCEPTED` moves the filing `SUBMITTED → ACCEPTED`, while `REJECTED` moves it `SUBMITTED → REJECTED_AGENCY`, from which the resubmission cycle above can begin again. Separately, a filing in `SUBMITTED` or `ACCEPTED` may be voided by recording a correction whose `mode` is `VOID` together with a `reason`, moving it to the terminal `VOID` status.

All of these transitions reconcile one running total. A contractor's `lifetime_reported_cents` is the sum of `signed_amount_cents` over exactly those of the contractor's filings in `SUBMITTED` or `ACCEPTED` status; filings in `DRAFT`, `REJECTED_AGENCY`, `SUPERSEDED`, or `VOID` contribute nothing. The total is recomputed on every transition into or out of the counted set — submission, resubmission, agency response, void correction, and correction supersession — so the reconciliation invariant holds: a submission followed by a `VOID` correction of the same filing returns `lifetime_reported_cents` to its pre-submission value exactly.

### 3.9. Agency Inquiries and Conversion to Employment

When a regulator comes asking, an `AgencyLiaison` registers an **AgencyInquiry** against an engagement, recording the `agency_type` — `IRS`, `DOL`, `STATE_EDD`, or `STATE_UI` — the `received_at` instant, a `response_deadline`, the alleged `back_payments_cents` exposure base (zero or greater), and the `quarters_outstanding`, the whole quarters the alleged misclassification has persisted (zero or greater). Registration computes the `exposure_estimate_cents` in a pinned evaluation order that must not be rearranged. First, the base is taken as the alleged `back_payments_cents`. Second, a penalty is computed on that base: ten percent when the base is below 10000000 cents, twenty percent when the base is at least 10000000 but below 100000000 cents, and forty percent when the base is 100000000 cents or more — the tier is keyed on the pre-penalty base, and the penalty is rounded half up to whole cents. Third, simple interest accrues at five percent per outstanding quarter on the sum of the base and the penalty — interest compounds on back payments plus penalty, never on itself — rounded half up to whole cents. Fourth, the estimate is the sum of base, penalty, and interest. As a worked pin: a base of 5000000 cents with 2 quarters outstanding yields a penalty of 500000 cents, interest of 550000 cents, and a total exposure of 6050000 cents. A new inquiry begins in `RECEIVED`. The inquiries of an engagement are retrievable as a list, and the inquiry collection may be listed with `engagement_id` or `status` filters.

The `AgencyLiaison` responds to an inquiry by submitting a `response_summary`, which moves it `RECEIVED → RESPONSE_SUBMITTED` and is only permitted while the clock has not passed the `response_deadline`; a response after the deadline is rejected with `ERR_INQUIRY_DEADLINE_PASSED` (HTTP 422). Resolution then takes one of two shapes. Recording an `outcome` of `RESOLVED` moves the inquiry to its terminal `RESOLVED` status. Recording an `outcome` of `ESCALATE_TO_AUDIT` requires a `new_response_deadline` in the future (its absence, or a deadline not later than the clock, is `ERR_INVALID_REQUEST`) and moves the inquiry `RESPONSE_SUBMITTED → AUDIT_OPENED` with two side effects: a new RiskAudit is created against the inquiry's contractor with `audit_type` `FIELDWORK`, status `OPEN`, and `engagement_id` set to the inquiry's engagement — its provisional score computed from declared data exactly as a directly created audit — and the inquiry's `response_deadline` is replaced by `new_response_deadline`. From `AUDIT_OPENED`, a further response submission opens a new response round against the replacement deadline, moving the inquiry back to `RESPONSE_SUBMITTED`; the same deadline rule applies. Each of these steps increments the inquiry's `version`.

The terminal remedy for entrenched misclassification is conversion to employment. A `ComplianceOfficer` opens a **ConversionCase** against an engagement in `ACTIVE` or `SUSPENDED` status — any other status is rejected with `ERR_CONVERSION_NOT_POSSIBLE` (HTTP 409) — supplying `lookback_quarters`, exactly four entries each pairing a `quarter_label` with a `service_fee_cents` amount; any other entry count is `ERR_INVALID_REQUEST`. Creation immediately computes the lookback compensation with a pinned rounding order. For each quarter, in array order: the employer cost is the quarter's `service_fee_cents` multiplied by the employer tax factor 1.0765, rounded half up to whole cents; the benefits load is thirty percent of that **rounded** employer cost, itself rounded half up to whole cents; and the quarter's W-2 equivalent is the sum of the two. The `w2_equivalent_total_cents` is the sum of the four quarter equivalents, and `lookback_delta_cents` is that total minus the sum of the four `service_fee_cents` amounts. Rounding per quarter and then summing is mandatory: summing the bases first and applying the factors once yields different cents and is not compliant. On a lookback of 1000300, 1000400, 1005200, and 1003400 cents, the pinned order yields a W-2 equivalent total of 5610815 cents, where the sum-then-round order would yield 5610814. A new case begins in `INITIATED`, and the conversion cases of an engagement are retrievable as a list.

An `HRApprover` extends the employment offer, recording `offer_salary_cents` and moving the case `INITIATED → OFFER_EXTENDED`. The `EngagementManager` then records the worker's `decision`. A `DECLINED` decision moves the case to `DECLINED` and a `RESCINDED` decision to `RESCINDED`, both terminal and without further effect. An `ACCEPTED` decision requires the engagement to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and completes the case as `COMPLETED`, firing the conversion cascade: the source engagement moves `ACTIVE → CONVERTED`; that conversion moves the contractor's `standing_status` to `CONVERTED_TO_EMPLOYEE`; and that standing mutation rejects every other engagement of the same contractor still in a non-terminal status — `DRAFT`, `INTAKE_SUBMITTED`, `CLASSIFIED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVAL_PENDING`, or `APPROVED` — moving each to `REJECTED`. Every resource touched by the cascade has its `version` incremented.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including all action endpoints and the questionnaire upsert, which returns `200 OK` even on first submission — return `200 OK`. Rows marked **Any** in the role column are readable by every declared role of §2.1. Request bodies, computed fields, side effects, and the conditions under which each operation fails are defined by the workflows of §3 and the principles of §2; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/jurisdictions` | Create a jurisdiction classification regime | PlatformAdmin |
| GET | `/api/jurisdictions` | List jurisdictions | Any |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock (startup default 2026-08-01T00:00:00Z; never falls back to wall-clock) | PlatformAdmin |
| POST | `/api/contractors` | Register a contractor (business entity or individual) | EngagementManager |
| GET | `/api/contractors` | List contractors with filters | Any |
| GET | `/api/contractors/{id}` | Read one contractor (both parallel status dimensions, lifetime total) | Any |
| POST | `/api/contractors/{id}/verify` | Record a business entity verification decision | ComplianceOfficer |
| POST | `/api/engagements` | Open an engagement intake in `DRAFT` | EngagementManager |
| GET | `/api/engagements` | List engagements with filters | Any |
| GET | `/api/engagements/{id}` | Read one engagement (risk tier, approvals recorded, scope creep) | Any |
| POST | `/api/engagements/{id}/questionnaire` | Submit or resubmit the intake questionnaire (upsert; revision increments) | EngagementManager |
| GET | `/api/engagements/{id}/questionnaire` | Read the questionnaire of an engagement (array of length 0 or 1) | Any |
| POST | `/api/engagements/{id}/determinations` | Run the jurisdiction classification test (OCC-guarded; supersedes the prior determination) | ClassificationAnalyst |
| GET | `/api/engagements/{id}/determinations` | List all determinations of an engagement, newest first | Any |
| POST | `/api/engagements/{id}/submit-review` | Move a classified engagement `CLASSIFIED → UNDER_REVIEW` | EngagementManager |
| POST | `/api/engagements/{id}/request-info` | Suspend review `UNDER_REVIEW → INFO_REQUESTED` | ClassificationAnalyst |
| POST | `/api/engagements/{id}/submit-approval` | Move `UNDER_REVIEW → APPROVAL_PENDING`; requires a fresh determination | ClassificationAnalyst |
| POST | `/api/engagements/{id}/approve` | Record the next quorum approval; auto-approves at quorum; segregation of duties enforced | HRApprover, LegalApprover, ComplianceBoardMember |
| POST | `/api/engagements/{id}/reject` | Reject from `UNDER_REVIEW` or `APPROVAL_PENDING` | ClassificationAnalyst, HRApprover, LegalApprover, ComplianceBoardMember |
| POST | `/api/engagements/{id}/activate` | Move `APPROVED → ACTIVE`; requires an executed contract and contractor standing | EngagementManager |
| POST | `/api/engagements/{id}/suspend` | Move `ACTIVE → SUSPENDED`; fires the four-link suspension cascade | ComplianceOfficer |
| POST | `/api/engagements/{id}/reinstate` | Move `SUSPENDED → ACTIVE`; restores the contract but not voided amendments or revoked exceptions | ComplianceOfficer |
| POST | `/api/engagements/{id}/terminate` | Move `ACTIVE` or `SUSPENDED → TERMINATED`; terminates the contract | ComplianceOfficer |
| POST | `/api/engagements/{id}/exceptions` | Grant a documented classification-risk exception (capacity-gated per jurisdiction) | ComplianceBoardMember |
| GET | `/api/engagements/{id}/exceptions` | List the exception grants of an engagement | Any |
| POST | `/api/exceptions/{id}/revoke` | Revoke an active grant; contractor standing recomputed to `WATCH` | ComplianceBoardMember |
| POST | `/api/engagements/{id}/contracts` | Draft a contract for an `APPROVED` or `ACTIVE` engagement; half-open overlap check | EngagementManager |
| GET | `/api/engagements/{id}/contracts` | List the contracts of an engagement | Any |
| GET | `/api/contracts/{id}` | Read one contract | Any |
| GET | `/api/contracts` | List contracts with filters | Any |
| POST | `/api/contracts/{id}/execute` | Move `DRAFT → EXECUTED`; verification, insurance, and high-tier exception gates | EngagementManager |
| POST | `/api/contracts/{id}/amendments` | Propose an amendment (OCC-guarded on contract version) | EngagementManager |
| GET | `/api/contracts/{id}/amendments` | List the amendments of a contract | Any |
| POST | `/api/amendments/{id}/approve` | Adjudicate an amendment: approve applies it in the same request, or reject | LegalApprover |
| POST | `/api/engagements/{id}/reviews` | Schedule a monitoring review (engagement must be `ACTIVE`; 30-day minimum gap) | ComplianceOfficer |
| GET | `/api/engagements/{id}/reviews` | List the reviews of an engagement | Any |
| POST | `/api/reviews/{id}/close` | Close a review with findings; findings require linked open remediation actions of the same contractor | ComplianceOfficer |
| POST | `/api/audits` | Open a reclassification risk audit; provisional score computed | ComplianceOfficer |
| GET | `/api/audits` | List audits with filters | Any |
| GET | `/api/audits/{id}` | Read one audit (scores, level, open action count) | Any |
| POST | `/api/audits/{id}/finalize` | Finalize findings; computes the final score and applies standing effects | ComplianceOfficer |
| POST | `/api/audits/{id}/remediation-actions` | Create a remediation action on a finalized audit | ComplianceOfficer |
| GET | `/api/audits/{id}/remediation-actions` | List the remediation actions of an audit | Any |
| POST | `/api/remediation-actions/{id}/close` | Close or waive an action; decrements the audit's open count; may restore standing | ComplianceOfficer |
| POST | `/api/audits/{id}/close` | Close an audit under the status-specific closure rules | ComplianceOfficer |
| POST | `/api/filings` | Create a 1099 filing (`ORIGINAL` or `CORRECTION`); reporting math fixed at creation | TaxReportingSpecialist |
| GET | `/api/filings` | List filings with filters | Any |
| GET | `/api/filings/{id}` | Read one filing | Any |
| POST | `/api/filings/{id}/submit` | Submit (or resubmit) a filing; verification gate; penalty computed; corrections supersede | TaxReportingSpecialist |
| POST | `/api/filings/{id}/agency-response` | Record the agency acknowledgement: accepted or rejected | TaxReportingSpecialist |
| POST | `/api/filings/{id}/correct` | Void a submitted or accepted filing (compensating action of submit) | TaxReportingSpecialist |
| POST | `/api/engagements/{id}/inquiries` | Register an incoming agency inquiry; exposure estimate computed | AgencyLiaison |
| GET | `/api/engagements/{id}/inquiries` | List the inquiries of an engagement | Any |
| GET | `/api/inquiries` | List inquiries with filters | Any |
| POST | `/api/inquiries/{id}/respond` | Submit a response; deadline enforced against the logical clock | AgencyLiaison |
| POST | `/api/inquiries/{id}/resolve` | Resolve the inquiry, or escalate to audit (creates a fieldwork audit, sets a new deadline) | AgencyLiaison |
| POST | `/api/engagements/{id}/conversions` | Open a conversion-to-employment case; lookback compensation computed at creation | ComplianceOfficer |
| GET | `/api/engagements/{id}/conversions` | List the conversion cases of an engagement | Any |
| POST | `/api/conversions/{id}/extend-offer` | Extend the employment offer with a salary | HRApprover |
| POST | `/api/conversions/{id}/record-decision` | Record the decision: accepted (fires the conversion cascade), declined, or rescinded | EngagementManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3 alongside the workflows they guard; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DETERMINATION_REQUIRED` | 409 Conflict |
| `ERR_DETERMINATION_STALE` | 409 Conflict |
| `ERR_QUESTIONNAIRE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_ENGAGEMENT_NOT_APPROVAL_PENDING` | 409 Conflict |
| `ERR_APPROVAL_OUT_OF_ORDER` | 409 Conflict |
| `ERR_APPROVER_ALREADY_ACTED` | 409 Conflict |
| `ERR_EXCEPTION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EXCEPTION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_EXCEPTION_CAPACITY_REACHED` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_CONTRACTOR_STANDING_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_INSURANCE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_EXECUTED` | 409 Conflict |
| `ERR_CONTRACT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REVIEW_INTERVAL_TOO_SHORT` | 409 Conflict |
| `ERR_REVIEW_NOT_CLOSABLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FILING` | 409 Conflict |
| `ERR_FILING_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_CORRECTION_REQUIRES_ACCEPTED` | 409 Conflict |
| `ERR_AUDIT_NOT_OPEN` | 409 Conflict |
| `ERR_AUDIT_ACTIONS_OPEN` | 409 Conflict |
| `ERR_INQUIRY_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CONVERSION_NOT_POSSIBLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
