# Sales Tax Nexus API — Product Requirements Document

## 1. Introduction

Multi-state sales tax compliance is one of the most error-prone obligations a modern seller carries. A single sale can be taxed at the buyer's location or the seller's, can be fully taxable, reduced, or exempt depending on the product, and can shift the seller's collection duty onto a marketplace platform entirely. On top of per-transaction arithmetic, every state imposes an *economic nexus* threshold — a level of cumulative sales or transaction count at or above which the seller becomes legally obligated to register and collect — and these accumulators must move forward as sales settle and backward as sales are voided.

This API provides the system of record for that compliance lifecycle. It models tax jurisdictions and their rates, the taxability of product categories, sellers and their physical origin, customer exemption certificates, marketplace facilitators, and the transactions that flow through them. As transactions settle, the system resolves sourcing, computes per-line tax, decides who is responsible for remittance, and accrues nexus toward each state's threshold. Periodically, a tax return is drafted, independently approved by a different person than the one who prepared it, filed, and finally remitted. Throughout, an append-only audit trail records every consequential action so that the entire posture can be reconstructed during a state audit.

The design goal is exactness. Tax figures are money, nexus postures determine legal obligations, and the segregation of duties between preparer and approver is a control that auditors verify. The remainder of this document specifies the structural contract that every client depends on (Section 2) and the business rules that govern each workflow (Section 3), followed by the endpoint and error-code references (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and structural contracts that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `PlatformAdmin`, `Seller`, `TaxPreparer`, `TaxApprover`, and `Auditor`.

A `PlatformAdmin` is the system operator who configures jurisdictions, product taxability, facilitators, seller accounts, and the test clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

A `Seller` is the taxpayer who records sales, files certificates, registers for nexus, and accrues use tax. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` compare the resource's `seller_id` to `X-User-ID`.

A `TaxPreparer` drafts and reopens tax returns and may accrue use tax, but may never approve or file a return — that separation is the core segregation-of-duties control. A `TaxApprover` accepts, rejects, files, and remits returns but may never prepare one, and must be a different person than the return's preparer. An `Auditor` provides read-only oversight plus the independent audit dimension (flagging and clearing transactions) and access to the audit log. When `X-User-Role` is `TaxPreparer`, `TaxApprover`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `prepared_by` or `approved_by` on a `TaxReturn`, or as `actor_id` on an `AuditLogEntry`, where a workflow writes it) but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values run from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that begins at its initial value and increases by exactly one on every mutation of the resource; it underpins the optimistic-concurrency mechanism described in §2.8.

Two entities are deliberately lighter. A `TransactionLineItem` and an `AuditLogEntry` carry only `id` and `created_at` — they have neither an `updated_at` nor a `version`, because a line item is fixed once attached to a transaction and an audit entry is append-only and never altered. All other entities carry the full `id`, `created_at`, `updated_at`, and `version` set.

Whenever a derived or system field on a resource changes — for example when a transaction's settlement fields are populated, when a nexus profile's accumulators move, or when a return's `tax_due` is computed — that change is a mutation of the owning resource: it refreshes `updated_at` and increments `version` by one.

### 2.5. Nexus Posture and the Economic-Nexus Threshold Principle

Each `NexusProfile` is a per-state accumulator for one seller. It tracks `cumulative_taxable_sales` and `cumulative_txn_count`, and from these derives a `nexus_status` that reflects the seller's legal posture in that state. A freshly opened profile starts at `NO_NEXUS` with both accumulators at zero and a null `registered_at`.

The posture is recomputed from the profile's own accumulators and its jurisdiction's thresholds every time the accumulators move. The sales test is met when `cumulative_taxable_sales` is greater than or equal to the jurisdiction's `economic_nexus_sales_threshold`; this comparison is inclusive, so reaching the threshold exactly counts as met. The count test is met only when the jurisdiction's `economic_nexus_txn_threshold` is greater than zero and `cumulative_txn_count` is greater than or equal to that threshold; a threshold of zero disables the count test entirely. The threshold is considered crossed when either the sales test or the count test is met.

The posture itself is determined as follows: if the profile is already `REGISTERED`, it stays `REGISTERED` regardless of where the accumulators stand — registration is sticky and never reverts. Otherwise, if the threshold is crossed the posture is `THRESHOLD_MET`, and if it is not crossed the posture is `NO_NEXUS`. The amounts driving the sales test are held to two decimal places, but the threshold comparisons themselves are exact.

### 2.6. Sourcing, Rates, and Monetary Precision

Every jurisdiction declares a `combined_rate`, which is a convenience value equal to its `state_rate` plus its `local_rate` and is recomputed whenever either rate changes. A separate `reduced_rate` applies to categories taxed at a reduced level. All three rates are stored as decimal fractions (for example, 0.0725 represents 7.25%) and preserve their input precision; they are not rounded to two places.

All money amounts — taxable subtotals, per-line tax, transaction tax totals, accrued use tax, return amounts due, and remittance amounts — are computed and stored to exactly two decimal places using the round-half-up method. Where a calculation specifies a particular order of rounding (notably the per-line round-then-sum rule in §3.4), that order is part of the contract and must be honored precisely.

### 2.7. The Audit Trail

The system maintains an append-only audit trail. Consequential state transitions — settling, voiding, flagging, and clearing transactions; revoking and reinstating certificates; registering for nexus; and accepting, rejecting, reopening, filing, and remitting returns — each append an `AuditLogEntry`. Each entry records the `seller_id` whose activity it concerns, the `subject_entity` (the entity type involved, such as Transaction, TaxReturn, or ExemptionCertificate), the `subject_id` of the affected record, and the `action` performed (for example SETTLE, VOID, FILE_RETURN, FLAG, or REVOKE_CERTIFICATE). The server itself stamps the `actor_role` and `actor_id` from the request's `X-User-Role` and `X-User-ID` headers. Audit entries are immutable once written and are visible only to the `Auditor` and `PlatformAdmin` roles.

### 2.8. Optimistic Concurrency Control on Remittance

Most mutations in this system are guarded by their own state preconditions, but remittance carries an explicit optimistic-concurrency check because it is the act that consumes a return's FILED state. Creating a remittance payment requires the client to supply `expected_tax_return_version` carrying the `version` of the target `TaxReturn` as the client last observed it. If `expected_tax_return_version` does not equal the return's current `version` — meaning another writer has advanced the return since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from remitting against a return whose state it has not actually seen; for instance, a second remittance attempt that carries a version captured before a prior payment moved the return to `REMITTED` is rejected on this check. Endpoints other than remittance creation do not take a version field.

### 2.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the failure a client sees is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of any path-referenced resource (`ERR_NOT_FOUND`), then existence of any body-referenced foreign key such as `jurisdiction_id`, `facilitator_id`, `transaction_id`, `tax_return_id`, or `seller_id` (`ERR_REFERENCE_NOT_FOUND`), then well-formedness of the request body including required fields, types, enum membership, and numeric bounds (`ERR_INVALID_REQUEST`), then uniqueness constraints (`ERR_DUPLICATE_RESOURCE`), then interval well-formedness (`ERR_INVALID_INTERVAL`), then the temporal-overlap checks for certificates and return periods (`ERR_CERTIFICATE_OVERLAP` and `ERR_RETURN_PERIOD_OVERLAP`), and finally the state and business-rule checks particular to each operation. The operation-specific rules — segregation of duties, the nexus-registration precondition, the filing lock, the seller-suspension gate, amount matching, and the stale-version check — are described alongside the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Configuring Jurisdictions, Categories, Facilitators, and Sellers

Before any sale can be recorded, a `PlatformAdmin` lays down the reference data. A tax jurisdiction is created with its two-letter `state_code` (uppercase A–Z, exactly two characters, and unique across all jurisdictions), its `sourcing_rule` of either `ORIGIN` or `DESTINATION`, and its `state_rate`. A jurisdiction may also carry a `local_rate` and a `reduced_rate`, each of which defaults to zero when omitted; the `state_rate` must be between 0 and 0.25 inclusive, the `local_rate` between 0 and 0.10 inclusive, and the `reduced_rate` between 0 and 0.25 inclusive. The thresholds are set with `economic_nexus_sales_threshold`, which must be strictly greater than zero, and an optional `economic_nexus_txn_threshold`, which must be at least zero and defaults to zero (disabling the count test). On creation the system computes `combined_rate` as the sum of `state_rate` and `local_rate`. Attempting to create a second jurisdiction with an already-used `state_code` is rejected with `ERR_DUPLICATE_RESOURCE`.

A product category row records how one category is taxed in one state. It is created with a `jurisdiction_id` naming the state, a `category_code` such as TANGIBLE, GROCERY, or DIGITAL, and a `taxability` of `FULL`, `REDUCED`, or `EXEMPT`. The pair of `jurisdiction_id` and `category_code` must be unique; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`.

A marketplace facilitator — a platform that collects and remits on a seller's behalf — is registered with its `name` and a non-empty array of `collecting_state_codes`, each element being a valid two-letter uppercase state code. These are the states in which the facilitator assumes collection-and-remittance duty for sales it facilitates.

A seller is registered with a `legal_name` and an `origin_state_code` (a valid two-letter uppercase code naming the seller's physical/origin state, used when a destination jurisdiction sources to origin). A new seller's `status` begins `ACTIVE`. A `PlatformAdmin` may later suspend a seller, moving `status` to `SUSPENDED`; a suspended seller is blocked from settling transactions, as described in §3.4.

### 3.2. Opening and Registering a Nexus Profile

A seller (or a `PlatformAdmin` acting on their behalf) opens a nexus accumulator for a particular state by creating a `NexusProfile` from a `seller_id` and a `jurisdiction_id`. The pair must be unique per seller and state; a second profile for the same `seller_id` and `jurisdiction_id` is rejected with `ERR_DUPLICATE_RESOURCE`. A new profile initializes `cumulative_taxable_sales` to zero, `cumulative_txn_count` to zero, and `nexus_status` to `NO_NEXUS`.

The accumulators move only through transaction settlement and voiding (§3.4), and the posture is recomputed by the rule in §2.5 each time they move. As long as the profile is still `THRESHOLD_MET`, a de-accrual that drops both accumulators back below their thresholds steps the posture from `THRESHOLD_MET` back to `NO_NEXUS`. Once a seller registers, however, the posture is sticky and a later void cannot pull it down.

Registration is the seller's own action and is available only once the threshold has been met. A seller registering for collection requires the profile to be in `THRESHOLD_MET`; attempting it from any other posture is rejected with `ERR_INVALID_STATE`. On success the posture advances `THRESHOLD_MET → REGISTERED`, `registered_at` is set to the current clock, an `AuditLogEntry` recording the registration is appended, and the profile's `version` increments by one. Because acceptance of a return requires a `REGISTERED` profile (§3.6), registration is a cross-entity precondition that itself depends on transactions having accrued enough to cross the threshold.

### 3.3. Recording a Sale: Transactions and Line Items

A seller records a sale by first creating a `Transaction` in the `PENDING` settlement state. Creation takes the `seller_id` making the sale, the `jurisdiction_id` of the buyer's destination state, the buyer's opaque `customer_ref`, an optional `facilitator_id` (null when the sale is not marketplace-facilitated), and an optional `customer_exempt_requested` flag that defaults to false. A new transaction's `settlement_status` is `PENDING` and its `audit_status` is `UNREVIEWED`; its `tax_return_id` is null. All of the computed tax fields remain unpopulated until settlement.

Line items are added to a `PENDING` transaction one at a time. Each line carries the `transaction_id` of its parent sale, a `category_code` identifying the product, a `quantity` of at least one unit, and a `unit_price` strictly greater than zero stated to two decimal places. A line's `line_taxability` and `line_tax` are computed fields, left blank until the parent transaction settles. A transaction must have at least one line item before it can be settled.

The buyer's `customer_exempt_requested` flag is only an assertion; it is honored only if, at settlement time, an `ACTIVE` certificate actually matches the line, as described next.

### 3.4. Settling a Transaction: Sourcing, Taxability, and Tax Computation

Settlement is the central calculation of the system, and it is the seller's action. A transaction may be settled only from the `PENDING` settlement state; settling from any other state, or settling a transaction that has no line items, is rejected with `ERR_INVALID_STATE`. Settlement is also blocked for a suspended seller: if the selling `Seller` has `status` of `SUSPENDED`, the attempt is rejected with `ERR_SELLER_SUSPENDED`. On success the settlement advances `PENDING → SETTLED`, appends an `AuditLogEntry` recording the settle, and increments the transaction's `version` by one.

**Resolving sourcing.** The first step is to decide which state's rate applies and which state's nexus is affected, recorded in `sourcing_used`. The destination jurisdiction is the one named by the transaction's `jurisdiction_id`. If that jurisdiction's `sourcing_rule` is `DESTINATION`, then `sourcing_used` is `DESTINATION`, the rate applied is the destination jurisdiction's `combined_rate`, and nexus accrues to the destination state. If instead the destination jurisdiction's `sourcing_rule` is `ORIGIN`, then `sourcing_used` is `ORIGIN`, the rate applied is the `combined_rate` of the jurisdiction whose `state_code` equals the seller's `origin_state_code`, and nexus accrues to that origin state. The rate chosen this way is recorded on the transaction as `applied_rate`. The state to which sourcing resolves — destination or origin — is hereafter the "sourced state," and it is the state used for both product-category lookup and nexus accrual. Because the same line items sourced to origin versus destination can pull a different rate and touch a different profile, sourcing must be resolved before any per-line tax is computed.

**Resolving each line's taxability.** For each line item, in the order the lines were added, the system resolves `line_taxability`. It first looks up the product category for the sourced state and the line's `category_code`. A line is treated as exempt when either of two conditions holds: the matching product category's `taxability` is `EXEMPT`, or the buyer has a valid certificate. A certificate exempts the line only when the transaction's `customer_exempt_requested` flag is true and there exists an `ExemptionCertificate` that is `ACTIVE`, belongs to the same `seller_id` as the transaction, is filed for the sourced state, has a `customer_ref` equal to the transaction's `customer_ref`, has an `exempt_category_code` equal to the line's `category_code`, and whose validity window contains the current clock — that is, the clock is at or after `valid_from` and strictly before `valid_to`. When a line is exempt by either route, its `line_taxability` is `EXEMPT` and its `line_tax` is 0.00, and the line contributes nothing to the taxable subtotal. Otherwise, if the category's `taxability` is `REDUCED`, the line's `line_taxability` is `REDUCED` and its `line_tax` is the line's `quantity` multiplied by its `unit_price` multiplied by the sourced state's `reduced_rate`, rounded half-up to two decimal places. In all remaining cases the line's `line_taxability` is `FULL` and its `line_tax` is the line's `quantity` multiplied by its `unit_price` multiplied by the `applied_rate`, rounded half-up to two decimal places.

**Aggregating the transaction.** The transaction's `taxable_subtotal` is the sum, over every line whose resolved `line_taxability` is not `EXEMPT`, of that line's `quantity` multiplied by its `unit_price`, with the total rounded half-up to two decimal places. The transaction's `tax_collected` is the sum of every line's already-rounded `line_tax`. This ordering is mandatory: each line's tax is rounded to two decimal places first, and only then are the per-line amounts summed — round-then-sum, never sum-then-round.

**Lazy certificate expiry.** Certificate validity is evaluated at settlement against the current clock. A certificate that is `ACTIVE` but whose `valid_to` is at or before the current clock has effectively expired: settlement treats the matching line as non-exempt. (No separate endpoint moves a certificate to `EXPIRED`; expiry is observed lazily at settlement time.)

### 3.5. Remittance Responsibility and Nexus Accrual

As part of settlement the system fixes `remittance_responsibility`, which decides whether the seller or a marketplace owes the tax. If the transaction has a `facilitator_id` set and the destination state's `state_code` appears in that facilitator's `collecting_state_codes`, then `remittance_responsibility` is `MARKETPLACE`: the facilitator collects and remits, the seller's nexus is not accrued, and the sale is excluded from the seller's return even though `tax_collected` is still computed and recorded on the transaction. In every other case — no facilitator, or a facilitator that does not collect in the destination state — `remittance_responsibility` is `SELLER`: the seller owes remittance and nexus accrues.

When and only when `remittance_responsibility` resolves to `SELLER`, settlement accrues nexus to the sourced state's profile for this seller: the profile's `cumulative_taxable_sales` is increased by this transaction's `taxable_subtotal` and its `cumulative_txn_count` is increased by one, after which `nexus_status` is recomputed by the rule in §2.5. If that recomputation flips the posture `NO_NEXUS → THRESHOLD_MET` within the same settle call, that flip is the cascade triggered by the sale. The profile mutation refreshes its `updated_at` and increments its `version`.

A settled transaction may later be voided by the seller, but only while it is still `SETTLED` and has not been swept into a return. Voiding from any state other than `SETTLED` is rejected with `ERR_INVALID_STATE`, and voiding a transaction whose `tax_return_id` is already set (it has been swept into a return) is rejected with `ERR_TRANSACTION_LOCKED`. A successful void advances `SETTLED → VOIDED`, appends an `AuditLogEntry` recording the void, and increments the transaction's `version`. Voiding is the compensating action for settlement: when the voided transaction was `SELLER`-responsible, the system decreases the sourced-state profile's `cumulative_taxable_sales` by that transaction's `taxable_subtotal` and decreases `cumulative_txn_count` by one, then recomputes `nexus_status`. This de-accrual may step the posture `THRESHOLD_MET → NO_NEXUS`, but it can never pull it below `REGISTERED` — once a seller has registered, the posture is sticky and a void leaves it `REGISTERED`. The conserved quantity across a settle/void pair is the profile's `cumulative_taxable_sales`.

### 3.6. The Independent Audit Dimension

A transaction carries a second, independent state dimension recorded in `audit_status`, governed entirely by the `Auditor` role and unaffected by where the transaction stands in settlement. A new transaction is `UNREVIEWED`. An auditor may flag a transaction, advancing `UNREVIEWED → FLAGGED`; this is permitted only from `UNREVIEWED` and is otherwise rejected with `ERR_INVALID_STATE`. An auditor may then clear a flagged transaction, advancing `FLAGGED → CLEARED`; this is permitted only from `FLAGGED` and is otherwise rejected with `ERR_INVALID_STATE`. Flagging is allowed whether the transaction is still `PENDING` or already `SETTLED`, because the audit dimension evolves independently of settlement. Each flag appends an `AuditLogEntry` recording the flag and each clear appends one recording the clear, and each action increments the transaction's `version` by one.

### 3.7. Exemption Certificates

A seller files a customer's exemption certificate by providing a `seller_id`, a `jurisdiction_id` naming the state in which the certificate exempts purchases, the buyer's `customer_ref`, the `exempt_category_code` the certificate covers, a `valid_from`, and a `valid_to`. The validity window is half-open and must be well-formed: `valid_to` must be strictly after `valid_from`, and a window that is not is rejected with `ERR_INVALID_INTERVAL`. A new certificate begins `ACTIVE`.

Certificates for the same buyer, state, and category may not overlap in time. When a new certificate is filed, the system rejects it with `ERR_CERTIFICATE_OVERLAP` if its half-open window from `valid_from` up to but not including `valid_to` intersects the half-open window of any existing `ACTIVE` certificate sharing the same `seller_id`, `jurisdiction_id`, `customer_ref`, and `exempt_category_code`. Because the interval is half-open, touching endpoints do not collide: an existing certificate whose `valid_to` exactly equals the new certificate's `valid_from` is allowed.

A seller may revoke an `ACTIVE` certificate, advancing its `status` `ACTIVE → REVOKED`; this is permitted only from `ACTIVE` and is otherwise rejected with `ERR_INVALID_STATE`. A revoked certificate no longer exempts future settlements, though transactions already settled against it are unaffected. A seller may reinstate a `REVOKED` certificate, advancing its `status` `REVOKED → ACTIVE`, but only while the certificate is still within its window — the current clock must be strictly before `valid_to`. Reinstating from any state other than `REVOKED` is rejected with `ERR_INVALID_STATE`, and reinstating a certificate whose window has already ended (the current clock is at or after `valid_to`) is rejected with `ERR_VALIDATION_FAILED`. Each revoke appends an `AuditLogEntry` recording the certificate revocation and each reinstatement appends one recording the reinstatement, and each action increments the certificate's `version`. Independently of these manual transitions, a certificate is treated as expired at settlement once the current clock reaches or passes its `valid_to`, as described in §3.4; this is the certificate's terminal `EXPIRED` outcome and has no dedicated endpoint.

### 3.8. Self-Assessed Use Tax

When a seller makes an untaxed purchase on which use tax must be self-assessed, a seller or a `TaxPreparer` records a `UseTaxAccrual` from a `seller_id`, a `jurisdiction_id` naming the state whose rate applies, and a `purchase_amount` strictly greater than zero stated to two decimal places. The system computes `accrued_use_tax` as the `purchase_amount` multiplied by the destination jurisdiction's `combined_rate`, rounded half-up to two decimal places. A new accrual's `status` is `ACCRUED`, and its `tax_return_id` is null until the accrual is swept into an accepted return. When swept, its `status` becomes `INCLUDED_IN_RETURN`.

### 3.9. Preparing, Approving, and Reopening a Return

A `TaxPreparer` opens a tax return for one state and one period by supplying a `seller_id`, a `jurisdiction_id`, a `period_start`, and a `period_end`. The period is well-formed only when `period_end` is strictly after `period_start`; otherwise the create is rejected with `ERR_INVALID_INTERVAL`. The server records the preparer's identity in `prepared_by` from `X-User-ID` and starts the return in `DRAFT` with `approved_by` null and `tax_due` at zero.

Return periods for a given seller and state may not overlap or even touch. A new return is rejected with `ERR_RETURN_PERIOD_OVERLAP` if its closed period — from `period_start` through `period_end` inclusive — intersects or touches the closed period of any existing return for the same `seller_id` and `jurisdiction_id` that is not `REJECTED` (that is, any return whose `status` is `DRAFT`, `ACCEPTED`, `FILED`, or `REMITTED`). Because this interval is treated as closed and adjacency is forbidden, shared endpoints do collide: an existing return whose `period_end` exactly equals the new return's `period_start` is rejected.

Acceptance is a `TaxApprover`'s action and the segregation-of-duties control sits here. A return may be accepted only from `DRAFT`; otherwise the attempt is rejected with `ERR_INVALID_STATE`. The accepting approver's `X-User-ID` must differ from the return's `prepared_by`; if the same user who prepared the return tries to accept it, the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. Acceptance further requires that the seller's `NexusProfile` for this state be `REGISTERED`; if it is not, the attempt is rejected with `ERR_NEXUS_NOT_REGISTERED`. When all preconditions hold, acceptance sweeps the period's activity, computes `tax_due`, records the approver in `approved_by`, advances `DRAFT → ACCEPTED`, appends an `AuditLogEntry` recording the acceptance, and increments the return's `version`.

The sweep at acceptance gathers two sets. The first is every transaction for this `seller_id` whose nexus accrued to this return's `jurisdiction_id`, whose `settlement_status` is `SETTLED` (not voided), whose `remittance_responsibility` is `SELLER`, and whose `created_at` falls in the period — at or after `period_start` and strictly before `period_end`; each such transaction has its `tax_return_id` set to this return. The second is every `UseTaxAccrual` for this `seller_id` and `jurisdiction_id` whose `status` is `ACCRUED` and whose `created_at` falls in that same half-open period; each such accrual has its `tax_return_id` set and its `status` advanced to `INCLUDED_IN_RETURN`. The return's `tax_due` is then the sum of every swept transaction's `tax_collected` plus the sum of every swept accrual's `accrued_use_tax`, rounded half-up to two decimal places. When there are no use-tax accruals in the period, `tax_due` is just the swept transactions' `tax_collected`; when accruals exist, their `accrued_use_tax` is added on top. Voided transactions and `MARKETPLACE`-responsible transactions are never swept and never contribute to `tax_due`.

A `TaxApprover` may instead reject a `DRAFT` return. Rejection is permitted only from `DRAFT` and is otherwise rejected with `ERR_INVALID_STATE`, and it too enforces segregation of duties: an approver whose `X-User-ID` equals the return's `prepared_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful rejection advances `DRAFT → REJECTED`, appends an `AuditLogEntry` recording the rejection, and increments the return's `version`. A rejected return is not a dead end: a `TaxPreparer` may reopen it, advancing `REJECTED → DRAFT` so the return can be corrected and resubmitted. Reopening is permitted only from `REJECTED` and is otherwise rejected with `ERR_INVALID_STATE`; it appends an `AuditLogEntry` recording the reopen and increments the return's `version`.

### 3.10. Filing and Remitting a Return

Once a return is `ACCEPTED`, a `TaxApprover` files it, advancing `ACCEPTED → FILED`. Filing is permitted only from `ACCEPTED` and is otherwise rejected with `ERR_INVALID_STATE`; it appends an `AuditLogEntry` recording the filing and increments the return's `version`. The transactions swept at acceptance remain locked through filing — they were locked the moment their `tax_return_id` was set, which is why a swept transaction can no longer be voided.

Remittance settles the return by paying it in full and is also a `TaxApprover`'s action. A remittance payment is created against a `FILED` return by supplying the `tax_return_id`, an `amount`, and the `expected_tax_return_version` described in §2.8. The target return must be `FILED`; otherwise the create is rejected with `ERR_INVALID_STATE`. The `expected_tax_return_version` must equal the return's current `version`, or the create is rejected with `ERR_STALE_VERSION`. The `amount` must equal the return's `tax_due` exactly — a partial or excess payment is rejected with `ERR_AMOUNT_MISMATCH` — and the `amount` itself must be strictly greater than zero. On success the system creates a `RemittancePayment` whose `status` is `APPLIED`, advances the return `FILED → REMITTED`, appends an `AuditLogEntry` recording the remittance, and increments the return's `version`. `REMITTED` is the terminal state of a return.

### 3.11. The Test Clock

Because certificate validity windows and return periods are evaluated against "now," a `PlatformAdmin` may set the server's logical UTC clock for test-driving purposes by supplying a `to_iso8601` instant. Subsequent certificate-window checks, lazy expiry at settlement, and period evaluation all read this clock as the current time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or transition an existing resource, including the action endpoints that drive state machines, return `200 OK`. The remittance-payment endpoint creates a new `RemittancePayment` resource and therefore returns `201 Created`. List and fetch endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tax-jurisdictions` | Create a state tax jurisdiction | PlatformAdmin |
| GET | `/tax-jurisdictions/{id}` | Fetch a jurisdiction | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| GET | `/tax-jurisdictions` | List jurisdictions | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| POST | `/product-categories` | Declare a category's taxability in a jurisdiction | PlatformAdmin |
| GET | `/product-categories/{id}` | Fetch a product-category row | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| GET | `/product-categories` | List product-category rows | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| POST | `/sellers` | Register a seller | PlatformAdmin |
| GET | `/sellers/{id}` | Fetch a seller | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| GET | `/sellers` | List sellers | PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/sellers/{id}/suspend` | Suspend a seller account | PlatformAdmin |
| POST | `/marketplace-facilitators` | Register a marketplace facilitator | PlatformAdmin |
| GET | `/marketplace-facilitators/{id}` | Fetch a facilitator | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| GET | `/marketplace-facilitators` | List facilitators | PlatformAdmin, Seller, TaxPreparer, TaxApprover, Auditor |
| POST | `/nexus-profiles` | Open a nexus accumulator for a seller | Seller, PlatformAdmin |
| GET | `/nexus-profiles/{id}` | Fetch a nexus profile | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/nexus-profiles` | List nexus profiles | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/nexus-profiles/{id}/register` | Register the seller for collection in this state | Seller |
| POST | `/exemption-certificates` | File a customer exemption certificate | Seller |
| GET | `/exemption-certificates/{id}` | Fetch an exemption certificate | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/exemption-certificates` | List exemption certificates | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/exemption-certificates/{id}/revoke` | Revoke an active certificate | Seller |
| POST | `/exemption-certificates/{id}/reinstate` | Reinstate a revoked certificate within its window | Seller |
| POST | `/transactions` | Create a PENDING transaction | Seller |
| GET | `/transactions/{id}` | Fetch a transaction | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/transactions` | List transactions | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/line-items` | Add a line item to a PENDING transaction | Seller |
| GET | `/line-items/{id}` | Fetch a line item | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/line-items` | List line items | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/transactions/{id}/settle` | Settle a transaction | Seller |
| POST | `/transactions/{id}/void` | Void a settled, not-yet-swept transaction | Seller |
| POST | `/transactions/{id}/flag` | Flag a transaction (audit dimension) | Auditor |
| POST | `/transactions/{id}/clear` | Clear a flagged transaction (audit dimension) | Auditor |
| POST | `/use-tax-accruals` | Self-assess use tax on an untaxed purchase | Seller, TaxPreparer |
| GET | `/use-tax-accruals/{id}` | Fetch a use-tax accrual | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/use-tax-accruals` | List use-tax accruals | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/tax-returns` | Create a DRAFT tax return | TaxPreparer |
| GET | `/tax-returns/{id}` | Fetch a tax return | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/tax-returns` | List tax returns | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| POST | `/tax-returns/{id}/accept` | Accept a DRAFT return; sweep and compute tax due | TaxApprover |
| POST | `/tax-returns/{id}/reject` | Reject a DRAFT return | TaxApprover |
| POST | `/tax-returns/{id}/reopen` | Reopen a REJECTED return to DRAFT | TaxPreparer |
| POST | `/tax-returns/{id}/file` | File an ACCEPTED return | TaxApprover |
| POST | `/remittance-payments` | Remit a FILED return in full (OCC-guarded) | TaxApprover |
| GET | `/remittance-payments/{id}` | Fetch a remittance payment | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/remittance-payments` | List remittance payments | Seller, PlatformAdmin, TaxPreparer, TaxApprover, Auditor |
| GET | `/audit-log-entries/{id}` | Fetch a single audit-log entry | Auditor, PlatformAdmin |
| GET | `/audit-log-entries` | List audit-trail entries | Auditor, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_CERTIFICATE_OVERLAP` | 409 Conflict |
| `ERR_RETURN_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NEXUS_NOT_REGISTERED` | 409 Conflict |
| `ERR_TRANSACTION_LOCKED` | 409 Conflict |
| `ERR_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SELLER_SUSPENDED` | 409 Conflict |
| `ERR_VALIDATION_FAILED` | 422 Unprocessable Entity |
