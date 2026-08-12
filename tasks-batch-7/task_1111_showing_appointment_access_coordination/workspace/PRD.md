# Showing Access Coordination API — Product Requirements Document

## 1. Introduction

Coordinating a single property showing looks trivial until three parties with competing interests share one calendar. The buyer's agent wants fast, frictionless access; the occupant wants explicit control over when strangers walk through their home; the listing agent wants a defensible audit trail when something goes wrong. Vacant homes call for self-service lockbox access, while occupied homes demand time-boxed, human-approved entry. No-shows and last-minute cancellations burn everyone's afternoon, and the seller — the client underwriting all of this activity — expects a periodic, quantitative account of what actually happened at their front door.

This document specifies the Showing Access Coordination API, a ShowingTime-style scheduling and access service exposed under the `/showing-desk` path prefix. It governs showing-request intake with occupant approval, overlap and buffer rules for competing appointments, buyer-agent identity verification and a strike-based standing ladder, vacancy-aware access instructions with lockbox and door-code issuance and expiration, automated post-showing feedback collection, no-show and late-cancellation tracking, and a computed activity report delivered to the seller. Every deadline, access window, and expiration in the system is evaluated against a controllable logical clock, so temporal behavior is fully deterministic for operators and integrators.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The platform recognizes exactly five roles: `Anonymous`, `PlatformAdmin`, `Seller`, `ListingAgent`, and `BuyerAgent`. A request that arrives without these headers, or carrying a role value the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). When a role is entity-backed and the caller does not own the resource being acted upon, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Two roles carry an opaque identity. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the role exists solely so that a prospective agent can self-register, and the server performs no ownership comparison for it. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the platform may record it in audit trails but never compares it against any entity's `id`.

The remaining three roles are entity-backed. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a seller compare the resource's seller foreign key — for example a listing's `seller_id` — to `X-User-ID`. When `X-User-Role` is `ListingAgent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks on a listing compare the listing's `listing_agent_id` to `X-User-ID`. When `X-User-Role` is `BuyerAgent`, `X-User-ID` is likewise the `id` of the acting `Agent`; ownership checks on showing requests, access credentials, and feedback requests compare the relevant `buyer_agent_id` — held directly on the showing request, and reached through the parent showing request for credentials and feedback — to `X-User-ID`. The two agent roles are distinct capacities over the same persisted Agent records: the role header selects the capacity, while `X-User-ID` names the Agent record in both cases.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

Time inside this platform is logical, not wall-clock. Every rule in this document that says "now" — approval deadlines, access windows, strike expiration, the sweep — reads a single server-side logical clock. At startup, before any operator intervention, the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A `PlatformAdmin` may advance or set the clock through an administrative capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. All deadline and window comparisons described in §3 are evaluated against this clock at the moment the request is processed.

### 2.5. Common Resource Properties

Every primary resource — Seller, Agent, Listing, VerificationCase, BlackoutWindow, ShowingRequest, AccessCredential, FeedbackRequest, and StrikeRecord — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, and which underpins optimistic concurrency control where the API exposes it.

The ActivityEvent is the deliberate exception to this convention. As an immutable, append-only log record, it carries only `id` and `created_at`; `updated_at` and `version` are absent, because an event is never modified after being appended.

### 2.6. Nested Resource Retrieval and Existence Ordering

Requests that target nested resources are validated left-to-right along the path. Depending on the endpoint, the path may carry a generic resource `id` or a specifically named identifier — `case_id` for verification cases, `strike_id` for strikes, `window_id` for blackout windows, `credential_id` for access credentials, and `feedback_id` for feedback requests. The server confirms each path identifier in sequence and rejects the request immediately with the 404 error corresponding to the first identifier that does not resolve: `ERR_SELLER_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_SHOWING_REQUEST_NOT_FOUND`, `ERR_VERIFICATION_CASE_NOT_FOUND`, `ERR_BLACKOUT_WINDOW_NOT_FOUND`, `ERR_ACCESS_CREDENTIAL_NOT_FOUND`, `ERR_FEEDBACK_REQUEST_NOT_FOUND`, or `ERR_STRIKE_NOT_FOUND`. A request addressed at a credential under a showing request that does not exist therefore fails with `ERR_SHOWING_REQUEST_NOT_FOUND` before the credential identifier is ever examined. The same existence discipline applies to identifiers supplied in a request body: a creation payload referencing a `seller_id` or `listing_id` that does not exist is rejected with the corresponding 404 before any business rule runs.

### 2.7. The Validation Pipeline and Error Precedence

Every mutating request passes through a fixed validation pipeline, and the stages run in the order below. The first failing stage produces the response; later stages are never reached, so an earlier failure masks every later one.

1. Authentication: the headers are present and the role is recognized, else `ERR_UNAUTHENTICATED`.
2. Request shape: required fields are present, types are correct, enum values are valid, and unknown fields are rejected, else `ERR_INVALID_REQUEST`. Within this stage, rating answers `q1` through `q5` must be integers from 1 to 5 inclusive; a rating outside that range is reported as `ERR_RATING_OUT_OF_RANGE`.
3. Role authorization: the caller's role appears in the endpoint's authorized role list, else `ERR_FORBIDDEN_ROLE`.
4. Existence: path identifiers resolve, validated left-to-right, followed by body-supplied foreign keys, else the matching per-resource 404.
5. Ownership: an entity-backed caller owns the target resource — the seller owns the listing, the listing agent owns the listing, the buyer agent owns the request, credential, or feedback — else `ERR_NOT_RESOURCE_OWNER`.
6. Optimistic concurrency: where an endpoint takes a version field, the supplied expectation equals the parent's current version, else the applicable stale-version error from §2.8.
7. State preconditions: the target resource sits in the state the action requires, else the per-state 409 (`ERR_LISTING_NOT_ACTIVE`, `ERR_LISTING_ALREADY_WITHDRAWN`, `ERR_SHOWING_NOT_PENDING_APPROVAL`, `ERR_SHOWING_NOT_APPROVED`, `ERR_SHOWING_NOT_CONFIRMED`, `ERR_SHOWING_NOT_DECLINED`, `ERR_SHOWING_ALREADY_TERMINAL`, `ERR_CASE_NOT_SUBMITTED`, `ERR_CASE_NOT_REJECTED`, `ERR_STRIKE_NOT_ACTIVE`, `ERR_CREDENTIAL_NOT_REDEEMABLE`, `ERR_FEEDBACK_NOT_AVAILABLE`, or `ERR_FEEDBACK_ALREADY_SUBMITTED`).
8. Buyer-agent eligibility for intake and confirmation: the agent must be verified and not suspended, else `ERR_AGENT_NOT_VERIFIED` or `ERR_AGENT_SUSPENDED`.
9. Time-range sanity: the window's `end_at` is strictly later than its `start_at` and the duration is at most 120 minutes, else `ERR_INVALID_TIME_RANGE`.
10. Lead time: the requested start is at least the listing's minimum notice ahead of now, else `ERR_INSUFFICIENT_LEAD_TIME`.
11. Buffered overlap: the new window does not conflict with any occupancy-state request under the buffered interval rule, else `ERR_SHOWING_OVERLAP_CONFLICT`.
12. Blackout intersection: the new window does not intersect any blackout window of the listing under the closed-interval rule, else `ERR_BLACKOUT_CONFLICT`.
13. Action deadlines: the action lands inside its permitted time band — approval before the approval deadline, confirmation before the confirm-by deadline, no-show declaration only after the window has ended, redemption within the credential's active band — else the matching deadline error (`ERR_APPROVAL_DEADLINE_PASSED`, `ERR_CONFIRM_DEADLINE_PASSED`, `ERR_NO_SHOW_TOO_EARLY`, `ERR_CREDENTIAL_NOT_YET_ACTIVE`, or `ERR_CREDENTIAL_EXPIRED`).
14. Daily showing cap: the listing's per-day count has not reached its maximum, else `ERR_DAILY_SHOWING_LIMIT`.
15. Credential uniqueness: no credential in ISSUED or USED status already exists for the showing at issuance time, else `ERR_CREDENTIAL_ALREADY_ISSUED`.
16. Single open verification case: no other case of the same agent is currently SUBMITTED, else `ERR_VERIFICATION_CASE_OPEN`.
17. No-show declarability: no credential of the request has been USED, else `ERR_NO_SHOW_NOT_DECLARABLE`.

Ordering is observable behavior. On showing-request intake, for example, an insufficient-lead-time violation surfaces before any overlap conflict; an overlap conflict surfaces before a blackout conflict; and the daily cap is reported only after the window has cleared lead time, overlap, and blackout. Likewise, a caller who fails authentication never learns anything about the payload's validity, because stage one preempts stage two.

### 2.8. Optimistic Concurrency Control

Two write operations guard against stale reads through optimistic concurrency, and each names its expectation field explicitly. A scheduling-policy update on a listing must carry `expected_listing_version`, a non-optional input holding the caller's last observed `version` of that listing; if the listing's version has advanced beyond what the caller observed, the update is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412), and the caller must re-read the listing before reapplying the change. An approval-settings update on a seller must likewise carry `expected_seller_version`, a non-optional input holding the caller's last observed `version` of that seller; a mismatch is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412). A successful guarded update increments the parent's `version` by one, so every accepted write invalidates previously observed versions. No endpoint outside these two accepts a version field at all.

### 2.9. Cascading Consistency and Booking Invariants

Two numeric invariants are maintained continuously, not recomputed on read. First, a listing's `confirmed_showing_count` always equals the number of its showing requests currently in CONFIRMED status: confirmation increments it (the forward leg), and every transition out of CONFIRMED — buyer cancellation, completion, no-show declaration, or system cascade — decrements it (the compensating legs). Second, an agent's `active_strike_points` always equals the sum of the `weight` values of that agent's StrikeRecords in ACTIVE status; strike creation raises it, while forgiveness and sweep-driven expiry lower it, each change triggering a standing recompute.

Structural cascades propagate terminal decisions outward in the same request. Withdrawing a listing cancels its live requests, revokes their credentials, and cancels their pending feedback in one atomic sweep (CASCADE A, detailed in §3.2). An agent whose standing falls into SUSPENDED has every future request cancelled by the system, with the same downstream revocation and feedback cancellation for those that had been confirmed (CASCADE B, detailed in §3.6). Consistency is immediate: a cascade completes within the triggering call, and every entity mutated along the way — request, credential, feedback, listing, or agent — has its `updated_at` refreshed and its `version` incremented.

### 2.10. Temporal and Numeric Precision Conventions

Scheduling arithmetic is performed at minute precision and all timestamps are ISO 8601 in UTC. Several distinct interval conventions coexist, and the differences are contractual:

- A showing window is half-open: it occupies the time from `start_at` (inclusive) up to `end_at` (exclusive).
- The buffered overlap rule uses strict inequalities, so two windows that merely touch at a buffered boundary do not conflict.
- A blackout window is a closed interval — both its `start_at` and its `end_at` are occupied — and no buffer is applied to it, so touching either blackout boundary is a conflict.
- A credential is redeemable from its `active_from` (inclusive) until its `expires_at` (exclusive); the instant of `expires_at` itself is already too late.

Scores and rates carry their own precision. Feedback scores are rounded half-up to exactly 1 decimal place, and the rounding order — round each individual feedback score first, then average — is pinned (see §3.7). Rates on the seller activity report are rounded half-up to exactly 2 decimal places. Strike points are integers.

### 2.11. The Expiration Sweep

Time-driven transitions are applied by an administrative checkpoint, restricted to `PlatformAdmin`, which walks six steps in a pinned order:

1. Every showing request still in PENDING_APPROVAL whose `approval_deadline` has been reached or passed moves to EXPIRED.
2. Every showing request in APPROVED whose `confirm_by_deadline` has been reached or passed moves to EXPIRED.
3. Every showing request in CONFIRMED whose `end_at` has passed and for which a credential has been USED moves to COMPLETED, and its SCHEDULED feedback request flips to SENT in the same step.
4. Every credential in ISSUED whose `expires_at` has been reached or passed moves to EXPIRED.
5. Every feedback request in SENT whose `due_at` has been reached or passed moves to EXPIRED.
6. Every strike in ACTIVE whose `expires_at` has been reached or passed moves to EXPIRED, and each expired strike triggers a standing recompute on its agent.

The response summarizes the run with six counts: `requests_expired_count`, `requests_completed_count`, `credentials_expired_count`, `feedback_sent_count`, `feedback_expired_count`, and `strikes_expired_count`. Because the steps are ordered, a request completed in step 3 has its feedback emitted in the same sweep, and an agent whose strikes expire in step 6 sees standing relax within the same run.

### 2.12. The Append-Only Activity Trail

Every meaningful mutation appends an ActivityEvent to the affected listing's log. An event records the `listing_id` it belongs to, the `showing_request_id` it concerns (null for listing-level events such as pauses), an `event_type`, the `actor_role` responsible — one of `BuyerAgent`, `Seller`, `ListingAgent`, `PlatformAdmin`, or `SYSTEM` for clock- and sweep-driven actions — and a human-readable `detail` line. The event taxonomy is fixed and exhaustive: `REQUEST_CREATED`, `APPROVED`, `DECLINED`, `RESCHEDULED`, `CONFIRMED`, `CANCELLED`, `EXPIRED`, `COMPLETED`, `NO_SHOW`, `CREDENTIAL_ISSUED`, `CREDENTIAL_REDEEMED`, `CREDENTIAL_REVOKED`, `CREDENTIAL_EXPIRED`, `FEEDBACK_SENT`, `FEEDBACK_SUBMITTED`, `STRIKE_ISSUED`, `LISTING_PAUSED`, `LISTING_RESUMED`, and `LISTING_WITHDRAWN`. Events are queryable per listing or per showing request, with an optional `event_type` filter, and are visible to the seller and the listing agent.

## 3. Business Logic & Workflows

### 3.1. Onboarding Sellers and Agents; Identity Verification

A `PlatformAdmin` onboards a seller by supplying the seller's `full_name` and `contact_email`, plus two optional approval-policy fields. The `approval_timeout_minutes` field sets how long a showing request may await the occupant's decision before it becomes eligible to expire; it defaults to 240 minutes (four hours) and accepts values from 1 minute up to 10080 minutes (seven days). The `auto_approve` flag defaults to false; when set to true it waives manual occupant approval, but only for that seller's VACANT listings — an OCCUPIED listing always requires explicit occupant approval regardless of the flag. The seller may later adjust either setting through the approval-settings update, which is the version-guarded write described in §2.8 and therefore must carry the seller's current `expected_seller_version`.

Agent registration is open to the `Anonymous` role as pure self-service: the caller provides a `full_name`, a `license_number`, and a `brokerage_name`. License numbers must be unique across all registered agents. A newly registered agent is born with `verification_status` of UNVERIFIED, `standing` of GOOD_STANDING, and `active_strike_points` of zero. The `verification_status` field is computed, never set directly: an agent is VERIFIED exactly when at least one of that agent's VerificationCases sits in APPROVED status, and UNVERIFIED otherwise.

To become verified, an agent — acting in either the `ListingAgent` or `BuyerAgent` capacity — files a VerificationCase for themselves with a `license_document_ref` pointing at their license proof. The case is born SUBMITTED with `resubmission_count` zero and `reviewed_at` null. An agent may have at most one case in flight: filing while another of the agent's cases is still SUBMITTED is rejected with `ERR_VERIFICATION_CASE_OPEN` (HTTP 409). Review is a `PlatformAdmin` prerogative exercised through a `decision` of APPROVE or REJECT with optional `review_notes`; a case that is no longer SUBMITTED cannot be reviewed, and the attempt fails with `ERR_CASE_NOT_SUBMITTED`. An APPROVE decision stamps `reviewed_at` with the current time, records the notes, and recomputes the agent's `verification_status` to VERIFIED. A REJECT decision stamps the same review fields but leaves the case REJECTED.

Rejection is not the end of the road. The owning agent may resubmit a REJECTED case with a fresh `license_document_ref`, cycling the case back to SUBMITTED while incrementing `resubmission_count` by one; the caller's agent identity must match the case's `agent_id`, and resubmission of a case that is not currently REJECTED is rejected with `ERR_CASE_NOT_REJECTED`. The resubmit cycle is deliberately unbounded — the paperwork of a career has hiccups — but each round trip is counted and visible to reviewers through the case history.

### 3.2. Listing Setup, Scheduling Policy, and Availability

A `ListingAgent` creates a listing with a payload containing the `seller_id` of the owning seller, the property `address`, and an `occupancy_type` of either VACANT or OCCUPIED. The referenced seller must exist, else the creation fails with `ERR_SELLER_NOT_FOUND`. Three optional scheduling-policy knobs ride along at creation: `buffer_minutes` (default 30 minutes, accepted range 0 to 240 inclusive), `max_showings_per_day` (default 5, range 1 to 20 inclusive), and `min_notice_minutes` (default 120 minutes — two hours — range 0 to 4320 inclusive, i.e. up to three days). The creating agent is recorded as the listing's `listing_agent_id`, and the listing is born ACTIVE with `confirmed_showing_count` zero and `avg_feedback_score` 0.0. Two properties are frozen at birth: `occupancy_type` is immutable after creation, and the owning seller cannot be retargeted through policy edits.

Policy tuning continues after creation through the scheduling-policy update, available to the owning listing agent. The caller may supply any subset of `buffer_minutes`, `max_showings_per_day`, and `min_notice_minutes`, and — because this is one of the two OCC-guarded writes in the platform — must supply `expected_listing_version` matching the listing's current `version`. A version that has advanced since the caller last read the listing produces `ERR_STALE_LISTING_VERSION` (HTTP 412); a successful update increments the listing's `version` by one. Note what the policy update does not touch: occupancy type and ownership are outside its reach.

Availability is managed along two axes. On the coarse axis, the owning listing agent pauses an ACTIVE listing, moving it to PAUSED with a `LISTING_PAUSED` event appended, and later resumes it from PAUSED back to ACTIVE with `LISTING_RESUMED`; each transition bumps the listing's `version`. Pause requires the listing to be ACTIVE and resume requires it to be PAUSED. On the fine axis, the owning seller carves out blackout windows by supplying a `start_at`, an `end_at`, and an optional `reason`. A blackout is a closed interval — both endpoints are blocked — and it must pass the same time-range sanity rule as a showing window: the end must be strictly later than the start and the span may not exceed 120 minutes, else `ERR_INVALID_TIME_RANGE`. Blackouts can be listed by the seller and the listing agent, and the owning seller can delete one outright, which returns a 204 with no content. Sellers and agents browsing their portfolios can filter the listing collection by `seller_id`, `listing_agent_id`, or `status`.

Withdrawal is the point of no return. From either ACTIVE or PAUSED, the owning listing agent may withdraw the listing, moving it to the terminal WITHDRAWN state; once WITHDRAWN, no further lifecycle action is possible, and any pause, resume, or re-withdraw attempt is rejected with `ERR_LISTING_ALREADY_WITHDRAWN`. Withdrawal fires CASCADE A as a single atomic sweep. Hop 1: every showing request of this listing in PENDING_APPROVAL, APPROVED, or CONFIRMED moves to CANCELLED with `cancel_actor` set to SYSTEM and `cancelled_at` stamped to now. Hop 2: for each of those requests that had been CONFIRMED, its credential in ISSUED status moves to REVOKED with a `CREDENTIAL_REVOKED` event, and the listing's `confirmed_showing_count` is decremented once per such confirmed cancellation. Hop 3: each cancelled request's feedback request still in SCHEDULED moves to CANCELLED, and a `CANCELLED` event is appended per request. Finally a `LISTING_WITHDRAWN` event is appended and the listing's `version` increments. Requests that were merely pending or approved carry no credentials and no feedback requests yet, so for them the cascade ends at hop 1.

### 3.3. Showing Request Intake and Scheduling Constraints

A `BuyerAgent` initiates a showing by supplying the target `listing_id`, a proposed `start_at` and `end_at`, and optionally a `buyer_name` display name and a free-text `note` to the occupant. The platform does not accept an agent identifier in the payload: `buyer_agent_id` is taken from the caller's `X-User-ID` at creation, binding the request to the acting agent. A `REQUEST_CREATED` event is appended, and the request's `reschedule_count` starts at zero while `decline_reason`, `cancel_actor`, `cancelled_at`, and `completed_at` all start null.

Intake then runs the validation pipeline of §2.7, and the temporal gauntlet deserves a close read because its order is observable. The listing must be ACTIVE — intake against a PAUSED or WITHDRAWN listing fails with `ERR_LISTING_NOT_ACTIVE`. The acting agent must be VERIFIED, else `ERR_AGENT_NOT_VERIFIED` (HTTP 403), and must not be SUSPENDED, else `ERR_AGENT_SUSPENDED` (HTTP 403). The window itself must be sane: `end_at` strictly later than `start_at` and the duration no longer than 120 minutes, else `ERR_INVALID_TIME_RANGE` (HTTP 422). The start must respect the listing's notice floor — the gap between now and `start_at` must be at least `min_notice_minutes`, else `ERR_INSUFFICIENT_LEAD_TIME` (HTTP 422).

Next come the two conflict checks, which use deliberately different interval mathematics. The buffered overlap check pads every competing request — those on the same listing in PENDING_APPROVAL, APPROVED, or CONFIRMED, excluding the request under evaluation itself — by `buffer_minutes` on both sides. A conflict exists exactly when the new window's start falls before some existing window's padded end (its `end_at` plus the buffer) and that window's padded start (its `start_at` minus the buffer) falls before the new window's end. Because both comparisons are strict, a new window that merely kisses a padded boundary is allowed. A violation yields `ERR_SHOWING_OVERLAP_CONFLICT` (HTTP 409). The blackout check is a separate, buffer-free closed-interval intersection against every BlackoutWindow of the listing: a conflict exists when the new start is at or before the blackout's `end_at` and the blackout's `start_at` is at or before the new end — touching counts here, and the rejection is `ERR_BLACKOUT_CONFLICT` (HTTP 409).

Last comes the daily cap. The platform counts the listing's requests in PENDING_APPROVAL, APPROVED, or CONFIRMED whose `start_at` falls on the same UTC calendar date as the proposed start; creation proceeds only while that count is strictly below `max_showings_per_day`, so a request arriving when the count already equals the cap is rejected with `ERR_DAILY_SHOWING_LIMIT` (HTTP 409). Note the cap counts the pending pipeline, not just confirmed business — three unreviewed requests can fill a day as surely as three confirmed ones.

Two deadline fields are computed at creation. The `confirm_by_deadline` is always one hour (60 minutes) before the window's `start_at`. The `approval_deadline` depends on occupancy and seller policy. When the listing is VACANT and its seller has `auto_approve` set, the deadline collapses to the request's own creation time and the request is born directly in APPROVED — no occupant touch required. In every other case the request is born PENDING_APPROVAL and the deadline is a clamped window: take the later of (a) thirty minutes after creation — a minimum review floor — and (b) the earlier of the seller's `approval_timeout_minutes` after creation and the listing's notice-adjusted latest approval moment, which is `start_at` minus `min_notice_minutes`. Both deadlines are recomputed from scratch on every reschedule. Browsing the request collection supports filtering by `listing_id`, `buyer_agent_id`, or `status`.

### 3.4. Occupant Approval, Decline, and Rescheduling

Approval belongs to the occupant side. The seller who owns the listing approves a request sitting in PENDING_APPROVAL; a request in any other state cannot be approved (`ERR_SHOWING_NOT_PENDING_APPROVAL`), and one that has already reached a terminal state draws `ERR_SHOWING_ALREADY_TERMINAL`. Approval is also time-boxed: once now reaches the request's `approval_deadline`, approval is rejected with `ERR_APPROVAL_DEADLINE_PASSED` (HTTP 422), because the occupant's decision window has closed. A successful approval appends an `APPROVED` event and increments the request's `version`.

Decline is the symmetric sibling. The same seller, on the same PENDING_APPROVAL precondition, may decline with an optional `reason` in the payload; the platform records it into `decline_reason`, appends a `DECLINED` event, and bumps the `version`. A decline does not kill the request — it hands the initiative back to the buyer's agent.

Should the occupant simply stay silent, the sweep of §2.11 cleans up: a request still PENDING_APPROVAL once now reaches its `approval_deadline` moves to EXPIRED, and a request sitting APPROVED once now reaches its `confirm_by_deadline` likewise moves to EXPIRED, each with an `EXPIRED` event. Silence is never allowed to pin a calendar slot forever.

Rescheduling is the buyer agent's recovery move from DECLINED, and only from DECLINED — attempting it from any other state fails with `ERR_SHOWING_NOT_DECLINED`. The caller supplies a fresh `start_at` and `end_at`, and the new window is revalidated from the ground up exactly as at intake: the listing must be ACTIVE, the time range sane, the lead time satisfied, and the buffered-overlap, blackout, and daily-cap checks must all pass (with the request's own prior window excluded from the overlap comparison). The target state is normally PENDING_APPROVAL, reopening the occupant's decision; when the listing is VACANT and the seller auto-approves, the reschedule lands directly in APPROVED instead. A successful reschedule replaces the window, recomputes both `approval_deadline` and `confirm_by_deadline`, increments `reschedule_count` by one, appends a `RESCHEDULED` event, and bumps the `version`.

### 3.5. Confirmation and Access Credentialing

Approval alone does not fill a calendar slot; the buyer's agent must still confirm. Confirmation requires the request in APPROVED (`ERR_SHOWING_NOT_APPROVED` otherwise), and it re-runs the eligibility checks from intake at confirmation time: the acting agent must still be VERIFIED (`ERR_AGENT_NOT_VERIFIED`) and must not now be SUSPENDED (`ERR_AGENT_SUSPENDED`) — an agent suspended between approval and confirmation loses the slot. The action must also beat the clock: once now reaches the `confirm_by_deadline`, confirmation is rejected with `ERR_CONFIRM_DEADLINE_PASSED` (HTTP 422). Success carries real weight: the listing's `confirmed_showing_count` increments by one (the forward leg of the confirmed-count invariant), a FeedbackRequest is automatically created in SCHEDULED status for the request, a `CONFIRMED` event is appended, and the request's `version` increments.

With a confirmed showing in hand, the owning listing agent issues exactly one access credential for it. Issuance requires the request in CONFIRMED — any other state yields `ERR_SHOWING_NOT_CONFIRMED` — and is refused when a credential in ISSUED or USED status already exists for the request, drawing `ERR_CREDENTIAL_ALREADY_ISSUED` (HTTP 409). The caller chooses a `credential_type` of LOCKBOX_CODE, DOOR_CODE, or SMART_LOCK; the server generates the `access_code` itself as a six-digit numeric string, and a `CREDENTIAL_ISSUED` event marks the birth of the credential in ISSUED status.

The access window and instructions are computed from occupancy, and the two variants differ materially. For a VACANT listing, the credential becomes redeemable one hour (60 minutes) before the showing's `start_at` and remains redeemable until one hour after its `end_at`; the computed `instructions_text` reads "Vacant property: self-access with lockbox/code anytime inside the access window." For an OCCUPIED listing, entry tightens: redeemable from fifteen minutes before `start_at` until the listing's `buffer_minutes` after `end_at`, and the `instructions_text` reads "Occupied property: occupant-approved access; arrive no earlier than 15 minutes before start." In both variants the `expires_at` boundary is exclusive — the credential dies at that instant, not after it.

Redemption is the buyer agent's act of arrival. The credential must be ISSUED, else `ERR_CREDENTIAL_NOT_REDEEMABLE`; the parent showing must still be CONFIRMED, else `ERR_SHOWING_NOT_CONFIRMED`; now must be at or after `active_from`, else `ERR_CREDENTIAL_NOT_YET_ACTIVE` (HTTP 422); and now must still be before `expires_at`, else `ERR_CREDENTIAL_EXPIRED` (HTTP 422). A successful redemption stamps `redeemed_at`, moves the credential to USED, appends `CREDENTIAL_REDEEMED`, and bumps the credential's `version`. Credentials also die without redemption: the sweep moves any ISSUED credential past its `expires_at` to EXPIRED with a `CREDENTIAL_EXPIRED` event, and the owning listing agent may revoke an ISSUED credential at will, moving it to REVOKED with `CREDENTIAL_REVOKED`. Both the listing agent and the buyer agent can list the credentials attached to a showing request.

### 3.6. Completion, No-Show Declaration, and the Strike System

A confirmed showing resolves in one of two ways. The happy path is swept automatically: once now has passed the request's `end_at` and a credential for the request has been USED, the sweep moves the request to COMPLETED, stamps `completed_at`, decrements the listing's `confirmed_showing_count`, flips the request's SCHEDULED feedback request to SENT — stamping `sent_at` and setting `due_at` seventy-two hours (three days) later with a `FEEDBACK_SENT` event — and appends a `COMPLETED` event. The redeemed credential is thus the proof of life that separates a completed showing from a no-show.

The unhappy path is the no-show declaration, made by the owning listing agent after the window closes. Declaring before `end_at` has passed is premature and fails with `ERR_NO_SHOW_TOO_EARLY` (HTTP 422); declaring when any credential of the request has been USED is contradictory and fails with `ERR_NO_SHOW_NOT_DECLARABLE` (HTTP 409); and the request must still be CONFIRMED, else `ERR_SHOWING_NOT_CONFIRMED`. A valid declaration fires CASCADE B in four hops, all within the same call. Hop 1: a StrikeRecord of `strike_type` NO_SHOW, `weight` 25, is created against the buyer agent — its `agent_id` names the penalized agent and its `showing_request_id` the originating request — with a `STRIKE_ISSUED` event. Hop 2: the agent's standing is recomputed from the new point total. Hop 3: if the recompute transitioned the agent INTO SUSPENDED, every other showing request of that agent in PENDING_APPROVAL, APPROVED, or CONFIRMED whose `start_at` lies in the future is moved to CANCELLED with `cancel_actor` SYSTEM. Hop 4: for each of those hop-3 cancellations that had been CONFIRMED, the request's ISSUED credential is revoked, its SCHEDULED feedback request is cancelled, and its listing's `confirmed_showing_count` is decremented. The no-show request itself loses its slot in the count, appends a `NO_SHOW` event, and increments its `version`. The cascade fires on the transition into suspension; an agent who was already SUSPENDED and merely adds points does not re-trigger it.

The buyer agent's own escape hatch is cancellation, available from PENDING_APPROVAL, APPROVED, or CONFIRMED with an optional `reason`. From the two pre-confirmation states the effect is light: `cancel_actor` is set to BUYER_AGENT, `cancelled_at` is stamped, a `CANCELLED` event is appended, and the `version` bumps. Cancelling from CONFIRMED is the expensive variant: the listing's `confirmed_showing_count` decrements, the request's ISSUED credential is revoked with its `CREDENTIAL_REVOKED` event, the SCHEDULED feedback request is cancelled, and — when the cancellation lands less than 24 hours before the window's `start_at` — a LATE_CANCEL strike of `weight` 10 is created against the buyer agent, immediately recomputing that agent's standing and, on a transition into SUSPENDED, fanning out the same future-request cascade described above.

Standing is a three-rung ladder computed from `active_strike_points`, the summed `weight` of the agent's ACTIVE strikes — 25 for a NO_SHOW, 10 for a LATE_CANCEL. An agent at 30 points or more is SUSPENDED; at 15 points or more but below 30, RESTRICTED; below 15, GOOD_STANDING. The boundaries are inclusive upward: exactly 15 points is RESTRICTED, exactly 30 is SUSPENDED. Every standing change increments the agent's `version`, and de-escalation is deliberately unforgiving in one direction — when points fall and standing relaxes, requests already cancelled by a prior suspension stay CANCELLED; nothing is resurrected.

Strikes age out on their own schedule. A strike is born ACTIVE with `expires_at` set ninety days after its creation; the sweep moves ACTIVE strikes at or past that instant to EXPIRED and recomputes the agent's standing with each expiry. A `PlatformAdmin` may also forgive an ACTIVE strike — an optional `reason` may accompany the decision — moving it to FORGIVEN and recomputing standing as the compensating leg of the points invariant; forgiving anything not currently ACTIVE fails with `ERR_STRIKE_NOT_ACTIVE`. Strike history is inspectable per agent by platform staff and by the agent in either capacity, and the strikes originating from a particular showing request are visible to the platform admin, the seller, and the listing agent.

One closing note on symmetry: when the system itself cancels a request — whether through a withdrawal cascade or a suspension cascade — the shape of the cancellation depends on how far the request had progressed. From PENDING_APPROVAL or APPROVED there is nothing downstream to unwind, so only `cancel_actor` SYSTEM, `cancelled_at`, and the `CANCELLED` event are recorded. From CONFIRMED the full unwind runs: credential revoked, feedback cancelled, and the listing's confirmed count decremented.

### 3.7. Post-Showing Feedback Collection and Scoring

Feedback is solicited automatically, never manually. The FeedbackRequest is born in SCHEDULED the moment a showing is confirmed, rides along silently, and is flipped to SENT by the sweep only when the showing completes — at which point `sent_at` is stamped and `due_at` lands seventy-two hours later. If the buyer's agent lets that window lapse, the sweep moves the SENT request to EXPIRED. If the showing is cancelled before completing, the SCHEDULED feedback request is cancelled alongside it, since there is nothing to review. The single feedback request belonging to a showing — zero or one exists at any time — can be fetched by the seller, the listing agent, or the buyer agent.

Submission is the buyer agent's to make, and only from SENT. A feedback request still SCHEDULED, already EXPIRED, or CANCELLED answers with `ERR_FEEDBACK_NOT_AVAILABLE` (HTTP 409); one already SUBMITTED answers with `ERR_FEEDBACK_ALREADY_SUBMITTED` (HTTP 409). The payload carries five answers — `q1` for overall impression, `q2` for property condition, `q3` for price fit, `q4` for location, and `q5` for likelihood to offer — each an integer from 1 to 5 inclusive, with any answer outside that range rejected as `ERR_RATING_OUT_OF_RANGE` (HTTP 400). An optional free-text `comment` rides alongside.

Scoring is a two-leg computation with a pinned rounding order. The per-feedback leg computes the request's `overall_score` as a weighted blend — 0.30 of `q1`, 0.25 of `q2`, 0.20 of `q3`, 0.15 of `q4`, and 0.10 of `q5` — rounded half-up to exactly 1 decimal place. The rollup leg then recomputes the listing's `avg_feedback_score` as the mean of the already-rounded per-feedback scores across all of that listing's SUBMITTED feedback requests, itself rounded half-up to 1 decimal place; a listing with no submitted feedback reports 0.0. The order is contractual: each score is rounded first and only then averaged. Averaging the raw unrounded blends and rounding once at the end is forbidden, because it diverges — raw scores of 4.25, 4.25, and 4.20 average to 4.3 under the pinned order but 4.2 under the aggregate-first shortcut. A successful submission stamps `submitted_at`, appends a `FEEDBACK_SUBMITTED` event, and increments the feedback request's `version`.

### 3.8. Seller Reporting and the Activity Trail

The seller-facing activity report distills a listing's entire request history into a single computed payload, available to the seller and the listing agent. An optional `mode` query parameter selects the lens: FINAL, the default end-of-period view, or PROVISIONAL, a mid-period pipeline view. Both variants report the same eight counts over all requests of the listing regardless of status: the pipeline counts `pending_approval_count`, `approved_count`, and `confirmed_count`, plus the terminal counts `completed_count`, `no_show_count`, `cancelled_count` (covering every `cancel_actor`, agent or system), `expired_count`, and `declined_count`.

Where the modes diverge is the rate. In FINAL mode, `completion_rate` is the completed count divided by the terminal total — the sum of completed, no-show, cancelled, expired, and declined counts — rounded half-up to 2 decimal places, and reported as 0.00 when the listing has no terminal requests at all; `provisional_completion_rate` is null in this mode. In PROVISIONAL mode the platform additionally reports `provisional_completion_rate`, computed as the completed count divided by the larger of (completed plus no-show plus confirmed) and 1, again rounded half-up to 2 decimal places. The provisional rate deliberately counts CONFIRMED appointments as will-complete, so on identical data the two rates diverge — that divergence is the point of offering both. The report also carries the listing's `avg_feedback_score` per the rollup of §3.7, 0.0 when no feedback has been submitted.

Alongside the aggregates sits the raw trail described in §2.12: the append-only event feed, queryable for the whole listing or narrowed to a single showing request, with an optional `event_type` filter and standard pagination. Sellers reconcile the report against the trail; listing agents use the trail to reconstruct exactly who did what when a dispute lands.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or perform a state transition return `200 OK`; the blackout-window deletion returns `204 No Content`; reads return `200 OK`. Request and response payloads are described in the workflow narratives of §3 rather than duplicated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/showing-desk/sellers` | Create a seller | PlatformAdmin |
| GET | `/showing-desk/sellers/{id}` | Get a seller | PlatformAdmin, Seller |
| PATCH | `/showing-desk/sellers/{id}/approval-settings` | Update seller approval settings (version-guarded) | Seller |
| POST | `/showing-desk/agents` | Register an agent (self-service) | Anonymous |
| GET | `/showing-desk/agents/{id}` | Get an agent | PlatformAdmin, ListingAgent, BuyerAgent |
| POST | `/showing-desk/agents/{id}/verification-cases` | Submit an identity-verification case for the calling agent | ListingAgent, BuyerAgent |
| GET | `/showing-desk/agents/{id}/verification-cases` | List an agent's verification cases | PlatformAdmin, ListingAgent, BuyerAgent |
| POST | `/showing-desk/verification-cases/{case_id}/review` | Approve or reject a SUBMITTED verification case | PlatformAdmin |
| POST | `/showing-desk/verification-cases/{case_id}/resubmit` | Resubmit a REJECTED verification case | ListingAgent, BuyerAgent |
| GET | `/showing-desk/agents/{id}/strikes` | List an agent's strike records | PlatformAdmin, ListingAgent, BuyerAgent |
| POST | `/showing-desk/strikes/{strike_id}/forgive` | Forgive an ACTIVE strike | PlatformAdmin |
| POST | `/showing-desk/listings` | Create a listing | ListingAgent |
| GET | `/showing-desk/listings/{id}` | Get a listing | PlatformAdmin, Seller, ListingAgent, BuyerAgent |
| GET | `/showing-desk/listings` | List listings with optional filters | PlatformAdmin, Seller, ListingAgent, BuyerAgent |
| PATCH | `/showing-desk/listings/{id}/policy` | Update scheduling policy (version-guarded) | ListingAgent |
| POST | `/showing-desk/listings/{id}/pause` | Pause an ACTIVE listing | ListingAgent |
| POST | `/showing-desk/listings/{id}/resume` | Resume a PAUSED listing | ListingAgent |
| POST | `/showing-desk/listings/{id}/withdraw` | Withdraw a listing, cascading cancellations | ListingAgent |
| POST | `/showing-desk/listings/{id}/blackout-windows` | Create a closed-interval blackout window | Seller |
| GET | `/showing-desk/listings/{id}/blackout-windows` | List a listing's blackout windows | Seller, ListingAgent |
| DELETE | `/showing-desk/blackout-windows/{window_id}` | Delete a blackout window | Seller |
| POST | `/showing-desk/showing-requests` | Create a showing request | BuyerAgent |
| GET | `/showing-desk/showing-requests/{id}` | Get a showing request | PlatformAdmin, Seller, ListingAgent, BuyerAgent |
| GET | `/showing-desk/showing-requests` | List showing requests with optional filters | PlatformAdmin, Seller, ListingAgent, BuyerAgent |
| POST | `/showing-desk/showing-requests/{id}/approve` | Occupant approves a pending request | Seller |
| POST | `/showing-desk/showing-requests/{id}/decline` | Occupant declines a pending request | Seller |
| POST | `/showing-desk/showing-requests/{id}/confirm` | Buyer agent confirms an approved request | BuyerAgent |
| POST | `/showing-desk/showing-requests/{id}/cancel` | Buyer agent cancels a request | BuyerAgent |
| POST | `/showing-desk/showing-requests/{id}/reschedule` | Reschedule a declined request with a new window | BuyerAgent |
| POST | `/showing-desk/showing-requests/{id}/declare-no-show` | Listing agent declares a no-show after the window ends | ListingAgent |
| POST | `/showing-desk/showing-requests/{id}/access-credentials` | Issue an access credential for a confirmed showing | ListingAgent |
| GET | `/showing-desk/showing-requests/{id}/access-credentials` | List credentials of a showing request | ListingAgent, BuyerAgent |
| GET | `/showing-desk/showing-requests/{id}/strikes` | List strikes originating from a showing request | PlatformAdmin, Seller, ListingAgent |
| GET | `/showing-desk/showing-requests/{id}/feedback-request` | Get the feedback request of a showing | Seller, ListingAgent, BuyerAgent |
| POST | `/showing-desk/access-credentials/{credential_id}/redeem` | Buyer agent redeems a credential inside its window | BuyerAgent |
| POST | `/showing-desk/access-credentials/{credential_id}/revoke` | Listing agent revokes an ISSUED credential | ListingAgent |
| POST | `/showing-desk/feedback-requests/{feedback_id}/submit` | Buyer agent submits feedback answers | BuyerAgent |
| GET | `/showing-desk/listings/{id}/activity-events` | List the append-only activity log of a listing | Seller, ListingAgent |
| GET | `/showing-desk/showing-requests/{id}/activity-events` | List activity events tied to one showing request | Seller, ListingAgent |
| GET | `/showing-desk/listings/{id}/activity-report` | Computed seller activity report (FINAL or PROVISIONAL) | Seller, ListingAgent |
| POST | `/showing-desk/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/showing-desk/_ops/run_expiration_sweep` | Run the six-step expiration sweep | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each code are specified in the narratives of §2 and §3; this table is the index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_RATING_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SELLER_NOT_FOUND` | 404 Not Found |
| `ERR_AGENT_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_SHOWING_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_VERIFICATION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_BLACKOUT_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_ACCESS_CREDENTIAL_NOT_FOUND` | 404 Not Found |
| `ERR_FEEDBACK_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_STRIKE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_LISTING_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SELLER_VERSION` | 412 Precondition Failed |
| `ERR_LISTING_NOT_ACTIVE` | 409 Conflict |
| `ERR_LISTING_ALREADY_WITHDRAWN` | 409 Conflict |
| `ERR_SHOWING_NOT_PENDING_APPROVAL` | 409 Conflict |
| `ERR_SHOWING_NOT_APPROVED` | 409 Conflict |
| `ERR_SHOWING_NOT_CONFIRMED` | 409 Conflict |
| `ERR_SHOWING_NOT_DECLINED` | 409 Conflict |
| `ERR_SHOWING_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_CASE_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CASE_NOT_REJECTED` | 409 Conflict |
| `ERR_STRIKE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_FEEDBACK_NOT_AVAILABLE` | 409 Conflict |
| `ERR_FEEDBACK_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_AGENT_NOT_VERIFIED` | 403 Forbidden |
| `ERR_AGENT_SUSPENDED` | 403 Forbidden |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LEAD_TIME` | 422 Unprocessable Entity |
| `ERR_SHOWING_OVERLAP_CONFLICT` | 409 Conflict |
| `ERR_BLACKOUT_CONFLICT` | 409 Conflict |
| `ERR_DAILY_SHOWING_LIMIT` | 409 Conflict |
| `ERR_APPROVAL_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CONFIRM_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_NO_SHOW_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_NO_SHOW_NOT_DECLARABLE` | 409 Conflict |
| `ERR_CREDENTIAL_ALREADY_ISSUED` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_YET_ACTIVE` | 422 Unprocessable Entity |
| `ERR_CREDENTIAL_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_CASE_OPEN` | 409 Conflict |
