# Investment Policy Portfolio API — Product Requirements Document

## 1. Introduction

An investment advisory firm lives and dies by the discipline of its fiduciary process. Every household's objectives, risk tolerance, and target asset allocation are formalized in an Investment Policy Statement (IPS); every portfolio is then monitored for drift against that policy; every corrective rebalance is proposed, reviewed, and executed under compliance oversight with an awareness of embedded tax cost; and every change of policy is itself governed by a committee process whose votes and minutes form the audit trail regulators expect. This document specifies the Investment Policy Portfolio API, the system of record for that entire loop — from drafting an IPS and obtaining the client's signature, through drift-band monitoring, trade generation, withdrawal impact modeling, and performance reporting, to the amendment quorum and ratified minutes that keep the policy current.

The API is mounted under `/advisory`. Two technical commitments shape everything that follows. First, the server maintains a logical clock (§2.5): every timestamp-dependent rule in the system — restriction windows, review due dates, proposal expiry, same-day trade voids, future-dating rejections — reads that clock rather than the wall clock. Second, the firm operates under strict segregation of duties: advisors propose, compliance officers approve, committee members vote, and the committee chair ratifies, with no actor permitted to wear two hats on the same artifact. Section 2 defines the system-wide contracts (roles, envelope, pagination, precision, concurrency, the event-sourced cash ledger); Section 3 walks the business workflows; Section 4 tabulates the endpoints; Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The recognized roles are exactly six: `Advisor`, `ComplianceOfficer`, `Client`, `CommitteeMember`, `CommitteeChair`, and `PlatformAdmin`. A request with a missing or blank header, or whose `X-User-Role` is not one of these six spellings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity works as follows. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity; ownership checks on any resource that belongs to a client — the client record itself, its IPS records and allocation targets, its portfolios, positions, withdrawal requests, performance reports, and cash-flow events — compare the resource's owning-client foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). On the collection list endpoints — portfolios, IPS records, positions, withdrawal requests, performance reports, and cash-flow events — this ownership rule acts as a visibility scope rather than a rejection: a `Client`'s list results contain only its own household's rows, and query-parameter filters narrow further within that scope, so a filter naming another household's id yields an empty page rather than an ownership error. The same ownership error protects one advisor-scoped artifact: withdrawing a policy amendment requires the caller's `X-User-ID` to equal the amendment's `proposed_by_user_id`. When `X-User-Role` is `Advisor`, `ComplianceOfficer`, `CommitteeMember`, `CommitteeChair`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `proposed_by_user_id` on an amendment, `recorded_by_user_id` on a minute, `decided_by_user_id` on a proposal, `finalized_by_user_id` on an amendment, or `ratified_by_user_id` on a minute — but it is never compared to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — clients, benchmarks, IPS records, allocation targets, portfolios, securities, positions, restricted-list entries, rebalance proposals, trade instructions, withdrawal requests, performance reports, amendments, and committee minutes — carries a standard system-managed field set. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. `version` is an integer that increments by exactly one on every mutation of the resource, including mutations driven by system cascades, and anchors the optimistic-concurrency rules of §2.8.

The cash-flow ledger entry is the sole exception. A `CashFlowEvent` is an immutable append-only record and carries only `id` and `created_at` from the standard set; it has no `updated_at` and no `version`.

### 2.5. The Logical Clock

The server keeps a logical clock that every timestamp-dependent rule consults. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any operator sets it, the logical clock reads that default and never the wall clock. A `PlatformAdmin`-only capability sets the clock: the request carries `to_iso8601`, the target instant, and the response echoes the new reading as `current_utc`. This is the only operation `PlatformAdmin` may perform.

All system-assigned timestamps — `activated_at`, `generated_at`, `expires_at`, `executed_at`, `voided_at`, `modeled_at`, `finalized_at`, `ratified_at`, `ratified_at`-style audit stamps, and `updated_at` — read this clock. So do the derived rules: whether a restricted-list entry is `SCHEDULED`, `ACTIVE`, or `EXPIRED`; whether an IPS review is overdue; whether a proposal has outlived its time-to-live; whether a trade void is still inside its same-day window; and whether a cash movement or committee minute is future-dated. Every ISO 8601 UTC datetime the server emits — the envelope's `api_request_timestamp`, resource `created_at` and `updated_at`, the clock-derived fields above, `next_review_due`, ledger `occurred_at`, restriction `effective_from` and `effective_to`, and the clock-set response's `current_utc` — is serialized with exactly three fractional digits and a `Z` suffix, so the startup default reads `2026-08-01T00:00:00.000Z`.

### 2.6. Monetary Precision, Percentages, and Rounding Conventions

All monetary quantities are integer cents — `amount_cents`, `cash_balance_cents`, `total_value_cents`, `market_value_cents`, `cost_basis_cents`, and their kin are never fractional. Prices are likewise integer cents and must be at least 1. Allocation percentages (`target_pct`, `band_pct`) are numbers carried to exactly two decimal places.

Three rounding conventions recur throughout the document and are contractual. When a percentage is converted to basis points or a value ratio is converted to basis points, the result is rounded half-up to an integer basis point; each percentage point corresponds to 100 basis points. When a trade or liquidation quantity must be a whole number of units, the rebalance trade generator rounds down (floor) per line, while the withdrawal impact model rounds up (ceiling) so proceeds meet the need; quantities are always whole units. When a tax amount is estimated, each line is rounded half-up to integer cents before any summation, and the aggregate is never re-rounded. The capital-gains rate used for every tax estimate and accrual is 2,000 basis points — twenty percent of the realized gain — and it accrues only against portfolios whose `tax_status` is `TAXABLE`; `TAX_DEFERRED` and `TAX_EXEMPT` portfolios accrue zero.

### 2.7. Validation Order and Error Precedence

Checks run in a fixed priority order, and when several checks would fail, the request is rejected with the error from the earliest category:

1. **Authentication** — headers present, non-blank, role declared (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the acting role appears in the endpoint's authorized list (`ERR_FORBIDDEN_ROLE`).
3. **Ownership** — entity-backed ownership for the `Client` role and amendment-proposer ownership (`ERR_NOT_RESOURCE_OWNER`).
4. **Request shape** — required fields present; types valid; enum values within their declared sets; ranges enforced (risk scores between 1 and 100 inclusive; `target_pct` greater than 0 and at most 100; `band_pct` greater than 0 and at most 50; quantities at least 1 on intake; `amount_cents` greater than 0; price inputs at least 1; `review_cadence_months` between 1 and 24 inclusive; dates in `YYYY-MM-DD` form; datetimes in ISO 8601 UTC); a duplicate `asset_class` inside a `targets` array; unknown request fields — all rejected as `ERR_INVALID_REQUEST` (HTTP 400).
5. **Path existence** — path identifiers are resolved strictly left to right; the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404).
6. **Body references** — ids carried in the body (`client_id`, `benchmark_id`, `portfolio_id`, `security_id`, `ips_id`, `proposed_benchmark_id`, `ratified_minute_id`, and every element of `amendment_refs`) must resolve to existing resources, else `ERR_INVALID_REFERENCE` (HTTP 422).
7. **Lifecycle state** — the from-state preconditions of every state machine (the 409 family: `ERR_CLIENT_INVALID_STATE`, `ERR_IPS_INVALID_STATE`, `ERR_PORTFOLIO_INVALID_STATE`, `ERR_PORTFOLIO_NOT_ACTIVE`, `ERR_NO_ACTIVE_IPS`, `ERR_SECURITY_INVALID_STATE`, `ERR_BENCHMARK_INVALID_STATE`, `ERR_PROPOSAL_INVALID_STATE`, `ERR_TRADES_BLOCKED`, `ERR_TRADE_INVALID_STATE`, `ERR_WITHDRAWAL_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_AMENDMENT_INVALID_STATE`, `ERR_MINUTE_INVALID_STATE`).
8. **Optimistic concurrency** — the two stale-version checks of §2.8 (`ERR_STALE_IPS_VERSION`, `ERR_STALE_PORTFOLIO_VERSION`, HTTP 412).
9. **Compliance and segregation-of-duties gates** — `ERR_SECURITY_RESTRICTED`, `ERR_SECURITY_NOT_TRADEABLE`, `ERR_SOD_SELF_VOTE`, `ERR_SOD_MINUTE_SELF_RATIFY`, `ERR_AMENDMENT_MINUTE_NOT_RATIFIED` (HTTP 422).
10. **Referential business checks** — `ERR_BENCHMARK_NOT_ACTIVE`, `ERR_BENCHMARK_IN_USE`, `ERR_SECURITY_IN_USE`, `ERR_PROPOSAL_STALE_PIN`, `ERR_AMENDMENT_NOT_IN_MINUTE` (HTTP 422).
11. **Business constraints** — `ERR_ALLOCATION_SUM_INVALID`, `ERR_RISK_TOLERANCE_MISMATCH`, `ERR_RESTRICTION_WINDOW_OVERLAP`, `ERR_INVALID_DATE_RANGE`, `ERR_REPORT_PERIOD_OVERLAP`, `ERR_POSITION_EXISTS`, `ERR_AMENDMENT_EMPTY_CHANGES`, `ERR_DUPLICATE_VOTE`, `ERR_DRIFT_NOT_BREACHED` (HTTP 422).
12. **Temporal rules** — `ERR_TRADE_VOID_WINDOW_EXPIRED`, `ERR_EVENT_IN_FUTURE`, `ERR_MEETING_DATE_IN_FUTURE` (HTTP 422).
13. **Fiscal rules** — `ERR_WITHDRAWAL_EXCEEDS_VALUE`, `ERR_INSUFFICIENT_CASH`, `ERR_WITHDRAWAL_PLAN_INFEASIBLE`, `ERR_PORTFOLIO_NOT_EMPTY`, `ERR_OPEN_WORK_ITEMS` (HTTP 422).

Two consequences of this ordering are worth internalizing. At proposal generation, the stale-portfolio-version rejection (category 8) fires before the drift-breach requirement (category 11), so a caller holding an old portfolio `version` hears about staleness even if the trigger precondition would also fail. At amendment finalization, the quorum state check and the stale-IPS-version rejection precede the minute and benchmark checks: a non-`QUORUM_REACHED` amendment surfaces `ERR_AMENDMENT_INVALID_STATE`, and a stale view of the IPS surfaces `ERR_STALE_IPS_VERSION`, before the system ever evaluates the ratified-minute gate.

### 2.8. Optimistic Concurrency Control

Exactly two write operations are protected by optimistic concurrency control, and each names its own version field.

Generating a rebalance proposal requires the request to carry `expected_portfolio_version`, holding the client's last observed `version` of the target portfolio. If the portfolio's current `version` differs — because another writer has mutated the portfolio since the client last read it, for example by generating a proposal that superseded earlier ones — the generation is rejected with `ERR_STALE_PORTFOLIO_VERSION` (HTTP 412).

Finalizing an amendment requires the request to carry `expected_ips_version`, holding the finalizer's last observed `version` of the target IPS. If the IPS's current `version` differs — for instance because another amendment was finalized against it first under the quorum process — the finalization is rejected with `ERR_STALE_IPS_VERSION` (HTTP 412).

No other endpoint accepts a version field; requests to any other endpoint must not include one.

### 2.9. The Cash Ledger: Event-Sourced Projections

A portfolio's cash position is not a stored balance that operations overwrite; it is a projection over an append-only ledger of `CashFlowEvent` records. Each event records the owning `portfolio_id`, the effective `occurred_at` instant, a `kind`, a signed `amount_cents`, and two snapshots taken at append time: `balance_after_cents`, the running cash balance immediately after the event is applied, and `valuation_before_cents`, the portfolio's `total_value_cents` immediately before the event is applied. The signed convention is fixed: deposits, trade proceeds, settlement proceeds, and void refunds are positive; withdrawals, disbursements, and buys are negative. The event `kind` is one of `MANUAL_DEPOSIT`, `MANUAL_WITHDRAWAL`, `TRADE_EXECUTION`, `TRADE_VOID`, `WITHDRAWAL_DISBURSEMENT`, or `SETTLEMENT_PROCEEDS`.

Ledger order is arrival (append) order. The `occurred_at` value — which may be backdated — influences reporting windows only and never reorders the ledger; `balance_after_cents` is always computed at append time from the prior ledger tip. A portfolio's `cash_balance_cents` at any moment is the sum of `amount_cents` across its events, with immediate consistency after every append.

Each event also carries a polymorphic provenance pair. `source_type` is one of `MANUAL`, `TRADE`, or `WITHDRAWAL`, and `source_id` resolves through it: when `source_type` is `TRADE`, `source_id` is the `id` of the originating `TradeInstruction`; when `WITHDRAWAL`, the `id` of the originating `WithdrawalRequest`; when `MANUAL`, `source_id` is null. The `source_id` is a soft reference only — no referential cascade follows it.

From the ledger and the positions, valuations compose deterministically. A position's `market_value_cents` is its `quantity` multiplied by the security's current `price_cents`. A portfolio's `total_value_cents` is `cash_balance_cents` plus the sum of `market_value_cents` over its positions. A client's `total_aum_cents` is the sum of `total_value_cents` over that client's portfolios whose `lifecycle_status` is `OPEN`, `ACTIVE`, or `FROZEN`; `CLOSED` portfolios are excluded.

### 2.10. Two Independent Portfolio Dimensions

Every portfolio carries two state dimensions that never interfere with one another. `lifecycle_status` — `OPEN`, `ACTIVE`, `FROZEN`, or `CLOSED` — is endpoint-driven: operators move it deliberately through activation, freezes, and closure. `drift_status` — `UNTRACKED`, `WITHIN_BANDS`, or `BREACHED` — is computed by the drift assessment of §3.5 and changes only in response to market, ledger, or policy events. A drift transition never alters `lifecycle_status`, and a lifecycle transition never alters `drift_status` except where a specific rule says so (activation runs an assessment; closure sets `WITHIN_BANDS` vacuously). Nearly every portfolio-scoped operation gates on `lifecycle_status` being `ACTIVE`; attempts against an `OPEN`, `FROZEN`, or `CLOSED` portfolio are rejected with `ERR_PORTFOLIO_NOT_ACTIVE`.

### 2.11. Cascades and Cross-Entity Consistency

State changes propagate downward so that no artifact outlives the policy or relationship that authorizes it. When a client's IPS is superseded at client signature, every rebalance proposal pinned to the superseded IPS transitions to `EXPIRED`, and every `PENDING` or `BLOCKED` trade instruction of those proposals transitions to `CANCELLED`. The same pin-expiry cascade fires when a client's IPS records are archived at client termination, and when an amendment finalization advances the IPS `version` past the pin a proposal was generated against. A successful proposal generation likewise supersedes the portfolio's earlier non-terminal proposals. Repricing a security ripples through every position holding it, every affected portfolio's totals and drift status, and every withdrawal model that has gone stale. Each resource touched by a cascade has its own `updated_at` refreshed and its own `version` incremented by one — cascades are real mutations, not read-time derivations.

### 2.12. Segregation of Duties and the Fiduciary Record

Governance artifacts separate the hand that drafts from the hand that approves. An advisor who drafts an amendment is recorded in `proposed_by_user_id` and may not vote on it; a committee member who records a minute is recorded in `recorded_by_user_id` and may not ratify it. Each committee member casts at most one vote per amendment. An amendment becomes eligible for finalization only when a committee minute that has been ratified by the chair documents its decision — the minute must reference the amendment, and the amendment must reference the minute back at finalize time. These gates, and the error codes attached to them, appear in context in §3.8.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Relationship Termination

An `Advisor` opens a relationship by creating a client with the household's legal `full_name` and a `risk_tolerance_score` between 1 and 100 inclusive. The client begins life in `PROSPECT` status. Activation, an `Advisor` action, moves the client `PROSPECT → ACTIVE`; attempting it from any other state is rejected with `ERR_CLIENT_INVALID_STATE`. Only an `ACTIVE` client may hold an active policy or an active portfolio: creating an IPS draft for a non-`ACTIVE` client is rejected with `ERR_CLIENT_INVALID_STATE`, as is submitting one, and portfolio activation applies the same gate. A client's `total_aum_cents` aggregates the value of the relationship as defined in §2.9. Advisors and compliance officers may list clients, optionally filtering by `status`; a `Client` reading its own record is an ownership-checked operation, and a `Client` presenting another household's id is rejected with `ERR_NOT_RESOURCE_OWNER`.

Termination is the reverse gate. An `Advisor` terminates a client, moving it `ACTIVE → TERMINATED`, only when every portfolio of the client has `lifecycle_status` equal to `CLOSED`; otherwise the request is rejected with `ERR_CLIENT_INVALID_STATE`. `TERMINATED` is the client's terminal state, and the transition cascades: every IPS of the client in `DRAFT`, `PENDING_COMPLIANCE`, `PENDING_CLIENT`, or `ACTIVE` transitions to `ARCHIVED`; every rebalance proposal pinned to an IPS that the cascade just archived transitions to `EXPIRED`; and every `PENDING` or `BLOCKED` trade instruction belonging to those expired proposals transitions to `CANCELLED`. The client record's own `updated_at` and `version` refresh, as do those of every resource the cascade touches.

### 3.2. The Investment Policy Statement Lifecycle

An `Advisor` drafts an IPS for an `ACTIVE` client by supplying the owning `client_id`, the policy `benchmark_id`, the `objective_text` documenting the investment objective, a `risk_tolerance_score` snapshot between 1 and 100 inclusive, and optionally `review_cadence_months` — the number of months between required reviews, between 1 and 24 inclusive, defaulting to 12 when omitted. The new statement starts in `DRAFT`.

While the statement is in `DRAFT`, the advisor defines its target allocation through an atomic bulk replacement of the allocation-target set. The request carries a `targets` array; each element names an `asset_class` — one of `US_EQUITY`, `INTL_EQUITY`, `FIXED_INCOME`, `CASH_EQUIVALENT`, or `ALTERNATIVES` — a `target_pct` greater than 0 and at most 100 with two decimal places, and a `band_pct`, the absolute drift band in percentage points, greater than 0 and at most 50 with two decimal places. The replacement is all-or-nothing: every element is validated, and the whole set is swapped atomically, with each stored row's `ips_id` taken from the path. A duplicate `asset_class` inside the array is a request-shape failure (`ERR_INVALID_REQUEST`). Replacement is permitted only while the statement is in `DRAFT` — against any other status it is rejected with `ERR_IPS_INVALID_STATE` — and it deliberately does not modify the IPS's own `version`.

Submitting the statement moves it `DRAFT → PENDING_COMPLIANCE` under an ordered battery of checks. The state check fires first: a statement not in `DRAFT` is rejected with `ERR_IPS_INVALID_STATE`. Then the business constraints: at least one allocation target must exist and the `target_pct` values must total exactly 100.00, else `ERR_ALLOCATION_SUM_INVALID`; the statement's `risk_tolerance_score` must sit within 10 points of the owning client's current `risk_tolerance_score` in either direction, else `ERR_RISK_TOLERANCE_MISMATCH`; and the client must be `ACTIVE`, else `ERR_CLIENT_INVALID_STATE`.

A `ComplianceOfficer` then reviews the submission. Compliance approval moves `PENDING_COMPLIANCE → PENDING_CLIENT`; compliance rejection — which may carry an optional `reason` — returns it `PENDING_COMPLIANCE → DRAFT` for rework. Either action against a statement not in `PENDING_COMPLIANCE` is rejected with `ERR_IPS_INVALID_STATE`.

The client itself then decides. Client signature moves `PENDING_CLIENT → ACTIVE` and is ownership-checked: the acting client's id must equal the statement's `client_id`, else `ERR_NOT_RESOURCE_OWNER`; the client must still be `ACTIVE`, else `ERR_CLIENT_INVALID_STATE`; and the referenced benchmark must still be `ACTIVE`, else `ERR_BENCHMARK_NOT_ACTIVE`. Signature has far-reaching effects. Any prior `ACTIVE` statement of the same client transitions to `SUPERSEDED`, and the newly active statement records that predecessor in `supersedes_ips_id` (null when there is no predecessor). Every rebalance proposal pinned to the superseded statement transitions to `EXPIRED`, and its `PENDING` or `BLOCKED` trade instructions transition to `CANCELLED`. The statement's `activated_at` — which remains null until the statement first reaches `ACTIVE` — is set to the current logical clock, and `next_review_due` is computed by adding `review_cadence_months` calendar months to `activated_at`, clamping the day-of-month to the target month's last day when necessary — a statement signed on 31 January with a one-month cadence comes due on 28 February. Finally, the drift status of every non-`CLOSED` portfolio of the client is recomputed, moving each from `UNTRACKED` to `WITHIN_BANDS` or `BREACHED` as the assessment finds. Client decline — also ownership-checked, with an optional `reason` — returns `PENDING_CLIENT → DRAFT`.

Review cadence is enforced by derivation, not by a stored flag that ages. On any read, `review_overdue` is true exactly when the statement's status is `ACTIVE` and the current logical clock is strictly later than `next_review_due`; at the precise instant of `next_review_due` the review is not yet overdue. When an `Advisor` records a completed review against an `ACTIVE` statement (any other state yields `ERR_IPS_INVALID_STATE`), the schedule advances by repeatedly adding `review_cadence_months` to `next_review_due` — same month-addition clamp — until the result lands strictly in the future; a single completion can therefore consume several missed cycles. `SUPERSEDED` and `ARCHIVED` are terminal. IPS records may be listed with filters on `client_id`, `benchmark_id`, `supersedes_ips_id`, and `status`; a `Client` sees only its own household's rows.

### 3.3. Securities, Market Pricing, and the Restricted List

The compliance desk owns the security catalog. A `ComplianceOfficer` registers a security with an uppercase `ticker` (letters, digits, and dots; unique by exact match — a duplicate is rejected as `ERR_INVALID_REQUEST`), its `asset_class` from the same five-class enum used by allocation targets, and an `initial_price_cents` of at least 1. The security's `price_cents` is seeded from `initial_price_cents` at creation, begins in `LISTED` trading status, and changes only when repriced.

Repricing is a compliance action carrying `new_price_cents` (again at least 1) and is deliberately loud. The security's `price_cents` updates; every position holding the security recomputes its `market_value_cents` and `unrealized_gain_cents` (each such position's `version` increments); every affected portfolio recomputes `total_value_cents` and re-runs the drift assessment (each such portfolio's `version` increments); and every withdrawal request of an affected portfolio that had been modeled reverts from `MODELED` to `SUBMITTED` with its modeled fields cleared, since the model was priced at stale quotes. A reprice that does not touch any held position changes only the security itself.

Trading status moves `LISTED → HALTED` and back `HALTED → LISTED` freely under compliance control, and `LISTED → DELISTED` or `HALTED → DELISTED` only when no position anywhere holds more than zero units of the security, else `ERR_SECURITY_IN_USE`. A status change attempted from a wrong from-state — halting an already-`HALTED` security, listing a `DELISTED` one — is rejected with `ERR_SECURITY_INVALID_STATE`. `DELISTED` is terminal. The catalog can be listed with filters on `ticker`, `asset_class`, and `trading_status`.

The restricted list expresses compliance embargoes as time windows. A `ComplianceOfficer` creates an entry naming the `security_id`, a `restriction_level` of `NO_BUY` (sells remain permitted) or `NO_TRADE` (both buys and sells are blocked), an `effective_from` window start that is inclusive, an `effective_to` window end that is exclusive, and an optional `reason` defaulting to empty. The window must be non-degenerate: a start not strictly earlier than the end is rejected with `ERR_INVALID_DATE_RANGE`. Windows for the same security observe half-open semantics — two entries whose intervals overlap at all are rejected with `ERR_RESTRICTION_WINDOW_OVERLAP`, while mere adjacency, where one entry's `effective_to` equals the next entry's `effective_from`, is permitted. An entry's `status` is never stored; it derives from the logical clock as `SCHEDULED` when the clock is earlier than `effective_from`, `ACTIVE` when the clock is at or after `effective_from` and before `effective_to`, and `EXPIRED` at or after `effective_to`. A compliance officer may also terminate an entry early, which rewrites `effective_to` to the current logical clock so the entry becomes `EXPIRED`; terminating an entry that is already `EXPIRED` is rejected with `ERR_INVALID_DATE_RANGE`. Entries can be listed filtered by `security_id`, `restriction_level`, or the derived `status`.

Enforcement bites at four moments: while generating buys for a rebalance plan (restricted securities are simply never selected), while approving a proposal (affected pending trades are blocked, §3.5), while releasing a blocked trade, and while executing an approved proposal. The blocking rule is side-aware: a `NO_TRADE` entry blocks both `BUY` and `SELL`, while a `NO_BUY` entry blocks `BUY` only. Only `ACTIVE` entries block; `SCHEDULED` and `EXPIRED` entries are inert. Notably, the restricted list does not block position transfer-ins (§3.4) — the embargo governs trading, not custody intake.

### 3.4. Portfolios, Positions, and Cash Movements

An `Advisor` creates a portfolio for a client by supplying `client_id`, a display `name`, and a `tax_status` of `TAXABLE`, `TAX_DEFERRED`, or `TAX_EXEMPT` — the flag that gates all capital-gains tax accrual for the account. The portfolio starts in `OPEN` lifecycle with zero cash, and its `drift_status` is derived: `UNTRACKED` while the client has no `ACTIVE` IPS, and `WITHIN_BANDS` while the account holds no value.

Activation moves the portfolio `OPEN → ACTIVE` and is the onboarding checkpoint for the whole policy apparatus: the portfolio must be `OPEN` (else `ERR_PORTFOLIO_INVALID_STATE`), the owning client must be `ACTIVE` (else `ERR_CLIENT_INVALID_STATE`), and the client must hold an `ACTIVE` IPS (else `ERR_NO_ACTIVE_IPS`). Activation runs the drift assessment immediately so the portfolio enters service with a fresh `drift_status`. Thereafter a `ComplianceOfficer` may freeze an `ACTIVE` portfolio (`ACTIVE → FROZEN`) and unfreeze it (`FROZEN → ACTIVE`); either transition from a wrong from-state is rejected with `ERR_PORTFOLIO_INVALID_STATE`. While a portfolio is not `ACTIVE`, the operational surface closes: creating positions, recording cash movements, generating, approving, revising, or executing proposals, and modeling, approving, or settling withdrawals are all rejected with `ERR_PORTFOLIO_NOT_ACTIVE`.

Closure is the deliberate wind-down. An `Advisor` closes an `ACTIVE` portfolio only when every position stands at zero units and `cash_balance_cents` is zero, else `ERR_PORTFOLIO_NOT_EMPTY`, and only when no withdrawal request stands in `SUBMITTED`, `MODELED`, or `APPROVED` and no rebalance proposal stands in `PROPOSED`, `NEEDS_REVISION`, or `APPROVED`, else `ERR_OPEN_WORK_ITEMS`. Closure moves `ACTIVE → CLOSED` and sets `drift_status` to `WITHIN_BANDS` — vacuously true, since the account is worth nothing. `CLOSED` is terminal, and a closed portfolio drops out of the client's `total_aum_cents`.

Positions enter the book by transfer-in, an `Advisor` action carrying `portfolio_id`, `security_id`, a `quantity` of at least 1, and `opening_cost_basis_cents` of at least 0, which seeds the position's `cost_basis_cents`. One position exists per security per portfolio: a second transfer-in for the same `(portfolio_id, security_id)` pair is rejected with `ERR_POSITION_EXISTS`. The security must be `LISTED`, else `ERR_SECURITY_NOT_TRADEABLE`; as noted in §3.3, the restricted list does not block transfer-ins. On creation the position's `market_value_cents` is computed as `quantity` times the security's current `price_cents`, `unrealized_gain_cents` as `market_value_cents` minus `cost_basis_cents`, and the portfolio's totals and drift status are recomputed — with the same staleness revert of `MODELED` withdrawal requests described in §3.6, since intake is a portfolio-affecting mutation. Positions list with filters on `portfolio_id` and `security_id`.

Cash moves through manual movements recorded by an `Advisor`. The request carries a `direction`, an `amount_cents` greater than 0, and an `occurred_at` effective instant; the flow may be backdated but never future-dated — an `occurred_at` later than the current logical clock is rejected with `ERR_EVENT_IN_FUTURE`. A deposit appends a `MANUAL_DEPOSIT` event with a positive signed amount; a withdrawal appends a `MANUAL_WITHDRAWAL` event with a negative signed amount and is permitted only while the amount does not exceed the current `cash_balance_cents`, else `ERR_INSUFFICIENT_CASH`. Either direction records `balance_after_cents`, `valuation_before_cents`, a `source_type` of `MANUAL`, and a null `source_id` on the event, then recomputes the portfolio's cash, total value, and drift status, bumps the portfolio's `version`, and reverts any `MODELED` withdrawal requests of the portfolio to `SUBMITTED`. The ledger is readable through the cash-flow event list, filterable by `portfolio_id`, by `kind`, and by an `occurred_at` window bounded by `from` and `to`; a `Client` sees events only for its own portfolios. Portfolios themselves list with filters on `client_id`, `lifecycle_status`, and `drift_status`.

### 3.5. Drift Monitoring and Rebalance Proposals

**Drift assessment.** The system continually re-derives each portfolio's `drift_status`. Assessment fires after any of these events: a reprice touching a held position; a trade execution or void; a withdrawal settlement; a cash movement; a position creation; an IPS activation by client signature; and an amendment finalization. The algorithm is fixed. The assessment total is the portfolio's `cash_balance_cents` plus the sum of its positions' `market_value_cents`. If the owning client has no `ACTIVE` IPS, the status is `UNTRACKED` and evaluation stops. If the total is zero, the status is `WITHIN_BANDS` and evaluation stops. Otherwise, for each allocation target of the active IPS — iterated in the fixed class order `US_EQUITY`, `INTL_EQUITY`, `FIXED_INCOME`, `CASH_EQUIVALENT`, `ALTERNATIVES` — the class market value is the sum of `market_value_cents` over positions whose security belongs to the class, with the portfolio's cash added to the `CASH_EQUIVALENT` sleeve. The class's actual weight in basis points is its market value times 10,000 divided by the total, rounded half-up to an integer; the target weight in basis points is `target_pct` times 100, rounded half-up; and the band in basis points is `band_pct` times 100, rounded half-up. A class breaches when its actual weight differs from its target weight by strictly more than the band — equality with the band edge is not a breach. Independently, if any held class — a security class present among positions with more than zero units — has no allocation target at all, that untargeted holding is itself a breach. Any breach sets `BREACHED`; a clean sweep sets `WITHIN_BANDS`. Each transition refreshes the portfolio's `updated_at` and `version`.

**Generation.** An `Advisor` generates a rebalance proposal by naming the `portfolio_id`, a `trigger_type` of `DRIFT_BREACH`, `CASH_FLOW`, or `MANUAL`, and the OCC field `expected_portfolio_version` (§2.8 — a stale view is rejected with `ERR_STALE_PORTFOLIO_VERSION`). The portfolio must be `ACTIVE`, else `ERR_PORTFOLIO_NOT_ACTIVE`; and a `DRIFT_BREACH` trigger is honored only while the portfolio's `drift_status` is `BREACHED`, else `ERR_DRIFT_NOT_BREACHED` — with the staleness check firing first, per §2.7. Generation supersedes the portfolio's earlier open work: every existing proposal of the same portfolio in `PROPOSED` or `NEEDS_REVISION` transitions to `EXPIRED`, and its `PENDING` or `BLOCKED` trades transition to `CANCELLED`. The new proposal pins the client's currently `ACTIVE` IPS by recording `ips_id` and the IPS's current `version` in `pinned_ips_version`, stamps `generated_at` from the logical clock, and sets `expires_at` seven days later. The proposal is born in `PROPOSED` status; generation also increments the portfolio's `version`.

**Trade generation.** The proposal's trade list is produced at generation (and again at revision) from the pre-trade snapshot of the portfolio's `total_value_cents`, which is never recomputed mid-generation. Targets are processed in the same fixed class order. For each class, the target value is `target_pct` times the total divided by 100, rounded half-up to integer cents before any class comparison; the class market value counts cash toward `CASH_EQUIVALENT`; and the class delta is target value minus class market value. An overweight class (negative delta) sells: candidate lots are the class's positions with more than zero units, ranked by unrealized gain per unit ascending — the exact rational quotient of `market_value_cents` minus `cost_basis_cents` over `quantity`, with ties broken by the position's `created_at` ascending. Walking lots in rank order against the remaining overweight amount, each lot sells the smaller of its full `quantity` and the remaining amount divided by the security's current `price_cents` rounded down to whole units; a lot yielding at least one unit emits a `SELL` instruction at that quantity with `pinned_price_cents` set to the current price, and the remaining amount shrinks by the units sold times the price. Residual dust smaller than one unit's price stays unsold. An underweight class (positive delta) buys: candidates are securities of the class that are `LISTED` and not blocked from buying by any `ACTIVE` restricted-list entry, ranked by `price_cents` ascending with ties broken by `created_at` ascending; the first-ranked security receives a `BUY` for the delta divided by its price, rounded down, emitted only when that is at least one unit. If no candidate exists, the underweight amount simply stays in cash. The `CASH_EQUIVALENT` sleeve never generates trades at all — a cash shortfall or excess is absorbed by the waterfall below, never by synthetic cash instruments. Quantities are floored per line first, and proceeds are summed afterward; the aggregate is never rounded.

Each generated `TradeInstruction` records its `proposal_id` and `security_id`, the `side` (`BUY` or `SELL`), the whole-unit `quantity` of at least 1, and the `pinned_price_cents` observed at generation — estimates only, since execution settles at the then-current price. `est_proceeds_cents` is the quantity times the pinned price. `est_tax_impact_cents` is nonzero only for a `SELL` in a `TAXABLE` portfolio: the estimated gain — the pinned proceeds minus the basis relief those units would draw — floored at zero, multiplied by the 2,000-basis-point gains rate, divided by 10,000, and rounded half-up; buys and non-taxable portfolios carry zero. Trades begin in `PENDING` status.

**Cash waterfall.** The proposal's money arithmetic then resolves in a pinned order that is contractual. Sells are sized first, exactly as above, independent of tax. The estimated tax reserve is the sum over `SELL` lines of the same per-line formula as `est_tax_impact_cents` — each line rounded half-up before summing — and is zero for `TAX_DEFERRED` and `TAX_EXEMPT` portfolios; this total lands in `est_tax_reserve_cents`. The amount available for buys is current `cash_balance_cents` plus total sell proceeds minus the reserve. Buy trades are then trimmed in the fixed class order: walking the generated `BUY` instructions, while a buy's cost exceeds the remaining available amount, its quantity is reduced to the remaining amount divided by its pinned price rounded down, and a trade whose quantity floors to zero is dropped. Sells are never recomputed after the reserve is known. The proposal's `total_sells_cents` and `total_buys_cents` are the sums of `est_proceeds_cents` over the generated sells and the post-trim buys respectively, and `cash_delta_cents` is the projected post-rebalance cash — current cash plus sells minus the reserve minus the trimmed buys — minus the current `cash_balance_cents`.

**Review loop.** A `ComplianceOfficer` reviews a `PROPOSED` plan in one of three ways. Approval moves `PROPOSED → APPROVED` and first re-checks the context: the portfolio must still be `ACTIVE`, else `ERR_PORTFOLIO_NOT_ACTIVE`, and the pinned policy must still be current — the pinned IPS still `ACTIVE` and `pinned_ips_version` still equal to the IPS's current `version` — else `ERR_PROPOSAL_STALE_PIN`. Approval runs a compliance scan over the plan: every `PENDING` trade whose security has an `ACTIVE` restriction blocking its side, or whose security is no longer `LISTED`, transitions to `BLOCKED`. Approval records the acting officer in `decided_by_user_id`. Requesting changes moves `PROPOSED → NEEDS_REVISION`, optionally carrying a `reason`, and likewise records `decided_by_user_id`. Rejection — also with optional `reason` and `decided_by_user_id` — is terminal and may happen from `PROPOSED` or `NEEDS_REVISION`; in both cases every `PENDING` or `BLOCKED` trade of the proposal transitions to `CANCELLED`. The advisor's parallel escape hatch, cancellation, moves `PROPOSED` or `NEEDS_REVISION` to `CANCELLED` with the same trade-cancel cascade. Any of these transitions from a wrong from-state is rejected with `ERR_PROPOSAL_INVALID_STATE`.

A proposal in `NEEDS_REVISION` can be reworked by an `Advisor`. Revision requires the portfolio still `ACTIVE` (else `ERR_PORTFOLIO_NOT_ACTIVE`) and, when the proposal's `trigger_type` is `DRIFT_BREACH`, the portfolio's `drift_status` still `BREACHED`, else `ERR_DRIFT_NOT_BREACHED`. Revision cancels every `PENDING` or `BLOCKED` trade of the proposal, regenerates the full trade list at current prices through the generation and waterfall rules above, recomputes `total_buys_cents`, `total_sells_cents`, `est_tax_reserve_cents`, and `cash_delta_cents`, refreshes `pinned_ips_version` to the IPS's current `version`, and resets `expires_at` to seven days from the present — returning the proposal to `PROPOSED`.

**Execution.** An `Advisor` executes an `APPROVED` proposal. The checks fire in priority order: the proposal must be `APPROVED`, else `ERR_PROPOSAL_INVALID_STATE`; the portfolio must be `ACTIVE`, else `ERR_PORTFOLIO_NOT_ACTIVE`; no trade of the proposal may stand in `BLOCKED`, else `ERR_TRADES_BLOCKED`; the compliance gates then re-examine each trade, rejecting with `ERR_SECURITY_RESTRICTED` when an `ACTIVE` entry blocks the trade's side and `ERR_SECURITY_NOT_TRADEABLE` when the security is not `LISTED`; and the pin is re-verified — the pinned IPS still `ACTIVE` with `pinned_ips_version` equal to its current `version`, else `ERR_PROPOSAL_STALE_PIN`. Execution fills every `PENDING` trade at the security's current `price_cents`, never the pinned estimate, in a deterministic ledger order: all `SELL` trades first in the fixed class order, then all `BUY` trades in the fixed class order, with ties inside a class broken by the trade's `created_at` ascending; ledger events append in exactly that execution order. Each executed trade stamps `executed_at` and `executed_price_cents` from the clock and the fill; both fields remain null until the trade reaches `EXECUTED`.

The bookkeeping per fill follows the average-cost relief rule. A `SELL` of some number of units from a lot relieves basis proportionally: the relief is the lot's `cost_basis_cents` times the units sold divided by the lot's prior `quantity`, rounded half-up once; the realized gain is the units times the executed price minus that pinned relief; the lot's `cost_basis_cents` falls by the relief and its `quantity` by the units sold — and a full exit relieves the entire basis exactly, leaving no dust. The realized gain (signed) accrues into the portfolio's `lifetime_realized_gains_cents`, and a `TRADE_EXECUTION` event appends with the proceeds as a positive amount, `source_type` of `TRADE`, and `source_id` set to the trade's id. A `BUY` adds its cost — units times executed price — to the lot's `cost_basis_cents` and its units to the `quantity`, appending a `TRADE_EXECUTION` event with the cost as a negative amount. After the fills, positions recompute `market_value_cents` and `unrealized_gain_cents`; the portfolio recomputes cash, total, and drift status (a plan that fully covers its breach should land on `WITHIN_BANDS`); any `MODELED` withdrawal requests of the portfolio revert to `SUBMITTED`; and the proposal, the portfolio, and every touched position refresh `updated_at` and increment `version`. The proposal ends in `EXECUTED`, terminal.

**Release, void, and expiry.** A compliance officer may release a blocked trade when the embargo has lifted: the trade must be `BLOCKED` (else `ERR_TRADE_INVALID_STATE`), no `ACTIVE` restricted-list entry may block its side (else `ERR_SECURITY_RESTRICTED`), the security must be `LISTED` (else `ERR_SECURITY_NOT_TRADEABLE`), and the owning proposal must stand in `APPROVED` (else `ERR_PROPOSAL_INVALID_STATE`); release returns the trade `BLOCKED → PENDING`, ready for a subsequent execution. A compliance officer may also void an executed trade, but only within the same UTC day: the trade must be `EXECUTED` (else `ERR_TRADE_INVALID_STATE`), and the UTC date of the current logical clock must equal the UTC date of the trade's `executed_at`, else `ERR_TRADE_VOID_WINDOW_EXPIRED`. A void is exact compensation, never an approximation. Voiding a `SELL` restores the sold units to the position, restores exactly the relief cents recorded at execution to `cost_basis_cents`, and pulls the proceeds back out of cash through a `TRADE_VOID` event; voiding a `BUY` removes the bought units, removes the added cost from basis, and refunds the cost through a `TRADE_VOID` event. Either way the net effect returns `quantity`, `cost_basis_cents`, and `cash_balance_cents` to their pre-execution values; market value, totals, and drift recompute; `MODELED` withdrawals of the portfolio revert to `SUBMITTED`; the trade stamps `voided_at` — null until this moment — and lands in `VOIDED`, terminal; and the trade, portfolio, and position versions increment. Proposals also die of old age: a `ComplianceOfficer`-run daily operations checkpoint expires every non-terminal proposal — `PROPOSED`, `NEEDS_REVISION`, or `APPROVED` — whose `expires_at` has been reached or passed by the logical clock, transitioning it to `EXPIRED` and cancelling its `PENDING` and `BLOCKED` trades, and reporting back `expired_proposal_count` together with the `expired_proposal_ids`. The same `EXPIRED` fate strikes a non-terminal proposal when its pinned IPS leaves `ACTIVE` through supersession or archival, or when a newer proposal is generated for the same portfolio. Proposals list with filters on `portfolio_id`, `ips_id`, and `status`; trades list with filters on `proposal_id`, `security_id`, and `status`.

### 3.6. Withdrawal Modeling and Settlement

A withdrawal request asks the system to plan a disbursement before anyone commits to it. Either an `Advisor` or the owning `Client` creates the request with a `portfolio_id`, an `amount_cents` greater than 0, and a `funding_mode` of `CASH_FIRST`, `PRO_RATA`, or `TAX_AWARE`, which selects the impact-model variant used later; a client creating against another household's portfolio is rejected with `ERR_NOT_RESOURCE_OWNER`. The request begins in `SUBMITTED`.

**Modeling.** An `Advisor` models the impact of a `SUBMITTED` request (any other state yields `ERR_WITHDRAWAL_INVALID_STATE`) against an `ACTIVE` portfolio (else `ERR_PORTFOLIO_NOT_ACTIVE`). Two fiscal gates apply at the threshold: under `CASH_FIRST` the portfolio's cash must cover the full `amount_cents`, else `ERR_INSUFFICIENT_CASH`, and under every mode the amount may not exceed the portfolio's `total_value_cents`, else `ERR_WITHDRAWAL_EXCEEDS_VALUE`. The model consumes the cash sleeve first: `modeled_cash_used_cents` is the smaller of the requested amount and the cash on hand, and the remaining need is the amount minus that cash usage. Then the variant takes over.

Under `CASH_FIRST`, the plan is empty and raises nothing — cash alone carries the withdrawal. Under `PRO_RATA`, sells spread proportionally across positions without regard to gains. The invested sleeve is `total_value_cents` minus `cash_balance_cents`; positions are visited in `created_at` ascending order while the amount raised remains below the need; each visited position's proportional share of the need is the need times the position's `market_value_cents` divided by the invested sleeve, and the position sells the smaller of its full `quantity` and that share divided by the security's current price rounded up to whole units — rounding up so proceeds meet the need, capped at the holding. A position yielding at least one unit appends a lot to the plan, and the running total rises by the lot's estimated proceeds. Under `TAX_AWARE`, the candidate lots are positions with more than zero units whose security carries no `ACTIVE` `NO_TRADE` restriction, ranked by unrealized gain per unit ascending — losses first — computed as the exact rational quotient of market value minus basis over quantity, ties broken by the position's `created_at` ascending. Walking that ranking while the need remains, each lot sells the smaller of its `quantity` and the still-unfunded need divided by the current price rounded up. If the lots are exhausted with the need still unfunded, the model stands only when the amount raised plus the cash on hand covers the requested amount; otherwise modeling fails with `ERR_WITHDRAWAL_EXCEEDS_VALUE`.

The model then prices its own tax and drift consequences. `modeled_tax_cost_cents` sums, over the plan's lots, the per-lot estimated gain floored at zero times the 2,000-basis-point gains rate divided by 10,000, each line rounded half-up — but only for a `TAXABLE` portfolio; the other two tax statuses model zero. `post_withdrawal_drift_status` projects the portfolio after settlement: each class's value falls by the sum of its lots' quantities times current prices, cash falls by the full requested amount, and the projected total is the current total minus that amount; when the projected total is zero the projection is `WITHIN_BANDS`, otherwise the band check of §3.5 re-runs against the projected composition to choose between `WITHIN_BANDS` and `BREACHED`. Modeling persists, onto the request, the ordered `modeled_plan` — a list of lots each naming `position_id`, `security_id`, `quantity`, `est_proceeds_cents`, and `est_gain_cents` in execution order — plus `modeled_proceeds_cents` (the sum of the lots' estimated proceeds), `modeled_tax_cost_cents`, `modeled_cash_used_cents`, `post_withdrawal_drift_status`, and a `modeled_at` timestamp — all six modeled fields are null until the request reaches `MODELED` — and lands the request in `MODELED`.

**Staleness and decision.** A model is a snapshot, and the system treats it as perishable. Any portfolio-affecting mutation — a reprice touching a held position, a trade execution or void, a cash movement, a position creation, or a settlement — reverts every `MODELED` request of that portfolio back to `SUBMITTED`, clearing `modeled_plan`, the three modeled totals, `post_withdrawal_drift_status`, and `modeled_at`. From `MODELED`, an `Advisor` may approve the request (`MODELED → APPROVED`), re-validating at that moment that the amount still does not exceed the portfolio's current `total_value_cents`, else `ERR_WITHDRAWAL_EXCEEDS_VALUE`. An `Advisor` may reject a request from `SUBMITTED` or `MODELED`, optionally with a `reason`; rejecting a modeled request clears its modeled fields. The owning `Client` may cancel from `SUBMITTED` or `MODELED` — ownership-checked against the portfolio's `client_id`, else `ERR_NOT_RESOURCE_OWNER` — and canceling a modeled request likewise clears the model. In every case, clearing the model — by staleness revert, rejection, or cancellation — resets each of those fields (`modeled_plan`, the three modeled totals, `post_withdrawal_drift_status`, and `modeled_at`) to null. `REJECTED` and `CANCELLED` are terminal.

**Settlement.** An `Advisor` settles an `APPROVED` request against an `ACTIVE` portfolio. The fiscal gates re-run: the amount must still not exceed `total_value_cents`, else `ERR_WITHDRAWAL_EXCEEDS_VALUE`, and — because the market and the book may have moved since modeling — every lot of the `modeled_plan` must still be feasible, meaning each planned lot's current position `quantity` is at least the planned quantity, else `ERR_WITHDRAWAL_PLAN_INFEASIBLE`. Settlement then executes the modeled sells in plan order at current prices under the average-cost relief rule of §3.5: each lot appends a `SETTLEMENT_PROCEEDS` event with its positive proceeds, `source_type` of `WITHDRAWAL`, and `source_id` set to the request's id, and the realized gains accrue into `lifetime_realized_gains_cents`. After the lots settle, a `WITHDRAWAL_DISBURSEMENT` event appends with the requested amount as a negative amount and the same provenance. Cash, totals, and drift recompute; the portfolio's `total_value_cents` falls by exactly the disbursed amount plus any tax-independent price drift since modeling. The request lands in `SETTLED`, terminal, and the request, the portfolio, and every touched position increment their versions. Withdrawal requests list with filters on `portfolio_id` and `status`.

### 3.7. Benchmarks and Performance Measurement

Benchmarks anchor both policy and reporting. A `ComplianceOfficer` creates a benchmark with a `name` that is unique by exact match (duplicates are rejected as `ERR_INVALID_REQUEST`) and an optional `description` that defaults to empty; the benchmark begins `ACTIVE`. Retirement moves `ACTIVE → RETIRED` and is refused while any IPS in `ACTIVE` status references the benchmark, surfacing `ERR_BENCHMARK_IN_USE`; retiring a benchmark that is not `ACTIVE` surfaces `ERR_BENCHMARK_INVALID_STATE`. `RETIRED` is terminal. Beyond retirement, a retired benchmark also blocks three downstream moments named elsewhere: client signature on an IPS that references it, finalization of a performance report that references it, and finalization of an amendment proposing to adopt it — each rejected with `ERR_BENCHMARK_NOT_ACTIVE`. Benchmarks list with a `status` filter and are readable by every operational role.

Performance reporting is evidence the advisor prepares and compliance certifies. An `Advisor` creates a report in `DRAFT` by supplying the `portfolio_id`, the comparison `benchmark_id`, a `period_start` and `period_end` as `YYYY-MM-DD` dates forming a closed interval — both bounds inclusive, and a start later than the end is rejected with `ERR_INVALID_DATE_RANGE` — a `calculation_method` of `TIME_WEIGHTED` or `MONEY_WEIGHTED`, the client-supplied `beginning_value_cents` and `ending_value_cents` valuations (each at least 0), and the `benchmark_return_bps` for the period, which may be negative.

Finalization, a `ComplianceOfficer` action, certifies the numbers. The report must be `DRAFT`, else `ERR_REPORT_INVALID_STATE`; the referenced benchmark must be `ACTIVE`, else `ERR_BENCHMARK_NOT_ACTIVE`; and the closed period may not touch any already-`FINALIZED` report of the same portfolio — closed-interval semantics mean a shared boundary date already counts as overlap, and an offending report is rejected with `ERR_REPORT_PERIOD_OVERLAP`. Finalization computes `portfolio_return_bps` by the report's chosen method and derives `excess_return_bps` as `portfolio_return_bps` minus `benchmark_return_bps`.

Both methods draw their flows from the portfolio's ledger over a consistent window: events whose `occurred_at` UTC date is strictly after `period_start` and on or before `period_end` — the start date is exclusive, the end date inclusive — ordered by `occurred_at` ascending with ties broken by `created_at` ascending. Under `TIME_WEIGHTED`, the return chains geometrically around each flow to eliminate timing effects. The chain begins with a running post-flow valuation equal to `beginning_value_cents`. Each flow's sub-period factor is its `valuation_before_cents` divided by the running valuation — except that when the running valuation is zero as a flow arrives, that sub-period's factor is treated as exactly one — and the running valuation then advances to the flow's `valuation_before_cents` plus its signed `amount_cents`. After the last flow, the terminal factor is `ending_value_cents` divided by the running valuation, again treated as exactly one when the running valuation is zero. The product of every sub-period factor and the terminal factor, minus one, times 10,000, is rounded half-up once at the very end to an integer basis-point return; intermediate factors are never rounded. Under `MONEY_WEIGHTED`, a Modified Dietz closed form weights each flow by the time remaining in the period. The period length in days is the difference between the two dates, treated as one day when the dates coincide. Each flow's weight is the period length minus the flow's day offset from `period_start` — whole-day granularity on the UTC date — divided by the period length. The numerator of the return is `ending_value_cents` minus `beginning_value_cents` minus the sum of all flow amounts; the denominator is `beginning_value_cents` plus the sum of each flow's weight times its amount; and when the denominator is zero the return is zero basis points, otherwise the ratio times 10,000 is rounded half-up once to integer basis points. Given mid-period flows, the two methods deliberately yield different returns from identical inputs. Reports list with filters on `portfolio_id`, `benchmark_id`, and `status`; a `Client` sees only its own portfolios' reports.

### 3.8. Amendments, Committee Votes, and Fiduciary Minutes

Policy evolves by amendment, never by silent edit. An `Advisor` drafts an amendment against an existing IPS by naming `ips_id` and at least one change lever among `proposed_objective_text`, `proposed_review_cadence_months` (1 to 24 inclusive), `proposed_risk_tolerance_score` (1 to 100 inclusive), and `proposed_benchmark_id`; a draft carrying no lever at all is rejected with `ERR_AMENDMENT_EMPTY_CHANGES`. The drafting advisor's identity is captured in `proposed_by_user_id`, and the draft begins in `DRAFT`. Submission — an `Advisor` action — moves `DRAFT → SUBMITTED` and requires the referenced IPS to be `ACTIVE` at that moment, else `ERR_IPS_INVALID_STATE`; submitting from any other amendment state is rejected with `ERR_AMENDMENT_INVALID_STATE`.

The committee then votes. A `CommitteeMember` casts a `decision` of `APPROVE` or `REJECT` on a `SUBMITTED` amendment — voting at any other time is `ERR_AMENDMENT_INVALID_STATE`. Segregation of duties bars the proposer: a voter whose identity equals `proposed_by_user_id` is rejected with `ERR_SOD_SELF_VOTE`. Each member votes at most once; a second vote from the same member is rejected with `ERR_DUPLICATE_VOTE`. Every accepted vote appends to `voter_user_ids`, the ordered audit list of `voter_user_id` and `decision` pairs, and recomputes `approve_votes` and `reject_votes` as counts of distinct decisions of each kind. Quorum is three: the vote that records the third distinct `APPROVE` moves the amendment `SUBMITTED → QUORUM_REACHED`, and the vote that records the third distinct `REJECT` moves it `SUBMITTED → REJECTED`, terminal.

Finalization belongs to the `CommitteeChair` and carries the system's two-document fiduciary gate. The amendment must stand in `QUORUM_REACHED`, else `ERR_AMENDMENT_INVALID_STATE`. The request carries the OCC field `expected_ips_version` (§2.8); a mismatch with the IPS's current `version` is rejected with `ERR_STALE_IPS_VERSION`. The request also carries `ratified_minute_id`: it must resolve, else `ERR_INVALID_REFERENCE`; the referenced minute must stand in `RATIFIED`, else `ERR_AMENDMENT_MINUTE_NOT_RATIFIED`; and the amendment's own id must appear in that minute's `amendment_refs`, else `ERR_AMENDMENT_NOT_IN_MINUTE`. Two business checks close the battery: if `proposed_benchmark_id` is set, that benchmark must be `ACTIVE`, else `ERR_BENCHMARK_NOT_ACTIVE`; and if `proposed_risk_tolerance_score` is set, it must sit within 10 points of the client's `risk_tolerance_score` in either direction, else `ERR_RISK_TOLERANCE_MISMATCH`.

A successful finalization applies every non-null proposed lever to the IPS, stamps the amendment with `ratified_minute_id`, `finalized_by_user_id`, and `finalized_at` — the latter two remaining null until the amendment reaches `APPROVED` — and increments the IPS's `version` by exactly one. When the cadence lever changed, `next_review_due` is recomputed by adding the new cadence in calendar months to `finalized_at`, with the same end-of-month clamp as activation. The version bump detonates the pin cascade: every rebalance proposal pinned to the amended IPS whose `pinned_ips_version` no longer matches transitions to `EXPIRED`, and its `PENDING` or `BLOCKED` trades transition to `CANCELLED`. The client's non-`CLOSED` portfolios then re-run the drift assessment — targets do not change through amendments, but risk and benchmark changes keep the policy current. The amendment lands in `APPROVED`, terminal. The proposer may instead withdraw a draft or submitted amendment (`DRAFT` or `SUBMITTED` → `WITHDRAWN`, terminal); only the advisor identity recorded in `proposed_by_user_id` may do so, else `ERR_NOT_RESOURCE_OWNER`. Amendments list with filters on `ips_id`, `ratified_minute_id`, and `status`.

Minutes are the fiduciary record the gate leans on. A `CommitteeMember` records a minute with a `meeting_date` — which may not be later than the current logical clock date, else `ERR_MEETING_DATE_IN_FUTURE` — an `amendment_refs` list of the amendment ids the minute documents (which may be empty), and the free-text `decisions_text`. The recorder's identity lands in `recorded_by_user_id`, and the minute begins in `DRAFT`. Ratification, a `CommitteeChair` action, moves `DRAFT → RATIFIED` under three checks: the minute must be `DRAFT`, else `ERR_MINUTE_INVALID_STATE`; the chair's identity must differ from `recorded_by_user_id`, else `ERR_SOD_MINUTE_SELF_RATIFY`; and every id in `amendment_refs` must resolve to an existing amendment, else `ERR_INVALID_REFERENCE`. Ratification stamps `ratified_by_user_id` and `ratified_at`, both null until the minute reaches `RATIFIED`, and `RATIFIED` is terminal. Minutes list with a `status` filter.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request and response payloads for every row are governed by the workflows of §3 and the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/advisory/clients` | Create a client (starts `PROSPECT`) | Advisor |
| GET | `/advisory/clients` | List clients with pagination | Advisor, ComplianceOfficer |
| GET | `/advisory/clients/{id}` | Read one client | Advisor, ComplianceOfficer, Client |
| POST | `/advisory/clients/{id}/activate` | Activate a `PROSPECT` client | Advisor |
| POST | `/advisory/clients/{id}/terminate` | Terminate an `ACTIVE` client with the archival cascade | Advisor |
| POST | `/advisory/benchmarks` | Create a benchmark (starts `ACTIVE`) | ComplianceOfficer |
| GET | `/advisory/benchmarks` | List benchmarks | Advisor, ComplianceOfficer, CommitteeMember, CommitteeChair |
| POST | `/advisory/benchmarks/{id}/retire` | Retire a benchmark; blocked while an `ACTIVE` IPS references it | ComplianceOfficer |
| POST | `/advisory/ips-policies` | Create an IPS in `DRAFT` for an `ACTIVE` client | Advisor |
| GET | `/advisory/ips-policies` | List IPS records | Advisor, ComplianceOfficer, Client |
| GET | `/advisory/ips-policies/{id}` | Read one IPS (`review_overdue` derived on read) | Advisor, ComplianceOfficer, Client |
| PUT | `/advisory/ips-policies/{id}/allocation-targets` | Atomically replace the allocation-target set of a `DRAFT` IPS | Advisor |
| GET | `/advisory/ips-policies/{id}/allocation-targets` | List an IPS's allocation targets | Advisor, ComplianceOfficer, Client |
| POST | `/advisory/ips-policies/{id}/submit` | Submit a draft IPS for compliance review | Advisor |
| POST | `/advisory/ips-policies/{id}/compliance-approve` | Compliance approval, moving the IPS to client signature | ComplianceOfficer |
| POST | `/advisory/ips-policies/{id}/compliance-reject` | Compliance rejection, returning the IPS to draft | ComplianceOfficer |
| POST | `/advisory/ips-policies/{id}/client-sign` | Client signature activating the IPS and superseding its predecessor | Client |
| POST | `/advisory/ips-policies/{id}/client-decline` | Client decline, returning the IPS to draft | Client |
| POST | `/advisory/ips-policies/{id}/complete-review` | Record a completed review and advance the due date | Advisor |
| POST | `/advisory/portfolios` | Create a portfolio (`OPEN`, zero cash) | Advisor |
| GET | `/advisory/portfolios` | List portfolios | Advisor, ComplianceOfficer, Client |
| GET | `/advisory/portfolios/{id}` | Read one portfolio | Advisor, ComplianceOfficer, Client |
| POST | `/advisory/portfolios/{id}/activate` | Activate an `OPEN` portfolio | Advisor |
| POST | `/advisory/portfolios/{id}/freeze` | Freeze an `ACTIVE` portfolio | ComplianceOfficer |
| POST | `/advisory/portfolios/{id}/unfreeze` | Unfreeze a `FROZEN` portfolio | ComplianceOfficer |
| POST | `/advisory/portfolios/{id}/close` | Close an empty, work-item-free `ACTIVE` portfolio | Advisor |
| POST | `/advisory/portfolios/{id}/cash-movements` | Append a manual deposit or withdrawal ledger event | Advisor |
| POST | `/advisory/securities` | Register a security with an initial price | ComplianceOfficer |
| GET | `/advisory/securities` | List securities | Advisor, ComplianceOfficer |
| GET | `/advisory/securities/{id}` | Read one security | Advisor, ComplianceOfficer |
| POST | `/advisory/securities/{id}/reprice` | Update the security's price with the recompute cascade | ComplianceOfficer |
| POST | `/advisory/securities/{id}/set-trading-status` | Move among `LISTED`, `HALTED`, and `DELISTED` | ComplianceOfficer |
| POST | `/advisory/positions` | Transfer in an opening position | Advisor |
| GET | `/advisory/positions` | List positions | Advisor, ComplianceOfficer, Client |
| GET | `/advisory/positions/{id}` | Read one position | Advisor, ComplianceOfficer, Client |
| POST | `/advisory/restricted-list-entries` | Add a restriction window | ComplianceOfficer |
| GET | `/advisory/restricted-list-entries` | List restricted-list entries | Advisor, ComplianceOfficer |
| GET | `/advisory/restricted-list-entries/{id}` | Read one restricted-list entry | Advisor, ComplianceOfficer |
| POST | `/advisory/restricted-list-entries/{id}/terminate` | End a restriction early | ComplianceOfficer |
| POST | `/advisory/rebalance-proposals` | Generate a rebalance proposal (OCC on the portfolio version) | Advisor |
| GET | `/advisory/rebalance-proposals` | List rebalance proposals | Advisor, ComplianceOfficer |
| GET | `/advisory/rebalance-proposals/{id}` | Read one proposal | Advisor, ComplianceOfficer |
| POST | `/advisory/rebalance-proposals/{id}/approve` | Approve a proposal with the compliance scan | ComplianceOfficer |
| POST | `/advisory/rebalance-proposals/{id}/request-changes` | Send a proposal back for revision | ComplianceOfficer |
| POST | `/advisory/rebalance-proposals/{id}/revise` | Regenerate a proposal's trades at current prices | Advisor |
| POST | `/advisory/rebalance-proposals/{id}/reject` | Reject a proposal | ComplianceOfficer |
| POST | `/advisory/rebalance-proposals/{id}/cancel` | Cancel a proposal | Advisor |
| POST | `/advisory/rebalance-proposals/{id}/execute` | Execute an approved proposal at current prices | Advisor |
| GET | `/advisory/trade-instructions` | List trade instructions | Advisor, ComplianceOfficer |
| GET | `/advisory/trade-instructions/{id}` | Read one trade instruction | Advisor, ComplianceOfficer |
| POST | `/advisory/trade-instructions/{id}/release` | Release a blocked trade after the embargo lifts | ComplianceOfficer |
| POST | `/advisory/trade-instructions/{id}/void` | Void an executed trade with same-day exact compensation | ComplianceOfficer |
| POST | `/advisory/withdrawal-requests` | Create a withdrawal request | Advisor, Client |
| GET | `/advisory/withdrawal-requests` | List withdrawal requests | Advisor, ComplianceOfficer, Client |
| GET | `/advisory/withdrawal-requests/{id}` | Read one withdrawal request | Advisor, ComplianceOfficer, Client |
| POST | `/advisory/withdrawal-requests/{id}/model-impact` | Model the impact of a submitted withdrawal | Advisor |
| POST | `/advisory/withdrawal-requests/{id}/approve` | Approve a modeled withdrawal | Advisor |
| POST | `/advisory/withdrawal-requests/{id}/reject` | Reject a withdrawal request | Advisor |
| POST | `/advisory/withdrawal-requests/{id}/cancel` | Cancel a withdrawal request (owning client only) | Client |
| POST | `/advisory/withdrawal-requests/{id}/settle` | Settle an approved withdrawal per its modeled plan | Advisor |
| POST | `/advisory/performance-reports` | Create a draft performance report | Advisor |
| GET | `/advisory/performance-reports` | List performance reports | Advisor, ComplianceOfficer, Client |
| GET | `/advisory/performance-reports/{id}` | Read one performance report | Advisor, ComplianceOfficer, Client |
| POST | `/advisory/performance-reports/{id}/finalize` | Finalize a report, computing its returns | ComplianceOfficer |
| POST | `/advisory/ips-amendments` | Draft an IPS amendment with at least one change lever | Advisor |
| GET | `/advisory/ips-amendments` | List amendments | Advisor, ComplianceOfficer, CommitteeMember, CommitteeChair |
| GET | `/advisory/ips-amendments/{id}` | Read one amendment | Advisor, ComplianceOfficer, CommitteeMember, CommitteeChair |
| POST | `/advisory/ips-amendments/{id}/submit` | Submit an amendment for committee vote | Advisor |
| POST | `/advisory/ips-amendments/{id}/vote` | Cast an `APPROVE` or `REJECT` vote | CommitteeMember |
| POST | `/advisory/ips-amendments/{id}/finalize` | Finalize a quorum-passed amendment (OCC on the IPS version) | CommitteeChair |
| POST | `/advisory/ips-amendments/{id}/withdraw` | Withdraw a draft or submitted amendment | Advisor |
| POST | `/advisory/committee-minutes` | Record committee minutes | CommitteeMember |
| GET | `/advisory/committee-minutes` | List committee minutes | Advisor, ComplianceOfficer, CommitteeMember, CommitteeChair |
| GET | `/advisory/committee-minutes/{id}` | Read one minute | Advisor, ComplianceOfficer, CommitteeMember, CommitteeChair |
| POST | `/advisory/committee-minutes/{id}/ratify` | Ratify a draft minute | CommitteeChair |
| GET | `/advisory/cash-flow-events` | List ledger events, filterable by portfolio, kind, and date window | Advisor, ComplianceOfficer, Client |
| GET | `/advisory/cash-flow-events/{id}` | Read one ledger event | Advisor, ComplianceOfficer |
| POST | `/advisory/compliance-checkpoints` | Run the daily checkpoint expiring stale proposals | ComplianceOfficer |
| POST | `/advisory/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each code live with the workflows in §2 and §3; this table is the index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_STALE_IPS_VERSION` | 412 |
| `ERR_STALE_PORTFOLIO_VERSION` | 412 |
| `ERR_CLIENT_INVALID_STATE` | 409 |
| `ERR_IPS_INVALID_STATE` | 409 |
| `ERR_PORTFOLIO_INVALID_STATE` | 409 |
| `ERR_PORTFOLIO_NOT_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_IPS` | 409 |
| `ERR_SECURITY_INVALID_STATE` | 409 |
| `ERR_BENCHMARK_INVALID_STATE` | 409 |
| `ERR_PROPOSAL_INVALID_STATE` | 409 |
| `ERR_TRADES_BLOCKED` | 409 |
| `ERR_TRADE_INVALID_STATE` | 409 |
| `ERR_WITHDRAWAL_INVALID_STATE` | 409 |
| `ERR_REPORT_INVALID_STATE` | 409 |
| `ERR_AMENDMENT_INVALID_STATE` | 409 |
| `ERR_MINUTE_INVALID_STATE` | 409 |
| `ERR_SECURITY_RESTRICTED` | 422 |
| `ERR_SECURITY_NOT_TRADEABLE` | 422 |
| `ERR_SOD_SELF_VOTE` | 422 |
| `ERR_SOD_MINUTE_SELF_RATIFY` | 422 |
| `ERR_AMENDMENT_MINUTE_NOT_RATIFIED` | 422 |
| `ERR_AMENDMENT_NOT_IN_MINUTE` | 422 |
| `ERR_BENCHMARK_NOT_ACTIVE` | 422 |
| `ERR_BENCHMARK_IN_USE` | 422 |
| `ERR_SECURITY_IN_USE` | 422 |
| `ERR_PROPOSAL_STALE_PIN` | 422 |
| `ERR_ALLOCATION_SUM_INVALID` | 422 |
| `ERR_RISK_TOLERANCE_MISMATCH` | 422 |
| `ERR_RESTRICTION_WINDOW_OVERLAP` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_REPORT_PERIOD_OVERLAP` | 422 |
| `ERR_POSITION_EXISTS` | 422 |
| `ERR_AMENDMENT_EMPTY_CHANGES` | 422 |
| `ERR_DUPLICATE_VOTE` | 422 |
| `ERR_DRIFT_NOT_BREACHED` | 422 |
| `ERR_TRADE_VOID_WINDOW_EXPIRED` | 422 |
| `ERR_EVENT_IN_FUTURE` | 422 |
| `ERR_MEETING_DATE_IN_FUTURE` | 422 |
| `ERR_WITHDRAWAL_EXCEEDS_VALUE` | 422 |
| `ERR_INSUFFICIENT_CASH` | 422 |
| `ERR_WITHDRAWAL_PLAN_INFEASIBLE` | 422 |
| `ERR_PORTFOLIO_NOT_EMPTY` | 422 |
| `ERR_OPEN_WORK_ITEMS` | 422 |
