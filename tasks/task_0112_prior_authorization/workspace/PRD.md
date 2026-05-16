# Prior Authorization API — Product Requirements Document

## 1. Introduction

Health plans require advance approval — prior authorization — before paying for a growing list of services, drugs, and devices. The process is paperwork-heavy and time-sensitive: a single denial can interrupt a treatment regimen, and a delayed decision can keep a patient out of a specialty clinic for weeks. This document specifies the Prior Authorization API, a backend system that mediates the end-to-end negotiation between requesting providers and the payer's clinical reviewers.

The API governs the full lifecycle of an authorization request — from a provider's initial draft, through clinical-evidence upload and (optionally) a peer-to-peer call, to a final decision that either approves a measurable quantity of units or denies the request with a coded reason. Denials are appealable along a three-tier ladder of escalating reviewer authority, and approvals carry an explicit expiration that the system sweeps automatically. Resubmissions of expired authorizations carry forward prior evidence with a measured reuse discount, balancing reviewer efficiency against the imperative that each new request stand on its own clinical merit.

Throughout, the system mediates competing concerns: the payer's interest in evidence-supported decisions, the provider's interest in fast turnaround for expedited cases, and a shared interest in version-pinned, audit-friendly history. This document specifies the contract every implementer must satisfy so that conformant servers can be tested interchangeably.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two identity headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the call is being made. Requests missing or malformed in either header are rejected with `ERR_AUTH_MISSING` and HTTP 401. When a caller's role does not include the requested operation in the RBAC matrix, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

The system recognizes six roles: `PlatformAdmin`, `Provider`, `InitialReviewer`, `MedicalDirector`, `ExternalReviewer`, and `PayerReviewer`.

The interpretation of `X-User-ID` depends on the role:

- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity. Ownership checks on any resource that references a `Provider` (for example, an `AuthorizationRequest` whose `provider_id` identifies the requesting practice) compare the resource's foreign-key field to `X-User-ID`. A `Provider` may only act on, and may only list, authorization requests whose `provider_id` equals `X-User-ID`.
- When `X-User-Role` is `PlatformAdmin`, `InitialReviewer`, `MedicalDirector`, `ExternalReviewer`, or `PayerReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes (for example, as `payer_reviewer_id` on a `PeerToPeerReview` when a transition writes it) but does not compare it to any entity's `id`. Each of these five roles is governed only by the RBAC matrix and by role-specific business rules (notably tier-matching on appeals).

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

The `meta` object of every list response includes the four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Audit Fields

Almost every primary, top-level resource — `Patient`, `Provider`, `ServiceCatalogItem`, `AuthorizationRequest`, `PeerToPeerReview`, and `Appeal` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID without any type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 on creation and increments by one on every mutation. This field is the basis for the optimistic concurrency control mechanism described in §2.6.

Two entities are deliberate exceptions to this template: `ClinicalEvidence` and `Decision`. These resources are append-only — `ClinicalEvidence` is created in `ATTACHED` status and may only transition to `WITHDRAWN`; `Decision` is immutable history. Both carry `id` and `created_at` but omit both `updated_at` and `version`.

### 2.5. Cascading Status Alignment Across the Authorization Hierarchy

An `AuthorizationRequest` is the root of a small hierarchy: it owns its `ClinicalEvidence` rows, its `PeerToPeerReview` rows, its `Decision` rows, and its `Appeal` rows. When a state transition fires anywhere in this tree, the system aligns related resources atomically.

The principal cascades the implementer must honor are:

- Withdrawing an authorization that has a `SCHEDULED` peer-to-peer review cancels that review, transitioning the `PeerToPeerReview.status` from `SCHEDULED` to `CANCELLED`.
- Completing a peer-to-peer review (`SCHEDULED → COMPLETED`) returns the parent authorization from `PEER_REVIEW` to `UNDER_REVIEW`.
- Cancelling a peer-to-peer review (`SCHEDULED → CANCELLED`) likewise returns the parent authorization from `PEER_REVIEW` to `UNDER_REVIEW`.
- An overturned appeal cascades back to the parent authorization, flipping it from `DENIED` to `APPROVED` and producing a new superseding `Decision`.

Every cascade is a real mutation on each affected resource: the resource's `updated_at` is refreshed and its `version` is incremented by one. For resources that omit these fields (notably `ClinicalEvidence` and `Decision`), only the underlying state change is recorded; no version bump occurs because the resource has no `version` field to bump.

### 2.6. Optimistic Concurrency Control

Any state-change endpoint that targets a specific resource by id, and the `PATCH` endpoints that modify a resource's payload, accept an optional `version` field in the request body. When the client includes `version`, the server compares it to the resource's current `version`; if they differ, the request is rejected with `ERR_VERSION_MISMATCH` and HTTP 409. When the client omits `version`, the server performs the mutation without an OCC check. The same `version` field that participates in this check is the integer that increments by one on every mutation (see §2.4).

A `PATCH` that races a state transition on the same `AuthorizationRequest`, `PeerToPeerReview`, or `Appeal` is serialized through this mechanism; whichever request observes a now-stale `version` loses and receives `ERR_VERSION_MISMATCH`.

### 2.7. Nested Resource Retrieval and Existence Checks

When an endpoint path contains multiple resource identifiers — for example, withdrawing a piece of evidence under an authorization — the server validates each identifier in left-to-right order, parent before child. The first identifier that does not resolve to an existing resource produces an immediate `404 Not Found` with `ERR_NOT_FOUND`; later checks do not run. Independently, foreign-key references that arrive in a request body — `patient_id`, `provider_id`, `service_catalog_item_id`, `authorization_request_id`, `payer_reviewer_id`, and `prior_request_id` — must resolve to existing rows; missing references produce `ERR_REFERENCE_NOT_FOUND` and HTTP 404. (Resubmission has a more specific check for `prior_request_id` discussed in §3.8 that uses `ERR_PRIOR_REQUEST_NOT_FOUND`.)

### 2.8. Validation Priority and Ordering

Validations are evaluated in a fixed priority order so that the most fundamental checks fail fast and the most specific business reasons surface only when the request is otherwise well-formed. The order, from first to last, is:

1. Identity headers present and well-formed — failure yields `ERR_AUTH_MISSING`.
2. Role permitted for the endpoint per the RBAC matrix — failure yields `ERR_FORBIDDEN`.
3. Path-parameter resources exist (resolved left to right) — failure yields `ERR_NOT_FOUND`.
4. Foreign-key body references resolve — failure yields `ERR_REFERENCE_NOT_FOUND`.
5. The target resource is in a state from which the requested transition is legal — failure yields `ERR_INVALID_STATE`.
6. `ServiceCatalogItem.status` is `ACTIVE` at submission — failure yields `ERR_CATALOG_RETIRED`.
7. `Patient.status` is `ACTIVE` at submission — failure yields `ERR_PATIENT_INACTIVE`.
8. `Provider.status` is `ACTIVE` at submission — failure yields `ERR_PROVIDER_SUSPENDED`.
9. Expedited-justification length check — failure yields `ERR_EXPEDITED_JUSTIFICATION_REQUIRED`.
10. Evidence-completeness threshold for the transition — failure yields `ERR_EVIDENCE_INSUFFICIENT`.
11. Evidence reuse must reference the correct prior request — failure yields `ERR_EVIDENCE_REUSE_MISMATCH`.
12. Resubmission requires that the referenced prior is in `EXPIRED` — failure yields `ERR_PRIOR_REQUEST_NOT_EXPIRED`.
13. At most one resubmission per `prior_request_id` — failure yields `ERR_RESUBMISSION_ALREADY_EXISTS`.
14. `approved_units` is in the legal range for the outcome — failure yields `ERR_INVALID_APPROVED_UNITS`.
15. `denial_reason_code` is supplied when the outcome is `DENIED` — failure yields `ERR_DENIAL_REASON_REQUIRED`.
16. The caller's role matches the appeal tier — failure yields `ERR_APPEAL_TIER_ROLE_MISMATCH`.
17. Appeals are filed in strict tier order — failure yields `ERR_APPEAL_TIER_OUT_OF_ORDER`.
18. No `PENDING` appeal already exists at the same tier — failure yields `ERR_APPEAL_ALREADY_FILED`.
19. The appeal decision deadline has not passed — failure yields `ERR_APPEAL_DEADLINE_EXPIRED`.
20. At most one peer-to-peer review per authorization in `SCHEDULED` or `COMPLETED` — failure yields `ERR_PEER_REVIEW_ALREADY_SCHEDULED`.
21. The proposed peer-to-peer time does not conflict with another `SCHEDULED` review for the same reviewer — failure yields `ERR_PEER_REVIEW_TIME_CONFLICT`.
22. `ClinicalEvidence.byte_size` is in range — failure yields `ERR_EVIDENCE_SIZE_INVALID`.
23. `ClinicalEvidence.uri` is unique among `ATTACHED` rows for the same authorization — failure yields `ERR_EVIDENCE_DUPLICATE_URI`.
24. Optimistic-concurrency `version` matches — failure yields `ERR_VERSION_MISMATCH`.

When two validations would both fail, the one with the lower number prevails. This is what guarantees, for example, that a caller whose `version` is stale on a `DRAFT` request that is not theirs sees the role-mismatch error first (priority 2) rather than the OCC error (priority 24).

### 2.9. Precision and Rounding

All numeric scores produced by the system — most notably `evidence_completeness_score` and `evidence_reuse_discount` — are stored and returned to exactly two decimal places, rounded half-up. Scores are clamped into the closed interval from 0.00 to 1.00 after rounding.

All datetime fields produced or accepted by the system — `submitted_at`, `decision_deadline_at`, `decided_at`, `expires_at`, `filed_at`, `scheduled_at`, `created_at`, `updated_at`, and the clock-advance `to` parameter — use ISO 8601 in UTC with three fractional digits ("to the millisecond"). Hour-based extensions (SLA windows, appeal deadlines, the 90-day approval validity expressed in hours) are added as exact wall-clock durations to the relevant base timestamp.

### 2.10. Version Pinning of Catalog Data

A `ServiceCatalogItem` may be edited at any time by a `PlatformAdmin`, and each edit increments the catalog item's `version`. To prevent in-flight authorizations from being silently re-priced or re-scoped, every `AuthorizationRequest` captures `service_catalog_item_version` at the moment it transitions from `DRAFT` to `SUBMITTED` and records the catalog item's `code` at the same time as `service_code` (denormalized for audit). All downstream calculations — SLA windows, evidence completeness, approval expiration — read the version-pinned snapshot, not the live catalog row. An appeal that later flips `DENIED` to `APPROVED` does not re-pin: the cascade continues to use the version captured at the original submission.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Patients, Providers, and the Service Catalog

Before any authorization can be created, the system needs three sets of reference data, all maintained by a `PlatformAdmin`.

A `Patient` is registered with the insurance `member_id` (which must be unique across the system), the patient's `full_name`, the `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and the `plan_type`, which must be one of `COMMERCIAL`, `MEDICARE`, or `MEDICAID`. Every patient starts in `ACTIVE` status; the only other allowed status value is `INACTIVE`. The active/inactive distinction matters at submission time, as discussed below.

A `Provider` is registered with the `npi` (the National Provider Identifier — exactly 10 digits and unique across the system), the provider's `full_name`, a free-text `specialty` (for example, `CARDIOLOGY`), and an optional `in_network` boolean that defaults to true. Every provider starts in `ACTIVE` status; the only other allowed status value is `SUSPENDED`. As with patients, the active/suspended distinction matters at submission time.

A `ServiceCatalogItem` represents a billable service or drug for which prior authorization may be required. It carries a unique `code` (a CPT, HCPCS, or NDC string), a `kind` discriminator that is one of `SERVICE` or `DRUG`, a human-readable `name`, and a boolean `requires_pa` that defaults to true. Three SLA-related integers complete the operational shape: `standard_sla_hours` (the decision window for a `STANDARD` request, defaulting to 336 — that is, 14 days — and required to be at least 24), `expedited_sla_hours` (defaulting to 72 — three days — and required to be at least 4 and strictly less than `standard_sla_hours`), and `approval_validity_days` (defaulting to 90 and required to be at least 1; this is how long an `APPROVED` authorization remains usable from its approval timestamp). Finally, a catalog item declares its `required_evidence_categories` — an array drawn from `LAB`, `IMAGING`, `NOTES`, `MED_HISTORY`, and `OTHER`. Every catalog item starts in `ACTIVE` status; an admin may retire a catalog item by moving its status to `RETIRED`.

Updates to a `ServiceCatalogItem` apply only to future submissions; in-flight authorizations retain the values captured by `service_catalog_item_version`, as established in §2.10.

### 3.2. Creating, Editing, and Submitting an Authorization Request

The provider initiates a new `AuthorizationRequest` by supplying the `patient_id` of the affected patient, the `provider_id` of the requesting practice (which must equal `X-User-ID` when the caller is a `Provider`), the `service_catalog_item_id` of the requested service or drug, an `urgency` that is one of `STANDARD` or `EXPEDITED` (defaults to `STANDARD`), a free-text `clinical_justification` capped at 4,000 characters, and `requested_units` — the number of visits, doses, or sessions requested, which must be at least 1. An optional `prior_request_id` marks the request as a resubmission and points back to a previously expired authorization; the resubmission rules in §3.8 then apply. On creation, the new authorization is in `DRAFT` status, its `evidence_reuse_discount` is initialized to 0.00, and no SLA timer has yet started.

While in `DRAFT`, the provider may freely revise `clinical_justification`, `requested_units`, or `urgency` and may also attach or withdraw clinical evidence (see §3.3). The same provider may also withdraw the request entirely from `DRAFT`, in which case the authorization transitions directly to `WITHDRAWN`. Any attempt to revise a request once it has left `DRAFT` is rejected as `ERR_INVALID_STATE`.

When the provider is ready, submitting the request advances `AuthorizationRequest.status` from `DRAFT` to `SUBMITTED`. Submission is gated by four preconditions, evaluated in the priority order described in §2.8: the catalog item must be `ACTIVE` (else `ERR_CATALOG_RETIRED`), the patient must be `ACTIVE` (else `ERR_PATIENT_INACTIVE`), the provider must be `ACTIVE` (else `ERR_PROVIDER_SUSPENDED`), and — if `urgency` is `EXPEDITED` — the `clinical_justification` must contain at least 50 non-whitespace characters (else `ERR_EXPEDITED_JUSTIFICATION_REQUIRED`). The same 50-character requirement does not apply to `STANDARD` requests.

On a successful submission, four side effects fire atomically: `submitted_at` is set to the current server time, `service_catalog_item_version` is pinned to the catalog item's current `version` and `service_code` is denormalized to the catalog item's current `code`, `decision_deadline_at` is computed by the standard-or-expedited deadline rule (described in §3.6), and the request's `evidence_completeness_score` and `evidence_reuse_discount` are recomputed against the now-pinned catalog snapshot.

A submitted request may still be withdrawn by the requesting provider. Withdrawal from `SUBMITTED` cancels any peer-to-peer review that is currently `SCHEDULED` for the authorization, transitioning that review's status to `CANCELLED`. Withdrawal from `PENDING_INFO` is also allowed; no further cascades fire because no peer-to-peer review can have been scheduled from that state. Once withdrawn, the authorization is terminal.

### 3.3. Clinical Evidence: Attaching, Reusing, and Withdrawing Documents

Each piece of `ClinicalEvidence` belongs to exactly one `AuthorizationRequest`, identified by its `authorization_request_id`. The provider uploading the document supplies the document's `category` — one of `LAB`, `IMAGING`, `NOTES`, `MED_HISTORY`, or `OTHER` — a human-readable `title`, the storage `uri` where the document lives (typically an opaque `s3://...` reference), and the document's `byte_size`. The `byte_size` must be strictly greater than 0 and no greater than 50,000,000 (50 MB); any size outside that closed-bounded range is rejected with `ERR_EVIDENCE_SIZE_INVALID`. Two `ATTACHED` evidence rows under the same authorization may not share the same `uri`; a colliding upload is rejected with `ERR_EVIDENCE_DUPLICATE_URI`.

A document being reused from a prior authorization is uploaded with `sourced_from_request_id` set to the id of the source authorization. Reuse is only valid in the context of a resubmission: if `sourced_from_request_id` is set, it must equal the current authorization's `prior_request_id`, otherwise the upload is rejected with `ERR_EVIDENCE_REUSE_MISMATCH`. Documents that are not reused — original uploads — leave `sourced_from_request_id` as null. Every evidence row is created in `ATTACHED` status by default.

A provider can withdraw a previously attached document; this transitions its `status` from `ATTACHED` to `WITHDRAWN`. Both attaching a new piece of evidence and withdrawing an existing piece recompute the parent authorization's `evidence_completeness_score` and (when `sourced_from_request_id` is involved) its `evidence_reuse_discount`. Because `ClinicalEvidence` is append-only history, its records carry only `id` and `created_at`; there is no `updated_at` and no `version`.

### 3.4. Initial Review: Starting, Requesting More Information, and Resuming

Once an authorization is `SUBMITTED`, the payer's `InitialReviewer` may begin a clinical review by starting it, advancing the authorization from `SUBMITTED` to `UNDER_REVIEW`. This transition is gated by an evidence-completeness threshold: the request's `evidence_completeness_score` must be at least 0.50. A request that does not yet meet that bar is rejected with `ERR_EVIDENCE_INSUFFICIENT`.

During `UNDER_REVIEW`, the `InitialReviewer` may decide that more information is required and request information, moving the authorization from `UNDER_REVIEW` to `PENDING_INFO`. This transition has no preconditions on the evidence score; it is the mechanism by which the reviewer signals the provider that more evidence is needed. The act of pausing for additional information extends the decision deadline, as detailed in §3.6.

While the request is in `PENDING_INFO`, the provider may attach further clinical evidence (or withdraw and replace existing evidence). The `InitialReviewer` may then resume the review, moving the authorization from `PENDING_INFO` back to `UNDER_REVIEW`. Resumption is gated by a stricter evidence threshold: `evidence_completeness_score` must be at least 0.75 (else `ERR_EVIDENCE_INSUFFICIENT`). The first threshold (0.50) governs the initial entry into review; the second (0.75) governs resumption after a pending-information cycle. The two cycles — `SUBMITTED → UNDER_REVIEW`, `UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW` — can repeat any number of times for the same authorization.

While the authorization is in `PENDING_INFO`, the provider may also withdraw the request entirely; the authorization transitions directly to `WITHDRAWN`.

### 3.5. Peer-to-Peer Reviews

When clinical disagreement exists, the requesting provider may schedule a peer-to-peer call with a `PayerReviewer`. Scheduling is permitted only from `UNDER_REVIEW`; on success, the parent authorization advances from `UNDER_REVIEW` to `PEER_REVIEW` and a `PeerToPeerReview` row is created with `status` `SCHEDULED` and `outcome` `PENDING`. The scheduling payload includes `scheduled_at` (the proposed call slot in ISO 8601 UTC, which must be strictly after the current server time), `duration_minutes` (the call window length, between 15 and 60 inclusive), and `payer_reviewer_id` (the opaque identifier of the proposed payer reviewer).

At most one peer-to-peer review per authorization may exist in `SCHEDULED` or `COMPLETED` status; an attempt to schedule a second is rejected with `ERR_PEER_REVIEW_ALREADY_SCHEDULED`. Independently, the proposed `scheduled_at` must not overlap, within the half-open interval that starts at `scheduled_at` and ends at `scheduled_at` plus `duration_minutes` minutes (so the endpoint is exclusive), with any other `SCHEDULED` review whose `payer_reviewer_id` is the same; a conflict is rejected with `ERR_PEER_REVIEW_TIME_CONFLICT`.

When the call has happened, the `PayerReviewer` completes the review, transitioning its `status` from `SCHEDULED` to `COMPLETED`. The completion payload supplies an `outcome` that must be one of `UPHELD`, `OVERTURNED`, or `NO_SHOW` (otherwise `ERR_INVALID_P2P_OUTCOME`) and may include free-text `notes` captured at completion. Completing the review cascades back to the parent authorization, returning it from `PEER_REVIEW` to `UNDER_REVIEW`. If the `outcome` is `OVERTURNED`, the parent authorization's `evidence_completeness_score` is recomputed using the post-peer-to-peer variant, which adds a bonus of 0.10 to the base score before clamping (see §3.7).

Either party — the requesting `Provider` or the `PayerReviewer` — may cancel a `SCHEDULED` review. Cancellation transitions the `PeerToPeerReview.status` from `SCHEDULED` to `CANCELLED` and reverts the parent authorization from `PEER_REVIEW` back to `UNDER_REVIEW` (the revert path). Once a peer-to-peer review reaches `COMPLETED` or `CANCELLED`, it is terminal.

### 3.6. Decision Deadlines

Every submitted authorization carries a server-computed `decision_deadline_at` — the moment by which the payer must have reached `APPROVED` or `DENIED`. The deadline is the sum of `submitted_at` and a base SLA window expressed in hours, plus any extensions earned through pending-information cycles. The base window depends on `urgency`: a `STANDARD` request uses the version-pinned `standard_sla_hours` (default 14 days), and an `EXPEDITED` request uses the version-pinned `expedited_sla_hours` (default 3 days).

Each completed `UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW` cycle adds an additional extension to the deadline. The extension per cycle is 168 hours (one week) for a `STANDARD` request and 24 hours (one day) for an `EXPEDITED` request. A request that has experienced two such pending-information cycles thus has its deadline pushed out by 336 hours (two weeks) for a `STANDARD` request or 48 hours for an `EXPEDITED` request. The deadline is recomputed whenever the request enters `PENDING_INFO` and again whenever it returns to `UNDER_REVIEW` from `PENDING_INFO`; the formula is `submitted_at` plus the base SLA hours plus the total accumulated pending-information extension hours, expressed to the millisecond in ISO 8601 UTC.

Per §2.10, the SLA constants used in this formula are the catalog values pinned at `submitted_at`; subsequent edits to the catalog item do not retroactively shift the deadline.

### 3.7. Evidence Completeness and Reuse Discount

The `evidence_completeness_score` measures, as a number between 0.00 and 1.00, how much of the required clinical evidence has been supplied. The score is recomputed whenever any `ClinicalEvidence` row under the authorization is attached or withdrawn, whenever the authorization transitions on submission, on the two `UNDER_REVIEW ↔ PENDING_INFO` transitions, and on the `PEER_REVIEW → UNDER_REVIEW` transition that follows an overturned peer-to-peer review.

The score is computed in three stages. First, a base coverage fraction is produced from the version-pinned `required_evidence_categories` of the underlying `ServiceCatalogItem`: if the catalog item requires no categories, the base coverage is 1.00; otherwise, the base coverage is the number of required categories for which at least one `ATTACHED` `ClinicalEvidence` row exists under this authorization, divided by the total number of required categories. Second, the base coverage is reduced by the request's `evidence_reuse_discount` (see below) and then increased by a peer-to-peer bonus, which is 0.10 when the most recent `PeerToPeerReview` on this authorization has `outcome` `OVERTURNED` and 0.00 otherwise. Third, the result is rounded half-up to two decimal places and clamped into the closed interval from 0.00 to 1.00. A reader reconstructing this rule should read it as: take the base coverage, subtract the reuse discount, add the post-peer-to-peer bonus, round to two decimal places half-up, then clamp the lower end to 0.00 and the upper end to 1.00.

The `evidence_reuse_discount` exists to dampen the score when a resubmission carries over evidence from its expired predecessor. If `prior_request_id` is null, the discount is 0.00. Otherwise, the system locates the prior authorization referenced by `prior_request_id` (raising `ERR_PRIOR_REQUEST_NOT_FOUND` if it does not exist), counts the number of `ATTACHED` `ClinicalEvidence` rows under the current authorization whose `sourced_from_request_id` equals that prior authorization's `id`, and computes the discount as 0.05 multiplied by the count of reused documents, but never larger than 0.20 — that is, the discount is the smaller of 0.05 times the reused count and 0.20. (If the pinned catalog item requires no evidence categories at all, the discount is 0.00 regardless of reuse.) The result is rounded half-up to two decimal places. Together, the per-document discount of 0.05 and the cap of 0.20 mean that the fifth and any further reused documents contribute nothing additional to the discount.

### 3.8. Resubmission of Expired Authorizations

When an authorization that previously reached `APPROVED` has aged past its `expires_at`, the expiration sweep moves it to `EXPIRED` (see §3.10). Once `EXPIRED`, no new appeal may be filed on that authorization; the remedy is resubmission. A resubmission is created by issuing a new `AuthorizationRequest` whose body sets `prior_request_id` to the id of the expired authorization.

Three checks govern resubmission. First, the referenced prior must exist (else `ERR_PRIOR_REQUEST_NOT_FOUND`). Second, the prior's `status` must be `EXPIRED`; resubmissions targeting a prior that is still in any earlier state, or one that was withdrawn, are rejected with `ERR_PRIOR_REQUEST_NOT_EXPIRED`. Third, at most one resubmission may exist per `prior_request_id`: a second attempt to resubmit the same expired authorization is rejected with `ERR_RESUBMISSION_ALREADY_EXISTS`, and the first-writer-wins guarantee on resubmission creation is the system's serialization point should a resubmission race the expiration sweep itself.

A resubmitted authorization carries `prior_request_id` permanently on its record, and the reuse-discount mechanism in §3.7 quietly draws the score down to reflect that the evidence is not fresh. Original (non-resubmission) authorizations leave `prior_request_id` null and are unaffected by the discount.

### 3.9. The Decision: Approve or Deny

The `InitialReviewer` issues the initial decision while the authorization is in `UNDER_REVIEW`, advancing it to `APPROVED` or `DENIED`. The decision payload includes the `outcome` (one of `APPROVED` or `DENIED`), a free-text `rationale` capped at 4,000 characters, an `approved_units` integer, and — when `outcome` is `DENIED` — a `denial_reason_code` drawn from `NOT_MEDICALLY_NECESSARY`, `EXPERIMENTAL`, `OUT_OF_NETWORK`, `EVIDENCE_INSUFFICIENT`, and `NON_COVERED_BENEFIT`.

`approved_units` is constrained tightly to the outcome. When the outcome is `APPROVED`, `approved_units` must be at least 1 and at most the authorization's `requested_units`; values outside that range are rejected with `ERR_INVALID_APPROVED_UNITS`. When the outcome is `DENIED`, `approved_units` must be 0 (and a `denial_reason_code` must be supplied, else `ERR_DENIAL_REASON_REQUIRED`). The `denial_reason_code` is null on approved decisions and is non-null on denials.

A successful decision creates a `Decision` row whose `authorization_request_id` ties it back to the authorization, whose `outcome` and `rationale` and `approved_units` and `denial_reason_code` mirror the decision payload, and whose `decided_by_role` is set by the system to `INITIAL_REVIEWER` on the initial decision (the role takes the values `INITIAL_REVIEWER`, `MEDICAL_DIRECTOR`, or `EXTERNAL_REVIEWER` depending on which reviewer produced the decision). On the initial decision, `supersedes_decision_id` is null because no prior decision is being overridden. The authorization's `decided_at` is set to the current server time. If the outcome is `APPROVED`, the system also computes `expires_at` as `decided_at` plus the version-pinned `approval_validity_days` multiplied by 24 hours, expressed to the millisecond in ISO 8601 UTC. Two concurrent decisions on the same authorization serialize through the state machine: the first writer wins; the second observes the status has already advanced past `UNDER_REVIEW` and is rejected with `ERR_INVALID_STATE`.

The `Decision` resource is immutable history: it carries only `id` and `created_at` — no `updated_at` and no `version`.

### 3.10. Approval Expiration and the Sweep

An approval is not perpetual. From the moment `decided_at` is recorded on an `APPROVED` authorization, the system schedules an `expires_at` exactly `approval_validity_days` days later, using the value version-pinned at submission. The expiration sweep — an admin-driven test capability — examines every authorization currently in `APPROVED` and, for each one whose current server time has reached or passed `expires_at`, advances its `status` to `EXPIRED`, refreshes `updated_at`, and increments `version`. The endpoint returns the set of ids it swept as `expired_authorization_request_ids`. Because the system is time-aware but the tests need deterministic time, the platform also exposes a clock-advance capability: an admin-only test-driving capability advances the logical clock to a supplied `to` instant. Advancing the clock does not itself run the sweep; the two endpoints are deliberately decoupled so that tests can advance time, observe pre-sweep state, and then run the sweep explicitly.

Once an authorization is `EXPIRED`, no new `Appeal` may be filed on it; the path forward is resubmission via a new authorization that points back through `prior_request_id` (§3.8). For an authorization that flips from `DENIED` to `APPROVED` through an overturned appeal, `expires_at` is recomputed at that moment using the same version-pinned `approval_validity_days` — the appeal does not re-pin the catalog version, so the validity window comes from the catalog snapshot captured at the original `submitted_at`, not from the current live catalog row.

### 3.11. Appeals: A Three-Tier Ladder

When an authorization reaches `DENIED`, the requesting provider may appeal. Filing an appeal produces a new `Appeal` resource whose `authorization_request_id` ties it back to the authorization, whose `reason` carries the provider's free-text appeal grounds (capped at 4,000 characters), whose `filed_at` records the moment of filing, and whose `superseded_decision_id` points to the id of the most recent `DENIED` `Decision` on the authorization. New appeals are created with `outcome` `PENDING`.

The appeal's `tier` is set by the system, not the caller: it is one greater than the count of prior appeals on this authorization that have already reached `UPHELD`. Thus the first appeal on a denied authorization is tier 1; if that appeal is upheld, a second appeal becomes tier 2; if that one is also upheld, a third becomes tier 3. The values 1, 2, and 3 are the only legal tiers. A withdrawn appeal does not count as `UPHELD` for the purposes of computing the next tier, so withdrawing a tier-1 appeal and filing again still produces tier 1. Appeals must be filed in strict tier order — tier `N` may only be filed after tier `N-1` has reached `UPHELD` — and any out-of-order attempt is rejected with `ERR_APPEAL_TIER_OUT_OF_ORDER`. Independently, at most one `PENDING` appeal may exist at the same tier for the same authorization; a second concurrent filing at the same tier is rejected with `ERR_APPEAL_ALREADY_FILED`.

The appeal's `decision_deadline_at` is computed at filing time from `filed_at` and a per-tier SLA. For `STANDARD` authorizations, tier 1 has a 240-hour window (10 days), tier 2 has 480 hours (20 days), and tier 3 has 720 hours (30 days). For `EXPEDITED` authorizations, the per-tier windows shrink considerably: tier 1 has 72 hours (3 days), tier 2 has 96 hours (4 days), and tier 3 has 168 hours (7 days). The deadline is the appeal's `filed_at` plus the hours selected by tier and urgency, expressed to the millisecond in ISO 8601 UTC.

Deciding an appeal is restricted by tier: tier 1 is decided by an `InitialReviewer`, tier 2 by a `MedicalDirector`, and tier 3 by an `ExternalReviewer`. A caller whose role does not match the appeal's `tier` is rejected with `ERR_APPEAL_TIER_ROLE_MISMATCH`. The decision payload supplies `outcome` (one of `UPHELD` or `OVERTURNED`), a free-text `rationale`, and — when overturning — `approved_units` (which must be at least 1; otherwise `ERR_INVALID_APPROVED_UNITS`). The parent authorization must still be in `DENIED` for the appeal decision to be valid; if it has moved on, the appeal decision is rejected with `ERR_INVALID_STATE`. The current server time must not exceed the appeal's `decision_deadline_at`; a late decision is rejected with `ERR_APPEAL_DEADLINE_EXPIRED`.

An upheld appeal records `decided_at` on the appeal but does not change the parent authorization's status — the authorization remains `DENIED`. An overturned appeal records `decided_at` on the appeal, then cascades to the parent: the authorization transitions from `DENIED` to `APPROVED`, a new `Decision` is created with `outcome` `APPROVED`, with `decided_by_role` equal to the appeal-decider's role (`INITIAL_REVIEWER` for tier 1, `MEDICAL_DIRECTOR` for tier 2, `EXTERNAL_REVIEWER` for tier 3), and with `supersedes_decision_id` pointing to the id of the prior `DENIED` `Decision` that the appeal targeted (i.e., the appeal's `superseded_decision_id`). The new `Decision` also receives the `decided_at` and `approved_units` values from the appeal decision. The parent authorization's own `decided_at` is refreshed to the current server time, and its `expires_at` is recomputed per the rule in §3.10. Throughout, the cascade observes §2.5 — `updated_at` is refreshed and `version` is incremented on the parent.

A `PENDING` appeal may also be withdrawn by the requesting provider; withdrawal sets the appeal's `outcome` to `WITHDRAWN` and records `decided_at`, and leaves the parent authorization's status untouched (still `DENIED`). The terminal states for an `Appeal` are `UPHELD`, `OVERTURNED`, and `WITHDRAWN`.

### 3.12. Concurrency and Serialization

Five concurrency scenarios deserve explicit attention; in each, the system serializes through a specific durable invariant and the losing request receives a specific error.

- Two `InitialReviewer` operators attempt to decide the same authorization at the same time. The state machine guarantees that at most one transition out of `UNDER_REVIEW` succeeds; the loser, observing that the status has already advanced, receives `ERR_INVALID_STATE` with HTTP 409.
- Two providers attempt to schedule a peer-to-peer review for the same authorization simultaneously. The "at most one in `SCHEDULED` or `COMPLETED` per authorization" invariant serializes them; the loser receives `ERR_PEER_REVIEW_ALREADY_SCHEDULED` with HTTP 409.
- Two providers attempt to file an appeal at the same tier on the same denied authorization concurrently. The "at most one `PENDING` appeal per (authorization, tier)" invariant serializes them; the loser receives `ERR_APPEAL_ALREADY_FILED` with HTTP 409.
- A resubmission race — two providers try to resubmit the same expired authorization at the same moment, or a resubmission races the expiration sweep itself. The "at most one `AuthorizationRequest` per `prior_request_id`" invariant serializes them; the loser receives `ERR_RESUBMISSION_ALREADY_EXISTS` with HTTP 409.
- An in-place payload update (for example, a provider revising `clinical_justification` while still in `DRAFT`) collides with a state transition on the same authorization. The collision is resolved by optimistic concurrency on `AuthorizationRequest.version`; the stale-version request receives `ERR_VERSION_MISMATCH` with HTTP 409.

## 4. Endpoint Definitions

Operations that create a new resource (a new authorization, a new piece of clinical evidence, a new peer-to-peer review, a new appeal) return HTTP `201 Created`. Operations that mutate an existing resource — submitting, starting review, deciding, withdrawing, scheduling cancellations, attaching a decision, completing a peer-to-peer review, advancing the clock, running the sweep, and so on — return HTTP `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/patients` | Register a new patient | PlatformAdmin |
| GET    | `/patients/{patientId}` | Fetch a patient | PlatformAdmin, Provider, InitialReviewer, MedicalDirector, ExternalReviewer |
| POST   | `/providers` | Register a provider | PlatformAdmin |
| GET    | `/providers/{providerId}` | Fetch a provider | PlatformAdmin, Provider, InitialReviewer |
| POST   | `/service-catalog-items` | Create a service-catalog item | PlatformAdmin |
| GET    | `/service-catalog-items/{itemId}` | Fetch a catalog item | PlatformAdmin, Provider, InitialReviewer, MedicalDirector, ExternalReviewer |
| PATCH  | `/service-catalog-items/{itemId}` | Update a catalog item | PlatformAdmin |
| POST   | `/authorization-requests` | Create a new authorization request (DRAFT; may be a resubmission) | Provider |
| GET    | `/authorization-requests` | List authorization requests with filtering and pagination | PlatformAdmin, Provider, InitialReviewer, MedicalDirector, ExternalReviewer |
| GET    | `/authorization-requests/{authId}` | Fetch a specific authorization request | PlatformAdmin, Provider, InitialReviewer, MedicalDirector, ExternalReviewer, PayerReviewer |
| PATCH  | `/authorization-requests/{authId}` | Update a DRAFT authorization request | Provider |
| POST   | `/authorization-requests/{authId}/submit` | Submit a DRAFT request for payer review | Provider |
| POST   | `/authorization-requests/{authId}/start-review` | Begin initial review (SUBMITTED → UNDER_REVIEW) | InitialReviewer |
| POST   | `/authorization-requests/{authId}/request-info` | Request more information (UNDER_REVIEW → PENDING_INFO) | InitialReviewer |
| POST   | `/authorization-requests/{authId}/resume-review` | Resume review (PENDING_INFO → UNDER_REVIEW) | InitialReviewer |
| POST   | `/authorization-requests/{authId}/peer-to-peer` | Schedule a peer-to-peer review (UNDER_REVIEW → PEER_REVIEW) | Provider |
| POST   | `/authorization-requests/{authId}/decide` | Issue the initial decision (UNDER_REVIEW → APPROVED or DENIED) | InitialReviewer |
| POST   | `/authorization-requests/{authId}/withdraw` | Withdraw the authorization | Provider |
| POST   | `/authorization-requests/{authId}/clinical-evidence` | Attach a clinical-evidence document | Provider |
| GET    | `/authorization-requests/{authId}/clinical-evidence` | List clinical evidence under an authorization | PlatformAdmin, Provider, InitialReviewer, MedicalDirector, ExternalReviewer, PayerReviewer |
| POST   | `/authorization-requests/{authId}/clinical-evidence/{evidenceId}/withdraw` | Withdraw a clinical-evidence document (ATTACHED → WITHDRAWN) | Provider |
| GET    | `/peer-to-peer-reviews/{p2pId}` | Fetch a peer-to-peer review | PlatformAdmin, Provider, InitialReviewer, PayerReviewer |
| POST   | `/peer-to-peer-reviews/{p2pId}/complete` | Record the outcome of a peer-to-peer review (SCHEDULED → COMPLETED) | PayerReviewer |
| POST   | `/peer-to-peer-reviews/{p2pId}/cancel` | Cancel a scheduled peer-to-peer review (SCHEDULED → CANCELLED) | Provider, PayerReviewer |
| POST   | `/authorization-requests/{authId}/appeals` | File an appeal against the latest DENIED decision | Provider |
| GET    | `/appeals/{appealId}` | Fetch an appeal | PlatformAdmin, Provider, InitialReviewer, MedicalDirector, ExternalReviewer |
| POST   | `/appeals/{appealId}/decide` | Decide an appeal (UPHELD keeps denial; OVERTURNED flips to APPROVED via cascade) | InitialReviewer, MedicalDirector, ExternalReviewer |
| POST   | `/appeals/{appealId}/withdraw` | Withdraw a pending appeal | Provider |
| POST   | `/_clock/advance` | Advance the system clock to a future ISO timestamp | PlatformAdmin |
| POST   | `/_sweep/run` | Run the expiration sweep that transitions APPROVED → EXPIRED | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_PRIOR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_MISMATCH` | 409 Conflict |
| `ERR_CATALOG_RETIRED` | 409 Conflict |
| `ERR_PATIENT_INACTIVE` | 409 Conflict |
| `ERR_PROVIDER_SUSPENDED` | 409 Conflict |
| `ERR_RESUBMISSION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_APPEAL_ALREADY_FILED` | 409 Conflict |
| `ERR_PEER_REVIEW_ALREADY_SCHEDULED` | 409 Conflict |
| `ERR_PEER_REVIEW_TIME_CONFLICT` | 409 Conflict |
| `ERR_EVIDENCE_DUPLICATE_URI` | 409 Conflict |
| `ERR_EXPEDITED_JUSTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_REUSE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRIOR_REQUEST_NOT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_APPROVED_UNITS` | 422 Unprocessable Entity |
| `ERR_DENIAL_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_APPEAL_TIER_ROLE_MISMATCH` | 403 Forbidden |
| `ERR_APPEAL_TIER_OUT_OF_ORDER` | 422 Unprocessable Entity |
| `ERR_APPEAL_DEADLINE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_SIZE_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_P2P_OUTCOME` | 422 Unprocessable Entity |
