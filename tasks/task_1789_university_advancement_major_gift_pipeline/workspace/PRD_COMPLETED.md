# University Advancement & Major Gift Pipeline API — Product Requirements Document

## 1. Introduction

A university development office runs on a long, carefully governed pipeline: a name surfaces in research, a capacity and affinity rating is attached, the prospect is assigned to a frontline fundraiser's portfolio, cultivated through a disciplined series of moves, asked for a specific amount through a tiered approval process, and finally booked through a gift agreement whose dollars must be receipted, split, counted, stewarded, and recognized. Every hand-off in that pipeline is a control point — the researcher may not approve their own rating, the gift officer may not approve their own ask, the write-off requester may not approve their own write-off — and every dollar is traced from pledge to payment to fund balance to campaign total to donor-recognition standing.

This document specifies the University Advancement & Major Gift Pipeline API, the system of record for that pipeline. It covers prospect research and capacity/affinity rating, portfolio assignment and moves-management stages, proposal and ask-amount approval with tiered quorums, gift-agreement terms including naming opportunities, pledge schedules with reminders and write-offs, restricted-fund establishment with an endowment spending rule and stewardship reporting, campaign counting under two official variants with credit splits, and recognition-society membership. All resources are mounted under the `/advancement` path prefix.

The API is deliberately strict about segregation of duties, optimistic concurrency on the two write paths whose parent mutation invalidates a writer's assumptions, and time-based behavior — reservation expiries, overdue installments, stale approvals, and lapsed stewardship are all driven by a controllable logical clock rather than wall-clock time. Implementers should read §2 for the system-wide contract, §3 for the business workflows in which the rules live, §4 for the endpoint inventory, and §5 for the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. Where §3 narrates a workflow, the statements here still govern it.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or whose `X-User-Role` does not name one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles: `GiftOfficer`, `ProspectResearcher`, `AdvancementDirector`, `VPAdvancement`, `DonorRelationsOfficer`, and `FinanceSteward`. Each endpoint declares which roles may invoke it (see §4); a caller whose role is not listed for that endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

Role identity works differently for the frontline than for everyone else. When `X-User-Role` is `GiftOfficer`, `X-User-ID` is the `id` of the acting `Fundraiser` record; ownership checks on any resource that references a `Fundraiser` compare the resource's foreign-key field to `X-User-ID`, and portfolio-ownership checks resolve the caller's `ACTIVE` assignments by matching `fundraiser_id` against it. When `X-User-Role` is `ProspectResearcher`, `AdvancementDirector`, `VPAdvancement`, `DonorRelationsOfficer`, or `FinanceSteward`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by` on a `ResearchAssessment`, `submitted_by` on a `Proposal` or `StewardshipReport`, `requested_by` on a `PledgeWriteOff`, or `decided_by` on a review) but does not compare it to any entity's `id`. Segregation-of-duties checks, which compare a reviewer's `X-User-ID` to the originator identifier stored on the resource being reviewed, apply across all six roles and yield `ERR_SEGREGATION_OF_DUTIES` when violated.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Every list endpoint accepts both, even where the table in §4 lists additional filters.

Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — fundraisers, prospects, assessments, assignments, proposals, naming opportunities, agreements, funds, pledges, installments, write-offs, payments, campaigns, credit splits, stewardship reports, and recognition societies — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, unique across the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation — with `created_at` and `updated_at` initially equal — and increments by exactly 1 on every mutation, including mutations caused by system-driven sweeps, cascades from another resource, and recomputation of derived counters. No entity in this system is exempt: there are no reduced-property resources.

Because recomputing a derived field (for example, a fundraiser's open-ask counter) is itself a mutation, any such recomputation refreshes `updated_at` and advances `version` on the owning resource. Clients that pin a version for optimistic concurrency (§2.7) must therefore expect versions to advance even when they made no direct write to that resource. Exactly two derived-field updates are exempt from this rule: recomputation of a campaign's `face_value_counted_cents` and `cash_counted_cents` (§3.9) updates the campaign in place without advancing its `version` or `updated_at`, and the lazy recognition-society refresh performed during a recognition read (§3.9) updates the prospect's `recognition_society_id` without advancing the prospect's `version` or `updated_at`.

### 2.5. The Logical Clock and Scheduled Sweeps

All time-dependent behavior in the system — due dates, expiries, grace periods, and fiscal-year boundaries — is evaluated against a **logical clock**, never against wall-clock time. At server startup, before any explicit adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter.

Every timestamp the API emits is rendered in one lexical form: ISO 8601 UTC with exactly three fractional digits and a `Z` suffix (for example, `2026-08-15T00:00:00.000Z`). This holds not only for the `created_at`, `updated_at`, and `api_request_timestamp` system fields of §2.2 and §2.4 but for every domain timestamp — `reserved_until`, `reservation_expires_at`, `approved_at`, `reversed_at`, `received_at`, `first_due_date`, installment and report `due_date`, `period_start` and `period_end`, `counting_start` and `counting_end`, valuation `quarter_end`, and the clock endpoint's `current_utc` echo.

An administrator capability, available to `AdvancementDirector` and `VPAdvancement`, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The target must be strictly later than the current logical time; a target equal to or earlier than the current logical time is rejected with `ERR_INVALID_REQUEST`. Time therefore moves only forward.

Setting the clock is not a passive readjustment: it runs every time-based sweep in the system before responding. Specifically, the sweep (a) flips pledge installments whose due date passed more than 30 days ago to `OVERDUE`; (b) expires `APPROVED` proposals older than 90 days that no gift agreement references; (c) releases naming reservations whose reserved-until instant has been reached; and (d) flips `DRAFT` stewardship reports past their due date to `OVERDUE`, cascading the fund freeze and agreement compliance lapse described in §3.8. Each of these sweeps is detailed with its owning workflow in §3.

### 2.6. Money, Precision, and Rounding

All monetary amounts in the API are integer cents, carried in fields suffixed `_cents`; there are no decimal money fields and no floating-point money arithmetic anywhere in the system. Input money fields must be positive integers unless a rule explicitly permits zero.

Where a calculation produces a fractional cent, the rounding method is pinned per rule and stated with that rule in §3: capacity adjustment and corporate-matching amounts **round down (floor)** to a whole cent, while affinity scores, effective ask amounts, credit-split amounts, and the endowment spending allowance use **round half up** to a whole cent (or, for the affinity score, to a whole integer). Every percentage and multiplier referenced in §3 is exact, and every threshold comparison is inclusive or strict exactly as the relevant rule states.

### 2.7. Optimistic Concurrency Control

Two write operations take an optimistic-concurrency pin on a parent resource, because the write's validity depends on the parent's state as the client last observed it. Both rejections carry HTTP status 412 and the error id `ERR_STALE_VERSION`.

First, creating a proposal requires the request body to carry `expected_prospect_version`, a non-optional field holding the `version` of the target prospect as the client last read it. If the prospect's current `version` differs — because, for instance, a new assessment approval changed the capacity band, or a moves-stage change landed since the client read the record — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the officer from sizing an ask against a rating context they have not observed.

Second, creating a portfolio assignment requires the request body to carry `expected_fundraiser_version`, a non-optional field holding the `version` of the target fundraiser as the client last read it. If another writer has advanced the fundraiser's version since that read — for example by assigning or releasing a prospect, which mutates `current_prospect_count` and `current_open_ask_cents` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so capacity decisions are never made against a stale portfolio snapshot.

No other endpoint takes a version field. Endpoints not named above must not require, and their documented inputs do not include, any `expected_*_version` parameter.

### 2.8. Nested Resource Retrieval

Requests that address a resource through a parent path segment are validated strictly left to right. The system resolves the first path identifier before examining the second: a prospect segment resolves to a prospect before any assessment, assignment, moves, or proposal work beneath it is considered; a fundraiser segment resolves before an assignment beneath it; a proposal segment before an agreement; a pledge segment before an installment or write-off; a fund segment before a stewardship report. The request is rejected with the 404 error corresponding to the first identifier that does not resolve.

The not-found errors are resource-specific: `ERR_PROSPECT_NOT_FOUND` for an unresolvable prospect segment or a `prospect_id` body reference, `ERR_FUNDRAISER_NOT_FOUND` for a fundraiser segment, `ERR_PROPOSAL_NOT_FOUND` for a proposal segment, `ERR_AGREEMENT_NOT_FOUND` for an agreement segment or an `agreement_id` body reference, `ERR_PLEDGE_NOT_FOUND` for a pledge segment or a `pledge_id` body reference, `ERR_PAYMENT_NOT_FOUND` for a payment segment, `ERR_FUND_NOT_FOUND` for a fund segment or a `fund_id` body reference, and `ERR_CAMPAIGN_NOT_FOUND` for a campaign segment or a `campaign_id` body reference. All other addressable resources — assessments, assignments, installments, write-offs, stewardship reports, naming opportunities, and recognition societies — report `ERR_RESOURCE_NOT_FOUND` when their identifier does not resolve.

### 2.9. Parallel Status Dimensions, Open Proposals, and Hierarchical Consistency

Two entities carry **two independent status dimensions** that evolve in parallel. A prospect has a `research_status` (the research pipeline: `IDENTIFIED`, `IN_SCREENING`, `RATED`, `DISQUALIFIED`) and a `moves_stage` (the cultivation pipeline: `QUALIFICATION`, `CULTIVATION`, `SOLICITATION`, `NEGOTIATION`, `STEWARDSHIP`, `CLOSED_LOST`); neither dimension implies the other, and rules in §3 address each separately. A gift agreement has a `signature_status` (`DRAFT`, `PENDING_SIGNATURE`, `EXECUTED`, `RESCINDED`) and a `compliance_status` (`COMPLIANT`, `STEWARDSHIP_LAPSED`); stewardship lapses freeze spending without touching the signature dimension.

A fundraiser's exposure to open solicitations is measured over a fixed set of proposal states. The **open proposal states** are exactly `UNDER_REVIEW`, `NEGOTIATING`, and `APPROVED`; `DRAFT`, `RETURNED`, `REJECTED`, `SUPERSEDED`, and `EXPIRED` proposals do not count. A fundraiser's `current_open_ask_cents` is the sum of `ask_amount_cents` over proposals in the open proposal states whose prospect currently has an `ACTIVE` assignment to that fundraiser, and `current_prospect_count` is the number of `ACTIVE` assignments the fundraiser holds. Both counters are recomputed by the system whenever the underlying set changes — assignment creation or release, proposal submission, rejection, supersession, expiry, edit, or prospect disqualification — and every such recomputation advances the fundraiser's `version`.

The system maintains consistency across the graph automatically: superseding a rival rating or proposal, releasing assignments on disqualification, canceling a pledge on rescission, and freezing a fund on an overdue report all happen as side effects of the triggering operation, without a separate client request on the affected resource, and each touched resource advances its own `version` and `updated_at`.

### 2.10. Validation Priority Order

Every request is validated against an ordered chain of checks, and **the first failing check wins**: once an earlier check fires, later checks are not evaluated, so the returned error is always the highest-priority failure present. The chain, from first to last, is:

1. **Authentication.** Both headers are present and `X-User-Role` names a declared role; otherwise `ERR_UNAUTHENTICATED`.
2. **Role authorization.** The acting role is listed for the endpoint; otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Request shape.** The body is well-formed: required fields present, types correct, enum values within their declared sets, integer money fields positive, unknown fields rejected, and split structures well-formed; otherwise `ERR_INVALID_REQUEST`. On endpoints that declare no request-body fields, a supplied body is accepted and ignored rather than rejected for unknown fields.
4. **Path and reference existence.** Identifiers resolve left to right per §2.8; otherwise the corresponding 404.
5. **Portfolio ownership.** Where the acting `GiftOfficer` must own the prospect, `X-User-ID` must equal the `fundraiser_id` of an `ACTIVE` assignment for that prospect; otherwise `ERR_NOT_PROSPECT_OWNER`. This check guards exactly eight operations: recording a move, creating a proposal, submitting a proposal, editing a proposal, drafting an agreement from a proposal, presenting an agreement, creating a pledge, and requesting a write-off.
6. **Segregation of duties.** The reviewer or decider differs from the resource's originator; otherwise `ERR_SEGREGATION_OF_DUTIES` (or `ERR_DUPLICATE_APPROVAL` for a repeat principal-tier approver).
7. **Optimistic concurrency.** A supplied expected-version field equals the parent's current `version`; otherwise `ERR_STALE_VERSION`.
8. **Entity state preconditions.** The target entity is in a state that permits the operation per its state machine (proposal editable or submittable or under review, agreement presentable or executable, pledge active, installment remindable, write-off pending, payment not reversed, campaign in the required phase, fundraiser active, assessment submitted, report draft or submitted, moves transition legal); otherwise the state-specific 409 listed with the rule in §3.
9. **Stewardship gates on money movement.** A payment may not credit a `SPENDING_FROZEN` fund (`ERR_STEWARDSHIP_LAPSED`) and a disbursement may not leave a `SPENDING_FROZEN` fund (`ERR_FUND_SPENDING_FROZEN`); these two gates apply to payment recording and fund disbursement respectively.
10. **Cross-reference consistency.** A payment carrying both a pledge and a fund reference must name the fund the pledge actually pays into; otherwise `ERR_FUND_PLEDGE_MISMATCH`.
11. **Capacity, tier, floor, and uniqueness constraints.** Portfolio count and open-ask ceilings, tier-role mapping, naming availability and price floor, agreement-amount equality, pledge-per-agreement uniqueness, society-level uniqueness, quarter-valuation uniqueness, and the one-active-assignment-per-prospect rule.
12. **Temporal windows.** These guards apply to four operations: agreement execution (the naming reservation must not have expired), stewardship report creation (periods must not overlap), payment recording, and pledge creation (the campaign counting window must contain the booked item).
13. **Fiscal limits.** Amounts against outstanding balances, split percentages summing to one hundred, and disbursements within the spending allowance.

## 3. Business Logic & Workflows

### 3.1. Staffing the Pipeline: Fundraisers and Portfolio Assignments

Before any prospect can be worked, the office staffs its frontline. A `VPAdvancement` creates each **fundraiser** with a `display_name`, a work `email`, and two portfolio capacity limits: `max_prospect_count`, the maximum number of simultaneously active portfolio assignments, and `max_open_ask_cents`, the maximum aggregate ask amount the fundraiser may carry across open solicitations. Both limits are positive integers. A new fundraiser starts with `status` `ACTIVE`, `current_prospect_count` at zero, and `current_open_ask_cents` at zero; the two counters are computed by the system thereafter and are never set directly.

Portfolio assignment is a director's decision with a concurrency guard. An `AdvancementDirector` assigns a prospect to a fundraiser by posting the `prospect_id` together with `expected_fundraiser_version` (see §2.7). Creation is refused when the fundraiser is not `ACTIVE` (`ERR_FUNDRAISER_INACTIVE`), when the prospect already has an `ACTIVE` assignment to any fundraiser (`ERR_PROSPECT_ALREADY_ASSIGNED`), when the fundraiser's `current_prospect_count` has already reached `max_prospect_count` — that is, when the count is greater than or equal to the maximum (`ERR_PORTFOLIO_CAPACITY_EXCEEDED`) — and when adding the prospect's open proposals would push `current_open_ask_cents` above `max_open_ask_cents` (`ERR_OPEN_ASK_LOAD_EXCEEDED`). A successful assignment is created `ACTIVE`, increments the fundraiser's `current_prospect_count` by one, folds the prospect's open proposals into `current_open_ask_cents`, and advances the fundraiser's `version` by 1.

An `AdvancementDirector` may later release an `ACTIVE` assignment, supplying a `released_reason` of `GRADUATED`, `REBALANCING`, or `DISQUALIFIED`; the assignment becomes `RELEASED` (releasing one that is not `ACTIVE` is rejected with `ERR_INVALID_MOVES_TRANSITION`). Release decrements `current_prospect_count`, recomputes `current_open_ask_cents` to subtract the released prospect's open proposals, and advances the fundraiser's `version`. Assignments of a fundraiser can be listed with an optional `status` filter, and a prospect's assignment history is likewise retrievable through the prospect with an optional `status` filter.

A `VPAdvancement` may deactivate a fundraiser whose book is empty. Deactivation requires `status` `ACTIVE` (otherwise `ERR_INVALID_MOVES_TRANSITION`) and a `current_prospect_count` of exactly zero; attempting it while any assignment is still `ACTIVE` fails with `ERR_FUNDRAISER_HAS_ACTIVE_ASSIGNMENTS`. A deactivated fundraiser's `status` becomes `INACTIVE` and its `version` advances by 1. Deactivation is one-way in this system: no transition returns a fundraiser to `ACTIVE`.

### 3.2. Prospect Intake, Research, and Rating

Everything begins with a name. A `ProspectResearcher` creates a **prospect** with a `full_name`, a `prospect_type` of `INDIVIDUAL` or `ORGANIZATION`, and a `contact_email`; an optional `spouse_prospect_id` links the record to another prospect for household soft-credit suggestions — a supplied `spouse_prospect_id` that does not resolve to an existing prospect is rejected with `ERR_PROSPECT_NOT_FOUND`. A new prospect enters with `research_status` `IDENTIFIED` and `moves_stage` `QUALIFICATION` — the two parallel dimensions of §2.9 — with `capacity_band`, `affinity_score`, `rated_assessment_id`, and `rated_adjusted_capacity_cents` all null until the first approved rating, and with `lifetime_given_cents`, `outstanding_pledge_cents`, and `recognition_society_id` initialized to zero, zero, and null respectively. The prospect directory can be listed with filters on `research_status`, `moves_stage`, `capacity_band`, `spouse_prospect_id`, `rated_assessment_id`, and `recognition_society_id`.

Research proceeds through **assessments**. A `ProspectResearcher` files an assessment against a prospect with `assessed_capacity_cents` (a positive integer estimating raw giving capacity), three indicator scores — `engagement_score`, `philanthropy_score`, and `recency_score`, each an integer from 0 to 100 — and an `evidence_tier` of `SELF_REPORTED`, `PUBLIC_RECORD`, or `VERIFIED_DOCUMENT`. The assessment is born `SUBMITTED`, records the filer's `X-User-ID` as `created_by`, and its `prospect_id` ties it to the subject. Filing the first assessment moves the prospect from `IDENTIFIED` to `IN_SCREENING`; filing one against a `RATED` prospect re-opens screening (`RATED` back to `IN_SCREENING`), and in that cyclic case the prospect's existing `capacity_band`, `affinity_score`, `rated_assessment_id`, and `rated_adjusted_capacity_cents` remain in force from the prior rating until a new approval replaces them. Either filing advances the prospect's `version` by 1, as does a filing against a prospect already `IN_SCREENING`, which changes no status. Attempting to file an assessment against a `DISQUALIFIED` prospect is rejected with `ERR_INVALID_MOVES_TRANSITION`.

Only a director converts research into a rating. An `AdvancementDirector` reviews a `SUBMITTED` assessment with a `decision` of `APPROVE` or `REJECT` and an optional `review_rationale`; the reviewer is recorded as `reviewed_by`. Two guards precede every review: the assessment must still be `SUBMITTED` (otherwise `ERR_ASSESSMENT_NOT_REVIEWABLE`), and the reviewer's `X-User-ID` must differ from the assessment's `created_by` (otherwise `ERR_SEGREGATION_OF_DUTIES`).

Approval runs the **capacity and affinity rating**. The raw `assessed_capacity_cents` is multiplied by the evidence multiplier for the assessment's `evidence_tier` — 0.6 for `SELF_REPORTED`, 0.8 for `PUBLIC_RECORD`, and 1.0 for `VERIFIED_DOCUMENT` — and the product is rounded down to a whole cent to yield `adjusted_capacity_cents`. The capacity band follows from the adjusted amount using inclusive lower bounds: band `A` when the adjusted capacity is at least $10,000,000 (1000000000 cents), otherwise band `B` when at least $1,000,000 (100000000 cents), otherwise band `C` when at least $250,000 (25000000 cents), otherwise band `D` when at least $50,000 (5000000 cents), and otherwise band `E`. The affinity score is a weighted blend — half of `engagement_score`, three-tenths of `philanthropy_score`, and one-fifth of `recency_score`, summed and rounded half up to a whole integer between 0 and 100 — recorded as `affinity_score_result`. These three results land on the assessment as `adjusted_capacity_cents`, `capacity_band_result`, and `affinity_score_result`, and are copied onto the prospect: the prospect's `research_status` becomes `RATED`, `capacity_band` takes the resulting band, `affinity_score` the resulting affinity, `rated_assessment_id` the approved assessment's `id`, and `rated_adjusted_capacity_cents` the adjusted capacity — this last figure later serves as the ask ceiling at proposal submit time (§3.4). Approval also supersedes the prior rating: any other assessment of the same prospect still in `APPROVED` status moves to `SUPERSEDED`. The prospect's `version` advances by 1. If the assessment's prospect is `DISQUALIFIED` at approval time, the assessment still becomes `APPROVED` with its three results recorded, but the prospect is left untouched: it remains `DISQUALIFIED`, keeps its prior rating fields, and no supersession of its other assessments runs. Rejection, by contrast, touches nothing on the prospect: the assessment becomes `REJECTED`, the prospect remains `IN_SCREENING`, and a rejected rating never updates any prospect field.

A prospect's file also accumulates giving aggregates that later workflows depend on: `lifetime_given_cents`, the sum of `amount_cents` over the prospect's non-reversed gift payments as hard-credit donor; `outstanding_pledge_cents`, the sum of `outstanding_cents` over the prospect's `ACTIVE` pledges; and `recognition_society_id`, the highest recognition level the prospect's cash total currently qualifies for, or null when below every level (§3.9).

Disqualification is the research pipeline's terminal exit and is deliberately destructive downstream. A `ProspectResearcher` or `AdvancementDirector` may disqualify any prospect whose `research_status` is not already `DISQUALIFIED` (otherwise `ERR_INVALID_MOVES_TRANSITION`). Disqualification sets `research_status` to `DISQUALIFIED` while leaving `moves_stage` unchanged, and then cascades: every `ACTIVE` assignment of the prospect is released with `released_reason` `DISQUALIFIED`, decrementing each owning fundraiser's `current_prospect_count`; and every proposal of the prospect in `DRAFT`, `UNDER_REVIEW`, `NEGOTIATING`, or `RETURNED` status is rejected with `decision_rationale` set to `PROSPECT_DISQUALIFIED`, with the owning fundraisers' `current_open_ask_cents` recomputed. The prospect's `version` advances by 1, and each touched fundraiser's `version` advances per §2.9.

### 3.3. Moves Management and the Cultivation Cycle

The moves pipeline tracks where a prospect stands in the relationship, and it belongs to the assigned officer. Every move is performed by a `GiftOfficer` who must hold an `ACTIVE` assignment for the prospect — `X-User-ID` equal to the assignment's `fundraiser_id` — or the request fails with `ERR_NOT_PROSPECT_OWNER`. The officer supplies a `target_stage` and may attach an optional `note`. Each successful move advances the prospect's `version` by 1.

Forward progress is gated. From `QUALIFICATION`, an officer may open `CULTIVATION` provided the prospect is not `DISQUALIFIED` (a disqualified prospect rejects any such move with `ERR_INVALID_MOVES_TRANSITION`). From `CULTIVATION`, entering `SOLICITATION` requires the prospect's `research_status` to be `RATED` — an unrated prospect is not yet askable, and the attempt fails with `ERR_PROSPECT_NOT_RATED`. From `SOLICITATION`, entering `NEGOTIATION` requires that the prospect already have a proposal in `APPROVED` status; without one the move is rejected with `ERR_INVALID_MOVES_TRANSITION`.

The pipeline is deliberately cyclic. From any of `SOLICITATION`, `NEGOTIATION`, or `STEWARDSHIP`, an officer may pull the prospect back to `CULTIVATION` — the recultivation loop — and from `CULTIVATION` back to `QUALIFICATION`; any other stage pairing is an illegal jump and draws `ERR_INVALID_MOVES_TRANSITION`. One stage is system-reserved: `STEWARDSHIP` is reached only as a side effect of executing a gift agreement (§3.5) from `CULTIVATION`, `SOLICITATION`, or `NEGOTIATION`, and a direct API move naming `STEWARDSHIP` as the target is rejected with `ERR_INVALID_MOVES_TRANSITION`. Finally, from any stage other than `CLOSED_LOST` an officer may close the book by moving the prospect to `CLOSED_LOST`; a prospect already in `CLOSED_LOST` rejects further moves with `ERR_INVALID_MOVES_TRANSITION`. `CLOSED_LOST` and `DISQUALIFIED` are the terminal states of their respective dimensions.

### 3.4. Proposals: Ask Sizing, Approval Tiers, and Quorums

The proposal is the office's formal ask, created by the owning officer under a concurrency pin. A `GiftOfficer` holding the prospect's `ACTIVE` assignment (otherwise `ERR_NOT_PROSPECT_OWNER`) creates a proposal with the `prospect_id`, a `proposal_type` of `OUTRIGHT`, `PLEDGE`, or `PLANNED`, a positive integer `ask_amount_cents`, a free-text `designation_purpose`, and the required `expected_prospect_version` pin of §2.7. Creation is gated on the prospect's readiness: `research_status` must be `RATED` (otherwise `ERR_PROSPECT_NOT_RATED`) and `moves_stage` must be one of `CULTIVATION`, `SOLICITATION`, or `NEGOTIATION` (otherwise `ERR_PROSPECT_NOT_SOLICITABLE`); a `DISQUALIFIED` prospect satisfies neither gate. A new proposal starts as `DRAFT`, and its creation advances the prospect's `version` by 1. Proposals of a prospect can be listed through the prospect with an optional `status` filter.

While a proposal is in `DRAFT`, `NEGOTIATING`, `RETURNED`, or `REJECTED`, the owning officer may edit `ask_amount_cents` or `designation_purpose`; the edit resets the proposal to `DRAFT` and clears the review machinery — `approval_tier`, `effective_ask_cents`, and `pinned_capacity_band` return to null, `approvals_received` returns to zero, and `approver_ids` empties — so every renegotiated ask faces a fresh review round. Editing from any other state, including `UNDER_REVIEW`, `APPROVED`, `SUPERSEDED`, or `EXPIRED`, is rejected with `ERR_PROPOSAL_STATE_FORBIDS`. If the proposal had been in one of the open proposal states before the edit, the owning fundraiser's `current_open_ask_cents` is recomputed and the fundraiser's `version` advances.

Submitting a proposal converts a draft number into a governed ask. The owning officer may submit from `DRAFT`, `RETURNED`, `REJECTED`, or `NEGOTIATING` (from any other state, `ERR_PROPOSAL_STATE_FORBIDS`). Submission enforces two ceilings in business terms. First, the ask may not exceed the prospect's rated capacity: `ask_amount_cents` greater than the prospect's `rated_adjusted_capacity_cents` is rejected with `ERR_ASK_EXCEEDS_CAPACITY`. Second, the fundraiser's open-ask load may not exceed its ceiling: the fundraiser's `current_open_ask_cents` plus this proposal's `ask_amount_cents` must be no more than `max_open_ask_cents` — equality is allowed — otherwise the submission fails with `ERR_OPEN_ASK_LOAD_EXCEEDED`. A successful submission runs the tier determination below, pins the prospect's current `capacity_band` onto the proposal as `pinned_capacity_band`, records the caller as `submitted_by`, resets `approvals_received` to zero, `approver_ids` to empty, and `decided_by` to null, and moves the proposal to `UNDER_REVIEW`; because `UNDER_REVIEW` is an open proposal state, the owning fundraiser's `current_open_ask_cents` is recomputed and the fundraiser's `version` advances.

The **approval tier** is computed from four inputs at submit time. The proposal's `effective_ask_cents` is the `ask_amount_cents` multiplied by the type multiplier — 1.0 for `OUTRIGHT`, 1.0 for `PLEDGE`, and 0.5 for `PLANNED` — rounded half up to a whole cent; planned gifts therefore count at half their face value for tiering. The base tier follows from the effective ask with the stated boundaries: `STANDARD` when the effective ask is less than $250,000 (25000000 cents), `MAJOR` when it is at least $250,000 but less than $1,000,000 (100000000 cents), and `PRINCIPAL` when it is at least $1,000,000. A trusted-capacity shift then applies: when the prospect's `prospect_type` is `INDIVIDUAL` and the pinned capacity band is `A`, the tier shifts one step down — `PRINCIPAL` becomes `MAJOR`, `MAJOR` becomes `STANDARD`, and `STANDARD` stays `STANDARD` — reflecting the office's confidence in its best-understood donors; `ORGANIZATION` prospects never shift. The resulting `approval_tier` and `effective_ask_cents` are stored on the proposal, and the tier fixes the approval requirement: a `STANDARD` proposal needs exactly one `AdvancementDirector` approval, a `MAJOR` proposal exactly one `VPAdvancement` approval, and a `PRINCIPAL` proposal a quorum of two distinct `VPAdvancement` approvals.

Review is a decision endpoint guarded by the tier. A reviewer — `AdvancementDirector` or `VPAdvancement`, matching the tier's requirement or the request fails with `ERR_TIER_APPROVAL_ROLE_VIOLATION` — acts on a proposal in `UNDER_REVIEW` (otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`) with a `decision` and an optional `decision_rationale`. The reviewer must differ from `submitted_by` (otherwise `ERR_SEGREGATION_OF_DUTIES`), and each approval is recorded: `approvals_received` increments and the reviewer's `X-User-ID` joins `approver_ids`, so a `VPAdvancement` who has already approved the current round cannot approve it again (`ERR_DUPLICATE_APPROVAL`). Four decisions exist. `NEGOTIATE` moves the proposal to `NEGOTIATING` and captures the rationale. `RETURN` moves it to `RETURNED`, likewise capturing the rationale. `REJECT` moves it to `REJECTED`, records the reviewer as `decided_by`, and — because a rejected proposal leaves the open proposal states — recomputes the owning fundraiser's `current_open_ask_cents` and advances the fundraiser's `version`. `APPROVE` applies the quorum: for `STANDARD` and `MAJOR` a single approval decides; for `PRINCIPAL` the first approval merely leaves the proposal `UNDER_REVIEW` with `approvals_received` at 1, and only the second distinct `VPAdvancement` approval completes it. On the final approval the proposal becomes `APPROVED`, `decided_by` records the deciding reviewer, and `approved_at` is stamped from the logical clock; approval is exclusive per prospect, so any other proposal of the same prospect currently `APPROVED` moves to `SUPERSEDED`, and that supersession — like the later expiry — removes the proposal from the open proposal states and recomputes the owning fundraiser's `current_open_ask_cents`. An approval itself does not change `current_open_ask_cents`, because `APPROVED` remains an open proposal state.

Approved asks are perishable. When the logical clock advances past `approved_at` plus 90 days and no gift agreement references the proposal, the clock sweep moves the proposal from `APPROVED` to `EXPIRED`, recomputing the owning fundraiser's open-ask load and advancing its `version`. `SUPERSEDED` and `EXPIRED` are the proposal's terminal states. The loop from `UNDER_REVIEW` through `NEGOTIATING`, `RETURNED`, or `REJECTED`, back to `DRAFT` by edit, and forward to `UNDER_REVIEW` again is the sanctioned negotiation cycle.

### 3.5. Gift Agreements and Naming Opportunities

An approved ask becomes a legal instrument through the **gift agreement**. The owning `GiftOfficer` drafts an agreement from a proposal that is `APPROVED` — a proposal in any other state, including `EXPIRED` and `SUPERSEDED`, fails with `ERR_PROPOSAL_NOT_APPROVED`. The drafting payload carries a `restriction_type` of `UNRESTRICTED`, `RESTRICTED_CURRENT_USE`, or `ENDOWED`; a positive integer `agreement_amount_cents` that must equal the approved proposal's `ask_amount_cents` exactly (any difference is rejected with `ERR_AGREEMENT_AMOUNT_MISMATCH`); an optional `purpose_code` that becomes **required** whenever the `restriction_type` is anything other than `UNRESTRICTED` (a missing `purpose_code` on a restricted agreement is a malformed request, `ERR_INVALID_REQUEST`); and an optional `naming_opportunity_id` staking a claim on a named space or fund. The price floor is enforced at draft time: when a naming claim is present, `agreement_amount_cents` below the opportunity's `price_floor_cents` is rejected with `ERR_BELOW_NAMING_FLOOR`. A new agreement enters with `signature_status` `DRAFT` and `compliance_status` `COMPLIANT`, its `prospect_id` copied from the proposal. Agreements can be listed with filters on `proposal_id`, `prospect_id`, `naming_opportunity_id`, and `signature_status`.

The naming inventory is managed centrally. A `VPAdvancement` creates each **naming opportunity** with a `name`, a `category` of `BUILDING`, `ENDOWED_CHAIR`, `SCHOLARSHIP`, or `PROGRAM`, and a positive integer `price_floor_cents`; it starts `AVAILABLE`. Presenting an agreement — an action of the owning `GiftOfficer` — moves the agreement from `DRAFT` to `PENDING_SIGNATURE` (any other signature state is rejected with `ERR_AGREEMENT_INVALID_STATE`), and when the agreement claims a naming opportunity, presentation is also the moment of reservation: the opportunity must be `AVAILABLE` (otherwise `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`), and on success it becomes `RESERVED` with `reserved_by_agreement_id` set to the agreement and `reserved_until` set to the current logical time plus 14 days. The hold is **half-open**: it covers the interval from the presentation instant up to but not including `reserved_until`, so the reservation is free again at exactly `reserved_until`. The agreement mirrors that instant in its own `reservation_expires_at`, and the opportunity's `version` advances by 1. The reservations attached to an agreement — at most one — can be read back through the agreement's naming-reservations listing.

Execution is a vice-presidential act with a temporal guard. A `VPAdvancement` executes an agreement in `PENDING_SIGNATURE` (otherwise `ERR_AGREEMENT_INVALID_STATE`). When a naming claim is attached, three checks apply: the opportunity must still be `RESERVED`, the reservation must be held by this very agreement, and the current logical time must still be earlier than `reservation_expires_at`; a lapsed window fails with `ERR_RESERVATION_EXPIRED`, while an opportunity `RESERVED` by another agreement, `OCCUPIED`, or `RETIRED` fails with `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`. Execution sets `signature_status` to `EXECUTED` and then performs its three establishment effects: a claimed opportunity becomes `OCCUPIED` (its `reserved_until` is kept for audit, and its `version` advances); for `RESTRICTED_CURRENT_USE` or `ENDOWED` agreements the system establishes a **restricted fund** carrying the `agreement_id`, the agreement's `purpose_code`, an `is_endowed` flag true exactly when the agreement is `ENDOWED`, a `balance_cents` of zero, a `minimum_activation_cents` of $25,000 (2500000 cents) copied from the system constant at establishment, an empty `trailing_market_values` list, and `status` `PENDING_MINIMUM`; and the prospect's `moves_stage` moves to `STEWARDSHIP` from `CULTIVATION`, `SOLICITATION`, or `NEGOTIATION` — the only path into that stage — with the prospect's `version` advancing by 1; a prospect in any other stage at execution time keeps its current stage and version.

Rescission unwinds an agreement that money has not yet touched. A `VPAdvancement` may rescind from `DRAFT`, `PENDING_SIGNATURE`, or `EXECUTED` (an already `RESCINDED` agreement rejects with `ERR_AGREEMENT_INVALID_STATE`), but only while no non-reversed gift payment references the agreement's pledge or its fund — otherwise `ERR_RESCIND_BLOCKED_BY_PAYMENTS`. Rescission sets `signature_status` to `RESCINDED` and cascades: a naming opportunity `RESERVED` or `OCCUPIED` by this agreement returns to `AVAILABLE` with `reserved_by_agreement_id` and `reserved_until` cleared and its `version` advanced; the agreement's pledge, if any, is cancelled per §3.6; and the established restricted fund, if any, closes to `CLOSED`. Independently of rescission, the clock sweep releases any `RESERVED` opportunity whose `reserved_until` instant has been reached, clearing both reservation fields.

Retirement removes inventory from circulation. A `VPAdvancement` may retire an opportunity that is `AVAILABLE` or `RESERVED`; attempting it on an `OCCUPIED` or already `RETIRED` opportunity fails with `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`. When a `RESERVED` opportunity is retired, the holding agreement keeps its `signature_status` but loses its claim: retirement sets the opportunity's `status` to `RETIRED` while leaving `reserved_by_agreement_id` and `reserved_until` in place (contrast rescission and the clock sweep above, which clear both reservation fields), and a later execution attempt then fails with `ERR_NAMING_OPPORTUNITY_UNAVAILABLE`, since the opportunity is no longer held for it. `RETIRED` is the opportunity's terminal state.

### 3.6. Pledges, Installments, and Write-Offs

A pledge books a promised stream of payments against an executed pledge-type agreement. The owning `GiftOfficer` creates a pledge with the `agreement_id`, a positive integer `total_amount_cents`, an `installment_count` between 1 and 120 inclusive, a `frequency` of `MONTHLY`, `QUARTERLY`, or `ANNUAL`, a `first_due_date` for installment 1, and an optional `campaign_id` booking. The agreement must be `EXECUTED` (otherwise `ERR_AGREEMENT_INVALID_STATE`) and its proposal must be of type `PLEDGE` (otherwise `ERR_PLEDGE_TYPE_REQUIRED`); one agreement supports exactly one pledge, so a second attempt on the same agreement fails with `ERR_PLEDGE_ALREADY_EXISTS`. When `campaign_id` is present, the campaign must be `ACTIVE` (otherwise `ERR_CAMPAIGN_INVALID_STATE`) and the booking moment must fall inside the campaign's inclusive counting window (otherwise `ERR_OUTSIDE_COUNTING_WINDOW`). Creation copies `prospect_id` from the agreement and `fund_id` from the agreement's established fund — null for an `UNRESTRICTED` agreement — sets `written_off_cents` to zero, and marks the pledge `ACTIVE`.

The **installment schedule** is generated at creation with the remainder front-loaded. The base installment amount is the `total_amount_cents` divided by the `installment_count`, rounded down to a whole cent; the remainder — the total minus the base times the count — is distributed one extra cent to each of the earliest-due installments, so installment 1 absorbs first and no later installment ever exceeds an earlier one by more than the schedule's design. Each row records its `pledge_id`, a 1-based `sequence_number`, its `amount_cents`, and a `due_date` computed by advancing `first_due_date` by one `frequency` step per preceding installment — one calendar month for `MONTHLY`, three for `QUARTERLY`, one year for `ANNUAL` — with the day of month clamped to the last day of the target month, so a January 31 start with monthly frequency lands on February 28 or 29. Every installment starts `SCHEDULED` with `paid_cents` and `written_off_cents` at zero and `reminder_count` at zero, and the pledge's `outstanding_cents` — the sum over installments of each installment's `amount_cents` minus its `paid_cents` minus its `written_off_cents` — equals `total_amount_cents` at creation. Creation also recomputes the prospect's `outstanding_pledge_cents` with a prospect `version` bump, and a campaign-booked pledge immediately enters the campaign's face-value total per §3.9. Pledges are listable with `agreement_id`, `fund_id`, `campaign_id`, `prospect_id`, and `status` filters, and a pledge's installments are listable in schedule order with an optional `status` filter.

Collections work is reminder-driven but capped. A `DonorRelationsOfficer` may send a reminder for an installment in `SCHEDULED`, `REMINDED`, or `OVERDUE` status — a `PAID` or `WRITTEN_OFF` installment rejects with `ERR_INSTALLMENT_NOT_REMINDABLE` — provided `reminder_count` is still below the system maximum of 3; a third reminder already sent means the next attempt fails with `ERR_REMINDER_LIMIT_EXCEEDED`. Each reminder increments `reminder_count` by 1, sets the installment to `REMINDED`, and advances its `version`. Independently, the clock sweep moves a `SCHEDULED` or `REMINDED` installment to `OVERDUE` once the current logical time is strictly later than the installment's `due_date` plus 30 days; an installment exactly 30 days past due is not yet overdue.

When collection fails, the office writes balances off through a two-person control. A `GiftOfficer` (owning the prospect) or a `FinanceSteward` requests a write-off on an `ACTIVE` pledge (otherwise `ERR_PLEDGE_NOT_ACTIVE`) with a positive `amount_cents` and a `reason` of `UNCOLLECTIBLE`, `DONOR_HARDSHIP`, `DUPLICATE`, or `OTHER`; the amount must not exceed the pledge's `outstanding_cents` at request time (`ERR_WRITE_OFF_EXCEEDS_OUTSTANDING`). The request is born `PENDING` with `requested_by` recording the caller, and is reviewable by an `AdvancementDirector` — who must differ from `requested_by` (otherwise `ERR_SEGREGATION_OF_DUTIES`) — through a `decision` with an optional `review_rationale`; a write-off no longer `PENDING` rejects review with `ERR_WRITE_OFF_NOT_PENDING`. Rejection simply closes the request as `REJECTED` with `decided_by` recorded.

Approval allocates the written amount **latest-first**: installments with an open balance are visited from the latest due date to the earliest — ties broken by descending `sequence_number` — and each receives the smaller of the remaining write-off amount and its open balance, added to its `written_off_cents`. An installment thereby fully covered with `paid_cents` still zero becomes `WRITTEN_OFF`; partial coverage simply raises `written_off_cents`; and an installment that becomes fully covered while holding `paid_cents` above zero is treated as settled and becomes `PAID`. The pledge's `written_off_cents` grows by the approved amount, `outstanding_cents` is recomputed, and the pledge's status is re-evaluated. Approval also nets the written amount out of the booking campaign's face-value total (§3.9) and recomputes the prospect's outstanding balance and recognition standing. A write-off's requests are listable per pledge with an optional `status` filter.

The pledge's own status re-evaluates after every payment allocation, reversal, approved write-off, and rescission: it becomes `FULFILLED` when every installment is `PAID` with the pledge's `written_off_cents` at zero; it becomes `WRITTEN_OFF` when no installment remains in `SCHEDULED`, `REMINDED`, or `OVERDUE` and at least one installment carries a positive `written_off_cents`; and it becomes `CANCELLED` when its establishing agreement is rescinded, which nets the unwritten remaining balance out of the booking campaign's face-value total. Each terminal transition recomputes the prospect's `outstanding_pledge_cents` — and, for write-offs, the recognition totals — and advances the pledge's and prospect's `version`.

### 3.7. Recording Gifts: Payments, Splits, and Reversals

Money enters the system exclusively through the `FinanceSteward`. Recording a payment takes the hard-credit `donor_prospect_id`, a positive integer `amount_cents`, the `received_at` timestamp that drives campaign-window tests, a `payment_method` of `CHECK`, `WIRE`, `CARD`, or `STOCK`, and four optional modifiers: `pledge_id` to apply the payment to a pledge's installments, `fund_id` for a direct fund gift or to name the pledge's fund explicitly, `campaign_id` to count the payment toward a campaign, `corporate_matched` (default false) to flag employer matching, and `splits` to apportion credit. The guards fire in the order of §2.10: a linked pledge must be `ACTIVE` (`ERR_PLEDGE_NOT_ACTIVE`) and the payment's `amount_cents` must not exceed the pledge's `outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`); when both `pledge_id` and `fund_id` are present, the `fund_id` must equal the pledge's own `fund_id` — both being null is allowed — else `ERR_FUND_PLEDGE_MISMATCH`; the fund a payment would credit is the pledge's fund for a pledge-linked payment and the payload's `fund_id` otherwise, and it is this credited fund — not merely any fund the payload names — that the fund-state gates examine: a payment whose credited fund is `SPENDING_FROZEN` is refused with `ERR_STEWARDSHIP_LAPSED`, and one whose credited fund is `CLOSED` with `ERR_FUND_NOT_ACTIVE`; a campaign reference requires the campaign `ACTIVE` (`ERR_CAMPAIGN_INVALID_STATE`) with `received_at` inside the inclusive window from `counting_start` to `counting_end` (`ERR_OUTSIDE_COUNTING_WINDOW`). The recorded payment's `fund_id` is the credited fund's `id` — a pledge-linked payment therefore records the pledge's fund even when the payload omitted `fund_id` — and is null when no fund is credited.

When `splits` is present, it is a list of entries each naming a `prospect_id`, a `credit_type` of `HARD` or `SOFT`, and an integer `split_pct` between 1 and 100. Exactly one split must be `HARD` and it must name the `donor_prospect_id`, and the percentages must sum to exactly 100; any deviation — a missing or duplicated hard split, a percentage outside 1 to 100, or a sum other than 100 — is rejected with `ERR_SPLIT_PERCENT_SUM_INVALID`, while a structurally malformed splits value is `ERR_INVALID_REQUEST`. The credited amounts are computed with a pinned rounding order: the splits are sorted by ascending `split_pct`, ties broken by their position in the request array (first listed counts as smaller); every split except the last in that order — the largest — is credited the payment's `amount_cents` multiplied by its percentage and divided by 100, rounded half up to a whole cent; and the largest split absorbs the residual, receiving the payment amount minus the sum of the rounded amounts, so the parts always total the payment exactly. A `CampaignCreditSplit` row is created for every split, recording the `gift_payment_id`, the credited `prospect_id`, the `credit_type`, the `split_pct`, and the computed `amount_cents`; its `campaign_id` equals the payment's campaign when one is present and is null otherwise. Only the `HARD` split's amount enters campaign counting (§3.9); `SOFT` splits surface only in the comprehensive recognition projection. Splits are retrievable per payment or per prospect with an optional `credit_type` filter, and per campaign as well.

A pledge-linked payment applies its amount as a **waterfall, earliest obligation first**: installments with an open balance are visited in ascending `due_date`, ties broken by ascending `sequence_number`, and each receives the smaller of the payment's remaining amount and its open balance. The resulting per-installment application is stored on the payment as `applied_allocations`, a list of entries pairing each `installment_id` with its `applied_cents` in that same chronological order. An installment whose `paid_cents` reaches its `amount_cents` with no write-off becomes `PAID`, and an installment that becomes fully covered through a mix of payments and write-offs while holding `paid_cents` above zero likewise becomes `PAID`; either transition recomputes the pledge's `outstanding_cents` and may fulfill the pledge per §3.6. The credited fund — the pledge's fund for a pledge-linked payment, otherwise the payload's `fund_id` when present — has its `balance_cents` increased by the payment amount, and a fund at or above its `minimum_activation_cents` after the credit moves from `PENDING_MINIMUM` to `ACTIVE` with a `version` bump. Campaign totals recompute under both variants, with a `corporate_matched` payment counted at half its counted amount (§3.9), rounded down to a whole cent per payment. The donor prospect's `lifetime_given_cents`, `outstanding_pledge_cents`, and recognition standing recompute, and the prospect's `version` advances by 1. Payments are listable with `pledge_id`, `fund_id`, `campaign_id`, and `donor_prospect_id` filters.

Reversal is the books-and-records undo, available to the `FinanceSteward` on any payment not already reversed (a second reversal fails with `ERR_PAYMENT_ALREADY_REVERSED`). Reversal sets `reversed` true, stamps `reversed_at` from the logical clock, and reconciles every derived field the payment touched: each allocation in `applied_allocations` is withdrawn from its installment's `paid_cents`; a `PAID` installment reopens to `OVERDUE` when the current logical time is already strictly later than its `due_date` plus 30 days, otherwise to `REMINDED` when its `reminder_count` is above zero, otherwise to `SCHEDULED`; a `FULFILLED` pledge returns to `ACTIVE` with its outstanding balance recomputed; the credited fund's `balance_cents` is decremented, dropping an `ACTIVE` fund back to `PENDING_MINIMUM` when the balance falls below `minimum_activation_cents`; campaign totals decrement under both variants; and the donor prospect's aggregates and recognition recompute with the prospect's `version` advancing. A reversed payment counts toward nothing anywhere in the system.

### 3.8. Restricted Funds, Endowment Spending, and Stewardship

Restricted gifts create obligations the office must both invest and report on. Each restricted fund established at agreement execution (§3.5) tracks a `balance_cents` — the sum of non-reversed payments credited to the fund minus disbursements — against its `minimum_activation_cents`. A `PENDING_MINIMUM` fund activates automatically: as soon as a payment credit brings `balance_cents` to at least `minimum_activation_cents`, the fund becomes `ACTIVE`; and should a reversal or disbursement later pull the balance below that floor, an `ACTIVE` fund returns to `PENDING_MINIMUM`. Funds are listable with `agreement_id` and `status` filters, and reading a fund always returns its current `spendable_fy_cents` and `allowance_remaining_cents`.

Endowed funds spend by formula, not by balance alone. The office's fiscal year runs July 1 through June 30; the fiscal year containing a date starts on July 1 of that date's calendar year when the month is July or later, and on July 1 of the prior calendar year otherwise. The **spending allowance** for the current fiscal year uses only market history that predates the year: the fund's `trailing_market_values` entries — each a `quarter_end` paired with a `value_cents`, unique per fund by quarter — are filtered to those whose `quarter_end` is strictly before the current fiscal year's start, and at most the 12 most recent such entries participate. Fewer than 4 qualifying quarters means no spending authority at all: `spendable_fy_cents` is 0. Otherwise `spendable_fy_cents` is four and a half percent (0.045) of the average `value_cents` across the qualifying quarters, rounded half up to a whole cent. Disbursements and valuations recorded during the current fiscal year never change the current year's `spendable_fy_cents`; they only affect later years. The `allowance_remaining_cents` is `spendable_fy_cents` minus the disbursement amounts posted with a `created_at` inside the current fiscal year. Current-use funds (`is_endowed` false) keep `spendable_fy_cents` and `allowance_remaining_cents` at zero and are constrained by `balance_cents` alone. The allowance is recomputed on every fund read, before every disbursement, when valuations are appended, and whenever the clock crosses a fiscal-year boundary.

A `FinanceSteward` maintains the market history by appending valuations with a `quarter_end` and a `value_cents`; a quarter already recorded on the fund rejects the append with `ERR_DUPLICATE_QUARTER_VALUATION`. Appending extends `trailing_market_values`, recomputes `spendable_fy_cents` and `allowance_remaining_cents`, and advances the fund's `version`. A valuation is an entry in the fund's `trailing_market_values`, not a standalone resource in the sense of §2.4, so the append is a modification of the fund and returns `200 OK` with the updated fund, not `201 Created`. The same steward disburses from a fund with an `amount_cents` and a `purpose_note`: the disbursement is refused when the fund is `SPENDING_FROZEN` (`ERR_FUND_SPENDING_FROZEN`) or `CLOSED` (`ERR_FUND_NOT_ACTIVE`), and for an endowed fund the amount must not exceed the smaller of `allowance_remaining_cents` and `balance_cents` — for a current-use fund, `balance_cents` alone caps it — with any excess rejected as `ERR_SPENDING_ALLOWANCE_EXCEEDED`. A posted disbursement decrements `balance_cents`, recomputes `allowance_remaining_cents`, drops the fund to `PENDING_MINIMUM` if the balance fell below the minimum, and advances the fund's `version`.

Stewardship reporting closes the loop with the donor, on the clock. A `DonorRelationsOfficer` opens a report on a fund with a `period_start`, a `period_end` that must be later than the start, and an optional `narrative`; the report's `due_date` is set automatically to `period_end` plus 90 days, and it starts as `DRAFT`. Report periods for the same fund must not overlap under **closed-interval** semantics — both endpoints count as inside the period, so a new period that merely shares a boundary date with an existing report already overlaps and is rejected with `ERR_REPORT_PERIOD_OVERLAP`. The officer then submits the report, moving it to `SUBMITTED` with `submitted_by` recorded; submission is allowed from `DRAFT` and, as the catch-up path, from `OVERDUE` — any other state fails with `ERR_REPORT_TRANSITION_INVALID` — and a catch-up submission leaves the fund frozen and the agreement lapsed until the report is actually delivered. Delivery moves a `SUBMITTED` report to `DELIVERED` (from any other state, `ERR_REPORT_TRANSITION_INVALID`). Reports of a fund are listable with an optional `status` filter.

Lapsed stewardship has teeth. When the clock sweep finds a `DRAFT` report whose `due_date` is strictly before the current logical time, the report becomes `OVERDUE`, and two cascades fire: the fund moves from `ACTIVE` to `SPENDING_FROZEN` — a fund still `PENDING_MINIMUM` is not frozen — and the establishing agreement's `compliance_status` becomes `STEWARDSHIP_LAPSED`, each touched resource advancing its `version`. While frozen, the fund rejects incoming credits and outgoing disbursements per §2.10. Recovery is just as automatic: when the overdue report reaches `DELIVERED` and no other report of the fund remains `OVERDUE`, the fund returns from `SPENDING_FROZEN` to `ACTIVE` and the agreement's `compliance_status` returns to `COMPLIANT`. `DELIVERED` is the report's terminal state; `CLOSED` is the fund's, reached only through rescission of its establishing agreement.

### 3.9. Campaigns, Credit, and Donor Recognition

Campaigns frame the office's public goals. A `VPAdvancement` creates a campaign with a `name`, a positive integer `goal_cents`, and an **inclusive** counting window from `counting_start` through `counting_end` — the end must be later than the start — entering `DRAFT` with `face_value_counted_cents` and `cash_counted_cents` both zero. The same role activates a `DRAFT` campaign (`ACTIVE`), closes an `ACTIVE` one (`CLOSED`), and marks a `CLOSED` one as `REPORTED`; each step out of order fails with `ERR_CAMPAIGN_INVALID_STATE`, and `REPORTED` is terminal. Closing freezes both counted totals permanently: a payment or pledge booking later referencing the campaign is rejected (per §3.6 and §3.7) rather than re-opening the books, while write-off approvals, pledge cancellations, and payment reversals that touch a closed campaign proceed normally and leave the frozen totals unchanged.

The office reports every campaign under **two counting variants**, stored denormalized on the campaign and recomputed whenever a payment is recorded or reversed, a pledge is created, a write-off is approved, or a pledge is cancelled. A payment's **counted amount** is its `amount_cents` — or, when the payment carries splits, the computed `amount_cents` of its single `HARD` split per §3.7 — taken in full, or, when the payment is `corporate_matched`, halved and rounded down to a whole cent per payment. Under `FACE_VALUE_BOOKING` — the board-facing booking measure — the campaign counts every pledge booked to it whose creation time falls inside the inclusive window and whose status is `ACTIVE`, `FULFILLED`, or `WRITTEN_OFF`, at its `total_amount_cents` net of its `written_off_cents` (a `CANCELLED` pledge contributes nothing, its remaining balance netting out at cancellation), plus every non-reversed payment booked to the campaign that is not pledge-linked and whose `received_at` falls inside the window, counted at its counted amount. Under `CASH_RECEIPTS` — the cash-flow measure — the campaign counts every non-reversed payment booked to it whose `received_at` falls inside the window, including pledge-linked payments that the face-value variant ignores, at the same counted amount; unpaid pledge balances count for nothing here. The variants are exposed side by side through the campaign's totals read, which returns `face_value_counted_cents`, `cash_counted_cents`, `goal_cents`, and the campaign `status`, and credit splits booked to the campaign are listable with an optional `credit_type` filter.

Recognition converts giving history into donor standing. A `DonorRelationsOfficer` configures each **recognition society** with a `name`, a `level` of `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM` — unique across all societies, so a duplicate level is rejected with `ERR_DUPLICATE_SOCIETY_LEVEL` — a positive integer `threshold_cash_cents`, and an optional `benefits_text`. Two totals are maintained per prospect. The **cash-only** total is exactly the prospect's `lifetime_given_cents`. The **comprehensive** total adds to that the `outstanding_cents` of the prospect's `ACTIVE` pledges plus the `amount_cents` of the prospect's non-reversed `SOFT` credit splits — the same figure reported as `soft_credit_cents` in the recognition read. Membership uses cash only: among the societies whose `threshold_cash_cents` is at or below the cash-only total, the one with the highest threshold wins — levels ranked `BRONZE` below `SILVER` below `GOLD` below `PLATINUM` — and a prospect's `member_level` is that society's level, or null when the total clears no threshold; the `projected_level` applies the same rule to the comprehensive total, so a prospect can project higher than its membership. Should two societies share a threshold, the lower-ranked level wins, and a remaining tie breaks by earlier `created_at`. The prospect's `recognition_society_id` holds the society corresponding to the member level; society maintenance is reflected **lazily**, recomputed on the next recognition read rather than eagerly across the directory, and that lazy refresh updates `recognition_society_id` in place without advancing the prospect's `version` or `updated_at`. The recognition read for a prospect returns `cash_total_cents`, `comprehensive_total_cents`, `soft_credit_cents`, `member_level`, and `projected_level`, and the totals recompute on every payment creation or reversal, pledge creation, approved write-off, or pledge cancellation touching the prospect.

## 4. Endpoint Definitions

All endpoints live under the `/advancement` prefix. Operations that create a new resource return `201 Created`; operations that modify, transition, or compute against an existing resource return `200 OK`. Request and response payloads are not repeated here — they are defined by the narratives of §3 — and every list endpoint accepts the pagination parameters of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/advancement/_clock/set_current_utc` | Advance the logical clock and run all time-based sweeps | AdvancementDirector, VPAdvancement |
| POST | `/advancement/fundraisers` | Create a fundraiser with portfolio capacity limits | VPAdvancement |
| GET | `/advancement/fundraisers/{id}` | Get a fundraiser including computed capacity counters | All roles |
| POST | `/advancement/fundraisers/{id}/deactivate` | Deactivate a fundraiser; requires zero ACTIVE assignments | VPAdvancement |
| POST | `/advancement/fundraisers/{id}/assignments` | Assign a prospect to a fundraiser's portfolio (OCC on fundraiser version) | AdvancementDirector |
| GET | `/advancement/fundraisers/{id}/assignments` | List assignments of a fundraiser | All roles |
| POST | `/advancement/assignments/{id}/release` | Release an ACTIVE assignment | AdvancementDirector |
| POST | `/advancement/prospects` | Create a prospect (IDENTIFIED / QUALIFICATION) | ProspectResearcher |
| GET | `/advancement/prospects/{id}` | Get a prospect including giving aggregates and recognition society | All roles |
| GET | `/advancement/prospects` | List prospects with filters | All roles |
| POST | `/advancement/prospects/{id}/disqualify` | Disqualify a prospect; releases assignments and rejects open proposals | ProspectResearcher, AdvancementDirector |
| POST | `/advancement/prospects/{id}/moves` | Advance or loop the moves-management stage | GiftOfficer |
| GET | `/advancement/prospects/{id}/assignments` | List assignments of a prospect | All roles |
| GET | `/advancement/prospects/{id}/credit-splits` | List credit splits where the prospect receives credit | All roles |
| GET | `/advancement/prospects/{id}/recognition` | Recognition totals under both variants and derived society levels | All roles |
| POST | `/advancement/prospects/{id}/assessments` | Create a research assessment; moves the prospect to IN_SCREENING | ProspectResearcher |
| GET | `/advancement/prospects/{id}/assessments` | List assessments of a prospect | All roles |
| POST | `/advancement/assessments/{id}/review` | Approve or reject a SUBMITTED assessment | AdvancementDirector |
| GET | `/advancement/prospects/{id}/proposals` | List proposals of a prospect | All roles |
| POST | `/advancement/proposals` | Create a DRAFT proposal (OCC on prospect version) | GiftOfficer |
| GET | `/advancement/proposals/{id}` | Get a proposal | All roles |
| PATCH | `/advancement/proposals/{id}` | Edit a proposal; resets it to DRAFT and clears tier/quorum fields | GiftOfficer |
| POST | `/advancement/proposals/{id}/submit` | Submit for approval; computes tier and pins the capacity band | GiftOfficer |
| POST | `/advancement/proposals/{id}/review` | Decide a proposal under review per its tier | AdvancementDirector, VPAdvancement |
| POST | `/advancement/proposals/{id}/agreements` | Draft a gift agreement from an APPROVED proposal | GiftOfficer |
| GET | `/advancement/agreements/{id}` | Get a gift agreement (both status dimensions) | All roles |
| GET | `/advancement/agreements` | List agreements with filters | All roles |
| POST | `/advancement/agreements/{id}/present` | Present for signature; claims the naming opportunity for 14 days | GiftOfficer |
| POST | `/advancement/agreements/{id}/execute` | Execute a presented agreement; establishes the restricted fund | VPAdvancement |
| POST | `/advancement/agreements/{id}/rescind` | Rescind an agreement with no non-reversed payments | VPAdvancement |
| GET | `/advancement/agreements/{id}/naming-reservations` | List naming opportunities reserved or occupied by this agreement | All roles |
| POST | `/advancement/naming-opportunities` | Create a naming opportunity with a price floor | VPAdvancement |
| GET | `/advancement/naming-opportunities/{id}` | Get a naming opportunity | All roles |
| POST | `/advancement/naming-opportunities/{id}/retire` | Retire an AVAILABLE or RESERVED opportunity | VPAdvancement |
| POST | `/advancement/pledges` | Create a pledge on an EXECUTED pledge-type agreement; generates the schedule | GiftOfficer |
| GET | `/advancement/pledges/{id}` | Get a pledge | All roles |
| GET | `/advancement/pledges` | List pledges with filters | All roles |
| GET | `/advancement/pledges/{id}/installments` | List installments of a pledge in schedule order | All roles |
| POST | `/advancement/installments/{id}/remind` | Send a pledge reminder; at most 3 per installment | DonorRelationsOfficer |
| POST | `/advancement/pledges/{id}/write-offs` | Request a pledge write-off (PENDING) | GiftOfficer, FinanceSteward |
| GET | `/advancement/pledges/{id}/write-offs` | List write-off requests of a pledge | All roles |
| POST | `/advancement/write-offs/{id}/review` | Approve or reject a PENDING write-off | AdvancementDirector |
| POST | `/advancement/gift-payments` | Record a gift payment; allocates, credits, counts, and splits | FinanceSteward |
| GET | `/advancement/gift-payments/{id}` | Get a gift payment including applied allocations | All roles |
| GET | `/advancement/gift-payments` | List gift payments with filters | All roles |
| POST | `/advancement/gift-payments/{id}/reverse` | Reverse a payment and reconcile every derived field it touched | FinanceSteward |
| GET | `/advancement/gift-payments/{id}/credit-splits` | List credit splits of a payment | All roles |
| GET | `/advancement/funds/{id}` | Get a restricted fund including spending allowance figures | All roles |
| GET | `/advancement/funds` | List restricted funds with filters | All roles |
| POST | `/advancement/funds/{id}/valuations` | Append a quarter-end market valuation | FinanceSteward |
| POST | `/advancement/funds/{id}/disburse` | Disburse from a fund within the spending allowance | FinanceSteward |
| POST | `/advancement/funds/{id}/reports` | Create a stewardship report for a closed, non-overlapping period | DonorRelationsOfficer |
| GET | `/advancement/funds/{id}/reports` | List stewardship reports of a fund | All roles |
| POST | `/advancement/stewardship-reports/{id}/submit` | Submit a DRAFT or OVERDUE report | DonorRelationsOfficer |
| POST | `/advancement/stewardship-reports/{id}/deliver` | Deliver a SUBMITTED report; unfreezes when no other report is overdue | DonorRelationsOfficer |
| POST | `/advancement/campaigns` | Create a campaign with an inclusive counting window | VPAdvancement |
| GET | `/advancement/campaigns/{id}` | Get a campaign | All roles |
| POST | `/advancement/campaigns/{id}/activate` | Activate a DRAFT campaign | VPAdvancement |
| POST | `/advancement/campaigns/{id}/close` | Close an ACTIVE campaign; totals freeze | VPAdvancement |
| POST | `/advancement/campaigns/{id}/report` | Mark a CLOSED campaign as REPORTED | VPAdvancement |
| GET | `/advancement/campaigns/{id}/totals` | Both counting variants side by side | All roles |
| GET | `/advancement/campaigns/{id}/credit-splits` | List credit splits booked to a campaign | All roles |
| POST | `/advancement/recognition-societies` | Configure a recognition society level | DonorRelationsOfficer |
| GET | `/advancement/recognition-societies` | List recognition societies | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live with the rules in §2 and §3; this catalogue enumerates only identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_PROSPECT_OWNER` | 403 |
| `ERR_TIER_APPROVAL_ROLE_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROSPECT_NOT_FOUND` | 404 |
| `ERR_FUNDRAISER_NOT_FOUND` | 404 |
| `ERR_PROPOSAL_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_PLEDGE_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_MOVES_TRANSITION` | 409 |
| `ERR_PROSPECT_NOT_RATED` | 409 |
| `ERR_PROSPECT_NOT_SOLICITABLE` | 409 |
| `ERR_FUNDRAISER_INACTIVE` | 409 |
| `ERR_FUNDRAISER_HAS_ACTIVE_ASSIGNMENTS` | 409 |
| `ERR_ASSESSMENT_NOT_REVIEWABLE` | 409 |
| `ERR_PROPOSAL_STATE_FORBIDS` | 409 |
| `ERR_PROPOSAL_NOT_UNDER_REVIEW` | 409 |
| `ERR_PROPOSAL_NOT_APPROVED` | 409 |
| `ERR_AGREEMENT_INVALID_STATE` | 409 |
| `ERR_RESCIND_BLOCKED_BY_PAYMENTS` | 409 |
| `ERR_PLEDGE_NOT_ACTIVE` | 409 |
| `ERR_PLEDGE_ALREADY_EXISTS` | 409 |
| `ERR_INSTALLMENT_NOT_REMINDABLE` | 409 |
| `ERR_REMINDER_LIMIT_EXCEEDED` | 409 |
| `ERR_WRITE_OFF_NOT_PENDING` | 409 |
| `ERR_PAYMENT_ALREADY_REVERSED` | 409 |
| `ERR_CAMPAIGN_INVALID_STATE` | 409 |
| `ERR_FUND_NOT_ACTIVE` | 409 |
| `ERR_REPORT_TRANSITION_INVALID` | 409 |
| `ERR_PROSPECT_ALREADY_ASSIGNED` | 409 |
| `ERR_STEWARDSHIP_LAPSED` | 409 |
| `ERR_FUND_SPENDING_FROZEN` | 409 |
| `ERR_FUND_PLEDGE_MISMATCH` | 422 |
| `ERR_PORTFOLIO_CAPACITY_EXCEEDED` | 409 |
| `ERR_OPEN_ASK_LOAD_EXCEEDED` | 409 |
| `ERR_NAMING_OPPORTUNITY_UNAVAILABLE` | 409 |
| `ERR_ASK_EXCEEDS_CAPACITY` | 422 |
| `ERR_BELOW_NAMING_FLOOR` | 422 |
| `ERR_AGREEMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_PLEDGE_TYPE_REQUIRED` | 422 |
| `ERR_DUPLICATE_SOCIETY_LEVEL` | 409 |
| `ERR_DUPLICATE_QUARTER_VALUATION` | 409 |
| `ERR_DUPLICATE_APPROVAL` | 409 |
| `ERR_RESERVATION_EXPIRED` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_OUTSIDE_COUNTING_WINDOW` | 422 |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 |
| `ERR_WRITE_OFF_EXCEEDS_OUTSTANDING` | 422 |
| `ERR_SPLIT_PERCENT_SUM_INVALID` | 422 |
| `ERR_SPENDING_ALLOWANCE_EXCEEDED` | 422 |
