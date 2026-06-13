# Accounts Receivable & Collections API — Product Requirements Document

## 1. Introduction

This document specifies the Accounts Receivable & Collections API, the system of record for what every customer owes, what has been collected, and how aggressively each account is being pursued. The platform threads together the full receivables lifecycle: invoices age into delinquency buckets, dunning sequences chase the most valuable overdue balances, cash receipts are applied (and occasionally short-paid or reversed) against open invoices, deductions and disputes carve contested amounts out of the dunnable balance, promises to pay buy customers structured grace, and genuinely uncollectible balances are charged off as bad debt under a strict approval discipline.

Two ideas dominate the design. The first is **ledger reconciliation**: every cash movement, credit, write-off, or dispute resolution must keep a customer's derived balances — exposure, open balance, and bad-debt total — internally consistent, and reversing an operation must return those balances to exactly where they were. The second is **posture-driven gating**: each customer carries two independent postures, a *credit dimension* (`GOOD`, `WATCH`, `HOLD`) governing whether new business may be booked, and a *collections dimension* (`CURRENT`, `DUNNING`, `COLLECTIONS`, `WRITEOFF`) tracking how far down the recovery funnel the account has slid. These dimensions move on their own triggers and must never be conflated. Finally, because the AR clerk who applies cash must not be the person who approves a write-off, the API enforces segregation of duties at the operation level. All endpoints are mounted under `/ar`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts — authentication, response envelopes, pagination, derived-field consistency, monetary precision, and concurrency control — that every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request other than the unauthenticated health probe must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing or malforming either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a present-but-blank header, and an `X-User-Role` whose value is not one of the four recognised roles, both count as malformed and likewise yield `ERR_UNAUTHENTICATED` (an unrecognised role is never treated as a well-formed-but-forbidden role). When the headers are well-formed — both present and the role being one of the four recognised values — but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognises exactly four roles, spelled precisely as follows: `AR_MANAGER`, `AR_CLERK`, `COLLECTIONS_AGENT`, and `AUDITOR`. The `AR_MANAGER` supervises the receivables function — opening customer accounts, placing and releasing credit holds, adjudicating disputes, and approving write-offs. The `AR_CLERK` runs the cash-application desk, recording payments and applying, short-paying, auto-applying, or reversing them. The `COLLECTIONS_AGENT` drives the recovery effort: dunning runs, raising and withdrawing disputes, recording and cancelling promises, and scheduling dunning pauses. The `AUDITOR` has read-only oversight across the entire ledger and may perform any GET read but no mutation.

For each of these four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow needs it — for example, to remember which operator created a write-off so that a different operator must approve it — but it never compares `X-User-ID` to any entity's `id` for ownership purposes. Authorization is therefore by role for every operation, with one additional identity check: the segregation-of-duties rule on write-off approval, described in §2.8, compares the approving operator's `X-User-ID` against the creating operator's `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with the resource `id` ascending as a deterministic final tie-break when two records share the same `created_at`. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items returned on this page is still less than `total_count`.

### 2.4. Common Resource Properties and Identity

Most resources in this system are durable, top-level records and carry the full set of system-managed fields. Customer, Invoice, Payment, PaymentApplication, Dispute, PromiseToPay, WriteOff, DunningSequence, DunningPause, and Statement each include:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every modification to the resource, including changes to computed fields.
- `version` — an integer that starts at its initial value and increments by one on every mutation of the resource. It underpins optimistic concurrency control (§2.9).

Two entities are deliberately lighter. A **DunningNotice** is an immutable audit record once emitted, and a **CashForecast** is an ephemeral computed projection that is never persisted. Both carry only `id` and `created_at`; neither has an `updated_at` nor a `version` field. The CashForecast in particular is produced on demand by the forecasting read and is never stored, so it has no stored foreign key and cannot be retrieved later by id.

### 2.5. Nested Resource Retrieval and Reverse Reachability

Several read endpoints expose a child collection beneath a parent resource — for example, the disputes raised against an invoice, the statements cut for a customer, or the notices produced by a dunning sequence. When a path carries an identifier, the system validates it before doing any work: if the parent named in the path does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Where a path carries more than one identifier, they are validated left to right, and the first identifier that resolves to nothing produces the 404 — the server does not proceed to later segments. These reverse-reachability reads return the children whose foreign key points back at the named parent, sorted and paginated per §2.3.

### 2.6. Derived Balances, Posture Cascades, and Consistency

Customer postures and balances are **computed**, never written directly by a client. Whenever an operation changes what a customer owes, the system recomputes the affected derived fields atomically within the same request, before the response is returned, so a caller never observes a half-updated ledger.

A customer's `exposure_cents` is the sum, over that customer's `OPEN` and `PARTIAL` invoices, of each invoice's dunnable balance — that is, its `balance_cents` minus its `disputed_amount_cents`. Exposure is the denominator of every credit decision. A customer's `total_open_balance_cents` is the sum of `balance_cents` over the customer's `OPEN`, `PARTIAL`, and `DISPUTED` invoices; it is the conserved quantity behind the payment-reversal invariant — reversing an application must return `total_open_balance_cents` to exactly the value it held before the application. A customer's `bad_debt_total_cents` is the cumulative amount charged off for that customer and only ever grows, by approved write-offs.

Because cascades touch more than one entity, every mutation that moves money states all of its effects. When an invoice's balance changes, the system recomputes the owning customer's `exposure_cents` and `total_open_balance_cents`, then re-evaluates `credit_status`, and where the triggering event warrants it, re-evaluates `collection_stage`. Each such recomputation that alters the customer is a mutation of the customer: it refreshes the customer's `updated_at` and increments the customer's `version`. A single logical operation is counted as exactly one customer mutation, however many derived fields its recomputation alters: when the operation that triggers the recomputation already mutates that customer directly — placing or releasing a manual hold, creating a promise, or approving a write-off — the version is incremented by exactly one for the whole operation, and the accompanying derived-field recomputation does not add a second increment on top of that direct mutation, even when it also flips a derived field such as `credit_status` or `collection_stage`. The per-operation single increment applies to the customer that the operation mutates directly; a recomputation that is the *only* effect on a customer — because the operation directly mutated a different entity (an invoice, payment, or dispute) and the customer changed solely through the resulting cascade — is itself that customer's one increment. The same holds for invoices — any change to an invoice's balance, disputed amount, status, or dunning index refreshes that invoice's `updated_at` and bumps its `version`.

The two customer postures are **parallel and independent**. `credit_status` answers "may we extend more credit?"; `collection_stage` answers "how far gone is recovery?". They are recomputed by different rules (§2.7 and §3) and one never substitutes for the other. Where a money-moving cascade re-evaluates `collection_stage`, it is recomputed deterministically from the customer's current state, in this fixed order: if the customer has any `WRITTEN_OFF` invoice the stage is `WRITEOFF`; otherwise, taking the worst due-date-basis aging bucket over the customer's `OPEN`, `PARTIAL`, and `DISPUTED` invoices, if that worst bucket is `CURRENT` and the customer has no unredeemed broken promise the stage is `CURRENT`; otherwise if the customer has an unredeemed broken promise or the worst bucket is `B61_90` or `B91_PLUS` the stage is `COLLECTIONS`; otherwise the stage is `DUNNING`. An "unredeemed broken promise" is a `BROKEN` promise with no later-created `KEPT` promise for the same customer. The `CURRENT → DUNNING` move that a dunning run performs (§3.7) is the one transition applied directly rather than through this recomputation.

### 2.7. Credit Posture and the Credit Hold Gate

A customer's `credit_status` is derived from exposure, the credit limit, and the manual-hold flag, re-evaluated after any change to `exposure_cents` — a payment, a write-off, a dispute movement, or a new invoice. The rule is evaluated in this fixed order. If the customer's `manual_hold` is set, the status is `HOLD`. Otherwise, if `exposure_cents` is greater than or equal to `credit_limit_cents`, the status is `HOLD` — note the boundary is inclusive, so exposure exactly equal to the limit yields `HOLD`, not `WATCH`. Otherwise, if `exposure_cents` is greater than or equal to eighty percent of `credit_limit_cents` (that watch threshold being computed as eighty percent of the limit, rounded half up to whole cents), the status is `WATCH`. Otherwise, if a broken-promise floor is in force (§3.5 sets one when a promise breaks while the customer is `GOOD`, and it persists while that broken promise stands unredeemed), the status is `WATCH`. Otherwise the status is `GOOD`.

An `AR_MANAGER` may place a manual credit hold on a customer, which sets `manual_hold` to true and forces `credit_status` to `HOLD` regardless of exposure; releasing the hold clears `manual_hold` and recomputes `credit_status` from exposure. A manual hold holds the account until it is explicitly released.

The credit gate bites at invoice creation. Creating an invoice for a customer whose `credit_status` is `HOLD` at request time — whether because `manual_hold` is active or because current `exposure_cents` is at or above `credit_limit_cents` — is rejected with `ERR_CREDIT_HOLD` (HTTP 402). The check is evaluated against the customer's posture as it stands before the new invoice; the new invoice's own `face_amount_cents` is not pre-added to exposure for this gate. A customer sitting one cent below the limit may therefore still receive an invoice that pushes exposure to the limit; the resulting `HOLD` only blocks the *next* invoice.

### 2.8. Segregation of Duties on Write-Off Approval

A write-off moves through two hands by design. The operator who creates a pending write-off and the operator who approves it must be different people. On approval, the system compares the approving request's `X-User-ID` against the `X-User-ID` that created the write-off; if they are the same, the approval is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This is the system's structural guarantee that no single individual can both originate and finalise a charge-off against bad debt.

### 2.9. Optimistic Concurrency Control on Promise Creation

Recording a promise to pay is the one write that takes an optimistic-concurrency token. A request to create a `PromiseToPay` must carry `expected_customer_version`, a non-optional field holding the `version` of the target customer that the client last observed when it read that customer's promise calendar. The server compares `expected_customer_version` to the customer's current `version`. If they do not match — because another writer has already added a promise to that customer and thereby advanced the customer's `version` since the client read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), before the new promise's own non-overlap judgement is trusted. Two clients can each judge their proposed window non-overlapping against the calendar they separately observed; OCC on the customer's `version` is the deterministic serialiser that lets only the writer holding the current version through, and the stale writer is turned away. On a successful create, the customer's `version` is incremented by one. No other endpoint takes a version field; only promise creation participates in this check.

### 2.10. Monetary Precision and Rounding

All stored monetary amounts are held in integer minor units (cents); fields ending in `_cents` are whole-cent integers and are never fractional. Where a calculation introduces a fraction — a finance charge at a monthly rate, or a forecast probability — the result is rounded **half up** to the stated precision before it is stored or returned. Finance charges and forecast projections round half up to whole cents. The collection-priority score, which is not money, rounds half up to two decimal places. Two calculations pin a *specific* rounding order that must not be rearranged: the statement finance charge rounds each per-invoice charge before summing (never sums then rounds), and the watch threshold rounds eighty percent of the limit to whole cents before comparison. These orderings are described where the calculations live, in §3.

## 3. Business Logic & Workflows

### 3.1. Opening Accounts and Issuing Invoices

The ledger begins with a **Customer**, opened by an `AR_MANAGER` who supplies the account's legal `name`, an optional `currency`, and a `credit_limit_cents`. The `currency` is one of `USD`, `EUR`, or `GBP` and defaults to `USD` when omitted; `credit_limit_cents` is an integer of at least zero and caps the total exposure the account may carry. A new customer is born with `credit_status` of `GOOD` and `collection_stage` of `CURRENT`, with `exposure_cents`, `total_open_balance_cents`, and `bad_debt_total_cents` all at zero and `manual_hold` false. Reading a single customer recomputes `exposure_cents`, `total_open_balance_cents`, and `credit_status` before responding, so the returned posture is always live. Customers may be listed and filtered by `credit_status` and by `collection_stage`.

An **Invoice** is raised by an `AR_CLERK` or an `AR_MANAGER` against a customer, identified by the `customer_id` in the payload, together with an `invoice_date`, a `due_date`, and a `face_amount_cents`. The `face_amount_cents` is the original billed amount and must be an integer of at least one. The `due_date` must be the same as or later than the `invoice_date`; a `due_date` earlier than `invoice_date` is rejected with `ERR_VALIDATION` (HTTP 422). Creation runs the credit gate of §2.7: if the customer is on `HOLD`, the invoice is refused with `ERR_CREDIT_HOLD`. On success the invoice starts in `OPEN` status with `balance_cents` equal to `face_amount_cents`, `disputed_amount_cents` zero, and `dunning_stage_index` zero, after which the customer's `exposure_cents` and `credit_status` are recomputed.

An invoice's `balance_cents` is its `face_amount_cents` less all applied payment amounts less any write-off amount; it is decremented by payment application and by write-off and restored by reversal. The `status` of an invoice is one of `OPEN`, `PARTIAL`, `DISPUTED`, `PAID`, or `WRITTEN_OFF`, with `PAID` and `WRITTEN_OFF` terminal. Reading an invoice recomputes its `aging_bucket` against the system clock before responding. Invoices may be listed and filtered by `customer_id`, by `status`, and by `aging_bucket`.

### 3.2. Aging Classification

Every invoice carries an `aging_bucket`, one of `CURRENT`, `B1_30`, `B31_60`, `B61_90`, or `B91_PLUS`, recomputed on read, on every dunning run, and during statement generation. The classification counts whole UTC days overdue: take the difference between the current clock and a reference date, divide by the number of milliseconds in a day, and floor it to a whole number of days. A paid or written-off invoice is always `CURRENT`. Otherwise, an invoice less than one day overdue is `CURRENT`; one through thirty days overdue inclusive is `B1_30`; thirty-one through sixty days inclusive is `B31_60`; sixty-one through ninety days inclusive is `B61_90`; and ninety-one or more days overdue is `B91_PLUS`. The upper edge of each band is inclusive: exactly thirty days overdue is `B1_30`, and thirty-one days is `B31_60`.

The reference date differs by purpose. For dunning and all credit decisions, the **due-date basis** is used: the reference date is the invoice's `due_date`. The statement aging report uses an alternative **invoice-date basis**, where the reference date is the invoice's `invoice_date`; because an invoice is issued no later than it is due, the invoice-date basis always reports at least as many days overdue as the due-date basis. Unless a workflow explicitly names the invoice-date basis, the due-date basis applies.

### 3.3. Applying Cash: Payments, Short-Pays, and Reversals

A **Payment** records cash received and is created by an `AR_CLERK` or `AR_MANAGER` with the remitting account's `customer_id`, the `amount_cents` received (an integer of at least one), and the `received_at` timestamp. A new payment is `UNAPPLIED`, with `applied_cents` zero and `unapplied_cents` equal to `amount_cents`. As the cash is allocated, `applied_cents` accumulates and `unapplied_cents` — the on-account remainder — is `amount_cents` minus `applied_cents`. A payment's `status` is one of `UNAPPLIED`, `PARTIALLY_APPLIED`, or `FULLY_APPLIED`; there is no separate reversed state, because reversal is tracked per application. Payments may be listed and filtered by `customer_id` and by `status`.

Manually applying cash to one invoice is exclusive to the `AR_CLERK`. The request names the target `invoice_id`, the `applied_cents` to allocate (an integer of at least one), and an optional `settle_in_full` flag. The payment must be `UNAPPLIED` or `PARTIALLY_APPLIED` and the target invoice must be `OPEN` or `PARTIAL`; an application to a payment or invoice outside those states (including a terminal `PAID`, `WRITTEN_OFF`, or fully `DISPUTED` invoice) is rejected with `ERR_INVALID_STATE` (HTTP 409). The amount allocated must not exceed the payment's `unapplied_cents` — an over-allocation is rejected with `ERR_OVER_APPLICATION` (HTTP 422). The payment and the invoice it pays must belong to the same account: if the payment's `customer_id` differs from the invoice's `customer_id`, the application is rejected with `ERR_CUSTOMER_MISMATCH` (HTTP 409). Each application creates a **PaymentApplication** linking `payment_id` to `invoice_id` and recording its `applied_cents`; it carries a `short_pay_cents` (zero unless a settle-in-full short pay is booked) and a `reversed` flag (false until un-applied).

How the application moves the invoice depends on the amount. Applying strictly between zero and the invoice's current `balance_cents` to an `OPEN` invoice advances it to `PARTIAL` and decrements `balance_cents` by the applied amount; the same partial application to an already-`PARTIAL` invoice leaves it `PARTIAL` and decrements the balance further. Applying an amount equal to the invoice's `balance_cents` settles it: the invoice moves to `PAID` and its `balance_cents` is set to zero, whether it started `OPEN` or `PARTIAL`. The `settle_in_full` path is the short-pay case: when that flag is set and the allocated amount is at most the invoice balance, the invoice is settled to `PAID`, its `balance_cents` set to zero, and the gap between the prior balance and the amount applied is booked on the application as `short_pay_cents`. Outside the settle-in-full path, an `applied_cents` that exceeds the invoice's dunnable balance is rejected with `ERR_APPLY_EXCEEDS_INVOICE` (HTTP 422); with the flag set, the amount need only be at most the dunnable balance. Each application increments the payment's `applied_cents` and recomputes `unapplied_cents`, advancing the payment from `UNAPPLIED` toward `PARTIALLY_APPLIED`, and reaching `FULLY_APPLIED` precisely when the amount applied consumes the entire remaining `unapplied_cents`. Every settlement or partial cascades into the customer: `exposure_cents`, `total_open_balance_cents`, `credit_status`, and where an invoice reaches a terminal state, `collection_stage` are recomputed.

The `AR_CLERK` may also **auto-apply** a payment's whole unapplied balance across the customer's invoices in one shot. Auto-apply walks the customer's `OPEN` and `PARTIAL` invoices oldest-aging first: ordered by `aging_bucket` with the most overdue bucket (`B91_PLUS`) first, then by `due_date` ascending, then by `created_at` ascending as the final deterministic tie-break — the invoice `id` is never used to order. Starting from the payment's `unapplied_cents` as the remaining pool, each invoice in turn takes the smaller of the pool remaining and that invoice's dunnable balance (`balance_cents` minus `disputed_amount_cents`); invoices whose dunnable balance is zero or negative are skipped, and allocation stops once the pool is exhausted. Each take creates a PaymentApplication, reduces the pool, and cascades the invoice and customer recomputations as above; any pool left over remains on account as `unapplied_cents`. The same customer-match rule applies — auto-apply only touches the remitting customer's invoices.

Reversing an application is also the `AR_CLERK`'s, and it is a compensating operation; the application named in the path must belong to the payment named in the path (otherwise `ERR_INVALID_STATE`). The target application must not already be `reversed`, else `ERR_INVALID_STATE`. Reversal marks the application `reversed`, restores the invoice's `balance_cents` by the application's `applied_cents` plus any `short_pay_cents` the application booked (so a reversed settle-in-full short pay returns the full prior balance, not merely the cash applied), reverts the invoice's status if the application had driven it to `PAID` or `PARTIAL` — the invoice returns to `OPEN` when its restored `balance_cents` is at least its `face_amount_cents`, and to `PARTIAL` otherwise — decrements the payment's `applied_cents`, and recomputes the customer's `total_open_balance_cents` and `credit_status` (and `collection_stage`). A payment that was `FULLY_APPLIED` falls back to `PARTIALLY_APPLIED`, and one that was `PARTIALLY_APPLIED` may return to `UNAPPLIED`. The governing invariant is that `total_open_balance_cents` returns to exactly its pre-application value.

### 3.4. Disputes and Deductions

A **Dispute** carves a contested amount out of an invoice. A `COLLECTIONS_AGENT` or `AR_MANAGER` raises one against an invoice named by `invoice_id`, for an `amount_cents` of at least one, classified by a `reason_code` of `PRICING`, `SHORTAGE`, `DAMAGE`, `DUPLICATE`, or `QUALITY`. The disputed amount must not exceed the invoice's dunnable balance — its `balance_cents` minus any existing `disputed_amount_cents` — or the request is rejected with `ERR_DISPUTE_EXCEEDS_BALANCE` (HTTP 422). On creation the dispute amount is added onto the invoice's `disputed_amount_cents` (so a second dispute accumulates on top of an existing one, never overwriting it) and the customer's `exposure_cents` is recomputed to exclude the now-disputed amount. When the accumulated `disputed_amount_cents` reaches the invoice's entire `balance_cents`, the invoice moves to `DISPUTED`: a fully disputed `OPEN` or `PARTIAL` invoice transitions to `DISPUTED`, and only in the `OPEN` case is its `dunning_stage_index` reset to zero because dunning is suspended while the invoice is fully disputed.

A dispute's lifecycle is cyclic, with `status` one of `OPEN`, `UNDER_REVIEW`, `RESOLVED_CREDIT`, `REJECTED`, or `WITHDRAWN`; the last three are terminal except that two of them can be reopened. It also carries a `resolution_credit_cents` (zero until resolved in the customer's favour) and a `reopen_count` (the number of times it has cycled back to review). Adjudication is the `AR_MANAGER`'s work. Starting review moves a dispute from `OPEN` to `UNDER_REVIEW` with no balance change; calling start-review on a dispute that is not `OPEN` is rejected with `ERR_INVALID_STATE`. Resolving a dispute under review supplies a `resolve_credit_cents` of at least zero (a zero credit is permitted) that must not exceed the dispute's `amount_cents` — a credit over the dispute amount is rejected with `ERR_VALIDATION`; resolution moves the dispute to `RESOLVED_CREDIT`, records that figure as `resolution_credit_cents`, decrements the invoice's `balance_cents` by the credit, removes this dispute's contested amount from the invoice's `disputed_amount_cents` (subtracting the dispute's `amount_cents`, floored at zero), and recomputes the customer's derived fields. When the resulting `balance_cents` reaches zero, the invoice is settled to `PAID`; otherwise, if the invoice had been `DISPUTED`, it leaves that state and returns to `PARTIAL` when its `balance_cents` is below its `face_amount_cents` and to `OPEN` otherwise. When a resolution credit equals the full invoice balance, the invoice itself is settled, moving `DISPUTED → PAID` with `balance_cents` and `disputed_amount_cents` both set to zero and the customer posture cascade run. Rejecting a dispute under review moves it to `REJECTED`, removes this dispute's contested amount from the invoice's `disputed_amount_cents` (subtracting the dispute's `amount_cents`, floored at zero), restores the invoice's dunnable balance, and recomputes the customer's `exposure_cents` and `credit_status`; where the rejected dispute had covered the full balance, the invoice leaves `DISPUTED` — returning to `OPEN` when its `balance_cents` is at least its `face_amount_cents` and to `PARTIAL` when it is below (because the invoice had been partially paid) — with its dunnable balance equal to its balance again. Rejecting a dispute that is not `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`.

A `COLLECTIONS_AGENT` (the role that may withdraw, regardless of which operator raised the dispute, since `X-User-ID` ownership is never checked) may **withdraw** a dispute while it is `OPEN` or `UNDER_REVIEW`, moving it to `WITHDRAWN`; withdrawal removes this dispute's contested amount from the invoice's `disputed_amount_cents` (subtracting the dispute's `amount_cents`, floored at zero), restores the invoice's dunnable balance, and recomputes the customer's `exposure_cents`, conserving the identity that the dunnable balance plus the disputed amount is unchanged across the withdraw. A withdraw that had covered the full balance likewise returns the invoice out of `DISPUTED` — to `OPEN` when its `balance_cents` is at least its `face_amount_cents` and to `PARTIAL` otherwise. Withdrawing a dispute that is neither `OPEN` nor `UNDER_REVIEW` is rejected with `ERR_INVALID_STATE`. Finally, the `AR_MANAGER` may **reopen** a dispute that is `RESOLVED_CREDIT` or `REJECTED` (any other status is rejected with `ERR_INVALID_STATE`), provided the underlying invoice is not in `PAID` or `WRITTEN_OFF` (otherwise `ERR_INVALID_STATE`); reopening moves the dispute back to `UNDER_REVIEW`, increments `reopen_count`, resets `resolution_credit_cents` to zero, adds the dispute amount back onto the invoice's `disputed_amount_cents`, moves the invoice to `DISPUTED` when that disputed amount now equals its `balance_cents` and the invoice was `OPEN` or `PARTIAL`, and recomputes the customer's `exposure_cents`.

### 3.5. Promises to Pay

A **PromiseToPay** is a customer's structured commitment, recorded by a `COLLECTIONS_AGENT` for a named `customer_id`. It states a `promised_amount_cents` of at least one and a half-open coverage window running from `coverage_start` inclusive to `coverage_end` exclusive — the promised payment is due strictly before `coverage_end`, which must be strictly after `coverage_start` (otherwise `ERR_VALIDATION`). A promise's `status` is one of `ACTIVE`, `KEPT`, `BROKEN`, or `CANCELLED`, beginning `ACTIVE`, and it tracks `applied_payment_cents`, the payments received within its window credited toward the commitment. Promises may be listed and filtered by `customer_id` and by `status`.

Two guards protect promise creation. First, a new `ACTIVE` promise's window must not overlap any other `ACTIVE` promise window for the same customer; abutting windows where one ends exactly as the next begins are allowed, but any true overlap is rejected with `ERR_PROMISE_WINDOW_OVERLAP` (HTTP 409). Second, creation participates in the optimistic-concurrency check of §2.9: the request carries `expected_customer_version`, and a mismatch with the customer's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); a successful create increments the customer's `version` by one and recomputes `collection_stage`.

A `COLLECTIONS_AGENT` may **cancel** an `ACTIVE` promise, moving it to `CANCELLED` with no posture change. Either an `AR_MANAGER` or a `COLLECTIONS_AGENT` may trigger a system **evaluation** of a promise against the clock. Evaluation only acts on an `ACTIVE` promise once the clock is at or past `coverage_end`; called on an `ACTIVE` promise whose `coverage_end` the clock has not yet reached, evaluation is a successful no-op that leaves the promise `ACTIVE` and returns it with HTTP 200. When it does act: if `applied_payment_cents` (recomputed from the customer's in-window payments before judging) is at or above `promised_amount_cents`, the promise is `KEPT`, and if the customer then has no other broken promise and nothing overdue, `collection_stage` is recomputed toward `CURRENT`; if a shortfall remains, the promise is `BROKEN`, which cascades the customer one step deeper — advancing `collection_stage` from `DUNNING` toward `COLLECTIONS` and setting `credit_status` to `WATCH` if it was `GOOD`. That break-induced `WATCH` is sticky: it raises a `GOOD` posture to `WATCH` and a subsequent exposure-only recompute (§2.7) will not silently drop the customer back to `GOOD` while the broken promise stands unredeemed, though a `HOLD` from exposure or a manual hold still overrides it. Both evaluate and cancel guard their target with a domain-specific state check distinct from the generic one: calling either on a promise that is not `ACTIVE` is rejected with `ERR_PROMISE_ALREADY_RESOLVED` (HTTP 409), not `ERR_INVALID_STATE`.

### 3.6. Write-Offs and Bad Debt

A **WriteOff** charges an uncollectible balance off the books. A `COLLECTIONS_AGENT` or `AR_MANAGER` creates a pending write-off against an invoice named by `invoice_id`, for an `amount_cents` of at least one, classified by a `reason_code` of `UNCOLLECTIBLE`, `SETTLEMENT`, `BANKRUPTCY`, or `SMALL_BALANCE`. The amount must equal the invoice's dunnable balance exactly — its `balance_cents` minus its `disputed_amount_cents` — or the request is rejected with `ERR_WRITEOFF_AMOUNT_MISMATCH` (HTTP 422). A write-off cannot be raised, nor later approved, against an invoice that has a dispute in `OPEN` or `UNDER_REVIEW`; such an attempt is rejected with `ERR_DISPUTE_BLOCKS_WRITEOFF` (HTTP 409). A created write-off is born pending, with `approved` false; creating it changes no balances.

Approval is the `AR_MANAGER`'s, and it is where bad debt is realised. Approval is subject to the segregation-of-duties rule of §2.8: the approving `X-User-ID` must differ from the creating one, else `ERR_SOD_VIOLATION`. The write-off must still be pending — re-approving one already `approved`, or one whose target invoice is no longer `OPEN` or `PARTIAL`, is rejected with `ERR_INVALID_STATE`. The target invoice must be `OPEN` or `PARTIAL` and must still have no dispute in `OPEN` or `UNDER_REVIEW`, and the write-off's `amount_cents` must still equal `balance_cents` minus `disputed_amount_cents`. These conditions are evaluated in the §3.10 order: the state guard (`ERR_INVALID_STATE`) first, then the dispute block (`ERR_DISPUTE_BLOCKS_WRITEOFF`), then segregation of duties (`ERR_SOD_VIOLATION`), then the amount match (`ERR_WRITEOFF_AMOUNT_MISMATCH`). On approval the write-off's `approved` becomes true, the invoice moves to `WRITTEN_OFF` with `balance_cents` set to zero, and a cascade fires on the customer: `bad_debt_total_cents` is incremented by the written-off amount, then `exposure_cents` is recomputed, then `credit_status` is re-evaluated, and finally `collection_stage` is advanced toward `WRITEOFF`.

### 3.7. Dunning: Sequences, Runs, Notices, and Pauses

Collections pressure is applied through dunning. An `AR_MANAGER` defines a **DunningSequence** with a `name`, an `active` flag (defaulting to true, marking whether new runs use this sequence), and an ordered `steps` array. Each step is an object of `min_days_overdue` (an integer), `channel` (one of `EMAIL`, `PHONE`, `LETTER`, or `SMS`), and `severity` (an integer); the steps must be non-empty and their `min_days_overdue` must strictly increase from one step to the next. A step's position in the array — counted from one, identical to the `step_index` below — is the `dunning_stage_index` an invoice reaches once it ages into that step. A malformed `steps` array (missing, not a list, empty, or with a step missing a key or carrying a non-integer `min_days_overdue`/`severity`) yields `ERR_INVALID_REQUEST`; a `channel` outside its enum yields `ERR_INVALID_ENUM`; and a `min_days_overdue` that does not strictly increase yields `ERR_VALIDATION`.

A `COLLECTIONS_AGENT` triggers a **dunning run** against a customer's overdue invoices by naming the `customer_id` and the `sequence_id` of the policy to apply (validated for existence in that left-to-right order). The run considers the customer's non-terminal invoices that are not fully `DISPUTED` (a fully disputed invoice has dunning suspended) and whose due-date-basis aging is `B1_30` or worse; an active dunning pause for the customer (any pause whose window covers the clock) suppresses the whole run, so no notice is emitted for any of that customer's invoices while a pause is active. For each remaining candidate the run selects the highest step whose `min_days_overdue` the invoice has reached on the due-date basis; an invoice that has not yet reached the first step emits no notice. The run emits a **DunningNotice** for each invoice that fires a step. Each notice records the targeted `invoice_id`, the `sequence_id` that produced it, the 1-based `step_index` of the step that fired, the `severity` copied from that step, and a computed `priority_score`. A run advances each targeted invoice's `dunning_stage_index` to that 1-based `step_index`, and when it emits the first notice for an overdue invoice it moves the customer's `collection_stage` from `CURRENT` to `DUNNING`; this requires at least one invoice to have reached `B1_30` or worse with no active pause suppressing it. The run responds with HTTP 201 and an array of the emitted notice objects (an empty array when nothing fired). Notices for an invoice can be listed under that invoice, and notices produced by a sequence can be listed under that sequence.

The **priority score** ranks candidate invoices so a run chases the most valuable targets first. For each candidate it is the sum of three weighted terms less a promise discount. The first term weights the invoice's dunnable balance at one times the smaller of two values: the dunnable balance divided by one hundred thousand, and ten — capping the balance contribution at ten. The second term weights aging at two times an age weight keyed by the invoice's due-date-basis `aging_bucket`, where `CURRENT` is 0, `B1_30` is 1, `B31_60` is 2, `B61_90` is 3, and `B91_PLUS` is 4. The third term weights the customer's `collection_stage` at one and one-half times a stage weight, where `CURRENT` is 0, `DUNNING` is 1, `COLLECTIONS` is 2, and `WRITEOFF` is 0. From that sum, three is subtracted when the customer has an `ACTIVE` promise to pay whose window covers today, and nothing is subtracted otherwise. The dunnable balance used here is `balance_cents` minus `disputed_amount_cents`. The final score is rounded half up to two decimal places.

A `COLLECTIONS_AGENT` or `AR_MANAGER` may schedule a **DunningPause** to suppress dunning for a customer over a window. The pause names the `customer_id`, a `pause_start`, and a `pause_end`, defining a closed window in which notices are suppressed on both endpoints, where `pause_end` must be the same as or later than `pause_start`. A new pause must keep a one-day buffer from every existing pause for that customer: any two windows for the same customer whose gap is one day or less, inclusive, collide, and the new pause is rejected with `ERR_PAUSE_WINDOW_CONFLICT` (HTTP 409). A pause's `status` is derived from the clock: `SCHEDULED` while the clock is before `pause_start`, `ACTIVE` while the clock is between `pause_start` and `pause_end` inclusive, and `EXPIRED` once the clock is past `pause_end`. Pauses for a customer can be listed under that customer.

### 3.8. Statements

A **Statement** is cut for a customer at a period close by an `AR_MANAGER` or `AR_CLERK`, who supplies the `period_end`. The period being closed runs from the most recent prior statement's `period_end` (exclusive) up to and including this `period_end`; the prior statement is the customer's latest one whose `period_end` is at or before this one, and when none exists the period has no lower bound and covers everything up to and including `period_end`. The statement computes four figures. Its `opening_balance_cents` is the customer's `total_open_balance_cents` as of the prior statement's `period_end`, captured as the snapshot of that quantity taken when the prior statement was cut (zero when there is no prior statement). Its `new_charges_cents` is the sum of `face_amount_cents` over invoices whose `invoice_date` falls within the period (after the prior `period_end`, through this `period_end` inclusive). Its `finance_charge_cents` is the per-invoice finance charge summed across the customer's overdue invoices, computed as follows: for each invoice whose invoice-date-basis aging is worse than `CURRENT` and whose `status` is `OPEN`, `PARTIAL`, or `DISPUTED`, take its dunnable balance (`balance_cents` minus `disputed_amount_cents`), multiply by the monthly rate of one and one-half percent, and round that product half up to whole cents *for that invoice*; the finance charge is the integer sum of those per-invoice roundings. This per-invoice-then-sum order is authoritative — summing first and rounding once is explicitly not used and would yield a different total when several invoices each carry a half-cent. The statement's `closing_balance_cents` is the opening balance plus new charges plus the finance charge, less the payments whose `received_at` falls within the period (after the prior `period_end`, through this `period_end` inclusive). Statements for a customer can be listed under that customer, and a single statement can be fetched by id.

### 3.9. Cash Forecasting

The cash forecast is an on-demand projection — never stored — of the cash a customer is expected to yield over a horizon. The forecasting read names, as query parameters, the `customer_id` to project, a `horizon_days` (an integer between 1 and 365 inclusive; missing, non-integer, or out of range is `ERR_VALIDATION`), and a `method` of `EXPECTED` or `CONSERVATIVE` (a missing `method` is `ERR_VALIDATION`, while a present `method` outside those two members is `ERR_INVALID_ENUM`); a missing `customer_id` is `ERR_VALIDATION`. The result is an object carrying the computed `projected_cents`, the ephemeral `id` and `created_at` of §2.4, and the request's `customer_id`, `horizon_days`, and `method` echoed back. The horizon end is the current clock plus `horizon_days` whole days. The candidates are the customer's invoices in `OPEN`, `PARTIAL`, or `DISPUTED` whose dunnable balance (`balance_cents` minus `disputed_amount_cents`) is positive; already-overdue invoices are candidates too, because the forecast measures cash still to be recovered rather than new billings.

The two methods diverge in how each candidate contributes. Under `EXPECTED`, an invoice is "covered" when some `ACTIVE` promise's half-open window from `coverage_start` to `coverage_end` both contains the invoice's `due_date` and ends at or before the horizon end; a covered invoice contributes the smaller of that promise's `promised_amount_cents` and the invoice's dunnable balance, while an uncovered invoice contributes nothing, and each `ACTIVE` promise covers at most one matching invoice so nothing is double-counted. The `EXPECTED` method is promise-driven and ignores aging decay. Under `CONSERVATIVE`, promises are ignored and each candidate contributes its dunnable balance multiplied by a collection probability keyed to its due-date-basis aging bucket — `CURRENT` collects at full value, `B1_30` at ninety percent, `B31_60` at seventy percent, `B61_90` at forty percent, and `B91_PLUS` at ten percent. Under either method the sum of contributions is rounded half up to whole cents to yield `projected_cents`.

### 3.10. Validation Ordering and the System Clock

When several checks could fail one request, they are evaluated in a fixed priority so the reported error is deterministic. Authentication comes first: a missing or malformed header yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Existence is then checked — every path and body id (customer, invoice, payment, dispute, sequence, promise) must resolve, left to right, else `ERR_NOT_FOUND` — followed by request well-formedness, where a missing required field, a `null` for a required field, malformed JSON, a body that is not a JSON object, or a field of the wrong JSON type (a non-integer where an integer is required, a non-string where a string is required, or an empty/blank string) yields `ERR_INVALID_REQUEST`, and an enum field carrying a value outside its declared members yields `ERR_INVALID_ENUM`. A field that is well-formed in type but violates a value constraint — an integer below its stated minimum, a `due_date` before its `invoice_date`, a `coverage_end` not after `coverage_start`, a `pause_end` before `pause_start`, an out-of-range `horizon_days`, or a resolve credit above the dispute amount — yields `ERR_VALIDATION` rather than `ERR_INVALID_REQUEST`. Only then are state and business rules evaluated: the generic transition guard `ERR_INVALID_STATE` (which does not govern promise evaluate or cancel — those use `ERR_PROMISE_ALREADY_RESOLVED` instead), the promise OCC check `ERR_STALE_VERSION`, the write-off dispute block `ERR_DISPUTE_BLOCKS_WRITEOFF`, the segregation-of-duties check `ERR_SOD_VIOLATION`, the payment customer-match `ERR_CUSTOMER_MISMATCH`, the dispute ceiling `ERR_DISPUTE_EXCEEDS_BALANCE`, the promise-window overlap `ERR_PROMISE_WINDOW_OVERLAP`, the pause-window buffer `ERR_PAUSE_WINDOW_CONFLICT`, the over-application and over-invoice ceilings `ERR_OVER_APPLICATION` and `ERR_APPLY_EXCEEDS_INVOICE`, the write-off amount match `ERR_WRITEOFF_AMOUNT_MISMATCH`, the credit gate `ERR_CREDIT_HOLD`, and last the promise-resolved guard `ERR_PROMISE_ALREADY_RESOLVED`. This ordering means that, for instance, an unauthenticated caller never learns whether a resource exists, and a forbidden role never learns whether its payload was valid.

So that aging and promise evaluation can be exercised deterministically, an `AR_MANAGER` has an administrative test-driving capability that sets the server's current UTC instant by supplying a target `to_iso8601` value. Every subsequent aging-bucket computation and every comparison against a promise's `coverage_end` uses this clock.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Because manually applying cash mints a new `PaymentApplication`, that operation returns `201 Created`; a dunning run, which mints new `DunningNotice` records, likewise returns `201 Created` (with an array body). Operations that modify an existing resource — including state transitions, holds, reversals, approvals, evaluations, and auto-apply (which returns the updated payment) — return a `200 OK` status code. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ar/customers` | Create a customer account with a credit limit | AR_MANAGER |
| GET | `/ar/customers/{id}` | Fetch a customer with computed exposure, posture, balances | AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR |
| GET | `/ar/customers` | List customers (paginated, filterable) | AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR |
| POST | `/ar/customers/{id}/hold` | Place a manual credit hold | AR_MANAGER |
| POST | `/ar/customers/{id}/release-hold` | Release a manual credit hold | AR_MANAGER |
| GET | `/ar/customers/{id}/statements` | List statements cut for a customer | AR_MANAGER, AR_CLERK, AUDITOR |
| GET | `/ar/customers/{id}/dunning-pauses` | List dunning pauses for a customer | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| POST | `/ar/invoices` | Create an invoice; runs the credit check | AR_CLERK, AR_MANAGER |
| GET | `/ar/invoices/{id}` | Fetch one invoice with computed balance and aging | AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR |
| GET | `/ar/invoices` | List invoices, filterable by customer/status/aging | AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR |
| GET | `/ar/invoices/{id}/disputes` | List disputes raised against an invoice | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| GET | `/ar/invoices/{id}/write-offs` | List write-offs booked against an invoice | AR_MANAGER, AUDITOR |
| GET | `/ar/invoices/{id}/payment-applications` | List applications posted to an invoice | AR_MANAGER, AR_CLERK, AUDITOR |
| GET | `/ar/invoices/{id}/dunning-notices` | List dunning notices emitted for an invoice | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| POST | `/ar/payments` | Record a cash receipt for a customer | AR_CLERK, AR_MANAGER |
| GET | `/ar/payments/{id}` | Fetch a payment with applied/unapplied split | AR_MANAGER, AR_CLERK, AUDITOR |
| GET | `/ar/payments` | List payments, filterable by customer | AR_MANAGER, AR_CLERK, AUDITOR |
| POST | `/ar/payments/{id}/applications` | Apply part of a payment to one invoice (short-pay supported) | AR_CLERK |
| POST | `/ar/payments/{id}/auto-apply` | Auto-apply the unapplied balance via the oldest-aging-first waterfall | AR_CLERK |
| GET | `/ar/payments/{id}/applications` | List applications of a payment | AR_MANAGER, AR_CLERK, AUDITOR |
| POST | `/ar/payments/{id}/applications/{appId}/reverse` | Reverse (un-apply) one application | AR_CLERK |
| POST | `/ar/disputes` | Raise a dispute/deduction against an invoice | COLLECTIONS_AGENT, AR_MANAGER |
| GET | `/ar/disputes/{id}` | Fetch a dispute | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| POST | `/ar/disputes/{id}/start-review` | Move a dispute to under review | AR_MANAGER |
| POST | `/ar/disputes/{id}/resolve` | Resolve a dispute with a credit | AR_MANAGER |
| POST | `/ar/disputes/{id}/reject` | Reject a dispute; restore the invoice balance | AR_MANAGER |
| POST | `/ar/disputes/{id}/reopen` | Reopen a resolved/rejected dispute | AR_MANAGER |
| POST | `/ar/disputes/{id}/withdraw` | Withdraw a dispute | COLLECTIONS_AGENT |
| POST | `/ar/promises` | Record a promise to pay | COLLECTIONS_AGENT |
| GET | `/ar/promises/{id}` | Fetch a promise | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| GET | `/ar/promises` | List promises, filterable by customer | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| POST | `/ar/promises/{id}/cancel` | Cancel an active promise | COLLECTIONS_AGENT |
| POST | `/ar/promises/{id}/evaluate` | Evaluate a promise against the clock and credited payments | AR_MANAGER, COLLECTIONS_AGENT |
| POST | `/ar/write-offs` | Create a pending write-off against an invoice | COLLECTIONS_AGENT, AR_MANAGER |
| POST | `/ar/write-offs/{id}/approve` | Approve a write-off (segregation of duties enforced) | AR_MANAGER |
| GET | `/ar/write-offs/{id}` | Fetch a write-off | AR_MANAGER, AUDITOR |
| POST | `/ar/dunning-sequences` | Define an ordered dunning policy | AR_MANAGER |
| GET | `/ar/dunning-sequences/{id}` | Fetch a dunning sequence | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| GET | `/ar/dunning-sequences/{id}/notices` | List notices produced by a sequence | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| POST | `/ar/dunning-runs` | Run a sequence against a customer's overdue invoices | COLLECTIONS_AGENT |
| POST | `/ar/dunning-pauses` | Schedule a dunning suppression window | COLLECTIONS_AGENT, AR_MANAGER |
| POST | `/ar/customers/{id}/statements` | Cut a statement at a period end, with finance charge | AR_MANAGER, AR_CLERK |
| GET | `/ar/statements/{id}` | Fetch a statement | AR_MANAGER, AR_CLERK, AUDITOR |
| GET | `/ar/cash-forecast` | Compute a cash-collection forecast for a customer | AR_MANAGER, COLLECTIONS_AGENT, AUDITOR |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC instant | AR_MANAGER |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DISPUTE_BLOCKS_WRITEOFF` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_CUSTOMER_MISMATCH` | 409 Conflict |
| `ERR_DISPUTE_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_PROMISE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PAUSE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OVER_APPLICATION` | 422 Unprocessable Entity |
| `ERR_APPLY_EXCEEDS_INVOICE` | 422 Unprocessable Entity |
| `ERR_WRITEOFF_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 402 Payment Required |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
| `ERR_PROMISE_ALREADY_RESOLVED` | 409 Conflict |
