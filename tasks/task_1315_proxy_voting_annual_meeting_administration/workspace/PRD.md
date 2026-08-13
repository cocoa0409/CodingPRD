# Proxy Voting & Annual Meeting Administration API — Product Requirements Document

## 1. Introduction

Public-company proxy administration is a regulated, deadline-driven business in which a single miscounted share can invalidate an entire shareholder meeting. This document specifies the Proxy Voting & Annual Meeting Administration API: a system in the style of a Broadridge proxy agent that carries an issuer's meeting from the initial record-date shareholder list through distribution of proxy materials, multi-channel vote tabulation, quorum determination by an independent inspector, and final certification of results with the associated regulatory filing.

The API serves five distinct operator populations — the proxy agent's own operations staff, the issuer's transfer agent, registered shareholders, broker/dealer respondents, and an independent inspector of election — and enforces strict segregation of duties between them. Because vote instructions form an ordered event stream in which the latest valid instruction wins, and because tallies must be viewable both as live provisional figures and as final certified numbers, the system maintains dual computation variants for every rollup it produces. Compliance artifacts (the inspector's certification snapshot and the 8-K results filing) are first-class resources whose creation and signing are gated by explicit concurrency and conflict-of-interest controls.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. A request that is missing either header, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles:

- `ProxyAdministrator` — proxy agent operations staff. Owns the meeting lifecycle (creation, amendment, record-date lock, opening voting, convening, adjournment, reconvening, conclusion, cancellation, and the 8-K filing), proxy material generation and delivery outcomes, agenda proposals and withdrawals, virtual platform sessions, solicitation campaigns, question moderation, in-person vote capture, and the test-driving clock.
- `TransferAgent` — the issuer's transfer agent. Builds the record-date shareholder list and initiates broker searches; may also update a holder's delivery preferences.
- `Shareholder` — a registered holder on the record-date list. Votes over remote channels, manages its own delivery preferences, submits and resubmits meeting questions, and revokes its own votes.
- `Broker` — a broker/dealer respondent. Answers broker search requests with omnibus share positions and submits omnibus votes over the broker channel.
- `InspectorOfElection` — the independent inspector. Raises and adjudicates vote challenges, and creates and signs result certifications.

When `X-User-Role` is `Shareholder`, `X-User-ID` is the `id` of the acting `ShareholderAccount`; ownership checks on any resource that references a shareholder account — the account itself, a vote instruction, or a question submission — compare the resource's account foreign-key field to `X-User-ID`. A `Shareholder` may therefore read only its own account record, its own votes, and its own questions, and may act only on resources tied to its own account. When `X-User-Role` is `ProxyAdministrator`, `TransferAgent`, `Broker`, or `InspectorOfElection`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on an `InspectorCertification`) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept resource-specific filter parameters in addition to `limit` and `offset`: meetings filter by `status` and `meeting_type`; shareholder accounts by `meeting_id`, `status`, and `delivery_preference`; broker search records by `meeting_id` and `status`; material distribution packages by `meeting_id`, `status`, `channel`, `representative_account_id`, and `covered_account_ids`; proposals by `meeting_id` and `status`; vote instructions by `meeting_id`, `proposal_id`, `account_id`, `channel`, and `status`; platform sessions by `meeting_id` and `session_type`; question submissions by `meeting_id`, `account_id`, and `status`; vote challenges by `meeting_id`, `vote_instruction_id`, and `status`; solicitation campaigns by `meeting_id` and `soliciting_party`; and inspector certifications by `meeting_id` and `status`.

### 2.4. The Logical Clock

All system-generated timestamps and all temporal checks in the API read a single logical clock — never the host's wall-clock time. At server startup the logical clock is set to exactly `2026-08-01T00:00:00Z` and the server must not fall back to wall-clock time under any circumstance. A `ProxyAdministrator` may advance the logical clock through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value; the capability responds with the resulting `current_utc`. Creation timestamps, modification timestamps, filing timestamps, and the convene-time comparison against `meeting_datetime` all consult this clock.

### 2.5. Common Resource Properties

Every resource in the system — meetings, shareholder accounts, broker search records, material distribution packages, proposals, vote instructions, platform sessions, question submissions, vote challenges, solicitation campaigns, and inspector certifications — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created; sourced from the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

Every mutation is visible in the response of the call that performed it; derived rollups such as quorum and tabulation figures are recomputed whenever an underlying vote changes.

### 2.6. Request Validation Order

When several validation rules could reject the same request, the server applies them in a fixed precedence order so that the failure surfaced to the caller is deterministic:

1. **Authentication.** Presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`).
2. **Authorization.** Whether the role is permitted on the endpoint, whether a `Shareholder` is acting on its own account resources, and whether the vote channel matches the role (`ERR_FORBIDDEN`).
3. **Existence.** Every identifier in the request path, validated left to right, with the resource-specific not-found error (for example `ERR_MEETING_NOT_FOUND` before `ERR_PROPOSAL_NOT_FOUND` when both appear in a path). Each resource type has its own code: `ERR_MEETING_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`, `ERR_QUESTION_NOT_FOUND`, `ERR_CHALLENGE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_BROKER_SEARCH_NOT_FOUND`, and `ERR_CERTIFICATION_NOT_FOUND`.
4. **State.** Whether the target resource's lifecycle state permits the operation (`ERR_INVALID_MEETING_STATE` and its resource-specific counterparts).
5. **Segregation of duties.** The certification signer's conflict-of-interest check (`ERR_SEGREGATION_OF_DUTIES`).
6. **Temporal ordering.** Record-date ordering, convene-time, and window-ordering rules (`ERR_RECORD_DATE_INVALID`, `ERR_MEETING_NOT_YET_STARTED`, and window-shape failures reported as `ERR_INVALID_REQUEST`).
7. **Cross-meeting referential integrity.** Body-referenced resources resolving to the request's meeting (`ERR_CROSS_MEETING_REFERENCE`).
8. **Domain constraints.** Uniqueness, control-number, share-range, choice-compatibility, mode-compatibility, overlap, gating, and quorum rules (the specific error codes named in §3).
9. **Optimistic concurrency.** The `expected_meeting_version` check on the two endpoints that carry it (`ERR_STALE_VERSION`).
10. **Request body shape.** Required fields present, enum values valid, numbers in range, datetimes parseable (`ERR_INVALID_REQUEST`). Structural request errors are reported last — after authentication and authorization, so that unauthenticated or forbidden calls fail closed, and after the existence, state, and domain rules above, which take precedence.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control against the meeting's version counter, and both require the field `expected_meeting_version` as a non-optional input carrying the client's last observed `version` of the meeting:

- Amending a meeting's parameters. If the meeting's current `version` has advanced beyond the supplied value — because another writer amended the meeting or drove a lifecycle transition since the client last read it — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Signing an inspector certification. The same comparison is made against the meeting's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the signer from certifying against a meeting state it has not observed.

Endpoints not named above do not take a version field.

### 2.8. Two Lenses on Every Tally

Every computed voting figure in the system exists in two variants, and readers must be explicit about which lens they are using:

- Quorum is computed as `PROVISIONAL` (the default read variant while voting is in progress) or `FINAL` (used at meeting conclusion, at certification creation, and whenever explicitly requested). The `FINAL` variant excludes votes that are under an open challenge and adds shares physically present at the meeting without a voted proxy; the `PROVISIONAL` variant includes challenged-but-still-valid votes and never counts walk-in shares.
- Proposal tabulation is computed as `UNOFFICIAL` (the default read variant at any time before or after the meeting) or `CERTIFIED` (used at certification creation and signing, and whenever explicitly requested). The `CERTIFIED` variant excludes votes with an open challenge, so it can reach a different outcome than `UNOFFICIAL` on identical raw data.

Both computed reads accept a `variant` query parameter selecting the lens; omitting it yields the default variant named above.

### 2.9. Share-Class Weighting and Basis-Point Precision

Voting power is share-weighted by class. Each account's `share_class` is either `COMMON`, carrying a vote weight of 1.0 per share, or `PREFERRED`, carrying a vote weight of 0.5 per share. All tabulation arithmetic converts each vote instruction to a whole number of weighted votes by multiplying its `shares_voted` by the weight of its account's class and rounding the product half up to an integer; this per-instruction rounding happens **before** any summation, and that order is pinned — summing first and rounding the total is not an acceptable substitute. Quorum arithmetic is performed in integer basis points: both the quorum percentage and the threshold are scaled by ten thousand and rounded half up to whole basis points before comparison. Share counts themselves are integers and are never rounded.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Meeting

A `ProxyAdministrator` opens an engagement by creating the **Meeting** resource, supplying the issuer's `company_name` and `ticker`, the `meeting_type` (`ANNUAL`, `SPECIAL`, or `CONTESTED`), the `record_date` in `YYYY-MM-DD` form, the scheduled `meeting_datetime` as an ISO 8601 UTC instant, the `meeting_mode` (`IN_PERSON`, `VIRTUAL`, or `HYBRID`), the `quorum_threshold_pct` expressed as a fraction that must be greater than zero and at most one, and the `outstanding_shares` as of the record date, which must be a positive integer. A new meeting begins in `DRAFT` status. The `record_date` must fall strictly before the `meeting_datetime`; this ordering is enforced at creation, on every amendment, and again at record-date lock, with violations rejected as `ERR_RECORD_DATE_INVALID`.

While the meeting remains in `DRAFT` or `RECORD_DATE_LOCKED`, the administrator may amend `quorum_threshold_pct`, `meeting_datetime`, `meeting_mode`, or `outstanding_shares`. The amendment request must carry `expected_meeting_version` per §2.7, and a successful amendment increments the meeting's `version` by one. A meeting that has not yet distributed materials may be abandoned entirely: cancellation is permitted from `DRAFT` or `RECORD_DATE_LOCKED` and moves the meeting to the terminal `CANCELLED` state, incrementing `version`; any later state is not cancellable and the attempt is rejected with `ERR_INVALID_MEETING_STATE`.

The meeting resource also carries two system fields that stay null until the very end of the lifecycle — `filed_at` and `filing_reference`, populated only when results are filed — and a `walk_in_shares` counter, initially zero, that records shares present at the meeting without a voted proxy and is counted only by the `FINAL` quorum variant.

### 3.2. Building the Record-Date List and Running the Broker Search

With a meeting in `DRAFT`, the `TransferAgent` builds the record-date list one holder at a time. Each **ShareholderAccount** is created with the `meeting_id` it belongs to, the registered `holder_name`, an `account_number` that must be unique within the meeting (duplicates are rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER`), a `share_class`, the `shares_held` on the record date as a positive integer, and delivery attributes: an optional `address_key` (the normalized mailing-address key used for householding), an optional `email`, a `delivery_preference` of `NOTICE_AND_ACCESS`, `FULL_MAIL`, or `E_DELIVERY` (defaulting to `NOTICE_AND_ACCESS`), and a `householding_opt_out` flag (defaulting to `false`) which, when true, guarantees the holder always receives an individual package. At creation the system mints the holder's `control_number` — a 12-digit number printed on the holder's materials and required on remote-channel votes — and sets the account's `status` to `PENDING`. Accounts may only be added while the meeting is `DRAFT`; the attempt against any later state fails with `ERR_INVALID_MEETING_STATE`.

Locking the record date is the point of no return for the holder list. The `ProxyAdministrator` performs the lock, which requires the meeting to be in `DRAFT`, requires the record-date ordering to hold, and requires at least one shareholder account to exist for the meeting; failures surface as `ERR_INVALID_MEETING_STATE` or, for the date ordering, `ERR_RECORD_DATE_INVALID`. The lock snapshots the list: every account of the meeting transitions `PENDING → ELIGIBLE`, and the meeting moves `DRAFT → RECORD_DATE_LOCKED` with its `version` incremented by one.

Once the list is locked, the `TransferAgent` initiates the **broker search** — the process of asking each broker/dealer how many omnibus shares it holds for beneficial owners. A broker search record is created with the meeting's `meeting_id`, a `broker_code` unique within the meeting (`ERR_DUPLICATE_BROKER_CODE` on collision), and the `broker_name`; the meeting must be in `RECORD_DATE_LOCKED` or `MATERIALS_DISTRIBUTED`. The record begins in `REQUESTED` status, with `shares_reported` null until the broker answers. The `Broker` answers the request by reporting its omnibus `shares_reported`, which must be zero or greater; the response stores the figure on the record and transitions it from `REQUESTED` to `RESPONDED`. A record that has already been answered rejects a second response with `ERR_BROKER_SEARCH_ALREADY_RESPONDED`. The broker search must be fully resolved before voting can open: every record of the meeting still in `REQUESTED` blocks the opening of voting with `ERR_BROKER_SEARCH_INCOMPLETE`.

### 3.3. Proxy Materials: Householding and Distribution

Proxy material generation converts the locked shareholder list into delivery packages, consolidating households to cut print and postage costs. When the `ProxyAdministrator` triggers generation for a meeting, the system considers every `ELIGIBLE` account. Accounts whose `delivery_preference` is `NOTICE_AND_ACCESS` or `FULL_MAIL`, that have not set `householding_opt_out`, and that have a non-null `address_key` are grouped by the combination of their `address_key` and `delivery_preference`. Each group yields a single **MaterialDistribution** package: its `channel` is the group's shared delivery preference, its `representative_account_id` is the earliest-created account in the group (the household representative), its `covered_account_ids` lists every member account, and its `covered_shares` is the sum of `shares_held` across those members. Every remaining eligible account — those electing `E_DELIVERY`, those that opted out of householding, and those with no `address_key` — receives an individual package whose representative and sole covered account is itself and whose `covered_shares` equals its own `shares_held`. Packages are created in ascending order of their representative's creation time, and each new package starts in `ACTIVE` status.

Generation is regenerable. Any regeneration supersedes all of the meeting's existing packages that are not already `SUPERSEDED` — whether they are `ACTIVE`, `DELIVERED`, or `BOUNCED` — and builds a fresh set per the grouping rule above. The first generation for a meeting is additionally a lifecycle event: it requires the meeting to be in `RECORD_DATE_LOCKED` or `MATERIALS_DISTRIBUTED` (otherwise `ERR_INVALID_MEETING_STATE`), requires at least one proposal to exist for the meeting, moves the meeting `RECORD_DATE_LOCKED → MATERIALS_DISTRIBUTED`, flips every `DRAFT` proposal of the meeting to `ACTIVE`, and increments the meeting's `version`. Later regenerations while the meeting is `MATERIALS_DISTRIBUTED` re-run the grouping and supersede prior packages without re-activating proposals, and still increment the meeting's `version`.

Delivery is tracked per package. The administrator records a package's `delivery_outcome` as `DELIVERED` or `BOUNCED`; only an `ACTIVE` package accepts an outcome, and recording against a package in any other state is rejected with `ERR_DISTRIBUTION_NOT_ACTIVE`.

Holders may adjust how they receive materials after the fact. A `Shareholder` (for its own account only) or the `TransferAgent` may update an account's `delivery_preference` or `householding_opt_out` at any time before the meeting reaches `MEETING_HELD`; from `MEETING_HELD` onward the attempt is rejected as `ERR_INVALID_MEETING_STATE`. Such an update does not itself rebuild any packages — it takes effect at the next generation.

### 3.4. The Agenda: Proposals, Vote Capture, and Tabulation

The `ProxyAdministrator` builds the meeting's agenda as a set of **Proposal** resources while the meeting is in `DRAFT` or `RECORD_DATE_LOCKED`. Each proposal carries the `meeting_id`, a `proposal_number` unique within the meeting (`ERR_DUPLICATE_PROPOSAL_NUMBER` on collision), a `title`, a `proposal_type` of `DIRECTOR_ELECTION`, `SAY_ON_PAY`, `RATIFICATION`, or `SHAREHOLDER_PROPOSAL`, the `vote_standard` it will be judged against — `MAJORITY_OF_VOTES_CAST`, `MAJORITY_OF_OUTSTANDING`, or `PLURALITY` — and an optional `board_recommendation` of `FOR`, `AGAINST`, or `NO_RECOMMENDATION` that defaults to `FOR`. A proposal begins in `DRAFT` and is activated automatically by the first material generation. A proposal that should not go forward may be withdrawn while it is in `DRAFT` or `ACTIVE`, moving it to the terminal `WITHDRAWN` state (withdrawing a terminal proposal is rejected with `ERR_PROPOSAL_NOT_ACTIVE`); withdrawing an `ACTIVE` proposal also supersedes every `VALIDATED` vote instruction on it and triggers recomputation of the proposal's tabulation and the meeting's quorum.

Voting itself is an event stream with latest-valid-vote-wins semantics. A vote instruction is cast with the `meeting_id`, the `proposal_id`, the `account_id` doing the voting, the `channel`, the `choice`, an optional `shares_voted` (defaulting to the full `shares_held` of the account), and, for remote channels, the `control_number`. The proposal and the account referenced in the body must both belong to the meeting named in the request; a reference that resolves to a different meeting is rejected with `ERR_CROSS_MEETING_REFERENCE`. Voting is accepted only while the meeting is in `VOTING_OPEN` or `MEETING_IN_PROGRESS`; attempts at any other time fail with `ERR_VOTING_NOT_OPEN`, and a vote against a proposal that is not `ACTIVE` fails with `ERR_PROPOSAL_NOT_ACTIVE`.

The channel a caller may use is bound to its role: a `Shareholder` votes over `INTERNET`, `PHONE`, or `MAIL` and only on its own account; a `Broker` votes over the `BROKER` channel; and a `ProxyAdministrator` records `IN_PERSON` votes. A channel that does not match the caller's role, or a shareholder acting on another holder's account, is rejected with `ERR_FORBIDDEN`. Remote-channel votes — `INTERNET`, `PHONE`, and `MAIL` — must carry the account's `control_number`, and a missing or mismatched number is rejected with `ERR_INVALID_CONTROL_NUMBER`; the `BROKER` channel is exempt from the control-number check. The `shares_voted` must be greater than zero and no more than the account's `shares_held`, with violations rejected as `ERR_SHARES_EXCEED_HELD`. The `choice` must be compatible with the proposal type: `FOR`, `AGAINST`, and `ABSTAIN` are available on non-director proposals, while a `DIRECTOR_ELECTION` proposal accepts only `FOR` or `WITHHOLD` — `WITHHOLD` on any other proposal type, or `AGAINST` or `ABSTAIN` on a director election, is rejected with `ERR_CHOICE_NOT_ALLOWED`.

A successfully cast instruction starts in `VALIDATED`. If a newer valid instruction arrives for the same account and proposal, the older one transitions `VALIDATED → SUPERSEDED` automatically, so at most one instruction per account-and-proposal is live. A holder (its own votes only) or the administrator may also explicitly revoke a `VALIDATED` instruction while the meeting is in `VOTING_OPEN` or `MEETING_IN_PROGRESS`, moving it to `REVOKED`; revoking an instruction that is already `SUPERSEDED`, `REVOKED`, or `INVALIDATED` is rejected with `ERR_VOTE_NOT_ALTERABLE`. Supersession, revocation, invalidation, and proposal withdrawal each trigger recomputation of the affected proposal's tabulation and the meeting's quorum.

Tabulation converts the live instruction set into weighted totals. For the chosen variant, the system takes the proposal's `VALIDATED` instructions — the `CERTIFIED` variant additionally excludes any instruction with an `OPEN` challenge, while `UNOFFICIAL` includes them — and converts each instruction to weighted votes by multiplying `shares_voted` by the class weight of its account (1.0 for `COMMON`, 0.5 for `PREFERRED`), rounding each product half up to an integer before summing. The totals reported are `for_votes`, `against_votes`, `abstain_votes`, and `withhold_votes`, plus `votes_cast`, which counts only `FOR` and `AGAINST` votes — abstentions and withholds are not votes cast. The `projected_outcome` applies the proposal's standard: under `MAJORITY_OF_VOTES_CAST` the outcome is `PASS` when at least one vote has been cast and twice `for_votes` exceeds `votes_cast`, otherwise `FAIL`; under `MAJORITY_OF_OUTSTANDING` it is `PASS` when twice `for_votes` exceeds the meeting's `outstanding_shares`, otherwise `FAIL`; under `PLURALITY` it is `PASS` when `for_votes` exceeds `withhold_votes`, otherwise `FAIL`. The tabulation read reports the `proposal_id`, the `variant`, the four weighted totals, `votes_cast`, and the `projected_outcome`.

### 3.5. The Virtual Platform: Sessions and Question Moderation

Meetings conducted `VIRTUAL` or `HYBRID` run on a virtual platform whose schedule is booked in advance. A `ProxyAdministrator` books a **MeetingPlatformSession** with the `meeting_id`, a `session_type` of `REHEARSAL` or `LIVE`, and a half-open window from `start_at` to `end_at`, where `end_at` must fall strictly after `start_at` (a malformed window is rejected with `ERR_INVALID_REQUEST`). Sessions of the same meeting may not overlap: a new window that overlaps an existing session is rejected with `ERR_SESSION_OVERLAP`, though windows that merely touch — one ending exactly when the next begins — are permitted. Once booked, a session is immutable and remains in `SCHEDULED` status. Booking a session for an `IN_PERSON` meeting makes no sense and is rejected with `ERR_MEETING_MODE_INCOMPATIBLE`.

Shareholders engage with the meeting through **QuestionSubmission** resources. A `Shareholder` submits a question with the `meeting_id`, its own `account_id`, and non-empty `question_text`; submission is accepted only for `VIRTUAL` or `HYBRID` meetings (`ERR_MEETING_MODE_INCOMPATIBLE` otherwise) and only while the meeting is in `VOTING_OPEN` or `MEETING_IN_PROGRESS` (`ERR_INVALID_MEETING_STATE` at other times). A new question starts in `SUBMITTED`. The `ProxyAdministrator` moderates each `SUBMITTED` question with an `action` of `APPROVE`, `REJECT`, or `RETURN` and an optional `moderation_note`, which is stored on the question; the question moves to `APPROVED`, `REJECTED`, or `RETURNED` accordingly, and moderating a question that is no longer `SUBMITTED` fails with `ERR_INVALID_QUESTION_STATE`. A `RETURNED` question is not dead: the shareholder may resubmit it with replacement `question_text`, which clears the `moderation_note` back to null and returns the question to `SUBMITTED`. Resubmission is restricted to the question's owning account (`ERR_FORBIDDEN`) and to questions currently `RETURNED` (`ERR_INVALID_QUESTION_STATE`).

### 3.6. Contested Meetings and Solicitation Campaigns

A meeting whose `meeting_type` is `CONTESTED` opens a second front: competing parties contacting shareholders. Each **SolicitationCampaign** is booked by the `ProxyAdministrator` with the `meeting_id`, the `soliciting_party` running the outreach (for example, the issuer or a dissident), and a contact window from `start_at` to `end_at`. Attempting to book a campaign for a meeting that is not `CONTESTED` is rejected with `ERR_MEETING_NOT_CONTESTED`. The window must be well-formed — `end_at` strictly after `start_at` — and must close no later than the meeting itself, so an `end_at` after `meeting_datetime` is rejected; both shape failures surface as `ERR_INVALID_REQUEST`. To keep any single party from monopolizing holders, windows booked by the same `soliciting_party` must be separated by at least twenty-four hours: the gap between one window's `end_at` and the next window's `start_at` must be twenty-four hours or more, in either direction, and a closer pairing is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`. Contested status also hardens quorum: as described in §3.7, a contested meeting's effective quorum threshold is never allowed to fall below one half of outstanding shares.

### 3.7. Convening the Meeting: Quorum, Adjournment, and Conclusion

With materials distributed, the `ProxyAdministrator` opens voting. Opening requires the meeting to be in `MATERIALS_DISTRIBUTED`, requires at least one proposal to be `ACTIVE` (`ERR_NO_ACTIVE_PROPOSAL`), and requires that no broker search record remain `REQUESTED` (`ERR_BROKER_SEARCH_INCOMPLETE`); success moves the meeting to `VOTING_OPEN`. When the appointed time arrives, convening moves the meeting `VOTING_OPEN → MEETING_IN_PROGRESS` — but only once the logical clock has reached the `meeting_datetime`; convening early is rejected with `ERR_MEETING_NOT_YET_STARTED`. Each of these lifecycle actions, like every meeting transition, increments the meeting's `version` by one.

While the meeting is live, attendance is measured continuously through the quorum computation. For the `PROVISIONAL` variant, shares present are the sum of `shares_voted` across the meeting's `VALIDATED` instructions, including any that carry an open challenge. For the `FINAL` variant, instructions with an `OPEN` challenge are excluded and the meeting's `walk_in_shares` are added to the sum. In both variants the effective threshold fraction is the meeting's `quorum_threshold_pct` — except that for a `CONTESTED` meeting the effective threshold is the greater of `quorum_threshold_pct` and one half. Both the effective threshold and the achieved percentage are converted to integer basis points by multiplying by ten thousand and rounding half up: the threshold becomes `threshold_bp`, and the achieved figure becomes `quorum_pct_bp`, computed from shares present divided by `outstanding_shares`. `quorum_met` is true exactly when `quorum_pct_bp` is at least `threshold_bp`. The quorum read reports the `meeting_id`, the `variant`, `shares_present`, `outstanding_shares`, `quorum_pct_bp`, `threshold_bp`, and `quorum_met`.

Business may pause without ending the meeting. Adjourning moves the meeting from `MEETING_IN_PROGRESS` to `ADJOURNED` and suspends voting — vote and revoke calls during an adjournment fail with `ERR_VOTING_NOT_OPEN` — and reconvening moves the meeting from `ADJOURNED` back to `MEETING_IN_PROGRESS`, resuming vote intake. Both transitions are restricted to their respective source states (`ERR_INVALID_MEETING_STATE`).

Concluding the meeting is gated on final quorum. The administrator concludes with an optional `walk_in_shares` figure (defaulting to zero), which is stored on the meeting; the `FINAL` quorum variant — walk-ins included — must be met at that moment, or the conclusion is rejected with `ERR_QUORUM_NOT_MET` and the meeting stays in progress. A successful conclusion moves the meeting `MEETING_IN_PROGRESS → MEETING_HELD` and closes voting permanently: no further vote or revoke calls are accepted.

### 3.8. Challenges, Certification, and the 8-K Filing

Once a meeting is in `MEETING_IN_PROGRESS`, `MEETING_HELD`, or `RESULTS_CERTIFIED`, the `InspectorOfElection` may contest individual ballots. A **VoteChallenge** is raised with the `meeting_id`, the `vote_instruction_id` of the targeted instruction, and a `reason`; the target instruction must belong to the same meeting (`ERR_CROSS_MEETING_REFERENCE`) and must currently be `VALIDATED` (`ERR_VOTE_NOT_ALTERABLE` for an instruction already out of play), and the meeting's state requirement is enforced as `ERR_INVALID_MEETING_STATE`. The challenge begins in `OPEN` with its `ruling` and `resolution_note` null. Adjudication is performed by an inspector supplying a `ruling` of `UPHELD` or `OVERRULED` and an optional `resolution_note`, which is recorded; only an `OPEN` challenge can be ruled on, otherwise `ERR_CHALLENGE_NOT_OPEN`. An `OVERRULED` ruling leaves the targeted instruction untouched. An `UPHELD` ruling invalidates the vote — the instruction moves `VALIDATED → INVALIDATED` — and the effect cascades outward: the proposal's tabulation is recomputed, the meeting's quorum is recomputed, and any `DRAFT` or `SIGNED` certification for the meeting is superseded; if the superseded certification was `SIGNED`, the meeting itself reverts `RESULTS_CERTIFIED → MEETING_HELD` and all of its `PASSED` and `FAILED` proposals return to `ACTIVE`. This cascade is the intended compensation path when a late challenge upends certified results.

Certification formalizes the outcome. An `InspectorOfElection` creates an **InspectorCertification** draft for a meeting that is `MEETING_HELD` with zero `OPEN` challenges (`ERR_UNRESOLVED_CHALLENGES` if any remain); creating a new draft supersedes any existing `DRAFT` certification for the meeting. Creation records the acting inspector's header identity in `created_by_user_id` and snapshots the final state of play: `final_quorum_met` and `final_quorum_pct_bp` from the `FINAL` quorum variant at that instant, and an `outcomes` map from each proposal's id to `PASSED` or `FAILED` per the `CERTIFIED` tabulation variant at that instant. The draft begins in `DRAFT` status.

Signing turns the draft into the official record. The signer must be an `InspectorOfElection` other than the draft's creator — a signer whose identity equals `created_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. The certification must still be in `DRAFT` (`ERR_CERTIFICATION_NOT_DRAFT`), no challenge may be `OPEN` (`ERR_UNRESOLVED_CHALLENGES`), and the request must carry `expected_meeting_version` matching the meeting's current `version` per §2.7, with a stale value rejected as `ERR_STALE_VERSION`. A successful signing moves the certification `DRAFT → SIGNED`, resolves every `ACTIVE` proposal to `PASSED` or `FAILED` according to its `CERTIFIED` tabulation outcome, advances the meeting `MEETING_HELD → RESULTS_CERTIFIED`, and increments the meeting's `version`.

The closing act is the regulatory filing. From `RESULTS_CERTIFIED`, the administrator files the results, supplying the `filing_reference`; the system stamps `filed_at` from the logical clock, records the reference, moves the meeting to the terminal `FILED_8K` state, and increments its `version`. Because a challenge adjudication can supersede a signed certification and revert the meeting to `MEETING_HELD`, the filing precondition is simply the `RESULTS_CERTIFIED` state — a meeting whose certification has been knocked out must be re-certified before it can be filed.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a lifecycle transition return `200 OK`. All endpoints are mounted under the `/proxy` prefix. Request bodies, preconditions, and side effects are specified in §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/proxy/meetings` | Create a meeting in `DRAFT` | ProxyAdministrator |
| GET | `/proxy/meetings` | List meetings with pagination | ProxyAdministrator, TransferAgent, Shareholder, Broker, InspectorOfElection |
| GET | `/proxy/meetings/{id}` | Read one meeting | ProxyAdministrator, TransferAgent, Shareholder, Broker, InspectorOfElection |
| PATCH | `/proxy/meetings/{id}` | Amend meeting parameters in `DRAFT`/`RECORD_DATE_LOCKED`; OCC on meeting version | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/lock-record-date` | Lock the record date; snapshot accounts to `ELIGIBLE` | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/open-voting` | Open voting channels | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/convene` | Convene the meeting once the logical clock reaches `meeting_datetime` | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/adjourn` | Adjourn an in-progress meeting; voting suspended | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/reconvene` | Reconvene an adjourned meeting | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/conclude` | Conclude the meeting; final quorum with walk-ins must be met | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/cancel` | Cancel a meeting in `DRAFT` or `RECORD_DATE_LOCKED` | ProxyAdministrator |
| POST | `/proxy/meetings/{id}/file-8k` | File certified results; meeting must be `RESULTS_CERTIFIED` | ProxyAdministrator |
| GET | `/proxy/meetings/{id}/quorum` | Computed quorum read; `PROVISIONAL` (default) or `FINAL` | ProxyAdministrator, TransferAgent, InspectorOfElection |
| POST | `/proxy/shareholder-accounts` | Add a record-date shareholder account; meeting must be `DRAFT` | TransferAgent |
| GET | `/proxy/shareholder-accounts` | List accounts; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection |
| GET | `/proxy/shareholder-accounts/{id}` | Read one account; shareholders see only their own | ProxyAdministrator, TransferAgent, InspectorOfElection, Shareholder |
| PATCH | `/proxy/shareholder-accounts/{id}` | Update delivery preference / householding opt-out before `MEETING_HELD` | Shareholder, TransferAgent |
| POST | `/proxy/broker-searches` | Request a broker search | TransferAgent |
| GET | `/proxy/broker-searches` | List broker search records; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection, Broker |
| GET | `/proxy/broker-searches/{id}` | Read one broker search record | ProxyAdministrator, TransferAgent, InspectorOfElection, Broker |
| POST | `/proxy/broker-searches/{id}/respond` | Broker responds with its omnibus share position | Broker |
| POST | `/proxy/material-distributions/generate` | Generate or regenerate material packages with householding consolidation | ProxyAdministrator |
| GET | `/proxy/material-distributions` | List distribution packages; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection |
| GET | `/proxy/material-distributions/{id}` | Read one package | ProxyAdministrator, TransferAgent, InspectorOfElection |
| PATCH | `/proxy/material-distributions/{id}` | Record delivery outcome for an `ACTIVE` package | ProxyAdministrator |
| POST | `/proxy/proposals` | Create an agenda proposal in `DRAFT` | ProxyAdministrator |
| GET | `/proxy/proposals` | List proposals; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection, Shareholder, Broker |
| GET | `/proxy/proposals/{id}` | Read one proposal | ProxyAdministrator, TransferAgent, InspectorOfElection, Shareholder, Broker |
| POST | `/proxy/proposals/{id}/withdraw` | Withdraw a `DRAFT` or `ACTIVE` proposal; supersedes its validated votes | ProxyAdministrator |
| GET | `/proxy/proposals/{id}/tabulation` | Computed tabulation read; `UNOFFICIAL` (default) or `CERTIFIED` | ProxyAdministrator, TransferAgent, InspectorOfElection |
| POST | `/proxy/vote-instructions` | Cast a vote; latest valid vote wins per account and proposal | Shareholder, Broker, ProxyAdministrator |
| GET | `/proxy/vote-instructions` | List vote instructions; shareholders see only their own | ProxyAdministrator, TransferAgent, InspectorOfElection, Shareholder, Broker |
| GET | `/proxy/vote-instructions/{id}` | Read one vote instruction | ProxyAdministrator, TransferAgent, InspectorOfElection, Shareholder |
| POST | `/proxy/vote-instructions/{id}/revoke` | Revoke a `VALIDATED` vote while voting is open | Shareholder, ProxyAdministrator |
| POST | `/proxy/platform-sessions` | Book a rehearsal or live session on the virtual platform | ProxyAdministrator |
| GET | `/proxy/platform-sessions` | List sessions; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection |
| GET | `/proxy/platform-sessions/{id}` | Read one session | ProxyAdministrator, TransferAgent, InspectorOfElection |
| POST | `/proxy/question-submissions` | Submit a question for a virtual/hybrid meeting | Shareholder |
| GET | `/proxy/question-submissions` | List questions; shareholders see only their own | ProxyAdministrator, InspectorOfElection, Shareholder |
| GET | `/proxy/question-submissions/{id}` | Read one question | ProxyAdministrator, InspectorOfElection, Shareholder |
| POST | `/proxy/question-submissions/{id}/moderate` | Moderate a `SUBMITTED` question | ProxyAdministrator |
| POST | `/proxy/question-submissions/{id}/resubmit` | Resubmit a `RETURNED` question with edited text | Shareholder |
| POST | `/proxy/vote-challenges` | Challenge a `VALIDATED` vote | InspectorOfElection |
| GET | `/proxy/vote-challenges` | List challenges; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection |
| GET | `/proxy/vote-challenges/{id}` | Read one challenge | ProxyAdministrator, TransferAgent, InspectorOfElection |
| POST | `/proxy/vote-challenges/{id}/adjudicate` | Rule on an `OPEN` challenge | InspectorOfElection |
| POST | `/proxy/solicitation-campaigns` | Book a solicitation contact window; contested meetings only | ProxyAdministrator |
| GET | `/proxy/solicitation-campaigns` | List campaigns; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection |
| GET | `/proxy/solicitation-campaigns/{id}` | Read one campaign | ProxyAdministrator, TransferAgent, InspectorOfElection |
| POST | `/proxy/inspector-certifications` | Create a `DRAFT` certification snapshot | InspectorOfElection |
| GET | `/proxy/inspector-certifications` | List certifications; filterable | ProxyAdministrator, TransferAgent, InspectorOfElection |
| GET | `/proxy/inspector-certifications/{id}` | Read one certification | ProxyAdministrator, TransferAgent, InspectorOfElection |
| POST | `/proxy/inspector-certifications/{id}/sign` | Sign a `DRAFT` certification; signer must differ from creator; OCC on meeting version | InspectorOfElection |
| POST | `/proxy/_clock/set_current_utc` | Set the logical clock (test-driving capability) | ProxyAdministrator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MEETING_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_PROPOSAL_NOT_FOUND` | 404 |
| `ERR_VOTE_NOT_FOUND` | 404 |
| `ERR_QUESTION_NOT_FOUND` | 404 |
| `ERR_CHALLENGE_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 |
| `ERR_BROKER_SEARCH_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_INVALID_MEETING_STATE` | 409 |
| `ERR_VOTING_NOT_OPEN` | 409 |
| `ERR_PROPOSAL_NOT_ACTIVE` | 409 |
| `ERR_VOTE_NOT_ALTERABLE` | 409 |
| `ERR_INVALID_QUESTION_STATE` | 409 |
| `ERR_CHALLENGE_NOT_OPEN` | 409 |
| `ERR_CERTIFICATION_NOT_DRAFT` | 409 |
| `ERR_BROKER_SEARCH_ALREADY_RESPONDED` | 409 |
| `ERR_DISTRIBUTION_NOT_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_MEETING_NOT_YET_STARTED` | 422 |
| `ERR_RECORD_DATE_INVALID` | 422 |
| `ERR_DUPLICATE_ACCOUNT_NUMBER` | 409 |
| `ERR_DUPLICATE_PROPOSAL_NUMBER` | 409 |
| `ERR_DUPLICATE_BROKER_CODE` | 409 |
| `ERR_INVALID_CONTROL_NUMBER` | 422 |
| `ERR_SHARES_EXCEED_HELD` | 422 |
| `ERR_CHOICE_NOT_ALLOWED` | 422 |
| `ERR_MEETING_MODE_INCOMPATIBLE` | 422 |
| `ERR_MEETING_NOT_CONTESTED` | 422 |
| `ERR_SESSION_OVERLAP` | 409 |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 |
| `ERR_NO_ACTIVE_PROPOSAL` | 422 |
| `ERR_BROKER_SEARCH_INCOMPLETE` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_UNRESOLVED_CHALLENGES` | 422 |
| `ERR_CROSS_MEETING_REFERENCE` | 422 |
| `ERR_STALE_VERSION` | 412 |
