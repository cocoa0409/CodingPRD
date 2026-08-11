# Rep-Payee Professional Fiduciary API — Product Requirements Document

## 1. Introduction

Professional fiduciary organizations that act as Social Security Administration representative payees operate under an unusually dense web of obligations: every dollar of a beneficiary's funds must be traceable, every withdrawal from a court-blocked account must trace back to a granted court order, surety bond coverage must always exceed funds under management, and annual accountings to the SSA (form SSA-6233) and to state courts must reconcile to the cent against the ledger. A failure in any of these is not a bookkeeping inconvenience — it is a compliance event that can trigger audits, bond claims, or removal of the payee.

This document specifies a REST API that runs the daily operations of such an organization. Case managers draft monthly budgets and request disbursements against them; financial officers move money under segregation-of-duties controls; court-appointed conservators co-sign larger or exclusive-scope payments; compliance auditors adjudicate periodic reports and investigate misuse. The system maintains an append-only ledger per managed account, derives every balance from that ledger, enforces Medicaid countable-resource ceilings with forward-looking spend-down planning, and drives time-dependent behavior — court-order expiry, bond lapse, report due dates — from a single controllable logical clock rather than the wall clock. The audience is the engineering team building this service; the contract surfaces (response envelopes, pagination, error identifiers) are fixed, while the business rules are presented as the workflows in which they live.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `FiduciaryAdmin` — the organization administrator: client intake and lifecycle, benefit entitlement registration and verification, court orders, surety bonds, the conservator registry, and the logical clock.
- `CaseManager` — the caseworker: budget plans, disbursement requests, spend-down plans, and report drafting.
- `FinancialOfficer` — money movement: trust accounts, deposits, disbursement approval, release and return, budget approval, and report submission.
- `ConservatorOfficer` — a court-appointed conservator acting on coordinated clients; the only operation exclusive to this role is disbursement co-approval.
- `ComplianceAuditor` — the SSA, state, court, or bonding-company audit function: audit cases and report adjudication.

All five roles share read access: every list and get endpoint in the system accepts any authenticated role.

Identity semantics differ by role. When `X-User-Role` is `ConservatorOfficer`, `X-User-ID` is the `id` of the acting Conservator record; ownership checks on a disbursement awaiting co-approval compare the disbursement's client relationship against the Conservator entity whose `id` is presented in `X-User-ID`. When `X-User-Role` is `FiduciaryAdmin`, `CaseManager`, `FinancialOfficer`, or `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requested_by_user_id` on a disbursement, `created_by_user_id` on a budget plan, or `approved_by_user_id` on an approval) but does not compare it to any entity's `id`.

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

All error API responses (4xx status codes) follow this standard envelope format — including requests that match no route, rejected with `ERR_NOT_FOUND` (HTTP 404), and requests using an unsupported method on a known route, rejected with `ERR_METHOD_NOT_ALLOWED` (HTTP 405):

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

### 2.3. Pagination and List Filtering

List endpoints accept `limit` and `offset` query parameters. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. A `limit` that is not an integer in that range, or an `offset` that is not a non-negative integer, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are sorted by `created_at` ascending, and the `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Beyond paging, each list endpoint accepts optional equality filters drawn from the resource's own fields — the full vocabulary of filter names across the API is `status`, `client_id`, `medicaid_enrolled`, `claim_type`, `account_type`, `entry_type`, `period_month`, `superseded_by_plan_id`, `category`, `source`, `entitlement_id`, `order_type`, `executed_disbursement_id`, `report_type`, `target_month`, `authority`, `authority_scope`, `budget_plan_id`, `court_order_id`, `spend_down_plan_id`, `account_id`, and `co_approved_by_conservator_id`, each applied to the collection for which §4 lists it. The one boolean filter, `medicaid_enrolled`, matches enrolled clients only for the value `true` (case-insensitive); any other supplied value matches non-enrolled clients.

### 2.4. The Logical Clock

All time-dependent business behavior — statutory deadlines, coverage windows, expiry, lapse, period bucketing — reads from a single server-maintained **logical clock**, never from wall-clock time. At startup, before any operator has set it, the logical clock reads exactly 2026-05-01T00:00:00Z, and it must never silently fall back to wall-clock time. An administrator-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. The supplied instant is not constrained to the future — a supplied datetime without an explicit offset is read as UTC — and the transitions below are evaluated against the resulting reading. Advancing the clock is not a passive read: it evaluates time-triggered transitions, expiring court orders whose `expiry_date` has passed and lapsing surety bonds whose coverage has ended or whose premium has run out, as described in §3.7.

### 2.5. Resource Identity and Common Fields

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, plus a `created_at` and an `updated_at`, both ISO 8601 UTC timestamps with three fractional digits stamped from the logical clock (§2.4), and a `version` integer that starts at 1 when the resource is created and increments by one on every successful mutation of that resource. The one exception is the ledger entry: ledger entries carry only `id` and `created_at` — they are immutable once written, so both `updated_at` and `version` are absent from them. Version increments matter to clients holding resources across requests: client activation, suspension, and termination each increment the client's `version`; budget-plan creation increments the owning client's `version` in addition to creating the plan; rebalancing increments the plan's `version`; deposit posting and return each increment the deposit's `version`; disbursement release and return each increment the disbursement's `version`.

### 2.6. The Ledger as the System of Record

No account balance is ever stored as mutable state. A trust account's `balance_cents` is derived as the signed sum of its ledger entries, and every balance-affecting event in the system — posting a deposit, releasing a disbursement, returning either — appends exactly one ledger entry and then recomputes the derived balances that depend on it. Entries are append-only, are strictly serialized per account in request order, and each records the running `balance_after_cents` of its account immediately after itself in chronological replay order. All amounts across the API are integer cents; negative entry amounts are debits and positive amounts are credits. Because balances are derived, every balance-affecting mutation also refreshes the client-level rollups (`total_funds_cents`, `countable_resources_cents`) and the organization-wide bond rollup (`funds_under_management_cents`), as detailed in the workflows of §3.

### 2.7. Monetary Precision and Rounding Discipline

Money is always represented as whole integer cents. Three distinct rounding disciplines apply, each pinned to its calculation: the fiduciary fee is rounded half-up to whole cents exactly once per disbursement at release time (§3.6); budget allocation lines are rounded half-up to whole cents per line before any residual folding (§3.4); and bond utilization is an integer floor division with no rounding (§3.7). Spend-down excess figures and report totals use pure integer arithmetic with no rounding at all.

### 2.8. Optimistic Concurrency on Budget-Plan Creation

Exactly one write endpoint in the API is guarded by optimistic concurrency control: budget-plan creation. A request to create a budget plan must carry `expected_client_version`, the `version` of the owning client as last observed by the caller. If the client's current `version` has advanced since that observation — for example because another writer created a superseding plan, or a lifecycle action bumped the client — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a writer holding stale client state from blindly superseding a plan it never saw. The version check fires after the owning client reference has been resolved and before the client-activity gate, so a stale observation against a terminated client reports `ERR_STALE_VERSION` rather than `ERR_CLIENT_NOT_ACTIVE`. No other endpoint in the API accepts a version field; callers must not send one elsewhere.

### 2.9. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and earlier stages mask later ones. Stage one is authentication (§2.1): missing or invalid headers produce `ERR_UNAUTHENTICATED`. Stage two is role authorization: an authenticated role outside the endpoint's permitted set produces `ERR_FORBIDDEN`. Stage three is request-body shape: on every endpoint that accepts a request body, any field outside the endpoint's accepted set — including server-managed fields the caller has no business sending, such as `id`, `created_at`, or `version` — produces `ERR_INVALID_REQUEST` (HTTP 400), as do missing required fields, invalid enum values, violated integer constraints (amounts that must be positive, counts that must be non-negative), an `ssn_last4` that is not exactly four digits, budget line percents that do not sum to exactly 100 or repeat a category, malformed date strings, and date-ordering violations — an entitlement `effective_end_date` that does not fall after its start, a bond `coverage_end_date` that does not fall after its start, or a report or audit `period_end_date` that precedes its start. Stage four is existence: path identifiers are resolved first, from left to right, then body foreign-key references in their declared field order; an unknown client reference produces `ERR_CLIENT_NOT_FOUND`, and each other resource family reports its own identifier — `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_DEPOSIT_NOT_FOUND`, `ERR_COURT_ORDER_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_SPEND_DOWN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, and `ERR_CONSERVATOR_NOT_FOUND` — all at HTTP 404.

Stage five is the terminal-state guard: an entity already in a terminal state — a `TERMINATED` client or entitlement, a `CLOSED` account, a `RETURNED` deposit, a `SUPERSEDED` plan, a `REJECTED` or `RETURNED` disbursement, an `ACCEPTED` or `REJECTED` report, a `MET` or `LAPSED` spend-down plan, a `DISCHARGED` conservator, an `EXECUTED` or `EXPIRED` court order, a `LAPSED` bond, a `CLOSED_NO_ACTION` or `MISUSE_CONFIRMED` audit — rejects any further action with `ERR_ALREADY_TERMINAL` (HTTP 409). Stage six checks that the entity's state machine permits the requested transition from its current, non-terminal state (`ERR_INVALID_STATE`, HTTP 409). Stage seven is the client-activity gate (`ERR_CLIENT_NOT_ACTIVE`, HTTP 409), whose per-endpoint status requirements are given in §3. Stage eight is endpoint business rules, which fire in ascending priority order: on disbursement creation the court-order-required check precedes the dedicated-account category check, which precedes foreign-key coherence; on disbursement release the court-order grantability check precedes the court-order amount-cap check, which precedes the dedicated-account category check, which precedes the plan-period check, which precedes the plan-approval check, which precedes the insufficient-funds check, which precedes the budget-category check, with the active-bond presence check last among the business gates, followed by a final requirement that the disbursement's source account be `OPEN` (`ERR_ACCOUNT_NOT_OPEN`); on account close the zero-balance check precedes the pending-disbursements check; on report creation the period-overlap check precedes the period-gap check. Segregation-of-duties, conservator-activity, entitlement-overlap, bond-window, report-overdue, plan-period, entitlement-account-coherence, bond-coverage, spend-down-necessity, verified-entitlement, and unique-field checks each fire at their documented priority within their workflows in §3.

### 2.10. Cascading State Propagation

Several operations in this system deliberately mutate more than one entity, and the cascades are part of the contract, not side effects to be discovered. Four cascade families exist. The **client lifecycle cascade** propagates suspension and termination into accounts, entitlements, plans, and spend-downs (§3.1). The **freeze cascade** propagates an account freeze into that account's pending disbursements, rejecting them (§3.2). The **resource recompute chain** propagates every ledger write outward into account balances, client fund rollups, and bond utilization; automatic spend-down drafting when a Medicaid client's countable resources cross the ceiling is evaluated only on deposit posting (§3.3), not on other ledger writes such as disbursement returns. The **misuse cascade** propagates a confirmed audit finding into client suspension, then account freezes, then disbursement rejections (§3.9). Implementations must apply these cascades atomically with the transition that triggered them.

## 3. Business Logic & Workflows

### 3.1. Client Intake, Entitlements, and the Client Lifecycle

A `FiduciaryAdmin` opens a client relationship by registering the beneficiary with `legal_name`, `date_of_birth`, `ssn_last4` (exactly four digits), `county_of_residence` (the county code that fixes court jurisdiction), and `medicaid_enrolled`. `medicaid_resource_limit_cents` is stored on every client — defaulting to 200,000 cents ($2,000.00) when omitted, and required to be positive when supplied — and it acts as the countable-resource ceiling only when the client is Medicaid-enrolled. A new client begins in `INTAKE_REVIEW`. Three figures are always derivable on read: `total_funds_cents`, the sum of `balance_cents` over all of the client's accounts in `OPEN` or `FROZEN` status regardless of account type; `countable_resources_cents`, the same sum restricted to `OPERATING` and `RESTRICTED` accounts — `DEDICATED` accounts are excluded per SSA countable-resource rules; and `medicaid_at_risk`, which is true exactly when the client is Medicaid-enrolled and `countable_resources_cents` is strictly greater than `medicaid_resource_limit_cents` — equality with the ceiling is not at risk.

Before a client can be activated, the SSA award must exist and be verified. An administrator registers a benefit entitlement with the beneficiary's `client_id`, a `claim_type` of `SSI` or `SSDI`, a positive `monthly_benefit_cents`, and a half-open effective window from `effective_start_date` to `effective_end_date`, where a null `effective_end_date` means the award is open-ended; a supplied end date must fall after the start date. Among a client's non-`TERMINATED` entitlements sharing the same `claim_type`, these half-open windows must not overlap — adjacency, where one window's end equals the next window's start, is permitted — and an overlapping registration is rejected with `ERR_ENTITLEMENT_OVERLAP`. A new entitlement sits in `PENDING_VERIFICATION` until an administrator verifies it, which stamps `verified_at` with the current logical clock; an entitlement whose owning client has reached `TERMINATED` cannot be verified. Verification moves the entitlement `PENDING_VERIFICATION` → `VERIFIED`; an administrator may also end a verified award, moving it `VERIFIED` → `TERMINATED`.

Activation moves a client `INTAKE_REVIEW` → `ACTIVE` or `SUSPENDED` → `ACTIVE`. It requires at least one `VERIFIED` entitlement on the client — without one the request fails with `ERR_NO_VERIFIED_ENTITLEMENT` — and as it completes, every `FROZEN` account of the client reopens to `OPEN` and the client's `version` advances. Suspension moves a client `ACTIVE` → `SUSPENDED` and freezes every `OPEN` account to `FROZEN`, which in turn rejects that account's pending disbursements through the freeze cascade; suspension is also how the misuse cascade of §3.9 manifests on the client.

Termination moves a client `ACTIVE` → `TERMINATED` or `SUSPENDED` → `TERMINATED` and is unconditional with respect to disbursement history — a client with released-but-unreturned disbursements may still be terminated. The termination cascade is the widest in the system: every `OPEN` account freezes (continuing into the freeze cascade), every entitlement in `PENDING_VERIFICATION` or `VERIFIED` moves to `TERMINATED`, every budget plan in `DRAFT`, `PROPOSED`, or `APPROVED` moves to `SUPERSEDED` with a null `superseded_by_plan_id`, and every spend-down plan in `DRAFT` or `ACTIVE` moves to `LAPSED`.

### 3.2. Trust Accounts and the Append-Only Ledger

A `FinancialOfficer` opens managed accounts for a client. Each account records its owning `client_id`, an `account_type`, and an external `bank_account_ref` that must be unique across every trust account in the system — a duplicate reference is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`. Three account types exist. An `OPERATING` account is the ordinary spending account. A `RESTRICTED` account is court-blocked: withdrawals from it require a granted court order, as detailed in §3.6. A `DEDICATED` account holds SSI past-due benefits and may only fund `MEDICAL` and `EDUCATION` disbursements. Accounts open in `OPEN` status and move `OPEN` → `FROZEN` → `OPEN` only through the client lifecycle cascades of §3.1; there is no operator endpoint that freezes an account directly.

Closing an account moves it `OPEN` → `CLOSED` and carries two gates evaluated in order: the derived `balance_cents` must be exactly zero, failing with `ERR_ACCOUNT_NOT_ZERO`, and the account must have no disbursements in `REQUESTED`, `PENDING_CONSERVATOR`, or `APPROVED`, failing with `ERR_PENDING_DISBURSEMENTS`.

The ledger is the account's memory. Each ledger entry records its `account_id`, an `entry_type` of `DEPOSIT_POSTED`, `DEPOSIT_RETURNED`, `DISBURSEMENT_RELEASED`, or `DISBURSEMENT_RETURNED`, a signed `amount_cents`, a polymorphic `reference_id` naming the deposit or disbursement that produced the entry, and the running `balance_after_cents` (§2.6). Operators read an account's ledger chronologically, oldest entry first, optionally narrowed by `entry_type`. When an account freezes — through suspension, termination, or the misuse cascade — every disbursement posted against that account in `REQUESTED`, `PENDING_CONSERVATOR`, or `APPROVED` moves to `REJECTED`; this rejection is the freeze cascade's second link and needs no operator action.

### 3.3. Deposits, Bond Coverage, and the Resource Cascade

Inbound money arrives as a deposit recorded by a `FinancialOfficer` with the destination `account_id`, a `source` of `SSA_BENEFIT`, `PENSION`, `REFUND`, or `OTHER`, a positive `amount_cents`, and the `received_date` on which funds arrived. When the source is an SSA benefit, the optional `entitlement_id` links the deposit to the award; when present, the entitlement must belong to the same client as the destination account, a coherence enforced both at recording and again at posting, with violations rejected as `ERR_ENTITLEMENT_ACCOUNT_MISMATCH`. Recording a deposit also requires the account's owning client to be in any status other than `TERMINATED` — deposit creation against a terminated client fails with `ERR_CLIENT_NOT_ACTIVE`. A recorded deposit sits in `RECEIVED`.

Posting moves a deposit `RECEIVED` → `POSTED` and is the first balance-affecting event most accounts see. Posting evaluates its gates in order: the destination account must be `OPEN` — posting into a frozen or closed account fails with `ERR_ACCOUNT_NOT_OPEN` — then the entitlement coherence described above is re-checked (violations again rejected as `ERR_ENTITLEMENT_ACCOUNT_MISMATCH`), and finally bond coverage is respected: if an `ACTIVE` surety bond exists, the organization-wide funds under management after the post must not exceed that bond's `coverage_amount_cents`, or the post fails with `ERR_BOND_COVERAGE_EXCEEDED`; when no `ACTIVE` bond exists, posts are unbounded. A successful post stamps `posted_at` from the logical clock, appends a `DEPOSIT_POSTED` ledger entry crediting the full `amount_cents` with the deposit's id as its `reference_id`, and then runs the resource recompute chain: the account's `balance_cents` refreshes first, the client's `total_funds_cents` and `countable_resources_cents` refresh second, and the bond's `funds_under_management_cents` refreshes alongside them.

The recompute chain has a third, conditional link. When the client is Medicaid-enrolled and the refreshed `countable_resources_cents` has crossed strictly above `medicaid_resource_limit_cents`, and no spend-down plan in `DRAFT` or `ACTIVE` already exists for that client for the current logical-clock month, the system auto-creates a spend-down plan: status `DRAFT`, `auto_created` set true, an empty `entries` list, `target_month` set to the current clock month, and `provisional_excess_cents` computed by the provisional formula of §3.9. A posted deposit that is later sent back moves `POSTED` → `RETURNED`, appending a compensating `DEPOSIT_RETURNED` entry debiting the same amount and recomputing the same chain — account balance, client rollups, and bond funds under management.

### 3.4. Budget Plans: Drafting, Approval, Revision, and Rebalancing

A `CaseManager` drafts a monthly budget by creating a plan with the beneficiary's `client_id`, the `period_month` in year-month form, a positive `source_benefit_cents` as the allocation basis (usually the monthly benefit), and `lines` pairing a `category` with an integer `percent` between 0 and 100 inclusive. The percents must sum to exactly 100, categories must be unique within the plan, and the category vocabulary is `HOUSING`, `FOOD`, `CLOTHING`, `PERSONAL`, `MEDICAL`, `EDUCATION`, `SAVINGS`. Because creation supersedes, the request is optimistic-concurrency guarded per §2.8: it must carry `expected_client_version` matching the client's current `version`, or it is refused with `ERR_STALE_VERSION`. The create also requires the client to be in any status other than `TERMINATED` — drafting against a terminated client fails with `ERR_CLIENT_NOT_ACTIVE`. A successful create stamps `created_by_user_id` from the requester's `X-User-ID`, marks any existing non-`SUPERSEDED` plan for the same client and `period_month` as `SUPERSEDED` with `superseded_by_plan_id` pointing at the new plan, advances the client's `version`, and freezes the allocation math described next.

Allocation is computed once, at creation. Each line's planned amount is `source_benefit_cents` multiplied by the line's `percent` and divided by one hundred, rounded half-up to whole cents per line. Per-line rounding can drift from the basis, so the residual — `source_benefit_cents` minus the sum of the rounded line amounts, which may be negative — is folded into the `HOUSING` line when the plan has one, and otherwise into the first line in the canonical category order `HOUSING`, `FOOD`, `CLOTHING`, `PERSONAL`, `MEDICAL`, `EDUCATION`, `SAVINGS`. The result is stored as `allocated_lines`, and the invariant holds at all times: the per-line amounts always sum to `total_planned_cents`, which always equals `source_benefit_cents`.

A draft plan moves `DRAFT` → `PROPOSED` when its case manager proposes it, and `PROPOSED` → `APPROVED` when a `FinancialOfficer` approves it. Approval enforces segregation of duties: the approver's `X-User-ID` must differ from the plan's `created_by_user_id`, and a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. When an approved plan needs rework, revision moves it `APPROVED` → `DRAFT`; the revision loop reverts only the status — the previously computed `allocated_lines` persist untouched. Rebalancing is the one edit allowed on a live plan: in either `DRAFT` or `APPROVED`, a case manager may move `amount_cents` from one allocated line named `from_category` to another named `to_category`, decreasing the source line and increasing the destination line by the same amount so `total_planned_cents` is conserved, and advancing the plan's `version` by one. The moved `amount_cents` must be positive, `from_category` and `to_category` must differ and must each name a line present in `allocated_lines`, and the source line's amount must be at least the moved amount; any violation fails with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.5. Conservators and the Disbursement Approval Pipeline

Some beneficiaries have a court-appointed conservator whose signature must accompany spending. A `FiduciaryAdmin` maintains the conservator registry: each record carries the coordinated `client_id`, the conservator's `full_name`, a `court_case_number` that must be unique across the registry (duplicates fail with `ERR_DUPLICATE_UNIQUE_FIELD`), an `authority_scope`, and the `appointed_date`. Scope semantics govern co-approval: `EXCLUSIVE` requires conservator co-approval on every disbursement for that client, `SHARED` requires it only when the disbursement's `amount_cents` is at least 50,000 cents ($500.00), and `ADVISORY` never requires it. A conservator is `ACTIVE` from registration; an administrator may suspend one (`ACTIVE` → `SUSPENDED`) or discharge one (`ACTIVE` → `DISCHARGED` or `SUSPENDED` → `DISCHARGED`). Suspension leaves the client's `PENDING_CONSERVATOR` disbursements in place but un-co-approvable while the conservator is not `ACTIVE`; discharge is terminal for those disbursements — every one of the client's `PENDING_CONSERVATOR` disbursements moves to `REJECTED` because the co-signing authority is gone.

Spending begins when a `CaseManager` requests a disbursement, naming the paying `client_id`, the source `account_id`, the `budget_plan_id` the spend counts against, the `payee_name`, a `category` from the budget vocabulary, a positive `amount_cents`, and the `scheduled_release_date` the payment is planned for — the date by which accrual-basis reports bucket the spend. Two optional references ride along: `court_order_id`, which is required exactly when the source account is `RESTRICTED` (its absence there fails creation with `ERR_COURT_ORDER_REQUIRED`), and `spend_down_plan_id`, which links the spend to a Medicaid spend-down plan. Creation enforces its checks in a fixed order: the client-activity gate first (a `TERMINATED` client fails with `ERR_CLIENT_NOT_ACTIVE`), then the restricted-account court-order requirement, then the dedicated-account category rule (a `DEDICATED` source account may fund only `MEDICAL` and `EDUCATION` categories, otherwise `ERR_DEDICATED_ACCOUNT_RESTRICTED`), and finally foreign-key coherence — the account, the budget plan, the court order when present, and the spend-down plan when present must all belong to the named client, or creation fails with `ERR_BUDGET_PLAN_MISMATCH`. A created disbursement records `requested_by_user_id` from the requester and sits in `REQUESTED`, with `fee_cents` at zero until release.

Approval is where duties divide. A `FinancialOfficer` approves a `REQUESTED` disbursement, and segregation of duties forbids the approver's `X-User-ID` from equaling `requested_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`. When no co-approval is required, approval moves the disbursement `REQUESTED` → `APPROVED` and stamps `approved_by_user_id`. When an `ACTIVE` conservator of the client has `EXCLUSIVE` scope, or `SHARED` scope with the amount at or above the 50,000-cent threshold, the same approval instead routes the disbursement `REQUESTED` → `PENDING_CONSERVATOR`, still stamping `approved_by_user_id`. Co-approval is then performed by a `ConservatorOfficer` whose `X-User-ID` is the `id` of an `ACTIVE` conservator of that client — anything else fails with `ERR_CONSERVATOR_NOT_ACTIVE` — moving the disbursement `PENDING_CONSERVATOR` → `APPROVED` and stamping `co_approved_by_conservator_id`. A `FinancialOfficer` may also reject a disbursement outright from `REQUESTED` or `PENDING_CONSERVATOR`, moving it to `REJECTED`.

### 3.6. Releasing Funds: Gates, Fiduciary Fees, and Returns

Release is the most heavily guarded transition in the system, moving a disbursement `APPROVED` → `RELEASED` and actually moving money. Its gates evaluate in a fixed order. First, for a `RESTRICTED` source account, the named court order must be grantable: the `court_order_id` must be present, the order must be `GRANTED`, it must belong to the disbursement's client, its `order_type` must be `RESTRICTED_WITHDRAWAL`, and the logical clock date must be on or before its `expiry_date` — any failure is `ERR_COURT_ORDER_NOT_GRANTABLE`. Second, the disbursement's `amount_cents` must not exceed the order's `amount_limit_cents`, failing with `ERR_COURT_ORDER_EXCEEDED`. Third, a `DEDICATED` source account again permits only `MEDICAL` and `EDUCATION` categories at release, failing with `ERR_DEDICATED_ACCOUNT_RESTRICTED`. Fourth, the referenced plan's `period_month` must equal the calendar month of the current logical clock date, failing with `ERR_PLAN_PERIOD_MISMATCH`. Fifth, that plan must be `APPROVED`, failing with `ERR_PLAN_NOT_APPROVED`. Sixth, the account's `balance_cents` must be at least `amount_cents`, failing with `ERR_INSUFFICIENT_FUNDS`. Seventh, the spend must fit the category's remaining allocation: `amount_cents` must not exceed the category's `allocated_lines` amount minus the sum of `amount_cents` over already-`RELEASED` and not-yet-`RETURNED` disbursements sharing the same `budget_plan_id` and `category`, failing with `ERR_BUDGET_CATEGORY_EXCEEDED` — a category absent from the plan's `allocated_lines` has a remaining allocation of zero. Last, an `ACTIVE` surety bond must exist, failing with `ERR_NO_ACTIVE_BOND`. After all eight gates, the source account must be `OPEN` at the moment of release, failing with `ERR_ACCOUNT_NOT_OPEN`.

A successful release stamps `released_at` from the logical clock, appends a `DISBURSEMENT_RELEASED` ledger entry debiting `amount_cents` with the disbursement's id as its `reference_id`, recomputes the account balance and the client's fund rollups, and computes the fiduciary fee into `fee_cents`. When the source account is `RESTRICTED`, release also consumes the court order: the order moves `GRANTED` → `EXECUTED` and records the releasing disbursement's id in `executed_disbursement_id`.

The fee is a marginal, tiered charge positioned by the client's month-to-date released volume immediately before this release. The prior volume is the sum of `amount_cents` over all of the client's disbursements whose status is `RELEASED` or `RETURNED` and whose `released_at` falls in the same calendar month as this release's clock month; because the disbursement being released is not yet `RELEASED` at evaluation time, it is excluded from its own prior volume by construction. The new volume interval runs from that prior volume up to the prior volume plus this disbursement's `amount_cents`. The first tier charges the portion of that interval lying at or below 100,000 cents ($1,000.00) at five percent; the second tier charges the portion lying above 100,000 cents and at or below 300,000 cents ($3,000.00) — a span of 200,000 cents — at three percent; the third tier charges the portion above 300,000 cents at one and a half percent. The raw fee is the sum of the three tier charges, rounded half-up to whole cents exactly once, at release. A monthly cap then applies: the fee charged is the smaller of the rounded raw fee and the remaining headroom under a 20,000-cent ($200.00) monthly cap, where headroom is the cap minus the sum of `fee_cents` already charged on the client's releases in the same clock month, floored at zero. The month-to-date fee total is therefore the sum of individually rounded per-release fees; the tiered fee is never computed on aggregated monthly volume and rounded afterwards.

When a released payment comes back — a returned check, a refused transfer — returning it moves the disbursement `RELEASED` → `RETURNED`, stamps `returned_at`, appends a compensating `DISBURSEMENT_RETURNED` ledger entry crediting the original `amount_cents`, and recomputes the account balance and client rollups. The fee is not reversed on a return: `fee_cents` remains as charged at release, and the compensating entry credits only the original `amount_cents`. The disbursement's `version` advances on both release and return.

### 3.7. Court Orders, Surety Bonds, and Clock-Driven Expiry

Court orders begin as petitions. A `FiduciaryAdmin` petitions an order with the subject `client_id`, an `order_type` of `RESTRICTED_WITHDRAWAL`, `REPORT_EXTENSION`, or `BOND_RELIEF`, the `petitioned_date`, and an `expiry_date` after which the order is unusable. An optional `amount_limit_cents` — positive when supplied, null when omitted — records the maximum withdrawable under the order; it has effect only on `RESTRICTED_WITHDRAWAL` orders (enforced at release, §3.6) and is stored, unused, on the other two types. A petitioned order sits in `PETITIONED` until an administrator grants it, moving it `PETITIONED` → `GRANTED` and stamping `granted_date` with the logical clock date. From there the order has two exits, both already introduced: consumption by a restricted release (`GRANTED` → `EXECUTED`, §3.6), and clock-driven expiry. Advancing the logical clock past an order's `expiry_date` moves it to `EXPIRED` whether it is still `PETITIONED` or already `GRANTED`.

Surety bonds insure the organization against misuse up to a coverage ceiling. Registration records a positive `coverage_amount_cents`, a half-open coverage window from `coverage_start_date` to `coverage_end_date` (the end must fall after the start), and the `premium_paid_through_date` through which premiums are paid; a new bond is `PENDING`. Activation moves it `PENDING` → `ACTIVE` and enforces single coverage: the activating bond's half-open window must not overlap the window of any other `ACTIVE` bond — adjacency is allowed, and `PENDING` bonds never block activation — with conflicts rejected as `ERR_BOND_WINDOW_CONFLICT`. Two figures are always derivable on a bond: `funds_under_management_cents`, the sum of `balance_cents` over every trust account organization-wide in `OPEN` or `FROZEN` status (`CLOSED` accounts are excluded), recomputed on every balance-affecting mutation; and `utilization_bps`, the floor of `funds_under_management_cents` multiplied by ten thousand and divided by `coverage_amount_cents`, where ten thousand basis points marks full utilization. Bonds lapse by the clock: advancing the logical clock to a date on or after `coverage_end_date`, or to any date after `premium_paid_through_date`, moves an `ACTIVE` bond to `LAPSED`.

Both expirations and the lapse are evaluated when the logical clock advances (§2.4) — the admin-only clock-setting capability is the single driver of time in this system, and its default starting reading is exactly 2026-05-01T00:00:00Z.

### 3.8. Periodic Accounting: SSA-6233 and Court Annual Reports

Twice a year at minimum, the organization owes accountings: the SSA-6233 payee accounting and the court's annual accounting. A `CaseManager` drafts a report with the subject `client_id`, a `report_type` of `SSA_6233` or `COURT_ANNUAL`, a closed reporting interval from `period_start_date` through `period_end_date` inclusive (the end must not precede the start), and a `basis` of `CASH` or `ACCRUAL` that selects the totals variant computed at submission. The statutory `due_date` is derived immediately: thirty days after `period_end_date`. Reports for the same client and report type form a contiguous chain over those in `SUBMITTED` or `ACCEPTED` status: a new report's `period_start_date` must be exactly the day after the previous report's `period_end_date`. A period that collides with an existing submitted or accepted report is rejected with `ERR_REPORT_PERIOD_OVERLAP`; a non-overlapping period that starts on any day other than that required next day — whether starting later, leaving a gap, or starting earlier, preceding the chain — is rejected with `ERR_REPORT_PERIOD_GAP`. A drafted report sits in `DRAFTING` with its four totals still null.

Submission is a `FinancialOfficer` action moving the report `DRAFTING` → `SUBMITTED`, and it carries two gates: the client must be `ACTIVE` or `SUSPENDED` (otherwise `ERR_CLIENT_NOT_ACTIVE`), and the current logical clock date must be on or before the `due_date` (otherwise `ERR_REPORT_OVERDUE`). Submission computes and freezes the four totals. The `opening_balance_cents`, identical under both bases, replays the ledger entries of every account of the client with `created_at` before `period_start_date` in chronological order and sums their signed amounts. Under the `CASH` basis — the SSA-6233 filing view — `receipts_total_cents` sums the amounts of the client's deposits in `POSTED` status whose `posted_at` date falls within the closed period, and `disbursements_total_cents` sums the amounts of the client's disbursements in `RELEASED` status whose `released_at` date falls within the period. Under the `ACCRUAL` basis — the court annual view — receipts are instead bucketed by `received_date`: deposits in `RECEIVED` or `POSTED` status count when their `received_date` falls within the period (a posted deposit's `posted_at` is not consulted under this basis), and disbursements additionally include disbursements still in `APPROVED` status whose `scheduled_release_date` falls within the period. Returned flows never appear: `RETURNED` deposits and `RETURNED` disbursements are excluded from both bases, since they net to zero through the ledger while the report shows gross flows. The `ending_balance_cents` is the opening balance plus receipts minus disbursements, and `submitted_at` stamps the logical clock.

Adjudication belongs to the `ComplianceAuditor`: acceptance moves a submitted report `SUBMITTED` → `ACCEPTED`, and rejection moves it `SUBMITTED` → `REJECTED`. A rejected report stops counting toward period contiguity — the chain is repaired by drafting a replacement report for the same period, supersede-by-recreate.

### 3.9. Medicaid Spend-Down, Audits, and the Misuse Cascade

A Medicaid-enrolled client whose countable resources exceed the ceiling must spend the excess down or lose eligibility. A `CaseManager` creates a spend-down plan — permitted only for clients with `medicaid_enrolled` true (an attempt for a non-enrolled client fails with `ERR_INVALID_REQUEST`, HTTP 400), and requiring the client to be in any status other than `TERMINATED`, failing with `ERR_CLIENT_NOT_ACTIVE` — naming the `client_id`, a `target_month` in year-month (`YYYY-MM`) form, and `entries` pairing a category with a positive `planned_amount_cents`; the spend-down category vocabulary excludes `SAVINGS`, running `HOUSING`, `FOOD`, `CLOTHING`, `PERSONAL`, `MEDICAL`, `EDUCATION`, and categories must not repeat within `entries`. At creation the plan computes its provisional excess: the client's current `countable_resources_cents`, plus the expected inflow — the sum of `monthly_benefit_cents` over the client's `VERIFIED` entitlements whose half-open effective window covers at least one day of `target_month`, where a null `effective_end_date` covers every month from the start onward — minus `medicaid_resource_limit_cents`, floored at zero, stored as `provisional_excess_cents`. Deposit posting can draft the same plan automatically through the resource cascade of §3.3, in which case `auto_created` reads true. Plans live in `DRAFT`.

Activation moves a plan `DRAFT` → `ACTIVE` and requires genuine necessity: a plan whose `provisional_excess_cents` is zero is not activatable and fails with `ERR_SPEND_DOWN_NOT_REQUIRED`. Finalization, allowed once the logical clock's month has reached the `target_month` — an earlier clock month fails with `ERR_INVALID_STATE` (HTTP 409) — computes the final excess — the client's actual `countable_resources_cents` at finalize time minus the resource limit, floored at zero, with no expected-inflow term — into `final_excess_cents` and routes the plan by its value: a final excess of exactly zero moves the plan `ACTIVE` → `MET`, while a positive final excess moves it `ACTIVE` → `LAPSED`. The provisional and final figures legitimately disagree for the same plan, because inflows and outflows land between creation and finalization. Client termination lapses any plan in `DRAFT` or `ACTIVE` (§3.1).

Oversight closes the loop. A `ComplianceAuditor` opens an audit case with the audited `client_id`, an `authority` of `SSA`, `STATE_COURT`, or `BONDING_COMPANY`, a `scope` of `CLIENT_ACCOUNT` or `ORG_WIDE`, and the audit window from `period_start_date` to `period_end_date` (the end must not precede the start). The case opens in `OPENED`; issuing findings moves it `OPENED` → `FINDINGS_ISSUED` and records the declared `misuse_amount_cents` (zero for clean findings, never negative) and `findings_count` (never negative). Closing a findings-issued case forks on the misuse amount: with `misuse_amount_cents` equal to zero the case moves `FINDINGS_ISSUED` → `CLOSED_NO_ACTION`; with any positive misuse amount it moves `FINDINGS_ISSUED` → `MISUSE_CONFIRMED`, and that confirmation fires the misuse cascade in three links — the client moves `ACTIVE` → `SUSPENDED`, every `OPEN` account of the client freezes to `FROZEN`, and each frozen account rejects its pending disbursements in `REQUESTED`, `PENDING_CONSERVATOR`, and `APPROVED` to `REJECTED`. If the client is not `ACTIVE` at confirmation time, the case still closes as `MISUSE_CONFIRMED`, but the cascade leaves the client, its accounts, and its disbursements untouched.

## 4. Endpoint Definitions

All endpoints live under the API root. Creating a new resource returns HTTP 201 with the created resource; reads, lifecycle actions, and mutations of existing resources return HTTP 200 with the affected resource. Request payloads, gate conditions, and side effects for each endpoint are specified in the workflows of §3; the table below is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /clients | Create a client in `INTAKE_REVIEW` | FiduciaryAdmin |
| GET | /clients | List clients with filters | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /clients/{id} | Get one client including computed fund and resource rollups | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /clients/{id}/activate | Activate a client; requires a verified entitlement; unfreezes accounts | FiduciaryAdmin |
| POST | /clients/{id}/suspend | Suspend a client; freezes accounts and rejects pending disbursements | FiduciaryAdmin |
| POST | /clients/{id}/terminate | Terminate a client with the full lifecycle cascade | FiduciaryAdmin |
| POST | /benefit-entitlements | Register an entitlement in `PENDING_VERIFICATION` with overlap check | FiduciaryAdmin |
| GET | /benefit-entitlements | List entitlements | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /benefit-entitlements/{id} | Get one entitlement | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /benefit-entitlements/{id}/verify | Verify an entitlement, stamping `verified_at` | FiduciaryAdmin |
| POST | /benefit-entitlements/{id}/terminate | Terminate a verified entitlement | FiduciaryAdmin |
| POST | /trust-accounts | Open an `OPERATING`, `RESTRICTED`, or `DEDICATED` account | FinancialOfficer |
| GET | /trust-accounts | List accounts | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /trust-accounts/{id} | Get one account including computed `balance_cents` | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /trust-accounts/{id}/close | Close a zero-balance account with no pending disbursements | FinancialOfficer |
| GET | /trust-accounts/{id}/ledger | Read the account's append-only ledger chronologically | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /budget-plans | Create a draft plan, superseding any prior plan for the same client and month; OCC-guarded | CaseManager |
| GET | /budget-plans | List budget plans | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /budget-plans/{id} | Get one plan including computed `allocated_lines` and `total_planned_cents` | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /budget-plans/{id}/propose | Move a draft plan to `PROPOSED` | CaseManager |
| POST | /budget-plans/{id}/approve | Approve a proposed plan under segregation of duties | FinancialOfficer |
| POST | /budget-plans/{id}/revise | Return an approved plan to `DRAFT` for rework | CaseManager |
| POST | /budget-plans/{id}/rebalance | Move an amount between two allocated lines, conserving the total | CaseManager |
| POST | /disbursements | Request a payment; restricted accounts require a court order at creation | CaseManager |
| GET | /disbursements | List disbursements | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /disbursements/{id} | Get one disbursement including computed `fee_cents` | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /disbursements/{id}/approve | Approve a request, routing to conservator co-approval when required | FinancialOfficer |
| POST | /disbursements/{id}/co-approve | Co-approve as the client's active conservator | ConservatorOfficer |
| POST | /disbursements/{id}/reject | Reject a requested or conservator-pending disbursement | FinancialOfficer |
| POST | /disbursements/{id}/release | Release an approved disbursement through all funding gates; writes the ledger and the fee | FinancialOfficer |
| POST | /disbursements/{id}/return | Return a released disbursement with a compensating ledger credit | FinancialOfficer |
| POST | /deposits | Record inbound funds in `RECEIVED` | FinancialOfficer |
| GET | /deposits | List deposits | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /deposits/{id} | Get one deposit | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /deposits/{id}/post | Post a received deposit through the bond-coverage gate and resource cascade | FinancialOfficer |
| POST | /deposits/{id}/return | Return a posted deposit with a compensating ledger debit | FinancialOfficer |
| POST | /court-orders | Petition a court order | FiduciaryAdmin |
| GET | /court-orders | List court orders | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /court-orders/{id} | Get one court order | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /court-orders/{id}/grant | Grant a petitioned order, stamping `granted_date` | FiduciaryAdmin |
| POST | /surety-bonds | Register a surety bond in `PENDING` | FiduciaryAdmin |
| GET | /surety-bonds | List bonds including computed funds under management and utilization | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /surety-bonds/{id} | Get one bond with computed utilization | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /surety-bonds/{id}/activate | Activate a bond; no overlapping active coverage window | FiduciaryAdmin |
| POST | /accounting-reports | Draft a report under the contiguity chain for its client and type | CaseManager |
| GET | /accounting-reports | List reports | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /accounting-reports/{id} | Get one report | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /accounting-reports/{id}/submit | Submit a draft report, computing totals per its basis | FinancialOfficer |
| POST | /accounting-reports/{id}/accept | Accept a submitted report | ComplianceAuditor |
| POST | /accounting-reports/{id}/reject | Reject a submitted report, removing it from the contiguity chain | ComplianceAuditor |
| POST | /spend-down-plans | Create a Medicaid spend-down plan in `DRAFT` | CaseManager |
| GET | /spend-down-plans | List spend-down plans | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /spend-down-plans/{id} | Get one spend-down plan | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /spend-down-plans/{id}/activate | Activate a draft plan with a positive provisional excess | CaseManager |
| POST | /spend-down-plans/{id}/finalize | Finalize an active plan to `MET` or `LAPSED` by its final excess | CaseManager |
| POST | /audit-cases | Open an audit case | ComplianceAuditor |
| GET | /audit-cases | List audit cases | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /audit-cases/{id} | Get one audit case | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /audit-cases/{id}/issue-findings | Issue findings, recording misuse amount and findings count | ComplianceAuditor |
| POST | /audit-cases/{id}/close | Close a findings-issued case, firing the misuse cascade when misuse is positive | ComplianceAuditor |
| POST | /conservators | Register a court conservator in `ACTIVE` | FiduciaryAdmin |
| GET | /conservators | List conservators | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| GET | /conservators/{id} | Get one conservator | FiduciaryAdmin, CaseManager, FinancialOfficer, ConservatorOfficer, ComplianceAuditor |
| POST | /conservators/{id}/suspend | Suspend an active conservator | FiduciaryAdmin |
| POST | /conservators/{id}/discharge | Discharge a conservator, rejecting the client's conservator-pending disbursements | FiduciaryAdmin |
| POST | /_clock/set_current_utc | Set the logical clock, evaluating order expiry and bond lapse | FiduciaryAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with their workflows in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CLIENT_NOT_FOUND | 404 |
| ERR_ENTITLEMENT_NOT_FOUND | 404 |
| ERR_ACCOUNT_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_DISBURSEMENT_NOT_FOUND | 404 |
| ERR_DEPOSIT_NOT_FOUND | 404 |
| ERR_COURT_ORDER_NOT_FOUND | 404 |
| ERR_BOND_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_SPEND_DOWN_NOT_FOUND | 404 |
| ERR_AUDIT_NOT_FOUND | 404 |
| ERR_CONSERVATOR_NOT_FOUND | 404 |
| ERR_NOT_FOUND | 404 |
| ERR_METHOD_NOT_ALLOWED | 405 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_CLIENT_NOT_ACTIVE | 409 |
| ERR_NO_VERIFIED_ENTITLEMENT | 409 |
| ERR_ACCOUNT_NOT_OPEN | 409 |
| ERR_COURT_ORDER_REQUIRED | 422 |
| ERR_COURT_ORDER_NOT_GRANTABLE | 422 |
| ERR_COURT_ORDER_EXCEEDED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CONSERVATOR_NOT_ACTIVE | 422 |
| ERR_DEDICATED_ACCOUNT_RESTRICTED | 422 |
| ERR_ENTITLEMENT_OVERLAP | 409 |
| ERR_REPORT_PERIOD_OVERLAP | 409 |
| ERR_REPORT_PERIOD_GAP | 409 |
| ERR_REPORT_OVERDUE | 422 |
| ERR_BOND_WINDOW_CONFLICT | 409 |
| ERR_PLAN_PERIOD_MISMATCH | 422 |
| ERR_BUDGET_PLAN_MISMATCH | 422 |
| ERR_PLAN_NOT_APPROVED | 409 |
| ERR_ENTITLEMENT_ACCOUNT_MISMATCH | 422 |
| ERR_INSUFFICIENT_FUNDS | 422 |
| ERR_BUDGET_CATEGORY_EXCEEDED | 422 |
| ERR_BOND_COVERAGE_EXCEEDED | 422 |
| ERR_ACCOUNT_NOT_ZERO | 422 |
| ERR_PENDING_DISBURSEMENTS | 422 |
| ERR_SPEND_DOWN_NOT_REQUIRED | 422 |
| ERR_NO_ACTIVE_BOND | 409 |
| ERR_DUPLICATE_UNIQUE_FIELD | 409 |
| ERR_STALE_VERSION | 412 |
