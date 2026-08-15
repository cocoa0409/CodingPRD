# Offer Approval & Compensation Governance API — Product Requirements Document

## 1. Introduction

Hiring is a fiscal commitment long before it is a handshake. Every offer letter that leaves the building commits an annual budget line, moves an internal-equity position, and binds the company to sign-on and relocation promises with real clawback terms. When those commitments are assembled over email and approved by whoever happens to be online, organizations drift into the failure modes this product exists to prevent: offers priced outside the approved band, budgets silently oversubscribed across parallel requisitions, counteroffers conceded by staff without the authority to concede them, and start dates announced before the background check has cleared.

This document specifies a REST API, mounted under `/api`, that governs the full recruiting approval workflow end to end. A requisition carries an approved budget and salary band through finance and compensation review; offers are constructed against that band with computed cost and equity analytics; approval chains are generated from policy rows according to how far the offer deviates from the band; counteroffers are bounded by per-role concession authority; letters are pinned to exact offer versions; candidates accept, decline, or let the offer lapse against a deterministic logical clock; and contingency checks arbitrate the final step from acceptance to hire — or to automatic rescission. Nine acting roles cooperate under segregation of duties, every meaningful occurrence is written to an append-only audit trail, and every mutation flows through explicit state machines with optimistic concurrency control on the write paths where stale views are dangerous.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API: identity, response shape, pagination, time, resource metadata, money, concurrency, cascading reconciliation, audit, and the order in which validations run.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`; certain endpoints narrow the permitted role further by workflow stage, and a stage-mismatched role draws the same error. Where a role owns resources, acting on another owner's resource is rejected with `ERR_NOT_RESOURCE_OWNER`.

The system recognizes nine roles, spelled exactly as follows: `HRAdmin`, `HiringManager`, `Recruiter`, `CompAnalyst`, `FinanceController`, `DepartmentDirector`, `VPPeople`, `BackgroundScreener`, and `Candidate`.

Eight of these roles have opaque identity. When `X-User-Role` is `HRAdmin`, `HiringManager`, `Recruiter`, `CompAnalyst`, `FinanceController`, `DepartmentDirector`, `VPPeople`, or `BackgroundScreener`, the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `hiring_manager_id` on a Requisition at creation, as `created_by_user_id` on an Offer, as `decided_by_user_id` on an ApprovalStep or NegotiationRound, or in the delegation-grant fields — but it is never compared to any entity's `id` for these roles.

The `Candidate` role is entity-backed. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting Candidate resource. Ownership checks on any resource that references a Candidate compare the resource's foreign-key field — an offer's `candidate_id` or the candidate record's own `id` — to `X-User-ID`. A Candidate may read only their own record and their own offers, and may act only on their own offers; anything else is `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100, and a value outside that range is rejected as a malformed request with `ERR_INVALID_REQUEST`. The `offset` parameter specifies how many items to skip and defaults to 0. Both are validated as part of request-shape checking.

Unless a list endpoint states a more specific ordering, every list returns resources sorted by `created_at` ascending. The paginated response's `meta` object carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent business logic — offer expiry, delegation windows — reads a server-side logical clock, never the wall clock. At server startup the logical clock is exactly `2026-08-01T00:00:00Z`. An `HRAdmin` may advance it through a test-driving capability that accepts a `to_iso8601` timestamp and responds with the resulting `current_utc`; setting the clock mutates no entity.

Expiry in this system is lazy rather than swept. There is no background job scanning for expired offers or lapsed grants: the first call that observes the logical clock at or past a deadline persists the resulting state change and fires its side effects at that moment. Implementations must therefore evaluate expiry on every state-changing call against a time-boxed resource, and on reads where specified.

### 2.5. Common Resource Properties

Every primary resource in the system — Requisition, Candidate, InternalEquitySnapshot, ApprovalPolicy, Offer, ApprovalStep, NegotiationRound, PerkPackage, ClearanceCheck, OfferLetter, and DelegationGrant — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource's properties.
- `version` (integer): a system-managed integer that increments on every mutation of the resource; it backs the optimistic concurrency rules of §2.7.

The audit-trail resource, OfferEvent, is the sole exception: it is append-only and immutable, so it carries `id` and `created_at` only — `updated_at` and `version` are absent.

### 2.6. Money, Precision, and Rounding

All monetary amounts are represented as integer cents — budget lines, salary band points, offer terms, perk amounts, and every computed cost field. No floating-point money appears anywhere in the API. Where a monetary derivation requires rounding, the rule is round half up to whole cents, applied at each pinned step of the derivation rather than once at the end; §3 names the pinned steps for each calculation.

Two ratio metrics use finer precision. The internal-equity compa ratio and the negotiation concession percentage are carried at four decimal places, each rounded half up. The peer percentile is an integer from 0 to 100, rounded half up. Band thresholds are compared against unrounded products — a boundary comparison never rounds the product before comparing it.

Expiry comparisons are made against the logical clock at one-second resolution on ISO 8601 UTC instants: a call landing exactly at an expiry instant is treated as expired, while one second earlier is still valid.

### 2.7. Optimistic Concurrency Control

Three write endpoints carry an explicit optimistic concurrency contract; no other endpoint accepts a version field.

- `PATCH /api/offers/{id}` — revising an offer's terms — requires the request to carry `expected_offer_version` holding the offer's `version` as the client last observed it. If the offer's current `version` has advanced beyond that value — because another writer revised terms or recorded a negotiation round, both of which legitimately advance it — the request is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412), so the client cannot overwrite an offer state it has not observed.
- `POST /api/offers/{id}/negotiation-rounds` — recording a negotiation round against an offer — likewise requires `expected_offer_version`, and a mismatch with the offer's current `version` is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412) on the same rationale: a prior terms revision or round creation has moved the negotiation state past the client's view.
- `PATCH /api/requisitions/{id}` — editing a requisition — requires `expected_requisition_version` matching the requisition's current `version`; a mismatch is rejected with `ERR_STALE_REQUISITION_VERSION` (HTTP 412), because a prior edit has advanced the requisition past the client's view.

The version fields are mandatory inputs on these three endpoints — there is no "omit to skip the check" path.

### 2.8. Cascading Reconciliation and Derived State

Several resources carry derived state that the server reconciles automatically whenever the underlying facts change, without waiting for an explicit client request on the derived resource. Two standing aggregates live on every requisition: `committed_budget_cents`, the sum of the fully loaded annual cost over exactly those of its offers in `PENDING_APPROVAL`, `APPROVED`, `LETTER_GENERATED`, `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED` status, recomputed in full — never incrementally adjusted — whenever an offer enters or leaves that counted set or an offer's fully loaded cost changes; and `headcount_filled`, the count of the requisition's offers in `HIRED` status, recomputed whenever an offer enters or leaves `HIRED`. Because the counted set excludes `DRAFT` and `RETURNED`, a submitting offer is never counted against its own budget gate.

State changes propagate down the hierarchy as well. When a requisition closes at full headcount or is cancelled, every still-active offer of that requisition is withdrawn in one cascade, and each withdrawn offer in turn supersedes its undecided approval steps, withdraws its pending negotiation round, and voids its unvested perks — §3.9 specifies the cascade exhaustively. When an offer's clearance posture resolves, the offer is hired or rescinded automatically, and a hire may in turn close the requisition. Each such reconciliation mutates the affected resource: any change to a resource's recorded properties refreshes its `updated_at` and increments its `version`, and the transitions that explicitly advance an Offer's `version` are terms revision and negotiation-round creation or acceptance.

### 2.9. The Offer Audit Trail

Every Offer owns an append-only sequence of OfferEvent records, ordered by a `sequence` that starts at 1 and increases monotonically per offer. Each event carries the `offer_id` it belongs to, an `event_type`, the `actor_user_id` of the operator who caused it — or the literal string `system` when a cascade or lazy evaluation caused it — and an optional machine-readable `detail` (for example the rescind reason or an approval step's sequence). The complete set of event types is: `OFFER_CREATED`, `TERMS_REVISED`, `SUBMITTED`, `STEP_APPROVED`, `STEP_REJECTED`, `STEP_SUPERSEDED`, `APPROVED`, `RETURNED`, `LETTER_GENERATED`, `LETTER_SUPERSEDED`, `EXTENDED`, `COUNTER_RECORDED`, `COUNTER_ACCEPTED`, `COUNTER_REJECTED`, `ROUND_WITHDRAWN`, `ACCEPTED`, `DECLINED`, `EXPIRED`, `RESCINDED`, `WITHDRAWN`, `HIRED`, `CHECK_INITIATED`, `CHECK_TRANSITIONED`, `CHECK_WAIVED`, `CHECK_CANCELLED`, `PERK_ADDED`, and `PERK_VOIDED`. §3 names the exact moment each type is appended. The trail is readable per offer, paginated, and filterable by `event_type`.

### 2.10. Validation Order and Nested Resource Retrieval

Every request is evaluated against an ordered validation pipeline, and a request that would fail several checks surfaces the error from the earliest tier it fails — the tiers are not independent, and their relative order is part of the contract:

1. **Authentication.** Headers present and role declared, else `ERR_UNAUTHENTICATED`.
2. **Request shape.** Required fields present, unknown fields rejected, types and enum membership valid, integer amounts positive where specified, pagination `limit` inside its permitted range, else `ERR_INVALID_REQUEST`.
3. **Endpoint role membership**, including stage-dependent role checks — the requisition review decision demands a `FinanceController` at the budget stage and a `CompAnalyst` at the range stage — else `ERR_UNAUTHORIZED_ROLE`.
4. **Ownership** — a Candidate confined to their own offers and record, a HiringManager confined to requisitions they own — else `ERR_NOT_RESOURCE_OWNER`.
5. **Existence.** Path identifiers are validated left to right, and the first segment that does not resolve rejects the request: `ERR_REQUISITION_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_APPROVAL_STEP_NOT_FOUND`, `ERR_NEGOTIATION_ROUND_NOT_FOUND`, `ERR_PERK_NOT_FOUND`, `ERR_CLEARANCE_CHECK_NOT_FOUND`, `ERR_DELEGATION_GRANT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, or `ERR_SNAPSHOT_NOT_FOUND`, each HTTP 404. On a nested path such as an offer's perks, an unknown offer id surfaces before the system ever looks for the perk. Body references — the `requisition_id` and `candidate_id` supplied at offer creation — are validated for existence at this tier as well.
6. **State gates.** The action must be legal from the resource's current status: requisition-state violations draw `ERR_REQUISITION_INVALID_STATE`; offer creation, submission, and letter generation against a non-`OPEN` requisition draw `ERR_REQUISITION_NOT_OPEN`; offer actions illegal from the offer's current status draw `ERR_INVALID_OFFER_STATE`; deciding a step that is not `ACTIONABLE` draws `ERR_STEP_NOT_ACTIONABLE`; deciding a round that is not `PROPOSED` draws `ERR_ROUND_NOT_PENDING`; a clearance transition that is not a declared edge of the check's machine draws `ERR_CHECK_INVALID_TRANSITION`; creating an offer for an `ARCHIVED` candidate draws `ERR_CANDIDATE_NOT_HIRABLE`; archiving a candidate with live offers draws `ERR_CANDIDATE_HAS_ACTIVE_OFFER`. All are HTTP 409.
7. **Optimistic concurrency**, per §2.7 — `ERR_STALE_OFFER_VERSION` or `ERR_STALE_REQUISITION_VERSION`, HTTP 412.
8. **Segregation of duties** on approval decisions — `ERR_SELF_APPROVAL_FORBIDDEN`, HTTP 403.
9. **Peer-data sufficiency** at offer submission — `ERR_INSUFFICIENT_PEER_DATA`, HTTP 422.
10. **Business constraints** — negotiation round limit, single active offer per candidate, duplicate active check, perk-add window, delegation overlap, delegation self-reference and window coherence, mandatory declination reason, candidate email uniqueness, and salary-range coherence, each with its own error id.
11. **Temporal checks.** Lazy expiry of an `EXTENDED` or `COUNTERED` offer persists `EXPIRED` and rejects the triggering call with `ERR_OFFER_EXPIRED`; a delegated decision outside the grant's window draws `ERR_DELEGATION_NOT_ACTIVE`.
12. **Fiscal gates**, last: the submission budget gate (`ERR_REQUISITION_BUDGET_EXCEEDED`), the base hard cap (`ERR_BASE_EXCEEDS_HARD_CAP`), the sign-on hard cap (`ERR_SIGNON_EXCEEDS_HARD_CAP`), and counteroffer concession authority (`ERR_CONCESSION_EXCEEDS_AUTHORITY`).

A request that is both stale-versioned and role-forbidden therefore surfaces `ERR_UNAUTHORIZED_ROLE`; a request failing both the state gate and the budget gate surfaces the state error.

## 3. Business Logic & Workflows

### 3.1. Requisition Intake and Approval Gates

Every hiring need begins as a Requisition drafted by a `HiringManager`. Creation captures the `title`, the owning `department`, the `role_level` band — one of `L3`, `L4`, `L5`, `L6`, or `L7` — and the `geo_tier` pay locality — one of `T1`, `T2`, or `T3`. The financial frame is set by `annual_budget_cents`, the total approved annual budget for all hires on the requisition, and by the approved salary band `salary_min_cents`, `salary_mid_cents`, and `salary_max_cents`, while `headcount_authorized` fixes how many hires the requisition funds. The system stamps the creator's `X-User-ID` into `hiring_manager_id`, starts the requisition in `DRAFT`, and initializes `headcount_filled` to zero, `committed_budget_cents` to zero, and `close_reason` to null.

The financial frame must be coherent both at creation and on any later edit: the band minimum must be positive and strictly below the midpoint, the midpoint must not exceed the maximum, the budget must be positive, and the authorized headcount must be at least one. Any violation is rejected with `ERR_SALARY_RANGE_INVALID`. While the requisition remains in `DRAFT`, the owning hiring manager may edit its terms — `title`, `department`, `annual_budget_cents`, the three band points, or `headcount_authorized` — subject to the optimistic concurrency rule of §2.7: the edit must carry `expected_requisition_version`, and each successful edit increments the requisition's `version`. Edits by anyone other than the requisition's owner are rejected with `ERR_NOT_RESOURCE_OWNER`, and edits attempted once the requisition has left `DRAFT` are rejected with `ERR_REQUISITION_INVALID_STATE`.

Submission moves the requisition `DRAFT → BUDGET_REVIEW` and is likewise owner-only. From there a two-stage review runs. At the `BUDGET_REVIEW` stage only a `FinanceController` may record a review decision; at the `RANGE_APPROVAL` stage only a `CompAnalyst` may. The decision payload carries a `decision` of `APPROVE` or `RETURN` plus an optional `note`. An `APPROVE` advances the requisition — `BUDGET_REVIEW → RANGE_APPROVAL`, then `RANGE_APPROVAL → OPEN` — while a `RETURN` at either stage sends it back to `DRAFT` for rework. A decision attempted in any other status, or by the wrong stage role, is rejected (`ERR_REQUISITION_INVALID_STATE` and `ERR_UNAUTHORIZED_ROLE` respectively).

Once `OPEN`, the requisition accepts offers. The owner may pause intake, moving `OPEN → PAUSED` by recording a hold `action` of `PAUSE`, and resume with `PAUSED → OPEN` via `RESUME`; either action from the wrong status draws `ERR_REQUISITION_INVALID_STATE`. The owner may also cancel outright from `OPEN` or `PAUSED`, optionally attaching a `reason`; cancellation moves the requisition to the terminal `CANCELLED` status and triggers the auto-withdraw cascade described in §3.9 with event detail `REQUISITION_CANCELLED`. Requisitions are listable with optional `status` and `hiring_manager_id` filters.

The final requisition transitions are system-driven. When a hire recomputation finds `headcount_filled` exactly equal to `headcount_authorized` on an `OPEN` requisition, the requisition closes itself: `OPEN → CLOSED`, with `CLOSED` recording `close_reason` as `FILLED` and the auto-withdraw cascade firing with event detail `REQUISITION_FILLED`. The boundary is exact equality — because the requisition closes at equality, a count beyond the authorized headcount can never occur. Symmetrically, when a `HIRED` offer is later rescinded for `RENEG` or `COMPLIANCE_HOLD` on a requisition whose `close_reason` is `FILLED`, the requisition reopens `CLOSED → OPEN` and `close_reason` returns to null.

### 3.2. Candidates, Peer Benchmarks, and Routing Policies

Three configuration-side resources feed the offer workflow: the candidate roster, the internal-equity peer set, and the approval policy table.

A `Recruiter` registers a Candidate with a `full_name` and an `email`; the email must be unique case-insensitively across all candidates, and a duplicate is rejected with `ERR_CANDIDATE_EMAIL_EXISTS`. An optional `current_base_cents` captures the candidate's self-reported current base salary for analytics only — it participates in no gate or calculation. New candidates start as `PROSPECT`. The first offer created for a candidate moves them `PROSPECT → IN_PROCESS` automatically; an offer reaching `HIRED` moves the candidate `IN_PROCESS → HIRED`; and a reneg or compliance rescission of that hire returns them `HIRED → IN_PROCESS`. A `Recruiter` may archive a candidate from `PROSPECT` or `IN_PROCESS`, but only when the candidate has no offer in any live status — `DRAFT`, `RETURNED`, `PENDING_APPROVAL`, `APPROVED`, `LETTER_GENERATED`, `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED` — otherwise the archive is rejected with `ERR_CANDIDATE_HAS_ACTIVE_OFFER`. `ARCHIVED` is terminal, and creating an offer for an archived candidate is rejected with `ERR_CANDIDATE_NOT_HIRABLE`. Candidate records are readable by `Recruiter`, `HiringManager`, `CompAnalyst`, and `HRAdmin`, and by the candidate themselves — a `Candidate` reading anyone else's record is `ERR_NOT_RESOURCE_OWNER`.

The internal-equity peer set is maintained one row at a time by a `CompAnalyst`. Each InternalEquitySnapshot records one incumbent's `role_level`, `geo_tier`, current `base_cents` (which must be positive), and an optional `bonus_target_pct` expressed as a decimal (a value of 0.10 means ten percent) that defaults to 0 when omitted. Snapshots have no status and are never filtered by one; the peer set for an offer is simply every snapshot whose `role_level` and `geo_tier` match the requisition's. The collection is listable with optional `role_level` and `geo_tier` filters.

Routing policy is configured by an `HRAdmin` as ApprovalPolicy rows. Each row names a `min_band_severity` — `BELOW_MIN`, `ABOVE_BAND`, or `EXCEPTION` — a `required_role` of `CompAnalyst`, `DepartmentDirector`, or `VPPeople`, and a `chain_position` of at least 1 that orders the row within generated chains. (Position 0 never appears in policy rows: it is permanently reserved for the hiring manager, as §3.5 describes.) Rows are created `ACTIVE` and may later be deactivated to `INACTIVE`. Severity is numeric under the hood — `IN_BAND` is severity one, `BELOW_MIN` and `ABOVE_BAND` are both severity two, and `EXCEPTION` is severity three — and a row applies to any offer whose band severity is at least the row's `min_band_severity`. A row keyed at `EXCEPTION` therefore catches only exception-band offers, while a row keyed at `BELOW_MIN` or `ABOVE_BAND` catches below-minimum, above-band, and exception offers alike. The policy table is listable with an optional `status` filter; deactivating a missing row draws `ERR_POLICY_NOT_FOUND`.

### 3.3. Constructing the Offer

An offer is assembled by a `Recruiter` or `HiringManager` against an `OPEN` requisition — construction against a requisition in any other status is rejected with `ERR_REQUISITION_NOT_OPEN` — and for a candidate who is not `ARCHIVED`. The payload names the `requisition_id` and `candidate_id`, both of which must resolve to existing resources, and the four term fields: `base_cents` (the offered annual base salary, which must be positive), `bonus_target_pct` (a decimal at or above zero), `equity_shares` (a grant size at or above zero), and `equity_fmv_cents` (the fair market value per share in cents, at or above zero). A hard ceiling applies at the moment of construction: the base may not exceed one hundred twenty-five percent of the requisition's `salary_max_cents`, compared against the unrounded product, or the request fails with `ERR_BASE_EXCEEDS_HARD_CAP`. On success the server stamps `created_by_user_id` from the creator's `X-User-ID` — the anchor for segregation of duties — sets the offer to `DRAFT`, initializes `clearance_posture` to `NOT_STARTED`, `round_count` to zero, `original_submitted_base_cents` and `expires_at` to null, computes the analytics below, flips a `PROSPECT` candidate to `IN_PROCESS`, and appends the `OFFER_CREATED` audit event.

The offer's `band` measures the base against the requisition's band. A base strictly below `salary_min_cents` classifies `BELOW_MIN`. A base at or below `salary_max_cents` — including exactly the minimum or exactly the maximum — classifies `IN_BAND`. A base above the maximum but not above one hundred ten percent of it classifies `ABOVE_BAND`, and a base exactly equal to that one-hundred-ten-percent product is still `ABOVE_BAND`. Anything beyond classifies `EXCEPTION`, subject to the hard cap above. The classification runs at creation, on every terms revision, and whenever a counter is accepted.

Two cost views are computed in a pinned order. First `bonus_target_cents` is the base times `bonus_target_pct`, rounded half up to whole cents. Then the benefits load is thirty percent of the sum of base and bonus, again rounded half up to whole cents. Then annualized equity is `equity_shares` times `equity_fmv_cents` divided across a four-year vest, rounded half up to whole cents. Separately, the perk totals are the sums of `amount_cents` over this offer's non-`VOIDED` perks of each kind. The **cash view**, exposed as `cash_only_annual_cost_cents`, is base plus `bonus_target_cents` plus the sign-on total plus the relocation total — the number recruiters and candidates see, strictly lower than the loaded view whenever bonus, benefits, or equity are non-zero. The **budget view**, exposed as `fully_loaded_annual_cost_cents`, adds annualized equity and the benefits load on top of the cash view. The budget view is the only variant the requisition's `committed_budget_cents` aggregate and the submission budget gate ever consult. The offer's `total_cash_cents` equals the cash view — base plus bonus plus both perk totals — and feeds routing: a sign-on total strictly greater than 1,000,000 cents (ten thousand dollars) demands compensation-analyst review, evaluated on the sign-on total itself before and independently of the tier test, and a `total_cash_cents` of at least 30,000,000 cents (three hundred thousand dollars) — the boundary value included — demands VP review. Both totals are recomputed on creation, terms revision, perk creation or voiding, and counter acceptance, before the approval-chain logic consults them.

Peer equity analytics compare the base to the matching snapshot set defined in §3.2. With fewer than three matching snapshots, both `equity_compa_ratio` and `equity_percentile` are null and both risk flags are false; submission additionally refuses to proceed in this case (§3.5). With at least three, the peer mean is the sum of peer bases divided by the peer count, rounded half up to whole cents; `equity_compa_ratio` is the offer base divided by that mean, carried at four decimal places rounded half up; and `equity_percentile` is the midpoint percentile — take the count of peers strictly below the offer base, add half the count exactly equal to it, divide that sum by the peer count, then multiply by one hundred, with the single rounding half up to an integer from 0 to 100 applied at the end. `equity_compa_risk_flag` is true when the ratio is strictly below 0.85 or strictly above 1.15, and `equity_percentile_risk_flag` is true when the percentile is below 10 or at least 90 — a percentile of exactly 90 flags. The two measures legitimately diverge on skewed peer sets: the ratio is mean-relative, so a single very high incumbent drags the mean up and lowers the ratio, while the percentile is rank-relative and moves only with position. These metrics recompute at creation, on terms revision, on counter acceptance, and again at submission once the peer-count gate passes.

While the offer is in `DRAFT` — or in `RETURNED` after a rejected review — a `Recruiter` or `HiringManager` may revise its terms, supplying `expected_offer_version` plus any subset of `base_cents`, `bonus_target_pct`, `equity_shares`, and `equity_fmv_cents`. A revision changes no status: it applies the changed fields, recomputes the band, both cost views, `total_cash_cents`, and the equity metrics and risk flags, increments the offer's `version` by one, and appends a `TERMS_REVISED` event. The stale-version rejection of §2.7 protects this path.

### 3.4. Sign-On and Relocation Perks

Perks attach to an offer while it is still malleable — in `DRAFT` or `RETURNED` only; an attempt in any other status is rejected with `ERR_PERK_STATE_LOCKED`. A `Recruiter` or `HiringManager` creates each PerkPackage with a `kind` of `SIGN_ON` or `RELOCATION`, a positive `amount_cents`, a `clawback_months` service requirement of at least one month, and a `clawback_variant` of `FULL_CLIFF` or `PRORATED_MONTHLY`. A single sign-on perk may not exceed 2,500,000 cents (twenty-five thousand dollars); a larger amount is rejected with `ERR_SIGNON_EXCEEDS_HARD_CAP`. Each creation starts the perk in `DRAFT`, recomputes the offer's cash and loaded totals, and appends a `PERK_ADDED` event. An offer's perks are listable in creation order, including by the candidate.

From then on the perk's lifecycle rides the offer's. Submission locks `DRAFT` perks to `LOCKED`; a return unlocks them back to `DRAFT`; full chain approval promotes `LOCKED` perks to `APPROVED`; a hire activates `APPROVED` perks to `ACTIVE`. Voiding is the other terminal state: withdrawing an offer voids its `DRAFT` or `LOCKED` perks, declination, expiry, rescission, or requisition-driven auto-withdrawal voids its `APPROVED` perks, and rescinding a hire voids its `ACTIVE` perks. Every void appends a `PERK_VOIDED` event.

Clawback terms become concrete through an advisory quote: given a `months_worked` query value of zero or more, the quote reports `repayment_cents`, the `remaining_months` still outstanding in the clawback window, and the perk's `clawback_variant`, and it never mutates anything. Under `FULL_CLIFF`, departure before completing the full `clawback_months` window repays the entire `amount_cents`; at or beyond the window the repayment is zero — there is no proration. Under `PRORATED_MONTHLY`, the repayment is zero once `months_worked` reaches `clawback_months`, and it is the full `amount_cents` when `months_worked` is zero — a special case that skips the installment math entirely. In between, the calculation is installment-first: the per-month installment is `amount_cents` divided by `clawback_months` rounded half up to whole cents, and the repayment is that rounded installment multiplied by the number of unworked months. The pinned order matters: a 1,000,100-cent perk over a three-month window quoted after one month of service yields an installment of 333,367 cents and a repayment of 666,734 cents, whereas rounding only at the end would yield 666,733 cents — the installment-first result is authoritative.

### 3.5. Submission and the Approval Chain

Submission — by a `Recruiter` or `HiringManager`, from `DRAFT` or from `RETURNED` — is the offer's point of no return into governance, and four gates stand in front of it. The requisition must be `OPEN`, else `ERR_REQUISITION_NOT_OPEN`. At least three InternalEquitySnapshots must match the requisition's `role_level` and `geo_tier`, else `ERR_INSUFFICIENT_PEER_DATA`. The budget gate requires the offer's `fully_loaded_annual_cost_cents` to fit within the requisition's uncommitted balance — `annual_budget_cents` minus `committed_budget_cents` — else `ERR_REQUISITION_BUDGET_EXCEEDED`; because a `DRAFT` or `RETURNED` offer is outside the committed set, it never blocks itself. And the hard cap on base, one hundred twenty-five percent of the band maximum, is enforced again, else `ERR_BASE_EXCEEDS_HARD_CAP`.

A successful submission stamps `original_submitted_base_cents` with the current `base_cents` if that anchor is still null — the anchor is written once and never moves, which makes concession caps cumulative by construction — generates the approval chain, locks `DRAFT` perks to `LOCKED`, recomputes the requisition's `committed_budget_cents` (the offer, now `PENDING_APPROVAL`, joins the counted set), and appends `SUBMITTED`. Resubmission from `RETURNED` first supersedes every pre-existing step of the old chain not already `SUPERSEDED` — including steps that were `APPROVED` — appending a `STEP_SUPERSEDED` event for each, then proceeds exactly as a first submission.

Chain generation is deterministic. Step zero is always the `HiringManager`. Then every `ACTIVE` ApprovalPolicy row whose `min_band_severity` is at or below the offer's band severity contributes its `required_role`: the rows are ordered by `chain_position` ascending with ties broken by `created_at` ascending, and each role is appended only if not already in the chain — deduplication keeps the earliest occurrence. Two escalation rules follow. If the offer's sign-on perk total exceeds 1,000,000 cents, or either equity risk flag is set, the chain must contain `CompAnalyst` — appended after the policy rows if absent. If `total_cash_cents` reaches 30,000,000 cents, the chain must contain `VPPeople` — appended last if absent. The final order is step zero, then the sorted policy rows, then the ensured roles in the fixed order `CompAnalyst` before `VPPeople`; the entries receive `sequence` values from zero upward, each becoming an ApprovalStep whose `offer_id` points back to the offer, with sequence zero starting `ACTIONABLE` and every later step `WAITING`.

A step becomes `ACTIONABLE` when every step with a smaller `sequence` is `APPROVED`, so the chain ratchets forward one decision at a time. The decider — whose `X-User-Role` must equal the step's `required_role`, or who must hold an active delegation for it as described below — records a `decision` of `APPROVED` or `REJECTED` with an optional `note`, which is preserved on the step as `decision_note`. Deciding a step that is not `ACTIONABLE` fails with `ERR_STEP_NOT_ACTIONABLE`. Segregation of duties is absolute: the offer's creator may never decide any step of its chain, and an attempt is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. Every decision stamps `decided_by_user_id`, sets `decided_via_delegation` and `delegation_grant_id` when a grant was used, and writes to the audit trail. An approval appends `STEP_APPROVED`; if a `WAITING` step remains it becomes `ACTIONABLE`, and if none remains the offer itself advances `PENDING_APPROVAL → APPROVED`, promoting `LOCKED` perks to `APPROVED` and appending `APPROVED`. A rejection appends `STEP_REJECTED` and cascades: the offer drops `PENDING_APPROVAL → RETURNED`, every sibling step still `WAITING` or `ACTIONABLE` is superseded with a `STEP_SUPERSEDED` event apiece, `LOCKED` perks fall back to `DRAFT`, the requisition's committed budget releases the offer, and `RETURNED` closes the sequence.

Delegation lets an approver's authority be lent for a bounded window. An `HRAdmin` creates a DelegationGrant naming the `grantor_user_id` whose authority is lent, the `delegate_user_id` receiving it, the `scope_role` it impersonates (`CompAnalyst`, `DepartmentDirector`, or `VPPeople`), and a half-open window from `valid_from` (inclusive) to `valid_until` (exclusive). A grant whose grantor equals its delegate, or whose `valid_until` does not fall after `valid_from`, is rejected with `ERR_GRANT_SELF_DELEGATION`. Two grants for the same delegate and scope role may not overlap in time — though adjacency, one grant's `valid_from` landing exactly on another's `valid_until`, is allowed — and an overlapping creation is rejected with `ERR_GRANT_OVERLAP`. Grants start `ACTIVE`; an `HRAdmin` may revoke one to `REVOKED`, and a grant consulted at decision time once the clock has reached its `valid_until` is lazily marked `EXPIRED`. A delegated decision is honored only while the grant is `ACTIVE` with the delegate's `X-User-ID`, the `scope_role` equal to the step's `required_role`, and the clock inside the window; otherwise the attempt is rejected with `ERR_DELEGATION_NOT_ACTIVE`. Grants are listable with optional `delegate_user_id`, `scope_role`, and `status` filters.

### 3.6. Letters, Extension, and the Candidate's Answer

An `APPROVED` offer becomes a document. A `Recruiter` generates the offer letter — only while the requisition remains `OPEN`, else `ERR_REQUISITION_NOT_OPEN` — and the server renders an OfferLetter whose `body_text` summarizes the pinned terms, whose `sequence` is 1, and whose `pinned_offer_version` records the offer's `version` at generation time. The letter starts `GENERATED`, the offer advances `APPROVED → LETTER_GENERATED`, and `LETTER_GENERATED` is appended. Regeneration from `LETTER_GENERATED` supersedes the currently `GENERATED` letter (`LETTER_SUPERSEDED`) and issues a fresh `GENERATED` letter with the next `sequence` and the offer's then-current version pinned. An offer's letters are listable by `sequence`, including by the candidate.

Extension is the act of putting the letter in the candidate's hands. A `Recruiter` may extend only from `LETTER_GENERATED`, only when the latest letter is `GENERATED` and pinned to the offer's current `version` — a letter rendered stale by intervening change must be regenerated first — and only when the candidate has no other offer in `EXTENDED`, `COUNTERED`, or `ACCEPTED`, else `ERR_CANDIDATE_ACTIVE_OFFER_EXISTS`. Extension sets `expires_at` to the logical clock plus ten days, moves the offer to `EXTENDED`, and appends `EXTENDED`.

From `EXTENDED` (and later `COUNTERED`) the clock governs. Expiry is lazy, per §2.4: any state-changing call — or even a read of the offer — that finds the clock at or past `expires_at` first persists the offer as `EXPIRED` with its full side effects — `APPROVED` perks voided with `PERK_VOIDED` events, the committed budget released, a pending negotiation round withdrawn with `ROUND_WITHDRAWN`, and the `EXPIRED` event appended — and a state-changing call is then rejected with `ERR_OFFER_EXPIRED`. The boundary is exact: a call landing precisely at `expires_at` expires; one second earlier it would have succeeded.

The candidate answers for themselves — every candidate-facing action checks `X-User-ID` against the offer's `candidate_id` and rejects mismatches with `ERR_NOT_RESOURCE_OWNER`. Acceptance from `EXTENDED` moves the offer to `ACCEPTED` and appends `ACCEPTED`. Acceptance is also possible from `COUNTERED`: the candidate takes the originally extended terms, the pending round is abandoned to `WITHDRAWN` with a `ROUND_WITHDRAWN` event, and the same `ACCEPTED` landing follows. Either path runs the lazy expiry check first. Declination requires a `reason` drawn from `COMPETING_OFFER`, `COMPENSATION`, `ROLE_SCOPE`, `LOCATION`, `BENEFITS`, `PERSONAL`, `TIMING`, or `OTHER`, with an optional free-text `detail`; a missing or out-of-enum reason is rejected with `ERR_DECLINATION_REASON_REQUIRED`. The reason is recorded as the offer's `declination_reason`, `APPROVED` perks are voided, the committed budget is released, and `DECLINED` is appended; from `COUNTERED` the pending round is withdrawn as on acceptance. Offers are listable with optional `requisition_id`, `candidate_id`, and `status` filters — a `Candidate` sees only their own offers in any list or read.

An `ACCEPTED` offer is counted in the requisition's committed budget and waits on exactly one thing: contingency clearance.

### 3.7. Negotiation Rounds and Counteroffer Authority

While an offer is `EXTENDED`, a `Recruiter` may record the candidate's counter as a NegotiationRound. The request carries `expected_offer_version` under the rule of §2.7, a positive `proposed_base_cents`, and optionally `proposed_bonus_target_pct` and `proposed_equity_shares`. Two gates apply: the offer's `round_count` — the number of rounds ever created for it, in any status — must be below three, else `ERR_NEGOTIATION_ROUND_LIMIT`; and the proposed base must satisfy the same hard cap as an original base, one hundred twenty-five percent of the band maximum, else `ERR_BASE_EXCEEDS_HARD_CAP`. A recorded round takes `sequence` equal to `round_count` plus one, starts `PROPOSED`, moves the offer `EXTENDED → COUNTERED`, increments the offer's `version` by one, and appends `COUNTER_RECORDED`. The round's `concession_pct` measures the proposed base against the offer's frozen `original_submitted_base_cents` anchor — the difference divided by the anchor, at four decimal places rounded half up — so it reflects every concession already made, not merely this round's.

The decision on a `PROPOSED` round is recorded by a `Recruiter`, `HiringManager`, or `VPPeople` as an `outcome` of `ACCEPTED` or `REJECTED` with an optional `note`, preserved as the round's `decision_note` alongside `decided_by_user_id`; deciding a round no longer `PROPOSED` fails with `ERR_ROUND_NOT_PENDING`. Rejection is unconstrained — any of the three roles may reject at any magnitude — and returns the offer `COUNTERED → EXTENDED` with terms and `expires_at` untouched, the round `REJECTED`, and `COUNTER_REJECTED` appended.

Acceptance is where authority bites. The proposed base may not exceed the anchor by more than the actor's cap: five percent for a `Recruiter`, ten percent for a `HiringManager`, one hundred percent for a `VPPeople`. Formally, the ceiling is the anchor plus the product of the anchor and the cap, that product rounded half up to whole cents before the addition, and a proposal exactly at the ceiling is permitted; anything above is rejected with `ERR_CONCESSION_EXCEEDS_AUTHORITY`. The budget gate is then re-checked against the new terms: the recomputed `fully_loaded_annual_cost_cents` must fit within `annual_budget_cents` minus `committed_budget_cents` plus the offer's own previous fully loaded cost — the offer remains in the counted set, so its old commitment is released as its new one is assessed — else `ERR_REQUISITION_BUDGET_EXCEEDED`. A successful acceptance marks the round `ACCEPTED`, applies the proposed base and any proposed bonus or equity to the offer, recomputes every computed field, increments the offer's `version`, supersedes any `GENERATED` letters with `LETTER_SUPERSEDED` events, recomputes the committed budget, and appends `COUNTER_ACCEPTED`.

Where the offer lands next depends on routing coverage. The approval chain is recomputed from the new terms per §3.5. If every role in the recomputed chain already appeared in the last fully approved chain, the offer moves directly `COUNTERED → APPROVED`. If the recomputed chain introduces a role the approved chain lacked, the offer returns to `PENDING_APPROVAL` and a fresh chain is generated — the old chain, fully decided, is left in place for audit rather than superseded. An offer's rounds are listable by `sequence`.

### 3.8. Contingency Clearance and Hire

Acceptance converts the offer into a contingent hire-in-waiting. A `BackgroundScreener` initiates each ClearanceCheck against an `ACCEPTED` offer with a `kind` of `BACKGROUND` or `REFERENCE`; the check starts `INITIATED`, the offer's clearance posture recomputes, and `CHECK_INITIATED` is appended. One active check per kind is the limit — a second check of the same kind while one exists in `INITIATED`, `IN_PROGRESS`, or `FLAGGED` is rejected with `ERR_DUPLICATE_ACTIVE_CHECK`.

The screener advances a check by naming the target status `to`, with an optional `note` retained as the check's `note` from its latest transition. The declared edges are `INITIATED → IN_PROGRESS`, `IN_PROGRESS → CLEARED`, `IN_PROGRESS → FLAGGED`, `FLAGGED → IN_PROGRESS` (the re-check cycle), and `FLAGGED → FAILED`; any other move — `INITIATED` directly to `CLEARED`, for instance — is rejected with `ERR_CHECK_INVALID_TRANSITION`. Each successful move appends `CHECK_TRANSITIONED` and recomputes the offer's posture. Separately, a `VPPeople` may waive a check in `IN_PROGRESS` or `FLAGGED`, supplying a mandatory `reason`; the check becomes `WAIVED`, `CHECK_WAIVED` is appended, and the posture recomputes. Checks also cancel automatically — `INITIATED`, `IN_PROGRESS`, or `FLAGGED` to `CANCELLED` with a `CHECK_CANCELLED` event each — whenever their offer reaches a negative terminal state.

The offer's `clearance_posture` aggregates its checks: `FAILED` if any check has failed; otherwise `NOT_STARTED` if no checks exist; otherwise `CLEARED` when every check is `CLEARED` or `WAIVED`; otherwise `PENDING`. Two posture resolutions act on an `ACCEPTED` offer immediately. A posture of `CLEARED` hires: the offer moves `ACCEPTED → HIRED`, `APPROVED` perks become `ACTIVE`, the candidate moves to `HIRED`, the requisition's `headcount_filled` is recomputed — closing the requisition at full headcount per §3.1, which in turn auto-withdraws its remaining live offers — and `HIRED` is appended. A posture of `FAILED` rescinds: the offer moves `ACCEPTED → RESCINDED` with `rescind_reason` set to `CONTIGENCY_FAILED`, every in-flight check is cancelled, `APPROVED` perks are voided, the committed budget is released, and `RESCINDED` is appended with the failure as its `detail`.

### 3.9. Rescission, Withdrawal, and Reopening

Beyond the automatic contingency rescission, an offer may be rescinded deliberately by an `HRAdmin` — or by a `HiringManager`, but only on requisitions they own, else `ERR_NOT_RESOURCE_OWNER` — from `LETTER_GENERATED`, `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED`. The request's `reason` must be `RENEG` or `COMPLIANCE_HOLD` (anything else fails request-shape validation with `ERR_INVALID_REQUEST`), and the reason is recorded as `rescind_reason` and as the `RESCINDED` event's `detail`. The unwind depends on where the offer stood. From `LETTER_GENERATED` or `EXTENDED`, `APPROVED` perks are voided and the committed budget released. From `COUNTERED`, the pending round is additionally withdrawn with `ROUND_WITHDRAWN`. From `ACCEPTED`, in-flight checks are additionally cancelled as in the failure cascade. From `HIRED`, `ACTIVE` perks are voided, `headcount_filled` is recomputed downward, a requisition that had closed `FILLED` reopens `CLOSED → OPEN` with `close_reason` cleared, the candidate returns `HIRED → IN_PROCESS`, and the committed budget is released. Every rescission appends `RESCINDED`.

Withdrawal is the gentler, desk-side exit, available to a `Recruiter` or `HiringManager` while the offer is in `DRAFT`, `RETURNED`, or `PENDING_APPROVAL`, with an optional `reason`. From `DRAFT` or `RETURNED` the offer's `DRAFT` perks are voided and `WITHDRAWN` is appended. From `PENDING_APPROVAL` the unwind is deeper: every non-terminal step is superseded with its `STEP_SUPERSEDED` event, `LOCKED` perks are voided, the committed budget is released, and `WITHDRAWN` is appended. Attempting to withdraw from any later status fails with `ERR_INVALID_OFFER_STATE`.

The requisition-level cascade, referenced throughout, works as follows when a requisition closes at full headcount or is cancelled. Every offer of that requisition in `DRAFT`, `RETURNED`, `PENDING_APPROVAL`, `APPROVED`, `LETTER_GENERATED`, `EXTENDED`, or `COUNTERED` transitions to `WITHDRAWN`. For each such offer: every non-terminal ApprovalStep becomes `SUPERSEDED` with a `STEP_SUPERSEDED` event; a `PROPOSED` NegotiationRound becomes `WITHDRAWN` with `ROUND_WITHDRAWN`; every PerkPackage in `DRAFT`, `LOCKED`, or `APPROVED` becomes `VOIDED` with `PERK_VOIDED`; and the offer's own `WITHDRAWN` event carries `detail` of `REQUISITION_FILLED` or `REQUISITION_CANCELLED` according to the cause. The requisition's `committed_budget_cents` is then recomputed. Note what the cascade deliberately spares: offers already `ACCEPTED` or `HIRED` are left standing — unwinding those requires rescission.

`DECLINED`, `EXPIRED`, `RESCINDED`, and `WITHDRAWN` are the offer's terminal states; nothing leaves them. And because every transition, cascade, and decision in this section writes to the offer's audit trail in `sequence` order, the full history of any offer — from `OFFER_CREATED` to its terminal event — is reconstructible from the events log alone.

## 4. Endpoint Definitions

Operations that create a new resource — a requisition, candidate, snapshot, policy row, offer, negotiation round, perk, clearance check, letter, or delegation grant — return `201 Created`. Operations that modify an existing resource or record a decision, transition, or other action against one return `200 OK`. All endpoints are mounted under `/api`; request payloads, computed fields, and side effects are specified per workflow in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | HRAdmin |
| POST | `/api/requisitions` | Create a requisition in `DRAFT` | HiringManager |
| GET | `/api/requisitions` | List requisitions (paginated) | HiringManager, Recruiter, CompAnalyst, FinanceController, DepartmentDirector, VPPeople, HRAdmin |
| GET | `/api/requisitions/{id}` | Get a requisition | HiringManager, Recruiter, CompAnalyst, FinanceController, DepartmentDirector, VPPeople, HRAdmin |
| PATCH | `/api/requisitions/{id}` | Edit a `DRAFT` requisition (OCC) | HiringManager |
| POST | `/api/requisitions/{id}/submit` | Submit for budget review (`DRAFT → BUDGET_REVIEW`) | HiringManager |
| POST | `/api/requisitions/{id}/review-decision` | Approve or return at the current review stage | FinanceController, CompAnalyst |
| POST | `/api/requisitions/{id}/hold` | Pause (`OPEN → PAUSED`) or resume (`PAUSED → OPEN`) | HiringManager |
| POST | `/api/requisitions/{id}/cancel` | Cancel and auto-withdraw non-terminal offers | HiringManager |
| POST | `/api/candidates` | Create a candidate in `PROSPECT` | Recruiter |
| GET | `/api/candidates/{id}` | Get a candidate (Candidate role restricted to self) | Recruiter, HiringManager, CompAnalyst, HRAdmin, Candidate |
| POST | `/api/candidates/{id}/archive` | Archive a candidate with no active offers | Recruiter |
| POST | `/api/equity-snapshots` | Add one incumbent peer data row | CompAnalyst |
| GET | `/api/equity-snapshots` | List peer snapshots (paginated) | CompAnalyst, Recruiter, HiringManager, HRAdmin |
| GET | `/api/equity-snapshots/{id}` | Get one peer snapshot | CompAnalyst, Recruiter, HiringManager, HRAdmin |
| POST | `/api/approval-policies` | Create an `ACTIVE` routing policy row | HRAdmin |
| GET | `/api/approval-policies` | List policy rows | HRAdmin, CompAnalyst, VPPeople, DepartmentDirector, Recruiter, HiringManager |
| POST | `/api/approval-policies/{id}/deactivate` | Deactivate a policy row | HRAdmin |
| POST | `/api/offers` | Construct an offer in `DRAFT` with computed band, costs, and equity metrics | Recruiter, HiringManager |
| GET | `/api/offers` | List offers (paginated; Candidate sees only own) | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin, Candidate |
| GET | `/api/offers/{id}` | Get an offer (Candidate restricted to own; lazy expiry may persist `EXPIRED`) | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin, Candidate |
| PATCH | `/api/offers/{id}` | Revise offer terms while `DRAFT` or `RETURNED` (OCC) | Recruiter, HiringManager |
| POST | `/api/offers/{id}/submit` | Submit for approval; generates the routed ApprovalStep chain | Recruiter, HiringManager |
| POST | `/api/offers/{id}/withdraw` | Withdraw while `DRAFT`, `RETURNED`, or `PENDING_APPROVAL` | Recruiter, HiringManager |
| POST | `/api/offers/{id}/extend` | Extend the current letter to the candidate (ten-day expiry) | Recruiter |
| POST | `/api/offers/{id}/accept` | Candidate accepts (from `EXTENDED`, or from `COUNTERED` abandoning the pending round) | Candidate |
| POST | `/api/offers/{id}/decline` | Candidate declines with mandatory reason | Candidate |
| POST | `/api/offers/{id}/rescind` | Rescind from `LETTER_GENERATED`/`EXTENDED`/`COUNTERED`/`ACCEPTED`/`HIRED` | HRAdmin, HiringManager |
| GET | `/api/offers/{id}/approval-steps` | List an offer's approval steps by `sequence` | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin |
| POST | `/api/approval-steps/{id}/decide` | Approve or reject the `ACTIONABLE` step; role match or active delegation; SoD enforced | HiringManager, CompAnalyst, DepartmentDirector, VPPeople |
| POST | `/api/offers/{id}/negotiation-rounds` | Record a candidate counter while `EXTENDED` (OCC; at most three rounds) | Recruiter |
| GET | `/api/offers/{id}/negotiation-rounds` | List an offer's negotiation rounds by `sequence` | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin |
| POST | `/api/negotiation-rounds/{id}/decision` | Accept (authority-capped, may re-route) or reject (back to `EXTENDED`) | Recruiter, HiringManager, VPPeople |
| POST | `/api/offers/{id}/perks` | Add a sign-on or relocation perk with clawback terms while `DRAFT`/`RETURNED` | Recruiter, HiringManager |
| GET | `/api/offers/{id}/perks` | List an offer's perks in creation order | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin, Candidate |
| GET | `/api/perks/{id}/clawback-quote` | Advisory clawback repayment quote for a given `months_worked` (never mutates) | Recruiter, HiringManager, HRAdmin, VPPeople |
| POST | `/api/offers/{id}/clearance-checks` | Initiate a `BACKGROUND` or `REFERENCE` check on an `ACCEPTED` offer | BackgroundScreener |
| GET | `/api/offers/{id}/clearance-checks` | List an offer's clearance checks | Recruiter, HiringManager, HRAdmin, VPPeople, BackgroundScreener |
| POST | `/api/clearance-checks/{id}/transition` | Advance a check per the clearance machine (re-check cycle supported) | BackgroundScreener |
| POST | `/api/clearance-checks/{id}/waive` | Waive an `IN_PROGRESS` or `FLAGGED` check with mandatory reason | VPPeople |
| POST | `/api/offers/{id}/letters` | Generate (or regenerate, superseding) the letter pinned to the current offer version | Recruiter |
| GET | `/api/offers/{id}/letters` | List an offer's letters by `sequence` | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin, Candidate |
| GET | `/api/offers/{id}/events` | Append-only audit log for an offer, by `sequence` (paginated) | Recruiter, HiringManager, CompAnalyst, DepartmentDirector, VPPeople, HRAdmin, BackgroundScreener |
| POST | `/api/delegation-grants` | Delegate an approver role's authority for a half-open window | HRAdmin |
| GET | `/api/delegation-grants` | List delegation grants (paginated) | HRAdmin, VPPeople |
| GET | `/api/delegation-grants/{id}` | Get a delegation grant | HRAdmin |
| POST | `/api/delegation-grants/{id}/revoke` | Revoke an `ACTIVE` grant | HRAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_CANDIDATE_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_APPROVAL_STEP_NOT_FOUND` | 404 Not Found |
| `ERR_NEGOTIATION_ROUND_NOT_FOUND` | 404 Not Found |
| `ERR_PERK_NOT_FOUND` | 404 Not Found |
| `ERR_CLEARANCE_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_DELEGATION_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_INVALID_STATE` | 409 Conflict |
| `ERR_REQUISITION_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_OFFER_STATE` | 409 Conflict |
| `ERR_STEP_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_ROUND_NOT_PENDING` | 409 Conflict |
| `ERR_CHECK_INVALID_TRANSITION` | 409 Conflict |
| `ERR_CANDIDATE_NOT_HIRABLE` | 409 Conflict |
| `ERR_CANDIDATE_HAS_ACTIVE_OFFER` | 409 Conflict |
| `ERR_STALE_OFFER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REQUISITION_VERSION` | 412 Precondition Failed |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_INSUFFICIENT_PEER_DATA` | 422 Unprocessable Entity |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 409 Conflict |
| `ERR_CANDIDATE_ACTIVE_OFFER_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CHECK` | 409 Conflict |
| `ERR_PERK_STATE_LOCKED` | 409 Conflict |
| `ERR_GRANT_OVERLAP` | 409 Conflict |
| `ERR_GRANT_SELF_DELEGATION` | 422 Unprocessable Entity |
| `ERR_DECLINATION_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CANDIDATE_EMAIL_EXISTS` | 409 Conflict |
| `ERR_SALARY_RANGE_INVALID` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_DELEGATION_NOT_ACTIVE` | 403 Forbidden |
| `ERR_REQUISITION_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BASE_EXCEEDS_HARD_CAP` | 422 Unprocessable Entity |
| `ERR_CONCESSION_EXCEEDS_AUTHORITY` | 422 Unprocessable Entity |
| `ERR_SIGNON_EXCEEDS_HARD_CAP` | 422 Unprocessable Entity |
