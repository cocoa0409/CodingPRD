# Robo-Advisor Tax-Loss Harvesting API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for an automated investment-management platform that performs tax-loss harvesting on behalf of advised clients. The platform's central job is to keep each client's holdings aligned with a model portfolio's target asset allocation while opportunistically realizing investment losses to offset taxable gains — all without running afoul of the Internal Revenue Service's wash-sale rule, which disallows a loss when a substantially identical security is repurchased within a thirty-day window around the sale.

The system models the full lifecycle of an advised account: a prospective client is profiled by a risk questionnaire, the questionnaire's weighted score selects a model portfolio whose risk band contains that score, and acceptance of the questionnaire activates the account against the chosen model. From there the platform tracks every purchase as an immutable tax lot in a cost-basis ledger, continuously recomputes the account's allocation drift, flags accounts for quarterly rebalancing when drift crosses the model's threshold, and lets advisors harvest losing lots by selling them and immediately buying a correlation-screened replacement security with the proceeds. Because each harvest and rebalance mutates cash, opens and closes lots, and recomputes drift, the platform serializes those mutations with optimistic concurrency control on the account, and it provides a compliance oversight role that can freeze accounts, reject or reverse harvests, and delist securities. At year end, the platform produces a 1099-B tax form summarizing every disposed lot, its proceeds and basis, and any wash-sale disallowance carried into the following year.

Two operational roles drive the platform: an advisory role that constructs and operates accounts, and a compliance role that supervises them. The remainder of this document defines the global contract every request obeys (Section 2), the business logic and workflows that govern each entity's behavior (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. A request missing either header, or carrying an `X-User-Role` that is not one of the two recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly two roles, spelled `Advisor` and `Compliance`. The `Advisor` role manages accounts, model portfolios, questionnaires, tax lots, harvests, rebalances, and tax forms. The `Compliance` role provides oversight: it freezes and unfreezes accounts, rejects and reverses harvests, delists securities, and audits the system. Some operations are shared between the two roles, as detailed in the endpoint table of Section 4.

Both roles are operator identities rather than client identities. When `X-User-Role` is `Advisor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `Compliance`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded for audit but never matched against an entity's `id`. Consequently, ownership of a client account is established by the account's own `client_email` and foreign-key references, never by the acting user header.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits, recording when the resource was first created.

Most resources additionally carry an `updated_at` timestamp — an ISO 8601 UTC value refreshed on every mutation — and a `version`, an integer that begins at 1 on creation and increments by one with every subsequent mutation. The securities catalog, model portfolios, accounts, tax lots, harvest events, rebalance events, and 1099-B forms all carry both `updated_at` and `version`.

The risk questionnaire is the sole exception: it carries only `id` and `created_at`. A questionnaire has no `updated_at` and no `version`. A questionnaire's computed score is immutable once written, and its lifecycle is driven entirely through state transitions on the owning account rather than through versioned edits of its own fields.

### 2.5. Nested Path Resolution and Resource Existence

The platform uses a flat, multi-collection topology: each entity type is its own top-level collection, and resources reference one another through foreign-key fields carried in request bodies rather than through deeply nested URL paths. Whenever a request names a resource — whether by an identifier in the path or by a foreign-key identifier in the body — the server validates those identifiers left-to-right and rejects the first one that does not resolve to an existing entity with `ERR_NOT_FOUND`. For an operation such as proposing a harvest, this means the account, the source lot, and the replacement security are each resolved in turn, and a missing account surfaces before a missing lot, which surfaces before a missing security.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents; the API never represents money as a fractional dollar string. Wherever a calculation produces a non-integer cent value — for example, when multiplying a fractional share quantity by a per-share price, or when apportioning a disallowed loss — the result is rounded half up to the nearest whole cent. Percentage figures used in drift computation are likewise rounded half up to whole integer percentage points. Realized gains are signed integers (a loss is negative); disallowed-loss magnitudes are non-negative integers.

### 2.7. Drift, Allocation, and the Rebalance-Due Boundary

Each active account is continuously reconciled against its model portfolio's target allocation. The account's `invested_value_cents` is the sum, over every `OPEN` tax lot belonging to the account, of that lot's `market_value_cents`, where a lot's market value is the lot `quantity` multiplied by the current per-share `price_cents` of its security, rounded half up to whole cents. For each asset class named in the model's `targets`, the actual allocation percentage is 100 multiplied by the summed market value of that account's `OPEN` lots whose security belongs to the asset class, divided by `invested_value_cents`, rounded half up to a whole percentage point; when `invested_value_cents` is zero the actual percentage is zero. The per-asset-class drift is the absolute difference between that actual percentage and the asset class's `target_pct`. The account's `max_drift_pct` is the largest such drift across all asset classes, and it is zero when the account holds no `OPEN` lots.

An account becomes `REBALANCE_DUE` exactly when its `max_drift_pct` is greater than or equal to the model's `drift_threshold_pct`. The boundary is inclusive: a drift equal to the threshold triggers the flag, a drift one point below it does not. This reconciliation is recomputed whenever a tax lot opens or closes, whenever a security's price is updated, when a rebalance or harvest executes, and when a questionnaire is accepted as a re-profile. Each such recomputation that changes the account independently mutates the account, refreshing its `updated_at` and incrementing its `version`.

### 2.8. The Cost-Basis Ledger and Account Value

The platform maintains a cost-basis ledger in which every purchase tranche is one immutable tax lot. An account's `cash_balance_cents` holds uninvested settled cash and defaults to zero at account creation; harvest proceeds and reinvestment remainders flow through it. The account's `total_value_cents` is the sum of `cash_balance_cents` and `invested_value_cents`. Two year-to-date ledgers ride on the account: `realized_gain_cents_ytd` is the signed sum of `realized_gain_cents` over `CLOSED` tax lots whose `disposed_at` falls in the current tax year (losses being negative), and `wash_sale_disallowed_cents_ytd` is the running sum of disallowed loss (in positive cents) deferred under the wash-sale rule in the current tax year. Both default to zero.

### 2.9. Optimistic Concurrency Control on the Account

Because a harvest or a rebalance moves cash, opens and closes lots, and recomputes drift, the two creation operations that begin those workflows are guarded by optimistic concurrency control against the owning account's `version`.

A request to propose a harvest event must carry `expected_account_version` holding the `version` of the account the client last observed. If another writer has advanced the account's `version` since that read — for instance, by executing a harvest or rebalance that legitimately moved cash, opened or closed lots, and recomputed drift — the proposing client's view of the account is stale, and the proposal is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), forcing the new harvest to be re-derived from fresh state. A request to plan a rebalance event must likewise carry `expected_account_version` matching the account's current `version`; if a prior harvest or rebalance has changed the holdings the plan was computed against, the stale plan would buy or sell the wrong quantities and is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Operations other than these two creation endpoints do not take a version field.

### 2.10. Validation Ordering

When more than one validation could fire on a single request, checks are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication is checked first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`. The server then resolves every referenced identifier, returning `ERR_NOT_FOUND` for the first that does not exist. For any creation request the body is then validated for well-formedness — required fields present, enum members valid, numeric ranges respected — yielding `ERR_INVALID_REQUEST` when violated, followed by uniqueness checks that yield `ERR_DUPLICATE_RESOURCE`. Only after these generic gates does the server evaluate state-machine eligibility and the domain-specific business rules described in Section 3; among those, an account's operability gate and the account-status-versus-transition checks precede the wash-sale and lot-eligibility checks, and the optimistic-concurrency check on `expected_account_version` is evaluated against an otherwise admissible create. The detailed trigger conditions for each domain error live alongside the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Building the Investable Universe: Securities and Model Portfolios

Before any client can be served, the platform must hold a catalog of tradable securities and at least one model portfolio. A security is created with a `ticker` — a trading symbol such as VTI that must be uppercase and unique across all securities — together with an `asset_class`, a current per-share `price_cents`, and an optional `correlated_with` map. The `asset_class` is one of `US_EQUITY`, `INTL_EQUITY`, `BOND`, `REIT`, or `COMMODITY`. The `price_cents` must be at least 1. The `correlated_with` value is an array of objects, each pairing a `ticker` with a `correlation` — a float between -1.0 and 1.0 inclusive expressing how closely that other security tracks this one; this map is what lets the harvesting engine pick a wash-sale-safe replacement. Upon creation a security's `is_active` flag is set to true; the flag stays true until the security is delisted, and a delisted security can no longer be bought. Attempting to create a security whose `ticker` already exists is rejected with `ERR_DUPLICATE_RESOURCE`.

Updating a security's price is a first-class operation because price drives both market values and drift. When the `price_cents` of a security is updated, every account holding `OPEN` lots in that security has its market values, `invested_value_cents`, and drift recomputed, and any such account may auto-transition between `ACTIVE` and `REBALANCE_DUE` according to the drift boundary of §2.7. Delisting a security sets its `is_active` flag to false, after which it can no longer be bought as a replacement.

A model portfolio is created with a `name`, an inclusive `min_risk_score` and `max_risk_score` (each in the range 0 through 100, with `max_risk_score` greater than or equal to `min_risk_score`) defining the band of risk scores the model serves, a `targets` array, a `drift_threshold_pct`, and an optional `lot_selection`. Each entry in `targets` pairs an `asset_class` with an integer `target_pct`, and the `target_pct` values must sum to exactly 100; a model whose targets do not sum to 100 is rejected with `ERR_INVALID_REQUEST`. The `drift_threshold_pct` is the per-asset-class absolute drift, in percentage points, at or above which an account on this model is flagged `REBALANCE_DUE`, and it must be at least 1. The `lot_selection` enum is either `FIFO` or `HIFO` and defaults to `FIFO` when omitted; it governs the order in which lots are consumed on a partial sell, as described in §3.6. Upon creation a model's `is_active` flag is true. A model may later be retired, which sets `is_active` to false: a retired model keeps serving accounts already assigned to it but accepts no new assignments.

### 3.2. Profiling the Client: Risk Questionnaire and Account Activation

A client relationship begins when an advisor opens an account by supplying a `client_email`, which must be unique across all accounts; a duplicate email is rejected with `ERR_DUPLICATE_RESOURCE`. A freshly opened account starts in `PENDING_PROFILE` status with `cash_balance_cents` of zero, a `version` of 1, and a `model_portfolio_id` and `risk_score` of null until the first questionnaire is accepted.

To profile the account, an advisor submits a risk questionnaire that references the account through its `account_id` and carries four self-reported inputs: `horizon_years` (the investment horizon, 0 through 50), `loss_tolerance` (0 through 10), `liquidity_need` (a near-term cash need where higher means more cash needed, 0 through 10), and `income_band` (an income band code, 0 through 10). On submission the server computes a `risk_score` and resolves an `assigned_model_portfolio_id`, and the questionnaire is recorded in `SCORED` status.

The score is a weighted blend. The horizon contribution is the horizon weight times the smaller of `horizon_years` and 30, divided by 30, times 100. The tolerance contribution is the tolerance weight times `loss_tolerance` divided by 10, times 100. The income contribution is the income weight times `income_band` divided by 10, times 100. The liquidity contribution is the liquidity weight times `liquidity_need` divided by 10, times 100, and it is subtracted from the sum of the other three. The horizon and tolerance weights are each 0.35, the income weight is 0.20, and the liquidity weight is 0.10. The four terms are combined into a single raw value as one expression — all four terms first, then a single rounding — because rounding each term individually would drift the result; the raw value is rounded half up to an integer and then clamped to lie between 0 and 100 inclusive, producing `risk_score`.

The `assigned_model_portfolio_id` is the active model portfolio whose inclusive `[min_risk_score, max_risk_score]` band contains the computed `risk_score`. When two active models both contain the score, the platform picks the one with the smaller band width — that is, the smaller value of `max_risk_score` minus `min_risk_score` — and breaks any remaining tie by choosing the model created earliest (`created_at` ascending). If no active model's band contains the score, the submission is rejected with `ERR_NO_MODEL_FOR_SCORE`.

Accepting a `SCORED` questionnaire is what activates or re-profiles the account, and it is reserved to an advisor. Acceptance is permitted only while the questionnaire is in `SCORED` status — accepting a questionnaire that is not `SCORED` is rejected with `ERR_INVALID_STATE` — and only while the model named by its `assigned_model_portfolio_id` is still active; accepting a questionnaire whose assigned model has been retired is rejected with `ERR_MODEL_RETIRED`. When a questionnaire is accepted for an account still in `PENDING_PROFILE`, the account's `model_portfolio_id` is set to the questionnaire's `assigned_model_portfolio_id`, its `risk_score` is set to the questionnaire's `risk_score`, the questionnaire moves to `ACCEPTED`, the account advances from `PENDING_PROFILE` to `ACTIVE`, and the account's `version` increments by one. When a questionnaire is accepted for an account that is already `ACTIVE` (a re-profile), any prior `ACCEPTED` questionnaire for that account is moved to `SUPERSEDED`, the account's `model_portfolio_id` and `risk_score` are updated from the new questionnaire, `max_drift_pct` is recomputed against the new model's targets, and the account's `version` increments by one; if that recomputed `max_drift_pct` is at or above the new model's `drift_threshold_pct` the account lands in `REBALANCE_DUE` rather than `ACTIVE`. A questionnaire that has reached `SUPERSEDED` is terminal and admits no further acceptance.

### 3.3. Opening Tax Lots and the Drift Bubble-Up

With an account active, an advisor opens tax lots to build the holdings. A tax lot is created against an `account_id` and a `security_id`, with a `quantity` of shares (which must be greater than 0) and a `cost_basis_cents` representing the total acquisition cost of the whole lot, not the per-share cost (which must be at least 1). At creation the lot's `acquired_at` is stamped from the server clock, its `status` is `OPEN`, its `disposed_at` and `proceeds_cents` are null, and its `closed_by_harvest_id` is null. While the lot is `OPEN`, its `market_value_cents` is the lot's `quantity` multiplied by the security's current `price_cents` rounded half up to whole cents, and its `unrealized_gain_cents` is that market value minus `cost_basis_cents`. Once a lot is `CLOSED`, both its `market_value_cents` and `unrealized_gain_cents` are reported as 0, and its `realized_gain_cents` — null while `OPEN` — is fixed at its `proceeds_cents` minus `cost_basis_cents`. A lot also carries a `wash_sale_disallowed_cents` field, which records the portion of a realized loss disallowed under the wash-sale rule at close; it is 0 when no disallowance applies.

Opening a lot is a holdings change, so it triggers the drift recomputation of §2.7: the account's `invested_value_cents` and `max_drift_pct` are recomputed, the account may auto-transition between `ACTIVE` and `REBALANCE_DUE`, and the account's `version` increments by one. The same bubble-up occurs whenever a lot closes.

### 3.4. The Tax-Loss Harvest: Proposal, Screening, and the Execute Cascade

A harvest is the platform's signature operation, and it proceeds in two acts: an advisor first proposes it, then an advisor executes it. Proposing a harvest event names the `account_id`, the `source_lot_id` of the `OPEN` losing lot to be sold, and a `replacement_security_id` to buy with the proceeds, and it carries `expected_account_version` for the optimistic-concurrency guard of §2.9. A successful proposal records the event in `PROPOSED` status with `realized_loss_cents`, `disallowed_loss_cents`, and `replacement_lot_id` not yet populated. Proposal against an account whose `version` no longer matches `expected_account_version` is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Proposal and execution both require the owning account to be operable — its `status` must be `ACTIVE` or `REBALANCE_DUE`; an account that is `FROZEN`, `CLOSED`, or `PENDING_PROFILE` cannot be harvested, and the attempt is rejected with `ERR_ACCOUNT_NOT_OPERABLE`.

Executing a proposed harvest is where the screening and the cascade happen, and it advances the event from `PROPOSED` to `EXECUTED`. Execution is allowed only on an event still in `PROPOSED` status (otherwise `ERR_INVALID_STATE`) and re-verifies the optimistic-concurrency match on the account version (otherwise `ERR_STALE_ACCOUNT_VERSION`). Several eligibility screens then run. The source lot must be `OPEN` and must belong to the named account. The lot must genuinely be a loss lot — its `unrealized_gain_cents` must be less than zero — or execution is rejected with `ERR_NOT_A_LOSS_LOT`. The replacement security must still be active, or the harvest is rejected with `ERR_SECURITY_DELISTED`. The replacement security must not be the same security as the source lot's security, since selling and immediately rebuying the identical security is the very wash sale the platform exists to avoid; an identical replacement is rejected with `ERR_SUBSTANTIALLY_IDENTICAL`. Finally, the replacement must be sufficiently uncorrelated with the sold security: the absolute value of the correlation between the source lot's security and the replacement security must be at most the maximum replacement correlation the platform permits, which is 0.95; a replacement whose absolute correlation exceeds 0.95 is rejected with `ERR_REPLACEMENT_TOO_CORRELATED` because it would be a wash-sale-equivalent substitute.

When every screen passes, the execute step runs a strictly ordered cascade. First, the source lot is closed: its `disposed_at` is stamped with the current clock instant, its `proceeds_cents` is set to the lot's market value at the moment of sale, its `realized_gain_cents` is computed as proceeds minus cost basis (a negative number for a loss), and its `closed_by_harvest_id` is set to this harvest event; the event's `realized_loss_cents` records the positive magnitude of that loss, namely cost basis minus proceeds. Second, that close triggers the wash-sale scan described in §3.5, which may set the source lot's `wash_sale_disallowed_cents` and increase a surviving in-window lot's cost basis; the event's `disallowed_loss_cents` records the disallowed magnitude, which is 0 when the replacement and window are clean. Third, the wash-sale recompute updates the account's `wash_sale_disallowed_cents_ytd` and its `realized_gain_cents_ytd` (the loss net of any disallowance). The platform then opens the replacement lot: a new `OPEN` tax lot in the replacement security whose `quantity` is the proceeds in cents divided by the replacement security's `price_cents`, taking the whole-number floor, and whose `cost_basis_cents` is that quantity multiplied by the price; whatever proceeds remain after buying whole shares are credited back to the account's `cash_balance_cents` as automatic reinvestment, and the new lot's `id` becomes the event's `replacement_lot_id`. Finally the account's `invested_value_cents` and `max_drift_pct` are recomputed and the account auto-transitions between `ACTIVE` and `REBALANCE_DUE` per the drift boundary, the event moves to `EXECUTED`, and the account's `version` increments by one.

Harvesting is permitted whether the account is `ACTIVE` or `REBALANCE_DUE`. Executing a harvest on an `ACTIVE` account leaves it `ACTIVE` when the recomputed `max_drift_pct` remains below the model's `drift_threshold_pct`. Executing a harvest on a `REBALANCE_DUE` account leaves it `REBALANCE_DUE`: a harvest does not by itself clear the drift flag, because the drift remains unresolved until a rebalance runs.

### 3.5. The Wash-Sale Rule and Loss Disallowance

The wash-sale rule disallows a realized loss to the extent a substantially identical purchase occurred close in time to the sale. The platform applies this rule whenever a lot is closed at a loss — both at the second hop of a harvest execution and on any loss-generating sell during a rebalance. Gains are never disallowed.

The window spans from the disposal instant minus the wash-sale day count to the disposal instant plus the wash-sale day count, inclusive of both ends, where the wash-sale day count is 30 days. A triggering replacement purchase is any other `OPEN` tax lot in the same security as the closing lot whose `acquired_at` falls inside that window. (The harvest's own freshly bought replacement is, by construction, in a different and sufficiently uncorrelated security, so it never triggers a disallowance against the lot being sold.) The disallowed amount is the smaller of the absolute realized loss and the value obtained by taking the in-window replacement shares divided by the closing lot's shares, multiplying by the absolute realized loss, and rounding half up to whole cents — where the in-window replacement shares is the total shares purchased in-window in that security, capped at the closing lot's share count. The disallowance has three effects: the closing lot's `wash_sale_disallowed_cents` is set to the disallowed amount; the in-window replacement lot's `cost_basis_cents` is increased by that same amount as a basis carryover; and the net realized loss recognized in the current year is the realized loss plus the disallowed amount — since the loss is negative, adding the positive disallowance moves the recognized loss back toward zero.

### 3.6. Quarterly Rebalancing and Lot-Selection Variants

When an account's drift has pushed it to `REBALANCE_DUE`, an advisor restores the target allocation through a rebalance. Planning a rebalance event names the `account_id`, a `quarter_label` tag matching the pattern of a four-digit year, a hyphen, the letter Q, and a quarter number (for example 2026-Q2), and an `expected_account_version` for the optimistic-concurrency guard of §2.9. A stale account version is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Planning, like harvest proposal, requires the account to be operable — `ACTIVE` or `REBALANCE_DUE`, never `FROZEN`, `CLOSED`, or `PENDING_PROFILE` — failing which the plan is rejected with `ERR_ACCOUNT_NOT_OPERABLE`. A successful plan is recorded in `PLANNED` status with `trades_count` and `cash_consumed_cents` at zero.

Executing a planned rebalance is reserved to an advisor and drives the account from `REBALANCE_DUE` back to `ACTIVE`. Execution requires that the event be in `PLANNED` status (otherwise `ERR_INVALID_STATE`), that the account's `status` be `REBALANCE_DUE` at execution time (an attempt while the account is not `REBALANCE_DUE` is rejected with `ERR_NOT_REBALANCE_DUE`), that `expected_account_version` still match the account's current `version` (otherwise `ERR_STALE_ACCOUNT_VERSION`), and that no already-`EXECUTED` rebalance for this account shares the same `quarter_label` — a repeated quarter is rejected with `ERR_QUARTER_ALREADY_REBALANCED`, since a `quarter_label` is unique per account among executed rebalances. On execution the platform generates the buys and sells needed to drive every asset class's drift below the model's `drift_threshold_pct`; the account's `cash_balance_cents` is decreased by the cash spent on buys and credited with the proceeds of sells, the account's `max_drift_pct` is recomputed, the account's `status` becomes `ACTIVE`, the event's `trades_count` and `cash_consumed_cents` are recorded (the latter being the cash spent on buys during this rebalance), the event moves to `EXECUTED`, and the account's `version` increments by one. A planned rebalance that is no longer wanted may instead be cancelled by an advisor, which moves the event to `CANCELLED` with no ledger changes.

Whenever a rebalance must sell a number of shares of a security that is held across more than one `OPEN` lot, the lots are consumed in a pinned order, and the realized gain is the sum over the consumed lots of the proceeds for the consumed portion minus the cost basis for that portion. The order depends on the model's `lot_selection`. Under the default `FIFO` variant — in effect whenever `lot_selection` is unset or `FIFO` — the oldest lots are consumed first, ordered by `acquired_at` ascending and breaking ties by `created_at` ascending; in a rising market this typically realizes larger gains. Under the `HIFO` variant — in effect when `lot_selection` is `HIFO` — the lots with the highest per-share cost basis are consumed first, ordered by `cost_basis_cents` divided by `quantity` descending, breaking ties by `acquired_at` ascending and then `created_at` ascending; this minimizes the realized gain and maximizes the harvested loss. Because the two variants select different lots for the same partial sell, they realize different `realized_gain_cents` on identical holdings. When a lot is closed directly by id, as in a harvest, the realized gain is simply that lot's `proceeds_cents` minus its `cost_basis_cents`; proceeds are rounded half up to whole cents and gains are reported as signed integers.

### 3.7. Compliance Oversight: Freezing, Rejecting, and Reversing

The compliance role supervises the platform's activity and can intervene at several points. A compliance operator may freeze an `ACTIVE` or `REBALANCE_DUE` account, setting its `status` to `FROZEN` and incrementing its `version`; while frozen, an account blocks all harvests and rebalances. Unfreezing a frozen account recomputes its `max_drift_pct` and lands it in `REBALANCE_DUE` if that drift is at or above the model's `drift_threshold_pct`, otherwise in `ACTIVE`, again incrementing the account's `version`.

A proposed harvest may be rejected by a compliance operator before it executes; rejection moves the event from `PROPOSED` to `REJECTED` with no ledger changes. An already-executed harvest may instead be reversed by a compliance operator, provided the owning account is not `CLOSED`. Reversal is a compensating undo that moves the event from `EXECUTED` to `REVERSED`: the replacement lot is closed with proceeds equal to its market value and the cash for its shares returned, the source lot is reopened to `OPEN` with its `disposed_at`, `proceeds_cents`, and `realized_gain_cents` cleared, the wash-sale disallowance applied at execution is unwound so that the account's `wash_sale_disallowed_cents_ytd` and `realized_gain_cents_ytd` are restored to their pre-harvest values and any cost-basis carryover bumped onto a survivor lot is undone, and the account's `version` increments by one. The reversal is exact: the account's `total_value_cents` returns to precisely its pre-harvest value.

### 3.8. Closing an Account

An advisor closes an account once the relationship ends, but only after the holdings have been fully liquidated. Closing requires that no `OPEN` tax lot remains for the account; an attempt to close while any open lot survives is rejected with `ERR_OPEN_LOTS_REMAIN`. A successful close moves the account's `status` to `CLOSED` and increments its `version`. `CLOSED` is terminal and blocks all further mutation of the account.

### 3.9. Year-End Reporting: The 1099-B Tax Form

At year end, an advisor or compliance operator generates a 1099-B tax form for an account and a `tax_year` (a calendar year between 2000 and 2100 inclusive). On creation the form is recorded in `DRAFT` status and its totals are computed; the totals continue to be recomputed while the form remains in `DRAFT`. The reportable lots are the `CLOSED` tax lots belonging to the form's account whose `disposed_at` calendar year equals the `tax_year`, and the form reports exactly one 1099-B line per reportable lot. The `total_proceeds_cents` is the sum of `proceeds_cents` over the reportable lots; the `total_cost_basis_cents` is the sum of `cost_basis_cents` over the reportable lots; the `total_wash_sale_disallowed_cents` is the sum of `wash_sale_disallowed_cents` over the reportable lots; the `net_realized_gain_cents` is the total proceeds minus the total cost basis, plus the total wash-sale disallowed losses added back; and the `line_count` is the count of reportable lots. Lines are ordered by `disposed_at` ascending, breaking ties by `created_at` ascending. All these figures are integer cents throughout.

Finalizing a form freezes its totals into an immutable snapshot and moves it from `DRAFT` to `FINALIZED`. A form may only be finalized once its `tax_year` is strictly before the clock's current calendar year — a year that is the current calendar year or later is not yet closed and the attempt is rejected with `ERR_TAX_YEAR_NOT_CLOSED`. A `FINALIZED` form is immutable.

### 3.10. The Test-Driving Clock

The platform's notion of "now" is supplied by a logical clock, which the test harness can set explicitly. A clock-setting capability accepts a `to_iso8601` instant and advances or resets the server's current UTC to it, returning the new `current_utc`. Because the clock drives `acquired_at` stamping, `disposed_at` stamping, the wash-sale window arithmetic, and the tax-year gate on form finalization, controlling it lets a caller exercise time-dependent behavior deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, price updates, freezes, and finalizations — return a `200 OK` status code. All list and single-resource read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/securities` | Create a tradable security in the catalog | Advisor, Compliance |
| GET | `/securities/{id}` | Get one security | Advisor, Compliance |
| GET | `/securities` | List securities (paginated; filter by asset class) | Advisor, Compliance |
| PATCH | `/securities/{id}/price` | Update a security's current price | Advisor, Compliance |
| POST | `/securities/{id}/delist` | Delist a security | Compliance |
| POST | `/model-portfolios` | Create a model portfolio | Advisor |
| GET | `/model-portfolios/{id}` | Get one model portfolio | Advisor, Compliance |
| GET | `/model-portfolios` | List model portfolios (paginated) | Advisor, Compliance |
| POST | `/model-portfolios/{id}/retire` | Retire a model portfolio | Advisor |
| POST | `/accounts` | Open a new client account | Advisor |
| GET | `/accounts/{id}` | Get one account with all computed fields | Advisor, Compliance |
| GET | `/accounts` | List accounts (paginated; filter by status, model portfolio) | Advisor, Compliance |
| POST | `/accounts/{id}/freeze` | Compliance freeze | Compliance |
| POST | `/accounts/{id}/unfreeze` | Lift a compliance freeze | Compliance |
| POST | `/accounts/{id}/close` | Close an account | Advisor |
| POST | `/questionnaires` | Submit and score a risk questionnaire | Advisor |
| GET | `/questionnaires/{id}` | Get one questionnaire | Advisor, Compliance |
| GET | `/questionnaires` | List questionnaires (filter by account, model, status) | Advisor, Compliance |
| POST | `/questionnaires/{id}/accept` | Accept a scored questionnaire and activate the account | Advisor |
| POST | `/tax-lots` | Open a tax lot on an account | Advisor |
| GET | `/tax-lots/{id}` | Get one tax lot with computed gain fields | Advisor, Compliance |
| GET | `/tax-lots` | List tax lots (filter by account, security, harvest, status) | Advisor, Compliance |
| POST | `/harvest-events` | Propose a tax-loss harvest | Advisor |
| GET | `/harvest-events/{id}` | Get one harvest event | Advisor, Compliance |
| GET | `/harvest-events` | List harvest events (filter by account, lots, security, status) | Advisor, Compliance |
| POST | `/harvest-events/{id}/execute` | Execute a proposed harvest | Advisor |
| POST | `/harvest-events/{id}/reject` | Reject a proposed harvest | Compliance |
| POST | `/harvest-events/{id}/reverse` | Reverse an executed harvest | Compliance |
| POST | `/rebalance-events` | Plan a quarterly rebalance | Advisor |
| GET | `/rebalance-events/{id}` | Get one rebalance event | Advisor, Compliance |
| GET | `/rebalance-events` | List rebalance events (filter by account, status) | Advisor, Compliance |
| POST | `/rebalance-events/{id}/execute` | Execute a planned rebalance | Advisor |
| POST | `/rebalance-events/{id}/cancel` | Cancel a planned rebalance | Advisor |
| POST | `/tax-forms` | Generate a draft 1099-B for an account and tax year | Advisor, Compliance |
| GET | `/tax-forms/{id}` | Get one 1099-B | Advisor, Compliance |
| GET | `/tax-forms` | List 1099-B forms (filter by account, tax year, status) | Advisor, Compliance |
| POST | `/tax-forms/{id}/finalize` | Finalize a draft 1099-B | Advisor, Compliance |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | Advisor, Compliance |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_OPERABLE` | 409 Conflict |
| `ERR_NOT_REBALANCE_DUE` | 409 Conflict |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_NOT_A_LOSS_LOT` | 409 Conflict |
| `ERR_SUBSTANTIALLY_IDENTICAL` | 409 Conflict |
| `ERR_REPLACEMENT_TOO_CORRELATED` | 409 Conflict |
| `ERR_SECURITY_DELISTED` | 409 Conflict |
| `ERR_NO_MODEL_FOR_SCORE` | 409 Conflict |
| `ERR_MODEL_RETIRED` | 409 Conflict |
| `ERR_QUARTER_ALREADY_REBALANCED` | 409 Conflict |
| `ERR_OPEN_LOTS_REMAIN` | 409 Conflict |
| `ERR_TAX_YEAR_NOT_CLOSED` | 409 Conflict |
