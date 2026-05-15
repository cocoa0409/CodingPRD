# Five Twenty Nine College Savings API — Product Requirements Document

## 1. Introduction

Section 529 plans are state-sponsored, federally tax-advantaged investment vehicles that families use to fund a beneficiary's education. They are also among the most error-prone savings products to operate: every dollar that lands in or leaves an account is shadowed by an in-state versus cross-state deduction question, a federal annual cap on K-12 tuition, a 10% earnings penalty on non-qualified spending, an IRS-defined family-relationship table that restricts beneficiary changes, and a Form 1099-Q reporting boundary that, once locked, cannot be reopened. A platform that misclassifies even a few of these events at year-end exposes donors to overstated tax deductions or surprise penalties, and exposes the plan administrator to regulatory action.

This document specifies the back-office API for a 529 college savings management system. The platform serves three constituencies: **donors** who open accounts and fund them (either as one-off lump-sum gifts or as automated recurring transfers), **beneficiaries** whose education is being financed (and who, by design, may *not* initiate withdrawals against the account they benefit from), and **plan administrators** who settle contributions, classify withdrawals against substantiating receipts, manage the state-rule table, and finalize each year's 1099-Q. The same API also exposes two test-driving endpoints — a logical clock and a recurring-plan sweep — which exist so that the time-dependent behaviors of the system (annual K-12 reset, tax-report aggregation, recurring contribution generation) can be exercised deterministically.

The remainder of this document is organized into global cross-cutting specifications (Section 2), the business-logic narrative that defines correct behavior across the account lifecycle (Section 3), the summary endpoint table (Section 4), and the consolidated error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, the caller's identifier, and `X-User-Role`, exactly one of `Donor`, `Beneficiary`, or `PlanAdministrator`. Requests missing either header are rejected with `ERR_AUTH_MISSING`. Requests whose `X-User-Role` is not one of those three exact strings are rejected with `ERR_AUTH_INVALID_ROLE`. When the role is valid but the role is not authorized for the endpoint per Section 4, the request is rejected with `ERR_FORBIDDEN`.

The three roles map to identity as follows. When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor`; ownership checks on any resource that references a `Donor` (an `Account` via its `primary_donor_id`, a `Contribution` or `RecurringPlan` via its `donor_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; the read-only views available to a beneficiary are restricted to accounts whose `beneficiary_id` equals `X-User-ID`. When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`.

The three roles also embody a deliberate segregation of duties. A `Donor` opens accounts, funds them, and disburses money out of them, but cannot settle the contributions they create or approve a beneficiary change they request; those administrative completions belong to `PlanAdministrator`. A `Beneficiary` may inspect the accounts they benefit from but holds no write capability — most importantly, a `Beneficiary` cannot initiate a withdrawal from their own account; only the `Donor` may. A `PlanAdministrator` operates the plan: settling and reversing contributions, rejecting withdrawals, approving or rejecting beneficiary changes, finalizing 1099-Q tax reports, maintaining the state-rule table, and (in test environments) advancing the logical clock and triggering the recurring-plan sweep.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must be a non-negative integer. List endpoints sort their results by `created_at` ascending, and the response's `meta` block carries `limit`, `offset`, `total_count`, and `has_more` alongside the standard envelope fields.

### 2.4. Common Resource Properties

Most resources in this system — `Donor`, `Beneficiary`, `Account`, `Withdrawal`, `RecurringPlan`, `BeneficiaryChangeRequest`, and `StateRule` — carry four common properties. The `id` is a server-minted UUID with no type-prefix (no `acct_`, `dnr_`, or similar; just the raw UUID string). The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at row creation, `updated_at` is refreshed on every mutation. The `version` is an integer that starts at 1 and increments by 1 on every successful mutation of the row.

Two entities omit the `updated_at` and `version` fields: `Contribution` and `EducationExpense` (which are append-mostly records that transition through state or are attached once and never updated), and `TaxReport` (which is recomputed in place until finalized and then frozen — its mutability is governed by the `locked` boolean and the per-withdrawal cascade described in Section 3, not by an OCC version). For those three entities, the row carries only `id` and `created_at`.

### 2.5. Optimistic Concurrency Control

PATCH endpoints — currently the update endpoint on a recurring plan — accept an optional `version` in the request body. When `version` is supplied, the server compares it to the row's current `version`; if the values differ, the write is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server skips the check and applies the write unconditionally. A successful PATCH increments `version` by 1 and refreshes `updated_at`.

### 2.6. Nested Resource Path Resolution

Many endpoints take nested path identifiers — `/accounts/{id}/contributions`, `/accounts/{id}/withdrawals`, `/accounts/{id}/recurring-plans`, `/accounts/{id}/beneficiary-change-requests`. Path identifiers are resolved left-to-right: if `account_id` does not resolve to a live row, the request is rejected with `ERR_NOT_FOUND` before any nested resource is examined. The same `ERR_NOT_FOUND` rejection applies to body-referenced identifiers such as `donor_id`, `beneficiary_id`, `recurring_plan_id`, and `withdrawal_id` that do not resolve to a live row.

### 2.7. Validation Priority Ordering

When multiple validations could apply to the same request, they are evaluated in a fixed order; the first failure is returned, and later checks do not run. Authentication-shape checks fire first — missing headers (`ERR_AUTH_MISSING`), then invalid role (`ERR_AUTH_INVALID_ROLE`), then role-not-authorized (`ERR_FORBIDDEN`). Existence resolution follows: path identifiers, then body-referenced foreign keys, both producing `ERR_NOT_FOUND`. State-machine checks come next: an account whose status is not `OPEN` causes write operations on it to fail with `ERR_ACCOUNT_RESTRICTED`, and a target row whose source state does not match the transition's from-state fails with `ERR_INVALID_STATE`.

The next priority tier is **business safety** ahead of **business fiscal**. Specifically, the locked-tax-report check (`ERR_TAX_REPORT_LOCKED`) fires *before* the gift-exclusion, lifetime-cap, K-12-cap, and insufficient-balance checks. A withdrawal disbursement attempt against a tax year whose 1099-Q has already been locked is treated as a regulatory error regardless of whether the balance would otherwise allow it. Following the locked-report check, expense receipts are verified — receipts with a category mismatching the parent withdrawal's `expense_category` produce `ERR_EXPENSE_CATEGORY_MISMATCH` and are rejected before any cap math runs; an `EducationExpense` whose `incurred_on` does not fall in the same calendar year as the withdrawal's disbursement produces `ERR_EXPENSE_OUT_OF_YEAR`.

Within beneficiary-change approval, four checks fire in order: identical-to-current (`ERR_BENEFICIARY_IDENTICAL_TO_CURRENT`) first, then the IRS permissible-family check (`ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN`), then the generation-skip check (`ERR_BENEFICIARY_GENERATION_SKIP`). The generation-skip check is classified as a **safety** check and intentionally fires ahead of business-constraint checks such as the K-12 annual cap (`ERR_K12_CAP_EXCEEDED`). Finally, OCC version mismatch (`ERR_VERSION_CONFLICT`) is the last check on PATCH endpoints, applied after all upstream validations have passed.

### 2.8. Monetary Precision and Rounding

All monetary quantities in this system are stored and transmitted as integer cents — there are no floating-point dollar values. Where calculations would otherwise produce fractional cents (proportional splits, percentage penalties), the result is **rounded half-up to the nearest integer cent**. Where a calculation expresses one value as the residual of another (basis being the residual of an earnings split, for example), only the first quantity is rounded; the residual is the exact integer subtraction needed to make the two sum to the original requested amount. Aggregations on `TaxReport` — the 1099-Q boxes — are pure integer sums of per-withdrawal already-rounded values, never a re-derived ratio-times-total at report time; sum-then-round is incorrect and produces different cents than the canonical per-withdrawal-then-sum order.

### 2.9. Hierarchical State Cascades and Conserved-Quantity Invariants

Several state transitions in this system trigger cascades on sibling rows. Restricting an account pauses every `ACTIVE` recurring plan attached to it; closing an account cancels every recurring plan attached to it whose status is `ACTIVE` or `PAUSED`; finalizing a tax report transitions every `CLASSIFIED` withdrawal in the report's year on the report's account to `REPORTED` and flips the report's `locked` to `true`. Every cascaded mutation refreshes the affected row's `updated_at` and increments its `version` exactly as if the operation had been called individually.

Two invariants are conserved across the entire system. First, the **balance invariant**: at all times, `basis_balance_cents + earnings_balance_cents = total_balance_cents` on every account. Every mutation that moves money — contribution settlement, withdrawal disbursement — preserves this identity exactly. Second, the **beneficiary-change conservation invariant**: approving a beneficiary change mutates only `beneficiary_id` on the account; `basis_balance_cents`, `earnings_balance_cents`, and `total_balance_cents` are unchanged. The new beneficiary inherits the existing balance composition; no basis/earnings reset occurs.

### 2.10. Concurrency Serialization

Several operations race against one another in ways that can be observed by clients. The system serializes each such race on a single contested field and returns a specific `error_id` to the losing operation.

When a `Donor` disburses a withdrawal at the same instant a `PlanAdministrator` restricts the account, exactly one operation succeeds. If the restrict lands first, the disburse attempt observes `Account.status` as `RESTRICTED` and is rejected with `ERR_ACCOUNT_RESTRICTED`; the contest is serialized first-writer-wins on `Account.status`.

When two disbursements on the same account race and together would exceed `total_balance_cents`, only one succeeds; the second re-reads the post-commit balance and fails its balance precondition with `ERR_INSUFFICIENT_BALANCE`. The race is serialized first-writer-wins on `total_balance_cents`.

When two beneficiary-change approvals on the same account race, exactly one approval lands. The loser observes that `Account.beneficiary_id` has already moved away from its captured `current_beneficiary_id` snapshot, fails the snapshot match, and is rejected with `ERR_STALE_BENEFICIARY_SNAPSHOT`. The race is serialized first-writer-wins on `Account.beneficiary_id`.

When a tax-report finalize races a classify in the same tax year, the first writer wins on `TaxReport.locked`. If finalize wins, the late classify is rejected with `ERR_TAX_REPORT_LOCKED`; if classify wins, finalize re-aggregates and includes the newly classified row.

When two contributions to the same account each individually fit the lifetime cap but together exceed it, first-writer-wins on `total_balance_cents`: the second contribution's settle is rejected with `ERR_LIFETIME_CAP_WOULD_EXCEED` because the post-credit total would exceed `lifetime_contribution_cap_cents`.

When two concurrent PATCH calls supply the same `version`, the first commits and increments `version`; the second sees a stale value and is rejected with `ERR_VERSION_CONFLICT`. The contest is a compare-and-swap on `version`.

## 3. Business Logic & Workflows

### 3.1. State Rules, Donors, and Beneficiaries — the Reference Data

Each U.S. state that participates in 529 sponsorship is represented by a `StateRule` keyed by its two-uppercase-letter `state_code`. A state rule carries four policy levers that the rest of the system depends on. The `deduction_cap_cents` defines the maximum amount, in integer cents, that a single donor may claim as a state-income-tax deduction in one calendar year against this state. The `parity` field is either `IN_STATE_ONLY` — meaning the state grants its deduction only when the account's `state_plan_code` equals the donor's `state_of_residence` — or `PARITY`, meaning the state grants its deduction for contributions to any state's plan. The `lifetime_aggregate_cap_cents` is the ceiling on cumulative contributions that any account sponsored by this state may ever hold. The `k12_qualified` boolean records whether the state recognizes K-12 expenses as state-tax-qualified; the federal K-12 annual cap (described in Section 3.5) still applies independently.

State rules are administrative reference data. A `PlanAdministrator` registers or replaces a state rule by supplying `state_code`, `deduction_cap_cents`, `parity`, `lifetime_aggregate_cap_cents`, and `k12_qualified`; every replacement increments the rule's `version`. Crucially, an existing account's pinned snapshot of the lifetime cap is **not** re-read when the underlying state rule changes — see Section 3.3 for the pin semantics. Both `Donor` and `PlanAdministrator` may retrieve a single state rule by `state_code` or list all state rules.

A `Donor` is registered by a `PlanAdministrator` with `full_name`, `state_of_residence`, and `ssn_last_four`. The `full_name` must be a non-empty string of at most 200 characters; `state_of_residence` must be exactly two uppercase letters matching a `StateRule.state_code`; `ssn_last_four` must be exactly four digits and is required because every donor appears as the contributor of record on 1099-Q reporting. Each donor also carries two computed counters that the system maintains in real time: `ytd_contribution_total_cents` is the calendar-year sum of `amount_cents` over the donor's `SETTLED` contributions, and `ytd_state_deduction_used_cents` is the deduction credited toward this donor's state of residence in the current calendar year. Both counters reset to zero on January 1.

A `Beneficiary` is registered by either a `PlanAdministrator` or a `Donor` with `full_name`, `date_of_birth`, `ssn_last_four`, and `relationship_family_code`. The `date_of_birth` is an ISO 8601 date used to distinguish K-12 from post-secondary eligibility windows. The `relationship_family_code` enumerates the IRS family-relationship vocabulary and must be exactly one of `SELF`, `CHILD`, `SIBLING`, `NIECE_NEPHEW`, `PARENT`, `COUSIN`, `SPOUSE`, `IN_LAW`, or `FIRST_COUSIN_ONCE_REMOVED`. The beneficiary also carries a computed counter, `k12_ytd_qualified_cents`, the calendar-year sum of the qualified K-12 portion across every `CLASSIFIED` withdrawal for accounts whose `beneficiary_id` equals this beneficiary's `id`. This counter is the linchpin of the federal K-12 annual cap (Section 3.5) and likewise resets on January 1.

### 3.2. Opening, Restricting, Releasing, and Closing the Account

A `Donor` opens an `Account` by supplying three fields: `primary_donor_id` (the donor of record, normally the caller themselves), `beneficiary_id` (the current beneficiary), and `state_plan_code` (the two-letter code of the state sponsoring the plan, which is independent of the donor's `state_of_residence`). At open, the system pins two snapshots onto the new account: `lifetime_contribution_cap_cents` is set from the matching `StateRule.lifetime_aggregate_cap_cents` and is frozen for the life of the account — it is never re-read from `StateRule` on subsequent contributions — and `state_rule_version_at_open` is set from the state rule's current `version`. If the state rule is later replaced with a different lifetime cap, this account's cap remains at the snapshotted value and the version drift can be detected from `state_rule_version_at_open`. The account is created in status `OPEN` with `basis_balance_cents`, `earnings_balance_cents`, and `total_balance_cents` all zero.

Three lifecycle transitions move the account between `OPEN`, `RESTRICTED`, and `CLOSED`. A `PlanAdministrator` may restrict an `OPEN` account, transitioning its status from `OPEN` to `RESTRICTED`. Restriction has a cascade: every recurring plan attached to the account whose status is `ACTIVE` transitions to `PAUSED`, and while the account is `RESTRICTED` no new contribution settlements, withdrawal disbursements, recurring resumes, or beneficiary-change approvals are accepted — each such attempt is rejected with `ERR_ACCOUNT_RESTRICTED`. A `PlanAdministrator` may release a `RESTRICTED` account, transitioning it from `RESTRICTED` back to `OPEN`; the release does *not* automatically resume previously paused recurring plans, because a paused plan reflects donor intent that the donor must reaffirm explicitly. The `Donor` (and only the donor) may close an `OPEN` account, transitioning it from `OPEN` to `CLOSED`. Closing requires three preconditions: `total_balance_cents` is zero, no withdrawal on the account is in status `REQUESTED`, `DISBURSED`, or `CLASSIFIED`, and no beneficiary-change request on the account is in status `SUBMITTED`. Closing cascades every recurring plan on the account in status `ACTIVE` or `PAUSED` to `CANCELLED`. Each cascade refreshes `updated_at` and increments `version` on the affected rows. Any attempt to drive a transition against the wrong from-state — restricting an already-`RESTRICTED` account, closing a `CLOSED` account, releasing an `OPEN` one — is rejected with `ERR_INVALID_STATE`.

A `Donor` or `PlanAdministrator` may retrieve a single account by `id`, including its computed balances, or list accounts with optional filters `primary_donor_id`, `beneficiary_id`, `status`, and `state_plan_code`. A `Beneficiary` may read accounts where they are the named beneficiary but cannot list across the system.

### 3.3. Contributing — Lump Sum, Recurring, and the State-Tax-Benefit Credit

Funding an account happens in two flavors. A **lump-sum** contribution is initiated by a `Donor` posting a payload containing `donor_id`, `amount_cents`, `contribution_kind` set to `LUMP_SUM`, and a null `recurring_plan_id`; the donor in the payload need not equal the account's `primary_donor_id`, because third-party gifts (a grandparent funding a parent's account) are explicitly supported. A **recurring** contribution is generated by the system: a `Donor` first creates a `RecurringPlan` on the account with `donor_id`, `amount_cents`, and `cadence_days` (one of 7, 14, 30, 90, or 365), and the plan's `next_run_at` is initialized to the current server clock plus `cadence_days` × 86400 seconds. The sweep capability — a `PlanAdministrator`-only operation against a server-internal sweep capability — materializes one `PENDING` contribution per `ACTIVE` plan whose `next_run_at` is less than or equal to `now()`, advances each swept plan's `next_run_at` by `cadence_days` × 86400 seconds, and stamps each resulting contribution with `contribution_kind` of `RECURRING` and the originating `recurring_plan_id`.

Every contribution starts in status `PENDING` with `settled_at` null. A `PlanAdministrator` settles a `PENDING` contribution, transitioning its status from `PENDING` to `SETTLED`. Settlement requires the account to be `OPEN` (else `ERR_ACCOUNT_RESTRICTED`), the post-credit account total to remain at or below the pinned lifetime cap (else `ERR_LIFETIME_CAP_WOULD_EXCEED` — that is, `total_balance_cents` plus the contribution's `amount_cents` must not exceed the account's `lifetime_contribution_cap_cents`), and the post-credit donor calendar-year total to remain at or below the IRS annual gift-tax exclusion (else `ERR_GIFT_EXCLUSION_EXCEEDED` — the donor's `ytd_contribution_total_cents` plus the contribution's `amount_cents` must not exceed the annual gift exclusion of $18,000, equivalently 1,800,000 cents). On successful settlement, the account's `basis_balance_cents` and `total_balance_cents` each increase by `amount_cents`, the donor's `ytd_contribution_total_cents` increases by `amount_cents`, `settled_at` is set to the current server timestamp, and the **state-tax-benefit credit** is computed and applied to the donor's `ytd_state_deduction_used_cents`. A `PlanAdministrator` may instead reverse a `PENDING` contribution, transitioning its status from `PENDING` to `REVERSED` with no balance change. A `SETTLED` contribution cannot be reversed — mistakes after settlement are corrected by a subsequent withdrawal.

The **state-tax-benefit credit** at settlement is computed against the state rule of the donor's `state_of_residence` (not the account's `state_plan_code`). The system first resolves the donor's residence-state rule. If that rule's `parity` is `IN_STATE_ONLY` *and* the account's `state_plan_code` is different from the donor's `state_of_residence`, the credit awarded for this contribution is zero and the contribution still settles — there is no rejection, just no deduction. Otherwise — that is, when `parity` is `PARITY`, or when `parity` is `IN_STATE_ONLY` and the account's `state_plan_code` matches the donor's `state_of_residence` — the system computes the remaining deduction room for the year by subtracting the donor's existing `ytd_state_deduction_used_cents` from the rule's `deduction_cap_cents`, taking the greater of that difference and zero. The credit awarded equals the smaller of the contribution's `amount_cents` and that remaining room. The donor's `ytd_state_deduction_used_cents` is incremented by the credit awarded. All quantities are integer cents; no rounding occurs.

A donor or administrator may retrieve any contribution by `id` or list contributions on an account, optionally filtered by `status` and `contribution_kind`.

### 3.4. Recurring Plans — Pause, Resume, Update, Cancel

A `RecurringPlan` cycles through `ACTIVE`, `PAUSED`, and the terminal `CANCELLED`. A `Donor` may pause an `ACTIVE` plan, transitioning its status from `ACTIVE` to `PAUSED`; a paused plan stops producing contributions at its next scheduled run. As noted in Section 3.2, the same `ACTIVE` → `PAUSED` transition is cascaded when a `PlanAdministrator` restricts the account. A `Donor` may resume a `PAUSED` plan, transitioning its status from `PAUSED` to `ACTIVE`, provided the account is `OPEN`; on resume, `next_run_at` is reset to the current server clock plus `cadence_days` × 86400 seconds. A `Donor` may cancel a plan in either `ACTIVE` or `PAUSED`, and the same transition to `CANCELLED` is cascaded when an account is closed. A plan that is already `CANCELLED` cannot be transitioned again (`ERR_INVALID_STATE`).

A `Donor` may update an existing plan's `amount_cents` or `cadence_days` (or both) by supplying the changed values along with the current `version`. The plan's OCC check operates exactly as Section 2.5 describes: omitting `version` skips the check; supplying a `version` that does not match the current row results in `ERR_VERSION_CONFLICT`.

### 3.5. Withdrawing, Substantiating Receipts, and the K-12 Annual Cap

A withdrawal begins as a `Donor` request. The donor supplies `requested_amount_cents` (in integer cents, strictly greater than zero) and `expense_category`, exactly one of `POST_SECONDARY_TUITION`, `ROOM_AND_BOARD`, `BOOKS_SUPPLIES`, `K_12`, or `NON_QUALIFIED`. The system creates the withdrawal in status `REQUESTED` with all computed monetary fields (`basis_portion_cents`, `earnings_portion_cents`, `qualified_amount_cents`, `non_qualified_amount_cents`, `penalty_cents`) initially null. Create-time checks: the account must be `OPEN`; the `requested_amount_cents` must not exceed the account's `total_balance_cents` (else `ERR_INSUFFICIENT_BALANCE` at create); the tax report for the account's current tax year, if it exists and is locked, blocks the create with `ERR_TAX_REPORT_LOCKED`; and when `expense_category` is `K_12`, the create is rejected with `ERR_K12_CAP_EXCEEDED` if the beneficiary has zero cap room remaining for the current calendar year *and* the request would push them into negative cap room. A request that lands exactly on the remaining cap room (so cap room equals requested) is allowed.

A `PlanAdministrator` may reject a `REQUESTED` withdrawal, transitioning its status from `REQUESTED` to `REJECTED` and stamping a `rejected_reason`, one of `INSUFFICIENT_BALANCE`, `ACCOUNT_RESTRICTED`, `K12_CAP_WOULD_EXCEED`, or `EXPENSE_RECEIPT_MISSING`. A rejection mutates no balances.

The `Donor` disburses a `REQUESTED` withdrawal, transitioning its status from `REQUESTED` to `DISBURSED`. Disbursement requires the account to be `OPEN` (else `ERR_ACCOUNT_RESTRICTED`) and re-checks that `requested_amount_cents` does not exceed the account's current `total_balance_cents` (else `ERR_INSUFFICIENT_BALANCE`). At disbursement, the system runs the **basis/earnings split**: it computes the earnings-share ratio as the account's `earnings_balance_cents` divided by its pre-disbursement `total_balance_cents`, multiplies that ratio by `requested_amount_cents`, rounds the product half-up to integer cents to obtain `earnings_portion_cents`, and sets `basis_portion_cents` as the residual `requested_amount_cents` minus `earnings_portion_cents`. The basis portion is therefore never rounded separately — it is the exact integer that makes the two portions sum to `requested_amount_cents`. The account's `basis_balance_cents` decreases by `basis_portion_cents`, `earnings_balance_cents` decreases by `earnings_portion_cents`, and `total_balance_cents` decreases by `requested_amount_cents`, preserving the balance invariant.

Once a withdrawal is `DISBURSED`, the `Donor` may attach `EducationExpense` receipts to it. Each receipt carries `institution_name` (non-empty, at most 200 characters), `category` (one of the same enumeration as `expense_category`), `amount_cents` (strictly positive integer cents), and `incurred_on` (an ISO 8601 date). Attaching a receipt requires `incurred_on` to fall in the same calendar year (UTC) as the withdrawal's disbursement; otherwise `ERR_EXPENSE_OUT_OF_YEAR`. The `withdrawal_id` is inferred from the URL path.

The `Donor` classifies a `DISBURSED` withdrawal, transitioning its status from `DISBURSED` to `CLASSIFIED`. Classification is rejected with `ERR_TAX_REPORT_LOCKED` if the tax report for that account and that year is already locked, and rejected with `ERR_EXPENSE_CATEGORY_MISMATCH` if any attached receipt's `category` does not equal the withdrawal's `expense_category`. Furthermore, when the withdrawal's `expense_category` is not `NON_QUALIFIED`, the sum of receipt `amount_cents` for matching-category receipts must be strictly greater than zero, else the transition fails with `ERR_INVALID_STATE` on the missing-substantiation precondition.

On a successful classify, the system runs the **K-12 cap application** and the **non-qualified earnings penalty** in sequence. The K-12 cap application proceeds case-by-case. If `expense_category` is `NON_QUALIFIED`, `qualified_amount_cents` is zero. If `expense_category` is `K_12`, the system computes the receipts total — the sum of `EducationExpense.amount_cents` for receipts on this withdrawal whose `category` is `K_12` — and computes the remaining cap room as the federal K-12 annual cap of $10,000 (1,000,000 cents) minus the beneficiary's `k12_ytd_qualified_cents`; the qualified amount is then the smallest of three quantities: `requested_amount_cents`, the receipts total, and the remaining cap room. If `expense_category` is any post-secondary value (`POST_SECONDARY_TUITION`, `ROOM_AND_BOARD`, `BOOKS_SUPPLIES`), only the receipts ceiling applies: the qualified amount is the smaller of `requested_amount_cents` and the matching-category receipts total. In every case, `non_qualified_amount_cents` is `requested_amount_cents` minus `qualified_amount_cents`. The beneficiary's `k12_ytd_qualified_cents` is then increased by the K-12 portion of the qualified amount (i.e., by `qualified_amount_cents` when `expense_category` is `K_12`, and by zero otherwise). The federal K-12 cap is *per beneficiary, per calendar year*, applied cumulatively across every account whose `beneficiary_id` is this beneficiary — it is not a per-account cap.

The **non-qualified earnings penalty** then computes the proportional earnings share of the non-qualified portion. If `requested_amount_cents` is zero or `non_qualified_amount_cents` is zero, the `penalty_cents` is zero. Otherwise the system computes the earnings share of the non-qualified portion as `earnings_portion_cents` multiplied by `non_qualified_amount_cents` divided by `requested_amount_cents`, rounded half-up to integer cents; it then multiplies that share by the penalty rate of 10% (0.10) and rounds half-up again to integer cents to obtain `penalty_cents`. The two rounding steps are sequential — first the proportional earnings share is rounded, then the 10% product is rounded — and this nested ordering produces the canonical penalty result.

The earnings allocation between qualified and non-qualified is proportional to the dollar split, not basis-first. While the disbursement step depletes the account basis-first via the basis/earnings split, the penalty step at classification re-derives the earnings share of the non-qualified slice proportionally from the already-pinned `earnings_portion_cents`; this is deliberate, because the IRS treats the 10% penalty as applying to the proportional earnings of the non-qualified spending, not to the basis-depleted residual.

A `Donor` or `PlanAdministrator` may retrieve a single withdrawal by `id` or list withdrawals on an account, optionally filtered by `status` and `expense_category`. A `Beneficiary` may list and read withdrawals on the accounts they benefit from.

### 3.6. Changing the Beneficiary

A `Donor` submits a beneficiary change by posting `proposed_beneficiary_id` against an account; the system creates a `BeneficiaryChangeRequest` in status `SUBMITTED` and captures a `current_beneficiary_id` snapshot from the account's `beneficiary_id` at submit time. The request has its own `status`, lifecycle from `SUBMITTED` to either `APPROVED` or `REJECTED`, and optional `rejection_reason` populated only when rejected.

A `PlanAdministrator` approves a `SUBMITTED` change request, transitioning its status from `SUBMITTED` to `APPROVED`. Approval requires the account to be `OPEN`, the request to still be `SUBMITTED` (else `ERR_INVALID_STATE`), and a sequence of beneficiary checks evaluated in order. The first check is identity: the proposed beneficiary's `id` must not equal the current `beneficiary_id` (else `ERR_BENEFICIARY_IDENTICAL_TO_CURRENT`). The second check is the IRS permissible-family set: the proposed beneficiary's `relationship_family_code` must be one of `CHILD`, `SIBLING`, `NIECE_NEPHEW`, `COUSIN`, `FIRST_COUSIN_ONCE_REMOVED`, `SPOUSE`, `IN_LAW`, or `PARENT` — `SELF` is not in the permissible set for a change — and otherwise the request is rejected with `ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN`. The third check is generation-skip: when the proposed beneficiary's relationship is more than one generation removed upward from the current beneficiary (the canonical example being a change from a `CHILD` beneficiary to a `PARENT` or `IN_LAW` beneficiary), the request is rejected with `ERR_BENEFICIARY_GENERATION_SKIP`. Implementations should table-drive the (from-relationship, to-relationship) pairs to recognize generation-skip cases. The generation-skip check is a **safety** check and fires ahead of business-constraint checks elsewhere in the system (such as the K-12 annual cap).

On a successful approval, the account's `beneficiary_id` is set to the request's `proposed_beneficiary_id`. As stated in Section 2.9, no other account field is mutated — `basis_balance_cents`, `earnings_balance_cents`, and `total_balance_cents` are conserved exactly, and `state_rule_version_at_open` and `lifetime_contribution_cap_cents` are untouched. A `PlanAdministrator` may instead reject a `SUBMITTED` request, transitioning its status from `SUBMITTED` to `REJECTED` and stamping `rejection_reason`, one of `RELATIONSHIP_NOT_PERMITTED`, `GENERATION_SKIP`, `ACCOUNT_NOT_OPEN`, or `IDENTICAL_TO_CURRENT`. Rejection mutates no account field.

### 3.7. Form 1099-Q — Aggregating, Locking, and the Cascade to REPORTED

A `PlanAdministrator` creates a `TaxReport` stub by supplying `account_id` and `tax_year` (a four-digit integer of at least 2000). The stub is created with `locked` set to false and with all four computed boxes — `gross_distribution_cents`, `earnings_cents`, `basis_cents`, `total_penalty_cents` — populated in **live recompute** mode. In live mode, every read of the report re-runs the aggregation against the current set of withdrawals.

The aggregation considers all withdrawals on the report's `account_id` whose disbursement date falls within `tax_year` and whose `status` is `CLASSIFIED` or `REPORTED`. Withdrawals in status `REQUESTED`, `REJECTED`, or `DISBURSED` are excluded. The eligible withdrawals are ordered by `created_at` ascending with `id` ascending as a tie-breaker. The four boxes are then computed as pure integer sums of the already-rounded per-withdrawal values: `gross_distribution_cents` is the sum of `requested_amount_cents` (Box 1 of the 1099-Q); `earnings_cents` is the sum of `earnings_portion_cents` (Box 2); `basis_cents` is `gross_distribution_cents` minus `earnings_cents` (Box 3); and `total_penalty_cents` is the sum of `penalty_cents`. As emphasized in Section 2.8, this per-withdrawal-then-sum order is canonical; sum-then-round (re-deriving earnings as ratio × total at report time) produces different cents and is incorrect.

A `PlanAdministrator` finalizes a tax report, transitioning it into **frozen snapshot** mode. Finalize runs the aggregation one last time, flips `locked` from false to true, and cascades: every withdrawal on the same account in status `CLASSIFIED` whose disbursement year equals `tax_year` is transitioned from `CLASSIFIED` to `REPORTED`. Each cascaded transition refreshes the affected withdrawal's `updated_at` and increments its `version`. Once a report is locked, its boxes are immutable: subsequent disburse and classify operations targeting the same `(account_id, tax_year)` are rejected with `ERR_TAX_REPORT_LOCKED`. A `Donor` or `PlanAdministrator` may retrieve any tax report by `id` (a `Beneficiary` may read tax reports on accounts they benefit from); when the report is unlocked, the read triggers a live recompute, and when the report is locked, the frozen boxes are returned unchanged.

### 3.8. Test-Driving the Logical Clock and the Recurring Sweep

Because the system's behavior depends on calendar time — annual K-12 cap reset on January 1, donor YTD totals reset on January 1, tax-year membership of a withdrawal determined by its disbursement date, recurring plans firing at `next_run_at` — two test-driving endpoints are exposed for use by an administrator. An admin-only clock-advance capability takes a body containing `to_iso8601` and moves the server's `now()` forward to that instant; time only moves forward, and an attempt to advance to a moment less than or equal to current `now()` is rejected with `ERR_CLOCK_NOT_MOVING_FORWARD`. An admin-only sweep capability iterates every `ACTIVE` recurring plan whose `next_run_at` is at or before the current `now()`, materializes one `PENDING` contribution per qualifying plan (stamped with `contribution_kind` of `RECURRING` and the originating `recurring_plan_id`), and advances each swept plan's `next_run_at` by `cadence_days` × 86400 seconds. The output of the sweep is the list of newly created contributions.

## 4. Endpoint Definitions

All endpoints below return HTTP 201 when they create a new persistent resource, and HTTP 200 for all other successful operations (state transitions, reads, list, and PATCH). The table is deliberately minimal: it does not expose request bodies, response bodies, or side effects — those are fully described in Section 3, and implementers must read the narrative there to reconstruct the full contract of each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/donors` | Register a donor | `PlanAdministrator` |
| GET | `/donors/{id}` | Get a donor including computed YTD totals | `PlanAdministrator`, `Donor` |
| POST | `/beneficiaries` | Register a beneficiary | `PlanAdministrator`, `Donor` |
| GET | `/beneficiaries/{id}` | Get a beneficiary including `k12_ytd_qualified_cents` | `PlanAdministrator`, `Donor` |
| POST | `/accounts` | Open a 529 account; pins `lifetime_contribution_cap_cents` and `state_rule_version_at_open` | `Donor` |
| GET | `/accounts/{id}` | Get an account including computed balances | `PlanAdministrator`, `Donor`, `Beneficiary` |
| GET | `/accounts` | List accounts; supports filter by `primary_donor_id`, `beneficiary_id`, `status`, `state_plan_code` | `PlanAdministrator`, `Donor`, `Beneficiary` |
| POST | `/accounts/{id}/restrict` | Restrict the account; pauses all `ACTIVE` recurring plans | `PlanAdministrator` |
| POST | `/accounts/{id}/release` | Release the restriction | `PlanAdministrator` |
| POST | `/accounts/{id}/close` | Close an account with zero balance | `Donor` |
| POST | `/accounts/{id}/contributions` | Create a contribution in `PENDING`; `donor_id` may differ from `primary_donor_id` | `Donor` |
| POST | `/contributions/{id}/settle` | Settle a `PENDING` contribution; updates account balances and donor YTD | `PlanAdministrator` |
| POST | `/contributions/{id}/reverse` | Reverse a `PENDING` contribution (cannot reverse `SETTLED`) | `PlanAdministrator` |
| GET | `/contributions/{id}` | Get a contribution | `PlanAdministrator`, `Donor` |
| GET | `/accounts/{id}/contributions` | List contributions on an account, filter by `status` and `contribution_kind` | `PlanAdministrator`, `Donor`, `Beneficiary` |
| POST | `/accounts/{id}/recurring-plans` | Create a recurring plan | `Donor` |
| PATCH | `/recurring-plans/{id}` | Update plan amount or cadence; supports OCC via `version` | `Donor` |
| POST | `/recurring-plans/{id}/pause` | Pause an `ACTIVE` recurring plan | `Donor` |
| POST | `/recurring-plans/{id}/resume` | Resume a `PAUSED` plan; only if account is `OPEN` | `Donor` |
| POST | `/recurring-plans/{id}/cancel` | Cancel a recurring plan | `Donor` |
| POST | `/accounts/{id}/withdrawals` | Create a withdrawal request | `Donor` |
| POST | `/withdrawals/{id}/disburse` | Disburse a `REQUESTED` withdrawal; runs the basis/earnings split | `Donor` |
| POST | `/withdrawals/{id}/reject` | Reject a `REQUESTED` withdrawal with a `rejected_reason` | `PlanAdministrator` |
| POST | `/withdrawals/{id}/expenses` | Attach an `EducationExpense` receipt to a `DISBURSED` withdrawal | `Donor` |
| POST | `/withdrawals/{id}/classify` | Classify `DISBURSED` → `CLASSIFIED`; runs K-12 cap application and non-qualified penalty | `Donor` |
| GET | `/withdrawals/{id}` | Get a withdrawal | `PlanAdministrator`, `Donor` |
| GET | `/accounts/{id}/withdrawals` | List withdrawals on an account, filter by `status` and `expense_category` | `PlanAdministrator`, `Donor`, `Beneficiary` |
| POST | `/accounts/{id}/beneficiary-change-requests` | Submit a beneficiary change for an account | `Donor` |
| POST | `/beneficiary-change-requests/{id}/approve` | Approve; mutates `beneficiary_id`; balances conserved | `PlanAdministrator` |
| POST | `/beneficiary-change-requests/{id}/reject` | Reject with a `rejection_reason` | `PlanAdministrator` |
| POST | `/tax-reports` | Create an unlocked `TaxReport` stub for `(account_id, tax_year)` | `PlanAdministrator` |
| GET | `/tax-reports/{id}` | Get a 1099-Q (live boxes if unlocked, frozen if locked) | `PlanAdministrator`, `Donor`, `Beneficiary` |
| POST | `/tax-reports/{id}/finalize` | Lock the 1099-Q; cascades all `CLASSIFIED` withdrawals in that year to `REPORTED` | `PlanAdministrator` |
| GET | `/state-rules/{state_code}` | Get a state rule | `PlanAdministrator`, `Donor` |
| GET | `/state-rules` | List all state rules | `PlanAdministrator`, `Donor` |
| POST | `/state-rules` | Seed or replace a state rule (administrative) | `PlanAdministrator` |
| POST | `/_clock/advance` | Advance the server clock to a supplied `to_iso8601` instant (test harness) | `PlanAdministrator` |
| POST | `/_sweep/run-recurring` | Sweep all `ACTIVE` recurring plans whose `next_run_at` has been reached | `PlanAdministrator` |

## 5. Error Code Catalogue

The trigger conditions for every error below are defined in the corresponding narrative of Sections 2 and 3 — this table summarizes only the identifier and its HTTP status code.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID_ROLE` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_RESTRICTED` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 422 |
| `ERR_LIFETIME_CAP_WOULD_EXCEED` | 422 |
| `ERR_GIFT_EXCLUSION_EXCEEDED` | 422 |
| `ERR_K12_CAP_EXCEEDED` | 422 |
| `ERR_EXPENSE_CATEGORY_MISMATCH` | 422 |
| `ERR_EXPENSE_OUT_OF_YEAR` | 422 |
| `ERR_BENEFICIARY_IDENTICAL_TO_CURRENT` | 422 |
| `ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN` | 422 |
| `ERR_BENEFICIARY_GENERATION_SKIP` | 422 |
| `ERR_TAX_REPORT_LOCKED` | 409 |
| `ERR_STALE_BENEFICIARY_SNAPSHOT` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_CLOCK_NOT_MOVING_FORWARD` | 422 |
| `ERR_VALIDATION_FAILED` | 400 |
