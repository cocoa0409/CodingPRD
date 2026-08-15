# Life Insurance Claims API — Product Requirements Document

## 1. Introduction

When an insured dies, the claims department of a life insurer inherits a bundle of obligations that are at once financial, evidentiary, and statutory. A death claim must be notified and substantiated with proof-of-death documentation; policies still inside their contestability window demand a deeper underwriting review that can end in rescission; beneficiary designations must be honored precisely as written, and competing claims to the same proceeds must be frozen, adjudicated, or referred to a court through interpleader. State law adds its own pressure: interest accrues on delayed payment under per-state statutes, proceeds that go unclaimed must be reconciled against the death master file, and dormant money must ultimately be escheated to the state. Each of these duties carries deadlines, dollar-amount computations, and audit trails that a manual process handles poorly.

This document specifies an API that operates that entire lifecycle for a life insurer's claims organization. It covers the configuration of per-state claims statutes, the issuance and lapsing of policies together with their beneficiary designations, the intake and adjudication of death claims, the filing and validation of beneficiary claims with their dispute cascades, the election of settlement options — lump sum or a retained asset account — and the dormancy-driven escheatment workflow that closes out unclaimed proceeds. The system is built for a regulated environment: duties are segregated between the examiner who works a claim and the approver who decides it, every mutation is versioned for audit, and a controllable logical clock drives all date-sensitive behavior so that interest accrual, election windows, and dormancy deadlines are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly six roles. A `ClaimsExaminer` handles claims intake and review: filing death claims, uploading and reviewing proof-of-death documents, filing and validating beneficiary claims, and recording settlement elections. A `ClaimsApprover` holds decision authority: approving, denying, or rescinding claims, executing payment, and authorizing retained-asset withdrawals. A `PolicyAdministrator` administers policies and beneficiary designations. A `LegalCounsel` operator manages legal escalation through interpleader referral. A `ComplianceOfficer` performs regulatory operations: statute configuration, death-master-file matching, and escheatment. A `SystemAdmin` performs test-driving operations through logical clock control.

For all six roles — `ClaimsExaminer`, `ClaimsApprover`, `PolicyAdministrator`, `LegalCounsel`, `ComplianceOfficer`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for authorship — for example as `assigned_examiner_id` on a claim, or as `uploaded_by_id` and `reviewed_by_id` on a document — and segregation-of-duties checks compare those recorded identifiers against the caller's `X-User-ID`, but `X-User-ID` is never itself the `id` of a stored entity.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. Many list endpoints additionally accept resource-scoped filter parameters (for example, a status filter); the filters available on each collection are noted with that collection's workflow in Section 3.

### 2.4. The Logical Clock and Scheduled Sweeps

All date and time sensitivity in the system is governed by a server-side logical clock, never by wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `SystemAdmin` may set the logical clock through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc` value.

Setting the clock triggers the system's time-based sweep, which always runs its two phases in a fixed order. First, retained-asset dormancy is evaluated: accounts whose last activity lies strictly more than the governing statute's dormancy period in the past flip from `OPEN` to `DORMANT`, each spawning an escheatment case. Second, escheatment-case progression is evaluated: cases in `MONITORING` whose due-diligence start has been reached advance to `DUE_DILIGENCE`. Every date the system stamps onto a resource — a claim's `notification_date` and `approved_at`, a policy's `lapse_date`, a designation's `revoked_at`, an election's `elected_at`, an account's `last_activity_at` — is read from this logical clock.

### 2.5. Common Resource Properties

All primary resources — policies, beneficiary designations, claims, death documents, beneficiary claims, payout elections, retained asset accounts, death master matches, and escheatment cases — share a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, marking creation and last modification respectively. The `version` is a system-managed integer that increments by one with every mutation of the resource, including mutations produced by automatic cascades, and it anchors the optimistic concurrency controls described in §2.8. A mutation that touches several resources — a cascade that disputes a beneficiary claim and places its claim on legal hold, for instance — refreshes `updated_at` and increments `version` on each resource it mutates.

State statutes are the deliberate exception. A `StateStatute` is configuration data carrying only `id` and `created_at`; it has no `updated_at` and no `version`, and statute records are never mutated through the API once created.

### 2.6. Monetary Precision and Rate Conventions

Every monetary amount in the system is carried as an integer number of cents — field names ending in `_cents` follow this convention without exception. Interest rates are expressed in basis points, where ten thousand basis points equal one hundred percent; applying a rate means dividing the basis-point figure by ten thousand. All interest results are rounded half-up to whole cents — a half-cent rounds up. Day-count conventions are fixed: statutory delay interest and the retained-asset statement estimate both use a 365-day year, while the retained-asset final yield compounds monthly, twelve compoundings per year. Where a statute or account offers both a provisional and a final figure, the two are computed by different methods and are expected to diverge for identical balances; that divergence is intentional and is detailed with the account workflow in §3.9.

### 2.7. Statute Resolution and Cross-Aggregate References

The claims rules of each state live in a `StateStatute` record keyed by its two-letter `state_code`, with at most one statute per state. A policy's `state_code` is a plain reference, not a foreign key with referential actions; it is resolved cross-aggregate at claim time. When a claim is filed, the claim snapshots the policy's `state_code`, and every statutory question for that claim — the interest rate and its accrual basis, the grace period, the payment deadline, the dormancy period, the retained-asset minimum and credit rate — is answered by resolving the statute whose `state_code` matches. Filing a claim against a policy whose state has no configured statute is rejected with `ERR_STATUTE_NOT_CONFIGURED` (HTTP 422).

### 2.8. Optimistic Concurrency Control

Two write operations in the system carry a mandatory version field, and no other endpoint accepts one. First, recording a settlement election for a beneficiary claim requires the request to carry `expected_claim_version`, holding the claim `version` the client last observed. Because creating an election legitimately supersedes the beneficiary's prior election, a writer holding a stale claim version would supersede a choice it never saw; if `expected_claim_version` does not match the claim's current `version`, the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). Second, adding a beneficiary designation to a policy requires `expected_policy_version`, holding the policy `version` the client last observed. Because every designation creation or revocation restructures the policy's beneficiary pool and increments the policy's `version`, a stale writer would allocate shares against a pool composition it never saw; a mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). These checks evaluate against the version current at the moment of the write, independent of when any other request may have run.

### 2.9. Segregation of Duties

Decision authority is deliberately separated from casework. The operator who approves, denies, or rescinds a claim must not be the examiner who filed it: on each of those three actions the caller's `X-User-ID` is compared against the claim's `assigned_examiner_id`, and equality is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). The same separation governs evidence: the examiner who reviews a proof-of-death document must not be the operator who uploaded it, so the reviewer's `X-User-ID` is compared against the document's `uploaded_by_id`, with equality likewise rejected as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

### 2.10. Validation Evaluation Order

When several checks could reject the same request, the server applies them in a fixed priority order so that the surfaced error is deterministic. The order is:

1. Header presence and role recognition (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Request body shape — required fields present, enum values inside their domains, integers positive where required (`face_amount_cents` and `amount_cents` must be greater than zero; `share_percent` must be greater than zero, at most 100, and carry at most two decimal places) — rejected as `ERR_INVALID_REQUEST`.
4. Existence of every path and body resource identifier, validated left to right, producing the resource-specific 404 errors listed in §2.12.
5. Optimistic concurrency checks where the endpoint takes a version field (`ERR_STALE_CLAIM_VERSION`, `ERR_STALE_POLICY_VERSION`).
6. State preconditions of the target resource (the per-resource 409 errors such as `ERR_CLAIM_NOT_REVIEWABLE` or `ERR_BENEFICIARY_CLAIM_INVALID_STATE`). Within this tier, when the claim sits in `LEGAL_HOLD`, `ERR_CLAIM_IN_LEGAL_HOLD` takes precedence over the generic review-state errors — an approval attempted during a hold surfaces the legal-hold error rather than `ERR_CLAIM_NOT_UNDER_REVIEW`.
7. Segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`).
8. The proof-of-death completeness check on approval (`ERR_REQUIRED_DOCS_INCOMPLETE`).
9. Temporal rules (`ERR_INVALID_DEATH_DATE`, `ERR_ELECTION_WINDOW_CLOSED`, `ERR_ESCHEATMENT_NOT_DUE`, `ERR_DESIGNATION_FROZEN_AFTER_CLAIM`).
10. Structural constraints (`ERR_DESIGNATION_WINDOW_OVERLAP`, `ERR_SHARE_TOTAL_EXCEEDED`, `ERR_DESIGNATION_ALREADY_CLAIMED`, `ERR_ALLOCATION_CAPACITY_EXCEEDED`, `ERR_STATUTE_ALREADY_EXISTS`).
11. Referential integrity (`ERR_STATUTE_NOT_CONFIGURED`, `ERR_DESIGNATION_POLICY_MISMATCH`, `ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH`).
12. Fiscal floors and balances (`ERR_BELOW_RAA_MINIMUM`, `ERR_INSUFFICIENT_ACCOUNT_BALANCE`, `ERR_NO_PAYABLE_BENEFICIARIES`).

### 2.11. Cascading State Consistency

Consistency is immediate: every mutation and every cascade it triggers is visible in the same response and in all subsequent reads. Several operations in this domain propagate well beyond their target resource — a rival beneficiary filing disputes an existing claimant and places the whole claim on legal hold; a denial or rescission rejects every open beneficiary claim; an escheatment closes out claims, beneficiary claims, elections, and accounts together. Each resource a cascade touches is independently mutated: its state changes, its `updated_at` refreshes, and its `version` increments. The server may also transition a resource with no explicit client request against it when a stated criterion is met — the claim's automatic release from legal hold and the bubble-up to `PAID` once proceeds are fully distributed are both system-driven transitions of this kind.

### 2.12. Nested Resource Retrieval

Requests that carry several resource identifiers — whether in the path or the body — are validated left to right along the containment chain: policy first, then claim, then the document or beneficiary claim beneath it; designations, elections, accounts, matches, and cases each resolve their own identifier. The request is rejected at the first identifier that does not correspond to an existing resource, with the error naming that resource: `ERR_POLICY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_DESIGNATION_NOT_FOUND`, `ERR_BENEFICIARY_CLAIM_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, or `ERR_CASE_NOT_FOUND` (all HTTP 404). A document review under a non-existent claim therefore fails as `ERR_CLAIM_NOT_FOUND` before the document identifier is ever examined.

## 3. Business Logic & Workflows

### 3.1. Statutory Configuration and Policy Issuance

Before any claim can be filed in a state, a `ComplianceOfficer` must configure that state's claims statute. Statute creation accepts the two-letter `state_code` together with the full claims rulebook for the state: the `annual_interest_rate_bp` at which delayed-payment interest accrues, the `interest_basis` selecting the accrual start — either `DATE_OF_DEATH` or `PROOF_OF_LOSS_COMPLETE` — the `grace_days` that must elapse after the basis date before interest begins, the `payment_deadline_days` within which payment is statutorily due once the proof of loss is complete, the `dormancy_years` that unclaimed property may sit before escheatment comes due, the `raa_minimum_cents` floor for a retained-asset election, and the `raa_annual_interest_rate_bp` credited to retained asset accounts. Only one statute may exist per state; a second configuration for an already-configured `state_code` is rejected with `ERR_STATUTE_ALREADY_EXISTS`. The `payment_deadline_days` value is informational: it marks the number of days after a claim's proof-of-loss completion date by which payment is statutorily due, and the deadline is surfaced on the claim for tracking rather than enforced as a hard gate. The statute list view accepts a `state_code` filter.

A `PolicyAdministrator` issues policies. Issuance captures the carrier-assigned `policy_number`, which must be unique across all policies; the insured's full legal `insured_name` and date of birth `insured_dob`; the optional `insured_ssn_last4` and `insured_zip`, both defaulting to null and both consumed later by death-master matching; the two-letter `state_code` of issue; the `face_amount_cents`, which must be greater than zero; the coverage `issue_date`; and an optional `contestability_months` that defaults to 24 when omitted. A new policy stands in `ACTIVE` status. The policy list view accepts `status` and `state_code` filters.

A policy that ceases to be in force is lapsed by a `PolicyAdministrator`. Lapsing requires the policy to be `ACTIVE` — any other state is rejected with `ERR_POLICY_NOT_ACTIVE` — and stamps `lapse_date` with the logical clock date as the policy moves from `ACTIVE` to the terminal `LAPSED` state, incrementing the policy's `version` by one.

### 3.2. Beneficiary Designations and the Share Pool

While a policy is in force and still untouched by claims, the `PolicyAdministrator` builds its beneficiary structure. Adding a designation requires the policy to be `ACTIVE` (a lapsed policy rejects the operation with `ERR_POLICY_NOT_ACTIVE`) and takes `beneficiary_name`, a `beneficiary_type` of `PRIMARY` or `CONTINGENT`, a `share_percent` giving the share of proceeds — greater than zero, at most 100, with no more than two decimal places — and the `effective_date` from which the designation takes effect. Because each creation restructures the pool, the request must carry `expected_policy_version` per the optimistic concurrency rule in §2.8, and every successful creation increments the policy's `version` by one. A new designation stands in `ACTIVE` status. The designations of a policy can be listed with `status` and `beneficiary_type` filters.

Two structural rules protect the pool at creation time, evaluated after the temporal freeze rule described below per the ordering in §2.10. First, window exclusivity: a designation's active window is the half-open interval beginning on its `effective_date` (inclusive) and ending on the date of its `revoked_at` (exclusive), and designations sharing the same policy, the same `beneficiary_type`, and the same `beneficiary_name` may not have overlapping active windows — windows that merely touch, where one designation's revocation date equals another's effective date, are permitted, but genuine overlap is rejected with `ERR_DESIGNATION_WINDOW_OVERLAP`. Second, share capacity: the sum of `share_percent` across all `ACTIVE` designations of the same type on the policy, including the candidate, must not exceed 100, else the creation fails with `ERR_SHARE_TOTAL_EXCEEDED`.

Revocation by a `PolicyAdministrator` requires the designation to still be `ACTIVE` — revoking an already-revoked designation is rejected with `ERR_DESIGNATION_ALREADY_REVOKED` — and stamps `revoked_at` with the logical clock time as the designation moves from `ACTIVE` to `REVOKED`, again incrementing the policy's `version`. Both creation and revocation are frozen the moment a claim exists on the policy: from that point on, either operation is rejected with `ERR_DESIGNATION_FROZEN_AFTER_CLAIM`, because the beneficiary structure as of the insured's death must remain reconstructible.

### 3.3. Death-Master File Matching and Proactive Claim Generation

Insurers are expected to find deceased insureds, not merely wait for families to call. A `ComplianceOfficer` submits a death master file record against a policy, supplying the record's `deceased_name`, `deceased_dob`, and `deceased_death_date`, plus the optional `deceased_ssn_last4` and `deceased_zip`. On submission the system computes a `match_score` from zero to one hundred by exact string comparison against the stored policy fields. If both the record's `deceased_ssn_last4` and the policy's `insured_ssn_last4` are present and exactly equal, the score is 100 outright — the SSN match short-circuits the weighted computation. Otherwise the score is a weighted sum: 45 points when `deceased_name` equals the policy's `insured_name` exactly, 25 points when `deceased_dob` equals `insured_dob`, 15 points when both ZIP values are present and equal, and 15 points when both SSN last-four values are present and equal — a term that is unreachable in the weighted path precisely because an exact SSN match has already short-circuited to 100, and which is retained for specification symmetry.

The score bands drive the match's initial status. A score of 85 or higher is automatically `CONFIRMED` at creation; a score from 60 through 84 lands in `PENDING_REVIEW`; a score below 60 is automatically dismissed as `FALSE_POSITIVE`. A `ComplianceOfficer` may manually settle a pending match through review with a `review_outcome` of `CONFIRMED` or `FALSE_POSITIVE`; the manual path requires the match to still be in `PENDING_REVIEW`, else it is rejected with `ERR_MATCH_NOT_PENDING_REVIEW`. A policy's matches can be listed with a `status` filter.

Confirmation — whether automatic at creation or by manual review — generates a claim proactively. If the policy has no non-terminal claim, the system creates one in `NOTIFIED` status with `date_of_death` taken from the record's `deceased_death_date`, a null `assigned_examiner_id`, and a freshly computed contestability flag, and records it on the match as `generated_claim_id`. If a non-terminal claim already exists on the policy, auto-creation is skipped and `generated_claim_id` remains null.

### 3.4. Claim Intake and the Contestability Fork

The ordinary path begins when a `ClaimsExaminer` files a death claim. The filing body carries the `policy_id`, the insured's `date_of_death`, and an optional `cause_of_death`. The policy's state must have a configured statute, per §2.7, or the filing is rejected with `ERR_STATUTE_NOT_CONFIGURED`. The `date_of_death` must fall on or after the policy's `issue_date` and on or before the logical current date; a death date before issuance or in the future is rejected with `ERR_INVALID_DEATH_DATE`. A successfully filed claim stands in `NOTIFIED` status with its `notification_date` stamped from the logical clock, the filing examiner's `X-User-ID` recorded as `assigned_examiner_id` (the segregation-of-duties anchor for later decisions), and the policy's `face_amount_cents` and `state_code` snapshotted onto the claim so that later policy edits cannot rewrite the claim's basis. At filing, `accrued_interest_cents` starts at zero and `total_payable_cents` remains unset; both are first quantified at approval. Claims can be listed with `policy_id` and `status` filters.

Filing also computes the `contestability_flag`. The boundary date is the policy's `issue_date` advanced by `contestability_months` calendar months, preserving the day of month; a death strictly before that boundary renders the flag true, while a death exactly on the boundary date is not contestable and renders it false.

Routing into review is a fork on that flag. When a `ClaimsExaminer` begins review — allowed only from `NOTIFIED`, else `ERR_CLAIM_NOT_REVIEWABLE` — a claim whose `contestability_flag` is false moves to `UNDER_REVIEW`, while a contestable claim moves to `CONTESTABILITY_REVIEW`. Either way the claim's `version` increments by one.

### 3.5. Proof-of-Death Documentation and Review

Adjudication rests on evidence. A `ClaimsExaminer` uploads proof-of-death documents to a claim, choosing a `doc_type` from the supported document types: `CERTIFIED_DEATH_CERTIFICATE`, `ATTENDING_PHYSICIAN_STATEMENT`, and `FUNERAL_HOME_STATEMENT`. Each upload records the uploader's `X-User-ID` as `uploaded_by_id` and starts with `review_result` in `PENDING`. The documents of a claim can be listed with `review_result` and `doc_type` filters.

Review is performed by a different examiner than the uploader: reviewing one's own upload is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Only `PENDING` documents can be reviewed — acting on an already-decided document is rejected with `ERR_DOCUMENT_ALREADY_REVIEWED`. The review sets `review_result` to `VERIFIED` or `REJECTED`; a rejection must carry a `rejection_reason`, and its absence is an `ERR_INVALID_REQUEST`. The reviewing examiner is recorded as `reviewed_by_id`.

The required proof set depends on the claim's contestability posture: every claim needs at least one `VERIFIED` certified death certificate, and a claim whose `contestability_flag` is true additionally needs at least one `VERIFIED` attending physician statement. After every document review the claim's `proof_complete_date` is recomputed: if every required document type now has at least one `VERIFIED` document, the field is set to the logical clock date of the review that completed the set; otherwise it is null. A rejection can therefore clear a previously completed proof date, and `REJECTED` documents never count toward the set.

### 3.6. Adjudication: Approval, Denial, and Rescission

Approval belongs to a `ClaimsApprover` and is permitted from either `UNDER_REVIEW` or `CONTESTABILITY_REVIEW`; from any other state the attempt is rejected with `ERR_CLAIM_NOT_UNDER_REVIEW`, except that an approval attempted while the claim sits in `LEGAL_HOLD` surfaces `ERR_CLAIM_IN_LEGAL_HOLD`, the hold signal taking precedence per §2.10. The approver must not be the examiner recorded in `assigned_examiner_id` (§2.9), and the required proof set of §3.5 must be fully `VERIFIED` before approval — an incomplete set is rejected with `ERR_REQUIRED_DOCS_INCOMPLETE`.

Approval is the moment money is first quantified. The claim moves to `APPROVED` with `approved_at` stamped from the logical clock — the date that starts both the election window and, where relevant, the escheatment clock for claim proceeds. Statutory delay interest is then computed as of the approve date and stored as `accrued_interest_cents`, and `total_payable_cents` is set to the face amount plus that accrued interest.

The statutory interest computation works as follows. The claim's statute is resolved by its `state_code`, and the accrual basis date is chosen by the statute's `interest_basis`: the claim's `date_of_death` when the basis is `DATE_OF_DEATH`, or the claim's `proof_complete_date` when the basis is `PROOF_OF_LOSS_COMPLETE` — if proof is incomplete there is no basis date and accrual cannot start. The days elapsed are counted from the basis date to the as-of date, and the accrual days are the days elapsed beyond the statute's `grace_days`, floored at zero: on the day the elapsed count exactly equals the grace period, accrual is still zero. The interest is then the claim's `face_amount_cents` multiplied by the statute's `annual_interest_rate_bp`, divided by ten thousand, multiplied by the accrual days, and divided by 365, with the result rounded half-up to whole cents. Because the two basis variants start the clock on different dates, identical claim data yields more interest under the death basis than under the proof basis whenever death precedes proof completion. The same computation is re-run as of the payment date during payment execution, and it is run one final time as of the referral date at interpleader, where the accrued figure is frozen and accrual stops.

With the total fixed, the allocation waterfall distributes it among validated beneficiaries. The pool is selected by rank from the claim's beneficiary claims in `VALIDATED` status — claims in `SUBMITTED`, `DISPUTED`, `REJECTED`, `WITHDRAWN`, or `INTERPLEADED` never participate: if any validated claim references a `PRIMARY` designation, those claims form the pool; otherwise, if any references a `CONTINGENT` designation, those form the pool; otherwise, if an `ESTATE` claimant exists, the estate claims form the pool, each treated as holding a share of 100 — which the capacity rule of §3.7 guarantees can be at most one; otherwise the pool is empty and the proceeds stand unclaimed. For each pool member the raw share is the `total_payable_cents` multiplied by the member's `share_percent` and divided by 100, and each member's share is rounded half-up to whole cents first — the total itself is never rounded. The remainder, positive or negative, between the total and the sum of the rounded shares is assigned to the pool member with the highest `share_percent`; ties break to the earliest designation `effective_date`, then to the earliest designation creation timestamp. Pool members move from `VALIDATED` to `PAYABLE` carrying their `allocated_amount_cents`; validated claims outside the pool remain `VALIDATED`. When the pool is empty, approval additionally opens an escheatment case over the claim proceeds — `subject_type` `CLAIM_PROCEEDS`, status `MONITORING`, `trigger_date` set to the `approved_at` date, `amount_cents` snapshotting the unpaid proceeds — per the lifecycle in §3.9. Approval increments the claim's `version` by one.

Denial is the approver's negative decision, available from `UNDER_REVIEW` or `CONTESTABILITY_REVIEW` under the same state and segregation rules as approval. It requires a `denial_reason`, and it cascades: every beneficiary claim of this claim in `SUBMITTED`, `VALIDATED`, or `DISPUTED` is rejected with `rejection_reason` set to `CLAIM_DENIED`. Rescission is the contestability outcome for material misrepresentation, available only from `CONTESTABILITY_REVIEW` — from any other state it is rejected with `ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW` — again under segregation of duties. It requires a `rescission_reason` and cascades identically, except that open beneficiary claims are rejected with `rejection_reason` set to `POLICY_RESCINDED`. Both decisions are terminal — `DENIED` and `RESCINDED` respectively — and each increments the claim's `version`.

### 3.7. Competing Beneficiaries, Legal Hold, and Interpleader

Anyone asserting rights to proceeds files a beneficiary claim against the claim. A `ClaimsExaminer` files it with a `claimant_name`, a `claimant_type` of `NAMED_BENEFICIARY` or `ESTATE`, and — for a named beneficiary — the `designation_id` of the designation being claimed; the `designation_id` is null only for estate claimants, and a supplied identifier that does not resolve is rejected with `ERR_DESIGNATION_NOT_FOUND`. The parent claim must be non-terminal — filing against a closed claim is rejected with `ERR_CLAIM_NOT_FILEABLE` — and must not be sitting in `LEGAL_HOLD`, which rejects the filing with `ERR_CLAIM_IN_LEGAL_HOLD`. The filing itself is always accepted into `SUBMITTED` status.

The dispute cascade fires at filing time. If a rival beneficiary claim on the same designation already stands `VALIDATED` or `PAYABLE` under a different `claimant_name`, the rival — not the new filing — is cascaded to `DISPUTED`, its `version` incrementing, and the parent claim is placed in `LEGAL_HOLD`: the claim records its pre-hold state in `hold_return_state` (one of `UNDER_REVIEW`, `CONTESTABILITY_REVIEW`, or `APPROVED`), every payout election of the claim's beneficiary claims in `ELECTED` or `CONFIRMED` is suspended to `SUSPENDED`, and the claim's `version` increments.

Validation is the dispute-resolution path. A `ClaimsExaminer` validates a beneficiary claim from `SUBMITTED` or `DISPUTED` — any other state is rejected with `ERR_BENEFICIARY_CLAIM_INVALID_STATE`. The parent claim must still be non-terminal (`ERR_CLAIM_NOT_FILEABLE`), but a legal hold does not block validation, precisely because validation is how disputes get resolved. When the claim references a designation, two referential checks apply, both at filing and at validation: the designation must belong to the same policy as the claim, else `ERR_DESIGNATION_POLICY_MISMATCH`, and the designation must have been active on the claim's `date_of_death` — the death occurring on or after the designation's `effective_date` and, where the designation has been revoked, strictly before the revocation date — else `ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH`. Exclusivity follows: no other beneficiary claim in `VALIDATED` or `PAYABLE` may already hold the same designation, else `ERR_DESIGNATION_ALREADY_CLAIMED`. Finally, aggregate capacity caps the whole claim: the sum of shares across the beneficiary claims in `VALIDATED` or `PAYABLE` plus the candidate — each share being its designation's `share_percent`, or 100 for an `ESTATE` claimant — must not exceed 100, else validation is rejected with `ERR_ALLOCATION_CAPACITY_EXCEEDED`; the estate's share of 100 is what guarantees at most one validated estate claimant per claim. Successful validation moves the beneficiary claim to `VALIDATED` and increments its `version`.

Rejection and withdrawal close a beneficiary claim out. Rejection by a `ClaimsExaminer` is permitted from `SUBMITTED`, `VALIDATED`, or `DISPUTED` and stores a required `rejection_reason`. Withdrawal is permitted from `SUBMITTED` or `DISPUTED`. From any other status, either action is rejected with `ERR_BENEFICIARY_CLAIM_INVALID_STATE`.

The legal hold releases automatically: whenever no beneficiary claim of the claim remains in `DISPUTED` — because rivals were validated, rejected, or withdrawn — the claim returns to the state recorded in `hold_return_state`, the field is cleared to null, every election suspended by the hold returns from `SUSPENDED` to `ELECTED` and must be re-confirmed, and the claim's `version` increments. When the recorded return state is `APPROVED`, the allocation waterfall of §3.6 re-runs so that the validated pool members return to `PAYABLE` with recomputed `allocated_amount_cents`; the hold never touched `total_payable_cents`, so the restored allocations match the pre-hold amounts exactly.

When competition cannot be settled internally, a `LegalCounsel` refers the claim to court through interpleader. Referral requires the claim to be in `LEGAL_HOLD` — from any other state it is rejected with `ERR_CLAIM_NOT_IN_LEGAL_HOLD` — and requires a `court_reference`. The claim moves to the terminal `INTERPLEADED` state, accrued interest is recomputed as of the referral date and frozen there, every beneficiary claim still in `DISPUTED` moves to `INTERPLEADED`, every payout election of the claim in `ELECTED`, `CONFIRMED`, or `SUSPENDED` is superseded to `SUPERSEDED`, and the claim's `version` increments.

Beneficiary claims are queryable in two list views: the claims-scoped view accepts a `status` filter and is ordered by creation ascending, and the global view accepts `claim_id`, `designation_id`, and `status` filters.

### 3.8. Settlement Elections and Payment Execution

Once a beneficiary claim stands `PAYABLE`, its settlement option is recorded as a payout election. A `ClaimsExaminer` creates the election with an `option` of `LUMP_SUM` or `RETAINED_ASSET_ACCOUNT`; the request must carry `expected_claim_version` per §2.8, and a stale version is rejected with `ERR_STALE_CLAIM_VERSION`. Election requires the beneficiary claim to be `PAYABLE` — else `ERR_BENEFICIARY_CLAIM_NOT_PAYABLE` — and the claim to be `APPROVED`; attempting an election while the claim is under a legal hold surfaces `ERR_CLAIM_IN_LEGAL_HOLD`, while any other non-approved state surfaces `ERR_CLAIM_NOT_APPROVED`. The election window is thirty days: the logical clock date must be on or before the claim's `approved_at` plus 30 days, and a late election is rejected with `ERR_ELECTION_WINDOW_CLOSED`. Choosing the retained-asset option additionally requires the beneficiary claim's `allocated_amount_cents` to be at least the statute's `raa_minimum_cents`, else the election is rejected with `ERR_BELOW_RAA_MINIMUM`. A created election stands in `ELECTED` status with `elected_at` stamped from the logical clock, and creating it supersedes the beneficiary's prior election: every previous election of that beneficiary claim not already `SUPERSEDED` moves to `SUPERSEDED`. Election creation increments the claim's `version` by one.

Confirmation locks the choice in. Confirming an election requires it to still be `ELECTED` — else `ERR_ELECTION_NOT_CONFIRMABLE` — and the same thirty-day window applies at confirmation, with a closed window rejected as `ERR_ELECTION_WINDOW_CLOSED`. Confirmation stamps `confirmed_at` and moves the election to `CONFIRMED`. The elections of a beneficiary claim can be listed with a `status` filter.

Payment execution, performed by a `ClaimsApprover`, distributes the proceeds. The claim must be `APPROVED` — a claim under legal hold rejects the execution with `ERR_CLAIM_IN_LEGAL_HOLD`, and any other non-approved state with `ERR_CLAIM_NOT_APPROVED`. Execution first recomputes the statutory interest of §3.6 as of the payment date, refreshes `total_payable_cents` to the face amount plus the recomputed interest, and re-runs the allocation waterfall so every pool member's `allocated_amount_cents` reflects the final total. There must be at least one beneficiary claim in `PAYABLE` holding a `CONFIRMED` election, else the execution is rejected with `ERR_NO_PAYABLE_BENEFICIARIES`. Each payable beneficiary claim holding a confirmed election is then paid in beneficiary-claim creation order, oldest first: a `LUMP_SUM` election disburses the allocation directly, while a `RETAINED_ASSET_ACCOUNT` election funds a new retained asset account that opens in `OPEN` status with its `deposited_cents` and `balance_cents` both set to the disbursed amount, `withdrawn_total_cents` at zero, and `last_activity_at` stamped from the logical clock. Either way the beneficiary claim's `paid_amount_cents` is set to its final, post-recompute `allocated_amount_cents` and it moves to `PAID`, its `version` incrementing. When every beneficiary claim in `PAYABLE` standing has reached `PAID` and the sum of the disbursed amounts equals the claim's `total_payable_cents`, the claim itself bubbles up to `PAID`, stamping `paid_at` from the logical clock and incrementing the claim's `version`.

### 3.9. Retained Asset Accounts, Dormancy, and Escheatment

A retained asset account keeps a beneficiary's proceeds on the insurer's books, credited with interest, until withdrawn or escheated. The account records the `claim_id` whose proceeds funded it and the `beneficiary_claim_id` whose election created it; its `deposited_cents` preserve the initial deposit — the beneficiary claim's allocated amount at funding — and are immutable, while `balance_cents` tracks the current principal. Two interest figures coexist by design. The `provisional_interest_cents` field is a statement estimate recomputed on every read: simple interest on the current `balance_cents` at the statute's `raa_annual_interest_rate_bp` for the number of days the account has been open — the logical current date minus the creation date — over a 365-day year, rounded half-up to whole cents. The `interest_paid_cents` field stays zero until the account closes or escheats, when the final yield is posted. Accounts can be listed with `claim_id`, `beneficiary_claim_id`, and `status` filters.

Withdrawals are drafts against the account, authorized by a `ClaimsApprover`. The account must be `OPEN` or `DORMANT` — a closed or escheated account rejects the withdrawal with `ERR_ACCOUNT_NOT_WITHDRAWABLE` — the `amount_cents` must be greater than zero (`ERR_INVALID_REQUEST`), and it must not exceed the current `balance_cents`, else `ERR_INSUFFICIENT_ACCOUNT_BALANCE`. A successful withdrawal reduces `balance_cents` by the amount, adds it to `withdrawn_total_cents`, and stamps `last_activity_at` from the logical clock. A withdrawal against an `OPEN` account leaves it `OPEN`; a withdrawal against a `DORMANT` account reactivates it to `OPEN`, and the escheatment case linked to that account, if still open in `MONITORING` or `DUE_DILIGENCE`, is automatically resolved with `resolution_note` set to `OWNER_ACTIVITY`. A withdrawal that reduces the balance to exactly zero closes the account: the final compound yield is posted as `interest_paid_cents` and paid out together with the final withdrawal, and the account moves to the terminal `CLOSED` state.

The final yield compounds monthly. The compounding period count is the number of complete calendar months between the account's creation date and its closing or escheat date, where a month completes on the same day of month as the creation day and any residual days earn nothing. The posted interest is the closing balance multiplied by the growth factor — one plus the monthly rate, the monthly rate being the statute's `raa_annual_interest_rate_bp` divided by ten thousand and then by twelve, raised to the power of the complete-month count, with one subtracted — rounded half-up to whole cents. Because the provisional figure is simple interest on the current balance while the final figure compounds over complete months, the two diverge for identical balances, and only the final figure is ever posted.

Dormancy is enforced by the clock sweep of §2.4. When the logical current date passes the account's `last_activity_at` by strictly more than the statute's `dormancy_years` calendar years — a date exactly equal to the anniversary leaves the account `OPEN` — the account flips from `OPEN` to `DORMANT`, and the system opens an escheatment case over it with `subject_type` `RETAINED_ASSET_ACCOUNT`, status `MONITORING`, and `trigger_date` set to the date of the account's last activity.

Escheatment cases are the system's unclaimed-property ledger. Every case records the `claim_id` it belongs to; an `account_id` is present when the `subject_type` is `RETAINED_ASSET_ACCOUNT` and null when it is `CLAIM_PROCEEDS`; and the `state_code` is copied from the claim, since the state's `dormancy_years` governs the schedule. The `trigger_date` marks when the dormancy clock started — the claim's `approved_at` for proceeds cases, the account's last-activity date for account cases. The `escheat_due_date` is the trigger date advanced by the statute's dormancy period in calendar years, and the `due_diligence_start_date` is 120 days before the due date. The `amount_cents` snapshots the unpaid proceeds — the claim's `total_payable_cents` less amounts already paid — at creation for a proceeds case, and is finalized at escheat for an account case. As the sweep runs, a case in `MONITORING` advances to `DUE_DILIGENCE` once the logical date reaches the due-diligence start, on or after that date. Cases can be listed with `claim_id`, `account_id`, `status`, and `subject_type` filters.

Resolution and escheatment are the `ComplianceOfficer`'s two dispositions. Resolving a case requires it to be in `MONITORING` or `DUE_DILIGENCE` — otherwise `ERR_CASE_NOT_ACTIONABLE` — stores an optional `resolution_note`, and moves the case to the terminal `RESOLVED` state; when the subject is a retained asset account, the account also reactivates from `DORMANT` to `OPEN` with `last_activity_at` refreshed. Escheating a case requires it to be in `DUE_DILIGENCE` (`ERR_CASE_NOT_ACTIONABLE`) and the logical clock date to be on or after the `escheat_due_date` — an early remittance is rejected with `ERR_ESCHEATMENT_NOT_DUE`. For a proceeds case, escheatment finalizes `amount_cents` as the claim's total payable less the sum already paid, moves the claim from `APPROVED` to the terminal `ESCHEATED` state, and cascades: beneficiary claims in `VALIDATED` or `PAYABLE` move to `ESCHEATED`, and elections in `ELECTED`, `CONFIRMED`, or `SUSPENDED` move to `SUPERSEDED`, with the claim's `version` incrementing. For an account case, escheatment posts the final compound yield as of the escheat date, sets `amount_cents` to the balance plus that interest as the amount remitted to the state, and moves the account from `DORMANT` to the terminal `ESCHEATED` state.

## 4. Endpoint Definitions

All collections are mounted at the API root; there is no global path prefix. Operations that create a new resource — issuing a policy, configuring a statute, filing a claim, uploading a document, adding a designation, filing a beneficiary claim, recording an election, submitting a death master match — return `201 Created` with the new resource in the response. Operations that modify an existing resource in place — state transitions, reviews, decisions, withdrawals, sweeps — return `200 OK` with the updated resource. Request payloads and cascaded side effects for each operation are specified by the workflows in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock; triggers the time-based sweep | SystemAdmin |
| POST | `/state-statutes` | Configure a state's claims statute | ComplianceOfficer |
| GET | `/state-statutes` | List statutes | All roles |
| POST | `/policies` | Issue a policy | PolicyAdministrator |
| GET | `/policies` | List policies | All roles |
| GET | `/policies/{policyId}` | Get a policy | All roles |
| POST | `/policies/{policyId}/lapse` | Lapse an active policy | PolicyAdministrator |
| POST | `/policies/{policyId}/beneficiary-designations` | Add a beneficiary designation (OCC-guarded on the policy version) | PolicyAdministrator |
| GET | `/policies/{policyId}/beneficiary-designations` | List designations of a policy | All roles |
| POST | `/beneficiary-designations/{designationId}/revoke` | Revoke a designation | PolicyAdministrator |
| POST | `/claims` | File a death claim | ClaimsExaminer |
| GET | `/claims` | List claims | All roles |
| GET | `/claims/{claimId}` | Get a claim | All roles |
| POST | `/claims/{claimId}/begin-review` | Route the claim into review, forking on contestability | ClaimsExaminer |
| POST | `/claims/{claimId}/approve` | Approve the claim; compute interest and run the allocation waterfall | ClaimsApprover |
| POST | `/claims/{claimId}/deny` | Deny the claim | ClaimsApprover |
| POST | `/claims/{claimId}/rescind` | Rescind the policy from contestability review | ClaimsApprover |
| POST | `/claims/{claimId}/refer-interpleader` | Refer competing claims to court via interpleader | LegalCounsel |
| POST | `/claims/{claimId}/execute-payment` | Pay payable beneficiaries holding confirmed elections | ClaimsApprover |
| POST | `/claims/{claimId}/documents` | Upload a proof-of-death document | ClaimsExaminer |
| GET | `/claims/{claimId}/documents` | List documents of a claim | All roles |
| POST | `/claims/{claimId}/documents/{documentId}/review` | Verify or reject a document | ClaimsExaminer |
| POST | `/claims/{claimId}/beneficiary-claims` | File a beneficiary claim | ClaimsExaminer |
| GET | `/claims/{claimId}/beneficiary-claims` | List beneficiary claims of a claim | All roles |
| GET | `/beneficiary-claims` | List beneficiary claims across claims | All roles |
| GET | `/beneficiary-claims/{beneficiaryClaimId}` | Get a beneficiary claim | All roles |
| POST | `/beneficiary-claims/{beneficiaryClaimId}/validate` | Validate a beneficiary claim | ClaimsExaminer |
| POST | `/beneficiary-claims/{beneficiaryClaimId}/reject` | Reject a beneficiary claim | ClaimsExaminer |
| POST | `/beneficiary-claims/{beneficiaryClaimId}/withdraw` | Withdraw a beneficiary claim | ClaimsExaminer |
| POST | `/beneficiary-claims/{beneficiaryClaimId}/elections` | Record a settlement-option election (OCC-guarded on the claim version) | ClaimsExaminer |
| GET | `/beneficiary-claims/{beneficiaryClaimId}/elections` | List elections of a beneficiary claim | All roles |
| POST | `/payout-elections/{electionId}/confirm` | Confirm an election within the election window | ClaimsExaminer |
| GET | `/retained-asset-accounts` | List retained asset accounts | All roles |
| GET | `/retained-asset-accounts/{accountId}` | Get an account; provisional interest recomputed on read | All roles |
| POST | `/retained-asset-accounts/{accountId}/withdrawals` | Draft against the account | ClaimsApprover |
| POST | `/policies/{policyId}/death-master-matches` | Submit a death master file record for matching | ComplianceOfficer |
| GET | `/policies/{policyId}/death-master-matches` | List death master matches of a policy | All roles |
| POST | `/death-master-matches/{matchId}/review` | Manually confirm or dismiss a pending match | ComplianceOfficer |
| GET | `/escheatment-cases` | List escheatment cases | All roles |
| GET | `/escheatment-cases/{caseId}` | Get an escheatment case | All roles |
| POST | `/escheatment-cases/{caseId}/resolve` | Resolve a case (owner located or owner activity) | ComplianceOfficer |
| POST | `/escheatment-cases/{caseId}/escheat` | Remit unclaimed proceeds to the state | ComplianceOfficer |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return and its HTTP status. The conditions that trigger each error are specified in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DESIGNATION_NOT_FOUND` | 404 Not Found |
| `ERR_BENEFICIARY_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_ELECTION_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_MATCH_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CLAIM_VERSION` | 412 Precondition Failed |
| `ERR_STALE_POLICY_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW` | 409 Conflict |
| `ERR_CLAIM_IN_LEGAL_HOLD` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_LEGAL_HOLD` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_CLAIM_NOT_FILEABLE` | 409 Conflict |
| `ERR_DOCUMENT_ALREADY_REVIEWED` | 409 Conflict |
| `ERR_BENEFICIARY_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_BENEFICIARY_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_ELECTION_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_CASE_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_MATCH_NOT_PENDING_REVIEW` | 409 Conflict |
| `ERR_DESIGNATION_ALREADY_REVOKED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_REQUIRED_DOCS_INCOMPLETE` | 409 Conflict |
| `ERR_INVALID_DEATH_DATE` | 422 Unprocessable Entity |
| `ERR_ELECTION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ESCHEATMENT_NOT_DUE` | 409 Conflict |
| `ERR_DESIGNATION_FROZEN_AFTER_CLAIM` | 409 Conflict |
| `ERR_DESIGNATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SHARE_TOTAL_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DESIGNATION_ALREADY_CLAIMED` | 409 Conflict |
| `ERR_ALLOCATION_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STATUTE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_STATUTE_NOT_CONFIGURED` | 422 Unprocessable Entity |
| `ERR_DESIGNATION_POLICY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH` | 422 Unprocessable Entity |
| `ERR_BELOW_RAA_MINIMUM` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ACCOUNT_BALANCE` | 422 Unprocessable Entity |
| `ERR_NO_PAYABLE_BENEFICIARIES` | 422 Unprocessable Entity |
