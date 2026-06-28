# Fractional Brokerage API — Product Requirements Document

## 1. Introduction

This document specifies a commission-free, fractional-share brokerage platform in the spirit of consumer trading apps. The system lets retail customers fund accounts through instant deposits, place dollar-based fractional orders alongside conventional share-quantity orders, trade in both regular and extended-hours sessions, and reinvest cash dividends automatically. Behind that consumer-facing simplicity sits a strict ledger-reconciliation engine: every fill cascades into tax lots, settlement legs, cash movements, buying-power recomputation, and — for margin accounts — maintenance and margin-call evaluation.

The platform must keep several derived quantities perfectly consistent at all times. Buying power, account equity, and maintenance excess are never stored by a client; they are recomputed synchronously inside whichever request perturbs them, so that the next read reflects reality immediately. The system also encodes a set of regulatory protocols familiar to U.S. equity trading — T+1 settlement, the pattern-day-trader (PDT) rule, options-suitability approval gates, FIFO and average-cost tax-lot accounting feeding a 1099-B, and margin maintenance — and exposes them as explicit, test-driven state machines rather than background jobs.

Because settlement and corporate actions unfold over calendar time, the platform runs on an explicit logical clock advanced by an operator call rather than wall-clock time. Advancing the clock is the moment at which pending deposits and unsettled trade legs clear. This deterministic clock is what makes the otherwise time-dependent behaviors — settlement, dividend windows, margin cure deadlines, and the rolling PDT window — reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. A request that omits `X-User-Role`, or supplies a value that is not one of the four declared roles, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `AccountHolder`, `ComplianceOfficer`, `ClearingSystem`, and `MarketData`. When a caller is authenticated but the role is not permitted for the requested operation — or when an `AccountHolder` attempts to act on an account it does not own — the request is rejected with `ERR_FORBIDDEN`.

The `AccountHolder` role is entity-backed. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's `account_id` (or, for path-addressed accounts, the `Account.id`) to `X-User-ID`. An `AccountHolder` may read and act only on resources belonging to its own account.

The remaining three roles are opaque operator identities. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ClearingSystem`: `X-User-ID` is an opaque operator identifier for the clearing, settlement, and corporate-actions back office, recorded but never matched to an entity `id`. Likewise, when `X-User-Role` is `MarketData`, `X-User-ID` is an opaque operator identifier for the market-data feed, recorded but not compared to any entity's `id`. These three operator roles are not subject to per-account ownership checks; their authorization is purely role-based per the matrix in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of matching records before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created. For resources that can be modified after creation, `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation, and `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of that resource.

Two entities are reference/configuration records that never mutate after creation and therefore carry only `id` and `created_at` — they expose neither `updated_at` nor `version`. The first is the `Security`, a tradable instrument definition; note that the quote endpoint does update a security's `last_price_cents` in place, but the security still exposes only `id` and `created_at` and does not carry a `version`. The second is the `Fill`, an immutable execution record. All ten other entities — `Account`, `Deposit`, `Order`, `Settlement`, `Position`, `Lot`, `Disposal`, `DividendEvent`, `OptionsApproval`, and `MarginCall` — carry the full set including `updated_at` and `version`.

### 2.5. Logical Clock and Monetary Precision

The platform keeps a single logical clock that starts at exactly `2026-01-01T00:00:00Z` on server startup. Before any advance, every time-dependent computation reads exactly this default instant; the clock never falls back to wall-clock time. Only an operator advance moves the clock, and that advance is also the trigger for the settlement sweep described in §3.

All monetary values are integers denominated in whole cents; there are no fractional cents and no floating-point money. Wherever a calculation produces a non-integer cent amount — for instance multiplying a fractional share quantity by a per-share price in cents — the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). Share quantities, by contrast, may be fractional and are tracked to six decimal places; where the specification truncates a share quantity (notably during dividend reinvestment), it truncates toward zero at the sixth decimal place rather than rounding. Maintenance rates and PFOF rebates are expressed in basis points, where one basis point is one ten-thousandth, so a rate or rebate applied to a cent amount divides the basis-point figure by 10000 and rounds the product half up to whole cents.

### 2.6. Nested Resource Retrieval and Existence Ordering

Several read endpoints address a parent resource in the path and then enumerate or fetch a child — fills under an order, lots and disposals under a position, deposits/settlements/dividends/options-approvals/margin-calls under an account, and a specific margin call under an account. For any such path, the system validates the identifiers left-to-right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource. A request for a child under a parent that does not exist fails on the parent before the child is ever consulted. This left-to-right existence check is the third validation gate overall, applied after authentication and authorization but before any body-shape or business rule.

### 2.7. Validation Ordering

When a single endpoint is guarded by several checks, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The global ordering is: first, authentication — the `X-User-Role` header must be present and one of the declared roles, else `ERR_UNAUTHENTICATED`. Second, authorization — the role must be permitted for the operation and, for an `AccountHolder`, must own the target account, else `ERR_FORBIDDEN`. Third, existence — every referenced id (in path or body) must resolve, validated left-to-right, else `ERR_NOT_FOUND`. Fourth, request well-formedness — required fields present, enum values legal, monetary amounts strictly positive, and for orders exactly one of notional or quantity supplied, else `ERR_INVALID_REQUEST`. Fifth, optimistic-concurrency version match where required, else `ERR_STALE_ACCOUNT_VERSION`. Sixth, target-resource state legality for the requested transition, else `ERR_INVALID_STATE`. Only after all six of these gates pass does the system evaluate the operation-specific business rules described in §3 (frozen-account, restriction, options-level, order-shape, share-sufficiency, buying-power, and the various temporal and fiscal checks), each in the order detailed alongside its workflow.

### 2.8. Optimistic Concurrency Control

Two write operations protect against acting on a stale account snapshot by requiring an optimistic-concurrency version token. Placing an order requires the request to carry `expected_account_version` holding the client's last observed `version` of the target `Account`; if that value does not equal the account's current `version`, the order is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412. This guards the case where another buying-power-consuming write (such as a prior BUY that reserved buying power and advanced the account version) landed after the client read the account but before this order arrived, leaving the client's view of `buying_power_cents` stale; the order is refused rather than reserving against an out-of-date balance. Deciding an options application likewise requires `expected_account_version` to match the account's current `version`, and a mismatch is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412; this prevents two approvals from each granting against the same stale account snapshot after one of them has already raised `options_level` and bumped the version. No other endpoint takes a version field; endpoints not named here perform no OCC check.

### 2.9. Account Derived Quantities and the Trading Posture

An `Account` is identified by a unique `holder_email` and is opened as one of two `account_type` values, `CASH` or `MARGIN`, defaulting to `CASH`. Every account also tracks a manual `compliance_hold` boolean that defaults to false. Beyond these inputs, the account carries a family of computed quantities that the system keeps mutually consistent after every event that could perturb them: `settled_cash_cents` (cash that has fully cleared T+1, the only cash a `CASH` account may spend), `unsettled_cash_cents` (the net of pending settlement legs not yet cleared, which may be negative when cash is owed or positive when cash is incoming), `instant_credit_cents` (provisional buying power granted from pending instant deposits), `buying_power_cents` (spendable buying power), `account_equity_cents`, `maintenance_requirement_cents`, `maintenance_excess_cents`, `day_trade_count`, `pdt_flagged`, `options_level`, and `trading_status`. All of these default to their zero/false/`ACTIVE` baselines at account open: equity, all cash fields, buying power, and `day_trade_count` start at 0, `pdt_flagged` starts false, `options_level` starts at 0, and `trading_status` starts at `ACTIVE`.

The `trading_status` is a compound posture derived after every event that changes equity, maintenance, the PDT flag, or the compliance hold. It takes one of four values, evaluated by a strict first-match-wins priority. First, if `compliance_hold` is true, the posture is `FROZEN`. Otherwise, if an open margin call (a `MarginCall` in status `ISSUED`) exists for the account, the posture is `MARGIN_CALL`. Otherwise, if `pdt_flagged` is true or `maintenance_excess_cents` is below zero, the posture is `RESTRICTED_CLOSING_ONLY`. Otherwise, the posture is `ACTIVE`. Because the posture is derived, it is recomputed in place rather than set by a client, and any recomputation that changes it (along with any change to a computed cash, equity, or buying-power field) is a mutation that refreshes the account's `updated_at` and increments its `version`.

### 2.10. Cascade and Reconciliation Principle

Many operations mutate more than one entity. A trade fill is the densest example: it creates a `Fill`, advances the order's `order_status`, opens or consumes tax `Lot` records, recomputes the `Position`, may create one or more `Disposal` records, creates a `Settlement` leg, and then recomputes the account's equity, maintenance, buying power, and trading posture. Whenever a side effect changes a derived account quantity, the account's `version` increments and `updated_at` refreshes as part of the same request. The platform never defers these recomputes to a background process — every cascade completes synchronously within the triggering request, so a subsequent read observes a fully reconciled state. Where a settlement leg, deposit reversal, or dividend reversal undoes a prior provisional effect, the reversal is a compensating mutation that runs the same recompute chain in the opposite direction.

## 3. Business Logic & Workflows

### 3.1. Account Funding: Deposits, Instant Credit, and Settlement

An `AccountHolder` funds an account by submitting a deposit carrying `amount_cents` and an optional `instant_eligible` flag (defaulting to true). The deposit records its `account_id`, begins life in status `PENDING`, and is assigned a `settles_on` equal to the logical clock date plus one business day (T+1). The amount must be strictly positive; a non-positive amount is a malformed request rejected with `ERR_INVALID_REQUEST`.

When instant credit is requested, the system grants a provisional credit immediately, but only up to a cumulative ceiling. The relevant ceiling, `INSTANT_CAP_CENTS`, is one hundred thousand dollars — that is, ten million cents of cumulative provisional credit per account. To compute the grant, the system sums `instant_credit_granted_cents` across the account's deposits that are still `PENDING` (deposits already `SETTLED` or `REVERSED` do not count) to obtain the outstanding provisional credit, then subtracts that from the ceiling to find the remaining headroom. The requested amount (the deposit's `amount_cents` when instant-eligible, otherwise zero) is compared to the headroom: if the request exceeds the headroom it is rejected with `ERR_INSTANT_LIMIT_EXCEEDED`, and the boundary is inclusive — a request exactly equal to the remaining headroom is allowed, while a request one cent greater is rejected. Otherwise `instant_credit_granted_cents` is set to the requested amount and the account's `instant_credit_cents` increases by that same amount. Each deposit also exposes its `instant_credit_granted_cents` and its `status`. Creating the deposit recomputes the account's `buying_power_cents` and increments the account's `version` by one.

Deposits clear when the logical clock crosses the deposit's `settles_on`. On the operator clock advance, any `PENDING` deposit whose `settles_on` is at or before the new clock instant transitions to `SETTLED`: the deposit's `amount_cents` is added to `settled_cash_cents`, the provisional `instant_credit_granted_cents` is removed from the account's `instant_credit_cents` (the provisional credit is retired now that real settled cash has arrived), and buying power is recomputed — for a `CASH` account the net effect on spendable buying power at settle is zero, because real cash replaces an equal amount of provisional credit. Alternatively, the `ClearingSystem` may report an ACH return on a still-`PENDING` deposit, transitioning it to `REVERSED`: the provisional `instant_credit_granted_cents` is clawed back from `instant_credit_cents`, buying power is recomputed (which may drive it negative and in turn trigger a maintenance/restriction recompute), and the account `version` increments. A deposit that has already left `PENDING` cannot be reversed; attempting a transition on a wrong-status deposit is rejected with `ERR_INVALID_STATE`.

### 3.2. Securities and Market Data

The tradable universe is defined by `Security` records, each registered by either the `ClearingSystem` or a `ComplianceOfficer`. A security carries a unique `symbol`, an `instrument_type` of `EQUITY` or `OPTION`, a current `last_price_cents`, a `fractional_enabled` flag (default true) governing whether dollar-based fractional orders are allowed, a `maintenance_rate_bps` margin maintenance rate in basis points (default 2500, i.e. twenty-five percent), a `required_options_level` giving the minimum account options level needed to trade this instrument (default 0, used only for options; equities use 0), and an `extended_hours_eligible` flag (default true) controlling whether extended-hours sessions accept orders for it.

The `MarketData` feed (and the `ClearingSystem`) pushes a fresh quote by updating a security's `last_price_cents`. A quote update is not a passive write: for every `Position` held on that security, the system recomputes the position's `market_value_cents`, then recomputes each affected account's equity, maintenance requirement, maintenance excess, buying power, and finally its trading posture. A quote that pushes an account's `maintenance_excess_cents` below zero is exactly the kind of event that can flip a `MARGIN` account's posture from `ACTIVE` into `RESTRICTED_CLOSING_ONLY`.

### 3.3. Placing an Order

An `AccountHolder` places an order against their account by supplying `account_id`, `security_id`, `side` (`BUY` or `SELL`), `order_type` (`MARKET` or `LIMIT`), `expected_account_version`, and exactly one of `notional_cents` (a dollar-based fractional size in cents) or `quantity` (a possibly-fractional share count). The order may also carry `limit_price_cents`, a `session` of `REGULAR` or `EXTENDED` (default `REGULAR`), and an `is_closing` flag (default false) that marks a SELL permitted even when the account is restricted to closing activity. A fresh order begins in `order_status` `PENDING_NEW`. Beyond these inputs the order tracks computed fields: `filled_quantity` and `filled_notional_cents` accumulate across fills (both default 0), `reserved_buying_power_cents` holds the buying power locked while a BUY is live (default 0), `pfof_venue` records the routing venue chosen for the order, and `opened_day_trade` flags whether the order's fill paired with a same-symbol same-session opposite leg to count as a day trade.

Exactly one of `notional_cents` and `quantity` must be provided; supplying both, or neither (both zero), is a malformed body rejected with `ERR_INVALID_REQUEST`. The order then passes through the operation-specific gates in this order. If the account's posture is `FROZEN`, all order placement is blocked with `ERR_ACCOUNT_FROZEN`. If the posture is `RESTRICTED_CLOSING_ONLY` or `MARGIN_CALL`, an opening BUY is blocked and only a SELL marked `is_closing` is accepted, with the rejection carried as `ERR_RESTRICTED_CLOSING_ONLY`; equivalently, an opening BUY requires the posture to be `ACTIVE`. For an `OPTION` security, the account's `options_level` must be at least the security's `required_options_level`, else the order is rejected with `ERR_OPTIONS_LEVEL_INSUFFICIENT`. A `LIMIT` order requires `limit_price_cents` to be strictly greater than zero, else `ERR_LIMIT_PRICE_REQUIRED`.

Order-shape constraints layer on top. A notional (dollar-fractional) order is permitted only on a security whose `fractional_enabled` is true, otherwise it is rejected with `ERR_FRACTIONAL_NOT_ALLOWED`; and a notional order must additionally be `MARKET` order_type in a `REGULAR` session, otherwise it is rejected with `ERR_FRACTIONAL_ORDER_CONSTRAINT`. An `EXTENDED`-session order is accepted only when the security is `extended_hours_eligible` and the order_type is `LIMIT`; an extended order that is not a limit, or whose security is not extended-hours eligible, is rejected with `ERR_EXTENDED_HOURS_LIMIT_ONLY`. For a SELL, the requested share count must not exceed the available `Position.quantity`, else `ERR_INSUFFICIENT_SHARES`. Finally, for a BUY, the required cash to reserve must not exceed the account's `buying_power_cents`, else `ERR_INSUFFICIENT_BUYING_POWER`. Note that the optimistic-concurrency check on `expected_account_version` (see §2.8) and the existence, well-formedness, and state gates of §2.7 all precede these business gates; when several apply, the lower-numbered priority wins, so a frozen account surfaces `ERR_ACCOUNT_FROZEN` ahead of a restriction, options, shape, share, or buying-power failure.

When every gate passes, the order transitions `PENDING_NEW → ACCEPTED`: a routing venue is selected (see §3.4), and for a BUY the required cash is locked as `reserved_buying_power_cents` and the account's `buying_power_cents` decreases by that reservation. Placing an order increments the account's `version` by one. If any precondition fails the order is instead recorded as `PENDING_NEW → REJECTED` with no reservation and no position change.

### 3.4. Order Routing, Reservation, and the PFOF Rebate

Routing chooses a payment-for-order-flow venue when the order is accepted. The candidate venues are `VENUE_A`, `VENUE_B`, and `VENUE_C`, each carrying a rebate in basis points: `VENUE_A` at 30, `VENUE_B` at 20, and `VENUE_C` at 10. For an `EQUITY` instrument all three venues are eligible; for an `OPTION` instrument only `VENUE_A` and `VENUE_B` are eligible. The selector scores each eligible venue by its rebate in basis points and picks the highest score, so a higher rebate ranks first; ties (which cannot arise among these distinct rebates) break by venue name in ascending lexicographic order, with `VENUE_A` before `VENUE_B` before `VENUE_C`. Because `VENUE_A` is always eligible the eligible set is never empty and no fallback is needed. The chosen venue is recorded as the order's `pfof_venue`.

The cash to reserve for a BUY, and the rebate that later accrues, are computed in a pinned order to break their apparent circularity. First the system computes the required gross trade value: for a notional order it is simply the `notional_cents`; for a quantity order it is the `quantity` multiplied by a reference price and rounded half up to whole cents, where the reference price is `limit_price_cents` for a `LIMIT` order and the security's `last_price_cents` otherwise. Second, the routing venue is selected over that required gross value. Third, the `reserved_buying_power_cents` is set equal to the required gross value — the rebate never reduces the reservation. Fourth and only later, on each fill, the per-fill `pfof_rebate_cents` is computed as the fill's `gross_value_cents` multiplied by the chosen venue's rebate basis points divided by 10000, rounded half up to whole cents; this rebate is credited to settled cash at settlement and is never pre-netted against the reservation. Pinning the reservation before any rebate guarantees the buying-power check never double-counts the rebate.

Buying power itself is recomputed after any deposit, settlement, fill, dividend, reversal, quote update, or order reservation/release, using one of two variants keyed by `account_type`. For a `CASH` account, `buying_power_cents` equals `settled_cash_cents` plus `instant_credit_cents`, minus the sum of `reserved_buying_power_cents` over all live BUY orders; unsettled cash is never spendable in a cash account. For a `MARGIN` account, the system takes the account equity, subtracts the maintenance requirement, multiplies that excess by the leverage multiplier of 2, floors the result at zero, and then subtracts the same sum of `reserved_buying_power_cents` over live BUY orders. A live BUY order is one whose `order_status` is `ACCEPTED` or `PARTIALLY_FILLED`. Buying power is carried as a whole-cent integer.

### 3.5. Executions, Tax Lots, and Cost Basis

The `ClearingSystem` reports an execution against an accepted order by submitting a `Fill` carrying `fill_quantity` (shares executed in this fill, strictly positive and possibly fractional) and `fill_price_cents` (the execution price per share). A fill cannot be reported against a terminal order — one already `FILLED`, `REJECTED`, or `CANCELLED` — and such an attempt is rejected with `ERR_CANNOT_FILL_TERMINAL`. Each fill computes its `gross_value_cents` as `fill_quantity` multiplied by `fill_price_cents`, rounded half up to whole cents, and its `pfof_rebate_cents` from the order's venue as described above. The fill records the `order_id` of the order it executes against, carries a denormalized `account_id` copied from that parent order, and, once the settlement leg is created, a `settlement_id` referencing that leg; fills for an order are discovered by listing the order's fills, and the settlement leg is discovered by filtering settlements by `fill_id`.

A fill advances the order along its lifecycle. From `ACCEPTED`, a fill whose cumulative `filled_quantity` reaches the order's target quantity completes the order to `FILLED`, while a fill that leaves cumulative quantity below target moves it to `PARTIALLY_FILLED`; a further fill from `PARTIALLY_FILLED` that reaches the target completes it to `FILLED`. On every such fill, `filled_quantity` increases by `fill_quantity` and `filled_notional_cents` increases by the fill's `gross_value_cents`. For a BUY, the fill opens a new tax `Lot` on the position (or extends the position's lot set), cascading into a recompute of `Position.quantity` and `average_cost_cents`. For a SELL, the fill creates one or more `Disposal` records consuming open lots, cascading into a recompute of `Position.quantity` and `realized_pl_cents`. Every fill also creates a `Settlement` leg in status `UNSETTLED` dated T+1, and recomputes the account's equity, maintenance, buying power, and trading posture, incrementing the account `version`. When a fill completes a BUY to `FILLED`, any leftover reserved buying power — the original reservation minus the cash actually consumed by fills — is released back to the account; a partial fill releases nothing yet.

Each BUY fill opens a `Lot` recording its `position_id`, an `acquired_at` set to the logical-clock time the opening fill executed (which is also the FIFO ordering key), an `original_quantity` equal to the shares acquired, a `remaining_quantity` (initially equal to original, reduced by later disposals), and a `cost_per_share_cents` equal to the opening fill's `gross_value_cents` divided by its `fill_quantity`, rounded half up to whole cents. A lot begins `OPEN`. A disposal that consumes part of a lot — disposing fewer shares than the lot's `remaining_quantity` — moves it to `PARTIALLY_CLOSED` and reduces `remaining_quantity`; a disposal that consumes exactly the whole remaining quantity moves the lot to `CLOSED` with `remaining_quantity` driven to zero, whether that happens from `OPEN` or from `PARTIALLY_CLOSED`.

A `Position` is keyed uniquely per account-and-security pair, recording its `account_id`, `security_id`, a computed `quantity` (the sum of `remaining_quantity` over its open lots), a computed `average_cost_cents` (total open cost basis divided by quantity, rounded half up), a `cost_basis_method` of `FIFO` or `AVERAGE` pinned when the position first opens (default `FIFO`) that governs which disposal variant applies, a computed `market_value_cents` (the position `quantity` multiplied by the security's `last_price_cents`, rounded half up), a cumulative `realized_pl_cents`, and a `drip_enabled` flag (default false) toggled by its holder.

Cost basis is realized on every SELL disposal. Each `Disposal` records its `position_id`, the `fill_id` of the SELL fill that drove it, a `lot_id` (the consumed lot under FIFO, null under AVERAGE), the `quantity` disposed, the `proceeds_cents`, the `cost_basis_cents`, the realized `realized_pl_cents`, and a `term` of `SHORT` or `LONG`. Proceeds are the disposed quantity multiplied by the SELL fill price per share, rounded half up to whole cents. The two basis variants diverge as follows. Under the FIFO variant — applied when the position's `cost_basis_method` is `FIFO` — the system consumes open lots oldest-first, ordered by ascending `acquired_at` then `created_at`, considering only `OPEN` and `PARTIALLY_CLOSED` lots and excluding `CLOSED` ones; for each consumed slice of quantity taken from a lot, the slice basis is that slice quantity multiplied by the lot's `cost_per_share_cents` rounded half up, and the disposal's `cost_basis_cents` is the sum of those per-slice bases, with the specific consumed `lot_id` recorded. Under the AVERAGE variant — applied when `cost_basis_method` is `AVERAGE` — the basis is simply the disposed quantity multiplied by the position's `average_cost_cents`, rounded half up, with `lot_id` left null. In both variants the realized profit or loss is the proceeds minus the cost basis, and this figure flows to the 1099-B. The `term` is `SHORT` when the holding period from acquisition to the current clock instant is at most 365 days and `LONG` when it exceeds 365 days; under FIFO the holding period is measured from the consumed lot's `acquired_at`, and under AVERAGE it is measured from the earliest contributing lot's `acquired_at`. An accepted order may also be cancelled by its holder while non-terminal; cancellation moves it from `ACCEPTED` or `PARTIALLY_FILLED` to `CANCELLED`, releasing the reserved buying power (the remaining unfilled portion's reservation) back to the account and incrementing the account `version`.

### 3.6. Settlement and the T+1 Cash Leg

Settlement is a parallel state dimension that evolves independently of the order's own lifecycle — an order may sit at `FILLED` while its settlement leg is still `UNSETTLED`. Each `Settlement` records its `account_id`, the originating `fill_id`, a `direction` of `DEBIT` (a BUY, where cash leaves the account) or `CREDIT` (a SELL, where cash arrives), an `amount_cents` equal to the originating fill's `gross_value_cents`, a `settles_on` of trade date plus one business day, and a `status` that begins `UNSETTLED`. Settlement legs for an account are discovered by listing the account's settlements, optionally filtered by `fill_id` or `status`.

Legs clear on the operator clock advance: when the logical clock date reaches or passes a leg's `settles_on`, the `ClearingSystem` sweep moves it `UNSETTLED → SETTLED`. For a `DEBIT` leg, settling subtracts the `amount_cents` from `settled_cash_cents` and adds it back to `unsettled_cash_cents` (which had carried the negative reserve); for a `CREDIT` leg, settling adds the `amount_cents` to `settled_cash_cents` and subtracts it from `unsettled_cash_cents`. Buying power is then recomputed. A leg whose `settles_on` is still in the future is left `UNSETTLED`; an explicit attempt to settle a not-yet-due leg is rejected with `ERR_SETTLEMENT_NOT_DUE`. Alternatively, the `ClearingSystem` may fail a still-`UNSETTLED` leg, moving it `UNSETTLED → FAILED` and reversing the provisional cash and position effects of the originating fill as a compensation; this is rejected with `ERR_INVALID_STATE` if the leg is not `UNSETTLED`, and the failure increments the account `version`.

### 3.7. Dividends and Dividend Reinvestment (DRIP)

The `ClearingSystem` announces a cash dividend for a position by supplying the `account_id`, the `position_id` earning it, a `rate_per_share_cents` (the declared per-share cash dividend), and an `ex_date`. On announce the event records its `record_quantity` as a snapshot of the position's `quantity` at announce time, computes a `gross_amount_cents` as the `record_quantity` multiplied by `rate_per_share_cents` rounded half up to whole cents, sets its computed `window_end` to `ex_date` plus the dividend window of 30 calendar days, initializes `reinvest_quantity` and `residual_cash_cents` to 0, and begins in status `ANNOUNCED`. The dividend's processing window is the half-open calendar interval from `ex_date` up to but not including `window_end`. Two non-terminal dividends — those in `ANNOUNCED` or `PAID` status — for the same position may not have overlapping windows: a new dividend overlaps an existing non-terminal dividend for that position when the new `ex_date` is strictly before the existing window's end and the existing `ex_date` is strictly before the new `window_end`. Because the interval is half-open, windows that merely touch at an endpoint do not overlap. Any overlap rejects the announcement with `ERR_DIVIDEND_WINDOW_OVERLAP`. Dividend events for an account are discovered by listing the account's dividends.

A dividend proceeds through pay, then optionally reinvest, or alternatively reverse. Paying moves it `ANNOUNCED → PAID`: this requires the event to be `ANNOUNCED` with a `record_quantity` greater than zero, adds the `gross_amount_cents` to `settled_cash_cents`, recomputes buying power, and increments the account `version`. Attempting to pay, reinvest, or reverse a dividend that is not in the appropriate status is rejected with `ERR_DIVIDEND_NOT_PAYABLE`. From `PAID`, the dividend may be reinvested (`PAID → REINVESTED`) when the position's `drip_enabled` is true and the computed `reinvest_quantity` is greater than zero; if DRIP is not enabled the reinvest is rejected with `ERR_DRIP_NOT_ENABLED`, and if the gross dividend buys less than a single fractional share at the current price — yielding a `reinvest_quantity` of zero — it is rejected with `ERR_DRIP_BELOW_MINIMUM`. Reinvestment is computed in a pinned rounding order. First the gross dividend is taken as the already-rounded `gross_amount_cents` (rounded once, per event, at announce). Second, the `reinvest_quantity` is the gross amount divided by the security's `last_price_cents`, truncated to six decimal places — share quantities are truncated, never rounded up. Third, the spent cash is the `reinvest_quantity` multiplied by `last_price_cents`, rounded half up to whole cents. The `residual_cash_cents` is the gross amount minus that spend; because shares are truncated first, the residual is always at least zero. Reinvesting subtracts the spend (gross amount minus residual) from `settled_cash_cents`, opens a new `Lot` for the `reinvest_quantity` (cascading into a recompute of `Position.quantity` and `average_cost_cents`), leaves the `residual_cash_cents` in settled cash, and increments the account `version`. Alternatively, a `PAID` dividend that has not yet been reinvested may be reversed (`PAID → REVERSED`) as a correction, which subtracts the `gross_amount_cents` back out of `settled_cash_cents` to compensate the earlier pay credit and increments the account `version`.

### 3.8. Options Approval and Suitability

An `AccountHolder` applies for an options trading level by submitting an application carrying `account_id`, a `requested_level`, a `stated_experience_years`, and a `liquid_net_worth_cents`. The requested level must be 1, 2, or 3; a requested level outside that range is rejected with `ERR_OPTIONS_LEVEL_TOO_HIGH`. The application records a computed `granted_level` (initially 0) and begins in status `SUBMITTED`. Options approvals for an account are discovered by listing the account's options approvals.

A `ComplianceOfficer` decides the application by supplying a `decision` and the `expected_account_version` for the OCC check described in §2.8. On an approve decision the system computes a suitability cap from the application's self-reported figures, using these thresholds: the level-3 boundary requires at least 3 years of stated experience and a liquid net worth of at least one hundred thousand dollars (ten million cents); the level-2 boundary requires at least 2 years of experience; the level-1 boundary requires at least 1 year of experience. Concretely, the base cap is 3 when stated experience is at least 3 years and liquid net worth is at least ten million cents; otherwise it is 2 when experience is at least 2 years; otherwise 1 when experience is at least 1 year; otherwise 0. The net-worth gate matters only at the level-3 boundary. The `granted_level` is then the smaller of the `requested_level` and that base cap. If the granted level is greater than zero the application transitions `SUBMITTED → APPROVED`, and the account's `options_level` is raised to the larger of its current value and the granted level, cascading into option-order eligibility; placing or deciding raises the account `version`. If the suitability calculation grants zero, or the officer's decision is to deny, the application transitions `SUBMITTED → DENIED` with the account's `options_level` unchanged. An approved application may later be revoked (`APPROVED → REVOKED`), upon which the account's `options_level` is reset to the highest level still held under another `APPROVED` application for that account (or 0 if none remains), again incrementing the account `version`.

### 3.9. Margin Maintenance, the PDT Rule, and Margin Calls

Maintenance is recomputed after every fill, quote update, deposit, settlement, dividend, or liquidation. The account equity is `settled_cash_cents` plus `unsettled_cash_cents` plus the sum over positions of each position's `market_value_cents`, where each `market_value_cents` is the position `quantity` multiplied by the security's `last_price_cents` rounded half up. The maintenance requirement is the sum over positions of each position's `market_value_cents` multiplied by the security's `maintenance_rate_bps` divided by 10000, rounded half up to whole cents. The maintenance excess is the account equity minus the maintenance requirement; while the maintenance excess is below zero a margin call is warranted, and a negative excess is what flips the posture toward restriction.

The pattern-day-trader rule tracks day trades in a rolling window. A day trade is a same-security open-and-close (a BUY-to-open and SELL-to-close, or a short open and cover) of the same security within the same logical-clock calendar date. On a closing fill, if an opening fill of the same security exists with the same logical-clock date, the system increments `day_trade_count` and sets that order's `opened_day_trade` to true. The window is the trailing 5 business days from the current clock date inclusive, and `day_trade_count` counts day trades whose detection date falls within that window. The account becomes `pdt_flagged` when the `day_trade_count` reaches the PDT threshold of 4 and the `account_equity_cents` is below the PDT minimum equity of twenty-five thousand dollars (two and a half million cents). The boundaries are exact: exactly 4 day trades flags, and equity of exactly twenty-five thousand dollars does not flag because the minimum-equity test clears at or above that figure.

A `MarginCall` is issued by the `ClearingSystem` against an account in deficiency. Issuance requires the account's `maintenance_excess_cents` to be below zero, else it is rejected with `ERR_NO_DEFICIENCY`. The cure window is single-occupancy with capacity one: a new call collides if any `MarginCall` in status `ISSUED` already occupies the account's cure window — that is, an existing issued call whose closed interval from its creation time through its `cure_by` still contains the current clock, where the upper bound `cure_by` is inclusive — and such a collision is rejected with `ERR_MARGIN_CALL_ACTIVE`; a second issued call may never coexist with a first. On successful issuance the call records its `account_id`, a `deficiency_cents` equal to the absolute value of `maintenance_excess_cents` at issuance, a `cure_by` of the logical clock date plus the margin cure period of 4 business days, and a `status` of `ISSUED`, and the account's trading posture moves to `MARGIN_CALL`. Margin calls for an account are discovered by listing the account's margin calls.

A margin call resolves in one of two ways. It is met automatically — transitioning `ISSUED → MET` — when `maintenance_excess_cents` returns to zero or above after a deposit, a settle, or a closing SELL fill; meeting it recomputes the trading posture, which may return the account to `ACTIVE`. Alternatively the `ClearingSystem` may liquidate it (`ISSUED → LIQUIDATED`) once the deadline has passed: liquidation requires the logical clock date to be strictly past `cure_by` and the `maintenance_excess_cents` to still be below zero, and an attempt to liquidate before `cure_by` or when the excess is already non-negative is rejected with `ERR_MARGIN_CALL_NOT_DUE`. Liquidation force-creates closing SELL fills until the maintenance excess is restored to zero or above — cascading into disposals, position updates, realized P/L, and settled cash — then recomputes the trading posture.

### 3.10. The Trading Posture Transitions and Compliance Freeze

The account's `trading_status` posture moves among its four values as the underlying conditions change, always honoring the first-match-wins priority of §2.9. From `ACTIVE`, the posture moves to `RESTRICTED_CLOSING_ONLY` when a recompute after a fill or quote drives `maintenance_excess_cents` below zero or sets the PDT flag, provided the compliance hold is clear and no issued call yet exists; while restricted, opening BUY orders are rejected with `ERR_RESTRICTED_CLOSING_ONLY` and only closing SELLs are accepted. From `ACTIVE` or from `RESTRICTED_CLOSING_ONLY`, the posture moves to `MARGIN_CALL` when the clearing system issues a call against an account whose `maintenance_excess_cents` is below zero and whose compliance hold is clear, which creates the issued call, blocks opening BUYs, and still allows closing SELLs. The posture returns from `MARGIN_CALL` to `ACTIVE` when the call is met (a deposit or closing sells restoring the excess to zero or above) provided no other issued call remains, the PDT flag is clear, and the compliance hold is clear; meeting re-enables opening BUYs. Likewise the posture returns from `RESTRICTED_CLOSING_ONLY` to `ACTIVE` once `maintenance_excess_cents` is at or above zero and the PDT flag is cleared and the compliance hold is clear, re-enabling opening BUYs.

The compliance freeze is a manual override owned by the `ComplianceOfficer`, who sets or clears an account's `compliance_hold`. Setting the hold true drives the posture to `FROZEN` from `ACTIVE`, `RESTRICTED_CLOSING_ONLY`, or `MARGIN_CALL`, blocking all order placement with `ERR_ACCOUNT_FROZEN` and incrementing the account `version` by one. Clearing the hold lifts the freeze: if at that point no issued call remains, the PDT flag is clear, and `maintenance_excess_cents` is at or above zero, the account returns from `FROZEN` to `ACTIVE` with order placement re-enabled and the `version` incremented; but if instead the PDT flag is still set or `maintenance_excess_cents` is still below zero (with no issued call), clearing the hold returns the account from `FROZEN` to `RESTRICTED_CLOSING_ONLY`, where closing SELLs are re-enabled while opening BUYs remain blocked. Each compliance-hold change recomputes the posture and increments the account `version`.

### 3.11. The Operator Clock

The `ClearingSystem` advances the logical clock by supplying a target instant as `to_iso8601`. Setting the clock runs the settlement sweep in the same request: every `PENDING` deposit and every `UNSETTLED` settlement leg whose `settles_on` is at or before the new clock instant is settled per the rules in §3.1 and §3.6, and the affected accounts are recomputed. This capability is the deterministic substitute for wall-clock time and is the only mechanism by which T+1 settlement, dividend windows, margin cure deadlines, and the rolling PDT window advance. The advance itself returns no resource body.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (opening an account, registering a security, recording a deposit, placing an order, reporting a fill, announcing a dividend, applying for options, or issuing a margin call) return `201 Created`. Operations that modify an existing resource, drive a state transition on it, or perform an administrative action (quotes, cancels, settles/fails, dividend lifecycle steps, options decisions, liquidations, the compliance hold, the DRIP toggle, and the clock advance) return `200 OK`. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Open a brokerage account | AccountHolder, ComplianceOfficer |
| GET | `/accounts/{id}` | Get an account (computed equity/buying-power/maintenance) | AccountHolder, ComplianceOfficer, ClearingSystem |
| PATCH | `/accounts/{id}/compliance-hold` | Set or clear the compliance freeze | ComplianceOfficer |
| POST | `/accounts/{id}/deposits` | Instant deposit with optional provisional credit | AccountHolder |
| GET | `/accounts/{id}/deposits` | List deposits for an account | AccountHolder, ClearingSystem, ComplianceOfficer |
| POST | `/deposits/{id}/reverse` | ACH return: reverse a pending deposit | ClearingSystem |
| POST | `/securities` | Register a tradable instrument | ClearingSystem, ComplianceOfficer |
| PATCH | `/securities/{id}/quote` | Push a new last price (market data) | MarketData, ClearingSystem |
| POST | `/orders` | Place a market/limit, regular/extended, fractional or share-quantity order | AccountHolder |
| GET | `/orders/{id}` | Get an order | AccountHolder, ClearingSystem, ComplianceOfficer |
| GET | `/orders` | List orders | AccountHolder, ClearingSystem, ComplianceOfficer |
| POST | `/orders/{id}/cancel` | Cancel a non-terminal order | AccountHolder |
| POST | `/orders/{id}/fills` | Report an execution against an order | ClearingSystem |
| GET | `/orders/{id}/fills` | List fills for an order | AccountHolder, ClearingSystem, ComplianceOfficer |
| GET | `/accounts/{id}/settlements` | List settlement legs for an account | AccountHolder, ClearingSystem, ComplianceOfficer |
| POST | `/settlements/{id}/fail` | Fail an unsettled leg (compensation) | ClearingSystem |
| GET | `/positions/{id}` | Get a position | AccountHolder, ClearingSystem, ComplianceOfficer |
| GET | `/positions` | List positions | AccountHolder, ClearingSystem, ComplianceOfficer |
| PATCH | `/positions/{id}/drip` | Enable or disable DRIP for a position | AccountHolder |
| GET | `/positions/{id}/lots` | List tax lots for a position | AccountHolder, ClearingSystem, ComplianceOfficer |
| GET | `/positions/{id}/disposals` | List realized disposals (1099-B detail) for a position | AccountHolder, ClearingSystem, ComplianceOfficer |
| POST | `/dividends` | Announce a cash dividend for a position | ClearingSystem |
| GET | `/accounts/{id}/dividends` | List dividend events for an account | AccountHolder, ClearingSystem, ComplianceOfficer |
| POST | `/dividends/{id}/pay` | Pay the announced cash dividend | ClearingSystem |
| POST | `/dividends/{id}/reinvest` | Reinvest a paid dividend (DRIP) into fractional shares | ClearingSystem |
| POST | `/dividends/{id}/reverse` | Reverse a paid (not yet reinvested) dividend | ClearingSystem |
| POST | `/options-approvals` | Apply for an options trading level | AccountHolder |
| GET | `/accounts/{id}/options-approvals` | List options approvals for an account | AccountHolder, ComplianceOfficer |
| POST | `/options-approvals/{id}/decide` | Approve (suitability-capped) or deny an options application | ComplianceOfficer |
| POST | `/options-approvals/{id}/revoke` | Revoke an approved options level | ComplianceOfficer |
| POST | `/accounts/{id}/margin-calls` | Issue a margin call against an account in deficiency | ClearingSystem |
| GET | `/accounts/{id}/margin-calls` | List margin calls for an account | AccountHolder, ClearingSystem, ComplianceOfficer |
| POST | `/accounts/{id}/margin-calls/{call_id}/liquidate` | Liquidate to cure an unmet margin call past its deadline | ClearingSystem |
| POST | `/_clock/advance` | Advance the logical clock and run the settlement sweep | ClearingSystem |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_FROZEN` | 409 |
| `ERR_RESTRICTED_CLOSING_ONLY` | 409 |
| `ERR_OPTIONS_LEVEL_INSUFFICIENT` | 409 |
| `ERR_FRACTIONAL_NOT_ALLOWED` | 422 |
| `ERR_FRACTIONAL_ORDER_CONSTRAINT` | 422 |
| `ERR_EXTENDED_HOURS_LIMIT_ONLY` | 422 |
| `ERR_INSUFFICIENT_SHARES` | 409 |
| `ERR_INSUFFICIENT_BUYING_POWER` | 402 |
| `ERR_INSTANT_LIMIT_EXCEEDED` | 402 |
| `ERR_LIMIT_PRICE_REQUIRED` | 422 |
| `ERR_DRIP_NOT_ENABLED` | 409 |
| `ERR_DRIP_BELOW_MINIMUM` | 409 |
| `ERR_DIVIDEND_NOT_PAYABLE` | 409 |
| `ERR_OPTIONS_LEVEL_TOO_HIGH` | 422 |
| `ERR_MARGIN_CALL_NOT_DUE` | 409 |
| `ERR_NO_DEFICIENCY` | 409 |
| `ERR_MARGIN_CALL_ACTIVE` | 409 |
| `ERR_CANNOT_FILL_TERMINAL` | 409 |
| `ERR_SETTLEMENT_NOT_DUE` | 409 |
| `ERR_DIVIDEND_WINDOW_OVERLAP` | 409 |
