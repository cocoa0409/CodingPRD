# Drug Trial Ethics API — Product Requirements Document

## 1. Introduction

Clinical-trial ethics review is the gating workflow between a sponsor's interest in studying a new investigational drug and the first dose administered to a human subject. The committees that perform this review operate under sharp procedural constraints: applications must be screened for completeness before review; voting members must be free of conflicts of interest with the sponsor; meetings must give every member enough lead time to read the materials; quorum rules must be satisfied before any resolution is recognized; and every approval, rejection, and rectification must be auditable years later when a regulator asks why a particular trial proceeded.

This document specifies the API for the **Drug Trial Ethics** platform — the system of record for ethics-review applications, committee composition, review meetings, voting, resolutions, applicant rectifications, and annual continuing review. The platform supports five user roles spanning principal investigators, committee staff, the committee chair, the voting membership, and a read-only regulatory observer. It enforces segregation of duties between secretarial scheduling, chair-led tally, and member-led voting; freezes the materials a committee actually voted on (so a late-arriving submission revision cannot retroactively change the basis of a resolution); and emits a continuous audit trail that downstream regulatory and IM systems consume.

The remainder of this document defines the global request/response contract, the cross-cutting principles that govern concurrency, freezing, and timing, the per-workflow business logic, the full endpoint catalogue, and the error codes the API returns.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two case-sensitive headers: `X-User-ID` (the caller's identifier) and `X-User-Role` (the caller's role). Both headers must be present and non-empty; a missing or empty header yields `ERR_AUTH_MISSING` with HTTP 401. An `X-User-Role` value outside the declared set yields `ERR_AUTH_INVALID` with HTTP 401. The declared roles are exactly: `Applicant`, `Secretary`, `Chairperson`, `CommitteeMember`, and `RegulatoryWatcher`. When a caller is authenticated and authorized for the endpoint by role but is not the resource owner or not in scope for the specific resource, the response is `ERR_FORBIDDEN` with HTTP 403.

The five roles bind `X-User-ID` to underlying entities differently:

- When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque principal-investigator identifier not tied to any persisted entity. The server records it as `applicant_id` on the `Application` it owns; thereafter, every write action that names a specific application (submitting for pre-screen, uploading a new submission version, responding to a rectification, filing an annual report) compares the addressed `Application`'s `applicant_id` to `X-User-ID` and rejects mismatches with `ERR_FORBIDDEN`.
- When `X-User-Role` is `Secretary`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, in `AuditLog.actor_id` when the secretary performs an audited action) but does not compare it to any entity's `id`.
- When `X-User-Role` is `Chairperson`, `X-User-ID` is the `id` of the acting `CommitteeMember`; the member referenced must currently be active. Ownership checks on any action a chair performs compare against this `CommitteeMember.id`.
- When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting `CommitteeMember`; attendance and vote endpoints compare the resource's `member_id` to `X-User-ID`.
- When `X-User-Role` is `RegulatoryWatcher`, `X-User-ID` is an opaque external-observer identifier not tied to any persisted entity; this role has read-only access to applications, resolutions, audit logs, and annual reports.

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

All list endpoints accept two pagination query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0 and may not be negative. Both parameters appear in the `meta` envelope of every list response, alongside the resolved `total_count` and a `has_more` boolean indicating whether more rows exist beyond the current page. List endpoints return rows in ascending order of `created_at`; ties are broken by ascending `id`.

### 2.4. Common Resource Properties and Auditability

Every persisted entity carries a server-minted `id` (a UUID, with no type prefix and no embedded semantics) and an immutable `created_at` timestamp (ISO 8601 UTC with three fractional digits). Mutable entities — `Application`, `Submission`, `CommitteeMember`, `Meeting`, `AgendaItem`, `Resolution`, `Rectification`, and `AnnualReport` — additionally carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 on creation and increments by exactly 1 on every persisted mutation. Three entities are append-only and therefore carry only `id` and `created_at`, with no `updated_at` or `version` field: `ConflictDeclaration`, `AttendanceConfirmation`, `Vote`, and `AuditLog`. The `AuditLog` resource exists to keep a permanent record of every review decision, member recusal, and outbound regulatory or IM sync event: each entry captures the `actor_role` and `actor_id` taken from the request headers at the time of the audited action, the `event_type` (one of `REVIEW_DECISION`, `MEMBER_RECUSAL`, `REGULATORY_SYNC`, `IM_NOTIFICATION`), the `subject_entity` name and `subject_id`, and a domain-specific `payload` snapshot.

### 2.5. Optimistic Concurrency Control

For every mutating endpoint, the request body may carry an optional `version` field. When `version` is present, the server compares it to the persisted entity's current `version`; a mismatch yields `ERR_VERSION_CONFLICT` with HTTP 409. When `version` is omitted, the concurrency check is skipped and the mutation proceeds against the current state. Successful mutations always bump `version` by exactly 1 and refresh `updated_at`.

### 2.6. Nested Resource Path Resolution

URL paths with multiple identifier segments are resolved left to right. For example, on the annual-reports listing under an application, the path parameter `aid` names the parent application's id and is resolved first; if no application of that `id` exists, the response is `ERR_NOT_FOUND` with HTTP 404 and the inner resource is never consulted. Body foreign-key references (such as `application_id` on a submission or rectification creation) are resolved separately and yield `ERR_REFERENCE_NOT_FOUND` with HTTP 404 if the referenced row does not exist.

### 2.7. Validation Ordering

Validations are evaluated in a fixed priority order so that the same failing request always produces the same error. Authentication header presence (`ERR_AUTH_MISSING`) is checked first, followed by role-set membership (`ERR_AUTH_INVALID`); then path-parameter existence (`ERR_NOT_FOUND`); then body foreign-key resolution (`ERR_REFERENCE_NOT_FOUND`); then role-based access permission per the §1.7 RBAC matrix (`ERR_FORBIDDEN`); then identity-ownership checks that bind `X-User-ID` to the addressed resource (also `ERR_FORBIDDEN`); then state legality for mutations (`ERR_INVALID_STATE`); then the conflict-of-interest gate (`ERR_MEMBER_RECUSED`); then member-qualification checks (`ERR_MEMBER_NOT_QUALIFIED`); then temporal checks such as agenda lead time (`ERR_AGENDA_LEAD_TIME_VIOLATION`) and rectification deadlines (`ERR_RECTIFICATION_EXPIRED`); then business-constraint checks such as checklist completeness (`ERR_CHECKLIST_INCOMPLETE`), duplicate vote prevention (`ERR_DUPLICATE_VOTE`), explicit quorum assertion (`ERR_QUORUM_NOT_MET`), generic field shape (`ERR_FIELD_VALIDATION`), and annual-report invariants; and finally the optimistic concurrency check (`ERR_VERSION_CONFLICT`). Two priority pairs are subtle and worth calling out: the conflict-of-interest gate runs **before** the state legality check, so a recused member who attempts to vote on a CLOSED agenda item receives `ERR_MEMBER_RECUSED`, not `ERR_INVALID_STATE`; and the optimistic concurrency check runs **after** every business validation, so a stale `version` only surfaces when no other rule has already rejected the request.

### 2.8. Version Pinning at Agenda Publication

The platform treats the agenda-publication moment as the **freeze point** for everything a committee will actually be asked to vote on. At the instant the secretary publishes an agenda, three values are snapshotted onto every `AgendaItem` belonging to that meeting and never change thereafter: `pinned_submission_version` is set to the parent application's `current_submission_version` at that instant; `eligible_voter_count` is set to the number of active committee members with no active conflict declaration against the item's application; and `quorum_required` is computed from the eligible count by the rules in §2.9. A new submission version uploaded after publication does **not** retroactively change the agenda's pinned version; a new conflict declaration filed after publication does **not** retroactively shrink the frozen eligible voter count or quorum; and a member who resigns after publication remains a frozen-in eligible voter for that already-published item (though of course they can no longer cast a vote because their `is_active` flag is false at vote time).

### 2.9. Quorum Composition

Legal quorum is computed at agenda publication as follows. First, the system counts active eligible members — committee members whose administrative `status` is `ACTIVE` and whose current logical-clock time falls in the half-open interval starting at `term_start` and ending before `term_end`, excluding any member who has an active `ConflictDeclaration` for the agenda item's `application_id`. This eligible count is multiplied by 67 percent, rounded up to the next whole integer using ceiling rounding, and then the larger of that value and the absolute minimum quorum of 5 voters is taken as `quorum_required`. The order is pinned: multiply percent by the eligible count first, take the ceiling next, then take the maximum with the absolute floor of 5 voters last. All quorum and vote tallies are integer-valued; there is no rounding inside the tally itself.

### 2.10. Conflict-of-Interest Protections

Two mechanisms guard against tainted votes. First, when a committee member's record lists the application's `sponsor_name` in their `affiliated_sponsors` array (e.g., employment, advisory board, equity), the system auto-detects the conflict and treats it as an active declaration with `auto_detected` set to true. Second, the secretary or the member themselves may manually file a `ConflictDeclaration` for a specific `(member_id, application_id)` pair, naming a `conflict_type` of `SPONSOR_RELATION`, `CO_AUTHOR`, or `ECONOMIC_INTEREST` together with free-text `details`. In both cases, a member with an active declaration for an application's agenda item may not vote on it, may not confirm attendance for it, and may not convene a meeting that contains it; attempts produce `ERR_MEMBER_RECUSED` with HTTP 403. The conflict gate is enforced at attendance time, at vote time, and at convener-selection time for meeting scheduling.

### 2.11. Audit, Regulatory Sync, and IM Notifications

Three side effects flow out of the platform whenever a review reaches a terminal outcome. The system writes an `AuditLog` row of `event_type` `REVIEW_DECISION` capturing the action, actor, and resolution outcome. The system emits a `REGULATORY_SYNC` audit row representing the outbound notification to the regulatory authority; this event accompanies every Application transition into `APPROVED`, `APPROVED_WITH_MOD`, `REJECTED`, `SUSPENDED`, `TERMINATED`, or `COMPLETED` (but not `NO_QUORUM` outcomes, which do not constitute regulatory decisions). The system also emits an `IM_NOTIFICATION` audit row to drive the internal IM channel for every `REVIEW_DECISION` whose outcome is a regulator-visible decision (again excluding `NO_QUORUM`). Every conflict declaration likewise produces a `MEMBER_RECUSAL` audit row.

## 3. Business Logic & Workflows

### 3.1. Application Intake, Submissions, and the Rework Loop

An `Application` is the root entity of an ethics review. The Applicant creates one by supplying the trial sponsor's organization name (`sponsor_name`, 1 to 200 characters, non-empty), the investigational drug or product name (`drug_name`, 1 to 200 characters), the clinical indication being studied (`indication`, 1 to 500 characters), the clinical trial phase, and an optional review-track selector. The trial `phase` must be one of `PHASE_I`, `PHASE_II`, `PHASE_III`, or `PHASE_IV`. The `review_track` parameter is either `STANDARD` for the periodic review channel or `EXPEDITED` for the urgent-review channel, and defaults to `STANDARD` when omitted. On creation the application enters `DRAFT` status, its `current_submission_version` begins at 0, both `approved_submission_version` and `approval_resolution_id` are null, and the server records the caller's `X-User-ID` as `applicant_id`.

Document materials live in child `Submission` rows. The Applicant uploads each version by supplying four URIs — `protocol_doc_uri` for the study protocol, `investigator_brochure_uri` for the investigator brochure, `informed_consent_uri` for the informed-consent form, and `cv_doc_uri` for the investigator CV — together with the `application_id` foreign key the URL already determines. The server assigns the new submission a `version_number` equal to one greater than the maximum existing `version_number` under that application (starting at 1 for the first submission), sets `is_current` to true on the new row, clears `is_current` on whichever sibling submission had previously been current, and updates the parent application's `current_submission_version` to match. The new submission's `checklist_complete` flag is computed by inspecting the four document URIs: it is true only when all four are non-null, non-empty strings, and false otherwise. Each new submission's `prescreen_status` starts at `PENDING` and the optional `prescreen_notes` field is null until a secretary records a rationale.

When the applicant submits the current submission for formal pre-screening, the application transitions out of `DRAFT` (or out of `REWORK_REQUIRED` if this is a rework cycle) into `PENDING_PRESCREEN`. The precondition for this transition is that the application has a current submission with `checklist_complete` true; if any required document URI is missing, the request is rejected with `ERR_CHECKLIST_INCOMPLETE`. The side effect of a successful submit is that the current submission's `prescreen_status` is set to `PENDING`. The Applicant may pass an optional `version` field in the request body for optimistic concurrency control.

Pre-screening itself is the Secretary's prerogative. The secretary supplies a `decision` field — either `PASS` or `REJECT` — and an optional `prescreen_notes` rationale. A `PASS` decision requires the current submission's `checklist_complete` to be true; on success the application advances from `PENDING_PRESCREEN` to `PENDING_REVIEW`, the current submission's `prescreen_status` is set to `PASSED`, and an audit row of `event_type` `REVIEW_DECISION` is written. A `REJECT` decision moves the application from `PENDING_PRESCREEN` to `REWORK_REQUIRED`, sets the current submission's `prescreen_status` to `REJECTED`, and likewise writes a `REVIEW_DECISION` audit row. The secretary may reject a checklist-complete submission for content reasons; the rework loop is the rectification channel before the committee ever sees the file. After `REWORK_REQUIRED`, the applicant uploads a new submission version (which auto-becomes the new current submission and resets its `prescreen_status` to `PENDING`) and re-submits, returning the application to `PENDING_PRESCREEN`.

### 3.2. Committee Composition, Member Lifecycle, and Conflict Declarations

The committee is a roster of `CommitteeMember` rows. Each row is created by the Secretary with the member's `full_name`, a required `qualification` drawn from the closed set `MEDICAL_EXPERT`, `PHARMACOLOGIST`, `ETHICIST`, `LEGAL_EXPERT`, `LAY_REPRESENTATIVE`, and `STATISTICIAN`, a `term_start` and `term_end` (both ISO 8601 UTC timestamps), and an optional `affiliated_sponsors` array listing the sponsor organization names the member is contractually connected to (defaulting to an empty list). Each member carries an administrative `status` (one of `ACTIVE`, `RESIGNED`, or `REMOVED`, defaulting to `ACTIVE` at creation) and a derived `is_active` boolean that is true exactly when the logical-clock time is at or after `term_start` and strictly before `term_end` **and** the administrative `status` equals `ACTIVE`.

Conflict-of-interest declarations are `ConflictDeclaration` rows pinning a `(member_id, application_id)` pair to a `conflict_type` and free-text `details`. Filed manually, the row's `auto_detected` flag is false; filed by the system because the application's `sponsor_name` appeared in the member's `affiliated_sponsors`, the flag is true. Every declaration emits a `MEMBER_RECUSAL` audit row. A declaration filed after a relevant agenda item has already been published does not retroactively change that item's frozen eligible voter count or quorum requirement — those numbers were locked at publication — but it will block the member from confirming attendance or casting a vote on the live item, since the conflict gate is consulted at the moment of action.

### 3.3. Meeting Scheduling, Agenda Composition, and Publication

Meetings are scheduled by the Secretary, who supplies a `meeting_type` (either `STANDARD` for periodic review or `EXPEDITED` for an urgent-review session), an ISO 8601 UTC `scheduled_at` timestamp, and the `convener_member_id` of the committee member who will chair the session. The convener must be currently `is_active` and must hold the `MEDICAL_EXPERT` qualification; violations yield `ERR_MEMBER_NOT_QUALIFIED` with HTTP 422. A member with an active conflict against any application the secretary later attempts to add to this meeting's agenda may not serve as convener for that agenda item; the conflict gate runs as part of meeting scheduling, returning `ERR_MEMBER_RECUSED`. The meeting begins life in `SCHEDULED` status with `agenda_published_at` null. The `lead_time_hours` field on a meeting is derived from `meeting_type` — 168 hours (which is 7 days) for a `STANDARD` meeting, 24 hours (which is 1 day) for an `EXPEDITED` meeting.

Before publishing the agenda, the Secretary adds one or more `AgendaItem` rows by supplying the parent `meeting_id` (determined by the URL), the `application_id` to be reviewed, a `review_kind` from the closed set `INITIAL_REVIEW`, `SECONDARY_REVIEW`, `ANNUAL_REVIEW`, `AMENDMENT_REVIEW`, and `FINAL_REPORT_REVIEW`, and optionally either an `annual_report_id` (when the item reviews a continuing-review submission) or a `rectification_id` (when the item is a secondary review of a rectified application). Every newly-added agenda item begins in `DRAFT` per-item status. At creation the item's `pinned_submission_version`, `eligible_voter_count`, and `quorum_required` are all null/unset; they are frozen only at publication.

Publishing the agenda is the moment the meeting's review materials become committee-visible. The transition from `SCHEDULED` to `AGENDA_PUBLISHED` is the Secretary's action and is gated by two preconditions: at least one `AgendaItem` must belong to the meeting, and the time gap between the meeting's `scheduled_at` and the current logical clock must be at least the meeting's required lead-time hours. The required-hours value is selected by `meeting_type` from a two-tier table — 168 hours for `STANDARD`, 24 hours for `EXPEDITED` — and is then compared as a strict inequality: the request is rejected with `ERR_AGENDA_LEAD_TIME_VIOLATION` only when the seconds remaining until the meeting are strictly less than the required hours multiplied by 3600; a meeting scheduled exactly the required-hours interval away from now is allowed. On success the meeting's `agenda_published_at` is set to the current clock time, every child `AgendaItem` moves from `DRAFT` to `PUBLISHED`, and for each item the `pinned_submission_version` is taken from the application's `current_submission_version`, the `eligible_voter_count` is taken from the active-member-minus-conflicts count, and the `quorum_required` is computed as described in §2.9 — multiply percent by the eligible count, take the ceiling, then take the maximum with 5.

When the meeting's `scheduled_at` time has been reached, the Secretary opens the session, which advances the meeting from `AGENDA_PUBLISHED` to `IN_SESSION` and every `PUBLISHED` agenda item to `OPEN_FOR_VOTING`. The precondition is that the current logical clock has reached or passed `scheduled_at`. Once every item has reached either `RESOLVED` or `CLOSED_WITHOUT_QUORUM`, the Secretary closes the meeting (advancing it to `CLOSED`). A meeting still in `SCHEDULED` status — that is, with no agenda yet published — can be cancelled outright, which moves the meeting to `CANCELLED` and cascade-deletes every child agenda item. After publication, cancellation is not available.

### 3.4. Attendance and Voting

After an agenda item enters `OPEN_FOR_VOTING`, eligible members confirm their attendance by creating an `AttendanceConfirmation` row that records the member's `member_id` and a server-stamped `confirmed_at` timestamp. Attendance confirmation is itself gated by the conflict-of-interest check: a member with an active declaration against the item's application receives `ERR_MEMBER_RECUSED`. The same member may not double-confirm, and confirmation is required only insofar as the surrounding workflow requires it; the operative check at resolution time is the count of cast votes against `quorum_required`.

Voting is the act of inserting a `Vote` row referencing the `agenda_item_id` and supplying a `vote_mode` of `APPROVE`, `APPROVE_WITH_MODIFICATION`, `REJECT`, or `DEFER`. Three protections sit around vote insertion. First, the conflict gate runs **before** the state-legality check, so a recused member who tries to vote — even on an item that has already moved out of `OPEN_FOR_VOTING` — receives `ERR_MEMBER_RECUSED` rather than `ERR_INVALID_STATE`. Second, a member may cast at most one vote per agenda item: a second insert from the same member with the same `agenda_item_id` is rejected with `ERR_DUPLICATE_VOTE`. Third, when two simultaneous votes arrive for the same agenda item and one of them is from a recused member, the recused vote is rejected with `ERR_MEMBER_RECUSED` (HTTP 403) while the non-recused vote is accepted; when the same member tries to insert two votes simultaneously on the same agenda item, the database's uniqueness constraint on `(agenda_item_id, member_id)` ensures exactly one wins and the loser receives `ERR_DUPLICATE_VOTE` (HTTP 409). When the Chairperson attempts to resolve an agenda item at the same instant a vote is being inserted that would change the tally, the resolve loses to the in-flight vote on the agenda item's `version`; the chair receives `ERR_VERSION_CONFLICT` (HTTP 409). Likewise, when the Secretary publishes an agenda while the applicant is concurrently uploading a new submission version, first-writer-wins on the application's `version`: if publish wins, the agenda freezes the older submission; if the new submission wins, the agenda publishes with the newer version, and the late writer receives `ERR_VERSION_CONFLICT`. Two simultaneous attempts to insert new submission rows on the same application also serialize on the uniqueness of `(application_id, version_number)`: the server assigns `version_number = max(existing) + 1` inside a transaction, and the loser receives `ERR_VERSION_CONFLICT`.

### 3.5. Tally, Resolution, and Outcome Mapping

When the Chairperson resolves an open agenda item, the system tallies all `Vote` rows whose `member_id` is not in the recused set for the item's `application_id` (recusal exclusions were already applied at publication when `eligible_voter_count` was frozen). The number of cast votes is compared to the `quorum_required` snapshot. If the cast count is below the required count, two possibilities branch on a query parameter: with `require_quorum` set to true, the resolve is rejected with `ERR_QUORUM_NOT_MET` (HTTP 422) and the agenda item remains `OPEN_FOR_VOTING`; without `require_quorum` (the default, omitted, or false), the resolve succeeds with a `NO_QUORUM` outcome — a `Resolution` row is created whose `outcome` is `NO_QUORUM`, the agenda item moves to `CLOSED_WITHOUT_QUORUM`, and the parent application transitions from `IN_REVIEW` to `DEFERRED` (with no rectification created).

When quorum is met, the tally counts each `vote_mode` and resolves according to a fixed precedence. The vote-counting steps are: first, if the number of `REJECT` votes is strictly more than half of the votes cast, the outcome is `REJECT`. Otherwise, if the sum of `APPROVE` and `APPROVE_WITH_MODIFICATION` votes is at least two-thirds of the votes cast (rounded up to the nearest whole vote — for example, with 7 cast votes the threshold is 5 approving votes), the outcome is one of the approval variants, broken by an explicit tie rule: when the count of `APPROVE_WITH_MODIFICATION` votes is strictly greater than the count of `APPROVE` votes, the outcome is `APPROVE_WITH_MODIFICATION`; otherwise (including when the two counts are equal — equality resolves to `APPROVE_WITH_MODIFICATION` as the conservative default), the outcome is `APPROVE`. Otherwise, if the count of `DEFER` votes is at least half of the votes cast (rounded up to the nearest whole vote), the outcome is `DEFER`. Otherwise, the fallback outcome when no clear majority emerges is also `DEFER`. The supermajority threshold for an approval is "two-thirds of votes cast" (rounded up), and the rejection threshold is "strict majority of votes cast"; both apply to the count of cast votes, not the eligible-voter count.

A successful resolve produces a `Resolution` row carrying the `agenda_item_id` it closes, the application_id mirrored from the agenda item, the tallied `outcome`, the full `tally` object recording per-mode counts plus `total_votes_cast`, `eligible_voter_count`, and `quorum_required`, the `pinned_submission_version` mirrored from the agenda item, and a server-generated `document_uri` whose value is the literal ethics-resolutions URI template formed by joining the resolution's id between a leading "/ethics/resolutions/" segment and a trailing "/document.pdf" suffix. The agenda item itself moves to `RESOLVED` and cannot be re-voted. The Application's downstream transition depends on the outcome and on the `review_kind` of the agenda item.

For an `INITIAL_REVIEW` or `SECONDARY_REVIEW` agenda item — that is, the initial-review variant of the tally rule — the Application transitions out of `IN_REVIEW` to one of four destinations. An `APPROVE` outcome moves the application to `APPROVED`, locks `approved_submission_version` to the agenda item's `pinned_submission_version`, sets `approval_resolution_id` to the resolution's id, and emits both a `REGULATORY_SYNC` and an `IM_NOTIFICATION` audit row. An `APPROVE_WITH_MODIFICATION` outcome moves the application to `APPROVED_WITH_MOD`, likewise locks `approved_submission_version` to the pinned version, creates a `Rectification` row with `opinions` populated from the resolution's reviewer comments and `due_at` set to the resolution's `created_at` plus 30 calendar days, and emits `REGULATORY_SYNC` and `IM_NOTIFICATION` events. A `REJECT` outcome moves the application to `REJECTED` and emits `REGULATORY_SYNC` and `IM_NOTIFICATION`. A `DEFER` outcome moves the application to `DEFERRED`, creates a `Rectification` with opinions copied from the comments and a `due_at` 30 calendar days out, and emits `REGULATORY_SYNC` and `IM_NOTIFICATION`. The `NO_QUORUM` case described above moves the application to `DEFERRED` without creating a rectification and without emitting regulatory or IM events.

For an `ANNUAL_REVIEW`, `AMENDMENT_REVIEW`, or `FINAL_REPORT_REVIEW` agenda item — the continuing-review variant of the tally rule — the underlying counts and the same supermajority and majority steps apply, but the final Application-level outcome is remapped to the continuing-review domain: an `APPROVE` or `APPROVE_WITH_MODIFICATION` count yields a `CONTINUE` outcome on the linked `AnnualReport`, a `REJECT` count yields `TERMINATE`, and a `DEFER` count yields `SUSPEND`. A `CONTINUE` result while the application is in `APPROVED` or `APPROVED_WITH_MOD` keeps the application in that same state for `ANNUAL_REVIEW` and `AMENDMENT_REVIEW` items; a `CONTINUE` result on a `FINAL_REPORT_REVIEW` (which requires the linked `AnnualReport`'s `report_kind` to be `FINAL_REPORT` and the underlying vote `outcome` to be `APPROVE`) advances the application to `COMPLETED` and emits `REGULATORY_SYNC`. A `SUSPEND` mapping moves the application from `APPROVED` or `APPROVED_WITH_MOD` to `SUSPENDED` and stores `SUSPEND` on the linked annual report's `outcome`; the suspension is lifted later by a subsequent `CONTINUE` resolution on a follow-up annual report, which transitions the application from `SUSPENDED` back to `APPROVED`. A `TERMINATE` mapping moves the application from `APPROVED` or `APPROVED_WITH_MOD` to `TERMINATED` and stores `TERMINATE` on the linked annual report; this transition emits `REGULATORY_SYNC` when originating from `APPROVED`. The continuing-review variant emits the same audit events as the initial-review variant.

### 3.6. Rectifications, Deadlines, and Secondary Review

When a resolution outcome is `APPROVE_WITH_MODIFICATION` or `DEFER`, the system automatically creates a child `Rectification` row that carries the `application_id`, the `source_resolution_id` pointing back to the resolution that generated it, an `opinions` array of one or more rectification opinion strings (required to be non-empty when the source resolution outcome is `APPROVE_WITH_MODIFICATION` or `DEFER`), an `applicant_response_uri` initially null, a `responded_at` timestamp initially null, and a derived `due_at` deadline. The deadline is computed at creation as the source resolution's `created_at` plus the rectification window: that is, the resolution's creation instant offset forward by 30 calendar days. The new rectification's `status` starts at `OPEN`.

The Applicant submits a response by hitting the rectification's respond endpoint and supplying an `applicant_response_uri` that points to the response document (and typically to a new submission version). The precondition is that the current logical clock is strictly before the rectification's `due_at` and the rectification's `status` is `OPEN`; a request made at or after the deadline is rejected with `ERR_RECTIFICATION_EXPIRED` (HTTP 409). On success the rectification's `responded_at` is set to the current clock time and the status advances from `OPEN` to `RESPONDED`. The applicant may also upload a new submission version as a separate step in the same workflow.

The Secretary then schedules a follow-up review by adding a new agenda item with `review_kind` `SECONDARY_REVIEW` referencing the `rectification_id`, and publishing that meeting's agenda. When the agenda is published the rectification's status advances from `RESPONDED` to `UNDER_SECONDARY_REVIEW`. The secondary-review item is tallied using the initial-review variant: an `APPROVE` outcome closes the rectification with `status` `CLOSED_APPROVED`; an `APPROVE_WITH_MODIFICATION` is also a closure-with-approval; a `REJECT` outcome closes the rectification with `status` `CLOSED_REJECTED`. When a rectification reaches `CLOSED_APPROVED` and originated from a `DEFER` source resolution, the parent application transitions from `DEFERRED` back to `PENDING_REVIEW` and becomes eligible for re-agendaing; when it originated from an `APPROVE_WITH_MODIFICATION` source, the parent application remains in `APPROVED_WITH_MOD` and its `approved_submission_version` is now permanently locked. When a rectification reaches `CLOSED_REJECTED`, the parent application cascades to `REJECTED`.

The deadline is enforced asynchronously by a sweep capability. An admin-only test-driving capability advances the logical clock to a supplied `target_timestamp`; the rectification-expiry sweep capability then iterates all rectifications still in `OPEN` status whose `due_at` has been reached or passed by the current clock (the boundary is inclusive: the exact `due_at` instant counts as expired) in ascending `created_at`, breaking ties on ascending `id`, and flips each one's status to `EXPIRED`. The cascade depends on which kind of resolution originated the rectification: if the source resolution's `outcome` was `APPROVE_WITH_MODIFICATION`, the application cascades from `APPROVED_WITH_MOD` to `REJECTED`; if the source outcome was `DEFER`, the application remains in `DEFERRED`. Each expiry writes a `REVIEW_DECISION` audit row labelled `RECTIFICATION_EXPIRED`. When an applicant attempts to respond after the sweep has already flipped a rectification to `EXPIRED`, the respond request is rejected with `ERR_RECTIFICATION_EXPIRED` (HTTP 409). When a respond request and the sweep race, the sweep is the canonical winner: an atomic compare-and-set on `Rectification.status` ensures sweep-wins and the late response is rejected.

### 3.7. Annual Continuing Review and Safety Alerts

Once an application is in `APPROVED` or `APPROVED_WITH_MOD`, the Applicant must periodically file an `AnnualReport` covering trial progress, adverse events, and enrollment. Each report carries an `application_id` (which must reference an application in one of those two states), a `report_period_start` and `report_period_end` (both ISO 8601 UTC), a `report_kind` from `ANNUAL_PROGRESS`, `PROTOCOL_AMENDMENT`, or `FINAL_REPORT`, a `serious_adverse_event_count` that must be non-negative, a `total_adverse_event_count` that must be greater than or equal to the serious count, and an `enrollment_count` of subjects enrolled in the period (must be non-negative). Violations of these integer invariants — a negative count, a count that exceeds its own total, or a malformed datetime — are rejected with `ERR_FIELD_VALIDATION`. The new report enters `SUBMITTED` status and immediately has its `safety_alert_flag` and the underlying `outcome` placeholder computed; the outcome itself remains null until a committee resolution maps the eventual tally.

The `safety_alert_flag` is set true when either of two threshold conditions holds. The first condition is that the `serious_adverse_event_count` is at least 3 serious events in the period; the boundary is inclusive, so exactly 3 SAEs is enough to raise the flag. The second condition is computed only when `enrollment_count` is strictly greater than zero: the observed adverse-event rate, defined as `total_adverse_event_count` divided by `enrollment_count`, is at or above 0.20 (twenty percent). The observed rate is computed as a float and the comparison uses an at-or-above check, so a rate of exactly 0.20 raises the flag. The system pins this chronological interpretation of the rate — numerator restricted to already-recorded events, denominator equal to the reported enrollment — rather than a forward-looking variant that would include pending events in the numerator.

The Secretary then adds an agenda item with `review_kind` of `ANNUAL_REVIEW`, `AMENDMENT_REVIEW`, or `FINAL_REPORT_REVIEW` referencing the `annual_report_id`. At publication the annual report's status advances from `SUBMITTED` to `SCHEDULED_FOR_REVIEW`. When the linked agenda item is resolved, the report's status advances to `RESOLVED` and its `outcome` is set per the continuing-review mapping described in §3.5: `APPROVE`/`APPROVE_WITH_MODIFICATION` count → `CONTINUE`, `REJECT` → `TERMINATE`, `DEFER` → `SUSPEND`. The application state then transitions as described in §3.5.

### 3.8. Audit Logs, Regulatory Sync, and Read-Only Observation

Every audited event is recoverable through the audit-log listing, filterable on `event_type`, `subject_entity`, and `subject_id`. The Secretary uses this listing for committee-internal recordkeeping; the `RegulatoryWatcher` uses it as the canonical record handed off to the external regulator and the IM channel. Resolutions, audit logs, applications, and annual reports are the four resources the `RegulatoryWatcher` may read; this role has no write authority anywhere in the system and is excluded from member-management, meeting-management, and submission listings.

## 4. Endpoint Definitions

New-resource creation endpoints return HTTP 201; modifications to existing resources return HTTP 200; the cancellation of a `SCHEDULED` meeting returns HTTP 204. List endpoints return HTTP 200. All endpoints carry the standard success/error envelope described in §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/ethics/applications` | Create a new ethics-review application in DRAFT status. | Applicant |
| GET | `/ethics/applications/{id}` | Fetch one application by id. | Applicant, Secretary, Chairperson, CommitteeMember, RegulatoryWatcher |
| GET | `/ethics/applications` | List applications, with filtering by status, phase, sponsor. | Secretary, Chairperson, CommitteeMember, RegulatoryWatcher |
| POST | `/ethics/applications/{id}/submissions` | Create a new submission version under an application (version_number auto-assigned as max+1). | Applicant |
| GET | `/ethics/applications/{id}/submissions` | List all submission versions for an application (current and historical). | Applicant, Secretary, Chairperson, CommitteeMember |
| POST | `/ethics/applications/{id}/submit` | Submit the application's current submission for formal pre-screening. | Applicant |
| POST | `/ethics/applications/{id}/prescreen` | Secretary performs formal-review pre-screening: PASS sends to PENDING_REVIEW; REJECT sends to REWORK_REQUIRED. | Secretary |
| POST | `/ethics/members` | Register a new committee member. | Secretary |
| GET | `/ethics/members/{id}` | Fetch a committee member. | Secretary, Chairperson, CommitteeMember |
| GET | `/ethics/members` | List committee members; filter by status and qualification. | Secretary, Chairperson, CommitteeMember |
| POST | `/ethics/members/{id}/conflicts` | Manually declare a conflict of interest for a member on an application. | Secretary, CommitteeMember |
| GET | `/ethics/members/{id}/conflicts` | List a member's declared conflicts. | Secretary, CommitteeMember, Chairperson |
| POST | `/ethics/meetings` | Schedule a review meeting (STANDARD periodic or EXPEDITED urgent). | Secretary |
| GET | `/ethics/meetings/{id}` | Fetch a meeting. | Secretary, Chairperson, CommitteeMember |
| GET | `/ethics/meetings` | List meetings; filter by status or meeting_type. | Secretary, Chairperson, CommitteeMember |
| POST | `/ethics/meetings/{id}/agenda-items` | Add an agenda item (initial review, secondary review, annual review, amendment, or final report) before publication. | Secretary |
| POST | `/ethics/meetings/{id}/publish-agenda` | Publish the agenda. Validates lead time; freezes pinned_submission_version, eligible_voter_count and quorum_required on every AgendaItem. | Secretary |
| POST | `/ethics/meetings/{id}/open` | Open the meeting session (members may now vote). | Secretary |
| POST | `/ethics/meetings/{id}/close` | Close the meeting. All agenda items must be RESOLVED or CLOSED_WITHOUT_QUORUM first. | Secretary |
| DELETE | `/ethics/meetings/{id}` | Cancel a SCHEDULED meeting (before agenda publication). | Secretary |
| POST | `/ethics/agenda-items/{id}/attendance` | A member confirms attendance for an agenda item (required to vote). | CommitteeMember |
| POST | `/ethics/agenda-items/{id}/votes` | Cast a vote on an open agenda item. | CommitteeMember |
| POST | `/ethics/agenda-items/{id}/resolve` | Chairperson resolves an open agenda item: system tallies votes, checks quorum, generates a Resolution, and cascades downstream Application transitions and (if needed) Rectification creation. | Chairperson |
| GET | `/ethics/agenda-items/{id}` | Fetch an agenda item with frozen pinned state. | Secretary, Chairperson, CommitteeMember, Applicant |
| GET | `/ethics/resolutions/{id}` | Fetch a resolution document record. | Secretary, Chairperson, CommitteeMember, Applicant, RegulatoryWatcher |
| GET | `/ethics/rectifications/{id}` | Fetch a rectification. | Secretary, Chairperson, CommitteeMember, Applicant |
| POST | `/ethics/rectifications/{id}/respond` | Applicant submits a response. May include applicant_response_uri pointing to a new submission version. | Applicant |
| POST | `/ethics/applications/{aid}/annual-reports` | Submit an annual progress report, protocol amendment, or final report. | Applicant |
| GET | `/ethics/applications/{aid}/annual-reports` | List annual reports for an application. | Applicant, Secretary, Chairperson, CommitteeMember, RegulatoryWatcher |
| GET | `/ethics/audit-logs` | List audit log entries (filterable by event_type, subject_entity, subject_id). | Secretary, RegulatoryWatcher |
| POST | `/ethics/_clock/advance` | Advance the server's logical clock to a future ISO 8601 UTC timestamp (test harness). | Secretary |
| POST | `/ethics/_sweep/run` | Run the rectification-expiry sweep idempotently: flips OPEN rectifications past due_at to EXPIRED and cascades application state. | Secretary |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID` | 401 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_RECUSED` | 403 |
| `ERR_MEMBER_NOT_QUALIFIED` | 422 |
| `ERR_AGENDA_LEAD_TIME_VIOLATION` | 422 |
| `ERR_RECTIFICATION_EXPIRED` | 409 |
| `ERR_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_DUPLICATE_VOTE` | 409 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_FIELD_VALIDATION` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
