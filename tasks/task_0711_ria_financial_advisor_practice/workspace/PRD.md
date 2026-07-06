# RIA Practice API — Product Requirements Document

## 1. Introduction

A Registered Investment Advisor (RIA) practice runs on a fragile chain of obligations: a client must be risk-profiled and given a signed Investment Policy Statement before money is managed, accounts must be aggregated across custodians so that asset-based fees are billed against the right balance, model portfolios must be kept in alignment as markets drift, and every fee assessment and policy decision must survive a Reg BI or Form ADV examination years later. This API is the system of record for that entire practice. It models households and the clients, accounts, policy statements, fee runs, financial plans, reviews, and compliance obligations that orbit them, and it enforces the separation-of-duties and audit guarantees that distinguish a defensible advisory shop from one that merely keeps spreadsheets.

The product exists to make the practice's hardest invariants automatic rather than aspirational. Assets-under-management fees are computed from tiered, marginal-rate schedules and prorated to the day, with the household's aggregated wealth selecting the breakpoint tier and a per-client policy mandate constraining what the advisor may build. Money-touching actions are deliberately split between the advisor who proposes and the independent officer or administrator who blesses: the advisor who proposes a policy may not approve it, and the administrator who builds a fee run may not be the one who finalizes it. Throughout, the system reconciles derived figures — billable assets, drift, plan funding — the instant their inputs change, so that what a reader sees on a household, an account, or a goal is always the current truth rather than a stale cache.

Because the practice operates against deadlines (review cadences, disclosure due dates, billing periods), the server keeps a controllable logical clock rather than reading wall time. All "today" comparisons — overdue reviews, lapsed obligations, projection horizons — read from this clock, which lets examiners and the test harness reproduce time-dependent behavior exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API. All entity collections are peers rooted at the server root; there is no shared parent path segment.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, the acting operator's identifier, and `X-User-Role`, the operational capacity under which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication is checked before authorization, and both are checked before anything else.

The system recognizes exactly three roles: `Advisor`, `ComplianceOfficer`, and `BillingAdmin`.

- An `Advisor` builds and runs the practice: onboarding clients, building and publishing model portfolios, drafting and proposing policy statements, adding and managing accounts, running financial plans and reviews, and proposing and executing rebalances.
- A `ComplianceOfficer` provides independent oversight: approving or requesting changes to policy statements, approving or rejecting rebalances, and managing and archiving compliance obligations.
- A `BillingAdmin` owns the fee mechanics: creating fee schedules, creating and progressing fee runs, and setting the logical clock.

All three roles share read access; every `GET` endpoint is available to `Advisor`, `ComplianceOfficer`, and `BillingAdmin` alike.

For all three roles, `X-User-ID` is an **opaque operator identifier** — it is not the primary key of any persisted entity, and the server never compares it to an entity's `id`. The server does, however, record it where the workflow demands an actor of record. When an `Advisor` creates a household, the supplied `lead_advisor_id` is the opaque advisor operator who owns that relationship. When an `Advisor` proposes a policy statement, the server records that advisor's `X-User-ID` as the proposing advisor for the later separation-of-duties check. When a `ComplianceOfficer` approves a policy statement, the server records their `X-User-ID` in `approved_by_user_id`. When a `BillingAdmin` creates a fee run, the server records that administrator's `X-User-ID` as the run's creator so that a different administrator must be the one to finalize it. None of these recorded values are treated as foreign keys to a user entity; they are operator identifiers compared only to one another.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1, a `limit` above 100, or a negative `offset` is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in the system carries a server-minted `id` (a UUID, with no type prefix) and a `created_at` timestamp (ISO 8601 UTC with three fractional digits). All of the entities in this API — households, fee schedules, clients, policy statements, portfolios, accounts, fee runs, financial plans, goals, rebalance orders, reviews, and compliance items — additionally carry an `updated_at` timestamp (ISO 8601 UTC, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on every mutation of the resource. The `version` field is the basis of the optimistic-concurrency check described in §2.6.

When a derived figure is recomputed on a resource as a side effect of some action, that recomputation is itself a mutation of the resource: it refreshes the resource's `updated_at` and increments its `version`. The one place the specification calls out an explicit cross-entity `version` bump is fee-run finalization, described in §2.6 and §3.5.

The server maintains a single logical clock that supplies "today" and "now" everywhere the system reasons about time: overdue reviews, lapsed compliance obligations, fee-period day counts, certification of whether a goal is on track, and the thirty-day extension granted when a compliance item is reopened. The clock's startup default is `2026-03-01T00:00:00Z`; before any clock-setting call has been made, the clock reads exactly this default and never falls back to wall-clock time. A clock-setting capability accepts a target instant in the `to_iso8601` field and moves the clock to it, returning the new `current_utc`. Advancing the clock does not eagerly rewrite stored rows; instead, time-derived read fields such as a review's `is_overdue` flag are recomputed lazily when the resource is read.

### 2.5. Nested Resource Retrieval and Reference Integrity

Several read endpoints address a resource through a parent in the path — for example, listing the clients or accounts that belong to a household, the rebalance orders that belong to an account, or the goals that belong to a financial plan. The system validates path identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. A request to list goals under a financial plan that does not exist fails on the plan before the system considers any goal.

Path existence (checked with `ERR_NOT_FOUND`, HTTP 404) is distinct from body-reference existence. When a creation request names another entity through a body field — `household_id`, `client_id`, `fee_schedule_id`, `target_portfolio_id`, `plan_id`, or `account_id` — and that referenced entity does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422). The ordering of validations across all endpoints is fixed and described in §2.7.

### 2.6. Optimistic Concurrency on Fee-Run Creation

Creating a fee run is the one write in this system guarded by optimistic concurrency control, because a fee run is the moment a household's billing state advances and a stale view of that state would let an operator bill against a balance they never observed. A fee-run creation request must carry `expected_household_version`, a non-optional field that holds the `version` of the target household as the client last read it. The server compares `expected_household_version` against the household's current `version`. If they do not match — because some other writer (most commonly a prior fee run that finalized and bumped the household) has advanced the household's `version` since the client read it — the creation is rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412). The rejection is an optimistic-concurrency rejection on a stale observed version, not a state error: the household remains `ACTIVE` and a new fee run is itself perfectly legitimate; the client simply re-reads the household, picks up the current `version`, and retries. No other endpoint in the system takes a version field, and no other create or transition performs this check.

### 2.7. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the failure a client sees is deterministic. The order is:

1. Authentication — `X-User-ID` and `X-User-Role` present and the role recognized, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. Authorization — the role is permitted for the operation per §2.1 and the endpoint table, else `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint.
3. Path existence — every resource named by a path identifier exists, validated left to right, else `ERR_NOT_FOUND` (404). Applies to every endpoint that has a path identifier.
4. Body-reference existence — every body foreign key (`household_id`, `client_id`, `fee_schedule_id`, `target_portfolio_id`, `plan_id`, `account_id`) resolves, else `ERR_REFERENCE_NOT_FOUND` (422). Applies to every creation endpoint that carries such a field.
5. State legality — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409). Applies to every action and transition endpoint.
6. Separation of duties — the policy-statement approver is not the proposing advisor, and the fee-run finalizer is not the run's creator, else `ERR_SEGREGATION_OF_DUTIES` (403). Applies to policy-statement approval and fee-run finalization.
7. Policy-mandate safety — a policy statement's `max_equity_pct` is at least the target portfolio's `model_equity_pct`, and the target portfolio is published, else `ERR_IPS_MANDATE_VIOLATION` (422). Applies to policy-statement proposal.
8. Cross-entity preconditions — account activation requires the owning client in an eligible onboarding state, and rebalance approval requires the linked account `ACTIVE` and the client's policy statement `APPROVED`, else `ERR_CROSS_ENTITY_PRECONDITION` (409). Applies to account activation and rebalance approval.
9. Billing-period overlap — no two finalized fee runs for one household may cover overlapping periods, else `ERR_BILLING_PERIOD_OVERLAP` (409). Applies to fee-run finalization.
10. Review-date collision — two scheduled reviews for one household may not share a scheduled date, else `ERR_REVIEW_DATE_COLLISION` (409). Applies to review scheduling.
11. Allocation validity — a portfolio's target weights sum to exactly 100, and an account's equity value does not exceed its market value, else `ERR_ALLOCATION_INVALID` (422). Applies to portfolio creation, account creation, and account valuation.
12. Period validity — a fee run's period end is strictly after its period start, else `ERR_INVALID_PERIOD` (422). Applies to fee-run creation.
13. Stale-household optimistic concurrency — `expected_household_version` equals the household's current `version`, else `ERR_STALE_HOUSEHOLD_VERSION` (412). Applies to fee-run creation.
14. Field-level input validation — enums within their declared sets, scores within range, non-negative cent amounts, well-formed ISO dates, and pagination bounds, else `ERR_INVALID_REQUEST` (400). Applies to every endpoint.

Several endpoints layer their own domain conditions on top of this spine; those (for example the duplicate-policy guard, the published-portfolio guard, the approved-policy guard for rebalances, the open-fee-run guard on account closure, the compliance due-date guard, and the goal-amount guard) are described alongside the workflows they protect in §3, and their error codes appear in the catalogue in §5.

### 2.8. Households, Aggregation, and Breakpoint Tiers

The household is the billing root. A household pins a `fee_schedule_id` and a `billing_method` of either `ARREARS` or `ADVANCE` (defaulting to `ARREARS`), and the system maintains three derived figures on it. The `billable_aum_cents` is the sum of `market_value_cents` over the household's member accounts that are simultaneously `ACTIVE`, billable, and not held away. The `aggregated_aum_cents` is the broader figure: the sum of `market_value_cents` over **all** the household's `ACTIVE` member accounts, including held-away and non-billable ones. The `breakpoint_tier_index` is the zero-based index of the fee-schedule tier selected by `aggregated_aum_cents`; it pins the marginal-rate schedule the next fee run will use. All three start at 0 on a freshly created household and are recomputed whenever an account's state changes, whenever an account is revalued, or whenever an account is added — the precise recomputation is given in §3.

Tier selection treats the schedule's tiers as ordered ascending by `upper_bound_cents`, with the final tier open-ended (its `upper_bound_cents` is null). The selected index is that of the first tier whose `upper_bound_cents` is null or strictly greater than `aggregated_aum_cents`. The boundary is strict: an `aggregated_aum_cents` exactly equal to a tier's `upper_bound_cents` does not belong to that tier — it falls into the next, higher tier. Landing one cent below a bound keeps the lower tier; landing exactly on the bound advances to the next.

A household begins `ACTIVE` and can be moved to `CLOSED`. A `CLOSED` household rejects new fee runs and new account additions.

### 2.9. Fee Calculation, Precision, and Schedule Locking

Asset-based fees are computed in integer cents throughout. Where a calculation introduces a fraction — applying a basis-point rate, prorating an annual figure across a period, or computing a minimum floor — the result is rounded to whole cents using the round-half-up convention (a value exactly at the half-cent rounds up). Basis points convert to a fraction by dividing by 10000, and annual figures prorate against a 365-day year. The exact evaluation order of the fee formula is given in §3.4; it matters, because rounding is applied per tier slice and again at proration and floor, never as a single rounding at the end.

A fee schedule is built from an ascending list of `tiers`, each carrying an `upper_bound_cents` (null on the final, open-ended tier) and an `annual_rate_bps`, plus a `minimum_annual_fee_cents` floor. A schedule exposes `is_locked`, which starts false and becomes true the moment any fee run that references the schedule reaches `CALCULATED` or `FINALIZED`. A locked schedule rejects edits to its tiers or minimum; such an edit is treated as an illegal operation and rejected with `ERR_INVALID_STATE` (409). To insulate a fee run from later schedule edits, the run snapshots the schedule it will use at creation time into `fee_schedule_snapshot_id`, and the snapshotted schedule's tiers and minimum are the ones the calculation uses regardless of subsequent edits to the live schedule.

### 2.10. Drift, Mandates, and Suitability Bands

Several derived figures outside the fee domain are likewise reconciled on change. An account's `drift_bps` measures how far its actual equity weight has drifted from the model equity weight mandated by the client's approved policy statement, and `rebalance_flagged` records whether that drift has reached the policy's tolerance. A client's `suitability_band` is derived from the client's two risk scores. A goal's `funded_ratio_bps` and `on_track` flag are derived from the goal's funds and the plan's assumptions. Each of these is specified in full, with its exact formula and boundary behavior, in §3 alongside the workflow that produces it. The governing precision rule is the same as for fees: round half up, to whole cents or whole basis points as the figure demands.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Suitability

A client is born as a `PROSPECT` when an `Advisor` creates them under a household. Creation requires the owning `household_id`, the client's `full_name`, a `date_of_birth` as an ISO `YYYY-MM-DD` date, and two onboarding-questionnaire scores: `risk_capacity_score`, the objective ability to bear loss, and `risk_tolerance_score`, the subjective willingness to bear loss. Both scores are integers from 0 through 100 inclusive; a score outside that range is an `ERR_INVALID_REQUEST` (400). The client's `onboarding_status` begins at `PROSPECT`, and `suitability_band` begins at `MODERATE`.

Onboarding advances through a state machine driven by the advisor. Verifying KYC moves a client from `PROSPECT` to `KYC_VERIFIED`; it requires that the client currently be `PROSPECT` and that `date_of_birth` be present and parse to a valid past date. As a side effect of KYC verification, the system computes the client's `suitability_band` from the **smaller** of `risk_capacity_score` and `risk_tolerance_score`: the conservative of the two scores selects the band. A low combined score yields `CONSERVATIVE`, a middle combined score yields `MODERATE`, and a high combined score yields `AGGRESSIVE`. Signing the policy statement moves the client from `KYC_VERIFIED` to `IPS_SIGNED`; it requires the client be `KYC_VERIFIED` and that an investment policy statement exist for this client in `APPROVED` status. Activating moves the client from `IPS_SIGNED` to `ACTIVE`; it requires the client be `IPS_SIGNED` and that at least one account exist for the client whose status is `PENDING` or `ACTIVE`. From either `PROSPECT` or `KYC_VERIFIED`, a client may be disengaged to the terminal `DISENGAGED` state; disengagement carries no cascade. A transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE` (409). The onboarding states, in full, are `PROSPECT`, `KYC_VERIFIED`, `IPS_SIGNED`, `ACTIVE`, and `DISENGAGED`; the suitability bands are `CONSERVATIVE`, `MODERATE`, and `AGGRESSIVE`.

### 3.2. Model Portfolios and the Investment Policy Statement

Before any client can be managed, an `Advisor` builds a **model portfolio**: a `name`, a target `model_equity_pct` (an integer from 0 through 100), and `target_weights`, a list of sleeves each carrying a `sleeve` label and an integer `target_pct`. The `target_pct` values across the sleeves must sum to exactly 100; a portfolio whose weights do not sum to 100 is rejected with `ERR_ALLOCATION_INVALID` (422). A portfolio is created unpublished, with `is_published` false, and a separate publish action sets `is_published` to true. Only a published portfolio may be named as the target of a policy statement.

The **investment policy statement** (IPS) is the per-client mandate, created in `DRAFT` by an advisor with the client's `client_id`, the `target_portfolio_id` of the model it mandates, a `max_equity_pct` ceiling (an integer from 0 through 100) on equity allocation, and an optional `drift_tolerance_bps` — the absolute drift, in basis points, beyond which a rebalance is mandated — which must be greater than zero and defaults to 500 when omitted. A policy statement also carries a `revision_round` counter that starts at 0, an `approved_by_user_id` that is null until approval, and a `status` that starts at `DRAFT`.

The policy statement moves through a cyclic approval workflow whose full state set is `DRAFT`, `PROPOSED`, `APPROVED`, and `SUPERSEDED`. The advisor proposes the statement, advancing it from `DRAFT` to `PROPOSED`. Proposal requires the statement be `DRAFT`; it requires the portfolio named by `target_portfolio_id` to exist and have `is_published` true (a target that is unpublished is rejected with `ERR_PORTFOLIO_NOT_PUBLISHED`, 422); and it requires the statement's `max_equity_pct` to be at least the target portfolio's `model_equity_pct`, so that the mandate actually permits the model it points at — a `max_equity_pct` below the model's equity weight is rejected with `ERR_IPS_MANDATE_VIOLATION` (422). A client may have only one statement in flight: proposing a new statement while the same client already has a `PROPOSED` statement is rejected with `ERR_DUPLICATE_APPROVED_IPS` (409). As a side effect of a successful proposal, the system records the proposing advisor's `X-User-ID` for the later separation-of-duties check.

A `ComplianceOfficer` resolves a `PROPOSED` statement one of two ways. Requesting changes returns the statement from `PROPOSED` to `DRAFT` and, as its side effect, increments `revision_round` by one — this is the cycle counter that records how many times the statement has been bounced back. Approving advances the statement from `PROPOSED` to `APPROVED`; it requires the statement be `PROPOSED` and, crucially, that the approving officer's `X-User-ID` differ from the proposing advisor recorded at propose time. An officer who is also the proposing advisor cannot self-approve; that attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). Approval has three side effects: it sets `approved_by_user_id` to the approving officer's `X-User-ID`; it supersedes any other statement for the same `client_id` currently in `APPROVED` status by transitioning that prior statement from `APPROVED` to `SUPERSEDED`; and it opens a compliance obligation — a compliance item whose `subject_type` is `CLIENT`, whose `subject_id` is the client, whose `obligation_type` is `IPS_ARCHIVE`, and whose status is `OPEN`. The `SUPERSEDED` state is terminal and is reached only through this system-driven supersession; it carries no further cascade.

### 3.3. Accounts, Aggregation, and Drift

An `Advisor` adds an account to a household with the owning `household_id`, the primary owner's `client_id`, a `custodian` name, and an `account_type` drawn from `TAXABLE`, `IRA`, `ROTH`, `TRUST`, and `HELD_AWAY_401K`. Two booleans shape how the account participates in billing and aggregation: `held_away`, defaulting to false, marks assets the practice tracks but does not custody, and `billable`, defaulting to true, marks whether the account participates in fee billing. The account's value is given by `market_value_cents`, defaulting to 0 and never negative, and the equity portion of that value by `equity_value_cents`, defaulting to 0, never negative, and never greater than `market_value_cents`. An account whose `equity_value_cents` exceeds its `market_value_cents` is rejected with `ERR_ALLOCATION_INVALID` (422). The account also carries the computed `drift_bps` and `rebalance_flagged` figures, and a `status` that begins at `PENDING`.

Accounts move through `PENDING`, `ACTIVE`, `FROZEN`, and `CLOSED`. Activation moves an account from `PENDING` to `ACTIVE`; it requires the account be `PENDING`, the owning client's `onboarding_status` to be `IPS_SIGNED` or `ACTIVE`, and the owning household to be `ACTIVE`. A client not yet far enough along onboarding fails this cross-entity gate with `ERR_CROSS_ENTITY_PRECONDITION` (409). Freezing moves an account from `ACTIVE` to `FROZEN`; unfreezing moves it back from `FROZEN` to `ACTIVE` and requires the owning household to be `ACTIVE`. An account may be closed from either `ACTIVE` or `FROZEN`, reaching the terminal `CLOSED` state, but only when there is no fee run referencing the owning household in `DRAFT` or `CALCULATED` status — an account cannot be closed while an open fee run is in flight, and the attempt is rejected with `ERR_FEE_RUN_OPEN` (409).

Each of these account transitions recomputes the owning household's aggregation. Activation, unfreezing, and either closure path each recompute `billable_aum_cents` and `aggregated_aum_cents`; activation and the two closure paths additionally recompute `breakpoint_tier_index`. Freezing recomputes `billable_aum_cents` and `aggregated_aum_cents` — a frozen account's value is still aggregated into `aggregated_aum_cents` but is no longer billable, so the two figures diverge — and freezing additionally cancels any rebalance order for that account currently in `PROPOSED` status by transitioning it from `PROPOSED` to `REJECTED`. The recomputation itself follows §2.8: `aggregated_aum_cents` is the sum of `market_value_cents` over the household's `ACTIVE` accounts; `billable_aum_cents` is the same sum restricted to accounts that are also billable and not held away; and `breakpoint_tier_index` is then selected from `aggregated_aum_cents` against the household's fee schedule with the strict-boundary rule.

Revaluing an account updates its `market_value_cents` and `equity_value_cents` together (the equity portion still may not exceed market value, on pain of `ERR_ALLOCATION_INVALID`), and triggers two reconciliations. First it recomputes the account's drift, and second it recomputes the owning household's `billable_aum_cents`, `aggregated_aum_cents`, and `breakpoint_tier_index`. Drift is computed as the absolute difference between the account's actual equity weight and the model's equity weight, expressed in basis points. The actual equity weight in basis points is `equity_value_cents` multiplied by 10000 and divided by `market_value_cents`, rounded half up to whole basis points; if `market_value_cents` is zero, the actual weight is treated as zero basis points. The model weight in basis points is the model equity percentage multiplied by 100, where the model equity percentage comes from the `model_equity_pct` of the portfolio targeted by the client's `APPROVED` policy statement. The drift is the absolute value of the difference between those two basis-point figures, and `rebalance_flagged` is true exactly when `drift_bps` is greater than or equal to the policy's `drift_tolerance_bps` — at-tolerance flags. If the account's client has no `APPROVED` policy statement, there is no model to compare against, so `drift_bps` is 0 and `rebalance_flagged` is false.

### 3.4. Fee Runs: Basis Selection, Tiered Marginal Fee, and the Floor

A `BillingAdmin` creates a fee run for a household by supplying the `household_id`, an inclusive `period_start` and `period_end` as ISO `YYYY-MM-DD` dates, and `expected_household_version`. The period end must be strictly after the period start, or the creation is rejected with `ERR_INVALID_PERIOD` (422). The optimistic-concurrency rule of §2.6 governs `expected_household_version`. On a successful create the run begins in `DRAFT`, and the system snapshots two values that pin the run against later drift: `billing_method_snapshot`, a copy of the household's `billing_method` (`ARREARS` or `ADVANCE`), and `fee_schedule_snapshot_id`, the household's fee schedule pinned at creation. Creating the run is itself a household-level mutation and increments the household's `version` by one. The run's `basis_aum_cents`, `gross_fee_cents`, and `assessed_fee_cents` all begin at 0; they are filled in by calculation. A fee run's full state set is `DRAFT`, `CALCULATED`, `FINALIZED`, and `VOIDED`.

Calculating advances a run from `DRAFT` to `CALCULATED`. It requires the run be `DRAFT`, the owning household be `ACTIVE`, and the period end be strictly after the period start. Calculation performs three computations in a fixed order and then locks the schedule.

The first computation selects the **basis**, branching on `billing_method_snapshot`. Under `ARREARS`, the basis is the household's billable assets as of the period end — the current `billable_aum_cents`. Under `ADVANCE`, the basis is the household's billable assets as of the period start, which the system reconstructs as the `basis_aum_cents` of the household's most recent `FINALIZED` fee run whose `period_end` equals this run's `period_start`; if several such prior finalized runs exist, the one with the latest `created_at` is used; and if no such prior finalized run exists, the basis falls back to the current `billable_aum_cents`. The selected figure is stored in `basis_aum_cents`. Both branches operate in integer cents with no rounding.

The second computation produces the **gross fee** by applying the snapshotted schedule's tiers marginally to `basis_aum_cents` and then prorating. The tiers are walked in ascending order. For each tier, the slice of the basis that falls within that tier is the portion of the basis between the tier's lower edge (the previous tier's `upper_bound_cents`, or 0 for the first tier) and the tier's `upper_bound_cents` (or the whole remaining basis for the open-ended final tier whose `upper_bound_cents` is null). Each tier's slice fee is the slice amount multiplied by that tier's `annual_rate_bps`, divided by 10000, **rounded half up to whole cents for that slice independently**; the tier slice fees are then summed to give the annual fee. Rounding is per slice, then summed — never sum-then-round. The annual fee is then prorated by the inclusive day count of the period: the number of days is the difference between `period_end` and `period_start` in days, plus one, and the prorated figure is the annual fee multiplied by that day count, divided by 365, rounded half up to whole cents. This prorated figure is `gross_fee_cents`.

The third computation applies the **minimum floor**. The schedule's `minimum_annual_fee_cents` is prorated the same way — multiplied by the inclusive day count, divided by 365, rounded half up — and `assessed_fee_cents` is the larger of `gross_fee_cents` and that prorated minimum. When the prorated marginal fee is at least the prorated minimum, the floor does not bind and `assessed_fee_cents` equals `gross_fee_cents`; when the prorated marginal fee falls below the prorated minimum, the floor binds and `assessed_fee_cents` is the prorated minimum, while `gross_fee_cents` still records the pre-floor marginal fee. Finally, reaching `CALCULATED` locks the referenced fee schedule by setting its `is_locked` to true.

A run in `CALCULATED` can be sent back for rework, finalized, or voided. Requesting a recalculation returns the run from `CALCULATED` to `DRAFT` and clears `basis_aum_cents`, `gross_fee_cents`, and `assessed_fee_cents` back to 0 to await recomputation. Voiding moves a run to the terminal `VOIDED` state from either `CALCULATED` or `DRAFT` and discards the run with no compliance item created. Finalizing is the consequential terminal transition and is covered next.

### 3.5. Finalizing a Fee Run

Finalizing advances a run from `CALCULATED` to the terminal `FINALIZED` state, and it is the most heavily guarded transition in the system. It requires the run be `CALCULATED`. It enforces separation of duties: the finalizing administrator's `X-User-ID` must differ from the `X-User-ID` of the administrator who created the run — the builder of a run cannot be its finalizer, and a self-finalization is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). And it enforces temporal non-overlap: there must be no other `FINALIZED` fee run for the same household whose inclusive `period_start`-through-`period_end` range overlaps this run's range; an overlap is rejected with `ERR_BILLING_PERIOD_OVERLAP` (409).

Finalization has two side effects that ripple beyond the run. It opens a compliance obligation — a compliance item whose `subject_type` is `HOUSEHOLD`, whose `subject_id` is the household, whose `obligation_type` is `FEE_DISCLOSURE`, and whose status is `OPEN`. And it increments the owning household's `version` by one, because a finalized fee run is a household-level mutation: this is exactly the version advance that a later, stale-versioned fee-run creation will collide with under the optimistic-concurrency rule of §2.6, which is the intended serialization point between one period's billing and the next.

### 3.6. Financial Plans and Goal Funding

The financial-plan domain runs in parallel to the fee domain and carries two independent state axes on a single plan row. An `Advisor` creates a plan for a household with the owning `household_id`, a `name`, an `assumed_annual_return_bps` projection assumption (non-negative basis points, defaulting to 600, i.e. 6.00%), and a `monthly_contribution_cents` assumption (non-negative, defaulting to 0). A plan tracks a `lifecycle_status` on one axis — `DRAFT`, then `ACTIVE`, then the terminal `ARCHIVED` — and a `review_status` on a fully independent axis — `NEEDS_REVIEW`, `REVIEWED`, and `STALE` — both evolving on the same plan without touching each other. A plan begins `DRAFT` on the lifecycle axis and `NEEDS_REVIEW` on the review axis.

On the lifecycle axis, activating moves a plan from `DRAFT` to `ACTIVE` and requires at least one goal to exist under the plan; as a side effect it recomputes `funded_ratio_bps` and `on_track` for every goal under the plan. Archiving moves a plan from `ACTIVE` to `ARCHIVED` with no cascade beyond the status change. On the review axis, marking reviewed moves a plan from either `NEEDS_REVIEW` or `STALE` to `REVIEWED` and, as a side effect, recomputes `funded_ratio_bps` and `on_track` for every goal under the plan; marking stale moves a plan from `REVIEWED` to `STALE` with no field change beyond the review status. Each axis only accepts its own transitions from the appropriate current value; a transition requested from the wrong state is `ERR_INVALID_STATE` (409).

A **goal** belongs to a plan via `plan_id` and is created by an advisor with a `name`, a `target_amount_cents` that must be greater than zero (a non-positive target is rejected with `ERR_GOAL_AMOUNT_INVALID`, 422), a `target_date` as an ISO `YYYY-MM-DD` date, an optional `current_amount_cents` of funds earmarked today (non-negative, defaulting to 0), and an optional `priority` drawn from `ESSENTIAL`, `SECONDARY`, and `ASPIRATIONAL` (defaulting to `SECONDARY`) that expresses the waterfall funding order. The goal carries computed `funded_ratio_bps` and `on_track` figures. Funds may later be added to a goal by an amount given as `amount_cents`, which must be greater than zero (a non-positive funding amount is also `ERR_GOAL_AMOUNT_INVALID`, 422); funding increases the goal's `current_amount_cents` and recomputes its `funded_ratio_bps` and `on_track`. Creating a goal likewise computes these figures.

The funding figure has two variants chosen by the plan's `lifecycle_status`. When the plan is `ACTIVE`, the **projected** variant applies: the goal's current balance is future-valued to the target date, and the assumed monthly contributions are future-valued as an annuity, both at the plan's assumed monthly return. The number of whole months between today (from the logical clock) and the goal's `target_date` is twelve times the difference in years plus the difference in months, floored at zero so a past target yields zero months. The monthly return rate is `assumed_annual_return_bps` divided by 10000 and then by 12. The future value of the current balance is `current_amount_cents` multiplied by one plus the monthly rate raised to the power of that month count. The future value of the contributions is `monthly_contribution_cents` multiplied by the standard annuity factor — that is, the quantity one plus the monthly rate raised to the month count, minus one, all divided by the monthly rate — except that when the monthly rate is exactly zero the contribution future value is simply `monthly_contribution_cents` multiplied by the month count. The projected value is the sum of those two future values, rounded half up to whole cents. When the plan is `DRAFT` (or otherwise not `ACTIVE`), the **actual** variant applies and the projected value is simply the goal's `current_amount_cents` with no projection. In both variants, `funded_ratio_bps` is that projected value multiplied by 10000 and divided by `target_amount_cents`, rounded half up to whole basis points (with `target_amount_cents` of zero yielding a ratio of 0), where 10000 basis points represents 100%. The goal is `on_track` exactly when `funded_ratio_bps` is greater than or equal to 10000 — landing exactly at 100% counts as on track.

### 3.7. Rebalance Orders

When an account has drifted from its model, an `Advisor` proposes a **rebalance order** for it, supplying only the `account_id`. The proposing action copies the `target_portfolio_id` from the account's client's `APPROVED` policy statement onto the order, and computes the order's `trade_equity_delta_cents` — the signed cents to move into equity (positive) or out of equity (negative) to reach the model weight. An account whose client has no `APPROVED` policy statement cannot have a rebalance proposed or approved against it; that attempt is rejected with `ERR_NO_APPROVED_IPS` (409). A rebalance order begins `PROPOSED`, and its full state set is `PROPOSED`, `APPROVED`, `EXECUTED`, and `REJECTED`.

A `ComplianceOfficer` resolves a `PROPOSED` order. Approving advances it from `PROPOSED` to `APPROVED`; it requires the order be `PROPOSED`, the linked account be `ACTIVE` (a rebalance cannot be approved against a frozen or closed account), and the account's client to have a policy statement in `APPROVED` status — a frozen or closed account, or a client without an approved statement, fails with `ERR_CROSS_ENTITY_PRECONDITION` (409). Rejecting moves an order from `PROPOSED` to the terminal `REJECTED` state with no field change beyond status. An `Advisor` then executes an `APPROVED` order, advancing it from `APPROVED` to the terminal `EXECUTED` state; execution requires the order be `APPROVED` and the linked account be `ACTIVE`. Executing has two side effects on the account: it sets the account's `equity_value_cents` so that the account's actual equity percentage equals the target portfolio's `model_equity_pct`, and it then recomputes the account's `drift_bps` and `rebalance_flagged`, which collapse the drift toward zero. (Recall from §3.3 that freezing an account also reaches into this state machine, cancelling any still-`PROPOSED` order by transitioning it to `REJECTED`.)

### 3.8. Reviews and the Cadence Calendar

An `Advisor` schedules a household **review** with the `household_id`, a `scheduled_for` ISO date, and an optional `cadence_days` — the required number of days between completed reviews — which must be greater than zero and defaults to 365. A review begins `SCHEDULED`, and its full state set is `SCHEDULED`, `COMPLETED`, and `MISSED`. Two scheduled reviews for the same household may not share a `scheduled_for` date; a collision on the calendar is rejected with `ERR_REVIEW_DATE_COLLISION` (409). When a new review is scheduled for a household and its `scheduled_for` falls after that of an existing `SCHEDULED` review for the same household, the earlier `SCHEDULED` review is superseded — it transitions from `SCHEDULED` to the terminal `MISSED` state with no further cascade.

A review carries three time-derived fields. The `completed_at` datetime is null until the review is completed. The `next_due_date` is null until completion. The `is_overdue` flag is true when the logical clock's date is past the review's `scheduled_for` and the review is still `SCHEDULED`; it is recomputed lazily when the review is read, so advancing the clock makes a still-open past-due review read as overdue without any explicit write. Completing a review moves it from `SCHEDULED` to the terminal `COMPLETED` state; it requires the review be `SCHEDULED` and the owning household be `ACTIVE`, and as side effects it stamps `completed_at` with the current logical-clock datetime and computes `next_due_date` as the `completed_at` date plus `cadence_days`.

### 3.9. Compliance Obligations, Remediation, and Archiving

Compliance items are the audit spine of the practice. Some are opened automatically — policy-statement approval opens an `IPS_ARCHIVE` item against the client (§3.2), and fee-run finalization opens a `FEE_DISCLOSURE` item against the household (§3.5) — and a `ComplianceOfficer` may also open one manually. A manual compliance item names a polymorphic subject through `subject_type`, one of `CLIENT`, `ACCOUNT`, or `HOUSEHOLD`, and the `subject_id` of the matching entity, together with an `obligation_type` drawn from `REG_BI_DISCLOSURE`, `FORM_ADV_DELIVERY`, `IPS_ARCHIVE`, and `FEE_DISCLOSURE`, and a `due_date` ISO date. An item also carries an `archive_hash` (null until archived), a `remediation_round` cycle counter starting at 0, and a `status` starting at `OPEN`. The full state set is `OPEN`, `REMEDIATION`, `SATISFIED`, and `ARCHIVED`.

A `ComplianceOfficer` drives the item through a cyclic remediation workflow keyed off the logical clock against the item's `due_date`. Satisfying moves an item from `OPEN` to `SATISFIED`; it requires the item be `OPEN` and the logical clock's date to be on or before the item's `due_date` — an obligation may not be satisfied once it has lapsed. Flagging remediation moves an item from `OPEN` to `REMEDIATION`; it requires the item be `OPEN` and the logical clock's date to be strictly after the item's `due_date` — only an overdue item may enter remediation. These two due-date conditions are complementary, and a request that violates either one (satisfying an already-past-due item, or flagging an item that is not yet overdue) is rejected with `ERR_COMPLIANCE_NOT_DUE` (409). Reopening moves an item from `REMEDIATION` back to `OPEN`, closing the cycle; as side effects it increments `remediation_round` by one and advances the item's `due_date` to thirty days after the current logical-clock date. Archiving moves a `SATISFIED` item to the terminal `ARCHIVED` state; its side effect stamps `archive_hash` with a tamper-evident SHA-256 hash computed over the item's `subject_type`, `subject_id`, `obligation_type`, and `created_at` joined together. Any of these transitions requested from a state where it is not defined is rejected with `ERR_INVALID_STATE` (409).

Compliance items can be listed and read by any role; the list may be filtered by `subject_id` or by `status`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that read a resource, drive a state transition, or otherwise modify an existing resource return `200 OK`. Every state-machine transition for an entity is driven through that entity's single `state` action endpoint by supplying the desired `action` in the request body (for example `VERIFY_KYC`, `PROPOSE`, `APPROVE`, `CALCULATE`, `FINALIZE`, `ACTIVATE`, `FREEZE`, `MARK_REVIEWED`, `SATISFY`, and so on), except for review completion, which has its own action endpoint. The request and response bodies are intentionally not tabulated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | BillingAdmin, ComplianceOfficer, Advisor |
| POST | `/fee-schedules` | Create a tiered fee schedule | BillingAdmin |
| GET | `/fee-schedules` | List fee schedules | BillingAdmin, Advisor, ComplianceOfficer |
| GET | `/fee-schedules/{id}` | Read a fee schedule | BillingAdmin, Advisor, ComplianceOfficer |
| PATCH | `/fee-schedules/{id}` | Edit tiers/minimum of an unlocked schedule | BillingAdmin |
| POST | `/portfolios` | Create a model portfolio | Advisor |
| GET | `/portfolios` | List portfolios | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/portfolios/{id}` | Read a portfolio | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/portfolios/{id}/publish` | Publish a portfolio | Advisor |
| POST | `/households` | Create a household | Advisor |
| GET | `/households` | List households (filter by `fee_schedule_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/households/{id}` | Read a household | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/households/{id}/close` | Close a household | Advisor |
| GET | `/households/{id}/clients` | List clients in a household | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/households/{id}/accounts` | List accounts in a household | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/clients` | Create a prospect client | Advisor |
| GET | `/clients` | List clients (filter by `household_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/clients/{id}` | Read a client | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/clients/{id}/state` | Drive the client onboarding state machine | Advisor |
| POST | `/investment-policy-statements` | Create a DRAFT policy statement | Advisor |
| GET | `/investment-policy-statements` | List policy statements (filter by `client_id`, `target_portfolio_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/investment-policy-statements/{id}` | Read a policy statement | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/investment-policy-statements/{id}/state` | Drive the policy-statement approval state machine | Advisor, ComplianceOfficer |
| POST | `/accounts` | Add an account | Advisor |
| GET | `/accounts` | List accounts (filter by `household_id`, `client_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/accounts/{id}` | Read an account | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/accounts/{id}/valuation` | Update market/equity value; recompute drift and household AUM | Advisor |
| POST | `/accounts/{id}/state` | Drive the account state machine | Advisor |
| GET | `/accounts/{id}/rebalance-orders` | List rebalance orders for an account | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/fee-runs` | Create a DRAFT fee run (OCC on household version) | BillingAdmin |
| GET | `/fee-runs` | List fee runs (filter by `household_id`, `fee_schedule_snapshot_id`) | BillingAdmin, Advisor, ComplianceOfficer |
| GET | `/fee-runs/{id}` | Read a fee run | BillingAdmin, Advisor, ComplianceOfficer |
| POST | `/fee-runs/{id}/state` | Drive the fee-run state machine | BillingAdmin |
| POST | `/financial-plans` | Create a DRAFT financial plan | Advisor |
| GET | `/financial-plans` | List financial plans (filter by `household_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/financial-plans/{id}` | Read a financial plan | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/financial-plans/{id}/state` | Drive the financial-plan parallel state machine | Advisor |
| GET | `/financial-plans/{id}/goals` | List goals under a plan | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/goals` | Create a goal under a plan | Advisor |
| GET | `/goals/{id}` | Read a goal | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/goals/{id}/fund` | Add funds to a goal | Advisor |
| POST | `/rebalance-orders` | Propose a rebalance for an account | Advisor |
| GET | `/rebalance-orders` | List rebalance orders (filter by `account_id`, `target_portfolio_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/rebalance-orders/{id}` | Read a rebalance order | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/rebalance-orders/{id}/state` | Drive the rebalance-order state machine | Advisor, ComplianceOfficer |
| POST | `/reviews` | Schedule a household review | Advisor |
| GET | `/reviews` | List reviews (filter by `household_id`) | Advisor, ComplianceOfficer, BillingAdmin |
| GET | `/reviews/{id}` | Read a review | Advisor, ComplianceOfficer, BillingAdmin |
| POST | `/reviews/{id}/complete` | Complete a scheduled review | Advisor |
| POST | `/compliance-items` | Open a compliance obligation | ComplianceOfficer |
| GET | `/compliance-items` | List compliance items (filter by `subject_id`, `status`) | ComplianceOfficer, Advisor, BillingAdmin |
| GET | `/compliance-items/{id}` | Read a compliance item | ComplianceOfficer, Advisor, BillingAdmin |
| POST | `/compliance-items/{id}/state` | Drive the compliance-item remediation state machine | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_IPS_MANDATE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CROSS_ENTITY_PRECONDITION` | 409 Conflict |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REVIEW_DATE_COLLISION` | 409 Conflict |
| `ERR_ALLOCATION_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_STALE_HOUSEHOLD_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FEE_RUN_OPEN` | 409 Conflict |
| `ERR_PORTFOLIO_NOT_PUBLISHED` | 422 Unprocessable Entity |
| `ERR_NO_APPROVED_IPS` | 409 Conflict |
| `ERR_COMPLIANCE_NOT_DUE` | 409 Conflict |
| `ERR_DUPLICATE_APPROVED_IPS` | 409 Conflict |
| `ERR_GOAL_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
