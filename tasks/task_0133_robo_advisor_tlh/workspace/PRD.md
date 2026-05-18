# Robo-Advisor Tlh API — Product Requirements Document

## 1. Introduction

Modern retail investors expect their accounts to do three things automatically: stay aligned with their risk tolerance, harvest losses for tax benefit without breaking IRS regulations, and produce defensible tax forms at year end. The Robo-Advisor Tax-Loss Harvesting platform consolidates those three responsibilities into one back-end so that an advisor's operational cost per client falls without sacrificing regulatory rigor.

Operationally, the platform must score each client's risk profile from a short questionnaire, match the resulting risk band against a time-horizon band to assign a model portfolio, and then keep the actual asset mix within a tight tolerance of that model's targets through quarterly rebalancing. Loss harvesting runs on its own cadence: when an individual position's mark-to-market loss crosses a threshold, the system flags a harvest opportunity and proposes a correlated but **not** substantially identical replacement. Every sell is then policed against the IRS Wash Sale rule, which symmetrically forbids the purchase of a substantially identical security within thirty calendar days on either side of the realized loss; matched losses are disallowed and folded back into the replacement's cost basis. At year end, a 1099-B form aggregates settled sells into short-term and long-term buckets with an explicit pinned rounding order so that the issued numbers reconcile to the trade ledger to the cent.

Because all of these flows touch the same money and the same lots, the system runs on **immediate consistency** — every state change, basis adjustment, and drift recompute settles within the originating API call. This document specifies the request contract, the workflows, and the error contract that every implementation of this back-end must satisfy.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. Either header missing or malformed yields `ERR_AUTH_MISSING` with HTTP 401. If the role string is present but is not one of the recognised role names, or if the role exists but lacks permission for the requested operation per the §1.7 matrix in this document and §4 below, the response is `ERR_AUTH_FORBIDDEN` with HTTP 403. Entity-backed roles whose `X-User-ID` does not resolve to an actual stored backing entity instance receive `ERR_AUTH_IDENTITY_UNKNOWN`, also 403.

Five roles exist, with the spellings shown: `ClientUser`, `Advisor`, `ComplianceOfficer`, `TaxAdmin`, and `system`.

When `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` (the client's own `Account`, the trades, positions, harvest opportunities, and forms beneath each `Account`) compare the resource's `client_id` foreign-key field to `X-User-ID`. A `ClientUser` may only act on the client whose `id` equals their `X-User-ID`. When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of the acting `Advisor` entity; advisor-side operations are scoped to advisors assigned to the relevant client (the platform records but does not over-enforce the assignment graph for endpoints listed as `Advisor`-permitted). When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The same opaque rule applies when `X-User-Role` is `TaxAdmin` (1099-B preparation) and when `X-User-Role` is `system` (automated runners exposed via the test-driving endpoints listed in §4).

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

List endpoints accept two optional query parameters, `limit` and `offset`. The default `limit` is 10 when omitted, the minimum is 1, and the maximum is 100. The default `offset` is 0 and it must be a non-negative integer. Any value of `limit` outside the inclusive range one through one hundred, or any negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422). List responses are sorted by `created_at` ascending unless a specific subsection states otherwise. The `meta` envelope on list responses exposes `limit`, `offset`, `total_count` (the unpaginated total), and `has_more` (true when more rows remain after this page).

### 2.4. Common Resource Properties and Versioning

Every persisted entity receives a server-minted `id` that is a plain UUID with no type prefix. Entities marked as carrying common audit fields — `Client`, `Account`, `Position`, `Lot`, `Trade`, `HarvestOpportunity`, `RebalanceRun`, `Form1099B` — additionally carry `created_at`, `updated_at`, and `version`. `created_at` is the ISO 8601 UTC timestamp of row creation with three fractional digits; `updated_at` is the same format and is refreshed on every mutating write; `version` is an integer that starts at 1 and increments by one on every mutation.

Append-only or immutable association entities — `RiskQuestionnaire`, `ModelPortfolio`, `Security`, `CorrelationLink`, `WashSaleEvent`, `DividendEvent` — carry only `id` and `created_at`; both `updated_at` and `version` are absent on those rows because they are written once and never updated in place.

### 2.5. Optimistic Concurrency Control

Endpoints that mutate a versioned row (PATCH, PUT, and the cancel action that explicitly accepts `version` in its body) treat `version` in the request body as optional. When the caller omits the `version` field, the server applies the mutation without a concurrency check. When the caller supplies `version`, the server compares the submitted integer to the row's current `version`; on mismatch the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). A successful mutation always advances `version` by one and refreshes `updated_at`, whether or not `version` was supplied on the request.

### 2.6. Nested Resource Resolution

URL paths beyond the first segment, such as those addressing a trade or harvest opportunity beneath an account, are validated left-to-right. The outer `accountId` must resolve before the inner `tradeId` or `opportunityId` is inspected, and the inner identifier must in fact belong under the outer resource. A missing or non-matching path id at any step yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Body-side foreign keys — for example `client_id` on a new `Account` or `security_id` on a new trade — produce `ERR_FK_NOT_FOUND` (HTTP 422) when they reference rows that do not exist.

### 2.7. Validation Ordering

Several endpoints carry multiple checks that could all conceivably fail. The platform evaluates them in a fixed, layered priority so that an automated client can predict which error surfaces first. Authentication runs first: header presence and well-formedness (`ERR_AUTH_MISSING`), then role membership (`ERR_AUTH_FORBIDDEN`), then entity-backed identity resolution (`ERR_AUTH_IDENTITY_UNKNOWN`). Existence checks follow: path-parameter resolution (`ERR_RESOURCE_NOT_FOUND`) precedes body foreign-key resolution (`ERR_FK_NOT_FOUND`). State preconditions evaluated against §3 (`ERR_INVALID_STATE` and its trade-specific cousin `ERR_INVALID_TRADE_STATE` for the rebalance-child cancel guard) come next. Business safety and compliance fire before generic business constraints — the wash sale violation gate, the account-frozen gate, and the security-not-investable gate precede the constraint checks on lot shares, position shares, drift, harvest threshold, and so on. Pagination validation (`ERR_PAGINATION_INVALID`) runs at the GET list-endpoint layer.

Concretely: when a `BUY` execute is attempted on a frozen account whose security is also non-investable, the response is `ERR_ACCOUNT_FROZEN` rather than `ERR_SECURITY_NOT_INVESTABLE`, because the safety-tier compliance gate at priority nine wins over the referential-tier gate at priority ten. When the same call would additionally fail a wash sale check, the wash-sale check at priority eight wins over both. The fine-grained ordering of all twenty-four scaffold checks is preserved exactly as their priority numbers in §1.4 dictate.

### 2.8. Precision and Rounding

All monetary amounts are stored as whole-cent integers in fields suffixed `_cents`. The drift percentage `max_drift_pct` is stored to two decimal places (e.g., a value of 5.27 means 5.27 percentage points of absolute deviation). Every per-trade rounding follows **round half-up** to the next whole cent. The realized-gain-loss calculation applies a single rounding pass at the trade-level total — lot-level multiplications stay as raw integer-cent arithmetic, and only the per-trade `total_basis_cents` and per-trade `gross_proceeds_cents` are rounded. The wash sale basis adjustment rounds at each named per-share step (`loss_per_share`, `disallowed_for_cand`, `boost_per_share`) and does **not** round again at aggregation time. The 1099-B aggregation sums already-rounded per-trade integers and applies no further rounding (see §3 for the explicit pinned ordering and §2.8.1 below for the drift rule). Fractional share quantities — produced only by the dividend reinvestment path — are truncated to four decimal places.

#### 2.8.1. Drift percentage rounding

The drift recompute aggregates current asset-class weights against the assigned model portfolio's `target_allocation`, computes the absolute deviation per asset class in percentage points, takes the maximum across all five asset classes, and rounds the maximum half-up to two decimal places **once at the end**. Intermediate per-class weights are not rounded.

### 2.9. Hierarchical Consistency and Cascading Side Effects

Because state changes cascade across entities (a client suspension touches every account beneath it; a trade settlement touches the lot, the position, the wash-sale ledger, the drift recompute, and potentially a freshly-detected harvest opportunity), every cascade in §3 is **atomic and immediate within the originating API call**. When an endpoint's narrative says that settlement triggers basis adjustment and harvest detection, those steps complete before the response is returned. Every modified row receives a refreshed `updated_at` and a `version` increment in the same transaction.

### 2.10. The Wash Sale Window and Substantially Identical Grouping

Two securities are treated as **substantially identical** for IRS Wash Sale purposes when their `substantially_identical_group_id` matches; the field is the self-referential group key on `Security`. The wash sale window is symmetric and inclusive: thirty calendar days before through thirty calendar days after the calendar date of the realized loss, using UTC calendar dates. A buy that falls anywhere inside that closed sixty-one-day window on the same account and same group as a loss-realizing sell is a wash sale candidate. Two policy levers act on this window: a settle-time basis adjustment that always applies (a settled sell that realized a loss searches for already-settled buys within the window and shifts disallowed loss into their replacement lots), and a rebalance pre-flight `BLOCK` policy that prevents a rebalance child buy from being emitted into the window in the first place. The pre-flight rejection surfaces as `ERR_WASH_SALE_VIOLATION` at request time; the settle-time adjustment is silent at the API boundary but visible on the resulting `WashSaleEvent` row and on the boosted replacement lot.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Risk Profiling

A client begins life when a `ComplianceOfficer` creates them; the new `Client` row is born with `kyc_status` set to `PENDING` and `risk_band` null. Onboarding captures the client's legal `full_name` (between one and one hundred twenty characters), their `birth_date` as an ISO 8601 calendar date, and their investment `time_horizon_years` expressed as a whole-number count of years. The `time_horizon_years` value must be at least one and at most forty; values outside that inclusive range are rejected with `ERR_TIME_HORIZON_OUT_OF_RANGE`. The compliance officer may later update the name or horizon through a patch, with the same horizon validation in force and optimistic concurrency via `version` honoured when supplied; changing the horizon to a value that crosses a horizon-band boundary additionally re-runs the model assignment for every account the client owns.

Risk profiling is collected through a five-question questionnaire submitted under the client. Each of the five integer answers — `q1_loss_tolerance` (twenty-percent drawdown tolerance), `q2_volatility_comfort` (month-to-month swing comfort), `q3_growth_vs_stability` (growth preference), `q4_liquidity_need` (liquidity need, where lower means more liquid), and `q5_experience` (self-reported investment experience) — must be an integer in the inclusive range one through five. Any answer outside that range causes the entire submission to fail with `ERR_QUESTIONNAIRE_OUT_OF_RANGE`. A `ClientUser` may submit their own questionnaire only when the path's `clientId` equals their `X-User-ID`; a `ComplianceOfficer` may submit on the client's behalf. The submission records `client_id`, `submitted_at` (server clock), and an optional `scoring_method` whose default is `STANDARD` and whose other allowed value is `AGE_ADJUSTED`. If a compliance officer suspends the client in the same instant a questionnaire is being submitted, only one of the two actions can be the final state — the racing operations serialize first-writer-wins on the client's `kyc_status` read at submission time, so if suspension lands first the submission is rejected with `ERR_CLIENT_NOT_ACCEPTING_INPUT`, and if submission lands first it is accepted and the subsequent suspension still succeeds with the new submission marked as the latest.

The submission's `raw_score` and `assigned_band` are computed deterministically. For the `STANDARD` variant, all five questions weight equally at one, and a reverse-coding is applied to `q4_liquidity_need` so that a low liquidity need contributes a high score: the raw score equals one times `q1_loss_tolerance`, plus one times `q2_volatility_comfort`, plus one times `q3_growth_vs_stability`, plus one times the quantity six minus `q4_liquidity_need`, plus one times `q5_experience`. The raw score's natural range under `STANDARD` is therefore the integers five through twenty-five. Bucket boundaries map the raw score to the `assigned_band`: a raw score of ten or less assigns `CONSERVATIVE`; a raw score from eleven through seventeen assigns `MODERATE`; a raw score of eighteen or greater (and no higher than the maximum twenty-five) assigns `AGGRESSIVE`. The `raw_score` is stored as an integer; no rounding is applied because the inputs are integers.

The `AGE_ADJUSTED` variant applies only when the submitter selects `scoring_method` equal to `AGE_ADJUSTED` and the client's derived `age` is at least fifty-five years (the age-bias threshold). When both conditions hold, the variant uses the same formula except that the third term — the growth-vs-stability contribution — is replaced by one times the quantity six minus `q3_growth_vs_stability`, inverting the growth axis so that a higher growth preference for an older client lowers the raw score and biases the bucket toward stability. For the identical five answers, the `STANDARD` and `AGE_ADJUSTED` paths can land the client in different bands; the bucket boundaries above apply unchanged to the variant's raw score. The client's `age` is derived from `birth_date` against the latest clock epoch as the floor number of whole years and is recomputed on clock advance.

When the submission completes successfully, the client's `risk_band` field is overwritten with the freshly computed `assigned_band`. Until the first submission, `risk_band` remains null.

A `ComplianceOfficer` moves the client from `PENDING` to `ACTIVE` only after at least one `RiskQuestionnaire` has been submitted and `time_horizon_years` has been set; that activation step kicks the model assignment calculation, populating `model_portfolio_id` on every `Account` of the client where the field was previously null. From `ACTIVE`, a compliance officer may move the client to `SUSPENDED`; the suspension cascades into the per-account compliance dimension (every `Account` belonging to the suspended client transitions its `compliance_status` to `FROZEN_DOC_REVIEW`) and into the harvest pipeline (every `HarvestOpportunity` in `DETECTED` for those accounts transitions to `DISMISSED`). A subsequent reinstatement from `SUSPENDED` back to `ACTIVE` cascades the account-level `compliance_status` back to `ACTIVE`; harvest opportunities previously dismissed by the suspension do not reanimate (the cycle is per-position re-detection, not per-row revival).

### 3.2. Model Portfolios and Assignment

The set of admissible portfolios is configured by an `Advisor`. Each `ModelPortfolio` is keyed conceptually by a `risk_band` from the conservative-to-aggressive ladder, a `horizon_band` from short-to-long, and a `target_allocation` over the five fixed asset classes — `US_EQUITY`, `INTL_EQUITY`, `US_BOND`, `INTL_BOND`, `CASH`. The allocation is a mapping from asset class to a decimal weight between zero and one inclusive, and the five weights must sum to exactly one. Any individual weight outside the closed unit interval, or a sum that does not equal one, is rejected with `ERR_ALLOCATION_INVALID`. The `is_active` flag defaults to true and gates whether the model is selectable by the assignment calculation.

Assignment derives the horizon band from `time_horizon_years` using these tiers: `SHORT` covers years one through five, `MID` covers years six through fifteen, and `LONG` covers years sixteen through forty. Given the client's freshly computed `risk_band` and derived horizon band, the calculation selects the active `ModelPortfolio` whose stored `risk_band` matches the client's and whose stored `horizon_band` matches the derived band; when multiple actives qualify, the model with the lexicographically lowest `id` wins as a stable tie-breaker. Assignment runs on three occasions: at the client's `PENDING` to `ACTIVE` activation (populating any account that was null), through the dedicated reassignment capability listed in §4 (which a compliance officer also invokes after a horizon edit), and implicitly when a horizon-band-changing patch lands.

### 3.3. Accounts and the Parallel Status Dimensions

A `ComplianceOfficer` creates an `Account` under a client by supplying the parent `client_id`. The new account starts with `compliance_status` of `ACTIVE`, `investment_status` of `ACCUMULATING`, `model_portfolio_id` null, `cash_balance_cents` zero, and `max_drift_pct` of 0.00. The account carries **two parallel status dimensions** that evolve independently. The compliance dimension transitions between `ACTIVE` and `FROZEN_DOC_REVIEW` and is driven by compliance officers — directly through freeze and unfreeze capabilities on the account, or indirectly through the client-level suspend and reinstate cascades described above. The investment dimension transitions across `ACCUMULATING`, `REBALANCING`, and `HARVESTING` and is driven by system operations: a rebalance run takes the account from `ACCUMULATING` to `REBALANCING` on `SCHEDULED → IN_PROGRESS` and back to `ACCUMULATING` whenever the run reaches any of its three terminal states; an executed harvest opportunity takes the account from `ACCUMULATING` to `HARVESTING` and back to `ACCUMULATING` when all the harvest's associated trades reach terminal states.

Any mutating operation on an account or its children — trade creation, execute, settle, cancel, rebalance start, harvest approve, harvest execute, dividend recording, cash deposit — requires `compliance_status` of `ACTIVE`. A frozen account rejects the mutation with `ERR_ACCOUNT_FROZEN`.

Cash is credited to an account through the cash-deposit capability available to advisors and compliance officers; the deposit body carries an integer `amount_cents` that is added to `cash_balance_cents`, after which `recompute_drift` runs because the new cash position changes the `CASH` bucket's current weight. The account read returns `max_drift_pct` and `cash_balance_cents` along with the rest of the audit fields.

### 3.4. The Trade Lifecycle and Cost-Basis Methods

Trades are the unit of capital movement. A `Trade` is created in `PENDING` by an `Advisor` or a `ClientUser`, naming the target `security_id`, the `side` (`BUY` or `SELL`), the `requested_shares` (a positive number, fractional to four decimal places), and — for `SELL` only — an optional `cost_basis_method` that defaults to `FIFO` and whose other allowed value is `SPECIFIC_LOT`. When the method is `SPECIFIC_LOT`, a `specific_lot_id` must accompany the body and must resolve to a `Lot` whose `position_id` belongs to the same `Position` being sold and whose `shares_remaining` is at least the requested share count; otherwise the trade is rejected with `ERR_INSUFFICIENT_LOT_SHARES`. The `cost_basis_method` field is ignored on `BUY` trades. Trades emitted as the children of a rebalance run carry the originating run's id in `rebalance_run_id`; client-initiated trades leave that field null.

The transition from `PENDING` to `EXECUTED` is performed by an `Advisor` (or by the system for rebalance children). Execution requires the account's `compliance_status` to be `ACTIVE` and the trade to currently be in `PENDING`; trying to execute a trade that has already moved to `EXECUTED`, `SETTLED`, `CANCELLED`, or `REJECTED` is rejected with `ERR_INVALID_STATE`. For a `SELL`, the target position must have enough open shares to satisfy the request: when the method is `FIFO`, the sum of `shares_remaining` across all `OPEN` and `PARTIALLY_CLOSED` lots for the position must be at least `requested_shares` or the trade is rejected with `ERR_INSUFFICIENT_POSITION_SHARES`; when the method is `SPECIFIC_LOT`, the named `specific_lot_id` must still resolve with sufficient `shares_remaining` or the trade is rejected with `ERR_INSUFFICIENT_LOT_SHARES`. For a `BUY`, the target `Security` must be marked `is_investable` (otherwise `ERR_SECURITY_NOT_INVESTABLE`) and the account's `cash_balance_cents` must be at least the requested-shares times the execution price rounded half-up to whole cents (otherwise `ERR_INSUFFICIENT_CASH`). The execution step snapshots the security's current `last_price_cents` into the trade's `execution_price_cents`, records `executed_at` as the current clock, and — for `SELL` — runs the realized-gain-loss calculation on the spot: lots are consumed (transitioning from `OPEN` to `PARTIALLY_CLOSED` when only some shares are taken, or `OPEN`/`PARTIALLY_CLOSED` to `CLOSED` when the remainder is consumed), and `gross_proceeds_cents` and `realized_gain_loss_cents` are persisted on the trade. For a `BUY`, execution opens a new `Lot` in status `OPEN` with `shares_opened` equal to `requested_shares`, `unit_cost_cents` equal to the executed price, `buy_trade_id` linking back to the trade, and `acquired_at` equal to the execution timestamp; this `acquired_at` is what drives FIFO ordering and the short-versus-long-term holding-period classification.

When the rebalance run system or the manual execution path attempts to drive a trade through but a precondition fails, the trade falls into `REJECTED`; in that case, if the trade belongs to a parent `RebalanceRun`, the run is bubbled to `FAILED` unless the rejection cause is a wash-sale block (in which case the run terminates at `BLOCKED_BY_WASH_SALE` instead). Rejection does not cascade `version` changes onto unrelated rows; only the trade itself transitions.

A `PENDING` trade can also be cancelled. The cancel action requires the trade to still be in `PENDING` and to **not** be associated with a `RebalanceRun` — rebalance child trades cannot be cancelled individually, since the run owns their lifecycle. A cancel attempt that fails either condition surfaces as `ERR_INVALID_TRADE_STATE`. A `ClientUser` may cancel only their own client-initiated pending trades; an `Advisor` may cancel client-initiated trades as well. The cancel body accepts an optional `version` for optimistic concurrency. When a client cancel and an advisor execute race on the same `PENDING` trade, exactly one wins; the loser observes the trade in a terminal state and is rejected with `ERR_INVALID_TRADE_STATE`, with serialization first-writer-wins on `Trade.status`.

The transition from `EXECUTED` to `SETTLED` is invoked either per-trade through the dedicated settle capability or in batch through the system's settlement-sweep capability. Settlement requires the trade to be in `EXECUTED`. On settlement, `cash_balance_cents` is decremented (for a `BUY`) or incremented (for a `SELL`) by the trade's `gross_proceeds_cents`; the wash-sale basis adjustment runs for `SELL` trades that realized a loss; the affected `Position`'s `shares`, `total_cost_basis_cents`, and `market_value_cents` are recomputed; and the harvest-opportunity detection pass runs against the affected position. Recompute-drift runs on the account after settlement to refresh `max_drift_pct`.

### 3.5. Realized Gain/Loss: FIFO versus Specific-Lot

For a `SELL` trade, the realized P&L is computed at execution from the lot consumption order. Under the `FIFO` variant, the calculation gathers all `OPEN` and `PARTIALLY_CLOSED` lots belonging to the target `Position`, sorts them by `acquired_at` ascending with the lot `id` as a stable tie-breaker, and consumes from the oldest lot first. Under the `SPECIFIC_LOT` variant, the calculation acts only on the single `Lot` referenced by `specific_lot_id`, which must belong to the same `Position`; nothing else is consumed.

Consumption proceeds lot by lot in the chosen order. For each lot in turn, the system computes the number of shares to take as the lesser of the trade's remaining unsatisfied share count and the lot's current `shares_remaining`. The taken-shares quantity is multiplied by the lot's `adjusted_unit_cost_cents` and rounded half-up to whole cents; that rounded integer is added into a per-trade running total `total_basis_cents`. The lot's `shares_remaining` is decremented by the taken-share quantity, the trade's unsatisfied count is reduced accordingly, and the loop moves on; when the trade's unsatisfied count reaches zero, consumption stops. The per-trade `gross_proceeds_cents` is the trade's `requested_shares` multiplied by `execution_price_cents`, rounded half-up to whole cents in a single step. The per-trade `realized_gain_loss_cents` is `gross_proceeds_cents` minus `total_basis_cents`; a negative value denotes a realized loss. Rounding is applied **only once at the trade-level totals** — lot-level multiplications stay in integer-cent arithmetic until the running `total_basis_cents` rounds and `gross_proceeds_cents` rounds.

For identical inputs (same position, same share count, same price) the two variants typically diverge: `FIFO` consumes the chronologically oldest lot and `SPECIFIC_LOT` consumes the chosen lot, and the per-share `adjusted_unit_cost_cents` of the two lots differ in general. The variants are therefore deliberately surfaced as two distinct cost-basis methods so that the advisor can lean toward either tax outcome.

When two distinct `SELL` executes race against the same `Lot` under `SPECIFIC_LOT` (and the remaining shares only cover one), only one execute succeeds; the second is rejected with `ERR_INSUFFICIENT_LOT_SHARES` because `shares_remaining` is now insufficient. Serialization is first-writer-wins on the monotonic lot-share resource.

### 3.6. The Wash Sale Basis Adjustment

After a `SELL` settles and only when the realized P&L is negative (a loss), the system runs the wash sale basis adjustment. The sell date is the calendar date of `executed_at` interpreted in UTC; the window starts thirty days before the sell date inclusive and ends thirty days after the sell date inclusive, giving a symmetric closed window. The candidate set is every `Trade` whose `account_id` equals the selling account's, whose `side` is `BUY`, whose `status` is `SETTLED`, whose security shares the same `substantially_identical_group_id` as the sold security (the self-referential grouping that defines "substantially identical"), and whose `executed_at` floor-date lies inclusively between the window's two endpoints. Candidates are sorted by `executed_at` ascending with `id` as the stable tie-breaker.

Matching is by share count. Let the per-share loss be the trade's `realized_gain_loss_cents` divided by `requested_shares`, rounded half-up to a (negative) whole cent and stored as `loss_per_share`. For each candidate in order: the system takes the lesser of that candidate's `requested_shares` and the still-unmatched portion of the sell's shares as the matched quantity; multiplies the matched quantity by the absolute value of `loss_per_share` and rounds half-up to whole cents to obtain `disallowed_for_cand`; computes a per-share basis boost as `disallowed_for_cand` divided by the candidate's `shares_opened`, rounded half-up to whole cents and stored as `boost_per_share`; and applies the boost to the candidate's replacement lot — the unique `Lot` opened by that candidate `BUY` — by adding `boost_per_share` to its `adjusted_unit_cost_cents`. The matched quantity is added to a running matched-shares total, and the trade's `disallowed_loss_cents` accumulates `disallowed_for_cand`. The loop stops as soon as the running matched-shares total reaches the sell's `requested_shares`. The thirty-day window length is the only constant in this rule.

Each match also produces a `WashSaleEvent` for the audit trail. The event captures `sell_trade_id`, `replacement_trade_id`, `group_id` (the common `substantially_identical_group_id`), `matched_shares` (the lesser of the sell and buy share counts within the window for that match), `disallowed_loss_cents` for that match, `replacement_lot_id` (the lot that received the boost), and `recorded_at` (the server clock at write time). Rounding follows the precision rule that each named per-share step rounds half-up to whole cents and aggregation is performed without further rounding. The same wash-sale logic governs the rebalance pre-flight: a rebalance child `BUY` whose target security would match a `SELL` of the same group settled within the last thirty calendar days on the same account is rejected at request time with `ERR_WASH_SALE_VIOLATION` rather than being permitted to settle and trigger the adjustment. The pre-flight applies to every `BUY` execute path — client-initiated trades, rebalance children, dividend reinvest, and harvest replacement.

### 3.7. Harvest Opportunity Detection, Approval, and Execution

The harvest detection pass runs on the affected `Position` after every trade settlement and on demand through the positions-recompute capability when the caller's `intent` query parameter is `detect` (the default `intent` is `refresh`, which recomputes positions without scanning for opportunities). For each position in the account, the calculation computes the unrealized P&L as `market_value_cents` minus `total_cost_basis_cents`. When the unrealized P&L is at most negative five hundred dollars — that is, `unrealized_loss_cents` is less than or equal to negative fifty thousand cents, with the boundary inclusive — the system creates a new `HarvestOpportunity` row in `DETECTED` carrying `account_id`, `position_id`, the computed `unrealized_loss_cents`, and the `detected_at` server clock timestamp. Below that threshold magnitude (a smaller loss), nothing is created, and a recompute call with `intent=detect` that finds no position past the threshold returns `ERR_HARVEST_THRESHOLD_NOT_MET`. The five-hundred-dollar minimum harvest threshold is the only constant in this rule.

Replacement-security selection runs in the same pass. The candidate set is every `Security` whose `is_investable` flag is true, whose `substantially_identical_group_id` differs from the held security's group (so the replacement is not substantially identical and cannot itself trigger a wash sale), and for which a `CorrelationLink` exists with the held security (the link's `correlation` value drives the ranking). Candidates are sorted by `correlation` descending with `ticker` ascending as the tie-breaker, and the top candidate's id is stored on `replacement_security_id`. When no candidate qualifies — typically because no correlated investable security outside the group has been linked — the opportunity is created in `BLOCKED` instead of `DETECTED`, and `replacement_security_id` stays null. Adding a new `CorrelationLink` between two securities can resolve a blocked opportunity: the system re-evaluates positions whose blocked opportunities now have an eligible replacement, and those opportunities transition from `BLOCKED` back to `DETECTED` with `replacement_security_id` populated.

An `Advisor` approves a `DETECTED` opportunity only when the account's `compliance_status` is `ACTIVE`, the account's `investment_status` is not `REBALANCING` (a rebalance in flight cannot be intersected by a harvest execute), and `replacement_security_id` is not null. Approval moves the opportunity from `DETECTED` to `APPROVED` and has no other side effects. From `DETECTED`, an advisor may instead dismiss the opportunity (and the system also dismisses it as part of the client-suspension cascade); dismissal lands the row in `DISMISSED`, which is non-terminal at the position level — a future detection on the same position simply creates a new opportunity row, leaving the dismissed row historical.

Executing an `APPROVED` opportunity is an advisor-exclusive action that immediately moves the account's `investment_status` from `ACCUMULATING` to `HARVESTING` and emits two companion trades in `PENDING`: one `SELL` of the held security and one `BUY` of `replacement_security_id`. Both trades flow through the usual execute and settle pipeline; when the companion `SELL` reaches `SETTLED` with a realized loss, the opportunity transitions from `APPROVED` to `EXECUTED` (terminal). The account's `investment_status` returns to `ACCUMULATING` once all the harvest's associated trades have reached their terminal states.

### 3.8. Quarterly Rebalancing and the Branching Run

A `RebalanceRun` is the unit of automatic alignment back to the assigned model's targets. An `Advisor` starts a run by naming the `quarter_key` in the format `YYYY-Qn` (for example `2026-Q2`) and optionally passing `force=true` to override the drift gate. The system's quarterly capability does the same in batch across every account whose `max_drift_pct` meets the threshold. A run can be started only when the account is `ACTIVE` on its compliance dimension; only one run may exist per `(account_id, quarter_key)` pair whose status is anything other than `FAILED`; the `quarter_key` must be the current quarter or a future quarter (no backfilling). Violating any of those preconditions surfaces as `ERR_REBALANCE_ALREADY_IN_PROGRESS` (the duplicate/in-progress case) or `ERR_INVALID_STATE` (the future-quarter and account-state cases). Two simultaneous starts on the same `(account_id, quarter_key)` serialize first-writer-wins on the uniqueness constraint; exactly one `RebalanceRun` is created, and the loser receives `ERR_REBALANCE_ALREADY_IN_PROGRESS` (HTTP 409). The drift gate itself: a non-`force` start requires `max_drift_pct` to be at least 5.00 percentage points, and a request that fails the gate is rejected with `ERR_DRIFT_BELOW_THRESHOLD`. The drift threshold of five percentage points is the only constant in this gate.

When the start succeeds, the run is created in `SCHEDULED` and transitions to `IN_PROGRESS` in the same call: `started_at` is set to the current clock, `max_drift_pct_at_start` snapshots the pre-rebalance drift, the account's `investment_status` becomes `REBALANCING`, and child `PENDING` trades — `SELL` over-weight asset classes, `BUY` under-weight asset classes — are emitted with their `rebalance_run_id` set to the run's id. The run then branches into one of three terminal states.

When every child trade reaches `SETTLED` with no wash-sale blocking (no child has `disallowed_loss_cents` greater than zero), the run lands in `COMPLETED`: `completed_at` is the current clock, the account's `investment_status` returns to `ACCUMULATING`, and `max_drift_pct` is recomputed against the post-rebalance holdings. When at least one child `BUY` would create a wash sale against a recent loss on the same group within the trailing thirty calendar days (the pre-flight policy is `BLOCK`), those blocking children are set to `REJECTED`, the account's `investment_status` returns to `ACCUMULATING`, `completed_at` is the current clock, and the run lands in `BLOCKED_BY_WASH_SALE`. When any child trade is rejected for a reason other than a wash sale, every remaining `PENDING` child is set to `CANCELLED`, the account's `investment_status` returns to `ACCUMULATING`, `completed_at` is the current clock, and the run lands in `FAILED`. When the run reaches any of those three terminal states, the account's investment dimension transitions out of `REBALANCING` back to `ACCUMULATING`, and `max_drift_pct` is refreshed from the post-run holdings.

The drift recompute itself runs after every settled trade, on demand through the dedicated drift-recompute capability under the account, and at run start. The calculation gathers every position in the account, computes a `total_market_value` as the sum of every `Position`'s `market_value_cents` plus the account's `cash_balance_cents`, and then for each of the five asset classes computes the current weight as the sum of `market_value_cents` over the positions whose security has that `asset_class`, divided by `total_market_value`. The `CASH` bucket additionally includes `cash_balance_cents` in its numerator (since cash itself counts as the cash asset class). The target weight per class comes from the assigned model portfolio's `target_allocation`. The per-class drift is the absolute difference between current weight and target weight, multiplied by one hundred to yield percentage points. The account's `max_drift_pct` is the maximum drift across the five classes, rounded half-up to two decimal places once at the end; intermediate weights are not rounded.

### 3.9. Securities, Correlations, and Pricing

Securities are registered by an `Advisor`. Each `Security` carries a `ticker` of between one and ten uppercase characters, unique across the catalog; an `asset_class` from the five-class set; a `substantially_identical_group_id` that groups same-fund equivalents under one IRS-wash-sale identity; and an `is_investable` flag (default true) that determines whether the security may be bought through any path. The most recent price is held in `last_price_cents`, refreshed by the pricing capability that takes a `security_id` and a `last_price_cents`; a price update triggers a market-value recompute on every `Position` holding that security.

Correlation links are added between two securities by an `Advisor` through the dedicated capability. The link's body identifies the pair by `security_a_id` (conventionally the lower lexical id) and `security_b_id` (the higher), and carries a `correlation` value in the inclusive interval from negative one through positive one — values outside that range, or a request where `security_a_id` equals `security_b_id`, are rejected with `ERR_CORRELATION_INVALID`. New correlation links may unblock previously `BLOCKED` `HarvestOpportunity` rows by exposing a new eligible replacement.

### 3.10. Dividends and Reinvestment

Dividends are recorded against an account through the dividend capability. A `DividendEvent` captures `account_id`, `security_id` (the security paying the dividend or interest), `amount_cents` as a positive whole-cent integer, `received_at` as the server clock timestamp at receipt, and a `reinvest_trade_id` that is back-linked to the auto-generated reinvestment `BUY` trade once the side effect runs. The reinvestment is deterministic. Cash is credited first: `cash_balance_cents` is increased by `amount_cents`. The target for reinvestment is then chosen: if a `Position` exists in this account for the dividend's paying `security_id` and that security's `is_investable` flag is true, the target is the same security; otherwise the system falls back to the first `is_investable` security whose `asset_class` equals `CASH`, ordered by `ticker` ascending (alphabetically lowest). When no `CASH`-class investable security exists, no reinvestment trade is emitted and the cash simply sits in the account.

Once a target is chosen, the number of shares to buy is computed as `amount_cents` divided by the target's `last_price_cents`, truncated to four decimal places. When that fractional share count is greater than zero, a `BUY` `Trade` is emitted in `PENDING` with `requested_shares` set to the truncated share count, `side` set to `BUY`, and `security_id` set to the chosen target; the account's `cash_balance_cents` is then decreased by the truncated share count times the price, rounded half-up to whole cents. The cash credit and the cash debit are sequenced in that order so that the reinvest cannot overspend the freshly received amount.

### 3.11. The 1099-B Tax Form Lifecycle

A `TaxAdmin` creates a `Form1099B` for a client by naming the `tax_year`. Only one form may exist per `(client_id, tax_year)` pair; a duplicate create surfaces as `ERR_FORM_ALREADY_EXISTS` (HTTP 409), and two simultaneous creates for the same pair serialize on the uniqueness constraint so that exactly one form persists and the loser receives `ERR_FORM_ALREADY_EXISTS`. The form is born in `DRAFT`, and the assembly calculation populates its aggregates from every `SELL` `Trade` belonging to any `Account` of the client whose `status` is `SETTLED` and whose `executed_at` falls in the named `tax_year`. The form is refreshed each time it is fetched while still in `DRAFT`, so its values stay live until issuance.

Per-trade holding period is the weighted average over consumed lots of the calendar-day difference between the trade's `executed_at` date and each consumed lot's `acquired_at` date, weighted by `shares_consumed`. A trade is classified `SHORT` when its weighted holding period is at most three hundred and sixty-five days and `LONG` when it exceeds three hundred and sixty-five days. The three-hundred-and-sixty-five-day long-term threshold is the only constant in this rule.

Assembly proceeds with a **pinned rounding order**: per-trade `gross_proceeds_cents` and per-trade `realized_gain_loss_cents` are taken as already-stored integers from the realized-gain-loss calculation (which performed the only allowed rounding pass at the trade-level totals). The form sums those already-rounded integers and applies no further rounding. Specifically, the form's `short_term_proceeds_cents` is the sum of `gross_proceeds_cents` over `SHORT`-classified trades, and `short_term_cost_basis_cents` is the sum across the same trade set of `(gross_proceeds_cents - realized_gain_loss_cents)` per trade. The form's `short_term_realized_gain_loss_cents` is `short_term_proceeds_cents` minus `short_term_cost_basis_cents`. The long-term fields — `long_term_proceeds_cents`, `long_term_cost_basis_cents`, and `long_term_realized_gain_loss_cents` — are computed identically over the `LONG`-classified trades. The form's `total_disallowed_wash_sale_cents` is the sum of every `SELL` trade's `disallowed_loss_cents` over the same year and client set. This sum-of-rounded-trade-cents ordering is deliberate: the alternative ordering — sum exact lot products and round once at the end — disagrees in cents on edge cases.

Issuance moves the form from `DRAFT` to `ISSUED`. Issuance requires the client's `kyc_status` to be `ACTIVE` (a `SUSPENDED` client cannot have a form issued; the cross-entity precondition surfaces as `ERR_INVALID_STATE`) and zero `SELL` trades for the client in the named tax year remaining non-terminal — every such trade must already be `SETTLED`, `CANCELLED`, or `REJECTED`. When any sell is still `PENDING` or `EXECUTED`, issuance is rejected with `ERR_OPEN_TRADES_FOR_TAX_YEAR`. Issuance pins the aggregates to their values at issue time so that subsequent settlements do not perturb the issued form. The form may be voided into `VOIDED` from either `DRAFT` or `ISSUED`, but a void from `ISSUED` to `VOIDED` is permitted only when the form was issued less than thirty calendar days ago — beyond that, the transition into `VOIDED` is rejected with `ERR_INVALID_STATE`.

### 3.12. Test-driving Capabilities

Three system-only capabilities exist to make the time-based logic — wash-sale windows, quarter rollovers, the 30-day post-issue void window — testable. An admin-only clock-advance capability sets the logical clock to the instant supplied as an optional `to_iso` body parameter (when omitted, the clock advances by one tick), and recomputes every client's `age` against the new epoch. A second capability, the quarterly run, sweeps every account whose `max_drift_pct` is at the trigger threshold and which does not already have a rebalance in the current quarter, creating and starting a `RebalanceRun` for each. A third capability, the settlement sweep, drives every `EXECUTED` `Trade` to `SETTLED` in a single batch so that test scenarios can fan out through every cascade — wash-sale events, harvest detection, drift refresh — in one call. These three endpoints are gated to the `system` role only.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that modify, transition, or read an existing resource respond with HTTP 200. Successful responses follow the envelope in §2.2 and surface the affected resource or list in `data`. Refer back to §3 for the request-body contents and side effects of each operation; the table below is the routing summary.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/clients` | Create a Client (`kyc_status` PENDING). | ComplianceOfficer |
| GET | `/clients/{clientId}` | Fetch a Client. | ComplianceOfficer, Advisor, TaxAdmin, ClientUser |
| PATCH | `/clients/{clientId}` | Update Client mutable fields; horizon change re-runs model assignment. | ComplianceOfficer |
| POST | `/clients/{clientId}/activate` | Move Client PENDING→ACTIVE; runs model assignment. | ComplianceOfficer |
| POST | `/clients/{clientId}/suspend` | Move Client ACTIVE→SUSPENDED; cascade freezes accounts and dismisses outstanding opportunities. | ComplianceOfficer |
| POST | `/clients/{clientId}/reinstate` | Move Client SUSPENDED→ACTIVE; cascade unfreezes accounts. | ComplianceOfficer |
| POST | `/clients/{clientId}/risk-questionnaire` | Submit a risk questionnaire; compute `raw_score`, `assigned_band`; update `Client.risk_band`. | ComplianceOfficer, ClientUser |
| POST | `/model-portfolios` | Create a ModelPortfolio for a (risk_band, horizon_band) pair. | Advisor |
| GET | `/model-portfolios` | List model portfolios (paginated). | Advisor, ComplianceOfficer |
| POST | `/securities` | Register a Security. | Advisor |
| POST | `/_pricing/set` | Test-only price update; triggers position market-value recompute. | Advisor, system |
| POST | `/correlation-links` | Add a CorrelationLink between two Securities. | Advisor |
| POST | `/accounts` | Create an Account for a Client. | ComplianceOfficer |
| GET | `/accounts/{accountId}` | Fetch an Account (current `max_drift_pct`, balances). | ComplianceOfficer, Advisor, ClientUser |
| POST | `/accounts/{accountId}/freeze` | Set Account `compliance_status` to FROZEN_DOC_REVIEW. | ComplianceOfficer |
| POST | `/accounts/{accountId}/unfreeze` | Set Account `compliance_status` to ACTIVE. | ComplianceOfficer |
| POST | `/accounts/{accountId}/cash-deposit` | Credit cash to `cash_balance_cents`; triggers drift recompute. | Advisor, ComplianceOfficer |
| POST | `/accounts/{accountId}/trades` | Create a Trade in PENDING (BUY or SELL). | Advisor, ClientUser |
| POST | `/accounts/{accountId}/trades/{tradeId}/execute` | Execute a PENDING Trade. | Advisor, system |
| POST | `/accounts/{accountId}/trades/{tradeId}/settle` | Settle an EXECUTED Trade; runs wash-sale adjustment and harvest detection. | Advisor, system |
| POST | `/accounts/{accountId}/trades/{tradeId}/cancel` | Cancel a PENDING client-initiated Trade. | Advisor, ClientUser |
| GET | `/accounts/{accountId}/trades` | List trades for an Account (paginated, filterable by `status`, `side`, `year`). | Advisor, ComplianceOfficer, ClientUser, TaxAdmin |
| GET | `/accounts/{accountId}/positions` | List current Positions for an Account. | Advisor, ComplianceOfficer, ClientUser |
| POST | `/accounts/{accountId}/positions/recompute` | Recompute positions and optionally detect harvest opportunities (via `intent`). | Advisor, system |
| POST | `/accounts/{accountId}/drift/recompute` | Recompute Account `max_drift_pct`. | Advisor, system |
| GET | `/accounts/{accountId}/harvest-opportunities` | List harvest opportunities for an Account. | Advisor, ComplianceOfficer |
| POST | `/accounts/{accountId}/harvest-opportunities/{opportunityId}/approve` | Approve a DETECTED HarvestOpportunity. | Advisor |
| POST | `/accounts/{accountId}/harvest-opportunities/{opportunityId}/dismiss` | Dismiss a DETECTED HarvestOpportunity. | Advisor |
| POST | `/accounts/{accountId}/harvest-opportunities/{opportunityId}/execute` | Execute an APPROVED HarvestOpportunity; emit companion SELL/BUY. | Advisor |
| POST | `/accounts/{accountId}/rebalance/start` | Start a quarterly RebalanceRun (one per `quarter_key`). | Advisor |
| GET | `/accounts/{accountId}/rebalance-runs` | List rebalance runs for an Account. | Advisor, ComplianceOfficer |
| POST | `/accounts/{accountId}/dividends` | Record a DividendEvent and emit reinvest BUY. | Advisor, system |
| POST | `/clients/{clientId}/forms-1099b` | Create a DRAFT Form1099B for a `tax_year`. | TaxAdmin |
| GET | `/clients/{clientId}/forms-1099b/{formId}` | Fetch a Form1099B (refreshes assembly while DRAFT). | TaxAdmin, ClientUser |
| POST | `/clients/{clientId}/forms-1099b/{formId}/issue` | Issue (DRAFT→ISSUED); pins aggregates. | TaxAdmin |
| POST | `/clients/{clientId}/forms-1099b/{formId}/void` | Void a Form1099B (DRAFT or recently-ISSUED). | TaxAdmin |
| POST | `/_clock/advance` | Advance the logical clock (test-only); recomputes `Client.age`. | system |
| POST | `/_quarterly/run` | Batch-sweep accounts past drift threshold and run a RebalanceRun for each. | system |
| POST | `/_settle/run` | Settle every EXECUTED Trade in batch. | system |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_FORBIDDEN` | 403 |
| `ERR_AUTH_IDENTITY_UNKNOWN` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_TRADE_STATE` | 409 |
| `ERR_ACCOUNT_FROZEN` | 409 |
| `ERR_WASH_SALE_VIOLATION` | 422 |
| `ERR_SECURITY_NOT_INVESTABLE` | 422 |
| `ERR_INSUFFICIENT_LOT_SHARES` | 422 |
| `ERR_INSUFFICIENT_POSITION_SHARES` | 422 |
| `ERR_REBALANCE_ALREADY_IN_PROGRESS` | 409 |
| `ERR_DRIFT_BELOW_THRESHOLD` | 422 |
| `ERR_HARVEST_THRESHOLD_NOT_MET` | 422 |
| `ERR_ALLOCATION_INVALID` | 422 |
| `ERR_CORRELATION_INVALID` | 422 |
| `ERR_QUESTIONNAIRE_OUT_OF_RANGE` | 422 |
| `ERR_TIME_HORIZON_OUT_OF_RANGE` | 422 |
| `ERR_FORM_ALREADY_EXISTS` | 409 |
| `ERR_OPEN_TRADES_FOR_TAX_YEAR` | 409 |
| `ERR_INSUFFICIENT_CASH` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_CLIENT_NOT_ACCEPTING_INPUT` | 409 |
