# Currency Transaction Reporting & Exemption Management API — Product Requirements Document

## 1. Introduction

Bank Secrecy Act operations teams live under two simultaneous pressures: regulators expect every reportable cash movement to surface as a Currency Transaction Report within hard statutory deadlines, and legitimate high-volume cash customers expect not to be buried under duplicative filings. This document specifies the Currency Transaction Reporting & Exemption Management API, the system of record a bank's BSA operations group uses to reconcile those pressures. The API captures every cash transaction and cash-funded monetary instrument sale across branches, aggregates activity per customer per calendar day, decides which customer-days demand a CTR, and tracks each report from auto-created draft through validation, filing, regulator acknowledgement, and—when the underlying facts change—correction by amendment.

The same platform governs the exempt-person program that keeps routine commercial cash activity out of the reporting stream. Phase I and Phase II designations carry different eligibility bases, different directional coverage, and a mandatory annual review; the system continuously re-evaluates whether an active exemption actually shields a customer-day from reporting, and it unwinds that shielding the moment an exemption lapses or is revoked. Around those two pillars the API wraps the compliance perimeter examiners expect: a structuring detector that watches five-day windows for sub-threshold splitting, a tamper-evident append-only audit ledger with hash-chain verification, a logical clock that makes every deadline and retention computation deterministic, and first-class support for regulator examinations from case intake through finding remediation.

Everything in the system is time-driven in a way wall clocks cannot be: deadlines run off calendar-day arithmetic anchored to a logical UTC clock the operations team controls, every mutation and every automatic cascade is recorded exactly once in the audit trail, and segregation of duties is enforced mechanically at each step where banking regulation forbids one person from both preparing and approving a control.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply to every resource and every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose authenticated role is not in the target endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles, spelled exactly as follows: `SystemAdmin`, `BranchManager`, `Teller`, `ComplianceAnalyst`, `BSAOfficer`, and `Examiner`.

For all six roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: when `X-User-Role` is `SystemAdmin`, `BranchManager`, `Teller`, `ComplianceAnalyst`, `BSAOfficer`, or `Examiner`, the server may record the identifier (for example, as `validated_by_id` on a CTR, `requested_by_id` and `designated_by_officer_id` on an ExemptionDesignation, or `filed_by_id` on a filed CTR where a state transition writes it) but never compares it to any entity's `id`. Segregation-of-duties checks compare `X-User-ID` against those recorded operator identifiers, never against resource identifiers.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter sets the number of items skipped before the page begins and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Because all `created_at` values read the logical clock, creation order is stable and ties cannot arise within a test run.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock, Business Dates, and Deadline Arithmetic

All time in the system reads a single logical UTC clock, never wall-clock time. Before the clock has been set by any call, the logical clock starts at exactly `2026-08-01T00:00:00Z`. A `SystemAdmin` advances it through an admin-only test-driving capability that accepts a target instant `to_iso8601` and sets the current logical time to that instant. Every system-managed timestamp—`created_at`, `updated_at`, `filed_at`, `acknowledged_at`, `voided_at`, `referred_at`, `designated_at`, `last_reviewed_at`, `last_recomputed_at`—reads this logical clock at the moment it is written.

Every cash transaction and monetary instrument sale carries a `business_date`: the UTC calendar date, in `YYYY-MM-DD` form, of its `occurred_at` timestamp. Aggregation, structuring detection windows, exemption eligibility windows, and filing deadlines are all computed on these UTC calendar dates. The system treats every UTC date as a business day; there is no holiday table.

Deadline and window arithmetic is always expressed in whole calendar days added to or subtracted from a date. The CTR electronic deadline is the business date plus 15 calendar days; the paper deadline is the business date plus 25 calendar days; an amendment is permitted only while the current logical date is on or before the business date plus 45 days; an exemption's next annual review falls due on the UTC date 365 days after its designation or last successful review; a monetary instrument record must be retained until exactly five years after its sale timestamp.

### 2.5. Common Resource Properties

Every primary resource—Branch, Customer, CashTransaction, MonetaryInstrumentSale, DailyCashAggregation, CTR, ExemptionDesignation, StructuringAlert, ExaminationCase, and ExaminationFinding—carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation from the logical clock.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations driven by automatic cascades.

The AuditEvent resource is the deliberate exception. Audit events are append-only and immutable once written, so an AuditEvent carries only `id` and `created_at` from the common set; `updated_at` and `version` are absent from AuditEvent responses.

### 2.6. Nested Resource Retrieval

Requests that target nested resources validate path identifiers sequentially from left to right, rejecting immediately with the per-entity 404 error for the first identifier that fails to resolve. A request to record a finding under a non-existent examination case is rejected with `ERR_CASE_NOT_FOUND` before the finding payload is examined; a request against a non-existent exemption designation is rejected with `ERR_EXEMPTION_NOT_FOUND`; analogous lookups surface `ERR_BRANCH_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_INSTRUMENT_SALE_NOT_FOUND`, `ERR_AGGREGATION_NOT_FOUND`, `ERR_CTR_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, or `ERR_FINDING_NOT_FOUND` according to the path segment that failed. Body-supplied foreign keys are checked in the order the endpoint declares them: on cash transaction and instrument sale creation the `customer_id` reference is resolved first (yielding `ERR_CUSTOMER_NOT_FOUND` when unresolvable), then the `branch_id` reference (yielding `ERR_BRANCH_NOT_FOUND`).

### 2.7. The Append-Only Audit Ledger and Hash Chain

Every successful mutating call appends exactly one AuditEvent, whose `action` records the endpoint template of the call (for example, the literal string `POST /cash-transactions`) and whose `actor_role` and `actor_id` record the `X-User-Role` and `X-User-ID` of the caller. Automatic system mutations append one additional AuditEvent each: CTR auto-creation, auto-voiding of a no-longer-required CTR, and auto-flagging of a diverged CTR as amendment-required each append an event with `actor_role` set to `SYSTEM` and `action` set to `SYSTEM_AUTO`; transitions driven by the clock sweep append an event with `actor_role` set to `SYSTEM` and `action` set to `SYSTEM_SWEEP`.

Each event carries a monotonically increasing `sequence_no` that starts at 1 for the genesis event and grows by exactly one per event with no gaps, an `entity_type` and `entity_id` identifying the primary mutated record, and a `details` object summarizing the mutation as a before-and-after picture plus a list of its cascade side effects. Events are chained by hash: each event's `prev_hash` is the `event_hash` of the preceding event, with the genesis event using sixty-four `0` characters. The `event_hash` itself is the lowercase-hex SHA-256 of the concatenation of `prev_hash`, a pipe character, the `sequence_no`, a pipe character, the `action`, a pipe character, the `entity_type`, a pipe character, the `entity_id`, a pipe character, and the canonical JSON of `details`—canonical meaning keys sorted and separators reduced to a bare comma and colon with no whitespace.

Chain verification replays all events in ascending `sequence_no` order, recomputes each `event_hash`, and reports the chain as valid only when every recomputed hash matches, every `prev_hash` linkage is exact, and the sequence runs gap-free from 1. The verification capability is exposed to `SystemAdmin`, `BSAOfficer`, and `Examiner` callers and returns `chain_valid` together with `events_checked`, the number of events replayed.

### 2.8. Derived Aggregations and the Recompute Cascade

The DailyCashAggregation is a server-maintained projection, never written directly by any client. A row is created lazily on the first contributing record for a given customer and business date, and the pair (`customer_id`, `business_date`) is unique across all aggregation rows. Every create or void of a cash transaction or monetary instrument sale recomputes the affected row immediately within the same request; the system is strictly consistent—every mutation and the full cascade it triggers commit atomically, and the clock sweep runs synchronously within the call that advances the clock.

Aggregation recompute feeds a second derivation, CTR reportability, which may in turn create, void, or flag CTR records without any client request. Exemption state changes likewise propagate: approval, annual-review completion, revocation, and the clock sweep's transition of a designation to `REVIEW_DUE` each re-evaluate reportability across the trailing 45 calendar dates for that customer, voiding now-covered draft and validated CTRs or auto-creating newly-required ones. Each of those automatic CTR mutations appends its own `SYSTEM_AUTO` AuditEvent per §2.7, and each swept exemption transition appends a `SYSTEM_SWEEP` event. Every automatic mutation of a versioned resource refreshes that resource's `updated_at` and increments its `version` just as a client-driven mutation would.

### 2.9. Optimistic Concurrency Control

Three write operations require the caller to present the version of the parent record it last observed, protecting against lost updates where another writer has advanced the record in the meantime. Each uses its own field name, and in every case the field is non-optional and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412):

- Updating a customer profile requires `expected_customer_version` matching the customer's current `version`. If another BranchManager has patched the customer since the caller last read it, the update is rejected.
- Creating a correction amendment against a CTR requires `expected_ctr_version` matching that CTR's current `version`. If the CTR's version has advanced since the filing officer last observed it—for instance because another officer has already superseded it—the amendment is rejected.
- Completing an annual review of an exemption designation requires `expected_exemption_version` matching the designation's current `version`, since the eligibility snapshot the reviewer relied on may no longer reflect the designation's state.

Endpoints not listed above do not accept a version field at all.

### 2.10. Validation Ordering

Every endpoint applies the same fixed priority order when multiple checks could fail on one request, so the surfaced error is deterministic:

1. Authentication: the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role, else `ERR_UNAUTHENTICATED`.
2. Authorization: the role appears in the endpoint's authorized-roles list, else `ERR_UNAUTHORIZED`.
3. Request shape: the body is a JSON object, all required input fields are present, types and enum values are valid, an examination scope satisfies `scope_start_date` strictly earlier than `scope_end_date`, and a manually opened alert window has its start on or before its end with a span of at most 31 days—any failure yields `ERR_INVALID_REQUEST`.
4. Existence: path identifiers resolve left-to-right with the per-entity 404, then body foreign-key references resolve (`customer_id` before `branch_id` on transaction and sale creation), then a finding's `target_id` resolves against the entity type named by `target_type` (else `ERR_FINDING_TARGET_NOT_FOUND`).
5. Optimistic concurrency: the supplied expected-version field equals the parent record's current `version`, else `ERR_STALE_VERSION`.
6. State and status checks: the requested action is a valid transition from the record's current status (else `ERR_INVALID_STATE_TRANSITION`); the receiving branch is `ACTIVE` when posting to it (else `ERR_BRANCH_INACTIVE`); the subject customer is `ACTIVE` when posting a transaction, sale, or exemption designation for them (else `ERR_CUSTOMER_NOT_ACTIVE`, with the customer checked before the branch); a cash transaction void target is not already `VOIDED` (else `ERR_TRANSACTION_ALREADY_VOIDED`); a CTR amendment target is in `FILED`, `ACKNOWLEDGED`, or `AMENDMENT_REQUIRED` (else `ERR_CTR_NOT_AMENDABLE`); a customer close is not blocked by open items (else `ERR_CUSTOMER_HAS_OPEN_ITEMS`); a case close is not blocked by unverified findings (else `ERR_EXAMINATION_HAS_OPEN_FINDINGS`); and finding creation is permitted only while the parent case is in `FIELDWORK` or `FINDINGS_ISSUED` (else `ERR_INVALID_STATE_TRANSITION`).
7. Business safety: exemption approval is refused while the customer has an alert in `OPEN` or `UNDER_REVIEW` (else `ERR_OPEN_ALERT_BLOCKS_EXEMPTION`); segregation-of-duties checks refuse self-completion of a control step (else `ERR_SEGREGATION_OF_DUTIES`).
8. Business constraints: phase-to-customer-type compatibility (else `ERR_EXEMPTION_PHASE_MISMATCH`), no second live designation for the customer (else `ERR_DUPLICATE_ACTIVE_EXEMPTION`), Phase I basis (else `ERR_PHASE_I_BASIS_INVALID`), Phase II eligibility (else `ERR_PHASE_II_INELIGIBLE`), case-number uniqueness (else `ERR_DUPLICATE_CASE_NUMBER`), positive amounts (else `ERR_AMOUNT_NOT_POSITIVE`), money-order limit (else `ERR_INSTRUMENT_LIMIT_EXCEEDED`), CTR completeness at validation (else `ERR_CTR_INCOMPLETE`), and monetary-instrument recordkeeping completeness (else `ERR_INSTRUMENT_RECORD_INCOMPLETE`).
9. Business temporal rules: `occurred_at` not later than the current logical clock (else `ERR_OCCURRED_AT_IN_FUTURE`), same-day void windows (else `ERR_VOID_WINDOW_EXPIRED`), the 45-day amendment window (else `ERR_AMENDMENT_WINDOW_EXPIRED`), manual alert window overlap (else `ERR_ALERT_WINDOW_OVERLAP`), and examination scope overlap (else `ERR_CASE_SCOPE_OVERLAP`).
10. Fiscal consistency at filing: the frozen CTR snapshot still equals the live aggregation totals, else `ERR_CTR_SNAPSHOT_STALE`.

All monetary amounts are integer cents everywhere in the API; there are no fractional-cent values and no rounding in aggregation arithmetic. The single rounding operation in the system is the per-instrument fee computation of §3.3, which rounds half-up to whole cents per instrument before any summation.

## 3. Business Logic & Workflows

### 3.1. Branch and Customer Master Data

A `SystemAdmin` creates branches. Each branch records a display `name`, a `branch_code` that must be unique across all branches and is immutable once created, and an optional `region` label that defaults to null when omitted. Every branch carries a system-managed `status` of `ACTIVE` or `INACTIVE` and is born `ACTIVE`. A `SystemAdmin` may deactivate an `ACTIVE` branch, moving it `ACTIVE → INACTIVE`, and may later reactivate an `INACTIVE` branch, moving it `INACTIVE → ACTIVE`; both transitions append an audit event. Posting cash activity to an `INACTIVE` branch is refused with `ERR_BRANCH_INACTIVE`. The branch list endpoint accepts an optional `status` filter alongside the standard pagination parameters.

A `BranchManager` creates customers with a `legal_name`, an optional `tin` (taxpayer identification number, nullable at creation but required before any CTR for the customer can be validated), a `customer_type`, and the `account_opened_date` on which the customer relationship began. The `customer_type` is one of `INDIVIDUAL`, `BUSINESS_NONLISTED`, `BUSINESS_LISTED`, `BANK`, `GOVERNMENT_AGENCY`, or `PAYROLL_CUSTOMER`, and it is immutable after creation because it determines which exemption phase the customer may hold. A customer is born `ACTIVE` and carries two system-maintained fields: `structuring_referral_count`, the number of structuring alerts ever referred for the customer (initially zero), and `active_exemption_id`, the `id` of the designation currently in `ACTIVE` status for the customer (null when none).

A `BranchManager` may update a customer's `legal_name` or `tin` through a profile patch that increments the customer's `version` by one and appends an audit event; per §2.9 the patch must carry `expected_customer_version`. The customer's system-managed `status`—`ACTIVE`, `SUSPENDED`, or `CLOSED`—is moved `ACTIVE → SUSPENDED` on suspension and `SUSPENDED → ACTIVE` on reactivation. Closing a customer is permitted from either `ACTIVE` or `SUSPENDED`, moving the customer to the terminal `CLOSED` state, but only when the customer has no open items: no CTR in `DRAFT`, `VALIDATED`, `FILED`, or `AMENDMENT_REQUIRED`, and no structuring alert in `OPEN` or `UNDER_REVIEW`. A close attempted against either kind of open item is rejected with `ERR_CUSTOMER_HAS_OPEN_ITEMS`. Transactions, instrument sales, and exemption designation requests may only be posted for an `ACTIVE` customer; posting for a `SUSPENDED` or `CLOSED` customer is rejected with `ERR_CUSTOMER_NOT_ACTIVE`. The customer list endpoint accepts optional `customer_type` and `status` filters.

### 3.2. Posting Cash Activity at the Teller Line

A `Teller` posts a cash transaction by supplying the `customer_id` on whose behalf the cash moves, the `branch_id` where it moved, a `direction` of `CASH_IN` for a deposit or `CASH_OUT` for a withdrawal, the `amount_cents` moved, the `occurred_at` timestamp, and an optional `conductor_name` naming the person who physically conducted the transaction when that person differs from the customer. The amount must be greater than zero—otherwise the posting is rejected with `ERR_AMOUNT_NOT_POSITIVE`—and `occurred_at` must not be later than the current logical clock, otherwise the posting is rejected with `ERR_OCCURRED_AT_IN_FUTURE`. On acceptance the transaction is born `POSTED`, its `business_date` is derived as the UTC date of `occurred_at`, and `voided_at` remains null.

Posting a cash transaction fires three derivations atomically within the request: the daily aggregation for (`customer_id`, `business_date`) is recomputed as described in §3.4; CTR reportability is re-evaluated with the cascade described there; and when the direction is `CASH_IN`, the structuring detector of §3.7 is evaluated.

A posted transaction may be voided by a `Teller` or a `BranchManager`, optionally recording a `void_reason`. Voiding is a same-day correction mechanism only: the transaction's `business_date` must equal the current logical clock date, otherwise the request is rejected with `ERR_VOID_WINDOW_EXPIRED`; a void attempted on an already-`VOIDED` transaction is rejected with `ERR_TRANSACTION_ALREADY_VOIDED`. A successful void moves the transaction `POSTED → VOIDED`, stamps `voided_at` with the current logical time, recomputes the daily aggregation (voided records contribute nothing), re-evaluates CTR reportability with the full cascade of §3.4, and appends an audit event. The transaction list endpoint filters by `customer_id`, `branch_id`, `business_date`, `direction`, and `status` (each transaction carrying a `status` of `POSTED` or `VOIDED`), all optional.

### 3.3. Monetary Instrument Sales and Recordkeeping

Cash-funded sales of monetary instruments are recorded by a `Teller` with the `customer_id` of the purchaser, the `branch_id` of the selling branch, an `instrument_type` of `CASHIERS_CHECK`, `MONEY_ORDER`, or `TRAVELERS_CHECK`, the `amount_cents` paid in cash, and the `occurred_at` sale timestamp, which must not be later than the current logical clock (`ERR_OCCURRED_AT_IN_FUTURE`). The amount must be positive (`ERR_AMOUNT_NOT_POSITIVE`), and money orders carry a per-instrument cap: a `MONEY_ORDER` with an amount greater than 100000 cents is rejected with `ERR_INSTRUMENT_LIMIT_EXCEEDED`. A sale is born `RECORDED`, derives its `business_date` from `occurred_at`, and counts toward the customer's cash-in aggregation even though no deposit account is involved.

BSA monetary-instrument recordkeeping attaches conditionally. The system computes `record_required` as true exactly when the amount is at least 300000 cents and at most 1000000 cents—the recordkeeping band. When `record_required` is true, all four purchaser fields are mandatory: `purchaser_name`, `purchaser_tin`, `purchaser_address`, and `purchaser_id_number`; a sale in the band missing any of the four is rejected with `ERR_INSTRUMENT_RECORD_INCOMPLETE`. Outside the band the four fields are optional and default to null. Every recorded sale also derives a `retention_until` timestamp exactly five years after `occurred_at`, the statutory retention horizon for the record.

Each sale carries a per-instrument `fee_cents`, computed as the greater of 150 cents and the sale's `amount_cents` multiplied by 50 basis points (that is, multiplied by 50 and divided by 10000), rounded half-up to whole cents. The rounding is applied per instrument first; the daily aggregation's `instrument_fee_total_cents` then sums the already-rounded per-instrument fees. The pinned order matters: rounding each fee and then summing is the implemented rule, and summing amounts first and rounding once is a different result—for two sales of 100100 cents and 99900 cents, per-instrument rounding yields a daily fee total of 1001 cents while sum-then-round yields 1000 cents.

Voiding an instrument sale mirrors voiding a cash transaction: a `Teller` or `BranchManager` may void with an optional `void_reason`, the sale's `business_date` must equal the current logical clock date (`ERR_VOID_WINDOW_EXPIRED`), and a double-void is rejected under the generic state rule with `ERR_INVALID_STATE_TRANSITION`. The void moves the sale `RECORDED → VOIDED`, stamps `voided_at`, recomputes the aggregation including instrument counts and the fee total, re-evaluates CTR reportability, and appends an audit event. The sale list endpoint filters by `customer_id`, `branch_id`, `business_date`, `instrument_type`, and `status` (each sale carrying a `status` of `RECORDED` or `VOIDED`), all optional.

### 3.4. Daily Aggregation and the CTR Reportability Cascade

The DailyCashAggregation row for a (`customer_id`, `business_date`) pair is the single source from which reporting obligations derive. Recompute considers only cash transactions in `POSTED` status and instrument sales in `RECORDED` status for that pair; `VOIDED` records contribute nothing. From that input set the row derives, all in integer cents with no rounding:

- `total_cash_in_cents` — the sum of `amount_cents` over posted transactions with direction `CASH_IN` plus the sum of `amount_cents` over recorded instrument sales.
- `total_cash_out_cents` — the sum of `amount_cents` over posted transactions with direction `CASH_OUT`.
- `transaction_count` — the count of contributing posted cash transactions across both directions.
- `instrument_sale_count` — the count of contributing recorded instrument sales.
- `instrument_fee_total_cents` — the sum of the per-instrument `fee_cents` over contributing sales, rounded per instrument before summing per §3.3.
- `last_recomputed_at` — the logical-clock time of the most recent recompute.

CTR reportability is re-evaluated immediately after every aggregation recompute, in a pinned evaluation order that avoids any circular dependency between CTRs and exemptions. First, the aggregation totals are read. Second, the raw reportability flags are computed ignoring any exemption: `raw_reportable_in` is true exactly when `total_cash_in_cents` is strictly greater than 1000000 cents, and `raw_reportable_out` is true exactly when `total_cash_out_cents` is strictly greater than 1000000 cents. Third, coverage is read from the customer's exemption designation in `ACTIVE` status, of which at most one may exist: `covered_in` is true exactly when such a designation exists and either its `phase` is `PHASE_I` or its `covers_cash_in` is true; `covered_out` is true exactly when such a designation exists and either its `phase` is `PHASE_I` or its `covers_cash_out` is true. Designations in `REVIEW_DUE`, `PENDING_REVIEW`, `DENIED`, or `REVOKED` never cover. Fourth, `ctr_required` is true exactly when the cash-in side is raw-reportable and not covered, or the cash-out side is raw-reportable and not covered.

The distinction between the two coverage variants is material. Under an active Phase I designation both directions are covered, so `ctr_required` is false regardless of the totals. Under an active Phase II designation only one direction is covered—cash-in for a `BUSINESS_NONLISTED` customer, cash-out for a `PAYROLL_CUSTOMER`—so the uncovered direction can still force `ctr_required` true; identical aggregates yield a required CTR under Phase II but none under Phase I.

Flips in `ctr_required` drive the live CTR set for the customer-day without any client request. When `ctr_required` flips from false to true and no live CTR exists for the pair—live meaning status in `DRAFT`, `VALIDATED`, `FILED`, `ACKNOWLEDGED`, or `AMENDMENT_REQUIRED`—the system auto-creates a CTR in `DRAFT` with its snapshot set to the current totals. When `ctr_required` flips from true to false and a live CTR exists in `DRAFT` or `VALIDATED`, that CTR is transitioned to `VOIDED`. And when the recomputed totals diverge from the frozen snapshot of a CTR in `FILED` or `ACKNOWLEDGED`, that CTR is transitioned to `AMENDMENT_REQUIRED`. Each automatic transition appends its own audit event with the `SYSTEM_AUTO` action per §2.7.

### 3.5. The CTR Lifecycle: Validation, Filing, Acknowledgement, Amendment

A CTR reports one customer's cash activity for one business date, and at most one live CTR exists per (`customer_id`, `business_date`) pair. Each CTR records a `filing_type` of `INITIAL` or `CORRECTION`, a `prior_ctr_id` pointing at the superseded report for corrections (null for initial filings), an `amendment_reason` captured from the amendment that created it (null for initial filings), and the snapshot totals `snapshot_cash_in_cents` and `snapshot_cash_out_cents`. While a CTR is in `DRAFT` its snapshot live-refreshes from the aggregation; validation freezes the snapshot. Deadline fields are derived at creation: `due_date_efile` is the business date plus 15 calendar days and `due_date_paper` is the business date plus 25 calendar days, both in `YYYY-MM-DD` form.

Validation is performed by a `ComplianceAnalyst` and moves the CTR `DRAFT → VALIDATED`. Two completeness conditions are enforced at validation, and a failure of either is rejected with `ERR_CTR_INCOMPLETE`: the customer's `tin` must be non-null, and the frozen-or-live snapshot must exceed the reporting threshold on at least one side—`snapshot_cash_in_cents` strictly greater than 1000000 cents or `snapshot_cash_out_cents` strictly greater than 1000000 cents. On success the analyst's `X-User-ID` is recorded as `validated_by_id` and the snapshot freezes. A `ComplianceAnalyst` may also return a validated report to draft, moving it `VALIDATED → DRAFT`, which clears `validated_by_id` to null and refreshes the snapshot from the current aggregation.

Filing is performed by a `BSAOfficer` and moves the CTR `VALIDATED → FILED`. The filing request supplies the `filing_channel`, either `EFILE` or `PAPER`. Segregation of duties is enforced mechanically: the filer's `X-User-ID` must differ from the recorded `validated_by_id`, otherwise the filing is rejected with `ERR_SEGREGATION_OF_DUTIES`. Because aggregation may have moved since validation, filing additionally requires that the frozen snapshot still equal the current aggregation totals; a mismatch is rejected with `ERR_CTR_SNAPSHOT_STALE`. On success the system stamps `filed_at` with the current logical time, records the filer's `X-User-ID` as `filed_by_id`, stores the `filing_channel`, and computes `filed_late`: the filing is late exactly when `filed_at` is strictly later than 23:59:59.999 UTC on the applicable due date—the electronic deadline for `EFILE`, the paper deadline for `PAPER`—so filing on the due date itself is timely. The two channels diverge in practice: the same CTR filed on the same day is late under `EFILE` but timely under `PAPER` whenever the filing date falls after the fifteenth day and on or before the twenty-fifth.

Separately from `filed_late`, which is fixed at filing, each CTR exposes a read-time `is_late` flag: it is true exactly when the CTR's status is `DRAFT` or `VALIDATED` and the current logical date is later than `due_date_efile`. The read-time flag always uses the electronic deadline, even if the report is later filed on paper. Before filing, `filed_late` is null and `is_late` is false.

Regulator acknowledgement is recorded by a `SystemAdmin`, moving a `FILED` report `FILED → ACKNOWLEDGED`, stamping `acknowledged_at` and storing the supplied `regulator_tracking_id`.

Amendment corrects an already-filed report. A `BSAOfficer` files an amendment against a CTR by supplying an `amendment_reason` and, per §2.9, the `expected_ctr_version` matching the CTR's current `version` (a stale observation is rejected with `ERR_STALE_VERSION`). Amendment is permitted only from `FILED`, `ACKNOWLEDGED`, or `AMENDMENT_REQUIRED`—any other status is rejected with `ERR_CTR_NOT_AMENDABLE`—and only while the current logical date is on or before the business date plus 45 days, otherwise the request is rejected with `ERR_AMENDMENT_WINDOW_EXPIRED`. On success the original CTR transitions to the terminal `SUPERSEDED` state with its `version` incremented by one, and a successor CTR is created in `DRAFT` with `filing_type` set to `CORRECTION`, `prior_ctr_id` set to the superseded report's id, `amendment_reason` recorded from the request, and its snapshot taken from the current aggregation. The successor then flows through validation and filing like any other report. Clients can trace a correction lineage through the `prior_ctr_id` filter on the CTR list endpoint.

System-driven transitions complete the machine: per §3.4 a CTR in `FILED` or `ACKNOWLEDGED` moves to `AMENDMENT_REQUIRED` when recomputed totals diverge from its snapshot, and a CTR in `DRAFT` or `VALIDATED` moves to the terminal `VOIDED` state when `ctr_required` flips false—with `validated_by_id` cleared to null when a validated report is voided. The CTR list endpoint accepts optional `customer_id`, `business_date`, `status` (one of the seven CTR statuses), and `prior_ctr_id` filters; the daily-aggregation list endpoint accepts optional `customer_id` and `business_date` filters.

### 3.6. Exempt-Person Designation and Annual Review

A `BSAOfficer` requests an exempt-person designation for a customer by supplying the `phase`, an optional `stock_exchange`, and an optional justification `note`. The phase must be compatible with the customer's `customer_type`: `PHASE_I` is available to `BANK`, `GOVERNMENT_AGENCY`, and `BUSINESS_LISTED` customers; `PHASE_II` is available to `BUSINESS_NONLISTED` and `PAYROLL_CUSTOMER` customers. An incompatible pairing is rejected with `ERR_EXEMPTION_PHASE_MISMATCH`. A customer may hold at most one designation in any of `PENDING_REVIEW`, `ACTIVE`, or `REVIEW_DUE`; a request while one exists is rejected with `ERR_DUPLICATE_ACTIVE_EXEMPTION`. On acceptance the designation is born `PENDING_REVIEW`, the requesting officer's `X-User-ID` is recorded as `requested_by_id`, and the coverage flags are derived from the phase and customer type: `covers_cash_in` is true for `PHASE_I` always and for `PHASE_II` only when the customer is `BUSINESS_NONLISTED`; `covers_cash_out` is true for `PHASE_I` always and for `PHASE_II` only when the customer is `PAYROLL_CUSTOMER`.

Approval is performed by a `BSAOfficer` other than the requester—segregation of duties compares the approver's `X-User-ID` against `requested_by_id` and rejects a match with `ERR_SEGREGATION_OF_DUTIES`. Approval is refused while the customer has any structuring alert in `OPEN` or `UNDER_REVIEW`, surfacing `ERR_OPEN_ALERT_BLOCKS_EXEMPTION`. The eligibility basis then depends on the phase. For `PHASE_I`, the customer's type must be one of `BANK`, `GOVERNMENT_AGENCY`, or `BUSINESS_LISTED`, and a `BUSINESS_LISTED` customer must have a non-null `stock_exchange`; failure surfaces `ERR_PHASE_I_BASIS_INVALID`. For `PHASE_II`, the initial-designation eligibility evaluation must pass, surfacing `ERR_PHASE_II_INELIGIBLE` when it does not.

The Phase II eligibility evaluation anchors a window at the current logical date: the 365 UTC dates from 364 days before the anchor through the anchor itself, inclusive at both ends. Within that window the evaluation counts `qualifying_day_count`, the number of business dates whose aggregation row is raw-reportable in the covered direction ignoring any exemption coverage—`raw_reportable_in` for a `BUSINESS_NONLISTED` customer, `raw_reportable_out` for a `PAYROLL_CUSTOMER`. Because raw reportability ignores coverage, this counting never depends on the designation being evaluated. The evaluation also computes `account_age_days`, the number of days between the date part of the customer's `account_opened_date` and the anchor, and `referred_alert_in_window`, true exactly when a structuring alert in `REFERRED` status exists whose `referred_at` date falls within the window. The initial-designation variant passes exactly when `qualifying_day_count` is at least 5 and `account_age_days` is at least 60; it does not consult referred alerts. Whichever variant runs, the designation stores an `eligibility_snapshot` object capturing `window_start`, `window_end`, `qualifying_day_count`, `account_age_days`, and `referred_alert_in_window` at the moment of evaluation.

On approval the designation moves `PENDING_REVIEW → ACTIVE`: `designated_at` and `last_reviewed_at` are stamped with the current logical time, `designated_by_officer_id` records the approver, `review_due_date` is set to the UTC date 365 days hence, the eligibility snapshot is stored, the customer's `active_exemption_id` is set to this designation, and CTR reportability is recomputed across the trailing 45 calendar dates—any live CTR in `DRAFT` or `VALIDATED` whose day is now fully covered transitions to `VOIDED`. Denial is the other exit from review: a `BSAOfficer` other than the requester (again enforced via `ERR_SEGREGATION_OF_DUTIES`) may deny a `PENDING_REVIEW` designation with a recorded `reason`, moving it to the terminal `DENIED` state.

Annual review is driven by the logical clock. When a `SystemAdmin` advances the clock, the sweep synchronously transitions every `ACTIVE` designation whose `review_due_date` is earlier than the new current date from `ACTIVE` to `REVIEW_DUE`. The transition lapses coverage immediately: the customer's `active_exemption_id` is cleared to null, since a designation in `REVIEW_DUE` does not cover; reportability is then recomputed across the trailing 45 calendar dates, and any newly-required day with no live CTR gets an auto-created `DRAFT` CTR per §3.4. Each swept designation appends a `SYSTEM_SWEEP` audit event, in addition to the single event the clock-advance call itself appends.

Completing an annual review is a `BSAOfficer` action that carries the review `outcome`, an optional `review_note`, and—per §2.9—the `expected_exemption_version` matching the designation's current `version`; a stale observation is rejected with `ERR_STALE_VERSION`. The reviewer must differ from the officer recorded as `designated_by_officer_id`, else `ERR_SEGREGATION_OF_DUTIES`. When `outcome` is `PASS`, the designation's eligibility basis is re-checked: the annual-review variant for `PHASE_II`, and the Phase I basis for `PHASE_I` (including the `stock_exchange` requirement for `BUSINESS_LISTED`), with failures surfacing `ERR_PHASE_II_INELIGIBLE` or `ERR_PHASE_I_BASIS_INVALID` respectively. The annual-review variant passes exactly when `qualifying_day_count` is at least 5 and `referred_alert_in_window` is false—the account-age conjunct drops away, and the referred-alert conjunct appears in its place; because the window anchors at the review date, the same transaction history can pass at designation and fail at review, or vice versa. A passing review moves the designation `REVIEW_DUE → ACTIVE`: `last_reviewed_at` is stamped, `review_due_date` advances 365 days from the current date, the fresh eligibility snapshot is stored, `version` increments by one, the customer's `active_exemption_id` is restored, and reportability recompute across the trailing 45 dates voids now-covered live CTRs in `DRAFT` or `VALIDATED`. When `outcome` is `FAIL`, the designation moves `REVIEW_DUE → REVOKED` with `revocation_reason` set to `REVIEW_FAILED`, `version` increments, and reportability recompute across the trailing 45 dates auto-creates `DRAFT` CTRs for newly-required days.

A `BSAOfficer` may also revoke an `ACTIVE` designation at any time with a recorded `reason`, moving it `ACTIVE → REVOKED` with `revocation_reason` set to `MANUAL_REVOKE`, clearing the customer's `active_exemption_id` to null, and triggering the same trailing-45-date recompute that auto-creates `DRAFT` CTRs for newly-required days. The designation list endpoint accepts optional `customer_id`, `status`, and `phase` filters.

### 3.7. Structuring Detection and Alert Disposition

The structuring detector runs automatically on every posted cash transaction with direction `CASH_IN` and on every recorded monetary instrument sale. Detection uses a five-day window: for a triggering record with business date `d`, the window runs from four days before `d` through `d`, five consecutive UTC dates inclusive. For each date in the window the detector takes the customer's aggregated cash-in cents—posted cash-in transactions plus recorded instrument sales—and fires (creating a StructuringAlert in `OPEN` with `detection_source` set to `AUTO`) exactly when all five of the following hold:

1. The sum of the daily cash-in totals across the window is strictly greater than 1000000 cents.
2. The largest single-day total in the window is at most 1000000 cents—no single reportable day, since the CTR machinery already covers that case.
3. At least two days in the window have a cash-in total greater than zero.
4. Either the contributing records span at least two distinct branches, or at least three days in the window have a cash-in total greater than zero.
5. No existing alert for the customer in `OPEN` or `UNDER_REVIEW` has a window overlapping the new window under closed-interval semantics—two windows sharing at least one date conflict, while windows that touch without sharing a date do not. When this condition fails, detection is silently deduplicated and no new alert row is created.

An auto-created alert records its `window_start_date` and `window_end_date` as the first and last dates of the window, its `detected_amount_cents` as the sum of the daily totals across the window, its `distinct_day_count` as the number of days in the window with cash-in greater than zero, and its `distinct_branch_count` as the number of distinct branches among the contributing records. Its `risk_score` starts at a base of 40, adds 8 points per distinct branch counting at most 4 branches, adds 6 points per distinct day counting at most 5 days, adds 15 points when the largest single-day total falls in the near-threshold band of at least 900000 cents and at most 1000000 cents, adds 10 points per prior referral counting at most 3 prior referrals where the prior count is the customer's `structuring_referral_count` as it stood before this alert, and is capped at a maximum of 100.

A `BSAOfficer` may also open an alert manually—for instance on a teller's tip—by supplying the `customer_id`, the `window_start_date` and `window_end_date`, and a `note`. The manual window's start must be on or before its end with a span of at most 31 days (`ERR_INVALID_REQUEST`), and it must not overlap, under the same closed-interval date semantics, an existing alert in `OPEN` or `UNDER_REVIEW` for the same customer (`ERR_ALERT_WINDOW_OVERLAP`). A manually opened alert is born `OPEN` with `detection_source` set to `MANUAL`, `detected_amount_cents`, `distinct_day_count`, and `distinct_branch_count` all zero until computed, and `risk_score` fixed at 0.

Alert triage is split across roles. A `ComplianceAnalyst` begins review, moving an alert `OPEN → UNDER_REVIEW`. A `BSAOfficer` then dispositions it: dismissal moves `UNDER_REVIEW → DISMISSED` and stores the supplied `disposition_note` as the alert's `note`; referral moves `UNDER_REVIEW → REFERRED` (the terminal state), stamps `referred_at` with the current logical time, stores the supplied `referral_note` as the `note`, and increments the customer's `structuring_referral_count` by one. A `DISMISSED` alert may be returned to active work by a `BSAOfficer`, moving `DISMISSED → UNDER_REVIEW` and replacing the `note` with the supplied input `note`. The alert list endpoint accepts optional `customer_id` and `status` filters, and the audit-event list endpoint accepts optional `entity_type`, `entity_id`, and `actor_id` filters.

Open alerts gate the exemption program per §3.6: an exemption approval is refused while any alert for the customer is in `OPEN` or `UNDER_REVIEW`. Referred alerts feed the annual-review eligibility evaluation through the `referred_alert_in_window` conjunct.

### 3.8. Regulator Examinations and Findings

An `Examiner` opens an examination case by supplying the `regulator`—one of `FINCEN`, `OCC`, `FDIC`, or `STATE`—a `case_number` unique across all examination cases (a duplicate is rejected with `ERR_DUPLICATE_CASE_NUMBER`), and the scope bounds `scope_start_date` and `scope_end_date`. The scope is a half-open interval: it includes the start date and excludes the end date, the start must be strictly earlier than the end (`ERR_INVALID_REQUEST`), and it must not overlap any other case for the same regulator in `OPEN`, `FIELDWORK`, or `FINDINGS_ISSUED`; touching boundaries are allowed, so a scope ending exactly where another begins does not conflict. An overlap is rejected with `ERR_CASE_SCOPE_OVERLAP`. A case is born `OPEN`.

The case lifecycle is driven by the `Examiner`: beginning fieldwork moves `OPEN → FIELDWORK`; issuing findings moves `FIELDWORK → FINDINGS_ISSUED`; reopening fieldwork cycles `FINDINGS_ISSUED → FIELDWORK`; and closing moves `FINDINGS_ISSUED → CLOSED`, the terminal state. Closing is guarded: every finding recorded against the case must be in `VERIFIED` status, otherwise the close is rejected with `ERR_EXAMINATION_HAS_OPEN_FINDINGS`. The case list endpoint accepts optional `regulator` and `status` filters alongside the standard pagination parameters.

Findings are recorded by an `Examiner` against a case that is in `FIELDWORK` or `FINDINGS_ISSUED`—creation at any other case status is rejected with `ERR_INVALID_STATE_TRANSITION`. Each finding belongs to its parent case through the `case_id` recorded from the path, and carries a `severity` of `OBSERVATION`, `DEFICIENCY`, or `VIOLATION`, a polymorphic target identified by `target_type` (one of `CTR`, `EXEMPTION_DESIGNATION`, `STRUCTURING_ALERT`, `MONETARY_INSTRUMENT_SALE`, or `CASH_TRANSACTION`) and `target_id`, and a `description` narrative. The `target_id` must resolve against the entity type named by `target_type`; an unresolvable target is rejected with `ERR_FINDING_TARGET_NOT_FOUND`. A finding is born `OPEN`. The finding list endpoint accepts optional `case_id`, `status`, and `severity` filters.

Remediation is the bank's side of the loop: a `BSAOfficer` remediates an `OPEN` finding, supplying a `remediation_note` that is recorded on the finding, moving it `OPEN → REMEDIATED`—but only while the parent case is in `FIELDWORK` or `FINDINGS_ISSUED`. A finding in `REMEDIATED` then awaits examiner verdict: the `Examiner` either verifies the remediation, moving the finding `REMEDIATED → VERIFIED` (the terminal state), or rejects it, moving the finding `REMEDIATED → OPEN` and replacing the `remediation_note` with the supplied input `note`.

## 4. Endpoint Definitions

Operations that create a new resource—posting a cash transaction or instrument sale, opening an alert or examination case, recording a finding, requesting an exemption designation, or filing a CTR amendment (which creates the successor CTR)—return `201 Created`. Operations that modify an existing resource, including all state-transition actions, return `200 OK`. All endpoints are mounted under `/`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps overdue exemption reviews | SystemAdmin |
| POST | `/branches` | Create a branch | SystemAdmin |
| GET | `/branches` | List branches | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/branches/{id}` | Get a branch | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/branches/{id}/deactivate` | Deactivate a branch | SystemAdmin |
| POST | `/branches/{id}/reactivate` | Reactivate a branch | SystemAdmin |
| POST | `/customers` | Create a customer | BranchManager |
| GET | `/customers` | List customers | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/customers/{id}` | Get a customer | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| PATCH | `/customers/{id}` | Update customer legal name or TIN (OCC on customer version) | BranchManager |
| POST | `/customers/{id}/suspend` | Suspend a customer | BranchManager |
| POST | `/customers/{id}/reactivate` | Reactivate a suspended customer | BranchManager |
| POST | `/customers/{id}/close` | Close a customer with no open items | BranchManager |
| POST | `/cash-transactions` | Post a cash transaction | Teller |
| GET | `/cash-transactions` | List cash transactions (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/cash-transactions/{id}` | Get a cash transaction | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/cash-transactions/{id}/void` | Void a same-day posted transaction | Teller, BranchManager |
| POST | `/monetary-instrument-sales` | Record a cash-funded instrument sale | Teller |
| GET | `/monetary-instrument-sales` | List instrument sales (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/monetary-instrument-sales/{id}` | Get an instrument sale | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/monetary-instrument-sales/{id}/void` | Void a same-day recorded sale | Teller, BranchManager |
| GET | `/daily-aggregations` | List daily cash aggregations (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/daily-aggregations/{id}` | Get one daily aggregation | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/ctrs` | List CTRs (filtered; lineage via prior_ctr_id) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/ctrs/{id}` | Get a CTR | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/ctrs/{id}/validate` | Validate a draft CTR; freezes the snapshot | ComplianceAnalyst |
| POST | `/ctrs/{id}/return-to-draft` | Return a validated CTR to draft | ComplianceAnalyst |
| POST | `/ctrs/{id}/file` | File a validated CTR (EFILE or PAPER) | BSAOfficer |
| POST | `/ctrs/{id}/amendments` | Supersede a filed CTR with a correction successor | BSAOfficer |
| POST | `/ctrs/{id}/acknowledge` | Record regulator acknowledgement | SystemAdmin |
| POST | `/customers/{customer_id}/exemption-designations` | Request an exempt-person designation | BSAOfficer |
| GET | `/exemption-designations` | List designations (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/exemption-designations/{id}` | Get a designation | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/exemption-designations/{id}/approve` | Approve a pending designation after eligibility checks | BSAOfficer |
| POST | `/exemption-designations/{id}/deny` | Deny a pending designation | BSAOfficer |
| POST | `/exemption-designations/{id}/complete-review` | Complete annual review (PASS or FAIL) | BSAOfficer |
| POST | `/exemption-designations/{id}/revoke` | Manually revoke an active designation | BSAOfficer |
| POST | `/structuring-alerts` | Manually open a structuring alert | BSAOfficer |
| GET | `/structuring-alerts` | List alerts (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/structuring-alerts/{id}` | Get an alert | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/structuring-alerts/{id}/begin-review` | Begin compliance review of an alert | ComplianceAnalyst |
| POST | `/structuring-alerts/{id}/dismiss` | Dismiss an alert under review | BSAOfficer |
| POST | `/structuring-alerts/{id}/refer` | Refer an alert under review | BSAOfficer |
| POST | `/structuring-alerts/{id}/reopen` | Reopen a dismissed alert | BSAOfficer |
| POST | `/examination-cases` | Open a regulator examination case | Examiner |
| GET | `/examination-cases` | List examination cases (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/examination-cases/{id}` | Get an examination case | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/examination-cases/{id}/begin-fieldwork` | Begin fieldwork on a case | Examiner |
| POST | `/examination-cases/{id}/issue-findings` | Issue findings on a case | Examiner |
| POST | `/examination-cases/{id}/reopen-fieldwork` | Reopen fieldwork after findings issued | Examiner |
| POST | `/examination-cases/{id}/close` | Close a case once all findings verified | Examiner |
| POST | `/examination-cases/{case_id}/findings` | Record a finding against a cited record | Examiner |
| GET | `/examination-findings` | List findings (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/examination-findings/{id}` | Get a finding | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| POST | `/examination-findings/{id}/remediate` | Remediate an open finding (bank side) | BSAOfficer |
| POST | `/examination-findings/{id}/verify` | Verify a remediated finding | Examiner |
| POST | `/examination-findings/{id}/reject-remediation` | Reject a remediation, returning the finding to open | Examiner |
| GET | `/audit-events` | List audit events (filtered) | SystemAdmin, BranchManager, Teller, ComplianceAnalyst, BSAOfficer, Examiner |
| GET | `/audit-events/verify-chain` | Verify the audit hash chain | SystemAdmin, BSAOfficer, Examiner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BRANCH_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_INSTRUMENT_SALE_NOT_FOUND` | 404 |
| `ERR_AGGREGATION_NOT_FOUND` | 404 |
| `ERR_CTR_NOT_FOUND` | 404 |
| `ERR_EXEMPTION_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_FINDING_TARGET_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_BRANCH_INACTIVE` | 409 |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 |
| `ERR_TRANSACTION_ALREADY_VOIDED` | 409 |
| `ERR_CTR_NOT_AMENDABLE` | 409 |
| `ERR_CUSTOMER_HAS_OPEN_ITEMS` | 409 |
| `ERR_EXAMINATION_HAS_OPEN_FINDINGS` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_OPEN_ALERT_BLOCKS_EXEMPTION` | 422 |
| `ERR_CTR_INCOMPLETE` | 422 |
| `ERR_INSTRUMENT_RECORD_INCOMPLETE` | 422 |
| `ERR_INSTRUMENT_LIMIT_EXCEEDED` | 422 |
| `ERR_EXEMPTION_PHASE_MISMATCH` | 422 |
| `ERR_PHASE_I_BASIS_INVALID` | 422 |
| `ERR_PHASE_II_INELIGIBLE` | 422 |
| `ERR_DUPLICATE_ACTIVE_EXEMPTION` | 422 |
| `ERR_DUPLICATE_CASE_NUMBER` | 422 |
| `ERR_AMOUNT_NOT_POSITIVE` | 422 |
| `ERR_OCCURRED_AT_IN_FUTURE` | 422 |
| `ERR_VOID_WINDOW_EXPIRED` | 409 |
| `ERR_AMENDMENT_WINDOW_EXPIRED` | 422 |
| `ERR_ALERT_WINDOW_OVERLAP` | 422 |
| `ERR_CASE_SCOPE_OVERLAP` | 422 |
| `ERR_CTR_SNAPSHOT_STALE` | 422 |
