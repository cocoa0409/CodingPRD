# Fractional CFO Accounting API — Product Requirements Document

## 1. Introduction

Small and mid-sized businesses rarely employ a full finance department, yet they still carry the full weight of a finance department's obligations: a clean general ledger, a disciplined monthly close, timely accounts-receivable collection, controlled accounts-payable disbursement, coordinated payroll, defensible cash-flow forecasts, and an annual tax package an external preparer can actually use. This API backs a fractional-CFO practice that delivers all of that as an outsourced service. A single platform tracks each client from the first sales lead through ledger setup and engagement activation, then carries them month after month through bookkeeping closes, billing, advisory, and tax-prep handoff.

The product's hardest requirements are not the individual records but the relationships and lifecycles that bind them. A client advances along two independent axes at once — an onboarding axis that provisions the engagement and an engagement axis that governs billing — and the two interact only at carefully defined gates. A monthly close is not a single status field but a roll-up of weighted checklist tasks, shadowed by a parallel review track. Retainer billing reads tiered pricing and surcharge inputs off the client at the instant of issuance, so two requests that differ only in timing can mint different invoices. Catch-up cleanup projects loop through revision cycles; tax handoffs fork into two review branches that must rejoin; cash-flow forecasts are gated by bank-covenant floors; and payroll cost is split across departments with a remainder-reconciliation rule that must reconcile to the penny. The sections below specify these behaviors precisely so that an implementation, and the test suite that grades it, agree on every threshold, every cascade, and every rejection.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint. Where a business rule lives more naturally beside a specific workflow, it appears in Section 3 instead; this section carries the cross-cutting concerns.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `CFO`, `Bookkeeper`, `ClientContact`, and `PlatformAdmin`. When a recognized role attempts an operation the RBAC matrix does not grant it, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles divide the work along ownership lines. The `CFO` is the fractional Chief Financial Officer: they own onboarding sign-offs, the engagement lifecycle, all approvals and finalizations, advisory work, billing, and forecasts. The `Bookkeeper` is the outsourced bookkeeper: they own ledger setup, day-to-day bookkeeping, accounts-payable entry and scheduling, payroll allocation, and the books branch of tax review. The `ClientContact` represents the client and reviews catch-up work, disputes invoices, approves or rejects catch-up projects, and pays retainer invoices. The `PlatformAdmin` is an operational administrator who controls the logical clock and performs read-only oversight; they are not a domain actor in the accounting sense.

The relationship between `X-User-ID` and the data differs by role. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; any ownership check on a resource that references a `Client` compares that resource's `client_id` to `X-User-ID`. For the other three roles — `CFO`, `Bookkeeper`, and `PlatformAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0; a negative offset is not permitted. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless an endpoint specifies otherwise, every list is sorted by the resource's creation timestamp, `created_at`, in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Almost every resource in this system also carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and an integer `version` that begins at the resource's creation value and increments by one on each mutation. The `version` field underpins optimistic concurrency control as described in §2.7. Every entity in this domain — `Client`, `LedgerAccount`, `CatchupProject`, `MonthlyClose`, `CloseTask`, `ARInvoice`, `APBill`, `PayrollRun`, `PayrollAllocation`, `CashFlowForecast`, `ForecastLine`, `TaxHandoff`, and `RetainerInvoice` — exposes the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Derived-Field Reconciliation

Several fields are not written directly by clients but are reconciled by the server whenever an event makes them stale; each such reconciliation is itself a mutation that refreshes `updated_at` and increments `version` on the entity it lands on. A `Client` carries three reconciled fields. Its `included_txn_count` is copied from the tier table the moment `retainer_tier` is set, taking the value 200 for `ESSENTIALS`, 500 for `GROWTH`, and 1200 for `CFO`. Its `catchup_active` flag is true exactly when the client owns at least one `CatchupProject` whose status is `SCOPED` or `IN_PROGRESS`, and is reconciled whenever a catch-up project changes state. Its `open_close_count` is the number of `MonthlyClose` rows for the client whose status is anything other than `FINALIZED`, and it is reconciled on every monthly-close mutation — incremented when a close is opened and decremented when one is finalized.

A `MonthlyClose` carries two reconciled completion figures, `completion_pct` and `provisional_completion_pct`, both recomputed from scratch on every change to one of its `CloseTask` children (see §3.4 for the formulas). A `CashFlowForecast` carries `ending_balance_cents` and `min_projected_balance_cents`, both recomputed on every change to its `ForecastLine` children (see §3.7). A `PayrollAllocation` carries `allocated_cents`, set when its parent run is allocated and zeroed when the run is reversed (see §3.6). A `RetainerInvoice` carries `base_fee_cents`, `overage_cents`, `surcharge_cents`, and `total_cents`, all computed once at issuance (see §3.8). A `CatchupProject` carries `revision_rounds`, incremented each time the project is rejected back into rework. When a parent's state is driven by its children — as with a monthly close whose status follows its tasks — the server performs the transition automatically when the children's criteria are met, without an explicit client request on the parent.

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are stored and exchanged as integer cents. Where a calculation produces a fractional cent — the metered overage on a retainer invoice, the catch-up surcharge, the per-department payroll split, the DSO ratios — the result is rounded half up. Concretely, a value whose fractional part is exactly one half rounds away from zero to the next whole unit. The two percentage figures on a monthly close and the two DSO figures on the AR summary are rounded half up to two decimal places. Cash-flow balances require no rounding because every `ForecastLine` amount is already an integer number of cents; the running and minimum balances are simple integer sums.

### 2.7. Optimistic Concurrency Control

Two write operations in this system are guarded against stale-version overwrites, and both guard against a stale view of the parent `Client`. Approving a cash-flow forecast and issuing a retainer invoice each require the caller to submit `expected_client_version` carrying the `version` of the target `Client` the caller last observed. The server compares that value to the client's current `version`; if they differ — because some other writer has advanced the client since the caller read it — the write is rejected with `ERR_STALE_VERSION` (HTTP 412). These are stale-version comparisons, not timing conditions: the rejection depends only on whether the submitted version matches the persisted one, never on whether requests overlap. The two affected operations are detailed in §3.7 and §3.8, where the reason each needs a fresh client view is explained. No other endpoint takes a version field; an endpoint not named here performs its mutation without any concurrency check.

### 2.8. Nested Resource Retrieval and Referential Existence

Many paths address a resource nested under a parent, and many request bodies carry foreign-key references. The server validates existence left to right: every identifier in the path is checked in order before any body reference, and the first identifier that does not resolve to an existing resource causes an immediate `ERR_NOT_FOUND`. Only once every path and body reference resolves does the server evaluate state and business rules. List endpoints that hang off a parent — a client's ledger accounts, a close's tasks, a run's allocations (each `PayrollAllocation` referencing its run by `payroll_run_id`), a forecast's lines (each `ForecastLine` referencing its forecast by `forecast_id`), and the like — return only the children that reference the named parent, providing reverse reachability from a parent down to the rows that point back to it.

### 2.9. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or unknown header pair yields `ERR_UNAUTHENTICATED`. Role authorization comes next, yielding `ERR_FORBIDDEN_ROLE`. Then existence of every referenced resource is checked, yielding `ERR_NOT_FOUND`. For a state-transition endpoint, the system then confirms the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE` if not. Only after these four gates pass does the server evaluate the operation's specific business constraints — onboarding completeness, open-close counts, December-close finalization, payroll-close finalization, ledger-account presence, cross-client parents, duplicate codes, duplicate periods, pay-period overlaps, covenant floors, underpayments, missing schedule dates, and the stale-version check — followed last by generic request-shape validation that catches a missing or wrong-typed field with `ERR_INVALID_REQUEST`. The shape and enum checks that carry their own dedicated codes (`ERR_INVALID_PERIOD`, `ERR_INVALID_TASK_STATUS`, `ERR_NEGATIVE_AMOUNT`) are evaluated as part of the same business-constraint stage that guards their respective endpoints.

### 2.10. The Logical Clock

Accounts-receivable and accounts-payable aging, and the dating of forecast movements, are measured against a server-controlled logical clock rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any administrator sets it, every aging and date-window computation uses that default — the server never falls back to real time. A `PlatformAdmin` may advance or reset the clock by supplying a `to_iso8601` instant; this capability exists so that aging buckets and date windows can be exercised deterministically.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Engagement — Two Independent Axes

A client record is the root of everything else, and a `CFO` (or a `PlatformAdmin`) creates one by supplying the `legal_name`, the two-letter uppercase `state_code` of incorporation, and the `retainer_tier`, which must be one of `ESSENTIALS`, `GROWTH`, or `CFO`. An optional `covenant_floor_cents` may be supplied to declare the minimum projected cash balance the client's bank covenant requires; when omitted it is zero. At creation the tier's included transaction volume is copied into `included_txn_count`, and the client begins life with `onboarding_status` of `LEAD` and `engagement_status` of `PROSPECT`. These two status fields move along completely independent axes, and most lifecycle subtlety in this domain comes from how they interact only at one gate.

The **onboarding axis** runs `LEAD → KICKOFF_SCHEDULED → LEDGER_SETUP → ONBOARDED`. From `LEAD`, scheduling the kickoff — a `CFO` action permitted only while `onboarding_status` is `LEAD` — advances it to `KICKOFF_SCHEDULED`. From there, the `Bookkeeper` starting ledger setup (permitted only while `onboarding_status` is `KICKOFF_SCHEDULED`) advances it to `LEDGER_SETUP`. Completing onboarding, a `CFO` action permitted only while `onboarding_status` is `LEDGER_SETUP`, advances it to `ONBOARDED`; this transition additionally requires that the client already have at least one `LedgerAccount` whose `status` is `ACTIVE`, and is otherwise rejected with `ERR_NO_LEDGER_ACCOUNTS`. Each of these three transitions increments the client's `version`.

The **engagement axis** runs over `PROSPECT`, `ACTIVE`, `PAUSED`, and the terminal `OFFBOARDED`. Activating the engagement — a `CFO` action — is the single point where the two axes touch: it is allowed only when `engagement_status` is `PROSPECT` or `PAUSED`, and in both cases it additionally requires that `onboarding_status` already be `ONBOARDED`; an attempt while onboarding is incomplete is rejected with `ERR_ONBOARDING_INCOMPLETE`. A successful activation sets `engagement_status` to `ACTIVE`. A `CFO` may pause an `ACTIVE` engagement, moving it to `PAUSED`, and may reactivate a `PAUSED` engagement back to `ACTIVE` under the same onboarding precondition. Offboarding is a `CFO` action permitted when `engagement_status` is either `ACTIVE` or `PAUSED`; it additionally requires `open_close_count` to be zero — that is, the client may not be offboarded while any non-finalized monthly close remains — and is otherwise rejected with `ERR_OPEN_CLOSES_EXIST`. A successful offboard sets `engagement_status` to `OFFBOARDED` and, as a cascade, transitions every one of the client's catch-up projects in `DRAFT`, `SCOPED`, `IN_PROGRESS`, `CLIENT_REVIEW`, or `REVISION` to `CANCELLED`. Each engagement transition increments the client's `version`. Clients may be listed with pagination and an optional `engagement_status` filter; both onboarding actions and engagement actions, when attempted from a state the transition is not defined for, are rejected with `ERR_INVALID_STATE`.

### 3.2. The Chart of Accounts

Ledger setup builds a client's chart of accounts as a self-referential tree. A `Bookkeeper` or `CFO` creates an account by supplying the `account_code` — a numeric code string — together with the `account_type`, which classifies the account as one of `ASSET`, `LIABILITY`, `EQUITY`, `REVENUE`, or `EXPENSE`, and a human-readable `name`. An optional `parent_account_id` places the new account beneath an existing one in the tree; when omitted the account is top-level. Behind the scenes each account also records the `client_id` of the client whose books it belongs to. A new account is born with `status` of `ACTIVE`.

Two constraints guard account creation. First, when a `parent_account_id` is supplied, it must reference an `ACTIVE` account belonging to the *same* client; a parent that lives under a different client, or a parent that is not `ACTIVE`, is a cross-client reference and is rejected with `ERR_CROSS_CLIENT_PARENT`. Second, the `account_code` must be unique among the client's non-`ARCHIVED` accounts; reusing a code already held by an `ACTIVE` account of the same client is rejected with `ERR_DUPLICATE_ACCOUNT_CODE`. A `CFO` may later archive an account, moving its `status` from `ACTIVE` to `ARCHIVED`; an archived code is freed for reuse because uniqueness is enforced only across non-archived rows. The tree can be navigated both downward — listing the children whose `parent_account_id` points at a given account — and per client, and the presence of at least one `ACTIVE` account is what unblocks the onboarding completion described in §3.1.

### 3.3. Catch-Up and Cleanup Projects

When a client arrives with historical books in disarray, a `CFO` opens a catch-up/cleanup project by supplying `months_behind` (the count of historical months needing cleanup, which must be an integer of at least 1) and the one-time `quoted_fee_cents`. The project begins in `DRAFT` and carries a `revision_rounds` counter that starts at zero. Its lifecycle is deliberately cyclic, looping through client review and revision as many times as the client demands.

Scoping the project — a `CFO` action permitted only from `DRAFT` — moves it to `SCOPED` and sets the owning client's `catchup_active` flag to true (reconciled per §2.5). A `Bookkeeper` then starts the work, moving `SCOPED → IN_PROGRESS`, and later submits it for review, moving `IN_PROGRESS → CLIENT_REVIEW`. From `CLIENT_REVIEW` the `ClientContact` decides: rejecting the work moves it `CLIENT_REVIEW → REVISION` and increments `revision_rounds` by one (this is the cycle entry), while approving it moves it `CLIENT_REVIEW → COMPLETED`. A `Bookkeeper` resubmitting from `REVISION` moves it back `REVISION → CLIENT_REVIEW`, closing the loop; `revision_rounds` therefore accumulates across however many rejection cycles occur. A `CFO` may cancel the project from any non-terminal state — `DRAFT`, `SCOPED`, `IN_PROGRESS`, `CLIENT_REVIEW`, or `REVISION` — moving it to `CANCELLED`.

Both terminal transitions touch the client. Reaching `COMPLETED` and reaching `CANCELLED` each clear the client's `catchup_active` flag back to false, unless the client still owns another catch-up project in `SCOPED` or `IN_PROGRESS` that keeps the flag true; in either case the client's `version` is incremented as part of the reconciliation, and the scope transition into `SCOPED` likewise increments it. Because `catchup_active` feeds the retainer surcharge described in §3.8, the exact moment a project enters or leaves the active set is what determines whether a retainer invoice carries a surcharge. Any of these project transitions attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.4. The Monthly Close — A Roll-Up With a Parallel Review Track

A monthly bookkeeping close is opened by a `Bookkeeper` or `CFO` for a client and a specific period, supplying `period_year` and `period_month`; an optional `txn_count` records how many bookkeeping transactions the period carried and defaults to zero. The `period_month` must be an integer from 1 through 12, and a month outside that range is rejected with `ERR_INVALID_PERIOD`. A close opens with `status` of `OPEN` and `review_status` of `NOT_STARTED`, and opening it increments the client's `open_close_count`. Two closes for the same client and the same `(period_year, period_month)` may not both be non-finalized; attempting a second open close for a period the client already has open is rejected with `ERR_DUPLICATE_PERIOD`.

The close's `status` is not set directly — it is a compound status that rolls up from a checklist of `CloseTask` children. A `Bookkeeper` or `CFO` adds a task by supplying its `name` and an integer `weight` of at least 1; the task is born `PENDING`. A task moves between `PENDING`, `IN_REVIEW`, `DONE`, `WAIVED`, and `BLOCKED` by a transition request that supplies the target `to_status`; when moving a task to `BLOCKED`, an optional `blocking_reason` may accompany it. A `to_status` that is not one of the five `CloseTask` statuses is rejected with `ERR_INVALID_TASK_STATUS`.

Two completion percentages are recomputed on the parent close after every task create or transition, both derived the same way and differing only in which statuses count as "complete." Let the **total weight** be the sum of the `weight` of every task on the close, counting `BLOCKED` and `PENDING` tasks in that denominator even though they contribute nothing to the numerator. If the total weight is zero, both percentages are zero. Otherwise `completion_pct` — the **final** figure — is the sum of the weights of tasks that are `DONE` or `WAIVED`, divided by the total weight, multiplied by 100, and rounded half up to two decimal places. The `provisional_completion_pct` — the **provisional** figure that drives the dashboard — is computed identically except that its numerator also counts `IN_REVIEW` tasks as complete; for identical task data it is therefore always at least as large as the final figure.

These percentages drive automatic status changes on the close, performed by the server with no explicit request on the close itself. While a close is `OPEN`, the first `CloseTask` to move out of `PENDING` advances the close `OPEN → IN_PROGRESS`. Once the final `completion_pct` reaches exactly 100 — meaning every task is `DONE` or `WAIVED` — an `IN_PROGRESS` close advances `IN_PROGRESS → READY_FOR_REVIEW` and, on the parallel review axis, its `review_status` moves to `UNDER_REVIEW`. The review axis is then driven by the `CFO`. Approving the review is a parallel-axis-only action: it requires the close to be `READY_FOR_REVIEW` with `review_status` of `UNDER_REVIEW`, and it advances `review_status` to `APPROVED` while leaving `status` at `READY_FOR_REVIEW`. Finalizing the close is a `CFO` action permitted only when `status` is `READY_FOR_REVIEW` and `review_status` is `APPROVED`; it moves the close `READY_FOR_REVIEW → FINALIZED`, decrements the client's `open_close_count` (reconciled), and increments the close's `version`.

Review can also push the close backward. Requesting changes is a `CFO` action permitted when the close is `READY_FOR_REVIEW` with `review_status` of `UNDER_REVIEW`; the caller supplies `changed_task_names`, the list of task names to reopen. The close moves `READY_FOR_REVIEW → REOPENED`, its `review_status` becomes `CHANGES_REQUESTED`, every `DONE` task whose `name` appears in `changed_task_names` is reset to `PENDING`, and the two completion percentages are recomputed. Once reopened, the close behaves like an open one: the next task on a `REOPENED` close to move out of `PENDING` advances it `REOPENED → IN_PROGRESS` and resets `review_status` to `NOT_STARTED`. Any of these close or task transitions attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`. Each close exposes lists of its tasks, its payroll runs, and its retainer invoices.

### 3.5. Accounts Receivable and Accounts Payable

A `Bookkeeper` or `CFO` records a receivable by creating an invoice for a client with the `counterparty_name` of the customer who owes it, the `amount_cents` owed (an integer of at least 1), the `issue_date`, and the `due_date`; aging buckets on the AR summary are measured from `due_date` against the logical clock. The invoice begins `OPEN` with `paid_amount_cents` of zero. From `OPEN`, a `ClientContact` may dispute the invoice (`OPEN → DISPUTED`) and a `Bookkeeper` may later resolve the dispute (`DISPUTED → OPEN`). A `Bookkeeper` records a payment by supplying `payment_cents`; the payment is added to `paid_amount_cents`, and the invoice moves `OPEN → PAID`. Crucially, partial payments are not accepted: a payment is allowed only when the resulting `paid_amount_cents` would reach or exceed `amount_cents`, and a payment that would leave the cumulative paid amount below the invoice total is rejected with `ERR_UNDERPAYMENT`. A `CFO` may instead write an `OPEN` invoice off (`OPEN → WRITTEN_OFF`). An amount below 1 on creation is rejected with `ERR_NEGATIVE_AMOUNT`.

The AR summary endpoint aggregates a client's outstanding receivables and computes Days Sales Outstanding in two variants. The caller supplies `credit_sales_cents` as a query input. The system considers only invoices in `OPEN` or `DISPUTED` status — `PAID` and `WRITTEN_OFF` invoices are excluded entirely. The **gross outstanding** is the sum, over those `OPEN` and `DISPUTED` invoices, of `amount_cents` minus `paid_amount_cents`; the **net outstanding** is the same sum restricted to `OPEN` invoices only, so it omits disputed balances. The gross DSO is the gross outstanding divided by `credit_sales_cents`, multiplied by a fixed 30-day window, rounded half up to two decimal places; the net DSO is computed the same way from the net outstanding. When `credit_sales_cents` is zero, both DSO figures are reported as zero rather than dividing by zero. Because disputed balances inflate the gross numerator but not the net one, for identical data the net DSO never exceeds the gross DSO. The summary response reports the gross outstanding as `gross_outstanding_cents`, the net outstanding as `net_outstanding_cents`, the two ratios as `dso_gross` and `dso_net`, and four aging buckets — `bucket_current_cents`, `bucket_1_30_cents`, `bucket_31_60_cents`, and `bucket_61_plus_cents` — sorted by how far past `due_date` each invoice has aged against the logical clock.

On the payable side, a `Bookkeeper` enters a bill for a client with the `vendor_name`, the `amount_cents` due (an integer of at least 1), and the `due_date`; it begins in `ENTERED`. The bill then flows through an approval and payment pipeline that enforces segregation of duties: a `CFO`, who must not be the bookkeeper who entered the bill, approves it (`ENTERED → APPROVED`). A `Bookkeeper` schedules an approved bill (`APPROVED → SCHEDULED`) by supplying the `scheduled_pay_date`, which is required for this step — scheduling without it is rejected with `ERR_MISSING_SCHEDULE_DATE`. A `Bookkeeper` then marks a scheduled bill paid (`SCHEDULED → PAID`). At any point while the bill is still `ENTERED` or `APPROVED`, a `CFO` may void it (`→ VOID`). A bill amount below 1 is rejected with `ERR_NEGATIVE_AMOUNT`, and any of these AP or AR transitions attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.6. Payroll Coordination and Cost Allocation

Payroll is coordinated per client and tied to a close period. A `Bookkeeper` creates a run by supplying the `monthly_close_id` of the close it posts into, the `pay_date`, the half-open pay period bounded by `pay_period_start` (inclusive) and `pay_period_end` (exclusive), and the `total_employer_cost_cents` — the full employer cost of wages plus taxes, an integer of at least 1. The run begins in `DRAFT`. A client's pay periods may not overlap: a new run whose half-open interval from `pay_period_start` up to but not including `pay_period_end` overlaps the interval of any existing non-`REVERSED` run for the same client is rejected with `ERR_PAY_PERIOD_OVERLAP`. Adjacency does not count as overlap — one period ending exactly where the next begins is allowed, because the intervals are half-open. A `total_employer_cost_cents` below 1 is rejected with `ERR_NEGATIVE_AMOUNT`.

Before allocation, a `Bookkeeper` adds one or more department lines to the `DRAFT` run, each supplying a `department_name` and that department's `dept_gross_cents` — the department's gross wages, an integer of at least 1, which serves as the weight for splitting the total. Each allocation line is born with `allocated_cents` of zero, and a `dept_gross_cents` below 1 is rejected with `ERR_NEGATIVE_AMOUNT`. Allocating the run — a `Bookkeeper` action permitted only from `DRAFT` and requiring at least one allocation line to exist — moves it `DRAFT → ALLOCATED` and runs the cost-allocation algorithm across the lines.

The allocation must reconcile to the penny, and it does so with a pinned per-line-then-remainder rule. First, the sum of all departments' `dept_gross_cents` is taken. For each line, a raw share is computed as `total_employer_cost_cents` multiplied by that line's `dept_gross_cents`, divided by the sum of gross, rounded half up to whole cents. These rounded shares are summed, and the leftover remainder — the run's `total_employer_cost_cents` minus the sum of the rounded shares — is added in full to a single recipient line: the line with the largest `dept_gross_cents`, breaking a tie in favor of the earliest `created_at`. Each line's final `allocated_cents` is its rounded share, with the chosen recipient additionally carrying the remainder. Because the remainder is reconciled onto exactly one line rather than left to drift, the sum of every line's `allocated_cents` equals the run's `total_employer_cost_cents` exactly.

Posting the run is a `CFO` action permitted only from `ALLOCATED`, moving it `ALLOCATED → POSTED`; it requires the linked `MonthlyClose` not be `FINALIZED`, and posting into a finalized close is rejected with `ERR_CLOSE_FINALIZED`. Reversing the run is a `CFO` action permitted only from `POSTED`, moving it `POSTED → REVERSED`; reversal is likewise blocked when the linked close is `FINALIZED`, again with `ERR_CLOSE_FINALIZED`. As compensation, reversing the run sets every one of its `PayrollAllocation` lines' `allocated_cents` back to zero, draining the run's allocation. A run's allocation lines can be listed, and runs can be listed per client (optionally filtered by `status` or `monthly_close_id`) and per close. Any payroll transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.7. Cash-Flow Forecasting and the Covenant Gate

A `CFO` builds a cash-flow forecast for a client by supplying the `opening_balance_cents` that seeds the horizon. The forecast begins in `DRAFT` with both its `ending_balance_cents` and `min_projected_balance_cents` initialized to the opening balance. The `CFO` then adds projected movements as forecast lines, each supplying an `effective_date`, a `direction` of either `INFLOW` or `OUTFLOW`, and an `amount_cents` magnitude (an integer of at least 1). Adding a line recomputes the forecast's two balances.

The projection walks the lines in chronological order — sorted by `effective_date` ascending, breaking ties by `created_at` ascending — starting from a running balance equal to `opening_balance_cents`. Each `INFLOW` line adds its `amount_cents` to the running balance and each `OUTFLOW` line subtracts its `amount_cents`. The `ending_balance_cents` is the running balance after the last line. The `min_projected_balance_cents` is the lowest value the running balance ever takes across the walk, where the opening balance itself is the first candidate for that minimum; whenever an outflow dips the running balance below where it ends, the minimum is strictly below the ending balance.

Approving a forecast is the gated step. It is a `CFO` action permitted only from `DRAFT`, and it carries the optimistic-concurrency obligation from §2.7: the request must include `expected_client_version` matching the target client's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The reason the fresh client view matters is that approval is checked against the client's `covenant_floor_cents`, which a concurrent change may have just reset, and a newly approved forecast supersedes any prior approved one for the client; approving off a stale client view risks checking against an out-of-date floor. The covenant gate itself requires the forecast's `min_projected_balance_cents` to be at or above the client's `covenant_floor_cents` — that is, the minimum projected balance must be greater than or equal to the floor — and an approval whose minimum falls below the floor is rejected with `ERR_COVENANT_BREACH`. On success the forecast moves `DRAFT → APPROVED`, every other `APPROVED` forecast for the same client is superseded (`→ SUPERSEDED`), and the client's `version` is incremented. An approval attempted on a forecast that is not `DRAFT` is rejected with `ERR_INVALID_STATE`.

### 3.8. Tier Billing and the Retainer Invoice

Retainer billing is where tiered pricing, metered overage, and the catch-up surcharge all come together, and it is the second optimistic-concurrency-guarded write. A `CFO` issues a retainer invoice for a client by naming the `monthly_close_id` whose transaction count drives the metered portion and supplying `expected_client_version`. As with forecast approval, the supplied `expected_client_version` must equal the client's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); this guard matters because both the surcharge eligibility and the included transaction volume are read off the client at the instant of issuance, so a tier change or a catch-up transition that bumped the client's `version` would otherwise let the invoice be minted off out-of-date pricing inputs. The issued invoice begins with `status` of `ISSUED`, and issuing it increments the client's `version`.

The invoice amount is built from three computed parts, all in integer cents. The **base fee**, stored as `base_fee_cents`, is the flat fee for the client's `retainer_tier`: $1,500.00 (150000 cents) for `ESSENTIALS`, $3,000.00 (300000 cents) for `GROWTH`, and $6,000.00 (600000 cents) for `CFO`. The **overage**, stored as `overage_cents`, meters transactions above the tier's included volume: the named close's `txn_count` minus the tier's included transactions, floored at zero so an under-volume month carries no overage, multiplied by the tier's per-transaction overage rate. Each tier's included volume and per-transaction rate are paired with its base, where every rate is expressed in milli-dollars (thousandths of a dollar): `ESSENTIALS` includes 200 transactions and charges 750 milli-dollars ($0.75, i.e. 75 cents) per overage transaction; `GROWTH` includes 500 transactions at 600 milli-dollars ($0.60, i.e. 60 cents) each; and `CFO` includes 1,200 transactions at 450 milli-dollars ($0.45, i.e. 45 cents) each. Because the rate is given in thousandths of a dollar, the overage in cents is the number of overage transactions multiplied by that milli-dollar rate, then divided by ten, with the result rounded half up to whole cents. The **surcharge**, stored as `surcharge_cents`, applies only when the client's `catchup_active` flag is true at the instant of issuance: it is 20 percent of the tier base fee, rounded half up to whole cents. When `catchup_active` is false at issuance the surcharge is zero, so two invoices issued off identical close data — one with an active catch-up project, one without — produce different totals. The `total_cents` is the straightforward sum of `base_fee_cents`, `overage_cents`, and `surcharge_cents`. A `ClientContact` or `CFO` may later pay the invoice (`ISSUED → PAID`), and an invoice may be listed per client and per close. A pay attempted on an invoice that is not `ISSUED` is rejected with `ERR_INVALID_STATE`.

### 3.9. Tax-Prep Handoff — Fork, Join, and Delivery

The annual tax package is assembled and handed to an external preparer through a fork-join workflow. A `CFO` creates a handoff for a client by supplying the `tax_year`; it begins in `PREPARING` with both branch flags, `books_signoff` and `advisory_signoff`, false. Starting the reviews is a `CFO` action permitted only from `PREPARING` and gated on the books being closed: the client's `MonthlyClose` for the December period — that is, for `period_year` equal to `tax_year` and `period_month` 12 — must be `FINALIZED`, and a start attempted before that December close is finalized is rejected with `ERR_DECEMBER_CLOSE_NOT_FINAL`. Starting the reviews forks the workflow, moving it `PREPARING → BOOKS_REVIEW` and opening both review branches at once.

The two branches sign off independently and may complete in either order. A `Bookkeeper` signs off the books branch: permitted while the handoff is in `BOOKS_REVIEW` or `ADVISORY_REVIEW` and `books_signoff` is still false, it sets `books_signoff` to true, and if `advisory_signoff` was already true it advances the handoff to `READY`, otherwise it moves the handoff to `ADVISORY_REVIEW` to indicate the still-pending branch. Symmetrically, a `CFO` signs off the advisory branch: permitted while the handoff is in `BOOKS_REVIEW` or `ADVISORY_REVIEW` and `advisory_signoff` is still false, it sets `advisory_signoff` to true, and if `books_signoff` was already true it advances the handoff to `READY`, otherwise it moves the handoff to `BOOKS_REVIEW`. The join is therefore reached — `status` becomes `READY` — only once both `books_signoff` and `advisory_signoff` are true. From `READY`, a `CFO` delivers the package (`READY → DELIVERED`), and once the external preparer returns the completed work a `CFO` marks it returned (`DELIVERED → RETURNED`). Each of these handoff transitions increments the handoff's `version`, and any of them attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — every state transition, every sign-off, every reconciliation-bearing action — return `200 OK`. Read operations return `200 OK`. Reconstruct each endpoint's request body, computed outputs, and side effects from the Section 3 narratives; the table below is intentionally a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/clients` | Create a client (LEAD / PROSPECT) | CFO, PlatformAdmin |
| GET | `/clients` | List clients (optional engagement filter) | CFO, Bookkeeper, PlatformAdmin |
| GET | `/clients/{id}` | Fetch a single client | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| POST | `/clients/{id}/schedule-kickoff` | Onboarding: LEAD → KICKOFF_SCHEDULED | CFO |
| POST | `/clients/{id}/start-ledger-setup` | Onboarding: KICKOFF_SCHEDULED → LEDGER_SETUP | Bookkeeper |
| POST | `/clients/{id}/complete-onboarding` | Onboarding: LEDGER_SETUP → ONBOARDED | CFO |
| POST | `/clients/{id}/activate-engagement` | Engagement: PROSPECT/PAUSED → ACTIVE | CFO |
| POST | `/clients/{id}/pause-engagement` | Engagement: ACTIVE → PAUSED | CFO |
| POST | `/clients/{id}/offboard` | Engagement: ACTIVE/PAUSED → OFFBOARDED | CFO |
| POST | `/clients/{id}/ledger-accounts` | Create a chart-of-accounts entry | Bookkeeper, CFO |
| GET | `/clients/{id}/ledger-accounts` | List a client's ledger accounts | Bookkeeper, CFO, PlatformAdmin |
| GET | `/ledger-accounts/{id}` | Fetch a single ledger account | Bookkeeper, CFO, PlatformAdmin |
| GET | `/ledger-accounts/{id}/children` | List an account's child accounts | Bookkeeper, CFO, PlatformAdmin |
| POST | `/ledger-accounts/{id}/archive` | Archive an account (ACTIVE → ARCHIVED) | CFO |
| POST | `/clients/{id}/catchup-projects` | Create a catch-up project (DRAFT) | CFO |
| GET | `/clients/{id}/catchup-projects` | List a client's catch-up projects | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| GET | `/catchup-projects/{id}` | Fetch a single catch-up project | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| POST | `/catchup-projects/{id}/scope` | DRAFT → SCOPED | CFO |
| POST | `/catchup-projects/{id}/start` | SCOPED → IN_PROGRESS | Bookkeeper |
| POST | `/catchup-projects/{id}/submit-for-review` | IN_PROGRESS/REVISION → CLIENT_REVIEW | Bookkeeper |
| POST | `/catchup-projects/{id}/reject` | CLIENT_REVIEW → REVISION | ClientContact |
| POST | `/catchup-projects/{id}/approve` | CLIENT_REVIEW → COMPLETED | ClientContact |
| POST | `/catchup-projects/{id}/cancel` | Non-terminal → CANCELLED | CFO |
| POST | `/clients/{id}/monthly-closes` | Open a monthly close | Bookkeeper, CFO |
| GET | `/clients/{id}/monthly-closes` | List a client's monthly closes | Bookkeeper, CFO, ClientContact, PlatformAdmin |
| GET | `/monthly-closes/{id}` | Fetch a single monthly close | Bookkeeper, CFO, ClientContact, PlatformAdmin |
| POST | `/monthly-closes/{id}/close-tasks` | Add a checklist task (PENDING) | Bookkeeper, CFO |
| GET | `/monthly-closes/{id}/close-tasks` | List a close's tasks | Bookkeeper, CFO, ClientContact, PlatformAdmin |
| GET | `/monthly-closes/{id}/payroll-runs` | List payroll runs for a close | Bookkeeper, CFO, PlatformAdmin |
| GET | `/monthly-closes/{id}/retainer-invoices` | List retainer invoices for a close | CFO, Bookkeeper, PlatformAdmin |
| POST | `/close-tasks/{id}/transition` | Move a task; bubble up to the close | Bookkeeper, CFO |
| POST | `/monthly-closes/{id}/approve-review` | Review: UNDER_REVIEW → APPROVED | CFO |
| POST | `/monthly-closes/{id}/request-changes` | READY_FOR_REVIEW → REOPENED | CFO |
| POST | `/monthly-closes/{id}/finalize` | READY_FOR_REVIEW → FINALIZED | CFO |
| POST | `/clients/{id}/ar-invoices` | Create an AR invoice (OPEN) | Bookkeeper, CFO |
| GET | `/clients/{id}/ar-invoices` | List a client's AR invoices | Bookkeeper, CFO, ClientContact, PlatformAdmin |
| GET | `/ar-invoices/{id}` | Fetch a single AR invoice | Bookkeeper, CFO, ClientContact, PlatformAdmin |
| POST | `/ar-invoices/{id}/dispute` | OPEN → DISPUTED | ClientContact |
| POST | `/ar-invoices/{id}/resolve-dispute` | DISPUTED → OPEN | Bookkeeper |
| POST | `/ar-invoices/{id}/record-payment` | OPEN → PAID | Bookkeeper |
| POST | `/ar-invoices/{id}/write-off` | OPEN → WRITTEN_OFF | CFO |
| GET | `/clients/{id}/ar-summary` | AR aging + DSO summary | CFO, Bookkeeper, PlatformAdmin |
| POST | `/clients/{id}/ap-bills` | Create an AP bill (ENTERED) | Bookkeeper |
| GET | `/clients/{id}/ap-bills` | List a client's AP bills | Bookkeeper, CFO, PlatformAdmin |
| GET | `/ap-bills/{id}` | Fetch a single AP bill | Bookkeeper, CFO, PlatformAdmin |
| POST | `/ap-bills/{id}/approve` | ENTERED → APPROVED | CFO |
| POST | `/ap-bills/{id}/schedule` | APPROVED → SCHEDULED | Bookkeeper |
| POST | `/ap-bills/{id}/mark-paid` | SCHEDULED → PAID | Bookkeeper |
| POST | `/ap-bills/{id}/void` | ENTERED/APPROVED → VOID | CFO |
| POST | `/clients/{id}/payroll-runs` | Create a payroll run (DRAFT) | Bookkeeper |
| GET | `/clients/{id}/payroll-runs` | List a client's payroll runs | Bookkeeper, CFO, PlatformAdmin |
| GET | `/payroll-runs/{id}` | Fetch a single payroll run | Bookkeeper, CFO, PlatformAdmin |
| POST | `/payroll-runs/{id}/allocations` | Add a department allocation line | Bookkeeper |
| GET | `/payroll-runs/{id}/allocations` | List a run's allocation lines | Bookkeeper, CFO, PlatformAdmin |
| POST | `/payroll-runs/{id}/allocate` | DRAFT → ALLOCATED | Bookkeeper |
| POST | `/payroll-runs/{id}/post` | ALLOCATED → POSTED | CFO |
| POST | `/payroll-runs/{id}/reverse` | POSTED → REVERSED | CFO |
| POST | `/clients/{id}/forecasts` | Create a cash-flow forecast (DRAFT) | CFO |
| GET | `/clients/{id}/forecasts` | List a client's forecasts | CFO, Bookkeeper, PlatformAdmin |
| GET | `/forecasts/{id}` | Fetch a single forecast | CFO, Bookkeeper, PlatformAdmin |
| POST | `/forecasts/{id}/lines` | Add a projected cash movement | CFO |
| GET | `/forecasts/{id}/lines` | List a forecast's lines | CFO, Bookkeeper, PlatformAdmin |
| POST | `/forecasts/{id}/approve` | DRAFT → APPROVED (OCC + covenant) | CFO |
| POST | `/clients/{id}/tax-handoffs` | Create a tax handoff (PREPARING) | CFO |
| GET | `/clients/{id}/tax-handoffs` | List a client's tax handoffs | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| GET | `/tax-handoffs/{id}` | Fetch a single tax handoff | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| POST | `/tax-handoffs/{id}/start-reviews` | PREPARING → BOOKS_REVIEW (fork) | CFO |
| POST | `/tax-handoffs/{id}/books-signoff` | Books branch sign-off | Bookkeeper |
| POST | `/tax-handoffs/{id}/advisory-signoff` | Advisory branch sign-off | CFO |
| POST | `/tax-handoffs/{id}/deliver` | READY → DELIVERED | CFO |
| POST | `/tax-handoffs/{id}/mark-returned` | DELIVERED → RETURNED | CFO |
| POST | `/clients/{id}/retainer-invoices` | Issue a retainer invoice (OCC) | CFO |
| GET | `/clients/{id}/retainer-invoices` | List a client's retainer invoices | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| GET | `/retainer-invoices/{id}` | Fetch a single retainer invoice | CFO, Bookkeeper, ClientContact, PlatformAdmin |
| POST | `/retainer-invoices/{id}/pay` | ISSUED → PAID | ClientContact, CFO |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ONBOARDING_INCOMPLETE` | 409 |
| `ERR_OPEN_CLOSES_EXIST` | 409 |
| `ERR_DECEMBER_CLOSE_NOT_FINAL` | 409 |
| `ERR_CLOSE_FINALIZED` | 409 |
| `ERR_NO_LEDGER_ACCOUNTS` | 409 |
| `ERR_CROSS_CLIENT_PARENT` | 422 |
| `ERR_DUPLICATE_ACCOUNT_CODE` | 409 |
| `ERR_DUPLICATE_PERIOD` | 409 |
| `ERR_PAY_PERIOD_OVERLAP` | 409 |
| `ERR_COVENANT_BREACH` | 422 |
| `ERR_UNDERPAYMENT` | 422 |
| `ERR_MISSING_SCHEDULE_DATE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PERIOD` | 422 |
| `ERR_INVALID_TASK_STATUS` | 422 |
| `ERR_NEGATIVE_AMOUNT` | 422 |
| `ERR_VALIDATION_LIMIT` | 400 |
