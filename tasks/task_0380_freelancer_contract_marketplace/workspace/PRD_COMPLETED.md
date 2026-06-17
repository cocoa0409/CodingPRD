# Freelancer Contract Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Freelancer Contract Marketplace API, a back-end platform that brokers contract work between buyers and sellers of services in the style of Upwork. The platform exists to make a fundamentally adversarial transaction — one party paying in advance for work that has not yet been delivered — safe for both sides. It does this by holding money in escrow, by giving each side a structured negotiation channel before any commitment is made, and by routing genuine disagreements to a neutral arbitrator rather than letting either party seize the funds unilaterally.

The lifecycle the system governs is long and multi-stage. A buyer publishes a job, sellers bid on it, the two sides may counter back and forth until they agree, and the winning bid becomes a contract with a written statement of work. From there the contract is broken into milestones; each milestone is funded into escrow from the buyer's prepaid wallet, worked, submitted, and then either approved and released to the seller or escalated into a dispute. Money that leaves escrow is taxed by a platform fee that varies with the seller's track record, paid out subject to having tax paperwork on file, and ultimately aggregated into year-end 1099 tax reporting. Because escrow movements and reputation are sensitive to ordering and to concurrent edits, the platform layers optimistic concurrency control over the funding and release operations and recomputes derived reputation and fee tiers as a side effect of the events that change them.

The reader should treat every monetary figure as an integer count of cents and every reputation or match figure as a bounded score. The sections that follow define the global contract first, then the business workflows where the bulk of the domain rules live, and finally the endpoint and error reference tables.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as `Client`, `Freelancer`, `Arbitrator`, and `PlatformAdmin`. When a caller presents a role that is syntactically valid but not permitted to perform the requested operation — or presents an entity-backed role whose identity does not own the targeted resource — the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of the four roles are entity-backed, and two are opaque operators. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` — for example a `JobPosting` through its `client_id` or a `Contract` through its `client_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Freelancer`, `X-User-ID` is the `id` of the acting `Freelancer`; ownership checks on any resource that references a `Freelancer` — a `Proposal` through its `freelancer_id`, a `Contract` through its `freelancer_id`, a `Payout` through its `freelancer_id`, or a `TimeLog` through its `freelancer_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Arbitrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

A `Client` is the buyer of work: it owns its job postings and contracts, funds escrow, and approves and releases milestones. A `Freelancer` is the seller: it submits proposals, logs hours, submits milestone work, and receives payouts. An `Arbitrator` is a neutral third party who takes disputes under arbitration and resolves them, but can never fund, release, or otherwise move money on its own behalf. A `PlatformAdmin` is the platform operator who provisions client and freelancer accounts, settles payouts, generates 1099 tax records, and performs administrative wallet deposits.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter counts how many leading items to skip and defaults to 0. Both parameters, when supplied, must parse as integers within their bounds — a `limit` that is non-integer or outside 1 through 100, or an `offset` that is non-integer or negative, is rejected with `ERR_INVALID_REQUEST`.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order — that is, oldest first. The one deliberate exception is the ranked-proposals read described in §3, which sorts by a computed match score rather than by creation time.

Every list-based response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. The `total_count` is the size of the full filtered result set before the offset and limit window is applied, and `has_more` is true exactly when `offset` plus `limit` is strictly less than that `total_count` — that is, when further items remain beyond the returned page.

### 2.4. Common Resource Properties and Identity

Most resources in this system carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix, serving as identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, and it is refreshed on every mutation. The `version` field is an integer that begins at its initial value of 1 and increments by one on every modification to the resource; it underpins the optimistic concurrency control described below.

Two entity types are deliberately leaner. An `EscrowTransaction` is an append-only ledger row: it carries only `id` and `created_at` and has neither an `updated_at` nor a `version`, because ledger rows are never modified after insertion. A `TaxRecord` is likewise a generated artifact carrying only `id` and `created_at`, with no `updated_at` and no `version`. For every other entity — `Client`, `Freelancer`, `JobPosting`, `Proposal`, `Contract`, `Milestone`, `TimeLog`, `Dispute`, `Payout`, and `Review` — all four common fields are present.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths address a child resource through one or more parent identifiers, such as a milestone reached through its contract or a timelog reached through its contract. For any such request the system validates the identifiers strictly left to right and rejects on the first one that does not resolve to an existing resource. A request naming a milestone under a non-existent contract is rejected with `ERR_CONTRACT_NOT_FOUND` before the milestone is ever looked up; only once the contract resolves does a bad milestone identifier surface as `ERR_MILESTONE_NOT_FOUND`. Each entity has its own not-found code in this family: `ERR_CLIENT_NOT_FOUND`, `ERR_FREELANCER_NOT_FOUND`, `ERR_JOB_POSTING_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_TIMELOG_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, and `ERR_TAX_RECORD_NOT_FOUND`. Identifiers passed in the request body are resolved the same way and in the same parent-before-child order.

### 2.6. Validation Ordering

When a single operation is guarded by several checks, the platform evaluates them in a fixed precedence so that the rejection a caller receives is deterministic. The order is: first, authentication — the presence and well-formedness of the two user-context headers (`ERR_MISSING_USER_CONTEXT`); second, role authorization — whether the declared role is one of those permitted to invoke this operation at all (`ERR_FORBIDDEN_ROLE`); third, existence of every path and body identifier, resolved left to right (the not-found family of §2.5); fourth, structural request validity — required fields present and well-typed, enums in range, ratings within one through five, and amounts and minute values within their declared bounds (`ERR_INVALID_REQUEST`). Entity-backed ownership — whether the acting `X-User-ID` actually owns the specific resource being acted on — is a distinct check that, because it must inspect the resolved resource, is evaluated only after that resource's existence has been established; an ownership failure surfaces as `ERR_FORBIDDEN_ROLE`, so a caller who neither owns nor can resolve a target receives the not-found code rather than the forbidden code. Only after these pass does the system reach the domain-specific checks — skill coverage, resource state, cross-entity state, turn alternation, time-log geometry, award range, open-item gating, wallet sufficiency, and concurrency — which are described in the workflows of §3 and whose relative ordering is noted there.

### 2.7. Monetary and Score Precision

All amounts in the system are integer counts of cents and are never rounded, because they are already whole cents; wallet debits and credits, escrow movements, and ledger sums are exact. Where a calculation derives cents from a rate — the platform fee and the hourly milestone cap — the result is truncated downward to a whole number of cents (floor), never rounded up, and the intermediate rate arithmetic is performed in IEEE-754 double precision. The reputation score is the one figure carried to two decimal places, rounded half up. The match score used to rank proposals is rounded to four decimal places purely for the purpose of establishing a stable ordering.

### 2.8. Optimistic Concurrency Control on Escrow Movements

Two operations move escrow against a contract and therefore advance that contract's `version`: funding a milestone and releasing an approved milestone. Both are protected by optimistic concurrency control. A fund request must carry `expected_contract_version` and that value must equal the target contract's current `version`; if another writer has advanced the contract's version since the client last read it — because some earlier fund or release already moved escrow — the fund is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), and the client is thereby prevented from acting on a stale view of the contract's escrow state. A release request likewise must carry `expected_contract_version` matching the contract's current `version`, and a stale value is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) for the same reason. The `expected_contract_version` field is a required input on both of these operations. No other endpoint takes a version field, and operations that are not funding or releasing perform no such check.

### 2.9. Escrow Conservation and the Wallet Invariant

The escrow ledger is the source of truth for every cent that moves, and the platform maintains a conservation law over it. An `EscrowTransaction` has a `txn_type` that is one of three values — `FUND`, `RELEASE`, or `REFUND` — each recording a positive `amount_cents`, and a `status` that is one of `HELD`, `SETTLED`, or `REVERSED`. A `FUND` row is written `HELD`. It is moved to `SETTLED` whenever the milestone is released — the standard approval release and any dispute resolution with a non-zero award, including a `SPLIT` where part of the held escrow is refunded, all settle the `FUND` row. It is moved to `REVERSED` instead only when the milestone's held escrow is fully returned to the buyer with no release at all — a dispute resolved entirely in the client's favor (award zero) or a contract termination. `RELEASE` and `REFUND` rows are always written directly in `SETTLED`. For any one milestone, the cents still held in escrow equal the sum of `FUND` amounts whose status is `HELD`; the gross cents released equal the sum of `RELEASE` amounts whose status is `SETTLED`; and the cents refunded to the buyer equal the sum of `REFUND` amounts whose status is `SETTLED`. The conservation guarantee is that, for a milestone, the sum of all of its `FUND` amounts regardless of status equals its released gross plus its refunded cents plus the cents still held. A milestone's `funded_cents` is exactly the held escrow — the sum of its `FUND` amounts minus its `REFUND` amounts.

The wallet side carries a matching invariant for each `Client`. Every `FUND` debits the client's `wallet_balance_cents` by exactly the funded amount, every `REFUND` credits the wallet by exactly the refunded amount, and a `RELEASE` never touches the wallet because released money flows from escrow directly to the freelancer. Consequently a client's `lifetime_funded_cents` — the cumulative cents ever moved from wallet into escrow — equals the client's current `escrow_held_cents` plus the total released gross across that client's milestones plus the total refunded back to the wallet across that client's milestones. The `wallet_balance_cents` may never go negative.

### 2.10. Hierarchical Consistency and Derived Field Maintenance

Several fields are computed from the state of related rows rather than supplied by a caller, and the platform keeps them current as the underlying events occur. On a `Client`, `escrow_held_cents`, `lifetime_funded_cents`, and the `ACTIVE`-or-`SUSPENDED` `status` are system-maintained. On a `JobPosting`, `proposal_count` reflects the number of non-terminal proposals and `awarded_proposal_id` is set when the posting is awarded and is otherwise null. On a `Contract`, `total_released_cents`, `total_refunded_cents`, `open_milestone_count`, and `open_dispute_count` are recomputed from the contract's children. On a `Milestone`, `funded_cents`, `released_gross_cents`, and `refunded_cents` follow the escrow ledger. On a `Freelancer`, `lifetime_earnings_cents`, `lifetime_gross_billed_cents`, `completed_contract_count`, `dispute_loss_count`, `reputation_score`, and `fee_tier` are all derived. Whenever an operation changes one of these derived fields on a versioned entity, that change is itself a mutation: it refreshes the entity's `updated_at` and increments its `version`. The platform may also transition a parent or child resource on its own, without an explicit client request against that specific resource, when the state machine's preconditions for an automatic transition are met — for example a posting closing when its contract activates, or sibling proposals being declined when one is accepted.

## 3. Business Logic & Workflows

### 3.1. Accounts, Wallets, and Reputation

The platform's two principals are provisioned by a `PlatformAdmin`. Creating a `Client` takes a `display_name` and an `email` that is unique among clients; the new client opens with `status` of `ACTIVE` and a `wallet_balance_cents` of zero. Creating a `Freelancer` takes a `display_name`, an `email` unique among freelancers, a required `skills` array of tag strings, and an optional `tax_id_on_file` flag indicating whether a W-9 or TIN is on record; when omitted the flag defaults to false. The uniqueness constraint is scoped to each principal type independently, and an attempt to create a client or freelancer with an `email` already used by an existing record of the same type is rejected with `ERR_INVALID_REQUEST`, the catalogue carrying no dedicated duplicate-email code. A new freelancer opens `ACTIVE` with every lifetime field at zero and a `reputation_score` of zero. A freelancer may later revise its own profile, supplying a new `skills` array or toggling `tax_id_on_file`; setting that flag true is significant because it unblocks any payouts that were previously held for want of tax paperwork, as the payout workflow describes.

A client's prepaid balance is topped up through an administrative deposit that adds a supplied `amount_cents` (which must be at least 1) to `wallet_balance_cents`. This deposit may be performed by a `PlatformAdmin` or by the owning `Client`. The client and freelancer list endpoints each accept an optional `email` query parameter that, when present, narrows the result to records whose `email` matches it exactly before pagination is applied.

The freelancer's standing is captured by a weighted reputation score on a zero-to-one-hundred scale, recomputed whenever a contract completes, whenever a disputed milestone is refunded against the freelancer, whenever a payout is paid, and whenever a dispute resolves in the client's favor or as a split. The computation works from three inputs: the freelancer's count of completed contracts, the count of disputes lost (resolved in the client's favor or split), and the average of the star ratings on client-authored reviews for that freelancer, treated as zero when there are no such reviews. The total number of resolved outcomes is the sum of the completed count and the lost count. The completion rate is the completed count divided by that total of outcomes, and is taken as zero when there are no outcomes at all. The rating factor is the average rating divided by five, and is zero when there are no reviews. A raw figure is formed as the completion rate weighted at six tenths plus the rating factor weighted at four tenths. An acute penalty is then computed as the lost count multiplied by four, but never more than forty. The reputation score is the raw figure multiplied by one hundred, less that acute penalty, clamped to lie within zero and one hundred, and rounded half up to two decimal places. A brand-new freelancer with no outcomes and no reviews has a reputation score of exactly 0.0.

A freelancer's `fee_tier` is one of `TIER_A`, `TIER_B`, or `TIER_C` and is derived from cumulative earnings as the fee workflow in §3.6 explains. The `status` of either principal is `ACTIVE` or `SUSPENDED`.

### 3.2. Posting Work and Negotiating Proposals

A `Client` opens the marketplace loop by publishing a `JobPosting`, supplying the `client_id` that owns it, a `title`, a `billing_type` of either `FIXED` or `HOURLY` that pins how every contract under the posting will bill, a `budget_cents` that advertises the fixed budget or gives per-hour context and must be at least 100, and a `required_skills` array of skill tags. The posting opens in `OPEN` status. Postings can be listed, optionally filtered by `client_id` or by `status`, and a client's own postings are reachable as a list keyed on the owning client.

A `Freelancer` bids by submitting a `Proposal` that names the `job_posting_id` being bid on, the `freelancer_id` bidding, a `bid_amount_cents` that is the total bid for a fixed posting or the offered hourly rate in cents for an hourly posting and must be at least 1, and a `cover_letter`. Before a proposal is accepted the system requires that the freelancer's `skills` cover every tag in the posting's `required_skills`; a proposal whose freelancer does not cover all required skills is rejected with `ERR_SKILLS_NOT_COVERED`. A new proposal opens in `SUBMITTED` status with `last_actor` set to `FREELANCER`, a `round_count` of zero, and the very first proposal on a posting moves that posting from `OPEN` to `UNDER_REVIEW` while bumping its `proposal_count` to one.

Negotiation is a turn-taking cycle. Either side may issue a counter-offer, supplying an `actor_role` and a new `bid_amount_cents`; this drives the proposal into `COUNTERED` status from either `SUBMITTED` or `COUNTERED`, overwrites the live `bid_amount_cents` with the new offer, increments `round_count` by one, and flips `last_actor` to the party that just acted. A counter is permitted only while the posting is `OPEN` or `UNDER_REVIEW`, only while `round_count` is below the ceiling of five rounds, and only when the acting party is the opposite of the proposal's current `last_actor` so that turns strictly alternate. A counter against a proposal that is no longer live — one that has already reached a terminal state — or one whose posting is no longer `OPEN` or `UNDER_REVIEW` is rejected with `ERR_INVALID_PROPOSAL_STATE`, which is checked before the turn and round-ceiling rules; a counter that violates the turn rule or that has reached the five-round ceiling is rejected with `ERR_NOT_YOUR_TURN`. Because a proposal can cycle from `COUNTERED` back to `COUNTERED` many times, the negotiation may run for several rounds before either side settles.

Acceptance ends the negotiation. Supplying an `actor_role`, a party accepts the live offer; this is permitted from `SUBMITTED` or `COUNTERED`, only while the posting is `OPEN` or `UNDER_REVIEW`, and only when the acting party is the opposite of `last_actor`, because a party may never accept its own live offer — an attempt to do so is rejected with `ERR_NOT_YOUR_TURN`. An accept against a proposal that is no longer in `SUBMITTED` or `COUNTERED`, or whose posting is no longer `OPEN` or `UNDER_REVIEW`, is rejected with `ERR_INVALID_PROPOSAL_STATE` (checked before the own-offer rule); likewise a `decline` or `withdraw` against a proposal not in `SUBMITTED` or `COUNTERED` is rejected with `ERR_INVALID_PROPOSAL_STATE`. Acceptance moves the proposal to `ACCEPTED` and cascades widely: the posting transitions to `AWARDED` with its `awarded_proposal_id` set to the accepted proposal, every sibling proposal still in `SUBMITTED` or `COUNTERED` is moved to `DECLINED`, and a new `Contract` is created in `DRAFT` carrying the `billing_type` and the agreed amount drawn from this proposal. The accept response body is the now-`ACCEPTED` proposal object itself, not the freshly drafted contract; the contract is discovered separately through the contract lists, matched by its `proposal_id` provenance pointer. A `Client` may instead `decline` a single proposal, moving it to `DECLINED` and recomputing the posting's `proposal_count`. A `Freelancer` may `withdraw` its own proposal — permitted only for the freelancer that owns it — moving it to `WITHDRAWN` and recomputing the count. A proposal may also be declined by the system as part of a sibling-award or posting-cancel cascade. The terminal proposal states are `ACCEPTED`, `DECLINED`, and `WITHDRAWN`.

A `Client` may cancel a posting while it is `OPEN` or `UNDER_REVIEW`; cancellation moves it to `CANCELLED` and declines every proposal still in `SUBMITTED` or `COUNTERED`. A cancel attempt against a posting in any other state is rejected with `ERR_INVALID_CONTRACT_STATE`. The terminal posting states are `CLOSED` and `CANCELLED`. A posting that has been awarded sits in `AWARDED` until its contract activates, at which point it closes.

For a client weighing live bids, the platform offers a server-side ranking of the still-active proposals on a posting — those in `SUBMITTED` or `COUNTERED`, with terminal proposals excluded. Each candidate is scored on three factors. Skill coverage is the count of the posting's `required_skills` that appear in the freelancer's `skills`, divided by the greater of one and the number of required skills. The reputation factor is the freelancer's `reputation_score` divided by one hundred. The price factor is the posting's `budget_cents` divided by the greater of one and the proposal's `bid_amount_cents`, clamped to lie between zero and one. The match figure is skill coverage weighted at one half, plus the reputation factor weighted at three tenths, plus the price factor weighted at two tenths. Candidates are ranked from highest match to lowest, the match figure being computed to four decimal places for ordering, and ties are broken by `created_at` ascending — never by `id`.

### 3.3. Activating Contracts and Building Milestones

When a proposal is accepted, the resulting `Contract` is born in `DRAFT`. It copies `client_id` from the posting, copies `freelancer_id` and the proposal's bid into its `agreed_amount_cents`, and records the `proposal_id` it was created from as a one-to-one provenance pointer that is reachable forward from the proposal's accept response. The `billing_type` is copied from the posting. For a fixed contract `agreed_amount_cents` is the total contract value; for an hourly contract it is the agreed hourly rate in cents.

A `Client` activates the contract by supplying the `sow_text` — the statement of work prose — and, for hourly work, an optional `hourly_cap_hours` that nominally describes a per-UTC-calendar-day billable-hours limit for the contract (this cap is null for fixed contracts, and any value supplied on a fixed contract is ignored and left null). The value may be supplied as an integer or a fractional number and is recorded verbatim, but it is not enforced as a gate on time-logging or any other operation: the only daily ceiling the platform actually enforces is the global 720-minute cross-contract cap described in §3.4. Activation is permitted only from `DRAFT` and only when `sow_text` is provided; it moves the contract to `ACTIVE` and, as a cross-entity effect, closes the awarded posting by moving it to `CLOSED`. An attempt to activate from any state other than `DRAFT` is an invalid contract state and is rejected with `ERR_INVALID_CONTRACT_STATE`.

Within an `ACTIVE` contract a `Client` builds `Milestone` deliverables, each supplied with a `title`, an `amount_cents`, and an `ordinal` that fixes the one-based sequence position (it must be at least 1) and must be unique within the contract. Building a milestone requires the contract to be `ACTIVE`, checked after the structural field validation but before the ordinal-uniqueness check: a milestone create against a contract that is not `ACTIVE` is rejected with `ERR_INVALID_CONTRACT_STATE`, and a repeated ordinal on an active contract is rejected with `ERR_DUPLICATE_MILESTONE_ORDINAL`. For a fixed milestone the `amount_cents` is the escrow sum to be funded and must be at least 100; for an hourly milestone the amount is not supplied directly (any `amount_cents` in the body is ignored, the milestone opening at zero) but is recomputed from verified time, as §3.4 describes. A milestone opens in `DRAFT`. Its lifecycle runs through `FUNDED`, `SUBMITTED`, then a fork to `APPROVED` or `DISPUTED`, and terminates in `RELEASED`, `REFUNDED`, or `CANCELLED`. The system tracks `funded_cents`, `released_gross_cents`, and `refunded_cents` against the escrow ledger as those events land.

The contract carries running aggregates: `total_released_cents` is the gross released across its milestones, `total_refunded_cents` is the escrow refunded to the client, `open_milestone_count` counts milestones not yet in a terminal state, and `open_dispute_count` counts non-terminal disputes on the contract.

### 3.4. Hourly Time-Tracking and Verification

On an `HOURLY` contract a `Freelancer` records work by logging time against a milestone. A `TimeLog` is created with the `milestone_id` it accrues to, a `work_date` as a UTC calendar date in year-month-day form, a `start_minute` and an `end_minute` measured as minutes from midnight UTC on that date, and a `memo` describing the work. The contract this log bills is named by its `contract_id`, and the working freelancer is denormalized onto the log as `freelancer_id`, copied from the contract for the daily-cap aggregate and reachable through the contract and milestone time-log lists. The `start_minute` lies in the range 0 through 1439; the `end_minute` lies in the range 1 through 1440, must be strictly greater than `start_minute`, and defines a half-open interval that includes the start minute but excludes the end minute. The system computes `billable_minutes` as the end minute minus the start minute. A new log opens in `LOGGED` status; its terminal states are `VERIFIED` and `REJECTED`. The contract-scoped time-log list accepts optional `milestone_id` and `work_date` query parameters that each narrow the result to logs whose corresponding field matches exactly before pagination, and the contract-scoped escrow-transaction list likewise accepts an optional `milestone_id` filter.

Two geometric checks guard time-log creation, and they use different semantics. The first is a same-milestone overlap check: the new half-open interval on `work_date` must not intersect any existing `LOGGED` or `VERIFIED` interval on the same milestone and the same date. Adjacency is explicitly allowed — an interval ending at minute 120 and another beginning at minute 120 do not overlap, because touching endpoints are permitted. A violation is rejected with `ERR_TIMELOG_OVERLAP`. The second is a cross-contract daily cap: summing the freelancer's `VERIFIED` and `LOGGED` billable minutes across all of that freelancer's contracts on the same `work_date`, plus the minutes of the new interval, must not exceed the global daily ceiling of 720 minutes, which is twelve hours. This is a running-total capacity check rather than a pairwise comparison, and a breach is rejected with `ERR_DAILY_HOURS_CAP_EXCEEDED`.

A `Client` reviews each logged interval and either verifies or rejects it. Verifying requires the log to be in `LOGGED` and the parent contract to be `ACTIVE`; the log-state check is applied first, so an attempt to verify a log that is not in `LOGGED` is rejected with `ERR_INVALID_TIMELOG_STATE`, and only when the log is `LOGGED` but the contract is not `ACTIVE` is the verify rejected with `ERR_CONTRACT_NOT_ACTIVE`. Verification moves the log to `VERIFIED` and recomputes the milestone's `amount_cents`. That recomputation rounds per log and then sums: for each `VERIFIED` time log on the milestone the per-log cents are the billable minutes divided by sixty, multiplied by the contract's agreed hourly rate, and floored to a whole cent; the milestone's `amount_cents` is the sum of those per-log figures. Because each log is floored independently before summing, the order of summation does not matter. If the milestone has no `VERIFIED` logs at all, its `amount_cents` is zero, and a milestone with zero verified time cannot be submitted. Rejecting a log requires it to be in `LOGGED`, moves it to `REJECTED`, and has no further effect; an attempt to reject a log that is not in `LOGGED` is likewise rejected with `ERR_INVALID_TIMELOG_STATE`.

### 3.5. Funding, Submission, Approval, and the Release Path

Funding moves a milestone from `DRAFT` to `FUNDED`. A `Client` funds escrow on a milestone, supplying `expected_contract_version`. Funding is permitted only when the milestone itself is in `DRAFT`, only when the parent contract is `ACTIVE` — otherwise the operation is rejected with `ERR_CONTRACT_NOT_ACTIVE` — only when the client's `wallet_balance_cents` is at least the milestone's `amount_cents`, and only when `expected_contract_version` matches the contract's current `version`. These domain checks are applied in exactly that order, so a milestone not in `DRAFT` is rejected with `ERR_INVALID_MILESTONE_STATE` before the contract-state check, the contract-state check precedes the wallet check, and the wallet check precedes the version check. An insufficient wallet is rejected with `ERR_INSUFFICIENT_WALLET`, and a stale version with `ERR_STALE_CONTRACT_VERSION`. On success the system debits the client's `wallet_balance_cents` by `amount_cents`, writes a `FUND` `EscrowTransaction` in `HELD` status setting the milestone's `funded_cents` to `amount_cents`, and increments the contract's `version` by one.

Once a milestone is `FUNDED`, the `Freelancer` submits the deliverable. Submission is permitted only when the milestone is `FUNDED` and the contract is `ACTIVE`, and for an hourly milestone it additionally requires that at least one `VERIFIED` time log exists for the milestone; these checks are applied in that order, so a milestone not in `FUNDED` is rejected with `ERR_INVALID_MILESTONE_STATE`, a contract that is not `ACTIVE` with `ERR_CONTRACT_NOT_ACTIVE`, and a submission attempt on an hourly milestone with no verified logs is rejected with `ERR_NO_VERIFIED_TIMELOGS`. Submission moves the milestone to `SUBMITTED`, which is the fork point: from here the milestone branches either to `APPROVED` or to `DISPUTED`.

On the approval branch, a `Client` approves a `SUBMITTED` milestone, moving it to `APPROVED`; approving a milestone not in `SUBMITTED` is rejected with `ERR_INVALID_MILESTONE_STATE`. The client then releases the `APPROVED` milestone, again supplying `expected_contract_version`. The milestone-state check is applied before the version check, so a release attempt on a milestone not in `APPROVED` is rejected with `ERR_INVALID_MILESTONE_STATE` first, and only on an `APPROVED` milestone does a supplied `expected_contract_version` that fails to match the contract's current `version` reject the release with `ERR_STALE_CONTRACT_VERSION`. Release is the money event: a `RELEASE` `EscrowTransaction` is written for the full `funded_cents` in `SETTLED` status and the milestone's `released_gross_cents` is set to that full funded amount, the milestone's originating `FUND` transaction moves to `SETTLED`, the milestone moves to `RELEASED`, a `Payout` is created with `gross_cents` equal to the released gross and its platform fee and net computed, the freelancer's `lifetime_gross_billed_cents` increases by the gross, and the contract's `version` increments by one. Creating that payout also re-derives and re-stores the freelancer's `reputation_score` and `fee_tier`, which refreshes the freelancer's `updated_at` and increments its `version` even though those two values are typically unchanged at this point because none of their inputs have yet moved. The freelancer's `lifetime_earnings_cents` increases by the net only when the resulting payout is actually paid, which in turn recomputes the freelancer's `fee_tier` and `reputation_score`.

### 3.6. Payouts, Platform Fees, and Tax Identity

Every release of money to a freelancer creates a `Payout`. The payout names the `freelancer_id` payee and the `milestone_id` whose release it settles, records `gross_cents` equal to the milestone's released gross at creation, derives `platform_fee_cents` and `net_cents`, and stamps the `tax_year` as the UTC year of the release. The net is simply the gross less the platform fee. A payout opens in `PENDING`; its other states are `PAID` and `HELD_NO_TAX_ID`. The per-freelancer payout list accepts an optional `tax_year` query parameter that, when present, restricts the result to payouts stamped with that `tax_year` before pagination is applied. A payout references no `client_id`, so a `Client` reading a single payout is granted access only when the payout settles a milestone on one of that client's own contracts — resolved by walking the payout's `milestone_id` to its milestone, then to that milestone's contract, and comparing the contract's `client_id` to `X-User-ID`; a `Client` requesting a payout outside its own contracts is rejected with `ERR_FORBIDDEN_ROLE`.

The platform fee is tiered on the freelancer's track record, and the order of evaluation is fixed so the result is well-defined. The fee is keyed on the freelancer's cumulative net earnings as they stood before this payout is added. A base rate is chosen first: if those pre-payout lifetime earnings are below fifty thousand dollars — five million cents — the base rate is twenty percent, which is `TIER_A`; if they are at or above that figure but below ten thousand dollars expressed as one hundred million cents, the base rate is ten percent, which is `TIER_B`; otherwise the base rate is five percent, which is `TIER_C`. (These same thresholds define the freelancer's `fee_tier` field.) A risk surcharge is then applied: if the freelancer's `dispute_loss_count` is at least three, five percentage points are added to the rate. The resulting rate is then capped so it can never exceed twenty-five percent. The `platform_fee_cents` is the gross multiplied by this effective rate and floored to a whole cent, but it is never less than a floor of 100 cents unless the gross is itself zero, in which case the fee is zero, and it never exceeds the gross. The net is the gross minus this fee.

Settlement of a payout is a `PlatformAdmin` action gated on tax paperwork. Settling a `PENDING` payout when the freelancer's `tax_id_on_file` is true moves the payout to `PAID`, adds its `net_cents` to the freelancer's `lifetime_earnings_cents` — which recomputes the `fee_tier` — and recomputes the `reputation_score`. Settling a `PENDING` payout when `tax_id_on_file` is false instead moves the payout to `HELD_NO_TAX_ID` and makes no lifetime update: the settlement was attempted but blocked for missing tax identity. Once the freelancer puts a tax id on file, a payout sitting in `HELD_NO_TAX_ID` can be settled again, this time moving to `PAID` and applying the same lifetime-earnings and reputation updates. Settling a payout that is in neither a `PENDING` nor a `HELD_NO_TAX_ID` settle-eligible state is rejected with `ERR_INVALID_PAYOUT_STATE`. The terminal payout state is `PAID`.

### 3.7. Disputes and Arbitration

When the two sides disagree about delivered work, either a `Client` or a `Freelancer` may open a dispute on a `SUBMITTED` milestone, supplying who is `raised_by` (either `CLIENT` or `FREELANCER`), a `reason`, and a `claimed_release_cents` that the freelancer claims should be released, which must be at least zero and must not exceed the milestone's `funded_cents`. The `claimed_release_cents` bound is enforced as a structural amount check at the `ERR_INVALID_REQUEST` tier of §2.6, evaluated before the milestone-state check, so a value below zero or above `funded_cents` is rejected with `ERR_INVALID_REQUEST`. Opening a dispute requires the milestone to be in `SUBMITTED`; a dispute attempt against a milestone in any other state is rejected with `ERR_INVALID_MILESTONE_STATE`. The act moves the milestone to `DISPUTED`, creates a `Dispute` in `OPEN` whose `contract_id` is copied from the milestone and whose `milestone_id` names the disputed milestone, and increments the contract's `open_dispute_count`. This is the second branch of the fork out of `SUBMITTED`, and it carries a different side-effect set than approval.

A dispute may be withdrawn by its raiser while it is still `OPEN` — the acting party must equal the dispute's `raised_by`, supplied as an `actor_role` — which returns the milestone to `SUBMITTED` and decrements the contract's `open_dispute_count`. The `OPEN`-state requirement is checked first, so a withdraw against a dispute not in `OPEN` is rejected with `ERR_INVALID_DISPUTE_STATE`; a withdraw whose supplied `actor_role` does not match the dispute's `raised_by` is rejected with `ERR_FORBIDDEN_ROLE`. Otherwise an `Arbitrator` takes the dispute under arbitration, moving it from `OPEN` to `UNDER_ARBITRATION`; assigning arbitration to a dispute not in `OPEN` is rejected with `ERR_INVALID_DISPUTE_STATE`. The arbitrator then resolves the dispute by supplying an `arbitrator_award_cents` — the cents to be released to the freelancer, with the remainder refunded to the client. Resolution is permitted only from `UNDER_ARBITRATION`, and the award must satisfy being at least zero and at most the milestone's `funded_cents`; the dispute-state check is applied before the award-range check, so an attempt to resolve a dispute not in `UNDER_ARBITRATION` is rejected with `ERR_INVALID_DISPUTE_STATE` even when the supplied award is also out of range, and an in-state resolution whose award lies outside that inclusive range is rejected with `ERR_AWARD_OUT_OF_RANGE`.

The award determines the `resolution` and cascades through escrow and reputation. When the award equals the full `funded_cents` the resolution is `FREELANCER_FAVOR`; when the award is zero the resolution is `CLIENT_FAVOR`; otherwise it is `SPLIT`. For any award greater than zero the milestone moves to `RELEASED`: a `RELEASE` `EscrowTransaction` is emitted for the `arbitrator_award_cents`, and if that award is less than the funded amount a `REFUND` `EscrowTransaction` returns the remainder to the client's `wallet_balance_cents`; a `Payout` is created with gross equal to the award and its fee and net computed. For an award of zero the milestone moves to `REFUNDED`: a `REFUND` `EscrowTransaction` returns the full `funded_cents` to the client's wallet, the freelancer's `dispute_loss_count` increments, and the reputation is recomputed. In every resolution the contract's `open_dispute_count` decrements. Any award greater than zero creates a `Payout`, and that payout creation re-derives and re-stores the freelancer's `reputation_score` and `fee_tier` exactly as the release path in §3.5 does — version-bumping the freelancer even on a `FREELANCER_FAVOR` outcome whose loss count does not change — while on a `CLIENT_FAVOR` or `SPLIT` outcome the freelancer's reputation is recomputed a further time because such outcomes count as losses that do move the score. The dispute's terminal states are `RESOLVED` and `WITHDRAWN`.

### 3.8. Completing or Terminating Contracts, and Reviews

A `Client` completes an `ACTIVE` contract once nothing is left open. Completion requires the contract to be `ACTIVE`, requires `open_milestone_count` to be zero — meaning every milestone has reached `RELEASED`, `REFUNDED`, or `CANCELLED` — and requires `open_dispute_count` to be zero; the contract-state check is applied before the open-item check, so an attempt to complete a contract that is not `ACTIVE` is rejected with `ERR_INVALID_CONTRACT_STATE` first, and only on an `ACTIVE` contract does either count being above zero reject the completion with `ERR_CONTRACT_HAS_OPEN_ITEMS`. Completion moves the contract to `COMPLETED`, increments the freelancer's `completed_contract_count`, and recomputes the freelancer's `reputation_score`.

Alternatively a `Client` terminates a contract from `DRAFT` or `ACTIVE`, but only when `open_dispute_count` is zero; here too the contract-state check precedes the open-item check, so an attempt to terminate a contract that is neither `DRAFT` nor `ACTIVE` is rejected with `ERR_INVALID_CONTRACT_STATE` first, and only on a `DRAFT` or `ACTIVE` contract does an open dispute block termination with `ERR_CONTRACT_HAS_OPEN_ITEMS`. Termination cascades in stages: each milestone in `DRAFT`, `FUNDED`, `SUBMITTED`, or `APPROVED` is moved to `CANCELLED`; then each cancelled milestone whose `funded_cents` is greater than zero emits a `REFUND` `EscrowTransaction` returning its held escrow to the client's `wallet_balance_cents`; and finally the freelancer's `reputation_score` is recomputed. The contract moves to `TERMINATED`. Both `TERMINATED` and `COMPLETED` are terminal contract states.

After a contract reaches `COMPLETED`, either party may leave a `Review`. A review names the `contract_id` being reviewed, an `author_role` of `CLIENT` or `FREELANCER`, a `rating` from one through five stars, and a `comment`. The reviewed freelancer is captured as `freelancer_id`, copied from the contract and reachable through the contract's reviews list. The acting party must own its side of the reviewed contract — a `Client` caller must own the contract's `client_id` and a `Freelancer` caller must own its `freelancer_id`, or the request is rejected with `ERR_FORBIDDEN_ROLE` (this ownership is keyed on the caller's `X-User-Role`, independent of the supplied `author_role`). A review may only be left on a contract that is `COMPLETED`; an attempt to review a contract in any other state is rejected with `ERR_REVIEW_CONTRACT_NOT_COMPLETED`. When the author role is `CLIENT`, the freelancer's reputation is recomputed, since only client-authored ratings feed the reputation average. Because the error catalogue carries no review-specific not-found code, a read of a `Review` by an id that does not resolve is rejected with `ERR_CONTRACT_NOT_FOUND`.

### 3.9. Year-End Tax Reporting

For tax compliance a `PlatformAdmin` generates a `TaxRecord` for a given freelancer and year, naming the `freelancer_id` subject and the `tax_year`, and optionally choosing a reporting `basis` whose value is one of the two strings `GROSS_BASIS` or `NET_BASIS`, defaulting to `GROSS_BASIS` when omitted; any other value is rejected with `ERR_INVALID_REQUEST`. The chosen basis only selects the aggregation and is not itself stored on the generated record. The record aggregates only paid payouts: payouts in `PENDING` or `HELD_NO_TAX_ID` are excluded from the sweep. The aggregation has two valid variants that produce different totals for the same freelancer and year, selected by the `basis` input. Under the default gross basis — the IRS 1099-NEC convention — the `reportable_gross_cents` is the sum of `gross_cents` over the freelancer's payouts that are `PAID` in that `tax_year`. Under the net basis, used for the platform's internal statement, it is instead the sum of `net_cents` over those same paid payouts. The record's `is_reportable` flag is true when `reportable_gross_cents` is at least the reporting threshold of sixty thousand cents — six hundred dollars — using an inclusive comparison, and false below it. The `form_status` is `GENERATED` when the record is reportable and `BELOW_THRESHOLD` otherwise.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a client, a freelancer, a job posting, a proposal, a milestone, a dispute, a time log, a review, or a tax record — return `201 Created`. Operations that modify an existing resource, including every state-transition action and every wallet deposit, return `200 OK`. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a client account | PlatformAdmin |
| GET | `/clients` | List clients | PlatformAdmin, Client |
| GET | `/clients/{id}` | Get a client | PlatformAdmin, Client |
| POST | `/clients/{id}/wallet/deposit` | Top up a client wallet | PlatformAdmin, Client |
| GET | `/clients/{id}/job-postings` | List job postings owned by a client | PlatformAdmin, Client, Freelancer |
| GET | `/clients/{id}/contracts` | List contracts for a client | PlatformAdmin, Client |
| POST | `/freelancers` | Create a freelancer account | PlatformAdmin |
| GET | `/freelancers` | List freelancers | PlatformAdmin, Client, Freelancer |
| GET | `/freelancers/{id}` | Get a freelancer | PlatformAdmin, Client, Freelancer |
| PATCH | `/freelancers/{id}` | Update a freelancer profile | PlatformAdmin, Freelancer |
| GET | `/freelancers/{id}/proposals` | List a freelancer's proposals | PlatformAdmin, Freelancer |
| GET | `/freelancers/{id}/contracts` | List a freelancer's contracts | PlatformAdmin, Freelancer, Client |
| GET | `/freelancers/{id}/payouts` | List a freelancer's payouts | PlatformAdmin, Freelancer |
| GET | `/freelancers/{id}/tax-records` | List a freelancer's tax records | PlatformAdmin, Freelancer |
| POST | `/job-postings` | Create a job posting | Client |
| GET | `/job-postings` | List job postings | PlatformAdmin, Client, Freelancer |
| GET | `/job-postings/{id}` | Get a job posting | PlatformAdmin, Client, Freelancer |
| POST | `/job-postings/{id}/cancel` | Cancel a posting; decline live proposals | Client |
| GET | `/job-postings/{id}/proposals` | List proposals for a posting | PlatformAdmin, Client, Freelancer |
| GET | `/job-postings/{id}/ranked-proposals` | Rank live proposals by match score | PlatformAdmin, Client |
| POST | `/proposals` | Submit a proposal on a posting | Freelancer |
| GET | `/proposals/{id}` | Get a proposal | PlatformAdmin, Client, Freelancer |
| POST | `/proposals/{id}/counter` | Counter-offer (alternating turns) | Client, Freelancer |
| POST | `/proposals/{id}/accept` | Accept the live offer; award and draft a contract | Client, Freelancer |
| POST | `/proposals/{id}/decline` | Decline a proposal | Client |
| POST | `/proposals/{id}/withdraw` | Withdraw a proposal | Freelancer |
| GET | `/contracts/{id}` | Get a contract | PlatformAdmin, Client, Freelancer |
| POST | `/contracts/{id}/activate` | Activate a DRAFT contract with SOW text | Client |
| POST | `/contracts/{id}/complete` | Complete an ACTIVE contract with no open items | Client |
| POST | `/contracts/{id}/terminate` | Terminate a contract; cancel milestones, refund escrow | Client |
| GET | `/contracts/{id}/milestones` | List milestones for a contract | PlatformAdmin, Client, Freelancer |
| GET | `/contracts/{id}/timelogs` | List timelogs for a contract | PlatformAdmin, Client, Freelancer |
| GET | `/contracts/{id}/escrow-transactions` | List escrow ledger rows for a contract | PlatformAdmin, Client, Freelancer |
| GET | `/contracts/{id}/disputes` | List disputes for a contract | PlatformAdmin, Client, Freelancer, Arbitrator |
| GET | `/contracts/{id}/reviews` | List reviews for a contract | PlatformAdmin, Client, Freelancer |
| POST | `/contracts/{id}/milestones` | Create a milestone under an ACTIVE contract | Client |
| GET | `/contracts/{id}/milestones/{milestoneId}` | Get a milestone | PlatformAdmin, Client, Freelancer |
| POST | `/contracts/{id}/milestones/{milestoneId}/fund` | Fund escrow for a milestone | Client |
| POST | `/contracts/{id}/milestones/{milestoneId}/submit-work` | Submit the milestone deliverable | Freelancer |
| POST | `/contracts/{id}/milestones/{milestoneId}/approve` | Approve a submitted milestone | Client |
| POST | `/contracts/{id}/milestones/{milestoneId}/release` | Release escrow; create a payout | Client |
| POST | `/contracts/{id}/milestones/{milestoneId}/dispute` | Open a dispute on a submitted milestone | Client, Freelancer |
| POST | `/contracts/{id}/timelogs` | Log hourly work against a milestone | Freelancer |
| POST | `/contracts/{id}/timelogs/{timelogId}/verify` | Verify a logged interval | Client |
| POST | `/contracts/{id}/timelogs/{timelogId}/reject` | Reject a logged interval | Client |
| GET | `/disputes/{id}` | Get a dispute | PlatformAdmin, Client, Freelancer, Arbitrator |
| POST | `/disputes/{id}/assign-arbitration` | Take a dispute under arbitration | Arbitrator |
| POST | `/disputes/{id}/resolve` | Resolve a dispute with an award | Arbitrator |
| POST | `/disputes/{id}/withdraw` | Withdraw an open dispute | Client, Freelancer |
| GET | `/payouts/{id}` | Get a payout | PlatformAdmin, Freelancer, Client |
| POST | `/payouts/{id}/settle` | Settle a pending payout | PlatformAdmin |
| GET | `/milestones/{id}` | Get a milestone by global id | PlatformAdmin, Client, Freelancer |
| GET | `/milestones/{id}/payouts` | List payouts for a milestone | PlatformAdmin, Freelancer, Client |
| GET | `/milestones/{id}/escrow-transactions` | List escrow rows for a milestone | PlatformAdmin, Client, Freelancer |
| GET | `/milestones/{id}/timelogs` | List timelogs for a milestone | PlatformAdmin, Client, Freelancer |
| GET | `/milestones/{id}/disputes` | List disputes for a milestone | PlatformAdmin, Client, Freelancer, Arbitrator |
| POST | `/reviews` | Leave a review on a completed contract | Client, Freelancer |
| GET | `/reviews/{id}` | Get a review | PlatformAdmin, Client, Freelancer |
| POST | `/tax-records` | Generate a 1099 tax record (dual-basis) | PlatformAdmin |
| GET | `/tax-records/{id}` | Get a tax record | PlatformAdmin, Freelancer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CLIENT_NOT_FOUND` | 404 Not Found |
| `ERR_FREELANCER_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_POSTING_NOT_FOUND` | 404 Not Found |
| `ERR_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_TIMELOG_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYOUT_NOT_FOUND` | 404 Not Found |
| `ERR_TAX_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_SKILLS_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_INVALID_PROPOSAL_STATE` | 409 Conflict |
| `ERR_NOT_YOUR_TURN` | 409 Conflict |
| `ERR_INVALID_CONTRACT_STATE` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_MILESTONE_STATE` | 409 Conflict |
| `ERR_NO_VERIFIED_TIMELOGS` | 409 Conflict |
| `ERR_INVALID_TIMELOG_STATE` | 409 Conflict |
| `ERR_TIMELOG_OVERLAP` | 409 Conflict |
| `ERR_DAILY_HOURS_CAP_EXCEEDED` | 409 Conflict |
| `ERR_INVALID_DISPUTE_STATE` | 409 Conflict |
| `ERR_AWARD_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CONTRACT_HAS_OPEN_ITEMS` | 409 Conflict |
| `ERR_INVALID_PAYOUT_STATE` | 409 Conflict |
| `ERR_REVIEW_CONTRACT_NOT_COMPLETED` | 409 Conflict |
| `ERR_INSUFFICIENT_WALLET` | 402 Payment Required |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_MILESTONE_ORDINAL` | 409 Conflict |
