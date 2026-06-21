# Background Check FCRA API — Product Requirements Document

## 1. Introduction

Hiring organizations operating across multiple US jurisdictions face an unforgiving compliance surface. The federal Fair Credit Reporting Act (FCRA) sets a floor for how consumer-report-based hiring decisions must be conducted — written disclosure, signed consent, a Pre-Adverse Action notice followed by a mandatory waiting period, and a Final Adverse Action separately issued — while state-level overlays add Ban-the-Box restrictions on when criminal-history inquiries may occur and Salary History bans that forbid eliciting compensation history during application. A single misstep, such as ordering a background check before a conditional offer in a Ban-the-Box state or finalizing an adverse action a day too early, exposes the employer to statutory damages.

This document specifies the Background Check & Adverse Action API: a compliance-audit service that orchestrates the entire workflow — applicant onboarding, jurisdiction-aware consent capture, three parallel verification streams (criminal records, motor-vehicle records, and education), Pre-Adverse and Final Adverse Action with strict segregation of duties between the Recruiter and the Compliance Officer, and a tamper-evident audit trail. The service is mounted under the `/api/v1` URL prefix and is designed to be driven by a test-controlled logical clock so that the FCRA waiting period and other time-sensitive transitions can be exercised deterministically.

The product manager's intent is twofold. First, structural correctness: every state transition is gated by the precise legal precondition, and every cascade — order completion driving Pre-Adverse Action, dispute resolution restoring the order's clear posture, finalization rejecting the parent application — is propagated atomically. Second, evidentiary integrity: optimistic concurrency control on the writes most prone to race conditions, plus an append-only audit log, ensures that an external auditor can reconstruct every decision after the fact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to a non-public endpoint must include two HTTP headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request missing either header is rejected with `ERR_MISSING_AUTH` (HTTP 401). A request whose `X-User-Role` does not match one of the declared role names below is rejected with `ERR_INVALID_ROLE` (HTTP 401). When the role is authenticated but is not permitted to call the requested endpoint, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The system recognises exactly five roles:

- `PlatformAdmin` — operates the platform: creates Jurisdiction rows and drives the test-only logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, in the audit log as `actor_user_id`) but does not compare it to any entity's `id`.
- `Applicant` — the job applicant. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an `Applicant` compare the resource's foreign-key field — `Application.applicant_id`, or the applicant chain via `ConsentDisclosure.application_id`, `BackgroundCheckOrder.application_id`, `Verification.order_id`, and `AdverseAction.order_id` — back to `X-User-ID`.
- `Recruiter` — the hiring manager. When `X-User-Role` is `Recruiter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (notably as `actor_user_id` on the audit log entry stamped when the conditional offer is extended) but does not compare it to any entity's `id`.
- `ComplianceOfficer` — the officer authorised to issue final adverse actions and read the audit log. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. On finalization the server captures it both as `actor_user_id` on the new audit row and on the AdverseAction's `finalized_by_user_id` field, and uses it for the segregation-of-duties comparison described in §2.7.
- `VerificationProvider` — the third-party screener that reports and resolves individual verifications. When `X-User-Role` is `VerificationProvider`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

All list endpoints accept two optional query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and must not exceed 100. `offset` defaults to 0 and must be a non-negative integer. List results are returned sorted by `created_at` in ascending order so that pages reflect a stable insertion-order timeline. The `meta` envelope for list responses includes `limit`, `offset`, `total_count` (the total number of rows matching the filter), and `has_more` (true when more rows exist past the current page).

### 2.4. Common Resource Properties and the Test-Driven Clock

Every business resource — Applicant, Application, ConsentDisclosure, BackgroundCheckOrder, Verification, and AdverseAction — carries four system-managed fields. The `id` is a server-minted UUID, with no type prefix and no embedded semantics. The `created_at` is an ISO 8601 UTC timestamp recorded at insertion time with three fractional digits. The `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation. The `version` is an integer that starts at 1 on creation and increments by one on every mutation; it is the value clients carry forward to drive optimistic concurrency control.

Two infrastructural rows are exceptions to this convention. The Jurisdiction row carries `id` and `created_at` but neither `updated_at` nor `version`. The SystemClock and AuditLog rows likewise carry `id` and `created_at` but neither `updated_at` nor `version`. The SystemClock is a true singleton: its `id` is always the literal string `singleton`, and its `current_utc` field is a mutable test-controlled wall clock. All server-stamped timestamps and waiting-period comparisons read from `current_utc`, never from operating-system time, so that tests can fast-forward arbitrary intervals deterministically. The AuditLog is an append-only stream ordered ascending by `created_at` for tamper-evidence, with each row carrying `actor_role`, `actor_user_id`, `action` (a short verb tag such as `CONSENT_GRANT`, `ORDER_CREATE`, `VERIFICATION_REPORT`, `PRE_ADVERSE_SEND`, or `FINAL_ADVERSE_ISSUE`), `entity_type`, `entity_id`, and the optional pair `prior_state` and `new_state` describing the transition (both null for pure-create actions).

### 2.5. Nested Resource Retrieval and Cascading Mutations

Several endpoints expose a sub-resource form for FK reverse-reachability — listing the consents under an application, the verifications under an order, or the (at most one) adverse-action under an order. For these endpoints the path is validated left-to-right: the leftmost path parameter must resolve first; if it does not, the rejection is `ERR_NOT_FOUND` (HTTP 404) for the leftmost unresolved id, even if a later id in the same path is also missing.

Whenever an operation mutates more than one entity, every mutated entity has its `updated_at` refreshed and its `version` incremented. The single most consequential cascade is order completion: when a `BackgroundCheckOrder` settles into `COMPLETE` with an `overall_result` of `CONSIDER`, a new `AdverseAction` row is auto-created in `PRE_ADVERSE_SENT` as part of the same logical step. Conversely, when a dispute resolution flips the order's `overall_result` back to `CLEAR`, the order's existing `AdverseAction` transitions to `CANCELLED` in the same step. In both directions every touched row — order, adverse-action, the resolving verification — has its `version` bumped.

### 2.6. Optimistic Concurrency Control

Two specific writes are guarded by optimistic concurrency control, because legitimate sibling traffic on the same parent — a conditional offer being extended, a verification being disputed and then resolved — can advance the parent's `version` between the moment a client reads and the moment it writes.

The first guarded write is creating a `BackgroundCheckOrder`. The request must carry `expected_application_version` as a non-optional field. The server compares it against the target `Application`'s current `version`; if another writer has advanced the application's `version` since the client last observed it — for instance, the application has legitimately moved from `SUBMITTED` to `CONDITIONAL_OFFER`, or has been withdrawn — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the recruiter to re-read and re-decide before retrying.

The second guarded write is finalizing an `AdverseAction`. The request must carry `expected_adverse_action_version` as a non-optional field. The server compares it against the target `AdverseAction`'s current `version`; if a sibling write — for example a verification dispute cascading the adverse action to `DISPUTED`, or a downstream resolution auto-cancelling it back to `CANCELLED` — has advanced that `version` since the Compliance Officer last observed it, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412). Without this check the segregation-of-duties and waiting-period re-checks could be bypassed by acting on stale state.

Every other mutating endpoint that takes an `expected_*_version` field (application submit, conditional offer, hire, withdraw, consent grant, consent revoke, order cancel, verification report, verification dispute, verification resolve) likewise requires that field as part of the request payload and rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412). Endpoints not enumerated here — list endpoints, gets, applicant creation, application creation, jurisdiction creation, the clock setter, and the verification-create sub-resource — do not take a version field.

### 2.7. Segregation of Duties

Finalizing an Adverse Action requires that the Compliance Officer issuing the finalize be a different operator from the Recruiter who extended the parent application's conditional offer. The conditional-offer audit row captures the Recruiter's `X-User-ID`; on the finalize call the server compares the acting `X-User-ID` against that recorded operator. If the two are equal, the finalize is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The Compliance Officer's `X-User-ID` is also stamped onto the AdverseAction's `finalized_by_user_id` field as the durable record of who finalized.

### 2.8. Numerical Precision and the Federal Waiting-Period Floor

The applicant risk score (described in §3.7) is reported as a number between 0.00 and 1.00, rounded half-up to two decimal places. The rounding occurs at every step: each verification stream's contribution is rounded half-up to two decimals before being summed, and the final sum is itself rounded half-up to two decimals. The order is pinned — round-then-sum, never sum-then-round — because when two contributions round in opposite directions, the two orderings produce different totals.

Datetime arithmetic for the FCRA waiting period preserves millisecond precision. The `earliest_final_at` timestamp on an AdverseAction is computed by adding the parent jurisdiction's `pre_adverse_waiting_days` (interpreted as a calendar-day count) to the `pre_adverse_sent_at` baseline, preserving the time-of-day component rather than rounding to a day boundary. The waiting-period check at finalize time is inclusive: the finalize is permitted when `current_utc` is at or after `earliest_final_at`, not strictly later. The federal minimum waiting period is five calendar days; a jurisdiction created or updated with a `pre_adverse_waiting_days` value below 5 is rejected with `ERR_BELOW_FEDERAL_FLOOR` (HTTP 422).

### 2.9. Validation Priority Order

When more than one validation could fail on the same request, the server evaluates them in this fixed priority order so that the rejection is deterministic and the most diagnostic error surfaces first:

1. Authentication first — the `X-User-ID` and `X-User-Role` headers must both be present (otherwise `ERR_MISSING_AUTH`).
2. Then the role must be one of the five declared roles (otherwise `ERR_INVALID_ROLE`).
3. Then the role must have permission for the requested endpoint (otherwise `ERR_UNAUTHORIZED`).
4. Then every id referenced in the URL path and every foreign key in the body must resolve (otherwise `ERR_NOT_FOUND`).
5. Then the target entity must be in a state from which the requested transition is legal (otherwise `ERR_INVALID_STATE`).
6. Then, on the two writes guarded by §2.6, the `expected_*_version` value must equal the current parent `version` (otherwise `ERR_STALE_VERSION`).
7. Then the business-safety, business-temporal, business-referential, and business-constraint rules of §3 apply in the order listed in §3.
8. Body schema well-formedness — types, enum membership, and presence of required fields — is checked last and rejected with `ERR_INVALID_REQUEST` (HTTP 400).

This means a request whose body is also malformed but is on top of that unauthorised will surface as `ERR_UNAUTHORIZED`, not `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Applicant and Anchoring the Application

A workflow begins when an applicant is registered. Either the applicant themselves or a recruiter may register an `Applicant` row by supplying `full_name` (the applicant's legal full name), `email` (a unique email, lowercased on store), and `date_of_birth` (an ISO 8601 date used later for identity matching on consumer reports).

With an applicant in hand, an `Application` is opened by supplying `applicant_id`, `jurisdiction_id`, and a `position_title` for the role being applied to. The application begins in `DRAFT`. A `salary_history_disclosed` field is also accepted at creation time and represents the applicant's previously disclosed compensation; it defaults to null. The pinned `jurisdiction_id` is decisive: it determines whether the salary-history ban and the ban-the-box gate apply throughout the rest of the workflow. The `Application` also carries a `conditional_offer_at` timestamp that is null until the conditional offer is extended.

Each US-state `Jurisdiction` is created by a `PlatformAdmin` from a `state_code` (a two-letter uppercase US state code, unique across jurisdictions, with length exactly two), a `ban_the_box_enabled` boolean (default false; when true, criminal history may not be inquired about before a conditional offer), a `salary_history_ban_enabled` boolean (default false; when true, `salary_history_disclosed` on an Application must remain null at submission), and `pre_adverse_waiting_days` (an integer, default 5, that must be at least 5 — the FCRA federal floor; lower values are rejected with `ERR_BELOW_FEDERAL_FLOOR`). The same federal-floor check applies to a jurisdiction update.

### 3.2. Capturing Consent

Before any background check may be ordered, a `ConsentDisclosure` must be captured and granted. An applicant opens a consent by supplying `application_id`, `disclosure_text_version` (a version tag of the FCRA disclosure shown, for example `v2024-01`, stored for audit), `signed_at` (the ISO 8601 timestamp at which the applicant clicked Accept), and `ip_address` (the client IP captured at consent). The consent is inserted with `consent_status` set to `PENDING`. At most one consent per `application_id` may be open at a time — that is, at most one consent with `consent_status` in `PENDING` or `GRANTED`. A second consent opened against an application that already has an open consent is rejected with `ERR_CONSENT_ALREADY_OPEN`.

The applicant then grants the consent, carrying `expected_consent_disclosure_version` so that two concurrent grant attempts do not silently overwrite each other. Granting is only valid from `PENDING`, and only when `signed_at` is at or before the system clock's `current_utc` (no future-dated grants). On success the consent advances from `PENDING` to `GRANTED`, its `version` is incremented, and an audit row with action `CONSENT_GRANT` is appended.

An applicant may revoke a granted consent up until the moment that a background-check order made against that consent has begun reporting. Revocation requires `expected_consent_disclosure_version`. If any `BackgroundCheckOrder` tied to the consent has reached `IN_REVIEW` or `COMPLETE`, the revoke is rejected with `ERR_CONSENT_REVOKE_TOO_LATE`. When the revoke is permitted, the consent transitions from `GRANTED` to `REVOKED`; if a `PENDING` order existed against this consent, it cascade-cancels to `CANCELLED`, and each of that order's `PENDING` `Verification` children transitions to `RESOLVED` with `result` left null, with every touched row's `version` incremented.

Submitting a `DRAFT` application requires that the application have at least one consent in `GRANTED` status. It also enforces the salary-history ban: in a jurisdiction with `salary_history_ban_enabled` set to true, the application's `salary_history_disclosed` must be null at submission, otherwise the submit is rejected with `ERR_SALARY_HISTORY_DISCLOSED_BANNED`. The submit call carries `expected_application_version`; on success the application advances from `DRAFT` to `SUBMITTED`, its `version` is incremented, and an audit row is appended with action `APPLICATION_SUBMIT`. An applicant may withdraw the application from either `DRAFT` or `SUBMITTED` by submitting the withdraw call with `expected_application_version`; on success the application advances to `WITHDRAWN`, a terminal state.

### 3.3. The Ban-the-Box Gate and the Conditional Offer

The conditional offer is the operational pivot of the workflow. A `Recruiter` extends the conditional offer to a `SUBMITTED` application, carrying `expected_application_version`; on success the application advances from `SUBMITTED` to `CONDITIONAL_OFFER`, `conditional_offer_at` is stamped from `current_utc`, the `version` is incremented, and an audit row with action `CONDITIONAL_OFFER` is appended. The Recruiter's `X-User-ID` is captured on that audit row and is what the segregation-of-duties check (§2.7) will later compare against.

Creating a `BackgroundCheckOrder` requires `application_id`, `consent_id`, and `expected_application_version`. In a jurisdiction with `ban_the_box_enabled` set to true, the parent application's `status` must be `CONDITIONAL_OFFER` — `SUBMITTED` is not enough. An attempt against a `SUBMITTED` application in such a jurisdiction is rejected with `ERR_BAN_THE_BOX_PREMATURE_INQUIRY`. The referenced consent must satisfy two conditions: its `consent_status` must be `GRANTED`, and its applicant chain — the consent's `application_id` resolves to an application whose `applicant_id` matches the order's application's `applicant_id` — must match the order's application. A consent that is not granted, or that belongs to a different applicant, is rejected with `ERR_CONSENT_NOT_GRANTED`. On success the order is inserted with `status` `PENDING` and `ordered_at` stamped from `current_utc`, and the parent application's `version` is incremented.

### 3.4. The Three Parallel Verification Streams

A background check order has exactly three child `Verification` rows — one of each `verification_type`: `CRIMINAL`, `MVR`, and `EDUCATION`. The recruiter creates each by supplying only the `verification_type`; the row is inserted in `PENDING` with `order_id` set to the parent order. A second verification of a type already present on the same order is rejected with `ERR_DUPLICATE_VERIFICATION_TYPE`.

When a `VerificationProvider` reports a verification, the call carries `result` (either `PASS` or `FAIL`), `report_payload` (a free-form JSON object capturing verification-specific evidence — for example, conviction details on a criminal record, license issues on an MVR record, or a degree mismatch on education), and `expected_verification_version`. Reporting is only legal from `PENDING`, and only when the parent order's `status` is `PENDING` or `IN_REVIEW`. On success the verification advances from `PENDING` to `REPORTED`, with `result`, `report_payload`, and `reported_at` set and `version` incremented.

The parent order's posture is recomputed after every report. The order's `status` is computed from its three children: `PENDING` until any child is non-`PENDING`; `IN_REVIEW` once at least one child has reported but at least one remains `PENDING`; `COMPLETE` once all three are in `REPORTED` or `RESOLVED` (the system also bridges any sibling that was `REPORTED` to `RESOLVED` as part of the same transition). The first report on a `PENDING` order normally drives the order from `PENDING` to `IN_REVIEW`; if all three reports land in the same logical step before any `IN_REVIEW` snapshot is observable, the order transitions directly from `PENDING` to `COMPLETE`. When the order's `status` actually changes, its `version` is incremented; if a sibling reports while the order is already `IN_REVIEW` without changing the order's `status`, the order's `version` is not incremented.

The order's `overall_result` is computed at the moment the order's `status` reaches `COMPLETE`, and recomputed whenever a child verification changes status while the order is `COMPLETE`. Each verification contributes its current effective `result`: a `REPORTED` row contributes its `result`; a `DISPUTED` row continues to contribute its original `result` while the dispute is open; a `RESOLVED` row contributes the post-resolution `result`, which may differ from what was originally reported; a `PENDING` row cannot enter this calculation because the calculation only fires once the order's `status` is `COMPLETE`. The calculation reads the three effective results and returns `CONSIDER` if any one of them is `FAIL`, otherwise `CLEAR`. The initial completion variant reads each child's reported `result`; the post-dispute recompute variant reads each child's current `result`, where the just-resolved row's value may have flipped from `FAIL` to `PASS`, so the two variants can produce different `overall_result` values for what started as identical inputs.

Whenever the order's status recompute lands on `COMPLETE` with `overall_result` equal to `CONSIDER` — whether via the `IN_REVIEW` to `COMPLETE` transition or via the atomic-burst `PENDING` to `COMPLETE` transition — the cascade also auto-creates a single `AdverseAction` row in `PRE_ADVERSE_SENT`, with `pre_adverse_sent_at` stamped from `current_utc` and `earliest_final_at` computed (per §3.5). This is the bridge from order completion to the adverse-action workflow; it fires exactly once.

A recruiter may cancel a `PENDING` order. The cancel call carries `expected_background_check_order_version`; on success the order transitions from `PENDING` to `CANCELLED`, and each child verification that was still `PENDING` transitions to `RESOLVED` with `result` left null, with every touched row's `version` incremented.

### 3.5. Disputes and the Compensating-Action Invariant

When a `REPORTED` verification carries a finding the applicant believes to be wrong, the applicant disputes it. The dispute call carries `dispute_reason` (the applicant's text explanation) and `expected_verification_version`. Disputing is only legal from `REPORTED`, and only when the parent order's `status` is `IN_REVIEW` or `COMPLETE`. If the parent order already has an `AdverseAction`, that `AdverseAction` must still be in `PRE_ADVERSE_SENT` — a dispute after the adverse action has reached `FINALIZED` is not accepted (rejected with `ERR_INVALID_STATE`). On success the verification advances from `REPORTED` to `DISPUTED`, `disputed_at` is stamped from `current_utc`, and the verification's `version` is incremented. If a parent `AdverseAction` exists in `PRE_ADVERSE_SENT`, that `AdverseAction` cascades from `PRE_ADVERSE_SENT` to `DISPUTED` and its `version` is incremented.

A `VerificationProvider` resolves a `DISPUTED` verification by supplying `new_result` (either `PASS` or `FAIL`) and `expected_verification_version`. On success the verification advances from `DISPUTED` to `RESOLVED`, the `result` field is replaced with the `new_result`, and the `version` is incremented. If the parent order's `status` is `COMPLETE`, the order's `overall_result` is recomputed and the order's `version` is incremented. Two compensating-action sub-cases follow. If the recompute yields `CLEAR` and an `AdverseAction` exists, that adverse action transitions to `CANCELLED` with its `version` incremented; the parent `Application` is deliberately NOT auto-rejected — this is the compensating-action invariant, because the adverse action is being withdrawn rather than honored. If the recompute leaves `overall_result` at `CONSIDER` and no child verifications remain `DISPUTED`, any parent `AdverseAction` that had been cascaded to `DISPUTED` cycles back from `DISPUTED` to `PRE_ADVERSE_SENT` with its `version` incremented, re-enabling the eventual finalize.

When the parent order transitions to `COMPLETE` and a sibling is in `REPORTED`, the system also moves that sibling from `REPORTED` to `RESOLVED` as part of the same logical step, with its `version` incremented; this is the order-completion bridge that keeps every child in `RESOLVED` once the parent is terminal.

### 3.6. Pre-Adverse Action, the FCRA Waiting Period, and Finalization

The `AdverseAction` row is the legal artifact corresponding to the Pre-Adverse Action notice. Each adverse-action carries `order_id` (the parent background-check order, exactly one adverse-action per order), `status`, `pre_adverse_sent_at` (the clock baseline, stamped on row creation), `earliest_final_at` (the computed timestamp at which finalization first becomes legal), `finalized_at` (null until the Compliance Officer finalizes), `finalized_by_user_id` (null until finalization), and `dispute_reason` (the optional applicant-supplied dispute text, set only when the adverse-action's `status` transitions through `DISPUTED`).

The `earliest_final_at` value is computed once, at row creation: the system takes `pre_adverse_sent_at` as the base instant and adds exactly the parent jurisdiction's `pre_adverse_waiting_days` calendar days, preserving the base time-of-day. Federal law sets the floor at five calendar days, but a state may set a higher value on its `Jurisdiction` row, and the federal-floor invariant guarantees the floor will never drop below five (any attempt to do so is caught at jurisdiction creation or update).

Finalization is performed by a `ComplianceOfficer`, with `expected_adverse_action_version` supplied to defeat stale-state races. Four preconditions are checked. First, the adverse-action's `status` must be `PRE_ADVERSE_SENT` — finalizing a `DISPUTED`, `FINALIZED`, or `CANCELLED` row is rejected with `ERR_INVALID_STATE`. Second, the system clock's `current_utc` must be at or after the adverse-action's `earliest_final_at`; an earlier attempt is rejected with `ERR_WAITING_PERIOD_NOT_ELAPSED`. Third, the acting `X-User-ID` must differ from the Recruiter `X-User-ID` recorded on the parent application's conditional-offer audit row; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. Fourth, the parent `BackgroundCheckOrder`'s `status` must be `COMPLETE` and its `overall_result` must be `CONSIDER`; otherwise the finalize is rejected with `ERR_INVALID_STATE`.

On success the adverse-action advances from `PRE_ADVERSE_SENT` to `FINALIZED`, with `finalized_at` stamped from `current_utc`, `finalized_by_user_id` set to the acting `X-User-ID`, and `version` incremented. The cascade rejects the parent `Application`: its `status` transitions from `CONDITIONAL_OFFER` to `REJECTED` with its `version` incremented. An audit row is appended with action `FINAL_ADVERSE_ISSUE`.

Two automatic adverse-action transitions complete the state machine. If, while the adverse-action is in `PRE_ADVERSE_SENT`, any child verification of the parent order is disputed (the `REPORTED` to `DISPUTED` transition fires on a child), the adverse-action cascades from `PRE_ADVERSE_SENT` to `DISPUTED`. Once all disputed verifications have been resolved and none remain `DISPUTED`, the adverse-action cycles back from `DISPUTED` to `PRE_ADVERSE_SENT` so that finalization is once again possible. If instead the resolution flipped the order's `overall_result` to `CLEAR`, the adverse-action — whether previously in `PRE_ADVERSE_SENT` or `DISPUTED` — is auto-cancelled to `CANCELLED` with its `version` incremented.

### 3.7. Hiring or Rejecting the Applicant, and the Applicant Risk Score

Once a background-check order has settled into `COMPLETE` with `overall_result` `CLEAR`, the recruiter may hire the applicant. The hire call carries `expected_application_version`; on success the application advances from `CONDITIONAL_OFFER` to `HIRED`. An attempt to hire when the order is not yet `COMPLETE` or when `overall_result` is not `CLEAR` is rejected with `ERR_INVALID_STATE`. Rejection of the application is system-driven only — it fires automatically when an adverse-action reaches `FINALIZED`, as described above.

Alongside the `overall_result` flag, the system maintains a numerical applicant risk score. The score is a weighted aggregation over the three verification streams. Each stream contributes a sub-score equal to its failure weight when the stream's effective `result` is `FAIL`, and zero when the stream's effective `result` is `PASS`. The failure weights are pinned: criminal contributes 0.65, motor-vehicle 0.25, and education 0.10. Evaluation order is also pinned — criminal first, motor-vehicle second, education third — and each per-stream contribution is rounded half-up to two decimal places before being added to the running total. The final sum is then itself rounded half-up to two decimal places, yielding a score between 0.00 and 1.00. Verification streams that are still `PENDING` are excluded from the sum entirely; only streams that have reached `REPORTED`, `DISPUTED`, or `RESOLVED` contribute.

The score has two variants distinguished by the parent order's `status`. The provisional-in-review variant applies while the order is `IN_REVIEW`: at least one stream is still `PENDING` and is excluded from the sum, so the partial score may understate the eventual risk relative to the final value. The final-complete variant applies once the order is `COMPLETE`: all three streams contribute, and the score may rise above the 0.50 risk threshold (and trigger `CONSIDER`) even when the in-review score was below the threshold.

The score is exposed through a computed read on the parent order. The read returns a `score` (the rounded numerical value), a `variant` (the textual variant in effect — provisional or final), an `exceeds_threshold` boolean (true when `score` is at or above 0.50), and the `threshold` value itself (so that clients do not hardcode it). The read does not mutate any state and is available to recruiters and compliance officers.

### 3.8. The Audit Trail and the Test Clock

Every state-changing operation appends an `AuditLog` row. The action verb tags include at least `CONSENT_GRANT`, `ORDER_CREATE`, `VERIFICATION_REPORT`, `PRE_ADVERSE_SEND`, and `FINAL_ADVERSE_ISSUE` (plus `APPLICATION_SUBMIT`, `CONDITIONAL_OFFER`, `HIRE`, and `APPLICATION_REJECTED` for the application state machine). Each row carries `actor_role` and `actor_user_id` captured from the `X-User-Role` and `X-User-ID` of the calling request, the affected `entity_type` and `entity_id`, and (for transitions) `prior_state` and `new_state` — both null for pure-create actions. The log is read-only and is available only to the `ComplianceOfficer` role, with optional filters on `entity_type` and `entity_id`.

The system clock is exposed as a singleton row with the literal `id` `singleton` and a mutable `current_utc` field. A `PlatformAdmin`-only test-driving capability updates the singleton from a supplied `to_iso8601` payload value, advancing the logical wall clock to an arbitrary instant; subsequent server-stamped timestamps and waiting-period comparisons read from the new value. A read endpoint exposes the current clock state to platform admins, recruiters, and compliance officers. Application code never reads operating-system time.

## 4. Endpoint Definitions

Operations that create new top-level or distinct sub-resources return a `201 Created` status code (the Applicant, Application, Jurisdiction, ConsentDisclosure, BackgroundCheckOrder, and Verification creation endpoints). Operations that modify or transition an existing resource — submit, conditional offer, hire, withdraw, grant, revoke, cancel, report, dispute, resolve, finalize — return a `200 OK` status code. Read endpoints also return `200 OK`.

| Method | Path                                                              | Description                                                                                          | Authorized Role(s) |
| ------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------ |
| POST   | `/api/v1/jurisdictions`                                           | Create a US-state jurisdiction with ban-the-box and salary-history-ban toggles                       | PlatformAdmin |
| GET    | `/api/v1/jurisdictions/{id}`                                      | Fetch a jurisdiction by id                                                                           | PlatformAdmin, Recruiter, ComplianceOfficer, VerificationProvider, Applicant |
| GET    | `/api/v1/jurisdictions`                                           | List jurisdictions; supports filtering by `state_code`                                               | PlatformAdmin, Recruiter, ComplianceOfficer |
| POST   | `/api/v1/applicants`                                              | Register an applicant                                                                                 | Applicant, Recruiter |
| GET    | `/api/v1/applicants/{id}`                                         | Fetch applicant by id                                                                                 | Applicant, Recruiter, ComplianceOfficer |
| POST   | `/api/v1/applications`                                            | Create an Application in DRAFT for a given Applicant and Jurisdiction                                 | Applicant, Recruiter |
| GET    | `/api/v1/applications/{id}`                                       | Fetch application                                                                                     | Applicant, Recruiter, ComplianceOfficer |
| GET    | `/api/v1/applications`                                            | List applications; supports filtering by `applicant_id`, `jurisdiction_id`, and `status`              | Recruiter, ComplianceOfficer |
| POST   | `/api/v1/applications/{id}/submit`                                | Submit a draft Application                                                                            | Applicant |
| POST   | `/api/v1/applications/{id}/conditional-offer`                     | Recruiter extends a conditional offer to a SUBMITTED application                                      | Recruiter |
| POST   | `/api/v1/applications/{id}/hire`                                  | Recruiter hires applicant                                                                             | Recruiter |
| POST   | `/api/v1/applications/{id}/withdraw`                              | Applicant withdraws a DRAFT or SUBMITTED application                                                  | Applicant |
| POST   | `/api/v1/consents`                                                | Create a ConsentDisclosure record (PENDING) for an Application                                        | Applicant |
| POST   | `/api/v1/consents/{id}/grant`                                     | Applicant grants the pending consent                                                                  | Applicant |
| POST   | `/api/v1/consents/{id}/revoke`                                    | Applicant revokes a granted consent                                                                   | Applicant |
| GET    | `/api/v1/consents/{id}`                                           | Fetch consent record                                                                                   | Applicant, Recruiter, ComplianceOfficer |
| GET    | `/api/v1/applications/{id}/consents`                              | List ConsentDisclosure rows for an Application                                                        | Applicant, Recruiter, ComplianceOfficer |
| POST   | `/api/v1/background-check-orders`                                 | Recruiter creates a BackgroundCheckOrder                                                              | Recruiter |
| GET    | `/api/v1/background-check-orders/{id}`                            | Fetch order                                                                                            | Recruiter, ComplianceOfficer, Applicant, VerificationProvider |
| GET    | `/api/v1/background-check-orders`                                 | List orders; supports filtering by `application_id`, `consent_id`, and `status`                       | Recruiter, ComplianceOfficer, Applicant |
| POST   | `/api/v1/background-check-orders/{id}/verifications`              | Create one Verification (CRIMINAL/MVR/EDUCATION) for an order                                         | Recruiter |
| POST   | `/api/v1/background-check-orders/{id}/cancel`                     | Recruiter cancels a PENDING order                                                                     | Recruiter |
| GET    | `/api/v1/background-check-orders/{id}/risk-score`                 | Computed read of the applicant risk score for this order                                              | Recruiter, ComplianceOfficer |
| GET    | `/api/v1/verifications/{id}`                                      | Fetch a verification                                                                                   | Recruiter, ComplianceOfficer, VerificationProvider, Applicant |
| GET    | `/api/v1/background-check-orders/{id}/verifications`              | List verifications under an order                                                                      | Recruiter, ComplianceOfficer, VerificationProvider, Applicant |
| POST   | `/api/v1/verifications/{id}/report`                               | Provider reports a verification outcome (PASS/FAIL)                                                   | VerificationProvider |
| POST   | `/api/v1/verifications/{id}/dispute`                              | Applicant disputes a REPORTED verification                                                            | Applicant |
| POST   | `/api/v1/verifications/{id}/resolve`                              | Provider resolves a DISPUTED verification with a final result                                         | VerificationProvider |
| GET    | `/api/v1/adverse-actions/{id}`                                    | Fetch an adverse action                                                                                | Recruiter, ComplianceOfficer, Applicant |
| GET    | `/api/v1/background-check-orders/{id}/adverse-action`             | Sub-resource list (0 or 1) of the AdverseAction for the order                                          | Recruiter, ComplianceOfficer, Applicant |
| POST   | `/api/v1/adverse-actions/{id}/finalize`                           | ComplianceOfficer finalizes the AdverseAction after the FCRA waiting period                            | ComplianceOfficer |
| GET    | `/api/v1/audit-logs`                                              | List audit log rows; supports filtering by `entity_type` and `entity_id`                              | ComplianceOfficer |
| POST   | `/api/v1/_clock/set_current_utc`                                  | Set the SystemClock singleton to an arbitrary ISO timestamp (test-driving)                            | PlatformAdmin |
| GET    | `/api/v1/_clock`                                                  | Read current SystemClock singleton                                                                    | PlatformAdmin, Recruiter, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID                                | HTTP Status Code |
| --------------------------------------- | ---------------- |
| `ERR_MISSING_AUTH`                      | 401 Unauthorized |
| `ERR_INVALID_ROLE`                      | 401 Unauthorized |
| `ERR_UNAUTHORIZED`                      | 403 Forbidden    |
| `ERR_NOT_FOUND`                         | 404 Not Found    |
| `ERR_INVALID_REQUEST`                   | 400 Bad Request  |
| `ERR_INVALID_STATE`                     | 409 Conflict     |
| `ERR_STALE_VERSION`                     | 412 Precondition Failed |
| `ERR_BAN_THE_BOX_PREMATURE_INQUIRY`     | 422 Unprocessable Entity |
| `ERR_SALARY_HISTORY_DISCLOSED_BANNED`   | 422 Unprocessable Entity |
| `ERR_CONSENT_NOT_GRANTED`               | 422 Unprocessable Entity |
| `ERR_CONSENT_REVOKE_TOO_LATE`           | 422 Unprocessable Entity |
| `ERR_DUPLICATE_VERIFICATION_TYPE`       | 422 Unprocessable Entity |
| `ERR_WAITING_PERIOD_NOT_ELAPSED`        | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES`             | 422 Unprocessable Entity |
| `ERR_BELOW_FEDERAL_FLOOR`               | 422 Unprocessable Entity |
| `ERR_CONSENT_ALREADY_OPEN`              | 422 Unprocessable Entity |
