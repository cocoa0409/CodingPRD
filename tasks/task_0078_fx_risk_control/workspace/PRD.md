# Fx Risk Control API — Product Requirements Document

## 1. Introduction

Foreign-exchange trading desks live or die by the speed at which a control system can answer two questions: *how much risk is the firm running right now?*, and *who is allowed to take that risk?* Spot and option desks book hundreds of trades per minute across overlapping currency pairs, market quotes drift continuously, and the difference between a profitable book and a regulatory event is often a few basis points held a few seconds too long. The Fx Risk Control API is the middle-office spine that ties trader limits, real-time position monitoring, stop-loss enforcement, counterparty credit ratings, settlement netting and compliance reporting into a single, auditable substrate.

The system is built around segregation of duties: traders book exposure, risk officers gate it, compliance officers police counterparties, and settlement operators close it out — and no actor may sign off on their own activity. Limits split cleanly into an intraday window and an overnight window, so a trade booked at 16:59 UTC and the same trade booked at 17:00 UTC have entirely different consequences for utilization. Temporary overrides can be granted, but only through an approval workflow with an explicit expiry, after which the system silently rolls back to the baseline cap. Stop-loss rules — keyed to price, dollar loss, or loss ratio — are evaluated on every market-data quote and can trigger anything from a passive alert to a forced-flatten that books an offsetting trade on the trader's behalf.

The API is mounted under `/fx-risk` and is consumed by trading front-ends, the market-data feed, the bank's settlement plumbing and a regulator-facing reporting service. Every state-changing operation produces an audit-log row, and every approval flow records both the requester and the approver so that an end-of-day reconstruction is always possible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the Fx Risk Control API MUST carry two HTTP headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, identifying which role the principal is acting as. If either header is missing or empty, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). If both are present but the role is not permitted to invoke the requested endpoint per the role-to-endpoint matrix implicit in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles are recognised, spelled exactly as shown:

- `Trader` — front-office user who books trades, raises limit-adjustment requests on their own limits, and acknowledges stop-loss events that fire against their own positions. Identity is entity-backed: when `X-User-Role` is `Trader`, the supplied `X-User-ID` MUST be the `id` of an existing `Trader` row. Ownership checks on any resource that references a trader (`Limit`, `LimitAdjustmentRequest`, `Trade`, `Position`, `StopLossEvent`) compare the resource's `trader_id` foreign key to the caller's `X-User-ID`.
- `RiskOfficer` — middle-office user who provisions traders, currency pairs and limits, approves or rejects temporary overrides, and authors and executes stop-loss rules. Identity is opaque: `X-User-ID` is an operator identifier not bound to any persisted entity, but the server records it on audit rows and on the `approver_user_id` field of any `LimitAdjustmentRequest` they decide.
- `ComplianceOfficer` — risk-and-compliance user who registers counterparties, adjusts ratings, manages the watchlist and files regulatory reports. Identity is opaque; the server records the caller in `AuditLog.actor_user_id` and on the `filed_by_user_id` of any report they file.
- `SettlementOperator` — back-office user driving netting, sending and reconciling settlement instructions. Identity is opaque; recorded on audit rows.
- `MarketDataSystem` — non-human caller representing the firm's market-data feed. Identity is opaque; permitted only to push quotes and force stop-loss re-evaluation, never to mutate business entities directly.

All role names appear verbatim, case-sensitive, exactly as the five strings above.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0, minimum 0). Both are integers, and both are validated together against `ERR_INVALID_PAGINATION` (HTTP 422) — a request with `limit` outside the inclusive range 1 through 100, or with `offset` strictly less than 0, is rejected. Results are sorted by `created_at` ascending; when two rows share a `created_at`, the tie-breaker is the resource's `id` ascending. The response `meta` object on a list endpoint carries `limit`, `offset`, `total_count` (the size of the full unpaginated result set), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties, IDs and Timestamps

Most entities in this system share a common envelope of four fields. The `id` is a server-minted UUID with no type prefix — a `Trader` id and a `Counterparty` id look identical and are not interchangeable. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at insert time and `updated_at` advances on every mutation, including computed-field cascades. The `version` field is an integer, initialised to 1 at creation, and incremented by exactly 1 on every successful mutation of the row.

Two entities are tracked only by `id` and `created_at` — they are append-only and never mutated in place. The `Trade` entity is one of them: a booked trade's lifecycle status advances by inserting offsetting trades or by settlement cascades, but the trade row itself is not re-versioned. The `ComplianceReport` entity is the other: each filing is a fresh row, and "amending" a report means writing a new `ComplianceReport` with the same `report_type` and `reference_trade_id` and a higher `version` integer (see §3.6). Both entities carry no `updated_at` and no `version` field on the persisted row (the `version` integer on `ComplianceReport` is a monotonic counter within the report family, not the OCC token described in §2.5). The `AuditLog` entity is likewise append-only: rows carry `id` and `created_at` only.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that target a versioned entity (`Trader`, `CurrencyPair`, `Limit`, `LimitAdjustmentRequest`, `Position`, `StopLossEvent`, `Counterparty`, `SettlementInstruction`) accept an optional `version` field in the request body. When supplied, it MUST match the entity's current `version` exactly; if it does not, the mutation is rejected with `ERR_VERSION_CONFLICT` (HTTP 409) and no state is changed. When the caller omits `version` from the body, the OCC check is skipped and the latest row is mutated. Successful mutations increment `version` by 1 and refresh `updated_at`.

### 2.6. Precision, Rounding and Currency Conversion

All USD-denominated monetary fields — `notional_cap_usd`, `stop_loss_cap_usd`, `temporary_override_usd`, `utilization_usd`, `net_open_usd`, `mtm_pnl_usd`, `credit_limit_usd`, `nostro_balance_delta`, `gross_pay_amount`, `gross_receive_amount`, `net_amount`, and the headline `gross_usd` / `net_usd` / `var_99_1d_usd` outputs — are carried to two decimal places, rounded half-up. The `utilization_pct` field is likewise carried to two decimal places, rounded half-up. The `mid_rate` and `entry_rate` quote fields are carried to six decimal places. The `daily_volatility` field is also carried to six decimal places. The trade `notional_base` field is two decimal places.

To convert a position into USD, the system uses the following rule, which all USD-denominated calculations share. If the pair's `base_ccy` is the string `"USD"`, the USD-per-base rate is 1. Otherwise, if the pair's `quote_ccy` is `"USD"`, the USD-per-base rate is the pair's current `mid_rate`. Otherwise, the system triangulates by multiplying the pair's `mid_rate` by the USD-per-`quote_ccy` rate, where the latter is itself 1 when the quote currency is `"USD"`, and is otherwise the `mid_rate` of the pair whose code is `USD` concatenated with the quote currency.

### 2.7. Cascading Side Effects, `updated_at` and `version` Semantics

When a single API call mutates multiple rows — for instance, a market-data quote that recomputes positions, fires stop-losses and shifts limit utilisation; or a settlement failure that ripples back into counterparty scoring and trader suspension — every touched row receives a fresh `updated_at` and (for rows with `common_fields: true`) a `version` increment. The order in which side effects are listed inside each §3 workflow IS the order in which the server applies them; tests targeting the intermediate state assume this ordering. Cascades never short-circuit on a benign update: if the recomputation lands on the same numeric value, the row's `updated_at` still advances.

### 2.8. Nested Resource Retrieval

Several endpoints carry hierarchical paths — `traders/{trader_id}/limits`, `traders/{trader_id}/positions`, `traders/{trader_id}/exposure`, `traders/{trader_id}/var`, `desks/{desk_code}/positions`. Path parameters are resolved left to right. A non-existent parent yields `ERR_NOT_FOUND` (HTTP 404) before any later validation runs, so a request that names a missing trader and a missing child resource will surface the missing-trader error, never the child's. The same left-to-right rule applies when a state-machine endpoint receives an id that exists but in the wrong shape — existence is checked first, then state.

### 2.9. Validation Ordering and the Validation Pipeline

When several validations could fire on the same request, they are evaluated in a fixed priority order, and the first failure short-circuits the rest. The pipeline is: (1) the two header checks — missing headers raise `ERR_AUTH_REQUIRED`, role-not-permitted raises `ERR_FORBIDDEN`; then (2) path-id existence raises `ERR_NOT_FOUND`; then (3) state-machine eligibility for state-changing endpoints raises `ERR_INVALID_STATE`; then (4) segregation-of-duties on approve/reject/override/execute operations raises `ERR_SEGREGATION_VIOLATION`; then (5) counterparty-watchlist gating on `/settlements/{id}/send` raises `ERR_COUNTERPARTY_WATCHLIST`; then (6) referential-and-trader-status checks on trade booking raise `ERR_TRADER_SUSPENDED`; then (7) format checks like currency-pair regex raise `ERR_INVALID_PAIR_FORMAT`; then (8) the temporal check on `expires_at` raises `ERR_EXPIRES_IN_PAST`; then (9) fiscal checks raise `ERR_LIMIT_BREACH` or `ERR_COUNTERPARTY_LIMIT_BREACH`; then (10) the settlement-idempotency check produces `ERR_IDEMPOTENCY_REPLAY` (which is a 200 success, not an error — see §3.7); then (11) OCC raises `ERR_VERSION_CONFLICT`; then (12) pagination raises `ERR_INVALID_PAGINATION`. A request that violates rule 4 and rule 9 simultaneously surfaces only the rule-4 outcome. The `ERR_VALIDATION` code is reserved for generic input-shape failures (missing required body field, wrong JSON type, numeric out of declared range) that do not match a more specific code; the `ERR_INVALID_STOPLOSS_MODE` code is reserved for the narrower failure where `rule_mode` is not one of `PRICE`, `LOSS_AMOUNT`, `LOSS_RATIO`, or where the supplied `threshold_value` is not strictly greater than zero.

### 2.10. Audit Trail Coverage

Every mutating call writes an `AuditLog` row. Each row records the `event_type` (one of `LIMIT_CHANGE`, `LIMIT_OVERRIDE_APPROVED`, `LIMIT_OVERRIDE_EXPIRED`, `STOP_LOSS_TRIGGERED`, `STOP_LOSS_OVERRIDDEN`, `RATING_CHANGE`, `TRADE_BOOKED`, `SETTLEMENT_FAILED`, `REPORT_FILED`), the caller's `actor_user_id` (or the literal `"SYSTEM"` for clock- and sweep-driven events), the caller's `actor_role`, the `subject_entity` name (`Trader`, `Limit`, `LimitAdjustmentRequest`, `StopLossEvent`, `Counterparty`, `SettlementInstruction`, `ComplianceReport` etc.), the `subject_id` of the touched row, a `before_snapshot` of the relevant fields prior to mutation (which is null for creates), and an `after_snapshot` of the relevant fields after mutation. Audit log rows are immutable after they are written. The list endpoint exposes filtering by `event_type`, `subject_entity` and `subject_id` query parameters.

### 2.11. Concurrency Guarantees

Five concurrent-write scenarios receive deterministic outcomes; in every case, exactly one writer wins and the loser receives a specific `error_id`. (a) Two `RiskOfficer` calls simultaneously deciding the same `LimitAdjustmentRequest` — one wins, and the loser, finding the request no longer `PENDING`, receives `ERR_REQUEST_ALREADY_DECIDED` (HTTP 409). (b) Two `Trader` trades that individually fit a limit but jointly exceed `notional_cap_usd + temporary_override_usd` in either bucket — the first lands, the second is rejected on the post-write utilisation with `ERR_LIMIT_BREACH` (HTTP 409). (c) Two settlement-generation calls supplying the same `client_request_id` for the same `counterparty_id` and `value_date` — the second returns the first call's `SettlementInstruction` set with HTTP 200, surfacing `ERR_IDEMPOTENCY_REPLAY`. (d) Two operators racing `/confirm` and `/mark-failed` against the same `SettlementInstruction` in `SENT` — exactly one terminal status sticks; the loser receives `ERR_INVALID_STATE` (HTTP 409). (e) `/override` and `/execute` racing against the same `TRIGGERED` `FORCED_FLATTEN` `StopLossEvent` — exactly one wins; the loser receives `ERR_INVALID_STATE` (HTTP 409).

### 2.12. Clock and Sweep Infrastructure

The system carries an explicit server clock. Two test-driving capabilities permit deterministic exercise of time-sensitive behaviour. The clock-advance capability accepts a `to_iso` instant and forwards the server clock to it; it re-evaluates time-gated state immediately (for example, marking an `expires_at` as having passed) but does NOT itself walk the cascade. The sweep capability walks the cascade idempotently and may be invoked any number of times for the same logical clock position with the same final state. Both capabilities are reserved to `RiskOfficer`.

## 3. Business Logic & Workflows

### 3.1. Onboarding Traders, Currency Pairs and Quotes

A `RiskOfficer` brings a new trader online by supplying a `name` and a `desk_code`. The `desk_code` must be one of the three permitted desk strings — `G10_SPOT`, `EM_FX`, or `OPTIONS` — otherwise the registration is rejected as a generic input failure. The newly minted trader's `status` field is initialised to `ACTIVE`; it remains there until either a settlement-failure cascade or an explicit risk-officer action drives it to `SUSPENDED`. The trader row also receives the standard `id`, `created_at`, `updated_at`, and `version` envelope described in §2.4. While in `SUSPENDED`, the trader cannot book new trades — that gate is the rule-7 fiscal check, which surfaces `ERR_TRADER_SUSPENDED`.

Currency pairs are likewise registered by the `RiskOfficer`. A pair carries a six-letter `code` in `BASE_QUOTE` form (for example `EURUSD`, `USDJPY`), and the `base_ccy` and `quote_ccy` ISO-4217 strings MUST agree with the first three and last three letters of `code` respectively. The pair is rejected with `ERR_INVALID_PAIR_FORMAT` (HTTP 422) when `code` is not exactly six uppercase letters, when the slices disagree with the supplied `base_ccy`/`quote_ccy`, or when a row with the same `code` already exists. The initial market state is supplied at registration time as `mid_rate` (strictly positive, six decimal places) and `daily_volatility` (zero or greater, six decimal places); the latter feeds the value-at-risk calculation.

The `MarketDataSystem` role (and, for manual interventions, the `RiskOfficer`) pushes fresh quotes into the system. A quote payload identifies a pair by `code` and supplies a new `mid_rate`. Pushing a quote IS the heartbeat of the risk control system: it overwrites the pair's `mid_rate`, recomputes every affected `Position` (touching `net_open_usd` and `mtm_pnl_usd`), recomputes `Limit.utilization_usd`, `Limit.utilization_pct` and `Position.warning_status` accordingly, and walks every `ARMED` `StopLossEvent` on the pair to see whether any of them has now crossed its trigger condition. The order of those cascades is: position recompute first, then limit utilisation, then stop-loss evaluation; the stop-loss evaluation can only see the post-recompute view.

### 3.2. Limits, Buckets and the Intraday/Overnight Split

A `RiskOfficer` provisions one or more `Limit` rows per trader. Each row pins a `bucket` — either `INTRADAY` or `OVERNIGHT` — and optionally a `pair_code`. When `pair_code` is null, the limit is an aggregate cap across every pair the trader holds in that bucket; when set, the limit gates only positions in that one pair. Each row also carries a `notional_cap_usd` (the strict positive USD ceiling on the bucket's net open position) and a `stop_loss_cap_usd` (zero or greater, the cumulative realised-plus-unrealised loss the bucket tolerates before stop-loss rules attached to it are armed). Both monetary fields are recorded to two decimal places.

The two buckets describe overlapping but distinct exposure windows. Trades booked during the same trading day before 17:00 UTC contribute to the `INTRADAY` bucket; trades booked at or after 17:00 UTC on the same trading day, or any trades carried over from a prior `trading_day`, contribute to the `OVERNIGHT` bucket. The boundary is sharp: a trade timestamped exactly 17:00:00.000 UTC counts as `OVERNIGHT`. The intraday utilisation is computed against the intraday `Limit` row's `notional_cap_usd`; the overnight utilisation is computed against the overnight row's cap and over a wider trade inclusion set, so the same trader at the same instant produces two distinct `utilization_pct` numbers — one per bucket — and both must hold.

Direct edits to a base cap are confined to a `RiskOfficer` patching the `Limit` row to change `notional_cap_usd` or `stop_loss_cap_usd`; the request body carries those optional fields plus the OCC `version`. Such an edit does NOT bypass the approval workflow described in §3.3 — it simply re-baselines the cap and is distinct from a temporary additive override.

For every (`trader_id`, `pair_code`, `bucket`) tuple, the effective cap is `notional_cap_usd` plus `temporary_override_usd`; `temporary_override_usd` is zero unless an approved limit-adjustment is currently in effect. `utilization_usd` is the absolute value of the bucket's `net_open_usd`. `utilization_pct` is the utilisation in USD divided by the effective cap in USD, multiplied by 100, then rounded half-up to two decimal places. The `warning_status` field on `Position` is derived from that percentage: a utilisation strictly below 80 is `NORMAL`, a utilisation at or above 80 but strictly below 100 is `WARNING`, and a utilisation at or above 100 is `BREACH`. The 80 boundary belongs to `WARNING` and the 100 boundary belongs to `BREACH`. The constants 80 and 100 are pinned and do not vary by desk or trader.

### 3.3. Temporary Override Approval Workflow

A `Trader` who needs short-term headroom raises a limit-adjustment request, naming the target `limit_id`, supplying a strictly positive `requested_delta_usd` (recorded to two decimal places), a one-to-five-hundred-character `justification`, and an `expires_at` ISO 8601 UTC instant strictly greater than the current server clock — a non-future `expires_at` at creation time is rejected with `ERR_EXPIRES_IN_PAST` (HTTP 422). The request is created in `PENDING` status, with `requester_trader_id` copied from the caller's `X-User-ID` (which MUST equal the target limit's `trader_id`) and `approver_user_id` left null until a decision is recorded.

A `RiskOfficer` resolves the request through one of three terminal-or-pending actions, each of which advances state out of `PENDING`. Approval transitions `PENDING` to `APPROVED`, but only when four preconditions hold: the request is still `PENDING`, the officer's `X-User-ID` does NOT equal `requester_trader_id` (segregation of duties — self-approval is rejected with `ERR_SEGREGATION_VIOLATION`), the owning trader's `status` is `ACTIVE`, and the request's `expires_at` is still strictly greater than the server clock at approval time (a request whose `expires_at` has slipped past during the wait is rejected at approval time with `ERR_EXPIRES_IN_PAST`). On a successful approval, the request's `requested_delta_usd` is added to the target `Limit.temporary_override_usd`, `Limit.utilization_pct` is recomputed against the new effective cap, the `approver_user_id` is set to the officer's `X-User-ID`, and a cross-entity cascade then re-evaluates the owning `Position.warning_status`: if it was sitting on `BREACH` and the new percentage lands strictly below 100, it shifts to `WARNING` or `NORMAL` as the recomputed threshold dictates. An audit row of `event_type` `LIMIT_OVERRIDE_APPROVED` is written.

Rejection transitions `PENDING` to `REJECTED` and likewise requires that the rejecter's `X-User-ID` differs from `requester_trader_id`; no side effect on the limit ensues, only an audit row. Sending the request back for revision transitions `PENDING` to `REVISION_REQUESTED`; the revision route has no segregation-of-duties gate, because no commit-level action is taken. From `REVISION_REQUESTED`, only the original requester (matched by `X-User-ID == requester_trader_id`) may resubmit, supplying updated `requested_delta_usd`, `justification` or `expires_at` and the entity's `version` for OCC; the request returns to `PENDING` and the cycle continues. Once a request leaves `PENDING`, it is terminal for the purposes of the approve/reject lane — a second concurrent decision finds the request already decided and is rejected with `ERR_REQUEST_ALREADY_DECIDED` (HTTP 409), which is the deterministic loser-code in §2.11's concurrent-decision scenario.

When an `APPROVED` request's `expires_at` passes — discovered either by the next clock-advance instant or by an explicit sweep — the system transitions the request from `APPROVED` to the terminal `EXPIRED` state, subtracts `requested_delta_usd` back out of `Limit.temporary_override_usd` (so the limit invariantly returns to its baseline cap), recomputes `Limit.utilization_pct`, and re-evaluates `Position.warning_status`: if the new percentage lands at or above 100 and the position was previously `NORMAL` or `WARNING`, the status hops to `BREACH`. An audit row of `event_type` `LIMIT_OVERRIDE_EXPIRED` is written. The expiry side of the workflow is the inverse of approval, by design, so that a sweep run twice at the same logical clock position lands the same state.

### 3.4. Booking Trades and Real-Time Position Recompute

A `Trader` books an FX spot trade by supplying the `pair_code`, a `side` of `BUY` or `SELL`, a strictly positive `notional_base` in base-currency units (two decimal places), the `entry_rate` at execution (strictly positive, six decimal places), and the facing `counterparty_id`. The system stamps `executed_at` with the current server clock as an ISO 8601 UTC instant, and computes `trading_day` as the YYYY-MM-DD calendar date of that clock; both fields are server-stamped and never accepted from the caller. The trade enters `BOOKED` status.

Before a trade is accepted, the system runs the booking pre-flight in priority order. The currency pair must exist, the counterparty must exist, and the calling trader must exist; the trader's `status` must be `ACTIVE`, otherwise the trade is rejected with `ERR_TRADER_SUSPENDED`. The counterparty must not be on the watchlist (the same `ERR_TRADER_SUSPENDED` rule guards this — a watchlisted counterparty cannot face fresh trades). Then the trade's projected impact on `utilization_usd` is computed against the trader's effective caps in both `INTRADAY` and `OVERNIGHT` buckets; if either projection would exceed the bucket's `notional_cap_usd + temporary_override_usd`, the booking is rejected with `ERR_LIMIT_BREACH` (HTTP 409). Then the aggregate notional facing the same counterparty (across all the trader's books and other traders' books) is projected against `Counterparty.credit_limit_usd`; if it would exceed, the booking is rejected with `ERR_COUNTERPARTY_LIMIT_BREACH` (HTTP 409). Two simultaneous trades that pass independently but jointly breach the limit serialise: the first writes, and the second re-evaluates against the post-write state and sees `ERR_LIMIT_BREACH`.

After acceptance, the `Position` for the (`trader_id`, `pair_code`) tuple is recomputed. The position's `net_base` is the signed sum of every `BOOKED` trade in the current trading day for that tuple, processed in `executed_at` ascending order with ties broken by trade `id` ascending; a `BUY` contributes a positive `notional_base`, a `SELL` contributes a negative `notional_base`. The position's `net_open_usd` is `net_base` multiplied by the pair's USD-per-base rate (computed per §2.6's triangulation rule), then rounded half-up to two decimal places. The position's `mtm_pnl_usd` is the unrealised mark-to-market in USD across the same trades, recomputed on every quote arrival. The position carries a `warning_status` derived from the bucket utilisation as described in §3.2.

If the trade's notional in USD lands at ten million USD or more — a threshold that is pinned at the constant ten-million-USD value — the system additionally emits a `ComplianceReport` of `report_type` `LARGE_TRADE` referencing the new trade, at `version` one greater than the prior largest `version` for the same (`report_type`, `reference_trade_id`) pair, defaulting to 1 on first emission. An audit row of `event_type` `TRADE_BOOKED` is written. The aggregate per-desk view returned by the desk-positions retrieval (keyed by `desk_code`) sums the per-trader `Position` rows for traders whose `desk_code` matches.

### 3.5. Stop-Loss Rules, Triggering and Forced Flatten

A `RiskOfficer` arms a stop-loss against a (`trader_id`, `pair_code`) tuple. The rule carries a `rule_mode` of either `PRICE`, `LOSS_AMOUNT`, or `LOSS_RATIO`, a strictly positive `threshold_value` (a violation of either constraint surfaces `ERR_INVALID_STOPLOSS_MODE` at HTTP 422), and an `action` of either `ALERT` or `FORCED_FLATTEN`. The rule is created with its `state` field set to `ARMED` and with `triggered_at` and `triggering_value` both null. The three rule modes are evaluated independently and, when several rules apply on the same quote event, in the order `PRICE` first, then `LOSS_AMOUNT`, then `LOSS_RATIO`.

A `PRICE` rule trips when the current `mid_rate` crosses the `threshold_value` in the direction that hurts the trader. If the trader's `net_base` is positive — they are long the base currency — the trigger fires when `mid_rate` is less than or equal to `threshold_value`; if `net_base` is negative — they are short the base — the trigger fires when `mid_rate` is greater than or equal to `threshold_value`. A flat position does not trip a `PRICE` rule. A `LOSS_AMOUNT` rule trips when the position's `mtm_pnl_usd` is strictly negative AND the absolute value of that mark-to-market loss is greater than or equal to `threshold_value`. A `LOSS_RATIO` rule trips when the position's `mtm_pnl_usd` is strictly negative AND, dividing the absolute loss by the position's absolute notional in USD (computed from `net_base` and the USD-per-base rate per §2.6), the resulting ratio rounded half-up to six decimal places is greater than or equal to `threshold_value`. A `LOSS_RATIO` rule against a flat (zero-notional) position never trips.

On any `ARMED` rule's first crossing, the system transitions the rule from `ARMED` to `TRIGGERED`, stamps `triggered_at` with the server clock, and stamps `triggering_value` with the observed metric — the current `mid_rate` for a `PRICE` rule, the absolute USD loss for `LOSS_AMOUNT`, and the six-decimal-place ratio for `LOSS_RATIO`. An audit row of `event_type` `STOP_LOSS_TRIGGERED` is written.

From `TRIGGERED`, the owning trader (matched on `X-User-ID == trader_id`) acknowledges the event, transitioning it to `ACKNOWLEDGED`; acknowledgement requires that the trader's `status` is still `ACTIVE`. From `ACKNOWLEDGED`, a `RiskOfficer` whose `X-User-ID` is NOT the affected trader's id may override the event (segregation of duties), transitioning it to `OVERRIDDEN`; this writes an audit row of `event_type` `STOP_LOSS_OVERRIDDEN`. An overridden event does NOT immediately re-arm; instead, on the next sweep run, every event sitting in `OVERRIDDEN` is transitioned back to `ARMED`, and its `triggered_at` and `triggering_value` are cleared.

The alternate path out of `TRIGGERED` is execution. A `RiskOfficer` (again, not the affected trader, per segregation of duties) may execute a `TRIGGERED` rule whose `action` is `FORCED_FLATTEN`, transitioning it to `EXECUTED`. Execution books an offsetting `Trade` at the current `mid_rate` that closes `Position.net_base` to zero on the rule's `pair_code`, then cascades: the position is recomputed, the trader's `Limit.utilization_usd` and `utilization_pct` are recomputed, and if the offsetting trade's USD notional lands at ten million USD or more, a `ComplianceReport` of `report_type` `LARGE_TRADE` is emitted at the next `version`. An audit row is written. Executing a rule whose `action` is `ALERT` is not permitted — only `FORCED_FLATTEN` executes; alert-only rules can only progress through acknowledgement and override.

Once a rule is `EXECUTED`, the subsequent sweep transitions it to the terminal `ARCHIVED` state, after which it is read-only and supports no further transitions. Both the override and execute paths racing against the same `TRIGGERED` `FORCED_FLATTEN` rule deterministically resolve to one winner, with the loser receiving `ERR_INVALID_STATE`.

A `RiskOfficer` (or the `MarketDataSystem`) may force a single rule's re-evaluation by name. This is idempotent: a rule that has not crossed remains `ARMED` with no side effect, and a rule that has crossed transitions exactly once.

### 3.6. Counterparty Ratings, Watchlist and Credit Limit

A `ComplianceOfficer` registers a counterparty with a legal `name`, an `external_rating` drawn from the set `AAA`, `AA`, `A`, `BBB`, `BB`, `B`, `CCC`, or `NR`, and an `internal_score` integer in the inclusive range 0 through 100. From these two inputs, the system computes a `rating_band` of `INVESTMENT`, `STANDARD`, `SPECULATIVE`, or `WATCH`, by combining two separate band derivations and taking the worse of the two on a severity scale where `INVESTMENT` is the least severe (rank 0), `STANDARD` rank 1, `SPECULATIVE` rank 2, and `WATCH` the most severe (rank 3).

The external-rating band is fixed by lookup: `AAA` and `AA` map to `INVESTMENT`; `A` and `BBB` map to `STANDARD`; `BB` and `B` map to `SPECULATIVE`; `CCC` and `NR` map to `WATCH`. The internal-score band is a four-tier step: an `internal_score` of 80 or greater is `INVESTMENT`; a score from 60 through 79 inclusive is `STANDARD`; a score from 40 through 59 inclusive is `SPECULATIVE`; a score strictly below 40 is `WATCH`. The final `rating_band` is whichever of the two bands is more severe. The `on_watchlist` boolean is true if and only if `rating_band` is `WATCH`.

From `rating_band` the system reads `credit_limit_usd` from a pinned four-tier table: `INVESTMENT` counterparties carry a one-hundred-million-USD ceiling; `STANDARD` counterparties carry a fifty-million-USD ceiling; `SPECULATIVE` counterparties carry a ten-million-USD ceiling; `WATCH` counterparties carry a one-million-USD ceiling. All four tier amounts are recorded to two decimal places. The ceiling caps aggregate notional facing the counterparty across all traders (see §3.4's pre-flight).

A subsequent rating update — a `ComplianceOfficer` patch carrying a new `external_rating` and/or `internal_score` and the OCC `version` — recomputes both the band derivations, the final `rating_band`, the `credit_limit_usd`, and the `on_watchlist` flag in one atomic step. When the counterparty crosses from a non-`WATCH` band into `WATCH`, `on_watchlist` flips to true, `credit_limit_usd` drops to the one-million-USD `WATCH` tier, and an audit row of `event_type` `RATING_CHANGE` is written; any `SettlementInstruction` already in `GENERATED` against this counterparty stays `GENERATED`, but the gate on the next outbound step (see §3.7) is now active. When a subsequent update lifts the counterparty back out of `WATCH`, `on_watchlist` flips to false and `credit_limit_usd` is recomputed back to the new band's tier. The watchlist toggle is the same cascade in both directions.

### 3.7. Settlement Netting, Sending and Reconciliation

At end-of-day a `SettlementOperator` invokes the netting generator with a `counterparty_id`, a `value_date` (a YYYY-MM-DD string for the settlement value date, typically the next business day), and a caller-supplied `client_request_id` that serves as the idempotency key. The generator scans every `BOOKED` `Trade` whose `counterparty_id` matches and whose `trading_day` is today or earlier, decomposes each trade into two per-currency cash legs, and aggregates per (`counterparty_id`, `value_date`, `ccy`) tuple, producing one `SettlementInstruction` row per tuple. For a `BUY` trade we receive `notional_base` units of the pair's `base_ccy` and we pay `notional_base` times `entry_rate` units of `quote_ccy`; for a `SELL` trade the directions reverse. Trades are processed in `executed_at` ascending order with ties broken by `Trade.id` ascending.

For each emitted `SettlementInstruction`, `gross_pay_amount` is the sum of outbound flows in that currency, `gross_receive_amount` is the sum of inbound flows, and `net_amount` is `gross_pay_amount` minus `gross_receive_amount`, rounded half-up to two decimal places — a positive `net_amount` means the firm pays out, a negative means the firm receives. The instruction is created in `GENERATED` status, carries the `client_request_id` provided by the caller, and starts with `nostro_balance_delta` at zero.

The idempotency key is scoped per (`counterparty_id`, `value_date`, `client_request_id`): a repeat call with the same triple returns the original `SettlementInstruction` set with HTTP 200 (not 201), surfacing `ERR_IDEMPOTENCY_REPLAY`. This is by design the "concurrent generation replay" lane in §2.11.

Once generated, instructions advance through a linear lifecycle. Sending transitions `GENERATED` to `SENT`, but is blocked when the facing counterparty's `on_watchlist` is true — that rejection raises `ERR_COUNTERPARTY_WATCHLIST` (HTTP 409), and clearing the watchlist requires a `ComplianceOfficer` rating update that re-bands the counterparty out of `WATCH`. Confirming a sent instruction transitions `SENT` to `SETTLED`, and on this transition `nostro_balance_delta` is set to the negative of `net_amount` (since a positive `net_amount` is an outbound flow that debits the firm's Nostro account), and every linked `BOOKED` `Trade` transitions to `SETTLED`. Reconciliation transitions `SETTLED` to the terminal `RECONCILED` state and marks the Nostro/Vostro pair reconciled.

The alternate terminal path is failure. A `SettlementOperator` marking a `SENT` instruction as failed transitions it to `FAILED`, writes an audit row of `event_type` `SETTLEMENT_FAILED`, transitions every linked `BOOKED` `Trade` to `FAILED`, and triggers a transitive cascade four levels deep: the facing `Counterparty.internal_score` is decremented by 5 (clamped at a floor of 0), the counterparty's `rating_band` and `credit_limit_usd` are recomputed per the rules in §3.6, the new `on_watchlist` flag is set, and finally, for every `Trader` whose aggregate facing notional now exceeds the lower `credit_limit_usd`, that trader's `status` is flipped to `SUSPENDED`. The confirm-versus-mark-failed race against the same `SENT` instruction is the §2.11 deterministic-winner lane that surfaces `ERR_INVALID_STATE` to the loser.

### 3.8. Risk Reporting — Exposure and Value-at-Risk

A trader's gross exposure is the sum of the absolute USD value of every open position across pairs, with no netting between pairs. Concretely, the system iterates the trader's `Position` rows, takes the absolute value of each row's `net_open_usd`, accumulates the running total, and rounds the final sum half-up to two decimal places.

Net exposure decomposes each pair's position into two single-currency legs in USD terms — a leg in the pair's `base_ccy` and a leg in its `quote_ccy` — and then nets across pairs that share a currency. For each position, the base leg is `net_base` multiplied by the USD-per-`base_ccy` rate, and the quote leg is `net_base` multiplied by the pair's `mid_rate` multiplied by the USD-per-`quote_ccy` rate, with the quote leg signed opposite the base leg. After accumulating per-currency signed totals, the net exposure is the sum of the absolute values of each currency's accumulated leg, rounded half-up to two decimal places. A trader who is long `EURUSD` and short `GBPUSD` will see the USD legs partially offset under this rule; a trader who is long `EURUSD` and long `GBPJPY` will see no netting.

Value-at-risk is computed as a one-day parametric VaR at the 99th confidence percentile, using a single-asset additive aggregation that pessimistically assumes perfect correlation across pairs. The pinned 99th-percentile z-score is 2.326. The evaluation order is fixed: first, for each of the trader's positions with non-zero `net_base`, compute the position's USD exposure as the absolute value of `net_open_usd`; second, compute the per-pair VaR as the exposure multiplied by the pair's `daily_volatility` multiplied by 2.326; third, round each per-pair VaR half-up to two decimal places; fourth, sum the rounded per-pair VaRs to produce the trader's total VaR. This is "round per position, then sum" — pinned in that direction, because the alternative "sum, then round" produces a different final cent for borderline inputs. The output endpoint returns the total under the key `var_99_1d_usd`.

### 3.9. Compliance Reports and Versioning

Two report types fire automatically. The `LARGE_TRADE` report is emitted on any trade whose USD notional lands at or above ten million USD, whether the trade was booked directly by a trader or as the offsetting trade of a forced flatten. The `INTERNAL_CONTROL` report is emitted at end-of-day reconciliation, one per `trading_day`, with `reference_trade_id` defaulting to null and `payload` capturing the day's risk summary. The third type, `SUSPICIOUS_TRANSACTION`, exists in the `report_type` enum and is filed manually by a `ComplianceOfficer`.

Each `ComplianceReport` row carries a `version` integer that is scoped per (`report_type`, `reference_trade_id`) pair and increments by 1 on each amendment, starting at 1 on first emission. The `payload` is the canonical report body (trader, pair, USD notional, counterparty, narrative); `filed_at` and `filed_by_user_id` are server-stamped (`"SYSTEM"` for automatic emissions, the officer's id for manual ones) and immutable thereafter. The list-reports retrieval supports filtering by `report_type` and by `reference_trade_id` query parameters, and returns the latest `version` per pair as the canonical view. A manual filing call accepts `report_type`, an optional `reference_trade_id`, and the `payload`, and the server takes care of computing the next `version`.

### 3.10. End-of-Day Reconciliation Sweep

The end-of-day sweep is invoked by a `RiskOfficer` either by advancing the clock past 17:00 UTC and then running the sweep explicitly, or by running the sweep directly. The sweep walks six steps, in this exact order, idempotently — a sweep run twice for the same logical clock position lands the same final state. Step one: every `LimitAdjustmentRequest` whose `status` is `APPROVED` and whose `expires_at` is at or before the current server clock is transitioned to `EXPIRED`, with the override-reversal cascade described in §3.3. Step two: for each `Trader`, today's `net_open_usd` is snapshotted as the position's end-of-day carry. Step three: `Position.warning_status` is recomputed using the `OVERNIGHT` `Limit` caps. Step four: every `StopLossEvent` sitting in `OVERRIDDEN` is transitioned back to `ARMED` and its `triggered_at` and `triggering_value` are cleared. Step five: every `StopLossEvent` sitting in `EXECUTED` is transitioned to the terminal `ARCHIVED` state and becomes read-only. Step six: one `ComplianceReport` of `report_type` `INTERNAL_CONTROL` is emitted for the trading day at `version` one greater than the prior largest version (defaulting to 1 on the first sweep).

The clock-advance capability and the sweep capability are deliberately decoupled. Advancing the clock re-evaluates time-gated state (a request whose `expires_at` is now in the past is, from the perspective of an approve call, no longer eligible) but does NOT itself walk the six-step cascade. Running the sweep walks the cascade. Tests that need the cascaded view call both in sequence.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications and state transitions return HTTP 200. Read endpoints return 200 with the resource or array in `data`. Errors carry the codes in §5 with the HTTP status shown there. The settlement-generation endpoint is the only mutation that returns HTTP 200 on an idempotent replay (an otherwise-201 endpoint returning 200 for a known `client_request_id`).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /fx-risk/traders | Register a new trader. | RiskOfficer |
| GET | /fx-risk/traders/{id} | Fetch a trader. | RiskOfficer, Trader, ComplianceOfficer |
| GET | /fx-risk/desks/{desk_code}/positions | Aggregated positions across all traders on a desk. | RiskOfficer, ComplianceOfficer |
| POST | /fx-risk/currency-pairs | Register a currency pair. | RiskOfficer |
| POST | /fx-risk/market-data/quote | Push a new mid-market quote. | RiskOfficer, MarketDataSystem |
| POST | /fx-risk/traders/{trader_id}/limits | Create a Limit row for a trader. | RiskOfficer |
| GET | /fx-risk/traders/{trader_id}/limits | List a trader's limits with current utilization. | RiskOfficer, Trader, ComplianceOfficer |
| PATCH | /fx-risk/limits/{id} | Edit baseline notional or stop-loss cap. | RiskOfficer |
| POST | /fx-risk/limit-adjustments | Trader raises a temporary override request. | Trader |
| POST | /fx-risk/limit-adjustments/{id}/approve | RiskOfficer approves a pending request. | RiskOfficer |
| POST | /fx-risk/limit-adjustments/{id}/reject | RiskOfficer rejects a pending request. | RiskOfficer |
| POST | /fx-risk/limit-adjustments/{id}/request-revision | RiskOfficer returns a request for revision. | RiskOfficer |
| PATCH | /fx-risk/limit-adjustments/{id} | Trader resubmits a revision-requested request. | Trader |
| POST | /fx-risk/trades | Book a spot FX trade. | Trader |
| GET | /fx-risk/traders/{trader_id}/positions | List positions for a trader. | RiskOfficer, Trader, ComplianceOfficer |
| GET | /fx-risk/traders/{trader_id}/exposure | Return gross and net USD exposure. | RiskOfficer, Trader, ComplianceOfficer |
| GET | /fx-risk/traders/{trader_id}/var | Return the trader's 1-day 99% VaR in USD. | RiskOfficer, Trader, ComplianceOfficer |
| POST | /fx-risk/stop-loss | Create a stop-loss rule. | RiskOfficer |
| POST | /fx-risk/stop-loss/{id}/evaluate | Force a re-evaluation of one rule. | RiskOfficer, MarketDataSystem |
| POST | /fx-risk/stop-loss/{id}/acknowledge | Trader acknowledges a triggered event. | Trader |
| POST | /fx-risk/stop-loss/{id}/override | RiskOfficer overrides an acknowledged event. | RiskOfficer |
| POST | /fx-risk/stop-loss/{id}/execute | RiskOfficer executes a forced-flatten. | RiskOfficer |
| POST | /fx-risk/counterparties | Register a counterparty. | ComplianceOfficer |
| PATCH | /fx-risk/counterparties/{id} | Update counterparty ratings. | ComplianceOfficer |
| POST | /fx-risk/settlements/generate | Multilateral-netting settlement generator. | SettlementOperator |
| POST | /fx-risk/settlements/{id}/send | Mark a settlement instruction sent. | SettlementOperator |
| POST | /fx-risk/settlements/{id}/confirm | Mark a settlement instruction settled. | SettlementOperator |
| POST | /fx-risk/settlements/{id}/mark-failed | Mark a settlement instruction failed. | SettlementOperator |
| POST | /fx-risk/settlements/{id}/reconcile | Mark a settled instruction reconciled. | SettlementOperator |
| GET | /fx-risk/reports | List filed compliance reports. | ComplianceOfficer, RiskOfficer |
| POST | /fx-risk/reports | File or amend a compliance report. | ComplianceOfficer |
| GET | /fx-risk/audit-log | Query the audit log. | ComplianceOfficer, RiskOfficer |
| POST | /fx-risk/_clock/advance | Advance the server clock. | RiskOfficer |
| POST | /fx-risk/_sweep/run | Run the end-of-day sweep. | RiskOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_VIOLATION | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_REQUEST_ALREADY_DECIDED | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_LIMIT_BREACH | 409 |
| ERR_COUNTERPARTY_LIMIT_BREACH | 409 |
| ERR_COUNTERPARTY_WATCHLIST | 409 |
| ERR_TRADER_SUSPENDED | 409 |
| ERR_EXPIRES_IN_PAST | 422 |
| ERR_INVALID_PAIR_FORMAT | 422 |
| ERR_INVALID_PAGINATION | 422 |
| ERR_IDEMPOTENCY_REPLAY | 200 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_STOPLOSS_MODE | 422 |
