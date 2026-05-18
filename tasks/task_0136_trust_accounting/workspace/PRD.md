# Trust Accounting API — Product Requirements Document

## 1. Introduction

Wealth-management institutions, family offices, and law firms that administer private trusts share a common problem: the fiduciary record of a trust is simultaneously a legal instrument, a tax filing engine, and an operational ledger, and the three views must remain reconciled at all times. A grantor funds a trust today, beneficiaries are added or terminated as families evolve, a trustee books income and expense events throughout the calendar year, distributions are proposed, scrutinized and paid, and at year-end a tax preparer closes the books and issues IRS Schedule K-1 forms to each beneficiary. Any of these actors can race, misorder, or contradict each other, and the system is held to court-of-law standards of immutability and auditability.

This document specifies the Trust Accounting API, a backend service that captures the entire revocable-and-irrevocable trust lifecycle: trust formation in draft, activation under fiduciary supervision, lifetime income and expense bookkeeping, distribution proposal and execution under segregation-of-duties controls, generation-skipping transfer (GST) exemption tracking, year-end Distributable Net Income (DNI) computation, dual-variant entity-level income taxation for grantor versus non-grantor trusts, K-1 issuance with version-pinned snapshots, and the amendment cycle that lets a closed year be reopened for correction. The API is mounted under `/trusts`, with a single auxiliary endpoint at `/_clock/advance` for deterministic test-driven time control.

The design priority is correctness under concurrency and across cascading mutations: a transaction recorded in a closing tax year must propagate into the year's DNI, a distribution executed during a year-end close must re-shape every affected beneficiary's draft K-1, and a stale optimistic-concurrency token must reject the writer without silently corrupting downstream computations. The natural-language requirements below define every entity, every state transition, every calculation order, every validation priority, and every error code that achieves that goal.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must include the two authentication headers `X-User-ID` and `X-User-Role`. If either header is missing or cannot be parsed, the server rejects the request with `ERR_UNAUTHENTICATED`. If the authenticated role is not permitted to invoke the requested endpoint, the server rejects the request with `ERR_FORBIDDEN`.

Five roles are defined; their names are spelled exactly as follows: `Grantor`, `Trustee`, `Beneficiary`, `TaxPreparer`, and `Auditor`.

- `Grantor` is the natural person who creates and funds a trust. Grantor identity is opaque: there is no persisted Grantor entity. When `X-User-Role` is `Grantor`, `X-User-ID` is an opaque identifier not tied to any stored entity record. The server records this identifier on a Trust at creation time as `grantor_user_id`, and subsequent ownership checks on Trust-scoped grantor operations compare the supplied `X-User-ID` against the Trust's `grantor_user_id`.
- `Trustee` is the fiduciary administrator. When `X-User-Role` is `Trustee`, `X-User-ID` is the `user_id` of an existing `Trustee` record under the trust referenced in the URL path, and that `Trustee` record must have `status` equal to `ACTIVE`. Ownership and segregation-of-duties checks on Distribution operations compare `X-User-ID` against the `Trustee.user_id` registered on the target trust.
- `Beneficiary` is a read-only recipient identity. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of an existing `Beneficiary` record. Ownership filtering on Beneficiary-scoped reads compares the resource's `beneficiary_id` (or, for the Beneficiary record itself, its `id`) to `X-User-ID`.
- `TaxPreparer` is the tax-computation operator. When `X-User-Role` is `TaxPreparer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server uses it only for audit logging, not for ownership comparison.
- `Auditor` is an independent read-only role with global visibility. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque operator identifier; no ownership filter is applied, and the auditor sees all trusts and all nested resources.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter has a default of 10, a minimum of 1, and a maximum of 100; the `offset` parameter has a default of 0 and a minimum of 0. List results are sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring `limit` and `offset`), and `has_more` (a boolean indicating whether further pages remain).

### 2.4. Common Resource Properties

Most resources expose four common fields: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix; clients never supply it. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every successful mutation of the resource (whether through a direct PATCH, a state-transition action, or a cascade triggered by an operation on a related resource).

One entity is an exception: the `Transaction` resource is an append-only event-log record that carries only `id` and `created_at`; it has no `updated_at` and no `version`, because a booked transaction is never edited in place — corrections are made by recording further compensating transactions.

### 2.5. Optimistic Concurrency Control

Every PATCH endpoint on a resource that carries a `version` field accepts a `version` value in its request body. When the supplied `version` matches the resource's current `version`, the mutation is applied and the resource's `version` is incremented. When the supplied `version` does not match, the server rejects the request with `ERR_VERSION_MISMATCH` and an HTTP 409 status. Omitting `version` from the request body skips the optimistic-concurrency check entirely; the mutation proceeds against whatever the current state is. Two concurrent PATCH writers on the same Trust where one carries a stale `version` and the other is current resolve as a compare-and-swap on `Trust.version`: the stale writer receives `ERR_VERSION_MISMATCH`.

### 2.6. Path Resolution and Nested Resource Hierarchy

Endpoint paths are deeply nested: a K-1 is read through a path that names the parent Trust, then the parent TaxYear, then the K-1 itself. All path-segment identifiers are validated from left to right. The Trust is resolved first; if it does not exist, `ERR_NOT_FOUND` is returned. Only then does the server resolve the next segment (Trustee, Beneficiary, Asset, Transaction, Distribution, or TaxYear under that trust). For K-1 reads, TaxYear is resolved before the K-1. If any segment fails to resolve to an existing record under the appropriate parent scope, `ERR_NOT_FOUND` is returned. Sibling-entity references inside request bodies — for instance, the `beneficiary_id` supplied when proposing a distribution, or the implicit `tax_year_id` derivation from a transaction's `transaction_date` — must resolve to a record that exists under the same Trust; otherwise the request is rejected with `ERR_NOT_FOUND`.

### 2.7. Monetary Precision and Rounding

All monetary fields are denominated in United States dollars and carry exactly 2 decimal places. The rounding method is "round half up" — that is, a value whose discarded fractional remainder is exactly 0.005 rounds away from zero (so 0.005 becomes 0.01). This precision and rounding rule applies to every computed monetary field: `principal_balance`, `income_balance`, `gst_exemption_used`, `gst_tax_amount`, `dni`, `trust_taxable_income`, `trust_income_tax`, and every K-1 share field. For multi-step calculations, rounding is performed only at the points explicitly pinned in §3 — never silently in the middle of an aggregation.

### 2.8. Validation Priority Ordering

When multiple validations would reject a request, the server evaluates them in a fixed priority order and returns the error of the first one that fails. Authentication runs first: a missing or unparseable `X-User-Role` / `X-User-ID` pair produces `ERR_UNAUTHENTICATED` before any other check. Role-based authorization comes second, producing `ERR_FORBIDDEN` for a permitted-but-wrong-role caller. Path-segment existence comes third, with `ERR_NOT_FOUND` for any unresolved `trustId`, `trusteeId`, `beneficiaryId`, `assetId`, `transactionId`, `distributionId`, `taxYearId`, or `k1Id`; sibling-reference existence inside the body comes fourth, also producing `ERR_NOT_FOUND`. Optimistic-concurrency `version` matching comes fifth on PATCH endpoints, producing `ERR_VERSION_MISMATCH`. State-machine acceptability comes sixth, producing `ERR_INVALID_STATE` when the target resource is not in a state from which the requested action is allowed. Beneficiary-active checks come seventh, producing `ERR_BENEFICIARY_TERMINATED`. Segregation-of-duties checks come eighth, producing `ERR_SEGREGATION_OF_DUTIES`. Court-of-law immutability checks come ninth, producing `ERR_IRREVOCABLE_CANNOT_REVOKE`. Tax-year temporal checks come tenth and eleventh, producing `ERR_TAX_YEAR_CLOSED` and `ERR_TAX_YEAR_NOT_ENDED` respectively. The amendment-ordering check is twelfth, producing `ERR_NEWER_YEAR_CLOSED`. Activation-prerequisite checks are thirteenth, producing `ERR_NO_PRIMARY_TRUSTEE` (the same activation pathway also surfaces `ERR_NO_BENEFICIARY` and `ERR_NO_OPEN_TAX_YEAR` as parallel checks at the same logical step). Grantor-status-compatibility is fourteenth, producing `ERR_GRANTOR_STATUS_INCOMPATIBLE` with HTTP 422. Fiscal sufficiency checks are fifteenth, sixteenth, and seventeenth, producing `ERR_INSUFFICIENT_PRINCIPAL`, `ERR_INSUFFICIENT_INCOME`, and `ERR_INSUFFICIENT_INCOME_FOR_TAX` respectively. Termination-completeness comes eighteenth, producing `ERR_NONZERO_BALANCE`. Malformed body shapes — negative monetary amounts, unrecognized enums, or otherwise unparseable JSON — surface as `ERR_BAD_REQUEST` with HTTP 400 at the JSON-shape parsing stage, ahead of every business validation but after authentication.

### 2.9. Cascading Side Effects, `updated_at`, and `version` Semantics on Cascades

A single inbound request can mutate more than one resource. When this happens, every mutated resource has its `updated_at` refreshed to the current server clock and its `version` incremented by 1. The Trust aggregate is the most common cascade target: adding an Asset updates the Trust's principal_balance or income_balance and therefore bumps `Trust.version`; recording a Transaction bumps `Trust.version`; executing a Distribution bumps `Trust.version` and also bumps the affected DRAFT K-1's `version`. Cascades may go up to three levels deep (for example, executing a distribution adjusts trust balances, refreshes the DRAFT K-1 shares for the affected beneficiary, and updates the running DNI accrual on the open TaxYear). On every level of the cascade, both `updated_at` and `version` are refreshed on the mutated record.

### 2.10. The Logical Clock

Because tax-year closing depends on calendar time, the system relies on a server-controlled logical clock rather than wall-clock time. An admin-only test-driving capability advances this clock to a supplied target instant carried as `to_timestamp` in the request body; all subsequent server-side time lookups return the advanced value. Roles permitted to advance the clock are `TaxPreparer`, `Trustee`, and `Grantor`. The clock never moves backwards in normal operation; once advanced, all temporal validations (notably `ERR_TAX_YEAR_NOT_ENDED`) read from this advanced value.

### 2.11. Court-of-Law Immutability

Once a Trust has transitioned to `ACTIVE`, certain configuration fields become legally immutable. The `trust_type` and `inception_date` are frozen at activation. The `grantor_tax_status` is also frozen at activation — any subsequent PATCH attempting to change `trust_type` or `grantor_tax_status` is rejected with `ERR_IRREVOCABLE_CANNOT_REVOKE`. While the trust is still in `DRAFT`, both `trust_type` and `grantor_tax_status` may be patched; the `has_grantor_powers` flag may also be patched in `DRAFT` and is locked once active. Updating `situs_state` or `name` remains permitted on an `ACTIVE` trust.

## 3. Business Logic & Workflows

### 3.1. Trust Formation, Activation, and Termination

A trust begins life when a `Grantor` creates a Trust resource by supplying a payload containing the trust's legal `name`, the `trust_type` (either `REVOCABLE` or `IRREVOCABLE`), the `grantor_tax_status` (either `GRANTOR` or `NON_GRANTOR`), a `has_grantor_powers` boolean, a two-letter `situs_state` US state code, and the `inception_date` on which the trust instrument was executed. The new Trust enters `DRAFT` status, its `grantor_user_id` is pinned to the creator's `X-User-ID`, and its `principal_balance`, `income_balance`, and `gst_exemption_used` all initialize to 0.

At creation and on any subsequent `DRAFT`-stage patch, the combination of `grantor_tax_status`, `trust_type`, and `has_grantor_powers` is checked for legal compatibility. A `GRANTOR` tax status is forbidden when the `trust_type` is `IRREVOCABLE` and `has_grantor_powers` is false; that combination is rejected with `ERR_GRANTOR_STATUS_INCOMPATIBLE` and HTTP 422. The `GRANTOR` tax status is permitted whenever the trust is either `REVOCABLE`, or `IRREVOCABLE` with `has_grantor_powers` set to true. The economic meaning of this flag is that under `GRANTOR` status, all trust income flows to the grantor's personal 1040 return and the trust pays no entity-level income tax.

Before a trust can be activated, three structural conditions must hold. There must be exactly one `Trustee` record under the trust with `is_primary` set to true and `status` equal to `ACTIVE`; if not, activation fails with `ERR_NO_PRIMARY_TRUSTEE`. There must be at least one `Beneficiary` record under the trust with `status` equal to `ACTIVE`; otherwise activation fails with `ERR_NO_BENEFICIARY`. A TaxYear matching the calendar year of `inception_date` must exist for the trust in `OPEN` status; otherwise activation fails with `ERR_NO_OPEN_TAX_YEAR`. When all three preconditions hold, activation transitions `Trust.status` from `DRAFT` to `ACTIVE`, freezes `trust_type` and `inception_date`, and recomputes both balances: `principal_balance` is set to the sum of `book_value` across all `Asset` records whose `classification` is `PRINCIPAL` and whose `status` is `FUNDED`; `income_balance` is set to the analogous sum over assets whose `classification` is `INCOME`.

Two terminal exits are available from `ACTIVE`. The first is revocation, available only to a `Grantor` and only on a `REVOCABLE` trust. Revoking an `IRREVOCABLE` trust is rejected with `ERR_IRREVOCABLE_CANNOT_REVOKE`. Revocation also requires that no Distribution is currently in `APPROVED` status (otherwise `ERR_HAS_APPROVED_DISTRIBUTIONS`) and that no TaxYear is currently in `CLOSING` status (otherwise `ERR_TAX_YEAR_CLOSING_IN_PROGRESS`). When revocation succeeds, the Trust transitions `ACTIVE → REVOKED`; the `principal_balance` and `income_balance` are returned to the grantor by being zeroed; every `Beneficiary` with `status` of `ACTIVE` transitions to `TERMINATED`; every `Asset` with `status` of `FUNDED` transitions to `DISTRIBUTED`; and these cascades go three levels deep — the revoke itself, then asset re-statusing, then a balance true-up that may further reduce `income_balance` to zero. The Trust's `version` and `updated_at` are refreshed at the top of the cascade, and every cascaded child resource has its own `version` and `updated_at` refreshed.

The second exit is termination, available only to a `Trustee` and intended for the natural end of a trust's productive life. Termination requires that every `Asset` is in either `DISTRIBUTED` or `SOLD` status (otherwise `ERR_HAS_UNDISTRIBUTED_ASSETS`); that both `principal_balance` and `income_balance` are exactly zero (otherwise `ERR_NONZERO_BALANCE`); and that the Trust's `current_tax_year_id` refers to a TaxYear whose `status` is either `CLOSED` or `AMENDED` (otherwise `ERR_TAX_YEAR_NOT_CLOSED`). When all three hold, the Trust transitions `ACTIVE → TERMINATED` and all remaining `ACTIVE` beneficiaries transition to `TERMINATED`.

### 3.2. Trustees, Beneficiaries, and Assets

A `Grantor` registers trustees by submitting a payload containing the trustee's `user_id` (the opaque platform identifier of the natural person who will act as trustee), their legal `full_name`, and a boolean `is_primary` flag. Every active trust must have exactly one primary trustee; the primary trustee is the sole signatory for any irrevocable Trust amendment scenario. If a new trustee is registered with `is_primary` set to true while another trustee on the same trust already has `is_primary` set to true, the prior primary is automatically demoted by having its `is_primary` flipped to false — this is a two-level cascade, and both trustee records have their `version` and `updated_at` refreshed. A Trustee record carries a `trust_id` (system-populated) and a `status` field that progresses through `ACTIVE`, `RESIGNED`, and `REMOVED`.

A `Grantor` registers beneficiaries by submitting a payload containing the beneficiary's `full_name`, the `relation_class` (`SPOUSE`, `CHILD`, `GRANDCHILD`, `OTHER_LINEAL`, or `NON_LINEAL`), the `beneficiary_class` (`INCOME`, `REMAINDER`, or `INCOME_AND_REMAINDER`), the `distribution_tier` (`TIER_1` for mandatory income distributees or `TIER_2` for discretionary), and the `birth_date`. The system computes the `is_skip_person` flag at creation time, and recomputes it any time the `relation_class` or `birth_date` is patched. A beneficiary is a "skip person" for generation-skipping-transfer-tax purposes under the following rule: if the `relation_class` is `GRANDCHILD`, the beneficiary is always a skip person. If the `relation_class` is `OTHER_LINEAL` (great-grandchildren and further-removed lineal descendants), the system computes the age difference in years between the trust's `inception_date` (used here as the grantor's date-of-birth proxy) and the beneficiary's `birth_date` using a day-count divided by 365.25, expressed to two decimal places; the beneficiary is a skip person when that age difference is at least 37.5 years. If the `relation_class` is `NON_LINEAL`, the same age-difference computation is applied with the same threshold. For `SPOUSE` or `CHILD`, the beneficiary is never a skip person. The threshold uses an at-least comparison, so an age difference of exactly 37.5 years qualifies as a skip person; 37.49 does not. The Beneficiary record also has a `trust_id` populated by the system and a `status` field of either `ACTIVE` or `TERMINATED`.

Terminating a beneficiary is a trustee operation. The transition is `ACTIVE → TERMINATED`, and it is rejected with `ERR_HAS_PENDING_DISTRIBUTIONS` if any Distribution referencing the beneficiary is currently in either `PROPOSED` or `APPROVED` status, and with `ERR_TRUST_NOT_ACTIVE` if the parent Trust is not in `ACTIVE` status.

Assets may be added by either a `Grantor` or a `Trustee`. The request body carries a `description` string, an `asset_class` (`CASH`, `EQUITY`, `BOND`, `REAL_ESTATE`, or `OTHER`), a `book_value` in USD with two decimal places, and a `classification` of either `PRINCIPAL` or `INCOME`. The Asset record carries a `trust_id` and a `status` that flows through `FUNDED`, `DISTRIBUTED`, and `SOLD`. Adding a `FUNDED` asset increases the Trust's `principal_balance` by `book_value` when classification is `PRINCIPAL`, or its `income_balance` by `book_value` when classification is `INCOME`; the Trust's `version` and `updated_at` are refreshed by the cascade. A cash asset that is classified as `INCOME` becomes the natural source of future income-only distributions.

### 3.3. The Transaction Event Log

A `Trustee` records financial events as Transactions. Each Transaction submission carries a `txn_type` (one of `INCOME_ORDINARY`, `INCOME_INTEREST`, `INCOME_DIVIDEND`, `INCOME_CAPITAL_GAIN`, `EXPENSE_ADMINISTRATIVE`, or `EXPENSE_INVESTMENT`), a positive `amount` in USD with two decimal places (the sign is implied by `txn_type`: income types add, expense types subtract), a `transaction_date`, a `principal_or_income` accounting classification (either `PRINCIPAL` or `INCOME`), and a free-text `description` memo. The Transaction record carries a `trust_id` and, populated by the server at booking time, a `tax_year_id` resolved by mapping `transaction_date` to the TaxYear whose calendar year contains it. Capital gains default conceptually to `PRINCIPAL` unless the trust instrument allocates them to `INCOME`, but the `principal_or_income` field is always explicit in the request, so the client always declares the allocation.

A Transaction's `transaction_date` must fall inside a TaxYear that is in either `OPEN` or `CLOSING` status for this trust; otherwise the request is rejected with `ERR_TAX_YEAR_CLOSED`. Transactions are append-only: there is no PATCH endpoint for Transaction, and the record carries only `id` and `created_at`, with no `updated_at` and no `version`. Booking a Transaction triggers a balance recomputation cascade on the parent Trust — depending on `principal_or_income`, either `principal_balance` or `income_balance` is updated, the Trust's `version` and `updated_at` are refreshed, and if the `transaction_date` falls in a `CLOSING` year, the DRAFT K-1s and DNI snapshot for that year are also recomputed (a depth-three cascade).

Transactions may be listed under a Trust with optional filters `tax_year_id`, `txn_type`, `from`, and `to` (the last two delimiting a date range), with the standard `limit` and `offset` pagination parameters.

### 3.4. Distribution Proposal, Approval, Execution, and Rejection

A Distribution moves money out of the trust to a beneficiary, and its lifecycle enforces strict segregation of duties. Either a `Grantor` or a `Trustee` may propose a Distribution by submitting a request body containing the recipient's `beneficiary_id`, a `scheduled_date`, an `amount_principal` (USD, two decimal places, not less than zero), an `amount_income` (USD, two decimal places, not less than zero), and a `distribution_type` of `MANDATORY` (for tier-1 income distributions), `DISCRETIONARY`, or `TERMINATING`. The new Distribution starts in `PROPOSED` status; its `trust_id` is system-populated, its `tax_year_id` is resolved from `scheduled_date`, its `proposed_by_user_id` is pinned to the proposer's `X-User-ID`, and `approved_by_user_id` is null. The `gst_taxable` flag is computed in preview mode on proposal (informational only) and pinned for real on approval. The `scheduled_date` must fall inside an `OPEN` TaxYear for this trust; otherwise the proposal is rejected with `ERR_TAX_YEAR_CLOSED`.

A `Trustee` then approves the proposed Distribution. Approval requires that the parent Trust is in `ACTIVE` status (otherwise `ERR_TRUST_NOT_ACTIVE`), that the referenced Beneficiary is in `ACTIVE` status (otherwise `ERR_BENEFICIARY_TERMINATED`), and that the referenced TaxYear is in `OPEN` status (otherwise `ERR_TAX_YEAR_NOT_OPEN`). The approving trustee's `X-User-ID` must differ from the Distribution's `proposed_by_user_id`; if they match, approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. The `amount_principal` must be at most the Trust's current `principal_balance` (otherwise `ERR_INSUFFICIENT_PRINCIPAL`), and the `amount_income` must be at most the Trust's current `income_balance` (otherwise `ERR_INSUFFICIENT_INCOME`). When all preconditions hold, the Distribution transitions `PROPOSED → APPROVED`; `approved_by_user_id` is pinned to the acting trustee; and both `gst_taxable` and `gst_tax_amount` are recomputed and pinned per the GST rules described in §3.6. Two trustees racing to approve the same `PROPOSED` Distribution serialize on `Distribution.status`: exactly one succeeds, and the second observes that the distribution is no longer `PROPOSED` and is rejected with `ERR_INVALID_STATE`. A race between an approve and a reject on the same `PROPOSED` Distribution resolves identically: exactly one transition takes effect on `Distribution.status`, and the loser sees `ERR_INVALID_STATE`.

A `Trustee` executes an `APPROVED` Distribution. Execution re-checks fiscal sufficiency immediately before applying the debit: `principal_balance` must still be at least `amount_principal` (otherwise `ERR_INSUFFICIENT_PRINCIPAL`) and `income_balance` must still be at least `amount_income` (otherwise `ERR_INSUFFICIENT_INCOME`). The Beneficiary must still be in `ACTIVE` status (otherwise `ERR_BENEFICIARY_TERMINATED`). On success the Distribution transitions `APPROVED → EXECUTED` and four cascade effects fire: the Trust's `principal_balance` is reduced by `amount_principal`; its `income_balance` is reduced by `amount_income`; its `gst_exemption_used` is increased by the exemption-applied portion described in §3.6; and if `gst_taxable` is true, `income_balance` is additionally reduced by `gst_tax_amount` (the trust pays the GST tax out of its retained income). The DRAFT K-1 for this beneficiary in the affected TaxYear is recomputed (refreshing `ordinary_income_share`, `interest_income_share`, `dividend_income_share`, `capital_gain_share`, and `total_distributed`), and the year's `dni` running sum is refreshed — a depth-three cascade. Two executions racing on two different `APPROVED` distributions that individually fit the Trust's `principal_balance` but together do not serialize as first-writer-wins on the principal debit: the first execution succeeds, and the second observes the reduced `principal_balance` and is rejected with `ERR_INSUFFICIENT_PRINCIPAL`. The analogous income race is rejected with `ERR_INSUFFICIENT_INCOME`.

Rejection ends a Distribution's life early. A `Trustee` may reject a Distribution that is in `PROPOSED` status, which transitions it `PROPOSED → REJECTED`; the parent Trust must be in `ACTIVE` or `REVOKED` status for this transition (a rejection on a revoked trust is allowed because it represents a permitted clean-up of stale proposals). A Trustee may also reject a Distribution that has been approved but not yet executed, transitioning it `APPROVED → REJECTED`; in this second case the rejecting trustee's `X-User-ID` must differ from `approved_by_user_id`, because a different trustee must serve as the rejecter (segregation again); a same-trustee approve-then-reject is rejected with `ERR_SEGREGATION_OF_DUTIES`. The `approved_by_user_id` is retained on a rejected-after-approval Distribution for audit purposes.

### 3.5. TaxYears, DNI Computation, and the Closing Cycle

A `Trustee` or `TaxPreparer` opens a TaxYear by supplying its four-digit `calendar_year`. The TaxYear's `start_date` and `end_date` are derived from the calendar year (first and last day, respectively). The combination of `trust_id` and `calendar_year` is unique. When the first TaxYear is opened for a trust, the Trust's `current_tax_year_id` is set to point at it. A TaxYear progresses through `OPEN → CLOSING → CLOSED`, with `CLOSED → AMENDED` available to reopen for K-1 corrections, and `AMENDED → CLOSED` to re-close after corrections. The `closed_at` timestamp records when the most recent `CLOSING → CLOSED` (or `AMENDED → CLOSED`) transition occurred.

A `TaxPreparer` initiates closing when the calendar year has ended. The transition `OPEN → CLOSING` requires that the logical clock has reached at least the TaxYear's `end_date`; otherwise the request is rejected with `ERR_TAX_YEAR_NOT_ENDED`. It also requires that no Distribution belonging to this `tax_year_id` is in `APPROVED` status — the preparer must execute or reject every approved-but-unexecuted distribution before closing can start; otherwise `ERR_HAS_APPROVED_DISTRIBUTIONS`. As a side effect of beginning the close, every Distribution in `PROPOSED` status for this `tax_year_id` is automatically transitioned to `REJECTED`. The TaxYear's `dni` is then computed and pinned via the DNI formula below, and each beneficiary's DRAFT K-1 has its character shares refreshed via the waterfall allocation described in §3.7. A race between begin-close and Distribution execution on the same TaxYear serializes on `TaxYear.status`: if execution lands first, the year stays `OPEN` and the preparer's begin-close precondition fails; if begin-close lands first, the execution observes that the TaxYear is no longer `OPEN` and is rejected with `ERR_TAX_YEAR_NOT_OPEN`. Two amend requests on the same `CLOSED` TaxYear serialize on `TaxYear.status` from `CLOSED` to `AMENDED`: exactly one amendment cycle starts, and the second sees status `AMENDED` and is rejected with `ERR_INVALID_STATE`.

The Distributable Net Income (DNI) computation aggregates over every Transaction whose `transaction_date` falls within the closed inclusive interval from the TaxYear's `start_date` to its `end_date`, joined to a parent Trust whose `status` is in the set `ACTIVE`, `REVOKED`, or `TERMINATED`. From that source set, the system sums `Transaction.amount` separately by `txn_type` into the buckets `ordinary_income` (sum where `txn_type` equals `INCOME_ORDINARY`), `interest_income` (`INCOME_INTEREST`), `dividend_income` (`INCOME_DIVIDEND`), and `capital_gain` (`INCOME_CAPITAL_GAIN`, restricted further to transactions whose `principal_or_income` is `INCOME`). It also sums `admin_expense` (`EXPENSE_ADMINISTRATIVE`) and `invest_expense` (`EXPENSE_INVESTMENT`). The gross income for the year is the sum of `ordinary_income`, `interest_income`, `dividend_income`, and `capital_gain`. The deductible expense is the sum of `admin_expense` and `invest_expense`. The TaxYear's `dni` is the gross income minus the deductible expense, floored at zero (a negative net is recorded as 0.00 DNI rather than negative DNI), and the final result is rounded half-up to two decimal places.

Finalizing the year transitions `CLOSING → CLOSED`. The preconditions require that every DRAFT K-1 under this `tax_year_id` is ready to transition (one DRAFT K-1 per `ACTIVE`-at-year-end Beneficiary). The trust-level taxable income and the trust-level income tax are computed per §3.7 and §3.8. The Trust's `income_balance` is then debited by the computed `trust_income_tax`; if doing so would drive `income_balance` negative — that is, if `income_balance` is less than the computed `trust_income_tax` — finalize is rejected with `ERR_INSUFFICIENT_INCOME_FOR_TAX`. On success, every DRAFT K-1 transitions to `ISSUED`, its `snapshot_distribution_version_sum` is pinned to the current sum of `version` values across the Distributions that feed into it, and its `issued_at` is set to the logical-clock current time. The TaxYear's `closed_at` is set to the same instant. If a TaxYear exists for the next calendar year (created system-side on the first transaction of that next year), the Trust's `current_tax_year_id` advances to point at it. The finalize cascade goes three levels deep: finalize → tax computed → `income_balance` reduced → K-1 amounts (which were already pinned) remain unchanged and the ISSUED snapshot is taken.

The amendment cycle reopens a `CLOSED` TaxYear for K-1 corrections. Only the `TaxPreparer` may invoke it. Amendment is forbidden when a later TaxYear for the same trust has already reached `CLOSED` status — the rule is "amend in chronological order" and the rejection code is `ERR_NEWER_YEAR_CLOSED`. On success the TaxYear transitions `CLOSED → AMENDED`; every K-1 in `ISSUED` status for this `tax_year_id` transitions to `SUPERSEDED`; and a fresh set of DRAFT K-1 records is created, one per `ACTIVE`-at-year-end Beneficiary. A subsequent finalize transitions the TaxYear back `AMENDED → CLOSED` and re-issues the K-1s; at that point, the version-pinning rule applies: each new DRAFT K-1's `snapshot_distribution_version_sum` must equal the live sum of `Distribution.version` values across the underlying distributions at re-issuance time, and any drift since the prior amendment snapshot is rejected with `ERR_K1_STALE_REFERENCE`. The trust_income_tax difference (new amount minus old amount) is applied to `Trust.income_balance`: a positive delta represents additional tax owed and is debited; a negative delta represents a refund credited.

### 3.6. Generation-Skipping Transfer Tax

The GST regime applies to distributions paid to skip persons. The classification rule for `gst_taxable` operates on three inputs: the recipient's `is_skip_person` flag, the Distribution's combined amount (`amount_principal` plus `amount_income`), and the Trust's running `gst_exemption_used`. The simplified per-trust lifetime GST exemption limit is 13,610,000.00 USD; the GST tax rate applied to amounts beyond exemption is 40%.

The classification proceeds as follows. The total amount of the distribution is `amount_principal` plus `amount_income`. The remaining exemption is computed as the GST exemption limit minus the Trust's current `gst_exemption_used`, floored at zero. If the beneficiary is not a skip person, the taxable portion is zero. If the beneficiary is a skip person, the taxable portion is the total amount minus the remaining exemption, floored at zero. The distribution is `gst_taxable` exactly when the beneficiary is a skip person and the taxable portion is strictly greater than zero. The boundary condition is exact: if the total amount equals the remaining exemption, the taxable portion is zero and `gst_taxable` is false; if the total amount exceeds the remaining exemption by even 0.01, the taxable portion is 0.01 and `gst_taxable` is true.

The `gst_tax_amount` is computed only at execution time, and only when `gst_taxable` is true. The evaluation order is pinned and is critical because the dependency looks circular at first glance: `gst_exemption_used` affects the taxable portion, and the executed distribution writes back to `gst_exemption_used`. The pinned order is: first, classify `gst_taxable` using the current `gst_exemption_used`; second, compute the exemption applied as the lesser of the total amount and the remaining exemption; third, compute the taxable portion as the total amount minus the exemption applied; fourth, compute `gst_tax_amount` as the taxable portion multiplied by 40%, rounded half-up to two decimal places. The exemption is allocated first (consumed on execute up to the remaining cap), and tax is then computed on the residual. If `gst_taxable` is false, the `gst_tax_amount` is 0.00. On a successful execution, the Trust's `gst_exemption_used` is increased by the exemption applied — the minimum of the distribution's total amount and the remaining exemption before the execution.

### 3.7. K-1 Issuance and the DNI Waterfall

A K-1 represents one beneficiary's share of the trust's distributable net income for a tax year. Exactly one K-1 in `ISSUED` status exists per pairing of `tax_year_id` and `beneficiary_id`; previously-issued copies for the same pair are moved to `SUPERSEDED` when a new amendment is issued. Each K-1 record carries the parent `tax_year_id`, a denormalized `trust_id` for indexing, the `beneficiary_id`, the four character shares (`ordinary_income_share`, `interest_income_share`, `dividend_income_share`, `capital_gain_share`), a `total_distributed` field (the sum of `amount_income` plus `amount_principal` over `EXECUTED` distributions to this beneficiary in this TaxYear), a `status` of `DRAFT`, `ISSUED`, or `SUPERSEDED`, a `snapshot_distribution_version_sum` (the pinned sum of `version` values from the contributing Distributions, recorded on issuance), and an `issued_at` timestamp (null while in `DRAFT`).

DNI is allocated across beneficiaries through a tiered waterfall. The order is pinned. Define, for each beneficiary B, the per-beneficiary executed income distribution as the sum of `amount_income` across `EXECUTED` distributions to B in this TaxYear. The waterfall executes the following steps in order. First, compute `tier_1_total` as the sum of those per-beneficiary income distributions across beneficiaries whose `distribution_tier` is `TIER_1`. Second, compute `tier_2_total` analogously for beneficiaries whose `distribution_tier` is `TIER_2`. Third, compute the DNI allocated to tier-1 as the lesser of the TaxYear's `dni` and `tier_1_total`. Fourth, compute the DNI remaining after tier-1 as the TaxYear's `dni` minus that tier-1 allocation. Fifth, compute the DNI allocated to tier-2 as the lesser of the remaining DNI and `tier_2_total`. Sixth, for each tier-1 beneficiary, that beneficiary's pre-character share equals the tier-1 DNI allocation multiplied by the beneficiary's per-beneficiary income distribution divided by `tier_1_total` (or zero if `tier_1_total` is zero). Seventh, the analogous formula applies to each tier-2 beneficiary using `tier_2_total` and the tier-2 DNI allocation.

Inside each beneficiary's pre-character share, the four character buckets are pro-rated against the TaxYear's gross DNI character composition. The `ordinary_income_share` is the beneficiary's pre-character share multiplied by `ordinary_income` divided by the TaxYear's `dni`. The `interest_income_share` uses the `interest_income` bucket. The `dividend_income_share` uses the `dividend_income` bucket. The `capital_gain_share` uses the `capital_gain` bucket, but is only populated when the beneficiary's largest distribution in the year had `distribution_type` equal to `TERMINATING` (or when the trust instrument allocates capital gains to income); in all other cases `capital_gain_share` is zero.

Rounding for K-1 shares is pinned and matters: the per-beneficiary pre-character share is computed first to full precision and then rounded half-up to two decimal places. The four character shares are then derived by character split, and the four character shares for a single beneficiary must sum exactly to that beneficiary's rounded pre-character share; the largest character bucket absorbs any 0.01 rounding remainder. When the TaxYear's `dni` is zero, every character share for every beneficiary is 0.00.

The K-1 transitions are: `DRAFT → ISSUED` is a system transition driven by TaxYear `CLOSING → CLOSED` or `AMENDED → CLOSED`, at which point the K-1 totals are pinned, the `snapshot_distribution_version_sum` is recorded, and `issued_at` is set to the current logical-clock time. `ISSUED → SUPERSEDED` is a system transition driven by TaxYear `CLOSED → AMENDED`. When listing K-1s, the `Beneficiary` role sees only K-1 records whose `beneficiary_id` equals their `X-User-ID` — the server applies this filter server-side. A direct read of a single K-1 by a `Beneficiary` is permitted only when the K-1's `beneficiary_id` equals `X-User-ID`; otherwise the request is rejected with `ERR_FORBIDDEN`.

### 3.8. Trust Taxable Income and the Two Tax Variants

The TaxYear's `trust_taxable_income` field is computed at finalize-time, both during the initial `CLOSING → CLOSED` and during any subsequent `AMENDED → CLOSED` re-close. The computation has two variants, and the same Transactions and Distributions can produce two different values depending on which variant applies — the choice is driven by the parent Trust's `grantor_tax_status`.

Under the grantor variant (which applies when the Trust's `grantor_tax_status` is `GRANTOR`, meaning either a `REVOCABLE` trust or an `IRREVOCABLE` trust with `has_grantor_powers` set to true), all income flows through to the grantor's personal 1040 return. The Trust's `trust_taxable_income` is forced to 0.00 regardless of `dni`, and the Trust's `trust_income_tax` is also 0.00. The same Transactions and Distributions that would produce a positive trust-taxable-income under the non-grantor variant produce zero here.

Under the non-grantor variant (which applies when `grantor_tax_status` is `NON_GRANTOR`), the trust is a separate taxpayer. The system first computes the executed income distributions for the year as the sum of `amount_income` across Distributions whose `status` is `EXECUTED` and whose `tax_year_id` equals the TaxYear's `id`. The Trust's `trust_taxable_income` is then the TaxYear's `dni` minus that sum, floored at zero, rounded half-up to two decimal places. The intuition is that the trust is taxed on whatever income it retained after distribution to beneficiaries.

The `trust_income_tax` is then computed from `trust_taxable_income` using compressed-trust marginal brackets. If `trust_taxable_income` is zero or negative, the tax is 0.00. Otherwise, the system processes four ordered bands. The first band covers taxable income from 0.00 up to 3,100.00 at a marginal rate of 10%. The second band covers the range above 3,100.00 up to 11,150.00 at 24%. The third band covers the range above 11,150.00 up to 15,200.00 at 35%. The fourth band covers everything above 15,200.00 at 37%. Processing proceeds in ascending order: the portion of `trust_taxable_income` that falls within each band is multiplied by that band's rate, and the products are summed into a running total. Rounding is pinned and is applied exactly once, at the very end of the cumulative tax sum — never per band. The final cumulative total is rounded half-up to two decimal places, and that is the TaxYear's `trust_income_tax`.

### 3.9. The Trust Balance Aggregation Identity

At any instant, the Trust's `principal_balance` is reconstructable from the underlying records as: the sum of `book_value` across Assets whose `classification` is `PRINCIPAL` and whose `status` is `FUNDED`, plus the sum of `amount` across Transactions whose `principal_or_income` is `PRINCIPAL` and whose `txn_type` is in the set of income types (`INCOME_ORDINARY`, `INCOME_INTEREST`, `INCOME_DIVIDEND`, `INCOME_CAPITAL_GAIN`), minus the sum of `amount` across Transactions whose `principal_or_income` is `PRINCIPAL` and whose `txn_type` is in the set of expense types (`EXPENSE_ADMINISTRATIVE`, `EXPENSE_INVESTMENT`), minus the sum of `amount_principal` across Distributions whose `status` is `EXECUTED`. The final aggregation is rounded half-up to two decimal places — at the final sum, not term by term.

The Trust's `income_balance` is reconstructable as: the sum of `book_value` across Assets whose `classification` is `INCOME` and whose `status` is `FUNDED`, plus the sum of `amount` across Transactions whose `principal_or_income` is `INCOME` and whose `txn_type` is an income type, minus the sum of `amount` across Transactions whose `principal_or_income` is `INCOME` and whose `txn_type` is an expense type, minus the sum of `amount_income` across Distributions whose `status` is `EXECUTED`, minus the sum of `gst_tax_amount` across Distributions whose `status` is `EXECUTED` and whose `gst_taxable` flag is true, minus the sum of `trust_income_tax` across TaxYears whose `status` is in the set `CLOSED` or `AMENDED`. The final aggregation is likewise rounded half-up to two decimal places at the end, not term by term.

These identities are maintained as live invariants by the cascade rules: each Asset state change, each Transaction creation, each Distribution execution, and each TaxYear finalize triggers a re-aggregation against this rule.

## 4. Endpoint Definitions

Successful endpoint invocations return HTTP 200, except for endpoints that create a wholly new resource — which return HTTP 201. Clock advancement returns HTTP 200 because it mutates the server's clock state but does not create a resource. State-transition actions on existing resources (activate, revoke, terminate, approve, execute, reject, begin-close, finalize, amend) all return HTTP 200. All endpoints follow the response envelope and pagination rules defined in §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/advance` | Advance the server's logical clock to a supplied target instant. | `TaxPreparer`, `Trustee`, `Grantor` |
| POST | `/trusts` | Create a Trust in DRAFT status. | `Grantor` |
| GET | `/trusts/{trustId}` | Read a Trust. | `Grantor`, `Trustee`, `Beneficiary`, `TaxPreparer`, `Auditor` |
| GET | `/trusts` | List Trusts visible to the caller (paginated; filters `status`, `trust_type`). | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor` |
| PATCH | `/trusts/{trustId}` | Update mutable Trust fields. `trust_type` and `grantor_tax_status` are mutable only while status is DRAFT. | `Grantor` |
| POST | `/trusts/{trustId}/activate` | Activate the Trust (DRAFT → ACTIVE). | `Grantor` |
| POST | `/trusts/{trustId}/revoke` | Revoke a REVOCABLE Trust (ACTIVE → REVOKED). | `Grantor` |
| POST | `/trusts/{trustId}/terminate` | Terminate an exhausted Trust (ACTIVE → TERMINATED). | `Trustee` |
| POST | `/trusts/{trustId}/trustees` | Add a Trustee. | `Grantor` |
| GET | `/trusts/{trustId}/trustees/{trusteeId}` | Read a Trustee. | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor` |
| POST | `/trusts/{trustId}/beneficiaries` | Add a Beneficiary. | `Grantor` |
| GET | `/trusts/{trustId}/beneficiaries/{beneficiaryId}` | Read a Beneficiary. | `Grantor`, `Trustee`, `Beneficiary`, `TaxPreparer`, `Auditor` |
| POST | `/trusts/{trustId}/beneficiaries/{beneficiaryId}/terminate` | Terminate a Beneficiary (ACTIVE → TERMINATED). | `Trustee` |
| POST | `/trusts/{trustId}/assets` | Add an Asset. | `Grantor`, `Trustee` |
| GET | `/trusts/{trustId}/assets/{assetId}` | Read an Asset. | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor` |
| POST | `/trusts/{trustId}/transactions` | Record an INCOME or EXPENSE Transaction. | `Trustee` |
| GET | `/trusts/{trustId}/transactions/{transactionId}` | Read a Transaction. | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor` |
| GET | `/trusts/{trustId}/transactions` | List Transactions (paginated; filters `tax_year_id`, `txn_type`, `from`, `to`). | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor` |
| POST | `/trusts/{trustId}/distributions` | Propose a Distribution (status PROPOSED). | `Grantor`, `Trustee` |
| GET | `/trusts/{trustId}/distributions/{distributionId}` | Read a Distribution. | `Grantor`, `Trustee`, `Beneficiary`, `TaxPreparer`, `Auditor` |
| POST | `/trusts/{trustId}/distributions/{distributionId}/approve` | Approve a PROPOSED Distribution. | `Trustee` |
| POST | `/trusts/{trustId}/distributions/{distributionId}/execute` | Execute an APPROVED Distribution. | `Trustee` |
| POST | `/trusts/{trustId}/distributions/{distributionId}/reject` | Reject a PROPOSED or APPROVED Distribution. | `Trustee` |
| POST | `/trusts/{trustId}/tax-years` | Open a TaxYear for a specified calendar year (idempotent on the (trust, calendar_year) pair). | `Trustee`, `TaxPreparer` |
| GET | `/trusts/{trustId}/tax-years/{taxYearId}` | Read a TaxYear. | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor` |
| POST | `/trusts/{trustId}/tax-years/{taxYearId}/begin-close` | Begin closing the TaxYear (OPEN → CLOSING); auto-rejects PROPOSED Distributions in the year. | `TaxPreparer` |
| POST | `/trusts/{trustId}/tax-years/{taxYearId}/finalize` | Finalize the TaxYear (CLOSING → CLOSED, or AMENDED → CLOSED). | `TaxPreparer` |
| POST | `/trusts/{trustId}/tax-years/{taxYearId}/amend` | Reopen a CLOSED TaxYear for K-1 corrections (CLOSED → AMENDED). | `TaxPreparer` |
| GET | `/trusts/{trustId}/tax-years/{taxYearId}/k1s` | List K-1 records for the TaxYear (filters `status`, `beneficiary_id`). | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor`, `Beneficiary` |
| GET | `/trusts/{trustId}/tax-years/{taxYearId}/k1s/{k1Id}` | Read a single K-1. | `Grantor`, `Trustee`, `TaxPreparer`, `Auditor`, `Beneficiary` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BENEFICIARY_TERMINATED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_IRREVOCABLE_CANNOT_REVOKE` | 403 |
| `ERR_TAX_YEAR_CLOSED` | 409 |
| `ERR_TAX_YEAR_NOT_OPEN` | 409 |
| `ERR_TAX_YEAR_NOT_ENDED` | 409 |
| `ERR_TAX_YEAR_CLOSING_IN_PROGRESS` | 409 |
| `ERR_TAX_YEAR_NOT_CLOSED` | 409 |
| `ERR_NEWER_YEAR_CLOSED` | 409 |
| `ERR_NO_PRIMARY_TRUSTEE` | 409 |
| `ERR_NO_BENEFICIARY` | 409 |
| `ERR_NO_OPEN_TAX_YEAR` | 409 |
| `ERR_GRANTOR_STATUS_INCOMPATIBLE` | 422 |
| `ERR_INSUFFICIENT_PRINCIPAL` | 409 |
| `ERR_INSUFFICIENT_INCOME` | 409 |
| `ERR_INSUFFICIENT_INCOME_FOR_TAX` | 409 |
| `ERR_HAS_APPROVED_DISTRIBUTIONS` | 409 |
| `ERR_HAS_PENDING_DISTRIBUTIONS` | 409 |
| `ERR_HAS_UNDISTRIBUTED_ASSETS` | 409 |
| `ERR_NONZERO_BALANCE` | 409 |
| `ERR_TRUST_NOT_ACTIVE` | 409 |
| `ERR_K1_STALE_REFERENCE` | 409 |
| `ERR_BAD_REQUEST` | 400 |
