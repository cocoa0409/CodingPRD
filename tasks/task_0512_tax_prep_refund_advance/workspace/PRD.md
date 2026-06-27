# Tax-Prep Refund Advance API — Product Requirements Document

## 1. Introduction

This document specifies the back-office API that powers a storefront tax-preparation business modeled on national chains such as H&R Block and Jackson Hewitt. A single deployment serves many physical storefronts, each of which intakes taxpayers, books appointments, collects source documents, prepares and electronically files federal and state returns, and — where the storefront is licensed for it — layers consumer bank products on top: a refund-transfer product that routes the IRS refund through the office's fee-deduction waterfall, and a refund-anticipation advance loan underwritten against the taxpayer's expected refund.

The business problem the API solves is keeping four very different concerns consistent inside one transaction boundary: the front-desk scheduling workflow, the preparation-and-e-file lifecycle (including IRS acknowledgement, rejection, correction loops, prior-year filings, and 1040X amendments), the IRS compliance regime that gates every transmission on a live EFIN and an unexpired PTIN credential, and the money movement that deducts preparation fees, bank-product fees, audit-protection fees, and advance repayments from a disbursed refund. Because money and compliance are involved, the API favors immediate consistency over eventual reconciliation: every cascade, counter, and ledger figure settles within the request that triggers it.

The reader of this document is the engineer implementing the service. The document is organized so that Section 2 fixes the system-wide contracts (authentication, response envelope, pagination, concurrency, rounding, and cross-cutting compliance principles) and Section 3 narrates the business workflows in the order an office actually performs them. Sections 4 and 5 summarize the HTTP surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is evaluated before permission, which is evaluated before any resource lookup.

The system recognizes exactly four roles: `OfficeManager`, `FrontDeskAgent`, `TaxPreparer`, and `BankProductOfficer`.

The `OfficeManager` is the compliance-and-administration operator. It owns storefront creation, EFIN suspension and reinstatement, PTIN-credential filing and revocation, and preparer onboarding, and it may stand in for front-desk and bank-product duties as a superset operator. When `X-User-Role` is `OfficeManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `FrontDeskAgent` runs the intake desk — registering taxpayers, booking and advancing appointments, opening returns, and maintaining the document checklist. When `X-User-Role` is `FrontDeskAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never matched against an entity's `id`. The `BankProductOfficer` underwrites and funds the bank products — refund-transfers, refund-advances, and the audit-protection add-on. When `X-User-Role` is `BankProductOfficer`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity, recorded but not compared to any entity's `id`.

The `TaxPreparer` is the only entity-backed role. When `X-User-Role` is `TaxPreparer`, `X-User-ID` is the `id` of the acting `Preparer` row; ownership and capacity checks on any resource that references a `Preparer` compare the resource's `preparer_id` to `X-User-ID`. The `TaxPreparer` exclusively transmits e-files and records IRS acknowledgements, and shares return-opening, assignment, transition, and document duties with the other operators.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Almost every persisted resource — `Office`, `ComplianceCredential`, `Preparer`, `Client`, `Appointment`, `TaxReturn`, `DocumentIntake`, `FeeLine`, `AuditProtection`, `EfileSubmission`, `RefundTransfer`, and `RefundAdvance` — carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped at creation. `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation. `version` is an integer that begins at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.6.

The single exception is the logical clock resource, `ComplianceClock`. It is a singleton configuration row that carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and clients must not expect either field on it.

### 2.5. Nested Resource Retrieval and Validation Ordering

Many endpoints address a resource through a path that names a parent before a child — for example, a return's documents or an office's appointments. The server validates path identifiers and foreign-key references left to right: the leftmost path segment is resolved first, then the next, and only then are body-level foreign keys resolved. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404), before any later identifier or any business rule is considered.

This ordering is part of a fixed validation precedence applied to every request. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first; then role permission (`ERR_FORBIDDEN`, 403); then existence of all path and foreign-key resources (`ERR_NOT_FOUND`, 404); then request-body well-formedness (`ERR_INVALID_REQUEST`, 422) on create and transition endpoints, covering required fields present, enum values in range, an appointment's `end_utc` strictly after its `start_utc`, `ssn_last4` being exactly four digits, `ptin` matching the letter `P` followed by eight digits, and `efin` being exactly six digits; then, on transition, e-file, e-file-ack, underwrite, disburse, and cancel endpoints, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409); and then, on the refund-transfer disburse endpoint specifically, the optimistic-concurrency check (`ERR_STALE_VERSION`, 412). Business rules specific to each workflow are evaluated only after this common precedence has passed. Where two business rules could both apply to one request, the lower-numbered rule in this precedence wins and its error surfaces first.

### 2.6. Optimistic Concurrency Control on Refund-Transfer Disbursement

One endpoint participates in optimistic concurrency control: disbursing a refund-transfer. The disburse request must carry `expected_refundtransfer_version`, a non-optional input field whose value is the `version` of the target `RefundTransfer` that the client last observed. If that value does not equal the transfer's current `version`, the disburse is rejected with `ERR_STALE_VERSION` (HTTP 412).

The reason this guard matters is that a refund-transfer stays in `PENDING_FUNDING` while the bank revises its pending refund figure. Each revision re-stamps the estimated figure and advances the transfer's `version` by one. A disburse request that still carries the version observed before a revision will therefore find the transfer in an identical `PENDING_FUNDING` state — every state precondition passes — yet the version it presents is stale because another writer has superseded the pending figure. Because disbursement permanently runs the fee-deduction waterfall, it must be computed against the figure the client actually observed; the stale presenter is rejected rather than allowed to overwrite a revision it never saw. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.7. Money, Precision, and Rounding

All monetary amounts in the system are stored and exchanged as integer cents — there are no fractional-cent values and no floating-point dollar figures. Field names ending in `_cents` are always whole-cent integers.

Two calculations involve multiplying a cent amount by a non-integer factor and therefore require rounding: the preparation-fee computation and the refund-advance eligibility computation. In both, the half-up rounding method is used — a value exactly halfway between two whole cents rounds up to the larger cent. The preparation-fee computation rounds each fee line to whole cents before the lines are summed (round-per-line, not sum-then-round), and rounds the returning-client discount after the subtotal is formed. The electronic-disbursement surcharge described in §3 likewise rounds each funded bucket to whole cents before summing those rounded amounts. The refund waterfall itself needs no rounding because every input to it is already an integer cent amount.

### 2.8. Storefront Compliance Gates: EFIN and PTIN

Two compliance artifacts gate electronic filing, and they are checked independently. At the storefront level, an `Office` carries an `efin` (its six-digit IRS Electronic Filing Identification Number) and an `efin_status` that is either `ACTIVE` or `SUSPENDED`. A suspended EFIN blocks every e-file transmission in that office. At the preparer level, a `ComplianceCredential` records a `ptin` (the letter `P` followed by eight digits), the `holder_name`, an `expires_on` date, and a `status` of either `ACTIVE` or `REVOKED`. The credential's `status` is set to `REVOKED` by the revoke action and otherwise begins `ACTIVE`; date expiry is a separate test performed against the logical clock at e-file time. A credential is filed under an office through its `office_id`, and a preparer signs under one credential identified by `credential_id`.

### 2.9. Hierarchical Consistency, Counters, and Cascades

The system maintains denormalized counters and propagates state changes immediately. Each `Office` carries `open_return_count`, the number of its `TaxReturn` rows whose status is neither `EFILED_ACCEPTED` nor `CANCELLED`. Each `Preparer` carries `assigned_open_returns`, the number of returns assigned to that preparer whose status is neither `EFILED_ACCEPTED` nor `CANCELLED`, and a `max_open_returns` ceiling. Opening a return increments the office's `open_return_count` by one; assigning a preparer increments that preparer's `assigned_open_returns` by one; accepting a return decrements both by one; cancelling a return recomputes both so the cancelled return leaves the count (the office count falls by one, and the preparer count falls by one when a preparer had been assigned).

Cancellation also cascades to dependent bank products and add-ons, and these cascades are detailed in §3 alongside the workflows that create those resources. Whenever the server mutates a resource — whether at direct client request or as an automatic cascade — that resource's `updated_at` is refreshed and its `version` is incremented. A cascade that flips a child entity's state is itself a mutation of that child and bumps the child's own `version`.

## 3. Business Logic & Workflows

### 3.1. Storefronts, Credentials, and Preparers

A storefront is the top-level scope. An `OfficeManager` opens one by supplying a `name`, the office `efin`, and the two-letter `state_code` where it operates, and may optionally pass `bank_product_enabled` to declare whether the office is licensed to offer refund-transfers and advances; when omitted, bank products are disabled. On creation the office's `efin_status` is `ACTIVE` and its `open_return_count` is zero. The manager can later flip `efin_status` between `ACTIVE` and `SUSPENDED` by submitting the new `efin_status`; a `SUSPENDED` EFIN gates all future transmissions in that office.

Before a preparer can sign anything, a PTIN credential must be filed. An `OfficeManager` files one against an office by supplying `office_id`, the `ptin`, the `holder_name`, and the `expires_on` date; the credential starts in `ACTIVE` status. The same manager may later revoke a credential, which sets its `status` to `REVOKED`. A `Preparer` is then added to an office by an `OfficeManager`, who supplies the `credential_id` the preparer signs under, the preparer's `full_name`, and optionally `max_open_returns`; when that ceiling is omitted it defaults to 25. A newly added preparer begins with `assigned_open_returns` at zero, and the server records the parent `office_id` on the preparer. Credentials can be listed and optionally filtered by their `office_id`, and preparers can be listed within an office or filtered by `credential_id`.

### 3.2. Taxpayer Intake and Appointment Scheduling

The front desk intakes a taxpayer as a `Client` of an office. A `FrontDeskAgent` (or an `OfficeManager`) supplies the client's `full_name` and `ssn_last4` (the last four digits of the SSN, used for duplicate detection within an office and tax year), and may optionally pass the underwriting `risk_band` and the `is_returning` flag. The `risk_band` defaults to `MEDIUM` and is one of `LOW`, `MEDIUM`, or `HIGH`; it gates refund-advance eligibility. The `is_returning` flag defaults to false and, when true, marks the taxpayer as having filed with this office in a prior year, which drives the returning-client preparation discount. The server stamps the intake `office_id` on the client.

Appointments tie a client to a preparer for a meeting. Booking an appointment under an office requires `client_id`, `preparer_id`, `start_utc` (the inclusive ISO 8601 UTC start), and `end_utc` (the exclusive end, which must be strictly after `start_utc`). A new appointment begins in `SCHEDULED` status. Two overlap guards run at booking time, and they treat time intervals differently for preparers and for clients. For the named preparer, the new appointment's half-open interval — start inclusive, end exclusive — must not overlap any existing non-terminal appointment for that preparer; adjacency, where one appointment's end equals the next appointment's start, is allowed. A preparer overlap is rejected with `ERR_PREPARER_DOUBLE_BOOKED`. For the named client, the interval is treated as closed on both ends, so a shared boundary collides: if the new appointment's start equals an existing appointment's end (or otherwise overlaps), it is rejected with `ERR_CLIENT_DOUBLE_BOOKED`. Both guards consider only non-terminal appointments. Appointments can be listed within an office, or listed globally filtered by `office_id`, `client_id`, or `preparer_id`.

An appointment advances through its lifecycle by a `FrontDeskAgent` (or `OfficeManager`) submitting the target state in the `to` field. From `SCHEDULED` it may move to `CHECKED_IN`, but only once the logical clock has reached or passed the appointment's `start_utc` — checking in before the window opens is rejected with `ERR_APPOINTMENT_WINDOW_NOT_OPEN`. From `CHECKED_IN` it may move to `COMPLETED` with no further precondition. From `SCHEDULED` it may instead be marked `NO_SHOW`, but only after the window has fully passed — that is, only once the clock has reached or passed the appointment's `end_utc`; recording a no-show before then is rejected with the same `ERR_APPOINTMENT_WINDOW_NOT_OPEN`. From `SCHEDULED` it may also be `CANCELLED` with no precondition. `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal.

### 3.3. Opening a Return and Building the Document Checklist

A tax return is opened for a client by a `FrontDeskAgent`, `OfficeManager`, or `TaxPreparer`. The opener supplies `office_id`, `client_id`, and `tax_year` (for example 2025), and may optionally supply `return_kind`, `complexity_band`, `schedules`, `state_return_count`, `expected_refund_cents`, and `amends_return_id`. The `return_kind` is one of `ORIGINAL`, `PRIOR_YEAR`, or `AMENDED_1040X`, defaulting to `ORIGINAL`. The `complexity_band` is one of `SIMPLE`, `STANDARD`, or `COMPLEX`, defaulting to `SIMPLE`, and drives the preparation-fee multiplier. The `schedules` field is a subset of the set {A, B, C, D, E, EIC}, defaulting to an empty list, and each attached schedule adds a per-schedule fee line. The `state_return_count` is the number of state returns filed alongside the federal return and defaults to zero. The `expected_refund_cents` is the preparer-entered expected federal refund in cents, defaulting to zero, and gates advance eligibility. The `amends_return_id` references the originally accepted return that a 1040X amends and is null for an original return; it is the self-referential link between a 1040X and its predecessor. A new return opens in `INTAKE` status, its `preparer_id` is null until assignment, its computed `prep_fee_cents` is unset until preparation, and its `reject_count` starts at zero. Opening a return increments the office's `open_return_count` by one.

A duplicate-taxpayer guard runs at open time: within one office, no two returns may share the same `client_id` and `tax_year` unless the new one is an `AMENDED_1040X` (a 1040X is expected to share the client and year with the original it amends). A second non-amended return for the same office, client, and tax year is rejected with `ERR_DUPLICATE_RETURN`.

Documents are tracked as a checklist hanging off the return. Adding a document supplies its `doc_type` — one of `W2`, `1099`, `ID`, `PRIOR_RETURN`, or `OTHER` — and optionally `is_required`, which defaults to true and declares whether the document must be present before preparation can begin. A new `DocumentIntake` row starts in `PENDING` status and records the parent `tax_return_id`. A document is later marked `RECEIVED` or `WAIVED` by submitting the new `status`. Documents for a return can be listed.

Returns can be listed and filtered by `office_id`, `client_id`, `preparer_id`, or `amends_return_id`, and a single return retrieved by its identifier.

### 3.4. Assignment, Preparation, and the Fee Computation

Assigning a return to a preparer is a capacity-checked action available to an `OfficeManager` or `TaxPreparer`. The assigner supplies `preparer_id`. The assignment is rejected with `ERR_PREPARER_AT_CAPACITY` when it would push the target preparer's `assigned_open_returns` above that preparer's `max_open_returns`. A successful assignment sets the return's `preparer_id` and increments the assigned preparer's `assigned_open_returns` by one.

A return advances through its non-e-file lifecycle when a `FrontDeskAgent`, `OfficeManager`, or `TaxPreparer` submits the target state in `to`. Moving from `INTAKE` to `DOCS_PENDING` requires that at least one `DocumentIntake` row exists for the return; with zero documents the move is rejected with `ERR_NO_DOCUMENTS`. Moving from `DOCS_PENDING` to `IN_PREP` is performed by a `TaxPreparer` and carries three preconditions evaluated in this order: the return must have a non-null `preparer_id`, else `ERR_PREPARER_NOT_ASSIGNED`; every `DocumentIntake` whose `is_required` is true must be in either `RECEIVED` or `WAIVED` status (a still-`PENDING` required document fails), else `ERR_REQUIRED_DOCS_MISSING`; and the assigned preparer's credential must be in `ACTIVE` status, else `ERR_CREDENTIAL_INVALID`.

The move into `IN_PREP` is also where the preparation fee is computed, written to `prep_fee_cents`, and materialized as `FeeLine` rows; the fee is recomputed every time the return enters `IN_PREP`. Each fee line records the parent `tax_return_id`, a `line_kind` of `BASE_1040`, `SCHEDULE`, `STATE_RETURN`, or `DISCOUNT`, a human-readable `label` such as "Schedule C" or "Returning-client discount", and a signed `amount_cents` (discount lines are negative). All amounts are integer cents. The computation proceeds in this pinned order. First, a band multiplier is selected from the return's `complexity_band`: `SIMPLE` uses 1.00, `STANDARD` uses 1.20, and `COMPLEX` uses 1.50. Second, the base line is the base-1040 fee of 15000 cents multiplied by that band multiplier and rounded half-up to whole cents; it becomes one `BASE_1040` line. Third, for each schedule attached to the return, one `SCHEDULE` line is produced as that schedule's fee multiplied by the band multiplier and rounded half-up to whole cents; the per-schedule fees are 4000 cents for A, 2500 for B, 9000 for C, 6000 for D, 7500 for E, and 5000 for EIC. Fourth, for each state return counted in `state_return_count`, one `STATE_RETURN` line is produced as the state-return fee of 6000 cents multiplied by the band multiplier and rounded half-up to whole cents. Each of these lines is rounded individually before any summing.

The subtotal is the base line plus the sum of the schedule lines plus the sum of the state-return lines. The returning-client discount applies only when the linked client's `is_returning` is true. When it applies, the discount is the smaller of a cap of 2500 cents and ten percent of the subtotal rounded half-up to whole cents, and it is added as a single negative `DISCOUNT` line carrying the negated discount amount. When the client is not returning, no discount line is produced and `prep_fee_cents` equals the subtotal exactly. When the client is returning, `prep_fee_cents` is the subtotal minus the discount, and the figure is floored at zero so it can never go negative. The schedules and `state_return_count` are read from the return row at transition time, and `is_returning` is read from the linked client.

From `IN_PREP` the return moves to `PREPARED` when its `expected_refund_cents` is greater than or equal to zero; a negative figure is rejected with `ERR_INVALID_REFUND_FIGURE`.

### 3.5. Transmission, IRS Acknowledgement, and the Correction Loop

Transmitting a `PREPARED` return for e-file is an action exclusive to the `TaxPreparer`. Three preconditions guard the transmission. The office's `efin_status` must be `ACTIVE`, else `ERR_EFIN_SUSPENDED`. The assigned preparer's credential must be in `ACTIVE` status and its `expires_on` must be strictly after the logical clock's current instant — both conditions together — else `ERR_CREDENTIAL_INVALID`. And if the return's `return_kind` is `AMENDED_1040X`, the return referenced by `amends_return_id` must itself be in `EFILED_ACCEPTED`, else `ERR_AMEND_TARGET_NOT_ACCEPTED`. A successful transmission moves the return from `PREPARED` to `EFILED_PENDING` and creates one `EfileSubmission` in `TRANSMITTED` status, recording the parent `tax_return_id`, the `efin_used` copied from the office's EFIN at transmission time, and the `ptin_used` copied from the assigned preparer's credential PTIN at transmission time. Its `ack_status` is one of `TRANSMITTED`, `ACCEPTED`, or `REJECTED`, and its `reject_code` is null unless a rejection is recorded. The transmission history for a return can be listed.

The IRS acknowledgement is recorded by the `TaxPreparer` against the open transmission by submitting `ack_status` and, on a rejection, `reject_code`. When `ack_status` is `ACCEPTED`, the return moves from `EFILED_PENDING` to `EFILED_ACCEPTED`: the latest `TRANSMITTED` submission's `ack_status` becomes `ACCEPTED`, the office's `open_return_count` is decremented by one, and the assigned preparer's `assigned_open_returns` is decremented by one. When `ack_status` is `REJECTED`, a `reject_code` must be supplied, else `ERR_REJECT_CODE_REQUIRED`; the return moves to `EFILED_REJECTED`, the latest `TRANSMITTED` submission's `ack_status` becomes `REJECTED` with the supplied `reject_code` stored on it, and the return's `reject_count` is incremented by one.

A rejected return can be corrected and re-transmitted. A `TaxPreparer` moves it from `EFILED_REJECTED` back to `PREPARED`, provided the return's `reject_count` is at most 3; once a fourth rejection would be in play — that is, when `reject_count` already exceeds 3 — the return is locked and the move is rejected with `ERR_REJECT_LIMIT_REACHED`. The cycle is therefore `EFILED_REJECTED` → `PREPARED` → `EFILED_PENDING`, repeated until the return is accepted or the reject limit is reached.

A return may be cancelled from `INTAKE`, `DOCS_PENDING`, `IN_PREP`, or `PREPARED` by a `TaxPreparer` (the cancellation transition is also available to the other operators through the same transition action). `EFILED_ACCEPTED` and `CANCELLED` are the terminal states. Cancellation from any of those four states runs the same effects: the office's `open_return_count` is recomputed so the cancelled return leaves the count (falling by one), and the assigned preparer's `assigned_open_returns` is recomputed to fall by one when a preparer had been assigned. Cancellation then cascades. Every `AuditProtection` on the return that is currently `ACTIVE` is moved to `VOIDED`. Any `RefundAdvance` on the return whose status is `REQUESTED` or `APPROVED` is moved to `CANCELLED`; and that advance cancellation in turn moves the linked `RefundTransfer` to `CANCELLED` when that transfer is in `PENDING_FUNDING`. Each of these cascaded state flips is a mutation of the affected child and refreshes its `updated_at` and `version`.

### 3.6. The Audit-Protection Add-On

The audit-protection add-on is an optional product attached to a return by a `BankProductOfficer` or `OfficeManager`. Adding one supplies the `tax_return_id` it protects and optionally `fee_cents`, the one-time audit-protection fee, which defaults to 5900 cents. A new `AuditProtection` starts in `ACTIVE` status, and its `status` is one of `ACTIVE`, `CANCELLED`, or `VOIDED`. The officer may later cancel an `ACTIVE` add-on, moving it to `CANCELLED`, but only while the linked return is not yet `EFILED_ACCEPTED`; cancelling protection once the return has been accepted is rejected with `ERR_RETURN_ALREADY_ACCEPTED`. The `VOIDED` state is never reached by client request — it is set automatically only when the linked return is cancelled, as described in §3.5. Add-ons can be retrieved individually or listed and filtered by `tax_return_id`.

### 3.7. The Refund-Transfer Bank Product and the Disbursement Waterfall

A refund-transfer routes an accepted return's IRS refund through the office's fee-deduction waterfall. A `BankProductOfficer` or `OfficeManager` opens one by supplying the `tax_return_id`. Because this is a bank product, the office's `bank_product_enabled` must be true, else `ERR_BANK_PRODUCT_DISABLED`. A new transfer starts in `PENDING_FUNDING` status with its `bank_product_fee_cents` set to 3995 cents and its `estimated_refund_cents` defaulting to zero. Its `status` is one of `PENDING_FUNDING`, `DISBURSED`, or `CANCELLED`. Transfers can be retrieved individually or listed and filtered by `tax_return_id`.

While the transfer is `PENDING_FUNDING`, the bank may revise the pending refund figure. A `BankProductOfficer` or `OfficeManager` submits a new `estimated_refund_cents`, which must be greater than zero, else `ERR_INVALID_REFUND_FIGURE`. The revision re-stamps `estimated_refund_cents` to the supplied figure and increments the transfer's `version` by one, leaving the transfer in `PENDING_FUNDING`. This version bump is what makes a later disburse that still carries the pre-revision version stale, per the optimistic-concurrency guard in §2.6.

Disbursing the transfer is exclusive to a `BankProductOfficer`. The disburse request supplies `disbursed_refund_cents`, the actual federal refund received from the IRS, and `expected_refundtransfer_version`. The linked return must be in `EFILED_ACCEPTED`, else `ERR_RETURN_NOT_ACCEPTED`; the `disbursed_refund_cents` must be greater than zero, else `ERR_INVALID_REFUND_FIGURE`; and `expected_refundtransfer_version` must equal the transfer's current `version`, else `ERR_STALE_VERSION` (HTTP 412). A successful disburse runs the fee-deduction waterfall, writes `net_to_taxpayer_cents` and `fee_shortfall_cents`, moves the transfer to `DISBURSED`, and increments its `version` by one.

The waterfall distributes `disbursed_refund_cents` across four fee buckets in this exact, pinned order, each bucket taking the smaller of what remains and what the bucket is owed. The first bucket is the bank-product fee, equal to the transfer's `bank_product_fee_cents`. The second is the preparation fee, equal to the linked return's `prep_fee_cents` (finalized when the return entered `IN_PREP`). The third is the audit fee, equal to the sum of `fee_cents` across the return's `AuditProtection` rows whose status is `ACTIVE`, and zero when none are active. The fourth is the advance repayment, equal to the linked `RefundAdvance`'s `approved_cents` when that advance is in `DISBURSED`, and zero when there is no disbursed advance. Processing the buckets in order, each bucket takes the smaller of the remaining refund and its owed amount, and the remaining refund is reduced by that take. After all four buckets, whatever remains is `net_to_taxpayer_cents`. The total fees are the sum of the four bucket amounts (bank-product fee plus preparation fee plus audit fee plus advance repayment), and `fee_shortfall_cents` is the total fees minus `disbursed_refund_cents`, floored at zero — so when the refund covers every bucket fully the shortfall is zero and the taxpayer nets a positive remainder, and when the refund falls short the lower-priority buckets are partially or not filled, the taxpayer nets zero, and the shortfall is the excess of fees over the refund.

Alongside the waterfall, the disburse response reports an electronic-disbursement surcharge. The surcharge is 2.9 percent applied to each bucket that the waterfall actually funded — that is, each bucket whose take was greater than zero — with each per-bucket charge rounded half-up to whole cents and then those rounded charges summed in that same pinned bucket order. This round-per-bucket-then-sum order is required and can differ from a sum-then-round result by a cent. The surcharge is informational: it is reported but does not reduce `net_to_taxpayer_cents`.

The disburse also drives the linked advance. When a `RefundAdvance` in `DISBURSED` status is linked to the same return, the advance-repayment bucket's take becomes that advance's `repaid_cents` and the advance moves to `REPAID` — the bubble described in §3.8.

A pending transfer can also be cancelled by a `BankProductOfficer` or `OfficeManager`, moving it to `CANCELLED`, but only when no linked `RefundAdvance` is in `DISBURSED`; cancelling while a linked advance is disbursed is rejected with `ERR_ADVANCE_ALREADY_DISBURSED`.

### 3.8. The Refund-Anticipation Advance Lifecycle

A refund-advance is a loan against the taxpayer's expected refund, requested by a `BankProductOfficer` or `OfficeManager` by supplying the `tax_return_id` and the `requested_cents` the taxpayer asked for. Because this is a bank product, the office's `bank_product_enabled` must be true, else `ERR_BANK_PRODUCT_DISABLED`. A new advance starts in `REQUESTED` status, with `approved_cents` unset and `repaid_cents` at zero. Its `status` is one of `REQUESTED`, `APPROVED`, `DISBURSED`, `REPAID`, `DENIED`, or `CANCELLED`; `REPAID`, `DENIED`, and `CANCELLED` are terminal. Advances can be retrieved individually or listed and filtered by `tax_return_id`.

Underwriting is exclusive to a `BankProductOfficer`, who submits a `decision` of either an approval or a denial. A denial moves the advance from `REQUESTED` to `DENIED` and sets `approved_cents` to zero. An approval moves it from `REQUESTED` to `APPROVED`, but only when the linked return's office has `bank_product_enabled` true (else `ERR_BANK_PRODUCT_DISABLED`) and the maximum eligible advance for the linked return and client is greater than zero (else `ERR_ADVANCE_INELIGIBLE`); the same eligibility floor also requires `requested_cents` to be greater than zero, and a `requested_cents` at or below zero or a maximum eligible of zero is rejected with `ERR_ADVANCE_INELIGIBLE`.

The maximum-eligible computation is a nested minimum over a refund-size tier cap and a risk-band fraction of the expected refund, evaluated in this pinned order. The tier cap is read from the return's `expected_refund_cents`: a refund below 100000 cents yields a cap of 0 (no advance under one thousand dollars); a refund from 100000 cents up to but not including 300000 cents yields a cap of 50000 cents; a refund from 300000 cents up to but not including 600000 cents yields a cap of 150000 cents; and a refund of 600000 cents or more yields a cap of 350000 cents. The tier boundaries are inclusive at the lower edge, so a refund of exactly 300000 cents lands in the 150000-cent cap tier. The risk fraction is read from the linked client's `risk_band`: `LOW` uses 0.75, `MEDIUM` uses 0.50, and `HIGH` uses 0.00. The maximum eligible is the smaller of the tier cap and the expected refund multiplied by the risk fraction, rounded half-up to whole cents. A `HIGH` risk band therefore drives the fraction product to zero, forcing the maximum eligible to zero and producing `ERR_ADVANCE_INELIGIBLE` regardless of refund size; a `LOW` band's fraction rarely binds, so the tier cap usually dominates. On an approval, `approved_cents` is set to the smaller of `requested_cents` and that maximum eligible. The `expected_refund_cents` comes from the linked return and the `risk_band` from the linked client.

Disbursing an approved advance is exclusive to a `BankProductOfficer` and takes no body fields. It requires the linked return to be in `EFILED_ACCEPTED`, else `ERR_RETURN_NOT_ACCEPTED`, and requires a `RefundTransfer` in `PENDING_FUNDING` to exist for the same return, else `ERR_NO_REFUND_TRANSFER`. A successful disburse moves the advance from `APPROVED` to `DISBURSED`.

The advance reaches `REPAID` not by direct request but as a system event: when the linked `RefundTransfer` transitions from `PENDING_FUNDING` to `DISBURSED`, the waterfall's advance-repayment bucket take becomes the advance's `repaid_cents` and the advance moves from `DISBURSED` to `REPAID`. This is the settlement bubble — the transfer's disbursement is what repays and closes out the advance.

### 3.9. The Logical Clock

Every time-based check in the system — appointment window opening, no-show eligibility, and credential expiry at e-file — reads a logical server clock rather than wall-clock time. The clock is the singleton `ComplianceClock`, whose `current_utc` defaults to 2026-05-01T00:00:00Z at startup and never falls back to real time before it is set. An `OfficeManager` advances or sets it through an administrative test-driving capability by supplying `to_iso8601`, the instant the clock should read; the response returns the clock with its `current_utc` set to that instant.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions, status changes, and the clock-setting capability — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/offices` | Create a storefront | OfficeManager |
| GET | `/offices/{id}` | Get an office | OfficeManager, FrontDeskAgent, TaxPreparer, BankProductOfficer |
| POST | `/offices/{id}/efin-status` | Suspend or reinstate the office EFIN | OfficeManager |
| POST | `/credentials` | File a PTIN credential under an office | OfficeManager |
| GET | `/credentials/{id}` | Get a credential | OfficeManager, TaxPreparer |
| GET | `/credentials` | List credentials, optionally filtered by office | OfficeManager, TaxPreparer |
| POST | `/credentials/{id}/revoke` | Revoke a credential | OfficeManager |
| POST | `/offices/{id}/preparers` | Add a preparer to an office | OfficeManager |
| GET | `/offices/{id}/preparers` | List preparers in an office | OfficeManager, FrontDeskAgent, TaxPreparer |
| GET | `/preparers/{id}` | Get a preparer | OfficeManager, FrontDeskAgent, TaxPreparer, BankProductOfficer |
| GET | `/preparers` | List preparers, optionally filtered by credential | OfficeManager, TaxPreparer |
| POST | `/offices/{id}/clients` | Intake a taxpayer | FrontDeskAgent, OfficeManager |
| GET | `/offices/{id}/clients` | List clients in an office | FrontDeskAgent, OfficeManager, TaxPreparer |
| GET | `/clients/{id}` | Get a client | FrontDeskAgent, OfficeManager, TaxPreparer, BankProductOfficer |
| POST | `/offices/{id}/appointments` | Book an appointment | FrontDeskAgent, OfficeManager |
| GET | `/offices/{id}/appointments` | List appointments in an office | FrontDeskAgent, OfficeManager, TaxPreparer |
| GET | `/appointments` | List appointments, filterable by office/client/preparer | FrontDeskAgent, OfficeManager, TaxPreparer |
| GET | `/appointments/{id}` | Get an appointment | FrontDeskAgent, OfficeManager, TaxPreparer |
| POST | `/appointments/{id}/transition` | Advance an appointment | FrontDeskAgent, OfficeManager |
| POST | `/returns` | Open a tax return for a client | FrontDeskAgent, OfficeManager, TaxPreparer |
| GET | `/returns/{id}` | Get a tax return | FrontDeskAgent, OfficeManager, TaxPreparer, BankProductOfficer |
| GET | `/returns` | List returns, filterable by office/client/preparer/amends target | FrontDeskAgent, OfficeManager, TaxPreparer, BankProductOfficer |
| POST | `/returns/{id}/assign` | Assign a preparer to a return | OfficeManager, TaxPreparer |
| POST | `/returns/{id}/transition` | Advance a return through its lifecycle | FrontDeskAgent, OfficeManager, TaxPreparer |
| POST | `/returns/{id}/efile` | Transmit the return for e-file | TaxPreparer |
| POST | `/returns/{id}/efile-ack` | Record the IRS ACK for the open transmission | TaxPreparer |
| POST | `/returns/{id}/documents` | Add a document to the intake checklist | FrontDeskAgent, OfficeManager, TaxPreparer |
| GET | `/returns/{id}/documents` | List a return's documents | FrontDeskAgent, OfficeManager, TaxPreparer |
| POST | `/documents/{id}/status` | Mark a document RECEIVED or WAIVED | FrontDeskAgent, OfficeManager, TaxPreparer |
| GET | `/returns/{id}/fee-lines` | List the itemized fee lines for a return | FrontDeskAgent, OfficeManager, TaxPreparer, BankProductOfficer |
| POST | `/audit-protections` | Add the audit-protection add-on to a return | BankProductOfficer, OfficeManager |
| GET | `/audit-protections/{id}` | Get an audit-protection add-on | BankProductOfficer, OfficeManager, TaxPreparer |
| GET | `/audit-protections` | List audit-protection add-ons, filterable by return | BankProductOfficer, OfficeManager, TaxPreparer |
| POST | `/audit-protections/{id}/cancel` | Cancel an active audit-protection add-on | BankProductOfficer, OfficeManager |
| GET | `/returns/{id}/efile-submissions` | List the transmission/ACK history for a return | TaxPreparer, OfficeManager |
| POST | `/refund-transfers` | Open a refund-transfer bank product for a return | BankProductOfficer, OfficeManager |
| GET | `/refund-transfers/{id}` | Get a refund-transfer | BankProductOfficer, OfficeManager, TaxPreparer |
| GET | `/refund-transfers` | List refund-transfers, filterable by return | BankProductOfficer, OfficeManager, TaxPreparer |
| POST | `/refund-transfers/{id}/adjust` | Revise the pending refund figure on a transfer | BankProductOfficer, OfficeManager |
| POST | `/refund-transfers/{id}/disburse` | Fund and disburse through the fee-deduction waterfall | BankProductOfficer |
| POST | `/refund-transfers/{id}/cancel` | Cancel a pending refund-transfer | BankProductOfficer, OfficeManager |
| POST | `/refund-advances` | Request a refund-anticipation advance | BankProductOfficer, OfficeManager |
| GET | `/refund-advances/{id}` | Get a refund-advance | BankProductOfficer, OfficeManager, TaxPreparer |
| GET | `/refund-advances` | List refund-advances, filterable by return | BankProductOfficer, OfficeManager, TaxPreparer |
| POST | `/refund-advances/{id}/underwrite` | Underwrite the advance (approve or deny) | BankProductOfficer |
| POST | `/refund-advances/{id}/disburse` | Disburse an approved advance | BankProductOfficer |
| POST | `/_clock/set_current_utc` | Set the logical server clock | OfficeManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NO_DOCUMENTS` | 409 |
| `ERR_PREPARER_NOT_ASSIGNED` | 409 |
| `ERR_REQUIRED_DOCS_MISSING` | 409 |
| `ERR_CREDENTIAL_INVALID` | 409 |
| `ERR_INVALID_REFUND_FIGURE` | 409 |
| `ERR_EFIN_SUSPENDED` | 409 |
| `ERR_AMEND_TARGET_NOT_ACCEPTED` | 409 |
| `ERR_REJECT_CODE_REQUIRED` | 422 |
| `ERR_REJECT_LIMIT_REACHED` | 409 |
| `ERR_PREPARER_DOUBLE_BOOKED` | 409 |
| `ERR_CLIENT_DOUBLE_BOOKED` | 409 |
| `ERR_APPOINTMENT_WINDOW_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_RETURN` | 409 |
| `ERR_PREPARER_AT_CAPACITY` | 409 |
| `ERR_BANK_PRODUCT_DISABLED` | 409 |
| `ERR_ADVANCE_INELIGIBLE` | 409 |
| `ERR_RETURN_NOT_ACCEPTED` | 409 |
| `ERR_NO_REFUND_TRANSFER` | 409 |
| `ERR_ADVANCE_ALREADY_DISBURSED` | 409 |
| `ERR_RETURN_ALREADY_ACCEPTED` | 409 |
