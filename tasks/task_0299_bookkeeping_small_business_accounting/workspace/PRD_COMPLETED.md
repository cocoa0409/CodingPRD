# Bookkeeping & Small-Business Accounting API — Product Requirements Document

## 1. Introduction

Small businesses live and die by the integrity of their books. A bookkeeper records the daily flow of money, an accountant posts and reconciles it, and at month-end someone must be able to swear that debits equal credits, that the bank statement ties out, and that the sales-tax and 1099 obligations are correct. This API is the system of record for that work. It maintains a per-company chart of accounts, ingests bank-feed transactions for categorization, captures customer invoices and vendor bills, drives the bank-reconciliation and monthly-close workflows, tracks sales and use tax, and produces the financial statements and 1099 totals that flow into tax filings.

The system is built around a double-entry general ledger: every economic event ultimately resolves into a balanced journal entry, and the platform guarantees the trial-balance invariant — total posted debits always equal total posted credits — across the entire lifecycle. Because accounting errors compound and because regulators and lenders rely on these numbers, the API enforces a strict separation of duties between the person who drafts an entry and the person who posts it, locks closed accounting periods against casual edits, and treats every balance-affecting operation as a cascade that keeps account balances, company-level derived totals, and reconciliation state mutually consistent. This document specifies the entities, the state machines that govern their lifecycles, the calculation rules for taxes and balances, the validation order, and the full HTTP contract.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted under the `/ledger` prefix; there is no nested ownership chain in the URL space — entities are peers linked by foreign-key fields carried in request bodies.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are valid but the role is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly four roles: `Owner`, `Accountant`, `Bookkeeper`, and `Auditor`. The `Owner` is the business superuser — the only role permitted to create a company, configure it, reopen a closed period, and void a posted journal entry — and may additionally perform everything an `Accountant` or `Bookkeeper` can. The `Accountant` posts journal entries, approves and pays bills, runs the monthly close (both the begin-close and post-close steps are exclusive to this role), reconciles bank accounts, voids and sends invoices, and reverses payments. The `Bookkeeper` handles day-to-day data entry: drafting journal entries and their lines, categorizing bank-feed transactions, drafting and sending invoices, recording invoice payments, and drafting bills; a `Bookkeeper` may not post journal entries, approve bills, run the close, or finalize a reconciliation. The `Auditor` has read-only access to every resource, including financial statements and 1099 totals, and may not mutate anything.

For all four roles, `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity. The server may record it where a workflow demands — most notably, when a journal entry is drafted, the drafter's `X-User-ID` is stored on that entry as `created_by_user_id` so the maker-checker rule can later compare it — but the server never treats `X-User-ID` as the `id` of any stored record and performs no ownership lookup against it. The single place this recorded identifier is consulted is the segregation-of-duties check described in §3.4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range numeric values are clamped rather than rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Almost every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every subsequent modification of the resource. The `version` field is an integer that begins at 1 on creation and increments by one on every mutation; it underpins the optimistic-concurrency controls described in §2.7.

One entity is the exception to this convention. A `JournalLine` is an immutable detail row attached to a journal entry and carries only `id` and `created_at` — it has no `updated_at` field and no `version` field, because once written it is never modified in place (a correction is made by reversing and re-posting the parent entry, never by editing a line). Every other entity — `Company`, `Account`, `AccountingPeriod`, `JournalEntry`, `BankAccount`, `BankFeedTransaction`, `Reconciliation`, `Customer`, `Invoice`, `InvoicePayment`, `Vendor`, `Bill`, and `TaxRate` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

Foreign-key references travel in request bodies as identifier fields rather than through nested URL paths. When a request both names resources in its path and references resources in its body, the server validates them left-to-right: the path identifier is resolved first, and the first identifier in the path that does not correspond to an existing resource produces a 404 before any body-level reference is examined. The 404's `error_id` is keyed on the kind of identifier that missed, exactly as for body references (§3.11): a path `accountId` that resolves to no account surfaces `ERR_ACCOUNT_NOT_FOUND`, while a missing path identifier for any other resource (company, period, journal entry, journal line, bank account, transaction, reconciliation, customer, invoice, payment, vendor, bill, or tax rate) surfaces `ERR_NOT_FOUND`.

### 2.5. The Double-Entry Ledger and Posted Balances

Every account belongs to one of five types — `ASSET`, `LIABILITY`, `EQUITY`, `REVENUE`, or `EXPENSE` — recorded in `account_type`, and this type fixes the account's normal balance side. Each `Account` exposes a computed `posted_balance_cents`: a signed running balance, in integer cents with no rounding, derived only from `JournalLine` rows whose parent `JournalEntry` is in `POSTED` status. For each such posted line touching the account, the system takes the natural amount as the line's `debit_cents` minus its `credit_cents`; for an `ASSET` or `EXPENSE` account the signed contribution equals that natural amount, while for a `LIABILITY`, `EQUITY`, or `REVENUE` account the signed contribution is the negation of that natural amount. The `posted_balance_cents` is the sum of these signed contributions, recomputed from scratch on every posting and on every reversal cascade.

At the company level, `trial_balance_status` is a computed enum that is `BALANCED` when the total posted debit cents equal the total posted credit cents summed across all of the company's accounts, and `OUT_OF_BALANCE` otherwise. Because balanced journal entries are the only way debits and credits enter the ledger, the system is expected to remain `BALANCED` in normal operation; the close workflow explicitly re-checks this invariant before it will finalize a period.

A read endpoint exposes the same balance arithmetic in two variants. The **posted** variant is the default and is exactly what the stored `posted_balance_cents` holds: it counts only `POSTED` entries. The **projected** variant, requested with the `include_drafts` query flag set to true, runs the identical signed-sum arithmetic but over lines whose parent entry is in either `POSTED` or `DRAFT` status — that is, draft entries are projected as if they had been posted. The two variants diverge precisely when an unposted draft touches the account; otherwise they agree. The balance read returns both `account_id` and the two figures `posted_balance_cents` and `projected_balance_cents`. The projected figure is only actually computed over drafts when the request supplies `include_drafts=true` (the literal string, case-insensitive); when the flag is absent or any other value, the response simply echoes the posted figure into `projected_balance_cents` so the two are equal.

### 2.6. Cascading Recomputation, Reversal, and `updated_at`/`version` Semantics

Balance-affecting operations are never isolated point mutations; they propagate. Posting a journal entry recomputes the `posted_balance_cents` of every account its lines reference and then recomputes the owning company's `trial_balance_status`. Voiding a posted entry does not erase it: the system creates a compensating `REVERSAL` journal entry — `source` set to `REVERSAL`, `reverses_journal_entry_id` pointing at the original — in which every line's debit and credit are swapped, and posts that reversal immediately; the reversal's posting in turn recomputes the affected account balances and the company's trial-balance status. The arithmetic guarantee is that an original entry plus its reversal leave total posted debits minus total posted credits unchanged, so the trial-balance invariant survives every void.

Whenever a server-managed mutation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented — this is true for derived fields as well as input fields. In particular, when the closing cascade recomputes a company's retained-earnings total, or when finalizing a reconciliation advances a bank account's reconciled state, the affected parent resource's `version` advances, which is what makes the optimistic-concurrency checks in §2.7 meaningful.

### 2.7. Optimistic Concurrency Control

Two operations are guarded by optimistic concurrency control because they advance a parent resource whose prior state a client may have read and cached.

Opening a new accounting period advances the company's `current_period_id` and increments `Company.version`. The open request must therefore carry `expected_company_version` as a required field holding the company `version` the client last observed. If that value does not match the company's current `version` — because another open has already advanced it since the client read it — the create is rejected with `ERR_STALE_VERSION` at HTTP 412. The client's belief about which period is current is stale, and the system refuses to let it open a period off an outdated view.

Finalizing a reconciliation advances the bank account's `last_reconciled_statement_balance_cents` and `last_reconciled_through` and increments `BankAccount.version`. The finalize request must carry `expected_bank_account_version` holding the bank-account `version` the client last observed. If that value does not match the bank account's current `version` — because another reconciliation already advanced the bank account's reconciled state — the finalize is rejected with `ERR_STALE_VERSION` at HTTP 412, since the client's opening-balance view is no longer current. Beyond these two required guards, the only other endpoint that consults a version is configuring a company (§3.1), which accepts an *optional* `expected_company_version` and, when that field is present, rejects a mismatch with `ERR_STALE_VERSION` at HTTP 412; when it is omitted the configure proceeds with no concurrency check. No endpoint other than these three takes a version field, and endpoints not named here perform no optimistic-concurrency check.

### 2.8. Monetary Precision and Tax Rounding

All monetary values are stored and exchanged as **integer cents** in the company's `base_currency`; there is no fractional-cent representation. Plain ledger arithmetic — summing line amounts, computing posted balances, computing a reconciliation difference — is exact integer arithmetic with no rounding.

Tax and discount arithmetic is the exception that requires rounding, and the rounding method is **round half up** to a whole number of cents. Tax rates are expressed in basis points (`rate_bps`), where one basis point is one ten-thousandth, so a percentage is recovered by dividing the basis-point figure by 10,000. Two firm rules govern every tax computation. First, rounding is applied **per line and then summed**, never on an aggregate base: each taxable line's tax is rounded to whole cents on its own before the lines are added together, and this ordering is pinned. Second, discount and tier arithmetic round half up at each pinned step as described in §3.6. Wherever a fractional cent would otherwise arise, round half up to the nearest cent.

### 2.9. The Accounting Period and the Open-Period Lock

Posting and most economic activity are gated on an `OPEN` accounting period. A `Company` tracks the single period currently open for posting in `current_period_id`, which is null until the first period is opened and is advanced by the close-then-open cycle. Periods are contiguous and non-overlapping: each period is a half-open interval from an inclusive `start_date` to an exclusive `end_date`, written `[start_date, end_date)`, and a new period's `start_date` must equal the prior closed period's `end_date` so that no gap or overlap can form. A period progresses through the states `OPEN`, `CLOSING`, and `CLOSED`, and a closed period may be reopened back to `OPEN` for late adjustments.

Operations that write into the ledger — posting a journal entry, categorizing a bank-feed transaction, sending an invoice, approving a bill, recording a bill payment — require the company's current period to be `OPEN` and require the relevant entity date to fall within that period's half-open interval; otherwise they are rejected with `ERR_PERIOD_NOT_OPEN`. Compensating operations that run against a period that has since closed — voiding a journal entry, voiding an invoice, reversing an invoice payment — are rejected with `ERR_PERIOD_CLOSED`; only an `Owner` reopening the period can unlock it for such corrections.

### 2.10. Sales Tax, Use Tax, and Effective Rate Windows

A `TaxRate` records a `rate_bps` for a `jurisdiction` that applies over the half-open window from inclusive `effective_from` to exclusive `effective_to`. Within one company, the effective windows for a given jurisdiction must not overlap; an attempt to create a rate whose window overlaps an existing rate for the same jurisdiction is rejected with `ERR_TAX_RATE_OVERLAP`. When an invoice is sent, the system captures into `applied_tax_rate_bps` the rate effective on the invoice's `issue_date` for the customer's `tax_jurisdiction` (zero if no rate is in effect). When a bill is approved, the system captures into the bill's `applied_tax_rate_bps` the use-tax rate effective on the `bill_date` for the company's default jurisdiction. Once captured at send/approve time, the applied rate is frozen on that document even if the underlying `TaxRate` later changes.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Company and Its Chart of Accounts

A new engagement begins when an `Owner` creates a `Company`, supplying its `legal_name` and optionally its `base_currency` (defaulting to `USD`) and `accounting_basis`. The `accounting_basis` is either `ACCRUAL` or `CASH`, defaults to `ACCRUAL`, and is consequential: it selects which 1099 total variant the system reports and the revenue-recognition basis. On creation the company's `version` is 1, its `retained_earnings_cents` is 0, its `trial_balance_status` is `BALANCED`, and its `current_period_id` is null. Because the equity account that will absorb net income does not yet exist at company-creation time, the `retained_earnings_account_id` may be supplied later: an `Owner` can reconfigure the company — setting `retained_earnings_account_id` and/or `accounting_basis` — once the equity account has been created, and that reconfiguration increments `Company.version` by one. The configure request may optionally carry `expected_company_version`; when present it must equal the company's current `version` or the request is rejected with `ERR_STALE_VERSION` at HTTP 412, and when omitted no concurrency check is performed. A company may be looked up directly or listed with filters on `current_period_id` or `retained_earnings_account_id`.

An `Owner` or `Accountant` builds the chart of accounts by creating `Account` records, each carrying the owning `company_id`, a `code`, a display `name`, and an `account_type`. The `code` must be unique per company among all accounts that are not `ARCHIVED`; a collision with a live account's code is rejected with `ERR_DUPLICATE_ACCOUNT_CODE`. An account may be a sub-account of another by supplying `parent_account_id`, which is self-referential and defaults to null for a top-level account; a sub-account must share its parent's `account_type`, and a mismatch is rejected with `ERR_ACCOUNT_TYPE_MISMATCH`. The `is_cash` flag (default false) marks accounts that back a bank account and must be an `ASSET`. A new account is born `ACTIVE` with `posted_balance_cents` of 0; its `status` may later be moved to `ARCHIVED`, and attempting to archive an account that is already `ARCHIVED` is rejected as an invalid state transition. A missing or malformed required field on account creation is rejected with `ERR_INVALID_REQUEST`. Accounts can be fetched individually, or listed and filtered by `company_id`, `parent_account_id`, `account_type`, or `status`. A computed balance for any account is available as its own read, optionally with `include_drafts` to obtain the projected figure described in §2.5.

### 3.2. Opening, Working, and Closing an Accounting Period

After accounts exist, an `Owner` or `Accountant` opens the first `AccountingPeriod` for a company by supplying `company_id`, a `period_label` (informational, e.g. `2026-01`), `start_date`, `end_date`, and `expected_company_version` (see §2.7). A newly opened period is `OPEN`, becomes the company's `current_period_id`, and is seeded with a `close_checklist`: an array of four items keyed `BANK_RECONCILED`, `AR_REVIEWED`, `AP_REVIEWED`, and `SALES_TAX_REVIEWED`, every one of them carrying a `done` flag initialized to false. A subsequent period's `start_date` must equal the prior closed period's `end_date`, and a violation is rejected with `ERR_PERIOD_NOT_CONTIGUOUS`. Periods may be fetched directly or listed and filtered by `company_id`, `status`, or `closing_journal_entry_id`. Throughout the month, any `Owner`, `Accountant`, or `Bookkeeper` marks checklist progress by naming an `item` and the `done` value to set on it.

When the books are ready, an `Accountant` begins the close, transitioning the period from `OPEN` to `CLOSING`. Three preconditions are enforced, each with its own rejection: all four `close_checklist` items must be marked done, or the request fails with `ERR_CHECKLIST_INCOMPLETE`; no `DRAFT` journal entry may exist whose `period_id` is this period, or the request fails with `ERR_OPEN_DRAFT_ENTRIES`; and no reconciliation in `IN_PROGRESS` status may exist on any bank account of the company, or the request fails with `ERR_RECONCILIATION_IN_PROGRESS`.

From `CLOSING`, the `Accountant` posts the close, transitioning the period to `CLOSED`. This is permitted only when the company's `trial_balance_status` is `BALANCED`; an out-of-balance ledger is rejected with `ERR_TRIAL_BALANCE_OUT_OF_BALANCE`. Posting the close drives a three-hop cascade. First, the system creates a `CLOSING`-source journal entry that debits each `REVENUE` account by its posted balance and credits each `EXPENSE` account by its posted balance, with the net carried to the company's `retained_earnings_account_id`, then posts that entry and records its id as the period's `closing_journal_entry_id`. If the period has no `REVENUE` or `EXPENSE` activity (every such account already at a zero posted balance), no closing entry is created and `closing_journal_entry_id` remains null. Second, as a consequence of that posting, each `REVENUE` and `EXPENSE` account's `posted_balance_cents` is recomputed to 0 and the retained-earnings account's `posted_balance_cents` is recomputed. Third, as a consequence of the retained-earnings account mutation, the company's `retained_earnings_cents` is recomputed from that account's new posted balance. The period then becomes `CLOSED`.

A closed period is not permanently frozen. An `Owner` — and only an `Owner` — may reopen the most recently closed period, transitioning it from `CLOSED` back to `OPEN` for late adjustments. Reopening is allowed only for the latest closed period; an attempt to reopen any earlier closed period (one for which the company's current period refers to a later period) is rejected with `ERR_NOT_LATEST_CLOSED_PERIOD`. Reopening voids the closing entry through its reversal path — creating a `REVERSAL` entry that recomputes the affected account balances and the company's `retained_earnings_cents` — clears `closing_journal_entry_id` back to null, and returns the period to `OPEN`.

### 3.3. Drafting Journal Entries and Their Lines

The general ledger's atomic unit is the `JournalEntry`. Any `Owner`, `Accountant`, or `Bookkeeper` may create one in `DRAFT` status by supplying `company_id`, the target `period_id`, an `entry_date`, and an optional `memo` (defaulting to an empty string). On creation the entry's `source` is `MANUAL`, its `created_by_user_id` is set to the caller's `X-User-ID`, and its `total_debit_cents` and `total_credit_cents` are 0. The `source` enum more broadly takes one of `MANUAL`, `BANK_FEED`, `CLOSING`, or `REVERSAL`, with the latter three reserved for system-generated entries. Entries may be fetched directly or listed and filtered by `company_id`, `period_id`, `status`, or `reverses_journal_entry_id`.

Detail is added to a draft entry as `JournalLine` rows, again by any `Owner`, `Accountant`, or `Bookkeeper`. A line names its parent `journal_entry_id` and an `account_id`, and carries a `debit_cents`, a `credit_cents` (each defaulting to 0), and an optional `line_memo`. Exactly one of `debit_cents` and `credit_cents` must be greater than zero and both must be at least zero; a line that has both positive, both zero, or any negative value is rejected with `ERR_INVALID_LINE`. A line may be added only while its parent entry is still `DRAFT`; adding a line to an entry that is not in `DRAFT` is rejected as an invalid state transition. Each line added recomputes the parent entry's `total_debit_cents` and `total_credit_cents` from the sum of its lines' debit and credit amounts respectively. Lines may be fetched directly or listed and filtered by `journal_entry_id` or `account_id`.

### 3.4. Posting, Maker-Checker, and Voiding Entries

Posting drives a draft entry from `DRAFT` to `POSTED` and may be performed by an `Accountant` or an `Owner`. Several preconditions are evaluated. The entry must balance and be non-trivial: `total_debit_cents` must equal `total_credit_cents`, that common total must be greater than zero, and the entry must have at least two `JournalLine` rows — any of these failing is rejected with `ERR_ENTRY_NOT_BALANCED`. Segregation of duties is enforced: the posting caller's `X-User-ID` must differ from the entry's `created_by_user_id`, so the maker of an entry can never post their own work; a self-post is rejected with `ERR_SEGREGATION_OF_DUTIES`. The entry's `period_id` must refer to a period in `OPEN` status, or the post is rejected with `ERR_PERIOD_NOT_OPEN`. Finally every account referenced by the entry's lines must be `ACTIVE`; a reference to an `ARCHIVED` account is rejected with `ERR_ACCOUNT_ARCHIVED`. On success the entry becomes `POSTED`, each referenced account's `posted_balance_cents` is recomputed per its normal side, and the company's `trial_balance_status` is recomputed.

Voiding is reserved to the `Owner` and applies only to a `POSTED` entry, moving it to the terminal `VOIDED` state. Two preconditions guard it: the entry's `period_id` must refer to a period in `OPEN` status, with a closed period rejected as `ERR_PERIOD_CLOSED`; and the entry's `source` must not be `CLOSING`, since closing entries are unwound only by reopening their period — a direct void of a closing entry is rejected with `ERR_CLOSING_ENTRY_PROTECTED`. The void runs the reversal cascade described in §2.6: a `REVERSAL` entry with swapped debits and credits is created and posted immediately, the affected account balances and the company's `trial_balance_status` are recomputed, and the original entry's status becomes `VOIDED`.

### 3.5. Bank Accounts and the Bank-Feed Categorization Loop

A `BankAccount`, created by an `Owner` or `Accountant`, links a real-world account to the ledger by naming its `company_id`, the `gl_account_id` of the cash GL account it posts to, and a display `nickname`. The linked GL account must be a cash `ASSET` account (`is_cash` true); linking a non-cash account is rejected with `ERR_INVALID_CATEGORIZATION_ACCOUNT`. A new bank account starts with `last_reconciled_statement_balance_cents` of 0, `last_reconciled_through` of null, and `version` 1. Bank accounts may be fetched or listed and filtered by `company_id` or `gl_account_id`.

Bank activity arrives as `BankFeedTransaction` rows imported by an `Owner`, `Accountant`, or `Bookkeeper` with `company_id`, `bank_account_id`, `posted_date`, a signed `amount_cents` (positive for a deposit into the account, negative for a withdrawal), and the raw `bank_description`. An imported transaction begins `UNMATCHED` with `cleared` false. A transaction may be fetched or listed and filtered by `company_id`, `bank_account_id`, `counter_account_id`, `journal_entry_id`, or `status`.

A `Bookkeeper` or `Accountant` categorizes an `UNMATCHED` transaction by supplying the `counter_account_id` — the non-cash account the money flows to or from — which moves it to `CATEGORIZED`. Three preconditions apply: the `counter_account_id` must reference an existing `ACTIVE` account in the same company (a missing account yields `ERR_ACCOUNT_NOT_FOUND`, an archived one yields `ERR_ACCOUNT_ARCHIVED`, and an existing non-archived account belonging to a different company yields `ERR_INVALID_CATEGORIZATION_ACCOUNT`); the chosen account must not be `EQUITY`-typed and must not be the bank's own `gl_account_id`, either of which is rejected with `ERR_INVALID_CATEGORIZATION_ACCOUNT`; and the company's `current_period_id` must be set, its period `OPEN`, and the transaction's `posted_date` within that period, failing which the request is `ERR_PERIOD_NOT_OPEN`. On success the system creates a two-line `BANK_FEED` journal entry and posts it immediately: for a deposit (positive amount) it debits the bank's cash GL account and credits the counter account; for a withdrawal (negative amount) it debits the counter account and credits the bank's cash GL account. The new entry's id is stored on the transaction's `journal_entry_id`, the `counter_account_id` is retained, the affected account balances and the company's `trial_balance_status` are recomputed, and the transaction's `status` becomes `CATEGORIZED`.

Categorization is reversible until reconciled. A `Bookkeeper` or `Accountant` may recategorize a `CATEGORIZED` transaction back to `UNMATCHED`, provided its `cleared` flag is false; a transaction already cleared by a reconciliation cannot be recategorized and is rejected with `ERR_TRANSACTION_CLEARED`. Recategorization voids the linked `BANK_FEED` entry through the reversal cascade, resets both `journal_entry_id` and `counter_account_id` to null, and returns the transaction to `UNMATCHED` — so a transaction may bounce between `UNMATCHED` and `CATEGORIZED` any number of times until it is reconciled. Separately, an `UNMATCHED` transaction that does not belong on the books may be moved to the terminal `EXCLUDED` state by a `Bookkeeper` or `Accountant`, with no further side effects.

### 3.6. Customers, Invoices, and the Tiered-Discount Tax Breakdown

A `Customer` is created by an `Owner`, `Accountant`, or `Bookkeeper` with `company_id`, a `display_name`, a `tax_jurisdiction` used to select the applicable tax rate, and the `ar_account_id` of the receivable `ASSET` account that invoices will debit. Customers may be fetched or listed and filtered by `company_id` or `ar_account_id`.

An `Invoice` is drafted by an `Owner`, `Accountant`, or `Bookkeeper` with `company_id`, `customer_id`, the `revenue_account_id` to credit, the `tax_liability_account_id` (the `LIABILITY` account holding collected sales tax), an `issue_date`, and `lines`. Each entry in `lines` carries a `description`, a `quantity`, a `unit_price_cents`, and a `taxable` boolean. A draft invoice begins with `delivery_status` of `DRAFT` and `payment_status` of `UNPAID`, and all of its computed money fields at 0. The two status axes are independent: `delivery_status` tracks the document's lifecycle (`DRAFT`, `SENT`, `VOID`) while `payment_status` tracks collection (`UNPAID`, `PARTIALLY_PAID`, `PAID`). Invoices may be fetched or listed and filtered by `company_id`, `customer_id`, `revenue_account_id`, `tax_liability_account_id`, `delivery_status`, or `payment_status`.

A `Bookkeeper` or `Accountant` sends a `DRAFT` invoice, moving its `delivery_status` to `SENT` while `payment_status` stays `UNPAID`. Sending requires that `lines` be non-empty (an empty invoice is rejected with `ERR_INVOICE_EMPTY`) and that the company's current period be `OPEN` with `issue_date` within it (otherwise `ERR_PERIOD_NOT_OPEN`). On send the system first captures `applied_tax_rate_bps` from the tax rate effective on `issue_date` for the customer's jurisdiction, then computes the money breakdown in a **pinned evaluation order** — subtotals, then discount, then tax, then total:

1. **Subtotals.** The `taxable_subtotal_cents` is the sum, over taxable lines, of each line's `quantity` multiplied by its `unit_price_cents`; the `nontaxable_subtotal_cents` is the same sum over non-taxable lines.
2. **Discount.** A volume discount is keyed on `taxable_subtotal_cents`. When the taxable subtotal is at least 1,000,000 cents (that is, ten thousand dollars), the discount percentage is ten percent; otherwise, when it is at least 500,000 cents (five thousand dollars), the discount percentage is five percent; otherwise it is zero. The `discount_cents` is the taxable subtotal multiplied by that discount percentage, rounded half up to whole cents.
3. **Tax.** The discounted taxable base is `taxable_subtotal_cents` minus `discount_cents`. Tax is computed per taxable line and then summed: each taxable line's share is that line's amount multiplied by `applied_tax_rate_bps`, divided by 10,000, multiplied by the ratio of the discounted taxable base to the original `taxable_subtotal_cents`, with each per-line result rounded half up to whole cents before the lines are summed into `tax_cents`.
4. **Total.** The `total_cents` is the discounted taxable base plus `nontaxable_subtotal_cents` plus `tax_cents`.

Sending then posts a `MANUAL`-source journal entry that debits the receivable account by the total, credits the revenue account by the discounted taxable base plus the non-taxable subtotal, and credits the tax-liability account by `tax_cents`. The invoice also exposes `amount_paid_cents` (the sum of cleared payments applied) and `balance_due_cents` (the `total_cents` minus `amount_paid_cents`, meaningful once the invoice is `SENT`).

A `SENT` invoice that has not been paid may be voided by an `Accountant` or `Owner`, moving `delivery_status` to `VOID`. Voiding is permitted only when `payment_status` is `UNPAID`; an invoice carrying any cleared payment is rejected with `ERR_INVOICE_HAS_PAYMENTS`. The company's current period must be `OPEN`, with a non-open current period rejected as `ERR_PERIOD_CLOSED` (the period guard is evaluated against the company's `current_period_id`, not a separately resolved issue-date period). Voiding reverses the invoice's posting entry through the reversal cascade.

### 3.7. Receiving Customer Payments

A `Bookkeeper` or `Accountant` records an `InvoicePayment` against a `SENT` invoice by supplying `company_id`, the `invoice_id`, the `deposit_bank_account_id` (the cash account that receives the funds), and an `amount_cents`. The payment amount must be greater than zero and must not exceed the invoice's current `balance_due_cents`; an over-application is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`, and recording a payment against an invoice that is not `SENT` is rejected as an invalid state. A payment is created in `CLEARED` status, and the system posts the receipt journal entry into the named `journal_entry_id` (debit cash, credit accounts-receivable). Each cleared payment recomputes the invoice: `amount_paid_cents` becomes the sum of `amount_cents` over the invoice's `CLEARED` payments, `balance_due_cents` becomes `total_cents` minus that sum, and `payment_status` is re-derived — `UNPAID` when nothing has been paid, `PARTIALLY_PAID` when the paid amount is greater than zero but less than `total_cents`, and `PAID` when the paid amount equals `total_cents`. The invariant `amount_paid_cents` plus `balance_due_cents` equals `total_cents` holds at all times. Payments may be fetched or listed and filtered by `company_id`, `invoice_id`, `deposit_bank_account_id`, or `journal_entry_id`.

A cleared payment may be reversed by an `Accountant` or `Owner`, moving it from `CLEARED` to the terminal `REVERSED` state, provided the company's current period is still `OPEN` (a non-open current period is rejected with `ERR_PERIOD_CLOSED`; the guard is evaluated against the company's `current_period_id` rather than a separately resolved issue-date period). Reversal voids the receipt entry through the reversal cascade, then recomputes the invoice's `amount_paid_cents`, `balance_due_cents`, and `payment_status`. The compensation property holds: applying a payment and then reversing it leaves the `amount_paid_cents`-plus-`balance_due_cents`-equals-`total_cents` invariant intact.

### 3.8. Vendors, Bills, Use Tax, and 1099 Tracking

A `Vendor` is created by an `Owner`, `Accountant`, or `Bookkeeper` with `company_id`, a `display_name`, the `ap_account_id` of the payable `LIABILITY` account bills will credit, and an optional `is_1099_eligible` flag (default false) indicating whether payments to the vendor count toward 1099-NEC reporting. Each vendor exposes a computed `ytd_1099_total_cents`, recomputed on bill approval and on bill payment, and initialized to 0 at creation. Vendors may be fetched or listed and filtered by `company_id` or `ap_account_id`.

A `Bill` is drafted by an `Owner`, `Accountant`, or `Bookkeeper` with `company_id`, `vendor_id`, the `expense_account_id` to debit, a `bill_date`, and `lines`, where each line carries a `description`, an `amount_cents`, and a `use_taxable` boolean. A draft bill begins in `DRAFT` status with its computed fields at 0. Across its life a bill moves through `DRAFT`, `APPROVED`, `PARTIALLY_PAID`, `PAID`, and `VOID`. Bills may be fetched or listed and filtered by `company_id`, `vendor_id`, `expense_account_id`, or `status`.

An `Accountant` or `Owner` approves a `DRAFT` bill, moving it to `APPROVED`; there is no maker-checker constraint on bills. Approval requires non-empty `lines` (an empty bill is rejected with `ERR_BILL_EMPTY`) and the company's current period `OPEN` with `bill_date` within it (otherwise `ERR_PERIOD_NOT_OPEN`). On approval the system captures the use-tax `applied_tax_rate_bps` from the company's default-jurisdiction rate effective on `bill_date`; because no explicit default-jurisdiction field is stored on the company, this is resolved as any of the company's `TaxRate` records whose half-open `[effective_from, effective_to)` window covers `bill_date`, regardless of its `jurisdiction`, and when more than one such rate exists the most recently created one is used (the captured rate is 0 if none applies). It then computes the bill totals: the `subtotal_cents` is the sum of every line's `amount_cents`; for each line whose `use_taxable` is true, that line's use tax is the line's `amount_cents` multiplied by `applied_tax_rate_bps` divided by 10,000, rounded half up to whole cents; the `use_tax_cents` is the sum of those per-line rounded amounts (rounded per line, then summed, in that pinned order); and `total_cents` is `subtotal_cents` plus `use_tax_cents`. Approval posts a `MANUAL` journal entry debiting the expense account by the subtotal plus use tax and crediting the payable account by the total, then recomputes `Vendor.ytd_1099_total_cents`. A `DRAFT` bill may instead be voided by an `Accountant` or `Owner`, moving it to `VOID`; voiding is permitted only from `DRAFT`, and a void attempt on an `APPROVED` or paid bill is rejected as an invalid state.

Payments against an `APPROVED` (or `PARTIALLY_PAID`) bill are recorded by an `Accountant` or `Owner` by supplying `pay_from_bank_account_id` (a valid bank account of the company), an `amount_cents`, and a `payment_date`. The payment posts a `MANUAL` journal entry debiting the payable account and crediting the bank's cash GL account, then recomputes `amount_paid_cents`, `paid_in_tax_year`, and `Vendor.ytd_1099_total_cents`. The resulting status depends on the running paid total: when `amount_paid_cents` plus the new `amount_cents` exactly equals `total_cents`, the bill becomes `PAID`; when it is less than `total_cents`, the bill becomes `PARTIALLY_PAID`; and when it would exceed `total_cents`, the payment is rejected with `ERR_BILL_OVERPAY`. The payment date must fall within the company's `OPEN` period, or the request is rejected with `ERR_PERIOD_NOT_OPEN`.

The vendor's `ytd_1099_total_cents` is reported through a dedicated read returning `vendor_id`, the `basis`, the `ytd_1099_total_cents`, and `is_1099_eligible`, and is computed in one of two variants selected by the company's `accounting_basis`. The tax year is the calendar year of the company's current open period's `start_date`. If the vendor's `is_1099_eligible` is false, the total is 0. Under the **accrual** variant (`accounting_basis` is `ACCRUAL`), the total is the sum of `total_cents` over the vendor's bills whose `status` is not `VOID` and whose `bill_date` falls in the tax year — bill totals counted by `bill_date` regardless of payment. Under the **cash** variant (`accounting_basis` is `CASH`), the total is the sum of `paid_in_tax_year` over the vendor's bills — only amounts actually paid within the tax year count, so an approved-but-unpaid bill contributes nothing. The `paid_in_tax_year` field on a bill is the sum of that bill's payment amounts whose payment date falls in the company tax year, and it is what drives the cash-basis variant.

### 3.9. Bank Reconciliation

Reconciliation ties the ledger's cash position to the bank statement. An `Accountant` or `Owner` starts a `Reconciliation` by supplying `company_id`, `bank_account_id`, the statement window `statement_start_date` (inclusive) and `statement_end_date` (exclusive), the `statement_opening_balance_cents`, the `statement_ending_balance_cents`, and `included_transaction_ids` — the list of bank-feed transactions selected as cleared on this statement. For contiguity, callers are expected to set `statement_end_date` equal to the bank account's `last_reconciled_through` when that is set and `statement_opening_balance_cents` equal to the bank account's `last_reconciled_statement_balance_cents`; the system does not, however, validate or reject on these contiguity expectations at creation — no dedicated error is raised for a non-contiguous statement window or opening balance. Every included transaction must be `CATEGORIZED`, belong to the same bank account, and not already be cleared; an included transaction that is not categorized or is already cleared is rejected with `ERR_TRANSACTION_NOT_CATEGORIZED`. A reconciliation is created `IN_PROGRESS`.

The system computes `difference_cents` at creation and re-checks it before finalizing: it sums the signed `amount_cents` over the included transactions to obtain the cleared movement, adds that movement to `statement_opening_balance_cents` to obtain the expected ending balance, and sets `difference_cents` to `statement_ending_balance_cents` minus that expected ending balance. Reconciliations may be fetched or listed and filtered by `company_id`, `bank_account_id`, or `status`.

An `Accountant` or `Owner` finalizes an `IN_PROGRESS` reconciliation, moving it to the terminal `RECONCILED` state. Finalize requires `difference_cents` to be exactly zero with no tolerance (a non-zero difference is rejected with `ERR_RECONCILIATION_UNBALANCED`), every included transaction to still be `CATEGORIZED` and not cleared (otherwise `ERR_TRANSACTION_NOT_CATEGORIZED`), and `expected_bank_account_version` to match the bank account's current `version` per §2.7 (otherwise `ERR_STALE_VERSION` at HTTP 412). On success each included `BankFeedTransaction` has its `cleared` flag set to true, the bank account's `last_reconciled_statement_balance_cents` is set to `statement_ending_balance_cents`, its `last_reconciled_through` is set to `statement_end_date`, and `BankAccount.version` is incremented by one. Alternatively an `IN_PROGRESS` reconciliation may be abandoned by an `Accountant` or `Owner`, moving it to the terminal `ABANDONED` state with no transactions cleared.

### 3.10. Financial Statements

A computed financial-statements read, available to an `Owner`, `Accountant`, or `Auditor` and accepting an optional `as_of_period_id` query parameter, derives a picture from all of the company's `POSTED` entries; the `as_of_period_id` parameter is accepted but does not narrow the result — the figures always roll up every posted entry of the company regardless of period. It returns the company's `trial_balance_status`, the `total_revenue_cents`, the `total_expense_cents`, the `net_income_cents`, the `total_assets_cents`, the `total_liabilities_cents`, and the `total_equity_cents`. These figures roll up the posted balances of the relevant account types and are read-only — generating the statement mutates nothing.

### 3.11. Validation Ordering Across the Workflow

When several checks could apply to a single request, the system evaluates them in a fixed priority order so that the failure surfaced is deterministic. Authentication comes first: the presence and validity of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) is checked before role authorization (`ERR_FORBIDDEN_FOR_ROLE`). Existence checks follow: a referenced `account_id` that does not exist surfaces as `ERR_ACCOUNT_NOT_FOUND`, and this account-existence check is evaluated before the more general existence check for any other referenced resource (company, period, invoice, bill, vendor, customer, bank account, reconciliation, or transaction), which surfaces as `ERR_NOT_FOUND`. Only once existence is established does the system check that a target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`).

Business rules are then evaluated in their own order. The segregation-of-duties check on posting (`ERR_SEGREGATION_OF_DUTIES`) precedes referential business rules. Among referential rules, an `ARCHIVED` account is detected first (`ERR_ACCOUNT_ARCHIVED`) — that is, the account-archived check runs before the categorization-target-type rule (`ERR_INVALID_CATEGORIZATION_ACCOUNT`), so a categorization onto an archived account reports the archived error rather than the categorization-account error. Structural temporal rules — a sub-account sharing its parent's type (`ERR_ACCOUNT_TYPE_MISMATCH`), a non-overlapping tax-rate window (`ERR_TAX_RATE_OVERLAP`), and a contiguous period start (`ERR_PERIOD_NOT_CONTIGUOUS`) — are evaluated next on their respective create endpoints. Fiscal-period rules follow: the open-period requirement (`ERR_PERIOD_NOT_OPEN`) for posting, categorizing, sending, approving, and paying, then the closed-period rejection (`ERR_PERIOD_CLOSED`) for voids and reverses. After those come the balance and content constraints — entry balance (`ERR_ENTRY_NOT_BALANCED`), line validity (`ERR_INVALID_LINE`), non-empty invoice (`ERR_INVOICE_EMPTY`), and non-empty bill (`ERR_BILL_EMPTY`) — followed by the payment ceilings (`ERR_PAYMENT_EXCEEDS_BALANCE` for invoices and `ERR_BILL_OVERPAY` for bills), the void-with-payments guard (`ERR_INVOICE_HAS_PAYMENTS`), the reconciliation constraints (`ERR_RECONCILIATION_UNBALANCED` and `ERR_TRANSACTION_NOT_CATEGORIZED`), the period-close constraints (`ERR_CHECKLIST_INCOMPLETE`, `ERR_OPEN_DRAFT_ENTRIES`, `ERR_RECONCILIATION_IN_PROGRESS`, `ERR_TRIAL_BALANCE_OUT_OF_BALANCE`, and `ERR_NOT_LATEST_CLOSED_PERIOD`), the protection rules (`ERR_TRANSACTION_CLEARED` and `ERR_CLOSING_ENTRY_PROTECTED`), and the duplicate-account-code rule (`ERR_DUPLICATE_ACCOUNT_CODE`). Optimistic-concurrency checks (`ERR_STALE_VERSION`) are the last business gate, applying to period creation and reconciliation finalize.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify an existing resource — including all state-transition actions — return a `200 OK` status code. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1. The table below is intentionally a summary: request bodies, response shapes, and side effects are specified in the §3 narratives and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/ledger/companies` | Create a company | Owner |
| GET    | `/ledger/companies/{companyId}` | Get a company | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/companies` | List companies | Owner, Accountant, Bookkeeper, Auditor |
| PATCH  | `/ledger/companies/{companyId}` | Configure a company | Owner |
| POST   | `/ledger/accounts` | Create an account | Owner, Accountant |
| GET    | `/ledger/accounts/{accountId}` | Get an account | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/accounts` | List accounts | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/accounts/{accountId}/balance` | Get a computed account balance | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/accounts/{accountId}/archive` | Archive an account | Owner, Accountant |
| POST   | `/ledger/accounting-periods` | Open a new accounting period | Owner, Accountant |
| GET    | `/ledger/accounting-periods/{periodId}` | Get an accounting period | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/accounting-periods` | List accounting periods | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/accounting-periods/{periodId}/checklist` | Mark a close-checklist item | Owner, Accountant, Bookkeeper |
| POST   | `/ledger/accounting-periods/{periodId}/begin-close` | Begin period close | Accountant |
| POST   | `/ledger/accounting-periods/{periodId}/post-close` | Post period close | Accountant |
| POST   | `/ledger/accounting-periods/{periodId}/reopen` | Reopen the latest closed period | Owner |
| POST   | `/ledger/journal-entries` | Create a draft journal entry | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/journal-entries/{entryId}` | Get a journal entry | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/journal-entries` | List journal entries | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/journal-lines` | Add a journal line | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/journal-lines/{lineId}` | Get a journal line | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/journal-lines` | List journal lines | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/journal-entries/{entryId}/post` | Post a draft journal entry | Accountant, Owner |
| POST   | `/ledger/journal-entries/{entryId}/void` | Void a posted journal entry | Owner |
| POST   | `/ledger/bank-accounts` | Create a bank account | Owner, Accountant |
| GET    | `/ledger/bank-accounts/{bankAccountId}` | Get a bank account | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/bank-accounts` | List bank accounts | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/bank-feed-transactions` | Import a bank-feed transaction | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/bank-feed-transactions/{transactionId}` | Get a bank-feed transaction | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/bank-feed-transactions` | List bank-feed transactions | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/bank-feed-transactions/{transactionId}/categorize` | Categorize a transaction | Bookkeeper, Accountant |
| POST   | `/ledger/bank-feed-transactions/{transactionId}/recategorize` | Recategorize a transaction | Bookkeeper, Accountant |
| POST   | `/ledger/bank-feed-transactions/{transactionId}/exclude` | Exclude a transaction | Bookkeeper, Accountant |
| POST   | `/ledger/reconciliations` | Start a reconciliation | Accountant, Owner |
| GET    | `/ledger/reconciliations/{reconciliationId}` | Get a reconciliation | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/reconciliations` | List reconciliations | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/reconciliations/{reconciliationId}/finalize` | Finalize a reconciliation | Accountant, Owner |
| POST   | `/ledger/reconciliations/{reconciliationId}/abandon` | Abandon a reconciliation | Accountant, Owner |
| POST   | `/ledger/customers` | Create a customer | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/customers/{customerId}` | Get a customer | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/customers` | List customers | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/invoices` | Create a draft invoice | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/invoices/{invoiceId}` | Get an invoice | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/invoices` | List invoices | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/invoices/{invoiceId}/send` | Send a draft invoice | Bookkeeper, Accountant |
| POST   | `/ledger/invoices/{invoiceId}/void` | Void a sent unpaid invoice | Accountant, Owner |
| POST   | `/ledger/invoice-payments` | Record an invoice payment | Bookkeeper, Accountant |
| GET    | `/ledger/invoice-payments/{paymentId}` | Get an invoice payment | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/invoice-payments` | List invoice payments | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/invoice-payments/{paymentId}/reverse` | Reverse a cleared invoice payment | Accountant, Owner |
| POST   | `/ledger/vendors` | Create a vendor | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/vendors/{vendorId}` | Get a vendor | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/vendors` | List vendors | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/vendors/{vendorId}/1099` | Get the vendor 1099 total | Owner, Accountant, Auditor |
| POST   | `/ledger/bills` | Create a draft bill | Owner, Accountant, Bookkeeper |
| GET    | `/ledger/bills/{billId}` | Get a bill | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/bills` | List bills | Owner, Accountant, Bookkeeper, Auditor |
| POST   | `/ledger/bills/{billId}/approve` | Approve a draft bill | Accountant, Owner |
| POST   | `/ledger/bills/{billId}/record-payment` | Record a bill payment | Accountant, Owner |
| POST   | `/ledger/bills/{billId}/void` | Void a draft bill | Accountant, Owner |
| POST   | `/ledger/tax-rates` | Create a tax-rate window | Owner, Accountant |
| GET    | `/ledger/tax-rates/{taxRateId}` | Get a tax rate | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/tax-rates` | List tax rates | Owner, Accountant, Bookkeeper, Auditor |
| GET    | `/ledger/companies/{companyId}/financial-statements` | Generate financial statements | Owner, Accountant, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_LINE` | 422 Unprocessable Entity |
| `ERR_ENTRY_NOT_BALANCED` | 422 Unprocessable Entity |
| `ERR_INVOICE_EMPTY` | 422 Unprocessable Entity |
| `ERR_BILL_EMPTY` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_CATEGORIZATION_ACCOUNT` | 409 Conflict |
| `ERR_ACCOUNT_ARCHIVED` | 409 Conflict |
| `ERR_ACCOUNT_TYPE_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_ACCOUNT_CODE` | 409 Conflict |
| `ERR_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_PERIOD_CLOSED` | 409 Conflict |
| `ERR_PERIOD_NOT_CONTIGUOUS` | 409 Conflict |
| `ERR_CHECKLIST_INCOMPLETE` | 409 Conflict |
| `ERR_OPEN_DRAFT_ENTRIES` | 409 Conflict |
| `ERR_RECONCILIATION_IN_PROGRESS` | 409 Conflict |
| `ERR_TRIAL_BALANCE_OUT_OF_BALANCE` | 409 Conflict |
| `ERR_NOT_LATEST_CLOSED_PERIOD` | 409 Conflict |
| `ERR_CLOSING_ENTRY_PROTECTED` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 Conflict |
| `ERR_BILL_OVERPAY` | 409 Conflict |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_RECONCILIATION_UNBALANCED` | 409 Conflict |
| `ERR_TRANSACTION_NOT_CATEGORIZED` | 409 Conflict |
| `ERR_TRANSACTION_CLEARED` | 409 Conflict |
| `ERR_TAX_RATE_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
