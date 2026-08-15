# IRB Human Subjects Protocol Review API — Product Requirements Document

## 1. Introduction

Universities conducting research on human subjects operate under federal oversight rules that require every study to pass institutional review before enrollment begins and to remain under board supervision for as long as the study stays open. The operational burden is substantial: intake staff must route each submission to the correct review pathway, chairs must adjudicate conflicts of interest before acting, convened boards must satisfy quorum and composition rules, compliance officers must track adverse events against strict filing deadlines, and multi-site studies layer reliance agreements between institutions on top of everything else.

This document specifies the IRB Human Subjects Protocol Review API as a single system of record for that entire lifecycle. It governs submission and coordinator determination across the three review pathways (exempt, expedited, and full board), reviewer assignment with conflict-of-interest management, informed-consent document review including the federal waiver criteria, convened-meeting agenda construction and quorum enforcement, modification and continuing-review cadence, adverse-event and unanticipated-problem reporting, non-compliance investigation with suspension and debarment consequences, and reliance agreements for multi-site studies. All temporal behavior — submission windows, reporting deadlines, meeting grace periods, approval expiry — is measured against a controllable logical clock so that compliance outcomes are deterministic and auditable.

All endpoints are mounted under the `/irb` prefix, with the exception of the administrative clock control described in §2.4.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or presenting an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles: `PrincipalInvestigator`, `Reviewer`, `IrbChair`, `IrbCoordinator`, `IrbAdmin`, and `ComplianceOfficer`. Attempting an operation outside the caller's designated role is rejected with `ERR_FORBIDDEN` (HTTP 403).

How `X-User-ID` is interpreted depends on the role presented:

- When `X-User-Role` is `PrincipalInvestigator`, `X-User-ID` is the `id` of the acting Investigator; ownership checks on any resource that references an Investigator — above all a protocol's `pi_id` — compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting IrbMember; ownership checks on review assignments and conflict declarations compare the resource's `reviewer_id` to `X-User-ID`.
- When `X-User-Role` is `IrbChair`, `X-User-ID` is likewise the `id` of an IrbMember, with one additional constraint: that member's `is_chair` flag must be true. A member whose `is_chair` is false — or an `X-User-ID` that resolves to no registered member at all — acting in the `IrbChair` capacity is rejected with `ERR_FORBIDDEN`. The member's `status` is not examined, so an `INACTIVE` member whose `is_chair` is true may still act in the `IrbChair` capacity.
- When `X-User-Role` is `IrbCoordinator`, `IrbAdmin`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from the wall clock rather than the logical clock of §2.4.
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and out-of-range values are clamped rather than rejected — a value below 1 is clamped up to 1, and a value above 100 is clamped down to 100. The `offset` parameter skips a number of items from the front of the result set, defaults to 0, and clamps negative values up to 0. A non-integer `limit` or `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Every paginated list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, with `has_more` true exactly when `offset` plus the number of items returned is less than `total_count`.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties broken by `id` ascending. One endpoint deliberately overrides this default: a meeting's agenda listing follows deliberation order rather than creation order, as specified in §3.6.

### 2.4. The Logical Clock and Scheduled Sweeps

Every temporal judgment in the system — deadline checks, submission windows, approval expiry, meeting grace periods — is evaluated against a server-maintained logical clock, never the wall clock. At startup, before any adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never silently falls back to wall-clock time.

An administrator-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the supplied instant is unconstrained, so the clock may be set to any valid ISO 8601 instant, forward or backward. Each advance immediately runs a sweep across three families of overdue work:

1. **Lapsed continuing reviews.** Any continuing-review cycle in `PENDING_SUBMISSION` or `SUBMITTED` whose due date is strictly before the new clock reading transitions to `LAPSED`. The cascade is described fully in §3.7: the parent protocol moves from `APPROVED` to `EXPIRED`, a non-compliance case of source `LAPSED_CR` is opened, and the investigator's provisional compliance score is recomputed.
2. **Meetings that failed to start.** Any board meeting still `SCHEDULED` once the clock has passed thirty minutes beyond its scheduled start transitions to `FAILED_QUORUM`.
3. **Stale assignment offers.** Any review assignment still `OFFERED` past its response deadline transitions to `EXPIRED`, and the affected member's `active_assignment_count` is decremented by one.

The capability's response reports the new clock reading as `current_utc` — rendered as an ISO 8601 UTC timestamp with three fractional digits, the same rendering discipline as the resource timestamps of §2.5 — together with three sweep counters: `lapsed_continuing_reviews`, `failed_quorum_meetings`, and `expired_assignments`.

### 2.5. Common Resource Properties

Every resource in the system — investigators, IRB members, protocols, consent documents, review assignments, conflict declarations, board meetings, agenda items, modification requests, continuing reviews, adverse-event reports, non-compliance cases, and reliance agreements — carries four system-managed properties:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. All resource timestamps are rendered from the logical clock of §2.4, never the wall clock.
- `updated_at` (string): an ISO 8601 UTC timestamp updated on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at 1 on creation and increments on every mutation; it backs the optimistic concurrency control rules of §2.8.

Recomputing a derived field — a protocol's fee figures, a meeting's `item_count`, a member's `active_assignment_count`, an investigator's compliance scores — counts as a mutation of the owning resource: it refreshes `updated_at` and increments `version` just as a client-visible edit would.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated left to right along the path. The server resolves each path identifier in sequence and rejects the request at the first identifier that fails to resolve, returning the 404 error that names the missing resource kind: `ERR_INVESTIGATOR_NOT_FOUND` for an investigator, `ERR_MEMBER_NOT_FOUND` for a member, `ERR_PROTOCOL_NOT_FOUND` for a protocol, `ERR_CONSENT_DOC_NOT_FOUND` for a consent document, `ERR_ASSIGNMENT_NOT_FOUND` for a review assignment, `ERR_DECLARATION_NOT_FOUND` for a conflict declaration, `ERR_MEETING_NOT_FOUND` for a board meeting, `ERR_AGENDA_ITEM_NOT_FOUND` for an agenda item, `ERR_MODIFICATION_NOT_FOUND` for a modification request, `ERR_CR_NOT_FOUND` for a continuing review, `ERR_AE_NOT_FOUND` for an adverse-event report, `ERR_CASE_NOT_FOUND` for a non-compliance case, and `ERR_RELIANCE_NOT_FOUND` for a reliance agreement. A request aimed at a consent document beneath a protocol that does not exist therefore fails with `ERR_PROTOCOL_NOT_FOUND` before the consent identifier is ever examined.

### 2.7. Fee Precision and Rounding Discipline

All review-fee amounts are stored as integer numbers of cents. The rounding order is pinned and not negotiable: each fee line is first computed by multiplying its base amount by the protocol's industry multiplier, and that product is rounded half-up to a whole number of cents; only then are the rounded lines summed into a fee total. Sum-then-round is the rejected alternative and yields different cents. The industry multiplier is 1.5 when the protocol's `is_industry_sponsored` flag is true and 1.0 otherwise.

The base fee for a review level is 50,000 cents ($500.00) for `EXEMPT`, 150,000 cents ($1,500.00) for `EXPEDITED`, and 250,000 cents ($2,500.00) for `FULL_BOARD`. Each executed reliance agreement contributes a site line whose base is 74,999 cents ($749.99), likewise multiplied and rounded half-up as its own line. How these lines assemble into a protocol's provisional and settled assessments is described in §3.2 and §3.9.

### 2.8. Optimistic Concurrency Control

Two write endpoints carry optimistic concurrency control; no other endpoint accepts a version field. On both endpoints the version field is optional: when it is omitted, no concurrency check runs; when it is present, it must be an integer — a non-integer value draws `ERR_VALIDATION` (HTTP 400) — equal to the resource's current `version`.

Filing a modification request against a protocol accepts `expected_protocol_version`, holding the protocol `version` the client last observed. Because filing a modification itself advances the protocol's `version` — as does approving a modification and every other protocol mutation — a writer holding an older value is composing its amendment against a protocol state it has not observed. When `expected_protocol_version` is supplied and does not match the protocol's current `version`, the filing is rejected with `ERR_STALE_PROTOCOL_VERSION` (HTTP 412).

Listing a protocol on a meeting's agenda accepts `expected_meeting_version`, holding the meeting `version` the client last observed. Each agenda-item addition bumps the meeting's `version`, so a writer holding an older value is composing against a stale agenda — its capacity headroom and duplicate-listing set may no longer be accurate. When `expected_meeting_version` is supplied and does not match the meeting's current `version`, the listing is rejected with `ERR_STALE_MEETING_VERSION` (HTTP 412).

### 2.9. Validation Pipeline and Error Precedence

When several rules fail on the same request, the error surfaced is determined by a fixed evaluation order, not by which check happens to run first in code. The order is:

1. **Authentication** — the presence and recognizability of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`).
2. **Authorization** — role permission for the endpoint, the chair-flag requirement on chair-only operations, and ownership rules such as a principal investigator acting only on their own protocol or a reviewer acting only on their own assignment (`ERR_FORBIDDEN`).
3. **Existence** — left-to-right path resolution per §2.6 (the 404 family).
4. **State legality** — the target resource must sit in a from-state of the attempted transition (`ERR_INVALID_STATE`).
5. **Business safety gates** — the investigator eligibility gate of §3.2, reviewer and chair conflict checks (`ERR_REVIEWER_CONFLICTED`, `ERR_CHAIR_CONFLICTED`), consent and waiver safety (`ERR_WAIVER_CRITERIA_NOT_MET`, `ERR_NO_APPROVED_CONSENT`), and submission completeness (`ERR_NO_CONSENT_DOCUMENT`).
6. **Business constraints** — determination legality (`ERR_EXEMPT_REQUIRES_MINIMAL_RISK`), expedited routing rules (`ERR_INSUFFICIENT_RECOMMENDATIONS`, `ERR_EXPEDITED_DISAPPROVE_REQUIRES_BOARD`), assignment uniqueness and pool availability (`ERR_DUPLICATE_ASSIGNMENT`, `ERR_NO_ELIGIBLE_REVIEWER`), meeting composition (`ERR_QUORUM_NOT_MET`, `ERR_QUORUM_COMPOSITION_MISSING`, `ERR_ATTENDEE_NOT_ELIGIBLE`), vote integrity (`ERR_VOTE_TALLY_MISMATCH`), agenda capacity and uniqueness (`ERR_AGENDA_CAPACITY_EXCEEDED`, `ERR_DUPLICATE_AGENDA_LISTING`), room and reliance overlap (`ERR_MEETING_ROOM_CONFLICT`, `ERR_RELIANCE_WINDOW_OVERLAP`), and modification routing (`ERR_MAJOR_REQUIRES_BOARD`).
7. **Temporal windows** — scheduling in the future, continuing-review windows, reliance date ranges, and adverse-event occurrence dates (`ERR_SCHEDULE_IN_PAST`, `ERR_CR_WINDOW_NOT_OPEN`, `ERR_INVALID_DATE_RANGE`, `ERR_AE_OCCURRED_IN_FUTURE`).
8. **Cross-entity state references** — reliance execution against an unapproved protocol, modification approval against a non-submitted consent document, close or reinstate against open cases (`ERR_PROTOCOL_NOT_APPROVED`, `ERR_CONSENT_DOC_NOT_SUBMITTED`, `ERR_OPEN_CASES_REMAIN`).
9. **Optimistic concurrency** — the two OCC checks of §2.8 (`ERR_STALE_PROTOCOL_VERSION`, `ERR_STALE_MEETING_VERSION`).
10. **Request shape** — required fields present, values well-typed, enum values valid (`ERR_VALIDATION`).

Tier 10's position carries one mechanical qualification: each request field is validated at the point the workflow first reads it, and several workflows read body fields before running their gates — filing a modification parses `scope` and `description` before the ownership and state gates, and recording a determination parses `determined_review_level` before the exempt-routing check — so on those paths a missing or malformed required field surfaces `ERR_VALIDATION` ahead of higher-tier gates. Within a single endpoint, any finer ordering mandated by a specific workflow is stated where that workflow is described in §3 — for instance the fixed order of the submission gates in §3.2 and the ordered convene checks in §3.6.

### 2.10. Hierarchical Consistency and Cascade Invariants

Suspension is the system's strongest consistency event, and it cascades outward from the protocol. Whenever a protocol enters `SUSPENDED`, every executed reliance agreement of that protocol moves to `SUSPENDED`; every agenda item of that protocol still `LISTED` on a `SCHEDULED` meeting is removed and its meeting's `item_count` recomputed — items listed on `CONVENED` or `FAILED_QUORUM` meetings are untouched; and a meeting whose `item_count` falls to zero through those removals is cancelled outright. Reinstatement compensates only partially — reliance agreements return to `EXECUTED`, but removed agenda items are not restored — and §3.8 describes the asymmetry in full.

Two further invariants hold across entity boundaries. First, consent cardinality: at most one consent document per protocol may be `APPROVED` at any moment, so approving a new document always supersedes the previously approved one. Second, snapshot integrity: a convened meeting freezes both its attendee roster (`attendee_member_ids`) and its `quorum_threshold` at the moment of convening, and a recorded vote freezes the `eligible_voter_count` it was tallied against; later membership changes do not retroactively alter those snapshots.

## 3. Business Logic & Workflows

### 3.1. Registry Onboarding: Investigators and Board Members

Before any protocol work begins, an `IrbAdmin` populates the two registries. Registering an investigator requires a `full_name`, an `email` that must be unique across all investigators (a duplicate is rejected with `ERR_VALIDATION`, HTTP 400), a `department`, and a `training_expires_at` timestamp marking when the investigator's human-subjects training certificate lapses. Both compliance scores, `provisional_compliance_score` and `final_compliance_score`, start at 100 for a newly registered investigator, and the investigator's `status` starts at `ACTIVE`; the system later flips it to `DEBARRED` under the scoring rules of §3.8. The investigator directory can be listed with an optional `status` filter, paginated with `limit` and `offset`, and individual investigators can be fetched to inspect their current scores.

Board members are registered the same way, with `full_name`, a unique `email` (a duplicate likewise drawing `ERR_VALIDATION`), a `member_category` of `SCIENTIST`, `NON_SCIENTIST`, `UNAFFILIATED`, or `PRISONER_REPRESENTATIVE`, and an optional `is_chair` flag that defaults to false and marks the one member empowered to act in the `IrbChair` capacity. A member's `status` begins as `ACTIVE`, and their `active_assignment_count` — the number of their review assignments currently in `OFFERED` or `ACCEPTED` — begins at zero and is maintained thereafter by the assignment lifecycle. Deactivating a member flips `status` to `INACTIVE`, excluding them from the quorum base and from all new assignments while leaving any existing `OFFERED` or `ACCEPTED` assignments untouched; reactivation returns an `INACTIVE` member to `ACTIVE`. Neither flip enforces a state precondition — deactivating an already-`INACTIVE` member or reactivating an already-`ACTIVE` one succeeds. The member roster can be listed with optional `status` and `member_category` filters.

### 3.2. Protocol Drafting, Submission Gates, and Coordinator Determination

A `PrincipalInvestigator` drafts a protocol by supplying a `title`, a `claimed_review_level` of `EXEMPT`, `EXPEDITED`, or `FULL_BOARD`, a `risk_level` of `MINIMAL` or `GREATER_THAN_MINIMAL`, and two optional flags: `involves_prisoners` (default false) and `is_industry_sponsored` (default false, and the flag that drives the industry multiplier of §2.7). The protocol's `pi_id` is not client-supplied; it is taken from the caller's `X-User-ID`, which is what ownership checks compare against later. New protocols are born in `DRAFT`. The protocol collection supports listing with optional `pi_id` and `status` filters.

Submitting a protocol is the most heavily gated action in the system, and its checks run in a fixed order so that a doubly ineligible investigator always sees the same error. State legality comes first: submission is legal only from `DRAFT`, `RETURNED`, `CHANGES_REQUESTED`, or `BOARD_CHANGES_REQUESTED`, and a protocol in any other state is rejected with `ERR_INVALID_STATE` before ownership is examined. Ownership follows — a caller whose `X-User-ID` does not match the protocol's `pi_id` is rejected with `ERR_FORBIDDEN`. The protocol's `pi_id` must then resolve to a registered investigator, failing which the submit is rejected with `ERR_INVESTIGATOR_NOT_FOUND`. The three investigator-eligibility checks follow in this exact sequence: an investigator whose `status` is `DEBARRED` is rejected with `ERR_INVESTIGATOR_DEBARRED`; an investigator whose `training_expires_at` is not strictly after the current logical time is rejected with `ERR_PI_TRAINING_LAPSED`; and an investigator whose `provisional_compliance_score` is below the submission gate of 60 is rejected with `ERR_COMPLIANCE_SCORE_TOO_LOW`. Finally, submission completeness requires at least one consent document of the protocol to sit in `SUBMITTED` or `APPROVED`, failing which the submit is rejected with `ERR_NO_CONSENT_DOCUMENT`.

Where the protocol lands after a successful submit depends on where it came from. From `DRAFT` or `RETURNED` it enters `SUBMITTED`; from `CHANGES_REQUESTED` it re-enters `UNDER_EXPEDITED_REVIEW`; from `BOARD_CHANGES_REQUESTED` it re-enters `AWAITING_FULL_BOARD`. The very first submission — the `DRAFT` → `SUBMITTED` crossing — is also the billing event: the system computes `provisional_fee_cents` exactly once, taking the base fee for the `claimed_review_level` (50,000 cents for `EXEMPT`, 150,000 cents for `EXPEDITED`, 250,000 cents for `FULL_BOARD`), multiplying by the industry multiplier, and rounding the product half-up to a whole number of cents per §2.7. Resubmissions from `RETURNED`, `CHANGES_REQUESTED`, or `BOARD_CHANGES_REQUESTED` leave `provisional_fee_cents` untouched.

From `SUBMITTED`, an `IrbCoordinator` holds two levers. Returning the protocol moves it `SUBMITTED` → `RETURNED` with a free-text `reason` — accepted but not persisted on the protocol — signalling the PI to complete and resubmit. Recording a determination with a `determined_review_level` routes the study onto its review track: `EXEMPT` is legal only when the protocol's `risk_level` is `MINIMAL` — an exempt determination on a `GREATER_THAN_MINIMAL` protocol is rejected with `ERR_EXEMPT_REQUIRES_MINIMAL_RISK` — and moves the protocol to `EXEMPT_ACTIVE`; `EXPEDITED` moves it to `UNDER_EXPEDITED_REVIEW`; `FULL_BOARD` moves it to `AWAITING_FULL_BOARD`. A protocol not currently in `SUBMITTED` rejects either lever with `ERR_INVALID_STATE`. Every determination stamps `determined_review_level` and settles the fee base: `settled_fee_cents` becomes the rounded base line for the determined level, and `fee_delta_cents` is recomputed as the settled assessment minus the provisional one. Exempt studies carry no continuing-review cadence — no continuing review is created and `approval_expires_at` stays null.

A PI who abandons a study may withdraw it from `DRAFT`, `SUBMITTED`, or `RETURNED`, moving it to the terminal `WITHDRAWN` state; withdrawal from any other state is rejected with `ERR_INVALID_STATE`, and withdrawal of another investigator's protocol with `ERR_FORBIDDEN`.

### 3.3. Informed Consent Documents and Waiver Adjudication

Every protocol accumulates a versioned stack of consent documents, uploaded by its owning PI. An upload supplies a `file_ref` storage pointer and may request a consent waiver via `waiver_type`, one of `NONE` (the default), `WAIVER_OF_CONSENT`, `WAIVER_OF_DOCUMENTATION`, or `ALTERATION_OF_CONSENT`. Four boolean flags accompany any waiver request, each echoing a criterion of 45 CFR 46.116(f): `waiver_criterion_minimal_risk`, `waiver_criterion_rights_not_adversely_affected`, `waiver_criterion_impracticable_without_waiver`, and `waiver_criterion_debrief_when_appropriate`, all defaulting to false. The server assigns each upload a `version_seq` equal to one more than the highest existing sequence number on that protocol, and the document begins life in `SUBMITTED`. No protocol-state gate applies: uploads are accepted whatever state the protocol sits in. A protocol's document stack can be listed with an optional `status` filter.

Adjudication of a document rests with the chair, acting through a review `outcome` of `APPROVE` or `REQUIRE_CHANGES` on a document currently in `SUBMITTED` — anything else is rejected with `ERR_INVALID_STATE`. Approval carries a safety condition: when the document's `waiver_type` is anything other than `NONE`, all four waiver-criterion flags must be true, and approving without them is rejected with `ERR_WAIVER_CRITERIA_NOT_MET`. A successful approval also enforces the single-approved-document invariant: any other document of the same protocol currently `APPROVED` moves to `SUPERSEDED`, keeping the count of approved documents per protocol at one whenever one was already approved. A `REQUIRE_CHANGES` outcome moves the document to `CHANGES_REQUIRED`, which is terminal for that version — the PI responds by uploading a fresh document that receives the next `version_seq`. Approval can also arrive indirectly, as a side effect of approving a modification that carries a `new_consent_document_id` (§3.7); the same transition and the same waiver-criteria precondition govern that path.

### 3.4. Reviewer Assignment and Conflict-of-Interest Management

With a protocol under review, the coordinator builds its review panel. Offering an assignment normally names the intended member via `reviewer_id` and may set a `reviewer_role` of `PRIMARY` or `SECONDARY` (defaulting to `SECONDARY`). Offering imposes no protocol-state gate. An explicitly named reviewer must resolve to a registered member (else `ERR_MEMBER_NOT_FOUND`), must be `ACTIVE` (else `ERR_NO_ELIGIBLE_REVIEWER`), and must hold no `CONFLICTED` declaration on the protocol (else `ERR_REVIEWER_CONFLICTED`), all evaluated in that order before the uniqueness check; the five-assignment ceiling constrains only the auto-selection pool, never an explicitly named reviewer. The system stamps `offered_at` with the logical instant of creation and sets `response_deadline_at` seven days later; the assignment starts in `OFFERED`, and the member's `active_assignment_count` rises by one, since both `OFFERED` and `ACCEPTED` assignments count against a member's load. Uniqueness is enforced per protocol and reviewer: a second assignment in `OFFERED`, `ACCEPTED`, or `SUBMITTED` for the same pairing is rejected with `ERR_DUPLICATE_ASSIGNMENT` (HTTP 409).

When the offer omits `reviewer_id`, the server selects deterministically. The candidate pool is every `ACTIVE` member whose `active_assignment_count` is below the five-assignment ceiling, who holds no `CONFLICTED` declaration on this protocol, and who has no existing assignment on this protocol in `OFFERED`, `ACCEPTED`, or `SUBMITTED`. Candidates are ranked by `active_assignment_count` ascending, ties broken by the member's `created_at` ascending — never by `id` — and the first candidate receives the offer. An empty pool is rejected with `ERR_NO_ELIGIBLE_REVIEWER` (HTTP 422).

The addressed reviewer answers the offer with a `response` of `ACCEPT`, `DECLINE`, or `RECUSE`; the caller must be the assignment's `reviewer_id`, otherwise `ERR_FORBIDDEN`, and the assignment must still be `OFFERED`, otherwise `ERR_INVALID_STATE`. Accepting moves the assignment to `ACCEPTED` and leaves the member's count unchanged; declining moves it to `DECLINED` and recusing to `RECUSED`, each decrementing the count by one. Offers left unanswered past their `response_deadline_at` are swept to `EXPIRED` by the clock, again decrementing the count.

From `ACCEPTED`, and only while the protocol sits in `UNDER_EXPEDITED_REVIEW` or `AWAITING_FULL_BOARD` (otherwise `ERR_INVALID_STATE`), the reviewer files a `recommendation` of `APPROVE`, `MINOR_REVISIONS`, `MAJOR_REVISIONS`, or `DISAPPROVE`. Filing moves the assignment to the terminal `SUBMITTED` state, stores the recommendation, and decrements the member's count by one. Assignment collections can be listed with optional `protocol_id`, `reviewer_id`, and `status` filters.

Conflict management runs alongside assignment. A reviewer self-declares against a protocol with a `declaration_type` of `NONE`, `FINANCIAL`, `PERSONAL`, or `SCIENTIFIC` — `NONE` being an affirmative no-conflict statement — plus an optional free-text `detail`; the declaration's `reviewer_id` is taken from the caller's identity, and the declaration opens in `PENDING_REVIEW`. The chair then adjudicates it to `CLEARED` or `CONFLICTED`; adjudication requires the declaration to sit in `PENDING_REVIEW`, anything else drawing `ERR_INVALID_STATE`. A `CONFLICTED` adjudication detonates a cascade across that reviewer's work on the protocol: every assignment in `OFFERED` or `ACCEPTED` moves to `RECUSED` with the member's count decremented per recusal, and every assignment already `SUBMITTED` has its `recommendation_voided` flag set true, excluding the recommendation from expedited completeness counts and from vote eligibility. Because that cascade fires at adjudication time, a conflicted reviewer will usually find their assignments already gone; any residual attempt to accept an offer or file a recommendation while holding a `CONFLICTED` declaration on the protocol — as well as any coordinator attempt to offer such a reviewer an assignment — is rejected with `ERR_REVIEWER_CONFLICTED`. Declarations can be listed with optional `protocol_id`, `reviewer_id`, and `status` filters.

### 3.5. Expedited Review and Chair Determination

Expedited protocols are decided by the chair alone, through a determination `outcome` of `APPROVE`, `REQUIRE_CHANGES`, or `REFER_TO_FULL_BOARD` on a protocol in `UNDER_EXPEDITED_REVIEW` (any other state: `ERR_INVALID_STATE`).

Whatever the outcome, the chair must hold no `CONFLICTED` declaration on the protocol, else `ERR_CHAIR_CONFLICTED` — this check precedes every outcome-specific gate. Approval is then conditioned on a chain of checks evaluated in order. At least two review assignments must stand in `SUBMITTED` with `recommendation_voided` false, else `ERR_INSUFFICIENT_RECOMMENDATIONS`. No non-voided submitted recommendation may be `DISAPPROVE` — expedited review cannot disapprove, so that situation is rejected with `ERR_EXPEDITED_DISAPPROVE_REQUIRES_BOARD` and the study belongs in front of the convened board instead. And at least one consent document of the protocol must be `APPROVED`, else `ERR_NO_APPROVED_CONSENT`. A successful approval writes `continuing_review_interval_days` as 180 when the protocol's `risk_level` is `GREATER_THAN_MINIMAL` and 365 when it is `MINIMAL`, sets `approval_expires_at` to the approval instant plus that interval, moves the protocol to `APPROVED`, and creates the first continuing-review cycle: `cycle_index` 1, `due_at` equal to `approval_expires_at`, `window_opens_at` sixty days before the due date, status `PENDING_SUBMISSION`.

Requesting changes requires a lighter gate — at least one non-voided submitted recommendation, else `ERR_INSUFFICIENT_RECOMMENDATIONS` — and moves the protocol to `CHANGES_REQUESTED`, from which the PI resubmits per §3.2. Referring to the full board moves the protocol to `AWAITING_FULL_BOARD` with no further checks.

### 3.6. Convened Board Meetings: Quorum, Agenda, and Voting

The full-board track convenes around scheduled meetings. A coordinator schedules a meeting with a `room_id`, a `scheduled_at` start that must be strictly after the current logical time (otherwise `ERR_SCHEDULE_IN_PAST`), and a `duration_minutes` length; the future-start check runs before the room-overlap check, so a request failing both draws `ERR_SCHEDULE_IN_PAST`. The meeting begins in `SCHEDULED` with an `item_count` of zero. A meeting occupies its room over a half-open interval — from `scheduled_at` up to but not including `scheduled_at` plus `duration_minutes` — so a meeting beginning at the exact instant another ends does not collide with it. Any true overlap with another `SCHEDULED` or `CONVENED` meeting in the same room is rejected with `ERR_MEETING_ROOM_CONFLICT` (HTTP 409). The meetings collection lists with an optional `status` filter.

Building the agenda is a coordinator duty guarded by the meeting-level OCC of §2.8: each listing request names a `protocol_id`, optionally a `modification_id`, and the mandatory `expected_meeting_version`. The meeting must still be `SCHEDULED`, and the item's business shape must be one of two forms, anything else drawing `ERR_INVALID_STATE`: either `modification_id` is omitted and the protocol sits in `AWAITING_FULL_BOARD`, `SUSPENDED`, or `EXPIRED` (an initial-review listing), or `modification_id` is present, that modification is `SUBMITTED`, and the protocol is `APPROVED`, `SUSPENDED`, or `EXPIRED` (a modification deliberation). Capacity is capped at eight `LISTED` items per meeting — a ninth is rejected with `ERR_AGENDA_CAPACITY_EXCEEDED` — and a protocol may hold at most one `LISTED` item across all `SCHEDULED` or `CONVENED` meetings at a time, a second listing drawing `ERR_DUPLICATE_AGENDA_LISTING` (HTTP 409). At listing time the server derives the item's `priority_class`: `SUSPENSION_REVIEW` when the protocol is in `SUSPENDED` or `EXPIRED`, else `MODIFICATION` when a `modification_id` is attached, else `INITIAL_REVIEW`. Each successful addition increments the meeting's `version` exactly once and recomputes its `item_count` — the recomputation is that single mutation per §2.5, not an additional increment on top of the addition. While other lists follow the default creation-order sort, a meeting's agenda reads in deliberation order: `SUSPENSION_REVIEW` items first, then `INITIAL_REVIEW`, then `MODIFICATION`, with ties inside a class ordered by the protocol's `created_at` ascending and any remaining ties broken by the agenda item's `id` ascending. Agenda items can also be browsed globally with optional `protocol_id`, `meeting_id`, `modification_id`, and `status` filters.

Convening belongs to the chair, who presents the attendee roster as `attendee_member_ids`. The checks run in a deliberate order: every listed id must resolve to an `ACTIVE` member, else `ERR_ATTENDEE_NOT_ELIGIBLE`; the roster size must reach the quorum threshold — one more than half the number of `ACTIVE` members, the half rounded down to a whole number — else `ERR_QUORUM_NOT_MET`; and the composition must include at least one attendee of category `NON_SCIENTIST` and at least one of category `UNAFFILIATED`, with an additional requirement of at least one `PRISONER_REPRESENTATIVE` attendee whenever any `LISTED` item's protocol has `involves_prisoners` true, composition failures drawing `ERR_QUORUM_COMPOSITION_MISSING`. A meeting not in `SCHEDULED` refuses to convene with `ERR_INVALID_STATE`. On success the roster and the computed `quorum_threshold` are snapshotted onto the meeting and its status becomes `CONVENED`.

Once convened, the chair works the agenda by recording votes. A vote names a `motion` of `APPROVE` or `REQUIRE_CHANGES` plus the three tallies `votes_for`, `votes_against`, and `votes_abstain`. The item must be `LISTED` and its meeting `CONVENED` — a cross-entity gate, each breach answered by `ERR_INVALID_STATE` — and the chair must hold no `CONFLICTED` declaration on the item's protocol, else `ERR_CHAIR_CONFLICTED`. At the moment of voting the server freezes `eligible_voter_count`: the size of the meeting's attendee roster minus those attendees holding a `CONFLICTED` declaration on the item's protocol. Integrity demands the three tallies sum exactly to that count, any mismatch rejected with `ERR_VOTE_TALLY_MISMATCH`; this integrity check fires before any consent-side approval gate. Those consent-side gates — the `ERR_NO_APPROVED_CONSENT` requirement on an initial-review approval, and the requirement that a modification's referenced consent document exist (else `ERR_CONSENT_DOC_NOT_FOUND`), sit in `SUBMITTED`, and satisfy the waiver criteria — run only when the recorded outcome is `APPROVE`. A motion passes only when twice `votes_for` strictly exceeds `eligible_voter_count`; an exact tie fails. The four outcome branches then read as follows. An `APPROVE` motion that passes records `outcome` `APPROVE`: on an initial-review item the protocol becomes `APPROVED` with the same interval, expiry, and first-cycle creation side effects as an expedited approval — and the same requirement that an `APPROVED` consent document exist, else `ERR_NO_APPROVED_CONSENT` — while on a modification item the modification becomes `APPROVED` with the consent-supersede side effects of §3.7. An `APPROVE` motion that fails records `outcome` `DISAPPROVE`: the protocol becomes `DISAPPROVED` — only a convened board may disapprove a protocol — or the modification becomes `DENIED`. A `REQUIRE_CHANGES` motion that passes records `outcome` `REQUIRE_CHANGES`: the protocol becomes `BOARD_CHANGES_REQUESTED`, or the modification becomes `DENIED`. A `REQUIRE_CHANGES` motion that fails records `outcome` `DEFER`, and the item itself moves to `DEFERRED` rather than `VOTED`; in every other case the item lands in `VOTED`.

Adjournment by the chair moves the meeting `CONVENED` → `ADJOURNED` and converts every still-`LISTED` item to `DEFERRED`, recomputing `item_count`. Two failure-and-recovery paths round out the lifecycle. When the clock sweep finds a meeting still `SCHEDULED` more than thirty minutes past its `scheduled_at`, the meeting moves to `FAILED_QUORUM`; the coordinator may then reschedule it — a new `scheduled_at` strictly after the current logical time (else `ERR_SCHEDULE_IN_PAST`), optionally a new `room_id` or `duration_minutes`, the room-occupation overlap check applied anew (else `ERR_MEETING_ROOM_CONFLICT`) — returning it to `SCHEDULED` with its `LISTED` items carried over. And when a protocol suspension removes the last `LISTED` item of a still-`SCHEDULED` meeting so that its `item_count` falls to zero, the meeting moves to `CANCELLED`; note that a meeting created with zero items is never auto-cancelled — only a removal event triggers that transition.

### 3.7. Modifications and Continuing Review

Once approved, a protocol evolves through formal amendments. The owning PI files a modification with a `scope` of `MINOR` or `MAJOR`, a free-text `description`, an optional `new_consent_document_id` naming a replacement consent document to be approved atomically with the amendment, and the optional `expected_protocol_version` of §2.8. The request body — `scope` and `description` — is parsed and validated before the ownership and state gates run, so a malformed filing draws `ERR_VALIDATION` ahead of `ERR_FORBIDDEN` or `ERR_INVALID_STATE`. The protocol must be `APPROVED` — with one carve-out: while a protocol is `SUSPENDED`, only a `MINOR` safety amendment may be filed, and attempting a `MAJOR` one is rejected with `ERR_INVALID_STATE`. A `new_consent_document_id` is not validated at filing time; the referenced document is examined only at approval. Filing a modification itself mutates the protocol, incrementing its `version` by one, which is exactly the staleness the OCC field protects subsequent filers against. New modifications open in `SUBMITTED`. A protocol's amendments list with an optional `status` filter, and the amendments referencing a particular consent document can be listed from that document as well.

Routing depends on scope. A `MINOR` modification may be adjudicated directly by the chair with an `outcome` of `APPROVE` or `DENY` — the chair must hold no `CONFLICTED` declaration on the protocol on either outcome, else `ERR_CHAIR_CONFLICTED`, a check that precedes the major-amendment routing gate; chair approval of a `MAJOR` modification is rejected with `ERR_MAJOR_REQUIRES_BOARD`, because major amendments are decided only by a convened board voting on an agenda item that carries the modification's `modification_id` — a passing `APPROVE` approves it, while a failed `APPROVE` or a passing `REQUIRE_CHANGES` denies it. Approval carries one referential gate and one cascade. When `new_consent_document_id` is set, that document must exist (else `ERR_CONSENT_DOC_NOT_FOUND`) and must currently be `SUBMITTED`, else `ERR_CONSENT_DOC_NOT_SUBMITTED`; on approval the named document moves to `APPROVED` and the protocol's previously `APPROVED` document moves to `SUPERSEDED`, conserving the single-approved-document invariant. Every modification approval — by the chair or by the board — increments the protocol's `version` again, whether or not a replacement consent document is attached. Denial — by chair `DENY` or by the board outcomes above — moves the modification to `DENIED`.

Continuing review enforces the federal check-in cadence on approved studies. The first cycle is created at protocol approval (§3.5) with `due_at` set to the approval instant plus the protocol's `continuing_review_interval_days` and `window_opens_at` sixty days before the due date. A protocol's continuing-review cycles can be listed with an optional `status` filter. The owning PI submits the cycle while it sits in `PENDING_SUBMISSION` or `CHANGES_REQUESTED` — any other status draws `ERR_INVALID_STATE`, and this state gate runs before the ownership check, under which acting on another investigator's cycle draws `ERR_FORBIDDEN`. Submission is accepted only inside the window: before `window_opens_at` the submit is rejected with `ERR_CR_WINDOW_NOT_OPEN`, and once the current time has passed `due_at` the sweep will already have moved the cycle to `LAPSED`. Both window bounds are inclusive — submitting exactly at the window's opening or exactly at the due date is accepted — and a successful submit stamps `submitted_at` and moves the cycle to `SUBMITTED`.

The chair adjudicates a submitted cycle with an `outcome` of `APPROVE` or `REQUIRE_CHANGES`; the chair must hold no `CONFLICTED` declaration on the protocol, else `ERR_CHAIR_CONFLICTED`, evaluated before the cycle's state gates. Approval extends the study: `approval_expires_at` becomes the adjudication instant plus the protocol's interval, and the next cycle springs into existence with its `cycle_index` incremented by one, a freshly computed `due_at` and `window_opens_at`, and status `PENDING_SUBMISSION`. A `REQUIRE_CHANGES` outcome returns the cycle to `CHANGES_REQUESTED` for the PI to revise and resubmit inside the same window.

Lapse is the sweep's job. A cycle in `PENDING_SUBMISSION` or `SUBMITTED` whose `due_at` falls strictly before the current logical time moves to `LAPSED` — sitting exactly at `due_at` still counts as open — and the lapse cascades in three linked steps: the protocol moves `APPROVED` → `EXPIRED`, halting enrollment (this transition applies only to a protocol currently `APPROVED`); a non-compliance case of source `LAPSED_CR` opens in `OPENED` whatever state the protocol sits in; and the investigator's provisional score is recomputed with the new open case weighing five points. Recovery runs through the same adjudication endpoint: approving a `LAPSED` cycle — legal only while the protocol is `EXPIRED`, anything else drawing `ERR_INVALID_STATE` — returns the protocol from `EXPIRED` to `APPROVED`, recomputes `approval_expires_at` from the adjudication instant, and creates the next cycle, while the `LAPSED_CR` case deliberately stays open until the compliance process of §3.8 investigates and closes it. Exempt studies escape this machinery entirely — an `EXEMPT_ACTIVE` protocol holds no continuing reviews and a null `approval_expires_at` — and closing a protocol renders any cycle in `PENDING_SUBMISSION`, `SUBMITTED`, or `CHANGES_REQUESTED` moot by moving it to `APPROVED`, with no further sweep action against it.

### 3.8. Adverse Events, Non-Compliance, Suspension, and Reinstatement

Safety reporting continues for as long as a study is open to subjects. The owning PI files a report on a protocol in `APPROVED`, `SUSPENDED`, `EXPIRED`, or `EXEMPT_ACTIVE` — the post-approval reporting states — supplying an `event_type` of `SERIOUS_ADVERSE_EVENT`, `UNANTICIPATED_PROBLEM`, or `PROTOCOL_DEVIATION_WITH_HARM`, the `occurred_at` instant, and a narrative `description`. An `occurred_at` after the current logical time is rejected with `ERR_AE_OCCURRED_IN_FUTURE`. The server stamps `reported_at` at creation and immediately computes timeliness: `deadline_at` is `occurred_at` plus five days for a serious adverse event or an unanticipated problem, or plus fifteen days for a protocol deviation with harm, and `is_late` is true only when `reported_at` falls strictly after `deadline_at` — a report filed exactly at its deadline is on time. New reports stand in `FILED`; a protocol's reports list with an optional `status` filter.

A `ComplianceOfficer` then triages the report, optionally recording a `triage_note`, moving it `FILED` → `TRIAGED`. Triage of a late report has teeth: the system opens a non-compliance case of source `LATE_AE` in `OPENED` on the protocol and recomputes the investigator's provisional score, where the five-point open-case deduction replaces the eight-point late-unfiled deduction now that the report has left `FILED`. Disposition closes the matter from `TRIAGED`: a `disposition` of `CLOSED_NO_ACTION` simply terminates the report, while `CLOSED_WITH_ACTION` records an `action_type` of `REQUIRE_MODIFICATION` or `SUSPEND_PROTOCOL`. Choosing `SUSPEND_PROTOCOL` opens a further case of source `AE_ACTION` whatever state the protocol sits in, and — only against a protocol in `APPROVED` or `EXEMPT_ACTIVE` — fires the full suspension cascade below.

The compliance-score ledger underpins every gate in this section. Both scores start from a base of 100. The `final_compliance_score` deducts 20 points per confirmed finding — cases with `finding_confirmed` true sitting in `FINDING_CONFIRMED` or `CLOSED`. The `provisional_compliance_score` deducts those same confirmed findings and, on top, 5 points per case in `OPENED` or `INVESTIGATION` and 8 points per late report still standing in `FILED`. Everything is counted across all of the investigator's protocols regardless of protocol status, and the scores are recomputed whenever a case opens, a finding issues, a case closes, or a late report arrives or is triaged. When the `final_compliance_score` drops below 60, the investigator's `status` flips to `DEBARRED`, which in turn blocks every future submission per §3.2; the flip is one-way, and a later score recovery does not restore `ACTIVE`.

Every case carries a `source` recording how it came to exist: `LATE_AE` when triage of a late report opened it, `LAPSED_CR` when the clock sweep opened it, `AE_ACTION` when a suspend-protocol disposition opened it, or `MANUAL` when an officer created it directly. Beyond the automatic openings, a compliance officer may open a `MANUAL` case on a protocol with a mandatory free-text `reason`; `opened_at` records the logical instant. The case lifecycle runs `OPENED` → `INVESTIGATION` via open-investigation, then to a finding: issuing `finding` `CONFIRMED` moves the case to `FINDING_CONFIRMED`, sets `finding_confirmed` true, recomputes the investigator's scores with the new twenty-point deduction and the debarment check, and — when the protocol is `APPROVED` or `EXEMPT_ACTIVE` — suspends it. Issuing `finding` `NOT_CONFIRMED` moves the case to `FINDING_NOT_CONFIRMED`, sets `finding_confirmed` false, and recomputes the scores so the five-point open-case deduction lifts. Either finding state closes to `CLOSED` with an optional `closure_note` (accepted but not persisted on the case); closing from anywhere else is rejected with `ERR_INVALID_STATE`. A protocol's cases list with an optional `status` filter.

Suspension itself is always a system cascade, never a hand-set state. Whether triggered by a confirmed finding or by a suspend-protocol disposition, the protocol first records its `pre_suspension_state` — `APPROVED` or `EXEMPT_ACTIVE` — then moves to `SUSPENDED`; findings issued against protocols in any other state are recorded without suspension. The cascade then propagates in three links: every reliance agreement of the protocol in `EXECUTED` moves to `SUSPENDED`; every agenda item of the protocol still `LISTED` on a `SCHEDULED` meeting moves to `REMOVED` with the meeting's `item_count` recomputed; and any meeting whose `item_count` reaches zero through those removals moves to `CANCELLED`.

Reinstatement is the chair's deliberate undo, and it is deliberately asymmetric. The protocol must sit in `SUSPENDED` (else `ERR_INVALID_STATE`), and no non-compliance case of the protocol may remain in `OPENED`, `INVESTIGATION`, or `FINDING_CONFIRMED` — open cases block reinstatement with `ERR_OPEN_CASES_REMAIN`. A clean reinstatement returns the protocol to its recorded `pre_suspension_state`, clears that field, and flips every reliance agreement of the protocol from `SUSPENDED` back to `EXECUTED`. Removed agenda items, however, are not restored; a coordinator who still wants the matter heard must re-list it under §3.6. Closure is the PI's counterpart for a finished study: the owning PI may close a protocol in `APPROVED` or `EXEMPT_ACTIVE`, subject to the same open-cases check (`ERR_OPEN_CASES_REMAIN`), moving it to the terminal `CLOSED` state and mooting its continuing reviews per §3.7.

### 3.9. Reliance Agreements for Multi-Site Studies

Multi-site studies distribute review through reliance agreements, administered by an `IrbAdmin`. Creating an agreement names the `protocol_id` of the multi-site study, the `ceding_institution_code` of the institution ceding review, the `reviewing_institution_code` of the institution providing review, and an effectiveness window from `effective_start_date` to `effective_end_date`. The window is a closed interval — both endpoints inclusive — and a start date later than the end date is rejected with `ERR_INVALID_DATE_RANGE`. The referenced protocol must not stand in a terminal state (`DISAPPROVED`, `WITHDRAWN`, or `CLOSED`); otherwise the creation is rejected with `ERR_INVALID_STATE`. The terminal-state check runs before the window-validity check, so a creation failing both draws `ERR_INVALID_STATE`. New agreements stand in `PROPOSED`, and the registry lists with optional `protocol_id`, `ceding_institution_code`, and `status` filters.

Execution activates the agreement and carries three gates: the agreement must be `PROPOSED` (else `ERR_INVALID_STATE`); the protocol must be `APPROVED` — a cross-entity gate failing with `ERR_PROTOCOL_NOT_APPROVED`; and no other `EXECUTED` agreement may exist for the same protocol and ceding institution whose closed window intersects the new one, with the boundary rule that windows touching at a single shared date do intersect, a violation drawing `ERR_RELIANCE_WINDOW_OVERLAP` (HTTP 409). Each execution is also a billing event per §2.7: one rounded site line — the 74,999-cent reliance base multiplied by the protocol's industry multiplier and rounded half-up — is added onto the protocol's `settled_fee_cents`, and `fee_delta_cents` is recomputed against `provisional_fee_cents`.

Thereafter the agreement rides the protocol's fortunes: a protocol suspension moves every `EXECUTED` agreement to `SUSPENDED`, and reinstatement moves it back to `EXECUTED`. Either of those non-terminal states may also be terminated outright by the administrator, moving the agreement to the terminal `TERMINATED` state; termination attempts from any other state are rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. The clock-control endpoint returns `200 OK`. Request payloads, preconditions, and side effects for each operation are specified by the workflows of §3; this table is the routing and authorization reference.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the scheduled sweeps | IrbAdmin |
| POST | `/irb/investigators` | Register an investigator | IrbAdmin |
| GET | `/irb/investigators/{id}` | Fetch one investigator | Any |
| GET | `/irb/investigators` | List investigators | Any |
| POST | `/irb/irb-members` | Register an IRB member | IrbAdmin |
| GET | `/irb/irb-members/{id}` | Fetch one member | Any |
| GET | `/irb/irb-members` | List members | Any |
| POST | `/irb/irb-members/{id}/deactivate` | Deactivate a member | IrbAdmin |
| POST | `/irb/irb-members/{id}/reactivate` | Reactivate a member | IrbAdmin |
| POST | `/irb/protocols` | Create a draft protocol | PrincipalInvestigator |
| GET | `/irb/protocols/{id}` | Fetch one protocol | Any |
| GET | `/irb/protocols` | List protocols | Any |
| POST | `/irb/protocols/{id}/submit` | Submit or resubmit a protocol | PrincipalInvestigator |
| POST | `/irb/protocols/{id}/return` | Return a submitted protocol for completion | IrbCoordinator |
| POST | `/irb/protocols/{id}/determinations` | Record the review-level determination | IrbCoordinator |
| POST | `/irb/protocols/{id}/expedited-determination` | Chair decision on an expedited review | IrbChair |
| POST | `/irb/protocols/{id}/withdraw` | Withdraw a protocol | PrincipalInvestigator |
| POST | `/irb/protocols/{id}/close` | Close an approved or exempt protocol | PrincipalInvestigator |
| POST | `/irb/protocols/{id}/reinstate` | Reinstate a suspended protocol | IrbChair |
| POST | `/irb/protocols/{id}/consent-documents` | Upload a consent document version | PrincipalInvestigator |
| GET | `/irb/consent-documents/{id}` | Fetch one consent document | Any |
| GET | `/irb/protocols/{id}/consent-documents` | List a protocol's consent documents | Any |
| GET | `/irb/consent-documents/{id}/modifications` | List modifications referencing a consent document | Any |
| POST | `/irb/consent-documents/{id}/review` | Chair review of a consent document | IrbChair |
| POST | `/irb/protocols/{id}/review-assignments` | Offer a review assignment (explicit or auto-selected reviewer) | IrbCoordinator |
| GET | `/irb/review-assignments/{id}` | Fetch one assignment | Any |
| GET | `/irb/review-assignments` | List assignments | Any |
| POST | `/irb/review-assignments/{id}/respond` | Reviewer responds to an offer | Reviewer |
| POST | `/irb/review-assignments/{id}/recommendations` | Reviewer files a recommendation | Reviewer |
| POST | `/irb/protocols/{id}/conflict-declarations` | Reviewer self-declares a conflict | Reviewer |
| GET | `/irb/conflict-declarations/{id}` | Fetch one declaration | Any |
| GET | `/irb/conflict-declarations` | List declarations | Any |
| POST | `/irb/conflict-declarations/{id}/adjudicate` | Chair clears or confirms a conflict | IrbChair |
| POST | `/irb/board-meetings` | Schedule a board meeting | IrbCoordinator |
| GET | `/irb/board-meetings/{id}` | Fetch one meeting | Any |
| GET | `/irb/board-meetings` | List meetings | Any |
| POST | `/irb/board-meetings/{id}/agenda-items` | List a protocol on a meeting agenda (OCC-guarded) | IrbCoordinator |
| GET | `/irb/board-meetings/{id}/agenda-items` | List a meeting's agenda in deliberation order | Any |
| GET | `/irb/agenda-items/{id}` | Fetch one agenda item | Any |
| GET | `/irb/agenda-items` | List agenda items | Any |
| POST | `/irb/board-meetings/{id}/convene` | Convene a meeting with an attendee roster | IrbChair |
| POST | `/irb/board-meetings/{id}/adjourn` | Adjourn a convened meeting | IrbChair |
| POST | `/irb/board-meetings/{id}/reschedule` | Reschedule a failed-quorum meeting | IrbCoordinator |
| POST | `/irb/agenda-items/{id}/vote` | Record the vote tally on an agenda item | IrbChair |
| POST | `/irb/protocols/{id}/modifications` | File a modification request (OCC-guarded) | PrincipalInvestigator |
| GET | `/irb/modifications/{id}` | Fetch one modification | Any |
| GET | `/irb/protocols/{id}/modifications` | List a protocol's modifications | Any |
| POST | `/irb/modifications/{id}/adjudicate` | Chair adjudication of a minor modification | IrbChair |
| GET | `/irb/continuing-reviews/{id}` | Fetch one continuing review | Any |
| GET | `/irb/protocols/{id}/continuing-reviews` | List a protocol's continuing reviews | Any |
| POST | `/irb/continuing-reviews/{id}/submit` | Submit a continuing review inside its window | PrincipalInvestigator |
| POST | `/irb/continuing-reviews/{id}/adjudicate` | Chair adjudication of a continuing review | IrbChair |
| POST | `/irb/protocols/{id}/adverse-events` | File an adverse-event or unanticipated-problem report | PrincipalInvestigator |
| GET | `/irb/adverse-events/{id}` | Fetch one report | Any |
| GET | `/irb/protocols/{id}/adverse-events` | List a protocol's reports | Any |
| POST | `/irb/adverse-events/{id}/triage` | Triage a filed report | ComplianceOfficer |
| POST | `/irb/adverse-events/{id}/disposition` | Dispose of a triaged report, with or without action | ComplianceOfficer |
| POST | `/irb/protocols/{id}/non-compliance-cases` | Open a manual non-compliance case | ComplianceOfficer |
| GET | `/irb/non-compliance-cases/{id}` | Fetch one case | Any |
| GET | `/irb/protocols/{id}/non-compliance-cases` | List a protocol's cases | Any |
| POST | `/irb/non-compliance-cases/{id}/open-investigation` | Move a case into investigation | ComplianceOfficer |
| POST | `/irb/non-compliance-cases/{id}/issue-finding` | Issue a confirmed or not-confirmed finding | ComplianceOfficer |
| POST | `/irb/non-compliance-cases/{id}/close` | Close a case after its finding | ComplianceOfficer |
| POST | `/irb/reliance-agreements` | Create a proposed reliance agreement | IrbAdmin |
| GET | `/irb/reliance-agreements/{id}` | Fetch one agreement | Any |
| GET | `/irb/reliance-agreements` | List agreements | Any |
| POST | `/irb/reliance-agreements/{id}/execute` | Execute a proposed agreement | IrbAdmin |
| POST | `/irb/reliance-agreements/{id}/terminate` | Terminate an executed or suspended agreement | IrbAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified throughout §2 and §3; this catalogue is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVESTIGATOR_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_PROTOCOL_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_DOC_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DECLARATION_NOT_FOUND` | 404 Not Found |
| `ERR_MEETING_NOT_FOUND` | 404 Not Found |
| `ERR_AGENDA_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_MODIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_CR_NOT_FOUND` | 404 Not Found |
| `ERR_AE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_RELIANCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVESTIGATOR_DEBARRED` | 422 Unprocessable Entity |
| `ERR_PI_TRAINING_LAPSED` | 422 Unprocessable Entity |
| `ERR_COMPLIANCE_SCORE_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_NO_CONSENT_DOCUMENT` | 422 Unprocessable Entity |
| `ERR_NO_APPROVED_CONSENT` | 422 Unprocessable Entity |
| `ERR_WAIVER_CRITERIA_NOT_MET` | 422 Unprocessable Entity |
| `ERR_EXEMPT_REQUIRES_MINIMAL_RISK` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_RECOMMENDATIONS` | 422 Unprocessable Entity |
| `ERR_EXPEDITED_DISAPPROVE_REQUIRES_BOARD` | 422 Unprocessable Entity |
| `ERR_REVIEWER_CONFLICTED` | 422 Unprocessable Entity |
| `ERR_CHAIR_CONFLICTED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_NO_ELIGIBLE_REVIEWER` | 422 Unprocessable Entity |
| `ERR_ATTENDEE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_QUORUM_COMPOSITION_MISSING` | 422 Unprocessable Entity |
| `ERR_VOTE_TALLY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AGENDA_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_AGENDA_LISTING` | 409 Conflict |
| `ERR_MEETING_ROOM_CONFLICT` | 409 Conflict |
| `ERR_RELIANCE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MAJOR_REQUIRES_BOARD` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_CR_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_AE_OCCURRED_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_PROTOCOL_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_CONSENT_DOC_NOT_SUBMITTED` | 422 Unprocessable Entity |
| `ERR_OPEN_CASES_REMAIN` | 422 Unprocessable Entity |
| `ERR_STALE_PROTOCOL_VERSION` | 412 Precondition Failed |
| `ERR_STALE_MEETING_VERSION` | 412 Precondition Failed |
