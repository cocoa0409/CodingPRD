# Invoice Factoring & A/R Funding API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for an Invoice Factoring and Accounts-Receivable Funding platform of the kind operated by working-capital lenders such as BlueVine. The platform lets a factor advance cash to a client against the face value of invoices the client has issued to its customers (the account-debtors), hold back a reserve, accrue a discount fee over the time the receivable remains outstanding, and ultimately reconcile every dollar once the debtor pays — or fails to pay. The business is fundamentally a ledger-reconciliation system layered with compliance controls: every advance, reserve movement, fee accrual, collection, rebate, buyback, and write-off must be traceable through an append-only ledger, and every funding decision must respect credit limits, debtor-concentration ceilings, notice-of-assignment posture, and a strict segregation of duties between the officer who approves credit and the officer who deploys capital.

The lifecycle the API governs runs from onboarding and underwriting of both clients and their debtors, through the creation of the client-debtor relationships that carry recourse terms and notice status, into invoice submission, verification, and batch funding, and finally through the collection, aging, settlement, recourse buyback, and write-off processes that close out each receivable. A central design tension drives much of the logic: the fee owed on an invoice is provisional and grows daily while the invoice is live, but is pinned to a final, tiered figure the moment the invoice terminalizes. The platform must reconcile denormalized exposure balances on clients and debtors as invoices move through their states, while serializing concurrent funding and collection activity through optimistic concurrency control so that no operator acts on a stale view of a client's headroom or reserve.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API. All resources are exposed as flat collections mounted under `/factoring`; relationships between resources are carried by foreign-key fields and expressed through the workflows in Section 3 rather than through nested URLs.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the user's operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `UnderwritingOfficer`, `FundingOfficer`, and `CollectionsOfficer`.

- A `PlatformAdmin` is an operational super-user who creates programs, onboards clients and debtors, and suspends programs; it cannot make credit decisions, fund invoices, or post collections.
- An `UnderwritingOfficer` makes credit decisions on clients and debtors, suspends, reinstates and closes clients, declares debtors insolvent, and writes off uncollectible invoices.
- A `FundingOfficer` submits, verifies, and rejects invoices, manages relationships and notices, and creates and funds purchase batches.
- A `CollectionsOfficer` posts and reverses collections, records adjustments, closes short-paid invoices, and triggers settlement and recourse buyback.

All four roles share read access to every list and read endpoint.

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server does not compare it to any entity's `id`. It does, however, record it where a credit decision is issued: when an `UnderwritingOfficer` approves or rejects a client, the acting `X-User-ID` is written to that client's `credit_decision_user_id`, and likewise when underwriting decides a debtor the acting `X-User-ID` is written to the debtor's `credit_decision_user_id`. These recorded identifiers are not used as ownership keys; they exist solely to power the segregation-of-duties check enforced at funding time, described in Section 2.4 and Section 3.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response carries the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Concurrency

Most resources in the system are first-class records carrying a standard set of system-managed properties:

- `id` — a unique, server-minted identifier formatted as a UUID. It carries no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — a system-managed integer that begins at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control.

Two entities are deliberately leaner. A `Verification` and a `LedgerEntry` are immutable audit records: each carries only `id` and `created_at`. Neither has an `updated_at` field and neither has a `version` field, because once written they are never modified.

**Logical clock.** All date-driven behavior in the system — due-date crossing, aging classification, and fee accrual — reads a server-maintained logical clock rather than wall-clock time. The clock's startup default is `2026-05-01T00:00:00Z`, and before any administrative set call it reads exactly this value and never falls back to real time. An administrative test-driving capability advances the clock to a supplied instant carried as `to_iso8601`; advancing it recomputes aging classification and automatically moves any now-past-due funded invoices into their overdue state, as described in Section 3.

**Optimistic Concurrency Control.** Two write operations are guarded by OCC against the parent `Client`, because both consume or move denormalized client balances that other writers may have already changed. In each case the request body must carry `expected_client_version`, a non-optional field whose value is the `version` of the target client that the caller last observed.

- When funding a purchase batch, the request must carry `expected_client_version` matching the funding client's current `version`. If another funding has advanced principal against this client since the caller last read it — moving `funded_advance_outstanding_cents` and bumping `version` — the caller's view of the client's credit headroom and concentration capacity is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any invoice is funded.
- When posting a collection against an invoice, the request must likewise carry `expected_client_version` matching the owning client's current `version`. If a prior settlement or buyback has already moved the client's reserve balance since the caller's last read, the posting would be applied against a stale reserve and ledger snapshot, so it is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field; endpoints not named above perform their mutations without an OCC check.

### 2.5. Path Resolution and Referential Integrity

When an endpoint addresses a resource by an identifier in its path, the server resolves every such identifier left-to-right (program, then client, debtor, invoice, relationship, batch, or posting as applicable) and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same `ERR_NOT_FOUND` governs foreign-key references supplied in a request body: a `program_id`, `client_id`, `debtor_id`, `invoice_id`, or any member of an `invoice_ids` array that does not resolve causes the create or action to be rejected as not found.

### 2.6. Request Validation Order

When more than one validation could apply to a request, the checks are evaluated in a fixed priority order so that the surfaced error is deterministic. The order is:

1. Authentication of the headers (`ERR_UNAUTHENTICATED`).
2. Authorization of the acting role for the operation (`ERR_UNAUTHORIZED`).
3. Existence of all path resources, resolved left-to-right (`ERR_NOT_FOUND`).
4. Existence of all foreign-key references in the body (`ERR_NOT_FOUND`).
5. Structural validity of the body — required fields present and well-typed, enum values within their allowed sets, `face_amount_cents` greater than zero, any `amount_cents` greater than zero, `due_date` strictly later than `issue_date`, and advance and concentration rates within range (`ERR_INVALID_REQUEST`, HTTP 422).
6. Invoice-number uniqueness on invoice submission (`ERR_DUPLICATE_INVOICE_NUMBER`, HTTP 409).
7. Relationship uniqueness on relationship creation (`ERR_DUPLICATE_RELATIONSHIP`, HTTP 409).
8. Optimistic-concurrency version match on the two guarded writes (`ERR_STALE_VERSION`, HTTP 412).
9. Segregation of duties on batch funding (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403).
10. State validity — the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409).

The remaining business checks (party-approval, notice posture, verification match, funding eligibility, concentration, debtor ceiling, credit limit, buyback eligibility, recourse grace, write-off eligibility, client-close balances, and overpayment) are evaluated within the workflow they guard, after the foregoing structural and state checks have passed. Their trigger conditions are described alongside the workflows in Section 3 and in the cross-cutting principles below.

### 2.7. Monetary Precision and Rounding

All monetary quantities are integer counts of cents in the program's `currency`. Wherever a fractional cent would otherwise arise — most importantly when computing the advance amount as a fraction of face value, and when computing per-diem fee accruals — the result is rounded to a whole number of cents using the round-half-up method. The reserve is always computed as the exact integer remainder of face value minus the advance, so that face equals advance plus reserve with no rounding drift. Rates and multipliers (`default_fee_rate_per_day`, `tier2_multiplier`, `tier3_multiplier`, `advance_rate_pct`, `fee_rate_per_day`, `requested_advance_rate_pct`, `approved_advance_rate_pct`, `concentration_limit_pct`, and `default_concentration_limit_pct`) preserve their input precision.

### 2.8. Reserve, Exposure, and the Append-Only Ledger

The platform maintains several denormalized balances that must always reconcile to the underlying invoices. On each client, `reserve_balance_cents` is the sum of `reserve_held_cents` across that client's invoices whose status is `FUNDED`, `OUTSTANDING`, or `SHORT_PAID` — the client equity the factor still holds — and `funded_advance_outstanding_cents` is the sum of `advance_outstanding_cents` across that same set of invoices. On each debtor, `outstanding_face_cents` is the sum of `face_amount_cents` across the debtor's invoices in those same three statuses. These denormalized figures are recomputed whenever an invoice funds, settles, is short-paid and closed out, is bought back, or is written off, and reading a client or debtor recomputes and returns the figure.

Alongside these balances the system keeps an append-only `LedgerEntry` log keyed by `client_id`. Each entry records the `invoice_id` that produced the movement, an `entry_type` drawn from `ADVANCE_DISBURSED`, `RESERVE_HELD`, `FEE_ACCRUED`, `COLLECTION_POSTED`, `REBATE_PAID`, `RESERVE_RELEASED`, `BUYBACK_RECEIVED`, and `WRITE_OFF`, a signed `amount_cents` whose sign follows the convention of its entry type, and a `reserve_balance_after_cents` snapshot capturing the client's `reserve_balance_cents` immediately after the entry. Ledger entries are never modified once written.

### 2.9. Hierarchical Consistency and Cascades

Because invoice settlement and terminalization move money that is also reflected on the parent client and the debtor, a single operation routinely mutates several entities at once. Whenever an invoice transition adjusts a client's reserve or outstanding-advance figures, that client is itself mutated: its `updated_at` is refreshed and its `version` increments. The detailed cascades — what reserve is released, what ledger entries are appended, and in what order — are specified within the relevant workflows in Section 3. Two cascades deserve emphasis here: declaring a debtor insolvent propagates downward to suspend that debtor's noticed relationships and thereby make their funded receivables eligible for write-off or buyback, and fully collecting an invoice cascades from the invoice through the client's balances into the ledger. Both are detailed in Section 3.

### 2.10. Debtor Concentration, Credit Limits, and Aging

Three threshold regimes constrain and classify funded receivables.

The **debtor-concentration** ceiling caps how much of a client's funded portfolio may rest on a single debtor. The applicable ceiling for a candidate invoice is the relationship's `concentration_limit_pct`, or, when that field is null on the relationship, the client's `default_concentration_limit_pct`. The check is performed with exact integer cross-multiplication, with the candidate invoice included on both sides: the debtor's prospective exposure (the debtor's `outstanding_face_cents` plus the candidate's `face_amount_cents`) is compared against the ceiling multiplied by the prospective portfolio (the sum of `face_amount_cents` over the client's invoices in `FUNDED`, `OUTSTANDING`, or `SHORT_PAID` status, plus the candidate's `face_amount_cents`). Funding is rejected only when the prospective debtor exposure is strictly greater than the ceiling times the prospective portfolio; the boundary case where the two are exactly equal is allowed. The comparison is performed by cross-multiplication on integer cents, never by floating-point division.

The **debtor credit ceiling** caps total funded face the factor will accept against one debtor across all clients. The **client credit limit** caps the principal advance outstanding the factor will fund for one client. Both are described as funding preconditions in Section 3.

**Aging classification.** While an invoice is live, its `aging_bucket` is derived from the number of whole days past due at the current logical clock — that is, the floor of the elapsed time between the due date and the clock divided by a 24-hour day (86,400 seconds). The bucket is `CURRENT` when days past due is zero or negative; `DPD_1_30` when days past due is at least 1 and at most 30; `DPD_31_60` when at least 31 and at most 60; `DPD_61_90` when at least 61 and at most 90; and `DPD_90_PLUS` beyond 90 days. The upper edge of each band is inclusive: 30 days past due is `DPD_1_30`, 31 is `DPD_31_60`, 90 is `DPD_61_90`, and 91 is `DPD_90_PLUS`. The bucket is recomputed on every read of an invoice and whenever the logical clock advances.

## 3. Business Logic & Workflows

### 3.1. Program Setup and Party Onboarding

The first object created is a `FactoringProgram`, which holds the factor's configuration. A `PlatformAdmin` creates one by supplying a display `name` and optionally a `currency` (defaulting to `USD`), a `default_fee_rate_per_day` (the base factoring discount rate per day, defaulting to 0.0005, i.e. five hundredths of one percent per day), a `tier2_multiplier` (defaulting to 1.5), a `tier3_multiplier` (defaulting to 2.0), and `recourse_grace_days` (defaulting to 90). A program begins in `ACTIVE` status. The same admin may later suspend a program, moving its `status` to `SUSPENDED`; while suspended, no new funding may occur against any client in the program. Programs occupy the enumerated statuses `ACTIVE` and `SUSPENDED`.

A client is onboarded by either a `PlatformAdmin` or an `UnderwritingOfficer`, who supplies the `program_id` it belongs to, its `legal_name`, and its `requested_advance_rate_pct` — the advance rate the client asks for, which must lie strictly between 0 and 1. A new client starts in `PENDING` status with `approved_advance_rate_pct`, `credit_limit_cents`, `default_concentration_limit_pct`, and `credit_decision_user_id` all unset, and its computed `reserve_balance_cents` and `funded_advance_outstanding_cents` at zero. Clients move through the statuses `PENDING`, `APPROVED`, `REJECTED`, `SUSPENDED`, and `CLOSED`, of which `REJECTED` and `CLOSED` are terminal.

A debtor — the account-debtor who actually owes on the invoices — is likewise onboarded by a `PlatformAdmin` or `UnderwritingOfficer` with its `program_id`, `legal_name`, and a submitted `credit_rating` drawn from `AAA`, `A`, `BBB`, `BB`, or `C`. A new debtor starts `PENDING` with `approved_credit_ceiling_cents`, `credit_decision_user_id` unset, `verification_required` carrying its default of true, and computed `outstanding_face_cents` at zero. Debtors move through `PENDING`, `APPROVED`, `REJECTED`, and `INSOLVENT`, with `REJECTED` terminal.

### 3.2. Underwriting and Credit Decisions

Credit decisions are the exclusive province of the `UnderwritingOfficer`. Deciding a client carries a `decision` field; an approve decision additionally carries `approved_advance_rate_pct`, `credit_limit_cents`, and `default_concentration_limit_pct`. To approve a client it must currently be `PENDING` and its program must be `ACTIVE`, and the body must set `approved_advance_rate_pct` strictly between 0 and 1, `credit_limit_cents` greater than zero, and `default_concentration_limit_pct` greater than 0 and at most 1; on success the client moves `PENDING → APPROVED`, those three values are written from the body, the acting `X-User-ID` is recorded as `credit_decision_user_id` for the later segregation-of-duties check, and the client's `version` increments by one. A reject decision on a `PENDING` client moves it `PENDING → REJECTED` and increments `version`.

Once approved, a client may be suspended by underwriting, moving `APPROVED → SUSPENDED` (after which no new invoice funding is permitted while suspended), and a suspended client may be reinstated, moving `SUSPENDED → APPROVED`; each increments `version`. A client may be closed from either `APPROVED` or `SUSPENDED`, moving to `CLOSED`, but only if both its `funded_advance_outstanding_cents` and its `reserve_balance_cents` are exactly zero; if either is nonzero the close is rejected with `ERR_CLIENT_HAS_OUTSTANDING`. Closing increments `version`.

Deciding a debtor likewise carries a `decision`; an approve additionally carries `approved_credit_ceiling_cents` and `verification_required`. Approval requires the debtor to be `PENDING` and the body to set `approved_credit_ceiling_cents` greater than zero; on success the debtor moves `PENDING → APPROVED`, the ceiling and `verification_required` flag are written from the body, the acting `X-User-ID` is recorded as `credit_decision_user_id`, and `version` increments. A reject moves a `PENDING` debtor to `REJECTED` and increments `version`.

An approved debtor may be declared insolvent by underwriting, moving `APPROVED → INSOLVENT`. This declaration is the origin of a multi-hop cascade. First, every `ClientDebtorRelationship` on this debtor whose `notice_status` is `NOTICED` has its notice posture driven to `SUSPENDED`. Each such newly suspended relationship in turn makes its funded receivables — invoices in `FUNDED` or `OUTSTANDING` status — eligible for the write-off path (when the relationship is `NON_RECOURSE`) or the buyback path (when it is `RECOURSE`), as governed by the invoice transitions in Section 3.6. The debtor's `version` increments by one.

### 3.3. Relationships and Notice of Assignment

A client and a debtor are joined by a `ClientDebtorRelationship`, a many-to-many junction created by a `FundingOfficer` or `UnderwritingOfficer` who supplies the `client_id`, the `debtor_id`, the `recourse_type` (`RECOURSE` or `NON_RECOURSE`), and optionally a per-relationship `concentration_limit_pct`. Under `RECOURSE`, the client must buy back uncollected invoices; under `NON_RECOURSE`, the factor absorbs only debtor-insolvency credit losses, while dilution always remains the client's liability. A new relationship's `notice_status` begins `PENDING`, and its `status` is permanently `ACTIVE` — the relationship lifecycle is carried entirely by `notice_status`, which occupies the enumerated values `PENDING`, `NOTICED`, and `SUSPENDED`. Only one relationship with `status` `ACTIVE` may exist for a given `(client_id, debtor_id)` pair; an attempt to create a duplicate is rejected with `ERR_DUPLICATE_RELATIONSHIP`.

A `FundingOfficer` sends the notice-of-assignment to instruct the debtor to remit directly to the factor. Sending the notice requires the relationship's `notice_status` to be `PENDING` and, as a cross-entity guard, both the client and the debtor to be `APPROVED`; if either party is not approved the request is rejected with `ERR_PARTY_NOT_APPROVED`. On success the posture moves `PENDING → NOTICED` and the relationship `version` increments. A noticed relationship may be suspended by a funding officer (or by the system during the debtor-insolvency cascade), moving `NOTICED → SUSPENDED` and blocking new funding on that relationship. A suspended relationship may be resumed, moving `SUSPENDED → NOTICED`, but only when the debtor is still `APPROVED` — otherwise the resume is rejected with `ERR_PARTY_NOT_APPROVED`. The relationship's notice posture thus cycles `NOTICED → SUSPENDED → NOTICED`; each of these transitions increments `version`.

### 3.4. Invoice Submission and Verification

A `FundingOfficer` submits an invoice for factoring by supplying its `client_id`, `debtor_id`, a client-supplied `invoice_number`, the gross `face_amount_cents` (which must be greater than zero), an `issue_date`, and a `due_date` (which must be strictly later than the issue date). At submission the server resolves and records the `relationship_id` from the `ACTIVE` relationship for that `(client_id, debtor_id)` pair, and the invoice begins in `SUBMITTED` status. The `invoice_number` must be unique per client across all of that client's invoices that are not in `REJECTED` status; a collision is rejected with `ERR_DUPLICATE_INVOICE_NUMBER`. Invoices occupy the statuses `SUBMITTED`, `VERIFIED`, `FUNDED`, `OUTSTANDING`, `SHORT_PAID`, `SETTLED`, `BOUGHT_BACK`, `WRITTEN_OFF`, and `REJECTED`; the terminal statuses are `SETTLED`, `BOUGHT_BACK`, `WRITTEN_OFF`, and `REJECTED`. A submitted invoice that should not proceed may instead be rejected by the funding officer, moving `SUBMITTED → REJECTED` with no side effects.

Verifying an invoice confirms the debtor's obligation. A funding officer verifies by supplying the confirmation `method` — one of `PHONE`, `EMAIL`, `PORTAL`, or `WAIVED` — and the `confirmed_amount_cents` the debtor acknowledges owing. Verification requires the invoice to be `SUBMITTED`. As a cross-entity guard, the governing relationship's `notice_status` must already be `NOTICED`; if not, the request is rejected with `ERR_NOTICE_NOT_SENT`. Furthermore, when the debtor's `verification_required` flag is true, the `confirmed_amount_cents` must equal the invoice's `face_amount_cents` and the `method` must not be `WAIVED`; a mismatch on either count is rejected with `ERR_VERIFICATION_MISMATCH`. On success the invoice moves `SUBMITTED → VERIFIED` and the system creates a `Verification` record carrying the `invoice_id`, the `method`, the `confirmed_amount_cents`, `notice_of_assignment_sent` set to true, and a `verified_at` stamped at the current logical clock.

### 3.5. Batch Funding

Invoices are funded in batches. A `FundingOfficer` first creates a `PurchaseBatch` by supplying the `client_id`, an operator `batch_reference`, and an ordered list of `invoice_ids` — all expected to be `VERIFIED` invoices to be funded together, in the listed array order. A new batch begins in `DRAFT` status, with computed `total_advance_cents` at zero and `failure_error_id` unset; batches occupy the statuses `DRAFT`, `FUNDED`, and `FAILED`, the latter two terminal.

Funding the batch is the capital-deployment step and is the most heavily guarded operation in the system. The request carries `expected_client_version` for the OCC check described in Section 2.4. Beyond the version match, the funding officer's `X-User-ID` must differ from the `credit_decision_user_id` recorded on both the client and the debtor of every invoice in the batch; if the funding officer is the same person who underwrote either party, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Each invoice in `invoice_ids` must be `VERIFIED` and must clear, in array order, the full set of per-invoice funding preconditions described below.

For each invoice reached in order, the system verifies these funding preconditions:

- The invoice is `VERIFIED`, the client is `APPROVED`, and the program is `ACTIVE`; if the client is not approved, the program is suspended, or (as below) the relationship is not noticed, funding is blocked with `ERR_FUNDING_BLOCKED`.
- The governing relationship's `notice_status` is `NOTICED`; otherwise funding is blocked, also with `ERR_FUNDING_BLOCKED`.
- The debtor-concentration check of Section 2.10 passes; otherwise the invoice is rejected with `ERR_CONCENTRATION_EXCEEDED`.
- The debtor credit ceiling holds: the debtor's `outstanding_face_cents` plus this invoice's `face_amount_cents` must not exceed the debtor's `approved_credit_ceiling_cents`; otherwise `ERR_DEBTOR_CEILING_EXCEEDED`.
- The client credit limit holds: this invoice's computed advance must not exceed the client's remaining headroom, namely `credit_limit_cents` minus `funded_advance_outstanding_cents`; otherwise `ERR_CREDIT_LIMIT_EXCEEDED`.

When an invoice clears these checks it moves `VERIFIED → FUNDED` with the funding cascade applied: the system snapshots `advance_rate_pct` from the client's `approved_advance_rate_pct` and `fee_rate_per_day` from the program's `default_fee_rate_per_day`, then computes the advance split. The `advance_amount_cents` is the face value multiplied by the advance rate, rounded half-up to whole cents, and the `reserve_held_cents` is the exact remainder of `face_amount_cents` minus `advance_amount_cents`. The `advance_outstanding_cents` is initialized to the full advance amount, `funded_at` is stamped at the current clock, and the `aging_bucket` is recomputed. The client's `reserve_balance_cents` increases by the held reserve and its `funded_advance_outstanding_cents` increases by the advance, the debtor's `outstanding_face_cents` increases by the face amount, and two ledger entries are appended in this order: an `ADVANCE_DISBURSED` entry followed by a `RESERVE_HELD` entry. The client's `version` increments by one for each invoice funded.

Batch funding is transactional and all-or-nothing. If every listed invoice clears, the batch moves `DRAFT → FUNDED`, its `total_advance_cents` is set to the sum of the funded `advance_amount_cents`, the client's `version` is incremented once per funded invoice, and the batch's own `version` increments. If any invoice fails a funding precondition when it is reached in array order, no invoice in the batch is funded and no client or debtor balance change persists; the batch moves `DRAFT → FAILED`, its `failure_error_id` is set to the `error_id` of the first invoice that failed, and the batch's `version` increments.

### 3.6. Collections, Aging, and the Settlement Waterfall

Once funded, an invoice begins accruing fee against the logical clock and is collected as cash arrives. A `CollectionsOfficer` posts a collection by supplying the `amount_cents` received (greater than zero), the `received_at` date the cash was received, optionally a `payer` of `DEBTOR` (the default) or `CLIENT`, and `expected_client_version` for the OCC check. A posting begins in status `POSTED`; postings occupy the statuses `POSTED` and `REVERSED`. The posted amount may not exceed the invoice's remaining collectible face — that is, `face_amount_cents` minus `dilution_cents` minus the already-collected `amount_collected_cents`; an overpayment is rejected with `ERR_OVERPAYMENT`. The same error guards reversal: a collections officer may reverse a posting (moving `POSTED → REVERSED` and recomputing the invoice's `amount_collected_cents`), but only a posting that is currently `POSTED` may be reversed. The invoice's `amount_collected_cents` is the sum of `amount_cents` over its `POSTED` collection postings; `REVERSED` postings are excluded.

As the logical clock advances past an invoice's `due_date` while it has not been fully collected — that is, while its `amount_collected_cents` is still below `face_amount_cents` minus `dilution_cents` — the system automatically moves the invoice from `FUNDED` to `OUTSTANDING` and recomputes its `aging_bucket`. This crossing happens as a side effect of advancing the clock.

**Provisional fee.** While an invoice is `FUNDED` or `OUTSTANDING`, its `accrued_fee_cents` is a provisional, flat per-diem figure recomputed on every read. It equals the face amount multiplied by `fee_rate_per_day` multiplied by the number of whole days elapsed since funding — that elapsed-day count being the floor of the difference between the current clock and `funded_at` divided by a 24-hour day (86,400 seconds), and never less than zero. The provisional figure applies a single flat rate and ignores aging tiers.

**Full collection and settlement.** When a posting brings the invoice's `amount_collected_cents` to at least its collectible face (`face_amount_cents` minus `dilution_cents`), the invoice settles — moving `FUNDED → SETTLED` or `OUTSTANDING → SETTLED`. Settlement first pins the final fee (described in Section 3.7) using the latest `POSTED` collection `received_at` as the cutoff, then runs the settlement waterfall. The waterfall takes the total collected — the sum of `amount_cents` over `POSTED` postings, ordered by `received_at` ascending and breaking ties by creation time ascending — and fills three buckets in this pinned order: first, `principal_applied_cents` is the lesser of the collected total and the `advance_amount_cents`; the collected total is then reduced by that amount, and `fee_applied_cents` is the lesser of what remains and the final fee; the remainder after that, floored at zero, is the `rebate_cents` released to the client. The `fee_shortfall_cents` is the final fee minus the fee actually applied. After the waterfall, the invoice's `advance_outstanding_cents` becomes the `advance_amount_cents` minus the `principal_applied_cents`.

Settlement records a `Settlement` child carrying the `invoice_id`, the `collected_total_cents`, the `principal_applied_cents`, the `fee_applied_cents`, the `rebate_cents`, and the `fee_shortfall_cents`; it pins `final_fee_cents` on the invoice and drives `advance_outstanding_cents` to zero. The cascade then reaches the client: its `reserve_balance_cents` decreases by the invoice's `reserve_held_cents` and its `funded_advance_outstanding_cents` decreases by the `advance_amount_cents`, while the debtor's `outstanding_face_cents` decreases by the `face_amount_cents`. Finally the system appends three ledger entries — `FEE_ACCRUED`, `REBATE_PAID`, and `RESERVE_RELEASED` — each carrying its `reserve_balance_after_cents` snapshot. If `fee_shortfall_cents` is greater than zero, the system creates a `CHARGEBACK_FEE` `Adjustment` for the shortfall, billing the uncovered fee to the client. The client's `version` increments by one.

**Short pay.** When an outstanding invoice has collected something but not enough — that is, its `amount_collected_cents` is greater than zero but still below its collectible face — a collections officer may close out collection, moving `OUTSTANDING → SHORT_PAID`. This runs the partial settlement waterfall in the same pinned principal-then-fee-then-rebate order, sets `advance_outstanding_cents` to `advance_amount_cents` minus `principal_applied_cents`, and pins `final_fee_cents` using the latest `POSTED` `received_at` as the cutoff. Unlike a full settlement, the client's `reserve_balance_cents` and `funded_advance_outstanding_cents` remain in place because residual advance is still at risk pending buyback or write-off. The system appends a `COLLECTION_POSTED` ledger entry followed by a `FEE_ACCRUED` entry, and the client's `version` increments.

### 3.7. Final Fee, Recourse Buyback, and Write-Off

**Final fee.** When an invoice terminalizes — on settlement, short-pay, buyback, or write-off — its `final_fee_cents` is pinned as a tiered, escalating per-diem figure and never recomputed thereafter. The cutoff date is the latest `POSTED` collection `received_at` for the settlement and short-pay paths, and the current logical clock for a buyback or write-off that has no qualifying posting. The number of whole financed days is the floor of the difference between the cutoff and `funded_at` over a 24-hour day (86,400 seconds), never less than zero. That day count is split into three tiers: the first tier is the lesser of the day count and 30 days; the second tier is the day count beyond 30, capped at a further 30 days (that is, the lesser of the day count minus 30 and 30, floored at zero); and the third tier is any days beyond 60 (the day count minus 60, floored at zero). The first tier's fee is the face amount times `fee_rate_per_day` times the first tier's days; the second tier's fee is the face amount times `fee_rate_per_day` times `tier2_multiplier` times the second tier's days; the third tier's fee is the face amount times `fee_rate_per_day` times `tier3_multiplier` times the third tier's days. Each tier's fee is rounded half-up to whole cents independently, and only then are the three rounded tier amounts summed to give `final_fee_cents`. This per-tier-round-then-sum order is the pinned mode and diverges from the flat provisional accrual once the financed span exceeds 30 days.

**Recourse buyback.** A `CollectionsOfficer` triggers a buyback by supplying a `trigger_reason` of `RECOURSE_OVERDUE`, `DEBTOR_DISPUTE`, or `CLIENT_REQUEST`. A buyback may be taken from a `SHORT_PAID` invoice, in which case it is permitted when the relationship is `RECOURSE`, or when a `DILUTION` `Adjustment` exists on the invoice (dilution remains the client's liability even under `NON_RECOURSE`); if neither holds the request is rejected with `ERR_NON_RECOURSE_NO_BUYBACK`. A buyback may also be taken from an `OUTSTANDING` invoice, but only when the relationship is `RECOURSE` — otherwise `ERR_NON_RECOURSE_NO_BUYBACK` — and only after the recourse grace window has elapsed, namely when the current clock is later than the `due_date` plus the program's `recourse_grace_days`; if the grace window is still active the request is rejected with `ERR_RECOURSE_GRACE_ACTIVE`.

On a permitted buyback the invoice moves to `BOUGHT_BACK`. The system pins the final fee using the current clock as the cutoff, then computes the uncovered fee as the final fee minus any fee already covered by a prior settlement run (the `fee_applied_cents` of any prior waterfall, or zero if none), floored at zero. The `buyback_amount_cents` the client must remit to make the factor whole is the invoice's `advance_outstanding_cents` plus that uncovered fee, and `reserve_released_cents` equals the invoice's `reserve_held_cents`. The system creates a `Buyback` record carrying the `invoice_id`, the `trigger_reason`, the computed `buyback_amount_cents`, and the `reserve_released_cents`, created directly in its only status, `COMPLETED`, reflecting synchronous remittance. The client's `reserve_balance_cents` decreases by the released reserve and its `funded_advance_outstanding_cents` decreases by the invoice's `advance_outstanding_cents`, the invoice's own `advance_outstanding_cents` goes to zero, and the debtor's `outstanding_face_cents` decreases by the `face_amount_cents`. Two ledger entries are appended in order — `BUYBACK_RECEIVED` then `RESERVE_RELEASED` — and the client's `version` increments.

**Write-off.** An `UnderwritingOfficer` writes off an uncollectible receivable when the factor must absorb the loss. A write-off may be taken from `OUTSTANDING` or from `SHORT_PAID`, and in both cases it is eligible only when the relationship is `NON_RECOURSE`, the debtor's status is `INSOLVENT`, and no `DILUTION` `Adjustment` exists on the invoice; if any of these does not hold the request is rejected with `ERR_WRITEOFF_NOT_ELIGIBLE`. On a permitted write-off the invoice moves to `WRITTEN_OFF`, its `final_fee_cents` is pinned to the accrued fee at the write-off date using the current clock as the cutoff, the client's `reserve_balance_cents` decreases by the `reserve_held_cents` and its `funded_advance_outstanding_cents` decreases by the `advance_outstanding_cents`, the invoice's `advance_outstanding_cents` goes to zero, and the debtor's `outstanding_face_cents` decreases by the `face_amount_cents`. The factor absorbs the outstanding-advance loss: a `WRITE_OFF` ledger entry is appended followed by a `RESERVE_RELEASED` entry, and the client's `version` increments.

### 3.8. Adjustments

A `CollectionsOfficer` or `FundingOfficer` records an `Adjustment` against an invoice by supplying its `type`, an `amount_cents` (greater than zero), and a free-text `reason`. The `type` is one of `DILUTION` (a short-ship or dispute that reduces collectible face), `CREDIT_MEMO` (a client-issued credit), or `CHARGEBACK_FEE` (an uncovered factor fee billed to the client). The invoice's `dilution_cents` — which reduces the collectible face used throughout collection and settlement — is recomputed as the sum of `amount_cents` over adjustments whose `type` is `DILUTION` or `CREDIT_MEMO`. As noted in Section 3.6, a settlement with a positive `fee_shortfall_cents` itself creates a `CHARGEBACK_FEE` adjustment automatically.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that act on or transition an existing resource return `200 OK`. The table below is a routing summary only — the request payloads, response contents, and side effects for each operation are defined by the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/factoring/programs` | Create factoring program | PlatformAdmin |
| GET | `/factoring/programs` | List factoring programs | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/programs/{programId}` | Read a program | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/programs/{programId}/suspend` | Suspend a program | PlatformAdmin |
| POST | `/factoring/clients` | Onboard a client | PlatformAdmin, UnderwritingOfficer |
| GET | `/factoring/clients` | List clients | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/clients/{clientId}` | Read a client | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/clients/{clientId}/credit-decision` | Underwriting credit decision on a client | UnderwritingOfficer |
| POST | `/factoring/clients/{clientId}/suspend` | Suspend a client | UnderwritingOfficer |
| POST | `/factoring/clients/{clientId}/reinstate` | Reinstate a suspended client | UnderwritingOfficer |
| POST | `/factoring/clients/{clientId}/close` | Close a client | UnderwritingOfficer |
| GET | `/factoring/ledger-entries` | List ledger entries | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/ledger-entries/{ledgerEntryId}` | Read a single ledger entry | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/debtors` | Onboard a debtor | PlatformAdmin, UnderwritingOfficer |
| GET | `/factoring/debtors` | List debtors | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/debtors/{debtorId}` | Read a debtor | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/debtors/{debtorId}/credit-decision` | Underwriting credit decision on a debtor | UnderwritingOfficer |
| POST | `/factoring/debtors/{debtorId}/declare-insolvent` | Declare a debtor insolvent | UnderwritingOfficer |
| POST | `/factoring/relationships` | Create a client-debtor relationship | FundingOfficer, UnderwritingOfficer |
| GET | `/factoring/relationships` | List relationships | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/relationships/{relationshipId}` | Read a relationship | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/relationships/{relationshipId}/send-notice` | Send notice-of-assignment | FundingOfficer |
| POST | `/factoring/relationships/{relationshipId}/suspend` | Suspend a relationship | FundingOfficer |
| POST | `/factoring/relationships/{relationshipId}/resume` | Resume a suspended relationship | FundingOfficer |
| POST | `/factoring/invoices` | Submit an invoice for factoring | FundingOfficer |
| GET | `/factoring/invoices` | List invoices | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/invoices/{invoiceId}` | Read an invoice | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/invoices/{invoiceId}/verify` | Verify an invoice | FundingOfficer |
| POST | `/factoring/invoices/{invoiceId}/reject` | Reject a submitted invoice | FundingOfficer |
| GET | `/factoring/verifications` | List verifications | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/verifications/{verificationId}` | Read a single verification | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/invoices/{invoiceId}/postings` | Post a collection against an invoice | CollectionsOfficer |
| GET | `/factoring/collection-postings` | List collection postings | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/collection-postings/{postingId}` | Read a collection posting | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/postings/{postingId}/reverse` | Reverse a posted collection | CollectionsOfficer |
| POST | `/factoring/invoices/{invoiceId}/adjustments` | Record an adjustment | CollectionsOfficer, FundingOfficer |
| GET | `/factoring/adjustments` | List adjustments | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/adjustments/{adjustmentId}` | Read a single adjustment | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/invoices/{invoiceId}/close-collection` | Close a partially-collected invoice as short-paid | CollectionsOfficer |
| POST | `/factoring/invoices/{invoiceId}/buyback` | Client recourse buyback of an invoice | CollectionsOfficer |
| GET | `/factoring/buybacks` | List buybacks | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/buybacks/{buybackId}` | Read a single buyback | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/invoices/{invoiceId}/write-off` | Write off an uncollectible invoice | UnderwritingOfficer |
| GET | `/factoring/settlements` | List settlements | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/settlements/{settlementId}` | Read a single settlement | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/purchase-batches` | Create a funding batch | FundingOfficer |
| GET | `/factoring/purchase-batches` | List purchase batches | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| GET | `/factoring/purchase-batches/{batchId}` | Read a purchase batch | PlatformAdmin, UnderwritingOfficer, FundingOfficer, CollectionsOfficer |
| POST | `/factoring/purchase-batches/{batchId}/fund` | Fund all verified invoices in a batch | FundingOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_RELATIONSHIP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOTICE_NOT_SENT` | 409 Conflict |
| `ERR_PARTY_NOT_APPROVED` | 409 Conflict |
| `ERR_VERIFICATION_MISMATCH` | 409 Conflict |
| `ERR_FUNDING_BLOCKED` | 409 Conflict |
| `ERR_CONCENTRATION_EXCEEDED` | 409 Conflict |
| `ERR_DEBTOR_CEILING_EXCEEDED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_NON_RECOURSE_NO_BUYBACK` | 409 Conflict |
| `ERR_RECOURSE_GRACE_ACTIVE` | 409 Conflict |
| `ERR_WRITEOFF_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CLIENT_HAS_OUTSTANDING` | 409 Conflict |
| `ERR_OVERPAYMENT` | 409 Conflict |
