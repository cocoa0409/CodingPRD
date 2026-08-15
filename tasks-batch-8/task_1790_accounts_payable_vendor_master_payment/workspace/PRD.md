# AP Vendor Master & Payment Controls API — Product Requirements Document

## 1. Introduction

Accounts payable is where organizational cash leaves the building, and the vendor master file is where most payment fraud begins: a fictitious vendor registration, a quietly altered bank account, a duplicate record paid twice. This document specifies the AP Vendor Master & Payment Controls API, built for a shared-services accounts payable department that treats vendor master data as a controlled asset from first registration through final settlement. The API governs vendor onboarding under segregation of duties with documentation gates, fuzzy duplicate detection with a managed merge path, sanctions and watchlist screening both at vendor setup and again at payment time, out-of-band callback verification of bank details against the vendor's known contact, dormancy hygiene for stale vendors, a tiered invoice approval matrix, and payment-file controls culminating in positive-pay acknowledgement processing.

Every time-dependent rule in this document is evaluated against a server-side logical clock rather than wall-clock time, so that cooling-off windows, dormancy thresholds, discount windows, and expiry policies behave deterministically. Twelve operator roles participate under explicit segregation-of-duties constraints; every master-data mutation is written to an append-only audit trail; and the vendor master record is guarded by optimistic concurrency control so that a stale view of a vendor is refused rather than silently layered over newer state. Section 2 defines the system-wide contract, Section 3 develops the business workflows in which the rules live, Section 4 summarizes the endpoint surface, and Section 5 catalogues the error identifiers.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and control principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). On invoice approval and rejection specifically, role authorization is finer-grained: the caller's role must equal the role designated for the approval tier being exercised, as described in §3.5.

The system recognizes exactly twelve roles:

- `VendorSpecialist` — AP vendor desk clerk; creates and edits vendor master data, requests bank account changes, and files compliance documents.
- `VendorManager` — vendor desk supervisor; approves, rejects, reinstates, reactivates, deactivates, and merges vendors, and disables bank accounts. A `VendorManager` may also create vendors, in which case segregation of duties bars them from approving their own creation.
- `ComplianceOfficer` — sanctions and watchlist owner; maintains watchlist entries, dispositions review cases, and may suspend vendors.
- `APClerk` — invoice intake clerk; creates, edits, submits, resubmits, and cancels invoices.
- `APSupervisor` — tier-1 invoice approver; also performs invoice intake duties.
- `APManager` — tier-2 invoice approver; also performs invoice intake duties.
- `Controller` — tier-3 invoice approver and administrator of the approval matrix.
- `TreasuryAnalyst` — builds payment runs, adds invoices to them, compiles and uncompiles them, and voids payments or whole runs.
- `TreasuryManager` — approves and releases payment files; segregation of duties bars them from approving or releasing runs they created.
- `BankFileProcessor` — bank integration service account; submits positive-pay acknowledgements.
- `Auditor` — read-only assurance role with access to the audit trail.
- `SystemAdmin` — platform operator for the logical clock and the vendor sweep.

All twelve roles are opaque operator identities. When `X-User-Role` is `VendorSpecialist`, `VendorManager`, `ComplianceOfficer`, `APClerk`, `APSupervisor`, `APManager`, `Controller`, `TreasuryAnalyst`, `TreasuryManager`, `BankFileProcessor`, `Auditor`, or `SystemAdmin`, the accompanying `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the resources the caller creates or mutates — for example as `created_by_user_id` on a vendor or a payment run, `submitted_by_user_id` on an invoice, `requested_by_user_id` on a bank account, `approved_by_user_id` where an approval is captured, or `actor_user_id` on audit events — and the segregation-of-duties checks in §2.6 compare it against those recorded anchors, but it is never compared to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Vendor Sweep

The server maintains a logical clock that governs every time-dependent rule in this document: dormancy evaluation, bank-change cooling-off, early-pay discount windows, callback verification expiry, document validity windows, and daily release bucketing all read the logical clock, never wall-clock time. Before the clock has been set by any call, the logical clock reads exactly 2026-08-01T00:00:00Z. A `SystemAdmin` may set it through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`; the logical clock then reads that instant for all subsequent evaluation.

A second `SystemAdmin` capability, the vendor sweep, is the ops-run checkpoint that performs four maintenance passes in a single run: dormancy evaluation, which may move `ACTIVE` vendors to `DORMANT`; deactivation of vendors that have remained `DORMANT` past the deactivation horizon; the document expiry cache update, which stamps `VendorDocument` rows `EXPIRED` once their validity window has closed; and the callback-expiry cascade, which expires stale verifications and rejects their parent bank accounts. The sweep answers with four counters — `vendors_marked_dormant`, `vendors_deactivated`, `documents_expired`, and `callback_verifications_expired` — reporting what each pass did. The detailed thresholds for every pass appear in §3.3 and §3.4.

### 2.5. Common Resource Properties

Primary resources — vendors, bank accounts, callback verifications, documents, watchlist entries, sanctions review cases, invoices, invoice approvals, approval matrix rules, payment runs, and payments — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

Three record types are deliberately lighter. A `ScreeningCheck`, a `VendorMergeRecord`, and an `AuditEvent` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from these three resources, because they are written once and never mutated thereafter.

Certain cross-resource mutations also increment a related resource's `version` even though the client wrote to a different resource. Adding a bank account to a vendor increments the vendor's `version`; confirming a new primary bank account increments both the superseded account's `version` and the vendor's `version`; disabling the vendor's primary account increments the vendor's `version`; merging a vendor increments the survivor's `version`; and a payment clearing increments its vendor's `version`. Each such mutation also refreshes the affected resource's `updated_at`.

### 2.6. Segregation of Duties

Fraud control in accounts payable rests on the principle that no single operator should be able to both introduce a payee and approve its payment path. The system enforces six segregation-of-duties rules, each anchored to an operator identifier recorded at an earlier step. Each violation is rejected with HTTP 403.

- **SoD-1 (vendor creation vs. vendor approval).** The `VendorManager` approving a vendor must not be the operator recorded as that vendor's `created_by_user_id`. A self-approval attempt is rejected with `ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE`.
- **SoD-2 (invoice submission vs. invoice approval).** The approver of an invoice must not be the operator recorded as `submitted_by_user_id` for the invoice's current approval round. A violation is rejected with `ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE`.
- **SoD-5 (one tier per approver per round).** Within a single approval round of an invoice, one operator may approve at most one tier. An operator who already holds an approval row in the current round and attempts another tier is rejected with `ERR_SOD_SAME_APPROVER_TWO_TIERS`.
- **SoD-3 (bank change request vs. callback confirmation).** The operator confirming a callback verification must not be the operator recorded as `requested_by_user_id` on the bank account. A violation is rejected with `ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM`.
- **SoD-4a (run creation vs. run approval).** The `TreasuryManager` approving a payment run must not be the operator recorded as the run's `created_by_user_id`. A violation is rejected with `ERR_SOD_RUN_CREATOR_CANNOT_APPROVE`.
- **SoD-4b (run creation vs. run release).** The `TreasuryManager` releasing a payment run must not be the operator recorded as the run's `created_by_user_id`. A violation is rejected with `ERR_SOD_RUN_CREATOR_CANNOT_RELEASE`.

### 2.7. The Append-Only Master-Data Audit Trail

Every master-data mutation appends an `AuditEvent` to an audit trail that no endpoint can update or delete — the trail is append-only by construction. Each event records `entity_type` (the entity type name, for example Vendor or VendorBankAccount), `entity_id` (the polymorphic target identifier, interpreted through `entity_type` and deliberately not a strict foreign key), and `event_type`, which is one of `CREATE`, `UPDATE`, `STATUS_CHANGE`, `VERIFY`, `MERGE`, `RETIRE`, or `DISPOSITION`. For `UPDATE` and `STATUS_CHANGE` events the record also carries `field_name`, with the prior and replacement values stringified into `old_value` and `new_value`. Every event stamps `actor_user_id` and `actor_role` from the caller's headers.

Editing a vendor's master data writes one `UPDATE` audit event per changed field, so a single edit that touches three fields appends three events. The trail is queryable with the optional filters `entity_type`, `entity_id`, `actor_user_id`, and `event_type`. Access to the audit trail is restricted to assurance and control roles: `VendorManager`, `ComplianceOfficer`, `Controller`, and `Auditor`.

### 2.8. Optimistic Concurrency Control on the Vendor Master

Three write operations on the vendor master require the client to state which version of the vendor it last observed, carried in the non-optional request field `expected_vendor_version`: editing a vendor's master data, adding a bank account to a vendor, and merging a duplicate vendor into a survivor (in the merge case the check applies to the survivor vendor's version). If `expected_vendor_version` does not equal the vendor's current `version`, the client's view of the vendor is stale — another write has legitimately advanced the record since the client last read it — and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being silently layered over the newer state. The client must re-read the vendor and re-apply its intent against current contents. No endpoint other than these three accepts a version field.

### 2.9. Monetary Precision, Score Precision, and Rounding

All money in the system is represented as integer cents — invoice gross amounts, discounts, fees, payment nets, and run totals alike. Early-pay discounts are computed per single invoice and rounded half up to whole cents before they are ever combined; discounting is never batched across invoices before rounding. Payment run totals obey a pinned rounding order: each payment's discount is rounded to whole cents first, each payment's net is then formed as an integer sum of cents, and only then are the per-payment nets summed into the run total. Summing unrounded discounts and rounding the total afterwards is forbidden, because it diverges by cents.

Similarity scores used by duplicate detection and sanctions screening are decimal values carried to four decimal places, rounded half up. A payment issued under the `WIRE` payment method carries a `fee_cents` of 2,500 cents — a flat twenty-five-dollar wire fee per payment — while `CHECK` and `ACH` payments carry a fee of zero.

### 2.10. Name Normalization and Similarity Scoring

Duplicate detection and sanctions screening share one name-normalization transform and one similarity score. Normalization takes a single raw name string and applies four steps in order: first, uppercase the string; second, replace every character that is not a letter or digit with a space; third, split on whitespace and discard any token that is a corporate suffix — `INC`, `LLC`, `CORP`, `CORPORATION`, `COMPANY`, `CO`, `LTD`, `LP`, `LLP`, `PLLC`, or `PC`; fourth, concatenate the surviving tokens with no separator. The transform is an exact string operation with no approximation.

The similarity score between two raw names normalizes both, then compares their character-trigram sets — the set of all three-character sliding windows of the normalized string, or, when the normalized string is shorter than three characters, a set containing the string itself. The score is twice the size of the intersection of the two trigram sets divided by the sum of the two set sizes (the Dice coefficient), rounded half up to four decimal places. When the two normalized strings are identical, the score is exactly 1.0000 by definition and no trigram arithmetic is performed.

### 2.11. Validation Order and Nested Path Existence

Every request is screened through a fixed validation pipeline, and the ordering is part of the contract. Credentials come first: missing or invalid `X-User-ID` / `X-User-Role` context is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is examined. Role authorization follows, yielding `ERR_FORBIDDEN_FOR_ROLE`. Request-shape validity comes next — an unparsable body, a missing required field, an invalid enum value, a non-positive `amount_cents`, a negative `min_amount_cents`, a `tax_id` supplied in a vendor edit, or a document window whose `valid_from` falls after its `valid_until` are all rejected with `ERR_INVALID_REQUEST` (HTTP 400). Only then are path identifiers resolved: endpoints that address nested resources validate the path strictly left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond to an existing resource — a request targeting a bank account under a non-existent vendor fails on the vendor before the account is ever sought.

After existence comes optimistic concurrency: a stale `expected_vendor_version` is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state or business rule runs. State legality follows — a transition whose source state does not permit it, an edit outside its allowed status window, or an acknowledgement aimed at an already-terminal resource is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), with the more specific state guards `ERR_CALLBACK_LOCKED`, `ERR_CALLBACK_EXPIRED`, and `ERR_PAYMENT_ALREADY_TERMINAL` applied where they exist. Domain guards run last, in their declared order: business-safety rules (a blocked vendor, a pending sanctions review, duplicate-vendor enforcement, and the segregation-of-duties rules), then business constraints (vendor activity, documents, matrix coverage, merge gates, uniqueness, run contents, and callback codes), then temporal rules (cooling-off, document expiry, snapshot freshness), and finally the fiscal daily-release limit. The individual rules and their relative ordering within each endpoint appear in §3.

## 3. Business Logic & Workflows

### 3.1. Vendor Registration, Duplicate Detection, and Compliance Documents

A vendor relationship begins when a `VendorSpecialist` or `VendorManager` registers a new vendor with its `legal_name`, `tax_id`, `remit_email`, `phone`, `address_line1`, `city`, and `country`, optionally supplemented by a `dba_name` trade name and by payment configuration. The payment configuration consists of `payment_terms_days` (net terms in days, defaulting to 30), `early_pay_discount_pct` (a discount fraction such as 0.02, defaulting to 0, where 0 disables early-pay discounting entirely), and `discount_window_days` (the number of days from an invoice's `received_date` during which the discount applies, defaulting to 0, with the window's end day inclusive). The `phone` number is more than contact data: it is the vendor's known-contact line, and the callback verification of §3.3 must dial this pre-existing number. The new vendor is born in `DRAFT` status, the caller is recorded as `created_by_user_id` (the SoD-1 anchor), and a `CREATE` audit event is appended. The `tax_id` is immutable for the life of the record — it may never appear in a later master-data edit — and must be unique among vendors that are not `MERGED`, `REJECTED`, or `DEACTIVATED`.

Registration runs the duplicate-detection screen, which executes at creation time only and is never re-run on a later edit or at approval. Candidates are all vendors whose status is not `MERGED`, `REJECTED`, or `DEACTIVATED`. The screen's two legs are evaluated in order. The strict leg flags only exact collisions: if any candidate's `tax_id` equals the new vendor's `tax_id`, creation is rejected with `ERR_DUPLICATE_TAX_ID`. The relaxed leg computes the §2.10 similarity score of the new `legal_name` against each candidate's `legal_name` and, when the candidate carries one, its `dba_name`, taking the best score over all comparisons; because the score is a trigram measure, a one-character typo in the name with a different `tax_id` passes the strict leg cleanly but is caught here. If the best score is at least 0.9000, creation is rejected with `ERR_DUPLICATE_VENDOR_HARD_BLOCK` — identical input that produced no strict match produces a hard block here. If the best score is at least 0.7500 but below 0.9000, creation is rejected with `ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED` unless the caller asserted `duplicate_acknowledged` as true, in which case the vendor is created with its `duplicate_review_required` flag set to true. Below 0.7500 the vendor is created with `duplicate_review_required` false. Both thresholds compare against the four-decimal-place rounded score with at-least semantics, and the create-time checks fire in this order: request validity first, then the tax-identifier collision, then the hard block, then the review band.

Accounts payable staff can browse the vendor register with optional filters: `status` isolates a lifecycle stage, `name_contains` matches against vendor names, `merged_into_vendor_id` finds everything absorbed into a given survivor, and `primary_bank_account_id` locates the vendor currently paying through a given account.

Before a draft vendor can advance, its compliance file must be in order. A `VendorSpecialist` attaches documents to the vendor by supplying a `doc_type` — one of `W9`, `INSURANCE_CERT`, or `BANK_AUTHORIZATION` — together with `valid_from` and `valid_until`, ISO dates that bound the document's effectiveness as a closed interval: the document is effective on `valid_from`, remains effective on `valid_until` itself, and a submission whose `valid_from` falls after its `valid_until` is rejected with `ERR_INVALID_REQUEST`. For a given vendor and a given `doc_type`, two documents' windows must not overlap, and because the intervals are closed, even sharing a single endpoint day counts as an overlap, rejected with `ERR_DOCUMENT_PERIOD_OVERLAP`. A document is born `VALID`; a `VendorSpecialist` may supersede it, moving it from `VALID` to `SUPERSEDED` with a `STATUS_CHANGE` audit event, and the vendor sweep stamps `VALID` rows `EXPIRED` once the logical date has passed their `valid_until`. That `EXPIRED` status is only a sweep-maintained cache: every business gate evaluates document validity live. A document passes live evaluation when its status is `VALID` and the current logical date falls on or after `valid_from` and on or before `valid_until` — both bounds inclusive — so a row still cached as `VALID` whose window has already closed fails live checks. A vendor's document list can be filtered by `doc_type` and `status`.

Submitting the vendor moves it from `DRAFT` to `PENDING_APPROVAL` and is permitted to both vendor-desk roles. The submit gate requires at least one live-valid `W9` on file at the current logical date; when no live-valid W9 exists — whether none was ever filed or every W9's window has closed — the submission is rejected with `ERR_REQUIRED_DOCUMENT_MISSING`. A successful submission appends a `STATUS_CHANGE` audit event.

### 3.2. Vendor Approval, Watchlists, and Sanctions Review

Approval of a `PENDING_APPROVAL` vendor is reserved to a `VendorManager`, and the checks fire in a fixed order: a vendor not in `PENDING_APPROVAL` is rejected with `ERR_INVALID_STATE_TRANSITION`; SoD-1 then bars the vendor's creator from approving it with `ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE`; and finally an inline sanctions screening — the setup variant — routes the outcome. The approval takes no request body. When the screening result is `CLEAR`, the vendor becomes `ACTIVE`: the caller is recorded as `approved_by_user_id`, the vendor's `first_activated_at` is stamped with the logical time of this first entry into `ACTIVE` (later reactivations do not overwrite it), and the screening row is persisted. When the result is `REVIEW`, the vendor instead becomes `SUSPENDED`, a sanctions review case opens with `opened_reason` `SETUP_SCREENING` unless an `OPEN` case already exists for this vendor, and the screening row is persisted. When the result is `HIT`, the vendor becomes `BLOCKED` and the screening row is persisted. Each path appends a `STATUS_CHANGE` audit event. Rejection is the lighter path: a `VendorManager` may reject a vendor from `DRAFT` or from `PENDING_APPROVAL`, supplying a `reason`, moving it to `REJECTED` with a `STATUS_CHANGE` audit event.

The screening itself screens the vendor's `legal_name` against every watchlist entry whose status is `ACTIVE`; retired entries no longer participate. Each entry is scored with the §2.10 similarity score against the vendor's normalized name, and the best-scoring entry wins, with ties broken in favor of the entry created earliest. If the best score is exactly 1.0000 and that entry's `severity` is `BLOCK`, the result is `HIT`; if the best score is exactly 1.0000 with severity `REVIEW`, the result is `REVIEW`; if the best score is at least 0.8000 without reaching exact equality, the result is `REVIEW`; otherwise the result is `CLEAR`. Every evaluation — whatever its outcome — persists a `ScreeningCheck` row recording its `subject_type` (`VENDOR` for lifecycle screening, `PAYMENT` for payment-time screening), the screened `vendor_id`, the `payment_id` when the subject is a payment, the `matched_watchlist_entry_id` of the best entry when the result is not `CLEAR`, the `match_score` rounded half up to four decimal places, the `result`, and `screened_at` stamped from the logical clock. Screening history can be browsed with the filters `vendor_id`, `payment_id`, `matched_watchlist_entry_id`, and `result`.

Watchlist maintenance belongs to the `ComplianceOfficer`. Creating an entry requires a `name_pattern` to screen against (normalized with the same §2.10 transform before matching), a `severity` of `BLOCK` or `REVIEW`, and a `list_source` recording provenance such as `OFAC_SDN` or `INTERNAL_FRAUD`; the entry is born `ACTIVE` and a `CREATE` audit event is appended. Retiring an entry moves it from `ACTIVE` to `RETIRED` with a `RETIRE` audit event. Because only `ACTIVE` entries are screened, retiring changes future outcomes — and this is where the two screening variants diverge. The setup variant, evaluated at vendor approval, reactivation, or a name edit, reflects the watchlist as of that transition, and a `CLEAR` then does not immunize the vendor against entries added later. The payment variant, evaluated when an invoice is added to a payment run (§3.6), re-evaluates against the current `ACTIVE` watchlist, so an entry created after the vendor was approved can flip that same vendor from `CLEAR` to `REVIEW` or `HIT` at payment time.

A sanctions review case tracks human adjudication of a `REVIEW` outcome. At most one case per vendor may be `OPEN` at any time. The case links back through `screening_check_id` to the check that opened it, carries the `vendor_id`, records `payment_id` for cases of payment-screening origin, and notes its `opened_reason` as `SETUP_SCREENING` or `PAYMENT_SCREENING`. Cases can be listed with the filters `vendor_id`, `payment_id`, `screening_check_id`, and `status`. Disposition belongs to the `ComplianceOfficer`, who supplies a `decision` and may attach an optional `note`, which is recorded on the case as `disposition_note`; the caller is recorded as `dispositioned_by_user_id`, and a `DISPOSITION` audit event is appended. A case not currently `OPEN` cannot be dispositioned and yields `ERR_INVALID_STATE_TRANSITION`. A `decision` of `CLEARED` closes the case as `CLEARED`, and if the referenced vendor is `SUSPENDED` and has no other `OPEN` case, the vendor returns from `SUSPENDED` to `ACTIVE`, firing the resume cascade of §3.4. A `decision` of `CONFIRMED_HIT` closes the case as `CONFIRMED_HIT` and drives the vendor from `SUSPENDED` to `BLOCKED`, firing the ordered block cascade: first, the vendor's invoices in `PENDING_APPROVAL` or `APPROVED`, plus any invoices in `IN_PAYMENT_RUN` whose payment is still `PENDING` because the run has not been released, move to `ON_HOLD` with their prior status recorded in `pre_hold_status` (an invoice already `ON_HOLD` keeps its original `pre_hold_status`); second, every payment whose invoice was just held out of `IN_PAYMENT_RUN` — all of them still `PENDING` by the first step's filter — is voided with `void_reason` `VENDOR_BLOCKED`; third, each affected run recomputes its totals, and a run sitting in `APPROVED` whose contents changed demotes itself to `COMPILED`. Invoices already inside a `RELEASED` run are not held; they ride to their positive-pay acknowledgement outcome.

### 3.3. Bank Account Registration and Callback Verification

Bank details are the highest-risk field on the vendor master, so the system never takes them on faith. A `VendorSpecialist` registers a bank account against a vendor by supplying the `account_number`, the nine-digit `routing_number`, the `account_holder_name`, and optionally the `is_primary` flag, which defaults to false. The write carries the OCC guard of §2.8 — the request must present `expected_vendor_version` equal to the vendor's current `version`, or it is rejected with `ERR_STALE_VERSION` — and the vendor must be in `DRAFT`, `PENDING_APPROVAL`, `ACTIVE`, or `SUSPENDED`; attempting to add an account to a vendor in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. The new account is born in `PENDING_VERIFICATION` with the caller recorded as `requested_by_user_id` (the SoD-3 anchor), the vendor's `version` increments by one, and a `CREATE` audit event is appended. The `is_primary` flag is only a request at this stage: it becomes the effective primary solely upon successful verification.

Registration spawns a callback verification addressed to the vendor's known contact. The server mints a six-digit `verification_code`, which is deemed phoned to the vendor at its pre-existing `phone` number — the callback must dial that known number, never a number supplied alongside the new account details. The verification is born `PENDING` with `attempts` at zero, its `expires_at` fixed at creation to exactly 48 hours after its `created_at`, and a link to its account through `bank_account_id`. Because this is a simulation, the code is exposed on read: the account's callback verifications can be listed, and each row shows the `verification_code`, `attempts`, `status`, `expires_at`, and, once known, `confirmed_by_user_id`.

Confirmation is performed by a `VendorSpecialist` or `VendorManager` presenting the `verification_code`. The guards fire in a fixed order. A verification already `CONFIRMED` is rejected with `ERR_INVALID_STATE_TRANSITION`; a `LOCKED` verification is rejected with `ERR_CALLBACK_LOCKED`; an `EXPIRED` verification is rejected with `ERR_CALLBACK_EXPIRED`. SoD-3 then bars the account's requester from confirming it, yielding `ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM`. Finally the code itself is compared: a mismatch increments `attempts` and, while fewer than three attempts have accumulated, is rejected with `ERR_CALLBACK_CODE_MISMATCH`; the third mismatch instead locks the verification — it becomes `LOCKED`, its parent account moves from `PENDING_VERIFICATION` to `REJECTED` — and the rejection carries `ERR_CALLBACK_LOCKED`. A confirmation presented while the verification is still `PENDING`, with fewer than three accumulated attempts, and at a logical time no later than `expires_at` — at exactly `expires_at` the code remains confirmable — succeeds: the verification becomes `CONFIRMED` with the caller recorded as `confirmed_by_user_id`, the account becomes `VERIFIED` with `verified_at` stamped at the logical time, and a `VERIFY` audit event is appended. When the account carries `is_primary` true, the supersede chain fires in the same step: the vendor's previous `VERIFIED` primary, if any, becomes `SUPERSEDED` and its `version` increments, the vendor's `primary_bank_account_id` is set to the newly verified account, and the vendor's `version` increments by one. A vendor's `primary_bank_account_id` remains null until the first verification completes.

Two system paths retire a pending verification without a confirmation call. When `attempts` reaches three through mismatches, the verification locks as described above. And when the vendor sweep finds a verification still `PENDING` at a logical time strictly later than its `expires_at`, the verification becomes `EXPIRED` and its parent account — still `PENDING_VERIFICATION` — becomes `REJECTED`, each with a `STATUS_CHANGE` audit event.

A `VendorManager` may disable a `VERIFIED` account. The manual gate refuses the disable while any payment in `PENDING` or `RELEASED` references the account, rejecting with `ERR_BANK_ACCOUNT_IN_USE`. When the disabled account was the vendor's primary, the vendor's `primary_bank_account_id` is cleared to null and the vendor's `version` increments by one; a `STATUS_CHANGE` audit event is appended either way. A vendor's account list can be browsed with an optional `status` filter.

### 3.4. Master Data Maintenance, Suspension, Merge, and the Dormancy Lifecycle

Master-data edits are performed by a `VendorSpecialist` and are guarded twice: the OCC rule of §2.8 requires `expected_vendor_version`, and the vendor must be in `DRAFT`, `PENDING_APPROVAL`, `ACTIVE`, `SUSPENDED`, or `DORMANT` — editing a vendor in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. The OCC check runs before the state check, and request validity runs before both, so a `tax_id` supplied in the edit payload is rejected with `ERR_INVALID_REQUEST` before the version is ever examined. The editable fields are `legal_name`, `dba_name`, `remit_email`, `phone`, `address_line1`, `city`, `country`, `payment_terms_days`, `early_pay_discount_pct`, and `discount_window_days`. A successful edit increments the vendor's `version` by one and appends one `UPDATE` audit event per changed field. Editing `legal_name` while the vendor is `ACTIVE` or `SUSPENDED` re-runs the setup variant of sanctions screening against the current watchlist: a `CLEAR` leaves the vendor untouched; a `REVIEW` suspends an `ACTIVE` vendor and opens a review case; a `HIT` blocks the vendor outright and fires the ordered block cascade described in §3.2.

Suspension is the system's general-purpose freeze. A `VendorManager` or `ComplianceOfficer` may suspend an `ACTIVE` vendor, supplying a `reason`. The vendor moves from `ACTIVE` to `SUSPENDED`, and the hold cascade freezes its open approval pipeline: every invoice of this vendor in `PENDING_APPROVAL` or `APPROVED` moves to `ON_HOLD` with its former status recorded in `pre_hold_status`, while an invoice already `ON_HOLD` keeps its original `pre_hold_status`. A plain suspension does not touch invoices in `IN_PAYMENT_RUN`. The same transition also fires from three system triggers — a payment-time screening `REVIEW` at payment-run add, the positive-pay mismatch chain of §3.7, and a name-edit re-screen `REVIEW` — and when the trigger is a screening, a sanctions review case opens unless one is already `OPEN` for the vendor. Every suspension, manual or system-driven, appends a `STATUS_CHANGE` audit event. The mismatch chain additionally stamps the vendor's `fraud_hold_reason` as `POSITIVE_PAY_MISMATCH`.

Reinstatement by a `VendorManager` moves a `SUSPENDED` vendor back to `ACTIVE`, but only while no sanctions review case in `OPEN` status references the vendor; otherwise the reinstatement is rejected with `ERR_VENDOR_HAS_OPEN_CASE`. Success fires the resume cascade: each of the vendor's `ON_HOLD` invoices returns to the status recorded in its `pre_hold_status`, and `pre_hold_status` is then cleared; a `STATUS_CHANGE` audit event records the return to `ACTIVE`. Because `BLOCKED` is terminal, an `ON_HOLD` invoice whose `pre_hold_status` is `IN_PAYMENT_RUN` — a state reachable only through the block cascade, which voided its payment — never resumes; resume targets are only `PENDING_APPROVAL` and `APPROVED`.

Deactivation by a `VendorManager` retires a vendor from `ACTIVE`, `SUSPENDED`, or `DORMANT` into the terminal `DEACTIVATED` status. Two gates apply: the vendor must hold no invoices in `RECEIVED`, `PENDING_APPROVAL`, `APPROVED`, `IN_PAYMENT_RUN`, or `ON_HOLD` — a violation is rejected with `ERR_VENDOR_HAS_OPEN_INVOICES` — and the vendor must have no payments still in `PENDING` or `RELEASED`. A `STATUS_CHANGE` audit event records the deactivation.

Dormancy is the system-driven half of vendor hygiene, executed by the vendor sweep. For each `ACTIVE` vendor, the sweep forms a reference timestamp: the vendor's `last_payment_cleared_at` when set, otherwise its `first_activated_at`. When that reference is set, at least 180 days have elapsed between it and the current logical time — a vendor exactly 180 days along is eligible — and the vendor holds no invoices in the five open statuses listed above, the vendor moves from `ACTIVE` to `DORMANT` with `dormant_since_at` stamped at the logical time and a `STATUS_CHANGE` audit event. In a second pass, each `DORMANT` vendor for whom at least 90 days have elapsed since `dormant_since_at`, again with no open invoices, moves to `DEACTIVATED`. A `VendorManager` may instead bring a `DORMANT` vendor back through reactivation, which re-runs the setup screening variant and routes on its result: `CLEAR` restores the vendor to `ACTIVE` and clears `dormant_since_at` to null; `REVIEW` moves it to `SUSPENDED` and opens a review case unless one is already `OPEN`; `HIT` moves it to `BLOCKED`. Each path persists its screening row and a `STATUS_CHANGE` audit event.

When duplicate vendors survive the create-time screen, a `VendorManager` merges the duplicate into a survivor by addressing the survivor and naming the absorbed record as `duplicate_vendor_id`, carrying `expected_vendor_version` for the survivor per §2.8. The merge gate rejects with `ERR_VENDOR_NOT_MERGEABLE` unless all of the following hold: the source vendor is in `DRAFT`, `PENDING_APPROVAL`, `ACTIVE`, `SUSPENDED`, or `DORMANT`; the survivor is `ACTIVE`; source and survivor are different vendors; neither vendor has payments in `PENDING` or `RELEASED`; neither vendor has an `OPEN` sanctions review case; and re-pointing the source's invoices would not collide an `invoice_number` already present on the survivor. The stale-version rejection precedes the gate. A successful merge moves the source vendor to the terminal `MERGED` status with its `merged_into_vendor_id` set to the survivor, re-points every invoice of the source whose status is neither `PAID` nor `CANCELLED` to the survivor, disables the source's bank accounts in `PENDING_VERIFICATION` or `VERIFIED` — each moving to `DISABLED` — while the survivor's primary account is left unchanged, and increments the survivor's `version` by one. The merge persists a `VendorMergeRecord` capturing `survivor_vendor_id`, `merged_vendor_id`, the `match_score` between the two legal names at merge time at four decimal places, the `invoices_repointed_count`, the `bank_accounts_disabled_count`, and the `merged_by_user_id`, and appends a `MERGE` audit event on both vendors. Merge records can be browsed with the filters `survivor_vendor_id` and `merged_vendor_id`.

### 3.5. Invoice Intake and Tiered Approval

Invoice intake is performed by an `APClerk`, `APSupervisor`, or `APManager`, who registers an invoice with its `vendor_id`, the vendor's own `invoice_number`, the gross `amount_cents` — which must be strictly positive — and the `cost_center` that selects the approval routing. The optional `received_date` records when the invoice arrived and defaults to the current logical date when omitted. The vendor gates fire before the invoice exists: a `BLOCKED` vendor rejects the intake with `ERR_VENDOR_BLOCKED`, a vendor in any status other than `ACTIVE` rejects it with `ERR_VENDOR_NOT_ACTIVE`, and an `invoice_number` already present on that vendor among invoices not in `CANCELLED` status rejects it with `ERR_DUPLICATE_INVOICE_NUMBER` — a cancelled invoice's number is free to be reused. A registered invoice is born in `RECEIVED` status with `approval_round` at zero. While an invoice sits in `RECEIVED` or `REJECTED`, the intake roles may correct its `amount_cents`, `cost_center`, or `invoice_number`; editing one in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`, and a corrected `invoice_number` must still satisfy the per-vendor uniqueness rule. Invoices can be browsed with the filters `vendor_id`, `status`, and `cost_center`.

How many approval tiers an invoice needs is governed by the approval matrix, administered by the `Controller`. A matrix rule carries a `cost_center` — or the literal scope `GLOBAL`, which serves as the fallback — a bracket lower bound `min_amount_cents` that is inclusive and must be non-negative, an optional bracket upper bound `max_amount_cents` that is exclusive and, when omitted, leaves the bracket unbounded above, and a base `tier` of 1, 2, or 3 for amounts in that half-open bracket. Within one `cost_center` scope, the `ACTIVE` rules' half-open brackets must not overlap; two rules merely touching — one's `min_amount_cents` equaling the other's `max_amount_cents` — is adjacency and is allowed. A violating creation is rejected with `ERR_RULE_RANGE_OVERLAP`. A rule is born `ACTIVE` with a `CREATE` audit event, and the `Controller` may retire it to `RETIRED` with a `RETIRE` audit event; retirement never disturbs invoices already in flight, which keep the tier snapshot they were given.

Submitting an invoice — from `RECEIVED` to `PENDING_APPROVAL`, open to the three intake roles — first requires the vendor to be `ACTIVE`, else `ERR_VENDOR_NOT_ACTIVE`, and then snapshots the routing. Routing selects among `ACTIVE` matrix rules: the scope is the rules whose `cost_center` equals the invoice's `cost_center`, or, when no such rule exists, the rules in the `GLOBAL` scope. The covering rule is the unique scope rule whose `min_amount_cents` is no greater than the invoice's `amount_cents` and whose `max_amount_cents` is either unset or strictly greater than the amount; when no rule covers the amount in either scope, submission is rejected with `ERR_NO_APPROVAL_RULE`. The required tier starts at the covering rule's base `tier` and receives two possible bumps: one when the vendor's `first_activated_at` is set and the submit time falls strictly before the instant thirty days after it — a vendor exactly thirty days active earns no bump — and one when the vendor has a primary `VERIFIED` bank account whose `verified_at` lies strictly less than 72 hours before the submit time. The sum of the base tier and both bumps is capped at a maximum tier of 3, and the result is pinned onto the invoice as `required_tier`, a snapshot that later matrix edits do not disturb. Submission also increments `approval_round` — to 1 on the first submit — and records the caller as `submitted_by_user_id`, the SoD-2 anchor for the new round.

Approval proceeds tier by tier, with each tier reserved to its designated role: tier 1 belongs to an `APSupervisor`, tier 2 to an `APManager`, and tier 3 to a `Controller`. The approver presents the `tier` they are exercising, and the guards fire in a fixed order. The caller's role must equal the role designated for the presented tier, else `ERR_FORBIDDEN_FOR_ROLE`. A presented tier at or below the number of approvals already recorded in the current round is rejected with `ERR_INVALID_STATE_TRANSITION`. SoD-2 then rejects the round's own submitter with `ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE`, and SoD-5 rejects an operator who already approved another tier this round with `ERR_SOD_SAME_APPROVER_TWO_TIERS`. Finally, a presented tier that skips ahead of the next pending tier is rejected with `ERR_APPROVAL_TIER_OUT_OF_ORDER`. A valid intermediate-tier approval appends an `InvoiceApproval` row recording the `invoice_id`, the `round_no` equal to the invoice's `approval_round` at approval time, the `tier`, the `approver_user_id`, and the `approver_role` used for that tier, and the invoice remains `PENDING_APPROVAL`. When the approved tier equals the invoice's `required_tier`, the approval is final: the invoice moves to `APPROVED`, the approval row is appended as usual, and the provisional discount snapshot is taken (§3.6). An invoice's approval rows across all rounds can be listed with an optional `round_no` filter.

Rejection follows the same tier discipline: an approver presents a `tier` and a `reason`, the same role-for-tier and next-pending-tier ordering rules as approval apply — including `ERR_APPROVAL_TIER_OUT_OF_ORDER` on a skip — and the invoice moves from `PENDING_APPROVAL` to `REJECTED`, with a `STATUS_CHANGE` audit event recorded with the supplied reason. A rejected invoice can be resubmitted by the intake roles, moving from `REJECTED` back to `PENDING_APPROVAL`: the vendor must again be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), a covering matrix rule must again exist (`ERR_NO_APPROVAL_RULE`), `approval_round` increments, the caller becomes the new `submitted_by_user_id`, and — critically — `required_tier` is re-snapshotted against the current matrix and the current activation and bank-verification timestamps, so matrix edits and vendor aging since the first submit take effect now. An `APClerk` may cancel an invoice from `RECEIVED`, `PENDING_APPROVAL`, or `REJECTED`, supplying an optional `reason`; the invoice becomes `CANCELLED`, and when it was cancelled mid-approval, that round's approval rows remain as history.

### 3.6. Building the Payment Run: Pay-Gates and Payment-Time Screening

Treasury assembles disbursements through payment runs. A `TreasuryAnalyst` or `TreasuryManager` creates a run by supplying its `scheduled_date` — the ISO value date that drives the final discount decision — and its `payment_method` of `CHECK`, `ACH`, or `WIRE`. The run is born in `DRAFT` with the caller recorded as `created_by_user_id` (the SoD-4 anchor) and both computed counters, `total_amount_cents` and `item_count`, at zero.

Adding an invoice to a run is performed by a `TreasuryAnalyst` naming an `invoice_id`, and it is the most heavily gated write in the system. The run must be in `DRAFT` and the invoice in `APPROVED`, else `ERR_INVALID_STATE_TRANSITION`. Then the payment variant of sanctions screening runs against the current `ACTIVE` watchlist — before the remaining gates — and its side effects persist even when the add is rejected: the screening row is always written with `subject_type` `PAYMENT`, and on a `REVIEW` the vendor is suspended and a review case opens, while on a `HIT` the vendor is blocked with the full §3.2 cascade. The gate order then surfaces the outcome: a vendor already `BLOCKED`, or one whose fresh screening returned `HIT`, rejects the add with `ERR_VENDOR_BLOCKED`; a vendor with an `OPEN` review case, or one whose fresh screening returned `REVIEW`, rejects with `ERR_SANCTIONS_REVIEW_PENDING`; a vendor in any other non-`ACTIVE` status rejects with `ERR_VENDOR_NOT_ACTIVE`. With the vendor cleared, its banking gates follow: the vendor must have a primary `VERIFIED` bank account, else `ERR_BANK_ACCOUNT_NOT_VERIFIED`, and at least 72 hours must have elapsed since that primary account's `verified_at` — the bank-change cooling-off, where a primary verified exactly 72 hours ago passes and a fresher one rejects with `ERR_BANK_CHANGE_COOLING_OFF`. Last, the vendor must hold a live-valid `W9` at add time under the live evaluation of §3.1; a W9 on file whose window has passed rejects with `ERR_DOCUMENT_EXPIRED`.

A successful add moves the invoice from `APPROVED` to `IN_PAYMENT_RUN` and creates a `PENDING` payment that snapshots everything it needs: `payment_run_id` and `invoice_id` link it into place, `vendor_id` is denormalized from the invoice, `bank_account_id` snapshots the vendor's current primary account and `bank_account_version` that account's `version` at this instant, and `amount_cents` carries the invoice's gross at add time. The discount snapshot `discount_applied_cents` uses the final variant of the pay-amount rule: the discount window ends on the invoice's `received_date` plus the vendor's `discount_window_days`, the end day inclusive, and the discount applies when the run's `scheduled_date` falls on or before that window end — so a run scheduled past the window yields a zero `discount_applied_cents` on the very same invoice whose provisional snapshot was non-zero. The discount itself is the invoice's `amount_cents` multiplied by the vendor's `early_pay_discount_pct`, rounded half up to whole cents per invoice, and zero when the window is missed or the vendor's discount fraction is zero. The provisional variant taken at final-tier approval answers the same question with the logical date at approval as the reference — "would the discount apply if we paid today" — and is stored on the invoice as `provisional_discount_cents`. The payment's `fee_cents` is the 2,500-cent wire fee when the run's method is `WIRE` and zero otherwise, and its `net_amount_cents` is the gross minus the discount plus the fee. Every add recomputes the run's totals under the pinned rounding order of §2.9: `total_amount_cents` is the sum of `net_amount_cents` over the run's payments not in `VOIDED` status, and `item_count` counts those same payments. The run's payments can be listed with a `status` filter, and the payment ledger as a whole can be browsed with the filters `vendor_id`, `invoice_id`, `bank_account_id`, and `status`.

### 3.7. Run Approval, Release, and Positive-Pay Settlement

A draft run becomes a payment file through a three-step treasury workflow. Compilation, performed by a `TreasuryAnalyst`, moves the run from `DRAFT` to `COMPILED` and requires at least one non-`VOIDED` payment — compiling an empty run is rejected with `ERR_EMPTY_PAYMENT_RUN` — recomputing the run totals as it goes; uncompilation reverses it back to `DRAFT` for rework. Approval, performed by a `TreasuryManager`, moves the run from `COMPILED` to `APPROVED` under SoD-4a: the approver must differ from the run's `created_by_user_id`, else `ERR_SOD_RUN_CREATOR_CANNOT_APPROVE`, and the approver is recorded as `approved_by_user_id`. Approval is revocable — the same role can move the run back to `COMPILED`, clearing `approved_by_user_id` to null — and it is also fragile: when the run's contents change underneath it because a payment was voided or the block cascade voided payments, an `APPROVED` run demotes itself to `COMPILED` and must be approved afresh.

Release is the point of no return, performed by a `TreasuryManager` on an `APPROVED` run, and three guards fire in order. SoD-4b bars the run's creator from releasing it with `ERR_SOD_RUN_CREATOR_CANNOT_RELEASE`. Next, every payment's bank snapshot is re-checked for freshness: for each payment, the vendor's current `primary_bank_account_id` must still equal the payment's `bank_account_id`, and that account's current `version` must still equal the payment's `bank_account_version`; any drift rejects the release with `ERR_BANK_SNAPSHOT_STALE`. Last, the daily release limit buckets runs by logical UTC date: the sum of `total_amount_cents` over all runs in `RELEASED` or `CLOSED` whose `released_at` falls on the same logical date, plus this run's `total_amount_cents`, must not exceed 10,000,000 cents — a one-hundred-thousand-dollar daily ceiling; a release landing exactly on the limit is allowed, and one cent over is rejected with `ERR_DAILY_LIMIT_EXCEEDED`. A released run stamps `released_by_user_id` and `released_at` from the logical clock, and every `PENDING` payment in the run moves to `RELEASED` — the positive-pay file is deemed issued to the bank at this moment.

Settlement arrives as positive-pay acknowledgements from the bank, submitted by the `BankFileProcessor` as a list of `acks`, each item identifying one payment of the run and carrying an `ack_result` of `MATCH` or `MISMATCH`. The run must be `RELEASED`, and each acked payment must still be `RELEASED`; an ack aimed at a payment already `CLEARED` or `VOIDED` is rejected with `ERR_PAYMENT_ALREADY_TERMINAL`. A `MATCH` clears the payment: it moves from `RELEASED` to `CLEARED`, its invoice moves from `IN_PAYMENT_RUN` to `PAID`, the vendor's `last_payment_cleared_at` is stamped with the logical time and the vendor's `version` increments by one — this timestamp is the dormancy reference of §3.4 — and the run checks whether every payment it contains has reached a terminal state, closing itself from `RELEASED` to `CLOSED` when the last one lands.

A `MISMATCH` is the fraud alarm, and its chain fires in a fixed order. The payment becomes `VOIDED` with `void_reason` `POSITIVE_PAY_MISMATCH`. First, its invoice reverts from `IN_PAYMENT_RUN` to `APPROVED`. Second, the vendor moves from `ACTIVE` to `SUSPENDED` with its `fraud_hold_reason` set to `POSITIVE_PAY_MISMATCH`. Third, the suspension's hold cascade catches the vendor's invoices in `PENDING_APPROVAL` or `APPROVED` — which now includes the invoice just reverted in the first step, so that invoice ends `ON_HOLD` with `pre_hold_status` recording `APPROVED`. The run then performs the same terminal-payment bubble-up check. Because the vendor is merely `SUSPENDED` and no review case is opened by this chain, a `VendorManager` can reinstate it once the mismatch is investigated.

Two reversal paths unwind work before release. A `TreasuryAnalyst` may void a payment manually while it is still `PENDING` — a payment that is no longer `PENDING`, including one inside a `RELEASED`, `CLOSED`, or `VOIDED` run, yields `ERR_INVALID_STATE_TRANSITION` — which sets `void_reason` `MANUAL_REMOVED`, returns its invoice from `IN_PAYMENT_RUN` to `APPROVED`, recomputes the run totals, and demotes the run from `APPROVED` to `COMPILED` if that is where it sat. Voiding the whole run, open to both treasury roles from `DRAFT` or `COMPILED`, moves the run to `VOIDED`, moves every `PENDING` payment to `VOIDED` with `void_reason` `RUN_VOIDED`, returns their invoices from `IN_PAYMENT_RUN` to `APPROVED`, and recomputes the totals. Once a run is `RELEASED`, its payments are beyond manual void and resolve only through positive-pay acknowledgements.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a vendor, a bank account, a document, a watchlist entry, an approval matrix rule, an invoice, or a payment run — or that add a new payment to a run return `201 Created`. All other successful operations, including state transitions, edits, and reads, return `200 OK`. Request payloads, response bodies, and side effects are defined by the workflows in §3; this table is only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |
| POST | `/vendor-sweeps/run` | Run the ops sweep: dormancy, deactivation, document expiry, callback expiry | SystemAdmin |
| POST | `/vendors` | Create a vendor in DRAFT with duplicate detection | VendorSpecialist, VendorManager |
| GET | `/vendors` | List vendors with filters | All roles |
| GET | `/vendors/{id}` | Get a vendor | All roles |
| PATCH | `/vendors/{id}` | Update vendor master data (OCC); name edits may re-screen | VendorSpecialist |
| POST | `/vendors/{id}/submit` | Move DRAFT to PENDING_APPROVAL (requires live-valid W9) | VendorSpecialist, VendorManager |
| POST | `/vendors/{id}/approve` | Approve vendor; inline screening routes to ACTIVE / SUSPENDED / BLOCKED | VendorManager |
| POST | `/vendors/{id}/reject` | Move DRAFT or PENDING_APPROVAL to REJECTED | VendorManager |
| POST | `/vendors/{id}/suspend` | Move ACTIVE to SUSPENDED with the invoice hold cascade | VendorManager, ComplianceOfficer |
| POST | `/vendors/{id}/reinstate` | Move SUSPENDED to ACTIVE with the resume cascade | VendorManager |
| POST | `/vendors/{id}/reactivate` | Re-screen a DORMANT vendor to ACTIVE / SUSPENDED / BLOCKED | VendorManager |
| POST | `/vendors/{id}/deactivate` | Move ACTIVE, SUSPENDED, or DORMANT to DEACTIVATED | VendorManager |
| POST | `/vendors/{id}/merge` | Absorb a duplicate vendor into this survivor (OCC on survivor) | VendorManager |
| GET | `/vendor-merge-records` | List merge records | All roles |
| GET | `/vendor-merge-records/{id}` | Get one merge record | All roles |
| POST | `/vendors/{id}/bank-accounts` | Add a bank account (OCC on vendor); spawns callback verification | VendorSpecialist |
| GET | `/vendors/{id}/bank-accounts` | List a vendor's bank accounts | All roles |
| GET | `/bank-accounts/{id}` | Get a bank account | All roles |
| POST | `/bank-accounts/{id}/confirm-verification` | Confirm the callback code; verifies the account and applies primary supersede | VendorSpecialist, VendorManager |
| POST | `/bank-accounts/{id}/disable` | Move VERIFIED to DISABLED when not in use | VendorManager |
| GET | `/bank-accounts/{id}/callback-verifications` | List callback verifications for an account (exposes the code) | All roles |
| POST | `/vendors/{id}/documents` | Attach a compliance document (closed-interval overlap gate) | VendorSpecialist |
| GET | `/vendors/{id}/documents` | List a vendor's documents | All roles |
| POST | `/documents/{id}/supersede` | Move a VALID document to SUPERSEDED | VendorSpecialist |
| POST | `/watchlist-entries` | Create an ACTIVE watchlist entry | ComplianceOfficer |
| POST | `/watchlist-entries/{id}/retire` | Move an ACTIVE watchlist entry to RETIRED | ComplianceOfficer |
| GET | `/screening-checks` | List screening checks | All roles |
| GET | `/screening-checks/{id}` | Get a screening check | All roles |
| GET | `/sanctions-cases` | List sanctions review cases | All roles |
| GET | `/sanctions-cases/{id}` | Get a sanctions review case | All roles |
| POST | `/sanctions-cases/{id}/disposition` | Disposition a case: CLEARED reinstates, CONFIRMED_HIT blocks | ComplianceOfficer |
| POST | `/approval-matrix-rules` | Create an ACTIVE approval matrix rule | Controller |
| POST | `/approval-matrix-rules/{id}/retire` | Move an ACTIVE matrix rule to RETIRED | Controller |
| POST | `/invoices` | Create an invoice in RECEIVED for an ACTIVE vendor | APClerk, APSupervisor, APManager |
| GET | `/invoices` | List invoices | All roles |
| GET | `/invoices/{id}` | Get an invoice | All roles |
| PATCH | `/invoices/{id}` | Edit amount, cost center, or number while RECEIVED or REJECTED | APClerk, APSupervisor, APManager |
| POST | `/invoices/{id}/submit` | Move RECEIVED to PENDING_APPROVAL; snapshots required tier | APClerk, APSupervisor, APManager |
| POST | `/invoices/{id}/approve` | Approve the next pending tier; final tier approves the invoice | APSupervisor, APManager, Controller |
| POST | `/invoices/{id}/reject` | Reject at the next pending tier | APSupervisor, APManager, Controller |
| POST | `/invoices/{id}/resubmit` | Move REJECTED to PENDING_APPROVAL; re-snapshots required tier | APClerk, APSupervisor, APManager |
| POST | `/invoices/{id}/cancel` | Move RECEIVED, PENDING_APPROVAL, or REJECTED to CANCELLED | APClerk |
| GET | `/invoices/{id}/approvals` | List an invoice's approval rows across all rounds | All roles |
| POST | `/payment-runs` | Create a DRAFT payment run | TreasuryAnalyst, TreasuryManager |
| GET | `/payment-runs/{id}` | Get a payment run | All roles |
| POST | `/payment-runs/{id}/invoices` | Add an APPROVED invoice to a DRAFT run (payment-time screening first) | TreasuryAnalyst |
| POST | `/payments/{id}/void` | Void a PENDING payment (manual removal) | TreasuryAnalyst |
| POST | `/payment-runs/{id}/compile` | Move DRAFT to COMPILED (requires a non-empty run) | TreasuryAnalyst |
| POST | `/payment-runs/{id}/uncompile` | Move COMPILED back to DRAFT | TreasuryAnalyst |
| POST | `/payment-runs/{id}/approve` | Move COMPILED to APPROVED (SoD-4a) | TreasuryManager |
| POST | `/payment-runs/{id}/revoke-approval` | Move APPROVED back to COMPILED | TreasuryManager |
| POST | `/payment-runs/{id}/release` | Move APPROVED to RELEASED (SoD-4b, snapshot freshness, daily limit) | TreasuryManager |
| POST | `/payment-runs/{id}/positive-pay-acks` | Bank acknowledgement per payment: MATCH clears, MISMATCH voids | BankFileProcessor |
| POST | `/payment-runs/{id}/void` | Move DRAFT or COMPILED to VOIDED; unwinds payments and invoices | TreasuryAnalyst, TreasuryManager |
| GET | `/payment-runs/{id}/payments` | List the payments of a run | All roles |
| GET | `/payments/{id}` | Get a payment | All roles |
| GET | `/payments` | List payments with filters | All roles |
| GET | `/audit-events` | Query the append-only master-data audit trail | VendorManager, ComplianceOfficer, Controller, Auditor |

## 5. Error Code Catalogue

The trigger conditions for each error are defined in §2 and §3; this table is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CALLBACK_LOCKED` | 409 Conflict |
| `ERR_CALLBACK_EXPIRED` | 409 Conflict |
| `ERR_PAYMENT_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_VENDOR_BLOCKED` | 409 Conflict |
| `ERR_SANCTIONS_REVIEW_PENDING` | 409 Conflict |
| `ERR_DUPLICATE_TAX_ID` | 409 Conflict |
| `ERR_DUPLICATE_VENDOR_HARD_BLOCK` | 409 Conflict |
| `ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE` | 403 Forbidden |
| `ERR_SOD_INVOICE_SUBMITTER_CANNOT_APPROVE` | 403 Forbidden |
| `ERR_SOD_SAME_APPROVER_TWO_TIERS` | 403 Forbidden |
| `ERR_SOD_RUN_CREATOR_CANNOT_APPROVE` | 403 Forbidden |
| `ERR_SOD_RUN_CREATOR_CANNOT_RELEASE` | 403 Forbidden |
| `ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM` | 403 Forbidden |
| `ERR_VENDOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_REQUIRED_DOCUMENT_MISSING` | 409 Conflict |
| `ERR_DOCUMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_RULE_RANGE_OVERLAP` | 409 Conflict |
| `ERR_VENDOR_NOT_MERGEABLE` | 409 Conflict |
| `ERR_NO_APPROVAL_RULE` | 409 Conflict |
| `ERR_APPROVAL_TIER_OUT_OF_ORDER` | 409 Conflict |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 Conflict |
| `ERR_BANK_ACCOUNT_NOT_VERIFIED` | 409 Conflict |
| `ERR_BANK_ACCOUNT_IN_USE` | 409 Conflict |
| `ERR_VENDOR_HAS_OPEN_CASE` | 409 Conflict |
| `ERR_VENDOR_HAS_OPEN_INVOICES` | 409 Conflict |
| `ERR_EMPTY_PAYMENT_RUN` | 409 Conflict |
| `ERR_CALLBACK_CODE_MISMATCH` | 409 Conflict |
| `ERR_BANK_CHANGE_COOLING_OFF` | 409 Conflict |
| `ERR_DOCUMENT_EXPIRED` | 409 Conflict |
| `ERR_BANK_SNAPSHOT_STALE` | 409 Conflict |
| `ERR_DAILY_LIMIT_EXCEEDED` | 409 Conflict |
