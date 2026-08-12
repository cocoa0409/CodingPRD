# Third-Party Vendor Risk Management API — Product Requirements Document

## 1. Introduction

Financial institutions operate under strict regulatory expectations for how they onboard, monitor, and exit third-party vendors. Supervisory frameworks increasingly demand that banks demonstrate a complete audit trail for every outsourced relationship: who vetted the vendor, what contractual protections were negotiated, how the vendor is monitored on an ongoing basis, which subcontractors touch regulated data, and how the institution responds when the vendor fails. This document describes the Third-Party Vendor Risk Management (TPRM) API, which supports this end-to-end oversight discipline.

The platform serves six operational roles across the vendor-management lifecycle. A `VendorRelationshipManager` onboards new vendors and drafts engagements, contracts, and due-diligence packages. A `RiskOfficer` independently approves due diligence, executes contracts, triages incidents, and administers remediation plans. A `BusinessUnitOwner` files incidents from the line of business and is the only role permitted to verify remediation outcomes. An `InternalAuditor` exercises the contractual right-to-audit on engagements, outside day-to-day operations. A `ComplianceDirector` publishes concentration assessments and board reports, and may waive monitoring cycles for the lowest-tier vendors. A `PlatformAdmin` exists solely to drive test-time operations on the logical clock and holds no vendor-management permissions.

The API is mounted under `/tprm`. It covers vendor inventory and criticality tiering, due-diligence packages with independent financial, security, and compliance review, contract-clause enforcement tied to vendor tier, fourth-party subcontractor registration and acknowledgement, tier-cadenced monitoring cycles, incident and remediation workflows, concentration-risk assessment by region or service category, business-continuity testing with RTO/RPO verification, internal audit exercises, and board-level reporting. State integrity, segregation of duties, and optimistic concurrency are first-class concerns throughout.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role identified by `X-User-Role` is not authorized for the target endpoint per §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six role names are spelled exactly: `VendorRelationshipManager`, `RiskOfficer`, `BusinessUnitOwner`, `InternalAuditor`, `ComplianceDirector`, and `PlatformAdmin`. For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does record it in specific places — `onboarded_by_user_id` on `Vendor`, `started_by_user_id` on `VendorEngagement`, `submitted_by_user_id` and `approver_user_id` on `DueDiligencePackage`, `reported_by_user_id` on `Incident`, `owner_user_id` and `approved_by_user_id` on `RemediationPlan`, `exercised_by_user_id` on `AuditExercise`, `acknowledged_by_user_id` on `FourthParty`, `waived_by_user_id` on `MonitoringCycle`, `published_by_user_id` on `ConcentrationAssessment` and `BoardReport`, and `changed_by_user_id` on `RiskTierChangeLog` — and uses these recorded values to enforce segregation of duties. The server does not, however, compare `X-User-ID` against any entity's `id` for ownership checks.

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

List endpoints accept the optional query parameters `limit` and `offset`. The default value of `limit` is 10, with a minimum of 1 and a maximum of 100. The default value of `offset` is 0. List responses return the pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`. Unless an endpoint documents otherwise, list results are sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties and Identity Conventions

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` that is an ISO 8601 UTC timestamp with three fractional digits. Entities marked as carrying the full set of common fields also expose `updated_at` (same timestamp format, refreshed on every mutation) and `version` (an integer incremented by exactly 1 on every mutation of that entity). The entities carrying full common fields are `Vendor`, `VendorEngagement`, `DueDiligencePackage`, `Contract`, `FourthParty`, `MonitoringCycle`, `Incident`, `RemediationPlan`, `ConcentrationAssessment`, `BusinessContinuityTest`, `AuditExercise`, and `BoardReport`. Three entities are exceptions and carry only `id` and `created_at`: `ConcentrationBucket`, `AuditFinding`, and `RiskTierChangeLog` — these do not have `updated_at` and do not have `version`.

### 2.5. Nested Resource Retrieval and Path-Parameter Resolution

Many resources are reachable through hierarchical paths (vendor → engagement → child entity). Path-templated resource identifiers resolve left-to-right: the vendor identifier is resolved first, then the engagement identifier scoped to that vendor, then the child identifier scoped to that engagement. If any segment fails to resolve, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later segment is considered.

### 2.6. Precision, Rounding, and Numeric Representation

All monetary and percentage values computed by the system use 2 decimal places with round-half-up unless a specific calculation documents otherwise. The composite risk score, the due-diligence aggregate score, the concentration share percentage, and the exit readiness score all follow this rule. Dates and datetimes are represented as ISO 8601 UTC strings with second precision on computed scheduling fields (`due_at`, `remediation_due_at`, `next_monitoring_due_at`) and three-fractional-digit precision on event timestamps (`created_at`, `updated_at`, `completed_at`, `closed_at`, `published_at`, `computed_at`, `initiated_at`).

### 2.7. Optimistic Concurrency Control

Three write endpoints require the caller to supply a version field captured from the caller's most recent read of the parent entity. Approving a due-diligence package, executing a contract, and changing a vendor's criticality tier each take a required `expected_engagement_version` (for the first two) or `expected_vendor_version` (for the third) carrying the caller's last observed `version` of the `VendorEngagement` or `Vendor`. If the value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from overwriting changes it has not observed. No other endpoints accept a version field.

### 2.8. Logical Clock and Time-Dependent Rules

The server maintains a logical clock used by all time-dependent rules — monitoring-cycle overdue promotion, contract expiry promotion, deadline computation, and time-window inclusion. The server boots at 2026-05-01T00:00:00Z and must not fall back to wall-clock time before the clock is first set via the dedicated clock-set capability, which accepts a `to_iso8601` timestamp parameter naming the new current instant. Setting the clock forward triggers every system-driven promotion whose threshold is crossed by the new time: any `MonitoringCycle` still in `SCHEDULED` or `IN_PROGRESS` whose `due_at` is earlier than the new clock value transitions to `OVERDUE`, and any `Contract` in `EXECUTED` whose `expiry_date` is at or earlier than the new clock value transitions to `EXPIRED` provided its engagement is no longer `ACTIVE`. Any vendor whose monitoring cycles were promoted to `OVERDUE` has its `tier_posture` recomputed as part of the same atomic operation.

### 2.9. State Enumeration Values

The following state names appear verbatim throughout this document. `Vendor.status` ∈ {`ONBOARDING`, `ACTIVE`, `SUSPENDED`, `EXITED`}. `Vendor.tier_posture` ∈ {`CLEAN`, `WATCH`, `ESCALATED`, `BREACH`}. `Vendor.criticality_tier` ∈ {`TIER_1_CRITICAL`, `TIER_2_HIGH`, `TIER_3_STANDARD`, `TIER_4_LOW`}. `Vendor.headquarters_region` ∈ {`NA`, `EMEA`, `APAC`, `LATAM`}. `Vendor.service_category` ∈ {`CLOUD_INFRA`, `PAYMENTS`, `KYC_AML`, `DATA_ANALYTICS`, `CUSTODIAL`, `BPO`, `LEGAL`, `OTHER`}. `VendorEngagement.lifecycle_status` ∈ {`DRAFT`, `DD_IN_PROGRESS`, `DD_APPROVED`, `CONTRACTING`, `ACTIVE`, `EXITING`, `EXITED`, `TERMINATED_FOR_CAUSE`}. `VendorEngagement.risk_attention_state` ∈ {`NORMAL`, `UNDER_REVIEW`, `REMEDIATION_REQUIRED`}. `VendorEngagement.data_sensitivity` ∈ {`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `REGULATED`}. `DueDiligencePackage.status` ∈ {`DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `SUPERSEDED`}. `DueDiligencePackage.dd_outcome` ∈ {`PENDING`, `PASS`, `CONDITIONAL_PASS`, `FAIL`}. `Contract.status` ∈ {`DRAFT`, `EXECUTED`, `EXPIRED`, `TERMINATED`}. `FourthParty.acknowledgement_status` ∈ {`PENDING`, `ACKNOWLEDGED`, `REJECTED`}. `FourthParty.data_access_level` ∈ {`NONE`, `METADATA`, `PII`, `REGULATED_PII`}. `MonitoringCycle.status` ∈ {`SCHEDULED`, `IN_PROGRESS`, `COMPLETED_ON_TIME`, `COMPLETED_LATE`, `OVERDUE`, `WAIVED`}. `Incident.incident_type` ∈ {`DATA_BREACH`, `SLA_BREACH`, `OUTAGE`, `FINANCIAL_DISTRESS`, `REGULATORY_FINDING`, `FOURTH_PARTY_EVENT`}. `Incident.severity` ∈ {`SEV_1`, `SEV_2`, `SEV_3`, `SEV_4`}. `Incident.status` ∈ {`OPEN`, `TRIAGED`, `REMEDIATION_PLANNED`, `REMEDIATION_IN_PROGRESS`, `AWAITING_VERIFICATION`, `CLOSED`, `REOPENED`}. `RemediationPlan.status` ∈ {`DRAFT`, `SUBMITTED`, `APPROVED`, `IN_EXECUTION`, `VERIFICATION_SUBMITTED`, `VERIFIED`, `REJECTED`}. `ConcentrationAssessment.status` ∈ {`COMPUTING`, `PUBLISHED`, `SUPERSEDED`}. `ConcentrationAssessment.grouping_dimension` ∈ {`REGION`, `SERVICE_CATEGORY`}. `BusinessContinuityTest.status` ∈ {`SCHEDULED`, `IN_PROGRESS`, `PASSED`, `FAILED`, `CANCELLED`}. `BusinessContinuityTest.outcome` ∈ {`PASS`, `FAIL`}. `BusinessContinuityTest.scenario` ∈ {`FULL_FAILOVER`, `PARTIAL_DEGRADATION`, `CYBER_INCIDENT`, `DATA_RESTORE`}. `AuditExercise.scope` ∈ {`SECURITY`, `FINANCIAL`, `OPERATIONAL`, `REGULATORY`, `FULL`}. `AuditExercise.status` ∈ {`INITIATED`, `FIELDWORK`, `FINDINGS_ISSUED`, `CLOSED`}. `AuditFinding.severity` ∈ {`SEV_1`, `SEV_2`, `SEV_3`, `SEV_4`}. `BoardReport.status` ∈ {`DRAFT`, `PUBLISHED`}.

### 2.10. Soft-Delete and Archival

Vendors are never physically deleted. When a `Vendor` reaches `EXITED`, the system sets its `archived_at` to the current timestamp. Once `archived_at` is non-null, the vendor is excluded from uniqueness checks on `legal_name`, excluded from concentration aggregation, and excluded from board-report vendor counts. List endpoints accept an `include_archived` flag to surface archived vendors when needed.

### 2.11. Atomicity of Side Effects

All side effects triggered by a transition — tier recompute, posture recompute, monitoring-cycle scheduling, cascade into parent or sibling entities, audit-log writes — commit atomically within the triggering request. There is no eventual-consistency window during which an observer can see a partially applied transition.

## 3. Business Logic & Workflows

### 3.1. Vendor Onboarding and Inventory

A `VendorRelationshipManager` opens a new vendor relationship by creating a `Vendor` record with `legal_name`, `headquarters_region`, and `service_category`. The server rejects the creation when another non-archived vendor already holds the same `legal_name`, returning `ERR_DUPLICATE_KEY` (HTTP 409). The server stamps `onboarded_by_user_id` from `X-User-ID`, initializes `status` to `ONBOARDING`, initializes `criticality_tier` to `TIER_3_STANDARD`, sets `composite_risk_score` to 0, and sets `tier_posture` to `CLEAN`. If the caller supplies values for `composite_risk_score`, `tier_posture`, `id`, `version`, `created_at`, or `updated_at` in the creation payload, those values are accepted but ignored — the server always mints its own. While the vendor remains in `ONBOARDING`, `next_monitoring_due_at` is null because no monitoring cycle has been scheduled yet.

### 3.2. Engagement Lifecycle from Draft to Active

Against an existing vendor, a `VendorRelationshipManager` creates a `VendorEngagement` by supplying `engagement_code` (unique within the vendor; duplicates are rejected with `ERR_DUPLICATE_KEY`), `service_summary`, `annual_spend_cents` (must be greater than or equal to zero), and `data_sensitivity`. The server sets `lifecycle_status` to `DRAFT`, sets `risk_attention_state` to `NORMAL`, stamps `started_by_user_id` from `X-User-ID`, and records the owning vendor's `id` on the engagement's `vendor_id` field.

Due diligence begins when the manager creates the first `DueDiligencePackage` on the engagement. The server records the parent engagement on the package's `engagement_id` field. The package payload carries `financial_review_score`, `security_review_score`, and `compliance_review_score` (each an integer between 0 and 100 inclusive), together with `financial_reviewer_id`, `security_reviewer_id`, and `compliance_reviewer_id` identifying the three analysts. Creating the package requires the engagement to be in `DRAFT`; otherwise the request is rejected with `ERR_ENGAGEMENT_NOT_DRAFT` (HTTP 409). On creation the package lands in `DRAFT` with `review_round` equal to 1, and the engagement transitions `DRAFT → DD_IN_PROGRESS` as a side effect.

When the manager believes the package is complete, they submit it. Submission requires the package to be in `DRAFT` and all three review scores to be present, otherwise `ERR_DD_NOT_DRAFT` (HTTP 409). On submission the server stamps `submitted_by_user_id` from `X-User-ID`, computes `aggregate_dd_score` as the weighted sum of the three review scores using tier-dependent weights (see §3.3), derives `dd_outcome`, and transitions the package `DRAFT → SUBMITTED`.

A `RiskOfficer` then moves the package to `UNDER_REVIEW` via the begin-review capability, which requires the package to be in `SUBMITTED` (otherwise `ERR_DD_NOT_SUBMITTED`, HTTP 409). While the package is `UNDER_REVIEW`, the officer may either approve it or reject it. Approval requires the package to be `UNDER_REVIEW` (otherwise `ERR_DD_NOT_UNDER_REVIEW`, HTTP 409), requires that `X-User-ID` differ from `submitted_by_user_id` (otherwise `ERR_SOD_DD_SELF_APPROVE`, HTTP 403), and requires `dd_outcome` to be either `PASS` or `CONDITIONAL_PASS` (otherwise `ERR_DD_OUTCOME_FAIL`, HTTP 422). Approval is also OCC-guarded: the request must carry `expected_engagement_version` matching the engagement's current `version`, otherwise `ERR_STALE_VERSION` (HTTP 412). On successful approval the server stamps `approver_user_id`, transitions the engagement `DD_IN_PROGRESS → DD_APPROVED` if it is still in `DD_IN_PROGRESS`, increments the engagement's `version` by 1, and supersedes any previously `APPROVED` package on the same engagement (that older package transitions `APPROVED → SUPERSEDED`). Rejection requires the package to be `UNDER_REVIEW` and the same segregation-of-duties check, but does not require a passing outcome and does not bump the engagement. Rejection transitions the package `UNDER_REVIEW → REJECTED`.

A rejected package can be resubmitted by a `VendorRelationshipManager` while its `review_round` is still less than 3; attempts to resubmit at `review_round` equal to 3 are rejected with `ERR_DD_REVIEW_ROUND_EXHAUSTED` (HTTP 422), and attempts to resubmit a package not in `REJECTED` are rejected with `ERR_DD_NOT_REJECTED` (HTTP 409). Resubmission may carry updated values for any of `financial_review_score`, `security_review_score`, or `compliance_review_score`. On resubmit, `review_round` is incremented by 1 and `aggregate_dd_score` and `dd_outcome` are recomputed from the (possibly edited) scores using the tier weights in force at this new submission instant.

### 3.3. Due-Diligence Aggregate Score

The `aggregate_dd_score` is the weighted sum of the three review scores. Weights depend on the vendor's `criticality_tier` at the moment of submission. For `TIER_1_CRITICAL` vendors, the financial, security, and compliance weights are 0.25, 0.45, and 0.30 respectively. For `TIER_2_HIGH` vendors, they are 0.30, 0.40, and 0.30. For `TIER_3_STANDARD` vendors, they are 0.40, 0.35, and 0.25. For `TIER_4_LOW` vendors, they are 0.50, 0.25, and 0.25. The raw weighted sum is rounded half-up to two decimal places and stored on `aggregate_dd_score`.

The outcome `dd_outcome` is then derived from the score: a value of at least 75.00 yields `PASS`; a value of at least 60.00 but less than 75.00 yields `CONDITIONAL_PASS`; any lower value yields `FAIL`. Before the score is computed the outcome holds the sentinel `PENDING`. Score semantics are snapshot-at-submit: a subsequent tier change on the vendor does not recompute the score on already-submitted packages. An approved package remains valid for its engagement even if the vendor is later re-tiered.

### 3.4. Contracting, Clause Completeness, and Execution

Once the engagement reaches `DD_APPROVED`, a `VendorRelationshipManager` drafts a `Contract` on the engagement by supplying `contract_reference` (unique within the vendor; duplicates are rejected with `ERR_DUPLICATE_KEY`), `effective_date`, `expiry_date`, the three clause flags `has_right_to_audit_clause`, `has_sla_terms`, and `has_exit_plan_section`, plus `sla_uptime_pct`, `breach_cure_window_days`, and `renewal_notice_days`. Creation requires the engagement to be in `DD_APPROVED`, otherwise `ERR_DD_NOT_APPROVED` (HTTP 409). The expiry must be strictly later than the effective date, otherwise `ERR_TEMPORAL_ORDER` (HTTP 422). `sla_uptime_pct` must lie in the range 90.000 to 100.000 inclusive, `breach_cure_window_days` must be at least 1, and `renewal_notice_days` must be at least 0. On creation the contract lands in `DRAFT` and the engagement transitions `DD_APPROVED → CONTRACTING`. `version_pin_dd_package_id` remains null until execution.

Execution is performed by a `RiskOfficer` and is the action that takes the engagement live. Execution enforces several checks, evaluated in this order so that the most foundational problems surface first: the contract must be in `DRAFT` (otherwise `ERR_CONTRACT_NOT_DRAFT`, HTTP 409); the OCC check on the engagement's `version` is applied via `expected_engagement_version` (mismatch yields `ERR_STALE_VERSION`, HTTP 412); `has_sla_terms` must be true on every tier (otherwise `ERR_MISSING_SLA_TERMS`, HTTP 422); if the vendor's `criticality_tier` is `TIER_1_CRITICAL` or `TIER_2_HIGH` then `has_right_to_audit_clause` must be true (otherwise `ERR_MISSING_AUDIT_CLAUSE`, HTTP 422); if the vendor is `TIER_1_CRITICAL` then `has_exit_plan_section` must be true (otherwise `ERR_MISSING_EXIT_PLAN`, HTTP 422); and finally every `FourthParty` on the engagement must have `acknowledgement_status` equal to `ACKNOWLEDGED` (otherwise `ERR_FOURTH_PARTY_PENDING`, HTTP 422). On success the contract transitions `DRAFT → EXECUTED`, `version_pin_dd_package_id` is set to the id of the most recently approved `DueDiligencePackage` on the engagement (this pin is permanent for the life of the contract — subsequent modifications to that DD package do not revalidate the contract, only a new execution would), the engagement transitions `CONTRACTING → ACTIVE`, and the vendor's `composite_risk_score` is recomputed. If the vendor was still in `ONBOARDING`, it remains in `ONBOARDING` — vendor activation is a separate `RiskOfficer` step.

A contract in `EXECUTED` later transitions to `EXPIRED` automatically when the logical clock reaches or passes `expiry_date` and the engagement is no longer `ACTIVE` (that is, when `lifecycle_status` is `EXITING`, `EXITED`, or `TERMINATED_FOR_CAUSE`). It transitions to `TERMINATED` automatically when its parent engagement transitions to `TERMINATED_FOR_CAUSE`.

### 3.5. Fourth-Party Subcontractor Registration

A `VendorRelationshipManager` declares subcontractors on an engagement. Each `FourthParty` carries `name`, `service_provided`, `data_access_level`, and an optional `parent_fourth_party_id`. When `parent_fourth_party_id` is provided it must reference an existing `FourthParty` on the same engagement, and the resulting chain must be cycle-free (a fourth party cannot be its own ancestor); violations are rejected with `ERR_FP_PARENT_INVALID` (HTTP 422). A null `parent_fourth_party_id` indicates a direct subcontractor; a non-null value indicates a sub-sub-contractor. New fourth parties land in `PENDING`.

A `RiskOfficer` acknowledges or rejects each fourth party. Both actions require the current status to be `PENDING`, otherwise `ERR_FP_NOT_PENDING` (HTTP 409). Acknowledgement is additionally tier-gated: if the fourth party's `data_access_level` is `REGULATED_PII`, the vendor's `criticality_tier` must be `TIER_1_CRITICAL` or `TIER_2_HIGH`; otherwise the acknowledgement is rejected with `ERR_FP_PII_TIER_TOO_LOW` (HTTP 422). On acknowledgement the server stamps `acknowledged_by_user_id` from `X-User-ID`. On rejection the engagement's `risk_attention_state` is set to `UNDER_REVIEW`. Contract execution is blocked while any fourth party remains in `PENDING`.

### 3.6. Vendor Activation, Suspension, Reinstatement, and Exit

A `RiskOfficer` activates a vendor once its first engagement is live. Activation requires the vendor to be in `ONBOARDING` (otherwise `ERR_VENDOR_NOT_ONBOARDING`, HTTP 409), requires at least one engagement in `ACTIVE` (otherwise `ERR_NO_ACTIVE_ENGAGEMENT`, HTTP 422), and requires the absence of any `OPEN` or `REOPENED` incident with severity `SEV_1` on any of the vendor's engagements (otherwise `ERR_OPEN_SEV1_INCIDENT`, HTTP 422). On activation the server recomputes `composite_risk_score`, creates the first `MonitoringCycle` with `due_at` derived from the tier cadence (see §3.7), and sets `next_monitoring_due_at` to that cycle's `due_at`.

Suspension moves a vendor `ACTIVE → SUSPENDED`. It requires the vendor to be `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`, HTTP 409) and at least one triggering condition: an `OPEN` or `REOPENED` `SEV_1` incident on any engagement, any monitoring cycle that has been `OVERDUE` for more than 30 days, or a `FAILED` business-continuity test on a `TIER_1_CRITICAL` engagement. On suspension every `ACTIVE` engagement on the vendor has its `risk_attention_state` set to `UNDER_REVIEW`, and `next_monitoring_due_at` is cleared to null because no new cycles are scheduled while suspended.

Reinstatement moves a vendor `SUSPENDED → ACTIVE`. It requires the vendor to be `SUSPENDED` (otherwise `ERR_VENDOR_NOT_SUSPENDED`, HTTP 409), no `OPEN` or `REOPENED` `SEV_1` incidents anywhere on the vendor, and no monitoring cycle in `OVERDUE`. On reinstatement the server recomputes `composite_risk_score` and schedules the next monitoring cycle from the current instant per tier cadence.

Vendor exit moves `ACTIVE → EXITED`. It requires the vendor to be `ACTIVE`, every engagement to be in either `EXITED` or `TERMINATED_FOR_CAUSE` (otherwise `ERR_ENGAGEMENTS_NOT_EXITED`, HTTP 422), and no `OPEN` or `REOPENED` incidents anywhere on the vendor (otherwise `ERR_OPEN_INCIDENTS_REMAIN`, HTTP 422). On exit the server sets `archived_at` to the current timestamp (soft archive) and clears `next_monitoring_due_at` to null.

### 3.7. Tier-Cadenced Monitoring

Monitoring cycles are scheduled on a cadence driven by the vendor's `criticality_tier`. A `TIER_1_CRITICAL` vendor is monitored every 90 days, `TIER_2_HIGH` every 180 days, `TIER_3_STANDARD` every 365 days, and `TIER_4_LOW` every 730 days. The first cycle is anchored to the vendor's activation instant; subsequent cycles are anchored to the previous cycle's `completed_at`. When a cycle is waived, the next cycle is anchored to the waived cycle's `due_at` rather than to the waive instant. Each cycle stores a snapshot of the cadence in force at scheduling time in `cadence_days`, plus a monotonically increasing `cycle_index` per vendor (1, 2, 3, …). Cycle windows are half-open: at most one cycle per vendor may be in `SCHEDULED` or `IN_PROGRESS` at any instant, and a new cycle's window must not overlap the window of any prior non-`WAIVED` cycle on the same vendor. Adjacent windows with no gap are permitted. Violations surface as `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 422) at the moment the system would schedule a conflicting cycle.

A `RiskOfficer` begins a scheduled cycle, which requires the cycle to be `SCHEDULED` (otherwise `ERR_CYCLE_NOT_SCHEDULED`, HTTP 409) and the vendor to be `ACTIVE` (otherwise `ERR_VENDOR_NOT_ACTIVE`, HTTP 409). Completion of an in-progress cycle requires the cycle to be `IN_PROGRESS` (otherwise `ERR_CYCLE_NOT_IN_PROGRESS`, HTTP 409) and may carry an optional `findings_summary`. The completion instant relative to `due_at` determines the outcome: completion at or before `due_at` lands the cycle in `COMPLETED_ON_TIME`; completion strictly after `due_at` lands it in `COMPLETED_LATE`. In both cases the server stamps `completed_at`, schedules the next cycle per tier cadence anchored to this `completed_at`, and updates `next_monitoring_due_at`. A late completion additionally triggers a `tier_posture` recompute (typically pushing the vendor to `WATCH` or `ESCALATED`). A `SCHEDULED` or `IN_PROGRESS` cycle is promoted to `OVERDUE` by the system the moment the logical clock advances past its `due_at`; this promotion also triggers a `tier_posture` recompute.

A `ComplianceDirector` may waive a scheduled cycle, but only for `TIER_4_LOW` vendors; attempts on other tiers are rejected with `ERR_WAIVE_TIER_FORBIDDEN` (HTTP 422), and attempts on non-`SCHEDULED` cycles are rejected with `ERR_CYCLE_NOT_SCHEDULED`. On waive the server stamps `waived_by_user_id` and schedules the next cycle anchored to the waived cycle's `due_at`.

### 3.8. Incident Intake, Triage, and Remediation

A `BusinessUnitOwner` files an `Incident` on an engagement by supplying `incident_type`, `severity`, and `detected_at`. New incidents land in `OPEN` with `reported_by_user_id` stamped from `X-User-ID` and `reopen_count` initialized to 0.

A `RiskOfficer` triages an `OPEN` incident (otherwise `ERR_INCIDENT_NOT_OPEN`, HTTP 409). At triage the server computes `remediation_due_at` by adding an effective window to the triage instant. The base window depends on severity: 7 days for `SEV_1`, 30 days for `SEV_2`, 90 days for `SEV_3`, and 180 days for `SEV_4`. If the engagement has an `EXECUTED` contract, the contract's `breach_cure_window_days` narrows the window when shorter — the effective window is the smaller of the severity window and the contractual cure window. The triage side effects also include setting the engagement's `risk_attention_state` to `UNDER_REVIEW` if it was `NORMAL`, and recomputing the vendor's `tier_posture`.

Once triaged, a `RiskOfficer` drafts a `RemediationPlan` on the incident by supplying `plan_summary` and `committed_completion_date`. The server records the parent incident's `id` on the plan's `incident_id` field. The committed completion date must not be later than the incident's `remediation_due_at`, otherwise `ERR_TEMPORAL_ORDER` (HTTP 422). The drafting officer must not be the same user as `reported_by_user_id` on the incident, otherwise `ERR_SOD_INCIDENT_SELF_REMEDIATE` (HTTP 403). Plan creation requires the incident to be `TRIAGED` (otherwise `ERR_INCIDENT_NOT_TRIAGED`, HTTP 409), stamps `owner_user_id` from `X-User-ID`, lands the plan in `DRAFT`, and transitions the incident `TRIAGED → REMEDIATION_PLANNED`.

The plan moves `DRAFT → SUBMITTED` when the owning officer submits it (requires `DRAFT`, otherwise `ERR_PLAN_NOT_DRAFT`, HTTP 409). Approval is performed by a `RiskOfficer` other than the plan owner and other than the incident reporter — violating either constraint yields `ERR_SOD_PLAN_SELF_APPROVE` (HTTP 403). Approval requires the plan to be `SUBMITTED` (otherwise `ERR_PLAN_NOT_SUBMITTED`, HTTP 409) and, atomically within the same request, transitions the plan `SUBMITTED → APPROVED → IN_EXECUTION` while the incident transitions `REMEDIATION_PLANNED → REMEDIATION_IN_PROGRESS`. Rejection by a `RiskOfficer` (also excluding the plan owner via `ERR_SOD_PLAN_SELF_APPROVE`) requires the plan to be `SUBMITTED` and reverts the incident to `TRIAGED`.

When execution has produced evidence, a `RiskOfficer` submits verification by supplying `verification_evidence_uri`. This requires the plan to be `IN_EXECUTION` (otherwise `ERR_PLAN_NOT_IN_EXECUTION`, HTTP 409) and requires a non-empty `verification_evidence_uri` (otherwise `ERR_EVIDENCE_REQUIRED`, HTTP 422). On submission the plan transitions `IN_EXECUTION → VERIFICATION_SUBMITTED` and the incident transitions `REMEDIATION_IN_PROGRESS → AWAITING_VERIFICATION`.

Verification is performed by a `BusinessUnitOwner` and only by the same user who filed the incident — any other user yields `ERR_SOD_VERIFY_NOT_REPORTER` (HTTP 403). Verification requires the plan to be `VERIFICATION_SUBMITTED` (otherwise `ERR_PLAN_NOT_VERIFICATION_SUBMITTED`, HTTP 409). On success the plan transitions `VERIFICATION_SUBMITTED → VERIFIED`, the incident transitions `AWAITING_VERIFICATION → CLOSED`, the server stamps `closed_at`, the engagement's `risk_attention_state` returns to `NORMAL` if no other `OPEN` or `REOPENED` incidents remain on that engagement, and the vendor's `tier_posture` is recomputed.

A `BusinessUnitOwner` may reopen a closed incident, but only the same user who filed it (otherwise `ERR_SOD_REOPEN_NOT_REPORTER`, HTTP 403), only when the incident is `CLOSED` (otherwise `ERR_INCIDENT_NOT_CLOSED`, HTTP 409), and only while `reopen_count` is less than 2 (otherwise `ERR_REOPEN_LIMIT_REACHED`, HTTP 422). Reopening increments `reopen_count` by 1, clears `closed_at` to null, sets the engagement's `risk_attention_state` to `UNDER_REVIEW`, and recomputes the vendor's `tier_posture`.

### 3.9. Engagement Exit and Termination for Cause

An `ACTIVE` engagement may be wound down by a `VendorRelationshipManager` via the initiate-exit capability. The engagement must be `ACTIVE` (otherwise `ERR_ENGAGEMENT_NOT_ACTIVE`, HTTP 409) and must have no `OPEN` or `REOPENED` incident with severity `SEV_1` or `SEV_2` (otherwise `ERR_BLOCKING_INCIDENTS_OPEN`, HTTP 422). On initiation the engagement transitions `ACTIVE → EXITING` and the server computes `exit_readiness_score` per the formula below.

The exit readiness score starts at 100 and applies deductions: 50 points if any incident on the engagement is in a non-terminal state (that is, any of `OPEN`, `TRIAGED`, `REMEDIATION_PLANNED`, `REMEDIATION_IN_PROGRESS`, `AWAITING_VERIFICATION`, or `REOPENED`); 20 points if any remediation plan on the engagement's incidents is in `DRAFT`, `SUBMITTED`, `APPROVED`, `IN_EXECUTION`, or `VERIFICATION_SUBMITTED`; 30 points if the contract lacks `has_exit_plan_section` while the vendor is `TIER_1_CRITICAL`; 15 points if any fourth party on the engagement is still in `PENDING`; and 10 points if any monitoring cycle on the vendor is `OVERDUE`. The result is clamped to the range 0 to 100 and stored with two-decimal-place representation.

A `RiskOfficer` finalizes exit once the engagement is `EXITING` (otherwise `ERR_ENGAGEMENT_NOT_EXITING`, HTTP 409), the score is at least 80.00 (otherwise `ERR_EXIT_READINESS_TOO_LOW`, HTTP 422), and no `OPEN` or `REOPENED` incidents remain (otherwise `ERR_OPEN_INCIDENTS_REMAIN`, HTTP 422). Finalization transitions the engagement `EXITING → EXITED` and resets `risk_attention_state` to `NORMAL`.

Termination for cause is an exceptional path. A `RiskOfficer` invokes it on an `ACTIVE` engagement when at least one `OPEN` or `REOPENED` `SEV_1` incident exists; absence of such an incident yields `ERR_NO_SEV1_INCIDENT` (HTTP 422). On termination the engagement transitions `ACTIVE → TERMINATED_FOR_CAUSE`, `risk_attention_state` becomes `REMEDIATION_REQUIRED`, and the engagement's contract is transitioned to `TERMINATED`.

### 3.10. Composite Risk Score and Tier Posture

The composite risk score aggregates incident, monitoring, and business-continuity signals into a single 0–100 number per vendor. Each non-terminal incident on any of the vendor's engagements contributes a severity-weighted amount: `SEV_1` contributes 40, `SEV_2` contributes 20, `SEV_3` contributes 8, and `SEV_4` contributes 3. Each `OVERDUE` monitoring cycle on the vendor contributes 10. Each `FAILED` business-continuity test on any of the vendor's engagements contributes 15. The base sum is multiplied by a tier factor — 1.5 for `TIER_1_CRITICAL`, 1.2 for `TIER_2_HIGH`, 1.0 for `TIER_3_STANDARD`, and 0.8 for `TIER_4_LOW` — and the product is rounded half-up to two decimal places and clamped to the range 0 to 100. Closed incidents contribute zero; reopening an incident immediately re-contributes its severity weight.

The score is recomputed at vendor activation, on every tier change, on every incident `OPEN` / `CLOSED` / `REOPENED` transition, on every monitoring-cycle `OVERDUE` promotion, and on every business-continuity-test `FAILED` transition. Each recompute then derives `tier_posture` by thresholding: a score of at least 70 lands the vendor in `BREACH`; at least 40 but less than 70 lands in `ESCALATED`; at least 15 but less than 40 lands in `WATCH`; anything below 15 lands in `CLEAN`. The boundary is inclusive on the lower end — a score of exactly 15.00 is `WATCH`, while 14.99 is `CLEAN`.

### 3.11. Criticality Tier Changes

A `RiskOfficer` changes a vendor's `criticality_tier` by supplying `to_tier`, a free-text `reason`, and `expected_vendor_version` carrying the officer's last observed `version` of the vendor. A mismatch against the current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the server updates `criticality_tier`, writes a `RiskTierChangeLog` row recording `from_tier`, `to_tier`, `reason`, and `changed_by_user_id`, recomputes `composite_risk_score` (the tier multiplier changed), recomputes `next_monitoring_due_at` from the new cadence anchored to the most recent cycle's `completed_at` (or to vendor activation if no cycles have completed), and increments the vendor's `version` by 1. The change log is readable via the dedicated tier-change-log listing for audit purposes.

### 3.12. Business Continuity Testing

A `RiskOfficer` schedules a `BusinessContinuityTest` on an engagement by supplying `scheduled_for` (must be in the future at create, otherwise `ERR_TEMPORAL_ORDER`), `scenario`, `rto_target_minutes` (at least 1), and `rpo_target_minutes` (at least 0). New tests land in `SCHEDULED`. Beginning a test requires it to be `SCHEDULED` (otherwise `ERR_BCP_NOT_SCHEDULED`, HTTP 409) and the engagement to be `ACTIVE` (otherwise `ERR_ENGAGEMENT_NOT_ACTIVE`, HTTP 409), and moves it to `IN_PROGRESS`. Cancelling requires `SCHEDULED` and moves it to `CANCELLED`.

Submitting a result requires the test to be `IN_PROGRESS` (otherwise `ERR_BCP_NOT_IN_PROGRESS`, HTTP 409) and carries `actual_rto_minutes` and `actual_rpo_minutes` (each at least 0). The `outcome` field is `PASS` when the actual RTO is at most `rto_target_minutes` and the actual RPO is at most `rpo_target_minutes`; otherwise `outcome` is `FAIL`. A `PASS` lands the test in `PASSED`. A `FAIL` lands it in `FAILED`, triggers a `tier_posture` recompute on the vendor, and, when the engagement's vendor is `TIER_1_CRITICAL`, additionally auto-creates an `Incident` of type `OUTAGE` with severity `SEV_2` on the same engagement.

### 3.13. Right-to-Audit Exercises and Findings

An `InternalAuditor` initiates an `AuditExercise` on an engagement by supplying `scope`; the server records the parent engagement on the audit's `engagement_id` field. The auditor must differ from the user recorded as `started_by_user_id` on the engagement, otherwise `ERR_SOD_AUDITOR_IS_CREATOR` (HTTP 403). The engagement must have an `EXECUTED` contract whose `has_right_to_audit_clause` is true; initiating without that clause is rejected with `ERR_AUDIT_NO_RIGHT_TO_AUDIT` (HTTP 422). At most one audit per engagement may be in `INITIATED`, `FIELDWORK`, or `FINDINGS_ISSUED` at any instant — a second concurrent attempt is rejected with `ERR_AUDIT_ALREADY_ACTIVE` (HTTP 422); closed audits do not count toward this capacity. On initiation the audit lands in `INITIATED`, `initiated_at` is stamped by the server, `exercised_by_user_id` is stamped from `X-User-ID`, and `findings_count` starts at 0.

Beginning fieldwork requires `INITIATED` (otherwise `ERR_AUDIT_NOT_INITIATED`, HTTP 409) and moves the audit to `FIELDWORK`. While in `FIELDWORK` the auditor attaches findings via the findings capability, each carrying `severity` and `description`; the server records the parent audit's `id` on each finding's `audit_exercise_id` field, and each attachment increments `findings_count` by 1. Issuing findings requires `FIELDWORK` (otherwise `ERR_AUDIT_NOT_FIELDWORK`, HTTP 409) and transitions the audit to `FINDINGS_ISSUED`. At the moment of issuance the system walks every finding with severity `SEV_1` or `SEV_2` and auto-creates an `Incident` of type `REGULATORY_FINDING` with matching severity on the same engagement, recording the new incident's id in the finding's `raised_incident_id`. Findings of severity `SEV_3` or `SEV_4` do not auto-raise incidents.

Closing the audit requires `FINDINGS_ISSUED` (otherwise `ERR_AUDIT_NOT_FINDINGS_ISSUED`, HTTP 409) and requires every auto-raised incident to be `CLOSED`; any auto-raised incident still in a non-`CLOSED` state blocks the close with `ERR_AUDIT_FINDINGS_UNRESOLVED` (HTTP 422). On close the server stamps `closed_at`.

### 3.14. Concentration Assessment

A `ComplianceDirector` creates a `ConcentrationAssessment` by supplying `assessment_window_start`, `assessment_window_end` (must be strictly later than the start, otherwise `ERR_TEMPORAL_ORDER`), and `grouping_dimension`. New assessments land in `COMPUTING`.

Publishing the assessment (requires `COMPUTING`, otherwise `ERR_ASSESSMENT_NOT_COMPUTING`, HTTP 409) triggers the share computation across all `ACTIVE` engagements whose vendor is not archived. For `grouping_dimension` equal to `REGION`, each engagement is bucketed by its vendor's `headquarters_region`; for `SERVICE_CATEGORY`, by its vendor's `service_category`. Each bucket's `total_spend_cents` is the sum of `annual_spend_cents` over the engagements in that bucket. Each bucket's `share_pct` is the bucket's spend divided by the grand total spend across all active engagements, multiplied by 100, then rounded half-up to two decimal places; if the grand total is zero, every bucket's `share_pct` is 0.00. A bucket is flagged `is_breach` when its rounded `share_pct` is at least 25.00; the comparison uses the rounded value, so a true share of 24.996 becomes 25.00 after rounding and therefore is a breach, while 24.99 is not. Each bucket row records the parent assessment's `id` on its `assessment_id` field. The assessment's `breach_bucket_keys` collects the `bucket_key` of every bucket with `is_breach` true. For any downstream iteration, buckets are sorted by `share_pct` descending, with ties broken by `bucket_key` ascending in string order. Publishing stamps `computed_at` and `published_by_user_id`, and transitions the assessment `COMPUTING → PUBLISHED`. When a newer assessment on the same `grouping_dimension` reaches `PUBLISHED`, the older one transitions to `SUPERSEDED`.

### 3.15. Board Reporting

A `ComplianceDirector` drafts a `BoardReport` by supplying `period_start` and `period_end` (the end must be strictly later than the start, otherwise `ERR_TEMPORAL_ORDER`). The new draft's reporting window is half-open on the right — incidents detected exactly at `period_start` are included; those detected exactly at `period_end` are not. The window must not overlap the window of any `PUBLISHED` board report; touching at a boundary (this draft's `period_start` equal to another report's `period_end`) is permitted, but any other overlap is rejected with `ERR_REPORT_WINDOW_OVERLAP` (HTTP 422). New reports land in `DRAFT`.

Publishing a report (requires `DRAFT`, otherwise `ERR_REPORT_NOT_DRAFT`, HTTP 409) computes `snapshot_payload` aggregating the following indicators: `vendor_count_by_tier` counting non-archived vendors grouped by `criticality_tier`; `vendor_count_by_posture` counting vendors grouped by `tier_posture`; `engagement_count_by_lifecycle` counting engagements grouped by `lifecycle_status`; `incidents_opened_in_window` counting incidents whose `detected_at` falls within the window; `incidents_closed_in_window` counting incidents whose `closed_at` is non-null and falls within the window; `overdue_monitoring_cycles_at_publish` counting cycles in `OVERDUE` at the publish instant; `concentration_breaches_active` summing, for each `grouping_dimension`, the number of breach buckets on the latest `PUBLISHED` assessment for that dimension (zero when none has been published); `bcp_failures_in_window` counting business-continuity tests whose status is `FAILED` and whose completion or last-update instant falls within the window; and `composite_risk_score_distribution` bucketing vendor `composite_risk_score` values into the histogram intervals [0, 15), [15, 40), [40, 70), and [70, 100]. All counts are integers; no rounding is applied. Publishing stamps `published_at` and `published_by_user_id` and transitions the report `DRAFT → PUBLISHED`. A published report is immutable.

### 3.16. Validation Ordering Across a Request

When multiple validation rules could fire on the same request, the server applies them in a fixed priority order so that the most foundational problem is reported first. Authentication (`ERR_UNAUTHENTICATED`) runs before authorization (`ERR_UNAUTHORIZED`), which runs before path resolution (`ERR_NOT_FOUND`), which runs before state-machine preconditions (`ERR_INVALID_STATE` and the more specific state errors), which run before segregation-of-duties checks (`ERR_SOD_*`), which run before blocking-incident gates, which run before contract-clause completeness, which run before fourth-party acknowledgement gates, which run before due-diligence outcome gates, which run before temporal-ordering rules, which run before fiscal and tier-specific business constraints (exit readiness, waive tier, fourth-party PII tier), which run before referential checks on fourth-party parent links, which run before review-round and reopen caps, which run before capacity rules (cycle window overlap, concurrent audit, board-report window overlap), which run before OCC stale-version checks, which run before uniqueness checks (`ERR_DUPLICATE_KEY`), which run before generic payload validation (`ERR_INVALID_REQUEST`).

## 4. Endpoint Definitions

Status code conventions: endpoints that create a new resource return 201; endpoints that modify an existing resource or trigger a state transition return 200; list and fetch endpoints return 200. Error responses carry the codes listed in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/tprm/vendors` | Create a vendor in `ONBOARDING` with initial tier `TIER_3_STANDARD`. | VendorRelationshipManager |
| GET | `/tprm/vendors` | List vendors with optional filters. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| GET | `/tprm/vendors/{id}` | Fetch a single vendor. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| POST | `/tprm/vendors/{id}/activate` | Transition vendor `ONBOARDING → ACTIVE`. | RiskOfficer |
| POST | `/tprm/vendors/{id}/suspend` | Transition vendor `ACTIVE → SUSPENDED`. | RiskOfficer |
| POST | `/tprm/vendors/{id}/reinstate` | Transition vendor `SUSPENDED → ACTIVE`. | RiskOfficer |
| POST | `/tprm/vendors/{id}/exit` | Transition vendor `ACTIVE → EXITED` (soft-archive). | RiskOfficer |
| POST | `/tprm/vendors/{id}/tier-change` | Change the vendor's `criticality_tier`; OCC-guarded. | RiskOfficer |
| GET | `/tprm/vendors/{id}/tier-change-log` | List tier-change audit rows for a vendor. | RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/vendors/{id}/engagements` | Create an engagement on a vendor. | VendorRelationshipManager |
| GET | `/tprm/vendors/{id}/engagements` | List engagements for a vendor. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| GET | `/tprm/engagements/{id}` | Fetch a single engagement. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| POST | `/tprm/engagements/{id}/initiate-exit` | Transition engagement `ACTIVE → EXITING`; computes `exit_readiness_score`. | VendorRelationshipManager |
| POST | `/tprm/engagements/{id}/finalize-exit` | Transition engagement `EXITING → EXITED`. | RiskOfficer |
| POST | `/tprm/engagements/{id}/terminate-for-cause` | Transition engagement `ACTIVE → TERMINATED_FOR_CAUSE`. | RiskOfficer |
| POST | `/tprm/engagements/{id}/due-diligence-packages` | Create a DD package; transitions engagement `DRAFT → DD_IN_PROGRESS`. | VendorRelationshipManager |
| GET | `/tprm/engagements/{id}/due-diligence-packages` | List DD packages on an engagement. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/due-diligence-packages/{id}` | Fetch a DD package. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/due-diligence-packages/{id}/submit` | Transition package `DRAFT → SUBMITTED`; computes aggregate score and outcome. | VendorRelationshipManager |
| POST | `/tprm/due-diligence-packages/{id}/begin-review` | Transition package `SUBMITTED → UNDER_REVIEW`. | RiskOfficer |
| POST | `/tprm/due-diligence-packages/{id}/approve` | Transition package `UNDER_REVIEW → APPROVED`; SoD and OCC guarded. | RiskOfficer |
| POST | `/tprm/due-diligence-packages/{id}/reject` | Transition package `UNDER_REVIEW → REJECTED`. | RiskOfficer |
| POST | `/tprm/due-diligence-packages/{id}/resubmit` | Transition package `REJECTED → SUBMITTED`; review-round cap 3. | VendorRelationshipManager |
| POST | `/tprm/engagements/{id}/contracts` | Create a contract; transitions engagement `DD_APPROVED → CONTRACTING`. | VendorRelationshipManager |
| GET | `/tprm/engagements/{id}/contracts` | List contracts on an engagement. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/contracts` | Filtered list of contracts across engagements. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/contracts/{id}` | Fetch a contract. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/contracts/{id}/execute` | Transition contract `DRAFT → EXECUTED`; cascades engagement `CONTRACTING → ACTIVE`; OCC-guarded. | RiskOfficer |
| POST | `/tprm/engagements/{id}/fourth-parties` | Declare a subcontractor on an engagement. | VendorRelationshipManager |
| GET | `/tprm/engagements/{id}/fourth-parties` | List fourth parties on an engagement. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/fourth-parties` | Filtered list of fourth parties across engagements. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/fourth-parties/{id}` | Fetch a fourth party. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/fourth-parties/{id}/acknowledge` | Transition fourth party `PENDING → ACKNOWLEDGED`; tier-gated for `REGULATED_PII`. | RiskOfficer |
| POST | `/tprm/fourth-parties/{id}/reject` | Transition fourth party `PENDING → REJECTED`. | RiskOfficer |
| GET | `/tprm/vendors/{id}/monitoring-cycles` | List monitoring cycles for a vendor. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/monitoring-cycles/{id}` | Fetch a monitoring cycle. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/monitoring-cycles/{id}/begin` | Transition cycle `SCHEDULED → IN_PROGRESS`. | RiskOfficer |
| POST | `/tprm/monitoring-cycles/{id}/complete` | Transition cycle `IN_PROGRESS → COMPLETED_ON_TIME` or `COMPLETED_LATE`. | RiskOfficer |
| POST | `/tprm/monitoring-cycles/{id}/waive` | Transition cycle `SCHEDULED → WAIVED`; only for `TIER_4_LOW` vendors. | ComplianceDirector |
| POST | `/tprm/engagements/{id}/incidents` | File an incident on an engagement. | BusinessUnitOwner |
| GET | `/tprm/engagements/{id}/incidents` | List incidents on an engagement. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| GET | `/tprm/incidents/{id}` | Fetch an incident. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| POST | `/tprm/incidents/{id}/triage` | Transition incident `OPEN → TRIAGED`; computes `remediation_due_at`. | RiskOfficer |
| POST | `/tprm/incidents/{id}/reopen` | Transition incident `CLOSED → REOPENED`; cap 2. | BusinessUnitOwner |
| POST | `/tprm/incidents/{id}/remediation-plans` | Draft a remediation plan; transitions incident `TRIAGED → REMEDIATION_PLANNED`. | RiskOfficer |
| GET | `/tprm/incidents/{id}/remediation-plans` | List plans on an incident. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| GET | `/tprm/remediation-plans/{id}` | Fetch a plan. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor, BusinessUnitOwner |
| POST | `/tprm/remediation-plans/{id}/submit` | Transition plan `DRAFT → SUBMITTED`. | RiskOfficer |
| POST | `/tprm/remediation-plans/{id}/approve` | Transition plan `SUBMITTED → APPROVED → IN_EXECUTION`; cascades incident. | RiskOfficer |
| POST | `/tprm/remediation-plans/{id}/reject` | Transition plan `SUBMITTED → REJECTED`; incident reverts to `TRIAGED`. | RiskOfficer |
| POST | `/tprm/remediation-plans/{id}/submit-verification` | Transition plan `IN_EXECUTION → VERIFICATION_SUBMITTED`. | RiskOfficer |
| POST | `/tprm/remediation-plans/{id}/verify` | Transition plan `VERIFICATION_SUBMITTED → VERIFIED`; incident closes. | BusinessUnitOwner |
| POST | `/tprm/concentration-assessments` | Create a `ConcentrationAssessment` in `COMPUTING`. | ComplianceDirector |
| GET | `/tprm/concentration-assessments` | List assessments. | RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/concentration-assessments/{id}` | Fetch one assessment. | RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/concentration-assessments/{id}/publish` | Transition assessment `COMPUTING → PUBLISHED`; computes buckets. | ComplianceDirector |
| GET | `/tprm/concentration-assessments/{id}/buckets` | List concentration buckets for an assessment. | RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/engagements/{id}/bcp-tests` | Schedule a business-continuity test on an engagement. | RiskOfficer |
| GET | `/tprm/engagements/{id}/bcp-tests` | List BCP tests on an engagement. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/bcp-tests/{id}` | Fetch a BCP test. | VendorRelationshipManager, RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/bcp-tests/{id}/begin` | Transition test `SCHEDULED → IN_PROGRESS`. | RiskOfficer |
| POST | `/tprm/bcp-tests/{id}/submit-result` | Transition test `IN_PROGRESS → PASSED` or `FAILED` based on actual vs target. | RiskOfficer |
| POST | `/tprm/bcp-tests/{id}/cancel` | Transition test `SCHEDULED → CANCELLED`. | RiskOfficer |
| POST | `/tprm/engagements/{id}/audits` | Initiate a right-to-audit exercise on an engagement. | InternalAuditor |
| GET | `/tprm/engagements/{id}/audits` | List audits on an engagement. | RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/audits/{id}` | Fetch an audit exercise. | RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/audits/{id}/begin-fieldwork` | Transition audit `INITIATED → FIELDWORK`. | InternalAuditor |
| POST | `/tprm/audits/{id}/findings` | Attach a finding to a `FIELDWORK` audit. | InternalAuditor |
| GET | `/tprm/audits/{id}/findings` | List findings on an audit. | RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/audit-findings` | Filtered list of audit findings. | RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/audit-findings/{id}` | Fetch a single audit finding. | RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/audits/{id}/issue-findings` | Transition audit `FIELDWORK → FINDINGS_ISSUED`; auto-raises incidents for high-severity findings. | InternalAuditor |
| POST | `/tprm/audits/{id}/close` | Transition audit `FINDINGS_ISSUED → CLOSED`; requires auto-raised incidents closed. | InternalAuditor |
| POST | `/tprm/board-reports` | Create a board report draft for a reporting window. | ComplianceDirector |
| GET | `/tprm/board-reports` | List board reports. | RiskOfficer, ComplianceDirector, InternalAuditor |
| GET | `/tprm/board-reports/{id}` | Fetch a board report. | RiskOfficer, ComplianceDirector, InternalAuditor |
| POST | `/tprm/board-reports/{id}/publish` | Transition report `DRAFT → PUBLISHED`; computes `snapshot_payload`. | ComplianceDirector |
| POST | `/tprm/_clock/set_current_utc` | Advance the logical clock; triggers time-driven promotions. | PlatformAdmin |
| GET | `/tprm/_clock/current_utc` | Read the logical clock. | PlatformAdmin, RiskOfficer, ComplianceDirector, VendorRelationshipManager, InternalAuditor, BusinessUnitOwner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VENDOR_NOT_ONBOARDING` | 409 |
| `ERR_VENDOR_NOT_ACTIVE` | 409 |
| `ERR_VENDOR_NOT_SUSPENDED` | 409 |
| `ERR_NO_ACTIVE_ENGAGEMENT` | 422 |
| `ERR_OPEN_SEV1_INCIDENT` | 422 |
| `ERR_ENGAGEMENTS_NOT_EXITED` | 422 |
| `ERR_OPEN_INCIDENTS_REMAIN` | 422 |
| `ERR_BLOCKING_INCIDENTS_OPEN` | 422 |
| `ERR_ENGAGEMENT_NOT_DRAFT` | 409 |
| `ERR_DD_NOT_APPROVED` | 409 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_ENGAGEMENT_NOT_EXITING` | 409 |
| `ERR_NO_SEV1_INCIDENT` | 422 |
| `ERR_EXIT_READINESS_TOO_LOW` | 422 |
| `ERR_DD_NOT_DRAFT` | 409 |
| `ERR_DD_NOT_SUBMITTED` | 409 |
| `ERR_DD_NOT_UNDER_REVIEW` | 409 |
| `ERR_DD_NOT_REJECTED` | 409 |
| `ERR_DD_OUTCOME_FAIL` | 422 |
| `ERR_DD_REVIEW_ROUND_EXHAUSTED` | 422 |
| `ERR_CONTRACT_NOT_DRAFT` | 409 |
| `ERR_CONTRACT_CLAUSES_INCOMPLETE` | 422 |
| `ERR_MISSING_SLA_TERMS` | 422 |
| `ERR_MISSING_AUDIT_CLAUSE` | 422 |
| `ERR_MISSING_EXIT_PLAN` | 422 |
| `ERR_FOURTH_PARTY_PENDING` | 422 |
| `ERR_FP_NOT_PENDING` | 409 |
| `ERR_FP_PII_TIER_TOO_LOW` | 422 |
| `ERR_FP_PARENT_INVALID` | 422 |
| `ERR_CYCLE_NOT_SCHEDULED` | 409 |
| `ERR_CYCLE_NOT_IN_PROGRESS` | 409 |
| `ERR_WAIVE_TIER_FORBIDDEN` | 422 |
| `ERR_INCIDENT_NOT_OPEN` | 409 |
| `ERR_INCIDENT_NOT_TRIAGED` | 409 |
| `ERR_INCIDENT_NOT_CLOSED` | 409 |
| `ERR_REOPEN_LIMIT_REACHED` | 422 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_SUBMITTED` | 409 |
| `ERR_PLAN_NOT_IN_EXECUTION` | 409 |
| `ERR_PLAN_NOT_VERIFICATION_SUBMITTED` | 409 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_SOD_DD_SELF_APPROVE` | 403 |
| `ERR_SOD_INCIDENT_SELF_REMEDIATE` | 403 |
| `ERR_SOD_PLAN_SELF_APPROVE` | 403 |
| `ERR_SOD_VERIFY_NOT_REPORTER` | 403 |
| `ERR_SOD_REOPEN_NOT_REPORTER` | 403 |
| `ERR_SOD_AUDITOR_IS_CREATOR` | 403 |
| `ERR_ASSESSMENT_NOT_COMPUTING` | 409 |
| `ERR_AUDIT_FINDINGS_UNRESOLVED` | 422 |
| `ERR_AUDIT_NOT_INITIATED` | 409 |
| `ERR_AUDIT_NOT_FIELDWORK` | 409 |
| `ERR_AUDIT_NOT_FINDINGS_ISSUED` | 409 |
| `ERR_AUDIT_NO_RIGHT_TO_AUDIT` | 422 |
| `ERR_BCP_NOT_SCHEDULED` | 409 |
| `ERR_BCP_NOT_IN_PROGRESS` | 409 |
| `ERR_REPORT_NOT_DRAFT` | 409 |
| `ERR_TEMPORAL_ORDER` | 422 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 422 |
| `ERR_AUDIT_ALREADY_ACTIVE` | 422 |
| `ERR_REPORT_WINDOW_OVERLAP` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_STALE_VERSION` | 412 |
