# Municipal Sales/Use Tax Filing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Municipal Sales/Use & Business-Activity Tax Filing API, the system of record a municipality uses to register taxpayers, accept periodic tax returns, collect remittances, run audits, issue assessments, adjudicate appeals, and process refunds. The domain is fundamentally one of ledger reconciliation: every filed return, every issued assessment, every applied payment, and every approved refund moves a taxpayer's running account balance, and that balance must stay consistent under a stream of forward actions and their compensating reversals.

The hard problems this API must solve are not CRUD problems. The same taxable base yields a different amount owed depending on which penalty-and-interest algorithm applies (an auditor-found deficiency is penalized differently from a self-reported late filing) and which refund-interest algorithm applies (interest that begins only after a statutory grace period versus interest that accrues from the date money was overpaid). Rounding order matters — tax is rounded on each return line before the lines are summed, never after. And because a taxpayer's balance is derived on read from four underlying collections, forward operations must be paired precisely with their compensating operations: amending a return un-applies the payments that were sitting against it, and allowing an appeal abates the assessment that was inflating the balance. When these pairs are implemented faithfully, the conserved ledger identities hold; when they are not, money silently leaks.

The intended readers are the engineers who will build the service. Domain intent is described first and the mechanical contract second; where a rule has a precise numeric or ordering requirement, that precision is stated without hedging.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than public taxpayer registration must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming its operational capacity. When either header is missing on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes five roles, spelled exactly as follows:

- `Anonymous` — an unauthenticated public caller. Its identity is opaque: on the single operation it may perform (public taxpayer registration), `X-User-ID` is not compared to any persisted entity and need not be supplied.
- `Taxpayer` — a registered business acting on its own resources. This role is entity-backed: when `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the acting `Taxpayer`. Ownership checks on any resource that references a taxpayer compare that resource's `taxpayer_id` (or, for an appeal, the `taxpayer_id` of the assessment it contests) to `X-User-ID`.
- `TaxAuditor` — a municipal auditor who opens and closes audits and issues assessments. Its identity is opaque: `X-User-ID` is an operator identifier not tied to any persisted entity. The server records it where a transition writes it — for example as `opened_by_user_id` on an `Audit` or `issued_by_user_id` on an `Assessment` — but does not compare it to any entity's `id`.
- `AppealsOfficer` — an independent officer who reviews and decides appeals. Its identity is opaque; the server records the deciding officer as `decided_by_user_id` on the `Appeal` but does not tie `X-User-ID` to any entity's `id`.
- `TaxAdmin` — an administrative operator who manages jurisdictions, account lifecycle, refunds, and the logical clock. Its identity is opaque.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties and Precision

Every primary resource — `Taxpayer`, `Jurisdiction`, `TaxReturn`, `ExemptionCertificate`, `Remittance`, `Audit`, `Assessment`, `Appeal`, and `RefundClaim` — carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp (ISO 8601 UTC, three fractional digits) fixed at creation, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at 1 and increments by one on every mutation. All of these resources carry the full set; none of them is an immutable value object, so `updated_at` and `version` are always present.

All monetary quantities are integer cents. Rate values are basis points: a jurisdiction storing `rate_bps` of 850 represents 8.50%, so a per-line tax is the taxable cents multiplied by `rate_bps` and divided by 10000. Every rounding step in this system uses the round-half-up convention to the nearest whole cent. Where a calculation both rounds and sums, the order in which those two steps happen is pinned by the specific rule in §3 and must not be reordered.

### 2.5. Logical Clock

The service runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until an administrator advances it, every timestamp the server stamps — `created_at`, `filed_at`, `received_at`, `issued_at`, `approved_at`, `closed_at`, `decided_at`, `activated_at` — reads from this logical instant and never falls back to the host wall clock. A `TaxAdmin` advances the clock by supplying a `to_iso8601` instant; every timeliness comparison in the system (vendor-discount timeliness, appeal windows, months-late, refund day counts) is evaluated against the logical clock in effect at the moment of the operation.

### 2.6. The Account Balance Ledger

A taxpayer's `account_balance_cents` is never stored as a mutable field; it is derived on read every time a taxpayer is fetched and recomputed after any mutation to that taxpayer's returns, assessments, remittances, or refunds. A positive balance means money is owed to the municipality. The balance is the sum of four signed contributions:

- **plus** the `net_return_due_cents` of every `TaxReturn` owned by the taxpayer whose `status` is either `FILED` or `ASSESSED` (returns in `DRAFT` or `AMENDING` contribute nothing);
- **plus** the `total_due_cents` of every `Assessment` owned by the taxpayer whose `status` is either `ISSUED` or `AFFIRMED` (an `ABATED` assessment contributes nothing);
- **minus** the `applied_amount_cents` of every `Remittance` owned by the taxpayer, regardless of which return it is applied to;
- **minus** the `refund_total_cents` of every `RefundClaim` owned by the taxpayer whose `status` is `APPROVED` (claims in any other status contribute nothing).

Because the balance is a pure function of these four collections under those exact status filters, forward and compensating actions stay conserved automatically: abating an assessment removes its `total_due_cents` from the second term, so the balance falls by exactly that amount, and un-applying a remittance restores it to the third term. Every operation whose side effects mutate one of these collections must trigger a recomputation for the owning taxpayer.

### 2.7. Optimistic Concurrency on Returns

Two operations act on a `TaxReturn` through a version the client last observed, and both take an `expected_return_version` field carrying that observed `version`. Filing a refund claim is the primary case: a create-refund request must carry `expected_return_version` equal to the target return's current `version`. If another writer has advanced the return's `version` since the client last read it — for instance because a prior refund claim was filed and superseded, which itself advances the return — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from filing a claim against a return state it never observed. Amending a return likewise requires `expected_return_version` to match the return's current `version`, and a mismatch is rejected as a stale-version conflict with the same `ERR_STALE_VERSION` (HTTP 412). Endpoints that are not version-guarded take no version field.

### 2.8. Validation Ordering

When several checks guard one endpoint, they run in a fixed precedence so that the reported error is deterministic. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first, then authorization (`ERR_UNAUTHORIZED`, 403), then body well-formedness — required fields present, enum values in range, amounts strictly positive where required — reported as `ERR_VALIDATION` (400). Existence of every path id and referenced foreign-key id is checked next (the 404 family), resolving identifiers left-to-right along the path so that the first unresolved identifier is the one reported. State-precondition checks (the 409 family) follow existence. Business referential and temporal checks come after basic state checks, and the fiscal over-application check is evaluated last. Individual §3 workflows call out the specific ordering where two checks on the same endpoint could otherwise be reported in either order.

### 2.9. Nested Retrieval and List Filtering

For any path that names a sub-resource beneath a parent identifier, the parent identifier is validated before the child. Reads of a specific resource by id, and any operation that references a resource by a path id or a foreign-key id, return `404` with the resource-specific not-found code when the id does not resolve: an unresolved taxpayer yields `ERR_TAXPAYER_NOT_FOUND`, an unresolved return yields `ERR_RETURN_NOT_FOUND`, an unresolved remittance yields `ERR_REMITTANCE_NOT_FOUND`, an unresolved audit yields `ERR_AUDIT_NOT_FOUND`, an unresolved appeal yields `ERR_APPEAL_NOT_FOUND`, and an unresolved refund claim yields `ERR_REFUND_NOT_FOUND` (with `ERR_JURISDICTION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and `ERR_ASSESSMENT_NOT_FOUND` covering their respective resources). List endpoints accept reverse-reachability filters — for example returns may be filtered by `taxpayer_id`, `exemption_certificate_id`, `status`, or `period_key`; remittances by `taxpayer_id`, `applied_return_id`, or `remittance_type`; assessments by `taxpayer_id`, `audit_id`, `return_id`, or `status`; audits by `taxpayer_id`, `status`, or `audit_type`; appeals by `assessment_id` or `status`; refund claims by `taxpayer_id`, `return_id`, or `status`; certificates by `taxpayer_id` or `exemption_type`; taxpayers by `account_status`; and jurisdictions by `active`.

## 3. Business Logic & Workflows

### 3.1. Taxpayer Registration and Account Lifecycle

Registration is the only public entry point. Anyone may register a business by supplying its `legal_name`, its `entity_type` (one of `SOLE_PROP`, `LLC`, `CORP`, or `PARTNERSHIP`), a contact `email` that is unique per taxpayer, and a `filing_frequency` of `MONTHLY`, `QUARTERLY`, or `ANNUAL`. A newly registered taxpayer begins in `account_status` `PENDING` with `nexus_status` `NONE`, no `suspend_reason`, and no `activated_at`.

A `TaxAdmin` moves an account through its lifecycle. Activation takes a `PENDING` account to `ACTIVE`; this first activation stamps `activated_at` with the current clock and bumps the taxpayer's `version`. Activation is also the reinstatement path: a `SUSPENDED` account returns to `ACTIVE`, which clears its `suspend_reason` and bumps `version` (a reinstatement does not overwrite the original `activated_at`). Suspension takes an `ACTIVE` account to `SUSPENDED`, recording the free-text `suspend_reason` from the request and bumping `version`. Because an account can move `ACTIVE → SUSPENDED → ACTIVE` any number of times, the account state machine is cyclic and has no terminal state. Activation requires the account to currently be `PENDING` or `SUSPENDED`, and suspension requires it to be `ACTIVE`; the account's `nexus_status` flips to `ESTABLISHED` only through the audit path described in §3.5.

### 3.2. Jurisdictions and Exemption Certificates

Tax rates live on jurisdictions, which only a `TaxAdmin` may create. A jurisdiction carries a short `code` that must be unique across all jurisdictions (a duplicate is rejected with `ERR_DUPLICATE_JURISDICTION`), a human-readable `name`, a combined rate `rate_bps` that must be at least 0, and an `active` flag that defaults to true and governs whether the jurisdiction may be cited on new return lines. Anyone authenticated may read a single jurisdiction or list them.

A `Taxpayer` registers exemption certificates that justify exempt sales on its returns. A certificate names the owning `taxpayer_id`, an `exemption_type` of `RESALE`, `GOVERNMENT`, `NONPROFIT`, or `MANUFACTURING`, an issuer-assigned `certificate_number`, an inclusive `effective_date`, and an exclusive `expiry_date`. A certificate's validity interval is half-open: it covers `effective_date` up to but not including `expiry_date`. When a new certificate is registered, the system rejects it if the same taxpayer already holds a certificate of the same `exemption_type` whose half-open validity interval overlaps the new one, returning `ERR_CERTIFICATE_OVERLAP`.

### 3.3. Filing a Return: Tax, Discount, and Net Due

A `Taxpayer` drafts a return by declaring the owning `taxpayer_id`, a `period_key` label such as "2026-Q1", an inclusive `period_start_date` and inclusive `period_end_date`, a statutory `filing_due_date`, and an array of `lines`. Each line object supplies a `jurisdiction_id`, `gross_sales_cents`, `exempt_sales_cents`, and `deduction_cents`; the server fills each line's `rate_bps` from the cited jurisdiction and computes the line's `taxable_cents` and `line_tax_cents` at file time. A return may optionally reference an `exemption_certificate_id`. A fresh return begins in `status` `DRAFT` with a null `filed_at`.

Two guards run at draft creation. First, the new period may not overlap an existing return for the same taxpayer: if any existing return's period interval `[period_start_date, period_end_date]` — treated as a closed interval on both ends — overlaps the new one, the request is rejected with `ERR_PERIOD_OVERLAP`. Second, if an `exemption_certificate_id` is supplied, the certificate must belong to the same taxpayer as the return (otherwise `ERR_CERTIFICATE_OWNER_MISMATCH`), and it must be valid at the return's `period_end_date` — meaning its `effective_date` is on or before `period_end_date` and `period_end_date` is strictly before its `expiry_date` — otherwise `ERR_CERTIFICATE_EXPIRED`. The owner check precedes the validity check. A missing referenced certificate yields `ERR_CERTIFICATE_NOT_FOUND`, and a line citing a jurisdiction that does not exist or is inactive yields `ERR_JURISDICTION_NOT_FOUND`.

Filing transitions a return from `DRAFT` to `FILED`, and requires both that the return currently be in `DRAFT` (or `AMENDING`, per §3.4) — otherwise `ERR_RETURN_NOT_DRAFT` — and that the owning taxpayer's `account_status` be `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`. At file time the server resolves each line and computes tax. For every line, the taxable base is the gross sales minus exempt sales minus deductions, floored at zero: `taxable_cents` is the larger of 0 and `gross_sales_cents − exempt_sales_cents − deduction_cents`. Each line's tax is the taxable cents multiplied by the jurisdiction's `rate_bps`, divided by 10000, and rounded half-up to a whole cent — and this rounding happens on each line individually. The return's `total_taxable_cents` is the sum of the per-line taxable amounts, and its `tax_due_cents` is the sum of the already-rounded per-line taxes; that is, tax is rounded per line first and only then summed, never summed and then rounded.

The vendor collection discount rewards timely filers. After the tax total is known, the system determines timeliness by comparing the logical-clock date at the moment of filing against the return's `filing_due_date` at day granularity: filing on or before the due date is timely, and filing exactly on the due date qualifies. When the filing is timely and the owning taxpayer's `account_status` is `ACTIVE`, the `vendor_discount_cents` is one and a half percent of the tax due — `tax_due_cents` multiplied by 150 basis points and divided by 10000, rounded half-up — but never more than a cap of 100000 cents (one thousand dollars); the discount is the smaller of the computed amount and that cap. When the filing is late or the account is not active, `vendor_discount_cents` is zero. In all cases the return's `net_return_due_cents` is `tax_due_cents` minus `vendor_discount_cents`, and this net figure is what the return contributes to the account balance. Filing stamps `filed_at` with the current clock, recomputes the owning taxpayer's balance, and bumps the return's `version`.

### 3.4. Amending Returns, Remittances, and Prepayments

A filed return can be corrected. Amendment moves a return from `FILED` to `AMENDING` and requires the return to currently be `FILED` (otherwise `ERR_RETURN_NOT_FILED`), the supplied `expected_return_version` to match the return's current `version` (otherwise the stale-version conflict of §2.7), and — because an open audit freezes the period — that no `Audit` exists for the same `taxpayer_id` and `period_key` in `OPEN` status, otherwise `ERR_AUDIT_OPEN_ON_PERIOD`. The amend request supplies replacement `lines`. Amendment has a compensating cascade: because the return is leaving `FILED`, every `Remittance` whose `applied_return_id` points at this return is un-applied — its `applied_amount_cents` resets to 0, its `unapplied_amount_cents` returns to the full `amount_cents`, and its `applied_return_id` clears to null. The owning taxpayer's balance is recomputed and the return's `version` bumps. An amended return re-files through the same filing action, transitioning `AMENDING → FILED`, which recomputes `total_taxable_cents`, `tax_due_cents`, `vendor_discount_cents`, and `net_return_due_cents` from the amended lines, re-stamps `filed_at`, recomputes the balance, and bumps `version` again. The `DRAFT → FILED → AMENDING → FILED` cycle may repeat.

Money arrives as remittances. A `Taxpayer` records a remittance by naming the owning `taxpayer_id`, a `remittance_type` of either `PAYMENT` (settling a filed return) or `PREPAYMENT` (an on-account deposit), and a positive `amount_cents`. A new remittance is stamped with `received_at` at the current clock, starts with `applied_amount_cents` of 0, and therefore has `unapplied_amount_cents` equal to its full `amount_cents` and a null `applied_return_id`. The invariant `applied_amount_cents + unapplied_amount_cents == amount_cents` holds at all times.

Applying a remittance draws down its unapplied balance against a filed return. The apply request names the `applied_return_id` and an `apply_amount_cents`. The target return must be in `FILED` status — this state check (`ERR_RETURN_NOT_FILED`) is evaluated before the fiscal check. The room remaining on the target is its `net_return_due_cents` minus the sum of `applied_amount_cents` already applied to it by other remittances. The requested `apply_amount_cents` may exceed neither the remittance's own `unapplied_amount_cents` nor that remaining room; either excess is rejected with `ERR_OVERAPPLICATION` (HTTP 422). On success the remittance's `applied_amount_cents` increases by the requested amount, its `unapplied_amount_cents` becomes `amount_cents` minus the new `applied_amount_cents`, its `applied_return_id` is set to the target, the owning taxpayer's balance is recomputed, and its `version` bumps.

### 3.5. Audits, Nexus Discovery, and Assessments

A `TaxAuditor` opens an audit against a taxpayer by naming the `taxpayer_id`, an `audit_type`, and the `period_key` under review. A `FIELD_AUDIT` reviews a filed period; a `NEXUS_DISCOVERY` tests economic nexus and requires a `gross_receipts_cents` figure. At creation the server records `opened_by_user_id` from the acting auditor's `X-User-ID` and, for a `NEXUS_DISCOVERY`, computes `nexus_established` as true exactly when the measured `gross_receipts_cents` is greater than or equal to the nexus threshold of 10000000 cents (one hundred thousand dollars); receipts equal to the threshold do establish nexus. A new audit starts in `OPEN`.

Closing an audit requires it to be `OPEN` (otherwise `ERR_AUDIT_NOT_OPEN`) and carries an `outcome`. When the `outcome` is `NO_CHANGE`, the audit moves to `CLOSED_NO_CHANGE`; if this was a `NEXUS_DISCOVERY` whose `nexus_established` came back true, closing it flips the owning taxpayer's `nexus_status` to `ESTABLISHED`. Either way `closed_at` is stamped and the audit's `version` bumps.

When the `outcome` is `ASSESSED`, the close carries a `tax_deficiency_cents` greater than zero and an `original_due_date`, and optionally a `return_id`; the audit moves to `CLOSED_ASSESSED`. This drives a three-link cascade. First, the system creates an `Assessment` of `assessment_type` `AUDIT_DEFICIENCY`, linking it to this audit via `audit_id`, carrying the same `taxpayer_id`, the supplied `return_id`, the `tax_deficiency_cents`, and the `original_due_date`, in `status` `ISSUED`, with `issued_by_user_id` copied from the audit's `opened_by_user_id`. Its penalty and interest are computed as described below. Second, if a `return_id` was supplied, that `TaxReturn` is driven from `FILED` to `ASSESSED`. Third, because the return became `ASSESSED`, any `RefundClaim` on that return still in `OPEN` is voided to `VOIDED`. The owning taxpayer's balance is recomputed, `closed_at` is stamped, and the audit's `version` bumps.

A `TaxAuditor` may also issue a `LATE_FILING` assessment directly, without an audit, by supplying the `taxpayer_id`, `assessment_type`, a positive `tax_deficiency_cents`, an `original_due_date`, and an optional `return_id`; `issued_by_user_id` is the acting auditor and `issued_at` is stamped from the clock. Every assessment records `penalty_cents`, `interest_cents`, and a `total_due_cents` equal to `tax_deficiency_cents + penalty_cents + interest_cents`, and begins in `ISSUED`.

Penalty and interest are computed in a pinned order — base, then penalty, then interest on base-plus-penalty, then total — and the penalty rule differs by variant. Let the base be the assessment's `tax_deficiency_cents`. The number of whole months late is the count of 30-day periods between the `original_due_date` and the issuance date on the logical clock: the elapsed days divided by 30 and rounded down to a whole number. For an `AUDIT_DEFICIENCY`, the `penalty_cents` is twenty-five percent of the base — base multiplied by 2500 basis points, divided by 10000, rounded half-up — with no cap. For a `LATE_FILING`, the `penalty_cents` is ten percent of the base — base multiplied by 1000 basis points, divided by 10000, rounded half-up — but never more than a cap of 500000 cents (five thousand dollars); the penalty is the smaller of the computed amount and that cap. The `interest_cents` is then one percent per month applied to the sum of base and penalty: `(tax_deficiency_cents + penalty_cents)` multiplied by 100 basis points, divided by 10000, multiplied by the number of months late, rounded half-up. Interest is always charged on base plus penalty, never on the base alone. Issuing an assessment recomputes the owning taxpayer's balance.

### 3.6. Appeals

A `Taxpayer` contests an assessment by filing an appeal that names the `assessment_id` and states the `grounds`; ownership derives from the assessment's `taxpayer_id`. The assessment must be in `ISSUED` (otherwise `ERR_ASSESSMENT_NOT_ISSUED`, and a missing assessment yields `ERR_ASSESSMENT_NOT_FOUND`), and the appeal must be filed within 60 days of the assessment's `issued_at`, measured on the logical clock; filing more than 60 days after issuance is rejected with `ERR_APPEAL_WINDOW_CLOSED`. A new appeal is stamped with `filed_at` and starts in `SUBMITTED`, with a null `info_request_note`, `decided_by_user_id`, and `decided_at`.

The review may cycle. An `AppealsOfficer` who needs more information moves a `SUBMITTED` appeal to `INFO_REQUESTED`, recording the `info_request_note` from the request and bumping `version`. The owning taxpayer responds to an info request with a `response_note`, moving the appeal from `INFO_REQUESTED` back to `SUBMITTED` and bumping `version`; responding requires the appeal to currently be `INFO_REQUESTED` (otherwise `ERR_INFO_NOT_REQUESTED`) and requires the acting taxpayer to own the appealed assessment. The `SUBMITTED → INFO_REQUESTED → SUBMITTED` loop may repeat any number of rounds. Requesting info or deciding requires the appeal to be `SUBMITTED`; attempting either on an appeal not in `SUBMITTED` yields `ERR_APPEAL_NOT_OPEN`.

An `AppealsOfficer` decides a `SUBMITTED` appeal by supplying an `outcome`. Segregation of duties applies: the deciding officer's `X-User-ID` must differ from the appealed assessment's `issued_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. On a decision the appeal records `decided_by_user_id` and `decided_at` and bumps `version`. An `outcome` of `ALLOW` drives the appeal to `ALLOWED` and cascades the appealed assessment from `ISSUED` to `ABATED`: the abated assessment's `total_due_cents` drops out of the balance, and if the assessment carries a `return_id` whose return is currently `ASSESSED`, that return reverts to `FILED`. An `outcome` of `DENY` drives the appeal to `DENIED` and cascades the assessment from `ISSUED` to `AFFIRMED`, leaving its `total_due_cents` in the balance. Either decision recomputes the owning taxpayer's balance; abating lowers it by exactly the abated `total_due_cents`.

### 3.7. Refund Claims

A `Taxpayer` files a refund claim for an overpayment on a return, naming the `taxpayer_id`, the `return_id` the overpayment relates to, a positive `claim_amount_cents` of principal, a `reason` of either `TAXPAYER_ERROR` or `AUDIT_ADJUSTMENT`, the `overpayment_date`, and the `expected_return_version`. The version guard of §2.7 applies: a `expected_return_version` that does not match the return's current `version` is rejected with `ERR_STALE_VERSION` (412). Filing a claim supersedes any prior `RefundClaim` on the same return still in `OPEN`, driving that prior claim to `SUPERSEDED`, and it advances the return's `version` — which is precisely why a second create still carrying the earlier observed version is working from a stale view. A new claim starts in `OPEN` with a null `interest_cents`, `refund_total_cents`, and `approved_at`.

A `TaxAdmin` approves or denies an open claim. Approval requires the claim to be `OPEN` (otherwise `ERR_REFUND_NOT_OPEN`) and the owning taxpayer to not be `SUSPENDED`, otherwise `ERR_ACCOUNT_SUSPENDED`. Approval computes refund interest by the variant its `reason` selects and moves the claim to `APPROVED`. When the `reason` is `TAXPAYER_ERROR`, interest is a statutory-delay variant that only begins after a 90-day grace period from the claim's filing date: the chargeable days are the days from the claim's `created_at` date to the approval date on the logical clock, less 90, floored at zero, and the `interest_cents` is the principal `claim_amount_cents` multiplied by 3 basis points, divided by 10000, multiplied by those chargeable days, rounded half-up; a claim approved within the grace period earns zero interest. When the `reason` is `AUDIT_ADJUSTMENT`, interest accrues from the `overpayment_date` with no grace: the days are counted from `overpayment_date` to the approval date, and the `interest_cents` is the principal multiplied by 3 basis points, divided by 10000, multiplied by those days, rounded half-up. In both variants day counts include the ending day and exclude the starting day. The `refund_total_cents` is `claim_amount_cents + interest_cents`; approval stamps `approved_at`, recomputes the owning taxpayer's balance (which falls by the `refund_total_cents`), and bumps `version`. Denial requires the claim to be `OPEN`, accepts an optional `deny_reason`, moves the claim to `DENIED`, and bumps `version`. A claim may also reach `VOIDED` when its return becomes `ASSESSED` (see §3.5) or `SUPERSEDED` when a newer claim is filed on the same return.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. All state-changing endpoints follow the validation ordering of §2.8.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tax/jurisdictions` | Create a tax jurisdiction (rate config) | TaxAdmin |
| GET | `/tax/jurisdictions/{id}` | Read a jurisdiction | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/jurisdictions` | List jurisdictions | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/taxpayers` | Public taxpayer registration; account starts PENDING | Anonymous |
| GET | `/tax/taxpayers/{id}` | Read a taxpayer, including derived account balance | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/taxpayers` | List taxpayers | TaxAdmin, TaxAuditor, AppealsOfficer |
| POST | `/tax/taxpayers/{id}/activate` | Activate or reinstate an account | TaxAdmin |
| POST | `/tax/taxpayers/{id}/suspend` | Suspend an ACTIVE account | TaxAdmin |
| POST | `/tax/returns` | Create a DRAFT return with line objects | Taxpayer |
| GET | `/tax/returns/{id}` | Read a return | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/returns` | List/filter returns | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/returns/{id}/file` | File a DRAFT/AMENDING return | Taxpayer |
| POST | `/tax/returns/{id}/amend` | Reopen a FILED return for correction (OCC-guarded) | Taxpayer |
| POST | `/tax/exemption-certificates` | Register an exemption certificate | Taxpayer |
| GET | `/tax/exemption-certificates/{id}` | Read an exemption certificate | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/exemption-certificates` | List/filter exemption certificates | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/remittances` | Record a PAYMENT or PREPAYMENT on account | Taxpayer |
| GET | `/tax/remittances/{id}` | Read a remittance | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/remittances` | List/filter remittances | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/remittances/{id}/apply` | Apply a remittance to a FILED return | Taxpayer |
| POST | `/tax/audits` | Open a FIELD_AUDIT or NEXUS_DISCOVERY audit | TaxAuditor |
| GET | `/tax/audits/{id}` | Read an audit | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/audits` | List/filter audits | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/audits/{id}/close` | Close an audit (ASSESSED cascades an assessment) | TaxAuditor |
| POST | `/tax/assessments` | Issue a LATE_FILING assessment directly | TaxAuditor |
| GET | `/tax/assessments/{id}` | Read an assessment | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/assessments` | List/filter assessments | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/appeals` | File an appeal against an ISSUED assessment | Taxpayer |
| GET | `/tax/appeals/{id}` | Read an appeal | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/appeals` | List/filter appeals | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/appeals/{id}/request-info` | Request more information on an appeal | AppealsOfficer |
| POST | `/tax/appeals/{id}/respond` | Respond to an info request | Taxpayer |
| POST | `/tax/appeals/{id}/decide` | Allow or deny an appeal (SoD-checked) | AppealsOfficer |
| POST | `/tax/refund-claims` | File a refund claim (OCC-guarded on the return) | Taxpayer |
| GET | `/tax/refund-claims/{id}` | Read a refund claim | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| GET | `/tax/refund-claims` | List/filter refund claims | TaxAdmin, TaxAuditor, AppealsOfficer, Taxpayer |
| POST | `/tax/refund-claims/{id}/approve` | Approve a refund (computes interest) | TaxAdmin |
| POST | `/tax/refund-claims/{id}/deny` | Deny a refund claim | TaxAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | TaxAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_TAXPAYER_NOT_FOUND` | 404 |
| `ERR_JURISDICTION_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_REMITTANCE_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_REFUND_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_DRAFT` | 409 |
| `ERR_RETURN_NOT_FILED` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_AUDIT_NOT_OPEN` | 409 |
| `ERR_ASSESSMENT_NOT_ISSUED` | 409 |
| `ERR_APPEAL_NOT_OPEN` | 409 |
| `ERR_INFO_NOT_REQUESTED` | 409 |
| `ERR_REFUND_NOT_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CERTIFICATE_OWNER_MISMATCH` | 409 |
| `ERR_CERTIFICATE_EXPIRED` | 409 |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_CERTIFICATE_OVERLAP` | 409 |
| `ERR_DUPLICATE_JURISDICTION` | 409 |
| `ERR_AUDIT_OPEN_ON_PERIOD` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_OVERAPPLICATION` | 422 |
