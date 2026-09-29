# Identity Verification & Age Assurance API — Product Requirements Document

## 1. Introduction

Relying parties — marketplaces, gambling operators, social platforms, banks — increasingly have to prove two separate things about a person before letting them transact: that the person is who they claim to be, and that the person is old enough. These are not the same question, they fail in different ways, and they are answered by different vendor technologies: document scanning with forensic tamper detection, authoritative database lookups, biometric face comparison guarded by liveness detection, knowledge-based challenges, and statistical age estimation. This API is the orchestration layer that a verification provider operates on behalf of those relying parties. It selects methods by risk, scores the evidence each method returns, keeps identity assurance and age assurance on two independent tracks, and produces a single auditable disposition per subject.

Two obligations shape the design as much as accuracy does. The first is inclusion: a meaningful fraction of the population holds no standard identity document, and a system that simply rejects them is a system that excludes them, so the service supports adjudicated vouching and self-attestation pathways that contribute real — but capped — assurance. The second is fairness and data minimisation: false-reject rates differ measurably across demographic cohorts, biometric templates are among the most sensitive data a company can hold, and children must not have their faces processed at all. The service therefore runs a continuous demographic performance-testing programme that can restrict a vendor method mid-flight and force live sessions back to evidence collection, and it deletes biometric templates the moment a session closes unless a documented retention basis survives.

Everything in this document is expressed against a **logical clock** rather than wall-clock time, so that session lapse, review service-level deadlines and multi-month retention windows are all reachable and reproducible. Operators onboard clients and vendor profiles, compliance officers own policy publication and bias testing, and three narrow reviewer roles adjudicate escalations under strict segregation of duties. The API is mounted under `/idv`, with one out-of-band clock control endpoint outside that prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. If either header is absent, or if `X-User-Role` is not one of the six role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well-formed but the declared role is not authorised for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The six roles are `PlatformAdmin`, `ClientIntegrator`, `ComplianceOfficer`, `ReviewManager`, `ManualReviewer`, and `InclusionReviewer`.

A `PlatformAdmin` is the verification provider's own operator. It onboards relying-party clients and vendor method profiles, runs the operations sweep, drives the logical clock, and may read every resource. A `ClientIntegrator` is a relying party acting on its own traffic: it drafts policies, opens sessions, submits subject evidence, requests inclusion pathways, and closes sessions. A `ComplianceOfficer` owns policy publication and the entire bias-testing programme — opening audits, recording cohort metrics, evaluating disparity and recording remediation — and may read every resource, but may never open a session or submit subject evidence. A `ReviewManager` triages the manual-review queue and assigns cases, reserving review capacity as it does so, and may never decide a case. A `ManualReviewer` decides the case assigned to it and nothing else. An `InclusionReviewer` adjudicates accessibility pathways and touches nothing else.

Role identity is interpreted differently for the relying party than for the provider's own staff. When `X-User-Role` is `ClientIntegrator`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign-key field to `X-User-ID`, walking through the owning session where the resource does not carry the client reference directly. A `ClientIntegrator` that addresses a policy, session, attempt, evidence row, pathway or client record belonging to any other client is rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `ComplianceOfficer`, `ReviewManager`, `ManualReviewer` or `InclusionReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it where a transition asks for it — as `evaluated_by_user_id` or `remediated_by_user_id` on a bias audit, as `assigned_by_user_id`, `assigned_reviewer_user_id` or `decided_by_user_id` on a manual review case, as `reviewer_user_id` on an inclusion pathway, and as `actor_user_id` on every audit event — but it is never compared to any entity's `id`.

Two controls are enforced by segregation of duties, and both fail with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). In manual review, the `ManualReviewer` recorded as `decided_by_user_id` must differ from the `ReviewManager` recorded as `assigned_by_user_id`; separately, that reviewer's `X-User-ID` must equal `assigned_reviewer_user_id`, and a different reviewer submitting the verdict is rejected with `ERR_REVIEW_ASSIGNEE_MISMATCH` (HTTP 403). In bias remediation, the `ComplianceOfficer` recorded as `remediated_by_user_id` must differ from the `ComplianceOfficer` recorded as `evaluated_by_user_id` for the most recent evaluation of that audit.

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

Every list endpoint accepts two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` is the number of records to skip before the first returned record; it defaults to 0 and its minimum accepted value is 0.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource the API mints carries an `id` that is a server-generated UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource. Clients, method profiles, verification policies, verification sessions, method attempts, biometric templates, alternative pathways, manual review cases and bias audits all carry the full set.

Five record kinds are write-once observations rather than mutable resources, and they carry only `id` and `created_at` — both `updated_at` and `version` are absent from their representations entirely: document captures, liveness checks, age assurance results, cohort metrics, and audit events.

All temporal reasoning in this service runs on a **logical clock** rather than the host wall clock. The clock starts at the mandatory default instant `2026-08-01T00:00:00Z`. A `PlatformAdmin` may move it by supplying `current_utc`, and the response echoes the resulting `current_utc`; no business entity is mutated by that call. Every datetime field written by the server — `expires_at`, `completed_at`, `finalized_at`, `published_at`, `retired_at`, `decided_at`, `sla_due_at`, `restricted_at`, `remediated_at`, `deleted_at`, `retention_expires_at`, `occurred_at`, `swept_at` — is an instant read off this logical clock at the moment the writing transition executes. Time never advances on its own: deadline-driven outcomes only materialise when the clock is moved forward and the operations sweep is invoked.

### 2.5. Basis Points, Integer Arithmetic and Rounding Discipline

There are no decimal quantities anywhere in this API. Every score, rate, ratio, threshold and multiplier is an integer expressed in **basis points**, where 10,000 basis points means 100 percent and one basis point means one hundredth of one percent. Monetary amounts are integers in minor currency units (cents). Ages are integers in whole months. Credits and counters are plain integers.

Three rounding disciplines are used, and which one applies is stated at each formula rather than left to preference:

- **Round half up to a whole basis point** governs conversions of a count ratio into a rate or ratio: the document base score derived from validated security features, each cohort's false-reject and false-accept rates, the pooled false-reject rate, and both disparity ratios. A value exactly at the midpoint rounds away from zero.
- **Truncation toward zero (floor)** governs every score that is *spent* rather than reported: the tamper penalty, the blended biometric quality, the database and knowledge-based quality figures, the halving applied to an inconclusive liveness result, each attempt's assurance contribution, and the bias haircut applied when a final score is written. Truncation is applied per attempt before any summation, never after; the sum is never re-derived from raw basis points.
- **Rounding up (ceiling)** governs exactly one quantity: the age-estimation safety buffer in months.

### 2.6. Validation Order and Error Precedence

Many endpoints are guarded by several checks at once, and which error surfaces is part of the contract, not an implementation detail. Checks are evaluated strictly in the order listed below, and the first failing check determines the response. A check whose scope does not include the endpoint being called is skipped.

1. `ERR_UNAUTHENTICATED` (401) — headers present and the role recognised. Every endpoint.
2. `ERR_ROLE_NOT_PERMITTED` (403) — the caller's role is listed on the endpoint. Every endpoint.
3. `ERR_CLIENT_NOT_FOUND` (404) — the client named by the path exists. `PATCH /idv/clients/{id}`, `GET /idv/clients/{id}`.
4. `ERR_METHOD_PROFILE_NOT_FOUND` (404) — the method profile named by the path exists. `GET /idv/method-profiles/{id}`, `GET /idv/method-profiles/{id}/bias-audits`.
5. `ERR_POLICY_NOT_FOUND` (404) — the verification policy named by the path exists. `POST /idv/verification-policies/{id}/publish`, `GET /idv/verification-policies/{id}`.
6. `ERR_SESSION_NOT_FOUND` (404) — the verification session named by the path exists. Every `/idv/verification-sessions/{id}/...` endpoint and `GET /idv/verification-sessions/{id}`.
7. `ERR_ATTEMPT_NOT_FOUND` (404) — the method attempt named by the path exists. Every `/idv/method-attempts/{id}/...` endpoint and `GET /idv/method-attempts/{id}`.
8. `ERR_PATHWAY_NOT_FOUND` (404) — the alternative pathway named by the path exists. `POST /idv/alternative-pathways/{id}/decision`.
9. `ERR_REVIEW_CASE_NOT_FOUND` (404) — the manual review case named by the path exists. `POST /idv/manual-review-cases/{id}/assign`, `POST /idv/manual-review-cases/{id}/decision`.
10. `ERR_AUDIT_NOT_FOUND` (404) — the bias audit named by the path exists. Every `/idv/bias-audits/{id}/...` endpoint and `GET /idv/bias-audits/{id}`.
11. `ERR_CLIENT_SCOPE_VIOLATION` (403) — for a `ClientIntegrator` caller, the target resource resolves to the client whose `id` equals `X-User-ID`. Every endpoint whose authorised roles include `ClientIntegrator`.
12. `ERR_REVIEW_ASSIGNEE_MISMATCH` (403) — `X-User-ID` equals the case's `assigned_reviewer_user_id`. `POST /idv/manual-review-cases/{id}/decision`.
13. `ERR_INVALID_REQUEST` (422) — the body parses, carries no unknown key, contains every required field, and satisfies every declared enum, range, length and conditional-presence constraint. Every endpoint that accepts a body. The conditional-presence constraints include: `window_end` strictly after `window_start`; `passed_feature_count` not greater than `required_feature_count`; `false_reject_count` and `false_accept_count` each not greater than `attempt_count`; an `ESTIMATION` age result requiring both `estimated_age_months` and `estimation_profile_id` while a `VERIFICATION` age result requires `date_of_birth`; database-check evidence requiring `matched_field_count` and `total_field_count` while knowledge-based evidence requires `correct_answer_count` and `question_count`; a `VOUCHING` pathway requiring `voucher_reference` while an `ATTESTATION` pathway requires `attestation_document_ref`; and at least one mutable field on the client patch.
14. `ERR_CLIENT_NOT_FOUND` (404) — a client referenced by a body field exists. `POST /idv/verification-policies`, `POST /idv/verification-sessions`.
15. `ERR_METHOD_PROFILE_NOT_FOUND` (404) — a method profile referenced by a body field exists. `POST /idv/bias-audits`, `POST /idv/verification-sessions/{id}/method-attempts`, `POST /idv/verification-sessions/{id}/age-assurance-results`.
16. `ERR_SESSION_STATE_INVALID` (409) — the session is in a state the operation admits. Every session-mutating endpoint. This includes `POST /idv/manual-review-cases/{id}/decision`, whose owning session must still be at `MANUAL_REVIEW`; for that endpoint the check deliberately precedes the case-state check at position 20, so a case whose session has already left `MANUAL_REVIEW` reports `ERR_SESSION_STATE_INVALID` rather than `ERR_REVIEW_CASE_STATE_INVALID`.
17. `ERR_EVIDENCE_ALREADY_SUBMITTED` (409) — the attempt does not yet carry an evidence row. The three evidence-submission endpoints. This check deliberately precedes the attempt-state check at position 40, so that a second evidence submission against an already-scored attempt reports the specific duplicate-evidence error rather than the generic attempt-state error.
18. `ERR_POLICY_STATE_INVALID` (409) — the policy is `DRAFT`. `POST /idv/verification-policies/{id}/publish`.
19. `ERR_PATHWAY_STATE_INVALID` (409) — the pathway is `VOUCH_PENDING` or `ATTESTATION_PENDING`. `POST /idv/alternative-pathways/{id}/decision`.
20. `ERR_REVIEW_CASE_STATE_INVALID` (409) — the case is `QUEUED` for assignment and `ASSIGNED` for a decision. `POST /idv/manual-review-cases/{id}/assign`, `POST /idv/manual-review-cases/{id}/decision`.
21. `ERR_AUDIT_STATE_INVALID` (409) — the audit is `COLLECTING` for cohort submission and evaluation, and `REMEDIATION_REQUIRED` for remediation. `POST /idv/bias-audits/{id}/cohort-metrics`, `POST /idv/bias-audits/{id}/evaluate`, `POST /idv/bias-audits/{id}/remediation`.
22. `ERR_STALE_CLIENT_VERSION` (412) — `expected_client_version` equals the client's current `version`. `POST /idv/verification-policies/{id}/publish`.
23. `ERR_STALE_METHOD_PROFILE_VERSION` (412) — `expected_method_profile_version` equals the audited method profile's current `version`. `POST /idv/bias-audits/{id}/remediation`.
24. `ERR_CLIENT_NOT_LIVE` (409) — the client's integration posture admits the operation. `POST /idv/verification-sessions`, `POST /idv/verification-policies/{id}/publish`, `POST /idv/verification-sessions/{id}/method-attempts`.
25. `ERR_PINNED_POLICY_RETIRED` (409) — the session's pinned policy is still `PUBLISHED`. `POST /idv/verification-sessions/{id}/method-attempts`.
26. `ERR_METHOD_RESTRICTED_BY_BIAS` (409) — the method profile involved is not restricted. `POST /idv/verification-sessions/{id}/method-attempts`, `POST /idv/bias-audits/{id}/evaluate`.
27. `ERR_MINOR_BIOMETRIC_PROHIBITED` (409) — the session's resolved age band is not a minor band. `POST /idv/method-attempts/{id}/liveness-checks`.
28. `ERR_BIOMETRIC_CONSENT_REQUIRED` (409) — the session recorded biometric consent. `POST /idv/method-attempts/{id}/liveness-checks`.
29. `ERR_AGE_ACCURACY_UNDOCUMENTED` (422) — the estimation profile documents an accuracy for the band the estimate resolves to. `POST /idv/verification-sessions/{id}/age-assurance-results`.
30. `ERR_SEGREGATION_OF_DUTIES` (403) — the acting user is not the same person who performed the paired earlier step. `POST /idv/manual-review-cases/{id}/decision`, `POST /idv/bias-audits/{id}/remediation`.
31. `ERR_NO_PUBLISHED_POLICY` (409) — the client has a published policy to pin. `POST /idv/verification-sessions`.
32. `ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE` (409) — an explicitly requested profile's method may be attempted directly by a client. `POST /idv/verification-sessions/{id}/method-attempts`. This check deliberately precedes the admitted-method check at position 33, because neither of the two non-attemptable methods can ever appear in a policy's admitted list.
33. `ERR_METHOD_NOT_IN_POLICY` (409) — an explicitly requested profile's method is admitted by the pinned policy. `POST /idv/verification-sessions/{id}/method-attempts`.
34. `ERR_EVIDENCE_METHOD_MISMATCH` (409) — the evidence kind matches the attempt's method. The three evidence-submission endpoints.
35. `ERR_METHOD_PROFILE_DUPLICATE` (409) — the method and vendor pair is unused. `POST /idv/method-profiles`.
36. `ERR_POLICY_VERSION_DUPLICATE` (409) — the client-scoped policy version number is unused. `POST /idv/verification-policies`.
37. `ERR_COHORT_DUPLICATE` (409) — the cohort label is unused within the audit. `POST /idv/bias-audits/{id}/cohort-metrics`.
38. `ERR_SESSION_EXPIRED` (409) — the session has not lapsed. Every session-mutating endpoint and every attempt-mutating endpoint.
39. `ERR_AUDIT_WINDOW_OVERLAP` (409) — the requested measurement window does not overlap a live audit window on the same profile. `POST /idv/bias-audits`.
40. `ERR_ATTEMPT_STATE_INVALID` (409) — the attempt is in a state the operation admits. The three evidence-submission endpoints and `POST /idv/method-attempts/{id}/finalize`.
41. `ERR_NO_ELIGIBLE_METHOD` (409) — the method selector produces a non-empty candidate set. `POST /idv/verification-sessions/{id}/method-attempts`, `POST /idv/alternative-pathways/{id}/decision`.
42. `ERR_STEP_UP_LIMIT_REACHED` (409) — step-up budget remains. `POST /idv/verification-sessions/{id}/step-up`.
43. `ERR_ATTEMPT_PENDING_FINALIZATION` (409) — no attempt of the session is still open. `POST /idv/verification-sessions/{id}/complete`.
44. `ERR_PENDING_PATHWAY_BLOCKS_COMPLETION` (409) — no inclusion pathway of the session is still pending. `POST /idv/verification-sessions/{id}/complete`.
45. `ERR_ALTERNATIVE_PATHWAY_DISABLED` (409) — the pinned policy enables alternative pathways. `POST /idv/verification-sessions/{id}/alternative-pathways`.
46. `ERR_AGE_ASSURANCE_MISSING` (409) — the age axis has been answered when the policy gates on age. `POST /idv/verification-sessions/{id}/complete`.
47. `ERR_INSUFFICIENT_COHORT_COVERAGE` (409) — the audit has enough in-scope cohort rows. `POST /idv/bias-audits/{id}/evaluate`.
48. `ERR_REVIEW_CAPACITY_EXHAUSTED` (409) — the client has an available review credit to reserve. `POST /idv/manual-review-cases/{id}/assign`.
49. `ERR_CLIENT_DAILY_QUOTA_EXCEEDED` (409) — the client's rolling-window session count is below its quota. `POST /idv/verification-sessions`.

### 2.7. Optimistic Concurrency on Client and Method Profile Versions

Exactly two write endpoints take an optimistic-concurrency input, because exactly two operations legitimately supersede a decision another operator may have based work on. Both are non-optional inputs on their endpoint, and both compare against the *parent* entity's `version` rather than the addressed resource's own.

Publishing a draft policy supersedes the client's currently published policy and repoints every future session's pinned policy, so a second sequential publish of a different draft would itself succeed under the natural product semantics. `POST /idv/verification-policies/{id}/publish` therefore requires `expected_client_version` carrying the client's `version` as the caller last observed it. If that value does not equal the client's current `version`, the publish is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412); on success the client's `version` increments by one, so an operator working from an earlier read of the client is rejected rather than silently replacing a policy it never saw.

Recording remediation lifts a restricted method profile back to monitored status and rejects every attempt that was blocked pending rescore, and a second sequential remediation from another audit on the same profile would itself succeed under the natural product semantics. `POST /idv/bias-audits/{id}/remediation` therefore requires `expected_method_profile_version` carrying the audited profile's `version` as observed when the remediation evidence was gathered. If that value does not equal the profile's current `version`, the remediation is rejected with `ERR_STALE_METHOD_PROFILE_VERSION` (HTTP 412); on success the profile's `version` increments by one.

No other endpoint accepts a version field, and no other endpoint performs a stale-version check.

### 2.8. Derived Counters and Cascading Consistency

A single request in this service routinely mutates several resources. Each mutated resource independently refreshes its own `updated_at` and increments its own `version`; a cascade that touches five sessions bumps five session versions. Derived fields are ordinary mutations for this purpose — recomputing a session's provisional score is a mutation of that session.

Five counters on the client record are wholly server-derived and are never accepted as input. `reserved_review_credits` is the number of that client's manual review cases currently in the `ASSIGNED` state. `available_review_credits` is `granted_review_credits` minus `reserved_review_credits`, and the invariant that reserved and available credits always sum to the granted total is re-checked after every request that touches a credit; at creation, available equals granted. `stored_template_count` is the number of biometric templates in the `STORED` state belonging to sessions of that client, and it decrements exactly once per template, at the moment that template leaves `STORED`. `pending_stepup_count` is the number of that client's sessions whose identity axis sits at `AWAITING_EVIDENCE`. `consumed_review_count` is a lifetime tally of that client's manual review cases that reached `DECIDED`; it only ever increases.

Cascades are always immediate and always complete within the request that triggers them. Where a transition below is described as driving another entity's transition, that second transition's own side effects also run, including its audit-event append and its counter adjustments.

### 2.9. Path Resolution and List Filters

Every business resource in this service is addressed as a peer collection under `/idv` — no business entity is addressed through a parent's identifier. Foreign keys travel in request bodies, and reverse navigation is offered through filtered list endpoints and through read-only sub-resource collections such as the captures of one attempt or the audit trail of one session.

Where a path does carry an identifier followed by a sub-resource segment, identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the 404 that is returned. A request for the cohort rows of a non-existent audit reports `ERR_AUDIT_NOT_FOUND`; a request for the liveness checks of a non-existent attempt reports `ERR_ATTEMPT_NOT_FOUND`. Existence resolution always precedes ownership, schema, state and business checks, exactly as ordered in §2.6.

List endpoints accept optional exact-match filters in addition to `limit` and `offset`. Bias audits may be filtered by `state`. Verification policies may be filtered by `client_id` and `state`. Verification sessions may be filtered by `client_id`, `policy_id`, `identity_state`, `age_state` and `external_subject_ref`. Method attempts may be filtered by `session_id`, `method_profile_id` and `state`. Biometric templates and alternative pathways of a session, and manual review cases of a session, may be filtered by `state`. A session's audit trail may be filtered by `event_type`, and it is ordered by `occurred_at` ascending and then `created_at` ascending. A session's age assurance results are ordered by `created_at` ascending, so the newest result is last.

### 2.10. The Append-Only Audit Trail

Every consequential change to a session appends an immutable audit event to that session's trail. An audit event records the `session_id` it describes, an `event_type` drawn from `SESSION_CREATED`, `ATTEMPT_FINALIZED`, `STEP_UP_TRIGGERED`, `ESCALATED_TO_REVIEW`, `REVIEW_DECIDED`, `PATHWAY_DECIDED`, `METHOD_RESTRICTION_APPLIED`, `TEMPLATE_DELETED` and `SESSION_TERMINAL`, the `actor_role` that caused it, the `actor_user_id` that caused it, a `payload_summary` naming the fields the transition mutated, and the `occurred_at` instant read off the logical clock.

For a caller-driven event, `actor_role` is the caller's `X-User-Role` and `actor_user_id` is the caller's `X-User-ID`. For an event produced by the operations sweep, `actor_role` is the literal string `system` and `actor_user_id` is null. Audit events are never updated or removed.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Clients, Vendor Method Profiles and the Policy Ladder

A relying party enters the system as a **Client**, registered by a `PlatformAdmin` with a `name` between 1 and 120 characters, a `home_jurisdiction_code` that is exactly two uppercase letters in ISO 3166-1 alpha-2 form, a `biometric_retention_mode` that is one of `DELETE_ON_COMPLETE`, `RETAIN_90_DAYS` or `RETAIN_WITH_CONSENT`, a `daily_session_quota` of at least 1, and a `granted_review_credits` grant of 0 or more. Registration always lands the client in the `SANDBOX` integration posture: `integration_state` is one of `SANDBOX`, `LIVE` or `SUSPENDED`, and only the admin patch moves it to `LIVE` or `SUSPENDED`. At registration `reserved_review_credits`, `stored_template_count`, `pending_stepup_count` and `consumed_review_count` all start at 0, and `available_review_credits` starts equal to `granted_review_credits`.

The admin patch is the single way to adjust a live client. It accepts any non-empty subset of `integration_state`, `biometric_retention_mode`, `daily_session_quota` and `granted_review_credits`; a patch carrying none of them is rejected with `ERR_INVALID_REQUEST`. After a grant change the available-credit figure is re-derived from the client's currently assigned cases so that the pool invariant of §2.8 still holds, and the client's `version` increments by one — which, per §2.7, invalidates any publish request an operator had prepared from an earlier read.

Vendor capabilities are registered separately as **MethodProfile** records, also by a `PlatformAdmin`. A profile names the `method_code` it configures — one of `DOCUMENT_SCAN`, `DATABASE_CHECK`, `BIOMETRIC_COMPARISON`, `KNOWLEDGE_BASED`, `VOUCHING_ATTESTATION` or `AGE_ESTIMATION` — together with a `vendor_code` of 1 to 24 characters. The combination of method and vendor must be unique across all profiles; a repeat is rejected with `ERR_METHOD_PROFILE_DUPLICATE`. A profile declares an `assurance_weight` between 1 and 100, being the maximum assurance points the method may contribute to any one session; an `acceptance_floor_bps` between 0 and 10000, being the minimum evidence quality at which an attempt on this profile is accepted; documented error rates `far_bps` and `frr_bps`, each between 0 and 10000 basis points; a boolean `strong_evidence` marking whether the method is admissible for high-risk sessions; and a `cost_cents` per-attempt vendor cost of 0 or more. Age-estimation vendors additionally declare `estimation_mae_months`, the documented mean absolute error of the estimator in whole months, which defaults to 0 and is 0 for every non-estimation method, and `band_accuracy_bps`, a map whose keys are a subset of `U13`, `B13_15`, `B16_17`, `B18_20` and `A21_PLUS` and whose values are basis points between 0 and 10000; the map defaults to empty. Every new profile starts with `bias_state` at `CLEARED` and `restricted_at` null, and neither field is ever writable by a direct profile write — only the bias-testing transitions of §3.9 move them.

A **VerificationPolicy** is drafted against a `client_id` by either a `ClientIntegrator` acting for that client or a `ComplianceOfficer`. Each draft carries a client-scoped `policy_version` of at least 1, unique within the client; a repeat is rejected with `ERR_POLICY_VERSION_DUPLICATE`. The policy's `allowed_method_codes` is a non-empty array of distinct values drawn only from `DOCUMENT_SCAN`, `DATABASE_CHECK`, `BIOMETRIC_COMPARISON` and `KNOWLEDGE_BASED` — the vouching and age-estimation methods are structurally excluded from the identity ladder. A `min_assurance_score` between 1 and 100 sets the bar for an unaided verified outcome. Four tuning knobs carry defaults: `doc_authenticity_floor_bps`, the score at or above which a document is judged authentic, defaults to 8000 and must lie between 5001 and 10000; `pad_threshold_bps`, the baseline presentation-attack-detection threshold before any adjustment, defaults to 7500 and must lie between 1000 and 9500; `age_buffer_multiplier_bps`, the multiplier applied to an estimator's documented error to derive the safety buffer, defaults to 15000 and must lie between 10000 and 30000; and `step_up_max_rounds`, the number of step-up rounds a session may consume, defaults to 2 and must lie between 0 and 5. The `required_min_age_years` gate defaults to 0 and must lie between 0 and 25, where 0 disables the age axis entirely. Finally `alternative_pathway_enabled` defaults to true and decides whether subjects without standard documentation may request an inclusion pathway. A fresh draft sits in `DRAFT` with `published_at` and `retired_at` null and `degraded_flag` false.

Publication is a `ComplianceOfficer` prerogative and is the only way a policy leaves `DRAFT`. It requires the policy to still be in `DRAFT` — otherwise `ERR_POLICY_STATE_INVALID` — and requires the owning client not to be `SUSPENDED`, otherwise `ERR_CLIENT_NOT_LIVE`. It also carries the client-version guard described in §2.7. On success the policy moves `DRAFT → PUBLISHED` with `published_at` set to the clock, and in the same request the client's previously `PUBLISHED` policy, if any, moves `PUBLISHED → RETIRED` with `retired_at` set to the clock; the client's `version` increments by one. Retirement is terminal for a policy. Sessions that were already pinned to the retired policy keep their pinned policy reference and continue to be evaluated against its thresholds, but they can no longer open new attempts: any such request is rejected with `ERR_PINNED_POLICY_RETIRED`.

One derived flag on the policy is worth stating on its own. `degraded_flag` is true whenever at least one method profile whose `method_code` appears in that policy's `allowed_method_codes` currently has `bias_state` equal to `RESTRICTED`, and false otherwise. It is a disclosure signal for the relying party, not a gate.

### 3.2. Opening a Verification Session: Quota, Policy Pinning and Risk Banding

A `ClientIntegrator` opens a **VerificationSession** by naming the `client_id` it acts for, a `external_subject_ref` of 1 to 64 characters that is the client's own pseudonymous handle for the subject, a `requested_assurance_tier` of `BASIC`, `STANDARD` or `ENHANCED`, and a `subject_jurisdiction_code` of exactly two uppercase letters. Three inputs are optional: `declared_transaction_value_cents`, the value of the transaction being protected, defaults to 0 and must not be negative; `biometric_consent` defaults to false; and `documentation_status` defaults to `STANDARD_DOCS` and may instead be `NO_STANDARD_DOCS`.

Opening a session requires the client's `integration_state` to be exactly `LIVE`. A client still in `SANDBOX`, or one that has been `SUSPENDED`, is rejected with `ERR_CLIENT_NOT_LIVE` — note that publication and attempt creation are more permissive, admitting `SANDBOX` and refusing only `SUSPENDED`, whereas session creation admits `LIVE` alone.

Volume is capped by a rolling window rather than a calendar day. The window spans the twenty-four hours ending at the current clock instant and is inclusive at both ends, so a session created exactly twenty-four hours before the clock still counts against the quota while advancing the clock one further second drops it out and frees capacity. Usage is the number of that client's sessions whose `created_at` falls inside the window, counted regardless of their identity axis — expired and rejected sessions count exactly as verified ones do. If usage has already reached `daily_session_quota`, the request is rejected with `ERR_CLIENT_DAILY_QUOTA_EXCEEDED`; otherwise the session is created.

The session is then pinned to a policy version, and the pin never moves. Candidates are every policy of that client currently in `PUBLISHED`. They are ranked by `policy_version` descending, and where two share a version number, by `created_at` ascending; the winner's identifier is written to the session's `policy_id`. Entity identifiers are never used as a ranking or tie-break key. If the candidate set is empty the session is not created and the request fails with `ERR_NO_PUBLISHED_POLICY`. The pin survives the pinned policy's later retirement: `policy_id` continues to point at the retired policy and its thresholds continue to govern the session.

Risk is scored once, at creation, and is then frozen — neither `risk_score` nor `risk_level` is ever recomputed for the life of the session. The score begins from the requested tier: 10 points for `BASIC`, 30 for `STANDARD`, 60 for `ENHANCED`. A transaction-value bump is added next: nothing for a declared value of at most 24,999 cents, 10 points for a declared value above 24,999 cents and at most 999,999 cents, and 20 points for a declared value above 999,999 cents. A further 20 points are added when the `subject_jurisdiction_code` the subject presents differs from the client's `home_jurisdiction_code`. A further 10 points are added when `documentation_status` is `NO_STANDARD_DOCS`. Finally a history bump is added: 15 points for each earlier session of the same client with the same `external_subject_ref` whose identity axis ended in `REJECTED`, with the whole history bump capped at 30 points so that a third and any subsequent prior rejection adds nothing further. The sum of these five terms is `risk_score`. The derived `risk_level` is `HIGH` when the score is 70 or more, `MEDIUM` when the score is at least 40 and below 70, and `LOW` otherwise — so a `STANDARD` request declaring exactly 25,000 cents scores exactly 40 and lands precisely on the `MEDIUM` boundary.

Sessions are short-lived. `expires_at` is set to the session's `created_at` plus sixty minutes on the logical clock. A session is treated as lapsed by every mutating endpoint as soon as the clock is strictly past `expires_at`, and such requests are rejected with `ERR_SESSION_EXPIRED` — even before the operations sweep has materialised the lapse as an `EXPIRED` identity state. A clock instant exactly equal to `expires_at` is still inside the window.

The new session runs two independent state axes. The identity axis, `identity_state`, starts at `IN_PROGRESS` and moves among `IN_PROGRESS`, `AWAITING_EVIDENCE`, `MANUAL_REVIEW`, `VERIFIED`, `REJECTED` and `EXPIRED`, of which the last three are terminal. The age axis, `age_state`, moves among `NOT_REQUIRED`, `PENDING`, `ASSURED` and `FAILED`; it starts at `NOT_REQUIRED` when the pinned policy sets `required_min_age_years` to 0, and at `PENDING` otherwise. The two axes progress entirely independently of one another. The remaining derived fields start at their baselines: `assurance_score_provisional` at 0, `assurance_score_final` null, `assurance_ceiling` at 100, `resolved_age_band` null, `fraud_signal_count` at 0, `step_up_round` at 0, `manual_override_flag` false, `disposition_reason` null and `completed_at` null. Creation appends an audit event of type `SESSION_CREATED`.

### 3.3. Choosing a Method and Opening an Attempt

A **MethodAttempt** is the unit of evidence collection. A `ClientIntegrator` opens one against a session that is `IN_PROGRESS` and not lapsed, whose client is not `SUSPENDED`, and whose pinned policy is still `PUBLISHED`. The body carries a single optional field, `method_profile_id`, and its presence or absence decides between two very different behaviours.

When the caller names `method_profile_id` explicitly, no selection runs. The named profile is used, `selection_mode` is recorded as `CLIENT_REQUESTED`, and three gates apply in the order fixed by §2.6: first, a profile whose `method_code` is `VOUCHING_ATTESTATION` or `AGE_ESTIMATION` is refused with `ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE`, because those two methods are granted by adjudication and by the age axis respectively and can never appear in a policy's admitted list; then a profile whose `method_code` falls outside the pinned policy's `allowed_method_codes` is refused with `ERR_METHOD_NOT_IN_POLICY`; then a profile whose `bias_state` is `RESTRICTED` is refused with `ERR_METHOD_RESTRICTED_BY_BIAS`.

When the caller omits `method_profile_id`, the server climbs the method ladder on its behalf. A profile is a candidate when all four of the following hold: its `method_code` appears in the pinned policy's `allowed_method_codes`; its `bias_state` is not `RESTRICTED`; either the session's `risk_level` is not `HIGH` or the profile's `strong_evidence` is true; and no attempt of this session already carries that same `method_code` in the `ACCEPTED` state. Candidates are ranked by `assurance_weight` descending, then by `cost_cents` ascending, then by `created_at` ascending; identifiers are never used as a ranking or tie-break key, and `created_at` ascending is the final arbiter. The top-ranked candidate is used and `selection_mode` is recorded as `SERVER_SELECTED`. An empty candidate set is rejected with `ERR_NO_ELIGIBLE_METHOD` — which is precisely what a `HIGH`-risk session gets when its policy admits only profiles whose `strong_evidence` is false.

Either way the resolved profile is recorded on the attempt as `method_profile_id`, its method is copied to the attempt's own `method_code` — one of `DOCUMENT_SCAN`, `DATABASE_CHECK`, `BIOMETRIC_COMPARISON`, `KNOWLEDGE_BASED` or `VOUCHING_ATTESTATION` — and the attempt is filed under the owning `session_id`. Its `retry_index` is the number of attempts that already exist on the same session with the same `method_code`, so the first document scan of a session has index 0 and a second has index 1; this figure matters later for liveness tuning. The attempt opens in `AWAITING_EVIDENCE`, one of `AWAITING_EVIDENCE`, `SCORED`, `REQUIRES_RESCORE`, `ACCEPTED`, `REJECTED` and `EXPIRED`, of which the last three are terminal. Its scoring fields start empty: `evidence_quality_bps` null, `match_score_bps` null, `contribution_points` null, `tamper_flag` false, `rejection_reason` null and `finalized_at` null.

An attempt accepts exactly one evidence row, and the kind of evidence must match its `method_code`. A mismatched kind is refused with `ERR_EVIDENCE_METHOD_MISMATCH`; a second submission of any kind is refused with `ERR_EVIDENCE_ALREADY_SUBMITTED`, which per §2.6 takes precedence over the `ERR_ATTEMPT_STATE_INVALID` that the now-`SCORED` attempt would otherwise produce.

### 3.4. Document Evidence: Tamper Detection and Security-Feature Validation

A document-scan attempt is scored from a **DocumentCapture** submitted against its `attempt_id`. The capture declares the `document_type` presented — one of `PASSPORT`, `NATIONAL_ID`, `DRIVERS_LICENSE` or `RESIDENCE_PERMIT` — the `required_feature_count` of security features that document class must expose, which is between 1 and 40; the `passed_feature_count` of features that validated successfully, which is between 0 and the required count; the `tamper_signal_count` of distinct signals the forensic engine raised, which is between 0 and 20; and the boolean `mrz_checksum_valid` outcome of the machine-readable-zone checksum.

Authenticity is then assessed in six ordered steps, and the order is load-bearing.

First, `base_score_bps` is the proportion of security features that validated, expressed in basis points: ten thousand multiplied by `passed_feature_count`, divided by `required_feature_count`, rounded half up to a whole basis point. A document where every required feature validated scores exactly 10000.

Second, `tamper_tier_multiplier_bps` is read off the *pre-penalty* base score, never off any later figure. A `base_score_bps` of 9000 or more yields a multiplier of 10000; a `base_score_bps` of at least 7000 and below 9000 yields 15000; a `base_score_bps` below 7000 yields 20000. A weak document is therefore punished twice as hard per tamper signal as a clean one.

Third, `tamper_penalty_bps` is 450 basis points per tamper signal, scaled by that tier multiplier: 450 multiplied by `tamper_signal_count`, multiplied by `tamper_tier_multiplier_bps`, divided by ten thousand, truncated toward zero.

Fourth, the raw score is the base score less the tamper penalty, floored at zero so that a heavily tampered document cannot go negative.

Fifth, the machine-readable-zone cap is applied *after* the tamper penalty, never before it: when `mrz_checksum_valid` is false, `authenticity_score_bps` is the lesser of the raw score and 4000 basis points; when the checksum validated, `authenticity_score_bps` is the raw score unchanged.

Sixth, the `assessment` verdict is `AUTHENTIC` when `authenticity_score_bps` is at or above the pinned policy's `doc_authenticity_floor_bps`, `SUSPECT` when it is at least 5000 basis points but below that floor, and `FORGED` otherwise. A score exactly equal to the floor is `AUTHENTIC`; a score of exactly 5000 is `SUSPECT` and one basis point lower is `FORGED`.

The capture's `authenticity_score_bps` becomes the attempt's `evidence_quality_bps` verbatim, and the attempt's `contribution_points` is the resolved profile's `assurance_weight` multiplied by that quality, divided by ten thousand, truncated toward zero. The per-attempt truncation happens here, before any session-level summation. The attempt advances `AWAITING_EVIDENCE → SCORED`, and the session's `assurance_score_provisional` is recomputed as described in §3.8.

### 3.5. Biometric Evidence: Liveness Tuning, Consent and Template Custody

A biometric-comparison attempt is scored from a **LivenessCheck** submitted against its `attempt_id`, and two protective gates come before anything is computed. If the session's `resolved_age_band` is one of the minor bands `U13`, `B13_15` or `B16_17`, biometric processing is prohibited outright and the submission is rejected with `ERR_MINOR_BIOMETRIC_PROHIBITED`. If the session recorded `biometric_consent` as false, the submission is rejected with `ERR_BIOMETRIC_CONSENT_REQUIRED`. The minor-band gate is evaluated before the consent gate.

The check itself declares the `capture_modality` used — `PASSIVE` or `ACTIVE` — the `pad_score_bps` the presentation-attack detector returned, between 0 and 10000, and the `match_score_bps` of the biometric comparison, between 0 and 10000. The comparison score is accepted only here and is stored on the owning attempt; no other endpoint accepts it, and it stays null for every non-biometric method. The check copies the owning attempt's `retry_index` onto itself so the tuning inputs remain auditable after the fact.

The threshold the check is judged against is not the policy baseline; it is that baseline tuned three ways. Start from the pinned policy's `pad_threshold_bps`. Add a risk bump: nothing for a `LOW`-risk session, 300 basis points for `MEDIUM`, 800 basis points for `HIGH`. Add 200 basis points for each prior attempt of the same method on this session, that is, 200 multiplied by the attempt's `retry_index`. Then subtract a relief of 250 basis points when `capture_modality` is `ACTIVE`, and nothing when it is `PASSIVE`. The resulting figure is floored at zero and then capped at 9500 basis points, and that clamped result is `effective_threshold_bps`. The ceiling is applied last, so no accumulation of retries can push the bar past 9500. The design intent is explicit: an operator tightens tolerance for false accepts through the risk and retry bumps, and buys back tolerance for false rejects by asking the subject for an active capture.

The `decision` follows: `PASS` when `pad_score_bps` is at or above `effective_threshold_bps`, `INCONCLUSIVE` when `pad_score_bps` is at least 300 basis points below that threshold but still short of it, and `FAIL` otherwise. A score exactly equal to the threshold passes; a score exactly 300 basis points below it is inconclusive.

Evidence quality blends the two scores sixty-forty in favour of the comparison: six thousand multiplied by `match_score_bps`, plus four thousand multiplied by `pad_score_bps`, divided by ten thousand, truncated toward zero. A `PASS` records that blended figure as `evidence_quality_bps`. An `INCONCLUSIVE` records the blended figure halved and truncated toward zero. A `FAIL` records 0, and consequently `contribution_points` of 0 as well. As with document evidence, `contribution_points` is the profile's `assurance_weight` multiplied by `evidence_quality_bps`, divided by ten thousand, truncated toward zero, and the attempt advances `AWAITING_EVIDENCE → SCORED` with the session's provisional score recomputed.

Whenever the `decision` is anything other than `FAIL`, the biometric evidence has produced a reusable template, and a **BiometricTemplate** is created against the owning `session_id` in the `STORED` state with `source_method_code` recorded as `BIOMETRIC_COMPARISON`, and the client's `stored_template_count` increases by one. A `FAIL` produces no template at all and leaves the counter untouched. A template's custody states are `STORED`, `PURGE_SCHEDULED` and `DELETED`, with deletion terminal; while it is `STORED` on a non-terminal session its `retention_expires_at`, `deleted_at` and `deletion_reason` are all null. What happens to it when the session closes is the subject of §3.10.

### 3.6. Database and Knowledge-Based Evidence, Finalisation and the Step-Up Loop

The two non-forensic methods share one submission endpoint and are distinguished by which pair of counts the body carries. A database-check attempt supplies `matched_field_count` and `total_field_count`, and its `evidence_quality_bps` is ten thousand multiplied by the matched count, divided by the total count, truncated toward zero — so a fully matched record yields exactly 10000. A knowledge-based attempt supplies `correct_answer_count` and `question_count`, and its `evidence_quality_bps` is ten thousand multiplied by the correct count, divided by the question count, truncated toward zero. Supplying the wrong pair for the attempt's method is a schema failure. In both cases `contribution_points` is derived exactly as for the other methods — the profile's `assurance_weight` multiplied by `evidence_quality_bps`, divided by ten thousand, truncated toward zero — the attempt advances `AWAITING_EVIDENCE → SCORED`, and the session's provisional score is recomputed.

Finalisation carries no body at all and is where a scored attempt meets its vendor's acceptance bar. A `SCORED` attempt whose `evidence_quality_bps` is at or above the resolved profile's `acceptance_floor_bps` advances `SCORED → ACCEPTED`; one below the floor advances `SCORED → REJECTED`. Either outcome stamps `finalized_at` with the clock, recomputes the session's provisional score, and appends an audit event of type `ATTEMPT_FINALIZED`.

A rejection also records why, in `rejection_reason`. A document-scan attempt whose capture was assessed `FORGED` records `DOCUMENT_FORGED` and additionally sets the attempt's `tamper_flag` to true; a document-scan attempt whose capture was assessed anything else records `DOCUMENT_SUSPECT`. A biometric-comparison attempt records `LIVENESS_FAILED`, a database check records `DATA_MISMATCH`, and a knowledge-based attempt records `KBA_FAILED`. Two further reasons exist but are written elsewhere: `METHOD_RESTRICTED` by the remediation of §3.9, and `EXPIRED_WINDOW` by the sweep of §3.10.

The distinction between a merely weak rejection and a fraudulent one is the pivot of the whole identity axis. When a rejection carries `tamper_flag` true, the session moves `IN_PROGRESS → MANUAL_REVIEW` in the same request: `fraud_signal_count` — the count of that session's attempts whose `tamper_flag` is true — increases by one, a manual review case is created in `QUEUED` with `trigger_reason` of `FRAUD_SIGNAL` and its service-level deadline set as in §3.8, the provisional score is recomputed, and an audit event of type `ESCALATED_TO_REVIEW` is appended. When a rejection carries `tamper_flag` false and the session's `step_up_round` is still below the pinned policy's `step_up_max_rounds`, the session instead moves `IN_PROGRESS → AWAITING_EVIDENCE`: the provisional score is recomputed, the client's `pending_stepup_count` increases by one, and the audit event appended is of type `ATTEMPT_FINALIZED`.

A session parked at `AWAITING_EVIDENCE` is waiting for the relying party to decide whether to spend a step-up round on it. Requesting step-up requires the session to be at `AWAITING_EVIDENCE`, requires the clock not to be past `expires_at`, and requires `step_up_round` to still be below `step_up_max_rounds` — a session that has already consumed its budget is rejected with `ERR_STEP_UP_LIMIT_REACHED`. On success the session moves `AWAITING_EVIDENCE → IN_PROGRESS`, `step_up_round` increases by one, the client's `pending_stepup_count` decreases by one, and an audit event of type `STEP_UP_TRIGGERED` is appended. A policy whose `step_up_max_rounds` is 0 therefore admits no step-up at all: a non-tamper rejection on such a session leaves the identity axis at `IN_PROGRESS` and the relying party's only route forward is completion or another method.

### 3.7. The Age Assurance Axis and Inclusion Pathways

The age axis answers a single question — is the subject at least `required_min_age_years` old — and it answers it independently of whatever the identity axis is doing. Recording an **AgeAssuranceResult** requires the session's `age_state` to be `PENDING` or `FAILED`, requires the clock not to be past `expires_at`, and requires the pinned policy's `required_min_age_years` to be greater than zero; a policy with the age gate disabled leaves `age_state` at `NOT_REQUIRED` permanently and admits no results. Each result is filed under the owning `session_id` and declares its `method`, either `ESTIMATION` or `VERIFICATION`.

An `ESTIMATION` result supplies `estimated_age_months`, a model estimate between 0 and 1200 months, together with `estimation_profile_id` naming the `AGE_ESTIMATION` method profile that produced it; `date_of_birth` is forbidden. The server snapshots that profile's `vendor_code` into `source_vendor_code` and its `estimation_mae_months` into `mae_months_snapshot`, then derives the safety buffer: `buffer_months` is `mae_months_snapshot` multiplied by the pinned policy's `age_buffer_multiplier_bps`, divided by ten thousand, rounded *up* to a whole month. The `effective_age_months` used for every downstream decision is `estimated_age_months` less `buffer_months`, floored at zero. Because the buffer is subtracted before banding, a subject whose raw estimate sits above the gate can still band below it — which is the entire point of the buffer.

A `VERIFICATION` result supplies `date_of_birth` in `YYYY-MM-DD` form and forbids `estimated_age_months`; no method profile is consulted, so `source_vendor_code`, `mae_months_snapshot` and `documented_accuracy_bps` all stay null. Its `buffer_months` is 0, and its `effective_age_months` is the number of complete calendar months between `date_of_birth` and the current logical-clock date, where a month counts only once the day-of-month has been reached.

The `resolved_band` follows from `effective_age_months` alone: `U13` at 155 months or fewer, `B13_15` above 155 and at most 191, `B16_17` above 191 and at most 215, `B18_20` above 215 and at most 251, and `A21_PLUS` above 251. For an estimation result the server then reads `documented_accuracy_bps` out of the estimating profile's `band_accuracy_bps` map at exactly that band; if the vendor has published no accuracy figure for the band the estimate landed in, the result is not stored at all and the request is rejected with `ERR_AGE_ACCURACY_UNDOCUMENTED`. This is the accuracy-documentation obligation the service owes its clients: an estimate is only admissible where its error characteristics for that specific band are on record.

The `decision` is `ASSURED` when `effective_age_months` is at or above `required_min_age_years` multiplied by twelve, and `FAILED` otherwise; an effective age exactly equal to the gate is `ASSURED`. The session's `age_state` follows the decision — `PENDING → ASSURED` or `PENDING → FAILED` — and `FAILED` is deliberately re-enterable in the upward direction: a subject who failed an estimation may follow up with a verification and move `FAILED → ASSURED`. `NOT_REQUIRED` and `ASSURED` are the terminal states of this axis. Regardless of the decision, the session's `resolved_age_band` is set to the `resolved_band` of the most recent result, which is why a failed estimate that banded a subject at `U13` immediately blocks any further biometric capture on that session and, at closure, forces minor-protection deletion of any template already held.

Subjects without standard documentation are served by an **AlternativePathway**, requestable by the `ClientIntegrator` while the session's identity axis is at `IN_PROGRESS` or `AWAITING_EVIDENCE` and only when the pinned policy's `alternative_pathway_enabled` is true; otherwise the request is rejected with `ERR_ALTERNATIVE_PATHWAY_DISABLED`. The request names the owning `session_id` and a `pathway_type` of either `VOUCHING` or `ATTESTATION`, and it forks immediately on that choice: a `VOUCHING` request must carry `voucher_reference`, the reference of an accredited voucher, and opens in `VOUCH_PENDING`; an `ATTESTATION` request must carry `attestation_document_ref`, the reference of the self-attestation package, and opens in `ATTESTATION_PENDING`. The five pathway states are `VOUCH_PENDING`, `ATTESTATION_PENDING`, `APPROVED`, `DENIED` and `WITHDRAWN`, of which the last three are terminal. While pending, `reviewer_user_id`, `granted_points` and `decided_at` are all null.

An `InclusionReviewer` adjudicates the pathway by supplying `action`, either `APPROVE` or `DENY`.

Approval of a `VOUCHING` pathway (`VOUCH_PENDING → APPROVED`) requires the pathway to be pending, the session's identity axis to be at `IN_PROGRESS` or `AWAITING_EVIDENCE`, the clock not to be past `expires_at`, and at least one method profile with `method_code` of `VOUCHING_ATTESTATION` and a `bias_state` other than `RESTRICTED` to exist — an empty candidate set is rejected with `ERR_NO_ELIGIBLE_METHOD`. Among such profiles the winner is ranked by `cost_cents` ascending and then by `created_at` ascending. On approval `reviewer_user_id` records the adjudicating `X-User-ID` and `decided_at` records the clock; a method attempt is created and carried all the way to `ACCEPTED` inside the same request with `selection_mode` of `PATHWAY_GRANTED`, moving `AWAITING_EVIDENCE → ACCEPTED` directly with `finalized_at` set to the clock. That attempt's `evidence_quality_bps` is 9000 basis points, its `contribution_points` is the granting profile's `assurance_weight` multiplied by 9000, divided by ten thousand, truncated toward zero, and `granted_points` on the pathway records exactly that figure. The session's `assurance_ceiling` is left at 100. The provisional score is recomputed and an audit event of type `PATHWAY_DECIDED` is appended.

Approval of an `ATTESTATION` pathway (`ATTESTATION_PENDING → APPROVED`) runs through exactly the same preconditions, the same eligibility check with the same `ERR_NO_ELIGIBLE_METHOD` rejection, the same cost-then-age ranking, the same `reviewer_user_id` and `decided_at` writes, the same in-request creation and acceptance of a `PATHWAY_GRANTED` attempt with `finalized_at` set to the clock, the same recomputation of the provisional score, and the same `PATHWAY_DECIDED` audit event. Two things differ. That attempt's `evidence_quality_bps` is 7000 basis points rather than 9000, so its `contribution_points` — and therefore the pathway's `granted_points` — is the profile's `assurance_weight` multiplied by 7000, divided by ten thousand, truncated toward zero. And the session's `assurance_ceiling` is lowered from 100 to 70, permanently capping what a self-attested subject can be certified at. Because the ceiling is only consulted when the final score is written, lowering it changes nothing about the running provisional figure.

Denial is symmetrical across the fork: from either `VOUCH_PENDING` or `ATTESTATION_PENDING` the pathway moves to `DENIED`, `reviewer_user_id` records the adjudicating `X-User-ID`, `decided_at` records the clock, and `granted_points` stays null. No method attempt is created, the session's `assurance_score_provisional` does not change, and its `assurance_ceiling` does not change. An audit event of type `PATHWAY_DECIDED` is appended exactly as for an approval.

### 3.8. Assurance Scoring, Completion and Manual Review

Two assurance figures live on every session and they are computed differently on purpose. `assurance_score_provisional` is the running view a relying party can watch during collection: it sums the `contribution_points` of every attempt of the session currently in `SCORED` or `ACCEPTED`, and caps the sum at 100. It applies no bias haircut and it ignores `assurance_ceiling` entirely. It is rewritten on every evidence submission, every finalisation, every pathway approval, every restriction cascade, at completion, and on every review decision.

`assurance_score_final` is written exactly once, by the transition that gives the session a terminal identity state or escalates it to manual review at completion, and it is null before that. It sums only attempts in `ACCEPTED` — attempts sitting in `REQUIRES_RESCORE`, `REJECTED` or `EXPIRED` contribute nothing to either figure. For each accepted attempt, if that attempt's method profile has `bias_state` equal to `RESTRICTED` at the moment the final score is written, its contribution is halved: `contribution_points` multiplied by 5000, divided by ten thousand, truncated toward zero. Otherwise the contribution is `contribution_points` unchanged. The sum is capped at 100 and then capped again at the session's `assurance_ceiling`, whichever bound bites first. Two consequences follow directly. A profile that becomes restricted only after its attempt was accepted halves that attempt's weight in the final figure while leaving the provisional figure exactly where it was. And an attestation approval that dropped `assurance_ceiling` to 70 constrains the final figure only.

Completion carries no body and is a `ClientIntegrator` action. It requires the identity axis to be at `IN_PROGRESS` and the clock not to be past `expires_at`. It further requires that no attempt of the session is still open in `AWAITING_EVIDENCE`, `SCORED` or `REQUIRES_RESCORE`, otherwise `ERR_ATTEMPT_PENDING_FINALIZATION`; that no pathway of the session is still in `VOUCH_PENDING` or `ATTESTATION_PENDING`, otherwise `ERR_PENDING_PATHWAY_BLOCKS_COMPLETION`; and that, when the pinned policy sets `required_min_age_years` above zero, `age_state` is no longer `PENDING`, otherwise `ERR_AGE_ASSURANCE_MISSING`.

Three outcomes are possible, and the age axis is consulted first. When `age_state` is `FAILED`, the session moves `IN_PROGRESS → REJECTED`: `assurance_score_final` is written, `disposition_reason` is set to `AGE_GATE_FAILED`, `completed_at` is set to the clock, the retention schedule of §3.10 is applied to every template of the session still in `STORED`, and an audit event of type `SESSION_TERMINAL` is appended. When the age axis is not failed and the freshly written `assurance_score_final` is at or above the pinned policy's `min_assurance_score`, the session moves `IN_PROGRESS → VERIFIED` with `disposition_reason` set to `SCORE_SATISFIED`, `completed_at` set to the clock, the same retention schedule applied and the same `SESSION_TERMINAL` event appended. When the age axis is not failed and the final score falls short of `min_assurance_score`, the session moves `IN_PROGRESS → MANUAL_REVIEW`: `assurance_score_final` is still written, a manual review case is created in `QUEUED` with `trigger_reason` of `SCORE_SHORTFALL`, and an audit event of type `ESCALATED_TO_REVIEW` is appended. This third branch does not set `completed_at` and does not touch biometric templates — the session is not finished, only handed off.

A **ManualReviewCase** is always server-created, never client-created, and its `trigger_reason` is one of `FRAUD_SIGNAL`, `SCORE_SHORTFALL`, `AGE_INCONCLUSIVE` or `RESTRICTED_METHOD`. It is filed under the escalated `session_id`, opens in `QUEUED` — one of `QUEUED`, `ASSIGNED`, `DECIDED` and `WITHDRAWN`, the last two terminal — with `assigned_by_user_id`, `assigned_reviewer_user_id`, `decision`, `decided_by_user_id` and `decided_at` all null. Its `sla_due_at` is its `created_at` plus forty-eight hours on the logical clock, and the sweep withdraws it once the clock reaches or passes that instant.

Assignment is a `ReviewManager` action that names the `assigned_reviewer_user_id` expected to decide the case. It requires the case to be `QUEUED` and requires the owning client's `available_review_credits` to be at least 1, otherwise `ERR_REVIEW_CAPACITY_EXHAUSTED`. On success the case moves `QUEUED → ASSIGNED`, `assigned_by_user_id` records the manager's `X-User-ID`, and one credit is reserved — meaning `reserved_review_credits` rises by one and `available_review_credits` falls by one, the pool invariant of §2.8 holding throughout. Queued cases hold no credit at all, which is deliberate: escalation itself can never be blocked by exhausted capacity, only its assignment can.

The verdict is a `ManualReviewer` action supplying `decision`, one of `APPROVE`, `REJECT` or `RETURN_FOR_STEP_UP`. It requires the owning session's identity axis to still be at `MANUAL_REVIEW`, otherwise `ERR_SESSION_STATE_INVALID` — which, per §2.6, is evaluated before the case-state check, so a second verdict on an already-`DECIDED` case reports `ERR_SESSION_STATE_INVALID` once that first verdict has moved the session off `MANUAL_REVIEW`. It further requires the case to be `ASSIGNED`, requires the caller's `X-User-ID` to equal `assigned_reviewer_user_id`, and requires the caller's `X-User-ID` to differ from `assigned_by_user_id`. On success the case moves `ASSIGNED → DECIDED` with `decision`, `decided_by_user_id` and `decided_at` written, the reserved credit is released back to `available_review_credits`, and the client's `consumed_review_count` rises by one. An audit event of type `REVIEW_DECIDED` is appended for all three verdicts.

Each verdict drives the session out of `MANUAL_REVIEW` differently. `APPROVE` moves the session `MANUAL_REVIEW → VERIFIED`, sets `manual_override_flag` to true, sets `disposition_reason` to `MANUAL_OVERRIDE`, sets `completed_at` to the clock, writes `assurance_score_final`, and applies the retention schedule to every template still in `STORED`. `REJECT` moves the session `MANUAL_REVIEW → REJECTED` and is symmetrical in every respect except the reason: `manual_override_flag` becomes true, `disposition_reason` becomes `REVIEW_REJECTED`, `completed_at` is stamped, `assurance_score_final` is written, and the retention schedule runs. `RETURN_FOR_STEP_UP` additionally requires the clock not to be past `expires_at`, and moves the session `MANUAL_REVIEW → AWAITING_EVIDENCE`: the client's `pending_stepup_count` rises by one, and because the session is not terminal, no `assurance_score_final` is written, no `completed_at` is stamped, `manual_override_flag` stays false and no template is touched. In all three cases the credit release and the `consumed_review_count` increment happen identically.

### 3.9. Bias Testing, Method Restriction and Remediation

Demographic performance testing is a standing `ComplianceOfficer` programme, and it is the only mechanism that writes a method profile's `bias_state`. That posture cycles `CLEARED → MONITORED → RESTRICTED → MONITORED → CLEARED`, and no direct profile write can move it.

A **BiasAudit** is opened against a `method_profile_id` with a measurement window bounded by an inclusive `window_start` and an exclusive `window_end` that must be strictly later than the start. Windows on the same profile may not overlap while another audit on that profile is still live — that is, while it sits in `COLLECTING`, `EVALUATED` or `REMEDIATION_REQUIRED` — and an overlap is rejected with `ERR_AUDIT_WINDOW_OVERLAP`. Because windows are half-open, an audit that begins exactly at another's `window_end` is admissible. A new audit opens in `COLLECTING`, one of `COLLECTING`, `EVALUATED`, `REMEDIATION_REQUIRED` and `REMEDIATED`, of which only `REMEDIATED` is terminal, with `remediation_round` at 0, `remediated_at` null, `evaluated_by_user_id` and `remediated_by_user_id` null, `included_cohort_count` and `excluded_cohort_count` at 0, `insufficient_sample` false, and `max_frr_bps`, `min_frr_bps`, `pooled_frr_bps`, `disparity_ratio_max_to_min_bps`, `disparity_ratio_max_to_pooled_bps` and `worst_cohort_code` all null.

Observations arrive as **CohortMetric** rows filed under the audit's `bias_audit_id`. Each row names a `cohort_code` — one of `AGE_13_17`, `AGE_18_24`, `AGE_25_44`, `AGE_45_64`, `AGE_65_PLUS`, `SKIN_TONE_I_III` or `SKIN_TONE_IV_VI` — which must be unique within the audit, a repeat being rejected with `ERR_COHORT_DUPLICATE`. It supplies the `attempt_count` observed for that cohort inside the window, which must not be negative, along with `false_reject_count` and `false_accept_count`, each between 0 and `attempt_count`. Two rates are derived on submission: `frr_bps` is ten thousand multiplied by `false_reject_count`, divided by `attempt_count`, rounded half up, and `far_bps` is the same computation over `false_accept_count`; both are 0 when `attempt_count` is 0. The row is marked `included_in_ratio` true when its `attempt_count` is at least 50, and false below that — small cohorts are recorded and disclosed but do not drive the gate.

Evaluation requires the audit to be `COLLECTING` and requires the audited profile not to already be `RESTRICTED`, otherwise `ERR_METHOD_RESTRICTED_BY_BIAS`. The rows in scope are those cohort rows of the audit whose `created_at` is at or after the audit's `remediated_at`, or all of the audit's rows when `remediated_at` is null — this is how each remediation round starts from a clean measurement. If fewer than 3 rows are in scope, the evaluation is refused with `ERR_INSUFFICIENT_COHORT_COVERAGE` before any figure is computed.

The included set is the in-scope rows whose `included_in_ratio` is true. `included_cohort_count` is the size of that set and `excluded_cohort_count` is the number of in-scope rows less that size. `insufficient_sample` is true when fewer than two rows are included; when it is true both disparity ratios stay null, the audit still moves `COLLECTING → EVALUATED`, and the profile's `bias_state` is left exactly as it was. Otherwise `max_frr_bps` is the highest and `min_frr_bps` the lowest `frr_bps` among included rows, and `pooled_frr_bps` is ten thousand multiplied by the sum of `false_reject_count` over included rows, divided by the sum of `attempt_count` over included rows, rounded half up — a pooled rate computed from summed counts, never as an average of per-cohort rates. `worst_cohort_code` is the included cohort with the highest `frr_bps`, ties broken by `cohort_code` in ascending alphabetical order; entity identifiers are never used as a tie-break key.

Two disparity ratios are always computed and stored, and only one of them gates. `disparity_ratio_max_to_min_bps` is ten thousand multiplied by `max_frr_bps`, divided by `min_frr_bps`, rounded half up; it is null when `min_frr_bps` is 0 or when fewer than two cohorts are included, and it exists purely for disclosure and never drives a state change. `disparity_ratio_max_to_pooled_bps` is ten thousand multiplied by `max_frr_bps`, divided by `pooled_frr_bps`, rounded half up; it is null when `pooled_frr_bps` is 0 or when fewer than two cohorts are included, and it is the gating ratio. The disclosure ratio can sit far above the restriction threshold while the gating ratio only reaches monitoring, which is exactly why the gating decision uses the pooled comparator.

The gate reads the gating ratio against two thresholds, 11000 basis points for monitoring and 12500 basis points for restriction. A gating ratio of 12500 or more restricts. A gating ratio of at least 11000 but below 12500 monitors. A gating ratio below 11000 clears. Each evaluation records the acting `X-User-ID` in `evaluated_by_user_id`.

When the gating ratio is below 12500, the audit moves `COLLECTING → EVALUATED` and the profile's posture is set to `MONITORED` when the ratio is at or above 11000 and to `CLEARED` when it is below. There is one exception: when the audit's `remediation_round` is already at least 1 and the gating ratio is below 11000, the remediation programme has demonstrably worked, and the audit moves `COLLECTING → REMEDIATED` instead — a terminal state — with the profile's `bias_state` set to `CLEARED` and its `restricted_at` set back to null. All disparity fields are written in every one of these cases.

When the gating ratio reaches 12500, the audit moves `COLLECTING → REMEDIATION_REQUIRED`, all disparity fields are written, and the restriction cascades transitively through everything the profile touches. The profile's `bias_state` becomes `RESTRICTED` and its `restricted_at` records the clock. Every method attempt on that profile sitting in `AWAITING_EVIDENCE`, `SCORED` or `REQUIRES_RESCORE` moves to `REQUIRES_RESCORE` with its `contribution_points` set back to null. Every affected non-terminal session at `IN_PROGRESS` moves `IN_PROGRESS → AWAITING_EVIDENCE`, and the owning client's `pending_stepup_count` rises by one for each such session. Every pinned verification policy whose `allowed_method_codes` admits the restricted method has its `degraded_flag` set to true. Each affected session's `assurance_score_provisional` is recomputed — and because attempts in `REQUIRES_RESCORE` count for nothing, a mid-flight restriction visibly lowers the running score. Each affected session receives an audit event of type `METHOD_RESTRICTION_APPLIED`.

Remediation closes the loop and is deliberately not available to whoever ran the evaluation. It requires the audit to be `REMEDIATION_REQUIRED`, carries the profile-version guard of §2.7 through `expected_method_profile_version`, requires the acting `X-User-ID` to differ from `evaluated_by_user_id`, and takes a `remediation_note` recording what was done. On success the audit moves `REMEDIATION_REQUIRED → COLLECTING`, its `remediation_round` rises by one, `remediated_at` records the clock — thereby scoping the next evaluation to cohort rows created from that instant onward — and `remediated_by_user_id` records the acting user. The profile moves `RESTRICTED → MONITORED` with `restricted_at` set back to null, and its `version` increments by one. Every attempt still in `REQUIRES_RESCORE` on that profile is closed out rather than resurrected: it moves `REQUIRES_RESCORE → REJECTED` with `rejection_reason` of `METHOD_RESTRICTED`, `contribution_points` of 0 and `finalized_at` set to the clock, and each owning session's provisional score is recomputed. Finally, `degraded_flag` is cleared on every policy that no longer admits any restricted profile.

### 3.10. Biometric Retention, SLA Lapse and the Operations Sweep

Every transition that gives a session a terminal identity state resolves the custody of every biometric template that session still holds in `STORED`. Four rules are consulted strictly in this precedence order, and the first that matches decides the template's fate.

First, if the session's `resolved_age_band` is one of the minor bands `U13`, `B13_15` or `B16_17`, the template is deleted immediately with `deletion_reason` of `MINOR_PROTECTION`. This rule deliberately outranks everything below it, so a client configured for `RETAIN_90_DAYS` still loses a minor's template at once. Second, if the client's `biometric_retention_mode` is `DELETE_ON_COMPLETE`, the template is deleted immediately with `deletion_reason` of `POLICY_IMMEDIATE`. Third, if the client's mode is `RETAIN_WITH_CONSENT` and the session's `biometric_consent` is false, the template is deleted immediately with `deletion_reason` of `CONSENT_ABSENT`. Fourth and otherwise, the template moves `STORED → PURGE_SCHEDULED` and its `retention_expires_at` is set to the session's `completed_at` plus ninety days on the logical clock, preserving the time of day.

An immediate deletion moves the template `STORED → DELETED`, stamps `deleted_at` with the clock, and appends an audit event of type `TEMPLATE_DELETED`. Whether a template is deleted at once or merely scheduled for purge, the client's `stored_template_count` decrements exactly once, at the moment the template leaves `STORED`. A session that never captured biometrics produces no template work at all and leaves the counter untouched.

The operations sweep is the `PlatformAdmin` capability that materialises every deadline the logical clock has passed. It takes no input and reports four figures: `expired_session_count`, `withdrawn_case_count`, `deleted_template_count`, and `swept_at`, the clock instant at which the sweep ran.

The sweep first lapses overdue sessions. Any session whose identity axis is at `IN_PROGRESS` or `AWAITING_EVIDENCE` and whose `expires_at` the clock has passed moves to `EXPIRED`. Every attempt of that session in `AWAITING_EVIDENCE`, `SCORED` or `REQUIRES_RESCORE` moves to `EXPIRED` with `rejection_reason` of `EXPIRED_WINDOW` and `finalized_at` set to the clock. Every pathway of that session in `VOUCH_PENDING` or `ATTESTATION_PENDING` moves to `WITHDRAWN` with `decided_at` set to the clock and `reviewer_user_id` left null. The session's `disposition_reason` becomes `EXPIRED_TTL` and its `completed_at` is stamped, the retention rules above are applied to every template still in `STORED`, and an audit event of type `SESSION_TERMINAL` is appended. Where the lapsing session was sitting at `AWAITING_EVIDENCE`, the client's `pending_stepup_count` decreases by one; where it was at `IN_PROGRESS`, it was never counted there and no adjustment is made. Lapse writes no `assurance_score_final`: an expired session's final score stays null, because nothing was ever adjudicated.

The sweep then withdraws review cases that have blown their service level. Any case in `QUEUED` or `ASSIGNED` whose `sla_due_at` the clock has reached or passed moves to `WITHDRAWN` with `decided_at` set to the clock; a case at exactly its deadline is withdrawn, the comparison being inclusive. A credit is released only when the withdrawn case was `ASSIGNED` — a case withdrawn straight out of `QUEUED` had reserved nothing, so nothing is released, and `consumed_review_count` does not move for a withdrawal in either case since it counts only cases that reached `DECIDED`. The abandoned session moves `MANUAL_REVIEW → REJECTED` with `disposition_reason` of `REVIEW_LAPSED` and `completed_at` set to the clock, `assurance_score_final` is written, the retention rules are applied to every template still in `STORED`, and an audit event of type `SESSION_TERMINAL` is appended.

The sweep finally purges deferred templates. Any template in `PURGE_SCHEDULED` whose `retention_expires_at` the clock has reached or passed moves `PURGE_SCHEDULED → DELETED` with `deleted_at` set to the clock and `deletion_reason` of `RETENTION_EXPIRED`, and an audit event of type `TEMPLATE_DELETED` is appended; a template whose deadline exactly equals the clock is deleted, the comparison being inclusive. Because the count was already decremented when the template left `STORED`, this second step does not touch `stored_template_count` again.

## 4. Endpoint Definitions

Requests that mint a new resource — a client, a method profile, a policy draft, a session, an attempt, an evidence row, an age result, a pathway request, an audit or a cohort row — return `201 Created`. Requests that modify an existing resource, including every state-transition action, every patch, the operations sweep and the clock control, return `200 OK`. All list and read requests return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/idv/clients` | Register a relying-party client with its retention mode, quota and manual-review credit pool | PlatformAdmin |
| PATCH | `/idv/clients/{id}` | Adjust a client's integration posture, retention mode, quota or credit grant | PlatformAdmin |
| GET | `/idv/clients/{id}` | Read one client with its live credit pool and custody counters | PlatformAdmin, ComplianceOfficer, ClientIntegrator |
| POST | `/idv/method-profiles` | Register a vendor method profile with its assurance weight, acceptance floor and documented error rates | PlatformAdmin |
| GET | `/idv/method-profiles/{id}` | Read one method profile with its bias posture and documented error rates | PlatformAdmin, ComplianceOfficer, ClientIntegrator |
| GET | `/idv/method-profiles/{id}/bias-audits` | List the bias audits recorded against one method profile | PlatformAdmin, ComplianceOfficer |
| POST | `/idv/verification-policies` | Draft a client verification policy: method ladder, score floor, document and liveness thresholds, age gate, step-up budget and inclusion switch | ClientIntegrator, ComplianceOfficer |
| POST | `/idv/verification-policies/{id}/publish` | Publish a draft policy, retiring the client's current published policy under optimistic concurrency on the client version | ComplianceOfficer |
| GET | `/idv/verification-policies/{id}` | Read one verification policy | PlatformAdmin, ComplianceOfficer, ClientIntegrator |
| GET | `/idv/verification-policies` | List verification policies, filterable by client and publication state | PlatformAdmin, ComplianceOfficer, ClientIntegrator |
| POST | `/idv/verification-sessions` | Open a verification session, pin the client's published policy, and freeze the risk assessment | ClientIntegrator |
| GET | `/idv/verification-sessions/{id}` | Read one verification session with both state axes, both scores and the disposition | PlatformAdmin, ComplianceOfficer, ClientIntegrator, ReviewManager, ManualReviewer, InclusionReviewer |
| GET | `/idv/verification-sessions` | List verification sessions, filterable by client, pinned policy, either state axis and subject reference | PlatformAdmin, ComplianceOfficer, ClientIntegrator |
| POST | `/idv/verification-sessions/{id}/method-attempts` | Start a verification attempt, either on an explicitly requested profile or on the winner of the risk-aware method selector | ClientIntegrator |
| POST | `/idv/verification-sessions/{id}/age-assurance-results` | Record an age estimation or age verification result with its documented accuracy and band | ClientIntegrator |
| GET | `/idv/verification-sessions/{id}/age-assurance-results` | List the age assurance results recorded for one session, newest last by creation time | PlatformAdmin, ComplianceOfficer, ClientIntegrator, ManualReviewer |
| POST | `/idv/verification-sessions/{id}/step-up` | Consume one step-up round and return a session awaiting evidence to in-progress | ClientIntegrator |
| POST | `/idv/verification-sessions/{id}/complete` | Close an in-progress session: write the final assurance score and resolve the disposition, escalating to manual review when the score falls short | ClientIntegrator |
| POST | `/idv/verification-sessions/{id}/alternative-pathways` | Request an inclusion pathway for a subject without standard documentation; the request forks on pathway type | ClientIntegrator |
| GET | `/idv/verification-sessions/{id}/alternative-pathways` | List the inclusion pathways requested for one session | PlatformAdmin, ComplianceOfficer, ClientIntegrator, InclusionReviewer |
| GET | `/idv/verification-sessions/{id}/biometric-templates` | List the biometric templates held for one session with their custody state and retention deadline | PlatformAdmin, ComplianceOfficer |
| GET | `/idv/verification-sessions/{id}/manual-review-cases` | List the manual review cases raised for one session | PlatformAdmin, ComplianceOfficer, ReviewManager, ManualReviewer |
| GET | `/idv/verification-sessions/{id}/audit-events` | List the append-only audit trail of one session | PlatformAdmin, ComplianceOfficer |
| POST | `/idv/method-attempts/{id}/document-captures` | Submit a document capture for a document-scan attempt and assess authenticity with tamper detection and security-feature validation | ClientIntegrator |
| GET | `/idv/method-attempts/{id}/document-captures` | List the document captures submitted for one attempt | PlatformAdmin, ComplianceOfficer, ClientIntegrator, ManualReviewer |
| POST | `/idv/method-attempts/{id}/liveness-checks` | Submit liveness and comparison scores for a biometric-comparison attempt and apply the tuned presentation-attack threshold | ClientIntegrator |
| GET | `/idv/method-attempts/{id}/liveness-checks` | List the liveness checks submitted for one attempt | PlatformAdmin, ComplianceOfficer, ClientIntegrator, ManualReviewer |
| POST | `/idv/method-attempts/{id}/data-evidence` | Submit database-check field matches or knowledge-based answer counts for the attempt | ClientIntegrator |
| POST | `/idv/method-attempts/{id}/finalize` | Finalise a scored attempt against its profile acceptance floor, driving step-up or fraud escalation on the session | ClientIntegrator |
| GET | `/idv/method-attempts/{id}` | Read one method attempt with its evidence quality and contribution | PlatformAdmin, ComplianceOfficer, ClientIntegrator, ManualReviewer |
| GET | `/idv/method-attempts` | List method attempts, filterable by session, profile and state | PlatformAdmin, ComplianceOfficer, ClientIntegrator, ManualReviewer |
| POST | `/idv/alternative-pathways/{id}/decision` | Approve or deny an inclusion pathway; approval grants a vouching-attestation attempt and, for attestation, lowers the session assurance ceiling | InclusionReviewer |
| POST | `/idv/manual-review-cases/{id}/assign` | Assign a queued escalation to a named reviewer, reserving one manual-review credit | ReviewManager |
| POST | `/idv/manual-review-cases/{id}/decision` | Record the reviewer verdict, releasing the reserved credit and driving the session out of manual review | ManualReviewer |
| POST | `/idv/bias-audits` | Open a demographic performance audit over a measurement window for one method profile | ComplianceOfficer |
| GET | `/idv/bias-audits/{id}` | Read one bias audit with both disparity ratios and the cohort coverage counters | PlatformAdmin, ComplianceOfficer |
| POST | `/idv/bias-audits/{id}/cohort-metrics` | Add one demographic cohort's attempt, false-reject and false-accept counts to a collecting audit | ComplianceOfficer |
| GET | `/idv/bias-audits/{id}/cohort-metrics` | List the cohort rows attached to one bias audit | PlatformAdmin, ComplianceOfficer |
| POST | `/idv/bias-audits/{id}/evaluate` | Evaluate cohort disparity, set the profile's bias posture and cascade any restriction into live sessions | ComplianceOfficer |
| POST | `/idv/bias-audits/{id}/remediation` | Record disparity remediation under optimistic concurrency on the method profile version, lifting the restriction and clearing rescore-blocked attempts | ComplianceOfficer |
| POST | `/idv/retention-sweeps` | Operations sweep that lapses overdue sessions, withdraws review cases past SLA and deletes biometric templates whose retention window has closed | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving endpoint that sets the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_CLIENT_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_REVIEW_ASSIGNEE_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_METHOD_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_PATHWAY_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_AGE_ACCURACY_UNDOCUMENTED` | 422 Unprocessable Entity |
| `ERR_SESSION_STATE_INVALID` | 409 Conflict |
| `ERR_ATTEMPT_STATE_INVALID` | 409 Conflict |
| `ERR_POLICY_STATE_INVALID` | 409 Conflict |
| `ERR_PATHWAY_STATE_INVALID` | 409 Conflict |
| `ERR_REVIEW_CASE_STATE_INVALID` | 409 Conflict |
| `ERR_AUDIT_STATE_INVALID` | 409 Conflict |
| `ERR_STALE_CLIENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_METHOD_PROFILE_VERSION` | 412 Precondition Failed |
| `ERR_CLIENT_NOT_LIVE` | 409 Conflict |
| `ERR_PINNED_POLICY_RETIRED` | 409 Conflict |
| `ERR_METHOD_RESTRICTED_BY_BIAS` | 409 Conflict |
| `ERR_MINOR_BIOMETRIC_PROHIBITED` | 409 Conflict |
| `ERR_BIOMETRIC_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_NO_PUBLISHED_POLICY` | 409 Conflict |
| `ERR_METHOD_NOT_IN_POLICY` | 409 Conflict |
| `ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE` | 409 Conflict |
| `ERR_EVIDENCE_METHOD_MISMATCH` | 409 Conflict |
| `ERR_EVIDENCE_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_METHOD_PROFILE_DUPLICATE` | 409 Conflict |
| `ERR_POLICY_VERSION_DUPLICATE` | 409 Conflict |
| `ERR_COHORT_DUPLICATE` | 409 Conflict |
| `ERR_SESSION_EXPIRED` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_ELIGIBLE_METHOD` | 409 Conflict |
| `ERR_STEP_UP_LIMIT_REACHED` | 409 Conflict |
| `ERR_ATTEMPT_PENDING_FINALIZATION` | 409 Conflict |
| `ERR_PENDING_PATHWAY_BLOCKS_COMPLETION` | 409 Conflict |
| `ERR_ALTERNATIVE_PATHWAY_DISABLED` | 409 Conflict |
| `ERR_AGE_ASSURANCE_MISSING` | 409 Conflict |
| `ERR_INSUFFICIENT_COHORT_COVERAGE` | 409 Conflict |
| `ERR_REVIEW_CAPACITY_EXHAUSTED` | 409 Conflict |
| `ERR_CLIENT_DAILY_QUOTA_EXCEEDED` | 409 Conflict |
