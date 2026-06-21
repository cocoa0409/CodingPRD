# Accounts Payable Automation API — Product Requirements Document

## 1. Introduction

Accounts payable is where a finance organization quietly leaks money: invoices arrive in inconsistent shapes, get coded to the wrong ledger accounts, slip past approval thresholds, are paid twice, or miss early-payment discounts the vendor was happy to grant. This API exists to close those gaps by automating the full payables lifecycle — from the moment an invoice is captured (often via optical character recognition) through coding, two- and three-way matching against purchase orders and goods receipts, tiered approval, payment-run disbursement across ACH, check, and card rails, and period-end accrual of unbilled receipts.

The system is deliberately built around segregation of duties: the person who codes an invoice must not be the one who approves it, and neither may release the payment run that pays it. Every consequential action is recorded as an audit event, every monetary figure is held in integer cents to avoid rounding drift, and the ledgers that track purchase-order consumption, batch disbursement, and reportable 1099 spend are reconciled the instant the triggering event occurs. The result is a payables engine that an APClerk, an Approver, an APManager, and an Auditor can each operate within their own lane while the platform guarantees the books stay balanced.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API. Unless a later business-logic section states a more specific rule, everything here holds globally. The API is mounted under `/ap`.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they are acting. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `APManager`, `APClerk`, `Approver`, and `Auditor`.

- An `APManager` owns the master data and the money: creating vendors, GL accounts, purchase orders, and approval routes; opening, releasing, settling, and voiding payment batches; adding and removing payments; returning settled payments; and booking and reversing accruals.
- An `APClerk` captures and codes invoices, adds coding lines, runs the match, manages match exceptions, submits invoices for approval, and rejects invoices that are still under coding review. A clerk may not approve invoices and may not release payments.
- An `Approver` acts on individual approval steps — approving or rejecting the lowest pending step. An approver may not code invoices and may not release payments.
- An `Auditor` has read-only visibility across the entire payables surface and performs no mutating operations.

All four roles may perform GET reads across the surface. Capturing invoices and recording or posting goods receipts are shared between `APManager` and `APClerk`.

Every role in this system uses an **opaque** identity model. In each case, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id`. The server does, however, record the acting `X-User-ID` onto entities where a workflow transition writes it — for example as `coded_by` and `approved_by` on an `Invoice`, as `resolved_by` on a `MatchException`, as `acted_by` on an `ApprovalStep`, as `released_by` on a `PaymentBatch`, and as `actor_user_id` on an `AuditEvent`. Segregation-of-duties checks compare these recorded operator identifiers to the current actor's `X-User-ID`; they are not entity-ownership checks.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before collection begins, and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether further pages remain beyond the current window.

### 2.4. Common Resource Properties and Validation Ordering

Most resources in this system are full first-class entities and carry a common set of system-managed fields: an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp in the same format that is refreshed on every mutation, and a `version` integer that starts at 1 and increments by one on every mutation. Vendors, purchase orders, goods receipts, invoices, invoice lines, match exceptions, approval steps, payment batches, payments, and accruals all carry this full set.

A small number of records are lightweight and **do not** carry `updated_at` or `version`; they expose only `id` and `created_at`. This applies to GL accounts, approval routes, and audit events. For those three, treat the absence of `updated_at` and `version` as intentional.

When the server validates a request, it does so in a fixed precedence so that the most fundamental failures surface first. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then authorization of the role for the operation (`ERR_UNAUTHORIZED`), then existence of every resource referenced in the path or body (`ERR_NOT_FOUND`), then well-formedness of the request body — required fields present, correct types, valid enum values (`ERR_INVALID_REQUEST`), and then, for any endpoint that drives a state machine, whether the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`). Only after all of those pass does the server evaluate the domain-specific business rules described throughout Section 3. The existence check is performed left-to-right across the path, so for a nested path the outer resource is confirmed before any inner identifier is examined, and the first missing identifier is what produces the `ERR_NOT_FOUND`.

### 2.5. Monetary Precision and Rounding

All monetary amounts in this system are integers denominated in cents — there are no fractional-cent values stored anywhere. Where a calculation produces a non-integer intermediate (for example, an early-payment discount that is a percentage of a cent total, or a percentage-based match tolerance), the result is rounded to the nearest whole cent using the round-half-up convention, meaning a value exactly halfway between two cents rounds up to the larger cent. The specific point at which rounding is applied matters and is called out per calculation in Section 3; in general, rounding happens once, on the single product, before any subtraction or summation.

### 2.6. Ledger Reconciliation and Derived Amounts

Several entities maintain computed amounts that must always agree with the underlying records that feed them; the system reconciles these immediately whenever a contributing event occurs, rather than on a schedule. A purchase order's `received_amount_cents` is the sum of `received_amount_cents` over that PO's POSTED goods receipts and is recomputed each time a receipt is posted. A purchase order's `matched_amount_cents` is the sum of `total_amount_cents` over that PO's invoices whose status is one of `MATCHED`, `APPROVED`, `SCHEDULED`, or `PAID`, recomputed on every invoice match, approval-driven change, payment, and on the compensating reversals that reopen a rejected or voided invoice. An invoice's `total_amount_cents` is the sum of its lines' `amount_cents`, recomputed whenever a line is added. A payment batch's `total_disbursed_cents` is the sum of its member payments' `net_amount_cents`. A vendor's `ytd_1099_paid_cents` is the running sum of net amounts settled to that vendor in the current year, recomputed on every settlement and adjusted down on a return. When any of these reconciliations changes a parent entity, that parent's `updated_at` is refreshed and its `version` increments.

A purchase order's `status` is itself derived from the ledger: it is `OPEN` until its `matched_amount_cents` reaches or exceeds its `ordered_amount_cents`, at which point it becomes `CLOSED`. Because the reconciliation is immediate, a match that pushes matched spend to the ordered total closes the PO in the same operation, and a compensating reversal that drops matched spend back below the ordered total reopens it.

### 2.7. Cascading State Effects

Many operations in this system touch more than one entity. Whenever a transition's specification names a secondary effect — a parent that closes or reopens, a child invoice that flips to PAID, a vendor's year-to-date figure that moves, a match exception that gets created — that effect is part of the operation and must occur atomically with the primary transition. Section 3 enumerates each cascade in the narrative of the workflow that triggers it. A particularly important pattern is **bubble-up**: a parent entity auto-transitions when its children reach a collective condition, with no separate client request against the parent. When the last approval step on an invoice is approved, the invoice itself bubbles from `PENDING_APPROVAL` to `APPROVED`; when a batch is released, each member invoice bubbles from `SCHEDULED` to `PAID`; when a batch settles, each member payment's settlement axis bubbles from `PENDING` to `SETTLED`. The mirror pattern is **compensation**: when a previously applied ledger effect must be undone — a rejected invoice, a voided batch, a returned payment, a removed scheduled payment — the system reverses the earlier debit or credit so that the conserved quantities (matched amounts, disbursed totals, 1099 year-to-date) return to a state consistent with the records that remain.

### 2.8. Nested Resource Retrieval

Although the entity model is flat — children carry foreign-key fields rather than living under deep URL nesting — several read endpoints expose a child collection beneath a parent identifier (for instance, the goods receipts, accruals, invoices, audit events, match exceptions, approval steps, or payments associated with a given parent). For any such nested read, the parent identifier in the path is validated first; if it does not correspond to an existing resource the request fails with `ERR_NOT_FOUND` before the collection is assembled. These collection reads honor the same pagination and ascending-creation-time ordering described in Section 2.3.

### 2.9. Optimistic Concurrency on Batch Release

Releasing a payment batch is the one operation in this system guarded by optimistic concurrency control, because between the moment an operator reviews a batch and the moment they release it, another writer may have added or removed a payment — and every such mutation bumps the batch's `version` and changes its `total_disbursed_cents`. To prevent releasing a batch whose contents and disbursed total are no longer what the releaser believes, the release request must include `expected_paymentbatch_version` as a required field carrying the `version` the client last observed for that batch. If that value does not equal the batch's current `version`, the release is rejected with `ERR_STALE_BATCH_VERSION` and an HTTP status of 412, signaling that the client must re-read the batch before releasing it. No other endpoint in the system takes a version field; release is the sole OCC-guarded write.

## 3. Business Logic & Workflows

### 3.1. Master Data: Vendors, GL Accounts, Purchase Orders, and Approval Routes

Before any invoice can flow, an `APManager` establishes the master data the rest of the system references. A **vendor** is created with a `legal_name` and a default disbursement rail in `payment_method`, which must be one of `ACH`, `CHECK`, or `CARD`. A vendor may be flagged as a reportable 1099 vendor via the `is_1099` boolean, which defaults to false; when `is_1099` is true, a non-empty `tax_id` must be supplied at creation, and a creation that sets the flag without a tax identifier is rejected with `ERR_TAX_ID_REQUIRED`. For non-1099 vendors the `tax_id` is optional. A vendor may advertise an early-payment discount through `early_pay_terms_pct` (a fractional rate such as 0.02 for two percent, defaulting to 0 when none is offered) paired with `early_pay_window_days`, the number of days from the invoice date within which paying earns that discount (defaulting to 0). The vendor's `net_terms_days` (defaulting to 30) governs how far after the invoice date payment is due. A new vendor begins life with a `status` of `ACTIVE` and a `ytd_1099_paid_cents` of 0, both system-managed.

A vendor's `status` toggles between `ACTIVE` and `ON_HOLD`. An `APManager` may place a vendor on hold or release the hold by supplying an `on_hold` boolean; when `on_hold` is true the vendor moves to `ON_HOLD`, and when false it returns to `ACTIVE`.

A **GL account** is created with a `code` (a string that must be unique across all GL accounts; a creation whose `code` collides with an existing GL account is rejected with `ERR_INVALID_REQUEST`), a `name`, and an `is_postable` boolean that defaults to true. Non-postable accounts are roll-up parents to which invoice and accrual lines may never post; only postable accounts are valid coding targets.

A **purchase order** is raised against a vendor by supplying that `vendor_id`, a default `gl_account_code` that matched invoice lines will code against (which must reference a postable GL account), and an `ordered_amount_cents` total that must be at least 1. The PO is created `OPEN` with both its computed `received_amount_cents` and `matched_amount_cents` initialized to 0. An entirely absent `gl_account_code` field fails the required-field check with `ERR_INVALID_REQUEST` (per the Section 2.4 precedence); a `gl_account_code` that is present but references no GL account or references a non-postable account is rejected with `ERR_GL_ACCOUNT_NOT_POSTABLE`.

An **approval route** defines one tier of the approval ladder, specified by an inclusive lower bound `min_amount_cents` (at least 0), an exclusive upper bound `max_amount_cents` (a large sentinel is used for the top tier; `max_amount_cents` must be strictly greater than `min_amount_cents`, and a creation that violates this is rejected with `ERR_INVALID_REQUEST`), and `required_levels`, the number of sequential approver sign-offs that an invoice falling in this tier requires (at least 1). Tiers must not overlap; conceptually each tier owns the half-open cent interval from its lower bound up to but not including its upper bound. Non-overlap is a modeling expectation only — route creation validates each tier's bounds in isolation and does not reject a new tier for overlapping an existing one, so the caller is responsible for supplying a disjoint tier table.

### 3.2. Receiving Goods Against a Purchase Order

Goods receipts record what has physically arrived against a purchase order, and they are the basis of three-way matching. Either an `APClerk` or an `APManager` records a receipt by supplying the `po_id` it is received against, a `received_amount_cents` value (at least 1) representing the value of goods received, a `received_date` marking the start of the delivery window, and an optional `coverage_days` (at least 1, defaulting to 1) giving the length in days of that window. A receipt occupies the half-open interval that begins at its received date and ends `coverage_days` later — the end instant itself is excluded. A new receipt is created in `DRAFT`.

Posting a receipt moves it from `DRAFT` to `POSTED` and is what makes it count toward matching. On posting, the parent purchase order's `received_amount_cents` is recomputed as the sum across all of that PO's POSTED receipts. A receipt may not be posted against a `CLOSED` purchase order; such an attempt is rejected with `ERR_PO_CLOSED`. Posting is also blocked when the new receipt's half-open coverage window would overlap the window of any receipt already POSTED on the same PO; because the interval is half-open, mere adjacency — where one window's end instant equals the next window's start instant — is permitted and does not count as an overlap, but any true overlap is rejected with `ERR_RECEIPT_WINDOW_OVERLAP`.

### 3.3. Capturing and Coding Invoices

An invoice enters the system through capture — typically the output of OCR. An `APClerk` or `APManager` captures it by supplying the issuing `vendor_id`, an optional `po_id` (the purchase order it bills against, left absent for non-PO invoices), the vendor-supplied `invoice_number`, the `invoice_date`, and an optional `ocr_confidence` between 0.0 and 1.0 that defaults to 1.0. At capture the system computes the invoice's `due_date` as the invoice date advanced by the vendor's net terms, and its `discount_deadline` as the invoice date advanced by the vendor's early-pay window — but only when the vendor actually offers a discount; when the vendor offers none, the discount deadline is left null. The system also fixes the `match_type`: it is `NON_PO` when no PO is referenced; when a PO is referenced, it is `THREE_WAY` if that PO has at least one POSTED goods receipt at capture time and `TWO_WAY` if it has none.

Capture normally lands the invoice in `CAPTURED`. There is one exception driven by capture quality: if `ocr_confidence` is below the confidence floor of 0.80, the captured invoice is instead placed directly into `CODING_REVIEW`, forcing manual review before coding can be finalized. The invoice's `total_amount_cents` begins at 0 and its `variance_cents` at 0; `coded_by` and `approved_by` are null until the respective actions occur. The full status vocabulary an invoice may occupy is `CAPTURED`, `CODING_REVIEW`, `MATCHED`, `PENDING_APPROVAL`, `APPROVED`, `SCHEDULED`, `PAID`, and `REJECTED`, the last of which is terminal.

Coding is the act of assigning the invoice's spend to ledger accounts. An `APClerk` adds one or more coding lines, each carrying the `gl_account_code` the spend posts to (which must reference a postable GL account), an `amount_cents` of at least 1, and an optional `description`. Each line belongs to its invoice via `invoice_id`. Adding a line that codes to a missing or non-postable GL account is rejected with `ERR_GL_ACCOUNT_NOT_POSTABLE`. Every time a line is added, the invoice's `total_amount_cents` is recomputed as the sum of its lines' amounts.

### 3.4. The Match and Its Exceptions

Once an invoice has been lined out, the `APClerk` runs the match, which finalizes coding. The match may be run on an invoice that is in `CAPTURED` or, after a revision loop, in `CODING_REVIEW`. Running the match requires the invoice to have at least one line and a `total_amount_cents` greater than 0, requires its `ocr_confidence` to be at or above the 0.80 floor when leaving `CAPTURED`, and requires that no other invoice already exists with the same combination of `vendor_id` and `invoice_number` — the duplicate-detection check, which on collision rejects the match with `ERR_DUPLICATE_INVOICE`. When the match is run on an invoice already in `CODING_REVIEW`, it additionally requires that every match exception attached to that invoice has reached a non-`PENDING` resolution; if any exception is still pending, the match is rejected with `ERR_EXCEPTION_UNRESOLVED`. On a successful match the system computes the match type and the variance, records the acting operator into `coded_by`, and appends a `CODED` audit event.

The variance computation depends on the match type, and the dual interpretation is the heart of matching. For a `NON_PO` invoice there is nothing to match against, so the variance is 0. For a `TWO_WAY` invoice the variance is the invoice's `total_amount_cents` minus the purchase order's `ordered_amount_cents` — billed against ordered. For a `THREE_WAY` invoice the variance is the invoice's `total_amount_cents` minus the purchase order's `received_amount_cents` — billed against what was actually received, where the received basis (drawn only from POSTED goods receipts) can differ from the ordered basis and so can produce a different variance for otherwise identical invoice data. The variance recorded on the invoice may be negative (an under-bill) or positive (an over-bill).

Whether that variance breaches tolerance decides the branch. The tolerance is computed as the larger of an absolute floor of 1000 cents and the purchase order's `ordered_amount_cents` multiplied by a percentage tolerance of 0.02, with that percentage product rounded half-up to the nearest cent. The variance breaches tolerance only when its absolute magnitude is strictly greater than the tolerance; a magnitude exactly equal to the tolerance is within tolerance. When the variance is within tolerance, the invoice transitions to `MATCHED`, the parent PO's `matched_amount_cents` is recomputed (which may close the PO), and matching is complete. When the variance breaches tolerance, instead of advancing to `MATCHED` the invoice is held in `CODING_REVIEW` and a match exception is created in `PENDING`: its `reason` is `PRICE_VARIANCE` for a `TWO_WAY` breach and `QTY_VARIANCE` for a `THREE_WAY` breach, and its `variance_cents` is copied from the invoice's variance at creation. A match exception references its invoice via `invoice_id`, and its `resolution` enumerates `PENDING`, `RESOLVED`, `WRITTEN_OFF`, and `ESCALATED`, with `resolved_by` left null until a terminal resolution is set.

A clerk clears a pending exception in one of three mutually exclusive ways, each of which records the acting operator into `resolved_by` and is permitted only while the exception is still `PENDING` and its invoice remains in `CODING_REVIEW`. **Resolving** the exception accepts the variance as-is, moves the resolution to `RESOLVED`, leaves the invoice's variance untouched, and appends an `EXCEPTION_RESOLVED` audit event. **Writing off** the exception is permitted only when its `variance_cents` is at or below the write-off ceiling of 5000 cents; it moves the resolution to `WRITTEN_OFF`, zeroes the linked invoice's `variance_cents` (the write-off absorbs the variance, which distinguishes it from a plain resolve), and appends an `EXCEPTION_WRITTEN_OFF` audit event. A write-off attempted on a variance above the 5000-cent ceiling is rejected with `ERR_WRITEOFF_LIMIT_EXCEEDED`. **Escalating** the exception is permitted only when its `variance_cents` is strictly greater than the 5000-cent ceiling; it moves the resolution to `ESCALATED` and appends an `EXCEPTION_ESCALATED` audit event. The escalate and write-off branches are exact complements at the ceiling: a variance at or below 5000 cents must be written off rather than escalated, and an escalate attempted at or below the ceiling is rejected with `ERR_ESCALATE_BELOW_CEILING`. Once every exception on the invoice is non-pending, the clerk re-runs the match, which recomputes the match type and variance, records `coded_by`, advances the invoice to `MATCHED`, recomputes the PO's matched amount (possibly closing the PO), and appends a `CODED` event — closing the revision loop. An invoice sitting in `CODING_REVIEW` may instead be abandoned: a clerk may reject it outright, moving it to `REJECTED` and appending a `REJECTED` audit event.

### 3.5. Tiered Approval

A `MATCHED` invoice is submitted for approval by an `APClerk`. Submission is permitted only from `MATCHED`, and it additionally requires that none of the invoice's match exceptions remain pending (a still-pending exception blocks submission with `ERR_EXCEPTION_UNRESOLVED`). On submission the system selects the approval tier for the invoice and builds the approval chain. The tier is the single approval route whose half-open cent interval contains the invoice's `total_amount_cents` — that is, the route whose lower bound is at or below the total while the total is strictly below the route's upper bound; should more than one route match (because the tier table was not kept disjoint), the first matching route in route-creation order is the one used. From that tier's `required_levels` the system creates that many approval steps, numbered with a 1-based `level` from 1 up to the required count, each starting `PENDING`, each linked to the invoice by `invoice_id`. The invoice then moves to `PENDING_APPROVAL` and a `SUBMITTED` audit event is appended. If no approval route covers the invoice total — a gap in the tier table — submission is rejected with `ERR_NO_APPROVAL_ROUTE`. When the matching tier requires a single level, exactly one step is created; when it requires two or more, the steps are sequential and a higher level cannot be acted upon until the level beneath it is approved.

Approvers act on the steps one at a time. An approval step carries a `status` of `PENDING`, `APPROVED`, or `REJECTED` and records the acting operator into `acted_by` once acted upon. A step may be acted on only if it is the lowest-level pending step for its invoice and the parent invoice is still in `PENDING_APPROVAL`; acting on a step that is not the lowest pending step is rejected with `ERR_APPROVAL_OUT_OF_ORDER`. Approving a step sets it to `APPROVED` and records `acted_by`. If the approved step is the highest level on the invoice, the invoice bubbles up from `PENDING_APPROVAL` to `APPROVED`: the operator who approved that final step is recorded into the invoice's `approved_by`, and an `APPROVED` audit event is appended. Rejecting a step is the destructive branch: the targeted step moves to `REJECTED` with `acted_by` recorded, every higher-level still-pending step on the same invoice is cascaded to `REJECTED`, the invoice itself moves to `REJECTED`, and the match-time ledger debit is compensated by decrementing the parent purchase order's `matched_amount_cents` by this invoice's total (reopening the PO if it had closed). A `REJECTED` audit event is appended. This compensation keeps the matched-amount ledger conserved when an approved-and-matched invoice is ultimately turned away.

### 3.6. Payment Runs: Building, Releasing, Settling, Voiding

Disbursement happens through payment batches, each representing one run on one rail. An `APManager` opens a batch by supplying its `payment_method` (one of `ACH`, `CHECK`, or `CARD`) and a `run_date`, the effective disbursement date against which each member invoice's discount eligibility is evaluated. A new batch is `BUILDING` with `total_disbursed_cents` at 0 and `released_by` null. A batch's `status` ranges over `BUILDING`, `RELEASED`, `SETTLED`, and `VOID`.

While a batch is `BUILDING`, the manager adds an `APPROVED` invoice to it by supplying that `invoice_id`. Adding the invoice creates a payment that links the run via `batch_id` and the invoice via `invoice_id`, copies the invoice's `total_amount_cents` into the payment's `gross_amount_cents`, computes the early-pay `discount_taken_cents` and the resulting `net_amount_cents`, moves the invoice from `APPROVED` to `SCHEDULED`, recomputes the batch's `total_disbursed_cents`, increments the batch's `version` by one, and appends a `SCHEDULED` audit event. An invoice may only be added when it is `APPROVED` and its vendor's `status` is `ACTIVE`. Several guards protect this step: the invoice's vendor must use the same disbursement rail as the batch, or the addition is rejected with `ERR_PAYMENT_METHOD_MISMATCH`; a vendor that is `ON_HOLD` cannot be paid, and an attempt is rejected with `ERR_VENDOR_ON_HOLD`; and an invoice may appear in at most one payment across all non-`VOID` batches, so adding an invoice that already has a live payment is rejected with `ERR_INVOICE_ALREADY_SCHEDULED` to prevent double payment. A payment also tracks a parallel `settlement_status` of `PENDING`, `SETTLED`, or `RETURNED`, beginning `PENDING`.

Before release, the manager may remove a payment from a `BUILDING` batch. Removal deletes the payment, reverts its invoice from `SCHEDULED` back to `APPROVED`, recomputes the batch's `total_disbursed_cents`, increments the batch's `version` by one, and appends an `UNSCHEDULED` audit event.

Releasing the batch is the consequential, OCC-guarded step. It requires the supplied `expected_paymentbatch_version` to match the batch's current `version` (a mismatch is rejected with `ERR_STALE_BATCH_VERSION`), requires the batch to hold at least one payment (an empty batch is rejected with `ERR_BATCH_EMPTY`), and enforces segregation of duties: the releasing operator's `X-User-ID` must not equal the `coded_by` or `approved_by` of any member invoice, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. These three release-time checks are evaluated in exactly the textual order just given: the OCC version match is tested first, then the non-empty requirement, then segregation of duties. When more than one of these conditions would fail on the same release, the first in that order is the one reported — so a stale version is reported even if the batch is also empty or would also violate segregation of duties, and an empty batch is reported ahead of a segregation-of-duties violation. On release the batch records `released_by`, freezes its `total_disbursed_cents`, moves to `RELEASED`, bubbles every member invoice from `SCHEDULED` to `PAID` (appending a `PAID` audit event per invoice), and increments its `version` by one.

A `RELEASED` batch may be settled or voided. **Settling** cascades each member payment's `settlement_status` from `PENDING` to `SETTLED`, and for each settled payment recomputes the recipient vendor's `ytd_1099_paid_cents` by adding the payment's net amount, then moves the batch to `SETTLED`. **Voiding** is the compensating reverse of a release that has not yet settled: it cascades every member invoice from `PAID` back to `APPROVED`, deletes all member payments, drives the batch's `total_disbursed_cents` to 0, moves the batch to `VOID`, and appends a `PAYMENT_VOIDED` audit event; settlement is not involved because void only applies before any funds settle.

After settlement, an individual settled payment may be returned by the manager. Returning is permitted only when the payment's `settlement_status` is `SETTLED` and its parent batch is `SETTLED`; it moves the payment's `settlement_status` to `RETURNED`, reverses the paid invoice from `PAID` back to `APPROVED`, and subtracts the payment's net amount from the vendor's `ytd_1099_paid_cents` to keep the year-to-date figure conserved, appending a `PAYMENT_RETURNED` audit event. The settlement axis thus evolves independently of the invoice lifecycle: a payment can be `PENDING`, `SETTLED`, or `RETURNED` on its own track while its invoice walks its own status path.

### 3.7. Discount, Net, and Batch-Total Computation

When a payment is added to a batch, its discount and net are computed and then the batch total is re-derived; the discount is also re-evaluated on release. The discount keys on the batch's `run_date` against the invoice's `discount_deadline`. If the vendor's `early_pay_terms_pct` is 0 or the invoice's `discount_deadline` is null, no discount applies and `discount_taken_cents` is 0. Otherwise, when the run date falls on or before the discount deadline — paying exactly on the deadline still earns the discount — the discount is the invoice's `total_amount_cents` multiplied by the vendor's `early_pay_terms_pct`, with that single product rounded half-up to the nearest cent. When the run date falls after the deadline, no discount applies and `discount_taken_cents` is 0. In every case the payment's `net_amount_cents` is its `gross_amount_cents` minus its `discount_taken_cents`; the rounding is applied to the discount product before the subtraction, never per line.

A batch's `total_disbursed_cents` is the plain sum of its member payments' already-rounded `net_amount_cents`, taken over every payment whose `batch_id` is this batch with no status filter — every member counts while the batch is building. Because each net amount was rounded once at the time its payment was added, the batch total is a sum of rounded integers (sum-of-rounded), not a rounding of an unrounded sum. The total is recomputed whenever a payment is added or removed and is frozen at the value it holds when the batch is released.

### 3.8. Period-End Accruals

At period close an `APManager` books an accrual to estimate the value of goods received against a purchase order but not yet billed by an invoice. An accrual is booked by supplying the `po_id`, a `period_label` (such as a year-month string), a `period_start`, and a `period_end`, where the period occupies the closed interval from start to end inclusive and the end must be on or after the start. Booking computes the estimate and creates the accrual in `BOOKED` with `final_cents` left at 0. The booked `estimated_cents` is the greater of 0 and the purchase order's `received_amount_cents` minus its `matched_amount_cents` — the unbilled receipt gap as of booking, never allowed to go negative.

Because the accrual period is a closed interval, an accrual may not be booked when its period interval overlaps that of any existing `BOOKED` accrual on the same PO; since both endpoints are inclusive, even sharing a single endpoint date counts as an overlap (no adjacency is permitted), and such an attempt is rejected with `ERR_ACCRUAL_PERIOD_OVERLAP`.

Reversing an accrual performs the chronological true-up: it computes `final_cents` as the greater of 0 and the same difference — the purchase order's `received_amount_cents` minus its `matched_amount_cents` — but recomputed from those two fields as they stand at reversal time, then moves the accrual to `REVERSED`. The final figure diverges from the original estimate precisely when invoices matched against the PO between booking and reversal, since matching moves the matched amount and thus narrows the unbilled gap.

### 3.9. The Audit Trail

Every consequential transition on an invoice is recorded as an audit event linked to that invoice via `invoice_id`. Each event carries a system-assigned `event_type` label (for example `CODED`, `SUBMITTED`, `APPROVED`, `REJECTED`, `SCHEDULED`, `UNSCHEDULED`, `PAID`, `PAYMENT_VOIDED`, `PAYMENT_RETURNED`, `EXCEPTION_RESOLVED`, `EXCEPTION_WRITTEN_OFF`, or `EXCEPTION_ESCALATED`) and the `actor_user_id` of the operator whose action produced it. Audit events are immutable once written and are exposed as a read-only chronological trail per invoice, available to every role.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions, posts, releases, and reversals — return `200 OK`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/ap/vendors` | Create a vendor | APManager |
| GET    | `/ap/vendors/{id}` | Fetch a vendor | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/vendors/{id}/hold` | Place a vendor on hold or release the hold | APManager |
| POST   | `/ap/gl-accounts` | Create a GL account | APManager |
| POST   | `/ap/purchase-orders` | Raise a purchase order against a vendor | APManager |
| GET    | `/ap/purchase-orders/{id}` | Fetch a purchase order with computed received/matched amounts | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/purchase-orders` | List purchase orders; filter by vendor_id | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/purchase-orders/{id}/goods-receipts` | List goods receipts for this PO | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/purchase-orders/{id}/accruals` | List accruals booked for this PO | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/purchase-orders/{id}/invoices` | List invoices billed against this PO | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/goods-receipts` | Record a goods receipt (DRAFT) against a PO | APClerk, APManager |
| POST   | `/ap/goods-receipts/{id}/post` | Post a goods receipt; updates PO received amount | APClerk, APManager |
| GET    | `/ap/goods-receipts/{id}` | Fetch a goods receipt | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/invoices` | Capture an invoice | APClerk, APManager |
| GET    | `/ap/invoices/{id}` | Fetch an invoice with computed totals and variance | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/invoices` | List invoices; filter by vendor_id, po_id, or status | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/invoices/{id}/lines` | Add a coding line to an invoice | APClerk |
| GET    | `/ap/invoices/{id}/lines` | List an invoice's coding lines | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/invoices/{id}/code` | Run the match and finalize coding | APClerk |
| POST   | `/ap/invoices/{id}/submit-approval` | Submit a matched invoice for approval | APClerk |
| POST   | `/ap/invoices/{id}/reject` | Reject an invoice still under coding review | APClerk |
| GET    | `/ap/invoices/{id}/audit-events` | List audit events for an invoice | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/invoices/{id}/match-exceptions` | List match exceptions for an invoice | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/invoices/{id}/approval-steps` | List approval steps for an invoice | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/match-exceptions/{id}` | Fetch a match exception | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/match-exceptions/{id}/resolve` | Accept the variance and resolve the exception | APClerk |
| POST   | `/ap/match-exceptions/{id}/write-off` | Write off a small variance | APClerk |
| POST   | `/ap/match-exceptions/{id}/escalate` | Escalate a large variance | APClerk |
| POST   | `/ap/approval-routes` | Define an approval tier | APManager |
| GET    | `/ap/approval-steps/{id}` | Fetch an approval step | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/approval-steps/{id}/approve` | Approve the lowest-level pending step | Approver |
| POST   | `/ap/approval-steps/{id}/reject` | Reject the lowest-level pending step | Approver |
| POST   | `/ap/payment-batches` | Open a payment run for a rail | APManager |
| GET    | `/ap/payment-batches/{id}` | Fetch a payment batch | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/payment-batches/{id}/payments` | Add an approved invoice to the run as a payment | APManager |
| GET    | `/ap/payment-batches/{id}/payments` | List payments in a batch | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/payment-batches/{id}/release` | Release the run | APManager |
| POST   | `/ap/payment-batches/{id}/settle` | Settle a released run | APManager |
| POST   | `/ap/payment-batches/{id}/void` | Void a released-but-unsettled run | APManager |
| GET    | `/ap/payments/{id}` | Fetch a payment | APManager, APClerk, Approver, Auditor |
| GET    | `/ap/payments` | List payments; filter by invoice_id | APManager, APClerk, Approver, Auditor |
| DELETE | `/ap/payments/{id}` | Remove a payment from a building batch | APManager |
| POST   | `/ap/payments/{id}/return` | Mark a settled payment as returned | APManager |
| POST   | `/ap/accruals` | Book a period-end accrual estimate for a PO | APManager |
| GET    | `/ap/accruals/{id}` | Fetch an accrual | APManager, APClerk, Approver, Auditor |
| POST   | `/ap/accruals/{id}/reverse` | Reverse an accrual with a final true-up | APManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TAX_ID_REQUIRED` | 422 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_GL_ACCOUNT_NOT_POSTABLE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PAYMENT_METHOD_MISMATCH` | 422 |
| `ERR_VENDOR_ON_HOLD` | 409 |
| `ERR_INVOICE_ALREADY_SCHEDULED` | 409 |
| `ERR_WRITEOFF_LIMIT_EXCEEDED` | 422 |
| `ERR_EXCEPTION_UNRESOLVED` | 409 |
| `ERR_APPROVAL_OUT_OF_ORDER` | 409 |
| `ERR_STALE_BATCH_VERSION` | 412 |
| `ERR_NO_APPROVAL_ROUTE` | 422 |
| `ERR_PO_CLOSED` | 409 |
| `ERR_ESCALATE_BELOW_CEILING` | 422 |
| `ERR_BATCH_EMPTY` | 409 |
| `ERR_RECEIPT_WINDOW_OVERLAP` | 409 |
| `ERR_ACCRUAL_PERIOD_OVERLAP` | 409 |
