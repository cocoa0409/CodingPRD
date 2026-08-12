# Expert Witness Sourcing API — Product Requirements Document

## 1. Introduction

Litigation lives and dies by the credibility of its expert witnesses, and the firms that source them carry a heavy operational burden: finding the right specialty, screening for conflicts of interest, vetting credentials and Daubert history, negotiating engagement letters, producing documents without breaching privilege, holding experts to report deadlines, booking deposition and trial time, policing invoices against a matter budget, and learning from each engagement so the roster improves over time. This document specifies the Expert Witness Sourcing API, the system of record a litigation support firm uses to run that entire lifecycle.

The API rests on a strict segregation of duties. Sourcing analysts screen, case managers drive the matter forward, billing reviewers guard the budget, and experts act only on their own engagements — no single operator may both create and approve the spend on an engagement. Financially, the system maintains a per-engagement retainer ledger with an inviolable conservation invariant, recomputes every invoice server-side under a pinned rounding order, and projects each matter's committed spend forward so overruns surface at approval time rather than at settlement. Every temporal rule in the system — report deadlines, schedule-in-the-past rejection, cancellation windows, rating decay — reads a single logical clock, so behavior is deterministic and auditable. All endpoints are mounted under the `/litigation` prefix, with one administrative clock capability mounted outside it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `CaseManager`, `ConflictAnalyst`, `CredentialAnalyst`, `BillingReviewer`, and `Expert`. A request whose headers are missing, or whose role header is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role — including action-level rules such as the conflict-waiver reservation or the expert-ownership rules — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `Expert`, `X-User-ID` is the `id` of the acting `Expert` entity; ownership checks on any resource that references an `Expert` compare the resource's `expert_id` foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `CaseManager`, `ConflictAnalyst`, `CredentialAnalyst`, or `BillingReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on an `Engagement`) but does not compare it to any entity's `id`.

The roles divide the work as follows:

- A `PlatformAdmin` is the firm administrator: registers venues, performs roster maintenance transitions, waives flagged conflict checks, and sets the logical clock; the role has read access to all resources.
- A `CaseManager` runs matters end to end: opens cases, revises budgets, creates sourcing requests, drives the engagement lifecycle (propose, fund, amend, terminate, close), registers document productions, reviews and discloses reports, manages testimony schedules, and records post-case evaluations; the role has read access to all resources.
- A `ConflictAnalyst` opens conflict checks and resolves them to cleared or flagged outcomes — and deliberately cannot waive a flag, a segregation-of-duties boundary.
- A `CredentialAnalyst` opens credential and Daubert reviews and records their outcomes.
- A `BillingReviewer` approves, disputes, and settles invoices against the matter budget, and is barred from approving an invoice on an engagement created by the same user.
- An `Expert` is a roster witness acting on their own engagements: countering and signing engagement letters, submitting and revising reports, acknowledging document productions, and submitting or resubmitting invoices.

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

The same error envelope also answers an unexpected internal failure: any exception that escapes endpoint processing is rejected with `error_id` `ERR_INTERNAL` and HTTP status 500.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Entity Identity

Every primary resource in the system — Expert, Case, EngagementRequest, ConflictCheck, CredentialReview, Engagement, DocumentProduction, Report, Venue, TestimonySchedule, and Invoice — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified; it refreshes on any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by exactly one with every modification to the resource.

One uniform mutation rule applies across the whole API: every state transition described in §3 — whether triggered by an explicit client call or fired automatically by a system cascade — refreshes the affected entity's `updated_at` and increments its `version` by one. Recomputations of derived fields (retainer balances, case aggregates, expert ratings) are mutations of their owning entity and follow the same rule.

The Evaluation record is the single exception. Evaluations are terminal records, immutable once created, and carry only `id` and `created_at`; both `updated_at` and `version` are absent from an Evaluation.

### 2.5. The Logical Clock

The server maintains a single logical clock, and every temporal rule in this document — report deadlines, schedule-in-the-past rejection, the cancellation-fee window, evaluation decay ages, session completion eligibility — reads that clock and never the wall clock. At server startup, before any administrative call, the logical clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. A `PlatformAdmin` may advance it through the administrative capability `POST /_clock/set_current_utc`, whose payload carries `to_iso8601`, the ISO 8601 UTC instant the clock should move to. This capability returns no resource data.

### 2.6. Optimistic Concurrency Control on Superseding Writes

Two write operations in this API legitimately supersede prior state rather than being rejected by a state-field check, so they alone carry an optimistic-concurrency guard; no other endpoint takes a version field.

- A request to `POST /litigation/engagements/{id}/amend` must carry `expected_engagement_version`, holding the caller's last observed `version` of the target Engagement. Because a newer amendment legitimately supersedes prior terms, a second sequential amendment carrying a stale version observes no state-field rejection and must be stopped by OCC: if the value does not match the engagement's current `version`, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from unknowingly overwriting terms it has not observed.
- A request to `POST /litigation/cases/{id}/budget-revisions` must carry `expected_case_version`, holding the caller's last observed `version` of the target Case. Each revision legitimately supersedes the prior budget, so only the OCC check distinguishes a stale writer: a mismatch with the case's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Monetary Precision and Rounding

All monetary amounts in this API — budgets, rates, retainers, expenses, invoice totals, fees — are integer numbers of cents. Where a monetary computation produces a fractional cent (a fractional hour multiplied against a rate, a percentage fee), the result is rounded to the nearest whole cent using round-half-up. Expert ratings are the only non-monetary computed numbers exposed by the API; they are rounded half-up to two decimal places.

Two rounding-order rules are pinned and must not be varied. Invoice service totals round each line to the nearest cent before summing — never sum-then-round (§3.7 pins this with a worked example). Schedule estimates and cancellation fees are computed from the full expression and rounded once, half-up, to the nearest cent.

### 2.8. The Retainer Ledger

Every engagement carries a four-column retainer ledger. `retainer_funded_cents` records the total the client has funded; `retainer_drawn_cents` records the total applied to approved invoices and cancellation fees; `retainer_refunded_cents` records the total refunded at termination; and `retainer_remaining_cents` is derived as the funded amount minus the drawn amount minus the refunded amount. One conservation invariant holds at all times: the funded amount always equals the sum of the drawn, refunded, and remaining amounts, and the remaining amount never goes negative.

When an invoice is approved, the ledger updates in a pinned evaluation order that resolves what would otherwise look like a circular dependency: first the invoice's `computed_total_cents` is computed from the current rate card, before any balance moves; the budget gate then reads the case's paid actuals and approved-outstanding amounts as of the pre-approval state; the draw is then taken as the lesser of the approved total and the retainer remaining as it stood before this draw; only after that is the draw added to `retainer_drawn_cents`; and finally the case aggregates are recomputed from the post-approval invoice set. The same ledger also funds late-cancellation fees (drawn as the lesser of the fee and the remaining balance) and unwinds at termination, where the refund returns whatever remains after draws.

### 2.9. Matter Fiscal Posture: Paid Actuals and the Committed Projection

Each Case exposes three computed spend figures on every read, recomputed on every invoice, schedule, or engagement mutation touching the case. The two headline figures are deliberate variants of one another and diverge whenever any spend is pending.

- `actuals_paid_cents` is the chronological, backward-looking variant: the sum of `computed_total_cents` over all invoices in `PAID` status on the case's engagements. The sum is order-independent.
- `approved_outstanding_cents` is the sum of `computed_total_cents` over invoices in `APPROVED` status that have not yet been paid.
- `committed_cents` is the forward-looking variant: the paid actuals, plus the computed totals of approved-but-unpaid invoices, plus the computed totals of invoices still in `SUBMITTED` or `DISPUTED`, plus the `retainer_remaining_cents` of every engagement of the case currently in `ACTIVE` status, plus the cost estimate of every testimony session in `CONFIRMED` status on the case's engagements. A confirmed session's estimate is its `estimated_hours` multiplied by the engagement's `hourly_rate_cents`, multiplied by one and a quarter, rounded half-up to the nearest cent. Rejected invoices and paid-terminal items contribute nothing to the forward part beyond the actuals term, and cancelled or completed sessions are excluded from it entirely.

### 2.10. Calendar and Venue Booking Geometry

Two distinct overlap regimes govern testimony scheduling, and both are checked when a session is proposed and re-checked against the current clock state when a session is confirmed. Only sessions in `PROPOSED` or `CONFIRMED` status participate in either check; cancelled and completed sessions free their slots.

The expert's calendar is a half-open model. A new session conflicts with an existing session of the same expert whenever the existing session starts before the new session ends and the new session starts before the existing session ends. Because the intervals are half-open, adjacency is allowed: a new session starting at exactly the instant an existing session ends does not conflict. A violation is rejected with `ERR_SCHEDULE_CONFLICT` (HTTP 409).

A venue booking is a closed model with a turnover buffer. When a session names a `venue_id`, the session is treated as occupying that room from thirty minutes before its `start_at` until thirty minutes after its `end_at`, with both boundary instants included. Two buffered windows for the same venue conflict whenever each starts at or before the other's buffered end — which means touching still conflicts: a new session starting exactly thirty minutes after an existing session's end violates the buffer. A violation is rejected with `ERR_VENUE_CONFLICT` (HTTP 409). Sessions without a venue (remote testimony) skip the venue check entirely.

### 2.11. Validation Order and Nested Path Resolution

Every request is validated against a fixed global ladder before any endpoint-specific business rule runs: first the authentication headers are checked (missing or unknown role, or a missing user identifier, yields `ERR_UNAUTHENTICATED`); then the request body shape is checked — required fields present, types correct, enum members valid — with violations yielding `ERR_INVALID_REQUEST` (HTTP 400); then role authorization for the endpoint and the specific action is enforced, with violations yielding `ERR_FORBIDDEN`; then path identifiers are resolved; then the target entity's state preconditions for the requested transition are checked, with violations yielding `ERR_INVALID_STATE` (HTTP 409); and only then do the endpoint's business rules run, in the explicit order each workflow lists them in §3.

Nested resources are validated left to right. When an endpoint path contains multiple resource identifiers, the system resolves each identifier in path order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, without examining later identifiers.

## 3. Business Logic & Workflows

### 3.1. The Expert Roster: Admission, Standing, and Quality Memory

A `PlatformAdmin` admits a witness to the roster by supplying the expert's `full_name` and `specialty_area`. Three optional registration fields round out the profile: `daubert_challenge_count` and `daubert_exclusion_count`, both integers that default to 0 and may never be negative, record the expert's historical Daubert challenges and exclusions; and `max_concurrent_engagements`, an integer of at least 1 defaulting to 5, caps how many engagements the expert may hold at once. A newly admitted expert's `roster_status` begins at `ACTIVE`, and both computed ratings — `rating_simple` and `rating_decayed` — read 0.0 until evaluations exist.

Sourcing staff search the roster with optional `specialty_area` and `roster_status` filters, paginated by `limit` and `offset`. The expert detail view exposes the full computed picture: `active_engagement_count`, the number of this expert's engagements currently in `SIGNED` or `ACTIVE` status; `evaluation_count`, the number of evaluation records the expert has accumulated; and the two ratings.

Ratings are computed over every evaluation ever recorded for the expert — evaluations are terminal records and carry no status, so no filtering applies. `rating_simple` is the unweighted mean of the evaluations' `overall_score` values, rounded half-up to two decimal places, and 0.0 when the expert has none. `rating_decayed` applies recency decay: an evaluation's age in days is the whole number of days between its `evaluated_at` instant and the current logical-clock time, discarding any partial day, and its weight is one-half raised to the number of complete 180-day periods contained in that age — an evaluation under 180 days old weighs 1, one between 180 and 359 days old weighs one-half, one between 360 and 539 days weighs one-quarter, and so on. The decayed rating is the sum of each evaluation's weight times its `overall_score`, divided by the sum of the weights, rounded half-up to two decimal places, and 0.0 when no evaluations exist. The two variants diverge exactly when old and recent evaluations tell different stories: a recent poor evaluation pulls the decayed figure below the simple one.

Standing on the roster is a state machine over `ACTIVE`, `PROBATION`, and `REMOVED`. An automatic demotion fires the moment a newly recorded evaluation leaves an `ACTIVE` expert with at least two evaluations and a `rating_decayed` below 3.0: the expert's standing moves `ACTIVE` → `PROBATION`, its `version` increments, and a cascade runs. Every conflict check still `PENDING` for that expert becomes `FLAGGED` with its `resolution_rationale` set to `ROSTER_PROBATION`. Any sourcing request still in `SCREENING` whose conflict checks have thereby all landed `FLAGGED` — and in which no expert any longer satisfies the readiness predicate of §3.2 — reverts from `SCREENING` to `OPEN`. A `PlatformAdmin` may also move an expert between standings manually by submitting a `to_status` with a `rationale`: `ACTIVE` → `PROBATION` (which fires the same cascade as the automatic path), `PROBATION` → `ACTIVE` for rehabilitation, and `ACTIVE` → `REMOVED` or `PROBATION` → `REMOVED` for removal. Removal is blocked while the expert's `active_engagement_count` is greater than zero, failing with `ERR_EXPERT_HAS_ACTIVE_ENGAGEMENTS`; `REMOVED` is terminal. One further consequence of the count model bears emphasis: because `SIGNED` and `ACTIVE` engagements both count, activating an engagement never changes `active_engagement_count`, while signing, terminating, and closing do.

### 3.2. Opening a Matter and Screening Candidates

A `CaseManager` opens a litigation matter with its `case_number` — unique per firm — plus the `court` of venue, a matter `title`, the total expert-spend `budget_cents` (strictly positive), the `trial_date`, and the `report_deadline`. The trial date must be strictly later than the report deadline. A new matter's `status` begins at `INTAKE`, and its three computed spend figures (`actuals_paid_cents`, `approved_outstanding_cents`, `committed_cents`) start at zero.

Sourcing begins when the `CaseManager` opens an engagement request against the matter, carrying the `case_id`, the required `specialty_area`, and optional `notes` (default empty). The request's `status` starts at `OPEN`, and the first request created for a case automatically moves the case `INTAKE` → `SOURCING`, incrementing the case's `version`.

Screening runs on two parallel tracks per candidate expert. A `ConflictAnalyst` opens a conflict check under the request, naming the `expert_id` and listing the `adverse_parties` whose names are screened against the expert's history; the check starts `PENDING`. A `CredentialAnalyst` opens a credential review under the request, naming the `expert_id`; the review likewise starts `PENDING`. The first check or review opened under a request moves it `OPEN` → `SCREENING`. Each (request, expert) pair supports exactly one conflict check and exactly one credential review: a second of either for the same pair is rejected with `ERR_DUPLICATE_SCREENING` — the rule guards both screening-opening operations.

Resolving a conflict check is a `ConflictAnalyst` action carrying an `outcome` and a `rationale`. From `PENDING`, the analyst may clear the check (`PENDING` → `CLEARED`) or flag it (`PENDING` → `FLAGGED`); in both cases the submitted rationale is recorded as the check's `resolution_rationale` (a flag raised by the roster-probation cascade instead records `ROSTER_PROBATION`). A flagged check may later be waived (`FLAGGED` → `WAIVED`), but waiver is reserved to a `PlatformAdmin` — a `ConflictAnalyst` attempting the `WAIVED` outcome is rejected with `ERR_FORBIDDEN` — and the waiver also records its `resolution_rationale`. Credential resolution is a `CredentialAnalyst` action carrying an `outcome` and optional `daubert_notes` (default empty): from `PENDING`, a review may pass (`PASSED`), fail (`FAILED`), or pass with conditions (`PASSED_WITH_CONDITIONS`).

Readiness is recomputed after every screening resolution. A candidate is fully qualified for a request when that expert holds a conflict check under the request in `CLEARED` or `WAIVED` and a credential review under the same request in `PASSED` or `PASSED_WITH_CONDITIONS`. The first time any candidate satisfies this predicate, the request moves `SCREENING` → `READY`; a pass or conditional pass re-evaluates the predicate, while a failed review records the outcome without promoting the request. If the last fully-qualified candidate later loses qualification, the request falls back `READY` → `SCREENING` (waiver revocation is not supported; this reversion path is reserved). The roster-probation cascade of §3.1 can push a request from `SCREENING` back to `OPEN`. A request reaches `FILLED` when an engagement is created from it (`READY` → `FILLED`). A direct jump `OPEN` → `FILLED` is impossible by construction: creating an engagement against a request that is not `READY` fails with `ERR_INVALID_STATE`.

### 3.3. The Engagement Letter: Terms, Negotiation, and Funding

With a request `READY`, a `CaseManager` drafts engagement-letter terms for the chosen expert. The creation payload names the `engagement_request_id` and `expert_id` and sets the commercial terms: `hourly_rate_cents` (strictly positive), `retainer_cents` (zero or more), and `expense_cap_cents` (zero or more, the lifetime cap on reimbursable travel expenses). At creation the engagement's `case_id` is denormalized from its originating request, and the creator's `X-User-ID` is recorded as `created_by_user_id` — the segregation-of-duties anchor used later at invoice approval. A new engagement starts in `DRAFT` with `negotiation_round_count` at 0, `nda_executed` false, all four retainer ledger fields at 0, and `expenses_approved_cents` at 0.

Creation is gated by seven business-safety checks, evaluated in this order after the global ladder of §2.11: first conflict clearance — the expert's check under the request must be `CLEARED` or `WAIVED`, else `ERR_CONFLICT_NOT_CLEARED`; then credential passage — the review must be `PASSED` or `PASSED_WITH_CONDITIONS`, else `ERR_CREDENTIAL_NOT_PASSED`; then roster standing — the expert must be `ACTIVE`, with `PROBATION` or `REMOVED` experts rejected as `ERR_EXPERT_ROSTER_INELIGIBLE`; then the Daubert bar — an expert with three or more `daubert_exclusion_count` is barred with `ERR_EXPERT_DAUBERT_BARRED`, while exactly two still passes; then the request's own posture — it must be `READY`, else `ERR_INVALID_STATE`; then uniqueness — no other engagement for the same `case_id` and `expert_id` pair may exist in any non-terminal state (`DRAFT`, `PROPOSED`, `NEGOTIATING`, `SIGNED`, or `ACTIVE`), else `ERR_DUPLICATE_CASE_ENGAGEMENT`; and finally capacity — the expert's `active_engagement_count` must be strictly below `max_concurrent_engagements`, with equality at the cap failing as `ERR_EXPERT_CAPACITY_FULL`. A successful creation moves the request `READY` → `FILLED`.

Negotiation is a two-party exchange. The `CaseManager` proposes terms, moving the engagement `DRAFT` → `PROPOSED`. The engaged expert — identified by matching `X-User-ID` to the engagement's `expert_id`, with any other expert's attempt rejected as `ERR_FORBIDDEN` — counters with a strictly positive `counter_rate_cents`, moving the engagement `PROPOSED` → `NEGOTIATING` and incrementing `negotiation_round_count` by one. The `CaseManager` may then propose again, moving `NEGOTIATING` → `PROPOSED` and optionally carrying a revised `hourly_rate_cents` in the payload, which replaces the offered rate — the counter-offer acceptance loop. Rounds may repeat as needed.

Signature belongs to the engaged expert alone. Signing moves `PROPOSED` → `SIGNED`, sets `nda_executed` to true, and recomputes the expert's `active_engagement_count`, which now includes this engagement. If the matter is still in `SOURCING`, the first signature automatically moves the case `SOURCING` → `ENGAGED`.

Funding converts signature into an active engagement. Once signed, the `CaseManager` funds the retainer in one or more payments, each carrying an `amount_cents` that is added to `retainer_funded_cents`. A payment that would push the funded total above `retainer_cents` is rejected with `ERR_RETAINER_OVERFUND`; a payment that brings the funded total to exactly `retainer_cents` completes funding and moves the engagement `SIGNED` → `ACTIVE`. Activation leaves the expert's `active_engagement_count` unchanged, because `SIGNED` and `ACTIVE` both count toward it.

Terms may be amended after the fact. A `CaseManager` submits an amendment carrying a mandatory `reason`, the OCC guard `expected_engagement_version` per §2.6, and any of `hourly_rate_cents`, `retainer_cents`, or `expense_cap_cents` to replace; the new terms supersede the prior ones and the engagement's `version` increments. Because an amendment is legal from any posture where terms remain meaningful, only the stale-version rejection distinguishes a writer acting on terms it has not observed.

Engagements are listed with optional `case_id`, `expert_id`, `engagement_request_id`, and `status` filters plus pagination, and the engagement detail view exposes the full retainer ledger alongside the commercial terms.

### 3.4. Document Production and Privilege Boundaries

Producing documents to an expert is a privilege-gated workflow. A `CaseManager` registers a production on an engagement with a `title`, a `privilege_tier` of `DISCOVERABLE`, `WORK_PRODUCT`, or `PRIVILEGED`, and a `content_ref` — an opaque reference to the material. The production's `engagement_id` ties it to the producing engagement, and its `status` begins at `REQUESTED`.

Advancement is driven by an `action` value of `DELIVER`, `ACKNOWLEDGE`, or `RECALL`. Delivery — an `action` of `DELIVER`, moving `REQUESTED` → `DELIVERED` — is a `CaseManager` action guarded by a tier gate keyed to the engagement's posture: a `DISCOVERABLE` production may be delivered once the engagement is `SIGNED` or `ACTIVE`; a `WORK_PRODUCT` production requires the engagement to be `ACTIVE`; and a `PRIVILEGED` production requires the engagement to be `ACTIVE` with `nda_executed` true. A delivery that violates its tier gate is rejected with `ERR_PRIVILEGE_TIER_BLOCKED`. Acknowledgment — an `action` of `ACKNOWLEDGE`, moving `DELIVERED` → `ACKNOWLEDGED` — belongs to the engaged expert, identified by `X-User-ID` matching the engagement's `expert_id`. Recall — an `action` of `RECALL`, moving `DELIVERED` → `RECALLED` — is a `CaseManager` action. Termination of the engagement — the cascade of §3.8 — recalls every production still sitting in `REQUESTED` or `DELIVERED`. Both `ACKNOWLEDGED` and `RECALLED` are terminal postures for a production.

### 3.5. Expert Reports and the Review Protocol

When the matter needs written testimony, a `CaseManager` opens a report on an engagement with a `title` and a `report_type` of `LIABILITY`, `DAMAGES`, or `REBUTTAL`. The report pins its own `deadline_at` as a copy of the case's `report_deadline` taken at creation — version-pinned, so later edits to the case do not move an open report's deadline. Each engagement supports at most one non-terminal report at a time: while any report on the engagement sits in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED`, or `FINALIZED`, opening another is rejected with `ERR_REPORT_ALREADY_ACTIVE`. The first report opened on any engagement of a case moves the case `ENGAGED` → `DISCOVERY`.

Submission belongs to the engaged expert and moves the report `DRAFT` → `IN_REVIEW`. Submission is permitted only while the engagement is `ACTIVE` and the logical clock reads at or before the pinned `deadline_at` — a submission landing exactly at the deadline passes, while a strictly later one fails with `ERR_REPORT_DEADLINE_PASSED`. A successful submission stamps `submitted_at` with the current clock time; until the first submission the field is null.

Review is a `CaseManager` decision carried in a `decision` value with optional `notes`. A `decision` of `REQUEST_REVISION` moves the report `IN_REVIEW` → `REVISION_REQUESTED`; a `decision` of `FINALIZE` moves it `IN_REVIEW` → `FINALIZED`. The expert answers a revision request by returning a revised draft — `REVISION_REQUESTED` → `DRAFT` — carrying `revision_notes`, which increments `revision_count` by one and reopens the submission gate, deadline check included, for the next attempt.

Disclosure is the success end-state of the firm-initiated flow. A `CaseManager` discloses a `FINALIZED` report — `FINALIZED` → `DISCLOSED` — only while the logical clock reads strictly before the case's `trial_date`; disclosure at or after the trial date fails with `ERR_TRIAL_DATE_PASSED`. The first disclosure on a case in `DISCOVERY` moves it `DISCOVERY` → `TRIAL_PREP`. `DISCLOSED` is nonetheless not a terminal state: the termination cascade of §3.8 can still withdraw a disclosed report.

### 3.6. Deposition and Trial Scheduling

Logistics begin with rooms. A `PlatformAdmin` registers each deposition suite as a venue with a `name`, a `location`, and an optional `capacity` that defaults to 20 and must be at least 1.

Against an engagement, a `CaseManager` proposes a testimony session with a `kind` of `DEPOSITION` or `TRIAL`, a `start_at` and `end_at` in UTC, a strictly positive `estimated_hours` used for cost projection, an optional `venue_id` (absent or null for remote sessions), and an optional `travel_required` flag defaulting to false. The interval must be sensible: `end_at` strictly after `start_at`, else `ERR_INVALID_INTERVAL`. A new session starts in `PROPOSED` with `actual_hours` and `cancellation_fee_cents` at 0. Session lists are readable per engagement and per venue.

Booking checks run at proposal in a fixed order after the interval rule: the session must start strictly after the current logical clock, with a start at or before the present rejected as `ERR_SCHEDULE_IN_PAST`; then the expert's calendar is checked under the half-open overlap rule of §2.10, with violations rejected as `ERR_SCHEDULE_CONFLICT`; then, when a `venue_id` is present, the venue's buffered closed-interval rule runs, with violations rejected as `ERR_VENUE_CONFLICT`.

Confirmation re-runs the gauntlet. A `CaseManager` confirms a `PROPOSED` session — moving it `PROPOSED` → `CONFIRMED` — only while the engagement is `ACTIVE`; the in-past check, the expert-calendar check, and the venue check are re-evaluated in that same order against the current clock state, and for a session of kind `TRIAL` the engagement must additionally hold a report in `FINALIZED` or `DISCLOSED`, else `ERR_REPORT_NOT_FINALIZED`. Confirmation recomputes the case's `committed_cents`, because the session's estimate is now committed spend.

Cancellation distinguishes posture and always lands the session in `CANCELLED`. Cancelling a `PROPOSED` session — a `CaseManager` action with an optional `reason` — carries no fee. Cancelling a `CONFIRMED` session inside the late window draws a fee from the retainer: when the logical clock has passed the instant seventy-two hours before the session's `start_at`, the `cancellation_fee_cents` is fifty percent of the estimated testimony value — the `estimated_hours` multiplied by the engagement's `hourly_rate_cents` and by one and a quarter — rounded half-up to the nearest cent; the draw is the lesser of that fee and the remaining retainer, and is added to `retainer_drawn_cents`. The window condition is strict: at exactly the seventy-two-hour boundary the fee is zero. Either way the case's `committed_cents` is recomputed, with the session's estimate removed and any fee retained in the drawn column. Sessions cancelled by the engagement-termination cascade never incur a fee.

Completion waits for the clock. Once the logical clock reaches the session's `end_at`, a `CaseManager` marks the session completed — `CONFIRMED` → `COMPLETED` — recording the `actual_hours` from the payload; the estimate leaves the committed projection.

### 3.7. Invoicing, Budget Enforcement, and Settlement

Billing is expert-initiated. The engaged expert submits an invoice on the engagement with a `period_start` and `period_end` — the period end may equal but never precede the start, else `ERR_INVALID_INTERVAL` — an array of `line_items`, a claimed `travel_expense_cents` (zero or more, default 0), and the client-declared `total_cents`. Each line item carries a `kind` of `PREP`, `TESTIMONY`, or `TRAVEL_TIME` and a strictly positive `hours`; the array may even be empty when a nonzero travel expense is claimed. A new invoice's `status` is `SUBMITTED`, with `dispute_count`, `retainer_draw_cents`, and `billed_to_client_cents` all starting at 0.

The server never trusts the declared total. It recomputes the invoice before persistence — at original submission and again at every resubmission — under a pinned rounding order. Each line's charge is the line's `hours` multiplied by the engagement's `hourly_rate_cents`, multiplied by the kind multiplier: 1.00 for `PREP`, 1.25 for `TESTIMONY`, 0.50 for `TRAVEL_TIME`. Every line amount is rounded half-up to the nearest whole cent first, and only then summed into the service total; the alternative order — summing the raw unrounded line values and rounding once at the end — is explicitly not used and produces different cents (at a rate of 10001 cents per hour, two one-hour `TRAVEL_TIME` lines total 10002 cents under the pinned per-line order versus 10001 under the counterfactual). The travel allowance is the lesser of the claimed `travel_expense_cents` and the remaining expense room — the engagement's `expense_cap_cents` minus its `expenses_approved_cents`, floored at zero, where the approved figure accumulates only the allowed expense portions of invoices in `APPROVED` or `PAID`. The `computed_total_cents` is the service total plus the allowance. A declared `total_cents` that differs from the recomputation — by even one cent — is rejected with `ERR_INVOICE_AMOUNT_MISMATCH`; on an interval violation the interval rule fires first, before the amount comparison.

Budget revisions keep the fiscal target current. A `CaseManager` revises the matter's budget by submitting `new_budget_cents`, a mandatory `reason`, and the OCC guard `expected_case_version` per §2.6; the revision supersedes the prior `budget_cents` and increments the case's `version`, with stale writers rejected as `ERR_STALE_VERSION` (HTTP 412).

Approval belongs to a `BillingReviewer` and is guarded by checks evaluated in a fixed order after the global ladder: segregation of duties first — the approver's `X-User-ID` must differ from the engagement's `created_by_user_id`, so the case manager who created the engagement cannot approve its invoices, with violations rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and then the fiscal boundary: the invoice's `computed_total_cents` must not exceed the case's remaining budget, defined as `budget_cents` minus `actuals_paid_cents` minus `approved_outstanding_cents`; an invoice exactly equal to the remaining budget passes, while exceeding it fails with `ERR_BUDGET_EXCEEDED`. Approval additionally requires the invoice to be `SUBMITTED`, the engagement to be `ACTIVE`, and the case not to be `CLOSED`. On approval (`SUBMITTED` → `APPROVED`) the retainer drawdown runs in the pinned order of §2.8: the draw — the lesser of the approved total and the remaining retainer — is recorded as the invoice's `retainer_draw_cents`, the remainder of the total becomes its `billed_to_client_cents`, the engagement's `retainer_drawn_cents` grows by the draw and its `expenses_approved_cents` by the allowed expense portion, and the case's `approved_outstanding_cents` and `committed_cents` are recomputed.

Disputes cycle without losing history. A `BillingReviewer` disputes a submitted invoice with a `reason` (`SUBMITTED` → `DISPUTED`), incrementing `dispute_count` by one. The engaged expert resubmits with replacement `line_items`, `travel_expense_cents`, and `total_cents` (`DISPUTED` → `SUBMITTED`); the interval rule fires first and the server recomputation second, in the same pinned order as the original submission, with any divergence rejected as `ERR_INVOICE_AMOUNT_MISMATCH`, and `dispute_count` is left unchanged by resubmission.

Settlement closes the loop from either side. A `BillingReviewer` settles with an `outcome`: from `APPROVED`, the `PAID` outcome moves the invoice `APPROVED` → `PAID`, adds its `computed_total_cents` to the case's `actuals_paid_cents`, subtracts the same amount from `approved_outstanding_cents`, and recomputes `committed_cents`; from `DISPUTED`, the `REJECTED` outcome moves the invoice `DISPUTED` → `REJECTED` and recomputes `committed_cents` with the billed amount removed from the forward projection. Both `PAID` and `REJECTED` are terminal. Invoice lists are readable per engagement with an optional `status` filter.

### 3.8. Termination Cascades, Close-Out, and Post-Case Evaluation

Termination is the heaviest operation in the system, and its cascade differs by posture. A `CaseManager` terminates an engagement with a mandatory `reason`.

From `SIGNED`, termination (`SIGNED` → `TERMINATED`) refunds the retainer: `retainer_refunded_cents` becomes the funded amount minus the drawn amount, keeping the ledger invariant of §2.8 intact, and the expert's `active_engagement_count` is recomputed as this engagement drops out.

From `ACTIVE`, termination (`ACTIVE` → `TERMINATED`) fires the full cascade. Every testimony session of the engagement still in `PROPOSED` or `CONFIRMED` is cancelled — with no cancellation fee on this path, regardless of the clock. Every report of the engagement in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED`, `FINALIZED`, or `DISCLOSED` is withdrawn to `WITHDRAWN`; and when the withdrawn report was the case's only `DISCLOSED` one — that is, when no other disclosed report remains across the case's engagements — the case itself reverts `TRIAL_PREP` → `DISCOVERY`. Every document production still in `REQUESTED` or `DELIVERED` is recalled to `RECALLED`. Every invoice in `SUBMITTED` or `DISPUTED` is rejected to `REJECTED`. The remaining retainer — funded minus drawn minus any amount already refunded — moves into `retainer_refunded_cents`. The case's `committed_cents` is recomputed, dropping this engagement's retainer remainder and its schedule estimates, and the expert's `active_engagement_count` is recomputed as well.

Ordinary close-out is stricter than termination. A `CaseManager` closes an engagement from `ACTIVE` only when no report on it remains in `DRAFT`, `IN_REVIEW`, `REVISION_REQUESTED`, or `FINALIZED`, no session remains in `PROPOSED` or `CONFIRMED`, and every invoice is in `PAID` or `REJECTED`; any of these blockers rejects the close with `ERR_ENGAGEMENT_NOT_CLOSABLE`. A clean close (`ACTIVE` → `CLOSED`) recomputes the expert's `active_engagement_count`.

Closing the matter itself is the final act. A `CaseManager` may close a case from `ENGAGED`, from `DISCOVERY`, or from `TRIAL_PREP` — the same preconditions apply at all three — once every engagement of the case has reached `CLOSED` or `TERMINATED` and every invoice on those engagements has reached `PAID` or `REJECTED`; otherwise the close is rejected with `ERR_CASE_NOT_CLOSABLE`. `CLOSED` is terminal for the case.

Learning closes the loop back onto the roster. Once an engagement is `CLOSED` — evaluation against any other engagement posture fails with `ERR_INVALID_STATE` — a `CaseManager` records a post-case evaluation: a mandatory `overall_score` between 0.0 and 5.0 inclusive, optional `quality_score`, `timeliness_score`, and `testimony_score` each in the same range or null (default null), and optional `comments` defaulting to empty. The record's `expert_id` is denormalized from the engagement, and `evaluated_at` stamps the logical clock at creation, anchoring the decay weights of §3.1. Each new evaluation recomputes the expert's `rating_simple` and `rating_decayed`, and it is here that the automatic probation trigger fires: an `ACTIVE` expert left with at least two evaluations and a decayed rating below 3.0 is demoted to `PROBATION`, with the full screening cascade of §3.1.

## 4. Endpoint Definitions

Operations that create a new resource — a case, an expert, a venue, a sourcing request, a screening record, an engagement, a production, a report, a session, an invoice, or an evaluation — return a `201 Created` status code. Operations that modify an existing resource or advance one through its workflow, and all reads, return a `200 OK` status code. The table below is a summary map only; request payloads, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/litigation/experts` | Create roster expert | PlatformAdmin |
| GET | `/litigation/experts` | Expertise search with filters and pagination | PlatformAdmin, CaseManager, ConflictAnalyst, CredentialAnalyst, BillingReviewer |
| GET | `/litigation/experts/{id}` | Expert detail incl. computed ratings and active engagement count | PlatformAdmin, CaseManager, ConflictAnalyst, CredentialAnalyst, BillingReviewer, Expert |
| POST | `/litigation/experts/{id}/roster-status` | Roster maintenance transition | PlatformAdmin |
| GET | `/litigation/experts/{id}/conflict-checks` | Conflict checks for an expert | PlatformAdmin, CaseManager, ConflictAnalyst |
| GET | `/litigation/experts/{id}/credential-reviews` | Credential reviews for an expert | PlatformAdmin, CaseManager, CredentialAnalyst |
| GET | `/litigation/experts/{id}/evaluations` | Evaluations for an expert | PlatformAdmin, CaseManager, BillingReviewer |
| POST | `/litigation/cases` | Open a litigation matter | CaseManager |
| GET | `/litigation/cases/{id}` | Case detail incl. actuals / committed dual-variant fields | PlatformAdmin, CaseManager, BillingReviewer, Expert |
| POST | `/litigation/cases/{id}/budget-revisions` | Revise case budget (OCC; supersedes prior budget) | CaseManager |
| POST | `/litigation/cases/{id}/close` | Close matter when all engagements and invoices are terminal | CaseManager |
| GET | `/litigation/cases/{id}/engagement-requests` | Sourcing requests for a case | PlatformAdmin, CaseManager, ConflictAnalyst, CredentialAnalyst |
| POST | `/litigation/engagement-requests` | Open an expert sourcing request on a case | CaseManager |
| GET | `/litigation/engagement-requests/{id}` | Request detail | PlatformAdmin, CaseManager, ConflictAnalyst, CredentialAnalyst |
| POST | `/litigation/engagement-requests/{id}/conflict-checks` | Open conflict screening for an expert under this request | ConflictAnalyst |
| GET | `/litigation/engagement-requests/{id}/conflict-checks` | Checks under a request | PlatformAdmin, CaseManager, ConflictAnalyst |
| POST | `/litigation/conflict-checks/{id}/resolve` | Resolve screening; WAIVED requires PlatformAdmin | ConflictAnalyst, PlatformAdmin |
| POST | `/litigation/engagement-requests/{id}/credential-reviews` | Open credential/Daubert review for an expert | CredentialAnalyst |
| GET | `/litigation/engagement-requests/{id}/credential-reviews` | Reviews under a request | PlatformAdmin, CaseManager, CredentialAnalyst |
| POST | `/litigation/credential-reviews/{id}/resolve` | Record Daubert/credential outcome | CredentialAnalyst |
| POST | `/litigation/engagements` | Create engagement letter terms for a screened expert | CaseManager |
| GET | `/litigation/engagements` | Engagement list with filters | PlatformAdmin, CaseManager, BillingReviewer, Expert |
| GET | `/litigation/engagements/{id}` | Engagement detail incl. retainer ledger fields | PlatformAdmin, CaseManager, BillingReviewer, Expert |
| POST | `/litigation/engagements/{id}/propose` | Propose terms (initial or re-proposal with optional new rate) | CaseManager |
| POST | `/litigation/engagements/{id}/counter` | Expert counters the proposed rate | Expert |
| POST | `/litigation/engagements/{id}/sign` | Expert signs engagement letter; executes NDA | Expert |
| POST | `/litigation/engagements/{id}/fund-retainer` | Fund retainer; reaching exactly the required amount activates | CaseManager |
| POST | `/litigation/engagements/{id}/amend` | Amend rate/retainer/expense-cap terms (OCC; supersedes prior terms) | CaseManager |
| POST | `/litigation/engagements/{id}/terminate` | Terminate engagement; cascades to schedules/reports/documents/invoices and refunds retainer | CaseManager |
| POST | `/litigation/engagements/{id}/close` | Close engagement after all deliverables terminal | CaseManager |
| POST | `/litigation/engagements/{id}/document-productions` | Register document production to the expert | CaseManager |
| GET | `/litigation/engagements/{id}/document-productions` | Productions for an engagement | PlatformAdmin, CaseManager, Expert |
| POST | `/litigation/document-productions/{id}/advance` | Advance production: DELIVER (CaseManager), ACKNOWLEDGE (Expert owner), RECALL (CaseManager) | CaseManager, Expert |
| POST | `/litigation/engagements/{id}/reports` | Open expert report; deadline pinned from case | CaseManager |
| GET | `/litigation/engagements/{id}/reports` | Reports for an engagement | PlatformAdmin, CaseManager, Expert |
| POST | `/litigation/reports/{id}/submit` | Expert submits draft for review (deadline-gated) | Expert |
| POST | `/litigation/reports/{id}/review` | Case manager review decision: FINALIZE or REQUEST_REVISION | CaseManager |
| POST | `/litigation/reports/{id}/revise` | Expert returns revised draft | Expert |
| POST | `/litigation/reports/{id}/disclose` | Disclose finalized report (before trial date) | CaseManager |
| POST | `/litigation/engagements/{id}/testimony-schedules` | Propose deposition/trial session; overlap-checked | CaseManager |
| GET | `/litigation/engagements/{id}/testimony-schedules` | Schedules for an engagement | PlatformAdmin, CaseManager, Expert |
| GET | `/litigation/venues/{id}/testimony-schedules` | Schedules occupying a venue | PlatformAdmin, CaseManager |
| POST | `/litigation/testimony-schedules/{id}/confirm` | Confirm session (re-checks overlaps; TRIAL requires finalized report) | CaseManager |
| POST | `/litigation/testimony-schedules/{id}/cancel` | Cancel session; late cancel draws fee from retainer | CaseManager |
| POST | `/litigation/testimony-schedules/{id}/complete` | Mark session completed with actual hours | CaseManager |
| POST | `/litigation/venues` | Register a deposition venue | PlatformAdmin |
| GET | `/litigation/venues/{id}` | Venue detail | PlatformAdmin, CaseManager |
| POST | `/litigation/engagements/{id}/invoices` | Expert submits invoice; server recomputes total | Expert |
| GET | `/litigation/engagements/{id}/invoices` | Invoices for an engagement | PlatformAdmin, CaseManager, BillingReviewer, Expert |
| POST | `/litigation/invoices/{id}/approve` | Approve invoice against budget; draws retainer | BillingReviewer |
| POST | `/litigation/invoices/{id}/dispute` | Dispute invoice | BillingReviewer |
| POST | `/litigation/invoices/{id}/resubmit` | Expert resubmits adjusted invoice | Expert |
| POST | `/litigation/invoices/{id}/settle` | Settle: PAID from APPROVED; REJECTED from DISPUTED | BillingReviewer |
| POST | `/litigation/engagements/{id}/evaluations` | Post-case evaluation of the expert | CaseManager |
| GET | `/litigation/engagements/{id}/evaluations` | Evaluations recorded on an engagement | PlatformAdmin, CaseManager, BillingReviewer |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONFLICT_NOT_CLEARED` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_PASSED` | 409 Conflict |
| `ERR_EXPERT_ROSTER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EXPERT_DAUBERT_BARRED` | 422 Unprocessable Entity |
| `ERR_PRIVILEGE_TIER_BLOCKED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_CASE_ENGAGEMENT` | 409 Conflict |
| `ERR_EXPERT_CAPACITY_FULL` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SCREENING` | 409 Conflict |
| `ERR_REPORT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_VENUE_CONFLICT` | 409 Conflict |
| `ERR_REPORT_DEADLINE_PASSED` | 409 Conflict |
| `ERR_TRIAL_DATE_PASSED` | 409 Conflict |
| `ERR_REPORT_NOT_FINALIZED` | 409 Conflict |
| `ERR_INVOICE_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RETAINER_OVERFUND` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ENGAGEMENT_NOT_CLOSABLE` | 409 Conflict |
| `ERR_CASE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_EXPERT_HAS_ACTIVE_ENGAGEMENTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INTERNAL` | 500 Internal Server Error |
