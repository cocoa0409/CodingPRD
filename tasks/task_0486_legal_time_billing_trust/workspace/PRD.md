# Legal Time, Billing & Trust API — Product Requirements Document

## 1. Introduction

Law firms operate two ledgers that must never be confused: the firm's own operating books and the client trust (IOLTA) money it holds in escrow. This API is the system of record that keeps those two worlds honest at the same time. It carries a matter from intake — through conflict screening, time and expense capture, LEDES/UTBMS coding, and invoicing — all the way to collections, while independently tracking every dollar of client retainer through a pooled trust account that must reconcile three ways at all times.

The product exists because the two hardest problems in legal billing are arithmetic discipline and segregation of duties. Billable amounts must be rounded the same way every time, in pinned six-minute increments, so that a finalized invoice can never disagree with the sum of its lines. Trust money must obey a conserved invariant — the firm's cash book, the per-client sub-ledgers, and the bank statement are three legs of one balance — and the person who initiates a disbursement of a client's trust funds can never be the person who approves it. Layered on top are realization reporting (what the firm actually collects versus what it billed), retainer replenishment thresholds, and an optimistic-concurrency guard that prevents a trust sweep from over-paying an invoice whose balance has already moved.

This document specifies the complete contract: the resources, their lifecycles, the calculations that pin monetary values, the validations that protect the trust, and the role boundaries that enforce IOLTA controls. Unless a rule below states otherwise, every monetary figure is an integer number of cents and every timestamp is interpreted against the server's logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under `/firm`, with a single test-driving clock endpoint living outside that prefix.

### 2.1. User and Role-Based Access Control

Every request other than the liveness probe must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as `PlatformAdmin`, `BillingClerk`, and `Attorney`. When a present, authenticated role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All three roles carry an **opaque** identity: when `X-User-Role` is `PlatformAdmin`, `BillingClerk`, or `Attorney`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server does, however, record these operator identifiers where the workflow demands an audit trail — specifically, the identifier of whoever initiates a trust disbursement or sweep is stored as `initiated_by_user_id` on the resulting `TrustTransaction`, and the identifier of the attorney who approves or reverses such a transaction is stored as `approved_by_user_id`. These recorded values exist so the segregation-of-duties rule can compare initiator against approver; they remain opaque strings, not foreign keys to any user entity.

`PlatformAdmin` is the firm's operational superuser and may perform any business action in the system, in addition to its exclusive configuration powers (creating timekeepers, creating billing codes, creating trust accounts, and advancing the logical clock). `BillingClerk` runs the back office. `Attorney` is the licensed-attorney counterparty whose approval is required wherever IOLTA segregation of duties applies. The precise role authorized for each operation is given in the endpoint table of §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Audit Trail

Most resources in the system are full first-class entities and carry a common set of system-managed fields. Each such resource exposes an `id` — a server-minted UUID with no type prefix, used for identity only and never as a business-decision input — together with `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and an integer `version`. The `created_at` of a resource is the canonical chronological and tie-break key used throughout the system. The `version` of a resource begins at 1 on creation and increases by exactly 1 on every mutation, including mutations caused by a cascaded side effect originating elsewhere; the `updated_at` timestamp is refreshed on every such mutation. The full-fielded entities are `Client`, `Timekeeper`, `Matter`, `ConflictCheck`, `TimeEntry`, `ExpenseEntry`, `Invoice`, `TrustAccount`, `ClientTrustLedger`, `RetainerHold`, and `Payment`.

Two resources are deliberately leaner. A `BillingCode` and a `TrustTransaction` each carry only an `id` and a `created_at`; neither has an `updated_at` and neither has a `version`. This reflects their nature: billing codes are reference data and trust transactions are append-only ledger events. A trust transaction is never edited in place — its `created_at` is the append-only ordering key for replaying a ledger, and any correction is made by a separate compensating transaction rather than by mutating the original.

### 2.5. Monetary Precision and Rounding

Every monetary value in the system is stored and returned as an integer number of cents. Where a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent — that is, a value exactly halfway between two cents rounds to the larger magnitude. Hourly rates supplied as input (`standard_rate_cents`, `matter_rate_cents`, and the `rate_cents` of a client rate override) are taken as already-rounded integer cents and are never re-rounded. The realization percentage reported for a client is the one place a non-integer appears: it is expressed to exactly two decimal places, also rounded half up. The exact rounding order for time-entry amounts and invoice subtotals is pinned in §3 and must be followed precisely, because rounding per line and then summing yields a different cent total than summing first and rounding once.

### 2.6. Resource Existence and Left-to-Right Path Validation

Before any business rule runs, the system confirms that every resource referenced by the request actually exists. For endpoints whose path contains a resource identifier, and for request bodies that carry foreign-key references, validation proceeds left to right: the resource named earliest in the path is checked first, then nested or sub-resources, and finally the foreign keys carried in the body. The first identifier that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND` (HTTP 404), before any later identifier is examined and before any state or business check is attempted. For example, an operation against a conflict check under a matter resolves the matter identifier before the conflict-check identifier.

### 2.7. Referential Kind Checks

Several foreign keys must point not merely at an existing record but at a record of the correct kind. A time entry's `utbms_task_code` must reference a `BillingCode` whose `kind` is `TASK`, its `utbms_activity_code` must reference a `BillingCode` whose `kind` is `ACTIVITY`, and an expense entry's `utbms_expense_code` must reference a `BillingCode` whose `kind` is `EXPENSE`. Likewise, when a conflict check supplies an `adverse_party_client_id`, that value must be the `id` of an existing `Client`. Any of these kind violations is rejected with `ERR_CODE_KIND_MISMATCH` (HTTP 422). These checks apply to time-entry capture, expense-entry capture, and conflict-check creation.

### 2.8. The Three-Way Trust Invariant

The firm's pooled trust money is tracked along three reconciliation legs that must agree. A `TrustAccount` carries a `book_balance_cents` (the firm's cash book) and a `bank_balance_cents` (the bank statement). Each client with money in that account has a `ClientTrustLedger` whose `balance_cents` is that client's sub-ledger. The conserved invariant is that an account's `book_balance_cents` always equals the exact sum of the `balance_cents` of every `ClientTrustLedger` belonging to that account — this equality is a hard invariant that must hold after every posted transaction and must never drift. The bank leg is allowed to lag: `bank_balance_cents` moves only when a transaction clears at the bank, so while any transaction is still pending the bank leg trails the book leg by the signed total of those pending transactions. Full reconciliation is achieved only when no pending transactions remain and all three legs are equal. The mechanics of how individual transactions move each leg are described in §3.

### 2.9. Optimistic Concurrency on Trust Sweeps

Paying an invoice out of trust is the one operation guarded by optimistic concurrency control. A request to sweep trust funds against an invoice must carry `expected_invoice_version`, a non-optional field whose value is the `version` of the target invoice as the client last observed it. The sweep both reads how much the invoice still owes and writes a payment against it, so if another writer has advanced the invoice's `version` since the client's last read — for example by applying an operating payment that legitimately reduced the remaining balance — the sweeping client's view of the amount owed is stale and would over-pay. When `expected_invoice_version` does not equal the invoice's current `version`, the sweep is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412) and no ledger is touched. No other endpoint accepts or requires a version field; only the trust sweep is OCC-guarded.

### 2.10. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then referential kind checks (`ERR_CODE_KIND_MISMATCH`). Only after those gates does the system evaluate whether the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`), followed by the optimistic-concurrency check on a trust sweep (`ERR_STALE_INVOICE_VERSION`). Business-safety rules are evaluated next, in this order: segregation of duties (`ERR_SOD_SAME_ACTOR`), conflict gating (`ERR_CONFLICT_NOT_CLEARED`), the no-overdraw rule on trust (`ERR_TRUST_OVERDRAW`), and the ledger-belongs-to-client check on a sweep (`ERR_LEDGER_ACCOUNT_MISMATCH`). Temporal-overlap rules follow: time-entry overlap (`ERR_TIME_OVERLAP`) and retainer-hold overlap (`ERR_HOLD_OVERLAP`). The remaining business constraints — invoice over-payment (`ERR_OVERPAYMENT`), the full-balance write-off rule (`ERR_PARTIAL_WRITEOFF`), the matter-close balance rule (`ERR_MATTER_HAS_OPEN_BALANCE`), and the inactive-timekeeper rule (`ERR_TIMEKEEPER_INACTIVE`) — are evaluated after the safety rules. Last of all comes generic body validation (`ERR_INVALID_REQUEST`) for missing or malformed fields, bad enums, and non-positive numeric inputs, except that pagination-bound violations surface as `ERR_VALIDATION_LIMIT` and a duplicate billing code surfaces as `ERR_DUPLICATE_CODE`.

## 3. Business Logic & Workflows

### 3.1. Client and Matter Intake

A firm begins by registering a `Client`, supplying a `display_name` (the client's legal name, one to two hundred characters) and a `client_type` of either `INDIVIDUAL` or `ORGANIZATION`. A newly created client starts life in `status` `PROSPECT` with an `ar_balance_cents` of 0. A client's `status` is computed by the system and walks `PROSPECT → ACTIVE → INACTIVE` over its lifetime: it becomes `ACTIVE` the first time one of its matters is opened for work, and returns to `INACTIVE` once every one of its matters has been closed. The `display_name` doubles as the value screened during conflict checking, matched case-insensitively after trimming surrounding whitespace.

A `Matter` is opened against a client by supplying that client's identifier as `client_id`, the identifier of the responsible attorney as `responsible_timekeeper_id`, a `title` of one to two hundred characters, and optionally a `matter_rate_cents` — a negotiated matter-level hourly rate which, when present, must be at least 0 and which sits at the top of the rate ladder described in §3.3. A new matter is created in `status` `INTAKE` with both `wip_fees_cents` and `wip_expenses_cents` at 0. The matter's `status` follows a branching, partly cyclic lifecycle: `INTAKE → CONFLICT_PENDING → CONFLICT_CLEARED → OPEN → CLOSED`, with a `CONFLICT_BLOCKED` branch off `CONFLICT_PENDING`. Both `CLOSED` and `CONFLICT_BLOCKED` are terminal in the ordinary sense, though a blocked matter can be re-opened by a partner waiver as described below.

### 3.2. Conflict Screening and the Intake Gate

Before a matter can do any work, it must clear a conflict screen. A `BillingClerk` runs the screen against a matter that is currently in `INTAKE` (and whose `client_id` references an existing client), supplying an `adverse_party_name` of one to two hundred characters and optionally an `adverse_party_client_id` naming an existing client as the adverse party. Running the screen creates a `ConflictCheck` carrying its `matter_id` and the supplied adverse-party fields, and moves the matter from `INTAKE` to `CONFLICT_PENDING`.

The screen computes the check's `result` and its `matched_client_id` as follows. The system normalizes a name by trimming surrounding whitespace and comparing case-insensitively. It assembles a candidate set: if `adverse_party_client_id` was supplied, that linked client is always a candidate; additionally, every existing `Client` whose normalized `display_name` equals the normalized `adverse_party_name` is a candidate, and every existing `Timekeeper` whose normalized `full_name` equals the normalized `adverse_party_name` is a candidate. If the candidate set is empty, `result` is `CLEAR` and `matched_client_id` is left null. If the candidate set is non-empty, `result` is `FLAGGED`; the system then takes the subset of candidates that are clients, orders them by `created_at` ascending, and sets `matched_client_id` to the earliest such client's `id` — or leaves `matched_client_id` null when only a timekeeper matched and no client did. A `WAIVED` result, the third possible value, is reached only through a partner override and never directly from the screen.

The screen's outcome drives the matter automatically. When the just-created check is `CLEAR`, the system advances the matter from `CONFLICT_PENDING` to `CONFLICT_CLEARED`. When it is `FLAGGED`, the system advances the matter from `CONFLICT_PENDING` to `CONFLICT_BLOCKED` instead. A blocked matter is reopened only by partner waiver: an `Attorney` waiving a flagged check requires that the check's `result` is `FLAGGED` and the matter's `status` is `CONFLICT_BLOCKED`; the waiver sets the check's `result` to `WAIVED`, records the approving attorney's identifier on the check, and moves the matter from `CONFLICT_BLOCKED` back to `CONFLICT_CLEARED`. The conflict gate is enforced wherever work would begin: a matter may not be opened, and no time or expense may be captured against it, unless its latest conflict check has a `result` of either `CLEAR` or `WAIVED`; a matter whose latest check is `FLAGGED` is `CONFLICT_BLOCKED`, and any of these three operations — opening the matter, capturing a time entry, or capturing an expense entry — is rejected with `ERR_CONFLICT_NOT_CLEARED` (HTTP 409) when the gate is not satisfied.

### 3.3. Opening a Matter and Resolving the Billable Rate

An `Attorney` opens a matter that is in `CONFLICT_CLEARED`, moving its `status` to `OPEN`. Opening has cascading effects: if the owning client is still `PROSPECT`, its `status` is promoted to `ACTIVE`; and if the client does not yet have a trust sub-ledger in the default trust account, one `ClientTrustLedger` is created for that client. Capture of time and expense becomes legal only once the matter is `OPEN` — an attempt to capture against a matter in any other state is an invalid-state rejection (`ERR_INVALID_STATE`, HTTP 409).

Capturing a `TimeEntry` resolves and freezes an hourly rate at the moment of capture. The system uses a strict precedence ladder and stops at the first applicable tier. The highest-precedence tier is the matter's own negotiated rate: if the matter's `matter_rate_cents` is present (non-null), the resolved rate is exactly that value. Otherwise, the system looks for a client rate override matching the client and the timekeeper's `role_kind`; if such an override exists, the resolved rate is the override's `rate_cents`. If neither of those applies, the resolved rate falls to the timekeeper's `standard_rate_cents`, which is always present and is the lowest-precedence tier. The chosen value is stored on the entry as `resolved_rate_cents` and never changes afterward. A client rate override is itself created against a client by supplying a `role_kind` and a `rate_cents`, and creating a new override for a role tier replaces any prior override for that same `role_kind`; the override exposes its own `id`, `client_id`, `role_kind`, and `rate_cents`.

### 3.4. Capturing Time and Expense

To capture a `TimeEntry`, a caller supplies the `matter_id`, the `timekeeper_id` of who performed the work, the `worked_at` start instant, the `minutes` worked (a positive integer), and the two UTBMS codes `utbms_task_code` and `utbms_activity_code`. The timekeeper must be active: capturing against a `Timekeeper` whose `is_active` is false is rejected with `ERR_TIMEKEEPER_INACTIVE` (HTTP 422). A captured entry starts in `status` `CAPTURED` with its `invoice_id` null.

Billing is metered in six-minute increments — tenths of an hour — and always rounds the duration up. The number of billable tenths of an hour is the worked `minutes` divided by 6, rounded up to the next whole tenth (so 1 through 6 minutes bill as one tenth, 7 through 12 as two tenths, and so on). The entry's `billable_amount_cents` is then the resolved hourly rate (`resolved_rate_cents`) multiplied by that number of billable tenths, divided by ten, with the result rounded half up to whole cents. This per-entry cent amount is computed and pinned on each entry individually at capture; invoice subtotals are later formed by summing these already-rounded per-entry amounts, and the system never sums raw rate-times-minutes products and rounds once at the end. Capturing a time entry adds its `billable_amount_cents` to the owning matter's `wip_fees_cents`.

Each time entry also occupies a slice of its timekeeper's calendar: the half-open interval that starts at `worked_at` and ends `minutes` later, written as the interval from `worked_at` up to but not including `worked_at` plus `minutes`. Two entries for the same timekeeper may not overlap. Because the interval is half-open, two entries that merely touch — one ending at exactly the instant the next begins — do not overlap and are permitted; any genuine overlap with an existing entry for that same timekeeper that is not in `status` `WRITTEN_DOWN` is rejected with `ERR_TIME_OVERLAP` (HTTP 409).

An `ExpenseEntry` is simpler: a caller supplies the `matter_id`, an `utbms_expense_code`, and a positive `amount_cents`, which is a hard cost taken as final with no rate applied. A new expense starts in `status` `CAPTURED` with a null `invoice_id`, and its `amount_cents` is added to the matter's `wip_expenses_cents`. Both a time entry and an expense entry have a three-valued `status`: `CAPTURED` at creation, `INVOICED` once rolled onto a finalized invoice, and `WRITTEN_DOWN` if struck before invoicing. An `Attorney` may strike a still-`CAPTURED` time entry — writing it down sets its `status` to `WRITTEN_DOWN` and subtracts its `billable_amount_cents` from the matter's `wip_fees_cents`. The provisional work-in-progress for a matter can be read at any time before finalizing: that summary recomputes `wip_fees_cents` and `wip_expenses_cents` live as the sum of `billable_amount_cents` over the matter's `CAPTURED` time entries and the sum of `amount_cents` over its `CAPTURED` expense entries, and reports them alongside a `time_entry_count` and an `expense_entry_count`. No line write-downs are applied in this provisional view.

### 3.5. Drafting, Finalizing, and Voiding Invoices

An invoice is built in two stages. First a `BillingClerk` creates a `DRAFT` `Invoice` for a matter, supplying the `matter_id`, an `issue_date`, and optionally `net_terms_days` (defaulting to 30, and at least 0). At creation the invoice copies the matter's owning client into its `client_id`, sets `billing_status` to `DRAFT`, and sets `collection_status` to `CURRENT`. An `Invoice` carries two independent state dimensions on the same record: a `billing_status` that walks `DRAFT → ISSUED → PARTIALLY_PAID → PAID` with branch states `WRITTEN_OFF` and `VOID`, and a `collection_status` that walks `CURRENT → DUE → OVERDUE → IN_COLLECTIONS` with a `SETTLED` terminus. These two dimensions evolve independently while the invoice is `ISSUED`.

Finalizing a `DRAFT` invoice issues it. A `BillingClerk` finalizes, optionally supplying `line_write_downs` — per-line fee reductions to apply at finalize. Finalize requires that the invoice's `billing_status` is `DRAFT` and the matter's `status` is `OPEN`, and that at least one `CAPTURED` time or expense entry is attached so that the resulting `total_cents` is greater than zero after write-downs. The attachment set is precisely those time entries and expense entries whose `matter_id` equals the invoice's `matter_id`, whose `status` is `CAPTURED`, and whose `invoice_id` is null; entries already `INVOICED` or `WRITTEN_DOWN` are excluded, and the eligible entries are ordered by `created_at` ascending for deterministic line numbering. Finalize pins four amounts. The `fees_subtotal_cents` is the sum of `billable_amount_cents` over the attached time entries (each already rounded per the per-entry rule), then reduced by the total of the supplied `line_write_downs`. The `expenses_subtotal_cents` is the sum of `amount_cents` over the attached expense entries. The `written_off_cents` is set to the total of those line write-downs. The `total_cents` is `fees_subtotal_cents` plus `expenses_subtotal_cents` after the write-downs are applied.

Finalize then cascades. Each attached time entry and expense entry flips from `CAPTURED` to `INVOICED` and has its `invoice_id` set to this invoice, so it can never re-enter another invoice's work-in-progress. The matter's `wip_fees_cents` and `wip_expenses_cents` are decremented by the amounts just invoiced. The owning client's `ar_balance_cents` is increased by the invoice's `total_cents`. The invoice's `collection_status` is set to `CURRENT`, its `issue_date` is set, its `billing_status` becomes `ISSUED`, and its `version` is incremented. From the `issue_date` and `net_terms_days` the system derives the collections clock: the due date is the `issue_date` advanced by `net_terms_days` days.

A `DRAFT` invoice that should not have been raised can be voided by a `BillingClerk`; only an un-issued draft may be voided. Voiding moves `billing_status` to `VOID`, detaches any attached entries (their `status` stays `CAPTURED` and their `invoice_id` is cleared so they return to work-in-progress), and increments the invoice's `version`.

### 3.6. Payments, Trust Sweeps, and the A/R Ledger

Once an invoice is `ISSUED`, it can be paid two ways: directly from the firm's operating account, or by sweeping the client's trust funds. A `BillingClerk` applies an operating-account `Payment` by supplying an `amount_cents` and a `method` of `CHECK`, `ACH`, or `CARD`; the payment is created in `status` `APPLIED` against the invoice named by its `invoice_id`. Applying a payment adds its `amount_cents` to the invoice's `amount_paid_cents`, advances the billing dimension, recomputes the client's `ar_balance_cents`, and increments the invoice's `version`. The billing dimension advances by comparing the new cumulative `amount_paid_cents` against the amount actually owed, which is `total_cents` minus `written_off_cents`: while the cumulative paid is strictly greater than zero but strictly less than that owed amount, an `ISSUED` invoice becomes `PARTIALLY_PAID`; when the cumulative paid exactly equals the owed amount, the invoice becomes `PAID` (whether it was `ISSUED` or `PARTIALLY_PAID`), and reaching `PAID` also cross-sets the `collection_status` to `SETTLED`. A payment or sweep whose amount would carry the invoice past its remaining balance — the remaining balance being `total_cents` minus `amount_paid_cents` minus `written_off_cents` — is rejected as an over-payment with `ERR_OVERPAYMENT` (HTTP 422).

An operating payment can be reversed, for instance when a check bounces. A `BillingClerk` reverses an `APPLIED` payment only while the invoice's `billing_status` is not `WRITTEN_OFF`; reversal sets the payment's `status` to `REVERSED`, subtracts its `amount_cents` from the invoice's `amount_paid_cents`, recomputes the billing dimension (a previously `PAID` invoice falls back to `PARTIALLY_PAID` or `ISSUED`), recomputes the `collection_status` from the clock so the invoice is un-settled, recomputes the client's `ar_balance_cents`, and increments the invoice's `version`.

Paying from trust is the segregation-of-duties-sensitive path. An `Attorney` sweeps an `ISSUED` or `PARTIALLY_PAID` invoice from the client's trust sub-ledger by supplying an `amount_cents`, the `client_trust_ledger_id` to draw from, an `initiated_by_user_id` naming the back-office operator who initiated the sweep, and the `expected_invoice_version` for the optimistic-concurrency check of §2.9. The approving attorney's own `X-User-ID` must differ from the supplied `initiated_by_user_id`; if they are the same actor, the sweep is rejected with `ERR_SOD_SAME_ACTOR` (HTTP 403). The chosen sub-ledger must belong to the same client as the invoice's `client_id` — a client's trust may only pay that client's invoices — and a mismatch is rejected with `ERR_LEDGER_ACCOUNT_MISMATCH` (HTTP 422). The sweep records a `SWEEP_TO_OPERATING` `TrustTransaction` in `status` `PENDING`, decrements the sub-ledger's `balance_cents` and the trust account's `book_balance_cents` by the swept amount, adds the amount to the invoice's `amount_paid_cents`, advances the billing dimension exactly as a payment would (including the cross-set to `SETTLED` on reaching `PAID`), recomputes the client's `ar_balance_cents`, and increments the invoice's `version`. After the sweep, if the sub-ledger's `balance_cents` has fallen below its `retainer_floor_cents`, the client is flagged for retainer replenishment. A sweep may never drive a sub-ledger's `balance_cents` below zero; such an overdraw is rejected with `ERR_TRUST_OVERDRAW` (HTTP 422).

A client's accounts-receivable picture is two dual quantities computed over the same invoices. The provisional `ar_balance_cents` is the sum, over the client's invoices whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`, of `total_cents` minus `amount_paid_cents` minus `written_off_cents`; it is recomputed on every invoice finalize, payment, and write-down. The final realization rate is computed only over closed-out invoices — those whose `billing_status` is `PAID` or `WRITTEN_OFF`. Over that closed set, the system totals `total_cents` plus `written_off_cents` into a billed-final figure (`billed_final_cents`) and totals `amount_paid_cents` into a collected-final figure (`collected_final_cents`); the `realization_pct` is the collected-final figure multiplied by ten thousand, divided by the billed-final figure, rounded half up, then divided by one hundred to yield a percentage carried to two decimal places — and it is reported as 0 when the billed-final figure is zero. Write-offs therefore lower realization without lowering the billed amount, which is the whole point of the measure. The A/R summary returns `ar_balance_cents`, `realization_pct`, `billed_final_cents`, and `collected_final_cents` together.

### 3.7. Write-Off, Collections Aging, and Matter Close

An `Attorney` can write off the full remaining balance of an `ISSUED` or `PARTIALLY_PAID` invoice. The supplied `amount_cents` must equal the full remaining balance — `total_cents` minus `amount_paid_cents` — because partial write-offs are not supported; a write-off amount that does not equal the full remaining balance is rejected with `ERR_PARTIAL_WRITEOFF` (HTTP 422). A valid write-off adds the remaining balance into `written_off_cents`, moves `billing_status` to `WRITTEN_OFF`, cross-sets `collection_status` to `SETTLED`, drops the invoice out of A/R by recomputing the client's `ar_balance_cents`, and increments the invoice's `version`.

The collection dimension ages against the server's logical clock. Whenever the clock is advanced, and whenever an individual invoice is read, the system recomputes `collection_status` for every invoice whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`. The rules are pinned to exact boundaries. An invoice whose `billing_status` is `PAID`, `WRITTEN_OFF`, or `VOID` is `SETTLED` (a voided invoice has no collections life). Otherwise, if the current clock instant is at or before the due date, the invoice is `DUE` when the clock has reached the `issue_date` and `CURRENT` while still before it. If the current clock is strictly past the due date but no later than the due date plus the collections grace period of fifteen days, the invoice is `OVERDUE`. Past that grace window the invoice remains `OVERDUE` until acted upon — it never becomes `IN_COLLECTIONS` automatically. At exactly the due date the invoice is `DUE` and not yet `OVERDUE`; `OVERDUE` requires the clock to be strictly past the due date. Moving an invoice into `IN_COLLECTIONS` is an explicit action: a `BillingClerk` sends an `OVERDUE` invoice to collections, permitted only once the clock is past the due date plus the fifteen-day grace and while the invoice's `billing_status` is still `ISSUED` or `PARTIALLY_PAID`; doing so sets `collection_status` to `IN_COLLECTIONS` and increments the invoice's `version`. Attempting to send to collections before the grace period has fully elapsed is rejected with `ERR_COLLECTIONS_TOO_EARLY` (HTTP 409).

Closing a matter is the final discipline. An `Attorney` closes an `OPEN` matter only when there is no un-invoiced work in progress — both `wip_fees_cents` and `wip_expenses_cents` must be zero — and no outstanding receivable, meaning the matter has no invoice whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`. A close attempt that violates either condition is rejected with `ERR_MATTER_HAS_OPEN_BALANCE` (HTTP 409). A successful close moves the matter's `status` to `CLOSED` and, if every sibling matter of the client is now `CLOSED`, cascades the client's `status` to `INACTIVE`.

### 3.8. Trust Deposits, Disbursements, Confirmation, and Reversal

The trust ledger is fed and drained by append-only transactions. A trust sub-ledger is opened against an account by supplying a `trust_account_id`, a `client_id`, and optionally a `retainer_floor_cents` (defaulting to 0, at least 0); opening is idempotent per account-and-client pair and the new `ClientTrustLedger` starts with `balance_cents` of 0. A `TrustTransaction` posts to a sub-ledger by its `client_trust_ledger_id` with a `kind`, a positive `amount_cents` carrying the absolute magnitude (the sign is implied by the kind), and an `initiated_by_user_id`. The `kind` is one of `DEPOSIT` (a retainer coming in, positive), `DISBURSEMENT` (a refund or third-party payment going out, negative), or `SWEEP_TO_OPERATING` (paying an invoice, negative, and carrying the paid invoice in its `invoice_id`); the `invoice_id` is set only for a sweep and is otherwise null. Posting a transaction is immediate on the book side: it adjusts the sub-ledger's `balance_cents` and the account's `book_balance_cents` by the signed amount, increments both the sub-ledger's `version` and the account's `version`, but does not move `bank_balance_cents`. A new transaction starts in `status` `PENDING`. A `DISBURSEMENT` or `SWEEP_TO_OPERATING` may never drive the sub-ledger's `balance_cents` below zero — a client's trust funds may never cover another client's obligation — and any such overdraw is rejected with `ERR_TRUST_OVERDRAW` (HTTP 422). For a disbursement, the approving attorney's `X-User-ID` must differ from the transaction's `initiated_by_user_id`, and the approver's identifier is recorded as `approved_by_user_id` (which stays null for a deposit).

Two later actions move a transaction out of `PENDING`. Confirming a `PENDING` transaction — a `BillingClerk` action — records that it cleared at the bank: it sets `status` to `CONFIRMED` and adds the signed amount to the account's `bank_balance_cents`, letting the bank leg catch up to the book leg, and increments the account's `version`. Reversing a transaction is the compensation path and is an `Attorney` action; the reversing attorney's `X-User-ID` must differ from the transaction's `initiated_by_user_id`, and a same-actor reversal is rejected with `ERR_SOD_SAME_ACTOR` (HTTP 403). Reversing a still-`PENDING` transaction sets its `status` to `VOIDED`, subtracts the signed amount from both the sub-ledger's `balance_cents` and the account's `book_balance_cents`, and increments both versions — the bank leg is left untouched because a pending transaction never reached the bank. Reversing a `CONFIRMED` transaction also sets `status` to `VOIDED` and reverses the sub-ledger and book legs, and additionally subtracts the signed amount from `bank_balance_cents` because that transaction had already cleared; both versions increment. Either reversal must leave the three-way invariant of §2.8 intact. The three-way reconciliation report for an account returns the book leg as `leg_book_cents`, the summed client sub-ledgers as `leg_client_cents`, the bank leg as `leg_bank_cents`, a `reconciled` boolean that is true only when all three legs are equal, and an `unconfirmed_cents` figure equal to the book leg minus the bank leg — the magnitude still pending at the bank.

### 3.9. Retainer Holds

When the firm anticipates a cost against a client's trust, it can reserve part of the balance with a `RetainerHold`. A hold is placed on a sub-ledger by supplying its `client_trust_ledger_id`, a positive `amount_cents` to reserve, and the reservation window's `hold_start_at` and `hold_end_at`; the end instant must be strictly after the start instant. The hold is an informational reservation and starts in `status` `ACTIVE`. The reservation window is a closed interval running from `hold_start_at` through `hold_end_at` inclusive of both endpoints. Two holds on the same sub-ledger may not overlap, and because the interval is closed the endpoints collide: a new hold whose start equals an existing active hold's end (or vice versa) does overlap and is rejected — this is stricter than the half-open time-entry interval, where touching endpoints are allowed. Any overlap with an `ACTIVE` hold on the same sub-ledger is rejected with `ERR_HOLD_OVERLAP` (HTTP 409). A `BillingClerk`, `Attorney`, or `PlatformAdmin` may release an `ACTIVE` hold; releasing sets its `status` to `RELEASED`, frees the window so a later active hold may occupy it, and increments the hold's `version`.

### 3.10. Reference Data and the Logical Clock

Billing codes are reference data managed by a `PlatformAdmin`, who creates a `BillingCode` by supplying a `code` (a UTBMS/LEDES string of two to ten characters, unique across all billing codes), a `kind` of `TASK`, `ACTIVITY`, or `EXPENSE`, and a human-readable `label` of one to one hundred twenty characters. Attempting to create a code whose `code` already exists is rejected with `ERR_DUPLICATE_CODE` (HTTP 409). A `Timekeeper` is likewise created by a `PlatformAdmin` with a `full_name`, a `role_kind` of `PARTNER`, `ASSOCIATE`, or `PARALEGAL` (which drives the default standard-rate tier), a non-negative `standard_rate_cents`, and an optional `is_active` flag defaulting to true; the `full_name` is screened against adverse-party names during conflict checks. A `TrustAccount` is created by a `PlatformAdmin` with a `name` of one to one hundred twenty characters, starting with `book_balance_cents` and `bank_balance_cents` both at 0.

Finally, the system runs on a logical clock rather than wall-clock time so that collections aging is deterministic and testable. Before any clock is set, the server's logical clock reads `2026-01-01T00:00:00Z`. A `PlatformAdmin` advances the clock to a supplied UTC instant, given as `to_iso8601`; setting it returns the new `current_utc` and recomputes `collection_status` for every invoice whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`, per the aging rules of §3.7. A liveness probe is also available without authentication and reports a `status` string and the current `current_utc`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. The liveness probe is the only endpoint that requires no authentication headers; every other endpoint requires `X-User-ID` and `X-User-Role`. List endpoints accept the pagination query parameters `limit` and `offset` described in §2.3, in addition to the resource-specific filters noted below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/firm/clients` | Create a client (PROSPECT) | PlatformAdmin, BillingClerk |
| GET | `/firm/clients/{id}` | Fetch a client | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/clients` | List clients (filter by `status`) | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/clients/{id}/matters` | List a client's matters | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/clients/{id}/ar-summary` | A/R and realization summary for a client | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/clients/{id}/trust-ledgers` | List a client's trust sub-ledgers | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/clients/{id}/conflict-checks` | List conflict checks referencing this client | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/clients/{id}/rate-overrides` | Set a client's negotiated rate for a role tier | PlatformAdmin, BillingClerk |
| GET | `/firm/clients/{id}/rate-overrides` | List a client's rate overrides | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/timekeepers` | Create a timekeeper with a standard rate | PlatformAdmin |
| GET | `/firm/timekeepers/{id}` | Fetch a timekeeper | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/timekeepers` | List timekeepers (filter by `is_active`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/billing-codes` | Create a UTBMS/LEDES code | PlatformAdmin |
| GET | `/firm/billing-codes` | List billing codes (filter by `kind`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/matters` | Create a matter (INTAKE) for a client | PlatformAdmin, BillingClerk |
| GET | `/firm/matters/{id}` | Fetch a matter | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/matters` | List matters (filter by `client_id`, `responsible_timekeeper_id`, `status`) | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/matters/{id}/wip-summary` | Provisional WIP totals for a matter | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/matters/{id}/conflict-checks` | Run a conflict screen for a matter | PlatformAdmin, BillingClerk |
| GET | `/firm/matters/{id}/conflict-checks` | List conflict checks for a matter | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/matters/{id}/open` | Open a CONFLICT_CLEARED matter | Attorney, PlatformAdmin |
| POST | `/firm/matters/{id}/close` | Close an OPEN matter | Attorney, PlatformAdmin |
| GET | `/firm/conflict-checks/{id}` | Fetch a conflict check | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/conflict-checks/{id}/waive` | Partner waiver of a FLAGGED conflict | Attorney |
| POST | `/firm/time-entries` | Capture a time entry | Attorney, BillingClerk, PlatformAdmin |
| GET | `/firm/time-entries/{id}` | Fetch a time entry | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/time-entries` | List time entries (filter by `matter_id`, `timekeeper_id`, `invoice_id`, `status`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/time-entries/{id}/write-down` | Strike a CAPTURED time entry before invoicing | Attorney |
| POST | `/firm/expense-entries` | Capture an expense entry | Attorney, BillingClerk, PlatformAdmin |
| GET | `/firm/expense-entries/{id}` | Fetch an expense entry | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/expense-entries` | List expense entries (filter by `matter_id`, `invoice_id`, `status`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/invoices` | Create a DRAFT invoice for a matter | BillingClerk, PlatformAdmin |
| GET | `/firm/invoices/{id}` | Fetch an invoice (recomputes collection_status) | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/invoices` | List invoices (filter by `matter_id`, `client_id`, `billing_status`, `collection_status`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/invoices/{id}/finalize` | Finalize a DRAFT invoice and issue it | BillingClerk, PlatformAdmin |
| POST | `/firm/invoices/{id}/void` | Void a DRAFT invoice | BillingClerk, PlatformAdmin |
| POST | `/firm/invoices/{id}/payments` | Apply an operating-account payment | BillingClerk, PlatformAdmin |
| GET | `/firm/invoices/{id}/payments` | List payments applied to an invoice | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/invoices/{id}/trust-sweep` | Pay an invoice from the client's trust ledger | Attorney, PlatformAdmin |
| POST | `/firm/invoices/{id}/write-off` | Write off the full remaining balance | Attorney |
| POST | `/firm/invoices/{id}/send-to-collections` | Move an OVERDUE invoice to IN_COLLECTIONS | BillingClerk, PlatformAdmin |
| GET | `/firm/payments/{id}` | Fetch a payment | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/payments/{id}/reverse` | Reverse an APPLIED operating payment | BillingClerk, PlatformAdmin |
| POST | `/firm/trust-accounts` | Create a pooled IOLTA trust account | PlatformAdmin |
| GET | `/firm/trust-accounts/{id}` | Fetch a trust account | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/trust-accounts/{id}/ledgers` | List client sub-ledgers in an account | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/trust-accounts/{id}/reconciliation` | Three-way reconciliation report | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/trust-ledgers` | Open a client trust sub-ledger | PlatformAdmin, BillingClerk |
| GET | `/firm/trust-ledgers/{id}` | Fetch a client trust sub-ledger | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/trust-ledgers` | List sub-ledgers (filter by `trust_account_id`, `client_id`) | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/trust-ledgers/{id}/transactions` | List a sub-ledger's transactions | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/trust-transactions` | Post a DEPOSIT or DISBURSEMENT to a sub-ledger | BillingClerk, Attorney, PlatformAdmin |
| GET | `/firm/trust-transactions/{id}` | Fetch a trust transaction | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/trust-transactions` | List trust transactions (filter by `client_trust_ledger_id`, `invoice_id`, `status`, `kind`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/trust-transactions/{id}/confirm` | Confirm a PENDING transaction cleared at the bank | BillingClerk, PlatformAdmin |
| POST | `/firm/trust-transactions/{id}/reverse` | Reverse (VOID) a transaction via compensation | Attorney, PlatformAdmin |
| POST | `/firm/retainer-holds` | Place a closed-interval reservation hold | BillingClerk, Attorney, PlatformAdmin |
| GET | `/firm/retainer-holds/{id}` | Fetch a retainer hold | PlatformAdmin, BillingClerk, Attorney |
| GET | `/firm/retainer-holds` | List retainer holds (filter by `client_trust_ledger_id`, `status`) | PlatformAdmin, BillingClerk, Attorney |
| POST | `/firm/retainer-holds/{id}/release` | Release an ACTIVE hold | BillingClerk, Attorney, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock and re-age invoices | PlatformAdmin |
| GET | `/firm/health` | Liveness probe (no auth) | PlatformAdmin, BillingClerk, Attorney |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CODE_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_INVOICE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_SAME_ACTOR` | 403 Forbidden |
| `ERR_CONFLICT_NOT_CLEARED` | 409 Conflict |
| `ERR_TRUST_OVERDRAW` | 422 Unprocessable Entity |
| `ERR_COLLECTIONS_TOO_EARLY` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_PARTIAL_WRITEOFF` | 422 Unprocessable Entity |
| `ERR_MATTER_HAS_OPEN_BALANCE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_TIMEKEEPER_INACTIVE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_VALIDATION_LIMIT` | 422 Unprocessable Entity |
| `ERR_LEDGER_ACCOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TIME_OVERLAP` | 409 Conflict |
| `ERR_HOLD_OVERLAP` | 409 Conflict |
