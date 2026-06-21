# Brokerage Account & Options Approval API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Brokerage Account & Options Approval API, the back-office system of record that governs how a retail brokerage onboards customers, grants them progressively riskier trading privileges, and keeps their buying power honest against settled cash, open positions, and reserved orders. The platform is built around a single hub entity — the brokerage account — and a constellation of peer records that hang off it: options-level approval applications, margin-agreement upgrade applications, recorded positions, working orders, day-trade event rows, and ACAT (Automated Customer Account Transfer) transfers between custodians.

Two regulatory regimes shape almost every rule in the system. The first is suitability and segregation-of-duties compliance: an account must complete Know-Your-Customer (KYC) and W-9 certification before it can trade, options privileges are handed out one rung at a time against income and experience thresholds, and the compliance officer who submits an application may never be the one who approves it. The second is the margin and pattern-day-trading regime: buying power is computed differently under a cash agreement, a Regulation T margin agreement, and a Portfolio Margin agreement, and an account that day-trades too aggressively while under-capitalized is automatically restricted. Because several of these decisions race against settled transfers and prior upgrades, the system uses optimistic concurrency control to reject approvals built on a stale view of the account.

The intended readers of this document are the engineers building the service. Every field name, state, threshold, and error condition the implementation must honor is described in prose below; the structured endpoint and error tables in §4 and §5 are deliberately thin and must be read together with the narrative in §3.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly three roles: `AccountHolder`, `ComplianceOfficer`, and `Custodian`.

- The `AccountHolder` is the retail customer who owns an account — opening it, recording and closing positions, placing, accepting, cancelling, and rejecting orders, and requesting or cancelling ACAT transfers.
- The `ComplianceOfficer` is the back-office officer who runs KYC activation, account restriction and closure, the options-level and margin-upgrade approval workflows, and order fills.
- The `Custodian` is the clearing-side operator who validates, settles, and rejects ACAT transfers, and may also request a transfer.

All three roles use **opaque** identity. When `X-User-Role` is `AccountHolder`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `account_holder_user_id` on the `Account` at open time, and ownership of an account is established by comparing that stored `account_holder_user_id` against the caller's `X-User-ID`, but the identifier is never matched against any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity; the server records it where a transition writes it — as `submitted_by_user_id` when an application is submitted and as `decided_by_user_id` when one is approved or rejected — and the segregation-of-duties rule compares those two recorded identifiers, but neither is matched against any entity's `id`. When `X-User-Role` is `Custodian`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result set and defaults to 0.

Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most top-level resources — `Account`, `OptionsApproval`, `MarginUpgrade`, `Position`, `Order`, and `AcatTransfer` — carry a standard set of system-managed fields. Each has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits, fixed at creation), an `updated_at` timestamp (ISO 8601 UTC with three fractional digits, refreshed on every mutation), and an integer `version` that begins at its initial value and increments by one each time the resource is mutated.

Every lifecycle-bearing entity — `Account`, `OptionsApproval`, `MarginUpgrade`, `Position`, `Order`, and `AcatTransfer` — also carries a system-managed `status` field holding its current state, whose enumerated values and transitions are defined in §3.

The `DayTrade` entity is the exception. A day-trade row is an append-only event record and carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because it is never modified after it is written.

Whenever a state transition or computed-field recomputation mutates a resource, that resource's `updated_at` is refreshed. The `version` increments specifically where the state machine narratives in §3 say so — most notably on every `Account` lifecycle transition and on the cross-entity cascades that change account state.

### 2.5. Nested Resource Retrieval and Referential Validation

The topology is flat: accounts, options approvals, margin upgrades, positions, orders, day-trade rows, and ACAT transfers are each addressed under their own top-level collection rather than nested under the account. Even so, many operations reference a resource by an identifier in the path and reference other resources by foreign-key fields in the body. All referenced resources are validated for existence in left-to-right order — path identifiers first, then body references — and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated.

List endpoints that expose a child collection accept an optional filter on `account_id` so that, for example, all options approvals, margin upgrades, positions, orders, day-trade rows, or ACAT transfers belonging to one account can be discovered. The day-trade listing additionally accepts an optional `closing_order_id` filter so a specific round trip can be traced back to the order that closed it.

### 2.6. Validation Ordering

When several checks could fail on the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` before anything else. Role authorization comes second, yielding `ERR_FORBIDDEN_ROLE`. Resource existence comes third, yielding `ERR_NOT_FOUND`. State legality comes fourth: any state-transition endpoint invoked on a resource that is not in a state from which the requested transition is defined fails with `ERR_INVALID_STATE` (HTTP 409). Only after these four universal gates pass does the system evaluate the operation-specific business rules described in §3 — segregation of duties, KYC completeness, suitability, options gating, level sequencing, price completeness, the PMA equity floor, the pattern-day-trader block, buying-power sufficiency, and the optimistic-concurrency check — in the orderings called out alongside each workflow.

Malformed request bodies and missing required input fields that are not covered by a more specific business error are rejected with `ERR_VALIDATION` (HTTP 422).

### 2.7. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents; there are no fractional cents anywhere in the system. Wherever a calculation divides — the Portfolio Margin buying-power formula, the per-position maintenance computation, and the unfilled-remainder proration of reserved order notional — the result is floored to the nearest whole cent (rounded toward zero on the non-negative magnitudes involved). Maintenance margin is computed per position and floored per position before the per-position results are summed, never summed first and floored once.

### 2.8. Optimistic Concurrency Control on Margin-Upgrade Approval

Approving a margin upgrade is the one operation in the system guarded by optimistic concurrency control. The approval request must carry `expected_account_version`, the `version` of the parent `Account` that the compliance officer last observed. If that value does not equal the account's current `version` at approval time, the approval is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). This guards the case where another writer — a settled transfer-in, a closed position, or a prior margin upgrade — has already advanced the account's version since the approver read it, so the approver's view of margin type and buying-power inputs is stale and the recomputation would run on out-of-date numbers. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.9. Buying Power, Equity, and Maintenance Margin

Three computed money fields travel on every account read and are recomputed on every event that can move them: a margin-type change, a position open or close, an order accept or cancel, and an ACAT settle.

`equity_cents` is the account's `cash_balance_cents` plus the sum of `market_value_cents` over the account's `OPEN` positions (the signed market values are added, so a short position with negative market value reduces equity).

`maintenance_margin_cents` is the sum, over the account's `OPEN` positions taken in `created_at` ascending order, of each position's maintenance requirement. For an `EQUITY` position the requirement is the absolute value of its `market_value_cents` multiplied by the equity maintenance rate of 25 percent, floored to whole cents. For an `OPTION` position the requirement is the absolute value of its `market_value_cents` multiplied by the option maintenance rate of 100 percent, floored to whole cents. The floor is applied to each position's line item, and the floored line items are then summed. Closed positions are excluded entirely.

`buying_power_cents` depends on the account's `margin_type` and is the central dual-variant calculation of the system; it is described in full in §3.6.

### 2.10. State-Cascade Consistency

Several operations mutate more than one entity. When an account is restricted, its working orders are cancelled and its pending options approvals are rejected; when an order fills, a day-trade row may be created and the account may be automatically restricted; when a position closes or a transfer settles, the account's computed money fields are recomputed. Each such cascade is described in the workflow where it originates (§3). The governing principle is that a child mutation that changes the inputs to a parent's computed fields always triggers the parent's recomputation, and a parent transition that invalidates its children always resolves those children in the same operation, so the system is never left in a state where the account's recorded buying power, equity, or maintenance margin disagrees with its open positions and reserved orders.

## 3. Business Logic & Workflows

### 3.1. Opening and Activating an Account

An `AccountHolder` opens a brokerage account by submitting the KYC and W-9 intake: their `account_holder_user_id` (the opaque owner identifier), `legal_name`, `tax_id` (the SSN or EIN supplied on the W-9), `date_of_birth` as an ISO `YYYY-MM-DD` date, `w9_certified` (whether the backup-withholding certification box was signed, defaulting to false if omitted), `liquid_net_worth_cents`, `annual_income_cents`, `investment_experience` (one of `NONE`, `LIMITED`, `GOOD`, or `EXTENSIVE`), and optionally an initial `cash_balance_cents` (defaulting to 0). A newly opened account is born in `PENDING_KYC` status with `options_level` of 0 (meaning no options trading is permitted), `margin_type` of `CASH`, and `pdt_flagged` false with a `day_trade_count` of 0.

A `ComplianceOfficer` activates the account, moving it from `PENDING_KYC` to `ACTIVE`. Activation enforces the KYC gate, which is three conditions: the W-9 must be certified (`w9_certified` is true), otherwise the activation is rejected with `ERR_W9_NOT_CERTIFIED`; the account holder must be at least 18 years old as of the account's `created_at` date, measured from `date_of_birth`, otherwise `ERR_KYC_AGE`; and the `tax_id` must be present and non-empty, otherwise `ERR_KYC_INCOMPLETE`. When the gate passes, the status becomes `ACTIVE` and the account's `version` increments by one.

The same activation endpoint also restores a `RESTRICTED` account to `ACTIVE`. In the restore case the KYC gate does not re-apply, but the pattern-day-trader equity call does: if the account is `pdt_flagged`, its `equity_cents` must be at least the pattern-day-trader minimum equity of $25,000.00 (2,500,000 cents); if a flagged account is below that floor, the restore is rejected with `ERR_PDT_EQUITY_CALL`. On a successful restore the status becomes `ACTIVE` and `version` increments by one.

### 3.2. Restricting and Closing an Account

A `ComplianceOfficer` may restrict an `ACTIVE` account, moving it to `RESTRICTED`. Restriction has no preconditions but fans out a cascade: the account's status becomes `RESTRICTED`; every `Order` on the account currently in `DRAFT`, `ACCEPTED`, or `PARTIALLY_FILLED` is transitioned to `CANCELLED`; every `OptionsApproval` on the account currently in `DRAFT` or `SUBMITTED` is transitioned to `REJECTED` with its `rejection_reason` set to the literal string `ACCOUNT_RESTRICTED`; and the account's `version` increments by one. When the cancelled orders had reserved notional, that notional is released back to buying power as described in §3.5, and the account's buying power is recomputed.

Closing an account is a terminal action a `ComplianceOfficer` may take from either `ACTIVE` or `RESTRICTED`, moving the account to `CLOSED`. Closure has two preconditions evaluated against the account's children: there must be no `Position` on the account in `OPEN` status, otherwise the close is rejected with `ERR_OPEN_POSITIONS`; and there must be no `AcatTransfer` on the account in `REQUESTED` or `VALIDATED` status, otherwise `ERR_PENDING_TRANSFER`. On success the status becomes `CLOSED` and `version` increments by one. `CLOSED` is terminal.

### 3.3. The Options-Level Approval Workflow

Options privileges are tracked by the `OptionsApproval` entity and granted one rung at a time. A `ComplianceOfficer` creates a draft application by supplying the `account_id` it targets and the `requested_level` (an integer from 1 to 4). The new application begins in `DRAFT`.

Submitting a draft moves it to `SUBMITTED`. Two preconditions apply. The parent account must be `ACTIVE`, otherwise the submission is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. And the requested level must be exactly one rung above the account's current `options_level` — that is, `requested_level` must equal the account's `options_level` plus one — because levels are never skipped; a request that is not the next rung is rejected with `ERR_LEVEL_SKIP`. On a successful submit the status becomes `SUBMITTED` and the submitting officer's `X-User-ID` is recorded as `submitted_by_user_id`.

A submitted application is then either approved or rejected by a `ComplianceOfficer`, and both decisions enforce segregation of duties: the deciding officer's `X-User-ID` must differ from the recorded `submitted_by_user_id`; if the same user who submitted attempts to decide, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval additionally enforces the suitability gate for the `requested_level` (detailed in §3.7); if suitability is not met the approval is rejected with `ERR_SUITABILITY_NOT_MET`. When approval succeeds the application moves to `APPROVED`, the deciding officer is recorded as `decided_by_user_id`, the parent account's `options_level` is set to the `requested_level` as a cross-entity write, and the account's `version` increments by one. On these two parallel decisions the precedence is segregation of duties first, then — for approval only — the suitability gate.

Rejecting a submitted application moves it to `REJECTED`, records the deciding officer as `decided_by_user_id`, and sets `rejection_reason` from the request body. Rejection enforces only the segregation-of-duties check and does not touch the account's options level or version. Both `APPROVED` and `REJECTED` are terminal for an options approval.

### 3.4. The Margin-Upgrade Workflow

The `MarginUpgrade` entity governs moving an account between margin agreements. A `ComplianceOfficer` creates a draft upgrade by supplying the `account_id` and the `requested_margin_type`, which is either `REG_T` or `PMA`. The application begins in `DRAFT`.

Submitting the draft moves it to `SUBMITTED` and enforces three preconditions. The parent account must be `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`. The `requested_margin_type` must differ from the account's current `margin_type`, since upgrading to the agreement already in force is a no-op rejected with `ERR_MARGIN_NOOP`. And if the requested type is `PMA`, the account's `equity_cents` must be at least the Portfolio Margin equity floor of $150,000.00 (15,000,000 cents); an account below that floor is rejected with `ERR_PMA_EQUITY_MINIMUM`. On a successful submit the status becomes `SUBMITTED` and the submitting officer is recorded as `submitted_by_user_id`.

Approving a submitted upgrade is the optimistic-concurrency-guarded operation. The approval request carries `expected_account_version`, and two preconditions apply, evaluated segregation-of-duties first and then the version check: the deciding officer's `X-User-ID` must differ from `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; and `expected_account_version` must equal the account's current `version`, otherwise `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). When approval succeeds, the upgrade moves to `APPROVED`, the officer is recorded as `decided_by_user_id`, the account's `margin_type` is set to the `requested_margin_type` as a cross-entity write, the account's `buying_power_cents` is recomputed under the new margin type, and the account's `version` increments by one.

Rejecting a submitted upgrade moves it to `REJECTED` and records `decided_by_user_id`. Rejection enforces only the segregation-of-duties check and does not change the account's margin type, buying power, or version. Both `APPROVED` and `REJECTED` are terminal for a margin upgrade.

### 3.5. Positions and the Order Lifecycle

Positions are the inventory that drives equity and maintenance margin. An `AccountHolder` or a `ComplianceOfficer` records a position by supplying its `account_id`, `symbol`, `instrument_type` (`EQUITY` or `OPTION`), `quantity` (a signed share or contract count — positive long, negative short), and `market_value_cents` (the signed marked value). A recorded position begins `OPEN`, and recording it recomputes the account's `maintenance_margin_cents`, `equity_cents`, and `buying_power_cents`. A position is closed (from `OPEN` to `CLOSED`) only while its parent account is `ACTIVE` or `RESTRICTED`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`; closing it recomputes the account's maintenance margin excluding that position, then recomputes equity and buying power. `CLOSED` is terminal for a position.

Orders flow through a richer lifecycle. An `AccountHolder` creates an order in `DRAFT` by supplying its `account_id`, `symbol`, `instrument_type` (`EQUITY` or `OPTION`), `side` (`BUY` or `SELL`), `order_type` (which must be exactly one of `LIMIT`, `STOP`, or `TAKE_PROFIT`; a present `order_type` whose value is none of these is rejected at order creation with `ERR_VALIDATION`), `quantity` (which must be greater than zero), the `trade_date` (the `YYYY-MM-DD` business date on which the order executes), and, as applicable, `limit_price_cents` and `stop_price_cents`. The order body may also carry `opened_position_same_day`, a flag (defaulting to false) marking that this order opens or adds to a position the account also closed on the same `trade_date`, identifying it as the closing leg of a day-trade round trip.

Accepting a `DRAFT` order moves it to `ACCEPTED` and is performed by the `AccountHolder`. Acceptance is where the heaviest validation lives, and the checks are evaluated in this order. First, the parent account must be `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`. Second, if the order's `instrument_type` is `OPTION`, the account's `options_level` must be at least 1, otherwise `ERR_OPTIONS_NOT_APPROVED`. Third, the required price fields for the declared `order_type` must be present (the price-completeness rule of §3.8), otherwise `ERR_MISSING_PRICE`. Fourth, the pattern-day-trader preventive block of §3.9 is applied; a same-day closing leg that would trip the threshold under-capitalized is rejected with `ERR_PDT_RULE_BLOCK`. Fifth, the order's computed `notional_cents` (the reservation rule of §3.8) must not exceed the account's `buying_power_cents`, otherwise `ERR_INSUFFICIENT_BUYING_POWER`. When all checks pass, the status becomes `ACCEPTED` and the computed `notional_cents` is reserved against the account's buying power, which is recomputed to reflect the reservation.

A `DRAFT` order may instead be rejected by the `AccountHolder`, moving it directly to `REJECTED` with no preconditions.

Fills are applied by a `ComplianceOfficer` against an `ACCEPTED` or `PARTIALLY_FILLED` order, each fill carrying a `fill_quantity`. A fill is valid only when the running `filled_quantity` plus this `fill_quantity` stays within bounds: a partial fill requires the cumulative filled total to be strictly greater than zero and strictly less than the order `quantity`, and a completing fill requires the cumulative filled total to equal the order `quantity` exactly; any `fill_quantity` that is non-positive or that would push the cumulative total above the order quantity is rejected with `ERR_FILL_QUANTITY`. A partial fill adds `fill_quantity` to `filled_quantity` and leaves (or sets) the order in `PARTIALLY_FILLED`. A completing fill sets `filled_quantity` equal to `quantity`, moves the order to `FILLED`, and — if `opened_position_same_day` is true — creates a `DayTrade` row capturing the account, this order's id as the `closing_order_id`, the order's `symbol`, and its `trade_date`, after which the pattern-day-trader status is recomputed on the account; if that recomputation newly flags the account as a pattern day trader while its equity is below the $25,000.00 floor, the account cascades from `ACTIVE` to `RESTRICTED` (§3.9). `FILLED` is terminal.

Cancelling an order is performed by the `AccountHolder` (and also occurs automatically when an account is restricted) and applies to an order in `ACCEPTED` or `PARTIALLY_FILLED`. Cancellation moves the order to `CANCELLED` and releases its reserved notional back to the account's buying power: for an `ACCEPTED` order the full reserved `notional_cents` is released; for a `PARTIALLY_FILLED` order only the reservation on the unfilled remainder is released. After the release the account's buying power is recomputed. `CANCELLED` is terminal.

### 3.6. Computing Buying Power — Cash, Reg T, and Portfolio Margin

Buying power is the dual-variant heart of the system, computed differently under each `margin_type` but always from the same building blocks. The reserved order notional is the total still held against working orders: it is the sum, over the account's orders in `ACCEPTED` or `PARTIALLY_FILLED` status, of each order's reservation, where an `ACCEPTED` order contributes its full `notional_cents` and a `PARTIALLY_FILLED` order contributes only the portion attributable to its unfilled remainder, namely its `notional_cents` multiplied by the quantity still unfilled (the order `quantity` minus its `filled_quantity`) divided by the order `quantity`, with that division floored to whole cents. Excess equity is the account's `equity_cents` minus its `maintenance_margin_cents` minus this reserved order notional.

Under a `CASH` agreement, buying power is the account's `cash_balance_cents` minus the reserved order notional, and never less than zero — the larger of zero and that difference. Under a `REG_T` agreement, buying power is twice the excess equity, never less than zero — the larger of zero and two times excess equity — reflecting Regulation T's 50 percent initial requirement, which doubles the purchasing reach of excess equity (maintenance and reserved notional are already netted into excess equity). Under a `PMA` (Portfolio Margin) agreement, buying power is the account's `equity_cents` divided by the 15 percent risk-based initial margin rate (the division floored to whole cents), then reduced by `maintenance_margin_cents` and by the reserved order notional, never less than zero — the larger of zero and that result. Dividing total equity by the 0.15 rate yields a strictly larger pool than Reg T grants on the same equity, which is the privilege Portfolio Margin confers.

### 3.7. The Options Suitability Gate

When a `ComplianceOfficer` approves an options application, the requested level is tested against the account holder's self-reported finances and experience, evaluated against the `requested_level` itself rather than the account's current level — so level 4 demands the strictest pair. Two conditions must both hold. First, the combined figure of `liquid_net_worth_cents` plus `annual_income_cents` must be at least the level's minimum combined threshold: $0 for level 1, $50,000.00 (5,000,000 cents) for level 2, $100,000.00 (10,000,000 cents) for level 3, and $250,000.00 (25,000,000 cents) for level 4. Second, the holder's `investment_experience`, ranked as `NONE` = 0, `LIMITED` = 1, `GOOD` = 2, and `EXTENSIVE` = 3, must be at least the level's minimum experience rank: 0 for level 1, 1 for level 2, 2 for level 3, and 3 for level 4. If either condition fails, the approval is rejected with `ERR_SUITABILITY_NOT_MET`.

### 3.8. Order Notional and Required Prices

Two computations key off the order's `order_type`. The first determines which price fields must be present at accept time. A `LIMIT` order requires `limit_price_cents` (non-null and greater than zero) and ignores `stop_price_cents`. A `STOP` order requires `stop_price_cents` (non-null and greater than zero) and ignores `limit_price_cents`. A `TAKE_PROFIT` order requires both `limit_price_cents` and `stop_price_cents` (each non-null and greater than zero). A missing required field for the declared order type yields `ERR_MISSING_PRICE`.

The second computation reserves the worst-case cash impact as `notional_cents`. The base figure is the order `quantity` multiplied by a per-unit price chosen by `order_type`: for `LIMIT` the `limit_price_cents`; for `STOP` the `stop_price_cents`; and for `TAKE_PROFIT` the larger of `limit_price_cents` and `stop_price_cents`, taking the worst case of the two legs. If the order's `instrument_type` is `OPTION`, this base is multiplied by the option contract multiplier of 100 to reflect contract size; for an `EQUITY` order the base is used as-is (multiplied by one). As a special case, a `SELL` order against an existing `OPEN` long position in the same symbol reserves nothing — when `side` is `SELL` and the account holds an `OPEN` `Position` in the same symbol with positive quantity, `notional_cents` is 0, because closing a long frees rather than consumes buying power.

### 3.9. The Pattern Day Trader Rule

A round trip — opening and closing a position in the same symbol on the same business day — is recorded as a `DayTrade` row when a completing fill lands on an order whose `opened_position_same_day` flag is true; the row captures the account, the closing order, the `symbol`, and the `trade_date`. The account's `day_trade_count` is then derived over a rolling trailing window: take the anchor date as the most recent `trade_date` among the account's day-trade rows (if the account has no day-trade rows the count is 0), set the window start to that anchor date minus 5 calendar days, and count the day-trade rows whose `trade_date` falls within that window from the window start through the anchor date inclusive. If `day_trade_count` reaches the threshold of 4 day trades or more, the account is flagged: `pdt_flagged` becomes true. At exactly three day trades the account is not flagged; the fourth day trade flips it. A newly flagged account whose `equity_cents` is below the $25,000.00 minimum is moved from `ACTIVE` to `RESTRICTED` — the equity call — carrying with it the restriction cascade of §3.2.

The same rule is also enforced preventively at order-accept time for a same-day closing leg. The prospective count is the number of existing day-trade rows for the account whose `trade_date` equals this order's `trade_date`, plus one for this order. If the account is not yet `pdt_flagged`, its `equity_cents` is below the $25,000.00 minimum, and the prospective count reaches the threshold of 4 or more, the acceptance is blocked with `ERR_PDT_RULE_BLOCK`.

Because that accept-time block makes a fourth same-day round trip unreachable through ordinary order placement while the account is under-capitalized, an administrative test-driving capability exists for a `ComplianceOfficer` to seed the day-trade log directly: it injects a given `count` of synthetic day-trade rows for an `account_id` on a supplied `trade_date`, then recomputes pattern-day-trader status and applies the `ACTIVE` to `RESTRICTED` equity-call cascade if the account newly flags below the minimum equity, incrementing the account's `version` by one if its status changes.

### 3.10. ACAT Transfers

An ACAT transfer moves assets between custodians. An `AccountHolder` or a `Custodian` requests one by supplying the `account_id`, the `direction` (`IN` for a transfer into this account or `OUT` for one out of it), the `counterparty_dtc` (the DTC clearing number of the contra brokerage), and the `transfer_value_cents` (the total marked value of the assets). A requested transfer begins in `REQUESTED`.

A `Custodian` validates a `REQUESTED` transfer, moving it to `VALIDATED`, but only while the parent account is `ACTIVE` or `RESTRICTED`; a frozen or closed account cannot validate, and the attempt is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. A `Custodian` then settles a `VALIDATED` transfer, moving it to `SETTLED`, but only while the parent account is `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`. Settlement adjusts the account's cash: when `direction` is `IN`, the `transfer_value_cents` is added to the account's `cash_balance_cents`; when `direction` is `OUT`, the `transfer_value_cents` is subtracted from it. In both cases the account's buying power is recomputed and the account's `version` increments by one.

A `Custodian` may reject a transfer that is in `REQUESTED` or `VALIDATED`, moving it to `REJECTED`; the rejection must supply a `reject_code` — one of `SSN_MISMATCH`, `TITLE_MISMATCH`, or `ACCT_FROZEN` — in the request body, otherwise it is rejected with `ERR_MISSING_REJECT_CODE`. Finally, an `AccountHolder` may cancel a transfer that is still `REQUESTED`, moving it to `CANCELLED`, with no preconditions. `SETTLED`, `REJECTED`, and `CANCELLED` are all terminal for a transfer.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions — return a `200 OK` status code. List and single-resource retrievals return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Open a brokerage account (KYC/W-9 intake) | AccountHolder |
| GET | `/accounts/{accountId}` | Get an account with computed buying power, equity, day-trade count | AccountHolder, ComplianceOfficer, Custodian |
| GET | `/accounts` | List accounts, optionally filtered by holder | ComplianceOfficer |
| POST | `/accounts/{accountId}/activate` | Activate a PENDING_KYC account or restore a RESTRICTED one | ComplianceOfficer |
| POST | `/accounts/{accountId}/restrict` | Restrict an ACTIVE account (cascades) | ComplianceOfficer |
| POST | `/accounts/{accountId}/close` | Close an account with no open positions or pending transfers | ComplianceOfficer |
| POST | `/options-approvals` | Create a DRAFT options-level approval application | ComplianceOfficer |
| GET | `/options-approvals/{approvalId}` | Get an options approval | ComplianceOfficer, AccountHolder |
| GET | `/options-approvals` | List options approvals, filterable by account_id | ComplianceOfficer, AccountHolder |
| POST | `/options-approvals/{approvalId}/submit` | Submit a DRAFT options approval for decision | ComplianceOfficer |
| POST | `/options-approvals/{approvalId}/approve` | Approve a SUBMITTED options approval | ComplianceOfficer |
| POST | `/options-approvals/{approvalId}/reject` | Reject a SUBMITTED options approval | ComplianceOfficer |
| POST | `/margin-upgrades` | Create a DRAFT margin-agreement upgrade application | ComplianceOfficer |
| GET | `/margin-upgrades/{upgradeId}` | Get a margin upgrade | ComplianceOfficer, AccountHolder |
| GET | `/margin-upgrades` | List margin upgrades, filterable by account_id | ComplianceOfficer, AccountHolder |
| POST | `/margin-upgrades/{upgradeId}/submit` | Submit a DRAFT margin upgrade for decision | ComplianceOfficer |
| POST | `/margin-upgrades/{upgradeId}/approve` | Approve a SUBMITTED margin upgrade (OCC + segregation of duties) | ComplianceOfficer |
| POST | `/margin-upgrades/{upgradeId}/reject` | Reject a SUBMITTED margin upgrade | ComplianceOfficer |
| POST | `/positions` | Record an OPEN position on an account | AccountHolder, ComplianceOfficer |
| GET | `/positions/{positionId}` | Get a position | AccountHolder, ComplianceOfficer |
| GET | `/positions` | List positions, filterable by account_id | AccountHolder, ComplianceOfficer |
| POST | `/positions/{positionId}/close` | Close an OPEN position; recomputes margin/equity/buying power | AccountHolder, ComplianceOfficer |
| POST | `/orders` | Create a DRAFT order (LIMIT / STOP / TAKE_PROFIT) | AccountHolder |
| GET | `/orders/{orderId}` | Get an order with computed notional and filled quantity | AccountHolder, ComplianceOfficer |
| GET | `/orders` | List orders, filterable by account_id | AccountHolder, ComplianceOfficer |
| POST | `/orders/{orderId}/accept` | Accept a DRAFT order; validates and reserves notional | AccountHolder |
| POST | `/orders/{orderId}/fill` | Apply a partial or full fill | ComplianceOfficer |
| POST | `/orders/{orderId}/cancel` | Cancel an ACCEPTED or PARTIALLY_FILLED order | AccountHolder |
| POST | `/orders/{orderId}/reject` | Reject a DRAFT order | AccountHolder |
| POST | `/_day-trades/seed` | Test-driving: inject DayTrade rows and recompute PDT status | ComplianceOfficer |
| GET | `/day-trades/{dayTradeId}` | Get a single day-trade row | ComplianceOfficer, AccountHolder |
| GET | `/day-trades` | List day-trade rows, filterable by account_id / closing_order_id | ComplianceOfficer, AccountHolder |
| POST | `/acat-transfers` | Request an ACAT transfer (IN or OUT) | AccountHolder, Custodian |
| GET | `/acat-transfers/{transferId}` | Get an ACAT transfer | AccountHolder, Custodian, ComplianceOfficer |
| GET | `/acat-transfers` | List ACAT transfers, filterable by account_id | AccountHolder, Custodian, ComplianceOfficer |
| POST | `/acat-transfers/{transferId}/validate` | Validate a REQUESTED transfer | Custodian |
| POST | `/acat-transfers/{transferId}/settle` | Settle a VALIDATED transfer; adjusts cash and buying power | Custodian |
| POST | `/acat-transfers/{transferId}/reject` | Reject a REQUESTED or VALIDATED transfer with a reject_code | Custodian |
| POST | `/acat-transfers/{transferId}/cancel` | Cancel a still-REQUESTED transfer | AccountHolder |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_W9_NOT_CERTIFIED` | 422 |
| `ERR_KYC_AGE` | 422 |
| `ERR_KYC_INCOMPLETE` | 422 |
| `ERR_SUITABILITY_NOT_MET` | 422 |
| `ERR_OPTIONS_NOT_APPROVED` | 422 |
| `ERR_LEVEL_SKIP` | 422 |
| `ERR_MISSING_PRICE` | 422 |
| `ERR_MARGIN_NOOP` | 422 |
| `ERR_PMA_EQUITY_MINIMUM` | 422 |
| `ERR_PDT_RULE_BLOCK` | 409 |
| `ERR_PDT_EQUITY_CALL` | 409 |
| `ERR_INSUFFICIENT_BUYING_POWER` | 409 |
| `ERR_FILL_QUANTITY` | 422 |
| `ERR_OPEN_POSITIONS` | 409 |
| `ERR_PENDING_TRANSFER` | 409 |
| `ERR_MISSING_REJECT_CODE` | 422 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
