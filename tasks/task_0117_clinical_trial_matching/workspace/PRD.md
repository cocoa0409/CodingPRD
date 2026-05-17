# Clinical Trial Matching API — Product Requirements Document

## 1. Introduction

Modern clinical research is governed by a tightly coupled chain of regulatory, scientific, and operational gates. Before a single patient is enrolled, a Trial must clear Institutional Review Board (IRB) oversight; once enrolled, every blood draw is bound to a narrow protocol-scheduled window; and every dollar of participant compensation is reconciled against the audit history of which consent version was in force at the time of each visit. The Clinical Trial Matching API exists to make these constraints machine-enforceable rather than dependent on operator vigilance.

The system serves three distinct operator populations whose duties must remain separated by design: a `PrincipalInvestigator` who authors trials and reviews adverse events; an `IRBReviewer` who independently approves or rejects those trials; and a `StudyCoordinator` who runs the day-to-day mechanics of screening, consent, visits, and payment. Participants themselves can act on a narrow surface to sign consent and to withdraw. Every state change is auditable, every cascade is deterministic, and every compensation cent traces back to a specific consent version and a specific blood-draw window.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which the request is made. Missing, empty, or invalid headers cause the request to be rejected with `ERR_AUTH_REQUIRED`. An authenticated caller whose declared role is not authorized to invoke the targeted endpoint is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled as follows: `PrincipalInvestigator`, `IRBReviewer`, `StudyCoordinator`, and `Participant_self`.

For the three operator roles — `PrincipalInvestigator`, `IRBReviewer`, and `StudyCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity record. The server may record it (for example, as `reviewer_id` on an `IRBReview` row written by a `IRBReviewer`, or as the trial's `created_by_user_id` recorded when a `PrincipalInvestigator` creates a Trial) but it does not compare such ids to any entity's `id`. The `created_by_user_id` so recorded is what the segregation-of-duties check compares against the acting `IRBReviewer`'s `X-User-ID` (see §2.4).

For `Participant_self`, `X-User-ID` is the `id` of the acting `Participant`. Ownership checks on any participant-scoped resource compare the path-bound `participant_id` to `X-User-ID`: `Participant_self` may sign consent, withdraw, read their own participant record, list their own visits, and list their own payments only when `participant_id == X-User-ID`. Any attempt by `Participant_self` to touch another participant's resources is `ERR_FORBIDDEN`.

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

For endpoints that return lists, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return, defaulting to 10 if not provided, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses include the following four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Top-level operational resources — `Trial`, `Arm`, `Participant`, `Visit`, `AdverseEvent`, and `IRBReview` — carry a standard set of system-managed fields:

- `id` is a server-minted UUID string, with no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, recording first-creation time.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` is an integer that begins at 1 on creation and increments by exactly 1 on every server-side mutation, including mutations driven by cascade rather than by a direct client call on that resource.

Two entities are immutable-after-write and carry only `id` and `created_at` — they have no `updated_at` and no `version` field. These are `ConsentVersion` (a published consent record is an audit row, not a mutable entity) and `Payment` (each ledger line is a permanent row; corrections are issued as additional `REVERSAL` rows rather than in-place edits).

### 2.5. Segregation of Duties and Role-Scoped Operations

Trial approval is built around a hard segregation-of-duties (SoD) barrier between the operator who authored a trial and the operator who reviews it. Each `Trial` row records the `X-User-ID` of its creator as `created_by_user_id` at the moment a `PrincipalInvestigator` calls trial creation. When an `IRBReviewer` later submits a review decision, the reviewer's `X-User-ID` is compared to that recorded `created_by_user_id`; if they match, the request is rejected with `ERR_SOD_VIOLATION` at HTTP 403. The same SoD check applies to all three possible decisions — approval, revision request, and rejection.

The `Participant_self` role, by contrast, is bound to a specific participant identity: a `Participant_self` request is honored only when the path-bound `participant_id` equals `X-User-ID`; any mismatch is `ERR_FORBIDDEN`. `StudyCoordinator` and `PrincipalInvestigator` may act on behalf of any participant within the bounds of their endpoint surface.

### 2.6. Optimistic Concurrency Control

`PATCH /trials/{trial_id}`, `PATCH /participants/{participant_id}`, `PATCH /visits/{visit_id}`, and `PATCH /arms/{arm_id}` accept an optional `version` field in the request body. When a client supplies `version`, the server compares it against the row's persisted `version`; if the two are not equal, the request is rejected with `ERR_VERSION_CONFLICT` at HTTP 409. When the `version` field is omitted from the body, the OCC check is skipped entirely and the mutation proceeds without a stale-data guard.

Any successful mutation, whether direct or cascaded, increments `version` by exactly one and refreshes `updated_at`. Cascade-induced mutations — for instance the `Trial.enrolled_count` bump that follows a sign-consent, or the `Visit.status` flip that follows a participant withdrawal — count as mutations and produce the same `version` and `updated_at` bookkeeping.

### 2.7. Nested Resource Path Resolution

Endpoints that nest resources under one another (for example `/trials/{trial_id}/arms`, `/trials/{trial_id}/irb-reviews`, `/participants/{participant_id}/visits`, or `/participants/{participant_id}/adverse-events/{adverse_event_id}/resolve`) are validated strictly left-to-right. The outermost path segment is resolved first: if `trial_id` does not refer to any persisted trial, the request fails with `ERR_NOT_FOUND` before any inner segment is even examined. Only after the parent is resolved does the server attempt to resolve the next segment — for example `participant_id`, then `adverse_event_id` — and so on down the path. The same principle applies to foreign-key identifiers that appear in the request body (for example `caused_visit_id` on an adverse-event creation): a body-referenced id that does not resolve is `ERR_NOT_FOUND`.

### 2.8. Validation Ordering

When multiple validation conditions could apply to the same request, the server evaluates them in a fixed priority order so that the error code returned is deterministic. The order from highest priority to lowest is: authentication and header well-formedness first, producing `ERR_AUTH_REQUIRED`; then role authorization for the endpoint, producing `ERR_FORBIDDEN`; then path-parameter existence checks, producing `ERR_NOT_FOUND`; then body-referenced foreign-key existence checks, also producing `ERR_NOT_FOUND`; then state-machine eligibility, producing `ERR_INVALID_STATE`; then endpoint-specific gating conditions described in §3 (`ERR_IRB_EXPIRED` on opening enrollment, the SoD check `ERR_SOD_VIOLATION` on IRB review, the consent-version gate `ERR_CONSENT_VERSION_STALE`, the adverse-event gate `ERR_AE_BLOCKING`, the blood-draw window gate `ERR_DRAW_OUTSIDE_WINDOW`, the window-not-yet-passed gate `ERR_WINDOW_NOT_YET_PASSED`, the visit-sequence uniqueness `ERR_DUPLICATE_VISIT_SEQUENCE`, the cross-participant attribution `ERR_CROSS_PARTICIPANT_REFERENCE`, randomization misconfiguration `ERR_RANDOMIZATION_MISCONFIGURED`, the trial-full check `ERR_TRIAL_FULL`, the consent-publish state check, the protocol-code uniqueness `ERR_DUPLICATE_PROTOCOL_CODE`, the stratum-key check `ERR_STRATUM_KEY_MISSING`); then OCC `ERR_VERSION_CONFLICT`; and only last the generic input-schema check `ERR_INVALID_INPUT`. In particular, when a visit-complete request would simultaneously fail the adverse-event gate, the consent-version gate, and the draw-window gate, the first of those to fire is `ERR_AE_BLOCKING`, then `ERR_CONSENT_VERSION_STALE`, then `ERR_DRAW_OUTSIDE_WINDOW` — the safety check is the most specific and takes precedence.

### 2.9. Blood-Draw Window Semantics

Every blood-draw event is checked against a symmetric, inclusive calendar-day window anchored on the visit's `target_date`. The window radius is the parent trial's `blood_draw_window_days`, an integer between 0 and 14 inclusive. When the server evaluates whether a recorded draw falls within the window, it first projects both the `actual_draw_at` timestamp and the `target_date` to their UTC calendar dates (the time-of-day component of `actual_draw_at` is dropped after timezone normalization to UTC), then takes the absolute difference in whole calendar days. A draw whose absolute day-offset is less than or equal to `blood_draw_window_days` is within the window and the visit may complete; a draw whose absolute day-offset is strictly greater than `blood_draw_window_days` is outside the window and the visit-complete request is rejected with `ERR_DRAW_OUTSIDE_WINDOW`. The boundary is inclusive on both sides: a draw on `target_date + blood_draw_window_days` is within the window; a draw on `target_date + blood_draw_window_days + 1` is outside.

The same `blood_draw_window_days` integer also gates the mark-missed operation. A visit may be marked missed only after the current logical clock time has strictly passed `target_date + blood_draw_window_days` — that is, the entire window must have elapsed. A mark-missed call submitted before that boundary is rejected with `ERR_WINDOW_NOT_YET_PASSED`.

### 2.10. Consent Versioning and the Re-Consent Gate

Each Trial maintains a monotonically increasing chain of consent rows. When a `PrincipalInvestigator` publishes the first consent for a trial, it is assigned `version` 1 and the trial's `active_consent_version` is set to 1. Every subsequent publish increments the version by exactly one (1, 2, 3, ...) and updates `active_consent_version` on the parent trial atomically. Publishing a second or later version requires `change_summary` of between 1 and 500 characters; publishing the first version does not require `change_summary`. The `published_at` timestamp is set by the server at the moment a version becomes the active version.

Once a participant has reached `ENROLLED`, the participant's `signed_consent_version` is recorded at sign-consent time. If a newer consent version is later published, that participant's `signed_consent_version` becomes strictly less than the trial's `active_consent_version` — the participant is now "stale-versioned". No further visit may be completed for a stale-versioned participant: visit-complete requires `signed_consent_version` to equal `active_consent_version` exactly, and any inequality is rejected with `ERR_CONSENT_VERSION_STALE`. The same error code is returned by sign-consent when the body's `consent_version` parameter does not equal the trial's current `active_consent_version`.

A new consent version may only be published while the trial's `status` is one of `DRAFT`, `IRB_PENDING`, `APPROVED`, or `OPEN_FOR_ENROLLMENT`; an attempt to publish a consent version when the trial is in any other status is rejected with `ERR_INVALID_STATE`. The `requires_re_consent` flag on a `ConsentVersion` is a publish-time boolean: when it is true, every previously `ENROLLED` participant whose `signed_consent_version` is less than the new version is immediately marked stale and is held against further visit completion by the re-consent gate.

### 2.11. Precision and Rounding

The eligibility score is expressed with one decimal place. Multiplications, divisions, and other intermediate decimal operations that feed into the eligibility score are rounded using the half-up convention before the score is recorded. Compensation amounts, by contrast, are stored as integer cents in `compensation_cents` on a visit and as integer cents in `amount_cents` on a payment; the cent figures themselves are never rounded, though any intermediate decimal multiplication that contributes to a cent value uses half-up rounding before being converted to a cent integer.

### 2.12. Test-Only Logical Clock

Several rules in this specification depend on the passage of real-world time — for example the 365-day expiry of an IRB approval, or the requirement that a missed-visit declaration come strictly after the window has elapsed. To make these reachable in automated tests from a freshly empty database, an admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The submitted timestamp must be greater than or equal to the current clock; the clock is monotonic and may not be moved backwards.

## 3. Business Logic & Workflows

### 3.1. Authoring a Trial: From DRAFT to IRB Submission

A `PrincipalInvestigator` opens the lifecycle by creating a trial. The creation payload carries a `protocol_code` (a 2–4 letter prefix, a hyphen, and 3–5 digits, matching the regex `^[A-Z]{2,4}-[0-9]{3,5}$`, unique across the system after trimming surrounding whitespace), a human-readable `title` of 1–200 characters after trimming, the `sponsor_org` organization name, an ordered `inclusion_criteria` array and an `exclusion_criteria` array (each of at most 20 entries, each entry of the shape `{code, op, field, value}` where `op` is one of `GTE`, `LTE`, `EQ`, `IN`, `BETWEEN`), the chosen `randomization_scheme`, the `target_enrollment` integer in the range 1 to 10000 inclusive, and the trial-wide `blood_draw_window_days` integer in the range 0 to 14 inclusive. When the scheme is `PERMUTED_BLOCK` or `STRATIFIED_BLOCK` the payload also carries `block_size`, which must be one of 2, 4, 6, or 8; for `SIMPLE_BERNOULLI` it must be null. `STRATIFIED_BLOCK` additionally requires a non-null `stratification_field` naming the profile attribute used to compute strata.

A freshly created trial begins life in `DRAFT` status with `active_consent_version` of null and `enrolled_count` of zero. Two protocol-code constraints apply: any duplicate `protocol_code` collision at create time, or at update time (a metadata edit applied to an existing trial in `DRAFT`), is rejected with `ERR_DUPLICATE_PROTOCOL_CODE`. While the trial is in `DRAFT`, the investigator can edit `title`, `sponsor_org`, `inclusion_criteria`, `exclusion_criteria`, and `target_enrollment` through the metadata-update endpoint; that endpoint also accepts an optional `version` to drive OCC. Outside of `DRAFT`, the trial is no longer editable through that endpoint.

Arms are attached to the trial while it is still in `DRAFT`. Each arm carries a short `code` of 1–8 uppercase alphanumeric characters (regex `^[A-Z0-9]{1,8}$`) that must be unique within the parent trial, a human-readable `label`, and a `weight` integer between 1 and 10 inclusive. The server tracks an `assigned_count` of how many participants currently sit in `ENROLLED` or `COMPLETED` against that arm. Each arm row also includes the `trial_id` of its parent.

Before submitting for IRB review, the investigator must also publish at least one consent version. Consent publication adds a `document_uri` of 1 to 500 characters, optionally a `change_summary` (required from version 2 onward) and an optional `requires_re_consent` boolean (defaulting to false). The first publish sets `active_consent_version` from null to 1; subsequent publishes set it to the new server-minted version. Publishing is allowed only while the trial's status is `DRAFT`, `IRB_PENDING`, `APPROVED`, or `OPEN_FOR_ENROLLMENT`; in any other status the publish is rejected with `ERR_INVALID_STATE`.

The investigator then submits the trial for review, transitioning `DRAFT → IRB_PENDING`. The submit precondition fires `ERR_RANDOMIZATION_MISCONFIGURED` (HTTP 422) unless **all four** of the following are true: the trial has at least 2 arms; for `PERMUTED_BLOCK` or `STRATIFIED_BLOCK`, the `block_size` is exactly divisible by the arm count (`block_size` modulo the number of arms is zero); for those same schemes, every arm's `weight` is equal to every other arm's `weight`; and for `STRATIFIED_BLOCK` specifically, `stratification_field` is non-null. The same precondition also requires that at least one consent version has been published (i.e. `active_consent_version` is non-null). When all checks pass, the trial moves into `IRB_PENDING`.

### 3.2. Independent IRB Review and the Segregation Barrier

An `IRBReviewer` then records a decision against a trial in `IRB_PENDING` by submitting a review with a `decision` value of `APPROVED`, `REVISIONS_REQUESTED`, or `REJECTED`, plus reviewer `notes` of 1 to 1000 characters. The review creates an `IRBReview` row with the reviewer's `X-User-ID` stored as `reviewer_id`, the timestamp of the decision as `decided_at`, and the supplied `notes`.

Every decision branch is gated on the same SoD precondition: the reviewer's `X-User-ID` must not equal the trial's recorded `created_by_user_id`. If they match, the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403) before any state change is written. This holds equally for `APPROVED`, `REVISIONS_REQUESTED`, and `REJECTED` — all three are subject to the SoD barrier, none of them can be self-served.

When the SoD check passes, the three branches diverge:

- An `APPROVED` decision transitions the trial `IRB_PENDING → APPROVED`. The server records `irb_decision_note` from the supplied `notes`, sets `irb_approval_expires_at` to exactly 365 days after the `decided_at` timestamp, and persists the new `IRBReview` row. Each subsequent approval (after a revision cycle) recomputes `irb_approval_expires_at` from its own `decided_at`.
- A `REVISIONS_REQUESTED` decision transitions the trial back to `DRAFT`, records the `notes` as the new `irb_decision_note`, and persists the `IRBReview` row. The trial returns to the editable state.
- A `REJECTED` decision transitions the trial directly to `TERMINATED`, persists the `IRBReview` row, and ends the lifecycle.

Reviews are append-only: the `IRBReview` rows for a trial constitute a chronological audit log of every decision made against it. Listing the reviews is shared between the principal investigator and the IRB reviewer.

### 3.3. Opening Enrollment, Reaching Cap, Manual Close, and Termination

With the trial in `APPROVED`, the investigator opens enrollment. Two conditions must hold: `active_consent_version` must be non-null, and the current logical clock time must be strictly earlier than `irb_approval_expires_at`. If the clock has reached or passed that expiry, the request is rejected with `ERR_IRB_EXPIRED` and the trial must be re-submitted and re-approved before enrollment can begin. When the conditions hold, the trial moves to `OPEN_FOR_ENROLLMENT`.

Once open, the trial can leave that state in three ways. First, a manual close by the investigator moves it from `OPEN_FOR_ENROLLMENT` to `CLOSED_TO_ENROLLMENT`. Second, the system itself auto-closes when `enrolled_count` reaches `target_enrollment` immediately after a participant enrollment transition: the moment the count equals the cap, the trial transitions `OPEN_FOR_ENROLLMENT → CLOSED_TO_ENROLLMENT` as a cascade off the enrolling participant's commit, with no client action required. Third, the investigator may terminate the trial outright, optionally supplying a `reason` field; this transitions `OPEN_FOR_ENROLLMENT → TERMINATED` and triggers the two-tier cascade described in §3.7.

From `CLOSED_TO_ENROLLMENT`, the investigator may complete the trial, moving it to the terminal `COMPLETED` state. Completion is permitted only when **every** participant attached to the trial has reached `COMPLETED`, `WITHDRAWN`, or `INELIGIBLE` — that is, when no participant is still in `SCREENING`, `ELIGIBLE`, `CONSENT_PENDING`, or `ENROLLED`. If any participant is still active, the request is rejected with `ERR_INVALID_STATE`.

### 3.4. Participant Screening and the Eligibility Score

A `StudyCoordinator` creates a participant in the `SCREENING` state by attaching them to a trial via `trial_id` and supplying their `profile` — a bag of typed attribute keys (at most 50 keys, scalar values) that will be evaluated against the trial's inclusion and exclusion criteria. The `trial_id` is locked at creation; the participant's `arm_id` is null until enrollment fills it from the randomization engine; `signed_consent_version` is null until a successful sign-consent; `eligibility_score` is null until evaluation runs; `open_ae_count` begins at zero; and `enrolled_at` is null until the participant reaches `ENROLLED`.

Evaluation may be requested by the coordinator once the parent trial is in `OPEN_FOR_ENROLLMENT`. The evaluator computes a numeric `eligibility_score` and decides between `ELIGIBLE` and `INELIGIBLE` through a two-step procedure that uses **only** the participant's own profile and the trial's currently-live inclusion and exclusion criteria — other participants' profiles are not considered.

Step one is the exclusion gate. The evaluator walks the trial's `exclusion_criteria` list in declared order; if **any** exclusion predicate evaluates true against the participant's `profile`, the participant is immediately decided as `INELIGIBLE`, the `eligibility_score` is recorded as 0.0, and step two is skipped.

Step two is the inclusion score. For each entry in the trial's `inclusion_criteria` list in declared order, the evaluator records a contribution of 1 if the predicate matches the profile, or a contribution of 0 either when the predicate's field is missing from the profile or when the predicate is present but does not match. The raw fraction is then the sum of contributions divided by the number of inclusion criteria; the recorded `eligibility_score` is 100 times that fraction, rounded half-up to one decimal place. The decision then compares the score against the threshold of 80.0: a score greater than or equal to 80.0 is `ELIGIBLE` (the threshold is inclusive); a score less than 80.0 is `INELIGIBLE`. The transition fires either `SCREENING → ELIGIBLE` or `SCREENING → INELIGIBLE` accordingly, and `eligibility_score` is written in either case.

This live evaluation is the **forward-looking** variant of the score. The coordinator and the investigator can also request an audit replay via the eligibility-history capability on a participant, which produces the **chronological** variant: that variant pins the criteria to whichever inclusion and exclusion criteria were attached to the trial at the moment of the participant's `created_at`, even if the criteria have since been amended. The chronological replay may produce a different score, and even a different `ELIGIBLE` versus `INELIGIBLE` decision, for the same `profile`. The chronological capability is a read-only diagnostic; it does not mutate `eligibility_score` on the participant.

### 3.5. From ELIGIBLE to ENROLLED: Consent, Randomization, and the Cap Race

A participant in `ELIGIBLE` is moved to `CONSENT_PENDING` by the coordinator's request-consent action; this transition requires `active_consent_version` to be non-null on the trial.

From `CONSENT_PENDING`, the participant (or, on their behalf, the coordinator) signs consent by submitting a `consent_version` integer in the body. The transition `CONSENT_PENDING → ENROLLED` requires all three of the following to hold simultaneously: the supplied `consent_version` equals the trial's `active_consent_version` exactly (otherwise `ERR_CONSENT_VERSION_STALE`); the trial's `status` is `OPEN_FOR_ENROLLMENT` (otherwise `ERR_INVALID_STATE`); and the trial's `enrolled_count` is strictly less than `target_enrollment` (otherwise `ERR_TRIAL_FULL`). Additionally, if the trial's `randomization_scheme` is `STRATIFIED_BLOCK`, the participant's `profile` must contain the trial's `stratification_field` key at sign-consent time; absence is rejected with `ERR_STRATUM_KEY_MISSING`.

On successful sign-consent the server performs an atomic bundle of writes: `signed_consent_version` is set to the supplied `consent_version`; `arm_id` is set by the arm-assignment routine described below; the chosen arm's `assigned_count` is incremented by one; the trial's `enrolled_count` is incremented by one; `enrolled_at` is stamped with the current logical clock instant; `status` is set to `ENROLLED`. If after this increment `enrolled_count` equals `target_enrollment`, the parent trial is cascaded from `OPEN_FOR_ENROLLMENT` to `CLOSED_TO_ENROLLMENT` in the same commit.

Arm assignment is deterministic — despite the word "randomization", every assignment is reproducible from the trial's existing state and a fixed seed equal to the arms' code-ascending order, which is the standard mechanism used in regulated trials so the assignment is auditable. The arm-assignment routine consults the trial's `randomization_scheme`, the list of arm rows with their `code`, `weight`, and `assigned_count`, the `block_size`, the `stratification_field`, and the participant's `profile`. There are three branches:

- Under `SIMPLE_BERNOULLI`, the assigned arm is the one whose ratio of `assigned_count` to `weight` is minimum — that is, the arm with the largest deficit relative to its weight share. If two or more arms tie on that ratio, the tie is broken by picking the arm with the lexicographically smallest `code`.
- Under `PERMUTED_BLOCK`, the arms are first ordered by their `code` field in ascending lexicographic order. A canonical block sequence is then defined as the arm codes repeated `block_size` divided by the number of arms times each, laid out in that code-ascending order. The position within this trial-wide block sequence is the trial's current `enrolled_count` evaluated just before this enrollment commits; the arm at that position is selected.
- Under `STRATIFIED_BLOCK`, the algorithm is identical to `PERMUTED_BLOCK` except that the position counter is a per-stratum running counter rather than the trial-wide `enrolled_count`. The stratum key is the value of `profile[stratification_field]`. If the stratum key is missing — which is the same situation the validation in the previous paragraph rejects with `ERR_STRATUM_KEY_MISSING` — the routine cannot proceed.

The routine assumes the trial has at least one arm. A defensive fallback exists for the otherwise unreachable zero-arm case: arm assignment on a trial with zero arms is `ERR_NO_ARMS_DEFINED`. This is unreachable in normal operation because submission to IRB already enforces the requirement of at least two arms.

A participant in `CONSENT_PENDING` who does not wish to proceed may withdraw, transitioning `CONSENT_PENDING → WITHDRAWN`; this branch has no further cascades because the participant was never enrolled.

### 3.6. The Visit Lifecycle: Window Boundaries, Adverse-Event Gating, Re-Consent Gating

Once a participant is `ENROLLED`, the coordinator schedules visits against them. Each visit creation carries a 1-indexed `sequence_no` between 1 and 50 that must be unique within the participant (any duplicate is `ERR_DUPLICATE_VISIT_SEQUENCE`), plus a `target_date` for the protocol-scheduled blood draw. The visit begins in `SCHEDULED`, with `actual_draw_at` null and `compensation_cents` at zero; both will be filled at completion time.

Three precondition checks gate `SCHEDULED → COMPLETED` when the coordinator submits the visit-complete request with `actual_draw_at`. First, the parent participant must be in `ENROLLED` — a complete on a participant in any other status is `ERR_INVALID_STATE`. Second, the participant's `open_ae_count` must be exactly zero; if any adverse event is still in `OPEN` or `UNDER_REVIEW`, the visit-complete is rejected with `ERR_AE_BLOCKING`. Third, the re-consent gate must be satisfied: the participant's `signed_consent_version` must equal the trial's `active_consent_version` exactly, otherwise `ERR_CONSENT_VERSION_STALE`. Fourth, the supplied `actual_draw_at` must fall inside the inclusive blood-draw window described in §2.9; an out-of-window draw is `ERR_DRAW_OUTSIDE_WINDOW`. On commit, the visit's `status` becomes `COMPLETED`, `actual_draw_at` is recorded, `compensation_cents` is computed by the provisional variant of the compensation calculation, and a `Payment` row of `kind` `PROVISIONAL` is written with `amount_cents` equal to that `compensation_cents` and `paid_at` of null.

Marking a visit `MISSED` is the alternative happy-path terminal transition. The coordinator may mark `SCHEDULED → MISSED` only when the current logical clock time is strictly later than `target_date` plus `blood_draw_window_days` — that is, the window must have fully passed. A premature attempt is `ERR_WINDOW_NOT_YET_PASSED`. There is no payment row for a `MISSED` visit.

A visit may also be cancelled outright while it is still `SCHEDULED`, either by a direct delete request from the coordinator or by cascade from a parent operation. A `SCHEDULED → CANCELLED` cancellation produces no payment row by itself, but if the visit had previously been completed and held a `PROVISIONAL` payment — for example because it was completed and then is being unwound through a participant withdrawal cascade — the cancellation chain emits a `REVERSAL` row as described in §3.7.

### 3.7. Adverse Events, Auto-Escalation, and the Cascade Chains

A `StudyCoordinator` or a `PrincipalInvestigator` records an adverse event against a participant by submitting `severity`, a `narrative` of 1 to 2000 characters, and an optional `caused_visit_id` pointing at a visit on the **same** participant. If `caused_visit_id` is set and the referenced visit belongs to a different participant, the report is rejected with `ERR_CROSS_PARTICIPANT_REFERENCE` at HTTP 422. The event is stamped with `reported_at` at the current logical clock time and begins life in `OPEN`. The participant's `open_ae_count` is incremented by one.

Severity drives the auto-escalation pathway on intake. When `severity` is `SEVERE` or `LIFE_THREATENING`, the newly created event is **immediately** transitioned `OPEN → ESCALATED_HOLD` by the system as part of the same commit. The escalation cascades: every visit on that participant whose `status` is `SCHEDULED` is moved to `CANCELLED`, and for each such cancelled visit that was holding a `PROVISIONAL` payment row, a corresponding `REVERSAL` `Payment` row is written whose `amount_cents` is the negation of the provisional row's `amount_cents`. The original `PROVISIONAL` rows remain as audit history. Additionally, when `severity` is `LIFE_THREATENING` and the parent trial is currently `OPEN_FOR_ENROLLMENT`, the trial itself is cascaded to `CLOSED_TO_ENROLLMENT` in the same commit. When `severity` is `MILD` or `MODERATE`, the event remains in `OPEN` and no cascade fires beyond the bump of `open_ae_count`.

The investigator manages the event through its workflow. Starting review transitions `OPEN → UNDER_REVIEW`; the participant's `open_ae_count` is unchanged by this move because an under-review event still counts as open against the visit-complete gate of §3.6. From `UNDER_REVIEW`, the investigator may manually escalate to `ESCALATED_HOLD`, which fires exactly the same cascade chain as the severity-driven auto-escalation: scheduled visits to `CANCELLED`, provisional payments to `REVERSAL`, and, if the parent trial is `OPEN_FOR_ENROLLMENT` and the severity is `LIFE_THREATENING`, parent trial to `CLOSED_TO_ENROLLMENT`. Alternatively, the investigator may resolve the event from `UNDER_REVIEW` by supplying a `resolution_note` of 1 to 1000 characters: this writes `RESOLVED` as the new status, records the resolution note on the event, and decrements `open_ae_count` by one. An event in `ESCALATED_HOLD` may also be resolved by supplying `resolution_note`; this likewise sets `RESOLVED` and decrements `open_ae_count` by one. `RESOLVED` is the only terminal state of the adverse-event lifecycle.

Participant withdrawal from `ENROLLED` produces a parallel cascade chain. When the coordinator or the participant themselves submits the withdraw action with an optional `reason`, the transition `ENROLLED → WITHDRAWN` first sets the participant's `status` accordingly, then cascades every `SCHEDULED` visit on that participant to `CANCELLED`. For each visit cascaded to `CANCELLED` that holds a `PROVISIONAL` payment, the server writes a `REVERSAL` `Payment` row with a negated `amount_cents`. The trial's `enrolled_count` is decremented by one because the participant is no longer enrolled, and the previously-assigned arm's `assigned_count` is decremented by one in the same commit. A withdrawal from `CONSENT_PENDING` (before enrollment ever took place) sets the participant to `WITHDRAWN` without any of these enrollment-side decrements.

Trial termination produces the longest cascade chain. When the investigator terminates the trial from `OPEN_FOR_ENROLLMENT`, every participant whose `status` is in `SCREENING`, `ELIGIBLE`, `CONSENT_PENDING`, or `ENROLLED` is cascaded to `WITHDRAWN`. Each such cascaded `Participant → WITHDRAWN` then itself cascades: every `SCHEDULED` visit on that participant is moved to `CANCELLED`. This is the cascade-of-cascade pattern — the trial's single termination action propagates one level to participants and a second level to visits in a single transactional commit.

### 3.8. Compensation: Provisional Accrual, Reversal, and Finalization

Compensation flows through the `Payment` table as three kinds of rows: `PROVISIONAL`, `FINAL`, and `REVERSAL`. Every row pins both the `participant_id` and the `visit_id` it accrued against, plus an `amount_cents` integer (which is positive for `PROVISIONAL` and `FINAL` and negative for `REVERSAL`) and a `paid_at` timestamp that is set only on `FINAL` rows. Listing payments may be filtered by a `kind` query parameter.

Per-visit accrual happens at the `SCHEDULED → COMPLETED` transition, in the provisional variant. The base compensation is 5000 cents. The server computes the absolute day-offset `d` as the absolute difference in calendar days between `actual_draw_at` (date-only, in UTC) and `target_date`. From `d`, a per-visit bonus is derived in a tiered manner:

- When `d` equals zero — the draw is exactly on `target_date` — the bonus is the on-time bonus of 1000 cents.
- When `d` is 1 or 2 — within a two-day grace period — the bonus is zero.
- When `d` is at least 3 and at most `blood_draw_window_days` — late but still within the window — the bonus is negative: the late-day penalty of 750 cents is multiplied by the number of days past the grace period, computed as `(d - 2)`. So a draw 3 days off target carries a 750-cent penalty, 4 days off carries a 1500-cent penalty, and so on, scaling linearly with each additional day past day 2.
- When `d` exceeds `blood_draw_window_days` — outside the window — the visit cannot complete in the first place; the compensation calculation is not reached because the request is rejected with `ERR_DRAW_OUTSIDE_WINDOW`.

The bonus is then floored at the negation of the base — that is, the bonus is set to the maximum of itself and `-5000` cents — so the per-visit total never falls below zero. The provisional cents amount is then 5000 plus the (clamped) bonus, with a final floor at zero. That amount is what `compensation_cents` is set to on the visit and what `amount_cents` is set to on the newly issued `PROVISIONAL` `Payment` row; the row's `paid_at` is null.

Finalization happens at the `Participant ENROLLED → COMPLETED` transition, in the final variant. The coordinator initiates participant completion only when every visit on that participant has reached `COMPLETED`, `MISSED`, or `CANCELLED` and `open_ae_count` is zero. On commit, for each visit whose `status` is `COMPLETED` and which still holds a `PROVISIONAL` payment row, the server writes a new `FINAL` `Payment` row whose `amount_cents` equals the provisional amount unchanged, and stamps `paid_at` with the current logical clock instant. The earlier `PROVISIONAL` rows remain as audit history; the sum of `PROVISIONAL` rows is **not** what gets paid, only the sum of `FINAL` rows is.

A re-consent bonus is added at finalization only. If the participant's `signed_consent_version` equals the trial's `active_consent_version` and at least one `ConsentVersion` row with `version` of 2 or higher exists on the trial — that is, the participant re-consented at least once during their enrollment — a re-consent bonus of 2500 cents is allocated to the last chronological `COMPLETED` visit, where "last" is determined by the visit's `sequence_no`, taking the maximum `sequence_no` and breaking ties (in the unlikely case of equal sequence numbers) by descending `sequence_no`. The order of operations is fixed: compute the per-visit bonus, clamp to non-negative, sum across visits, then add the re-consent bonus to the chosen last visit's `FINAL` row. A participant who never re-consented — either because no `ConsentVersion` with `version` 2 or above ever existed, or because their `signed_consent_version` is less than the current `active_consent_version` — receives a final total equal to the sum of provisional rows, with no bonus. A participant who did re-consent receives a final total equal to the sum of provisional rows plus 2500 cents.

### 3.9. Concurrency and Serialization

A handful of races are addressed deterministically.

Two coordinators submitting sign-consent on the same participant at the same time serialize on the participant's `status` transition out of `CONSENT_PENDING`; the first writer wins, and the second sees `ERR_INVALID_STATE` because the participant is no longer in `CONSENT_PENDING` by the time the second attempt is evaluated.

Two sign-consent calls racing for the last enrollment slot — the case where `enrolled_count` equals `target_enrollment - 1` and both succeed past the consent-version and state checks — serialize on the `enrolled_count` increment. Exactly one reaches `ENROLLED`; the loser is rejected with `ERR_TRIAL_FULL` because by the time its commit attempts to bump `enrolled_count`, the count already equals `target_enrollment`.

If an investigator publishes a new consent version at the same time a participant's sign-consent for the previous version is in flight, the writes are linearized on `active_consent_version`. If the publish commits first, the in-flight sign fails with `ERR_CONSENT_VERSION_STALE` because the body's `consent_version` no longer matches the new `active_consent_version`. If the sign commits first, the publish still succeeds, but the just-enrolled participant is now stale-versioned and is held from any further visit completion by the re-consent gate of §3.6.

If an IRB approval is being recorded at the same time a `PrincipalInvestigator` is publishing a new consent version that would shift `active_consent_version`, the two writes are independent unless the approval is the first action to flip `status` to `APPROVED`. In that case, the publish must still observe `status` to be not equal to `DRAFT` for the publish to be allowed; if the publish observes `DRAFT` (pre-approval), it fails with `ERR_INVALID_STATE`. The check is read-then-write under a row-level lock on the trial's `status`.

Two simultaneous visit-complete calls on the same visit serialize on `Visit.status`. At most one reaches `COMPLETED`; the second loses with `ERR_INVALID_STATE` because the visit is no longer `SCHEDULED`.

If two simultaneous adverse-event reports of `severity` `SEVERE` are made on the same participant while a visit-complete is mid-flight, both adverse-event rows are created (their idempotency keys differ), and the visit-complete transaction observes `open_ae_count` of at least 1 at precondition time and is rejected with `ERR_AE_BLOCKING`. The adverse-event inserts and the visit-complete read share the same row-level lock on the participant.

## 4. Endpoint Definitions

The API is mounted under the root prefix `/`. Operations that create new resources — for example a new trial, a new arm, a new consent version, a new participant, a new visit, a new adverse-event row, or a new IRB review — return a `201 Created` status code. Operations that modify or transition existing resources return a `200 OK` status code, with the exception of the visit delete-cancel which returns `204 No Content`. All list endpoints accept the optional `limit` and `offset` query parameters from §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/trials`                                                                       | Create a new Trial in DRAFT                                            | `PrincipalInvestigator` |
| GET    | `/trials`                                                                       | List Trials (supports `status` filter)                                 | `PrincipalInvestigator`, `IRBReviewer`, `StudyCoordinator` |
| GET    | `/trials/{trial_id}`                                                            | Read a single Trial                                                    | `PrincipalInvestigator`, `IRBReviewer`, `StudyCoordinator` |
| PATCH  | `/trials/{trial_id}`                                                            | Update Trial metadata (DRAFT only); supports OCC via `version`         | `PrincipalInvestigator` |
| POST   | `/trials/{trial_id}/submit-for-irb`                                             | DRAFT → IRB_PENDING                                                    | `PrincipalInvestigator` |
| POST   | `/trials/{trial_id}/irb-reviews`                                                | Submit an IRB decision; transitions Trial accordingly                  | `IRBReviewer` |
| GET    | `/trials/{trial_id}/irb-reviews`                                                | List IRB review history                                                | `PrincipalInvestigator`, `IRBReviewer` |
| POST   | `/trials/{trial_id}/open-enrollment`                                            | APPROVED → OPEN_FOR_ENROLLMENT                                         | `PrincipalInvestigator` |
| POST   | `/trials/{trial_id}/close-enrollment`                                           | OPEN_FOR_ENROLLMENT → CLOSED_TO_ENROLLMENT (manual)                    | `PrincipalInvestigator` |
| POST   | `/trials/{trial_id}/complete`                                                   | CLOSED_TO_ENROLLMENT → COMPLETED                                       | `PrincipalInvestigator` |
| POST   | `/trials/{trial_id}/terminate`                                                  | OPEN_FOR_ENROLLMENT → TERMINATED with cascade                          | `PrincipalInvestigator` |
| POST   | `/trials/{trial_id}/arms`                                                       | Add an arm to a DRAFT Trial                                            | `PrincipalInvestigator` |
| GET    | `/trials/{trial_id}/arms`                                                       | List arms on a Trial                                                   | `PrincipalInvestigator`, `IRBReviewer`, `StudyCoordinator` |
| POST   | `/trials/{trial_id}/consent-versions`                                           | Publish a new consent version (server-minted version number)           | `PrincipalInvestigator` |
| GET    | `/trials/{trial_id}/consent-versions`                                           | List consent versions for a Trial                                      | `PrincipalInvestigator`, `IRBReviewer`, `StudyCoordinator` |
| POST   | `/participants`                                                                 | Create a participant in SCREENING                                      | `StudyCoordinator` |
| GET    | `/participants/{participant_id}`                                                | Read a participant                                                     | `PrincipalInvestigator`, `StudyCoordinator`, `Participant_self` (self only) |
| POST   | `/participants/{participant_id}/evaluate`                                       | Run eligibility; SCREENING → ELIGIBLE | INELIGIBLE                    | `StudyCoordinator` |
| GET    | `/participants/{participant_id}/eligibility-history`                            | Chronological-variant eligibility replay (audit)                       | `PrincipalInvestigator`, `StudyCoordinator` |
| POST   | `/participants/{participant_id}/request-consent`                                | ELIGIBLE → CONSENT_PENDING                                             | `StudyCoordinator` |
| POST   | `/participants/{participant_id}/sign-consent`                                   | CONSENT_PENDING → ENROLLED; performs arm assignment                    | `Participant_self`, `StudyCoordinator` |
| POST   | `/participants/{participant_id}/withdraw`                                       | Withdraw participant with cascade                                      | `Participant_self`, `StudyCoordinator` |
| POST   | `/participants/{participant_id}/complete`                                       | ENROLLED → COMPLETED; finalizes payments                               | `StudyCoordinator` |
| POST   | `/participants/{participant_id}/visits`                                         | Schedule a visit                                                       | `StudyCoordinator` |
| GET    | `/participants/{participant_id}/visits`                                         | List visits on a participant                                           | `PrincipalInvestigator`, `StudyCoordinator`, `Participant_self` (self only) |
| POST   | `/visits/{visit_id}/complete`                                                   | SCHEDULED → COMPLETED with `actual_draw_at`; provisional Payment row   | `StudyCoordinator` |
| POST   | `/visits/{visit_id}/mark-missed`                                                | SCHEDULED → MISSED (after window has fully passed)                     | `StudyCoordinator` |
| DELETE | `/visits/{visit_id}`                                                            | Cancel a SCHEDULED visit                                               | `StudyCoordinator` |
| POST   | `/participants/{participant_id}/adverse-events`                                 | Report an adverse event; SEVERE/LIFE_THREATENING auto-escalate         | `PrincipalInvestigator`, `StudyCoordinator` |
| POST   | `/participants/{participant_id}/adverse-events/{adverse_event_id}/start-review` | AE OPEN → UNDER_REVIEW                                                 | `PrincipalInvestigator` |
| POST   | `/participants/{participant_id}/adverse-events/{adverse_event_id}/escalate`     | AE UNDER_REVIEW → ESCALATED_HOLD                                       | `PrincipalInvestigator` |
| POST   | `/participants/{participant_id}/adverse-events/{adverse_event_id}/resolve`      | AE {UNDER_REVIEW, ESCALATED_HOLD} → RESOLVED                           | `PrincipalInvestigator` |
| GET    | `/participants/{participant_id}/adverse-events`                                 | List adverse events for a participant (supports `status` filter)       | `PrincipalInvestigator`, `StudyCoordinator` |
| GET    | `/participants/{participant_id}/payments`                                       | List Payment rows (supports `kind` filter)                             | `PrincipalInvestigator`, `StudyCoordinator`, `Participant_self` (self only) |
| POST   | `/_clock/advance`                                                               | Test-only: advance the logical clock to `to_iso8601`                   | `PrincipalInvestigator`, `IRBReviewer`, `StudyCoordinator` |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_AUTH_REQUIRED`               | 401 Unauthorized |
| `ERR_FORBIDDEN`                   | 403 Forbidden    |
| `ERR_SOD_VIOLATION`               | 403 Forbidden    |
| `ERR_NOT_FOUND`                   | 404 Not Found    |
| `ERR_INVALID_STATE`               | 409 Conflict     |
| `ERR_IRB_EXPIRED`                 | 409 Conflict     |
| `ERR_RANDOMIZATION_MISCONFIGURED` | 422 Unprocessable Entity |
| `ERR_CONSENT_VERSION_STALE`       | 409 Conflict     |
| `ERR_TRIAL_FULL`                  | 409 Conflict     |
| `ERR_STRATUM_KEY_MISSING`         | 422 Unprocessable Entity |
| `ERR_AE_BLOCKING`                 | 409 Conflict     |
| `ERR_DRAW_OUTSIDE_WINDOW`         | 409 Conflict     |
| `ERR_WINDOW_NOT_YET_PASSED`       | 409 Conflict     |
| `ERR_DUPLICATE_VISIT_SEQUENCE`    | 409 Conflict     |
| `ERR_DUPLICATE_PROTOCOL_CODE`     | 409 Conflict     |
| `ERR_CROSS_PARTICIPANT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_VERSION_CONFLICT`            | 409 Conflict     |
| `ERR_INVALID_INPUT`               | 422 Unprocessable Entity |
| `ERR_NO_ARMS_DEFINED`             | 422 Unprocessable Entity |
