# Privacy Program & Data Mapping API — Product Requirements Document

## 1. Introduction

The corporate privacy office operates at the intersection of data governance, regulatory compliance, and operational accountability. Every processing activity the business undertakes must be catalogued, every vendor that touches personal data must be vetted, every cross-border transfer must be assessed for legal adequacy, and every consumer who exercises a privacy right must receive a timely, verifiable response. The cost of getting this wrong is measured not just in fines but in the organization's license to operate in regulated markets.

This document specifies the Privacy Program & Data Mapping API, a single REST surface mounted under `/privacy` that the privacy office uses to run the full lifecycle of its compliance program. The API covers the processing-activity inventory and the data elements each activity links, the legal-basis documentation and retention policies that govern each purpose of processing, the vendor register with its contract-clause verification workflow, privacy impact assessments triggered by risk thresholds or initiated manually, consumer rights requests routed across the systems that store the requested categories, cross-border transfer assessment, notice and policy version management with a supersede-and-retract protocol, and state-law applicability determination with threshold monitoring.

The system enforces segregation of duties between the business owners who submit assessments and the legal counsel who decide them, between the vendor managers who onboard processors and the privacy administrators who approve them, and between the data stewards who route rights requests and the legal counsel who may deny them. A logical clock drives all temporal semantics — deadlines, effectiveness windows, retention expiry — so that compliance behavior is deterministic and reproducible. The remainder of this document is organized as follows: §2 states the system-wide contracts every endpoint honors, §3 walks the business workflows and the rules that gate them, §4 tabulates the endpoints, and §5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if the role value is not one of the declared roles, the server rejects the request with `ERR_UNAUTHENTICATED` (HTTP 401). If the caller's role is not in the endpoint's authorized role list, or if a `Consumer` attempts to act on another consumer's resources, the server rejects the request with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles are declared. `PrivacyAdmin` is the privacy office administrator and owns configuration, notices, vendor approval, transfers, applicability runs, and the logical clock. `DataSteward` is the data mapping steward and owns data elements, processing activities, purposes, PIA creation, request verification, routing, response, and task execution. `BusinessOwner` is the business unit owner who submits privacy impact assessments for review. `LegalCounsel` is the legal reviewer who decides PIAs, verifies contracts, assesses transfers, and denies rights requests. `VendorManager` owns the vendor register and the contract lifecycle. `Consumer` is the external data subject who files rights requests.

For `PrivacyAdmin`, `DataSteward`, `BusinessOwner`, `LegalCounsel`, and `VendorManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` on a `PrivacyImpactAssessment` at submit time — but does not compare it to any entity's `id`. When `X-User-Role` is `Consumer`, `X-User-ID` is the `id` of the acting `Consumer`; ownership checks on any resource that references a `Consumer` compare the resource's foreign-key field to `X-User-ID`, so a consumer may file requests only for itself and may read only its own requests.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; the default `offset` is 0. A non-integer `limit` or `offset`, a `limit` outside the range 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Results are returned sorted by `created_at` ascending. The response `meta` carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted entity carries a server-minted `id` that is a UUID with no type prefix, a `created_at` timestamp, and — for all entities except `ApplicabilityEvaluation` — an `updated_at` timestamp and a monotonically increasing integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits. `version` starts at 1 on creation and increments by exactly 1 on every mutation, including cascade-driven mutations initiated by the system rather than by a client request. `ApplicabilityEvaluation` is the exception: it carries `id` and `created_at` but no `updated_at` and no `version`, because evaluation rows are immutable records of a threshold-monitoring run.

### 2.5. The Logical Clock

All temporal semantics in the system — effectiveness windows, retention expiry, deadline computation, the `published_at` timestamp on a notice, and overdue evaluation on rights requests — are anchored to a logical clock, never to wall time. Before any test-driving call, the clock reads exactly 2026-08-01T00:00:00Z; the clock never falls back to wall time at any point. A privacy administrator may advance the clock to a supplied `to_iso8601` instant via an admin-only test-driving capability; the supplied instant is applied unconditionally — no monotonicity check is performed, so the clock may be set to an earlier instant than its current reading — and the capability returns the new `current_utc`. Everywhere this document says "the logical clock," it means this server-held instant.

### 2.6. Precision, Rounding, and Risk Arithmetic

Risk scores, applicability percentages, and all other computed numbers obey one set of precision rules. The activity risk score and the assessment final score are integers throughout. The element-value products (category weight times classification multiplier) yield values with a fractional part of exactly .0 or .5; round-half-up is applied exactly once, to the max term in the screening variant and to the sum term in the comprehensive variant, before the remaining surcharges and the cap are applied. The applicability revenue share percentage is computed by dividing the raw annual cent totals first, multiplying by 100, then rounding half-up once to two decimal places; per-quarter or per-line values are never rounded first, and no truncation occurs at any step. Day arithmetic for deadlines and retention operates on the `created_at` timestamp of the owning record.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. A reclassification request on a data element must carry `expected_element_version` matching the element's current `version`; if another writer has advanced the element's version since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because reclassification legitimately overwrites the category and classification and cascades into activity risk, and a stale writer would silently undo a reclassification it never observed. A contract-creation request against a vendor must carry `expected_vendor_version` matching that vendor's current `version`; if the vendor's version has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because contract creation legitimately supersedes the vendor's existing draft and verified contracts, and a stale writer would supersede contracts it never observed. Endpoints not named in this subsection do not take a version field.

### 2.8. Validation Priority Order

When multiple validation rules guard the same endpoint, they are evaluated in a fixed priority order, and the first failure surfaces its error. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_FORBIDDEN_ROLE`). Path-id and body-supplied foreign-key existence (`ERR_NOT_FOUND`) comes next, with path identifiers validated left-to-right. Optimistic-concurrency staleness (`ERR_STALE_VERSION`) follows on the two OCC-guarded writes. Lifecycle-state permission (`ERR_INVALID_STATE_TRANSITION`) is then checked on every state-transition endpoint, covering both invalid-from and terminal lockdown. Cross-dimension and parent-state gates — routing while unverified, creating a purpose or assessment on a retired activity, responding before tasks are done — come after that, surfacing `ERR_REQUEST_NOT_VERIFIED`, `ERR_ACTIVITY_RETIRED`, or `ERR_TASKS_OUTSTANDING`. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) is checked next, then transfer mechanism adequacy (`ERR_MECHANISM_NOT_ADEQUATE`), then PIA activation and resume gating (`ERR_PIA_NOT_APPROVED`), then referenced-entity state checks (`ERR_NO_PUBLISHED_NOTICE`, `ERR_ELEMENT_RETIRED`, `ERR_VENDOR_NOT_APPROVED`, `ERR_SYSTEM_DECOMMISSIONED`, `ERR_CONTRACT_NOT_EXECUTED`, `ERR_NO_EXECUTED_CONTRACT`), then temporal window validity (`ERR_INVALID_WINDOW`, `ERR_NOTICE_WINDOW_OVERLAP`), then uniqueness, buffer, pool, and open-assessment constraints (`ERR_DUPLICATE_KEY`, `ERR_TRANSFER_WINDOW_CONFLICT`, `ERR_OPEN_ASSESSMENT_EXISTS`, `ERR_NO_SYSTEMS_IN_SCOPE`, `ERR_NO_DOCUMENTED_PURPOSE`), and finally request body shape (`ERR_INVALID_REQUEST`).

### 2.9. Hierarchical Consistency and Cascade Semantics

A small number of operations mutate more than one entity. Whenever this document describes a cascade, every entity touched by the cascade — including the root entity whose state changed — has its `version` incremented by exactly 1 and its `updated_at` refreshed. Cascades are processed in a deterministic order: where the cascade fans out over a collection, members are visited in `created_at` ascending order unless the narrative says otherwise. Nested path identifiers are validated left-to-right, so a request against `/privacy/vendors/{vendor_id}/contracts` first checks that the vendor exists before any contract-level rule runs. A state machine's terminal state is a lockdown: once a resource reaches a terminal state, no further trigger is valid against it, and any attempt is rejected with `ERR_INVALID_STATE_TRANSITION`, unless the endpoint's own narrative assigns a different error to that trigger — the rights-request respond endpoint rejects every attempt against a request not in `READY_TO_RESPOND` with `ERR_TASKS_OUTSTANDING`, terminal states included.

### 2.10. The Two Risk Score Variants and the PIA Gating Order

The system computes two variants of the activity risk score at different moments and for different purposes, and it pins their evaluation order to break what would otherwise look like a circular dependency between risk, PIA gating, and activation. The **screening** variant is computed only at activity creation and during the data-element reclassification cascade; the `pia_required` flag is derived only from the screening score at those same two moments. The **comprehensive** variant is computed only at PIA approval and is written only to the assessment's `final_score`. The final score never feeds back into the activity's `risk_score`, never re-derives `pia_required`, and never gates activation. A reader should therefore treat the screening score as the gating signal and the comprehensive score as the audit record.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Retention Policies, Data Elements, Data Systems, State Law Rules

Before any processing activity can be documented, the privacy office seeds its reference data. A `PrivacyAdmin` creates retention policies by supplying a `policy_code`, a `duration_days` integer count that must be greater than zero, and a `disposal_action` that is one of `ANONYMIZE`, `DELETE`, or `ARCHIVE`. The policy code is unique across all retention policies; a collision is rejected with `ERR_DUPLICATE_KEY`.

A `DataSteward` then catalogues data elements. Each element carries an `element_key` that is unique across all data elements, a `category` drawn from `BASIC_CONTACT`, `IDENTIFIER`, `FINANCIAL`, `HEALTH`, `BIOMETRIC`, `PRECISE_LOCATION`, or `MINOR_DATA`, and a `classification` drawn from `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or `RESTRICTED`. An element is created in `ACTIVE` status. The category drives a risk weight — `BASIC_CONTACT` 50, `IDENTIFIER` 100, `FINANCIAL` 200, `PRECISE_LOCATION` 250, `HEALTH` 300, `MINOR_DATA` 350, `BIOMETRIC` 400 — and the classification drives a risk multiplier — `PUBLIC` 0.5, `INTERNAL` 1.0, `CONFIDENTIAL` 1.5, `RESTRICTED` 2.0 — and the element's value in any risk computation is the product of its weight and its multiplier. A `DataSteward` may retire an element that is `ACTIVE`; retirement sets the element's `status` to `RETIRED` and bumps its version. Retired elements are rejected by `ERR_ELEMENT_RETIRED` when a new processing activity attempts to link them, but activities that already link the element are not modified — links are immutable once created.

A `PrivacyAdmin` registers data systems by supplying a `system_key` that is unique across all systems, a `hosting_region` that is one of `US`, `EU`, `UK`, `BR`, or `APAC`, and a `stores_categories` list whose members are drawn from the data element category enum; the list may be empty. A system is created in `ACTIVE` status. When a system is no longer in service, the administrator decommissions it, transitioning its `status` to `DECOMMISSIONED`. Decommissioned systems are no longer eligible for routing selection and cannot be the source of a new transfer.

A `PrivacyAdmin` also declares state law rules. Each rule carries a `state_code` that is a 2-letter US state code unique across all rules — any two alphabetic characters are accepted, without case normalization — a `law_name` such as CCPA, a `resident_records_threshold` integer greater than zero, a `revenue_share_threshold_pct` numeric value greater than 0 and at most 100, a `request_deadline_days` integer greater than zero, and an `extension_days` integer that may be zero or more. These rules feed both the applicability-monitoring run described in §3.8 and the deadline computation described in §3.6.

### 3.2. Notices and the Supersede-and-Retract Protocol

Privacy notices are versioned documents with half-open effectiveness windows. A `PrivacyAdmin` creates a notice by supplying a `scope` — one of `WEBSITE`, `MOBILE_APP`, `EMPLOYEE`, or `LOYALTY_PROGRAM` — a `title`, a `body`, an `effective_from` instant, an optional `effective_to` instant whose absence leaves the window open-ended, and an optional `supersedes_notice_id` declaring which currently published notice this one is intended to replace. A new notice is created in `DRAFT` status, with `published_at` and `superseded_by_notice_id` both null.

Publication is the load-bearing transition. When a `PrivacyAdmin` publishes a draft notice, the server first checks the window itself: if `effective_to` is present it must be strictly after `effective_from`, otherwise the publish is rejected with `ERR_INVALID_WINDOW`. The server then checks overlap against other notices in the same scope. The publication window is half-open — `effective_from` is inclusive, `effective_to` is exclusive — and two notices whose windows share only a boundary instant are adjacent, not overlapping, and do not conflict. If another `PUBLISHED` notice in the same scope has a window that overlaps this one, and that notice is not the declared `supersedes_notice_id` target, the publish is rejected with `ERR_NOTICE_WINDOW_OVERLAP`. If `supersedes_notice_id` is non-null, its target must be `PUBLISHED`, must be in the same scope, and must have a window that overlaps this notice's window; a target that fails any of these three conditions also yields `ERR_NOTICE_WINDOW_OVERLAP`. When all checks pass, the notice's `status` becomes `PUBLISHED`, `published_at` is set to the logical clock, and the notice's version increments.

The publication then cascades. If `supersedes_notice_id` was declared, that target notice transitions to `SUPERSEDED` with its `superseded_by_notice_id` set to the newly published notice's id. Every `Purpose` whose `pinned_notice_id` equals the superseded notice's id and whose `status` is `DOCUMENTED` transitions to `CONSENT_STALE`, processed in `created_at` ascending order. Every `ProcessingActivity` that owns at least one such stale purpose and whose `status` is `ACTIVE` transitions to `COMPLIANCE_HOLD`. Every `CrossBorderTransfer` whose `activity_id` is one of those held activities and whose `status` is `APPROVED` transitions to `SUSPENDED` with `suspension_reason` set to `ACTIVITY_HOLD`. Each entity touched by the cascade has its version incremented.

Retraction is the compensating action. When a `PrivacyAdmin` retracts a `PUBLISHED` notice, the retracted notice's `status` becomes `RETRACTED`. The notice that this one superseded — identified by its `superseded_by_notice_id` pointing back to the retracted notice — is restored to `PUBLISHED` if it is still `SUPERSEDED`. Every `Purpose` in `CONSENT_STALE` whose `pinned_notice_id` is the restored notice's id transitions back to `DOCUMENTED`, in `created_at` ascending order. Every `ProcessingActivity` in `COMPLIANCE_HOLD` that now has zero purposes in `CONSENT_STALE` and zero assessments in `TRIGGERED`, `IN_REVIEW`, or `CHANGES_REQUESTED` transitions back to `ACTIVE`. Every `CrossBorderTransfer` in `SUSPENDED` with `suspension_reason` equal to `ACTIVITY_HOLD` whose owning activity just resumed transitions back to `APPROVED` with `suspension_reason` cleared to null. Retraction therefore unwinds the staleness cascade that publication introduced.

### 3.3. Vendors and the Contract Clause Verification Workflow

A `VendorManager` onboards a vendor by supplying the `vendor_name`, a `home_region` drawn from the same five-region enum as data systems, and a `processes_categories` list whose members are drawn from the data element category enum; the list may be empty. At creation the server computes the vendor's `risk_tier`. If `processes_categories` intersects the high-sensitivity set — `HEALTH`, `BIOMETRIC`, or `MINOR_DATA` — the tier is `HIGH`. Otherwise, if it intersects the moderate-sensitivity set — `FINANCIAL`, `PRECISE_LOCATION`, or `IDENTIFIER` — the tier is `STANDARD`. Otherwise — the list is empty or contains only `BASIC_CONTACT` — the tier is `LOW`. The vendor is created in `ONBOARDING` status.

The vendor's lifecycle runs `ONBOARDING` → `ASSESSMENT` → `APPROVED` (or `REJECTED`) → `OFFBOARDED`. A `VendorManager` submits the vendor for assessment, moving the status from `ONBOARDING` to `ASSESSMENT`. A `PrivacyAdmin` then approves or rejects. Approval requires that the vendor already have at least one `VendorContract` in `EXECUTED` status; without one, the approve is rejected with `ERR_NO_EXECUTED_CONTRACT`. Rejection moves the vendor to the terminal `REJECTED` status. An approved vendor may later be offboarded, moving its `status` to `OFFBOARDED`.

Offboarding cascades. Every `VendorContract` of the vendor in `DRAFT`, `VERIFIED`, or `EXECUTED` status transitions to `SUPERSEDED`, processed in `created_at` ascending order. Every `CrossBorderTransfer` whose `vendor_contract_id` is one of those formerly-executed contracts and whose `status` is `APPROVED` transitions to `SUSPENDED` with `suspension_reason` set to `CONTRACT_SUPERSEDED`. In a direct fan-out that is not part of the hop chain, every `CrossBorderTransfer` whose `vendor_id` is this vendor and whose `status` is `PROPOSED` or `UNDER_ASSESSMENT` transitions to `REJECTED`.

Contracts are managed as children of the vendor. When a `VendorManager` creates a contract against a vendor, the request must carry `expected_vendor_version` per the OCC rule in §2.7. The request body supplies `provided_clauses`, a list whose members are drawn from `DPA`, `BREACH_NOTICE_72H`, `DELETION_ON_EXIT`, `SUBPROCESSOR_CONSENT`, and `AUDIT_RIGHTS`. At creation the server computes `required_clauses` from the vendor's `risk_tier`: a `LOW` tier requires only `DPA`; a `STANDARD` tier requires `DPA`, `BREACH_NOTICE_72H`, and `DELETION_ON_EXIT`; a `HIGH` tier requires all five — `DPA`, `BREACH_NOTICE_72H`, `DELETION_ON_EXIT`, `SUBPROCESSOR_CONSENT`, and `AUDIT_RIGHTS`. The server also computes `missing_clauses` as the required set minus the provided set, sorted by clause code ascending. The new contract is created in `DRAFT` status with `verification_status` set to `UNVERIFIED`. Creating the contract also increments the owning vendor's `version` by exactly 1 and refreshes its `updated_at`, which is what makes a concurrent stale `expected_vendor_version` observable. Creating a newer contract for the same vendor supersedes every prior `DRAFT` or `VERIFIED` contract of that vendor, each of which transitions to `SUPERSEDED`.

A `LegalCounsel` reviewer then verifies the contract. If `missing_clauses` is empty, verification passes: `verification_status` becomes `PASSED` and `status` advances from `DRAFT` to `VERIFIED`. If `missing_clauses` is non-empty, verification fails: `verification_status` becomes `FAILED` and `status` stays `DRAFT`. A `VendorManager` may then execute a `VERIFIED` contract, moving it to `EXECUTED`, but only when the owning vendor's `status` is neither `REJECTED` nor `OFFBOARDED`; a vendor in either of those states yields `ERR_INVALID_STATE_TRANSITION` on the execute attempt.

### 3.4. Processing Activities, Purposes, and the Reclassification Cascade

A `DataSteward` documents a processing activity by supplying an `activity_name`, a `business_unit`, a `notice_scope` drawn from the same four-value enum as notices, a `data_element_ids` list whose members must each resolve to a data element in `ACTIVE` status (duplicate entries are preserved as supplied, and each occurrence counts as a linked element in the risk computation), and an optional `vendor_id` referencing the processing vendor. The list of elements may be empty. At creation the server computes the screening variant of the risk score. For each linked element, the element value is its category weight multiplied by its classification multiplier, using the tables in §3.1. The screening score takes the maximum element value across the linked set — the maximum over an empty set is 0 — adds 25 for each element beyond the first, adds the vendor exposure (0 for `LOW`, 75 for `STANDARD`, 150 for `HIGH`, and 0 when no vendor is linked), applies round-half-up to the max term before the surcharges, and caps the result at 1000. The result is stored on the activity's `risk_score` and the activity's `pia_required` is set to true exactly when the screening score reaches at least 500. If `pia_required` is true, the server auto-creates a `PrivacyImpactAssessment` in `TRIGGERED` status with `trigger_reason` set to `RISK_THRESHOLD`. The new activity itself is created in `DRAFT` status.

The activity lifecycle runs `DRAFT` → `ACTIVE` → `COMPLIANCE_HOLD` → `ACTIVE` → `RETIRED`, with the hold reachable only by cascade. Activation by a `DataSteward` requires that the activity be in `DRAFT`, that any `pia_required` activity already have an `APPROVED` assessment — otherwise `ERR_PIA_NOT_APPROVED` — and that at least one `Purpose` with `status` `DOCUMENTED` exist for the activity — otherwise `ERR_NO_DOCUMENTED_PURPOSE`. Resume by a `DataSteward` requires that the activity be in `COMPLIANCE_HOLD`, that no `Purpose` of the activity be in `CONSENT_STALE`, and that no assessment in `TRIGGERED`, `IN_REVIEW`, or `CHANGES_REQUESTED` exist for the activity — a violation of the stale-purpose condition yields `ERR_INVALID_STATE_TRANSITION`, and a violation of the last of these yields `ERR_PIA_NOT_APPROVED`. When a resume succeeds, every `CrossBorderTransfer` whose `activity_id` is this activity and whose `status` is `SUSPENDED` with `suspension_reason` equal to `ACTIVITY_HOLD` transitions back to `APPROVED` with `suspension_reason` cleared. Retirement by a `DataSteward` is valid from either `ACTIVE` or `COMPLIANCE_HOLD` and moves the activity to the terminal `RETIRED` status; every `CrossBorderTransfer` whose `activity_id` is this activity and whose `status` is `APPROVED` transitions to `SUSPENDED` with `suspension_reason` set to `ACTIVITY_HOLD`.

Reclassification is the second route into the compliance hold. Only an `ACTIVE` element may be reclassified; the attempt against a `RETIRED` element is rejected with `ERR_INVALID_STATE_TRANSITION`. When a `DataSteward` reclassifies an element — supplying a new `category`, a new `classification`, and the `expected_element_version` per §2.7 — the element's category and classification are overwritten and its version increments. The reclassification then cascades. In hop 1, every `ProcessingActivity` whose `data_element_ids` contains this element and whose `status` is `DRAFT`, `ACTIVE`, or `COMPLIANCE_HOLD` has its `risk_score` and `pia_required` recomputed using the screening variant, processed in `created_at` ascending order. In hop 2, any such activity whose `pia_required` flips from false to true gets a `PrivacyImpactAssessment` auto-created in `TRIGGERED` status with `trigger_reason` set to `RECLASSIFICATION`, but only when no open assessment — one in `TRIGGERED`, `IN_REVIEW`, or `CHANGES_REQUESTED` — already exists for that activity. In hop 3, any such activity in `ACTIVE` status transitions to `COMPLIANCE_HOLD`; this reclassification-driven hold does not suspend the activity's transfers.

Purposes document why an activity processes data. A `DataSteward` creates a purpose against an activity that is not `RETIRED` — attempting it against a retired activity is rejected with `ERR_ACTIVITY_RETIRED` — by supplying a `purpose_type` drawn from `MARKETING`, `ANALYTICS`, `SERVICE_DELIVERY`, `EMPLOYMENT`, `LEGAL_COMPLIANCE`, or `RESEARCH`, a `legal_basis` drawn from `CONSENT`, `CONTRACT`, `LEGAL_OBLIGATION`, `LEGITIMATE_INTEREST`, `VITAL_INTEREST`, or `PUBLIC_TASK`, and a `retention_policy_id` referencing an existing retention policy. The new purpose is created in `DOCUMENTED` status. The server computes `retention_expires_at` as the purpose's `created_at` plus the policy's `duration_days` days. When the legal basis is `CONSENT`, the server also pins `pinned_notice_id` to the current `PUBLISHED` notice in the activity's `notice_scope`, selected by the same rule the relink action uses below — the notice whose window contains the logical clock, else the one with the latest `effective_from`, ties broken by `created_at` ascending; if no such published notice exists the create is rejected with `ERR_NO_PUBLISHED_NOTICE`. For non-consent bases, `pinned_notice_id` stays null. An activity-level earliest-purge timestamp may be derived on read as the minimum `retention_expires_at` across the activity's purposes whose `status` is not `RETIRED`, and is null when no such purposes exist.

Relink is the recovery path for a consent-stale purpose. When a `DataSteward` relinks a purpose in `CONSENT_STALE` status, the server requires that a `PUBLISHED` notice exist in the purpose's activity's `notice_scope` — otherwise `ERR_NO_PUBLISHED_NOTICE` — and re-pins `pinned_notice_id` to the current published notice in scope. When several published notices in the scope have disjoint windows, the pin target is the one whose window contains the logical clock — and if several windows contain it, the earliest-created containing notice wins; if none contains it, the target is the one with the latest `effective_from`, with those ties broken by `created_at` ascending. The purpose returns to `DOCUMENTED`. If the owning activity is in `COMPLIANCE_HOLD` and now has zero remaining `CONSENT_STALE` purposes and zero assessments in `TRIGGERED`, `IN_REVIEW`, or `CHANGES_REQUESTED`, the activity auto-resumes to `ACTIVE`, reinstating its `ACTIVITY_HOLD`-suspended transfers as in the resume transition. A purpose in either `DOCUMENTED` or `CONSENT_STALE` may be retired, moving it to the terminal `RETIRED` status.

### 3.5. Privacy Impact Assessments and Segregation of Duties

Assessments enter the system through three routes. A risk-threshold trigger auto-creates one at activity creation, as described in §3.4, with `trigger_reason` `RISK_THRESHOLD`. A reclassification cascade auto-creates one when an activity's `pia_required` flips to true, with `trigger_reason` `RECLASSIFICATION`. A `DataSteward` may also manually trigger one against an activity that is not `RETIRED`, with `trigger_reason` `MANUAL`; the manual route is blocked with `ERR_OPEN_ASSESSMENT_EXISTS` when the activity already has an open assessment in `TRIGGERED`, `IN_REVIEW`, or `CHANGES_REQUESTED`. In all three routes the assessment is created in `TRIGGERED` status, its `screening_score` is copied from the activity's current `risk_score`, its `final_score` is null, and its `submitted_by_user_id` is null.

The review workflow is a segregation-of-duties handshake between `BusinessOwner` and `LegalCounsel`. A `BusinessOwner` submits an assessment in `TRIGGERED` or `CHANGES_REQUESTED` status; the assessment moves to `IN_REVIEW` and its `submitted_by_user_id` is set to the caller's `X-User-ID`. From `IN_REVIEW`, a `LegalCounsel` reviewer may request changes, approve, or reject. All three reviewer actions require that the reviewer's `X-User-ID` differ from the assessment's `submitted_by_user_id`; a reviewer who is also the most recent submitter is rejected with `ERR_SEGREGATION_OF_DUTIES`. Request-changes moves the assessment to `CHANGES_REQUESTED`, from which the business owner may submit again. Reject moves the assessment to the terminal `REJECTED` status.

Approve is the heaviest transition. The server computes the comprehensive variant of the risk score over the activity's current linked elements, vendor, and documented purposes: the element values are summed rather than maxed, round-half-up is applied to the sum term, the vendor exposure is added as in the screening variant, a consent adjustment of 50 is added when any purpose of the activity has `status` `DOCUMENTED` and `legal_basis` `CONSENT`, and the result is capped at 1000. The computed value is written to the assessment's `final_score`, the assessment moves to the terminal `APPROVED` status, and per the gating order in §2.10 the final score never re-derives `pia_required` or re-gates activation. Approval then cascades: if the owning activity is in `COMPLIANCE_HOLD` with zero `CONSENT_STALE` purposes and zero other assessments in `TRIGGERED`, `IN_REVIEW`, or `CHANGES_REQUESTED`, the activity auto-resumes to `ACTIVE`, reinstating its `ACTIVITY_HOLD`-suspended transfers.

### 3.6. Consumer Rights Requests and Deadline Computation

A `PrivacyAdmin` registers consumers by supplying an `email` that is unique across all consumers — a collision yields `ERR_DUPLICATE_KEY` — a `full_name`, and a `state_code` that is a 2-letter US state code (any two alphabetic characters are accepted, without case normalization). Once registered, a consumer files rights requests for itself; the request body supplies a `request_type` drawn from `ACCESS`, `DELETION`, `CORRECTION`, `PORTABILITY`, or `OPT_OUT`, and a non-empty `requested_categories` list whose members are drawn from the data element category enum.

At request creation the server resolves the governing state law rule. The rule that governs is the `StateLawRule` whose `state_code` equals the consumer's `state_code`, but only when the latest `ApplicabilityEvaluation` for that rule — the one with the latest `created_at`, with ties in `created_at` (possible under a fixed logical clock) broken in favor of the later-created row — has `applies` true. If no rule exists for the state, or no evaluation exists for the rule, or the latest evaluation has `applies` false, the request falls back to defaults. The `applicable_state_code` is set to the governing rule's `state_code` when one governs and null otherwise. The provisional deadline, `provisional_due_at`, is the request's `created_at` plus the governing rule's `request_deadline_days`, or plus the 45-day default when no rule governs; the provisional variant never includes an extension. The new request is created with `verification_status` `UNVERIFIED` and `fulfillment_status` `INTAKE`, and `final_due_at` stays null until verification.

Verification is a `DataSteward` action on a request in `UNVERIFIED` status. A successful verify sets `verification_status` to `VERIFIED` and computes the final deadline. The governing rule consulted at verification is the one recorded on the request at creation via `applicable_state_code`; governance is never re-resolved against newer evaluations at verification time. The final variant anchors to the request's `created_at` — never to the verification time — and adds the governing rule's `request_deadline_days` (or the 45-day default) plus the rule's `extension_days` (or the 30-day default) when the `request_type` is `DELETION` or `PORTABILITY`; for `ACCESS`, `CORRECTION`, and `OPT_OUT` the final deadline equals the provisional deadline. A failed verification — the `DataSteward`'s fail-verification action — sets `verification_status` to `VERIFICATION_FAILED` and, in a cross-dimension side effect, moves `fulfillment_status` from `INTAKE` to `DENIED`; no tasks exist yet at intake, so no task cascade runs.

A rights request record carries `consumer_id` referencing the consumer who filed it; that field is what the server consults when enforcing the self-access rule in §2.1.

Routing is the next step and is gated on verification. When a `DataSteward` routes a request whose `fulfillment_status` is `INTAKE` and whose `verification_status` is `VERIFIED` — routing an unverified request is rejected with `ERR_REQUEST_NOT_VERIFIED` — the server selects the pool of `DataSystem` rows whose `status` is `ACTIVE` and whose `stores_categories` intersects the request's `requested_categories` with a non-empty intersection. The pool is ranked by `created_at` ascending; ties, which are possible under a fixed logical clock, are broken by `system_key` ascending, and `id` is never used as a tie-break. An empty pool is rejected with `ERR_NO_SYSTEMS_IN_SCOPE`; the system performs no partial routing. One `RequestTask` is created per selected system, in that order, each in `PENDING` status; each task carries `request_id` referencing the parent request and `data_system_id` referencing the system it fulfills against, and the request's `fulfillment_status` moves to `ROUTED`. The task list endpoints accept `rights_request_id` and `data_system_id` as optional foreign-key filters.

Tasks are worked by `DataSteward` operators. Starting a task in `PENDING` status moves it to `IN_PROGRESS`; the first task of a request to enter `IN_PROGRESS` bubbles the parent request from `ROUTED` to `IN_PROGRESS`. Completing a task in `IN_PROGRESS` status — optionally carrying `outcome_notes` — moves it to `COMPLETED`; when every sibling task has reached a terminal status, `COMPLETED` or `CANCELLED`, the parent request bubbles from `IN_PROGRESS` to `READY_TO_RESPOND`. A `DataSteward` then responds to a request in `READY_TO_RESPOND` status — a respond attempt against any other fulfillment status, including the terminal `COMPLETED` and `DENIED` states, is rejected with `ERR_TASKS_OUTSTANDING` — moving `fulfillment_status` to the terminal `COMPLETED`. A `LegalCounsel` reviewer may instead deny a request in `INTAKE`, `ROUTED`, or `IN_PROGRESS` status, optionally supplying a `reason`; denial moves `fulfillment_status` to `DENIED` and cancels every task of the request in `PENDING` or `IN_PROGRESS` status, processed in `created_at` ascending order.

Overdue evaluation is continuous. A request's `is_overdue` flag is true exactly when the logical clock is past the effective due date — `final_due_at` when the request is `VERIFIED`, else `provisional_due_at` — and the `fulfillment_status` is neither `COMPLETED` nor `DENIED`.

### 3.7. Cross-Border Transfers and the 30-Day Buffer

A `PrivacyAdmin` proposes a cross-border transfer by supplying a `source_system_id`, a `vendor_id`, a `vendor_contract_id`, an `activity_id`, a `dest_region` drawn from the five-region enum, a `mechanism` drawn from `SCC_2021`, `ADEQUACY`, `BCR`, or `DEROGATION`, and an `effective_from` and `effective_to` that delimit the transfer window. The referenced source system must be in `ACTIVE` status — otherwise `ERR_SYSTEM_DECOMMISSIONED` — and the referenced vendor must be in `APPROVED` status — otherwise `ERR_VENDOR_NOT_APPROVED`. The window itself must be valid: `effective_to` must be strictly after `effective_from`, otherwise `ERR_INVALID_WINDOW`. The new transfer is created in `PROPOSED` status with `suspension_reason` null.

The assessment workflow runs `PROPOSED` → `UNDER_ASSESSMENT` → `APPROVED` (or `REJECTED`). A `LegalCounsel` reviewer moves a proposed transfer into `UNDER_ASSESSMENT`. Approval then enforces three gates in addition to the state check. The mechanism-adequacy gate: if the source system's `hosting_region` is `EU` or `UK` and the `dest_region` is `US`, the `mechanism` must be `SCC_2021` or `BCR`, otherwise `ERR_MECHANISM_NOT_ADEQUATE`. The contract gate: the contract referenced by `vendor_contract_id` must be in `EXECUTED` status, otherwise `ERR_CONTRACT_NOT_EXECUTED`. The buffer gate: no other transfer with the same `source_system_id` and `vendor_id` and a status of `APPROVED` or `SUSPENDED` may have a window within 30 days of this window on either side — the new transfer's `effective_from` must be at or after the existing transfer's `effective_to` plus 30 days, or the new transfer's `effective_to` must be at or before the existing transfer's `effective_from` minus 30 days — otherwise `ERR_TRANSFER_WINDOW_CONFLICT`. When all gates pass, the transfer moves to `APPROVED`. Rejection moves it to the terminal `REJECTED` status.

Suspension is system-driven, never client-driven. An `APPROVED` transfer transitions to `SUSPENDED` when its activity is placed on hold by the notice-publication cascade (§3.2) or is retired — with `suspension_reason` set to `ACTIVITY_HOLD`; a hold imposed by the reclassification cascade (§3.4) does not suspend transfers — or when its contract is superseded by vendor offboarding — with `suspension_reason` set to `CONTRACT_SUPERSEDED`. A `SUSPENDED` transfer whose `suspension_reason` is `ACTIVITY_HOLD` transitions back to `APPROVED` with `suspension_reason` cleared when its owning activity resumes to `ACTIVE`. A transfer suspended for `CONTRACT_SUPERSEDED` does not auto-resume.

### 3.8. State-Law Applicability Monitoring

Threshold monitoring runs on demand. When a `PrivacyAdmin` triggers an applicability run, the request body supplies `state_revenues`, a map from state code to annual revenue in cents, and `total_revenue_cents`, the enterprise-wide annual revenue in cents. The run iterates over every `StateLawRule` in `created_at` ascending order, breaking ties by `state_code` ascending, and produces one `ApplicabilityEvaluation` row per rule. All rows of a run share one server-minted `evaluation_run_id`, which is also returned in the response alongside the `evaluation_count`.

Each evaluation row carries `state_law_rule_id` referencing the rule that was evaluated, and the evaluation list endpoint accepts `state_law_rule_id` and `evaluation_run_id` as optional filters.

For each rule, the run computes three derived values. `resident_consumer_count` is the count of `Consumer` rows whose `state_code` equals the rule's `state_code`; all consumers are counted, because no consumer status filter exists. `revenue_share_pct` takes the state's revenue from `state_revenues` — 0 when the state is absent from the map — divides by `total_revenue_cents`, multiplies by 100, and applies round-half-up once to two decimal places, in the pinned order described in §2.6; when `total_revenue_cents` is zero, `revenue_share_pct` is 0.00 for every rule. `applies` is true when the resident consumer count reaches at least the rule's `resident_records_threshold` or the revenue share percentage reaches at least the rule's `revenue_share_threshold_pct`. `margin_to_threshold` is the resident consumer count minus the rule's `resident_records_threshold`, and is negative when the count falls below the threshold. The resulting rows are immutable audit records; per §2.4 they carry no `updated_at` and no `version`. The `applies` value on the latest evaluation per rule is what the rights-request deadline resolver in §3.6 consults.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200. Error responses carry the HTTP status tabulated in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PrivacyAdmin |
| POST | `/privacy/retention-policies` | Create a retention policy | PrivacyAdmin |
| POST | `/privacy/data-elements` | Create a data element | DataSteward |
| GET | `/privacy/data-elements/{id}` | Get one data element | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/data-elements/{id}/reclassify` | Reclassify an element's category/classification (OCC-guarded) | DataSteward |
| POST | `/privacy/data-elements/{id}/retire` | Retire an element | DataSteward |
| POST | `/privacy/data-systems` | Register a data system | PrivacyAdmin |
| GET | `/privacy/data-systems` | List data systems (paginated) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/data-systems/{id}/decommission` | Decommission a system | PrivacyAdmin |
| POST | `/privacy/notices` | Create a draft notice | PrivacyAdmin |
| GET | `/privacy/notices` | List notices (paginated; filterable by `scope`, `status`, `supersedes_notice_id`, `superseded_by_notice_id`) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/notices/{id}` | Get one notice | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/notices/{id}/publish` | Publish a notice; supersedes declared target | PrivacyAdmin |
| POST | `/privacy/notices/{id}/retract` | Retract a published notice; restores superseded predecessor | PrivacyAdmin |
| POST | `/privacy/state-law-rules` | Create a state law rule | PrivacyAdmin |
| POST | `/privacy/vendors` | Create a vendor; risk tier computed | VendorManager |
| GET | `/privacy/vendors/{id}` | Get one vendor | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/vendors/{id}/submit-assessment` | Move vendor from onboarding to assessment | VendorManager |
| POST | `/privacy/vendors/{id}/approve` | Approve a vendor; requires an executed contract | PrivacyAdmin |
| POST | `/privacy/vendors/{id}/reject` | Reject a vendor | PrivacyAdmin |
| POST | `/privacy/vendors/{id}/offboard` | Offboard a vendor; contract and transfer cascade | PrivacyAdmin |
| POST | `/privacy/vendors/{id}/contracts` | Create a contract (OCC on vendor); supersedes draft/verified predecessors | VendorManager |
| GET | `/privacy/vendors/{id}/contracts` | List contracts of a vendor | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/contracts/{id}/verify` | Verify clause completeness | LegalCounsel |
| POST | `/privacy/contracts/{id}/execute` | Execute a verified contract | VendorManager |
| POST | `/privacy/processing-activities` | Create an activity; screening risk computed; auto-PIA when required | DataSteward |
| GET | `/privacy/processing-activities` | List activities (paginated; filterable by `status` and `vendor_id`) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/processing-activities/{id}` | Get one activity | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/processing-activities/{id}/activate` | Activate a draft activity (PIA gate and purpose presence) | DataSteward |
| POST | `/privacy/processing-activities/{id}/resume` | Resume a held activity; reinstates held transfers | DataSteward |
| POST | `/privacy/processing-activities/{id}/retire` | Retire an activity; suspends its approved transfers | DataSteward |
| POST | `/privacy/processing-activities/{id}/purposes` | Document a purpose with legal basis and retention linkage | DataSteward |
| GET | `/privacy/processing-activities/{id}/purposes` | List purposes of an activity | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/purposes/{id}` | Get one purpose | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/purposes` | List purposes filtered by foreign key (paginated) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/purposes/{id}/relink` | Re-link a consent-stale purpose to the current published notice | DataSteward |
| POST | `/privacy/purposes/{id}/retire` | Retire a purpose | DataSteward |
| POST | `/privacy/processing-activities/{id}/assessments` | Manually trigger a privacy impact assessment | DataSteward |
| GET | `/privacy/processing-activities/{id}/assessments` | List assessments of an activity | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/assessments/{id}` | Get one assessment | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/assessments/{id}/submit` | Submit an assessment for review | BusinessOwner |
| POST | `/privacy/assessments/{id}/approve` | Approve an assessment (segregation of duties); computes final score | LegalCounsel |
| POST | `/privacy/assessments/{id}/request-changes` | Request changes on an assessment (segregation of duties) | LegalCounsel |
| POST | `/privacy/assessments/{id}/reject` | Reject an assessment (segregation of duties) | LegalCounsel |
| POST | `/privacy/consumers` | Register a consumer | PrivacyAdmin |
| GET | `/privacy/consumers/{id}` | Get one consumer | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/consumers/{id}/rights-requests` | File a rights request for a consumer (self only) | Consumer |
| GET | `/privacy/consumers/{id}/rights-requests` | List a consumer's requests (self or staff) | Consumer, PrivacyAdmin, DataSteward, LegalCounsel |
| GET | `/privacy/rights-requests/{id}` | Get one request (self or staff) | Consumer, PrivacyAdmin, DataSteward, LegalCounsel |
| POST | `/privacy/rights-requests/{id}/verify` | Verify a request; computes final deadline | DataSteward |
| POST | `/privacy/rights-requests/{id}/fail-verification` | Fail verification; denies the request | DataSteward |
| POST | `/privacy/rights-requests/{id}/route` | Route a verified request; fans out tasks per selector | DataSteward |
| POST | `/privacy/rights-requests/{id}/deny` | Deny a request; cancels open tasks | LegalCounsel |
| POST | `/privacy/rights-requests/{id}/respond` | Respond to a request once tasks are done | DataSteward |
| GET | `/privacy/rights-requests/{id}/tasks` | List tasks of a request | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/tasks/{id}` | Get one task | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/tasks` | List tasks filtered by foreign key (paginated) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/tasks/{id}/start` | Start a pending task | DataSteward |
| POST | `/privacy/tasks/{id}/complete` | Complete an in-progress task | DataSteward |
| POST | `/privacy/transfers` | Propose a cross-border transfer | PrivacyAdmin |
| GET | `/privacy/transfers` | List transfers filtered by foreign key (paginated) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/transfers/{id}` | Get one transfer | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| POST | `/privacy/transfers/{id}/assess` | Move a proposed transfer into assessment | LegalCounsel |
| POST | `/privacy/transfers/{id}/approve` | Approve a transfer (adequacy, contract, and buffer gates) | LegalCounsel |
| POST | `/privacy/transfers/{id}/reject` | Reject a transfer | LegalCounsel |
| POST | `/privacy/applicability-evaluations/run` | Run threshold monitoring across all state law rules | PrivacyAdmin |
| GET | `/privacy/applicability-evaluations` | List evaluations (paginated, filterable) | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |
| GET | `/privacy/applicability-evaluations/{id}` | Get one evaluation | PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_REQUEST_NOT_VERIFIED` | 409 |
| `ERR_ACTIVITY_RETIRED` | 409 |
| `ERR_TASKS_OUTSTANDING` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MECHANISM_NOT_ADEQUATE` | 422 |
| `ERR_PIA_NOT_APPROVED` | 409 |
| `ERR_NO_PUBLISHED_NOTICE` | 422 |
| `ERR_ELEMENT_RETIRED` | 422 |
| `ERR_VENDOR_NOT_APPROVED` | 422 |
| `ERR_SYSTEM_DECOMMISSIONED` | 422 |
| `ERR_CONTRACT_NOT_EXECUTED` | 422 |
| `ERR_NO_EXECUTED_CONTRACT` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_NOTICE_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_TRANSFER_WINDOW_CONFLICT` | 409 |
| `ERR_OPEN_ASSESSMENT_EXISTS` | 409 |
| `ERR_NO_SYSTEMS_IN_SCOPE` | 422 |
| `ERR_NO_DOCUMENTED_PURPOSE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
