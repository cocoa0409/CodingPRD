# Bookkeeping Cleanup API — Product Requirements Document

## 1. Introduction

Accounting firms that take on a neglected set of books face a recurring, painful pattern: a client arrives months or years behind, the ledger is incomplete, bank and credit-card activity has never been reconciled, and nobody can say with confidence what the business actually earned. The Bookkeeping Cleanup API is the system of record for these catch-up engagements. It carries a client's books from an initial scope-and-volume estimate, through ledger reconstruction and categorization, into bank and credit reconciliation, fixed-price phase billing, and finally a clean books-to-tax handoff — optionally converting the relationship into an ongoing monthly service once the cleanup is done.

The system is built around a strict separation of professional duties. The bookkeeper who reconstructs and categorizes the ledger is deliberately not permitted to be the reviewer who signs off on a reconciliation, and the tax preparer who builds the taxable-income package is a distinct party again. This document specifies the engagement lifecycle, the parallel billing track that runs alongside it, the calculation rules that drive volume estimates, pricing, reconciliation differences, taxable income and service proration, and the exception-tracking machinery that surfaces missing documents and out-of-balance accounts before they can poison a tax return. Every workflow below is designed so that an engagement can only reach completion when its books are genuinely in balance, its blocking exceptions are cleared, and its phase invoices are fully paid.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles: `EngagementManager`, `Bookkeeper`, `Reviewer`, and `TaxPreparer`. When a caller presents a recognized role that is nonetheless not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

For all four roles, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity. When `X-User-Role` is `EngagementManager`, `X-User-ID` is an opaque operator identifier; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `Bookkeeper`, when it is `Reviewer`, and when it is `TaxPreparer`: in each case `X-User-ID` is opaque and is never matched against a stored foreign key for ownership. The server may, however, record an opaque identifier for the purpose of enforcing segregation of duties (see below) — it remembers which user categorized an account in order to compare it against the user attempting later sign-off, but it never treats that identifier as a reference to a persisted record.

The roles divide the work along professional lines. An `EngagementManager` owns the engagement lifecycle end to end: creating clients and engagements, scoping, quoting and phase billing, completion, and service-plan management. A `Bookkeeper` reconstructs and categorizes the ledger — creating accounts, posting and reversing entries, opening exceptions, and requesting and receiving documents. A `Reviewer` is the independent second pair of eyes who reconciles bank statements, signs off accounts as reconciled, and waives exceptions. A `TaxPreparer` builds, hands off, and amends the tax package. All four roles share read access to the GET endpoints.

**Segregation of duties.** Because the reviewer's sign-off is meaningful only if it is genuinely independent, the user who marks an account as reconciled must not be the same user (by `X-User-ID`) who categorized that account. A reviewer who attempts to sign off on an account they themselves categorized is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint says otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource in the system — clients, engagements, scope estimates, ledger accounts, ledger entries, bank statements, reconciliation items, phases, phase invoices, tax packages, service plans, exceptions, and completion reports — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. These resources additionally carry an `updated_at` timestamp, likewise ISO 8601 UTC with three fractional digits, refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on each mutation of the resource. Whenever a derived field on a resource is recomputed as a side effect of some operation — for instance the engagement's readiness or reconciliation aggregates — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Nested Resource Retrieval and Path Validation

Most resources live beneath an engagement, addressed through paths such as an engagement's accounts, entries, statements, phases or exceptions, and some go one level deeper — a statement's reconciliation items, for example. When a path names more than one resource identifier, the system validates them strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A reconciliation item requested under a non-existent statement fails on the statement before the item is ever considered, and any child requested under a non-existent engagement fails on the engagement first. This left-to-right existence check is the fourth validation in priority order, applying to every endpoint that addresses a resource by path.

### 2.6. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. Authentication comes first: header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) is checked before anything else. Role authorization (`ERR_FORBIDDEN_FOR_ROLE`) is checked second. The segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`) on account sign-off is third, ahead of resource existence. Resource existence along the path (`ERR_NOT_FOUND`) is fourth. Request-body well-formedness — required fields present, enum values valid, and `amount_cents` and `weight_bp` strictly positive (`ERR_INVALID_REQUEST`) — is fifth. State-machine validity for the requested transition (`ERR_INVALID_STATE`) is sixth. All remaining business rules described in section 3 are evaluated after these, in the order their narratives describe.

### 2.7. Derived Engagement Aggregates

A `CleanupEngagement` exposes several read-only fields that the system keeps in step with its children rather than accepting from clients. The `reconciled_account_count` is the number of the engagement's accounts currently in the `RECONCILED` state. The `total_account_count` is the number of the engagement's accounts that are not in the `EXCLUDED` state. The `open_blocking_exception_count` is the number of the engagement's exceptions whose severity is `BLOCKING` and whose status is neither `RESOLVED` nor `WAIVED`. The `estimated_txn_volume` is zero until a scope estimate is accepted, at which point it takes the accepted estimate's transaction-volume figure. The `recon_status` is one of `PENDING`, `IN_BALANCE`, or `OUT_OF_BALANCE`, aggregated from the outcomes of the engagement's reconciliation work as follows: it is `OUT_OF_BALANCE` when the engagement has at least one statement currently in `RECONCILING` and at least one open (neither `RESOLVED` nor `WAIVED`) `UNRECONCILED_DIFF` exception; otherwise it is `PENDING` when any non-`EXCLUDED` `is_bank_account` account has no `RECONCILED` statement; otherwise it is `IN_BALANCE`. A fresh engagement with no bank accounts and no reconciliation activity therefore reads `IN_BALANCE`. The `readiness_score` is an integer from 0 to 100 measuring books-to-tax readiness. Each of these is recomputed whenever an underlying child changes in a way that affects it, and the recomputation follows the mutation semantics of section 2.4.

### 2.8. Readiness Scoring

The engagement's `readiness_score` reflects how close the books are to being tax-ready. If the engagement has no countable accounts — that is, `total_account_count` is zero — the base score is zero. Otherwise the base is one hundred multiplied by `reconciled_account_count`, divided by `total_account_count`, with the result rounded down to a whole number before any penalty is applied. From that base, a penalty of eight points is subtracted for each open blocking exception, i.e. eight multiplied by `open_blocking_exception_count`. The final `readiness_score` is then clamped into the inclusive range from 0 to 100: any value below zero becomes zero and any value above one hundred becomes one hundred. This score is recomputed whenever an account is signed off as reconciled, whenever a blocking exception is resolved or waived, and whenever a statement is finalized.

### 2.9. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents — there are no fractional cents and no floating-point money. Where a calculation produces a non-integer cent value that must be rounded, the system rounds half up to the nearest whole cent. Transaction-volume estimates are likewise integers, rounded down (floored) to a whole number of transactions. The readiness score is an integer between 0 and 100, with the ratio floored before the blocking penalty is applied.

### 2.10. Optimistic Concurrency Control on Scope Acceptance

Accepting a scope estimate rebaselines the engagement's scope and is therefore guarded by optimistic concurrency control on the engagement. The accept request must carry an `expected_engagement_version` field whose value is the `version` of the target `CleanupEngagement` that the client last observed. The server compares this against the engagement's current `version`. If a competing scope estimate was accepted in the meantime — which legitimately supersedes the earlier baseline and increments the engagement's `version` — then the client's observed version is now stale, and the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` and HTTP status 412. This prevents an acceptor whose view of the engagement predates a prior acceptance from clobbering the scope baseline that was set in the interim. This is the only endpoint that takes a version field; no other operation requires `expected_engagement_version`.

## 3. Business Logic & Workflows

### 3.1. Clients and Engagement Creation

Every cleanup begins with a `Client`. An `EngagementManager` registers a client by supplying its `legal_name`, its `entity_type` — one of `SOLE_PROP`, `PARTNERSHIP`, `S_CORP`, `C_CORP`, or `LLC` — and optionally its `accounting_basis`, which is either `CASH` or `ACCRUAL` and defaults to `ACCRUAL` when omitted. The accounting basis is consequential: it ultimately decides which transactions count toward taxable income at handoff time. Newly created clients are given a system `status` of `ACTIVE`, which may later read `ARCHIVED`.

Against a client, the `EngagementManager` opens a `CleanupEngagement`, naming the owning `client_id`, a `title`, and the cleanup window as `period_start` and `period_end` (each an inclusive ISO date in `YYYY-MM-DD` form, the first and last days of the period). The manager may also declare a `complexity_tier` of `LOW`, `MEDIUM`, or `HIGH`, defaulting to `MEDIUM`; this tier scales the forward volume estimate. A fresh engagement starts with `workflow_status` of `DRAFT`, a parallel `billing_status` of `UNBILLED`, and `scope_locked` set to false. Its `estimated_txn_volume` is zero until scope is accepted, and — having no accounts, exceptions, or reconciliation activity yet — its `reconciled_account_count`, `total_account_count`, and `open_blocking_exception_count` are zero, its `readiness_score` is zero, and its `recon_status` is `IN_BALANCE`.

The engagement carries two independent state dimensions that progress in parallel. The lifecycle dimension, `workflow_status`, runs `DRAFT` → `SCOPING` → `RECONSTRUCTION` → `RECONCILIATION` → `TAX_HANDOFF` → `COMPLETED`, with `CANCELLED` as an alternate terminal outcome. The billing dimension, `billing_status`, runs `UNBILLED` → `QUOTED` → `PHASED` → `SETTLED`. The two tracks advance through separate operations described below.

### 3.2. Scoping and Forward Volume Estimation

An `EngagementManager` moves an engagement from `DRAFT` into `SCOPING` to begin estimating the size of the job. During scoping, the manager creates one or more `ScopeEstimate` records against the engagement, each declaring a `monthly_txn_rate` — the operator's estimate of average transactions per month over the period. Upon creation a scope estimate begins with `status` of `PROPOSED` and the system computes two derived figures.

The first is `period_month_count`, the inclusive whole-month span of the engagement's period: take the difference in years between `period_end` and `period_start` multiplied by twelve, add the difference in their month numbers, and add one. The second is `txn_volume_estimate`, the forward-looking volume forecast: multiply `period_month_count` by the estimate's `monthly_txn_rate` and by the complexity factor for the engagement's tier, where that factor is 10000 basis points for `LOW`, 11500 for `MEDIUM`, and 13000 for `HIGH`; divide that product by 10000 and round the result down to a whole number of transactions. Working the multiplier in basis points and flooring at the end keeps the arithmetic exact and avoids floating-point drift. This forward estimate is purely a forecast derived from the declared monthly rate, the month span, and the tier multiplier.

To lock the scope, the manager accepts one of the proposed estimates. Acceptance is permitted only while the chosen `ScopeEstimate` is in `PROPOSED`; accepting an estimate that is not `PROPOSED` is rejected with `ERR_INVALID_STATE`. The accept request must also carry `expected_engagement_version` and is subject to the optimistic-concurrency rule of section 2.10 (rejected with `ERR_STALE_ENGAGEMENT_VERSION`, HTTP 412, on a version mismatch). On a successful accept, the chosen estimate's `status` becomes `ACCEPTED` and any other estimate that was previously `ACCEPTED` is moved to `SUPERSEDED`; the engagement's `scope_locked` flag is set to true; its `estimated_txn_volume` is set to the accepted estimate's `txn_volume_estimate`; the engagement's `version` is incremented by one; and the engagement's `workflow_status` advances from `SCOPING` to `RECONSTRUCTION`.

### 3.3. Reconstructing the Ledger: Accounts and Entries

With scope locked, the bookkeeping work begins in the `RECONSTRUCTION` phase. A `Bookkeeper` (or the `EngagementManager`) builds the chart of accounts by creating `LedgerAccount` records under the engagement, each with an `account_code`, a display `name`, and an `account_type` of `ASSET`, `LIABILITY`, `EQUITY`, `INCOME`, or `EXPENSE`. An account may be flagged `is_bank_account` (defaulting to false) when it represents a bank or credit-card account that will require statement reconciliation. The system derives each account's `normal_side`: accounts of type `ASSET` or `EXPENSE` have a `DEBIT` normal side, and all other types have a `CREDIT` normal side. New accounts begin in `DRAFT` status. The `account_code` must be unique within the engagement among accounts that are not `EXCLUDED`; a collision is rejected with `ERR_DUPLICATE_ACCOUNT_CODE`. Each account also exposes a computed `book_balance_cents`, the signed running balance derived from its `POSTED` entries: each such entry contributes `+amount_cents` when its `side` equals the account's `normal_side` and `-amount_cents` otherwise, so a debit-normal account carries a positive balance for net debit activity and a credit-normal account a positive balance for net credit activity. Entries that are not `POSTED` (whether `DRAFT` or `REVERSED`) do not contribute.

A `Bookkeeper` records activity as `LedgerEntry` rows on the engagement, each naming the `account_id` it belongs to, a `txn_date` (ISO `YYYY-MM-DD`), a `side` of `DEBIT` or `CREDIT`, a positive magnitude `amount_cents`, and an optional free-text `memo` (defaulting to empty). Entries start in `DRAFT`, with `cash_settled` false and no `reconciliation_item_id` yet assigned. An entry created as a reversal of another points at the original through `reversed_entry_id`. Posting an entry advances it from `DRAFT` to `POSTED`, but only when its `txn_date` falls within the engagement's `period_start` through `period_end` inclusive — an out-of-period date is rejected with `ERR_ENTRY_OUT_OF_PERIOD` — and only when the target account is not `EXCLUDED`, an excluded account being rejected with `ERR_ACCOUNT_EXCLUDED`. Posting recomputes the account's `book_balance_cents`.

A posted entry may be reversed, moving it from `POSTED` to `REVERSED`, provided it has not been cash-settled — a reversal of an entry whose `cash_settled` is true is rejected with `ERR_ENTRY_SETTLED` — and provided its account is not already `RECONCILED`, which is rejected with `ERR_ACCOUNT_RECONCILED`. Reversing an entry creates a brand-new `POSTED` ledger entry with the opposite `side`, the same `amount_cents`, and its `reversed_entry_id` set to the original entry's id; it then recomputes the account's `book_balance_cents`.

Once at least one entry has been posted to an account, a `Bookkeeper` categorizes that account, moving it from `DRAFT` to `CATEGORIZED`. Categorization is permitted only while the engagement is in `RECONSTRUCTION` (otherwise `ERR_INVALID_STATE`) and only when the account has at least one `POSTED` entry (otherwise `ERR_NO_POSTED_ENTRIES`); it recomputes `book_balance_cents` from the posted entries. A `Bookkeeper` may instead exclude an account that should not be part of the books. Excluding an account in `DRAFT` moves it directly to `EXCLUDED`. Excluding an account in `CATEGORIZED` also moves it to `EXCLUDED`, but is refused for a bank account that has a statement in `RECONCILING` or `RECONCILED` (rejected with `ERR_BANK_NOT_RECONCILED`). Either exclusion recomputes the engagement's `total_account_count`. `EXCLUDED` is terminal for an account.

### 3.4. Advancing to Reconciliation

When reconstruction is far enough along, the `EngagementManager` advances the engagement from `RECONSTRUCTION` to `RECONCILIATION`. This is gated by two conditions. There must be at least one account in `CATEGORIZED` or `RECONCILED` (otherwise `ERR_NO_CATEGORIZED_ACCOUNTS`), and no ledger entry on the engagement may remain in `DRAFT` — every entry must be `POSTED` (or `REVERSED`) first, since a lingering draft entry would mean the books are not fully recorded; an unposted entry blocks the advance with `ERR_UNPOSTED_ENTRIES`.

### 3.5. Bank and Credit Reconciliation

Reconciliation matches the firm's reconstructed books against what the bank actually reported. For each bank account, a `Bookkeeper` or `Reviewer` imports a `BankStatement` naming the `account_id`, the statement window `statement_start` and `statement_end` (inclusive ISO dates, with `statement_end` no earlier than `statement_start`), and the bank-reported `ending_balance_cents`. The import may also declare `deposits_in_transit_cents` (outstanding deposits not yet on the statement) and `outstanding_checks_cents` (checks not yet cleared), each defaulting to zero. A statement begins in `IMPORTED`.

A `Reviewer` then works the statement line by line, creating `ReconciliationItem` records against it. Each item names the `ledger_entry_id` being matched and the `statement_line_amount_cents` as the bank shows it, along with a `match_kind` of `EXACT` or `TOLERANCE` (defaulting to `EXACT`). An `EXACT` match requires the magnitudes to be equal; a `TOLERANCE` match allows the book and statement magnitudes to differ by up to 100 cents. An item that matches lands in `MATCHED`; one whose magnitudes differ beyond what its `match_kind` permits lands in `UNMATCHED`, and an item under dispute may read `DISPUTED`. Each item also records the `engagement_id` and the owning statement's `statement_id`, and when matched it links the book entry to it through the entry's `reconciliation_item_id`. Creating the first reconciliation item on a statement advances the statement from `IMPORTED` to `RECONCILING`, and is permitted only when the statement's account is genuinely a bank account (otherwise `ERR_NOT_BANK_ACCOUNT`).

A `Reviewer` finalizes the statement, moving it from `RECONCILING` to `RECONCILED`. Finalization first requires that no reconciliation item on the statement is still `UNMATCHED` or `DISPUTED` (otherwise `ERR_OPEN_RECON_ITEMS`). It then computes the reconciliation difference: take the statement's `ending_balance_cents`, add its `deposits_in_transit_cents`, subtract its `outstanding_checks_cents`, and from that adjusted bank figure subtract the account's `book_balance_cents`. If the absolute value of that difference is at most 100 cents — the boundary is inclusive, so a difference whose magnitude equals exactly 100 still reconciles — the statement becomes `RECONCILED`. Finalization then marks every linked ledger entry's `cash_settled` flag true and recomputes the engagement's `recon_status`. If instead the absolute difference exceeds 100 cents, finalization is rejected with `ERR_RECON_OUT_OF_BALANCE`, and the system opens a `BLOCKING` `UNRECONCILED_DIFF` exception on the account to track the out-of-balance condition.

A `Reviewer` signs off an account as reconciled, moving it from `CATEGORIZED` to `RECONCILED`, but only as an independent party: the reviewer must not be the same user who categorized the account, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Two further conditions apply. If the account is a bank account, one of its statements must already be `RECONCILED` (otherwise `ERR_BANK_NOT_RECONCILED`), and the account must have no open `UNRECONCILED_DIFF` exception (otherwise `ERR_OPEN_DIFF_EXCEPTION`). On sign-off the engagement's `reconciled_account_count` increases, and the engagement's `readiness_score` and `recon_status` are recomputed. The actual reconstructed volume of an engagement can be read back at any point after reconstruction as a chronologically derived count: it counts the `POSTED`, non-`REVERSED` ledger entries whose `txn_date` falls in the engagement's period, reports that as `actual_txn_volume` alongside the stored `estimated_txn_volume`, and gives the `variance` between them, computed as `actual_txn_volume` minus `estimated_txn_volume` (so a positive variance means more entries than forecast). This computed read is returned as a plain object with exactly these three fields and carries no `id`, timestamps, or `version`. This actual count is a different measure entirely from the forward forecast of section 3.2 — it ignores the estimate inputs and simply tallies real entries.

### 3.6. Exception Tracking

Exceptions are the system's mechanism for flagging problems that stand between the books and a clean tax handoff. A `Bookkeeper` or `Reviewer` opens an `Exception` against the engagement, naming the `account_id` it concerns and a `kind` of `MISSING_DOC`, `UNCATEGORIZED`, `UNRECONCILED_DIFF`, or `DUPLICATE`. An exception declares a `severity` of `NORMAL` or `BLOCKING` (defaulting to `NORMAL`); `BLOCKING` exceptions are the ones that suppress readiness and bar tax handoff. When the `kind` is `MISSING_DOC`, a `doc_due_date` (ISO date) for the requested document is required. Exceptions open in `OPEN`. Opening a `BLOCKING` exception recomputes the engagement's `open_blocking_exception_count` and `readiness_score`.

The exception lifecycle is cyclic for document chasing. A `Bookkeeper` may request documents on a `MISSING_DOC` exception, moving it from `OPEN` to `WAITING_DOCS` — this transition is allowed only for the `MISSING_DOC` kind, and requesting docs on any other kind is rejected with `ERR_INVALID_STATE`. When the documents arrive, the `Bookkeeper` records receipt, moving the exception back from `WAITING_DOCS` to `OPEN`. From either `OPEN` or `WAITING_DOCS`, a `Bookkeeper` may resolve the exception, moving it to `RESOLVED`. A `Reviewer` may instead waive an `OPEN` exception, moving it to `WAIVED`; waiving is forbidden for an `UNRECONCILED_DIFF` exception, which must be genuinely resolved rather than dismissed (rejected with `ERR_CANNOT_WAIVE_DIFF`). Both `RESOLVED` and `WAIVED` are terminal. Whenever a `BLOCKING` exception is resolved or waived, the engagement's `open_blocking_exception_count` and `readiness_score` are recomputed.

### 3.7. Quoting and Phase Billing

The billing track runs alongside the lifecycle. Once scope is locked, the `EngagementManager` requests a quote, which computes the engagement's fixed price — stored and exposed on the engagement as `fixed_price_cents`, and null before a quote is requested — and moves `billing_status` from `UNBILLED` to `QUOTED`. Quoting requires that `scope_locked` be true; quoting before scope is locked is rejected with `ERR_SCOPE_NOT_LOCKED`. The fixed price is a marginal, tiered function of the engagement's `estimated_txn_volume` and is not an average rate. The base fee covers the first 500 transactions at 50000 cents. For volume above 500 and up to 1500, each transaction beyond the first 500 adds 40 cents. For volume above 1500, the price is the base of 50000 cents, plus 40 cents for each of the 1000 transactions in the 500-to-1500 band, plus 30 cents for every transaction above 1500. Concretely: if the estimated volume is at most 500, the price is 50000 cents; if it is at most 1500, the price is 50000 cents plus 40 cents times the volume in excess of 500; otherwise the price is 50000 cents plus 40 cents times 1000 plus 30 cents times the volume in excess of 1500.

The manager plans the work as `Phase` records on the engagement, each with a one-based `phase_index` (unique per engagement; phases bill in ascending index order), a `label`, and a `weight_bp` giving that phase's share of the fixed price in basis points. Phases begin in `PLANNED`. To turn the plan into billable amounts, the manager generates phase amounts, which moves `billing_status` from `QUOTED` to `PHASED`. Generation requires that the phases' `weight_bp` values sum to exactly 10000 basis points (otherwise `ERR_PHASE_WEIGHTS_INVALID`). Generation then allocates the fixed price across the phases by a waterfall: order the phases by ascending `phase_index`; for every phase except the one with the highest index, set its `amount_cents` to the fixed price multiplied by that phase's `weight_bp`, divided by 10000, rounded half up to whole cents; then set the highest-index phase's `amount_cents` to the fixed price minus the sum of all the earlier phases' amounts, so the final phase absorbs the rounding remainder and the phase amounts sum to exactly the fixed price. Generation moves each phase from `PLANNED` to `BILLABLE`.

Phases are then invoiced and paid in order. The `EngagementManager` invoices a `BILLABLE` phase, moving it to `INVOICED`, but only after every lower-`phase_index` phase on the engagement is already `INVOICED` or `PAID` (otherwise `ERR_PHASE_ORDER`). Invoicing creates a `PhaseInvoice` naming its `phase_id`, in status `ISSUED`, snapshotting the phase's `amount_cents` into the invoice's own `amount_cents`. The manager records payment on an invoice, which sets the invoice's `status` to `PAID` and advances its phase from `INVOICED` to `PAID`. When the last phase becomes `PAID` — that is, once every phase on the engagement is `PAID` — the engagement's `billing_status` bubbles up automatically from `PHASED` to `SETTLED`. A `PhaseInvoice` may also read `VOID`.

### 3.8. Books-to-Tax Handoff

When the books are in balance and clear of blockers, a `TaxPreparer` builds the tax package, which moves the engagement from `RECONCILIATION` to `TAX_HANDOFF` and creates a `TaxPackage` in `BUILT`. Two preconditions gate the build, and they are evaluated with the blocking-exception check ahead of the balance check: first, the engagement must have no open blocking exceptions — `open_blocking_exception_count` must be zero, or the build is rejected with `ERR_BLOCKING_EXCEPTIONS_OPEN`; then, the engagement's `recon_status` must be `IN_BALANCE`, or the build is rejected with `ERR_RECON_NOT_IN_BALANCE`.

The package records the `basis` (`CASH` or `ACCRUAL`), copied from the client's `accounting_basis` at build time, and computes `net_book_income_cents`, the taxable book income under that basis. The computation considers only `POSTED`, non-`REVERSED` ledger entries whose `txn_date` lies within the engagement's `period_start` through `period_end` inclusive, on accounts that are not `EXCLUDED`. Income is the sum of `amount_cents` over qualifying entries on `INCOME` accounts with a `CREDIT` side; expense is the sum of `amount_cents` over qualifying entries on `EXPENSE` accounts with a `DEBIT` side; and `net_book_income_cents` is income minus expense. The basis decides which entries qualify. Under `ACCRUAL`, every qualifying posted entry counts regardless of cash settlement. Under `CASH`, only entries whose `cash_settled` flag is true count — unsettled invoiced income and accrued-but-unpaid expense are excluded, so the cash figure generally differs from the accrual figure on the very same set of entries.

A `TaxPreparer` hands off a `BUILT` package, moving it to `HANDED_OFF`, but only while the engagement has no open blocking exceptions (`open_blocking_exception_count` of zero; otherwise `ERR_BLOCKING_EXCEPTIONS_OPEN`). After handoff, a `TaxPreparer` may amend the package, moving it from `HANDED_OFF` to `AMENDED`, which recomputes `net_book_income_cents` under the same basis rules.

### 3.9. Completion and Ongoing-Service Conversion

The `EngagementManager` completes an engagement, moving it from `TAX_HANDOFF` to `COMPLETED`. Completion requires that the engagement's `billing_status` be `SETTLED` (otherwise `ERR_BILLING_NOT_SETTLED`) and that a tax package exist in `HANDED_OFF` (otherwise `ERR_TAX_NOT_HANDED_OFF`). On completion the system emits an immutable `CompletionReport` against the engagement, in status `FINAL`, snapshotting the engagement's `readiness_score` into `final_readiness_score`, its `reconciled_account_count`, and the `total_billed_cents` — the sum of `amount_cents` over the engagement's phase invoices whose status is not `VOID` at the moment of completion. A completion report, once created, cannot be changed.

An engagement may instead be cancelled. The `EngagementManager` cancels an engagement from `DRAFT`, from `SCOPING`, or from `RECONSTRUCTION`, moving it to `CANCELLED`. Cancelling from `RECONSTRUCTION` is refused if any phase invoice on the engagement is already `PAID` (rejected with `ERR_PAID_INVOICES_EXIST`); when cancellation from `RECONSTRUCTION` does proceed, any phases in `PLANNED` or `BILLABLE` remain as they are while the engagement's billing is frozen. `CANCELLED` and `COMPLETED` are the two terminal lifecycle outcomes.

Once the cleanup is winding down, the relationship can convert into an ongoing monthly service. The `EngagementManager` creates a `ServicePlan` on the engagement, naming the recurring `monthly_fee_cents` and the `conversion_date` (ISO date) on which ongoing service begins. A service plan starts in `PENDING`. The manager activates it, moving it from `PENDING` to `ACTIVE`, which is permitted only while the engagement's `workflow_status` is `TAX_HANDOFF` or `COMPLETED` (otherwise `ERR_INVALID_STATE`). Activation computes the prorated first-month fee, `first_month_prorated_cents`: let the day be the day-of-month of the `conversion_date` and let the number of days in that month be its full count; the remaining days, counted inclusively of the conversion day, are the days-in-month minus the day-of-month plus one; the prorated fee is the `monthly_fee_cents` multiplied by those remaining days, divided by the days in the month, rounded half up to whole cents. The manager may cancel a service plan from either `PENDING` or `ACTIVE`, moving it to `CANCELLED`, which is terminal.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including the state-transition operations that drive the engagement, account, entry, statement, phase, exception, tax-package and service-plan lifecycles — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a Client | EngagementManager |
| GET | `/clients/{clientId}` | Get a Client | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| GET | `/engagements` | List engagements; filter by client_id | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements` | Create a CleanupEngagement | EngagementManager |
| GET | `/engagements/{id}` | Get a CleanupEngagement with computed fields | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| GET | `/engagements/{id}/volume-actuals` | Computed read: actual reconstructed transaction volume | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/start-scoping` | Move engagement DRAFT → SCOPING | EngagementManager |
| POST | `/engagements/{id}/advance-to-reconciliation` | Move engagement RECONSTRUCTION → RECONCILIATION | EngagementManager |
| POST | `/engagements/{id}/quote` | Compute fixed price and move billing UNBILLED → QUOTED | EngagementManager |
| POST | `/engagements/{id}/complete` | Move engagement TAX_HANDOFF → COMPLETED and emit CompletionReport | EngagementManager |
| POST | `/engagements/{id}/cancel` | Cancel an engagement | EngagementManager |
| POST | `/engagements/{id}/scope-estimates` | Create a ScopeEstimate | EngagementManager |
| GET | `/engagements/{id}/scope-estimates` | List ScopeEstimates for an engagement | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/scope-estimates/{eid}/accept` | Accept a ScopeEstimate; lock scope and advance to RECONSTRUCTION | EngagementManager |
| POST | `/engagements/{id}/accounts` | Create a LedgerAccount | Bookkeeper, EngagementManager |
| GET | `/engagements/{id}/accounts` | List LedgerAccounts; filter by status | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| GET | `/accounts/{accountId}` | Get a LedgerAccount | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/accounts/{aid}/categorize` | Categorize a LedgerAccount (DRAFT → CATEGORIZED) | Bookkeeper |
| POST | `/engagements/{id}/accounts/{aid}/mark-reconciled` | Mark a LedgerAccount RECONCILED | Reviewer |
| POST | `/engagements/{id}/accounts/{aid}/exclude` | Exclude a LedgerAccount (→ EXCLUDED) | Bookkeeper |
| POST | `/engagements/{id}/entries` | Create a draft LedgerEntry | Bookkeeper |
| GET | `/engagements/{id}/entries` | List LedgerEntries; filter by account/status | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/entries/{eid}/post` | Post a LedgerEntry (DRAFT → POSTED) | Bookkeeper |
| POST | `/engagements/{id}/entries/{eid}/reverse` | Reverse a POSTED LedgerEntry | Bookkeeper |
| POST | `/engagements/{id}/statements` | Import a BankStatement | Bookkeeper, Reviewer |
| GET | `/engagements/{id}/statements` | List BankStatements; filter by account/status | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/statements/{sid}/finalize` | Finalize reconciliation (RECONCILING → RECONCILED) | Reviewer |
| POST | `/engagements/{id}/statements/{sid}/reconciliation-items` | Match a LedgerEntry to a statement line | Reviewer |
| GET | `/engagements/{id}/statements/{sid}/reconciliation-items` | List ReconciliationItems for a statement | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| GET | `/reconciliation-items` | List ReconciliationItems; filter by entry/statement | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/phases` | Create a Phase | EngagementManager |
| GET | `/engagements/{id}/phases` | List Phases for an engagement | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/phases/generate` | Compute phase amounts and move billing QUOTED → PHASED | EngagementManager |
| POST | `/engagements/{id}/phases/{pid}/invoice` | Invoice a BILLABLE Phase (creates PhaseInvoice) | EngagementManager |
| POST | `/engagements/{id}/invoices/{iid}/pay` | Mark a PhaseInvoice PAID (may settle billing) | EngagementManager |
| GET | `/engagements/{id}/invoices` | List PhaseInvoices; filter by phase/status | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/tax-packages` | Build a TaxPackage (RECONCILIATION → TAX_HANDOFF) | TaxPreparer |
| GET | `/engagements/{id}/tax-packages` | List TaxPackages for an engagement | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/tax-packages/{tid}/handoff` | Hand off a TaxPackage (BUILT → HANDED_OFF) | TaxPreparer |
| POST | `/engagements/{id}/tax-packages/{tid}/amend` | Amend a TaxPackage (HANDED_OFF → AMENDED) | TaxPreparer |
| POST | `/engagements/{id}/service-plans` | Create a ServicePlan | EngagementManager |
| GET | `/engagements/{id}/service-plans` | List ServicePlans for an engagement | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/service-plans/{spid}/activate` | Activate a ServicePlan (PENDING → ACTIVE) | EngagementManager |
| POST | `/engagements/{id}/service-plans/{spid}/cancel` | Cancel a ServicePlan (→ CANCELLED) | EngagementManager |
| POST | `/engagements/{id}/exceptions` | Open an Exception | Bookkeeper, Reviewer |
| GET | `/engagements/{id}/exceptions` | List Exceptions; filter by account/kind/status/severity | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |
| POST | `/engagements/{id}/exceptions/{xid}/request-docs` | Move a MISSING_DOC Exception OPEN → WAITING_DOCS | Bookkeeper |
| POST | `/engagements/{id}/exceptions/{xid}/docs-received` | Move an Exception WAITING_DOCS → OPEN | Bookkeeper |
| POST | `/engagements/{id}/exceptions/{xid}/resolve` | Resolve an Exception (→ RESOLVED) | Bookkeeper |
| POST | `/engagements/{id}/exceptions/{xid}/waive` | Waive an Exception (→ WAIVED) | Reviewer |
| GET | `/engagements/{id}/completion-report` | Get the engagement's CompletionReport(s), returned as a paginated array envelope (`response_type` of "array") | EngagementManager, Bookkeeper, Reviewer, TaxPreparer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ENTRY_OUT_OF_PERIOD` | 409 Conflict |
| `ERR_ACCOUNT_EXCLUDED` | 409 Conflict |
| `ERR_ENTRY_SETTLED` | 409 Conflict |
| `ERR_ACCOUNT_RECONCILED` | 409 Conflict |
| `ERR_NO_POSTED_ENTRIES` | 409 Conflict |
| `ERR_NO_CATEGORIZED_ACCOUNTS` | 409 Conflict |
| `ERR_UNPOSTED_ENTRIES` | 409 Conflict |
| `ERR_NOT_BANK_ACCOUNT` | 409 Conflict |
| `ERR_OPEN_RECON_ITEMS` | 409 Conflict |
| `ERR_RECON_OUT_OF_BALANCE` | 409 Conflict |
| `ERR_BANK_NOT_RECONCILED` | 409 Conflict |
| `ERR_OPEN_DIFF_EXCEPTION` | 409 Conflict |
| `ERR_RECON_NOT_IN_BALANCE` | 409 Conflict |
| `ERR_BLOCKING_EXCEPTIONS_OPEN` | 409 Conflict |
| `ERR_PHASE_WEIGHTS_INVALID` | 409 Conflict |
| `ERR_PHASE_ORDER` | 409 Conflict |
| `ERR_SCOPE_NOT_LOCKED` | 409 Conflict |
| `ERR_BILLING_NOT_SETTLED` | 409 Conflict |
| `ERR_TAX_NOT_HANDED_OFF` | 409 Conflict |
| `ERR_PAID_INVOICES_EXIST` | 409 Conflict |
| `ERR_CANNOT_WAIVE_DIFF` | 409 Conflict |
| `ERR_DUPLICATE_ACCOUNT_CODE` | 409 Conflict |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 Precondition Failed |
