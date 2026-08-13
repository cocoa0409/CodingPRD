# Portfolio Asset Management API — Product Requirements Document

## 1. Introduction

Real estate asset managers run a portfolio on an annual rhythm. Each asset carries an annual business plan with a monthly budget and a capital plan; property managers post actuals against that plan; the asset manager re-forecasts at fixed checkpoints, funds capital projects, monitors debt covenants, and decides whether each asset should be refinanced, held, or sold. This document specifies the Portfolio Asset Management API, the system of record for that full operating cycle — portfolios, assets, business plans, budget lines, actuals, reforecasts, capital projects and funding draws, lease strategies, loans and covenants, valuations, manager scorecards, disposition decisions, and lender reports.

Three commitments shape the design. First, segregation of duties: the operator who proposes a capital project never approves it, the analyst who drafts a valuation never confirms it, and the committee that approves a funding draw never releases the cash. Second, auditability: covenant tests, lender reports, and scorecards are timestamped records whose consequences — breaches, watch-list placements, manager suspensions — propagate automatically and atomically through the resource hierarchy. Third, determinism: every time-derived rule (fiscal-month cadence, reporting lateness, covenant cure windows, trigger arming) evaluates against a server-side logical clock rather than wall-clock time, so a portfolio's history replays identically in any environment.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their role. A request missing either header, carrying a malformed value, or naming an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The declared roles are `PortfolioDirector`, `AssetManager`, `PropertyManager`, `InvestmentCommittee`, `Lender`, and `Analyst`.

- A `PortfolioDirector` is the senior executive: owns portfolio, asset, and manager setup; approves business plans; confirms valuations; accepts reforecasts; releases funding draws; executes disposition decisions; originates loans and covenants; and controls the logical clock. When `X-User-Role` is `PortfolioDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- An `AssetManager` drafts and submits business plans and budget lines, accepts or rejects actuals reports, proposes capital projects and funding draws, drafts lease strategies and reforecasts, opens and advances disposition decisions, drafts and submits lender reports, and reviews and finalizes scorecards. When `X-User-Role` is `AssetManager`, `X-User-ID` is opaque; the server records it on created resources — as `proposed_by_user_id` on a capital project, `requested_by_user_id` on a funding draw, and `created_by_user_id` on a disposition decision — but never compares it to any entity's `id`.
- When `X-User-Role` is `PropertyManager`, `X-User-ID` is the `id` of the acting `PropertyManager` record; ownership checks on any asset-scoped write compare the asset's `property_manager_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`. The server records this identity as `submitted_by_user_id` on each actuals report the manager posts.
- An `InvestmentCommittee` member approves or rejects capital projects and funding draws, and ratifies or shelves disposition decisions. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity.
- A `Lender` waives breached covenants and acknowledges lender reports; `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- An `Analyst` records covenant tests, drafts valuations, and computes lease-rate recommendations; `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Two further names appear in this document but are never valid `X-User-Role` values. `System` is the automation actor credited with cascade transitions (breach propagation, supersede chains, posture recomputation, the sale cascade). `Any` is a documentation alias for the shared read surface: every GET endpoint authorizes all six concrete business roles.

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

All error API responses (4xx status codes) — including requests whose path matches no endpoint or whose method the endpoint does not support, which surface as `ERR_NOT_FOUND` (HTTP 404) — follow this standard envelope format:

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and out-of-range values are clamped into that range rather than rejected. `offset` skips a number of items before returning results, defaults to 0, and is floored at 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; because every creation timestamp reads the logical clock, ties are common and break in favor of the earlier-created record.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more` — the last true exactly when `offset` plus the number of returned items is still below `total_count`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation (when `created_at` and `updated_at` coincide) and increments by one on every mutation of the resource.

One exception exists: the covenant test is an append-only measurement record and carries only `id` and `created_at`. Because a recorded covenant test never changes after creation, `updated_at` and `version` are both absent from it.

Any change to a resource — including a server-side cascade that recomputes derived fields or forces a state transition — refreshes that resource's `updated_at` and increments its `version`, even when the client never addressed the resource directly.

### 2.5. The Logical Clock and the Fiscal Calendar

The server maintains a logical clock. Before any client call, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time; every timestamp the server emits — `api_request_timestamp`, `created_at`, `updated_at`, `submitted_at`, `last_breach_at` — reads this clock. A director-only test-driving capability advances the clock: the request carries `to_iso8601`, which must be strictly after the current logical time — a malformed or non-advancing value is `ERR_INVALID_REQUEST` — and the response reports the new reading as `current_utc`, an ISO 8601 UTC string that omits fractional seconds when the reading lands on a whole second. The capability mutates no entity directly; instead, every time-derived rule — fiscal-month determination, lender-report lateness, covenant cure windows, decision-trigger arming — evaluates against the new clock on subsequent calls.

Each portfolio declares a `fiscal_year_start_month`, an integer from 1 to 12 defaulting to 1, identifying the calendar month in which its fiscal year begins. A business plan's `fiscal_year` label covers twelve consecutive months beginning in that month of that year, and the plan's current fiscal month (1 through 12) at any moment is derived from the logical clock against that window — concretely, (clock year − `fiscal_year`) × 12 + (clock month − `fiscal_year_start_month`) + 1, a figure that evaluates below 1 or above 12 when the clock sits outside the plan's fiscal year. Fiscal-month position governs which months may receive actuals and when a reforecast may be opened, as §3.3 details.

### 2.6. Monetary Precision, Basis Points, and Rounding

All monetary amounts in the API — budgets, actuals, prices, principal balances, valuations — are represented as integer cents. Rates and ratios (interest rates, cap rates, covenant thresholds and measurements, value gains) are represented as integer basis points, where ten thousand basis points equal one hundred percent. Occupancy, collections, and renewal percentages are integers from 0 to 100.

Whenever a computation divides or applies a rate and the result is stored — annualized NOI, implied valuation, variance ratios, covenant measurements, recommended rents, per-category reforecast spreads — the stored integer is rounded half-up to a whole unit. Where a rule instead requires rounding down (the per-month capital spend spread, the monthly schedule cap, elapsed hold years), the relevant section says so explicitly. Rounding is applied at each multiplication or division step before any subsequent clamp or comparison, never once at the end of a chain. The single non-integer figure in the API is a property manager's `composite_score_avg`, which is carried to exactly two decimal places, rounded half-up.

### 2.7. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control on a parent resource. Each requires a non-optional version field in the request body carrying the caller's last observed `version` of the parent; if another writer has advanced the parent's `version` since the client last read it, the request is rejected and the client's stale basis is never written.

- Creating a business plan (`POST /api/business-plans`) requires `expected_asset_version` matching the target asset's current `version`; a mismatch is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412). Plan creation can legitimately supersede the asset's previously approved plan, so a writer whose view of the asset's plan lineage is stale must not proceed.
- Confirming a valuation (`POST /api/valuations/{id}/confirm`) requires `expected_asset_version` matching the asset's current `version`; a mismatch is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412). Another writer may have confirmed a different valuation — superseding the prior one and moving the asset's value — so the confirming writer's basis must be current.
- Accepting a reforecast (`POST /api/reforecasts/{id}/accept`) requires `expected_plan_version` matching the plan's current `version`; a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). The plan's budget lines may have been rewritten by an earlier applied reforecast or by accepted actuals.
- Approving a capital project (`POST /api/capital-projects/{id}/approve`) requires `expected_plan_version` matching the plan's current `version`; a mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). A prior approval may already have drawn down the plan's available capital, leaving the approver's budget basis stale.

Endpoints not listed above take no version field at all.

### 2.8. Cascading State Reconciliation

Many operations mutate more than one resource, and every such cascade commits atomically within the triggering request. Cascades run to depth: a failed covenant test breaches the covenant, moves its loan onto the watch list, and recomputes the portfolio's risk posture in a single step; closing a sale pays off the loan, waives its covenants, closes the asset's plans, cancels those plans' capital projects with capital release, and rejects their pending reforecasts. Each resource touched by a cascade — however deep in the chain — refreshes its `updated_at` and increments its `version`, and derived aggregates on parent resources (plan budget totals and capital buckets, asset value and annualized NOI, portfolio value and posture) are recomputed immediately rather than asynchronously. Conversely, when a parent becomes non-operational, the system resolves dependent child resources and their financial commitments rather than leaving them dangling; the sale pipeline in §3.8 is the fullest expression of this principle.

### 2.9. Validation Pipeline, Lookup Order, and Error Precedence

Incoming writes are validated against a fixed pipeline, and a failure in an earlier tier masks every later tier. When a request path addresses a resource through another resource, the referenced identifiers are validated from left to right, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) before any later lookup or business rule is evaluated; body-referenced resources follow the same existence check. The full pipeline, in priority order:

1. Presence and well-formedness of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Two role-tier checks key off a resolved resource and therefore run immediately after that resource's existence check — ahead of all later tiers and of any further body-reference resolution: the property-manager ownership comparison on asset-scoped writes (evaluated once the scoping asset or plan resolves), and the restriction of emergency capital approval to the director (evaluated once the project resolves).
3. Existence of every path- and body-referenced resource, validated left to right (`ERR_NOT_FOUND`).
4. Optimistic-concurrency checks where §2.7 applies (`ERR_STALE_ASSET_VERSION`, `ERR_STALE_PLAN_VERSION`).
5. State legality: the target must be in a from-state that permits the requested transition, terminal states reject all transitions (`ERR_INVALID_STATE_TRANSITION`), and domain state gates apply (`ERR_PLAN_NOT_APPROVED`, `ERR_PROJECT_NOT_FUNDABLE`, `ERR_COVENANT_NOT_TESTABLE`, `ERR_LOAN_NOT_REPORTABLE`, `ERR_ASSET_NOT_OPERATING`, `ERR_ASSET_NOT_SELLABLE`, `ERR_PROJECT_NEVER_FUNDED`, `ERR_COVENANT_NOT_WAIVABLE`).
6. Segregation of duties on capital approval and disposition ratification (`ERR_SELF_APPROVAL_FORBIDDEN`).
7. Manager standing and portfolio posture (`ERR_MANAGER_SUSPENDED`, `ERR_PORTFOLIO_RESTRICTED`).
8. Referential coherence of body references (`ERR_REFERENTIAL_INTEGRITY`).
9. Shape and uniqueness: malformed bodies, bad enumerations, non-positive amounts, bad period labels, inverted month ranges (`ERR_INVALID_REQUEST`), and the uniqueness rules (`ERR_DUPLICATE_PLAN`, `ERR_DUPLICATE_ACTUALS`, `ERR_DUPLICATE_COVENANT_TEST`, `ERR_DUPLICATE_SCORECARD`, `ERR_LOAN_EXISTS`, `ERR_DUPLICATE_BUDGET_LINE`, `ERR_REFORECAST_CATEGORIES_INCOMPLETE`).
10. Clock-derived temporal rules (`ERR_FUTURE_PERIOD`, `ERR_VALUATION_REGRESSIVE`, `ERR_STALE_VALUATION`, `ERR_REFORECAST_CADENCE`, `ERR_REFORECAST_LIMIT`, `ERR_LENDER_REPORT_GAP`).
11. Money checks, with pinned internal order — capital availability before schedule capacity before draw authorization before the reforecast floor (`ERR_CAPITAL_BUDGET_EXCEEDED`, `ERR_CAPITAL_SCHEDULE_OVER_COMMITTED`, `ERR_DRAW_EXCEEDS_AUTHORIZATION`, `ERR_REFORECAST_BELOW_ACTUALS`).
12. Plan completeness at submission (`ERR_PLAN_LINES_INCOMPLETE`).

Two orderings inside this pipeline deserve emphasis because they are observable. Within tier 7, the manager-standing check precedes the portfolio-posture check, so a plan approval against a suspended manager surfaces `ERR_MANAGER_SUSPENDED` even when the portfolio is also restricted. Within tier 11, a capital approval that would both exceed available capital and over-commit the schedule surfaces `ERR_CAPITAL_BUDGET_EXCEEDED`, never the schedule error.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Portfolio: Portfolios, Managers, and Assets

A `PortfolioDirector` begins by creating a portfolio with a display `name`, an optional `base_currency` (an ISO currency code defaulting to USD), and an optional `fiscal_year_start_month`. A new portfolio starts `ACTIVE` with `risk_posture` set to `NORMAL` and `total_value_cents` at zero. The `status` of a portfolio moves only once in its life: archiving transitions it from `ACTIVE` to `ARCHIVED`, and is permitted only when every asset of the portfolio has reached `SOLD` — while any asset remains in another status the archive is refused with `ERR_PORTFOLIO_NOT_EMPTY`.

Property management firms are onboarded with a `firm_name` and a primary `contact_email`. A new manager starts `ACTIVE`, with `probation_streak` at zero and `composite_score_avg` null until finalized scorecards exist. The director may suspend a manager, moving `ACTIVE` to `SUSPENDED`; reinstate one, moving `SUSPENDED` back to `ACTIVE` and resetting `probation_streak` to zero; or terminate one by passing `terminate` set to true on the suspend action, moving `ACTIVE` directly to `TERMINATED`. Termination is refused with `ERR_MANAGER_IN_USE` while any asset in `OWNED`, `LISTED_FOR_SALE`, or `UNDER_CONTRACT` still references the manager. Suspension never touches the portfolio's `risk_posture`; its teeth show up at plan-approval time (§3.2) and its causes in the scorecard cascade (§3.7).

With a portfolio and a manager in place, the director creates an asset by supplying `portfolio_id`, the managing firm's `property_manager_id`, a `name`, a street `address`, an `asset_class` of `OFFICE`, `RETAIL`, `INDUSTRIAL`, or `MULTIFAMILY`, a `net_rentable_sqft` greater than zero, an `acquisition_price_cents` greater than zero, an `acquisition_date` that must not fall after the current clock date (a future date is rejected with `ERR_FUTURE_PERIOD`), and a `hold_period_years` greater than zero that anchors the disposition triggers of §3.8. A new asset is `OWNED`; its three derived fields — `current_value_cents`, `current_annualized_noi_cents`, and `current_plan_id` — remain null until a valuation is confirmed, actuals are accepted, and a plan is approved.

### 3.2. The Annual Business Plan and Its Budget Lines

An `AssetManager` opens the annual cycle by creating a plan for an asset, supplying `asset_id`, the `fiscal_year` label, and the concurrency field `expected_asset_version` described in §2.7. The plan is born `DRAFT`. Two guards protect the plan lineage. When a plan in `DRAFT` or `SUBMITTED` already exists for the same asset and fiscal year, creation fails with `ERR_DUPLICATE_PLAN`. When an `APPROVED` plan exists for the same asset and fiscal year, the new draft supersedes it — but only when that approved plan carries no capital project in `APPROVED` or `IN_PROGRESS`; otherwise the create call is refused with `ERR_PLAN_HAS_ACTIVE_PROJECTS`. A successful supersede moves the old plan to `SUPERSEDED`, rejects its reforecasts still sitting in `DRAFT` or `SUBMITTED`, and recomputes the asset's `current_plan_id` — null until the new plan is itself approved — bumping the asset's `version` by one. When no `APPROVED` plan exists for the same asset and fiscal year, creation supersedes nothing and touches no other resource: the asset's `current_plan_id` and `version` are left unchanged until the new plan is itself approved.

While a plan is `DRAFT` — or `REJECTED`, inside the revision loop — the asset manager bulk-creates its budget lines; a plan in any other state rejects the batch with `ERR_INVALID_STATE_TRANSITION`. The request carries `plan_id` and a `lines` array — non-empty, else `ERR_INVALID_REQUEST` — whose entries each name a `category`, a `month_index` from 1 to 12, and a `budget_amount_cents` of zero or more — revenue and expense budgets are both entered as positive amounts. A successful batch returns the created lines as an array. The referenced plan must resolve and cohere with the batch (`ERR_REFERENTIAL_INTEGRITY`). The ten categories are `RENT_REVENUE`, `PARKING_REVENUE`, `OTHER_REVENUE`, `CAM_EXPENSE`, `TAX_EXPENSE`, `INSURANCE_EXPENSE`, `UTILITIES_EXPENSE`, `MANAGEMENT_FEE_EXPENSE`, `OTHER_OPEX`, and `CAPITAL`. Creation is atomic: any failure rejects the whole request. Uniqueness is enforced per plan, category, and month — a second line for the same triple is `ERR_DUPLICATE_BUDGET_LINE`. Each accepted batch recomputes the plan's derived totals and bumps the plan's `version`: `total_revenue_budget_cents` sums the line budgets across the three revenue categories, `total_opex_budget_cents` sums them across the expense categories, `total_capital_budget_cents` sums the `CAPITAL` lines, and `budgeted_noi_cents` is the revenue total minus the operating-expense total. Every line is born with `actual_amount_cents` zero, `has_actual` false, and its variance fields null.

Submitting a plan is the asset manager's hand-off to the director. From `DRAFT`, submission requires the asset to be `OWNED` (`ERR_ASSET_NOT_OPERATING`, the earlier pipeline tier) and requires every one of the ten categories to hold at least one line (`ERR_PLAN_LINES_INCOMPLETE`). Approval by a `PortfolioDirector` then faces two gates, evaluated with manager standing first: the asset's property manager must be `ACTIVE` — a `SUSPENDED` or `TERMINATED` manager blocks approval with `ERR_MANAGER_SUSPENDED` — and the portfolio's `risk_posture` must not be `RESTRICTED` (`ERR_PORTFOLIO_RESTRICTED`). Approval moves the plan from `SUBMITTED` to `APPROVED`, points the asset's `current_plan_id` at it, and performs the year-rollover handoff: any still-`APPROVED` plan of the same asset for a different fiscal year transitions to `CLOSED`, which cancels that plan's capital projects in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` with their reserved capital released, and rejects its reforecasts in `DRAFT` or `SUBMITTED`. The director may instead reject a submitted plan, optionally with a `reason`, moving it to `REJECTED`; its lines may then be edited through fresh bulk creation and the plan resubmitted, with category completeness checked again; the asset's `OWNED`-state gate applies only to a first submission from `DRAFT`, not to a resubmission from `REJECTED`. The plan lifecycle is therefore a genuine revision loop — `DRAFT` to `SUBMITTED` to `REJECTED` and back to `SUBMITTED` — and it ends at one of the two terminal states, `SUPERSEDED` or `CLOSED`; an asset sale (§3.8) closes plans in `DRAFT`, `SUBMITTED`, `APPROVED`, or `REJECTED` alike.

Two further notes belong to the plan's working life. The plan's `reforecast_count` starts at zero and counts applied reforecasts against a hard cap of three (§3.3). And the plan carries three capital-ledger fields — `available_capital_cents`, `reserved_capital_cents`, and `drawn_capital_cents` — whose arithmetic is owned by the capital workflow in §3.4. A variance-summary read on the plan returns its `plan_id`, a per-category rollup in `categories` — covering all ten categories in fixed order, each carrying its summed `budget_amount_cents`, its summed `actual_amount_cents` over posted lines, a `variance_cents` summed over posted lines (null when none are posted), a category-level `favorable` flag under the line sign rule (likewise null when none are posted), and the category's `lines` — and three headline figures: `total_budget_noi_cents`, the static full-year budget NOI computed as budgeted revenue minus budgeted operating expense with no regard to actuals; `ytd_actual_noi_cents`, the signed sum of posted actuals (revenue positive, expense negative) over non-`CAPITAL` lines whose `has_actual` is true (`CAPITAL` lines never participate, as §3.3 pins for the annualization); and `annualized_actual_noi_cents`, the trailing-actuals annualization of §3.3. Within the rollup, a line is flagged favorable when its `variance_cents` is zero or positive for a revenue category, or zero or negative for an expense category.

### 3.3. Posting Actuals, Variance, and Mid-Year Re-Forecasts

Each fiscal month, the property manager posts an actuals report against the plan of an asset it manages — the ownership comparison of §2.1 applies here as everywhere — supplying `plan_id`, the reported `month_index`, and a `lines` array whose entries pair a `budget_line_id` with an `actual_amount_cents`. The array must be non-empty, each amount an integer of zero or more, and no `budget_line_id` may repeat within one report (`ERR_INVALID_REQUEST`). The report is created directly in `SUBMITTED` status, and the server stamps `submitted_by_user_id` with the caller's `X-User-ID`. Four guards shape creation. The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`). Every referenced line must belong to that plan and carry a `month_index` equal to the report's month (`ERR_REFERENTIAL_INTEGRITY`). At most one report per plan and month may ever reach `ACCEPTED`, and no referenced line may already have `has_actual` set — both surface as `ERR_DUPLICATE_ACTUALS`. Finally, the reported month may not run ahead of the plan's current fiscal month under the logical clock (`ERR_FUTURE_PERIOD`).

Acceptance by an `AssetManager` moves the report from `SUBMITTED` to `ACCEPTED` — terminal — and posts each reported amount onto its budget line: `actual_amount_cents` is set, `has_actual` flips to true, and the line's variance is computed — `variance_cents` is the posted actual minus the budget, and `variance_bps` scales that difference by ten thousand against the budget, rounded half-up to a whole basis point. Two edge cases are pinned: when the budget is zero and the actual is also zero, `variance_bps` is 0; when the budget is zero and the actual is positive, `variance_bps` is exactly 1000000 — a pinned cap of ten-thousand percent, never infinity. Each touched line bumps its own `version`. The plan's `ytd_actual_noi_cents` is then recomputed, the asset's `current_annualized_noi_cents` follows it, and the plan's `version` bumps. Rejection by the asset manager, with an optional `reason`, moves the report to `REJECTED` and posts nothing.

Annualized NOI comes in two variants, and readers must keep them apart. The TRAILING_ACTUALS variant — used by covenant tests, internal-cap valuations, lender reports, and the asset's `current_annualized_noi_cents` — looks only at the asset's `APPROVED` plan. Let M be the number of distinct fiscal months, from 1 to 12, on which that plan holds at least one non-`CAPITAL` line with `has_actual` true; when M is zero the figure is null and every caller treats that as "no evidence". Otherwise the year-to-date NOI is summed over posted lines with revenue categories positive and expense categories negative (`CAPITAL` lines never participate), and the annualized figure is that year-to-date sum times twelve, divided by M, rounded half-up to a whole cent. The BUDGET_BASELINE variant is the plan's static full-year budget NOI — `total_revenue_budget_cents` minus `total_opex_budget_cents` — and ignores actuals entirely; identical inputs generally produce a different value under the two variants.

Three times a year at most, the plan may be re-forecast, and only at fixed checkpoints: creation is permitted only when the plan's current fiscal month is the fourth, seventh, or tenth (`ERR_REFORECAST_CADENCE`), and only while `reforecast_count` remains below three (`ERR_REFORECAST_LIMIT`). The asset manager drafts the reforecast with `plan_id` and a `lines` array whose entries each pair a `category` with a `revised_annual_amount_cents`; the array must be non-empty (`ERR_INVALID_REQUEST`), and the entries must cover each of the nine non-`CAPITAL` categories exactly once — an unrecognized category is `ERR_INVALID_REQUEST`, while a `CAPITAL` entry, a repeated category, or incomplete coverage is `ERR_REFORECAST_CATEGORIES_INCOMPLETE`. The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`). At creation the server assigns the `label` — the letter R followed by the count of reforecasts ever created on the plan plus one, so `R1`, `R2`, `R3`, and on, with rejected drafts still consuming their label in the sequence — and stamps `effective_from_month` with the plan's current fiscal month, which is therefore always one of 4, 7, or 10. The draft sits in `DRAFT` until the asset manager submits it, moving it to `SUBMITTED`.

Acceptance by a `PortfolioDirector` carries `expected_plan_version` per §2.7 (a stale basis is `ERR_STALE_PLAN_VERSION`) and again requires the plan to be `APPROVED` (`ERR_PLAN_NOT_APPROVED`). On acceptance the reforecast rewrites the remaining months of each category. For a category whose revised annual amount is R: take the year-to-date posted actuals on that category's lines in months before `effective_from_month`, add the budget still sitting on that category's elapsed-but-unposted lines in those same months, and subtract both from R; the result is the remaining amount, which must not be negative (`ERR_REFORECAST_BELOW_ACTUALS`). Divide the remaining amount by the count of months from `effective_from_month` through 12, rounded down to a whole cent, and write that figure into the category's line for every remaining month except the twelfth; month 12 absorbs the remainder, receiving the remaining amount minus the per-month figure times the count of earlier remaining months. Rounding order is pinned — the per-month figure is floored first and the entire remainder lands in month 12 — so that after the apply, each reforecasted category's twelve-month column (posted actual where a line has one, budget otherwise) sums to R exactly. Lines are created where none exist for a category and month, and overwritten where they do; created lines append after the originals in the plan's line listing, while elapsed months before `effective_from_month` are never touched. The plan's `total_revenue_budget_cents`, `total_opex_budget_cents`, and `budgeted_noi_cents` are then recomputed, `reforecast_count` increments by one, and the plan's `version` bumps. A `SUBMITTED` reforecast may be rejected by the director with an optional `reason`, and a plan supersede or asset sale cascades both `DRAFT` and `SUBMITTED` reforecasts to `REJECTED`; `APPLIED` is terminal.

### 3.4. Capital Projects and Funding Draws

An asset manager proposes a capital project by supplying `asset_id`, `plan_id`, a `name`, a `requested_amount_cents` greater than zero, a `sched_start_month` and `sched_end_month` (each from 1 to 12, the start no later than the end — an inverted range is `ERR_INVALID_REQUEST`), and an optional `is_emergency` flag defaulting to false. The named plan must belong to the same asset as the project (`ERR_REFERENTIAL_INTEGRITY`), and by approval time it must be the asset's approved plan. The project is born `PROPOSED` and stamps `proposed_by_user_id` with the creator's identity, the segregation-of-duties anchor for everything that follows. For scheduling purposes the project's approved spend spreads evenly across its calendar: with the span defined as end month minus start month plus one, `monthly_spend_cents` is the approved amount divided by the span, rounded down to a whole cent, and `final_month_spend_cents` is the approved amount minus the monthly figure times (span minus one) — the rounding remainder lands entirely in `sched_end_month`.

Every plan runs a three-bucket capital ledger. `reserved_capital_cents` sums, over the plan's projects in `APPROVED` or `IN_PROGRESS`, each project's `approved_amount_cents` minus its `drawn_cents`. `drawn_capital_cents` sums `drawn_cents` over the plan's projects in `APPROVED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`. `available_capital_cents` is then `total_capital_budget_cents` minus reserved minus drawn, and the invariant that the total capital budget equals available plus reserved plus drawn holds at all times.

Approval belongs to the `InvestmentCommittee` — shared with the director, and for emergency projects restricted to the director alone — and its checks run in a fixed, observable order. Caller role first: an emergency project approved by anyone but a `PortfolioDirector` is `ERR_FORBIDDEN_FOR_ROLE`. Next the concurrency field `expected_plan_version` is compared to the plan's current `version` (`ERR_STALE_PLAN_VERSION`). The plan must be `APPROVED` (`ERR_PLAN_NOT_APPROVED`). Segregation of duties follows: the approver's `X-User-ID` must differ from the project's `proposed_by_user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`). Portfolio posture comes next: a `RESTRICTED` portfolio blocks approval unless the project is an emergency (`ERR_PORTFOLIO_RESTRICTED`). Only then do the two fiscal checks run — availability before schedule — and emergency projects skip both, which is the only way `available_capital_cents` may go negative. The availability check requires `requested_amount_cents` not to exceed the plan's `available_capital_cents`, with equality permitted: a full draw-down to zero is valid, and anything more is `ERR_CAPITAL_BUDGET_EXCEEDED`. The schedule check caps each month's committed spend at one twelfth of the plan's `total_capital_budget_cents`, rounded down to a whole cent: for every fiscal month inside the project's closed schedule interval, the spend of the plan's other `APPROVED` or `IN_PROGRESS` projects whose intervals also contain that month, plus this project's own spend for the month, must not exceed the cap, or approval fails with `ERR_CAPITAL_SCHEDULE_OVER_COMMITTED`. Intervals are closed at both ends, so a project ending in a given month collides with another starting in that same month. A successful approval sets `approved_amount_cents` equal to `requested_amount_cents`, reserves the amount against the plan's ledger, and bumps the plan's `version` by one — the concurrency-observable signal to other would-be approvers. The committee (or director) may instead reject a `PROPOSED` project outright, optionally with a `reason`, moving it to `REJECTED`.

An approved project is started by the asset manager, moving `APPROVED` to `IN_PROGRESS`. Completion — also by the asset manager — requires that something was actually drawn: `drawn_cents` must be greater than zero, else `ERR_PROJECT_NEVER_FUNDED`. Completing returns the unused authorization, the approved amount minus what was drawn, to the plan's available capital and bumps the plan's `version`. Cancellation is available from either `APPROVED` or `IN_PROGRESS`, at the asset manager's hand or by cascade when the asset is sold: it releases the same unused authorization back to the plan, leaves whatever was drawn standing in the plan's drawn bucket as sunk cost, rejects any funding draws still `REQUESTED` or `APPROVED`, and bumps the plan's `version`. `COMPLETED`, `CANCELLED`, and `REJECTED` are all terminal.

Funding draws are the cash-motion mechanism against an approved authorization, deliberately split across three roles. The asset manager requests a draw with `project_id` and an `amount_cents` greater than zero, against a project that is `APPROVED` or `IN_PROGRESS` — anything else is `ERR_PROJECT_NOT_FUNDABLE`; the draw is born `REQUESTED` and stamps `requested_by_user_id`. The committee approves a requested draw — only while the project remains `APPROVED` or `IN_PROGRESS`, else `ERR_PROJECT_NOT_FUNDABLE` — under a cumulative check: the project's `drawn_cents` plus the new `amount_cents` must not exceed `approved_amount_cents`, with equality allowed, and any excess is `ERR_DRAW_EXCEEDS_AUTHORIZATION`. Money moves only when the director releases an approved draw: the project's `drawn_cents` increases by the draw amount, the project's `version` bumps, and the plan's drawn and available buckets are recomputed with a further plan `version` bump. The committee may reject a `REQUESTED` draw; a project cancellation cascades draws in `REQUESTED` or `APPROVED` to `REJECTED`, while `RELEASED` draws are never reversed.

### 3.5. Valuations and Leasing Strategy

An `Analyst` drafts a valuation by supplying `asset_id`, an `effective_date` that must not fall after the current clock date (`ERR_FUTURE_PERIOD`), and a `method` of `EXTERNAL_APPRAISAL` or `INTERNAL_CAP`. The two methods take disjoint inputs. `appraised_value_cents` is required when the method is `EXTERNAL_APPRAISAL` and forbidden otherwise; `cap_rate_bps` is required when the method is `INTERNAL_CAP` and forbidden otherwise — a missing conditional field, or a forbidden one supplied anyway, is `ERR_INVALID_REQUEST`. An external appraisal takes the appraiser's figure directly as `implied_value_cents`, ignores NOI, and leaves `noi_used_cents` null. An internal capitalization snapshots the asset's `current_annualized_noi_cents` — the TRAILING_ACTUALS figure of §3.3 — into `noi_used_cents` at creation, and when no such figure exists creation fails with `ERR_VALUATION_NO_NOI_EVIDENCE`; the implied value is then that NOI times ten thousand, divided by the cap rate in basis points, rounded half-up to a whole cent. Drafts sit in `DRAFT`, and the same asset state generally yields a different implied value under the two methods.

Confirmation belongs to the director and is concurrency-guarded per §2.7: the request carries `expected_asset_version`, and a mismatch with the asset's current `version` is `ERR_STALE_ASSET_VERSION`. The draft's `effective_date` must also be strictly later than the effective date of the asset's currently confirmed valuation, if one exists — a regressive or equal date is `ERR_VALUATION_REGRESSIVE`. Because effective dates therefore strictly increase along an asset's confirmation chain, no two confirmed valuations can tie on date. Confirming moves the draft to `CONFIRMED`, supersedes whatever valuation was previously `CONFIRMED` for that asset (that valuation goes to `SUPERSEDED`, terminal), sets the asset's `current_value_cents` to the newly implied value, bumps the asset's `version` by one, and recomputes the portfolio's `total_value_cents`.

Leasing strategy follows a draft-recommend-ratify rhythm. A strategy is drafted for a `space_type` of `OFFICE_SUITE`, `RETAIL_BAY`, `INDUSTRIAL_BAY`, or `APARTMENT_UNIT` — by the asset manager, or by the property manager for an asset it manages — supplying `asset_id`, `space_type`, the `current_occupancy_pct` of that space type (0 to 100), a `proposed_asking_rate_psf_cents`, and a `market_comp_rate_psf_cents`, both rates positive and expressed per square foot per year. The draft sits in `DRAFT` with `recommended_rate_psf_cents` null. The analyst's recommendation step then prices the strategy. The market comparable is adjusted by occupancy tier: below 70 percent occupancy, the comparable is marked down 1000 basis points; at 70 up to but not including 85 percent, down 500 basis points; at 85 up to but not including 95 percent, it is left unadjusted; and at 95 through 100 percent inclusive, it is marked up 500 basis points — the adjusted figure is the comparable times (10000 plus the tier adjustment) divided by ten thousand, rounded half-up. That adjusted market figure is then clamped between a floor of 95 percent of the proposed asking rate and a ceiling of 110 percent of the market comparable, each bound computed with half-up rounding to a whole cent: the recommended rate is the adjusted figure raised to the floor when it falls short, or capped at the ceiling when it overshoots. The result is stored as `recommended_rate_psf_cents` and the strategy moves to `RECOMMENDED`.

Ratification is the director's call and requires the asset to be `OWNED` or `LISTED_FOR_SALE` (`ERR_ASSET_NOT_OPERATING`). Ratifying a strategy supersedes whatever strategy was previously `RATIFIED` for the same asset and space type — the older one moves to `SUPERSEDED` — so exactly one ratified strategy exists per space type at any time. The director may instead reject a `RECOMMENDED` strategy with an optional `reason`; `REJECTED` and `SUPERSEDED` are terminal.

### 3.6. Debt: Loans, Covenants, and Lender Reporting

A `PortfolioDirector` originates an interest-only loan on an asset with `asset_id`, `lender_name`, a `principal_balance_cents` and an `annual_interest_rate_bps` both greater than zero, an `origination_date`, and a `maturity_date` strictly after origination — an inverted pair is `ERR_INVALID_REQUEST`. An asset carries at most one live loan: while any loan in `CURRENT`, `WATCH`, or `DEFAULT` exists for the asset, another origination is refused with `ERR_LOAN_EXISTS`. The loan is born `CURRENT`, and its principal is static for life; annual debt service — the denominator of the coverage ratios below — is the principal times the note rate in basis points divided by ten thousand, rounded half-up to a whole cent.

Covenants attach to a loan with `loan_id`, a `covenant_type` of `MIN_DSCR`, `MAX_LTV`, or `MIN_DEBT_YIELD`, a positive `threshold_bps`, a `test_frequency` of `QUARTERLY` or `ANNUAL` recording the cadence the lender expects, and an optional `cure_period_days` — positive, defaulting to 30 — that bounds how long a breach may run before escalation. A covenant is born `ACTIVE` with `last_breach_at` null. For each period, an `Analyst` records a test supplying `covenant_id` and a `period_label` in the format YYYY-Qn with n from 1 to 4 (a malformed label is `ERR_INVALID_REQUEST`). Only one test may exist per covenant and period (`ERR_DUPLICATE_COVENANT_TEST`), and a test against a `WAIVED` covenant — or against a loan in `DEFAULT`, `REFINANCED`, or `PAID_OFF` — is refused with `ERR_COVENANT_NOT_TESTABLE`. The measurement is computed once, at creation, and is immutable thereafter: the record carries `measured_value_bps`, the `annualized_noi_cents_used`, and a `result` of `PASS` or `FAIL`, and as an append-only record it has no `updated_at` or `version` (§2.4).

The three covenant types measure different ratios. For `MIN_DSCR`, the measured value is the trailing-actuals annualized NOI times ten thousand divided by annual debt service, rounded half-up to a whole basis point, and the test passes when the measured value is at least `threshold_bps`. `MIN_DEBT_YIELD` substitutes the principal balance for debt service — NOI times ten thousand divided by principal, rounded half-up — and likewise passes at or above threshold. Both NOI-based tests refuse to run before any actuals exist: when the trailing-actuals NOI is null, creation fails with `ERR_NO_NOI_EVIDENCE`. `MAX_LTV` works off value rather than income: it reads the asset's latest confirmed valuation (latest by `effective_date`, which strictly increases per §3.5, so no tie is possible), measures the principal times ten thousand divided by that valuation's implied value with half-up rounding, and passes when the measured value is at most `threshold_bps`. An LTV test with no confirmed valuation at all, or whose latest confirmed valuation's `effective_date` is more than 270 days before the clock date, fails closed with `ERR_STALE_VALUATION` and the test is not recorded; LTV tests record `annualized_noi_cents_used` as null.

Consequences propagate upward the moment a test is recorded. A `FAIL` on an `ACTIVE` covenant breaches it — `ACTIVE` to `IN_BREACH` — stamps `last_breach_at` with the current clock time, moves the loan from `CURRENT` to `WATCH`, and recomputes the portfolio's `risk_posture`. A `PASS` recorded against an `IN_BREACH` covenant cures it — back to `ACTIVE`, with `last_breach_at` cleared to null — and when no other covenant of the same loan remains in breach, the loan returns from `WATCH` to `CURRENT`, again recomputing posture. The dark path runs through the cure window: when a `FAIL` is recorded while that same covenant is already `IN_BREACH` and the logical clock has passed `last_breach_at` plus `cure_period_days`, the loan escalates from `WATCH` to `DEFAULT`, terminal, and posture recomputes. A `Lender` may instead forgive a breach: waiving requires the covenant to be `IN_BREACH` (`ERR_COVENANT_NOT_WAIVABLE`), moves it to `WAIVED` (terminal) and clears `last_breach_at` to null — every cascade waive does the same — and when no other covenant of the loan remains in breach and the loan sits in `WATCH`, returns the loan to `CURRENT` with a posture recompute. Two further loan endings belong to other workflows and are specified there: execution of a refinance decision moves a `CURRENT` or `WATCH` loan to `REFINANCED` (§3.8), and closing a sale moves a `CURRENT` or `WATCH` loan to `PAID_OFF` (§3.8); both waive every covenant of the loan still in `ACTIVE` or `IN_BREACH` and recompute posture.

Lender reporting runs on the calendar quarter. An asset manager drafts a report with `loan_id` and a `period_label`; the server derives `quarter_end_date` from the label — Q1 ends March 31, Q2 June 30, Q3 September 30, Q4 December 31 of the label year — and sets `due_date` 45 days after quarter end. The labeled quarter must already have ended under the logical clock: a quarter-end later than the clock date is `ERR_FUTURE_PERIOD`. Quarters must also be contiguous — unless the report is the loan's first, the previous calendar quarter's report must exist in `SUBMITTED` or `ACKNOWLEDGED`, and a duplicate `period_label` for the same loan is likewise refused; both surface as `ERR_LENDER_REPORT_GAP`. The draft sits in `DRAFT` with `submitted_at` null.

Submission by the asset manager requires the loan to be `CURRENT` or `WATCH` (`ERR_LOAN_NOT_REPORTABLE`) and freezes the evidence: `submitted_at` is stamped from the clock, `is_late` is computed as the submission date falling after `due_date`, and three snapshots are stored — `noi_ttm_cents`, the trailing-actuals annualized NOI, or null when no actuals exist (submission does not require NOI evidence); `dscr_bps`, the NOI times ten thousand divided by annual debt service, rounded half-up, or null when the NOI is null; and `ltv_bps`, the principal times ten thousand divided by the asset's `current_value_cents`, rounded half-up, or null when no confirmed valuation exists. Lateness has teeth: when a report is late and the loan sits in `CURRENT`, the loan cascades to `WATCH` and the portfolio's posture is recomputed. The lender's acknowledgment — the only remaining step — moves the report from `SUBMITTED` to `ACKNOWLEDGED`, terminal.

### 3.7. Property Manager Oversight: Scorecards and Standing

Quarterly oversight starts with the property manager, who submits a scorecard for an asset it manages — the ownership comparison of §2.1 applies, so a manager acting for an asset whose `property_manager_id` differs from its own identity is refused with `ERR_FORBIDDEN_FOR_ROLE`. The submission supplies `asset_id`, a `period_label` for the calendar quarter, and four operating metrics: `occupancy_pct`, `collections_pct`, and `renewal_rate_pct`, each an integer from 0 to 100, plus `expense_variance_bps`, a signed basis-point measure of actual-versus-budget operating expense. Only one scorecard may exist per asset and period in any status (`ERR_DUPLICATE_SCORECARD`). At creation the server copies `property_manager_id` from the asset, computes the composite score and rating, and sets the scorecard's status to `SUBMITTED`.

The composite weighs the four metrics. Occupancy and collections contribute their percentage points directly. The expense score starts at 100 and loses one point per full fifty basis points of absolute expense variance — the count of complete fifty-basis-point steps in the variance's magnitude — never falling below zero. Renewal contributes its percentage points. The `composite_score` is then thirty times occupancy plus thirty times collections plus twenty-five times the expense score plus fifteen times renewal, divided by one hundred, rounded half-up to a whole number between 0 and 100. The `rating` follows fixed thresholds: a composite of 85 or more earns `EXCELLENT`; 70 through 84 earns `SATISFACTORY`; 55 through 69 earns `WATCH`; below 55 lands on `PROBATION`.

Review and finalization belong to the asset manager. Marking a scorecard reviewed moves `SUBMITTED` to `REVIEWED`; finalizing moves `REVIEWED` to `FINALIZED`, terminal, and that is where consequences land. A finalized `PROBATION` rating increments the manager's `probation_streak` by one; any other rating resets the streak to zero. When the increment drives the streak to two — a second consecutive probation quarter — the manager cascades from `ACTIVE` to `SUSPENDED`, with the plan-approval consequences of §3.2 (the portfolio's `risk_posture` is deliberately not affected). Finalization also recomputes the manager's `composite_score_avg`: the mean of `composite_score` over the four most recently finalized scorecards (ranked by finalization time) across all assets the firm manages — fewer when fewer exist — rounded half-up to two decimal places, and null while no finalized scorecard exists.

### 3.8. Disposition Decisions and the Sale Pipeline

An asset manager opens a disposition decision for an asset by naming `asset_id` and a `trigger_type` of `REFINANCE`, `HOLD`, or `SELL`. Creation freezes a full evidence snapshot and two signal flags, all computed at that moment. `dscr_bps_snapshot` is the measured value of the most recently created covenant test on a `MIN_DSCR` covenant of the asset's live loan, and null when no live loan or no such test exists. `ltv_bps_snapshot` is the live loan's principal times ten thousand divided by the asset's `current_value_cents`, rounded half-up, and null when there is no live loan or no confirmed valuation. `hold_years_elapsed` counts whole years since acquisition: the month count between `acquisition_date` and the clock date — twelve times the year difference plus the month-number difference, less one when the clock's day-of-month precedes the acquisition's day-of-month — divided by twelve and rounded down. `value_gain_bps` measures appreciation as the current value minus `acquisition_price_cents`, scaled by ten thousand against the acquisition price and rounded half-up, and is null without a confirmed valuation.

The two signals arm the gates. `refinance_signal` is true only when all three conditions hold: the DSCR snapshot is present and at least 14000 basis points; the LTV snapshot is present and at most 6000 basis points; and no more than eighteen whole months remain between the clock date and the loan's `maturity_date`, measured with the same whole-month counting rule. `sell_signal` is true when either the elapsed hold reaches the asset's `hold_period_years` or the value gain is present and reaches 2500 basis points. The trigger type must be armed at creation: a `SELL` decision requires `sell_signal` true, a `REFINANCE` decision requires `refinance_signal` true, and `HOLD` is always permitted — an unarmed `SELL` or `REFINANCE` is rejected with `ERR_DECISION_TRIGGER_NOT_ARMED`. The decision is born in `SCREENING` and stamps `created_by_user_id`, the segregation anchor for ratification.

From `SCREENING`, the asset manager advances the decision to `COMMITTEE_REVIEW`. The `InvestmentCommittee` then ratifies it — with segregation of duties enforced: the ratifier's `X-User-ID` must differ from `created_by_user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`) — moving it to `RATIFIED`, or shelves it, optionally with a `reason`; shelving is available from either `COMMITTEE_REVIEW` or `RATIFIED` and lands in `SHELVED`, terminal.

Execution belongs to the director, applies only to a `RATIFIED` decision, and branches on the trigger type. Executing `SELL` requires the asset to be `OWNED` (`ERR_ASSET_NOT_SELLABLE`) and moves the asset to `LISTED_FOR_SALE`. Executing `REFINANCE` requires the payload to carry `new_loan` with its five terms — `principal_balance_cents`, `annual_interest_rate_bps`, `origination_date`, `maturity_date`, and `lender_name` — with a missing payload rejected as `ERR_INVALID_REQUEST`; the existing loan in `CURRENT` or `WATCH` moves to `REFINANCED`, every covenant of it still in `ACTIVE` or `IN_BREACH` is waived, a brand-new loan is created on the asset in `CURRENT`, and the portfolio's posture is recomputed. Executing `HOLD` requires `extension_years` of at least one in the payload and adds that many years to the asset's `hold_period_years`. `EXECUTED` is terminal.

The sale itself runs as a three-action pipeline under the director's hand, each action naming the intended step in `action`. The `CONTRACT` action moves a `LISTED_FOR_SALE` asset to `UNDER_CONTRACT` and requires `sale_agreed_price_cents`; it is permitted only when a ratified-or-executed `SELL` decision exists for the asset, and otherwise fails with `ERR_ASSET_NOT_SELLABLE`. The `CLOSE` action moves an `UNDER_CONTRACT` asset to `SOLD` — terminal — with `final_sale_price_cents` required; the closing sets the asset's `current_value_cents` to the final price, clears its `current_plan_id` to null, and fires the deepest cascade in the system. Both prices are recorded on the asset itself — `sale_agreed_price_cents` and `final_sale_price_cents` sit null until their respective actions set them. The asset's loan in `CURRENT` or `WATCH` moves to `PAID_OFF`, and every covenant of that loan still in `ACTIVE` or `IN_BREACH` is waived. Every business plan of the asset in `DRAFT`, `SUBMITTED`, `APPROVED`, or `REJECTED` moves to `CLOSED`; their capital projects in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` are cancelled with their unused reservations released to plan capital as in §3.4; and their reforecasts in `DRAFT` or `SUBMITTED` are rejected. The portfolio's `total_value_cents` and `risk_posture` are recomputed. The `DELIST` action runs the pipeline in reverse direction, moving a `LISTED_FOR_SALE` asset back to `OWNED`. An action that does not match the asset's current status — contracting an unlisted asset, closing without a contract, delisting something not listed — is rejected with `ERR_ASSET_NOT_SELLABLE`, and a missing price field where one is required is `ERR_INVALID_REQUEST`. Once every asset of a portfolio is `SOLD`, the archive gate of §3.1 opens.

### 3.9. Portfolio Risk Posture and Performance Reporting

The portfolio's `risk_posture` is a pure function of its loan book, recomputed whenever a loan changes status, a covenant is waived, or a sale cascade completes. Counting only loans on assets that are not `SOLD`: when any loan is in `DEFAULT`, or two or more loans are in `WATCH`, the posture is `RESTRICTED`; when exactly one loan is in `WATCH` and none in `DEFAULT`, the posture is `ELEVATED`; otherwise it is `NORMAL`. Posture is not decorative — a `RESTRICTED` portfolio blocks business-plan approval (§3.2) and blocks approval of any non-emergency capital project (§3.4). The portfolio's `total_value_cents` is likewise derived: the sum of the latest confirmed valuations' implied values across the portfolio's assets in `OWNED` or `LISTED_FOR_SALE`, recomputed at every valuation confirmation and at sale closing.

The performance rollup read answers how the portfolio is operating. It ranges over assets in `OWNED`, `LISTED_FOR_SALE`, or `UNDER_CONTRACT` and reports five figures: `asset_count`, the number of such assets; `total_value_cents`, the sum of their `current_value_cents` with unset values treated as zero; `portfolio_noi_cents`, the sum of their `current_annualized_noi_cents`, again treating unset values as zero; `weighted_occupancy_pct`, the square-footage-weighted mean occupancy — each asset contributes the occupancy of its most recent finalized scorecard — the latest by `period_label`, with any residual tie resolved in favor of the later-created record — times its `net_rentable_sqft`, divided by the total square footage of all counted assets, rounded half-up — or exactly 0 when no assets are counted and the denominator is zero — where an asset with no finalized scorecard contributes zero to the numerator but still adds its square footage to the denominator; and `implied_cap_rate_bps`, the portfolio NOI times ten thousand divided by the total value, rounded half-up, or null when the total value is zero.

## 4. Endpoint Definitions

Operations that create a new resource — a portfolio, asset, plan, budget-line batch, actuals report, project, draw, strategy, loan, covenant, covenant test, valuation, scorecard, reforecast, decision, or lender report — return `201 Created`. Operations that modify an existing resource, including every state-transition action, return `200 OK`. The logical-clock capability also returns `200 OK`. The API is mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the server's logical clock to a supplied instant | PortfolioDirector |
| POST | `/api/portfolios` | Create a portfolio | PortfolioDirector |
| GET | `/api/portfolios/{id}` | Get a portfolio | Any |
| POST | `/api/portfolios/{id}/archive` | Archive a portfolio whose assets are all SOLD | PortfolioDirector |
| GET | `/api/portfolios/{id}/performance-report` | Computed portfolio performance rollup | Any |
| GET | `/api/portfolios/{id}/assets` | List assets of a portfolio | Any |
| POST | `/api/property-managers` | Create a property manager | PortfolioDirector |
| GET | `/api/property-managers/{id}` | Get a property manager | Any |
| POST | `/api/property-managers/{id}/suspend` | Suspend a manager, or terminate when the terminate flag is true | PortfolioDirector |
| POST | `/api/property-managers/{id}/reinstate` | Reinstate a suspended manager | PortfolioDirector |
| GET | `/api/property-managers/{id}/assets` | List assets managed by a property manager | Any |
| GET | `/api/property-managers/{id}/performance-scorecards` | List scorecards of a manager | Any |
| POST | `/api/assets` | Create an asset in a portfolio under a property manager | PortfolioDirector |
| GET | `/api/assets/{id}` | Get an asset | Any |
| POST | `/api/assets/{id}/record-sale` | Run the sale pipeline: CONTRACT, CLOSE, or DELIST | PortfolioDirector |
| GET | `/api/assets/{id}/business-plans` | List plans of an asset | Any |
| GET | `/api/assets/{id}/capital-projects` | List capital projects of an asset | Any |
| GET | `/api/assets/{id}/lease-strategies` | List lease strategies of an asset | Any |
| GET | `/api/assets/{id}/loans` | List loans of an asset | Any |
| GET | `/api/assets/{id}/valuations` | List valuations of an asset | Any |
| GET | `/api/assets/{id}/performance-scorecards` | List scorecards of an asset | Any |
| GET | `/api/assets/{id}/disposition-decisions` | List disposition decisions of an asset | Any |
| POST | `/api/business-plans` | Create a draft annual plan, superseding any approved same-year plan | AssetManager |
| GET | `/api/business-plans/{id}` | Get a business plan | Any |
| POST | `/api/business-plans/{id}/submit` | Submit a draft plan, or resubmit a rejected one | AssetManager |
| POST | `/api/business-plans/{id}/approve` | Approve a submitted plan (manager standing and posture gates) | PortfolioDirector |
| POST | `/api/business-plans/{id}/reject` | Reject a submitted plan | PortfolioDirector |
| GET | `/api/business-plans/{id}/variance-summary` | Per-category budget-versus-actual variance rollup | Any |
| GET | `/api/business-plans/{id}/budget-lines` | List budget lines of a plan in creation order | Any |
| GET | `/api/business-plans/{id}/actuals-reports` | List actuals reports of a plan | Any |
| GET | `/api/business-plans/{id}/capital-projects` | List capital projects reserved against a plan | Any |
| GET | `/api/business-plans/{id}/reforecasts` | List reforecasts of a plan | Any |
| POST | `/api/budget-lines` | Bulk-atomic creation of budget lines on a DRAFT or REJECTED plan | AssetManager |
| POST | `/api/actuals-reports` | Post monthly actuals against plan lines | PropertyManager |
| POST | `/api/actuals-reports/{id}/accept` | Accept an actuals report, posting actuals to lines | AssetManager |
| POST | `/api/actuals-reports/{id}/reject` | Reject an actuals report | AssetManager |
| POST | `/api/capital-projects` | Propose a capital project against an asset's plan | AssetManager |
| GET | `/api/capital-projects/{id}` | Get a capital project | Any |
| POST | `/api/capital-projects/{id}/approve` | Approve a project with plan OCC, reserving plan capital | InvestmentCommittee, PortfolioDirector |
| POST | `/api/capital-projects/{id}/reject` | Reject a proposed project | InvestmentCommittee, PortfolioDirector |
| POST | `/api/capital-projects/{id}/start` | Mark an approved project in progress | AssetManager |
| POST | `/api/capital-projects/{id}/complete` | Complete a project, releasing unused authorization | AssetManager |
| POST | `/api/capital-projects/{id}/cancel` | Cancel an approved or in-progress project | AssetManager |
| GET | `/api/capital-projects/{id}/funding-draws` | List draws of a project | Any |
| POST | `/api/funding-draws` | Request a funding draw against a project | AssetManager |
| POST | `/api/funding-draws/{id}/approve` | Approve a draw (cumulative authorization check) | InvestmentCommittee |
| POST | `/api/funding-draws/{id}/reject` | Reject a requested draw | InvestmentCommittee |
| POST | `/api/funding-draws/{id}/release` | Release an approved draw (money movement) | PortfolioDirector |
| POST | `/api/lease-strategies` | Draft a lease strategy for a space type | AssetManager, PropertyManager |
| POST | `/api/lease-strategies/{id}/recommend` | Compute the recommended rate for a draft strategy | Analyst |
| POST | `/api/lease-strategies/{id}/ratify` | Ratify a recommended strategy, superseding the prior one | PortfolioDirector |
| POST | `/api/lease-strategies/{id}/reject` | Reject a recommended strategy | PortfolioDirector |
| POST | `/api/loans` | Originate a loan on an asset | PortfolioDirector |
| GET | `/api/loans/{id}` | Get a loan | Any |
| GET | `/api/loans/{id}/covenants` | List covenants of a loan | Any |
| GET | `/api/loans/{id}/lender-reports` | List lender reports of a loan | Any |
| POST | `/api/covenants` | Attach a covenant to a loan | PortfolioDirector |
| GET | `/api/covenants/{id}` | Get a covenant | Any |
| POST | `/api/covenants/{id}/waive` | Waive a breached covenant | Lender |
| GET | `/api/covenants/{id}/covenant-tests` | List tests of a covenant (append-only) | Any |
| POST | `/api/covenant-tests` | Record a covenant test with server-side measurement | Analyst |
| POST | `/api/valuations` | Draft a valuation (external appraisal or internal cap) | Analyst |
| POST | `/api/valuations/{id}/confirm` | Confirm a valuation with asset OCC, superseding the prior one | PortfolioDirector |
| POST | `/api/performance-scorecards` | Submit a quarterly scorecard for a managed asset | PropertyManager |
| POST | `/api/performance-scorecards/{id}/review` | Mark a scorecard reviewed | AssetManager |
| POST | `/api/performance-scorecards/{id}/finalize` | Finalize a scorecard, applying streak and suspension rules | AssetManager |
| POST | `/api/reforecasts` | Draft a reforecast for the approved plan at a cadence checkpoint | AssetManager |
| POST | `/api/reforecasts/{id}/submit` | Submit a reforecast draft | AssetManager |
| POST | `/api/reforecasts/{id}/accept` | Accept and apply a reforecast with plan OCC | PortfolioDirector |
| POST | `/api/reforecasts/{id}/reject` | Reject a submitted reforecast | PortfolioDirector |
| POST | `/api/disposition-decisions` | Open a refinance, hold, or sell decision with trigger snapshot | AssetManager |
| POST | `/api/disposition-decisions/{id}/submit-review` | Move a decision to committee review | AssetManager |
| POST | `/api/disposition-decisions/{id}/ratify` | Ratify a decision (ratifier differs from creator) | InvestmentCommittee |
| POST | `/api/disposition-decisions/{id}/shelve` | Shelve a decision under review or ratified | InvestmentCommittee |
| POST | `/api/disposition-decisions/{id}/execute` | Execute a ratified decision | PortfolioDirector |
| POST | `/api/lender-reports` | Draft a quarterly lender report for a loan | AssetManager |
| POST | `/api/lender-reports/{id}/submit` | Submit a lender report, freezing snapshots and lateness | AssetManager |
| POST | `/api/lender-reports/{id}/acknowledge` | Acknowledge a submitted lender report | Lender |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narrative of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_DUPLICATE_PLAN` | 409 Conflict |
| `ERR_PLAN_HAS_ACTIVE_PROJECTS` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_ASSET_NOT_OPERATING` | 409 Conflict |
| `ERR_ASSET_NOT_SELLABLE` | 409 Conflict |
| `ERR_MANAGER_SUSPENDED` | 409 Conflict |
| `ERR_MANAGER_IN_USE` | 409 Conflict |
| `ERR_PORTFOLIO_RESTRICTED` | 409 Conflict |
| `ERR_PORTFOLIO_NOT_EMPTY` | 409 Conflict |
| `ERR_CAPITAL_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_CAPITAL_SCHEDULE_OVER_COMMITTED` | 409 Conflict |
| `ERR_PROJECT_NOT_FUNDABLE` | 409 Conflict |
| `ERR_DRAW_EXCEEDS_AUTHORIZATION` | 409 Conflict |
| `ERR_PROJECT_NEVER_FUNDED` | 409 Conflict |
| `ERR_DUPLICATE_BUDGET_LINE` | 409 Conflict |
| `ERR_DUPLICATE_ACTUALS` | 409 Conflict |
| `ERR_REFORECAST_LIMIT` | 409 Conflict |
| `ERR_REFORECAST_BELOW_ACTUALS` | 409 Conflict |
| `ERR_DUPLICATE_COVENANT_TEST` | 409 Conflict |
| `ERR_COVENANT_NOT_TESTABLE` | 409 Conflict |
| `ERR_NO_NOI_EVIDENCE` | 409 Conflict |
| `ERR_STALE_VALUATION` | 409 Conflict |
| `ERR_COVENANT_NOT_WAIVABLE` | 409 Conflict |
| `ERR_VALUATION_REGRESSIVE` | 409 Conflict |
| `ERR_VALUATION_NO_NOI_EVIDENCE` | 409 Conflict |
| `ERR_DECISION_TRIGGER_NOT_ARMED` | 409 Conflict |
| `ERR_LOAN_EXISTS` | 409 Conflict |
| `ERR_LOAN_NOT_REPORTABLE` | 409 Conflict |
| `ERR_LENDER_REPORT_GAP` | 409 Conflict |
| `ERR_DUPLICATE_SCORECARD` | 409 Conflict |
| `ERR_PLAN_LINES_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_FUTURE_PERIOD` | 422 Unprocessable Entity |
| `ERR_REFORECAST_CADENCE` | 422 Unprocessable Entity |
| `ERR_REFORECAST_CATEGORIES_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_STALE_ASSET_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
