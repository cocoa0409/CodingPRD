# Corporate Card & Spend Management API — Product Requirements Document

## 1. Introduction

Modern finance teams issue corporate cards the way engineering teams provision cloud resources: instantly, at scale, and with policy guardrails baked in. The Corporate Card & Spend Management API is the system of record behind that experience. It governs the full arc of corporate spend — issuing virtual and physical cards against a shared corporate credit line, enforcing per-merchant and per-policy controls at the moment of authorization, capturing transactions and matching them to receipts, routing high-value spend through an approval workflow, reimbursing employees for out-of-pocket expenses, and closing the books each cycle through statements, repayments, and an export to the general ledger.

The core difficulty the platform solves is reconciliation under two simultaneously moving dimensions. Every transaction tracks money (authorization) and compliance (review) on independent timelines: a charge can settle into a statement before anyone has reviewed it, and it can be receipt-matched while the funds are still merely held. Layered on top is a conserved-quantity credit pool that must stay exact across authorizations, settlements, reversals, statement closes, and repayments — a single arithmetic drift corrupts every downstream spending decision. The API is built around four actor types whose duties are deliberately segregated: cardholders who spend, approvers who decide (but never on their own spend), finance administrators who run the money machinery, and auditors who observe everything and change nothing.

This document specifies the complete contract: the resource model, the two-dimensional and revision-cycle state machines, the dual-variant billing and reward calculations, the validation and precedence rules, and the role-based authorization matrix that ties them together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`. The same `ERR_FORBIDDEN_FOR_ROLE` is returned when an operation requires the caller to be the resource owner and the caller is not.

The system recognizes exactly four roles, spelled here exactly as they must appear in the `X-User-Role` header: `FinanceAdmin`, `Approver`, `CardholderEmployee`, and `Auditor`.

Three of these roles are backed by an `Employee` record, and this binding is what makes ownership and segregation-of-duties checks meaningful. When `X-User-Role` is `FinanceAdmin`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's relevant employee foreign-key field to `X-User-ID`. When `X-User-Role` is `Approver`, `X-User-ID` is the `id` of the acting `Employee`; this is the identity compared against a transaction's cardholder, an approval request's `requester_employee_id`, or a claim's `employee_id` whenever a segregation-of-duties rule forbids deciding on one's own spend. When `X-User-Role` is `CardholderEmployee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks for resubmitting an approval request, or for submitting, revising, and submitting a reimbursement claim, compare the resource's owning employee field to `X-User-ID`. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`; the `Auditor` role is read-only and may invoke only the listing and retrieval (GET) endpoints across all resources.

Note that the business role recorded on an employee — the `employee_role` field, whose value is one of `CARDHOLDER`, `APPROVER`, or `FINANCE_ADMIN` — is distinct from the `X-User-Role` header. The header governs request authorization; `employee_role` is an attribute of the employee record used for organizational modeling.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order, so the earliest-created resource appears first.

Every list response includes these four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Identification

Almost every resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) recorded when the resource is first created. `updated_at` is the ISO 8601 UTC timestamp of the most recent modification. `version` is an integer that begins at its initial value of 1 on creation and increments by exactly one on every mutation of the resource, including mutations of derived fields and automatic state transitions performed by the server.

One entity is the exception: a `Receipt` is immutable once created and therefore carries only `id` and `created_at`. A `Receipt` has no `updated_at` field and no `version` field.

Resources are addressed by their own identifiers; the API uses a flat collection topology, so parent–child relationships are carried by foreign-key fields in the request and response bodies rather than by nesting in the URL. The exceptions are the handful of endpoints whose path embeds a parent identifier — capturing or listing transactions and receipts under a card or transaction, opening an approval request under a transaction, and reading a statement's cashback summary. For any such path that embeds more than one identifier, the system validates them left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve. When a request body references resources, the company is resolved before any child resource that also appears in the body. A reference to a non-existent company or child resource yields `ERR_NOT_FOUND`.

### 2.5. Monetary Precision and Reward Rounding

All monetary quantities in the system are stored and transmitted as integer cents; there are no fractional cents and no floating-point representation of money in API bodies. Aggregations that sum integer-cent values — closing balances, repayment allocations, available credit, and the per-line cashback total — therefore require no rounding, because all inputs are already whole cents.

Two computations do involve a fraction and must round deterministically. When a reward (cashback) figure is derived from a basis-point rate, the raw product is rounded half up to whole cents before any cap is applied. When the minimum payment is derived as a fraction of a closing balance, the raw fractional cents are rounded up to the next whole cent (ceiling) before the floor-and-cap logic runs. These two roundings differ on purpose: rewards round half up, the minimum-payment fraction rounds up.

### 2.6. The Conserved Credit Pool

Each company exposes a derived field, `available_credit_cents`, that the system reconciles on every mutation that can affect it: every transaction authorization, clear, settle, and reverse; every statement close; and every repayment clear and reverse. It is never stored as a free-running counter — it is recomputed from first principles so it can never drift.

The value is the company's `credit_limit_cents` minus two subtractions. The first subtraction is open authorization holds: the sum of `amount_cents` over every transaction of the company whose `auth_status` is either `PENDING` or `CLEARED`. The second subtraction is posted-but-unpaid statement balances: for every statement of the company in status `CLOSED`, `DUE`, or `PAST_DUE`, the difference between its `closing_balance_cents` and its `amount_repaid_cents`, summed across those statements. In words, `available_credit_cents` is the credit limit, less everything currently held against open authorizations, less everything posted to statements that has not yet been repaid.

Several invariants follow directly and must hold exactly. When a transaction settles, its hold leaves the first subtraction (the hold is released) but its settled amount joins a statement balance only once that statement closes — so settlement alone moves the amount out of open holds and into the company's posted exposure pathway. When a transaction is reversed, its hold leaves the first subtraction and `available_credit_cents` returns to its pre-authorization value. When a repayment clears, the unpaid portion of its statement shrinks and `available_credit_cents` rises by the repaid amount; when that repayment is reversed, the unpaid portion grows back and `available_credit_cents` falls by the same amount. The note on `card_limit_cents` below is independent of this pool: per-card ceilings may sum to more than `credit_limit_cents` (oversubscription is allowed), and the company pool is the backstop.

### 2.7. Hierarchical Consistency and Cascading Reconciliation

Many operations mutate more than one resource. Whenever an operation changes a derived field on a parent — `held_cents` on a card, `available_credit_cents` on a company, `amount_repaid_cents` on a statement, or the running balances on the reward account — that parent's `updated_at` is refreshed and its `version` increments as part of the same operation. The card's `held_cents` is itself a derived field: it is the sum of `amount_cents` over the card's transactions whose `auth_status` is `PENDING` or `CLEARED`, reconciled on every transaction transition. The system may also transition a parent automatically when a child's change satisfies or violates the parent's criteria — for example, a statement moving to `PAID` when a clearing repayment lifts its repaid total to the minimum due, or reverting from `PAID` to `DUE` when a reversal drops it back below. Each such automatic transition is a real mutation that increments the affected resource's `version`.

### 2.8. Optimistic Concurrency on Repayment Creation

Creating a repayment is the one write in the system guarded by optimistic concurrency control, because a statement's payable state changes as earlier repayments clear or reverse. A request to create a repayment must include `expected_statement_version`, carrying the `version` of the target statement that the client last observed. If that value does not equal the statement's current `version` — which happens when another writer has cleared or reversed a repayment and thereby advanced the statement's `version` and changed its `amount_repaid_cents` or `status` since the client read it — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412. This prevents a client from creating a repayment against a stale view of how much remains due. No other endpoint accepts or requires a version field in its body.

### 2.9. Merchant-Category, Limit, and Credit Gating at Authorization

Capturing a transaction is the system's most heavily gated operation, and its checks run in a fixed precedence so that the most specific business reason for a rejection always wins. After the universal header, role, existence, and body-shape checks (described in §2.10), and after the amount-positivity check, the capture pipeline evaluates, in this order: first, the merchant-category control — if the transaction's `mcc_code` is among the card's spend policy's `blocked_mcc_codes`, the capture is rejected with `ERR_MCC_BLOCKED`; second, card state — the card must be `ACTIVE`, so a `REQUESTED` physical card, a `FROZEN` card, or a `TERMINATED` card is rejected with `ERR_CARD_NOT_ACTIVE`; third, the per-transaction policy ceiling — if `amount_cents` exceeds the policy's `per_transaction_limit_cents`, the capture is rejected with `ERR_PER_TXN_LIMIT_EXCEEDED`; fourth, the card's remaining headroom — if `amount_cents` exceeds `card_limit_cents` minus the card's current `held_cents`, the capture is rejected with `ERR_CARD_LIMIT_EXCEEDED`; and fifth, the company credit pool — if `amount_cents` exceeds the company's `available_credit_cents`, the capture is rejected with `ERR_INSUFFICIENT_CREDIT` and HTTP status 402. This ordering means, for example, that a blocked merchant category is reported even when the card is also frozen, and a frozen card is reported before any limit arithmetic is attempted.

### 2.10. Validation Precedence

When several validations could apply to one request, they are evaluated in a fixed priority order so the returned error is deterministic. The order is: (1) the user-context header check, `ERR_MISSING_USER_CONTEXT`; (2) the role-permission check, `ERR_FORBIDDEN_FOR_ROLE`; (3) existence of all referenced resources, `ERR_NOT_FOUND`, resolving the company before any child that also appears in the body; (4) body well-formedness — required fields present and enum values valid — `ERR_VALIDATION`; (5) monetary positivity, `ERR_INVALID_AMOUNT`; then the domain-specific checks at lower priority. Among the capture-only gates the order is merchant block, card-active, per-transaction limit, card headroom, then company credit, as detailed in §2.9. The generic state check, `ERR_INVALID_STATE`, applies to every transition endpoint and fires when the target resource is not in a state from which the requested transition is defined. Endpoint-specific gates (GL coding, approval gate, receipt gate, segregation of duties, the OCC version check, company suspension, clock-not-set, and the two authorization-window checks) are described in §3 alongside the workflows they guard, and they take effect after the generic state check has confirmed the transition is structurally legal.

Monetary positivity deserves emphasis: every monetary amount supplied by a client must be strictly greater than zero. This covers a transaction's `amount_cents`, the `settled_amount_cents` supplied at settle, a receipt's `amount_cents`, a repayment's `amount_cents`, a reimbursement claim's `amount_cents` and `receipt_amount_cents`, a spend authorization's `budget_cents`, and the redemption `amount_cents`. A non-positive value, or a `settled_amount_cents` greater than the transaction's authorized `amount_cents`, is rejected with `ERR_INVALID_AMOUNT` (HTTP 422). A spend authorization whose `window_end` is not strictly after its `window_start` is likewise rejected with `ERR_INVALID_AMOUNT`.

### 2.11. The Simulated Company Clock

Time in this system is explicit, not wall-clock. Each company carries a `clock_utc` field that is null until set and is advanced only through the administrative clock-setting capability, which accepts a `company_id` and a `to_iso8601` instant and assigns `clock_utc` to that instant. Statement due dates and the past-due evaluation both read this clock; a statement cannot be closed until the clock is set. Advancing the clock also triggers an automatic past-due sweep, described in §3.6.

## 3. Business Logic & Workflows

### 3.1. Company Setup and the Org Graph

A `FinanceAdmin` brings a company into existence by supplying its `legal_name`, its `credit_limit_cents` (the corporate charge-card ceiling shared across all its cards), and its `billing_model`, which is one of `CHARGE` (the full closing balance is due each cycle) or `CREDIT` (revolving, with a minimum payment). Optionally the request may set `currency` (defaulting to `USD`), `minimum_payment_pct` (the fraction of a closing balance that becomes the minimum payment under the `CREDIT` model, defaulting to 0.10 and ignored under `CHARGE`), and `reward_rate_default_bps` (the default cashback rate in basis points, where 100 basis points equal one percent, defaulting to 100, used for any merchant category that has no override). A newly created company starts in `status` `ACTIVE`, with `available_credit_cents` equal to its `credit_limit_cents` and `clock_utc` null. Two cascades fire at creation: a `RewardAccount` is created for the company with all balances at zero, and the company's first statement is opened with `cycle_index` 1 (its `opened_at` remaining null until the clock is first set).

A company can be moved to `status` `SUSPENDED` through a suspend capability that optionally records a `reason`; suspension increments the company's `version`. A suspended company blocks three money-forward operations — card activation, card unfreeze, and transaction settlement — each of which is rejected with `ERR_COMPANY_SUSPENDED` while the company is not `ACTIVE`.

Around the company the administrator builds the supporting graph. A spend policy is created with a `company_id`, a `name`, a `per_transaction_limit_cents`, an `approval_threshold_cents` (transactions whose amount exceeds this require an approval request before review can reach approval), an optional `blocked_mcc_codes` list of four-digit Merchant Category Code strings (defaulting to empty), and an optional `mcc_reward_overrides` list, each entry pairing an `mcc_code` with a `reward_rate_bps` category cashback override (defaulting to empty); a policy starts `ACTIVE` and may later be `ARCHIVED`. Employees are created with a `company_id`, an `email`, a `full_name`, an `employee_role` (`CARDHOLDER`, `APPROVER`, or `FINANCE_ADMIN`), and an optional `manager_employee_id` referencing the employee who approves this person's spend (a self-reference to another employee; null for a finance administrator); an employee's `email` must be unique among the company's `ACTIVE` employees, and a reused email is rejected with `ERR_DUPLICATE_EMAIL`. An employee starts `ACTIVE` and may become `DEACTIVATED`. GL accounts are created with a `company_id`, a `gl_code`, and a `name`; the `gl_code` must be unique among the company's `ACTIVE` GL accounts, and a duplicate is rejected with `ERR_DUPLICATE_GL_CODE`. A GL account starts `ACTIVE` and may become `ARCHIVED`.

### 3.2. Card Issuance and Lifecycle

A `FinanceAdmin` issues a card against a `company_id`, an `employee_id` (the cardholder), a `spend_policy_id` (the policy that governs its limits and merchant blocks), a `form_factor` of `VIRTUAL` or `PHYSICAL`, and a `card_limit_cents` per-card ceiling. If any of the referenced company, employee, or policy is absent the issuance fails with `ERR_NOT_FOUND`. A virtual card is born ready to spend, in `status` `ACTIVE`; a physical card is born in `status` `REQUESTED` and must be activated before it can be used. Every new card starts with `held_cents` at zero.

The card lifecycle is a small state machine driven entirely by the administrator. Activating a physical card moves it `REQUESTED → ACTIVE`; this is defined only for a physical card (a virtual card is already `ACTIVE`, and attempting to activate one is rejected with `ERR_INVALID_STATE`) and is blocked while the company is suspended with `ERR_COMPANY_SUSPENDED`. Freezing an `ACTIVE` card moves it `ACTIVE → FROZEN`; if the card is not `ACTIVE` the freeze is rejected with `ERR_INVALID_STATE`. Unfreezing moves a card `FROZEN → ACTIVE`; it is defined only from `FROZEN` (otherwise `ERR_INVALID_STATE`) and is blocked while the company is suspended with `ERR_COMPANY_SUSPENDED`. The freeze/unfreeze pair may cycle any number of times. Terminating a card moves it to `TERMINATED` from either `ACTIVE` or `FROZEN` (any other starting state yields `ERR_INVALID_STATE`); termination is refused with `ERR_CARD_HAS_OPEN_AUTH` if the card still has any transaction whose `auth_status` is `PENDING`. `TERMINATED` is the terminal state. Each of these transitions increments the card's `version`.

### 3.3. Spending: The Two-Dimensional Transaction

A transaction is the heart of the system, and it advances along two completely independent dimensions. The authorization dimension, `auth_status`, tracks the money through `PENDING → CLEARED → SETTLED`, with a reversal branch to `REVERSED` reachable from either `PENDING` or `CLEARED`. The compliance dimension, `review_status`, tracks the paperwork through `UNREVIEWED → NEEDS_RECEIPT → MATCHED → APPROVED`, with a `FLAGGED` branch. The two dimensions do not wait for each other: a transaction may be `SETTLED` while still `UNREVIEWED`, or `MATCHED` while still `PENDING`.

A `CardholderEmployee` (or a `FinanceAdmin` acting on their behalf) captures a transaction on a specific card by supplying a `merchant_name`, an `mcc_code` (a four-digit Merchant Category Code), an `amount_cents` (the authorized amount, which must be positive), and optionally a `gl_account_id` for early GL coding. The capture runs the merchant, card-state, and limit gates in the precedence given in §2.9. On success the transaction is created with `auth_status` `PENDING`, its `company_id` copied from the card, its `statement_id` null for now, its `settled_amount_cents` null and its `reward_points_cents` 0 until settle, and a hold placed: the card's `held_cents` and the company's `available_credit_cents` are recomputed to reflect the new authorization. The compliance dimension is set at birth based on size: if `amount_cents` is greater than the receipt-required threshold of seventy-five dollars (7,500 cents), the transaction starts `review_status` `NEEDS_RECEIPT`; otherwise it starts `UNREVIEWED`.

The authorization dimension is advanced by a `FinanceAdmin`. Clearing moves `auth_status` `PENDING → CLEARED` (defined only from `PENDING`, else `ERR_INVALID_STATE`); the hold remains counted in both `held_cents` and `available_credit_cents`, because cleared money is still held, not yet posted. Settling moves `auth_status` `CLEARED → SETTLED` (defined only from `CLEARED`, else `ERR_INVALID_STATE`) and is the richest transition in the system. The settle request supplies `settled_amount_cents`, the final cleared amount, which must be greater than zero and no greater than the authorized `amount_cents` (a partial capture is allowed; a value outside that range yields `ERR_INVALID_AMOUNT`). Settling is refused with `ERR_COMPANY_SUSPENDED` when the company is not `ACTIVE`. On success: `settled_amount_cents` is recorded; the transaction's `statement_id` is set to the company's currently `OPEN` statement (one always exists, since a fresh one is opened at company creation and again on every close); the hold of `amount_cents` is released from `held_cents`, which in turn lowers the open-holds component and triggers recomputation of `available_credit_cents`; the transaction's `reward_points_cents` is computed by the reward rule (§3.4) and that same amount is added to the reward account's `accrued_points_cents` and `balance_points_cents`; and the transaction's `version` increments.

Reversal is the compensating branch. Reversing a transaction from `PENDING` or `CLEARED` moves `auth_status` to `REVERSED` (any other state yields `ERR_INVALID_STATE`). The reversal drops the card's `held_cents` by `amount_cents` and raises the company's `available_credit_cents` by the same `amount_cents`, so the credit pool returns exactly to its pre-authorization value. A reversal also nets the transaction's accrued reward back out of the reward account, keeping `accrued_points_cents` and `balance_points_cents` consistent with the surviving settled spend. The transaction's `version` increments. `SETTLED` and `REVERSED` are the terminal authorization states.

### 3.4. Receipt Matching, GL Coding, and Reward Accrual

A receipt drives the compliance dimension forward. A `CardholderEmployee` (or `FinanceAdmin`) uploads a receipt against a transaction by supplying the receipt's `amount_cents` and `merchant_name`; the system copies the `company_id` and `transaction_id` onto the receipt and computes its `match_result`. The result is `MATCH` when the absolute difference between the receipt's `amount_cents` and the transaction's `amount_cents` is at most the match tolerance of one dollar (100 cents), and `MISMATCH` otherwise. On a `MATCH`, the transaction advances along the compliance dimension to `MATCHED` and its `version` increments: from `NEEDS_RECEIPT → MATCHED` for a transaction that required a receipt, or directly `UNREVIEWED → MATCHED` for a small transaction (one whose `amount_cents` did not exceed the receipt-required threshold) that had skipped `NEEDS_RECEIPT`. On a `MISMATCH`, the receipt is still recorded with `match_result` `MISMATCH`, but the transaction's `review_status` is left unchanged. A receipt is immutable and carries no `version`.

GL coding can happen at capture or later. A `CardholderEmployee` or `FinanceAdmin` may assign or change a transaction's `gl_account_id` through a coding operation; the referenced GL account must be `ACTIVE` or the change is rejected with `ERR_GL_CODE_REQUIRED`. A successful coding sets `gl_account_id` and increments the transaction's `version`.

The reward (cashback) figure for a transaction is computed at settle and accrues on the net basis — that is, on `settled_amount_cents`, the amount that actually cleared, not on the authorized `amount_cents`, so a partial capture earns less than a full one would. The rate is selected per merchant category: if the transaction's `mcc_code` appears as an `mcc_code` key among the card's spend policy's `mcc_reward_overrides`, that override's `reward_rate_bps` is used; otherwise the company's `reward_rate_default_bps` applies. The raw reward is the settled amount multiplied by the selected rate in basis points, divided by ten thousand, rounded half up to whole cents. The stored `reward_points_cents` is then the lesser of that rounded raw reward and the per-transaction cashback cap of fifty dollars (5,000 cents) — the cap is applied after rounding.

A statement's cashback summary is a computed read returning the statement's `statement_id`, a `statement_cashback_cents` total, and a `settled_transaction_count`. The total is the sum of `reward_points_cents` over the transactions whose `statement_id` is this statement and whose `auth_status` is `SETTLED`. The order is fixed and matters: each transaction's reward was already rounded half up at settle, and the summary sums those already-rounded per-transaction values — it does not re-sum raw products and round once at the end.

### 3.5. The Approval Workflow

High-value spend must clear a human approval gate before its compliance review can be finalized. A `CardholderEmployee` or `FinanceAdmin` opens an approval request against a transaction; the request is created in `status` `PENDING`, its `requester_employee_id` set to the cardholder employee of the transaction's card, its `company_id` copied from the transaction, and its `revision_count` at zero. An approval request is only meaningful for a transaction whose `amount_cents` exceeds the governing policy's `approval_threshold_cents`; opening one for a transaction at or below that threshold is rejected with `ERR_APPROVAL_NOT_NEEDED`.

An `Approver` decides the request. Approving moves it `PENDING → APPROVED` and records the deciding approver in `approver_employee_id` (set to the approver's `X-User-ID`), optionally storing a `decision_note`; the request's `version` increments. Approval is defined only from `PENDING` (else `ERR_INVALID_STATE`), is forbidden when the approver's `X-User-ID` equals the `requester_employee_id` (segregation of duties, `ERR_SELF_APPROVAL`), and is refused with `ERR_INVALID_STATE` when the underlying transaction has been reversed (a reversed transaction's `auth_status` is `REVERSED`). Rejecting moves the request `PENDING → REJECTED`, also recording `approver_employee_id` and any `decision_note` and incrementing `version`; it too is defined only from `PENDING` and forbidden for the requester themselves under `ERR_SELF_APPROVAL`. A rejected request is not dead: the original requester may resubmit it, moving it `REJECTED → PENDING`, which increases `revision_count` by one and clears `approver_employee_id` back to null. Resubmission is defined only from `REJECTED` (else `ERR_INVALID_STATE`) and is permitted only when `X-User-ID` equals the `requester_employee_id`, otherwise `ERR_FORBIDDEN_FOR_ROLE`. `APPROVED` is the terminal state.

The approval gate connects back to the transaction at review time. An `Approver` advances a transaction's compliance dimension `MATCHED → APPROVED`, but only when four conditions hold, evaluated against the transaction in question. First, the review must currently be `MATCHED`; if it is still `NEEDS_RECEIPT` or `UNREVIEWED`, approval is blocked with `ERR_RECEIPT_REQUIRED`. Second, the transaction's `gl_account_id` must be set and reference an `ACTIVE` GL account, else `ERR_GL_CODE_REQUIRED`. Third, if the transaction's `amount_cents` exceeds the policy's `approval_threshold_cents`, there must exist an approval request for this transaction in `status` `APPROVED`, else `ERR_APPROVAL_REQUIRED`. Fourth, the approving `X-User-ID` must not be the cardholder employee of the transaction's card, else `ERR_SELF_APPROVAL`. On success the review moves to `APPROVED` and the transaction's `version` increments. Separately, an `Approver` may flag a transaction, moving its review to `FLAGGED` from either `MATCHED` or `NEEDS_RECEIPT`, optionally with a `note`; flagging is likewise forbidden when the approver is the cardholder (`ERR_SELF_APPROVAL`) and increments the transaction's `version`.

### 3.6. Statements, the Billing Cycle, and Repayment

A company always has exactly one `OPEN` statement accumulating its settled spend. A `FinanceAdmin` closes the open statement to draw a line under the cycle; closing requires the company's `clock_utc` to be set, otherwise `ERR_CLOCK_NOT_SET`, and is defined only from `OPEN`, otherwise `ERR_INVALID_STATE`. On close, `closed_at` is set to the company's `clock_utc`, `due_at` is set to twenty-one days after `closed_at`, the `closing_balance_cents` is computed per the billing model (below), and `minimum_due_cents` is computed immediately afterward. Closing then cascades: the company's `available_credit_cents` is recomputed (the new closing balance now counts as posted-unpaid exposure), and a fresh `OPEN` statement is created for the company with the next `cycle_index` (the per-company cycle counter is monotonic and starts at 1). The closed statement's `version` increments.

The closing balance is a dual-variant calculation over the same candidate transactions, and the two variants genuinely differ. Reversed transactions are excluded under both. Under the accrual variant, which applies when the company's `billing_model` is `CHARGE`, the closing balance is the sum of `settled_amount_cents` over every `SETTLED` transaction assigned to this statement, plus the sum of `amount_cents` over every transaction of the company that is `CLEARED` but not yet `SETTLED` at the moment of close; and as part of close, the accrual variant assigns those swept cleared transactions' `statement_id` to this statement. Under the cash variant, which applies when the `billing_model` is `CREDIT`, only `SETTLED` transactions assigned to this statement are included — the closing balance is the sum of their `settled_amount_cents`, and cleared-but-unsettled spend does not post this cycle. The two variants produce different closing balances whenever any cleared-but-unsettled transaction exists at close.

The minimum due reads the closing balance that was just computed (evaluation order is fixed: balance first, then minimum). Under the `CHARGE` model the minimum due equals the full `closing_balance_cents`. Under the `CREDIT` model: if the closing balance is zero, the minimum due is zero; if the closing balance is at most the minimum-payment floor of twenty-five dollars (2,500 cents), the minimum due equals the whole closing balance; otherwise the raw minimum is the closing balance multiplied by the company's `minimum_payment_pct`, rounded up to whole cents, and the minimum due is the greater of that raw figure and the minimum-payment floor.

After closing, the administrator issues the statement, moving it `CLOSED → DUE` (defined only from `CLOSED`, else `ERR_INVALID_STATE`) and incrementing its `version`; issuing represents handing the invoice to the company. A `DUE` statement settles its debt through repayments. A statement may also slip past due: when the clock is advanced and a `DUE` statement's `due_at` is now earlier than the new `clock_utc` while its `amount_repaid_cents` is still below its `minimum_due_cents`, the system automatically transitions that statement `DUE → PAST_DUE` and increments its `version`. The terminal happy state is `PAID`, reached automatically when repayments bring the repaid total up to the minimum due, as described next.

Repayment is OCC-guarded and has its own lifecycle. A `FinanceAdmin` creates a repayment against a `statement_id`, supplying an `amount_cents` (positive) and the `expected_statement_version` described in §2.8; the target statement must be in `DUE` or `PAST_DUE` (else `ERR_INVALID_STATE`), and a stale version yields `ERR_STALE_VERSION` (412). A new repayment starts `INITIATED`. Clearing it moves `INITIATED → CLEARED` and cascades: the statement's `amount_repaid_cents` increases by the repayment's `amount_cents`; because that changed, the company's `available_credit_cents` increases by the same amount (the posted-unpaid component shrinks); and if the statement's `amount_repaid_cents` has reached or exceeded its `minimum_due_cents`, the statement (whether `DUE` or `PAST_DUE`) transitions to `PAID`. Both the repayment's `version` and the statement's `version` increment. Failing an `INITIATED` repayment moves it to `FAILED` with no ledger effect. Reversing a `CLEARED` repayment moves it to `REVERSED` and runs the compensating cascade: the statement's `amount_repaid_cents` decreases by `amount_cents`, the company's `available_credit_cents` decreases by the same amount, and if the statement had been `PAID` and its `amount_repaid_cents` now falls below `minimum_due_cents`, the statement reverts `PAID → DUE`. Both versions increment. `FAILED` and `REVERSED` are terminal for a repayment; clearing is defined only from `INITIATED`, failing only from `INITIATED`, and reversing only from `CLEARED` (each otherwise `ERR_INVALID_STATE`).

### 3.7. Out-of-Pocket Reimbursement

Employees who spend their own money file reimbursement claims. A `CardholderEmployee` or `FinanceAdmin` creates a claim with a `company_id`, an `employee_id` (the claimant), a `gl_account_id` for coding, a `merchant_name`, an `amount_cents` claimed (positive), and a `receipt_amount_cents` (the amount on the attached receipt, which caps the payout). A new claim is `DRAFT` with `reimbursable_cents` at zero. The claim runs a revision cycle: the claimant submits it `DRAFT → SUBMITTED` (defined only from `DRAFT`, and permitted only when `X-User-ID` equals the claim's `employee_id`, else `ERR_FORBIDDEN_FOR_ROLE`).

An `Approver` decides a submitted claim. Approving moves it `SUBMITTED → APPROVED`; it is defined only from `SUBMITTED` (else `ERR_INVALID_STATE`), forbidden when the approver's `X-User-ID` equals the claimant's `employee_id` (`ERR_SELF_APPROVAL`), and requires the claim's referenced `gl_account_id` to be `ACTIVE` (else `ERR_GL_CODE_REQUIRED`). On approval the payout `reimbursable_cents` is computed as the least of the claimed `amount_cents`, the `receipt_amount_cents`, and the per-claim reimbursement cap of two thousand dollars (200,000 cents); the claim's `version` increments. Rejecting a submitted claim moves it `SUBMITTED → REJECTED` (same state and self-approval guards) and increments `version`. A rejected claim returns to `DRAFT` through a revise action (defined only from `REJECTED`, permitted only to the claimant by `X-User-ID` matching `employee_id`, else `ERR_FORBIDDEN_FOR_ROLE`) for editing and re-submission. Finally a `FinanceAdmin` pays an approved claim, moving it `APPROVED → PAID` (defined only from `APPROVED`); payment cascades a reward into the company's reward account, increasing both `accrued_points_cents` and `balance_points_cents` by the claim's `reimbursable_cents` multiplied by the company's `reward_rate_default_bps`, divided by ten thousand, rounded half up to whole cents (the per-transaction cashback cap of §3.4 does not apply to this reimbursement reward). The claim's `version` increments. `PAID` is terminal.

### 3.8. Rewards Ledger and Redemption

Each company has exactly one reward account, created with the company. It is a derived ledger: `accrued_points_cents` is the lifetime cashback accrued from settled transactions and paid reimbursements, net of transaction reversals; `redeemed_points_cents` is the total redeemed; and `balance_points_cents` is `accrued_points_cents` minus `redeemed_points_cents`. A `FinanceAdmin` redeems cashback by supplying an `amount_cents` to redeem (positive); the redemption increases `redeemed_points_cents` by that amount and recomputes `balance_points_cents`, incrementing the account's `version`. A redemption greater than the current `balance_points_cents` is rejected with `ERR_INSUFFICIENT_REWARD_BALANCE`.

### 3.9. Pre-Authorized Spend Budgets

A `FinanceAdmin` or `Approver` may pre-authorize a budget over a time window. A spend authorization is created with a `company_id`, a `scope` of `EMPLOYEE` or `CARD`, an `employee_id` (always required), an optional `card_id` (required when `scope` is `CARD`, null when `scope` is `EMPLOYEE`), a `budget_cents` (positive), and a half-open window from `window_start` (inclusive) to `window_end` (exclusive). The authorization is created `ACTIVE`. The two scopes use deliberately different interval rules, and the distinction is the whole point.

For an `EMPLOYEE`-scope authorization, the new window must not overlap any `ACTIVE` `EMPLOYEE`-scope authorization for the same `employee_id`. Overlap is the half-open test in which the new window's start is earlier than an existing window's end and that existing window's start is earlier than the new window's end; windows that merely touch at an endpoint do not overlap and are allowed. A true overlap is rejected with `ERR_AUTH_WINDOW_OVERLAP`. For a `CARD`-scope authorization, the new window must keep a buffer gap of two days from any `ACTIVE` `CARD`-scope authorization for the same `card_id`: the new window is acceptable only if its start is at least two days after the existing window's end, or its end plus two days is at or before the existing window's start. Any window that fails to keep that two-day buffer — including windows that merely touch, which the employee scope would have allowed — is rejected with `ERR_AUTH_WINDOW_TOO_CLOSE`. Under both scopes, only `ACTIVE` authorizations constrain a new one; authorizations that have been consumed or cancelled do not block. An administrator may mark an `ACTIVE` authorization `CONSUMED` or `CANCELLED` (each defined only from `ACTIVE`, else `ERR_INVALID_STATE`); cancelling frees the window so a later authorization may overlap or abut it, and each transition increments the authorization's `version`.

### 3.10. ERP Export

When a cycle's books are settled, a `FinanceAdmin` builds an ERP sync batch from a statement that is `CLOSED`, `DUE`, `PAST_DUE`, or `PAID` (any other status yields `ERR_INVALID_STATE`). The build is given a `company_id` and a `statement_id`, and it captures, at build time, the company's `SETTLED` transactions whose `statement_id` is this statement and whose `gl_account_id` is non-null: the batch records the count of those rows in `entry_count` and the sum of their `settled_amount_cents` in `total_debits_cents`. A new batch is `BUILT`. The administrator then either posts it (`BUILT → POSTED`) or discards it (`BUILT → DISCARDED`); each is defined only from `BUILT` (else `ERR_INVALID_STATE`) and increments the batch's `version`. `POSTED` and `DISCARDED` are terminal. Auditors, alongside finance administrators, may read ERP batches.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and computed reads — return `200 OK`. All endpoints are mounted at the API root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/companies` | Create a company (also creates its reward account and first open statement) | FinanceAdmin |
| GET | `/companies/{companyId}` | Get a company (includes computed available credit) | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/companies` | List companies | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/companies/{companyId}/suspend` | Suspend a company | FinanceAdmin |
| POST | `/_clock/set_current_utc` | Set a company's simulated clock; triggers past-due evaluation | FinanceAdmin |
| POST | `/spend-policies` | Create a spend policy | FinanceAdmin |
| GET | `/spend-policies/{policyId}` | Get a spend policy | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/spend-policies` | List spend policies | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/employees` | Create an employee | FinanceAdmin |
| GET | `/employees/{employeeId}` | Get an employee | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/employees` | List employees | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/gl-accounts` | Create a GL account | FinanceAdmin |
| GET | `/gl-accounts/{glAccountId}` | Get a GL account | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/gl-accounts` | List GL accounts | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/cards` | Issue a card (virtual active, physical requested) | FinanceAdmin |
| GET | `/cards/{cardId}` | Get a card (includes computed held amount) | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/cards` | List cards | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/cards/{cardId}/activate` | Activate a physical card | FinanceAdmin |
| POST | `/cards/{cardId}/freeze` | Freeze a card | FinanceAdmin |
| POST | `/cards/{cardId}/unfreeze` | Unfreeze a card | FinanceAdmin |
| POST | `/cards/{cardId}/terminate` | Terminate a card | FinanceAdmin |
| POST | `/cards/{cardId}/transactions` | Capture a transaction (authorization) on a card | CardholderEmployee, FinanceAdmin |
| GET | `/transactions/{txId}` | Get a transaction | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/transactions` | List transactions | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| PATCH | `/transactions/{txId}` | Assign or change the GL code on a transaction | CardholderEmployee, FinanceAdmin |
| POST | `/transactions/{txId}/clear` | Advance authorization pending to cleared | FinanceAdmin |
| POST | `/transactions/{txId}/settle` | Advance authorization cleared to settled; posts to statement and accrues reward | FinanceAdmin |
| POST | `/transactions/{txId}/reverse` | Reverse a pending/cleared authorization (releases hold) | FinanceAdmin |
| POST | `/transactions/{txId}/receipts` | Upload a receipt and run receipt-match | CardholderEmployee, FinanceAdmin |
| GET | `/transactions/{txId}/receipts` | List receipts for a transaction | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/receipts/{receiptId}` | Get a receipt | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/receipts` | List receipts | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/transactions/{txId}/approve-review` | Advance review matched to approved | Approver |
| POST | `/transactions/{txId}/flag` | Flag a transaction for review | Approver |
| POST | `/transactions/{txId}/approval-requests` | Open an approval request for a high-value transaction | CardholderEmployee, FinanceAdmin |
| GET | `/approval-requests/{arId}` | Get an approval request | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/approval-requests` | List approval requests | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/approval-requests/{arId}/approve` | Approve an approval request | Approver |
| POST | `/approval-requests/{arId}/reject` | Reject an approval request | Approver |
| POST | `/approval-requests/{arId}/resubmit` | Resubmit a rejected approval request | CardholderEmployee |
| POST | `/reimbursement-claims` | Create an out-of-pocket reimbursement claim | CardholderEmployee, FinanceAdmin |
| GET | `/reimbursement-claims/{claimId}` | Get a reimbursement claim | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/reimbursement-claims` | List reimbursement claims | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/reimbursement-claims/{claimId}/submit` | Submit a draft claim | CardholderEmployee |
| POST | `/reimbursement-claims/{claimId}/approve` | Approve a submitted claim (computes payout) | Approver |
| POST | `/reimbursement-claims/{claimId}/reject` | Reject a submitted claim | Approver |
| POST | `/reimbursement-claims/{claimId}/revise` | Return a rejected claim to draft | CardholderEmployee |
| POST | `/reimbursement-claims/{claimId}/pay` | Pay an approved claim (accrues reward) | FinanceAdmin |
| GET | `/statements/{stmtId}` | Get a statement | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/statements` | List statements | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/statements/{stmtId}/close` | Close the open statement; computes balance and minimum due; opens next cycle | FinanceAdmin |
| POST | `/statements/{stmtId}/issue` | Issue a closed statement (closed to due) | FinanceAdmin |
| GET | `/statements/{stmtId}/cashback-summary` | Computed read: statement cashback total over settled transactions | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/repayments` | Create a repayment against a due/past-due statement (OCC guarded) | FinanceAdmin |
| GET | `/repayments/{repaymentId}` | Get a repayment | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/repayments` | List repayments | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/repayments/{repaymentId}/clear` | Clear a repayment; allocates to statement, frees credit, may pay the statement | FinanceAdmin |
| POST | `/repayments/{repaymentId}/fail` | Fail an initiated repayment | FinanceAdmin |
| POST | `/repayments/{repaymentId}/reverse` | Reverse a cleared repayment (unwinds allocation) | FinanceAdmin |
| GET | `/reward-accounts/{rewardAccountId}` | Get the reward account | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/reward-accounts` | List reward accounts | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/reward-accounts/{rewardAccountId}/redeem` | Redeem cashback (decreases balance) | FinanceAdmin |
| POST | `/spend-authorizations` | Create a pre-authorized spend budget over a window | FinanceAdmin, Approver |
| GET | `/spend-authorizations/{authId}` | Get a spend authorization | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| GET | `/spend-authorizations` | List spend authorizations | FinanceAdmin, Approver, CardholderEmployee, Auditor |
| POST | `/spend-authorizations/{authId}/consume` | Mark a spend authorization consumed | FinanceAdmin |
| POST | `/spend-authorizations/{authId}/cancel` | Cancel a spend authorization (frees its window) | FinanceAdmin |
| POST | `/erp-sync-batches` | Build an ERP sync batch from a closed statement's coded settled transactions | FinanceAdmin |
| GET | `/erp-sync-batches/{batchId}` | Get an ERP sync batch | FinanceAdmin, Auditor |
| GET | `/erp-sync-batches` | List ERP sync batches | FinanceAdmin, Auditor |
| POST | `/erp-sync-batches/{batchId}/post` | Post an ERP batch | FinanceAdmin |
| POST | `/erp-sync-batches/{batchId}/discard` | Discard an ERP batch | FinanceAdmin |

The query parameters available on list endpoints are: `status` (companies, spend policies, employees, GL accounts, cards, statements, repayments, ERP batches, spend authorizations); `company_id` (spend policies, employees, GL accounts, cards, transactions, receipts, approval requests, reimbursement claims, statements, repayments, reward accounts, spend authorizations, ERP batches); `manager_employee_id` and `employee_role` (employees); `employee_id` (cards, reimbursement claims, spend authorizations); `spend_policy_id` (cards); `card_id` (transactions, spend authorizations); `statement_id` (transactions, repayments, ERP batches); `gl_account_id` (transactions, reimbursement claims); `auth_status` and `review_status` (transactions); `transaction_id` (receipts, approval requests); `requester_employee_id` and `approver_employee_id` (approval requests); and `scope` (spend authorizations).

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_SELF_APPROVAL` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_GL_CODE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_COMPANY_SUSPENDED` | 409 |
| `ERR_MCC_BLOCKED` | 409 |
| `ERR_CARD_NOT_ACTIVE` | 409 |
| `ERR_PER_TXN_LIMIT_EXCEEDED` | 409 |
| `ERR_CARD_LIMIT_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
| `ERR_CARD_HAS_OPEN_AUTH` | 409 |
| `ERR_GL_CODE_REQUIRED` | 409 |
| `ERR_APPROVAL_REQUIRED` | 409 |
| `ERR_APPROVAL_NOT_NEEDED` | 409 |
| `ERR_RECEIPT_REQUIRED` | 409 |
| `ERR_CLOCK_NOT_SET` | 409 |
| `ERR_INSUFFICIENT_REWARD_BALANCE` | 409 |
| `ERR_AUTH_WINDOW_OVERLAP` | 409 |
| `ERR_AUTH_WINDOW_TOO_CLOSE` | 409 |
