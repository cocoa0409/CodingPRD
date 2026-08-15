# Playtest Recruitment & Feedback Program API — Product Requirements Document

## 1. Introduction

Running a playtest program at a game studio is a compliance-sensitive logistics problem disguised as a research exercise. Participants must be screened against age, region, and platform criteria before they ever see an unreleased build; confidentiality agreements must be executed — and re-executed when legal re-papers a study — before any access key changes hands; sessions compete for lab stations, moderators, and participant attention; surveys and feedback tickets have to be scored and routed consistently; and every incentive payment must survive segregation-of-duties scrutiny. When a participant leaks a build, the fallout is procedural: investigations, substantiation, sanctions, and a cascade that unwinds their bookings, keys, signatures, and pending payouts.

This document specifies the Playtest Recruitment & Feedback Program API, the system of record for that entire lifecycle. The API is mounted under the `/playtests` path prefix and serves six distinct operator populations, from research operations administrators down to the participants themselves. It covers participant roster management and attribute verification, study setup with cohort capacity and incentive budgets, screening applications with a two-pass fit score, NDA versioning with a re-papering cascade, build distribution with expiring access keys and an append-only exposure journal, session scheduling with waitlist promotion and no-show discipline, survey instruments with weighted scoring, feedback triage with forced priority overrides, incentive payouts under budget control, and confidentiality breach adjudication. Section 2 states the system-wide contracts; Section 3 walks the business workflows; Sections 4 and 5 fix the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and contracts that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request that is missing either header, or whose `X-User-Role` value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles: `ResearchOpsAdmin`, `Researcher`, `Moderator`, `Participant`, `IncentiveOfficer`, and `LegalCounsel`. When the presented role is not permitted on the target endpoint, or when an ownership check on an owned resource fails, the request is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a participant — an application, a booking, a signature, a survey response, a redeemed key — compare the resource's `participant_id` field against `X-User-ID`. When `X-User-Role` is `Moderator`, `X-User-ID` is the `id` of the acting `Moderator`; ownership checks on a session compare the session's `moderator_id` field against `X-User-ID`. When `X-User-Role` is `ResearchOpsAdmin`, `Researcher`, `IncentiveOfficer`, or `LegalCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow calls for attribution (for example, `created_by_user_id` on an incentive payout, `adjudicated_by_user_id` on a breach case, or `reported_by_user_id` on a breach report) but never compares it to any entity's `id`. Ownership comparisons bite only where a workflow declares an action owner-only — the submit-info and withdrawal actions on an application, NDA signing, key redemption, booking cancellation by a participant, response submission, the assigned-moderator session actions, and the adjudicating counsel's breach actions. List and fetch endpoints are never owner-scoped: any caller whose role is permitted on the endpoint may read any resource it returns.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter controls how many items are skipped and defaults to 0. Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order; ties on `created_at` — common while the logical clock is held — are broken by creation sequence, earliest created first, so a listing is effectively in creation order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of resources matching the endpoint's filters and `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Clock and the Expiry Sweep

Every time-gated rule in the system — session start windows, signature and key expiry, rolling strike windows, recorded event times — evaluates against a server-side logical clock, never against wall-clock time. At startup, before any adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ResearchOpsAdmin` may install a new instant through an admin-only clock-setting capability whose payload carries `to_iso8601`; the response echoes the installed instant as `now_iso8601`. Once set, the clock holds that value until set again; it never falls back to wall-clock time.

Alongside the clock, operations runs an expiry checkpoint, the expiry sweep, which is also restricted to `ResearchOpsAdmin`. Each run expires every `PENDING` NDA signature whose `expires_at` is at or before the current logical instant — a signature whose `expires_at` equals the current instant expires — and every `ISSUED` access key whose `expires_at` is at or before the current instant, with the same boundary rule. Each expired key appends a `KEY_EXPIRED` record to the exposure journal and decrements the owning build's `keys_active_count` by one; expired signatures have no further side effects. The sweep response reports how many of each resource it processed via `signatures_expired` and `keys_expired`.

### 2.5. Common Resource Properties and the Append-Only Exposure Journal

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer that increments by one on every mutation of the resource, including mutations driven by cascades, and it anchors the optimistic concurrency control described in §2.7.

One entity breaks this pattern deliberately. The `ExposureRecord` is an append-only event journal: it carries `id` and `created_at` only — both `updated_at` and `version` are absent — because no endpoint ever mutates an exposure record. Records are written by key lifecycle transitions and by nothing else; each record holds `participant_id`, `build_id`, a denormalized `study_id` copied from the build, an `event_type` drawn from `KEY_ISSUED`, `KEY_REDEEMED`, `KEY_REVOKED`, and `KEY_EXPIRED`, and a `recorded_at` timestamp taken from the logical clock at the moment the event was recorded. The exposure-records listing filters by `participant_id`, `build_id`, `study_id`, and `event_type`.

All state changes are atomic and immediately consistent: every effect of a request — primary transition, cascade, counter adjustment, journal append — commits within that request and is visible to the next read.

### 2.6. Units, Precision, and Rounding

All monetary amounts are represented as integer cents; no fractional cents exist anywhere in the system. Whenever a monetary computation produces a fractional intermediate value — for example, applying a tier multiplier to a payout base — the result is rounded half-up to a whole cent before it is stored or compared. Scores, percentages, and priority values are carried to two decimal places, also using round-half-up. One component of the screening fit score (the platform component, §3.2) is rounded half-up to a whole number instead; that exception is stated where the score is defined.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

`PATCH /playtests/studies/{id}` requires the request body to carry `expected_study_version`, a non-optional field holding the `version` of the study as the client last observed it. If the study's current `version` does not match — because another writer's amendment has advanced it since the client last read the study — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no field of the study changes. An amendment legitimately supersedes the previously stored cohort criteria or budget, so a writer holding a stale version would otherwise silently overwrite a newer amendment it never saw.

`PATCH /playtests/sessions/{id}/reschedule` likewise requires `expected_session_version`, compared against the session's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) and the window is left untouched. A reschedule legitimately supersedes the previously stored window, which is exactly why a stale write must not land. On both guarded endpoints the expected-version field is validated — present and an integer, else `ERR_INVALID_REQUEST` — and compared against the current `version` immediately after the target resource is loaded, ahead of every remaining body validation, state-machine, and conflict check; a stale write therefore surfaces as `ERR_STALE_VERSION` no matter what else the request would have failed.

### 2.8. Scheduling Conflict Semantics

Three resources can be double-booked — lab stations, moderators, and participants — and each uses a different overlap convention. The convention is part of the contract; tests of adjacency depend on it.

A **lab station** is occupied by sessions in `SCHEDULED` or `IN_PROGRESS` under half-open interval semantics: a new window conflicts with an existing window whenever the new window's `starts_at` falls before the existing window's `ends_at` and the existing window's `starts_at` falls before the new window's `ends_at`. Windows that merely touch — one ending at exactly the instant the other begins — do not conflict. Violations are rejected with `ERR_STATION_CONFLICT`.

A **moderator** is occupied by their sessions in `SCHEDULED` or `IN_PROGRESS` under fifteen-minute buffered semantics: a new window conflicts whenever its `starts_at` falls before fifteen minutes after the existing window's `ends_at`, and the existing window's `starts_at` falls before fifteen minutes after the new window's `ends_at`. A gap of exactly fifteen minutes between windows is permitted; anything shorter conflicts with `ERR_MODERATOR_CONFLICT`.

A **participant** is occupied by sessions on which they hold a booking in `BOOKED` or `PROMOTED` under closed-interval semantics: a new window conflicts whenever its `starts_at` falls at or before the existing window's `ends_at` and the existing window's `starts_at` falls at or before the new window's `ends_at`. Unlike stations, touching endpoints do conflict here, and violations are rejected with `ERR_PARTICIPANT_CONFLICT`.

### 2.9. Validation Order and Error Precedence

Every request is validated against the same ordered gauntlet, and a failure at an earlier tier masks every later check. The tiers, evaluated in this order:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers are present and the role is a declared one; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** The role is permitted on the endpoint and, for `Participant` and `Moderator` actors on owned resources, `X-User-ID` equals the resource's ownership field; otherwise `ERR_FORBIDDEN`. This tier also covers breach-case actions attempted by a counsel who is not the case's adjudicator — though the breach workflows of §3.9, like the moderator-owned session actions of §3.5, evaluate the target's state check before that ownership comparison.
3. **Request shape.** Required fields are present, enum values are valid, and numeric ranges hold — `age_years` at least 13, `max_age` at least `min_age`, `cohort_capacity` at least 1, `incentive_budget_cents` at least 0, `max_keys` at least 1, `key_ttl_hours` at least 1, `seat_capacity` at least 1, `reach_count` at least 0, `reproducibility_pct` between 0 and 1 inclusive, `pass_threshold` between 0 and 100 inclusive, and each answer's `points` between 0 and its question's `max_points` inclusive; otherwise `ERR_INVALID_REQUEST`. One exception: a session window whose `ends_at` does not fall strictly after its `starts_at`, on session creation or reschedule, is reported as `ERR_WINDOW_VIOLATION` rather than `ERR_INVALID_REQUEST`.
4. **Existence.** Identifiers in the path are validated left to right, then foreign-key identifiers in the body; the first missing reference yields `ERR_NOT_FOUND`. On create endpoints where the role binds the caller to a persisted entity, the caller's own `X-User-ID` is resolved after the body references — a `Participant`-role caller whose id matches no participant is likewise `ERR_NOT_FOUND`.
5. **State-machine legality.** The target resource is in a state that permits the requested transition. The generic rejection is `ERR_INVALID_STATE`; named variants apply where the workflow defines them — `ERR_SESSION_NOT_BOOKABLE` for a booking into a session that is not `SCHEDULED`, `ERR_STUDY_NOT_RECRUITING` for an application create or approve against a study that is not `RECRUITING`, `ERR_STUDY_NOT_CLOSED` for a session start while the study is outside `CLOSED` and `ANALYSIS`, and `ERR_PARTICIPANT_NOT_ACTIVE` for an application create by a participant who is not `ACTIVE`.
6. **Cross-entity referential gates**, applied on key issuance, booking creation, application approval, survey submission, and payout approval: the build is `RELEASED` (`ERR_BUILD_NOT_RELEASED`), an `ENROLLED` application exists for the session's study (`ERR_NOT_ENROLLED`), a `PUBLISHED` agreement exists for the study (`ERR_NDA_NOT_PUBLISHED`), an `ATTENDED` booking exists for the survey's session (`ERR_ATTENDANCE_REQUIRED`), and the payout's participant is not `BANNED` (`ERR_PARTICIPANT_NOT_ACTIVE`).
7. **Compliance and safety gates**, applied on access-key issuance, payout approval, payout issuance, breach open-investigation, and participant reinstatement: a `SIGNED` signature on the study's current `PUBLISHED` agreement before any key is issued (`ERR_NDA_NOT_SIGNED`), segregation of duties on payout approval and issuance (`ERR_SEGREGATION_OF_DUTIES`) — on payout approval this check is evaluated before the tier-6 banned-participant gate — the breach reporter may not adjudicate (`ERR_REPORTER_CANNOT_ADJUDICATE`), and reinstatement is blocked while a breach case is open (`ERR_OPEN_BREACH_EXISTS`).
8. **Uniqueness and capacity constraints** on creation and transition endpoints that carry them: one non-terminal application per study and participant (`ERR_DUPLICATE_APPLICATION`), one active key per build and participant (`ERR_DUPLICATE_KEY`), one non-terminal booking per session and participant (`ERR_DUPLICATE_BOOKING`), one response per instrument, session, and participant (`ERR_DUPLICATE_RESPONSE`), one non-`VOID` payout per study and participant (`ERR_DUPLICATE_PAYOUT`), one `PUBLISHED` instrument per study (`ERR_INSTRUMENT_ALREADY_PUBLISHED`), cohort capacity on approval (`ERR_COHORT_FULL`), the key quota on issuance (`ERR_KEY_QUOTA_EXCEEDED`), a station for `IN_LAB` sessions (`ERR_STATION_REQUIRED`), an assigned moderator for session start (`ERR_MODERATOR_REQUIRED`), at least one attended booking before a payout is drafted (`ERR_NO_COMPENSABLE_ACTIVITY`), and every answered question known to the instrument (`ERR_UNKNOWN_QUESTION`).
9. **Temporal rules**, applied on session creation, session reschedule, moderator assignment, booking creation, session start, signature signing, and key redemption: the station half-open overlap (`ERR_STATION_CONFLICT`), the moderator buffered overlap (`ERR_MODERATOR_CONFLICT`), the participant closed-interval overlap (`ERR_PARTICIPANT_CONFLICT`), the session start window (`ERR_SESSION_NOT_IN_WINDOW`), the signature deadline (`ERR_SIGNATURE_EXPIRED`), and the key deadline (`ERR_KEY_EXPIRED`).
10. **The fiscal gate**, applied only on payout approval: the study's committed budget plus the recomputed final amount must not exceed the incentive budget, else `ERR_BUDGET_EXCEEDED`. This tier is evaluated last, so state and compliance failures always win over budget failures.

### 2.10. Confidentiality Governance and Segregation of Duties

Two governance principles cut across every workflow in Section 3.

First, confidentiality paperwork is a hard gate, not a formality. Approval of a screening application pins the exact NDA version the participant must sign, keys are issued only against a live signature on the study's currently published agreement, and re-publishing an agreement voids signatures on the retired version and re-papers every enrolled participant back through the signature step. The details live in §3.3 and §3.4.

Second, incentive money moves only under segregation of duties. The officer who drafts a payout may not approve it, and the officer who approves it may not issue it — those two pairwise checks are the entire constraint, so nothing forbids the drafting officer from also issuing — with the three attributions recorded as `created_by_user_id`, `approved_by_user_id`, and `issued_by_user_id`. The same separation-of-concerns principle governs breaches: the moderator or researcher who reports a breach may not adjudicate it, and only the counsel who opened the investigation may substantiate, dismiss, or sanction it.

## 3. Business Logic & Workflows

The workflows below are organized along the program's natural timeline: standing up the roster and the study, screening applicants, papering NDAs, distributing builds, running sessions, scoring surveys, triaging feedback, paying incentives, and adjudicating breaches. Rules that touch several workflows are stated where they bite hardest and cross-referenced elsewhere.

### 3.1. Roster and Program Setup: Participants, Moderators, Stations, and Studies

A participant enters the program when a `ResearchOpsAdmin` registers them with an `email` that is unique across all participants, a `full_name`, a self-declared `age_years` of at least 13, a self-declared `region_code` such as US-W, and self-declared `platform_tags` such as PC, PS5, or XB. New participants start in `REGISTERED` with `no_show_strikes` at 0, `risk_score` at 0, and `verified_platform_tags` empty. Activation moves a participant `REGISTERED` → `ACTIVE`; only `ACTIVE` participants may apply to studies. Operations may later attest a participant's hardware by replacing `verified_platform_tags` through the attribute-verification action, which increments the participant's `version`; the verified set — initially empty — is what the second pass of the fit score consults at approval time (§3.2). The participants listing supports filtering by `status` and `region_code`.

Suspension is the program's intermediate sanction. A `ResearchOpsAdmin` may suspend an `ACTIVE` participant, moving them `ACTIVE` → `SUSPENDED`, and the same transition fires automatically when the no-show strike rule of §3.5 trips or when a breach is substantiated (§3.9). Suspension runs a full cascade: every booking the participant holds in `BOOKED` or `PROMOTED` is cancelled, and each such cancellation frees a seat that immediately promotes the earliest-created eligible waitlisted booking on the same session under the promotion rule of §3.5; the participant's bookings in `WAITLISTED` are cancelled as well, though a waitlist cancellation frees no seat and promotes nobody; and every access key the participant holds in `ISSUED` is revoked, each revocation appending a `KEY_REVOKED` record to the exposure journal and decrementing the owning build's `keys_active_count` by one. Reinstatement moves `SUSPENDED` → `ACTIVE`, resets `no_show_strikes` to 0, and is refused with `ERR_OPEN_BREACH_EXISTS` while any breach case against the participant sits in `REPORTED`, `UNDER_INVESTIGATION`, or `SUBSTANTIATED`.

Banning is terminal and belongs to `LegalCounsel`. A ban moves the participant `ACTIVE` → `BANNED` or `SUSPENDED` → `BANNED` — the same cascade runs from either source state — and that cascade is the heaviest in the system: every booking in `BOOKED`, `PROMOTED`, or `WAITLISTED` is cancelled, with freed seats promoting waitlisted bookings per the booking-cancel rule; every access key in `ISSUED` or `REDEEMED` is revoked, each writing a `KEY_REVOKED` journal record and decrementing the build's `keys_active_count`; every NDA signature in `PENDING` or `SIGNED` is voided, and any application in `ENROLLED` whose signature was just voided reverts to `APPROVED`, decrementing the study's `enrolled_count` by one per reverted application; and every incentive payout in `DRAFT`, `PENDING_APPROVAL`, or `REJECTED` is voided outright, while a payout in `APPROVED` is voided with its committed amount released back — the study's `budget_committed_cents` is reduced by that payout's `amount_final_cents`.

Moderators are created by a `ResearchOpsAdmin` with a `display_name` and an `email` unique across moderators, starting in `ACTIVE`. A moderator's `status` moves `ACTIVE` → `INACTIVE` when they leave the rotation and `INACTIVE` → `ACTIVE` when they return, each through an administrative update that increments the moderator's `version`; only `ACTIVE` moderators may be assigned to sessions. Lab stations are registered with a unique `station_code`, a `location`, and an optional `equipment_tags` list defaulting to empty; a station's `status` moves `AVAILABLE` → `OUT_OF_SERVICE` when it is pulled for maintenance and `OUT_OF_SERVICE` → `AVAILABLE` when it comes back, each through an administrative update that increments the station's `version`. Both listings filter by `status`.

A study is the program's organizing container. A `ResearchOpsAdmin` creates one with a `title`, a `code` unique across studies, an inclusive eligibility age band `min_age` to `max_age` (the maximum must be at least the minimum), the `allowed_regions` eligible to participate, the `required_platforms` the study targets — an empty list means the study is platform-agnostic — a `cohort_capacity` of at least 1 capping enrolled applications, and an `incentive_budget_cents` of at least 0. A new study is `DRAFT` with `enrolled_count`, `budget_committed_cents`, and `budget_spent_cents` all at 0. The study lifecycle is a straight line: `DRAFT` → `RECRUITING` when operations opens recruitment, `RECRUITING` → `CLOSED` when operations closes it, `CLOSED` → `ANALYSIS` when a `Researcher` begins analysis, and `ANALYSIS` → `COMPLETED` when operations completes the study, which is terminal.

While a study is `DRAFT` or `RECRUITING`, operations may amend its `title`, `min_age`, `max_age`, `allowed_regions`, `required_platforms`, `cohort_capacity`, or `incentive_budget_cents`. The amendment endpoint is OCC-guarded per §2.7: the request must carry `expected_study_version` matching the study's current `version`, and a successful amendment increments that `version`. Amendments never recompute the fit scores of applications already on file — they govern future evaluations only. The studies listing filters by `status`.

### 3.2. Screening Applications and the Two-Pass Fit Score

An `ACTIVE` participant applies to a study by submitting a payload containing the `study_id`; the application records the applicant's `participant_id` from the caller's `X-User-ID`. The study must be `RECRUITING` (`ERR_STUDY_NOT_RECRUITING`), the applicant must be `ACTIVE` (`ERR_PARTICIPANT_NOT_ACTIVE`), and the pair must not already have a live application: at most one application per study and participant may exist in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `APPROVED`, or `ENROLLED`, so a prior `REJECTED` or `WITHDRAWN` application never blocks a fresh one — violations are `ERR_DUPLICATE_APPLICATION`. A new application starts `SUBMITTED`, and submission immediately computes the self-reported variant of the fit score, stored as `fit_score_provisional`.

The screening fit score is a sum of three components. The age component contributes 40 points when the participant's `age_years` falls within the study's `min_age`–`max_age` band, both bounds inclusive, and 0 otherwise. The region component contributes 30 points when the participant's `region_code` appears in the study's `allowed_regions`, and 0 otherwise. The platform component depends on the study's targeting: when `required_platforms` is empty, it contributes a flat 30 points; otherwise it contributes 30 points scaled by the fraction of the study's required platforms present in the relevant platform-tag set, rounded half-up to a whole number. The two variants differ only in which platform-tag set they consult. The **self-reported** variant, computed at submission, uses the participant's self-declared `platform_tags` and lands in `fit_score_provisional`. The **verified** variant, computed at approval, uses `verified_platform_tags` — empty until operations verifies attributes — and lands in `fit_score_final`, which stays null until an approval is attempted; identical inputs therefore produce a different score whenever verification narrowed the platform set. The score is pure attribute matching; the participant's status plays no part in it.

Review is a `Researcher`'s workflow. Starting review moves `SUBMITTED` → `UNDER_REVIEW`. Requesting more information moves `UNDER_REVIEW` → `INFO_REQUESTED` and records the request's `info_request_note`; the owning participant answers through the submit-info action — optionally attaching a `supplemental_note`, which is accepted but not persisted on the application — which returns the application `INFO_REQUESTED` → `UNDER_REVIEW`. That cycle may repeat without limit. Both the submit-info action and withdrawal are owner-only: a caller whose `X-User-ID` is not the application's `participant_id` is refused with `ERR_FORBIDDEN`. Withdrawal moves an application `SUBMITTED` → `WITHDRAWN` or `UNDER_REVIEW` → `WITHDRAWN`; either way it is terminal.

Approval is the gate with the most conditions, and they bind in a fixed order. The application must be `UNDER_REVIEW`; the study must still be `RECRUITING` (`ERR_STUDY_NOT_RECRUITING`); a `PUBLISHED` NDA agreement must exist for the study — at most one can exist at a time by the publish rule of §3.3 — else `ERR_NDA_NOT_PUBLISHED`; the cohort must have room, meaning `enrolled_count` is strictly below `cohort_capacity` with equality meaning full (`ERR_COHORT_FULL`); and only then is the verified fit score computed, stored as `fit_score_final`, and compared against the pass mark of 60 — a score below 60 is rejected with `ERR_FIT_SCORE_BELOW_THRESHOLD`. On success the application moves `UNDER_REVIEW` → `APPROVED`, its `pinned_nda_agreement_id` is set to the published agreement's `id`, and a `PENDING` NDA signature is created for the participant on that agreement with an `expires_at` seven days out. Rejection instead moves `UNDER_REVIEW` → `REJECTED` and records the supplied `decision_reason`.

Enrollment itself is automatic: when the application's pending signature is signed (§3.3), the application bubbles `APPROVED` → `ENROLLED` and the study's `enrolled_count` increases by one. The applications listing filters by `study_id`, `participant_id`, `status`, and `pinned_nda_agreement_id`.

### 3.3. NDA Paperwork, Signatures, and the Re-Papering Cascade

A `LegalCounsel` authors each NDA version for a study with a `study_id`, a `version_label` unique within that study (v1, v2, and so on), and the full `body_text` presented for signature; new agreements are `DRAFT`. Publishing moves an agreement `DRAFT` → `PUBLISHED` and stamps `published_at` — and publishing is never a local act. The publish cascade runs three links: the previously `PUBLISHED` agreement for the same study, if any, becomes `RETIRED` (the only way an agreement leaves `PUBLISHED`); every signature on that retired agreement in `PENDING` or `SIGNED` becomes `VOIDED`; and every application in `ENROLLED` whose signed signature was just voided reverts `ENROLLED` → `APPROVED`, decrementing the study's `enrolled_count` by one per reverted application, switching its `pinned_nda_agreement_id` to the newly published agreement, and receiving a fresh `PENDING` signature on the new version with a seven-day `expires_at`. The enrolled cohort, in effect, re-papers itself onto the new text.

A signature record ties together `agreement_id`, `participant_id`, a denormalized `study_id`, and the `application_id` whose enrollment it gates. It is created `PENDING` with `expires_at` set to its creation instant plus seven days. At most one signature per agreement and participant may exist in `PENDING` or `SIGNED`. Signing is an owner-only act by the named participant (`ERR_FORBIDDEN` for anyone else); the owning agreement must still be `PUBLISHED` — a signature whose agreement has been retired can no longer be signed and fails with `ERR_INVALID_STATE` — and the signing instant must fall strictly before `expires_at`, with an instant exactly equal to `expires_at` treated as expired (`ERR_SIGNATURE_EXPIRED`). A successful signing moves the signature `PENDING` → `SIGNED`, stamps `signed_at`, and bubbles the gated application `APPROVED` → `ENROLLED`, incrementing the study's `enrolled_count` by one. Signatures left `PENDING` past their deadline move `PENDING` → `EXPIRED` under the expiry sweep (§2.4). A signature moves `PENDING` → `VOIDED` or `SIGNED` → `VOIDED` when its agreement is retired by a re-publish or when the participant is banned; when a `SIGNED` signature is voided and its application stood `ENROLLED`, the application reverts to `APPROVED` as described above. The signatures listing filters by `agreement_id`, `participant_id`, `study_id`, `application_id`, and `status`; the agreements listing filters by `study_id` and `status`.

### 3.4. Build Distribution, Access Keys, and the Exposure Journal

Operations registers each game build against a study with a `study_id`, a `build_label` unique within the study (0.9.3-qa and the like), a `max_keys` of at least 1 capping simultaneously active keys, and an optional `key_ttl_hours` — the hours from issuance until an unredeemed key expires — defaulting to 72 and never below 1. A build starts `STAGED` with `keys_active_count` at 0. Releasing moves `STAGED` → `RELEASED` and stamps `released_at`; the owning study must be in `RECRUITING`, `CLOSED`, or `ANALYSIS`, otherwise the release fails with `ERR_INVALID_STATE`. Retiring moves `RELEASED` → `RETIRED` and revokes every key of the build still in `ISSUED` — each writing a `KEY_REVOKED` journal record and decrementing `keys_active_count` by one — while leaving `REDEEMED` keys untouched. The builds listing filters by `study_id` and `status`.

Key issuance is the most heavily gated create in the program, and the gates bind in order. The build must be `RELEASED` (`ERR_BUILD_NOT_RELEASED`). The recipient must hold a `SIGNED` signature on the study's currently `PUBLISHED` agreement — this safety gate outranks the quota check — else `ERR_NDA_NOT_SIGNED`. The build's `keys_active_count` must be strictly below `max_keys`, with equality meaning the quota is exhausted (`ERR_KEY_QUOTA_EXCEEDED`). And the build and participant pair must not already hold an active key: an existing key in `ISSUED` or `REDEEMED` blocks issuance with `ERR_DUPLICATE_KEY`, while an `EXPIRED` or `REVOKED` key does not. A successful issuance mints a unique `key_code` — the literal KEY- followed by twelve uppercase alphanumeric characters — sets the key `ISSUED` with `expires_at` at the issuance instant plus the build's `key_ttl_hours`, increments `keys_active_count` by one, and appends a `KEY_ISSUED` record to the exposure journal. The `keys_active_count` counter always reflects keys in `ISSUED` or `REDEEMED`.

Redemption is owner-only (`ERR_FORBIDDEN` for anyone but the key's participant) and requires the key still `ISSUED` with the redemption instant strictly before `expires_at` — equality is expired and rejected with `ERR_KEY_EXPIRED`. Redemption moves `ISSUED` → `REDEEMED`, stamps `redeemed_at`, and appends a `KEY_REDEEMED` record; `keys_active_count` does not change, because a redeemed key remains in the active set. Manual revocation by a `ResearchOpsAdmin` or `LegalCounsel` moves `ISSUED` → `REVOKED` with a `KEY_REVOKED` record and a one-count decrement; the same transition arrives by cascade from participant suspension, banning, or build retirement. The sweep moves `ISSUED` → `EXPIRED` past the deadline with a `KEY_EXPIRED` record and a decrement. One transition exists only inside the ban cascade: `REDEEMED` → `REVOKED`, again with its `KEY_REVOKED` record and a one-count decrement, fires when the participant is banned. The keys listing filters by `build_id`, `participant_id`, and `status`.

Cohort tracking across builds is served by a per-study summary. Only builds with `released_at` set appear — `STAGED` builds are excluded — ordered by `released_at` ascending with `created_at` ascending as the tie-break. For each build the summary carries the build's `build_id`, `build_label`, and `released_at`, and reports `keys_issued`, the count of `KEY_ISSUED` journal records for that build, and `keys_redeemed`, the count of `KEY_REDEEMED` records. Retention is computed between adjacent builds in that order: for the first build, or whenever the immediately previous build issued zero keys, `retained_from_previous` and `retention_pct` are null; otherwise `retained_from_previous` is the number of distinct participants holding a `KEY_ISSUED` record on both the previous build and the current one, and `retention_pct` is that count divided by the previous build's `keys_issued`, multiplied by 100, and rounded half-up to two decimal places. The response carries the `study_id` and the per-build entries under `builds`.

### 3.5. Sessions from Scheduling to Completion: Seats, Waitlists, and Attendance

A `Researcher` schedules a playtest session with a `study_id`, a `mode` of `REMOTE` or `IN_LAB`, a window from `starts_at` to `ends_at`, and a `seat_capacity` of at least 1. The window's end must fall strictly after its start; a window that fails this is rejected with `ERR_WINDOW_VIOLATION`, not the generic request error. The study must be in `RECRUITING`, `CLOSED`, or `ANALYSIS` (`ERR_INVALID_STATE` otherwise). An `IN_LAB` session must name a `station_id` for an `AVAILABLE` station, and a `REMOTE` session must not carry a `station_id` at all — both violations are `ERR_STATION_REQUIRED` — and an in-lab window is checked against that station's existing bookings under the half-open semantics of §2.8 (`ERR_STATION_CONFLICT`). A new session is `SCHEDULED` with `seats_taken` at 0 and no moderator assigned. The sessions listing filters by `study_id`, `moderator_id`, `station_id`, and `status`.

Moderator assignment is a separate act. Assigning — or replacing — a session's moderator requires the session still `SCHEDULED` and the named moderator `ACTIVE`, and it runs the moderator's fifteen-minute buffered overlap check of §2.8 against that moderator's other `SCHEDULED` or `IN_PROGRESS` sessions (`ERR_MODERATOR_CONFLICT`); success writes the payload's `moderator_id` onto the session and increments the session's `version`. Rescheduling moves the window while the session is `SCHEDULED`: the request carries `expected_session_version` under the OCC rule of §2.7 alongside the new `starts_at` and `ends_at`, re-validates the window rule, and re-runs the station half-open and moderator buffered conflict checks for the new window — the session itself excluded from both — before committing, incrementing the session's `version` on success.

Only the assigned moderator may start a session, and the start is heavily preconditioned: the session must be `SCHEDULED`; a moderator must be assigned at all, else `ERR_MODERATOR_REQUIRED`; the caller's `X-User-ID` must equal the session's `moderator_id` (`ERR_FORBIDDEN`); the study must be in `CLOSED` or `ANALYSIS` (`ERR_STUDY_NOT_CLOSED`); and the current instant must fall within the session window, both `starts_at` and `ends_at` inclusive (`ERR_SESSION_NOT_IN_WINDOW`). Starting moves `SCHEDULED` → `IN_PROGRESS`.

Booking is the participant's side of the market. A participant books with a payload containing the `session_id`; the booking's `participant_id` comes from `X-User-ID`. The session must be `SCHEDULED` (`ERR_SESSION_NOT_BOOKABLE`); the participant must hold an `ENROLLED` application in the session's study (`ERR_NOT_ENROLLED`); no non-terminal booking may already exist for the pair — `BOOKED`, `WAITLISTED`, or `PROMOTED` all block with `ERR_DUPLICATE_BOOKING`; and the new window must survive the participant's closed-interval overlap check of §2.8 against sessions where they already hold a `BOOKED` or `PROMOTED` seat (`ERR_PARTICIPANT_CONFLICT`). The seat gate is evaluated before the booking is inserted: if `seats_taken` is strictly below `seat_capacity`, the booking lands `BOOKED` and `seats_taken` increments by one; otherwise it lands `WAITLISTED` and no seat is consumed. `seats_taken` always counts bookings in `BOOKED`, `PROMOTED`, `ATTENDED`, or `NO_SHOW`. The bookings listing filters by `session_id`, `participant_id`, and `status`.

Cancellation frees seats and feeds the waitlist. A booking moves `BOOKED` → `CANCELLED` or `PROMOTED` → `CANCELLED` at the request of its owning participant or a `ResearchOpsAdmin` — anyone else is `ERR_FORBIDDEN` — and the same transitions arrive by cascade when the participant is suspended or banned or when the session itself is cancelled. Cancelling a held seat decrements `seats_taken` by one and then promotes the earliest-created eligible waitlisted booking on the same session: eligible means `WAITLISTED` with an owning participant still `ACTIVE`, ranked by `created_at` ascending with ties broken by creation sequence, earliest created first. A promotion moves that booking `WAITLISTED` → `PROMOTED` and increments `seats_taken` by one, so a cancel-plus-promotion pair leaves `seats_taken` unchanged; when no eligible waitlisted booking exists, the seat simply stays free. A `WAITLISTED` → `CANCELLED` transition frees no seat and triggers no promotion. One exception overrides all of this: when the cancellation is part of a session-cancel cascade, no promotion happens at all, because the session is dead.

Attendance is marked by the assigned moderator while the session is `IN_PROGRESS` (a booking not in `BOOKED` or `PROMOTED`, or a session not `IN_PROGRESS`, fails with `ERR_INVALID_STATE` — these state checks run before the ownership comparison — and `ERR_FORBIDDEN` for any caller whose `X-User-ID` is not the session's `moderator_id`): a booking moves `BOOKED` → `ATTENDED` or `PROMOTED` → `ATTENDED` via the mark-attended action, and `BOOKED` → `NO_SHOW` or `PROMOTED` → `NO_SHOW` via the mark-no-show action. Completing the session — `IN_PROGRESS` → `COMPLETED`, again the assigned moderator only, with the state check again evaluated before the ownership comparison — auto-marks every booking still in `BOOKED` or `PROMOTED` as `NO_SHOW`, the set of bookings to auto-mark being collected at the moment completion begins, stamping each with a `no_show_recorded_at` of the completion instant, and each of those auto-no-shows recomputes its participant's strike count exactly as an explicit mark would. Cancelling the session outright — `SCHEDULED` → `CANCELLED`, available to a `Researcher` or `ResearchOpsAdmin` — cancels every booking in `BOOKED`, `PROMOTED`, or `WAITLISTED` with no waitlist promotion and zeroes `seats_taken`.

No-shows carry the program's attendance discipline. Whenever a booking enters `NO_SHOW`, `no_show_recorded_at` is stamped and the participant's `no_show_strikes` is recomputed as the count of that participant's `NO_SHOW` bookings whose `no_show_recorded_at` falls on or after the instant ninety days before now — a rolling window with an inclusive boundary; `CANCELLED` and `ATTENDED` bookings never count. If the participant is `ACTIVE` and the recomputed count reaches 3 — exactly three strikes is enough — the participant transitions automatically `ACTIVE` → `SUSPENDED` and the full suspension cascade of §3.1 runs: their other `BOOKED` and `PROMOTED` bookings cancel with waitlist promotion on each freed seat, their `WAITLISTED` bookings cancel without promotion, and their `ISSUED` keys revoke with journal records.

### 3.6. Survey Instruments and Response Scoring

A `Researcher` designs each survey instrument with a `study_id`, a `title`, a `questions` list, and a `pass_threshold` between 0 and 100 inclusive. Each entry in `questions` carries a `question_key` unique within the instrument, a `weight` greater than 0, and a `max_points` of at least 1. Instruments are born `DRAFT`; publishing moves `DRAFT` → `PUBLISHED` and is refused with `ERR_INSTRUMENT_ALREADY_PUBLISHED` while any other instrument of the same study is `PUBLISHED`, so at most one published instrument exists per study at any moment; retiring moves `PUBLISHED` → `RETIRED`. The instruments listing filters by `study_id` and `status`.

A participant drafts a response with `instrument_id`, `session_id`, and an `answers` list whose entries pair a `question_key` with `points` between 0 and that question's `max_points` inclusive; the response's `participant_id` is taken from `X-User-ID`. At most one response may exist per instrument, session, and participant triple (`ERR_DUPLICATE_RESPONSE`). A draft response holds null `weighted_score`, `score_pct`, and `passed` until it is submitted.

Submission is owner-only (`ERR_FORBIDDEN`) and allowed from `DRAFT` alone. The instrument must be `PUBLISHED` at submit time (`ERR_INVALID_STATE`), the participant must hold an `ATTENDED` booking for the covered session (`ERR_ATTENDANCE_REQUIRED`), and every answered `question_key` must exist in the instrument (`ERR_UNKNOWN_QUESTION`). Scoring then runs with a pinned rounding order. The instrument's total weight is the sum of every question's `weight`. Each answered question contributes its `points` divided by its `max_points`, multiplied by its `weight`, and that per-question contribution is rounded half-up to two decimal places before any summation — rounding only the final sum is not equivalent and is non-conformant. The `weighted_score` is the sum of those rounded contributions, itself rounded half-up to two decimals; `score_pct` is the `weighted_score` divided by the total weight, multiplied by 100, rounded half-up to two decimals; and `passed` is true when `score_pct` is at least the instrument's `pass_threshold` — equality passes. Questions with no matching answer contribute 0. Submission stamps `submitted_at` and moves the response `DRAFT` → `SUBMITTED`; submitted responses are immutable, and no endpoint mutates one. The responses listing filters by `instrument_id`, `session_id`, `participant_id`, and `status`.

### 3.7. Feedback Tickets: Triage, Priority, and Routing

A `Moderator` or `Researcher` files a feedback ticket with a `study_id`, a short `title`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a `reach_count` estimating affected users at 0 or more, and a `reproducibility_pct` between 0 and 1 inclusive. An optional `session_id` links the session where the issue was observed and an optional `survey_response_id` links the response the ticket synthesizes; when present, each reference must belong to the ticket's study. A new ticket is `NEW` with `priority_score` and `priority_tier` null until its first triage and `backlog_target` null until it is routed.

Triage is a `Researcher`'s act and moves `NEW` → `TRIAGED` — or, on the repeat pass described below, `NEEDS_INFO` → `TRIAGED` — computing the ticket's priority each time. The priority score starts from a severity weight: 1 for `LOW`, 2 for `MEDIUM`, 3 for `HIGH`, and 5 for `CRITICAL`. The raw score is that weight multiplied by 100 and by the ticket's `reproducibility_pct`, plus a reach contribution that counts each affected user as half a point but never counts more than one thousand affected users. The `priority_score` is that raw value rounded half-up to two decimal places. The `priority_tier` then buckets the score: `P1` when the score is at least 400, otherwise `P2` when at least 200, otherwise `P3` when at least 80, otherwise `P4`. One forced override stands above the arithmetic: a ticket whose `severity` is `CRITICAL` and whose `reach_count` is at least 100 is `P1` regardless of its score.

The remaining ticket lifecycle is a `Researcher`'s loop. Requesting more information moves `TRIAGED` → `NEEDS_INFO`, and the `TRIAGED` → `NEEDS_INFO` → `TRIAGED` cycle may repeat, with each triage recomputing the score and tier from the ticket's current fields. Routing moves `TRIAGED` → `ROUTED` and sets `backlog_target` to one of `GAMEPLAY`, `PERFORMANCE`, `UX`, `AUDIO`, or `INFRA`. From `ROUTED`, resolution moves the ticket `ROUTED` → `RESOLVED` and the won't-fix call moves it `ROUTED` → `WONT_FIX`; both are terminal. The tickets listing filters by `study_id`, `session_id`, `survey_response_id`, `status`, and `priority_tier`.

### 3.8. Incentive Payouts and Budget Control

An `IncentiveOfficer` drafts a payout for a study and participant pair with `study_id` and `participant_id`. Drafting requires at least one `ATTENDED` booking by that participant in that study (`ERR_NO_COMPENSABLE_ACTIVITY`), and at most one payout per pair may exist outside `VOID` — a payout in `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, or `ISSUED` blocks a second with `ERR_DUPLICATE_PAYOUT`. Creation computes the provisional variant of the incentive amount and freezes it into `amount_provisional_cents` — never recomputed for that payout again — records the drafting officer in `created_by_user_id`, and leaves `amount_final_cents` null until approval. A new payout is `DRAFT`; submitting it moves `DRAFT` → `PENDING_APPROVAL`.

The amount formula counts the participant's footprint in the study. The attended count is the number of that participant's `SessionBooking` records in `ATTENDED` on sessions belonging to the payout's study — sessions contribute their bookings regardless of the session's own status. The no-show count is the same set filtered to `NO_SHOW`. The passed-survey count is the participant's `SUBMITTED` responses with `passed` true on instruments belonging to the study. The base is the attended count multiplied by 5,000 cents. A tier multiplier scales that base: one and a half when the attended count is at least 3 — exactly three attended sessions enters the top tier — one and a quarter when it is exactly 2, and one otherwise. The survey bonus adds 1,000 cents per passed survey. The **provisional** amount is the scaled base, rounded half-up to whole cents, plus the survey bonus, with no penalty term. The **final** amount is recomputed live at approval from the same ingredients — late attendance, no-show, and survey changes flow in — and then reduced by 2,000 cents per no-show, floored at zero so a heavy no-show record can never drive a payout negative. Identical underlying data therefore yields a final amount at most equal to the provisional one, and strictly less whenever any no-show exists.

Approval is the fiscal gate of the program, and four checks guard it. The payout must be `PENDING_APPROVAL` — this state check outranks the budget gate, and a payout in any other state fails with `ERR_INVALID_STATE`. Segregation of duties forbids the officer recorded in `created_by_user_id` from approving their own draft (`ERR_SEGREGATION_OF_DUTIES`). A payout whose participant has been `BANNED` is refused with `ERR_PARTICIPANT_NOT_ACTIVE`. And the budget check runs last — state and compliance failures always win over budget failures — with a pinned evaluation order: first the final amount is computed; then the study's `budget_committed_cents` plus that final amount is compared against `incentive_budget_cents`, and an excess rejects the approval with `ERR_BUDGET_EXCEEDED` and changes nothing; on success the payout's `amount_final_cents` is stored and the same amount is added to `budget_committed_cents`, and `approved_by_user_id` records the approving officer. Approval moves `PENDING_APPROVAL` → `APPROVED`.

The committed set backing `budget_committed_cents` is the study's payouts in `APPROVED` or `ISSUED` — spent money stays committed — while `budget_spent_cents` sums the `amount_final_cents` of payouts in `ISSUED` alone. Rejection moves `PENDING_APPROVAL` → `REJECTED` and records the supplied `rejection_reason`; resubmission moves `REJECTED` → `PENDING_APPROVAL`, and that revision loop may repeat. Issuance moves `APPROVED` → `ISSUED`: the issuing officer must differ from the officer in `approved_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), the study's `budget_spent_cents` increases by `amount_final_cents`, and `issued_by_user_id` records the issuer. `ISSUED` is terminal. The ban cascade of §3.1 voids payouts in flight: payouts move `DRAFT` → `VOID`, `PENDING_APPROVAL` → `VOID`, or `REJECTED` → `VOID` with no further effect, while an `APPROVED` → `VOID` transition releases the payout's commitment by reducing `budget_committed_cents` by its `amount_final_cents`. The payouts listing filters by `study_id`, `participant_id`, and `status`.

### 3.9. Confidentiality Breaches: Reporting, Adjudication, and Sanction

A breach case opens when a `Moderator` or `Researcher` reports one with the accused `participant_id`, the `study_id` whose confidentiality was breached, a free-text `evidence_summary`, and a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`. The case starts `REPORTED`, with `reported_by_user_id` and `reported_by_role` captured from the request headers, and `adjudicated_by_user_id` still null.

A `LegalCounsel` opens the investigation, moving `REPORTED` → `UNDER_INVESTIGATION` and recording themselves in `adjudicated_by_user_id`; the reporter is barred from adjudicating their own report, and an opener whose `X-User-ID` equals `reported_by_user_id` is refused with `ERR_REPORTER_CANNOT_ADJUDICATE`. From `UNDER_INVESTIGATION`, only the adjudicating counsel may act along three branches — on each of them the case's state is checked first, a case not in the branch's required state failing with `ERR_INVALID_STATE`, and only then is the caller compared against `adjudicated_by_user_id`, anyone else failing the ownership comparison with `ERR_FORBIDDEN`.

Substantiation moves `UNDER_INVESTIGATION` → `SUBSTANTIATED` and is the heaviest branch. The participant's `risk_score` increases by the severity weight — 10 for a `MINOR` breach, 25 for `MAJOR`, 40 for `CRITICAL` — capped at 100 so repeated substantiations never exceed it. The cascade then fires: if the participant is `ACTIVE`, they become `SUSPENDED`, and the suspension cascade of §3.1 runs in full — their bookings in `BOOKED`, `PROMOTED`, and `WAITLISTED` are cancelled, each freed seat promoting the earliest-created eligible waitlisted booking on that session so a cancel-plus-promotion pair leaves the session's `seats_taken` unchanged, and their access keys in `ISSUED` are revoked with a `KEY_REVOKED` journal record each.

Dismissal moves `UNDER_INVESTIGATION` → `DISMISSED`, terminal and side-effect free.

Sanction moves `SUBSTANTIATED` → `SANCTIONED` with a `sanction_type` of `WARNING` or `BAN` and an optional `sanction_note`. A `BAN` drives an `ACTIVE` or `SUSPENDED` participant into `BANNED` and runs the full ban cascade of §3.1 — bookings cancelled with promotion, all keys including `REDEEMED` ones revoked, signatures voided with enrolled applications reverting, and payouts voided with committed budget released; a participant still `REGISTERED` (never activated, so never suspended by the substantiation) keeps that status while the case still closes `SANCTIONED`. A `WARNING` leaves the participant's status untouched — they remain `SUSPENDED` from the substantiation — and because the case has left `SUBSTANTIATED`, it no longer blocks reinstatement: recall from §3.1 that reinstatement is refused only while a case sits in `REPORTED`, `UNDER_INVESTIGATION`, or `SUBSTANTIATED`. The breach listing filters by `participant_id`, `study_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition — return `200 OK`, as do all reads and the clock and sweep capabilities. The table below fixes the HTTP contract only; request payloads, computed fields, and side effects are defined by the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/playtests/_clock/set_current_utc` | Set the server's logical clock | ResearchOpsAdmin |
| POST | `/playtests/_sweeps/run-expiry` | Run the expiry sweep over signatures and keys | ResearchOpsAdmin |
| POST | `/playtests/participants` | Register a participant | ResearchOpsAdmin |
| GET | `/playtests/participants` | List participants | ResearchOpsAdmin, Researcher, IncentiveOfficer, LegalCounsel, Moderator |
| GET | `/playtests/participants/{id}` | Fetch one participant | ResearchOpsAdmin, Researcher, IncentiveOfficer, LegalCounsel, Moderator, Participant |
| POST | `/playtests/participants/{id}/activate` | Activate a registered participant | ResearchOpsAdmin |
| POST | `/playtests/participants/{id}/verify-attributes` | Set a participant's verified platform tags | ResearchOpsAdmin |
| POST | `/playtests/participants/{id}/suspend` | Suspend an active participant | ResearchOpsAdmin |
| POST | `/playtests/participants/{id}/reinstate` | Reinstate a suspended participant | ResearchOpsAdmin |
| POST | `/playtests/participants/{id}/ban` | Ban a participant | LegalCounsel |
| POST | `/playtests/moderators` | Create a moderator | ResearchOpsAdmin |
| GET | `/playtests/moderators` | List moderators | ResearchOpsAdmin, Researcher |
| GET | `/playtests/moderators/{id}` | Fetch one moderator | ResearchOpsAdmin, Researcher, Moderator |
| PATCH | `/playtests/moderators/{id}` | Update a moderator's status | ResearchOpsAdmin |
| POST | `/playtests/studies` | Create a study | ResearchOpsAdmin |
| GET | `/playtests/studies` | List studies | ResearchOpsAdmin, Researcher, IncentiveOfficer, LegalCounsel, Moderator |
| GET | `/playtests/studies/{id}` | Fetch one study | ResearchOpsAdmin, Researcher, IncentiveOfficer, LegalCounsel, Moderator, Participant |
| PATCH | `/playtests/studies/{id}` | Amend a study's criteria or budget (OCC-guarded) | ResearchOpsAdmin |
| POST | `/playtests/studies/{id}/open-recruitment` | Open recruitment for a study | ResearchOpsAdmin |
| POST | `/playtests/studies/{id}/close-recruitment` | Close recruitment for a study | ResearchOpsAdmin |
| POST | `/playtests/studies/{id}/begin-analysis` | Begin analysis on a closed study | Researcher |
| POST | `/playtests/studies/{id}/complete` | Complete a study | ResearchOpsAdmin |
| GET | `/playtests/studies/{id}/cohort-summary` | Cohort tracking summary across released builds | ResearchOpsAdmin, Researcher |
| POST | `/playtests/applications` | Apply to a study | Participant |
| GET | `/playtests/applications` | List screening applications | ResearchOpsAdmin, Researcher, Participant |
| GET | `/playtests/applications/{id}` | Fetch one application | ResearchOpsAdmin, Researcher, Participant |
| POST | `/playtests/applications/{id}/start-review` | Start reviewing an application | Researcher |
| POST | `/playtests/applications/{id}/request-info` | Request more information from the applicant | Researcher |
| POST | `/playtests/applications/{id}/submit-info` | Supply the requested information | Participant |
| POST | `/playtests/applications/{id}/approve` | Approve an application | Researcher |
| POST | `/playtests/applications/{id}/reject` | Reject an application | Researcher |
| POST | `/playtests/applications/{id}/withdraw` | Withdraw an application | Participant |
| POST | `/playtests/nda-agreements` | Author an NDA agreement version | LegalCounsel |
| GET | `/playtests/nda-agreements` | List NDA agreements | ResearchOpsAdmin, Researcher, LegalCounsel, Participant |
| GET | `/playtests/nda-agreements/{id}` | Fetch one NDA agreement | ResearchOpsAdmin, Researcher, LegalCounsel, Participant |
| POST | `/playtests/nda-agreements/{id}/publish` | Publish an NDA agreement | LegalCounsel |
| GET | `/playtests/nda-signatures` | List NDA signatures | ResearchOpsAdmin, Researcher, LegalCounsel, Participant |
| GET | `/playtests/nda-signatures/{id}` | Fetch one NDA signature | ResearchOpsAdmin, Researcher, LegalCounsel, Participant |
| POST | `/playtests/nda-signatures/{id}/sign` | Sign a pending NDA signature | Participant |
| POST | `/playtests/builds` | Register a game build | ResearchOpsAdmin |
| GET | `/playtests/builds` | List builds | ResearchOpsAdmin, Researcher, Moderator, Participant |
| GET | `/playtests/builds/{id}` | Fetch one build | ResearchOpsAdmin, Researcher, Moderator, Participant |
| POST | `/playtests/builds/{id}/release` | Release a staged build | ResearchOpsAdmin |
| POST | `/playtests/builds/{id}/retire` | Retire a released build | ResearchOpsAdmin |
| POST | `/playtests/access-keys` | Issue an access key | ResearchOpsAdmin |
| GET | `/playtests/access-keys` | List access keys | ResearchOpsAdmin, Researcher, LegalCounsel, Participant |
| GET | `/playtests/access-keys/{id}` | Fetch one access key | ResearchOpsAdmin, Researcher, LegalCounsel, Participant |
| POST | `/playtests/access-keys/{id}/redeem` | Redeem an issued key | Participant |
| POST | `/playtests/access-keys/{id}/revoke` | Revoke an issued key | ResearchOpsAdmin, LegalCounsel |
| POST | `/playtests/lab-stations` | Create a lab station | ResearchOpsAdmin |
| GET | `/playtests/lab-stations` | List lab stations | ResearchOpsAdmin, Researcher, Moderator |
| GET | `/playtests/lab-stations/{id}` | Fetch one lab station | ResearchOpsAdmin, Researcher, Moderator |
| PATCH | `/playtests/lab-stations/{id}` | Update a station's status | ResearchOpsAdmin |
| POST | `/playtests/sessions` | Schedule a playtest session | Researcher |
| GET | `/playtests/sessions` | List sessions | ResearchOpsAdmin, Researcher, Moderator, Participant, IncentiveOfficer |
| GET | `/playtests/sessions/{id}` | Fetch one session | ResearchOpsAdmin, Researcher, Moderator, Participant, IncentiveOfficer |
| POST | `/playtests/sessions/{id}/assign-moderator` | Assign or replace the session's moderator | Researcher |
| PATCH | `/playtests/sessions/{id}/reschedule` | Move the session window (OCC-guarded) | Researcher |
| POST | `/playtests/sessions/{id}/start` | Start a scheduled session | Moderator |
| POST | `/playtests/sessions/{id}/complete` | Complete an in-progress session | Moderator |
| POST | `/playtests/sessions/{id}/cancel` | Cancel a scheduled session | Researcher, ResearchOpsAdmin |
| POST | `/playtests/session-bookings` | Book a session seat | Participant |
| GET | `/playtests/session-bookings` | List bookings | ResearchOpsAdmin, Researcher, Moderator, Participant |
| GET | `/playtests/session-bookings/{id}` | Fetch one booking | ResearchOpsAdmin, Researcher, Moderator, Participant |
| POST | `/playtests/session-bookings/{id}/cancel` | Cancel a booking | Participant, ResearchOpsAdmin |
| POST | `/playtests/session-bookings/{id}/mark-attended` | Mark a booking attended | Moderator |
| POST | `/playtests/session-bookings/{id}/mark-no-show` | Mark a booking as a no-show | Moderator |
| POST | `/playtests/survey-instruments` | Create a survey instrument | Researcher |
| GET | `/playtests/survey-instruments` | List survey instruments | ResearchOpsAdmin, Researcher, Participant |
| GET | `/playtests/survey-instruments/{id}` | Fetch one instrument | ResearchOpsAdmin, Researcher, Participant |
| POST | `/playtests/survey-instruments/{id}/publish` | Publish an instrument | Researcher |
| POST | `/playtests/survey-instruments/{id}/retire` | Retire an instrument | Researcher |
| POST | `/playtests/survey-responses` | Create a draft survey response | Participant |
| GET | `/playtests/survey-responses` | List survey responses | ResearchOpsAdmin, Researcher, Participant |
| GET | `/playtests/survey-responses/{id}` | Fetch one response | ResearchOpsAdmin, Researcher, Participant |
| POST | `/playtests/survey-responses/{id}/submit` | Submit a draft response | Participant |
| POST | `/playtests/feedback-tickets` | File a feedback ticket | Moderator, Researcher |
| GET | `/playtests/feedback-tickets` | List feedback tickets | ResearchOpsAdmin, Researcher, Moderator |
| GET | `/playtests/feedback-tickets/{id}` | Fetch one feedback ticket | ResearchOpsAdmin, Researcher, Moderator |
| POST | `/playtests/feedback-tickets/{id}/triage` | Triage a ticket | Researcher |
| POST | `/playtests/feedback-tickets/{id}/request-info` | Send a ticket back for more information | Researcher |
| POST | `/playtests/feedback-tickets/{id}/route` | Route a ticket to a backlog | Researcher |
| POST | `/playtests/feedback-tickets/{id}/resolve` | Resolve a routed ticket | Researcher |
| POST | `/playtests/feedback-tickets/{id}/mark-wont-fix` | Mark a routed ticket as won't-fix | Researcher |
| POST | `/playtests/incentive-payouts` | Draft an incentive payout | IncentiveOfficer |
| GET | `/playtests/incentive-payouts` | List incentive payouts | ResearchOpsAdmin, IncentiveOfficer |
| GET | `/playtests/incentive-payouts/{id}` | Fetch one payout | ResearchOpsAdmin, IncentiveOfficer |
| POST | `/playtests/incentive-payouts/{id}/submit` | Submit a payout for approval | IncentiveOfficer |
| POST | `/playtests/incentive-payouts/{id}/approve` | Approve a payout | IncentiveOfficer |
| POST | `/playtests/incentive-payouts/{id}/reject` | Reject a payout | IncentiveOfficer |
| POST | `/playtests/incentive-payouts/{id}/resubmit` | Resubmit a rejected payout | IncentiveOfficer |
| POST | `/playtests/incentive-payouts/{id}/issue` | Issue an approved payout | IncentiveOfficer |
| POST | `/playtests/breach-cases` | Report a confidentiality breach | Moderator, Researcher |
| GET | `/playtests/breach-cases` | List breach cases | ResearchOpsAdmin, LegalCounsel, Researcher |
| GET | `/playtests/breach-cases/{id}` | Fetch one breach case | ResearchOpsAdmin, LegalCounsel, Researcher |
| POST | `/playtests/breach-cases/{id}/open-investigation` | Open an investigation into a report | LegalCounsel |
| POST | `/playtests/breach-cases/{id}/substantiate` | Substantiate an investigated case | LegalCounsel |
| POST | `/playtests/breach-cases/{id}/dismiss` | Dismiss an investigated case | LegalCounsel |
| POST | `/playtests/breach-cases/{id}/sanction` | Sanction a substantiated case | LegalCounsel |
| GET | `/playtests/exposure-records` | List exposure journal events | ResearchOpsAdmin, Researcher, LegalCounsel |
| GET | `/playtests/exposure-records/{id}` | Fetch one exposure record | ResearchOpsAdmin, Researcher, LegalCounsel |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of Sections 2 and 3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STUDY_NOT_RECRUITING` | 409 Conflict |
| `ERR_STUDY_NOT_CLOSED` | 409 Conflict |
| `ERR_PARTICIPANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_COHORT_FULL` | 422 Unprocessable Entity |
| `ERR_FIT_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_NDA_NOT_PUBLISHED` | 409 Conflict |
| `ERR_NDA_NOT_SIGNED` | 422 Unprocessable Entity |
| `ERR_SIGNATURE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BUILD_NOT_RELEASED` | 409 Conflict |
| `ERR_KEY_QUOTA_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_KEY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_STATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STATION_CONFLICT` | 409 Conflict |
| `ERR_MODERATOR_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MODERATOR_CONFLICT` | 409 Conflict |
| `ERR_PARTICIPANT_CONFLICT` | 409 Conflict |
| `ERR_SESSION_NOT_BOOKABLE` | 409 Conflict |
| `ERR_SESSION_NOT_IN_WINDOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BOOKING` | 409 Conflict |
| `ERR_NOT_ENROLLED` | 422 Unprocessable Entity |
| `ERR_ATTENDANCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_UNKNOWN_QUESTION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESPONSE` | 409 Conflict |
| `ERR_INSTRUMENT_ALREADY_PUBLISHED` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OPEN_BREACH_EXISTS` | 409 Conflict |
| `ERR_REPORTER_CANNOT_ADJUDICATE` | 403 Forbidden |
| `ERR_NO_COMPENSABLE_ACTIVITY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PAYOUT` | 409 Conflict |
