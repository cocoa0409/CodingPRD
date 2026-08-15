# GC Bid Management API — Product Requirements Document

## 1. Introduction

Commercial general contractors live and die by the bid calendar. Every week a handful of bid packages — structural steel for a tower, mechanical rough-in for a hospital wing, site concrete for a parking deck — move through the same gauntlet: an invitation list is assembled, plan-room documents are released, scope addenda fly out in the final days, and on bid day a spread of lump-sum numbers must be tabulated, leveled, and defended before an award recommendation reaches the chief estimator's desk. Between those milestones sit compliance traps that sink projects: a bidder whose prequalification quietly lapsed, a subcontractor who never acknowledged Addendum 3, a bid bond a few dollars short of the required percentage, a leveling sheet whose math nobody can reconstruct afterward.

This document specifies the GC Bid Management API, the system of record for that entire pre-award workflow. It governs subcontractor self-registration and prequalification review, invitation distribution and plan-room telemetry, addendum issuance and acknowledgment tracking, bid submission with last-minute revision handling, bid-day tabulation with compliance disqualification, scope leveling with pinned rounding order, post-bid interviews, award recommendation with segregation of duties between drafting and deciding estimators, and feedback to unsuccessful bidders. The audience is the engineering team building this API; every rule stated here is testable, and no behavior is left to convention.

Two design commitments shape everything that follows. First, the system runs on a **logical clock** — not wall-clock time — so that bid deadlines, prequalification expiry windows, and last-minute revision flags are fully deterministic; before any test-driving call advances it, the logical clock reads exactly `2026-08-01T00:00:00Z` and never falls back to wall-clock time. Second, the system enforces **immediate consistency**: counters such as `submitted_bid_count` and `issued_addendum_count`, derived flags such as `addendum_ack_complete`, and a subcontractor's `current_prequal_status` are recomputed at the moment the underlying event occurs, never by a background job.

## 2. Global Specifications & System-Wide Principles

This section fixes the structural contract of the API — envelopes, headers, pagination, identifiers, rounding, concurrency — plus the cross-cutting principles that recur across every workflow in §3.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID` identifies the acting user, and `X-User-Role` names the capacity in which they act. The declared roles, spelled exactly as the API expects them, are `LeadEstimator`, `ChiefEstimator`, `PrequalReviewer`, `Subcontractor`, and `Anonymous`. A request missing either header, or naming a role outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is declared but not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` differs by role, and this difference drives every ownership check in the system:

- When `X-User-Role` is `Subcontractor`, `X-User-ID` is the `id` of the acting `Subcontractor` record. Ownership checks on any resource that references a subcontractor — an `Invitation`, a `Bid`, an `AddendumAcknowledgment`, a `BidderFeedback` reached through its bid, or a `PrequalApplication` at create, resubmit, or read time — compare the resource's `subcontractor_id` foreign key against `X-User-ID`. A mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
- When `X-User-Role` is `LeadEstimator`, `ChiefEstimator`, `PrequalReviewer`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on an `AwardRecommendation` or `decided_by_user_id` on a decided recommendation — but never compares it to any entity's `id`. The segregation-of-duties check in §3.7 compares these recorded identifiers against the caller's `X-User-ID`, not against any entity.

Role capabilities in brief: the `LeadEstimator` runs the bid event end to end — packages, invitations, addenda, waivers, tabulation, leveling, interviews, recommendation drafting, and feedback delivery. The `ChiefEstimator` holds award authority alone, deciding submitted recommendations, and — by segregation of duties — must never be the drafter of the recommendation being decided. The `PrequalReviewer` verifies subcontractor financials and decides prequalification applications. A `Subcontractor` acts only on its own rows: responding to invitations, accessing the plan room, acknowledging addenda, and submitting, revising, or withdrawing its own bids. An `Anonymous` caller may do exactly one thing — self-register a subcontractor firm. All estimator-side roles (`LeadEstimator`, `ChiefEstimator`, `PrequalReviewer`) may set the logical clock and read any resource their role is authorized for in §4 — which excludes the `PrequalReviewer` from the leveling-sheet, leveling-adjustment, and bidder-feedback endpoints; a `Subcontractor` reading list endpoints sees only its own rows.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the ordering and defaults to 0. Unless an endpoint states otherwise, every list is sorted by `created_at` ascending, with ties — common under the logical clock — broken by `id` ascending. The `meta` object of every paginated response carries exactly four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` formatted as a bare UUID — no type prefix, no human-readable slug. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was first created. All resources except the `BidRevision` audit rows additionally carry `updated_at` (same timestamp format, refreshed on any mutation) and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource. A `BidRevision` is an append-only audit record: it carries only `id` and `created_at` from the common set, and both `updated_at` and `version` are absent from it. Mutations that cascade — for example, tabulation refreshing a package's `apparent_low_bid_id`, or award approval flipping a bid's `status` — are ordinary mutations on each affected resource: each touched row's `updated_at` is refreshed and its `version` is incremented where that row carries one.

### 2.5. The Logical Clock and Deadline Discipline

The system never consults wall-clock time. All temporal rules — the bid deadline, the 365-day prequalification validity window, the 60-minute last-minute revision window, the `responded_at`, `submitted_at`, `acknowledged_at`, `sent_at`, `decided_at`, `approved_at`, and `issued_at` stamps — read the logical clock, which starts at exactly `2026-08-01T00:00:00Z` before any test-driving call. An estimator-side capability exists to advance the logical clock to a supplied instant (accepted as `to_iso8601`); the clock moves only forward to the supplied value, the call answers with the resulting `current_utc`, and the clock is the single time source for every rule in this document.

Three deadline gates hang off the logical clock, each with its own error. Publishing a bid package requires the logical now to be strictly before the package's `bid_due_at`; otherwise the publish is rejected with `ERR_BID_DEADLINE_PASSED`. Bid submission and bid revision likewise require the logical now to be strictly before `bid_due_at` — the deadline is strict, so a submission landing exactly at the deadline instant is rejected with `ERR_BID_DEADLINE_PASSED`. Closing bidding runs the opposite inequality: it requires the logical now to be at or after `bid_due_at`, and an early attempt is rejected with `ERR_BID_DEADLINE_NOT_REACHED` (HTTP 422 in all three cases).

### 2.6. Monetary Precision and Rounding

Money is integer cents everywhere: `base_bid_cents`, `bond_amount_cents`, `amount_cents`, `resolved_amount_cents`, `leveled_amount_cents`, `winning_leveled_amount_cents`, and the revenue and bonding-capacity figures are all integers, never floats. Where a calculation must convert a fractional input into cents — a percentage-of-base leveling adjustment, or the required bid bond — the product is rounded to integer cents using the round-half-up method, and that rounding happens at the pinned step described in §3 for each calculation. Prequalification scores are the one non-integer numeric surface: components and the weighted total are each rounded to exactly 2 decimal places, again round half up, at the pinned steps in §3.4. Comparisons that decide awards and ranks (`bid_tabulation_ranking`) are integer-cent comparisons with no tolerance.

### 2.7. Optimistic Concurrency Control

Exactly two write endpoints carry an optimistic-concurrency contract; no other endpoint accepts a version field.

A bid revision request must carry `expected_bid_version` equal to the bid's current `version` as the caller last observed it. If the bid's `version` has advanced since that observation — because an earlier revision was recorded against it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from overwriting a bid state it has not seen. A successful revision increments the bid's `version` by 1.

Drafting an award recommendation must carry `expected_bid_package_version` equal to the package's current `version` as the caller last observed it. If the package's `version` has advanced since that observation — for example because a re-tabulation refreshed the rankings, or a recommendation draft was just created against the same package — the create is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412), because a recommendation must be based on the latest tabulation state.

Endpoints not named in this subsection take no version field; omitting `expected_bid_version` or `expected_bid_package_version` on the two endpoints that require them is a missing-required-field rejection under §2.9's payload rules. On either endpoint, the version comparison is evaluated only after every other gate of §2.8 has passed — immediately before the mutation is applied — so a request that is both stale and in violation of another rule reports the other rule's error.

### 2.8. Validation Order and Nested Resource Resolution

Every request passes through a fixed validation cascade, and the order is observable. Authentication context comes first (missing or malformed headers, then role authorization — priorities 1 and 2). Existence checks come next (priority 3): resource identifiers in the path are validated left to right, then body-referenced foreign keys in input order, each miss producing the corresponding 404 — `ERR_BID_PACKAGE_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_PREQUAL_APPLICATION_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`, `ERR_ADDENDUM_NOT_FOUND`, `ERR_BID_NOT_FOUND`, or the generic `ERR_RESOURCE_NOT_FOUND` for leveling adjustments, interviews, recommendations, feedbacks, and acknowledgments. Ownership scoping for `Subcontractor` callers follows (priority 4, `ERR_FORBIDDEN_OWNERSHIP`). Then state gates (priority 5): the target resource must be in a from-state permitted for the trigger, rejected with the machine-specific `ERR_PACKAGE_INVALID_STATE`, `ERR_INVITATION_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`, `ERR_BID_INVALID_STATE`, or the generic `ERR_INVALID_RESOURCE_STATE`; bid-write, plan-room, and reconsider operations that require a `PUBLISHED` package surface `ERR_PACKAGE_NOT_ACCEPTING_BIDS`; leveling writes outside the unlocked package states surface `ERR_LEVELING_LOCKED`. The business-safety gate follows (priority 6): the segregation-of-duties gate on award decisions (`ERR_SOD_VIOLATION`, HTTP 403). Uniqueness and eligibility checks come next (priority 7), each with its own error listed in §3: duplicate license numbers, duplicate invitations, publish with no invitees, prequal window overlap, duplicate bids, invitation not in `BIDDING`, the prequalification gate on bid creation (`ERR_PREQUAL_NOT_APPROVED`), plan-room access on a declined invitation, interview time ranges and room overlap, ineligible recommended bids, an already-active recommendation, and tabulation with no compliant bids. Deadline gates are priority 8, and bid-bond sufficiency is priority 9. Payload-shape validation (`ERR_INVALID_REQUEST`, HTTP 400) is deliberately last at priority 10, so that a malformed-but-parseable payload that also violates a business rule reports the business error. Outright schema-parse failures short-circuit that ordering, but not at one fixed point: on endpoints addressed by a path identifier, the path resource's existence is confirmed before the request body is inspected at all; on creation endpoints whose identifiers arrive in the body, the unknown-field and missing-required-field checks run immediately after the priority 1–2 checks, ahead of foreign-key existence; and every other payload check — per-field type, range, enum, and the exactly-one-of rule — fires as each field is consumed during the cascade rather than at one fixed priority.

### 2.9. Payload Shape Discipline

Request bodies must contain exactly the fields the endpoint accepts. Required fields must be present; enum fields must carry a declared member; numeric ranges must be honored — `base_bid_cents` strictly greater than 0, `bond_amount_cents` at least 0, `bid_bond_required_pct` strictly greater than 0 and at most 0.20, revenue and bonding-capacity figures at least 0, `declared_emr` strictly greater than 0. On leveling adjustments, exactly one of `amount_cents` or `pct_of_base` must be supplied — supplying both or neither breaks the exactly-one-of rule. Computed, system-managed, or read-only fields supplied by the client (for example `status`, `version`, `resolved_amount_cents`, `self_reported_score`, `submitted_bid_count`) are rejected. Every violation of this discipline is `ERR_INVALID_REQUEST` (HTTP 400), sequenced per §2.8.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Bid Event: Packages and the Invitation List

A bid event begins when a `LeadEstimator` creates a **bid package** with a `name` (a working title such as "Structural Steel — Tower A"), a `trade_code` label, the `bid_due_at` deadline, and optionally the `bid_bond_required_pct` — the fraction of the base bid that the submitted bond must cover, defaulting to 0.05 when omitted and always constrained to greater than 0 and at most 0.20. The package is born in `DRAFT` status with `issued_addendum_count` and `submitted_bid_count` both at 0 and `compliant_bid_count`, `apparent_low_bid_id`, and `leveled_low_bid_id` all null until the first tabulation.

While the package is `DRAFT` or `PUBLISHED`, the `LeadEstimator` builds the bidders list by creating **invitations**, each pairing a `bid_package_id` with a `subcontractor_id`. One invitation may exist per subcontractor per package; a second invite to the same firm on the same package is rejected with `ERR_DUPLICATE_INVITATION` (HTTP 409). Each invitation starts in `SENT` status.

Publishing is the point of no return for setup. A `LeadEstimator` publishes the package, moving it `DRAFT → PUBLISHED`, which makes invitations live and opens the plan room. Two preconditions guard the publish, and the existence/state ordering of §2.8 applies: at least one invitation must exist for the package (otherwise `ERR_NO_INVITED_BIDDERS`, HTTP 422), and the logical now must be strictly before `bid_due_at` (otherwise `ERR_BID_DEADLINE_PASSED`). Publishing increments the package's `version` by 1, as do close-bidding and each tabulation later in the lifecycle. The full package lifecycle is `DRAFT → PUBLISHED → BIDDING_CLOSED → TABULATED → RECOMMENDATION_PENDING → AWARDED`, with a return edge from `RECOMMENDATION_PENDING` back to `TABULATED` when a recommendation is returned, and `AWARDED` as the terminal state.

### 3.2. The Bidder's Door: Registration and Prequalification

A subcontracting firm enters the system by self-registering as an `Anonymous` caller, supplying its `legal_name`, `contact_email`, and `license_number`. The license number is unique across all subcontractors; a registration that reuses one is rejected with `ERR_DUPLICATE_LICENSE_NUMBER` (HTTP 409). The new firm's `current_prequal_status` starts at `NONE`.

To become biddable, the firm files a **prequalification application** as a `Subcontractor`, naming its own `subcontractor_id` (which must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`) and three self-reported figures: `declared_annual_revenue_cents` (average annual revenue, integer cents, at least 0), `declared_emr` (experience modification rate, strictly greater than 0), and `declared_bonding_capacity_cents` (single-project bonding capacity, integer cents, at least 0). The application is born in `SUBMITTED` status, and the system immediately computes its `self_reported_score` using the self-reported variant of the scoring rule in §3.4.

Only one live application may exist per subcontractor at a time: a create or resubmit is rejected with `ERR_PREQUAL_WINDOW_OVERLAP` (HTTP 409) while another application for the same firm is `SUBMITTED`, or `APPROVED` with an `expires_at` still in the future. A `PrequalReviewer` then decides the application. Approving requires all three verified inputs — `verified_annual_revenue_cents`, `verified_emr`, and `verified_bonding_capacity_cents` — present in the decision payload (a missing one is `ERR_INVALID_REQUEST`), each carrying the same range as its declared counterpart (revenue and bonding capacity integer cents at least 0, EMR a number strictly greater than 0), plus a `verified_score` of at least 70 computed from those verified inputs (otherwise `ERR_PREQUAL_SCORE_BELOW_THRESHOLD`, HTTP 422). On approval the system stamps `approved_at` with the logical now, sets `expires_at` to exactly 365 days after `approved_at`, and records the decision in `review_notes` if supplied. Rejection takes the same `decision` field with no verified-input requirement; when all verified inputs happen to be present on a rejection, the `verified_score` is still computed and stored, and it remains null otherwise — a partially supplied verified set on a rejection is discarded entirely, with no `verified_*` field stored. Either decision recomputes the firm's `current_prequal_status`.

Approval is not permanent. An application whose `expires_at` has been reached transitions `APPROVED → EXPIRED` lazily: the transition is applied whenever the application is read or consulted for a prequalification check and the logical now is at or past `expires_at`, and the firm's `current_prequal_status` is recomputed at that moment. The derived status itself is defined by a precedence walk over the firm's applications, ignoring `EXPIRED` rows entirely: `APPROVED` if a non-expired approved application exists at the logical now; otherwise `SUBMITTED` if one is awaiting decision; otherwise `REJECTED` if a rejected one exists; otherwise `NONE`. A rejected application may be resubmitted by the firm with fresh declared figures; resubmission moves it `REJECTED → SUBMITTED` (subject to the window-overlap gate above), recomputes `self_reported_score` from the new inputs, and clears every `verified_*` field and the `verified_score` back to null. Deciding an application that is not `SUBMITTED`, or resubmitting one that is not `REJECTED`, is rejected with `ERR_APPLICATION_INVALID_STATE` (HTTP 409).

### 3.3. Invitations in Play: Responses and the Plan Room

Once a package is `PUBLISHED`, invited firms respond. A `Subcontractor` responds to its own invitation with an `intent` of `BIDDING` or `DECLINED`; the invitation's `subcontractor_id` must equal the caller's `X-User-ID` (`ERR_FORBIDDEN_OWNERSHIP` otherwise). The transitions are `SENT → BIDDING`, `SENT → DECLINED`, `BIDDING → DECLINED`, and — the reconsider path — `DECLINED → BIDDING`, which is permitted only while the package remains `PUBLISHED` (otherwise `ERR_PACKAGE_NOT_ACCEPTING_BIDS`, HTTP 409). An `intent` that matches no permitted transition from the invitation's current status is rejected with `ERR_INVITATION_INVALID_STATE`. Every response stamps `responded_at` with the logical now.

Declining has a cleanup cascade: when an invitation moves from `BIDDING` to `DECLINED`, every still-`PENDING` addendum acknowledgment owed by that subcontractor on the package's addenda is moved to `WAIVED` with its `waived_reason` recorded as "bidder declined", and `addendum_ack_complete` is recomputed on the affected `SUBMITTED` bids. Reconsidering has the mirror cascade: when an invitation moves from `DECLINED` back to `BIDDING`, the system creates a fresh `PENDING` acknowledgment for each addendum of the package that lacks one in `PENDING` or `ACKNOWLEDGED` for this subcontractor — earlier `WAIVED` rows are retained as audit history, not resurrected.

Plan-room telemetry rides on the invitation. Each successful plan-room access by the invited subcontractor sets `first_plan_room_access_at` exactly once (the first time only) and increments `plan_room_access_count` by 1. Access requires the package to be `PUBLISHED` (otherwise `ERR_PACKAGE_NOT_ACCEPTING_BIDS`) and the invitation to be in `SENT` or `BIDDING`; accessing on a `DECLINED` invitation is rejected with `ERR_INVITATION_DECLINED` (HTTP 409).

### 3.4. Scoring Financial Strength: The Prequalification Score

Both score variants share one weighted formula with three components, and the rounding order is pinned. The **financial component** takes the revenue figure (declared or verified, per variant), divides it by a reference of 5,000,000,000 cents, multiplies by 100, caps the result at 100, and rounds half-up to 2 decimal places. The **safety component** is a piecewise function of the EMR: an EMR at or below 0.70 scores a full 100.00; an EMR at or above 1.20 scores 0.00; between those bounds the score is 100 minus twice the excess of the EMR over 0.70, expressed as 100 minus the product of 200 and the difference between the EMR and 0.70, rounded half-up to 2 decimal places. The **bonding component** divides the bonding-capacity figure by a reference of 2,000,000,000 cents, multiplies by 100, caps at 100, and rounds half-up to 2 decimal places. The total score weights the three individually rounded components — 0.40 for financial, 0.35 for safety, 0.25 for bonding — sums the weighted components, and rounds the sum half-up to 2 decimal places. Components are always rounded before weighting; weighting unrounded components and rounding only the total is a different number and is rejected.

The two variants differ only in inputs and one override. The **self-reported variant** runs at application submission and resubmission over the `declared_*` inputs and lands in `self_reported_score`; it carries no hard-fail rule. The **verified variant** runs at reviewer decision over the `verified_*` inputs and lands in `verified_score`; it carries the EMR hard fail: if the verified EMR is at or above 1.25, the `verified_score` is forced to exactly 0.00 regardless of the other components. Since approval requires a `verified_score` of at least 70 (the pass threshold), a hard-failed EMR makes approval impossible and surfaces as `ERR_PREQUAL_SCORE_BELOW_THRESHOLD`.

### 3.5. Addenda and the Acknowledgment Ledger

Scope changes mid-event are issued as **addenda**. A `LeadEstimator` issues an addendum to a `PUBLISHED` package by supplying its `bid_package_id` and a `summary` of the scope change; issuing outside `PUBLISHED` is rejected with `ERR_PACKAGE_INVALID_STATE`. The addendum's `number` is assigned per package as one more than the highest existing number for that package, starting at 1; `issued_at` is stamped at creation and the row is immutable afterward. Issuance cascades immediately: for every invitation on the package in `SENT` or `BIDDING` status, a `PENDING` **addendum acknowledgment** is created; each affected subcontractor's `SUBMITTED` bids on the package have `addendum_ack_complete` recomputed (to false, since a `PENDING` row now exists); and the package's `issued_addendum_count` increments by 1.

An acknowledgment row ties an `addendum_id` to the invited `subcontractor_id` that owes the acknowledgment, and lives in `PENDING`, `ACKNOWLEDGED`, or `WAIVED`, with the latter two terminal. A `Subcontractor` acknowledges an addendum, resolving its own `PENDING` row to `ACKNOWLEDGED` and stamping `acknowledged_at`; the preconditions are that the package is in `PUBLISHED` or `BIDDING_CLOSED` (otherwise `ERR_PACKAGE_INVALID_STATE`) and that a `PENDING` acknowledgment actually exists for the pair of that addendum and the caller's subcontractor id — never issued, already resolved, or belonging to another firm all surface as `ERR_ACKNOWLEDGMENT_NOT_FOUND` (HTTP 404) — and the package-state gate is evaluated first, so a call failing both surfaces `ERR_PACKAGE_INVALID_STATE`. A `LeadEstimator` may instead waive a subcontractor's `PENDING` acknowledgment, supplying the `subcontractor_id` and an optional `reason` that is recorded as `waived_reason`; waive carries the same not-found and package-state preconditions, in the same order. Both resolution paths recompute `addendum_ack_complete` on that subcontractor's `SUBMITTED` bids of the package. The third path into `WAIVED` is the bidder-declined cascade of §3.3.

The `addendum_ack_complete` flag on a bid is defined precisely: it is true if and only if no `PENDING` acknowledgment exists for the pairing of that bid's package and that bid's subcontractor. It is the compliance thread that tabulation pulls on in §3.8.

### 3.6. Bid Day: Submission, Bonds, and Last-Minute Revisions

Bid submission is creation — there is no draft state for bids. A `Subcontractor` submits by supplying the `bid_package_id`, a `base_bid_cents` lump sum (integer cents, strictly greater than 0), and a `bond_amount_cents` (integer cents, at least 0). The bid's `subcontractor_id` is set from the caller's `X-User-ID`, never from the payload. Six preconditions gate the create, in the cascade order of §2.8: the package must be `PUBLISHED` (`ERR_PACKAGE_NOT_ACCEPTING_BIDS`); the caller's invitation for the package must be in `BIDDING` status (`ERR_INVITATION_NOT_BIDDING`, HTTP 422); no other non-terminal bid — one still `SUBMITTED` — may exist for this package and caller (`ERR_DUPLICATE_BID`, HTTP 409); the caller must hold a prequalification application `APPROVED` with `expires_at` still in the future, with lazy expiry applied to that check first (`ERR_PREQUAL_NOT_APPROVED`, HTTP 422); the logical now must be strictly before `bid_due_at` (`ERR_BID_DEADLINE_PASSED`); and the bond must cover the required amount (`ERR_BID_BOND_INSUFFICIENT`, HTTP 402).

The required bond is computed per package: multiply the bid amount by the package's `bid_bond_required_pct`, round the product half-up to integer cents, and compare — the submitted `bond_amount_cents` must be at least the required figure. Equality passes; one cent short fails. When the package uses the default bond percentage, the required figure is 5 percent of the base bid, rounded half-up to cents.

A submitted bid lands in `SUBMITTED` status with `submitted_at` stamped, `version` starting at 1, `disqualification_reason` null, and the package's `submitted_bid_count` incremented by 1. Creation also writes the first row of the bid's revision audit trail: a **bid revision** with `sequence` 1, carrying the original `base_bid_cents` as its `amount_cents`, its `revised_at` stamped at the logical now, and its `is_last_minute` flag computed.

Before the deadline, the bidder may revise the amount. A revision supplies `new_base_bid_cents`, the OCC token `expected_bid_version` (per §2.7), and an optional `note` — the natural home for a last-minute phone-in reference. The same ownership, package-state, deadline, and bond-sufficiency gates apply to revisions as to creation, with the bond re-checked against the new amount. A successful revision overwrites `base_bid_cents` with the new amount, increments the bid's `version` by 1, appends a revision row whose `sequence` is one more than the bid's current maximum and whose `amount_cents` carries the new base, and responds with the updated bid object (HTTP 200), not the new revision row. The `is_last_minute` flag on every revision row — including the sequence-1 row at submission — is true if and only if the gap between `bid_due_at` and the row's `revised_at` is at most 60 minutes, inclusive; a revision recorded with exactly one hour to go is last-minute. The full audit trail is readable in `sequence` order by estimators and by the owning subcontractor.

Withdrawal is the bidder's exit: while the package is `PUBLISHED`, the owning `Subcontractor` may withdraw its `SUBMITTED` bid, moving it to `WITHDRAWN` and decrementing the package's `submitted_bid_count` by 1. Revision or withdrawal against a bid that has reached a terminal state (`AWARDED`, `NOT_AWARDED`, `DISQUALIFIED`, `WITHDRAWN`) is rejected with `ERR_BID_INVALID_STATE` (HTTP 409).

### 3.7. Leveling the Spread: Adjustments, Resolved Amounts, and the Leveling Sheet

Raw base bids are rarely comparable — one bidder excludes temporary bracing, another carries an allowance for winter conditions. The **leveling adjustment** is the `LeadEstimator`'s tool for normalizing the spread. Each adjustment hangs off a `bid_id` and carries a free-text `description` of the scope line being leveled, a `treatment` of `GC_ALLOWANCE`, `SUB_QUOTE`, or `EXCLUDED_SCOPE`, and a price expressed as exactly one of `amount_cents` (an absolute figure, which may be negative) or `pct_of_base` (a fraction of the bid's `base_bid_cents`, such as 0.025).

The resolved contribution of each adjustment is pinned. When `amount_cents` is given, `resolved_amount_cents` is that figure verbatim. When `pct_of_base` is given, the resolved figure is the product of the bid's current `base_bid_cents` and `pct_of_base`, rounded half-up to integer cents — and this per-adjustment rounding happens before any summation. An adjustment whose `treatment` is `EXCLUDED_SCOPE` always contributes 0 to the leveled total regardless of its price fields, but its presence matters: it sets the leveling sheet's exclusion flag.

The **leveled amount** of a bid is then the bid's `base_bid_cents` plus the sum of the `resolved_amount_cents` of every adjustment on the bid whose treatment is `GC_ALLOWANCE` or `SUB_QUOTE`. Sum-then-round — totaling fractional products and rounding once — is explicitly rejected; each percentage adjustment is rounded to integer cents individually and only then summed. The leveled amount is computed on leveling-sheet read and again during tabulation for every compliant bid.

The leveling sheet for a bid is a computed read returning the bid's `bid_id`, its `base_bid_cents`, the adjustment list with resolved amounts, the `leveled_amount_cents` total, a `has_exclusions` flag that is true when any adjustment on the bid carries the `EXCLUDED_SCOPE` treatment, a `pending_addendum_ack_count` of outstanding `PENDING` acknowledgments for this bidder on this package, and an `is_compliant` summary flag that is true exactly when the bid is still `SUBMITTED`, that pending count is zero, and the bidder holds a currently approved prequalification (lazy expiry applied) — the same two disqualifiers tabulation applies in §3.8.

Leveling has a locking lifecycle tied to the package. Adjustments may be created, edited, or deleted only while the package is `BIDDING_CLOSED` or `TABULATED`; a leveling write while the package is `RECOMMENDATION_PENDING` or `AWARDED` — or not yet `BIDDING_CLOSED` — is rejected with `ERR_LEVELING_LOCKED` (HTTP 409). Creating an adjustment computes its `resolved_amount_cents`; editing one (any of `description`, `treatment`, `amount_cents`, `pct_of_base`) recomputes it — the edit is partial, omitted fields keep their values, and a price field supplied as explicit null is cleared, with the exactly-one-of rule re-validated against the resulting pair; deleting one restores the bid's leveled total by removal. Any adjustment write against a bid no longer `SUBMITTED` is rejected with `ERR_BID_INVALID_STATE`, a check evaluated before the package-level leveling-lock gate, so a write failing both reports `ERR_BID_INVALID_STATE`.

### 3.8. Tabulation: The Compliance Sweep and the Two Low Bids

When the logical now reaches `bid_due_at`, the `LeadEstimator` closes bidding, moving the package `PUBLISHED → BIDDING_CLOSED`; attempting this before the deadline is `ERR_BID_DEADLINE_NOT_REACHED`. From `BIDDING_CLOSED` — and again from `TABULATED` after leveling edits — tabulation runs, and it is two distinct phases.

The first phase is the **compliance sweep**, an in-memory eligibility evaluation over every bid still `SUBMITTED`. Each bid is checked against two disqualifiers, in a pinned order: first the addendum-acknowledgment check — if any `PENDING` acknowledgment exists for the pairing of the package and the bid's subcontractor, the bid is disqualified with `disqualification_reason` set to `MISSING_ADDENDUM_ACK`; second the prequalification check — if the bid's subcontractor holds no application `APPROVED` with `expires_at` in the future (lazy expiry applied), the bid is disqualified with `disqualification_reason` `PREQUAL_LAPSED`. When both apply to the same bid, the acknowledgment check runs first and the recorded reason is `MISSING_ADDENDUM_ACK`. Disqualification is terminal: re-tabulation never resurrects a `DISQUALIFIED` bid. Each disqualification also decrements the package's `submitted_bid_count` by 1, mirroring withdrawal.

The second phase is **ranking** over the surviving compliant set — the bids still `SUBMITTED` after the sweep. Two low bidders are selected by two different keys. The apparent low bidder is the compliant bid with the smallest `base_bid_cents` — the raw bid-day number, ignoring leveling entirely. The leveled low bidder is the compliant bid with the smallest leveled amount as computed in §3.7 — and because leveling moves numbers, the leveled low bidder may be a different firm than the apparent low bidder on the identical bid set. Both orderings break ties identically: the earlier `submitted_at` wins; a further tie is broken by the earlier `created_at`. The sweep writes `compliant_bid_count` and both `apparent_low_bid_id` and `leveled_low_bid_id` onto the package and moves it `BIDDING_CLOSED → TABULATED`.

Two failure and repetition rules bound tabulation. If the compliant set after the sweep is empty, the entire tabulate call fails with `ERR_NO_COMPLIANT_BIDS` (HTTP 422) and no state changes are applied — no disqualifications persist, no counters move, the package stays put. And re-tabulation from `TABULATED` requires at least one bid still `SUBMITTED`; it re-runs the ranking over that set and refreshes `apparent_low_bid_id`, `leveled_low_bid_id`, and `compliant_bid_count`, which is how leveling edits made after the first tabulation flow into the rankings. Each bid's `leveled_rank` — its 1-based position in the leveled ordering under the same tie-breaks — is computed in the same pass; it is snapshotted onto feedback records at award time in §3.10.

### 3.9. Post-Bid Interviews and the Recommendation Pipeline

Between tabulation and award, the `LeadEstimator` may schedule **post-bid interviews** with shortlisted bidders. Scheduling requires the bid's package to be `TABULATED` or `RECOMMENDATION_PENDING` (otherwise `ERR_PACKAGE_INVALID_STATE`), the bid itself to be `SUBMITTED` (otherwise `ERR_BID_INVALID_STATE`), and a sane window: `scheduled_start` strictly before `scheduled_end` (otherwise `ERR_INVALID_TIME_RANGE`, HTTP 422). Interviews block rooms: the new interview's `interview_room` must not collide with any other `SCHEDULED` interview in the same room under half-open interval semantics — the new interval from `scheduled_start` up to but not including `scheduled_end` may not overlap an existing one, while pure adjacency, where one interview's end equals another's start, is allowed; a genuine overlap is rejected with `ERR_INTERVIEW_ROOM_OVERLAP` (HTTP 409). Completing an interview moves it `SCHEDULED → HELD` and records `outcome_notes`, a required field of the complete call (a missing one is `ERR_INVALID_REQUEST`); a `HELD` interview no longer blocks its room in future overlap checks. Completing an interview that is not `SCHEDULED` is `ERR_INVALID_RESOURCE_STATE`.

The award decision itself is a two-chair pipeline with segregation of duties. A `LeadEstimator` drafts an **award recommendation** against a `TABULATED` package, supplying the `bid_package_id`, a `recommended_bid_id`, a `rationale` covering scope coverage, leveling outcome, and interview result, and the OCC token `expected_bid_package_version` (per §2.7). The recommended bid must be a `SUBMITTED` bid of this very package — a bid from another package or in any other status is `ERR_RECOMMENDED_BID_INELIGIBLE` (HTTP 422). At most one recommendation per package may be alive in `DRAFT` or `SUBMITTED`; a second draft while one is active is `ERR_ACTIVE_RECOMMENDATION_EXISTS` (HTTP 409). The draft is born in `DRAFT` with `created_by_user_id` recorded from the caller's `X-User-ID`, and creating it increments the package's `version` by 1 — which is precisely why the next drafter must carry a fresh `expected_bid_package_version`.

Submitting the draft moves the recommendation `DRAFT → SUBMITTED` and, in the same motion, moves the package `TABULATED → RECOMMENDATION_PENDING`. That package transition locks leveling: from this moment, adjustment writes on the package's bids are rejected with `ERR_LEVELING_LOCKED`, freezing the numbers the decision will rest on. Submitting a recommendation not in `DRAFT`, or deciding one not in `SUBMITTED`, is `ERR_INVALID_RESOURCE_STATE`.

The `ChiefEstimator` then decides. Approval requires only one precondition beyond state: the deciding caller's `X-User-ID` must differ from the recommendation's `created_by_user_id` — the drafter may not approve their own recommendation, and a violation is `ERR_SOD_VIOLATION` (HTTP 403). On approval, `decided_by_user_id` and `decided_at` are recorded and the award cascade of §3.10 fires. Returning — the other decision — additionally requires `decision_notes` to be present (`ERR_INVALID_REQUEST` otherwise); it records the same decider fields, moves the recommendation `SUBMITTED → RETURNED`, and swings the package `RECOMMENDATION_PENDING → TABULATED`, which unlocks leveling and retains `apparent_low_bid_id` and `leveled_low_bid_id` from the last tabulation, leaving the field clear for a fresh draft.

### 3.10. Award, and the Courtesy of Feedback

Approval of a recommendation triggers the package's terminal cascade. The package moves `RECOMMENDATION_PENDING → AWARDED`. The recommended bid moves `SUBMITTED → AWARDED`; every other bid still `SUBMITTED` moves `SUBMITTED → NOT_AWARDED`. For each bid that became `NOT_AWARDED`, the system auto-creates a **bidder feedback** record in `DRAFT`, snapshotting three figures at the moment of award: the bid's `leveled_rank` from the latest tabulation ordering, its own `leveled_amount_cents`, and the `winning_leveled_amount_cents` — the leveled amount of the awarded bid.

A `LeadEstimator` later sends a feedback record, optionally supplying a `notes` narrative; sending moves it `DRAFT → SENT` and stamps `sent_at`. Re-sending a `SENT` record is `ERR_INVALID_RESOURCE_STATE`. Visibility is deliberately asymmetric: the `LeadEstimator` and `ChiefEstimator` see all feedback rows (the `PrequalReviewer` is not authorized on the feedback endpoints), while a `Subcontractor` sees only `SENT` rows on its own bids — a `DRAFT` feedback is never visible to a subcontractor, and a subcontractor touching another firm's feedback through its bid's `subcontractor_id` is `ERR_FORBIDDEN_OWNERSHIP`. The subcontractor's own acknowledgment ledger remains readable to the firm through the acknowledgments listing scoped by `subcontractor_id`, with an optional `status` filter, throughout the event.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`; deletion returns `204 No Content`. Request and response bodies follow §2.2; the narrative of §3 defines each endpoint's inputs, preconditions, and side effects. List endpoints additionally accept optional equality filters as query parameters: `/bid-packages` filters by `status`, `apparent_low_bid_id`, and `leveled_low_bid_id`; `/prequal-applications` by `subcontractor_id` and `status`; `/invitations` by `bid_package_id`, `subcontractor_id`, and `status`; `/addendums` by `bid_package_id`; `/addendums/{id}/acknowledgments` by `status` and `subcontractor_id`; `/subcontractors/{id}/acknowledgments` by `status`; and `/bids` by `bid_package_id`, `subcontractor_id`, and `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving) | LeadEstimator, ChiefEstimator, PrequalReviewer |
| POST | `/bid-packages` | Create a bid package (DRAFT) | LeadEstimator |
| GET | `/bid-packages` | List bid packages (paginated, filterable) | LeadEstimator, ChiefEstimator, PrequalReviewer |
| GET | `/bid-packages/{id}` | Read a bid package | LeadEstimator, ChiefEstimator, PrequalReviewer |
| POST | `/bid-packages/{id}/publish` | Publish the ITB: DRAFT → PUBLISHED | LeadEstimator |
| POST | `/bid-packages/{id}/close-bidding` | Close the bid period: PUBLISHED → BIDDING_CLOSED | LeadEstimator |
| POST | `/bid-packages/{id}/tabulate` | Run tabulation: compliance sweep plus apparent/leveled ranking; re-runs from TABULATED | LeadEstimator |
| GET | `/bid-packages/{id}/award-recommendations` | List award recommendations of a package | LeadEstimator, ChiefEstimator, PrequalReviewer |
| POST | `/subcontractors` | Self-register a subcontractor firm | Anonymous |
| GET | `/subcontractors` | List subcontractors (paginated) | LeadEstimator, ChiefEstimator, PrequalReviewer |
| GET | `/subcontractors/{id}` | Read a subcontractor (Subcontractor reads only its own row) | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| GET | `/subcontractors/{id}/acknowledgments` | List addendum acknowledgments owed by a subcontractor | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| POST | `/prequal-applications` | Submit a prequalification application | Subcontractor |
| GET | `/prequal-applications` | List prequalification applications (Subcontractor sees only own) | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| GET | `/prequal-applications/{id}` | Read a prequalification application | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| POST | `/prequal-applications/{id}/decision` | Reviewer decision: APPROVED or REJECTED | PrequalReviewer |
| POST | `/prequal-applications/{id}/resubmit` | Resubmit a REJECTED application with updated declared inputs | Subcontractor |
| POST | `/invitations` | Invite a subcontractor to a bid package | LeadEstimator |
| GET | `/invitations` | List invitations (Subcontractor sees only own) | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| GET | `/invitations/{id}` | Read an invitation | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| POST | `/invitations/{id}/respond` | Respond to an invitation: intent BIDDING or DECLINED | Subcontractor |
| POST | `/invitations/{id}/plan-room-access` | Record a plan-room access by the invited subcontractor | Subcontractor |
| POST | `/addendums` | Issue an addendum to a PUBLISHED package | LeadEstimator |
| GET | `/addendums` | List addenda | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| GET | `/addendums/{id}` | Read an addendum | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| GET | `/addendums/{id}/acknowledgments` | List acknowledgments for an addendum | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| POST | `/addendums/{id}/acknowledge` | Acknowledge an addendum as the invited subcontractor | Subcontractor |
| POST | `/addendums/{id}/waive` | Waive a subcontractor's PENDING acknowledgment | LeadEstimator |
| POST | `/bids` | Submit a bid (creation is submission) | Subcontractor |
| GET | `/bids` | List bids (Subcontractor sees only own) | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| GET | `/bids/{id}` | Read a bid | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| POST | `/bids/{id}/revisions` | Record a bid-amount revision (OCC via expected bid version) | Subcontractor |
| GET | `/bids/{id}/revisions` | List a bid's revision audit trail in sequence order | LeadEstimator, ChiefEstimator, PrequalReviewer, Subcontractor |
| POST | `/bids/{id}/withdraw` | Withdraw a SUBMITTED bid while the package is PUBLISHED | Subcontractor |
| GET | `/bids/{id}/leveling-sheet` | Computed leveling sheet for a bid | LeadEstimator, ChiefEstimator |
| GET | `/bids/{id}/leveling-adjustments` | List leveling adjustments of a bid | LeadEstimator, ChiefEstimator |
| GET | `/bids/{id}/post-bid-interviews` | List post-bid interviews for a bid | LeadEstimator, ChiefEstimator, PrequalReviewer |
| GET | `/bids/{id}/award-recommendations` | List award recommendations referencing a bid | LeadEstimator, ChiefEstimator, PrequalReviewer |
| GET | `/bids/{id}/bidder-feedbacks` | List feedback records for a bid (Subcontractor sees only SENT rows of own bids) | LeadEstimator, ChiefEstimator, Subcontractor |
| POST | `/leveling-adjustments` | Add a leveling adjustment to a SUBMITTED bid | LeadEstimator |
| PATCH | `/leveling-adjustments/{id}` | Edit a leveling adjustment while leveling is unlocked | LeadEstimator |
| DELETE | `/leveling-adjustments/{id}` | Delete a leveling adjustment while leveling is unlocked | LeadEstimator |
| POST | `/post-bid-interviews` | Schedule a post-bid interview | LeadEstimator |
| POST | `/post-bid-interviews/{id}/complete` | Mark an interview held and record outcome notes | LeadEstimator |
| POST | `/award-recommendations` | Draft an award recommendation (OCC via expected package version) | LeadEstimator |
| GET | `/award-recommendations/{id}` | Read an award recommendation | LeadEstimator, ChiefEstimator, PrequalReviewer |
| POST | `/award-recommendations/{id}/submit` | Submit a DRAFT recommendation; package moves to RECOMMENDATION_PENDING | LeadEstimator |
| POST | `/award-recommendations/{id}/decide` | ChiefEstimator decision: APPROVED (award cascade) or RETURNED | ChiefEstimator |
| POST | `/bidder-feedbacks/{id}/send` | Send a DRAFT feedback record to the unsuccessful bidder | LeadEstimator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_BID_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBCONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_PREQUAL_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVITATION_NOT_FOUND` | 404 Not Found |
| `ERR_ADDENDUM_NOT_FOUND` | 404 Not Found |
| `ERR_BID_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_ACKNOWLEDGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_INVALID_STATE` | 409 Conflict |
| `ERR_PACKAGE_NOT_ACCEPTING_BIDS` | 409 Conflict |
| `ERR_INVITATION_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_BID_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_RESOURCE_STATE` | 409 Conflict |
| `ERR_LEVELING_LOCKED` | 409 Conflict |
| `ERR_PREQUAL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVITATION_DECLINED` | 409 Conflict |
| `ERR_DUPLICATE_BID` | 409 Conflict |
| `ERR_DUPLICATE_INVITATION` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE_NUMBER` | 409 Conflict |
| `ERR_ACTIVE_RECOMMENDATION_EXISTS` | 409 Conflict |
| `ERR_INTERVIEW_ROOM_OVERLAP` | 409 Conflict |
| `ERR_NO_INVITED_BIDDERS` | 422 Unprocessable Entity |
| `ERR_BID_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_BID_DEADLINE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_PREQUAL_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_PREQUAL_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_INVITATION_NOT_BIDDING` | 422 Unprocessable Entity |
| `ERR_NO_COMPLIANT_BIDS` | 422 Unprocessable Entity |
| `ERR_RECOMMENDED_BID_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_BID_BOND_INSUFFICIENT` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PACKAGE_VERSION` | 412 Precondition Failed |
