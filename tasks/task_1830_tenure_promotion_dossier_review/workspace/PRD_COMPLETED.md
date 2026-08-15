# Tenure Promotion Dossier Review API — Product Requirements Document

## 1. Introduction

Universities run tenure and promotion reviews under exacting procedural obligations: evidence must be assembled into a dossier by fixed deadlines, external letters must be solicited at arm's length and held confidential, committees at three levels must vote under quorum and pass rules that differ by committee, and every decision carries notification, appeal, and records-retention deadlines prescribed by policy. Today these workflows are tracked in email threads, shared drives, and ad-hoc spreadsheets, which makes missed deadlines, confidentiality breaches, and unverifiable vote tallies routine risks rather than exceptions.

This document specifies the Tenure & Promotion Dossier Review API operated by the university provost office. The system governs the full lifecycle of a tenure or promotion case — dossier assembly with categorized evidence, solicitation of external reviewers under a confidentiality seal, sequential department, college, and university committee review with recorded ballots and certified tallies, the provost decision and its notification window, the appeal and grievance process with a full remand cascade, and post-decision record retention through archival and purge. It additionally supports mid-tenure reviews and stop-the-clock requests that extend a candidate's mandatory review date. All time-sensitive behavior is evaluated against a server-side logical clock so that deadlines are deterministic and testable. All API endpoints described in this document are mounted under the `/api` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, cross-cutting principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes eight roles: `ProvostOfficer`, `Candidate`, `CommitteeChair`, `CommitteeVoter`, `ExternalReviewer`, `AppealOfficer`, `RecordsOfficer`, and `SystemAdmin`. A ninth pseudo-role, `Any`, covers every authenticated principal for read endpoints. A request with a missing or empty header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting Candidate; ownership checks on any resource that references a Candidate — a case, a dossier item, a clock-extension request, an appeal — compare the resource's candidate reference to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. When `X-User-Role` is `CommitteeChair` or `CommitteeVoter`, `X-User-ID` is the `id` of the acting CommitteeMember; chair-only operations verify that this member is an active chair of the round's committee, and ballot operations verify that the acting member is the vote's own member. When `X-User-Role` is `ExternalReviewer`, `X-User-ID` is the `id` of the acting ExternalReviewer, and invitation responses are accepted only from the invited reviewer. When `X-User-Role` is `ProvostOfficer`, `AppealOfficer`, `RecordsOfficer`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `created_by_user_id` on a case at creation time or as `recorded_by_user_id` on a decision at recording time — but it is never compared to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the host wall clock rather than the logical clock of §2.4.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. An empty `limit` or `offset` value is treated as omitted. Invalid pagination parameters are rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with records created within the same clock reading ordered by the sequence in which the server created them.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`.

List endpoints also accept optional filter parameters scoped to their resource, alongside `limit` and `offset`: the case list accepts `candidate_id` and `stage`; the dossier item list accepts `case_id`, `supersedes_item_id`, `status`, and `category`; the invitation list accepts `case_id`, `reviewer_id`, and `status`; the member list accepts `committee_id`; the round list accepts `case_id`, `committee_id`, `level`, and `status`; the vote list accepts `round_id` and `member_id`; and the clock-extension, mid-tenure review, decision, and appeal lists each accept `case_id` (with `status` additionally on the clock-extension and appeal lists).

### 2.4. The Logical Clock

Every deadline, window, and timestamp comparison in the system — dossier submission deadlines, invitation response deadlines, review windows, notification and appeal windows, retention expiry — is evaluated against a server-side logical clock, never against wall-clock time. When the server starts, and before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never silently falls back to the host's wall clock. A `SystemAdmin` may advance the clock through a test-driving capability that accepts an ISO 8601 instant in the `to_iso8601` field — the supplied instant is adopted as-is, with no requirement that it lie after the current reading — and the capability responds with the clock's new reading in `current_utc`. There is no way to run the system on wall-clock time while a logical clock exists.

The logical clock also drives lazy expiry of reviewer invitations. An invitation whose response deadline has passed flips to `EXPIRED` — with its `version` incremented by one — whenever a request targets that invitation by its path identifier while the clock is past the deadline, and in a batch sweep at the start of the close-solicitation operation once its stage gate has passed. Such flips persist even when the triggering request is subsequently rejected — for example when a later close-solicitation gate fails. Reads of other invitations, such as capacity scans or list retrievals, never trigger expiry of an invitation they do not target.

### 2.5. Common Resource Properties

All resources in this system — candidates, cases, dossier items, reviewers, invitations, committees, members, rounds, votes, clock-extension requests, mid-tenure reviews, decisions, and appeals — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC at whole-second precision (for example, `2026-08-01T09:30:00Z`), stamped from the logical clock when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed from the logical clock upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 upon creation and increments with every modification to the resource, serving as the basis for optimistic concurrency control.

All other system-stamped timestamp fields — such as `invited_at`, `response_deadline`, `letter_received_at`, `opened_at`, `cast_at`, `retracted_at`, `certified_at`, `decided_at`, `notification_sent_at`, `completed_at`, `filed_at`, `resolved_at`, `closed_at`, and `purged_at` — use the same whole-second logical-clock format.

Recomputations of derived fields on a resource — a case's clock fields after an extension decision, a round's tallies after a ballot mutation — are mutations of that resource and therefore refresh `updated_at` and increment `version`.

### 2.6. Case Versioning and Cascading Lifecycle Changes

The TenureCase is the aggregate root of the review, and its `version` advances by exactly one on every case lifecycle transition — dossier submission, return for revision, resumption of assembly, solicitation close, stage advancement, withdrawal, notification, closure, archival, purge, and the remand cascade. In addition, creating a dossier item against a case, creating an invitation against a case, recording the provost decision, and approving or rescinding a clock-extension request each increment the case's `version` by one, because each of those operations mutates the case's review state even when the case record itself is not the request's target.

Cascades are executed atomically with their trigger: every mutation and every secondary effect it causes — status flips on the candidate, teardown of open invitations or rounds, retraction of cast ballots, creation of the next committee round — is applied within the same request, with the response carrying the request's target resource and every secondary effect immediately visible to subsequent reads. The server performs these reconciliations automatically when the governing criteria are met, without requiring a separate client request on each affected resource.

### 2.7. Confidentiality and Segregation of Duties

External letters and committee ballots are confidential by default. When a case is opened with `waiver_signed` set to true — the default when the field is omitted — the candidate has waived access to the review record, and any attempt by a `Candidate` to read invitations, rounds, or votes linked to a case whose `waiver_signed` is true is rejected with `ERR_CONFIDENTIAL_LETTERS_SEALED`. On the list endpoints the seal applies as follows: a candidate who supplies an explicit `case_id` filter naming a waiver-signed case is rejected with `ERR_CONFIDENTIAL_LETTERS_SEALED`, while a candidate list read without a `case_id` filter succeeds and simply omits the records of waiver-signed cases from the result. When `waiver_signed` is false, candidate reads of those resources are permitted. The letter bodies stored in `letter_text` on an invitation or a round are confidential under the same seal.

Four segregation-of-duties rules are enforced as hard conflicts. The certifying chair must not hold any non-retracted ballot in the round being certified — not even a `RECUSE` ballot; a violation is rejected with `ERR_SOD_CERTIFIER_VOTED`. The officer who records the provost decision must not be the officer who opened the case: the recorder's identity, captured in `recorded_by_user_id`, must differ from the case's `created_by_user_id`, otherwise the recording is rejected with `ERR_SOD_DECISION_BY_CASE_CREATOR`. Recusal is irrevocable through the ballot-change path: neither the current nor the new ballot of a change request may be `RECUSE`, otherwise the change is rejected with `ERR_RECUSAL_IRREVERSIBLE` — a member who wishes to leave a recusal retracts the ballot and casts a fresh one. Finally, an invitation may only be created under an arm's-length certification: `is_arm_length` must be true and `declared_coauthor` must be false, otherwise creation is rejected with `ERR_ARMS_LENGTH_VIOLATION`.

### 2.8. Interval Conventions and the Tenure Clock

Several resources carry date intervals, and the validation convention depends on the interval kind. Review windows (`review_window_start` and `review_window_end`), committee terms (`term_start` and `term_end`), and stop-the-clock intervals (`interval_start` and `interval_end`) require the start to be strictly before the end. Member service windows (`service_start` and `service_end`) are more permissive: a window whose start equals its end is valid, and only a start that falls after the end is rejected. Any violation of these rules is rejected with `ERR_INVALID_INTERVAL`. Date and datetime inputs are stored verbatim as supplied; a date-only value is interpreted as midnight UTC, and a datetime value without an offset is interpreted as UTC, whenever the value participates in a comparison.

Overlap semantics likewise differ by domain. Stop-the-clock intervals are half-open — the end date itself is excluded — so two approved intervals that merely touch, where one's `interval_start` equals the other's `interval_end`, do not overlap and are both permitted. Reviewer capacity windows, by contrast, use closed semantics: two review windows that touch at a boundary date do overlap for capacity purposes. The approved stop-the-clock intervals of a case are merged into their union — overlapping or touching intervals coalesce — and the union's total length may never exceed 730 days, the policy cap of two years of stopped clock.

The tenure clock itself is anchored on the candidate's `tenure_clock_start` and runs for a probationary period of 72 months, after which the case must have been submitted for review; the exact arithmetic of the two clock policies is specified in §3.1, and the effect of approved extensions is specified in §3.3.

### 2.9. Committee Governance: Selection, Quorum, and Tally Rules

Committees exist at three levels — `DEPARTMENT`, `COLLEGE`, and `UNIVERSITY` — and each committee declares a `pass_rule` selecting one of two vote-tally variants, `STRICT_MAJORITY_OF_CAST` or `SUPERMAJORITY_OF_ENTITLED`, along with a `quorum_fraction` that defaults to 0.5 when omitted. When a case enters a committee stage, the system — never the client — selects the governing committee and creates the review round bound to it; the selection algorithm is specified in §3.5.

Quorum arithmetic is anchored on the round's eligible electorate. The number of voters required for quorum, `quorum_required`, is the committee's `quorum_fraction` multiplied by the round's `eligible_voter_count`, rounded up to a whole number. Recusals shrink the eligible electorate: each non-retracted `RECUSE` ballot reduces `eligible_voter_count` by one, and `quorum_required` is recomputed alongside it, while recusal ballots never count as votes cast. Abstentions count toward votes cast but never toward the yes-percentage denominator. Quorum is considered met only when the round's `votes_cast` is at least `quorum_required` and at least one eligible voter remains.

At most one active member of a committee may hold the chair role at any time; an attempt to seat a second active chair is rejected with `ERR_CHAIR_CONFLICT`.

### 2.10. Precision and Rounding

All rating, percentage, and score arithmetic in the system is performed using decimal arithmetic, and all rounding uses the round-half-up method. Per-category dossier ratios are carried at three decimal places; the dossier strength index, round yes-percentages, and the case recommendation score are carried at four decimal places. Stop-the-clock extensions are accounted in whole days, with interval endpoints treated at date granularity (midnight UTC). API responses represent these computed values as standard numbers, not strings.

### 2.11. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to the `version` of a parent entity the client must have read before composing the request. Creating a dossier item requires the non-optional field `expected_case_version`, carrying the client's last observed `version` of the owning case; if the case's version has advanced since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a reviewer invitation likewise requires `expected_case_version` matching the target case's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. Changing a cast ballot requires the non-optional field `expected_vote_version`, carrying the client's last observed `version` of that vote; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the vote and resubmit against the fresh version rather than silently re-applying a change. Endpoints not listed here do not take a version field.

### 2.12. Validation Order

When a request would fail several checks, the error surfaced is the one from the earliest applicable priority. Priorities are evaluated in ascending order:

1. **Header presence.** The `X-User-ID` and `X-User-Role` headers must be present and non-empty, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to every endpoint.
2. **Role permission.** The role must be permitted for the endpoint, otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). This applies to every endpoint.
3. **Path resource existence.** Resource identifiers appearing in the request path must exist, validated left to right along the path — before any ownership evaluation, which itself needs the resource. The not-found catalogue is `ERR_CANDIDATE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_DOSSIER_ITEM_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`, `ERR_CLOCK_EXTENSION_NOT_FOUND`, `ERR_MIDTERM_REVIEW_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`, and `ERR_APPEAL_NOT_FOUND` (all HTTP 404), resolved per missing identifier.
4. **Body-referenced foreign keys.** Identifiers carried in the request body — `candidate_id`, `case_id`, `reviewer_id`, `committee_id`, `round_id`, `supersedes_item_id` — must resolve to existing resources, drawing on the same not-found catalogue (HTTP 404) per missing field.
5. **Ownership and confidentiality.** Role-scoped writes verify the acting identity — the candidate acting on their own case, item, extension, or appeal; the reviewer on their own invitation; the committee member or chair on their own committee's round — otherwise `ERR_OWNERSHIP_MISMATCH` (HTTP 403). Candidate reads of invitations, rounds, and votes of a waiver-signed case fail here with `ERR_CONFIDENTIAL_LETTERS_SEALED` (HTTP 403).
6. **Case stage gates and version freshness.** The case's `stage` must permit the operation — dossier item mutations require assembly, extension requests require a pre-decision stage, invitation creation requires external review, decision recording requires provost review, and so on — otherwise `ERR_CASE_STAGE_FORBIDDEN` (HTTP 409). In this same priority, optimistic-concurrency fields must match the current entity version, otherwise `ERR_STALE_VERSION` (HTTP 412).
7. **Entity lifecycle state.** The target entity's own status must permit the requested transition, otherwise the corresponding member of the invalid-state family — `ERR_INVALID_ITEM_STATE`, `ERR_INVALID_INVITATION_STATE`, `ERR_INVALID_ROUND_STATE`, `ERR_INVALID_EXTENSION_STATE`, `ERR_INVALID_MIDTERM_STATE`, `ERR_INVALID_APPEAL_STATE`, or `ERR_INVALID_VOTE_STATE` (all HTTP 409). Within this priority, the round-state check on ballot changes and retractions precedes the vote-state check, and on round open and reopen the round-seal check (`ERR_ROUND_SEALED`, HTTP 409) follows the round-state check.
8. **Segregation of duties and arm's-length safety.** The four rules of §2.7 are enforced here: `ERR_SOD_CERTIFIER_VOTED`, `ERR_SOD_DECISION_BY_CASE_CREATOR`, `ERR_RECUSAL_IRREVERSIBLE` (all HTTP 409), and `ERR_ARMS_LENGTH_VIOLATION` (HTTP 422).
9. **Structural constraints.** Uniqueness of `employee_id` and reviewer `email`, one non-retracted ballot per member per round, one active chair per committee, supersede-target shape, duplicate non-terminal invitations, interval sanity, extension overlap and day cap, reviewer capacity, and voter eligibility — `ERR_DUPLICATE_EMPLOYEE_ID`, `ERR_DUPLICATE_REVIEWER_EMAIL`, `ERR_DUPLICATE_BALLOT`, `ERR_CHAIR_CONFLICT`, `ERR_SUPERSEDE_TARGET_INVALID`, `ERR_DUPLICATE_INVITATION`, `ERR_INVALID_INTERVAL`, `ERR_EXTENSION_INTERVAL_OVERLAP`, `ERR_REVIEWER_CAPACITY_EXCEEDED`, `ERR_EXTENSION_CAP_EXCEEDED`, `ERR_VOTER_NOT_ELIGIBLE`, and malformed-request failures (missing required fields, wrong types, enum values outside the declared sets, invalid pagination parameters, a request body that is not a JSON object) under `ERR_INVALID_REQUEST`. Within this priority, ties evaluate in the order the checks are listed here.
10. **Temporal windows.** Deadline checks against the logical clock — `ERR_REVIEW_CLOCK_EXPIRED`, `ERR_INVITATION_EXPIRED`, `ERR_REVIEW_WINDOW_CLOSED`, `ERR_NOTIFICATION_WINDOW_LAPSED`, `ERR_APPEAL_WINDOW_LAPSED`, `ERR_APPEAL_WINDOW_OPEN`, and `ERR_RETENTION_NOT_EXPIRED` (all HTTP 409).
11. **Aggregate and referential gates.** Evaluated last: dossier completeness, open-invitation gates, the three-letter minimum, the mid-tenure review gates, round certification, committee selection, quorum and eligible-voter gates, the score threshold, and the single-open-appeal rule — `ERR_DOSSIER_INCOMPLETE`, `ERR_INSUFFICIENT_EXTERNAL_LETTERS`, `ERR_OPEN_INVITATIONS_EXIST`, `ERR_MIDTERM_REVIEW_MISSING`, `ERR_MIDTERM_OUTCOME_BLOCKS`, `ERR_ROUND_NOT_CERTIFIED`, `ERR_NO_ELIGIBLE_COMMITTEE`, `ERR_QUORUM_NOT_MET`, `ERR_NO_ELIGIBLE_VOTERS`, `ERR_SCORE_BELOW_THRESHOLD`, and `ERR_APPEAL_ALREADY_OPEN`. Within this priority, ties evaluate in the order the checks are listed here.

## 3. Business Logic & Workflows

### 3.1. Candidate Registration and Case Intake

A `ProvostOfficer` registers each faculty member under review by providing the candidate's `full_name`, `employee_id`, `department`, `college`, and `tenure_clock_start` — the date the probationary tenure clock began. The `employee_id` must be unique across all registered candidates; a duplicate registration is rejected with `ERR_DUPLICATE_EMPLOYEE_ID`. New candidates begin with `status` set to `ACTIVE`, and their status changes only through decision and withdrawal cascades described later — to `TENURED`, `NOT_RENEWED`, or `WITHDRAWN` — never through a direct update.

With a candidate registered, a `ProvostOfficer` opens the review case by submitting a payload containing the `candidate_id`, the `review_cycle` label (for example, `2026-2027`), the `target_rank` (`ASSOCIATE_PROFESSOR` or `FULL_PROFESSOR`), the `seeking_tenure` flag distinguishing a tenure case from a promotion-only case, the `clock_policy` selecting the deadline arithmetic (`ANNIVERSARY` or `DAY_COUNT`), and optionally `waiver_signed`, which defaults to true. The `clock_policy` is immutable once the case exists. The system records the creating officer's identity in `created_by_user_id` and places the case in `DOSSIER_ASSEMBLY`.

A case's `stage` walks a long path over its lifetime: `DOSSIER_ASSEMBLY`, `EXTERNAL_REVIEW`, `DEPT_COMMITTEE`, `COLLEGE_COMMITTEE`, `UNIVERSITY_COMMITTEE`, `PROVOST_REVIEW`, `DECIDED`, `NOTIFIED`, `CLOSED`, `ARCHIVED`, and `PURGED`, with `RETURNED_FOR_REVISION` as a revision loop off external review and `WITHDRAWN` as a candidate-driven exit; `WITHDRAWN` and `PURGED` are terminal.

At case creation the system also fixes the `mandatory_review_date`, the deadline by which the dossier must be submitted. The anchor is the candidate's `tenure_clock_start`. Under the `ANNIVERSARY` policy the base date is the anchor advanced by 72 calendar months, month-anchored: a clock that started on 2020-08-01 yields a base of 2026-08-01. Under the `DAY_COUNT` policy the base is the anchor advanced by a fixed count of days — 72 months at 30.4375 days per month, rounded half-up, giving 2,192 days — so the same 2020-08-01 anchor yields 2026-08-02, one day later than the anniversary result, since the fixed day count drifts across leap years. The case's `extension_days`, initially zero, is then added to the base date. Several computed fields remain null until their triggering events: `dossier_submitted_at` until the dossier is submitted, `dossier_strength_index` until the same moment, `recommendation_score` until the university round's certification advances the case, `appeal_filing_deadline` until notification, `closed_at` and `retention_until` until closure, and `purged_at` until purge.

### 3.2. Assembling the Dossier: Evidence, Completeness, and the Strength Index

While the case is in `DOSSIER_ASSEMBLY`, the owning `Candidate` composes the dossier one evidence item at a time. Creating an item requires a payload containing the `case_id`, the evidence `category` (`TEACHING`, `RESEARCH`, or `SERVICE`), a `title`, a `page_count` of at least one (anything less is rejected with `ERR_INVALID_REQUEST`), an optional `is_peer_reviewed` flag defaulting to false, and an optional `supersedes_item_id`, null when omitted, pointing at the item this new evidence replaces. Because the item set is composed against a snapshot of the case, the create also carries the OCC field `expected_case_version` per §2.11, and a successful create advances the case's `version` by one. New items begin in `DRAFT` status.

Items move through a small lifecycle. The owning candidate submits a `DRAFT` or `RETURNED` item, moving it to `SUBMITTED`; the provost office returns a `SUBMITTED` item, moving it back to `RETURNED`; the candidate withdraws a `DRAFT` or `RETURNED` item, moving it to `WITHDRAWN`. Submission is also where the supersede cascade fires: when the submitted item carries a `supersedes_item_id`, the target must be a `SUBMITTED` item of the same case and the same category, in which case the target flips to `SUPERSEDED`; if the target is anything else the submission fails with `ERR_SUPERSEDE_TARGET_INVALID`. All item mutations require the case to be in `DOSSIER_ASSEMBLY` — any other stage is rejected with `ERR_CASE_STAGE_FORBIDDEN` — and candidate actions require ownership, otherwise `ERR_OWNERSHIP_MISMATCH`. Transitions that do not match the item's current status are rejected with `ERR_INVALID_ITEM_STATE`. `SUPERSEDED` and `WITHDRAWN` are terminal.

When the dossier is ready, the candidate submits it, moving the case from `DOSSIER_ASSEMBLY` to `EXTERNAL_REVIEW`. Submission enforces three gates. The acting user must own the case, otherwise `ERR_OWNERSHIP_MISMATCH`. The dossier must be complete: counting only items in `SUBMITTED` status — items in `DRAFT`, `RETURNED`, `SUPERSEDED`, or `WITHDRAWN` never count — the dossier must contain at least two `TEACHING` items, at least three `RESEARCH` items, and at least one `SERVICE` item, and at least one of the `SUBMITTED` `RESEARCH` items must have `is_peer_reviewed` set to true; counts exactly equal to a minimum pass, and any shortfall is rejected with `ERR_DOSSIER_INCOMPLETE`. And the logical clock must not have passed the case's `mandatory_review_date`; a submission after that date is rejected with `ERR_REVIEW_CLOCK_EXPIRED`. On success the system stamps `dossier_submitted_at` with the current clock reading, computes and stores the `dossier_strength_index`, locks all of the case's `SUBMITTED` items against further transitions until the case is back in `DOSSIER_ASSEMBLY`, and increments the case's `version` by one.

The `dossier_strength_index` rewards depth beyond the minima. For each category, the system divides the number of qualifying `SUBMITTED` items by that category's completeness minimum — two for teaching, three for research, one for service — caps the resulting ratio at 2.0, and rounds the capped ratio half-up to three decimal places. Each rounded ratio is then multiplied by its category weight — 0.30 for teaching, 0.50 for research, 0.20 for service — using exact decimal arithmetic, and the three contributions are summed; the index is that sum rounded half-up to four decimal places. The evaluation order is pinned: each ratio is rounded to three decimal places first, before weighting and summation. Summing the unrounded ratios and rounding only the total is a forbidden variant — a dossier with three teaching items, five research items, and one service item yields 1.4835 under the pinned order, where the forbidden variant would produce 1.4833.

A case in `EXTERNAL_REVIEW` can be sent back for dossier work. A `ProvostOfficer` may return the case for revision only while no invitation of the case stands in `ACCEPTED` status — accepted reviewers must first be withdrawn or deliver their letters, otherwise the return is rejected with `ERR_OPEN_INVITATIONS_EXIST`. On return, the case moves to `RETURNED_FOR_REVISION`, every `SOLICITED` invitation of the case flips to `WITHDRAWN` and its review window is released, and the case's `version` increments by one. The candidate then resumes assembly — an ownership-checked action that moves the case from `RETURNED_FOR_REVISION` back to `DOSSIER_ASSEMBLY`, unlocks the dossier items so item transitions are allowed again, and increments the case's `version` by one.

### 3.3. Mid-Tenure Reviews and Stop-the-Clock Extensions

Two standing obligations run alongside dossier assembly and external review. The first is the mid-tenure review. A `ProvostOfficer` opens one for a case by providing the `case_id` and the `review_year` — the probation year the review covers, which must be at least one, otherwise `ERR_INVALID_REQUEST`. The review is created directly in `IN_PROGRESS` status. Completing the review stores the `outcome` from the payload — `SATISFACTORY`, `CONCERNS`, or `UNSATISFACTORY` — stamps `completed_at` with the current clock reading, and moves the review to its terminal `COMPLETED` status; completing an already-completed review is rejected with `ERR_INVALID_MIDTERM_STATE`. As §3.4 will show, a completed mid-tenure review with an acceptable outcome is a hard precondition for closing external solicitation.

The second obligation is the stop-the-clock process. The owning candidate files a clock-extension request while the case is in any stage before `DECIDED` — later stages are rejected with `ERR_CASE_STAGE_FORBIDDEN` — supplying the `case_id`, a `reason` (`PARENTAL_LEAVE`, `MEDICAL_LEAVE`, `BEREAVEMENT`, or `OTHER`), and the stopped interval as `interval_start` and `interval_end`, with the start strictly before the end per §2.8. The request is created in `PENDING` status, with `decided_at` null until a decision.

A `ProvostOfficer` then adjudicates. Approval enforces two checks in order, both against the case's already-`APPROVED` intervals. First, the candidate interval must not overlap any approved interval under the half-open semantics of §2.8 — touching intervals, where the new `interval_start` equals an existing `interval_end`, are permitted — otherwise `ERR_EXTENSION_INTERVAL_OVERLAP`. Second, the merged union of the approved intervals plus the candidate interval must total at most 730 days; because touching intervals coalesce into their union, the merged total of merely-touching intervals equals their plain sum. A union exceeding the cap is rejected with `ERR_EXTENSION_CAP_EXCEEDED`. On approval the request moves to `APPROVED` with `decided_at` stamped, the case's `extension_days` is recomputed as the sum, in whole days, of the merged union of all approved intervals, the `mandatory_review_date` is recomputed accordingly, and the case's `version` increments by one. Denial moves a `PENDING` request to `DENIED` with `decided_at` stamped and touches nothing else. An officer may also rescind an `APPROVED` request, moving it to `RESCINDED`: `decided_at` is stamped anew, `extension_days` and `mandatory_review_date` are recomputed without the rescinded interval, and the case's `version` increments by one. Requests whose status does not permit the attempted transition are rejected with `ERR_INVALID_EXTENSION_STATE`. When a case is withdrawn, its still-`PENDING` requests are cancelled automatically, moving to `CANCELLED`; `DENIED`, `RESCINDED`, and `CANCELLED` are terminal.

### 3.4. Soliciting External Reviewers and Collecting Letters

Before invitations can go out, a `ProvostOfficer` registers each external reviewer with their `full_name`, `institution` — which must differ from the university itself and is informational — `email`, and `expertise_area`. The `email` must be unique across all registered reviewers; duplicates are rejected with `ERR_DUPLICATE_REVIEWER_EMAIL`.

Solicitation happens while the case is in `EXTERNAL_REVIEW`; attempting it in any other stage is rejected with `ERR_CASE_STAGE_FORBIDDEN`. The officer creates an invitation with a payload containing the `case_id`, the `reviewer_id`, the proposed `review_window_start` and `review_window_end`, the arm's-length attestations `is_arm_length` and `declared_coauthor`, and the OCC field `expected_case_version` per §2.11; a successful create advances the case's `version` by one. Creation enforces the structural and temporal rules in priority order: the review window must be well-formed with the start strictly before the end (`ERR_INVALID_INTERVAL`); the window's end must still be in the future at creation time, otherwise `ERR_REVIEW_WINDOW_CLOSED`; the arm's-length rule of §2.7 must hold (`ERR_ARMS_LENGTH_VIOLATION`); no other invitation for the same case and reviewer may exist in `SOLICITED`, `ACCEPTED`, or `LETTER_RECEIVED` status (`ERR_DUPLICATE_INVITATION`); and the reviewer must have capacity — if the reviewer already holds two invitations in `SOLICITED` or `ACCEPTED` status whose review windows overlap the new window under the closed semantics of §2.8, where touching windows count as overlapping, creation is rejected with `ERR_REVIEWER_CAPACITY_EXCEEDED`, while two such invitations whose windows do not touch the new one leave capacity open. The invitation is created directly in `SOLICITED` status, `invited_at` is stamped with the current clock reading, and `response_deadline` is set fourteen days after `invited_at`.

The invited `ExternalReviewer` then responds. Accepting moves the invitation from `SOLICITED` to `ACCEPTED`; declining moves it to `DECLINED`. Both responses apply lazy expiry first: if the logical clock has passed the `response_deadline`, the invitation flips to `EXPIRED` and the response fails with `ERR_INVITATION_EXPIRED`. Both also require the acting reviewer to be the invited reviewer, otherwise `ERR_OWNERSHIP_MISMATCH`. After accepting, the reviewer submits the review letter by supplying `letter_text`; submission is allowed only while the clock has not passed `review_window_end` — a late letter is rejected with `ERR_REVIEW_WINDOW_CLOSED` — and on success `letter_received_at` is stamped and the invitation moves to its terminal `LETTER_RECEIVED` status. The provost office may withdraw a `SOLICITED` or `ACCEPTED` invitation, moving it to `WITHDRAWN`. Any response, letter submission, or withdrawal attempted from an incompatible status is rejected with `ERR_INVALID_INVITATION_STATE`.

When the solicitation phase is complete, a `ProvostOfficer` closes external review, moving the case from `EXTERNAL_REVIEW` to `DEPT_COMMITTEE`. The close first applies lazy expiry in a batch: every `SOLICITED` invitation whose `response_deadline` has passed flips to `EXPIRED`. If any invitation remains in `SOLICITED` after the batch expiry, the close is rejected with `ERR_OPEN_INVITATIONS_EXIST`. Only invitations in `LETTER_RECEIVED` status count as usable letters — `SOLICITED`, `ACCEPTED`, `DECLINED`, `WITHDRAWN`, and `EXPIRED` never count — and the case needs at least three of them, with exactly three passing; a shortfall is rejected with `ERR_INSUFFICIENT_EXTERNAL_LETTERS`. A `COMPLETED` mid-tenure review must exist for the case (`ERR_MIDTERM_REVIEW_MISSING`), and no completed mid-tenure review may carry the `UNSATISFACTORY` outcome (`ERR_MIDTERM_OUTCOME_BLOCKS`). Finally, the committee selector of §3.5 must find an eligible `DEPARTMENT` committee (`ERR_NO_ELIGIBLE_COMMITTEE`). On success the system creates the department-level review round in `SCHEDULED` status, bound to the selected committee, and increments the case's `version` by one.

### 3.5. Committees, Review Rounds, and Balloting

Committees are maintained by the provost office. Creating one requires the `level` (`DEPARTMENT`, `COLLEGE`, or `UNIVERSITY`), the `academic_unit` scope, the `term_start` and `term_end` dates with the start strictly before the end, the `pass_rule`, and optionally the `quorum_fraction` (defaulting to 0.5; any JSON number is accepted without range validation). Members are added with the `committee_id`, `full_name`, `email`, the service window `service_start` and `service_end` (equality of the endpoints permitted per §2.8), and an optional `role_in_committee` defaulting to `MEMBER`; a member may instead be created as `CHAIR`, subject to the one-active-chair rule of §2.9. New members have `is_active` set to true. Deactivating a member sets `is_active` to false — deactivating an already-inactive member succeeds, merely refreshing `updated_at` and incrementing `version`; inactive members are excluded from every eligibility count and cannot vote.

Review rounds are never created directly through the API. The system creates them at stage transitions — at solicitation close, at stage advancement, and at remand — binding each round to the committee produced by the selector. The selector first filters committees by eligibility: the `level` must equal the level being entered; the `academic_unit` must match the candidate's `department` for a `DEPARTMENT` round or the candidate's `college` for a `COLLEGE` round, while a `UNIVERSITY` round matches on level alone regardless of unit; and the committee's term must cover the current clock reading, with the clock reading falling on or after `term_start` and on or before `term_end`. Eligible committees are ranked by `term_start` with the most recent term first, ties broken by earliest `created_at`; entity identifiers are never used for ranking. An empty candidate set fails the calling transition with `ERR_NO_ELIGIBLE_COMMITTEE`. The created round copies `level` from its committee and starts in `SCHEDULED` status with `opened_at` null; its tally counters (`votes_cast`, `yes_count`, `no_count`, `abstain_count`, and `recusal_count`) start at zero with `quorum_met` false, while `active_member_count`, `eligible_voter_count`, `quorum_required`, `yes_percentage`, `passed`, `recommendation`, `letter_text`, and `certified_at` remain null until the round is opened or certified.

The round's committee chair — an active member with `role_in_committee` equal to `CHAIR`, acting under the `CommitteeChair` role — opens voting. Opening requires the round to be `SCHEDULED` (`ERR_INVALID_ROUND_STATE` otherwise), the acting user to be an active chair of the round's committee (`ERR_OWNERSHIP_MISMATCH` otherwise), and the owning case's stage to still match the round's level — a case that has advanced past the round seals it, rejected with `ERR_ROUND_SEALED`. Opening stamps `opened_at` with the current clock reading and fixes the electorate: `active_member_count` is the number of the committee's members with `is_active` true whose service window covers `opened_at`, `eligible_voter_count` starts equal to that count, `recusal_count` starts at zero, and `quorum_required` is computed per §2.9.

While the round is `VOTING_OPEN`, committee members cast ballots under the `CommitteeVoter` role with a payload containing the `round_id` and the `ballot` — `YES`, `NO`, `ABSTAIN`, or `RECUSE`. The vote's `member_id` is always resolved from the `X-User-ID` header, never accepted from the request body. Casting requires the voter to be an active member of the round's committee whose service window covers `opened_at`, otherwise `ERR_VOTER_NOT_ELIGIBLE`, and no member may hold more than one non-retracted ballot of any kind in the same round, otherwise `ERR_DUPLICATE_BALLOT`. Ballot operations against a round that is not `VOTING_OPEN` are rejected with `ERR_INVALID_ROUND_STATE`. A new vote begins in `CAST` status with `cast_at` stamped.

A member may change their ballot while the round remains `VOTING_OPEN`. The change is made by the vote's own member only (`ERR_OWNERSHIP_MISMATCH`), carries the OCC field `expected_vote_version` per §2.11, and is subject to the recusal-irreversibility rule of §2.7 (`ERR_RECUSAL_IRREVERSIBLE`); a successful change increments the vote's `version` by one. A member may instead retract, moving the vote from `CAST` to its terminal `RETRACTED` status with `retracted_at` stamped. Patch or retraction attempted on a vote that is not `CAST` is rejected with `ERR_INVALID_VOTE_STATE`.

Every ballot mutation — cast, change, or retraction — recomputes the round's live tallies while the round is neither `COMPLETED` nor `CANCELLED`: `yes_count`, `no_count`, and `abstain_count` count the non-retracted ballots of each kind, `votes_cast` counts the non-retracted `YES`, `NO`, and `ABSTAIN` ballots together while `RECUSE` ballots never count, `recusal_count` counts the non-retracted `RECUSE` ballots, `eligible_voter_count` is the fixed `active_member_count` minus `recusal_count`, and `quorum_required` is recomputed with it. Retracting a `RECUSE` ballot therefore re-includes the member in the eligible electorate. The round's `quorum_met` flag is true exactly when `votes_cast` is at least `quorum_required` and `eligible_voter_count` is at least one.

### 3.6. Tally Certification, Stage Advancement, and the Recommendation Score

When balloting is finished, the chair closes voting, moving the round from `VOTING_OPEN` to `TALLYING`. The tallies are recomputed at the close and ballots are frozen — no further casts, changes, or retractions are accepted until a reopen.

Certification is the chair's formal act, and it applies its gates in a stated order. The round must be in `TALLYING` (`ERR_INVALID_ROUND_STATE`), and the acting user must be an active chair of the round's committee (`ERR_OWNERSHIP_MISMATCH`). The payload's shape — the presence and validity of `recommendation` and `letter_text` — is validated next, before the tally gates. Among the tally gates, the eligible-electorate check is evaluated first: if `eligible_voter_count` has fallen to zero, certification is rejected with `ERR_NO_ELIGIBLE_VOTERS`. Next, quorum must be met per §2.9, otherwise `ERR_QUORUM_NOT_MET`. Finally the certifier must hold no non-retracted ballot of any kind in the round, otherwise `ERR_SOD_CERTIFIER_VOTED`. The certification payload carries the committee's `recommendation` — one of `STRONGLY_SUPPORT`, `SUPPORT`, `NEUTRAL`, `OPPOSE`, or `STRONGLY_OPPOSE` — and the recommendation letter body in `letter_text`, both stored on the round and confidential under the seal of §2.7. Certification stamps `certified_at`, computes the round's `yes_percentage` and `passed` verdict, and moves the round from `TALLYING` to `COMPLETED`.

The two certification computations follow the committee's tally arithmetic. `yes_percentage` is the round's `yes_count` divided by the sum of `yes_count` and `no_count`, rounded half-up to four decimal places; when no `YES` or `NO` ballots exist at all, it is null. The `passed` verdict depends on the committee's `pass_rule`. Under `STRICT_MAJORITY_OF_CAST`, the round passes when the yes-share of cast yes-plus-no ballots is strictly greater than one half — an exact tie fails. Under `SUPERMAJORITY_OF_ENTITLED`, the round passes when `yes_count` divided by `eligible_voter_count`, rounded half-up to four decimal places, is at least the 0.6667 threshold — an exact two-thirds, which rounds to 0.6667, passes — so recusals shrink the denominator while abstentions and non-voters count against the motion. Identical ballots can diverge under the two rules: with six eligible voters, three `YES`, one `NO`, and two `ABSTAIN`, the strict rule passes at 0.75 while the supermajority rule fails at 0.50 against its 0.6667 threshold.

Certification deliberately does not advance the case: advancement is a separate act by a `ProvostOfficer`, which keeps the reopen window reachable. While the case's stage still matches the round's level and the round remains the case's latest round at its level by `created_at` (creation order breaks ties), the chair may reopen a `COMPLETED` round, moving it back to `VOTING_OPEN`; a case that has advanced seals the round against both opening and reopening with `ERR_ROUND_SEALED`, and a remand — which creates a newer department round — seals the pre-remand round by the same code. Reopening clears `certified_at`, `passed`, `yes_percentage`, `recommendation`, and `letter_text` to null, leaves all non-retracted votes in `CAST`, and recomputes the tallies.

Advancement moves the case through the committee ladder. From `DEPT_COMMITTEE` it requires the case's latest department round by `created_at` (creation order breaks ties) to be `COMPLETED` (`ERR_ROUND_NOT_CERTIFIED`) and the selector to find an eligible `COLLEGE` committee (`ERR_NO_ELIGIBLE_COMMITTEE`); on success the case enters `COLLEGE_COMMITTEE` and a fresh college round is created in `SCHEDULED`. From `COLLEGE_COMMITTEE` the same two checks apply at the college and university levels respectively, producing a `SCHEDULED` university round and the `UNIVERSITY_COMMITTEE` stage. Each advancement increments the case's `version` by one.

Advancing from `UNIVERSITY_COMMITTEE` requires the latest university round to be `COMPLETED` (`ERR_ROUND_NOT_CERTIFIED`) and moves the case to `PROVOST_REVIEW`. At that moment the system computes and stores the case's `recommendation_score`. For each of the three levels it takes the case's `COMPLETED` round at that level — when several exist after a remand, the one with the latest `certified_at`, ties broken by latest `created_at` — and reads its already-rounded `yes_percentage`, with a selected round whose percentage is null contributing zero. The raw score is the department percentage weighted at 0.25, the college percentage at 0.35, and the university percentage at 0.40, summed. If any of the three selected rounds failed, the stored score is the raw sum rounded half-up to four decimal places, capped at 0.49 — whichever is smaller; otherwise it is simply the raw sum rounded half-up to four decimal places. For example, percentages of 0.75, 0.80, and 0.6667 with all rounds passed yield a raw 0.73418 and a stored 0.7342, while percentages of 0.80, 0.80, and 0.50 with the university round failed yield a raw 0.68 and a stored 0.49. A later remand clears the score back to null.

### 3.7. The Provost Decision, Notification, and Case Closure

With the case in `PROVOST_REVIEW` — any other stage is rejected with `ERR_CASE_STAGE_FORBIDDEN` — a `ProvostOfficer` records the decision with a payload containing the `case_id`, the `decision` (`GRANT_TENURE`, `GRANT_PROMOTION`, `GRANT_BOTH`, `DENY`, or `DEFER`), the `rationale_text`, and optionally `override_rationale`, which defaults to null. Two gates apply. The recorder's identity, stored as `recorded_by_user_id`, must differ from the case's `created_by_user_id` (`ERR_SOD_DECISION_BY_CASE_CREATOR`). And for any granting decision — `GRANT_TENURE`, `GRANT_PROMOTION`, or `GRANT_BOTH` — the case's `recommendation_score` must be at least 0.60 unless a non-empty `override_rationale` — one with non-whitespace content — is supplied; a grant below the threshold without an override is rejected with `ERR_SCORE_BELOW_THRESHOLD`. On success the decision is created in `RECORDED` status, `decided_at` is stamped, and the `notification_deadline` is set ten days after `decided_at`. The case moves from `PROVOST_REVIEW` to `DECIDED` and its `version` increments by one. The candidate cascade follows the verdict: a `DENY` moves the candidate's `status` to `NOT_RENEWED`, and a `GRANT_TENURE` or `GRANT_BOTH` recorded on a case whose `seeking_tenure` is true moves the candidate to `TENURED`. Because stage gating makes a second decision unreachable while one stands, a further decision can only be recorded after a remand voids the first.

Notification is time-boxed. A `ProvostOfficer` notifies the candidate only while a `RECORDED` decision exists — otherwise `ERR_DECISION_NOT_FOUND` — and only while the logical clock has not passed the `notification_deadline`, with notification exactly at the deadline still permitted; a late notification is rejected with `ERR_NOTIFICATION_WINDOW_LAPSED`. On success `notification_sent_at` is stamped on the decision, the case's `appeal_filing_deadline` is set thirty days after the notification, the case moves from `DECIDED` to `NOTIFIED`, and its `version` increments by one.

Closure waits out the appeal window. Closing requires the logical clock to be strictly past the `appeal_filing_deadline` — an attempt at or before the deadline is rejected with `ERR_APPEAL_WINDOW_OPEN` — and requires that no appeal of the case stands in `FILED` or `UNDER_REVIEW` (`ERR_APPEAL_PENDING`). On success `closed_at` is stamped, `retention_until` is set 2,555 days after closure — seven 365-day years — the case moves from `NOTIFIED` to `CLOSED`, and its `version` increments by one.

### 3.8. Appeals and the Remand Cascade

A candidate who disputes the outcome files an appeal while the case is `NOTIFIED` — any other stage is rejected with `ERR_CASE_STAGE_FORBIDDEN` — supplying the `case_id` and the `grounds`: `PROCEDURAL_ERROR`, `NEW_EVIDENCE`, `DISCRIMINATION`, or `CAPRICIOUS_EVALUATION`. Filing requires ownership (`ERR_OWNERSHIP_MISMATCH`), requires the filing to fall on or before the case's `appeal_filing_deadline`, with a filing exactly at the deadline permitted — a late filing is rejected with `ERR_APPEAL_WINDOW_LAPSED` — and requires that no other appeal of the case stands in `FILED` or `UNDER_REVIEW`, otherwise `ERR_APPEAL_ALREADY_OPEN`. The appeal is created in `FILED` status with `filed_at` stamped from the logical clock. Its `resolution`, `resolution_text`, and `resolved_at` remain null until resolution.

An `AppealOfficer` opens review, moving the appeal from `FILED` to `UNDER_REVIEW`, and later resolves it by supplying the `resolution` and a `resolution_text`; resolution stamps `resolved_at`. Three resolutions are possible, and they diverge sharply. `UPHELD` means the challenged decision stands — the appeal is dismissed and nothing on the case changes. `DENIED` rejects the appeal on its merits, likewise leaving the case untouched. `REMANDED` sends the case back for re-review and fires the full remand cascade, which is permitted only while the case is `DECIDED` or `NOTIFIED` (`ERR_CASE_STAGE_FORBIDDEN` otherwise); within a resolution call the appeal-state gate is applied first, then payload-shape validation, and only a `REMANDED` resolution reaches the case-stage gate. Resolution or review attempted from an incompatible appeal status is rejected with `ERR_INVALID_APPEAL_STATE`; `UPHELD`, `DENIED`, `REMANDED`, and `WITHDRAWN` are terminal. The candidate may also withdraw a `FILED` appeal — an ownership-checked action moving it to `WITHDRAWN`.

The remand cascade reopens the entire committee ladder. The `RECORDED` decision flips to `VOIDED`. The candidate's `status` returns to `ACTIVE` from either `TENURED` or `NOT_RENEWED`. The case's `recommendation_score` is cleared to null, and when the remand fires from `NOTIFIED` the `appeal_filing_deadline` is cleared as well. The committee selector must find an eligible `DEPARTMENT` committee — it runs before any mutation, so if none is eligible the appeal's resolution call itself fails with `ERR_NO_ELIGIBLE_COMMITTEE`, leaving the appeal and the case untouched — and the system creates a fresh department round in `SCHEDULED` status, which seals any pre-remand department round against reopening per §3.6. The case's `stage` moves from `DECIDED` or `NOTIFIED` back to `DEPT_COMMITTEE` and its `version` increments by one.

### 3.9. Withdrawal, Archival, and Records Purge

The candidate may abandon the case at any point before a decision stands. Withdrawal is an ownership-checked action (`ERR_OWNERSHIP_MISMATCH`) available from `DOSSIER_ASSEMBLY`, `EXTERNAL_REVIEW`, `RETURNED_FOR_REVISION`, `DEPT_COMMITTEE`, `COLLEGE_COMMITTEE`, `UNIVERSITY_COMMITTEE`, and `PROVOST_REVIEW`; from any later stage it is rejected with `ERR_CASE_STAGE_FORBIDDEN`. Every withdrawal moves the case to the terminal `WITHDRAWN` stage, moves the candidate's `status` to `WITHDRAWN`, cancels the case's still-`PENDING` clock-extension requests, and increments the case's `version` by one. The teardown then depends on the stage. From `EXTERNAL_REVIEW`, all invitations in `SOLICITED` or `ACCEPTED` flip to `WITHDRAWN`. From the three committee stages, every round in `SCHEDULED`, `VOTING_OPEN`, or `TALLYING` flips to the terminal `CANCELLED` status, and for rounds cancelled from `VOTING_OPEN` or `TALLYING` all of the round's `CAST` votes are retracted by the system with `retracted_at` stamped. From `DOSSIER_ASSEMBLY`, `RETURNED_FOR_REVISION`, and `PROVOST_REVIEW` no further teardown applies beyond the shared effects.

After closure, custody passes to the records office. A `RecordsOfficer` archives a `CLOSED` case, moving it to `ARCHIVED` and incrementing its `version` by one. Purge is the final act: it is permitted only once the logical clock has reached the case's `retention_until`, with a purge exactly at the boundary permitted; an earlier attempt is rejected with `ERR_RETENTION_NOT_EXPIRED`. On success `purged_at` is stamped, the case moves to the terminal `PURGED` stage, and its `version` increments by one.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a candidate, a case, a dossier item, a reviewer, an invitation, a committee, a member, a vote, a clock-extension request, a mid-tenure review, a decision, or an appeal — return a `201 Created` status code. Operations that modify an existing resource, including all lifecycle actions and state transitions, return a `200 OK` status code. The complete request and response shapes of each operation are defined by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/candidates` | Register a candidate | ProvostOfficer |
| GET | `/api/candidates/{id}` | Get a candidate | Any |
| POST | `/api/cases` | Open a tenure/promotion case for a candidate | ProvostOfficer |
| GET | `/api/cases` | List cases, filterable by candidate and stage | Any |
| GET | `/api/cases/{id}` | Get a case | Any |
| POST | `/api/cases/{id}/submit-dossier` | Submit the assembled dossier; `DOSSIER_ASSEMBLY` → `EXTERNAL_REVIEW` | Candidate |
| POST | `/api/cases/{id}/return-for-revision` | Return the case for dossier revision; `EXTERNAL_REVIEW` → `RETURNED_FOR_REVISION` | ProvostOfficer |
| POST | `/api/cases/{id}/resume-assembly` | Resume dossier assembly; `RETURNED_FOR_REVISION` → `DOSSIER_ASSEMBLY` | Candidate |
| POST | `/api/cases/{id}/close-solicitation` | Close external review and create the department round; `EXTERNAL_REVIEW` → `DEPT_COMMITTEE` | ProvostOfficer |
| POST | `/api/cases/{id}/advance-stage` | Advance past a certified round: department → college, college → university, or university → provost review | ProvostOfficer |
| POST | `/api/cases/{id}/withdraw` | Candidate withdraws the case (pre-decision stages only) | Candidate |
| POST | `/api/cases/{id}/notify` | Notify the candidate of the decision; `DECIDED` → `NOTIFIED` | ProvostOfficer |
| POST | `/api/cases/{id}/close` | Close the case after the appeal window lapses; `NOTIFIED` → `CLOSED` | ProvostOfficer |
| POST | `/api/cases/{id}/archive` | Move a closed case to archives; `CLOSED` → `ARCHIVED` | RecordsOfficer |
| POST | `/api/cases/{id}/purge` | Purge an archived case once retention expires; `ARCHIVED` → `PURGED` | RecordsOfficer |
| POST | `/api/dossier-items` | Create a dossier evidence item (OCC on the parent case) | Candidate |
| GET | `/api/dossier-items` | List dossier items, filterable by case, supersession target, status, and category | Any |
| GET | `/api/dossier-items/{id}` | Get a dossier item | Any |
| POST | `/api/dossier-items/{id}/submit` | Submit a `DRAFT` or `RETURNED` item; fires the supersede cascade | Candidate |
| POST | `/api/dossier-items/{id}/return` | Return a `SUBMITTED` item for revision | ProvostOfficer |
| POST | `/api/dossier-items/{id}/withdraw` | Withdraw a `DRAFT` or `RETURNED` item | Candidate |
| POST | `/api/reviewers` | Register an external reviewer | ProvostOfficer |
| GET | `/api/reviewers/{id}` | Get a reviewer | Any |
| POST | `/api/invitations` | Solicit an external reviewer for a case (OCC on the parent case); created `SOLICITED` | ProvostOfficer |
| GET | `/api/invitations` | List invitations, filterable by case, reviewer, and status; candidate reads sealed per §2.7 | Any, Candidate |
| GET | `/api/invitations/{id}` | Get an invitation; candidate reads sealed per §2.7 | Any, Candidate |
| POST | `/api/invitations/{id}/accept` | Reviewer accepts the solicitation; `SOLICITED` → `ACCEPTED` | ExternalReviewer |
| POST | `/api/invitations/{id}/decline` | Reviewer declines the solicitation; `SOLICITED` → `DECLINED` | ExternalReviewer |
| POST | `/api/invitations/{id}/submit-letter` | Reviewer submits the review letter; `ACCEPTED` → `LETTER_RECEIVED` | ExternalReviewer |
| POST | `/api/invitations/{id}/withdraw` | Withdraw a `SOLICITED` or `ACCEPTED` invitation | ProvostOfficer |
| POST | `/api/committees` | Create a committee (level, unit, term, quorum fraction, pass rule) | ProvostOfficer |
| GET | `/api/committees/{id}` | Get a committee | Any |
| POST | `/api/members` | Add a member to a committee | ProvostOfficer |
| GET | `/api/members` | List committee members, filterable by committee | Any |
| GET | `/api/members/{id}` | Get a committee member | Any |
| POST | `/api/members/{id}/deactivate` | Deactivate a member; excluded from eligibility and voting | ProvostOfficer |
| GET | `/api/rounds` | List review rounds, filterable by case, committee, level, and status; candidate reads sealed per §2.7 | Any, Candidate |
| GET | `/api/rounds/{id}` | Get a round; candidate reads sealed per §2.7 | Any, Candidate |
| POST | `/api/rounds/{id}/open` | Chair opens voting; `SCHEDULED` → `VOTING_OPEN`; fixes the electorate and quorum | CommitteeChair |
| POST | `/api/rounds/{id}/close-voting` | Chair closes balloting; `VOTING_OPEN` → `TALLYING` | CommitteeChair |
| POST | `/api/rounds/{id}/certify` | Chair certifies the tally and files the recommendation letter; `TALLYING` → `COMPLETED` (advancement is not automatic) | CommitteeChair |
| POST | `/api/rounds/{id}/reopen` | Chair reopens a certified round while the case remains at its level; `COMPLETED` → `VOTING_OPEN` | CommitteeChair |
| POST | `/api/votes` | Cast a ballot (member resolved from `X-User-ID`) | CommitteeVoter |
| GET | `/api/votes` | List votes, filterable by round and member; candidate reads sealed per §2.7 | Any, Candidate |
| GET | `/api/votes/{id}` | Get a vote; candidate reads sealed per §2.7 | Any, Candidate |
| PATCH | `/api/votes/{id}` | Change a ballot while the round is `VOTING_OPEN` (OCC on the vote; recusal changes forbidden) | CommitteeVoter |
| POST | `/api/votes/{id}/retract` | Retract a ballot while the round is `VOTING_OPEN` | CommitteeVoter |
| POST | `/api/clock-extensions` | Candidate files a stop-the-clock request; created `PENDING` | Candidate |
| GET | `/api/clock-extensions` | List clock-extension requests, filterable by case and status | Any |
| GET | `/api/clock-extensions/{id}` | Get a clock-extension request | Any |
| POST | `/api/clock-extensions/{id}/approve` | Approve a `PENDING` request; validates overlap and cap; recomputes the case clock | ProvostOfficer |
| POST | `/api/clock-extensions/{id}/deny` | Deny a `PENDING` request | ProvostOfficer |
| POST | `/api/clock-extensions/{id}/rescind` | Rescind an `APPROVED` request; recomputes the case clock without it | ProvostOfficer |
| POST | `/api/midterm-reviews` | Open a mid-tenure review for a case; created `IN_PROGRESS` | ProvostOfficer |
| GET | `/api/midterm-reviews` | List mid-tenure reviews, filterable by case | Any |
| GET | `/api/midterm-reviews/{id}` | Get a mid-tenure review | Any |
| POST | `/api/midterm-reviews/{id}/complete` | Complete a mid-tenure review with an outcome | ProvostOfficer |
| POST | `/api/decisions` | Record the provost decision (recorder must differ from the case creator) | ProvostOfficer |
| GET | `/api/decisions` | List decisions, filterable by case | Any |
| GET | `/api/decisions/{id}` | Get a decision | Any |
| POST | `/api/appeals` | Candidate files an appeal within the filing window; created `FILED` | Candidate |
| GET | `/api/appeals` | List appeals, filterable by case and status | Any |
| GET | `/api/appeals/{id}` | Get an appeal | Any |
| POST | `/api/appeals/{id}/begin-review` | Appeal officer opens review; `FILED` → `UNDER_REVIEW` | AppealOfficer |
| POST | `/api/appeals/{id}/resolve` | Appeal officer resolves; a `REMANDED` resolution fires the remand cascade on the case | AppealOfficer |
| POST | `/api/appeals/{id}/withdraw` | Candidate withdraws a `FILED` appeal | Candidate |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock to a supplied ISO 8601 instant | SystemAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_CONFIDENTIAL_LETTERS_SEALED` | 403 Forbidden |
| `ERR_CANDIDATE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DOSSIER_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEWER_NOT_FOUND` | 404 Not Found |
| `ERR_INVITATION_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITTEE_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ROUND_NOT_FOUND` | 404 Not Found |
| `ERR_VOTE_NOT_FOUND` | 404 Not Found |
| `ERR_CLOCK_EXTENSION_NOT_FOUND` | 404 Not Found |
| `ERR_MIDTERM_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_DECISION_NOT_FOUND` | 404 Not Found |
| `ERR_APPEAL_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_INTERVAL` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CASE_STAGE_FORBIDDEN` | 409 Conflict |
| `ERR_INVALID_ITEM_STATE` | 409 Conflict |
| `ERR_INVALID_INVITATION_STATE` | 409 Conflict |
| `ERR_INVALID_ROUND_STATE` | 409 Conflict |
| `ERR_INVALID_EXTENSION_STATE` | 409 Conflict |
| `ERR_INVALID_MIDTERM_STATE` | 409 Conflict |
| `ERR_INVALID_APPEAL_STATE` | 409 Conflict |
| `ERR_INVALID_VOTE_STATE` | 409 Conflict |
| `ERR_ROUND_SEALED` | 409 Conflict |
| `ERR_SOD_CERTIFIER_VOTED` | 409 Conflict |
| `ERR_SOD_DECISION_BY_CASE_CREATOR` | 409 Conflict |
| `ERR_RECUSAL_IRREVERSIBLE` | 409 Conflict |
| `ERR_ARMS_LENGTH_VIOLATION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMPLOYEE_ID` | 409 Conflict |
| `ERR_DUPLICATE_REVIEWER_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT` | 409 Conflict |
| `ERR_CHAIR_CONFLICT` | 409 Conflict |
| `ERR_SUPERSEDE_TARGET_INVALID` | 409 Conflict |
| `ERR_DUPLICATE_INVITATION` | 409 Conflict |
| `ERR_EXTENSION_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_EXTENSION_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_REVIEWER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_VOTER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_REVIEW_CLOCK_EXPIRED` | 409 Conflict |
| `ERR_INVITATION_EXPIRED` | 409 Conflict |
| `ERR_REVIEW_WINDOW_CLOSED` | 409 Conflict |
| `ERR_NOTIFICATION_WINDOW_LAPSED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_LAPSED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_OPEN` | 409 Conflict |
| `ERR_RETENTION_NOT_EXPIRED` | 409 Conflict |
| `ERR_DOSSIER_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_EXTERNAL_LETTERS` | 409 Conflict |
| `ERR_OPEN_INVITATIONS_EXIST` | 409 Conflict |
| `ERR_MIDTERM_REVIEW_MISSING` | 409 Conflict |
| `ERR_MIDTERM_OUTCOME_BLOCKS` | 409 Conflict |
| `ERR_NO_ELIGIBLE_COMMITTEE` | 409 Conflict |
| `ERR_ROUND_NOT_CERTIFIED` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_NO_ELIGIBLE_VOTERS` | 409 Conflict |
| `ERR_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_APPEAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_APPEAL_PENDING` | 409 Conflict |
