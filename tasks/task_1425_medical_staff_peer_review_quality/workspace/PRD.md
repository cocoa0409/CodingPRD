# Medical Staff Peer Review API — Product Requirements Document

## 1. Introduction

Hospitals are obligated to review the quality of care delivered by their medical staff, and the peer review process that discharges this obligation is among the most legally sensitive workflows in the institution: committee deliberations are privileged, reviewer independence must be demonstrably free of conflicts of interest, and the provider under review retains procedural rights to notification and response. This document specifies the Medical Staff Peer Review API, the system of record for a hospital's peer review committee. It governs the complete lifecycle of a quality review case — referral intake and screening, conflict-checked reviewer assignment, structured scoring of care appropriateness and opportunities for improvement, committee deliberation and final rating, provider notification and response, closure, and escalation to an external review body.

Beyond the single-case lifecycle, the system carries the longitudinal dimension of quality oversight: trend metrics computed across a provider's resolved cases, automatic triggers that open a focused review when thresholds are breached, and focus groups whose membership feeds a quorum rule back into deliberation. Four roles share the work under strict segregation of duties, every deadline and cooldown is evaluated against a controllable logical clock rather than wall-clock time, and the writes that multiple actors can contend over are guarded by optimistic concurrency. All endpoints are mounted under the `/peer-review` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The system recognizes exactly four roles: `QualityDirector`, `PeerReviewCoordinator`, `CommitteeMember`, and `Provider`. A request that is missing either header, or whose role value is not one of these four, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting CommitteeMember record; ownership checks on any resource that references a committee member — an assignment's `reviewer_id`, a conflict declaration's `member_id`, a note's `author_member_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting Provider; ownership checks on any resource that references a provider compare the resource's foreign-key field — most importantly a case's `subject_provider_id` — to `X-User-ID`. When `X-User-Role` is `QualityDirector` or `PeerReviewCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

Role mandates are deliberately non-overlapping. The `QualityDirector` owns the provider roster, committee seating and activation, screening decisions, external referrals, focused reviews, focus groups, and the logical clock. The `PeerReviewCoordinator` runs intake — referring cases and assigning reviewers — but cannot screen, score, finalize, or refer externally. A `CommitteeMember` reviews cases, declares and rescinds their own conflicts, and writes privileged notes; members whose `member_role` is `CHAIR` additionally finalize deliberations and drive the response loop. A `Provider` may read only their own cases, notifications, and responses, and may submit the single response to their own notified case; all committee-privileged content is denied to them. Even when a role is authorized for an endpoint, the specific target resource may be out of scope for the acting identity, in which case the request is rejected with `ERR_FORBIDDEN_RESOURCE`; the three chair-gated committee actions instead reject non-chair actors with `ERR_CHAIR_REQUIRED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. One exception exists: the assignment list of a case is ordered by `sequence` ascending.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Version Semantics

Every primary resource — Provider, CommitteeMember, ReviewCase, ReviewAssignment, Deliberation, FocusedReview, and FocusGroup — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Six record types are immutable ledger-style entries and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them: ConflictDeclaration, CaseNote, ProviderNotification, ProviderResponse, ExternalReferral, and FocusGroupMember.

Version semantics extend across cascades. Any single write that mutates several records — a score submission that also advances the case, a deactivation that waives pending assignments, a case resolution that stamps focus group membership — increments the `version` and refreshes the `updated_at` of every record it touches, the housing case included. All such cascade effects commit atomically with the triggering write; the consistency model is immediate, with no deferred reconciliation.

### 2.5. The Logical Clock

The server maintains a logical clock, and every timestamp it writes — `created_at`, `submitted_at`, `sent_at`, `opened_at`, `finalized_at`, `closed_at`, and their peers — is read from that clock, as are all deadline, window, and cooldown evaluations. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any administrative call it remains at this default and never falls back to wall-clock time. A `QualityDirector`-only, test-driving capability sets the clock: it accepts a `to_iso8601` value (an ISO 8601 UTC instant) and returns the new `current_utc`. All comparisons of instants — response deadlines, referral cooldowns, trend windows — are performed at second precision.

### 2.6. Scoring Precision and Rounding Discipline

Reviewer scores are integers from 1 to 5; no rounding ever applies to them. Derived trend averages are a different matter: every average the system reports is rounded to exactly 2 decimal places using the round-half-up method, and the rounding order is pinned — each per-case mean is rounded first, and the window-level average is then taken over the already-rounded per-case means (see §3.8). Threshold decisions in the focused-review trigger compare against these rounded values, never against raw sums. Averaging raw score sums first is a rejected interpretation and must not be implemented.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the case they belong to: creating a reviewer assignment on a case (`POST /peer-review/cases/{id}/assignments`) and submitting scores for an assignment (`POST /peer-review/assignments/{id}/submit`). Each requires a non-optional `expected_case_version` field in the request body, carrying the case's `version` as the client last observed it. If the case's current `version` has advanced past that value — for instance because another writer has already added a reviewer (legitimately consuming one of the three assignment slots) or another reviewer's submission has already advanced the case's status — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a case state it has not observed. Endpoints not named here do not accept a version field.

### 2.8. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline. The stages below are evaluated in order, and a failure at an earlier stage masks every later check — the reported error is always the first one that fires.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the four declared roles; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The acting role appears in the endpoint's authorized role list; otherwise `ERR_UNAUTHORIZED_ROLE` (403).
3. **Existence.** Identifiers in the path resolve to existing rows, validated left to right; then foreign-key identifiers in the body (`reviewer_id`, `provider_id`, `member_id`, `subject_provider_id`), again left to right. The 404 variant names the resource that failed to resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`, `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`.
4. **Ownership and scope.** A `Provider` may touch only cases whose `subject_provider_id` equals their `X-User-ID`; a `CommitteeMember` may declare or rescind only their own conflicts and may submit or revise only their own assignments; chair-gated actions require the acting member's `member_role` to be `CHAIR`. Violations surface as `ERR_FORBIDDEN_RESOURCE` (403), with the `ERR_CHAIR_REQUIRED` variant on the three chair-only actions.
5. **State legality.** The target entity must be in a state from which the requested transition exists; otherwise `ERR_INVALID_STATE` (409). When the target case is already in a terminal state (`SCREENED_OUT`, `CLOSED`, or `EXTERNAL_REVIEW`), the terminal variant `ERR_ALREADY_TERMINAL` (409) is returned instead.
6. **Optimistic concurrency.** Where §2.7 applies, `expected_case_version` must equal the case's current `version`; otherwise `ERR_STALE_VERSION` (412).
7. **Conflict-avoidance chain.** Reviewer assignment enforces three checks in this order: the reviewer is `ACTIVE` (`ERR_REVIEWER_INACTIVE`), the reviewer is not the subject of the case (`ERR_REVIEWER_IS_SUBJECT`), and no conflict declaration links the reviewer to the subject (`ERR_REVIEWER_CONFLICT_DECLARED`).
8. **Input shape and per-resource constraints.** Required fields present, enum values valid, datetimes well-formed, strings non-empty (`ERR_VALIDATION`, 400); the specialized constraints `ERR_SCREEN_OUT_REASON_REQUIRED` (400), `ERR_SCORE_OUT_OF_RANGE` (422), `ERR_REVIEWER_ALREADY_ASSIGNED` (422), `ERR_CASE_FULLY_ASSIGNED` (409), `ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER` (409), `ERR_CONFLICT_ALREADY_DECLARED` (409), `ERR_DUPLICATE_FOCUS_MEMBER` (409), and `ERR_FOCUS_PANEL_QUORUM_NOT_MET` (409), each triggered as described in §3.
9. **Temporal rules.** The referral cooldown (`ERR_DUPLICATE_REFERRAL_WINDOW`, 409), the response deadline (`ERR_RESPONSE_WINDOW_CLOSED`, 422), and the close-no-response timing rule (`ERR_RESPONSE_WINDOW_OPEN`, 409).
10. **Aggregate uniqueness.** A manual focused review cannot open while the provider already has an `ACTIVE` one (`ERR_FOCUSED_REVIEW_ALREADY_ACTIVE`, 409).

### 2.9. Committee Privilege and Provider Scope

Peer review proceedings are privileged, and the API enforces that privilege structurally. Committee notes, deliberations, reviewer assignments, trend metrics, and focused-review oversight are committee-facing surfaces: the `Provider` role is denied all of them. A provider's read access is confined to their own record, their own cases, and the notification and response attached to one of their own cases; listing cases through a provider other than their own is rejected with `ERR_FORBIDDEN_RESOURCE`. Case notes in particular are never exposed to the `Provider` role under any circumstances — they are the committee's privileged work product from the moment they are written.

### 2.10. Nested Resource Retrieval

Requests that target nested resources are validated hierarchically. When a path contains more than one identifier, the server resolves identifiers in left-to-right order and rejects the request immediately with the 404 variant that corresponds to the first identifier that does not resolve (see stage 3 of §2.8). Body-supplied foreign keys are checked only after every path identifier has resolved. This ordering guarantees that a request aimed at a child of a non-existent parent reports the missing parent, never the child.

## 3. Business Logic & Workflows

### 3.1. Rosters, Committee Seats, and Conflicts of Interest

Everything begins with the medical staff roster. A `QualityDirector` registers each provider with a non-empty `full_name` and a `specialty` drawn from exactly eight values: `INTERNAL_MEDICINE`, `SURGERY`, `CARDIOLOGY`, `PEDIATRICS`, `EMERGENCY_MEDICINE`, `ANESTHESIOLOGY`, `OBSTETRICS`, and `PSYCHIATRY`. The provider list may be filtered by `specialty`.

From that roster, the `QualityDirector` seats committee members by supplying a `provider_id` and a `member_role` of either `MEMBER` or `CHAIR`. The new member's `specialty` is denormalized from the referenced provider's record at creation time — any client-supplied `specialty` is ignored — and the member starts `ACTIVE` with a `reliability_completed_count` of 0. That counter records how many of the member's assignments have reached `SUBMITTED`; it is incremented on submission and never decremented. At most one `ACTIVE` membership may exist per provider: seating or reactivating a member while another `ACTIVE` membership for the same provider exists is rejected with `ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER`. The member list can be filtered by `provider_id`, `status`, `member_role`, or `specialty`.

Deactivation moves a member from `ACTIVE` to `INACTIVE` and ripples through their workload: every `PENDING` assignment held by that member flips to `WAIVED`, and each housing case has its `version` incremented and `updated_at` refreshed without any change to the case's own status. A `WAIVED` assignment frees its slot toward the per-case cap of three non-`WAIVED` assignments, so the coordinator may seat a replacement reviewer. The member's `SUBMITTED` assignments and `reliability_completed_count` are untouched by deactivation. Reactivation returns an `INACTIVE` member to `ACTIVE` — subject to the one-active-membership rule above — but performs no retroactive un-waiver: previously `WAIVED` assignments stay `WAIVED`. An `INACTIVE` member is excluded from reviewer candidacy and cannot be assigned to anything.

Conflicts of interest are self-declared. A member declares a conflict by naming a `provider_id` and a `conflict_type` — one of `PRIOR_TREATING`, `FAMILY`, `FINANCIAL`, `SUPERVISORY`, or `OTHER` — and may do so only for themselves: the acting member's identity must equal the member in the path, otherwise `ERR_FORBIDDEN_RESOURCE`. Declaring the same (`member_id`, `provider_id`) pair twice is rejected with `ERR_CONFLICT_ALREADY_DECLARED`. Such declarations carry a `source` of `SELF_DECLARED`; the second source value, `AUTO_CASE_RESOLVED`, is written only by the case-resolution cascade described in §3.7. Rescinding a declaration is a hard delete, again restricted to the declaring member, and it restores the member's eligibility for future assignments against that provider's cases.

### 3.2. Case Intake, Screening, and the Referral Cooldown

A `PeerReviewCoordinator` opens the lifecycle by referring a provider for review, supplying the `subject_provider_id`, a `referral_source` of `INCIDENT_REPORT`, `PATIENT_COMPLAINT`, `STAFF_REFERRAL`, `INSURER_INQUIRY`, or `OTHER`, the `referred_at` timestamp at which the referring party logged the concern (ISO 8601 UTC), and a non-empty free-text `description`. The case is born in `REFERRED` status.

A cooldown guards against referral churn. Before accepting a new referral, the server locates the subject provider's most recent `SCREENED_OUT` case, ranked by its `screened_out_at`. If that case exists and its `screened_out_at` is strictly more recent than the instant thirty days before the current logical time, the referral is rejected with `ERR_DUPLICATE_REFERRAL_WINDOW` (409). A referral made exactly thirty days after the screen-out — `screened_out_at` equal to the current logical time minus thirty days, to the second — is allowed.

Screening is the `QualityDirector`'s gate, exercised through a `decision` on a `REFERRED` case. A `decision` of `SCREEN_IN` moves the case to `SCREENED_IN`. A `decision` of `SCREEN_OUT` requires a `screened_out_reason` of `DUPLICATE`, `FRIVOLOUS`, `OUT_OF_SCOPE`, or `OTHER` — omitting it is rejected with `ERR_SCREEN_OUT_REASON_REQUIRED` — and moves the case to `SCREENED_OUT`, stamping `screened_out_at` with the current logical time and thereby arming the cooldown described above. Both screening outcomes increment the case's `version` and refresh `updated_at`; both are legal only from `REFERRED`. The `screened_out_reason` and `screened_out_at` fields remain null on any case that was never screened out. `SCREENED_OUT` is one of the case's three terminal states, alongside `CLOSED` and `EXTERNAL_REVIEW`, and any further action attempted on a terminal case is rejected with `ERR_ALREADY_TERMINAL`.

### 3.3. Reviewer Eligibility, Ranking, and Assignment

Once a case is screened in, the coordinator needs reviewers. Querying the ranked candidate list for a case runs the eligibility filter over every committee member: a candidate must be `ACTIVE`, must not be the subject of the case (their `provider_id` must differ from the case's `subject_provider_id`), must hold no conflict declaration against the subject provider, and must not already hold a non-`WAIVED` assignment on the case. Eligible candidates are ranked with same-specialty members first — those whose `specialty` equals the subject provider's specialty — then by `reliability_completed_count` with higher counts first, then by member `created_at` with the earliest first; the member `id` is never used as a tie-break. An empty candidate pool is not an error: the query returns 200 with an empty list. This query is available to the `PeerReviewCoordinator` and the `QualityDirector`, and it paginates like any other list.

Assigning a reviewer is the coordinator's write, and it is one of the two concurrency-guarded operations in §2.7: the request must carry `reviewer_id` and a non-optional `expected_case_version` matching the case's current `version`, else `ERR_STALE_VERSION` (412). The case must be in `SCREENED_IN`, `ASSIGNED`, or `IN_REVIEW`. The conflict-avoidance chain of §2.8 stage 7 then fires in its pinned order — `ERR_REVIEWER_INACTIVE` before `ERR_REVIEWER_IS_SUBJECT` before `ERR_REVIEWER_CONFLICT_DECLARED` — followed by the remaining constraints: a reviewer who already holds a non-`WAIVED` assignment on the case is rejected with `ERR_REVIEWER_ALREADY_ASSIGNED`, and a case that already has three non-`WAIVED` assignments is rejected with `ERR_CASE_FULLY_ASSIGNED`.

A created assignment starts `PENDING` and records the `case_id` of the case it serves. Its `sequence` is the count of all existing assignments on that case — of any status, `WAIVED` included — plus one, and sequence numbers are never reused, so a waived slot still consumes its ordinal. The assignment write increments the case's `version`, and the first assignment created on a `SCREENED_IN` case flips that case to `ASSIGNED`. The assignment list of a case is ordered by `sequence` ascending and may be filtered by `status`.

### 3.4. Score Submission and the Road to Deliberation

Reviewing is personal: only the assigned member may submit an assignment, so the acting member's identity must equal the assignment's `reviewer_id`, otherwise `ERR_FORBIDDEN_RESOURCE`. The submission carries a `care_appropriateness_score` — an integer from 1 (unacceptable) to 5 (fully appropriate) — and an optional `ofi_score`, an integer from 1 to 5 where 5 marks the most severe opportunity for improvement; the `ofi_score` is simply absent when the reviewer identifies no opportunity. A score present but outside the 1-to-5 range is rejected with `ERR_SCORE_OUT_OF_RANGE` (422). Submission is the second concurrency-guarded write of §2.7 and requires `expected_case_version` to match the case's current `version`. The assignment itself must still be `PENDING`, and the case must be in `ASSIGNED` or `IN_REVIEW`; otherwise the submission is rejected with `ERR_INVALID_STATE`, or with `ERR_ALREADY_TERMINAL` when the case has already reached a terminal state.

A successful submission does five things at once. The assignment moves to `SUBMITTED`, its `submitted_at` is stamped with the current logical time (first submission only — revision never touches it), and its `version` increments. The reviewing member's `reliability_completed_count` increments by one and the member's `version` increments. The case's `version` increments. If this is the first submission on the case, the case moves from `ASSIGNED` to `IN_REVIEW`. And if this submission makes three distinct `SUBMITTED` assignments on the case, the case moves from `IN_REVIEW` to `DELIBERATION` and the Deliberation auto-opens: exactly one Deliberation exists per case, created with status `OPEN`, `opened_at` stamped with the current logical time, and `rating` still null.

### 3.5. Deliberation, Committee Notes, and the Final Rating

Throughout the working life of a case — while it is in `ASSIGNED`, `IN_REVIEW`, `DELIBERATION`, `NOTIFIED`, `RESPONDED`, or `COMMITTEE_REVIEW` — any committee member may attach privileged notes. A note carries a non-empty `body` and an optional `note_type` of `GENERAL` (the default when omitted) or `DELIBERATION`; its `author_member_id` is stamped from the acting member's `X-User-ID`, never from the request body. Attempts to note a case outside the listed window are rejected under the standard state checks, with the terminal variant once the case is closed. Per §2.9, notes are never visible to the `Provider` role.

The committee's final rating is computed by severity-precedence aggregation over exactly the case's three `SUBMITTED` assignments — `PENDING` and `WAIVED` rows are excluded, and deliberation cannot open with fewer than three. The rule evaluates four bands in order, and the first match wins. If at least one of the three care appropriateness scores is 1, the rating is `UNACCEPTABLE`. Otherwise, if at least two of the three care scores are 2 or lower, or at least two of the submitted (non-null) OFI scores are 4 or higher, the rating is `MAJOR_OFI`. Otherwise, if exactly one care score is 2 or lower, or exactly one submitted OFI score is 4 or higher, or at least one OFI score was submitted at all, the rating is `MINOR_OFI`. Otherwise the rating is `APPROPRIATE`. Scoring is integer arithmetic with no rounding. This severity-precedence rule is pinned: the committee considered and rejected a majority-vote banding alternative, under which a case scored 1, 5, 5 with no OFI scores would have come out `APPROPRIATE` — under the pinned rule that combination is always `UNACCEPTABLE`.

Finalizing deliberation is a `CHAIR`-only action on a case in `DELIBERATION`; any other member attempting it is rejected with `ERR_CHAIR_REQUIRED`. One quorum rule can stand in the way: when the subject provider has an `ACTIVE` focused review, at least two of the case's three `SUBMITTED` reviewers must be members of at least one focus group belonging to that focused review, otherwise the finalization is rejected with `ERR_FOCUS_PANEL_QUORUM_NOT_MET` (409). On success the aggregation above runs, the Deliberation's `rating` is set, its status becomes `FINALIZED`, its `finalized_at` is stamped with the current logical time, its `version` increments, and the chair's optional `rationale_note` is stored. The case then moves to `NOTIFIED` with its `version` incremented, and the notification cascade creates the case's single ProviderNotification — exactly one per case — with `sent_at` stamped at the current logical time and `response_deadline` computed as exactly fourteen days after `sent_at`, to the second.

### 3.6. The Provider Response Loop and Case Closure

While a case is `NOTIFIED`, the subject provider may answer the committee's rating by submitting a non-empty `response_text`. Only the subject may respond — the acting provider's identity must equal the case's `subject_provider_id`, otherwise `ERR_FORBIDDEN_RESOURCE` — and only within the response window: the response is accepted while the current logical time is at or before the notification's `response_deadline`, inclusive, and rejected with `ERR_RESPONSE_WINDOW_CLOSED` (422) once the deadline has passed. At most one response exists per case; a successful submission creates it with `submitted_at` stamped and moves the case to `RESPONDED`, incrementing the case's `version`.

From `RESPONDED`, a `CHAIR` member marks the response as committee-reviewed (non-chairs draw `ERR_CHAIR_REQUIRED`), moving the case to `COMMITTEE_REVIEW` and opening the score-revision window. While the case sits in `COMMITTEE_REVIEW`, the original reviewer of any `SUBMITTED` assignment on the case may revise their scores, supplying a fresh `care_appropriateness_score` and optionally a fresh `ofi_score` under the same 1-to-5 ranges (`ERR_SCORE_OUT_OF_RANGE` on violation). Revision overwrites both scores, increments the assignment's `version`, leaves `submitted_at` untouched, increments the case's `version`, and does not increment `reliability_completed_count` — a revision is not a new submission. Revising is rejected with `ERR_INVALID_STATE` in any other case state, and revising another member's assignment draws `ERR_FORBIDDEN_RESOURCE`.

Closing the loop is again the chair's work. Finalizing after response re-runs the severity-precedence aggregation over the case's current three `SUBMITTED` assignments, picking up any revised scores; the Deliberation's `rating` is updated, the chair's optional `reconsideration_note` is stored, `reconsidered_at` is stamped with the current logical time, and the Deliberation's `version` increments. The case then moves to `CLOSED` with `closure_basis` set to `POST_RESPONSE` and `closed_at` stamped, its `version` incrementing — and the resolution cascade of §3.7 runs.

There is a second road to `CLOSED` for providers who stay silent. Once the current logical time is strictly after `response_deadline`, the `QualityDirector` may close a `NOTIFIED` case directly; attempting this at or before the deadline is rejected with `ERR_RESPONSE_WINDOW_OPEN` (409). The two rules interlock at the boundary: at the exact deadline instant, a provider response is still accepted and close-no-response is still rejected. Closing this way sets `closure_basis` to `NO_RESPONSE`, stamps `closed_at`, increments the case's `version`, and runs the same resolution cascade as a post-response closure. The `closure_basis` and `closed_at` fields remain null on any case that has not reached `CLOSED`.

### 3.7. External Referral and the Resolution Cascade

Some cases belong before an external review body. From `DELIBERATION`, the `QualityDirector` may refer the case externally by supplying a non-empty `reason`; the same referral is available from `COMMITTEE_REVIEW`, after the response loop has produced a finalized rating. Either way, the referral creates the case's ExternalReferral record — at most one per case — with `referred_at` stamped at the current logical time, moves the case to `EXTERNAL_REVIEW`, increments its `version`, and runs the resolution cascade. The two branches differ in exactly one respect: a case referred from `DELIBERATION` has a Deliberation whose `rating` is still null, so it is excluded from the rated set of the trend metrics, whereas a case referred from `COMMITTEE_REVIEW` carries a `FINALIZED` rating and enters the rated set, keyed on the Deliberation's `finalized_at`.

The resolution cascade fires on every transition into `CLOSED` or `EXTERNAL_REVIEW`, regardless of which door the case came through, and it has four links. First, the subject provider's trend metrics are recomputed as defined in §3.8. Second, the focused-review trigger is evaluated against those freshly computed values; if any predicate fires and the provider has no `ACTIVE` focused review, an `AUTOMATIC` focused review is created with its snapshot. Third, for each `SUBMITTED` assignment on the resolved case, a conflict declaration is created linking the assignment's reviewer (`member_id`) to the subject provider (`provider_id`) with `source` set to `AUTO_CASE_RESOLVED` — unless an identical (`member_id`, `provider_id`) declaration already exists, in which case none is added. Fourth, focus group stamping: if the subject provider has an `ACTIVE` focused review with at least one focus group, the case's `focus_group_id` is stamped with the group that has the fewest cases already attached to it, ties broken in favor of the group with the earliest `created_at`; when no such review or no such group exists, `focus_group_id` stays null. Cases can be listed with filters on `status`, `subject_provider_id`, and `focus_group_id`, which is how a focus group's stamped case list is assembled.

### 3.8. Trend Tracking, Focused Reviews, and Focus Groups

Provider trend metrics are recomputed whenever one of the provider's cases enters `CLOSED` or `EXTERNAL_REVIEW`, and again on every read of the provider's quality trend — a read-only query available to the `QualityDirector` and `PeerReviewCoordinator` that never creates anything. The rated set behind the metrics comprises exactly those of the provider's cases that are in `CLOSED` or `EXTERNAL_REVIEW`, hold a `FINALIZED` Deliberation with a non-null `rating`, and whose `finalized_at` falls inside the half-open window that begins exactly 365 days before the current logical time (exclusive) and ends at the current logical time (inclusive). Screened-out cases, cases without a finalized rating, and cases finalized outside the window are all excluded.

From that set, four numbers are produced. Each rated case first yields a per-case average: the mean of its three `SUBMITTED` care appropriateness scores, rounded half-up to two decimal places. The `rated_case_count` is the size of the rated set. The `avg_care_appropriateness` is the mean of those per-case averages, again rounded half-up to two decimal places — and it is null when `rated_case_count` is zero. Following §2.6's pinned rounding order, the per-case means are rounded before they are averaged; to see why the order matters, consider two rated cases scored 3, 3, 3 and 3, 3, 2 — the pinned order reports 2.84, while averaging the six raw scores directly would report 2.83, and only the former is correct. The `major_ofi_case_count` counts rated cases whose rating is `MAJOR_OFI`, and the `unacceptable_case_count` counts those rated `UNACCEPTABLE`. The trend response carries `provider_id`, `window_start`, `window_end`, `rated_case_count`, `avg_care_appropriateness`, `major_ofi_case_count`, and `unacceptable_case_count`, plus two trigger-facing fields: `focused_review_would_trigger` and `active_focused_review_id`.

Immediately after every resolution-driven recompute (never after the read-only query), the focused-review trigger evaluates four predicates against the freshly computed, already-rounded values, and fires when any one holds: `rated_case_count` is at least 3; `avg_care_appropriateness` is below 3.0, evaluated only when `rated_case_count` is greater than zero; `major_ofi_case_count` is at least 1; or `unacceptable_case_count` is at least 1. When the trigger fires and the provider has no `ACTIVE` focused review, the server creates one with `trigger_type` `AUTOMATIC`, status `ACTIVE`, `opened_at` stamped, and a `trigger_snapshot` object capturing the evidence: `window_start`, `window_end`, `rated_case_count`, `avg_care_appropriateness`, `major_ofi_case_count`, and `unacceptable_case_count`. When an `ACTIVE` focused review already exists, nothing is created.

A `QualityDirector` may also open a focused review manually, supplying the `provider_id` and an optional free-text `basis`; manual openings carry `trigger_type` `MANUAL` and a null `trigger_snapshot`, just as automatic ones carry a null `basis`. At most one `ACTIVE` focused review may exist per provider at any time — a manual open while one is active is rejected with `ERR_FOCUSED_REVIEW_ALREADY_ACTIVE` — with half-open interval semantics: a new review may open at the exact instant the prior one closed. Focused reviews can be listed with filters on `provider_id` and `status`. Closing one requires the director's `resolution_note` — omitting it is rejected with `ERR_VALIDATION` — and stamps `closed_at`, sets the status to `CLOSED`, and increments the version. Existing focus groups survive closure, but creating new groups or adding members under a `CLOSED` review is rejected with `ERR_INVALID_STATE`.

Focus groups are the working panels of a focused review. The `QualityDirector` creates one under an `ACTIVE` review by supplying a non-empty `name`; the group records the `focus_id` of the review it serves. Members are added by `member_id` and must be `ACTIVE` at add time (`ERR_REVIEWER_INACTIVE` otherwise); at most one membership row exists per (`focus_group_id`, `member_id`) pair, and a duplicate addition is rejected with `ERR_DUPLICATE_FOCUS_MEMBER`. Removing a member deletes the membership row outright, and a removal naming a pair with no membership row is rejected with `ERR_MEMBERSHIP_NOT_FOUND`. Group membership is not ornamental: it is the pool from which the deliberation quorum of §3.5 counts its two required reviewers whenever the subject provider is under an `ACTIVE` focused review.

## 4. Endpoint Definitions

Operations that create a new resource — whether a stand-alone record or a new entry in a collection — return `201 Created`. Operations that read, modify, or transition an existing resource return `200 OK`. The two deletion endpoints return `204 No Content`. Request bodies, response payloads, and side effects are specified per workflow in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/peer-review/providers` | Register a provider on the medical staff roster | QualityDirector |
| GET | `/peer-review/providers` | List providers | QualityDirector, PeerReviewCoordinator, CommitteeMember, Provider |
| GET | `/peer-review/providers/{id}` | Get one provider | QualityDirector, PeerReviewCoordinator, CommitteeMember, Provider |
| GET | `/peer-review/providers/{id}/cases` | List cases for a subject provider (Provider role: own id only) | QualityDirector, PeerReviewCoordinator, CommitteeMember, Provider |
| GET | `/peer-review/providers/{id}/conflict-declarations` | List conflict declarations naming this provider | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/providers/{id}/focused-reviews` | List focused reviews for a provider | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/providers/{id}/quality-trend` | Computed trailing-365-day trend metrics and trigger flags; read-only | QualityDirector, PeerReviewCoordinator |
| POST | `/peer-review/committee-members` | Seat a provider on the committee | QualityDirector |
| GET | `/peer-review/committee-members` | List committee members | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/committee-members/{id}` | Get one committee member | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/committee-members/{id}/deactivate` | Deactivate a member; their pending assignments are waived | QualityDirector |
| POST | `/peer-review/committee-members/{id}/activate` | Reactivate an inactive member | QualityDirector |
| POST | `/peer-review/committee-members/{id}/conflict-declarations` | Member self-declares a conflict with a provider | CommitteeMember |
| GET | `/peer-review/committee-members/{id}/conflict-declarations` | List a member's conflict declarations | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| DELETE | `/peer-review/conflict-declarations/{id}` | Rescind a conflict declaration (hard delete) | CommitteeMember |
| GET | `/peer-review/committee-members/{id}/assignments` | List a member's review assignments | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/committee-members/{id}/notes` | List case notes authored by a member | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/committee-members/{id}/focus-group-memberships` | List a member's focus group memberships | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/cases` | Refer a provider for peer review | PeerReviewCoordinator |
| GET | `/peer-review/cases` | List review cases | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/cases/{id}` | Get one case (Provider role: own cases only) | QualityDirector, PeerReviewCoordinator, CommitteeMember, Provider |
| POST | `/peer-review/cases/{id}/screen` | Screen a referred case in or out | QualityDirector |
| GET | `/peer-review/cases/{id}/reviewer-candidates` | Ranked eligible reviewer candidates for a case | PeerReviewCoordinator, QualityDirector |
| POST | `/peer-review/cases/{id}/assignments` | Assign a reviewer to a case (OCC-guarded) | PeerReviewCoordinator |
| GET | `/peer-review/cases/{id}/assignments` | List assignments of a case, by sequence ascending | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/assignments/{id}` | Get one assignment | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/assignments/{id}/submit` | Assigned reviewer submits scores (OCC-guarded) | CommitteeMember |
| POST | `/peer-review/assignments/{id}/revise` | Original reviewer revises scores during committee review | CommitteeMember |
| POST | `/peer-review/cases/{id}/notes` | Add a privileged committee note | CommitteeMember |
| GET | `/peer-review/cases/{id}/notes` | List privileged notes of a case | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/cases/{id}/deliberation` | Get the case's deliberation (list of 0 or 1) | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/cases/{id}/finalize-deliberation` | Chair finalizes the deliberation and notifies the provider | CommitteeMember |
| GET | `/peer-review/cases/{id}/notifications` | Get the case's notification (list of 0 or 1; Provider: own cases) | QualityDirector, PeerReviewCoordinator, CommitteeMember, Provider |
| POST | `/peer-review/cases/{id}/response` | Subject provider responds to the committee rating | Provider |
| GET | `/peer-review/cases/{id}/response` | Get the case's provider response (list of 0 or 1; Provider: own cases) | QualityDirector, PeerReviewCoordinator, CommitteeMember, Provider |
| POST | `/peer-review/cases/{id}/committee-review` | Chair marks the provider response committee-reviewed | CommitteeMember |
| POST | `/peer-review/cases/{id}/finalize-after-response` | Chair closes the response loop and the case | CommitteeMember |
| POST | `/peer-review/cases/{id}/close-no-response` | Close a notified case whose response deadline has passed | QualityDirector |
| POST | `/peer-review/cases/{id}/refer-external` | Refer the case to an external review body | QualityDirector |
| GET | `/peer-review/cases/{id}/external-referrals` | List external referrals of a case (0 or 1) | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/focused-reviews` | Manually open a focused review | QualityDirector |
| GET | `/peer-review/focused-reviews` | List focused reviews | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/focused-reviews/{id}` | Get one focused review | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/focused-reviews/{id}/close` | Close an active focused review | QualityDirector |
| POST | `/peer-review/focused-reviews/{id}/focus-groups` | Create a focus group under an active focused review | QualityDirector |
| GET | `/peer-review/focused-reviews/{id}/focus-groups` | List focus groups of a focused review | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/focus-groups/{id}` | Get one focus group | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| GET | `/peer-review/focus-groups/{id}/cases` | List cases stamped into this focus group | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| POST | `/peer-review/focus-groups/{id}/members` | Add an active committee member to a focus group | QualityDirector |
| GET | `/peer-review/focus-groups/{id}/members` | List members of a focus group | QualityDirector, PeerReviewCoordinator, CommitteeMember |
| DELETE | `/peer-review/focus-groups/{id}/members/{memberId}` | Remove a member from a focus group | QualityDirector |
| POST | `/peer-review/_clock/set_current_utc` | Set the server's logical clock | QualityDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow is described; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE` | 403 Forbidden |
| `ERR_CHAIR_REQUIRED` | 403 Forbidden |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONFLICT_NOT_FOUND` | 404 Not Found |
| `ERR_FOCUSED_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_FOCUS_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_SCREEN_OUT_REASON_REQUIRED` | 400 Bad Request |
| `ERR_SCORE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REVIEWER_INACTIVE` | 422 Unprocessable Entity |
| `ERR_REVIEWER_IS_SUBJECT` | 422 Unprocessable Entity |
| `ERR_REVIEWER_CONFLICT_DECLARED` | 422 Unprocessable Entity |
| `ERR_REVIEWER_ALREADY_ASSIGNED` | 422 Unprocessable Entity |
| `ERR_CASE_FULLY_ASSIGNED` | 409 Conflict |
| `ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER` | 409 Conflict |
| `ERR_CONFLICT_ALREADY_DECLARED` | 409 Conflict |
| `ERR_DUPLICATE_FOCUS_MEMBER` | 409 Conflict |
| `ERR_FOCUS_PANEL_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_DUPLICATE_REFERRAL_WINDOW` | 409 Conflict |
| `ERR_RESPONSE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_RESPONSE_WINDOW_OPEN` | 409 Conflict |
| `ERR_FOCUSED_REVIEW_ALREADY_ACTIVE` | 409 Conflict |
