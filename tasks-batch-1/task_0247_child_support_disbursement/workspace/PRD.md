# Child Support Disbursement API — Product Requirements Document

## 1. Introduction

A State Disbursement Unit (SDU) sits at the center of the child-support payment pipeline: it establishes legal support orders against obligors, directs employers to withhold income, receives the money those employers remit, splits each remittance correctly across the obligor's outstanding obligations, and finally pays the collected funds out to the custodial families it serves. This API is the system of record for that pipeline. It exists to make every cent traceable — from the moment a charge accrues, through each employer payment and its allocation, to the disbursement that lands with the family or the portion the state retains as reimbursement for public assistance.

The domain is unforgiving in two distinct ways. First, money must reconcile: balances are never stored as mutable totals but are derived by replaying an append-only ledger, so that the unpaid current-support balance, the arrears principal, and the accrued interest can always be reconstructed from first principles. Second, the law constrains how money moves: federal wage-withholding caps limit how much an employer may lawfully send, statutory interest accrues on overdue principal, enforcement intercepts may only be certified once arrears cross a threshold, and whether collected arrears flow to the family or are recovered by the state depends on the family's public-assistance history. The API encodes these rules as hard constraints rather than advisory guidance.

Operationally, four kinds of users collaborate through the system. Agency caseworkers establish and steer the orders; a separate supervisor approves the changes a caseworker proposes; finance officers in the disbursement unit move the actual money; and employers and custodial parents interact in narrowly scoped, read-mostly ways. The sections that follow define the global contract (Section 2), the business workflows where the substantive rules live (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The entire API is mounted under the `/sdu` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If the `X-User-Role` header is missing or does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED`. When the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled precisely as follows: `CaseWorker`, `FinanceOfficer`, `Supervisor`, `Employer`, and `CustodialParty`.

Three of these roles are operator identities not tied to any persisted record. When `X-User-Role` is `CaseWorker`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `FinanceOfficer`, `X-User-ID` is likewise an opaque operator identifier the server does not match against any entity. When `X-User-Role` is `Supervisor`, `X-User-ID` is again an opaque operator identifier with no entity backing.

The remaining two roles are entity-backed and drive ownership checks. When `X-User-Role` is `Employer`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` compare the resource's employer foreign key to `X-User-ID`, so an employer may read only its own employer record, its own income withholding orders, and its own remittances. When `X-User-Role` is `CustodialParty`, `X-User-ID` is the `id` of the acting `CustodialParty`; ownership checks on any resource that references a `CustodialParty` compare the resource's custodial-party foreign key to `X-User-ID`, so a custodial parent may read only their own custodial-party record, the support orders that name them as payee, and the disbursements directed to them.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by the resource's creation timestamp in ascending order.

List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Append-Only Ledger

Most resources in this system carry a standard set of system-managed fields. Every `CustodialParty`, `NoncustodialParty`, `Employer`, `SupportOrder`, `IncomeWithholdingOrder`, `Remittance`, `Allocation`, `Disbursement`, `Modification`, and `EnforcementAction` includes an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recorded at creation, an `updated_at` timestamp (same format) refreshed on every mutation, and an integer `version` that starts at its initial value and increments by one on each mutation.

The `LedgerEntry` is the deliberate exception. A ledger entry is an immutable, append-only event: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version`. Ledger entries are never edited or deleted; corrections are made by appending compensating rows. Each ledger row records the `support_order_id` it posts against, an `entry_type`, a `bucket`, a signed `amount_cents`, a `source_ref` naming the originating entity (remittance, allocation, modification, or enforcement) for audit, and an `effective_at` posting timestamp that serves as the chronological replay key for balance derivation.

The three monetary balances on a support order are never stored as standing totals; they are recomputed inline from the ledger on every read and after every posting. The `entry_type` of a row is one of `CHARGE`, `PAYMENT`, `INTEREST`, `DISBURSEMENT`, or `ADJUSTMENT`, and its `bucket` is one of `CURRENT_SUPPORT`, `INTEREST`, or `PRINCIPAL`. A row's `amount_cents` is signed: a positive amount increases the owed balance of its bucket, and a negative amount reduces it. Concretely, `current_support_due_cents` is the sum of `CHARGE` and `ADJUSTMENT` rows tagged `CURRENT_SUPPORT` minus the sum of `PAYMENT` rows tagged `CURRENT_SUPPORT`, never allowed to fall below zero. The `arrears_principal_cents` balance is the sum of `CHARGE` and `ADJUSTMENT` rows tagged `PRINCIPAL` minus the sum of `PAYMENT` rows tagged `PRINCIPAL`, floored at zero. The `interest_balance_cents` is the sum of `INTEREST` and `ADJUSTMENT` rows tagged `INTEREST` minus the sum of `PAYMENT` rows tagged `INTEREST`, floored at zero.

### 2.5. Cascading State Propagation and Parallel Status Dimensions

A `SupportOrder` carries two independent status dimensions that evolve separately. The `obligation_status` dimension tracks the order's lifecycle and moves among `ESTABLISHED`, `ACTIVE`, `SUSPENDED`, `MODIFIED`, and the terminal `TERMINATED`. The `enforcement_status` dimension tracks intercept activity and moves among `NONE`, `INTERCEPT_PENDING`, `INTERCEPT_ACTIVE`, and `LIFTED`. The two dimensions never share a value and are advanced by different triggers; an order can be `ACTIVE` while simultaneously `INTERCEPT_ACTIVE`.

Several operations mutate more than one resource. When an operation cascades, every affected resource is itself a mutation: its `updated_at` is refreshed and, for resources that carry one, its `version` increments. Where the scaffolded workflows below describe a cascade — an enforcement proposal nudging an order's enforcement dimension, a remittance allocation posting payment rows and recomputing balances across several orders, an order termination closing out its withholding orders, or an applied modification flowing through to the obligor's computed totals — each touched resource records the mutation independently. The system may also advance a resource's state on its own, without an explicit client call against that resource, when the conditions for the transition are met as a downstream effect of another operation.

### 2.6. Nested Resource Resolution and Referential Integrity

All entities in this system are top-level collections linked by foreign keys; there is no resource nesting in URL paths. Nevertheless, every request that names a resource — whether by a path identifier or by a foreign key in the body — must resolve those references in left-to-right order, and the first identifier that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later reference or business rule is evaluated.

Beyond mere existence, certain creates require that the referenced resources be mutually compatible. The foreign-key compatibility check rejects bodies whose references do not fit together — for example, an `Allocation` whose `support_order_id` does not belong to the obligor of its `remittance_id`, or a `Disbursement` whose `allocation_id` does not belong to the support order named in its `support_order_id`. A compatibility failure of this kind is reported as `ERR_FK_MISMATCH`. This referential check applies when creating a support order, an income withholding order, a remittance, a disbursement, a modification, or an enforcement action.

### 2.7. Monetary Precision and Rounding

All monetary quantities are integer cents. Where a calculation produces a fractional cent — the lawful withholding cap and the per-order proration of a remittance are the two such cases — the result is rounded to a whole number of cents using the round-half-up method (a value of exactly one-half cent rounds up). Calculations that involve only integer addition, subtraction, and the taking of minimums — the within-order waterfall, the rollover carry, and the family-versus-state split — produce whole cents directly and require no rounding.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of a support order, and both take a mandatory `expected_support_order_version` field carrying the client's last observed `version` of the target `SupportOrder`.

The first is the proposal of an enforcement action. A request to propose an enforcement intercept must carry `expected_support_order_version` matching the target order's current `version`. If another writer has advanced the order's version since the client last read it — for instance by already proposing an enforcement action, which legitimately moves the order's `enforcement_status` to `INTERCEPT_PENDING` and bumps its `version` — the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a second proposal from double-certifying against a view the client never observed.

The second is the application of an approved modification. A request to apply a modification must carry `expected_support_order_version` matching the linked order's current `version`. If another modification has already been applied — legitimately superseding `current_support_cents` and bumping the order's `version` — applying this stale view would clobber the newer amount, so the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and no other endpoint performs this check.

### 2.9. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. Authentication of the `X-User-Role` header comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then foreign-key compatibility of body references (`ERR_FK_MISMATCH`), then the structural validity of the body — required fields present and well-typed, cents fields non-negative integers, enum members recognized (`ERR_INVALID_REQUEST`) — and, on employer creation, the uniqueness of the federal identifier (`ERR_DUPLICATE_FEIN`). Only after these gate checks pass does the system evaluate transition-state validity (`ERR_INVALID_STATE`), then the optimistic-concurrency version match (`ERR_STALE_VERSION`), and then the operation-specific business rules described throughout Section 3. The effect of this ordering is that, for example, a request against a missing resource always surfaces as `ERR_NOT_FOUND` rather than being masked by a later state or business check.

## 3. Business Logic & Workflows

### 3.1. Standing the Cases Up: Parties, Employers, and Orders

The pipeline begins with the people and organizations involved. A `CaseWorker` registers a custodial parent by supplying the payee's `full_name` and their two-letter `state_code` of residence, optionally declaring the family's public-assistance history through `assistance_status`. That status is one of `NEVER_ASSISTED`, `FORMERLY_ASSISTED`, or `CURRENTLY_ASSISTED`, and it defaults to `NEVER_ASSISTED` when omitted. Every custodial party is created with a `payee_status` of `ACTIVE`; this status is system-managed and is the gate that later decides whether money may actually leave for the family.

A `CaseWorker` likewise registers the obligor — the noncustodial parent — with their `full_name`, the `ssn_last4` digits used to match them to employer filings, and an optional `supports_second_family` flag that defaults to false and later selects which withholding-cap tier applies. The obligor also exposes a computed `total_current_support_cents`, which is initialized to zero at registration and thereafter reflects the sum of `current_support_cents` across this obligor's support orders whose `obligation_status` is either `ACTIVE` or `MODIFIED`.

Employers are registered by a `CaseWorker` with a `legal_name`, a `fein` (the federal employer identification number), and an optional `remittance_method` that is either `EFT` or `CHECK` and defaults to `EFT`. The `fein` must be unique across all employers; a duplicate is rejected with `ERR_DUPLICATE_FEIN`.

With the parties in place, a `CaseWorker` creates a `SupportOrder` by naming the `custodial_party_id` payee and the `noncustodial_party_id` obligor, stating the monthly `current_support_cents` obligation, and optionally supplying `frequency` (which in this version supports only the value `MONTHLY` and defaults to it), `interest_rate_bps` (the statutory simple-interest annual rate in basis points, defaulting to 1000, i.e. ten percent per year), and `assigned_arrears_cents` (the arrears balance assigned to the state as reimbursement, defaulting to zero). A newly created order begins with `obligation_status` of `ESTABLISHED` and `enforcement_status` of `NONE`. At creation the system also derives the order's `arrears_distribution_rule`: if the linked custodial party's `assistance_status` is `NEVER_ASSISTED`, the rule is `FAMILY_FIRST`; otherwise — that is, when the family is `FORMERLY_ASSISTED` or `CURRENTLY_ASSISTED` — the rule is `STATE_FIRST`. This same derivation is reapplied whenever the custodial party's `assistance_status` changes. The order also exposes the four computed balances introduced in Section 2.4 — `current_support_due_cents`, `arrears_principal_cents`, `interest_balance_cents`, and `net_disbursed_to_family_cents` — and a system-managed `last_interest_accrual_at` timestamp that marks the point through which interest has been accrued.

Reading an obligor returns the freshly computed `total_current_support_cents`, and reading a support order returns its three owed balances recomputed from the ledger at read time. Support orders can be listed and narrowed by `noncustodial_party_id` or `custodial_party_id`.

### 3.2. Moving an Order Through Its Lifecycle

Activation is the gateway to accrual. A `CaseWorker` activates an order, which is permitted only when its `obligation_status` is `ESTABLISHED`, `SUSPENDED`, or `MODIFIED`; attempting it from any other state is rejected with `ERR_INVALID_STATE`. Activation from `ESTABLISHED` additionally requires that `current_support_cents` be greater than zero, failing with `ERR_INVALID_AMOUNT` otherwise. Activation moves `obligation_status` to `ACTIVE`. On the first activation the system stamps `last_interest_accrual_at` with the current clock time and posts the order's first `CURRENT_SUPPORT` `CHARGE` ledger entry for the monthly amount. Each activation increments the order's `version`.

Suspension takes an order out of accrual without ending it. A `CaseWorker` may suspend an order only while its `obligation_status` is `ACTIVE` (otherwise `ERR_INVALID_STATE`); the order moves to `SUSPENDED`, no new current-support charges accrue while it stays there, and the `version` increments. A suspended order returns to `ACTIVE` through the same activation path described above.

A monthly charge advances the obligation period. When a `CaseWorker` posts a charge, the system first performs an arrears rollover: it reads the current `current_support_due_cents` as the carry amount, and if that carry is greater than zero it posts a `PAYMENT` row in the `CURRENT_SUPPORT` bucket for that amount (clearing the current bucket) together with a `CHARGE` row in the `PRINCIPAL` bucket for the same amount (moving the unpaid period into arrears principal). Only after the rollover does it post the fresh `CURRENT_SUPPORT` `CHARGE` of `current_support_cents`, and that fresh charge is posted only when the order's `obligation_status` is `ACTIVE` or `MODIFIED`. After posting, `current_support_due_cents` and `arrears_principal_cents` are recomputed.

Termination closes an order permanently, and it is heavily guarded. A `CaseWorker` may terminate an order only when its `obligation_status` is `ACTIVE`, `SUSPENDED`, or `MODIFIED`; from any other state the request fails with `ERR_INVALID_STATE`. Two further guards then apply, each with its own code: the order may be terminated only when both `arrears_principal_cents` and `interest_balance_cents` are zero, failing with `ERR_ARREARS_OUTSTANDING` if either remains, and only when its `enforcement_status` is neither `INTERCEPT_PENDING` nor `INTERCEPT_ACTIVE`, failing with `ERR_ENFORCEMENT_ACTIVE` otherwise. When termination succeeds, the order moves to the terminal `TERMINATED`, every income withholding order on this order that is still `ISSUED` or `ACKNOWLEDGED` cascades to `TERMINATED`, and the order's `version` increments.

### 3.3. Directing Employers to Withhold

To collect from wages, a `CaseWorker` issues an income withholding order (IWO) by naming the `support_order_id` it serves, the `employer_id` directed to withhold, the per-period `ordered_amount_cents`, and the coverage interval bounded by `effective_start_at` and `effective_end_at`. The `ordered_amount_cents` must be greater than zero, failing with `ERR_INVALID_AMOUNT`. A new IWO is created with `status` of `ISSUED`.

The coverage interval is half-open: it runs from `effective_start_at` inclusive up to `effective_end_at` exclusive. A new IWO is rejected with `ERR_IWO_PERIOD_OVERLAP` if its half-open interval overlaps any non-`TERMINATED` IWO already recorded on the same `support_order_id`. Because the interval is half-open, adjacency is allowed: an IWO whose `effective_start_at` equals an existing IWO's `effective_end_at` does not overlap and is accepted.

An `Employer` acknowledges receipt of an IWO, which is permitted only while its `status` is `ISSUED` (otherwise `ERR_INVALID_STATE`) and moves the `status` to `ACKNOWLEDGED`. A `CaseWorker` may terminate an IWO directly while its `status` is `ISSUED` or `ACKNOWLEDGED` (otherwise `ERR_INVALID_STATE`), moving it to the terminal `TERMINATED`; the same terminal outcome also arrives by cascade when the parent support order is terminated. Income withholding orders can be listed and filtered by `support_order_id` or `employer_id`.

### 3.4. Receiving and Capping Employer Remittances

When an employer transmits withheld pay, the remittance is recorded — by an `Employer` reporting its own payment or by a `FinanceOfficer` — naming the `employer_id`, the `noncustodial_party_id` the money was withheld from, the employee's `disposable_earnings_cents` for the pay period, and the `gross_remitted_cents` actually transmitted. A new remittance is created with `status` of `RECEIVED`.

At creation the system computes the lawful withholding ceiling under the federal Consumer Credit Protection Act and records it as `ccpa_cap_cents`, together with the `distributable_cents` that will actually enter allocation. The cap percentage depends on two facts about the obligor: whether they support a second family, and how far their arrears have fallen behind. Behind-ness is measured in whole weeks overdue: take the sum of `arrears_principal_cents` across the obligor's `ACTIVE` and `MODIFIED` orders, divide it by the weekly equivalent of the obligor's `total_current_support_cents`, and discard any fractional week (floor to a whole number of weeks). The threshold that raises the tier is twelve weeks. If the obligor supports a second family and is fewer than twelve weeks overdue, the cap percentage is fifty percent; if they support a second family and are twelve or more weeks overdue, it is fifty-five percent; if they do not support a second family and are fewer than twelve weeks overdue, it is sixty percent; and if they do not support a second family and are twelve or more weeks overdue, it is sixty-five percent. The `ccpa_cap_cents` is the `disposable_earnings_cents` multiplied by the selected percentage, rounded half-up to whole cents. The `distributable_cents` is the smaller of `gross_remitted_cents` and `ccpa_cap_cents`. When the gross exceeds the cap, the cap binds and the shortfall — the gross minus the cap — is not distributable and the employer is notified of the unwithholdable excess; when the gross is at most the cap, the cap is non-binding and `distributable_cents` equals `gross_remitted_cents`.

Remittances can be read individually and listed, filtered by `employer_id` or `noncustodial_party_id`. A `FinanceOfficer` may return a received remittance to the employer without allocating it; returning is permitted only while `status` is `RECEIVED` (otherwise `ERR_INVALID_STATE`) and moves the `status` to the terminal `RETURNED` with no allocation posted.

### 3.5. Allocating a Remittance Across Orders

A `FinanceOfficer` allocates a received remittance, which spreads its distributable funds across the obligor's outstanding orders. Allocation is permitted only while the remittance `status` is `RECEIVED` (otherwise `ERR_INVALID_STATE`); the obligor must have at least one eligible support order — one whose `obligation_status` is `ACTIVE` or `MODIFIED` — or the request fails with `ERR_NO_ALLOCABLE_ORDER`; and the remittance's `distributable_cents` must be greater than zero, failing with `ERR_NOTHING_TO_ALLOCATE`. Orders that are `SUSPENDED`, `ESTABLISHED`, or `TERMINATED` are excluded from the candidate set. On success, the remittance moves to the terminal `ALLOCATED`.

Allocation proceeds in two stages. The first stage spreads the `distributable_cents` across eligible orders, taken in ascending `created_at` order, by their share of current support. Let the total current support be the sum of `current_support_cents` across all eligible orders. If the `distributable_cents` is less than or equal to that total, nothing reaches arrears: each order's current-support slice is the `distributable_cents` multiplied by that order's `current_support_cents` divided by the total, rounded half-up to whole cents. Because per-order rounding can leave the slices summing to a cent or two more or less than the distributable amount, the leftover remainder (the `distributable_cents` minus the sum of the rounded slices) is assigned in full to the order with the greatest `current_support_cents`, breaking ties toward the earliest `created_at`. In this shortfall branch every order's interest slice and principal slice are zero.

If instead the `distributable_cents` exceeds the total current support, current support is satisfied first on every order and the surplus cascades into arrears. Each order's current-support slice is set to its `current_support_due_cents` capped at its `current_support_cents`; the surplus is the `distributable_cents` minus the sum of those current-support slices. The second stage then walks the eligible orders in ascending `created_at` order and applies the running surplus to each order through the within-order waterfall, reducing the surplus as it goes, until the surplus is exhausted.

The within-order waterfall fills an order's buckets in a pinned sequence — current support, then interest, then principal. Given an amount to apply, the current-support portion is the smaller of that amount and the order's `current_support_due_cents`; the remainder after that is the amount less the current-support portion. The interest portion is the smaller of that remainder and the order's `interest_balance_cents`; the remainder shrinks again by the interest portion. The principal portion is the smaller of the new remainder and the order's `arrears_principal_cents`; anything still left after principal is an overpayment held as unapplied credit. Interest is therefore always consumed before principal, and principal is touched only once interest reaches zero; when the amount does not exceed `current_support_due_cents`, interest and principal are left untouched.

For each eligible order the system creates an `Allocation` recording the `remittance_id` it splits, the `support_order_id` it applied to, and the resulting `current_support_applied_cents`, `interest_applied_cents`, and `principal_applied_cents`, with `total_applied_cents` being the sum of those three slices. For each allocation it posts the corresponding `PAYMENT` ledger rows, one per bucket, against the target order, and then recomputes that order's `current_support_due_cents`, `interest_balance_cents`, and `arrears_principal_cents` from the ledger. Allocations can be listed and filtered by `remittance_id` or `support_order_id` and read individually. If an allocation drives an order's arrears principal and interest both to zero while an enforcement intercept is active on that order, the enforcement is satisfied automatically as described in Section 3.8.

### 3.6. Accruing Statutory Interest

Interest accrues as simple interest on arrears principal only — never on already-accrued interest. A `CaseWorker` or a `FinanceOfficer` triggers accrual on an order. The system counts whole days only: it takes the time elapsed between `last_interest_accrual_at` and the current clock and floors it to a whole number of days. The accrued amount is the `arrears_principal_cents` multiplied by the annual rate (the `interest_rate_bps` divided by ten thousand), multiplied by the day count, divided by 365, then rounded half-up to whole cents. When at least one whole day has elapsed, the system posts an `INTEREST` ledger row in the `INTEREST` bucket for the accrued amount and advances `last_interest_accrual_at` by exactly that whole-day count — not all the way to the clock — so that the fractional-day remainder is preserved for the next accrual. When fewer than a full day has elapsed (a day count of zero), the accrued amount is zero, no ledger row is posted, and `last_interest_accrual_at` is left unchanged. The same interest computation is also evaluated when checking an order's eligibility to terminate.

The ledger trail is fully auditable. Ledger entries can be listed for an order and filtered by `support_order_id` or by `entry_type`, returned in chronological order, and any single entry can be read on its own.

### 3.7. Paying the Family and Splitting With the State

A `FinanceOfficer` creates a disbursement from an allocation slice by naming the `support_order_id` whose collection is paid out, the `custodial_party_id` payee, and the `allocation_id` slice being disbursed, optionally choosing a `method` of `EFT`, `CHECK`, or `DEBIT_CARD` (defaulting to `EFT`). A new disbursement is created with `status` of `PENDING`. The disbursement amount may not exceed the allocation slice's distributable total — the combined family and state amount derivable from that slice — and an attempt to over-disburse a slice is rejected with `ERR_OVER_DISBURSEMENT`.

At creation the system computes how the collected money divides between the family and the state, keyed on the order's `arrears_distribution_rule`. The arrears collected on the slice is its `interest_applied_cents` plus its `principal_applied_cents`; the current collected is its `current_support_applied_cents`. Under `FAMILY_FIRST` the state retains nothing — `state_retained_cents` is zero — and the `family_amount_cents` is the current collected plus the entire arrears collected. Under `STATE_FIRST` the `state_retained_cents` is the smaller of the arrears collected and the order's `assigned_arrears_cents`, and the `family_amount_cents` is the current collected plus whatever arrears collection remains after that retention (the arrears collected minus the state-retained amount). In both variants current support always passes through to the family in full; the variants differ only in how much of the arrears collection the family ultimately receives.

Sending a disbursement is the moment cash leaves for the family, and it is the one place the payee hold bites. A `FinanceOfficer` sends a pending disbursement, which is permitted only while its `status` is `PENDING` (otherwise `ERR_INVALID_STATE`) and only when the disbursement's `CustodialParty` has a `payee_status` of `ACTIVE`; a payee on hold causes `ERR_PAYEE_ON_HOLD`. On send, the `status` moves to `SENT`, the system posts a `DISBURSEMENT` ledger row in the `CURRENT_SUPPORT` bucket whose `amount_cents` is the negative of `family_amount_cents` (cash leaving to the family), the order's `net_disbursed_to_family_cents` increases by `family_amount_cents`, and the disbursement's `version` increments.

A sent disbursement can be reversed. A `FinanceOfficer` returns a disbursement only while its `status` is `SENT` (otherwise `ERR_INVALID_STATE`), moving it to the terminal `RETURNED`. The return posts a compensating `ADJUSTMENT` ledger row in the `CURRENT_SUPPORT` bucket whose `amount_cents` is the positive `family_amount_cents`, exactly negating the send's `DISBURSEMENT` row; the order's `net_disbursed_to_family_cents` decreases by `family_amount_cents` back to its pre-send value, leaving the conserved cash-out total with zero drift; and the disbursement's `version` increments. Crucially, the order's owed buckets — `current_support_due_cents`, `interest_balance_cents`, and `arrears_principal_cents` — are unaffected by both the send and the return, because disbursement sits downstream of collection. Accordingly, `net_disbursed_to_family_cents` is the sum of `family_amount_cents` over this order's `SENT` disbursements minus the sum over its `RETURNED` disbursements, so a send-then-return pair leaves it unchanged. A `FinanceOfficer` may place or release a payee hold on a custodial party, setting `payee_status` to `HOLD` when the `hold` flag is true and back to `ACTIVE` when it is false. Disbursements can be read individually and listed, filtered by `support_order_id`, `custodial_party_id`, or `allocation_id`.

### 3.8. Enforcement Intercepts on Delinquent Orders

When an order falls far enough behind, the agency can intercept tax refunds or suspend licenses. A `CaseWorker` proposes an enforcement action by naming the `support_order_id`, choosing an `action_type` of either `TAX_INTERCEPT` or `LICENSE_SUSPENSION`, and supplying the `expected_support_order_version` for the stale-version guard described in Section 2.8. Proposal is allowed only when the certifiable arrears — the order's `arrears_principal_cents` plus its `interest_balance_cents` — reach the statutory threshold of fifty thousand cents, with the boundary inclusive (an amount exactly equal to the threshold qualifies); a delinquency below the threshold is rejected with `ERR_BELOW_ENFORCEMENT_THRESHOLD`. A successful proposal creates the action with `status` of `PROPOSED` and, as a cross-entity effect, moves the order's `enforcement_status` from `NONE` to `INTERCEPT_PENDING` and increments the order's `version`.

A `CaseWorker` certifies a proposed action, which is permitted only when its own `status` is `PROPOSED` and the linked order's `enforcement_status` is `INTERCEPT_PENDING`; either condition failing yields `ERR_INVALID_STATE`. Certification takes a snapshot of `certified_arrears_cents` equal to the order's `arrears_principal_cents` plus its `interest_balance_cents` at that moment, moves the action's `status` to `CERTIFIED`, and as a cross-entity effect advances the order's `enforcement_status` from `INTERCEPT_PENDING` to `INTERCEPT_ACTIVE`. A `CaseWorker` may instead withdraw a proposed action while its `status` is `PROPOSED` (otherwise `ERR_INVALID_STATE`); withdrawal moves the action to the terminal `WITHDRAWN` and, as a cross-entity effect, returns the order's `enforcement_status` from `INTERCEPT_PENDING` to `NONE`.

Once an action is `CERTIFIED`, it is satisfied automatically rather than by an explicit call: when a remittance allocation drives the order's `arrears_principal_cents` and `interest_balance_cents` both to zero, the system moves the action's `status` to the terminal `SATISFIED` and, as a transitive cascade, advances the order's `enforcement_status` from `INTERCEPT_ACTIVE` to `LIFTED`. Enforcement actions can be read individually and listed, filtered by `support_order_id`.

### 3.9. Modifying the Support Amount

Changing the monthly obligation runs through a segregated review cycle. A `CaseWorker` opens a modification by naming the `support_order_id` under review, the `proposed_current_support_cents` requested new amount, and the closed coverage interval bounded by `coverage_start_at` and `coverage_end_at`. A new modification is created with `status` of `DRAFT`. The coverage interval is closed: it runs from `coverage_start_at` through `coverage_end_at` inclusive on both ends. A new modification is rejected with `ERR_MODIFICATION_PERIOD_OVERLAP` if its closed interval overlaps any non-`REJECTED` modification on the same `support_order_id`; because both ends are inclusive, two modifications that merely touch at a boundary instant do overlap and the new one is rejected.

The review cycle then proceeds. A `CaseWorker` submits a draft, permitted only while `status` is `DRAFT` (otherwise `ERR_INVALID_STATE`) and only when `proposed_current_support_cents` is greater than zero (otherwise `ERR_INVALID_AMOUNT`); submission moves the `status` to `SUBMITTED`. A `Supervisor` — segregated from the caseworker who submitted — decides a submitted modification by supplying a `decision`. A decision to approve is permitted only while `status` is `SUBMITTED` and only when the linked order's `obligation_status` is `ACTIVE`, failing otherwise with `ERR_INVALID_STATE` or `ERR_ORDER_NOT_ACTIVE` respectively, and moves the `status` to `APPROVED`. A decision to reject is permitted only while `status` is `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and moves the `status` to `REJECTED`. A rejected modification is not dead: a `CaseWorker` revises it, permitted only while `status` is `REJECTED` (otherwise `ERR_INVALID_STATE`), which cycles the `status` back to `DRAFT` for re-submission.

Applying an approved modification is the act that changes the order, and it is OCC-guarded. A `CaseWorker` applies a modification, supplying the `expected_support_order_version` described in Section 2.8; application is permitted only while the modification's `status` is `APPROVED` (otherwise `ERR_INVALID_STATE`) and only when the linked order's `obligation_status` is `ACTIVE` (otherwise `ERR_ORDER_NOT_ACTIVE`). On success the modification moves to the terminal `APPLIED`; the linked order's `current_support_cents` is set to the modification's `proposed_current_support_cents`; the order's `obligation_status` moves from `ACTIVE` to `MODIFIED` as a cross-entity transition; the obligor's `total_current_support_cents` is recomputed as a transitive cascade; and the order's `version` increments. An order in `MODIFIED` returns to `ACTIVE` through the ordinary activation path. Modifications can be read individually and listed, filtered by `support_order_id`.

### 3.10. The Logical Clock

Interest accrual, charge posting, and date-stamped ledger postings all key off the server's logical UTC clock. For deterministic operation, a `CaseWorker` or a `FinanceOfficer` may set the clock to a supplied instant by providing `to_iso8601`. Advancing the clock changes the basis for the next interest accrual and for any newly posted entries; it does not retroactively rewrite entries already posted.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the payee-hold toggle — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sdu/custodial-parties` | Register a custodial party (payee) | CaseWorker |
| GET | `/sdu/custodial-parties/{id}` | Get a custodial party | CaseWorker, FinanceOfficer, CustodialParty |
| POST | `/sdu/custodial-parties/{id}/hold` | Place or release a payee hold | FinanceOfficer |
| POST | `/sdu/noncustodial-parties` | Register a noncustodial party (obligor) | CaseWorker |
| GET | `/sdu/noncustodial-parties/{id}` | Get a noncustodial party with computed total | CaseWorker, FinanceOfficer |
| POST | `/sdu/employers` | Register an employer | CaseWorker |
| GET | `/sdu/employers/{id}` | Get an employer | CaseWorker, FinanceOfficer, Employer |
| POST | `/sdu/support-orders` | Create a support order | CaseWorker |
| GET | `/sdu/support-orders/{id}` | Get a support order with computed balances | CaseWorker, FinanceOfficer, CustodialParty |
| GET | `/sdu/support-orders` | List support orders, filterable by obligor or payee | CaseWorker, FinanceOfficer |
| POST | `/sdu/support-orders/{id}/activate` | Activate (or reactivate) a support order | CaseWorker |
| POST | `/sdu/support-orders/{id}/suspend` | Suspend an active support order | CaseWorker |
| POST | `/sdu/support-orders/{id}/terminate` | Terminate a support order | CaseWorker |
| POST | `/sdu/support-orders/{id}/accrue-interest` | Accrue interest on arrears principal | CaseWorker, FinanceOfficer |
| POST | `/sdu/support-orders/{id}/post-charge` | Post a monthly current-support charge | CaseWorker |
| GET | `/sdu/ledger-entries` | List ledger entries for an order (chronological) | CaseWorker, FinanceOfficer |
| GET | `/sdu/ledger-entries/{id}` | Get a single ledger entry | CaseWorker, FinanceOfficer |
| POST | `/sdu/income-withholding-orders` | Issue an income withholding order | CaseWorker |
| GET | `/sdu/income-withholding-orders/{id}` | Get an income withholding order | CaseWorker, FinanceOfficer, Employer |
| GET | `/sdu/income-withholding-orders` | List IWOs, filterable by order or employer | CaseWorker, FinanceOfficer, Employer |
| POST | `/sdu/income-withholding-orders/{id}/acknowledge` | Employer acknowledges an IWO | Employer |
| POST | `/sdu/income-withholding-orders/{id}/terminate` | Terminate an IWO | CaseWorker |
| POST | `/sdu/remittances` | Record an employer remittance; computes CCPA cap | Employer, FinanceOfficer |
| GET | `/sdu/remittances/{id}` | Get a remittance | CaseWorker, FinanceOfficer, Employer |
| GET | `/sdu/remittances` | List remittances, filterable by employer or obligor | CaseWorker, FinanceOfficer, Employer |
| POST | `/sdu/remittances/{id}/allocate` | Allocate a received remittance across eligible orders | FinanceOfficer |
| POST | `/sdu/remittances/{id}/return` | Return a received remittance without allocating | FinanceOfficer |
| GET | `/sdu/allocations` | List allocations, filterable by remittance or order | CaseWorker, FinanceOfficer |
| GET | `/sdu/allocations/{id}` | Get a single allocation slice | CaseWorker, FinanceOfficer |
| POST | `/sdu/disbursements` | Create a pending disbursement from an allocation slice | FinanceOfficer |
| GET | `/sdu/disbursements/{id}` | Get a disbursement | CaseWorker, FinanceOfficer, CustodialParty |
| GET | `/sdu/disbursements` | List disbursements, filterable by order, payee, or allocation | CaseWorker, FinanceOfficer, CustodialParty |
| POST | `/sdu/disbursements/{id}/send` | Send a pending disbursement to the payee | FinanceOfficer |
| POST | `/sdu/disbursements/{id}/return` | Mark a sent disbursement returned and post the compensating entry | FinanceOfficer |
| POST | `/sdu/modifications` | Open a modification draft for a support order | CaseWorker |
| GET | `/sdu/modifications/{id}` | Get a modification | CaseWorker, FinanceOfficer, Supervisor |
| GET | `/sdu/modifications` | List modifications, filterable by order | CaseWorker, FinanceOfficer, Supervisor |
| POST | `/sdu/modifications/{id}/submit` | Submit a draft modification for review | CaseWorker |
| POST | `/sdu/modifications/{id}/decide` | Approve or reject a submitted modification | Supervisor |
| POST | `/sdu/modifications/{id}/revise` | Send a rejected modification back to draft | CaseWorker |
| POST | `/sdu/modifications/{id}/apply` | Apply an approved modification (OCC-guarded) | CaseWorker |
| POST | `/sdu/enforcement-actions` | Propose an enforcement intercept (OCC-guarded) | CaseWorker |
| GET | `/sdu/enforcement-actions/{id}` | Get an enforcement action | CaseWorker, FinanceOfficer |
| GET | `/sdu/enforcement-actions` | List enforcement actions, filterable by order | CaseWorker, FinanceOfficer |
| POST | `/sdu/enforcement-actions/{id}/certify` | Certify a proposed enforcement action | CaseWorker |
| POST | `/sdu/enforcement-actions/{id}/withdraw` | Withdraw a proposed enforcement action | CaseWorker |
| POST | `/sdu/_clock/set` | Set the server's current UTC clock (test-driving) | CaseWorker, FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FK_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FEIN` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_BELOW_ENFORCEMENT_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_PAYEE_ON_HOLD` | 409 Conflict |
| `ERR_NO_ALLOCABLE_ORDER` | 409 Conflict |
| `ERR_NOTHING_TO_ALLOCATE` | 409 Conflict |
| `ERR_ARREARS_OUTSTANDING` | 409 Conflict |
| `ERR_ENFORCEMENT_ACTIVE` | 409 Conflict |
| `ERR_ORDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_OVER_DISBURSEMENT` | 409 Conflict |
| `ERR_IWO_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_MODIFICATION_PERIOD_OVERLAP` | 409 Conflict |
