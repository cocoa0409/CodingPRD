# Data Breach Incident Response API — Product Requirements Document

## 1. Introduction

When a corporate data breach is suspected, the difference between a defensible response and a regulatory fiasco is almost never a question of whether the security team acted — it is whether every action was sequenced, timestamped, attributable, and auditable. Forensic leads need to baseline investigative scope before affected subjects can be enumerated. Privacy counsel needs to know — per jurisdiction, with statutory deadlines ticking — whether notification thresholds have been crossed, and to draft, approve, lock, and mail consumer notices without ever losing the chain of custody. General Counsel must approve consumer-facing language without ever being the same person who drafted it. And through it all, a regulator may open an inquiry at any moment and demand a coherent narrative on pain of penalty.

This document describes a REST API that orchestrates the entire data breach notification and incident response lifecycle for a corporate incident response team: intake and severity classification, forensic scoping and evidence preservation, affected-record determination and per-jurisdiction obligation evaluation, notice drafting and approval, mailing-vendor coordination, credit-monitoring offers and call-center staffing, regulator submissions and inquiry handling, and post-incident remediation through closure. The API is designed for a segregated-duties operating model — IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, AffectedSubjectRole, and Auditor — in which no single actor can both author and approve a notice, or own and verify a remediation step, or submit to and respond to a regulator.

Two principles shape the design. First, the `Incident` row carries two parallel state dimensions — `investigation_status` and `notification_status` — that evolve independently and must both reach a terminal or idle posture before the incident can close; this mirrors how real response teams run forensics and consumer notification as separate workstreams that converge only at the end. Second, every derived counter on the incident (affected subjects, notified subjects, pending subjects, credit-monitoring uptake, jurisdiction-level subject counts, risk scores) is recomputed eagerly at the moment its inputs change, so that any read of the incident reflects a consistent snapshot of the response as of that `version`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to invoke the requested endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The seven declared role names are spelled exactly as follows:

- `IncidentCommander` — owns the incident lifecycle (create, confirm, contain, close) and remediation actions; also drives the test-only logical clock.
- `ForensicLead` — owns forensic scope, evidence, and chain-of-custody records.
- `PrivacyCounsel` — drafts notices, coordinates the mailing vendor, submits to regulators, and manages credit-monitoring offers.
- `GeneralCounsel` — approves notices, requests changes, verifies remediation, responds to regulator inquiries.
- `DataAnalyst` — determines and verifies affected subjects.
- `AffectedSubjectRole` — the data subject themselves; can redeem or decline a credit-monitoring offer addressed to them.
- `Auditor` — read-only access across all resources for compliance review.

**Identity semantics.** When `X-User-Role` is `IncidentCommander`, `ForensicLead`, `PrivacyCounsel`, `GeneralCounsel`, `DataAnalyst`, or `Auditor`, the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `collected_by_user_id` on `EvidenceItem`, `owner_user_id` on `RemediationAction`, or `approved_by_user_id` on `Notice` — but does not compare it to any entity's `id`. When `X-User-Role` is `AffectedSubjectRole`, `X-User-ID` is the `id` of the acting `AffectedSubject`; ownership checks on any resource that references an `AffectedSubject` (specifically, redemption or decline of a `CreditMonitoringOffer`) compare the resource's `affected_subject_id` foreign key to `X-User-ID`, and list access for this role is filtered to the caller's own rows.

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

All list endpoints accept two query parameters: `limit` and `offset`. The default value of `limit` is 10, the minimum accepted value is 1, and the maximum accepted value is 100. The default value of `offset` is 0. List responses order results by `created_at` ascending. The `meta` object on every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional rows exist beyond the returned window.

### 2.4. Common Resource Properties and Versioning

Every resource in this system carries an `id` field, which is a server-minted UUID (without any type prefix), and a `created_at` field, which is an ISO 8601 UTC timestamp with three fractional digits. With one exception, every entity also carries `updated_at` (also an ISO 8601 UTC timestamp with three fractional digits) and an integer `version` that starts at 1 at creation and increments by exactly 1 every time the row is mutated. The exception is `EvidenceCustodyLog`: custody records are an append-only audit trail and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent on custody rows.

Any transition, side effect, or derived-field recompute that mutates an entity also refreshes that entity's `updated_at`. Because virtually every workflow step in this domain touches the parent `Incident` row, the incident's `version` is the primary optimistic-concurrency anchor: it advances on every state transition, every scope baseline or amendment, every evidence seal, every affected-subject add, verify, or exclude, every notice or mailing-batch creation, and so on. Clients that read an incident and later write against it are expected to carry the incident `version` they observed back into the write — see §2.6.

### 2.5. Hierarchical Addressing and Left-to-Right Resolution

Almost every resource in this domain hangs off an `Incident`, and the URL hierarchy reflects that: paths such as `/incidents/{incidentId}/forensic-scopes/{scopeId}/baseline` first resolve `incidentId`, then resolve `scopeId` within that incident, then execute the action. Resolution is strict left-to-right. If any path-template id fails to resolve to an existing row in scope — `incidentId`, `scopeId`, `itemId`, `subjectId`, `noticeId`, `batchId`, `offerId`, `planId`, `subId`, `actionId`, `jurisdictionEvaluationId`, or `evaluationId` — the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later check runs. The same `ERR_NOT_FOUND` also applies to foreign keys carried in the request body — `jurisdiction_evaluation_id`, `notice_id`, `supersedes_notice_id`, `evidence_item_id`, `affected_subject_id` — which must resolve to existing rows inside the same incident. Every child row carries a system-stamped `incident_id` foreign key tying it back to its parent, and every stateful row carries a `status` field tracking the row through its lifecycle. In addition to the nested forms, a set of flat read-only list endpoints (e.g., `/notices`, `/mailing-batches`, `/credit-monitoring-offers`, `/regulator-submissions`, `/jurisdiction-evaluations`, `/affected-subjects`, `/evidence-items`, `/forensic-scopes`, `/remediation-actions`, `/call-center-staffing-plans`, `/custody-logs`) supports cross-incident filtering by the relevant foreign key.

### 2.6. Optimistic Concurrency Control on the Incident

Two write endpoints take an optimistic-concurrency input that anchors the write to the incident row's current `version`:

- Creating a notice requires a non-optional `expected_incident_version` field in the request body, carrying the incident `version` the client last observed. If the incident's current `version` does not match, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another writer has just amended the forensic scope or advanced `notification_status` since the drafter's read, so the drafter's context is stale.
- Creating a mailing batch also requires a non-optional `expected_incident_version`. A mismatch with the incident's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of `recipient_count` and `notification_status` may no longer reflect actual incident state.

Endpoints not listed above do not accept a version field. The stale-version rejection is purely an optimistic-concurrency guarantee; it is not a locking protocol and does not depend on two requests arriving at the same time.

### 2.7. Validation Order and Priority

When multiple validation rules apply to the same endpoint, they are evaluated in a fixed priority order so that the error code returned to the caller is deterministic. The order is:

1. **Authentication** — `X-User-Role` header present and one of the declared role names; `X-User-ID` header present and non-empty. Violation: `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — role is permitted to invoke the endpoint. Violation: `ERR_FORBIDDEN` (403).
3. **Path-id existence** — every path-template id resolves, validated left-to-right. Violation: `ERR_NOT_FOUND` (404).
4. **Body foreign-key existence** — `jurisdiction_evaluation_id`, `notice_id`, `supersedes_notice_id`, and similar body FKs resolve inside the same incident. Violation: `ERR_NOT_FOUND` (404).
5. **Local state precondition** — target entity is in a state from which the requested transition is allowed. Violation: `ERR_INVALID_STATE` (409).
6. **Cross-entity state precondition** — incident-level parallel-state preconditions (e.g., notice approval requires `investigation_status` to be `CONFIRMED`; mailing-batch start-production requires `notification_status` to be `DISPATCHING`). Violation: `ERR_INVALID_STATE` (409).
7. **Chain-of-custody integrity** — evidence seal requires a `preservation_hash` matching the 64-character lowercase hex format; custody log creation requires no overlapping half-open interval for the same `evidence_item_id`. Violation: `ERR_CUSTODY_OVERLAP` (409).
8. **Segregation of duties** — notice approval requires the acting `GeneralCounsel` `X-User-ID` to differ from the `PrivacyCounsel` `X-User-ID` who drafted the notice; remediation verification requires the acting `GeneralCounsel` `X-User-ID` to differ from the action's `owner_user_id`; regulator-inquiry response requires the acting `GeneralCounsel` `X-User-ID` to differ from the submission's original submitter. Violation: `ERR_SEGREGATION_OF_DUTIES` (409).
9. **Statutory and temporal preconditions** — notice approval requires the linked jurisdiction's `deadline_at` to be strictly in the future; marking a batch shipped requires `scheduled_ship_date` to be at or before the current time; redeeming a credit-monitoring offer requires `expires_at` to be strictly in the future. Violation: `ERR_DEADLINE_PASSED` (409).
10. **Data-element scope consistency** — an affected subject's `data_elements_exposed` must be a subset of the current forensic scope's `data_elements_at_risk` whenever the scope has reached `BASELINED`, `AMENDED`, or `FINAL`. Violation: `ERR_DATA_ELEMENT_OUT_OF_SCOPE` (422).
11. **Notice supersession acyclicity** — a new notice's `supersedes_notice_id` must not form a cycle back to the notice being created. Violation: `ERR_SUPERSESSION_CYCLE` (422).
12. **Staffing-plan interval integrity** — a new `CallCenterStaffingPlan` must have `effective_from` strictly earlier than `effective_until`, and its effective interval must not partially overlap any other `ACTIVE` plan for the same incident under half-open interval semantics `[effective_from, effective_until)`; touching edges are permitted. Violation: `ERR_STAFFING_PLAN_OVERLAP` (409).
13. **Subject uniqueness** — an `external_subject_ref` must be unique per incident among affected-subject rows whose status is not `EXCLUDED`. Violation: `ERR_DUPLICATE_SUBJECT` (409).
14. **Single active offer** — at most one `ISSUED` credit-monitoring offer may exist per `affected_subject_id` at any time. Violation: `ERR_OFFER_ALREADY_ACTIVE` (409).
15. **Staffing-plan floor** — the computed `seats_required` must be at least 2 (a defensive floor). Violation: `ERR_INVALID_REQUEST` (422).
16. **Offer economic shape** — `term_months` must be either 12 or 24, and `unit_cost_cents` must be greater than zero. Violation: `ERR_INVALID_REQUEST` (422).
17. **Optimistic concurrency** — `expected_incident_version` must equal the incident's current `version` on the two endpoints that take it. Violation: `ERR_STALE_VERSION` (412).

A request that fails more than one of these checks receives the error from the earliest check in the order above.

### 2.8. Precision, Rounding, and Time Conventions

All timestamps are ISO 8601 UTC at millisecond precision. Date-of-deadline computations pin the result to `23:59:59.999Z` of the final day. All integer money amounts are expressed in cents; rounding of per-offer cost is round-half-up to integer cents and is applied per-offer before any aggregation across offers — never after. Risk scores are integers in the range 0 to 100; rounding is round-half-up and is applied only as the last step of each variant's computation, never on intermediate values. Seat counts are integers; the severity-multiplier step rounds half-up to an integer seat count. The server's logical clock is settable via a privileged endpoint (see §4); before any such call the logical clock starts at exactly `2026-05-01T00:00:00Z` and must not fall back to wall-clock time.

### 2.9. Derived Counters and Reconciliation

The `Incident` row carries a family of derived counters that are recomputed eagerly whenever their inputs change, and that readers may rely on as an internally consistent snapshot at a given `version`:

- `total_affected_subjects` is the count of `AffectedSubject` rows whose status is `IDENTIFIED` or `VERIFIED`.
- `total_notified_subjects` is the count of `AffectedSubject` rows whose status is `NOTIFIED`.
- `total_pending_subjects` is the count of `AffectedSubject` rows whose status is `IDENTIFIED`, `VERIFIED`, or `NOTICE_QUEUED`.
- `credit_monitoring_offered` is the count of `AffectedSubject` rows whose `credit_monitoring_status` is anything other than `NOT_OFFERED`.
- `credit_monitoring_enrolled` is the count of `AffectedSubject` rows whose `credit_monitoring_status` is `ENROLLED`.
- `credit_monitoring_declined` is the count of `AffectedSubject` rows whose `credit_monitoring_status` is `DECLINED`.
- On each `JurisdictionEvaluation`, `subjects_in_jurisdiction` is the count of `AffectedSubject` rows whose `residence_state_code` equals the evaluation's `state_code` and whose status is `IDENTIFIED`, `VERIFIED`, `NOTICE_QUEUED`, or `NOTIFIED` — `EXCLUDED` rows never count. `notification_required` is true exactly when `subjects_in_jurisdiction` is at least `record_count_threshold`; the comparison is inclusive at the boundary, so exactly-at-threshold triggers notification.
- On each `MailingBatch`, `recipient_count` is the number of `AffectedSubject` rows that this batch transitioned into `NOTICE_QUEUED`.

Every recompute event also increments the incident's `version` and refreshes its `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Incident Intake and Severity Classification

An `IncidentCommander` opens a new breach incident by supplying a `title`, the `discovered_at` timestamp at which the breach came to the team's attention, a best-estimate `occurred_at` timestamp for when the breach actually happened (which may be later than `discovered_at` in forensic-anomaly cases), and the `source_channel` through which the team learned of the incident — one of `INTERNAL_DETECTION`, `THIRD_PARTY_REPORT`, `LAW_ENFORCEMENT`, `CUSTOMER_COMPLAINT`, or `AUDIT`. The new incident is initialized with `investigation_status` set to `INTAKE`, `notification_status` set to `NOT_REQUIRED`, `severity` set to `UNCLASSIFIED`, `remediation_status` set to `NOT_STARTED`, all derived counters set to zero, and `version` set to 1. Severity itself remains `UNCLASSIFIED` until the risk scoring described in §3.3 has been computed — the `severity` field is updated as part of that computation, taking one of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL` based on the resulting scores.

### 3.2. Forensic Scoping, Evidence, and Chain of Custody

Once an incident is open, either the `IncidentCommander` or a `ForensicLead` may create the first `ForensicScope` by providing a `scope_statement`, a non-empty `systems_in_scope` array (for example `['CRM','EMAIL','HR_DB']`), a non-empty `data_elements_at_risk` array drawn from the PII category enumeration `NAME`, `SSN`, `DOB`, `EMAIL`, `PHONE`, `ADDRESS`, `DRIVER_LICENSE`, `PASSPORT`, `FINANCIAL_ACCOUNT`, `HEALTH_RECORD`, `BIOMETRIC`, `CREDENTIALS`, and an `exfiltration_likelihood_pct` between 0 and 100 representing the probability that data was actually exfiltrated. The first scope creation advances the incident's `investigation_status` from `INTAKE` to `SCOPED`, recomputes both risk score variants, and increments the incident's `version`. The new scope is created in `DRAFT` status.

While the scope is `DRAFT`, a `ForensicLead` may baseline it, provided `systems_in_scope` and `data_elements_at_risk` are both non-empty; baselining moves the scope from `DRAFT` to `BASELINED` and advances the incident from `SCOPED` to `INVESTIGATING`. From `BASELINED`, a `ForensicLead` may amend the scope — optionally updating any of `scope_statement`, `systems_in_scope`, `data_elements_at_risk`, or `exfiltration_likelihood_pct` — which moves the scope to `AMENDED`, recomputes both risk score variants, and increments the incident's `version`. Amendment is only permitted while the incident is in `INVESTIGATING`. An amended scope may be re-baselined back to `BASELINED` at any time, again advancing the incident's `version`. Once the incident has reached `CONFIRMED` or `CONTAINED`, the scope may be finalized from `BASELINED` to `FINAL`, which is the scope's terminal state; finalization also increments the incident's `version`.

Evidence handling runs in parallel. A `ForensicLead` registers an `EvidenceItem` against the incident with a `label` (for example `firewall-log-2026-05-01.gz`), an `evidence_type` chosen from `LOG`, `DISK_IMAGE`, `MEMORY_DUMP`, `EMAIL`, `NETWORK_PCAP`, `DOCUMENT`, or `PHOTO`, the `collected_at` timestamp, the collecting responder's `collected_by_user_id`, and a `preservation_hash`. The item starts in `COLLECTED` status and the incident's `version` increments. Sealing the item requires the `preservation_hash` to be present and well-formed as 64 lowercase hexadecimal characters, and requires that no `EvidenceCustodyLog` row already exists for this item on the half-open interval from seal time forward — a violation surfaces as `ERR_CUSTODY_OVERLAP` (409). A successful seal moves the item from `COLLECTED` to `SEALED` and increments the incident's `version`. Once the incident is `CONFIRMED` or `CONTAINED`, a `SEALED` item may be released, moving it to `RELEASED` and again incrementing the incident's `version`. After the incident is `CLOSED`, a `SEALED` item may be destroyed, moving it to `DESTROYED`; destruction does not advance the incident's `version`. The `preservation_hash` is immutable once the item is `SEALED`.

Every custody handoff is recorded by a `ForensicLead` as an `EvidenceCustodyLog` row carrying the `evidence_item_id` being handed off, the `custodian_user_id` of the responder holding custody, the `start_at` timestamp (inclusive), an optional `end_at` timestamp (exclusive — `null` while custody remains open), and a free-text `purpose`. Custody intervals are half-open `[start_at, end_at)`, so an existing interval may not be overlapped by a new one for the same `evidence_item_id`; an overlap is rejected with `ERR_CUSTODY_OVERLAP` (409). Custody rows are append-only: they carry `id` and `created_at` but no `updated_at` and no `version`.

### 3.3. Risk Scoring

Both risk scores on the incident are recomputed from the latest forensic scope — that is, the scope with the latest `updated_at` among those in `BASELINED`, `AMENDED`, or `FINAL` — together with the current set of non-`EXCLUDED` affected subjects. Recompute is triggered by scope baseline, scope amendment, affected-subject add, verify, or exclude, and by the incident's transition into `CONFIRMED`.

The base score is built from the scope's `data_elements_at_risk` by summing per-element weights: `SSN` contributes 20, `DRIVER_LICENSE` 15, `PASSPORT` 15, `FINANCIAL_ACCOUNT` 18, `HEALTH_RECORD` 18, `BIOMETRIC` 20, `CREDENTIALS` 15, `DOB` 8, `NAME` 2, `EMAIL` 3, `PHONE` 3, and `ADDRESS` 4. The sum is then multiplied by a channel multiplier determined by the incident's `source_channel`: `LAW_ENFORCEMENT` multiplies by 1.2, `THIRD_PARTY_REPORT` multiplies by 1.1, and every other channel multiplies by 1.0. To this product is added a volume bonus equal to the smaller of 20 and the integer floor of `total_affected_subjects` divided by 500. The result of these three steps — sum of element weights, multiply by channel multiplier, add volume bonus — is the base score, which is not rounded at any intermediate step.

The conservative variant, stored in `risk_score_conservative`, is the base score rounded half-up to an integer, capped at 100. The likelihood-adjusted variant, stored in `risk_score_likelihood_adjusted`, first multiplies the unrounded base score by `exfiltration_likelihood_pct` divided by 100, then rounds half-up, then caps at 100. Because the likelihood-adjusted variant applies the exfiltration probability before rounding, the same inputs produce a strictly lower score whenever `exfiltration_likelihood_pct` is below 100. Rounding is the last step in each variant.

### 3.4. Affected-Subject Determination

A `DataAnalyst` adds an `AffectedSubject` to the incident by providing the `external_subject_ref` (a stable external identifier such as a CRM customer number), the subject's `full_name`, the `residence_state_code` (a US state or territory code such as `CA`, `NY`, or `TX`, or the literal `NON_US` for non-US subjects), the `data_elements_exposed` array for this subject, and the `record_count` of exposed records belonging to this subject. New subjects are created in `IDENTIFIED` status with `credit_monitoring_status` set to `NOT_OFFERED` and `offered_at` null. The `external_subject_ref` must be unique per incident among non-`EXCLUDED` rows; a duplicate is rejected with `ERR_DUPLICATE_SUBJECT` (409). Once the incident's forensic scope has reached `BASELINED`, `AMENDED`, or `FINAL`, every subject's `data_elements_exposed` must be a subset of the scope's `data_elements_at_risk`; a non-subset is rejected with `ERR_DATA_ELEMENT_OUT_OF_SCOPE` (422).

A `DataAnalyst` may verify an `IDENTIFIED` subject — moving it to `VERIFIED` — provided `data_elements_exposed` is non-empty. Verification recomputes `total_affected_subjects` and `total_pending_subjects` on the incident and increments the incident's `version`. A `DataAnalyst` may alternatively exclude an `IDENTIFIED` subject — moving it to `EXCLUDED` — provided the incident's `notification_status` is neither `DISPATCHING` nor `COMPLETED`. Exclusion recomputes `total_affected_subjects`, `total_pending_subjects`, and `subjects_in_jurisdiction` on every linked `JurisdictionEvaluation`, and increments the incident's `version`. Both verify and exclude re-apply the subset check against the current forensic scope, so a scope amendment that narrows `data_elements_at_risk` can cause a previously admissible verify to be rejected with `ERR_DATA_ELEMENT_OUT_OF_SCOPE`.

### 3.5. Jurisdiction Obligation Matrix and Deadline Clock

A `PrivacyCounsel` registers a `JurisdictionEvaluation` for each jurisdiction that may govern notification, supplying the `state_code` (for example `CA`, `NY`, `TX`, or `GDPR-EEA`), the `statute_reference` (for example `Cal. Civ. Code §1798.82`), the `record_count_threshold` at or above which notification is mandatory, the `deadline_days` statutory window, the `deadline_kind` (either `CALENDAR_DAYS` or `BUSINESS_DAYS`), and two booleans: `requires_ag_notification` (whether the state Attorney General must also be notified) and `requires_credit_agencies` (whether the three nationwide consumer reporting agencies must be notified). New evaluations start in `PENDING` status with `subjects_in_jurisdiction` initialized to 0 and `deadline_at` null; creating an evaluation increments the incident's `version`.

The `subjects_in_jurisdiction` counter is maintained by the aggregation described in §2.9, and `notification_required` flips to true as soon as `subjects_in_jurisdiction` reaches `record_count_threshold` — the threshold comparison is inclusive.

The `deadline_at` field remains null until the incident transitions from `INVESTIGATING` to `CONFIRMED`. At the moment of that confirmation, every `PENDING` evaluation transitions to `TRIGGERED` and the server stamps a determination instant equal to the confirmation timestamp. From that instant, `deadline_at` is computed per the evaluation's `deadline_kind`. If the kind is `CALENDAR_DAYS`, the deadline is the calendar date obtained by adding `deadline_days` to the determination date, pinned to `23:59:59.999Z` of that final day. If the kind is `BUSINESS_DAYS`, the deadline is computed by walking forward from the determination instant and counting only Monday-through-Friday days that are not in the hardcoded list of US federal holidays for 2026 — January 1, January 19, February 16, May 25, June 19, July 3, September 7, October 12, November 11, November 26, and December 25 — until `deadline_days` business days have been counted; the result is again pinned to `23:59:59.999Z` of the final day. In both variants the determination instant is fixed first, the day arithmetic is applied second, and the end-of-day pinning is applied third.

The incident-level `notification_status` reacts to the evaluation matrix automatically: when any evaluation's `notification_required` flips to true while the incident is `EVALUATING`, the incident transitions to `REQUIRED`; when all evaluations resolve with `notification_required` false, the incident transitions back to `NOT_REQUIRED`.

### 3.6. Breach Confirmation, Containment, and Closure

Confirmation is the pivot on which the entire notification machinery turns. An `IncidentCommander` confirms the breach, advancing `investigation_status` from `INVESTIGATING` to `CONFIRMED`, only when two preconditions hold: at least one `SEALED` `EvidenceItem` exists for the incident (otherwise `ERR_EVIDENCE_NOT_SEALED`, 409), and `total_affected_subjects` is strictly greater than zero (otherwise `ERR_NO_AFFECTED_SUBJECTS`, 409). Confirmation has four side effects: `notification_status` flips to `EVALUATING`; every `PENDING` `JurisdictionEvaluation` transitions to `TRIGGERED` with its `deadline_at` computed per §3.5; each newly-`TRIGGERED` evaluation with `notification_required` true implicitly produces a notice-placeholder work item; and both risk scores are recomputed. The incident's `version` increments once for the confirmation as a whole.

Containment advances the incident from `CONFIRMED` to `CONTAINED` and is gated on every `RemediationAction` whose `category` is `TECHNICAL` having reached a terminal-or-cancelled posture — that is, `COMPLETED`, `VERIFIED`, or `CANCELLED`. Attempting containment while a technical action is still `OPEN` or `IN_PROGRESS` is rejected with `ERR_REMEDIATION_INCOMPLETE` (409). Containment flips `remediation_status` to `IN_PROGRESS` and increments the incident's `version`.

Closure is the terminal transition and carries the strictest gate. From `CONTAINED` to `CLOSED`, all of the following must hold simultaneously: `notification_status` must be `COMPLETED`, `WAIVED`, or `NOT_REQUIRED`; every `RemediationAction` must be in `VERIFIED` or `CANCELLED`; every `RegulatorSubmission` must be in `CLOSED` or `ACKNOWLEDGED`; and `remediation_status` must be `VERIFIED`. Any unmet condition surfaces as `ERR_INVALID_STATE` (or `ERR_REMEDIATION_INCOMPLETE` when the blocker is unfinished remediation). Closure increments the incident's `version` and is irreversible.

### 3.7. Notice Drafting, Approval, and Revision

The first time a `PrivacyCounsel` creates a `Notice` against an incident whose `notification_status` is `REQUIRED`, the incident transitions to `DRAFTING` and its `version` increments. Notice creation takes the linked `jurisdiction_evaluation_id`, the consumer-facing `body_text`, an optional ISO-639 `language` code defaulting to `en`, an optional `supersedes_notice_id` when the new notice is a revision of an existing `APPROVED` notice, and the mandatory `expected_incident_version` described in §2.6 — a stale value is rejected with `ERR_STALE_VERSION` (412). The supersession chain must remain acyclic: if `supersedes_notice_id` would form a cycle back to the notice being created, creation is rejected with `ERR_SUPERSESSION_CYCLE` (422). Each new notice begins in `DRAFT` status with `version_label` set to 1, and `approved_by_user_id` and `approved_at` both null.

Submitting a draft for legal review — moving the notice from `DRAFT` to `LEGAL_REVIEW` — requires `body_text` to be at least 200 characters long, and requires the incident's `notification_status` to be `DRAFTING` or `REQUIRED`. Submission increments the incident's `version`. Approval — moving the notice from `LEGAL_REVIEW` to `APPROVED` — is a `GeneralCounsel`-exclusive action and carries three preconditions evaluated in the priority order of §2.7: the incident's `investigation_status` must be `CONFIRMED` (otherwise `ERR_INVALID_STATE`, with the more specific `ERR_INCIDENT_NOT_CONFIRMED` (409) used when callers want to distinguish this case); the linked jurisdiction evaluation's `deadline_at` must be strictly in the future — approving a notice whose statutory deadline has already passed is rejected with `ERR_DEADLINE_PASSED` (409), also surfaced in some flows as `ERR_NOTICE_NOT_APPROVABLE` (409); and segregation of duties requires the acting `GeneralCounsel` `X-User-ID` to differ from the `PrivacyCounsel` `X-User-ID` who created the notice, with violation rejected as `ERR_SEGREGATION_OF_DUTIES` (409). On approval, the server stamps `approved_by_user_id` to the acting user and `approved_at` to the current timestamp, and increments the incident's `version`.

If legal review uncovers problems, a `GeneralCounsel` may instead request changes, returning the notice from `LEGAL_REVIEW` to `DRAFT` and incrementing `version_label` by 1 — so a notice that has been through two round trips carries `version_label` 3. Once a notice is `APPROVED`, a `PrivacyCounsel` may lock it for mail, moving it from `APPROVED` to `LOCKED_FOR_MAIL`, provided no `QUEUED` or `IN_PRODUCTION` mailing batch currently exists for that notice; locking increments the incident's `version`.

The revision cycle is explicit: when a new notice is created whose `supersedes_notice_id` points at an existing `APPROVED` notice, and that new notice is subsequently submitted for review, the prior notice automatically transitions from `APPROVED` to `SUPERSEDED`. Supersession has a destructive cascade — every `QUEUED` mailing batch pointing at the superseded notice is moved to `FAILED`, ensuring that no stale print run survives a revision. The incident-level `notification_status` flips from `DRAFTING` to `APPROVED` automatically as soon as every `TRIGGERED` jurisdiction evaluation has at least one notice in `APPROVED` or `LOCKED_FOR_MAIL`.

### 3.8. Mailing Vendor Coordination and Dispatch

With the incident in `APPROVED` notification posture, a `PrivacyCounsel` creates a `MailingBatch` against a locked notice, supplying the `notice_id`, the `vendor_code` (for example `PRINTCO_A` or `PRINTCO_B`), the `scheduled_ship_date`, and the mandatory `expected_incident_version`. A stale version is rejected with `ERR_STALE_VERSION` (412). The first batch creation flips the incident's `notification_status` from `APPROVED` to `DISPATCHING` and increments `version`; the new batch begins in `QUEUED` status with `recipient_count` zero.

Starting production — moving the batch from `QUEUED` to `IN_PRODUCTION` — is gated on the linked notice being in `LOCKED_FOR_MAIL` and the incident's `notification_status` being `DISPATCHING`. The side effects are extensive: every `AffectedSubject` in the batch's scope whose status is `VERIFIED` transitions to `NOTICE_QUEUED`; the batch's `recipient_count` is set to the number of subjects just transitioned; `total_pending_subjects` on the incident is recomputed; the `seats_required` of the currently `ACTIVE` `CallCenterStaffingPlan` is recomputed because the pending-subjects input to the seat formula has changed; and the incident's `version` increments.

Marking the batch shipped — moving it from `IN_PRODUCTION` to `SHIPPED` — requires `scheduled_ship_date` to be at or before the current time; attempting to ship early is rejected with `ERR_DEADLINE_PASSED` (409) or, in flows that distinguish shipping specifically, with `ERR_BATCH_NOT_SHIPPABLE` (409). On shipment, every subject that this batch moved into `NOTICE_QUEUED` now transitions to `NOTIFIED`; `total_notified_subjects` and `total_pending_subjects` are recomputed; if after this recompute `total_pending_subjects` is zero and `total_affected_subjects` equals `total_notified_subjects`, the incident's `notification_status` automatically transitions from `DISPATCHING` to `COMPLETED`; and the incident's `version` increments. Confirming delivery moves the batch from `SHIPPED` to `DELIVERED_CONFIRMED`, the batch's terminal-success state, with no further side effects.

A batch that has not yet entered production may be failed, moving it from `QUEUED` to `FAILED`. If the failed batch was the only batch pinning its notice to `LOCKED_FOR_MAIL`, the notice reverts to `APPROVED` so a fresh batch can be created against it; the incident's `version` increments.

### 3.9. Credit-Monitoring Offers

A `PrivacyCounsel` issues a `CreditMonitoringOffer` to an affected subject by supplying the `affected_subject_id`, the `vendor_code` (for example `CM_VENDOR_X`), the `term_months` (which must be either 12 or 24), and the `unit_cost_cents` (which must be greater than zero; violations of either constraint are rejected with `ERR_INVALID_REQUEST`, 422). At most one `ISSUED` offer may exist per `affected_subject_id` at any time; a second issuance against a subject with an already-`ISSUED` offer is rejected with `ERR_OFFER_ALREADY_ACTIVE` (409). The new offer is created in `ISSUED` status with a server-generated unique `offer_code` redemption string and an `expires_at` set to 90 days after the incident's determination instant. Issuance flips the target subject's `credit_monitoring_status` from `NOT_OFFERED` to `OFFERED_PENDING`, sets the subject's `offered_at` to the issuance timestamp, and increments the incident's `version`.

The subject themselves, authenticating as `AffectedSubjectRole` with `X-User-ID` equal to the subject's `id`, may redeem the offer while `expires_at` remains strictly in the future; redemption after expiry is rejected with `ERR_DEADLINE_PASSED` (409). Redemption moves the offer from `ISSUED` to `REDEEMED`, flips the subject's `credit_monitoring_status` to `ENROLLED`, recomputes `credit_monitoring_enrolled` on the incident, and increments the incident's `version`. The subject may instead decline, moving the offer from `ISSUED` to `DECLINED`, flipping the subject's `credit_monitoring_status` to `DECLINED`, recomputing `credit_monitoring_declined`, and incrementing `version`. If the logical clock advances past `expires_at` while the offer is still `ISSUED`, the offer automatically transitions to `EXPIRED` and the subject's `credit_monitoring_status` flips to `EXPIRED`. A `PrivacyCounsel` may cancel an `ISSUED` offer at any time before the incident's `notification_status` reaches `COMPLETED`; cancellation moves the offer to `CANCELLED`, returns the subject's `credit_monitoring_status` to `NOT_OFFERED`, and recomputes `credit_monitoring_offered`.

The incident's aggregate credit-monitoring cost in cents is exposed as a computed read. For each offer on the incident in any status, the per-offer cost is computed first and rounded to integer cents before any summation. The per-offer base is `term_months` multiplied by `unit_cost_cents`. If the offer is `REDEEMED`, its cost is the full base. If the offer is `DECLINED` or `EXPIRED`, its cost is zero. If the offer is `CANCELLED`, its cost is the base multiplied by a proration factor — the number of days from issuance to cancellation divided by thirty times `term_months` — rounded half-up to integer cents. If the offer is still `ISSUED`, its cost is the base multiplied by one tenth (a 10 percent reservation fee), rounded half-up to integer cents. The total cost is the sum of these per-offer rounded integer-cent values across all offers on the incident; the sum itself is never rounded. The computed read returns both the total in `credit_monitoring_cost_cents` and the number of offers considered in `offer_count`.

### 3.10. Call-Center Staffing

An `IncidentCommander` opens a `CallCenterStaffingPlan` for the incident by supplying `effective_from`, `effective_until`, and a `languages_supported` array (for example `['en','es']`). The plan must satisfy `effective_from` strictly earlier than `effective_until`, and its interval must not partially overlap the interval of any other `ACTIVE` plan for the same incident — half-open `[effective_from, effective_until)` semantics, with touching edges permitted; violations are rejected with `ERR_STAFFING_PLAN_OVERLAP` (409). The new plan starts in `ACTIVE` status and the incident's `version` increments. If the new plan's `effective_from` is at or after an existing `ACTIVE` plan's `effective_from` and strictly before that plan's `effective_until`, the existing plan is automatically transitioned from `ACTIVE` to `SUPERSEDED` — a strict-overlap requirement, so two plans whose intervals merely touch at an edge do not supersede each other.

The `seats_required` field is computed at plan creation from the incident's `total_pending_subjects` at that moment, denoted P below. The tier boundaries are inclusive on the lower bound and exclusive on the upper. If P is below 100, the base seat count is 2. If P is at least 100 but below 1000, the base is 2 plus the ceiling of (P minus 100) divided by 50. If P is at least 1000 but below 10000, the base is 20 plus the ceiling of (P minus 1000) divided by 250. If P is at least 10000, the base is 56 plus the ceiling of (P minus 10000) divided by 1000. After the base tier is determined, if the incident's `severity` is `CRITICAL` the base is multiplied by 1.5 and the result is rounded half-up to an integer. Finally, if `languages_supported` contains more than one language, 2 seats are added on top of the severity-adjusted result. The evaluation order is pinned: base tier first, severity multiplier with round-half-up second, language surcharge third. The computed `seats_required` must be at least 2; otherwise creation is rejected with `ERR_INVALID_REQUEST` (422).

Because the formula's primary input is `total_pending_subjects`, the active plan's `seats_required` is recomputed every time a mailing batch's start-of-production changes the pending-subject count. Once the incident's `notification_status` reaches `COMPLETED`, an `IncidentCommander` may close the active plan, moving it from `ACTIVE` to `CLOSED`; closure is only available in that notification posture.

### 3.11. Regulator and AG Submissions

When a jurisdiction evaluation requires Attorney-General notification, a `PrivacyCounsel` drafts a `RegulatorSubmission` by supplying the `jurisdiction_evaluation_id`, the `notice_id` of the approved notice to attach, and the `submission_channel` — one of `PORTAL`, `EMAIL`, or `CERTIFIED_MAIL`. The new submission begins in `DRAFT` status with `submitted_at` null, and creation increments the incident's `version`. Submitting to the regulator moves the submission from `DRAFT` to `SUBMITTED` and is gated on three preconditions: the attached notice must be `APPROVED` or `LOCKED_FOR_MAIL`; the linked evaluation's `requires_ag_notification` must be true; and the linked evaluation must be in `TRIGGERED` status. On submission, the server stamps `submitted_at` and increments the incident's `version`.

Acknowledgment by the regulator moves the submission from `SUBMITTED` to `ACKNOWLEDGED`. From there, the regulator may open an inquiry, moving the submission to `INQUIRY_OPEN`. Responding to the inquiry is a `GeneralCounsel`-exclusive action and enforces segregation of duties: the acting `GeneralCounsel` `X-User-ID` must differ from the submission's original submitter, with violation rejected as `ERR_SEGREGATION_OF_DUTIES` (409). Response moves the submission from `INQUIRY_OPEN` to `INQUIRY_RESPONDED`. Closure is available from either `ACKNOWLEDGED` or `INQUIRY_RESPONDED` and moves the submission to `CLOSED`, the terminal state.

### 3.12. Remediation and Lessons Learned

An `IncidentCommander` records a `RemediationAction` with a `title` (for example `Rotate CRM API keys`), a `category` chosen from `TECHNICAL`, `PROCESS`, `TRAINING`, `VENDOR`, or `LEGAL`, the `owner_user_id` of the responder who owns the action, and a `due_at` timestamp. New actions start in `OPEN` status with `completed_at` null, and creation increments the incident's `version`. The owner (or the `IncidentCommander` acting on their behalf) starts the action, moving it from `OPEN` to `IN_PROGRESS`; completes it, moving from `IN_PROGRESS` to `COMPLETED` with `completed_at` stamped; or cancels it directly from `OPEN`, moving to `CANCELLED`.

Verification is a `GeneralCounsel`-exclusive action and enforces segregation of duties against ownership: the acting `GeneralCounsel` `X-User-ID` must differ from the action's `owner_user_id`, with violation rejected as `ERR_SEGREGATION_OF_DUTIES` (409). Verification moves the action from `COMPLETED` to `VERIFIED`. The verify transition carries a roll-up side effect: if every `RemediationAction` row for the incident is now in `VERIFIED` or `CANCELLED`, the incident's `remediation_status` flips to `VERIFIED`. This roll-up, together with the per-category gate on containment (§3.6), ensures the incident cannot close while any technical remediation is still open.

### 3.13. Logical Clock for Deferred Actions

Certain transitions are time-triggered rather than actor-triggered — most visibly, an `ISSUED` credit-monitoring offer expires when the current time reaches its `expires_at`. To make those transitions testable, an `IncidentCommander` may advance the server's logical clock by supplying a `to_iso8601` instant; the server then re-evaluates every time-triggered transition. The startup default of the logical clock is exactly `2026-05-01T00:00:00Z`, and the logical clock never falls back to wall-clock time. Advancing the clock is what moves an `ISSUED` offer past `expires_at` into `EXPIRED` and flips the linked subject's `credit_monitoring_status` to `EXPIRED`.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200. All list endpoints are paginated per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /incidents | Create a new breach incident | IncidentCommander |
| GET | /incidents | List incidents (paginated; filter by severity, investigation_status, notification_status) | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, Auditor |
| GET | /incidents/{id} | Read one incident | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, Auditor |
| POST | /incidents/{id}/confirm | Confirm the breach (cascades jurisdiction triggers) | IncidentCommander |
| POST | /incidents/{id}/contain | Mark the incident as contained | IncidentCommander |
| POST | /incidents/{id}/close | Close the incident (terminal) | IncidentCommander |
| POST | /incidents/{id}/forensic-scopes | Create a forensic scope (first creation advances the incident) | IncidentCommander, ForensicLead |
| GET | /incidents/{id}/forensic-scopes | List forensic scopes for an incident | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/forensic-scopes/{scopeId} | Read one forensic scope | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/forensic-scopes/{scopeId}/baseline | Baseline the scope | ForensicLead |
| POST | /incidents/{id}/forensic-scopes/{scopeId}/amend | Amend the scope (recomputes risk) | ForensicLead |
| POST | /incidents/{id}/forensic-scopes/{scopeId}/re-baseline | Re-baseline an amended scope | ForensicLead |
| POST | /incidents/{id}/forensic-scopes/{scopeId}/finalize | Finalize the scope | ForensicLead |
| POST | /incidents/{id}/evidence-items | Register an evidence item | ForensicLead |
| GET | /incidents/{id}/evidence-items | List evidence items for an incident | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/evidence-items/{itemId} | Read one evidence item | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/evidence-items/{itemId}/seal | Seal an evidence item | ForensicLead |
| POST | /incidents/{id}/evidence-items/{itemId}/release | Release an evidence item | ForensicLead |
| POST | /incidents/{id}/evidence-items/{itemId}/destroy | Destroy an evidence item | ForensicLead |
| POST | /incidents/{id}/custody-logs | Record a custody handoff for an evidence item | ForensicLead |
| GET | /incidents/{id}/custody-logs | List custody logs (filter by evidence_item_id) | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/affected-subjects | Add an affected subject | DataAnalyst |
| GET | /incidents/{id}/affected-subjects | List affected subjects (filter by status, residence_state_code) | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, Auditor |
| GET | /incidents/{id}/affected-subjects/{subjectId} | Read one affected subject | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, Auditor |
| POST | /incidents/{id}/affected-subjects/{subjectId}/verify | Verify an affected subject | DataAnalyst |
| POST | /incidents/{id}/affected-subjects/{subjectId}/exclude | Exclude a subject | DataAnalyst |
| POST | /incidents/{id}/jurisdiction-evaluations | Register a jurisdiction evaluation row | PrivacyCounsel |
| GET | /incidents/{id}/jurisdiction-evaluations | List jurisdiction evaluations (filter by status) | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, Auditor |
| GET | /incidents/{id}/jurisdiction-evaluations/{evaluationId} | Read one jurisdiction evaluation | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, DataAnalyst, Auditor |
| POST | /incidents/{id}/notices | Draft a notice for a jurisdiction evaluation | PrivacyCounsel |
| GET | /incidents/{id}/notices | List notices for an incident | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/notices/{noticeId} | Read one notice | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/notices/{noticeId}/submit-for-review | Submit a draft notice for legal review | PrivacyCounsel |
| POST | /incidents/{id}/notices/{noticeId}/approve | General Counsel approves the notice | GeneralCounsel |
| POST | /incidents/{id}/notices/{noticeId}/request-changes | Send notice back to DRAFT with revision request | GeneralCounsel |
| POST | /incidents/{id}/notices/{noticeId}/lock-for-mail | Lock an approved notice for mailing | PrivacyCounsel |
| POST | /incidents/{id}/mailing-batches | Create a mailing batch against a locked notice | PrivacyCounsel |
| GET | /incidents/{id}/mailing-batches | List mailing batches | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/mailing-batches/{batchId} | Read one mailing batch | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/mailing-batches/{batchId}/start-production | Vendor starts production | PrivacyCounsel |
| POST | /incidents/{id}/mailing-batches/{batchId}/mark-shipped | Mark batch shipped | PrivacyCounsel |
| POST | /incidents/{id}/mailing-batches/{batchId}/confirm-delivery | Confirm delivery | PrivacyCounsel |
| POST | /incidents/{id}/mailing-batches/{batchId}/fail | Fail a queued batch | PrivacyCounsel |
| POST | /incidents/{id}/credit-monitoring-offers | Issue a credit-monitoring offer to a subject | PrivacyCounsel |
| GET | /incidents/{id}/credit-monitoring-offers | List credit-monitoring offers | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, AffectedSubjectRole |
| GET | /incidents/{id}/credit-monitoring-offers/{offerId} | Read one offer | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, AffectedSubjectRole |
| POST | /incidents/{id}/credit-monitoring-offers/{offerId}/redeem | Subject redeems the offer | AffectedSubjectRole |
| POST | /incidents/{id}/credit-monitoring-offers/{offerId}/decline | Subject declines the offer | AffectedSubjectRole |
| POST | /incidents/{id}/credit-monitoring-offers/{offerId}/cancel | PrivacyCounsel cancels an issued offer | PrivacyCounsel |
| POST | /incidents/{id}/call-center-staffing-plans | Create a staffing plan | IncidentCommander |
| GET | /incidents/{id}/call-center-staffing-plans | List staffing plans | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/call-center-staffing-plans/{planId} | Read one staffing plan | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/call-center-staffing-plans/{planId}/close | Close an active staffing plan | IncidentCommander |
| POST | /incidents/{id}/regulator-submissions | Draft a regulator/AG submission | PrivacyCounsel |
| GET | /incidents/{id}/regulator-submissions | List regulator submissions | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/regulator-submissions/{subId} | Read one submission | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/regulator-submissions/{subId}/submit | Submit to the regulator | PrivacyCounsel |
| POST | /incidents/{id}/regulator-submissions/{subId}/acknowledge | Mark acknowledged by regulator | PrivacyCounsel |
| POST | /incidents/{id}/regulator-submissions/{subId}/open-inquiry | Regulator opened an inquiry | PrivacyCounsel |
| POST | /incidents/{id}/regulator-submissions/{subId}/respond-inquiry | Respond to regulator inquiry | GeneralCounsel |
| POST | /incidents/{id}/regulator-submissions/{subId}/close | Close the submission record | PrivacyCounsel |
| POST | /incidents/{id}/remediation-actions | Create a remediation action | IncidentCommander |
| GET | /incidents/{id}/remediation-actions | List remediation actions | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /incidents/{id}/remediation-actions/{actionId} | Read one remediation action | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /incidents/{id}/remediation-actions/{actionId}/start | Start a remediation action | IncidentCommander |
| POST | /incidents/{id}/remediation-actions/{actionId}/complete | Complete a remediation action | IncidentCommander |
| POST | /incidents/{id}/remediation-actions/{actionId}/verify | Verify completion | GeneralCounsel |
| POST | /incidents/{id}/remediation-actions/{actionId}/cancel | Cancel a remediation action | IncidentCommander |
| GET | /incidents/{id}/cost-summary | Computed read: total credit-monitoring cost in cents | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| POST | /_clock/set_current_utc | Set the server's logical clock | IncidentCommander |
| GET | /custody-logs | List custody logs (flat, filtered) | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /custody-logs/{id} | Read one custody log (flat) | IncidentCommander, ForensicLead, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /notices | List notices (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /notices/{id} | Read one notice (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /mailing-batches | List mailing batches (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /mailing-batches/{id} | Read one mailing batch (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /credit-monitoring-offers | List credit-monitoring offers (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, AffectedSubjectRole |
| GET | /credit-monitoring-offers/{id} | Read one credit-monitoring offer (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, AffectedSubjectRole |
| GET | /regulator-submissions | List regulator submissions (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /regulator-submissions/{id} | Read one regulator submission (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /jurisdiction-evaluations | List jurisdiction evaluations (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, DataAnalyst, ForensicLead |
| GET | /jurisdiction-evaluations/{id} | Read one jurisdiction evaluation (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, DataAnalyst, ForensicLead |
| GET | /affected-subjects | List affected subjects (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, DataAnalyst |
| GET | /affected-subjects/{id} | Read one affected subject (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, DataAnalyst |
| GET | /evidence-items | List evidence items (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, ForensicLead |
| GET | /evidence-items/{id} | Read one evidence item (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, ForensicLead |
| GET | /forensic-scopes | List forensic scopes (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, ForensicLead |
| GET | /forensic-scopes/{id} | Read one forensic scope (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, ForensicLead |
| GET | /remediation-actions | List remediation actions (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, ForensicLead |
| GET | /remediation-actions/{id} | Read one remediation action (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor, ForensicLead |
| GET | /call-center-staffing-plans | List staffing plans (flat, filtered) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |
| GET | /call-center-staffing-plans/{id} | Read one staffing plan (flat) | IncidentCommander, PrivacyCounsel, GeneralCounsel, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_DEADLINE_PASSED | 409 |
| ERR_CUSTODY_OVERLAP | 409 |
| ERR_DATA_ELEMENT_OUT_OF_SCOPE | 422 |
| ERR_SUPERSESSION_CYCLE | 422 |
| ERR_STAFFING_PLAN_OVERLAP | 409 |
| ERR_DUPLICATE_SUBJECT | 409 |
| ERR_OFFER_ALREADY_ACTIVE | 409 |
| ERR_INCIDENT_NOT_CONFIRMED | 409 |
| ERR_NOTICE_NOT_APPROVABLE | 409 |
| ERR_NO_ACTIVE_STAFFING_PLAN | 409 |
| ERR_BATCH_NOT_SHIPPABLE | 409 |
| ERR_EVIDENCE_NOT_SEALED | 409 |
| ERR_REMEDIATION_INCOMPLETE | 409 |
| ERR_NO_AFFECTED_SUBJECTS | 409 |
