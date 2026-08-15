# Real Estate Underwriting API — Product Requirements Document

## 1. Introduction

This document specifies a REST API that powers the underwriting workbench of a real estate private equity firm. The platform covers the full arc from initial deal intake — capturing the property, its rent roll history, and its operating expense profile — through assumption-setting, scenario computation, debt sizing, waterfall modeling, and ultimately the Investment Committee (IC) vote that decides whether the firm pursues, renegotiates, or passes on the opportunity.

The system is built around a strict separation of duties. An `Analyst` originates a deal and assembles the data room; an `AssetManager` takes ownership of the deal once it moves into active underwriting and is the only party who can submit it to the IC; `IC_Member` and `IC_Chair` roles vote on submitted memos; and an `Admin` role exists for operational and test-driving tasks. Every state transition, every calculation, and every approval is recorded with optimistic-concurrency guards so that two writers never silently overwrite each other's view of a deal's lifecycle.

Because underwriting decisions involve real capital, every number the system emits — year-one net operating income, unlevered IRR, equity multiple, debt size, and LP/GP waterfall splits — must be reproducible from the inputs. Formulas are specified precisely, all money amounts are carried as integer cents, and percentages are carried as basis points to avoid floating-point ambiguity.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, presenting an empty `X-User-ID`, or carrying an `X-User-Role` value that is not one of the declared role names is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The five roles are:

- `Analyst` — deal originator; creates deals, enters rent roll and operating expense data, maintains market assumptions, builds scenarios, computes outputs, drafts IC memos, submits them, and reopens deals.
- `AssetManager` — senior reviewer; takes ownership of a deal once it moves into `UNDERWRITING`, submits deals to the IC, and marks rejected deals dead.
- `IC_Member` — investment committee member; casts votes on memos that are under vote.
- `IC_Chair` — IC chair; may cast votes just like an `IC_Member` and additionally may force-reject a memo.
- `Admin` — operator; reads any resource and drives the server's logical clock.

All five roles have `identity: opaque`. When `X-User-Role` is `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, or `Admin`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does, however, record `X-User-ID` onto specific fields of resources: onto `deal.analyst_id` at deal-creation time, onto `deal.asset_manager_id` at submit-underwriting time, and onto `ICVote.voter_user_id` at vote time. Ownership checks compare `X-User-ID` against these stored fields: any action scoped to "the deal's analyst" requires `X-User-ID` to equal `deal.analyst_id`, and any action scoped to "the deal's asset manager" requires `X-User-ID` to equal `deal.asset_manager_id`. A mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). A request whose role is not permitted for the requested endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Ownership matching is enforced only on the lifecycle actions named in §3: submit-underwriting, scenario compute, memo submit, and reopen (matched against `deal.analyst_id`), and submit-to-IC and mark-dead (matched against `deal.asset_manager_id`). All other write endpoints — creating properties, rent roll periods, operating expenses, assumption sets (including activation), scenarios, memos, debt sizings, and waterfalls — require only the endpoint's declared role and perform no ownership match.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format:

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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); the same applies to filter parameters that fail to parse (for example, a non-integer `period_year`). Results are always sorted by `created_at` ascending (oldest first) unless stated otherwise. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object; `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties

Most resources carry a uniform set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource. Every mutating operation (state transition, cascade side-effect, child-resource creation that bumps the parent) increments the affected resource's `version` by 1 and refreshes `updated_at`.

Two resource types are exceptions to this rule and carry only `id` and `created_at` — both `updated_at` and `version` are absent:

- `RentRollPeriod`
- `OperatingExpense`
- `ICVote`

These are append-only records. They are never updated, so optimistic concurrency does not apply to them.

### 2.5. Monetary and Percentage Representations

All money amounts are stored and transmitted as integer cents in fields whose names end in `_cents` (for example, `target_purchase_price_cents`, `gross_potential_rent_cents`, `loan_amount_cents`). All growth rates, cap rates, interest rates, hurdle rates, and promote percentages are carried as integer basis points in fields whose names end in `_bps` (for example, `market_rent_growth_yr1_bps`, `exit_cap_rate_bps`, `interest_rate_bps`, `promote_tier1_bps`). A value of 250 in a `_bps` field therefore represents 2.50 percent. Whole-percent integer fields (for example, `occupancy_stress_pct`, `min_dscr_pct`, `max_ltv_pct`, `dscr_at_size_pct`, `ltv_at_size_pct`) carry their value in whole percent, so 125 in `min_dscr_pct` represents a 1.25x DSCR floor.

Calculation precision is fixed: money amounts in cents are rounded to integer cents with round-half-up unless a specific formula specifies otherwise. The IRR is expressed as integer basis points rounded half-up. The equity multiple is expressed as integer basis points rounded half-up, where 10000 represents 1.0x. Debt-sizing loan amounts are rounded down (floor) to integer cents; the resulting DSCR and LTV percentages are rounded to the nearest whole percent (ties round half-up). Occupancy percentage is stored with exactly 2 decimal places, rounded half-up, and serialized as a JSON number.

### 2.6. Nested Resource Retrieval and Path Validation

Path parameters are validated left-to-right. For a path such as `/re-underwriting/deals/{id}/properties` or `/re-underwriting/scenarios/{id}/debt-sizing`, the server first verifies that the leftmost path parameter (the deal, the scenario, and so on) resolves to an existing resource, then walks right. If any path segment does not resolve, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any other check runs. Similarly, body-referenced foreign-key identifiers — such as `assumption_id` on a scenario-create request or `scenario_id` on a memo-create request — must resolve to existing resources; an unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency Control on Deal-Scoped Writes

Two write endpoints are OCC-guarded against the parent `Deal`'s `version`. Both accept an additional input field, `expected_deal_version`, carrying the value of `deal.version` that the client last observed. The field is optional at the protocol layer: when it is omitted, the create proceeds without an OCC check; when it is supplied, it must be an integer (otherwise `ERR_INVALID_REQUEST`, HTTP 400) and must equal the deal's current `version`.

- Creating a `Scenario` against a deal — if the request carries `expected_deal_version` and the deal's current `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against the case where another writer has just advanced the deal's lifecycle (submitted it to IC, reopened it, or marked it dead) and the current writer's view of the deal's status is stale.
- Creating an `ICMemo` against a deal — same rule, same field, same rejection code: if the request carries `expected_deal_version`, a mismatch with the deal's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other write endpoint takes a version field. Endpoints not listed here do not participate in OCC.

### 2.8. Validation Ordering

When several validation rules apply to a single request, they are evaluated in the following priority order. A failure at any tier short-circuits the remainder.

1. `X-User-Role` header is present and is one of the declared role names — otherwise `ERR_UNAUTHENTICATED` (401).
2. `X-User-ID` header is present and non-empty — otherwise `ERR_UNAUTHENTICATED` (401).
3. Caller role is permitted for the requested endpoint — otherwise `ERR_FORBIDDEN` (403).
4. Path resources exist, validated left-to-right — otherwise `ERR_NOT_FOUND` (404).
5. Body-referenced foreign-key ids exist — otherwise `ERR_NOT_FOUND` (404).
6. Target entity is in a state from which the requested transition is valid — otherwise `ERR_INVALID_STATE` (409).
7. Ownership: caller `X-User-ID` matches the owning role field on the parent (`deal.analyst_id` for analyst-scoped actions, `deal.asset_manager_id` for asset-manager-scoped actions) — otherwise `ERR_FORBIDDEN` (403).
8. Business referential checks specific to the endpoint (for scenario-create, `assumption_id` resolves to a `MarketAssumption` belonging to the same deal — otherwise `ERR_ASSUMPTION_MISMATCH` (422); for IC memo create, `scenario_id` resolves to a `Scenario` belonging to the same deal and in `COMPUTED` status — otherwise `ERR_SCENARIO_NOT_COMPUTED` (422)).
9. Business constraint checks (duplicate `deal_code` — `ERR_DUPLICATE_DEAL_CODE` (409); duplicate `(property_id, period_month)` for a rent roll or `(property_id, period_year, category)` for an operating expense — `ERR_DUPLICATE_PERIOD` (409); out-of-range numerics such as `occupancy_stress_pct`, `exit_cap_rate_bps`, `amortization_years`, `hold_period_years` — `ERR_INVALID_REQUEST` (400)).
10. Business fiscal checks (debt sizing on a scenario whose `computed_noi_yr1_cents` is not positive — `ERR_NOI_NONPOSITIVE` (422); regressive promote where `promote_tier2_bps` is less than `promote_tier1_bps` — `ERR_PROMOTE_REGRESSIVE` (422)).
11. Business safety checks (duplicate vote from the same voter — `ERR_DUPLICATE_VOTE` (409); segregation of duties where the deal's analyst attempts to vote on that deal's memo — `ERR_SEG_DUTIES` (403); voting on a memo that is not in `UNDER_VOTE` — `ERR_INVALID_STATE` (409)).
12. Business temporal checks (non-monotonic `period_month` on rent roll append — `ERR_NONMONOTONIC_PERIOD` (422); `period_year` in the future on an operating expense — `ERR_FUTURE_PERIOD` (422)).
13. OCC check: when `expected_deal_version` is supplied on an OCC-guarded endpoint, it must equal the deal's current `version` — otherwise `ERR_STALE_VERSION` (412).

Within this ordering, request-body field validation for the endpoint's own payload fields — presence of required fields, JSON types, enum membership, and numeric ranges, all rejected with `ERR_INVALID_REQUEST` (400) — is evaluated after body-referenced foreign-key existence (tier 5) and before the business referential checks of tier 8. For example, a scenario create carrying both an out-of-range `occupancy_stress_pct` and a cross-deal `assumption_id` is rejected with `ERR_INVALID_REQUEST`, not `ERR_ASSUMPTION_MISMATCH`.

So, for example, an analyst attempting to create a scenario against a deal whose version has advanced will only see `ERR_STALE_VERSION` after role, existence, state, ownership, referential, and constraint checks have all passed. Conversely, an unauthenticated caller is rejected with `ERR_UNAUTHENTICATED` before any resource lookup runs.

### 2.9. Logical Clock for Tests

The server maintains a logical UTC clock used wherever a "current time" is required (for example, when stamping `submitted_at`, `decided_at`, `approved_at`, or `cast_at`, or when evaluating whether a `period_year` is in the future). At server startup, the logical clock is initialized to `2026-08-01T00:00:00Z` and never falls back to the wall clock. An admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant — any valid ISO 8601 timestamp is accepted, including one earlier than the current value — and returns the resulting `current_utc`; an unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

---

## 3. Business Logic & Workflows

### 3.1. Deal Origination and Intake

A new engagement begins when an `Analyst` creates a deal. The analyst supplies a `deal_code` (a human-readable identifier unique across the firm, between 4 and 32 characters), a short `deal_name`, the investment `strategy` (one of `CORE`, `CORE_PLUS`, `VALUE_ADD`, `OPPORTUNISTIC`), and the proposed `target_purchase_price_cents` (any integer is accepted at intake; no positivity constraint applies at creation). The server records the caller's `X-User-ID` onto `deal.analyst_id` and initializes `status` to `DRAFT`. If another deal already carries the same `deal_code`, the create is rejected with `ERR_DUPLICATE_DEAL_CODE` (HTTP 409).

Before a deal can leave `DRAFT`, two prerequisites must hold: at least one `Property` has been created under it, and at least one `MarketAssumption` is active on it. Submitting for underwriting — transitioning the deal `DRAFT → UNDERWRITING` — is an analyst-only action that requires `X-User-ID` to equal `deal.analyst_id`. As part of that transition the server reads the `X-AssetManager-ID` header and writes it onto `deal.asset_manager_id` (if the header is absent, `asset_manager_id` is set to null), formally handing the deal off to a senior reviewer. The deal's `version` increments by 1.

Once a deal is in `UNDERWRITING`, the analyst can continue to build out the data room — adding rent rolls, expenses, and scenarios — but cannot re-edit intake-level identity fields. If the team decides to step back, the analyst may reopen the deal, transitioning it `UNDERWRITING → DRAFT`. Reopen is permitted only when no `ICMemo` for this deal is currently in `SUBMITTED` or `UNDER_VOTE` status; otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409). On a successful reopen, every `Scenario` belonging to the deal that is currently in `COMPUTED` status is cascaded to `SUPERSEDED` with `superseded_by_id` set to null — marking them for re-compute — and the deal's `version` increments by 1.

### 3.2. Property Data Room: Rent Roll and Operating History

Properties are created under a deal by an `Analyst`. The analyst provides `address_line`, `market` (an MSA or market name such as "Austin, TX"), `property_type` (one of `MULTIFAMILY`, `OFFICE`, `RETAIL`, `INDUSTRIAL`, `MIXED_USE`), `units` (at least 1), `rentable_sqft` (at least 100), and `year_built` (between 1800 and 2100). Property creation is permitted only while the parent deal is in `DRAFT` or `UNDERWRITING`; attempting it against a deal in any other state is rejected with `ERR_INVALID_STATE`. Each property creation bumps the parent deal's `version` by 1.

The rent roll is append-only and chronologically ordered. Each `RentRollPeriod` is bound to its parent by `property_id` and records `period_month` (a calendar month in `YYYY-MM` format), `occupied_units` (zero or more), `total_units` (at least 1), `gross_potential_rent_cents` (the rent the property would produce at full occupancy, zero or more), `collected_rent_cents` (actual rent collected, zero or more), an optional `concessions_cents` (a non-negative integer, defaulting to 0 when omitted), and `source_doc_ref` pointing to the external rent roll PDF or CSV. The server enforces that the new `period_month` is strictly greater than the latest existing `period_month` on the same property; an append that violates monotonicity is rejected with `ERR_NONMONOTONIC_PERIOD` (HTTP 422). Only one rent roll row may exist per `(property_id, period_month)` pair; a duplicate is rejected with `ERR_DUPLICATE_PERIOD` (HTTP 409). `period_month` is not format-validated beyond being a string; duplicate and monotonicity comparisons operate on the string as supplied (lexicographic ordering). Rent roll appends and operating-expense records are accepted regardless of the parent deal's status.

Each rent roll append also triggers a recomputation of the property's `occupancy_pct`. The property's occupancy is the ratio of `occupied_units` to `total_units` from the most recent `RentRollPeriod` by `period_month`, multiplied by 10000, rounded half-up to an integer, and then divided by 100 — yielding a percentage stored with exactly two decimal places and serialized as a JSON number (so a value serialized as 92.5 means 92.50%). Until the first rent roll exists, `occupancy_pct` is null. Each rent roll append increments the parent `Property.version` by 1.

Operating expenses are recorded per property per calendar year per category. The analyst supplies `period_year`, a `category` (one of `TAXES`, `INSURANCE`, `UTILITIES`, `REPAIRS`, `MANAGEMENT`, `PAYROLL`, `MARKETING`, `OTHER`), the `amount_cents` (zero or more), and an optional `is_recoverable` flag (defaulting to `false`) indicating whether the expense is recoverable from tenants. Only one row may exist per `(property_id, period_year, category)` triple; a duplicate is rejected with `ERR_DUPLICATE_PERIOD` (HTTP 409). The server also rejects a `period_year` that lies in the future relative to the server's logical clock with `ERR_FUTURE_PERIOD` (HTTP 422). Each operating-expense creation increments the parent `Property.version` by 1.

### 3.3. Market Assumptions and the Active Set

A `MarketAssumption` bundles the forward-looking inputs that drive every projection on a deal. The analyst provides a `label` (for example, "Base 2026 H2"), `market_rent_growth_yr1_bps` (year-one rent growth in basis points), `market_rent_growth_steady_bps` (steady-state growth applied to years two and beyond), `expense_growth_bps` (annual expense growth), `exit_cap_rate_bps` (terminal cap rate; must be greater than zero), `hold_period_years` (between 1 and 15 inclusive), `capex_per_unit_cents` (renovation budget per unit, zero or more), and `lease_up_months` (months to stabilize post-renovation, between 0 and 36 inclusive). An out-of-range numeric value on any of these fields is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Exactly one assumption set per deal is active at any moment, tracked by the `is_active` flag. The very first `MarketAssumption` created on a deal is automatically set to `is_active=true`. Activating a different assumption set is a dedicated action: it sets `is_active=true` on the target set, flips every other set on the same deal to `is_active=false`, and increments the target set's `version` by 1. Creating a new assumption set increments the parent deal's `version` by 1. Assumption sets may be created and activated regardless of the deal's status. Activating an already-active set is permitted and still increments its `version` by 1. Deactivation flips only the `is_active` flag of the previously active sets; their `version` and `updated_at` are left unchanged.

### 3.4. Scenarios: Building the Underwriting Cases

A `Scenario` is a specific underwriting case layered on top of an assumption set. The analyst picks a `scenario_kind` (one of `BASE`, `DOWNSIDE`, `UPSIDE`, `STRESS`), references an `assumption_id`, and sets `occupancy_stress_pct` as a whole percent between 0 and 100 (so 92 means the model assumes 92% steady-state occupancy). Because scenario creation is OCC-guarded, the request may also carry `expected_deal_version`; when supplied, a mismatch with the deal's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The referenced `assumption_id` must resolve to a `MarketAssumption` belonging to the same deal; a cross-deal reference is rejected with `ERR_ASSUMPTION_MISMATCH` (HTTP 422).

A new scenario starts in `DRAFT` status. Scenario creation is permitted regardless of the deal's status, and increments the parent deal's `version` by 1. The analyst then triggers computation, which transitions the scenario `DRAFT → COMPUTED` and writes three outputs onto it: `computed_noi_yr1_cents`, `computed_irr_bps`, and `computed_equity_multiple_bp`. Computation requires that the parent deal is in `UNDERWRITING` status; attempting to compute a scenario while the deal is in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Only the deal's analyst may compute. Each successful computation increments `Scenario.version` by 1.

A scenario in `COMPUTED` status may later be cascaded to `SUPERSEDED` (the terminal state for a scenario) by one of two events: a deal reopen, or a deal submit-to-IC (which supersedes every other `COMPUTED` scenario besides the one pinned to the memo). Computing a newer scenario — `BASE` or otherwise — does not supersede existing `COMPUTED` scenarios. The cascade sets `superseded_by_id` per the triggering event — null on reopen, or the pinned scenario's id on submit-to-IC — and increments `Scenario.version` by 1.

#### 3.4.1. Year-1 Net Operating Income

Year-1 NOI combines the property's latest rent roll, its most recent operating-expense year, the scenario's assumption set, and the scenario's occupancy stress. The relevant rent roll is the one with the latest `period_month`; the relevant expense set is all `OperatingExpense` rows on the property for the latest `period_year`, summed. When a deal has multiple properties, the computation uses the deal's first-created property. If the deal has no property, or the property has no rent roll, compute is rejected with `ERR_INVALID_STATE` (HTTP 409); if no operating-expense rows exist for the property, the expense base is zero. Computation also requires `target_purchase_price_cents` to be positive, otherwise `ERR_INVALID_REQUEST` (HTTP 400).

First, monthly rent-roll figures are annualized: `gross_potential_rent_cents` is multiplied by 12 to produce the annualized gross potential rent, and `concessions_cents` is multiplied by 12 to produce the annualized concessions.

Second, effective gross income is computed. The formula has two variants, differing only in whether concessions are netted before or after the year-one growth factor is applied. The occupancy factor is `occupancy_stress_pct` divided by 100. The year-one growth factor is one plus `market_rent_growth_yr1_bps` divided by 10000.

- The **provisional** variant — used while the scenario is still in `DRAFT` at the moment compute is invoked — subtracts annualized concessions after applying the growth factor: annualized gross potential rent is multiplied by the occupancy factor, multiplied by the year-one growth factor, and only then are annualized concessions subtracted.
- The **final** variant — used once the scenario is pinned by an IC memo (that is, the deal is in `IC_REVIEW` with `current_scenario_id` pointing at this scenario) — nets concessions before applying the growth factor: annualized gross potential rent minus annualized concessions, the result multiplied by the occupancy factor, and the product multiplied by the year-one growth factor. When the scenario is pinned for IC review, this final figure is recomputed and replaces the provisional value. The recomputation at pinning also recomputes `computed_irr_bps` and `computed_equity_multiple_bp` from the final NOI figure, and does not increment the scenario's `version`.

Third, year-one operating expenses are computed. The summed expenses from the latest `period_year` are grown by one plus `expense_growth_bps` divided by 10000. Two additional charges are added on top. The capex budget — `capex_per_unit_cents` multiplied by the property's `units` — is straight-line amortized across the hold period by dividing by the larger of 1 and `hold_period_years`. The lease-up cost — `lease_up_months` multiplied by the monthly gross potential rent, then multiplied by one minus the occupancy factor — is charged fully to year one.

Year-one NOI is the chosen effective-gross-income variant minus year-one operating expenses, rounded half-up to integer cents.

#### 3.4.2. Unlevered IRR and Equity Multiple

Once year-one NOI is known, the model projects forward across the hold period. For each year t from 2 through `hold_period_years`, the projected NOI for that year is the year-one NOI multiplied by one plus `market_rent_growth_steady_bps` divided by 10000, that whole factor raised to the power of (t − 1). The terminal NOI used at exit is the year-one NOI multiplied by one plus `market_rent_growth_steady_bps` divided by 10000, that whole factor raised to the power of `hold_period_years`. The exit value is the terminal NOI divided by the exit cap rate (the latter obtained by dividing `exit_cap_rate_bps` by 10000), rounded half-up to integer cents.

Cash flows are then assembled as follows. At time zero the flow is the negative of the deal's `target_purchase_price_cents`. For each year from 1 through `hold_period_years − 1`, the flow is that year's projected NOI. In the final year, the flow is that year's projected NOI plus the exit value.

The unlevered IRR is the discount rate at which the net present value of these flows is zero. It is solved by bisection on the rate over the interval from negative 0.99 to positive 1.00 with a tolerance of 1e-6. If the net present value has the same sign at both endpoints of the interval (no root is bracketed), the endpoint whose net present value has the smaller absolute magnitude is returned as the IRR. The result is converted to basis points by multiplying by 10000 and rounded half-up to an integer, which is written to `computed_irr_bps`.

The unlevered equity multiple is the sum of all projected year-NOIs from years 1 through `hold_period_years` plus the exit value, divided by `target_purchase_price_cents`, multiplied by 10000, and rounded half-up to an integer basis-point figure. The result — where 10000 represents 1.0x — is written to `computed_equity_multiple_bp`.

### 3.5. Debt Sizing

Once a scenario has been computed, the analyst may run a debt sizing against it. The scenario must be in `COMPUTED` status, otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409). The inputs are `interest_rate_bps` (fixed annual note rate), `amortization_years` (between 1 and 30 inclusive), `io_months` (interest-only period, between 0 and 120 inclusive), `min_dscr_pct` (minimum acceptable debt-service-coverage ratio, in whole percent — so 125 means 1.25x), and `max_ltv_pct` (maximum loan-to-value, in whole percent — so 65 means 65%). `io_months` is validated and recorded on the sizing but does not enter the sizing formula. Creating a debt sizing does not increment the parent scenario's `version`.

Debt sizing requires the scenario's `computed_noi_yr1_cents` to be positive. If it is zero or negative, the request is rejected with `ERR_NOI_NONPOSITIVE` (HTTP 422).

The sizing solves for the largest loan that satisfies both constraints. The annual rate is `interest_rate_bps` divided by 10000; the number of payments is `amortization_years` multiplied by 12. The monthly rate is the annual rate divided by 12. If the monthly rate is zero, the annual debt service per dollar of loan is one divided by `amortization_years`. Otherwise, the monthly payment per dollar is the monthly rate divided by the quantity one minus the quantity one plus the monthly rate raised to the negative of the number of payments; the annual debt service per dollar is then that monthly payment per dollar multiplied by 12.

The DSCR-constrained maximum loan is the year-one NOI divided by the product of `min_dscr_pct` divided by 100 and the annual debt service per dollar. The LTV-constrained maximum loan is the deal's `target_purchase_price_cents` multiplied by `max_ltv_pct` divided by 100. The sized `loan_amount_cents` is the smaller of the two maxima, floored to integer cents.

The binding constraint is recorded on `sizing_constraint`. If the absolute difference between the DSCR-constrained maximum and the LTV-constrained maximum is less than one cent, the sizing is recorded as `BOTH`. Otherwise, if the DSCR maximum is strictly less than the LTV maximum, the sizing is `DSCR`; otherwise it is `LTV`.

The realized ratios at the sized amount are also recorded. `dscr_at_size_pct` is the year-one NOI divided by the product of the sized loan and the annual debt service per dollar — a decimal converted to a whole percent. `ltv_at_size_pct` is the sized loan divided by `target_purchase_price_cents`, multiplied by 100, and rounded to the nearest whole percent. Both ratios are recorded as 0 when the sized loan is 0.

### 3.6. Waterfall and Promote Modeling

A `Waterfall` computes the LP/GP split at exit under a two-tier promote structure. The scenario must be in `COMPUTED` status, otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409); creating a waterfall does not increment the parent scenario's `version`. The analyst supplies `pref_return_bps` (LP preferred return, annualized), `promote_tier1_bps` (GP's share of excess profits above the preferred return up to the tier-1 hurdle — so 2000 means 20%), `tier1_hurdle_bps` (the tier-1 hurdle IRR above which tier-2 promote applies), and `promote_tier2_bps` (GP's share of excess profits above the tier-1 hurdle). A regressive promote structure — one where `promote_tier2_bps` is less than `promote_tier1_bps` — is rejected with `ERR_PROMOTE_REGRESSIVE` (HTTP 422).

The waterfall begins from the same projected cash flows the scenario's IRR calculation used. LP equity is the deal's `target_purchase_price_cents` multiplied by 0.90; GP equity is the remainder. Total distributions are the sum of every projected year-NOI across the hold plus the exit value.

The split is computed in tiers, each tier rounded half-up to integer cents before the next tier is computed — tier rounding is locked in sequence.

- Tier 0 returns capital pro-rata, with the convention that LP capital is returned first.
- Tier 1 pays the LP preferred return: `pref_owed` is the LP equity multiplied by `pref_return_bps` divided by 10000, multiplied by `hold_period_years` — a simple, non-compounded amount. The profit available after capital is returned is total distributions minus the sum of LP and GP equity. The LP preferred payment `lp_pref` is the smaller of `pref_owed` and the maximum of zero and that profit. The remaining profit after paying the pref is the profit minus `lp_pref`.
- Tier 2 splits the next slice of excess profits up to the tier-1 hurdle. The hurdle amount is the LP equity multiplied by the quantity one plus `tier1_hurdle_bps` divided by 10000 raised to the power of `hold_period_years`, minus 1, and then minus `lp_pref`. The tier-1 excess is the smaller of the maximum of zero and the remaining profit, and the maximum of zero and the hurdle amount. The GP's share of tier-1 (`gp_tier1`) is the tier-1 excess multiplied by `promote_tier1_bps` divided by 10000; the LP's share (`lp_tier1`) is the tier-1 excess minus `gp_tier1`.
- Tier 3 splits whatever remains above the tier-1 hurdle. The tier-2 excess is the remaining profit minus the tier-1 excess. The GP's share (`gp_tier2`) is the tier-2 excess multiplied by `promote_tier2_bps` divided by 10000; the LP's share (`lp_tier2`) is the tier-2 excess minus `gp_tier2`.

The waterfall writes three outputs: `lp_split_cents` is LP equity plus `lp_pref` plus `lp_tier1` plus `lp_tier2`; `gp_split_cents` is GP equity plus `gp_tier1` plus `gp_tier2`; and `gp_promote_cents` is `gp_tier1` plus `gp_tier2` — the carried-interest portion of the GP's distribution.

### 3.7. IC Memo: Drafting, Submission, and Vote

When the analyst believes the underwriting is mature, they draft an `ICMemo`. The memo references the pinned base-case `scenario_id`, carries the analyst's `recommendation` (one of `PURSUE`, `PASS`, `RENEGOTIATE`), and includes free-text `thesis` and `risks` narratives. Memo creation is OCC-guarded on the deal's `version` via `expected_deal_version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The referenced `scenario_id` must belong to the same deal and must already be in `COMPUTED` status; otherwise the create is rejected with `ERR_SCENARIO_NOT_COMPUTED` (HTTP 422). A new memo starts in `DRAFT` status, and memo creation increments the deal's `version` by 1. Memo creation is permitted regardless of the deal's status.

Submitting the memo transitions it `DRAFT → SUBMITTED`. Submission is the analyst's action (the caller's `X-User-ID` must equal `deal.analyst_id`), requires the parent deal to be in `UNDERWRITING` status, and requires the referenced scenario to be in `COMPUTED` status (otherwise `ERR_INVALID_STATE`, HTTP 409). On submit the server stamps `submitted_at` with the current logical-clock UTC timestamp and increments the memo's `version` by 1.

Moving the deal from `UNDERWRITING` to `IC_REVIEW` is the `AssetManager`'s prerogative — the caller's `X-User-ID` must equal `deal.asset_manager_id`. The submit-to-IC action requires that an `ICMemo` exists for the deal in `SUBMITTED` status — when several exist, the most recently created one is used, and when none exist the request is rejected with `ERR_INVALID_STATE` (HTTP 409) — and that the scenario the memo references is in `COMPUTED` status (otherwise `ERR_INVALID_STATE`, HTTP 409). On success, three cascades fire: the deal's `current_scenario_id` is set to the memo's `scenario_id` (this is the version-pinning step — the scenario's outputs are now locked in as the basis for the IC decision); every other `COMPUTED` scenario on the same deal is transitioned to `SUPERSEDED` with `superseded_by_id` set to the pinned scenario's id; and the memo itself transitions `SUBMITTED → UNDER_VOTE`. The deal's `version` increments by 1.

### 3.8. Voting, Approval, Rejection, and Post-Decision Paths

Once a memo is in `UNDER_VOTE`, any `IC_Member` or `IC_Chair` may cast a vote. Each vote is a separate `ICVote` row tied to its parent memo by `memo_id` and carrying the `vote` value (one of `YES`, `NO`, `ABSTAIN`), an optional free-text `comment`, the voter's `X-User-ID` recorded onto `voter_user_id`, and a server-stamped `cast_at` timestamp. The same voter may not vote twice on the same memo — a repeat attempt is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409). Voting is only permitted while the memo is in `UNDER_VOTE`; voting on an already-decided memo is rejected with `ERR_INVALID_STATE` (HTTP 409).

A segregation-of-duties rule separates the deal's originator from its deciders: the user identified by `deal.analyst_id` may not cast an `ICVote` on any memo belonging to that deal. A violation is rejected with `ERR_SEG_DUTIES` (HTTP 403).

The decision logic is automatic. On each vote, after the vote is recorded, the server evaluates the tally on that memo:

- If the count of `YES` votes is at least 2 (the quorum constant `IC_QUORUM_YES`) and the count of `NO` votes is exactly zero, the memo cascades `UNDER_VOTE → APPROVED` and the deal cascades `IC_REVIEW → APPROVED`. The server stamps `decided_at` on the memo and `approved_at` on the deal with the current logical-clock UTC timestamp. The deal's `version` and the memo's `version` each increment by 1.
- If any `NO` vote is cast, the memo cascades `UNDER_VOTE → REJECTED` and the deal cascades `IC_REVIEW → REJECTED`. The deal's `rejected_reason` is set from the vote's `comment`. The server stamps `decided_at` on the memo, and both `version` fields increment by 1.
- A vote that triggers neither outcome — fewer than `IC_QUORUM_YES` (2) `YES` votes and no `NO` vote — leaves the memo and deal statuses and `version`s unchanged; only the `ICVote` row is created.

Independent of the vote tally, an `IC_Chair` may force-reject a memo. The chair supplies a `reason`; the memo transitions `UNDER_VOTE → REJECTED` with `decided_at` stamped, the deal transitions `IC_REVIEW → REJECTED` with `rejected_reason` set from the supplied `reason`, and both `version` fields increment by 1.

A rejected deal is not necessarily terminal. The analyst may reopen it — transitioning the deal `REJECTED → UNDERWRITING`. The memo remains in its terminal `REJECTED` status as an audit trail. On reopen, the deal's `current_scenario_id` is cleared back to null (unpinning the scenario; a new scenario must be built), the deal's `rejected_reason` is left unchanged (retained as an audit trail), every `COMPUTED` scenario on the deal is transitioned to `SUPERSEDED` with `superseded_by_id` set to null, and the deal's `version` increments by 1.

Alternatively, the `AssetManager` may mark a rejected deal dead — the caller's `X-User-ID` must equal `deal.asset_manager_id` — transitioning it `REJECTED → DEAD`. This is a terminal transition; only the `version` increments by 1.

`APPROVED` and `DEAD` are the terminal states of a deal. `APPROVED` and `REJECTED` are the terminal states of an IC memo. `SUPERSEDED` is the terminal state of a scenario.

---

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200. Reads return HTTP 200. All endpoints are mounted under the `/re-underwriting` prefix. Requests to undefined paths or unsupported methods are rejected with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure is returned as `ERR_INTERNAL` (HTTP 500) in the standard error envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/re-underwriting/deals` | Create a new deal in `DRAFT` status | `Analyst` |
| GET | `/re-underwriting/deals` | List deals (paginated, filterable by `status`, `analyst_id`, `asset_manager_id`, `current_scenario_id`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/deals/{id}` | Fetch a single deal | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/deals/{id}/submit-underwriting` | Move deal `DRAFT → UNDERWRITING`; assigns asset manager via `X-AssetManager-ID` header | `Analyst` |
| POST | `/re-underwriting/deals/{id}/submit-ic` | Move deal `UNDERWRITING → IC_REVIEW`; pins memo's scenario; supersedes other `COMPUTED` scenarios; flips memo to `UNDER_VOTE` | `AssetManager` |
| POST | `/re-underwriting/deals/{id}/reopen` | Move deal back to `DRAFT` (from `UNDERWRITING`) or `UNDERWRITING` (from `REJECTED`); supersedes all `COMPUTED` scenarios | `Analyst` |
| POST | `/re-underwriting/deals/{id}/mark-dead` | Move deal `REJECTED → DEAD` (terminal) | `AssetManager` |
| POST | `/re-underwriting/deals/{id}/properties` | Create a property under a deal (deal must be in `DRAFT` or `UNDERWRITING`) | `Analyst` |
| GET | `/re-underwriting/deals/{id}/properties` | List properties for a deal | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/properties/{id}` | Fetch a single property | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/properties/{id}/rent-roll` | Append a new `RentRollPeriod` (chronologically append-only) | `Analyst` |
| GET | `/re-underwriting/properties/{id}/rent-roll` | List rent roll periods for a property (filterable by `period_month`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/properties/{id}/operating-expenses` | Record an operating expense (unique per property+year+category) | `Analyst` |
| GET | `/re-underwriting/properties/{id}/operating-expenses` | List operating expenses for a property (filterable by `period_year`, `category`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/deals/{id}/assumptions` | Create a `MarketAssumption` set under a deal; the first set becomes active by default | `Analyst` |
| POST | `/re-underwriting/assumptions/{id}/activate` | Mark this assumption set as the deal's active one (deactivates any prior) | `Analyst` |
| GET | `/re-underwriting/deals/{id}/assumptions` | List assumption sets for a deal | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/assumptions/{id}` | Fetch a single `MarketAssumption` | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/deals/{id}/scenarios` | Create a scenario (OCC-guarded on `deal.version` via `expected_deal_version`) | `Analyst` |
| GET | `/re-underwriting/deals/{id}/scenarios` | List scenarios for a deal (filterable by `status`, `scenario_kind`, `assumption_id`, `superseded_by_id`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/scenarios` | Flat list of all scenarios (filterable by `status`, `scenario_kind`, `assumption_id`, `superseded_by_id`, `deal_id`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/scenarios/{id}` | Fetch a single scenario | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/scenarios/{id}/compute` | Compute scenario outputs (NOI, IRR, equity multiple) | `Analyst` |
| POST | `/re-underwriting/scenarios/{id}/debt-sizing` | Run debt sizing against this scenario | `Analyst` |
| GET | `/re-underwriting/scenarios/{id}/debt-sizing` | List debt sizings for a scenario | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/scenarios/{id}/waterfall` | Run a waterfall split against this scenario | `Analyst` |
| GET | `/re-underwriting/scenarios/{id}/waterfall` | List waterfalls for a scenario | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/deals/{id}/ic-memos` | Create an IC memo pinned to a computed scenario (OCC-guarded on `deal.version` via `expected_deal_version`) | `Analyst` |
| GET | `/re-underwriting/deals/{id}/ic-memos` | List IC memos for a deal (filterable by `status`, `scenario_id`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/ic-memos` | Flat list of all IC memos (filterable by `status`, `scenario_id`, `deal_id`) | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| GET | `/re-underwriting/ic-memos/{id}` | Fetch a single IC memo | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/ic-memos/{id}/submit` | Submit memo (`DRAFT → SUBMITTED`) | `Analyst` |
| POST | `/re-underwriting/ic-memos/{id}/vote` | Cast a `YES`/`NO`/`ABSTAIN` vote on a memo in `UNDER_VOTE` | `IC_Member`, `IC_Chair` |
| POST | `/re-underwriting/ic-memos/{id}/reject` | IC Chair override: force memo to `REJECTED` | `IC_Chair` |
| GET | `/re-underwriting/ic-memos/{id}/votes` | List votes cast on a memo | `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin` |
| POST | `/re-underwriting/_clock/set_current_utc` | Test-driving endpoint: set the server's logical UTC clock; startup default is `2026-08-01T00:00:00Z` | `Admin` |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_DEAL_CODE` | 409 |
| `ERR_DUPLICATE_PERIOD` | 409 |
| `ERR_NONMONOTONIC_PERIOD` | 422 |
| `ERR_FUTURE_PERIOD` | 422 |
| `ERR_ASSUMPTION_MISMATCH` | 422 |
| `ERR_SCENARIO_NOT_COMPUTED` | 422 |
| `ERR_NOI_NONPOSITIVE` | 422 |
| `ERR_PROMOTE_REGRESSIVE` | 422 |
| `ERR_DUPLICATE_VOTE` | 409 |
| `ERR_SEG_DUTIES` | 403 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INTERNAL` | 500 |
