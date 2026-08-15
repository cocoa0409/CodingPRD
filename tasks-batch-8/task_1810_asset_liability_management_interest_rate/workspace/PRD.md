# Bank ALM Interest Rate Risk API — Product Requirements Document

## 1. Introduction

A bank's earnings live in the spread between what it earns on loans and securities and what it pays on deposits and borrowings, and that spread moves when interest rates move. This document specifies the Bank ALM Interest Rate Risk API: the system of record through which a bank's Asset-Liability Committee (ALCO) models cash flows under prepayment and deposit decay assumptions, simulates parallel rate shocks, ramps, and regulatory preset scenarios, measures net interest income and the economic value of equity against board-approved policy limits, governs deposit beta and prepayment assumptions through a segregation-of-duties approval flow, designates and effectiveness-tests hedging derivatives, works the resulting limit breaches to closure, and reports monthly to the committee with full regulatory coverage tracking.

The API is organized around a small set of cooperating aggregates with sharply separated duties. A `TreasuryAnalyst` maintains the balance sheet as books and positions, drafts assumption sets and scenarios, runs and publishes simulations, and drafts the monthly ALCO report. An `ALCOChair` approves or rejects assumptions, owns policy limits, designates and retires hedges, works the breach lifecycle, closes backtest reviews, and acknowledges reports. A `ModelRiskValidator` provides independent model risk control by recording hedge effectiveness tests and backtesting assumptions. A `Regulator` observes everything on a read-only basis. A logical clock — never wall-clock time — drives reporting periods, designation windows, and breach escalation, so the entire governance cycle is deterministic and reproducible under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly four roles, spelled as follows: `TreasuryAnalyst`, `ModelRiskValidator`, `ALCOChair`, and `Regulator`. Each operation is restricted to a defined set of roles (see §4); a caller whose role is not permitted for the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For all four roles — `TreasuryAnalyst`, `ModelRiskValidator`, `ALCOChair`, and `Regulator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any resource's `id`. It may, however, record it for audit and segregation-of-duties purposes: an `AssumptionSet` remembers its `created_by_user_id` and later its `approved_by_user_id`, and an `AlcoReport` remembers its `submitted_by_user_id` and `acknowledged_by_user_id`. The segregation-of-duties rules in §2.10 and §3 compare these recorded identifiers against the caller's `X-User-ID`.

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

List endpoints are paginated through query parameters. The `limit` parameter specifies the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Monthly Period Conventions

The system runs on a logical clock, not wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter; it advances only when an authorized caller moves it. A dedicated clock-setting capability accepts a `to_iso8601` instant and returns the resulting `current_utc`. This capability is available to `TreasuryAnalyst`, `ModelRiskValidator`, and `ALCOChair`; the `Regulator` role cannot move the clock. Moving the clock triggers the breach escalation sweep described in §3.5.

Monthly conventions pervade the model. Reporting periods and designation windows are expressed as `YYYY-MM` month strings; a run or breach stamped with `period_month` carries the `YYYY-MM` of the logical clock at the moment of its creation. Month comparisons in this document (for example, whether a window has fully elapsed) are comparisons of calendar month indices.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource.

The one exception is the `HedgeEffectivenessTest`, an append-only event record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent, because a recorded test is never modified.

### 2.6. Precision, Rounding, and Basis-Point Arithmetic

Rates are expressed in integer basis points throughout (400 means 4.00%), and monetary amounts are expressed in integer cents. The rounding discipline is pinned:

- Interest and expense amounts are rounded half-up to integer cents **per position first**, and only then summed. Unrounded per-position values are never summed and rounded once at the end.
- Derived percentage outputs (`nii_delta_pct`, `eve_delta_pct`, `deviation_pct`) are rounded half-up to exactly two decimal places.
- The hedge effectiveness `offset_ratio` is rounded half-up to exactly four decimal places.
- Intermediate quantities — the ramp-averaged year-one rate delta, effective prepayment and decay percentages, blended rates, and pass-through fractions — are used unrounded in downstream formulas.

### 2.7. Optimistic Concurrency Control on Book-Coupled Writes

Two write operations are guarded by optimistic concurrency control against the parent book: creating a simulation run against a book (`POST /books/{id}/simulation-runs`) and patching a position's economics (`PATCH /positions/{id}`). Each of these requests must carry `expected_book_version` as a non-optional input field, holding the `version` of the book the client last observed. Because position creation, position patching, position retirement, book activation, and simulation-run creation each advance the book's `version`, a client whose observed version no longer matches the book's current `version` is modeling a balance sheet that has since changed; the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the book and resubmit with the fresh version. Endpoints not named in this rule take no version field at all.

### 2.8. Book-Level Aggregates and Version Propagation

Each `AlmBook` maintains three computed aggregates over its own resources. `total_assets_cents` is the sum of `balance_cents` over the book's positions with `status` `ACTIVE` and `category` either `LOAN` or `SECURITY`. `total_liabilities_cents` is the sum of `balance_cents` over the book's `ACTIVE` positions with `category` either `DEPOSIT` or `BORROWING`. `hedged_notional_cents` is the sum of `notional_cents` over hedge relationships with `status` either `DESIGNATED` or `ACTIVE` that reference positions of the book. These aggregates are recomputed whenever their inputs change — position creation, patching, and retirement for the balance totals; hedge designation, dedesignation, termination, and failure-driven dedesignation for the hedged total.

Every mutation that recomputes a book's aggregates also advances the book itself: book activation, position creation, position patching, position retirement, and simulation-run creation each increment the book's `version` by one and refresh its `updated_at`. Mutations of any resource refresh that resource's own `updated_at` and increment its own `version` as well.

### 2.9. Nested Resource Retrieval and Validation Ordering

When an endpoint path contains multiple resource identifiers (for example, a position created under a book, or a hedge listed under a position), the server validates the existence of each identifier strictly left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource.

Beyond path resolution, every request is evaluated against twelve classes of checks in a fixed priority order, and an earlier failure masks every later one:

1. **Identity headers** — `X-User-ID` and `X-User-Role` present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role is listed for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Path existence** — every path identifier exists, left-to-right (`ERR_NOT_FOUND`).
4. **Body shape** — required fields present, enums valid, ranges valid, kind-conditional fields present (`ERR_INVALID_REQUEST`, `ERR_DEPOSIT_SEGMENT_REQUIRED`, `ERR_ASSUMPTION_PARAMS_MISMATCH`, `ERR_OBSERVED_VALUE_INVALID`).
5. **Optimistic concurrency** — `expected_book_version` matches the book's current `version` (`ERR_STALE_VERSION`).
6. **State-transition legality** — the target resource's current state permits the requested transition (`ERR_INVALID_STATE_TRANSITION`, `ERR_BOOK_NOT_ACTIVE`, `ERR_BOOK_ACTIVATION_INCOMPLETE`).
7. **Segregation of duties** — approver differs from creator; acknowledger differs from submitter (`ERR_SEGREGATION_OF_DUTIES`).
8. **Uniqueness and overlap** — policy-limit scope conflicts, report-period conflicts, hedge window overlap, backtest window overlap (`ERR_LIMIT_SCOPE_CONFLICT`, `ERR_REPORT_PERIOD_CONFLICT`, `ERR_HEDGE_WINDOW_OVERLAP`, `ERR_BACKTEST_WINDOW_OVERLAP`).
9. **Clock-relative windows** — designation window not in the past, hedge activatable, backtest window fully elapsed (`ERR_DESIGNATION_WINDOW_PAST`, `ERR_HEDGE_NOT_ACTIVATABLE`, `ERR_BACKTEST_WINDOW_NOT_ELAPSED`).
10. **Hedge notional ceiling** — the hedge notional must not exceed the hedged position's balance (`ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE`).
11. **Cross-entity state references** — scenario active, pinned assumption sets approved and not under review, hedged position active, retirement unblocked, revised closure justified (`ERR_SCENARIO_NOT_ACTIVE`, `ERR_ASSUMPTION_NOT_APPROVED`, `ERR_ASSUMPTION_UNDER_REVIEW`, `ERR_POSITION_RETIRED`, `ERR_POSITION_HAS_ACTIVE_HEDGE`, `ERR_BACKTEST_CLOSURE_REQUIRES_REVISION`).
12. **Aggregate gates** — report submission requires complete regulatory coverage; report acknowledgement requires zero open breaches (`ERR_REGULATORY_COVERAGE_INCOMPLETE`, `ERR_OPEN_BREACHES_REMAIN`).

### 2.10. Segregation of Duties

Two approval boundaries are enforced by comparing recorded user identifiers rather than roles. An assumption set may not be approved by the same operator who created it, and an ALCO report may not be acknowledged by the same operator who submitted it. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). These comparisons use the recorded `created_by_user_id` and `submitted_by_user_id` against the acting caller's `X-User-ID`.

## 3. Business Logic & Workflows

### 3.1. Building the Book: Positions and Activation

A `TreasuryAnalyst` opens a new book by supplying a display `name`, a flat base yield-curve level `base_curve_rate_bps` in basis points (for example, 400 represents a 4.00% curve), and optionally `min_hedged_notional_cents`, the policy floor for total hedged notional that defaults to 0 when omitted. A new book starts in `DRAFT` status with all three aggregates at zero.

Positions are added to a book through a payload carrying the `category` — one of `LOAN`, `SECURITY`, `DEPOSIT`, or `BORROWING` — together with `balance_cents` (the current principal balance, strictly greater than 0), `rate_bps` (the contractual coupon for assets or the paid rate for liabilities, at least 0), `scheduled_runoff_pct` (the contractual annual principal runoff fraction, from 0 to 100 percent), and `duration_years` (the effective duration consumed by the economic-value approximation, at least 0). A loan may additionally carry `is_prepayment_eligible`, defaulting to `false`, marking it as subject to the prepayment assumption set. When the `category` is `DEPOSIT`, a `deposit_segment` of `RETAIL_NONMATURITY`, `BUSINESS_NONMATURITY`, or `TIME` must be present; omitting it is rejected with `ERR_DEPOSIT_SEGMENT_REQUIRED` (HTTP 422). Each new position lands in `ACTIVE` status, the book's balance totals are recomputed, and the book's `version` advances by one. The position list of a book can be filtered by `category` and `status`.

Before a book can host simulation runs it must be activated. Activation moves the book from `DRAFT` to `ACTIVE` and is permitted only when the book holds at least one `ACTIVE` position whose `category` is `LOAN` or `SECURITY` and at least one `ACTIVE` position whose `category` is `DEPOSIT` or `BORROWING`; otherwise the activation is rejected with `ERR_BOOK_ACTIVATION_INCOMPLETE` (HTTP 409). A successful activation increments the book's `version` by one.

Position economics can be revised after creation. A `TreasuryAnalyst` patches any subset of `balance_cents`, `rate_bps`, `scheduled_runoff_pct`, `is_prepayment_eligible`, and `duration_years`, and the request must carry `expected_book_version` per §2.7 — a stale observation is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful patch recomputes the book totals and advances the book's `version`. Retirement is the terminal end of a position: retiring moves it from `ACTIVE` to `RETIRED`, but only while no hedge relationship in `PROPOSED`, `DESIGNATED`, or `ACTIVE` status references it — a referenced position is rejected with `ERR_POSITION_HAS_ACTIVE_HEDGE` (HTTP 409). Retirement recomputes the book totals with the position excluded and advances the book's `version` by one.

### 3.2. Assumption Governance: Drafting, Approval, and Supersession

Cash-flow behavior under rate movement is governed by versioned assumption sets, one per domain. The `domain` of an assumption set is fixed at creation and is one of `PREPAYMENT`, `DEPOSIT_DECAY`, or `DEPOSIT_BETA`; it is immutable thereafter. The `params` object is domain-keyed. A `PREPAYMENT` set carries `base_cpr_pct` and `prepay_sensitivity_per_100bps`. A `DEPOSIT_DECAY` set carries `base_annual_decay_pct` and `surge_decay_per_100bps`. A `DEPOSIT_BETA` set carries `up_beta_pct`, `down_beta_pct`, and `lag_months`.

A `TreasuryAnalyst` drafts a set against a book; it starts in `DRAFT` status, the server records the creator in `created_by_user_id`, the `governance_flag` starts at `NONE`, and `approved_by_user_id` and `approved_at` remain unset. While the set is in `DRAFT` its `params` may be edited; editing a set in any other status is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Submission moves the set `DRAFT → SUBMITTED`, and submission validates that the keys of `params` exactly match the schema of the set's domain — extra or missing keys are rejected with `ERR_ASSUMPTION_PARAMS_MISMATCH` (HTTP 422).

Approval is reserved for the `ALCOChair` and moves the set `SUBMITTED → APPROVED`. The approver's `X-User-ID` must differ from the recorded `created_by_user_id`; an operator approving their own draft is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Approval has three cascades: any other `APPROVED` set in the same book and domain transitions to `SUPERSEDED`; every simulation run that pinned a newly superseded set has its `assumption_stale` flag set to `true`; and the server stamps `approved_by_user_id` with the approver and `approved_at` with the logical clock. Rejection by the `ALCOChair` returns the set `SUBMITTED → DRAFT` for revision, accompanied by a `reason`, and the draft–submit–reject cycle may repeat as many times as needed. A set's `assumption_stale` semantics on the run side are definitional: the flag is `true` whenever any pinned set is no longer `APPROVED`.

### 3.3. Rate Scenarios and Regulatory Presets

Scenarios describe how rates move. A `TreasuryAnalyst` creates a scenario against a book with a display `name` and a `kind` of `PARALLEL_SHOCK`, `RAMP`, or `REGULATORY_PRESET`; new scenarios are `ACTIVE`. The kind determines which further fields are required: a `PARALLEL_SHOCK` scenario must carry `shock_bps`, the instantaneous parallel shift in basis points; a `RAMP` scenario must carry `ramp_total_bps`, the terminal shift reached linearly, and `ramp_months`, the ramp duration in months, which must be greater than 0; a `REGULATORY_PRESET` scenario must carry a `preset_code` of `REG_UP_400`, `REG_UP_300`, `REG_UP_200`, `REG_DOWN_200`, `REG_DOWN_300`, or `REG_DOWN_400`. A scenario missing the fields its kind requires is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The projection horizon `horizon_months` must be 12 or 24 and defaults to 12.

The six regulatory presets map to fixed instantaneous shocks: `REG_UP_400` is +400 basis points, `REG_UP_300` is +300, `REG_UP_200` is +200, `REG_DOWN_200` is −200, `REG_DOWN_300` is −300, and `REG_DOWN_400` is −400.

Archiving moves a scenario `ACTIVE → ARCHIVED`, its terminal state. Once a scenario is `ARCHIVED`, creating a simulation run that references it is rejected with `ERR_SCENARIO_NOT_ACTIVE` (HTTP 409).

### 3.4. The Simulation Engine: NII and EVE Projections

The simulation run is the computational heart of the ALM cycle. A `TreasuryAnalyst` requests a run against a book with a payload containing the `scenario_id`, three pinned assumption sets — `prepayment_set_id`, `decay_set_id`, and `beta_set_id` — the `balance_sheet_convention`, and the OCC field `expected_book_version` per §2.7. The book must be `ACTIVE`, else the request is rejected with `ERR_BOOK_NOT_ACTIVE` (HTTP 409). The referenced scenario must be `ACTIVE`. Each pinned set must belong to its matching domain, must be `APPROVED` (otherwise `ERR_ASSUMPTION_NOT_APPROVED`, HTTP 409), and must be free of any open breach review (otherwise `ERR_ASSUMPTION_UNDER_REVIEW`, HTTP 409, see §3.7). The `balance_sheet_convention` is `STATIC` or `DYNAMIC`; `annual_growth_pct` is required exactly when the convention is `DYNAMIC`, and a `DYNAMIC` run without it is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The run is computed synchronously and lands in `COMPLETED` status. The server records `period_month` as the logical clock's `YYYY-MM` at creation, snapshots the book's `version` at creation into `book_version_pinned`, and increments the book's `version` by one.

**The year-one rate delta.** For `PARALLEL_SHOCK` and `REGULATORY_PRESET` scenarios, the year-one delta is the effective shock itself — `shock_bps`, or the preset's mapped value. For a `RAMP`, the shift grows linearly from zero to `ramp_total_bps` over `ramp_months`, and its average over the first twelve months is pinned as follows: when the ramp completes within the first year (`ramp_months` not greater than 12), the year-one delta equals `ramp_total_bps` multiplied by the quantity twelve minus half of `ramp_months`, all divided by twelve; when the ramp extends beyond a year (`ramp_months` greater than 12), the year-one delta equals `ramp_total_bps` multiplied by six and divided by `ramp_months`. The year-one delta may be fractional and is used unrounded everywhere downstream. The economic-value computation always uses the terminal shock instead: the effective shock for `PARALLEL_SHOCK` and `REGULATORY_PRESET`, and `ramp_total_bps` for a `RAMP`.

**Effective behavioral assumptions.** For each prepayment-eligible loan, the effective annual prepayment rate is `base_cpr_pct` plus `prepay_sensitivity_per_100bps` for every full 100 basis points of rate decline — that is, the positive part of the negated year-one delta, divided by 100, multiplied by the sensitivity — with the result clamped to the 0-to-100 percent range. Falling rates speed prepayments up; rising rates never slow them below `base_cpr_pct`. Symmetrically, the effective annual decay rate for non-maturity deposits is `base_annual_decay_pct` plus `surge_decay_per_100bps` for every full 100 basis points of rate rise, clamped to the 0-to-100 percent range; falling rates leave the base decay untouched. For the paid rate on non-maturity deposits (segments `RETAIL_NONMATURITY` and `BUSINESS_NONMATURITY`; `TIME` deposits reprice through scheduled runoff like borrowings), the beta applied is `up_beta_pct` when the year-one delta is positive and `down_beta_pct` otherwise. The pass-through fraction is 1.0 for `PARALLEL_SHOCK` and `REGULATORY_PRESET` scenarios, and for a `RAMP` it is the greater of zero and twelve minus `lag_months`, divided by twelve. The deposit's new rate is its contractual `rate_bps` plus the chosen beta (divided by 100) multiplied by the year-one delta and by the pass-through fraction, floored at zero.

**Net interest income.** The projection walks every `ACTIVE` position of the book and computes interest or expense per position, rounding each per-position amount half-up to integer cents before summing — the rounding order is pinned and unrounded values are never summed first. For asset positions (`LOAN` and `SECURITY`), the runoff fraction is `scheduled_runoff_pct` plus the effective prepayment rate when the position is a prepayment-eligible loan, and the new-money rate is the greater of zero and `base_curve_rate_bps` plus the year-one delta; the blended rate is the contractual `rate_bps` weighted by the non-runoff fraction plus the new-money rate weighted by the runoff fraction. Under the `STATIC` convention the balance used is the position's `balance_cents`; under `DYNAMIC` it is `balance_cents` grown by `annual_growth_pct`. Interest is the balance used multiplied by the blended rate and divided by ten thousand. For non-maturity deposits, the rate used is the effective deposit rate above; under `STATIC` the balance is `balance_cents`, and under `DYNAMIC` the balance first shrinks by the effective annual decay percentage and then grows by `annual_growth_pct`, in that order. Expense is the balance used multiplied by the rate used, divided by ten thousand. For `TIME` deposits and borrowings, the blended rate is the contractual `rate_bps` weighted by the non-runoff fraction plus the new-money rate weighted by `scheduled_runoff_pct`, and the balance is `balance_cents` under `STATIC` or grown by `annual_growth_pct` under `DYNAMIC`; expense follows the same form. The run's net interest income is the sum of all per-position interest minus the sum of all per-position expense. Because balances differ between conventions, identical inputs produce different net interest income under `STATIC` and `DYNAMIC`.

The engine computes this projection twice: once at a delta of zero for the base (`nii_base_cents`) and once under the scenario delta (`nii_scenario_cents`). The reported `nii_delta_pct` is the scenario value minus the base value, divided by the base value, multiplied by one hundred, rounded half-up to two decimal places; when `nii_base_cents` is zero, `nii_delta_pct` is 0.00.

**Economic value of equity.** The base economic value, `eve_base_cents`, is `total_assets_cents` minus `total_liabilities_cents` over `ACTIVE` positions. The asset duration is the balance-weighted average of `duration_years` over `ACTIVE` `LOAN` and `SECURITY` positions — the sum of each position's `balance_cents` multiplied by its `duration_years`, divided by `total_assets_cents` — and the liability duration is the same weighted average over `ACTIVE` `DEPOSIT` and `BORROWING` positions against `total_liabilities_cents`. The scenario economic value, `eve_scenario_cents`, is `eve_base_cents` minus the duration-gap exposure (asset duration times total assets, minus liability duration times total liabilities) multiplied by the terminal scenario shock in basis points and divided by ten thousand, rounded half-up to integer cents. The reported `eve_delta_pct` is the scenario value minus the base value, divided by the base value, multiplied by one hundred, rounded half-up to two decimal places; when `eve_base_cents` is zero or negative, `eve_delta_pct` is 0.00.

Once both deltas exist, the run evaluates the book's policy limits (§3.5) and stamps `breach_summary` with `NONE`, `NII`, `EVE`, or `BOTH`. Every breached active limit opens a `LimitBreach` in `OPEN` status stamped with the current logical month, and the period ALCO report is upserted and recomputed — created in `DRAFT` if it does not yet exist — and if that report was `SUBMITTED` it auto-reverts to `DRAFT`.

Publishing moves a run `COMPLETED → PUBLISHED`. Publication upserts the period ALCO report for the run's book and `period_month` — creating it in `DRAFT` when absent — and recomputes its aggregates; if the report was `SUBMITTED`, it auto-reverts to `DRAFT`. Runs can be listed filtered by `book_id`, `scenario_id`, `prepayment_set_id`, `decay_set_id`, `beta_set_id`, and `status`.

### 3.5. Policy Limits and the Breach Lifecycle

Policy limits encode the board's risk appetite. The `ALCOChair` authors a limit for a book with a `metric` of `NII_DELTA_PCT` or `EVE_DELTA_PCT`, an `applies_to_kinds` scope — a list of scenario kinds, or the single string `ALL` — and a `threshold_pct` decline tolerance strictly greater than 0. A new limit is `ACTIVE`. At most one `ACTIVE` limit may exist for a given book, metric, and identical `applies_to_kinds` scope; a conflicting creation is rejected with `ERR_LIMIT_SCOPE_CONFLICT` (HTTP 409). The `ALCOChair` may patch a limit's `threshold_pct` and/or `status`, moving it between `ACTIVE` and `SUSPENDED`; a `SUSPENDED` limit is excluded from subsequent run breach evaluation, and resuming a limit (`SUSPENDED → ACTIVE`) is subject to the same scope-uniqueness check, again rejected with `ERR_LIMIT_SCOPE_CONFLICT` when another `ACTIVE` limit already covers the same scope.

Breach evaluation runs immediately after a simulation's deltas are computed. For each `ACTIVE` limit of the book whose `applies_to_kinds` is `ALL` or contains the run's scenario kind, an `NII_DELTA_PCT` limit is breached when the run's `nii_delta_pct` is strictly less than the negative of `threshold_pct`, and an `EVE_DELTA_PCT` limit is breached when the run's `eve_delta_pct` is strictly less than the negative of `threshold_pct`. A delta exactly equal to the negative threshold is not a breach, and the comparison uses the rounded two-decimal delta values stored on the run. Each breached limit creates one `LimitBreach` in `OPEN` status, recording the `run_id`, the `limit_id`, the `metric`, the `observed_delta_pct` of the run, the `threshold_pct` at breach time, and the `period_month` of the current logical month. Breaches can be listed filtered by `book_id`, `run_id`, `limit_id`, `metric`, and `status`.

The breach lifecycle is worked by the `ALCOChair`. Acknowledgement moves a breach `OPEN → ACKNOWLEDGED`; a remediation plan moves it `ACKNOWLEDGED → REMEDIATION_PLANNED` and requires a non-empty `remediation_note` together with a `due_date` timestamp, otherwise the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Closure moves a breach to its terminal `CLOSED` status from either `ACKNOWLEDGED` or `REMEDIATION_PLANNED` and requires a non-empty `resolution_note`, again otherwise `ERR_INVALID_REQUEST`.

Two system escalations ride on the logical clock. Whenever the clock is set, the escalation sweep runs: a breach still `OPEN` once the clock reaches or passes the instant five days after its `created_at` moves `OPEN → ESCALATED`, and a breach in `REMEDIATION_PLANNED` whose `due_date` the clock has passed (and which is not `CLOSED`) moves `REMEDIATION_PLANNED → ESCALATED`. An escalated breach returns to the worked state through acknowledgement, `ESCALATED → ACKNOWLEDGED`. Every acknowledgement and every closure recomputes `open_breach_count` on the period ALCO report.

A third family of breaches, with `metric` `HEDGE_COVERAGE`, originates outside simulation runs entirely — see §3.6. Those breaches carry no `run_id` and no `limit_id`, and their `observed_delta_pct` and `threshold_pct` are unset; otherwise they flow through the same lifecycle.

### 3.6. Hedge Accounting: Designation, Effectiveness, and the Coverage Floor

Hedging begins when a `TreasuryAnalyst` proposes a hedge relationship against a position of a book, supplying the `position_id` of the hedged item, an `instrument` of `PAYER_SWAP`, `RECEIVER_SWAP`, `CAP`, or `FLOOR`, a `designation_type` of `FAIR_VALUE` or `CASH_FLOW`, a `notional_cents` strictly greater than 0, and a `fixed_rate_bps` of at least 0. The new hedge starts in `PROPOSED` status.

Designation is an `ALCOChair` act that moves the hedge `PROPOSED → DESIGNATED` and pins the hedge accounting terms: a designation window from `start_month` to `end_month` and an `effectiveness_method` of `DOLLAR_OFFSET` or `REGRESSION`, which is pinned at designation and immutable thereafter. Four guards protect designation, in the priority order of §2.9. The referenced position must be `ACTIVE`, else `ERR_POSITION_RETIRED` (HTTP 409). The `start_month` must not be before the current logical month, else `ERR_DESIGNATION_WINDOW_PAST` (HTTP 409), and the `end_month` must be after the `start_month`, else `ERR_INVALID_REQUEST` (HTTP 400). The half-open window from `start_month` up to but not including `end_month` must not overlap any other `DESIGNATED` or `ACTIVE` hedge on the same position — adjacency is allowed — else `ERR_HEDGE_WINDOW_OVERLAP` (HTTP 409). Finally, `notional_cents` must not exceed the hedged position's `balance_cents`, else `ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE` (HTTP 409). A successful designation recomputes the book's `hedged_notional_cents`, because a `DESIGNATED` hedge now counts toward it.

Activation moves a hedge `DESIGNATED → ACTIVE` once the current logical month has reached the `start_month`; activating earlier is rejected with `ERR_HEDGE_NOT_ACTIVATABLE` (HTTP 409). Two voluntary exits exist, both `ALCOChair` acts accompanied by a `reason`: dedesignation, allowed from either `DESIGNATED` or `ACTIVE`, moves the hedge to its terminal `DEDESIGNATED` status, and termination, allowed from `ACTIVE`, moves it to its terminal `TERMINATED` status.

Every decrease of a book's `hedged_notional_cents` — manual dedesignation, termination, or the failure-driven dedesignation below — triggers the coverage floor check: after the hedged total is recomputed, if it has fallen below the book's `min_hedged_notional_cents`, the system creates a `LimitBreach` with `metric` `HEDGE_COVERAGE` in `OPEN` status, stamped with the current logical month, carrying no `run_id` and no `limit_id`. Increases of the hedged total never trigger this check.

Effectiveness testing is the independent control exercised by the `ModelRiskValidator`. A test is recorded against an `ACTIVE` hedge as an append-only event carrying the `hedge_id`, the `test_month` it applies to, the period change in the derivative's fair value `hedge_value_change_cents` and the period change in the hedged item's fair value `hedged_item_value_change_cents` (both signed), and the regression inputs `slope`, `r_squared` (between 0 and 1), and `sample_count`. The test's `method` snapshots the hedge's pinned `effectiveness_method` at test time, and the verdict `result` is computed per that method. Under `DOLLAR_OFFSET`, a `hedged_item_value_change_cents` of zero fails the test outright; otherwise the `offset_ratio` is the negation of the ratio of `hedge_value_change_cents` to `hedged_item_value_change_cents`, rounded half-up to four decimal places, and the test passes exactly when the ratio lies between 0.8000 and 1.2500 inclusive on both ends. Under `REGRESSION`, the test passes exactly when `r_squared` is at least 0.80, `slope` lies between 0.80 and 1.25 inclusive, and `sample_count` is at least 12. Each method ignores the other method's inputs — the value-change pair plays no part in a `REGRESSION` verdict, and the regression triple plays no part in a `DOLLAR_OFFSET` verdict — so the same payload can `PASS` under one method and `FAIL` under the other.

A `FAIL` result is consequential: it drives the hedge `ACTIVE → DEDESIGNATED` automatically, the book's `hedged_notional_cents` is recomputed downward, and the coverage floor check above runs, so a failed test can open a `HEDGE_COVERAGE` breach.

### 3.7. Backtesting and Model Risk Governance

Assumptions are validated against reality through backtest reviews. A `ModelRiskValidator` opens a review against an assumption set — of any status — identified by `assumption_set_id`, supplying the observation window's `start_month`, its length `observation_months` (strictly greater than 0), and the `observed_value_pct` realized over the window: a realized CPR percentage for a `PREPAYMENT` set, a realized annual decay percentage for a `DEPOSIT_DECAY` set, or a realized up-beta percentage for a `DEPOSIT_BETA` set. An `observed_value_pct` outside the 0-to-100 range is rejected with `ERR_OBSERVED_VALUE_INVALID` (HTTP 422). The review snapshots the set's `domain` and its book.

Two window rules govern creation. The observation window must be fully elapsed relative to the logical clock — the current month index must be at least the start month index plus `observation_months` — otherwise creation is rejected with `ERR_BACKTEST_WINDOW_NOT_ELAPSED` (HTTP 409). And the window must neither overlap nor abut an existing review window on the same assumption set: a gap of at least one month is required between windows, otherwise creation is rejected with `ERR_BACKTEST_WINDOW_OVERLAP` (HTTP 409).

The review computes its own verdict. The `predicted_value_pct` is drawn from the set's `params` by domain — `base_cpr_pct` for `PREPAYMENT`, `base_annual_decay_pct` for `DEPOSIT_DECAY`, and `up_beta_pct` for `DEPOSIT_BETA`. The `deviation_pct` is the absolute difference between observed and predicted, rounded half-up to two decimal places. The `outcome` is `BREACH` exactly when the deviation strictly exceeds the domain tolerance — 3.0 percentage points for `PREPAYMENT`, 2.0 percentage points for `DEPOSIT_DECAY`, and 10.0 percentage points for `DEPOSIT_BETA`; a deviation exactly equal to the tolerance is `WITHIN_TOLERANCE`. A `BREACH` outcome raises the set's `governance_flag` to `REVIEW_REQUIRED`, and while any `BREACH` review remains `OPEN` for a set, simulation-run creation pinning that set is rejected with `ERR_ASSUMPTION_UNDER_REVIEW` (HTTP 409) — this is the intended serialization point between model risk and treasury modeling.

Closure is an `ALCOChair` act supplying an `outcome` of `CLOSED_ACCEPTED` or `CLOSED_REVISED`, moving the review `OPEN → CLOSED_ACCEPTED` or `OPEN → CLOSED_REVISED` respectively; both are terminal. Closing as `CLOSED_REVISED` asserts that the model has been revised: another assumption set in the same book and domain must be `APPROVED` with a `created_at` later than the reviewed set's `created_at`, otherwise the closure is rejected with `ERR_BACKTEST_CLOSURE_REQUIRES_REVISION` (HTTP 409). When a closure leaves no other `OPEN` review referencing the same set, the set's `governance_flag` returns to `NONE`.

### 3.8. The Monthly ALCO Reporting Cycle

The ALCO report is the period pack that ties runs and breaches together. A `TreasuryAnalyst` creates the report for a book and a `period_month`; it starts in `DRAFT` with its aggregates initialized from the runs and breaches then present. Only one non-terminal report may exist for a book and period — a second creation while a `DRAFT` or `SUBMITTED` report exists for the same pair is rejected with `ERR_REPORT_PERIOD_CONFLICT` (HTTP 409).

Five aggregates define the pack. `run_count` is the number of `PUBLISHED` simulation runs of the book in the period. `worst_nii_delta_pct` and `worst_eve_delta_pct` are the minimum `nii_delta_pct` and `eve_delta_pct` over those runs, and are null when the period has no published runs. `open_breach_count` counts the book's breaches in the period whose status is anything other than `CLOSED`. `regulatory_coverage_complete` is true exactly when each of the six `preset_code` values has at least one `PUBLISHED` run in the period. These aggregates are recomputed whenever runs are published, breaches are created, acknowledged, or closed, or the report is created.

Submission moves the report `DRAFT → SUBMITTED` and requires complete regulatory coverage — a submission while `regulatory_coverage_complete` is false is rejected with `ERR_REGULATORY_COVERAGE_INCOMPLETE` (HTTP 409). The server records `submitted_by_user_id` from the caller's `X-User-ID`. Acknowledgement by the `ALCOChair` moves the report `SUBMITTED → ACKNOWLEDGED`, its terminal state, under two guards: the `open_breach_count` must be zero, else `ERR_OPEN_BREACHES_REMAIN` (HTTP 409), and the acknowledger's `X-User-ID` must differ from `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The server records `acknowledged_by_user_id`.

The pack is volatile until acknowledged: whenever a run in the period is published, or a breach is created in the period, while the report is `SUBMITTED`, the report auto-reverts from `SUBMITTED` to `DRAFT`, `submitted_by_user_id` is reset, and the aggregates are recomputed. Breach acknowledgements and closures recompute `open_breach_count` but do not themselves revert a submitted report.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code — this covers creating books, positions, assumption sets, scenarios, simulation runs, policy limits, hedge relationships, effectiveness tests, backtest reviews, and ALCO reports. Operations that read, modify, or drive a state transition on an existing resource return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/books` | Create an AlmBook in `DRAFT` status | TreasuryAnalyst |
| GET | `/books/{id}` | Get an AlmBook | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/books/{id}/activate` | Activate a book (requires at least one asset and one liability position) | TreasuryAnalyst |
| POST | `/books/{id}/positions` | Create a Position in a book | TreasuryAnalyst |
| GET | `/books/{id}/positions` | List positions of a book | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/positions/{id}` | Get a Position | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| PATCH | `/positions/{id}` | Update position economics (OCC-guarded on the book version) | TreasuryAnalyst |
| POST | `/positions/{id}/retire` | Retire a position | TreasuryAnalyst |
| POST | `/books/{id}/assumption-sets` | Create an AssumptionSet in `DRAFT` status | TreasuryAnalyst |
| GET | `/books/{id}/assumption-sets` | List assumption sets of a book | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/assumption-sets/{id}` | Get an AssumptionSet | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| PATCH | `/assumption-sets/{id}` | Edit assumption params while `DRAFT` | TreasuryAnalyst |
| POST | `/assumption-sets/{id}/submit` | Submit a set for ALCO approval | TreasuryAnalyst |
| POST | `/assumption-sets/{id}/approve` | Approve a submitted set; supersedes the prior approved set in the domain | ALCOChair |
| POST | `/assumption-sets/{id}/reject` | Reject a submitted set back to `DRAFT` | ALCOChair |
| POST | `/books/{id}/scenarios` | Create a RateScenario in `ACTIVE` status | TreasuryAnalyst |
| GET | `/books/{id}/scenarios` | List scenarios of a book | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/scenarios/{id}` | Get a RateScenario | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/scenarios/{id}/archive` | Archive a scenario; new runs referencing it are rejected | TreasuryAnalyst |
| POST | `/books/{id}/simulation-runs` | Create and synchronously compute a SimulationRun (OCC-guarded) | TreasuryAnalyst |
| GET | `/simulation-runs` | List simulation runs with filters | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/simulation-runs/{id}` | Get a SimulationRun | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/simulation-runs/{id}/publish` | Publish a completed run into the period ALCO pack | TreasuryAnalyst |
| POST | `/books/{id}/policy-limits` | Create a PolicyLimit in `ACTIVE` status | ALCOChair |
| GET | `/books/{id}/policy-limits` | List policy limits of a book | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/policy-limits/{id}` | Get a PolicyLimit | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| PATCH | `/policy-limits/{id}` | Update `threshold_pct` and/or suspend or resume a limit | ALCOChair |
| GET | `/breaches` | List breaches with filters | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/breaches/{id}` | Get a LimitBreach | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/breaches/{id}/acknowledge` | Acknowledge an `OPEN` or `ESCALATED` breach | ALCOChair |
| POST | `/breaches/{id}/remediation-plan` | Attach a remediation plan with a due date | ALCOChair |
| POST | `/breaches/{id}/close` | Close a breach with a resolution note | ALCOChair |
| POST | `/books/{id}/hedges` | Create a HedgeRelationship in `PROPOSED` status | TreasuryAnalyst |
| GET | `/books/{id}/hedges` | List hedges of a book | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/positions/{id}/hedges` | List hedges referencing a position | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/hedges/{id}` | Get a HedgeRelationship | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/hedges/{id}/designate` | Designate a proposed hedge; pins the window and effectiveness method | ALCOChair |
| POST | `/hedges/{id}/activate` | Activate a designated hedge once its window begins | ALCOChair |
| POST | `/hedges/{id}/dedesignate` | Remove hedge accounting designation | ALCOChair |
| POST | `/hedges/{id}/terminate` | Terminate an `ACTIVE` hedge early | ALCOChair |
| POST | `/hedges/{id}/effectiveness-tests` | Record a periodic effectiveness test; `FAIL` auto-dedesignates an `ACTIVE` hedge | ModelRiskValidator |
| GET | `/hedges/{id}/effectiveness-tests` | List effectiveness tests of a hedge | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/books/{id}/backtests` | Create a BacktestReview of an assumption set over an observation window | ModelRiskValidator |
| GET | `/backtests` | List backtest reviews with filters | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/backtests/{id}` | Get a BacktestReview | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/backtests/{id}/close` | Close a review as `CLOSED_ACCEPTED` or `CLOSED_REVISED` | ALCOChair |
| POST | `/books/{id}/alco-reports` | Create the ALCO report for a period in `DRAFT` status | TreasuryAnalyst |
| GET | `/books/{id}/alco-reports` | List ALCO reports of a book | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| GET | `/alco-reports/{id}` | Get an AlcoReport | TreasuryAnalyst, ModelRiskValidator, ALCOChair, Regulator |
| POST | `/alco-reports/{id}/submit` | Submit a `DRAFT` report to ALCO (requires full regulatory coverage) | TreasuryAnalyst |
| POST | `/alco-reports/{id}/acknowledge` | Acknowledge a submitted report (requires zero open breaches) | ALCOChair |
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers the breach escalation sweep | TreasuryAnalyst, ModelRiskValidator, ALCOChair |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DEPOSIT_SEGMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ASSUMPTION_PARAMS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OBSERVED_VALUE_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_BOOK_NOT_ACTIVE` | 409 Conflict |
| `ERR_BOOK_ACTIVATION_INCOMPLETE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_ASSUMPTION_NOT_APPROVED` | 409 Conflict |
| `ERR_ASSUMPTION_UNDER_REVIEW` | 409 Conflict |
| `ERR_SCENARIO_NOT_ACTIVE` | 409 Conflict |
| `ERR_LIMIT_SCOPE_CONFLICT` | 409 Conflict |
| `ERR_REPORT_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_OPEN_BREACHES_REMAIN` | 409 Conflict |
| `ERR_REGULATORY_COVERAGE_INCOMPLETE` | 409 Conflict |
| `ERR_POSITION_RETIRED` | 409 Conflict |
| `ERR_POSITION_HAS_ACTIVE_HEDGE` | 409 Conflict |
| `ERR_HEDGE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DESIGNATION_WINDOW_PAST` | 409 Conflict |
| `ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE` | 409 Conflict |
| `ERR_HEDGE_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_BACKTEST_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_BACKTEST_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BACKTEST_CLOSURE_REQUIRES_REVISION` | 409 Conflict |
