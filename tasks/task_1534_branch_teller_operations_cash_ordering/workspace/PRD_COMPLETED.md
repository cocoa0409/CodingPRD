# Branch Teller Operations API — Product Requirements Document

## 1. Introduction

Community banks live and die by the integrity of their teller line. Every dollar that moves across the counter — into a drawer, out of the vault, onto a deposit slip, or into a cashier's check — must be accounted for twice: once in the ledger and once in physical cash, with the two reconciled under dual control at the close of every business day. Regulators layer their own obligations on top: currency transaction reports when a customer's same-day cash activity crosses a federal threshold, funds-availability rules that decide when a deposited check becomes spendable, and surprise audits that can freeze a branch's cash operation without warning.

This document specifies the Branch Teller Operations API, the system of record for a single community-bank branch network's cash life. It governs how teller drawers are opened, funded from the vault, and balanced at close; how branch cash orders are forecast from day-of-week history, rounded to shipment steps, and gated by vault capacity; how over/short variances become investigation cases with segregation of duties on every sensitive decision; how negotiable instruments are issued only under dual-control approval; how check deposits acquire holds under the funds-availability policy; and how auditors schedule or surprise-launch cash counts that freeze the branch until every drawer and the vault are reconciled.

An important environmental note: the platform runs on a **logical clock**, not wall-clock time. Until an operator explicitly advances it, the logical clock reads exactly `2026-08-01T00:00:00Z` — a fixed, well-defined instant that precedes every business event in this document. All date-dependent behavior (business-day windows, hold releases, delivery dates, request expiry) derives from this clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role string the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the role is not permitted to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Four roles exist, spelled exactly as follows:

- **`BranchManager`** — the branch's chief operating authority: opens branches, hires and suspends tellers, closes accounts, decides cash orders and teller requests, voids transactions, attests drawer counts, waives holds, and manages over/short cases.
- **`HeadTeller`** — the line supervisor: opens accounts and drawer sessions, approves or rejects teller requests, places cash orders, and personally receives armored deliveries.
- **`Teller`** — the line role that operates a drawer: posts customer transactions, buys and sells cash against the vault, counts the drawer at close, raises dual-control requests, and places cash orders.
- **`Auditor`** — internal audit: schedules and conducts audits, attests drawer counts, and reads the compliance record.

When `X-User-Role` is `Teller`, `X-User-ID` is the `id` of the acting `Teller` resource; ownership checks on any resource that references a `Teller` compare the resource's foreign-key field to `X-User-ID`. In practice this means a teller can post transactions, buy or sell vault cash, record a count, or raise a request only on the drawer whose `teller_id` equals their `X-User-ID`; a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `BranchManager`, `HeadTeller`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires an actor (for example, `decided_by_user_id` on a cash order, `approved_by_user_id` on an approval record, or `voided_by_user_id` on a voided transaction) and compares it against creator identities for segregation-of-duties purposes, but never treats it as the `id` of any entity.

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

Every list endpoint accepts the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100; `offset` defaults to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside `meta`, with `has_more` true exactly when further items exist beyond the returned window. All list endpoints return their resources ordered by `created_at` ascending; this ordering is stable and deterministic and is never influenced by resource ids. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Resource Identity and Change Tracking

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix (for example, `8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2`), assigned at creation and immutable thereafter; any client-supplied `id` in a creation payload is ignored. Ids identify resources in paths and foreign keys but never decide business outcomes — no selection, ordering, tie-break, or allocation rule may consume an `id`.

Most resources additionally carry `created_at` (an ISO 8601 UTC timestamp with three fractional digits), `updated_at` (same format, refreshed on every mutation including cascaded side effects), and `version` (an integer starting at 1 that increments by exactly one on every mutation). The two exceptions are the compliance records `Approval` and `CTRFiling`, which are append-only in spirit: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them.

A resource's JSON representation carries exactly the fields this document attributes to that resource (including its common fields) — nothing more. Internal bookkeeping never appears in a response, and payload fields the receiving endpoint does not use are ignored rather than rejected.

### 2.5. The Logical Clock and Business-Day Arithmetic

The platform's notion of "now" is a logical clock, advanced exclusively through an admin-only test-driving capability that sets the current instant to a supplied `to_iso8601` value. Before any such call, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. The clock moves forward only: a call naming an instant earlier than the current logical time is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). All roles may advance the clock. Every write the server performs — each creation and each mutation — additionally advances the logical clock by one millisecond before stamping `created_at` / `updated_at`, so timestamp order always mirrors mutation order exactly.

Dates matter more than instants. A resource's **business date** is the calendar date (in UTC) of the logical clock at the moment the resource is created or an operation occurs. Business-day arithmetic — used by the funds-availability schedule — counts only Monday through Friday: adding *n* business days to a date walks forward over that many weekdays, never counting the starting date itself, and skips Saturdays and Sundays.

Advancing the clock to a later calendar date has two automatic consequences, applied atomically with the clock change: every teller request still `PENDING` from an earlier date transitions to `EXPIRED`, and every active hold whose scheduled release day has been reached releases, crediting its amount to the account's `balance_cents`.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, and these are the only endpoints that accept a version field:

- Placing a cash order requires the request body to carry `expected_branch_version`, the branch's `version` as the client last observed it. Because placing an order itself advances the branch's `version` by one (as does any other branch mutation, including a delivery crediting the vault), a client whose view is stale must be turned away: if the supplied value does not equal the branch's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Closing a teller drawer requires `expected_drawer_version`, the drawer's `version` as last observed. A mismatch with the drawer's current `version` — for example because a recount or an audit adjustment advanced it — is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field.

### 2.7. Monetary Representation and Rounding Discipline

All monetary values are integer cents, carried in fields suffixed `_cents`; there is no floating-point money anywhere in the system. Where a computation produces a fractional intermediate (the forecasting means), the final result is brought to whole cents exactly once, at the end, using ceiling — including for negative values, where the ceiling of a negative number is the nearest integer toward positive infinity. Step quantities (cash-order amounts) round **down** to whole steps; the rounding order for orders is fixed and described in §3.4.

### 2.8. Validation Order and Error Precedence

A request that would fail several checks receives exactly one error, determined by a strict evaluation order. Authentication comes first (missing or unrecognized credentials, `ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then resource existence along the URL path from left to right — a child identifier that exists but belongs to a different parent is reported as not found (`ERR_NOT_FOUND`, HTTP 404). Next come state preconditions (the target resource must be in a state that permits the operation, `ERR_INVALID_STATE`, HTTP 409; closed-account references, `ERR_ACCOUNT_CLOSED`; an unreleased hold blocking a void, `ERR_HOLD_ALREADY_RELEASED`; an unresolved over/short case blocking a drawer close, `ERR_OVER_SHORT_UNRESOLVED`). Safety and compliance checks follow: the audit freeze (`ERR_BRANCH_FROZEN`), dual control (`ERR_DUAL_CONTROL_VIOLATION`), segregation of duties (`ERR_SOD_VIOLATION`), teller suspension (`ERR_TELLER_SUSPENDED`), and the instrument-approval gate (`ERR_INSTRUMENT_REQUIRES_APPROVAL`). Next are structural constraints (`ERR_INVALID_REQUEST`, HTTP 400, for malformed payloads, invalid enum values, or non-positive amounts; `ERR_DRAWER_ALREADY_OPEN`; `ERR_DUPLICATE_CASH_ORDER`; `ERR_AUDIT_IN_PROGRESS`; `ERR_WAIVER_NOT_ALLOWED`), then temporal rules (`ERR_INVALID_DELIVERY_DATE`, `ERR_ORDER_NOT_DUE`, `ERR_INVALID_AUDIT_DATE`, `ERR_AUDIT_NOT_DUE`, `ERR_CLOCK_REGRESSION`), then referential checks (`ERR_CROSS_BRANCH`; `ERR_TRANSACTION_NOT_FOUND` for a fee-waiver subject), and only then the fiscal family (`ERR_INSUFFICIENT_DRAWER_CASH`, `ERR_INSUFFICIENT_FUNDS`, `ERR_TRANSACTION_OVER_LIMIT`, `ERR_DRAWER_LIMIT`, `ERR_INSUFFICIENT_VAULT_CASH`, `ERR_INSTRUMENT_LIMIT`, `ERR_ORDER_BELOW_MINIMUM`, `ERR_VAULT_CAPACITY_EXCEEDED`). The optimistic-concurrency version check (`ERR_STALE_VERSION`) is evaluated last. The practical consequence: a frozen branch masks an insufficient-funds problem, and a stale state masks an over-limit problem — never the reverse.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Branch

Before the first customer walks in, a `BranchManager` establishes the branch itself, supplying its `name` and three policy numbers that will govern everything that follows: `drawer_limit_cents`, the per-drawer cash cap enforced at the vault window; `vault_cash_cents`, the physical cash on hand at opening; and `over_short_investigation_threshold_cents`, the absolute counting variance at which an over/short investigation becomes mandatory. All three policy numbers are non-negative whole numbers of cents. A new branch is `OPEN` — its only other posture, `AUDIT_FROZEN`, arrives through the audit workflow in §3.9.

Tellers join the branch when the manager records a `display_name`; each new teller starts `ACTIVE`. An account opens with an `owner_name` and an opening `balance_cents`, which may be any whole number of cents; it begins `OPEN` and remains so until the manager closes it. Closing an account is permitted only when its `balance_cents` is exactly zero and no hold on it is still `ACTIVE` — otherwise the attempt is refused with `ERR_ACCOUNT_NOT_SETTLED`. Transactions and instrument issuance always reference the account through an `account_id` in the payload, and the account must belong to the same branch as the drawer serving the customer; a mismatch is rejected with `ERR_CROSS_BRANCH` (HTTP 422), and any reference to a `CLOSED` account is `ERR_ACCOUNT_CLOSED`.

Every teller and every account is anchored to exactly one branch through its `branch_id`, assigned by the server from the creation path, and every resource created inside a branch — drawers, transactions, orders, requests, holds, filings, cases, audits — inherits that same anchor at creation.

### 3.2. The Drawer Day: Opening, Funding, and the Buy/Sell Discipline

A teller's workday begins when a `HeadTeller` or `BranchManager` opens their drawer. The drawer session is bound to the teller through `teller_id`, anchored to the branch through `branch_id`, and stamped with the current business date in `business_date`. One teller, one drawer, one day: a second open call while any session for that teller is unclosed — or a new session on a business date the teller has already used — is refused with `ERR_DRAWER_ALREADY_OPEN`. A `SUSPENDED` teller's drawer cannot be opened at all (`ERR_TELLER_SUSPENDED`), and no drawer opens while the branch is `AUDIT_FROZEN` (`ERR_BRANCH_FROZEN`).

The drawer never starts empty-handed except on the teller's very first day. Opening a drawer carries forward cash: the new session's `cash_balance_cents` is initialized to the teller's previous `CLOSED` drawer's `counted_cash_cents` — the physically attested amount from the prior session — or to zero when no prior session exists.

Once `OPEN`, the drawer trades with the vault. Buying moves cash from vault to drawer: the branch's `vault_cash_cents` must cover the `amount_cents` requested (`ERR_INSUFFICIENT_VAULT_CASH` otherwise), and the buy is rejected with `ERR_DRAWER_LIMIT` whenever the drawer's balance after the buy would be greater than or equal to the branch's `drawer_limit_cents` — a teller may not buy their way up to or past the cap. Selling moves cash drawer to vault under the mirror-image discipline: the teller may sell only when the drawer's current balance has reached or exceeded the cap, and the sale must bring the drawer strictly below it. A sell attempted while the drawer sits below the cap, or one whose amount leaves the drawer at or above the cap, fails with `ERR_DRAWER_LIMIT`. The cap constrains only these two vault movements; customer transactions are never blocked by it. Only the drawer's owning teller may buy or sell on it.

At any moment, the system tracks the drawer's `expected_cash_cents`: the carry-forward baseline, plus the signed cash effect of every `POSTED` transaction on the drawer (deposits add their `amount_cents`; withdrawals subtract theirs; check deposits contribute nothing, since no currency moves; instrument purchases add the face amount plus the issuance `fee_cents` actually collected), plus buys from the vault, minus sells to it. This is the `STRICT` reading, and it is the value the close relies on. A preview reading, `LENIENT`, treats instrument-purchase cash as vault-settled and excludes it; the two readings diverge precisely when instruments have been purchased at the window. The drawer's `last_close_variant` records which reading the most recent close used, and it is always `STRICT`. Until the owning teller's first count, `counted_cash_cents` is null; `variance_cents` is null until the first attestation computes it; and `last_close_variant` is null until the first attestation and `STRICT` thereafter. Both readings are available through the drawer's expected-cash preview, which accepts an optional `variant` selector defaulting to `STRICT` and rejects any other value with `ERR_INVALID_REQUEST`.

### 3.3. Serving Customers: Transactions at the Window

The owning teller posts customer activity against their `OPEN` drawer as transactions, each carrying an `account_id`, a `type`, an `amount_cents` that must be a positive whole number of cents, and an optional `is_ctr_exempt` flag (defaulting to false) marking customers whose cash activity is exempt from currency-transaction reporting. Three types post directly at the window:

- `CASH_DEPOSIT` — the account's `balance_cents` increases by the amount; the drawer's cash increases by the amount.
- `CASH_WITHDRAWAL` — the account's available funds must cover the amount, where available funds are the account's `balance_cents` minus the amounts of its holds still `ACTIVE` (a shortfall is `ERR_INSUFFICIENT_FUNDS`); the drawer must physically hold at least the amount (`ERR_INSUFFICIENT_DRAWER_CASH`); and a teller-direct withdrawal may not exceed the per-transaction limit of 500000 cents — anything larger is `ERR_TRANSACTION_OVER_LIMIT` and must travel the dual-control path of §3.5. On success the account and the drawer both decrease by the amount.
- `CHECK_DEPOSIT` — no currency moves at the window, so the drawer is untouched; the account and the funds-availability machinery behave as §3.7 describes.

Two further types exist but may never be posted directly: `CASHIERS_CHECK_PURCHASE` and `MONEY_ORDER_PURCHASE` are rejected at the window with `ERR_INSTRUMENT_REQUIRES_APPROVAL`, because negotiable instruments are issued only through an approved dual-control request. The teller must be `ACTIVE` to post anything (`ERR_TELLER_SUSPENDED`), the drawer must be `OPEN` (`ERR_INVALID_STATE`), and no posting is possible while the branch is `AUDIT_FROZEN`.

Every transaction is born `POSTED`, records its `drawer_id`, its `account_id`, and the `branch_id` of the drawer that served it, and carries a computed `fee_cents` — zero for everything except instrument purchases. Each posting re-evaluates the currency-transaction-report aggregation of §3.6 for the affected account and business date. All changes are visible immediately: a posted transaction is fully readable, with its computed fields, in the same instant, and the drawer's expected cash already reflects it.

### 3.4. Ordering Cash for the Branch

When the vault runs lean ahead of a busy day, a `Teller` or `HeadTeller` places a cash order naming a `delivery_date` and — because the decision rests on a forecast anyone else could invalidate — the branch-version guard of §2.6. The `delivery_date` must be a Monday-through-Friday date strictly later than the order's own business date, or the request fails with `ERR_INVALID_DELIVERY_DATE`. The order records its `order_date` (the business date of placement) and the placing operator's identity in `created_by_user_id` for segregation of duties later. A branch may hold at most one order in `PENDING` or `APPROVED` for a given delivery date; a second order for an occupied date is refused with `ERR_DUPLICATE_CASH_ORDER` — though once the occupying order is `REJECTED` (or otherwise terminal), the date is free again. No order may be placed while the branch is `AUDIT_FROZEN`.

The order's heart is its forecast. The system projects the branch's cash need for the delivery date from the twenty-eight calendar days ending the day before the order date — both endpoints of that window included. Within the window it considers only days on which at least one `POSTED` cash deposit or cash withdrawal exists for the branch (a day with neither is not evidence and contributes nothing), and for each such day it computes the net outflow: the day's total posted cash withdrawals minus its total posted cash deposits. Days sharing the delivery date's day of week form the same-weekday sample; all other sampled days form the other-days sample. When the same-weekday sample holds at least three days, the forecast trusts it alone: the projected need is the arithmetic mean of those days' net outflows, ceiled once to whole cents at the end. When the same-weekday sample is too thin but at least one sample exists anywhere, the projected need is a weighted blend — seventy percent of the same-weekday mean plus thirty percent of the other-days mean, with each group's mean computed in exact arithmetic, a missing group contributing nothing and its weight shifting to the group that does have samples, and the single ceiling applied to the blended result. With no samples at all, the projected need is zero. Management may also ask, through the branch's forecast preview, for the always-blended comparison figure: the preview's response carries `projected_need_cents` (the official reading), `weighted_need_cents` (the seventy-thirty blend applied unconditionally, with a missing group contributing zero and no renormalization), and `suggested_order_cents`. The preview requires a `delivery_date`; a missing or unparseable date is `ERR_INVALID_REQUEST`.

On the order itself, `projected_need_cents` stores the official reading. `suggested_order_cents` is the projected need minus the branch's current `vault_cash_cents`, floored at zero — a vault already holding more than the need suggests ordering nothing. The quantity actually ordered, `ordered_amount_cents`, is then determined in a fixed sequence. First, the raw quantity is the request's optional `requested_amount_cents` when supplied, or the suggestion otherwise. Second, that raw quantity is rounded down to a whole multiple of the 100000-cent shipment step. Third, the remaining vault headroom — the vault capacity of 100000000 cents minus the cash presently on hand, never below zero — is itself rounded down to a whole step. Fourth, the ordered amount is the smaller of the two step-rounded figures. If that figure is zero, there is nothing to ship and the order is refused with `ERR_ORDER_BELOW_MINIMUM`.

An order begins `PENDING`. A `BranchManager` approves or rejects it — in both cases the manager's `X-User-ID` must differ from the placing operator's `created_by_user_id`, or the decision is refused with `ERR_SOD_VIOLATION` — and the decider is recorded in `decided_by_user_id`, which is null while the order is `PENDING`. Approval moves the order to `APPROVED`; rejection to terminal `REJECTED`. An approved order may still be cancelled by the manager, moving it to terminal `CANCELLED`, so long as it has not been delivered.

On the delivery date itself — the logical business date must equal `delivery_date`, or the attempt is `ERR_ORDER_NOT_DUE` — a `HeadTeller` receives the shipment, moving the order to terminal `DELIVERED` and adding `ordered_amount_cents` to the branch's `vault_cash_cents`. Delivery re-verifies capacity at that moment: if crediting the order would push the vault above its 100000-cent-step capacity ceiling of 100000000 cents, the delivery is refused with `ERR_VAULT_CAPACITY_EXCEEDED` and the order remains `APPROVED`. Deliveries do not happen under an audit freeze.

### 3.5. Dual Control at the Teller Line

Three sensitive actions never execute on a teller's own authority: issuing a negotiable instrument, refunding an instrument fee, and pushing a withdrawal past the per-transaction limit. Each begins as a request the teller raises against their own `OPEN` drawer, carrying a `type` — `ISSUE_INSTRUMENT`, `FEE_WAIVER`, or `OVER_LIMIT_TRANSACTION` — and a `params` object whose shape depends on the type. The request remembers its `teller_id`, its `drawer_id`, its `branch_id`, and the creating operator in `requested_by_user_id`, and it starts `PENDING`.

A `HeadTeller` or `BranchManager` then decides. The decider's `X-User-ID` must differ from `requested_by_user_id`; a self-decision is `ERR_SOD_VIOLATION` whether it arrives under a manager role or any other. Approval moves the request to `EXECUTED` **and performs the requested action atomically in the same moment**; rejection moves it to `REJECTED` and performs nothing. Execution re-validates the requested action against live state — the request's drawer must still be `OPEN` and the branch unfrozen, alongside the action's own rules — and if any check fails, the approval itself fails with that rule's error and the request stays `PENDING`. Waiving the fee of an instrument whose fee was already zero credits zero cents. Either decision writes an immutable `Approval` record — the decision ledger of §3.10 — with `action_type` `TELLER_REQUEST`, the request as its subject, and the decider in `approved_by_user_id`. A request that is still `PENDING` when the logical clock first lands on a later calendar date than its creation date expires automatically to `EXPIRED`, and nothing may execute it thereafter.

For `ISSUE_INSTRUMENT`, `params` names the `account_id` the purchase is attributed to, an `instrument_type` of `CASHIERS_CHECK` or `MONEY_ORDER`, the face `amount_cents`, and a `fee_waived` flag. The customer pays cash at the window: the face amount plus the issuance fee. The fee is fixed per instrument type — 800 cents for a cashier's check, 200 for a money order — and the waiver flag, when true, zeroes it. The evaluation order is fixed and not negotiable: the fee is decided first, from the instrument type and the waiver flag alone, and only then is the total cash received computed as face plus fee; the fee never depends on the total. A money order's face may not exceed 100000 cents (`ERR_INSTRUMENT_LIMIT`); a cashier's check has no face cap. Execution creates a transaction of type `CASHIERS_CHECK_PURCHASE` or `MONEY_ORDER_PURCHASE` in `POSTED` status, records the fee actually collected in its `fee_cents`, and adds face plus fee to the drawer's cash. Because the instrument is bought with currency, the account's `balance_cents` is not debited — the account identity exists for reporting, and the instrument's face amount participates in the currency-transaction aggregation of §3.6 (the fee never does).

For `FEE_WAIVER`, `params` names a `transaction_id`: an existing `POSTED` instrument-purchase transaction on the same branch (anything else — an unknown id, a voided transaction, a non-instrument transaction, another branch's transaction — is `ERR_TRANSACTION_NOT_FOUND`, HTTP 404). Execution refunds the fee by adding the transaction's `fee_cents` back to the account's `balance_cents`; the drawer's cash is untouched by the refund.

For `OVER_LIMIT_TRANSACTION`, `params` names the `account_id`, the `amount_cents`, and the `is_ctr_exempt` flag of a withdrawal the teller may not post directly. Execution posts that `CASH_WITHDRAWAL` with the per-transaction limit check set aside — all other rules, including available-funds and drawer-cash sufficiency, still apply at execution time; if any fails, the whole approval fails with that rule's error and the request does not execute.

### 3.6. Large Cash and the Currency Transaction Report

Federal reporting watches the customer, not the ticket. After every posting or void that touches cash, the system re-aggregates the affected account's same-business-day cash activity at its branch, considering only `POSTED` transactions whose `is_ctr_exempt` is false. Same-day **cash in** is the sum of cash deposits plus the face amounts of instrument purchases — explicitly excluding instrument fees. Same-day **cash out** is the sum of cash withdrawals. Either total crossing 1000000 cents — strictly greater than; a total of exactly 1000000 files nothing — obliges the branch to file.

When an obligation exists and no filing yet exists for that account, branch, and business date, the system creates a `CTRFiling` in `FILED` status, recording `business_date`, the two totals `total_cash_in_cents` and `total_cash_out_cents`, the contributing transaction identifiers in `transaction_ids` ordered by their `created_at` ascending, and a `trigger_direction` of `CASH_IN`, `CASH_OUT`, or `BOTH` according to which totals crossed. Later activity on the same day refreshes the filing's totals, direction, and transaction list in place. When a void or reversal pulls every total back to the threshold or below, the filing is not deleted — it flips to `AMENDED`, preserving the record that an obligation once existed and keeping the `trigger_direction` it last held; and if fresh activity pushes a total back over the threshold, an `AMENDED` filing returns to `FILED`. Exempt-flagged activity is invisible to all of this: it neither triggers a filing nor appears in a filing's totals.

### 3.7. Funds Availability: Holds on Check Deposits

A check is not cash. When a `CHECK_DEPOSIT` posts, the account is credited immediately only with the first 20000 cents of the check's face — the next-day availability portion — or with the full face when the check is smaller than that. The remainder is captured into a `Hold` on the account, recorded with its `transaction_id`, its `account_id`, its `branch_id`, and the held `amount_cents`.

The hold's terms depend on the check's size. A face of 500000 cents or less produces a hold whose `hold_type` is `STANDARD`, with a `release_day_offset` of 2: the held funds release on the second business day after the deposit's business date. A face even one cent larger produces a `hold_type` of `LARGE_CHECK` with a `release_day_offset` of 7. The boundary is inclusive toward the smaller schedule — exactly 500000 is `STANDARD`. Every check deposit creates a hold, even one small enough that the held amount computes to zero. Release is automatic: when the logical clock's date reaches the computed business-day point, the hold moves to `RELEASED` and the held amount is added to the account's `balance_cents` — whatever the account's status is at that moment.

A `BranchManager` may waive an `ACTIVE` hold for a known-good customer, moving it to `WAIVED` and shortening its `release_day_offset` to 1 — the funds then release one business day after the deposit date, through the same automatic path, and the waiver is memorialized as an `Approval` with `action_type` `HOLD_WAIVER`. A hold that is no longer `ACTIVE` cannot be waived (`ERR_INVALID_STATE`).

Holds discipline withdrawals: as §3.3 states, the funds available for a withdrawal are the balance minus amounts still `ACTIVE` in holds. They also constrain corrections, as §3.10 describes.

### 3.8. Closing the Day: Count, Attest, and the Over/Short Discipline

Closing a drawer is a two-person ceremony. The owning teller first records the physical count — a non-negative whole number of cents: the drawer moves from `OPEN` to `COUNTING`, and the attested figure lands in `counted_cash_cents`. A drawer can only be counted from `OPEN` — a second count, or a count after close, is `ERR_INVALID_STATE`.

Then a second person — a `BranchManager` or an `Auditor`, and crucially anyone other than the counting teller — attests. If the attestor's `X-User-ID` equals the drawer's `teller_id`, the attempt fails with `ERR_DUAL_CONTROL_VIOLATION` and the drawer stays `COUNTING`. On a good attest the drawer's `cash_balance_cents` is set to the counted figure — the physical count wins — and the system computes `variance_cents` as the counted figure minus the `STRICT` expected cash, positive when the drawer is over and negative when it is short. A variance of exactly zero lands the drawer in `BALANCED`; any nonzero variance lands it in `OUT_OF_BALANCE`.

A variance whose absolute value reaches or exceeds the branch's `over_short_investigation_threshold_cents` automatically opens an `OverShortCase` — `OPEN`, stamped with the `business_date`, linked to the `drawer_id`, and carrying a copy of the signed `variance_cents`. The escalation does not stop there when the loss is severe: a case whose absolute variance reaches or exceeds twice the threshold automatically suspends the drawer's teller, moving them from `ACTIVE` to `SUSPENDED` without any human call.

The case then lives its own lifecycle under the manager: from `OPEN` to `UNDER_INVESTIGATION`, and from there to terminal `RESOLVED`. Alternatively — but only while the absolute variance is below twice the threshold — the manager may waive the case outright from either `OPEN` or `UNDER_INVESTIGATION`, moving it to terminal `WAIVED` and writing an `Approval` of `action_type` `OVER_SHORT_WAIVER`; a case at or beyond twice the threshold is too serious to waive and refuses with `ERR_WAIVER_NOT_ALLOWED`.

The drawer itself finishes the day `CLOSED`, via the manager and the drawer-version guard of §2.6. A `BALANCED` drawer closes freely. An `OUT_OF_BALANCE` drawer closes only once its over/short case — if one was created — has reached `RESOLVED` or `WAIVED`; closing earlier is refused with `ERR_OVER_SHORT_UNRESOLVED`. Close is not idempotent: a `CLOSED` drawer rejects a second close with `ERR_INVALID_STATE`. And because the drawer lifecycle is a cycle rather than a pipeline, the same teller's next business date opens a fresh `OPEN` drawer on top of the carried-forward count, exactly as §3.2 describes.

### 3.9. Audit: Scheduled Reviews and Surprise Counts

Audit operates in two tempos. A `SCHEDULED` audit is planned by an `Auditor` for a future weekday: its `scheduled_date` must be a Monday-through-Friday date strictly later than the current logical date, or creation fails with `ERR_INVALID_AUDIT_DATE` — and supplying a `scheduled_date` for a `SURPRISE` audit is the same error. A planned audit sits `PLANNED` until its date arrives; beginning it early or late is `ERR_AUDIT_NOT_DUE`, and only when the logical date equals `scheduled_date` does beginning move it to `IN_PROGRESS`. A `SURPRISE` audit skips all of this: it is created directly `IN_PROGRESS`, in the very instant of its creation.

Either way, an audit in progress freezes the branch. The branch's status becomes `AUDIT_FROZEN` — set at creation for a surprise audit, at begin for a scheduled one, with `freeze_applied` recording that the freeze took hold — and while the freeze stands, no cash may move: no postings, no buys or sells, no drawer openings, no cash-order placement or delivery, and no instrument execution all fail with `ERR_BRANCH_FROZEN`. A branch hosts at most one audit in `PLANNED` or `IN_PROGRESS` at a time; a second creation attempt meets `ERR_AUDIT_IN_PROGRESS`. A planned audit that has not begun may be cancelled, moving it to terminal `CANCELLED`; cancellation never applies a freeze.

Completion is the count. The auditor submits the physically counted `vault_counted_cents` together with `drawer_counts`, a per-drawer count for every drawer of the branch not yet `CLOSED` — any drawer in `OPEN`, `COUNTING`, `BALANCED`, or `OUT_OF_BALANCE` must appear, and a submission that omits one is `ERR_INVALID_REQUEST`. The system then computes `discrepancy_total_cents`: the counted vault minus the recorded `vault_cash_cents`, plus, for each counted drawer, the counted figure minus that drawer's `cash_balance_cents`. When the branch has no unclosed drawers, `drawer_counts` is empty and the discrepancy is the vault's alone. Reality wins: the vault and every counted drawer are adjusted to their counted figures. The freeze lifts — the branch returns to `OPEN` — and the audit becomes terminal `COMPLETED`. When the absolute discrepancy reaches or exceeds the branch's `over_short_investigation_threshold_cents` and at least one drawer was counted, an `OverShortCase` opens automatically against the earliest-created of the counted drawers (breaking any tie by `created_at` ascending), carrying `variance_cents` equal to the total discrepancy — and the severity rule of §3.8 applies to it, suspending that drawer's teller when the absolute discrepancy reaches or exceeds twice the threshold.

### 3.10. Corrections, Voids, and the Immutable Decision Record

Mistakes at the window are corrected the same day, by a second person, with the drawer still open. A `BranchManager` may void a `POSTED` transaction — but only while its drawer is still `OPEN` (a drawer already counted, balanced, or closed makes the void `ERR_INVALID_STATE`), and only when the manager's `X-User-ID` differs from the posting teller's identity, a segregation-of-duties rule whose violation is `ERR_SOD_VIOLATION`. The void stamps `voided_by_user_id` and moves the transaction to terminal `VOIDED`, then unwinds every effect the posting had. The account's balance is restored — a deposit's credit is subtracted back, a withdrawal's debit is added back, a check deposit's immediately-credited portion is subtracted back. The drawer's cash is restored in mirror image — cash that came in is subtracted, cash that went out (including any instrument face and fee) is added back — and the drawer's expected cash is recomputed with the voided transaction excluded, since only `POSTED` transactions count. The currency-transaction aggregation of §3.6 re-evaluates immediately, amending a `FILED` filing if the day's totals fall back to the threshold or below.

A voided check deposit takes its hold down with it: the hold moves to `RELEASED` but, unlike a scheduled release, credits nothing — the held funds never post, because the deposit itself is undone. Symmetrically, a check deposit whose hold has already released on schedule (or was waived and released) cannot be voided at all: the attempt is `ERR_HOLD_ALREADY_RELEASED`, because the customer may already have spent those funds.

Every sensitive decision leaves a fingerprint in the `Approval` record set: an immutable row carrying `action_type` (`TELLER_REQUEST`, `OVER_SHORT_WAIVER`, or `HOLD_WAIVER`), the subject's kind in `subject_type` (`TellerRequest`, `OverShortCase`, or `Hold`) and identity in `subject_id`, the requesting party in `requested_by_user_id` (null on waiver records, which have no requesting party), the deciding party in `approved_by_user_id`, and a terminal-at-creation `status` of `APPROVED` or `REJECTED`. Approvals are created only as side effects of the workflows above; they are never written twice and never change.

Managers and auditors read the compliance surface directly: transactions may be listed with optional `drawer_id`, `account_id`, or `branch_id` filters; holds with `account_id`, `branch_id`, or `transaction_id`; teller requests with `branch_id`, `teller_id`, or `drawer_id`; filings with `branch_id` or `account_id`; cases with `branch_id` or `drawer_id`; and audits, approvals, orders, drawers, tellers, and accounts each with their natural filters — every list following the envelope, pagination, and ordering rules of §2.3, and every filter parameter outside a list's declared set ignored.

## 4. Endpoint Definitions

All endpoints live under the `/api` mount. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation — reads, actions, transitions — returns HTTP 200. The table below names each endpoint and the roles authorized to call it; request payloads, response content, and side effects are governed by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/api/_clock/set_current_utc` | Advance the logical clock. Before any call, the logical clock reads exactly 2026-08-01T00:00:00Z (never wall-clock). Moving to a later calendar date expires PENDING TellerRequests created before that date and releases ACTIVE holds whose release day has been reached. | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/branches` | Open a branch with its cash policies | BranchManager |
| GET | `/api/branches` | List branches (paginated); default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/branches/{branchId}` | Get one branch | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/branches/{branchId}/tellers` | Hire a teller at a branch | BranchManager |
| GET | `/api/tellers` | List tellers, optionally by branch; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/tellers/{tellerId}` | Get one teller | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/tellers/{tellerId}/suspend` | Suspend a teller (blocks drawer open and transaction posting) | BranchManager |
| POST | `/api/tellers/{tellerId}/reinstate` | Reinstate a suspended teller | BranchManager |
| POST | `/api/branches/{branchId}/accounts` | Open a customer account | BranchManager, HeadTeller |
| GET | `/api/accounts` | List accounts, optionally by branch; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/accounts/{accountId}` | Get one account | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/accounts/{accountId}/close` | Close an account (zero balance, no ACTIVE holds) | BranchManager |
| POST | `/api/tellers/{tellerId}/drawers` | Open the teller's drawer session for the current logical business date; carries forward the prior CLOSED drawer's counted cash | HeadTeller, BranchManager |
| GET | `/api/drawers` | List drawers, optionally by teller or branch; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/drawers/{drawerId}` | Get one drawer | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/drawers/{drawerId}/expected-cash` | Preview expected drawer cash under a variant (STRICT default, LENIENT optional) | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/drawers/{drawerId}/buy-from-vault` | Move cash vault -> drawer; rejected if post-buy balance >= drawer limit or vault short | Teller |
| POST | `/api/drawers/{drawerId}/sell-to-vault` | Move cash drawer -> vault; requires pre-sell balance >= limit and post-sell balance < limit | Teller |
| POST | `/api/drawers/{drawerId}/count` | Teller attests the physical count; drawer moves OPEN -> COUNTING | Teller |
| POST | `/api/drawers/{drawerId}/attest` | Second-person verification of the count (dual control); COUNTING -> BALANCED or OUT_OF_BALANCE | BranchManager, Auditor |
| POST | `/api/drawers/{drawerId}/close` | Close a BALANCED or OUT_OF_BALANCE drawer (OCC-guarded) | BranchManager |
| POST | `/api/drawers/{drawerId}/transactions` | Post a teller transaction (CASH_DEPOSIT, CASH_WITHDRAWAL, CHECK_DEPOSIT only; instruments require an approved TellerRequest) | Teller |
| GET | `/api/transactions` | List transactions, optionally by drawer, account, or branch; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/transactions/{transactionId}` | Get one transaction | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/transactions/{transactionId}/void` | Void a POSTED transaction (same-day correction; manager other than the posting teller) | BranchManager |
| POST | `/api/branches/{branchId}/cash-orders` | Place a cash order for a future business day; forecast, step-rounding and capacity clamp applied (OCC-guarded) | Teller, HeadTeller |
| GET | `/api/cash-orders` | List cash orders, optionally by branch; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/cash-orders/{orderId}` | Get one cash order | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/branches/{branchId}/cash-forecast` | Forecast preview for a target delivery date: TRAILING projected need, WEIGHTED comparison, and suggested order | BranchManager, HeadTeller, Teller |
| POST | `/api/cash-orders/{orderId}/approve` | Approve a PENDING cash order (manager other than the ordering teller) | BranchManager |
| POST | `/api/cash-orders/{orderId}/reject` | Reject a PENDING cash order (manager other than the ordering teller) | BranchManager |
| POST | `/api/cash-orders/{orderId}/deliver` | Receive the shipment on its delivery date; vault credited | HeadTeller |
| POST | `/api/cash-orders/{orderId}/cancel` | Cancel an APPROVED-but-undelivered order | BranchManager |
| POST | `/api/drawers/{drawerId}/teller-requests` | Teller creates a dual-control request (ISSUE_INSTRUMENT, FEE_WAIVER, OVER_LIMIT_TRANSACTION) against their own OPEN drawer | Teller |
| GET | `/api/teller-requests` | List teller requests, optionally by branch, teller, or drawer; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/teller-requests/{requestId}` | Get one teller request | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/teller-requests/{requestId}/approve` | Approve and atomically execute a PENDING request (approver != requester) | HeadTeller, BranchManager |
| POST | `/api/teller-requests/{requestId}/reject` | Reject a PENDING request (rejector != requester) | HeadTeller, BranchManager |
| GET | `/api/holds` | List holds, optionally by account, branch, or transaction; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Teller, Auditor |
| GET | `/api/holds/{holdId}` | Get one hold | BranchManager, HeadTeller, Teller, Auditor |
| POST | `/api/holds/{holdId}/waive` | Waive an ACTIVE hold to the shortened 1-business-day schedule | BranchManager |
| GET | `/api/ctr-filings` | List CTR filings, optionally by branch or account; default order created_at ASC, stable and deterministic | BranchManager, HeadTeller, Auditor |
| GET | `/api/ctr-filings/{filingId}` | Get one CTR filing | BranchManager, HeadTeller, Auditor |
| GET | `/api/over-short-cases` | List over/short cases, optionally by branch or drawer; default order created_at ASC, stable and deterministic | BranchManager, Auditor |
| GET | `/api/over-short-cases/{caseId}` | Get one over/short case | BranchManager, Auditor |
| POST | `/api/over-short-cases/{caseId}/investigate` | Move an OPEN case to UNDER_INVESTIGATION | BranchManager |
| POST | `/api/over-short-cases/{caseId}/resolve` | Resolve an UNDER_INVESTIGATION case | BranchManager |
| POST | `/api/over-short-cases/{caseId}/waive` | Waive a case whose |variance| is under twice the investigation threshold | BranchManager |
| GET | `/api/approvals` | List approval records, optionally by branch; default order created_at ASC, stable and deterministic | BranchManager, Auditor |
| GET | `/api/approvals/{approvalId}` | Get one approval record | BranchManager, Auditor |
| POST | `/api/branches/{branchId}/audits` | Schedule an audit (SCHEDULED for a future business day) or launch a SURPRISE audit (created IN_PROGRESS, freezes the branch immediately) | Auditor |
| GET | `/api/audits` | List audit sessions, optionally by branch; default order created_at ASC, stable and deterministic | BranchManager, Auditor |
| GET | `/api/audits/{auditId}` | Get one audit session | BranchManager, Auditor |
| POST | `/api/audits/{auditId}/begin` | Begin a SCHEDULED audit on its scheduled date (freezes the branch) | Auditor |
| POST | `/api/audits/{auditId}/complete` | Complete an IN_PROGRESS audit with vault and drawer counts; adjusts balances, lifts the freeze, may open an OverShortCase | Auditor |
| POST | `/api/audits/{auditId}/cancel` | Cancel a PLANNED (not yet begun) audit | Auditor |

## 5. Error Code Catalogue

Every error response carries one of the identifiers below with the listed HTTP status. The conditions that trigger each error are specified in the workflows of §2 and §3.

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_CLOSED` | 409 |
| `ERR_ACCOUNT_NOT_SETTLED` | 409 |
| `ERR_OVER_SHORT_UNRESOLVED` | 409 |
| `ERR_HOLD_ALREADY_RELEASED` | 409 |
| `ERR_BRANCH_FROZEN` | 409 |
| `ERR_DUAL_CONTROL_VIOLATION` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_TELLER_SUSPENDED` | 409 |
| `ERR_INSTRUMENT_REQUIRES_APPROVAL` | 409 |
| `ERR_DRAWER_ALREADY_OPEN` | 409 |
| `ERR_DUPLICATE_CASH_ORDER` | 409 |
| `ERR_AUDIT_IN_PROGRESS` | 409 |
| `ERR_WAIVER_NOT_ALLOWED` | 422 |
| `ERR_INVALID_DELIVERY_DATE` | 422 |
| `ERR_ORDER_NOT_DUE` | 409 |
| `ERR_INVALID_AUDIT_DATE` | 422 |
| `ERR_AUDIT_NOT_DUE` | 409 |
| `ERR_CLOCK_REGRESSION` | 422 |
| `ERR_CROSS_BRANCH` | 422 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_INSUFFICIENT_DRAWER_CASH` | 422 |
| `ERR_INSUFFICIENT_FUNDS` | 422 |
| `ERR_TRANSACTION_OVER_LIMIT` | 422 |
| `ERR_DRAWER_LIMIT` | 422 |
| `ERR_INSUFFICIENT_VAULT_CASH` | 422 |
| `ERR_INSTRUMENT_LIMIT` | 422 |
| `ERR_ORDER_BELOW_MINIMUM` | 422 |
| `ERR_VAULT_CAPACITY_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
