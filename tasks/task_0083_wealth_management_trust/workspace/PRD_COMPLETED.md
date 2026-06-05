# Wealth Management & Trust Accounting API — Product Requirements Document

## 1. Introduction

This document specifies the Wealth Management & Trust Accounting API, a fiduciary back-office platform that models the full lifecycle of revocable and irrevocable trusts — from drafting and funding, through day-to-day income and principal accounting, beneficiary distributions, annual tax filing, and ultimate termination. The platform is, at its heart, a double-ledger reconciliation engine: every dollar that enters or leaves a trust is classified as either income or principal corpus, and a large body of fiduciary law dictates how that classification flows through to distributable net income, beneficiary K-1 statements, trust income tax, and the generation-skipping transfer (GST) tax.

The system serves four kinds of actors. A fiduciary back-office operator administers the structural and tax machinery — registering parties, opening accounting periods, filing returns, allocating GST exemption, and reversing erroneous payments. The settlor (grantor) who created a trust may amend or revoke it, but only within the bounds of the trust instrument. Appointed trustees manage the trust day-to-day, posting ledger entries and shepherding distributions through a proposal-and-approval workflow that enforces segregation of duties. Beneficiaries have read-only visibility into their own tax statements. Because trust accounting is unforgiving of arithmetic drift, the platform recomputes every derived figure — balances, distributable net income, carry-out, K-1 character lines, inclusion ratios — atomically within the request that triggers the change, so that a response never reflects a half-applied mutation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `TrustAdmin`, `Grantor`, `Trustee`, and `Beneficiary`. A request missing either header, or carrying an `X-User-Role` that is not one of these four, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not permitted to perform the requested operation (per the authorization column of the endpoint table in §4) is rejected with `ERR_FORBIDDEN_ROLE`.

Three of the four roles are tied to a persisted entity, and their `X-User-ID` is interpreted as that entity's `id`. When `X-User-Role` is `Grantor`, `X-User-ID` is the `id` of the acting `Grantor`; any operation scoped to a trust verifies that the trust's `grantor_id` equals `X-User-ID`. When `X-User-Role` is `Trustee`, `X-User-ID` is the `id` of the acting `Trustee`; every trust-scoped operation a trustee performs — fetching the trust, reading or opening its accounting periods, posting and listing receipts and disbursements, and proposing, approving, paying, listing, or fetching distributions, as well as reading the period's K-1 statements — requires that this trustee hold an `ACTIVE` appointment over the owning trust, and a trustee lacking such an appointment is rejected with `ERR_NOT_OWNER`. Reading a trustee record or a trustee appointment is not so scoped: any `Trustee` may fetch any `/trustees/{id}` or `/trustee-appointments/{id}`. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; a beneficiary may read only a K-1 whose `beneficiary_id` equals `X-User-ID`, and may read only their own beneficiary record. When a beneficiary lists K-1s, the listing is implicitly scoped to their own `beneficiary_id` regardless of any filter supplied; a `beneficiary_id` query filter naming a different beneficiary is rejected with `ERR_NOT_OWNER`. In all three cases, when the entity-backed actor's `X-User-ID` does not match the owning entity the resource references, the request is rejected with `ERR_NOT_OWNER`. The fourth role, `TrustAdmin`, is an opaque fiduciary back-office identifier not tied to any persisted entity: the server accepts and may log it, but never compares it against any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100 rather than rejected, and the clamped value is the `limit` echoed in `meta`. `offset` is the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_VALIDATION`. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties and Versioning

Every entity in this system carries the standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation, while `updated_at` advances on every mutation. The `version` is an integer that begins at 1 and increments by exactly one on every mutation of the resource, including mutations to its computed/derived fields. All entities in this domain carry the full quartet — `id`, `created_at`, `updated_at`, and `version` — there are no creation-only resources that omit `updated_at` or `version`.

A recurring theme of this platform is that derived figures are recomputed and persisted whenever an underlying ledger fact changes. When such a recomputation lands on an entity — for example, when a posted receipt changes a trust's `principal_balance_cents`, or when a distribution payment refreshes an account's `dni_carried_out_cents` — that entity's `updated_at` is refreshed and its `version` is incremented, exactly as any other mutation would do.

### 2.5. Hierarchical Consistency and Cascading Reconciliation

The trust is the aggregate root. Beneath it sit accounting periods, and beneath each period sit its receipts, disbursements, and distributions; trustee appointments and GST exemption allocations hang directly off the trust. When a parent transition renders children non-operational — for instance, revoking or beginning to terminate a trust — the platform closes every accounting period still in `OPEN` status on that trust as part of the same operation, rather than waiting for an explicit request on each child period. Conversely, when a child fact changes a parent's derived state — a posted receipt, a paid distribution — the parent's balances and the affected period's distributable figures are recomputed in the same request. These cascades are described in full within the workflow narratives of §3; the governing rule here is that no cascade is deferred: every secondary mutation it implies lands atomically, refreshing each touched entity's `updated_at` and `version`.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many paths nest one resource within another (for example, an accounting period beneath a trust, or a ledger entry beneath a period). Existence is validated left to right: the outermost path segment is resolved first, and the request fails with `ERR_NOT_FOUND` against the first path segment that does not resolve to an existing resource, before any inner segment or body is considered. The same `ERR_NOT_FOUND` governs foreign-key references supplied in a request body — a body naming a non-existent grantor, trustee, beneficiary, account, or distribution is rejected on the same grounds. This existence pass runs after authentication and role authorization but before any business-rule evaluation.

### 2.7. The Income-and-Principal Ledger Principle

This is a two-ledger system. Every trust maintains a running **principal corpus** in `principal_balance_cents` and a running **undistributed income** balance in `income_balance_cents`, both expressed in whole cents. The principal balance is the sum of every principal-side receipt minus every principal-side disbursement minus the principal-funded portion of every paid distribution, taken across all of the trust's accounting periods. The income balance is, in parallel, the sum of every income-side receipt minus every income-side disbursement minus the income-funded portion of every paid distribution, again across all periods. Both balances are recomputed on every ledger mutation. Which sub-ledger a given entry touches is never supplied by the client; it is computed and recorded in the entry's `ledger_side` field, and the rules that decide it are described in §3.

### 2.8. Precision, Rounding, and Derived-Figure Reconciliation

All monetary quantities are stored and computed as whole cents using integer arithmetic; balances, distributable net income, carried-out amounts, and taxable income never carry a fractional cent. Where a calculation multiplies a cent amount by a rate or a fraction — trust income tax, GST tax, and the K-1 character allocation — the result is rounded half up to the nearest whole cent. The inclusion ratio is the one non-cent figure: it is a number carried to six decimal places. When a multi-beneficiary allocation rounds each beneficiary's share independently, the small residual that rounding leaves over is reconciled deterministically rather than discarded; the precise reconciliation rule lives with the K-1 narrative in §3.

### 2.9. Optimistic Concurrency on GST Exemption Allocation

Allocating GST exemption to a trust is the one write in this system guarded by optimistic concurrency control. A request to allocate exemption to a trust must include `expected_trust_version` as a required field, carrying the `version` of the trust that the client last observed. The server compares it against the trust's current `version`. If they differ — because some other writer has advanced the trust's version since the client read it, for example by posting an earlier allocation that consumed part of the shared grantor exemption pool — the allocation is rejected with `ERR_STALE_TRUST_VERSION` (HTTP 412), and the client must re-read the trust and re-derive its allocation against the fresh exemption-remaining figure before retrying. No other endpoint in this system takes a version field; only GST exemption allocation is version-checked.

### 2.10. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of path resources and body foreign keys (`ERR_NOT_FOUND`), then entity-backed ownership (`ERR_NOT_OWNER`), then whether the target is in a state that admits the transition (`ERR_INVALID_STATE`). Business-specific rules are evaluated only after those five gates pass. Among the business rules themselves the ordering, from earliest to latest, is: the irrevocable-trust bar (`ERR_TRUST_IRREVOCABLE`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), accounting-period overlap (`ERR_ACCOUNT_PERIOD_OVERLAP`), trustee-term conflict (`ERR_TRUSTEE_TERM_CONFLICT`), the frozen-period bar (`ERR_PERIOD_FROZEN`), amount validity (`ERR_INVALID_AMOUNT`), grantor consistency (`ERR_GRANTOR_MISMATCH`), corpus sufficiency (`ERR_INSUFFICIENT_CORPUS`), exemption-pool sufficiency (`ERR_GST_EXEMPTION_EXCEEDED`), and finally the GST-allocation stale-version check (`ERR_STALE_TRUST_VERSION`). Malformed request bodies — a missing required field, a wrong type, or an unrecognized enum value — are rejected with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Parties: Grantors, Trustees, and Beneficiaries

Before any trust exists, the back office registers the parties. A **grantor** (the settlor who creates trusts) is registered with a `full_name`; an optional `generation_level`, conventionally 0 for a grantor and defaulting to 0, persisted only for symmetry with the beneficiary's own generation tracking — the server does not force this field to 0 but stores whatever non-negative integer is supplied, rejecting only a negative value with `ERR_INVALID_AMOUNT`; and an optional `gst_exemption_total_cents`, the lifetime GST exemption pool the grantor brings, which must be zero or greater (a negative value is rejected with `ERR_INVALID_AMOUNT`) and, when omitted, defaults to the statutory lifetime amount the platform seeds, 1,399,000,000 cents. At creation the grantor's `gst_exemption_remaining_cents` is initialized equal to `gst_exemption_total_cents`; thereafter it is a computed figure equal to the total minus the sum, across all of that grantor's trusts, of the exemption currently allocated to each, and it is recomputed on every allocation and every release.

A **trustee** is registered with a `full_name` and an optional `is_corporate` flag — true for an institutional trustee, false (the default) for an individual. A **beneficiary** is registered with a `full_name`, a `grantor_id` naming the grantor against whom their generation is measured, and a `generation_level`, an integer that must be zero or greater giving the beneficiary's generation relative to that grantor (0 is the grantor's own generation, 1 the children, 2 the grandchildren, and so on); the named `grantor_id` must resolve to an existing grantor (`ERR_NOT_FOUND` otherwise), and a negative `generation_level` is rejected with `ERR_INVALID_AMOUNT` — the grantor-existence check is evaluated before the generation-level range check. From these the system computes `is_skip_person`: a beneficiary is a skip person — true — exactly when their `generation_level` minus the grantor's `generation_level` is at least 2. The skip-person flag is what later drives GST taxation of distributions and terminations. When listing beneficiaries the back office may filter by `grantor_id`.

### 3.2. Standing Up a Trust: Drafting, Funding, Activation, and Trustees

A trust is created in `DRAFT` status with a `name`, the settlor's `grantor_id`, and a `trust_type` of either `REVOCABLE` or `IRREVOCABLE`. Two governing-instrument elections may be set at creation, each defaulting to false: `is_grantor_trust`, the IRC subpart-E grantor-trust election under which the trust pays no income tax at the trust level and income character instead flows to the grantor; and `capital_gains_to_income`, which when true allocates realized capital gains to the income sub-ledger and when false (the default) leaves them in principal. On creation the trust's balances are zero, its `gst_exemption_allocated_cents` is 0, and its `version` is 1. Trusts may be listed and filtered by `grantor_id`.

A trust progresses through its early life under the back office. Funding moves it from `DRAFT` to `FUNDED`; it is permitted only while the trust is in `DRAFT` and only once at least one trustee appointment with `ACTIVE` status exists for the trust — a fund request against a trust that is not `DRAFT`, or one that has no `ACTIVE` trustee appointment, is rejected with `ERR_INVALID_STATE`. Activation then moves it from `FUNDED` to `ACTIVE`, permitted only while the trust is `FUNDED` and only once `principal_balance_cents` is greater than zero — that is, once an initial `CONTRIBUTION` receipt has posted; an activate request against a trust that is not `FUNDED`, or whose `principal_balance_cents` is not greater than zero, is likewise rejected with `ERR_INVALID_STATE`. Each of these transitions increments the trust's `version`.

Trustees are bound to a trust through a **trustee appointment**, the many-to-many junction between trust and trustee. The back office appoints a trustee by supplying the `trustee_id`, an inclusive `term_start`, and an inclusive `term_end` that must be strictly later than `term_start` (a `term_end` not strictly after `term_start` is rejected with `ERR_VALIDATION`); the appointment records the `trust_id` it governs and opens in `ACTIVE` status. `RESIGNED` is a defined appointment status but no endpoint in this API transitions an appointment into it, so an appointment created through this API remains `ACTIVE` for its lifetime. A new appointment must not conflict with an existing `ACTIVE` appointment for the **same** trust-and-trustee seat: the requested closed term interval `[term_start, term_end]` may neither overlap nor sit within 30 days of an existing active term for that same `(trust_id, trustee_id)` pair, the buffer being a mandatory gap between successive terms of one trustee on one trust. A conflict is rejected with `ERR_TRUSTEE_TERM_CONFLICT`. Distinct trustees may serve the same trust at the same time as co-trustees; the conflict is strictly per seat. Appointments on a trust may be listed, a single appointment may be fetched, and appointments may also be listed filtered by `trustee_id`.

### 3.3. Accounting Periods and the Ledger

All ledger activity happens inside an **accounting period** — a `TrustAccount` opened by the back office over a tax year. A period is created with a `tax_year`, an inclusive `period_start`, and an exclusive `period_end` that must be strictly later than `period_start` (a `period_end` not strictly after `period_start` is rejected with `ERR_VALIDATION`); the period therefore covers the half-open interval `[period_start, period_end)` and records the owning `trust_id`. A new period must not overlap any existing period on the same trust under half-open semantics, which means two periods that merely abut — where one period's `period_end` equals the next period's `period_start` — are allowed, while any true overlap is rejected with `ERR_ACCOUNT_PERIOD_OVERLAP`. A period opens in `OPEN` status and may later advance to `CLOSED` and then `FILED`; its `dni_cents`, `dni_carried_out_cents`, and `taxable_income_cents` all begin at 0 and are maintained as ledger facts change. Periods on a trust may be listed, and a single period fetched, exposing those computed figures.

Two kinds of ledger entries may be posted to an `OPEN` period. A **receipt** records money coming in: its `account_id`, an `amount_cents` greater than zero, and a `receipt_kind` of `INTEREST`, `DIVIDEND_ORDINARY`, `DIVIDEND_QUALIFIED`, `CAPITAL_GAIN`, or `CONTRIBUTION`. A **disbursement** records an expense paid out: its `account_id`, an `amount_cents` greater than zero, and an `expense_kind` of `TRUSTEE_FEE`, `INVESTMENT_FEE`, `TAX_PAYMENT`, or `ADMINISTRATIVE`. A disbursement also carries an `is_system_generated` flag, false for a trustee-entered expense and true only when the platform spawns the disbursement itself as a cascade (described in §3.6). Posting either entry to a period that is not `OPEN` — one that has been `CLOSED` or `FILED` and is therefore frozen against further entries — is rejected with `ERR_PERIOD_FROZEN`. An `amount_cents` of zero or less is rejected with `ERR_INVALID_AMOUNT`. Both receipts and disbursements may be listed per account.

The platform decides each entry's `ledger_side` rather than accepting it from the client. A `CONTRIBUTION` receipt always credits `PRINCIPAL`. A `CAPITAL_GAIN` receipt credits `INCOME` when the owning trust's `capital_gains_to_income` election is true and `PRINCIPAL` when it is false. Every other receipt kind — `INTEREST`, `DIVIDEND_ORDINARY`, `DIVIDEND_QUALIFIED` — credits `INCOME`. On the expense side, an `INVESTMENT_FEE` and a `TAX_PAYMENT` each debit `PRINCIPAL`, while a `TRUSTEE_FEE` and an `ADMINISTRATIVE` expense each debit `INCOME`. Posting an entry recomputes the trust's two balances and the period's distributable net income in the same request.

### 3.4. Distributable Net Income and Taxable Income

A period's **distributable net income** (`dni_cents`) measures the income available to carry out to beneficiaries. It is computed from the income sub-ledger only: take the sum of `amount_cents` over every receipt on the period whose computed `ledger_side` is `INCOME`, subtract the sum of `amount_cents` over every disbursement on the period whose `ledger_side` is `INCOME`, and floor the result at zero so it can never go negative. Because capital-gain receipts land in income only under the `capital_gains_to_income` election, the very same set of receipts produces a larger distributable net income — and a different K-1 capital-gain line — for a trust that has made that election than for one that has not. Distributable net income is recomputed whenever a receipt or disbursement is posted to an `OPEN` period, when the period is closed, and when an amendment commit changes the `capital_gains_to_income` election.

A period's **taxable income** (`taxable_income_cents`) is what the trust itself is taxed on. It equals the period's `dni_cents`, minus the amount of distributable net income carried out to beneficiaries (`dni_carried_out_cents`, described next), plus retained capital gains — the sum of `amount_cents` over every receipt on the period whose `ledger_side` is `PRINCIPAL` and whose `receipt_kind` is `CAPITAL_GAIN` — with the whole figure floored at zero. In words: income that flows out to beneficiaries is taxed to them and removed from the trust's burden, while capital gains retained in principal remain taxable at the trust unless the election pushed them into income and they were distributed out. Taxable income is recomputed when a period closes and whenever a ledger entry on a closing-bound period changes, and it is snapshotted when the period is filed.

### 3.5. The Distribution Lifecycle: Propose, Approve, Pay, and the Carry-Out Cascade

A **distribution** moves money to a beneficiary and follows a branching lifecycle recorded in its `status` field: `PROPOSED`, then either `APPROVED` then `PAID` (with `REVERSED` available afterward) or `REJECTED`. A trustee proposes a distribution against an `OPEN` period by supplying the `account_id`, the recipient's `beneficiary_id`, an `amount_cents` greater than zero, a `distribution_kind` of either `MANDATORY` (required by the instrument) or `DISCRETIONARY` (at trustee discretion), and the `proposer_trustee_id` identifying the proposing trustee. A distribution is born in `PROPOSED` status. The proposed beneficiary must belong to the same grantor as the trust — the beneficiary's `grantor_id` must equal the trust's `grantor_id` — otherwise the proposal is rejected with `ERR_GRANTOR_MISMATCH`; and a proposal against a frozen period is rejected with `ERR_PERIOD_FROZEN`. Distributions may be fetched individually, listed per account (filterable by `beneficiary_id`), and listed globally filtered by `beneficiary_id`, `proposer_trustee_id`, or `approver_trustee_id`.

Approval moves a distribution from `PROPOSED` to `APPROVED` and is performed by a trustee other than the proposer. The platform enforces **segregation of duties**: the approving trustee, identified by `X-User-ID`, must not equal the distribution's `proposer_trustee_id`, and an attempt by the proposer to approve their own distribution is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval is permitted only while the distribution is `PROPOSED` and the owning period is `OPEN`; these are checked in order — a distribution not in `PROPOSED` status is rejected with `ERR_INVALID_STATE`, the segregation-of-duties bar (`ERR_SEGREGATION_OF_DUTIES`) is evaluated next, and a period not in `OPEN` status is rejected with `ERR_PERIOD_FROZEN` only after both — and approval records the approving trustee in `approver_trustee_id` and increments the distribution's `version`. Rejection is the alternative branch out of `PROPOSED`: a trustee rejects a still-`PROPOSED` distribution, moving it to the terminal `REJECTED` state and incrementing its `version`; rejection requires no `OPEN`-period check and a distribution not in `PROPOSED` status is rejected with `ERR_INVALID_STATE`.

Paying a distribution moves it from `APPROVED` to `PAID` and is the system's most consequential cascade. It is permitted only while the distribution is `APPROVED`, the owning period is `OPEN`, and the owning trust is in `ACTIVE` or `TERMINATING` status — a `TERMINATED` or `REVOKED` trust can never pay. These preconditions are checked in order: a distribution not in `APPROVED` status and a trust not in `ACTIVE`/`TERMINATING` status are each rejected with `ERR_INVALID_STATE` (the distribution-status check before the trust-status check), then a period not in `OPEN` status is rejected with `ERR_PERIOD_FROZEN`, and only then is corpus sufficiency evaluated. The payment must be funded from available corpus: the `amount_cents` must be no greater than the trust's `principal_balance_cents` plus its `income_balance_cents`, or the payment is rejected with `ERR_INSUFFICIENT_CORPUS`. On payment the platform funds the distribution income-first: `funded_from_income_cents` is set to the lesser of `amount_cents` and the trust's `income_balance_cents` at payment time, and `funded_from_principal_cents` is set to the remainder, `amount_cents` minus `funded_from_income_cents`. It then debits the income balance and the principal balance by those respective portions. That balance change cascades into a recomputation of the owning period's `dni_carried_out_cents` and a re-run of the carry-out allocation across every `PAID` distribution on the period (described in §3.6), which in turn cascades into recomputation of every affected beneficiary's K-1 character lines. Finally, if the recipient beneficiary is a skip person, the payment spawns a GST event of type `TAXABLE_DISTRIBUTION` for the full `amount_cents` (described in §3.8); the event's `inclusion_ratio_snapshot` is the trust's `inclusion_ratio` as recomputed after this payment's balance cascade (the post-payment value, not the value before the payment debited principal). The distribution's `version` is incremented.

A paid distribution may be **reversed** by the back office while the owning period is still `OPEN`, moving it from `PAID` to the terminal `REVERSED` state; a reverse attempt on a distribution not in `PAID` status is rejected with `ERR_INVALID_STATE`, and one whose owning period is not `OPEN` is rejected with `ERR_PERIOD_FROZEN` (the status check first). Reversal is the exact inverse of payment: it credits the trust's `income_balance_cents` by `funded_from_income_cents` and its `principal_balance_cents` by `funded_from_principal_cents`, then resets the reversed distribution's own `funded_from_income_cents`, `funded_from_principal_cents`, and `dni_carried_amount_cents` all to 0 so the recompute backs its amounts out, then recomputes the period's `dni_carried_out_cents` and re-runs the carry-out allocation over the remaining `PAID` distributions, then recomputes the affected beneficiaries' K-1 lines. If the payment had spawned a GST event, that event is deleted so the taxable transfer is undone. The distribution's `version` is incremented.

### 3.6. Carry-Out Allocation, K-1 Statements, and the Tax-Payment Cascade

The amount of distributable net income carried out of a period, `dni_carried_out_cents`, is allocated across the period's `PAID` distributions by a **tiered waterfall**. The distributions are ordered so that all `MANDATORY` distributions precede all `DISCRETIONARY` ones, and within each tier they are ordered by `created_at` ascending (never by `id`). A running pool starts at the period's `dni_cents`. Walking the ordered list, each distribution's `dni_carried_amount_cents` is set to the lesser of its `amount_cents` and the remaining pool, and that amount is then subtracted from the pool. After the walk, the period's `dni_carried_out_cents` equals `dni_cents` minus whatever remains in the pool. This allocation is re-run in full on every distribution payment and every reversal.

Each beneficiary receiving carried-out income gets an annual **K-1** statement scoped to a period (its `account_id`) and a `beneficiary_id`, breaking the carried-out income into character lines: `ordinary_income_cents`, `qualified_dividend_cents`, `capital_gain_cents`, and a `total_carried_cents` that is their sum. The character breakdown works from the period's income-ledger character pools. If the period's `dni_carried_out_cents` is zero, every K-1 line on the period is zero. Otherwise the platform forms three pools from the income sub-ledger: an ordinary pool equal to the sum of `amount_cents` over income-side receipts of kind `INTEREST` or `DIVIDEND_ORDINARY` minus the sum of `amount_cents` over all income-side disbursements; a qualified-dividend pool equal to the sum of income-side `DIVIDEND_QUALIFIED` receipts; and a capital-gain pool equal to the sum of income-side `CAPITAL_GAIN` receipts (nonzero only under the `capital_gains_to_income` election). Each pool is scaled down by the carried fraction — the period's `dni_carried_out_cents` divided by its `dni_cents` — and the scaled figure for each character is rounded half up to whole cents. Then, for each beneficiary, that beneficiary's share is their summed `dni_carried_amount_cents` divided by the period's total `dni_carried_out_cents`; each of the beneficiary's three character lines is the corresponding scaled character pool times that share, rounded half up. Rounding is performed per beneficiary line independently; any residual cent — the scaled character total minus the sum of the rounded per-beneficiary lines — is then added to the beneficiary holding the largest carried share, ties broken by earliest `created_at`. This pinned order differs deliberately from a sum-then-truncate pass, which would drop the residual cent. A K-1 row is created the first time a beneficiary has any carried amount on the period and is thereafter persisted; once it exists it is never deleted, so a beneficiary who subsequently stops carrying — for instance after the only distribution funding them is reversed — keeps their K-1 row with every character line, and `total_carried_cents`, recomputed to zero rather than removed. K-1 statements may be listed per account (filterable by `beneficiary_id`), fetched individually, and listed globally by `beneficiary_id`.

### 3.7. Closing the Books and Filing the Return

Closing a period, performed by the back office, moves it from `OPEN` to `CLOSED`. It is permitted only while the period is `OPEN` and the owning trust is in one of `ACTIVE`, `AMENDMENT_PENDING`, `TERMINATING`, or `REVOKED`; a close request against a period that is not `OPEN`, or whose owning trust is in none of those four statuses, is rejected with `ERR_INVALID_STATE` (the period-status check first). Closing freezes the ledger — no further receipt, disbursement, or distribution may be created on the period — recomputes the period's distributable net income and taxable income, and increments the period's `version`.

A **tax filing** (Form 1041) is created by the back office in `DRAFT` status against a `CLOSED` period, naming its `account_id` and optionally a `supersedes_filing_id` that references a prior `FILED` filing this one will amend (null for an original filing); when supplied, `supersedes_filing_id` must be a string naming an existing filing — a non-existent reference is rejected with `ERR_NOT_FOUND`, though the referenced filing's own status is not checked at creation time — and creation against a period that is not `CLOSED` is rejected with `ERR_INVALID_STATE`. Filing a draft moves it from `DRAFT` to `FILED`; it is permitted only while the filing is `DRAFT`, only while the owning period is `CLOSED` (an `OPEN` period cannot be filed), and only when no existing filing for that period is already `FILED` and not yet superseded — each of those three precondition failures is rejected with `ERR_INVALID_STATE`. Filing snapshots the period's taxable income into `taxable_income_snapshot_cents` and computes `tax_due_cents` (described in §3.9). It then cascades: the owning period advances from `CLOSED` to `FILED`; and when `tax_due_cents` is greater than zero, the platform spawns a system disbursement on the period — `expense_kind` `TAX_PAYMENT`, `is_system_generated` true, `ledger_side` `PRINCIPAL`, `amount_cents` equal to `tax_due_cents` — which debits the trust's `principal_balance_cents`. The filing's `version` is incremented. A filing may be fetched, filings may be listed per account, and filings may be listed globally filtered by `account_id` or by `supersedes_filing_id`.

A filed return may be reopened for correction. Amending moves a filing from `FILED` to `AMENDED` and increments its `version`; an amend attempt against a filing that is not `FILED` is rejected with `ERR_INVALID_STATE`. Refiling then moves it from `AMENDED` back to `FILED`: it marks the prior original filing named by `supersedes_filing_id` as `SUPERSEDED` (only when that field is non-null and still resolves to a filing), recomputes `tax_due_cents` from the filing's own stored `taxable_income_snapshot_cents` (the snapshot is not re-taken from the period on refile), and increments the filing's `version`; a refile attempt against a filing that is not `AMENDED` is rejected with `ERR_INVALID_STATE`. This amend-and-refile loop may repeat.

### 3.8. GST Exemption Allocation and Generation-Skipping Events

A grantor's lifetime GST exemption can be parceled out to individual trusts to shelter them from generation-skipping transfer tax. The back office allocates exemption to a trust by supplying the funding `grantor_id`, an `amount_cents` greater than zero, and the `expected_trust_version` carrying the trust's last-observed `version`. The allocation opens in `ALLOCATED` status. The funding grantor must be consistent with the trust — the allocation is trust-scoped, and a grantor inconsistent with the trust is rejected with `ERR_GRANTOR_MISMATCH`. On this endpoint the grantor-consistency check is evaluated before the amount-validity check, so a request that both names an inconsistent grantor and supplies a non-positive `amount_cents` returns `ERR_GRANTOR_MISMATCH` (not `ERR_INVALID_AMOUNT`); an `amount_cents` of zero or less that survives the grantor check is then rejected with `ERR_INVALID_AMOUNT`. The requested `amount_cents` must not exceed the grantor's `gst_exemption_remaining_cents`, or the pool would go negative and the request is rejected with `ERR_GST_EXEMPTION_EXCEEDED`. And the allocation is the system's one optimistic-concurrency write: if `expected_trust_version` does not equal the trust's current `version`, it is rejected with `ERR_STALE_TRUST_VERSION`. A successful allocation increases the trust's `gst_exemption_allocated_cents` by `amount_cents`, recomputes the trust's `inclusion_ratio` and the grantor's `gst_exemption_remaining_cents`, and increments the trust's `version`. Allocations may be listed per trust, fetched individually, and listed globally filtered by `grantor_id`.

An allocation may be **released** by the back office, the compensating inverse of allocating: it is permitted only while the allocation is `ALLOCATED` (a release of an allocation not in `ALLOCATED` status is rejected with `ERR_INVALID_STATE`, checked before the consumed check) and only when no GST event on the trust has already consumed this exemption — operationally, the exemption is treated as consumed whenever any GST event whatsoever exists on the owning trust (the check is not narrowed to events tied to this particular allocation), and a release attempted against such a trust is rejected with `ERR_ALLOCATION_CONSUMED`. The release path is nested under the trust; an `alloc_id` that exists but whose `trust_id` does not match the path trust is rejected with `ERR_NOT_FOUND`. Release moves the allocation to the terminal `RELEASED` state, decrements the trust's `gst_exemption_allocated_cents` by the released `amount_cents`, recomputes the trust's `inclusion_ratio` and the grantor's `gst_exemption_remaining_cents`, and increments the trust's `version`.

A trust's `inclusion_ratio` expresses how exposed it is to GST tax. It is one minus the quotient of `gst_exemption_allocated_cents` over `principal_balance_cents`, rounded to six decimal places and clamped to the range from 0 to 1; when `principal_balance_cents` is zero the ratio is defined to be 0. A **GST event** records a generation-skipping transfer. It references the transferring `trust_id`, the skip-person `beneficiary_id`, and — for a distribution-driven event — the triggering `distribution_id` (null for a termination event). Its `event_type` is `TAXABLE_DISTRIBUTION` when a paid distribution reaches a skip person, or `TAXABLE_TERMINATION` when a trust terminates with a skip-person remainder. The `taxable_amount_cents` is the distribution amount for the former or the terminating principal share for the latter, and `inclusion_ratio_snapshot` captures the trust's `inclusion_ratio` at the moment the event was generated. GST events may be listed per trust (filterable by `beneficiary_id`), fetched individually, and listed globally filtered by `beneficiary_id` or `distribution_id`.

### 3.9. Trust Income Tax, GST Tax, and the Amendment, Revocation, and Termination Paths

**Trust income tax** is computed when a filing is filed and when an amended filing is refiled. For a grantor trust — one whose `is_grantor_trust` election is true — the `tax_due_cents` is 0, because the trust's income flows through to the grantor and the trust pays no tax at its own level. For a non-grantor trust the tax is computed on the snapshotted taxable income under the compressed four-bracket schedule, applied marginally: the first 310,000 cents of taxable income are taxed at 10 percent; taxable income above 310,000 and up to 1,115,000 cents at 24 percent; taxable income above 1,115,000 and up to 1,520,000 cents at 35 percent; and any taxable income above 1,520,000 cents at 37 percent. The four bracket amounts are summed and the total is rounded half up to whole cents. The identical taxable income therefore produces a positive tax for a separate-taxpayer trust and exactly zero for an otherwise-identical grantor trust.

**GST tax** is computed on every GST event, whether spawned by a skip-person distribution payment or by a taxable-termination cascade. It equals the event's `taxable_amount_cents` multiplied by the trust's `inclusion_ratio` at event time (the value captured in `inclusion_ratio_snapshot`, carried to six decimal places) multiplied by the GST rate of 0.40, with the product rounded half up to whole cents and recorded in `gst_tax_cents`.

The amendment loop belongs to the grantor and applies only to a revocable trust. Opening an amendment moves the trust from `ACTIVE` to `AMENDMENT_PENDING` and stages an election change; the grantor supplies the optional `set_capital_gains_to_income` and `set_is_grantor_trust` to record the new election values to be applied. It is permitted only while the trust is `ACTIVE`, and an attempt to amend an `IRREVOCABLE` trust is rejected with `ERR_TRUST_IRREVOCABLE`; the `ACTIVE`-status check is evaluated before the irrevocability check, so an amend on a trust that is both not `ACTIVE` and `IRREVOCABLE` returns `ERR_INVALID_STATE`, and a trust that is not `ACTIVE` for any other reason is also rejected with `ERR_INVALID_STATE`. Committing the amendment moves the trust from `AMENDMENT_PENDING` back to `ACTIVE` (a commit against a trust not in `AMENDMENT_PENDING` is rejected with `ERR_INVALID_STATE`), applies the staged `capital_gains_to_income` and `is_grantor_trust` changes to the trust, recomputes ledger sides and distributable net income for affected periods (since the capital-gain allocation may have flipped), and increments the trust's `version`. Each transition increments `version`.

Revocation, also a grantor action confined to revocable trusts, moves a trust from `ACTIVE` to the terminal `REVOKED` state; it is permitted only while the trust is `ACTIVE`, an attempt to revoke an `IRREVOCABLE` trust is rejected with `ERR_TRUST_IRREVOCABLE`, and it transitions every `OPEN` period on the trust to `CLOSED` and increments the trust's `version`. As with amendment, the `ACTIVE`-status check precedes the irrevocability check, so a revoke on a trust that is not `ACTIVE` returns `ERR_INVALID_STATE` even when the trust is also `IRREVOCABLE`. Termination is the back office's path and runs in two steps. Beginning termination moves a trust from `ACTIVE` to `TERMINATING`; it is permitted only while the trust is `ACTIVE` (a begin-termination request against a trust not in `ACTIVE` status is rejected with `ERR_INVALID_STATE`, checked before the unsettled-distribution scan) and only when no distribution on any of the trust's periods is still `PROPOSED` or `APPROVED` (an unsettled distribution blocks termination with `ERR_UNSETTLED_DISTRIBUTION`), and as its cascade it transitions every `OPEN` period to `CLOSED` and increments the trust's `version`. Finalizing termination moves the trust from `TERMINATING` to the terminal `TERMINATED` state; it is permitted only while the trust is `TERMINATING` and only when every period on the trust is `FILED` — a finalize request against a trust that is not `TERMINATING`, or one that still has any period not in `FILED` status, is rejected with `ERR_INVALID_STATE`. Its cascade creates, for each skip-person beneficiary, a GST event of type `TAXABLE_TERMINATION` whose `taxable_amount_cents` is that beneficiary's pro-rata share of the trust's `principal_balance_cents` — an equal split across the skip-person beneficiaries, with any remainder cents assigned to the earliest-created skip-person beneficiary by `created_at` ascending — and computes each event's GST tax. The set of skip-person beneficiaries for this cascade is every persisted `Beneficiary` whose `grantor_id` equals the trust's `grantor_id` and whose `is_skip_person` flag is true (the beneficiaries are not otherwise tied to the trust); each such beneficiary's `inclusion_ratio_snapshot` captures the trust's current `inclusion_ratio`. When the trust has no such skip-person beneficiary the cascade creates no GST events and finalization otherwise proceeds normally. The trust's `version` is incremented.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that transition or otherwise modify an existing resource, including releases and state transitions, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/grantors` | Create a grantor (settlor) | TrustAdmin |
| GET | `/grantors/{id}` | Fetch a grantor (with computed exemption remaining) | TrustAdmin, Grantor |
| POST | `/trustees` | Register a trustee | TrustAdmin |
| GET | `/trustees/{id}` | Fetch a trustee | TrustAdmin, Trustee |
| POST | `/beneficiaries` | Create a beneficiary (computes skip-person flag) | TrustAdmin |
| GET | `/beneficiaries/{id}` | Fetch a beneficiary | TrustAdmin, Beneficiary |
| GET | `/beneficiaries` | List beneficiaries (filter by grantor) | TrustAdmin |
| POST | `/trusts` | Create a trust in DRAFT | TrustAdmin |
| GET | `/trusts/{id}` | Fetch a trust (with balances and inclusion ratio) | TrustAdmin, Grantor, Trustee |
| GET | `/trusts` | List trusts (filter by grantor) | TrustAdmin |
| POST | `/trusts/{id}/fund` | Move a trust from DRAFT to FUNDED | TrustAdmin |
| POST | `/trusts/{id}/activate` | Move a trust from FUNDED to ACTIVE | TrustAdmin |
| POST | `/trusts/{id}/amendments` | Open an amendment (revocable only) | Grantor |
| POST | `/trusts/{id}/amendments/commit` | Commit a staged amendment | Grantor |
| POST | `/trusts/{id}/revoke` | Revoke a trust (revocable only) | Grantor |
| POST | `/trusts/{id}/terminate` | Begin terminating a trust | TrustAdmin |
| POST | `/trusts/{id}/terminate/finalize` | Finalize termination (spawns termination GST events) | TrustAdmin |
| POST | `/trusts/{id}/trustee-appointments` | Appoint a trustee over a trust | TrustAdmin |
| GET | `/trusts/{id}/trustee-appointments` | List a trust's trustee appointments | TrustAdmin, Trustee |
| GET | `/trustee-appointments/{id}` | Fetch a trustee appointment | TrustAdmin, Trustee |
| GET | `/trustee-appointments` | List trustee appointments (filter by trustee) | TrustAdmin |
| POST | `/trusts/{id}/accounts` | Open an accounting period | TrustAdmin |
| GET | `/accounts/{id}` | Fetch an accounting period (with computed figures) | TrustAdmin, Trustee |
| GET | `/trusts/{id}/accounts` | List a trust's accounting periods | TrustAdmin, Trustee |
| POST | `/accounts/{id}/close` | Close a period (freezes ledger) | TrustAdmin |
| POST | `/accounts/{id}/receipts` | Post a receipt | TrustAdmin, Trustee |
| GET | `/accounts/{id}/receipts` | List receipts on a period | TrustAdmin, Trustee |
| POST | `/accounts/{id}/disbursements` | Post a disbursement | TrustAdmin, Trustee |
| GET | `/accounts/{id}/disbursements` | List disbursements on a period | TrustAdmin, Trustee |
| POST | `/accounts/{id}/distributions` | Propose a distribution | Trustee |
| GET | `/distributions/{id}` | Fetch a distribution | TrustAdmin, Trustee |
| GET | `/accounts/{id}/distributions` | List distributions on a period | TrustAdmin, Trustee |
| GET | `/distributions` | List distributions (filter by beneficiary/proposer/approver) | TrustAdmin, Trustee |
| POST | `/distributions/{id}/approve` | Approve a distribution (segregation of duties) | Trustee |
| POST | `/distributions/{id}/reject` | Reject a distribution | Trustee |
| POST | `/distributions/{id}/pay` | Pay a distribution (cascading ledger/K-1/GST effects) | Trustee |
| POST | `/distributions/{id}/reverse` | Reverse a paid distribution (compensating) | TrustAdmin |
| GET | `/accounts/{id}/k1s` | List K-1 statements on a period | TrustAdmin, Trustee |
| GET | `/k1s/{id}` | Fetch a K-1 statement | TrustAdmin, Trustee, Beneficiary |
| GET | `/k1s` | List K-1 statements (filter by beneficiary) | TrustAdmin, Beneficiary |
| POST | `/accounts/{id}/filings` | Create a DRAFT tax filing | TrustAdmin |
| GET | `/filings/{id}` | Fetch a tax filing | TrustAdmin |
| GET | `/accounts/{id}/filings` | List filings on a period | TrustAdmin |
| GET | `/filings` | List filings (filter by account/superseded filing) | TrustAdmin |
| POST | `/filings/{id}/file` | File a draft return (cascades) | TrustAdmin |
| POST | `/filings/{id}/amend` | Amend a filed return | TrustAdmin |
| POST | `/filings/{id}/refile` | Refile an amended return | TrustAdmin |
| POST | `/trusts/{id}/gst-exemption-allocations` | Allocate GST exemption (OCC on trust version) | TrustAdmin |
| GET | `/trusts/{id}/gst-exemption-allocations` | List a trust's exemption allocations | TrustAdmin |
| GET | `/gst-exemption-allocations/{id}` | Fetch a GST exemption allocation | TrustAdmin |
| GET | `/gst-exemption-allocations` | List exemption allocations (filter by grantor) | TrustAdmin |
| DELETE | `/trusts/{id}/gst-exemption-allocations/{alloc_id}` | Release a GST exemption allocation | TrustAdmin |
| GET | `/trusts/{id}/gst-events` | List GST events on a trust | TrustAdmin |
| GET | `/gst-events/{id}` | Fetch a GST event | TrustAdmin |
| GET | `/gst-events` | List GST events (filter by beneficiary/distribution) | TrustAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TRUST_IRREVOCABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_ACCOUNT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_TRUSTEE_TERM_CONFLICT` | 409 Conflict |
| `ERR_PERIOD_FROZEN` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_GRANTOR_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_CORPUS` | 409 Conflict |
| `ERR_GST_EXEMPTION_EXCEEDED` | 409 Conflict |
| `ERR_STALE_TRUST_VERSION` | 412 Precondition Failed |
| `ERR_ALLOCATION_CONSUMED` | 409 Conflict |
| `ERR_UNSETTLED_DISTRIBUTION` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
