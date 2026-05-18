# Brokerage Options API — Product Requirements Document

## 1. Introduction

Retail brokerage today asks an end customer to navigate three intertwined regulatory regimes before a single share trades: Know-Your-Customer onboarding with W-9 collection, tiered options-trading approval that ranges from covered calls all the way up to uncovered (naked) strategies, and margin handling under either Regulation T (fixed 50% initial margin) or the discretionary Portfolio Margin Account framework reserved for sophisticated investors. Layered on top of these regimes are real-time gating rules — the Pattern Day Trader designation that fires when four day-trades accumulate inside a rolling five-business-day window, and the ACAT (Automated Customer Account Transfer) pipeline that ties up an account for six business days while assets settle between brokerages.

This document specifies the back-end REST API that orchestrates all of the above. The API supports three operator personas — end customers, compliance officers, and platform administrators — and exposes the lifecycle of seven domain entities: `Customer`, `Account`, `KYCSubmission`, `OptionsApproval`, `Order`, `DayTrade`, and `ACATTransfer`. The system is deterministic, audit-traceable, and time-driven via an explicit logical-clock primitive so that the six-business-day ACAT settlement and the rolling PDT window are testable without wall-clock waits.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_AUTH_MISSING` at HTTP 401. If `X-User-Role` is present but is not one of the three recognised roles — `Customer`, `ComplianceOfficer`, or `PlatformAdmin` — the request is rejected with `ERR_AUTH_INVALID_ROLE` at HTTP 401. If the role is recognised but is not authorised for the endpoint per the RBAC table in §4, the request is rejected with `ERR_FORBIDDEN` at HTTP 403.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (directly through `customer_id`, or transitively through `Account.customer_id`) compare the resource's owning customer chain to `X-User-ID`. A customer who attempts to read or mutate a resource that does not chain back to their own `Customer.id` is rejected with `ERR_OWNERSHIP_VIOLATION` at HTTP 403. When `X-User-Role` is `ComplianceOfficer` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`, and these roles are not subject to the ownership check.

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

List endpoints accept two query parameters, `limit` and `offset`. The default value of `limit` is 10, its minimum is 1, and its maximum is 100; any request exceeding these bounds is rejected with `ERR_VALIDATION` at HTTP 422. The default value of `offset` is 0, and values below 0 are likewise rejected. List endpoints return results sorted by `created_at` in ascending order. The pagination state echoed back in `meta` carries exactly four fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource governed by this API exposes an `id` as a server-minted UUID with no type prefix. Most resources also carry three additional system-managed fields: `created_at` (ISO 8601 UTC with three fractional digits, set on insert and immutable thereafter), `updated_at` (ISO 8601 UTC with three fractional digits, refreshed on every mutation including any side-effect cascade that touches the row), and `version` (a positive integer that begins at 1 and increases by exactly 1 on every successful mutation). Two of the entities — `KYCSubmission` and `DayTrade` — are append-only audit rows: they carry only `id` and `created_at`. Both `updated_at` and `version` are absent from those two resource shapes, and clients must not supply them in any payload that touches those entities.

### 2.5. Optimistic Concurrency Control

Endpoints that mutate a resource carrying a `version` field accept an optional `version` field in the request body. If the supplied `version` is omitted (or explicitly null), the server performs the mutation unconditionally. If the supplied `version` is present but does not equal the resource's current `version` at the moment of write, the mutation is rejected with `ERR_INVALID_STATE` at HTTP 409 — the resource has been modified by someone else since the caller last read it, and the caller is expected to re-read and retry. On any successful mutation, `version` increments by exactly 1 and `updated_at` is refreshed to the server's current time.

### 2.6. Time, Business Days, and the Logical Clock

The system runs against an explicit server-controlled logical clock. All timestamps emitted to clients are in UTC. The business calendar treats Monday through Friday as business days with no holiday exclusions: business-day arithmetic skips Saturday and Sunday but never any other date. The administrative endpoint described under §4 advances this clock in whole seconds; whenever the clock advances, time-gated transitions on `ACATTransfer` are evaluated and applied automatically, and any PDT calculation that consumes the rolling-five-business-day window uses the new `now()` as its right-hand boundary.

### 2.7. Precision and Monetary Rounding

Every monetary value crosses the wire as an integer count of US-cent units — fields ending in `_cents` always carry integer cents. Arithmetic that produces fractional cents (notional times a percentage rate, for example) is rounded up to the next whole cent at the point each per-term component is computed; that is, ceiling rounding is applied to each term before the terms are summed, never to the final sum after summation. Counts such as `business_days_elapsed`, `revision_count`, and `quantity` are exact integers with no rounding involved.

### 2.8. Hierarchical Path Resolution

Path parameters are resolved strictly left to right, and a path-parameter failure at any step short-circuits all subsequent validation. A request whose `customer_id` segment does not resolve is rejected with `ERR_CUSTOMER_NOT_FOUND` (HTTP 404) before any account, options-approval, order, or ACAT-transfer lookup is attempted. Likewise an unresolvable `account_id` yields `ERR_ACCOUNT_NOT_FOUND` (404); an unresolvable options-approval id yields `ERR_OPTIONS_APPROVAL_NOT_FOUND` (404); an unresolvable order id yields `ERR_ORDER_NOT_FOUND` (404); an unresolvable ACAT-transfer id yields `ERR_TRANSFER_NOT_FOUND` (404). Existence checks always run before ownership, state, and business-rule checks.

### 2.9. Validation Ordering and the Posture Gate

When multiple validation rules apply to a single request, they are evaluated in a fixed deterministic priority order, and the first violation surfaced determines the rejection. Authentication checks come first: header presence (`ERR_AUTH_MISSING`), then role recognition (`ERR_AUTH_INVALID_ROLE`), then per-endpoint role authorisation (`ERR_FORBIDDEN`). Next come path-existence checks in the order described under §2.8. After existence, ownership is enforced for `Customer` callers (`ERR_OWNERSHIP_VIOLATION`). Then the three account-level posture gates run, in this order, for every endpoint that touches trading, options approvals, ACAT transfers, or account closure: `Account.status` must equal `APPROVED` or the request is rejected with `ERR_ACCOUNT_NOT_APPROVED`; `Customer.kyc_status` must equal `VERIFIED` or the request is rejected with `ERR_KYC_NOT_VERIFIED`; and for order submission specifically, `Account.trading_posture` must equal `OPEN` or the request is rejected with `ERR_TRADING_FROZEN` — this latter rejection thus covers `RESTRICTED`, `PDT_FROZEN`, and `TRANSFER_LOCKED` postures alike. Source-state checks for the relevant entity follow (yielding `ERR_INVALID_STATE` when a transition source is wrong). Only after all of the above are field-level business-safety, business-constraint, business-referential, and business-fiscal checks evaluated. The KYC submission, in particular, enforces eligibility checks in this order after the generic auth/path/state checks: country eligibility (`ERR_KYC_INELIGIBLE_COUNTRY`), age eligibility (`ERR_KYC_AGE_INELIGIBLE`), then the W-9 name match (`ERR_W9_NAME_MISMATCH`).

### 2.10. Concurrency Serialisation

Several pairs of concurrent operations on the same aggregate are resolved on a first-writer-wins basis, and the loser receives a specific `error_id`. When a customer and a compliance officer act simultaneously on the same `OptionsApproval`, exactly one decision is recorded; the second request loses because the resource's `status` no longer matches the source state it expected, and the loser receives `ERR_INVALID_STATE` at HTTP 409. When two `ACATTransfer` rows with `direction` equal to `OUTBOUND` are submitted simultaneously for the same `account_id`, at most one survives in a non-terminal status, and the loser receives `ERR_TRANSFER_ALREADY_PENDING` at HTTP 409. When a customer cancels an `Order` at the same instant the system cancels the same order via a PDT or transfer-lock cascade, exactly one cancellation succeeds and the other receives `ERR_INVALID_STATE` at HTTP 409 because `Order.status` has already advanced to `CANCELLED`. When two `OptionsApproval` submissions for the same `Account` race, at most one ends up in the set of non-terminal states (`SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`), and the second is rejected with `ERR_OPTIONS_APPROVAL_IN_PROGRESS` at HTTP 409.

---

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and the KYC + W-9 Submission

A new customer enters the system through a registration call that captures self-reported personal and financial data: `legal_name` (1 to 120 characters), `date_of_birth` as a `YYYY-MM-DD` ISO date, `ssn_last4` (exactly four digits, immutable once first persisted), `annual_income_cents`, `liquid_net_worth_cents`, `total_net_worth_cents`, and `years_options_experience`. All four financial fields are non-negative integers; in addition, `total_net_worth_cents` must be greater than or equal to `liquid_net_worth_cents` — a customer cannot have more liquid wealth than total wealth. `years_options_experience` is likewise a non-negative integer. The new `Customer` row is created with `kyc_status` set to `NOT_STARTED` and `w9_collected` set to `false`.

Before the customer can trade, an `Account` must be opened for them. Account creation accepts the owning `customer_id` and an `account_type` chosen from `CASH`, `MARGIN_REG_T`, or `MARGIN_PMA`. The newly-minted `Account` begins life with `status` set to `PENDING_KYC` and `trading_posture` set to `RESTRICTED`; its `options_level`, `cash_balance_cents`, and `equity_value_cents` all start at 0, its `pdt_flag` is `false`, and its `pdt_flagged_at` is null.

KYC is then submitted via a dedicated KYC endpoint that creates a `KYCSubmission` row keyed by `customer_id`. The submission payload carries `government_id_type` (one of `PASSPORT`, `DRIVERS_LICENSE`, or `STATE_ID`), the document's `government_id_number` (1 to 40 characters), the customer's `address_line1`, the two-letter ISO-3166 country code `address_country` (exactly two uppercase letters), and a `w9_signed_name`. Two business-safety predicates fence the call: `address_country` must equal `US` exactly — only US persons are supported, and any other country is rejected with `ERR_KYC_INELIGIBLE_COUNTRY` at HTTP 422 — and the customer's age, derived from `date_of_birth`, must be at least 18 years at the moment of submission, with anything younger rejected with `ERR_KYC_AGE_INELIGIBLE` at HTTP 422. The W-9 name match is the third gate: `w9_signed_name` must equal `Customer.legal_name` after trimming surrounding whitespace and comparing case-insensitively; any mismatch is rejected with `ERR_W9_NAME_MISMATCH` at HTTP 422. KYC submission requires that the customer is either submitting for the first time (`Customer.kyc_status` equal to `NOT_STARTED`) or is resubmitting after a prior rejection (most recent `KYCSubmission.status` equal to `REJECTED`); otherwise no resubmission is permitted while one is already in flight. On success, a `KYCSubmission` row is inserted with its own `status` set to `PENDING` and its `rejection_reason` left null, `Customer.kyc_status` advances to `PENDING`, and the `Account` advances from `PENDING_KYC` to `KYC_REVIEW`.

A compliance officer then verifies or rejects the latest submission. Verification advances `KYCSubmission.status` to `VERIFIED`, sets `Customer.kyc_status` to `VERIFIED`, sets `Customer.w9_collected` to `true`, transitions the `Account` from `KYC_REVIEW` to `APPROVED`, and flips `trading_posture` from `RESTRICTED` to `OPEN` — the latter being the system-driven transition that finally permits trading. Verification is also conditional on `KYCSubmission.address_country` still being `US` and on `KYCSubmission.status` still being `PENDING`; if either is not, the decision is rejected with `ERR_INVALID_STATE`. Rejection sets `KYCSubmission.status` to `REJECTED`, records the populated `rejection_reason`, sets `Customer.kyc_status` to `REJECTED`, and walks the `Account` back to `PENDING_KYC` so the customer can resubmit — this is a deliberate cyclic transition supporting an unbounded revision loop until either verification or account closure.

### 3.2. Options Approval Tiers and the Eligibility Calculation

Once the account is approved and KYC is verified, a customer may submit an `OptionsApproval` request specifying the target `account_id` and a `requested_level` between 1 and 4 inclusive. The new approval row is created with `status` set to `SUBMITTED`, `approved_level` null until decided, `review_notes` null, and `revision_count` set to 0. At most one `OptionsApproval` for a given account may sit in the non-terminal set (`SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`) at any time; a second submission while one is already pending is rejected with `ERR_OPTIONS_APPROVAL_IN_PROGRESS`.

A compliance officer picks up the submission via a start-review action that advances `OptionsApproval.status` from `SUBMITTED` to `UNDER_REVIEW`. Start-review additionally requires that `Account.status` equals `APPROVED` and `Customer.kyc_status` equals `VERIFIED`; otherwise the officer's request is rejected at the §2.9 posture gate. From `UNDER_REVIEW` the officer can take three decisions: approve, request a revision, or reject. Approval requires an `approved_level` in the body and is gated by the system's options-eligibility calculation described below; on success it sets `OptionsApproval.approved_level` to the chosen value and bumps `Account.options_level` to the maximum of its current value and the newly-granted level (so a later, lower approval never demotes an existing higher grant). Requesting a revision requires non-empty `notes` and is permitted only while `revision_count` is strictly less than 3; at the boundary of 3 the action is rejected with `ERR_REVISION_LIMIT_REACHED` at HTTP 409. On success, the request-revision action writes the supplied `notes` into `OptionsApproval.review_notes` and transitions the row to `REVISION_REQUESTED`. From `REVISION_REQUESTED` the customer resubmits supporting data through a customer-driven patch action, which carries an optional `requested_level` and the resource's `version`, transitions the row back to `SUBMITTED`, and increments `revision_count` by exactly 1. Rejection from `UNDER_REVIEW` likewise requires non-empty `notes`, lands the row in terminal `REJECTED`, and unlike the revision branch is not bounded by `revision_count`.

The options-eligibility cap is computed from three customer fields at the moment of decision: `years_options_experience` (call it the years value), `liquid_net_worth_cents`, and `total_net_worth_cents`. The system applies four tier rules in order, each granting eligibility up to one specific level when both its experience floor and its net-worth floor(s) are met, and the final eligibility cap is the highest level whose conditions all hold. Level 1 (covered calls and cash-secured puts) requires years at least 0 and `liquid_net_worth_cents` at least 1,000,000 — that is, at least ten thousand dollars of liquid net worth. Level 2 (long calls and long puts) additionally requires years at least 1 and `liquid_net_worth_cents` at least 5,000,000 — fifty thousand dollars liquid. Level 3 (spreads) additionally requires years at least 2 with `liquid_net_worth_cents` at least 10,000,000 and `total_net_worth_cents` at least 25,000,000 — a hundred thousand dollars liquid and a quarter million dollars total. Level 4 (uncovered / naked options) additionally requires years at least 3 with `liquid_net_worth_cents` at least 25,000,000 and `total_net_worth_cents` at least 50,000,000 — a quarter million dollars liquid and half a million dollars total. The calculation returns the maximum level satisfied by all four predicates evaluated in this order (no rounding — these are exact integer comparisons in cents). On approval, the compliance officer's chosen `approved_level` must be at least 1 and must not exceed this calculated maximum; a value above the cap is rejected with `ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY` at HTTP 422.

The four checks at the approval endpoint are evaluated in this exact order so the failure most useful to the operator surfaces first: account posture (`Account.status` must equal `APPROVED` first), then KYC posture (`Customer.kyc_status` must equal `VERIFIED`), then source-state correctness on `OptionsApproval.status`, then — for the request-revision branch — the revision-count bound, then — for the approve branch — the eligibility-cap check.

### 3.3. Order Submission, Margin, and the Reg T versus PMA Calculation

Order submission is the workhorse trading endpoint and carries a thick payload: `account_id`, `symbol` (uppercase A–Z, 1 to 5 characters), `instrument_type` (`EQUITY` or `OPTION`), an optional `option_strategy` (one of `COVERED_CALL`, `CASH_SECURED_PUT`, `LONG_CALL`, `LONG_PUT`, `SPREAD`, `NAKED_CALL`, or `NAKED_PUT`), `side` (`BUY` or `SELL`), `order_type` (`MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, or `TAKE_PROFIT`), an integer `quantity` of at least 1, and the conditionally-required prices `limit_price_cents` and `stop_price_cents`. The `option_strategy` field is required when and only when `instrument_type` equals `OPTION`; supplying it for an equity order, or omitting it for an options order, is rejected with `ERR_ORDER_STRATEGY_REQUIRED` at HTTP 422. `limit_price_cents` is required for `LIMIT`, `STOP_LIMIT`, and `TAKE_PROFIT` orders; `stop_price_cents` is required for `STOP` and `STOP_LIMIT` orders; any missing price for the chosen `order_type` is rejected with `ERR_ORDER_PRICE_MISSING` at HTTP 422. `quantity` must be a positive integer, and any supplied price field must be strictly greater than 0; any breach is rejected with the generic `ERR_VALIDATION` at HTTP 422.

For options orders, the requested `option_strategy` must be compatible with the account's currently-granted `Account.options_level`. `COVERED_CALL` and `CASH_SECURED_PUT` require an `options_level` of at least 1; `LONG_CALL` and `LONG_PUT` require at least 2; `SPREAD` requires at least 3; `NAKED_CALL` and `NAKED_PUT` require at least 4. Any order whose strategy outranks its account's level is rejected with `ERR_OPTIONS_LEVEL_INSUFFICIENT` at HTTP 422.

The initial margin requirement for the order is computed before the order is accepted, stored on the row as `margin_requirement_cents`, and compared against `Account.cash_balance_cents`; an order whose required initial margin exceeds the available cash balance is rejected with `ERR_INSUFFICIENT_MARGIN` at HTTP 422. The calculation works on the order's notional value, which is `quantity` multiplied by the relevant reference price: `limit_price_cents` for `LIMIT`, `STOP_LIMIT`, and `TAKE_PROFIT` orders; `stop_price_cents` for a plain `STOP` order; and the submitted market-reference price for a `MARKET` order. From notional the system derives a base margin and, in one specific case, an add-on, then sums them — but ceiling rounding is applied to each term **before** the sum, so the rounding order is pinned and cannot be relaxed by aggregating first.

The base term depends on `Account.account_type`. For a `CASH` account, the base equals the full notional — 100% of the trade must be available in cash. For a `MARGIN_REG_T` account, Regulation T's 50% initial-margin rule applies: the base is the notional multiplied by 0.50 and rounded up to the next whole cent. For a `MARGIN_PMA` account, Portfolio Margin's stress-test rate of 15% applies: the base is the notional multiplied by 0.15 and rounded up to the next whole cent — strictly lower than the Reg T figure on identical inputs, which is the entire point of the PMA framework. The add-on term applies only to a `MARGIN_REG_T` account submitting an option order with `option_strategy` equal to `NAKED_CALL` or `NAKED_PUT`; in that single case, an additional 20% of notional, rounded up to the next whole cent, is added to the base. A PMA account submitting a naked option carries no such add-on (PMA replaces the add-on with its lower base rate). On any other combination of `account_type` and `option_strategy`, the add-on is exactly 0.

Once margin clears, the order is persisted with `margin_requirement_cents` set to the computed total. A `MARKET` order auto-fills immediately at the submitted market-reference price: `Order.status` becomes `FILLED`, `fill_price_cents` is set to that reference, `filled_at` is set to the current `now()`, and `Account.cash_balance_cents` is adjusted by signed quantity times fill price (a `BUY` debits the cash balance, a `SELL` credits it). Any non-`MARKET` order is persisted with `Order.status` set to `ACCEPTED` and then automatically advances to `WORKING` on the same request as the system routes it to market. A platform administrator may later fill a `WORKING` order via the operator-fill action, supplying an `execution_price_cents` that respects the order's price semantics: a `LIMIT` `BUY` requires the execution price to be less than or equal to `limit_price_cents`; a `LIMIT` `SELL` requires it greater than or equal to `limit_price_cents`; a `STOP` `BUY` requires it greater than or equal to `stop_price_cents`; a `STOP` `SELL` requires it less than or equal to `stop_price_cents`; a `STOP_LIMIT` order applies both the stop side and the limit side of these rules. Any violation is rejected with `ERR_FILL_PRICE_VIOLATES_LIMITS` at HTTP 422. Operator fill is allowed only when `Order.status` equals `WORKING`; an attempt against any other status returns `ERR_INVALID_STATE`. On success the order moves to `FILLED`, `fill_price_cents` and `filled_at` are recorded, and the cash balance is adjusted just as for the market-order case.

A customer may cancel their own order while it is still in `ACCEPTED` or `WORKING`; the result is `Order.status` set to `CANCELLED`. Cancellation against any other status returns `ERR_INVALID_STATE`. System-driven cascades also drive orders to `CANCELLED`: see §3.4 and §3.6.

### 3.4. Day-Trade Pairing and the Pattern Day Trader Posture

Every time an `Order` transitions to `FILLED`, the system runs day-trade pairing. For the newly-filled order, it looks for an existing same-account `Order` with the same `symbol`, the same UTC trading day (the `trade_date` derived from `filled_at`), `status` equal to `FILLED`, the opposite `side`, and `opened_for_day_trade` still `false`. Candidates are ordered by `filled_at` ascending and then by `id` ascending — FIFO — and the oldest unmatched candidate is paired with the new fill. When a pair is found, both the opener and the closer have their `opened_for_day_trade` flag set to `true`, and a new `DayTrade` row is inserted carrying `account_id`, `symbol`, `opening_order_id` (the opener's `id`), `closing_order_id` (the new fill's `id`), and `trade_date`. If no candidate exists, no `DayTrade` row is created and the new fill remains available as a future opener.

Immediately after any `DayTrade` row is inserted, the system runs the PDT check. The check counts `DayTrade` rows for the same `account_id` whose `trade_date` falls within a rolling window of five business days inclusive of both endpoints — the window starts four business days before today's UTC date and ends today, so a trade on either boundary date counts. (Business days here mean Monday through Friday, no holidays, exactly as in §2.6.) If the count is at least 4 and `Account.equity_value_cents` is strictly less than 2,500,000 (the equivalent of twenty-five thousand US dollars), the Pattern Day Trader threshold has tripped: `Account.pdt_flag` is set to `true`, `Account.pdt_flagged_at` is set to the current `now()`, and `Account.trading_posture` advances from `OPEN` to `PDT_FROZEN`. That posture change drives a depth-3 cascade: every `Order` for this account whose `status` is in the non-terminal set (`ACCEPTED`, `WORKING`) is moved to `CANCELLED`; every `OptionsApproval` for this account whose `status` is in the non-terminal set (`SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`) is moved to terminal `REJECTED` with a reason of `PDT_FREEZE`. The cascade depth is therefore: `DayTrade` insert → account posture flip → order cancellations → options-approval rejections, and each touched row has its `updated_at` refreshed and (where the entity carries it) its `version` incremented.

While `Account.pdt_flag` is `true` and `Account.equity_value_cents` is strictly less than 2,500,000, any further order submission that would create a fourth-or-later day trade in the rolling window is rejected outright with `ERR_PDT_EQUITY_BELOW_MINIMUM` at HTTP 409 — this is the pre-flag block that prevents a flagged account from incurring more day trades without first restoring equity. Note that the generic posture-gate rejection `ERR_TRADING_FROZEN` from §2.9 also applies whenever the account is not `OPEN`, and is evaluated first by virtue of its higher priority.

The PDT freeze is cleared by depositing fresh cash. The customer calls the PDT-reset action, which carries an `equity_top_up_cents` amount; the action adds the supplied amount to `Account.cash_balance_cents`, recomputes the portfolio equity (see §3.7), and — if the resulting `Account.equity_value_cents` is greater than or equal to 2,500,000 and the posture is still `PDT_FROZEN` — flips `Account.trading_posture` back to `OPEN` and sets `Account.pdt_flag` to `false`. If the topped-up equity still falls below 2,500,000, the posture stays at `PDT_FROZEN` and `pdt_flag` remains `true`.

### 3.5. ACAT Transfers and the Six-Business-Day Pipeline

A customer can move assets in or out of the brokerage via an `ACATTransfer`. Initiation accepts `account_id`, `direction` (`INBOUND` if assets are arriving, `OUTBOUND` if assets are leaving), `counterparty_brokerage`, `counterparty_account_number`, and `requested_value_cents`; the transfer value is in US cents, and a minimum of 100 cents (one dollar) is enforced — anything below is rejected with `ERR_VALIDATION`. The new row is created with `status` set to `INITIATED`, `initiated_at` set to the current `now()`, `expected_completion_at` and `completed_at` null until later, and `business_days_elapsed` at 0. At most one `OUTBOUND` transfer per account may sit in a non-terminal status (`INITIATED`, `VALIDATED`, or `IN_TRANSIT`); a second outbound submission against the same account is rejected with `ERR_TRANSFER_ALREADY_PENDING` at HTTP 409.

A compliance officer then validates the transfer. Validation requires `Account.status` equal to `APPROVED`, `Customer.kyc_status` equal to `VERIFIED`, and — when `direction` is `OUTBOUND` — no `Order` whose `status` is in `ACCEPTED` or `WORKING`; an outbound validate attempted with open orders is rejected with `ERR_OPEN_ORDERS_BLOCK_TRANSFER` at HTTP 409. On success, the transfer advances to `VALIDATED` and `expected_completion_at` is set by walking the calendar forward from `initiated_at`: starting from the calendar date of `initiated_at`, add one calendar day at a time and decrement a remaining counter each time the new date is a Monday, Tuesday, Wednesday, Thursday, or Friday; stop when the counter reaches 0, having consumed exactly 6 business days. The resulting date is then pinned to 17:00:00 UTC (zeroed seconds, milliseconds, etc.). When `direction` is `OUTBOUND`, validation also flips `Account.trading_posture` from `OPEN` to `TRANSFER_LOCKED` as a cascade and cancels every `Order` on the account whose `status` is in `ACCEPTED` or `WORKING` — order submission is disabled for the duration of the transfer-lock.

Once `VALIDATED`, the transfer's progress is driven by the logical clock. When the clock crosses `initiated_at` plus one business day, `business_days_elapsed` becomes greater than or equal to 1 and the transfer auto-advances from `VALIDATED` to `IN_TRANSIT`. When the clock subsequently crosses `expected_completion_at`, the transfer auto-advances from `IN_TRANSIT` to `COMPLETED`: `completed_at` is set to the current `now()`, and the cash and equity adjustments apply. An `INBOUND` completion adds `requested_value_cents` to both `Account.cash_balance_cents` and `Account.equity_value_cents`. An `OUTBOUND` completion subtracts `requested_value_cents` from both `Account.cash_balance_cents` and `Account.equity_value_cents`, and additionally — if the account is still in `TRANSFER_LOCKED` — reverts `Account.trading_posture` to `OPEN`, since the outbound pipeline has now settled. (Posture re-evaluation as part of an outbound completion is the cascade that closes the lock.)

Compliance can also reject a still-`INITIATED` transfer outright, carrying a `reason` in the body; this moves the row directly to terminal `REJECTED`. The customer can cancel a transfer that is still in `INITIATED` or `VALIDATED`; cancellation moves the row to terminal `CANCELLED`, and — if the cancellation occurs on a `VALIDATED` `OUTBOUND` transfer — the trading posture reverts from `TRANSFER_LOCKED` back to `OPEN`. Once a transfer has advanced to `IN_TRANSIT`, customer cancellation is no longer possible: an attempt is rejected with `ERR_INVALID_STATE`. The transition back from `TRANSFER_LOCKED` to `OPEN` (whether driven by completion, rejection, or cancellation) takes effect only when no other `OUTBOUND` `ACATTransfer` for the account is still in `VALIDATED` or `IN_TRANSIT`.

### 3.6. Account Closure

A customer can close an `APPROVED` account, but only when every dependency is settled: there must be no `Order` whose `status` is in `ACCEPTED` or `WORKING`, no `ACATTransfer` whose `status` is in `INITIATED`, `VALIDATED`, or `IN_TRANSIT` for this account, and `Account.cash_balance_cents` must equal 0 and `Account.equity_value_cents` must equal 0. Any unsettled dependency surfaces as `ERR_ACCOUNT_HAS_DEPENDENCIES` at HTTP 409. On success, `Account.status` advances from `APPROVED` to terminal `CLOSED` and `Account.trading_posture` is set back to `RESTRICTED`. Closure also requires `Customer.kyc_status` equal to `VERIFIED` — a customer cannot close an account whose KYC has been revoked or never completed.

### 3.7. Portfolio Equity and Mark-to-Market

`Account.equity_value_cents` is recomputed on three triggers: every time an `Order` fills (whether through `MARKET` auto-fill or operator fill), every time an `ACATTransfer` completes, and every time the PDT check runs. The calculation starts from `Account.cash_balance_cents` as the cash component. It then walks every `Order` row for the account whose `status` is `FILLED` and groups them by `symbol`. Only `EQUITY` instruments contribute to the equity calculation — options are excluded from the mark-to-market. For each symbol group, the system computes a net signed quantity by summing the `quantity` of `BUY` fills and subtracting the `quantity` of `SELL` fills, and identifies the most recent `fill_price_cents` for the symbol (the row with the largest `filled_at`, restricted to `EQUITY` orders for that symbol). If there is no last price for the symbol or if the net signed quantity is less than or equal to 0, the contribution of that symbol is exactly 0. Otherwise the contribution is the net quantity multiplied by the last price. The per-symbol contributions are summed and added to the cash component to produce the new `Account.equity_value_cents`. Per-symbol contributions are computed before being summed — the precision rule of §2.7 applies here term-by-term rather than to the aggregate.

### 3.8. Administrative Test-Driving: Clock and Sweep

The system exposes two test-only administrative capabilities reserved for the `PlatformAdmin` role. The first advances the server's logical clock by a number of `seconds` supplied in the request body. Advancing the clock recomputes every active `ACATTransfer.business_days_elapsed` and applies any newly-due time-gated transitions: a `VALIDATED` transfer whose `business_days_elapsed` has reached at least 1 auto-advances to `IN_TRANSIT`; an `IN_TRANSIT` transfer whose `expected_completion_at` is at or before the new `now()` auto-advances to `COMPLETED`, applying the cash/equity adjustments described in §3.5. The second is an explicit sweep capability that does the same evaluation pass without advancing the clock — it re-runs ACAT time-gate checks and reruns the PDT check across accounts, recomputing postures and applying any pending cascades. These two capabilities, together, give the test harness deterministic control over every time-driven transition in the system.

---

## 4. Endpoint Definitions

All endpoints are mounted under the `/brokerage` path prefix. Endpoints that create a new resource return HTTP 201 on success and the created resource body in the standard success envelope. Endpoints that modify, transition, or read an existing resource return HTTP 200. Failure responses use the appropriate 4xx status from the error catalogue in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/brokerage/customers` | Create a new `Customer` (no KYC yet) | `Customer`, `PlatformAdmin` |
| GET | `/brokerage/customers/{customer_id}` | Read a single `Customer` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/brokerage/customers/{customer_id}/kyc` | Submit KYC and W-9; creates `KYCSubmission`; advances account from `PENDING_KYC` to `KYC_REVIEW` | `Customer` |
| POST | `/brokerage/customers/{customer_id}/kyc/decision` | Compliance verifies or rejects the latest `KYCSubmission` | `ComplianceOfficer` |
| POST | `/brokerage/accounts` | Create an `Account` for an existing customer | `Customer` |
| GET | `/brokerage/accounts/{id}` | Read a single `Account` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/brokerage/accounts` | List accounts, paginated; filter by `customer_id`, `status` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/brokerage/accounts/{id}/close` | Close an account when all dependencies are settled | `Customer` |
| POST | `/brokerage/accounts/{id}/pdt/reset` | Top up cash via `equity_top_up_cents` and clear the PDT freeze when equity is restored | `Customer` |
| POST | `/brokerage/options-approvals` | Submit a new `OptionsApproval` | `Customer` |
| GET | `/brokerage/options-approvals/{id}` | Read a single `OptionsApproval` | `Customer`, `ComplianceOfficer` |
| POST | `/brokerage/options-approvals/{id}/start-review` | Compliance opens the approval for review | `ComplianceOfficer` |
| POST | `/brokerage/options-approvals/{id}/decide` | Compliance decides: approve, request revision, or reject | `ComplianceOfficer` |
| PATCH | `/brokerage/options-approvals/{id}` | Customer resubmits after a revision request; increments `revision_count` | `Customer` |
| POST | `/brokerage/orders` | Submit an order; runs margin and PDT checks | `Customer` |
| GET | `/brokerage/orders/{id}` | Read a single `Order` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/brokerage/orders` | List orders, paginated; filter by `account_id`, `symbol`, `status` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/brokerage/orders/{id}/fill` | Operator simulates a fill of a `WORKING` order at an `execution_price_cents` | `PlatformAdmin` |
| DELETE | `/brokerage/orders/{id}` | Customer cancels an `ACCEPTED` or `WORKING` order | `Customer` |
| POST | `/brokerage/acat-transfers` | Initiate an ACAT transfer | `Customer` |
| GET | `/brokerage/acat-transfers/{id}` | Read a single `ACATTransfer` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/brokerage/acat-transfers` | List transfers, paginated; filter by `account_id`, `direction`, `status` | `Customer`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/brokerage/acat-transfers/{id}/validate` | Compliance validates; computes `expected_completion_at` | `ComplianceOfficer` |
| POST | `/brokerage/acat-transfers/{id}/reject` | Compliance rejects an `INITIATED` transfer; carries a `reason` | `ComplianceOfficer` |
| DELETE | `/brokerage/acat-transfers/{id}` | Customer cancels an `INITIATED` or `VALIDATED` transfer | `Customer` |
| POST | `/brokerage/_clock/advance` | Test-only: advance the logical clock by `seconds`; applies time-gated transitions | `PlatformAdmin` |
| POST | `/brokerage/_sweep/run` | Test-only: re-run ACAT time-gate and PDT evaluation | `PlatformAdmin` |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_OPTIONS_APPROVAL_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_NOT_APPROVED` | 409 |
| `ERR_KYC_NOT_VERIFIED` | 409 |
| `ERR_TRADING_FROZEN` | 409 |
| `ERR_KYC_INELIGIBLE_COUNTRY` | 422 |
| `ERR_KYC_AGE_INELIGIBLE` | 422 |
| `ERR_W9_NAME_MISMATCH` | 422 |
| `ERR_OPTIONS_LEVEL_INSUFFICIENT` | 422 |
| `ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY` | 422 |
| `ERR_ORDER_PRICE_MISSING` | 422 |
| `ERR_ORDER_STRATEGY_REQUIRED` | 422 |
| `ERR_FILL_PRICE_VIOLATES_LIMITS` | 422 |
| `ERR_PDT_EQUITY_BELOW_MINIMUM` | 409 |
| `ERR_INSUFFICIENT_MARGIN` | 422 |
| `ERR_OPEN_ORDERS_BLOCK_TRANSFER` | 409 |
| `ERR_ACCOUNT_HAS_DEPENDENCIES` | 409 |
| `ERR_TRANSFER_ALREADY_PENDING` | 409 |
| `ERR_OPTIONS_APPROVAL_IN_PROGRESS` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 409 |
