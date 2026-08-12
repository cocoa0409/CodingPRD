# Margin Lending API — Product Requirements Document

## 1. Introduction

Retail brokerages that extend credit to their clients operate under a dense regulatory regime: Regulation T governs initial margin, exchange and FINRA rules impose minimum maintenance thresholds, and pattern-day-trading rules impose a minimum equity floor on active accounts — all while the firm's own risk desk layers stricter "house" requirements on top. The Margin Lending API is the operational backbone of the brokerage's margin department. It covers the full credit lifecycle: onboarding a customer, adjudicating the margin application under segregation of duties, executing and recording trades against margined positions, valuing the account on two price bases, issuing and curing margin calls, liquidating positions when calls expire, accruing tiered interest on debit balances, and resolving customer disputes.

Because margin decisions are only as good as the prices and the clock behind them, the platform treats market data and time itself as first-class inputs: price marks arrive in two series (realtime and official close), and a logical clock — never the wall clock — drives every deadline, accrual, and scheduled sweep. The API is mounted under `/margin`, with two additional test-driving capabilities (a clock control and an end-of-day sweep) mounted at the root. Everything the department does is attributed: five segregated roles act through signed request headers, sensitive two-person steps are enforced mechanically, and every mutation to an account is versioned so that stale write attempts are rejected rather than silently applied.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting an unrecognized role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Five roles exist:

- `Customer` — the retail client; owns applications, accounts, orders, cash movements, and disputes. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403).
- `MarginAnalyst` — margin operations analyst; onboards customers, moves applications into compliance review, and opens dispute reviews. When `X-User-Role` is `MarginAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewed_by_user_id` on the application or dispute being reviewed) but does not compare it to any entity's `id`.
- `MarginSupervisor` — approves and rejects applications, sets house margin policy and interest rate tiers, waives calls, and decides disputes. When `X-User-Role` is `MarginSupervisor`, `X-User-ID` is likewise opaque; it may be recorded as `decided_by_user_id` on applications and disputes.
- `LiquidationDesk` — creates, fills, and cancels liquidation orders. When `X-User-Role` is `LiquidationDesk`, `X-User-ID` is opaque; it may be recorded as `created_by_user_id` or `last_filled_by_user_id` on the orders it touches.
- `MarketDataOps` — market data and batch operator; posts price marks and drives the logical clock and the daily sweep. When `X-User-Role` is `MarketDataOps`, `X-User-ID` is opaque.

Segregation of duties is enforced mechanically across three controlled steps: the supervisor who approves or rejects an application must not be the analyst who reviewed it; the desk user who fills a liquidation order must not be the desk user who created it; and the supervisor who decides a dispute must not be the analyst who opened its review. Any such self-dealing attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the server's wall clock rather than the logical clock of §2.5.
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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, and out-of-range values are clamped into the range 1–100 rather than rejected. The `offset` parameter specifies the number of items to skip and defaults to 0, with negative values clamped to 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties — common under the logical clock — broken by creation (insertion) order. Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Integer Money, Basis Points, and Rounding Discipline

All monetary amounts are represented as integer cents — there are no floats anywhere in the financial core. Prices are integer cents per share. Rates, margin percentages, and concentration thresholds are integer basis points (ten-thousandths of a unit). Every ratio comparison — the concentration share tests and the day-trade ratio test among them — is evaluated with cross-multiplied integer arithmetic, never floating-point division.

Rounding, where a rule requires it, is always "round half up" to whole cents, and it is applied at exactly four pinned points and nowhere else: each per-position maintenance requirement line is rounded before the account-level requirement is summed; each daily interest accrual is rounded before the month's accruals are summed into a monthly posting; the Regulation T initial requirement is rounded when computed; and the weighted average-cost blend of §3.4 is rounded when a fill grows an existing position. Equity values themselves are exact integer-cent sums with no rounding at all.

### 2.5. The Logical Clock

The platform runs on a logical clock, never the wall clock. Before it is ever set, the clock reads exactly 2026-05-01T00:00:00Z. A `MarketDataOps` operator may advance it through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. The new time must be greater than or equal to the current logical time; an attempt to move it backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400). Every timestamp the business logic depends on — `issued_at` and `due_at` on calls, `marked_at` on marks, `fill_date` on fills, `accrual_date` on interest entries, `opened_at` on positions, `resolved_at` on calls, `pdt_flagged_at` on accounts — is taken from this clock.

### 2.6. Two Mark Bases: Realtime and Official Close

Every security carries two independent price series, distinguished by `mark_type`: `REALTIME` marks and `OFFICIAL_CLOSE` marks. The current mark for a security on a given basis is the mark of that type with the latest `marked_at`; if two marks of the same type share a `marked_at`, the one with the later `created_at` wins — a newly posted mark supersedes earlier marks stamped with the same `marked_at`.

The two bases serve different masters. The realtime basis drives trade gating, buying-power display, and the realtime account fields `equity_realtime_cents`, `reg_req_realtime_cents`, and `house_req_realtime_cents`. The official-close basis is the basis of record for margin-call evaluation: it drives `equity_official_cents`, `reg_req_official_cents`, and `house_req_official_cents`, every maintenance-excess computation, and the sweep's call checks. Identical positions can therefore yield two different equities when realtime and official marks diverge — an account can look healthy intraday and still be called at the close.

### 2.7. Common Resource Properties

Primary resources — `Customer`, `AccountApplication`, `MarginAccount`, `SecurityProfile`, `Position`, `MarginCall`, `LiquidationOrder`, `CashMovement`, `RateTier`, and `Dispute` — carry a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation from the logical clock of §2.5.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation to the current logical-clock time.
- `version` — an integer, starting at 1 on creation, that increments by one on every mutation; it backs the optimistic concurrency control of §2.8.

Ledger-style records — `TradeFill`, `DayTradeEvent`, `PriceMark`, and `InterestLedgerEntry` — are immutable once written and carry only `id` and `created_at`; both `updated_at` and `version` are absent from these resources. Recomputing an account's derived fields (equity, requirements, buying power) counts as a mutation of the account: it refreshes `updated_at` and increments `version`, as do the automatic posture transitions described in §2.11.

### 2.8. Optimistic Concurrency Control on Account Writes

Two write operations are guarded by optimistic concurrency control on the parent `MarginAccount`: recording a cash movement against an account (`POST /margin/accounts/{id}/cash-movements`) and creating liquidation orders against an account (`POST /margin/accounts/{id}/liquidation-orders`). Each requires a non-optional `expected_account_version` field in the request body, carrying the account `version` the client last observed.

If `expected_account_version` does not match the account's current `version` — because another writer has since posted a movement, filled an order, or run a sweep cascade against the same account, advancing its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The mover or the desk is thereby prevented from acting on a stale balance view, or on call amounts, positions, and requirements that have changed since they were read. The version check itself is applied after existence and ownership resolution and before any state or fiscal evaluation (on liquidation-order creation it follows the call scoping checks of §3.9). A successful guarded write increments the account's `version` by exactly one. No other endpoint accepts a version field; endpoints not named above take no concurrency input at all.

### 2.9. Nested Resource Retrieval

Requests that address nested resources are validated left to right along the path: each identifier must exist before the next is examined, and the request is rejected with the 404 error corresponding to the first identifier that does not resolve. The not-found catalogue is `ERR_CUSTOMER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_SECURITY_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_LIQUIDATION_ORDER_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, and `ERR_RATE_TIER_NOT_FOUND` (all HTTP 404). Single-record reads of the ledger-style resources fail with `ERR_FILL_NOT_FOUND`, `ERR_DAY_TRADE_EVENT_NOT_FOUND`, `ERR_MARK_NOT_FOUND`, `ERR_CASH_MOVEMENT_NOT_FOUND`, or `ERR_INTEREST_ENTRY_NOT_FOUND` (all HTTP 404) when the addressed id does not exist. A request for positions under a non-existent account therefore fails with `ERR_ACCOUNT_NOT_FOUND` before any position lookup is attempted. Body-supplied references — such as the security on an order or mark, or the call on a dispute or liquidation order — must likewise resolve to existing resources and fail with the corresponding 404 when they do not. A request that matches no defined route fails with `ERR_NOT_FOUND` (HTTP 404, or HTTP 405 for an unsupported method on a defined path), and an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500), both in the standard error envelope.

### 2.10. Validation Priority Cascade

Malformed bodies, missing required fields, unrecognized enum values, and non-positive amounts or quantities on order, cash-movement, and liquidation-fill bodies are rejected outright with `ERR_INVALID_REQUEST` (HTTP 400); declared application financials and rate-tier parameters, by contrast, accept any integer. Beyond that, every request is validated against the following cascade in this fixed order — a failure at any step short-circuits all later steps:

1. **User context** — the two headers are present and the role is recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization** — the role is permitted on this endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Existence** — path identifiers resolve left to right (the 404 catalogue of §2.9).
4. **Ownership** — on customer-scoped writes (submitting or resubmitting an application, placing orders, moving cash, filing disputes, closing the account), `X-User-ID` must equal the owning customer's `id` (`ERR_ACCOUNT_OWNERSHIP_MISMATCH`).
5. **State preconditions** — the account must not be `CLOSED` (`ERR_ACCOUNT_CLOSED`); opening orders, withdrawals, and journal debits additionally require `ACTIVE` posture (`ERR_ACCOUNT_RESTRICTED`); and applications, calls, disputes, and liquidation orders must stand in a valid from-state for the invoked transition (`ERR_APPLICATION_INVALID_STATE`, `ERR_CALL_NOT_OPEN`, `ERR_CALL_NOT_EXPIRED`, `ERR_DISPUTE_INVALID_STATE`, `ERR_LIQUIDATION_INVALID_STATE`).
6. **Regulatory and compliance gates** — segregation of duties on application approve/reject, liquidation fills, and dispute decisions (`ERR_SEGREGATION_OF_DUTIES`); and the pattern-day-trader minimum-equity gate on opening orders (`ERR_PDT_MIN_EQUITY`).
7. **Suitability at approval** — the financial thresholds and the one-account-per-customer rule (`ERR_SUITABILITY_NOT_MET`, `ERR_ACCOUNT_ALREADY_EXISTS`).
8. **Instrument and structural rules** — the security must be marginable for opening orders (`ERR_SECURITY_NOT_MARGINABLE`); a realtime mark must exist (`ERR_NO_MARKET_MARK`); rate-tier effective windows must not overlap (`ERR_RATE_TIER_OVERLAP`); a call may not carry two in-flight disputes (`ERR_DUPLICATE_DISPUTE`); an account may not carry two non-terminal liquidation orders (`ERR_LIQUIDATION_IN_PROGRESS`); and a position selected for liquidation must not already be reserved (`ERR_POSITION_RESERVED`).
9. **Temporal and mark sanity** — the logical clock never regresses (`ERR_CLOCK_REGRESSION`), and mark prices must be positive (`ERR_INVALID_MARK`).
10. **Fiscal checks** — post-trade buying power on opening orders (`ERR_INSUFFICIENT_BUYING_POWER`), withdrawal cash sufficiency (`ERR_INSUFFICIENT_CASH`), and the post-withdrawal maintenance-excess floor (`ERR_MAINTENANCE_EXCESS_NEGATIVE`).

Two pinned local orderings qualify this cascade: on liquidation-order creation the account-level `ERR_LIQUIDATION_IN_PROGRESS` screen precedes the `ERR_CALL_NOT_EXPIRED` state check (§3.9), and on dispute filing the `ERR_DUPLICATE_DISPUTE` screen precedes the `ERR_CALL_NOT_OPEN` state check (§3.8).

### 2.11. Account Posture and Automatic State Reconciliation

A `MarginAccount` is always in one of three postures: `ACTIVE`, `RESTRICTED`, or `CLOSED`. Posture changes are largely automatic. The moment any margin call on the account transitions to `OPEN` — whether issued by the official-close mark cascade or by the daily sweep — the account flips from `ACTIVE` to `RESTRICTED`, and from that moment its opening orders and withdrawals are rejected with `ERR_ACCOUNT_RESTRICTED`. Conversely, whenever the account's last non-terminal call resolves — a call is non-terminal while `OPEN`, `DISPUTED`, `EXPIRED`, or `LIQUIDATION_IN_PROGRESS` — the account automatically returns from `RESTRICTED` to `ACTIVE`. This posture recheck runs after every cure, every waiver, and every overturned dispute. These automatic transitions require no client request on the account itself, and each mutates the account's `updated_at` and `version` like any other write. `CLOSED` is terminal and is reached only through the explicit closure workflow described in §3.9.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and the Application Pipeline

A `MarginAnalyst` onboards a retail client by registering a `Customer` with a `legal_name` and an `email`; the email must be unique across all customers, a duplicate being rejected with `ERR_INVALID_REQUEST` (HTTP 400). From that point the client can apply for margin privileges. A `Customer` submits an application carrying `customer_id` — which must equal the caller's `X-User-ID`, otherwise the submission is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` — together with `annual_income_cents`, `liquid_net_worth_cents`, and `investment_experience_years`, all declared in integer cents and whole years respectively. A new application's `application_status` lands in `SUBMITTED` — the lifecycle thereafter runs `SUBMITTED` → `COMPLIANCE_REVIEW` → `APPROVED` or `REJECTED`, with a resubmission cycle back to `SUBMITTED` — and `reviewed_by_user_id`, `decided_by_user_id`, `rejection_reason`, and `account_id` are all null at the start. Applications can be listed and filtered by `customer_id` or `account_id`.

Review is a two-person affair. A `MarginAnalyst` first moves the application from `SUBMITTED` to `COMPLIANCE_REVIEW`; the application must actually stand in `SUBMITTED` (otherwise `ERR_APPLICATION_INVALID_STATE`), and the analyst's identity is recorded into `reviewed_by_user_id`. The decision belongs to a `MarginSupervisor`. Approval evaluates its checks in a fixed order: the application must stand in `COMPLIANCE_REVIEW` (else `ERR_APPLICATION_INVALID_STATE` — a wrong-state application surfaces this error rather than being masked by later checks); the supervisor's `X-User-ID` must differ from the recorded `reviewed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); the applicant must clear the suitability bar — `liquid_net_worth_cents` of at least 200,000 cents (two thousand dollars) and `investment_experience_years` of at least 1 (else `ERR_SUITABILITY_NOT_MET`); and the customer must not already hold a margin account (else `ERR_ACCOUNT_ALREADY_EXISTS`).

On approval the supervisor's identity lands in `decided_by_user_id`, and the system creates the `MarginAccount`: owned by the customer, linked back to the application through `application_id`, with `account_status` `ACTIVE`, zero `cash_balance_cents`, all equity and requirement fields at zero, `buying_power_cents` at zero, `pdt_flag` false, and `pdt_flagged_at` null. The application's `account_id` is set to the new account's `id`, and the application reaches its terminal `APPROVED` state. Accounts can be listed and filtered by `customer_id` or `application_id`.

Rejection moves the application from `COMPLIANCE_REVIEW` to `REJECTED` under the same state and segregation checks; the supervisor may supply an optional `reason`, which is recorded into `rejection_reason`, and `decided_by_user_id` is set. Rejection is not the end of the road: the owning customer may resubmit, cycling the application from `REJECTED` back to `SUBMITTED`. Resubmission is rejected if the application is not `REJECTED` (`ERR_APPLICATION_INVALID_STATE`) or if the caller is not the applicant (`ERR_ACCOUNT_OWNERSHIP_MISMATCH`), and it accepts optional updated values for `annual_income_cents`, `liquid_net_worth_cents`, and `investment_experience_years` — any provided value overwrites the declared financials. On resubmission `reviewed_by_user_id`, `decided_by_user_id`, and `rejection_reason` are all reset to null so the next review cycle starts clean.

### 3.2. Security Master Data and House Margin Policy

Before any trading can occur, a `MarginSupervisor` registers each instrument as a `SecurityProfile` carrying its `symbol` (unique across securities, a duplicate being rejected with `ERR_INVALID_REQUEST`), a `marginable` flag controlling whether opening margin positions are allowed, the house maintenance percentages `house_maint_long_bps` and `house_maint_short_bps`, a `liquidity_tier` where 1 denotes the most liquid instruments and which the liquidation selector uses as its primary ranking key in ascending order, and a `concentration_threshold_bps` — the share of an account's gross long market value above which a long position attracts concentration add-ons, with "above" meaning strictly greater.

House policy is not static. When a supervisor amends a security's profile — any of `house_maint_long_bps`, `house_maint_short_bps`, `concentration_threshold_bps`, or `marginable` may change — the server recomputes the official maintenance requirements of every account holding that security — every account with a position row in the security, including zero-quantity rows, though `CLOSED` accounts are skipped — and runs the full call evaluation of §3.7 for each affected account. A tightening of policy can therefore issue brand-new margin calls across the book and flip affected accounts from `ACTIVE` to `RESTRICTED` without any trading activity at all.

### 3.3. Price Marks and the Official-Close Cascade

`MarketDataOps` posts price marks one at a time, naming the `security_id`, the `mark_type` (`REALTIME` or `OFFICIAL_CLOSE`), and a `price_cents` that must be positive — non-positive marks are rejected with `ERR_INVALID_MARK`, and a mark naming a security that does not exist fails with `ERR_SECURITY_NOT_FOUND`. Each mark stamps the logical-clock time into `marked_at`, and marks can be listed filtered by `security_id` or `mark_type`.

The two mark types trigger very different cascades. A `REALTIME` mark updates `mv_realtime_cents` on every position in that security and recomputes the realtime equity, requirement, and buying-power fields of every holding account — nothing more. An `OFFICIAL_CLOSE` mark updates `mv_official_cents` and the official equity and requirement fields of every holder, and then runs the full call evaluation described in §3.7: within that evaluation, already-`OPEN` calls whose cure test is newly satisfied by the closing prices first resolve as `CURED` with `cure_method` `MARKET_RECOVERY`, and only then may one new call be issued, each freshly issued call flipping its account from `ACTIVE` to `RESTRICTED`. Both mark types recompute every account holding the security as a mutation (refreshing `updated_at` and incrementing `version` per §2.7), and both cascades skip `CLOSED` accounts. Posting the official close is thus the single most consequential write in the system.

### 3.4. Order Execution, Position Keeping, and Day-Trade Detection

The owning `Customer` places market orders against an account by naming a `security_id`, a `side` — one of `BUY`, `SELL`, `SELL_SHORT`, or `BUY_TO_COVER` — and a positive `quantity` (a non-positive quantity fails with `ERR_INVALID_REQUEST`). Orders fill immediately, in full, at the security's latest `REALTIME` mark.

Gating follows the cascade of §2.10. The account must exist and be owned by the caller, and it must not be `CLOSED` (`ERR_ACCOUNT_CLOSED`). Orders that would establish a new position or increase the size of an existing one are "opening orders" — including a fill that crosses through zero and reopens a residual on the other side, which is opening even when the absolute size shrinks, while an exact close to zero is never opening: opening orders require `ACTIVE` posture, and on a `RESTRICTED` account they fail with `ERR_ACCOUNT_RESTRICTED`, while orders that reduce or close out a position remain permitted. Opening orders next face the pattern-day-trader gate: when the account's `pdt_flag` is set and `equity_realtime_cents` is below 2,500,000 cents (twenty-five thousand dollars), the order is rejected with `ERR_PDT_MIN_EQUITY`. Instrument checks follow — an opening order requires the security to be `marginable` (`ERR_SECURITY_NOT_MARGINABLE`), and every order, opening or reducing, requires at least one `REALTIME` mark on record to price the fill (`ERR_NO_MARKET_MARK`). Finally the post-trade buying-power check runs in a pinned evaluation order that makes the circular-looking dependency explicit: first compute the cash that would result from applying the proposed fill; then derive the post-trade positions and their realtime market values; then compute post-trade equity on the realtime basis per §3.5; then compute the Regulation T initial requirement as fifty percent — 5,000 basis points — of the sum of the gross long and gross short realtime market values, rounded half up to whole cents; then compute the post-trade house maintenance requirement on realtime marks. The fill is allowed only if post-trade equity is greater than or equal to the Reg T initial requirement and greater than or equal to the house requirement; otherwise the order is rejected with `ERR_INSUFFICIENT_BUYING_POWER` and nothing is recorded.

A successful fill does several things atomically. A `TradeFill` is recorded with the account, the security, the `side`, the filled `quantity`, the execution `price_cents` (the latest realtime mark at order time), the `fill_date` taken from the logical clock, and an `is_day_trade` flag. Cash moves with the fill: `BUY` and `BUY_TO_COVER` debit `cash_balance_cents` by the filled value, while `SELL` and `SELL_SHORT` credit it. The position is created if absent and updated otherwise: `quantity` is signed (positive for long, negative for short); `avg_cost_cents` tracks the average acquisition price per share of the currently open quantity — a fill that grows the position blends the fill price into a size-weighted average rounded half up to whole cents, a reduction leaves the average unchanged, an exact close to zero retains the last average, and a fill that moves the quantity from zero to non-zero restarts the average at that fill's price; `opened_at` records the clock time at which the quantity last transitioned from zero to non-zero, with a sign flip that reopens on the other side in a single fill re-stamping it; and `last_trade_date` tracks the calendar date of the most recent fill. Day counters reset lazily — whenever a fill's `fill_date` differs from the position's stored `last_trade_date`, `today_bought_qty` and `today_sold_qty` are zeroed before the fill applies — and `BUY` fills add to `today_bought_qty` while `SELL_SHORT` fills add to `today_sold_qty`; `SELL` and `BUY_TO_COVER` fills move neither counter.

Day-trade detection rides on those counters. When a `SELL` closes long shares that were bought the same day, the day-trade share count is the smaller of `today_bought_qty` as it stood before the fill and the sold quantity; when that count is positive, the fill is marked `is_day_trade` and, unless a `DayTradeEvent` already exists for that account, security, and `event_date`, one is created — at most one event ever exists per account, security, and calendar date. A `BUY_TO_COVER` closing short shares sold the same day is handled symmetrically against `today_sold_qty`. After every fill, the account's equity, requirement, and buying-power fields are recomputed on both bases. A successful order placement returns 201 with the affected `Position` object as its `data`. Fills, positions, and day-trade events are all individually readable, and listable with filters on `account_id` and `security_id`.

### 3.5. Equity, Maintenance Requirements, and Concentration Add-Ons

Equity is the same formula on both bases: `cash_balance_cents`, plus the sum of long market values, minus the sum of the absolute values of short market values, taken across every `Position` row of the account — including zero-quantity rows, which contribute nothing. A position's market value on a basis is its `quantity` multiplied by the current mark price of that basis: positive quantities add to equity, negative quantities subtract their absolute size. The realtime variant is stored as `equity_realtime_cents` and serves trade gating, buying power, and realtime reads; the official variant is stored as `equity_official_cents` and is the basis of every call decision. Equity is recomputed on every order fill, every price-mark post (the realtime basis for `REALTIME` marks, both bases for `OFFICIAL_CLOSE` marks), every cash movement, each monthly interest posting, every liquidation fill, every house-policy amendment, and the daily sweep's per-account pass.

Maintenance requirements are computed per position — only positions with non-zero `quantity` participate — and per basis. The regulatory percentage is flat: 2,500 basis points (twenty-five percent) for long positions and 3,000 basis points (thirty percent) for short positions. Each position's regulatory requirement line is its absolute market value times the regulatory percentage, divided by ten thousand and rounded half up to whole cents; the account's `reg_req_official_cents` (or `reg_req_realtime_cents` on the realtime basis) is the sum of those rounded lines.

The house requirement starts from the security's own percentages and adds concentration surcharges. A long position is "concentrated" when its market value multiplied by ten thousand strictly exceeds the security's `concentration_threshold_bps` multiplied by the account's gross long market value on the same basis — the gross long market value being the sum of the positive market values of all the account's positions on that basis. A concentrated long adds 1,000 basis points when its share stays at or under seventy-five percent of gross long market value — precisely, when its market value times ten thousand is less than or equal to 7,500 times the gross long market value — and adds 2,000 basis points when strictly above that band. The position's house percentage is `house_maint_long_bps` or `house_maint_short_bps`, chosen by side, plus the add-on; its house requirement line uses the greater of the regulatory percentage and that house percentage, rounded half up per line in the same way; and the account's `house_req_official_cents` (or `house_req_realtime_cents`) is the sum of those rounded house lines.

Buying power is a display and gating quantity derived from realtime figures. When `pdt_flag` is true, `buying_power_cents` is four times the amount by which `equity_realtime_cents` exceeds the greater of `reg_req_realtime_cents` and `house_req_realtime_cents`, floored at zero. When the flag is false, `buying_power_cents` is twice the amount by which `equity_realtime_cents` exceeds the Regulation T initial requirement on realtime marks — 5,000 basis points of the combined gross long and gross short realtime market value, rounded half up — again floored at zero.

### 3.6. Pattern Day Trading and the Minimum-Equity Gate

Once per daily sweep, the platform re-evaluates every account's pattern-day-trader status. The window is the trailing five calendar dates inclusive of the sweep's clock date. Within that window the server counts the account's day-trade fills — its `TradeFill` records with `is_day_trade` set — by `fill_date`, and its `TradeFill` records overall by `fill_date`. The account is flagged — `pdt_flag` set true — when both conditions hold: the day-trade count is at least 4, and the day-trade count strictly exceeds six percent of the fill count, evaluated as integer cross-multiplication (day trades times one hundred strictly greater than six times fills). On the sweep where the flag transitions from false to true, `pdt_flagged_at` is stamped with the clock; on any later sweep where the condition no longer holds, the flag clears — `pdt_flag` returns to false while `pdt_flagged_at` is left as last stamped, to be re-stamped if the flag is later set again.

The flag has two teeth. First, the opening-order gate of §3.4: a flagged account whose `equity_realtime_cents` sits below 2,500,000 cents may not open positions at all (`ERR_PDT_MIN_EQUITY`). Second, the minimum-equity call of §3.7: a flagged account whose `equity_official_cents` falls below 2,500,000 cents attracts a `DAY_TRADE_MIN_EQUITY` call. The flag also changes the buying-power multiplier from two to four, as described in §3.5.

### 3.7. Margin Calls: Issuance, Deadlines, and Cure

Call evaluation always runs on the official-close basis, whether triggered by an official-close mark, by a house-policy change, or by the daily sweep. Four call types exist, in a fixed severity order: `MAINTENANCE` is most severe, then `HOUSE`, then `FED_REG_T`, then `DAY_TRADE_MIN_EQUITY`. At most one call is issued per evaluation — the most severe applicable type wins — and if that selected type already has a non-terminal call (`OPEN`, `DISPUTED`, `EXPIRED`, or `LIQUIDATION_IN_PROGRESS`) on the account, the evaluation issues nothing at all: lesser applicable types never leapfrog the blocked type, so at most one non-terminal call exists per account per `call_type`.

The evaluation compares `equity_official_cents` against three yardsticks. The regulatory excess is `equity_official_cents` minus `reg_req_official_cents`; the house excess is `equity_official_cents` minus `house_req_official_cents`; and the Regulation T initial deficiency is the greater of zero and the rounded Reg T initial requirement on official marks — 5,000 basis points of the gross long official market value, rounded half up — minus `equity_official_cents`. If the regulatory excess is negative, a `MAINTENANCE` call issues for the larger of the regulatory deficiency and the house deficiency. Otherwise, if the house excess is negative, a `HOUSE` call issues for the house deficiency. Otherwise, if the Reg T initial deficiency is positive, a `FED_REG_T` call issues for that deficiency. Otherwise, if `pdt_flag` is set and `equity_official_cents` is below 2,500,000 cents, a `DAY_TRADE_MIN_EQUITY` call issues for the difference between 2,500,000 cents and `equity_official_cents`. If none of the four applies, no call is issued. The issued amount is recorded as `call_amount_cents`, the clock time as `issued_at`, and issuance flips the account from `ACTIVE` to `RESTRICTED` per §2.11.

Every call carries a deadline: `due_at` is `issued_at` plus a per-type grace period — 96 hours for `FED_REG_T`, 72 hours for `MAINTENANCE`, 48 hours for `HOUSE`, and 120 hours for `DAY_TRADE_MIN_EQUITY`. While the call is non-terminal, `resolved_at` and `cure_method` stay null. The daily sweep expires any `OPEN` call whose `due_at` has been reached or passed, moving it to `EXPIRED`; calls in `DISPUTED` never expire — the deadline clock pauses for as long as a dispute is in flight.

An `OPEN` call cures automatically whenever recomputation shows the binding official maintenance excess — `equity_official_cents` minus the greater of `reg_req_official_cents` and `house_req_official_cents` — at zero or above; a `DAY_TRADE_MIN_EQUITY` call cures instead when `equity_official_cents` reaches at least 2,500,000 cents. The recorded `cure_method` names the trigger: `DEPOSIT` when a deposit or journal credit cascade satisfies the test, `MARKET_RECOVERY` when an official-mark recompute, a house-policy amendment, or the daily sweep does, and `LIQUIDATION` when a liquidation fill does. Every cure stamps `resolved_at` and runs the account posture recheck of §2.11. A `MarginSupervisor` may also waive a call outright, but only while it is `OPEN` or `EXPIRED` — waiving from any other state is rejected with `ERR_CALL_NOT_OPEN`. A waived call records `cure_method` `WAIVER`, stamps `resolved_at`, and runs the same posture recheck. Calls are listable per account with a `call_status` filter.

### 3.8. Disputes and Customer Communication

A customer who believes a call is wrong files a `Dispute` against it, supplying the `call_id` and a free-text `reason`; the call must belong to the customer's own account, and ownership is enforced as usual. Filing first verifies that the call carries no in-flight dispute — a call may carry at most one dispute in `OPEN` or `UNDER_REVIEW` at a time, a second in-flight filing failing with `ERR_DUPLICATE_DISPUTE` — and then that the call stands in `OPEN`, any other state rejecting the filing with `ERR_CALL_NOT_OPEN` (a `DISPUTED` call always carries an in-flight dispute, so the duplicate error surfaces first there). Filing creates the dispute with `dispute_status` `OPEN` — the dispute lifecycle runs `OPEN` → `UNDER_REVIEW` → `UPHELD` or `OVERTURNED` → `CLOSED` — with `reviewed_by_user_id`, `decided_by_user_id`, and `decision` all null, and simultaneously moves the call from `OPEN` to `DISPUTED`, pausing its expiry clock for the duration.

A `MarginAnalyst` picks up the dispute by starting review, moving it from `OPEN` to `UNDER_REVIEW` (any other from-state fails with `ERR_DISPUTE_INVALID_STATE`) and stamping `reviewed_by_user_id` with the analyst's identity. If the evidence is insufficient, the analyst can request more information, cycling the dispute from `UNDER_REVIEW` back to `OPEN` and resetting `reviewed_by_user_id` to null while the customer gathers documents.

The decision belongs to a `MarginSupervisor`, who supplies a `decision` of `UPHELD` or `OVERTURNED`. The dispute must stand in `UNDER_REVIEW` (`ERR_DISPUTE_INVALID_STATE` otherwise), and the deciding supervisor must not be the analyst recorded in `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). The supervisor's identity lands in `decided_by_user_id`, and the dispute then closes itself automatically: `UPHELD` and `OVERTURNED` are momentary states that transition immediately to the terminal `CLOSED`. The linked call feels the outcome. When the dispute is upheld, the call returns from `DISPUTED` to `OPEN` with its `due_at` unchanged — no extension is granted, so if the clock has already passed `due_at`, the next daily sweep will expire it. When the dispute is overturned, the call moves from `DISPUTED` to `WAIVED` with `cure_method` `WAIVER` and `resolved_at` stamped, followed by the account posture recheck. Disputes are listable globally or per account, filterable by `account_id` and `call_id`.

### 3.9. Liquidation, Cash Movements, Interest, and Closure

**Liquidation.** Once a call has reached `EXPIRED`, the `LiquidationDesk` steps in. Creating liquidation orders against an account requires the `call_id` of the expired call and the OCC field `expected_account_version` described in §2.8. The referenced call must resolve and belong to the addressed account (otherwise `ERR_CALL_NOT_FOUND`), and the version guard applies next. The account-level lock then fires before the call's state is examined: while any earlier order on the account remains `PENDING` or `PARTIALLY_FILLED`, a fresh creation is rejected with `ERR_LIQUIDATION_IN_PROGRESS` regardless of the call's state. Only then is the call's state checked: the referenced call must stand in `EXPIRED` — any other state is rejected with `ERR_CALL_NOT_EXPIRED`.

Position selection is a server-side policy; the desk does not choose. Eligible positions are those with non-zero `quantity` and zero `reserved_qty` — the server re-verifies the reservation guard at selection time and rejects with `ERR_POSITION_RESERVED` if a selected position is already reserved by a non-terminal order. Eligible positions are ranked by their security's `liquidity_tier` ascending, then by absolute `mv_official_cents` descending, with ties broken by `opened_at` ascending and any residual tie by position creation order — never by `id`. The selector takes whole positions in rank order until the cumulative absolute official market value reaches at least `call_amount_cents`; each selected position is liquidated in full, the order's `quantity` being the absolute size of that position. If no positions are eligible, or the total eligible official market value falls short of the call amount, creation is rejected with `ERR_NO_LIQUIDATABLE_POSITIONS`. One `LiquidationOrder` is created per selected position — a single creation can therefore spawn several orders atomically — and the response returns the first-ranked order. Each created order starts with `order_status` `PENDING`, `filled_quantity` zero, and `proceeds_cents` zero, records the desk user in `created_by_user_id` with `last_filled_by_user_id` null, reserves its shares by adding `quantity` to the position's `reserved_qty`, moves the call from `EXPIRED` to `LIQUIDATION_IN_PROGRESS`, and increments the account's `version` by one.

Filling is also desk work, but by a different pair of hands: the filler supplies `filled_quantity` and `fill_price_cents` — both integers, the price strictly positive, a non-positive price failing outright with `ERR_INVALID_REQUEST` — the order must stand in `PENDING` or `PARTIALLY_FILLED` (else `ERR_LIQUIDATION_INVALID_STATE`), the filler's `X-User-ID` must differ from `created_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and `filled_quantity` must be positive and no greater than the remaining unfilled quantity (else `ERR_FILL_EXCEEDS_QUANTITY`). Each fill reduces the position's `quantity` toward zero by the filled amount, releases those shares from `reserved_qty`, and moves cash: the filled value — `filled_quantity` shares at `fill_price_cents` — is credited to `cash_balance_cents` when liquidating a long position and debited when buying to cover a short. The order's cumulative `filled_quantity` and `proceeds_cents` grow, `last_filled_by_user_id` is stamped, the account's equity and requirement fields recompute on current marks, and the order's `order_status` advances to `PARTIALLY_FILLED` — or straight to `EXECUTED` when the fill completes the entire remaining quantity. A partially filled order never returns to `PENDING`; `EXECUTED` is terminal. After each fill the call's cure test runs: the call moves from `LIQUIDATION_IN_PROGRESS` to `CURED` with `cure_method` `LIQUIDATION` and `resolved_at` stamped when either the binding official maintenance excess is back at zero or above, or the cumulative `proceeds_cents` across the call's orders reaches `call_amount_cents`; the posture recheck follows.

Cancellation releases what filling did not consume. Cancelling is allowed from `PENDING` or `PARTIALLY_FILLED` (else `ERR_LIQUIDATION_INVALID_STATE`) and lands the order in its other terminal state, `CANCELLED`; the unfilled remainder is subtracted from the position's `reserved_qty`, while fills already applied are not reversed. When the cancellation leaves no non-terminal orders for the call, the call's cure test runs once more: if it is satisfied the call resolves `CURED` with `cure_method` `LIQUIDATION`, and otherwise the call falls back from `LIQUIDATION_IN_PROGRESS` to `EXPIRED`. Liquidation orders are listable with `account_id`, `call_id`, and `position_id` filters.

**Cash movements.** The owning customer moves cash by naming a `movement_type` — `DEPOSIT`, `WITHDRAWAL`, `JOURNAL_CREDIT`, or `JOURNAL_DEBIT` — a positive `amount_cents`, and the OCC field `expected_account_version`. Deposits and journal credits add to `cash_balance_cents`; withdrawals and journal debits subtract. The movement records the `resulting_cash_balance_cents` immediately after application, the account's `version` increments by one, and equity recomputes on both bases. Deposits and journal credits are permitted on any non-`CLOSED` account; withdrawals and journal debits require `ACTIVE` posture (`ERR_ACCOUNT_RESTRICTED` while restricted), may not exceed `cash_balance_cents` (`ERR_INSUFFICIENT_CASH`), and must leave the binding official maintenance excess at zero or above after the debit (`ERR_MAINTENANCE_EXCESS_NEGATIVE`). A deposit or credit that satisfies an `OPEN` call's cure test resolves it with `cure_method` `DEPOSIT`, followed by the posture recheck.

**Interest.** Interest accrues on debit balances against effective-dated `RateTier` records, which a `MarginSupervisor` maintains with a `tier_level`, an inclusive lower debit bound `min_balance_cents`, an `annual_rate_bps` quoted on a 360-day year, and an effective window from `effective_from` to `effective_to` — both dates inclusive, with a null `effective_to` meaning open-ended. Two tiers of the same `tier_level` may not share any calendar date; back-to-back windows are allowed, and an overlapping submission is rejected with `ERR_RATE_TIER_OVERLAP`. Each daily sweep writes at most one `DAILY_ACCRUAL` `InterestLedgerEntry` per account per calendar date — a second sweep on the same date adds none — and only for an account whose cash is negative and for which an applicable tier exists; when no tier's window covers the clock date with `min_balance_cents` at or below the debit, no accrual is written that day. The debit is the absolute value of a negative `cash_balance_cents` (zero when cash is non-negative), the applicable tier is the one whose effective window covers the clock date and whose `tier_level` is the greatest among those with `min_balance_cents` at or below the debit, and the day's `amount_cents` is the debit times the tier's `annual_rate_bps` divided by ten thousand and by 360, rounded half up to whole cents. The entry snapshots `debit_balance_snapshot_cents` and `rate_bps_applied`, records the covered date in `accrual_date`, and starts with `posted` false. On the first sweep whose calendar month differs from the last posted month — catching up across several unposted months if need be, one post per month in chronological order — a `MONTHLY_POST` entry is written for each prior month holding unposted daily accruals (a month with no accruals gets no posting), whose amount is the sum of that month's already-rounded daily accruals; the included dailies flip `posted` to true, and the `MONTHLY_POST` records the posting date in `accrual_date`, snapshots the account's current debit in `debit_balance_snapshot_cents` and the month's last daily's rate in `rate_bps_applied`, carries `posted` true itself, and its amount is debited from `cash_balance_cents` — a debit that feeds the same sweep's call evaluation. A computed interest summary per account reports `debit_balance_cents` — the current debit, zero when cash is non-negative — `current_daily_accrual_cents` — what the current day's accrual would be under the currently applicable tier, zero when there is no debit or no applicable tier — `month_to_date_accrued_cents` — the sum of the current calendar month's recorded daily accruals — a `provisional_month_estimate_cents` equal to the month-to-date accrual plus the days remaining in the month after the clock date times the current daily accrual (an estimate that assumes the debit stays constant and therefore diverges from posted actuals when the debit changes mid-month), and `posted_month_total_cents`, the chronological sum of the rounded daily accruals actually recorded for the last posted month (zero when no month has posted yet). Ledger entries are listable per account with an `entry_type` filter.

**The daily sweep.** `MarketDataOps` triggers the end-of-day sweep, which skips `CLOSED` accounts entirely and runs three steps in a pinned order: first interest — a `DAILY_ACCRUAL` for every debit account and, on month roll, the `MONTHLY_POST` whose cash debit feeds the third step; second, the pattern-day-trader evaluation of §3.6; third, call evaluation on the official basis — issuing new calls per §3.7, curing satisfied `OPEN` calls with `cure_method` `MARKET_RECOVERY`, and expiring `OPEN` calls at or past `due_at` while `DISPUTED` calls are left untouched. The sweep's response reports counters: `calls_issued`, `calls_cured`, `calls_expired`, `interest_accruals_created`, `interest_posts_created`, `pdt_flags_set`, and `pdt_flags_cleared`. Every mutation the sweep performs cascades to the affected accounts' computed fields and posture, and step 3's recomputation of every evaluated account's derived fields itself counts as a mutation per §2.7 — each evaluated account's `version` advances on every sweep even when nothing else changed.

**Closure.** The owning customer may close an account that has gone flat. Closure requires the account to be live — an already-`CLOSED` account rejects further operations with `ERR_ACCOUNT_CLOSED` — every position's `quantity` at exactly zero (`ERR_POSITIONS_EXIST`), no non-terminal margin calls of any kind (`ERR_OPEN_CALLS_EXIST`, which is also what blocks closure of a `RESTRICTED` account whose calls are still open), and `cash_balance_cents` at exactly zero (`ERR_NONZERO_BALANCE`). Both `ACTIVE` and `RESTRICTED` accounts may close under those conditions; `CLOSED` is terminal.

## 4. Endpoint Definitions

Operations that create new resources — onboarding a customer, submitting an application, registering a security profile, posting a price mark, placing an order, recording a cash movement, creating liquidation orders, creating a rate tier, filing a dispute — return a `201 Created` status code. Operations that modify an existing resource in place, including all state transitions (review, approve, reject, resubmit, close, waive, fill, cancel, start-review, request-info, decide), the profile amendment, the clock control, and the daily sweep, return `200 OK`. Reads return `200 OK`. Request and response payloads for every operation are defined by the workflows of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/margin/customers` | Onboard a customer | MarginAnalyst |
| GET | `/margin/customers/{id}` | Get a customer | Any authenticated role |
| POST | `/margin/account-applications` | Submit a margin account application | Customer |
| GET | `/margin/account-applications/{id}` | Get an application | Any authenticated role |
| GET | `/margin/account-applications` | List applications, filterable | Any authenticated role |
| POST | `/margin/account-applications/{id}/review` | Move an application to compliance review | MarginAnalyst |
| POST | `/margin/account-applications/{id}/approve` | Approve an application and create the margin account | MarginSupervisor |
| POST | `/margin/account-applications/{id}/reject` | Reject an application | MarginSupervisor |
| POST | `/margin/account-applications/{id}/resubmit` | Resubmit a rejected application | Customer |
| GET | `/margin/accounts/{id}` | Get a margin account including computed fields and version | Any authenticated role |
| GET | `/margin/accounts` | List accounts, filterable | Any authenticated role |
| POST | `/margin/accounts/{id}/close` | Close a flat, call-free, zero-cash account | Customer |
| POST | `/margin/security-profiles` | Register a security with house margin policy | MarginSupervisor |
| GET | `/margin/security-profiles/{id}` | Get a security profile | Any authenticated role |
| GET | `/margin/security-profiles` | List security profiles | Any authenticated role |
| PATCH | `/margin/security-profiles/{id}` | Amend house margin policy; recomputes requirements and may issue calls | MarginSupervisor |
| POST | `/margin/market-marks` | Post a price mark; official-close marks run the call evaluation cascade | MarketDataOps |
| GET | `/margin/market-marks/{id}` | Get a price mark | Any authenticated role |
| GET | `/margin/market-marks` | List price marks, filterable | Any authenticated role |
| POST | `/margin/accounts/{id}/orders` | Place a market order filled immediately at the latest realtime mark | Customer |
| GET | `/margin/accounts/{id}/positions` | List positions of an account | Any authenticated role |
| GET | `/margin/positions/{id}` | Get a position | Any authenticated role |
| GET | `/margin/positions` | List positions, filterable | Any authenticated role |
| GET | `/margin/accounts/{id}/fills` | List trade fills of an account | Any authenticated role |
| GET | `/margin/fills/{id}` | Get a trade fill | Any authenticated role |
| GET | `/margin/fills` | List trade fills, filterable | Any authenticated role |
| GET | `/margin/accounts/{id}/day-trade-events` | List day-trade events of an account | Any authenticated role |
| GET | `/margin/day-trade-events/{id}` | Get a day-trade event | Any authenticated role |
| GET | `/margin/day-trade-events` | List day-trade events, filterable | Any authenticated role |
| GET | `/margin/accounts/{id}/margin-calls` | List margin calls of an account, filterable by status | Any authenticated role |
| GET | `/margin/margin-calls/{id}` | Get a margin call | Any authenticated role |
| POST | `/margin/margin-calls/{id}/waive` | Waive an open or expired call | MarginSupervisor |
| POST | `/margin/accounts/{id}/liquidation-orders` | Create liquidation order(s) against an expired call via the selector policy; OCC-guarded | LiquidationDesk |
| GET | `/margin/liquidation-orders/{id}` | Get a liquidation order | Any authenticated role |
| GET | `/margin/liquidation-orders` | List liquidation orders, filterable | Any authenticated role |
| GET | `/margin/margin-calls/{id}/liquidation-orders` | List liquidation orders for a call | Any authenticated role |
| POST | `/margin/liquidation-orders/{id}/fill` | Fill a liquidation order; filler must differ from creator | LiquidationDesk |
| POST | `/margin/liquidation-orders/{id}/cancel` | Cancel the unfilled remainder, releasing the reservation | LiquidationDesk |
| POST | `/margin/accounts/{id}/cash-movements` | Deposit, withdraw, or journal cash; OCC-guarded | Customer |
| GET | `/margin/accounts/{id}/cash-movements` | List cash movements of an account | Any authenticated role |
| GET | `/margin/cash-movements/{id}` | Get a cash movement | Any authenticated role |
| POST | `/margin/rate-tiers` | Create an effective-dated interest rate tier | MarginSupervisor |
| GET | `/margin/rate-tiers/{id}` | Get a rate tier | Any authenticated role |
| GET | `/margin/rate-tiers` | List rate tiers | Any authenticated role |
| GET | `/margin/accounts/{id}/interest-entries` | List interest ledger entries of an account, filterable by type | Any authenticated role |
| GET | `/margin/interest-entries/{id}` | Get an interest ledger entry | Any authenticated role |
| GET | `/margin/accounts/{id}/interest-summary` | Computed interest read: provisional estimate versus posted actuals | Any authenticated role |
| POST | `/margin/disputes` | File a dispute against an open margin call | Customer |
| GET | `/margin/disputes/{id}` | Get a dispute | Any authenticated role |
| GET | `/margin/disputes` | List disputes, filterable | Any authenticated role |
| GET | `/margin/accounts/{id}/disputes` | List disputes of an account | Any authenticated role |
| POST | `/margin/disputes/{id}/start-review` | Open dispute review | MarginAnalyst |
| POST | `/margin/disputes/{id}/request-info` | Request more information; cycle the dispute back to open | MarginAnalyst |
| POST | `/margin/disputes/{id}/decide` | Decide a dispute; decider must differ from reviewer | MarginSupervisor |
| POST | `/_clock/set_current_utc` | Advance the test-driving logical clock | MarketDataOps |
| POST | `/_sweeps/daily` | Run the end-of-day sweep: interest, day-trade flags, call evaluation | MarketDataOps |

## 5. Error Code Catalogue

Trigger conditions for every error are described in the narratives of §2 and §3; this table is an identifier-to-status summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_SECURITY_NOT_FOUND` | 404 Not Found |
| `ERR_POSITION_NOT_FOUND` | 404 Not Found |
| `ERR_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_LIQUIDATION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_FILL_NOT_FOUND` | 404 Not Found |
| `ERR_DAY_TRADE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_MARK_NOT_FOUND` | 404 Not Found |
| `ERR_CASH_MOVEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INTEREST_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_ACCOUNT_RESTRICTED` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SUITABILITY_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_ALREADY_EXISTS` | 422 Unprocessable Entity |
| `ERR_PDT_MIN_EQUITY` | 403 Forbidden |
| `ERR_SECURITY_NOT_MARGINABLE` | 422 Unprocessable Entity |
| `ERR_NO_MARKET_MARK` | 422 Unprocessable Entity |
| `ERR_INVALID_MARK` | 400 Bad Request |
| `ERR_CALL_NOT_OPEN` | 409 Conflict |
| `ERR_CALL_NOT_EXPIRED` | 409 Conflict |
| `ERR_DISPUTE_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_DISPUTE` | 409 Conflict |
| `ERR_LIQUIDATION_INVALID_STATE` | 409 Conflict |
| `ERR_FILL_EXCEEDS_QUANTITY` | 422 Unprocessable Entity |
| `ERR_LIQUIDATION_IN_PROGRESS` | 409 Conflict |
| `ERR_POSITION_RESERVED` | 409 Conflict |
| `ERR_NO_LIQUIDATABLE_POSITIONS` | 409 Conflict |
| `ERR_INSUFFICIENT_BUYING_POWER` | 402 Payment Required |
| `ERR_INSUFFICIENT_CASH` | 402 Payment Required |
| `ERR_MAINTENANCE_EXCESS_NEGATIVE` | 402 Payment Required |
| `ERR_RATE_TIER_OVERLAP` | 409 Conflict |
| `ERR_POSITIONS_EXIST` | 409 Conflict |
| `ERR_OPEN_CALLS_EXIST` | 409 Conflict |
| `ERR_NONZERO_BALANCE` | 409 Conflict |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_FOUND` | 404 Not Found (405 for an unsupported method on a defined path) |
| `ERR_INTERNAL` | 500 Internal Server Error |
