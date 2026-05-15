# Paper Submission API — Product Requirements Document

## 1. Introduction

Scholarly publishing depends on a long chain of trust between authors, editors, reviewers, and the indexing infrastructure that disseminates accepted work. The Paper Submission system encodes that chain as a workflow: authors register themselves and bind an ORCID identity, prepare a manuscript with its co-authors and declarations, and submit it to a journal where editor-in-chief, section editors, and associate editors triage, assign, and ultimately decide. Reviewers — drawn from a pool curated by platform operators — receive invitations that are scored for both topical fit and conflict-of-interest exposure, accept under a strict capacity bound, and return ratings and recommendations that the associate editor aggregates into a recommended decision the editor-in-chief then finalizes. Revision rounds repeat the loop until the editor-in-chief accepts or rejects, and accepted work proceeds through copy-editing, proof correction, DOI minting, and indexing to PubMed, Web of Science, and Scopus.

The system optimizes for two competing imperatives. The first is rigor: every decision must be traceable, every conflict-of-interest signal recorded, every deadline enforced, and every cascade — from a co-author's decline to the auto-withdrawal of the manuscript, from a published manuscript's retraction to the failure of its indexing targets — applied atomically. The second is throughput: editors should not be blocked by paperwork, reviewers should not be over-allocated, and assignment-acceptance windows should not be allowed to silently overlap on a single editor. The API described below codifies both imperatives as a contract.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, the caller's identity, and `X-User-Role`, the caller's role. Requests that omit either header, or carry an unparseable value, are rejected with `ERR_AUTH_REQUIRED` (HTTP 401). Requests whose role is not authorized for the requested endpoint are rejected with `ERR_FORBIDDEN` (HTTP 403). Role names are case-sensitive and must be one of: `PlatformAdmin`, `Author`, `EditorInChief`, `SectionEditor`, `AssociateEditor`, `Reviewer`.

The six roles divide along identity lines. When `X-User-Role` is `Author`, `X-User-ID` is the `id` of the acting `Author`; ownership checks on any resource referencing an `Author` (for example, a `Manuscript`'s `corresponding_author_id`, a `CoAuthorConfirmation`'s `author_id`, a `Publication`'s author-approval path) compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `EditorInChief`, `SectionEditor`, or `AssociateEditor`, `X-User-ID` is the `id` of the acting `Editor` row; ownership checks compare `Manuscript.section_editor_id` or `Manuscript.associate_editor_id` to `X-User-ID` as appropriate. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `Reviewer`; the `reviewer_id` on a `ReviewerInvitation` (and indirectly on the `Review` it spawned) must equal `X-User-ID` for the reviewer-facing transitions. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_id` on `AuditLog` rows) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; any value outside `[1, 100]` is rejected as `ERR_VALIDATION` (HTTP 400). The default `offset` is 0; negative offsets are rejected the same way. List results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when more rows remain past the returned page. Several list endpoints accept additional filter parameters in the query string — for example, listing reviewers takes an `expertise_tag` and a `status`, listing editors takes a `role` and a `topic_tag`, listing manuscripts takes a `status`, `topic_tag`, and `corresponding_author_id`, listing invitations takes a `revision_round` and a `status`, and listing audit logs takes `entity`, `entity_id`, and `action`.

### 2.4. Common Resource Properties

Most persisted entities — `Author`, `Reviewer`, `Editor`, `Manuscript`, `CoAuthorConfirmation`, `ReviewerInvitation`, `Review`, `EditorDecision`, and `Publication` — carry the same four envelope fields: `id` (a server-minted UUID with no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits), and `version` (an integer that starts at 1 on creation and is incremented by one on every mutation that changes the resource). Two entities — `PlagiarismCheck` and `AuditLog` — are write-once event records; they carry `id` and `created_at` only, and neither `updated_at` nor `version` is present on them.

### 2.5. Validation Priority

When multiple validation checks would reject the same request, they are evaluated in a fixed order so that the rejection always identifies the first failing concern. The order is: authentication of headers (`ERR_AUTH_REQUIRED`), role authorization (`ERR_FORBIDDEN`), path-resource existence resolved left to right (`ERR_NOT_FOUND`), foreign-key existence inside the request body (`ERR_NOT_FOUND`), state-machine permissibility of the requested transition (`ERR_INVALID_STATE`), optimistic-concurrency check against the supplied `version` (`ERR_VERSION_CONFLICT`), and only then the business-rule checks listed in §3. Within the business-rule tier, endpoint-specific checks (ORCID verification, declaration completeness, conflict-of-interest scoring, topic match, deadlines, review minimums, list-disjointness, reviewer load, and editor-window overlap) are evaluated in the order in which §3 introduces them per endpoint.

### 2.6. Optimistic Concurrency Control

Every mutation endpoint accepts an optional `version` field in its request body. When the caller supplies it, the server compares the supplied value against the stored `version` of the target entity; a mismatch — including a supplied value that is stale, ahead, or negative — is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When the caller omits `version`, the OCC check is skipped and the mutation proceeds against whatever the current row holds. A successful mutation increments the stored `version` by one and refreshes `updated_at` to the server's current instant.

### 2.7. Nested Path Resolution

Endpoints with multi-segment paths (for example, `coauthor-confirmations` nested under a manuscript, or `invitations` nested under a manuscript, or `decisions` nested under a manuscript) resolve their path parameters left to right. The outer `Manuscript` must exist first; only then is the inner `CoAuthorConfirmation`, `ReviewerInvitation`, or `EditorDecision` resolved. A missing outer resource produces `ERR_NOT_FOUND` and the inner lookup is never attempted; a missing inner resource produces `ERR_NOT_FOUND` once the outer has been confirmed. The same left-to-right rule governs `/publications/{id}/...` paths: the `Publication` must exist before any sub-action is considered.

### 2.8. Hierarchical State Cascades

A small number of operations mutate more than one entity in a single atomic step, and the cascade is part of the contract — not an optimization. Three principal patterns recur:

- When the last `CoAuthorConfirmation` for a `Manuscript` flips from `PENDING` to `CONFIRMED`, the `Manuscript` itself advances from `AWAITING_COAUTHOR` to `SUBMITTED`; conversely, the first decline flips the `Manuscript` to `WITHDRAWN` and forces every still-`PENDING` sibling confirmation to `DECLINED` with a server-clock `responded_at`.
- When the editor-in-chief finalizes an `EditorDecision`, the parent `Manuscript` transitions to `ACCEPTED`, `REJECTED`, or `REVISION_REQUIRED` depending on `final_decision`; on a revision verdict, `revision_deadline_at` is computed and pinned in the same transaction.
- When a `Publication` reaches `PUBLISHED`, the parent `Manuscript` cascades from `IN_PRODUCTION` to `PUBLISHED` and copies the `Publication.doi` and `Publication.issue_label` onto the `Manuscript`'s `doi` and `issue_label` fields. Symmetrically, when the editor-in-chief retracts a published manuscript, the `Publication.status` cascades to `RETRACTED` and every entry in `indexing_status` is set to `FAILED`.

Each entity touched by a cascade — parent and child alike — has its own `version` incremented and its own `updated_at` refreshed. Withdrawal of a `Manuscript` in `SUBMITTED` or `UNDER_REVIEW` is itself a cascade: every still-`PENDING` `ReviewerInvitation` at the current `revision_round` is set to `WITHDRAWN`, and every `DRAFT` or `SUBMITTED` `Review` at that round is set to `SUPERSEDED`.

### 2.9. Numeric Precision and Rounding

Scored numeric outputs follow domain-specific precision rules. The `aggregate_score` on an `EditorDecision` is computed to two decimal places using round-half-up at every rounding step. The conflict-of-interest score `coi_score` and the reviewer-match score `match_score` on a `ReviewerInvitation` are integers in the closed interval from 0 to 100 — the result of a final cap that clips any raw value below 0 to 0 and any raw value above 100 to 100. The `similarity_percent` recorded on a `PlagiarismCheck` is stored to one decimal place. Timestamps are millisecond-precision.

### 2.10. Audit Logging

Every state transition and every administratively significant action produces an `AuditLog` row. The audit row carries `actor_role` and `actor_id` snapshotted from `X-User-Role` and `X-User-ID`, the `entity` name and `entity_id` it affected, an `action` token (such as `MANUSCRIPT_SUBMITTED`, `ASSOCIATE_ASSIGNED`, `DECISION_FINALIZED`, `INVITATION_EXPIRED`, `REVISION_TIMEOUT_AUTO_WITHDRAW`, `MANUSCRIPT_PUBLISHED`, `RETRACTED`), the `from_state` and `to_state` of the transition (both null for non-transition events), and a free-form `details` object for any structured context. Audit rows are append-only and carry only `id` and `created_at` from the common envelope.

## 3. Business Logic & Workflows

### 3.1. Author Registration and ORCID Binding

Authors enter the system through registration, where `full_name`, `email`, and `institution` are required and `orcid_id` and `recent_collaborator_ids` are optional. The `email` of an `Author` is globally unique among `Author` rows; the `orcid_id`, when supplied, must match the canonical `0000-0000-0000-0000` shape (four groups of four digits separated by hyphens) and must be unique among rows that supply one. A freshly registered author always has `orcid_verified` set to false. ORCID verification is driven by an external system: the platform receives an event carrying the `author_id` and `orcid_id`, and when the supplied `orcid_id` matches the stored value the system flips `orcid_verified` to true. Authors whose `orcid_verified` remains false cannot submit a manuscript; the attempt is rejected with `ERR_ORCID_NOT_VERIFIED`. The `recent_collaborator_ids` array — a list of other `Author.id` values the author co-published with in the last thirty-six months — is later consumed by the conflict-of-interest scorer.

### 3.2. Manuscript Drafting, Co-author Confirmation, and Submission

A `Manuscript` is created in `DRAFT` by the corresponding author. The draft must carry `title`, `corresponding_author_id`, `topic_tag`, `review_mode` (`SINGLE_BLIND`, `DOUBLE_BLIND`, or `OPEN`), `manuscript_file_uri`, and all three declarations — `declaration_coi`, `declaration_funding`, and `declaration_ethics`. The `topic_tag` must match the lower-snake-case shape `[a-z0-9_]+`. Optional inputs at creation are `co_author_ids` (an ordered list of `Author.id` values for non-corresponding co-authors), `supplementary_file_uris`, `suggested_reviewer_ids`, and `excluded_reviewer_ids`. At creation, the system rejects `co_author_ids` that either contains the `corresponding_author_id` itself or has duplicate entries — both shapes return `ERR_COAUTHOR_LIST_INVALID`. The `suggested_reviewer_ids` and `excluded_reviewer_ids` arrays must be disjoint; any shared identifier returns `ERR_REVIEWER_LISTS_OVERLAP`.

Submitting a `DRAFT` manuscript is the corresponding author's action; the optional `version` field on the request body enables OCC. At submit time the corresponding author must have `orcid_verified=true` (otherwise `ERR_ORCID_NOT_VERIFIED`), all three declaration fields must be non-empty, and `manuscript_file_uri` must be non-empty (otherwise `ERR_DECLARATION_INCOMPLETE`). Two branches diverge on the contents of `co_author_ids`. When `co_author_ids` is non-empty, the manuscript transitions from `DRAFT` to `AWAITING_COAUTHOR`, one `CoAuthorConfirmation` row is created per co-author with `status=PENDING`, and an audit row with action `MANUSCRIPT_SUBMITTED` is appended. When `co_author_ids` is empty, the manuscript transitions directly from `DRAFT` to `SUBMITTED`, a plagiarism check is requested from the external service (recorded later as a `PlagiarismCheck` row via the plagiarism-result event), and the same `MANUSCRIPT_SUBMITTED` audit entry is appended.

Each co-author then responds independently — confirming or declining their participation by acting on the confirmation row whose `author_id` matches `X-User-ID`. A confirmation sets `responded_at` to the server clock. When the last `PENDING` sibling flips to `CONFIRMED`, the manuscript advances from `AWAITING_COAUTHOR` to `SUBMITTED` and a plagiarism check is requested. When any sibling declines, the manuscript transitions to `WITHDRAWN`: every still-`PENDING` sibling is set to `DECLINED` with `responded_at=now`, and an audit row with action `COAUTHOR_DECLINED_AUTO_WITHDRAW` is appended. The two confirmation branches are symmetrical in their atomicity guarantee — when two co-authors confirm and decline simultaneously while the last sibling is still pending, the manuscript transitions exactly once: only one of `SUBMITTED` or `WITHDRAWN` can win, and the loser receives `ERR_INVALID_STATE`.

A withdrawal initiated by the author is admissible from `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW`. From `DRAFT` no cascade is needed and only an audit row with action `WITHDRAWN_BY_AUTHOR` is appended. From `SUBMITTED`, every still-`PENDING` `ReviewerInvitation` at the current `revision_round` is set to `WITHDRAWN`. From `UNDER_REVIEW`, the same invitation cascade applies, and additionally every `DRAFT` or `SUBMITTED` `Review` at the current `revision_round` is set to `SUPERSEDED`.

### 3.3. Plagiarism Screening

Once a manuscript reaches `SUBMITTED`, the external plagiarism service eventually reports back. The report supplies the `manuscript_id`, a `similarity_percent` between 0 and 100, and a `report_uri` pointing at the detailed result. The system creates a `PlagiarismCheck` row pinned to the manuscript's current `revision_round` and computes `result`: when `similarity_percent` is at least 25.0, the result is `FAIL`; when it is strictly less than 25.0, the result is `PASS`. The boundary is inclusive on the `FAIL` side, so a similarity of exactly 25.0 fails. The latest `plagiarism_similarity` is mirrored onto the parent `Manuscript`'s `plagiarism_similarity` field as a convenience for editor dashboards.

### 3.4. Section-Editor Pre-Screening, Desk Rejection, and Associate Assignment

The editor-in-chief assigns a section editor to a submitted manuscript by supplying `section_editor_id` on the assignment request; the field is written to `Manuscript.section_editor_id`. The section editor then exercises one of two outgoing transitions from `SUBMITTED`. The first is desk-rejection: the section editor must have already been assigned to the manuscript, and either the latest `PlagiarismCheck.result` must be `FAIL` or the request body must supply a non-empty `reason` string. A desk-reject call that meets neither condition is rejected with `ERR_DESK_REJECT_REASON_REQUIRED`. A successful desk-reject transitions the manuscript to `DESK_REJECTED` and emits an IM notification event.

The second transition out of `SUBMITTED` is associate-editor assignment. The section editor supplies `associate_editor_id` on the request body. The candidate must be an `Editor` row whose `role` is `ASSOCIATE_EDITOR` and whose `topic_tags` array contains the manuscript's `topic_tag`; a mismatch returns `ERR_EDITOR_TOPIC_MISMATCH`. The latest `PlagiarismCheck.result` for the manuscript must be `PASS`. No `ReviewerInvitation` rows may yet exist for this manuscript at the current `revision_round`. And — critically — the candidate associate editor must not already have an open assignment-acceptance window on a different manuscript. That window is defined as the five-day interval starting at `associate_assigned_at` and ending at `associate_window_end_at`; two manuscripts whose windows overlap on the same associate editor are rejected with `ERR_EDITOR_WINDOW_OVERLAP`. A successful assignment writes `associate_editor_id`, stamps `associate_assigned_at` to the server clock, sets `associate_window_end_at` to five days after `associate_assigned_at`, and advances the manuscript from `SUBMITTED` to `UNDER_REVIEW`. An `ASSOCIATE_ASSIGNED` audit row is appended.

Two simultaneous associate-editor finalizations and reassignments serialize on the manuscript's `version`: exactly one outcome wins, and the loser — who attempted to act on an associate-editor seat that has since changed — receives `ERR_INVALID_STATE`.

### 3.5. Reviewer Invitation, Conflict-of-Interest Scoring, and Acceptance Capacity

The associate editor builds a reviewer panel by issuing invitations one reviewer at a time. The invitation request carries the candidate `reviewer_id` and the system materializes the `ReviewerInvitation` row, copying the manuscript's current `revision_round` and setting `response_deadline_at` to seven days after the server clock. Before persisting the row the system computes two scores and pins them.

The conflict-of-interest score `coi_score` is the sum of three independent signal penalties. The first signal — co-authorship — fires when any author in the manuscript's author set (the corresponding author plus the `co_author_ids` list) has the candidate reviewer's `id` in their own `recent_collaborator_ids` array, or the candidate reviewer has any of those authors' `id`s in the reviewer's `recent_collaborator_ids` array; this signal contributes a penalty of 60. The second signal — same-institution — fires when any author's `institution` string equals the reviewer's `institution`; this signal contributes a penalty of 30. The third signal — author-excluded — fires when the candidate reviewer's `id` appears in the manuscript's `excluded_reviewer_ids`; this signal contributes a penalty of 100. The raw sum is then capped: `coi_score` is the smaller of the raw sum and 100. An invitation is rejected with `ERR_REVIEWER_CONFLICT` when `coi_score` is at least 50. The author-excluded signal alone (the candidate reviewer's `id` in `excluded_reviewer_ids` with no other signal firing) yields the distinct error `ERR_REVIEWER_EXCLUDED_BY_AUTHOR` instead — this is the only-signal case is the discriminator.

The reviewer-match score `match_score` ranks candidates by topical fit and workload. Three inputs drive it: a tag-match indicator equal to 1 when the manuscript's `topic_tag` appears in the reviewer's `expertise_tags` array and 0 otherwise; a suggested-bonus indicator equal to 1 when the reviewer's `id` appears in the manuscript's `suggested_reviewer_ids` and 0 otherwise; and a load penalty equal to the reviewer's current `active_assignments` count. The raw match value is the tag-match indicator multiplied by 60, plus the suggested-bonus indicator multiplied by 30, minus the load penalty multiplied by 10. The final `match_score` clamps the raw value into the closed interval from 0 to 100: any negative raw value becomes 0, and any value above 100 becomes 100. Both `coi_score` and `match_score` are pinned onto the `ReviewerInvitation` at creation time and never recomputed.

A second invitation for the same reviewer on the same manuscript at the same `revision_round` is rejected; the first-writer-wins on the `(manuscript_id, reviewer_id, revision_round)` tuple and the loser receives `ERR_INVITATION_ALREADY_EXISTS`.

A reviewer accepts or declines from the row whose `reviewer_id` matches `X-User-ID`. Acceptance is admissible only while the manuscript is in `UNDER_REVIEW` and the current server clock is at or before `response_deadline_at`; a clock past the deadline returns `ERR_INVITATION_DEADLINE_PASSED`. Acceptance is also bounded by reviewer capacity: a reviewer's `active_assignments` counts the `ReviewerInvitation` rows the reviewer has accepted whose paired `Review` has not yet been submitted, and accepting one more invitation must leave that count at most three. Said differently, the review interval is the half-open window from `accept_time` up to but not including `submit_time`, and the count of overlapping windows on a single reviewer must not exceed three. An acceptance that would push the count past three is rejected with `ERR_REVIEWER_OVERLOADED`. On a successful acceptance, the system creates a `Review` row in `DRAFT` with `review_deadline_at` set to twenty-one days after the server clock, copies the `manuscript_id` and `revision_round` onto the `Review` for query convenience, and increments the reviewer's `active_assignments` by one. A decline simply sets the invitation to `DECLINED` and appends an `INVITATION_DECLINED` audit row. Invitations that the reviewer never answers expire automatically during the deadline sweep, transitioning from `PENDING` to `EXPIRED` once the server clock has moved past `response_deadline_at`. The associate editor may also withdraw an invitation that is still `PENDING`, in which case the row transitions to `WITHDRAWN`; the caller must own the associate-editor seat — `Manuscript.associate_editor_id` must equal `X-User-ID`.

### 3.6. Reviewing and Submission of Reviews

A `Review` begins life as `DRAFT` with its `invitation_id` pointing back at the originating `ReviewerInvitation`. The reviewer edits the row through partial updates, setting `rating`, `recommendation`, `comments_to_author`, and `comments_to_editor`; `rating` is an integer at least 1 and at most 5, and `recommendation` is one of `ACCEPT`, `MINOR_REVISION`, `MAJOR_REVISION`, or `REJECT`. Submission is admissible only when the parent manuscript is still in `UNDER_REVIEW` and when the `reviewer_id` on the parent invitation matches `X-User-ID`. All four review fields — `rating`, `recommendation`, `comments_to_author`, `comments_to_editor` — must be set; `rating` must lie in the closed interval from 1 to 5, `recommendation` must lie in the enumerated set, and both comment strings must be non-empty. A submission that fails any of these checks is rejected with `ERR_REVIEW_INCOMPLETE`. A successful submit transitions the review from `DRAFT` to `SUBMITTED`, stamps `submitted_at` with the server clock, and decrements the reviewer's `active_assignments` by one.

A `Review` may also enter `SUPERSEDED` without the reviewer's action: when the parent manuscript transitions to `REVISION_SUBMITTED` at a higher `revision_round`, every prior-round `DRAFT` or `SUBMITTED` review is set to `SUPERSEDED`; and when the parent manuscript is withdrawn from `UNDER_REVIEW`, every `DRAFT` or `SUBMITTED` review at the current round is set to `SUPERSEDED`. Both supersession paths produce a `REVIEW_SUPERSEDED` audit row, and the auto-supersession of a `DRAFT` review clears its `submitted_at` back to null.

### 3.7. Editor Decision Aggregation and Finalization

Once at least two reviews are in `SUBMITTED` at the current `revision_round`, the associate editor creates an `EditorDecision`. The creation request carries `recommendation_from_associate` — one of `ACCEPT`, `MINOR_REVISION`, `MAJOR_REVISION`, `REJECT`, or `TRANSFER` — and the decision is created in `DRAFT`. The associate editor then moves the decision to `RECOMMENDED`, which is admissible only when the caller owns the associate-editor seat (`Manuscript.associate_editor_id` equals `X-User-ID`) and at least two submitted reviews exist at the current round. A recommend call with fewer than two submitted reviews is rejected with `ERR_INSUFFICIENT_REVIEWS`.

The recommend step runs two aggregations on the submitted reviews of the current round, considering only reviews whose `status` is `SUBMITTED` and excluding any with `status` of `DRAFT` or `SUPERSEDED`, ordered by `submitted_at` ascending.

The first aggregation produces the `aggregated_category`. Each submitted review's `recommendation` is mapped to one of four positions — `ACCEPT` first, `MINOR_REVISION` second, `MAJOR_REVISION` third, `REJECT` fourth. The system counts the reviews falling into each of the four positions, then picks the position with the highest count. When two or more positions tie at the highest count, the tie is broken by preferring the earlier position in the listed order — that is, `ACCEPT` beats `MINOR_REVISION`, which beats `MAJOR_REVISION`, which beats `REJECT`. The category corresponding to the winning position is written to `EditorDecision.aggregated_category`. When the associate editor's own `recommendation_from_associate` is `TRANSFER`, the aggregated category is reported as `ACCEPT` (the `aggregated_category` field is constrained to the four reviewer-facing categories and does not include `TRANSFER`).

The second aggregation produces the numeric `aggregate_score`. Each submitted review contributes a weighted rating: the reviewer's `rating` (an integer from 1 to 5) is multiplied by a weight determined by the reviewer's `recommendation`. The weights are 1.215 for `ACCEPT`, 1.005 for `MINOR_REVISION`, 0.835 for `MAJOR_REVISION`, and 0.605 for `REJECT`. The order of operations is pinned: first, each reviewer's weighted rating is rounded individually to two decimal places using round-half-up; second, those rounded per-reviewer values are summed and divided by the number of submitted reviews; third, the result of that division is again rounded to two decimal places using round-half-up. This order — round per reviewer first, then average, then round the average — is the official order; computing the unrounded sum first and rounding only at the end produces different `aggregate_score` values for the same input set and is not the convention. The final two-decimal `aggregate_score` is written to the decision row. The recommend step also compiles `compiled_reviewer_comments` by concatenating the `comments_to_author` strings from the submitted reviews in `submitted_at` ascending order.

The editor-in-chief then finalizes the decision. The finalize request carries `final_decision` (one of `ACCEPT`, `MINOR_REVISION`, `MAJOR_REVISION`, `REJECT`, or `TRANSFER`) and a non-empty `decision_letter_body`. The decision must already be `RECOMMENDED`, the round on the decision must equal the current `revision_round` of the manuscript, and at least two submitted reviews must still be present at that round. A mismatch between `EditorDecision.revision_round` and `Manuscript.revision_round` returns `ERR_REVIEW_ROUND_MISMATCH`. The finalize step sets `EditorDecision.status` to `FINALIZED`, stamps `finalized_at`, and cascades the manuscript: a `final_decision` of `ACCEPT` advances `UNDER_REVIEW → ACCEPTED`; a `final_decision` of `REJECT` advances `UNDER_REVIEW → REJECTED`; and a `final_decision` of `MINOR_REVISION` or `MAJOR_REVISION` advances `UNDER_REVIEW → REVISION_REQUIRED`. A `DECISION_FINALIZED` audit row is appended. The editor-in-chief's `final_decision` may legitimately diverge from the previously computed `aggregated_category`; both values remain on the decision for audit.

Two race shapes are notable. When the editor-in-chief finalizes while the author submits a revision against the same `revision_round`, first-writer-wins on the manuscript's `status` flip out of `UNDER_REVIEW`: if the FINALIZE write commits first, the revision attempt finds the manuscript no longer in `UNDER_REVIEW` and receives `ERR_INVALID_STATE`; if the revision write commits first, the manuscript's `revision_round` has already incremented and the FINALIZE call now references a stale round, receiving `ERR_REVIEW_ROUND_MISMATCH`.

### 3.8. Revision Loop and Deadline Enforcement

When a finalize lands `REVISION_REQUIRED`, the system computes a `revision_deadline_at` and writes it to the manuscript. The delta from the finalize instant is thirty days for `MINOR_REVISION` and sixty days for `MAJOR_REVISION`; the deadline is the finalize instant plus the appropriate delta. The author is notified by an IM event and a `REVISION_REQUESTED` audit row is appended. The author submits a revised manuscript by supplying `response_letter` and `revised_file_uri` on the request body. Submission is admissible only while the server clock is at or before `revision_deadline_at`; a clock past the deadline is rejected with `ERR_REVISION_DEADLINE_PASSED`. A successful revision submission increments the manuscript's `revision_round` by one, supersedes every prior-round `DRAFT` or `SUBMITTED` review, and advances the manuscript from `REVISION_REQUIRED` to `REVISION_SUBMITTED`. A `REVISION_SUBMITTED` audit row is appended.

The associate editor then opens the new round by issuing at least one fresh invitation through the reinvite-reviewers action, which carries an array of `reviewer_ids`. The action requires at least one new `ReviewerInvitation` to be created at the new `revision_round` and transitions the manuscript from `REVISION_SUBMITTED` back to `UNDER_REVIEW`. A `NEW_ROUND_STARTED` audit row is appended.

The deadline sweep is the system's automatic enforcer. When the platform admin runs the sweep, two automatic transitions occur. First, any `ReviewerInvitation` still in `PENDING` whose `response_deadline_at` has passed is moved to `EXPIRED`, with an `INVITATION_EXPIRED` audit row. Second, any `Manuscript` in `REVISION_REQUIRED` whose `revision_deadline_at` has passed is moved to `WITHDRAWN`, with a `REVISION_TIMEOUT_AUTO_WITHDRAW` audit row. The logical clock can be advanced through the test-driving clock-advance capability, which accepts a `to` instant and moves the server's notion of "now" forward to that value.

### 3.9. Production, Proof Review, Publication, and Retraction

Once a manuscript is `ACCEPTED`, the platform admin starts production by creating a `Publication` row. The creation request carries `copy_edit_uri`, `proof_uri`, `issue_label`, and an optional `indexing_targets` array drawn from the set `{PUBMED, WEB_OF_SCIENCE, SCOPUS}`. Exactly one `Publication` can exist per `Manuscript`; a second creation race is serialized on the unique constraint and the loser receives `ERR_PUBLICATION_ALREADY_EXISTS`. The new row begins in `COPY_EDITING` and the parent manuscript cascades from `ACCEPTED` to `IN_PRODUCTION`; a `PRODUCTION_STARTED` audit row is appended.

The publication then walks a four-step pipeline. From `COPY_EDITING` the platform admin sends the proof to the author — admissible only when both `copy_edit_uri` and `proof_uri` are non-empty — and the row advances to `PROOF_REVIEW`, with a `PROOF_SENT` audit row. From `PROOF_REVIEW` the corresponding author (the caller whose `X-User-ID` equals `Manuscript.corresponding_author_id`) approves the proof; the system asks the external DOI registry to mint a DOI for the publication and, on receipt of the doi-mint event with the `publication_id` and `doi`, writes `Publication.doi` and advances the row to `ONLINE_FIRST`. From `ONLINE_FIRST` the platform admin issues the publication: admissibility requires `doi` already present and `issue_label` non-empty (otherwise `ERR_PUBLICATION_NOT_READY`). On success, `published_at` is stamped, every entry in `indexing_status` is initialized to `PENDING` for each target listed in `indexing_targets`, and the manuscript cascades from `IN_PRODUCTION` to `PUBLISHED` — at which point the `Publication.doi` and `Publication.issue_label` are copied to the manuscript's own `doi` and `issue_label`. The system later records each external indexer's acknowledgement through an indexing-ack event carrying the `publication_id`, the `target`, and the `status` (`ACK` or `FAILED`), and the appropriate entry in `indexing_status` is updated.

Retraction is the editor-in-chief's prerogative. A retract call on a `PUBLISHED` manuscript transitions the manuscript to `RETRACTED`, cascades the `Publication.status` from `PUBLISHED` to `RETRACTED`, and sets every entry in the `Publication.indexing_status` map to `FAILED`. A `RETRACTED` audit row and a `PUBLICATION_RETRACTED` audit row are both appended.

## 4. Endpoint Definitions

All endpoints below are mounted directly under the API root using the paths shown. As a general rule, endpoints that create a brand-new resource (the various `POST` collection paths) return HTTP 201 on success; endpoints that mutate an existing resource — including all state-transition actions — return HTTP 200. All errors follow §2.2's error envelope with the HTTP statuses listed in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /authors | Register an author | PlatformAdmin, Author |
| GET | /authors/{id} | Fetch one author | PlatformAdmin, Author, EditorInChief, SectionEditor, AssociateEditor |
| GET | /authors | List authors (pagination) | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor |
| POST | /reviewers | Add a reviewer to the pool | PlatformAdmin |
| GET | /reviewers/{id} | Fetch one reviewer | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor, Reviewer |
| GET | /reviewers | List reviewers, filter by expertise tag or status | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor |
| POST | /editors | Register an editor | PlatformAdmin |
| GET | /editors/{id} | Fetch one editor | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor |
| GET | /editors | List editors filterable by role and topic_tag | PlatformAdmin, EditorInChief, SectionEditor |
| POST | /manuscripts | Create a manuscript in DRAFT | Author |
| GET | /manuscripts/{id} | Fetch one manuscript | PlatformAdmin, Author, EditorInChief, SectionEditor, AssociateEditor |
| GET | /manuscripts | List manuscripts filterable by status, topic_tag, corresponding_author_id | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor |
| POST | /manuscripts/{id}/submit | Submit a DRAFT manuscript to enter the review pipeline | Author |
| POST | /manuscripts/{id}/withdraw | Author withdraws the manuscript before publication | Author |
| POST | /manuscripts/{id}/coauthor-confirmations/{cid}/confirm | Co-author confirms participation | Author |
| POST | /manuscripts/{id}/coauthor-confirmations/{cid}/decline | Co-author declines participation | Author |
| GET | /manuscripts/{id}/coauthor-confirmations | List co-author confirmations | PlatformAdmin, Author, EditorInChief, SectionEditor, AssociateEditor |
| POST | /manuscripts/{id}/assign-section-editor | Editor-in-chief assigns a section editor | EditorInChief |
| POST | /manuscripts/{id}/desk-reject | Section editor desk-rejects (transitions to DESK_REJECTED) | SectionEditor |
| POST | /manuscripts/{id}/assign-associate | Section editor assigns associate editor and starts review | SectionEditor |
| POST | /manuscripts/{id}/invitations | Associate editor invites a reviewer at current revision_round | AssociateEditor |
| GET | /manuscripts/{id}/invitations | List invitations for a manuscript | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor |
| POST | /manuscripts/{mid}/invitations/{id}/accept | Reviewer accepts invitation | Reviewer |
| POST | /manuscripts/{mid}/invitations/{id}/decline | Reviewer declines invitation | Reviewer |
| POST | /manuscripts/{mid}/invitations/{id}/withdraw | Associate editor withdraws a pending invitation | AssociateEditor |
| GET | /reviews/{id} | Fetch one review | PlatformAdmin, EditorInChief, SectionEditor, AssociateEditor, Reviewer |
| PATCH | /reviews/{id} | Reviewer updates DRAFT review fields | Reviewer |
| POST | /reviews/{id}/submit | Reviewer submits the review | Reviewer |
| POST | /manuscripts/{id}/decisions | Associate editor creates a DRAFT decision for the current revision_round | AssociateEditor |
| POST | /manuscripts/{mid}/decisions/{id}/recommend | Associate editor moves decision DRAFT to RECOMMENDED; runs aggregation calculations | AssociateEditor |
| POST | /manuscripts/{mid}/decisions/{id}/finalize | Editor-in-chief finalizes the decision | EditorInChief |
| POST | /manuscripts/{id}/revisions | Author submits a revised manuscript (response letter + revised file) | Author |
| POST | /manuscripts/{id}/reinvite-reviewers | Associate editor starts the next round by creating at least one new invitation; transitions REVISION_SUBMITTED to UNDER_REVIEW | AssociateEditor |
| POST | /manuscripts/{id}/publications | PlatformAdmin starts production: create Publication COPY_EDITING | PlatformAdmin |
| POST | /publications/{id}/send-proof | PlatformAdmin sends proof to author | PlatformAdmin |
| POST | /publications/{id}/approve-proof | Corresponding author approves the proof; DOI is minted | Author |
| POST | /publications/{id}/publish-issue | PlatformAdmin issues publication and triggers indexing | PlatformAdmin |
| POST | /manuscripts/{id}/retract | Editor-in-chief retracts a published manuscript | EditorInChief |
| GET | /audit-logs | List audit log entries (filter by entity, entity_id, action) | PlatformAdmin, EditorInChief |
| POST | /_clock/advance | Advance server clock for tests (drives invitation/revision deadline transitions) | PlatformAdmin |
| POST | /_sweep/run | Run deadline sweep: expire overdue invitations; auto-withdraw overdue REVISION_REQUIRED manuscripts | PlatformAdmin |
| POST | /_events/orcid-verified | External ORCID system confirms an author's orcid_id is bound and verified | PlatformAdmin |
| POST | /_events/plagiarism-result | External plagiarism service reports a similarity percentage | PlatformAdmin |
| POST | /_events/doi-mint | External DOI registry reports the minted DOI for a Publication in ONLINE_FIRST | PlatformAdmin |
| POST | /_events/indexing-ack | External indexing database (PubMed/WoS/Scopus) acknowledges a publication | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_ORCID_NOT_VERIFIED | 422 |
| ERR_DECLARATION_INCOMPLETE | 422 |
| ERR_REVIEWER_CONFLICT | 422 |
| ERR_REVIEWER_EXCLUDED_BY_AUTHOR | 422 |
| ERR_EDITOR_TOPIC_MISMATCH | 422 |
| ERR_INVITATION_DEADLINE_PASSED | 422 |
| ERR_REVISION_DEADLINE_PASSED | 422 |
| ERR_INSUFFICIENT_REVIEWS | 422 |
| ERR_DESK_REJECT_REASON_REQUIRED | 422 |
| ERR_REVIEW_INCOMPLETE | 422 |
| ERR_PUBLICATION_NOT_READY | 422 |
| ERR_COAUTHOR_LIST_INVALID | 422 |
| ERR_REVIEWER_LISTS_OVERLAP | 422 |
| ERR_REVIEW_ROUND_MISMATCH | 409 |
| ERR_INVITATION_ALREADY_EXISTS | 409 |
| ERR_PUBLICATION_ALREADY_EXISTS | 409 |
| ERR_VALIDATION | 400 |
| ERR_REVIEWER_OVERLOADED | 422 |
| ERR_EDITOR_WINDOW_OVERLAP | 422 |
