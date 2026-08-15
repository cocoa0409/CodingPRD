# Fund-of-Funds Pacing API — Product Requirements Document

## 1. Introduction

Institutional fund-of-funds programs operate under a peculiar tension: capital is committed today against a pacing model, drawn down over years through capital calls, returned over more years through distributions, and reported to stakeholders with a one-quarter lag — all while concentration, liquidity, and governance constraints must hold continuously. An operator who books a commitment without checking the strategy cap, or who executes documents against a stale reading of program cash, can quietly push the program into an over-committed or under-buffered posture that only surfaces quarters later.

This document specifies the Fund-of-Funds Pacing API, mounted under the `/fof` URL prefix. The system manages the full lifecycle of an institutional fund-of-funds program: a `CIO` opens and tunes the program envelope, `Analyst` staff register managers and their vehicles, run due-diligence rounds, and draft commitment proposals; an `InvestmentCommittee` approves vehicles and proposals under segregation-of-duties; `OperationsAnalyst` staff execute documents, post capital calls and distributions against a cash ledger, capture quarterly NAV snapshots, settle secondary transactions, and publish valuation reports; and a `ComplianceOfficer` can suspend managers when diligence findings demand it. Every write that touches program cash or program-level aggregates is reconciled immediately — there is no batch settlement window — and three write paths are guarded by optimistic concurrency so that decisions are always made against a fresh read of the program's version.

The API is designed for segregation of duties as a first-class concern. The same person may hold two staff appointments, and the system resolves identity through a `StaffUser` directory so that an investment-committee approval by the recommending analyst is structurally detectable and rejected.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, identity and envelope contracts, the gating vocabulary shared across all write paths, and the precision and consistency guarantees that underpin every calculation.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting operator and `X-User-Role` naming the operational capacity in which they act. The system recognises five role names, spelled exactly: `CIO`, `Analyst`, `InvestmentCommittee`, `OperationsAnalyst`, and `ComplianceOfficer`. A missing `X-User-Role`, an unrecognised role value, or a missing `X-User-ID` for an entity-backed role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A role that is recognised but not permitted for the endpoint per the role matrix is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Roles differ in whether `X-User-ID` is resolved against a persisted entity. When `X-User-Role` is `Analyst`, `InvestmentCommittee`, or `OperationsAnalyst`, `X-User-ID` must be the `id` of an existing `StaffUser` row whose `staff_role` equals `ANALYST`, `IC_MEMBER`, or `OPS_ANALYST` respectively; ownership and segregation-of-duties checks compare resource foreign keys to that `id`. When `X-User-Role` is `CIO` or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

Endpoints returning lists of resources are paginated via query parameters. `limit` specifies the maximum number of items returned; it defaults to 10, accepts a minimum of 1, and is capped at 100. `offset` specifies the number of items to skip and defaults to 0. Unless otherwise specified, list endpoints sort by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Program Posture as a Gating Signal

A `FoFProgram` carries a derived `posture` field, one of `NORMAL`, `RESTRICTED`, or `FROZEN`, that is recomputed after every ledger append, every capital-call status change, and every program status change. The posture gates which writes are permitted against the program:

- If the program's `status` is `SUSPENDED` or `CLOSED`, posture is `FROZEN` and every mutating write scoped to the program is rejected with `ERR_POSTURE_GATED` (HTTP 409).
- Otherwise, if any `CapitalCall` for the program is in status `OVERDUE`, posture is `RESTRICTED`.
- Otherwise, if `unrestricted_cash` is strictly below `liquidity_buffer_min` multiplied by 1.10, posture is `RESTRICTED`; a cash balance exactly equal to the buffer times 1.10 is `NORMAL`.
- Otherwise, posture is `NORMAL`.

While `RESTRICTED`, the program continues to accept the cash-restoring writes — paying a capital call, receiving a distribution, posting a contribution ledger entry, settling a secondary bid — but four forward-committing writes are blocked with `ERR_POSTURE_GATED`: recommending a proposal, IC-approving a proposal, executing a commitment, and accepting a secondary bid.

### 2.5. Optimistic Concurrency Control on Program-Aggregate Writes

Three write endpoints are guarded by optimistic concurrency on the `FoFProgram` row, because all three make allocation decisions that depend on program aggregates — committed totals, unfunded totals, the liquidity buffer, the vintage band — that shift with every executed commitment and every ledger append. Each such request must carry a non-optional `expected_program_version` field carrying the client's last observed `version` of the parent `FoFProgram`. If the supplied value does not match the program's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the program before retrying. The three guarded writes are: superseding the approved pacing plan, executing a commitment, and settling a secondary bid. No other endpoint takes a version field.

### 2.6. The Cash Ledger and Derived Aggregates

A `FoFProgram` owns an append-only `CashLedgerEntry` collection that is the single source of truth for `unrestricted_cash`. Each entry records a signed `amount` (positive is cash in, negative is cash out), an `entry_kind` (one of `CONTRIBUTION`, `CAPITAL_CALL_PAYMENT`, `DISTRIBUTION_RECEIPT`, `SECONDARY_SETTLEMENT_OUT`, `SECONDARY_SETTLEMENT_IN`, `MANUAL_ADJUSTMENT`), a `ref_entity` and `ref_id` identifying the source row (`ref_id` is null for `CONTRIBUTION` and `MANUAL_ADJUSTMENT`), an optional free-text `note` for manual entries, and a computed `balance_after` capturing the running `unrestricted_cash` immediately after the entry. `unrestricted_cash` is the sum of all signed entry amounts and is recomputed on every append.

Program-level aggregates are recomputed whenever any contributing event lands: `committed_total` is the sum of `sized_amount` over `Commitment` rows in status `EXECUTED`; `deployed_total` is the sum of `amount` over `CapitalCall` rows in status `PAID`; `returned_total` is the sum of `amount` over `Distribution` rows in status `RECEIVED`; `secondary_purchase_unfunded_total` is the sum of `unfunded_assumed` over `SecondaryBid` rows in status `SETTLED` with `side` equal to `PURCHASE`; and `unfunded_total` is `committed_total` minus `deployed_total` plus `secondary_purchase_unfunded_total`.

### 2.7. Common Resource Properties

Primary resources carry a standard system-managed field set: `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits), `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation), and `version` (an integer that increments on every mutation, including mutations that only recompute derived fields). Two collection resources — `CashLedgerEntry` and `LookThroughLine` — are append-only audit children and carry only `id` and `created_at`; `updated_at` and `version` are absent on those rows. The `StaffUser` directory likewise carries only `id` and `created_at`, since a staff appointment row is not mutated after registration.

### 2.8. Nested Resource Retrieval

Requests that target nested resources validate path identifiers left-to-right: the program first, then the mid-level resource (pacing plan, vehicle, commitment, secondary bid, valuation report), then the leaf resource (call, distribution, snapshot, review). The first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404) and validation stops there — the server does not surface a child-not-found error when a parent id is already invalid. Foreign keys supplied in request bodies (such as `pacing_plan_id`, `linked_commitment_id`, `replacement_plan_id`, `program_id`, `vehicle_id`) are validated separately and surface `ERR_REF_NOT_FOUND` (HTTP 404).

### 2.9. Precision, Rounding, and the Logical Clock

All monetary values are computed in decimal arithmetic and rounded to 2 decimal places, round half up. Where the spec pins a per-row rounding order (notably pacing targets and fee layering), the rounding is applied per row before summing; the alternative sum-then-round order yields different cents and is non-conformant. Percentage fields reported as fractions — `concentration_strategy_pct` and `concentration_manager_pct` — are reported to 4 decimal places, round half up, on a 0..1 scale. IRR percentages are reported to 2 decimal places. The server maintains a logical clock seeded at exactly `2026-08-01T00:00:00Z` on startup; the clock never falls back to wall-clock time, and an `OperationsAnalyst` can advance it via a test-driving capability that takes a `to_iso8601` instant, runs the overdue sweep, and recomputes postures for affected programs.

## 3. Business Logic & Workflows

### 3.1. Program Setup and the Posture Envelope

A `CIO` establishes a program by supplying its `program_name`, a `base_currency` (one of `USD`, `EUR`, `GBP`) used for all aggregates, a `total_nav_budget` that must be greater than zero, and a set of governance knobs: `strategy_cap_pct` (the maximum share of `total_nav_budget` that `ACTIVE`-or-`EXECUTED` commitments in any single strategy may occupy, strictly greater than zero and at most one), `manager_cap_pct` (the maximum share committed to any single manager across all vehicles, same band), `max_vintage_band_years` (the maximum span in years between the earliest and latest `vintage_year` among `EXECUTED` commitments, at least one), `liquidity_buffer_min` (the minimum `unrestricted_cash` the program must retain after any cash outflow, at least zero), `overdue_grace_days` (the days after a capital call's `due_date` before it flips to `OVERDUE`, at least zero), and the secondary pricing bands `secondary_premium_cap_pct` and `secondary_discount_cap_pct` (each between zero and one inclusive). On creation the program's `status` is `DRAFT`, all aggregates are initialised to zero, and posture is computed — but a `DRAFT` program is not yet a candidate for `NORMAL` because it cannot be opened until its cash is funded.

A program moves from `DRAFT` to `OPEN` only when its `unrestricted_cash` is at least `liquidity_buffer_min` (otherwise `ERR_BUFFER_BREACH`, HTTP 422) and at least one `CONTRIBUTION` entry exists in the cash ledger. The open transition recomputes posture. While `OPEN`, the `CIO` may suspend the program, which drives posture to `FROZEN` and blocks all posture-gated writes; resuming a suspended program again requires `unrestricted_cash` to be at least the buffer and recomputes posture. Closing a program is permitted only when no `Commitment` remains in `PENDING_DOCS` or in `EXECUTED` with a positive `unfunded_amount`, no `CapitalCall` remains in `ISSUED` or `OVERDUE`, and no `SecondaryBid` remains in `PROPOSED`, `COUNTERED`, or `ACCEPTED`; the close transition cascades every `APPROVED` pacing plan to `ARCHIVED`, every `DRAFT` or `RECOMMENDED` proposal to `WITHDRAWN`, and freezes the posture.

Manual cash adjustments land through an `OperationsAnalyst` posting a ledger entry with `entry_kind` of `CONTRIBUTION` or `MANUAL_ADJUSTMENT` and a signed `amount`, optionally annotated with a `note`. Each append recomputes `unrestricted_cash`, records `balance_after`, recomputes posture, and bumps the program's `version`.

### 3.2. Pacing Plans and Per-Vintage Targets

An `Analyst` drafts a pacing plan against a program by supplying a `plan_label` (unique within the program), a `horizon_years` count of vintage years the plan spans (at least one), a `start_vintage_year` (at least 2000), and a `target_strategy_mix` — a list of strategy-and-weight objects whose weights must sum to exactly 1.0 across at most 4 entries, and whose strategies must each be one of the six declared strategies. A new plan lands in `DRAFT`.

A `CIO` approves a draft plan when the program is `OPEN` and its posture is not `FROZEN`. Approval validates the mix: weights that do not sum to exactly 1.0, or a mix with more than four entries, are rejected with `ERR_MIX_SUM_INVALID` (HTTP 422); if another plan for the same program is already `APPROVED`, the approval is rejected with `ERR_ACTIVE_PLAN_EXISTS` (HTTP 409). Successful approval populates `target_commit_by_year` via the pacing-targets waterfall and stores `projected_total_commit` as the sum of those per-year amounts, transitioning the plan from `DRAFT` to `APPROVED`.

The pacing waterfall allocates the remaining budget — `total_nav_budget` minus `committed_total` counting only `EXECUTED` commitments — evenly across the plan's horizon: the remaining budget divided by `horizon_years` gives an annual pool, and each vintage year from `start_vintage_year` through `start_vintage_year + horizon_years - 1` receives one row per mix entry, carrying that year's pool multiplied by the entry's weight. Each row's amount is rounded to 2 decimal places round half up, and the remainder cents from per-row rounding are swept into the first row — the earliest vintage year and the first strategy in the input order of the mix — so that the row amounts sum exactly to the rounded remaining budget. The accumulation sort order is `vintage_year` ascending, then strategy in mix order (never by row id).

Superseding an approved plan is an atomic operation. The `CIO` names a `replacement_plan_id` that must reference a plan of the same program still in `DRAFT` — otherwise `ERR_PLAN_NOT_DRAFT` (HTTP 422) — and supplies `expected_program_version` matching the program's current `version` (mismatch is `ERR_STALE_VERSION`). Because concentration headroom, vintage-band bounds, and the liquidity buffer all derive from program aggregates that shift with every executed commitment and ledger entry, a stale read cannot be used to justify replacing the plan. On success, the old plan transitions from `APPROVED` to `SUPERSEDED`, the replacement transitions from `DRAFT` to `APPROVED` and runs the pacing-targets waterfall, every `DRAFT` proposal tied to the old plan is moved to `WITHDRAWN`, and the program's `version` increments. A plan also moves from `APPROVED` to `ARCHIVED` automatically when its program closes.

### 3.3. Manager and Vehicle Diligence

An `Analyst` registers a `Manager` by providing its `legal_name` (globally unique), a `domicile_country` ISO-3166 alpha-2 code, and a `relationship_since_year` (at least 1980). New managers land in `PROSPECT`. The analyst then registers fund vehicles under a manager — the vehicle row carries a system-set `manager_id` linking it back to its manager — each with a `fund_name` unique within the manager, a `strategy` (one of `BUYOUT`, `VENTURE`, `GROWTH`, `CREDIT`, `REAL_ASSETS`, `SECONDARIES`), a `vintage_year` of at least 2000, a positive `fund_size_target`, two management-fee rates (`mgmt_fee_rate_early` during the investment period and `mgmt_fee_rate_late` after it, each strictly greater than zero and at most 0.05), an `investment_period_years` of at least one, a `carry_rate` between zero and 0.30 inclusive, and a `hurdle_rate` between zero and 0.15 inclusive. A vehicle lands in `SCREENING`.

Beginning diligence moves a vehicle from `SCREENING` to `IN_DILIGENCE`, requires the manager to be in `PROSPECT` or `APPROVED` (otherwise `ERR_MANAGER_NOT_ELIGIBLE`), and spawns the first `DueDiligenceReview` round — `round_index` set to 1 — in `DRAFT`. If a prior round was withdrawn or completed and diligence must rerun, the analyst opens a new round explicitly; the new round's `round_index` is the prior maximum plus one. While a review is in `DRAFT` or has been kicked back to `INFO_REQUESTED`, the analyst updates the four score fields — `score_strategy_fit`, `score_track_record`, `score_operations`, `score_compliance`, each an integer-valued score from 0 to 100 — through a partial update.

Submitting a review (the transition from `DRAFT` to `SUBMITTED`) requires all four score fields to be non-null; a submission with a missing score is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Submission computes `composite_score` as a weighted blend: thirty percent of `score_strategy_fit`, twenty-five percent of `score_track_record`, twenty-five percent of `score_operations`, and twenty percent of `score_compliance`, with the result rounded to 2 decimal places round half up. The weights are fixed constants. The `InvestmentCommittee` may kick a submitted review back to `INFO_REQUESTED`; resubmission from `INFO_REQUESTED` back to `SUBMITTED` recomputes the composite from the current scores, and this cycle may repeat. A submitted review is completed by the committee, and a draft review may be withdrawn by the analyst. `COMPLETED` and `WITHDRAWN` are the terminal states.

Vehicle approval (from `IN_DILIGENCE` to `APPROVED`) is gated on the latest review — the one with the highest `round_index` — being in `COMPLETED` status with a `composite_score` of at least 70; failure is `ERR_DD_SCORE_TOO_LOW` (HTTP 422). If the manager was still a `PROSPECT`, approval of the vehicle cascades the manager from `PROSPECT` to `APPROVED`. The committee may also decline a vehicle in diligence, which withdraws every non-terminal review on the vehicle, or close an approved vehicle to new commitments (permitted only when no proposal on the vehicle is in `DRAFT` or `RECOMMENDED`).

At the manager level, the `CIO` approves a `PROSPECT` manager once at least one of its vehicles has reached `APPROVED` — otherwise `ERR_NO_APPROVED_VEHICLE` (HTTP 422) — and exits an `APPROVED` manager when no commitment on any of the manager's vehicles remains live (no `PENDING_DOCS`, no `EXECUTED` with positive `unfunded_amount`). The exit transition moves the manager to its terminal `EXITED` status and cascades every vehicle not yet `CLOSED_TO_NEW` to `CLOSED_TO_NEW`. A `ComplianceOfficer` may suspend an `APPROVED` manager, which cascades broadly: every vehicle of the manager in `IN_DILIGENCE` is moved to `DECLINED`, every due-diligence review on any of the manager's vehicles in `DRAFT`, `SUBMITTED`, or `INFO_REQUESTED` is moved to `WITHDRAWN`, and every proposal on any of the manager's vehicles in `DRAFT` or `RECOMMENDED` is moved to `WITHDRAWN`. The same officer may reinstate a suspended manager, restoring it to `APPROVED` with no cascade.

### 3.4. From Proposal to Commitment: Caps, Capacity, and Segregation of Duties

An `Analyst` drafts an `InvestmentProposal` against a vehicle by supplying the `program_id` of the committing program, the `pacing_plan_id` of the approved plan it draws against, and a positive `proposed_amount`. The system stamps `recommended_by_analyst_id` from the acting analyst's `X-User-ID` at creation and lands the proposal in `DRAFT`.

Recommending a proposal — the transition from `DRAFT` to `RECOMMENDED` — is a heavily gated write. The program must be `OPEN` with posture `NORMAL` (otherwise `ERR_POSTURE_GATED`); the vehicle must be `APPROVED` (otherwise `ERR_VEHICLE_NOT_APPROVED`, HTTP 422); the manager must be `APPROVED` (otherwise `ERR_MANAGER_NOT_ELIGIBLE`); the referenced pacing plan must be `APPROVED` for this program (otherwise `ERR_PLAN_NOT_APPROVED`, HTTP 422); and the acting analyst's `X-User-ID` must equal the proposal's `recommended_by_analyst_id` — only the drafting analyst may recommend their own proposal. Successful recommendation computes and stores `concentration_strategy_pct` and `concentration_manager_pct`. Each is a post-trade fraction of `total_nav_budget`: the strategy figure adds the proposal's `proposed_amount` to the sum of `sized_amount` over existing commitments whose vehicle shares the proposal vehicle's strategy; the manager figure does the same across existing commitments whose vehicle belongs to the proposal vehicle's manager. Both figures count commitments in `EXECUTED` status and commitments in `REDUCED` status at their reduced `sized_amount`; `PENDING_DOCS` and `CANCELLED` rows are excluded. Both are reported as fractions on a 0..1 scale to 4 decimal places, round half up.

IC approval — `RECOMMENDED` to `IC_APPROVED` — is evaluated by an `InvestmentCommittee` member against five checks. The program must again be `OPEN` with posture `NORMAL` (`ERR_POSTURE_GATED`). The stored `concentration_strategy_pct` must not exceed the program's `strategy_cap_pct` (else `ERR_STRATEGY_CAP_EXCEEDED`, HTTP 422), and `concentration_manager_pct` must not exceed `manager_cap_pct` (else `ERR_MANAGER_CAP_EXCEEDED`, HTTP 422). The proposal's `proposed_amount` must fit within the remaining pacing capacity for the vehicle's vintage year under the approved plan — that is, the year's target minus the amounts of already `IC_APPROVED` proposals for that year (else `ERR_PACING_CAPACITY_EXCEEDED`, HTTP 422). Finally, segregation of duties: the acting IC member's `StaffUser` row is resolved via `X-User-ID`, the recommending analyst's row via `recommended_by_analyst_id`, and if the two rows share an `email` — the model's representation of one person holding two appointments — the approval is rejected with `ERR_SOD_VIOLATION` (HTTP 409). A successful approval spawns a `Commitment` in status `PENDING_DOCS` with `sized_amount` set equal to the `proposed_amount`. The committee may instead reject the proposal outright (`RECOMMENDED` to `IC_REJECTED`), and the drafting analyst may withdraw their own draft (`DRAFT` to `WITHDRAWN`, again requiring `X-User-ID` to match `recommended_by_analyst_id`).

A commitment is executed by an `OperationsAnalyst` once documents are in order. Execution takes two inputs: the final `sized_amount` and `expected_program_version` matching the program's current `version` (mismatch is `ERR_STALE_VERSION`). The execution is validated in order: the program must be `OPEN` with posture `NORMAL` (`ERR_POSTURE_GATED`); the final size must lie within the band of ninety percent to one hundred ten percent of the original `proposed_amount` inclusive (else `ERR_SIZE_OUT_OF_BAND`, HTTP 422); the vehicle's `vintage_year`, measured against the earliest and the latest `vintage_year` among existing `EXECUTED` commitments, must keep both spans within `max_vintage_band_years` (else `ERR_VINTAGE_BAND_BREACH`, HTTP 422); and program-level unfunded after execution must leave projected liquidity coverage at or above the buffer (else `ERR_BUFFER_BREACH`). On success the commitment transitions from `PENDING_DOCS` to `EXECUTED`, `executed_at` is set from the server clock, `committed_total` and `unfunded_total` are recomputed, the program's `version` increments, and posture is recomputed. Each executed commitment contributes to the posture envelope and the concentration checks above.

After execution, a commitment may be reduced: the `OperationsAnalyst` supplies a `reduce_to` amount that must be at least the sum of `PAID` capital calls on the commitment (else `ERR_REDUCE_BELOW_PAID`, HTTP 422); the commitment transitions from `EXECUTED` to `REDUCED`, its `sized_amount` is set to `reduce_to`, `unfunded_amount` is recomputed, and the program aggregates and `version` follow. A commitment still in `PENDING_DOCS` may instead be cancelled, which also recomputes the program aggregates and bumps the program `version`.

### 3.5. Capital Calls, Distributions, and the Unfunded Invariant

Once a commitment is `EXECUTED`, an `OperationsAnalyst` issues capital calls against it — each call row carries a system-set `commitment_id` pointing back to its funding commitment and a denormalized `program_id` for ledger queries — along with an `amount` greater than zero, a `purpose` (one of `INVESTMENT`, `FEES`, `EXPENSES`), and a `due_date` that must be strictly after the server-stamped `issued_on` (a non-strict deadline is rejected with `ERR_CALL_OVERDUE`, HTTP 422). Each call is assigned a per-commitment monotonic `call_number` starting at 1 and lands in `ISSUED`. A clock sweep — driven by advancing the logical clock — moves any `ISSUED` call whose `due_date` plus the program's `overdue_grace_days` has passed into `OVERDUE` and recomputes the program's posture; an overdue call forces posture to `RESTRICTED`.

Paying a call (allowed from `ISSUED` or from `OVERDUE`) validates three things: the commitment must be `EXECUTED` (else `ERR_COMMITMENT_NOT_EXECUTED`, HTTP 422); the call amount must not exceed the commitment's current `unfunded_amount` (else `ERR_OVERFUNDED`, HTTP 422) — this rejection happens before any ledger append, so the unfunded invariant is never violated; and paying must leave the program's `unrestricted_cash` at or above `liquidity_buffer_min` (else `ERR_BUFFER_BREACH`). On success, a `CashLedgerEntry` of kind `CAPITAL_CALL_PAYMENT` with a negative amount is appended, the commitment's `unfunded_amount` is reduced by the payment and its `version` increments, and the program's `deployed_total`, `unrestricted_cash`, `version`, and posture are all recomputed. Paying an overdue call is the standard recovery path that restores posture. A call may be cancelled only while the server's clock is at or before its `due_date` (else `ERR_CALL_OVERDUE`); cancellation moves it from `ISSUED` to `CANCELLED` with no ledger impact.

Distributions mirror the flow in the opposite direction. An `OperationsAnalyst` records a `PENDING` distribution — the distribution row carries a system-set `commitment_id` and a denormalized `program_id` — with an `amount`, a `distribution_type` (one of `RETURN_OF_CAPITAL`, `GAIN`, `INCOME`), and the `received_at` date the cash is expected. Receiving a distribution requires the commitment to be in `EXECUTED` or `REDUCED` (else `ERR_COMMITMENT_NOT_EXECUTED`), appends a `DISTRIBUTION_RECEIPT` ledger entry for the positive amount, and recomputes `returned_total`, `unrestricted_cash`, the program's `version`, and posture. A `PENDING` distribution may be cancelled.

The unfunded bookkeeping runs after every capital-call payment, every commitment reduction, and every secondary settlement: each commitment's `unfunded_amount` is its `sized_amount` minus the sum of `PAID` call amounts, the program's `unfunded_total` aggregates `unfunded_amount` over `EXECUTED` commitments plus `secondary_purchase_unfunded_total`, and any payment that would drive a commitment's `unfunded_amount` negative is rejected before any ledger append.

### 3.6. The Liquidity Forecast

A forward liquidity projection is exposed for the program, covering the next 8 quarters from the server's logical-clock quarter. For each `EXECUTED` commitment, expected future calls are computed by applying a built-in vintage call curve — a fixed 12-quarter curve keyed by the vehicle's `vintage_year` and quarters-since-vintage, summing to 1.0 — to the commitment's `unfunded_amount`. Each `ISSUED` or `OVERDUE` call contributes its full amount in the quarter containing its `due_date`. Each `ACCEPTED` secondary bid on the `PURCHASE` side contributes its full `price` in the current quarter. Each `PENDING` distribution contributes its `amount` as an inflow in the quarter containing its `received_at`. The forecast's `forecast_net_cash` for each quarter is the current `unrestricted_cash` minus the quarter's expected calls, minus the quarter's issued-or-overdue calls, minus the accepted purchase prices, plus the quarter's pending distribution inflows; all amounts are rounded to 2 decimal places round half up. When the requester passes the `stress` query flag, a stress variant is applied: pending distributions are excluded from inflows and expected calls are scaled by a factor of 1.15, with the same inclusion set otherwise. The response carries the `program_id`, the `base_quarter`, the `forecast_net_cash` array, and the program's current `posture`.

### 3.7. Secondary Purchases and Sales

An `Analyst` proposes a secondary transaction against a program by supplying the `vehicle_id` of the underlying vehicle, the `side` (`PURCHASE` when the program buys a position, `SALE` when it sells one), a positive `nav_basis` (the latest reported NAV basis for the position), a positive `price`, an `unfunded_assumed` amount (at least zero; required for `PURCHASE`, and must be exactly zero for `SALE`), and a `linked_commitment_id` (required for `SALE` — the program's own position being sold — and must be null for `PURCHASE`). The system computes `pricing_deviation_pct` as the signed ratio of `price` minus `nav_basis` over `nav_basis`, and the bid lands in `PROPOSED`.

The committee may counter a proposed bid (from `PROPOSED` to `COUNTERED`) whenever the program's posture is not `FROZEN`. The `CIO` accepts a bid from either `PROPOSED` or `COUNTERED`, with identical preconditions in both cases: the program must be `OPEN` with posture `NORMAL` (else `ERR_POSTURE_GATED`); on the `PURCHASE` side, `pricing_deviation_pct` must not exceed `secondary_premium_cap_pct` (else `ERR_PREMIUM_CAP_EXCEEDED`, HTTP 422); on the `SALE` side, the negated deviation — the discount below NAV basis — must not exceed `secondary_discount_cap_pct` (else `ERR_DISCOUNT_CAP_EXCEEDED`, HTTP 422); and on the `SALE` side, the linked commitment must be in `EXECUTED` status and belong to this program and this vehicle. The `CIO` may instead reject a proposed bid outright, moving it from `PROPOSED` to the terminal `REJECTED` status, and the analyst may withdraw a proposed bid, moving it from `PROPOSED` to `WITHDRAWN`.

Settlement of an `ACCEPTED` bid is performed by an `OperationsAnalyst` and is OCC-guarded: the request carries `expected_program_version` matching the program's current `version` (mismatch is `ERR_STALE_VERSION`), because the liquidity buffer and the linked commitment's funded position both mutate between accept and settle. Settlement requires posture not `FROZEN` (else `ERR_POSTURE_GATED`). On the `PURCHASE` side, the cash outflow must leave `unrestricted_cash` at or above `liquidity_buffer_min` (else `ERR_BUFFER_BREACH`); the settle appends a `SECONDARY_SETTLEMENT_OUT` ledger entry for the negative `price`, creates a new `Commitment` on the traded vehicle already in `EXECUTED` status with `sized_amount` equal to the sum of `price` and `unfunded_assumed`, `unfunded_amount` equal to `unfunded_assumed`, and `proposal_id` null, and recomputes `secondary_purchase_unfunded_total`, `committed_total`, `unfunded_total`, and `unrestricted_cash`. On the `SALE` side, settlement re-checks that the linked commitment's `unfunded_amount` still equals its `sized_amount` minus paid calls; the settle appends a `SECONDARY_SETTLEMENT_IN` entry for the positive `price`, moves the linked commitment to `REDUCED` with `sized_amount` set to its paid-to-date total and `unfunded_amount` set to zero. In both cases the program's `version` increments and posture is recomputed.

### 3.8. Quarterly Snapshots, Look-Through Exposure, and Valuation Reports

An `OperationsAnalyst` records a quarterly holding snapshot for a commitment — the snapshot row carries a system-set `commitment_id` and a denormalized `vehicle_id` for roll-ups — by supplying an `as_of_quarter` label in `YYYY-Qn` form and a non-negative `reported_nav` for the program's stake. The label is unique per commitment — a duplicate quarter for the same commitment is rejected with `ERR_DUPLICATE_QUARTER` (HTTP 409). Each snapshot lands in `PROVISIONAL` with `reported_at` stamped from the server clock, and its `is_final` flag is false. Finalizing a snapshot moves it from `PROVISIONAL` to `FINAL`, sets `is_final` true, and cascades: any valuation report for the same program and quarter currently `PUBLISHED` is moved to `RESTATED`, with its NAV fields recomputed on next publish. Restating a final snapshot moves it from `FINAL` to `RESTATED`, after which a replacement `PROVISIONAL` snapshot may be created for the same quarter; the same published-report cascade applies, and snapshots in `RESTATED` are excluded from every rollup sum.

Look-through lines are appended to a snapshot — each line carries a system-set `snapshot_id` linking it back to its parent snapshot — along with a `sector` (one of `TECH`, `HEALTHCARE`, `INDUSTRIALS`, `CONSUMER`, `FINANCIALS`, `ENERGY`, `OTHER`), a `geography` (one of `NA`, `EU`, `APAC`, `LATAM`, `MEA`), and a non-negative `exposure_amount` in base currency. A program-level look-through view aggregates these lines across the latest quarter's snapshots, grouped by a `group_by` dimension and optionally filtered by `as_of_quarter`.

A valuation report is opened per program for a specific `as_of_quarter`, unique per program (duplicates are rejected with `ERR_DUPLICATE_QUARTER`). Publishing a report — from `OPEN`, or from `RESTATED` under the same preconditions — requires at least one snapshot to exist for the program and quarter (else `ERR_NO_SNAPSHOTS`, HTTP 422) and computes three NAV variants, two IRR variants, and the fee-burden figure.

The NAV rollup walks each commitment that has at least one snapshot for the program and quarter. If a `FINAL` snapshot exists whose `reported_at` falls within 90 days after quarter end — the lag policy — the commitment contributes that snapshot's `reported_nav` to both `nav_final` and `nav_reported`; when several `FINAL` snapshots qualify, the latest by `reported_at` ascending wins, with ties broken by `created_at` ascending. A `FINAL` snapshot reported more than 90 days after quarter end is excluded from `nav_final`, and the commitment falls back to its latest `PROVISIONAL` snapshot if one exists, contributing that to both `nav_provisional` and `nav_reported`; if neither source exists, the commitment contributes nothing. `nav_reported` is the sum of `nav_final` and `nav_provisional` contributions. All NAV figures are rounded to 2 decimal places round half up.

The IRR figures solve for the rate that zeroes out net present value over a chronological cashflow series — `PAID` capital calls as outflows at their pay time, `RECEIVED` distributions as inflows at `received_at`, ordered by date ascending with `created_at` ascending as the tie-break — plus a terminal value at quarter end. `irr_provisional_pct` uses `nav_provisional` as the terminal value and `irr_final_pct` uses `nav_final`; the two differ whenever the NAV variants diverge, and both are reported as percentages to 2 decimal places round half up.

The fee-layering calculation totals the trailing quarter's fee burden across every `EXECUTED` or `REDUCED` commitment. For each commitment, the underlying-fund layer accrues an annual management fee of `sized_amount` multiplied by the applicable rate — `mgmt_fee_rate_early` while the number of quarters since the vehicle's `vintage_year` is at most four times `investment_period_years`, else `mgmt_fee_rate_late` — divided by four for a quarterly accrual. The underlying carry layer is the greater of zero or the excess of NAV gain over hurdle return, multiplied by `carry_rate`; NAV gain is the latest `reported_nav` minus total paid calls, and the hurdle return is total paid calls multiplied by `hurdle_rate` multiplied by the number of whole quarters from the vehicle's vintage-year Q1 through the report quarter inclusive, divided by four. The fund-of-funds wrapper layer adds `sized_amount` multiplied by the wrapper rate of 0.005, divided by four, per quarter. Each commitment's quarterly fee is rounded to 2 decimal places round half up before summing — the round-then-sum order is pinned — and `total_fee_burden_pct` is the sum of all fee layers over the trailing `min(4, quarters_held)` quarters ending at the report quarter, divided by the greater of `nav_reported` or 0.01, expressed as a percentage.

Once `PUBLISHED`, a report is moved to `RESTATED` automatically whenever a snapshot for the same program and quarter is finalized or restated; republishing from `RESTATED` recomputes every computed field from the current snapshot set.

### 3.9. Staff Directory and Segregation-of-Duties Plumbing

The `CIO` administers the `StaffUser` directory, registering each staff member with a `display_name`, a `staff_role` (one of `ANALYST`, `IC_MEMBER`, `OPS_ANALYST`) that names the entity-backed role the row backs, and an `email`. Email is deliberately not unique: two `StaffUser` rows sharing an email model the same person holding two role appointments, which is precisely what the segregation-of-duties check on IC approval detects. The returned `StaffUser.id` is what clients present as `X-User-ID` when acting in the corresponding entity-backed role.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource (including every state-transition action) return `200 OK`. All endpoints are mounted under the `/fof` prefix.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/fof/programs` | Create a FoFProgram in status DRAFT | CIO |
| GET | `/fof/programs` | List programs | Any authenticated role |
| GET | `/fof/programs/{programId}` | Get one program with aggregates and posture | Any authenticated role |
| POST | `/fof/programs/{id}/open` | Open program (requires buffer-funded cash) | CIO |
| POST | `/fof/programs/{id}/suspend` | Suspend program (posture FROZEN) | CIO |
| POST | `/fof/programs/{id}/resume` | Resume a suspended program | CIO |
| POST | `/fof/programs/{id}/close` | Close program; cascades to plans and proposals | CIO |
| POST | `/fof/programs/{id}/ledger-entries` | Append a manual CONTRIBUTION or MANUAL_ADJUSTMENT ledger entry | OperationsAnalyst |
| GET | `/fof/programs/{id}/ledger-entries` | List ledger entries for a program | Any authenticated role |
| GET | `/fof/programs/{id}/liquidity-forecast` | 8-quarter forward liquidity forecast; `stress=true` applies the stress variant | CIO, Analyst, InvestmentCommittee, OperationsAnalyst |
| POST | `/fof/programs/{id}/pacing-plans` | Create a PacingPlan in DRAFT | Analyst |
| GET | `/fof/programs/{id}/pacing-plans` | List pacing plans for a program | Any authenticated role |
| GET | `/fof/programs/{id}/pacing-plans/{planId}` | Get one pacing plan | Any authenticated role |
| POST | `/fof/programs/{id}/pacing-plans/{planId}/approve` | Approve a pacing plan; runs pacing targets | CIO |
| POST | `/fof/programs/{id}/pacing-plans/{planId}/supersede` | Atomically supersede APPROVED plan with a DRAFT replacement (OCC-guarded) | CIO |
| POST | `/fof/managers` | Register a manager (PROSPECT) | Analyst |
| GET | `/fof/managers` | List managers | Any authenticated role |
| GET | `/fof/managers/{managerId}` | Get one manager | Any authenticated role |
| POST | `/fof/managers/{id}/approve` | Approve manager (requires an APPROVED vehicle) | CIO |
| POST | `/fof/managers/{id}/suspend` | Suspend manager; cascades DECLINED/WITHDRAWN | ComplianceOfficer |
| POST | `/fof/managers/{id}/reinstate` | Reinstate a suspended manager | ComplianceOfficer |
| POST | `/fof/managers/{id}/exit` | Exit manager (no live commitments) | CIO |
| POST | `/fof/managers/{id}/vehicles` | Create a fund vehicle (SCREENING) | Analyst |
| GET | `/fof/managers/{id}/vehicles` | List vehicles for a manager | Any authenticated role |
| GET | `/fof/managers/{id}/vehicles/{vehicleId}` | Get one vehicle | Any authenticated role |
| POST | `/fof/managers/{id}/vehicles/{vehicleId}/begin-diligence` | Move vehicle SCREENING → IN_DILIGENCE and spawn DD round 1 | Analyst |
| POST | `/fof/managers/{id}/vehicles/{vehicleId}/approve-vehicle` | Approve vehicle after completed DD with composite ≥ 70 | InvestmentCommittee |
| POST | `/fof/managers/{id}/vehicles/{vehicleId}/decline-vehicle` | Decline vehicle; cascades open reviews to WITHDRAWN | InvestmentCommittee |
| POST | `/fof/managers/{id}/vehicles/{vehicleId}/close-to-new` | Close an APPROVED vehicle to new commitments | InvestmentCommittee |
| GET | `/fof/vehicles/{vehicleId}` | Get one vehicle by id (flat form) | Any authenticated role |
| GET | `/fof/vehicles/{id}/commitments` | List commitments into a vehicle | Any authenticated role |
| GET | `/fof/vehicles/{id}/secondary-bids` | List secondary bids referencing a vehicle | Any authenticated role |
| GET | `/fof/vehicles/{id}/snapshots` | List holding snapshots for a vehicle | Any authenticated role |
| GET | `/fof/pacing-plans/{planId}` | Get one pacing plan by id (flat form) | Any authenticated role |
| GET | `/fof/pacing-plans/{id}/proposals` | List proposals drawing against a pacing plan | Any authenticated role |
| GET | `/fof/programs/{id}/proposals` | List proposals for a program | Any authenticated role |
| GET | `/fof/programs/{id}/calls` | List all capital calls across the program's commitments | Any authenticated role |
| GET | `/fof/programs/{id}/distributions` | List all distributions across the program's commitments | Any authenticated role |
| GET | `/fof/commitments/{commitmentId}` | Get one commitment by id (flat form) | Any authenticated role |
| GET | `/fof/commitments/{id}/calls` | List calls for a commitment (flat form) | Any authenticated role |
| GET | `/fof/commitments/{id}/distributions` | List distributions for a commitment (flat form) | Any authenticated role |
| GET | `/fof/commitments/{id}/secondary-bids` | List secondary bids linked to a commitment | Any authenticated role |
| GET | `/fof/proposals/{id}/commitments` | List commitments spawned from a proposal | Any authenticated role |
| POST | `/fof/vehicles/{id}/dd-reviews` | Open a new DD review round on a vehicle in IN_DILIGENCE | Analyst |
| GET | `/fof/vehicles/{id}/dd-reviews` | List DD reviews for a vehicle | Any authenticated role |
| GET | `/fof/vehicles/{id}/dd-reviews/{reviewId}` | Get one DD review | Any authenticated role |
| PUT | `/fof/vehicles/{id}/dd-reviews/{reviewId}` | Update scores while DRAFT or INFO_REQUESTED | Analyst |
| POST | `/fof/vehicles/{id}/dd-reviews/{reviewId}/submit` | Submit review; computes composite score | Analyst |
| POST | `/fof/vehicles/{id}/dd-reviews/{reviewId}/request-info` | IC kicks review back for more info | InvestmentCommittee |
| POST | `/fof/vehicles/{id}/dd-reviews/{reviewId}/resubmit` | Resubmit after info request; recomputes composite | Analyst |
| POST | `/fof/vehicles/{id}/dd-reviews/{reviewId}/complete` | Complete a submitted review | InvestmentCommittee |
| POST | `/fof/vehicles/{id}/dd-reviews/{reviewId}/withdraw` | Withdraw a draft review | Analyst |
| POST | `/fof/vehicles/{id}/proposals` | Create an InvestmentProposal in DRAFT | Analyst |
| GET | `/fof/vehicles/{id}/proposals` | List proposals for a vehicle | Any authenticated role |
| GET | `/fof/proposals/{proposalId}` | Get one proposal | Any authenticated role |
| POST | `/fof/proposals/{id}/recommend` | Analyst recommends; runs concentration check | Analyst |
| POST | `/fof/proposals/{id}/ic-approve` | IC approves; enforces SoD + caps; spawns Commitment | InvestmentCommittee |
| POST | `/fof/proposals/{id}/ic-reject` | IC rejects proposal | InvestmentCommittee |
| POST | `/fof/proposals/{id}/withdraw` | Analyst withdraws own draft proposal | Analyst |
| GET | `/fof/programs/{id}/commitments` | List commitments for a program | Any authenticated role |
| GET | `/fof/programs/{id}/commitments/{commitmentId}` | Get one commitment | Any authenticated role |
| POST | `/fof/programs/{id}/commitments/{commitmentId}/execute` | Execute commitment documents (OCC-guarded) | OperationsAnalyst |
| POST | `/fof/programs/{id}/commitments/{commitmentId}/reduce` | Reduce an EXECUTED commitment's size | OperationsAnalyst |
| POST | `/fof/programs/{id}/commitments/{commitmentId}/cancel` | Cancel a PENDING_DOCS commitment | OperationsAnalyst |
| POST | `/fof/programs/{id}/commitments/{commitmentId}/calls` | Issue a capital call against a commitment | OperationsAnalyst |
| GET | `/fof/programs/{id}/commitments/{commitmentId}/calls` | List calls for a commitment | Any authenticated role |
| GET | `/fof/calls/{callId}` | Get one capital call | Any authenticated role |
| POST | `/fof/calls/{callId}/pay` | Pay a capital call; appends ledger entry | OperationsAnalyst |
| POST | `/fof/calls/{callId}/cancel` | Cancel an ISSUED call at or before its due date | OperationsAnalyst |
| POST | `/fof/programs/{id}/commitments/{commitmentId}/distributions` | Record a PENDING distribution | OperationsAnalyst |
| GET | `/fof/programs/{id}/commitments/{commitmentId}/distributions` | List distributions for a commitment | Any authenticated role |
| GET | `/fof/distributions/{distributionId}` | Get one distribution | Any authenticated role |
| POST | `/fof/distributions/{distributionId}/receive` | Mark distribution received; appends ledger entry | OperationsAnalyst |
| POST | `/fof/distributions/{distributionId}/cancel` | Cancel a PENDING distribution | OperationsAnalyst |
| POST | `/fof/programs/{id}/secondary-bids` | Propose a secondary purchase or sale | Analyst |
| GET | `/fof/programs/{id}/secondary-bids` | List secondary bids | Any authenticated role |
| GET | `/fof/programs/{id}/secondary-bids/{bidId}` | Get one bid | Any authenticated role |
| POST | `/fof/programs/{id}/secondary-bids/{bidId}/counter` | IC counters a proposed bid | InvestmentCommittee |
| POST | `/fof/programs/{id}/secondary-bids/{bidId}/accept` | CIO accepts a PROPOSED or COUNTERED bid | CIO |
| POST | `/fof/programs/{id}/secondary-bids/{bidId}/settle` | Settle an ACCEPTED bid (OCC-guarded) | OperationsAnalyst |
| POST | `/fof/programs/{id}/secondary-bids/{bidId}/reject` | CIO rejects a bid | CIO |
| POST | `/fof/programs/{id}/secondary-bids/{bidId}/withdraw` | Analyst withdraws a proposed bid | Analyst |
| POST | `/fof/commitments/{id}/snapshots` | Record a quarterly holding snapshot in PROVISIONAL | OperationsAnalyst |
| GET | `/fof/commitments/{id}/snapshots` | List snapshots for a commitment | Any authenticated role |
| GET | `/fof/snapshots/{snapshotId}` | Get one snapshot | Any authenticated role |
| POST | `/fof/snapshots/{id}/finalize` | Finalize a provisional snapshot | OperationsAnalyst |
| POST | `/fof/snapshots/{id}/restate` | Restate a FINAL snapshot | OperationsAnalyst |
| POST | `/fof/snapshots/{id}/look-through-lines` | Append look-through exposure lines to a snapshot | OperationsAnalyst |
| GET | `/fof/snapshots/{id}/look-through-lines` | List look-through lines for a snapshot | Any authenticated role |
| GET | `/fof/programs/{id}/look-through` | Aggregated look-through exposure by sector or geography | Any authenticated role |
| POST | `/fof/programs/{id}/valuation-reports` | Create an OPEN valuation report for a quarter | OperationsAnalyst |
| GET | `/fof/programs/{id}/valuation-reports` | List valuation reports | Any authenticated role |
| GET | `/fof/programs/{id}/valuation-reports/{reportId}` | Get one valuation report | Any authenticated role |
| POST | `/fof/programs/{id}/valuation-reports/{reportId}/publish` | Publish report; computes NAV variants, IRR variants, fee layering | OperationsAnalyst |
| POST | `/fof/staff-users` | Register a staff user backing an entity-backed role | CIO |
| GET | `/fof/staff-users` | List staff users | Any authenticated role |
| GET | `/fof/staff-users/{staffUserId}` | Get one staff user | Any authenticated role |
| POST | `/fof/_clock/set_current_utc` | Advance the server's logical clock; runs the overdue sweep | OperationsAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REF_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_POSTURE_GATED` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_DD_SCORE_TOO_LOW` | 422 |
| `ERR_BUFFER_BREACH` | 422 |
| `ERR_PREMIUM_CAP_EXCEEDED` | 422 |
| `ERR_DISCOUNT_CAP_EXCEEDED` | 422 |
| `ERR_STRATEGY_CAP_EXCEEDED` | 422 |
| `ERR_MANAGER_CAP_EXCEEDED` | 422 |
| `ERR_VINTAGE_BAND_BREACH` | 422 |
| `ERR_SIZE_OUT_OF_BAND` | 422 |
| `ERR_PACING_CAPACITY_EXCEEDED` | 422 |
| `ERR_MIX_SUM_INVALID` | 422 |
| `ERR_ACTIVE_PLAN_EXISTS` | 409 |
| `ERR_PLAN_NOT_DRAFT` | 422 |
| `ERR_PLAN_NOT_APPROVED` | 422 |
| `ERR_OVERFUNDED` | 422 |
| `ERR_REDUCE_BELOW_PAID` | 422 |
| `ERR_CALL_OVERDUE` | 422 |
| `ERR_DUPLICATE_QUARTER` | 409 |
| `ERR_NO_APPROVED_VEHICLE` | 422 |
| `ERR_VEHICLE_NOT_APPROVED` | 422 |
| `ERR_MANAGER_NOT_ELIGIBLE` | 422 |
| `ERR_COMMITMENT_NOT_EXECUTED` | 422 |
| `ERR_NO_SNAPSHOTS` | 422 |
